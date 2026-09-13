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


def add_column(nodes, members, target_nodes, height, tiers=1):
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
    height       : shaft length (m), from the new base node up to the head
                   (tiers=1) or the intermediate ring (tiers=2).
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

    Returns (nodes, members, base_node, head_node) -- new lists, the
    mesh's own node/member lists are not mutated in place.
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

    cx = sum(nodes[j][0] for j in target_nodes) / len(target_nodes)
    cy = sum(nodes[j][1] for j in target_nodes) / len(target_nodes)
    cz = sum(nodes[j][2] for j in target_nodes) / len(target_nodes)

    nodes = list(nodes)
    members = list(members)
    seen = {(min(m['a'], m['b']), max(m['a'], m['b'])) for m in members}

    # The head sits a short distance below the (average) attachment
    # surface -- never AT it, or the "shaft" would be zero-length -- so
    # the capital legs are genuinely inclined -- legs coplanar with the
    # attachment nodes would carry no vertical component at all.
    head_drop = min(0.3 * height, max(0.3, height))
    head = len(nodes)
    nodes.append((cx, cy, cz - head_drop))
    base = len(nodes)
    nodes.append((cx, cy, cz - head_drop - height))

    _add_member(members, seen, base, head, role='column_shaft')

    if tiers == 1:
        for j in target_nodes:
            _add_member(members, seen, head, j, role='capital')
        return nodes, members, base, head

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

    return nodes, members, base, head


def reinforcement_beam(nodes, members, edge_a, edge_b, depth, direction=(0.0, 0.0, -1.0),
                       tiers=1):
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

    Returns (nodes, members, apex_node_ids) -- apex_node_ids lists every
    tier's nodes in order (tier 1 first, closest to the base rows).
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

    n = len(edge_a)
    apex_tiers = []
    for t in range(1, tiers + 1):
        d_t = depth * t / tiers
        apex = []
        for k in range(n):
            ax, ay, az = nodes[edge_a[k]]
            bx, by, bz = nodes[edge_b[k]]
            mx, my, mz = (ax + bx) / 2.0, (ay + by) / 2.0, (az + bz) / 2.0
            apex.append(len(nodes))
            nodes.append((mx + dx * d_t, my + dy * d_t, mz + dz * d_t))
        apex_tiers.append(apex)

    for apex in apex_tiers:
        for k in range(n):
            _add_member(members, seen, edge_a[k], apex[k], role='reinf_web')
            _add_member(members, seen, edge_b[k], apex[k], role='reinf_web')
        for k in range(n - 1):
            _add_member(members, seen, edge_a[k], edge_a[k + 1], role='reinf_chord')
            _add_member(members, seen, edge_b[k], edge_b[k + 1], role='reinf_chord')
            _add_member(members, seen, apex[k], apex[k + 1], role='reinf_chord')
            # crossed bracing both ways per bay -- needed to stop the
            # whole apex chain from twisting about the base's own axis,
            # the same "spin" mechanism the single-row version needed
            # both-direction X-bracing to kill.
            _add_member(members, seen, edge_a[k], apex[k + 1], role='reinf_web')
            _add_member(members, seen, apex[k], edge_a[k + 1], role='reinf_web')
            _add_member(members, seen, edge_b[k], apex[k + 1], role='reinf_web')
            _add_member(members, seen, apex[k], edge_b[k + 1], role='reinf_web')

    # tie consecutive tiers together station by station -- pure ADDED
    # thickness/stiffness; each tier is already independently rigid above.
    for t in range(len(apex_tiers) - 1):
        for k in range(n):
            _add_member(members, seen, apex_tiers[t][k], apex_tiers[t + 1][k], role='reinf_web')

    return nodes, members, [a for tier in apex_tiers for a in tier]
