"""Gusset-plate verification for 3D space-frame nodes.

Adapts the 2D logic from apps/truss/truss_plates.py to 3D:

  * For each node, members are grouped into coplanar sets.
  * For each coplanar group (>= 2 members sharing a plane), the classic
    gusset checks run: Whitmore effective section, block shear (J4.3),
    and Thornton gusset buckling (E3) for compression members.

Units at this boundary match the rest of the stereo module:
  kN, kN-m, m, GPa, cm², cm⁴, MPa.
cirsoc_301 works in N, mm, MPa — conversions happen once per function.
"""
import math

import cirsoc_301 as cirsoc

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


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


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
