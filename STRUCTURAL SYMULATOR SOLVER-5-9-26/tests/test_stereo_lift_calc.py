"""The crane as a lifting calculator (stereo_lift_calc), without Tk."""
import math

import pytest

from apps.stereo import stereo_lift as slift
from apps.stereo import stereo_lift_calc as slc
from apps.stereo import stereo_math as sm

SEC = {'E': 200.0, 'A': 10.0, 'I': 100.0, 'J': 100.0, 'Fy': 250.0,
       'Fu': 400.0, 'r_gyr': 2.0, 'K': 1.0, 'conn': 'pin'}


def _panel(n=3, size=2.0, depth=1.0):
    """A small pin-jointed space truss: a top square grid over a bottom
    grid offset by half a bay -- stable on its own, the way a lifted piece
    has to be."""
    nodes, members = [], []
    top = {}
    for i in range(n + 1):
        for j in range(n + 1):
            top[i, j] = len(nodes)
            nodes.append((i * size, j * size, depth))
    bot = {}
    for i in range(n):
        for j in range(n):
            bot[i, j] = len(nodes)
            nodes.append(((i + 0.5) * size, (j + 0.5) * size, 0.0))

    def rod(a, b):
        members.append(dict(SEC, a=a, b=b))
    for i in range(n + 1):
        for j in range(n + 1):
            if i < n:
                rod(top[i, j], top[i + 1, j])
            if j < n:
                rod(top[i, j], top[i, j + 1])
    for i in range(n):
        for j in range(n):
            if i < n - 1:
                rod(bot[i, j], bot[i + 1, j])
            if j < n - 1:
                rod(bot[i, j], bot[i, j + 1])
            for di in (0, 1):
                for dj in (0, 1):
                    rod(bot[i, j], top[i + di, j + dj])
    corners = [top[0, 0], top[n, 0], top[0, n], top[n, n]]
    return nodes, members, corners


def _lifted(mode='auto', value=None, daf=1.0, allowance=0.0):
    nodes, members, picks = _panel()
    rods = list(range(len(members)))
    w, cog = slc.piece_weight(nodes, members, rods, allowance)
    rise = slc.hook_rise(nodes, picks, cog[:2], mode, value)
    top = max(nodes[p][2] for p in picks)
    nodes, members, hook = slc.add_slings(nodes, members, picks, SEC,
                                          (cog[0], cog[1], top + rise))
    for m in members[len(rods):]:
        m['addon'] = 'K1'
    lift = {'code': 'K1', 'rods': rods, 'daf': daf, 'allowance': allowance}
    return nodes, members, picks, hook, lift


def test_the_weight_and_centre_of_gravity():
    nodes, members, _p = _panel()
    w, cog = slc.piece_weight(nodes, members, range(len(members)))
    want = sum(10.0 * 1e-4 * math.dist(nodes[m['a']], nodes[m['b']])
               * sm.DEFAULT_STEEL_UNIT_WEIGHT for m in members)
    assert w == pytest.approx(want)
    assert cog[:2] == pytest.approx((3.0, 3.0))
    w2, _c = slc.piece_weight(nodes, members, range(len(members)), 0.10)
    assert w2 == pytest.approx(1.10 * w)
    assert slc.piece_weight(nodes, members, []) == (0.0, None)


def test_the_lift_load_is_the_weight_times_the_factors():
    nodes, members, _p = _panel()
    rods = range(len(members))
    w, _c = slc.piece_weight(nodes, members, rods, 0.05)
    loads = slc.lift_loads(nodes, members, rods, 0.05, 1.3)
    assert -sum(ld['fz'] for ld in loads) == pytest.approx(w * 1.3)
    assert all(ld['fx'] == 0.0 and ld['fy'] == 0.0 for ld in loads)


@pytest.mark.parametrize('mode, value, check', [
    ('height', 5.0, lambda L, a, r: r == pytest.approx(5.0)),
    ('angle', 60.0, lambda L, a, r: min(a) == pytest.approx(60.0)),
    ('length', 6.0, lambda L, a, r: max(L) == pytest.approx(6.0)),
])
def test_the_four_ways_to_set_the_hook(mode, value, check):
    nodes, _m, picks = _panel()
    r = slc.hook_rise(nodes, picks, (3.0, 3.0), mode, value)
    hz = 1.0 + r
    L = [math.dist(nodes[p], (3.0, 3.0, hz)) for p in picks]
    a = [math.degrees(math.asin((hz - nodes[p][2]) / l))
         for p, l in zip(picks, L)]
    assert check(L, a, r)
    auto = slc.hook_rise(nodes, picks, (3.0, 3.0))
    assert auto > 0


@pytest.mark.parametrize('mode, value, words', [
    ('height', 0.0, 'greater than zero'),
    ('angle', 95.0, 'between 0° and 90°'),
    ('length', 2.0, 'cannot reach'),
    ('length', 'x', 'Give a number'),
])
def test_a_hook_that_cannot_work_says_why(mode, value, words):
    nodes, _m, picks = _panel()
    with pytest.raises(ValueError, match=words):
        slc.hook_rise(nodes, picks, (3.0, 3.0), mode, value)


def test_rope_sizing():
    # the inverse of the working load limit of a rope
    assert slc.rope_diameter_mm(slift.rope_wll_kN(20.0)) == pytest.approx(20.0)
    assert slc.rope_diameter_mm(0) == 0.0
    assert slc.standard_size(12.1) == 13
    assert slc.standard_size(12.0) == 12
    assert slc.standard_size(99.0) is None
    assert slc.parse_sizes('10; 8, 12') == (8.0, 10.0, 12.0)
    assert slc.parse_sizes('') == tuple(float(x) for x in
                                        slc.STANDARD_ROPE_MM)
    with pytest.raises(ValueError):
        slc.parse_sizes('8, -2')


def test_a_balanced_lift_hangs_level_and_the_slings_carry_it_all():
    nodes, members, picks, hook, lift = _lifted('angle', 60.0, daf=1.2,
                                               allowance=0.1)
    s = slc.solve_lift(nodes, members, lift)
    assert s['ok'], s['error']
    sm_ = s['summary']
    assert sm_['verdict'] == 'OK'
    assert sm_['balance'] < slc.BALANCE_TOL_KN
    assert sm_['lift_load'] == pytest.approx(sm_['weight'] * 1.2)
    assert sm_['hook_load'] == pytest.approx(sm_['lift_load'], rel=1e-6)
    vert = sum(sl['T'] * math.sin(math.radians(sl['angle']))
               for sl in sm_['slings'])
    assert vert == pytest.approx(sm_['lift_load'], rel=1e-6)
    for sl in sm_['slings']:
        assert sl['angle'] == pytest.approx(60.0)
        assert sl['d_std'] >= sl['d_req']
    # only what is lifted is in the answer
    assert set(s['member_res']) == set(lift['rods']) | set(s['cables'])
    text = slc.summary_text(sm_)
    assert text.startswith('Crane K1 — OK')
    assert 'Balance 0.00 kN (level)' in text


def test_a_lift_on_too_few_slings_names_the_loose_nodes():
    nodes, members, picks = _panel()
    rods = list(range(len(members)))
    nodes, members, hook = slc.add_slings(nodes, members, picks[:1], SEC,
                                          (0.0, 0.0, 5.0))
    for m in members[len(rods):]:
        m['addon'] = 'K1'
    s = slc.solve_lift(nodes, members, {'code': 'K1', 'rods': rods})
    assert not s['ok'] and 'three or more slings' in s['error']


def test_combine_greys_out_what_no_lift_touches():
    nodes, members, picks, hook, lift = _lifted()
    extra = len(members)
    members = members + [dict(SEC, a=0, b=1)]   # a rod no lift touches
    s = slc.solve_lift(nodes, members, lift)
    res, checks = slc.combine(len(nodes), members, [s])
    assert res['case'] == 'lift'
    assert res['member_res'][extra]['ghost'] is True
    assert checks[extra]['ghost'] is True and not checks[extra]['checked']
    assert not res['member_res'][0].get('ghost')
    assert len(res['node_res']) == len(nodes)


def test_the_service_model_leaves_the_crane_out_and_gives_it_back():
    nodes, members, picks, hook, lift = _lifted()
    supports = [{'node': p, 'type': 'pin'} for p in picks]
    loads = [{'node': 0, 'fz': -5.0}, {'node': hook, 'fz': -1.0}]
    svc = slc.service_model(nodes, members, supports, loads)
    assert len(svc['nodes']) == len(nodes) - 1, 'the hook is not a joint'
    assert len(svc['members']) == len(lift['rods'])
    assert [ld['node'] for ld in svc['loads']] == [0]
    res, err = sm.analyze(svc['nodes'], svc['members'], svc['loads'],
                          svc['supports'])
    assert err is None
    full = slc.expand_service(res, svc, nodes, members)
    assert len(full['member_res']) == len(members)
    assert all(full['member_res'][j]['N'] == 0.0
               and full['member_res'][j]['inert'] for j in svc['crane'])
    assert full['node_res'][hook]['uz'] == 0.0
    assert slc.service_model(nodes, members[:len(lift['rods'])],
                             supports, loads) is None


def test_the_cranes_sheet_round_trip():
    recs = [{'code': 'K1', 'group_name': 'Truss 1', 'picks': [3, 7, 9],
             'hook_xyz': (1.0, 2.0, 3.0), 'hook_mode': 'length',
             'hook_value': 6.5, 'daf': 1.25, 'allowance': 0.08,
             'wll_kN': 30.0, 'cable_spec': 'WLL 30 kN', 'sizes': (8.0, 10.0)}]
    rows = slc.crane_rows(recs)
    back = slc.read_crane_rows([dict(zip(slc.CRANE_SHEET_COLUMNS, r))
                                for r in rows])
    k1 = back['K1']
    assert k1['group_name'] == 'Truss 1'
    assert k1['picks'] == [3, 7, 9]
    assert k1['hook_mode'] == 'length' and k1['hook_value'] == 6.5
    assert k1['daf'] == 1.25 and k1['allowance'] == pytest.approx(0.08)
    assert k1['wll_kN'] == 30.0 and k1['sizes'] == (8.0, 10.0)
    # a blank or nonsense row takes the defaults, a row with no code is
    # skipped
    back = slc.read_crane_rows([{'code': 'K2', 'hook_mode': 'sideways',
                                 'daf': 'x'}, {'code': None}])
    assert list(back) == ['K2']
    assert back['K2']['hook_mode'] == 'auto' and back['K2']['daf'] == 1.0


def test_the_lift_rods_rows():
    nodes, members, picks, hook, lift = _lifted()
    s = slc.solve_lift(nodes, members, lift)
    rows = slc.lift_rod_rows(nodes, members, [s], {0: 'Top'})
    assert len(rows) == len(lift['rods'])
    assert rows[0][:3] == ['K1', 0, 'Top']
    assert rows[0][3] == pytest.approx(s['member_res'][0]['N'])
