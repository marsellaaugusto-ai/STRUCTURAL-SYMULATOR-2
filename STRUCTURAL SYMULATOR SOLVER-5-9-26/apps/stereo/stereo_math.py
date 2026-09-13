"""3D direct-stiffness solver for the Stereo (space-structure) tab.

Storage units, kept consistent with the rest of the app (see units.py /
common.UnitsMixin): node coordinates in metres, member area in cm², E and G
in GPa, Fy/Fu in MPa, nodal loads in kN, self-weight density in kN/m³.
Internally everything is converted to SI (m, N, Pa) for the assembly, the
same boundary as truss_math.py crosses with its own *1e9/*1e-4/*1e3 factors.

MODEL
-----
nodes   : list of (x, y, z) tuples, metres. Node identity is list index.
members : list of dicts, each an axial bar ('pin', the default -- a
          ball-jointed space-truss member carrying only axial force, which
          is what MERO/Nodus/Triodetic-type real space structures actually
          build) or a full 3D beam-column ('rigid' -- a moment-transferring
          connection, for a Vierendeel-type space frame), with:
              a, b        : node indices
              conn        : 'pin' (default) | 'rigid'
              E           : GPa
              A           : cm²
              Fy, Fu      : MPa      (for the CIRSOC checks)
              K           : effective-length factor (default 1.0)
              r_gyr       : cm, weak-axis radius of gyration (pin members;
                            used for the compression buckling check)
              I           : cm⁴, weak-axis second moment (rigid members
                            only -- both bending planes are given this one
                            value, i.e. a doubly-symmetric section is
                            assumed; documented simplification)
              J           : cm⁴, torsion constant (rigid members only;
                            defaults to I if omitted -- another named
                            simplification, exact for a circular/round
                            tube and conservative-ish otherwise)
loads   : list of {'node': i, 'fx': kN, 'fy': kN, 'fz': kN,
                    'mx': kN·m, 'my': kN·m, 'mz': kN·m}, global axes.
          The moment components are optional (default 0) and only make
          physical sense at a node that can actually resist a moment; a
          node loaded with a nonzero mx/my/mz is granted rotational DOFs
          for exactly that reason, on top of the 'rigid member' and
          'restrained rotation' triggers below.
supports: list of {'node': i, 'type': preset_name_or_None,
                    'dofs': {dof_name: bool, ...}}
          -- see `support_restraints` below. This is deliberately NOT a
          fixed enum of support "types": `type` supplies a starting preset
          (or none at all) and `dofs` may restrain or free ANY of the six
          DOF names on top of it, so a user is never limited to a menu of
          canned support conditions.

BOUNDARY CONDITIONS -- "any combination the user pleases"
----------------------------------------------------------
Every one of the six DOFs at every node (ux, uy, uz, rx, ry, rz) is an
independent boolean: restrained or free. A preset ('pin', 'fixed',
'rollerX', ...) is only a convenience that fills in a starting `dofs` dict;
`support_restraints` always applies the user's explicit per-DOF overrides
on top of it, and a support with no preset at all (`type=None`) is
perfectly valid -- pick exactly the DOFs you want restrained. This is what
lets a genuinely unusual condition (e.g. a node free to translate but
restrained against rotation about one axis only, or a diagonal roller) be
built without inventing a new preset name for it. `check_boundary_setup`
below validates the result (rigid-body mechanism / over-restraint) so a
mistake shows up as a clear message instead of a silently wrong or
singular solve.

DOF ALLOCATION
--------------
Exactly the same lazy trick as truss_math.py's `needs_theta`, generalized
from one rotational DOF to three: a node gets rotational DOFs (rx,ry,rz)
only if a 'rigid' member touches it, or a support at that node restrains
at least one rotational DOF. A model built entirely from 'pin' members and
translation-only supports reduces exactly to a classic 3-DOF/node space
truss.
"""
import math
import numpy as np

from common import _beam_gauss_solve

gauss_solve = _beam_gauss_solve

DOF_NAMES = ('ux', 'uy', 'uz', 'rx', 'ry', 'rz')
ROT_DOFS = ('rx', 'ry', 'rz')

DEFAULT_STEEL_UNIT_WEIGHT = 78.5   # kN/m^3
DEFAULT_NU = 0.3                   # Poisson's ratio, for G = E / (2(1+nu))

PRESET_SUPPORTS = {
    'free':    {},
    'pin':     {'ux': True, 'uy': True, 'uz': True},
    'fixed':   {'ux': True, 'uy': True, 'uz': True, 'rx': True, 'ry': True, 'rz': True},
    'rollerX': {'uy': True, 'uz': True},    # free to slide along global X only
    'rollerY': {'ux': True, 'uz': True},    # free to slide along global Y only
    'rollerZ': {'ux': True, 'uy': True},    # free to slide along global Z only
}


def support_restraints(support):
    """The full 6-bool restraint dict for one support entry: a named preset
    (if any) merged with any explicit per-DOF override. This is the one
    place "any boundary condition the user pleases" is realised -- nothing
    downstream ever looks at `type` again, only at this resolved dict."""
    base = dict.fromkeys(DOF_NAMES, False)
    preset = support.get('type')
    if preset:
        if preset not in PRESET_SUPPORTS:
            raise ValueError(f'unknown support preset {preset!r}; expected one of '
                              f'{tuple(PRESET_SUPPORTS)} or None')
        base.update(PRESET_SUPPORTS[preset])
    base.update(support.get('dofs') or {})
    return base


def member_vector(nodes, member):
    na, nb = nodes[member['a']], nodes[member['b']]
    dx, dy, dz = nb[0] - na[0], nb[1] - na[1], nb[2] - na[2]
    L = math.sqrt(dx * dx + dy * dy + dz * dz)
    return dx, dy, dz, L


def _local_axes(dx, dy, dz, L):
    """A right-handed local (x,y,z) basis for a 3D frame element: local x
    along the member; local y and z from a fixed global reference vector,
    exactly like every standard 3D frame-element formulation (McGuire,
    Gallagher & Ziemian; Przemieniecki). Global Z is the reference vector
    unless the member itself is (near-)vertical, in which case global Y is
    used instead -- otherwise the cross product used to build local y would
    be with a parallel vector and degenerate to zero."""
    lx, ly, lz = dx / L, dy / L, dz / L
    if abs(lx) < 1e-9 and abs(ly) < 1e-9:
        ref = (0.0, 1.0, 0.0)
    else:
        ref = (0.0, 0.0, 1.0)
    # local y = ref x local_x, normalized
    yx = ref[1] * lz - ref[2] * ly
    yy = ref[2] * lx - ref[0] * lz
    yz = ref[0] * ly - ref[1] * lx
    nrm = math.sqrt(yx * yx + yy * yy + yz * yz)
    yx, yy, yz = yx / nrm, yy / nrm, yz / nrm
    # local z = local_x x local_y
    zx = ly * yz - lz * yy
    zy = lz * yx - lx * yz
    zz = lx * yy - ly * yx
    return (lx, ly, lz), (yx, yy, yz), (zx, zy, zz)


def _pin_stiffness(E_GPa, A_cm2, L):
    k = (E_GPa * 1e9) * (A_cm2 * 1e-4) / L
    return k


def _rigid_local_stiffness(E_GPa, A_cm2, I_cm4, J_cm4, L, nu=DEFAULT_NU):
    """The standard 12x12 local stiffness matrix for a 3D Euler-Bernoulli
    beam-column, DOF order (ux,uy,uz,rx,ry,rz) at node a then node b.
    Bending about local z (in-plane uy/rz) uses Iz; bending about local y
    (in-plane uz/ry) uses Iy. A doubly-symmetric section is assumed
    (Iy = Iz = I, the member's one given `I`), which is exact for a round
    or square hollow section -- the common choice for space-structure
    members -- and a documented simplification otherwise."""
    E = E_GPa * 1e9
    G = E / (2.0 * (1.0 + nu))
    A = A_cm2 * 1e-4
    Iy = Iz = I_cm4 * 1e-8
    J = J_cm4 * 1e-8

    EA_L = E * A / L
    GJ_L = G * J / L
    k = np.zeros((12, 12))

    k[0, 0] = k[6, 6] = EA_L
    k[0, 6] = k[6, 0] = -EA_L

    # bending in the local x-y plane (uy, rz), stiffness from Iz
    k[1, 1] = k[7, 7] = 12 * E * Iz / L ** 3
    k[1, 7] = k[7, 1] = -12 * E * Iz / L ** 3
    k[1, 5] = k[5, 1] = 6 * E * Iz / L ** 2
    k[1, 11] = k[11, 1] = 6 * E * Iz / L ** 2
    k[5, 7] = k[7, 5] = -6 * E * Iz / L ** 2
    k[7, 11] = k[11, 7] = -6 * E * Iz / L ** 2
    k[5, 5] = k[11, 11] = 4 * E * Iz / L
    k[5, 11] = k[11, 5] = 2 * E * Iz / L

    # bending in the local x-z plane (uz, ry), stiffness from Iy
    k[2, 2] = k[8, 8] = 12 * E * Iy / L ** 3
    k[2, 8] = k[8, 2] = -12 * E * Iy / L ** 3
    k[2, 4] = k[4, 2] = -6 * E * Iy / L ** 2
    k[2, 10] = k[10, 2] = -6 * E * Iy / L ** 2
    k[4, 8] = k[8, 4] = 6 * E * Iy / L ** 2
    k[8, 10] = k[10, 8] = 6 * E * Iy / L ** 2
    k[4, 4] = k[10, 10] = 4 * E * Iy / L
    k[4, 10] = k[10, 4] = 2 * E * Iy / L

    # torsion (rx)
    k[3, 3] = k[9, 9] = GJ_L
    k[3, 9] = k[9, 3] = -GJ_L

    return k


def _rotation_12(local_x, local_y, local_z):
    """Block-diagonal 12x12 transformation (global -> local) from the 3x3
    direction-cosine matrix, repeated once per translational/rotational
    triplet at each of the two nodes."""
    r3 = np.array([local_x, local_y, local_z])
    T = np.zeros((12, 12))
    for blk in range(4):
        T[blk * 3:blk * 3 + 3, blk * 3:blk * 3 + 3] = r3
    return T


def analyze(nodes, members, loads, supports):
    """Solve the space structure. Returns (result, error). On failure,
    result is None and error is a human-readable string (mirroring every
    other solver in this app, e.g. truss_math.analyze).

    result = {
        'node_res': [{'ux','uy','uz' (mm), 'rx','ry','rz' (rad)}, ...],
        'member_res': [{'N' (kN, +tension), and for rigid members also
                         'Vy','Vz' (kN), 'T','My_a','My_b','Mz_a','Mz_b'
                         (kN·m)}, ...],
        'reactions': {node_idx: {'Fx','Fy','Fz' (kN), 'Mx','My','Mz' (kN·m)}},
    }
    """
    err = check_boundary_setup(nodes, members, supports)
    if err:
        return None, err

    N = len(nodes)
    restraints = [dict.fromkeys(DOF_NAMES, False) for _ in range(N)]
    for sp in supports:
        r = support_restraints(sp)
        node_r = restraints[sp['node']]
        for d in DOF_NAMES:
            node_r[d] = node_r[d] or r[d]

    needs_rot = [False] * N
    for m in members:
        if m.get('conn', 'pin') == 'rigid':
            needs_rot[m['a']] = True
            needs_rot[m['b']] = True
    for i in range(N):
        if any(restraints[i][d] for d in ROT_DOFS):
            needs_rot[i] = True
    for ld in loads:
        if any(ld.get(k, 0.0) for k in ('mx', 'my', 'mz')):
            needs_rot[ld['node']] = True

    dof_of = [None] * N   # (ux,uy,uz, rx_or_None, ry_or_None, rz_or_None)
    ndof = 0
    for i in range(N):
        idx = [ndof, ndof + 1, ndof + 2]
        ndof += 3
        if needs_rot[i]:
            idx += [ndof, ndof + 1, ndof + 2]
            ndof += 3
        else:
            idx += [None, None, None]
        dof_of[i] = tuple(idx)

    K = np.zeros((ndof, ndof))
    for m in members:
        dx, dy, dz, L = member_vector(nodes, m)
        if L < 1e-9:
            continue
        lx, ly, lz = dx / L, dy / L, dz / L
        a_dof, b_dof = dof_of[m['a']], dof_of[m['b']]

        if m.get('conn', 'pin') != 'rigid':
            k = _pin_stiffness(m['E'], m['A'], L)
            dirn = np.array([lx, ly, lz])
            ke33 = k * np.outer(dirn, dirn)
            idx = [a_dof[0], a_dof[1], a_dof[2], b_dof[0], b_dof[1], b_dof[2]]
            ke = np.block([[ke33, -ke33], [-ke33, ke33]])
            for i in range(6):
                for j in range(6):
                    K[idx[i], idx[j]] += ke[i, j]
        else:
            local_x, local_y, local_z = _local_axes(dx, dy, dz, L)
            kloc = _rigid_local_stiffness(m['E'], m['A'], m.get('I', 0.0),
                                           m.get('J', m.get('I', 0.0)), L)
            T = _rotation_12(local_x, local_y, local_z)
            kgl = T.T @ kloc @ T
            idx = list(a_dof) + list(b_dof)
            for i in range(12):
                for j in range(12):
                    K[idx[i], idx[j]] += kgl[i, j]

    F = np.zeros(ndof)
    for ld in loads:
        idx = dof_of[ld['node']]
        F[idx[0]] += ld.get('fx', 0.0) * 1e3
        F[idx[1]] += ld.get('fy', 0.0) * 1e3
        F[idx[2]] += ld.get('fz', 0.0) * 1e3
        for k, key in ((3, 'mx'), (4, 'my'), (5, 'mz')):
            v = ld.get(key, 0.0)
            if v:
                F[idx[k]] += v * 1e3

    constrained = set()
    for sp in supports:
        r = support_restraints(sp)
        idx = dof_of[sp['node']]
        for k, d in enumerate(DOF_NAMES):
            if r[d]:
                if idx[k] is None:
                    # a rotational restraint at a node with no rotational
                    # DOF allocated cannot happen: needs_rot was set for
                    # exactly this case above.
                    raise AssertionError('internal: rotational DOF missing '
                                          'for a restrained rotation')
                constrained.add(idx[k])

    free = [i for i in range(ndof) if i not in constrained]
    if not free:
        return None, 'All degrees of freedom are constrained -- nothing can move.'

    Kf = K[np.ix_(free, free)]
    Ff = F[free]
    U_free = gauss_solve(Kf, Ff)
    if U_free is None:
        return None, ('Singular stiffness matrix -- the structure (or some part '
                       'of it) is a mechanism, or a node is floating with no '
                       'load path to a support. Check for missing members or '
                       'missing boundary conditions.')

    U = np.zeros(ndof)
    for li, gi in enumerate(free):
        U[gi] = U_free[li]

    node_res = []
    for i in range(N):
        idx = dof_of[i]
        node_res.append({
            'ux': U[idx[0]] * 1000.0, 'uy': U[idx[1]] * 1000.0, 'uz': U[idx[2]] * 1000.0,
            'rx': U[idx[3]] if idx[3] is not None else 0.0,
            'ry': U[idx[4]] if idx[4] is not None else 0.0,
            'rz': U[idx[5]] if idx[5] is not None else 0.0,
        })

    member_res = []
    for m in members:
        dx, dy, dz, L = member_vector(nodes, m)
        if L < 1e-9:
            member_res.append({'N': 0.0, 'conn': m.get('conn', 'pin'), 'length_m': 0.0})
            continue
        lx, ly, lz = dx / L, dy / L, dz / L
        a_dof, b_dof = dof_of[m['a']], dof_of[m['b']]

        if m.get('conn', 'pin') != 'rigid':
            ua = np.array([U[a_dof[0]], U[a_dof[1]], U[a_dof[2]]])
            ub = np.array([U[b_dof[0]], U[b_dof[1]], U[b_dof[2]]])
            dirn = np.array([lx, ly, lz])
            elong = float(np.dot(ub - ua, dirn))
            N_force = (m['E'] * 1e9) * (m['A'] * 1e-4) / L * elong
            member_res.append({'N': N_force / 1e3, 'conn': 'pin', 'length_m': L})
        else:
            local_x, local_y, local_z = _local_axes(dx, dy, dz, L)
            kloc = _rigid_local_stiffness(m['E'], m['A'], m.get('I', 0.0),
                                           m.get('J', m.get('I', 0.0)), L)
            T = _rotation_12(local_x, local_y, local_z)
            idx = list(a_dof) + list(b_dof)
            dgl = np.array([U[i] for i in idx])
            dloc = T @ dgl
            floc = kloc @ dloc
            member_res.append({
                'N': floc[6] / 1e3, 'conn': 'rigid', 'length_m': L,
                'Vy_a': floc[1] / 1e3, 'Vz_a': floc[2] / 1e3, 'T': floc[3] / 1e3,
                'My_a': floc[4] / 1e3, 'Mz_a': floc[5] / 1e3,
                'My_b': floc[10] / 1e3, 'Mz_b': floc[11] / 1e3,
            })

    reactions = {}
    Ku = K @ U
    for sp in supports:
        r = support_restraints(sp)
        if not any(r.values()):
            continue
        idx = dof_of[sp['node']]
        rxn = reactions.setdefault(sp['node'], {'Fx': 0.0, 'Fy': 0.0, 'Fz': 0.0,
                                                 'Mx': 0.0, 'My': 0.0, 'Mz': 0.0})
        labels = ('Fx', 'Fy', 'Fz', 'Mx', 'My', 'Mz')
        for k, d in enumerate(DOF_NAMES):
            if r[d] and idx[k] is not None:
                resid = Ku[idx[k]] - F[idx[k]]
                rxn[labels[k]] += resid / 1e3   # N -> kN, N*m -> kN*m

    return {'node_res': node_res, 'member_res': member_res, 'reactions': reactions}, None


def node_moment_vectors(nodes, members, member_res):
    """The internal moment (Mx, My, Mz, kN*m, in GLOBAL axes) each RIGID
    member end imposes on the joint it frames into, picking -- per node --
    the single connected member end with the LARGEST resultant magnitude
    as that joint's representative value. Returned as {node_idx: {'Mx',
    'My', 'Mz'}}, one entry per node touched by at least one rigid member
    (a purely pin-jointed joint carries no moment by definition and is
    omitted, exactly like a pin-jointed truss's support reads ~0 moment).

    Built with the exact same local-axis transform analyze() itself uses
    (_local_axes / _rotation_12) so the result is directly comparable,
    axis-for-axis, to a support's own reaction Mx/My/Mz -- e.g. through
    stereo_app's reaction_moment_signed, which works unchanged on either
    dict since both only need Mx/My/Mz keys.

    A plain SUM across every member framing into a joint was deliberately
    rejected: at an unloaded interior joint, moment CONTINUITY means the
    incoming member-end moments are equal and opposite by joint
    equilibrium, so a naive sum would read ~0 there regardless of how much
    bending the joint is actually carrying -- the opposite of useful for a
    "how much moment is happening here" visualization. Taking the single
    largest-magnitude incident end instead avoids that cancellation and
    reads as "the worst-loaded member framing into this joint", which for
    the common case of two collinear continuous members is the same
    (equal-and-opposite) value either end would give.

    member_res is the 'member_res' list an earlier analyze() call already
    returned -- this function does not re-solve anything, only re-expresses
    already-solved local end-moments in global axes.
    """
    best = {}
    for m, res in zip(members, member_res):
        if m.get('conn', 'pin') != 'rigid' or res.get('length_m', 0.0) < 1e-9:
            continue
        dx, dy, dz, L = member_vector(nodes, m)
        local_x, local_y, local_z = _local_axes(dx, dy, dz, L)
        T = res.get('T', 0.0)
        ends = ((m['a'], T, res.get('My_a', 0.0), res.get('Mz_a', 0.0)),
                (m['b'], -T, res.get('My_b', 0.0), res.get('Mz_b', 0.0)))
        for node, t_end, my, mz in ends:
            gx = local_x[0] * t_end + local_y[0] * my + local_z[0] * mz
            gy = local_x[1] * t_end + local_y[1] * my + local_z[1] * mz
            gz = local_x[2] * t_end + local_y[2] * my + local_z[2] * mz
            mag = math.sqrt(gx * gx + gy * gy + gz * gz)
            cur = best.get(node)
            if cur is None or mag > cur[0]:
                best[node] = (mag, {'Mx': gx, 'My': gy, 'Mz': gz})
    return {node: vec for node, (_mag, vec) in best.items()}


def degree_of_indeterminacy(nodes, members, supports):
    """The structure's degree of STATIC INDETERMINACY: how many more
    independent force/moment unknowns (member internal forces plus
    support reactions) exist than the equilibrium equations available to
    solve for them. 0 = statically determinate (exactly enough load
    paths, textbook "simple" structure); positive = redundant (more load
    paths than the bare minimum -- the classic meaning of "indeterminate"
    in the sense every statics course uses); negative = UNDER-restrained
    -- a genuine mechanism, the same condition `analyze()` would reject
    with a singular stiffness matrix (or `check_boundary_setup` catches
    even earlier). This is a property of the STRUCTURE alone (geometry,
    connectivity, supports) -- deliberately independent of any particular
    load case, the conventional meaning of the term.

    Generalizes the textbook single-typology formulas -- DSI = m + r - 3j
    for a pure pin-jointed truss, DSI = 6m + r - 6j for a pure rigid
    frame (m = members, r = individual restrained DOF components, j =
    joints) -- to any pin/rigid MIX, using the exact same per-node DOF-
    counting rule analyze() itself uses (a node needs 6 DOF, not just 3,
    the moment it touches a RIGID member or has a restrained rotation) so
    a mixed structure is counted consistently with how it is actually
    solved:

        DSI = (member unknowns: 1 per pin member, 6 per rigid member)
            + (total restrained DOF count across every support)
            - (total ACTIVE DOF count across every node)

    Verified against hand-checkable cases in
    tests/test_stereo_math.py::test_degree_of_indeterminacy_* -- a fully
    triangulated 3D tetrahedron (6 pin members, 4 joints) with the
    minimum 6 restraint components needed for 3D stability comes out
    to exactly 0; adding one redundant brace makes it +1; a fixed-fixed
    single rigid member (no intermediate joint) comes out to +6, the
    same result 2D statics gets for a fixed-fixed beam once the extra
    out-of-plane DOF a 3D formulation carries are accounted for.
    """
    N = len(nodes)
    restraints = [dict.fromkeys(DOF_NAMES, False) for _ in range(N)]
    for sp in supports:
        r = support_restraints(sp)
        node_r = restraints[sp['node']]
        for d in DOF_NAMES:
            node_r[d] = node_r[d] or r[d]

    needs_rot = [False] * N
    for m in members:
        if m.get('conn', 'pin') == 'rigid':
            needs_rot[m['a']] = True
            needs_rot[m['b']] = True
    for i in range(N):
        if any(restraints[i][d] for d in ROT_DOFS):
            needs_rot[i] = True

    ndof = sum(6 if needs_rot[i] else 3 for i in range(N))
    restraint_count = sum(1 for i in range(N) for d in DOF_NAMES if restraints[i][d])
    member_unknowns = sum(6 if m.get('conn', 'pin') == 'rigid' else 1 for m in members)
    return member_unknowns + restraint_count - ndof


def total_restrained_dofs(nodes, supports):
    """Total count of individual restrained DOF components (ux/uy/uz/rx/ry/rz)
    across every support, merging duplicate restraints on the same node.

    A 3D rigid body has exactly 6 possible rigid-body motions (3
    translations + 3 rotations). Suppressing all of them requires AT LEAST
    6 restrained DOF components in total, correctly placed -- this is a
    hard lower bound, independent of how many members exist or how they
    are arranged. Below this count the structure is a free-floating
    mechanism no matter how large `degree_of_indeterminacy` computes,
    because that formula only balances unknowns against equations in
    aggregate and cannot by itself see that missing EXTERNAL restraint
    can never be compensated for by internal bracing redundancy. Callers
    should treat `total_restrained_dofs(...) < 6` as an unconditional
    instability warning, checked separately from the DSI sign/value.
    """
    N = len(nodes)
    restraints = [dict.fromkeys(DOF_NAMES, False) for _ in range(N)]
    for sp in supports:
        r = support_restraints(sp)
        node_r = restraints[sp['node']]
        for d in DOF_NAMES:
            node_r[d] = node_r[d] or r[d]
    return sum(1 for i in range(N) for d in DOF_NAMES if restraints[i][d])


def check_boundary_setup(nodes, members, supports):
    """Validate supports BEFORE assembly, so a bad boundary-condition setup
    reads as a clear message instead of a numpy singular-matrix traceback
    or (worse) a silently wrong answer.

    Catches:
      * a support naming a node index out of range;
      * an unknown preset name (surfaced from `support_restraints`);
      * fewer than 3 independent translational restraints anywhere in the
        model, which always leaves at least a rigid-body translation or
        rotation free regardless of how the members are arranged -- the
        classic "floating in space" mistake. This is a coarse necessary
        check, not a full mechanism/stability analysis (a real mechanism
        hiding inside an otherwise adequately-supported model is instead
        caught by the singular-matrix guard in `analyze`).
    """
    N = len(nodes)
    for sp in supports:
        if not (0 <= sp['node'] < N):
            return f"support references node {sp['node']}, but the model has {N} nodes"
        try:
            support_restraints(sp)
        except ValueError as exc:
            return str(exc)

    restrained_axes = set()
    any_restraint = False
    for sp in supports:
        r = support_restraints(sp)
        for d in ('ux', 'uy', 'uz'):
            if r[d]:
                restrained_axes.add(d)
                any_restraint = True
    if not any_restraint:
        return ('No boundary conditions are defined -- the structure is free to '
                'translate and rotate as a rigid body. Restrain at least one node.')
    if len(restrained_axes) < 3:
        missing = sorted({'ux', 'uy', 'uz'} - restrained_axes)
        return ('The supports restrain translation along ' +
                ', '.join(sorted(a[-1] for a in restrained_axes)) +
                f' only; {", ".join(a[-1] for a in missing)} is free everywhere, so '
                'the whole structure can translate as a rigid body in that '
                'direction. Restrain it somewhere.')
    return None


def self_weight_loads(nodes, members, unit_weight_kN_m3=DEFAULT_STEEL_UNIT_WEIGHT):
    """Lump each member's self weight (kN) half-and-half onto its two end
    nodes as a downward (-z) nodal load -- the standard space-truss
    idealisation, exact for a pin member (which can carry no distributed
    load anyway) and the usual practical approximation for a rigid one."""
    totals = {}
    for m in members:
        _, _, _, L = member_vector(nodes, m)
        W = m['A'] * 1e-4 * L * unit_weight_kN_m3   # cm² -> m², times length, times kN/m3
        half = W / 2.0
        totals[m['a']] = totals.get(m['a'], 0.0) + half
        totals[m['b']] = totals.get(m['b'], 0.0) + half
    return [{'node': n, 'fx': 0.0, 'fy': 0.0, 'fz': -w} for n, w in totals.items()]


def area_load_to_nodal_loads(load_nodes, q_kN_m2, direction=(0.0, 0.0, -1.0)):
    """Convert a uniform pressure q (kN/m², e.g. snow/dead roof load) into
    nodal loads, using the exact/converged tributary areas a geometry
    generator returns as its `load_nodes` dict (node_idx -> area_m2; see
    stereo_geometry.py). `direction` is a unit-ish vector (normalized here,
    so the caller need not pre-normalize); the default -z matches
    `self_weight_loads`'s downward convention."""
    dx, dy, dz = direction
    norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    if norm < 1e-12:
        raise ValueError('direction must be a nonzero vector')
    dx, dy, dz = dx / norm, dy / norm, dz / norm
    loads = []
    for node, area in load_nodes.items():
        P = q_kN_m2 * area
        loads.append({'node': node, 'fx': P * dx, 'fy': P * dy, 'fz': P * dz})
    return loads


def combine_loads(*load_lists):
    """Merge several load lists (e.g. applied loads + self_weight_loads)
    into one, summing contributions that land on the same node instead of
    leaving them as separate entries analyze() would otherwise just add
    anyway -- kept separate only for readability of the combined list."""
    totals = {}
    for loads in load_lists:
        for ld in loads:
            t = totals.setdefault(ld['node'], {'node': ld['node'], 'fx': 0.0, 'fy': 0.0, 'fz': 0.0})
            t['fx'] += ld.get('fx', 0.0)
            t['fy'] += ld.get('fy', 0.0)
            t['fz'] += ld.get('fz', 0.0)
    return list(totals.values())
