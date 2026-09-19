"""Welded shear panels for the Stereo tab: a plate closing a polygon of rods.

The same stressed-skin ("shear panel", Kuhn) idealisation the Truss tab uses,
lifted into three dimensions. The plate carries CONSTANT shear flow
q = G*t*gamma in its own plane and no direct stress; the rods around it go on
carrying the axial force exactly as they did.

WHAT THIS ELEMENT IS NOT, and must not be read as:
  * NOT a meshed plate. One panel has one shear flow and one tau. There is no
    stress field and no sigma_x / sigma_y.
  * It has NO rotational DOF -- a membrane never does -- so a panel does not
    restrain joint rotation, and it is not a substitute for a meshed plate if
    local stress is what you actually want.
  * Post-buckling (tension-field) strength is NOT included. A thin panel
    buckles in shear long before it yields, which is why no result here is
    ever shown without its buckling check.

THE FORMULATION, and what is new in 3D. In plane, the average engineering
shear strain over the polygon comes exactly from its BOUNDARY, by the
divergence theorem, with u and v varying linearly along each edge:

    gamma * A = closed_integral (u*n_y + v*n_x) ds
              = sum over edges [ -u_bar_i * dx_i + v_bar_i * dy_i ]

giving a strain-displacement row B over the in-plane DOFs and a rank-1
stiffness K = G*t*A * B^T B. That much is the Truss tab's element, verified
there by patch test.

The 3D part is the frame. A panel in a space structure lies on some arbitrary
plane, so this module finds that plane, builds an orthonormal (e1, e2) in it,
and expresses the SAME row against each node's three global translations:

    Bg[node i] = B[2i] * e1 + B[2i+1] * e2

which keeps the element rank-1 over 3n DOFs. A displacement normal to the
plate produces no shear, which is correct for a membrane and is what makes
the out-of-plane direction drop out of Bg on its own rather than by being
deleted.

PLANARITY IS A REAL CONSTRAINT, not a modelling convenience. Three nodes are
always coplanar; four in a space frame very often are not, and a warped quad
has no single shear plane for gamma to be measured in. Such a panel is
REFUSED rather than quietly flattened onto a best-fit plane, because
flattening moves the weld line off the rods it is supposed to be welded to.
"""
import math

PLANARITY_TOL = 0.02        # out-of-plane offset allowed, as a fraction of
                            # the panel's own size. 2% of a 3 m bay is 60 mm,
                            # which is a fit-up tolerance, not a warp.
MIN_AREA_M2 = 1e-9


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    if n < 1e-12:
        return None
    return (a[0] / n, a[1] / n, a[2] / n)


def panel_loop_from_members(members, selected):
    """Turn selected member indices into the ordered node loop they enclose.

    Returns (loop, None) or (None, reason) with a message fit for a status
    line. Only triangles and quadrilaterals are accepted: anything else is
    refused rather than triangulated behind the user's back, because the
    element has one shear flow and a person choosing a panel should know
    exactly which polygon that flow is in.
    """
    sel = sorted({int(i) for i in selected})
    if len(sel) not in (3, 4):
        return None, (f'Select 3 or 4 rods forming a closed loop '
                      f'({len(sel)} selected).')
    try:
        edges = [(members[i]['a'], members[i]['b']) for i in sel]
    except (IndexError, KeyError, TypeError):
        return None, 'That selection refers to a rod that no longer exists.'

    deg = {}
    for a, b in edges:
        if a == b:
            return None, 'A rod joins a node to itself; that is not a loop.'
        deg.setdefault(a, []).append(b)
        deg.setdefault(b, []).append(a)
    if len(deg) != len(edges):
        return None, (f'Those rods do not form a single closed loop '
                      f'({len(edges)} rods, {len(deg)} nodes).')
    bad = [n for n, nb in deg.items() if len(nb) != 2]
    if bad:
        return None, (f'Those rods branch instead of closing a loop '
                      f'(node {bad[0]} meets {len(deg[bad[0]])} of them).')

    start = edges[0][0]
    loop = [start]
    prev, cur = None, start
    for _ in range(len(edges) - 1):
        nxt = [n for n in deg[cur] if n != prev]
        if not nxt:
            return None, 'Those rods do not form a single closed loop.'
        prev, cur = cur, nxt[0]
        loop.append(cur)
    if len(set(loop)) != len(edges):
        return None, 'Those rods do not form a single closed loop.'
    return loop, None


def panel_frame(nodes, loop):
    """The panel's own plane: (origin, e1, e2, normal) or (None, reason).

    The normal is the area-weighted sum of the loop's edge cross products
    (Newell's method), which is exact for a planar polygon and, for a warped
    one, gives the best-fit plane the planarity check then rejects it
    against.
    """
    pts = [nodes[i] for i in loop]
    n = len(pts)
    normal = (0.0, 0.0, 0.0)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        c = _cross(a, b)
        normal = (normal[0] + c[0], normal[1] + c[1], normal[2] + c[2])
    unit_n = _unit(normal)
    if unit_n is None:
        # Newell's normal vanishes when every point is collinear, and also
        # when the loop crosses itself so its two lobes cancel.
        return None, ('Those nodes are in a straight line, or the loop crosses '
                      'itself, so they enclose no panel.')
    e1 = _unit(_sub(pts[1], pts[0]))
    if e1 is None:
        return None, 'Two of those nodes are in the same place.'
    # Re-orthogonalise: the first edge is generally not perpendicular to the
    # normal by construction, only by the plane being flat.
    e1 = _unit(_sub(e1, tuple(_dot(e1, unit_n) * c for c in unit_n)))
    if e1 is None:
        return None, 'The panel edge is perpendicular to its own plane.'
    e2 = _cross(unit_n, e1)
    return (pts[0], e1, e2, unit_n), None


def panel_geometry(nodes, panel):
    """(loop, local points, area m^2, Bg rows) or (None, reason).

    `Bg` is a list of 3-vectors, one per loop node: the strain-displacement
    row for gamma expressed against that node's (ux, uy, uz).
    """
    loop = panel.get('nodes')
    if not loop or len(loop) not in (3, 4):
        return None, 'A panel needs 3 or 4 nodes.'
    if len(set(loop)) != len(loop):
        return None, 'A panel cannot use the same node twice.'
    if any(not (0 <= i < len(nodes)) for i in loop):
        return None, 'That panel refers to a node that no longer exists.'

    frame, reason = panel_frame(nodes, loop)
    if frame is None:
        return None, reason
    origin, e1, e2, unit_n = frame

    pts, out_of_plane = [], 0.0
    for i in loop:
        d = _sub(nodes[i], origin)
        pts.append((_dot(d, e1), _dot(d, e2)))
        out_of_plane = max(out_of_plane, abs(_dot(d, unit_n)))

    size = math.sqrt(max(abs(_shoelace(pts)) / 2.0, 1e-12))
    if size > 0 and out_of_plane > PLANARITY_TOL * size:
        return None, (f'Those four nodes are not coplanar: one is '
                      f'{out_of_plane * 1000.0:.0f} mm out of the plane of the '
                      f'others. A warped panel has no single shear plane, so '
                      f'there is nothing for the shear flow to be measured in.')

    area = _shoelace(pts) / 2.0
    if abs(area) < MIN_AREA_M2:
        return None, 'Those nodes enclose no area.'
    if area < 0:
        # Normalise the loop's orientation so a positive shear flow always
        # means "running the way the node loop runs".
        loop = [loop[0]] + loop[:0:-1]
        pts = [pts[0]] + pts[:0:-1]
        area = -area

    n = len(pts)
    B = [0.0] * (2 * n)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        for k in (i, (i + 1) % n):
            B[2 * k] += -dx / 2.0
            B[2 * k + 1] += dy / 2.0
    B = [b / area for b in B]

    Bg = []
    for i in range(n):
        bu, bv = B[2 * i], B[2 * i + 1]
        Bg.append((bu * e1[0] + bv * e2[0],
                   bu * e1[1] + bv * e2[1],
                   bu * e1[2] + bv * e2[2]))
    return (list(loop), pts, area, Bg), None


def _shoelace(pts):
    s = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s


def panel_material(panel):
    """(G in Pa, t in metres). G defaults to the isotropic E/(2(1+nu)), so a
    panel only has to carry E and nu if that is more convenient. Thickness is
    stored in mm because that is how plate is specified and ordered; every
    other length here is metres."""
    t_m = float(panel.get('thickness_mm', 0.0)) / 1000.0
    if panel.get('G_GPa') is not None:
        G_Pa = float(panel['G_GPa']) * 1e9
    else:
        E = float(panel.get('E_GPa', 200.0)) * 1e9
        nu = float(panel.get('nu', 0.3))
        G_Pa = E / (2.0 * (1.0 + nu))
    return G_Pa, t_m


def panel_loop_from_nodes(members, node_ids):
    """Order 3 or 4 SELECTED NODES into a loop whose every edge is a real rod.

    The Truss tab builds a panel from selected rods, because that is what it
    lets you click. This tab's selection tool is a lasso over nodes, so the
    natural gesture here is "these four joints", and the rods are looked up
    rather than picked.

    Every consecutive pair must already be joined by a member. A panel welded
    along an edge with no rod on it would be carrying its shear into thin
    air, so a set of nodes that does not close through real rods is refused
    rather than being given the edges it is missing.

    Returns (loop, None) or (None, reason).
    """
    ids = sorted({int(i) for i in node_ids})
    if len(ids) not in (3, 4):
        return None, (f'Select 3 or 4 nodes that a panel can be welded '
                      f'between ({len(ids)} selected).')
    adj = {i: set() for i in ids}
    want = set(ids)
    for m in members:
        a, b = m['a'], m['b']
        if a in want and b in want:
            adj[a].add(b)
            adj[b].add(a)

    start = ids[0]
    rest = ids[1:]

    def walk(path, remaining):
        if not remaining:
            return path if path[0] in adj[path[-1]] else None
        for nxt in remaining:
            if nxt in adj[path[-1]]:
                got = walk(path + [nxt], [r for r in remaining if r != nxt])
                if got:
                    return got
        return None

    loop = walk([start], rest)
    if loop is None:
        missing = [i for i in ids if len(adj[i]) < 2]
        if missing:
            return None, (f'Node {missing[0]} is not joined to two of the '
                          f'others by rods, so those nodes do not close a '
                          f'panel.')
        return None, ('Those nodes are all connected, but not in a single '
                      'ring -- a panel needs a closed loop of rods around it.')
    return loop, None
