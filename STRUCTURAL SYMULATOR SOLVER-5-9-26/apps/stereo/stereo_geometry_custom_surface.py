"""Custom surfaces: user-typed expressions plus a domain/module wizard.

Two ways to DEFINE a surface -- make_height_field_surface (a height field
z = f(x, y)) and make_parametric_surface (a full x(u,v)/y(u,v)/z(u,v)
triple, needed for anything a height field cannot express, like a torus or
a helicoid) -- are both normalized to the SAME internal shape, a callable
surface(p, q) -> (x, y, z). Everything below is therefore written once and
behaves identically regardless of how the surface was defined.

Independently, a domain/module wizard samples that callable into an actual
mesh: a coordinate system (Cartesian or Polar) for the domain's (p, q)
shape, a module PATTERN (square/diagonal/isometric) for how sampled points
connect, and either a 2D module (custom_surface_grid with depth 0 -- one
layer lying on the surface), a 3D module (two layers offset along the
surface's own local normal), or two independently-defined surfaces
connected as a double layer (custom_surface_between).

Expression parsing itself lives in apps/stereo/expr_math.py.
"""
import math

from apps.stereo import expr_math
from apps.stereo.stereo_geometry_core import _NodeBank, _add_member


def make_domain_fn(expr, ctx=None):
    """Compile a "keep this part of the plan?" rule into f(x, y) -> bool.

    The grid generators all lay out a RECTANGLE (or, in polar, an annular
    sector), because that is what a pair of ranges describes. Real roofs
    are not rectangles: they have a round plan, an L, a courtyard cut out
    of the middle. The mask is how a rectangle becomes those, without
    every generator having to learn about shapes:

        x**2 + y**2 < 36              a circular plan of radius 6
        not (x > 6 and y > 6)         an L, with one quadrant removed
        hypot(x, y) > 3               a ring, open at the middle

    `ctx` is an optional dict of extra named constants the rule may use
    (e.g. {'Lx': 12.0}), so a rule can be written in terms of the domain
    it will be applied to rather than in raw metres.

    An empty expression means "keep everything" and returns None, which
    `apply_domain_mask` passes straight through -- the no-mask case costs
    nothing and needs no special-casing at the call site.
    """
    text = (expr or '').strip()
    if not text:
        return None
    ctx = dict(ctx or {})
    names = ('x', 'y') + tuple(ctx)
    inner = expr_math.compile_expression(text, names)
    extra = tuple(ctx[k] for k in ctx)
    return lambda x, y: bool(inner(x, y, *extra))


def make_height_field_surface(expr_z):
    """A height-field surface z = f(x, y) from a typed expression, wrapped
    to the shared surface(p, q) -> (x, y, z) shape used everywhere below
    (p, q play the role of x, y here: the surface is just (p, q, f(p, q))).
    Raises expr_math.ExpressionError for a bad expression."""
    f = expr_math.compile_expression(expr_z, ('x', 'y'))
    return lambda p, q: (p, q, f(p, q))


def make_parametric_surface(expr_x, expr_y, expr_z):
    """A fully parametric surface (x(u, v), y(u, v), z(u, v)) from three
    typed expressions, wrapped to the shared surface(p, q) -> (x, y, z)
    shape (p, q play the role of u, v here). Needed for any surface a
    height field cannot express, e.g. a torus:
    x=(R+r*cos(v))*cos(u), y=(R+r*cos(v))*sin(u), z=r*sin(v).
    Raises expr_math.ExpressionError for a bad expression."""
    fx = expr_math.compile_expression(expr_x, ('u', 'v'))
    fy = expr_math.compile_expression(expr_y, ('u', 'v'))
    fz = expr_math.compile_expression(expr_z, ('u', 'v'))
    return lambda p, q: (fx(p, q), fy(p, q), fz(p, q))


def _domain_to_xy(coord, p, q, pole=(0.0, 0.0)):
    """Resolve one domain-lattice (p, q) pair to the flat 2-vector actually
    fed into the surface function. Cartesian: identity (p, q ARE the
    surface's own x, y or u, v). Polar: p is read as a RADIUS and q as an
    ANGLE (radians), converted the usual way -- so a Polar domain samples
    the same surface function over a disk/sector/annulus instead of a
    rectangle.

    `pole` is where that disk is CENTRED in the surface's own parameter
    plane, and it only means anything for a Polar domain. It used to be
    hard-wired to the origin, which is right only when the surface's apex
    happens to sit there: a polar grid's whole point is that its rings run
    along the surface's own contours and its ribs run straight down the
    fall, and both are true only about the summit. Put the pole at (0, 0)
    on a surface whose summit is at (4, 4) and the rings cut across the
    contours at an angle that changes as they go round -- the modules stop
    being congruent and the ribs stop being the shortest way down.
    """
    if coord == 'cartesian':
        return p, q
    if coord == 'polar':
        return pole[0] + p * math.cos(q), pole[1] + p * math.sin(q)
    raise ValueError(f"coord must be 'cartesian' or 'polar', got {coord!r}")


def surface_summits(surface, x_range, y_range, samples=41, kind='max'):
    """Every local summit (or hollow) of `surface` over a rectangle of its
    own parameter plane, strongest first.

    A polar domain has exactly ONE pole, and a pole is a singular point of
    the parameterisation: every rib meets there and the modules around it
    are wedges, not squares. That is a perfect fit for a surface with one
    summit and a nuisance on a surface with several -- a sinusoidal roof
    over a 4 x 4 field of humps has sixteen of them, and no single polar
    grid can be centred on more than one.

    So this exists to make that a decision rather than an accident: it
    counts the summits and says where they are, which is what tells you
    whether a polar grid is the right chart at all (one summit: yes, put
    the pole on it), or whether the surface wants a Cartesian/isometric
    lattice (which has no pole and so does not care where the summits are),
    or one polar patch per summit stitched along their shared valleys.

    `kind` is 'max' for summits and 'min' for hollows. Detection is a plain
    8-neighbour comparison on a sampled grid, so a summit narrower than the
    sample spacing can be missed -- raise `samples` for a surface that
    ripples fast. Points on the rectangle's own edge are never reported: a
    domain boundary is not a summit of the surface, only of the window.

    Returns [{'x', 'y', 'z'}, ...], highest (or deepest) first.
    """
    x0, x1 = x_range
    y0, y1 = y_range
    n = max(3, int(samples))
    xs = [x0 + (x1 - x0) * i / (n - 1) for i in range(n)]
    ys = [y0 + (y1 - y0) * j / (n - 1) for j in range(n)]
    z = [[surface(x, y)[2] for y in ys] for x in xs]
    better = (lambda a, b: a > b) if kind == 'max' else (lambda a, b: a < b)
    found = []
    for i in range(1, n - 1):
        for j in range(1, n - 1):
            here = z[i][j]
            if all(better(here, z[i + di][j + dj])
                   for di in (-1, 0, 1) for dj in (-1, 0, 1) if (di, dj) != (0, 0)):
                sx, sy, sz = surface(xs[i], ys[j])
                found.append({'x': sx, 'y': sy, 'z': sz})
    found.sort(key=lambda s: s['z'], reverse=(kind == 'max'))
    return found


def _surface_normal(surface, p, q, eps=1e-4):
    """Unit normal of `surface` at (p, q), via a central-difference estimate
    of the two tangent directions (d surface/dp, d surface/dq) and their
    cross product -- works identically for a height-field or a fully
    parametric surface, since both share the same surface(p, q) -> (x, y,
    z) shape. Falls back to +Z for a degenerate (zero-area) tangent plane
    rather than dividing by ~0, which a pathological expression (e.g. a
    surface that collapses to a single point at this (p, q)) could
    otherwise produce."""
    x0, y0, z0 = surface(p, q)
    xp, yp, zp = surface(p + eps, q)
    xq, yq, zq = surface(p, q + eps)
    tpx, tpy, tpz = (xp - x0) / eps, (yp - y0) / eps, (zp - z0) / eps
    tqx, tqy, tqz = (xq - x0) / eps, (yq - y0) / eps, (zq - z0) / eps
    nx = tpy * tqz - tpz * tqy
    ny = tpz * tqx - tpx * tqz
    nz = tpx * tqy - tpy * tqx
    norm = math.sqrt(nx * nx + ny * ny + nz * nz)
    if norm < 1e-9:
        return 0.0, 0.0, 1.0
    return nx / norm, ny / norm, nz / norm


def _domain_lattice(coord, pattern, p_range, q_range, n1, n2):
    """Build the (i, j) -> (p, q) domain-lattice dict feeding every custom-
    surface node, for one of the three module patterns:

    'square'/'diagonal' : an ORTHOGONAL (p, q) grid -- p0 + i*dp, q0 + j*dq
                  -- exactly the same node layout either way (only which
                  already-placed nodes later get CONNECTED differs, same
                  as flat_grid's own _add_chords). n1, n2 divisions are
                  used exactly as given.
    'isometric'   : a true 60-degree/equilateral-triangle lattice needs an
                  OBLIQUE basis instead -- a1 = (cell, 0), a2 = (cell *
                  cos60, cell * sin60), both the SAME length `cell`, so
                  every lattice cell is a rhombus that splits into two
                  equilateral triangles (see custom_surface_grid's own
                  connectivity comment for which diagonal does that split).
                  `cell` is derived from the p-range and n1 (n1 divisions
                  across p_range); n2 is then an approximate fill of the
                  q-range with the oblique basis's own q-extent per step,
                  since a fixed equilateral-triangle size generally cannot
                  land exactly on an arbitrary domain extent -- the same
                  kind of inherent mismatch as tiling a rectangle exactly
                  with equilateral triangles at an arbitrary corner count.
                  NEVER wraps, even over a Polar full 2*pi sweep: the
                  oblique basis shifts p (radius, in Polar terms) by a
                  fixed amount on every step in j, so the lattice actually
                  SPIRALS outward rather than closing into concentric
                  rings -- closing that seam back to j=0 would connect two
                  physically distant points with one long, wrong member.
                  A full-turn isometric Polar domain is therefore an open
                  spiral fan, not a closed disk, unlike 'square'/
                  'diagonal' over the same domain.

    Returns (grid_pq, n1_eff, n2_eff, wrap_j): `wrap_j` is True exactly
    when this is a 'square' or 'diagonal' pattern over a POLAR domain
    whose angular sweep is a full 2*pi turn -- the seam closes (j =
    n2_eff aliases j = 0, no duplicate node created for it), the same
    convention dome()/circular_flat_grid() already use for a full-circle
    sweep of sectors. Always False for 'isometric' (see above).
    """
    p0, p1 = p_range
    q0, q1 = q_range
    n1 = max(1, int(n1))
    full_turn = coord == 'polar' and abs((q1 - q0) - 2.0 * math.pi) < 1e-6

    if pattern == 'isometric':
        cell = (p1 - p0) / n1
        a2p = cell * math.cos(math.radians(60.0))
        a2q = cell * math.sin(math.radians(60.0))
        n2_eff = max(1, round((q1 - q0) / a2q)) if a2q > 1e-12 else max(1, int(n2))
        grid_pq = {}
        for j in range(n2_eff + 1):
            for i in range(n1 + 1):
                grid_pq[(i, j)] = (p0 + i * cell + j * a2p, q0 + j * a2q)
        return grid_pq, n1, n2_eff, False

    if pattern not in ('square', 'diagonal'):
        raise ValueError(f"pattern must be 'square', 'diagonal' or 'isometric', got {pattern!r}")
    n2 = max(1, int(n2))
    dp = (p1 - p0) / n1
    dq = (q1 - q0) / n2
    grid_pq = {}
    j_count = n2 if full_turn else n2 + 1
    for j in range(j_count):
        for i in range(n1 + 1):
            grid_pq[(i, j)] = (p0 + i * dp, q0 + j * dq)
    return grid_pq, n1, n2, full_turn


def _surface_chords(members, seen, grid, imax, jmax, pattern, wrap_j, role):
    """Chord/rib members across a custom-surface (i, j) lattice -- the same
    'square' (grid-line) / 'diagonal' (both diagonals of every cell, no
    grid-line chord at all -- see _add_chords) meaning as flat_grid's own
    _add_chords, generalized with an optional wraparound in j (a full-turn
    Polar domain's closed seam, j=jmax aliasing j=0) plus a third pattern,
    'isometric', that _add_chords has no notion of:

    'isometric' : the lattice itself is already laid out on the 60-degree
                  oblique basis (see _domain_lattice); each cell is a
                  rhombus with all four sides equal to the lattice's own
                  cell length, and its diagonal from (i+1, j) to (i, j+1)
                  is ALSO exactly that same length (a short calculation:
                  with a1=(c,0) and a2=(c*cos60, c*sin60), |a2-a1| = c) --
                  so ribs along i, ribs along j, plus that one diagonal
                  split every rhombus into two genuinely EQUILATERAL
                  triangles. The other diagonal, (i, j)-(i+1, j+1), is
                  the long one (|a1+a2| = c*sqrt(3)) and is never added.
    """
    def j_next(j):
        return (j + 1) % jmax if wrap_j else j + 1

    if pattern == 'isometric':
        # ribs along i
        for j in range(jmax if wrap_j else jmax + 1):
            for i in range(imax):
                _add_member(members, seen, grid[(i, j)], grid[(i + 1, j)], role=role)
        # ribs along j
        for j in range(jmax if wrap_j else jmax):
            jn = j_next(j)
            for i in range(imax + 1):
                _add_member(members, seen, grid[(i, j)], grid[(i, jn)], role=role)
        # the one diagonal that splits each rhombus into two equilateral
        # triangles -- see the docstring above for why this one and not
        # the other
        for j in range(jmax if wrap_j else jmax):
            jn = j_next(j)
            for i in range(imax):
                _add_member(members, seen, grid[(i + 1, j)], grid[(i, jn)], role=role)
        return

    if pattern == 'square':
        for j in range(jmax if wrap_j else jmax + 1):
            for i in range(imax):
                _add_member(members, seen, grid[(i, j)], grid[(i + 1, j)], role=role)
        for j in range(jmax if wrap_j else jmax):
            jn = j_next(j)
            for i in range(imax + 1):
                _add_member(members, seen, grid[(i, j)], grid[(i, jn)], role=role)
    elif pattern == 'diagonal':
        for j in range(jmax if wrap_j else jmax):
            jn = j_next(j)
            for i in range(imax):
                _add_member(members, seen, grid[(i, j)], grid[(i + 1, jn)], role=role)
                _add_member(members, seen, grid[(i + 1, j)], grid[(i, jn)], role=role)
    else:
        raise ValueError(f"pattern must be 'square', 'diagonal' or 'isometric', got {pattern!r}")


def _surface_webs(members, seen, top, bottom, imax, jmax, wrap_j):
    """Through-thickness bracing between a custom surface's two ALIGNED
    layers (top[(i,j)] directly normal-offset from bottom[(i,j)], not
    plan-offset the way flat_grid's own pyramidal webs are): a same-index
    web PLUS a diagonal web to a neighbouring cell's node, exactly
    _extruded_arch_grid's own 'web'/'web_diag' scheme (see its comments) --
    needed for the identical reason: a same-index web alone has no
    resistance to the two layers racking sideways relative to each other,
    since every such web is parallel to every other one."""
    def j_next(j):
        return (j + 1) % jmax if wrap_j else j + 1

    for ij, node in top.items():
        if ij in bottom:
            _add_member(members, seen, node, bottom[ij], role='web')
    for j in range(jmax if wrap_j else jmax):
        jn = j_next(j)
        for i in range(imax):
            _add_member(members, seen, top[(i, j)], bottom[(i + 1, jn)], role='web_diag')
            _add_member(members, seen, top[(i + 1, j)], bottom[(i, jn)], role='web_diag')


def _boundary_nodes(grid, imax, jmax, wrap_j):
    """The domain's plan/perimeter edge of one (i, j) node layer -- i=0,
    i=imax always (the two edges Polar's wraparound never closes), plus
    j=0, j=jmax when NOT wrapped (a wrapped Polar sweep has no j-edge at
    all: it is a closed ring). Mirrors flat_grid's own perimeter default
    for `support_candidates`."""
    out = set()
    for (i, j), node in grid.items():
        if i in (0, imax) or (not wrap_j and j in (0, jmax)):
            out.add(node)
    return sorted(out)


# How dense a net to test a two-surface pair on, relative to the lattice the
# mesh itself will use. A crossing that dips between two nodes still puts the
# top layer's chords under the bottom layer's in that strip, so testing only
# at the nodes would pass a truss that is locally inside out.
CROSS_CHECK_REFINE = 3
CROSS_CHECK_MIN = 24
CROSS_CHECK_MAX = 90


def _separation(surface_top, surface_bottom, x, y):
    tx, ty, tz = surface_top(x, y)
    bx, by, bz = surface_bottom(x, y)
    return (tx - bx, ty - by, tz - bz)


def surfaces_cross(surface_top, surface_bottom, coord='cartesian',
                   p_range=(0.0, 1.0), q_range=(0.0, 1.0), n1=8, n2=8,
                   pole=(0.0, 0.0)):
    """Where, if anywhere, two surfaces touch or swap over inside a domain.

    A double-layer grid is only a truss while its two layers stay on their
    own sides of each other. Where they meet, the web joining them has zero
    length -- a member with no direction, which is not a structure. Past
    where they cross, every web is inverted: the surface called "top" is
    underneath, the chords of one layer pass through the other, and the
    model that comes out is inside out rather than wrong by a little.

    That is easy to do by accident, because a domain is usually a RECTANGLE
    and the surfaces are usually radial. Two paraboloids that stay a
    comfortable 2 m apart out to r = 6 have already crossed at the corners
    of the square -12 <= x, y <= 12, which are 8.49 m from the centre.

    The test is local and needs no idea of which way is up, so it works for
    a parametric pair as well as two height fields: sample the separation
    vector (top - bottom) across the domain, and the surfaces have crossed
    between two neighbouring samples exactly when those two vectors point
    in opposite directions. A separation of zero is the crossing itself.

    Sampled on a net `CROSS_CHECK_REFINE` times finer than the mesh lattice,
    so a crossing that dips between two nodes is still caught; a crossing
    narrower than that net can still slip through, which is why this returns
    a report rather than claiming a proof.

    Returns None when the two surfaces stay apart, otherwise
    {'x', 'y', 'p', 'q', 'gap', 'count'} for the closest approach found --
    `gap` is the distance between the layers there (0.0 at a true crossing)
    and `count` how many sampled points were flagged.
    """
    n_p = max(CROSS_CHECK_MIN, min(CROSS_CHECK_MAX, int(n1) * CROSS_CHECK_REFINE))
    n_q = max(CROSS_CHECK_MIN, min(CROSS_CHECK_MAX, int(n2) * CROSS_CHECK_REFINE))
    p0, p1 = p_range
    q0, q1 = q_range
    full_turn = coord == 'polar' and abs((q1 - q0) - 2.0 * math.pi) < 1e-6

    pts, sep = {}, {}
    for i in range(n_p + 1):
        p = p0 + (p1 - p0) * i / n_p
        for j in range(n_q + 1):
            q = q0 + (q1 - q0) * j / n_q
            x, y = _domain_to_xy(coord, p, q, pole)
            pts[(i, j)] = (x, y, p, q)
            sep[(i, j)] = _separation(surface_top, surface_bottom, x, y)

    def dot(u, v):
        return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]

    flagged = []
    for ij, v in sep.items():
        i, j = ij
        here = math.sqrt(dot(v, v))
        if here <= 1e-9:                      # the layers meet exactly here
            flagged.append((0.0, ij))
            continue
        neighbours = [(i + 1, j), (i, j + 1)]
        if full_turn and j == n_q - 1:
            neighbours.append((i, 0))
        for nb in neighbours:
            w = sep.get(nb)
            if w is None:
                continue
            if dot(v, w) < 0.0:               # the separation reversed
                there = math.sqrt(dot(w, w))
                flagged.append((min(here, there), ij if here <= there else nb))
                break

    if not flagged:
        return None
    flagged.sort(key=lambda f: f[0])
    gap, ij = flagged[0]
    x, y, p, q = pts[ij]
    return {'x': x, 'y': y, 'p': p, 'q': q, 'gap': gap, 'count': len(flagged)}


def _crossing_message(where, coord):
    """The error a crossed pair raises -- it has to say WHERE, because the
    fix is either a smaller domain or a different expression and the user
    cannot choose between them without knowing which part of the domain is
    the problem."""
    place = (f"(x, y) = ({where['x']:.3f}, {where['y']:.3f})" if coord == 'cartesian'
             else f"r = {where['p']:.3f}, theta = {where['q']:.3f} rad "
                  f"-- (x, y) = ({where['x']:.3f}, {where['y']:.3f})")
    return (f'The two surfaces meet or cross inside this domain, at {place} '
            f'(the layers are {where["gap"]:.3f} m apart there, and '
            f'{where["count"]} sampled points are affected). '
            'Where they meet, the web between them has zero length; past it '
            'the truss is inside out. Shrink the domain so it stays inside '
            'the region where they are apart, or change one expression so '
            'that surface stays clear of the other everywhere in it.')


def custom_surface_grid(surface, coord='cartesian', pattern='square',
                        p_range=(0.0, 1.0), q_range=(0.0, 1.0), n1=8, n2=8,
                        module='2d', depth=0.0, offset_side='top',
                        pole=(0.0, 0.0)):
    """Sample an arbitrary `surface(p, q) -> (x, y, z)` (from
    make_height_field_surface or make_parametric_surface) into a mesh, via
    the domain/module wizard: `coord` picks the (p, q) domain's shape
    (Cartesian rectangle, or Polar disk/sector with p read as radius and q
    as angle), `pattern` picks how the sampled points connect (square,
    diagonal, or a true 60-degree isometric lattice), and `module` picks a
    single layer lying ON the surface ('2d') or a double layer ('3d') --
    the surface itself PLUS a second layer offset by `depth` along the
    surface's own local normal, `offset_side` choosing whether the defined
    surface becomes the 'top' layer (the auto-built second layer sits
    `depth` BELOW it, along -normal) or the 'bottom' layer (the second
    layer sits `depth` ABOVE it, along +normal).

    p_range, q_range : the sampled domain's extent in (p, q) -- for a
                  Polar coord, p_range is (r_min, r_max) and q_range is
                  (theta_min, theta_max) in radians (theta_max - theta_min
                  == 2*pi exactly closes the seam into a full disk/annulus
                  rather than an open sector).
    n1, n2       : division counts along p and q (isometric derives its
                  own n2 -- see _domain_lattice).
    pole         : where a POLAR domain's centre sits in the surface's own
                  parameter plane; ignored for a Cartesian one. Put it on
                  the summit the grid is meant to be about -- see
                  surface_summits, and _domain_to_xy for what goes wrong
                  when it sits anywhere else.

    A 2D module's 'square' and 'diagonal' patterns provide NO diagonal-
    plane bracing of their own (each is topologically just an orthogonal
    grid, 'diagonal' merely rotated 45 degrees onto the SAME nodes -- see
    _surface_chords) -- unlike a 3D module, where the web/web_diag layer
    connecting top and bottom does the actual triangulating regardless of
    which chord pattern is chosen, the same way flat_grid's own `pattern`
    is really just which way the primary chords run, not what keeps the
    grid from racking. Whether a PIN-jointed 2D 'square'/'diagonal' module
    actually analyzes therefore depends on the specific surface: a curved
    surface can end up incidentally stable (member directions varying in
    3D can pick up enough out-of-plane component to resist what would be
    a pure zero-energy racking mode on a flat grid), but this is NOT
    guaranteed -- verify with Analyze rather than assuming. 'isometric' is
    the only 2D pattern that is always fully triangulated on its own
    regardless of surface shape; the alternative for 'square'/'diagonal'
    is to give the mesh 'rigid' (moment-transferring) connectivity instead
    of the default 'pin', the same fix a Vierendeel-style single layer
    always needs.

    Returns the shared {'nodes','members','support_candidates','load_nodes'}
    dict; `support_candidates` is the domain's plan perimeter (both layers,
    for a 3D module) and `load_nodes` is a plain per-node domain-cell area
    (p*q units, NOT the true curved surface area -- the same kind of
    lumped-area approximation dome()'s own tributary areas document for a
    non-developable surface) on the layer facing the load direction.
    """
    if module not in ('2d', '3d'):
        raise ValueError(f"module must be '2d' or '3d', got {module!r}")
    if offset_side not in ('top', 'bottom'):
        raise ValueError(f"offset_side must be 'top' or 'bottom', got {offset_side!r}")
    if pattern == PATTERN_ISOMETRIC:
        # One isometric implementation, not two. _domain_lattice lays the
        # triangular module out in an OBLIQUE basis, which shears the whole
        # lattice across the Cartesian rectangle it was asked for: on a
        # 12 m domain it ran 6.75 m past the far edge (a 106% overshoot)
        # and left a third of the nodes outside. isometric_lattice staggers
        # the rows inside the rectangle and clamps the ends onto the edge
        # instead. That fix reached the Shape panel (which goes through
        # custom_surface_lattice) but NOT this function or
        # custom_surface_between, so the Custom Surface Wizard -- which
        # calls these two directly -- still built the sheared version.
        return isometric_lattice(surface, None, coord=coord, p_range=p_range,
                                 q_range=q_range, n1=n1, depth=depth,
                                 pole=pole, double=(module == '3d'))

    grid_pq, imax, jmax, wrap_j = _domain_lattice(coord, pattern, p_range, q_range, n1, n2)
    bank = _NodeBank()
    members = []
    seen = set()

    def place(p, q, along_normal=0.0):
        x, y = _domain_to_xy(coord, p, q, pole)
        sx, sy, sz = surface(x, y)
        if along_normal:
            nx, ny, nz = _surface_normal(surface, x, y)
            sx, sy, sz = sx + nx * along_normal, sy + ny * along_normal, sz + nz * along_normal
        return bank.add(sx, sy, sz)

    if module == '2d':
        outer = {ij: place(p, q) for ij, (p, q) in grid_pq.items()}
        _surface_chords(members, seen, outer, imax, jmax, pattern, wrap_j, role='surface_chord')
        support_candidates = _boundary_nodes(outer, imax, jmax, wrap_j)
        load_nodes = _domain_cell_areas(grid_pq, coord, imax, jmax, wrap_j, outer)
        return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
                'load_nodes': load_nodes}

    # No crossing check here, and deliberately not: the offset layer is
    # PARALLEL to the defined one by construction, so the two can never
    # swap over the way two independently-typed surfaces can (which is what
    # surfaces_cross tests, and what custom_surface_between raises on).
    # What an offset CAN do is fold through itself, when `depth` exceeds the
    # surface's own radius of curvature -- a different failure, and not one
    # this module tests for.
    if offset_side == 'top':
        top = {ij: place(p, q) for ij, (p, q) in grid_pq.items()}
        bottom = {ij: place(p, q, along_normal=-depth) for ij, (p, q) in grid_pq.items()}
    else:
        bottom = {ij: place(p, q) for ij, (p, q) in grid_pq.items()}
        top = {ij: place(p, q, along_normal=depth) for ij, (p, q) in grid_pq.items()}

    _surface_chords(members, seen, top, imax, jmax, pattern, wrap_j, role='outer_rib')
    _surface_chords(members, seen, bottom, imax, jmax, pattern, wrap_j, role='inner_rib')
    _surface_webs(members, seen, top, bottom, imax, jmax, wrap_j)
    support_candidates = sorted(set(_boundary_nodes(top, imax, jmax, wrap_j))
                                | set(_boundary_nodes(bottom, imax, jmax, wrap_j)))
    load_nodes = _domain_cell_areas(grid_pq, coord, imax, jmax, wrap_j, top)
    return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
            'load_nodes': load_nodes}


def custom_surface_between(surface_top, surface_bottom, coord='cartesian', pattern='square',
                           p_range=(0.0, 1.0), q_range=(0.0, 1.0), n1=8, n2=8,
                           pole=(0.0, 0.0)):
    """Connect two INDEPENDENTLY-shaped surfaces with a double-layer grid,
    one designated `surface_top` and the other `surface_bottom` -- the
    general two-surface form of custom_surface_grid's own '3d' module,
    which instead auto-derives its second layer as a fixed offset of the
    first. Both surfaces are sampled over the exact SAME (coord, pattern,
    p_range, q_range, n1, n2) domain lattice, which is what makes their
    node grids correspond 1:1 (top[(i,j)] faces bottom[(i,j)]) -- the
    caller (the wizard UI) is responsible for actually enforcing that the
    two surfaces share domain settings; this function has no way to
    detect two surfaces that were meant to differ and does not try to.

    The two surfaces must stay on their own sides of each other everywhere
    in the domain, and this raises ValueError naming the place if they do
    not -- see surfaces_cross for why a crossed pair is not a truss at all
    and for the limits of the test.

    Returns the shared {'nodes','members','support_candidates','load_nodes'}
    dict, exactly like custom_surface_grid's own '3d' module.
    """
    if pattern == PATTERN_ISOMETRIC:
        # Same delegation, same reason, as custom_surface_grid above: the
        # oblique-basis isometric shears out of the domain, and the wizard
        # reaches this function directly.
        return isometric_lattice(surface_top, surface_bottom, coord=coord,
                                 p_range=p_range, q_range=q_range, n1=n1,
                                 pole=pole, double=True)
    where = surfaces_cross(surface_top, surface_bottom, coord=coord,
                           p_range=p_range, q_range=q_range, n1=n1, n2=n2,
                           pole=pole)
    if where is not None:
        raise ValueError(_crossing_message(where, coord))

    grid_pq, imax, jmax, wrap_j = _domain_lattice(coord, pattern, p_range, q_range, n1, n2)
    bank = _NodeBank()
    members = []
    seen = set()

    top, bottom = {}, {}
    for ij, (p, q) in grid_pq.items():
        x, y = _domain_to_xy(coord, p, q, pole)
        top[ij] = bank.add(*surface_top(x, y))
        bottom[ij] = bank.add(*surface_bottom(x, y))

    _surface_chords(members, seen, top, imax, jmax, pattern, wrap_j, role='outer_rib')
    _surface_chords(members, seen, bottom, imax, jmax, pattern, wrap_j, role='inner_rib')
    _surface_webs(members, seen, top, bottom, imax, jmax, wrap_j)
    support_candidates = sorted(set(_boundary_nodes(top, imax, jmax, wrap_j))
                                | set(_boundary_nodes(bottom, imax, jmax, wrap_j)))
    load_nodes = _domain_cell_areas(grid_pq, coord, imax, jmax, wrap_j, top)
    return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
            'load_nodes': load_nodes}


def _domain_cell_areas(grid_pq, coord, imax, jmax, wrap_j, layer):
    """A plain per-node domain-cell area (the (p, q)-plane cell each node
    sits at the centre of, split at the domain boundary the usual half/
    quarter-cell way), attributed to `layer`'s own node at each (i, j) --
    NOT the true curved surface area (the same kind of lumped-area
    approximation dome()'s own tributary areas document for a surface with
    no simple closed-form area element)."""
    load_nodes = {}
    j_range = range(jmax) if wrap_j else range(jmax + 1)
    for j in j_range:
        for i in range(imax + 1):
            if (i, j) not in layer:
                continue
            p0, q0 = grid_pq[(i, j)]
            dp_lo = (p0 - grid_pq[(i - 1, j)][0]) if i > 0 else 0.0
            dp_hi = (grid_pq[(i + 1, j)][0] - p0) if i < imax else 0.0
            fp = ((dp_lo + dp_hi) / 2.0) if (dp_lo and dp_hi) else (dp_lo or dp_hi)
            j_prev = (j - 1) % jmax if wrap_j else j - 1
            j_nxt = (j + 1) % jmax if wrap_j else j + 1
            dq_lo = (q0 - grid_pq[(i, j_prev)][1]) if (j > 0 or wrap_j) else 0.0
            dq_hi = (grid_pq[(i, j_nxt)][1] - q0) if (j < jmax or wrap_j) else 0.0
            if wrap_j:
                dq_lo = abs(dq_lo) if dq_lo else 0.0
                dq_hi = abs(dq_hi) if dq_hi else 0.0
            fq = ((dq_lo + dq_hi) / 2.0) if (dq_lo and dq_hi) else (dq_lo or dq_hi)
            area = fp * fq
            if coord == 'polar':
                area *= p0 if p0 > 0 else 0.0
            load_nodes[layer[(i, j)]] = area
    return load_nodes


# ═══════════════════════════════════════════════════════════════════════════
#  Lattice types -- how the two layers relate to each other
# ═══════════════════════════════════════════════════════════════════════════
# This is a different question from SHAPE (which surface) and from PATTERN
# (how one layer's own nodes connect). It asks how the top layer and the
# bottom layer are registered against each other, and it is the question
# that actually names a space frame in practice.
#
# The first version of this tab had exactly these four and called them its
# grid families, which was right: on a two-surface grid they matter more
# than the surfaces do. A square-on-square offset and a diagonal-on-diagonal
# over the SAME pair of surfaces are different structures -- different rod
# counts, different rod lengths, different load paths, different buildability.
#
#   SINGLE          one layer lying on the surface. A 2-way grillage.
#                   Note that a FLAT one is a mechanism when pin-jointed --
#                   a plane grid of pinned bars has no out-of-plane
#                   stiffness at all -- so it wants either curvature (which
#                   gives it shell action) or rigid joints. That is physics,
#                   not a defect, and the app reports it rather than quietly
#                   bracing it.
#   SOS_OFFSET      top orthogonal; bottom orthogonal, offset half a module
#                   in both directions so each bottom node sits under the
#                   CENTRE of a top square and ties to its four corners.
#                   The classic space frame, and the one most systems build.
#   SQ_ON_DIAG      the same offset bottom layer, but its chords run
#                   diagonally. Fewer, longer bottom chords; the top layer
#                   stays square, which is what a deck or glazing wants.
#   DIAG_ON_DIAG    both layers diagonal. The lightest of the three for a
#                   given depth and the hardest to detail, because nothing
#                   is orthogonal to anything.
LATTICE_SINGLE = 'Single layer (2-way grillage)'
LATTICE_SOS_OFFSET = 'Square on square, offset'
LATTICE_SQ_ON_DIAG = 'Square on diagonal'
LATTICE_DIAG_ON_DIAG = 'Diagonal on diagonal'
LATTICE_ALIGNED = 'Double layer, aligned'

# The MODULE shape, which is a separate question from how the two LAYERS
# register (that is what LATTICE_TYPES answers). Defined here, beside the
# lattice names, because custom_surface_lattice takes one as a DEFAULT
# argument and a default is evaluated at import time.
PATTERN_SQUARE = 'square'
PATTERN_DIAGONAL = 'diagonal'
PATTERN_ISOMETRIC = 'isometric'
LATTICE_PATTERNS = (PATTERN_SQUARE, PATTERN_DIAGONAL, PATTERN_ISOMETRIC)

_SIN60 = math.sin(math.radians(60.0))
LATTICE_TYPES = (LATTICE_SOS_OFFSET, LATTICE_SQ_ON_DIAG,
                 LATTICE_DIAG_ON_DIAG, LATTICE_ALIGNED, LATTICE_SINGLE)

# (top layer diagonal?, bottom layer diagonal?) per type; SINGLE has no
# bottom layer at all and is handled before this table is consulted.
_LATTICE_DIAGONALS = {
    LATTICE_SOS_OFFSET: (False, False),
    LATTICE_SQ_ON_DIAG: (False, True),
    LATTICE_DIAG_ON_DIAG: (True, True),
}


def _orthogonal_chords(members, seen, grid, imax, jmax, role):
    for (i, j), n in grid.items():
        for nb in ((i + 1, j), (i, j + 1)):
            if nb in grid:
                _add_member(members, seen, n, grid[nb], role=role)


def _diagonal_chords(members, seen, grid, imax, jmax, role):
    """Both diagonals of every cell, plus the perimeter closed orthogonally.

    Without the perimeter the free edges are a mechanism: a corner node of a
    purely diagonal lattice is held by one bar in one direction only.
    """
    for i in range(imax):
        for j in range(jmax):
            if all(k in grid for k in ((i, j), (i + 1, j), (i, j + 1), (i + 1, j + 1))):
                _add_member(members, seen, grid[(i, j)], grid[(i + 1, j + 1)], role=role)
                _add_member(members, seen, grid[(i + 1, j)], grid[(i, j + 1)], role=role)
    for i in range(imax):
        for j in (0, jmax):
            if (i, j) in grid and (i + 1, j) in grid:
                _add_member(members, seen, grid[(i, j)], grid[(i + 1, j)], role=role)
    for j in range(jmax):
        for i in (0, imax):
            if (i, j) in grid and (i, j + 1) in grid:
                _add_member(members, seen, grid[(i, j)], grid[(i, j + 1)], role=role)


def custom_surface_lattice(surface_top, surface_bottom=None, coord='cartesian',
                           lattice=LATTICE_SOS_OFFSET, p_range=(0.0, 1.0),
                           q_range=(0.0, 1.0), n1=8, n2=8, depth=1.0,
                           pole=(0.0, 0.0), pattern=PATTERN_SQUARE):
    """A double-layer grid whose bottom layer is OFFSET half a module.

    custom_surface_grid and custom_surface_between both sample their two
    layers at the same (i, j), so every web is a vertical post and the two
    layers are the same lattice twice. That is one real space frame among
    several, and not the common one: in the classic offset frame each bottom
    node sits under the centre of a top square and ties to its four corners,
    which is what turns two flat grids into something with depth-action.

    `surface_bottom` may be another surface callable, or None to derive the
    bottom layer by dropping `depth` along the top surface's own normal.

    Returns the usual {'nodes', 'members', 'support_candidates',
    'load_nodes'} dict.
    """
    if lattice not in LATTICE_TYPES:
        raise ValueError(f'unknown lattice type {lattice!r}')
    if pattern not in LATTICE_PATTERNS:
        raise ValueError(f'unknown module pattern {pattern!r}')

    # Lattice and pattern are two independent questions -- how the two
    # LAYERS register, and what shape the MODULE is -- but not every pair
    # of answers describes a real space frame, and the ones that do not are
    # refused here rather than approximated into something that looks
    # buildable and is not.
    if lattice == LATTICE_ALIGNED:
        if pattern == PATTERN_ISOMETRIC:
            return isometric_lattice(surface_top, surface_bottom, coord=coord,
                                     p_range=p_range, q_range=q_range, n1=n1,
                                     depth=depth, pole=pole, double=True)
        # Square/diagonal aligned layers are exactly what custom_surface_grid
        # and custom_surface_between already build, so this delegates rather
        # than growing a fourth copy of the same top/bottom/web scheme.
        if surface_bottom is None:
            return custom_surface_grid(surface_top, coord=coord, pattern=pattern,
                                       p_range=p_range, q_range=q_range, n1=n1, n2=n2,
                                       module='3d', depth=depth, pole=pole)
        return custom_surface_between(surface_top, surface_bottom, coord=coord,
                                      pattern=pattern, p_range=p_range, q_range=q_range,
                                      n1=n1, n2=n2, pole=pole)
    if pattern == PATTERN_ISOMETRIC:
        if lattice != LATTICE_SINGLE:
            raise ValueError(
                f'{lattice!r} cannot be built on an isometric module. An offset '
                'lattice needs a half-module to offset INTO, and a triangular '
                'grid has no such thing -- the centre of a triangle is not a '
                'lattice point of the triangle below it. Use "Single layer" or '
                f'"{LATTICE_ALIGNED}" for an isometric module.')
        return isometric_lattice(surface_top, None, coord=coord, p_range=p_range,
                                 q_range=q_range, n1=n1, depth=depth, pole=pole,
                                 double=False)
    if pattern == PATTERN_DIAGONAL and lattice != LATTICE_SINGLE:
        # The four named double-layer lattices ALREADY encode which layer
        # runs diagonally (that is what their names mean), so a separate
        # 'diagonal' pattern on top of them would be saying it twice and
        # would contradict three of the four.
        raise ValueError(
            f'{lattice!r} already says which layer runs diagonally -- that is '
            'what its name means. The diagonal MODULE pattern applies to a '
            'single layer.')
    n1 = max(1, int(n1))
    n2 = max(1, int(n2))
    p0, p1 = p_range
    q0, q1 = q_range
    dp = (p1 - p0) / n1
    dq = (q1 - q0) / n2

    bank = _NodeBank()
    members = []
    seen = set()

    def place_top(p, q):
        x, y = _domain_to_xy(coord, p, q, pole)
        return bank.add(*surface_top(x, y))

    top = {}
    for i in range(n1 + 1):
        for j in range(n2 + 1):
            top[(i, j)] = place_top(p0 + i * dp, q0 + j * dq)

    if lattice == LATTICE_SINGLE:
        (_diagonal_chords if pattern == PATTERN_DIAGONAL else _orthogonal_chords)(
            members, seen, top, n1, n2, 'surface_chord')
        support_candidates = _boundary_nodes(top, n1, n2, False)
        grid_pq = {ij: (p0 + ij[0] * dp, q0 + ij[1] * dq) for ij in top}
        load_nodes = _domain_cell_areas(grid_pq, coord, n1, n2, False, top)
        return {'nodes': bank.nodes, 'members': members,
                'support_candidates': support_candidates, 'load_nodes': load_nodes}

    if surface_bottom is None:
        def surface_bottom(x, y, d=depth):
            sx, sy, sz = surface_top(x, y)
            nx, ny, nz = _surface_normal(surface_top, x, y)
            return (sx - nx * d, sy - ny * d, sz - nz * d)

    where = surfaces_cross(surface_top, surface_bottom, coord=coord,
                           p_range=p_range, q_range=q_range, n1=n1, n2=n2, pole=pole)
    if where is not None:
        raise ValueError(_crossing_message(where, coord))

    # the offset layer: one node under the CENTRE of every top cell
    bottom = {}
    for i in range(n1):
        for j in range(n2):
            x, y = _domain_to_xy(coord, p0 + (i + 0.5) * dp, q0 + (j + 0.5) * dq, pole)
            bottom[(i, j)] = bank.add(*surface_bottom(x, y))

    top_diag, bot_diag = _LATTICE_DIAGONALS[lattice]
    (_diagonal_chords if top_diag else _orthogonal_chords)(
        members, seen, top, n1, n2, 'outer_rib')
    (_diagonal_chords if bot_diag else _orthogonal_chords)(
        members, seen, bottom, n1 - 1, n2 - 1, 'inner_rib')

    # the webs: every bottom node to the four top corners of its own cell.
    # This is what gives the frame its depth-action and what makes every
    # node part of a closed 3D assembly rather than a flat grid with posts.
    for (i, j), b in bottom.items():
        for corner in ((i, j), (i + 1, j), (i, j + 1), (i + 1, j + 1)):
            _add_member(members, seen, b, top[corner], role='web')

    support_candidates = sorted(set(_boundary_nodes(top, n1, n2, False))
                                | set(_boundary_nodes(bottom, n1 - 1, n2 - 1, False)))
    grid_pq = {ij: (p0 + ij[0] * dp, q0 + ij[1] * dq) for ij in top}
    load_nodes = _domain_cell_areas(grid_pq, coord, n1, n2, False, top)
    return {'nodes': bank.nodes, 'members': members,
            'support_candidates': support_candidates, 'load_nodes': load_nodes}


# ═══════════════════════════════════════════════════════════════════════════
#  Isometric (equilateral-triangle) lattice on a CARTESIAN domain
# ═══════════════════════════════════════════════════════════════════════════


def staggered_rows(p0, p1, q0, q1, n1):
    """The (p, q) point rows of an equilateral-triangle lattice laid out
    INSIDE the rectangle [p0, p1] x [q0, q1] -- never across it.

    _domain_lattice's own 'isometric' does something different and, on a
    Cartesian domain, wrong: it builds the lattice on an OBLIQUE basis, so
    every row is shifted sideways by half a cell MORE than the row below,
    and the whole lattice shears out of the rectangle. On a 12 m domain
    divided six ways it runs 7 m past the right-hand edge and leaves a
    matching triangular hole on the left -- 19 of its 56 nodes land outside
    the domain that was asked for. That is the right construction for a
    lattice that is allowed to be a parallelogram, and the wrong one for a
    plan that has to stay a rectangle.

    The fix is to stagger ROWS rather than shear the basis:

      even rows   p0, p0+c, p0+2c, ... p1            (n1 + 1 points)
      odd rows    p0, p0+c/2, p0+3c/2, ... p1        (n1 + 2 points)

    so the half-cell offset that makes the triangles equilateral happens
    INSIDE the row, and every row still begins exactly on p0 and ends
    exactly on p1. Both side boundaries are straight lines, which is what
    lets a plan-shape rule, a support line or an edge beam follow them.

    The price -- and it is a real one, not a rounding error -- is the pair
    of HALF-WIDTH triangles at each end of every odd row, where the
    boundary node at p0 (or p1) sits only c/2 from its neighbour instead of
    c. Everything away from those two columns is equilateral to within the
    row-height rounding below. The alternative is a zig-zag boundary, and a
    straight edge is worth more than two regular triangles per row.

    Row spacing is c * sin(60), rounded to a whole number of rows so the
    last row lands exactly on q1; that rounding is why the triangles are
    equilateral to a few percent rather than exactly. Returns
    (rows, q_values) where rows[j] is the list of p positions in row j.
    """
    n1 = max(1, int(n1))
    cell = (p1 - p0) / n1
    span_q = q1 - q0
    if abs(cell) < 1e-12:
        raise ValueError('the x range of an isometric domain cannot be zero')
    nrows = max(1, int(round(abs(span_q) / (abs(cell) * _SIN60))))
    q_values = [q0 + span_q * j / nrows for j in range(nrows + 1)]

    rows = []
    for j in range(nrows + 1):
        if j % 2 == 0:
            rows.append([p0 + i * cell for i in range(n1 + 1)])
        else:
            inner = [p0 + (i + 0.5) * cell for i in range(n1)]
            rows.append([p0] + inner + [p1])
    return rows, q_values


def _stagger_links(row_a, row_b):
    """Which (index_in_a, index_in_b) pairs to connect between two adjacent
    staggered rows: every node to the two nodes of the other row nearest it
    in p, taken from BOTH sides so the result is symmetric.

    Chosen by POSITION rather than by index arithmetic. The two rows have
    different lengths (n1+1 against n1+2) and different offsets, so an
    index rule has to special-case both ends of both parities -- four cases
    that are easy to get subtly wrong and produce a crossed member or a
    missing triangle. Nearest-in-p is one rule, is obviously right, and the
    triangulation test checks the result rather than the reasoning.
    """
    links = set()
    for ia, pa in enumerate(row_a):
        order = sorted(range(len(row_b)), key=lambda ib: abs(row_b[ib] - pa))
        for ib in order[:2]:
            links.add((ia, ib))
    for ib, pb in enumerate(row_b):
        order = sorted(range(len(row_a)), key=lambda ia: abs(row_a[ia] - pb))
        for ia in order[:2]:
            links.add((ia, ib))
    return sorted(links)


def isometric_lattice(surface_top, surface_bottom=None, coord='cartesian',
                      p_range=(0.0, 1.0), q_range=(0.0, 1.0), n1=8,
                      depth=1.0, pole=(0.0, 0.0), double=False):
    """An equilateral-triangle lattice on `surface_top`, laid out inside the
    Cartesian rectangle rather than sheared across it (see staggered_rows).

    `double=False` gives a single layer. Because the lattice is already
    fully triangulated in its own surface, that single layer is stable on
    a curved surface without any web system -- which is the practical
    reason to reach for isometric in the first place, and what the square
    and diagonal patterns cannot promise (see custom_surface_grid's own
    note on why a 2D square module is not self-bracing).

    `double=True` adds a second layer on `surface_bottom` (or `depth` below
    the top surface along its own normal), sampled at the SAME (p, q), plus
    a post at every node and one diagonal per chord. Aligned, not offset:
    an offset lattice needs a half-module to offset INTO, and a triangular
    grid has no such thing -- the centre of a triangle is not a lattice
    point of the triangle below it. That is why the offset/square-on-
    diagonal/diagonal-on-diagonal lattices are refused for this pattern
    rather than silently approximated.

    Returns the usual {'nodes', 'members', 'support_candidates',
    'load_nodes'} dict.
    """
    p0, p1 = p_range
    q0, q1 = q_range
    rows, q_values = staggered_rows(p0, p1, q0, q1, n1)

    bank = _NodeBank()
    members = []
    seen = set()

    if double and surface_bottom is None:
        def surface_bottom(x, y, d=depth):
            sx, sy, sz = surface_top(x, y)
            nx, ny, nz = _surface_normal(surface_top, x, y)
            return (sx - nx * d, sy - ny * d, sz - nz * d)

    top, bottom = {}, {}
    for j, row in enumerate(rows):
        for i, p in enumerate(row):
            x, y = _domain_to_xy(coord, p, q_values[j], pole)
            top[(i, j)] = bank.add(*surface_top(x, y))
            if double:
                bottom[(i, j)] = bank.add(*surface_bottom(x, y))

    def chords(layer, role):
        edges = []
        for j, row in enumerate(rows):
            for i in range(len(row) - 1):
                edges.append(((i, j), (i + 1, j)))
            if j + 1 < len(rows):
                for ia, ib in _stagger_links(row, rows[j + 1]):
                    edges.append(((ia, j), (ib, j + 1)))
        for u, v in edges:
            _add_member(members, seen, layer[u], layer[v], role=role)
        return edges

    edges = chords(top, 'outer_rib' if double else 'surface_chord')
    if double:
        chords(bottom, 'inner_rib')
        for ij, node in top.items():
            _add_member(members, seen, node, bottom[ij], role='web')
        # One diagonal per chord turns each vertical quad into two
        # triangles. Posts alone leave the two layers free to rack
        # sideways relative to each other -- every post is parallel to
        # every other, exactly the failure _surface_webs documents.
        for u, v in edges:
            _add_member(members, seen, top[u], bottom[v], role='web_diag')

    boundary = set()
    last = len(rows) - 1
    for j, row in enumerate(rows):
        for i in range(len(row)):
            if j in (0, last) or i in (0, len(row) - 1):
                boundary.add(top[(i, j)])
                if double:
                    boundary.add(bottom[(i, j)])

    # Tributary area: half the p-gap either side, times half the row height
    # either side. Ragged rows make a closed form awkward and this is the
    # thing a closed form would have to reproduce anyway -- it sums to the
    # domain rectangle exactly, which the test checks.
    load_nodes = {}
    for j, row in enumerate(rows):
        dq_up = (q_values[j + 1] - q_values[j]) / 2.0 if j < last else 0.0
        dq_dn = (q_values[j] - q_values[j - 1]) / 2.0 if j > 0 else 0.0
        height = abs(dq_up) + abs(dq_dn)
        for i, p in enumerate(row):
            left = (p - row[i - 1]) / 2.0 if i > 0 else 0.0
            right = (row[i + 1] - p) / 2.0 if i < len(row) - 1 else 0.0
            load_nodes[top[(i, j)]] = abs(left + right) * height
    return {'nodes': bank.nodes, 'members': members,
            'support_candidates': sorted(boundary), 'load_nodes': load_nodes}
