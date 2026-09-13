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
