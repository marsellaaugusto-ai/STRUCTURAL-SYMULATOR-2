"""The shell drawn as a solid: geometry, checked against numbers.

The point of these tests is that "does the thickness show?" is answerable
without looking at a screen. A flat plate's solid has exactly the volume
area x t; the offset is exactly t/2 along the normal; the band round the
edge has exactly one face per free edge. Each of those is a number.
"""
import math
import sys
import os

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.shell import shell_solid as ss


def flat_grid(nx=4, ny=3, w=4.0, h=3.0, z=0.0):
    xs = np.linspace(0.0, w, nx + 1)
    ys = np.linspace(0.0, h, ny + 1)
    XX, YY = np.meshgrid(xs, ys)
    X = np.stack([XX.ravel(), YY.ravel(), np.full(XX.size, z)], axis=1)
    ids = np.arange(len(X)).reshape(ny + 1, nx + 1)
    elems = np.stack([ids[:-1, :-1], ids[:-1, 1:], ids[1:, 1:], ids[1:, :-1]],
                     -1).reshape(-1, 4)
    return X, elems


def dome(n=8, R=10.0, half_angle=0.5):
    """A spherical cap meshed on a square parameter patch."""
    u = np.linspace(-half_angle, half_angle, n + 1)
    UU, VV = np.meshgrid(u, u)
    X = np.stack([R * np.sin(UU.ravel()), R * np.sin(VV.ravel()),
                  R * np.cos(UU.ravel()) * np.cos(VV.ravel())], axis=1)
    ids = np.arange(len(X)).reshape(n + 1, n + 1)
    elems = np.stack([ids[:-1, :-1], ids[:-1, 1:], ids[1:, 1:], ids[1:, :-1]],
                     -1).reshape(-1, 4)
    return X, elems


# ── the flat case, where every answer is known exactly ──────────────────────

def test_a_flat_plate_has_vertical_normals():
    X, el = flat_grid()
    n = ss.node_normals(X, el)
    assert np.allclose(np.abs(n[:, 2]), 1.0)
    assert np.allclose(n[:, :2], 0.0, atol=1e-12)


def test_the_offset_is_exactly_half_the_thickness():
    X, el = flat_grid()
    t = np.full(len(el), 0.20)
    top, bot = ss.offset_surfaces(X, el, t)
    assert np.allclose(top[:, 2] - X[:, 2], 0.10)
    assert np.allclose(X[:, 2] - bot[:, 2], 0.10)
    assert np.allclose(top[:, :2], X[:, :2])          # no drift in plan


def test_exaggeration_scales_the_offset_and_nothing_else():
    X, el = flat_grid()
    t = np.full(len(el), 0.20)
    top1, bot1 = ss.offset_surfaces(X, el, t, 1.0)
    top5, bot5 = ss.offset_surfaces(X, el, t, 5.0)
    assert np.allclose(top5[:, 2] - X[:, 2], 5.0 * (top1[:, 2] - X[:, 2]))
    assert np.allclose(top5[:, :2], top1[:, :2])
    faces = ss.solid_faces(X, el, t, 5.0)
    assert faces['exaggeration'] == 5.0


def test_the_solid_of_a_flat_plate_has_the_volume_area_times_t():
    X, el = flat_grid(w=4.0, h=3.0)
    t = np.full(len(el), 0.15)
    assert ss.solid_volume(X, el, t) == pytest.approx(4.0 * 3.0 * 0.15, rel=1e-12)


def test_a_varying_thickness_is_integrated_element_by_element():
    X, el = flat_grid(nx=2, ny=1, w=2.0, h=1.0)      # two 1 x 1 m elements
    t = np.array([0.10, 0.30])
    assert ss.solid_volume(X, el, t) == pytest.approx(0.10 + 0.30, rel=1e-12)


# ── the band round the edge ────────────────────────────────────────────────

def test_the_boundary_is_every_edge_with_one_element_behind_it():
    X, el = flat_grid(nx=4, ny=3)
    edges = ss.boundary_edges(el)
    assert len(edges) == 2 * 4 + 2 * 3            # the perimeter of the grid
    interior = {(min(a, b), max(a, b)) for a, b, _ in edges}
    assert len(interior) == len(edges)            # no edge counted twice


def test_a_hole_in_the_mesh_is_boundary_too():
    """The plan rule will cut elements out one day; the band has to follow."""
    X, el = flat_grid(nx=3, ny=3)
    keep = [i for i in range(len(el)) if i != 4]   # drop the middle element
    edges = ss.boundary_edges(el[keep])
    assert len(edges) == 12 + 4                   # outside, plus the hole


def test_every_face_carries_its_element_and_its_role():
    X, el = flat_grid(nx=4, ny=3)
    t = np.full(len(el), 0.2)
    f = ss.solid_faces(X, el, t)
    n_side = len(ss.boundary_edges(el))
    assert len(f['poly']) == 2 * len(el) + n_side
    assert (f['role'] == ss.TOP).sum() == len(el)
    assert (f['role'] == ss.BOTTOM).sum() == len(el)
    assert (f['role'] == ss.SIDE).sum() == n_side
    assert f['elem'].max() < len(el) and f['elem'].min() >= 0


def test_a_side_face_is_exactly_as_tall_as_the_shell_is_thick():
    X, el = flat_grid(nx=2, ny=2)
    t = np.full(len(el), 0.25)
    f = ss.solid_faces(X, el, t)
    sides = f['poly'][f['role'] == ss.SIDE]
    # corners 0,1 are on the top surface and 2,3 below them on the soffit
    rise = sides[:, 0, 2] - sides[:, 3, 2]
    assert np.allclose(rise, 0.25)


# ── orientation, which is what makes the painter's algorithm work ──────────

def test_the_top_points_up_the_soffit_points_down():
    X, el = flat_grid()
    f = ss.solid_faces(X, el, np.full(len(el), 0.2))
    assert np.all(f['normal'][f['role'] == ss.TOP][:, 2] > 0.99)
    assert np.all(f['normal'][f['role'] == ss.BOTTOM][:, 2] < -0.99)


def test_side_normals_point_away_from_the_shell():
    X, el = flat_grid(nx=4, ny=4, w=4.0, h=4.0)
    f = ss.solid_faces(X, el, np.full(len(el), 0.2))
    sides = f['role'] == ss.SIDE
    mid = X.mean(axis=0)
    out = f['poly'][sides].mean(axis=1) - mid
    out[:, 2] = 0.0
    out /= np.linalg.norm(out, axis=1, keepdims=True)
    assert np.all(np.sum(f['normal'][sides] * out, axis=1) > 0.5)


def test_the_top_of_a_dome_is_offset_outwards_not_upwards():
    """On a curved shell the offset follows the surface, so a point on the
    flank moves sideways as well as up -- which is the whole difference
    between a slab and a sheet drawn thick."""
    X, el = dome()
    t = np.full(len(el), 0.4)
    top, bot = ss.offset_surfaces(X, el, t)
    R = np.linalg.norm(X, axis=1)
    Rtop = np.linalg.norm(top, axis=1)
    Rbot = np.linalg.norm(bot, axis=1)
    assert np.all(Rtop > R) and np.all(Rbot < R)
    # and the offset is t/2 along the radius, to within the mesh's own
    # discretisation of the normal
    assert np.allclose(Rtop - R, 0.2, atol=0.01)
    flank = np.argmax(np.abs(X[:, 0]))
    assert abs(top[flank, 0] - X[flank, 0]) > 1e-3


def test_the_thickness_is_carried_to_the_nodes_as_a_ramp_not_a_cliff():
    X, el = flat_grid(nx=2, ny=1, w=2.0, h=1.0)
    t = np.array([0.10, 0.30])
    tn = ss.node_thickness(X, el, t)
    on_thin = np.isclose(X[:, 0], 0.0)
    on_thick = np.isclose(X[:, 0], 2.0)
    shared = np.isclose(X[:, 0], 1.0)
    assert np.allclose(tn[on_thin], 0.10)
    assert np.allclose(tn[on_thick], 0.30)
    assert np.allclose(tn[shared], 0.20)          # the taper, at the join


# ── the honesty check ──────────────────────────────────────────────────────

def test_inward_limit_reports_a_shell_too_thick_for_its_own_curvature():
    X, el = dome(R=10.0)
    r_min, half = ss.inward_limit(X, el, np.full(len(el), 0.4))
    assert r_min == pytest.approx(10.0, rel=0.05)   # it found the radius
    assert half == 0.2
    assert half < r_min                             # 40 cm on a 10 m dome: fine
    _r, half_fat = ss.inward_limit(X, el, np.full(len(el), 44.0))
    assert half_fat > r_min                         # 22 m half-thickness: not


def test_an_empty_mesh_does_not_raise():
    X = np.zeros((0, 3))
    el = np.zeros((0, 4), int)
    f = ss.solid_faces(X, el, np.zeros(0))
    assert len(f['poly']) == 0
    assert ss.solid_volume(X, el, np.zeros(0)) == 0.0
