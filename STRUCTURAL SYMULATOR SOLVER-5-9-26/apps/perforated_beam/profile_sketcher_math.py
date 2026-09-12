"""
Profile sketcher -- pure geometry engine.

This module has NO tkinter import and knows nothing about drawing. It owns:
  - the sketch shape data model (circles + closed polygons, in absolute
    "world" mm coordinates: x along the beam axis, y measured from the
    bottom fiber of the section upward),
  - snapping math (grid / endpoint / midpoint / center),
  - typed precision-entry parsing ("x,y" / "@dx,dy" / "length<angle"),
  - simple / y-simple polygon validation (reusing perforated_beam_math's
    own rules so a sketched opening behaves exactly like a manually
    entered one),
  - conversion of finished shapes into the engine's own
    `perforated_beam_math.OpeningInstance` objects,
  - JSON serialization / deserialization of a whole sketch.

perforated_beam_app.py / profile_sketcher_ui.py are the only intended
callers. See apps/perforated_beam/README.md for the data-flow diagram.
"""
import json
import math

from apps.perforated_beam import perforated_beam_math as pbm

__all__ = [
    'CircleShape', 'PolygonShape',
    'polygon_area', 'polygon_centroid',
    'is_simple_polygon', 'is_y_simple', 'validate_polygon',
    'point_in_polygon', 'point_to_polygon_distance',
    'snap_to_grid', 'nearest_candidate', 'endpoint_candidates',
    'midpoint_candidates', 'center_candidates',
    'parse_typed_entry',
    'shape_to_opening_instance', 'shapes_to_openings',
    'serialize_shapes', 'deserialize_shapes',
    'mirror_shape_vertically', 'translate_shape',
]


# ─────────────────────────────────────────────────────────────────────────
# 1. Shape data model
# ─────────────────────────────────────────────────────────────────────────

class CircleShape:
    """A circular opening. `center` is (x, y) in absolute world mm."""
    kind = 'circle'

    def __init__(self, center, diameter, label=''):
        self.center = (float(center[0]), float(center[1]))
        self.diameter = float(diameter)
        self.label = label

    def bbox(self):
        cx, cy = self.center
        r = self.diameter / 2.0
        return cx - r, cy - r, cx + r, cy + r

    def to_dict(self):
        return {'kind': 'circle', 'center': list(self.center),
                'diameter': self.diameter, 'label': self.label}

    @staticmethod
    def from_dict(d):
        return CircleShape(tuple(d['center']), d['diameter'], d.get('label', ''))


class PolygonShape:
    """A closed polygon opening (from Line/Polyline/Polygon/Rectangle
    tools). `vertices` are absolute world mm, in order, NOT repeating the
    first point at the end."""
    kind = 'polygon'

    def __init__(self, vertices, label=''):
        self.vertices = [(float(x), float(y)) for x, y in vertices]
        self.label = label

    def bbox(self):
        xs = [v[0] for v in self.vertices]
        ys = [v[1] for v in self.vertices]
        return min(xs), min(ys), max(xs), max(ys)

    def to_dict(self):
        return {'kind': 'polygon', 'vertices': [list(v) for v in self.vertices],
                'label': self.label}

    @staticmethod
    def from_dict(d):
        return PolygonShape([tuple(v) for v in d['vertices']], d.get('label', ''))


# ─────────────────────────────────────────────────────────────────────────
# 2. Polygon geometry helpers
# ─────────────────────────────────────────────────────────────────────────

def polygon_area(vertices):
    """Signed shoelace area (positive = CCW)."""
    n = len(vertices)
    a = 0.0
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def polygon_centroid(vertices):
    """Area-weighted centroid. Falls back to the vertex average for
    degenerate (near-zero-area) shapes, e.g. while the user is still
    dragging out a 2-point line."""
    a = polygon_area(vertices)
    n = len(vertices)
    if abs(a) < 1e-9:
        xs = [v[0] for v in vertices]
        ys = [v[1] for v in vertices]
        return sum(xs) / n, sum(ys) / n
    cx = cy = 0.0
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    return cx / (6 * a), cy / (6 * a)


def _segments_intersect(p1, p2, p3, p4):
    """True if segment p1-p2 properly crosses segment p3-p4 (shared
    endpoints between ADJACENT edges of the same polygon are excluded by
    the caller, not here)."""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    d1 = cross(p3, p4, p1)
    d2 = cross(p3, p4, p2)
    d3 = cross(p1, p2, p3)
    d4 = cross(p1, p2, p4)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def is_simple_polygon(vertices):
    """Checks for self-intersection among non-adjacent edges."""
    n = len(vertices)
    if n < 3:
        return False
    edges = [(vertices[i], vertices[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i or j == (i + 1) % n or i == (j + 1) % n:
                continue  # adjacent (or same) edges share an endpoint by construction
            if _segments_intersect(edges[i][0], edges[i][1], edges[j][0], edges[j][1]):
                return False
    return True


def is_y_simple(vertices, samples=200):
    """Mirrors the assumption documented on pbm.opening_polygon: any
    vertical line through the shape's x-range must cross the boundary at
    exactly one entry/exit pair. Sampled numerically (good enough to warn
    a user drawing by hand; not a formal proof)."""
    xs = [v[0] for v in vertices]
    xmin, xmax = min(xs), max(xs)
    span = xmax - xmin
    if span <= 1e-9:
        return False
    n = len(vertices)
    for i in range(1, samples):
        x = xmin + span * i / samples
        crossings = 0
        for k in range(n):
            x1, y1 = vertices[k]
            x2, y2 = vertices[(k + 1) % n]
            if x1 == x2:
                continue
            lo, hi = (x1, x2) if x1 < x2 else (x2, x1)
            if lo <= x < hi or (x2 < x1 and x2 <= x < x1):
                crossings += 1
        if crossings not in (0, 2):
            return False
    return True


def validate_polygon(vertices):
    """Returns (ok, message). `message` explains the first problem found,
    or is empty when ok."""
    if len(vertices) < 3:
        return False, 'needs at least 3 vertices'
    if not is_simple_polygon(vertices):
        return False, 'self-intersecting outline'
    if not is_y_simple(vertices):
        return False, ('re-entrant shape: a vertical line through it crosses the '
                        'boundary more than twice, which the analysis engine '
                        'cannot resolve (see opening_polygon() limitations)')
    return True, ''


def point_in_polygon(point, vertices):
    """Even-odd ray-casting point-in-polygon test."""
    x, y = point
    n = len(vertices)
    inside = False
    x1, y1 = vertices[-1]
    for i in range(n):
        x2, y2 = vertices[i]
        if (y1 > y) != (y2 > y):
            x_at_y = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < x_at_y:
                inside = not inside
        x1, y1 = x2, y2
    return inside


def _point_to_segment_distance(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return _dist(p, a)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return _dist(p, (ax + t * dx, ay + t * dy))


def point_to_polygon_distance(point, vertices):
    """Minimum distance from `point` to any edge of the (closed) polygon."""
    n = len(vertices)
    return min(_point_to_segment_distance(point, vertices[i], vertices[(i + 1) % n])
               for i in range(n))


def mirror_shape_vertically(shape, axis_y):
    """Mirror a shape about the horizontal line y = axis_y (e.g. the
    section mid-depth), for building asymmetric hole patterns."""
    if shape.kind == 'circle':
        cx, cy = shape.center
        return CircleShape((cx, 2 * axis_y - cy), shape.diameter, shape.label)
    return PolygonShape([(x, 2 * axis_y - y) for x, y in shape.vertices], shape.label)


def translate_shape(shape, dx, dy):
    if shape.kind == 'circle':
        cx, cy = shape.center
        return CircleShape((cx + dx, cy + dy), shape.diameter, shape.label)
    return PolygonShape([(x + dx, y + dy) for x, y in shape.vertices], shape.label)


# ─────────────────────────────────────────────────────────────────────────
# 3. Snapping
# ─────────────────────────────────────────────────────────────────────────

def snap_to_grid(point, grid_size):
    if not grid_size:
        return point
    x, y = point
    return round(x / grid_size) * grid_size, round(y / grid_size) * grid_size


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def endpoint_candidates(shapes):
    pts = []
    for s in shapes:
        if s.kind == 'polygon':
            pts.extend(s.vertices)
        else:
            cx, cy = s.center
            r = s.diameter / 2.0
            pts.extend([(cx - r, cy), (cx + r, cy), (cx, cy - r), (cx, cy + r)])
    return pts


def midpoint_candidates(shapes):
    pts = []
    for s in shapes:
        if s.kind != 'polygon':
            continue
        n = len(s.vertices)
        for i in range(n):
            x1, y1 = s.vertices[i]
            x2, y2 = s.vertices[(i + 1) % n]
            pts.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0))
    return pts


def center_candidates(shapes):
    pts = []
    for s in shapes:
        if s.kind == 'circle':
            pts.append(s.center)
        else:
            pts.append(polygon_centroid(s.vertices))
    return pts


def nearest_candidate(point, candidates, tol):
    """Returns the closest candidate point within `tol` world units, or
    None. `tol` should already be converted from screen pixels to world
    units by the caller (it depends on current zoom)."""
    best, best_d = None, tol
    for c in candidates:
        d = _dist(point, c)
        if d <= best_d:
            best, best_d = c, d
    return best


# ─────────────────────────────────────────────────────────────────────────
# 4. Typed precision entry ("x,y" / "@dx,dy" / "length<angle")
# ─────────────────────────────────────────────────────────────────────────

def parse_typed_entry(text, ref_point=None):
    """Parses AutoCAD-style coordinate entry.

      "120,45"        -> absolute point (120, 45)
      "@30,-10"       -> ref_point + (30, -10)
      "150<0"         -> ref_point + 150mm at 0 degrees (CCW from +x)
      "150<90"        -> ref_point + 150mm straight up

    Raises ValueError with a human-readable message on bad input.
    """
    t = text.strip()
    if not t:
        raise ValueError('empty entry')
    if '<' in t:
        length_s, angle_s = t.lstrip('@').split('<', 1)
        length = float(length_s)
        angle = math.radians(float(angle_s))
        if ref_point is None:
            raise ValueError('length<angle needs a reference point')
        return ref_point[0] + length * math.cos(angle), ref_point[1] + length * math.sin(angle)
    relative = t.startswith('@')
    body = t[1:] if relative else t
    if ',' not in body:
        raise ValueError('expected "x,y", "@dx,dy" or "length<angle"')
    xs, ys = body.split(',', 1)
    x, y = float(xs), float(ys)
    if relative:
        if ref_point is None:
            raise ValueError('@dx,dy needs a reference point')
        return ref_point[0] + x, ref_point[1] + y
    return x, y


# ─────────────────────────────────────────────────────────────────────────
# 5. Conversion to the analysis engine's data model
# ─────────────────────────────────────────────────────────────────────────

def shape_to_opening_instance(shape, section_depth, label=None):
    """Converts one sketch shape (absolute world mm) into a
    pbm.OpeningInstance, using `section_depth` to place the local y=0 at
    the CURRENT section's mid-depth (per OpeningInstance's documented
    convention) -- this is resolved at conversion time, not at draw time,
    so a sketch drawn against one section still applies sensibly if the
    user later switches sections.
    """
    lbl = label if label is not None else shape.label
    mid = section_depth / 2.0
    if shape.kind == 'circle':
        cx, cy = shape.center
        base = pbm.opening_circle(shape.diameter)
        offset = cy - mid
        vertices_local = [(vx, vy + offset) for vx, vy in base]
        return pbm.OpeningInstance(cx, vertices_local, lbl)

    ok, msg = validate_polygon(shape.vertices)
    if not ok:
        raise ValueError(f'shape "{lbl}": {msg}')
    cx, _cy = polygon_centroid(shape.vertices)
    vertices_local = [(vx - cx, vy - mid) for vx, vy in shape.vertices]
    return pbm.OpeningInstance(cx, pbm.opening_polygon(vertices_local), lbl)


def shapes_to_openings(shapes, section_depth):
    """Converts a whole sketch. Raises ValueError (naming the offending
    shape) on the first invalid polygon -- callers should catch this and
    surface it rather than silently dropping shapes."""
    return [shape_to_opening_instance(s, section_depth) for s in shapes]


# ─────────────────────────────────────────────────────────────────────────
# 6. Persistence
# ─────────────────────────────────────────────────────────────────────────

def serialize_shapes(shapes, meta=None):
    payload = {'meta': meta or {}, 'shapes': [s.to_dict() for s in shapes]}
    return json.dumps(payload, indent=2)


def deserialize_shapes(text):
    payload = json.loads(text)
    out = []
    for d in payload.get('shapes', []):
        if d.get('kind') == 'circle':
            out.append(CircleShape.from_dict(d))
        else:
            out.append(PolygonShape.from_dict(d))
    return out, payload.get('meta', {})
