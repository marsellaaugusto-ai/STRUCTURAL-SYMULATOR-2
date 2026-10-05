"""
test_assembly_detail.py -- how two profiles are joined decides their
torsion constant, and by a factor of thousands.

Two lipped channels butted lip-to-lip and seam-welded form a closed cell;
the same two joined only by stitch plates do not. Everything else about
the section -- A, I, S, the drawing -- is identical. J differs by ~4000x,
and with any load eccentricity that is the difference between a
utilisation of 0.33 and one of 3.09.

There is no safe default between those, which is what these tests are
really pinning: that the choice must be DECLARED, that each kind uses its
own formula for both J and the shear stress, and that an undeclared
assembly still degrades to a bending-only check rather than guessing.

  1. test_closed_matches_bredt / test_open_matches_the_thin_wall_sum --
     each J against its closed form, computed independently here.
  2. test_the_two_details_differ_by_thousands -- the headline.
  3. test_shear_stress_formula_follows_the_detail -- Bredt vs St Venant;
     using the wrong one is unconservative in both directions.
  4. test_undeclared_assembly_still_degrades -- no detail, no guess.
  5. test_detail_changes_the_verdict -- the design consequence, end to end.
"""
import math
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

import pytest

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import welded_section_math as wsm
from apps.perforated_beam.hyperstatic_math import SupportSpec

T_PLATE, H, B, LIP_T, LIP_B = 10.0, 1800.0, 250.0, 100.0, 200.0


def lipped_c(mirror=False, name='C'):
    t, LT, LB = T_PLATE, LIP_T, LIP_B
    pts = [(0.0, -H/2), (B, -H/2), (B, -H/2+LB), (B-t, -H/2+LB), (B-t, -H/2+t),
           (t, -H/2+t), (t, H/2-t), (B-t, H/2-t), (B-t, H/2-LT), (B, H/2-LT),
           (B, H/2), (0.0, H/2)]
    if mirror:
        pts = [(-x, y) for x, y in reversed(pts)]
    return pbm.CustomProfileSection(name, pts)


def box(detail=None):
    A, Bp = lipped_c(), lipped_c(True, 'C right')
    cx, cy = A.centroid
    return wsm.CompoundSection(
        [wsm.PlacedProfile(A, dx=cx, dy=cy, label='left'),
         wsm.PlacedProfile(Bp, dx=2 * B - cx, dy=cy, label='right')], detail=detail)


CLOSED = wsm.AssemblyDetail('closed', plate_thickness=T_PLATE, label='continuous seam')
OPEN = wsm.AssemblyDetail('open', plate_thickness=T_PLATE, label='stitch plates only')


# ── 1. each J against its own closed form ────────────────────────────────

def test_closed_matches_bredt():
    """J = 4*Am^2*t/Lm, with Am and Lm worked out here independently."""
    sec = box(CLOSED)
    am = (H - T_PLATE) * (2 * B - T_PLATE)
    lm = 2.0 * ((H - T_PLATE) + (2 * B - T_PLATE))
    assert sec.J == pytest.approx(4.0 * am * am * T_PLATE / lm, rel=1e-12)
    assert sec.J == pytest.approx(6.748e9, rel=1e-3)


def test_open_matches_the_thin_wall_sum():
    """J = A*t^2/3, the uniform-thickness form of (1/3)*sum(b*t^3)."""
    sec = box(OPEN)
    assert sec.J == pytest.approx(sec.A * T_PLATE ** 2 / 3.0, rel=1e-12)
    assert sec.J == pytest.approx(1.7067e6, rel=1e-3)


def test_the_two_details_differ_by_thousands():
    """The headline. Same A, same I, same drawing -- J apart by ~4000."""
    c, o = box(CLOSED), box(OPEN)
    assert c.A == pytest.approx(o.A, rel=1e-12)
    assert c.I == pytest.approx(o.I, rel=1e-12)
    assert c.J / o.J == pytest.approx(3954.0, rel=0.02)


def test_shear_area_counts_both_webs():
    sec = box(CLOSED)
    assert sec.Aweb == pytest.approx(20.0 * (H - 2 * T_PLATE), rel=1e-9)
    assert sec.Aweb == pytest.approx(35600.0, rel=1e-9)


# ── 2. the stress formula follows the detail ─────────────────────────────

def test_shear_stress_formula_follows_the_detail():
    """Bredt for the cell, St Venant for the open pair. Swapping them is
    unconservative in BOTH directions -- the open formula on a closed cell
    reports almost no stress, and vice versa."""
    T = 7.0e7
    am = (H - T_PLATE) * (2 * B - T_PLATE)
    closed_expected = T / (2.0 * am * T_PLATE)
    open_expected = T * T_PLATE / (box(OPEN).J)
    assert box(CLOSED).torsion_shear_stress(T) == pytest.approx(closed_expected, rel=1e-12)
    assert box(OPEN).torsion_shear_stress(T) == pytest.approx(open_expected, rel=1e-12)
    assert open_expected / closed_expected > 90


def test_combined_check_asks_the_section_for_its_torsion_stress():
    """`_combined_util` must prefer the section's own formula over its
    generic T*t_max/J, which would be the open one."""
    sec = box(CLOSED)
    util, sigma, tau_v, tau_t, ok = pbm._combined_util(
        sec, pbm.Material(Fy=250.0), M=1.0e9, V=3.0e5, T=7.0e7)
    assert ok
    assert tau_t == pytest.approx(sec.torsion_shear_stress(7.0e7), rel=1e-12)


# ── 3. no detail, no guess ───────────────────────────────────────────────

def test_undeclared_assembly_still_degrades():
    """Without a detail the parts have no J of their own, so the section
    must keep refusing -- exactly as before this feature existed."""
    sec = box(None)
    with pytest.raises(AttributeError):
        sec.J
    with pytest.raises(AttributeError):
        sec.Aweb
    util, _, _, _, ok = pbm._combined_util(sec, pbm.Material(Fy=250.0),
                                           M=1.0e9, V=3.0e5, T=7.0e7)
    assert not ok                      # bending-only, and says so


def test_detail_without_thickness_refuses():
    sec = box(wsm.AssemblyDetail('closed', plate_thickness=0.0))
    with pytest.raises(AttributeError, match='No plate thickness'):
        sec.J


def test_bad_kind_refused():
    with pytest.raises(ValueError, match="'open' or 'closed'"):
        wsm.AssemblyDetail('welded-ish', plate_thickness=10.0)


def test_describe_says_which_model_is_in_use():
    assert 'Bredt' in CLOSED.describe()
    assert 'open section' in OPEN.describe()


# ── 4. the design consequence ────────────────────────────────────────────

def _beam(sec, ecc):
    b = pbm.BeamConfig(
        L=50400.0, section=sec, material=pbm.Material(Fy=250.0, E=200000.0),
        openings=pbm.uniform_layout(pbm.opening_circle(1350.0), 26, 1800.0, 2700.0),
        support_specs=[SupportSpec(1800.0), SupportSpec(16200.0), SupportSpec(48600.0)])
    for i in range(8):
        x = i * 7200.0
        if x <= b.L:
            b.point_loads.append(pbm.PointLoad(x, 100000.0, ecc))
    b.dist_loads.append(pbm.DistLoad(0.0, b.L, 5.0, 5.0, ecc))
    b.dist_loads.append(pbm.DistLoad(18000.0, 46800.0, 1.0, 1.0))
    return b


def test_detail_changes_the_verdict():
    """End to end on the real beam: with 250 mm of load eccentricity the
    seam-welded box passes comfortably and the stitch-plated pair is over
    three times its capacity. Same steel, same drawing."""
    closed_rep = pbm.analyze_beam(_beam(box(CLOSED), 250.0))
    open_rep = pbm.analyze_beam(_beam(box(OPEN), 250.0))
    c, o = closed_rep['combined'], open_rep['combined']
    assert c.util < 1.0
    assert o.util > 3.0
    assert o.tau_torsion / max(c.tau_torsion, 1e-9) > 90


def test_without_eccentricity_the_detail_does_not_matter():
    """The contrast above is torsion; with no torque the two are the same
    beam, which is the control that shows the difference is real and not
    an artefact of the two code paths."""
    c = pbm.analyze_beam(_beam(box(CLOSED), 0.0))['combined']
    o = pbm.analyze_beam(_beam(box(OPEN), 0.0))['combined']
    assert c.util == pytest.approx(o.util, rel=1e-9)
    assert c.tau_torsion == pytest.approx(0.0, abs=1e-9)
