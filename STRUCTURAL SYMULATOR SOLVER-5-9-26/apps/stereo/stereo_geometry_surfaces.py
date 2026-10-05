"""Revolved and swept shells (family 6 of the Stereo geometry library).

The four shapes here are the ones a rectangular plan cannot express at
all, because their own natural parameter is an ANGLE that closes back on
itself or winds past a full turn:

  hyperboloid_tower     -- a ruled hyperboloid of revolution (Shukhov)
  elliptic_hyperboloid  -- the same surface with two different plan radii
  torus_segment         -- a barrel vault bent round in plan (a ring vault)
  helicoid_ramp         -- a helicoidal deck: a spiral ramp or stair

See the package facade stereo_geometry.py for the mesh dict every one of
them returns, and tests/test_stereo_geometry.py for the "does it actually
analyze" check each one must pass.

THE RULED HYPERBOLOID, AND WHY ITS MEMBERS ARE EXACTLY STRAIGHT
---------------------------------------------------------------
A hyperboloid of ONE SHEET is doubly ruled: through every point of it run
two straight lines that lie entirely IN the surface. That is why Shukhov
could build a curved tower out of nothing but straight angle sections in
1896, and it is why this family is worth having even though a dome or a
cone is easier to describe -- every diagonal member of the lattice below
lies on the surface EXACTLY, not as a secant chord approximating a curve
the way every other curved family in this library must.

Getting that exactly right, rather than nearly right, takes one specific
node layout. Write the surface as

    x = a*cosh(w)*cos(phi),  y = b*cosh(w)*sin(phi),  z = c*sinh(w)

and its two generator families are the curves phi -/+ gd(w) = const, with
gd(w) = arctan(sinh w) the Gudermannian. So if the rings are placed at
EQUAL STEPS OF gd(w) -- not equal steps of height, and not equal steps of
w -- and each ring is rotated by exactly that same step, then:

  * ring i sits at psi_i = psi_0 + i*dpsi, with plan radius a/cos(psi_i)
    (by a=b, b/cos(psi_i)) and height c*tan(psi_i);
  * the chord from node (i, j) to node (i+1, j) is an exact generator of
    one family;
  * and, provided dpsi is a whole number of sectors (dpsi = twist*pi/
    n_sectors), the chord from (i, j) to (i+1, j-1) is an exact generator
    of the OTHER family -- the mirror image of the first through a plane
    containing the axis, which maps the surface and its generators onto
    themselves and lands exactly back on the node set.

That whole-number-of-sectors condition is why `twist` is an integer count
of sectors per ring here rather than a free angle: at any other value the
left-handed lines would miss the nodes and the lattice would have to fall
back to secant chords, losing the one property the shape was chosen for.
tests/test_stereo_geometry.py checks the straightness directly, to about
1e-9 m of deviation, for both families.

The elliptic version is the circular one scaled by different factors in x
and y. An affine map takes straight lines to straight lines, so BOTH
generator families survive the squash exactly, and an elliptic
hyperboloid of one sheet is doubly ruled for the same reason the circular
one is.
"""
import math

from apps.stereo.stereo_geometry_core import _NodeBank, _add_member
from apps.stereo.stereo_geometry_custom_surface import (
    _boundary_nodes, _surface_chords, _surface_webs,
)


# ═══════════════════════════════════════════════════════════════════════
#  1 · Ruled hyperboloid of one sheet (circular and elliptic)
# ═══════════════════════════════════════════════════════════════════════

BRACE_COUNTER = 'counter'
BRACE_RING = 'ring'
BRACE_NONE = 'none'
HYPERBOLOID_BRACES = (BRACE_COUNTER, BRACE_RING, BRACE_NONE)


def _hyperboloid_lattice(radius_x, radius_y, height, n_rings, n_sectors, twist,
                         brace=BRACE_COUNTER):
    """The shared engine for hyperboloid_tower and elliptic_hyperboloid: a
    single-layer diagrid on a hyperboloid of one sheet whose diagonals are
    EXACT straight generators (see the module docstring for the geometry).

    Returns the shared {'nodes','members','support_candidates','load_nodes'}
    dict. `support_candidates` is the bottom ring -- a free-standing tower
    bears on its base ring and nothing else.
    """
    radius_x = float(radius_x); radius_y = float(radius_y); height = float(height)
    n_rings = max(2, int(n_rings)); n_sectors = max(3, int(n_sectors))
    twist = max(1, int(twist))
    if brace not in HYPERBOLOID_BRACES:
        raise ValueError(f'brace must be one of {HYPERBOLOID_BRACES}, got {brace!r}')
    if radius_x <= 0 or radius_y <= 0:
        raise ValueError('both waist radii must be positive')
    if height <= 0:
        raise ValueError('height must be positive')

    # The half-sweep of the Gudermannian angle. At pi/2 the surface has
    # flared to an infinite radius, so the lattice must stop short of it;
    # refusing here beats handing the solver a tower whose top ring is
    # thousands of metres across.
    dpsi = twist * math.pi / n_sectors
    psi_max = n_rings * dpsi / 2.0
    if psi_max >= math.pi / 2.0 - 1e-9:
        raise ValueError(
            f'rings x twist is too large for {n_sectors} sectors: the flare '
            f'angle reaches {math.degrees(psi_max):.1f} deg and the surface '
            f'is only defined below 90. Use fewer rings, less twist, or more '
            f'sectors.')
    c = (height / 2.0) / math.tan(psi_max)

    bank = _NodeBank()
    rings = []
    for i in range(n_rings + 1):
        psi = -psi_max + i * dpsi
        flare = 1.0 / math.cos(psi)
        z = c * math.tan(psi) + height / 2.0
        ring = []
        for j in range(n_sectors):
            phi = 2.0 * math.pi * j / n_sectors + psi
            ring.append(bank.add(radius_x * flare * math.cos(phi),
                                 radius_y * flare * math.sin(phi), z))
        rings.append(ring)

    members = []
    seen = set()
    for i, ring in enumerate(rings):
        for j in range(n_sectors):
            _add_member(members, seen, ring[j], ring[(j + 1) % n_sectors], role='hoop')
            if i < n_rings:
                # The two exact generator families. 'meridian' is the
                # library's role for a member running up the surface, and
                # both of these do, one handed each way.
                # Right-handed: phi - psi is constant along it, i.e. the
                # sector index does not change. Left-handed: phi + psi is
                # constant, so the sector index drops by exactly `twist`
                # per course -- NOT by one, which is only the same thing
                # when twist is 1.
                _add_member(members, seen, ring[j], rings[i + 1][j], role='meridian')
                _add_member(members, seen, ring[j], rings[i + 1][(j - twist) % n_sectors],
                            role='meridian')

    # The two generator families plus one hoop per node put this lattice
    # EXACTLY on the Maxwell count, and an exactly-critical truss is the
    # one case where the count tells you nothing: measured on the
    # compatibility matrix, the bare lattice has precisely n_rings
    # inextensional mechanisms (one per ring course) and an equal number
    # of self-stress states -- see
    # tests/test_stereo_geometry.py::test_the_bare_shukhov_lattice_is_maxwell_critical.
    # Real Shukhov towers close that gap with riveted joints and
    # continuous ring beams; a pin-jointed model has to close it with
    # members, so `brace` decides how.
    if brace == BRACE_COUNTER:
        # A counter-diagonal in every other panel: the fewest added
        # members that removes all of them, and the only members in the
        # mesh that are NOT exact generators of the surface.
        for i in range(n_rings):
            for j in range(n_sectors):
                if (i + j) % 2 == 0:
                    _add_member(members, seen, rings[i][j],
                                rings[i + 1][(j + twist) % n_sectors], role='web_diag')
    elif brace == BRACE_RING:
        # The ring-beam reading instead: a skip-one chord round every
        # hoop, which is how a truss model says "this ring resists
        # bending in its own plane". More members than the counter
        # diagonals, and measurably the stiffer of the two.
        for ring in rings:
            for j in range(n_sectors):
                _add_member(members, seen, ring[j], ring[(j + 2) % n_sectors], role='hoop')

    support_candidates = sorted(rings[0])

    # Tributary lateral surface area: for each node, half the hoop
    # spacing either side times half the true ring-to-ring spacing either
    # side, measured on the actual node positions rather than assumed -- a
    # hyperboloid's rings are neither equally spaced in height nor equally
    # sized in radius, so a single closed-form strip area would be wrong
    # for all but the waist.
    def dist(p, q):
        return math.dist(bank.nodes[p], bank.nodes[q])

    load_nodes = {}
    for i, ring in enumerate(rings):
        for j in range(n_sectors):
            hoop = (dist(ring[j], ring[(j + 1) % n_sectors])
                    + dist(ring[j], ring[(j - 1) % n_sectors])) / 2.0
            up = dist(ring[j], rings[i + 1][j]) if i < n_rings else 0.0
            down = dist(ring[j], rings[i - 1][j]) if i > 0 else 0.0
            span = (up + down) / (2.0 if (up and down) else 1.0)
            load_nodes[ring[j]] = hoop * span
    return {'nodes': bank.nodes, 'members': members,
            'support_candidates': support_candidates, 'load_nodes': load_nodes}


def hyperboloid_tower(radius, height, n_rings=6, n_sectors=16, twist=1,
                      brace=BRACE_COUNTER):
    """A ruled HYPERBOLOID OF REVOLUTION -- the Shukhov lattice tower: a
    doubly curved shell built entirely out of STRAIGHT members, with a
    narrow waist at mid-height flaring to a wider ring top and bottom.

    Every diagonal here lies exactly on the surface (see the module
    docstring), which is the shape's whole claim: a hyperbolic tower needs
    no curved steel, no bent formwork and no jig, only two families of
    straight bars crossing at every node. Cooling towers, water towers,
    observation towers and the Canton Tower are all this surface.

    Structurally the doubled diagonals ARE the bracing -- each quadrilateral
    panel is crossed by one member of each family, so the lattice is fully
    triangulated as a single layer with no separate web system, and it
    resists twist about the axis as readily as bending, which a ring-and-
    meridian dome lattice does not.

    radius    : the WAIST radius (m) -- the narrowest ring, at mid-height.
                Both end rings flare to radius / cos(flare angle).
    height    : overall height (m), waist at mid-height.
    n_rings   : ring-to-ring courses up the tower (>= 2); the ring COUNT is
                n_rings + 1.
    n_sectors : nodes per ring (>= 3).
    twist     : how many SECTORS a generator crosses per ring course
                (>= 1). This sets the flare: the half flare angle is
                n_rings * twist * 90 / n_sectors degrees, and the end rings
                are 1/cos(that) times the waist radius. It must be a whole
                number of sectors for the left-handed generators to land on
                the nodes -- see the module docstring. ValueError if the
                combination flares past 90 degrees.
    brace     : how the Maxwell-critical bare lattice is stabilised.
                'counter' (the default) adds a counter-diagonal in every
                other panel -- the fewest members that remove every
                mechanism, and the only members here that are not exact
                generators. 'ring' instead stiffens each hoop with a
                skip-one chord, the truss model of a continuous ring
                beam: more members, and measurably stiffer. 'none' gives
                the bare two-family Shukhov lattice with every single
                member an exact generator -- offered because it is the
                pure geometry, NOT because it stands up on its own. It
                carries n_rings inextensional mechanisms, and the danger
                is that it does not always announce them: a symmetric
                self-weight load happens to be orthogonal to those modes,
                so the solver returns a perfectly plausible answer that is
                about 20 times too flexible (0.27 mm braced against 6.15 mm
                bare on the default tower). Use it to look at the pure
                ruled geometry, and brace it before believing a number.

    Returns the shared {'nodes','members','support_candidates'} dict, with
    the BOTTOM ring offered as support candidates.
    """
    return _hyperboloid_lattice(radius, radius, height, n_rings, n_sectors, twist,
                                brace=brace)


def elliptic_hyperboloid(radius_x, radius_y, height, n_rings=6, n_sectors=16,
                         twist=1, brace=BRACE_COUNTER):
    """An ELLIPTIC hyperboloid of one sheet: hyperboloid_tower squashed to
    an ELLIPTICAL plan, with independent waist radii in x and y.

    An ellipse is a circle under an affine map, and an affine map takes
    straight lines to straight lines, so this surface is doubly ruled for
    exactly the same reason the circular one is and every diagonal member
    is still an exact straight generator -- see the module docstring. What
    changes is that the nodes are no longer all equivalent: a ring is an
    ellipse, so the members around it vary in length, and the flatter sides
    of the plan are the softer ones against a horizontal load.

    radius_x, radius_y : the two WAIST semi-axes (m), at mid-height.
    height, n_rings, n_sectors, twist, brace : exactly as hyperboloid_tower.

    Returns the shared {'nodes','members','support_candidates'} dict, with
    the BOTTOM ring offered as support candidates.
    """
    return _hyperboloid_lattice(radius_x, radius_y, height, n_rings, n_sectors,
                                twist, brace=brace)


# ═══════════════════════════════════════════════════════════════════════
#  2 · Torus segment (a barrel vault bent round in plan)
# ═══════════════════════════════════════════════════════════════════════

def torus_segment(major_radius, tube_radius, sweep_deg=180.0, arc_deg=180.0,
                  n_sweep=16, n_arc=6, depth=0.6, pattern='square'):
    """A TORUS SEGMENT: a semicircular vault section swept round a circular
    plan -- a RING VAULT, the shape of a curved arcade, an annular concourse
    roof, a circular hall's aisle.

    It is the one family here that is doubly curved in the useful direction
    for BOTH spans at once: the tube section arches across the vault, and
    the plan sweep arches along it, so the crown line is itself an arch in
    plan. Unlike a straight barrel vault, which is developable and needs an
    end diaphragm or stiffening arch to stop it unrolling, a closed ring
    vault braces itself in plan -- its hoops cannot lengthen without the
    whole ring growing.

    major_radius : radius (m) from the plan centre to the CROWN of the tube.
    tube_radius  : radius (m) of the vault's own section.
    sweep_deg    : how far round the plan the vault runs. Exactly 360 closes
                   the seam into a complete ring with no free ends.
    arc_deg      : how much of the tube section is built. 180 is a
                   half-tube standing on two springing lines at z=0; less
                   gives a shallower vault, more brings the springings in
                   under themselves.
    n_sweep      : bays round the plan sweep.
    n_arc        : segments across the vault section.
    depth        : inner-layer offset (m), measured radially IN towards the
                   tube's own centre line -- a true concentric inner tube,
                   not a vertical offset. 0 gives a single layer.
    pattern      : 'square', 'diagonal' or 'isometric', as everywhere else.

    Returns the shared {'nodes','members','support_candidates'} dict. The
    support candidates are the two SPRINGING lines (the tube arc's two
    ends), which is where a ring vault actually bears.
    """
    major_radius = float(major_radius); tube_radius = float(tube_radius)
    depth = float(depth)
    n_sweep = max(2, int(n_sweep)); n_arc = max(1, int(n_arc))
    if major_radius <= 0 or tube_radius <= 0:
        raise ValueError('major_radius and tube_radius must both be positive')
    if depth < 0 or depth >= tube_radius:
        raise ValueError('depth must be at least 0 and less than tube_radius')
    sweep = math.radians(float(sweep_deg))
    arc = math.radians(float(arc_deg))
    if sweep <= 0 or arc <= 0:
        raise ValueError('sweep_deg and arc_deg must both be positive')

    wrap = abs(sweep - 2.0 * math.pi) < 1e-9
    bank = _NodeBank()

    def place(tau, sigma, r_tube):
        # sigma runs from one springing round to the other, so u = 0 is the
        # CROWN: z is highest and the plan radius is exactly major_radius
        # there, and for the default 180-degree arc both ends land on z = 0
        # at major_radius -/+ tube_radius -- the two springing lines.
        u = sigma - arc / 2.0
        rho = major_radius + r_tube * math.sin(u)
        z = r_tube * math.cos(u)
        return bank.add(rho * math.cos(tau), rho * math.sin(tau), z)

    # i runs across the vault section (springing to springing), j round the
    # plan sweep, so a wrapped full ring closes in j exactly the way the
    # custom-surface helpers expect.
    imax, jmax = n_arc, n_sweep
    j_count = jmax if wrap else jmax + 1
    outer, inner = {}, {}
    for j in range(j_count):
        tau = sweep * j / n_sweep
        for i in range(imax + 1):
            sigma = arc * i / n_arc
            outer[(i, j)] = place(tau, sigma, tube_radius)
            if depth > 0:
                inner[(i, j)] = place(tau, sigma, tube_radius - depth)

    members, seen = [], set()
    if depth > 0:
        _surface_chords(members, seen, outer, imax, jmax, pattern, wrap, role='outer_rib')
        _surface_chords(members, seen, inner, imax, jmax, pattern, wrap, role='inner_rib')
        _surface_webs(members, seen, outer, inner, imax, jmax, wrap)
    else:
        # A single layer has no web system to triangulate it, so the
        # section-to-sweep quadrilaterals get one diagonal each on top of
        # the requested chord pattern. Without it a pin-jointed single
        # layer racks, exactly as custom_surface_grid warns.
        _surface_chords(members, seen, outer, imax, jmax, pattern, wrap, role='surface_chord')
        if pattern == 'square':
            for j in range(jmax):
                jn = (j + 1) % jmax if wrap else j + 1
                for i in range(imax):
                    _add_member(members, seen, outer[(i, j)], outer[(i + 1, jn)],
                                role='web_diag')

    springings = sorted({n for (i, _j), n in outer.items() if i in (0, imax)}
                        | {n for (i, _j), n in inner.items() if i in (0, imax)})

    # Tributary surface area on the outer layer: the swept-arc cell each
    # node owns. A torus's own area element is (major + r*sin(...)) dtau *
    # r dsigma -- the sweep circumference varies across the section, which
    # is exactly what makes a ring vault's outer edge longer than its
    # inner one.
    d_sigma = arc / n_arc
    d_tau = sweep / n_sweep
    load_nodes = {}
    for (i, j), node in outer.items():
        sigma = arc * i / n_arc
        rho = major_radius + tube_radius * math.sin(sigma - arc / 2.0)
        fi = 0.5 if i in (0, imax) else 1.0
        fj = 1.0 if wrap else (0.5 if j in (0, jmax) else 1.0)
        load_nodes[node] = abs(rho) * d_tau * tube_radius * d_sigma * fi * fj
    return {'nodes': bank.nodes, 'members': members,
            'support_candidates': springings, 'load_nodes': load_nodes}


# ═══════════════════════════════════════════════════════════════════════
#  3 · Helicoid ramp
# ═══════════════════════════════════════════════════════════════════════

def helicoid_ramp(inner_radius, outer_radius, turns=1.0, rise_per_turn=3.2,
                  n_radial=4, n_along=24, depth=0.8, pattern='square'):
    """A HELICOID: an annular deck winding up a central axis -- a car-park
    ramp, a spiral stair, a helical walkway.

    The helicoid is the classic RULED surface of the list: every radial
    line of it is dead straight and horizontal, and only the winding
    direction climbs. It is also a minimal surface, which is the geometric
    reason a helical ramp looks so light: it has zero mean curvature, so it
    is the least-area surface spanning its own two edge helices.

    Structurally it is the hardest shape here, and honestly so. A helicoid
    has NO arch action in either direction -- the radial lines are straight
    and level, and the circumferential ones climb but do not curve
    vertically enough to arch. It spans by BENDING AND TORSION, and the
    torsion is unavoidable: a load on the outer edge twists the deck about
    its own helical axis, which is why a real helical ramp is either a
    deep-edged beam, a slab on a stiff central core, or propped by columns
    every bay. Give it real depth, and look at the outer edge deflection.

    inner_radius  : inner edge radius (m); 0 is not allowed (the axis is a
                    singular line of the surface, and every radial member
                    would meet at one point).
    outer_radius  : outer edge radius (m).
    turns         : how many full turns the ramp makes (may be fractional).
    rise_per_turn : height gained per full turn (m) -- a storey height for
                    a car park.
    n_radial      : bays across the deck width.
    n_along       : bays along the whole helical run.
    depth         : the soffit layer's offset (m) straight DOWN -- a real
                    ramp's structural depth is measured vertically, under
                    the deck. 0 gives a single layer, which is forced to
                    RIGID joints (see the code): a pinned single-layer
                    helicoid has no stiffness to speak of and is not a
                    structure.
    pattern       : 'square', 'diagonal' or 'isometric', as everywhere else.

    Returns the shared {'nodes','members','support_candidates'} dict. The
    support candidates are the INNER edge (the central core the ramp winds
    around) plus both ENDS of the run, which is how such a ramp is normally
    held.
    """
    inner_radius = float(inner_radius); outer_radius = float(outer_radius)
    depth = float(depth); turns = float(turns); rise_per_turn = float(rise_per_turn)
    n_radial = max(1, int(n_radial)); n_along = max(2, int(n_along))
    if inner_radius <= 0:
        raise ValueError('inner_radius must be positive (the axis itself is singular)')
    if outer_radius <= inner_radius:
        raise ValueError('outer_radius must exceed inner_radius')
    if turns <= 0:
        raise ValueError('turns must be positive')
    if depth < 0:
        raise ValueError('depth must be at least 0')

    total_angle = 2.0 * math.pi * turns
    pitch = rise_per_turn / (2.0 * math.pi)

    bank = _NodeBank()
    imax, jmax = n_radial, n_along
    deck, soffit = {}, {}
    for j in range(jmax + 1):
        tau = total_angle * j / n_along
        z = pitch * tau
        for i in range(imax + 1):
            r = inner_radius + (outer_radius - inner_radius) * i / n_radial
            x, y = r * math.cos(tau), r * math.sin(tau)
            deck[(i, j)] = bank.add(x, y, z)
            if depth > 0:
                soffit[(i, j)] = bank.add(x, y, z - depth)

    members, seen = [], set()
    if depth > 0:
        _surface_chords(members, seen, deck, imax, jmax, pattern, False, role='top_chord')
        _surface_chords(members, seen, soffit, imax, jmax, pattern, False, role='bottom_chord')
        _surface_webs(members, seen, deck, soffit, imax, jmax, False)
    else:
        # A single-layer helicoid is a PLATE, not a truss, and pretending
        # otherwise gives a metre of fictitious deflection rather than an
        # answer: its radial lines are straight and level, so a pinned bar
        # model of it has essentially no stiffness against a load on the
        # deck. Every member is therefore forced rigid (and tagged
        # rigid_required, so the Section panel cannot quietly pin it back)
        # exactly as vierendeel_grid does, for exactly the same reason --
        # this layer carries its load by BENDING AND TORSION and needs I
        # and J, not just E and A.
        rigid = {'conn': 'rigid', 'rigid_required': True}
        _surface_chords(members, seen, deck, imax, jmax, pattern, False,
                        role='surface_chord')
        for m in members:
            m.update(rigid)

    core = {n for (i, _j), n in deck.items() if i == 0}
    core |= {n for (i, _j), n in soffit.items() if i == 0}
    ends = {n for (_i, j), n in deck.items() if j in (0, jmax)}
    ends |= {n for (_i, j), n in soffit.items() if j in (0, jmax)}
    support_candidates = sorted(core | ends)

    # Tributary PLAN area of the annular sector cell each deck node owns:
    # r * dr * dtau, the polar area element -- so an outer-edge node
    # carries more deck than an inner one, which is the whole reason a
    # helical ramp's outer edge is the critical one.
    dr = (outer_radius - inner_radius) / n_radial
    d_tau = total_angle / n_along
    load_nodes = {}
    for (i, j), node in deck.items():
        r = inner_radius + (outer_radius - inner_radius) * i / n_radial
        fi = 0.5 if i in (0, imax) else 1.0
        fj = 0.5 if j in (0, jmax) else 1.0
        load_nodes[node] = r * dr * d_tau * fi * fj
    return {'nodes': bank.nodes, 'members': members,
            'support_candidates': support_candidates, 'load_nodes': load_nodes}
