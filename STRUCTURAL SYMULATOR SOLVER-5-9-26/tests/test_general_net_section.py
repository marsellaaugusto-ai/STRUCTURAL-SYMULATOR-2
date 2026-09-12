"""
test_general_net_section.py -- web openings through ANY drawable section.

The load-bearing test here is the FIRST one. `net_section_at` computes the
tees at an opening from a rolled section's flange/web dimensions
analytically; `general_net_section.tees_at` computes the same integral by
clipping the section's polygons. They are independent implementations of
one quantity, so their agreement is what licenses the general path on
shapes where no closed form exists to check against.

  1. test_general_matches_the_closed_form -- the cross-check, to 1e-9.
  2. test_material_width_* -- the general analogue of `tw`, including the
     two-web box where no single `tw` exists.
  3. test_box_girder_* -- the user's 1800x500 welded box with 1350 mm
     openings, which the tab refused outright before this.
  4. test_deep_opening_warns / test_warning_survives_to_the_report -- the
     0.75d caveat, and the reporting bug that hid it.
  5. test_opening_through_the_whole_section_is_invalid.
  6. test_net_I_uses_the_real_neutral_axis -- mid-depth is only right for
     a doubly symmetric shape.
"""
import math
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

import pytest

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import welded_section_math as wsm
from apps.perforated_beam import general_net_section as gns
from apps.perforated_beam.hyperstatic_math import SupportSpec


def lipped_c(mirror=False, name='C'):
    t, H, B, LT, LB = 10.0, 1800.0, 250.0, 100.0, 200.0
    pts = [(0.0, -H/2), (B, -H/2), (B, -H/2+LB), (B-t, -H/2+LB), (B-t, -H/2+t),
           (t, -H/2+t), (t, H/2-t), (B-t, H/2-t), (B-t, H/2-LT), (B, H/2-LT),
           (B, H/2), (0.0, H/2)]
    if mirror:
        pts = [(-x, y) for x, y in reversed(pts)]
    return pbm.CustomProfileSection(name, pts)


def box_girder():
    A, B = lipped_c(), lipped_c(True, 'C right')
    cx, cy = A.centroid
    return wsm.CompoundSection([wsm.PlacedProfile(A, dx=cx, dy=cy, label='left'),
                                wsm.PlacedProfile(B, dx=500.0 - cx, dy=cy, label='right')])


# ── 1. the cross-check that licenses everything else ─────────────────────

@pytest.mark.parametrize('name', ['IPE 300', 'IPE 400', 'IPE 500', 'HEB 240',
                                  'HEB 300', 'W 16x40 (approx)'])
@pytest.mark.parametrize('frac', [0.2, 0.4, 0.55, 0.65])
def test_general_matches_the_closed_form(name, frac):
    """Analytic rectangles vs polygon clipping: the same integral, two
    completely different routes. Agreement here is why `tees_at` can be
    trusted on a drawn or welded shape, where nothing else exists to
    compare it against."""
    sec = pbm.SECTION_CATALOG[name]
    half = frac * sec.d / 2.0
    yb, yt = sec.d / 2 - half, sec.d / 2 + half
    if yb < sec.tf or yt > sec.d - sec.tf:
        pytest.skip('opening would reach a flange; the closed form declares that invalid')
    exact = pbm.net_section_at(sec, yb, yt)
    gen = gns.tees_at(sec, yb, yt)
    for side in ('top', 'bottom'):
        for attr in ('A', 'y_bar', 'I', 'S_hole', 'S_outer'):
            e = getattr(exact[side], attr)
            g = getattr(gen[side], attr)
            assert g == pytest.approx(e, rel=1e-9), f'{name} {frac} {side}.{attr}'


def test_dispatch_uses_the_closed_form_for_a_rolled_section():
    """The exact path must stay the one a RolledSection takes -- the
    generalization is an addition, not a replacement."""
    sec = pbm.SECTION_CATALOG['IPE 400']
    a = pbm.net_section_general(sec, 150.0, 250.0)
    b = pbm.net_section_at(sec, 150.0, 250.0)
    assert a['top'].I == b['top'].I
    assert a['valid'] == b['valid']


# ── 2. material width, the general `tw` ──────────────────────────────────

def test_material_width_on_a_rolled_section():
    sec = pbm.SECTION_CATALOG['IPE 400']
    assert gns.material_width_at(sec, sec.d / 2) == pytest.approx(sec.tw, rel=1e-9)
    assert gns.material_width_at(sec, sec.tf / 2) == pytest.approx(sec.bf, rel=1e-9)


def test_material_width_sums_both_webs_of_a_box():
    """No single `tw` could express this: the two-C box has two 10 mm webs
    at mid-depth, and the web-post check needs their sum."""
    box = box_girder()
    assert gns.material_width_at(box, 900.0) == pytest.approx(20.0, rel=1e-9)


def test_material_width_dispatch():
    box = box_girder()
    assert pbm.web_thickness_at(box, 900.0) == pytest.approx(20.0, rel=1e-9)
    ipe = pbm.SECTION_CATALOG['IPE 400']
    assert pbm.web_thickness_at(ipe, 200.0) == ipe.tw


def test_material_width_outside_the_section_is_zero():
    assert gns.material_width_at(box_girder(), 5000.0) == 0.0


# ── 3. the user's box girder ─────────────────────────────────────────────

def test_box_girder_accepts_openings():
    """This exact configuration was refused outright before."""
    box = box_girder()
    ops = pbm.uniform_layout(pbm.opening_circle(1350.0), 26, 1800.0, 2700.0)
    beam = pbm.BeamConfig(L=50400.0, section=box, material=pbm.Material(Fy=250.0),
                          openings=ops,
                          support_specs=[SupportSpec(1800.0), SupportSpec(16200.0),
                                         SupportSpec(48600.0)])
    assert len(beam.openings) == 26


def test_box_girder_openings_reduce_I():
    box = box_girder()
    ops = pbm.uniform_layout(pbm.opening_circle(1350.0), 26, 1800.0, 2700.0)
    beam = pbm.BeamConfig(L=50400.0, section=box, material=pbm.Material(Fy=250.0),
                          openings=ops)
    net = pbm.net_I_at(beam, ops[3].x_center)
    assert net < box.I
    assert net > 0.5 * box.I          # a 0.75d hole should not halve it
    assert pbm.net_I_at(beam, 100.0) == pytest.approx(box.I, rel=1e-12)   # away from a hole


def test_box_girder_full_analysis_runs():
    box = box_girder()
    ops = pbm.uniform_layout(pbm.opening_circle(1350.0), 26, 1800.0, 2700.0)
    beam = pbm.BeamConfig(L=50400.0, section=box, material=pbm.Material(Fy=250.0, E=200000.0),
                          openings=ops,
                          support_specs=[SupportSpec(1800.0), SupportSpec(16200.0),
                                         SupportSpec(48600.0)])
    for i in range(8):
        x = i * 7200.0
        if x <= beam.L:
            beam.point_loads.append(pbm.PointLoad(x, 100000.0))
    beam.dist_loads.append(pbm.DistLoad(0.0, beam.L, 5.0, 5.0))
    beam.dist_loads.append(pbm.DistLoad(18000.0, 46800.0, 1.0, 1.0))
    rep = pbm.analyze_beam(beam)
    assert rep['governing_opening'] is not None
    assert rep['governing_webpost'] is not None
    total = (sum(p.P for p in beam.point_loads)
             + sum((d.w1 + d.w2) / 2 * (d.x2 - d.x1) for d in beam.dist_loads))
    assert sum(r[1] for r in rep['support_reactions']) == pytest.approx(total, rel=1e-9)


def test_openings_soften_a_hyperstatic_box():
    """The reason net_I_at feeds the stiffness solve: the holes must show
    up in the deflected shape."""
    box = box_girder()
    common = dict(L=50400.0, section=box, material=pbm.Material(Fy=250.0, E=200000.0),
                  support_specs=[SupportSpec(1800.0), SupportSpec(16200.0),
                                 SupportSpec(48600.0)])
    solid = pbm.BeamConfig(**common)
    holed = pbm.BeamConfig(openings=pbm.uniform_layout(
        pbm.opening_circle(1350.0), 26, 1800.0, 2700.0), **common)
    for b in (solid, holed):
        b.dist_loads.append(pbm.DistLoad(0.0, b.L, 5.0, 5.0))
    assert max(pbm.deflection_profile(holed)[1]) > max(pbm.deflection_profile(solid)[1])


# ── 4. warnings ──────────────────────────────────────────────────────────

def test_deep_opening_warns():
    box = box_girder()
    res = gns.tees_at(box, (1800 - 1350) / 2.0, (1800 + 1350) / 2.0)
    assert res['valid']
    assert res['warning'] and '75%' in res['warning']


def test_shallow_opening_does_not_warn():
    box = box_girder()
    res = gns.tees_at(box, 700.0, 1100.0)      # 400 of 1800 = 22%
    assert res['valid'] and res['warning'] is None


def test_warning_survives_to_the_opening_report():
    """The bug this guards: for a circular opening the governing station
    sits off-centre, where the hole is shallower and raises no warning at
    all -- so reading the warning off the governing station hid the 0.75d
    caveat entirely."""
    box = box_girder()
    ops = pbm.uniform_layout(pbm.opening_circle(1350.0), 4, 1800.0, 2700.0)
    beam = pbm.BeamConfig(L=20000.0, section=box, material=pbm.Material(Fy=250.0),
                          openings=ops,
                          dist_loads=[pbm.DistLoad(0.0, 20000.0, 5.0, 5.0)])
    rep = pbm.analyze_opening(beam, ops[1])
    assert rep['warnings'], 'no warning reached the opening report'
    assert any('75%' in w for w in rep['warnings'])
    assert rep['governing'].warning is None, \
        'governing station happens to warn; this test no longer proves anything'


def test_opening_beyond_the_section_leaves_nothing_and_is_invalid():
    box = box_girder()
    res = gns.tees_at(box, -50.0, 1850.0)
    assert not res['valid']
    assert 'nothing is left' in res['warning']
    assert res['top'].A == 0.0 and res['bottom'].A == 0.0


def test_opening_leaving_only_slivers_is_valid_but_warns_loudly():
    """Deliberately NOT flagged invalid. A 5 mm sliver of flange is still
    material and still acts as a chord -- the geometry is real, it is the
    MODEL that stops being appropriate. Saying 'invalid' would imply a
    geometry error the user does not have; the 99% warning says the true
    thing instead."""
    box = box_girder()
    res = gns.tees_at(box, 5.0, 1795.0)
    assert res['valid']
    assert res['top'].A > 0 and res['bottom'].A > 0
    assert res['warning'] and '99%' in res['warning']


# ── 5. neutral axis ──────────────────────────────────────────────────────

def test_net_I_uses_the_real_neutral_axis():
    """The box's centroid sits 29 mm below mid-depth because the bottom lip
    is twice the top one. Using d/2 would put the parallel-axis terms on
    the wrong axis."""
    box = box_girder()
    c_bot = gns.section_bottom_offset(box)
    assert c_bot == pytest.approx(870.7, abs=1.0)
    assert abs(c_bot - box.d / 2) > 20.0
    direct = gns.net_I(box, 225.0, 1575.0)
    beam = pbm.BeamConfig(L=10000.0, section=box, material=pbm.Material(Fy=250.0),
                          openings=pbm.uniform_layout(
                              pbm.opening_circle(1350.0), 1, 1800.0, 5000.0))
    assert pbm.net_I_at(beam, 5000.0) == pytest.approx(direct, rel=1e-6)


def test_section_with_no_geometry_still_refused():
    class Mystery:
        name, A, I, S, d = 'mystery', 1000.0, 1e6, 1e4, 100.0
    with pytest.raises(ValueError, match='no outline'):
        pbm.BeamConfig(L=4000.0, section=Mystery(), material=pbm.STEEL_A36,
                       openings=pbm.uniform_layout(pbm.opening_circle(40.0), 2, 500.0, 1000.0))


def test_clip_halfplane_basics():
    sq = [(-10, -10), (10, -10), (10, 10), (-10, 10)]
    top = gns.clip_halfplane(sq, 0.0, keep_above=True)
    bot = gns.clip_halfplane(sq, 0.0, keep_above=False)
    a_top = abs(pbm._loop_integrals(top)[0])
    a_bot = abs(pbm._loop_integrals(bot)[0])
    assert a_top == pytest.approx(200.0) and a_bot == pytest.approx(200.0)
    assert gns.clip_halfplane(sq, 100.0, keep_above=True) == []
