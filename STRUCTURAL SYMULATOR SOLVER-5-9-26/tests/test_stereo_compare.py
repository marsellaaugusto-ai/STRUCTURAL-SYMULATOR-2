"""Comparing iterations (stereo_compare), without Tk."""
import pytest

from apps.stereo import stereo_compare as scmp


def test_tags_are_proposed_from_the_names_and_their_order():
    names = (['Truss %d' % i for i in range(1, 13)]
             + ['Module %d' % i for i in range(1, 4)]
             + ['R%d Module 1' % i for i in range(1, 4)] + ['Misc'])
    t = scmp.propose_tags(names)
    # twelve trusses over three iterations: four each
    assert t['Truss 6'] == {'stage': 'truss', 'iteration': '2',
                            'position': '2'}
    assert t['Truss 12'] == {'stage': 'truss', 'iteration': '3',
                             'position': '4'}
    assert t['Module 3'] == {'stage': 'module', 'iteration': '3',
                             'position': '1'}
    # "R2": roof 2, said outright
    assert t['R2 Module 1'] == {'stage': 'roof', 'iteration': '2',
                                'position': '1'}
    assert t['Misc'] == {}


def test_spanish_names_and_an_explicit_iteration():
    t = scmp.propose_tags(['Iteración 2 cercha 3', 'Módulo 1'])
    assert t['Iteración 2 cercha 3']['stage'] == 'truss'
    assert t['Iteración 2 cercha 3']['iteration'] == '2'
    assert t['Módulo 1']['stage'] == 'module'


def test_the_compare_table_and_the_best_iteration():
    def row(w, util, verdict='OK'):
        return {'ok': True, 'verdict': verdict, 'weight': w, 'worst': util,
                'over': 0, 'hook_load': w, 'T_max': w / 3, 'L_max': 5.0,
                'angle_min': 50.0, 'd_std': 10.0}
    checked = [
        {'stage': 'truss', 'position': '1', 'iteration': '1',
         'group': 'Truss 1', 'row': row(20.0, 0.6)},
        {'stage': 'truss', 'position': '1', 'iteration': '2',
         'group': 'Truss 5', 'row': row(15.0, 0.4)},
        {'stage': 'module', 'position': '1', 'iteration': '1',
         'group': 'Module 1', 'row': row(90.0, 1.4, 'over capacity')},
        {'stage': 'module', 'position': '1', 'iteration': '2',
         'group': 'Module 2', 'row': row(95.0, 0.8)},
    ]
    its, table = scmp.compare_rows(checked)
    assert its == ['1', '2']
    assert table[0] == ('truss', '1', 'group', {'1': 'Truss 1',
                                                 '2': 'Truss 5'})
    labels = [r[2] for r in table if r[0] == 'truss']
    assert 'longest sling m' in labels and 'rope Ø mm' in labels
    assert scmp.best_iteration(checked) == {('truss', '1'): '2',
                                            ('module', '1'): '2'}


def test_check_lift_leaves_the_model_alone():
    from tests.test_stereo_lift_calc import _panel
    nodes, members, _picks = _panel()
    before = ([tuple(p) for p in nodes], [dict(m) for m in members])
    row = scmp.check_lift(nodes, members, list(range(len(members))),
                          'corners', {'daf': 1.0, 'allowance': 0.0},
                          7.85 * 9.81)
    assert row['ok'] and row['verdict'] == 'OK'
    assert len(row['picks']) == 4
    assert row['L_max'] > 0 and row['d_std'] is not None
    assert row['hook_load'] == pytest.approx(row['weight'], rel=1e-6)
    assert ([tuple(p) for p in nodes], members) == before


def test_merging_workbooks_keeps_the_group_tags():
    from apps.stereo import stereo_merge as smg
    base = {'nodes': [], 'members': [], 'loads': [], 'supports': [],
            'groups': [], 'profiles': {}}
    part = {'nodes': [(0, 0, 0), (1, 0, 0)],
            'members': [{'a': 0, 'b': 1}], 'loads': [], 'supports': [],
            'groups': [{'id': 1, 'name': 'Truss 5', 'parent': None,
                        'members': {0}, 'iteration': '2', 'stage': 'truss',
                        'position': '1', 'excluded': True}],
            'profiles': {}}
    merged, _rep = smg.merge_models(base, part, tol=1e-3, label='b.xlsx')
    g = merged['groups'][0]
    assert (g['iteration'], g['stage'], g['position'], g['excluded']) == \
        ('2', 'truss', '1', True)
