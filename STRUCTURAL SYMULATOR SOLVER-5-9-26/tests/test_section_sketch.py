"""
test_section_sketch.py -- correctness tests for the profile-designer
geometry added to section_profile_math.py: circles, center arcs, holes,
and weld marking.

Checked against closed forms (pi*r^2, pi*r^4/4, the exact area of a
rectangular tube) and against exact invariants (a point produced by an
arc tool must lie on the circle it claims to be on; a saved sketch must
reload identically). See MANIFESTO §2.

  1. test_circle_loop_* -- area and inertia of a polygonised circle
     against the closed form, including the DIRECTION of the
     discretisation bias, which is documented rather than merely small.
  2. test_center_arc_* -- every generated point on the circle, correct
     sweep direction, full-turn behaviour, and the end-point projection
     that makes the tool usable by hand.
  3. test_round_bar_outline / test_square_tube / test_plate_with_holes --
     whole sections built the way the UI builds them.
  4. test_sketch_roundtrip / test_loads_legacy_outline_file -- saving must
     be lossless, and previously saved profiles must still open.
  5. test_sketch_welds_reach_the_check -- a weld drawn on the sketch must
     arrive at check_welds with its geometry intact.
"""
import json
import math
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

import pytest

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import section_profile_math as secm
from apps.perforated_beam import welded_section_math as wsm
from apps.perforated_beam.section_profile_math import (
    CircleLoop, SectionOutline, SectionSketch, SketchWeld,
    circle_from_2_points, circle_from_center_point, project_to_circle,
    discretize_center_arc,
)


def poly_area(pts):
    n = len(pts)
    return abs(sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1]
                   for i in range(n))) / 2.0


# ── circles ──────────────────────────────────────────────────────────────

def test_circle_loop_area_matches_closed_form():
    r = 40.0
    pts = CircleLoop((0, 0), r).flatten()
    assert poly_area(pts) == pytest.approx(math.pi * r ** 2, rel=1e-3)


def test_circle_discretisation_bias_is_inscribed():
    """The documented direction of the error: an inscribed polygon is
    SMALLER than the true circle, so a hole built from one removes
    slightly too little material. Stated in CircleLoop's docstring; pinned
    here so it cannot silently flip, and bounded at the value that
    docstring claims."""
    r = 40.0
    exact = math.pi * r ** 2
    a = poly_area(CircleLoop((0, 0), r).flatten())
    assert a < exact                          # inscribed, never circumscribed
    assert a > 0.9995 * exact                 # 0.032% at 144 segments
    # and the closed form for an inscribed regular n-gon, exactly
    n = secm.CIRCLE_SEGMENTS
    assert a == pytest.approx(0.5 * n * r ** 2 * math.sin(2 * math.pi / n), rel=1e-12)


def test_circle_loop_refuses_nonsense():
    with pytest.raises(ValueError, match='radius must be positive'):
        CircleLoop((0, 0), 0.0)
    with pytest.raises(ValueError, match='at least 8 segments'):
        CircleLoop((0, 0), 10.0, n=4)


def test_circle_from_two_points_is_a_diameter():
    c, r = circle_from_2_points((-30.0, 0.0), (30.0, 0.0))
    assert c == pytest.approx((0.0, 0.0))
    assert r == pytest.approx(30.0)


def test_circle_from_center_and_edge():
    c, r = circle_from_center_point((10.0, 20.0), (10.0, 45.0))
    assert c == pytest.approx((10.0, 20.0))
    assert r == pytest.approx(25.0)


def test_circle_from_3_points_still_works():
    got = secm.circle_from_3_points((-10, 0), (0, 10), (10, 0))
    assert got is not None
    (cx, cy), r = got
    assert (cx, cy) == pytest.approx((0.0, 0.0), abs=1e-9)
    assert r == pytest.approx(10.0)


# ── center arcs ──────────────────────────────────────────────────────────

def test_project_to_circle_lands_on_the_circle():
    p = project_to_circle((0.0, 0.0), 50.0, (3.0, 4.0))
    assert math.hypot(*p) == pytest.approx(50.0, rel=1e-12)
    assert p[0] / p[1] == pytest.approx(3.0 / 4.0, rel=1e-12)


def test_project_to_circle_refuses_the_center():
    with pytest.raises(ValueError, match='coincide with its center'):
        project_to_circle((5.0, 5.0), 10.0, (5.0, 5.0))


def test_center_arc_points_all_lie_on_the_circle():
    r = 25.0
    pts = discretize_center_arc((0, 0), (r, 0), (0, r), ccw=True)
    for p in pts:
        assert math.hypot(*p) == pytest.approx(r, rel=1e-12)
    assert pts[0] == pytest.approx((r, 0.0), abs=1e-9)
    assert pts[-1] == pytest.approx((0.0, r), abs=1e-9)


def test_center_arc_direction_is_respected():
    """CCW from (r,0) to (0,r) is a quarter turn through the first
    quadrant; CW is the other three quarters."""
    r = 25.0
    ccw = discretize_center_arc((0, 0), (r, 0), (0, r), ccw=True)
    cw = discretize_center_arc((0, 0), (r, 0), (0, r), ccw=False)
    assert all(p[0] >= -1e-9 and p[1] >= -1e-9 for p in ccw)   # first quadrant only
    assert any(p[0] < 0 and p[1] < 0 for p in cw)              # sweeps the far side
    assert len(cw) > len(ccw)                                  # bigger sweep, more chords


def test_center_arc_start_equals_end_is_a_full_turn():
    r = 30.0
    pts = discretize_center_arc((0, 0), (r, 0), (r, 0), ccw=True)
    assert poly_area(pts[:-1]) == pytest.approx(math.pi * r ** 2, rel=1e-3)


def test_add_center_arc_projects_and_continues():
    o = SectionOutline((0.0, 0.0))
    o.add_line((100.0, 0.0))
    # centre at (100,50): radius 50 from the current point; the clicked end
    # is sloppy and must be pulled onto the circle
    o.add_center_arc((100.0, 50.0), (147.0, 52.0), ccw=True)
    end = o.last_point()
    assert math.hypot(end[0] - 100.0, end[1] - 50.0) == pytest.approx(50.0, rel=1e-12)
    pts = o.flatten()
    assert len(pts) > 3


def test_add_center_arc_without_a_start_is_refused():
    with pytest.raises(ValueError, match='start point of the outline'):
        SectionOutline().add_center_arc((0, 0), (10, 0))


def test_add_center_arc_on_the_center_is_refused():
    o = SectionOutline((50.0, 50.0))
    with pytest.raises(ValueError, match='coincides with the current point'):
        o.add_center_arc((50.0, 50.0), (10.0, 0.0))


# ── whole sections ───────────────────────────────────────────────────────

def test_round_bar_outline():
    """A circle used as the boundary: A = pi r^2, I = pi r^4 / 4."""
    r = 50.0
    s = SectionSketch()
    s.set_circle_outline((0.0, 0.0), r)
    sec = s.to_section('round bar')
    assert sec.A == pytest.approx(math.pi * r ** 2, rel=1e-3)
    assert sec.I == pytest.approx(math.pi * r ** 4 / 4.0, rel=2e-3)
    assert sec.I == pytest.approx(sec.Iy, rel=1e-9)


def test_square_tube_exact():
    """A rectangular hollow section, where the closed form is exact --
    no polygonisation anywhere."""
    o = SectionOutline((-50.0, -50.0))
    for p in [(50.0, -50.0), (50.0, 50.0), (-50.0, 50.0)]:
        o.add_line(p)
    s = SectionSketch(o)
    h = SectionOutline((-40.0, -40.0))
    for p in [(40.0, -40.0), (40.0, 40.0), (-40.0, 40.0)]:
        h.add_line(p)
    s.add_hole(h)
    sec = s.to_section('RHS 100x100x10')
    assert sec.A == pytest.approx(100 ** 2 - 80 ** 2, rel=1e-12)
    assert sec.I == pytest.approx((100 * 100 ** 3 - 80 * 80 ** 3) / 12.0, rel=1e-12)


def test_plate_with_circular_holes():
    o = SectionOutline((-100.0, -20.0))
    for p in [(100.0, -20.0), (100.0, 20.0), (-100.0, 20.0)]:
        o.add_line(p)
    s = SectionSketch(o)
    s.add_circle_hole((-50.0, 0.0), 10.0, label='bolt 1')
    s.add_circle_hole((50.0, 0.0), 10.0, label='bolt 2')
    sec = s.to_section('drilled plate')
    assert sec.A == pytest.approx(200 * 40 - 2 * math.pi * 100, rel=1e-3)
    assert sec.centroid == pytest.approx((0.0, 0.0), abs=1e-9)


def test_hole_outside_the_outline_is_refused_at_section_build():
    o = SectionOutline((-50.0, -50.0))
    for p in [(50.0, -50.0), (50.0, 50.0), (-50.0, 50.0)]:
        o.add_line(p)
    s = SectionSketch(o)
    s.add_circle_hole((500.0, 0.0), 10.0)
    with pytest.raises(ValueError, match='not fully inside the outline'):
        s.to_section()


def test_self_crossing_outline_is_refused():
    o = SectionOutline((0.0, 0.0))
    for p in [(100.0, 100.0), (100.0, 0.0), (0.0, 100.0)]:
        o.add_line(p)
    s = SectionSketch(o)
    ok, msg = s.validate()
    assert not ok and 'crosses itself' in msg
    with pytest.raises(ValueError, match='crosses itself'):
        s.to_section()


# ── persistence ──────────────────────────────────────────────────────────

def _demo_sketch():
    o = SectionOutline((-50.0, -50.0))
    o.add_line((50.0, -50.0))
    o.add_center_arc((50.0, 0.0), (50.0, 50.0), ccw=True)
    o.add_line((-50.0, 50.0))
    s = SectionSketch(o)
    s.add_circle_hole((0.0, 0.0), 15.0, label='void')
    s.add_weld((-50.0, 0.0), (50.0, 0.0), leg=6.0, n_lines=2, label='seam')
    return s


def test_sketch_roundtrip_is_lossless():
    s = _demo_sketch()
    back, meta = secm.deserialize_sketch(secm.serialize_sketch(s, {'name': 'demo'}))
    assert meta['name'] == 'demo'
    assert back.outline_points() == pytest.approx(s.outline_points())
    assert len(back.holes) == 1 and len(back.welds) == 1
    assert back.welds[0].leg == 6.0 and back.welds[0].n_lines == 2
    assert back.to_section().A == pytest.approx(s.to_section().A, rel=1e-12)


def test_loads_legacy_outline_only_file():
    """Profiles saved before holes and welds existed must still open."""
    o = SectionOutline((0.0, 0.0))
    for p in [(100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]:
        o.add_line(p)
    legacy = secm.serialize_outline(o, {'name': 'old'})
    sketch, meta = secm.deserialize_sketch(legacy)
    assert meta['name'] == 'old'
    assert sketch.holes == [] and sketch.welds == []
    assert sketch.to_section().A == pytest.approx(100 * 50, rel=1e-12)
    # and the old reader must still read the old file
    back, _ = secm.deserialize_outline(legacy)
    assert back.flatten() == pytest.approx(o.flatten())


def test_old_reader_also_accepts_a_new_file():
    text = secm.serialize_sketch(_demo_sketch())
    loop, _ = secm.deserialize_outline(text)
    assert len(loop.flatten()) > 3


# ── welds from the sketch ────────────────────────────────────────────────

def test_sketch_welds_reach_the_check():
    """A weld drawn on the sketch must arrive at check_welds with its
    geometry intact, and hold the area the drawing says it holds."""
    o = SectionOutline((-50.0, -50.0))
    for p in [(50.0, -50.0), (50.0, 50.0), (-50.0, 50.0)]:
        o.add_line(p)
    s = SectionSketch(o)
    s.add_weld((-50.0, 0.0), (50.0, 0.0), leg=5.0, label='mid seam')
    wp = s.to_welded_profile('welded plate')
    assert wp.A == pytest.approx(100 * 100, rel=1e-12)
    res = wsm.check_welds(wp, 100000.0)
    assert len(res) == 1
    r = res[0]
    assert r.label == 'mid seam'
    assert r.A_held == pytest.approx(5000.0, rel=1e-9)     # the top half
    assert r.Q == pytest.approx(5000.0 * 25.0, rel=1e-9)
    assert r.q == pytest.approx(1500.0, rel=1e-9)          # same closed form as before


def test_welded_profile_delegates_section_properties():
    sec = pbm.CustomProfileSection('p', [(-50, -50), (50, -50), (50, 50), (-50, 50)])
    wp = wsm.WeldedProfile(sec, [])
    assert wp.A == sec.A and wp.I == sec.I and wp.S_top == sec.S_top
    assert wp.d == sec.d
    assert wp.name == 'p'
