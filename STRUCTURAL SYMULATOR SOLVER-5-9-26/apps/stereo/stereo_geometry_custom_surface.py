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


def _domain_to_xy(coord, p, q):
    """Resolve one domain-lattice (p, q) pair to the flat 2-vector actually
    fed into the surface function. Cartesian: identity (p, q ARE the
    surface's own x, y or u, v). Polar: p is read as a RADIUS and q as an
    ANGLE (radians), converted the usual way -- so a Polar domain samples
    the same surface function over a disk/sector/annulus instead of a
    rectangle."""
    if coord == 'cartesian':
        return p, q
    if coord == 'polar':
        return p * math.cos(q), p * math.sin(q)
    raise ValueError(f"coord must be 'cartesian' or 'polar', got {coord!r}")


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


def custom_surface_grid(surface, coord='cartesian', pattern='square',
                        p_range=(0.0, 1.0), q_range=(0.0, 1.0), n1=8, n2=8,
                        module='2d', depth=0.0, offset_side='top'):
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

    grid_pq, imax, jmax, wrap_j = _domain_lattice(coord, pattern, p_range, q_range, n1, n2)
    bank = _NodeBank()
    members = []
    seen = set()

    def place(p, q, along_normal=0.0):
        x, y = _domain_to_xy(coord, p, q)
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
                           p_range=(0.0, 1.0), q_range=(0.0, 1.0), n1=8, n2=8):
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

    Returns the shared {'nodes','members','support_candidates','load_nodes'}
    dict, exactly like custom_surface_grid's own '3d' module.
    """
    grid_pq, imax, jmax, wrap_j = _domain_lattice(coord, pattern, p_range, q_range, n1, n2)
    bank = _NodeBank()
    members = []
    seen = set()

    top, bottom = {}, {}
    for ij, (p, q) in grid_pq.items():
        x, y = _domain_to_xy(coord, p, q)
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
