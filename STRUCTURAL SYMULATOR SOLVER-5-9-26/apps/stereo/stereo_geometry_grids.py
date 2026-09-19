"""Rectangular-plan double-layer space grids (family 1 of the Stereo
geometry library).

All four share flat_grid's own pyramidal-web bracing -- they differ only
in the height field fed to it, which is why a new rectangular-plan shape
is usually a ~10-line wrapper here rather than a new bracing scheme:

  flat_grid      -- flat roof (no height field at all)
  hip_roof_grid  -- a pyramidal hipped roof
  hypar_shell    -- a hyperbolic-paraboloid (saddle) shell
  groin_vault    -- a groin/cross vault, two crossing barrel profiles

See the package facade stereo_geometry.py for the mesh dict every one of
them returns, and tests/test_stereo_geometry.py for the "does it actually
analyze" check each one must pass.
"""
import math

from apps.stereo.stereo_geometry_core import _NodeBank, _add_chords, _add_member


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


def vierendeel_grid(span_x, span_y, depth, module, height_fn=None):
    """A double-layer VIERENDEEL space grid: two aligned chord layers joined
    by vertical posts, and no web diagonals anywhere.

    Every other family in this module triangulates: the webs make each
    module a tetrahedron or a half-octahedron, and the structure carries
    load by pure axial force in pin-jointed bars. This one deliberately does
    not. Its modules are rectangular boxes you can walk a duct, a walkway or
    a person through, which is the entire reason it exists and the reason it
    is worth the price.

    The price is real and is not optional. With pinned joints a rectangle of
    four bars is a mechanism -- it lozenges -- so this grid carries load by
    BENDING its members, and every member is tagged `conn='rigid'` and
    `rigid_required=True`. `rigid_required` is what stops the Section panel
    switching it back to pinned: the tag is not a preference, it is the
    difference between a frame and a pile of loose bars, and the solver
    reports the pinned version as a singular matrix rather than as a soft
    answer.

    Because it bends rather than stretching, a Vierendeel grid is
    substantially more flexible than a triangulated one of the same depth
    and section, and its members need I and J, not just E and A. Both facts
    are the designer's to weigh against the clear openings.

    Geometry: bottom nodes on the module grid at z=0 (or on `height_fn`), top
    nodes DIRECTLY above them at +depth, orthogonal chords in both layers,
    and one vertical post per node pair.
    """
    if span_x <= 0 or span_y <= 0:
        raise ValueError('span_x and span_y must both be positive.')
    if module <= 0:
        raise ValueError('module must be positive.')
    if depth <= 0:
        raise ValueError('depth must be positive.')

    nx = max(1, int(round(span_x / module)))
    ny = max(1, int(round(span_y / module)))
    dx, dy = span_x / nx, span_y / ny

    bank = _NodeBank()
    bottom, top = {}, {}
    for i in range(nx + 1):
        for j in range(ny + 1):
            x, y = i * dx, j * dy
            z0 = height_fn(x, y) if height_fn else 0.0
            bottom[(i, j)] = bank.add(x, y, z0)
            top[(i, j)] = bank.add(x, y, z0 + depth)

    members, seen = [], set()
    rigid = {'conn': 'rigid', 'rigid_required': True}
    for grid, role in ((bottom, 'bottom_chord'), (top, 'top_chord')):
        for i in range(nx + 1):
            for j in range(ny + 1):
                if i < nx:
                    _add_member(members, seen, grid[(i, j)], grid[(i + 1, j)],
                                role=role, **rigid)
                if j < ny:
                    _add_member(members, seen, grid[(i, j)], grid[(i, j + 1)],
                                role=role, **rigid)
    for ij in bottom:
        # The post is the ONLY thing between the two layers. In a
        # triangulated grid a purely vertical member would be useless -- no
        # horizontal stiffness at all -- which is exactly why the other
        # families never draw one. Here it is the web, and it works only
        # because its ends transfer moment.
        _add_member(members, seen, bottom[ij], top[ij], role='web', **rigid)

    support_candidates = sorted({bottom[(i, j)]
                                 for i in range(nx + 1) for j in range(ny + 1)
                                 if i in (0, nx) or j in (0, ny)})
    cell = dx * dy
    load_nodes = {}
    for (i, j), n in top.items():
        fx = 0.5 if i in (0, nx) else 1.0
        fy = 0.5 if j in (0, ny) else 1.0
        load_nodes[n] = cell * fx * fy
    return {'nodes': bank.nodes, 'members': members,
            'support_candidates': support_candidates, 'load_nodes': load_nodes}


def elliptic_paraboloid_shell(span_x, span_y, depth, module, rise,
                              offset=True, pattern='square'):
    """An ELLIPTIC-paraboloid ("elpar") double-layer shell -- the synclastic
    sibling of hypar_shell: a true quadratic dish

        z = rise * (1 - (u**2 + v**2) / 2),   u = 2(x-cx)/span_x in [-1, 1]
                                              v = 2(y-cy)/span_y in [-1, 1]

    which is `rise` at the plan centre and exactly ZERO at all four plan
    CORNERS -- the classic four-corner-supported sail roof. The two
    principal curvatures have the SAME sign everywhere (unlike a hypar's
    opposite pair), so the surface is a dome over a rectangle rather than
    a saddle, and it carries a uniform downward load largely in membrane
    COMPRESSION along both spans instead of splitting it into an arch and
    a cable direction.

    Note the corners, not the edges, are the level line: an elliptic
    paraboloid over a rectangle cannot have all four edges straight and
    level (a quadratic that is zero along a whole edge is zero along the
    parallel edge too). Halfway along each edge the surface stands
    rise/2 above the corners, which is the shape's own edge arch -- the
    reason a real elpar roof is edged with a stiffening beam or bears on
    four corner points only.

    rise : crown height (m) above the four corners.

    Returns the shared {'nodes','members','support_candidates'} dict.
    """
    rise = float(rise)
    cx, cy = float(span_x) / 2.0, float(span_y) / 2.0
    ax = cx if cx > 0 else 1.0
    ay = cy if cy > 0 else 1.0

    def height_fn(x, y):
        u = (x - cx) / ax
        v = (y - cy) / ay
        return rise * (1.0 - (u * u + v * v) / 2.0)

    return flat_grid(span_x, span_y, depth, module, offset=offset, pattern=pattern,
                     height_fn=height_fn)


def elliptic_hypar_shell(span_x, span_y, depth, module, rise_x, rise_y,
                         offset=True, pattern='square'):
    """An ELLIPTIC hyperbolic-paraboloid shell: the general saddle

        z = rise_x * u**2 - rise_y * v**2

    with INDEPENDENT principal curvatures along the two spans, where
    hypar_shell's own z = rise * u * v is the special (equal-and-opposite,
    45-degrees-rotated) case. This is the form an architect reaches for
    when the arch direction and the cable direction of a saddle roof are
    not meant to be equally curved -- a deep arch across a short span with
    a shallow suspension along a long one, say.

    Each u = const line is a downward parabola and each v = const line an
    upward one, so the surface arches along y and hangs along x: a uniform
    downward load goes into COMPRESSION along the arching direction and
    TENSION along the hanging one, which is the whole structural argument
    for a saddle and the reason it needs no bending stiffness to be stiff.

    Unlike hypar_shell this form is NOT ruled unless rise_x == rise_y, so
    its grid lines are genuine curves; the mesh chords are their secants,
    the same discretisation every other curved family here uses.

    rise_x : half-height (m) the surface climbs along x at the plan edge.
    rise_y : half-depth (m) it falls along y at the plan edge.

    Returns the shared {'nodes','members','support_candidates'} dict.
    """
    rise_x = float(rise_x); rise_y = float(rise_y)
    cx, cy = float(span_x) / 2.0, float(span_y) / 2.0
    ax = cx if cx > 0 else 1.0
    ay = cy if cy > 0 else 1.0

    def height_fn(x, y):
        u = (x - cx) / ax
        v = (y - cy) / ay
        return rise_x * u * u - rise_y * v * v

    return flat_grid(span_x, span_y, depth, module, offset=offset, pattern=pattern,
                     height_fn=height_fn)


def conoid_shell(span_x, span_y, depth, module, rise, offset=True, pattern='square'):
    """A CONOID shell -- the ruled surface swept by a straight line that
    slides along a straight directrix at y=0 while its other end rides an
    arch at y=span_y, staying parallel to a fixed plane throughout:

        z = rise * sin(pi * x / span_x) * (y / span_y)

    At y=0 the surface is a straight, level edge; at y=span_y it is a full
    sine arch of height `rise`. Every line of constant x is STRAIGHT (z is
    linear in y), which is what makes it a ruled surface and why Candela,
    Gaudi and the whole mid-century shell-concrete tradition used conoids
    so heavily: the formwork, and here every y-direction chord, is a
    straight member.

    Structurally it is the single-curvature-to-double-curvature transition
    in one roof: stiff and arch-like at the tall edge, flat and
    bending-dependent at the straight one, which is why a conoid is
    normally used in repeated bays with the straight edges meeting -- a
    north-light saw-tooth roof being the textbook case.

    rise : height (m) of the arch at the y = span_y edge.

    Returns the shared {'nodes','members','support_candidates'} dict.
    """
    rise = float(rise)
    sx = float(span_x) if span_x > 0 else 1.0
    sy = float(span_y) if span_y > 0 else 1.0

    def height_fn(x, y):
        return rise * math.sin(math.pi * x / sx) * (y / sy)

    return flat_grid(span_x, span_y, depth, module, offset=offset, pattern=pattern,
                     height_fn=height_fn)


def monkey_saddle_shell(span_x, span_y, depth, module, rise,
                        offset=True, pattern='square'):
    """A MONKEY SADDLE shell: the cubic surface

        z = rise * (u**3 - 3 * u * v**2)

    -- a saddle with THREE falls and three rises around its centre rather
    than an ordinary saddle's two of each (the name is the old joke that
    it has a place for the tail as well as the two legs). It is the real
    part of the complex cube, so its level set through the centre is three
    straight lines at 60 degrees, and it is the simplest surface whose
    centre is a MONKEY POINT: both principal curvatures vanish there at
    once, so the middle of the roof is locally FLAT to second order.

    That flat point is the structural story and the reason this belongs in
    the list as a cautionary shape as much as a sculptural one: a doubly
    curved shell is stiff because its curvature turns membrane force into
    vertical support, and at a monkey point there is no curvature to do
    it. Expect the centre to be much the softest part of the roof and to
    depend on the grid's own depth rather than on shell action -- run
    Analyze and look at the centre deflection before committing to one.

    rise : amplitude (m); the surface reaches +/- 2*rise at the plan
           corners, where u**3 - 3*u*v**2 is +/-2.

    Returns the shared {'nodes','members','support_candidates'} dict.
    """
    rise = float(rise)
    cx, cy = float(span_x) / 2.0, float(span_y) / 2.0
    ax = cx if cx > 0 else 1.0
    ay = cy if cy > 0 else 1.0

    def height_fn(x, y):
        u = (x - cx) / ax
        v = (y - cy) / ay
        return rise * (u ** 3 - 3.0 * u * v * v)

    return flat_grid(span_x, span_y, depth, module, offset=offset, pattern=pattern,
                     height_fn=height_fn)


def wave_shell(span_x, span_y, depth, module, rise, waves=2.0,
               offset=True, pattern='square'):
    """A SINUSOIDAL WAVE shell -- a corrugated roof whose section across x
    is a cosine and which is straight along y:

        z = rise * (1 - cos(2*pi * waves * x / span_x)) / 2

    so the roof touches z=0 at every trough and reaches `rise` at every
    crest, with `waves` full waves across the span. Set waves=1.5 or 2.5
    for a roof that starts and ends on a crest, or an integer for one that
    starts and ends in a trough (where the supports naturally go).

    This is the shape of the modern folded/undulating shell roof -- the
    Bosjes Chapel's white shell being the best-known recent one -- and it
    is a genuinely efficient one: each trough-to-trough arch spans in x by
    ARCH ACTION, and the alternation of crests and troughs gives the whole
    roof a corrugation depth far larger than the grid's own, which is why
    such a roof can be very thin and still span a long way. Supporting it
    only at the troughs, as the built examples do, is the point: each wave
    is then a free-standing arch and the crests fly.

    Being a single-curvature (developable) surface, it has no stiffness at
    all ACROSS the waves beyond what the grid's depth provides -- the y
    direction is dead straight. A real one gets an edge arch or a diaphragm
    at each end for exactly that reason.

    rise  : crest height (m) above the troughs.
    waves : number of full cosine waves across span_x (may be fractional).

    Returns the shared {'nodes','members','support_candidates'} dict.
    """
    rise = float(rise)
    waves = float(waves)
    sx = float(span_x) if span_x > 0 else 1.0

    def height_fn(x, y):
        return rise * (1.0 - math.cos(2.0 * math.pi * waves * x / sx)) / 2.0

    return flat_grid(span_x, span_y, depth, module, offset=offset, pattern=pattern,
                     height_fn=height_fn)


def billow_shell(span_x, span_y, depth, module, rise, waves_x=2.0, waves_y=2.0,
                 offset=True, pattern='square'):
    """A BILLOWING (two-way wave) shell -- the cloth-pinned-at-its-low-points
    roof, of which the Bosjes Chapel is the best-known built example:

        z = rise * cos(pi * waves_x * (x-cx)/span_x)
                 * cos(pi * waves_y * (y-cy)/span_y)

    It is the doubly curved sibling of wave_shell, and the difference is the
    whole point of having both. wave_shell corrugates in ONE direction and
    is dead straight along the other -- a developable surface, stiff across
    the waves and relying on the grid's own depth along them. This one waves
    in BOTH, so every point of it has curvature in two directions at once
    and the roof carries load by genuine shell action everywhere rather than
    as a row of parallel arches.

    `waves_x` and `waves_y` count HALF waves across each span, and the count
    is what picks the roof out of the family:

      1, 1  a single bubble, zero all the way round the plan edge -- a
            square sail or a lifted canopy.
      2, 2  the chapel configuration: the surface touches z = 0 along the
            lines a quarter and three quarters across each span, dips to
            -rise at the MIDDLE OF EACH EDGE, and rises to +rise at all four
            CORNERS and again at the centre. Those four edge-midpoint lows
            are where such a roof comes to the ground, and supporting it
            there and nowhere else is what makes the corners fly.
      3, 2  and so on: an egg-crate of alternating hills and hollows, the
            long-span industrial version of the same surface.

    A fractional count is allowed and is how a roof is made to start and
    stop mid-wave -- waves_x=1.5 gives a high edge at one end and a low one
    at the other.

    Structurally the alternating hills and hollows are the reason this shape
    is worth building: each hollow is an arch spanning between its two
    neighbouring highs in BOTH directions, so the effective structural depth
    is the full crest-to-trough amplitude rather than the depth of the grid,
    and the surface has no straight line in it anywhere to unroll along.
    The price is that the membrane forces change sign between hill and
    hollow, so the reversal lines -- where z crosses zero -- are where the
    chords swap from tension to compression and are worth looking at in the
    Analyse colours before sizing anything.

    rise    : the crest height (m) above the mean plane; the hollows go the
              same distance below it, so the full amplitude is 2 * rise.
    waves_x,
    waves_y : half waves across each span (may be fractional).

    Returns the shared {'nodes','members','support_candidates'} dict. Note
    that `support_candidates` is flat_grid's own plan perimeter, which for
    the 2, 2 case includes BOTH the four edge-midpoint lows the roof really
    stands on AND the corners it is meant to cantilever out to -- supporting
    the whole perimeter turns the corners from flying to held, which is a
    different building. Use the Support panel to keep the lows.
    """
    rise = float(rise)
    waves_x = float(waves_x); waves_y = float(waves_y)
    sx = float(span_x) if span_x > 0 else 1.0
    sy = float(span_y) if span_y > 0 else 1.0
    cx, cy = sx / 2.0, sy / 2.0

    def height_fn(x, y):
        return (rise * math.cos(math.pi * waves_x * (x - cx) / sx)
                     * math.cos(math.pi * waves_y * (y - cy) / sy))

    return flat_grid(span_x, span_y, depth, module, offset=offset, pattern=pattern,
                     height_fn=height_fn)
