"""Screen-space (2D) geometry helpers for the Stereo canvas.

Deliberately independent of Tkinter and of the model: these take plain
pixel coordinates and return plain numbers or polygons, which is what
makes them directly unit-testable without building a widget.

  _point_segment_distance -- click-to-member hit testing
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
    inside (the caller checks containment separately for speed).

    This is what makes a lasso select a ROD whose ends both lie outside the
    rubber band -- dragging a band across the middle of a long chord has to
    catch it, and an endpoint test alone never would.
    """
    def _crosses(px, py, qx, qy, rx, ry, sx, sy):
        d1x, d1y = qx - px, qy - py
        d2x, d2y = sx - rx, sy - ry
        denom = d1x * d2y - d1y * d2x
        if abs(denom) < 1e-12:
            return False            # parallel; a collinear overlap is caught
        t = ((rx - px) * d2y - (ry - py) * d2x) / denom
        u = ((rx - px) * d1y - (ry - py) * d1x) / denom
        return 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0

    edges = (
        (xmin, ymin, xmax, ymin),
        (xmax, ymin, xmax, ymax),
        (xmax, ymax, xmin, ymax),
        (xmin, ymax, xmin, ymin),
    )
    for ex0, ey0, ex1, ey1 in edges:
        if _crosses(ax, ay, bx, by, ex0, ey0, ex1, ey1):
            return True
    return False
