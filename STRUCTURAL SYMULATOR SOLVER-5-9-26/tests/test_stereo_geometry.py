"""Mesh-integrity checks for the Stereo tab's geometry generators
(apps/stereo/stereo_geometry.py) -- every typology unified behind one
{'nodes','members','support_candidates'} shape, feeding stereo_math.py.

These are geometry/connectivity checks, not solver checks: no zero-length
or duplicate members (the two most direct ways a generated mesh becomes a
silent mechanism or a double-counted stiffness), every member index in
range, and each generated shape actually landing on the surface it claims
to (planar layers at the right z, dome rings on the claimed sphere).
"""
import math

import pytest

from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_math as sm


def _assert_mesh_is_sane(mesh):
    nodes, members = mesh['nodes'], mesh['members']
    n = len(nodes)
    assert n > 0
    assert len(members) > 0
    seen = set()
    for m in members:
        assert 0 <= m['a'] < n
        assert 0 <= m['b'] < n
        assert m['a'] != m['b'], 'zero-length (self-loop) member'
        _, _, _, L = sm.member_vector(nodes, m)
        assert L > 1e-6, f'near-zero-length member {m}'
        key = (min(m['a'], m['b']), max(m['a'], m['b']))
        assert key not in seen, f'duplicate member {m}'
        seen.add(key)
    for c in mesh['support_candidates']:
        assert 0 <= c < n


# ── flat double-layer grid ──────────────────────────────────────────────────

@pytest.mark.parametrize('offset', [True, False])
def test_flat_grid_produces_a_sane_mesh(offset):
    mesh = sg.flat_grid(span_x=12.0, span_y=9.0, depth=1.0, module=3.0, offset=offset)
    _assert_mesh_is_sane(mesh)
    zs = sorted({round(z, 6) for _, _, z in mesh['nodes']})
    assert zs == [0.0, 1.0]


def test_flat_grid_bottom_nodes_are_the_full_bounding_rectangle():
    mesh = sg.flat_grid(span_x=10.0, span_y=10.0, depth=2.0, module=5.0, offset=True)
    xs = [x for x, y, z in mesh['nodes'] if z == 0.0]
    ys = [y for x, y, z in mesh['nodes'] if z == 0.0]
    assert min(xs) == pytest.approx(0.0)
    assert max(xs) == pytest.approx(10.0)
    assert min(ys) == pytest.approx(0.0)
    assert max(ys) == pytest.approx(10.0)


def test_flat_grid_support_candidates_are_the_bottom_perimeter_only():
    mesh = sg.flat_grid(span_x=9.0, span_y=6.0, depth=1.5, module=3.0, offset=True)
    nodes = mesh['nodes']
    for c in mesh['support_candidates']:
        x, y, z = nodes[c]
        assert z == 0.0
        assert (x == pytest.approx(0.0) or x == pytest.approx(9.0)
                or y == pytest.approx(0.0) or y == pytest.approx(6.0))


def test_flat_grid_rejects_nonpositive_dimensions():
    with pytest.raises(ValueError):
        sg.flat_grid(span_x=0.0, span_y=10.0, depth=1.0, module=2.0)
    with pytest.raises(ValueError):
        sg.flat_grid(span_x=10.0, span_y=10.0, depth=1.0, module=-1.0)


# ── barrel vault ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize('double_layer', [True, False])
def test_barrel_vault_produces_a_sane_mesh(double_layer):
    mesh = sg.barrel_vault(span=10.0, rise=2.5, length=15.0, n_arch=6, n_bays=5,
                            double_layer=double_layer, depth=0.6)
    _assert_mesh_is_sane(mesh)


def test_barrel_vault_arch_nodes_span_the_stated_rise_and_span():
    mesh = sg.barrel_vault(span=8.0, rise=2.0, length=5.0, n_arch=10, n_bays=1,
                            double_layer=False)
    ys = [y for x, y, z in mesh['nodes']]
    zs = [z for x, y, z in mesh['nodes']]
    assert max(ys) - min(ys) == pytest.approx(2.0, abs=1e-6)   # the rise
    assert max(zs) - min(zs) == pytest.approx(8.0, abs=1e-6)   # the span


def test_barrel_vault_support_candidates_are_on_the_two_end_arches():
    mesh = sg.barrel_vault(span=8.0, rise=2.0, length=6.0, n_arch=6, n_bays=3,
                            double_layer=False)
    nodes = mesh['nodes']
    xs = sorted({round(x, 6) for x, y, z in nodes})
    x_min, x_max = xs[0], xs[-1]
    for c in mesh['support_candidates']:
        x, y, z = nodes[c]
        assert x == pytest.approx(x_min) or x == pytest.approx(x_max)


# ── dome ─────────────────────────────────────────────────────────────────────

def test_dome_produces_a_sane_mesh():
    mesh = sg.dome(base_radius=10.0, rise=3.0, n_rings=4, n_sectors=12)
    _assert_mesh_is_sane(mesh)


def test_dome_rings_lie_on_the_sphere_through_apex_and_base():
    base_radius, rise = 10.0, 3.0
    mesh = sg.dome(base_radius=base_radius, rise=rise, n_rings=3, n_sectors=8)
    R = (base_radius ** 2 + rise ** 2) / (2.0 * rise)
    z0 = rise - R
    for x, y, z in mesh['nodes']:
        dist = math.sqrt(x * x + y * y + (z - z0) ** 2)
        assert dist == pytest.approx(R, rel=1e-6)


def test_dome_base_ring_radius_matches_the_requested_base_radius():
    mesh = sg.dome(base_radius=6.0, rise=2.0, n_rings=2, n_sectors=10)
    nodes = mesh['nodes']
    base_z = max(z for _, _, z in nodes if z <= max(z2 for _, _, z2 in nodes))
    # the base ring is the one at the lowest z (apex is at z=rise, the highest)
    lowest_z = min(z for _, _, z in nodes)
    for x, y, z in nodes:
        if z == pytest.approx(lowest_z, abs=1e-6):
            r = math.hypot(x, y)
            assert r == pytest.approx(6.0, rel=1e-6)


def test_dome_support_candidates_are_the_base_ring():
    mesh = sg.dome(base_radius=5.0, rise=1.5, n_rings=3, n_sectors=9)
    nodes = mesh['nodes']
    lowest_z = min(z for _, _, z in nodes)
    for c in mesh['support_candidates']:
        assert nodes[c][2] == pytest.approx(lowest_z, abs=1e-6)


def test_dome_rejects_nonpositive_dimensions():
    with pytest.raises(ValueError):
        sg.dome(base_radius=-1.0, rise=2.0)
    with pytest.raises(ValueError):
        sg.dome(base_radius=5.0, rise=0.0)


# ── the generators dispatch table ───────────────────────────────────────────

def test_generators_table_names_match_the_functions():
    assert sg.GENERATORS['flat_grid'] is sg.flat_grid
    assert sg.GENERATORS['barrel_vault'] is sg.barrel_vault
    assert sg.GENERATORS['dome'] is sg.dome


# ── a generated mesh must actually analyze ──────────────────────────────────

@pytest.mark.parametrize('gen,kwargs', [
    ('flat_grid', dict(span_x=9.0, span_y=9.0, depth=1.2, module=3.0, offset=True)),
    ('barrel_vault', dict(span=8.0, rise=2.0, length=6.0, n_arch=6, n_bays=3,
                          double_layer=True, depth=0.5)),
    ('dome', dict(base_radius=8.0, rise=2.5, n_rings=3, n_sectors=10)),
])
def test_generated_mesh_solves_under_self_weight_when_fully_pinned(gen, kwargs):
    mesh = sg.GENERATORS[gen](**kwargs)
    nodes, members = mesh['nodes'], mesh['members']
    for m in members:
        m.update(E=200.0, A=10.0, Fy=250.0, r_gyr=2.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, members)
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None, f'{gen} mesh failed to analyze: {err}'
    # equilibrium sanity: total vertical reaction must balance total applied load
    total_load_z = sum(ld['fz'] for ld in loads)
    total_rxn_z = sum(r.get('Fz', 0.0) for r in res['reactions'].values())
    assert total_rxn_z == pytest.approx(-total_load_z, rel=1e-6)


# ── area-load tributary areas (load_nodes) ──────────────────────────────────
# Both flat_grid and barrel_vault are locally flat/cylindrical (developable
# surfaces), so their lumped tributary split has NO curvature error: the
# areas must sum to the true surface area exactly, not approximately. A
# dome's sphere is not developable, so its version is a midpoint-rule
# discretization that only CONVERGES to the true area as the mesh refines
# -- tested separately, for convergence rather than exact equality.

@pytest.mark.parametrize('offset', [True, False])
def test_flat_grid_tributary_areas_sum_to_the_plan_area(offset):
    mesh = sg.flat_grid(span_x=13.0, span_y=7.0, depth=1.0, module=2.5, offset=offset)
    total = sum(mesh['load_nodes'].values())
    assert total == pytest.approx(13.0 * 7.0, rel=1e-9)


def test_flat_grid_tributary_areas_are_all_on_the_top_layer_and_positive():
    mesh = sg.flat_grid(span_x=9.0, span_y=9.0, depth=1.5, module=3.0, offset=True)
    nodes = mesh['nodes']
    for node, area in mesh['load_nodes'].items():
        assert area > 0.0
        assert nodes[node][2] == pytest.approx(1.5)   # z == depth, the top layer


@pytest.mark.parametrize('double_layer', [True, False])
def test_barrel_vault_tributary_areas_sum_to_the_shell_area(double_layer):
    span, rise, length = 10.0, 2.5, 15.0
    mesh = sg.barrel_vault(span=span, rise=rise, length=length, n_arch=6, n_bays=5,
                            double_layer=double_layer, depth=0.5)
    R = rise / 2.0 + span ** 2 / (8.0 * rise)
    half_angle = math.asin(min(1.0, (span / 2.0) / R))
    expected_shell_area = length * (R * 2.0 * half_angle)
    total = sum(mesh['load_nodes'].values())
    assert total == pytest.approx(expected_shell_area, rel=1e-9)


def test_barrel_vault_tributary_areas_are_all_on_the_outer_layer():
    mesh = sg.barrel_vault(span=8.0, rise=2.0, length=6.0, n_arch=6, n_bays=3,
                            double_layer=True, depth=0.4)
    outer_nodes = set()
    for m in mesh['members']:
        if m.get('role') in ('outer_rib', 'purlin'):
            outer_nodes.add(m['a']); outer_nodes.add(m['b'])
    for node, area in mesh['load_nodes'].items():
        assert area > 0.0
        assert node in outer_nodes, f'load node {node} is not on the outer shell'


def _dome_cap_area(base_radius, rise):
    R = (base_radius ** 2 + rise ** 2) / (2.0 * rise)
    phi_max = math.asin(min(1.0, base_radius / R))
    return 2.0 * math.pi * R ** 2 * (1.0 - math.cos(phi_max))


def test_dome_tributary_areas_converge_to_the_cap_area_as_the_mesh_refines():
    base_radius, rise = 10.0, 3.0
    exact = _dome_cap_area(base_radius, rise)
    errors = []
    for n_rings in (2, 8, 32):
        mesh = sg.dome(base_radius=base_radius, rise=rise, n_rings=n_rings, n_sectors=24)
        total = sum(mesh['load_nodes'].values())
        errors.append(abs(total - exact) / exact)
    # a coarse mesh is already within a few percent, and refining strictly
    # tightens it -- the signature of a convergent (not just approximately
    # right) discretization.
    assert errors[0] < 0.08
    assert errors[1] < errors[0]
    assert errors[2] < errors[1]
    assert errors[2] < 1e-3


def test_dome_tributary_areas_include_the_apex_and_are_all_positive():
    mesh = sg.dome(base_radius=6.0, rise=2.0, n_rings=3, n_sectors=10)
    apex = 0   # dome() always adds the apex first
    assert apex in mesh['load_nodes']
    for area in mesh['load_nodes'].values():
        assert area > 0.0


def test_area_load_to_nodal_loads_distributes_pressure_by_area():
    load_nodes = {0: 4.0, 1: 6.0}
    loads = sm.area_load_to_nodal_loads(load_nodes, q_kN_m2=2.0)
    by_node = {ld['node']: ld for ld in loads}
    assert by_node[0]['fz'] == pytest.approx(-8.0)     # 2.0 kN/m2 * 4.0 m2, downward
    assert by_node[1]['fz'] == pytest.approx(-12.0)
    assert by_node[0]['fx'] == pytest.approx(0.0)
    assert by_node[0]['fy'] == pytest.approx(0.0)


def test_area_load_to_nodal_loads_honors_a_custom_direction():
    loads = sm.area_load_to_nodal_loads({0: 10.0}, q_kN_m2=1.0, direction=(1.0, 0.0, 0.0))
    assert loads[0]['fx'] == pytest.approx(10.0)
    assert loads[0]['fz'] == pytest.approx(0.0)


def test_area_load_to_nodal_loads_rejects_a_zero_direction():
    with pytest.raises(ValueError):
        sm.area_load_to_nodal_loads({0: 1.0}, q_kN_m2=1.0, direction=(0.0, 0.0, 0.0))
