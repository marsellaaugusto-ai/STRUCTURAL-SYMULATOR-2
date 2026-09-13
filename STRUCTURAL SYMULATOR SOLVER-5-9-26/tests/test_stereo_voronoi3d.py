"""Tests for the 3D Voronoi tessellation (apps/stereo/stereo_voronoi3d.py).

Everything here is pure geometry, so none of it builds a widget: the module
deliberately returns model-space polygons and leaves projection and colour
to the renderer, and that is what makes these assertions possible.
"""
import math

import numpy as np
import pytest

from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_voronoi3d as v3


@pytest.fixture
def grid():
    mesh = sg.flat_grid(9.0, 9.0, 1.5, 3.0)
    return mesh['nodes'], mesh['members']


@pytest.fixture
def vault():
    mesh = sg.barrel_vault(12.0, 4.0, 8.0, n_arch=7, n_bays=4, double_layer=False)
    return mesh['nodes'], mesh['members']


# ── sites and the band radius ────────────────────────────────────────────────

def test_member_midpoints_sit_halfway_along_each_rod(grid):
    nodes, members = grid
    mids = v3.member_midpoints(nodes, members)
    assert len(mids) == len(members)
    for i, m in enumerate(members):
        a, b = np.array(nodes[m['a']]), np.array(nodes[m['b']])
        assert np.allclose(mids[i], (a + b) / 2.0)


def test_member_midpoints_of_an_empty_mesh_is_empty():
    assert v3.member_midpoints([], []).shape == (0, 3)


def test_default_band_radius_scales_with_the_model(grid):
    nodes, members = grid
    small = v3.default_band_radius(nodes, members)
    big_mesh = sg.flat_grid(90.0, 90.0, 15.0, 30.0)      # same shape, 10x bigger
    big = v3.default_band_radius(big_mesh['nodes'], big_mesh['members'])
    # only to the millimetre the default is rounded to -- rounding happens
    # before the scaling, so exact proportionality is not on offer
    assert big == pytest.approx(small * 10.0, abs=0.01)


def test_default_band_radius_actually_leaves_a_band(vault):
    # the regression this guards: at half a rod length the band swallowed the
    # whole hull on flat models, so the domain toggle looked like a no-op.
    nodes, members = vault
    r = v3.default_band_radius(nodes, members)
    pts = np.asarray(nodes, float)
    eq, _simp = v3.hull_of(pts)
    patches = v3.section_patches(pts, 2, 0.5)
    centres = np.array([p.mean(axis=0) for p in patches])
    in_hull = v3.inside_hull(eq, centres, tol=1e-6)
    in_band = in_hull & v3.within_band(centres, nodes, members, r)
    frac = in_band.sum() / max(1, in_hull.sum())
    assert 0.05 < frac < 0.95, f'band keeps {frac:.0%} of the hull -- not a band'


# ── the two domains ──────────────────────────────────────────────────────────

def test_hull_of_a_degenerate_point_set_is_reported_not_raised():
    assert v3.hull_of([(0, 0, 0), (1, 0, 0), (2, 0, 0)]) is None      # collinear
    assert v3.hull_of([(0, 0, 0)]) is None


def test_inside_hull_accepts_the_centroid_and_rejects_a_far_point(grid):
    nodes, _members = grid
    pts = np.asarray(nodes, float)
    eq, _simp = v3.hull_of(pts)
    probe = np.array([pts.mean(axis=0), pts.mean(axis=0) + 1e4])
    assert list(v3.inside_hull(eq, probe)) == [True, False]


def test_distance_to_members_measures_to_the_segment_not_its_line():
    # a point beyond the end of a rod is measured from the END, which is what
    # keeps a band from stretching off into space along a rod's own direction
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1}]
    beyond = np.array([[5.0, 0.0, 0.0]])
    assert v3.distance_to_members(beyond, nodes, members)[0] == pytest.approx(4.0)
    beside = np.array([[0.5, 3.0, 0.0]])
    assert v3.distance_to_members(beside, nodes, members)[0] == pytest.approx(3.0)


def test_within_band_agrees_with_the_exact_distance(grid):
    # within_band trades exactness for speed by sampling the rods; the error
    # it is allowed is a fraction of r, so only points within a hair of the
    # boundary may disagree.
    nodes, members = grid
    pts = np.asarray(nodes, float)
    probe = np.random.default_rng(7).uniform(pts.min(0), pts.max(0), size=(3000, 3))
    r = 1.0
    exact = v3.distance_to_members(probe, nodes, members) <= r
    sampled = v3.within_band(probe, nodes, members, r)
    disagree = exact != sampled
    assert disagree.mean() < 0.01
    if disagree.any():
        off = abs(v3.distance_to_members(probe[disagree], nodes, members) - r)
        assert off.max() < r / 10.0


def test_within_band_of_nothing_is_empty(grid):
    nodes, members = grid
    assert not v3.within_band(np.zeros((4, 3)), nodes, members, 0).any()
    assert not v3.within_band(np.zeros((0, 3)), nodes, members, 1.0).any()


# ── the three views ──────────────────────────────────────────────────────────

@pytest.mark.parametrize('view', v3.VIEWS)
@pytest.mark.parametrize('domain', v3.DOMAINS)
def test_every_view_and_domain_builds_patches(grid, view, domain):
    nodes, members = grid
    sites = v3.member_midpoints(nodes, members)
    out = v3.build(nodes, members, sites, view, domain,
                   band_r=v3.default_band_radius(nodes, members))
    assert out, f'{view}/{domain} produced nothing'
    for poly, owner in out:
        assert len(poly) >= 3
        assert 0 <= owner < len(sites)


def test_patches_stay_inside_the_domain(grid):
    nodes, members = grid
    pts = np.asarray(nodes, float)
    eq, _simp = v3.hull_of(pts)
    sites = v3.member_midpoints(nodes, members)
    out = v3.build(nodes, members, sites, v3.VIEW_SECTION, v3.DOMAIN_HULL)
    centres = np.array([np.asarray(p).mean(axis=0) for p, _i in out])
    assert v3.inside_hull(eq, centres, tol=1e-6).all()


def test_the_band_keeps_fewer_patches_than_the_hull(vault):
    nodes, members = vault
    sites = v3.member_midpoints(nodes, members)
    r = v3.default_band_radius(nodes, members)
    hull = v3.build(nodes, members, sites, v3.VIEW_SECTION, v3.DOMAIN_HULL, band_r=r)
    band = v3.build(nodes, members, sites, v3.VIEW_SECTION, v3.DOMAIN_BAND, band_r=r)
    assert 0 < len(band) < len(hull)


def test_moving_the_section_plane_moves_the_patches(grid):
    nodes, members = grid
    sites = v3.member_midpoints(nodes, members)
    low = v3.build(nodes, members, sites, v3.VIEW_SECTION, v3.DOMAIN_HULL,
                   section_axis=2, section_position=0.15)
    high = v3.build(nodes, members, sites, v3.VIEW_SECTION, v3.DOMAIN_HULL,
                    section_axis=2, section_position=0.85)
    z_low = np.mean([np.asarray(p)[:, 2].mean() for p, _i in low])
    z_high = np.mean([np.asarray(p)[:, 2].mean() for p, _i in high])
    assert z_high > z_low


def test_section_axis_chooses_the_plane_normal(grid):
    nodes, members = grid
    sites = v3.member_midpoints(nodes, members)
    for axis in (0, 1, 2):
        out = v3.build(nodes, members, sites, v3.VIEW_SECTION, v3.DOMAIN_HULL,
                       section_axis=axis, section_position=0.5)
        coord = np.array([np.asarray(p)[:, axis] for p, _i in out])
        assert coord.std() == pytest.approx(0.0, abs=1e-9)   # all on one plane


def test_cells_are_closed_polyhedra_around_their_own_site(grid):
    nodes, members = grid
    sites = v3.member_midpoints(nodes, members)
    out = v3.build(nodes, members, sites, v3.VIEW_CELLS, v3.DOMAIN_HULL)
    assert out
    # every triangle of a cell must lie no nearer another site than its own
    owners = {}
    for poly, owner in out:
        owners.setdefault(owner, []).append(np.asarray(poly))
    for owner, tris in list(owners.items())[:12]:
        centre = np.vstack(tris).mean(axis=0)
        d_own = np.linalg.norm(centre - sites[owner])
        d_all = np.linalg.norm(sites - centre, axis=1)
        assert d_own <= d_all.min() + 1e-6


def test_cells_decline_past_the_interactive_limit():
    # a big model must say no rather than freeze; Skin and Section still work
    mesh = sg.flat_grid(60.0, 60.0, 1.5, 1.5)
    nodes, members = mesh['nodes'], mesh['members']
    sites = v3.member_midpoints(nodes, members)
    assert len(sites) > v3.CELLS_SITE_LIMIT
    assert v3.build(nodes, members, sites, v3.VIEW_CELLS, v3.DOMAIN_HULL) == []
    assert v3.build(nodes, members, sites, v3.VIEW_SKIN, v3.DOMAIN_HULL)


def test_build_returns_nothing_when_there_is_nothing_to_tessellate(grid):
    nodes, members = grid
    assert v3.build(nodes, members, np.zeros((1, 3)), v3.VIEW_SKIN, v3.DOMAIN_HULL) == []
    assert v3.build([(0, 0, 0)], [], np.zeros((4, 3)), v3.VIEW_SKIN, v3.DOMAIN_HULL) == []


def test_the_tessellation_does_not_depend_on_the_camera(grid):
    # the whole point of moving it off the screen: nothing here takes a view
    # angle, so the result cannot change when the model is orbited.
    nodes, members = grid
    sites = v3.member_midpoints(nodes, members)
    a = v3.build(nodes, members, sites, v3.VIEW_SKIN, v3.DOMAIN_HULL)
    b = v3.build(nodes, members, sites, v3.VIEW_SKIN, v3.DOMAIN_HULL)
    assert len(a) == len(b)
    assert [i for _p, i in a] == [i for _p, i in b]
