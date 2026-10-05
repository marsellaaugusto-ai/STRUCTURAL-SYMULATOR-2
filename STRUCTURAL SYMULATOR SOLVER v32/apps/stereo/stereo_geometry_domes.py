"""Round-plan (axisymmetric) shells and grids (family 3 of the Stereo
geometry library).

The ribbed shells all share _add_apex_ribbed_shell: one apex, `n_rings`
hoop rings, and one Schwedler diagonal per panel, exactly as a Schwedler
dome is built. That bracing is purely TOPOLOGICAL -- it never references
the actual ring coordinates -- so the same connectivity dome() was
validated with across n_rings x n_sectors sweeps applies unchanged to any
differently-shaped meridian profile:

  dome            -- spherical cap
  cone_roof       -- straight-line (conical) meridian
  paraboloid_dish -- antenna/reflector paraboloid
  elliptic_dome   -- ellipsoid cap
  sphere_shell    -- a full sphere (two poles)

circular_flat_grid closes the file: a round-plan FLAT double-layer grid
with its own polar pyramidal-web bracing -- rings without an apex, so it
does not use the Schwedler helper above.
"""
import math

from apps.stereo.stereo_geometry_core import _NodeBank, _add_member


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
