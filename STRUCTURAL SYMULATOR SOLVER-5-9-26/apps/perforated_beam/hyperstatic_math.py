"""
hyperstatic_math.py — statically INDETERMINATE beam solver for the
Perforated Beam / Cellular Beam tab.

perforated_beam_math.py solves a determinate 2-support beam in closed
form by superposition. That is exact and fast, but it cannot represent a
continuous (multi-span) beam or a built-in end, which is what most real
long-span cellular beams actually are. This module adds that case
without disturbing the closed-form path: a direct-stiffness
(Euler-Bernoulli) solve on a 1-D mesh, used ONLY when the user asks for
supports the closed-form kernel cannot express.

UNITS: mm, N, MPa, N*mm -- identical to perforated_beam_math.py.

WHY A MESH AND NOT MORE CLOSED FORM
-----------------------------------
A perforated beam is not prismatic: `net_I_at` already reports a reduced
I(x) inside every opening. For a determinate beam that variation changes
only the deflection, never V or M, so closed-form statics stays exact.
For an indeterminate beam the redundant reactions depend on the
stiffness distribution, so I(x) changes the internal forces too. A mesh
with one EI per element is the honest way to carry that; each element
takes its EI from `net_I_at` at its own midpoint.

TWO-STAGE RECOVERY (why V/M are not read off the elements)
----------------------------------------------------------
The stiffness solve is used for ONE thing: finding the redundant
reactions. Once every reaction is known the beam is statically
determinate, so V(x) and M(x) are then recovered by plain equilibrium
integration from the left end -- exact, mesh-independent, and using the
same division-free trapezoid algebra as the closed-form path. This
matters: element-end forces would inherit the discretization error of
the Hermite shape functions and would be visibly wrong inside a
distributed load. Equilibrium recovery has no such error, so the only
approximation left in V/M is the reaction values themselves, which
converge quickly with mesh refinement.

SIGN CONVENTIONS (chosen to match perforated_beam_math.py exactly)
------------------------------------------------------------------
  * transverse load / deflection: POSITIVE DOWN
  * reaction force: reported POSITIVE UP (as `reactions()` does)
  * bending moment: positive sagging; an applied point moment M0 (+CCW)
    adds +M0 to M(x) for x > a, matching `_moment_diagram`
  * reaction couple at a fixed support: reported +CCW, so it enters M(x)
    exactly like an applied point moment

Note that "+CCW" here is CCW *in this module's own y-down frame*, which
is clockwise when drawn on a conventional y-up axis. That is not a wart
introduced by the mesh: it is already the convention `_moment_diagram`
implements (an applied +M0 there produces RA = -M0/span, which is the
y-down sense), and it makes the nodal rotation DOF theta = dv/dx
directly conjugate to the module's own moment sign, with no flip needed
anywhere. `test_hyperstatic_math.py` pins this down by requiring the
2-pin case to reproduce the closed-form kernel.

CONDITIONING: the rotation DOFs are scaled by a characteristic length
`Lc` before the solve (theta' = theta / Lc). Without it the translational
and rotational rows differ in magnitude by ~Lc^2, and since a beam
stiffness matrix is already O(n^4)-conditioned, a few hundred elements
was enough to lose most of the significant digits in the recovered
reactions -- visible as an error that GREW with mesh refinement. The
scaling is undone on the way out, so nothing outside this function sees
it.

STATION CONVENTION: this module reports the RIGHT-HAND limit at a
support (a reaction at x is included in V(x)/M(x) at exactly x). The
closed-form path uses the left-hand limit. The difference only shows AT
a support station, and the right-hand limit is the one that matters
here: it is what makes M(0) report the built-in moment of a fixed end
instead of zero. The closed-form path is left untouched.

DEPENDENCIES: standard library only (`math`, `dataclasses`), same as the
rest of this tab -- the banded solver below exists so that no numpy
dependency is introduced for a system this structured. See MANIFESTO §2.
"""
import math
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────────────────
# 1. Support description
# ─────────────────────────────────────────────────────────────────────────

PIN = 'pin'
ROLLER = 'roller'
FIXED = 'fixed'
SUPPORT_KINDS = (PIN, ROLLER, FIXED)


@dataclass
class SupportSpec:
    """One support at station `x`.

    `kind`:
      'pin' / 'roller' -- restrains vertical deflection only. These are
          the SAME restraint in this model and are deliberately not
          distinguished: the beam is analysed for bending (and torsion)
          only, with no axial degree of freedom, so the horizontal
          restraint that separates a real pin from a real roller has
          nothing to act on. Both labels are accepted because both are
          what an engineer would naturally type; neither changes a
          single computed number.
      'fixed' -- restrains vertical deflection AND rotation (built-in /
          empotrado end). This is what introduces a reaction COUPLE.

    `torsion_restrained` controls whether this support also forks/holds
    the section against twist. It defaults to True, matching the
    forked-end assumption the closed-form path already makes at both of
    its supports."""
    x: float
    kind: str = PIN
    torsion_restrained: bool = True

    def __post_init__(self):
        k = str(self.kind).strip().lower()
        if k not in SUPPORT_KINDS:
            raise ValueError(
                f'Unknown support kind {self.kind!r} at x={self.x:g} mm. '
                f'Use one of: {", ".join(SUPPORT_KINDS)}.')
        self.kind = k
        self.x = float(self.x)

    @property
    def restrains_rotation(self):
        return self.kind == FIXED


def normalize_supports(specs, L):
    """Sorts, validates and returns the support list, or raises with a
    message that says what is actually wrong with the arrangement.

    Refuses the arrangements that leave an unrestrained rigid-body motion,
    because a bare 'matrix is singular' from the solver is useless to the
    person who typed the supports in."""
    if not specs:
        raise ValueError('A beam needs at least one support.')
    out = sorted(specs, key=lambda s: s.x)
    for s in out:
        if not (-1e-9 <= s.x <= L + 1e-9):
            raise ValueError(
                f'Support at x={s.x:g} mm lies outside the beam (0 to {L:g} mm).')
    for a, b in zip(out, out[1:]):
        if abs(b.x - a.x) < 1e-6:
            raise ValueError(
                f'Two supports share the station x={a.x:g} mm. Merge them into one '
                '(a duplicated support adds no restraint and makes the system singular).')
    n_fixed = sum(1 for s in out if s.restrains_rotation)
    if len(out) == 1 and n_fixed == 0:
        raise ValueError(
            f'A single pin/roller at x={out[0].x:g} mm leaves the beam free to rotate '
            'about it -- the beam would spin. Add a second support, or make this one '
            'fixed (a cantilever).')
    return out


def degree_of_indeterminacy(specs):
    """Number of redundant reaction components: every vertical restraint
    plus every rotational one, less the 2 equations of planar bending
    equilibrium (sum of vertical forces, sum of moments). Axial
    equilibrium is not counted because no axial DOF is modelled (see
    SupportSpec)."""
    n = len(specs) + sum(1 for s in specs if s.restrains_rotation)
    return n - 2


def is_hyperstatic(specs):
    """True when the arrangement carries more restraints than planar
    bending statics can resolve on its own -- i.e. when the stiffness
    solve is genuinely needed rather than merely used."""
    return degree_of_indeterminacy(specs) > 0


# ─────────────────────────────────────────────────────────────────────────
# 2. Banded symmetric linear solver (stdlib-only)
# ─────────────────────────────────────────────────────────────────────────

def _banded_cholesky(A, n, bw):
    """In-place Cholesky of a symmetric positive-definite banded matrix.

    `A` is upper-band storage: A[i][k] holds K[i][i+k] for k in 0..bw. A
    beam stiffness matrix with DOFs numbered (v0, th0, v1, th1, ...) has
    bw = 3, so this runs in O(n * bw^2) instead of the O(n^3) a dense
    solve would cost -- which is what makes a few-hundred-element mesh
    tractable in pure Python.

    No pivoting: the assembled-and-restrained matrix is SPD whenever the
    beam is properly supported, so a non-positive pivot means a
    MECHANISM, not a numerical accident -- and that is what the error
    says."""
    for i in range(n):
        for k in range(bw + 1):
            j = i + k
            if j >= n:
                break
            s = A[i][k]
            for m in range(max(0, i - bw), i):
                ki, kj = i - m, j - m
                if ki <= bw and kj <= bw:
                    s -= A[m][ki] * A[m][kj]
            if k == 0:
                if s <= 0.0:
                    raise ValueError(
                        'The support arrangement leaves the beam free to move as a rigid '
                        'body (the stiffness matrix is singular). Check that the supports '
                        'actually restrain the beam -- a single pin/roller, or every '
                        'support at the same station, will do this.')
                A[i][0] = math.sqrt(s)
            else:
                A[i][k] = s / A[i][0]
    return A


def _banded_solve(R, b, n, bw):
    """Solves (R^T R) x = b for the Cholesky factor produced above."""
    y = list(b)
    for i in range(n):                      # forward substitution: R^T y = b
        s = y[i]
        for m in range(max(0, i - bw), i):
            s -= R[m][i - m] * y[m]
        y[i] = s / R[i][0]
    x = y
    for i in range(n - 1, -1, -1):          # back substitution: R x = y
        s = x[i]
        for k in range(1, bw + 1):
            j = i + k
            if j >= n:
                break
            s -= R[i][k] * x[j]
        x[i] = s / R[i][0]
    return x


# ─────────────────────────────────────────────────────────────────────────
# 3. Mesh
# ─────────────────────────────────────────────────────────────────────────

def _breakpoints(beam, supports):
    """Every station the mesh MUST place a node on: the beam ends, each
    support, each concentrated action (so it lands on a node and needs no
    shape-function smearing), each distributed-load boundary, and each
    opening edge (so no element straddles the I(x) step)."""
    L = float(beam.L)
    pts = {0.0, L}
    for s in supports:
        pts.add(float(s.x))
    for pl in beam.point_loads:
        pts.add(float(pl.x))
    for pm in beam.point_moments:
        pts.add(float(pm.x))
    for pt in beam.point_torques:
        pts.add(float(pt.x))
    for dl in beam.dist_loads:
        pts.add(float(dl.x1))
        pts.add(float(dl.x2))
    for dt in beam.dist_torques:
        pts.add(float(dt.x1))
        pts.add(float(dt.x2))
    for op in getattr(beam, 'openings', []):
        x0, x1 = op.x_span()
        pts.add(float(x0))
        pts.add(float(x1))
    return sorted(p for p in pts if -1e-9 <= p <= L + 1e-9)


def build_mesh(beam, supports, target_elements=160):
    """Node stations: every breakpoint, with each gap subdivided so no
    element is longer than roughly L/target_elements. The subdivision is
    what makes the redundants converge; the breakpoints are what keep
    each element's EI and loading uniform enough for that to be true."""
    bps = _breakpoints(beam, supports)
    L = float(beam.L)
    h_max = L / max(target_elements, 4)
    nodes = [bps[0]]
    for a, b in zip(bps, bps[1:]):
        gap = b - a
        if gap <= 1e-9:
            continue
        n_sub = max(1, int(math.ceil(gap / h_max)))
        for i in range(1, n_sub + 1):
            nodes.append(a + gap * i / n_sub)
    return nodes


# ─────────────────────────────────────────────────────────────────────────
# 4. Bending solve
# ─────────────────────────────────────────────────────────────────────────

def _ramp_value(dl, x):
    """Intensity of a trapezoidal load at x, or 0 outside its extent."""
    if x < dl.x1 - 1e-9 or x > dl.x2 + 1e-9:
        return 0.0
    d = dl.x2 - dl.x1
    if d <= 1e-12:
        return 0.0
    return dl.w1 + (dl.w2 - dl.w1) * (x - dl.x1) / d


def _consistent_ramp_load(wa, wb, Le):
    """Work-equivalent nodal load vector [F1, M1, F2, M2] for a linear
    ramp wa..wb (positive DOWN) over one element, from the exact
    integrals of the Hermite shape functions. Reduces to the familiar
    [wL/2, wL^2/12, wL/2, -wL^2/12] when wa == wb."""
    return (Le * (7 * wa + 3 * wb) / 20.0,
            Le * Le * (3 * wa + 2 * wb) / 60.0,
            Le * (3 * wa + 7 * wb) / 20.0,
            -Le * Le * (2 * wa + 3 * wb) / 60.0)


def _interp(xs, ys, x):
    if not xs:
        return 0.0
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    span = xs[hi] - xs[lo]
    if span <= 1e-12:
        return ys[lo]
    t = (x - xs[lo]) / span
    return ys[lo] * (1 - t) + ys[hi] * t


@dataclass
class HyperstaticSolution:
    """Result of one stiffness solve. `reactions` is a list of
    (x, R_up, M_ccw) -- vertical reaction positive UP and reaction couple
    positive CCW, both in the conventions perforated_beam_math.py uses,
    so they drop straight into an equilibrium sum."""
    nodes: list
    deflections: list                                      # positive DOWN, mm
    reactions: list                                        # [(x, R_up, M_ccw), ...]
    supports: list
    twists: list = field(default_factory=list)             # nodal twist, rad
    torque_reactions: list = field(default_factory=list)   # [(x, T), ...]
    torsion_solved: bool = False

    def deflection_at(self, x):
        return _interp(self.nodes, self.deflections, x)

    def twist_at(self, x):
        if not self.twists:
            return 0.0
        return _interp(self.nodes, self.twists, x)

    @property
    def max_deflection(self):
        """(x, v) at the node of largest |deflection|."""
        if not self.deflections:
            return 0.0, 0.0
        i = max(range(len(self.deflections)), key=lambda k: abs(self.deflections[k]))
        return self.nodes[i], self.deflections[i]


def solve_bending(beam, supports, target_elements=80, net_I_fn=None):
    """Direct-stiffness solve for the reactions of an arbitrarily
    supported beam. Returns a HyperstaticSolution.

    `net_I_fn(beam, x) -> I` supplies the second moment of area at a
    station; the caller passes `perforated_beam_math.net_I_at` so that
    openings reduce the stiffness exactly as they do in the deflection
    estimate. Defaults to the gross section when not given."""
    nodes = build_mesh(beam, supports, target_elements)
    n_node = len(nodes)
    n_dof = 2 * n_node
    bw = 3
    E = beam.material.E
    if net_I_fn is None:
        def net_I_fn(b, x):
            return b.section.I

    K = [[0.0] * (bw + 1) for _ in range(n_dof)]
    F = [0.0] * n_dof

    # Rotation-DOF scaling (see module docstring): solve for theta' =
    # theta / Lc so the two DOF families carry comparable magnitudes.
    Lc = (nodes[-1] - nodes[0]) / max(n_node - 1, 1)
    if Lc <= 0:
        Lc = 1.0
    dof_scale = (1.0, Lc, 1.0, Lc)

    def add_k(r, c, val):
        """Upper-band accumulate; the matrix is symmetric so only r <= c
        is stored."""
        if c < r:
            r, c = c, r
        k = c - r
        if k <= bw:
            K[r][k] += val

    for e in range(n_node - 1):
        xa, xb = nodes[e], nodes[e + 1]
        Le = xb - xa
        if Le <= 1e-12:
            continue
        I = net_I_fn(beam, 0.5 * (xa + xb))
        c = E * I / (Le ** 3)
        k11, k12 = 12 * c, 6 * Le * c
        k22, k24 = 4 * Le * Le * c, 2 * Le * Le * c
        d = (2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3)
        ke = ((k11, k12, -k11, k12),
              (k12, k22, -k12, k24),
              (-k11, -k12, k11, -k12),
              (k12, k24, -k12, k22))
        for a in range(4):
            for b in range(4):
                if d[b] >= d[a]:
                    add_k(d[a], d[b], ke[a][b] * dof_scale[a] * dof_scale[b])
        # Consistent nodal loads from every distributed load overlapping
        # this element. A load normally covers whole elements because its
        # ends are mesh breakpoints; the partial branch below is the
        # fallback for a load clipped by the beam end.
        for dl in beam.dist_loads:
            if dl.x2 <= xa + 1e-9 or dl.x1 >= xb - 1e-9:
                continue
            ov_a, ov_b = max(xa, dl.x1), min(xb, dl.x2)
            Lov = ov_b - ov_a
            if Lov <= 1e-12:
                continue
            wa = _ramp_value(dl, ov_a)
            wb_ = _ramp_value(dl, ov_b)
            if Lov < Le - 1e-9:
                w_eq = (wa + wb_) / 2.0 * Lov / Le
                fv = _consistent_ramp_load(w_eq, w_eq, Le)
            else:
                fv = _consistent_ramp_load(wa, wb_, Le)
            for a in range(4):
                F[d[a]] += fv[a] * dof_scale[a]

    node_index = {round(x, 6): i for i, x in enumerate(nodes)}

    def nearest_node(x):
        i = node_index.get(round(float(x), 6))
        if i is not None:
            return i
        return min(range(n_node), key=lambda k: abs(nodes[k] - x))

    for pl in beam.point_loads:
        F[2 * nearest_node(pl.x)] += pl.P          # +down, conjugate to +down v
    for pm in beam.point_moments:
        # No sign flip: theta = dv/dx with v measured DOWN is already
        # conjugate to this module's own moment sign (see the convention
        # note in the module docstring). Scaled like every other rotation
        # entry so it lands in the scaled system.
        F[2 * nearest_node(pm.x) + 1] += pm.M * Lc

    K_orig = [row[:] for row in K]
    F_orig = list(F)

    constrained = set()
    for s in supports:
        i = nearest_node(s.x)
        constrained.add(2 * i)
        if s.restrains_rotation:
            constrained.add(2 * i + 1)

    # Dirichlet BCs the band-preserving way: zero the row and the column,
    # unit diagonal, zero RHS. Renumbering to a reduced system would
    # scramble the bandwidth that makes this solve cheap.
    for dof in constrained:
        for k in range(bw + 1):
            if dof + k < n_dof:
                K[dof][k] = 0.0
            if dof - k >= 0:
                K[dof - k][k] = 0.0
        K[dof][0] = 1.0
        F[dof] = 0.0

    R = _banded_cholesky(K, n_dof, bw)
    u = _banded_solve(R, F, n_dof, bw)

    def k_row_dot(i):
        """(K_orig . u)[i], reading both halves of the symmetric band."""
        s = 0.0
        for k in range(bw + 1):             # stored entries K[i][i+k]
            j = i + k
            if j < n_dof:
                s += K_orig[i][k] * u[j]
        for k in range(1, bw + 1):          # mirrored entries K[i-k][i]
            j = i - k
            if j >= 0:
                s += K_orig[j][k] * u[j]
        return s

    reactions = []
    for s in supports:
        i = nearest_node(s.x)
        # k_row_dot - F is the generalized force the support applies along
        # +down; a support pushing UP therefore reports its negative.
        R_up = -(k_row_dot(2 * i) - F_orig[2 * i])
        M_ccw = 0.0
        if s.restrains_rotation:
            # Undo the rotation scaling (f = S^-1 f'). No sign flip, for
            # the same reason applied point moments need none. The result
            # is the couple the support applies ON the beam, in the same
            # sense as an applied point moment -- so M(x) can simply add
            # it, which is what makes M(0) at a built-in end come out as
            # the hogging moment rather than zero.
            M_ccw = (k_row_dot(2 * i + 1) - F_orig[2 * i + 1]) / Lc
        reactions.append((nodes[i], R_up, M_ccw))

    # translation DOFs were left unscaled, so these need no correction
    deflections = [u[2 * i] for i in range(n_node)]
    sol = HyperstaticSolution(nodes=nodes, deflections=deflections,
                              reactions=reactions, supports=list(supports))
    twists, t_reactions, ok = solve_torsion(beam, supports, nodes)
    sol.twists, sol.torque_reactions, sol.torsion_solved = twists, t_reactions, ok
    return sol


# ─────────────────────────────────────────────────────────────────────────
# 5. Torsion solve
# ─────────────────────────────────────────────────────────────────────────

def solve_torsion(beam, supports, nodes):
    """Uniform-torsion (St Venant) twist solve on the same mesh: one DOF
    per node, element stiffness GJ/Le, twist restrained at every support
    flagged `torsion_restrained`.

    Returns (twists, reactions, ok). `ok` is False -- with both lists
    empty -- when the section exposes no usable J (a custom-drawn profile
    has no generally inferable torsion constant, exactly as
    `analyze_combined` already handles), in which case the caller keeps
    the closed-form 2-restraint torque diagram rather than inventing one.

    WARPING IS NOT MODELLED, matching the rest of this tab: for an open
    I-shape with warping-restrained (forked) ends this is conservative on
    twist, and says nothing at all about the warping normal stress -- see
    MANIFESTO. Openings are not deducted from J either; the closed-form
    path makes the same simplification."""
    J = getattr(beam.section, 'J', None)
    if not isinstance(J, (int, float)) or J <= 0:
        return [], [], False
    restrained = [s for s in supports if s.torsion_restrained]
    if not restrained:
        return [], [], False

    G = beam.material.G
    n = len(nodes)
    bw = 1
    K = [[0.0] * (bw + 1) for _ in range(n)]
    F = [0.0] * n

    for e in range(n - 1):
        Le = nodes[e + 1] - nodes[e]
        if Le <= 1e-12:
            continue
        k = G * J / Le
        K[e][0] += k
        K[e][1] += -k
        K[e + 1][0] += k

    def nearest(x):
        return min(range(n), key=lambda i: abs(nodes[i] - x))

    for pt in beam.point_torques:
        F[nearest(pt.x)] += pt.T
    for pl in beam.point_loads:
        if pl.e:
            F[nearest(pl.x)] += pl.P * pl.e
    for dt in beam.dist_torques:
        _accumulate_dist_torque(F, nodes, dt.x1, dt.x2, dt.t1, dt.t2)
    for dl in beam.dist_loads:
        if dl.e:
            _accumulate_dist_torque(F, nodes, dl.x1, dl.x2, dl.w1 * dl.e, dl.w2 * dl.e)

    K_orig = [row[:] for row in K]
    F_orig = list(F)
    cons = {nearest(s.x) for s in restrained}
    for dof in cons:
        for k in range(bw + 1):
            if dof + k < n:
                K[dof][k] = 0.0
            if dof - k >= 0:
                K[dof - k][k] = 0.0
        K[dof][0] = 1.0
        F[dof] = 0.0

    Rf = _banded_cholesky(K, n, bw)
    phi = _banded_solve(Rf, F, n, bw)

    def row_dot(i):
        s = K_orig[i][0] * phi[i]
        if i + 1 < n:
            s += K_orig[i][1] * phi[i + 1]
        if i - 1 >= 0:
            s += K_orig[i - 1][1] * phi[i - 1]
        return s

    reactions = [(nodes[i], -(row_dot(i) - F_orig[i])) for i in sorted(cons)]
    return phi, reactions, True


def _accumulate_dist_torque(F, nodes, x1, x2, t1, t2):
    """Lumps a distributed-torque ramp onto the mesh with the linear
    (2-node bar) consistent load vector [Le*(2*ta+tb)/6, Le*(ta+2*tb)/6],
    scaled by the fraction of the element the torque actually covers."""
    d = x2 - x1
    if d <= 1e-12:
        return
    for e in range(len(nodes) - 1):
        xa, xb = nodes[e], nodes[e + 1]
        Le = xb - xa
        if Le <= 1e-12 or x2 <= xa + 1e-9 or x1 >= xb - 1e-9:
            continue
        ov_a, ov_b = max(xa, x1), min(xb, x2)
        ta = t1 + (t2 - t1) * (ov_a - x1) / d
        tb = t1 + (t2 - t1) * (ov_b - x1) / d
        cov = (ov_b - ov_a) / Le
        F[e] += Le * (2 * ta + tb) / 6.0 * cov
        F[e + 1] += Le * (ta + 2 * tb) / 6.0 * cov
