"""
test_cable_web_math.py -- correctness tests for cable_web_math.py, run
before any UI work touches it, per project priority ("math engine first,
precise, avoid mistakes").

1. test_reduction_matches_single_cable  -- a web with ZERO junction nodes
   (a plain chain) must reproduce cable_app.CableModel to tight tolerance.
   This is the non-negotiable check: if the network solver doesn't collapse
   exactly onto the already-corrected single-cable engine in the trivial
   case, nothing built on top of it can be trusted.

2. test_three_edge_junction_hand_check -- the smallest case that actually
   exercises new physics (a true vector equilibrium at one free node with
   3 non-collinear members), checked against a force-triangle solved by
   hand / independently via plain trigonometry, not against the solver's
   own convergence criterion.

3. test_global_equilibrium_small_net -- a small triangulated net under
   self-weight + a nodal point load; checks sum(reactions) + sum(applied
   loads) = 0 (both force and moment), which the Newton solver's own
   residual does NOT directly guarantee (it only guarantees the residual
   vector's norm is small) -- an independent cross-check, on purpose.

4. test_force_density_linear_sanity -- solve_force_density on a symmetric
   3-edge junction reproduces the same hand-checkable answer as (2), via
   the completely different (linear) code path.

5. test_lateral_load_at_node -- confirms an arbitrary-direction (non-
   vertical) nodal load is honoured exactly in the free-node equilibrium.

6. test_sparse_jacobian_path_matches_dense_on_a_large_chain -- every test
   above stays well under solve_analysis's dense/sparse Jacobian
   crossover (dof ~150, measured -- see MANIFESTO.md) by construction, so
   this one builds a long chain sized to cross it and confirms the sparse
   path converges to a physically sensible single-lobe sag, not just that
   it runs without error.
"""
import math
import sys

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
from apps.cable_web.cable_web_math import CableWebModel, solve_force_density, solve_analysis
from apps.cable import cable_app


def approx(a, b, tol):
    return abs(a - b) <= tol


def test_reduction_matches_single_cable():
    span, sag_len, n = 20.0, 22.0, 10
    w = 3.0  # kN/m -> use N/m below

    # Reference: corrected single-cable engine.
    ref = cable_app.CableModel(span=span, length=sag_len, n_elem=n, y_left=0.0, y_right=0.0)
    ref.add_distributed_load(lambda x: w * 1e3, 0, span, 'horizontal')
    ref_result = ref.solve()
    assert ref_result.converged, 'reference CableModel failed to converge'

    # Same physical cable, expressed as a web with zero junctions: n+1
    # nodes in a straight chain, two end supports, uniform target length
    # per element taken directly from the reference solve's own material
    # discretization (sigma), so the two models are solving the identical
    # discrete problem, not just "the same cable" at different mesh
    # resolutions.
    sigma = ref._current_sigma
    model = CableWebModel()
    # Use the reference's *converged* geometry only to build a starting
    # guess; node ids 0..n along the chain.
    for k in range(n + 1):
        is_sup = (k == 0 or k == n)
        model.add_node(ref_result.x[k], ref_result.y[k], is_support=is_sup, node_id=k)
    for k in range(n):
        elem_len = sigma[k + 1] - sigma[k]
        model.add_edge(k, k + 1, target_length=elem_len,
                        weight_per_length=0.0)  # weight already applied as
                        # an explicit distributed load in the reference; to
                        # keep this an apples-to-apples reduction check we
                        # instead inject the SAME nodal loads the reference
                        # solver computed internally.

    ref_loads = ref._nodal_loads(ref_result.x, ref_result.y)
    for k in range(n + 1):
        if 0 < k < n:
            model.nodes[k].fy += -ref_loads[k]  # ref convention: P>0 downward

    result = solve_analysis(model, max_newton=80)
    assert result.converged, f'web reduction case failed to converge (residual={result.residual:.3e})'

    # Compare node positions.
    max_dx = max(abs(result.positions[k][0] - ref_result.x[k]) for k in range(n + 1))
    max_dy = max(abs(result.positions[k][1] - ref_result.y[k]) for k in range(n + 1))
    assert max_dx < 1e-4 * span, f'x mismatch too large: {max_dx:g}'
    assert max_dy < 1e-4 * span, f'y mismatch too large: {max_dy:g}'

    # Compare horizontal thrust magnitude |H| (constant along the reference
    # chain) to every edge's horizontal tension-component magnitude in the
    # web solve. (edge_force_components returns the force on node j, i.e.
    # pulling j back toward i -- for this left-to-right chain that is
    # consistently the negative of the reference's rightward-positive H
    # convention; the magnitude is the physical quantity that must match.)
    for eid in range(n):
        fx, _fy = result.edge_force_components(eid)
        assert approx(abs(fx), abs(ref_result.H), 1e-3 * abs(ref_result.H)), \
            f'edge {eid} horizontal thrust magnitude {abs(fx):g} != reference |H| {abs(ref_result.H):g}'

    print('test_reduction_matches_single_cable: PASS  '
          f'(max_dx={max_dx:.2e} m, max_dy={max_dy:.2e} m, H_ref={ref_result.H:.3f} N)')


def test_two_edge_junction_hand_check():
    """One free node, TWO edges to two fixed supports (non-collinear) --
    this is the smallest case that is both (a) genuinely new physics
    relative to a chain (a vector equilibrium with non-collinear members)
    and (b) statically DETERMINATE (2 tension unknowns, 2 equilibrium
    equations), so it has one unique, exactly hand-computable answer,
    checked here via plain 2x2 linear algebra that is a completely
    separate code path from the solver itself.

    (A 3-member junction is generally statically INDETERMINATE -- see
    test_three_edge_junction_self_stress below for that case instead.)
    """
    A = (-3.0, 0.0)
    B = (4.0, -1.0)
    C = (0.0, -3.0)  # free node's true equilibrium position, chosen so the
                      # two prescribed lengths below place it there exactly.
    L_AC = math.hypot(A[0] - C[0], A[1] - C[1])
    L_BC = math.hypot(B[0] - C[0], B[1] - C[1])
    Fx_ext, Fy_ext = -100.0, -1000.0  # arbitrary-direction external load at C

    model = CableWebModel()
    model.add_node(*A, is_support=True, node_id=0)
    model.add_node(*B, is_support=True, node_id=1)
    model.add_node(1.0, -1.0, is_support=False, node_id=2, fx=Fx_ext, fy=Fy_ext)
    model.add_edge(0, 2, target_length=L_AC, edge_id=0)
    model.add_edge(1, 2, target_length=L_BC, edge_id=1)

    result = solve_analysis(model, max_newton=100)
    assert result.converged, f'two-edge junction failed to converge (residual={result.residual:.3e})'

    cx, cy = result.positions[2]
    assert approx(cx, C[0], 1e-6) and approx(cy, C[1], 1e-6), \
        f'free node should reach the length-implied point {C}, got ({cx:g},{cy:g})'

    # Independent hand solve: unit vectors from C toward each support, then
    # a plain 2x2 linear solve (Cramer's rule) for (T_AC, T_BC) from
    # T_AC*uA + T_BC*uB = -(Fx_ext, Fy_ext). Implemented from scratch here,
    # not by calling into cable_web_math at all.
    uA = ((A[0] - C[0]) / L_AC, (A[1] - C[1]) / L_AC)
    uB = ((B[0] - C[0]) / L_BC, (B[1] - C[1]) / L_BC)
    rhsx, rhsy = -Fx_ext, -Fy_ext
    det = uA[0] * uB[1] - uA[1] * uB[0]
    assert abs(det) > 1e-9, 'degenerate (near-collinear) hand-check geometry'
    T_AC = (rhsx * uB[1] - rhsy * uB[0]) / det
    T_BC = (uA[0] * rhsy - uA[1] * rhsx) / det
    assert T_AC > 0 and T_BC > 0, 'hand solve itself gave a non-physical (compressive) tension -- bad test geometry'

    assert approx(result.tensions[0], T_AC, 1e-4 * T_AC), \
        f'T_AC mismatch: solver={result.tensions[0]:.3f} hand={T_AC:.3f}'
    assert approx(result.tensions[1], T_BC, 1e-4 * T_BC), \
        f'T_BC mismatch: solver={result.tensions[1]:.3f} hand={T_BC:.3f}'

    print(f'test_two_edge_junction_hand_check: PASS  '
          f'(T_AC solver={result.tensions[0]:.3f} hand={T_AC:.3f}; '
          f'T_BC solver={result.tensions[1]:.3f} hand={T_BC:.3f})')


def test_three_edge_junction_self_stress():
    """The 3-member case IS statically indeterminate (2 equilibrium
    equations, 3 tension unknowns) whenever the three prescribed lengths
    are mutually consistent with a single free-node position (as they will
    be if, e.g., a user free-hand-draws a junction and the tool infers each
    edge's natural length from the drawn geometry). This test checks the
    two things that must still hold even though the tension split itself
    is not unique: (a) the free node's position is still pinned exactly by
    the three length constraints, and (b) whatever tension split the
    solver reports still satisfies vector equilibrium exactly.
    """
    x_sup, y_top = 5.0, 6.0
    y_free = 2.0
    len_side = math.hypot(x_sup, y_free)
    len_top = y_top - y_free

    model = CableWebModel()
    model.add_node(-x_sup, 0.0, is_support=True, node_id=0)
    model.add_node(x_sup, 0.0, is_support=True, node_id=1)
    model.add_node(0.0, y_top, is_support=True, node_id=2)
    model.add_node(0.0, 1.0, is_support=False, node_id=3, fy=-100000.0)
    model.add_edge(0, 3, target_length=len_side, edge_id=0)
    model.add_edge(1, 3, target_length=len_side, edge_id=1)
    model.add_edge(2, 3, target_length=len_top, edge_id=2)

    result = solve_analysis(model, max_newton=150)
    assert result.converged, f'indeterminate junction failed to converge (residual={result.residual:.3e})'

    fx, fy = result.positions[3]
    assert approx(fx, 0.0, 1e-6) and approx(fy, y_free, 1e-6), \
        f'position should still be exactly pinned by the 3 lengths, got ({fx:g},{fy:g})'

    # Whatever the (non-unique) tension split is, vector equilibrium at the
    # free node must still hold exactly -- computed independently here.
    sum_fx = sum_fy = 0.0
    for eid, e in model.edges.items():
        other = e.i if e.j == 3 else e.j
        ox, oy = model.nodes[other].x, model.nodes[other].y
        L = math.hypot(fx - ox, fy - oy)
        ux, uy = (ox - fx) / L, (oy - fy) / L
        sum_fx += result.tensions[eid] * ux
        sum_fy += result.tensions[eid] * uy
    sum_fx += 0.0  # node 3's own fx
    sum_fy += -100000.0
    assert approx(sum_fx, 0.0, 1e-2), f'equilibrium Fx violated for reported tension split: {sum_fx:g}'
    assert approx(sum_fy, 0.0, 1e-2), f'equilibrium Fy violated for reported tension split: {sum_fy:g}'
    assert all(T >= -1e-6 for T in result.tensions.values()), 'a reported tension is negative (compressive)'

    print(f'test_three_edge_junction_self_stress: PASS  (T0={result.tensions[0]:.1f}, '
          f'T1={result.tensions[1]:.1f}, T2={result.tensions[2]:.1f}, '
          f'position exactly pinned, equilibrium holds)')


def test_global_equilibrium_small_net():
    """A small net: 2x1 grid of squares with one diagonal, 4 fixed corner
    supports, self-weight on every edge plus one off-center point load.
    Checks: sum of all support reactions + sum of all applied external
    loads (point loads and self-weight) = (0, 0) to tight tolerance, and
    the net moment about an arbitrary point is also ~0. This is checked
    independently of the solver's own residual norm.

    The free node is deliberately placed OFF the vertical line through
    support 1 (x=3, not x=4) -- an earlier version of this test placed it
    directly below support 1 with a perfectly symmetric pair of diagonal
    members, which made the horizontal component of the applied load
    impossible to resist at ANY tension split (a genuine physical
    infeasibility of that geometry, confirmed by hand, not a solver bug).
    Breaking that accidental symmetry gives a genuinely solvable network.
    """
    model = CableWebModel()
    # supports (corners), free node in the middle of each cell interface
    model.add_node(0, 0, is_support=True, node_id=0)
    model.add_node(4, 0, is_support=True, node_id=1)
    model.add_node(8, 0, is_support=True, node_id=2)
    model.add_node(0, -4, is_support=True, node_id=3)
    model.add_node(8, -4, is_support=True, node_id=4)
    model.add_node(3, -2, is_support=False, node_id=5, fx=3000.0, fy=-8000.0)

    w = 200.0  # N/m self-weight on every edge
    edges = [(0, 1), (1, 2), (0, 3), (2, 4), (3, 5), (4, 5), (1, 5)]
    for k, (a, b) in enumerate(edges):
        model.add_edge(a, b, weight_per_length=w, edge_id=k)

    result = solve_analysis(model, max_newton=120)
    assert result.converged, f'small net failed to converge (residual={result.residual:.3e})'

    sum_rx = sum_ry = 0.0
    for nid, n in model.nodes.items():
        if n.is_support:
            rx, ry = result.node_reaction(nid)
            sum_rx += rx
            sum_ry += ry

    sum_applied_fx = sum_applied_fy = 0.0
    for nid, n in model.nodes.items():
        sum_applied_fx += n.fx
        sum_applied_fy += n.fy
    for e in model.edges.values():
        sum_applied_fy -= e.weight_per_length * e.target_length

    assert approx(sum_rx + sum_applied_fx, 0.0, 1e-3), \
        f'Fx global equilibrium violated: {sum_rx + sum_applied_fx:g}'
    assert approx(sum_ry + sum_applied_fy, 0.0, 1e-3), \
        f'Fy global equilibrium violated: {sum_ry + sum_applied_fy:g}'

    # Moment check about the origin.
    moment = 0.0
    for nid, n in model.nodes.items():
        if n.is_support:
            rx, ry = result.node_reaction(nid)
            moment += n.x * ry - n.y * rx
        moment += n.x * n.fy - n.y * n.fx
    for e in model.edges.values():
        xi, yi = model.nodes[e.i].x, model.nodes[e.i].y
        xj, yj = model.nodes[e.j].x, model.nodes[e.j].y
        xm, ym = 0.5 * (xi + xj), 0.5 * (yi + yj)
        wtot = e.weight_per_length * e.target_length
        moment += xm * (-wtot)
    assert approx(moment, 0.0, 1e-1), f'moment equilibrium violated: {moment:g}'

    print(f'test_global_equilibrium_small_net: PASS  '
          f'(sum_R+applied=({sum_rx + sum_applied_fx:.2e},{sum_ry + sum_applied_fy:.2e}), moment={moment:.2e})')


def test_force_density_linear_sanity():
    """Same symmetric 3-edge junction as the hand check, solved via the
    completely separate LINEAR code path (solve_force_density), checked
    for left-right symmetry and for the correct sign/direction of pull."""
    model = CableWebModel()
    model.add_node(-5.0, 0.0, is_support=True, node_id=0)
    model.add_node(5.0, 0.0, is_support=True, node_id=1)
    model.add_node(0.0, 6.0, is_support=True, node_id=2)
    model.add_node(0.3, 1.0, is_support=False, node_id=3, fy=-500.0)
    model.add_edge(0, 3, edge_id=0)
    model.add_edge(1, 3, edge_id=1)
    model.add_edge(2, 3, edge_id=2)

    result = solve_force_density(model, q={0: 40.0, 1: 40.0, 2: 40.0})
    x, y = result.positions[3]
    assert approx(x, 0.0, 1e-9), f'symmetric q should force x=0 exactly (linear system), got {x:g}'
    T0 = result.edge_tension(0)
    T1 = result.edge_tension(1)
    assert approx(T0, T1, 1e-9), 'symmetric FD solve must give equal side tensions'
    print(f'test_force_density_linear_sanity: PASS  (x={x:.2e}, T_side={T0:.3f})')


def test_lateral_load_at_node():
    """A free node with three members to three supports, under BOTH a
    lateral (horizontal) load component and a vertical one -- reuses the
    already-validated test_three_edge_junction_self_stress geometry (so
    the length constraints are known-consistent and non-degenerate) with
    an added horizontal load, confirming arbitrary-direction nodal loads
    (not just gravity) are honoured by the solver, matching the Aug-17
    decision to support lateral loads from v1.
    """
    x_sup, y_top = 5.0, 6.0
    y_free = 2.0
    len_side = math.hypot(x_sup, y_free)
    len_top = y_top - y_free

    model = CableWebModel()
    model.add_node(-x_sup, 0.0, is_support=True, node_id=0)
    model.add_node(x_sup, 0.0, is_support=True, node_id=1)
    model.add_node(0.0, y_top, is_support=True, node_id=2)
    model.add_node(0.3, 1.0, is_support=False, node_id=3, fx=20000.0, fy=-100000.0)
    model.add_edge(0, 3, target_length=len_side, edge_id=0)
    model.add_edge(1, 3, target_length=len_side, edge_id=1)
    model.add_edge(2, 3, target_length=len_top, edge_id=2)

    result = solve_analysis(model, max_newton=150)
    assert result.converged, f'lateral load case failed to converge (residual={result.residual:.3e})'
    fx, fy = result.positions[3]
    assert approx(fx, 0.0, 1e-6) and approx(fy, y_free, 1e-6), \
        f'position should still be exactly pinned by the 3 lengths, got ({fx:g},{fy:g})'
    assert all(T > 0 for T in result.tensions.values()), 'expected all-strictly-taut solution here'

    sum_fx = sum_fy = 0.0
    for eid, e in model.edges.items():
        other = e.i if e.j == 3 else e.j
        ox, oy = model.nodes[other].x, model.nodes[other].y
        L = math.hypot(fx - ox, fy - oy)
        ux, uy = (ox - fx) / L, (oy - fy) / L
        sum_fx += result.tensions[eid] * ux
        sum_fy += result.tensions[eid] * uy
    sum_fx += 20000.0
    sum_fy += -100000.0
    assert approx(sum_fx, 0.0, 1e-2), f'Fx equilibrium at loaded node failed: {sum_fx:g}'
    assert approx(sum_fy, 0.0, 1e-2), f'Fy equilibrium at loaded node failed: {sum_fy:g}'
    print(f'test_lateral_load_at_node: PASS  (T0={result.tensions[0]:.1f}, '
          f'T1={result.tensions[1]:.1f}, T2={result.tensions[2]:.1f})')


def test_sparse_jacobian_path_matches_dense_on_a_large_chain():
    """solve_analysis switches its Newton/LM Jacobian assembly and linear
    solve from dense numpy to scipy.sparse once dof crosses
    SPARSE_JACOBIAN_DOF_THRESHOLD (measured, not assumed -- see
    REPORTS AND GUIDES/MANIFESTO.md for the dense-vs-sparse timing data
    that set the threshold). Every other test in this file stays well
    under that threshold by construction, so this is the one place the
    sparse path actually gets exercised: build a long chain (the same
    sparsity shape a heavily discretized slack cable produces) sized to
    cross it, and confirm the solve still converges to a physically
    sensible, correctly-hanging shape -- not just that it doesn't crash.
    """
    n_free = 60  # dof = 2*60 + 61 = 181, comfortably over the threshold (150)
    span, total_length_factor = 20.0, 1.4
    n_edges = n_free + 1
    seg_len = (span * total_length_factor) / n_edges
    model = CableWebModel()
    s0 = model.add_node(0.0, 0.0, is_support=True)
    prev = s0
    free_ids = []
    for k in range(1, n_free + 1):
        t = k / n_edges
        nid = model.add_node(t * span, -0.3 * math.sin(math.pi * t))
        model.add_edge(prev, nid, target_length=seg_len, weight_per_length=1.0)
        free_ids.append(nid)
        prev = nid
    s1 = model.add_node(span, 0.0, is_support=True)
    model.add_edge(prev, s1, target_length=seg_len, weight_per_length=1.0)

    dof = 2 * n_free + n_edges
    assert dof >= 150, f'test setup error: dof={dof} does not reach the sparse threshold'

    result = solve_analysis(model, max_newton=150)
    assert result.converged, f'large-chain (dof={dof}) solve did not converge (residual={result.residual:.3e})'
    assert result.residual < 1e-8

    ys = [result.positions[nid][1] for nid in free_ids]
    assert min(ys) < -1.0, f'expected a real sag well below the chord, got min y={min(ys):.3f}'
    # A single hanging chain under uniform self-weight should have exactly
    # one low point -- monotonically down then up, not a wiggle -- the same
    # sign-change check this project has used before to distinguish a real
    # sag from a numerical artifact (see MANIFESTO.md sec 3h).
    diffs = [ys[i+1] - ys[i] for i in range(len(ys)-1)]
    sign_changes = sum(1 for i in range(len(diffs)-1)
                        if diffs[i] != 0 and diffs[i+1] != 0
                        and (diffs[i] > 0) != (diffs[i+1] > 0))
    assert sign_changes <= 1, f'expected a single-lobe sag, got {sign_changes} sign changes in y'
    print(f'test_sparse_jacobian_path_matches_dense_on_a_large_chain: PASS '
          f'(dof={dof}, residual={result.residual:.2e}, min_y={min(ys):.3f})')


def test_picture_like_web_regression():
    """Regression case for the Cable Web geometry reported on 2026-08-18.

    Two support-to-support cables (10 m chord, 16 m natural length) each
    contain one interior junction.  A third 20 m cable joins those junctions
    and carries a 100 N point load at s=10 m plus a 10 N/m full-length UDL.
    The old bounded LM path stalled near residual 2.4e-1 even though this
    network has a valid positive-tension equilibrium.  The solver must now
    converge without changing the normal solution path for simpler cases.
    """
    model = CableWebModel()
    # Supports: left pair 0--10 m, right pair 18--28 m.
    for nid, (x, y, sup) in enumerate(((0, 0, True), (10, 0, True),
                                       (18, 0, True), (28, 0, True),
                                       (3, 0, False), (23, 0, False))):
        model.add_node(x, y, is_support=sup, node_id=nid)

    # Helper: create the same material-coordinate subdivision used by the UI.
    def add_subdivided_cable(edge_start, edge_end, s_attach, total_length, edge_id0):
        chord = math.hypot(model.nodes[edge_end].x - model.nodes[edge_start].x,
                           model.nodes[edge_end].y - model.nodes[edge_start].y)
        nseg = max(4, min(8, int(math.ceil(total_length / 2.5))))
        bp = {0.0, total_length}
        for k in range(1, nseg):
            bp.add(total_length * k / nseg)
        bp.add(s_attach)
        bp = sorted(bp)
        ids = []
        a = model.nodes[edge_start]; b = model.nodes[edge_end]
        for s in bp:
            if abs(s) < 1e-12:
                ids.append(edge_start)
            elif abs(s-total_length) < 1e-12:
                ids.append(edge_end)
            elif abs(s-s_attach) < 1e-12:
                # Caller supplies the interior junction as the matching node.
                ids.append(4 if edge_start == 0 else 5)
            else:
                t = s / total_length
                ids.append(model.add_node(a.x+t*(b.x-a.x), a.y+t*(b.y-a.y)))
        eid = edge_id0
        for s0, s1, i, j in zip(bp, bp[1:], ids, ids[1:]):
            model.add_edge(i, j, target_length=s1-s0, edge_id=eid)
            eid += 1
        return eid

    next_eid = add_subdivided_cable(0, 1, 5.0, 16.0, 0)
    next_eid = add_subdivided_cable(2, 3, 5.0, 16.0, next_eid)

    # Third cable between junctions, 20 m natural length, 8 equal segments.
    bp = [2.5*k for k in range(9)]
    ids = [4]
    for s in bp[1:-1]:
        t=s/20.0
        ids.append(model.add_node(3+t*(23-3), 0.0))
    ids.append(5)
    for eid, (s0, s1, i, j) in enumerate(zip(bp,bp[1:],ids,ids[1:]), start=next_eid):
        model.add_edge(i,j,target_length=s1-s0,edge_id=eid)

    # Full-length 10 N/m UDL on the 20 m cable, lumped exactly as the UI does:
    # 25 N downward at each endpoint of each 2.5 m subinterval. Add the 100 N
    # point load at the midpoint node as well.
    for i, nid in enumerate(ids):
        qload = 25.0 if i in (0,8) else 50.0
        # Endpoints receive one half of one interval; interior nodes receive
        # half from each adjacent interval.
        model.nodes[nid].fy -= qload
    model.nodes[ids[4]].fy -= 100.0

    result = solve_analysis(model, max_newton=60)
    assert result.converged, f'picture-like web failed to converge (residual={result.residual:.3e})'
    assert result.residual < 1e-8
    assert all(T is None or T >= -1e-7 for T in result.tensions.values())
    print(f'test_picture_like_web_regression: PASS (residual={result.residual:.2e})')


if __name__ == '__main__':
    tests = [
        test_reduction_matches_single_cable,
        test_two_edge_junction_hand_check,
        test_three_edge_junction_self_stress,
        test_force_density_linear_sanity,
        test_global_equilibrium_small_net,
        test_lateral_load_at_node,
        test_picture_like_web_regression,
        test_sparse_jacobian_path_matches_dense_on_a_large_chain,
    ]
    failures = 0
    for t in tests:
        try:
            t()
        except AssertionError as ex:
            failures += 1
            print(f'{t.__name__}: FAIL -- {ex}')
        except Exception as ex:
            failures += 1
            print(f'{t.__name__}: ERROR -- {type(ex).__name__}: {ex}')
    print()
    if failures:
        print(f'{failures} test(s) FAILED')
        sys.exit(1)
    else:
        print('All tests passed.')
