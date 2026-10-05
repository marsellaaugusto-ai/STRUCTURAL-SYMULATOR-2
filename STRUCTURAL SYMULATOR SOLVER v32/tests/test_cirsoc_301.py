"""
test_cirsoc_301.py -- verification of the CIRSOC 301-2018 design-code
layer against the clauses themselves.

Every expected value below is either computed by hand from the clause
formula written out in the test, or is a transcribed table entry. Nothing
is checked against a previously recorded output of this code.

Source: Reglamento CIRSOC 301-2018, "Reglamento Argentino de Estructuras
de Acero para Edificios" (INTI-CIRSOC, July 2018). Clause references in
each test.

  1. test_resistance_factors -- the transcribed factors, including the one
     that differs from AISC.
  2. test_classification_* -- Table B.4.1b cases 11 and 16.
  3. test_flexural_* -- F.2.1 (Mp), F.2.5a (Lp), F.1 (phi_b), and the
     Lb regimes of F.2.2.
  4. test_shear_* -- G.2.1 (Vn), G.2.3-G.2.5 (Cv), G.1.1 (phi_v).
  5. test_stress_check_* -- H.3.4 and H.3.5, and the fact that H.3.3 is
     NOT a von Mises criterion.
  6. test_weld_* -- Table J.2.5 (phi, Fnw), J.2.2(a) (throat), Table
     J.2.4 (minimum leg), J.2.2(b) (maximum leg).
"""
import math
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

import pytest

from apps.perforated_beam import perforated_beam_math as pbm
import cirsoc_301 as cirsoc


IPE400 = pbm.SECTION_CATALOG['IPE 400']       # d=400 bf=180 tf=13.5 tw=8.6
FY = 250.0
E = 200000.0


# ── 1. resistance factors ────────────────────────────────────────────────

def test_resistance_factors_match_the_clauses():
    assert cirsoc.PHI_FLEXURE == 0.90      # F.1(1)
    assert cirsoc.PHI_SHEAR == 0.90        # G.1.1
    assert cirsoc.PHI_NORMAL == 0.90       # H.3.4
    assert cirsoc.PHI_TAU == 0.90          # H.3.5
    assert cirsoc.PHI_BUCKLING == 0.85     # H.3.6
    assert cirsoc.PHI_WELD == 0.60         # Tabla J.2.5, soldaduras de filete


def test_weld_factor_differs_from_aisc_deliberately():
    """The single most consequential number in the code layer. AISC 360-16
    Table J2.5 gives 0.75 for the same limit state; CIRSOC 301 gives 0.60.
    Using AISC's under CIRSOC overstates every fillet weld by 25%."""
    assert cirsoc.CIRSOC_301.phi_weld == 0.60
    assert cirsoc.AISC_360.phi_weld == 0.75
    assert cirsoc.AISC_360.phi_weld / cirsoc.CIRSOC_301.phi_weld == pytest.approx(1.25)


# ── 2. classification, Table B.4.1b ──────────────────────────────────────

def test_flange_classification_case_11():
    """b/t = (bf/2)/tf against lam_p = 0.38*sqrt(E/Fy)."""
    cls, ratio, lam_p, lam_r = cirsoc.classify_flange(IPE400, FY)
    assert ratio == pytest.approx((180 / 2) / 13.5, rel=1e-12)
    assert lam_p == pytest.approx(0.38 * math.sqrt(E / FY), rel=1e-12)
    assert lam_r == pytest.approx(0.83 * math.sqrt(E / (0.7 * FY)), rel=1e-12)
    assert cls == cirsoc.COMPACT              # 6.67 < 10.75


def test_web_classification_case_16():
    """h/tw against lam_p = 3.76*sqrt(E/Fy), lam_r = 5.70*sqrt(E/Fy)."""
    cls, ratio, lam_p, lam_r = cirsoc.classify_web(IPE400, FY)
    assert ratio == pytest.approx((400 - 2 * 13.5) / 8.6, rel=1e-12)
    assert lam_p == pytest.approx(3.76 * math.sqrt(E / FY), rel=1e-12)
    assert lam_r == pytest.approx(5.70 * math.sqrt(E / FY), rel=1e-12)
    assert cls == cirsoc.COMPACT              # 43.4 < 106.4


def test_slender_web_is_detected():
    thin = pbm.RolledSection('thin web', d=1000.0, bf=200.0, tf=12.0, tw=4.0)
    cls, ratio, _, lam_r = cirsoc.classify_web(thin, FY)
    assert ratio == pytest.approx((1000 - 24) / 4.0)
    assert cls == cirsoc.SLENDER              # 244 > 161


# ── 3. flexure, Chapter F ────────────────────────────────────────────────

def test_plastic_moment_F_2_1():
    """Mn = Mp = Fy*Zx <= 1.5*My, with Zx from the section's own geometry."""
    r = cirsoc.flexural_strength(IPE400, FY)
    Zx = IPE400.bf * IPE400.tf * (IPE400.d - IPE400.tf) + \
         IPE400.tw * (IPE400.d - 2 * IPE400.tf) ** 2 / 4.0
    assert r.Mp == pytest.approx(FY * Zx, rel=1e-12)
    assert r.My == pytest.approx(FY * IPE400.S, rel=1e-12)
    assert r.Mp < 1.5 * r.My                  # the cap does not bind here
    assert r.Mn == pytest.approx(r.Mp, rel=1e-12)


def test_design_flexural_strength_applies_phi_b_F_1():
    r = cirsoc.flexural_strength(IPE400, FY)
    assert r.Md == pytest.approx(0.90 * r.Mn, rel=1e-12)


def test_Lp_matches_F_2_5a():
    """Lp = 1.76*ry*sqrt(E/Fyf), with ry from Iy and A."""
    r = cirsoc.flexural_strength(IPE400, FY)
    ry = math.sqrt(IPE400.Iy / IPE400.A)
    assert r.Lp == pytest.approx(1.76 * ry * math.sqrt(E / FY), rel=1e-12)


def test_Lp_switches_for_top_flange_loading_F_2_5b():
    a = cirsoc.flexural_strength(IPE400, FY)
    b = cirsoc.flexural_strength(IPE400, FY, load_on_top_flange=True)
    assert b.Lp / a.Lp == pytest.approx(1.59 / 1.76, rel=1e-12)


def test_unbraced_length_regimes_F_2_2():
    """Mn = Mp up to Lp, then falls, and never exceeds Mp."""
    r0 = cirsoc.flexural_strength(IPE400, FY, Lb=0.0)
    Lp, Lr = r0.Lp, r0.Lr
    assert Lr > Lp
    at_Lp = cirsoc.flexural_strength(IPE400, FY, Lb=Lp * 0.999)
    mid = cirsoc.flexural_strength(IPE400, FY, Lb=(Lp + Lr) / 2.0)
    at_Lr = cirsoc.flexural_strength(IPE400, FY, Lb=Lr * 0.999)
    beyond = cirsoc.flexural_strength(IPE400, FY, Lb=Lr * 2.0)
    assert at_Lp.Mn == pytest.approx(r0.Mp, rel=1e-12)
    assert r0.Mp > mid.Mn > at_Lr.Mn > beyond.Mn
    for r in (r0, at_Lp, mid, at_Lr, beyond):
        assert r.Mn <= r0.Mp * (1 + 1e-12)


def test_Mn_at_Lr_approaches_Mr():
    """At Lb = Lr the F.2.2 line reaches Mr = FL*Sx with FL = 0.7*Fy."""
    r0 = cirsoc.flexural_strength(IPE400, FY)
    at_Lr = cirsoc.flexural_strength(IPE400, FY, Lb=r0.Lr)
    Mr = 0.7 * FY * IPE400.S
    assert at_Lr.Mn == pytest.approx(Mr, rel=1e-9)


def test_continuously_braced_default_is_stated_not_assumed():
    r = cirsoc.flexural_strength(IPE400, FY, Lb=0.0)
    assert 'continuously braced' in r.note
    assert 'continuously braced' in r.governing


def test_noncompact_section_is_capped_and_flagged():
    thin = pbm.RolledSection('slender web', d=1000.0, bf=200.0, tf=12.0, tw=4.0)
    r = cirsoc.flexural_strength(thin, FY)
    assert r.web_class == cirsoc.SLENDER
    assert r.Mn == pytest.approx(r.My, rel=1e-12)     # capped, conservative
    assert 'not compact' in r.note and 'F.3/F.4/F.5' in r.note


# ── 4. shear, Chapter G ──────────────────────────────────────────────────

def test_shear_strength_G_2_1():
    """Vn = 0.6*Fyw*Aw*Cv with Aw = d*tw (G.2.2), Cv = 1 for this web."""
    r = cirsoc.shear_strength(IPE400, FY)
    assert r.Aw == pytest.approx(400 * 8.6, rel=1e-12)
    assert r.Cv == pytest.approx(1.0, rel=1e-12)
    assert r.Vn == pytest.approx(0.6 * FY * 400 * 8.6, rel=1e-12)
    assert r.Vn == pytest.approx(516000.0, rel=1e-9)     # 516 kN
    assert r.Vd == pytest.approx(0.90 * r.Vn, rel=1e-12)  # G.1.1


def test_shear_area_is_not_the_elastic_web_area():
    """G.2.2 uses the FULL depth; the elastic stress check uses the clear
    web. Conflating them would overstate Vn by ~7% on an IPE 400."""
    r = cirsoc.shear_strength(IPE400, FY)
    assert r.Aw > IPE400.Aweb
    assert r.Aw == pytest.approx(IPE400.d * IPE400.tw, rel=1e-12)


@pytest.mark.parametrize('h_tw,expect', [(40.0, 'yielding'), (75.0, 'inelastic'),
                                         (120.0, 'elastic')])
def test_Cv_regimes_G_2_3_to_G_2_5(h_tw, expect):
    kv = 5.0
    lim1 = 1.10 * math.sqrt(kv * E / FY)      # 69.57
    lim2 = 1.37 * math.sqrt(kv * E / FY)      # 86.65
    Cv, gov = cirsoc.shear_web_coefficient(h_tw, FY, kv, E)
    assert expect in gov
    if h_tw <= lim1:
        assert Cv == pytest.approx(1.0)
    elif h_tw <= lim2:
        assert Cv == pytest.approx(lim1 / h_tw, rel=1e-12)
    else:
        assert Cv == pytest.approx(1.51 * kv * E / (h_tw ** 2 * FY), rel=1e-12)


def test_Cv_is_continuous_across_the_regime_boundaries():
    """The first boundary (G.2.3 -> G.2.4) is exactly continuous.

    The second (G.2.4 -> G.2.5) is NOT, and that is a property of the
    standard rather than of this code: at h/tw = 1.37*sqrt(kv*E/Fyw),
    G.2.4 gives Cv = 1.10/1.37 = 0.80292 while G.2.5 gives
    Cv = 1.51/1.37^2 = 0.80452 -- a 0.2% step, because the constants 1.10,
    1.37 and 1.51 are rounded. Pinned here at the size it actually is, so
    that a real discontinuity introduced by an edit would still be caught."""
    kv = 5.0
    lim1 = 1.10 * math.sqrt(kv * E / FY)
    below = cirsoc.shear_web_coefficient(lim1 * 0.9999, FY, kv, E)[0]
    above = cirsoc.shear_web_coefficient(lim1 * 1.0001, FY, kv, E)[0]
    assert below == pytest.approx(above, rel=1e-3)

    lim2 = 1.37 * math.sqrt(kv * E / FY)
    below = cirsoc.shear_web_coefficient(lim2 * 0.9999, FY, kv, E)[0]
    above = cirsoc.shear_web_coefficient(lim2 * 1.0001, FY, kv, E)[0]
    assert below == pytest.approx(1.10 / 1.37, rel=1e-3)
    assert above == pytest.approx(1.51 / 1.37 ** 2, rel=1e-3)
    assert abs(above - below) / below < 0.003        # the standard's own 0.2% step


def test_very_slender_web_warns_about_kv():
    thin = pbm.RolledSection('very thin', d=1200.0, bf=200.0, tf=12.0, tw=4.0)
    r = cirsoc.shear_strength(thin, FY)
    assert r.h_tw > 260
    assert 'exceeds 260' in r.note


# ── 5. stress checks, H.3.3 ──────────────────────────────────────────────

def test_normal_stress_check_H_3_4():
    """fun <= phi*Fy, phi = 0.90."""
    c = cirsoc.stress_check(200.0, 0.0, FY)
    assert c.Fn_normal == pytest.approx(0.90 * FY, rel=1e-12)
    assert c.util_normal == pytest.approx(200.0 / (0.90 * 250.0), rel=1e-12)
    assert c.util == pytest.approx(0.8889, rel=1e-3)
    assert 'H.3.4' in c.governing


def test_shear_stress_check_H_3_5():
    """fuv <= 0.6*phi*Fy, phi = 0.90 -> 135 MPa for Fy = 250."""
    c = cirsoc.stress_check(0.0, 100.0, FY)
    assert c.Fn_shear == pytest.approx(0.6 * 0.90 * FY, rel=1e-12)
    assert c.Fn_shear == pytest.approx(135.0, rel=1e-12)
    assert c.util_shear == pytest.approx(100.0 / 135.0, rel=1e-12)
    assert 'H.3.5' in c.governing


def test_H_3_3_is_not_a_von_mises_criterion():
    """The clause checks the two stresses SEPARATELY. In a strongly
    combined state von Mises exceeds both, which is why it is still
    reported alongside rather than dropped."""
    c = cirsoc.stress_check(125.0, 75.0, FY)
    assert c.util == pytest.approx(max(125.0 / 225.0, 75.0 / 135.0), rel=1e-12)
    assert c.von_mises == pytest.approx(
        math.sqrt(125.0 ** 2 + 3 * 75.0 ** 2) / 250.0, rel=1e-12)
    assert c.von_mises > c.util          # von Mises is the harsher one here


def test_pure_bending_is_more_conservative_than_the_old_unfactored_ratio():
    """The old report divided by Fy with no factor. Applying phi = 0.90
    must make the same stress read 1/0.9 = 11% higher."""
    c = cirsoc.stress_check(200.0, 0.0, FY)
    assert c.util / (200.0 / FY) == pytest.approx(1 / 0.90, rel=1e-12)


def test_buckling_check_H_3_6():
    """fun or fuv <= phi_c*Fcr, phi_c = 0.85."""
    assert cirsoc.buckling_stress_check(85.0, 200.0) == pytest.approx(
        85.0 / (0.85 * 200.0), rel=1e-12)


# ── 6. welds, J.2 ────────────────────────────────────────────────────────

def test_fillet_throat_J_2_2a():
    assert cirsoc.fillet_throat(6.0) == pytest.approx(0.707 * 6.0, rel=1e-12)


def test_weld_strength_table_J_2_5():
    """phi = 0.60, Fnw = 0.60*Fexx, on the effective throat."""
    got = cirsoc.weld_strength_per_mm(leg=6.0, Fexx=482.0, n_lines=2)
    assert got == pytest.approx(0.60 * 0.60 * 482.0 * 0.707 * 6.0 * 2, rel=1e-12)


def test_leg_for_shear_flow_inverts_the_capacity():
    q = 1500.0
    leg = cirsoc.leg_for_shear_flow(q, 482.0, n_lines=1)
    assert cirsoc.weld_strength_per_mm(leg, 482.0, 1) == pytest.approx(q, rel=1e-12)


def test_cirsoc_requires_a_25_percent_bigger_weld_than_aisc():
    """Direct consequence of phi 0.60 vs 0.75 -- the practical impact of
    the one factor where the two standards disagree."""
    q = 1500.0
    leg_c = cirsoc.leg_for_shear_flow(q, 482.0, code=cirsoc.CIRSOC_301)
    leg_a = cirsoc.leg_for_shear_flow(q, 482.0, code=cirsoc.AISC_360)
    assert leg_c / leg_a == pytest.approx(1.25, rel=1e-12)
    assert leg_c == pytest.approx(1500.0 / (0.60 * 0.60 * 482.0 * 0.707), rel=1e-12)


@pytest.mark.parametrize('t,expect', [(3.0, 3.0), (6.0, 3.0), (6.1, 5.0), (13.0, 5.0),
                                      (13.5, 6.0), (19.0, 6.0), (19.5, 8.0), (60.0, 8.0)])
def test_minimum_fillet_leg_table_J_2_4(t, expect):
    assert cirsoc.min_fillet_leg(t) == expect


@pytest.mark.parametrize('t,expect', [(4.0, 4.0), (5.9, 5.9), (6.0, 4.0), (20.0, 18.0)])
def test_maximum_fillet_leg_J_2_2b(t, expect):
    assert cirsoc.max_fillet_leg(t) == pytest.approx(expect, rel=1e-12)


def test_minimum_effective_length_J_2_2b():
    assert cirsoc.min_effective_length(6.0) == 24.0


# ── integration: the factors actually reach the reported results ─────────

def test_member_check_uses_the_design_strengths():
    beam = pbm.BeamConfig(L=8000.0, section=IPE400, material=pbm.Material(Fy=FY, E=E))
    beam.dist_loads.append(pbm.DistLoad(0.0, 8000.0, 20.0, 20.0))
    m = pbm.member_check(beam)
    assert m is not None
    # simply supported UDL: Mu = wL^2/8, Vu = wL/2
    assert abs(m.Mu) == pytest.approx(20.0 * 8000.0 ** 2 / 8, rel=1e-6)
    assert abs(m.Vu) == pytest.approx(20.0 * 8000.0 / 2, rel=1e-6)
    assert m.util_flexure == pytest.approx(abs(m.Mu) / (0.90 * m.flexure.Mn), rel=1e-9)
    assert m.util_shear == pytest.approx(abs(m.Vu) / (0.90 * m.shear.Vn), rel=1e-9)
    assert m.util == max(m.util_flexure, m.util_shear)


def test_member_check_now_runs_on_a_drawn_section():
    """It used to return None here, on the argument that Chapter F needs
    Zx and Chapter G needs an identifiable web. Both are now recovered
    from the polygons (`section_plastic`), so the check runs -- which is
    the whole point of that module. A 100x100 square is small enough to
    verify by hand: Zx = b*h^2/4 = 2.5e5 mm^3, so Mp = Fy*Zx."""
    sec = pbm.CustomProfileSection('p', [(-50, -50), (50, -50), (50, 50), (-50, 50)])
    beam = pbm.BeamConfig(L=4000.0, section=sec, material=pbm.Material(Fy=FY, E=E))
    beam.dist_loads.append(pbm.DistLoad(0.0, 4000.0, 10.0, 10.0))
    m = pbm.member_check(beam)
    assert m is not None
    assert m.flexure.Mp == pytest.approx(FY * 100.0 * 100.0 ** 2 / 4.0, rel=1e-6)
    # solid square: one "web" 100 mm wide over the full 100 mm depth
    assert m.shear.Aw == pytest.approx(100.0 * 100.0, rel=1e-6)
    assert m.util_flexure > 0 and m.util_shear > 0


def test_member_check_on_a_drawn_section_says_what_it_did_not_evaluate():
    """A drawn polygon has no classified flange or web and, with no
    declared assembly, no J. The result must SAY that rather than look
    like a complete check."""
    sec = pbm.CustomProfileSection('p', [(-50, -50), (50, -50), (50, 50), (-50, 50)])
    beam = pbm.BeamConfig(L=4000.0, section=sec, material=pbm.Material(Fy=FY, E=E),
                          Lb=3000.0)
    m = pbm.member_check(beam)
    assert m is not None
    assert m.flexure.flange_class == cirsoc.UNKNOWN_CLASS
    assert 'NOT A COMPLETE FLEXURAL CHECK' in m.flexure.note


def test_member_check_still_degrades_when_there_is_no_geometry():
    """The graceful degrade is kept, for the case that actually needs it:
    a section object that cannot describe its own shape."""
    class Opaque:
        name, A, I, S, d = 'opaque', 5000.0, 1e8, 5e5, 400.0
        Iy, centroid = 1e7, (0.0, 0.0)
        S_top = S_bot = 5e5

    beam = pbm.BeamConfig(L=4000.0, section=Opaque(),
                          material=pbm.Material(Fy=FY, E=E))
    assert pbm.member_check(beam) is None


def test_vierendeel_utilisation_now_carries_phi():
    """A station check must be 1/0.9 harsher than the same stresses were
    under the old unfactored ratio, when normal stress governs."""
    c = cirsoc.stress_check(180.0, 20.0, FY)
    assert c.util_normal > c.util_shear
    assert c.util == pytest.approx(180.0 / 225.0, rel=1e-12)


def test_analyze_beam_reports_the_code_basis():
    beam = pbm.BeamConfig(L=8000.0, section=IPE400, material=pbm.Material(Fy=FY, E=E))
    beam.dist_loads.append(pbm.DistLoad(0.0, 8000.0, 15.0, 15.0))
    rep = pbm.analyze_beam(beam)
    assert rep['code'].name == 'CIRSOC 301-2018'
    assert rep['member'] is not None
    assert 'F.1' in rep['code'].citation and 'J.2.5' in rep['code'].citation
