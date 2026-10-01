"""Merging several models into one structure (roadmap v2 4.5)."""
import pytest

from apps.stereo import stereo_merge as smg
from apps.stereo import stereo_groups as sgp


def _bar(a, b, A=20.0):
    return {'a': a, 'b': b, 'conn': 'pin', 'E': 200.0, 'A': A, 'I': 400.0,
            'J': 400.0, 'Fy': 235.0, 'Fu': 360.0, 'K': 1.0, 'r_gyr': 3.0}


def _roof():
    """Three nodes along x at z = 3 and two rods."""
    return {'nodes': [(0.0, 0.0, 3.0), (2.0, 0.0, 3.0), (4.0, 0.0, 3.0)],
            'members': [_bar(0, 1), _bar(1, 2)],
            'loads': [{'node': 1, 'fz': -10.0}],
            'supports': [], 'groups': [], 'profiles': {}}


def _columns():
    """Two columns standing under the roof's ends; the tops meet it."""
    return {'nodes': [(0.0, 0.0, 0.0), (0.0, 0.0, 3.0),
                      (4.0, 0.0, 0.0), (4.0, 0.0, 3.0004)],
            'members': [_bar(0, 1, A=50.0), _bar(2, 3, A=50.0)],
            'loads': [{'node': 1, 'fz': -2.0}],
            'supports': [{'node': 0, 'type': 'pin'}, {'node': 2, 'type': 'pin'}],
            'groups': [], 'profiles': {}}


def test_coincident_nodes_merge_and_the_rest_are_appended():
    merged, rep = smg.merge_models(_roof(), _columns())
    assert rep['nodes_merged'] == 2, 'both column tops sit on roof nodes'
    assert rep['nodes_added'] == 2
    assert len(merged['nodes']) == 5
    tops = {m['b'] for m in merged['members'][2:]}
    assert tops == {0, 2}, 'the columns now end on the roof\'s own nodes'


def test_the_tolerance_decides_what_counts_as_the_same_joint():
    _m, rep = smg.merge_models(_roof(), _columns(), tol=0.0001)
    assert rep['nodes_merged'] == 1, '0.4 mm apart is not within 0.1 mm'


def test_every_rod_keeps_its_own_section():
    merged, rep = smg.merge_models(_roof(), _columns())
    assert [m['A'] for m in merged['members']] == [20.0, 20.0, 50.0, 50.0]
    assert rep['members_added'] == 2


def test_a_rod_already_there_is_not_added_twice_and_the_first_section_wins():
    part = {'nodes': [(2.0, 0.0, 3.0), (4.0, 0.0, 3.0)],
            'members': [_bar(0, 1, A=99.0)], 'loads': [], 'supports': []}
    merged, rep = smg.merge_models(_roof(), part)
    assert rep['members_duplicate'] == 1 and rep['members_added'] == 0
    assert merged['members'][1]['A'] == 20.0


def test_a_rod_whose_ends_merge_into_one_node_is_dropped():
    part = {'nodes': [(0.0, 0.0, 3.0), (0.0, 0.0, 3.0005)],
            'members': [_bar(0, 1)], 'loads': [], 'supports': []}
    merged, rep = smg.merge_models(_roof(), part)
    assert rep['members_degenerate'] == 1
    assert len(merged['members']) == 2


def test_loads_on_a_shared_joint_add():
    merged, _rep = smg.merge_models(_roof(), _columns())
    at0 = sum(ld.get('fz', 0.0) for ld in merged['loads'] if ld['node'] == 0)
    assert at0 == pytest.approx(-2.0)
    total = sum(ld.get('fz', 0.0) for ld in merged['loads'])
    assert total == pytest.approx(-12.0)


def test_supports_at_a_shared_joint_combine_to_the_stricter():
    base = _roof()
    base['supports'] = [{'node': 0, 'type': 'rollerZ'}]
    part = {'nodes': [(0.0, 0.0, 3.0)], 'members': [], 'loads': [],
            'supports': [{'node': 0, 'type': 'pin'}]}
    merged, rep = smg.merge_models(base, part)
    from apps.stereo.stereo_math import support_restraints
    r = support_restraints(merged['supports'][0])
    assert r['ux'] and r['uy'] and r['uz']
    assert rep['supports_combined'] == 1


def test_groups_come_along_and_a_used_name_is_told_apart():
    base = _roof()
    sgp.new_group(base['groups'], 'Main', members=[0, 1])
    part = _columns()
    sgp.new_group(part['groups'], 'Main', members=[0])
    sgp.new_group(part['groups'], 'Right', members=[1])
    merged, rep = smg.merge_models(base, part, label='columns.xlsx')
    names = [g['name'] for g in merged['groups']]
    assert names == ['Main', 'Main (columns.xlsx)', 'Right']
    assert merged['groups'][1]['members'] == {2}
    assert merged['groups'][2]['members'] == {3}
    rec = sgp.totals_reconcile(merged['groups'], merged['nodes'],
                               merged['members'])
    assert rec['ok']


def test_the_inputs_are_left_alone():
    base, part = _roof(), _columns()
    smg.merge_models(base, part)
    assert len(base['nodes']) == 3 and len(part['nodes']) == 4


def test_the_summary_says_what_the_roadmap_asks_for():
    _m, rep = smg.merge_models(_roof(), _columns())
    text = smg.describe(rep, 2, 2)[0]
    assert text == ('Merged 2 node(s), combined 2 + 2 members. 2 coincident '
                    'node(s) were merged.')


def test_a_large_merge_is_not_quadratic():
    import time
    n = 4000
    base = {'nodes': [(float(i), 0.0, 0.0) for i in range(n)], 'members': [],
            'loads': [], 'supports': []}
    part = {'nodes': [(float(i), 0.0, 0.0) for i in range(n)], 'members': [],
            'loads': [], 'supports': []}
    t = time.time()
    _m, rep = smg.merge_models(base, part)
    assert rep['nodes_merged'] == n
    assert time.time() - t < 2.0
