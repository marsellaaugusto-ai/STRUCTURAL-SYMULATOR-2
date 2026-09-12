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
    is_simple_polygon, _dist,
)

__all__ = [
    'LineSegment', 'ArcSegment', 'CenterArcSegment', 'SectionOutline',
    'CircleLoop', 'SectionSketch', 'SketchWeld',
    'circle_from_3_points', 'circle_from_2_points', 'circle_from_center_point',
    'discretize_arc', 'discretize_center_arc', 'loop_points',
    'serialize_sketch', 'deserialize_sketch',
    'mirror_point', 'mirror_segment', 'mirror_loop', 'mirror_weld',
    'mirror_sketch', 'translate_point', 'translate_segment', 'translate_loop',
    'translate_weld', 'loop_bbox', 'sketch_bbox', 'bbox_union',
]

ARC_SEGMENTS = 20      # straight sub-segments per discretized 3-point arc
CIRCLE_SEGMENTS = 144  # per FULL circle; see CircleLoop for why this is finer


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


def circle_from_2_points(p1, p2):
    """Circle with p1-p2 as a DIAMETER -> (center, radius). The quickest
    way to draw a hole when what you know is the two edges it has to
    reach."""
    center = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
    return center, _dist(p1, p2) / 2.0


def circle_from_center_point(center, edge):
    """Circle from its center and any point on it -> (center, radius)."""
    return (float(center[0]), float(center[1])), _dist(center, edge)


def project_to_circle(center, radius, pt):
    """`pt` pushed onto the circle of the given center and radius.

    Clicking exactly on a circle by hand is impossible, so a center-arc
    tool that demanded it would be unusable. The projected point is what
    gets STORED, so the path stays self-consistent: the next segment
    starts where the arc actually ended, not where the mouse was."""
    dx, dy = pt[0] - center[0], pt[1] - center[1]
    d = math.hypot(dx, dy)
    if d < 1e-12:
        raise ValueError('The arc end point cannot coincide with its center -- '
                          'the direction of the arc would be undefined. Click a '
                          'point away from the center.')
    return (center[0] + radius * dx / d, center[1] + radius * dy / d)


def discretize_center_arc(center, start, end, ccw=True, n=None):
    """Points from `start` to `end` around `center`, sweeping in the given
    direction. Both endpoints are assumed already on the circle (see
    `SectionOutline.add_center_arc`, which projects them).

    Unlike `discretize_arc`, the sub-segment count SCALES with the swept
    angle rather than being fixed: a center arc is the natural way to draw
    a half or full circle, and 20 chords across 360 degrees would visibly
    polygonise it. The 3-point tool keeps its fixed count because its
    sweep is bounded by the three clicked points and changing it would
    move existing saved geometry."""
    cx, cy = center
    r = _dist(center, start)
    if r < 1e-9:
        return [tuple(start), tuple(end)]
    a0 = math.atan2(start[1] - cy, start[0] - cx)
    a1 = math.atan2(end[1] - cy, end[0] - cx)
    if ccw:
        sweep = (a1 - a0) % (2 * math.pi)
    else:
        sweep = -((a0 - a1) % (2 * math.pi))
    if abs(sweep) < 1e-9:
        sweep = 2 * math.pi if ccw else -2 * math.pi   # start == end -> full turn
    if n is None:
        n = max(6, min(240, int(math.ceil(CIRCLE_SEGMENTS * abs(sweep) / (2 * math.pi)))))
    return [(cx + r * math.cos(a0 + sweep * i / n),
             cy + r * math.sin(a0 + sweep * i / n)) for i in range(n + 1)]


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


class CenterArcSegment:
    """Arc defined by its CENTER and end point, sweeping from wherever the
    path currently is.

    This is the tool an engineer actually wants for a fillet or a rounded
    flange tip: the thing you know about such an arc is its radius and its
    center, not some third point along it. The 3-point tool can express
    the same geometry but only by finding a point on it first, which for a
    known-radius fillet means solving for it by hand."""
    kind = 'center_arc'

    def __init__(self, center, end, ccw=True):
        self.center = (float(center[0]), float(center[1]))
        self.end = (float(end[0]), float(end[1]))
        self.ccw = bool(ccw)

    @property
    def radius(self):
        return _dist(self.center, self.end)

    def to_dict(self):
        return {'kind': 'center_arc', 'center': list(self.center),
                'end': list(self.end), 'ccw': self.ccw}

    @staticmethod
    def from_dict(d):
        return CenterArcSegment(tuple(d['center']), tuple(d['end']), d.get('ccw', True))


def _segment_from_dict(sd):
    kind = sd.get('kind')
    if kind == 'arc':
        return ArcSegment.from_dict(sd)
    if kind == 'center_arc':
        return CenterArcSegment.from_dict(sd)
    return LineSegment.from_dict(sd)


class CircleLoop:
    """A complete circle as a closed loop in its own right -- the boundary
    of a round bar, or (far more often) a hole cut through a profile.

    Discretised at CIRCLE_SEGMENTS (144) rather than the 48 used for web
    openings, because a hole's polygonisation error feeds straight into
    A and I of the section itself.

    Note the DIRECTION of that error: an inscribed regular n-gon has area
    (n/2) r^2 sin(2*pi/n), which is always LESS than pi r^2, so a hole
    removes slightly too little material and the section comes out
    marginally stiffer than reality. That is a bias, not noise, so it is
    stated here rather than left to be discovered. At 144 segments it is
    0.032% of the hole's own area (it would be 0.127% at 72) -- far inside
    every other approximation in this module, root fillets included."""
    kind = 'circle'

    def __init__(self, center, radius, n=CIRCLE_SEGMENTS, label=''):
        self.center = (float(center[0]), float(center[1]))
        self.radius = float(radius)
        self.n = int(n)
        self.label = label
        if self.radius <= 0:
            raise ValueError(f'Circle radius must be positive; got {self.radius:g} mm.')
        if self.n < 8:
            raise ValueError('A circle needs at least 8 segments to be a circle.')

    def flatten(self, include_closing_segment=True):
        cx, cy = self.center
        return [(cx + self.radius * math.cos(2 * math.pi * i / self.n),
                 cy + self.radius * math.sin(2 * math.pi * i / self.n))
                for i in range(self.n)]

    def bbox(self):
        cx, cy = self.center
        r = self.radius
        return (cx - r, cy - r, cx + r, cy + r)

    def last_point(self):
        return None      # a circle is already closed; nothing continues from it

    def validate(self):
        return (True, '') if self.radius > 0 else (False, 'zero radius')

    def to_dict(self):
        return {'kind': 'circle', 'center': list(self.center),
                'radius': self.radius, 'n': self.n, 'label': self.label}

    @staticmethod
    def from_dict(d):
        return CircleLoop(tuple(d['center']), d['radius'],
                          d.get('n', CIRCLE_SEGMENTS), d.get('label', ''))


def loop_points(loop):
    """Flat polygon for either loop type -- a drawn path or a circle."""
    return loop.flatten()


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

    def add_center_arc(self, center, end, ccw=True):
        """Arc around `center`, from wherever the path currently ends to
        `end`. The radius comes from center->current point, and `end` is
        projected onto that circle before being stored (see
        `project_to_circle`) so the path stays continuous."""
        start = self.last_point()
        if start is None:
            raise ValueError('Place the start point of the outline before drawing an '
                              'arc -- an arc has to begin somewhere.')
        r = _dist(center, start)
        if r < 1e-9:
            raise ValueError('The arc center coincides with the current point, so the '
                              'arc would have zero radius. Pick a center away from it.')
        self.segments.append(CenterArcSegment(center, project_to_circle(center, r, end), ccw))

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
            elif seg.kind == 'center_arc':
                pts.extend(discretize_center_arc(seg.center, prev, seg.end, seg.ccw)[1:])
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
            out.segments.append(_segment_from_dict(sd))
        return out


def _loop_from_dict(d):
    return CircleLoop.from_dict(d) if d.get('kind') == 'circle' else SectionOutline.from_dict(d)


class SketchWeld:
    """A welded joint marked on the sketch: a straight line across the
    section, with the fillet size (if any) that is claimed for it.

    Stored here in sketch coordinates and converted to a
    welded_section_math.WeldLine on demand -- the drawing owns where the
    weld IS, that module owns what it can carry."""

    def __init__(self, p1, p2, leg=0.0, n_lines=1, side='auto', label=''):
        self.p1 = (float(p1[0]), float(p1[1]))
        self.p2 = (float(p2[0]), float(p2[1]))
        self.leg = float(leg)
        self.n_lines = int(n_lines)
        self.side = side
        self.label = label

    @property
    def length(self):
        return _dist(self.p1, self.p2)

    def to_weld_line(self):
        from apps.perforated_beam import welded_section_math as wsm
        return wsm.WeldLine(self.p1, self.p2, leg=self.leg, n_lines=self.n_lines,
                            side=self.side, label=self.label)

    def to_dict(self):
        return {'p1': list(self.p1), 'p2': list(self.p2), 'leg': self.leg,
                'n_lines': self.n_lines, 'side': self.side, 'label': self.label}

    @staticmethod
    def from_dict(d):
        return SketchWeld(tuple(d['p1']), tuple(d['p2']), d.get('leg', 0.0),
                          d.get('n_lines', 1), d.get('side', 'auto'), d.get('label', ''))


class SectionSketch:
    """A whole profile drawing: one boundary loop, any number of holes cut
    through it, and the weld lines marked on it.

    The boundary and each hole are independently either a drawn path
    (SectionOutline) or a full circle (CircleLoop), which is what lets a
    round bar, a rectangular tube, and a plate with bolt holes all be
    drawn with the same tools."""

    def __init__(self, outline=None):
        self.outline = outline if outline is not None else SectionOutline()
        self.holes = []
        self.welds = []

    # ── construction ────────────────────────────────────────────────────
    def set_circle_outline(self, center, radius):
        self.outline = CircleLoop(center, radius)

    def add_circle_hole(self, center, radius, label=''):
        self.holes.append(CircleLoop(center, radius, label=label))
        return self.holes[-1]

    def add_hole(self, loop):
        self.holes.append(loop)
        return loop

    def add_weld(self, p1, p2, leg=0.0, n_lines=1, side='auto', label=''):
        self.welds.append(SketchWeld(p1, p2, leg, n_lines, side, label))
        return self.welds[-1]

    def clear(self):
        self.outline = SectionOutline()
        self.holes = []
        self.welds = []

    # ── evaluation ──────────────────────────────────────────────────────
    def outline_points(self):
        return loop_points(self.outline)

    def hole_polygons(self):
        return [loop_points(h) for h in self.holes]

    def validate(self):
        pts = self.outline_points()
        if len(pts) < 3:
            return False, 'the outline needs at least 3 points'
        if not is_simple_polygon(pts):
            return False, 'the outline crosses itself'
        for i, h in enumerate(self.holes, 1):
            hp = loop_points(h)
            if len(hp) < 3:
                return False, f'hole {i} has fewer than 3 points'
            if not is_simple_polygon(hp):
                return False, f'hole {i} crosses itself'
        return True, ''

    def to_section(self, name='custom'):
        """-> perforated_beam_math.CustomProfileSection, holes included.
        Containment and overlap of the holes are checked there, so there
        is exactly one place that decides whether a void is legal."""
        ok, msg = self.validate()
        if not ok:
            raise ValueError(f'Cannot build section: {msg}')
        return pbm.CustomProfileSection(name, self.outline_points(), self.hole_polygons())

    def to_welded_profile(self, name='custom'):
        """-> welded_section_math.WeldedProfile, so `check_welds` can run
        against the profile exactly as drawn."""
        from apps.perforated_beam import welded_section_math as wsm
        return wsm.WeldedProfile(self.to_section(name),
                                 [w.to_weld_line() for w in self.welds])

    # ── persistence ─────────────────────────────────────────────────────
    def to_dict(self):
        return {'outline': self.outline.to_dict(),
                'holes': [h.to_dict() for h in self.holes],
                'welds': [w.to_dict() for w in self.welds]}

    @staticmethod
    def from_dict(d):
        s = SectionSketch(_loop_from_dict(d['outline']))
        s.holes = [_loop_from_dict(h) for h in d.get('holes', [])]
        s.welds = [SketchWeld.from_dict(w) for w in d.get('welds', [])]
        return s


def serialize_outline(outline, meta=None):
    return json.dumps({'meta': meta or {}, 'outline': outline.to_dict()}, indent=2)


def deserialize_outline(text):
    """Reads either an old outline-only file or a full sketch file, always
    returning just the boundary path -- kept so previously saved profiles
    still load."""
    payload = json.loads(text)
    data = payload.get('sketch', {}).get('outline') if 'sketch' in payload else payload['outline']
    return _loop_from_dict(data), payload.get('meta', {})


def serialize_sketch(sketch, meta=None):
    return json.dumps({'meta': meta or {}, 'sketch': sketch.to_dict()}, indent=2)


def deserialize_sketch(text):
    """Reads a sketch file, or upgrades an old outline-only file into a
    sketch with no holes and no welds."""
    payload = json.loads(text)
    if 'sketch' in payload:
        return SectionSketch.from_dict(payload['sketch']), payload.get('meta', {})
    return SectionSketch(_loop_from_dict(payload['outline'])), payload.get('meta', {})


# ─────────────────────────────────────────────────────────────────────────
# Transforms (mirror / move), added 2026-09-07
#
# These operate on the SKETCH, not on the flattened polygon, so a mirrored
# arc stays an arc and a mirrored circle stays a circle -- the drawing
# remains editable afterwards, which is the whole point of having a sketch
# rather than a point list.
#
# TWO THINGS FLIP THAT ARE NOT COORDINATES, and both are silent if missed:
#
#   * A CenterArcSegment's `ccw`. A reflection reverses handedness, so an
#     arc that swept counter-clockwise sweeps clockwise in the mirror.
#     Mirroring only its centre and end point leaves the geometry looking
#     right in a preview and bulging the wrong way in the flattened
#     polygon -- which changes A and I without changing anything visible
#     until the section is applied.
#
#   * A SketchWeld's `side`. 'positive'/'negative' name the side the
#     line's LEFT NORMAL points to, and mirroring reverses that normal.
#     Left unswapped, an explicitly-sided weld silently changes which
#     piece of steel it is claimed to hold.
#
# Both are pinned by tests that compare against the mirrored FLATTENED
# polygon, which is the only representation that cannot hide either error.
# ─────────────────────────────────────────────────────────────────────────

def mirror_point(p, horizontal=True, about=0.0):
    """One point reflected in a line parallel to an axis.

    `horizontal=True` is a LEFT-RIGHT flip: x is negated about the
    vertical line x = `about`. `horizontal=False` is a TOP-BOTTOM flip
    about the horizontal line y = `about`. The naming follows the way CAD
    tools label the buttons (what the user sees move), not the orientation
    of the mirror line itself."""
    x, y = float(p[0]), float(p[1])
    if horizontal:
        return (2.0 * about - x, y)
    return (x, 2.0 * about - y)


def mirror_segment(seg, horizontal=True, about=0.0):
    """One path segment, reflected. Returns a NEW segment."""
    if seg.kind == 'line':
        return LineSegment(mirror_point(seg.end, horizontal, about))
    if seg.kind == 'arc':
        return ArcSegment(mirror_point(seg.through, horizontal, about),
                          mirror_point(seg.end, horizontal, about))
    if seg.kind == 'center_arc':
        # `not seg.ccw`: see the module note above -- a reflection reverses
        # the sweep direction, and this is the line that keeps a mirrored
        # fillet bulging the same way its original did.
        return CenterArcSegment(mirror_point(seg.center, horizontal, about),
                                mirror_point(seg.end, horizontal, about),
                                not seg.ccw)
    raise ValueError(f'Cannot mirror an unknown segment kind {seg.kind!r}.')


def mirror_loop(loop, horizontal=True, about=0.0):
    """A boundary or hole loop, reflected. Returns a NEW loop of the same
    type -- a circle stays a circle rather than becoming 144 points."""
    if isinstance(loop, CircleLoop):
        return CircleLoop(mirror_point(loop.center, horizontal, about),
                          loop.radius, loop.n, loop.label)
    out = SectionOutline(mirror_point(loop.start_point, horizontal, about)
                         if loop.start_point else None)
    out.segments = [mirror_segment(s, horizontal, about) for s in loop.segments]
    return out


_OPPOSITE_SIDE = {'positive': 'negative', 'negative': 'positive', 'auto': 'auto'}


def mirror_weld(weld, horizontal=True, about=0.0):
    """A weld line, reflected -- including which side it holds.

    'auto' stays 'auto' because it is resolved from area at check time,
    not stored geometry, so it needs no adjustment."""
    return SketchWeld(mirror_point(weld.p1, horizontal, about),
                      mirror_point(weld.p2, horizontal, about),
                      weld.leg, weld.n_lines,
                      _OPPOSITE_SIDE.get(weld.side, weld.side), weld.label)


def loop_bbox(loop):
    """(xmin, ymin, xmax, ymax) of one loop, or None if it has no points."""
    if isinstance(loop, CircleLoop):
        return loop.bbox()
    pts = loop.flatten(include_closing_segment=True)
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def sketch_bbox(sketch, include_welds=True):
    """(xmin, ymin, xmax, ymax) over everything drawn, or None when the
    sketch is empty. Used for 'mirror about the selection's own centre'."""
    boxes = []
    b = loop_bbox(sketch.outline)
    if b:
        boxes.append(b)
    for h in sketch.holes:
        b = loop_bbox(h)
        if b:
            boxes.append(b)
    if include_welds:
        for w in sketch.welds:
            boxes.append((min(w.p1[0], w.p2[0]), min(w.p1[1], w.p2[1]),
                          max(w.p1[0], w.p2[0]), max(w.p1[1], w.p2[1])))
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def bbox_union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def mirror_sketch(sketch, horizontal=True, about=0.0):
    """The whole drawing reflected -- a new SectionSketch."""
    out = SectionSketch(mirror_loop(sketch.outline, horizontal, about))
    out.holes = [mirror_loop(h, horizontal, about) for h in sketch.holes]
    out.welds = [mirror_weld(w, horizontal, about) for w in sketch.welds]
    return out


def translate_point(p, dx, dy):
    return (float(p[0]) + dx, float(p[1]) + dy)


def translate_segment(seg, dx, dy):
    if seg.kind == 'line':
        return LineSegment(translate_point(seg.end, dx, dy))
    if seg.kind == 'arc':
        return ArcSegment(translate_point(seg.through, dx, dy),
                          translate_point(seg.end, dx, dy))
    if seg.kind == 'center_arc':
        # A translation preserves handedness, so `ccw` is carried unchanged
        # -- the contrast with mirror_segment is deliberate.
        return CenterArcSegment(translate_point(seg.center, dx, dy),
                                translate_point(seg.end, dx, dy), seg.ccw)
    raise ValueError(f'Cannot move an unknown segment kind {seg.kind!r}.')


def translate_loop(loop, dx, dy):
    if isinstance(loop, CircleLoop):
        return CircleLoop(translate_point(loop.center, dx, dy),
                          loop.radius, loop.n, loop.label)
    out = SectionOutline(translate_point(loop.start_point, dx, dy)
                         if loop.start_point else None)
    out.segments = [translate_segment(s, dx, dy) for s in loop.segments]
    return out


def translate_weld(weld, dx, dy):
    return SketchWeld(translate_point(weld.p1, dx, dy),
                      translate_point(weld.p2, dx, dy),
                      weld.leg, weld.n_lines, weld.side, weld.label)
