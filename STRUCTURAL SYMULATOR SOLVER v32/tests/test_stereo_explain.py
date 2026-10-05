"""'Explain this rod': a rod's code check written out as a hand calculation.

Every explanation has to land on the number the check itself produced --
an explanation that ends somewhere else is worse than none -- and the
timber pages are held to the Manual de Aplicación CIRSOC 601's own worked
examples, step by step.
"""
import math

import pytest

from apps.stereo import stereo_explain as sx
from apps.stereo import stereo_checks as sc
from apps.stereo import stereo_math as sm
from apps.stereo import stereo_profiles as sp
from apps.stereo import stereo_timber as stt


def _steel(**kw):
    m = {'a': 0, 'b': 1, 'conn': 'pin', 'E': 200.0, 'A': 20.0, 'I': 400.0,
         'J': 400.0, 'Fy': 235.0, 'Fu': 360.0, 'K': 1.0, 'r_gyr': 3.0}
    m.update(kw)
    return m


def _step(expl, title):
    hits = [s for s in expl['steps'] if s['title'] == title]
    assert hits, [s['title'] for s in expl['steps']]
    return hits[0]


def _num(text):
    return float(text.split()[0].replace(',', ''))


def test_a_steel_tie_is_sigma_over_phi_fy():
    m = _steel(_length_m=2.0)
    chk = sc.check_member(m, 100.0)
    e = sx.explain(m, 100.0, chk)
    assert _num(_step(e, 'Axial stress')['result']) == pytest.approx(50.0)
    assert _step(e, 'Design stress')['ref'] == 'H.3.4'
    assert _num(_step(e, 'Tension ratio')['result']) == pytest.approx(
        chk['util'], abs=5e-4)
    assert e['util'] == chk['util'] and 'OK' in e['verdict']


@pytest.mark.parametrize('L, branch, ref', [(2.0, 'inelastic', 'E3-2'),
                                            (5.0, 'elastic', 'E3-3')])
def test_a_steel_strut_takes_the_right_buckling_branch(L, branch, ref):
    m = _steel(_length_m=L)
    chk = sc.check_member(m, -150.0)
    e = sx.explain(m, -150.0, chk)
    assert _num(_step(e, 'Slenderness')['result']) == pytest.approx(
        L * 1000 / 30.0, abs=0.05)
    assert _step(e, 'Which branch')['result'] == branch
    assert _step(e, 'Critical stress')['ref'] == ref
    assert _num(_step(e, 'Critical stress')['result']) == pytest.approx(
        chk['Fcr_MPa'], abs=0.005)
    assert _num(_step(e, 'Design strength')['result']) == pytest.approx(
        chk['Pd_kN'], abs=0.005)
    assert _num(_step(e, 'Compression ratio')['result']) == pytest.approx(
        chk['util'], abs=5e-4)


def test_a_rigid_steel_rod_shows_the_h1_interaction():
    nodes = [(0, 0, 0), (1.5, 0, 0), (3, 0, 0)]
    mem = [_steel(a=0, b=1, conn='rigid'), _steel(a=1, b=2, conn='rigid')]
    sup = [{'node': 0, 'dofs': {'ux': True, 'uy': True, 'uz': True,
                                'rx': True}},
           {'node': 2, 'dofs': {'uy': True, 'uz': True, 'rx': True}}]
    res, err = sm.analyze(nodes, mem, [{'node': 1, 'fz': -5.0},
                                       {'node': 2, 'fx': -40.0}], sup)
    assert err is None
    mr = res['member_res'][0]
    m = dict(mem[0], _length_m=1.5)
    chk = sc.check_member(m, mr['N'], member_res=mr)
    e = sx.explain(m, mr['N'], chk, mr)
    h1 = _step(e, 'Axial + bending')
    assert h1['ref'] == 'H1-1b'
    assert _num(h1['result']) == pytest.approx(chk['util_interaction'],
                                               abs=5e-4)
    assert _num(_step(e, 'Bending capacity')['result']) == pytest.approx(
        chk['M_capacity_kNm'], abs=5e-4)
    assert _num(e['steps'][-1]['result']) == pytest.approx(chk['util'],
                                                           abs=5e-4)


def test_the_manual_M4E2_strut_page():
    """Pino taeda tablas C1, 25 × 100, l = 0.65 m, −12.5 kN, CD = 1.6: the
    Manual's FcE 5.4, Fc* 9.0, CP 0.5, F'c 4.5 < fc 5.0."""
    m = _steel()
    sp.write_section(m, stt.profile('Pino taeda tablas C1', 25, 100))
    m['_length_m'] = 0.65
    chk = sc.check_member(m, -12.5, timber={'duration': '10min'})
    e = sx.explain(m, -12.5, chk)
    assert 'CIRSOC 601' in e['heading']
    assert _num(_step(e, 'Compression stress')['result']) == pytest.approx(5.0)
    assert _num(_step(e, 'Slenderness')['result']) == pytest.approx(26.0)
    assert _num(_step(e, 'Buckling stress')['result']) == pytest.approx(
        5.4, abs=0.06)
    assert _num(_step(e, 'Value before stability')['result']) == \
        pytest.approx(9.0, abs=0.05)
    cp = _step(e, 'Column stability factor')
    assert cp['ref'] == '3.3.1-1' and _num(cp['result']) == pytest.approx(
        0.5, abs=0.01)
    assert _num(_step(e, 'Adjusted design value')['result']) == \
        pytest.approx(4.5, abs=0.05)
    assert 'OVER CAPACITY' in e['verdict']


def test_the_manual_M4E3_chord_page():
    """Pino paraná aserrada C1, 50 × 125, T 35.6 kN, P 1.5 kN mid-span:
    ft 5.7, fb 3.5, F't 10.5, F*b 17.6, 3.5.1-1 = 0.74."""
    nodes = [(0.6 * k, 0.0, 0.0) for k in range(3)]
    mem = []
    for k in range(2):
        m = {'a': k, 'b': k + 1, 'conn': 'rigid'}
        sp.write_section(m, stt.profile('Pino paraná aserrada C1', 50, 125))
        mem.append(m)
    sup = [{'node': 0, 'dofs': {'ux': True, 'uy': True, 'uz': True,
                                'rx': True}},
           {'node': 2, 'dofs': {'uy': True, 'uz': True, 'rx': True}}]
    res, err = sm.analyze(nodes, mem, [{'node': 1, 'fz': -1.5},
                                       {'node': 2, 'fx': 35.6}], sup)
    assert err is None
    mr = res['member_res'][0]
    m = dict(mem[0], _length_m=0.6)
    chk = stt.member_check(m, mr['N'], mr, {'duration': '10min'})
    e = sx.explain(m, mr['N'], chk, mr)
    assert _num(_step(e, 'Tension stress')['result']) == pytest.approx(
        5.7, abs=0.05)
    assert _num(_step(e, 'Bending stress, axis 1')['result']) == \
        pytest.approx(3.5, abs=0.05)
    assert _num(_step(e, 'Value before stability, axis 1')['result']) == \
        pytest.approx(17.6, abs=0.05)
    combined = [s for s in e['steps'] if s['title'] == 'Combined']
    assert combined[0]['formula'] == 'bending + tension (3.5.1-1)'
    assert _num(combined[0]['result']) == pytest.approx(0.74, abs=0.005)


def test_a_rod_without_a_check_says_why():
    m = {'a': 0, 'b': 1, 'conn': 'pin', 'E': 200.0, 'A': 0.0}
    chk = sc.check_member(m, 10.0)
    e = sx.explain(m, 10.0, chk)
    assert e['steps'] == [] and e['util'] is None
    assert e['verdict'] == chk['note']
    assert 'no code check' in sx.as_text(e)


def test_an_unloaded_timber_rod_is_not_a_calculation():
    m = _steel()
    sp.write_section(m, stt.profile('Pino taeda tablas C1', 25, 100))
    m['_length_m'] = 1.0
    chk = sc.check_member(m, 0.0)
    e = sx.explain(m, 0.0, chk)
    assert e['steps'] == [] and 'carries nothing' in e['heading']


def test_the_page_numbers_each_step_with_its_article():
    m = _steel(_length_m=2.0)
    chk = sc.check_member(m, -150.0)
    page = sx.as_text(sx.explain(m, -150.0, chk), title='Rod 3')
    assert page.startswith('Rod 3\n=====')
    assert ' 4. Critical stress  [E3-2]' in page
    assert 'Fcr = 0.658^(Fy/Fe) · Fy' in page
    assert page.rstrip().endswith('OK')
