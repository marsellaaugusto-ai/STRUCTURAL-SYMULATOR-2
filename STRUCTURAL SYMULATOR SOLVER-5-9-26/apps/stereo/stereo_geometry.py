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

def flat_grid(span_x, span_y, depth, module, offset=True):
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
                     above one another; webs are the four diagonals from
                     each bottom node up to its four neighbouring top
                     nodes (a pyramid opening upward), which is the other
                     configuration seen in practice and needs explicit
                     diagonals since aligned layers do not triangulate on
                     their own.

    Returns the shared {'nodes','members','support_candidates'} dict.
    `support_candidates` is every bottom-layer perimeter node.
    """
    span_x = float(span_x); span_y = float(span_y)
    depth = float(depth); module = float(module)
    if module <= 0 or span_x <= 0 or span_y <= 0:
        raise ValueError('span_x, span_y and module must all be positive')

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
    for j in range(ny + 1):
        for i in range(nx):
            _add_member(members, seen, bottom[(i, j)], bottom[(i + 1, j)], role='bottom_chord')
    for j in range(ny):
        for i in range(nx + 1):
            _add_member(members, seen, bottom[(i, j)], bottom[(i, j + 1)], role='bottom_chord')

    # top chords
    if offset:
        for j in range(ny):
            for i in range(nx - 1):
                _add_member(members, seen, top[(i, j)], top[(i + 1, j)], role='top_chord')
        for j in range(ny - 1):
            for i in range(nx):
                _add_member(members, seen, top[(i, j)], top[(i, j + 1)], role='top_chord')
    else:
        for j in range(ny + 1):
            for i in range(nx):
                _add_member(members, seen, top[(i, j)], top[(i + 1, j)], role='top_chord')
        for j in range(ny):
            for i in range(nx + 1):
                _add_member(members, seen, top[(i, j)], top[(i, j + 1)], role='top_chord')

    # webs (diagonals)
    if offset:
        for j in range(ny):
            for i in range(nx):
                t = top[(i, j)]
                for bi, bj in ((i, j), (i + 1, j), (i, j + 1), (i + 1, j + 1)):
                    _add_member(members, seen, t, bottom[(bi, bj)], role='web')
    else:
        for j in range(ny):
            for i in range(nx):
                b_corners = (bottom[(i, j)], bottom[(i + 1, j)],
                             bottom[(i, j + 1)], bottom[(i + 1, j + 1)])
                t_corners = (top[(i, j)], top[(i + 1, j)],
                             top[(i, j + 1)], top[(i + 1, j + 1)])
                for bcorner, tcorner in zip(b_corners, t_corners):
                    _add_member(members, seen, bcorner, tcorner, role='web')
                # aligned layers do not triangulate through verticals alone;
                # add one plan diagonal per bottom cell so the grid is not a
                # mechanism in-plane.
                _add_member(members, seen, bottom[(i, j)], bottom[(i + 1, j + 1)], role='plan_brace')

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
        # t in [-1, 1] across the span; y is up (rise direction), z is the
        # cross-section coordinate; x is the longitudinal (bay) direction.
        ang = t * half_angle
        y = cz + radius * math.cos(ang)
        z = radius * math.sin(ang)
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
    else:
        # single layer: brace every bay face with one diagonal so the
        # structure does not rack longitudinally.
        for bi in range(n_bays):
            for ai in range(n_arch):
                _add_member(members, seen, outer[(bi, ai)], outer[(bi + 1, ai + 1)], role='brace')

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


GENERATORS = {
    'flat_grid': flat_grid,
    'barrel_vault': barrel_vault,
    'dome': dome,
}
