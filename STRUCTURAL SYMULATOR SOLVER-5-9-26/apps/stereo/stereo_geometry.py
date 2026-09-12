"""Geometry generators for the Stereo (3D space-structure) tab.

"Estructura estéreo" covers several real-world families of bolted/welded
space structures that are otherwise built as separate, incompatible
programs: flat double-layer space grids (MERO/Nodus-type roofs), barrel
vaults, and ribbed (Schwedler-type) domes. The point of this module is to
generate all of them through ONE shared node/member representation so the
Stereo tab can offer a single generator panel that simply changes which
function is called, rather than one app per typology.

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

def flat_grid(span_x, span_y, depth, module, offset=True, pattern='square'):
    """A rectangular double-layer flat space grid (the classic MERO/Nodus
    roof lattice): a bottom chord layer on a square grid at z=0, a top
    chord layer at z=depth, and diagonal webs between them.

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

    Returns the shared {'nodes','members','support_candidates'} dict.
    `support_candidates` is every bottom-layer perimeter node.
    """
    span_x = float(span_x); span_y = float(span_y)
    depth = float(depth); module = float(module)
    if module <= 0 or span_x <= 0 or span_y <= 0:
        raise ValueError('span_x, span_y and module must all be positive')
    if pattern not in ('square', 'diagonal'):
        raise ValueError(f"pattern must be 'square' or 'diagonal', got {pattern!r}")

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
            bottom[(i, j)] = bank.add(i * dx, j * dy, 0.0)

    top = {}
    if offset:
        for j in range(ny):
            for i in range(nx):
                x = (i + 0.5) * dx
                y = (j + 0.5) * dy
                top[(i, j)] = bank.add(x, y, depth)
    else:
        for j in range(ny + 1):
            for i in range(nx + 1):
                top[(i, j)] = bank.add(i * dx, j * dy, depth)

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


# ═══════════════════════════════════════════════════════════════════════
#  2 · Barrel vault (single or double layer)
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
    every node on the two end arches (the vault's supported edges in the
    usual arrangement) offered as support candidates.
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
        # Single layer: X-brace (both diagonals) every bay panel. A single
        # diagonal per panel is enough for a FLAT grid cell (flat_grid's
        # 'square' pattern), but even a FULL X-brace here still left a
        # real mechanism at every INTERIOR bay's springing line -- found by
        # eigenanalysis (zero eigenvalues, and every member's elongation
        # under the mode was exactly zero, confirming a true unbraced DOF
        # rather than mere ill-conditioning). The reason is geometric, not
        # a missing member count: y and z here depend only on `ai`, so
        # EVERY member that steps by the same delta-ai (an outer_rib, or a
        # brace which steps delta-ai=1 and delta-bi=1 at once) has the
        # exact same (y, z) projection regardless of `bi` -- i.e. ribs and
        # braces at a given station are all parallel when flattened onto
        # the arc's own cross-sectional plane. A springing node (ai=0 or
        # ai=n_arch) only ever reaches ONE step in `ai` (there is no
        # ai=-1), so it gets exactly one independent in-plane direction
        # from its rib/braces -- leaving the direction perpendicular to it
        # (radially in or out of the shell) completely unresisted, unless
        # the node is itself a support (true only at the two END bays).
        # The fix: give every interior bay's springing node a SECOND,
        # non-parallel direction by also bracing it two stations in
        # (skipping ai=1) -- a chord across two unequal arc steps is not
        # parallel to a chord across one, which is exactly the missing
        # direction.
        for bi in range(n_bays):
            for ai in range(n_arch):
                _add_member(members, seen, outer[(bi, ai)], outer[(bi + 1, ai + 1)], role='brace')
                _add_member(members, seen, outer[(bi + 1, ai)], outer[(bi, ai + 1)], role='brace')
        _edge_brace(outer)

    support_candidates = sorted(set(outer[(0, ai)] for ai in range(n_arch + 1))
                                 | set(outer[(n_bays, ai)] for ai in range(n_arch + 1)))
    if double_layer and depth > 0:
        support_candidates = sorted(set(support_candidates)
                                     | set(inner[(0, ai)] for ai in range(n_arch + 1))
                                     | set(inner[(n_bays, ai)] for ai in range(n_arch + 1)))

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


# ═══════════════════════════════════════════════════════════════════════
#  3 · Ribbed (Schwedler-type) dome
# ═══════════════════════════════════════════════════════════════════════

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

    # meridian ribs
    for s in range(n_sectors):
        _add_member(members, seen, apex, rings[0][s], role='meridian')
        for k in range(n_rings - 1):
            _add_member(members, seen, rings[k][s], rings[k + 1][s], role='meridian')

    # hoop rings
    for k in range(n_rings):
        ring = rings[k]
        n = len(ring)
        for s in range(n):
            _add_member(members, seen, ring[s], ring[(s + 1) % n], role='hoop')

    # Schwedler diagonals: one per panel, alternating direction ring to ring
    # so consecutive rings brace against opposite racking senses.
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


# ═══════════════════════════════════════════════════════════════════════
#  4 · Add-on features: column (shaft + capital) and reinforcement beam
# ═══════════════════════════════════════════════════════════════════════
#
# Unlike the three generators above, these two AUGMENT an existing mesh
# (nodes/members already built by flat_grid/barrel_vault/dome) instead of
# building one from scratch -- they are the "add a feature to what's
# already there" tools a real space-frame designer reaches for once the
# base grid is in place.

def add_column(nodes, members, target_node, height, n_legs=4):
    """Add a column supporting the mesh at `target_node`: a vertical SHAFT
    from a new ground-level node up to a new "head" node just below the
    surface, and a CAPITAL of `n_legs` short raking members fanning from
    that head out to `target_node`'s existing neighbours in the mesh.

    This is the standard space-frame column detail: a column landing on a
    single joint would concentrate its whole reaction (and, in the other
    direction, its whole point load) onto that one node -- "piercing" the
    space truss, well beyond what one joint and the handful of members
    meeting there are sized for. Fanning the head out to several
    neighbouring nodes through the capital spreads that force into the
    grid the way it is actually built to carry load, before it ever
    reaches the single node above the column.

    height  : shaft length (m), from the new base node up to the head.
    n_legs  : how many of target_node's existing mesh-neighbours the
              capital connects to (nearest first). Must be <= the number
              of members already meeting at target_node -- a capital
              cannot fan out to neighbours that do not exist.

    Returns (nodes, members, base_node, head_node) -- new lists, the
    mesh's own node/member lists are not mutated in place.
    """
    if not (0 <= target_node < len(nodes)):
        raise ValueError(f'target_node {target_node} does not exist.')
    if height <= 0:
        raise ValueError('height must be positive.')
    if n_legs < 3:
        raise ValueError('a capital needs at least 3 legs to distribute load usefully.')

    neighbour_ids = sorted(
        {m['a'] if m['b'] == target_node else m['b']
         for m in members if target_node in (m['a'], m['b'])},
        key=lambda j: math.dist(nodes[j][:2], nodes[target_node][:2]))
    if len(neighbour_ids) < n_legs:
        raise ValueError(f'target_node {target_node} only has {len(neighbour_ids)} '
                         f'mesh neighbour(s); need at least {n_legs} for a {n_legs}-leg capital.')
    legs = neighbour_ids[:n_legs]

    tx, ty, tz = nodes[target_node]
    nodes = list(nodes)
    members = list(members)
    seen = {(min(m['a'], m['b']), max(m['a'], m['b'])) for m in members}

    # The head sits a short distance below the surface (never AT it, or
    # the "shaft" would be zero-length) so the capital legs are genuinely
    # inclined -- horizontal legs (head in the same plane as target_node)
    # would carry no vertical component at all.
    head_drop = min(0.3 * height, max(0.3, height))
    head_z = tz - head_drop
    head = len(nodes)
    nodes.append((tx, ty, head_z))
    base = len(nodes)
    nodes.append((tx, ty, head_z - height))

    _add_member(members, seen, base, head, role='column_shaft')
    for j in legs:
        _add_member(members, seen, head, j, role='capital')

    return nodes, members, base, head


def reinforcement_beam(nodes, members, edge_nodes, depth, direction=(0.0, 0.0, -1.0), width=None):
    """Attach a linear space-truss reinforcement beam along an existing
    run of `edge_nodes` (given in order along the line to reinforce).

    Space-truss beams reinforce part of a larger grid by attaching "the
    same type of structure... in a linear fashion": the existing edge_nodes
    become the beam's single TOP chord, and TWO new longitudinal chords
    ("left"/"right") run `depth` away from it, offset to either side of the
    edge by `width`. Every station forms a genuine, non-degenerate 3D
    triangle (edge[k], left[k], right[k]) -- not just a flat zig-zag in the
    plane of the edge -- and consecutive triangles are tied by both new
    chords plus a crossed pair of diagonals per bay, giving the classic
    triangulated ("tetrahedral") 3-chord space-truss girder cross-section
    used for real linear reinforcement/gantry beams. That triangulation is
    NOT optional decoration: an earlier version of this function offset a
    SINGLE new chord straight down from the edge -- with every new node and
    every new member confined to the one plane containing the (straight or
    gently curved) edge and the offset direction, that geometry is a true
    3D mechanism (zero-energy out-of-plane mode) REGARDLESS of how the
    single chord's own bracing is arranged, caught by
    test_generated_mesh_with_a_reinforcement_beam_analyzes_cleanly.

    edge_nodes : >= 2 existing node indices, in order along the line to
                 reinforce (e.g. one boundary row of a flat_grid, or a
                 barrel_vault springing line). Works best for a straight or
                 gently curved run; a very tightly curved one (e.g. a small
                 arc of a dome's own ring) can still leave a soft mode --
                 the same "pick a sensible edge" judgment a real designer
                 would make attaching a stiffening truss.
    depth      : offset (m) from the edge to the new chords, along
                 `direction`.
    direction  : (x, y, z) direction the new chords are offset in;
                 normalized internally. Must not run parallel to the
                 edge's own local direction anywhere along its length (a
                 beam cannot be offset "along itself") -- raises
                 ValueError if it does. The out-of-plane direction (e.g.
                 straight down/up off a roof edge) is the reliable choice;
                 an in-plane direction can leave the beam under-braced.
    width      : lateral separation (m) between the "left" and "right"
                 chords; defaults to `depth` (a roughly square cross-
                 section, typical of real linear space-truss girders).

    Returns (nodes, members, new_chord_node_ids) -- left chord node ids
    followed by right chord node ids, both in edge_nodes order.
    """
    if len(edge_nodes) < 2:
        raise ValueError('reinforcement_beam needs at least 2 edge nodes to span.')
    for j in edge_nodes:
        if not (0 <= j < len(nodes)):
            raise ValueError(f'edge node {j} does not exist.')
    dx, dy, dz = direction
    norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    if norm < 1e-9:
        raise ValueError('direction must be nonzero.')
    dx, dy, dz = dx / norm, dy / norm, dz / norm
    if width is None:
        width = depth

    nodes = list(nodes)
    members = list(members)
    seen = {(min(m['a'], m['b']), max(m['a'], m['b'])) for m in members}

    n = len(edge_nodes)
    laterals = []
    for k in range(n):
        lo, hi = max(k - 1, 0), min(k + 1, n - 1)
        ax, ay, az = nodes[edge_nodes[lo]]
        bx, by, bz = nodes[edge_nodes[hi]]
        tx, ty, tz = bx - ax, by - ay, bz - az
        lx = ty * dz - tz * dy
        ly = tz * dx - tx * dz
        lz = tx * dy - ty * dx
        lnorm = math.sqrt(lx * lx + ly * ly + lz * lz)
        if lnorm < 1e-9:
            raise ValueError(f'direction runs parallel to the edge at node {edge_nodes[k]}; '
                             'pick a direction that is not along the edge itself.')
        laterals.append((lx / lnorm, ly / lnorm, lz / lnorm))

    left, right = [], []
    for k, j in enumerate(edge_nodes):
        x, y, z = nodes[j]
        lx, ly, lz = laterals[k]
        left.append(len(nodes))
        nodes.append((x + dx * depth + lx * width / 2.0,
                     y + dy * depth + ly * width / 2.0,
                     z + dz * depth + lz * width / 2.0))
        right.append(len(nodes))
        nodes.append((x + dx * depth - lx * width / 2.0,
                     y + dy * depth - ly * width / 2.0,
                     z + dz * depth - lz * width / 2.0))

    for k, j in enumerate(edge_nodes):
        _add_member(members, seen, j, left[k], role='reinf_web')
        _add_member(members, seen, j, right[k], role='reinf_web')
        _add_member(members, seen, left[k], right[k], role='reinf_web')
    for k in range(n - 1):
        _add_member(members, seen, left[k], left[k + 1], role='reinf_chord')
        _add_member(members, seen, right[k], right[k + 1], role='reinf_chord')
        _add_member(members, seen, left[k], right[k + 1], role='reinf_web')
        _add_member(members, seen, right[k], left[k + 1], role='reinf_web')

    return nodes, members, left + right


GENERATORS = {
    'flat_grid': flat_grid,
    'barrel_vault': barrel_vault,
    'dome': dome,
}
