"""
test_welded_section.py -- correctness tests for welded_section_math.py and
for the holes support added to CustomProfileSection.

Everything here is checked against a value known independently of this
code: an elementary closed form (a rectangle's bd^3/12, a hollow box, an
annulus), an exact invariant (a compound of two halves must equal the
whole), or agreement with the existing BuiltUpDoubleSection for the one
arrangement both classes can express. See MANIFESTO §2.

A. Holes in CustomProfileSection
   1. test_hollow_box_closed_form / test_plate_with_circular_hole --
      A and I against the closed forms for a box and an annulus.
   2. test_hole_winding_does_not_matter -- a hole drawn clockwise must
      remove exactly the same material as one drawn anticlockwise. This
      is the invariant the per-loop orientation normalisation exists for.
   3. test_hole_outside_outline_refused / test_holes_consuming_all_area
      -- garbage geometry is refused with an explanation, not silently
      turned into a negative area.
   4. test_no_holes_matches_previous_behaviour -- the rewritten property
      code must not move the answer for a solid profile.

B. CompoundSection
   5. test_two_stacked_halves_equal_the_whole -- two 100x50 plates stacked
      must reproduce a single 100x100 plate exactly (A, I, S, d). The
      parallel-axis term is the entire content of this test.
   6. test_matches_builtup_double_for_side_by_side -- for the ONE
      arrangement BuiltUpDoubleSection can also express, the two classes
      must agree.
   7. test_offset_pair_is_asymmetric -- an offset pair must produce
      S_top != S_bot, which is exactly what BuiltUpDoubleSection cannot
      represent and why this class exists.
   8. test_aweb_and_j_degrade -- Aweb/J must raise (not fabricate) when
      any part lacks them.

C. Welds
   9. test_weld_shear_flow_matches_rectangle_closed_form -- q at the
      neutral axis of the stacked pair must equal the exact VQ/I for the
      equivalent solid rectangle, cross-checked against tau = 1.5V/A.
  10. test_weld_leg_sizing_round_trip -- the leg the code sizes must come
      back at utilisation 1.0 when supplied.
  11. test_auto_side_picks_smaller_area / test_explicit_side.
  12. test_weld_cutting_undrawable_part_refused -- refuses rather than
      guessing Q for a rolled shape it cannot clip.
"""
import math
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

import pytest

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import welded_section_math as wsm
from apps.perforated_beam.welded_section_math import (
    PlacedProfile, CompoundSection, WeldLine, WeldCode, check_welds,
)


def rect(w, h, cx=0.0, cy=0.0, name='rect'):
    """A w x h rectangle centred on (cx, cy), anticlockwise."""
    return pbm.CustomProfileSection(name, [
        (cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2),
        (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)])


def rect_pts(w, h, cx=0.0, cy=0.0, clockwise=False):
    pts = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2),
           (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
    return list(reversed(pts)) if clockwise else pts


def circle_pts(r, cx=0.0, cy=0.0, n=180, clockwise=False):
    pts = [(cx + r * math.cos(2 * math.pi * i / n),
            cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    return list(reversed(pts)) if clockwise else pts


# ── A. holes ─────────────────────────────────────────────────────────────

def test_hollow_box_closed_form():
    """100x100 outer, 80x80 void: A = 100^2 - 80^2, I = (100^4 - 80^4)/12."""
    sec = pbm.CustomProfileSection('box', rect_pts(100, 100), [rect_pts(80, 80)])
    assert sec.A == pytest.approx(100 * 100 - 80 * 80, rel=1e-12)
    assert sec.I == pytest.approx((100 * 100 ** 3 - 80 * 80 ** 3) / 12.0, rel=1e-12)
    assert sec.Iy == pytest.approx((100 * 100 ** 3 - 80 * 80 ** 3) / 12.0, rel=1e-12)
    assert sec.centroid == pytest.approx((0.0, 0.0), abs=1e-9)


def test_offset_hole_moves_the_centroid():
    """A void high in the section pulls the centroid DOWN, and by an
    amount fixed by first moments alone."""
    sec = pbm.CustomProfileSection('plate', rect_pts(100, 200),
                                   [rect_pts(40, 40, cy=60)])
    A_out, A_h = 100 * 200, 40 * 40
    expect_cy = (A_out * 0.0 - A_h * 60.0) / (A_out - A_h)
    assert sec.centroid[1] == pytest.approx(expect_cy, rel=1e-12)
    assert sec.A == pytest.approx(A_out - A_h, rel=1e-12)


def test_plate_with_circular_hole():
    """Annulus-in-a-plate, against the closed form pi*r^2 and pi*r^4/4.
    The polygonised circle converges from below, hence the loose-ish
    tolerance on a 180-gon."""
    r = 30.0
    sec = pbm.CustomProfileSection('plated', rect_pts(200, 200), [circle_pts(r)])
    assert sec.A == pytest.approx(200 * 200 - math.pi * r ** 2, rel=2e-4)
    I_exact = 200 * 200 ** 3 / 12.0 - math.pi * r ** 4 / 4.0
    assert sec.I == pytest.approx(I_exact, rel=2e-4)


@pytest.mark.parametrize('outline_cw', [False, True])
@pytest.mark.parametrize('hole_cw', [False, True])
def test_hole_winding_does_not_matter(outline_cw, hole_cw):
    """The invariant the per-loop orientation normalisation exists for: a
    hand-drawn loop can come back either way round, and a hole drawn
    clockwise must not ADD material."""
    sec = pbm.CustomProfileSection(
        'box', rect_pts(100, 100, clockwise=outline_cw),
        [rect_pts(80, 80, clockwise=hole_cw)])
    assert sec.A == pytest.approx(100 * 100 - 80 * 80, rel=1e-12)
    assert sec.I == pytest.approx((100 * 100 ** 3 - 80 * 80 ** 3) / 12.0, rel=1e-12)


def test_no_holes_matches_previous_behaviour():
    """The rewritten property code must not move a solid profile's answer."""
    sec = rect(100, 300)
    assert sec.A == pytest.approx(100 * 300, rel=1e-12)
    assert sec.I == pytest.approx(100 * 300 ** 3 / 12.0, rel=1e-12)
    assert sec.Iy == pytest.approx(300 * 100 ** 3 / 12.0, rel=1e-12)
    assert sec.S_top == pytest.approx(sec.I / 150.0, rel=1e-12)


def test_hole_outside_outline_refused():
    with pytest.raises(ValueError, match='not fully inside the outline'):
        pbm.CustomProfileSection('bad', rect_pts(100, 100),
                                 [rect_pts(20, 20, cx=200)])


def test_holes_consuming_all_area_refused():
    with pytest.raises(ValueError, match='remove as much area'):
        pbm.CustomProfileSection('gone', rect_pts(100, 100),
                                 [rect_pts(99, 99), rect_pts(99, 99)])


def test_degenerate_hole_refused():
    with pytest.raises(ValueError, match='fewer than 3'):
        pbm.CustomProfileSection('bad', rect_pts(100, 100), [[(0, 0), (1, 1)]])


def test_hollow_section_still_refuses_to_guess_torsion():
    """A closed box has a far larger J than the open-section formula would
    give, so guessing here would be UNconservative. The class must keep
    saying nothing."""
    sec = pbm.CustomProfileSection('box', rect_pts(100, 100), [rect_pts(80, 80)])
    assert not hasattr(sec, 'J')
    assert not hasattr(sec, 'Aweb')


# ── B. compound sections ─────────────────────────────────────────────────

def test_two_stacked_halves_equal_the_whole():
    """Two 100x50 plates stacked must reproduce one 100x100 plate exactly.
    The parallel-axis term is the entire content of this test: dropping it
    would give I = 2*(100*50^3/12) = 2.08e6 instead of 8.33e6."""
    half = rect(100, 50)
    comp = CompoundSection([PlacedProfile(half, dy=-25.0, label='bottom'),
                            PlacedProfile(half, dy=+25.0, label='top')])
    whole = rect(100, 100)
    assert comp.A == pytest.approx(whole.A, rel=1e-12)
    assert comp.I == pytest.approx(whole.I, rel=1e-12)
    assert comp.I == pytest.approx(100 * 100 ** 3 / 12.0, rel=1e-12)
    assert comp.d == pytest.approx(100.0, rel=1e-12)
    assert comp.S_top == pytest.approx(whole.S_top, rel=1e-12)
    assert comp.S_bot == pytest.approx(whole.S_bot, rel=1e-12)
    assert comp.centroid[1] == pytest.approx(0.0, abs=1e-9)


def test_side_by_side_halves_equal_the_whole_weak_axis():
    half = rect(50, 100)
    comp = CompoundSection([PlacedProfile(half, dx=-25.0),
                            PlacedProfile(half, dx=+25.0)])
    whole = rect(100, 100)
    assert comp.Iy == pytest.approx(whole.Iy, rel=1e-12)
    assert comp.I == pytest.approx(whole.I, rel=1e-12)


def test_matches_builtup_double_for_side_by_side():
    """For the one arrangement both classes can express -- two identical
    profiles side by side at equal height -- they must agree."""
    ch = pbm.CHANNEL_CATALOG['UPN 220']
    gap = 200.0
    old = pbm.BuiltUpDoubleSection(ch, gap=gap)
    new = CompoundSection([PlacedProfile(ch, dx=-gap / 2), PlacedProfile(ch, dx=+gap / 2)])
    assert new.A == pytest.approx(old.A, rel=1e-12)
    assert new.I == pytest.approx(old.I, rel=1e-12)
    assert new.d == pytest.approx(old.d, rel=1e-12)
    assert new.S_top == pytest.approx(old.S_top, rel=1e-12)
    assert new.Aweb == pytest.approx(old.Aweb, rel=1e-12)
    assert new.J == pytest.approx(old.J, rel=1e-12)


def test_offset_pair_is_asymmetric():
    """A channel capping an I-beam: the neutral axis rises, the section
    becomes singly symmetric, and S_top != S_bot. This is precisely what
    BuiltUpDoubleSection cannot represent."""
    ipe = pbm.SECTION_CATALOG['IPE 400']
    cap = rect(200, 20)
    comp = CompoundSection([PlacedProfile(ipe, dy=0.0, label='IPE 400'),
                            PlacedProfile(cap, dy=210.0, label='cap plate')])
    assert comp.A == pytest.approx(ipe.A + 200 * 20, rel=1e-12)
    assert comp.centroid[1] > 0.0                    # NA pulled up toward the cap
    assert comp.S_top != pytest.approx(comp.S_bot, rel=1e-6)
    # S = I/c, so the FURTHER fiber gets the SMALLER modulus. The NA has
    # risen toward the cap, so the bottom fiber is the far one and S_bot
    # is the governing (smaller) value.
    assert comp.S_top > comp.S_bot
    assert comp.S == pytest.approx(comp.S_bot, rel=1e-12)
    assert comp.I > ipe.I                            # the cap must stiffen it
    assert comp.d == pytest.approx(220.0 - (-200.0), rel=1e-12)


def test_compound_needs_two_parts():
    with pytest.raises(ValueError, match='at least 2 profiles'):
        CompoundSection([PlacedProfile(rect(10, 10))])


def test_compound_cannot_nest():
    inner = CompoundSection([PlacedProfile(rect(10, 10), dy=-5),
                             PlacedProfile(rect(10, 10), dy=5)])
    with pytest.raises(ValueError, match='cannot be nested'):
        PlacedProfile(inner)


def test_aweb_and_j_degrade_when_a_part_lacks_them():
    """A drawn profile exposes no Aweb/J, so the compound must not either
    -- analyze_combined's duck-typing depends on the AttributeError."""
    comp = CompoundSection([PlacedProfile(pbm.SECTION_CATALOG['IPE 400'], dx=-150),
                            PlacedProfile(rect(100, 100), dx=+150)])
    with pytest.raises(AttributeError):
        comp.Aweb
    with pytest.raises(AttributeError):
        comp.J


def test_compound_drives_a_full_beam_analysis():
    comp = CompoundSection([PlacedProfile(rect(100, 50), dy=-25),
                            PlacedProfile(rect(100, 50), dy=+25)])
    beam = pbm.BeamConfig(L=4000.0, section=comp, material=pbm.STEEL_A36,
                          point_loads=[pbm.PointLoad(2000.0, 10000.0)])
    report = pbm.analyze_beam(beam)
    assert report['combined'] is not None


# ── C. welds ─────────────────────────────────────────────────────────────

STACKED = CompoundSection(
    [PlacedProfile(rect(100, 50), dy=-25.0, label='bottom'),
     PlacedProfile(rect(100, 50), dy=+25.0, label='top')],
    welds=[WeldLine((-50.0, 0.0), (50.0, 0.0), label='interface')])


def test_weld_shear_flow_matches_rectangle_closed_form():
    """The interface of the stacked pair sits at the neutral axis of the
    equivalent 100x100 rectangle, so the shear flow there is the textbook
    maximum: q = V*Q/I with Q = 5000*25, cross-checked independently
    against tau_max = 1.5*V/A and q = tau*b."""
    V = 100000.0
    res = check_welds(STACKED, V)[0]
    assert res.A_held == pytest.approx(5000.0, rel=1e-12)
    assert res.Q == pytest.approx(5000.0 * 25.0, rel=1e-12)
    q_exact = V * (5000.0 * 25.0) / (100 * 100 ** 3 / 12.0)
    assert res.q == pytest.approx(q_exact, rel=1e-12)
    tau_max = 1.5 * V / (100.0 * 100.0)          # rectangle closed form
    assert res.q == pytest.approx(tau_max * 100.0, rel=1e-12)
    assert res.q == pytest.approx(1500.0, rel=1e-12)


def test_weld_shear_flow_scales_linearly_with_V():
    a = check_welds(STACKED, 50000.0)[0].q
    b = check_welds(STACKED, 150000.0)[0].q
    assert b == pytest.approx(3.0 * a, rel=1e-12)


def test_weld_leg_sizing_round_trip():
    """The leg the code sizes must come back at exactly utilisation 1.0."""
    V = 100000.0
    sized = check_welds(STACKED, V)[0]
    assert sized.leg_provided == 0.0
    assert sized.util == 0.0 and sized.ok           # sizing, not checking
    assert 'sizing result' in sized.note

    checked = CompoundSection(
        list(STACKED.parts),
        welds=[WeldLine((-50.0, 0.0), (50.0, 0.0), leg=sized.leg_required)])
    r = check_welds(checked, V)[0]
    assert r.util == pytest.approx(1.0, rel=1e-9)
    assert r.ok


def test_weld_capacity_matches_the_documented_formula():
    """CIRSOC 301 Tabla J.2.5: phi = 0.60 (NOT the AISC 0.75), Fnw =
    0.60*Fexx, on the J.2.2(a) effective throat of 0.707*leg."""
    code = WeldCode()
    leg, n = 6.0, 2
    assert code.phi == 0.60
    assert code.capacity_per_mm(leg, n) == pytest.approx(
        0.60 * 0.60 * 482.0 * 0.707 * 6.0 * 2, rel=1e-12)


def test_weld_capacity_is_below_the_aisc_value_by_the_phi_ratio():
    """Guards the number this whole change turned on: an AISC-factored
    weld would be 25% stronger, and using it on a CIRSOC job would
    undersize every seam."""
    import cirsoc_301 as cirsoc
    cirsoc_cap = WeldCode().capacity_per_mm(6.0, 1)
    aisc_cap = WeldCode(phi=cirsoc.AISC_360.phi_weld).capacity_per_mm(6.0, 1)
    assert aisc_cap / cirsoc_cap == pytest.approx(0.75 / 0.60, rel=1e-12)


def test_undersized_weld_is_flagged():
    sized = check_welds(STACKED, 100000.0)[0]
    weak = CompoundSection(
        list(STACKED.parts),
        welds=[WeldLine((-50.0, 0.0), (50.0, 0.0), leg=sized.leg_required * 0.5)])
    r = check_welds(weak, 100000.0)[0]
    assert r.util == pytest.approx(2.0, rel=1e-9)
    assert not r.ok
    assert 'needs a' in r.note


def test_more_weld_lines_share_the_flow():
    sized_1 = check_welds(STACKED, 100000.0)[0].leg_required
    two = CompoundSection(list(STACKED.parts),
                          welds=[WeldLine((-50.0, 0.0), (50.0, 0.0), n_lines=2)])
    assert check_welds(two, 100000.0)[0].leg_required == pytest.approx(
        sized_1 / 2.0, rel=1e-12)


def test_auto_side_picks_the_smaller_area():
    """A thin cap plate welded to a deep web: the held piece is the cap,
    not the whole rest of the section."""
    comp = CompoundSection(
        [PlacedProfile(rect(20, 400), dy=0.0, label='web'),
         PlacedProfile(rect(200, 20), dy=210.0, label='cap')],
        welds=[WeldLine((-100.0, 200.0), (100.0, 200.0), label='cap weld')])
    r = check_welds(comp, 100000.0)[0]
    assert r.A_held == pytest.approx(200 * 20, rel=1e-9)
    assert 'smaller area' in r.note


def test_explicit_side_overrides_auto():
    comp = CompoundSection(
        [PlacedProfile(rect(20, 400), dy=0.0, label='web'),
         PlacedProfile(rect(200, 20), dy=210.0, label='cap')],
        welds=[WeldLine((-100.0, 200.0), (100.0, 200.0), side='negative')])
    r = check_welds(comp, 100000.0)[0]
    assert r.A_held == pytest.approx(20 * 400, rel=1e-9)   # the web, not the cap


def test_weld_clips_a_part_it_cuts_through():
    """A weld line partway up a drawn plate must clip it, not take the
    whole part: holding the top 30 mm of a 100 mm plate is a much smaller
    Q than holding all of it."""
    comp = CompoundSection(
        [PlacedProfile(rect(100, 100), dy=0.0, label='plate'),
         PlacedProfile(rect(100, 20), dy=60.0, label='cap')],
        welds=[WeldLine((-50.0, 20.0), (50.0, 20.0), label='mid-plate')])
    r = check_welds(comp, 100000.0)[0]
    # held side = above y=20: the top 30 mm of the plate (3000) + cap (2000)
    assert r.A_held == pytest.approx(3000.0 + 2000.0, rel=1e-9)


def test_weld_cutting_an_undrawable_part_is_refused():
    """Refuses rather than guessing Q for a rolled shape it cannot clip."""
    comp = CompoundSection(
        [PlacedProfile(pbm.SECTION_CATALOG['IPE 400'], dy=0.0),
         PlacedProfile(rect(200, 20), dy=210.0)],
        welds=[WeldLine((-100.0, 0.0), (100.0, 0.0))])
    with pytest.raises(ValueError, match='not a drawn outline'):
        check_welds(comp, 100000.0)


def test_weld_outside_the_section_says_so():
    comp = CompoundSection(
        [PlacedProfile(rect(100, 50), dy=-25.0), PlacedProfile(rect(100, 50), dy=25.0)],
        welds=[WeldLine((-50.0, 900.0), (50.0, 900.0))])
    r = check_welds(comp, 100000.0)[0]
    assert r.A_held == 0.0 and r.q == 0.0
    assert 'does not cut the section' in r.note


def test_zero_length_weld_refused():
    with pytest.raises(ValueError, match='zero length'):
        WeldLine((0.0, 0.0), (0.0, 0.0))


def test_bad_side_refused():
    with pytest.raises(ValueError, match='side must be'):
        WeldLine((0.0, 0.0), (1.0, 0.0), side='left')


def test_governing_weld_prefers_utilisation_when_legs_are_given():
    comp = CompoundSection(
        list(STACKED.parts),
        welds=[WeldLine((-50.0, 0.0), (50.0, 0.0), leg=20.0, label='fat'),
               WeldLine((-50.0, 0.0), (50.0, 0.0), leg=3.0, label='thin')])
    g = wsm.governing_weld(check_welds(comp, 100000.0))
    assert g.label == 'thin'
