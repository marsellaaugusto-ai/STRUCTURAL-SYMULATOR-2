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

import cirsoc_301 as cirsoc

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


# ═══════════════════════════════════════════════════════════════════════════════
# GUSSET-PLATE VERIFICATION AT A NODE
#
# A second, independent plate feature that shares this module. The panels
# above are a structural ELEMENT: they carry shear flow and add stiffness to
# the solve. What follows is a CHECK: given a solved model, it verifies the
# gusset that joins the rods meeting at a node, and changes nothing about the
# analysis.
#
# They arrived on two separate branches that each created a stereo_plates.py,
# and were combined here rather than kept apart, because both are imported as
# `stereo_plates` by existing code (stereo_math, stereo_app_addons,
# stereo_reports). Nothing below is referenced by the panel element above,
# and nothing above is referenced here -- if this file is ever split again,
# it splits exactly at this line.
#
# Adapts the 2D logic from apps/truss/truss_plates.py to 3D:
#   * members at each node are grouped into coplanar sets
#   * for each coplanar group (>= 2 members in a plane) the classic gusset
#     checks run: Whitmore effective section, block shear (J4.3), and
#     Thornton gusset buckling (E3) for compression members
#
# Units at this boundary are the stereo module's: kN, kN-m, m, GPa, cm2,
# cm4, MPa. cirsoc_301 works in N, mm, MPa -- converted once per function.
#
# _dot, _norm and _cross are deliberately NOT redefined below: the panel
# half above already defines all three, identically (_norm differed only
# in its parameter name), so this half simply uses them.
# ═══════════════════════════════════════════════════════════════════════════════

WHITMORE_ANGLE_DEG = 30.0
GUSSET_K = 0.65

DEFAULT_FY_MPA = 235.0
DEFAULT_FU_MPA = 360.0
DEFAULT_T_MM = 10.0
DEFAULT_LANDING_M = 0.30


def _member_dirs_at_node(nodes, members, node_idx):
    """Unit vectors (3D) from *node_idx* along each member meeting it.

    Returns list of ``{'mi': member_index, 'other': other_node,
    'dir': (ux, uy, uz), 'L': length_m}``.
    """
    out = []
    for mi, m in enumerate(members):
        if m['a'] == node_idx:
            other = m['b']
        elif m['b'] == node_idx:
            other = m['a']
        else:
            continue
        x0, y0, z0 = nodes[node_idx]
        x1, y1, z1 = nodes[other]
        dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
        L = math.sqrt(dx * dx + dy * dy + dz * dz)
        if L < 1e-9:
            continue
        out.append({'mi': mi, 'other': other,
                    'dir': (dx / L, dy / L, dz / L), 'L': L})
    return out








def _normalise(v):
    n = _norm(v)
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-12 else (0.0, 0.0, 0.0)


def _normals_parallel(n1, n2, tol=0.05):
    """Two unit normals define the same plane if they are parallel (dot ~1)
    or antiparallel (dot ~-1)."""
    return abs(abs(_dot(n1, n2)) - 1.0) < tol


def find_coplanar_groups(nodes, members, node_idx, tol=0.05):
    """Find groups of coplanar members at *node_idx*.

    Two members from the same node always define a plane (their cross
    product gives the normal).  Three or more are coplanar when every
    additional member's direction has zero dot product with that normal.

    Returns list of lists, each inner list being dicts from
    ``_member_dirs_at_node`` that share a plane.  A member may appear in
    more than one group when it is collinear with multiple planes (rare
    but geometrically possible — e.g. a vertical member at the apex of a
    pyramid belongs to every vertical plane through the apex).

    Members with only one neighbour at the node (i.e. exactly one other
    member meets here) still form a pair.
    """
    dirs = _member_dirs_at_node(nodes, members, node_idx)
    if len(dirs) < 2:
        return []

    groups = []
    used_pairs = set()

    for i in range(len(dirs)):
        for j in range(i + 1, len(dirs)):
            pair_key = (dirs[i]['mi'], dirs[j]['mi'])
            if pair_key in used_pairs:
                continue
            normal = _cross(dirs[i]['dir'], dirs[j]['dir'])
            n_len = _norm(normal)
            if n_len < 1e-9:
                # collinear — these two define an infinite number of
                # planes; treat them as their own degenerate group
                groups.append([dirs[i], dirs[j]])
                used_pairs.add(pair_key)
                continue
            n_hat = (normal[0] / n_len, normal[1] / n_len, normal[2] / n_len)

            # see if this plane already exists in groups
            merged = False
            for g in groups:
                # check if this group's normal matches
                g_n = _cross(g[0]['dir'], g[1]['dir'] if len(g) > 1
                             else dirs[j]['dir'])
                g_n_len = _norm(g_n)
                if g_n_len < 1e-9:
                    continue
                g_n_hat = (g_n[0] / g_n_len, g_n[1] / g_n_len,
                           g_n[2] / g_n_len)
                if _normals_parallel(n_hat, g_n_hat, tol):
                    # add members not already in the group
                    mi_set = {d['mi'] for d in g}
                    if dirs[i]['mi'] not in mi_set:
                        g.append(dirs[i])
                    if dirs[j]['mi'] not in mi_set:
                        g.append(dirs[j])
                    used_pairs.add(pair_key)
                    merged = True
                    break

            if not merged:
                groups.append([dirs[i], dirs[j]])
                used_pairs.add(pair_key)

    return groups


def whitmore_width_m(landing_m=DEFAULT_LANDING_M,
                     angle_deg=WHITMORE_ANGLE_DEG):
    """Whitmore effective width in metres: ``2 * landing * tan(angle)``."""
    return 2.0 * landing_m * math.tan(math.radians(angle_deg))


def block_shear_areas_welded(t_mm, landing_mm, whitmore_mm):
    """Block-shear gross/net areas for a welded gusset (no holes).

    Returns ``(Agv, Anv, Ant, Agt)`` in mm².
    """
    t = max(t_mm, 0.0)
    Agv = Anv = 2.0 * t * landing_mm
    Agt = Ant = t * whitmore_mm
    return Agv, Anv, Ant, Agt


def gusset_buckling_check(P_kN, whitmore_mm, t_mm, landing_mm, Fy,
                          code=cirsoc.CIRSOC_301, K=GUSSET_K):
    """Thornton method: Whitmore width as a short column of thickness *t*.

    Only applies to compression (P_kN < 0).
    """
    if P_kN >= -1e-9:
        return {'applies': False, 'util': 0.0}
    r = t_mm / math.sqrt(12.0)
    if r <= 1e-9:
        return {'applies': False, 'util': float('inf')}
    slend = K * landing_mm / r
    area = whitmore_mm * t_mm
    res = cirsoc.compression_strength(area, slend, Fy, code,
                                      required=abs(P_kN) * 1e3)
    return {'applies': True, 'util': res.util, 'Fcr_MPa': res.Fcr,
            'slenderness': slend, 'Pd_kN': res.Pd / 1e3,
            'governing': res.governing}


def check_gusset_at_node(node_idx, group, member_res,
                         t_mm=DEFAULT_T_MM, Fy=DEFAULT_FY_MPA,
                         Fu=DEFAULT_FU_MPA, landing_m=DEFAULT_LANDING_M,
                         code=cirsoc.CIRSOC_301):
    """Run Whitmore + block-shear + buckling for every member in one
    coplanar *group* at *node_idx*.

    *group* is a list of dicts from ``find_coplanar_groups``.
    *member_res* is the ``results['member_res']`` list from the solver.

    Returns a list of per-member result dicts.
    """
    w_m = whitmore_width_m(landing_m)
    w_mm = w_m * 1000.0
    landing_mm = landing_m * 1000.0
    Agv, Anv, Ant, Agt = block_shear_areas_welded(t_mm, landing_mm, w_mm)

    out = []
    for d in group:
        mi = d['mi']
        N_kN = member_res[mi].get('N', 0.0)
        P_kN = abs(N_kN)

        area_mm2 = w_mm * t_mm
        sigma = (P_kN * 1e3) / area_mm2 if area_mm2 > 1e-9 else float('inf')
        wh_chk = cirsoc.stress_check(sigma, 0.0, Fy, code)

        bs = cirsoc.block_shear_strength(Agv, Anv, Ant, Fy, Fu, 1.0, code,
                                          required=P_kN * 1e3)

        gb = gusset_buckling_check(N_kN, w_mm, t_mm, landing_mm, Fy, code)

        worst_util = max(wh_chk.util, bs.util,
                         gb['util'] if gb.get('applies') else 0.0)
        if wh_chk.util >= bs.util and wh_chk.util >= gb.get('util', 0.0):
            governing = 'Whitmore (%s)' % wh_chk.governing
        elif bs.util >= gb.get('util', 0.0):
            governing = 'block shear (%s)' % bs.governing
        else:
            governing = 'gusset buckling (%s)' % gb.get('governing', '')

        out.append({
            'node': node_idx,
            'member': mi,
            'other': d['other'],
            'N_kN': N_kN,
            'mode': 'compression' if N_kN < -1e-9 else 'tension',
            'whitmore_mm': w_mm,
            't_mm': t_mm,
            'sigma_MPa': sigma,
            'whitmore_util': wh_chk.util,
            'Agv': Agv, 'Anv': Anv, 'Ant': Ant,
            'block_shear_Rd_kN': bs.Rd / 1e3,
            'block_shear_util': bs.util,
            'buckling_applies': gb.get('applies', False),
            'buckling_util': gb.get('util', 0.0),
            'buckling_Pd_kN': gb.get('Pd_kN'),
            'util': worst_util,
            'governing': governing,
            'ok': worst_util <= 1.0 + 1e-9,
        })
    return out


def check_all_gussets(nodes, members, member_res,
                      t_mm=DEFAULT_T_MM, Fy=DEFAULT_FY_MPA,
                      Fu=DEFAULT_FU_MPA, landing_m=DEFAULT_LANDING_M,
                      code=cirsoc.CIRSOC_301):
    """Check every node's coplanar groups and return a flat list of results.

    Each entry is a per-member-per-group check dict from
    ``check_gusset_at_node``, with an added ``'group'`` index so the
    caller can tell which members shared a plane.
    """
    all_checks = []
    group_id = 0
    for ni in range(len(nodes)):
        groups = find_coplanar_groups(nodes, members, ni)
        for group in groups:
            results = check_gusset_at_node(
                ni, group, member_res,
                t_mm=t_mm, Fy=Fy, Fu=Fu, landing_m=landing_m, code=code)
            for r in results:
                r['group'] = group_id
            all_checks.extend(results)
            group_id += 1
    return all_checks
