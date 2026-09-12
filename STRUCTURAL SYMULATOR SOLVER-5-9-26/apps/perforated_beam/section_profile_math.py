"""
Custom section-profile designer -- pure geometry engine (no tkinter).

Unlike profile_sketcher_math.py (which manages several independent closed
shapes representing web OPENINGS), this module manages a SINGLE continuous
outline representing a cross-section's own outer boundary, built from an
ordered sequence of line and 3-point-arc segments. It reuses
profile_sketcher_math's snapping / typed-entry / self-intersection helpers
rather than duplicating them.

Flow: user places points (Line tool) or 3-point arcs (Arc tool) -> the
high-level segment list is kept for editing/redraw -> `flatten()` turns
it into a plain polygon (arcs discretized) -> `to_section()` wraps that
polygon as a perforated_beam_math.CustomProfileSection, which computes
A/I/S/d numerically -- no shape-specific formula needed here at all.
"""
import json
import math

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam.profile_sketcher_math import (  # re-used, not duplicated
    snap_to_grid, nearest_candidate, parse_typed_entry,
    is_simple_polygon, polygon_area, polygon_centroid, _dist,
)

__all__ = [
    'LineSegment', 'ArcSegment', 'SectionOutline',
    'circle_from_3_points', 'discretize_arc',
]

ARC_SEGMENTS = 20  # straight sub-segments per discretized arc, for math + drawing


def circle_from_3_points(p1, p2, p3):
    """Circumcircle of 3 points -> (center, radius), or None if collinear
    (degenerate -- caller should fall back to a straight line)."""
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax ** 2 + ay ** 2) * (by - cy) + (bx ** 2 + by ** 2) * (cy - ay)
          + (cx ** 2 + cy ** 2) * (ay - by)) / d
    uy = ((ax ** 2 + ay ** 2) * (cx - bx) + (bx ** 2 + by ** 2) * (ax - cx)
          + (cx ** 2 + cy ** 2) * (bx - ax)) / d
    center = (ux, uy)
    r = _dist(p1, center)
    return center, r


def discretize_arc(start, through, end, n=ARC_SEGMENTS):
    """Points from `start` to `end` (inclusive) along the circle defined by
    the 3 points, sweeping whichever direction actually passes through
    `through`. Falls back to a straight [start, end] if the 3 points are
    (near-)collinear."""
    circ = circle_from_3_points(start, through, end)
    if circ is None:
        return [start, end]
    (cx, cy), r = circ
    if r < 1e-9:
        return [start, end]

    def angle(p):
        return math.atan2(p[1] - cy, p[0] - cx) % (2 * math.pi)

    a0, a1, am = angle(start), angle(end), angle(through)
    span_ccw = (a1 - a0) % (2 * math.pi)
    rel_m = (am - a0) % (2 * math.pi)
    if rel_m <= span_ccw:
        sweep, direction = span_ccw, 1
    else:
        sweep, direction = (2 * math.pi - span_ccw), -1
    pts = []
    for i in range(n + 1):
        a = a0 + direction * sweep * (i / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


class LineSegment:
    kind = 'line'

    def __init__(self, end):
        self.end = (float(end[0]), float(end[1]))

    def to_dict(self):
        return {'kind': 'line', 'end': list(self.end)}

    @staticmethod
    def from_dict(d):
        return LineSegment(tuple(d['end']))


class ArcSegment:
    kind = 'arc'

    def __init__(self, through, end):
        self.through = (float(through[0]), float(through[1]))
        self.end = (float(end[0]), float(end[1]))

    def to_dict(self):
        return {'kind': 'arc', 'through': list(self.through), 'end': list(self.end)}

    @staticmethod
    def from_dict(d):
        return ArcSegment(tuple(d['through']), tuple(d['end']))


class SectionOutline:
    """An ordered path starting at `start_point`, followed by a sequence
    of LineSegment/ArcSegment objects, implicitly closed back to
    `start_point` for math purposes (the UI shows that closing segment as
    a preview but the user doesn't have to click it into existence)."""

    def __init__(self, start_point=None):
        self.start_point = tuple(start_point) if start_point else None
        self.segments = []  # LineSegment | ArcSegment

    def clear(self):
        self.start_point = None
        self.segments = []

    def last_point(self):
        if self.segments:
            return self.segments[-1].end
        return self.start_point

    def add_line(self, end):
        self.segments.append(LineSegment(end))

    def add_arc(self, through, end):
        self.segments.append(ArcSegment(through, end))

    def undo_last(self):
        if self.segments:
            self.segments.pop()
        elif self.start_point is not None:
            self.start_point = None

    def flatten(self, include_closing_segment=True):
        """Returns a flat [(x, y), ...] polygon -- arcs discretized,
        NOT repeating the start point at the end. `include_closing_segment`
        controls whether the implicit close-back-to-start edge is assumed
        to be a straight line (True, the normal case) or the caller will
        handle closure themselves (False -- used while still drawing, to
        preview the open path)."""
        if self.start_point is None:
            return []
        pts = [self.start_point]
        prev = self.start_point
        for seg in self.segments:
            if seg.kind == 'line':
                pts.append(seg.end)
            else:
                arc_pts = discretize_arc(prev, seg.through, seg.end)
                pts.extend(arc_pts[1:])  # skip the duplicate start point
            prev = seg.end
        # drop an exact duplicate of the start point if the last segment
        # already closed back onto it
        if len(pts) > 1 and _dist(pts[-1], pts[0]) < 1e-6:
            pts.pop()
        return pts

    def is_closed_enough(self, tol):
        """True if the current end point is within `tol` of the start
        point -- i.e. the user has effectively closed the loop."""
        if self.start_point is None or not self.segments:
            return False
        return _dist(self.last_point(), self.start_point) <= tol

    def validate(self):
        pts = self.flatten()
        if len(pts) < 3:
            return False, 'needs at least 3 points'
        if not is_simple_polygon(pts):
            return False, 'self-intersecting outline'
        return True, ''

    def to_section(self, name='custom'):
        ok, msg = self.validate()
        if not ok:
            raise ValueError(f'Cannot build section: {msg}')
        return pbm.CustomProfileSection(name, self.flatten())

    def to_dict(self):
        return {'start_point': list(self.start_point) if self.start_point else None,
                'segments': [s.to_dict() for s in self.segments]}

    @staticmethod
    def from_dict(d):
        out = SectionOutline(tuple(d['start_point']) if d.get('start_point') else None)
        for sd in d.get('segments', []):
            out.segments.append(ArcSegment.from_dict(sd) if sd['kind'] == 'arc' else LineSegment.from_dict(sd))
        return out


def serialize_outline(outline, meta=None):
    return json.dumps({'meta': meta or {}, 'outline': outline.to_dict()}, indent=2)


def deserialize_outline(text):
    payload = json.loads(text)
    return SectionOutline.from_dict(payload['outline']), payload.get('meta', {})
