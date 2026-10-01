"""Timber members from the CIRSOC 601 Supplements (roadmap 4.3, timber half).

The table rows below are transcribed a SECOND time, independently, from the
Supplement's page images (Edición 2020-1): a typo in stereo_timber.GRADES
has to be made twice, the same way, to get through.
"""
import math

import pytest

from apps.stereo import stereo_timber as stt
from apps.stereo import stereo_profiles as sp
from apps.stereo import stereo_checks as sc
from apps.stereo import stereo_math as sm

# key: (Fb, Ft, Fv, Fc⊥, Fc, E, E0,05, Emin, ρ0,05, table)
EXPECTED = {
    'Pino paraná tablas C1': (9.4, 5.6, 0.9, 1.0, 7.2, 14600, 9800, 6200, 460, 'S.1.1.1-1'),
    'Pino paraná tablas C2': (4.4, 2.5, 0.5, 0.9, 5.0, 9900, 6600, 4200, 400, 'S.1.1.1-1'),
    'Pino paraná aserrada C1': (10.6, 6.3, 1.1, 1.0, 7.5, 13300, 8900, 5700, 440, 'S.1.1.1-3'),
    'Pino paraná aserrada C2': (6.6, 4.1, 0.7, 0.8, 6.3, 11400, 7700, 4900, 390, 'S.1.1.1-3'),
    'Pino paraná aserrada C3': (5.0, 3.1, 0.6, 0.8, 5.3, 10000, 6700, 4200, 390, 'S.1.1.1-3'),
    'Eucalipto grandis C1': (9.4, 5.6, 0.9, 1.8, 7.2, 12000, 8100, 5100, 430, 'S.1.1.2-1'),
    'Eucalipto grandis C2': (7.5, 4.4, 0.8, 1.7, 6.6, 10800, 7200, 4600, 430, 'S.1.1.2-1'),
    'Eucalipto grandis C3': (5.6, 3.4, 0.6, 1.5, 5.6, 10000, 6700, 4200, 430, 'S.1.1.2-1'),
    'Pino taeda tablas C1': (5.6, 3.4, 0.6, 0.9, 5.6, 10300, 6900, 4400, 420, 'S.1.1.3-1'),
    'Pino taeda tablas C2': (3.4, 2.2, 0.4, 0.8, 4.6, 6000, 4000, 2600, 390, 'S.1.1.3-1'),
    'Pino taeda aserrada C1': (6.2, 3.7, 0.7, 0.9, 6.0, 7700, 5200, 3300, 420, 'S.1.1.3-3'),
    'Pino taeda aserrada C2': (3.2, 1.9, 0.4, 0.8, 4.5, 6500, 4300, 2700, 390, 'S.1.1.3-3'),
    'Álamo C1': (7.5, 4.4, 0.8, 0.9, 6.6, 8800, 5900, 3700, 400, 'S.1.1.4-1'),
    'Álamo C2': (5.6, 3.4, 0.6, 0.9, 5.6, 7700, 5200, 3300, 400, 'S.1.1.4-1'),
    'Pino ponderosa C1': (5.0, 3.0, 0.6, 0.7, 2.3, 5700, 3900, 2400, 330, 'S.1.1.5-1'),
    'Pino ponderosa C2': (2.8, 1.7, 0.3, 0.7, 1.7, 4200, 2800, 1800, 330, 'S.1.1.5-1'),
    'Laminada pino taeda G1': (6.3, 3.5, 0.7, 0.9, 6.3, 11200, 7500, 4700, 420, 'S.2.1.1-1'),
    'Laminada pino taeda G2': (4.1, 2.3, 0.4, 0.8, 4.1, 6700, 4500, 2800, 390, 'S.2.1.1-1'),
    'Laminada pino paraná G1': (7.5, 4.1, 0.8, 1.0, 7.5, 13400, 9000, 5700, 460, 'S.2.1.1-1'),
    'Laminada pino paraná G2': (6.3, 3.5, 0.7, 0.9, 6.3, 11600, 7800, 4900, 400, 'S.2.1.1-1'),
    'Laminada eucalipto G1': (7.5, 4.1, 0.8, 1.8, 7.5, 13400, 9000, 5700, 430, 'S.2.1.1-1'),
    'Laminada eucalipto G2': (6.6, 3.7, 0.8, 1.7, 6.6, 11600, 7800, 4900, 430, 'S.2.1.1-1'),
    'Laminada álamo G1': (6.3, 3.5, 0.7, 0.9, 6.3, 9400, 6300, 4000, 400, 'S.2.1.1-1'),
    'Laminada álamo G2': (5.6, 3.2, 0.6, 0.9, 5.6, 8500, 5700, 3600, 400, 'S.2.1.1-1'),
    'Poste eucalipto (verde)': (8.8, 5.3, 0.5, 1.1, 4.4, 9500, 6400, 4000, 430, 'S.3.1.1-1'),
}


def test_every_grade_matches_the_supplement():
    assert set(stt.GRADES) == set(EXPECTED)
    for key, want in EXPECTED.items():
        g = stt.GRADES[key]
        got = (g['Fb'], g['Ft'], g['Fv'], g['Fc_perp'], g['Fc'], g['E'],
               g['E005'], g['Emin'], g['rho005'], g['table'])
        assert got == want, key


def test_glulam_carries_its_radial_tension_value():
    assert all(stt.GRADES[k].get('Frt') == 0.1 for k in EXPECTED
               if k.startswith('Laminada'))


def test_a_rectangle():
    s = stt.rectangle(50, 150)
    assert s['A'] == pytest.approx(75.0)                 # cm²
    assert s['I'] == pytest.approx(50 * 150 ** 3 / 12 / 1e4)
    assert s['Iw'] == pytest.approx(150 * 50 ** 3 / 12 / 1e4)
    assert s['c_cm'] == pytest.approx(7.5) and s['cw_cm'] == pytest.approx(2.5)
    assert s['r_gyr'] == pytest.approx(5.0 / math.sqrt(12))
    # a square's torsion constant: 0.1406 a⁴ (Roark)
    assert stt.rectangle(100, 100)['J'] == pytest.approx(0.1406 * 100 ** 4 / 1e4,
                                                         rel=2e-3)


def test_a_pole():
    s = stt.circle(200)
    assert s['A'] == pytest.approx(math.pi * 100 ** 2 / 100)
    assert s['I'] == s['Iw'] and s['J'] == pytest.approx(2 * s['I'])
    assert s['r_gyr'] == pytest.approx(5.0)


def test_a_profile_is_timber_and_has_no_steel_strength():
    p = stt.profile('Eucalipto grandis C1', 50, 150)
    assert p['E'] == pytest.approx(12.0)                 # GPa
    assert p['timber'] == 'Eucalipto grandis C1'
    assert 'Fy' not in p and 'Fu' not in p
    assert p['gamma_kN_m3'] == pytest.approx(430 * 9.80665 / 1000)
    assert stt.profile('Álamo C1', 50, 100, unit_weight=6.0)['gamma_kN_m3'] == 6.0


def _rod(**kw):
    m = {'a': 0, 'b': 1, 'conn': 'pin', 'E': 200.0, 'A': 20.0, 'I': 400.0,
         'J': 400.0, 'Fy': 235.0, 'Fu': 360.0, 'K': 1.0, 'r_gyr': 3.0}
    m.update(kw)
    return m


def test_writing_timber_over_steel_and_back():
    m = _rod()
    sp.write_section(m, stt.profile('Pino taeda aserrada C1', 50, 150))
    assert m['timber'] == 'Pino taeda aserrada C1'
    assert 'Fy' not in m and 'Fu' not in m
    sp.write_section(m, {'E': 200.0, 'A': 10.0, 'I': 100.0, 'J': 100.0,
                         'Fy': 235.0, 'Fu': 360.0, 'r_gyr': 2.0, 'K': 1.0})
    assert 'timber' not in m and 'gamma_kN_m3' not in m
    assert m['Fy'] == 235.0


def test_a_steel_catalog_section_makes_a_timber_rod_steel():
    m = _rod()
    sp.write_section(m, stt.profile('Álamo C2', 50, 100))
    sc.apply_recommendation([m], [0], 'IPE 200')
    assert 'timber' not in m and 'gamma_kN_m3' not in m
    assert m['Fy'] == sp.STEEL_F24.Fy and m['E'] == pytest.approx(200.0)


def test_a_timber_rod_is_not_checked_to_cirsoc_301():
    m = _rod()
    sp.write_section(m, stt.profile('Eucalipto grandis C1', 50, 150))
    m['_length_m'] = 3.0
    chk = sc.check_member(m, 15.0)            # 15 kN tension on 7500 mm²
    assert chk['checked'] is False and chk['util'] is None
    assert chk['stresses_MPa']['ft'] == pytest.approx(2.0)
    assert chk['ratios']['ft'] == pytest.approx(2.0 / 5.6)
    assert 'NOT a CIRSOC 601 verification' in chk['note']
    assert 'S.1.1.2-1' in chk['note']


def test_compression_reports_slenderness_over_the_least_dimension():
    m = _rod()
    sp.write_section(m, stt.profile('Eucalipto grandis C1', 50, 150))
    m['_length_m'] = 2.0
    chk = sc.check_member(m, -15.0)
    assert chk['mode'] == 'compression'
    assert chk['slenderness'] == pytest.approx(2000 / 50)
    assert 'buckling not applied' in chk['note']
    pole = _rod()
    sp.write_section(pole, stt.profile('Poste eucalipto (verde)', 200))
    pole['_length_m'] = 4.0
    assert sc.check_member(pole, -10.0)['slenderness'] == pytest.approx(20.0)


def test_a_timber_rod_weighs_its_own_density():
    nodes = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)]
    m = _rod()
    sp.write_section(m, stt.profile('Eucalipto grandis C1', 50, 150))
    w = -sum(ld['fz'] for ld in sm.self_weight_loads(nodes, [m]))
    assert w == pytest.approx(75e-4 * 4.0 * 430 * 9.80665 / 1000)
    steel = _rod(A=10.0)
    w2 = -sum(ld['fz'] for ld in sm.self_weight_loads(nodes, [steel], 78.5))
    assert w2 == pytest.approx(10e-4 * 4.0 * 78.5)


def test_the_solver_uses_the_grade_E():
    nodes = [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0)]
    m = _rod()
    sp.write_section(m, stt.profile('Álamo C1', 100, 100))
    sup = [{'node': 0, 'type': 'fixed'},
           {'node': 1, 'dofs': {'ux': False, 'uy': True, 'uz': True,
                                'rx': True, 'ry': True, 'rz': True}}]
    res, err = sm.analyze(nodes, [m], [{'node': 1, 'fx': 10.0}], sup)
    assert not err
    # PL / EA in mm: 10 kN, 3 m, E 8800 MPa, A 10000 mm²
    assert res['node_res'][1]['ux'] == pytest.approx(
        10e3 * 3000 / (8800 * 1e4), rel=1e-6)


def test_the_workbook_round_trip_keeps_the_timber(tmp_path):
    from apps.stereo import stereo_reports as sr
    nodes = [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0)]
    m = _rod()
    prof = stt.profile('Laminada eucalipto G1', 90, 300, unit_weight=5.5)
    sp.write_section(m, prof)
    m['profile'] = 'GL'
    path = str(tmp_path / 't.xlsx')
    sr.export_excel(nodes, [m], [], [{'node': 0, 'type': 'pin'}], None, path,
                    profiles={'GL': prof})
    _n, members, _l, _s, profiles = sr.import_excel_model(path)
    got = members[0]
    assert got['timber'] == 'Laminada eucalipto G1'
    assert got['gamma_kN_m3'] == pytest.approx(5.5)
    assert 'Fy' not in got and 'Fu' not in got
    assert profiles['GL']['timber'] == 'Laminada eucalipto G1'
    assert profiles['GL']['gamma_kN_m3'] == pytest.approx(5.5)


def test_rebuilding_a_section_from_typed_fields_keeps_it_timber():
    values = {'E': 12.0, 'A': 75.0, 'I': 1406.0, 'J': 100.0, 'Fy': 235.0,
              'Fu': 360.0, 'K': 1.0, 'r_gyr': 1.44}
    sp.keep_timber(values, {'timber': 'Álamo C1', 'gamma_kN_m3': 3.9})
    assert values['timber'] == 'Álamo C1' and 'Fy' not in values
    plain = {'E': 200.0, 'Fy': 235.0}
    sp.keep_timber(plain, None)
    assert plain == {'E': 200.0, 'Fy': 235.0}
