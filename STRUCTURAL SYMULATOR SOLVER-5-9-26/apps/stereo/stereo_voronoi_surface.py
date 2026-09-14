"""Voronoi tessellation ON the structure's own surface.

A space truss is a SHELL: a two-dimensional surface living in three
dimensions, with at most a slab's thickness. Its natural tessellation is
therefore two-dimensional and lies on that surface -- not a three-
dimensional tessellation of some volume inferred from the node cloud.

This module replaces the convex-hull domain stereo_voronoi3d used. That
domain was wrong wherever the structure is CONCAVE, which is most of them:
the hull of a vault bridges the void the vault arches over, so the arch is
sealed shut and a flat floor slab appears underneath it (measured on the
parabolic vault: 39% of the hull's surface is one slab in the z = -0.60 m
plane, 2.01 m from the nearest rod, and 27% of everything the old Skin view
drew was surface the structure does not have).

Three things make this correct where a hull, an alpha shape or a band
around the rods are all approximations:

DOMAIN -- the mesh's OWN panels, from stereo_geometry.find_cells: every
    minimal triangle and quad of existing members. Nothing is inferred and
    there is no parameter to tune. On all 14 grid families this covers 100%
    of the rods. It works identically on a hand-edited or Excel-imported
    mesh, because it is derived from the members rather than from any
    generator's metadata.

METRIC -- distance measured ALONG the fabric, not through space. A panel's
    candidate sites are the sites lying ON that panel (its own edge rods,
    or its own corner nodes), so every candidate is on the surface and the
    answer is geodesic by construction. This is not a refinement: on the
    flat double-layer grid the slab depth is 1.5 m and the chord spacing
    3.0 m, so under a straight-line 3D test a top panel's own chords sit
    1.500 m away while four web diagonals sit 1.299 m away -- and those
    four are an EXACT tie, leaving the winner to floating-point ordering.
    0% of top-surface panels got a top-layer rod, and the top surface came
    out a red/blue chequerboard of pure noise.

RESOLUTION -- adaptive. A coarse mesh (a 90-panel dome) is subdivided until
    the cell boundaries read crisply; a dense mesh (a 2999-panel vault)
    already has panels smaller than a cell and is left alone. Sub-patches
    choose among their own panel's owner plus its neighbours' owners, which
    sharpens the boundary without letting a distant site reach across the
    model.

Everything here works in MODEL space and returns plain 3D polygons, leaving
projection, depth sorting and colour to the renderer -- which is what makes
the geometry testable without building a widget.
"""
import heapq
import math

import numpy as np
from scipy.spatial import cKDTree

from apps.stereo.stereo_geometry_cells import find_cells

# Views. The first two tessellate the surface; Section is the one genuinely
# volumetric view, and it cuts the truss's own fabric rather than any
# inferred hull (see section_mask).
VIEW_SURFACE = 'Surface'
VIEW_CELLS = 'Cells'
VIEW_SECTION = 'Section'
VIEWS = (VIEW_SURFACE, VIEW_CELLS, VIEW_SECTION)

# How many drawable patches the surface is subdivided towards. Measured
# rather than guessed: ~2600 Tk canvas polygons redraw in under a tenth of
# a second, which is what keeps orbiting smooth.
TARGET_PATCHES = 2600
SUBDIVIDE_MAX = 3
SECTION_STEPS_MAX = 52


def panels_of(nodes, members):
    """Every minimal 3-/4-node panel of the mesh -- the fabric itself.

    Thin wrapper over find_cells so callers need not import two modules;
    the app caches the result per mesh edit (see _get_shaded_cells), since
    find_cells is O(members x degree^2) and the fabric only changes when
    the model does.
    """
    return find_cells(nodes, members)


def panel_polys(nodes, panels):
    pts = np.asarray(nodes, dtype=float)
    return [pts[list(p['nodes'])] for p in panels]


def panel_centroids(polys):
    if not polys:
        return np.zeros((0, 3))
    return np.array([p.mean(axis=0) for p in polys])


def panel_adjacency(panels):
    """Panels sharing a member are neighbours -- the fabric's own topology.

    Returns (adj, by_member): adj[i] is the set of panels touching panel i,
    and by_member[m] the panels that member m belongs to.
    """
    by_member = {}
    for i, p in enumerate(panels):
        for mi in p['members']:
            by_member.setdefault(mi, []).append(i)
    adj = {i: set() for i in range(len(panels))}
    for fs in by_member.values():
        for a in fs:
            for b in fs:
                if a != b:
                    adj[a].add(b)
    return adj, by_member


def assign_owners(centroids, panel_sites, sites, adj):
    """Which site owns each panel, measured along the fabric.

    `panel_sites[i]` lists the site indices lying ON panel i -- its own edge
    rods for rod-midpoint sites, its own corners for nodal ones. Because
    every candidate is on the panel, picking the nearest of them by straight
    line IS the geodesic answer, and the whole pass is O(panels) with no
    graph search at all.

    The Dijkstra below is the fallback for a panel that carries no site,
    which does not arise for rod-midpoint or nodal sites but keeps the
    engine usable if sites are ever subsampled. -1 marks a panel no site can
    reach (an isolated fragment); the caller drops it rather than colouring
    it with a guess.
    """
    S = np.asarray(sites, dtype=float)
    n = len(centroids)
    owner = [-1] * n
    for i in range(n):
        cand = panel_sites[i]
        if not cand:
            continue
        c = centroids[i]
        best, best_d = -1, math.inf
        for k in cand:
            d = float(np.dot(S[k] - c, S[k] - c))
            if d < best_d:
                best, best_d = int(k), d
        owner[i] = best
    if all(o >= 0 for o in owner) or not n:
        return owner
    pq = [(0.0, i, owner[i]) for i in range(n) if owner[i] >= 0]
    heapq.heapify(pq)
    dist = [0.0 if owner[i] >= 0 else math.inf for i in range(n)]
    while pq:
        d, i, k = heapq.heappop(pq)
        if d > dist[i]:
            continue
        for j in adj[i]:
            nd = d + float(np.linalg.norm(centroids[j] - centroids[i]))
            if nd < dist[j]:
                dist[j], owner[j] = nd, k
                heapq.heappush(pq, (nd, j, k))
    return owner


def subdivision_levels(n_panels, target=TARGET_PATCHES):
    """How many times to split each panel to land near the patch budget.

    A panel fans into (corners - 2) triangles, so a quad-dominated mesh
    yields about 2 per panel; each level multiplies by 4.
    """
    if n_panels <= 0:
        return 0
    levels = 0
    while n_panels * 2 * (4 ** (levels + 1)) <= target and levels < SUBDIVIDE_MAX:
        levels += 1
    return levels


def fan_triangles(poly):
    """A 3- or 4-node panel as triangles, fanned from its first corner."""
    return [np.array([poly[0], poly[i], poly[i + 1]])
            for i in range(1, len(poly) - 1)]


def subdivide(tris, levels):
    out = list(tris)
    for _ in range(levels):
        nxt = []
        for a, b, c in out:
            ab, bc, ca = (a + b) / 2.0, (b + c) / 2.0, (c + a) / 2.0
            nxt.append(np.array([a, ab, ca]))
            nxt.append(np.array([ab, b, bc]))
            nxt.append(np.array([ca, bc, c]))
            nxt.append(np.array([ab, bc, ca]))
        out = nxt
    return out


def build_surface(nodes, panels, sites, panel_sites, target=TARGET_PATCHES):
    """[(polygon, site_index)] covering the whole fabric, in model space.

    A panel is emitted whole when the mesh is already finer than the cell
    spacing; otherwise it is subdivided and each sub-patch goes to the
    nearest of a SHORT candidate list -- its own panel's owner plus its
    neighbours' -- which sharpens a cell boundary that falls mid-panel
    while keeping every candidate a short walk away across the surface.
    """
    if not panels or len(sites) == 0:
        return []
    polys = panel_polys(nodes, panels)
    cen = panel_centroids(polys)
    adj, _ = panel_adjacency(panels)
    owner = assign_owners(cen, panel_sites, sites, adj)
    levels = subdivision_levels(len(panels), target)
    S = np.asarray(sites, dtype=float)
    out = []
    for i, poly in enumerate(polys):
        if owner[i] < 0:
            continue
        if levels == 0:
            out.append((poly, owner[i]))
            continue
        cand = sorted({owner[i]} | {owner[j] for j in adj[i] if owner[j] >= 0})
        cs = S[cand]
        for tri in subdivide(fan_triangles(poly), levels):
            k = cand[int(np.argmin(((cs - tri.mean(axis=0)) ** 2).sum(axis=1)))]
            out.append((tri, k))
    return out


def cell_boundary_edges(nodes, members, panels, owners):
    """The rods where one cell meets another, as (p0, p1) model-space pairs.

    Drawn over the fill, this is what turns a continuous colour field into
    visible CELLS. A rod is a boundary when the panels meeting along it do
    not all belong to the same site -- deliberately not "exactly two panels
    share it", because in a braced mesh a rod is commonly shared by many:
    on the parabolic vault 2999 panels spread over 943 rods, about eleven
    panels per rod, and an exactly-two rule found no boundaries at all.
    """
    pts = np.asarray(nodes, dtype=float)
    by_member = {}
    for i, p in enumerate(panels):
        for mi in p['members']:
            by_member.setdefault(mi, []).append(i)
    edges = []
    for mi, fs in by_member.items():
        if len({owners[i] for i in fs if owners[i] >= 0}) > 1:
            m = members[mi]
            edges.append((pts[m['a']], pts[m['b']]))
    return edges


def section_plane(nodes, axis, position):
    """A grid of quads filling one plane through the model's extent.

    `position` runs 0..1 along `axis`, so the control driving it is
    independent of the model's own dimensions.
    """
    pts = np.asarray(nodes, dtype=float)
    if len(pts) == 0:
        return []
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    span = hi - lo
    at = lo[axis] + float(np.clip(position, 0.0, 1.0)) * span[axis]
    other = [k for k in range(3) if k != axis]
    n = int(min(SECTION_STEPS_MAX, max(12, math.sqrt(TARGET_PATCHES))))
    u = np.linspace(lo[other[0]], hi[other[0]], n + 1)
    v = np.linspace(lo[other[1]], hi[other[1]], n + 1)
    out = []
    for i in range(n):
        for j in range(n):
            quad = np.zeros((4, 3))
            quad[:, axis] = at
            for k, (uu, vv) in enumerate(((u[i], v[j]), (u[i + 1], v[j]),
                                          (u[i + 1], v[j + 1]), (u[i], v[j + 1]))):
                quad[k, other[0]] = uu
                quad[k, other[1]] = vv
            out.append(quad)
    return out


def default_cut_thickness(nodes, panels):
    """Half the separation between the fabric's two skins.

    A section is a cut through the truss's own material, so its thickness is
    a property of the structure, not a number to invent. The separation is
    measured as the distance from each panel to the nearest panel it shares
    no NODE with -- on a double-layer mesh that is the other skin (1.5 m on
    the flat grid, 0.6 m on a vault), and on a single-layer shell it falls
    back to one module, which is the right answer there too since a single
    skin encloses no volume of its own.
    """
    polys = panel_polys(nodes, panels)
    if len(polys) < 2:
        return 0.0
    cen = panel_centroids(polys)
    rings = [set(p['nodes']) for p in panels]
    tree = cKDTree(cen)
    k = min(24, len(cen))
    d, idx = tree.query(cen, k=k)
    seps = []
    for i in range(len(cen)):
        for dist, j in zip(np.atleast_1d(d[i]), np.atleast_1d(idx[i])):
            j = int(j)
            if j != i and not (rings[i] & rings[j]):
                seps.append(float(dist))
                break
    if not seps:
        return 0.0
    return round(0.5 * float(np.median(seps)), 3)


def section_mask(quads, nodes, panels, thickness, levels=1):
    """Which of `quads` lie within `thickness` of the fabric.

    This is what keeps the Section view on the truss's own material instead
    of filling the void a vault arches over -- the failure that made the old
    convex-hull domain draw a floor slab. The surface is sampled by
    subdividing its panels and the test becomes a nearest-neighbour query,
    so the cost does not grow with how finely the plane is gridded.
    """
    if not len(quads) or not panels or thickness is None or thickness <= 0:
        return np.zeros(len(quads), dtype=bool)
    polys = panel_polys(nodes, panels)
    samples = []
    for poly in polys:
        for tri in subdivide(fan_triangles(poly), levels):
            samples.append(tri.mean(axis=0))
            samples.extend(tri)
    cloud = np.asarray(samples, dtype=float)
    centres = np.array([q.mean(axis=0) for q in quads])
    return cKDTree(cloud).query(centres)[0] <= thickness


def build_section(nodes, panels, sites, axis, position, thickness):
    """[(quad, site_index)] for one cut plane through the truss's fabric.

    The one genuinely volumetric view: the plane is gridded across the
    model's extent, then clipped to the material the truss actually occupies
    and the space immediately enclosed by it. Owners are nearest-site in
    straight-line 3D here, unlike the surface views -- a point inside the
    fabric is not ON any panel, so there is no surface to walk along.
    """
    quads = section_plane(nodes, axis, position)
    if not quads or len(sites) == 0:
        return []
    keep = section_mask(quads, nodes, panels, thickness)
    if not keep.any():
        return []
    centres = np.array([q.mean(axis=0) for q in quads])
    owner = cKDTree(np.asarray(sites, dtype=float)).query(centres)[1]
    return [(quads[i], int(owner[i])) for i in np.nonzero(keep)[0]]
