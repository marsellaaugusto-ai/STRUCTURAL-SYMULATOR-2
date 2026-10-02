"""The design score: weight, the load carried, and pass or fail."""
import pytest

from apps.stereo import stereo_score as ss
from apps.stereo import stereo_math as sm


def _bar(A=10.0, L=2.0, **kw):
    m = {'a': 0, 'b': 1, 'A': A}
    m.update(kw)
    return [(0, 0, 0), (L, 0, 0)], [m]


def test_a_steel_bar_weighs_its_area_times_length_times_density():
    nodes, mem = _bar(A=10.0, L=2.0)        # 10 cm², 2 m of 78.5 kN/m³
    assert ss.model_mass_kg(nodes, mem, 78.5) == pytest.approx(
        10e-4 * 2.0 * 78.5 * 1000 / 9.80665)
    assert ss.model_mass_kg(nodes, mem, 78.5) == pytest.approx(16.0, abs=0.05)


def test_a_timber_bar_weighs_at_its_own_density():
    nodes, mem = _bar(A=100.0, L=1.0, gamma_kN_m3=5.0)
    assert ss.model_mass_kg(nodes, mem, 78.5) == pytest.approx(
        100e-4 * 5.0 * 1000 / 9.80665)


def _solved(rz, utils):
    results = {'reactions': {0: {'Fz': rz / 2.0}, 1: {'Fz': rz / 2.0}}}
    checks = [{'checked': True, 'util': u} for u in utils]
    return results, checks


def test_without_a_solve_only_the_weight_is_known():
    nodes, mem = _bar()
    sc = ss.score(nodes, mem)
    assert sc['mass_kg'] > 0 and sc['carried_kN'] is None
    assert ss.describe(sc)[0].endswith('▶ Analyze to score it')


def test_it_carries_its_reactions_less_its_own_weight():
    nodes, mem = _bar(A=10.0, L=2.0)
    res, chk = _solved(100.0, [0.4, 0.8])
    sc = ss.score(nodes, mem, res, chk, 78.5, self_weight_on=True)
    own = sc['own_kN']
    assert own == pytest.approx(10e-4 * 2.0 * 78.5)
    assert sc['carried_kN'] == pytest.approx(100.0 - own)
    assert sc['ratio'] == pytest.approx((100.0 - own) / own)
    assert sc['passes'] is True and sc['rod'] == 1 and sc['util'] == 0.8
    sc2 = ss.score(nodes, mem, res, chk, 78.5, self_weight_on=False)
    assert sc2['carried_kN'] == pytest.approx(100.0)


def test_a_failing_design_does_not_score():
    nodes, mem = _bar()
    res, chk = _solved(100.0, [1.3, 0.5, 1.1])
    sc = ss.score(nodes, mem, res, chk)
    assert sc['passes'] is False and sc['n_over'] == 2 and sc['rod'] == 0
    line = ss.describe(sc)[1]
    assert line.startswith('FAILS: rod 0 at 1.30, 2 over')


def test_the_lightest_passing_design_is_named():
    nodes, mem = _bar()
    res, chk = _solved(100.0, [0.5])
    sc = ss.score(nodes, mem, res, chk)
    assert 'Lightest passing design so far' in ss.describe(sc, sc['mass_kg'])[1]
    assert 'Lightest so far: 5 kg' in ss.describe(sc, 5.0)[1]


def test_comparable_designs_share_a_brief():
    a = [(0, 0, 0), (30, 30, 1.5)]
    b = [(0, 0, 0), (30.02, 30, 2.5)]
    assert ss.brief_key(a, 1800.2) == ss.brief_key(b, 1799.9)
    assert ss.brief_key(a, 1800) != ss.brief_key(a, 2400)


def test_heavy_models_read_in_tonnes():
    assert ss.mass_text(4210.0) == '4,210 kg'
    assert ss.mass_text(42100.0) == '42.10 t'
