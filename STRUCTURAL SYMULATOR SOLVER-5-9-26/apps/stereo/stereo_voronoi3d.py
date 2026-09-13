"""Three-dimensional Voronoi tessellation of a space structure.

The Stereo tab's original Voronoi mode tessellated the SCREEN: it projected
the model to 2D and ran a planar Voronoi over the projected points. That is
wrong in two ways -- the cells spill into empty space beside the structure,
and the whole tessellation changes every time the model is orbited, because
it was never attached to the model in the first place. This module replaces
it with a tessellation of the MODEL, computed once per geometry and held
still while the camera moves around it.

Two questions have to be answered before any of it can be drawn, and both
are exposed to the user rather than decided here:

DOMAIN -- which volume the cells are allowed to occupy.

  DOMAIN_HULL  the convex hull of the nodes: the closed polyhedron through
               the outermost joints. No parameter to set, and exactly right
               for a box-like structure, but it bridges over concavities --
               under a vault it fills the hollow the structure encloses.
  DOMAIN_BAND  everything within `band_r` metres of a rod. Follows the real
               shape of any structure, convex or not, and its parameter is
               a thickness in metres rather than an abstract radius.

  (An alpha shape was measured as a third option and rejected: on a
  SINGLE-layer shell every Delaunay tetrahedron has roughly the circumradius
  of the shell's own curvature, so the shape jumps straight from empty to
  the full hull with no usable setting in between. It works only on double-
  layer meshes, which is not a promise this can make to every model.)

VIEW -- how a solid tessellation is put on a flat canvas.

  VIEW_SKIN     colour the structure's outer surface by the cell behind it.
  VIEW_SECTION  colour one plane through the volume; the plane can be moved.
  VIEW_CELLS    the cell polyhedra themselves, drawn translucent.

Everything here works in MODEL space and returns plain 3D polygons, leaving
projection, depth sorting and colour to the renderer -- which is what makes
the geometry testable without building a widget.
"""
import math

import numpy as np
from scipy.spatial import ConvexHull, HalfspaceIntersection, cKDTree

DOMAIN_HULL = 'Convex hull'
DOMAIN_BAND = 'Band around rods'
DOMAINS = (DOMAIN_HULL, DOMAIN_BAND)

VIEW_SKIN = 'Skin'
VIEW_SECTION = 'Section'
VIEW_CELLS = 'Cells'
VIEWS = (VIEW_SKIN, VIEW_SECTION, VIEW_CELLS)

# A patch count that keeps a redraw comfortably under a tenth of a second on
# the meshes this app generates; the skin and section grids are subdivided
# towards it rather than to a fixed resolution, so a coarse model gets a fine
# tessellation and a 3000-rod model still redraws promptly.
TARGET_PATCHES = 2600
SECTION_STEPS_MAX = 52
# Building the cell polyhedra costs about 0.4 s per thousand sites and is
# cached per geometry, so the binding constraint is not the build but the
# redraw: every cell face is a canvas polygon, and a thousand cells is
# already ~19 000 of them. Past this the Cells view stops being interactive
# while Skin and Section still are, so the renderer declines and says which
# view to use instead of freezing.
CELLS_SITE_LIMIT = 1200
# A Voronoi cell is decided only by the sites near it, so bisectors against
# distant sites never touch the answer. Taking the nearest few turns an
# O(n) half-space set per cell into a fixed one.
CELL_NEIGHBOURS = 26


def member_midpoints(nodes, members):
    """The natural Voronoi site for a per-ROD quantity (force, utilization)."""
    pts = np.asarray(nodes, dtype=float)
    return np.array([(pts[m['a']] + pts[m['b']]) / 2.0 for m in members]) \
        if members else np.zeros((0, 3))


def median_rod_length(nodes, members):
    pts = np.asarray(nodes, dtype=float)
    if not members:
        return 0.0
    L = [float(np.linalg.norm(pts[m['a']] - pts[m['b']])) for m in members]
    return float(np.median(L))


def default_band_radius(nodes, members):
    """A fifth of a typical rod.

    Chosen by measuring, not by taste: at half a rod length the band keeps
    100% of the hull on a flat grid and 61% on a vault -- i.e. on the
    flattest structures the domain toggle would appear to do nothing at
    all, which is the worst possible default for a control whose whole job
    is to show a difference. A fifth keeps roughly a fifth to two thirds
    across the shapes this app generates, so the band always reads as a
    band. The field is editable; this only has to be a sane starting point.
    """
    return round(0.2 * median_rod_length(nodes, members), 3) or 0.5


def hull_of(nodes):
    """(equations, simplices) of the convex hull, or None if degenerate.

    A flat or collinear node set has no 3D hull at all (every generator in
    this app produces a genuine 3D mesh, but a hand-edited or imported one
    need not), so the caller is told rather than left with an exception.
    """
    pts = np.asarray(nodes, dtype=float)
    if len(pts) < 4:
        return None
    try:
        h = ConvexHull(pts)
    except Exception:
        return None
    return h.equations, h.simplices


def inside_hull(equations, P, tol=1e-9):
    return np.all(equations[:, :3] @ P.T + equations[:, 3:4] <= tol, axis=0)


def distance_to_members(P, nodes, members):
    """Distance from every point in P to the nearest rod SEGMENT.

    Segment rather than infinite line, and rather than distance to the
    nearest node: a band built from node distances alone would bulge at the
    joints and pinch in the middle of every rod.
    """
    pts = np.asarray(nodes, dtype=float)
    P = np.asarray(P, dtype=float)
    if not members or len(P) == 0:
        return np.full(len(P), np.inf)
    A = pts[[m['a'] for m in members]]
    AB = pts[[m['b'] for m in members]] - A
    L2 = np.maximum((AB * AB).sum(axis=1), 1e-12)
    # Chunked over POINTS and vectorised over members: the whole cross
    # product is points x rods x 3, which is tens of millions of floats on a
    # 3000-rod model, so it is walked in slices that stay cache-friendly
    # instead of either materialising it whole or looping rods in Python.
    best = np.empty(len(P))
    chunk = max(1, int(120_000 // max(1, len(members))))
    for s in range(0, len(P), chunk):
        Q = P[s:s + chunk]
        t = np.clip(((Q[:, None, :] - A) * AB).sum(axis=2) / L2, 0.0, 1.0)
        delta = Q[:, None, :] - (A + t[:, :, None] * AB)
        best[s:s + chunk] = np.sqrt((delta * delta).sum(axis=2)).min(axis=1)
    return best


def within_band(P, nodes, members, r):
    """Mask of the points in P lying within `r` of a rod.

    Sampled rather than exact: the rods are walked at a step of r/6 and the
    test becomes a nearest-neighbour query against those samples, which is a
    KD-tree lookup instead of a point-to-segment distance against every rod
    in the model. The band's edge can therefore sit up to about r/12 out of
    place -- invisible at any drawing scale, and the cost on a 3000-rod grid
    drops from over a second to a few milliseconds, which is the difference
    between a usable domain toggle and one nobody would leave switched on.
    distance_to_members above stays exact for anything that needs it.
    """
    P = np.asarray(P, dtype=float)
    # A non-positive radius is not a band at all. Rejected here rather than
    # clamped, because the sampling step is derived FROM r: a negative radius
    # once drove the step to its 1e-6 floor, which asked for a few million
    # samples per rod and took the process out with it.
    if not members or len(P) == 0 or not r or r <= 0:
        return np.zeros(len(P), dtype=bool)
    pts = np.asarray(nodes, dtype=float)
    step = max(r / 6.0, 1e-6)
    samples = []
    for m in members:
        a, b = pts[m['a']], pts[m['b']]
        L = float(np.linalg.norm(b - a))
        n = max(1, int(math.ceil(L / step)))
        t = np.linspace(0.0, 1.0, n + 1)[:, None]
        samples.append(a + t * (b - a))
    cloud = np.vstack(samples)
    return cKDTree(cloud).query(P)[0] <= r


def _subdivide(tris, levels):
    out = list(tris)
    for _ in range(levels):
        nxt = []
        for t in out:
            a, b, c = t
            ab, bc, ca = (a + b) / 2.0, (b + c) / 2.0, (c + a) / 2.0
            nxt.append(np.array([a, ab, ca]))
            nxt.append(np.array([ab, b, bc]))
            nxt.append(np.array([ca, bc, c]))
            nxt.append(np.array([ab, bc, ca]))
        out = nxt
    return out


def skin_patches(nodes, simplices):
    """The hull's own faces, subdivided until there are enough of them to
    resolve the cell pattern sitting behind the surface."""
    pts = np.asarray(nodes, dtype=float)
    base = [pts[s] for s in simplices]
    if not base:
        return []
    levels = 0
    while len(base) * (4 ** (levels + 1)) <= TARGET_PATCHES and levels < 4:
        levels += 1
    return _subdivide(base, levels)


def section_patches(nodes, axis, position):
    """A grid of quads filling one plane through the model.

    `position` runs 0..1 across the model's extent along `axis`, so the
    control that drives it is independent of the model's own dimensions.
    """
    pts = np.asarray(nodes, dtype=float)
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
            for k, (uu, vv) in enumerate(((u[i], v[j]), (u[i+1], v[j]),
                                          (u[i+1], v[j+1]), (u[i], v[j+1]))):
                quad[k, other[0]] = uu
                quad[k, other[1]] = vv
            out.append(quad)
    return out


def cell_patches(sites, equations, centroid):
    """Exact Voronoi cell polyhedra, clipped to the hull, as triangles.

    A Voronoi cell is the intersection of the half-spaces bounded by the
    perpendicular bisectors to the other sites; the hull is an intersection
    of half-spaces too, so clipping one against the other still leaves a
    single convex polyhedron and the unbounded cells at the edge of the
    point set need no special handling.

    Returns (triangles, owner_index) pairs. A cell that degenerates (a site
    on the hull surface can produce one) is dropped rather than guessed at.
    """
    out = []
    if len(sites) < 2:
        return out
    tree = cKDTree(sites)
    k = min(CELL_NEIGHBOURS + 1, len(sites))
    _, nbrs = tree.query(sites, k=k)
    for i, si in enumerate(sites):
        others = sites[[j for j in np.atleast_1d(nbrs[i]) if j != i]]
        if len(others) == 0:
            continue
        n = others - si
        mid = (others + si) / 2.0
        b = -np.einsum('ij,ij->i', n, mid)
        A = np.vstack([equations, np.column_stack([n, b])])
        pts = None
        for eps in (1e-3, 1e-2, 5e-2, 1.5e-1):
            p = si + eps * (centroid - si)
            if np.all(A[:, :3] @ p + A[:, 3] < -1e-12):
                try:
                    pts = HalfspaceIntersection(A, p).intersections
                except Exception:
                    pts = None
                break
        if pts is None or len(pts) < 4:
            continue
        try:
            ch = ConvexHull(pts)
        except Exception:
            continue
        out.append(([pts[s] for s in ch.simplices], i))
    return out


def build(nodes, members, sites, view, domain, band_r=None,
          section_axis=2, section_position=0.5):
    """Every drawable patch of the tessellation, in model space.

    Returns a list of (polygon, site_index) pairs: `polygon` is an (n, 3)
    array of model-space points and `site_index` says which site owns it,
    which is what the renderer turns into a colour. Returns [] when the
    tessellation cannot be built (too few sites, a degenerate hull, or a
    cell count past the interactive limit) -- the caller reports that in
    the legend rather than drawing something misleading.
    """
    pts = np.asarray(nodes, dtype=float)
    sites = np.asarray(sites, dtype=float)
    if len(sites) < 2 or len(pts) < 4:
        return []
    hull = hull_of(pts)
    if hull is None:
        return []
    equations, simplices = hull

    if view == VIEW_CELLS:
        if len(sites) > CELLS_SITE_LIMIT:
            return []
        cells = cell_patches(sites, equations, pts.mean(axis=0))
        if domain == DOMAIN_BAND and band_r:
            keep = within_band(sites, pts, members, band_r)
            cells = [(tris, i) for tris, i in cells if keep[i]]
        return [(tri, i) for tris, i in cells for tri in tris]

    patches = (skin_patches(pts, simplices) if view == VIEW_SKIN
               else section_patches(pts, section_axis, section_position))
    if not patches:
        return []
    centres = np.array([p.mean(axis=0) for p in patches])

    keep = inside_hull(equations, centres, tol=1e-6)
    if domain == DOMAIN_BAND and band_r:
        keep &= within_band(centres, pts, members, band_r)
    if not keep.any():
        return []

    owner = cKDTree(sites).query(centres)[1]
    return [(patches[i], int(owner[i])) for i in np.nonzero(keep)[0]]
