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
@pytest.mark.parametrize('pattern', ['square', 'diagonal'])
def test_flat_grid_produces_a_sane_mesh(offset, pattern):
    mesh = sg.flat_grid(span_x=12.0, span_y=9.0, depth=1.0, module=3.0,
                        offset=offset, pattern=pattern)
    _assert_mesh_is_sane(mesh)
    zs = sorted({round(z, 6) for _, _, z in mesh['nodes']})
    assert zs == [0.0, 1.0]


def test_flat_grid_rejects_an_unknown_pattern():
    with pytest.raises(ValueError):
        sg.flat_grid(span_x=9.0, span_y=9.0, depth=1.0, module=3.0, pattern='hexagonal')


def test_flat_grid_aligned_webs_are_pyramidal_not_vertical():
    """Regression for a real mechanism: an aligned (offset=False) layer's
    web used to connect each bottom node straight up to the top node
    directly above it -- a purely vertical member with zero horizontal
    stiffness, and (found by eigenanalysis) insufficient even to stop an
    interior bottom/top pair drifting together in Z. Every web must now
    run between DIFFERENT (i,j) positions, i.e. have a nonzero horizontal
    projection."""
    mesh = sg.flat_grid(span_x=9.0, span_y=9.0, depth=1.5, module=3.0, offset=False)
    nodes = mesh['nodes']
    webs = [m for m in mesh['members'] if m.get('role') == 'web']
    assert webs
    for m in webs:
        ax, ay, _ = nodes[m['a']]
        bx, by, _ = nodes[m['b']]
        assert (ax, ay) != (bx, by), 'a web is purely vertical (zero horizontal stiffness)'


def test_diagonal_pattern_chords_run_corner_to_corner_not_edge_to_edge():
    mesh = sg.flat_grid(span_x=9.0, span_y=9.0, depth=1.5, module=3.0,
                        offset=True, pattern='diagonal')
    nodes = mesh['nodes']
    chords = [m for m in mesh['members'] if m.get('role') in ('bottom_chord', 'top_chord')]
    assert chords
    for m in chords:
        ax, ay, _ = nodes[m['a']]
        bx, by, _ = nodes[m['b']]
        assert abs(ax - bx) > 1e-9 and abs(ay - by) > 1e-9, (
            'a diagonal-pattern chord is axis-aligned, not diagonal')


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
    # Z is vertical everywhere in this module (flat_grid, dome, the
    # solver's gravity direction and the Stereo view's camera all treat
    # +Z as up), so the rise belongs on Z and the cross-section coordinate
    # on Y -- the other way around was the "vault stands on its side" bug
    # fixed 2026-09-12.
    mesh = sg.barrel_vault(span=8.0, rise=2.0, length=5.0, n_arch=10, n_bays=1,
                            double_layer=False)
    ys = [y for x, y, z in mesh['nodes']]
    zs = [z for x, y, z in mesh['nodes']]
    assert max(ys) - min(ys) == pytest.approx(8.0, abs=1e-6)   # the span
    assert max(zs) - min(zs) == pytest.approx(2.0, abs=1e-6)   # the rise


@pytest.mark.parametrize('n_arch', [2, 3, 6, 10])
@pytest.mark.parametrize('n_bays', [2, 3, 5])
def test_single_layer_barrel_vault_analyzes_at_every_size(n_arch, n_bays):
    """Regression for a real mechanism at every INTERIOR bay's springing
    line: y and z depend only on `ai` here, so a rib or brace stepping by
    the same delta-ai has the identical (y, z) projection no matter which
    bay it is in -- every member touching a springing node (ai=0 or
    ai=n_arch) was parallel to every other, leaving the direction radial
    to the shell completely unbraced at any bay that was not itself a
    support. every() member's elongation under the mechanism mode was
    exactly zero (not just small), confirming a true missing direction,
    not merely a stiff-but-flexible joint."""
    mesh = sg.barrel_vault(span=8.0, rise=2.0, length=6.0, n_arch=n_arch,
                           n_bays=n_bays, double_layer=False)
    nodes, members = mesh['nodes'], mesh['members']
    for m in members:
        m.update(E=200.0, A=10.0, Fy=250.0, r_gyr=2.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, members)
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None, f'n_arch={n_arch} n_bays={n_bays}: {err}'


@pytest.mark.parametrize('n_arch', [2, 3, 6, 10])
@pytest.mark.parametrize('n_bays', [2, 3, 5])
@pytest.mark.parametrize('depth', [0.3, 0.8])
def test_double_layer_barrel_vault_analyzes_at_every_size(n_arch, n_bays, depth):
    """Regression for the same class of springing-line mechanism as the
    single-layer sweep above, this time surfacing only at the coarsest
    allowed arc resolution (n_arch=2) even with a full double layer and
    its web_diag bracing -- an interior bay's springing nodes still had
    only one independent in-arc-plane direction. Both layers now get the
    same 'brace two stations in' fix."""
    mesh = sg.barrel_vault(span=8.0, rise=2.0, length=6.0, n_arch=n_arch,
                           n_bays=n_bays, double_layer=True, depth=depth)
    nodes, members = mesh['nodes'], mesh['members']
    for m in members:
        m.update(E=200.0, A=10.0, Fy=250.0, r_gyr=2.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, members)
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None, f'n_arch={n_arch} n_bays={n_bays} depth={depth}: {err}'


def test_barrel_vault_crown_is_higher_in_z_than_its_springing():
    """The arch's own highest point (the crown, t=0) must be the highest Z
    at that bay station -- not merely at some extreme of Y or any other
    axis -- since Z is this module's one consistent "up" everywhere else
    (flat_grid's top layer, the dome's apex, gravity itself)."""
    mesh = sg.barrel_vault(span=10.0, rise=3.0, length=4.0, n_arch=8, n_bays=1,
                            double_layer=False)
    nodes = mesh['nodes']
    at_x0 = [(y, z) for x, y, z in nodes if abs(x) < 1e-9]
    crown = max(at_x0, key=lambda yz: yz[1])   # z is the second element
    springing = [yz for yz in at_x0 if abs(yz[0]) == max(abs(v[0]) for v in at_x0)]
    for y, z in springing:
        assert crown[1] > z


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

@pytest.mark.parametrize('n_rings', [1, 2, 3, 5, 8])
@pytest.mark.parametrize('n_sectors', [3, 6, 8, 12, 20])
def test_dome_analyzes_at_every_size(n_rings, n_sectors):
    """Same class of check as the flat_grid/barrel_vault sweeps above: a
    mesh with no zero-length or duplicate members can still be a
    mechanism, so every (n_rings, n_sectors) combination a user can pick
    gets an actual solve, not just a structural sanity check."""
    mesh = sg.dome(base_radius=10.0, rise=3.0, n_rings=n_rings, n_sectors=n_sectors)
    nodes, members = mesh['nodes'], mesh['members']
    for m in members:
        m.update(E=200.0, A=10.0, Fy=250.0, r_gyr=2.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, members)
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None, f'n_rings={n_rings} n_sectors={n_sectors}: {err}'


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
    assert sg.GENERATORS['hypar_shell'] is sg.hypar_shell
    assert sg.GENERATORS['hip_roof_grid'] is sg.hip_roof_grid
    assert sg.GENERATORS['circular_flat_grid'] is sg.circular_flat_grid
    assert sg.GENERATORS['barrel_vault'] is sg.barrel_vault
    assert sg.GENERATORS['parabolic_vault'] is sg.parabolic_vault
    assert sg.GENERATORS['elliptic_vault'] is sg.elliptic_vault
    assert sg.GENERATORS['dome'] is sg.dome
    assert sg.GENERATORS['paraboloid_dish'] is sg.paraboloid_dish
    assert sg.GENERATORS['elliptic_dome'] is sg.elliptic_dome
    assert sg.GENERATORS['sphere_shell'] is sg.sphere_shell


# ── a generated mesh must actually analyze ──────────────────────────────────

@pytest.mark.parametrize('gen,kwargs', [
    # All four flat_grid combinations are exercised here on purpose: the
    # offset=False path was a real, undetected mechanism (see
    # test_flat_grid_aligned_webs_are_pyramidal_not_vertical below) until
    # only offset=True was ever run through an actual solve -- a mesh can
    # look sane (no zero-length/duplicate members) while still being a
    # singular structure, so "does it analyze" has to be checked for every
    # combination a user can actually pick, not just the default.
    ('flat_grid', dict(span_x=9.0, span_y=9.0, depth=1.2, module=3.0, offset=True, pattern='square')),
    ('flat_grid', dict(span_x=9.0, span_y=9.0, depth=1.2, module=3.0, offset=True, pattern='diagonal')),
    ('flat_grid', dict(span_x=9.0, span_y=9.0, depth=1.2, module=3.0, offset=False, pattern='square')),
    ('flat_grid', dict(span_x=9.0, span_y=9.0, depth=1.2, module=3.0, offset=False, pattern='diagonal')),
    ('barrel_vault', dict(span=8.0, rise=2.0, length=6.0, n_arch=6, n_bays=3,
                          double_layer=True, depth=0.5)),
    ('barrel_vault', dict(span=8.0, rise=2.0, length=6.0, n_arch=6, n_bays=3,
                          double_layer=False)),
    ('dome', dict(base_radius=8.0, rise=2.5, n_rings=3, n_sectors=10)),
    ('hypar_shell', dict(span_x=9.0, span_y=9.0, depth=1.2, module=3.0, rise=2.0,
                        offset=True, pattern='square')),
    ('hypar_shell', dict(span_x=9.0, span_y=9.0, depth=1.2, module=3.0, rise=2.0,
                        offset=False, pattern='diagonal')),
    ('hip_roof_grid', dict(span_x=9.0, span_y=9.0, depth=1.2, module=3.0, rise=3.0,
                          offset=True, pattern='square')),
    ('hip_roof_grid', dict(span_x=9.0, span_y=9.0, depth=1.2, module=3.0, rise=3.0,
                          offset=False, pattern='diagonal')),
    ('circular_flat_grid', dict(outer_radius=10.0, depth=1.5, n_rings=3, n_sectors=10,
                              offset=True)),
    ('circular_flat_grid', dict(outer_radius=10.0, depth=1.5, n_rings=6, n_sectors=12,
                              offset=False)),
    ('parabolic_vault', dict(span=8.0, rise=2.0, length=6.0, n_arch=6, n_bays=3,
                            double_layer=True, depth=0.5)),
    ('parabolic_vault', dict(span=8.0, rise=2.0, length=6.0, n_arch=6, n_bays=3,
                            double_layer=False)),
    ('elliptic_vault', dict(span=8.0, rise=3.0, length=6.0, n_arch=6, n_bays=3,
                           double_layer=True, depth=0.5)),
    ('elliptic_vault', dict(span=8.0, rise=3.0, length=6.0, n_arch=6, n_bays=3,
                           double_layer=False)),
    ('paraboloid_dish', dict(base_radius=8.0, rise=2.5, n_rings=3, n_sectors=10)),
    ('elliptic_dome', dict(radius_x=8.0, radius_y=5.0, rise=2.5, n_rings=3, n_sectors=10)),
    ('sphere_shell', dict(radius=5.0, n_rings=3, n_sectors=10)),
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


# ── add-on features: column (shaft + capital) and reinforcement beam ────────

def _flat_grid_with_degrees():
    # 24x24 (nx=ny=8, 9 nodes per row) so a straight-edge test can safely
    # pick up to 6-7 colinear nodes from one boundary row without running
    # into the next row's differently-positioned nodes.
    mesh = sg.flat_grid(24.0, 24.0, 1.5, 3.0, offset=True)
    degree = {}
    for m in mesh['members']:
        degree[m['a']] = degree.get(m['a'], 0) + 1
        degree[m['b']] = degree.get(m['b'], 0) + 1
    return mesh, degree


def test_add_column_creates_a_shaft_and_a_capital_fanning_to_the_given_targets():
    mesh, degree = _flat_grid_with_degrees()
    # 4 well-connected nodes, standing in for a lasso-selected attachment set
    top = sorted(degree, key=degree.get, reverse=True)[:4]
    n0, m0 = len(mesh['nodes']), len(mesh['members'])
    nodes, members, base, head = sg.add_column(mesh['nodes'], mesh['members'], top, height=3.0)
    assert len(nodes) == n0 + 2
    shaft = [m for m in members if m.get('role') == 'column_shaft']
    capital = [m for m in members if m.get('role') == 'capital']
    assert len(shaft) == 1 and {shaft[0]['a'], shaft[0]['b']} == {base, head}
    assert len(capital) == len(top)
    assert {m['a'] if m['b'] == head else m['b'] for m in capital} == set(top)
    assert len(members) == m0 + 1 + len(top)
    # the base is strictly below the head, which is strictly below the
    # targets' own (average) elevation -- a genuine, non-degenerate shaft + capital
    avg_z = sum(mesh['nodes'][j][2] for j in top) / len(top)
    assert nodes[base][2] < nodes[head][2] < avg_z


def test_add_column_rejects_a_target_node_that_does_not_exist():
    mesh, degree = _flat_grid_with_degrees()
    top = sorted(degree, key=degree.get, reverse=True)[:3]
    top[0] = len(mesh['nodes']) + 5
    with pytest.raises(ValueError):
        sg.add_column(mesh['nodes'], mesh['members'], top, height=3.0)


def test_add_column_rejects_a_nonpositive_height():
    mesh, degree = _flat_grid_with_degrees()
    top = sorted(degree, key=degree.get, reverse=True)[:4]
    with pytest.raises(ValueError):
        sg.add_column(mesh['nodes'], mesh['members'], top, height=0.0)


def test_add_column_rejects_fewer_than_three_target_nodes():
    mesh, degree = _flat_grid_with_degrees()
    top = sorted(degree, key=degree.get, reverse=True)[:2]
    with pytest.raises(ValueError):
        sg.add_column(mesh['nodes'], mesh['members'], top, height=3.0)


def test_add_column_does_not_mutate_the_caller_s_lists():
    mesh, degree = _flat_grid_with_degrees()
    top = sorted(degree, key=degree.get, reverse=True)[:4]
    nodes_before = list(mesh['nodes'])
    members_before = [dict(m) for m in mesh['members']]
    sg.add_column(mesh['nodes'], mesh['members'], top, height=3.0)
    assert mesh['nodes'] == nodes_before
    assert mesh['members'] == members_before


def test_mesh_with_a_column_still_analyzes_once_the_base_is_pinned():
    mesh, _degree = _flat_grid_with_degrees()
    # a genuine 2D footprint (one module's 4 corners, spanning both x and
    # y) -- a capital fanning to COLINEAR targets only is a real mechanism
    # (it can revolve about that line), the same class of bug diagnosed
    # earlier for a straight-line-anchored reinforcement beam; a real
    # column capital always has a 2D spread footprint for exactly this
    # reason, so that is what this test exercises.
    top = [0, 1, 9, 10]
    nodes, members, base, _head = sg.add_column(mesh['nodes'], mesh['members'], top, height=3.0)
    for m in members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    supports.append({'node': base, 'type': 'pin'})
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None


def test_a_capital_fanning_to_colinear_targets_is_a_genuine_mechanism():
    """A capital's legs anchor its head only through the target nodes; if
    those targets are all COLINEAR, the head can still revolve about that
    line without changing any leg's length -- the same "3 colinear anchors
    can't pin a point" mechanism found (and fixed, by never anchoring to a
    straight line alone) for the reinforcement beam. This is not a
    solver quirk to patch around: a real column capital always spans a
    genuine 2D footprint for exactly this reason, so the UI must pick
    targets accordingly -- this test documents the failure mode so a
    future change doesn't reintroduce it silently."""
    mesh, degree = _flat_grid_with_degrees()
    colinear = sorted(degree, key=degree.get, reverse=True)[:5]   # one straight row
    assert len({round(mesh['nodes'][j][1], 6) for j in colinear}) == 1   # sanity: same y
    nodes, members, base, _head = sg.add_column(mesh['nodes'], mesh['members'], colinear,
                                                height=3.0)
    for m in members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    supports.append({'node': base, 'type': 'pin'})
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is not None


def _two_adjacent_rows(mesh, n_stations):
    """The first n_stations nodes of two adjacent bottom-chord rows of the
    24x24 (module 3) flat_grid built by _flat_grid_with_degrees -- row 0 is
    nodes 0..8 (y=0), row 1 is nodes 9..17 (y=3), both varying only in x."""
    return list(range(n_stations)), list(range(9, 9 + n_stations))


def test_reinforcement_beam_builds_a_triangulated_apex_over_two_base_rows():
    mesh, _ = _flat_grid_with_degrees()
    edge_a, edge_b = _two_adjacent_rows(mesh, 4)
    n0, m0 = len(mesh['nodes']), len(mesh['members'])
    nodes, members, apex = sg.reinforcement_beam(mesh['nodes'], mesh['members'], edge_a, edge_b,
                                                 depth=1.0, direction=(0.0, 0.0, -1.0))
    n = len(edge_a)
    assert len(apex) == n
    assert len(nodes) == n0 + n
    new_chord = [m for m in members if m.get('role') == 'reinf_chord']
    new_web = [m for m in members if m.get('role') == 'reinf_web']
    # edge_a's and edge_b's own chords already exist in the mesh (they are
    # real bottom-chord rows) -- _add_member dedups them, so only the
    # brand-new apex chord actually gets the 'reinf_chord' role.
    assert len(new_chord) == n - 1
    assert len(new_web) == 2 * n + 4 * (n - 1)    # 2 rings/station + crossed bay braces
    assert len(members) == m0 + len(new_chord) + len(new_web)

    for ja, jb, ap in zip(edge_a, edge_b, apex):
        ax, ay, az = mesh['nodes'][ja]
        bx, by, bz = mesh['nodes'][jb]
        mx, my, mz = (ax + bx) / 2.0, (ay + by) / 2.0, (az + bz) / 2.0
        assert nodes[ap] == pytest.approx((mx, my, mz - 1.0))


def test_reinforcement_beam_honors_a_custom_direction():
    mesh, _ = _flat_grid_with_degrees()
    edge_a, edge_b = _two_adjacent_rows(mesh, 2)
    nodes, _members, apex = sg.reinforcement_beam(mesh['nodes'], mesh['members'], edge_a, edge_b,
                                                  depth=2.0, direction=(0.0, 0.0, 1.0))
    ax, ay, az = mesh['nodes'][edge_a[0]]
    bx, by, bz = mesh['nodes'][edge_b[0]]
    mx, my, mz = (ax + bx) / 2.0, (ay + by) / 2.0, (az + bz) / 2.0
    assert nodes[apex[0]] == pytest.approx((mx, my, mz + 2.0))


def test_reinforcement_beam_rejects_mismatched_row_lengths():
    mesh, _ = _flat_grid_with_degrees()
    edge_a, edge_b = _two_adjacent_rows(mesh, 4)
    with pytest.raises(ValueError):
        sg.reinforcement_beam(mesh['nodes'], mesh['members'], edge_a, edge_b[:-1], depth=1.0)


def test_reinforcement_beam_rejects_fewer_than_two_stations():
    mesh, _ = _flat_grid_with_degrees()
    edge_a, edge_b = _two_adjacent_rows(mesh, 1)
    with pytest.raises(ValueError):
        sg.reinforcement_beam(mesh['nodes'], mesh['members'], edge_a, edge_b, depth=1.0)


def test_reinforcement_beam_rejects_a_zero_direction():
    mesh, _ = _flat_grid_with_degrees()
    edge_a, edge_b = _two_adjacent_rows(mesh, 2)
    with pytest.raises(ValueError):
        sg.reinforcement_beam(mesh['nodes'], mesh['members'], edge_a, edge_b, depth=1.0,
                              direction=(0.0, 0.0, 0.0))


def test_reinforcement_beam_rejects_an_edge_node_that_does_not_exist():
    mesh, _ = _flat_grid_with_degrees()
    edge_a, edge_b = _two_adjacent_rows(mesh, 2)
    edge_b[0] = len(mesh['nodes']) + 9
    with pytest.raises(ValueError):
        sg.reinforcement_beam(mesh['nodes'], mesh['members'], edge_a, edge_b, depth=1.0)


@pytest.mark.parametrize('n_stations', [2, 3, 4, 6])
def test_reinforced_edge_still_analyzes_under_self_weight(n_stations):
    mesh, _ = _flat_grid_with_degrees()
    edge_a, edge_b = _two_adjacent_rows(mesh, n_stations)
    nodes, members, _apex = sg.reinforcement_beam(mesh['nodes'], mesh['members'], edge_a, edge_b,
                                                  depth=1.0)
    for m in members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None


# ═══════════════════════════════════════════════════════════════════════
#  New grid families: hypar, hip roof, circular flat grid, parabolic/
#  elliptic vaults, paraboloid dish, elliptic dome, full sphere
# ═══════════════════════════════════════════════════════════════════════

def _solves(mesh):
    nodes, members = mesh['nodes'], mesh['members']
    for m in members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    _res, err = sm.analyze(nodes, members, loads, supports)
    return err


# ── hypar shell ──────────────────────────────────────────────────────────

@pytest.mark.parametrize('offset', [True, False])
@pytest.mark.parametrize('pattern', ['square', 'diagonal'])
def test_hypar_shell_analyzes_cleanly(offset, pattern):
    mesh = sg.hypar_shell(12.0, 12.0, 1.5, 3.0, rise=2.5, offset=offset, pattern=pattern)
    assert _solves(mesh) is None


def test_hypar_shell_saddles_opposite_corners_in_opposite_directions():
    mesh = sg.hypar_shell(12.0, 12.0, 1.5, 3.0, rise=2.5)
    by_xy = {(round(x, 6), round(y, 6)): z for x, y, z in mesh['nodes']}
    z00 = by_xy[(0.0, 0.0)]
    z_far = by_xy[(12.0, 12.0)]
    z_adj1 = by_xy[(12.0, 0.0)]
    z_adj2 = by_xy[(0.0, 12.0)]
    assert z00 == pytest.approx(z_far)          # same-sense corners rise/dip together
    assert z_adj1 == pytest.approx(z_adj2)
    assert (z00 > 0) != (z_adj1 > 0)             # opposite-sense corners are opposite


def test_hypar_shell_rejects_nonpositive_dimensions():
    with pytest.raises(ValueError):
        sg.hypar_shell(0.0, 9.0, 1.2, 3.0, rise=1.0)


# ── hip roof grid ────────────────────────────────────────────────────────

@pytest.mark.parametrize('offset', [True, False])
@pytest.mark.parametrize('pattern', ['square', 'diagonal'])
def test_hip_roof_grid_analyzes_cleanly(offset, pattern):
    mesh = sg.hip_roof_grid(12.0, 12.0, 1.5, 3.0, rise=3.0, offset=offset, pattern=pattern)
    assert _solves(mesh) is None


def test_hip_roof_grid_ridge_is_higher_than_the_eaves():
    # module divides evenly into both spans so the plan centre (the ridge
    # apex) lands exactly on a grid node.
    mesh = sg.hip_roof_grid(12.0, 12.0, 1.5, 3.0, rise=3.0)
    by_xy = {(round(x, 6), round(y, 6)): z for x, y, z in mesh['nodes']}
    z_ridge = by_xy[(6.0, 6.0)]
    z_eave = by_xy[(0.0, 0.0)]
    assert z_ridge == pytest.approx(3.0)
    assert z_eave == pytest.approx(0.0)


def test_hip_roof_grid_rejects_nonpositive_dimensions():
    with pytest.raises(ValueError):
        sg.hip_roof_grid(9.0, -1.0, 1.2, 3.0, rise=1.0)


# ── circular flat grid ───────────────────────────────────────────────────

@pytest.mark.parametrize('offset', [True, False])
@pytest.mark.parametrize('n_rings,n_sectors', [(1, 3), (2, 6), (3, 8), (6, 12), (4, 20)])
def test_circular_flat_grid_analyzes_at_every_size(offset, n_rings, n_sectors):
    mesh = sg.circular_flat_grid(10.0, 1.5, n_rings, n_sectors, offset=offset)
    assert _solves(mesh) is None, f'offset={offset} rings={n_rings} sectors={n_sectors}'


def test_circular_flat_grid_offset_tributary_areas_sum_to_the_plan_area():
    mesh = sg.circular_flat_grid(10.0, 1.5, 6, 12, offset=True)
    total = sum(mesh['load_nodes'].values())
    assert total == pytest.approx(math.pi * 10.0 ** 2, rel=1e-9)


def test_circular_flat_grid_aligned_tributary_areas_converge_to_the_plan_area():
    prev_err = None
    for n_rings, n_sectors in ((3, 8), (6, 16), (12, 32)):
        mesh = sg.circular_flat_grid(10.0, 1.5, n_rings, n_sectors, offset=False)
        total = sum(mesh['load_nodes'].values())
        err = abs(total - math.pi * 10.0 ** 2)
        if prev_err is not None:
            assert err < prev_err
        prev_err = err


def test_circular_flat_grid_support_candidates_are_the_outer_ring():
    mesh = sg.circular_flat_grid(10.0, 1.5, 4, 12, offset=True)
    assert len(mesh['support_candidates']) == 12
    for i in mesh['support_candidates']:
        x, y, z = mesh['nodes'][i]
        assert math.hypot(x, y) == pytest.approx(10.0)
        assert z == pytest.approx(0.0)


def test_circular_flat_grid_rejects_nonpositive_radius():
    with pytest.raises(ValueError):
        sg.circular_flat_grid(0.0, 1.5, 4, 12)


# ── parabolic and elliptic vaults ────────────────────────────────────────

@pytest.mark.parametrize('n_arch,n_bays', [(2, 2), (3, 3), (6, 2), (10, 5)])
@pytest.mark.parametrize('double_layer', [True, False])
def test_parabolic_vault_analyzes_at_every_size(n_arch, n_bays, double_layer):
    mesh = sg.parabolic_vault(10.0, 2.5, 15.0, n_arch, n_bays, double_layer=double_layer,
                              depth=0.6)
    assert _solves(mesh) is None


@pytest.mark.parametrize('n_arch,n_bays', [(2, 2), (3, 3), (6, 2), (10, 5)])
@pytest.mark.parametrize('double_layer', [True, False])
def test_elliptic_vault_analyzes_at_every_size(n_arch, n_bays, double_layer):
    mesh = sg.elliptic_vault(10.0, 3.5, 15.0, n_arch, n_bays, double_layer=double_layer,
                             depth=0.6)
    assert _solves(mesh) is None


def test_parabolic_vault_crown_is_higher_than_the_springing():
    mesh = sg.parabolic_vault(10.0, 2.5, 15.0, n_arch=8, n_bays=2)
    ys_zs = {(round(y, 6)): z for _x, y, z in mesh['nodes']}
    assert ys_zs[0.0] == pytest.approx(2.5)      # crown, t=0 -> y=0
    assert ys_zs[round(-5.0, 6)] == pytest.approx(0.0)   # springing, t=-1 -> y=-span/2


def test_elliptic_vault_matches_a_circle_when_rise_equals_half_span():
    # rise == span/2 makes the ellipse's two semi-axes equal -- a circle,
    # exactly the barrel_vault() special case.
    span, rise = 10.0, 5.0
    mesh_e = sg.elliptic_vault(span, rise, 6.0, n_arch=8, n_bays=1)
    mesh_c = sg.barrel_vault(span, rise, 6.0, n_arch=8, n_bays=1, double_layer=False)
    ys_e = sorted(round(y, 4) for _x, y, _z in mesh_e['nodes'])
    ys_c = sorted(round(y, 4) for _x, y, _z in mesh_c['nodes'])
    assert ys_e == pytest.approx(ys_c)


def test_parabolic_vault_rejects_nonpositive_dimensions():
    with pytest.raises(ValueError):
        sg.parabolic_vault(0.0, 2.5, 15.0)


def test_elliptic_vault_rejects_nonpositive_dimensions():
    with pytest.raises(ValueError):
        sg.elliptic_vault(10.0, 0.0, 15.0)


# ── paraboloid dish ──────────────────────────────────────────────────────

@pytest.mark.parametrize('n_rings,n_sectors', [(1, 3), (2, 6), (4, 12), (8, 20)])
def test_paraboloid_dish_analyzes_at_every_size(n_rings, n_sectors):
    mesh = sg.paraboloid_dish(10.0, 3.0, n_rings=n_rings, n_sectors=n_sectors)
    assert _solves(mesh) is None


def test_paraboloid_dish_apex_is_at_the_bottom_centre():
    mesh = sg.paraboloid_dish(10.0, 3.0, n_rings=4, n_sectors=12)
    apex = mesh['nodes'][0]
    assert apex == pytest.approx((0.0, 0.0, 0.0))
    rim_z = [z for x, y, z in mesh['nodes'] if math.hypot(x, y) == pytest.approx(10.0, abs=1e-6)]
    assert rim_z and all(z == pytest.approx(3.0) for z in rim_z)


def test_paraboloid_dish_rejects_nonpositive_dimensions():
    with pytest.raises(ValueError):
        sg.paraboloid_dish(10.0, 0.0)


# ── elliptic dome ────────────────────────────────────────────────────────

@pytest.mark.parametrize('n_rings,n_sectors', [(1, 3), (2, 6), (4, 12), (8, 20)])
def test_elliptic_dome_analyzes_at_every_size(n_rings, n_sectors):
    mesh = sg.elliptic_dome(10.0, 6.0, 2.5, n_rings=n_rings, n_sectors=n_sectors)
    assert _solves(mesh) is None


def test_elliptic_dome_base_ring_matches_the_two_requested_radii():
    mesh = sg.elliptic_dome(10.0, 6.0, 2.5, n_rings=4, n_sectors=4)
    base = mesh['support_candidates']
    xs = sorted(abs(round(mesh['nodes'][i][0], 4)) for i in base)
    ys = sorted(abs(round(mesh['nodes'][i][1], 4)) for i in base)
    assert max(xs) == pytest.approx(10.0)
    assert max(ys) == pytest.approx(6.0)
    for i in base:
        assert mesh['nodes'][i][2] == pytest.approx(0.0, abs=1e-9)


def test_elliptic_dome_matches_dome_when_radii_and_rise_are_equal():
    r = 8.0
    mesh_e = sg.elliptic_dome(r, r, r, n_rings=3, n_sectors=8)
    # elliptic_dome's own parametrization: apex height = rise = r, base radius = r
    apex = mesh_e['nodes'][0]
    assert apex == pytest.approx((0.0, 0.0, r))
    base_r = [math.hypot(mesh_e['nodes'][i][0], mesh_e['nodes'][i][1])
             for i in mesh_e['support_candidates']]
    assert all(v == pytest.approx(r) for v in base_r)


def test_elliptic_dome_rejects_nonpositive_dimensions():
    with pytest.raises(ValueError):
        sg.elliptic_dome(10.0, 6.0, 0.0)


# ── full sphere ──────────────────────────────────────────────────────────

@pytest.mark.parametrize('n_rings,n_sectors', [(1, 3), (2, 6), (4, 12), (8, 20)])
def test_sphere_shell_analyzes_at_every_size(n_rings, n_sectors):
    mesh = sg.sphere_shell(5.0, n_rings=n_rings, n_sectors=n_sectors)
    assert _solves(mesh) is None


def test_sphere_shell_spans_from_the_north_to_the_south_pole():
    mesh = sg.sphere_shell(5.0, n_rings=4, n_sectors=12)
    zs = [z for _x, _y, z in mesh['nodes']]
    assert max(zs) == pytest.approx(5.0)
    assert min(zs) == pytest.approx(-5.0)


def test_sphere_shell_every_node_lies_on_the_sphere():
    mesh = sg.sphere_shell(5.0, n_rings=4, n_sectors=12)
    for x, y, z in mesh['nodes']:
        assert math.sqrt(x * x + y * y + z * z) == pytest.approx(5.0)


def test_sphere_shell_support_candidates_are_the_equator():
    mesh = sg.sphere_shell(5.0, n_rings=4, n_sectors=12)
    for i in mesh['support_candidates']:
        assert mesh['nodes'][i][2] == pytest.approx(0.0, abs=1e-9)


def test_sphere_shell_tributary_areas_converge_to_the_full_surface_area():
    prev_err = None
    for n_rings, n_sectors in ((2, 8), (4, 16), (8, 32)):
        mesh = sg.sphere_shell(5.0, n_rings=n_rings, n_sectors=n_sectors)
        total = sum(mesh['load_nodes'].values())
        err = abs(total - 4.0 * math.pi * 5.0 ** 2)
        if prev_err is not None:
            assert err < prev_err
        prev_err = err


def test_sphere_shell_rejects_nonpositive_radius():
    with pytest.raises(ValueError):
        sg.sphere_shell(0.0)
