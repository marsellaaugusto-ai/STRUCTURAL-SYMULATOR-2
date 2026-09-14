"""Add-on features that AUGMENT an existing Stereo mesh.

Unlike every stereo_geometry_* family module, these two do not build a
mesh from scratch -- they take the nodes/members a generator already
produced and add to them, which is the "add a feature to what is already
there" tool a real space-frame designer reaches for once the base grid is
in place:

  add_column        -- a column (shaft + capital) under chosen nodes
  reinforcement_beam -- a deeper beam strip along a chosen edge

Both mutate the lists passed in and return the ids they created.
"""
import math

from apps.stereo.stereo_geometry_core import _add_member

# How the column carries the capital down to the ground. Every style ends in
# the SAME capital fan -- what differs is the structure between the head and
# the foundation, which is what a real space-frame column actually varies.
#
#   SHAFT     one strut. The reference case: a round or square section
#             column, the steel doing its work inside the section rather
#             than in a lattice (the red columns and the yellow tree column
#             in the reference photos).
#   LATTICE   four chords on a square footprint, tied at intervals and
#             X-braced on all four faces -- a space truss in its own right,
#             which is how a tall or heavily loaded space-frame column is
#             normally built, and what the lattice-portal reference photos
#             show. It bears on FOUR feet, not one.
#   TAPERED   the same lattice narrowing towards the ground, so the column
#             reads as a branching tree under the grid it carries.
#   LEGS      four inclined struts from a square footprint up to one head --
#             the "candelabra" support: no lattice to fabricate, but the
#             splayed feet give it the base width a single pin cannot.
COLUMN_SHAFT = 'Single shaft'
COLUMN_LATTICE = 'Latticed (4 chords)'
COLUMN_TAPERED = 'Latticed, tapered'
COLUMN_LEGS = 'Four inclined legs'
COLUMN_STYLES = (COLUMN_SHAFT, COLUMN_LATTICE, COLUMN_TAPERED, COLUMN_LEGS)

# The reinforcement beam's CROSS-SECTION, as lateral positions across the two
# base rows: 0.0 is the midline between them, +-1.0 is directly under each.
#
#   TRIANGLE  one chord on the midline. The lightest section for its depth
#             and the one that needs no bottom bracing, since a single chord
#             cannot lozenge -- but its whole bottom flange is one member, so
#             it is the weakest of the three in lateral bending.
#   BOX       two chords, one under each base row: a closed rectangular
#             girder. Twice the bottom flange area and far stiffer about the
#             vertical axis, at the cost of a second chord line and the
#             bracing that keeps the bottom plane square.
#   TRAPEZOID two chords at half the base width -- the compromise, and the
#             section most often rolled for a roof girder, because the
#             inclined side faces shed water and the narrower bottom needs
#             less bracing than a full box.
BEAM_TRIANGLE = 'Triangular'
BEAM_BOX = 'Box (rectangular)'
BEAM_TRAPEZOID = 'Trapezoidal'
BEAM_PROFILES = (BEAM_TRIANGLE, BEAM_BOX, BEAM_TRAPEZOID)
BEAM_PROFILE_OFFSETS = {BEAM_TRIANGLE: (0.0,),
                        BEAM_BOX: (-1.0, 1.0),
                        BEAM_TRAPEZOID: (-0.5, 0.5)}


def _square_ring(nodes, cx, cy, z, half):
    """Four new nodes on a square of side 2*half, centred on (cx, cy) at z."""
    ring = []
    for dx, dy in ((-half, -half), (half, -half), (half, half), (-half, half)):
        ring.append(len(nodes))
        nodes.append((cx + dx, cy + dy, z))
    return ring


def _build_shaft(nodes, members, seen, style, cx, cy, head, head_z, foot_z,
                 width, panels):
    """Everything between the capital head and the ground, per style.

    Returns the list of FOUNDATION nodes -- four of them for every style but
    the single shaft. A latticed or splay-footed column standing on one pin
    is a mechanism: the lattice is rigid as a body, so a single point of
    restraint leaves it three rotations short, which the solver reports as a
    mechanism rather than a result. The caller pins every foot returned.
    """
    if style == COLUMN_SHAFT:
        base = len(nodes)
        nodes.append((cx, cy, foot_z))
        _add_member(members, seen, base, head, role='column_shaft')
        return [base]

    if style == COLUMN_LEGS:
        feet = _square_ring(nodes, cx, cy, foot_z, width / 2.0)
        for f in feet:
            _add_member(members, seen, f, head, role='column_shaft')
        # The feet are tied into a closed square. Without it each leg is a
        # two-force member between one pin and one shared head, and the four
        # of them fold about the head like an umbrella.
        for a, b in zip(feet, feet[1:] + feet[:1]):
            _add_member(members, seen, a, b, role='column_tie')
        return feet

    # ── the two latticed styles ──────────────────────────────────────────
    taper = 0.45 if style == COLUMN_TAPERED else 1.0
    panels = max(1, int(panels))
    levels = []
    for k in range(panels + 1):
        t = k / panels                       # 0 at the foot, 1 at the head
        z = foot_z + t * (head_z - foot_z)
        half = 0.5 * width * (taper + (1.0 - taper) * t)
        levels.append(_square_ring(nodes, cx, cy, z, half))
    for ring in levels:                      # horizontal ties at every level
        for a, b in zip(ring, ring[1:] + ring[:1]):
            _add_member(members, seen, a, b, role='column_tie')
    for lo, hi in zip(levels, levels[1:]):   # chords and X bracing per face
        for i in range(4):
            j = (i + 1) % 4
            _add_member(members, seen, lo[i], hi[i], role='column_chord')
            _add_member(members, seen, lo[i], hi[j], role='column_web')
            _add_member(members, seen, lo[j], hi[i], role='column_web')
    for n in levels[-1]:                     # the top ring carries the head
        _add_member(members, seen, n, head, role='column_chord')
    return levels[0]


def add_column(nodes, members, target_nodes, height, tiers=1,
               style=COLUMN_SHAFT, capital_height=None, width=None, panels=4):
    """Add a column supporting the mesh at `target_nodes`: a vertical SHAFT
    from a new ground-level node up to a new "head" node just below the
    surface, and a CAPITAL fanning from that head out to EVERY node in
    `target_nodes` -- the exact attachment points the caller (the UI's
    lasso selection) chose, not an automatically-guessed nearest-neighbour
    set. The capital is always literally a MODULAR EXTENSION of the grid
    it meets: it never invents its own geometry, it just fans the head
    (tiers=1) or a ring of intermediate nodes (tiers=2) out to whichever
    real grid nodes the caller selected.

    This is the standard space-frame column detail: a column landing on a
    single joint would concentrate its whole reaction (and, in the other
    direction, its whole point load) onto that one node -- "piercing" the
    space truss, well beyond what one joint and the handful of members
    meeting there are sized for. Fanning the head out to several
    neighbouring nodes through the capital spreads that force into the
    grid the way it is actually built to carry load, before it ever
    reaches any single node above the column.

    target_nodes : >= 3 existing node indices the capital attaches to
                   (e.g. every node of one or a few grid modules, selected
                   with a lasso box in the UI).
    height       : shaft length (m), from the foundation up to the head
                   (tiers=1) or the intermediate ring (tiers=2).
    style        : one of COLUMN_STYLES -- what carries the head down to the
                   ground. See that table for what each one is and why it
                   bears on the number of feet it does.
    capital_height : how far the head sits BELOW the attachment surface, and
                   so how deep the capital fan is (m). None derives the old
                   default, 0.3 x the shaft height, which is what every
                   caller got before this was adjustable. Setting it is the
                   difference between a shallow, wide-spreading capital and
                   a deep, steep one, and it changes the load path: a
                   shallower capital drives more force into the capital legs
                   and less into the grid's own chords.
    width        : across-flats of a latticed or splay-footed column (m).
                   None takes a fifth of the shaft height, which keeps the
                   proportions of the reference photos at any scale.
    panels       : how many horizontal ties a latticed column is divided
                   into over its height.
    tiers        : 1 (default) -- a single inverted-pyramid module: the
                   head fans DIRECTLY to every node in `target_nodes`, the
                   plain capital under one module's worth of load.
                   2 -- "two modules thick": for a heavier column that
                   would overwhelm a single-module transition, the capital
                   gets literally deeper as well as wider. `target_nodes`
                   is split into 4 angular quadrants around its own
                   centroid (each needs >= 2 nodes -- a real two-module
                   capital always has more than one module's worth of
                   attachment points); the head fans to one new
                   INTERMEDIATE node per quadrant (a smaller inner
                   pyramid), each intermediate node then fans on to its
                   own quadrant's target nodes (a second, outer pyramid
                   tier), and the intermediate nodes are tied to each
                   other in a ring. That ring is not optional bracing: a
                   quadrant's intermediate node otherwise has only 3
                   independent directions (the shaft-side leg plus its 2
                   target legs), which numbers out (Maxwell count) but
                   left the whole head+intermediates cluster 2 DOF short
                   of rigid at ordinary sizes -- found by eigenanalysis,
                   fixed by ONE tie between each pair of neighbouring
                   intermediate nodes.

    Returns (nodes, members, base_nodes, head_node) -- new lists, the mesh's
    own node/member lists are not mutated in place. `base_nodes` is a LIST
    because only the single-shaft style stands on one point: a latticed or
    splay-footed column is rigid as a body, so pinning one node of it leaves
    three rotations free and the solver reports a mechanism. Every foot
    returned has to be restrained.
    """
    target_nodes = list(target_nodes)
    if len(target_nodes) < 3:
        raise ValueError('a capital needs at least 3 attachment nodes to distribute load usefully.')
    for j in target_nodes:
        if not (0 <= j < len(nodes)):
            raise ValueError(f'target node {j} does not exist.')
    if height <= 0:
        raise ValueError('height must be positive.')
    if tiers not in (1, 2):
        raise ValueError('tiers must be 1 or 2.')

    if style not in COLUMN_STYLES:
        raise ValueError(f'unknown column style {style!r}.')
    if capital_height is not None and capital_height <= 0:
        raise ValueError('capital height must be positive.')
    if width is not None and width <= 0:
        raise ValueError('column width must be positive.')

    cx = sum(nodes[j][0] for j in target_nodes) / len(target_nodes)
    cy = sum(nodes[j][1] for j in target_nodes) / len(target_nodes)
    cz = sum(nodes[j][2] for j in target_nodes) / len(target_nodes)

    nodes = list(nodes)
    members = list(members)
    seen = {(min(m['a'], m['b']), max(m['a'], m['b'])) for m in members}

    # The head sits a short distance below the (average) attachment
    # surface -- never AT it, or the capital legs would be coplanar with the
    # nodes they reach and carry no vertical component at all.
    head_drop = capital_height if capital_height is not None \
        else min(0.3 * height, max(0.3, height))
    head = len(nodes)
    nodes.append((cx, cy, cz - head_drop))
    foot_z = cz - head_drop - height
    bases = _build_shaft(nodes, members, seen, style, cx, cy, head,
                         cz - head_drop, foot_z,
                         width if width is not None else max(0.2 * height, 0.4),
                         panels)

    if tiers == 1:
        for j in target_nodes:
            _add_member(members, seen, head, j, role='capital')
        return nodes, members, bases, head

    buckets = {}
    for j in target_nodes:
        x, y, _z = nodes[j]
        ang = math.atan2(y - cy, x - cx)
        q = int(((ang + math.pi) // (math.pi / 2.0)) % 4)
        buckets.setdefault(q, []).append(j)
    if len(buckets) < 3:
        raise ValueError('target nodes are too clustered/colinear for a 2-tier capital; '
                         'pick a wider, more evenly spread footprint.')
    for js in buckets.values():
        if len(js) < 2:
            raise ValueError('a 2-tier capital needs at least 2 target nodes per angular '
                             'quadrant around the footprint -- pick more nodes, spanning at '
                             'least two grid modules.')

    inter_by_q = {}
    for q, js in buckets.items():
        mx = sum(nodes[j][0] for j in js) / len(js)
        my = sum(nodes[j][1] for j in js) / len(js)
        mz = sum(nodes[j][2] for j in js) / len(js)
        inter_z = (nodes[head][2] + mz) / 2.0
        inter = len(nodes)
        nodes.append((mx, my, inter_z))
        inter_by_q[q] = inter
        _add_member(members, seen, head, inter, role='capital')
        for j in js:
            _add_member(members, seen, inter, j, role='capital')

    order = sorted(inter_by_q)
    for a, b in zip(order, order[1:] + order[:1]):
        _add_member(members, seen, inter_by_q[a], inter_by_q[b], role='capital_ring')

    return nodes, members, bases, head


def reinforcement_beam(nodes, members, edge_a, edge_b, depth, direction=(0.0, 0.0, -1.0),
                       tiers=1, profile=BEAM_TRIANGLE):
    """Attach a linear space-truss reinforcement beam to TWO existing,
    parallel rows of nodes (`edge_a`, `edge_b` -- same length, each in
    order along the row, e.g. two adjacent bottom-chord rows of a
    flat_grid). Those two rows become the WIDE BASE of a triangular-
    cross-section truss girder -- already attached to the rest of the
    mesh through their own existing members -- and ONE new row of "apex"
    nodes, offset `depth` away along `direction`, is added and triangulated
    back to both rows. This is the real detail: the BASE (not a single new
    offset chord) does the attaching, matching how a triangular space-truss
    girder actually reinforces a roof/floor from below, base flush against
    the surface and the apex pointing away from it.

    An earlier version of this function instead reused a SINGLE existing
    row as the top chord and added two new chords below it -- structurally
    workable, but "upside down" relative to the real detail (narrow point
    at the grid, wide base hanging free) and it required the caller to
    hand-pick one already-straight row. Basing it on two existing rows
    both fixes the orientation and makes selection trivial: a lasso box
    dragged across two adjacent rows already contains everything needed.

    edge_a, edge_b : >= 2 existing node indices each, same length, in the
                     same order along the two rows (edge_a[k] and
                     edge_b[k] are the two ends of one cross-station).
    depth          : offset (m) from the rows' shared midline to the new
                     apex chord, along `direction`.
    direction      : (x, y, z) direction the apex is offset in;
                     normalized internally. The out-of-surface direction
                     (straight down/up off a roof) is the reliable choice
                     -- an in-plane direction can leave the beam
                     under-braced, the same way it did for the single-row
                     version.
    tiers          : 1 (default) -- a single apex row at `depth`, the
                     plain triangulated girder described above.
                     >= 2 -- MULTI-LAYER: `tiers` apex rows stacked at
                     depth*1/tiers, depth*2/tiers, ..., depth -- a taller,
                     stiffer girder for heavier loads, the same "make it
                     deeper, not just wider" idea as add_column's own
                     2-tier capital. Each tier independently gets the
                     EXACT SAME triangulation as the single-tier case
                     (its own web ties to edge_a/edge_b, its own chord,
                     its own both-direction X-bracing) -- never a
                     stripped-down or shared version of it -- so every
                     tier is already rigid on its own; the ties between
                     consecutive tiers only ADD stiffness on top of that,
                     never substitute for a tier's own bracing.

    profile        : the CROSS-SECTION, one of BEAM_PROFILES -- see that
                     table for what each is and what it trades. Triangular
                     puts one chord on the midline; the other two put a pair
                     of chords out towards the base rows, which roughly
                     doubles the bottom flange and stiffens the girder about
                     its vertical axis, at the cost of having to brace the
                     bottom plane against lozenging.

    Returns (nodes, members, apex_node_ids) -- apex_node_ids lists every
    tier's nodes in order (tier 1 first, closest to the base rows), and
    within a tier every offset chord in turn.
    """
    edge_a = list(edge_a)
    edge_b = list(edge_b)
    if len(edge_a) != len(edge_b):
        raise ValueError('edge_a and edge_b must be the same length.')
    if len(edge_a) < 2:
        raise ValueError('reinforcement_beam needs at least 2 stations to span.')
    for j in edge_a + edge_b:
        if not (0 <= j < len(nodes)):
            raise ValueError(f'edge node {j} does not exist.')
    dx, dy, dz = direction
    norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    if norm < 1e-9:
        raise ValueError('direction must be nonzero.')
    dx, dy, dz = dx / norm, dy / norm, dz / norm
    tiers = int(tiers)
    if tiers < 1:
        raise ValueError('tiers must be at least 1.')

    nodes = list(nodes)
    members = list(members)
    seen = {(min(m['a'], m['b']), max(m['a'], m['b'])) for m in members}

    if profile not in BEAM_PROFILE_OFFSETS:
        raise ValueError(f'unknown beam profile {profile!r}.')
    offsets = BEAM_PROFILE_OFFSETS[profile]

    n = len(edge_a)
    # apex_tiers[t] is a list of ROWS, one per offset chord in the section.
    apex_tiers = []
    for t in range(1, tiers + 1):
        d_t = depth * t / tiers
        rows = []
        for f in offsets:
            row = []
            for k in range(n):
                ax, ay, az = nodes[edge_a[k]]
                bx, by, bz = nodes[edge_b[k]]
                mx, my, mz = (ax + bx) / 2.0, (ay + by) / 2.0, (az + bz) / 2.0
                # f runs from the midline (0) out to either base row (+-1)
                px = mx + f * (bx - ax) / 2.0 + dx * d_t
                py = my + f * (by - ay) / 2.0 + dy * d_t
                pz = mz + f * (bz - az) / 2.0 + dz * d_t
                row.append(len(nodes))
                nodes.append((px, py, pz))
            rows.append(row)
        apex_tiers.append(rows)

    for rows in apex_tiers:
        for row in rows:
            for k in range(n):
                # Every offset node ties to BOTH base rows, not just the one
                # above it. On a box section the near tie alone is a plain
                # vertical, and the cross-section is then a four-bar linkage
                # that shears flat; the far tie is the diagonal that squares
                # it.
                _add_member(members, seen, edge_a[k], row[k], role='reinf_web')
                _add_member(members, seen, edge_b[k], row[k], role='reinf_web')
            for k in range(n - 1):
                _add_member(members, seen, row[k], row[k + 1], role='reinf_chord')
                # crossed bracing both ways per bay -- needed to stop the
                # whole chain from twisting about the base's own axis, the
                # same "spin" mechanism the single-row version needed
                # both-direction X-bracing to kill.
                _add_member(members, seen, edge_a[k], row[k + 1], role='reinf_web')
                _add_member(members, seen, row[k], edge_a[k + 1], role='reinf_web')
                _add_member(members, seen, edge_b[k], row[k + 1], role='reinf_web')
                _add_member(members, seen, row[k], edge_b[k + 1], role='reinf_web')
        for k in range(n - 1):
            _add_member(members, seen, edge_a[k], edge_a[k + 1], role='reinf_chord')
            _add_member(members, seen, edge_b[k], edge_b[k + 1], role='reinf_chord')
        # A section with two bottom chords has a bottom PLANE, and a plane of
        # parallelograms lozenges. Tie the pair at every station and brace
        # each bay of it.
        for lo, hi in zip(rows, rows[1:]):
            for k in range(n):
                _add_member(members, seen, lo[k], hi[k], role='reinf_web')
            for k in range(n - 1):
                _add_member(members, seen, lo[k], hi[k + 1], role='reinf_web')
                _add_member(members, seen, hi[k], lo[k + 1], role='reinf_web')

    # tie consecutive tiers together station by station -- pure ADDED
    # thickness/stiffness; each tier is already independently rigid above.
    for t in range(len(apex_tiers) - 1):
        for lo_row, hi_row in zip(apex_tiers[t], apex_tiers[t + 1]):
            for k in range(n):
                _add_member(members, seen, lo_row[k], hi_row[k], role='reinf_web')

    return nodes, members, [a for tier in apex_tiers for row in tier for a in row]
