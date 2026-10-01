"""Linear selection: a straight run from one node to another.

The canvas tool (stereo_app_view._handle_line_pick_click) is two clicks on
two nodes; this is what those clicks select, kept free of Tk so it can be
tested on its own.

  * NODES  -- every node within `tol` of the segment, measured in WORLD
              space, so a row is picked and not whatever lies behind it on
              screen.
  * RODS ALONG the line -- every rod whose two ends are both on it. Such a
              rod lies within `tol` of the segment over its whole length
              (the segment's tol-neighbourhood is convex), so these are
              exactly the rods the line runs along: the chord of a row, a
              support line's edge members.
  * RODS CROSSED (optional) -- every rod the line, as DRAWN on screen,
              passes through. A rod that only touches the line at one of its
              nodes does not count, or every web rod hanging off a chord
              would come with it.
"""


def nodes_near_segment(nodes, a, b, tol):
    """Every node within `tol` of the straight segment node a -> node b."""
    if not (0 <= a < len(nodes) and 0 <= b < len(nodes)):
        return []
    ax, ay, az = nodes[a]
    bx, by, bz = nodes[b]
    dx, dy, dz = bx - ax, by - ay, bz - az
    L2 = dx * dx + dy * dy + dz * dz
    if L2 < 1e-12:
        return [a]
    tol2 = tol * tol
    out = []
    for i, (x, y, z) in enumerate(nodes):
        t = ((x - ax) * dx + (y - ay) * dy + (z - az) * dz) / L2
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        px, py, pz = ax + dx * t, ay + dy * t, az + dz * t
        if (x - px) ** 2 + (y - py) ** 2 + (z - pz) ** 2 <= tol2:
            out.append(i)
    return out


def rods_along(members, node_ids):
    """The rods with both ends among `node_ids`."""
    on = set(node_ids)
    return [j for j, m in enumerate(members) if m['a'] in on and m['b'] in on]


def _orient(p, q, r):
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])


def segments_cross(p1, p2, q1, q2, eps=1e-9):
    """Do the 2D segments p1p2 and q1q2 cross at a point INSIDE both? A
    touch at an end, or collinear overlap, is not a crossing."""
    d1 = _orient(q1, q2, p1)
    d2 = _orient(q1, q2, p2)
    d3 = _orient(p1, p2, q1)
    d4 = _orient(p1, p2, q2)
    return ((d1 > eps and d2 < -eps) or (d1 < -eps and d2 > eps)) and \
           ((d3 > eps and d4 < -eps) or (d3 < -eps and d4 > eps))


def rods_crossing(screen, members, p0, p1, skip=()):
    """The rods whose drawn segment the screen segment p0 -> p1 crosses.
    `screen` is each node's (sx, sy); rods in `skip` are left out."""
    skip = set(skip)
    out = []
    for j, m in enumerate(members):
        if j in skip:
            continue
        a, b = m['a'], m['b']
        if not (0 <= a < len(screen) and 0 <= b < len(screen)):
            continue
        if segments_cross(p0, p1, screen[a], screen[b]):
            out.append(j)
    return out


def line_selection(nodes, members, a, b, tol, screen=None, crossing=False):
    """(node ids, rod ids) a line from node `a` to node `b` selects.

    With `crossing` (and the nodes' `screen` positions), the rods the drawn
    line passes through come too."""
    picked = nodes_near_segment(nodes, a, b, tol)
    rods = rods_along(members, picked)
    if crossing and screen is not None and a < len(screen) and b < len(screen):
        rods += rods_crossing(screen, members, screen[a], screen[b], skip=rods)
    return picked, sorted(set(rods))
