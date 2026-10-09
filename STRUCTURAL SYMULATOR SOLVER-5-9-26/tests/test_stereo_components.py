"""Components: one part, built more than once.

The claim a component makes is not "these groups look alike" -- it is
"these groups are one drawing, so the section has to carry the worst of
them". Most of this file is about that consequence, and about the
correspondence it rests on: which rod of this copy is which rod of that
one, when the copy has been moved, turned, or mirrored.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from apps.stereo import stereo_components as sc
from apps.stereo import stereo_groups as sgp
from apps.stereo import stereo_marks as sm


CHIRAL = [(0, 0, 0), (4, 0, 0), (1.7, 3.1, 0), (1.3, 0.9, 2.8),
          (3.4, 2.2, 4.1)]
BARS = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3), (3, 4), (1, 4)]


def rotation(axis, degrees):
    x, y, z = axis
    n = math.sqrt(x * x + y * y + z * z)
    x, y, z = x / n, y / n, z / n
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
            [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
            [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]]


def place(pts, matrix=None, offset=(0, 0, 0), mirror=False):
    out = []
    for p in pts:
        q = (p[0], p[1], -p[2]) if mirror else p
        if matrix:
            q = tuple(sum(matrix[i][j] * q[j] for j in range(3))
                      for i in range(3))
        out.append(tuple(q[i] + offset[i] for i in range(3)))
    return out


def model(copies=(None, None, None), shuffle=False):
    """A model of several copies of one truss. Each entry of `copies` is
    (matrix, offset, mirror) or None for 'as drawn, 30 m further along'."""
    import random
    nodes, members, groups = [], [], []
    rnd = random.Random(5)
    for k, how in enumerate(copies):
        matrix, offset, mirror = how or (None, (30 * k, 0, 0), False)
        at = len(nodes)
        nodes.extend(place(CHIRAL, matrix, offset, mirror))
        bar_list = list(BARS)
        if shuffle:
            rnd.shuffle(bar_list)
        first = len(members)
        for a, b in bar_list:
            members.append({'a': a + at, 'b': b + at, 'profile': 'IPE 200',
                            'A': 28.5, 'I': 1940.0, 'conn': 'pin',
                            'E': 200.0, 'Fy': 235.0, 'Fu': 360.0})
        groups.append({'id': k + 1, 'name': 'Truss %s' % 'ABCDE'[k],
                       'parent': None,
                       'members': set(range(first, len(members)))})
    return nodes, members, groups


def rod_len(nodes, m):
    return sm.rod_length(nodes, m)


# ── making one, and taking one apart ─────────────────────────────────────

def test_a_fresh_group_is_not_a_component():
    _n, _m, groups = model()
    assert sc.name_of(groups[0]) is None
    assert sc.copies(groups, 1) == 1
    assert sc.siblings(groups, 1) == []
    assert sc.components(groups) == {}


def test_making_a_component_names_the_groups_that_share_it():
    _n, _m, groups = model()
    name = sc.make_component(groups, [1, 2, 3], 'Gable truss')
    assert name == 'Gable truss'
    assert sc.copies(groups, 1) == 3
    assert [g['id'] for g in sc.instances_of(groups, name)] == [1, 2, 3]
    assert [g['id'] for g in sc.siblings(groups, 2)] == [1, 3]


def test_a_component_with_no_name_gets_a_free_one():
    _n, _m, groups = model()
    first = sc.make_component(groups, [1, 2])
    second = sc.make_component(groups, [3], None)
    assert first != second
    assert set(sc.components(groups)) == {first, second}


def test_a_branch_of_the_tree_cannot_be_a_part():
    """A group that holds only subgroups is not a thing anyone fabricates,
    and letting it in would make "the copies of this part" ambiguous."""
    _n, _m, groups = model()
    groups.append({'id': 9, 'name': 'Roof', 'parent': None, 'members': set()})
    with pytest.raises(ValueError, match='branch of the tree'):
        sc.make_component(groups, [1, 9])
    assert sc.name_of(groups[0]) is None, 'nothing changed'


def test_make_unique_detaches_one_copy_and_leaves_the_rest():
    _n, _m, groups = model()
    sc.make_component(groups, [1, 2, 3], 'T')
    was = sc.make_unique(groups, 2)
    assert was == 'T'
    assert sc.copies(groups, 2) == 1
    assert sc.name_of(groups[1]) is None
    assert [g['id'] for g in sc.instances_of(groups, 'T')] == [1, 3]
    assert len(groups[1]['members']) == len(BARS), 'it keeps its rods'


def test_make_unique_on_a_plain_group_is_harmless():
    _n, _m, groups = model()
    assert sc.make_unique(groups, 1) is None


def test_exploding_a_component_keeps_every_group():
    _n, _m, groups = model()
    sc.make_component(groups, [1, 2, 3], 'T')
    assert sc.explode_component(groups, 'T') == 3
    assert sc.components(groups) == {}
    assert len(groups) == 3
    assert all(g['members'] for g in groups)


def test_an_unknown_group_is_refused():
    _n, _m, groups = model()
    with pytest.raises(ValueError):
        sc.make_component(groups, [1, 77])
    with pytest.raises(ValueError):
        sc.make_unique(groups, 77)


# ── finding the copies ───────────────────────────────────────────────────

def test_it_finds_the_other_copies_wherever_they_sit():
    """What "Make component" offers: point at one truss, and it finds the
    ones someone drew separately and never connected in any way."""
    nodes, members, groups = model((
        None,
        (rotation((0.2, 0.7, -0.4), 61), (30, 5, 0), False),
        (None, (60, 0, 0), False)))
    found = sc.matching_groups(nodes, members, groups, 1)
    assert sorted(g['id'] for g in found) == [2, 3]


def test_it_finds_mirrored_copies_too():
    nodes, members, groups = model((
        None, (None, (30, 0, 0), True), (None, (60, 0, 0), False)))
    found = sc.matching_groups(nodes, members, groups, 1)
    assert sorted(g['id'] for g in found) == [2, 3]


def test_a_truss_that_is_not_the_same_shape_is_not_offered():
    nodes, members, groups = model()
    moved = sorted(groups[2]['members'])[0]
    node = members[moved]['b']
    x, y, z = nodes[node]
    nodes[node] = (x, y, z + 0.5)
    found = sc.matching_groups(nodes, members, groups, 1)
    assert [g['id'] for g in found] == [2]


# ── which rod is which ───────────────────────────────────────────────────

def test_the_correspondence_lines_up_rod_for_rod():
    """Even when a copy is turned in space and its bars were written down
    in a different order -- which is what a model built by copy-paste and
    then edited actually looks like."""
    nodes, members, groups = model((
        None, (rotation((0.2, 0.7, -0.4), 61), (30, 5, 0), False)),
        shuffle=True)
    sc.make_component(groups, [1, 2], 'T')
    rows = sc.correspondence(nodes, members, groups, 'T')
    assert len(rows) == len(BARS)
    assert all(len(r) == 2 for r in rows)
    for a, b in rows:
        assert rod_len(nodes, members[a]) == pytest.approx(
            rod_len(nodes, members[b]))
    assert sorted(r[0] for r in rows) == sorted(groups[0]['members'])
    assert sorted(r[1] for r in rows) == sorted(groups[1]['members'])


def test_a_mirrored_copy_still_lines_up():
    """A left-hand truss is the same drawing read the other way round, so
    its bottom chord is still the bottom chord."""
    nodes, members, groups = model((None, (None, (30, 0, 0), True)))
    sc.make_component(groups, [1, 2], 'T')
    rows = sc.correspondence(nodes, members, groups, 'T')
    assert len(rows) == len(BARS)
    for a, b in rows:
        assert rod_len(nodes, members[a]) == pytest.approx(
            rod_len(nodes, members[b]))


def test_a_copy_that_no_longer_matches_is_left_out_not_lined_up_wrongly():
    nodes, members, groups = model()
    sc.make_component(groups, [1, 2, 3], 'T')
    node = members[sorted(groups[2]['members'])[0]]['b']
    x, y, z = nodes[node]
    nodes[node] = (x, y, z + 0.5)
    rows = sc.correspondence(nodes, members, groups, 'T')
    assert all(len(r) == 2 for r in rows), 'the two that still agree'
    strayed = groups[2]['members']
    assert not any(set(r) & strayed for r in rows)


def test_matching_rods_grows_a_selection_to_every_copy():
    """The set a section edit really lands on."""
    nodes, members, groups = model()
    sc.make_component(groups, [1, 2, 3], 'T')
    one = sorted(groups[0]['members'])[0]
    reached = sc.matching_rods(nodes, members, groups, [one])
    assert len(reached) == 3
    assert one in reached
    assert len({sgp.owner_of_rod(groups)[i] for i in reached}) == 3


def test_matching_rods_leaves_a_rod_in_no_component_alone():
    nodes, members, groups = model()
    sc.make_component(groups, [1, 2], 'T')
    loose = sorted(groups[2]['members'])[0]
    assert sc.matching_rods(nodes, members, groups, [loose]) == [loose]


def test_matching_rods_is_always_safe_to_use_in_place_of_the_selection():
    nodes, members, groups = model()
    picked = [0, 1, 9]
    assert set(picked) <= set(sc.matching_rods(nodes, members, groups, picked))


# ── divergence is reported, never repaired ───────────────────────────────

def test_verify_says_when_a_copy_has_been_edited_away():
    nodes, members, groups = model()
    sc.make_component(groups, [1, 2, 3], 'T')
    node = members[sorted(groups[2]['members'])[0]]['b']
    x, y, z = nodes[node]
    nodes[node] = (x, y, z + 0.5)
    report = sc.verify(nodes, members, groups, 'T')
    assert report['instances'] == 3
    assert [g['id'] for g in report['agree']] == [1, 2]
    assert [g['id'] for g in report['differ']] == [3]


def test_verify_does_not_repair_anything():
    nodes, members, groups = model()
    sc.make_component(groups, [1, 2, 3], 'T')
    node = members[sorted(groups[2]['members'])[0]]['b']
    nodes[node] = (99, 99, 99)
    sc.verify(nodes, members, groups, 'T')
    assert sc.copies(groups, 3) == 3, 'still declared a copy; a decision'


def test_verify_counts_a_mirrored_copy_as_agreeing():
    nodes, members, groups = model((None, (None, (30, 0, 0), True)))
    sc.make_component(groups, [1, 2], 'T')
    report = sc.verify(nodes, members, groups, 'T')
    assert len(report['agree']) == 2
    assert [g['id'] for g in report['mirrored']] == [2]
    assert report['differ'] == []


def test_the_shape_most_copies_agree_on_is_the_part():
    """Two that match and one that does not: the odd one diverged, not the
    pair."""
    nodes, members, groups = model()
    sc.make_component(groups, [1, 2, 3], 'T')
    node = members[sorted(groups[0]['members'])[0]]['b']
    x, y, z = nodes[node]
    nodes[node] = (x, y, z + 0.5)
    report = sc.verify(nodes, members, groups, 'T')
    assert [g['id'] for g in report['differ']] == [1]


# ── sized for the worst copy ─────────────────────────────────────────────

def checks_for(members, utils):
    return [{'util': u, 'checked': True} for u in utils]


def test_the_envelope_takes_the_worst_copy_of_each_rod():
    nodes, members, groups = model()
    sc.make_component(groups, [1, 2, 3], 'T')
    utils = [0.1] * len(members)
    rows = sc.correspondence(nodes, members, groups, 'T')
    # Make the SECOND copy of the first position the heavily loaded one.
    utils[rows[0][1]] = 0.95
    env = sc.envelope(nodes, members, groups, 'T', checks_for(members, utils))
    first = [r for r in env if r['position'] == 0][0]
    assert first['worst_util'] == 0.95
    assert first['worst_rod'] == rows[0][1]
    assert first['spread'] == pytest.approx(0.85)


def test_the_governing_rods_are_the_worst_copy_of_each_position():
    nodes, members, groups = model()
    sc.make_component(groups, [1, 2, 3], 'T')
    rows = sc.correspondence(nodes, members, groups, 'T')
    utils = [0.1] * len(members)
    for k, row in enumerate(rows):
        utils[row[k % 3]] = 0.9                  # a different copy each time
    gov = sc.governing(nodes, members, groups, 'T',
                       checks_for(members, utils))
    assert gov == [row[k % 3] for k, row in enumerate(rows)]
    assert len({sgp.owner_of_rod(groups)[i] for i in gov}) == 3, \
        'the part is sized from several copies, not from one'


def test_the_envelope_works_before_anything_is_analysed():
    nodes, members, groups = model()
    sc.make_component(groups, [1, 2], 'T')
    env = sc.envelope(nodes, members, groups, 'T', checks=None)
    assert len(env) == len(BARS)
    assert all(r['worst_util'] is None for r in env)
    assert all(len(r['rods']) == 2 for r in env)
    assert all(r['length_m'] > 0 for r in env)


def test_the_spread_says_how_wrong_sizing_from_one_copy_would_be():
    """The number that makes the mistake visible: every copy looks right,
    and the one at the gable is carrying three times the load."""
    nodes, members, groups = model()
    sc.make_component(groups, [1, 2, 3], 'T')
    rows = sc.correspondence(nodes, members, groups, 'T')
    utils = [0.3] * len(members)
    utils[rows[2][2]] = 1.4
    env = sc.envelope(nodes, members, groups, 'T',
                      checks_for(members, utils))
    worst = max(env, key=lambda r: r['spread'])
    assert worst['position'] == 2
    assert worst['worst_util'] == 1.4
    assert worst['best_util'] == 0.3


# ── saying so before the edit ────────────────────────────────────────────

def test_a_plain_group_gets_no_warning():
    """Precisely the difference the user is choosing between."""
    _n, _m, groups = model()
    assert sc.section_warning(groups, 1) == ''
    assert sc.shape_warning(groups, 1) == ''


def test_a_section_edit_says_it_reaches_every_copy():
    _n, _m, groups = model()
    sc.make_component(groups, [1, 2, 3], 'Gable truss')
    text = sc.section_warning(groups, 1)
    assert 'built 3 times' in text
    assert 'Gable truss' in text
    assert 'worst of them' in text


def test_a_shape_edit_says_the_opposite_because_that_is_the_truth():
    """Sections are shared -- one drawing, one order. Geometry is not: each
    copy is its own rods. Saying "this changes 3 copies" here would be the
    comfortable lie; the useful warning is that nothing follows and the
    part splits."""
    _n, _m, groups = model()
    sc.make_component(groups, [1, 2, 3], 'Gable truss')
    text = sc.shape_warning(groups, 1)
    assert 'does NOT change the others' in text
    assert 'becomes two parts' in text
    assert 'Make unique' in text
