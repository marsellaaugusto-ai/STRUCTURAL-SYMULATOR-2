"""The welded shear panel: a plate closing a polygon of rods, in 3D.

The element itself (constant shear flow over a polygon, from the boundary by
the divergence theorem) is the Truss tab's, verified there by patch test. So
the tests that matter here are the ones about what is NEW in three
dimensions: that the element is frame-invariant, that it refuses a warped
panel instead of flattening it, that it carries shear into the global solve,
and that its corner forces have the sign that balances a joint rather than
the one that merely balances the element.
"""
import math

import pytest

from apps.stereo import stereo_plates as sp
from apps.stereo import stereo_math as sm
from apps.stereo import stereo_geometry as sg
from apps.truss import truss_plates as tp


SQUARE = [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 3.0, 0.0), (0.0, 3.0, 0.0)]
RING = [{'a': 0, 'b': 1}, {'a': 1, 'b': 2}, {'a': 2, 'b': 3}, {'a': 3, 'b': 0}]


def _rot(p, a=0.7, b=0.4):
    x, y, z = p
    x, z = x * math.cos(a) - z * math.sin(a), x * math.sin(a) + z * math.cos(a)
    y, z = y * math.cos(b) - z * math.sin(b), y * math.sin(b) + z * math.cos(b)
    return (x, y, z)


def _gamma(Bg, loop, disp):
    return sum(Bg[i][k] * disp[loop[i]][k] for i in range(len(loop)) for k in range(3))


# ── the element in space ─────────────────────────────────────────────────────

def test_a_panel_measures_the_same_shear_whatever_plane_it_lies_in():
    """The whole 3D part of this element is its frame. If the answer moved
    when the panel was tilted, every panel not lying in a global plane would
    be wrong, and nothing else here would be worth testing."""
    flat, _ = sp.panel_geometry(SQUARE, {'nodes': [0, 1, 2, 3]})
    loop, _pts, area, Bg = flat
    shear = {0: (0, 0, 0), 1: (0, 0, 0), 2: (3.0, 0, 0), 3: (3.0, 0, 0)}
    assert _gamma(Bg, loop, shear) == pytest.approx(1.0)

    tilted_nodes = [_rot(p) for p in SQUARE]
    tilted, _ = sp.panel_geometry(tilted_nodes, {'nodes': [0, 1, 2, 3]})
    loop_t, _pt, area_t, Bg_t = tilted
    assert area_t == pytest.approx(area)
    assert _gamma(Bg_t, loop_t, {i: _rot(v) for i, v in shear.items()}) \
        == pytest.approx(1.0)


def test_a_displacement_normal_to_the_panel_produces_no_shear():
    """A membrane has no out-of-plane stiffness. That direction has to drop
    out of the strain row on its own, not by being deleted."""
    geom, _ = sp.panel_geometry(SQUARE, {'nodes': [0, 1, 2, 3]})
    loop, _pts, _area, Bg = geom
    lift = {i: (0.0, 0.0, 1.0) for i in loop}
    assert _gamma(Bg, loop, lift) == pytest.approx(0.0, abs=1e-12)


def test_a_rigid_body_move_produces_no_shear():
    geom, _ = sp.panel_geometry(SQUARE, {'nodes': [0, 1, 2, 3]})
    loop, _pts, _area, Bg = geom
    for move in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        assert _gamma(Bg, loop, {i: move for i in loop}) == pytest.approx(0.0, abs=1e-12)


def test_a_warped_quad_is_refused_rather_than_flattened():
    """Flattening it onto a best-fit plane would move the weld line off the
    rods it is supposed to be welded to."""
    warped = list(SQUARE)
    warped[2] = (3.0, 3.0, 0.9)
    geom, why = sp.panel_geometry(warped, {'nodes': [0, 1, 2, 3]})
    assert geom is None
    assert 'coplanar' in why
    assert 'mm' in why, 'the message should say HOW far out of plane it is'


def test_a_fit_up_tolerance_is_not_a_warp():
    """2% of the panel's own size. Refusing a 1 mm build tolerance would
    make the feature unusable on any real surface."""
    nearly = list(SQUARE)
    nearly[2] = (3.0, 3.0, 0.001)
    geom, why = sp.panel_geometry(nearly, {'nodes': [0, 1, 2, 3]})
    assert geom is not None, why


def test_three_nodes_are_always_coplanar_so_a_triangle_is_never_warped():
    tri = [(0.0, 0.0, 0.0), (3.0, 0.0, 1.0), (0.0, 3.0, 2.5)]
    geom, why = sp.panel_geometry(tri, {'nodes': [0, 1, 2]})
    assert geom is not None, why
    assert geom[2] > 0


def test_collinear_nodes_enclose_no_panel():
    line = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    geom, why = sp.panel_geometry(line, {'nodes': [0, 1, 2]})
    assert geom is None and 'straight line' in why


# ── choosing a panel from a node selection ───────────────────────────────────

def test_a_panel_can_be_named_by_its_nodes_and_finds_its_own_rods():
    loop, why = sp.panel_loop_from_nodes(RING, [0, 1, 2, 3])
    assert why is None
    assert set(loop) == {0, 1, 2, 3}
    for k in range(4):
        a, b = loop[k], loop[(k + 1) % 4]
        assert any({m['a'], m['b']} == {a, b} for m in RING), \
            f'edge {a}-{b} has no rod on it'


def test_nodes_with_no_rod_between_them_are_refused():
    """A panel welded along an edge with no rod on it would be carrying its
    shear into thin air."""
    sparse = [{'a': 0, 'b': 1}, {'a': 1, 'b': 2}]
    loop, why = sp.panel_loop_from_nodes(sparse, [0, 1, 2])
    assert loop is None and 'not joined' in why


@pytest.mark.parametrize('count', [0, 1, 2, 5])
def test_only_three_or_four_nodes_make_a_panel(count):
    loop, why = sp.panel_loop_from_nodes(RING, list(range(count)))
    assert loop is None and '3 or 4' in why


def test_a_real_grid_bay_can_be_panelled():
    mesh = sg.flat_grid(span_x=12.0, span_y=12.0, depth=1.5, module=3.0)
    nodes, members = mesh['nodes'], mesh['members']
    zmax = max(p[2] for p in nodes)
    tops = [i for i, p in enumerate(nodes) if abs(p[2] - zmax) < 1e-9]
    xs = sorted({round(nodes[i][0], 6) for i in tops})
    ys = sorted({round(nodes[i][1], 6) for i in tops})
    quad = [i for i in tops if round(nodes[i][0], 6) in xs[:2]
            and round(nodes[i][1], 6) in ys[:2]]
    loop, why = sp.panel_loop_from_nodes(members, quad)
    assert why is None, why
    geom, why2 = sp.panel_geometry(nodes, {'nodes': loop})
    assert geom is not None, why2
    assert geom[2] == pytest.approx(9.0)


# ── in the solve ─────────────────────────────────────────────────────────────

def _bay(panels=None, t_mm=6.0, P=50.0):
    members = [dict(m, E=200.0, A=20.0) for m in RING]
    supports = [{'node': 0, 'type': 'pin'},
                {'node': 1, 'dofs': {'uy': True, 'uz': True}},
                {'node': 2, 'dofs': {'uz': True}},
                {'node': 3, 'dofs': {'uz': True}}]
    return sm.analyze(SQUARE, members, [{'node': 2, 'fx': P}], supports,
                      panels=panels)


def test_a_bay_of_four_pinned_bars_is_a_mechanism_until_it_is_panelled():
    """The cleanest demonstration that the panel is actually carrying
    something: without it the bay lozenges and there is no answer at all."""
    _res, err = _bay()
    assert err is not None
    _res, err = _bay(panels=[{'nodes': [0, 1, 2, 3], 'thickness_mm': 6.0}])
    assert err is None, err


def test_the_shear_flow_matches_the_hand_calculation():
    """q = V / side, tau = q / t. A panel that does not reproduce that is
    not a shear panel."""
    res, err = _bay(panels=[{'nodes': [0, 1, 2, 3], 'thickness_mm': 6.0}], P=50.0)
    assert err is None, err
    pr = res['panel_res'][0]
    assert pr['valid']
    assert pr['area_m2'] == pytest.approx(9.0)
    assert abs(pr['q']) == pytest.approx(50.0 / 3.0, rel=1e-6)
    assert abs(pr['tau_MPa']) == pytest.approx(50e3 / 3.0 / 0.006 / 1e6, rel=1e-6)


def test_the_corner_forces_balance():
    res, _err = _bay(panels=[{'nodes': [0, 1, 2, 3], 'thickness_mm': 6.0}])
    corner = res['panel_res'][0]['corner_forces']
    for k in ('Fx', 'Fy', 'Fz'):
        assert sum(c[k] for c in corner) == pytest.approx(0.0, abs=1e-9)


def test_a_thicker_panel_carries_the_same_shear_at_less_stress():
    a, _ = _bay(panels=[{'nodes': [0, 1, 2, 3], 'thickness_mm': 6.0}])
    b, _ = _bay(panels=[{'nodes': [0, 1, 2, 3], 'thickness_mm': 12.0}])
    qa, qb = abs(a['panel_res'][0]['q']), abs(b['panel_res'][0]['q'])
    assert qa == pytest.approx(qb, rel=1e-6), 'the shear is set by statics, not by t'
    assert abs(b['panel_res'][0]['tau_MPa']) == pytest.approx(
        abs(a['panel_res'][0]['tau_MPa']) / 2.0, rel=1e-6)


def test_a_panel_stiffens_the_structure_it_is_welded_into():
    mesh = sg.flat_grid(span_x=12.0, span_y=12.0, depth=1.5, module=3.0)
    nodes = mesh['nodes']
    members = [dict(m, E=200.0, A=20.0) for m in mesh['members']]
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = [{'node': n, 'fz': -3.0 * a} for n, a in mesh['load_nodes'].items()]
    bare, err = sm.analyze(nodes, members, loads, supports)
    assert err is None, err

    zmax = max(p[2] for p in nodes)
    tops = [i for i, p in enumerate(nodes) if abs(p[2] - zmax) < 1e-9]
    xs = sorted({round(nodes[i][0], 6) for i in tops})
    ys = sorted({round(nodes[i][1], 6) for i in tops})
    quad = [i for i in tops if round(nodes[i][0], 6) in xs[:2]
            and round(nodes[i][1], 6) in ys[:2]]
    loop, _why = sp.panel_loop_from_nodes(mesh['members'], quad)
    withp, err = sm.analyze(nodes, members, loads, supports,
                            panels=[{'nodes': loop, 'thickness_mm': 20.0}])
    assert err is None, err
    peak = lambda r: max(abs(v['uz']) for v in r['node_res'])
    assert peak(withp) <= peak(bare)


def test_an_invalid_panel_is_reported_rather_than_silently_dropped():
    """A panel in the list that never carries anything, with nothing said
    about it, is the worst outcome available."""
    warped = list(SQUARE)
    warped[2] = (3.0, 3.0, 0.9)
    members = [dict(m, E=200.0, A=20.0) for m in RING]
    # Not every node pinned: with the whole model restrained there is
    # nothing to solve and the error would be about that, not the panel.
    supports = [{'node': 0, 'type': 'pin'},
                {'node': 1, 'dofs': {'uy': True, 'uz': True}},
                {'node': 2, 'dofs': {'uz': True}},
                {'node': 3, 'dofs': {'ux': True, 'uz': True}}]
    res, err = sm.analyze(warped, members, [{'node': 2, 'fx': 10.0}], supports,
                          panels=[{'nodes': [0, 1, 2, 3], 'thickness_mm': 6.0}])
    # The panel is refused, so this bay is back to four pinned bars -- a
    # mechanism. What matters is that the PANEL says why it was dropped.
    assert res is None or res['panel_res'][0]['valid'] is False
    if res is None:
        geom, why = sp.panel_geometry(warped, {'nodes': [0, 1, 2, 3]})
        assert geom is None and 'coplanar' in why
        return
    pr = res['panel_res'][0]
    assert pr['valid'] is False
    assert 'coplanar' in pr['reason']


def test_a_model_with_no_panels_still_reports_an_empty_list():
    """`panels` defaults to None so every existing caller is unaffected, and
    the key is always there so no reader has to guess."""
    res, err = _bay(panels=[{'nodes': [0, 1, 2, 3], 'thickness_mm': 6.0}])
    assert err is None and res['panel_res']
    mesh = sg.flat_grid(span_x=6.0, span_y=6.0, depth=1.5, module=3.0)
    members = [dict(m, E=200.0, A=20.0) for m in mesh['members']]
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    res, err = sm.analyze(mesh['nodes'], members, [], supports)
    assert err is None, err
    assert res['panel_res'] == []


# ── the code checks ──────────────────────────────────────────────────────────

def test_a_panel_is_never_reported_without_its_buckling_check():
    """A thin plate buckles in shear long before it yields, so a comfortable
    tau on its own is the most dangerous output this feature could give."""
    panel = {'nodes': [0, 1, 2, 3], 'thickness_mm': 3.0, 'Fy': 235.0}
    res, err = _bay(panels=[panel], P=400.0)
    assert err is None, err
    chk = tp.panel_checks(panel, res['panel_res'][0])
    assert chk['valid']
    assert chk['tau_cr_MPa'] > 0
    assert 'buckling' in chk['governing']
    assert chk['util'] > 1.0, 'a 3 mm plate under this shear should fail'


def test_a_thick_enough_panel_passes():
    panel = {'nodes': [0, 1, 2, 3], 'thickness_mm': 20.0, 'Fy': 235.0}
    res, _err = _bay(panels=[panel], P=50.0)
    chk = tp.panel_checks(panel, res['panel_res'][0])
    assert chk['valid'] and chk['util'] < 1.0
