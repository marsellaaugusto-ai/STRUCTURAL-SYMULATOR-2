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
from apps.stereo import stereo_geometry_addons as ga


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


def test_barrel_vault_support_candidates_are_on_the_two_springing_lines():
    # The vault's actual base is the two springing lines (running the full
    # length, at the arch's two spring points) -- not the two end arches,
    # which would treat the vault like a beam spanning its own length
    # instead of an arch spanning its own width down to a continuous base.
    mesh = sg.barrel_vault(span=8.0, rise=2.0, length=6.0, n_arch=6, n_bays=3,
                            double_layer=False)
    nodes = mesh['nodes']
    ys = sorted({round(y, 6) for x, y, z in nodes})
    y_min, y_max = ys[0], ys[-1]
    xs_seen = set()
    for c in mesh['support_candidates']:
        x, y, z = nodes[c]
        assert y == pytest.approx(y_min) or y == pytest.approx(y_max)
        xs_seen.add(round(x, 6))
    # every longitudinal station (bay) contributes support candidates on
    # both springing lines -- the base runs the vault's full length.
    all_xs = sorted({round(x, 6) for x, y, z in nodes})
    assert xs_seen == set(all_xs)


@pytest.mark.parametrize('double_layer', [True, False])
@pytest.mark.parametrize('n_arch', [2, 3, 6, 10])
@pytest.mark.parametrize('n_bays', [1, 2, 3, 5])
def test_barrel_vault_rib_is_stable_when_only_the_springing_lines_are_pinned(
        n_bays, n_arch, double_layer):
    # Regression test: once support_candidates was corrected to sit on the
    # two springing lines (this vault's actual base) rather than the two
    # end arches, a real zero-energy mechanism was exposed at n_arch >= 6 --
    # every bay's rib flexing in-plane by the SAME amount along the vault's
    # length, which the existing inter-bay-only bracing ('brace'/
    # 'edge_brace') cannot see since that mode has no relative inter-bay
    # motion. The fix is an intra-rib skip-one diagonal (role='rib_diag')
    # bracing each rib within its own plane, independent of every other bay.
    mesh = sg.barrel_vault(span=8.0, rise=2.0, length=6.0, n_arch=n_arch,
                            n_bays=n_bays, double_layer=double_layer, depth=0.5)
    assert _solves(mesh) is None


@pytest.mark.parametrize('family', [sg.parabolic_vault, sg.elliptic_vault])
@pytest.mark.parametrize('double_layer', [True, False])
@pytest.mark.parametrize('n_arch', [2, 3, 6, 10])
@pytest.mark.parametrize('n_bays', [1, 2, 3, 5])
def test_extruded_arch_rib_is_stable_when_only_the_springing_lines_are_pinned(
        n_bays, n_arch, double_layer, family):
    # Same regression as the barrel_vault case above, for the shared
    # _extruded_arch_grid() engine used by parabolic_vault/elliptic_vault.
    mesh = family(span=8.0, rise=2.0, length=6.0, n_arch=n_arch, n_bays=n_bays,
                   double_layer=double_layer, depth=0.5)
    assert _solves(mesh) is None


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


# ── conical roof ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize('n_rings', [1, 2, 3, 5, 8])
@pytest.mark.parametrize('n_sectors', [3, 6, 8, 12, 20])
def test_cone_roof_analyzes_at_every_size(n_rings, n_sectors):
    mesh = sg.cone_roof(base_radius=10.0, rise=6.0, n_rings=n_rings, n_sectors=n_sectors)
    nodes, members = mesh['nodes'], mesh['members']
    for m in members:
        m.update(E=200.0, A=10.0, Fy=250.0, r_gyr=2.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, members)
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None, f'n_rings={n_rings} n_sectors={n_sectors}: {err}'


def test_cone_roof_produces_a_sane_mesh():
    mesh = sg.cone_roof(base_radius=10.0, rise=6.0, n_rings=4, n_sectors=12)
    _assert_mesh_is_sane(mesh)


def test_cone_roof_meridians_are_straight_lines_not_curved():
    # the defining difference from dome()/paraboloid_dish(): every ring
    # node's height is an exact LINEAR function of its radius, i.e. the
    # rafter from apex to base is a straight line (a true cone), not a
    # curve.
    base_radius, rise = 10.0, 6.0
    mesh = sg.cone_roof(base_radius=base_radius, rise=rise, n_rings=5, n_sectors=8)
    for x, y, z in mesh['nodes']:
        r = math.hypot(x, y)
        expected_z = rise * (1.0 - r / base_radius)
        assert z == pytest.approx(expected_z, abs=1e-6)


def test_cone_roof_apex_is_above_the_base_ring():
    mesh = sg.cone_roof(base_radius=8.0, rise=5.0, n_rings=3, n_sectors=10)
    apex = 0   # cone_roof() always adds the apex first
    ax, ay, az = mesh['nodes'][apex]
    assert (ax, ay) == (0.0, 0.0)
    assert az == pytest.approx(5.0)
    for c in mesh['support_candidates']:
        assert mesh['nodes'][c][2] == pytest.approx(0.0, abs=1e-6)


def test_cone_roof_base_ring_radius_matches_the_requested_base_radius():
    mesh = sg.cone_roof(base_radius=7.0, rise=3.0, n_rings=2, n_sectors=10)
    for c in mesh['support_candidates']:
        x, y, _z = mesh['nodes'][c]
        assert math.hypot(x, y) == pytest.approx(7.0, rel=1e-6)


def test_cone_roof_rejects_nonpositive_dimensions():
    with pytest.raises(ValueError):
        sg.cone_roof(base_radius=-1.0, rise=2.0)
    with pytest.raises(ValueError):
        sg.cone_roof(base_radius=5.0, rise=0.0)


def test_cone_roof_tributary_areas_converge_to_the_lateral_surface_area():
    # The MERIDIAN direction's secant is exact for a cone (a straight
    # line, unlike a dome's curved meridian) -- but load_nodes still
    # treats the apex cap as a flat disk (pi * r_half**2, the same
    # approximation dome()/paraboloid_dish() use for their own apex), when
    # a cone's actual tip is a small lateral cap, not a flat circle. That
    # keeps this a CONVERGENT approximation like the other apex-ribbed
    # shells, not an exact sum at every mesh density -- confirmed
    # numerically (n_rings=1 overshoots the true area by ~21%, tightening
    # to <0.1% by n_rings=16).
    base_radius, rise = 10.0, 6.0
    slant = math.hypot(base_radius, rise)
    exact = math.pi * base_radius * slant
    errors = []
    for n_rings in (1, 4, 16):
        mesh = sg.cone_roof(base_radius=base_radius, rise=rise,
                            n_rings=n_rings, n_sectors=24)
        total = sum(mesh['load_nodes'].values())
        errors.append(abs(total - exact) / exact)
    assert errors[0] < 0.25
    assert errors[1] < errors[0]
    assert errors[2] < errors[1]
    assert errors[2] < 1e-3


def test_cone_roof_tributary_areas_are_all_positive():
    mesh = sg.cone_roof(base_radius=6.0, rise=4.0, n_rings=3, n_sectors=10)
    apex = 0
    assert apex in mesh['load_nodes']
    for area in mesh['load_nodes'].values():
        assert area > 0.0


# ── truss bridge ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize('n_panels', [2, 3, 5, 6, 8, 10])
def test_truss_bridge_analyzes_at_every_panel_count(n_panels):
    # span/depth/width deliberately NOT round multiples of each other,
    # to steer well clear of the documented critical-geometry coincidence
    # (span=40, depth=5, width=6, n_panels=4) -- see truss_bridge's own
    # docstring.
    mesh = sg.truss_bridge(span=41.3, depth=5.2, width=8.1, n_panels=n_panels)
    assert _solves(mesh) is None


def test_truss_bridge_produces_a_sane_mesh():
    mesh = sg.truss_bridge(span=40.0, depth=5.0, width=8.0, n_panels=8)
    _assert_mesh_is_sane(mesh)


def test_truss_bridge_top_chord_is_exactly_depth_above_bottom_chord():
    mesh = sg.truss_bridge(span=40.0, depth=5.0, width=8.0, n_panels=8)
    nodes = mesh['nodes']
    by_xy = {}
    for x, y, z in nodes:
        by_xy.setdefault((round(x, 6), round(y, 6)), []).append(z)
    for (_x, _y), zs in by_xy.items():
        assert sorted(zs) == pytest.approx([0.0, 5.0])


def test_truss_bridge_deck_width_matches_the_transverse_spacing():
    mesh = sg.truss_bridge(span=40.0, depth=5.0, width=8.0, n_panels=8)
    ys = sorted({round(y, 6) for _x, y, _z in mesh['nodes']})
    assert ys == [0.0, 8.0]


def test_truss_bridge_support_candidates_are_the_four_bottom_corners():
    mesh = sg.truss_bridge(span=40.0, depth=5.0, width=8.0, n_panels=8)
    nodes = mesh['nodes']
    assert len(mesh['support_candidates']) == 4
    corners = {(round(nodes[i][0], 6), round(nodes[i][1], 6), round(nodes[i][2], 6))
              for i in mesh['support_candidates']}
    assert corners == {(0.0, 0.0, 0.0), (0.0, 8.0, 0.0), (40.0, 0.0, 0.0), (40.0, 8.0, 0.0)}


def test_truss_bridge_tributary_areas_sum_to_the_deck_plan_area():
    span, width = 40.0, 8.0
    mesh = sg.truss_bridge(span=span, depth=5.0, width=width, n_panels=8)
    total = sum(mesh['load_nodes'].values())
    assert total == pytest.approx(span * width)


def test_truss_bridge_rejects_nonpositive_dimensions():
    with pytest.raises(ValueError):
        sg.truss_bridge(span=-1.0, depth=5.0, width=8.0)
    with pytest.raises(ValueError):
        sg.truss_bridge(span=40.0, depth=0.0, width=8.0)
    with pytest.raises(ValueError):
        sg.truss_bridge(span=40.0, depth=5.0, width=0.0)


def test_truss_bridge_diagonals_alternate_direction_panel_to_panel():
    mesh = sg.truss_bridge(span=40.0, depth=5.0, width=8.0, n_panels=4)
    diag_members = [m for m in mesh['members'] if m.get('role') == 'diagonal']
    # 2 sides * n_panels diagonals
    assert len(diag_members) == 2 * 4


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
    assert sg.GENERATORS['cone_roof'] is sg.cone_roof
    assert sg.GENERATORS['paraboloid_dish'] is sg.paraboloid_dish
    assert sg.GENERATORS['elliptic_dome'] is sg.elliptic_dome
    assert sg.GENERATORS['sphere_shell'] is sg.sphere_shell
    assert sg.GENERATORS['groin_vault'] is sg.groin_vault
    assert sg.GENERATORS['truss_bridge'] is sg.truss_bridge


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
    ('cone_roof', dict(base_radius=8.0, rise=2.5, n_rings=3, n_sectors=10)),
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
    ('groin_vault', dict(span=9.0, rise=2.5, module=3.0, depth=1.2, offset=True,
                        pattern='square')),
    ('groin_vault', dict(span=9.0, rise=2.5, module=3.0, depth=1.2, offset=False,
                        pattern='diagonal')),
    # span=41.3/depth=5.2/width=8.1 are deliberately non-round: the exact
    # combination span=40, depth=5, width=6, n_panels=4 is a genuine
    # coincidental critical-geometry mechanism (see truss_bridge's docstring),
    # so the test avoids that exact point rather than proving nothing.
    ('truss_bridge', dict(span=41.3, depth=5.2, width=8.1, n_panels=6)),
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


# ── a pressure that varies over the surface ─────────────────────────────────

def test_a_varying_pressure_is_sampled_at_each_node():
    """The whole point of the varying form: two nodes with the SAME
    tributary area must still get different loads when the field differs
    over them."""
    coords = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
    loads = sm.varying_area_load_to_nodal_loads(
        coords, {0: 2.0, 1: 2.0}, lambda x, y, z: 1.0 + 0.5 * x)
    by_node = {ld['node']: ld for ld in loads}
    assert by_node[0]['fz'] == pytest.approx(-2.0)    # q=1.0 over 2 m2
    assert by_node[1]['fz'] == pytest.approx(-12.0)   # q=6.0 over 2 m2


def test_a_constant_field_matches_the_plain_area_load():
    """The uniform law is not a separate code path -- it is this function
    with a constant q -- so the two must agree to the last digit."""
    coords = [(0.0, 0.0, 0.0), (3.0, 0.0, 1.0), (6.0, 2.0, 0.5)]
    areas = {0: 4.0, 1: 6.5, 2: 1.25}
    plain = sm.area_load_to_nodal_loads(areas, q_kN_m2=2.5)
    varying = sm.varying_area_load_to_nodal_loads(coords, areas, lambda x, y, z: 2.5)
    assert {ld['node']: ld['fz'] for ld in varying} == \
        pytest.approx({ld['node']: ld['fz'] for ld in plain})


def test_a_varying_pressure_pushes_along_the_direction_given():
    coords = [(0.0, 0.0, 0.0)]
    loads = sm.varying_area_load_to_nodal_loads(
        coords, {0: 10.0}, lambda x, y, z: 2.0, direction=(3.0, 0.0, 4.0))
    assert loads[0]['fx'] == pytest.approx(20.0 * 0.6)   # the vector is normalised
    assert loads[0]['fz'] == pytest.approx(20.0 * 0.8)


def test_a_varying_pressure_rejects_a_zero_direction():
    with pytest.raises(ValueError):
        sm.varying_area_load_to_nodal_loads(
            [(0.0, 0.0, 0.0)], {0: 1.0}, lambda x, y, z: 1.0, direction=(0.0, 0.0, 0.0))


def test_only_restricts_the_load_and_leaves_the_rest_unloaded():
    """A drift over half a roof. Nodes outside the set must carry NO entry
    at all, not a zero one, so combine_loads can still layer another field
    onto them without a phantom zero winning."""
    coords = [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
    loads = sm.varying_area_load_to_nodal_loads(
        coords, {0: 1.0, 1: 1.0, 2: 1.0}, lambda x, y, z: 3.0, only={0, 2})
    assert sorted(ld['node'] for ld in loads) == [0, 2]


def test_a_node_the_field_zeroes_carries_no_load():
    """A wind that reverses across a ridge crosses zero somewhere; the node
    it crosses at gets no entry rather than a 0.0 kN one."""
    coords = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)]
    loads = sm.varying_area_load_to_nodal_loads(
        coords, {0: 1.0, 1: 1.0}, lambda x, y, z: x - 4.0)
    assert [ld['node'] for ld in loads] == [0]


def test_a_tributary_area_for_a_node_that_no_longer_exists_is_skipped():
    """load_nodes outliving its mesh is exactly the Excel-import failure the
    app guards against; the maths must not index off the end either."""
    loads = sm.varying_area_load_to_nodal_loads(
        [(0.0, 0.0, 0.0)], {0: 1.0, 7: 5.0}, lambda x, y, z: 1.0)
    assert [ld['node'] for ld in loads] == [0]


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
    nodes, members, bases, head = sg.add_column(mesh['nodes'], mesh['members'],
                                               top, height=3.0)
    assert len(bases) == 1, 'a single shaft stands on one foot'
    base = bases[0]
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


@pytest.mark.parametrize('style', sg.COLUMN_STYLES)
def test_every_column_style_solves_once_all_its_feet_are_pinned(style):
    """A latticed or splay-footed column is rigid as a BODY, so restraining
    one node of it leaves three rotations free and the solver reports a
    mechanism. Every foot the builder returns has to be pinned."""
    mesh, degree = _flat_grid_with_degrees()
    # The latticed styles run one chord down from each selected node, so
    # their footprint IS the selection and it has to enclose an area.
    top = (_square_footprint(mesh) if style in (sg.COLUMN_LATTICE, sg.COLUMN_TAPERED)
           else sorted(degree, key=degree.get, reverse=True)[:9])
    nodes, members, bases, head = sg.add_column(mesh['nodes'], mesh['members'], top,
                                                height=4.0, style=style,
                                                capital_height=1.0, width=1.2, panels=3)
    assert bases, 'a column with no foot at all'
    # the plain strut has no capital: it is one post per selected node, and
    # the latticed styles have no capital either -- one chord per node.
    expected_feet = {sg.COLUMN_PLAIN: len(top), sg.COLUMN_SHAFT: 1,
                     sg.COLUMN_TRIPOD: 3,
                     sg.COLUMN_LATTICE: len(top),
                     sg.COLUMN_TAPERED: len(top)}.get(style, 4)
    assert len(bases) == expected_feet
    assert all(nodes[b][2] < nodes[head][2] for b in bases), 'a foot above the head'
    for m in members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    supports.extend({'node': b, 'type': 'pin'} for b in bases)
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    _res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None, f'{style} did not solve: {err}'


def test_a_plain_vertical_column_is_one_post_under_one_node():
    """The simplest support there is: no head, no capital fan, just a strut
    from the node straight down to its own foundation."""
    mesh, degree = _flat_grid_with_degrees()
    target = sorted(degree, key=degree.get, reverse=True)[0]
    n0, m0 = len(mesh['nodes']), len(mesh['members'])
    nodes, members, bases, head = sg.add_column(mesh['nodes'], mesh['members'], [target],
                                                height=4.0, style=sg.COLUMN_PLAIN)
    assert len(nodes) == n0 + 1
    assert len(members) == m0 + 1
    assert len(bases) == 1
    assert head == target
    foot = nodes[bases[0]]
    assert foot[:2] == pytest.approx(mesh['nodes'][target][:2]), 'the post is not vertical'
    assert foot[2] == pytest.approx(mesh['nodes'][target][2] - 4.0)
    assert not [m for m in members if m.get('role') == 'capital'], 'it grew a capital'


def test_a_plain_column_gives_every_selected_node_its_own_post():
    mesh, degree = _flat_grid_with_degrees()
    targets = sorted(degree, key=degree.get, reverse=True)[:4]
    nodes, members, bases, _head = sg.add_column(mesh['nodes'], mesh['members'], targets,
                                                 height=3.0, style=sg.COLUMN_PLAIN)
    assert len(bases) == len(targets)
    shafts = [m for m in members if m.get('role') == 'column_shaft']
    assert len(shafts) == len(targets)
    assert {m['b'] for m in shafts} == set(targets)


def test_a_plain_column_still_needs_a_node_to_stand_under():
    mesh, _degree = _flat_grid_with_degrees()
    with pytest.raises(ValueError):
        sg.add_column(mesh['nodes'], mesh['members'], [], height=3.0,
                      style=sg.COLUMN_PLAIN)


def test_the_capital_styles_still_demand_a_footprint():
    """Relaxing the count for the plain strut must not relax it for the
    styles whose whole point is spreading the reaction."""
    mesh, degree = _flat_grid_with_degrees()
    one = [sorted(degree, key=degree.get, reverse=True)[0]]
    for style in (sg.COLUMN_SHAFT, sg.COLUMN_LATTICE, sg.COLUMN_TRIPOD):
        with pytest.raises(ValueError):
            sg.add_column(mesh['nodes'], mesh['members'], one, height=3.0, style=style)


def _square_footprint(mesh, n=4):
    """n top-layer nodes that enclose a real area in plan -- what a latticed
    column now needs, since its chords run down from the nodes themselves."""
    nodes = mesh['nodes']
    zmax = max(p[2] for p in nodes)
    tops = [i for i, p in enumerate(nodes) if abs(p[2] - zmax) < 1e-9]
    xs = sorted({round(nodes[i][0], 6) for i in tops})
    ys = sorted({round(nodes[i][1], 6) for i in tops})
    quad = [i for i in tops
            if round(nodes[i][0], 6) in xs[:2] and round(nodes[i][1], 6) in ys[:2]]
    return quad[:n]


def test_a_roof_standing_only_on_a_latticed_column_needs_every_foot_pinned():
    """The reason add_column returns a LIST of feet rather than one node.

    Worth stating precisely, because the answer CHANGED when the latticed
    column stopped going through a capital. The old one hung the whole
    lattice from a single head node, so one pinned foot left it free to spin
    about the vertical through that head -- a mechanism even with the grid
    fully supported around it. The new one lands on three or four separate
    grid joints, so a grid that is itself supported now braces the column,
    and one foot is enough.

    The property that survives is the one that matters in practice: a roof
    carried ONLY by its columns, which is what a column is for, is a
    mechanism unless every foot is restrained."""
    mesh, _degree = _flat_grid_with_degrees()
    top = _square_footprint(mesh)
    nodes, members, bases, _head = sg.add_column(mesh['nodes'], mesh['members'], top,
                                                 height=4.0, style=sg.COLUMN_LATTICE)
    for m in members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)

    one = [{'node': bases[0], 'type': 'pin'}]
    _res, err = sm.analyze(nodes, members, loads, one)
    assert err is not None, 'one foot held a whole roof up on its own'

    every = [{'node': b, 'type': 'pin'} for b in bases]
    _res, err = sm.analyze(nodes, members, loads, every)
    assert err is None, err


def test_a_tapered_column_is_narrower_at_its_feet_than_at_its_head():
    mesh, degree = _flat_grid_with_degrees()
    top = _square_footprint(mesh)
    out = {}
    for style in (sg.COLUMN_LATTICE, sg.COLUMN_TAPERED):
        nodes, _members, bases, _head = sg.add_column(
            mesh['nodes'], mesh['members'], top, height=4.0, style=style, width=1.2)
        xs = [nodes[b][0] for b in bases]
        out[style] = max(xs) - min(xs)
    assert out[sg.COLUMN_TAPERED] < out[sg.COLUMN_LATTICE]


def test_the_capital_height_is_the_drop_from_the_attachment_surface():
    mesh, degree = _flat_grid_with_degrees()
    top = sorted(degree, key=degree.get, reverse=True)[:9]
    avg_z = sum(mesh['nodes'][j][2] for j in top) / len(top)
    for cap in (0.4, 1.6):
        nodes, _members, _bases, head = sg.add_column(
            mesh['nodes'], mesh['members'], top, height=4.0, capital_height=cap)
        assert nodes[head][2] == pytest.approx(avg_z - cap)


def test_a_non_positive_capital_height_is_refused():
    mesh, degree = _flat_grid_with_degrees()
    top = sorted(degree, key=degree.get, reverse=True)[:9]
    with pytest.raises(ValueError):
        sg.add_column(mesh['nodes'], mesh['members'], top, height=3.0, capital_height=0.0)


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
    nodes, members, bases, _head = sg.add_column(mesh['nodes'], mesh['members'],
                                                top, height=3.0)
    base = bases[0]
    for m in members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    supports.extend({'node': b, 'type': 'pin'} for b in bases)
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
    nodes, members, bases, _head = sg.add_column(mesh['nodes'], mesh['members'], colinear,
                                                height=3.0)
    for m in members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    supports.extend({'node': b, 'type': 'pin'} for b in bases)
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is not None


@pytest.mark.parametrize('profile', sg.BEAM_PROFILES)
def test_every_beam_profile_solves_and_adds_the_chords_it_promises(profile):
    """Triangular puts one chord on the midline; the paired-chord sections
    put two out towards the base rows, which is only structurally sound once
    the bottom PLANE they create is braced against lozenging."""
    mesh = sg.flat_grid(span_x=12.0, span_y=12.0, depth=1.0, module=2.0)
    rows = {}
    for i, (x, y, z) in enumerate(mesh['nodes']):
        if abs(z) < 1e-9:
            rows.setdefault(round(y, 6), []).append(i)
    ys = sorted(rows)
    mid = len(ys) // 2
    edge_a = sorted(rows[ys[mid]], key=lambda i: mesh['nodes'][i][0])
    edge_b = sorted(rows[ys[mid + 1]], key=lambda i: mesh['nodes'][i][0])
    nodes, members, apex = sg.reinforcement_beam(mesh['nodes'], mesh['members'],
                                                 edge_a, edge_b, depth=1.6,
                                                 profile=profile)
    if profile == sg.BEAM_GRID_STRIP:
        # one offset node per BAY, under each module's own centre
        assert len(apex) == len(edge_a) - 1
    else:
        expected_rows = 1 if profile == sg.BEAM_TRIANGLE else 2
        assert len(apex) == expected_rows * len(edge_a)
    if profile == sg.BEAM_VIERENDEEL:
        assert all(m.get('conn') == 'rigid' for m in members
                   if m.get('rigid_required')), 'a Vierendeel member came out pinned'
    for m in members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
        # a Vierendeel carries load in BENDING, so its members need a second
        # moment and a torsion constant or the matrix is singular
        m.setdefault('I', 5000.0); m.setdefault('J', 8000.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    _res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None, f'{profile} did not solve: {err}'


def test_a_box_profile_is_wider_at_the_bottom_than_a_trapezoidal_one():
    mesh = sg.flat_grid(span_x=12.0, span_y=12.0, depth=1.0, module=2.0)
    rows = {}
    for i, (x, y, z) in enumerate(mesh['nodes']):
        if abs(z) < 1e-9:
            rows.setdefault(round(y, 6), []).append(i)
    ys = sorted(rows)
    mid = len(ys) // 2
    edge_a = sorted(rows[ys[mid]], key=lambda i: mesh['nodes'][i][0])
    edge_b = sorted(rows[ys[mid + 1]], key=lambda i: mesh['nodes'][i][0])
    widths = {}
    for profile in (sg.BEAM_BOX, sg.BEAM_TRAPEZOID):
        nodes, _members, apex = sg.reinforcement_beam(
            mesh['nodes'], mesh['members'], edge_a, edge_b, depth=1.6, profile=profile)
        widths[profile] = max(nodes[a][1] for a in apex) - min(nodes[a][1] for a in apex)
    assert widths[sg.BEAM_BOX] > widths[sg.BEAM_TRAPEZOID]
    base_width = abs(mesh['nodes'][edge_b[0]][1] - mesh['nodes'][edge_a[0]][1])
    assert widths[sg.BEAM_BOX] == pytest.approx(base_width)


@pytest.mark.parametrize('profile', sg.BEAM_PROFILES)
def test_a_parabolic_beam_is_deepest_at_midspan(profile):
    """The depth law is orthogonal to the cross-section: any profile can be
    built constant or fish-belly."""
    mesh = sg.flat_grid(span_x=16.0, span_y=12.0, depth=1.0, module=2.0)
    rows = {}
    for i, (x, y, z) in enumerate(mesh['nodes']):
        if abs(z) < 1e-9:
            rows.setdefault(round(y, 6), []).append(i)
    ys = sorted(rows)
    mid = len(ys) // 2
    edge_a = sorted(rows[ys[mid]], key=lambda i: mesh['nodes'][i][0])
    edge_b = sorted(rows[ys[mid + 1]], key=lambda i: mesh['nodes'][i][0])
    got = {}
    for law in sg.BEAM_DEPTH_LAWS:
        nodes, _members, apex = sg.reinforcement_beam(
            mesh['nodes'], mesh['members'], edge_a, edge_b, depth=1.6,
            profile=profile, depth_law=law)
        xs = sorted({round(nodes[a][0], 4) for a in apex})
        by_x = {}
        for a in apex:
            by_x.setdefault(round(nodes[a][0], 4), []).append(-nodes[a][2])
        got[law] = [max(by_x[x]) for x in xs]
    flat = got[sg.BEAM_DEPTH_CONSTANT]
    belly = got[sg.BEAM_DEPTH_PARABOLIC]
    assert len(set(round(d, 6) for d in flat)) == 1, 'a constant beam varied'
    span_mid = len(belly) // 2
    assert belly[span_mid] > belly[0], 'the fish-belly is not deepest at midspan'
    assert belly[0] > 0.0, 'a beam of zero depth at its support has no shear path'
    assert max(belly) <= max(flat) + 1e-9


def test_a_grid_strip_puts_its_chord_under_the_module_centre():
    """The mirrored 1 x n grid: every bay is a half-octahedron on the two
    base rows, the same module the flat grid itself is built from -- so the
    offset node sits BETWEEN two stations, not under one."""
    mesh = sg.flat_grid(span_x=12.0, span_y=12.0, depth=1.0, module=2.0)
    rows = {}
    for i, (x, y, z) in enumerate(mesh['nodes']):
        if abs(z) < 1e-9:
            rows.setdefault(round(y, 6), []).append(i)
    ys = sorted(rows)
    mid = len(ys) // 2
    edge_a = sorted(rows[ys[mid]], key=lambda i: mesh['nodes'][i][0])
    edge_b = sorted(rows[ys[mid + 1]], key=lambda i: mesh['nodes'][i][0])
    nodes, members, apex = sg.reinforcement_beam(
        mesh['nodes'], mesh['members'], edge_a, edge_b, depth=1.6,
        profile=sg.BEAM_GRID_STRIP)
    station_x = {round(mesh['nodes'][i][0], 4) for i in edge_a}
    for a in apex:
        assert round(nodes[a][0], 4) not in station_x, \
            'an offset node sits under a station, not under a module centre'
    # and each one reaches all four corners of its own module
    by_node = {}
    for m in members:
        by_node.setdefault(m['a'], set()).add(m['b'])
        by_node.setdefault(m['b'], set()).add(m['a'])
    base = set(edge_a) | set(edge_b)
    for a in apex:
        assert len(by_node[a] & base) == 4, 'a bay is not a half-octahedron'


def test_a_vierendeel_has_no_diagonals_and_keeps_its_rigid_joints():
    mesh = sg.flat_grid(span_x=12.0, span_y=12.0, depth=1.0, module=2.0)
    rows = {}
    for i, (x, y, z) in enumerate(mesh['nodes']):
        if abs(z) < 1e-9:
            rows.setdefault(round(y, 6), []).append(i)
    ys = sorted(rows)
    mid = len(ys) // 2
    edge_a = sorted(rows[ys[mid]], key=lambda i: mesh['nodes'][i][0])
    edge_b = sorted(rows[ys[mid + 1]], key=lambda i: mesh['nodes'][i][0])
    n0 = len(mesh['members'])
    nodes, members, _apex = sg.reinforcement_beam(
        mesh['nodes'], mesh['members'], edge_a, edge_b, depth=1.6,
        profile=sg.BEAM_VIERENDEEL)
    added = members[n0:]
    assert added
    for m in added:
        if not m.get('rigid_required'):
            continue
        ax, ay, az = nodes[m['a']]
        bx, by, bz = nodes[m['b']]
        # every member runs along exactly one axis: a diagonal would move in
        # the span direction AND across or down at the same time
        moves = sum(1 for d in (abs(bx - ax), abs(by - ay), abs(bz - az)) if d > 1e-6)
        assert moves == 1, f'a diagonal slipped into the Vierendeel: {m}'


def test_an_unknown_depth_law_is_refused():
    mesh = sg.flat_grid(span_x=8.0, span_y=8.0, depth=1.0, module=2.0)
    ids = [i for i, (x, y, z) in enumerate(mesh['nodes']) if abs(z) < 1e-9][:6]
    with pytest.raises(ValueError):
        sg.reinforcement_beam(mesh['nodes'], mesh['members'], ids[:3], ids[3:],
                              depth=1.0, depth_law='not a law')


def test_an_unknown_beam_profile_is_refused():
    mesh = sg.flat_grid(span_x=8.0, span_y=8.0, depth=1.0, module=2.0)
    ids = [i for i, (x, y, z) in enumerate(mesh['nodes']) if abs(z) < 1e-9][:6]
    with pytest.raises(ValueError):
        sg.reinforcement_beam(mesh['nodes'], mesh['members'], ids[:3], ids[3:],
                              depth=1.0, profile='not a profile')


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


# ── groin (cross) vault ──────────────────────────────────────────────────

@pytest.mark.parametrize('offset', [True, False])
@pytest.mark.parametrize('pattern', ['square', 'diagonal'])
def test_groin_vault_analyzes_cleanly(offset, pattern):
    mesh = sg.groin_vault(12.0, 3.0, 3.0, 0.5, offset=offset, pattern=pattern)
    assert _solves(mesh) is None


def test_groin_vault_produces_a_sane_mesh():
    mesh = sg.groin_vault(12.0, 3.0, 2.0, 0.5)
    _assert_mesh_is_sane(mesh)


def test_groin_vault_crown_is_full_rise_and_edges_are_at_ground():
    # module divides evenly into span so the centre lands on a node
    mesh = sg.groin_vault(12.0, 3.0, 3.0, 0.5)
    by_xy = {(round(x, 6), round(y, 6)): z for x, y, z in mesh['nodes']}
    assert by_xy[(6.0, 6.0)] == pytest.approx(3.0)   # crown
    assert by_xy[(0.0, 0.0)] == pytest.approx(0.0)    # corner
    assert by_xy[(0.0, 6.0)] == pytest.approx(0.0)    # mid-edge
    assert by_xy[(6.0, 0.0)] == pytest.approx(0.0)    # mid-edge


def test_groin_vault_diagonal_groin_line_reaches_full_rise_gradually():
    # along y=x (one of the two diagonals), both barrel profiles are
    # equal by construction, so the height there is the profile's own
    # smooth curve, not a flat plateau or a sharp jump.
    mesh = sg.groin_vault(12.0, 3.0, 1.0, 0.5)
    by_xy = {(round(x, 6), round(y, 6)): z for x, y, z in mesh['nodes']}
    # only the first half of the diagonal (corner to centre) is checked --
    # the full corner-to-corner diagonal rises to the crown then falls again,
    # so it is the half-diagonal that must be monotonically rising.
    diag_heights = [by_xy[(float(k), float(k))] for k in range(0, 7)
                   if (float(k), float(k)) in by_xy]
    assert len(diag_heights) > 5
    assert diag_heights == sorted(diag_heights)   # monotonically rising to the centre...
    assert diag_heights[-1] == pytest.approx(3.0)


def test_groin_vault_support_candidates_are_the_full_base_perimeter():
    # unlike barrel_vault's two springing lines only, a groin vault bears
    # on all four walls -- the same full perimeter flat_grid's own
    # bottom layer already offers.
    mesh = sg.groin_vault(12.0, 3.0, 3.0, 0.5)
    nodes = mesh['nodes']
    xs = sorted({round(nodes[i][0], 6) for i in mesh['support_candidates']})
    ys = sorted({round(nodes[i][1], 6) for i in mesh['support_candidates']})
    assert xs[0] == 0.0 and xs[-1] == 12.0
    assert ys[0] == 0.0 and ys[-1] == 12.0
    for i in mesh['support_candidates']:
        x, y, z = nodes[i]
        assert x in (0.0, 12.0) or y in (0.0, 12.0)


def test_groin_vault_rejects_nonpositive_dimensions():
    with pytest.raises(ValueError):
        sg.groin_vault(-1.0, 3.0, 3.0, 0.5)
    with pytest.raises(ValueError):
        sg.groin_vault(12.0, 0.0, 3.0, 0.5)


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


# ═══════════════════════════════════════════════════════════════════════
#  Multi-tier capitals and multi-layer reinforcement beams
# ═══════════════════════════════════════════════════════════════════════

def test_add_column_2tier_capital_fans_through_an_intermediate_ring():
    mesh, _ = _flat_grid_with_degrees()
    # a 3x3 block of one bottom-chord corner (9 nodes: 3 rows x 3 columns,
    # module=3 -> row stride 9 for this 24x24 mesh)
    targets = [0, 1, 2, 9, 10, 11, 18, 19, 20]
    n0, m0 = len(mesh['nodes']), len(mesh['members'])
    nodes, members, bases, head = sg.add_column(mesh['nodes'], mesh['members'], targets,
                                               height=3.0, tiers=2)
    assert len(nodes) == n0 + 2 + 4         # base + head + 4 intermediates (4 quadrants)
    capital = [m for m in members if m.get('role') == 'capital']
    ring = [m for m in members if m.get('role') == 'capital_ring']
    assert len(capital) == 4 + len(targets)  # head-to-intermediate + intermediate-to-target
    assert len(ring) == 4                    # one tie per adjacent intermediate pair
    assert len(members) == m0 + 1 + len(capital) + len(ring)

    for m in members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    supports.extend({'node': b, 'type': 'pin'} for b in bases)
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None


def test_add_column_rejects_2tier_capital_with_too_few_nodes_per_quadrant():
    mesh, _ = _flat_grid_with_degrees()
    # one module -- exactly 1 node per quadrant, not enough for a 2nd tier
    targets = [0, 1, 9, 10]
    with pytest.raises(ValueError):
        sg.add_column(mesh['nodes'], mesh['members'], targets, height=3.0, tiers=2)


def test_add_column_rejects_an_unknown_tier_count():
    mesh, degree = _flat_grid_with_degrees()
    top = sorted(degree, key=degree.get, reverse=True)[:4]
    with pytest.raises(ValueError):
        sg.add_column(mesh['nodes'], mesh['members'], top, height=3.0, tiers=3)


@pytest.mark.parametrize('tiers', [1, 2, 3])
def test_reinforcement_beam_multilayer_analyzes_cleanly(tiers):
    mesh, _ = _flat_grid_with_degrees()
    edge_a, edge_b = _two_adjacent_rows(mesh, 4)
    nodes, members, apex_ids = sg.reinforcement_beam(mesh['nodes'], mesh['members'],
                                                      edge_a, edge_b, depth=1.2, tiers=tiers)
    assert len(apex_ids) == tiers * len(edge_a)
    for m in members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None, f'tiers={tiers}: {err}'


def test_reinforcement_beam_tiers_are_stacked_at_increasing_depth():
    mesh, _ = _flat_grid_with_degrees()
    edge_a, edge_b = _two_adjacent_rows(mesh, 3)
    nodes, _members, apex_ids = sg.reinforcement_beam(mesh['nodes'], mesh['members'],
                                                       edge_a, edge_b, depth=3.0, tiers=3,
                                                       direction=(0.0, 0.0, -1.0))
    n = len(edge_a)
    tier1, tier2, tier3 = apex_ids[:n], apex_ids[n:2 * n], apex_ids[2 * n:]
    for k in range(n):
        z1, z2, z3 = nodes[tier1[k]][2], nodes[tier2[k]][2], nodes[tier3[k]][2]
        assert z1 > z2 > z3   # each tier further along -direction (deeper)


def test_reinforcement_beam_rejects_a_nonpositive_tier_count():
    mesh, _ = _flat_grid_with_degrees()
    edge_a, edge_b = _two_adjacent_rows(mesh, 2)
    with pytest.raises(ValueError):
        sg.reinforcement_beam(mesh['nodes'], mesh['members'], edge_a, edge_b, depth=1.0,
                              tiers=0)


# ── the grid's theoretical base module ──────────────────────────────────────

def test_the_base_module_of_a_flat_double_layer_grid_is_its_half_octahedron():
    """The reference drawing of the classic offset grid: a square the size
    of the module, one apex a depth below its centre, and the four web
    diagonals that reach it."""
    mesh = sg.flat_grid(span_x=12.0, span_y=12.0, depth=1.5, module=3.0)
    bm = sg.base_module(mesh['nodes'], mesh['members'])
    assert bm['shape'] == 'quad'
    assert bm['apexes'] == 1
    assert bm['planar'] is False
    assert len(bm['nodes']) == 5
    assert len(bm['members']) == 8          # 4 ring edges + 4 diagonals
    ring = [bm['nodes'][i] for i in bm['ring']]
    assert all(abs(p[2]) < 1e-9 for p in ring), 'the ring is the top chord plane'
    for i in range(4):
        assert math.dist(ring[i], ring[(i + 1) % 4]) == pytest.approx(3.0)
    assert abs(bm['nodes'][4][2]) == pytest.approx(1.5)


def test_a_single_layer_grids_base_module_is_a_flat_element():
    """The user-visible half of this: a surface mesh's module is a plate.
    Its corners come back exactly coplanar even though the real panel is
    warped around the shell -- the curvature belongs to the surface, not to
    the module."""
    mesh = sg.dome(base_radius=6.0, rise=2.0, n_rings=3, n_sectors=10)
    bm = sg.base_module(mesh['nodes'], mesh['members'])
    assert bm['planar'] is True
    assert bm['apexes'] == 0
    assert all(p[2] == 0.0 for p in bm['nodes'])


def test_a_surface_neighbour_is_not_mistaken_for_an_apex():
    """On a single-layer Schwedler dome a neighbouring node can be joined to
    all four corners of a panel and so passes the purely topological apex
    test -- while sitting 0.05 m out of a 2.14 m panel. Taking it would make
    a single-layer dome claim a solid module."""
    mesh = sg.dome(base_radius=6.0, rise=2.0, n_rings=3, n_sectors=10)
    cells = sg.find_cells(mesh['nodes'], mesh['members'])
    from apps.stereo import stereo_geometry_cells as gc
    trapped = [c for c in cells if gc._ring_apexes(mesh['members'], c['nodes'])]
    assert trapped, 'the fixture no longer has the trap'
    # every one of those "apexes" is a neighbour on the same single-layer
    # fabric, so the module this dome reports must still be flat
    assert sg.base_module(mesh['nodes'], mesh['members'])['apexes'] == 0


def test_the_base_module_is_expressed_in_its_own_frame_not_world_space():
    """A dome panel's module has to read upright whatever latitude the panel
    sits at, so corner 0 is the origin and corner 1 lies along +u."""
    mesh = sg.dome(base_radius=6.0, rise=2.0, n_rings=3, n_sectors=10)
    bm = sg.base_module(mesh['nodes'], mesh['members'])
    assert bm['nodes'][0] == (0.0, 0.0, 0.0)
    assert bm['nodes'][1][1] == pytest.approx(0.0, abs=1e-9)
    assert bm['nodes'][1][0] > 0.0


def test_the_base_module_reads_the_same_wherever_its_cell_sits():
    """Expressed in its own frame, the module of a dome panel at the crown
    and of one at the springing are the same drawing -- which is what makes
    it usable as a reference at all."""
    mesh = sg.dome(base_radius=6.0, rise=2.0, n_rings=3, n_sectors=10)
    cells = sg.find_cells(mesh['nodes'], mesh['members'])
    roles = sg.classify_cell_roles(mesh['nodes'], cells)['roles']
    dominant = roles[0]
    assert len(dominant) >= 2, 'the fixture has only one cell in its main role'
    from apps.stereo import stereo_geometry_cells as gc
    first = gc._local_frame_fn(mesh['nodes'], cells[dominant[0]]['nodes'])
    other = gc._local_frame_fn(mesh['nodes'], cells[dominant[-1]]['nodes'])
    a = [first(n) for n in cells[dominant[0]]['nodes']]
    b = [other(n) for n in cells[dominant[-1]]['nodes']]
    for pa, pb in zip(a, b):
        assert pa == pytest.approx(pb, abs=1e-6)


def test_the_base_module_survives_the_edits_that_used_to_redefine_it():
    """A reinforcement beam adds cells of its own; the grid's module is
    still the grid's module. (The app additionally FREEZES this at
    generation -- see StereoModuleEditorMixin._me_capture_base_module --
    because a shape signature alone cannot promise that for every edit.)"""
    mesh = sg.flat_grid(span_x=12.0, span_y=12.0, depth=1.5, module=3.0)
    before = sg.base_module(mesh['nodes'], mesh['members'])
    nodes, members = list(mesh['nodes']), list(mesh['members'])
    edge_a = sorted((i for i, p in enumerate(nodes)
                     if abs(p[1]) < 1e-9 and abs(p[2]) < 1e-9), key=lambda i: nodes[i][0])
    edge_b = sorted((i for i, p in enumerate(nodes)
                     if abs(p[1] - 12.0) < 1e-9 and abs(p[2]) < 1e-9),
                    key=lambda i: nodes[i][0])
    nodes, members = ga.reinforcement_beam(nodes, members, edge_a, edge_b, 2.0)[:2]
    assert len(members) > len(mesh['members']), 'the beam added nothing'
    assert sg.base_module(nodes, members) == before


def test_a_mesh_with_no_closed_cell_has_no_base_module():
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1}, {'a': 1, 'b': 2}]
    assert sg.base_module(nodes, members) is None


def test_every_generator_yields_a_usable_base_module():
    meshes = {
        'flat_grid': sg.flat_grid(12.0, 12.0, 1.5, 3.0),
        'hypar_shell': sg.hypar_shell(12.0, 12.0, 1.5, 3.0, 2.0),
        'hip_roof_grid': sg.hip_roof_grid(12.0, 12.0, 1.5, 3.0, 2.0),
        'groin_vault': sg.groin_vault(12.0, 3.0, 1.5, 3.0),
        'circular_flat_grid': sg.circular_flat_grid(8.0, 1.5, 3, 12),
        'barrel_vault': sg.barrel_vault(10.0, 2.5, 15.0),
        'parabolic_vault': sg.parabolic_vault(10.0, 2.5, 15.0),
        'elliptic_vault': sg.elliptic_vault(10.0, 2.5, 15.0),
        'dome': sg.dome(6.0, 2.0, 3, 10),
        'cone_roof': sg.cone_roof(6.0, 3.0, 3, 10),
        'paraboloid_dish': sg.paraboloid_dish(6.0, 2.0, 3, 10),
        'elliptic_dome': sg.elliptic_dome(6.0, 4.0, 2.0, 3, 10),
        'sphere_shell': sg.sphere_shell(6.0, 3, 10),
        'truss_bridge': sg.truss_bridge(24.0, 3.0, 6.0),
    }
    assert set(meshes) <= set(sg.GENERATORS), 'a generator was renamed'
    for name, mesh in meshes.items():
        bm = sg.base_module(mesh['nodes'], mesh['members'])
        assert bm is not None, f'{name} has no base module'
        assert len(bm['nodes']) >= 3, name
        assert bm['members'], name
        assert all(0 <= m['a'] < len(bm['nodes']) and 0 <= m['b'] < len(bm['nodes'])
                   for m in bm['members']), f'{name} points off its own node list'


# ── where a polar grid's pole goes ──────────────────────────────────────────

def _dome_at(cx, cy, peak=3.0, k=0.1):
    return sg.make_height_field_surface(f'{peak} - {k}*((x-{cx})**2 + (y-{cy})**2)')


def test_the_summit_of_a_single_peaked_surface_is_found_where_it_is():
    summits = sg.surface_summits(_dome_at(4.0, 4.0), (0.0, 8.0), (0.0, 8.0))
    assert len(summits) == 1
    assert summits[0]['x'] == pytest.approx(4.0, abs=0.2)
    assert summits[0]['y'] == pytest.approx(4.0, abs=0.2)
    assert summits[0]['z'] == pytest.approx(3.0, abs=0.01)


def test_a_sinusoidal_surface_reports_every_summit_it_has():
    """The user's own question: a surface with MANY apexes. One polar grid
    has one pole, so the count is what says a polar domain is the wrong
    chart here."""
    wavy = sg.make_height_field_surface('sin(x)*sin(y)')
    span = (0.0, 4.0 * math.pi)
    summits = sg.surface_summits(wavy, span, span, samples=81)
    assert len(summits) == 8
    assert all(s['z'] == pytest.approx(1.0, abs=0.02) for s in summits)


def test_hollows_are_found_the_same_way_as_summits():
    wavy = sg.make_height_field_surface('sin(x)*sin(y)')
    span = (0.0, 4.0 * math.pi)
    hollows = sg.surface_summits(wavy, span, span, samples=81, kind='min')
    assert len(hollows) == 8
    assert all(s['z'] == pytest.approx(-1.0, abs=0.02) for s in hollows)
    assert hollows[0]['z'] <= hollows[-1]['z']


def test_a_monotone_slope_has_no_summit_to_put_a_pole_on():
    """A ramp rises only towards its own edge, and a domain boundary is not
    a summit of the surface -- reporting one would send the pole to a corner."""
    ramp = sg.make_height_field_surface('0.5*x + 0.25*y')
    assert sg.surface_summits(ramp, (0.0, 8.0), (0.0, 8.0)) == []


def test_the_pole_moves_the_polar_grid_onto_the_summit():
    """The defect: the pole was hard-wired to the parameter origin, so a
    surface whose summit is at (4, 4) got a grid that never reached it."""
    surface = _dome_at(4.0, 4.0)
    kw = dict(coord='polar', p_range=(0.01, 4.0), q_range=(0.0, 2.0 * math.pi),
              n1=4, n2=12)
    at_origin = sg.custom_surface_grid(surface, **kw)
    on_summit = sg.custom_surface_grid(surface, pole=(4.0, 4.0), **kw)
    assert max(n[2] for n in on_summit["nodes"]) == pytest.approx(3.0, abs=1e-3)
    assert max(n[2] for n in at_origin['nodes']) < 2.9


def test_the_pole_leaves_a_cartesian_domain_alone():
    """It is a polar idea; a Cartesian lattice has no pole to move."""
    surface = _dome_at(4.0, 4.0)
    kw = dict(coord='cartesian', p_range=(0.0, 8.0), q_range=(0.0, 8.0), n1=4, n2=4)
    assert sg.custom_surface_grid(surface, **kw)['nodes'] == \
        sg.custom_surface_grid(surface, pole=(4.0, 4.0), **kw)['nodes']


def test_a_polar_grid_about_its_summit_has_congruent_rings():
    """What the pole is FOR. Centred on the summit of a surface of
    revolution, every node of one ring sits at the same height -- the rings
    follow the contours. Off-centre they do not."""
    surface = _dome_at(4.0, 4.0)
    kw = dict(coord='polar', p_range=(1.0, 4.0), q_range=(0.0, 2.0 * math.pi),
              n1=3, n2=16)
    centred = sg.custom_surface_grid(surface, pole=(4.0, 4.0), **kw)
    off = sg.custom_surface_grid(surface, **kw)

    def ring_spread(mesh):
        zs = sorted(round(n[2], 6) for n in mesh['nodes'])
        return max(zs) - min(zs), len(set(zs))

    _spread_c, levels_c = ring_spread(centred)
    _spread_o, levels_o = ring_spread(off)
    assert levels_c == 4, 'n1=3 gives 4 rings, each at one height'
    assert levels_o > 4 * levels_c, 'an off-centre grid should smear the rings'


def test_two_surfaces_take_the_same_pole():
    """A double layer is sampled over ONE domain, so the pole has to reach
    both or the two layers would be built about different centres."""
    top = _dome_at(4.0, 4.0, peak=3.0)
    bottom = _dome_at(4.0, 4.0, peak=2.0)
    kw = dict(coord='polar', p_range=(0.01, 4.0), q_range=(0.0, 2.0 * math.pi),
              n1=3, n2=12)
    mesh = sg.custom_surface_between(top, bottom, pole=(4.0, 4.0), **kw)
    # Both layers peak over the pole -- 3.0 for the top, 2.0 for the bottom
    # -- which they only do if the pole reached both. (r_min is 0.01, not 0,
    # so each apex node sits a hair off its own summit.)
    zs = [n[2] for n in mesh['nodes']]
    assert any(abs(z - 3.0) < 1e-3 for z in zs), 'the top layer missed its apex'
    assert any(abs(z - 2.0) < 1e-3 for z in zs), 'the bottom layer missed its apex'
    assert max(zs) == pytest.approx(3.0, abs=1e-3)


# ── two surfaces that cross are not a truss ─────────────────────────────────

def _height(expr):
    return sg.make_height_field_surface(expr)


def test_two_surfaces_that_cross_in_the_domain_are_refused():
    """A dish reaching zero at r = 6.93 is clear of a flat plane all the way
    along each edge of the square -6..6 -- and 2.00 m THROUGH it at every
    corner, which sits 8.49 m out. Past a crossing the webs invert and the
    truss is inside out, so this is a refusal, not a warning."""
    with pytest.raises(ValueError) as exc:
        sg.custom_surface_between(_height('3.0*(1-(x/6)**2-(y/6)**2)+1.0'), _height('0'),
                                  coord='cartesian', p_range=(-6.0, 6.0),
                                  q_range=(-6.0, 6.0), n1=8, n2=8)
    assert 'cross' in str(exc.value)


def test_the_refusal_says_where_the_crossing_is():
    """The fix is either a smaller domain or a different expression, and
    nobody can pick between them without knowing which part of the domain
    is the problem."""
    with pytest.raises(ValueError) as exc:
        sg.custom_surface_between(_height('3.0*(1-(x/6)**2-(y/6)**2)+1.0'), _height('0'),
                                  coord='cartesian', p_range=(-6.0, 6.0),
                                  q_range=(-6.0, 6.0), n1=8, n2=8)
    message = str(exc.value)
    assert '(x, y)' in message
    assert 'Shrink the domain' in message


def test_two_surfaces_that_stay_apart_build_normally():
    mesh = sg.custom_surface_between(_height('3.0*(1-(x/12)**2-(y/12)**2)+1.0'),
                                     _height('0'), coord='cartesian',
                                     p_range=(-6.0, 6.0), q_range=(-6.0, 6.0), n1=8, n2=8)
    assert mesh['nodes'] and mesh['members']


def test_the_same_pair_is_fine_over_a_domain_that_stops_short():
    """The crossing is a property of the PAIR AND the domain, not of the
    expressions alone -- the same two surfaces are a perfectly good truss
    over a window that stops before they meet."""
    top, bottom = _height('3.0*(1-(x/6)**2-(y/6)**2)+1.0'), _height('0')
    with pytest.raises(ValueError):
        sg.custom_surface_between(top, bottom, coord='cartesian',
                                  p_range=(-6.0, 6.0), q_range=(-6.0, 6.0), n1=8, n2=8)
    mesh = sg.custom_surface_between(top, bottom, coord='cartesian',
                                     p_range=(-4.0, 4.0), q_range=(-4.0, 4.0), n1=8, n2=8)
    assert mesh['nodes']


def test_surfaces_that_merely_touch_are_refused_too():
    """A tangency gives a web of zero length -- a member with no direction,
    which the solver cannot use even though nothing has inverted yet."""
    where = sg.surfaces_cross(_height('x**2'), _height('0'), coord='cartesian',
                              p_range=(-2.0, 2.0), q_range=(-2.0, 2.0), n1=8, n2=8)
    assert where is not None
    assert where['gap'] == pytest.approx(0.0, abs=1e-9)


def test_a_crossing_between_two_nodes_is_still_caught():
    """The check samples finer than the lattice on purpose: a crossing that
    dips between two nodes still puts one layer's chords through the
    other's in that strip."""
    # crosses only in a narrow band around |x| = 3, which a 4-division
    # lattice over -6..6 steps straight over (nodes at -6, -3, 0, 3, 6)
    top = _height('1.0 - 4.0*exp(-((abs(x)-3.0)**2)/0.05)')
    where = sg.surfaces_cross(top, _height('0'), coord='cartesian',
                              p_range=(-6.0, 6.0), q_range=(-6.0, 6.0), n1=4, n2=4)
    assert where is not None


def test_a_polar_pair_is_checked_around_its_own_seam():
    """A full-turn domain closes j = n2 back to j = 0, so the sample at one
    end of the sweep is the neighbour of the sample at the other."""
    top = _height('2.0 + 3.0*x')     # rises on one side, falls on the other
    where = sg.surfaces_cross(top, _height('0'), coord='polar',
                              p_range=(0.1, 4.0), q_range=(0.0, 2.0 * math.pi),
                              n1=6, n2=12)
    assert where is not None


def test_concentric_domes_are_not_mistaken_for_a_crossing():
    """Two strongly curved layers are NOT crossed just because their webs
    point very different ways at the crown and at the rim -- the test is
    local (each web against its neighbour), not against one fixed
    direction."""
    assert sg.surfaces_cross(_height('4.0*(1-(x/6)**2-(y/6)**2)+2.0'),
                             _height('2.0*(1-(x/6)**2-(y/6)**2)'),
                             coord='polar', p_range=(0.3, 6.0),
                             q_range=(0.0, 2.0 * math.pi), n1=6, n2=12) is None


def test_every_wizard_example_keeps_its_surfaces_apart():
    """The regression this whole check exists for: the shipped two-surface
    example crossed its own flat plane at all four corners."""
    from apps.stereo import stereo_examples as sx
    built = 0
    for label, builder in sx.EXAMPLES:
        mesh = builder()                 # raises if a pair crosses
        assert mesh['nodes'], label
        built += 1
    assert built == len(sx.EXAMPLES)


def test_the_dish_example_clears_the_plane_at_its_own_corners():
    from apps.stereo import stereo_examples as sx
    top = _height('3.0 * (1 - (x/12)**2 - (y/12)**2) + 1.0')
    for x, y in ((-6.0, -6.0), (6.0, -6.0), (-6.0, 6.0), (6.0, 6.0)):
        assert top(x, y)[2] > 2.0, 'the dish dips towards the plane at a corner'
    assert top(0.0, 0.0)[2] == pytest.approx(4.0)


# ── lattice types: how the two layers register against each other ───────────

def _flat():
    return sg.make_height_field_surface('0')


@pytest.mark.parametrize('lattice', sg.LATTICE_TYPES)
def test_every_lattice_type_builds(lattice):
    mesh = sg.custom_surface_lattice(_flat(), coord='cartesian', lattice=lattice,
                                     p_range=(0.0, 12.0), q_range=(0.0, 12.0),
                                     n1=4, n2=4, depth=1.5)
    assert mesh['nodes'] and mesh['members']
    assert mesh['support_candidates']
    assert all(0 <= m['a'] < len(mesh['nodes']) and 0 <= m['b'] < len(mesh['nodes'])
               for m in mesh['members'])


def test_the_offset_layer_sits_under_the_centre_of_a_top_cell():
    """The whole point of an offset frame: a bottom node under the middle of
    a top square, tying its four corners. Sample them at the same (i, j) and
    every web is a vertical post and the two layers are one lattice twice."""
    mesh = sg.custom_surface_lattice(_flat(), lattice=sg.LATTICE_SOS_OFFSET,
                                     p_range=(0.0, 12.0), q_range=(0.0, 12.0),
                                     n1=4, n2=4, depth=1.5)
    tops = [n for n in mesh['nodes'] if n[2] == pytest.approx(0.0)]
    bots = [n for n in mesh['nodes'] if n[2] == pytest.approx(-1.5)]
    assert len(tops) == 25 and len(bots) == 16
    # every bottom node lands on a half-module offset in BOTH directions
    for x, y, _z in bots:
        assert (x / 3.0 - 0.5) == pytest.approx(round(x / 3.0 - 0.5))
        assert (y / 3.0 - 0.5) == pytest.approx(round(y / 3.0 - 0.5))


def test_every_bottom_node_ties_to_four_top_corners():
    mesh = sg.custom_surface_lattice(_flat(), lattice=sg.LATTICE_SOS_OFFSET,
                                     p_range=(0.0, 9.0), q_range=(0.0, 9.0),
                                     n1=3, n2=3, depth=1.5)
    webs = [m for m in mesh['members'] if m.get('role') == 'web']
    assert len(webs) == 9 * 4
    from collections import Counter
    per_bottom = Counter()
    for m in webs:
        lo = m['a'] if mesh['nodes'][m['a']][2] < mesh['nodes'][m['b']][2] else m['b']
        per_bottom[lo] += 1
    assert set(per_bottom.values()) == {4}


def test_the_three_double_layer_lattices_differ_in_rod_count():
    """They are genuinely different structures over the same surfaces --
    different rod counts, lengths and load paths -- which is why the choice
    belongs in the UI rather than being fixed."""
    counts = {}
    for lattice in (sg.LATTICE_SOS_OFFSET, sg.LATTICE_SQ_ON_DIAG, sg.LATTICE_DIAG_ON_DIAG):
        mesh = sg.custom_surface_lattice(_flat(), lattice=lattice,
                                         p_range=(0.0, 12.0), q_range=(0.0, 12.0),
                                         n1=4, n2=4, depth=1.5)
        counts[lattice] = len(mesh['members'])
    assert len(set(counts.values())) == 3, counts
    assert counts[sg.LATTICE_SOS_OFFSET] < counts[sg.LATTICE_DIAG_ON_DIAG]


@pytest.mark.parametrize('lattice', [sg.LATTICE_SOS_OFFSET, sg.LATTICE_SQ_ON_DIAG,
                                     sg.LATTICE_DIAG_ON_DIAG])
def test_every_double_layer_lattice_solves_under_self_weight(lattice):
    mesh = sg.custom_surface_lattice(_flat(), lattice=lattice,
                                     p_range=(0.0, 12.0), q_range=(0.0, 12.0),
                                     n1=4, n2=4, depth=1.5)
    for m in mesh['members']:
        m.setdefault('E', 200.0)
        m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(mesh['nodes'], mesh['members'], 78.5)
    _res, err = sm.analyze(mesh['nodes'], mesh['members'], loads, supports)
    assert err is None, f'{lattice}: {err}'


def test_a_flat_single_layer_of_pinned_bars_is_honestly_a_mechanism():
    """Physics, not a defect. A plane grid of pinned bars has no
    out-of-plane stiffness; the app reports it rather than quietly bracing
    something the user did not ask for."""
    mesh = sg.custom_surface_lattice(_flat(), lattice=sg.LATTICE_SINGLE,
                                     p_range=(0.0, 12.0), q_range=(0.0, 12.0), n1=4, n2=4)
    for m in mesh['members']:
        m.setdefault('E', 200.0)
        m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(mesh['nodes'], mesh['members'], 78.5)
    _res, err = sm.analyze(mesh['nodes'], mesh['members'], loads, supports)
    assert err is not None and 'mechanism' in err.lower()


def test_a_curved_single_layer_stands_up_on_its_own():
    """The same lattice on a curved surface has shell action and solves."""
    dome = sg.make_height_field_surface('4 - 0.05*(x**2 + y**2)')
    mesh = sg.custom_surface_lattice(dome, lattice=sg.LATTICE_SINGLE,
                                     p_range=(-6.0, 6.0), q_range=(-6.0, 6.0), n1=5, n2=5)
    for m in mesh['members']:
        m.setdefault('E', 200.0)
        m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(mesh['nodes'], mesh['members'], 78.5)
    _res, err = sm.analyze(mesh['nodes'], mesh['members'], loads, supports)
    assert err is None, err


def test_a_lattice_over_two_surfaces_keeps_the_crossing_check():
    top = sg.make_height_field_surface('3.0*(1-(x/6)**2-(y/6)**2)+1.0')
    with pytest.raises(ValueError) as exc:
        sg.custom_surface_lattice(top, sg.make_height_field_surface('0'),
                                  p_range=(-6.0, 6.0), q_range=(-6.0, 6.0), n1=4, n2=4)
    assert 'cross' in str(exc.value)


def test_an_unknown_lattice_is_refused():
    with pytest.raises(ValueError):
        sg.custom_surface_lattice(_flat(), lattice='herringbone')


def test_a_polar_lattice_is_built_about_its_pole():
    dome = sg.make_height_field_surface('3 - 0.1*((x-4)**2 + (y-4)**2)')
    mesh = sg.custom_surface_lattice(dome, coord='polar', lattice=sg.LATTICE_SOS_OFFSET,
                                     p_range=(0.01, 4.0), q_range=(0.0, 2.0 * math.pi),
                                     n1=4, n2=12, depth=1.0, pole=(4.0, 4.0))
    assert max(n[2] for n in mesh['nodes']) == pytest.approx(3.0, abs=1e-3)


# ── plan-shape domain mask ───────────────────────────────────────────────────

def _lattice_12m(n=6):
    # The top must stay clear of the bottom across the WHOLE domain, or the
    # crossing check refuses the pair before any of this gets a chance to
    # run: 0.2*x over -6..6 reaches -1.2, so a bottom at -1.0 would meet it.
    top = sg.make_height_field_surface('0.2 * x')
    bot = sg.make_height_field_surface('-3.0')
    return sg.custom_surface_lattice(top, bot, lattice=sg.LATTICE_SOS_OFFSET,
                                     p_range=(-6.0, 6.0), q_range=(-6.0, 6.0),
                                     n1=n, n2=n)


def test_an_empty_rule_is_no_rule_at_all():
    """The no-mask case has to cost nothing, so every generator can pipe
    through apply_domain_mask without checking first."""
    assert sg.make_domain_fn('') is None
    assert sg.make_domain_fn(None) is None
    mesh = _lattice_12m()
    assert sg.apply_domain_mask(mesh, None) is mesh


def test_a_circular_rule_cuts_the_corners_off_a_square_domain():
    mesh = _lattice_12m()
    cut = sg.apply_domain_mask(mesh, sg.make_domain_fn('x^2 + y^2 < 16'))
    assert len(cut['nodes']) < len(mesh['nodes'])
    assert all(math.hypot(x, y) < 8.0 for x, y, _z in cut['nodes'])


def test_the_mask_keeps_the_chords_that_frame_the_hole():
    """A member survives only if BOTH ends do, and a node with no member
    left is dropped -- which is what stops the cut leaving a rim of
    half-connected nodes the solver would call a mechanism."""
    mesh = _lattice_12m()
    cut = sg.apply_domain_mask(mesh, sg.make_domain_fn('x^2 + y^2 < 16'))
    n = len(cut['nodes'])
    assert all(0 <= m['a'] < n and 0 <= m['b'] < n for m in cut['members'])
    attached = set()
    for m in cut['members']:
        attached.add(m['a'])
        attached.add(m['b'])
    assert attached == set(range(n)), 'a node survived with nothing attached'


def test_the_cut_edge_becomes_a_support_candidate():
    """A cut makes a NEW free edge. Keeping only the old rectangle's
    perimeter would leave the new rim with nothing to stand on."""
    mesh = _lattice_12m()
    cut = sg.apply_domain_mask(mesh, sg.make_domain_fn('x^2 + y^2 < 16'))
    assert cut['support_candidates']
    rim = [math.hypot(*cut['nodes'][i][:2]) for i in cut['support_candidates']]
    assert max(rim) > 3.0


def test_load_areas_follow_their_nodes_through_the_renumbering():
    mesh = _lattice_12m()
    cut = sg.apply_domain_mask(mesh, sg.make_domain_fn('x^2 + y^2 < 16'))
    assert cut['load_nodes']
    assert all(0 <= i < len(cut['nodes']) for i in cut['load_nodes'])
    assert all(a > 0 for a in cut['load_nodes'].values())


def test_a_rule_that_keeps_nothing_is_an_error_not_an_empty_mesh():
    mesh = _lattice_12m()
    with pytest.raises(ValueError, match='removed the whole structure'):
        sg.apply_domain_mask(mesh, lambda x, y: False)


def test_the_cut_is_module_granular_not_node_granular():
    """A surviving bottom node keeps the top corners its webs hang from,
    even across the line. The overshoot is bounded by one module -- that is
    the framing around the opening, not a leak."""
    mesh = _lattice_12m(n=6)
    cut = sg.apply_domain_mask(mesh, sg.make_domain_fn('x < 0'))
    module = 12.0 / 6
    assert max(x for x, _y, _z in cut['nodes']) <= module + 1e-6


def test_a_masked_lattice_still_solves():
    mesh = _lattice_12m()
    cut = sg.apply_domain_mask(mesh, sg.make_domain_fn('x^2 + y^2 < 16'))
    members = [dict(m, A=20.0, E=200.0, Fy=235.0, r_gyr=4.0) for m in cut['members']]
    loads = [{'node': i, 'fz': -5.0} for i in range(len(cut['nodes']))]
    supports = [{'node': i, 'type': 'pin'} for i in cut['support_candidates']]
    _res, err = sm.analyze(cut['nodes'], members, loads, supports)
    assert err is None, err


def test_a_domain_rule_may_name_the_domain_it_is_written_against():
    keep = sg.make_domain_fn('x < Lx / 2', {'Lx': 12.0})
    assert keep(5.0, 0.0) and not keep(7.0, 0.0)


# ── the latticed column, rebuilt ─────────────────────────────────────────────

def test_a_latticed_columns_chords_run_straight_down_from_the_nodes_it_carries():
    """The first version stood on an invented square of its own `width` near
    the centroid, which is not under the joints it carries at all."""
    mesh, _degree = _flat_grid_with_degrees()
    top = _square_footprint(mesh)
    want = sorted((round(mesh['nodes'][j][0], 6), round(mesh['nodes'][j][1], 6))
                  for j in top)
    nodes, _members, bases, _head = sg.add_column(
        mesh['nodes'], mesh['members'], top, height=4.0, style=sg.COLUMN_LATTICE)
    got = sorted((round(nodes[b][0], 6), round(nodes[b][1], 6)) for b in bases)
    assert got == want, 'the feet are not under the nodes the column carries'


def test_a_latticed_column_has_no_capital_at_all():
    """A capital exists to stop a column piercing the grid through ONE joint.
    A latticed column already arrives at three or four separate joints, so a
    capital squeezed all of them back through one node on the way -- the very
    thing it is there to avoid."""
    mesh, _degree = _flat_grid_with_degrees()
    top = _square_footprint(mesh)
    m0 = len(mesh['members'])
    _nodes, members, _bases, _head = sg.add_column(
        mesh['nodes'], mesh['members'], top, height=4.0, style=sg.COLUMN_LATTICE)
    new = members[m0:]
    assert new, 'the column added nothing'
    assert not [m for m in new if str(m.get('role', '')).startswith('capital')]


def test_a_latticed_column_can_have_three_chords():
    mesh, _degree = _flat_grid_with_degrees()
    tri = _square_footprint(mesh, n=3)
    nodes, members, bases, _head = sg.add_column(
        mesh['nodes'], mesh['members'], tri, height=4.0,
        style=sg.COLUMN_LATTICE, panels=3)
    assert len(bases) == 3
    chords = [m for m in members if m.get('role') == 'column_chord']
    assert len(chords) == 3 * 3, '3 chords over 3 panels'
    want = sorted((round(mesh['nodes'][j][0], 6), round(mesh['nodes'][j][1], 6))
                  for j in tri)
    got = sorted((round(nodes[b][0], 6), round(nodes[b][1], 6)) for b in bases)
    assert got == want


@pytest.mark.parametrize('count', [1, 2, 5, 9])
def test_a_latticed_column_refuses_anything_but_three_or_four_nodes(count):
    """One chord per node it carries is the whole idea; five nodes is not a
    column, it is a request the shape cannot answer."""
    mesh, degree = _flat_grid_with_degrees()
    top = sorted(degree, key=degree.get, reverse=True)[:count]
    with pytest.raises(ValueError, match='3 or 4'):
        sg.add_column(mesh['nodes'], mesh['members'], top, height=4.0,
                      style=sg.COLUMN_LATTICE)


def test_a_latticed_column_refuses_a_collinear_footprint():
    """Three nodes in a line enclose no area, so the column can fold about
    that line however it is braced."""
    mesh, _degree = _flat_grid_with_degrees()
    nodes = mesh['nodes']
    zmax = max(p[2] for p in nodes)
    row_y = min(p[1] for p in nodes if abs(p[2] - zmax) < 1e-9)
    line = [i for i, p in enumerate(nodes)
            if abs(p[2] - zmax) < 1e-9 and abs(p[1] - row_y) < 1e-9][:3]
    assert len(line) == 3
    with pytest.raises(ValueError, match='straight line'):
        sg.add_column(nodes, mesh['members'], line, height=4.0,
                      style=sg.COLUMN_LATTICE)


def test_the_bracing_joins_neighbours_not_opposite_corners():
    """Taken in selection order a four-node footprint can come out as a
    bow-tie, and the X bracing then crosses the middle of the column instead
    of lying on its faces."""
    mesh, _degree = _flat_grid_with_degrees()
    top = _square_footprint(mesh)
    scrambled = [top[0], top[3], top[1], top[2]]
    nodes, members, bases, _head = sg.add_column(
        mesh['nodes'], mesh['members'], scrambled, height=4.0,
        style=sg.COLUMN_LATTICE, panels=1)
    side = min(math.dist(nodes[a][:2], nodes[b][:2])
               for a in bases for b in bases if a != b)
    ties = [m for m in members if m.get('role') == 'column_tie'
            and m['a'] in bases and m['b'] in bases]
    assert ties
    for m in ties:
        d = math.dist(nodes[m['a']][:2], nodes[m['b']][:2])
        assert d < side * 1.3, 'a tie crosses the footprint diagonally'


def test_a_tapered_latticed_column_keeps_the_selections_plan_shape():
    """Narrowed, not a different footprint: every foot moves toward the
    centroid by the same fraction."""
    mesh, _degree = _flat_grid_with_degrees()
    top = _square_footprint(mesh)
    nodes, _m, bases, _h = sg.add_column(
        mesh['nodes'], mesh['members'], top, height=4.0, style=sg.COLUMN_TAPERED)
    cx = sum(mesh['nodes'][j][0] for j in top) / len(top)
    cy = sum(mesh['nodes'][j][1] for j in top) / len(top)
    ratios = []
    for b in bases:
        r_top = max(math.dist((mesh['nodes'][j][0], mesh['nodes'][j][1]), (cx, cy))
                    for j in top)
        ratios.append(math.dist((nodes[b][0], nodes[b][1]), (cx, cy)) / r_top)
    assert max(ratios) - min(ratios) < 1e-9, 'the footprint changed shape'
    assert 0.0 < ratios[0] < 1.0


def test_a_footprint_with_three_nodes_in_a_line_is_refused():
    """Plan area alone is not enough. A kite -- which is exactly what "the
    four bottom nodes nearest the centre" gives on an odd grid -- encloses a
    real area while three of its corners sit on one line. The two faces
    meeting at that middle corner are then coplanar, their bracing lies in
    one plane, and the column hinges about the line. The solver called that
    a singular matrix, which tells nobody which four nodes to pick instead.
    """
    mesh, _degree = _flat_grid_with_degrees()
    nodes = mesh['nodes']
    zmax = max(p[2] for p in nodes)

    def near(px, py):
        return min((i for i, p in enumerate(nodes) if abs(p[2] - zmax) < 1e-9),
                   key=lambda i: (nodes[i][0] - px) ** 2 + (nodes[i][1] - py) ** 2)

    xs = sorted({round(p[0], 6) for p in nodes if abs(p[2] - zmax) < 1e-9})
    ys = sorted({round(p[1], 6) for p in nodes if abs(p[2] - zmax) < 1e-9})
    x0, x1, x2 = xs[0], xs[1], xs[2]
    y0, y1 = ys[0], ys[1]
    kite = [near(x0, y1), near(x1, y1), near(x2, y1), near(x1, y0)]
    assert len(set(kite)) == 4
    with pytest.raises(ValueError, match='straight line'):
        sg.add_column(nodes, mesh['members'], kite, height=4.0,
                      style=sg.COLUMN_LATTICE)


def test_a_footprint_with_a_node_inside_the_others_is_refused():
    """It would brace across its own middle instead of round its faces."""
    mesh, _degree = _flat_grid_with_degrees()
    nodes = mesh['nodes']
    zmax = max(p[2] for p in nodes)

    def near(px, py):
        return min((i for i, p in enumerate(nodes) if abs(p[2] - zmax) < 1e-9),
                   key=lambda i: (nodes[i][0] - px) ** 2 + (nodes[i][1] - py) ** 2)

    xs = sorted({round(p[0], 6) for p in nodes if abs(p[2] - zmax) < 1e-9})
    ys = sorted({round(p[1], 6) for p in nodes if abs(p[2] - zmax) < 1e-9})
    inside = [near(xs[0], ys[0]), near(xs[2], ys[0]), near(xs[1], ys[2]),
              near(xs[1], ys[1])]
    assert len(set(inside)) == 4
    with pytest.raises(ValueError, match='convex'):
        sg.add_column(nodes, mesh['members'], inside, height=4.0,
                      style=sg.COLUMN_LATTICE)


def test_a_square_and_a_diamond_footprint_are_both_accepted():
    """The guard must not become "axis-aligned squares only"."""
    mesh, _degree = _flat_grid_with_degrees()
    nodes = mesh['nodes']
    zmax = max(p[2] for p in nodes)

    def near(px, py):
        return min((i for i, p in enumerate(nodes) if abs(p[2] - zmax) < 1e-9),
                   key=lambda i: (nodes[i][0] - px) ** 2 + (nodes[i][1] - py) ** 2)

    xs = sorted({round(p[0], 6) for p in nodes if abs(p[2] - zmax) < 1e-9})
    ys = sorted({round(p[1], 6) for p in nodes if abs(p[2] - zmax) < 1e-9})
    square = [near(xs[0], ys[0]), near(xs[1], ys[0]),
              near(xs[1], ys[1]), near(xs[0], ys[1])]
    diamond = [near(xs[1], ys[0]), near(xs[2], ys[1]),
               near(xs[1], ys[2]), near(xs[0], ys[1])]
    for footprint in (square, diamond):
        assert len(set(footprint)) == 4
        _n, _m, bases, _h = sg.add_column(nodes, mesh['members'], footprint,
                                          height=4.0, style=sg.COLUMN_LATTICE)
        assert len(bases) == 4
