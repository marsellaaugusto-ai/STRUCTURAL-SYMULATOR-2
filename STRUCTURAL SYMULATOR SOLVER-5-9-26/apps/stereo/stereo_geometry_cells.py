"""Module editor: cell detection, role classification, and local-frame
edits that propagate across every cell of the same role.

Deliberately GENERIC over the mesh's (nodes, members) alone -- not tied to
any one generator's own (i, j)/(bi, ai) indexing -- so this works for every
grid family, including a hand-edited or Excel-imported mesh, with no
per-generator metadata to keep in sync.

A "cell" here is a minimal 3- or 4-node closed circuit of existing members
(a triangle or a quad). A "role" groups cells that are congruent -- the
same multiset of edge lengths, and for quads the same diagonal lengths too
-- i.e. the same geometric shape repeated across the grid, regardless of
which generator built it or what it named the members' `role` field.
"""
import math

from apps.stereo.stereo_geometry_core import _add_member


def find_cells(nodes, members):
    """Every minimal 3- or 4-node closed circuit of existing members --
    the candidate "module cells" a grid is built from. Returns a list of
    dicts {'nodes': (a, b, c[, d]), 'members': (member_idx, ...)}, each
    node tuple already in CANONICAL cyclic order (see _canonical_cycle)
    so two congruent cells agree on which position is "the same" corner.

    A quad is only reported when NEITHER of its two diagonals is itself
    an existing member -- when one is, that quad is really just two
    triangles sharing an edge, and both those triangles are already found
    on their own; counting the quad too would make the same physical
    panel show up as two different, overlapping "cells"."""
    adj = {}
    edge_index = {}
    for mi, m in enumerate(members):
        a, b = m['a'], m['b']
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
        edge_index[(min(a, b), max(a, b))] = mi

    def medge(a, b):
        return edge_index[(min(a, b), max(a, b))]

    def has_edge(a, b):
        return (min(a, b), max(a, b)) in edge_index

    seen_tri = set()
    seen_quad = set()
    cells = []

    for (a, b) in list(edge_index):
        for c in adj.get(a, ()) & adj.get(b, ()):
            key = frozenset((a, b, c))
            if key in seen_tri:
                continue
            seen_tri.add(key)
            order = _canonical_cycle(nodes, (a, b, c))
            cells.append({'nodes': order,
                         'members': tuple(medge(order[i], order[(i + 1) % 3])
                                          for i in range(3))})
        for c in adj.get(b, ()) - {a}:
            for d in adj.get(c, ()) - {b}:
                if d == a or len({a, b, c, d}) != 4:
                    continue
                if not has_edge(d, a):
                    continue
                if has_edge(a, c) or has_edge(b, d):
                    continue   # a diagonal exists -- two triangles, not a quad cell
                key = frozenset((a, b, c, d))
                if key in seen_quad:
                    continue
                seen_quad.add(key)
                order = _canonical_cycle(nodes, (a, b, c, d))
                cells.append({'nodes': order,
                             'members': tuple(medge(order[i], order[(i + 1) % 4])
                                              for i in range(4))})
    return cells


def _canonical_cycle(nodes, node_ids):
    """Rotate/reflect a cell's node tuple to whichever starting point and
    direction gives the lexicographically smallest sequence of (rounded)
    edge lengths -- brute force over the <= 8 rotations/reflections of a
    3- or 4-node cycle, which is exactly why this is only attempted for
    such small cells. Makes "position k" comparable across every
    congruent cell of a role: two cells with the same edge-length
    sequence always agree on which corner is position 0, so an edit at
    position k lands on the analogous corner everywhere, not an arbitrary
    one."""
    n = len(node_ids)
    best = None
    for base in (node_ids, tuple(reversed(node_ids))):
        for start in range(n):
            rot = base[start:] + base[:start]
            lengths = tuple(round(math.dist(nodes[rot[i]], nodes[rot[(i + 1) % n]]), 6)
                           for i in range(n))
            if best is None or lengths < best[0]:
                best = (lengths, rot)
    return best[1]


def _cell_signature(nodes, cell_nodes):
    """A cell's congruence signature: its (canonical-order) edge lengths,
    plus its diagonal length(s) for a quad -- two cells sharing this same
    signature are considered the same module 'role' (the same shape,
    repeated), independent of the generator's own member `role` tags."""
    n = len(cell_nodes)
    edges = tuple(round(math.dist(nodes[cell_nodes[i]], nodes[cell_nodes[(i + 1) % n]]), 6)
                 for i in range(n))
    if n == 4:
        diag = tuple(sorted((round(math.dist(nodes[cell_nodes[0]], nodes[cell_nodes[2]]), 6),
                            round(math.dist(nodes[cell_nodes[1]], nodes[cell_nodes[3]]), 6))))
        return (n, edges, diag)
    return (n, edges)


def classify_cell_roles(nodes, cells):
    """Group `cells` (from find_cells) by congruence signature into
    ROLES, numbered 0, 1, 2, ... in DECREASING order of how many cells
    share that shape -- role 0 is always the grid's dominant, repeating
    module; every other role is a shape that occurs less often (down to
    a true one-off like a dome's own apex fan or a vault's end panel).

    Returns {'cell_role': [role_id, ...] (one per cell, same order as
    `cells`), 'roles': {role_id: [cell_idx, ...]}} sorted so role 0's
    list is the longest."""
    sig_groups = {}
    for i, cell in enumerate(cells):
        sig = _cell_signature(nodes, cell['nodes'])
        sig_groups.setdefault(sig, []).append(i)
    ordered = sorted(sig_groups.values(), key=len, reverse=True)
    cell_role = [0] * len(cells)
    roles = {}
    for role_id, idxs in enumerate(ordered):
        roles[role_id] = idxs
        for i in idxs:
            cell_role[i] = role_id
    return {'cell_role': cell_role, 'roles': roles}


def cell_local_basis(nodes, cell_nodes):
    """(origin, e_u, e_v, e_n) for one cell: origin is its position-0
    corner, e_u the unit direction to position 1, e_n the unit normal
    (via position-2, Gram-Schmidt'd against e_u so it is exactly
    perpendicular even for a non-planar/warped quad), e_v completing a
    right-handed orthonormal frame. Degenerates to a fallback frame (e_u
    along global X, e_n along global Z) only for a zero-length or fully
    collinear cell -- should not occur for any cell find_cells actually
    returns, but guards the divide-by-near-zero rather than crashing."""
    p0 = nodes[cell_nodes[0]]
    p1 = nodes[cell_nodes[1]]
    p2 = nodes[cell_nodes[2]]
    ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    ulen = math.sqrt(ux * ux + uy * uy + uz * uz)
    if ulen < 1e-9:
        return p0, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    eu = (ux / ulen, uy / ulen, uz / ulen)
    wx, wy, wz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
    dot = wx * eu[0] + wy * eu[1] + wz * eu[2]
    vx, vy, vz = wx - dot * eu[0], wy - dot * eu[1], wz - dot * eu[2]
    vlen = math.sqrt(vx * vx + vy * vy + vz * vz)
    if vlen < 1e-9:
        # p2 collinear with p0-p1 -- fall back to any perpendicular of eu
        fallback = (0.0, 0.0, 1.0) if abs(eu[2]) < 0.9 else (1.0, 0.0, 0.0)
        vx = fallback[1] * eu[2] - fallback[2] * eu[1]
        vy = fallback[2] * eu[0] - fallback[0] * eu[2]
        vz = fallback[0] * eu[1] - fallback[1] * eu[0]
        vlen = math.sqrt(vx * vx + vy * vy + vz * vz)
    ev = (vx / vlen, vy / vlen, vz / vlen)
    enx = eu[1] * ev[2] - eu[2] * ev[1]
    eny = eu[2] * ev[0] - eu[0] * ev[2]
    enz = eu[0] * ev[1] - eu[1] * ev[0]
    return p0, eu, ev, (enx, eny, enz)


def cell_local_coords(nodes, cell_nodes, position):
    """(u, v, n) of cell_nodes[position] in that cell's own local basis
    (see cell_local_basis) -- how far along e_u, e_v, e_n it sits from
    the cell's own origin corner."""
    origin, eu, ev, en = cell_local_basis(nodes, cell_nodes)
    p = nodes[cell_nodes[position]]
    dx, dy, dz = p[0] - origin[0], p[1] - origin[1], p[2] - origin[2]
    return (dx * eu[0] + dy * eu[1] + dz * eu[2],
           dx * ev[0] + dy * ev[1] + dz * ev[2],
           dx * en[0] + dy * en[1] + dz * en[2])


def _locked_directions(nodes, members, locked_member_idxs, node_id):
    """Unit direction of every LOCKED member touching `node_id` -- the
    directions a move at that node must not have any component along
    (see project_onto_unlocked_directions)."""
    dirs = []
    for mi in locked_member_idxs:
        m = members[mi]
        if node_id not in (m['a'], m['b']):
            continue
        other = m['b'] if m['a'] == node_id else m['a']
        p0, p1 = nodes[node_id], nodes[other]
        dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        L = math.sqrt(dx * dx + dy * dy + dz * dz)
        if L > 1e-9:
            dirs.append((dx / L, dy / L, dz / L))
    return dirs


def project_onto_unlocked_directions(delta, forbidden_dirs):
    """Project `delta` (a global dx, dy, dz) onto the orthogonal
    complement of the span of `forbidden_dirs` -- i.e. strip out any
    component of the requested move that runs along a LOCKED rod's own
    direction, via Gram-Schmidt orthonormalization of `forbidden_dirs`
    followed by subtracting delta's projection onto each orthonormal
    direction in turn. With zero forbidden directions this is the
    identity; with one it removes exactly the along-the-rod component
    (leaving free sideways motion); with two independent ones it leaves
    only the single direction perpendicular to both."""
    dx, dy, dz = delta
    ortho = []
    for d in forbidden_dirs:
        for o in ortho:
            dot = d[0] * o[0] + d[1] * o[1] + d[2] * o[2]
            d = (d[0] - dot * o[0], d[1] - dot * o[1], d[2] - dot * o[2])
        L = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)
        if L > 1e-9:
            ortho.append((d[0] / L, d[1] / L, d[2] / L))
    for o in ortho:
        dot = dx * o[0] + dy * o[1] + dz * o[2]
        dx, dy, dz = dx - dot * o[0], dy - dot * o[1], dz - dot * o[2]
    return (dx, dy, dz)


def move_role_node(nodes, members, cells, roles, role_id, position, delta_uvn,
                   locked_member_idxs=()):
    """Move the corner at `position` (0-based index into a cell's own
    canonical node order) of EVERY cell in role `role_id`, by `delta_uvn`
    (a (du, dv, dn) offset expressed in EACH cell's own local basis --
    see cell_local_basis -- so the same edit stays geometrically
    consistent even as the role's cells are oriented differently around
    a dome or fan out along a vault). A physical node touched by more
    than one cell of this role (an ordinary shared corner) gets the
    AVERAGE of every proposal made for it, rather than an arbitrary
    last-write-wins.

    Any candidate move is first run through
    project_onto_unlocked_directions against that physical node's own
    locked members (from `locked_member_idxs`), so a locked rod's length
    is preserved even under this bulk role-wide edit -- exactly the same
    rule a direct single-node drag follows.

    Returns a NEW nodes list; `members`/`cells`/`roles` are not mutated.
    """
    du, dv, dn = delta_uvn
    proposals = {}   # physical node id -> list of proposed new (x, y, z)
    for ci in roles.get(role_id, ()):
        cell_nodes = cells[ci]['nodes']
        if position >= len(cell_nodes):
            continue
        origin, eu, ev, en = cell_local_basis(nodes, cell_nodes)
        node_id = cell_nodes[position]
        raw = (du * eu[0] + dv * ev[0] + dn * en[0],
              du * eu[1] + dv * ev[1] + dn * en[1],
              du * eu[2] + dv * ev[2] + dn * en[2])
        forbidden = _locked_directions(nodes, members, locked_member_idxs, node_id)
        ddx, ddy, ddz = project_onto_unlocked_directions(raw, forbidden)
        x, y, z = nodes[node_id]
        proposals.setdefault(node_id, []).append((x + ddx, y + ddy, z + ddz))

    new_nodes = list(nodes)
    for node_id, cands in proposals.items():
        n = len(cands)
        new_nodes[node_id] = (sum(c[0] for c in cands) / n,
                              sum(c[1] for c in cands) / n,
                              sum(c[2] for c in cands) / n)
    return new_nodes


def rescale_role_cells(nodes, cells, roles, role_id, factor):
    """Scale every node touched by role `role_id` by `factor`, about ONE
    shared centroid common to the whole role -- "keeps your shape" (any
    prior freeform edit to that role survives, just uniformly bigger/
    smaller) rather than resetting to a fresh regular polygon.

    Deliberately NOT each cell's own separate centroid: a corner shared
    by several cells of the same role (the ordinary case for any tiled
    grid) would then get a different scaled position proposed by each
    of ITS cells, and averaging those -- the reasonable thing to do for
    move_role_node, whose per-cell deltas are legitimately different
    because neighbouring cells can be oriented differently -- would
    instead just partly CANCEL a plain scale-up here (two different
    pulls toward two different centroids, blended, land closer to the
    middle than either), silently delivering a smaller factor than
    asked for. A single shared centroid keeps this an unambiguous
    similarity transform: every pairwise distance scales by EXACTLY
    `factor`, full stop."""
    touched = sorted({nid for ci in roles.get(role_id, ()) for nid in cells[ci]['nodes']})
    if not touched:
        return list(nodes)
    cx = sum(nodes[nid][0] for nid in touched) / len(touched)
    cy = sum(nodes[nid][1] for nid in touched) / len(touched)
    cz = sum(nodes[nid][2] for nid in touched) / len(touched)

    new_nodes = list(nodes)
    for nid in touched:
        x, y, z = nodes[nid]
        new_nodes[nid] = (cx + (x - cx) * factor, cy + (y - cy) * factor, cz + (z - cz) * factor)
    return new_nodes


def set_role_member_length(nodes, cells, roles, role_id, pos_a, pos_b, new_length):
    """Set the length of the edge between canonical positions `pos_a` and
    `pos_b` to `new_length` in EVERY cell of role `role_id`, by moving the
    position-`pos_b` corner along the current pos_a->pos_b direction,
    computed from the ORIGINAL (pre-edit) positions of both -- the "click
    a rod, type its length" edit. Locking is enforced by the CALLER
    simply not invoking this on a locked member (see stereo_app.py); this
    function itself has no notion of a lock.

    position_a is proposed to STAY PUT by this edit, and position_b to
    MOVE to hit the target length -- but a physical node shared between
    cells of this role (the ordinary case for a tiled grid) can be
    position_a for one cell and position_b for another at the same time,
    which is a genuine conflict, not a bug: like move_role_node and
    rescale_role_cells, a node that collects more than one proposal gets
    their AVERAGE, computed entirely from the pre-edit snapshot (never
    from another cell's already-written result, which would let edits
    cascade through a shared corner depending on processing order). In
    a densely-interlocked role (every corner shared with a neighbour,
    e.g. flat_grid's own square chords) that averaging means the exact
    target length is NOT guaranteed at every single cell -- only where a
    role's cells share no nodes at all does every edge land exactly on
    `new_length` (see the module editor tests for both cases)."""
    proposals = {}
    for ci in roles.get(role_id, ()):
        cell_nodes = cells[ci]['nodes']
        if pos_a >= len(cell_nodes) or pos_b >= len(cell_nodes):
            continue
        a_id, b_id = cell_nodes[pos_a], cell_nodes[pos_b]
        ax, ay, az = nodes[a_id]
        bx, by, bz = nodes[b_id]
        dx, dy, dz = bx - ax, by - ay, bz - az
        L = math.sqrt(dx * dx + dy * dy + dz * dz)
        proposals.setdefault(a_id, []).append((ax, ay, az))
        if L < 1e-9:
            proposals.setdefault(b_id, []).append((bx, by, bz))
            continue
        scale = new_length / L
        proposals.setdefault(b_id, []).append((ax + dx * scale, ay + dy * scale, az + dz * scale))

    new_nodes = list(nodes)
    for nid, cands in proposals.items():
        n = len(cands)
        new_nodes[nid] = (sum(c[0] for c in cands) / n,
                         sum(c[1] for c in cands) / n,
                         sum(c[2] for c in cands) / n)
    return new_nodes


def toggle_role_member(members, cells, roles, role_id, pos_a, pos_b):
    """Add the member between canonical positions `pos_a`/`pos_b` to
    every cell of role `role_id` that doesn't already have it, or remove
    it from every cell that does -- whichever action applies to the
    role's REPRESENTATIVE cell (roles[role_id][0]) is the one applied
    everywhere, so a single click's effect is always "what you just did
    to the cell you were looking at," propagated. Returns a NEW members
    list; existing member indices below the first removed one, if any,
    are unaffected but indices in general may shift -- callers that hold
    onto a member index across this call must re-look-up afterward."""
    idxs = roles.get(role_id, ())
    if not idxs:
        return list(members)
    seen = {(min(m['a'], m['b']), max(m['a'], m['b'])) for m in members}

    rep_nodes = cells[idxs[0]]['nodes']
    if pos_a >= len(rep_nodes) or pos_b >= len(rep_nodes):
        return list(members)
    rep_key = (min(rep_nodes[pos_a], rep_nodes[pos_b]), max(rep_nodes[pos_a], rep_nodes[pos_b]))
    adding = rep_key not in seen

    new_members = list(members)
    for ci in idxs:
        cell_nodes = cells[ci]['nodes']
        if pos_a >= len(cell_nodes) or pos_b >= len(cell_nodes):
            continue
        a_id, b_id = cell_nodes[pos_a], cell_nodes[pos_b]
        key = (min(a_id, b_id), max(a_id, b_id))
        if adding:
            _add_member(new_members, seen, a_id, b_id, role='module_edit')
        elif key in seen:
            new_members = [m for m in new_members
                          if (min(m['a'], m['b']), max(m['a'], m['b'])) != key]
            seen.discard(key)
    return new_members
