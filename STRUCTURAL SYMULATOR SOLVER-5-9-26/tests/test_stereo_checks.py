"""CIRSOC member-check tests for the Stereo tab (apps/stereo/stereo_checks.py).

Every plain member here gets a real code check -- unlike the Truss tab,
where a rod with no gusset/panel attached is never checked at all (see
HANDOFF_MANIFESTO_2026-09-10.md). These tests pin the tension/compression
dispatch and the sign convention against `cirsoc_301` directly, so a future
change to either side cannot silently disagree about which check governs a
given member.
"""
import pytest

import cirsoc_301 as cirsoc
from apps.stereo import stereo_checks as sc
from apps.stereo import stereo_math as sm
from apps.stereo import stereo_geometry as sg


def test_tension_member_uses_stress_check_and_matches_it_directly():
    member = {'A': 20.0, 'Fy': 250.0, '_length_m': 3.0}   # 20 cm^2
    N_kN = 300.0   # tension
    result = sc.check_member(member, N_kN)
    assert result['checked']
    assert result['mode'] == 'tension'

    A_mm2 = 20.0 * 100.0
    sigma = (N_kN * 1e3) / A_mm2
    expected = cirsoc.stress_check(sigma, 0.0, 250.0)
    assert result['util'] == pytest.approx(expected.util, rel=1e-9)
    assert result['ok'] == (expected.util <= 1.0)


def test_compression_member_uses_compression_strength_and_matches_it_directly():
    member = {'A': 20.0, 'Fy': 250.0, 'r_gyr': 3.0, 'K': 1.0, '_length_m': 4.0}
    N_kN = -150.0   # compression
    result = sc.check_member(member, N_kN)
    assert result['checked']
    assert result['mode'] == 'compression'

    A_mm2 = 20.0 * 100.0
    KL_over_r = (1.0 * 4.0 * 1000.0) / (3.0 * 10.0)
    expected = cirsoc.compression_strength(A_mm2, KL_over_r, 250.0, required=150.0e3)
    assert result['util'] == pytest.approx(expected.util, rel=1e-9)
    assert result['slenderness'] == pytest.approx(KL_over_r, rel=1e-9)


def test_effective_length_factor_changes_the_slenderness():
    base = {'A': 20.0, 'Fy': 250.0, 'r_gyr': 3.0, '_length_m': 4.0}
    r_k1 = sc.check_member(dict(base, K=1.0), -100.0)
    r_k2 = sc.check_member(dict(base, K=2.0), -100.0)
    assert r_k2['slenderness'] == pytest.approx(2 * r_k1['slenderness'], rel=1e-9)
    # a more slender member (larger K*L/r) is never a HIGHER capacity
    assert r_k2['util'] >= r_k1['util']


def test_missing_section_is_reported_not_silently_skipped():
    result = sc.check_member({'A': 0.0, '_length_m': 3.0}, 50.0)
    assert result['checked'] is False
    assert result['util'] is None


def test_compression_member_missing_r_gyr_is_reported():
    result = sc.check_member({'A': 10.0, 'Fy': 250.0, '_length_m': 3.0}, -50.0)
    assert result['checked'] is False
    assert 'r_gyr' in result['note'] or 'radius of gyration' in result['note']


def test_check_all_members_matches_check_member_for_a_generated_mesh():
    mesh = sg.flat_grid(span_x=6.0, span_y=6.0, depth=1.0, module=3.0, offset=True)
    nodes, members = mesh['nodes'], mesh['members']
    for m in members:
        m.update(E=200.0, A=15.0, Fy=250.0, r_gyr=2.5, K=1.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, members)
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None

    checks = sc.check_all_members(nodes, members, res['member_res'])
    assert len(checks) == len(members)
    for m, mres, chk in zip(members, res['member_res'], checks):
        expected = sc.check_member(dict(m, _length_m=sm.member_vector(nodes, m)[3]),
                                    mres['N'])
        assert chk['checked'] == expected['checked']
        if chk['checked']:
            assert chk['util'] == pytest.approx(expected['util'], rel=1e-9)


def test_worst_utilization_ignores_unchecked_members():
    checks = [{'checked': True, 'util': 0.4}, {'checked': False, 'util': None},
              {'checked': True, 'util': 0.9}]
    assert sc.worst_utilization(checks) == pytest.approx(0.9)
    assert sc.worst_utilization([{'checked': False, 'util': None}]) is None


# ── the bending fallback no longer depends on the buckling radius ────────────

def _S(member):
    from apps.stereo import stereo_checks as _sk
    return _sk.elastic_section_modulus_cm3(member)


def test_changing_only_r_gyr_does_not_move_the_section_modulus():
    a = dict(A=27.25, I=1845.6, r_gyr=8.23)
    b = dict(A=27.25, I=1845.6, r_gyr=2.28)          # the same IPE, minor r
    assert _S(a) == pytest.approx(_S(b), rel=1e-12)


def test_the_fallback_is_a_thin_round_tube_from_I_and_A():
    import math
    m = dict(A=10.0, I=250.0, r_gyr=999.0)
    assert _S(m) == pytest.approx(250.0 / math.sqrt(2.0 * 250.0 / 10.0))


def test_the_fallback_is_conservative_for_every_i_and_channel_section():
    """Where the radius error was biggest, a lost depth must err SAFE:
    fallback S no larger than the real S = I/c."""
    from apps.stereo import stereo_profiles as _sp
    for name, sec in _sp.CATALOG.items():
        if sec.shape not in ('I', 'C'):
            continue
        props = _sp.section_to_props(sec)
        real = props['I'] / props['c_cm']
        guess = _S(dict(A=props['A'], I=props['I'], r_gyr=props['r_gyr']))
        assert guess <= real * (1 + 1e-9), (name, guess, real)


def test_a_catalog_member_uses_its_real_depth_not_the_guess():
    from apps.stereo import stereo_profiles as _sp
    props = _sp.section_to_props(_sp.CATALOG['L 50x5'])
    assert _S(props) == pytest.approx(props['I'] / props['c_cm'])


def test_an_ipe_in_compression_is_now_checked_about_its_weak_axis():
    """The fix, stated as a consequence: a 4 m IPE 200 strut is much more
    heavily utilised than the strong-axis radius used to report."""
    from apps.stereo import stereo_profiles as _sp
    from apps.stereo import stereo_checks as _sk
    sec = _sp.CATALOG['IPE 200']
    now = dict(_sp.section_to_props(sec, _sp.STEEL_F24), K=1.0, _length_m=4.0)
    was = dict(now, r_gyr=sec.r_x_mm / 10.0)
    u_now = _sk.check_member(now, -150.0)['util']
    u_was = _sk.check_member(was, -150.0)['util']
    assert u_now > 2.0 * u_was, (u_now, u_was)
