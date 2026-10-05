"""Group a model by its pieces, and each piece by what its rods do.

A file brought in from elsewhere (SketchUp, another program, a hand-made
workbook) arrives as one undifferentiated list of rods: every rod Ungrouped,
no roles. Most such files are a set of separate pieces -- a roof, the module
it repeats, the trusses it rests on -- and each piece has the same three
kinds of rod: the top strip, the bottom strip and the diagonals between
them. This finds both levels from the geometry alone.

PIECES are the connected parts of the model (stereo_lift.pieces). A piece
whose nodes all lie in one plane is a TRUSS; any other is a double-layer
grid, named ROOF when it is of the size of the largest grid in the file and
MODULE when it is markedly smaller.

In a truss the TOP and BOTTOM STRIPS are the rods round its outline. Its
chords need not be conventional -- in a lens or fish-belly truss they are
two continuous strips that meet at a node at each end -- so they are found
by walking the truss's outer boundary in its own plane and splitting that
loop at its two end nodes; the upper half is the top strip. Every other rod
of the truss (inside the outline, or an end post) is a DIAGONAL.

In a double-layer grid a rod running ACROSS the depth -- at more than
WEB_ANGLE_DEG to the local surface -- is a DIAGONAL; the others are chords,
on the TOP or BOTTOM layer according to which side of the local mid-surface
their nodes lie. "Local" is the node's two-ring of neighbours, so a curved
roof is read the same as a flat one.

Kept free of Tk. `auto_groups` returns a list in stereo_groups' own format.
"""
import math

import numpy as np

from apps.stereo import stereo_groups as sgp

PLANAR_TOL = 1e-3            # third extent / first extent, for "planar"
WEB_ANGLE_DEG = 20.0         # steeper than this to the surface = diagonal
ROOF_FRACTION = 0.5          # a grid this size of the largest is a roof
END_POST_SLOPE = 0.2         # |du|/L of a boundary rod that is an end post


# ── pieces ────────────────────────────────────────────────────────────────

def _pieces(members):
    from apps.stereo import stereo_lift as sl
    return [sorted(p) for p in sl.pieces(members, skip_roles=())]


def _nodes_of(members, rods):
    out = set()
    for j in rods:
        out.add(members[j]['a'])
        out.add(members[j]['b'])
    return sorted(out)


def is_planar(nodes, members, rods):
    ns = _nodes_of(members, rods)
    if len(ns) < 4:
        return True
    P = np.array([nodes[n] for n in ns], dtype=float)
    s = np.linalg.svd(P - P.mean(0), compute_uv=False)
    return s[0] <= 0 or s[2] <= PLANAR_TOL * s[0]


# ── a truss: its outline, split at the two ends ──────────────────────────

def _plane_coords(nodes, ns):
    """Each node's (u, v) in the truss's own plane: u along its length, v
    across it, with +v pointing up (towards +z) wherever the plane allows."""
    P = np.array([nodes[n] for n in ns], dtype=float)
    c = P.mean(0)
    _u, _s, vt = np.linalg.svd(P - c)
    ex, ey = vt[0], vt[1]
    if ey[2] < 0 or (abs(ey[2]) < 1e-9 and ey[1] < 0):
        ey = -ey
    Q = P - c
    return {n: (float(Q[k] @ ex), float(Q[k] @ ey)) for k, n in enumerate(ns)}


def _walk(uv, adjacency, start, sense):
    """Follow the plane graph from `start`, turning as far as possible
    one way at every node (sense +1: the first edge counter-clockwise from
    the one arrived on; -1: clockwise), until back at the start."""
    two_pi = 2.0 * math.pi
    back = math.pi                      # arrived "from the left": nothing
    loop, cur, prev = [start], start, None
    for _ in range(2 * sum(len(v) for v in adjacency.values()) + 4):
        cu, cv = uv[cur]
        best, key = None, None
        for n in adjacency[cur]:
            if n == prev and len(adjacency[cur]) > 1:
                continue
            a = math.atan2(uv[n][1] - cv, uv[n][0] - cu)
            turn = ((a - back) * sense) % two_pi
            if turn <= 1e-12:
                turn = two_pi
            if key is None or turn < key:
                best, key = n, turn
        if best is None:
            return None
        prev, cur = cur, best
        if cur == start:
            return loop
        loop.append(cur)
        back = math.atan2(uv[prev][1] - uv[cur][1], uv[prev][0] - uv[cur][0])
    return None


def _area(uv, loop):
    return 0.5 * sum(uv[p][0] * uv[q][1] - uv[q][0] * uv[p][1]
                     for p, q in zip(loop, loop[1:] + loop[:1]))


def outline(uv, adjacency):
    """The outer boundary of a plane graph as a closed list of nodes.

    From the leftmost node, keep turning as far as possible one way at
    every node: one of the two senses goes round the outside, the other
    round the face just inside it. The outline is the one that encloses
    more -- so no rule about which way is which has to be right.
    """
    start = min(uv, key=lambda n: (uv[n][0], uv[n][1]))
    best = None
    for sense in (1, -1):
        loop = _walk(uv, adjacency, start, sense)
        if loop and (best is None or abs(_area(uv, loop))
                     > abs(_area(uv, best))):
            best = loop
    return best or [start]


def truss_parts(nodes, members, rods):
    """{'top': [...], 'bottom': [...], 'diagonals': [...]} for a planar
    piece: the outline split at its two ends, and everything else."""
    ns = _nodes_of(members, rods)
    uv = _plane_coords(nodes, ns)
    adj = {n: set() for n in ns}
    by_pair = {}
    for j in rods:
        a, b = members[j]['a'], members[j]['b']
        if a == b:
            continue
        adj[a].add(b)
        adj[b].add(a)
        by_pair.setdefault(frozenset((a, b)), []).append(j)
    loop = outline(uv, adj)
    if len(loop) < 3:
        return {'top': [], 'bottom': [], 'diagonals': list(rods)}
    left = min(loop, key=lambda n: (uv[n][0], uv[n][1]))
    right = max(loop, key=lambda n: (uv[n][0], -uv[n][1]))
    i, k = loop.index(left), loop.index(right)
    ring = loop[i:] + loop[:i]
    k = ring.index(right)
    side_a = ring[:k + 1]
    side_b = ring[k:] + [ring[0]]

    def rods_along(path):
        out = []
        for p, q in zip(path, path[1:]):
            for j in by_pair.get(frozenset((p, q)), ()):
                du = abs(uv[p][0] - uv[q][0])
                L = math.hypot(du, uv[p][1] - uv[q][1])
                # an end post closes the outline but is not a strip
                if L > 0 and du / L < END_POST_SLOPE and (
                        p in (left, right) or q in (left, right)):
                    continue
                if j not in out:
                    out.append(j)
        return out

    mean_v = lambda path: sum(uv[n][1] for n in path) / len(path)  # noqa
    top_path, bot_path = ((side_a, side_b) if mean_v(side_a) >= mean_v(side_b)
                          else (side_b, side_a))
    top, bottom = rods_along(top_path), rods_along(bot_path)
    strip = set(top) | set(bottom)
    return {'top': sorted(top), 'bottom': sorted(bottom),
            'diagonals': sorted(j for j in rods if j not in strip)}


# ── a double-layer grid: across the depth, or along a layer ──────────────

def grid_parts(nodes, members, rods):
    """{'top', 'bottom', 'diagonals'} for a double-layer piece."""
    ns = _nodes_of(members, rods)
    adj = {n: set() for n in ns}
    for j in rods:
        a, b = members[j]['a'], members[j]['b']
        adj[a].add(b)
        adj[b].add(a)
    P = {n: np.asarray(nodes[n], dtype=float) for n in ns}
    normal, centre = {}, {}
    for n in ns:
        ring = {n} | adj[n]
        for m in list(adj[n]):
            ring |= adj[m]
        Q = np.array([P[m] for m in ring])
        c = Q.mean(0)
        if len(Q) >= 3:
            _u, _s, vt = np.linalg.svd(Q - c)
            nv = vt[2]
        else:
            nv = np.array([0.0, 0.0, 1.0])
        if nv[2] < 0:
            nv = -nv
        normal[n], centre[n] = nv, c
    sin_web = math.sin(math.radians(WEB_ANGLE_DEG))
    top, bottom, diag = [], [], []
    for j in rods:
        a, b = members[j]['a'], members[j]['b']
        d = P[b] - P[a]
        L = float(np.linalg.norm(d))
        if L <= 0:
            diag.append(j)
            continue
        nv = normal[a] + normal[b]
        nv = nv / (np.linalg.norm(nv) or 1.0)
        if abs(float(d @ nv)) / L > sin_web:
            diag.append(j)
            continue
        side = (float((P[a] - centre[a]) @ normal[a])
                + float((P[b] - centre[b]) @ normal[b]))
        (top if side >= 0 else bottom).append(j)
    return {'top': sorted(top), 'bottom': sorted(bottom),
            'diagonals': sorted(diag)}


# ── a 3D assembly of planar trusses ───────────────────────────────────────

PLANE_TOL = 1e-3             # m off the plane, and 1 - |cos| between normals
ASSEMBLY_SINGLE_FRACTION = 0.5   # this share of rods in one plane only


def planar_trusses(nodes, members, rods):
    """The planar trusses a piece is built from, as lists of rods.

    Every triangle of rods has a plane; triangles that share a rod and lie
    in one plane grow into one truss. A rod where two trusses meet -- a
    strip they share -- lies in both planes, and each truss lists it: a
    truss's strips can only be read off the whole truss. (auto_groups gives
    it to the first, since a rod belongs to one group only.) Returns
    (trusses, shared, loose): `shared` the rods two trusses have in common,
    `loose` the rods in no triangle at all."""
    P = np.asarray(nodes, dtype=float)
    adj = {}
    for j in rods:
        a, b = members[j]['a'], members[j]['b']
        if a == b:
            continue
        adj.setdefault(a, {})[b] = j
        adj.setdefault(b, {})[a] = j
    tris = []
    for a in adj:
        for b in adj[a]:
            if b <= a:
                continue
            for c in set(adj[a]) & set(adj[b]):
                if c <= b:
                    continue
                nv = np.cross(P[b] - P[a], P[c] - P[a])
                L = float(np.linalg.norm(nv))
                if L < 1e-12:
                    continue
                tris.append(((a, b, c), nv / L,
                             (adj[a][b], adj[b][c], adj[a][c])))
    on_edge = {}
    for k, t in enumerate(tris):
        for e in t[2]:
            on_edge.setdefault(e, []).append(k)
    seen, regions = set(), []
    for k0 in range(len(tris)):
        if k0 in seen:
            continue
        n0, p0 = tris[k0][1], P[tris[k0][0][0]]
        stack, reg = [k0], set(tris[k0][2])
        seen.add(k0)
        while stack:
            k = stack.pop()
            for e in tris[k][2]:
                for k2 in on_edge[e]:
                    if k2 in seen:
                        continue
                    t = tris[k2]
                    if abs(abs(float(t[1] @ n0)) - 1.0) < PLANE_TOL and all(
                            abs(float((P[v] - p0) @ n0)) < PLANE_TOL
                            for v in t[0]):
                        seen.add(k2)
                        stack.append(k2)
                        reg |= set(t[2])
        regions.append(reg)
    count = {}
    for reg in regions:
        for j in reg:
            count[j] = count.get(j, 0) + 1
    shared = sorted(j for j, c in count.items() if c > 1)
    trusses = [sorted(reg) for reg in regions if reg]
    loose = sorted(j for j in rods if j not in count)
    return trusses, shared, loose


def is_truss_assembly(nodes, members, rods):
    """Whether a non-planar piece is planar trusses joined at their strips
    (most rods in one truss's plane only) rather than a double-layer grid
    (whose every rod lies in two of its slanted planes)."""
    _t, shared, loose = planar_trusses(nodes, members, rods)
    single = len(rods) - len(shared) - len(loose)
    return single >= ASSEMBLY_SINGLE_FRACTION * len(rods)


def _centroid(nodes, members, rods):
    return np.mean([nodes[n] for n in _nodes_of(members, rods)], axis=0)


def _order(nodes, members, items):
    """Reading order: by y, then x, of each item's centroid (rounded to the
    metre, so a row that is not quite straight still reads as a row)."""
    def key(rods):
        c = _centroid(nodes, members, rods)
        return (round(float(c[1])), round(float(c[0])))
    return sorted(items, key=key)


def split_into_modules(nodes, members, trusses, per_module, width, axis):
    """Bin an assembly's trusses into modules `width` wide along `axis`
    (0 = x, 1 = y), each holding `per_module` trusses -- or None when the
    trusses do not fall into such bins."""
    if per_module <= 0 or width <= 0 or len(trusses) % per_module:
        return None
    cs = [float(_centroid(nodes, members, t)[axis]) for t in trusses]
    lo = min(float(nodes[n][axis]) for t in trusses
             for n in _nodes_of(members, t))
    bins = {}
    for t, c in zip(trusses, cs):
        bins.setdefault(int((c - lo) // width), []).append(t)
    if any(len(b) != per_module for b in bins.values()):
        return None
    return [bins[k] for k in sorted(bins)]


# ── the whole model ───────────────────────────────────────────────────────

def classify(nodes, members):
    """The model's pieces as a tree, in reading order.

    [{'kind': 'truss'|'module'|'roof', 'rods': [...],
      'parts': {...}            for a truss or a double-layer grid,
      'trusses': [rods, ...]    for an assembly of trusses,
      'modules': [[rods, ...], ...] for a roof made of modules}]"""
    out = []
    for rods in _pieces(members):
        if is_planar(nodes, members, rods):
            out.append({'kind': 'truss', 'rods': rods,
                        'parts': truss_parts(nodes, members, rods)})
        elif is_truss_assembly(nodes, members, rods):
            trusses, _shared, loose = planar_trusses(nodes, members, rods)
            out.append({'kind': 'grid', 'rods': rods, 'loose': loose,
                        'trusses': _order(nodes, members, trusses)})
        else:
            out.append({'kind': 'grid', 'rods': rods,
                        'parts': grid_parts(nodes, members, rods)})
    biggest = max((len(p['rods']) for p in out if p['kind'] == 'grid'),
                  default=0)
    for p in out:
        if p['kind'] == 'grid':
            p['kind'] = ('roof' if len(p['rods']) >= ROOF_FRACTION * biggest
                         else 'module')
    # A roof of trusses is read as modules when the file has a module of
    # trusses to read it by: its truss count, and its width along the
    # roof's length.
    modules = [p for p in out if p['kind'] == 'module' and 'trusses' in p]
    for roof in (p for p in out if p['kind'] == 'roof' and 'trusses' in p):
        P = np.array([nodes[n] for n in _nodes_of(members, roof['rods'])])
        axis = int(np.argmax(P.max(0)[:2] - P.min(0)[:2]))
        for mod in modules:
            Q = np.array([nodes[n] for n in _nodes_of(members, mod['rods'])])
            width = float(Q.max(0)[axis] - Q.min(0)[axis])
            got = split_into_modules(nodes, members, roof['trusses'],
                                     len(mod['trusses']), width, axis)
            if got:
                roof['modules'] = got
                break
    order = {'truss': 0, 'module': 1, 'roof': 2}

    def where(p):
        c = _centroid(nodes, members, p['rods'])
        return (round(float(c[1])), round(float(c[0])))
    out.sort(key=lambda p: (order[p['kind']], where(p)))
    return out


GRID_NAMES = ('Top chords', 'Bottom chords', 'Diagonals')
TRUSS_NAMES = ('top strip', 'bottom strip', 'diagonals')


def _add_truss(groups, nodes, members, rods, name, parent, taken=None,
               holders=None):
    """A truss group and its three parts, read off the WHOLE truss; a rod
    an earlier truss already holds (a strip the two share) stays there, and
    the strip that keeps it says which trusses it serves. `holders` maps a
    rod to the names of every truss it lies in."""
    taken = set() if taken is None else taken
    g = sgp.new_group(groups, name, parent=parent)
    parts = truss_parts(nodes, members, rods)
    for label, key in zip(TRUSS_NAMES, ('top', 'bottom', 'diagonals')):
        own = [j for j in parts[key] if j not in taken]
        taken.update(own)
        if not own:
            continue
        others = sorted({o for j in own for o in (holders or {}).get(j, ())
                         if o != name})
        title = '%s %s' % (name, label) + (
            ' (shared with %s)' % ', '.join(others) if others else '')
        sgp.new_group(groups, title, parent=g['id'], members=own)
    return g


def auto_groups(nodes, members):
    """A fresh groups list for the whole model.

    One group per piece -- Truss n, Module n, Roof n -- and inside each,
    as deep as the piece goes: a roof's modules, a module's trusses, and
    in every truss its top strip, bottom strip and diagonals. A
    double-layer grid gets its top chords, bottom chords and diagonals."""
    groups, count = [], {}
    for piece in classify(nodes, members):
        kind = piece['kind']
        count[kind] = count.get(kind, 0) + 1
        label = '%s %d' % (kind.capitalize(), count[kind])
        if kind == 'truss':
            _add_truss(groups, nodes, members, piece['rods'], label, None)
            continue
        top = sgp.new_group(groups, label)
        if 'parts' in piece:
            for name, key in zip(GRID_NAMES, ('top', 'bottom', 'diagonals')):
                if piece['parts'][key]:
                    sgp.new_group(groups, '%s %s' % (label, name.lower()),
                                  parent=top['id'],
                                  members=piece['parts'][key])
            continue
        short = label[0] + label.split()[1]          # R1, M2
        if piece.get('modules'):
            named = [('%s M%d Truss %d' % (short, mi, ti), rods, mi)
                     for mi, mod in enumerate(piece['modules'], 1)
                     for ti, rods in enumerate(_order(nodes, members, mod), 1)]
        else:
            named = [('%s Truss %d' % (short, ti), rods, None)
                     for ti, rods in enumerate(piece['trusses'], 1)]
        holders = {}
        for name, rods, _m in named:
            for j in rods:
                holders.setdefault(j, []).append(name)
        taken, module_group = set(), {}
        for name, rods, mi in named:
            parent = top['id']
            if mi is not None:
                if mi not in module_group:
                    module_group[mi] = sgp.new_group(
                        groups, '%s Module %d' % (short, mi),
                        parent=top['id'])['id']
                parent = module_group[mi]
            _add_truss(groups, nodes, members, rods, name, parent, taken,
                       holders)
        if piece.get('loose'):
            sgp.assign(groups, top['id'], piece['loose'])
    return groups
