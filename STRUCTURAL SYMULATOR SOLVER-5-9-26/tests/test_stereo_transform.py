"""Rotate and mirror a selection (roadmap v2 3.4): the geometry."""
import math

import pytest

from apps.stereo import stereo_transform as st


def _close(p, q, tol=1e-9):
    return all(abs(p[k] - q[k]) <= tol for k in range(3))


def test_a_quarter_turn_about_z_takes_x_to_y():
    assert _close(st.rotate_point((1, 0, 0), 'Z', 90, (0, 0, 0)), (0, 1, 0))
    assert _close(st.rotate_point((0, 1, 0), 'X', 90, (0, 0, 0)), (0, 0, 1))
    assert _close(st.rotate_point((0, 0, 1), 'Y', 90, (0, 0, 0)), (1, 0, 0))


def test_rotation_keeps_lengths_and_the_axis_coordinate():
    p, pivot = (3.0, -2.0, 5.0), (1.0, 1.0, 1.0)
    q = st.rotate_point(p, 'Z', 37.0, pivot)
    assert q[2] == p[2]
    assert math.dist(p[:2], pivot[:2]) == pytest.approx(math.dist(q[:2], pivot[:2]))


def test_a_selection_turns_about_its_own_middle_not_the_origin():
    nodes = [(10.0, 0.0, 0.0), (12.0, 0.0, 0.0), (99.0, 99.0, 99.0)]
    out = st.rotated(nodes, [0, 1], 'Z', 90)
    assert _close(out[0], (11.0, -1.0, 0.0)) and _close(out[1], (11.0, 1.0, 0.0))
    assert out[2] == nodes[2], 'nodes outside the selection do not move'


def test_mirroring_twice_is_where_you_started():
    nodes = [(1.0, 2.0, 3.0), (4.0, 5.0, 7.0)]
    once = st.mirrored(nodes, [0, 1], 'X')
    assert _close(once[0], (4.0, 2.0, 3.0)) and _close(once[1], (1.0, 5.0, 7.0))
    assert all(_close(a, b) for a, b in
               zip(st.mirrored(once, [0, 1], 'X'), nodes))


def test_a_mirrored_copy_merges_the_nodes_on_the_plane():
    # a half-frame: 0 on the mirror plane x = 0, 1 and 2 to its right
    nodes = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 0.0, 1.0)]
    members = [{'a': 0, 'b': 1, 'A': 5.0}, {'a': 1, 'b': 2, 'A': 5.0},
               {'a': 0, 'b': 2, 'A': 7.0}]
    out_n, out_m, node_map, new = st.mirror_copy(nodes, members, [0, 1, 2],
                                                 'X', pivot=(0.0, 0.0, 0.0))
    assert node_map[0] == 0, 'on the plane: copied onto itself'
    assert len(out_n) == 5
    assert _close(out_n[node_map[1]], (-2.0, 0.0, 0.0))
    assert len(new) == 3
    assert {frozenset((m['a'], m['b'])) for m in out_m[3:]} == \
        {frozenset((0, node_map[1])), frozenset((node_map[1], node_map[2])),
         frozenset((0, node_map[2]))}
    assert out_m[5]['A'] == 7.0, 'the copy keeps the section'


def test_a_copy_that_would_duplicate_a_rod_is_skipped():
    # symmetric already: mirroring adds nothing new
    nodes = [(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1}]
    out_n, out_m, node_map, new = st.mirror_copy(nodes, members, [0, 1], 'X')
    assert node_map == {0: 1, 1: 0}
    assert len(out_n) == 2 and new == []


def test_only_rods_among_the_copied_nodes_are_copied():
    nodes = [(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (5.0, 5.0, 0.0)]
    members = [{'a': 0, 'b': 1}, {'a': 1, 'b': 2}]
    _n, out_m, node_map, new = st.mirror_copy(nodes, members, [0, 1], 'Y',
                                              pivot=(0.0, -1.0, 0.0))
    assert len(new) == 1
    assert {out_m[new[0]]['a'], out_m[new[0]]['b']} == {node_map[0], node_map[1]}
