"""Tests for the custom-surface wizard machinery in stereo_geometry.py:
make_height_field_surface/make_parametric_surface (wrapping a typed
expression to the shared surface(p, q) -> (x, y, z) shape), the domain/
module wizard (custom_surface_grid), and the two-surface connector
(custom_surface_between)."""
import math

import pytest

from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_math as sm
from apps.stereo import expr_math as em


def _solves(mesh):
    nodes, members = mesh['nodes'], mesh['members']
    for m in members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    _res, err = sm.analyze(nodes, members, loads, supports)
    return err


def _dist(nodes, a, b):
    ax, ay, az = nodes[a]; bx, by, bz = nodes[b]
    return math.dist((ax, ay, az), (bx, by, bz))


# ── surface wrapping ─────────────────────────────────────────────────────

def test_height_field_surface_wraps_p_q_as_x_y():
    surf = sg.make_height_field_surface('x**2 + y**2')
    assert surf(2.0, 3.0) == pytest.approx((2.0, 3.0, 13.0))


def test_parametric_surface_wraps_u_v():
    surf = sg.make_parametric_surface('u', 'v', 'u + v')
    assert surf(2.0, 3.0) == pytest.approx((2.0, 3.0, 5.0))


def test_bad_expression_raises_expression_error():
    with pytest.raises(em.ExpressionError):
        sg.make_height_field_surface('x + z')


# ── domain coordinate systems ────────────────────────────────────────────

def test_cartesian_domain_places_nodes_at_x_y_directly():
    surf = sg.make_height_field_surface('0')
    mesh = sg.custom_surface_grid(surf, coord='cartesian', pattern='square',
                                  p_range=(0.0, 4.0), q_range=(0.0, 2.0),
                                  n1=4, n2=2, module='2d')
    xs = sorted({round(x, 6) for x, y, z in mesh['nodes']})
    ys = sorted({round(y, 6) for x, y, z in mesh['nodes']})
    assert xs == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert ys == [0.0, 1.0, 2.0]


def test_polar_domain_places_nodes_on_the_expected_circle():
    surf = sg.make_height_field_surface('0')
    mesh = sg.custom_surface_grid(surf, coord='polar', pattern='square',
                                  p_range=(2.0, 2.0), q_range=(0.0, 2 * math.pi),
                                  n1=1, n2=8, module='2d')
    for x, y, z in mesh['nodes']:
        assert math.hypot(x, y) == pytest.approx(2.0)


def test_polar_full_turn_does_not_duplicate_the_seam_node():
    surf = sg.make_height_field_surface('0')
    mesh = sg.custom_surface_grid(surf, coord='polar', pattern='square',
                                  p_range=(1.0, 3.0), q_range=(0.0, 2 * math.pi),
                                  n1=2, n2=8, module='2d')
    # 3 radial stations (i=0..2) x 8 distinct angular stations (no j=8
    # duplicate of j=0), all on the outer boundary except the hub ring
    assert len(mesh['nodes']) == 3 * 8


def test_polar_open_sector_does_create_two_distinct_edge_stations():
    surf = sg.make_height_field_surface('0')
    mesh = sg.custom_surface_grid(surf, coord='polar', pattern='square',
                                  p_range=(1.0, 3.0), q_range=(0.0, math.pi),
                                  n1=2, n2=4, module='2d')
    assert len(mesh['nodes']) == 3 * 5   # j = 0..4, no wraparound


# ── pattern connectivity ─────────────────────────────────────────────────

def test_square_pattern_only_connects_axis_aligned_neighbours():
    surf = sg.make_height_field_surface('0')
    mesh = sg.custom_surface_grid(surf, coord='cartesian', pattern='square',
                                  p_range=(0.0, 3.0), q_range=(0.0, 3.0),
                                  n1=3, n2=3, module='2d')
    for m in mesh['members']:
        ax, ay, _ = mesh['nodes'][m['a']]
        bx, by, _ = mesh['nodes'][m['b']]
        assert (ax == pytest.approx(bx)) != (ay == pytest.approx(by)), \
            'square pattern produced a non-axis-aligned member'


def test_diagonal_pattern_only_connects_diagonal_neighbours():
    surf = sg.make_height_field_surface('0')
    mesh = sg.custom_surface_grid(surf, coord='cartesian', pattern='diagonal',
                                  p_range=(0.0, 3.0), q_range=(0.0, 3.0),
                                  n1=3, n2=3, module='2d')
    for m in mesh['members']:
        ax, ay, _ = mesh['nodes'][m['a']]
        bx, by, _ = mesh['nodes'][m['b']]
        assert not (ax == pytest.approx(bx) or ay == pytest.approx(by)), \
            'diagonal pattern produced an axis-aligned member'


def test_isometric_pattern_is_a_true_equilateral_triangle_lattice():
    surf = sg.make_height_field_surface('0')
    mesh = sg.custom_surface_grid(surf, coord='cartesian', pattern='isometric',
                                  p_range=(0.0, 4.0), q_range=(0.0, 4.0),
                                  n1=4, n2=4, module='2d')
    lengths = [_dist(mesh['nodes'], m['a'], m['b']) for m in mesh['members']]
    cell = lengths[0]
    for L in lengths:
        assert L == pytest.approx(cell, rel=1e-6), \
            'an isometric lattice member is not the same length as the rest'


def test_isometric_module_never_wraps_even_over_a_full_polar_sweep():
    # Isometric over Polar is a documented spiral (the oblique basis
    # shifts radius with every angular step -- physical member lengths are
    # therefore NOT uniform the way the Cartesian case's are: a fixed
    # domain-space angular step covers more physical arc length at the
    # larger radius the spiral has drifted out to by the far end, which is
    # expected distortion, not a bug). What must actually never happen:
    # a member connecting the last built angular station straight back to
    # the first one, closing a seam that -- given the radius drift -- would
    # connect two points nowhere near each other.
    surf = sg.make_height_field_surface('0')
    n1, n2 = 3, 8
    mesh_full = sg.custom_surface_grid(surf, coord='polar', pattern='isometric',
                                       p_range=(1.0, 3.0), q_range=(0.0, 2 * math.pi),
                                       n1=n1, n2=n2, module='2d')
    # Recover which lattice (i, j) each node came from is not exposed by
    # the mesh dict, so check the documented, directly-verifiable
    # contract instead: _domain_lattice always returns wrap_j=False for
    # 'isometric' (see its own docstring) -- confirm that directly.
    grid_pq, _n1_eff, n2_eff, wrap_j = sg._domain_lattice(
        'polar', 'isometric', (1.0, 3.0), (0.0, 2 * math.pi), n1, n2)
    assert wrap_j is False
    assert len(grid_pq) == (n1 + 1) * (n2_eff + 1)   # a plain open rectangle of (i, j)


# ── 2D vs 3D module ───────────────────────────────────────────────────────

def test_2d_module_is_a_single_layer():
    surf = sg.make_height_field_surface('0')
    mesh = sg.custom_surface_grid(surf, coord='cartesian', pattern='isometric',
                                  p_range=(0.0, 4.0), q_range=(0.0, 4.0),
                                  n1=4, n2=4, module='2d')
    zs = {round(z, 9) for x, y, z in mesh['nodes']}
    assert zs == {0.0}


def test_3d_module_offsets_the_second_layer_along_the_normal():
    surf = sg.make_height_field_surface('0')   # flat, z=0 -- normal is +Z
    mesh = sg.custom_surface_grid(surf, coord='cartesian', pattern='square',
                                  p_range=(0.0, 4.0), q_range=(0.0, 4.0),
                                  n1=2, n2=2, module='3d', depth=0.7, offset_side='top')
    zs = {round(z, 6) for x, y, z in mesh['nodes']}
    assert zs == {0.0, -0.7}   # surface IS the top -> other layer is BELOW


def test_3d_module_offset_side_bottom_puts_the_surface_at_the_bottom():
    surf = sg.make_height_field_surface('0')
    mesh = sg.custom_surface_grid(surf, coord='cartesian', pattern='square',
                                  p_range=(0.0, 4.0), q_range=(0.0, 4.0),
                                  n1=2, n2=2, module='3d', depth=0.7, offset_side='bottom')
    zs = {round(z, 6) for x, y, z in mesh['nodes']}
    assert zs == {0.0, 0.7}   # surface IS the bottom -> other layer is ABOVE


def test_invalid_module_and_offset_side_are_rejected():
    surf = sg.make_height_field_surface('0')
    with pytest.raises(ValueError):
        sg.custom_surface_grid(surf, module='bogus')
    with pytest.raises(ValueError):
        sg.custom_surface_grid(surf, module='3d', offset_side='bogus')


# ── support candidates ────────────────────────────────────────────────────

def test_support_candidates_are_the_domain_perimeter():
    surf = sg.make_height_field_surface('0')
    mesh = sg.custom_surface_grid(surf, coord='cartesian', pattern='square',
                                  p_range=(0.0, 4.0), q_range=(0.0, 4.0),
                                  n1=4, n2=4, module='2d')
    xs = [mesh['nodes'][i][0] for i in mesh['support_candidates']]
    ys = [mesh['nodes'][i][1] for i in mesh['support_candidates']]
    for x, y in zip(xs, ys):
        assert x in (0.0, 4.0) or y in (0.0, 4.0)
    # every interior node is NOT a support candidate
    interior = [i for i, (x, y, z) in enumerate(mesh['nodes'])
               if x not in (0.0, 4.0) and y not in (0.0, 4.0)]
    assert set(interior).isdisjoint(mesh['support_candidates'])


def test_full_polar_sweep_has_no_j_edge_in_support_candidates():
    # a closed ring has no angular "edge" -- only the inner/outer radius
    # rings should be offered as supports.
    surf = sg.make_height_field_surface('0')
    mesh = sg.custom_surface_grid(surf, coord='polar', pattern='square',
                                  p_range=(1.0, 3.0), q_range=(0.0, 2 * math.pi),
                                  n1=2, n2=8, module='2d')
    radii = {round(math.hypot(x, y), 6) for i, (x, y, z) in enumerate(mesh['nodes'])
             if i in mesh['support_candidates']}
    assert radii == {1.0, 3.0}


# ── analysis: the 3D module is robustly stable ────────────────────────────

@pytest.mark.parametrize('pattern', ['square', 'diagonal', 'isometric'])
@pytest.mark.parametrize('coord,p_range,q_range', [
    ('cartesian', (-5.0, 5.0), (-4.0, 4.0)),
    ('polar', (0.5, 5.0), (0.0, 2 * math.pi)),
    ('polar', (0.5, 5.0), (0.0, math.pi)),
])
def test_3d_module_analyzes_under_self_weight(coord, p_range, q_range, pattern):
    surf = sg.make_height_field_surface('2.0 * (1 - (x/5)^2 - (y/4)^2)')
    mesh = sg.custom_surface_grid(surf, coord=coord, pattern=pattern,
                                  p_range=p_range, q_range=q_range,
                                  n1=5, n2=8, module='3d', depth=0.4, offset_side='top')
    assert _solves(mesh) is None


def test_2d_isometric_module_analyzes_under_self_weight():
    surf = sg.make_height_field_surface('2.0 * (1 - (x/5)^2 - (y/4)^2)')
    mesh = sg.custom_surface_grid(surf, coord='cartesian', pattern='isometric',
                                  p_range=(-5.0, 5.0), q_range=(-4.0, 4.0),
                                  n1=5, n2=8, module='2d')
    assert _solves(mesh) is None


def test_parametric_surface_3d_module_analyzes_under_self_weight():
    # an open half-cylinder: x=u, y=3*sin(v), z=3*cos(v)
    surf = sg.make_parametric_surface('u', '3*sin(v)', '3*cos(v)')
    mesh = sg.custom_surface_grid(surf, coord='cartesian', pattern='diagonal',
                                  p_range=(0.0, 6.0), q_range=(0.3, math.pi - 0.3),
                                  n1=6, n2=6, module='3d', depth=0.3, offset_side='top')
    assert _solves(mesh) is None


# ── two-surface connector ─────────────────────────────────────────────────

def test_custom_surface_between_connects_corresponding_nodes():
    top = sg.make_height_field_surface('1.0')
    bottom = sg.make_height_field_surface('0.0')
    mesh = sg.custom_surface_between(top, bottom, coord='cartesian', pattern='square',
                                     p_range=(0.0, 4.0), q_range=(0.0, 4.0), n1=2, n2=2)
    zs = {round(z, 6) for x, y, z in mesh['nodes']}
    assert zs == {0.0, 1.0}
    # a same-(x,y) web exists between every top/bottom pair
    by_xy = {}
    for i, (x, y, z) in enumerate(mesh['nodes']):
        by_xy.setdefault((round(x, 6), round(y, 6)), []).append(i)
    pair_edges = {(min(m['a'], m['b']), max(m['a'], m['b'])) for m in mesh['members']}
    for (x, y), pair in by_xy.items():
        assert len(pair) == 2
        a, b = sorted(pair)
        assert (a, b) in pair_edges


@pytest.mark.parametrize('pattern', ['square', 'diagonal', 'isometric'])
def test_custom_surface_between_analyzes_under_self_weight(pattern):
    top = sg.make_height_field_surface('2.0 * (1 - (x/5)^2 - (y/4)^2) + 1.0')
    bottom = sg.make_height_field_surface('0')
    mesh = sg.custom_surface_between(top, bottom, coord='cartesian', pattern=pattern,
                                     p_range=(-5.0, 5.0), q_range=(-4.0, 4.0), n1=5, n2=6)
    assert _solves(mesh) is None


def test_generators_table_includes_the_custom_surface_generators():
    assert sg.GENERATORS['custom_surface_grid'] is sg.custom_surface_grid
    assert sg.GENERATORS['custom_surface_between'] is sg.custom_surface_between
