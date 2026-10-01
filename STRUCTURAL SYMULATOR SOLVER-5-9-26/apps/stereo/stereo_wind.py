"""Simplified wind (roadmap v2 4.6, option 1).

The user gives a direction and a base pressure q; every node is loaded with
q times its tributary area PROJECTED square to the wind, along the wind. No
shape coefficients, no windward/leeward split, no roof suction -- that is
option 2, CIRSOC 102, which needs the standard's coefficient tables and is
not this.

Two ways the wind meets a space structure, and the user says which:

  CLAD   the roof is sheeted, so the wind meets a SURFACE. Each roof node's
         tributary area (the same exact areas the area load uses) is turned
         by how squarely the surface faces the wind there: A |n . d|, with n
         the surface normal at the node. A flat roof under a level wind
         catches nothing; a vault's flank catches it all.
  OPEN   no sheeting: the wind meets the RODS. Each rod presents its width b
         times its length L, turned by its angle to the wind -- L b sin(t) --
         and the force is shared between its two ends.

Either way the force on a node is along the wind, q A_proj. Direction
convention: the wind BLOWS TOWARDS azimuth t (0 = +X, 90 = +Y, in plan) at
elevation p above the horizontal.
"""
import math

CLAD, OPEN = 'clad', 'open'


def wind_direction(azimuth_deg, elevation_deg=0.0):
    """The unit vector the wind blows along."""
    t, p = math.radians(azimuth_deg), math.radians(elevation_deg)
    return (math.cos(p) * math.cos(t), math.cos(p) * math.sin(t),
            math.sin(p))


def _fit_normal(points):
    """Unit normal of the best-fit plane through `points`, or None."""
    import numpy as np
    if len(points) < 3:
        return None
    P = np.asarray(points, dtype=float)
    P = P - P.mean(axis=0)
    try:
        _u, s, vt = np.linalg.svd(P, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    if s[1] < 1e-9 * max(s[0], 1e-12):
        return None                      # the points lie on a line
    n = vt[-1]
    if n[2] < 0:
        n = -n
    return tuple(float(c) for c in n / np.linalg.norm(n))


def surface_normals(nodes, members, load_nodes):
    """{node: unit normal} over the roof, from each roof node and the roof
    nodes a rod joins it to. A node whose neighbourhood is too thin to fit a
    plane through gets the vertical, which is right for the flat roofs where
    that happens."""
    roof = set(load_nodes)
    nbrs = {n: set() for n in roof}
    for m in members:
        a, b = m['a'], m['b']
        if a in roof and b in roof:
            nbrs[a].add(b)
            nbrs[b].add(a)
    out = {}
    for n in roof:
        pts = [nodes[n]] + [nodes[k] for k in nbrs[n]]
        out[n] = _fit_normal(pts) or (0.0, 0.0, 1.0)
    return out


def member_width_m(m):
    """The width a rod shows the wind: its section depth -- 2c from the
    catalog, or the round-tube estimate sqrt(2I/A) doubled for a hand-typed
    section (the same fallback the bending check uses)."""
    c = float(m.get('c_cm', 0.0) or 0.0)
    if c <= 0.0:
        I, A = float(m.get('I', 0.0) or 0.0), float(m.get('A', 0.0) or 0.0)
        c = math.sqrt(2.0 * I / A) if (I > 0.0 and A > 0.0) else 0.0
    return 2.0 * c / 100.0


def clad_wind_loads(nodes, members, load_nodes, q_kN_m2, direction):
    d = _unit(direction)
    normals = surface_normals(nodes, members, load_nodes)
    loads = []
    for n, area in load_nodes.items():
        if not (0 <= n < len(nodes)):
            continue
        nx, ny, nz = normals[n]
        A = float(area) * abs(nx * d[0] + ny * d[1] + nz * d[2])
        P = q_kN_m2 * A
        if P:
            loads.append({'node': n, 'fx': P * d[0], 'fy': P * d[1],
                          'fz': P * d[2]})
    return loads


def lattice_wind_loads(nodes, members, q_kN_m2, direction):
    d = _unit(direction)
    acc = {}
    for m in members:
        a, b = m['a'], m['b']
        ax, ay, az = nodes[a]
        bx, by, bz = nodes[b]
        ex, ey, ez = bx - ax, by - ay, bz - az
        L = math.sqrt(ex * ex + ey * ey + ez * ez)
        if L < 1e-12:
            continue
        ex, ey, ez = ex / L, ey / L, ez / L
        cx = ey * d[2] - ez * d[1]
        cy = ez * d[0] - ex * d[2]
        cz = ex * d[1] - ey * d[0]
        sin_t = math.sqrt(cx * cx + cy * cy + cz * cz)
        P = q_kN_m2 * L * member_width_m(m) * sin_t
        for n in (a, b):
            acc[n] = acc.get(n, 0.0) + P / 2.0
    return [{'node': n, 'fx': P * d[0], 'fy': P * d[1], 'fz': P * d[2]}
            for n, P in sorted(acc.items()) if P]


def wind_loads(nodes, members, load_nodes, q_kN_m2, azimuth_deg,
               elevation_deg=0.0, mode='clad'):
    """The simplified wind case as nodal loads. `mode` is 'clad' or 'open'."""
    d = wind_direction(azimuth_deg, elevation_deg)
    if mode == OPEN:
        return lattice_wind_loads(nodes, members, q_kN_m2, d)
    return clad_wind_loads(nodes, members, load_nodes or {}, q_kN_m2, d)


def total(loads):
    return tuple(sum(ld.get(k, 0.0) for ld in loads) for k in ('fx', 'fy', 'fz'))


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-12:
        raise ValueError('the wind needs a direction')
    return tuple(c / n for c in v)
