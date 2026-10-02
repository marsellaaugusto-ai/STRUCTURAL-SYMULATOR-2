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


def test_a_timber_rod_is_checked_to_cirsoc_601_not_301():
    m = _rod()
    sp.write_section(m, stt.profile('Eucalipto grandis C1', 50, 150))
    m['_length_m'] = 3.0
    chk = sc.check_member(m, 15.0)            # 15 kN tension on 7500 mm²
    assert chk['checked'] is True and chk['code'] == stt.REGLAMENTO
    assert chk['stresses_MPa']['ft'] == pytest.approx(2.0)
    # F't = Ft CD CM Ct CF, CF = (150/150)^0.2 = 1
    assert chk['design_MPa']['Ft'] == pytest.approx(5.6)
    assert chk['util'] == pytest.approx(2.0 / 5.6)
    assert chk['governing'] == 'tension ∥ (3.4.1)'
    assert 'service' in chk['note']


def test_compression_reports_slenderness_over_the_least_dimension():
    m = _rod()
    sp.write_section(m, stt.profile('Eucalipto grandis C1', 50, 150))
    m['_length_m'] = 2.0
    chk = sc.check_member(m, -15.0)
    assert chk['mode'] == 'compression'
    assert chk['slenderness'] == pytest.approx(2000 / 50)
    assert 0 < chk['factors']['CP'] < 1
    pole = _rod()
    sp.write_section(pole, stt.profile('Poste eucalipto (verde)', 200))
    pole['_length_m'] = 4.0
    # art. 3.3.1: a round member buckles as the square of equal area
    side = math.sqrt(math.pi * 200 ** 2 / 4)
    assert sc.check_member(pole, -10.0)['slenderness'] == pytest.approx(
        4000 / side)


# ── the Manual de Aplicación's worked examples ────────────────────────────
#
# Each figure the Manual prints is checked, to the Manual's own rounding.

def _beam(grade, b, h, L, nseg):
    nodes = [(L * k / nseg, 0.0, 0.0) for k in range(nseg + 1)]
    members = []
    for k in range(nseg):
        m = {'a': k, 'b': k + 1, 'conn': 'rigid'}
        sp.write_section(m, stt.profile(grade, b, h))
        members.append(m)
    sup = [{'node': 0, 'dofs': {'ux': True, 'uy': True, 'uz': True,
                                'rx': True}},
           {'node': nseg, 'dofs': {'uy': True, 'uz': True, 'rx': True}}]
    return nodes, members, sup


def test_manual_M4E1_a_floor_beam_in_bending():
    """Eucalipto grandis C2, 50 × 150, l = 2.6 m, D + L = 1.7 kN/m, braced
    at its ends and middle, load sharing (Cr = 1.1): fb 7.7 ≤ F'b 8.1,
    RB 12.4, FbE 35.9, CL 0.98; fv 0.4 ≤ F'v 0.8."""
    n, m, s = _beam('Eucalipto grandis C2', 50, 150, 2.6, 2)
    res, err = sm.analyze(n, m, [], s, member_loads=[
        {'member': i, 'w': 1.7, 'dir': (0, 0, -1)} for i in range(2)])
    assert err is None
    chk = stt.member_check(dict(m[0], _length_m=1.3), res['member_res'][0]['N'],
                           res['member_res'][0], {'load_sharing': True})
    assert chk['mode'] == 'bending'
    assert chk['stresses_MPa']['fb1'] == pytest.approx(7.7, abs=0.05)
    assert chk['design_MPa']['Fb*1'] == pytest.approx(7.5 * 1.1)  # "8,3"
    assert chk['factors']['CL1'] == pytest.approx(0.98, abs=0.01)
    assert chk['design_MPa']['Fb1'] == pytest.approx(8.1, abs=0.05)
    assert chk['stresses_MPa']['fv'] == pytest.approx(0.4, abs=0.05)
    assert chk['design_MPa']['Fv'] == pytest.approx(0.8)
    assert chk['ok']
    RB = math.sqrt(stt.lateral_buckling_length(1300, 150) * 150 / 50 ** 2)
    assert RB == pytest.approx(12.4, abs=0.05)
    assert 1.2 * 4600 / RB ** 2 == pytest.approx(35.9, abs=0.15)


def test_manual_M4E2_a_truss_diagonal_board():
    """Pino taeda tablas C1, 25 × 100, l = 0.65 m. D + W = −12.5 kN with
    CD = 1.6: FcE 5.4, Fc* 9.0, CP 0.5, F'c 4.5 < fc 5.0 -- it FAILS, as
    the Manual says. D + L = 4.8 kN: CF 1.08, F't 3.7 ≥ ft 1.9."""
    m = _rod()
    sp.write_section(m, stt.profile('Pino taeda tablas C1', 25, 100))
    m['_length_m'] = 0.65
    c = sc.check_member(m, -12.5, timber={'duration': '10min'})
    assert c['stresses_MPa']['fc'] == pytest.approx(5.0)
    assert c['design_MPa']['FcE'] == pytest.approx(5.4, abs=0.05)
    assert c['design_MPa']['Fc*'] == pytest.approx(9.0, abs=0.05)
    assert c['factors']['CP'] == pytest.approx(0.5, abs=0.01)
    assert c['design_MPa']['Fc'] == pytest.approx(4.5, abs=0.05)
    assert c['ok'] is False and c['slenderness'] == pytest.approx(26.0)
    t = sc.check_member(m, 4.8)
    assert t['factors']['CF_t'] == pytest.approx(1.08, abs=0.005)
    assert t['design_MPa']['Ft'] == pytest.approx(3.7, abs=0.05)
    assert t['stresses_MPa']['ft'] == pytest.approx(1.9, abs=0.05)
    assert t['ok']


def test_manual_M4E3_a_chord_in_bending_and_tension():
    """Pino paraná aserrada C1, 50 × 125, l = 1.2 m, T 35.6 kN, P 1.5 kN
    at mid-span, CD = 1.6: ft 5.7, fb 3.5, F't 10.5, F*b 17.6,
    ft/F't + fb/F*b = 0.74 (3.5.1-1); (fb − ft)/F'b < 0 (3.5.1-2)."""
    n, m, s = _beam('Pino paraná aserrada C1', 50, 125, 1.2, 2)
    res, err = sm.analyze(n, m, [{'node': 1, 'fz': -1.5},
                                 {'node': 2, 'fx': 35.6}], s)
    assert err is None
    chk = stt.member_check(dict(m[0], _length_m=0.6),
                           res['member_res'][0]['N'], res['member_res'][0],
                           {'duration': '10min'})
    assert chk['stresses_MPa']['ft'] == pytest.approx(5.7, abs=0.05)
    assert chk['stresses_MPa']['fb1'] == pytest.approx(3.5, abs=0.05)
    assert chk['design_MPa']['Ft'] == pytest.approx(10.5, abs=0.05)
    assert chk['design_MPa']['Fb*1'] == pytest.approx(17.6, abs=0.05)
    assert chk['ratios']['bending + tension (3.5.1-1)'] == pytest.approx(
        0.74, abs=0.005)
    assert chk['ratios']['bending − tension (3.5.1-2)'] == 0.0
    assert chk['governing'] == 'bending + tension (3.5.1-1)'
    # the Manual's CL, with its own le = 1.11 lu, lu = 0.6 m: 0.995
    RB = math.sqrt(670 * 125 / 50 ** 2)          # the Manual: le = 0.67 m
    FbE = 1.2 * 5700 / RB ** 2
    assert RB == pytest.approx(5.8, abs=0.05) and FbE == pytest.approx(
        203, abs=2)
    assert stt.beam_stability_factor(17.6, FbE) == pytest.approx(0.995,
                                                                 abs=0.001)


def test_manual_M5E1_glulam_column_and_volume_factors():
    """Laminada pino paraná G1, 280 × 800, le/d = 26, CD = 1.15: FcE 6.9,
    CP 0.67 (c = 0.9), F'c 5.8; CV = 0.94."""
    FcE = 0.822 * 5700 / 26 ** 2
    assert FcE == pytest.approx(6.9, abs=0.05)
    CP = stt.column_stability_factor(7.5 * 1.15, FcE, stt.C_COLUMN['glulam'])
    assert CP == pytest.approx(0.67, abs=0.005)
    assert 7.5 * 1.15 * CP == pytest.approx(5.8, abs=0.05)
    assert stt.volume_factor(800, 280) == pytest.approx(0.94, abs=0.005)


# ── the factors, one by one ───────────────────────────────────────────────

def test_load_duration_factors_are_table_4_3_2():
    assert [cd for _k, _l, cd in stt.LOAD_DURATIONS] == [
        0.9, 1.0, 1.15, 1.25, 1.6, 2.0]
    assert stt.load_duration_factor() == 1.0
    assert stt.load_duration_factor({'duration': '10min'}) == 1.6


def test_wet_service_factors_are_tables_4_3_3_and_5_3_2():
    sawn = stt.GRADES['Pino paraná aserrada C1']       # Fb 10.6, Fc 7.5
    assert [stt.wet_service_factor(sawn, p) for p in
            ('Fb', 'Ft', 'Fv', 'Fc_perp', 'Fc', 'E', 'Emin')] == [
        0.85, 1.0, 0.97, 0.67, 0.8, 0.9, 0.9]
    weak = stt.GRADES['Pino ponderosa C2']            # Fb 2.8, Fc 1.7
    assert stt.wet_service_factor(weak, 'Fb') == 1.0  # note (1)
    assert stt.wet_service_factor(weak, 'Fc') == 1.0  # note (2)
    glulam = stt.GRADES['Laminada eucalipto G1']
    assert [stt.wet_service_factor(glulam, p) for p in
            ('Fb', 'Ft', 'Fv', 'Fc_perp', 'Fc', 'E')] == [
        0.80, 0.80, 0.87, 0.53, 0.73, 0.83]
    pole = stt.GRADES['Poste eucalipto (verde)']
    assert stt.wet_service_factor(pole, 'Fb') == 1.0  # Tabla 6.3-1: no CM


def test_temperature_factors_are_table_4_3_4():
    assert [stt.temperature_factor('Ft', False, t) for t in
            ('le40', '40to52', '52to65')] == [1.0, 0.9, 0.9]
    assert [stt.temperature_factor('Fb', False, t) for t in
            ('le40', '40to52', '52to65')] == [1.0, 0.8, 0.7]
    assert [stt.temperature_factor('Fc', True, t) for t in
            ('le40', '40to52', '52to65')] == [1.0, 0.7, 0.5]


def test_size_factor_caps_at_1_3():
    assert stt.size_factor(150) == pytest.approx(1.0)
    assert stt.size_factor(10) == pytest.approx(1.3)
    assert stt.size_factor(300) == pytest.approx((150 / 300) ** 0.2)


def test_lateral_buckling_length_is_the_general_case():
    assert stt.lateral_buckling_length(600, 100) == pytest.approx(2.06 * 600)
    assert stt.lateral_buckling_length(1000, 100) == pytest.approx(
        1.63 * 1000 + 300)
    assert stt.lateral_buckling_length(2000, 100) == pytest.approx(
        1.84 * 2000)


def test_a_wet_hot_short_load_case_moves_the_design_value():
    m = _rod()
    sp.write_section(m, stt.profile('Pino paraná aserrada C1', 50, 150))
    m['_length_m'] = 1.0
    base = stt.member_check(m, 10.0)['design_MPa']['Ft']
    wind = stt.member_check(m, 10.0, None, {'duration': '10min'})
    assert wind['design_MPa']['Ft'] == pytest.approx(base * 1.6)
    hot = stt.member_check(m, 10.0, None, {'temperature': '52to65'})
    assert hot['design_MPa']['Ft'] == pytest.approx(base * 0.9)
    assert 'CD 1.6' in wind['note']


def test_a_board_bent_edgewise_is_flagged_outside_its_grade():
    """Supplement 1 gives boards an Fb for flatwise bending only."""
    n, m, s = _beam('Pino taeda tablas C1', 25, 100, 1.0, 1)
    res, err = sm.analyze(n, m, [], s, member_loads=[
        {'member': 0, 'w': 0.5, 'dir': (0, 0, -1)}])
    assert err is None
    chk = stt.member_check(dict(m[0], _length_m=1.0),
                           res['member_res'][0]['N'], res['member_res'][0])
    assert chk['checked'] and chk['partial']
    assert 'flatwise' in chk['partial'][0]


def test_a_slender_strut_past_50_fails_on_slenderness():
    m = _rod()
    sp.write_section(m, stt.profile('Eucalipto grandis C1', 50, 150))
    m['_length_m'] = 3.0                              # le/d = 60
    chk = stt.member_check(m, -0.1)
    assert chk['ratios']['le/d ≤ 50 (3.3.1)'] == pytest.approx(60 / 50)
    assert chk['ok'] is False


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
