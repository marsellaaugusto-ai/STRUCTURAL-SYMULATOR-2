"""Linear selection (stereo_select): the nodes and rods a node-to-node line
picks."""
from apps.stereo import stereo_select as ssel


def _ladder():
    """Two rows of 4 nodes, 1 m apart: chords along each row, rungs across,
    and one diagonal per bay."""
    nodes = [(float(i), 0.0, 0.0) for i in range(4)] + \
            [(float(i), 1.0, 0.0) for i in range(4)]
    members = []
    for r in (0, 4):
        for i in range(3):
            members.append({'a': r + i, 'b': r + i + 1})      # chords 0-5
    for i in range(4):
        members.append({'a': i, 'b': 4 + i})                  # rungs 6-9
    for i in range(3):
        members.append({'a': i, 'b': 4 + i + 1})              # diagonals 10-12
    return nodes, members


def test_a_line_along_a_row_takes_its_nodes_and_its_chords_only():
    nodes, members = _ladder()
    picked, rods = ssel.line_selection(nodes, members, 0, 3, 0.3)
    assert picked == [0, 1, 2, 3]
    assert rods == [0, 1, 2]


def test_a_partial_line_takes_only_what_it_spans():
    nodes, members = _ladder()
    picked, rods = ssel.line_selection(nodes, members, 1, 3, 0.3)
    assert picked == [1, 2, 3] and rods == [1, 2]


def test_a_diagonal_line_takes_the_diagonal_rod():
    nodes, members = _ladder()
    picked, rods = ssel.line_selection(nodes, members, 0, 5, 0.1)
    assert picked == [0, 5] and rods == [10]


def test_the_crossing_option_adds_the_rods_the_drawn_line_passes_through():
    nodes, members = _ladder()
    screen = [(x * 100.0, y * 100.0) for x, y, _z in nodes]
    # a line from node 0 to node 7 crosses the rungs and diagonals between
    picked, rods = ssel.line_selection(nodes, members, 0, 7, 0.05,
                                       screen=screen, crossing=True)
    assert picked == [0, 7]
    assert set(rods) >= {7, 8}            # the middle rungs, crossed inside
    assert 6 not in rods and 9 not in rods, 'touching at an end is no crossing'


def test_a_touch_at_an_end_is_not_a_crossing():
    assert not ssel.segments_cross((0, 0), (1, 0), (1, 0), (1, 1))
    assert ssel.segments_cross((0, 0), (2, 0), (1, -1), (1, 1))
    assert not ssel.segments_cross((0, 0), (2, 0), (1, 0), (3, 0))
