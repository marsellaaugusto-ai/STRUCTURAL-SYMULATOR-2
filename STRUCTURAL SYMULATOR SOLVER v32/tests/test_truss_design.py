"""CIRSOC 301 rod checks, self-weight and the deflection limit of the Truss
tab (apps/truss/truss_design). The checks must agree with the Stereo tab's
for the same rod, force and section: they are the same code."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import PX_PER_M
from apps.truss import truss_design as td
from apps.truss.truss_math import analyze, compute_diagrams
from apps.stereo import stereo_profiles as sp
from apps.stereo import stereo_checks as sc

CHS = 'CHS 60.3x3.6'


def P(x, y):
    return (x * PX_PER_M, y * PX_PER_M)


def family(name=CHS):
    props = sp.section_to_props(sp.CATALOG[name], sp.STEEL_F24)
    props.update(catalog=name, material=sp.STEEL_F24.name)
    return props


def warren(prof='Default', conn='pin'):
    nodes = [P(0, 0), P(2, 0), P(4, 0), P(1, -1), P(3, -1)]
    fam = family() if prof != 'Default' else {'E': 200.0, 'A': 10.0, 'I': 8000.0}
    rods = [{'a': a, 'b': b, 'E': fam['E'], 'A': fam['A'], 'I': fam['I'],
             'conn': conn, 'udl': 0.0, 'point_loads': [], 'profile': prof}
            for a, b in ((0, 1), (1, 2), (3, 4), (0, 3), (3, 1), (1, 4), (4, 2))]
    sup = [{'node': 0, 'type': 'pin'}, {'node': 2, 'type': 'rollerX'}]
    loads = [{'node': 3, 'fx': 0.0, 'fy': 40.0}, {'node': 4, 'fx': 0.0, 'fy': 40.0}]
    return nodes, rods, sup, loads, {prof: fam}


def test_a_rod_without_a_steel_section_says_what_to_do():
    nodes, rods, sup, loads, profiles = warren()
    res, err = analyze(nodes, rods, loads, sup)
    checks = td.check_rods(nodes, rods, profiles, res)
    assert not checks[0]['checked'] and 'Steel section' in checks[0]['note']


def test_each_rod_gets_the_stereo_tabs_own_verdict():
    nodes, rods, sup, loads, profiles = warren(CHS)
    res, err = analyze(nodes, rods, loads, sup)
    assert err is None
    checks = td.check_rods(nodes, rods, profiles, res)
    for i, (rod, chk) in enumerate(zip(rods, checks)):
        m = td.member_for(nodes, rod, profiles)
        same = sc.check_member(m, res['rod_res'][i]['force'])
        assert chk['util'] == pytest.approx(same['util'])
    top = rods.index(next(r for r in rods if (r['a'], r['b']) == (3, 4)))
    assert checks[top]['mode'] == 'compression'          # the top chord
    i, worst = td.governing(checks)
    assert worst['util'] == max(c['util'] for c in checks)


def test_a_rigid_rod_adds_its_bending_by_h1():
    nodes, rods, sup, loads, profiles = warren(CHS, conn='rigid')
    rods[0]['udl'] = 5.0                                  # bends the bottom chord
    res, err = analyze(nodes, rods, loads, sup)
    assert err is None
    diags = compute_diagrams(nodes, rods, loads, res)
    chk = td.check_rods(nodes, rods, profiles, res, diags)[0]
    assert chk['M_demand_kNm'] > 0 and 'util_interaction' in chk
    assert chk['util'] >= chk['util_axial']
    assert 'bending' in chk['mode']


def test_self_weight_is_the_whole_weight_split_to_the_ends():
    nodes, rods, sup, loads, profiles = warren(CHS)
    sw = td.self_weight_loads(nodes, rods)
    total = sum(r['A'] * 1e-4 * td.rod_length_m(nodes, r) * 78.5 for r in rods)
    assert sum(sw.values()) == pytest.approx(total)
    merged = td.with_self_weight(loads, nodes, rods)
    assert sum(l['fy'] for l in merged) == pytest.approx(80.0 + total)
    assert sum(l['fy'] for l in loads) == pytest.approx(80.0)   # unchanged


def test_the_deflection_is_read_against_span_over_300():
    nodes, rods, sup, loads, profiles = warren(CHS)
    res, err = analyze(nodes, rods, loads, sup)
    d = td.deflection(nodes, sup, res['node_res'])
    assert d['span_m'] == pytest.approx(4.0)
    assert d['limit_mm'] == pytest.approx(4000 / 300)
    assert d['deflection_mm'] == pytest.approx(max(abs(n['uy']) for n in res['node_res']))
    assert d['ok'] == (d['deflection_mm'] <= d['limit_mm'])
