"""Geometry generators for the Stereo (3D space-structure) tab.

"Estructura estéreo" covers real-world families of bolted/welded space
structures that are otherwise built as separate, incompatible programs.
The point of this module is to generate all of them through ONE shared
node/member representation so the Stereo tab can offer a single generator
panel that simply changes which function is called, rather than one app
per typology. Three families of surface are covered, each built on a
shared internal engine so a new typology is usually just a different
height/radius/arch PROFILE fed into already-validated bracing:

  - Rectangular double-layer grids, all sharing flat_grid's own pyramidal-
    web bracing: flat_grid (flat), hip_roof_grid (pyramidal roof),
    hypar_shell (hyperbolic-paraboloid saddle).
  - Extruded-arch vaults, all sharing barrel_vault's own station/rib/
    purlin/edge-brace bracing: barrel_vault (circular arch),
    parabolic_vault, elliptic_vault.
  - Axisymmetric ribbed shells, all sharing dome's own apex+rings+
    Schwedler-diagonal bracing: dome (spherical cap), paraboloid_dish
    (antenna/reflector), elliptic_dome (ellipsoid cap), sphere_shell (a
    full sphere, two poles).
  - circular_flat_grid (a round-plan flat double-layer grid) stands alone,
    with its own polar pyramidal-web bracing.

Every one of the non-trivial typologies above was actually run through
stereo_math.analyze() under self-weight across a range of mesh densities
before being accepted, the same discipline barrel_vault's own springing-
line fix and flat_grid's own aligned-web fix were found under: a mesh can
look structurally sane (no zero-length or duplicate members) while still
being a mechanism, so "does it actually analyze" is checked, not assumed,
for every new shape and every new bracing scheme -- see
tests/test_stereo_geometry.py.

Every generator returns a plain dict:

    {'nodes': [(x, y, z), ...],        # metres, world coordinates
     'members': [{'a': i, 'b': j, 'conn': 'pin', 'role': '...'}, ...],
     'support_candidates': [node_idx, ...],   # a sensible default support
                                               # set -- NOT a restriction.
     'load_nodes': {node_idx: tributary_area_m2, ...}}  # the roof/shell
                                               # surface, for an area load.

`support_candidates` is only a suggestion the UI pre-selects with a 'pin'
preset; the whole point of the boundary-condition system in stereo_math.py
is that ANY node, not just these, can be given ANY combination of
restrained translations/rotations. Nothing here or in stereo_math.py ever
restricts which nodes may carry a support.

`load_nodes` is the exact (flat_grid, barrel_vault) or closed-form
midpoint-rule (dome -- see its own docstring) lumped tributary plan/shell
area belonging to each node of the load-bearing surface, in m². Multiplying
by a pressure q (kN/m²) gives that node's share of a uniform area load
directly -- see stereo_math.area_load_to_nodal_loads. For flat_grid and
barrel_vault the areas sum EXACTLY to the modeled surface's true area
(both are locally flat/cylindrical, so the tributary split has no
curvature error); tests/test_stereo_geometry.py checks this.

Node identity is a plain list index, exactly like truss_math.py. Members
default to 'pin' (axial-only, ball-jointed) connectivity, which is the
physically correct default for the great majority of built space structures
(MERO, Nodus, Triodetic and similar systems are deliberately moment-free at
the node so that only axial force has to be resisted there); 'rigid'
(moment-transferring, Vierendeel-style) connectivity is available on any
member by setting conn='rigid', mirroring the Truss tab's pin/rigid choice.
"""
import math

from apps.stereo import expr_math

ROUND = 9   # coordinate rounding (m) so coincident nodes from independent
            # construction paths (e.g. a grid line and a diagonal sharing an
            # intended corner) compare equal in dict-based de-duplication.


def _key(x, y, z):
    return (round(x, ROUND), round(y, ROUND), round(z, ROUND))


class _NodeBank:
    """De-duplicates nodes by coordinate while building a generator, so two
    construction paths that land on the same physical point (e.g. a top-
    chord grid line and a diagonal web) share one node instead of silently
    creating an unconnected duplicate sitting on top of it -- the single
    most common way a hand-built mesh becomes a mechanism."""

    def __init__(self):
        self.nodes = []
        self._index = {}

    def add(self, x, y, z):
        k = _key(x, y, z)
        i = self._index.get(k)
        if i is None:
            i = len(self.nodes)
            self.nodes.append((x, y, z))
            self._index[k] = i
        return i


def _add_chords(members, seen, grid, imax, jmax, role, pattern):
    """Add chord members across a rectangular (i, j) index grid (0..imax,
    0..jmax), either along the grid lines ('square': parallel to the plan
    boundary -- Makowski's "square-on-square" family) or along the grid's
    own diagonals ('diagonal': 45 degrees to the boundary -- the
    "diagonal-on-diagonal" family). 'diagonal' reuses the EXACT SAME node
    positions 'square' does -- only which already-placed nodes get
    connected changes -- so it carries none of the clipping/re-placement
    risk a genuinely rotated node layout would."""
    if pattern == 'square':
        for j in range(jmax + 1):
            for i in range(imax):
                _add_member(members, seen, grid[(i, j)], grid[(i + 1, j)], role=role)
        for j in range(jmax):
            for i in range(imax + 1):
                _add_member(members, seen, grid[(i, j)], grid[(i, j + 1)], role=role)
    elif pattern == 'diagonal':
        for j in range(jmax):
            for i in range(imax):
                _add_member(members, seen, grid[(i, j)], grid[(i + 1, j + 1)], role=role)
                _add_member(members, seen, grid[(i + 1, j)], grid[(i, j + 1)], role=role)
    else:
        raise ValueError(f"pattern must be 'square' or 'diagonal', got {pattern!r}")


def _add_member(members, seen, a, b, **props):
    """Skip a zero-length or exactly-duplicate member instead of letting it
    silently double a stiffness contribution or divide by zero in the
    solver."""
    if a == b:
        return
    key = (min(a, b), max(a, b))
    if key in seen:
        return
    seen.add(key)
    m = {'a': a, 'b': b, 'conn': 'pin'}
    m.update(props)
    members.append(m)


# ═══════════════════════════════════════════════════════════════════════
#  1 · Flat double-layer space grid
# ═══════════════════════════════════════════════════════════════════════

def flat_grid(span_x, span_y, depth, module, offset=True, pattern='square', height_fn=None):
    """A rectangular double-layer space grid (the classic MERO/Nodus roof
    lattice): a bottom chord layer, a top chord layer `depth` above it,
    and diagonal webs between them.

    span_x, span_y : plan dimensions (m).
    depth          : the vertical distance between the two layers (m).
    module         : the in-plan grid spacing (m) -- both layers use the
                     same module; `offset` decides how they relate.
    offset=True    : "square-on-square offset" -- the top layer is shifted
                     by half a module in both x and y so each top node sits
                     over the centroid of four bottom-layer cells, and each
                     top node webs down to the four bottom nodes around it.
                     This is the configuration used on almost every real
                     bolted-ball-joint roof, because it triangulates the
                     webs automatically without any extra diagonal member.
    offset=False   : "square-on-square" -- the two layers align directly
                     above one another; each bottom node webs UP to the
                     top nodes of its four orthogonal in-plan neighbours
                     (never to the top node directly above it, which would
                     be a purely vertical member with no horizontal
                     stiffness at all) -- an inverted pyramid at every
                     interior node. Those webs alone fully triangulate the
                     model in all three directions, which is why this
                     needs no separate bracing member regardless of
                     `pattern`.
    pattern='square'   : chords run parallel to the plan boundary (along
                     the grid lines) -- the two configurations above.
    pattern='diagonal' : "diagonal-on-diagonal" -- both chord layers
                     instead run along the grid's own 45-degree diagonals
                     (both diagonals of every cell). Combines with
                     `offset` exactly as above (the node layout is
                     identical either way; only which already-placed
                     nodes the chords connect changes), giving four
                     typologies from one function.
    height_fn      : optional callable (x, y) -> z (m), the plan-view
                     grid's own height above a flat z=0 datum -- lets this
                     one function generate a flat roof (the default,
                     height_fn=None, z=0 everywhere) OR a curved SHELL on
                     the exact same rectangular plan and bracing scheme:
                     hypar_shell and hip_roof_grid below are both just this
                     function called with a different height_fn. Both
                     layers use it (the top layer at its OWN, possibly
                     offset, (x, y) plus `depth`), so the two layers stay a
                     near-constant `depth` apart everywhere, the same way a
                     real curved double-layer grid shell is built. The
                     web/chord CONNECTIVITY above depends only on the (i,j)
                     grid topology, never on height_fn's actual values, so
                     it is exactly as validated for a curved height_fn as
                     for the flat default.

    Returns the shared {'nodes','members','support_candidates'} dict.
    `support_candidates` is every bottom-layer perimeter node. `load_nodes`
    areas are the PLAN projection (dx*dy per cell, exact for a flat roof);
    for a curved height_fn this slightly understates the true, sloped
    surface area, the same kind of small, curvature-side approximation
    dome()'s own tributary areas document.
    """
    span_x = float(span_x); span_y = float(span_y)
    depth = float(depth); module = float(module)
    if module <= 0 or span_x <= 0 or span_y <= 0:
        raise ValueError('span_x, span_y and module must all be positive')
    if pattern not in ('square', 'diagonal'):
        raise ValueError(f"pattern must be 'square' or 'diagonal', got {pattern!r}")
    if height_fn is None:
        height_fn = lambda x, y: 0.0

    nx = max(1, round(span_x / module))
    ny = max(1, round(span_y / module))
    dx = span_x / nx
    dy = span_y / ny

    bank = _NodeBank()
    members = []
    seen = set()

    bottom = {}
    for j in range(ny + 1):
        for i in range(nx + 1):
            x, y = i * dx, j * dy
            bottom[(i, j)] = bank.add(x, y, height_fn(x, y))

    top = {}
    if offset:
        for j in range(ny):
            for i in range(nx):
                x = (i + 0.5) * dx
                y = (j + 0.5) * dy
                top[(i, j)] = bank.add(x, y, height_fn(x, y) + depth)
    else:
        for j in range(ny + 1):
            for i in range(nx + 1):
                x, y = i * dx, j * dy
                top[(i, j)] = bank.add(x, y, height_fn(x, y) + depth)

    # bottom chords
    _add_chords(members, seen, bottom, nx, ny, 'bottom_chord', pattern)

    # top chords
    if offset:
        _add_chords(members, seen, top, nx - 1, ny - 1, 'top_chord', pattern)
    else:
        _add_chords(members, seen, top, nx, ny, 'top_chord', pattern)

    # webs (diagonals)
    if offset:
        for j in range(ny):
            for i in range(nx):
                t = top[(i, j)]
                for bi, bj in ((i, j), (i + 1, j), (i, j + 1), (i + 1, j + 1)):
                    _add_member(members, seen, t, bottom[(bi, bj)], role='web')
    else:
        # Aligned layers put top[i,j] directly above bottom[i,j], so a web
        # joining them at the SAME (i,j) is purely vertical -- a member
        # with zero horizontal projection contributes nothing to in-plane
        # (X/Y) stiffness, and, more subtly, leaves that bottom/top PAIR
        # free to translate together in Z with nothing else to stop it
        # (every other member touching an interior node is horizontal: a
        # chord). An earlier version connected exactly those same-index
        # pairs -- despite this function's own docstring describing
        # "diagonals... a pyramid opening upward" -- which left the model
        # a genuine mechanism (confirmed by eigenanalysis on a 2x2-module
        # grid: 4-7 zero-energy modes depending on chord pattern, some
        # racking the top layer as a parallelogram, one translating an
        # entire interior bottom/top pair in Z with zero resistance).
        #
        # The fix actually matching that docstring: connect each bottom
        # node UP to its four orthogonally NEIGHBOURING top nodes (not its
        # own vertical counterpart), forming an inverted pyramid at every
        # interior node. Each such member has both a horizontal step (one
        # module, in +/-x or +/-y) and a vertical step (`depth`), so it
        # resists motion in all three directions at once -- this alone
        # triangulates the model fully regardless of chord `pattern`, so
        # no separate plan-bracing member is needed for either pattern
        # here (unlike the bottom-only brace an earlier version relied on).
        for j in range(ny + 1):
            for i in range(nx + 1):
                b = bottom[(i, j)]
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ni_, nj_ = i + di, j + dj
                    if 0 <= ni_ <= nx and 0 <= nj_ <= ny:
                        _add_member(members, seen, b, top[(ni_, nj_)], role='web')

    perimeter = sorted({bottom[(i, j)] for j in range(ny + 1) for i in range(nx + 1)
                         if i in (0, nx) or j in (0, ny)})

    # Tributary area for a roof (area) load, lumped onto the TOP layer --
    # the higher, +z surface, i.e. the one facing the load. Each top node
    # "owns" a dx*dy cell centered on itself; a perimeter node's cell is
    # clipped by the model boundary, so it gets half (edge) or a quarter
    # (corner) of a full cell. This is the standard lumped-tributary-area
    # rule, and it is EXACT here (no curvature): the areas always sum to
    # exactly span_x*span_y, proven in the module docstring and pinned by
    # test_flat_grid_tributary_areas_sum_to_the_plan_area.
    load_nodes = {}
    if offset:
        # every top node already sits at a cell centre with a full,
        # unclipped dx*dy cell (the offset inset by half a module on every
        # side is exactly what makes this tile the whole span with no
        # partial cells at all).
        for j in range(ny):
            for i in range(nx):
                load_nodes[top[(i, j)]] = dx * dy
    else:
        for j in range(ny + 1):
            fy = dy if 0 < j < ny else dy / 2.0
            for i in range(nx + 1):
                fx = dx if 0 < i < nx else dx / 2.0
                load_nodes[top[(i, j)]] = fx * fy

    return {'nodes': bank.nodes, 'members': members, 'support_candidates': perimeter,
            'load_nodes': load_nodes}


def hypar_shell(span_x, span_y, depth, module, rise, offset=True, pattern='square'):
    """A hyperbolic-paraboloid ("hypar") double-layer shell: a saddle
    surface z = rise * ((x-cx)/a) * ((y-cy)/b) over the same rectangular
    plan/bracing scheme as flat_grid -- two diagonally-opposite corners
    rise by `rise` above the mean plane, the other two dip by `rise`
    below it. A hypar is the doubly-ruled surface classic to shell and
    grid-shell roofs (each straight grid line is already a generator of
    the surface), built here simply as flat_grid with a saddle height_fn.

    rise : height (m) of the "up" corners above the mean (z=0) plane; the
           "down" corners sit `rise` below it. Amplitude only -- the saddle
           is centred on the plan rectangle regardless of span_x/span_y.

    Returns the shared {'nodes','members','support_candidates'} dict.
    """
    rise = float(rise)
    cx, cy = float(span_x) / 2.0, float(span_y) / 2.0
    ax = cx if cx > 0 else 1.0
    ay = cy if cy > 0 else 1.0

    def height_fn(x, y):
        return rise * ((x - cx) / ax) * ((y - cy) / ay)

    return flat_grid(span_x, span_y, depth, module, offset=offset, pattern=pattern,
                     height_fn=height_fn)


def hip_roof_grid(span_x, span_y, depth, module, rise, offset=True, pattern='square'):
    """A hip (pyramidal) roof double-layer grid: both layers rise linearly
    from z=0 at every eave to z=`rise` along the ridge/apex at the plan
    centre -- the classic four-hip-plane roof, built as flat_grid with a
    piecewise-linear height_fn (each of the four triangular hip planes,
    split by the plan diagonals, is individually flat).

    rise : ridge/apex height (m) above the eaves.

    Returns the shared {'nodes','members','support_candidates'} dict.
    """
    rise = float(rise)
    cx, cy = float(span_x) / 2.0, float(span_y) / 2.0
    ax = cx if cx > 0 else 1.0
    ay = cy if cy > 0 else 1.0

    def height_fn(x, y):
        fx = abs(x - cx) / ax
        fy = abs(y - cy) / ay
        return rise * (1.0 - max(fx, fy))

    return flat_grid(span_x, span_y, depth, module, offset=offset, pattern=pattern,
                     height_fn=height_fn)


def groin_vault(span, rise, module, depth, offset=True, pattern='square'):
    """A groin (cross) vault: two equal-span barrel vaults crossing at
    right angles over a SQUARE plan, built as flat_grid with a height_fn
    that is the pointwise MINIMUM of the two independent barrel
    profiles -- the standard way to define a groin vault's own ceiling
    surface. Each profile is an elliptical rise*sqrt(1-t^2) curve (t the
    -1..1 position across that axis, echoing barrel_vault()'s own
    circular arc without needing its R/half_angle machinery, since here
    only the height field, not a true circular arc length, is wanted).

    The min() gives z=0 along all four plan edges (one of the two
    profiles is always 0 there), the full `rise` at the centre (where
    both profiles equal `rise`), and -- everywhere the two profiles are
    equal, i.e. along the plan's own two diagonals -- the visible
    crossing "groin" ridges a real groin vault is named for.

    span   : the SQUARE plan's side length (m), shared by both crossing
             barrel profiles.
    rise   : height of the crown above the base plane (m).
    module, depth, offset, pattern : exactly as in flat_grid, on this
             same square plan.

    Returns the shared {'nodes','members','support_candidates'} dict,
    with the FULL base perimeter offered as support candidates -- a
    groin vault bears on all four walls, unlike a plain barrel vault's
    two long springing lines only.
    """
    span = float(span); rise = float(rise)
    if span <= 0 or rise <= 0:
        raise ValueError('span and rise must both be positive')
    half = span / 2.0

    def profile(u):
        t = max(-1.0, min(1.0, (u - half) / half))
        return rise * math.sqrt(max(0.0, 1.0 - t * t))

    def height_fn(x, y):
        return min(profile(x), profile(y))

    return flat_grid(span, span, depth, module, offset=offset, pattern=pattern,
                     height_fn=height_fn)


# ═══════════════════════════════════════════════════════════════════════
#  2 · Extruded-arch vaults (single or double layer): circular
#      (barrel_vault), parabolic, and elliptic profiles
# ═══════════════════════════════════════════════════════════════════════

def barrel_vault(span, rise, length, n_arch=8, n_bays=8, double_layer=True,
                  depth=0.0):
    """A cylindrical barrel vault: a circular arc of the given span/rise,
    subdivided into `n_arch` segments, extruded along `length` in `n_bays`
    bays. Purlins run along the length connecting matching arch stations;
    each bay face is braced with one diagonal so the vault does not rack.

    span, rise : the arc's chord width and mid-height rise (m); together
                 they fix the circle's radius R = rise/2 + span**2/(8*rise).
    length     : the vault's length along its straight (longitudinal) axis.
    n_arch     : number of segments around the arc (>= 2).
    n_bays     : number of bays along the length (>= 1).
    double_layer, depth : as in flat_grid -- an inner arc offset radially
                 inward by `depth`, connected to the outer arc by webs, at
                 every longitudinal station. depth is ignored if
                 double_layer is False.

    Returns the shared {'nodes','members','support_candidates'} dict, with
    every node on the two SPRINGING LINES (ai=0 and ai=n_arch, running the
    full length at every bay station) offered as support candidates --
    the vault's actual base, where each arch rib's own thrust needs to
    land, the same way a real barrel vault bears continuously along its
    two long walls rather than only at its two short end faces (which an
    earlier version of this function used, structurally backwards: it
    treated the vault like a beam spanning its own length between two end
    diaphragms instead of an arch spanning its own width down to a
    continuous base).
    """
    span = float(span); rise = float(rise); length = float(length)
    n_arch = max(2, int(n_arch)); n_bays = max(1, int(n_bays))
    if span <= 0 or rise <= 0 or length <= 0:
        raise ValueError('span, rise and length must all be positive')

    R = rise / 2.0 + (span ** 2) / (8.0 * rise)
    half_angle = math.asin(min(1.0, (span / 2.0) / R))
    cz = R - rise   # centre of the arc, below the crown, on the symmetry axis

    def arch_point(t, radius):
        # t in [-1, 1] across the span; x is the longitudinal (bay)
        # direction, y is the cross-section (transverse) coordinate, and
        # z is UP (the rise direction) -- Z is vertical everywhere in this
        # module (flat_grid, dome, the solver's self-weight direction and
        # the Stereo view's camera all treat +Z as up), so an earlier
        # version of this function that put the rise on Y instead made a
        # generated vault stand on its side relative to every other family
        # and to gravity itself; fixed 2026-09-12.
        ang = t * half_angle
        z = cz + radius * math.cos(ang)
        y = radius * math.sin(ang)
        return y, z

    bank = _NodeBank()
    members = []
    seen = set()

    outer = {}
    inner = {}
    bay_dx = length / n_bays
    for bi in range(n_bays + 1):
        x = bi * bay_dx
        for ai in range(n_arch + 1):
            t = -1.0 + 2.0 * ai / n_arch
            y, z = arch_point(t, R)
            outer[(bi, ai)] = bank.add(x, y, z)
            if double_layer and depth > 0:
                y2, z2 = arch_point(t, R - depth)
                inner[(bi, ai)] = bank.add(x, y2, z2)

    # arch ribs (transverse chords) at every bay station
    for bi in range(n_bays + 1):
        for ai in range(n_arch):
            _add_member(members, seen, outer[(bi, ai)], outer[(bi, ai + 1)], role='outer_rib')
            if double_layer and depth > 0:
                _add_member(members, seen, inner[(bi, ai)], inner[(bi, ai + 1)], role='inner_rib')

    # Intra-rib skip-one diagonal (ai to ai+2, same bay): triangulates each
    # arch rib WITHIN ITS OWN PLANE, independent of any other bay. This is
    # needed in addition to the inter-bay 'brace'/'edge_brace' bracing
    # below: those only resist RELATIVE motion between different bays
    # (bi vs bi+1), so a mode where every bay's rib flexes in-plane by the
    # SAME amount (uniform along the vault's length -- no relative inter-bay
    # motion at all) is invisible to them and remained a genuine zero-energy
    # mechanism even with a fully double-layer or edge-braced vault, found
    # by eigenanalysis after the support-placement fix above stopped masking
    # it (see barrel_vault's module-level history/tests for the full
    # derivation). Chording i to i+2 (on top of the existing i to i+1 rib)
    # closes overlapping triangles along the whole rib, exactly like
    # _edge_brace's own two-station skip.
    for bi in range(n_bays + 1):
        for ai in range(n_arch - 1):
            _add_member(members, seen, outer[(bi, ai)], outer[(bi, ai + 2)], role='rib_diag')
            if double_layer and depth > 0:
                _add_member(members, seen, inner[(bi, ai)], inner[(bi, ai + 2)], role='rib_diag')

    # purlins (longitudinal chords)
    for ai in range(n_arch + 1):
        for bi in range(n_bays):
            _add_member(members, seen, outer[(bi, ai)], outer[(bi + 1, ai)], role='purlin')
            if double_layer and depth > 0:
                _add_member(members, seen, inner[(bi, ai)], inner[(bi + 1, ai)], role='purlin')

    # Every springing-line node (ai=0 or ai=n_arch) that is not itself a
    # support needs a SECOND, non-parallel in-arc-plane bracing direction
    # -- see the single-layer branch's own note below for the full
    # geometric reason (y, z depend only on `ai`, so a rib/brace stepping
    # by the same delta-ai is always parallel regardless of `bi`, leaving
    # the springing line's one-sided station with only one direction and
    # the radial one unbraced). This showed up as a genuine mechanism at
    # the coarsest allowed resolution (n_arch=2) even WITH a double layer,
    # so both layers get it whenever a second layer exists, not only the
    # single-layer case.
    def _edge_brace(layer):
        for bi in range(n_bays):
            for ai_edge, ai_far in ((0, min(2, n_arch)), (n_arch, max(n_arch - 2, 0))):
                _add_member(members, seen, layer[(bi, ai_edge)], layer[(bi + 1, ai_far)],
                           role='edge_brace')
                _add_member(members, seen, layer[(bi + 1, ai_edge)], layer[(bi, ai_far)],
                           role='edge_brace')

    # Inter-bay X-brace (both diagonals) every bay panel, on the outer layer
    # always and the inner layer too whenever a double layer exists. A
    # single diagonal per panel is enough for a FLAT grid cell (flat_grid's
    # 'square' pattern), but even a FULL X-brace here still left a real
    # mechanism at every INTERIOR bay's springing line in the single-layer
    # case -- found by eigenanalysis (zero eigenvalues, and every member's
    # elongation under the mode was exactly zero, confirming a true
    # unbraced DOF rather than mere ill-conditioning). The reason is
    # geometric, not a missing member count: y and z here depend only on
    # `ai`, so EVERY member that steps by the same delta-ai (an outer_rib,
    # or a brace which steps delta-ai=1 and delta-bi=1 at once) has the
    # exact same (y, z) projection regardless of `bi` -- i.e. ribs and
    # braces at a given station are all parallel when flattened onto the
    # arc's own cross-sectional plane. A springing node (ai=0 or ai=n_arch)
    # only ever reaches ONE step in `ai` (there is no ai=-1), so it gets
    # exactly one independent in-plane direction from its rib/braces --
    # leaving the direction perpendicular to it (radially in or out of the
    # shell) completely unresisted, unless the node is itself a support
    # (true only at the two END bays of the OLD, structurally-backwards
    # support pattern). _edge_brace below gives that second direction.
    #
    # This same 'brace' diagonal turned out to ALSO be needed for the
    # DOUBLE-layer case on a non-circular (parabolic/elliptic) profile: at
    # some n_arch/n_bays combinations the double layer's own 'web_diag'/
    # 'edge_brace' bracing left a genuine longitudinal (x-direction) shear
    # mechanism between adjacent arc stations -- found the same way, via
    # eigenanalysis showing an exact zero mode with zero elongation on
    # every member. 'brace' connects outer-to-outer (or inner-to-inner)
    # across BOTH a bay step and an arc step at once, so it is never
    # parallel/degenerate with the purely-longitudinal purlin or the
    # purely-in-plane rib/rib_diag/web, closing that x-shear mode
    # regardless of arch profile.
    for bi in range(n_bays):
        for ai in range(n_arch):
            _add_member(members, seen, outer[(bi, ai)], outer[(bi + 1, ai + 1)], role='brace')
            _add_member(members, seen, outer[(bi + 1, ai)], outer[(bi, ai + 1)], role='brace')
            if double_layer and depth > 0:
                _add_member(members, seen, inner[(bi, ai)], inner[(bi + 1, ai + 1)], role='brace')
                _add_member(members, seen, inner[(bi + 1, ai)], inner[(bi, ai + 1)], role='brace')

    if double_layer and depth > 0:
        # radial webs between the two layers, plus a diagonal per panel so
        # the two layers act as a true space truss rather than a set of
        # independent parallel arches.
        for bi in range(n_bays + 1):
            for ai in range(n_arch + 1):
                _add_member(members, seen, outer[(bi, ai)], inner[(bi, ai)], role='web')
        for bi in range(n_bays):
            for ai in range(n_arch):
                _add_member(members, seen, outer[(bi, ai)], inner[(bi + 1, ai + 1)], role='web_diag')
                _add_member(members, seen, outer[(bi + 1, ai)], inner[(bi, ai + 1)], role='web_diag')
        _edge_brace(outer)
        _edge_brace(inner)
    else:
        _edge_brace(outer)

    # The vault's BASE: the two springing lines (ai=0, ai=n_arch), running
    # the full length (every bi) -- where a real barrel vault actually
    # bears (continuously along its two long walls), not the two short end
    # faces (bi=0, bi=n_bays), which would treat the vault as a beam
    # spanning its own length instead of an arch spanning its own width.
    support_candidates = sorted(set(outer[(bi, 0)] for bi in range(n_bays + 1))
                                 | set(outer[(bi, n_arch)] for bi in range(n_bays + 1)))
    if double_layer and depth > 0:
        support_candidates = sorted(set(support_candidates)
                                     | set(inner[(bi, 0)] for bi in range(n_bays + 1))
                                     | set(inner[(bi, n_arch)] for bi in range(n_bays + 1)))

    # Tributary area for a roof (area) load, lumped onto the OUTER shell
    # (the one facing outward/upward, whether single- or double-layer).
    # The arc is a true circle, so the arc-length per segment (ds = R *
    # the constant angular step) is the same at every station -- no
    # curvature error the way a dome's spherical tributary area has, since
    # a cylinder is developable (locally flat when unrolled). Areas sum
    # EXACTLY to the modeled shell's true surface area (arc_length *
    # length); see test_barrel_vault_tributary_areas_sum_to_the_shell_area.
    ds = R * (2.0 * half_angle / n_arch)
    load_nodes = {}
    for bi in range(n_bays + 1):
        f_long = bay_dx if 0 < bi < n_bays else bay_dx / 2.0
        for ai in range(n_arch + 1):
            f_arc = ds if 0 < ai < n_arch else ds / 2.0
            load_nodes[outer[(bi, ai)]] = f_long * f_arc

    return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
            'load_nodes': load_nodes}


def _extruded_arch_grid(arch_point, length, n_arch, n_bays, double_layer, depth):
    """Shared engine for parabolic_vault/elliptic_vault: an arbitrary arch
    profile `arch_point(t) -> (y, z)` for t in [-1, 1], extruded along
    `length` in `n_bays` bays -- exactly barrel_vault()'s own station/rib/
    purlin/edge-brace/web bracing (see its comments for the springing-line
    mechanism that bracing avoids), generalized to any arch shape since
    that bracing is purely topological and never references the arc being
    a true circle. The double-layer inner arc is `arch_point` itself
    offset by -depth in z (a simple vertical offset, not a true normal
    offset -- the same simplification flat_grid's height_fn-based shells
    use, reasonable for the shallow-to-moderate arches these are meant for).

    Returns (bank, members, outer, inner, support_candidates, bay_dx).
    """
    n_arch = max(2, int(n_arch)); n_bays = max(1, int(n_bays))
    if length <= 0:
        raise ValueError('length must be positive')

    bank = _NodeBank()
    members = []
    seen = set()

    outer = {}
    inner = {}
    bay_dx = length / n_bays
    for bi in range(n_bays + 1):
        x = bi * bay_dx
        for ai in range(n_arch + 1):
            t = -1.0 + 2.0 * ai / n_arch
            y, z = arch_point(t)
            outer[(bi, ai)] = bank.add(x, y, z)
            if double_layer and depth > 0:
                inner[(bi, ai)] = bank.add(x, y, z - depth)

    for bi in range(n_bays + 1):
        for ai in range(n_arch):
            _add_member(members, seen, outer[(bi, ai)], outer[(bi, ai + 1)], role='outer_rib')
            if double_layer and depth > 0:
                _add_member(members, seen, inner[(bi, ai)], inner[(bi, ai + 1)], role='inner_rib')

    # Intra-rib skip-one diagonal -- see barrel_vault()'s own comment on
    # this same fix for the full derivation (the inter-bay 'brace'/
    # 'edge_brace' bracing below can't resist a mode where every bay's rib
    # flexes identically, since that mode has no relative inter-bay motion
    # for it to detect).
    for bi in range(n_bays + 1):
        for ai in range(n_arch - 1):
            _add_member(members, seen, outer[(bi, ai)], outer[(bi, ai + 2)], role='rib_diag')
            if double_layer and depth > 0:
                _add_member(members, seen, inner[(bi, ai)], inner[(bi, ai + 2)], role='rib_diag')

    for ai in range(n_arch + 1):
        for bi in range(n_bays):
            _add_member(members, seen, outer[(bi, ai)], outer[(bi + 1, ai)], role='purlin')
            if double_layer and depth > 0:
                _add_member(members, seen, inner[(bi, ai)], inner[(bi + 1, ai)], role='purlin')

    def _edge_brace(layer):
        for bi in range(n_bays):
            for ai_edge, ai_far in ((0, min(2, n_arch)), (n_arch, max(n_arch - 2, 0))):
                _add_member(members, seen, layer[(bi, ai_edge)], layer[(bi + 1, ai_far)],
                           role='edge_brace')
                _add_member(members, seen, layer[(bi + 1, ai_edge)], layer[(bi, ai_far)],
                           role='edge_brace')

    # Inter-bay X-brace, on the outer layer always and the inner layer too
    # whenever a double layer exists -- see barrel_vault()'s own comment on
    # this same fix. Needed for single-layer in-plane stability, AND (on a
    # non-circular profile specifically) to close a longitudinal x-shear
    # mechanism the double layer's own web_diag/edge_brace can leave open
    # at some n_arch/n_bays combinations.
    for bi in range(n_bays):
        for ai in range(n_arch):
            _add_member(members, seen, outer[(bi, ai)], outer[(bi + 1, ai + 1)], role='brace')
            _add_member(members, seen, outer[(bi + 1, ai)], outer[(bi, ai + 1)], role='brace')
            if double_layer and depth > 0:
                _add_member(members, seen, inner[(bi, ai)], inner[(bi + 1, ai + 1)], role='brace')
                _add_member(members, seen, inner[(bi + 1, ai)], inner[(bi, ai + 1)], role='brace')

    if double_layer and depth > 0:
        for bi in range(n_bays + 1):
            for ai in range(n_arch + 1):
                _add_member(members, seen, outer[(bi, ai)], inner[(bi, ai)], role='web')
        for bi in range(n_bays):
            for ai in range(n_arch):
                _add_member(members, seen, outer[(bi, ai)], inner[(bi + 1, ai + 1)], role='web_diag')
                _add_member(members, seen, outer[(bi + 1, ai)], inner[(bi, ai + 1)], role='web_diag')
        _edge_brace(outer)
        _edge_brace(inner)
    else:
        _edge_brace(outer)

    # The vault's BASE: the two springing lines (ai=0, ai=n_arch), running
    # the full length (every bi) -- see barrel_vault()'s own comment on
    # this same point (an earlier version of both functions put supports
    # on the two short end faces instead, structurally backwards).
    support_candidates = sorted(set(outer[(bi, 0)] for bi in range(n_bays + 1))
                                 | set(outer[(bi, n_arch)] for bi in range(n_bays + 1)))
    if double_layer and depth > 0:
        support_candidates = sorted(set(support_candidates)
                                     | set(inner[(bi, 0)] for bi in range(n_bays + 1))
                                     | set(inner[(bi, n_arch)] for bi in range(n_bays + 1)))

    return bank, members, outer, inner, support_candidates, bay_dx


def _secant_arc_load_nodes(arch_point, n_arch, n_bays, bay_dx, outer):
    """Tributary area for an extruded arch shell's outer layer via secant
    (straight-line) arc-length segments -- used for arch profiles with no
    circle-simple closed-form arc length (a parabola or an ellipse), the
    same kind of midpoint-rule approximation dome()'s own tributary area
    documents for a non-developable surface."""
    pts = [arch_point(-1.0 + 2.0 * ai / n_arch) for ai in range(n_arch + 1)]
    seg = [0.0] * (n_arch + 1)   # seg[ai]: distance from station ai-1 to ai
    for ai in range(1, n_arch + 1):
        seg[ai] = math.dist(pts[ai - 1], pts[ai])
    load_nodes = {}
    for bi in range(n_bays + 1):
        f_long = bay_dx if 0 < bi < n_bays else bay_dx / 2.0
        for ai in range(n_arch + 1):
            f_arc = ((seg[ai] if ai > 0 else 0.0) + (seg[ai + 1] if ai < n_arch else 0.0)) / 2.0
            load_nodes[outer[(bi, ai)]] = f_long * f_arc
    return load_nodes


def parabolic_vault(span, rise, length, n_arch=8, n_bays=8, double_layer=True, depth=0.0):
    """A parabolic-arch barrel vault: the same station/rib/purlin/bracing
    scheme as barrel_vault(), on a PARABOLIC arch profile instead of a
    circular one -- z = rise * (1 - t**2), y = (span/2) * t for t in
    [-1, 1] -- a shallower-crowned, steeper-springing shape than the
    circular arc of the same span/rise.

    span, rise, length, n_arch, n_bays, double_layer, depth : as in
    barrel_vault().

    Returns the shared {'nodes','members','support_candidates'} dict, with
    every node on the two springing lines (the vault's base) offered as
    support candidates.
    """
    span = float(span); rise = float(rise)
    if span <= 0 or rise <= 0:
        raise ValueError('span and rise must both be positive')

    def arch_point(t):
        return (span / 2.0) * t, rise * (1.0 - t * t)

    bank, members, outer, _inner, support_candidates, bay_dx = _extruded_arch_grid(
        arch_point, length, n_arch, n_bays, double_layer, depth)
    n_arch = max(2, int(n_arch)); n_bays = max(1, int(n_bays))
    load_nodes = _secant_arc_load_nodes(arch_point, n_arch, n_bays, bay_dx, outer)

    return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
            'load_nodes': load_nodes}


def elliptic_vault(span, rise, length, n_arch=8, n_bays=8, double_layer=True, depth=0.0):
    """An elliptic-arch barrel vault: the same station/rib/purlin/bracing
    scheme as barrel_vault(), on an ELLIPTICAL arch profile with
    independent half-span and rise -- y = (span/2)*sin(t*pi/2),
    z = rise*cos(t*pi/2) for t in [-1, 1] (a circular arch of radius
    span/2 is the special case rise = span/2).

    span, rise, length, n_arch, n_bays, double_layer, depth : as in
    barrel_vault() -- span and rise are now independent semi-axes rather
    than jointly fixing a single circle radius.

    Returns the shared {'nodes','members','support_candidates'} dict, with
    every node on the two springing lines (the vault's base) offered as
    support candidates.
    """
    span = float(span); rise = float(rise)
    if span <= 0 or rise <= 0:
        raise ValueError('span and rise must both be positive')
    a, b = span / 2.0, rise

    def arch_point(t):
        ang = t * (math.pi / 2.0)
        return a * math.sin(ang), b * math.cos(ang)

    bank, members, outer, _inner, support_candidates, bay_dx = _extruded_arch_grid(
        arch_point, length, n_arch, n_bays, double_layer, depth)
    n_arch = max(2, int(n_arch)); n_bays = max(1, int(n_bays))
    load_nodes = _secant_arc_load_nodes(arch_point, n_arch, n_bays, bay_dx, outer)

    return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
            'load_nodes': load_nodes}


# ═══════════════════════════════════════════════════════════════════════
#  3 · Ribbed (Schwedler-type) axisymmetric shells: dome, paraboloid dish,
#      elliptic dome, full sphere -- one apex, `n_rings` hoop rings, and
#      one Schwedler diagonal per panel, exactly as a Schwedler dome is
#      built, generalized to any ring PROFILE (the connectivity is purely
#      topological -- it never references the actual ring coordinates --
#      so the same bracing dome() already validated across n_rings x
#      n_sectors sweeps applies unchanged to a differently-shaped profile).
# ═══════════════════════════════════════════════════════════════════════

def _add_apex_ribbed_shell(members, seen, apex, rings, n_sectors):
    """Meridian ribs (apex to ring 0, then ring to ring), hoop rings, and
    one Schwedler diagonal per panel (alternating direction ring to ring
    so consecutive rings brace against opposite racking senses) -- the
    exact connectivity a Schwedler dome uses, shared by every apex-topped
    axisymmetric shell in this module. Takes node ids only, never
    coordinates, so it is correct for ANY ring profile, not just a sphere."""
    n_rings = len(rings)
    for s in range(n_sectors):
        _add_member(members, seen, apex, rings[0][s], role='meridian')
        for k in range(n_rings - 1):
            _add_member(members, seen, rings[k][s], rings[k + 1][s], role='meridian')

    for k in range(n_rings):
        ring = rings[k]
        n = len(ring)
        for s in range(n):
            _add_member(members, seen, ring[s], ring[(s + 1) % n], role='hoop')

    prev_ring = [apex] * n_sectors
    for k in range(n_rings):
        ring = rings[k]
        n = len(ring)
        for s in range(n_sectors):
            a = prev_ring[s]
            b = prev_ring[(s + 1) % n_sectors] if k > 0 else apex
            c = ring[s]
            d = ring[(s + 1) % n]
            if k == 0:
                # triangular apex panels are already stable; no diagonal
                # needed (a and b coincide at the apex).
                continue
            if s % 2 == 0:
                _add_member(members, seen, a, d, role='diagonal')
            else:
                _add_member(members, seen, b, c, role='diagonal')
        prev_ring = ring


def dome(base_radius, rise, n_rings=4, n_sectors=12):
    """A single-layer ribbed dome on a spherical cap: `n_sectors` meridian
    ribs from the apex to the base ring, `n_rings` intermediate hoop rings,
    and one diagonal per quadrilateral panel (a Schwedler dome's defining
    feature -- the diagonals are what make an otherwise-mechanism grid of
    meridians and hoops into a stable triangulated shell).

    base_radius : radius of the dome's base circle (m).
    rise        : height of the apex above the base plane (m).
    n_rings     : number of hoop rings between the apex and the base
                  (>= 1); the base ring itself is always included besides
                  these.
    n_sectors   : number of meridian ribs (>= 3).

    Returns the shared {'nodes','members','support_candidates'} dict, with
    the base ring nodes offered as support candidates.
    """
    base_radius = float(base_radius); rise = float(rise)
    n_rings = max(1, int(n_rings)); n_sectors = max(3, int(n_sectors))
    if base_radius <= 0 or rise <= 0:
        raise ValueError('base_radius and rise must both be positive')

    # Sphere through the apex (0,0,rise) and the base ring (base_radius, 0):
    # R = (base_radius**2 + rise**2) / (2*rise); centre sits below the base
    # plane at z = rise - R.
    R = (base_radius ** 2 + rise ** 2) / (2.0 * rise)
    z0 = rise - R
    phi_max = math.asin(min(1.0, base_radius / R))   # polar angle at the base

    bank = _NodeBank()
    members = []
    seen = set()

    apex = bank.add(0.0, 0.0, rise)

    rings = []   # rings[k][s] = node index, k=1..n_rings is the ring index
                 # (k=n_rings is the base ring), s=0..n_sectors-1
    for k in range(1, n_rings + 1):
        phi = phi_max * k / n_rings
        r_k = R * math.sin(phi)
        z_k = z0 + R * math.cos(phi)
        ring = []
        for s in range(n_sectors):
            th = 2.0 * math.pi * s / n_sectors
            ring.append(bank.add(r_k * math.cos(th), r_k * math.sin(th), z_k))
        rings.append(ring)

    _add_apex_ribbed_shell(members, seen, apex, rings, n_sectors)

    support_candidates = list(rings[-1])

    # Tributary area for a roof (area) load, lumped over the whole dome
    # surface (apex + every ring node). Unlike flat_grid/barrel_vault, a
    # sphere is NOT developable: "half the meridian arc-step times the
    # hoop circumference at this node's own latitude" is a MIDPOINT-RULE
    # discretization of the exact zone-area integral 2*pi*R^2*sin(phi)*dphi,
    # not an identity. It converges to the true spherical-cap area as
    # n_rings grows (tested for convergence, not exact equality, in
    # test_dome_tributary_areas_converge_to_the_cap_area) and is the same
    # lumping convention any FE tool uses for a curved shell, so the error
    # at ordinary mesh densities is small and always on the side of the
    # true curvature (a coarse dome very slightly overstates area near the
    # equator and understates it near the apex -- sin(phi) is concave here).
    phi_step = phi_max / n_rings
    load_nodes = {}
    apex_cap_half_angle = phi_step / 2.0
    load_nodes[apex] = 2.0 * math.pi * R ** 2 * (1.0 - math.cos(apex_cap_half_angle))
    for k in range(1, n_rings + 1):
        phi_k = phi_max * k / n_rings
        # R * phi_step, NOT bare phi_step: phi_step is an ANGLE (radians),
        # and the area element needs the actual meridian ARC LENGTH
        # (R * dphi) to pair with the hoop's arc length below -- omitting
        # R here understated every ring's area by a factor of R (~18x for
        # a typical dome), caught by
        # test_dome_tributary_areas_converge_to_the_cap_area_as_the_mesh_refines.
        meridian_factor = R * phi_step * (1.0 if k < n_rings else 0.5)
        hoop_factor = R * math.sin(phi_k) * (2.0 * math.pi / n_sectors)
        area = meridian_factor * hoop_factor
        for node in rings[k - 1]:
            load_nodes[node] = area

    return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
            'load_nodes': load_nodes}


def cone_roof(base_radius, rise, n_rings=4, n_sectors=12):
    """A single-layer ribbed CONICAL roof: the same Schwedler apex+rings+
    diagonals bracing as dome()/paraboloid_dish(), on a straight-line
    (conical) profile instead of a curved one -- z = rise * (1 - r /
    base_radius), apex at the centre (z=rise), sloping straight down to
    the base ring at z=0. Every meridian rib is a literal straight rafter
    from apex to base, unlike a dome's curved meridian -- the shape a
    conical tower roof or a silo top actually is.

    base_radius : radius of the base ring (m).
    rise        : height of the apex above the base ring (m).
    n_rings, n_sectors : as in dome().

    Returns the shared {'nodes','members','support_candidates'} dict, with
    the base ring nodes offered as support candidates.
    """
    base_radius = float(base_radius); rise = float(rise)
    n_rings = max(1, int(n_rings)); n_sectors = max(3, int(n_sectors))
    if base_radius <= 0 or rise <= 0:
        raise ValueError('base_radius and rise must both be positive')

    bank = _NodeBank()
    members = []
    seen = set()

    apex = bank.add(0.0, 0.0, rise)

    rings = []
    for k in range(1, n_rings + 1):
        r_k = base_radius * k / n_rings
        z_k = rise * (1.0 - r_k / base_radius)
        ring = []
        for s in range(n_sectors):
            th = 2.0 * math.pi * s / n_sectors
            ring.append(bank.add(r_k * math.cos(th), r_k * math.sin(th), z_k))
        rings.append(ring)

    _add_apex_ribbed_shell(members, seen, apex, rings, n_sectors)
    support_candidates = list(rings[-1])

    # Tributary area via the same midpoint-rule secant lumping dome() and
    # paraboloid_dish() use. The MERIDIAN direction has no discretization
    # error here (a cone's meridian genuinely is the straight line the
    # secant assumes), but the apex cap is still treated as a flat disk
    # (pi * r_half**2) rather than the small cone-tip lateral area it
    # actually is, so the total is still a CONVERGENT approximation, not
    # an exact sum at every mesh density -- confirmed numerically in
    # test_cone_roof_tributary_areas_converge_to_the_lateral_surface_area.
    seg = [0.0] * (n_rings + 1)
    prev_r, prev_z = 0.0, rise
    for k in range(1, n_rings + 1):
        r_k = base_radius * k / n_rings
        z_k = rise * (1.0 - r_k / base_radius)
        seg[k] = math.hypot(r_k - prev_r, z_k - prev_z)
        prev_r, prev_z = r_k, z_k

    load_nodes = {}
    for k in range(1, n_rings + 1):
        r_k = base_radius * k / n_rings
        hoop_factor = r_k * (2.0 * math.pi / n_sectors)
        meridian_in = seg[k] / 2.0
        meridian_out = seg[k + 1] / 2.0 if k < n_rings else 0.0
        area = (meridian_in + meridian_out) * hoop_factor
        for node in rings[k - 1]:
            load_nodes[node] = area
    r_half = base_radius / n_rings / 2.0
    load_nodes[apex] = math.pi * r_half ** 2

    return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
            'load_nodes': load_nodes}


def paraboloid_dish(base_radius, rise, n_rings=4, n_sectors=12):
    """A single-layer ribbed paraboloid dish (a satellite-dish/reflector-
    antenna shape): the same Schwedler apex+rings+diagonals bracing as
    dome(), on a PARABOLIC instead of spherical profile -- z = rise *
    (r / base_radius)**2, apex at the centre (z=0), opening upward to the
    rim at z=rise.

    base_radius : radius of the dish's rim (m).
    rise        : height of the rim above the apex (m).
    n_rings, n_sectors : as in dome().

    Returns the shared {'nodes','members','support_candidates'} dict, with
    the rim nodes offered as support candidates.
    """
    base_radius = float(base_radius); rise = float(rise)
    n_rings = max(1, int(n_rings)); n_sectors = max(3, int(n_sectors))
    if base_radius <= 0 or rise <= 0:
        raise ValueError('base_radius and rise must both be positive')

    bank = _NodeBank()
    members = []
    seen = set()

    apex = bank.add(0.0, 0.0, 0.0)

    rings = []
    for k in range(1, n_rings + 1):
        r_k = base_radius * k / n_rings
        z_k = rise * (r_k / base_radius) ** 2
        ring = []
        for s in range(n_sectors):
            th = 2.0 * math.pi * s / n_sectors
            ring.append(bank.add(r_k * math.cos(th), r_k * math.sin(th), z_k))
        rings.append(ring)

    _add_apex_ribbed_shell(members, seen, apex, rings, n_sectors)
    support_candidates = list(rings[-1])

    # Tributary area, lumped the same midpoint-rule way dome() does: half
    # the meridian SEGMENT LENGTH (the straight-line distance between
    # consecutive ring nodes -- a parabola has no simple closed-form arc
    # length the way a circle does, so this is a secant approximation,
    # good at ordinary mesh densities) times the hoop arc length at each
    # ring's own radius.
    seg = [0.0] * (n_rings + 1)   # seg[k]: distance from ring k-1 to ring k
    prev_r, prev_z = 0.0, 0.0
    for k in range(1, n_rings + 1):
        r_k = base_radius * k / n_rings
        z_k = rise * (r_k / base_radius) ** 2
        seg[k] = math.hypot(r_k - prev_r, z_k - prev_z)
        prev_r, prev_z = r_k, z_k

    load_nodes = {}
    for k in range(1, n_rings + 1):
        r_k = base_radius * k / n_rings
        hoop_factor = r_k * (2.0 * math.pi / n_sectors)
        meridian_in = seg[k] / 2.0
        meridian_out = seg[k + 1] / 2.0 if k < n_rings else 0.0
        area = (meridian_in + meridian_out) * hoop_factor
        for node in rings[k - 1]:
            load_nodes[node] = area
    r_half = base_radius / n_rings / 2.0
    load_nodes[apex] = math.pi * r_half ** 2

    return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
            'load_nodes': load_nodes}


def elliptic_dome(radius_x, radius_y, rise, n_rings=4, n_sectors=12):
    """A single-layer ribbed cap of a general ELLIPSOID (independent x and
    y base radii, and an independent rise): the same Schwedler apex+rings+
    diagonals bracing as dome(), with x = radius_x*sin(u)*cos(th),
    y = radius_y*sin(u)*sin(th), z = rise*cos(u) for u running 0 (apex) to
    pi/2 (base ring) -- a sphere is the special case radius_x = radius_y
    = rise.

    radius_x, radius_y : the base ellipse's two semi-axes (m).
    rise                : apex height above the base plane (m).
    n_rings, n_sectors  : as in dome().

    Returns the shared {'nodes','members','support_candidates'} dict, with
    the base ring nodes offered as support candidates.
    """
    radius_x = float(radius_x); radius_y = float(radius_y); rise = float(rise)
    n_rings = max(1, int(n_rings)); n_sectors = max(3, int(n_sectors))
    if radius_x <= 0 or radius_y <= 0 or rise <= 0:
        raise ValueError('radius_x, radius_y and rise must all be positive')

    bank = _NodeBank()
    members = []
    seen = set()

    apex = bank.add(0.0, 0.0, rise)
    apex_pt = (0.0, 0.0, rise)

    rings = []
    ring_pts = []
    for k in range(1, n_rings + 1):
        u = (k / n_rings) * (math.pi / 2.0)
        rr = math.sin(u)
        z_k = rise * math.cos(u)
        ring, pts = [], []
        for s in range(n_sectors):
            th = 2.0 * math.pi * s / n_sectors
            x = radius_x * rr * math.cos(th)
            y = radius_y * rr * math.sin(th)
            ring.append(bank.add(x, y, z_k))
            pts.append((x, y, z_k))
        rings.append(ring)
        ring_pts.append(pts)

    _add_apex_ribbed_shell(members, seen, apex, rings, n_sectors)
    support_candidates = list(rings[-1])

    # Tributary area via straight-line (secant) segment lengths, both
    # meridian and hoop -- an ellipse has no simple closed-form arc length
    # either way, so this is the same kind of midpoint-rule approximation
    # dome()'s own (exact-formula) spherical tributary area generalizes to
    # when no exact formula exists, converging the same way as n_rings and
    # n_sectors grow.
    load_nodes = {}
    for k in range(1, n_rings + 1):
        pts = ring_pts[k - 1]
        n = len(pts)
        next_pts = ring_pts[k] if k < n_rings else None
        for s in range(n):
            hoop = (math.dist(pts[s], pts[(s - 1) % n])
                   + math.dist(pts[s], pts[(s + 1) % n])) / 2.0
            merid_in = math.dist(pts[s], apex_pt) if k == 1 else math.dist(pts[s], ring_pts[k - 2][s])
            merid_out = math.dist(pts[s], next_pts[s]) if next_pts is not None else 0.0
            load_nodes[rings[k - 1][s]] = hoop * (merid_in + merid_out) / 2.0
    avg_merid0 = sum(math.dist(apex_pt, p) for p in ring_pts[0]) / len(ring_pts[0])
    load_nodes[apex] = math.pi * (avg_merid0 / 2.0) ** 2

    return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
            'load_nodes': load_nodes}


def sphere_shell(radius, n_rings=4, n_sectors=12):
    """A single-layer ribbed FULL sphere: the same Schwedler apex+rings+
    diagonals bracing as dome(), extended past a single cap all the way to
    a second (bottom) pole -- `n_rings` hoop rings per hemisphere
    (including the shared equator ring), meridian ribs pole to pole, and
    Schwedler diagonals in every ring-to-ring panel. Both polar caps are
    simple triangular fans, exactly like dome()'s own apex fan -- inherently
    stable, no diagonal needed.

    radius   : sphere radius (m).
    n_rings  : hoop rings PER HEMISPHERE, including the shared equator ring
               (>= 1); the total distinct hoop-ring count is 2*n_rings - 1.
    n_sectors: number of meridian ribs (>= 3).

    Returns the shared {'nodes','members','support_candidates'} dict, with
    the EQUATOR ring nodes offered as support candidates -- the natural
    place to support a free-standing spherical shell.
    """
    radius = float(radius)
    n_rings = max(1, int(n_rings)); n_sectors = max(3, int(n_sectors))
    if radius <= 0:
        raise ValueError('radius must be positive')

    bank = _NodeBank()
    members = []
    seen = set()

    apex_top = bank.add(0.0, 0.0, radius)

    total_rings = 2 * n_rings - 1
    rings = []
    for k in range(1, total_rings + 1):
        phi = math.pi * k / (2 * n_rings)
        r_k = radius * math.sin(phi)
        z_k = radius * math.cos(phi)
        ring = []
        for s in range(n_sectors):
            th = 2.0 * math.pi * s / n_sectors
            ring.append(bank.add(r_k * math.cos(th), r_k * math.sin(th), z_k))
        rings.append(ring)

    apex_bottom = bank.add(0.0, 0.0, -radius)

    _add_apex_ribbed_shell(members, seen, apex_top, rings, n_sectors)
    for s in range(n_sectors):
        _add_member(members, seen, rings[-1][s], apex_bottom, role='meridian')

    support_candidates = list(rings[n_rings - 1])   # the equator ring

    # Tributary area: the same midpoint-rule spherical-zone lumping dome()
    # uses. Unlike dome, every numbered ring here has a neighbour on BOTH
    # sides (another ring, or a pole) -- there is no free/boundary ring --
    # so every ring gets the FULL phi_step tributary width, with no
    # dome-style halving anywhere.
    phi_step = math.pi / (2 * n_rings)
    load_nodes = {}
    cap_area = 2.0 * math.pi * radius ** 2 * (1.0 - math.cos(phi_step / 2.0))
    load_nodes[apex_top] = cap_area
    load_nodes[apex_bottom] = cap_area
    for k in range(1, total_rings + 1):
        phi_k = math.pi * k / (2 * n_rings)
        meridian_factor = radius * phi_step
        hoop_factor = radius * math.sin(phi_k) * (2.0 * math.pi / n_sectors)
        area = meridian_factor * hoop_factor
        for node in rings[k - 1]:
            load_nodes[node] = area

    return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
            'load_nodes': load_nodes}


# ═══════════════════════════════════════════════════════════════════════
#  4 · Circular (radial) flat double-layer grid
# ═══════════════════════════════════════════════════════════════════════

def circular_flat_grid(outer_radius, depth, n_rings, n_sectors, offset=True):
    """A round-plan double-layer flat space grid (e.g. a circular stadium/
    arena roof): a HUB at the centre, `n_rings` concentric hoop rings of
    `n_sectors` nodes each on the bottom layer, and a matching top layer
    `depth` above it -- the polar analogue of flat_grid's own rectangular
    scheme, including its `offset` idea.

    offset=True  : the top layer's rings sit at radii BETWEEN consecutive
                   bottom rings and rotated by half a sector, so each top
                   node webs down to the 4 bottom nodes around it (or, for
                   the innermost top ring, to the hub plus the 2 nearest
                   ring-1 nodes) -- the polar equivalent of flat_grid's own
                   "square-on-square offset" pyramidal webs, and for the
                   same reason: it triangulates automatically with no
                   extra diagonal member.
    offset=False : the two layers align (same radius and angle); each
                   bottom node webs UP to its neighbouring top nodes --
                   one ring in, one ring out (where they exist, PLUS a
                   diagonal tie shifted one sector for each), one sector
                   each way -- never straight up to the point directly
                   above it, extending the fix flat_grid's own aligned
                   mode needed for the same reason (a purely vertical web
                   has no horizontal stiffness and leaves an interior
                   node's Z free). The diagonal (sector-shifted) radial tie
                   is NOT optional here the way it would be on a
                   rectangular grid: a same-sector radial web is purely
                   radial with zero tangential component, so without it an
                   entire ring can rotate rigidly relative to its
                   neighbours with no member changing length -- a genuine
                   mechanism found by eigenanalysis at ordinary mesh
                   densities (e.g. 6 rings x 12 sectors), fixed by giving
                   every radial web a deliberate angular offset too.

    outer_radius : plan radius of the grid (m).
    depth        : vertical distance between the two layers (m).
    n_rings      : number of concentric hoop rings (>= 1).
    n_sectors    : number of radial divisions (>= 3).

    Returns the shared {'nodes','members','support_candidates'} dict;
    `support_candidates` is the outermost bottom ring. `load_nodes` are
    exact for offset=True (the annular-sector cells tile the circle's
    plan area exactly, the same "no curvature error" property flat_grid's
    own rectangular cells have) and a standard r*dr*dtheta lumped
    approximation for offset=False.
    """
    outer_radius = float(outer_radius); depth = float(depth)
    n_rings = max(1, int(n_rings)); n_sectors = max(3, int(n_sectors))
    if outer_radius <= 0:
        raise ValueError('outer_radius must be positive')

    bank = _NodeBank()
    members = []
    seen = set()

    hub = bank.add(0.0, 0.0, 0.0)
    bottom = {}
    for k in range(1, n_rings + 1):
        r = outer_radius * k / n_rings
        for s in range(n_sectors):
            th = 2.0 * math.pi * s / n_sectors
            bottom[(k, s)] = bank.add(r * math.cos(th), r * math.sin(th), 0.0)

    top = {}
    if offset:
        for k in range(1, n_rings + 1):
            r = outer_radius * (k - 0.5) / n_rings
            for s in range(n_sectors):
                th = 2.0 * math.pi * (s + 0.5) / n_sectors
                top[(k, s)] = bank.add(r * math.cos(th), r * math.sin(th), depth)
    else:
        for k in range(1, n_rings + 1):
            r = outer_radius * k / n_rings
            for s in range(n_sectors):
                th = 2.0 * math.pi * s / n_sectors
                top[(k, s)] = bank.add(r * math.cos(th), r * math.sin(th), depth)

    # bottom chords: hub spokes, radial spokes, hoops
    for s in range(n_sectors):
        _add_member(members, seen, hub, bottom[(1, s)], role='bottom_chord')
    for k in range(1, n_rings):
        for s in range(n_sectors):
            _add_member(members, seen, bottom[(k, s)], bottom[(k + 1, s)], role='bottom_chord')
    for k in range(1, n_rings + 1):
        for s in range(n_sectors):
            _add_member(members, seen, bottom[(k, s)], bottom[(k, (s + 1) % n_sectors)],
                       role='bottom_chord')

    # top chords: hoops + radial spokes
    for k in range(1, n_rings + 1):
        for s in range(n_sectors):
            _add_member(members, seen, top[(k, s)], top[(k, (s + 1) % n_sectors)],
                       role='top_chord')
    for k in range(1, n_rings):
        for s in range(n_sectors):
            _add_member(members, seen, top[(k, s)], top[(k + 1, s)], role='top_chord')

    if offset:
        for s in range(n_sectors):
            _add_member(members, seen, top[(1, s)], hub, role='web')
            _add_member(members, seen, top[(1, s)], bottom[(1, s)], role='web')
            _add_member(members, seen, top[(1, s)], bottom[(1, (s + 1) % n_sectors)], role='web')
        for k in range(2, n_rings + 1):
            for s in range(n_sectors):
                _add_member(members, seen, top[(k, s)], bottom[(k - 1, s)], role='web')
                _add_member(members, seen, top[(k, s)], bottom[(k - 1, (s + 1) % n_sectors)],
                           role='web')
                _add_member(members, seen, top[(k, s)], bottom[(k, s)], role='web')
                _add_member(members, seen, top[(k, s)], bottom[(k, (s + 1) % n_sectors)], role='web')
    else:
        for s in range(n_sectors):
            _add_member(members, seen, hub, top[(1, s)], role='web')
            _add_member(members, seen, hub, top[(1, (s + 1) % n_sectors)], role='web_diag')
        for k in range(1, n_rings + 1):
            for s in range(n_sectors):
                if k > 1:
                    _add_member(members, seen, bottom[(k, s)], top[(k - 1, s)], role='web')
                    _add_member(members, seen, bottom[(k, s)], top[(k - 1, (s + 1) % n_sectors)],
                               role='web_diag')
                if k < n_rings:
                    _add_member(members, seen, bottom[(k, s)], top[(k + 1, s)], role='web')
                    _add_member(members, seen, bottom[(k, s)], top[(k + 1, (s + 1) % n_sectors)],
                               role='web_diag')
                _add_member(members, seen, bottom[(k, s)], top[(k, (s - 1) % n_sectors)], role='web')
                _add_member(members, seen, bottom[(k, s)], top[(k, (s + 1) % n_sectors)], role='web')

    support_candidates = [bottom[(n_rings, s)] for s in range(n_sectors)]

    load_nodes = {}
    angular_step = 2.0 * math.pi / n_sectors
    if offset:
        r_prev = 0.0
        for k in range(1, n_rings + 1):
            r_k = outer_radius * k / n_rings
            area = 0.5 * (r_k ** 2 - r_prev ** 2) * angular_step
            for s in range(n_sectors):
                load_nodes[top[(k, s)]] = area
            r_prev = r_k
    else:
        dr = outer_radius / n_rings
        for k in range(1, n_rings + 1):
            r_k = outer_radius * k / n_rings
            fr = dr if 1 < k < n_rings else dr / 2.0
            area = r_k * fr * angular_step
            for s in range(n_sectors):
                load_nodes[top[(k, s)]] = area

    return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
            'load_nodes': load_nodes}


# ═══════════════════════════════════════════════════════════════════════
#  4 · Truss bridge: two parallel planar Warren/Pratt-style trusses,
#      deck cross-beams, and lateral bracing
# ═══════════════════════════════════════════════════════════════════════

def truss_bridge(span, depth, width, n_panels=8):
    """A through-truss bridge: two parallel vertical PLANAR trusses (one
    along each edge of the deck), tied together by cross-beams at every
    panel point and full X lateral bracing at both the top and bottom
    chord levels. The lateral bracing is not optional decoration: each
    planar truss on its own is only stable WITHIN its own vertical
    plane, so without it the two planes together would be free to rack
    sideways -- a genuine 3D mechanism -- with nothing to resist
    transverse shear.

    Each planar truss is a classic zigzag (Warren/Pratt-style) truss: a
    vertical post at every panel point, one chord along the top and one
    along the bottom, and a single diagonal per panel that alternates
    direction panel to panel. On its own (as a 2D truss with one pin and
    one roller support) this is exactly statically determinate --
    m + r = 2j for any n_panels -- the standard bridge-truss topology,
    not an arbitrary triangulation.

    span     : total length along the direction of travel (m).
    depth    : vertical height between the top and bottom chords (m).
    width    : transverse distance between the two truss planes, i.e.
               the deck width (m).
    n_panels : number of panels along the span (>= 2 -- a single panel
               has no adjacent diagonal to alternate against).

    Returns the shared {'nodes','members','support_candidates'} dict,
    with the four BOTTOM corner nodes (both ends, both truss planes --
    a bridge's actual bearing points) offered as support candidates.

    Like any pin-jointed truss, a small set of EXACT dimension
    combinations can coincidentally put the geometry into a critical
    (instantaneously mechanistic) form -- a real, if narrow, structural
    phenomenon, not a defect in this topology: e.g. span=40, depth=5,
    width=6, n_panels=4 solves as a genuine mechanism, while width=5.9
    or 6.1 at the same other values does not. Analyze reports this the
    normal way (a singular stiffness matrix), the same as it would for a
    hand-built model that happened onto the same critical proportions;
    changing any one dimension slightly is enough to leave it.
    """
    span = float(span); depth = float(depth); width = float(width)
    n_panels = max(2, int(n_panels))
    if span <= 0 or depth <= 0 or width <= 0:
        raise ValueError('span, depth and width must all be positive')

    panel = span / n_panels
    bank = _NodeBank()
    members = []
    seen = set()

    bottom = {}   # (i, side) -> node id; side 0 is y=0, side 1 is y=width
    top = {}
    for i in range(n_panels + 1):
        x = i * panel
        for side, y in ((0, 0.0), (1, width)):
            bottom[(i, side)] = bank.add(x, y, 0.0)
            top[(i, side)] = bank.add(x, y, depth)

    for side in (0, 1):
        for i in range(n_panels):
            _add_member(members, seen, bottom[(i, side)], bottom[(i + 1, side)],
                        role='bottom_chord')
            _add_member(members, seen, top[(i, side)], top[(i + 1, side)],
                        role='top_chord')
        for i in range(n_panels + 1):
            _add_member(members, seen, bottom[(i, side)], top[(i, side)], role='vertical')
        for i in range(n_panels):
            if i % 2 == 0:
                _add_member(members, seen, bottom[(i, side)], top[(i + 1, side)],
                            role='diagonal')
            else:
                _add_member(members, seen, top[(i, side)], bottom[(i + 1, side)],
                            role='diagonal')

    # Cross-beams at every panel point, BOTH chord levels: the bottom
    # ones are where the roadway actually spans between the two edge
    # trusses; the top ones exist purely for stability -- without a
    # direct top(i,0)-top(i,1) member at each i, the top level's own
    # lateral X-braces (below) connect consecutive panel points only,
    # which makes each panel's own 4 top-level joints a plain 4-bar
    # loop (chord, brace, chord, brace, with no diagonal of ITS OWN) --
    # a textbook mechanism, not a rigid quadrilateral, and exactly what
    # produced a singular stiffness matrix before this member existed.
    for i in range(n_panels + 1):
        _add_member(members, seen, bottom[(i, 0)], bottom[(i, 1)], role='cross_beam')
        _add_member(members, seen, top[(i, 0)], top[(i, 1)], role='cross_beam')

    # Lateral X-bracing at both chord levels -- see this function's own
    # docstring for why it is required, not optional, for out-of-plane
    # (transverse) stability of the two truss planes together.
    for i in range(n_panels):
        _add_member(members, seen, bottom[(i, 0)], bottom[(i + 1, 1)], role='lateral_brace')
        _add_member(members, seen, bottom[(i, 1)], bottom[(i + 1, 0)], role='lateral_brace')
        _add_member(members, seen, top[(i, 0)], top[(i + 1, 1)], role='lateral_brace')
        _add_member(members, seen, top[(i, 1)], top[(i + 1, 0)], role='lateral_brace')

    support_candidates = [bottom[(0, 0)], bottom[(0, 1)],
                          bottom[(n_panels, 0)], bottom[(n_panels, 1)]]

    # Tributary area for a roadway (area) load, lumped onto the deck's
    # own bottom-chord panel points -- plan projection (width * panel
    # length per interior point, halved at the two ends), exact for a
    # flat deck, split evenly between the two edge trusses' own panel
    # points the way a real deck's own weight splits across both girders.
    load_nodes = {}
    for i in range(n_panels + 1):
        f_long = panel if 0 < i < n_panels else panel / 2.0
        area = f_long * width
        load_nodes[bottom[(i, 0)]] = area / 2.0
        load_nodes[bottom[(i, 1)]] = area / 2.0

    return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
            'load_nodes': load_nodes}


# ═══════════════════════════════════════════════════════════════════════
#  5 · Add-on features: column (shaft + capital) and reinforcement beam
# ═══════════════════════════════════════════════════════════════════════
#
# Unlike the generators above, these two AUGMENT an existing mesh
# (nodes/members already built by flat_grid/barrel_vault/dome) instead of
# building one from scratch -- they are the "add a feature to what's
# already there" tools a real space-frame designer reaches for once the
# base grid is in place.

def add_column(nodes, members, target_nodes, height, tiers=1):
    """Add a column supporting the mesh at `target_nodes`: a vertical SHAFT
    from a new ground-level node up to a new "head" node just below the
    surface, and a CAPITAL fanning from that head out to EVERY node in
    `target_nodes` -- the exact attachment points the caller (the UI's
    lasso selection) chose, not an automatically-guessed nearest-neighbour
    set. The capital is always literally a MODULAR EXTENSION of the grid
    it meets: it never invents its own geometry, it just fans the head
    (tiers=1) or a ring of intermediate nodes (tiers=2) out to whichever
    real grid nodes the caller selected.

    This is the standard space-frame column detail: a column landing on a
    single joint would concentrate its whole reaction (and, in the other
    direction, its whole point load) onto that one node -- "piercing" the
    space truss, well beyond what one joint and the handful of members
    meeting there are sized for. Fanning the head out to several
    neighbouring nodes through the capital spreads that force into the
    grid the way it is actually built to carry load, before it ever
    reaches any single node above the column.

    target_nodes : >= 3 existing node indices the capital attaches to
                   (e.g. every node of one or a few grid modules, selected
                   with a lasso box in the UI).
    height       : shaft length (m), from the new base node up to the head
                   (tiers=1) or the intermediate ring (tiers=2).
    tiers        : 1 (default) -- a single inverted-pyramid module: the
                   head fans DIRECTLY to every node in `target_nodes`, the
                   plain capital under one module's worth of load.
                   2 -- "two modules thick": for a heavier column that
                   would overwhelm a single-module transition, the capital
                   gets literally deeper as well as wider. `target_nodes`
                   is split into 4 angular quadrants around its own
                   centroid (each needs >= 2 nodes -- a real two-module
                   capital always has more than one module's worth of
                   attachment points); the head fans to one new
                   INTERMEDIATE node per quadrant (a smaller inner
                   pyramid), each intermediate node then fans on to its
                   own quadrant's target nodes (a second, outer pyramid
                   tier), and the intermediate nodes are tied to each
                   other in a ring. That ring is not optional bracing: a
                   quadrant's intermediate node otherwise has only 3
                   independent directions (the shaft-side leg plus its 2
                   target legs), which numbers out (Maxwell count) but
                   left the whole head+intermediates cluster 2 DOF short
                   of rigid at ordinary sizes -- found by eigenanalysis,
                   fixed by ONE tie between each pair of neighbouring
                   intermediate nodes.

    Returns (nodes, members, base_node, head_node) -- new lists, the
    mesh's own node/member lists are not mutated in place.
    """
    target_nodes = list(target_nodes)
    if len(target_nodes) < 3:
        raise ValueError('a capital needs at least 3 attachment nodes to distribute load usefully.')
    for j in target_nodes:
        if not (0 <= j < len(nodes)):
            raise ValueError(f'target node {j} does not exist.')
    if height <= 0:
        raise ValueError('height must be positive.')
    if tiers not in (1, 2):
        raise ValueError('tiers must be 1 or 2.')

    cx = sum(nodes[j][0] for j in target_nodes) / len(target_nodes)
    cy = sum(nodes[j][1] for j in target_nodes) / len(target_nodes)
    cz = sum(nodes[j][2] for j in target_nodes) / len(target_nodes)

    nodes = list(nodes)
    members = list(members)
    seen = {(min(m['a'], m['b']), max(m['a'], m['b'])) for m in members}

    # The head sits a short distance below the (average) attachment
    # surface -- never AT it, or the "shaft" would be zero-length -- so
    # the capital legs are genuinely inclined -- legs coplanar with the
    # attachment nodes would carry no vertical component at all.
    head_drop = min(0.3 * height, max(0.3, height))
    head = len(nodes)
    nodes.append((cx, cy, cz - head_drop))
    base = len(nodes)
    nodes.append((cx, cy, cz - head_drop - height))

    _add_member(members, seen, base, head, role='column_shaft')

    if tiers == 1:
        for j in target_nodes:
            _add_member(members, seen, head, j, role='capital')
        return nodes, members, base, head

    buckets = {}
    for j in target_nodes:
        x, y, _z = nodes[j]
        ang = math.atan2(y - cy, x - cx)
        q = int(((ang + math.pi) // (math.pi / 2.0)) % 4)
        buckets.setdefault(q, []).append(j)
    if len(buckets) < 3:
        raise ValueError('target nodes are too clustered/colinear for a 2-tier capital; '
                         'pick a wider, more evenly spread footprint.')
    for js in buckets.values():
        if len(js) < 2:
            raise ValueError('a 2-tier capital needs at least 2 target nodes per angular '
                             'quadrant around the footprint -- pick more nodes, spanning at '
                             'least two grid modules.')

    inter_by_q = {}
    for q, js in buckets.items():
        mx = sum(nodes[j][0] for j in js) / len(js)
        my = sum(nodes[j][1] for j in js) / len(js)
        mz = sum(nodes[j][2] for j in js) / len(js)
        inter_z = (nodes[head][2] + mz) / 2.0
        inter = len(nodes)
        nodes.append((mx, my, inter_z))
        inter_by_q[q] = inter
        _add_member(members, seen, head, inter, role='capital')
        for j in js:
            _add_member(members, seen, inter, j, role='capital')

    order = sorted(inter_by_q)
    for a, b in zip(order, order[1:] + order[:1]):
        _add_member(members, seen, inter_by_q[a], inter_by_q[b], role='capital_ring')

    return nodes, members, base, head


def reinforcement_beam(nodes, members, edge_a, edge_b, depth, direction=(0.0, 0.0, -1.0),
                       tiers=1):
    """Attach a linear space-truss reinforcement beam to TWO existing,
    parallel rows of nodes (`edge_a`, `edge_b` -- same length, each in
    order along the row, e.g. two adjacent bottom-chord rows of a
    flat_grid). Those two rows become the WIDE BASE of a triangular-
    cross-section truss girder -- already attached to the rest of the
    mesh through their own existing members -- and ONE new row of "apex"
    nodes, offset `depth` away along `direction`, is added and triangulated
    back to both rows. This is the real detail: the BASE (not a single new
    offset chord) does the attaching, matching how a triangular space-truss
    girder actually reinforces a roof/floor from below, base flush against
    the surface and the apex pointing away from it.

    An earlier version of this function instead reused a SINGLE existing
    row as the top chord and added two new chords below it -- structurally
    workable, but "upside down" relative to the real detail (narrow point
    at the grid, wide base hanging free) and it required the caller to
    hand-pick one already-straight row. Basing it on two existing rows
    both fixes the orientation and makes selection trivial: a lasso box
    dragged across two adjacent rows already contains everything needed.

    edge_a, edge_b : >= 2 existing node indices each, same length, in the
                     same order along the two rows (edge_a[k] and
                     edge_b[k] are the two ends of one cross-station).
    depth          : offset (m) from the rows' shared midline to the new
                     apex chord, along `direction`.
    direction      : (x, y, z) direction the apex is offset in;
                     normalized internally. The out-of-surface direction
                     (straight down/up off a roof) is the reliable choice
                     -- an in-plane direction can leave the beam
                     under-braced, the same way it did for the single-row
                     version.
    tiers          : 1 (default) -- a single apex row at `depth`, the
                     plain triangulated girder described above.
                     >= 2 -- MULTI-LAYER: `tiers` apex rows stacked at
                     depth*1/tiers, depth*2/tiers, ..., depth -- a taller,
                     stiffer girder for heavier loads, the same "make it
                     deeper, not just wider" idea as add_column's own
                     2-tier capital. Each tier independently gets the
                     EXACT SAME triangulation as the single-tier case
                     (its own web ties to edge_a/edge_b, its own chord,
                     its own both-direction X-bracing) -- never a
                     stripped-down or shared version of it -- so every
                     tier is already rigid on its own; the ties between
                     consecutive tiers only ADD stiffness on top of that,
                     never substitute for a tier's own bracing.

    Returns (nodes, members, apex_node_ids) -- apex_node_ids lists every
    tier's nodes in order (tier 1 first, closest to the base rows).
    """
    edge_a = list(edge_a)
    edge_b = list(edge_b)
    if len(edge_a) != len(edge_b):
        raise ValueError('edge_a and edge_b must be the same length.')
    if len(edge_a) < 2:
        raise ValueError('reinforcement_beam needs at least 2 stations to span.')
    for j in edge_a + edge_b:
        if not (0 <= j < len(nodes)):
            raise ValueError(f'edge node {j} does not exist.')
    dx, dy, dz = direction
    norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    if norm < 1e-9:
        raise ValueError('direction must be nonzero.')
    dx, dy, dz = dx / norm, dy / norm, dz / norm
    tiers = int(tiers)
    if tiers < 1:
        raise ValueError('tiers must be at least 1.')

    nodes = list(nodes)
    members = list(members)
    seen = {(min(m['a'], m['b']), max(m['a'], m['b'])) for m in members}

    n = len(edge_a)
    apex_tiers = []
    for t in range(1, tiers + 1):
        d_t = depth * t / tiers
        apex = []
        for k in range(n):
            ax, ay, az = nodes[edge_a[k]]
            bx, by, bz = nodes[edge_b[k]]
            mx, my, mz = (ax + bx) / 2.0, (ay + by) / 2.0, (az + bz) / 2.0
            apex.append(len(nodes))
            nodes.append((mx + dx * d_t, my + dy * d_t, mz + dz * d_t))
        apex_tiers.append(apex)

    for apex in apex_tiers:
        for k in range(n):
            _add_member(members, seen, edge_a[k], apex[k], role='reinf_web')
            _add_member(members, seen, edge_b[k], apex[k], role='reinf_web')
        for k in range(n - 1):
            _add_member(members, seen, edge_a[k], edge_a[k + 1], role='reinf_chord')
            _add_member(members, seen, edge_b[k], edge_b[k + 1], role='reinf_chord')
            _add_member(members, seen, apex[k], apex[k + 1], role='reinf_chord')
            # crossed bracing both ways per bay -- needed to stop the
            # whole apex chain from twisting about the base's own axis,
            # the same "spin" mechanism the single-row version needed
            # both-direction X-bracing to kill.
            _add_member(members, seen, edge_a[k], apex[k + 1], role='reinf_web')
            _add_member(members, seen, apex[k], edge_a[k + 1], role='reinf_web')
            _add_member(members, seen, edge_b[k], apex[k + 1], role='reinf_web')
            _add_member(members, seen, apex[k], edge_b[k + 1], role='reinf_web')

    # tie consecutive tiers together station by station -- pure ADDED
    # thickness/stiffness; each tier is already independently rigid above.
    for t in range(len(apex_tiers) - 1):
        for k in range(n):
            _add_member(members, seen, apex_tiers[t][k], apex_tiers[t + 1][k], role='reinf_web')

    return nodes, members, [a for tier in apex_tiers for a in tier]


# ═══════════════════════════════════════════════════════════════════════
#  6 · Custom surfaces: user-typed expressions + a domain/module wizard
# ═══════════════════════════════════════════════════════════════════════
#
# Two ways to DEFINE a surface (make_height_field_surface, a height field
# z = f(x, y); make_parametric_surface, a fully parametric x(u,v)/y(u,v)/
# z(u,v) triple -- needed for anything a height field cannot express, like
# a torus or a helicoid), both normalized to the SAME internal shape --
# a callable surface(p, q) -> (x, y, z) -- so every piece of machinery
# below (the domain lattice, the normal-offset double layer, the two-
# surface connector) is written once and works identically regardless of
# which way the surface was defined.
#
# Independently, a DOMAIN/MODULE wizard samples that callable into an
# actual mesh: a coordinate system (Cartesian or Polar) for the domain's
# (p, q) shape, a module PATTERN (square/diagonal/isometric) for how the
# sampled points connect, and either a 2D module (one layer, lying on the
# surface) or a 3D module (two layers, offset along the surface's own
# local normal by a fixed depth).

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


# ═══════════════════════════════════════════════════════════════════════
#  7 · Module editor: cell detection, role classification, and the
#      local-frame edits (move a node, toggle a member, set/lock a rod's
#      length, rescale) that propagate across every cell of the same role
# ═══════════════════════════════════════════════════════════════════════
#
# Deliberately GENERIC over the mesh's (nodes, members) alone -- not tied
# to any one generator's own (i, j)/(bi, ai) indexing -- so this works for
# every grid family (including a hand-edited or Excel-imported mesh) with
# no per-generator metadata to keep in sync. A "cell" here is a minimal
# 3- or 4-node closed circuit of existing members (a triangle or a quad);
# "role" groups cells that are congruent (the same multiset of edge
# lengths, and for quads the same diagonal lengths too) -- the same
# geometric shape repeated across the grid, regardless of which generator
# built it or what it happened to name the members' `role` field.

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


GENERATORS = {
    'flat_grid': flat_grid,
    'hypar_shell': hypar_shell,
    'hip_roof_grid': hip_roof_grid,
    'groin_vault': groin_vault,
    'circular_flat_grid': circular_flat_grid,
    'barrel_vault': barrel_vault,
    'parabolic_vault': parabolic_vault,
    'elliptic_vault': elliptic_vault,
    'dome': dome,
    'cone_roof': cone_roof,
    'paraboloid_dish': paraboloid_dish,
    'elliptic_dome': elliptic_dome,
    'sphere_shell': sphere_shell,
    'truss_bridge': truss_bridge,
    'custom_surface_grid': custom_surface_grid,
    'custom_surface_between': custom_surface_between,
}
