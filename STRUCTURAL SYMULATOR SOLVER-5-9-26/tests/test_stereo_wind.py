"""Simplified wind (roadmap v2 4.6, option 1), against hand results."""
import math

import pytest

from apps.stereo import stereo_wind as sw


def test_the_direction_convention():
    assert sw.wind_direction(0) == pytest.approx((1.0, 0.0, 0.0))
    assert sw.wind_direction(90) == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)
    assert sw.wind_direction(0, 90) == pytest.approx((0.0, 0.0, 1.0), abs=1e-12)


def _wall(tilt_deg):
    """A 2 m x 2 m plane, 3 x 3 nodes, tilted `tilt_deg` from horizontal
    about the y axis; every node carries a quarter-cell share of 4 m2."""
    nodes, idx = [], {}
    t = math.radians(tilt_deg)
    for i in range(3):
        for j in range(3):
            u, v = i * 1.0, j * 1.0
            idx[i, j] = len(nodes)
            nodes.append((u * math.cos(t), v, u * math.sin(t)))
    members = []
    for i in range(3):
        for j in range(3):
            if i < 2:
                members.append({'a': idx[i, j], 'b': idx[i + 1, j]})
            if j < 2:
                members.append({'a': idx[i, j], 'b': idx[i, j + 1]})
    w = {(0, 0): .25, (2, 0): .25, (0, 2): .25, (2, 2): .25,
         (1, 0): .5, (1, 2): .5, (0, 1): .5, (2, 1): .5, (1, 1): 1.0}
    load_nodes = {idx[k]: a for k, a in w.items()}
    return nodes, members, load_nodes


def test_a_flat_roof_under_a_level_wind_catches_nothing():
    nodes, members, ln = _wall(0)
    loads = sw.wind_loads(nodes, members, ln, 1.0, 0.0)
    assert sw.total(loads) == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)


def test_a_wall_square_to_the_wind_catches_q_times_its_area():
    nodes, members, ln = _wall(90)          # vertical wall facing +X
    loads = sw.wind_loads(nodes, members, ln, 0.8, 0.0)
    fx, fy, fz = sw.total(loads)
    assert fx == pytest.approx(0.8 * 4.0)
    assert fy == pytest.approx(0.0, abs=1e-9) and fz == pytest.approx(0.0, abs=1e-9)


def test_a_slope_catches_its_area_turned_by_the_slope():
    nodes, members, ln = _wall(30)
    loads = sw.wind_loads(nodes, members, ln, 1.0, 0.0)
    # the tributary areas are on the slope; the wind sees them times sin 30
    assert sw.total(loads)[0] == pytest.approx(4.0 * math.sin(math.radians(30)))


def test_the_force_is_along_the_wind():
    nodes, members, ln = _wall(90)
    loads = sw.wind_loads(nodes, members, ln, 1.0, 30.0)
    fx, fy, _fz = sw.total(loads)
    assert math.degrees(math.atan2(fy, fx)) == pytest.approx(30.0)
    # a wall facing +X seen 30 degrees off square shows cos 30 of itself
    assert math.hypot(fx, fy) == pytest.approx(4.0 * math.cos(math.radians(30)))


def test_an_open_rod_square_to_the_wind_takes_q_L_b():
    nodes = [(0.0, 0.0, 0.0), (0.0, 0.0, 3.0)]
    m = {'a': 0, 'b': 1, 'c_cm': 3.805}         # a CHS 76.1, b = 76.1 mm
    loads = sw.wind_loads(nodes, [m], {}, 1.0, 0.0, mode='open')
    assert sw.total(loads)[0] == pytest.approx(1.0 * 3.0 * 0.0761)
    assert [ld['fx'] for ld in loads] == pytest.approx([0.11415, 0.11415])


def test_an_open_rod_along_the_wind_takes_nothing():
    nodes = [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0)]
    loads = sw.wind_loads(nodes, [{'a': 0, 'b': 1, 'c_cm': 3.8}], {}, 1.0,
                          0.0, mode='open')
    assert loads == []


def test_a_hand_typed_rod_uses_the_round_tube_width():
    m = {'A': 8.2, 'I': 54.0}
    assert sw.member_width_m(m) == pytest.approx(
        2 * math.sqrt(2 * 54.0 / 8.2) / 100.0)
