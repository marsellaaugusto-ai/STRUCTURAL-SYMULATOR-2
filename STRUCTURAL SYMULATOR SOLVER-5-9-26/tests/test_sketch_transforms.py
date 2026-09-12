"""
test_sketch_transforms.py -- mirroring and moving a section sketch.

Every test here compares against the MIRRORED FLATTENED POLYGON rather
than against the mirrored segment objects. That is deliberate: the two
errors this code is exposed to -- a centre-arc that keeps its handedness,
and a weld that keeps its side -- both leave the segment objects looking
entirely correct. Only the flattened outline, and the A/I computed from
it, can see them.

The rule being tested throughout: mirroring the sketch and then
flattening must give the same points as flattening and then mirroring.
If those two ever disagree, the sketch is no longer the drawing it
displays.
"""
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

import math
import pytest

from apps.perforated_beam import section_profile_math as secm
from apps.perforated_beam import perforated_beam_math as pbm


def poly(pts):
    o = secm.SectionOutline(tuple(pts[0]))
    for p in pts[1:]:
        o.add_line(tuple(p))
    return o


def flat(loop):
    return [(round(x, 9), round(y, 9)) for x, y in loop.flatten()]


def mirrored_pts(pts, horizontal=True, about=0.0):
    return [(round(2 * about - x, 9), round(y, 9)) if horizontal
            else (round(x, 9), round(2 * about - y, 9)) for x, y in pts]


# ── the naming contract ──────────────────────────────────────────────────

def test_horizontal_flips_left_to_right_and_leaves_height_alone():
    """'Horizontal' names what the user sees MOVE, not the mirror line.
    Getting this backwards would be a silent usability inversion, so it is
    pinned rather than left to the button label."""
    assert secm.mirror_point((10.0, 3.0), horizontal=True) == (-10.0, 3.0)
    assert secm.mirror_point((10.0, 3.0), horizontal=False) == (10.0, -3.0)


def test_mirroring_about_an_offset_line():
    # x = 250 is the seam between the box girder's two profiles
    assert secm.mirror_point((0.0, 5.0), True, about=250.0) == (500.0, 5.0)
    assert secm.mirror_point((500.0, 5.0), True, about=250.0) == (0.0, 5.0)


def test_mirroring_twice_is_the_identity():
    pts = [(0., 0.), (100., 0.), (100., 40.), (30., 40.), (30., 90.), (0., 90.)]
    once = secm.mirror_loop(poly(pts), True, about=17.5)
    twice = secm.mirror_loop(once, True, about=17.5)
    assert flat(twice) == flat(poly(pts))


# ── the handedness trap ──────────────────────────────────────────────────

def test_centre_arc_reverses_its_sweep_when_mirrored():
    """A reflection reverses handedness. This is the assertion that fails
    if `not seg.ccw` is dropped from mirror_segment."""
    seg = secm.CenterArcSegment((10.0, 0.0), (20.0, 0.0), ccw=True)
    assert secm.mirror_segment(seg, horizontal=True).ccw is False
    assert secm.mirror_segment(seg, horizontal=False).ccw is False
    # and back again
    assert secm.mirror_segment(secm.mirror_segment(seg, True), True).ccw is True


def test_a_mirrored_centre_arc_bulges_the_same_way():
    """The check the `ccw` flag exists to pass: mirror-then-flatten must
    equal flatten-then-mirror. With the flag left alone the arc sweeps the
    long way round instead, and every point between the ends is wrong
    while both endpoints still match."""
    o = secm.SectionOutline((0.0, 0.0))
    o.add_line((100.0, 0.0))
    o.add_center_arc((100.0, 50.0), (100.0, 100.0), ccw=True)
    o.add_line((0.0, 100.0))

    got = flat(secm.mirror_loop(o, horizontal=True))
    expect = mirrored_pts(flat(o), horizontal=True)
    assert got == expect


def test_a_mirrored_three_point_arc_matches_too():
    o = secm.SectionOutline((0.0, 0.0))
    o.add_line((100.0, 0.0))
    o.add_arc((130.0, 50.0), (100.0, 100.0))
    o.add_line((0.0, 100.0))
    assert flat(secm.mirror_loop(o, True)) == mirrored_pts(flat(o), True)
    assert flat(secm.mirror_loop(o, False)) == mirrored_pts(flat(o), False)


def test_translation_does_not_touch_handedness():
    """The deliberate contrast with mirroring -- a move preserves it."""
    seg = secm.CenterArcSegment((10.0, 0.0), (20.0, 0.0), ccw=True)
    assert secm.translate_segment(seg, 5.0, 7.0).ccw is True


# ── circles stay circles ─────────────────────────────────────────────────

def test_a_mirrored_circle_is_still_a_circle():
    """Not 144 loose points. The sketch has to stay editable after a
    mirror, which is the reason transforms work on segments at all."""
    c = secm.CircleLoop((80.0, 20.0), 15.0, label='bolt')
    m = secm.mirror_loop(c, horizontal=True)
    assert isinstance(m, secm.CircleLoop)
    assert m.center == (-80.0, 20.0)
    assert m.radius == 15.0
    assert m.n == c.n and m.label == 'bolt'


# ── the weld-side trap ───────────────────────────────────────────────────

@pytest.mark.parametrize('side,expect', [
    ('positive', 'negative'), ('negative', 'positive'), ('auto', 'auto')])
def test_weld_side_swaps_under_a_mirror(side, expect):
    """'positive'/'negative' name the side the LEFT NORMAL points to, and
    a reflection reverses that normal. 'auto' is resolved from area at
    check time, so it needs no adjustment."""
    w = secm.SketchWeld((0.0, 0.0), (100.0, 0.0), leg=6.0, side=side)
    assert secm.mirror_weld(w, horizontal=True).side == expect


def test_weld_side_survives_a_round_trip_and_keeps_its_other_fields():
    w = secm.SketchWeld((0.0, 10.0), (50.0, 90.0), leg=8.0, n_lines=2,
                        side='positive', label='W1')
    back = secm.mirror_weld(secm.mirror_weld(w, False), False)
    assert (back.p1, back.p2, back.side) == (w.p1, w.p2, 'positive')
    assert (back.leg, back.n_lines, back.label) == (8.0, 2, 'W1')


def test_a_mirrored_weld_still_holds_the_same_physical_piece():
    """The end-to-end statement of the side rule: mirror the whole section
    AND its weld, and the held area must be unchanged. This is what a
    silent side flip would break -- it would report the shear flow for the
    big piece instead of the cap plate."""
    from apps.perforated_beam import welded_section_math as wsm
    # a plate capping the top of a tall rectangle
    pts = [(0., 0.), (100., 0.), (100., 200.), (0., 200.)]
    sk = secm.SectionSketch(poly(pts))
    sk.welds.append(secm.SketchWeld((-10., 180.), (110., 180.), leg=6.0, side='positive'))

    def held(sketch):
        sec = sketch.to_section('s')
        prof = wsm.WeldedProfile(sec, [w.to_weld_line() for w in sketch.welds])
        return wsm.check_welds(prof, 10000.0)[0].A_held

    assert held(secm.mirror_sketch(sk, horizontal=False)) == pytest.approx(held(sk), rel=1e-9)


# ── whole-sketch behaviour ───────────────────────────────────────────────

def test_mirroring_a_sketch_preserves_area_and_inertia():
    """A reflection is an isometry: A, I and the depth are invariant. Only
    the centroid's x moves (for a left-right flip)."""
    # a solid plate, so the bolt hole is genuinely inside material --
    # a hole in the thin arm of an L would be rejected by
    # CustomProfileSection, which is a different (correct) complaint.
    pts = [(0., 0.), (250., 0.), (250., 1800.), (0., 1800.)]
    sk = secm.SectionSketch(poly(pts))
    sk.holes.append(secm.CircleLoop((125.0, 900.0), 30.0))
    a = sk.to_section('a')
    b = secm.mirror_sketch(sk, horizontal=True).to_section('b')

    assert b.A == pytest.approx(a.A, rel=1e-12)
    assert b.I == pytest.approx(a.I, rel=1e-12)
    assert b.d == pytest.approx(a.d, rel=1e-12)
    assert b.centroid[0] == pytest.approx(-a.centroid[0], rel=1e-12)
    assert b.centroid[1] == pytest.approx(a.centroid[1], rel=1e-12)


def test_a_vertical_mirror_swaps_the_section_moduli():
    """A singly-symmetric section flipped top-for-bottom must exchange
    S_top and S_bot. If it does not, the mirror is not doing what it
    claims and an asymmetric profile would be checked on the wrong fibre."""
    # a T: wide flange at the top, thin stem below
    pts = [(-100., 180.), (100., 180.), (100., 200.), (-100., 200.)]
    stem = [(-10., 0.), (10., 0.), (10., 180.), (-10., 180.)]
    o = poly(stem[:2] + [(10., 180.), (100., 180.), (100., 200.),
                         (-100., 200.), (-100., 180.), (-10., 180.)])
    sk = secm.SectionSketch(o)
    a = sk.to_section('a')
    b = secm.mirror_sketch(sk, horizontal=False).to_section('b')
    assert a.S_top != pytest.approx(a.S_bot, rel=1e-6), 'test section must be asymmetric'
    assert b.S_top == pytest.approx(a.S_bot, rel=1e-9)
    assert b.S_bot == pytest.approx(a.S_top, rel=1e-9)


def test_mirror_about_the_seam_builds_the_box_girder():
    """The workflow this feature exists for: draw ONE lipped C, mirror a
    copy of it about the seam at x = 250, and the pair must be the box
    girder -- same A and I as the two profiles entered separately."""
    from apps.perforated_beam import welded_section_math as wsm
    H, B, T, LT, LB = 1800.0, 250.0, 10.0, 100.0, 200.0
    C = [(0., -H/2), (B, -H/2), (B, -H/2+LB), (B-T, -H/2+LB), (B-T, -H/2+T),
         (T, -H/2+T), (T, H/2-T), (B-T, H/2-T), (B-T, H/2-LT), (B, H/2-LT),
         (B, H/2), (0., H/2)]
    left = secm.SectionSketch(poly(C))
    right = secm.mirror_sketch(left, horizontal=True, about=B)

    a, b = left.to_section('A'), right.to_section('B')
    assert a.A == pytest.approx(25600.0, rel=1e-9)
    assert b.A == pytest.approx(a.A, rel=1e-12)

    box = wsm.CompoundSection(
        [wsm.PlacedProfile(a, dx=a.centroid[0], dy=a.centroid[1]),
         wsm.PlacedProfile(b, dx=b.centroid[0], dy=b.centroid[1])],
        detail=wsm.AssemblyDetail('closed', plate_thickness=T))
    assert box.A == pytest.approx(51200.0, rel=1e-9)
    assert box.I == pytest.approx(2.1065561354e10, rel=1e-6)
    assert box.d == pytest.approx(1800.0, rel=1e-9)


def test_move_selected_shifts_without_changing_shape():
    pts = [(0., 0.), (100., 0.), (100., 40.), (0., 40.)]
    o = poly(pts)
    moved = secm.translate_loop(o, 25.0, -7.0)
    assert flat(moved) == [(round(x + 25.0, 9), round(y - 7.0, 9)) for x, y in flat(o)]


def test_sketch_bbox_covers_outline_holes_and_welds():
    sk = secm.SectionSketch(poly([(0., 0.), (100., 0.), (100., 50.), (0., 50.)]))
    sk.holes.append(secm.CircleLoop((50.0, 25.0), 10.0))
    sk.welds.append(secm.SketchWeld((-20.0, 60.0), (120.0, 60.0)))
    assert secm.sketch_bbox(sk) == pytest.approx((-20.0, 0.0, 120.0, 60.0))
    assert secm.sketch_bbox(sk, include_welds=False) == pytest.approx((0.0, 0.0, 100.0, 50.0))


def test_empty_sketch_has_no_bbox():
    """None, not (0,0,0,0) -- 'nothing drawn' and 'a point at the origin'
    must not look the same to a caller centring a mirror on it."""
    assert secm.sketch_bbox(secm.SectionSketch()) is None
