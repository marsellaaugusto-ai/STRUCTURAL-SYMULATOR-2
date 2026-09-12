"""Closed-form and equilibrium checks for the Truss/Vierendeel solver.

This is the table in section 0 of `REPORTS AND GUIDES/DIAGNOSIS_TRUSS_2026-09-05.md`
turned into runnable tests (finding T-4). That diagnosis verified the solver by
hand and found no correctness bug; nothing here is expected to fail today. The
point is that it stays that way -- before this file the tab had NO test the
suite actually ran. `test_truss_load_signs.py` existed but defined only
`main()`, no `test_*` function, so `pytest` collected zero tests from it and
had done so for as long as it has existed.

Conventions used throughout, and easy to get backwards:
  * `nodes` are canvas pixels with **y pointing DOWN**; `PX_PER_M` = 24.
  * a load's `fy` is positive **downward**, and `reactions[i]['ry']` uses the
    same axis -- so an upward reaction reads NEGATIVE.
  * `compute_node_force_vectors` is the exception: it reports in the CAD
    readout's **y-up** frame, because it feeds the node free-body diagrams.
    Mixing the two is the sign error most likely to be introduced here.
"""
import math

import pytest

from common import PX_PER_M
from apps.truss.truss_app import analyze
from apps.truss.truss_math import compute_node_force_vectors


# ── helpers ──────────────────────────────────────────────────────────────────

def solve(nodes, rods, loads, supports):
    result, error = analyze(nodes, rods, loads, supports)
    assert error is None, error
    return result


def global_residuals(nodes, loads, reactions):
    """(sum Fx, sum Fy, sum M about the origin) over applied loads AND support
    reactions, all in the canvas frame (y down). Every one must vanish."""
    sfx = sfy = sm = 0.0
    for ld in loads:
        x, y = nodes[ld['node']]
        sfx += ld['fx']
        sfy += ld['fy']
        sm += (x / PX_PER_M) * ld['fy'] - (y / PX_PER_M) * ld['fx']
    for ni, r in reactions.items():
        x, y = nodes[ni]
        sfx += r['rx']
        sfy += r['ry']
        sm += (x / PX_PER_M) * r['ry'] - (y / PX_PER_M) * r['rx'] + r.get('m', 0.0)
    return sfx, sfy, sm


def joint_residuals(nodes, rods, loads, supports, result):
    """Method of joints at every FREE node: the rod forces meeting there plus
    the applied load must cancel.

    This check needs no reference values at all -- only the model itself -- so
    it applies to any truss a future change might break, which is why the
    diagnosis singled it out as the pattern worth keeping.
    """
    vectors = compute_node_force_vectors(nodes, rods, result['rod_res'])
    supported = {s['node'] for s in supports}
    load_at = {}
    for ld in loads:
        fx, fy = load_at.get(ld['node'], (0.0, 0.0))
        load_at[ld['node']] = (fx + ld['fx'], fy + ld['fy'])

    worst = 0.0
    for ni in range(len(nodes)):
        if ni in supported:
            continue
        fx, fy = load_at.get(ni, (0.0, 0.0))
        # vectors are y-UP, the load is y-DOWN: hence the sign flip on fy.
        rx = sum(v['Fx'] for v in vectors[ni]) + fx
        ry = sum(v['Fy'] for v in vectors[ni]) - fy
        worst = max(worst, abs(rx), abs(ry))
    return worst


def triangle_model(P=100.0, span_m=8.0, rise_m=3.0):
    """Pin-jointed triangle: pin at the left foot, roller at the right, a
    single vertical load P (kN, downward) at the apex."""
    span, rise = span_m * PX_PER_M, rise_m * PX_PER_M
    nodes = [(0.0, 0.0), (span, 0.0), (span / 2.0, -rise)]
    rods = [
        {'a': 0, 'b': 2, 'E': 200.0, 'A': 10.0},
        {'a': 2, 'b': 1, 'E': 200.0, 'A': 10.0},
        {'a': 0, 'b': 1, 'E': 200.0, 'A': 10.0},
    ]
    loads = [{'node': 2, 'fx': 0.0, 'fy': P}]
    supports = [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'rollerX'}]
    return nodes, rods, loads, supports


def warren_model():
    """The tab's own built-in Warren example, copied from `_load_example`."""
    ox, oy, sp, h = 96, 288, 120, 96
    nodes = [(ox, oy), (ox + sp, oy - h), (ox + 2 * sp, oy),
             (ox + 3 * sp, oy - h), (ox + 4 * sp, oy)]
    rods = [
        {'a': 0, 'b': 1, 'E': 200, 'A': 10}, {'a': 1, 'b': 2, 'E': 200, 'A': 10},
        {'a': 2, 'b': 3, 'E': 200, 'A': 10}, {'a': 3, 'b': 4, 'E': 200, 'A': 10},
        {'a': 0, 'b': 2, 'E': 200, 'A': 8}, {'a': 2, 'b': 4, 'E': 200, 'A': 8},
        {'a': 1, 'b': 3, 'E': 200, 'A': 8},
    ]
    loads = [{'node': 1, 'fx': 0, 'fy': 30}, {'node': 2, 'fx': 0, 'fy': 60},
             {'node': 3, 'fx': 0, 'fy': 30}]
    supports = [{'node': 0, 'type': 'pin'}, {'node': 4, 'type': 'rollerX'}]
    return nodes, rods, loads, supports


# ── 1. triangle truss against the closed form ────────────────────────────────

def test_triangle_reactions_and_member_forces_match_closed_form():
    P, span_m, rise_m = 100.0, 8.0, 3.0
    nodes, rods, loads, supports = triangle_model(P, span_m, rise_m)
    res = solve(nodes, rods, loads, supports)

    theta = math.atan2(rise_m, span_m / 2.0)
    # symmetric load on a symmetric triangle: half to each support, upward,
    # which in this module's y-down convention is negative.
    for ni in (0, 1):
        assert res['reactions'][ni]['ry'] == pytest.approx(-P / 2.0, abs=1e-9)
    assert res['reactions'][0]['rx'] == pytest.approx(0.0, abs=1e-9)

    diagonal = -(P / 2.0) / math.sin(theta)     # compression
    chord = (P / 2.0) / math.tan(theta)         # tension
    assert res['rod_res'][0]['force'] == pytest.approx(diagonal, rel=1e-12)
    assert res['rod_res'][1]['force'] == pytest.approx(diagonal, rel=1e-12)
    assert res['rod_res'][2]['force'] == pytest.approx(chord, rel=1e-12)


def test_triangle_is_in_global_equilibrium():
    nodes, rods, loads, supports = triangle_model()
    res = solve(nodes, rods, loads, supports)
    for r in global_residuals(nodes, loads, res['reactions']):
        assert abs(r) < 1e-9


# ── 2. the built-in Warren example ───────────────────────────────────────────

def test_warren_example_reactions_are_symmetric():
    nodes, rods, loads, supports = warren_model()
    res = solve(nodes, rods, loads, supports)
    # 30 + 60 + 30 = 120 kN down, symmetric -> 60 kN up at each support
    assert res['reactions'][0]['ry'] == pytest.approx(-60.0, abs=1e-9)
    assert res['reactions'][4]['ry'] == pytest.approx(-60.0, abs=1e-9)
    assert res['reactions'][0]['rx'] == pytest.approx(0.0, abs=1e-9)


def test_warren_example_is_in_global_equilibrium():
    nodes, rods, loads, supports = warren_model()
    res = solve(nodes, rods, loads, supports)
    for r in global_residuals(nodes, loads, res['reactions']):
        assert abs(r) < 1e-9


def test_warren_example_satisfies_method_of_joints_at_every_free_node():
    nodes, rods, loads, supports = warren_model()
    res = solve(nodes, rods, loads, supports)
    assert joint_residuals(nodes, rods, loads, supports, res) < 1e-9


def test_triangle_satisfies_method_of_joints():
    nodes, rods, loads, supports = triangle_model()
    res = solve(nodes, rods, loads, supports)
    assert joint_residuals(nodes, rods, loads, supports, res) < 1e-9


# ── 3. an all-pin model must not gain rotational DOFs ────────────────────────

def test_all_pin_model_has_no_bending_anywhere():
    """`analyze`'s docstring promises a model with every rod left 'pin' and no
    udl reduces EXACTLY to the classic pin-jointed truss. If a future change
    gives pin rods a rotational DOF, these zeros are the first thing to move."""
    nodes, rods, loads, supports = warren_model()
    res = solve(nodes, rods, loads, supports)
    for rr in res['rod_res']:
        assert rr['conn'] == 'pin'
        assert rr['V'] == 0.0 and rr['Ma'] == 0.0 and rr['Mb'] == 0.0
    for nr in res['node_res']:
        assert nr['theta'] == 0.0


# ── 4. the rigid (Vierendeel) element against the independent Beam solver ────

RIGID = {'a': 0, 'b': 1, 'E': 200.0, 'A': 10.0, 'I': 8000.0, 'conn': 'rigid'}
LEN_M = 10.0
NODES_1D = [(0.0, 0.0), (LEN_M * PX_PER_M, 0.0)]


def _beam_reference(build):
    """Solve the same span with the Beam tab's Hermite element. The two
    elements were written separately -- this is the strongest evidence in the
    diagnosis that the truss tab's frame element is right, precisely because
    nothing is shared between them but the physics."""
    from apps.beam.beam_app import BeamModel
    model = BeamModel(LEN_M)
    model.EI = 200.0e9 * 8000.0e-8          # E in GPa, I in cm^4 -> N*m^2
    build(model)
    return model.solve()


def test_rigid_rod_cantilever_matches_the_beam_solver():
    P = 50.0                                 # kN, downward at the free tip
    rod = dict(RIGID)
    res = solve(NODES_1D, [rod], [{'node': 1, 'fx': 0.0, 'fy': P}],
                [{'node': 0, 'type': 'fixed'}])

    ref = _beam_reference(lambda m: (m.add_support(0.0, 'fixed'),
                                     m.add_point_load(LEN_M, P * 1e3)))
    ref_fy, _ = ref.reaction_at(0.0)

    # vertical reaction: truss reports kN with y down, beam reports N with y up
    assert res['reactions'][0]['ry'] * 1e3 == pytest.approx(-ref_fy, rel=1e-6)
    # closed form as well, so a shared mistake in both solvers cannot hide
    assert res['reactions'][0]['ry'] == pytest.approx(-P, rel=1e-9)
    assert abs(res['rod_res'][0]['Ma']) == pytest.approx(P * LEN_M, rel=1e-6)

    # tip deflection PL^3/3EI, in mm (node_res stores mm)
    expected_mm = (P * 1e3) * LEN_M ** 3 / (3.0 * 200.0e9 * 8000.0e-8) * 1e3
    assert abs(res['node_res'][1]['uy']) == pytest.approx(expected_mm, rel=1e-6)


def test_rigid_rod_reports_axial_force_with_the_same_sign_as_a_pin_rod():
    """A rigid rod recovers its axial force through a different code path from
    a pin rod (`floc[3]` out of the 6-DOF element, versus EA/L times the
    projected elongation). Flipping the sign of that one line was the mutation
    every other test in this file survived -- nothing else here loads a rigid
    rod along its own axis, and the V/M/reaction checks are all blind to it.
    """
    P = 40.0                                 # kN, pulling node 1 to the right
    # A pin bar carries nothing transverse, so its free end needs restraining
    # or the stiffness matrix is singular -- hence rollerX rather than leaving
    # node 1 free. The same supports suit the rigid rod, which keeps the two
    # element types being compared on exactly the same problem.
    supports = [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'rollerX'}]
    expected_mm = (P * 1e3) * LEN_M / (200.0e9 * 10.0e-4) * 1e3   # PL/EA in mm

    for sign in (1.0, -1.0):
        for conn in ('pin', 'rigid'):
            rod = {**RIGID, 'conn': conn}
            res = solve(NODES_1D, [rod],
                        [{'node': 1, 'fx': P * sign, 'fy': 0.0}], supports)
            # pulled away from the support -> tension -> positive, and the
            # sign must reverse under the opposite load
            assert res['rod_res'][0]['force'] == pytest.approx(P * sign, rel=1e-9), conn
            assert res['node_res'][1]['ux'] == pytest.approx(expected_mm * sign, rel=1e-9), conn
            assert res['reactions'][0]['rx'] == pytest.approx(-P * sign, rel=1e-9), conn


def test_rigid_rod_with_udl_splits_the_load_evenly():
    w = 10.0                                 # kN/m, perpendicular to the rod
    rod = {**RIGID, 'udl': w, 'udl_rotation_deg': 0.0}
    res = solve(NODES_1D, [rod], [],
                [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'rollerX'}])

    for ni in (0, 1):
        assert res['reactions'][ni]['ry'] == pytest.approx(-w * LEN_M / 2.0, rel=1e-9)
    # V at end a of a simply-supported UDL span is wL/2
    assert abs(res['rod_res'][0]['V']) == pytest.approx(w * LEN_M / 2.0, rel=1e-9)
    # ...and a simple support carries no end moment
    assert res['rod_res'][0]['Ma'] == pytest.approx(0.0, abs=1e-9)
    assert res['rod_res'][0]['Mb'] == pytest.approx(0.0, abs=1e-9)


# ── 5. degenerate inputs are reported, not crashed on ────────────────────────

def test_unsupported_model_reports_a_singular_matrix_instead_of_raising():
    nodes = [(0.0, 0.0), (240.0, 0.0)]
    rods = [{'a': 0, 'b': 1, 'E': 200.0, 'A': 10.0}]
    result, error = analyze(nodes, rods, [{'node': 1, 'fx': 0.0, 'fy': 10.0}], [])
    assert result is None
    assert error and 'ingular' in error


def test_an_unrecognized_support_type_is_reported_not_silently_ignored():
    """A support whose 'type' matches none of the four accepted strings
    used to fall through analyze()'s if/elif chain untouched, contributing
    ZERO constraints -- the node reported as unrestrained with no error at
    all. Only reachable today via a hand-edited or corrupted Excel import
    (the UI's own combobox is readonly), but that path exists
    (truss_reports.import_excel_model reads the type string with no
    validation), so it must fail loudly rather than silently answer a
    different, unintended problem."""
    nodes = [(0.0, 0.0), (240.0, 0.0)]
    rods = [{'a': 0, 'b': 1, 'E': 200.0, 'A': 10.0}]
    result, error = analyze(nodes, rods, [], [{'node': 0, 'type': 'Pin'}])  # wrong case
    assert result is None
    assert error is not None and 'unrecognized type' in error


def test_a_support_on_an_out_of_range_node_is_reported_not_a_crash():
    """Same import path as above: nothing bounds-checked a support's node
    index against the actual node list, so a stale/corrupted reference
    raised an uncaught IndexError deep inside analyze() instead of the
    (result, error) contract every caller relies on."""
    nodes = [(0.0, 0.0), (240.0, 0.0)]
    rods = [{'a': 0, 'b': 1, 'E': 200.0, 'A': 10.0}]
    result, error = analyze(nodes, rods, [], [{'node': 5, 'type': 'pin'}])
    assert result is None
    assert error is not None and '5' in error
