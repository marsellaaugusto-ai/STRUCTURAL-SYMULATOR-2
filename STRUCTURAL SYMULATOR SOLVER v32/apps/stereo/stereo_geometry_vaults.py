"""Extruded-arch vaults, single or double layer (family 2 of the Stereo
geometry library).

All three share barrel_vault's own station/rib/purlin/edge-brace bracing
via _extruded_arch_grid -- they differ only in the arch PROFILE extruded
along the length, so a new vault profile is a short wrapper here:

  barrel_vault    -- circular arch
  parabolic_vault -- parabolic arch
  elliptic_vault  -- elliptic arch

The vault rises along +z and springs on the two long edges (its two
springing lines), NOT the two short end faces -- see barrel_vault's own
docstring for why that distinction is load-bearing, and the regression it
guards.
"""
import math

from apps.stereo.stereo_geometry_core import _NodeBank, _add_member


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


def catenary_vault(span, rise, length, n_arch=8, n_bays=8, double_layer=True,
                   depth=0.0, shape=2.0):
    """A CATENARY-arch barrel vault: the same station/rib/purlin/bracing
    scheme as barrel_vault(), on an INVERTED-CATENARY arch profile --

        y = (span/2) * t,
        z = rise * (cosh(shape) - cosh(shape*t)) / (cosh(shape) - 1)

    for t in [-1, 1], which is `rise` at the crown and zero at both
    springings for any `shape`.

    The catenary is the arch form that matters most in practice and the
    reason this family is worth having next to the parabolic one it
    resembles: a chain hanging under its OWN WEIGHT takes a catenary, so
    an arch of the same curve inverted carries its own weight in PURE
    COMPRESSION, with the thrust line lying exactly on the arch axis and
    no bending anywhere along it. (A parabola is the form for a load
    uniform per unit HORIZONTAL length -- a suspension bridge deck --
    which is a different load and a different curve.) For a masonry or
    concrete vault, where self-weight dominates and the material cannot
    take tension, that distinction is the whole design.

    The pure-compression property holds for self-weight ALONE. Any
    unsymmetric load -- wind, drifted snow, a point load -- moves the
    thrust line off the axis and reintroduces bending, exactly as it does
    for every other arch; the catenary is optimal for one load case, not
    immune to the others.

    shape : the dimensionless catenary parameter (span / 2c). Small values
            approach a parabola; larger ones give the steep, pointed,
            Gaudi-like arch of a heavy self-weight-dominated vault.
            Must be positive.
    span, rise, length, n_arch, n_bays, double_layer, depth : as in
            barrel_vault().

    Returns the shared {'nodes','members','support_candidates'} dict, with
    every node on the two springing lines (the vault's base) offered as
    support candidates.
    """
    span = float(span); rise = float(rise); shape = float(shape)
    if span <= 0 or rise <= 0:
        raise ValueError('span and rise must both be positive')
    if shape <= 0:
        raise ValueError('shape must be positive')
    denom = math.cosh(shape) - 1.0
    if denom <= 0:
        raise ValueError('shape is too small to define a catenary')

    def arch_point(t):
        return (span / 2.0) * t, rise * (math.cosh(shape) - math.cosh(shape * t)) / denom

    bank, members, outer, _inner, support_candidates, bay_dx = _extruded_arch_grid(
        arch_point, length, n_arch, n_bays, double_layer, depth)
    n_arch = max(2, int(n_arch)); n_bays = max(1, int(n_bays))
    load_nodes = _secant_arc_load_nodes(arch_point, n_arch, n_bays, bay_dx, outer)

    return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
            'load_nodes': load_nodes}
