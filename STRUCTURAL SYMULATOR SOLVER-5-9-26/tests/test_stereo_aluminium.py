"""Aluminium rods to the Reglamento CIRSOC 701 (apps/stereo/stereo_aluminium).

Expected values are worked by hand from the Reglamento's own formulas and
tables (Tables A.2-1, C.1-1, C.2-2; C.3, C.4.1, C.4.6, C.4.9, C.5, D.1).
"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.stereo import stereo_aluminium as sa
from apps.stereo import stereo_profiles as sp

A6061 = '6061-T6 extrusions (all)'
A6063 = '6063-T6 extrusions and pipe (all)'


def _bc(key=A6061):
    al = sa.ALLOYS[key]
    return al, sa.buckling_constants(al['Fyc'], al['Fyt'], al['Fyt'], al['E'],
                                     sa.artificially_aged(al['alloy']))


def _rod(profile, L=2.0):
    m = {'a': 0, 'b': 1, 'conn': 'pin', 'E': 200.0, 'A': 10.0, 'I': 100.0,
         'J': 100.0, 'Fy': 235.0, 'Fu': 360.0, 'K': 1.0, 'r_gyr': 2.0}
    sp.write_section(m, profile)
    m['_length_m'] = L
    return m


def test_table_a21_values_and_the_deformation_modulus():
    al = sa.ALLOYS[A6061]
    assert (al['Fut'], al['Fyt'], al['Fyc'], al['E']) == (260, 240, 240, 69600)
    assert sa.ALLOYS['7005-T53 extrusions (up to 20 mm)']['E'] == 72400
    p = sa.profile(A6061, 'tube', {'D': 50, 't': 3})
    assert p['E'] == pytest.approx((69600 - 700) / 1000)      # note 2
    assert 'Fy' not in p and p['aluminium'] == A6061
    assert sa.parse_section(p['al_section']) == ('tube', {'D': 50.0, 't': 3.0})


def test_table_c22_buckling_constants_for_6061_t6():
    al, bc = _bc()
    Bc = 240 * (1 + math.sqrt(240 / 15510))
    Dc = Bc / 10 * math.sqrt(Bc / 69600)
    assert bc['Bc'] == pytest.approx(Bc) and bc['Bc'] == pytest.approx(269.85, abs=0.01)
    assert bc['Dc'] == pytest.approx(Dc)
    assert bc['Cc'] == pytest.approx(0.41 * Bc / Dc)
    assert sa.artificially_aged('6061-T6') and not sa.artificially_aged('5083-H116')


def test_global_buckling_follows_c41_and_tends_to_euler():
    al, bc = _bc()
    # stocky: phi_cc Fyc with phi_cc = 1 - 0.21 lambda_c capped at 0.95
    f, lam, phi, eq = sa.global_buckling_stress(10, al, bc)
    assert (eq, phi) == ('C.4.1-1', 0.95) and f == pytest.approx(0.95 * 240)
    # slender: phi_cc Fyc / lambda^2 == phi_cc pi^2 E / (kL/r)^2
    f, lam, phi, eq = sa.global_buckling_stress(150, al, bc)
    assert eq == 'C.4.1-3'
    assert f == pytest.approx(phi * math.pi ** 2 * 69600 / 150 ** 2)
    # monotonic in the slenderness
    vals = [sa.global_buckling_stress(k, al, bc)[0] for k in range(5, 200, 5)]
    assert all(a >= b - 1e-9 for a, b in zip(vals, vals[1:]))


def test_tension_takes_the_lesser_of_yield_and_rupture():
    p = sa.profile(A6061, 'tube', {'D': 50, 't': 3})
    Pd, eq = sa.tension_strength(p, sa.ALLOYS[A6061])
    assert eq.startswith('C.3-2')                # 0.85*260 < 0.95*240
    assert Pd == pytest.approx(0.85 * 260 * p['A'] / 10)
    p = sa.profile(A6063, 'tube', {'D': 50, 't': 3})
    Pd, eq = sa.tension_strength(p, sa.ALLOYS[A6063])
    assert eq.startswith('C.3-1')                # 0.95*170 < 0.85*205
    assert Pd == pytest.approx(0.95 * 170 * p['A'] / 10)


def test_thin_walls_buckle_locally_before_the_member():
    """A 100x100x1.5 tube: b/t = 64.7 is past S2 of C.4.6, so the walls
    carry less than the member's global stress."""
    al, bc = _bc()
    f, eq, S1, S2 = sa.flat_wall_compression(97 / 1.5, al, bc)
    assert eq == 'C.4.6-3' and 97 / 1.5 > S2
    assert f == pytest.approx(0.85 * 2.27 * math.sqrt(bc['Bp'] * 69600) / (1.6 * 97 / 1.5))
    m = _rod(sa.profile(A6061, 'rhs', {'B': 100, 'H': 100, 't': 1.5}), L=1.0)
    chk = sa.member_check(m, -40.0)
    assert chk['phiFnp'] < chk['phiFng']
    assert chk['phiFnp'] == pytest.approx(f, rel=0.05)   # corners carry phiFng
    assert 'C.4.6-3' in chk['governing']


def test_round_tube_walls_follow_c49():
    al, bc = _bc()
    f1, eq1, S1, S2 = sa.tube_wall_compression(5.0, al, bc)
    assert eq1 == 'C.4.9-1' and f1 == pytest.approx(0.95 * 240)
    # S2 is where the inelastic and elastic expressions meet
    inel = 0.85 * (bc['Bt'] - bc['Dt'] * math.sqrt(S2))
    elas = 0.85 * math.pi ** 2 * 69600 / (16 * S2 * (1 + math.sqrt(S2) / 35) ** 2)
    assert inel == pytest.approx(elas, rel=1e-6)


def test_compression_utilisation_and_slenderness_limit():
    p = sa.profile(A6061, 'tube', {'D': 50, 't': 3})
    short = sa.member_check(_rod(p, 0.5), -50.0)
    long_ = sa.member_check(_rod(p, 3.0), -50.0)
    assert short['ok'] and not long_['ok']
    assert long_['util'] > short['util']
    too_long = sa.member_check(_rod(p, 4.0), -1.0)
    assert any('200' in k for k in too_long['ratios'])


def test_bending_strength_by_shape():
    al, bc = _bc()
    bar = sa.section('bar', {'D': 20})
    m = dict(bar, al_shape='bar', al_dims={'D': 20})
    Mn, eq = sa.bending_strength(m, al, bc)
    assert Mn == pytest.approx(min(1.3 * 0.95 * 240, 1.42 * 0.85 * 260) * bar['S'] / 1e3)
    sq = sa.section('rhs', {'B': 80, 'H': 80, 't': 4})
    m = dict(sq, al_shape='rhs', al_dims={'B': 80, 'H': 80, 't': 4})
    _, eq_sq = sa.bending_strength(m, al, bc, 'strong', 500)
    assert not eq_sq.startswith('C.5.2.5')        # C.5.2: no LTB for square tubes
    tube = sa.section('tube', {'D': 60, 't': 2})
    m = dict(tube, al_shape='tube', al_dims={'D': 60, 't': 2})
    Mt, eq_t = sa.bending_strength(m, al, bc)
    assert eq_t.startswith('C.5')


def test_combined_compression_and_bending_adds_the_ratios():
    """D.1.2-1 with a rigid rod's moment from the solver's own diagram."""
    from apps.stereo import stereo_math as sm
    p = sa.profile(A6061, 'tube', {'D': 60, 't': 3})
    m = _rod(p, 2.0)
    m['conn'] = 'rigid'
    nodes = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    sup = [{'node': 0, 'type': 'fixed'}]
    res, err = sm.analyze(nodes, [m], [{'node': 1, 'fx': -20.0, 'fz': -0.5}], sup)
    assert not err
    chk = sa.member_check(m, res['member_res'][0]['N'], res['member_res'][0])
    assert chk['mode'] == 'compression + bending'
    r = chk['ratios']
    comp = next(v for k, v in r.items() if k.startswith('compression ('))
    bend = next(v for k, v in r.items() if k.startswith('bending'))
    assert r['compression + bending (D.1.2-1)'] == pytest.approx(comp + bend)
    assert any('D.3' in p for p in chk['partial'])


def test_the_steel_check_hands_aluminium_rods_over():
    from apps.stereo import stereo_checks as sc
    m = _rod(sa.profile(A6061, 'tube', {'D': 50, 't': 3}), 1.0)
    chk = sc.check_member(m, -30.0)
    assert chk['material'] == 'aluminium' and chk['alloy'] == A6061


def test_a_steel_section_over_an_aluminium_rod_makes_it_steel_again():
    m = _rod(sa.profile(A6061, 'tube', {'D': 50, 't': 3}))
    assert m['aluminium'] and 'Fy' not in m
    sp.put_steel_section(m, sp.CATALOG[next(iter(sp.CATALOG))])
    assert 'aluminium' not in m and 'al_section' not in m


def test_the_workbook_round_trip_keeps_the_aluminium(tmp_path):
    from apps.stereo import stereo_reports as sr
    nodes = [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0)]
    prof = sa.profile(A6061, 'rhs', {'B': 60, 'H': 100, 't': 3})
    m = _rod(prof)
    m['profile'] = 'AL'
    path = str(tmp_path / 'a.xlsx')
    sr.export_excel(nodes, [m], [], [{'node': 0, 'type': 'pin'}], None, path,
                    profiles={'AL': prof})
    _n, members, _l, _s, profiles = sr.import_excel_model(path)
    got = members[0]
    assert got['aluminium'] == A6061 and got['al_section'] == 'rhs 60x100x3'
    assert 'Fy' not in got
    assert profiles['AL']['al_section'] == 'rhs 60x100x3'
