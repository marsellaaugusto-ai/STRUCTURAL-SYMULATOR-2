"""Piece marks: which rods and which groups are the same thing.

The hard part is the assembly signature, and what it has to survive: the
same truss moved, turned any way in space, and -- separately -- its mirror
image, which is a DIFFERENT piece of steel and has to be told apart. Most
of this file is that, because getting it wrong in the merging direction
sends the wrong steel to site.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from apps.stereo import stereo_marks as sm


# ── fixtures: a little truss, and ways of moving it ──────────────────────

def bars(pairs, profile='IPE200', **kw):
    out = []
    for a, b in pairs:
        m = {'a': a, 'b': b, 'profile': profile, 'A': 28.5, 'I': 1940.0,
             'conn': 'pin', 'Fy': 235.0, 'Fu': 360.0, 'E': 200.0}
        m.update(kw)
        out.append(m)
    return out


# Flat and asymmetric: a real truss shape. Being flat, it is its own mirror.
FLAT_PTS = [(0, 0, 0), (3, 0, 0), (6, 0, 0), (1.5, 0, 1.2), (4.5, 0, 1.7)]
FLAT_BARS = [(0, 1), (1, 2), (0, 3), (3, 1), (1, 4), (4, 2), (3, 4)]

# Genuinely three-dimensional, and chiral: no rotation maps it onto its
# mirror image. This is the shape that can tell a left hand from a right.
CHIRAL_PTS = [(0, 0, 0), (4, 0, 0), (1.7, 3.1, 0), (1.3, 0.9, 2.8),
              (3.4, 2.2, 4.1)]
CHIRAL_BARS = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3), (3, 4), (1, 4)]


def rotation(axis, degrees):
    x, y, z = axis
    n = math.sqrt(x * x + y * y + z * z)
    x, y, z = x / n, y / n, z / n
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
            [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
            [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]]


def placed(pts, matrix=None, offset=(0, 0, 0), mirror=False):
    out = []
    for p in pts:
        q = (p[0], p[1], -p[2]) if mirror else p
        if matrix:
            q = tuple(sum(matrix[i][j] * q[j] for j in range(3))
                      for i in range(3))
        out.append(tuple(q[i] + offset[i] for i in range(3)))
    return out


def sig(pts, pairs, **kw):
    return sm.assembly_signature(pts, bars(pairs), range(len(pairs)), **kw)


# ── the signature: what it must survive ──────────────────────────────────

def test_the_same_truss_somewhere_else_is_the_same_part():
    drawn, _ = sig(FLAT_PTS, FLAT_BARS)
    moved, _ = sig(placed(FLAT_PTS, offset=(100, -50, 7)), FLAT_BARS)
    assert moved == drawn


@pytest.mark.parametrize('axis,deg', [
    ((0, 0, 1), 90), ((0, 0, 1), 180), ((1, 0, 0), 45),
    ((0.3, 0.8, 0.5), 37), ((-0.2, 0.1, 0.9), 211),
])
def test_the_same_truss_turned_any_way_is_the_same_part(axis, deg):
    """A bay turned to face the other way is the same truss. Comparing raw
    coordinates would call it a different part and have the shop build a
    second drawing of the same steel."""
    drawn, _ = sig(FLAT_PTS, FLAT_BARS)
    turned, _ = sig(placed(FLAT_PTS, rotation(axis, deg), (12, 3, -9)),
                    FLAT_BARS)
    assert turned == drawn


def test_a_flat_truss_is_its_own_mirror():
    """Reflecting a planar truss in its own plane gives the same truss back,
    so it must NOT be reported as a handed pair -- there is no left-hand
    version of it to get wrong."""
    drawn, mirror = sig(FLAT_PTS, FLAT_BARS)
    assert drawn == mirror


def test_a_chiral_assembly_is_not_its_own_mirror():
    drawn, mirror = sig(CHIRAL_PTS, CHIRAL_BARS)
    assert drawn != mirror


def test_the_mirror_of_a_chiral_assembly_is_recognised_as_the_mirror():
    drawn, mirror = sig(CHIRAL_PTS, CHIRAL_BARS)
    m_drawn, m_mirror = sig(placed(CHIRAL_PTS, mirror=True), CHIRAL_BARS)
    assert m_drawn == mirror
    assert m_mirror == drawn
    assert m_drawn != drawn, 'a left hand is not a right hand'


def test_a_mirrored_assembly_turned_and_moved_is_still_the_mirror():
    _drawn, mirror = sig(CHIRAL_PTS, CHIRAL_BARS)
    far = placed(CHIRAL_PTS, rotation((0.2, -0.7, 0.4), 113), (-20, 8, 3),
                 mirror=True)
    m_drawn, _ = sig(far, CHIRAL_BARS)
    assert m_drawn == mirror


def test_moving_one_node_makes_it_a_different_part():
    drawn, _ = sig(FLAT_PTS, FLAT_BARS)
    changed = list(FLAT_PTS)
    changed[4] = (4.5, 0, 2.6)
    other, _ = sig(changed, FLAT_BARS)
    assert other != drawn


def test_the_same_shape_in_a_different_section_is_a_different_part():
    """Same bars in the same places, ordered as different steel."""
    a = sm.assembly_signature(FLAT_PTS, bars(FLAT_BARS, profile='IPE200'),
                              range(len(FLAT_BARS)))
    b = sm.assembly_signature(FLAT_PTS, bars(FLAT_BARS, profile='IPE300'),
                              range(len(FLAT_BARS)))
    assert a[0] != b[0]


def test_the_same_shape_connected_differently_is_a_different_part():
    """Welded ends and bolted ends are different shop work."""
    a = sm.assembly_signature(FLAT_PTS, bars(FLAT_BARS, conn='pin'),
                              range(len(FLAT_BARS)))
    b = sm.assembly_signature(FLAT_PTS, bars(FLAT_BARS, conn='rigid'),
                              range(len(FLAT_BARS)))
    assert a[0] != b[0]


def test_a_missing_diagonal_makes_it_a_different_part():
    """Same nodes, one bar fewer: the arrangement is part of the identity,
    not just the point cloud."""
    full, _ = sig(FLAT_PTS, FLAT_BARS)
    fewer, _ = sig(FLAT_PTS, FLAT_BARS[:-1])
    assert fewer != full


# ── the tolerance ────────────────────────────────────────────────────────

def test_noise_under_the_tolerance_is_the_same_part():
    """Two trusses that came through a drawing exchange agree to about a
    millimetre, not to the last bit of a double."""
    drawn, _ = sig(FLAT_PTS, FLAT_BARS, tol_mm=5.0)
    nudged = [(x + 0.0012, y - 0.0009, z + 0.0004) for x, y, z in FLAT_PTS]
    other, _ = sig(nudged, FLAT_BARS, tol_mm=5.0)
    assert other == drawn


def test_a_difference_over_the_tolerance_is_a_different_part():
    drawn, _ = sig(FLAT_PTS, FLAT_BARS, tol_mm=1.0)
    stretched = list(FLAT_PTS)
    stretched[2] = (6.05, 0, 0)          # 50 mm longer
    other, _ = sig(stretched, FLAT_BARS, tol_mm=1.0)
    assert other != drawn


def test_the_tolerance_is_part_of_the_comparison():
    """Signatures computed at different tolerances are never equal, so a
    cached mark from one setting can never be read under another."""
    a, _ = sig(FLAT_PTS, FLAT_BARS, tol_mm=1.0)
    b, _ = sig(FLAT_PTS, FLAT_BARS, tol_mm=10.0)
    assert a != b


@pytest.mark.parametrize('given,expect', [
    (None, sm.DEFAULT_TOL_MM), ('', sm.DEFAULT_TOL_MM),
    ('abc', sm.DEFAULT_TOL_MM), (0, sm.DEFAULT_TOL_MM),
    (-3, sm.DEFAULT_TOL_MM), (float('nan'), sm.DEFAULT_TOL_MM),
    (float('inf'), sm.DEFAULT_TOL_MM),
    (1e-9, sm.MIN_TOL_MM), (1e9, sm.MAX_TOL_MM),
    ('2.5', 2.5), (2.5, 2.5),
])
def test_a_nonsense_tolerance_falls_back_rather_than_crashing(given, expect):
    assert sm.clamp_tol(given) == expect


# ── symmetry, and knowing when to refuse ─────────────────────────────────

def test_a_symmetric_structure_still_compares_equal_to_its_own_rotation():
    """A cube's corners all tie for "farthest from the centre", so there is
    no single canonical frame -- every tied candidate is tried and the
    smallest spelling wins. Turn the cube a third of the way round its
    diagonal and it must still be the same part."""
    cube = [(x, y, z) for x in (0, 2) for y in (0, 2) for z in (0, 2)]
    pairs = [(i, j) for i in range(8) for j in range(i + 1, 8)
             if abs(sum((cube[i][k] - cube[j][k]) ** 2
                        for k in range(3)) - 4) < 1e-9]
    drawn, _ = sig(cube, pairs)
    turned, _ = sig(placed(cube, rotation((1, 1, 1), 120), (5, 5, 5)), pairs)
    assert drawn is not None
    assert turned == drawn


def test_a_single_rod_is_a_part_like_any_other():
    """One bar shipped on its own is still a piece, and two such bars of
    the same length and section are the same piece."""
    one = sm.assembly_signature([(0, 0, 0), (1, 0, 0)], bars([(0, 1)]), [0])
    same = sm.assembly_signature([(9, 9, 9), (9, 10, 9)], bars([(0, 1)]), [0])
    longer = sm.assembly_signature([(0, 0, 0), (2, 0, 0)], bars([(0, 1)]), [0])
    assert one[0] is not None
    assert same[0] == one[0], 'a bar is the same bar wherever it lies'
    assert longer[0] != one[0]


def test_no_rods_claims_nothing():
    assert sm.assembly_signature(FLAT_PTS, bars(FLAT_BARS), []) == (None, None)


def test_rods_outside_the_model_are_ignored_not_crashed_on():
    drawn, _ = sm.assembly_signature(FLAT_PTS, bars(FLAT_BARS),
                                     list(range(len(FLAT_BARS))) + [99, -1])
    assert drawn == sig(FLAT_PTS, FLAT_BARS)[0]


def test_every_node_on_the_centroid_is_refused():
    """Nothing to build a frame from. Refusing is the safe answer: the
    caller gives it a mark of its own rather than merging it with
    something it never compared."""
    assert sm.assembly_signature(
        [(0, 0, 0), (0, 0, 0)], bars([(0, 1)]), [0]) == (None, None)


def test_the_signature_is_stable_across_calls():
    """Marks are recomputed every time, so a signature that moved between
    runs would renumber a schedule for no reason."""
    first = sig(CHIRAL_PTS, CHIRAL_BARS)
    for _ in range(5):
        assert sig(CHIRAL_PTS, CHIRAL_BARS) == first


# ── part marks: the bar list ──────────────────────────────────────────────

def _model():
    """Six rods: three 3 m IPE200, two 3 m IPE300, one 5 m IPE200."""
    nodes = [(0, 0, 0), (3, 0, 0), (6, 0, 0), (9, 0, 0),
             (0, 1, 0), (3, 1, 0), (6, 1, 0), (0, 2, 0), (5, 2, 0)]
    members = (bars([(0, 1), (1, 2), (2, 3)], profile='IPE200')
               + bars([(4, 5), (5, 6)], profile='IPE300')
               + bars([(7, 8)], profile='IPE200'))
    return nodes, members


def test_identical_rods_share_a_mark():
    nodes, members = _model()
    by_rod, rows = sm.part_marks(nodes, members)
    assert by_rod[0] == by_rod[1] == by_rod[2]
    assert len({m for m in by_rod}) == 3
    assert {r['mark']: r['qty'] for r in rows} == {'B1': 3, 'B2': 2, 'B3': 1}


def test_the_most_used_part_is_numbered_first():
    """A fabricator reads the list top down, so the repeated work belongs at
    the top -- and the headline part keeps its number when something rare
    is added."""
    nodes, members = _model()
    _by_rod, rows = sm.part_marks(nodes, members)
    assert [r['qty'] for r in rows] == sorted(
        (r['qty'] for r in rows), reverse=True)
    assert rows[0]['mark'] == 'B1'


def test_a_different_length_is_a_different_part():
    nodes, members = _model()
    by_rod, _rows = sm.part_marks(nodes, members)
    assert by_rod[5] != by_rod[0], '5 m is not 3 m'


def test_the_quantities_add_up_to_the_model():
    nodes, members = _model()
    _by_rod, rows = sm.part_marks(nodes, members)
    assert sum(r['qty'] for r in rows) == len(members)
    assert sum(len(r['rods']) for r in rows) == len(members)


def test_the_totals_are_the_each_figures_times_the_count():
    nodes, members = _model()
    _by_rod, rows = sm.part_marks(nodes, members)
    for r in rows:
        assert r['total_length_m'] == pytest.approx(r['length_m'] * r['qty'])
        assert r['total_mass_kg'] == pytest.approx(r['mass_kg'] * r['qty'])


def test_a_rod_pointing_at_a_node_that_is_gone_is_left_unmarked():
    """An index past the end of the node list is a model mid-edit, not a
    reason to refuse the whole schedule."""
    nodes, members = _model()
    members.append({'a': 0, 'b': 999, 'profile': 'IPE200', 'A': 28.5})
    by_rod, rows = sm.part_marks(nodes, members)
    assert by_rod[-1] is None
    assert sum(r['qty'] for r in rows) == len(members) - 1


def test_timber_and_steel_of_the_same_size_are_different_parts():
    nodes, members = _model()
    members[0] = dict(members[0], gamma_kN_m3=5.0)
    by_rod, _rows = sm.part_marks(nodes, members)
    assert by_rod[0] != by_rod[1]


def test_mass_uses_the_rods_own_density_when_it_has_one():
    nodes = [(0, 0, 0), (1, 0, 0)]
    steel = bars([(0, 1)])[0]
    timber = dict(steel, gamma_kN_m3=5.0)
    assert sm.rod_mass_kg(nodes, steel) > 10 * sm.rod_mass_kg(nodes, timber)


# ── assembly marks: the piece list ────────────────────────────────────────

def _three_trusses(third_mirrored):
    """Two identical chiral trusses and a third that is either a copy or a
    mirror image of them."""
    nodes, members, groups = [], [], []
    for k, mirror in enumerate((False, False, third_mirrored)):
        at = len(nodes)
        nodes.extend(placed(CHIRAL_PTS, offset=(40 * k, 0, 0), mirror=mirror))
        first = len(members)
        members.extend(bars([(a + at, b + at) for a, b in CHIRAL_BARS]))
        groups.append({'id': k + 1, 'name': 'Truss %s' % 'ABC'[k],
                       'parent': None,
                       'members': set(range(first, len(members)))})
    return nodes, members, groups


def test_identical_groups_share_a_mark_with_a_count():
    nodes, members, groups = _three_trusses(third_mirrored=False)
    by_gid, rows = sm.assembly_marks(nodes, members, groups)
    assert by_gid == {1: 'T1', 2: 'T1', 3: 'T1'}
    assert [(r['mark'], r['qty']) for r in rows] == [('T1', 3)]


def test_a_mirrored_copy_is_marked_apart_not_merged():
    """Eight trusses, two drawings, and nobody bolting a left-hand one into
    a right-hand bay."""
    nodes, members, groups = _three_trusses(third_mirrored=True)
    by_gid, rows = sm.assembly_marks(nodes, members, groups)
    assert by_gid == {1: 'T1', 2: 'T1', 3: 'T1' + sm.MIRROR_SUFFIX}
    assert [(r['mark'], r['qty'], r['mirrored']) for r in rows] == [
        ('T1', 2, False), ('T1/m', 1, True)]


def test_a_group_with_no_rods_of_its_own_gets_no_mark():
    """A parent that only holds subgroups is a branch of the tree, not a
    piece to fabricate."""
    nodes, members, groups = _three_trusses(third_mirrored=False)
    groups.append({'id': 9, 'name': 'Roof', 'parent': None, 'members': set()})
    by_gid, _rows = sm.assembly_marks(nodes, members, groups)
    assert 9 not in by_gid


def test_a_group_is_compared_on_its_own_rods_not_its_subtree():
    """Otherwise a parent holding one truss would be compared against that
    truss on the same steel and come out as the same part."""
    nodes, members, groups = _three_trusses(third_mirrored=False)
    parent = {'id': 9, 'name': 'Roof', 'parent': None, 'members': set()}
    groups.append(parent)
    for g in groups[:3]:
        g['parent'] = 9
    by_gid, rows = sm.assembly_marks(nodes, members, groups)
    assert 9 not in by_gid
    assert [(r['mark'], r['qty']) for r in rows] == [('T1', 3)]


def test_different_groups_get_different_marks():
    nodes, members, groups = _three_trusses(third_mirrored=False)
    # Lengthen one bar of the third truss well past the tolerance.
    third = sorted(groups[2]['members'])[0]
    members[third] = dict(members[third], profile='IPE400')
    by_gid, rows = sm.assembly_marks(nodes, members, groups)
    assert by_gid[1] == by_gid[2] != by_gid[3]
    assert sorted(r['mark'] for r in rows) == ['T1', 'T2']


def test_the_marks_and_counts_cover_every_group_that_has_rods():
    nodes, members, groups = _three_trusses(third_mirrored=True)
    by_gid, rows = sm.assembly_marks(nodes, members, groups)
    assert set(by_gid) == {g['id'] for g in groups if g['members']}
    assert sum(r['qty'] for r in rows) == len(by_gid)
    assert sum(len(r['gids']) for r in rows) == len(by_gid)


def test_schedule_gathers_both_levels():
    nodes, members, groups = _three_trusses(third_mirrored=True)
    s = sm.schedule(nodes, members, groups, tol_mm=2.0)
    assert s['tol_mm'] == 2.0
    assert len(s['part_of_rod']) == len(members)
    assert {r['mark'] for r in s['assemblies']} == {'T1', 'T1/m'}
    assert s['mark_of_group'][3] == 'T1/m'
    assert all(r['qty'] >= 1 for r in s['parts'])


def test_a_model_with_no_groups_still_lists_its_parts():
    nodes, members = _model()
    s = sm.schedule(nodes, members, [])
    assert s['assemblies'] == []
    assert s['mark_of_group'] == {}
    assert sum(r['qty'] for r in s['parts']) == len(members)


# ── keeping a number across revisions ────────────────────────────────────

def _shed(count_by_length, profile='IPE 200'):
    """A model of N rods at each given length, each rod on its own."""
    nodes, members = [], []
    for length, count in count_by_length:
        for _ in range(count):
            at = len(nodes)
            nodes.extend([(0, len(nodes), 0), (length, len(nodes), 0)])
            members.append(bars([(at, at + 1)], profile=profile)[0])
    return nodes, members


def _add(nodes, members, length, count, profile='IPE 200'):
    for _ in range(count):
        at = len(nodes)
        nodes.extend([(0, len(nodes), 0), (length, len(nodes), 0)])
        members.append(bars([(at, at + 1)], profile=profile)[0])


def _by_length(rows):
    return {round(r['length_m'], 3): r['mark'] for r in rows}


def test_without_a_register_a_more_numerous_part_takes_the_first_number():
    """The behaviour the register exists to override. T1 is the most
    repeated work, which is right until the numbers have gone out."""
    nodes, members = _shed([(3.0, 5), (4.0, 3)])
    before = _by_length(sm.part_marks(nodes, members)[1])
    assert before[3.0] == 'B1'
    _add(nodes, members, 6.0, 9)
    after = _by_length(sm.part_marks(nodes, members)[1])
    assert after[6.0] == 'B1'
    assert after[3.0] != before[3.0], 'everything renumbered'


def test_an_issued_part_keeps_its_number_whatever_arrives_after_it():
    nodes, members = _shed([(3.0, 5), (4.0, 3)])
    register = sm.issue(sm.schedule(nodes, members))
    before = _by_length(sm.part_marks(nodes, members)[1])
    _add(nodes, members, 6.0, 9)
    after = _by_length(sm.part_marks(nodes, members, register=register)[1])
    assert after[3.0] == before[3.0] == 'B1'
    assert after[4.0] == before[4.0] == 'B2'
    assert after[6.0] == 'B3', 'the new part takes the next free number'


def test_a_number_that_went_out_is_never_given_to_another_part():
    """Two different parts called B2 in two revisions is the failure this
    exists to prevent, so the list has holes rather than reusing one."""
    nodes, members = _shed([(3.0, 5), (4.0, 3), (5.0, 1)])
    register = sm.issue(sm.schedule(nodes, members))
    members[:] = [m for m in members
                  if abs(sm.rod_length(nodes, m) - 4.0) > 1e-9]
    _add(nodes, members, 7.0, 2)
    after = _by_length(sm.part_marks(nodes, members, register=register)[1])
    assert 'B2' not in after.values()
    assert after[7.0] == 'B4', after


def test_a_part_that_has_left_the_model_is_named_as_withdrawn():
    nodes, members = _shed([(3.0, 5), (4.0, 3)])
    register = sm.issue(sm.schedule(nodes, members))
    members[:] = [m for m in members
                  if abs(sm.rod_length(nodes, m) - 4.0) > 1e-9]
    data = sm.schedule(nodes, members, register=register)
    assert data['withdrawn'] == ['B2']
    assert data['issued'] is True


def test_nothing_is_withdrawn_while_every_part_is_still_built():
    nodes, members = _shed([(3.0, 5), (4.0, 3)])
    register = sm.issue(sm.schedule(nodes, members))
    assert sm.schedule(nodes, members, register=register)['withdrawn'] == []


def test_issuing_again_keeps_what_was_already_held():
    """A second issue adds the new parts and leaves the old entries as
    they were, or the first revision's numbers would move."""
    nodes, members = _shed([(3.0, 5)])
    first = sm.issue(sm.schedule(nodes, members))
    _add(nodes, members, 6.0, 9)
    second = sm.issue(sm.schedule(nodes, members, register=first), first)
    assert first[sm.PART_PREFIX].items() <= second[sm.PART_PREFIX].items()
    marks = _by_length(sm.part_marks(nodes, members, register=second)[1])
    assert marks[3.0] == 'B1' and marks[6.0] == 'B2'


def test_assemblies_keep_their_numbers_too():
    nodes, members, groups = _three_trusses(third_mirrored=False)
    register = sm.issue(sm.schedule(nodes, members, groups))
    before = sm.assembly_marks(nodes, members, groups)[0]
    # Add a part that is more numerous, which would otherwise take T1.
    extra = []
    for k in range(5):
        at = len(nodes)
        nodes.extend(placed(CHIRAL_PTS, offset=(0, 90 + 20 * k, 0)))
        first = len(members)
        members.extend(bars([(a + at, b + at) for a, b in CHIRAL_BARS],
                            profile='IPE 400'))
        groups.append({'id': 100 + k, 'name': 'Other %d' % k,
                       'parent': None,
                       'members': set(range(first, len(members)))})
        extra.append(100 + k)
    after = sm.assembly_marks(nodes, members, groups, register=register)[0]
    assert all(after[g] == before[g] for g in before)
    assert after[extra[0]] not in before.values()


def test_a_mirrored_copy_does_not_change_the_number_it_is_held_to():
    """Which copy names a bucket is an accident of the group order. A
    signature that moved with it would lose the number whenever a copy
    was deleted."""
    nodes, members, groups = _three_trusses(third_mirrored=True)
    register = sm.issue(sm.schedule(nodes, members, groups))
    before = sm.assembly_marks(nodes, members, groups, register=register)[0]
    # Delete the first, unmirrored copy: the mirrored one now names it.
    gone = groups[0]['id']
    groups[:] = [g for g in groups if g['id'] != gone]
    after = sm.assembly_marks(nodes, members, groups, register=register)[0]
    assert {sm.mark_number(m) for m in after.values()} == \
        {sm.mark_number(m) for m in before.values()}


def test_a_register_from_another_tolerance_is_reported_as_not_applying():
    """Its signatures were computed under that tolerance, so none match.
    Everything would be numbered again, silently, without this."""
    nodes, members = _shed([(3.0, 5)])
    register = sm.issue(sm.schedule(nodes, members, tol_mm=1.0))
    assert sm.register_applies(register, 1.0)
    assert not sm.register_applies(register, 25.0)
    assert sm.register_applies(None, 25.0), 'no register always applies'


def test_a_register_is_keyed_by_shape_so_it_cannot_be_wrong():
    """The whole reason storing this does not break "a mark is derived".
    Change the steel and the entry simply stops matching; it never names
    the wrong part."""
    nodes, members = _shed([(3.0, 2)])
    register = sm.issue(sm.schedule(nodes, members))
    assert _by_length(sm.part_marks(nodes, members, register=register)[1]) \
        == {3.0: 'B1'}
    for m in members:
        m['profile'] = 'IPE 400'
    marks = sm.part_marks(nodes, members, register=register)[1]
    assert marks[0]['mark'] == 'B2', 'different steel, a number of its own'
    assert sm.schedule(nodes, members, register=register)['withdrawn'] \
        == ['B1']


def test_every_schedule_row_carries_what_the_register_knows_it_by():
    nodes, members, groups = _three_trusses(third_mirrored=True)
    data = sm.schedule(nodes, members, groups)
    assert all(r['signature'] for r in data['parts'])
    assert all(r['signature'] for r in data['assemblies'])


def test_a_group_we_declined_to_compare_is_never_registered():
    """No signature means we never measured it, so there is nothing to
    hold it to -- and it must not quietly take a held number."""
    nodes = [(0, 0, 0), (0, 0, 0)]
    members = bars([(0, 1)])
    groups = [{'id': 1, 'name': 'Collapsed', 'parent': None, 'members': {0}}]
    data = sm.schedule(nodes, members, groups)
    assert data['assemblies'][0]['signature'] is None
    register = sm.issue(data)
    assert register[sm.ASSEMBLY_PREFIX] == {}
