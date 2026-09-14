"""The surface tessellation engine, tested without building a widget.

Everything here is pure geometry over (nodes, members), which is exactly why
stereo_voronoi_surface returns model-space polygons and leaves projection,
depth sorting and colour to the renderer.
"""
import math

import numpy as np
import pytest

from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_voronoi_surface as svs


# ── fixtures: one flat panel, one double-layer slab, one vault ──────────────

@pytest.fixture
def unit_quad():
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    members = [{'a': 0, 'b': 1}, {'a': 1, 'b': 2}, {'a': 2, 'b': 3}, {'a': 3, 'b': 0}]
    return nodes, members


def _mesh(d):
    """The generators return a full mesh dict; these tests only need its
    geometry."""
    return d['nodes'], d['members']


@pytest.fixture
def slab():
    return _mesh(sg.flat_grid(span_x=12.0, span_y=12.0, depth=1.5, module=3.0))


@pytest.fixture
def vault():
    return _mesh(sg.parabolic_vault(span=10.0, rise=2.5, length=15.0))


def _rod_sites(nodes, members):
    pts = np.asarray(nodes, dtype=float)
    return np.array([(pts[m['a']] + pts[m['b']]) / 2.0 for m in members])


def _tessellate(nodes, members):
    panels = svs.panels_of(nodes, members)
    sites = _rod_sites(nodes, members)
    panel_sites = [list(p['members']) for p in panels]
    return panels, sites, svs.build_surface(nodes, panels, sites, panel_sites)


# ── the domain is the fabric ────────────────────────────────────────────────

def test_the_panels_cover_every_rod(slab, vault):
    for nodes, members in (slab, vault):
        panels = svs.panels_of(nodes, members)
        used = set()
        for p in panels:
            used.update(p['members'])
        assert len(used) == len(members), \
            f'{len(members) - len(used)} rods belong to no panel'


def test_nothing_is_drawn_out_in_the_void_a_vault_arches_over(vault):
    """The defect this engine exists to fix. The convex hull's own lowest
    face on this model is a flat 15 x 10 m slab whose centre is 2.01 m from
    the nearest rod; not one patch may land out there."""
    nodes, members = vault
    _panels, _sites, patches = _tessellate(nodes, members)
    assert patches
    pts = np.asarray(nodes, dtype=float)
    a = pts[[m['a'] for m in members]]
    ab = pts[[m['b'] for m in members]] - a
    L2 = np.maximum((ab * ab).sum(axis=1), 1e-12)
    worst = 0.0
    for poly, _owner in patches:
        q = poly.mean(axis=0)
        t = np.clip(((q - a) * ab).sum(axis=1) / L2, 0.0, 1.0)
        worst = max(worst, float(np.linalg.norm(q - (a + t[:, None] * ab), axis=1).min()))
    assert worst < 0.5, f'a patch centre sits {worst:.2f} m from any rod'


def test_every_patch_belongs_to_a_real_site(slab):
    nodes, members = slab
    _panels, sites, patches = _tessellate(nodes, members)
    assert patches
    assert all(0 <= owner < len(sites) for _poly, owner in patches)


def test_a_single_panel_still_tessellates(unit_quad):
    nodes, members = unit_quad
    _panels, _sites, patches = _tessellate(nodes, members)
    assert patches, 'one closed quad is a perfectly good surface'


def test_a_mesh_with_no_closed_panel_yields_nothing():
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1}, {'a': 1, 'b': 2}]
    panels = svs.panels_of(nodes, members)
    assert panels == []
    assert svs.build_surface(nodes, panels, _rod_sites(nodes, members), []) == []


# ── the metric follows the surface ──────────────────────────────────────────

def test_a_top_layer_panel_is_owned_by_a_top_layer_rod(slab):
    """Measured in straight-line 3D on this grid, a top panel's own chords
    are 1.500 m away and four web diagonals 1.299 m -- an exact tie among the
    four, so the winner fell to floating-point ordering and 0% of top panels
    got a top-layer rod. Distance along the fabric has no such failure."""
    nodes, members = slab
    panels = svs.panels_of(nodes, members)
    pts = np.asarray(nodes, dtype=float)
    top_z = pts[:, 2].max()
    sites = _rod_sites(nodes, members)
    polys = svs.panel_polys(nodes, panels)
    cen = svs.panel_centroids(polys)
    adj, _ = svs.panel_adjacency(panels)
    owners = svs.assign_owners(cen, [list(p['members']) for p in panels], sites, adj)
    tops = [i for i in range(len(panels)) if abs(cen[i][2] - top_z) < 1e-6]
    assert tops, 'no top-layer panels found -- the fixture changed'
    assert all(abs(sites[owners[i]][2] - top_z) < 1e-6 for i in tops)


def test_an_owner_always_lies_on_its_own_panel(slab):
    nodes, members = slab
    panels = svs.panels_of(nodes, members)
    sites = _rod_sites(nodes, members)
    polys = svs.panel_polys(nodes, panels)
    adj, _ = svs.panel_adjacency(panels)
    panel_sites = [list(p['members']) for p in panels]
    owners = svs.assign_owners(svs.panel_centroids(polys), panel_sites, sites, adj)
    for i, p in enumerate(panels):
        assert owners[i] in p['members'], \
            'a panel was captured by a rod that is not on it'


def test_a_panel_with_no_site_is_reached_through_its_neighbours(slab):
    """The Dijkstra fallback. It never fires for rod-midpoint or nodal sites,
    but it is what keeps the engine usable if sites are ever subsampled."""
    nodes, members = slab
    panels = svs.panels_of(nodes, members)
    sites = _rod_sites(nodes, members)
    polys = svs.panel_polys(nodes, panels)
    adj, _ = svs.panel_adjacency(panels)
    panel_sites = [list(p['members']) for p in panels]
    panel_sites[0] = []                       # starve one panel
    owners = svs.assign_owners(svs.panel_centroids(polys), panel_sites, sites, adj)
    assert owners[0] >= 0, 'a starved panel was left unowned'
    assert owners[0] in {owners[j] for j in adj[0]}


# ── resolution ──────────────────────────────────────────────────────────────

def test_a_coarse_mesh_is_subdivided_and_a_dense_one_is_not(slab, vault):
    assert svs.subdivision_levels(90) >= 1, 'a 90-panel dome needs refining'
    assert svs.subdivision_levels(2999) == 0, 'a 2999-panel vault does not'
    for nodes, members in (slab, vault):
        panels = svs.panels_of(nodes, members)
        _p, _s, patches = _tessellate(nodes, members)
        assert len(patches) >= len(panels)


def test_subdivision_preserves_the_panel(unit_quad):
    nodes, _members = unit_quad
    poly = np.asarray(nodes, dtype=float)
    tris = svs.subdivide(svs.fan_triangles(poly), 2)
    area = sum(0.5 * np.linalg.norm(np.cross(t[1] - t[0], t[2] - t[0])) for t in tris)
    assert area == pytest.approx(1.0)
    assert len(tris) == 2 * 4 ** 2


def test_the_patch_budget_is_respected(slab):
    nodes, members = slab
    panels = svs.panels_of(nodes, members)
    sites = _rod_sites(nodes, members)
    patches = svs.build_surface(nodes, panels, sites,
                                [list(p['members']) for p in panels],
                                target=40_000)
    assert len(patches) <= 40_000


# ── cell outlines ───────────────────────────────────────────────────────────

def test_cell_outlines_only_appear_where_ownership_changes(slab):
    nodes, members = slab
    panels = svs.panels_of(nodes, members)
    sites = _rod_sites(nodes, members)
    polys = svs.panel_polys(nodes, panels)
    adj, _ = svs.panel_adjacency(panels)
    owners = svs.assign_owners(svs.panel_centroids(polys),
                               [list(p['members']) for p in panels], sites, adj)
    edges = svs.cell_boundary_edges(nodes, members, panels, owners)
    assert edges, 'no cell boundaries at all'
    assert len(edges) < len(members), 'every rod cannot be a cell boundary'
    # give every panel the same owner and the boundaries must vanish
    flat = svs.cell_boundary_edges(nodes, members, panels, [0] * len(panels))
    assert flat == []


def test_outlines_survive_a_rod_shared_by_many_panels(vault):
    """On this model 2999 panels spread over 943 rods -- about eleven panels
    per rod -- and an "exactly two panels share it" rule found no boundaries
    at all."""
    nodes, members = vault
    panels = svs.panels_of(nodes, members)
    sites = _rod_sites(nodes, members)
    polys = svs.panel_polys(nodes, panels)
    adj, _ = svs.panel_adjacency(panels)
    owners = svs.assign_owners(svs.panel_centroids(polys),
                               [list(p['members']) for p in panels], sites, adj)
    assert svs.cell_boundary_edges(nodes, members, panels, owners)


# ── the section, the one volumetric view ────────────────────────────────────

def test_the_cut_thickness_grows_with_the_module():
    small = _mesh(sg.flat_grid(span_x=12.0, span_y=12.0, depth=1.5, module=3.0))
    big = _mesh(sg.flat_grid(span_x=24.0, span_y=24.0, depth=3.0, module=6.0))
    t_small = svs.default_cut_thickness(small[0], svs.panels_of(*small))
    t_big = svs.default_cut_thickness(big[0], svs.panels_of(*big))
    assert t_big > t_small


def test_a_non_positive_cut_keeps_nothing(slab):
    nodes, members = slab
    panels = svs.panels_of(nodes, members)
    quads = svs.section_plane(nodes, 2, 0.5)
    assert quads
    for bad in (-3.0, 0.0, None):
        assert not svs.section_mask(quads, nodes, panels, bad).any()


def test_the_section_plane_moves_with_its_position(vault):
    nodes, _members = vault
    pts = np.asarray(nodes, dtype=float)
    lo, hi = pts[:, 2].min(), pts[:, 2].max()
    for pos, expect in ((0.0, lo), (0.5, (lo + hi) / 2.0), (1.0, hi)):
        quads = svs.section_plane(nodes, 2, pos)
        assert all(q[:, 2] == pytest.approx(expect) for q in quads)


def test_the_section_plane_follows_its_axis(vault):
    nodes, _members = vault
    for axis in (0, 1, 2):
        quads = svs.section_plane(nodes, axis, 0.5)
        spread = {round(float(q[:, axis].std()), 9) for q in quads}
        assert spread == {0.0}, 'the plane is not flat along its own axis'


def test_the_section_stays_inside_the_fabric(vault):
    """A cut through a vault must not fill the hollow it arches over -- the
    failure that made the old convex-hull domain draw a floor slab."""
    nodes, members = vault
    panels = svs.panels_of(nodes, members)
    sites = _rod_sites(nodes, members)
    t = svs.default_cut_thickness(nodes, panels)
    quads = svs.section_plane(nodes, 2, 0.5)
    kept = svs.build_section(nodes, panels, sites, 2, 0.5, t)
    assert kept, 'the cut found no material at all'
    assert len(kept) < len(quads), 'the cut kept the whole plane'


def test_the_tessellation_does_not_depend_on_the_camera(vault):
    """It lives in model space, which is the whole point: orbiting must not
    change one polygon of it."""
    nodes, members = vault
    _p1, _s1, first = _tessellate(nodes, members)
    _p2, _s2, again = _tessellate(nodes, members)
    assert len(first) == len(again)
    for (p, o), (q, o2) in zip(first, again):
        assert o == o2
        assert np.allclose(p, q)


def test_build_is_quick_enough_to_stay_interactive(vault):
    import time
    nodes, members = vault
    panels = svs.panels_of(nodes, members)
    sites = _rod_sites(nodes, members)
    panel_sites = [list(p['members']) for p in panels]
    t0 = time.perf_counter()
    svs.build_surface(nodes, panels, sites, panel_sites)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f'building the tessellation took {elapsed:.2f}s'
