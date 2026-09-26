"""Screen-space (2D) geometry helpers for the Stereo canvas.

Deliberately independent of Tkinter and of the model: these take plain
pixel coordinates and return plain numbers or polygons, which is what
makes them directly unit-testable without building a widget.

  _point_segment_distance -- click-to-member hit testing
  _clip_polygon_to_bbox   -- Sutherland-Hodgman clip (exact for the convex
                             polygons Voronoi produces)
  _voronoi_cells_2d       -- one bounded Voronoi cell per screen point,
                             for the Voronoi tessellation render mode
"""
import math

def _point_segment_distance(px, py, ax, ay, bx, by):
    """Shortest distance from point (px, py) to the line SEGMENT (not
    infinite line) from (ax, ay) to (bx, by) -- used for click-to-inspect
    hit-testing against a member's own screen-space line."""
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    nx, ny = ax + t * dx, ay + t * dy
    return math.hypot(px - nx, py - ny)


def _seg_intersects_rect(ax, ay, bx, by, xmin, ymin, xmax, ymax):
    """True when the segment (ax,ay)-(bx,by) crosses the axis-aligned
    rectangle [xmin,ymin]-[xmax,ymax], assuming neither endpoint is
    inside (the caller checks containment separately for speed)."""
    def _cross(px, py, qx, qy, rx, ry, sx, sy):
        d1x, d1y = qx - px, qy - py
        d2x, d2y = sx - rx, sy - ry
        denom = d1x * d2y - d1y * d2x
        if abs(denom) < 1e-12:
            return False
        t = ((rx - px) * d2y - (ry - py) * d2x) / denom
        u = ((rx - px) * d1y - (ry - py) * d1x) / denom
        return 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0
    edges = [
        (xmin, ymin, xmax, ymin),
        (xmax, ymin, xmax, ymax),
        (xmax, ymax, xmin, ymax),
        (xmin, ymax, xmin, ymin),
    ]
    for ex0, ey0, ex1, ey1 in edges:
        if _cross(ax, ay, bx, by, ex0, ey0, ex1, ey1):
            return True
    return False


def _clip_polygon_to_bbox(poly, xmin, ymin, xmax, ymax):
    """Sutherland-Hodgman clip of a convex polygon (list of (x, y) points)
    against an axis-aligned rectangle -- every Voronoi cell is convex, so
    this is exact (no need for a general, non-convex clipper)."""

    def clip_edge(points, inside, intersect):
        if not points:
            return []
        out = []
        prev = points[-1]
        prev_in = inside(prev)
        for cur in points:
            cur_in = inside(cur)
            if cur_in:
                if not prev_in:
                    out.append(intersect(prev, cur))
                out.append(cur)
            elif prev_in:
                out.append(intersect(prev, cur))
            prev, prev_in = cur, cur_in
        return out

    def inter_x(p0, p1, x):
        t = (x - p0[0]) / (p1[0] - p0[0])
        return (x, p0[1] + t * (p1[1] - p0[1]))

    def inter_y(p0, p1, y):
        t = (y - p0[1]) / (p1[1] - p0[1])
        return (p0[0] + t * (p1[0] - p0[0]), y)

    poly = clip_edge(poly, lambda p: p[0] >= xmin, lambda a, b: inter_x(a, b, xmin))
    poly = clip_edge(poly, lambda p: p[0] <= xmax, lambda a, b: inter_x(a, b, xmax))
    poly = clip_edge(poly, lambda p: p[1] >= ymin, lambda a, b: inter_y(a, b, ymin))
    poly = clip_edge(poly, lambda p: p[1] <= ymax, lambda a, b: inter_y(a, b, ymax))
    return poly


def _voronoi_cells_2d(points, bbox_pad=40.0):
    """2D Voronoi cells (screen-space) for `points` (a list of (x, y)
    pairs) -- one convex polygon per input point, clipped to a padded
    bounding box of the points themselves. Returns a list of (point
    index, flat [x0, y0, x1, y1, ...] polygon) pairs, ready for
    canvas.create_polygon; a point whose natural cell is degenerate after
    clipping (fewer than 3 vertices survive) is simply omitted.

    scipy.spatial.Voronoi's own regions are UNBOUNDED at the edge of the
    point set (there is no natural boundary to a Voronoi diagram) --
    plotting those directly would need infinite polygons. The standard
    fix, used here: add a handful of "ghost" points far outside the real
    data (>= 10x its own span away) purely to give every real point's
    region a finite far boundary, then clip every resulting polygon down
    to the actual padded bounding box. The ghost points themselves are
    never returned as cells.

    Returns [] outright for fewer than 4 points (scipy.spatial.Voronoi's
    own minimum for a 2D diagram) rather than raising -- callers already
    treat "nothing to draw" as a normal, silent outcome elsewhere in this
    module (see e.g. _get_shaded_cells). An exactly-collinear real point
    set does NOT hit this case despite having no 2D diagram of its own:
    the off-axis ghost points make the COMBINED set non-degenerate, so
    scipy still returns a (possibly strip-shaped) cell for every point.
    """
    if len(points) < 4:
        return []
    try:
        from scipy.spatial import Voronoi, QhullError
    except ImportError:
        try:
            import common as _common
            _common._ensure_scipy()
            from scipy.spatial import Voronoi, QhullError
        except Exception:
            return []

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    xmin, xmax = min(xs) - bbox_pad, max(xs) + bbox_pad
    ymin, ymax = min(ys) - bbox_pad, max(ys) + bbox_pad
    span = max(xmax - xmin, ymax - ymin, 1.0) * 10.0
    cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
    ghosts = [(cx - span, cy - span), (cx + span, cy - span),
             (cx - span, cy + span), (cx + span, cy + span),
             (cx, cy - span), (cx, cy + span), (cx - span, cy), (cx + span, cy)]
    try:
        vor = Voronoi(list(points) + ghosts)
    except (QhullError, ValueError):
        return []   # degenerate (e.g. exactly collinear) input

    out = []
    for i in range(len(points)):
        region = vor.regions[vor.point_region[i]]
        if not region or -1 in region:
            continue   # still-unbounded despite the ghosts -- skip rather than guess
        poly = [tuple(vor.vertices[v]) for v in region]
        clipped = _clip_polygon_to_bbox(poly, xmin, ymin, xmax, ymax)
        if len(clipped) >= 3:
            out.append((i, [c for pt in clipped for c in pt]))
    return out
