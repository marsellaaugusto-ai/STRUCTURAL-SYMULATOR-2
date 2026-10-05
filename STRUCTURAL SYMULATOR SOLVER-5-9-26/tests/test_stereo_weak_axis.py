"""Rigid frames bend two ways: the weak axis gets its own stiffness and its
own capacity (backlog: "rigid frames treat Iy = Iz").

Checked against the cantilever by hand: a tip load P on a length L deflects
P L^3 / (3 E I), with I the second moment about the axis it bends.
"""
import math

import pytest

from apps.stereo import stereo_math as sm
from apps.stereo import stereo_checks as sk
from apps.stereo import stereo_profiles as sp

L = 3.0          # m
P = 1.0          # kN


def _ipe_member(a, b, **kw):
    m = dict(a=a, b=b, conn='rigid', E=200.0, Fy=235.0, Fu=360.0, K=1.0,
             profile='IPE 200')
    m.update(sp.section_to_props(sp.CATALOG['IPE 200']))
    m.update(kw)
    return m


def _tip(members, nodes, load):
    supports = [{'node': 0, 'type': 'fixed'}]
    res, err = sm.analyze(nodes, members, [dict(node=1, **load)], supports)
    assert err is None, err
    return res['node_res'][1]


def _cantilever_deflection_mm(I_cm4):
    E = 200e9
    return P * 1e3 * L ** 3 / (3.0 * E * I_cm4 * 1e-8) * 1e3


# ── the catalog carries the weak axis ─────────────────────────────────────

def test_every_catalog_section_has_a_weak_axis():
    for name, sec in sp.CATALOG.items():
        p = sp.section_to_props(sec)
        assert p['Iw'] > 0 and p['cw_cm'] > 0, name
        assert p['Iw'] <= p['I'] + 1e-9, name


def test_an_ipe_is_much_weaker_sideways_and_a_tube_is_not():
    ipe = sp.section_to_props(sp.CATALOG['IPE 200'])
    chs = sp.section_to_props(sp.CATALOG['CHS 76.1x3.6'])
    assert ipe['I'] / ipe['Iw'] == pytest.approx(13.0, abs=0.2)
    assert chs['I'] == pytest.approx(chs['Iw'])


def test_typing_another_section_over_a_catalog_one_drops_its_weak_axis():
    m = {}
    sp.write_section(m, sp.section_to_props(sp.CATALOG['IPE 200']))
    assert 'Iw' in m and 'cw_cm' in m
    sp.write_section(m, dict(A=30.0, I=900.0, r_gyr=4.0))
    assert 'Iw' not in m and 'cw_cm' not in m and 'c_cm' not in m


# ── the stiffness ─────────────────────────────────────────────────────────

def test_a_horizontal_beam_bends_its_strong_axis_under_gravity():
    nodes = [(0.0, 0.0, 0.0), (L, 0.0, 0.0)]
    m = _ipe_member(0, 1)
    uz = abs(_tip([m], nodes, {'fz': -P})['uz'])
    assert uz == pytest.approx(_cantilever_deflection_mm(m['I']), rel=1e-6)


def test_and_its_weak_axis_under_a_sideways_load():
    nodes = [(0.0, 0.0, 0.0), (L, 0.0, 0.0)]
    m = _ipe_member(0, 1)
    uy = abs(_tip([m], nodes, {'fy': P})['uy'])
    assert uy == pytest.approx(_cantilever_deflection_mm(m['Iw']), rel=1e-6)
    uz = abs(_tip([m], nodes, {'fz': -P})['uz'])
    assert uy / uz == pytest.approx(m['I'] / m['Iw'], rel=1e-6)


def test_a_column_bends_its_strong_axis_towards_global_y():
    """The documented orientation for a vertical member: local z = global Y,
    so a push in Y bends the strong axis and a push in X the weak one."""
    nodes = [(0.0, 0.0, 0.0), (0.0, 0.0, L)]
    m = _ipe_member(0, 1)
    uy = abs(_tip([m], nodes, {'fy': P})['uy'])
    ux = abs(_tip([m], nodes, {'fx': P})['ux'])
    assert uy == pytest.approx(_cantilever_deflection_mm(m['I']), rel=1e-6)
    assert ux == pytest.approx(_cantilever_deflection_mm(m['Iw']), rel=1e-6)


def test_a_hand_typed_section_stays_doubly_symmetric():
    nodes = [(0.0, 0.0, 0.0), (L, 0.0, 0.0)]
    m = dict(a=0, b=1, conn='rigid', E=200.0, A=20.0, I=400.0, J=400.0,
             Fy=235.0, Fu=360.0, K=1.0, r_gyr=3.0)
    uy = abs(_tip([m], nodes, {'fy': P})['uy'])
    uz = abs(_tip([m], nodes, {'fz': -P})['uz'])
    assert uy == pytest.approx(uz, rel=1e-9)


# ── the check ─────────────────────────────────────────────────────────────

def _check_with(My=0.0, Mz=0.0):
    m = _ipe_member(0, 1, _length_m=L)
    mr = {'conn': 'rigid', 'N': 0.0, 'length_m': L, 'T': 0.0,
          'My_a': My, 'My_b': -My, 'Mz_a': Mz, 'Mz_b': -Mz,
          'Vy_a': 0.0, 'Vz_a': 0.0, 'w_local': (0.0, 0.0, 0.0)}
    return sk.check_member(m, 0.0, member_res=mr)


def test_weak_axis_moment_is_checked_against_the_weak_capacity():
    strong = _check_with(My=5.0)
    weak = _check_with(Mz=5.0)
    m = _ipe_member(0, 1)
    Sx, Sw = m['I'] / m['c_cm'], m['Iw'] / m['cw_cm']
    assert weak['util_interaction'] / strong['util_interaction'] == \
        pytest.approx(Sx / Sw, rel=1e-6)
    assert weak['M_capacity_weak_kNm'] < weak['M_capacity_kNm']


# ── the weak axis survives the round trip, and nothing else ──────────────

def test_the_workbook_carries_the_weak_axis_both_ways(tmp_path):
    from apps.stereo import stereo_reports as sr
    nodes = [(0.0, 0.0, 0.0), (L, 0.0, 0.0)]
    m = _ipe_member(0, 1)
    path = str(tmp_path / 'w.xlsx')
    sr.export_excel(nodes, [m], [], [{'node': 0, 'type': 'fixed'}], None, path)
    got = sr.import_excel_model(path)[1][0]
    assert got['Iw'] == pytest.approx(m['Iw'])
    assert got['cw_cm'] == pytest.approx(m['cw_cm'])


def test_an_older_workbook_without_the_columns_still_loads(tmp_path):
    import openpyxl
    from apps.stereo import stereo_reports as sr
    nodes = [(0.0, 0.0, 0.0), (L, 0.0, 0.0)]
    path = str(tmp_path / 'old.xlsx')
    sr.export_excel(nodes, [_ipe_member(0, 1)], [], [], None, path)
    wb = openpyxl.load_workbook(path)
    ws = wb['Model']
    for row in ws.iter_rows():
        for c in row:
            if c.value in ('Iw_cm4', 'cw_cm'):
                c.value = None
    wb.save(path)
    got = sr.import_excel_model(path)[1][0]
    assert 'Iw' not in got, 'then the rod is simply doubly symmetric again'
