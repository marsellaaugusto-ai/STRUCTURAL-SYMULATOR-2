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