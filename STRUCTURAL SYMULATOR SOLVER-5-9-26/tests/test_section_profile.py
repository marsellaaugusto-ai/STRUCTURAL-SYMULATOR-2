"""
test_section_profile.py -- correctness tests for section_profile_math.py.

1. test_circle_from_3_points -- circumcircle formula against a known
   center/radius.
2. test_circle_from_3_points_collinear_returns_none -- degenerate input
   handled explicitly rather than raising or dividing by zero.
3. test_discretize_arc_endpoints_match -- an arc's discretized polyline
   starts/ends exactly at the given start/end points.
4. test_discretize_arc_passes_near_through_point -- the arc actually
   passes close to its "through" point (direction-of-sweep is correct,
   not just endpoint-correct).
5. test_outline_flatten_rectangle -- a lines-only outline flattens to the
   exact vertex list expected, without duplicating the start point.
6. test_outline_with_arc_produces_more_points_than_lines_alone -- sanity
   check that arc segments actually get discretized into multiple points.
7. test_outline_undo_last_removes_one_segment / test_outline_undo_last_on_empty_clears_start
   -- undo semantics match what the UI relies on.
8. test_outline_validate_rejects_self_intersection -- reuses
   profile_sketcher_math's is_simple_polygon under the hood.
9. test_outline_to_section_matches_perforated_beam_math -- round trip
   through CustomProfileSection reproduces the same numbers as calling it
   directly on the flattened points.
10. test_serialize_deserialize_round_trip -- JSON round trip for a mixed
    line+arc outline.
"""
import math
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

from apps.perforated_beam import section_profile_math as secm
from apps.perforated_beam import perforated_beam_math as pbm


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_circle_from_3_points():
    center, r = secm.circle_from_3_points((10, 0), (0, 10), (-10, 0))
    assert approx(center[0], 0.0) and approx(center[1], 0.0)
    assert approx(r, 10.0)


def test_circle_from_3_points_collinear_returns_none():
    assert secm.circle_from_3_points((0, 0), (1, 0), (2, 0)) is None


def test_discretize_arc_endpoints_match():
    pts = secm.discretize_arc((10, 0), (0, 10), (-10, 0))
    assert approx(pts[0][0], 10.0) and approx(pts[0][1], 0.0)
    assert approx(pts[-1][0], -10.0) and approx(pts[-1][1], 0.0)


def test_discretize_arc_passes_near_through_point():
    pts = secm.discretize_arc((10, 0), (0, 10), (-10, 0), n=40)
    best = min(math.hypot(px - 0, py - 10) for px, py in pts)
    assert best < 1.0  # within 1mm of the intended through point at this resolution


def test_outline_flatten_rectangle():
    o = secm.SectionOutline((0, 0))
    o.add_line((100, 0))
    o.add_line((100, 50))
    o.add_line((0, 50))
    assert o.flatten() == [(0, 0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]


def test_outline_with_arc_produces_more_points_than_lines_alone():
    o = secm.SectionOutline((10, 0))
    o.add_arc((0, 10), (-10, 0))
    pts = o.flatten()
    assert len(pts) > 3


def test_outline_undo_last_removes_one_segment():
    o = secm.SectionOutline((0, 0))
    o.add_line((10, 0))
    o.add_line((10, 10))
    o.undo_last()
    assert len(o.segments) == 1
    assert o.last_point() == (10.0, 0.0)


def test_outline_undo_last_on_empty_clears_start():
    o = secm.SectionOutline((5, 5))
    o.undo_last()
    assert o.start_point is None


def test_outline_validate_rejects_self_intersection():
    o = secm.SectionOutline((0, 0))
    o.add_line((10, 10))
    o.add_line((10, 0))
    o.add_line((0, 10))
    ok, msg = o.validate()
    assert ok is False
    assert 'self-intersecting' in msg


def test_outline_to_section_matches_perforated_beam_math():
    o = secm.SectionOutline((0, 0))
    o.add_line((100, 0))
    o.add_line((100, 50))
    o.add_line((0, 50))
    sec_via_outline = o.to_section('via_outline')
    sec_direct = pbm.CustomProfileSection('direct', o.flatten())
    assert approx(sec_via_outline.A, sec_direct.A)
    assert approx(sec_via_outline.I, sec_direct.I)


def test_serialize_deserialize_round_trip():
    o = secm.SectionOutline((0, 0))
    o.add_line((50, 0))
    o.add_arc((60, 10), (50, 20))
    o.add_line((0, 20))
    text = secm.serialize_outline(o, meta={'note': 'test'})
    restored, meta = secm.deserialize_outline(text)
    assert meta == {'note': 'test'}
    assert restored.start_point == (0.0, 0.0)
    assert [s.kind for s in restored.segments] == ['line', 'arc', 'line']
    assert restored.segments[1].through == (60.0, 10.0)
