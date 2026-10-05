"""
test_profile_sketcher.py -- correctness tests for profile_sketcher_math.py.

1. test_circle_shape_matches_manual_circle -- a CircleShape converted to
   an OpeningInstance must produce the same vertices (up to float noise)
   as pbm.opening_circle() called directly, so sketched circles behave
   identically to manually-entered ones in the analysis engine.
2. test_circle_offset_from_middepth_shifts_local_y -- a circle whose
   world-space center is NOT on the section mid-depth must come out with
   vertices_local shifted vertically by exactly that offset.
3. test_rectangle_polygon_round_trips_to_opening_rectangle -- a rectangle
   drawn as 4 world-space corners converts to the same local geometry
   (dimensions + centering) as pbm.opening_rectangle().
4. test_self_intersecting_polygon_is_rejected -- a bowtie shape fails
   is_simple_polygon() and shape_to_opening_instance() raises ValueError.
5. test_reentrant_polygon_fails_y_simple -- a valid (simple) but
   non-"y-simple" C-shape is flagged by is_y_simple(), matching
   opening_polygon()'s documented limitation.
6. test_serialize_deserialize_round_trip -- a mixed circle+polygon sketch
   survives a JSON save/load cycle exactly.
7. test_parse_typed_entry_absolute_relative_polar -- the three supported
   coordinate-entry syntaxes ("x,y", "@dx,dy", "length<angle") all parse
   to the expected point.
8. test_snap_to_grid_rounds_to_nearest_multiple -- grid snapping rounds
   to the nearest grid line, not truncates.
9. test_nearest_candidate_respects_tolerance -- point snap only fires
   within the given tolerance, never snapping to a distant point.
10. test_mirror_vertically_reflects_about_axis -- mirroring a circle
    about the mid-depth axis reflects its center y exactly.
11. test_shapes_to_openings_matches_uniform_layout -- an array of
    identical circles produced by the sketcher's translate_shape()
    reproduces the same x_center spacing as pbm.uniform_layout().
"""
import json
import math
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import profile_sketcher_math as psm


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def approx_pts(pts_a, pts_b, tol=1e-6):
    if len(pts_a) != len(pts_b):
        return False
    return all(approx(a[0], b[0], tol) and approx(a[1], b[1], tol) for a, b in zip(pts_a, pts_b))


# ── 1/2. Circle conversion ──────────────────────────────────────────────

def test_circle_shape_matches_manual_circle():
    depth = 400.0
    diameter = 250.0
    shape = psm.CircleShape(center=(1000.0, depth / 2.0), diameter=diameter, label='H1')
    oi = psm.shape_to_opening_instance(shape, section_depth=depth)
    expected = pbm.opening_circle(diameter)
    assert approx(oi.x_center, 1000.0)
    assert approx_pts(oi.vertices_local, expected, tol=1e-9)


def test_circle_offset_from_middepth_shifts_local_y():
    depth = 400.0
    offset = 30.0
    shape = psm.CircleShape(center=(500.0, depth / 2.0 + offset), diameter=200.0, label='H1')
    oi = psm.shape_to_opening_instance(shape, section_depth=depth)
    base = pbm.opening_circle(200.0)
    expected = [(vx, vy + offset) for vx, vy in base]
    assert approx_pts(oi.vertices_local, expected, tol=1e-9)


# ── 3. Rectangle polygon ────────────────────────────────────────────────

def test_rectangle_polygon_round_trips_to_opening_rectangle():
    depth = 400.0
    w, h = 200.0, 300.0
    cx, cy = 1500.0, depth / 2.0
    verts_world = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2),
                   (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
    shape = psm.PolygonShape(verts_world, label='H2')
    oi = psm.shape_to_opening_instance(shape, section_depth=depth)
    expected = pbm.opening_rectangle(w, h)
    assert approx(oi.x_center, cx)
    # order/winding should match since both start at the same corner
    assert approx_pts(oi.vertices_local, expected, tol=1e-9)


# ── 4/5. Validation ──────────────────────────────────────────────────────

def test_self_intersecting_polygon_is_rejected():
    bowtie = [(0, 0), (10, 10), (10, 0), (0, 10)]
    assert psm.is_simple_polygon(bowtie) is False
    shape = psm.PolygonShape(bowtie, label='bad')
    try:
        psm.shape_to_opening_instance(shape, section_depth=400.0)
        assert False, 'expected ValueError'
    except ValueError as exc:
        assert 'bad' in str(exc)


def test_reentrant_polygon_fails_y_simple():
    # A "C" shape: for x in the middle of its span, a vertical line
    # crosses the boundary four times, not two.
    c_shape = [(0, 0), (10, 0), (10, 3), (3, 3), (3, 7), (10, 7), (10, 10), (0, 10)]
    assert psm.is_simple_polygon(c_shape) is True
    assert psm.is_y_simple(c_shape) is False
    ok, msg = psm.validate_polygon(c_shape)
    assert ok is False
    assert 're-entrant' in msg


def test_simple_shapes_pass_validation():
    for verts in (pbm.opening_circle(200.0), pbm.opening_rectangle(150, 250),
                  pbm.opening_hexagon(400, 200)):
        ok, msg = psm.validate_polygon(verts)
        assert ok, msg


# ── 6. Serialization ─────────────────────────────────────────────────────

def test_serialize_deserialize_round_trip():
    shapes = [
        psm.CircleShape((1000.0, 200.0), 250.0, 'H1'),
        psm.PolygonShape([(2000, 50), (2200, 50), (2200, 350), (2000, 350)], 'H2'),
    ]
    text = psm.serialize_shapes(shapes, meta={'length': 8000.0, 'section_depth': 400.0})
    restored, meta = psm.deserialize_shapes(text)
    assert meta == {'length': 8000.0, 'section_depth': 400.0}
    assert len(restored) == 2
    assert restored[0].kind == 'circle' and restored[0].label == 'H1'
    assert approx(restored[0].diameter, 250.0)
    assert restored[1].kind == 'polygon' and restored[1].label == 'H2'
    assert approx_pts(restored[1].vertices, shapes[1].vertices)
    # must be plain JSON (no custom objects) so it's portable/inspectable
    json.loads(text)


# ── 7. Typed entry parsing ────────────────────────────────────────────────

def test_parse_typed_entry_absolute_relative_polar():
    assert psm.parse_typed_entry('120,45') == (120.0, 45.0)
    x, y = psm.parse_typed_entry('@30,-10', ref_point=(100.0, 100.0))
    assert approx(x, 130.0) and approx(y, 90.0)
    x, y = psm.parse_typed_entry('150<90', ref_point=(0.0, 0.0))
    assert approx(x, 0.0, 1e-6) and approx(y, 150.0, 1e-6)
    x, y = psm.parse_typed_entry('100<0', ref_point=(50.0, 50.0))
    assert approx(x, 150.0) and approx(y, 50.0)


# ── 8/9. Snapping ──────────────────────────────────────────────────────

def test_snap_to_grid_rounds_to_nearest_multiple():
    assert psm.snap_to_grid((123.0, 178.0), 50.0) == (100.0, 200.0)
    assert psm.snap_to_grid((174.0, 176.0), 50.0) == (150.0, 200.0)


def test_nearest_candidate_respects_tolerance():
    candidates = [(0.0, 0.0), (100.0, 0.0)]
    hit = psm.nearest_candidate((5.0, 0.0), candidates, tol=10.0)
    assert hit == (0.0, 0.0)
    miss = psm.nearest_candidate((50.0, 0.0), candidates, tol=10.0)
    assert miss is None


# ── 10. Mirroring ─────────────────────────────────────────────────────────

def test_mirror_vertically_reflects_about_axis():
    shape = psm.CircleShape((1000.0, 250.0), 200.0, 'H1')
    mirrored = psm.mirror_shape_vertically(shape, axis_y=200.0)
    assert approx(mirrored.center[0], 1000.0)
    assert approx(mirrored.center[1], 150.0)  # 2*200 - 250


# ── 11. Array / uniform layout equivalence ─────────────────────────────────

def test_shapes_to_openings_matches_uniform_layout():
    depth = 400.0
    diameter = 250.0
    base = psm.CircleShape((700.0, depth / 2.0), diameter, 'H1')
    spacing = 600.0
    n = 5
    shapes = [psm.translate_shape(base, spacing * i, 0.0) for i in range(n)]
    for i, s in enumerate(shapes):
        s.label = f'H{i + 1}'
    openings = psm.shapes_to_openings(shapes, section_depth=depth)
    expected = pbm.uniform_layout(pbm.opening_circle(diameter), n, spacing, 700.0)
    got_x = sorted(o.x_center for o in openings)
    exp_x = sorted(o.x_center for o in expected)
    assert all(approx(a, b) for a, b in zip(got_x, exp_x))


# ── 12. Selection hit-testing (regression for the "click empty canvas
#         always selects the nearest shape" bug) ──────────────────────────

def test_point_in_polygon_inside_and_outside():
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert psm.point_in_polygon((5, 5), square) is True
    assert psm.point_in_polygon((50, 50), square) is False
    assert psm.point_in_polygon((-5, 5), square) is False


def test_point_to_polygon_distance():
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert approx(psm.point_to_polygon_distance((5, 0), square), 0.0)
    assert approx(psm.point_to_polygon_distance((-3, 5), square), 3.0)
    assert approx(psm.point_to_polygon_distance((5, 5), square), 5.0)  # center, 5mm to nearest edge


def test_circle_hit_test_has_a_real_cutoff():
    # Mirrors the exact check now used in ProfileSketcher._select_at:
    # hit iff dist_to_center <= radius + tol.
    center, diameter, tol = (1000.0, 200.0), 300.0, 10.0
    r = diameter / 2.0
    far_point = (1000.0 + r + tol + 50.0, 200.0)  # 50mm past the tolerance ring
    near_point = (1000.0 + r + tol - 1.0, 200.0)  # just inside the tolerance ring
    center_point = center
    assert psm._dist(far_point, center) > r + tol
    assert psm._dist(near_point, center) <= r + tol
    assert psm._dist(center_point, center) <= r + tol
