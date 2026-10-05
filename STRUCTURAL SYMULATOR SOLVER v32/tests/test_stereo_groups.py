"""Groups of rods (roadmap 4.1) and the one-section-per-group recommendation.

The two rules under test throughout: a ROD is in exactly one group, and a
NODE's membership is DERIVED from the rods that touch it.
"""
import math

import pytest

from apps.stereo import stereo_groups as sgp
from apps.stereo import stereo_math as sm
from apps.stereo import stereo_checks as sk
from apps.stereo import stereo_profiles as sp


def _bar(a, b, **kw):
    m = dict(a=a, b=b, E=200.0, A=20.0, I=400.0, J=400.0, Fy=235.0, Fu=360.0,
             K=1.0, r_gyr=3.0)
    m.update(kw)
    return m


# ── rule 1: a rod belongs to exactly one group ─────────────────────────────

def test_assigning_a_rod_moves_it_out_of_its_old_group():
    groups = []
    a = sgp.new_group(groups, 'A', members=[0, 1, 2])
    b = sgp.new_group(groups, 'B')
    sgp.assign(groups, b['id'], [1, 2])
    assert a['members'] == {0}
    assert b['members'] == {1, 2}


def test_no_rod_can_end_up_in_two_groups_however_it_is_assigned():
    groups = []
    ids = [sgp.new_group(groups, n)['id'] for n in 'ABC']
    for gid in ids:
        sgp.assign(groups, gid, [5])
    holders = [g['id'] for g in groups if 5 in g['members']]
    assert holders == [ids[-1]], holders


def test_unassigning_returns_rods_to_ungrouped():
    groups = []
    sgp.new_group(groups, 'A', members=[0, 1])
    sgp.unassign(groups, [1])
    assert sgp.ungrouped_rods(groups, 3) == [1, 2]


def test_everything_unassigned_is_the_implicit_ungrouped_set():
    groups = []
    sgp.new_group(groups, 'A', members=[0, 2])
    assert sgp.ungrouped_rods(groups, 5) == [1, 3, 4]
    assert sgp.ungrouped_rods([], 3) == [0, 1, 2]


# ── arbitrary nesting ──────────────────────────────────────────────────────

def test_groups_nest_to_any_depth():
    groups = []
    gid = None
    for i in range(6):
        gid = sgp.new_group(groups, 'L%d' % i, parent=gid)['id']
    assert sgp.depth(groups, gid) == 5
    assert len(sgp.walk(groups)) == 6


def test_a_parents_rods_include_its_whole_subtree():
    groups = []
    root = sgp.new_group(groups, 'Roof', members=[0])
    bay = sgp.new_group(groups, 'Bay', parent=root['id'], members=[1])
    sgp.new_group(groups, 'Truss', parent=bay['id'], members=[2, 3])
    assert sgp.rods_of(groups, root['id'], deep=True) == [0, 1, 2, 3]
    assert sgp.rods_of(groups, root['id'], deep=False) == [0]


def test_a_group_cannot_be_nested_inside_itself():
    groups = []
    a = sgp.new_group(groups, 'A')
    b = sgp.new_group(groups, 'B', parent=a['id'])
    with pytest.raises(ValueError, match='inside itself'):
        sgp.reparent(groups, a['id'], b['id'])
    with pytest.raises(ValueError, match='inside itself'):
        sgp.reparent(groups, a['id'], a['id'])


def test_deleting_a_middle_group_keeps_its_children():
    """Deleting one group must not silently take a whole branch with it."""
    groups = []
    a = sgp.new_group(groups, 'A')
    b = sgp.new_group(groups, 'B', parent=a['id'])
    c = sgp.new_group(groups, 'C', parent=b['id'], members=[7])
    sgp.delete(groups, b['id'])
    assert sgp.find(groups, c['id'])['parent'] == a['id']
    assert sgp.find(groups, c['id'])['members'] == {7}


def test_deleting_recursively_returns_every_rod_to_ungrouped():
    groups = []
    a = sgp.new_group(groups, 'A', members=[0])
    sgp.new_group(groups, 'B', parent=a['id'], members=[1, 2])
    sgp.delete(groups, a['id'], recursive=True)
    assert groups == []
    assert sgp.ungrouped_rods(groups, 3) == [0, 1, 2]


# ── rule 2: node membership is derived ─────────────────────────────────────

def test_a_nodes_groups_are_derived_from_the_rods_that_touch_it():
    members = [_bar(0, 1), _bar(1, 2), _bar(2, 3)]
    groups = []
    a = sgp.new_group(groups, 'A', members=[0])
    b = sgp.new_group(groups, 'B', members=[1])
    assert sgp.nodes_of(groups, members, a['id']) == [0, 1]
    assert sgp.nodes_of(groups, members, b['id']) == [1, 2]


def test_moving_a_rod_moves_its_nodes_with_it_automatically():
    """Nothing to maintain: the shared node follows the rod."""
    members = [_bar(0, 1), _bar(1, 2)]
    groups = []
    a = sgp.new_group(groups, 'A', members=[0, 1])
    b = sgp.new_group(groups, 'B')
    assert sgp.shared_nodes(groups, members, len(members),
                            include_ungrouped=False) == {}
    sgp.assign(groups, b['id'], [1])
    assert sgp.shared_nodes(groups, members, len(members),
                            include_ungrouped=False) == {1: [a['id'], b['id']]}


def test_a_shared_node_lists_every_group_that_meets_there():
    members = [_bar(0, 1), _bar(1, 2), _bar(1, 3)]
    groups = []
    ids = [sgp.new_group(groups, n, members=[i])['id']
           for i, n in enumerate('ABC')]
    shared = sgp.shared_nodes(groups, members, len(members),
                              include_ungrouped=False)
    assert shared == {1: ids}


def test_the_ungrouped_boundary_is_reported_too():
    """The boundary you have not thought about is usually this one."""
    members = [_bar(0, 1), _bar(1, 2)]
    groups = []
    a = sgp.new_group(groups, 'A', members=[0])
    shared = sgp.shared_nodes(groups, members, len(members))
    assert shared == {1: [a['id'], None]}
    assert sgp.shared_nodes(groups, members, len(members),
                            include_ungrouped=False) == {}


def test_a_parent_sharing_with_its_own_child_is_reported_as_internal():
    """Not hidden. A subgroup is often fabricated on its own and bolted in,
    so a bay meeting the roof that contains it is a real interface to
    detail. It is MARKED rather than omitted, so cross-branch joints can
    sort first without any joint going missing."""
    members = [_bar(0, 1), _bar(1, 2)]
    groups = []
    root = sgp.new_group(groups, 'Roof', members=[0])
    bay = sgp.new_group(groups, 'Bay', parent=root['id'], members=[1])
    shared = sgp.shared_nodes(groups, members, len(members),
                              include_ungrouped=False)
    assert shared == {1: [root['id'], bay['id']]}
    assert sgp.shared_node_kind(groups, shared[1]) == 'internal'


def test_two_separate_branches_sharing_a_node_is_cross():
    members = [_bar(0, 1), _bar(1, 2)]
    groups = []
    a = sgp.new_group(groups, 'A', members=[0])
    b = sgp.new_group(groups, 'B', members=[1])
    shared = sgp.shared_nodes(groups, members, len(members),
                              include_ungrouped=False)
    assert sgp.shared_node_kind(groups, shared[1]) == 'cross'


def test_sharing_with_ungrouped_is_always_cross():
    members = [_bar(0, 1), _bar(1, 2)]
    groups = []
    root = sgp.new_group(groups, 'Roof', members=[0])
    sgp.new_group(groups, 'Bay', parent=root['id'], members=[1])
    # rod 2 is nobody's, so node 2 is a Bay/Ungrouped boundary
    members.append(_bar(2, 3))
    shared = sgp.shared_nodes(groups, members, len(members))
    assert sgp.shared_node_kind(groups, shared[2]) == 'cross'


def test_the_shared_node_rows_carry_each_sides_force_and_sort_cross_first():
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0),
             (3.0, 0.0, 0.0)]
    members = [_bar(0, 1), _bar(1, 2), _bar(2, 3)]
    member_res = [{'N': 10.0}, {'N': -4.0}, {'N': 7.0}]
    groups = []
    root = sgp.new_group(groups, 'Roof', members=[0])
    bay = sgp.new_group(groups, 'Bay', parent=root['id'], members=[1])
    sgp.new_group(groups, 'Other', members=[2])
    rows = sgp.shared_node_rows(groups, nodes, members, member_res,
                                include_ungrouped=False)
    kinds = [r['kind'] for r in rows]
    assert kinds[0] == 'cross', kinds
    by_node = {r['node']: r for r in rows}
    assert by_node[1]['kind'] == 'internal'
    assert by_node[2]['kind'] == 'cross'
    # Node 1: Roof's rod 0 is in tension, pulling node 1 back towards node 0.
    roof_side = [s for s in by_node[1]['sides'] if s['group'] == root['id']][0]
    assert roof_side['rods'] == [0]
    assert roof_side['Fx'] == pytest.approx(-10.0)
    bay_side = [s for s in by_node[1]['sides'] if s['group'] == bay['id']][0]
    assert bay_side['rods'] == [1]
    assert bay_side['F'] == pytest.approx(4.0)


def test_interface_rods_name_each_groups_own_side_of_the_joint():
    members = [_bar(0, 1), _bar(1, 2), _bar(1, 3)]
    groups = []
    a = sgp.new_group(groups, 'A', members=[0])
    b = sgp.new_group(groups, 'B', members=[1, 2])
    assert sgp.interface_rods(groups, members, 1, a['id']) == [0]
    assert sgp.interface_rods(groups, members, 1, b['id']) == [1, 2]


def test_the_interface_force_is_what_the_branch_pulls_on_the_joint():
    """A bar in tension pulls the node towards its far end."""
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    members = [_bar(0, 1)]
    member_res = [{'N': 10.0}]
    fx, fy, fz = sgp.interface_force(members, member_res, [0], 0, nodes)
    assert fx == pytest.approx(10.0)
    assert (fy, fz) == pytest.approx((0.0, 0.0))
    # and from the other end it pulls the other way
    fx2, _fy, _fz = sgp.interface_force(members, member_res, [0], 1, nodes)
    assert fx2 == pytest.approx(-10.0)


# ── the sum check ──────────────────────────────────────────────────────────

def test_the_per_group_totals_account_for_every_rod_exactly_once():
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)]
    members = [_bar(0, 1), _bar(1, 2), _bar(2, 3)]
    groups = []
    sgp.new_group(groups, 'A', members=[0])
    sgp.new_group(groups, 'B', members=[1])
    rec = sgp.totals_reconcile(groups, nodes, members)
    assert rec['rods_in_groups'] == 2
    assert rec['rods_ungrouped'] == 1
    assert rec['rods_counted'] == rec['rods_in_model'] == 3
    assert rec['length_counted_m'] == pytest.approx(rec['length_in_model_m'])
    assert rec['ok']


def test_a_parents_summary_row_rolls_its_subtree_up():
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    members = [_bar(0, 1), _bar(1, 2)]
    groups = []
    root = sgp.new_group(groups, 'Roof', members=[0])
    sgp.new_group(groups, 'Bay', parent=root['id'], members=[1])
    rows = {r['name']: r for r in sgp.group_summary(groups, nodes, members)}
    assert rows['Roof']['n_rods'] == 2
    assert rows['Bay']['n_rods'] == 1
    assert rows['Roof']['length_m'] == pytest.approx(2.0)


def test_ungrouped_gets_its_own_summary_row_when_it_is_not_empty():
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    members = [_bar(0, 1), _bar(1, 2)]
    groups = []
    sgp.new_group(groups, 'A', members=[0])
    names = [r['name'] for r in sgp.group_summary(groups, nodes, members)]
    assert sgp.UNGROUPED_NAME in names
    groups[0]['members'] = {0, 1}
    names = [r['name'] for r in sgp.group_summary(groups, nodes, members)]
    assert sgp.UNGROUPED_NAME not in names


# ── one section for a whole group ──────────────────────────────────────────

def _res(forces):
    return [{'N': f, 'conn': 'pin'} for f in forces]


def test_the_recommendation_carries_every_rod_in_the_group():
    """The point of the feature: one section, and it has to work for all."""
    nodes = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (4.0, 0.0, 0.0)]
    members = [_bar(0, 1), _bar(1, 2)]
    member_res = _res([300.0, -120.0])
    rec = sk.recommend_for_group(nodes, members, member_res, [0, 1])
    assert rec is not None and rec['name'], rec
    assert rec['worst_util'] <= 1.0 + 1e-9
    for i, u in rec['utils'].items():
        assert u is not None and u <= 1.0 + 1e-9, (i, u)


def test_it_picks_the_lightest_section_that_passes():
    nodes = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    members = [_bar(0, 1)]
    member_res = _res([200.0])
    rec = sk.recommend_for_group(nodes, members, member_res, [0])
    chosen = sp.CATALOG[rec['name']]
    lighter = [s for s in (sp.CATALOG[n] for n in sp.catalog_names())
               if s.A_mm2 < chosen.A_mm2]
    for s in lighter:
        worst, _gov, _u = sk._worst_over(
            [dict(members[0], _length_m=2.0)], member_res, [0], s)
        assert worst is None or worst > 1.0, (
            '%s is lighter than %s and also passes' % (s.name, rec['name']))


def test_the_governing_rod_is_not_always_the_one_with_the_largest_force():
    """The subtlety that makes this a search rather than a lookup.

    Compression capacity comes from KL/r, so a LONG slender strut can decide
    the section even though a SHORT rod carries more force. Sizing for "the
    most solicited member" and stopping would pick a section that the long
    strut then fails.
    """
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0),        # rod 0: short, 1 m
             (0.0, 10.0, 0.0), (0.0, 20.0, 0.0)]      # rod 1: long, 10 m
    members = [_bar(0, 1), _bar(2, 3)]
    # The SHORT rod carries more, but the LONG one buckles first.
    member_res = _res([-150.0, -100.0])
    rec = sk.recommend_for_group(nodes, members, member_res, [0, 1])
    assert rec['largest_force'] == 0, rec['forces']
    assert rec['governing'] == 1, (rec['governing'], rec['utils'])
    assert rec['governing'] != rec['largest_force']


def test_a_section_sized_for_the_largest_force_alone_would_not_carry_the_group():
    """The same case, stated as the failure it prevents."""
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
             (0.0, 10.0, 0.0), (0.0, 20.0, 0.0)]
    members = [_bar(0, 1), _bar(2, 3)]
    member_res = _res([-150.0, -100.0])
    naive = sk.recommend_for_group(nodes, members, member_res, [0])   # short only
    whole = sk.recommend_for_group(nodes, members, member_res, [0, 1])
    assert sp.CATALOG[naive['name']].A_mm2 < sp.CATALOG[whole['name']].A_mm2


def test_it_reports_the_spare_capacity_and_the_price_of_one_section():
    nodes = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (4.0, 0.0, 0.0)]
    members = [_bar(0, 1), _bar(1, 2)]
    member_res = _res([300.0, 5.0])      # one working rod, one barely loaded
    rec = sk.recommend_for_group(nodes, members, member_res, [0, 1])
    assert 0.0 <= rec['spare'] <= 1.0
    # Most of the group is oversized, which is exactly what you are buying.
    assert rec['overshoot'] > 0.3, rec['overshoot']


def test_it_offers_the_next_size_up_for_deliberate_oversizing():
    nodes = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    members = [_bar(0, 1)]
    rec = sk.recommend_for_group(nodes, members, _res([200.0]), [0])
    assert rec['next_up']
    assert (sp.CATALOG[rec['next_up']].A_mm2
            >= sp.CATALOG[rec['name']].A_mm2)


def test_a_target_below_one_sizes_with_a_margin():
    nodes = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    members = [_bar(0, 1)]
    tight = sk.recommend_for_group(nodes, members, _res([300.0]), [0])
    easy = sk.recommend_for_group(nodes, members, _res([300.0]),
                                  [0], target_util=0.6)
    assert easy['worst_util'] <= 0.6 + 1e-9
    assert sp.CATALOG[easy['name']].A_mm2 >= sp.CATALOG[tight['name']].A_mm2


def test_an_impossible_group_says_so_and_names_the_heaviest_it_tried():
    nodes = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    members = [_bar(0, 1)]
    rec = sk.recommend_for_group(nodes, members, _res([500000.0]), [0])
    assert rec['name'] is None
    assert rec['heaviest_tried']
    assert 'No catalog section' in rec['note']


def test_restricting_the_candidates_to_one_family_is_honoured():
    nodes = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    members = [_bar(0, 1)]
    chs = sp.profiles_in_group('CHS (tubes)')
    rec = sk.recommend_for_group(nodes, members, _res([150.0]), [0],
                                 candidates=chs)
    assert rec['name'] in chs
    assert rec['considered'] == len([n for n in chs if n in sp.CATALOG])


def test_applying_it_gives_every_rod_in_the_group_the_same_section():
    """A group's rods need not start alike; setting the group sets all."""
    members = [_bar(0, 1, A=5.0), _bar(1, 2, A=99.0)]
    n = sk.apply_recommendation(members, [0, 1], 'IPE 200')
    assert n == 2
    assert members[0]['A'] == members[1]['A']
    assert members[0]['profile'] == members[1]['profile'] == 'IPE 200'


def test_applying_it_leaves_rods_outside_the_group_alone():
    members = [_bar(0, 1, A=5.0), _bar(1, 2, A=99.0)]
    sk.apply_recommendation(members, [0], 'IPE 200')
    assert members[1]['A'] == 99.0


def test_applying_an_unknown_section_is_refused_by_name():
    members = [_bar(0, 1)]
    with pytest.raises(ValueError, match='no catalog section'):
        sk.apply_recommendation(members, [0], 'IPE 9999')


def test_resizing_does_not_change_the_steel():
    """Re-sizing a rod is not a decision to change its material."""
    members = [_bar(0, 1, Fy=345.0, Fu=450.0, E=210.0)]
    sk.apply_recommendation(members, [0], 'IPE 200')
    assert members[0]['Fy'] == 345.0
    assert members[0]['Fu'] == 450.0
    assert members[0]['E'] == 210.0


def test_the_recommendation_reports_the_forces_it_was_computed_from():
    """Because they change once it is applied -- see the iteration below."""
    nodes = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    members = [_bar(0, 1)]
    rec = sk.recommend_for_group(nodes, members, _res([123.0]), [0])
    assert rec['forces'] == {0: 123.0}


def test_an_empty_group_has_no_recommendation():
    assert sk.recommend_for_group([], [], [], []) is None


def test_the_iteration_settles_on_a_section_and_says_so():
    """Stiffening a branch draws more load into it, so one pass is not an
    answer in an indeterminate structure. The loop re-solves the WHOLE
    structure each time -- never the branch alone."""
    # A square base, all four corners pinned, with an apex above the middle
    # on four legs: 3D and stable (the legs are not coplanar), and
    # indeterminate by one, so how the legs share the load depends on their
    # relative stiffness. The group is only TWO of the four legs, which is
    # what makes the redistribution real -- sizing all four together would
    # scale them alike and move nothing.
    nodes = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 4.0, 0.0),
             (0.0, 4.0, 0.0), (2.0, 2.0, 3.0)]
    members = [_bar(0, 4), _bar(1, 4), _bar(2, 4), _bar(3, 4)]
    supports = [{'node': i, 'type': 'pin'} for i in range(4)]
    # Off-centre so the four legs carry unequal force.
    loads = [{'node': 4, 'fz': -400.0, 'fx': 60.0}]
    base, err = sm.analyze(nodes, members, loads, supports)
    assert err is None, err
    rec, history, work = sk.iterate_recommendation(
        nodes, members, loads, supports, [0, 1])
    assert rec is not None, history
    assert rec.get('settled') is True, history
    assert rec['passes'] >= 2
    # the caller's own members are untouched until they accept it
    assert members[0]['A'] == 20.0
    assert work[0]['profile'] == rec['name']


def test_the_iteration_reports_a_solver_failure_rather_than_guessing():
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    members = [_bar(0, 1)]
    rec, history, _work = sk.iterate_recommendation(
        nodes, members, [{'node': 1, 'fz': -10.0}], [], [0])
    assert rec is None
    assert history and 'error' in history[-1]
