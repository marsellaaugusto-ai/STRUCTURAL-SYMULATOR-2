"""Locked groups: the rules, without the window.

The request, in its own words: once made, a group is an uneditable object
unless edit mode is opened; it moves as a whole but its parts cannot; its
nodes cannot be moved after grouping, but rods can still be added to them;
and while one group is being edited, everything outside it is blocked.

The model used throughout is a chain of eight nodes along x:

    0 --A-- 1 --A-- 2 --C-- 3 --B-- 4 --B-- 5 --u-- 6 --u-- 7

    A  rods 0, 1         (top level)
    C  rod 2             (inside A)
    B  rods 3, 4         (top level)
    u  rods 5, 6         Ungrouped

so node 3 is where A's subtree meets B, and node 5 is where B meets the
Ungrouped rods.
"""
from apps.stereo import stereo_groups as sgp


def _model():
    nodes = [(float(i), 0.0, 0.0) for i in range(8)]
    members = [{'a': i, 'b': i + 1} for i in range(7)]
    groups = []
    a = sgp.new_group(groups, 'A', members=[0, 1])
    c = sgp.new_group(groups, 'C', parent=a['id'], members=[2])
    b = sgp.new_group(groups, 'B', members=[3, 4])
    return nodes, members, groups, a['id'], b['id'], c['id']


# ── the object a click lands on ────────────────────────────────────────────

def test_a_subgroup_belongs_to_its_outermost_group():
    _n, _m, groups, A, _B, C = _model()
    assert sgp.top_group(groups, C) == A
    assert sgp.top_group(groups, A) == A


def test_with_no_group_open_only_ungrouped_rods_can_be_changed_alone():
    _n, members, groups, *_ = _model()
    assert sgp.editable_rods(groups, None, len(members)) == {5, 6}
    assert sgp.rod_locked(groups, 0) and sgp.rod_locked(groups, 3)
    assert not sgp.rod_locked(groups, 6)


def test_a_grouped_node_is_locked_and_a_free_one_is_not():
    _n, members, groups, *_ = _model()
    assert sgp.node_locked(groups, members, 0)
    assert sgp.node_locked(groups, members, 5), 'B touches node 5'
    assert not sgp.node_locked(groups, members, 7)
    assert sgp.editable_nodes(groups, members, None, n_nodes=9) == {6, 7, 8}


# ── moving: the whole object, never a part ─────────────────────────────────

def test_dragging_a_grouped_node_moves_its_whole_outermost_group():
    _n, members, groups, A, B, C = _model()
    plan = sgp.move_plan(groups, members, {1}, editing=None)
    assert plan['groups'] == [A]
    assert plan['nodes'] == [0, 1, 2, 3], 'A and its subgroup C, whole'


def test_a_group_that_shares_a_joint_with_another_group_will_not_move():
    _n, members, groups, A, B, C = _model()
    plan = sgp.move_plan(groups, members, {0}, editing=None)
    assert plan['conflicts'] == {3: [B]}
    text = sgp.describe_conflicts(groups, plan['conflicts'])
    assert 'node 3' in text and 'B' in text


def test_a_joint_shared_only_with_ungrouped_rods_moves_and_they_stretch():
    nodes, members, groups, A, B, C = _model()
    sgp.unassign(groups, [2])           # A no longer reaches node 3
    plan = sgp.move_plan(groups, members, {0}, editing=None)
    assert plan['conflicts'] == {}, 'rod 2 is Ungrouped now, not an object'
    assert plan['nodes'] == [0, 1, 2]


def test_grabbing_a_shared_joint_takes_every_group_that_meets_there():
    _n, members, groups, A, B, C = _model()
    plan = sgp.move_plan(groups, members, {3}, editing=None)
    assert plan['groups'] == sorted([A, B])
    assert plan['conflicts'] == {}
    assert plan['nodes'] == [0, 1, 2, 3, 4, 5]


def test_a_free_node_still_moves_on_its_own():
    _n, members, groups, *_ = _model()
    plan = sgp.move_plan(groups, members, {7}, editing=None)
    assert plan == {'nodes': [7], 'groups': [], 'conflicts': {}}


def test_moving_a_named_group_takes_its_subgroups_along():
    _n, members, groups, A, B, C = _model()
    plan = sgp.group_move_plan(groups, members, B)
    assert plan['nodes'] == [3, 4, 5]
    assert plan['conflicts'] == {3: [C]}, 'node 3 is shared with C, inside A'


# ── edit mode: the open group's parts, and nothing else ────────────────────

def test_opening_a_group_unlocks_its_parts_and_its_subgroups():
    _n, members, groups, A, B, C = _model()
    assert sgp.editable_rods(groups, A, len(members)) == {0, 1, 2}
    assert sgp.editable_nodes(groups, members, A) == {0, 1, 2, 3}
    assert not sgp.rod_locked(groups, 2, editing=A)


def test_while_one_group_is_open_everything_outside_it_is_blocked():
    _n, members, groups, A, B, C = _model()
    assert sgp.rod_locked(groups, 3, editing=A), 'another group'
    assert sgp.rod_locked(groups, 6, editing=A), 'Ungrouped, too'
    assert sgp.node_locked(groups, members, 6, editing=A)


def test_in_edit_mode_a_part_moves_by_itself():
    _n, members, groups, A, B, C = _model()
    plan = sgp.move_plan(groups, members, {1}, editing=A)
    assert plan == {'nodes': [1], 'groups': [], 'conflicts': {}}


def test_in_edit_mode_a_joint_shared_with_another_group_still_holds():
    _n, members, groups, A, B, C = _model()
    plan = sgp.move_plan(groups, members, {3}, editing=A)
    assert plan['conflicts'] == {3: [B]}


def test_in_edit_mode_a_selected_node_outside_the_group_is_ignored():
    _n, members, groups, A, B, C = _model()
    plan = sgp.move_plan(groups, members, {1, 6}, editing=A)
    assert plan['nodes'] == [1]


# ── deleting ──────────────────────────────────────────────────────────────

def test_a_locked_groups_rods_cannot_be_deleted():
    _n, members, groups, A, B, C = _model()
    block = sgp.delete_blockers(groups, members, set(), {0, 6})
    assert block == {A: [0]}
    assert 'A: rod 0' in sgp.describe_rods(groups, block)


def test_deleting_a_node_is_blocked_by_every_locked_rod_it_would_take():
    _n, members, groups, A, B, C = _model()
    assert sgp.delete_blockers(groups, members, {5}, set()) == {B: [4]}


def test_ungrouped_rods_delete_freely_with_no_group_open():
    _n, members, groups, *_ = _model()
    assert sgp.delete_blockers(groups, members, {7}, {5}) == {}


def test_in_edit_mode_the_open_groups_rods_delete_and_outside_ones_do_not():
    _n, members, groups, A, B, C = _model()
    assert sgp.delete_blockers(groups, members, set(), {0, 2}, editing=A) == {}
    assert sgp.delete_blockers(groups, members, {3}, set(), editing=A) == \
        {B: [3]}
    assert sgp.delete_blockers(groups, members, set(), {6}, editing=A) == \
        {None: [6]}


# ── membership ────────────────────────────────────────────────────────────

def test_a_rod_cannot_be_taken_out_of_a_locked_group():
    _n, _m, groups, A, B, C = _model()
    assert sgp.assign_blockers(groups, [0, 3, 6], B) == {A: [0]}
    assert sgp.assign_blockers(groups, [0], None) == {A: [0]}


def test_rods_move_freely_inside_the_open_group():
    _n, _m, groups, A, B, C = _model()
    assert sgp.assign_blockers(groups, [0, 2], C, editing=A) == {}


def test_only_an_open_group_takes_rods_without_asking():
    _n, _m, groups, A, B, C = _model()
    assert not sgp.target_open(groups, B)
    assert sgp.target_open(groups, C, editing=A)
    assert not sgp.target_open(groups, B, editing=A)


# ── operations that rebuild the lists ──────────────────────────────────────

def test_a_rebuild_that_moves_a_locked_node_is_caught():
    nodes, members, groups, A, B, C = _model()
    moved = list(nodes)
    moved[1] = (1.0, 0.5, 0.0)
    bad = sgp.geometry_violations(groups, nodes, members, moved, members)
    assert (A, 0, 'node 1 moved') in bad
    assert sgp.geometry_violations(groups, nodes, members, moved, members,
                                   editing=A) == []


def test_a_rebuild_that_drops_a_locked_rod_is_caught():
    nodes, members, groups, A, B, C = _model()
    fewer = [m for i, m in enumerate(members) if i != 4]
    assert sgp.geometry_violations(groups, nodes, members, nodes, fewer) == \
        [(B, 4, 'removed')]


def test_a_rebuild_that_only_adds_or_touches_ungrouped_rods_is_fine():
    nodes, members, groups, *_ = _model()
    more_nodes = list(nodes) + [(7.0, 1.0, 0.0)]
    more_nodes[7] = (7.0, 0.0, 2.0)            # node 7 is free
    more = [members[i] for i in (6, 0, 1, 2, 3, 4)] + [{'a': 7, 'b': 8}]
    assert sgp.geometry_violations(groups, nodes, members, more_nodes, more) == []


def test_groups_follow_their_rods_through_a_reorder():
    _n, members, groups, A, B, C = _model()
    shuffled = [members[i] for i in (6, 5, 4, 3, 2, 1, 0)]
    sgp.remap_by_endpoints(groups, members, shuffled)
    assert sgp.find(groups, A)['members'] == {5, 6}
    assert sgp.find(groups, C)['members'] == {4}
    assert sgp.find(groups, B)['members'] == {2, 3}


def test_a_rod_gone_from_the_rebuild_leaves_its_group():
    _n, members, groups, A, B, C = _model()
    sgp.remap_by_endpoints(groups, members, members[:4])
    assert sgp.find(groups, B)['members'] == {3}
