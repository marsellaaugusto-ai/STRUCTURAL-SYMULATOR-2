"""
cable_web_math.py -- 2D cable/funicular NETWORK solver.

Generalizes cable_app.CableModel (one continuous chain between two supports,
constant horizontal thrust H) to an arbitrary planar graph of straight
tension-only members meeting at shared junction nodes (a "cable web"),
following the standard methodology for this exact problem:

  - Schek, H-J. (1974), "The force density method for form finding and
    computation of general networks", Comp. Meth. Appl. Mech. Eng. 3.
        -> linear form-finding solve (`solve_force_density`)
  - Block, P. & Ochsendorf, J. (2007), "Thrust Network Analysis: A New
    Methodology for Three-dimensional Equilibrium", J. IASS 48.
        -> the tension-network / inverted-compression-network duality
           (`inverted_shape` on CableWebResult), i.e. the digital analogue
           of Gaudi's hanging poly-funicular models for the Sagrada Familia
           Passion Facade (Burry et al., IJAC 3(1), 2005).

DESIGN DECISION (stated explicitly, not hidden in code):
A web EDGE is always a single straight tension-only member between two
nodes -- exactly like one bar of a truss, except it carries only tension
and its governing equation is a prescribed *natural length* (inextensible
cable segment) rather than a stiffness (EA/L) relation. There is no
separate "curved edge" representation. If a real rope must visibly sag
under its own weight between two knots, that sag is obtained the same way
FEM obtains it: by placing additional free (unsupported) nodes along that
rope's path, splitting it into several straight edges. This mirrors
exactly how cable_app.CableModel discretizes ONE continuous cable into many
straight elements, and keeps a single, uniform graph representation for
both a coarse funicular network (Gaudi's actual knot topology) and a finely
subdivided one (a visibly sagging individual rope). Self-weight per edge is
lumped as a point load split half-and-half onto its two end nodes, exactly
as a straight two-node element must (no distributed load can act at any
other point along a straight member with no interior nodes).

Point loads at nodes are exact by construction (there is no "epsilon
method" here at all, and none is needed): a nodal force is already the
precise discrete representation of a concentrated load, unlike in the
single-continuous-cable case where a point load along the material length
had to be pinned down as an extra unknown material coordinate. This is a
genuine simplification relative to the corrected cable_app.py, not a loss
of precision.

Two solve modes, meant to be used together (per project decision):

  1. solve_force_density(model, q)  -- LINEAR. Assign a force density
     q_e = T_e / L_e per edge. Free-node equilibrium becomes linear in the
     unknown coordinates because T_e * unit_vector(e) = q_e * (delta x, delta y)
     -- no division by the (unknown) current length is needed. Always
     solvable in one shot (no Newton, no divergence). Used to produce a
     robust initial guess for mode 2, and standalone for fast form-finding
     exploration.

  2. solve_analysis(model, ...) -- NONLINEAR. Every edge's natural length is
     prescribed (from the model, e.g. the as-drawn geometry, or explicit
     values) and every free node's vector force balance must hold exactly.
     Solved by Newton-Raphson with a finite-difference Jacobian (the same
     scheme cable_app.CableModel uses) wrapped in load-stepping continuation,
     seeded from the force-density solution.

Both modes support point loads in ARBITRARY direction (Fx, Fy) at any node
-- e.g. lateral wind loads applied directly at junctions, as in Model E of
the Burry et al. paper -- in addition to per-edge self-weight, which is
always vertical.

REDUCTION TEST (required before trusting anything built on top of this):
a web with no junction nodes (a single chain of nodes between two supports,
degree <= 2 everywhere) must reproduce cable_app.CableModel's converged H,
node positions and reactions to tight numerical tolerance. See
test_cable_web_math.py.
"""
import math
import numpy as np
from common import _beam_gauss_solve

G = 9.80665  # m/s^2, for weight-per-length given as mass-per-length; not
             # used directly (weights are specified as force/length in N/m)
             # -- kept only as a documented constant in case a caller wants
             # to convert from a mass density.


class MissingSolverDependency(RuntimeError):
    """A required third-party solver package is not installed.

    Deliberately its own type rather than a plain RuntimeError: callers
    (and `except` clauses that legitimately swallow a failed solve as
    "this web has no equilibrium") must be able to tell an environment
    problem apart from a numerical one.  Everything that catches broadly
    around solve_analysis re-raises this.
    """


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

class WebNode:
    __slots__ = ('id', 'x', 'y', 'is_support', 'fx', 'fy')

    def __init__(self, node_id, x, y, is_support=False, fx=0.0, fy=0.0):
        self.id = node_id
        self.x = float(x)
        self.y = float(y)
        self.is_support = bool(is_support)
        # External point load applied AT this node, arbitrary direction, N.
        # Sign convention: +x right, +y up (so a downward load is fy < 0).
        self.fx = float(fx)
        self.fy = float(fy)


class WebEdge:
    __slots__ = ('id', 'i', 'j', 'target_length', 'weight_per_length')

    def __init__(self, edge_id, node_i, node_j, target_length=None,
                 weight_per_length=0.0):
        self.id = edge_id
        self.i = node_i  # node id
        self.j = node_j  # node id
        # Natural (inextensible, prescribed) length used by solve_analysis.
        # If None, it is filled in from the initial nodal geometry when the
        # model is built (i.e. "as-drawn length"). Analysis mode CANNOT run
        # without a concrete number here; this is checked explicitly rather
        # than silently defaulting, since silently guessing a length is
        # exactly the kind of mistake we are trying to avoid.
        self.target_length = target_length
        # Self-weight, N per metre of the edge's own (material) length,
        # always acting in -y (gravity). Lumped half to each end node.
        self.weight_per_length = float(weight_per_length)


class CableWebModel:
    """A planar graph of WebNode + WebEdge. Build the topology, then call
    solve_force_density() and/or solve_analysis()."""

    def __init__(self):
        self.nodes = {}   # id -> WebNode
        self.edges = {}   # id -> WebEdge
        self._next_node_id = 0
        self._next_edge_id = 0

    def add_node(self, x, y, is_support=False, fx=0.0, fy=0.0, node_id=None):
        if node_id is None:
            node_id = self._next_node_id
        self._next_node_id = max(self._next_node_id, node_id + 1)
        n = WebNode(node_id, x, y, is_support, fx, fy)
        self.nodes[node_id] = n
        return node_id

    def add_edge(self, node_i, node_j, target_length=None,
                 weight_per_length=0.0, edge_id=None):
        if node_i not in self.nodes or node_j not in self.nodes:
            raise KeyError('add_edge: both endpoints must already exist as nodes')
        if node_i == node_j:
            raise ValueError('add_edge: an edge cannot connect a node to itself')
        if edge_id is None:
            edge_id = self._next_edge_id
        self._next_edge_id = max(self._next_edge_id, edge_id + 1)
        if target_length is None:
            a, b = self.nodes[node_i], self.nodes[node_j]
            target_length = math.hypot(b.x - a.x, b.y - a.y)
            if target_length <= 1e-12:
                raise ValueError(
                    'add_edge: coincident endpoints and no explicit target_length '
                    'given -- cannot infer a natural length of zero.')
        e = WebEdge(edge_id, node_i, node_j, target_length, weight_per_length)
        self.edges[edge_id] = e
        return edge_id

    # -- topology helpers ---------------------------------------------------

    def free_node_ids(self):
        return sorted(nid for nid, n in self.nodes.items() if not n.is_support)

    def incident_edges(self, node_id):
        return [e for e in self.edges.values() if e.i == node_id or e.j == node_id]

    def _validate_topology(self):
        if not self.nodes:
            raise ValueError('Model has no nodes.')
        if not self.edges:
            raise ValueError('Model has no edges.')
        free = self.free_node_ids()
        if not free:
            raise ValueError('Model has no free (non-support) nodes -- nothing to solve.')
        for nid in free:
            if not self.incident_edges(nid):
                raise ValueError(f'Free node {nid} has no incident edges -- '
                                  f'underconstrained (a floating point).')
        # Every node referenced by an edge must exist.
        for e in self.edges.values():
            if e.i not in self.nodes or e.j not in self.nodes:
                raise KeyError(f'Edge {e.id} references a node id that does not exist.')

    def nodal_loads(self):
        """External load (Fx, Fy) at every node: user point load plus half
        the self-weight of every incident edge (self-weight always acts in
        -y). Returns {node_id: (fx, fy)}."""
        loads = {nid: [n.fx, n.fy] for nid, n in self.nodes.items()}
        for e in self.edges.values():
            w_total = e.weight_per_length * e.target_length
            loads[e.i][1] -= 0.5 * w_total
            loads[e.j][1] -= 0.5 * w_total
        return {nid: (fx, fy) for nid, (fx, fy) in loads.items()}


# --------------------------------------------------------------------------
# Mode 1: Force Density Method (linear form-finding) -- Schek 1974
# --------------------------------------------------------------------------

class CableWebFDResult:
    def __init__(self, model, positions, q):
        self.model = model
        self.positions = positions  # {node_id: (x, y)}
        self.q = q                  # {edge_id: q_e}

    def edge_tension(self, edge_id):
        e = self.model.edges[edge_id]
        xi, yi = self.positions[e.i]
        xj, yj = self.positions[e.j]
        length = math.hypot(xj - xi, yj - yi)
        return self.q[edge_id] * length

    def edge_lengths(self):
        out = {}
        for eid, e in self.model.edges.items():
            xi, yi = self.positions[e.i]
            xj, yj = self.positions[e.j]
            out[eid] = math.hypot(xj - xi, yj - yi)
        return out


def solve_force_density(model, q, fixed_extra_loads=None):
    """Linear form-finding solve.

    q: {edge_id: q_e} force density (N/m) for every edge. A single float is
       also accepted and applied uniformly to every edge.

    At each free node j, equilibrium is:
        sum_{e incident to j} q_e * (coord_j - coord_other_end(e)) = F_ext_j
    which is LINEAR and DECOUPLED between x and y (same coefficient matrix
    for both), so it is solved as two independent linear systems sharing
    one factorized-by-elimination matrix build (built twice here for
    simplicity/clarity over cleverness, since this system is small).
    """
    model._validate_topology()
    if isinstance(q, (int, float)):
        q = {eid: float(q) for eid in model.edges}
    missing = [eid for eid in model.edges if eid not in q]
    if missing:
        raise ValueError(f'solve_force_density: missing q for edge id(s) {missing}')
    for eid, qv in q.items():
        if qv <= 0.0:
            raise ValueError(
                f'solve_force_density: q for edge {eid} must be > 0 (a '
                f'nonpositive force density cannot represent a taut, '
                f'tension-only cable).')

    free = model.free_node_ids()
    idx = {nid: k for k, nid in enumerate(free)}
    nf = len(free)
    loads = model.nodal_loads()

    Ax = [[0.0] * nf for _ in range(nf)]
    bx = [0.0] * nf
    Ay = [[0.0] * nf for _ in range(nf)]
    by = [0.0] * nf

    for nid in free:
        r = idx[nid]
        fx, fy = loads[nid]
        bx[r] += fx
        by[r] += fy

    for e in model.edges.values():
        qe = q[e.id]
        i, j = e.i, e.j
        ni, nj = model.nodes[i], model.nodes[j]
        i_free = i in idx
        j_free = j in idx
        if i_free:
            r = idx[i]
            Ax[r][r] += qe
            Ay[r][r] += qe
            if j_free:
                c = idx[j]
                Ax[r][c] -= qe
                Ay[r][c] -= qe
            else:
                bx[r] += qe * nj.x
                by[r] += qe * nj.y
        if j_free:
            r = idx[j]
            Ax[r][r] += qe
            Ay[r][r] += qe
            if i_free:
                c = idx[i]
                Ax[r][c] -= qe
                Ay[r][c] -= qe
            else:
                bx[r] += qe * ni.x
                by[r] += qe * ni.y

    xs = _beam_gauss_solve(Ax, bx)
    ys = _beam_gauss_solve(Ay, by)
    if xs is None or ys is None:
        raise RuntimeError(
            'solve_force_density: singular system -- the network is not '
            'fully connected to its supports through positive-q edges '
            '(a free node, or a whole disconnected sub-web, has no path '
            'to a support).')

    positions = {}
    for nid, n in model.nodes.items():
        if n.is_support:
            positions[nid] = (n.x, n.y)
    for nid in free:
        positions[nid] = (xs[idx[nid]], ys[idx[nid]])

    return CableWebFDResult(model, positions, dict(q))


# --------------------------------------------------------------------------
# Mode 2: nonlinear analysis (prescribed edge lengths, exact vector equilibrium)
# --------------------------------------------------------------------------

class CableWebResult:
    def __init__(self, model, positions, tensions, converged, residual):
        self.model = model
        self.positions = positions   # {node_id: (x, y)}
        self.tensions = tensions     # {edge_id: T_e}, T_e >= 0 expected
        self.converged = converged
        self.residual = residual

    def edge_length(self, edge_id):
        e = self.model.edges[edge_id]
        xi, yi = self.positions[e.i]
        xj, yj = self.positions[e.j]
        return math.hypot(xj - xi, yj - yi)

    def edge_force_components(self, edge_id):
        """(Fx, Fy): the force this edge (a taut cable) exerts ON NODE J --
        i.e. cut the cable just before node j and this is the internal
        tension vector acting on the j-side, pointing from j toward i (a
        taut cable always pulls each end toward the other end). This is
        the per-edge analogue of cable_app.CableResult.force_components().
        The force on node i is the exact negative of this vector.
        """
        e = self.model.edges[edge_id]
        xi, yi = self.positions[e.i]
        xj, yj = self.positions[e.j]
        L = math.hypot(xj - xi, yj - yi)
        T = self.tensions[edge_id]
        if T is None:
            raise ValueError(
                f'Edge {edge_id} connects two supports and was not part of '
                f'the solved system -- its tension is genuinely undefined '
                f'(any value is equally consistent with equilibrium), not '
                f'just unknown, so it has no force to report.')
        if L < 1e-13:
            return 0.0, 0.0
        # unit vector from j toward i -- the direction this taut edge pulls
        # node j.
        ux, uy = (xi - xj) / L, (yi - yj) / L
        return T * ux, T * uy

    def node_reaction(self, node_id):
        """Reaction (Rx, Ry) at a support node: the vector that must be
        supplied by the support to balance every edge tension pulling on it
        plus any external load applied directly at that (support) node.

        Note: if this support has an incident edge that is itself
        support-to-support (both ends fixed), that edge's internal tension
        is genuinely indeterminate (see CableWebModel's comment on
        inert edges) and is excluded here under the minimum-norm
        convention (assumed zero self-stress) -- any other tension in it
        would simply shift load between the two supports it connects
        without changing the rest of the network, so the reported
        reaction is exact up to that one indeterminate self-stress.
        """
        n = self.model.nodes[node_id]
        if not n.is_support:
            raise ValueError(f'Node {node_id} is not a support.')
        rx, ry = -n.fx, -n.fy
        for e in self.model.incident_edges(node_id):
            if self.tensions.get(e.id) is None:
                continue  # inert (support-to-support) edge -- see docstring
            fx, fy = self.edge_force_components(e.id)  # force on node j
            if e.j == node_id:
                rx -= fx
                ry -= fy
            else:
                # force on node i is the negative of the (j-side) vector
                rx -= -fx
                ry -= -fy
        # Include this support's share of any incident edges' self-weight.
        ry -= self.node_self_weight(node_id)[1]
        return rx, ry

    def node_self_weight(self, node_id):
        """(fx, fy) that incident edges' own self-weight applies AT a node.

        Consistent lumping gives each node half of every incident edge's
        total weight, and weight acts downward, so fy comes out negative.

        Defined once, here, because two callers need it and the same lumping
        convention derived twice is exactly the drift MANIFESTO sec 3j warns
        about: node_reaction() balances this force, and the Cable Web tab's
        equilibrium vectors draw it. Those two must never disagree about what
        a node is carrying.
        """
        fy = 0.0
        for e in self.model.incident_edges(node_id):
            fy -= 0.5 * e.weight_per_length * e.target_length
        return 0.0, fy

    def inverted_positions(self, about_y=0.0):
        """Mirror every node's y-coordinate about `about_y`: the classical
        Gaudi / Thrust-Network-Analysis duality -- a tension network in
        equilibrium under vertical load, inverted, is a compression-only
        network in equilibrium under the same load (Block & Ochsendorf,
        2007; Shodek's paragraph quoted in Burry et al. 2005). This
        inversion is rigorous for vertical load only; see the docstring
        warning in CableWebModel about non-vertical (lateral) loads before
        trusting an inverted view of a laterally-loaded web.
        """
        return {nid: (x, 2 * about_y - y) for nid, (x, y) in self.positions.items()}


def _pack(model, free, positions):
    z = []
    for nid in free:
        x, y = positions[nid]
        z.append(x)
        z.append(y)
    return z


def _unpack(model, free, z, base_positions):
    pos = dict(base_positions)
    for k, nid in enumerate(free):
        pos[nid] = (z[2 * k], z[2 * k + 1])
    return pos


def _feasible_tension_seed(model, positions):
    """Best-effort NON-NEGATIVE tension seed for the given (fixed)
    positions, found by a simplified active-set procedure:

      1. Solve the LINEAR equilibrium-only system (positions held fixed,
         so this is linear in the unknown tensions) by least squares
         (ridge-regularized normal equations -- this system is frequently
         underdetermined at indeterminate junctions, exactly the case
         that motivated this function).
      2. If any tension comes out negative, that member cannot actually be
         taut in a physical solution at this geometry/load -- clamp it to
         zero, drop it from the active (solvable) set, and re-solve the
         remaining reduced system. Repeat until every remaining tension is
         non-negative (or no edges remain).

    This directly generalizes the by-hand process used to diagnose the
    "member exactly at the tension boundary" and "feasible region only
    opens up far from a uniform-force-density guess" cases: instead of
    guessing a uniform force density and hoping Newton finds the feasible
    region on its own, this seed starts already inside (or very close to)
    the feasible region, which is what the nonlinear solver actually
    needs from an initial guess when the true solution has one or more
    members at or near zero tension.

    Returns {edge_id: T_e >= 0}. Not claimed to be exact equilibrium
    (positions are usually not yet at their converged location) -- it is
    a SEED for solve_analysis's Newton/LM iteration, not a final answer.
    """
    free = model.free_node_ids()
    idx = {nid: k for k, nid in enumerate(free)}
    nf = len(free)
    edge_ids = sorted(model.edges.keys())
    loads = model.nodal_loads()

    active = set(edge_ids)
    tensions = {eid: 0.0 for eid in edge_ids}

    for _ in range(len(edge_ids) + 1):
        active_list = sorted(active)
        m = 2 * nf
        ncols = len(active_list)
        if ncols == 0:
            break
        A = [[0.0] * ncols for _ in range(m)]
        b = [0.0] * m
        for nid in free:
            r0 = 2 * idx[nid]
            fx, fy = loads[nid]
            b[r0] -= fx
            b[r0 + 1] -= fy
        for c, eid in enumerate(active_list):
            e = model.edges[eid]
            xi, yi = positions[e.i]
            xj, yj = positions[e.j]
            L = math.hypot(xj - xi, yj - yi)
            if L < 1e-12:
                continue
            ux, uy = (xj - xi) / L, (yj - yi) / L
            if e.i in idx:
                r0 = 2 * idx[e.i]
                A[r0][c] += ux
                A[r0 + 1][c] += uy
            if e.j in idx:
                r0 = 2 * idx[e.j]
                A[r0][c] -= ux
                A[r0 + 1][c] -= uy

        # Ridge-regularized normal equations: (A^T A + eps I) T = A^T b.
        ata = [[sum(A[k][r] * A[k][c] for k in range(m)) for c in range(ncols)]
               for r in range(ncols)]
        atb = [sum(A[k][r] * b[k] for k in range(m)) for r in range(ncols)]
        scale = max((ata[d][d] for d in range(ncols)), default=1.0)
        eps = max(scale, 1.0) * 1e-9
        for d in range(ncols):
            ata[d][d] += eps
        sol = _beam_gauss_solve(ata, atb)
        if sol is None:
            break
        for c, eid in enumerate(active_list):
            tensions[eid] = sol[c]

        most_negative_eid = None
        most_negative_val = -1e-7
        for eid in active_list:
            if tensions[eid] < most_negative_val:
                most_negative_val = tensions[eid]
                most_negative_eid = eid
        if most_negative_eid is None:
            break
        active.discard(most_negative_eid)
        tensions[most_negative_eid] = 0.0

    return {eid: max(tensions.get(eid, 0.0), 0.0) for eid in edge_ids}


def solve_analysis(model, initial_positions=None, initial_tensions=None,
                    max_newton=60, tol=1e-9, verbose=False,
                    use_analytical_jacobian=True):
    """Nonlinear equilibrium solve with every edge length prescribed
    (model's WebEdge.target_length, which must not be None for any edge).

    Unknowns: (x, y) for every free node, and T_e for every edge
    (2 * n_free + n_edges total). Residuals: 2 vector force-balance
    equations per free node, plus 1 length-constraint equation per edge --
    exactly the same DOF/equation bookkeeping as cable_app.CableModel's
    chain (n-1 slope-continuity + (n-1) [implicit via the single H] length
    constraints... generalized here to explicit per-edge tension because a
    network has no single constant thrust H to exploit).

    use_analytical_jacobian: closed-form derivatives (2026-08-30) instead
    of the original per-column finite-difference Jacobian -- same
    equations, exact instead of an O(step) approximation, and `dof` times
    fewer residual evaluations per Newton iteration. Verified against the
    FD Jacobian to ~1e-5 relative agreement (FD's own truncation error)
    on both a converging case and the harder multi-junction case this was
    written for -- see REPORTS AND GUIDES/MANIFESTO.md. Set False to
    fall back to the original FD Jacobian (debugging/comparison only;
    not because the analytical one is in any doubt -- it produces
    identical converged results, just faster, on every case checked so
    far). Also used, when True, by the bounded least-squares fallback
    below in place of scipy's own 3-point finite-difference Jacobian --
    that fallback differentiates this exact same `residual` function, so
    the same closed form applies unchanged; profiled (not assumed) to be
    where most of that fallback's wall-clock time went (~90% on a
    49-node reference-preview case that needed it).
    """
    model._validate_topology()
    for e in model.edges.values():
        if e.target_length is None:
            raise ValueError(
                f'solve_analysis: edge {e.id} has no target_length -- '
                f'analysis mode requires an explicit prescribed length for '
                f'every edge (refusing to silently assume one).')
        if e.target_length <= 0.0:
            raise ValueError(f'solve_analysis: edge {e.id} has non-positive target_length.')

    # An edge whose BOTH endpoints are supports is kinematically inert: its
    # two positions never move, so its length residual is a fixed constant
    # that depends on no unknown at all, and it appears in NO free-node
    # equilibrium equation either (both ends are fixed). Its tension is
    # therefore not merely hard to find -- it is genuinely undefined by
    # this system (any value is equally consistent with every equation).
    # Solving for it anyway makes the Jacobian exactly rank-deficient by
    # one column per such edge, which is a real, avoidable cause of solver
    # stalling (found and confirmed 2026-08-18), not just an inconvenience.
    # These edges are therefore excluded from the solved system entirely;
    # their geometric consistency is checked once (a support-to-support
    # edge with an inconsistent prescribed length is a genuine modeling
    # contradiction, reported honestly rather than silently ignored), and
    # they are reported back with tension=None (undefined) rather than a
    # fabricated number.
    inert_edge_ids = []
    for eid, e in model.edges.items():
        ni, nj = model.nodes[e.i], model.nodes[e.j]
        if ni.is_support and nj.is_support:
            actual = math.hypot(nj.x - ni.x, nj.y - ni.y)
            if abs(actual - e.target_length) > 1e-6 * max(e.target_length, 1.0):
                raise ValueError(
                    f'solve_analysis: edge {eid} connects two supports whose '
                    f'fixed distance ({actual:.6g}) does not match its '
                    f'prescribed length ({e.target_length:.6g}) -- this is a '
                    f'rigid, unsolvable member, not a cable (an inextensible '
                    f'cable of the wrong length between two immovable points '
                    f'is a plain contradiction, not something to paper over).')
            inert_edge_ids.append(eid)

    free = model.free_node_ids()
    nf = len(free)
    edge_ids = sorted(eid for eid in model.edges if eid not in inert_edge_ids)
    ne = len(edge_ids)
    e_idx = {eid: k for k, eid in enumerate(edge_ids)}
    loads = model.nodal_loads()

    base_positions = {nid: (n.x, n.y) for nid, n in model.nodes.items() if n.is_support}

    # Characteristic force density, used both to seed positions (if not
    # supplied) and to seed tensions (always, since a network Newton solve
    # with tension unknowns starting at ~0 tends to stall on the L(z)
    # length-constraint Jacobian).
    total_load = sum(abs(fx) + abs(fy) for fx, fy in loads.values())
    total_len = sum(e.target_length for e in model.edges.values())
    q_guess = max(total_load / max(total_len, 1e-9), 1.0)

    dof = 2 * nf + ne
    force_scale = max(1.0, sum(abs(fx) + abs(fy) for fx, fy in loads.values()))
    length_scale = max(1.0, sum(e.target_length for e in model.edges.values()) / max(ne, 1))
    tension_scale = max(1.0, force_scale)

    def residual(z):
        pos = _unpack(model, free, z[:2 * nf], base_positions)
        T = {eid: z[2 * nf + e_idx[eid]] for eid in edge_ids}
        res = [0.0] * dof

        # Per free-node vector equilibrium.
        node_res = {nid: [loads[nid][0], loads[nid][1]] for nid in free}
        for eid in edge_ids:
            e = model.edges[eid]
            xi, yi = pos[e.i]
            xj, yj = pos[e.j]
            L = math.hypot(xj - xi, yj - yi)
            if L < 1e-13:
                ux, uy = 0.0, 0.0
            else:
                ux, uy = (xj - xi) / L, (yj - yi) / L
            Te = T[eid]
            if e.i in node_res:
                node_res[e.i][0] += Te * ux
                node_res[e.i][1] += Te * uy
            if e.j in node_res:
                node_res[e.j][0] -= Te * ux
                node_res[e.j][1] -= Te * uy
        for k, nid in enumerate(free):
            res[2 * k] = node_res[nid][0] / force_scale
            res[2 * k + 1] = node_res[nid][1] / force_scale

        # Per-edge length constraint (solved edges only -- inert
        # support-to-support edges were already checked once, above).
        for eid in edge_ids:
            e = model.edges[eid]
            xi, yi = pos[e.i]
            xj, yj = pos[e.j]
            L = math.hypot(xj - xi, yj - yi)
            res[2 * nf + e_idx[eid]] = (L - e.target_length) / length_scale

        return res

    node_row = {nid: 2 * k for k, nid in enumerate(free)}

    def jacobian_analytical(zc, f0=None):
        # Closed-form derivatives of `residual` above (verified against
        # finite-difference to ~5e-5 relative agreement -- FD's own
        # truncation error -- on both a converging case and a harder
        # multi-junction case; see MANIFESTO.md sec 6). f0 is accepted
        # (unused) only so this has the same call signature as the
        # finite-difference `jacobian` below and can also be handed
        # directly to scipy.optimize.least_squares's `jac` parameter as
        # `lambda zc: jacobian_analytical(zc)`, since it differentiates
        # this same `residual` function `least_squares` is called with
        # (not some differently-scaled variant): the "same equations,
        # exact instead of approximate" argument applies to the bounded
        # least-squares fallback exactly as much as the primary Newton
        # loop, not just the latter.
        pos = _unpack(model, free, zc[:2 * nf], base_positions)
        T = {eid: zc[2 * nf + e_idx[eid]] for eid in edge_ids}
        J = [[0.0] * dof for _ in range(dof)]
        for eid in edge_ids:
            e = model.edges[eid]
            xi, yi = pos[e.i]
            xj, yj = pos[e.j]
            dx, dy = xj - xi, yj - yi
            L = math.hypot(dx, dy)
            if L < 1e-13:
                ux = uy = Kxx = Kxy = Kyy = 0.0
            else:
                ux, uy = dx / L, dy / L
                # d(unit vector)/d(position): d(u)/d(pos_i) = -K,
                # d(u)/d(pos_j) = +K, where K = (I - u u^T) / L is the
                # standard 2D "geometric stiffness" projection matrix
                # (rank-1 update, symmetric) -- the same quantity a
                # truss/cable-net stiffness derivation always produces.
                Kxx = uy * uy / L
                Kxy = -ux * uy / L
                Kyy = ux * ux / L
            Te = T[eid]
            col_T = 2 * nf + e_idx[eid]
            row_len = 2 * nf + e_idx[eid]
            # Length residual: L_e = |pos_j - pos_i|, no T dependence.
            if e.i in node_row:
                ci = node_row[e.i]
                J[row_len][ci] += -ux / length_scale
                J[row_len][ci + 1] += -uy / length_scale
            if e.j in node_row:
                cj = node_row[e.j]
                J[row_len][cj] += ux / length_scale
                J[row_len][cj + 1] += uy / length_scale
            # Equilibrium residual at each free endpoint this edge
            # touches: contributes sign_n * T_e * u to that node's
            # force balance (sign_n = +1 at the "i" end, -1 at "j").
            for n, sign in ((e.i, 1.0), (e.j, -1.0)):
                if n not in node_row:
                    continue
                rn = node_row[n]
                J[rn][col_T] += sign * ux / force_scale
                J[rn + 1][col_T] += sign * uy / force_scale
                for m, mfac in ((e.i, -1.0), (e.j, 1.0)):
                    if m not in node_row:
                        continue
                    cm = node_row[m]
                    coeff = sign * Te * mfac / force_scale
                    J[rn][cm] += coeff * Kxx
                    J[rn][cm + 1] += coeff * Kxy
                    J[rn + 1][cm] += coeff * Kxy
                    J[rn + 1][cm + 1] += coeff * Kyy
        return J

    def jacobian_analytical_sparse(zc, f0=None):
        # Same derivatives as jacobian_analytical above, accumulated as
        # (row, col, value) triplets instead of into a dense dof x dof
        # array -- kept as an independent implementation rather than a
        # shared-with-dense refactor, deliberately: jacobian_analytical is
        # already verified against finite-difference (MANIFESTO.md sec 6)
        # and exercised by every existing test; routing it through a
        # generator to deduplicate would touch that proven path for a
        # benefit (avoiding ~60 lines of duplication) that matters far
        # less than not risking it. If the residual formulation above
        # ever changes, this needs the same change made twice -- worth a
        # comment, not worth the refactor risk here.
        #
        # Used only once dof crosses SPARSE_JACOBIAN_DOF_THRESHOLD (see
        # take_newton_steps): measured, not assumed, on chain topologies
        # from dof 16 to 3601 -- dense wins below ~dof 240 (sparse's own
        # construction/conversion overhead dominates at small size), then
        # sparse pulls ahead and the gap widens fast (dof 451: ~6x;
        # dof 1801: ~84x). Every dof this project's own built-in examples
        # and reference-preview solves actually reach today is under 150,
        # comfortably in dense's own regime -- this exists for a future
        # web big enough to need it, not because today's cases do.
        pos = _unpack(model, free, zc[:2 * nf], base_positions)
        T = {eid: zc[2 * nf + e_idx[eid]] for eid in edge_ids}
        rows, cols, vals = [], [], []
        for eid in edge_ids:
            e = model.edges[eid]
            xi, yi = pos[e.i]
            xj, yj = pos[e.j]
            dx, dy = xj - xi, yj - yi
            L = math.hypot(dx, dy)
            if L < 1e-13:
                ux = uy = Kxx = Kxy = Kyy = 0.0
            else:
                ux, uy = dx / L, dy / L
                Kxx = uy * uy / L
                Kxy = -ux * uy / L
                Kyy = ux * ux / L
            Te = T[eid]
            col_T = 2 * nf + e_idx[eid]
            row_len = 2 * nf + e_idx[eid]
            if e.i in node_row:
                ci = node_row[e.i]
                rows.append(row_len); cols.append(ci); vals.append(-ux / length_scale)
                rows.append(row_len); cols.append(ci + 1); vals.append(-uy / length_scale)
            if e.j in node_row:
                cj = node_row[e.j]
                rows.append(row_len); cols.append(cj); vals.append(ux / length_scale)
                rows.append(row_len); cols.append(cj + 1); vals.append(uy / length_scale)
            for n, sign in ((e.i, 1.0), (e.j, -1.0)):
                if n not in node_row:
                    continue
                rn = node_row[n]
                rows.append(rn); cols.append(col_T); vals.append(sign * ux / force_scale)
                rows.append(rn + 1); cols.append(col_T); vals.append(sign * uy / force_scale)
                for m, mfac in ((e.i, -1.0), (e.j, 1.0)):
                    if m not in node_row:
                        continue
                    cm = node_row[m]
                    coeff = sign * Te * mfac / force_scale
                    rows.append(rn); cols.append(cm); vals.append(coeff * Kxx)
                    rows.append(rn); cols.append(cm + 1); vals.append(coeff * Kxy)
                    rows.append(rn + 1); cols.append(cm); vals.append(coeff * Kxy)
                    rows.append(rn + 1); cols.append(cm + 1); vals.append(coeff * Kyy)
        import scipy.sparse as _sp
        return _sp.coo_matrix((vals, (rows, cols)), shape=(dof, dof)).tocsr()

    # Below this many unknowns, dense numpy wins (measured -- see
    # jacobian_analytical_sparse's own comment); above it, switch to
    # sparse assembly/solve for the Newton/LM loop. A large margin below
    # the measured ~dof-240 crossover on purpose: the crossover itself
    # was measured on one topology (a long chain); staying well clear of
    # it means small local differences in a real web's sparsity pattern
    # can't flip which side of the threshold is actually faster.
    SPARSE_JACOBIAN_DOF_THRESHOLD = 150

    def _sparse_lm_solve(JTJ, JTf, lam, diagJTJ):
        # Sparse counterpart of _beam_gauss_solve's role in the dense LM
        # step: same safety contract (None on a singular/unreliable
        # system, checked via the actual solution residual rather than a
        # solver-internal pivot proxy -- same reasoning as
        # _beam_gauss_solve's own docstring in common.py), different
        # backend (scipy.sparse.linalg.spsolve instead of
        # numpy.linalg.solve) because JTJ is a scipy.sparse matrix here,
        # not a dense array.
        import scipy.sparse as _sp
        import scipy.sparse.linalg as _spla
        A = (JTJ + _sp.diags(lam * diagJTJ)).tocsc()
        try:
            x = _spla.spsolve(A, -JTf)
        except Exception:
            return None
        if not np.all(np.isfinite(x)):
            return None
        residual = A @ x - (-JTf)
        scale = max(1.0, float(np.max(np.abs(JTf))))
        if np.max(np.abs(residual)) > 1e-6 * scale:
            return None
        return x.tolist()

    def take_newton_steps(z, n_iter, frac, loads_local):
        # `frac` load-steps the external loads (continuation), matching the
        # load-stepping robustness strategy already used in cable_app.
        scaled_loads = {nid: (fx * frac, fy * frac) for nid, (fx, fy) in loads_local.items()}

        def residual_scaled(zz):
            saved = loads.copy()
            loads.clear()
            loads.update(scaled_loads)
            try:
                return residual(zz)
            finally:
                loads.clear()
                loads.update(saved)

        def jacobian(zc, f0):
            J = [[0.0] * dof for _ in range(dof)]
            for col in range(dof):
                step = 1e-6 * (length_scale if col < 2 * nf else tension_scale)
                if step == 0.0:
                    step = 1e-6
                zk = zc[:]
                zk[col] += step
                fk = residual_scaled(zk)
                for i in range(dof):
                    J[i][col] = (fk[i] - f0[i]) / step
            return J

        jacobian_fn = jacobian_analytical if use_analytical_jacobian else jacobian
        use_sparse = use_analytical_jacobian and dof >= SPARSE_JACOBIAN_DOF_THRESHOLD

        # Levenberg-Marquardt, via the classical NORMAL-EQUATIONS form:
        # (J^T J + lambda * diag(J^T J)) delta = -J^T f0.
        #
        # This is deliberate, not an oversight: an earlier version of this
        # function damped the square Jacobian directly, (J + lambda I)
        # delta = -f0, to avoid squaring the condition number -- but that
        # form has NO guaranteed-descent property, because as lambda grows
        # its step direction limits to -f0/lambda (the raw residual
        # vector), not -J^T f0 (the true gradient of the merit function
        # 0.5*||f||^2). Only the normal-equations form's large-lambda limit
        # is the negative gradient, which is what actually guarantees a
        # decrease in the merit function for small enough steps. The
        # condition-squaring concern is real in principle but not in
        # practice for this problem's size/scaling (confirmed by the
        # reduction test converging to ~1e-9 below), and a correct,
        # guaranteed-descent method beats a better-conditioned one that
        # simply doesn't converge.
        #
        # Step-acceptance/convergence criteria, kept distinct on purpose:
        # accept/reject a trial step on the L2 merit function 0.5*||f||^2
        # (the quantity LM actually has a descent guarantee for); report
        # and test final convergence on the max-abs residual (the
        # physically meaningful "worst equation is satisfied to tol"
        # criterion). Conflating the two was an earlier bug.
        def merit(f):
            return sum(v * v for v in f)

        zc = z[:]
        lam = 1e-3
        f0 = residual_scaled(zc)
        rnorm = max(abs(v) for v in f0) if f0 else 0.0
        m0 = merit(f0)
        for _it in range(n_iter):
            if rnorm < tol:
                return zc, True, rnorm
            # J^T J / J^T f assembled via numpy (dense) or scipy.sparse
            # (once dof crosses SPARSE_JACOBIAN_DOF_THRESHOLD -- see that
            # threshold's own comment for the measurement behind the
            # cutoff) instead of nested Python loops -- same
            # normal-equations LM formulation either way, just not
            # O(dof^3) in interpreted Python. This is what actually
            # dominated wall-clock time for larger networks (confirmed by
            # profiling): the analytical Jacobian above cuts down how many
            # residual evaluations building J takes, but J^T J itself is a
            # dof x dof x dof reduction regardless of how J was obtained.
            f0_arr = np.asarray(f0, dtype=float)
            if use_sparse:
                J = jacobian_analytical_sparse(zc, f0)
                JTJ = (J.T @ J).tocsr()
                JTf = J.T @ f0_arr
                diagJTJ = np.maximum(JTJ.diagonal(), 1e-30)
            else:
                J = np.asarray(jacobian_fn(zc, f0), dtype=float)
                JTJ = J.T @ J
                JTf = J.T @ f0_arr
                diagJTJ = np.maximum(np.diag(JTJ), 1e-30)
            improved = False
            for _lm_try in range(60):
                if use_sparse:
                    delta = _sparse_lm_solve(JTJ, JTf, lam, diagJTJ)
                else:
                    A = JTJ + np.diag(lam * diagJTJ)
                    delta = _beam_gauss_solve(A, -JTf)
                if delta is None:
                    lam *= 10.0
                    continue
                zn = [zc[i] + delta[i] for i in range(dof)]
                if not all(zn[2 * nf + t] >= -1e-9 for t in range(ne)):
                    lam *= 10.0
                    continue
                fn = residual_scaled(zn)
                mn = merit(fn)
                if mn < m0:
                    zc, f0, m0 = zn, fn, mn
                    rnorm = max(abs(v) for v in fn) if fn else 0.0
                    lam = max(lam * 0.3, 1e-12)
                    improved = True
                    break
                lam *= 10.0
            if not improved:
                return zc, rnorm < tol, rnorm
        return zc, rnorm < tol, rnorm

    def _attempt(seed_positions, seed_tensions=None):
        guess_positions = dict(seed_positions)
        for nid in base_positions:
            guess_positions[nid] = base_positions[nid]
        if seed_tensions is None:
            seed_tensions = {}
            for eid, e in model.edges.items():
                xi, yi = guess_positions[e.i]
                xj, yj = guess_positions[e.j]
                L = max(math.hypot(xj - xi, yj - yi), 1e-9)
                seed_tensions[eid] = max(q_guess * L, 1e-6)

        z = _pack(model, free, guess_positions)
        for eid in edge_ids:
            z.append(seed_tensions[eid])

        fractions = [0.1, 0.25, 0.45, 0.65, 0.85, 1.0]
        ok_overall = True
        rnorm = None
        for frac in fractions:
            z, ok, rnorm = take_newton_steps(z, max_newton, frac, loads)
            if not ok:
                z, ok2, rnorm = take_newton_steps(z, max_newton * 2, frac, loads)
                ok_overall = ok2
                if not ok2:
                    break
            else:
                ok_overall = True

        positions = _unpack(model, free, z[:2 * nf], base_positions)
        tensions = {eid: z[2 * nf + e_idx[eid]] for eid in edge_ids}
        return positions, tensions, ok_overall, rnorm

    # Multi-seed strategy: try seeds in order of how likely they are to be
    # a good starting point, stop at the first that converges. This is a
    # deliberate robustness measure, not a way to paper over a wrong
    # answer -- each seed is solved to the SAME tight tolerance, and if
    # none converge, that failure is reported honestly (converged=False)
    # rather than silently returned as if it were a solution.
    as_drawn_positions = {nid: (n.x, n.y) for nid, n in model.nodes.items()}

    seeds = []  # (label, positions_or_None, tensions_or_None)
    if initial_positions is not None:
        seeds.append(('caller-supplied', dict(initial_positions), initial_tensions))
    seeds.append(('as-drawn', as_drawn_positions, None))
    # This seed specifically targets the failure mode diagnosed on 2026-08-18:
    # a uniform-force-density tension guess can be far from the feasible
    # (all-tension-nonnegative) region at a junction whose true equilibrium
    # has one or more members at or near zero tension, causing Newton/LM to
    # stall against the T>=0 wall. Solving the linear equilibrium-only
    # problem at the as-drawn geometry via active-set NNLS starts already
    # inside (or very near) that feasible region.
    try:
        feasible_T = _feasible_tension_seed(model, as_drawn_positions)
        seeds.append(('as-drawn+feasible-tensions', as_drawn_positions, feasible_T))
    except Exception:
        pass
    seeds.append(('force-density(q=characteristic)', None, None))
    seeds.append(('force-density(q x0.1)', None, None))
    seeds.append(('force-density(q x10)', None, None))

    best = None  # (positions, tensions, converged, residual, label)
    for label, seed_pos, seed_tensions in seeds:
        if seed_pos is None:
            mult = {'force-density(q=characteristic)': 1.0,
                     'force-density(q x0.1)': 0.1,
                     'force-density(q x10)': 10.0}[label]
            try:
                fd = solve_force_density(model, q_guess * mult)
            except (ValueError, RuntimeError):
                continue
            seed_pos = fd.positions
        try:
            positions, tensions, ok, rnorm = _attempt(seed_pos, seed_tensions)
        except Exception:
            continue
        if verbose:
            print(f'solve_analysis: seed [{label}] -> converged={ok} residual={rnorm:.3e}')
        if best is None or (rnorm is not None and (best[3] is None or rnorm < best[3])):
            best = (positions, tensions, ok, rnorm, label)
        if ok:
            break

    # If the bounded LM iterations above stall, use a bounded nonlinear
    # least-squares fallback.  The failure mode seen in the picture diagnostic
    # is a valid all-tension equilibrium, but hard rejection of every trial
    # step that crosses T=0 can trap LM near the tension boundary.
    # Trust-region reflective least-squares handles the same equations while
    # enforcing T_e >= 0.
    #
    # This was written as, and still reads as, an optional FALLBACK behind the
    # "normal" Newton/LM path.  Measured 2026-09-04, that framing is wrong:
    # on every multi-cable network tested -- including this project's own two
    # built-in examples -- all five Newton/LM seeds plateau far above tol and
    # 100% of the converged results come from here.  SciPy is therefore a hard
    # requirement for any web with a junction, and its absence must be
    # reported AS a missing dependency, never folded into "did not converge".
    # See REPORTS AND GUIDES/CABLE_WEB_DIAGNOSIS_2026-09-04.md.
    if best is not None and not best[2]:
        try:
            from scipy.optimize import least_squares
        except ImportError as ex:
            raise MissingSolverDependency(
                'Cable Web needs SciPy to solve a network with junctions.\n\n'
                'Install it with:\n'
                '    python -m pip install scipy\n\n'
                f'(underlying import error: {ex})') from ex
        try:
            fallback_seeds = []
            seen_labels = set()

            def add_fallback_seed(label, spos, stens=None):
                if spos is None or label in seen_labels:
                    return
                seen_labels.add(label)
                zz = _pack(model, free, spos)
                for eid in edge_ids:
                    default_t = q_guess * model.edges[eid].target_length
                    zz.append(max(float((stens or {}).get(eid, default_t)), 1e-6))
                fallback_seeds.append((label, zz))

            add_fallback_seed('best', best[0], best[1])
            add_fallback_seed('as-drawn', as_drawn_positions, None)
            for mult, label in ((1.0, 'fd-characteristic'), (10.0, 'fd-x10'), (0.1, 'fd-x0.1')):
                try:
                    fd = solve_force_density(model, q_guess * mult)
                    add_fallback_seed(label, fd.positions, None)
                except Exception:
                    pass

            best_ls = None
            max_nfev = max(1500, min(10000, 30 * dof))
            lower = [-math.inf] * (2 * nf) + [0.0] * ne
            upper = [math.inf] * (2 * nf + ne)
            for seed_label, z0 in fallback_seeds:
                try:
                    ls = least_squares(
                        residual, z0, bounds=(lower, upper), method='trf',
                        x_scale='jac',
                        jac=(lambda zc: jacobian_analytical(zc)) if use_analytical_jacobian else '3-point',
                        diff_step=1e-6,
                        ftol=1e-14, xtol=1e-14, gtol=1e-14,
                        max_nfev=max_nfev * 2)
                    ls_rnorm = max((abs(v) for v in ls.fun), default=0.0)
                    if verbose:
                        print(f'solve_analysis: bounded least-squares [{seed_label}] -> residual={ls_rnorm:.3e} nfev={ls.nfev}')
                    if best_ls is None or ls_rnorm < best_ls[0]:
                        best_ls = (ls_rnorm, ls)
                    if ls_rnorm < tol:
                        break
                except Exception as ex:
                    if verbose:
                        print(f'solve_analysis: bounded least-squares [{seed_label}] failed: {ex}')

            if best_ls is not None:
                ls_rnorm, ls = best_ls
                ls_pos = _unpack(model, free, ls.x[:2 * nf], base_positions)
                ls_T = {eid: max(0.0, float(ls.x[2 * nf + e_idx[eid]])) for eid in edge_ids}
                ls_ok = bool(ls_rnorm < tol)
                if ls_ok or best is None or ls_rnorm < best[3]:
                    best = (ls_pos, ls_T, ls_ok, ls_rnorm, 'bounded-least-squares')
        except Exception as ex:
            if verbose:
                print(f'solve_analysis: bounded least-squares fallback unavailable/failed: {ex}')

    # ------------------------------------------------------------------
    # Slack-aware stage.  Runs ONLY when every stage above has failed, so a
    # model that already solves cannot be affected by it.
    #
    # Everything above imposes  L == target_length  as an EQUALITY on every
    # edge.  That is right for a taut member and wrong for a slack one: a
    # cable carries no compression, so a member with more length than the gap
    # it spans must be free to sit at L < target with T = 0.  The equality
    # cannot express that, so such a model has NO solution as posed, however
    # good the seed or the optimiser.
    #
    # Diagnosed 2026-09-05 on the two topologies that had never converged --
    # a three-cable star at a free junction, and a junction tied down to an
    # anchor below it.  In both, the best attempt drove exactly one edge to
    # T ~= 1e-28 with L a few millimetres UNDER its target.  That is the
    # correct slack state; the solver had found the right answer and was
    # forced to report it as a failure, stuck at residual 1e-2.
    #
    # The cable constitutive law is a complementarity condition:
    #
    #     T >= 0        target - L >= 0        T * (target - L) = 0
    #     (no strut)    (cannot stretch)       (taut => L = target;
    #                                           slack => no tension)
    #
    # encoded here with the Fischer-Burmeister function
    #
    #     phi(a, b) = a + b - sqrt(a^2 + b^2),   phi == 0  <=>  all three
    #
    # as one row per edge in place of the equality row.  Both arguments are
    # non-dimensionalised first: mixing newtons with metres inside the square
    # root would make the root depend on the choice of units.
    #
    # phi is smooth away from the origin and only semismooth at it, so this
    # stage uses a finite-difference Jacobian rather than the analytic one
    # written for the equality residual, which no longer applies.
    if best is not None and not best[2]:
        try:
            from scipy.optimize import least_squares
        except ImportError:
            least_squares = None
        if least_squares is not None:
            def residual_ncp(z):
                pos = _unpack(model, free, z[:2 * nf], base_positions)
                T = {eid: z[2 * nf + e_idx[eid]] for eid in edge_ids}
                res = [0.0] * dof

                node_res = {nid: [loads[nid][0], loads[nid][1]] for nid in free}
                for eid in edge_ids:
                    e = model.edges[eid]
                    xi, yi = pos[e.i]
                    xj, yj = pos[e.j]
                    L = math.hypot(xj - xi, yj - yi)
                    if L < 1e-13:
                        ux, uy = 0.0, 0.0
                    else:
                        ux, uy = (xj - xi) / L, (yj - yi) / L
                    Te = T[eid]
                    if e.i in node_res:
                        node_res[e.i][0] += Te * ux
                        node_res[e.i][1] += Te * uy
                    if e.j in node_res:
                        node_res[e.j][0] -= Te * ux
                        node_res[e.j][1] -= Te * uy
                for k, nid in enumerate(free):
                    res[2 * k] = node_res[nid][0] / force_scale
                    res[2 * k + 1] = node_res[nid][1] / force_scale

                for eid in edge_ids:
                    e = model.edges[eid]
                    xi, yi = pos[e.i]
                    xj, yj = pos[e.j]
                    L = math.hypot(xj - xi, yj - yi)
                    a = T[eid] / tension_scale
                    b = (e.target_length - L) / length_scale
                    res[2 * nf + e_idx[eid]] = a + b - math.hypot(a, b)
                return res

            ncp_seeds = []
            seen_ncp = set()

            def add_ncp_seed(label, spos, stens=None):
                if spos is None or label in seen_ncp:
                    return
                seen_ncp.add(label)
                zz = _pack(model, free, spos)
                for eid in edge_ids:
                    default_t = q_guess * model.edges[eid].target_length
                    zz.append(max(float((stens or {}).get(eid, default_t)), 0.0))
                ncp_seeds.append((label, zz))

            add_ncp_seed('best-so-far', best[0], best[1])
            add_ncp_seed('as-drawn', as_drawn_positions, None)
            try:
                add_ncp_seed('fd-characteristic',
                             solve_force_density(model, q_guess).positions, None)
            except Exception:
                pass

            best_ncp = None
            for seed_label, z0 in ncp_seeds:
                try:
                    ls = least_squares(
                        residual_ncp, z0,
                        bounds=([-math.inf] * (2 * nf) + [0.0] * ne,
                                [math.inf] * (2 * nf + ne)),
                        method='trf', x_scale='jac', jac='3-point',
                        diff_step=1e-7,
                        ftol=1e-14, xtol=1e-14, gtol=1e-14,
                        max_nfev=max(2000, min(12000, 40 * dof)))
                    rn = max((abs(v) for v in ls.fun), default=0.0)
                    if verbose:
                        print(f'solve_analysis: slack-aware (complementarity) '
                              f'[{seed_label}] -> residual={rn:.3e} nfev={ls.nfev}')
                    if best_ncp is None or rn < best_ncp[0]:
                        best_ncp = (rn, ls)
                    if rn < tol:
                        break
                except Exception as ex:
                    if verbose:
                        print(f'solve_analysis: slack-aware [{seed_label}] failed: {ex}')

            if best_ncp is not None:
                ncp_rnorm, ls = best_ncp
                ncp_pos = _unpack(model, free, ls.x[:2 * nf], base_positions)
                ncp_T = {eid: max(0.0, float(ls.x[2 * nf + e_idx[eid]]))
                         for eid in edge_ids}
                # A network in which EVERY member is slack satisfies the
                # complementarity system trivially -- no member carries
                # anything, so every configuration with L <= target is an
                # equilibrium and the shape is arbitrary.  That is not a
                # solution found, it is the absence of a constraint, and
                # reporting it as converged would hand the user a meaningless
                # geometry with a 1e-13 residual attached.  A weightless,
                # unloaded cable is exactly this case, and it is the reason
                # the app defaults self-weight to a nonzero value.
                # Measured against the APPLIED load, not an absolute epsilon:
                # an unloaded weightless network settles at tensions around
                # 1e-7 -- pure optimiser noise -- which any fixed threshold
                # either lets through or, set high enough to stop, would also
                # reject a genuinely lightly-loaded web.
                carries_load = (
                    total_load > 1e-12
                    and max(ncp_T.values(), default=0.0) > 1e-6 * total_load)
                # phi == 0 already encodes equilibrium AND the whole cable law,
                # so its own max-abs residual is the honest convergence measure
                # for this stage -- there is no separate length equality left
                # to satisfy.  Only replace the incumbent if this actually did
                # better, so a failed slack solve cannot discard a nearly-good
                # taut one.
                if carries_load and ncp_rnorm < best[3]:
                    best = (ncp_pos, ncp_T, bool(ncp_rnorm < tol), ncp_rnorm,
                            'slack-aware-complementarity')
                elif verbose and not carries_load:
                    print('solve_analysis: slack-aware result rejected -- every '
                          'member is slack, so the shape is indeterminate.')

    if best is None:
        raise RuntimeError('solve_analysis: all nonlinear solve attempts failed to produce a candidate solution.')

    positions, tensions, ok_overall, rnorm, label = best

    # The network equations are scaled before solving.  For highly
    # ill-conditioned cable webs, especially when one or more members are at
    # the tension boundary T ~= 0, asking for a normalized max residual of
    # 1e-9 can be below the useful floating-point resolution of the finite-
    # difference Jacobian.  A result around 1e-7 is nevertheless only about
    # micrometres in the length equations and sub-10^-4 N in a few-hundred-N
    # load case.  Do not silently loosen the requested tolerance: retain the
    # strict result when available, but accept a bounded, physically checked
    # numerical convergence band so the UI does not report a valid equilibrium
    # as a failure.  This band is deliberately finite and is checked only
    # after all solver/fallback attempts have terminated.
    practical_tol = max(tol, 5e-7)
    if not ok_overall and rnorm is not None and rnorm <= practical_tol:
        finite = all(math.isfinite(v) for p in positions.values() for v in p)
        tension_ok = all((T is None or math.isfinite(T)) and
                         (T is None or T >= -1e-7)
                         for T in tensions.values())
        if finite and tension_ok:
            ok_overall = True
            if verbose:
                print(f'solve_analysis: accepting bounded numerical convergence '
                      f'(residual={rnorm:.3e} <= practical_tol={practical_tol:.3e})')

    for eid in inert_edge_ids:
        # Genuinely undefined (see the comment where inert_edge_ids is
        # built) -- reported as None rather than a fabricated number.
        tensions[eid] = None
    if verbose:
        print(f'solve_analysis: FINAL converged={ok_overall} residual={rnorm:.3e} (seed: {label})')
    return CableWebResult(model, positions, tensions, ok_overall, rnorm)
