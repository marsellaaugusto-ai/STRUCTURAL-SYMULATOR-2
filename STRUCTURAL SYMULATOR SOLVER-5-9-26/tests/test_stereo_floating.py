"""Floating pieces and pick rules (stereo_floating), without Tk."""
from apps.stereo import stereo_floating as sf


def _box(x0=0.0):
    """Two squares one above the other, joined: a little 3D frame."""
    nodes = []
    for z in (0.0, 1.0):
        for x, y in ((0, 0), (4, 0), (4, 2), (0, 2)):
            nodes.append((x0 + x, y, z))
    rods = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7), (0, 5), (2, 7)]
    return nodes, [{'a': a, 'b': b} for a, b in rods]


def test_a_piece_with_no_support_floats():
    n1, m1 = _box()
    n2, m2 = _box(10.0)
    k = len(n1)
    nodes = n1 + n2
    members = m1 + [{'a': m['a'] + k, 'b': m['b'] + k} for m in m2]
    supports = [{'node': 0, 'type': 'pin'}]
    fl = sf.floating_pieces(members, supports)
    assert fl == [list(range(len(m1), len(members)))]
    # left out, it no longer counts
    assert sf.floating_pieces(members, supports, skip=fl[0]) == []
    # crane slings do not join pieces
    members.append({'a': 1, 'b': k + 1, 'role': 'crane_cable'})
    assert sf.floating_pieces(members, supports) == fl
    assert sf.lowest_nodes(nodes, members, fl[0]) == [k, k + 1, k + 2, k + 3]


def test_the_pick_rules_on_a_box():
    nodes, members = _box()
    rods = range(len(members))
    assert sf.pick_nodes(nodes, members, rods, 'corners') == [4, 5, 6, 7]
    assert len(sf.pick_nodes(nodes, members, rods, 'corners_mid')) == 4
    ch = sf.pick_nodes(nodes, members, rods, 'chords')
    assert set(ch) <= {4, 5, 6, 7} and len(ch) == 4
