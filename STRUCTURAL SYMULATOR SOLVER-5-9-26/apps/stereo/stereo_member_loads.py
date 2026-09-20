"""Distributed loads applied ALONG a member, and the internal force
diagrams they produce.

WHY THIS EXISTS, AND WHY IT IS NOT JUST ANOTHER LOAD TYPE
---------------------------------------------------------
Every load the Stereo tab could apply until now arrived at a NODE: a
point load, or an area pressure lumped onto the nodes of the loaded
surface by tributary area. That is the right idealisation for most space
structures, and it has one consequence that is easy to miss:

    under nodal loads alone, the shear in a member is CONSTANT along it.

Nothing acts on the member between its ends, so nothing can change the
transverse force transmitted across a cut, wherever the cut is made. A
"shear along the rod" colour gradient under nodal loads would therefore
be drawing a picture of a single number -- there is no variation to show,
and any gradient on screen would be an invention.

A load applied along the member is what breaks that. Put w kN/m on a rod
and the shear falls linearly along it and the moment becomes a parabola,
which is the ordinary condition of any purlin, any beam carrying deck
directly, any chord with cladding hung off it, and any member under its
own self weight taken honestly rather than lumped to its ends. This
module is what makes those real, so the along-the-rod shear and moment
gradients have something true to draw.

WHAT A MEMBER LOAD IS
---------------------
A dict:

    {'member': index,
     'w': kN/m,                          intensity, always positive
     'dir': (dx, dy, dz),                GLOBAL direction it pushes
     'spread': ALONG or PROJECTED}

`spread` is the difference between two things that are easy to confuse:

  ALONG      w is per metre OF THE MEMBER. Self weight, a hung service
             run, an ice coating -- anything that belongs to the member
             itself and follows it however it is tilted.
  PROJECTED  w is per metre of the member's projection on the plane
             PERPENDICULAR to the load direction -- per horizontal metre
             for a gravity load. Snow and most code roof loads are quoted
             this way: a sloping purlin picks up the snow that falls on
             its plan length, not on its true length, so a steeper rod
             carries no more of it.

The two coincide exactly when the member is perpendicular to the load
direction, and diverge as the cosine of the tilt otherwise.

HOW IT IS SOLVED
----------------
A load between the nodes cannot be fed to a stiffness solve directly;
it is converted to the work-equivalent nodal load vector first, and the
member's own internal forces are then recovered by adding the
fixed-end forces back. Which conversion is correct depends entirely on
what the member's ends can transmit, and the two cases are genuinely
different structures, not two approximations of one:

  RIGID member  a beam-column. The equivalent nodal vector carries END
                MOMENTS (wL^2/12) as well as end shears (wL/2), and the
                element's true end forces are k*d PLUS the fixed-end
                vector. Its internal moment runs from one end value to
                the other as a PARABOLA, not the straight line a nodal
                load gives.
  PIN member    a bar with ball joints. Its ends cannot transmit moment
                at all, so the equivalent nodal vector is a plain
                half-and-half split with no moments -- exactly what
                self_weight_loads has always done -- and the member's own
                bending is a SIMPLY SUPPORTED span, the textbook
                wx(L-x)/2 parabola peaking at wL^2/8. That local bending
                is real and is what sizes a purlin, but it is
                deliberately NOT fed back into the global solve: a pinned
                joint transmits no moment, so the rest of the structure
                genuinely does not feel it. The app reports it as the
                member's own check quantity.

Every sign convention below is pinned down by tests against the two
closed-form cases (simply supported wL^2/8 at midspan; fixed-fixed
wL^2/12 at the ends and wL^2/24 at midspan) in BOTH local bending
planes, because a 3D frame element's x-z plane carries an opposite sign
to its x-y plane and reasoning about it is how that gets shipped
backwards.
"""
import math

from apps.stereo.stereo_math import _local_axes, member_vector

#: w is per metre of the member's own length.
ALONG = 'along'
#: w is per metre of the member's projection perpendicular to the load.
PROJECTED = 'projected'
SPREADS = (ALONG, PROJECTED)

SPREAD_LABELS = ((ALONG, 'Per metre of rod'),
                 (PROJECTED, 'Per metre projected (snow-style)'))


def _unit(v):
    x, y, z = v
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-12:
        raise ValueError('a member load needs a non-zero direction')
    return x / n, y / n, z / n


def local_intensity(nodes, member, load):
    """Resolve one member load into (wx, wy, wz, L): the intensity in the
    member's own LOCAL axes, in kN/m of member length, plus its length.

    A PROJECTED intensity is converted here and nowhere else: the member's
    projected length is L * sin(angle between the member and the load
    direction), so the per-member-metre intensity is w * sin(angle) -- and
    it falls to zero for a member running straight along the load
    direction, which is correct. A column collects no snow.
    """
    dx, dy, dz, L = member_vector(nodes, member)
    if L < 1e-9:
        return 0.0, 0.0, 0.0, 0.0
    ex, ey, ez = _local_axes(dx, dy, dz, L)
    gx, gy, gz = _unit(load.get('dir', (0.0, 0.0, -1.0)))
    w = float(load.get('w', 0.0))
    if load.get('spread', ALONG) == PROJECTED:
        along = gx * ex[0] + gy * ex[1] + gz * ex[2]
        w *= math.sqrt(max(0.0, 1.0 - along * along))
    return (w * (gx * ex[0] + gy * ex[1] + gz * ex[2]),
            w * (gx * ey[0] + gy * ey[1] + gz * ey[2]),
            w * (gx * ez[0] + gy * ez[1] + gz * ez[2]),
            L)


def fixed_end_local(nodes, members, load):
    """The 12-vector of local FIXED-END FORCES f^F for one member load, in
    N and N*m, ordered (ux, uy, uz, rx, ry, rz) at end a then end b -- the
    same ordering and units as analyze()'s own local element force vector,
    so the two add directly.

    The convention, fixed here once so everything downstream can rely on
    it: the element's true end forces are

        f_end = k * d + f^F

    which is why the equivalent nodal load applied to the STRUCTURE is the
    negative of this vector, and why equivalent_nodal_loads below is
    written as exactly that negation rather than as a second derivation
    that could drift out of step with this one.

    A PIN member gets force terms only. Its joints transmit no moment, so
    it has no fixed-end moments to carry -- which is also why its own
    bending never reaches the global solve.
    """
    m = members[load['member']]
    wx, wy, wz, L = local_intensity(nodes, m, load)
    f = [0.0] * 12
    if L < 1e-9:
        return f
    f[0] = f[6] = -wx * L / 2.0 * 1e3
    f[1] = f[7] = -wy * L / 2.0 * 1e3
    f[2] = f[8] = -wz * L / 2.0 * 1e3
    if m.get('conn', 'pin') == 'rigid':
        # Bending in the local x-y plane is resisted about local z, and in
        # the x-z plane about local y WITH THE OPPOSITE SIGN -- the 3D frame
        # element's own convention, and the single easiest thing in this
        # file to ship backwards. The closed-form tests check both planes
        # for exactly that reason.
        f[5] = -wy * L * L / 12.0 * 1e3
        f[11] = +wy * L * L / 12.0 * 1e3
        f[4] = +wz * L * L / 12.0 * 1e3
        f[10] = -wz * L * L / 12.0 * 1e3
    return f


def equivalent_nodal_loads(nodes, members, member_loads):
    """The work-equivalent nodal load list for a set of member loads -- the
    same {'node','fx','fy','fz','mx','my','mz'} dicts (kN, kN*m) analyze()
    already takes, so member loads plug into the existing load path rather
    than needing a second route through the solver.

    Each member's contribution is the NEGATIVE of its fixed-end vector,
    rotated from the member's local axes into global ones. Deriving it that
    way, rather than writing the wL/2 and wL^2/12 terms out a second time,
    is what guarantees the equivalent loads and the internal-force recovery
    can never disagree about a sign.
    """
    out = {}

    def add(node, key, value):
        if node not in out:
            out[node] = {'node': node, 'fx': 0.0, 'fy': 0.0, 'fz': 0.0,
                         'mx': 0.0, 'my': 0.0, 'mz': 0.0}
        out[node][key] += value

    for load in member_loads:
        m = members[load['member']]
        dx, dy, dz, L = member_vector(nodes, m)
        if L < 1e-9:
            continue
        ex, ey, ez = _local_axes(dx, dy, dz, L)
        f = fixed_end_local(nodes, members, load)
        for base, node in ((0, m['a']), (6, m['b'])):
            fx, fy, fz = -f[base] / 1e3, -f[base + 1] / 1e3, -f[base + 2] / 1e3
            mx, my, mz = -f[base + 3] / 1e3, -f[base + 4] / 1e3, -f[base + 5] / 1e3
            add(node, 'fx', fx * ex[0] + fy * ey[0] + fz * ez[0])
            add(node, 'fy', fx * ex[1] + fy * ey[1] + fz * ez[1])
            add(node, 'fz', fx * ex[2] + fy * ey[2] + fz * ez[2])
            if mx or my or mz:
                add(node, 'mx', mx * ex[0] + my * ey[0] + mz * ez[0])
                add(node, 'my', mx * ex[1] + my * ey[1] + mz * ez[1])
                add(node, 'mz', mx * ex[2] + my * ey[2] + mz * ez[2])
    return list(out.values())


def member_diagram(mres, t):
    """The internal forces at fractional position `t` (0 at end a, 1 at end
    b) along a member, as (N, Vy, Vz, My, Mz) in kN and kN*m.

    `mres` is one entry of analyze()'s own member_res list. A member with
    no distributed load on it has a CONSTANT shear and a LINEAR moment --
    the honest answer, and the reason this returns the same numbers at
    every t for such a member rather than manufacturing a gradient.
    """
    L = mres.get('length_m', 0.0)
    x = max(0.0, min(1.0, float(t))) * L
    wx, wy, wz = mres.get('w_local') or (0.0, 0.0, 0.0)
    if mres.get('conn') != 'rigid':
        # A pinned bar. Axially, the reported N is the elongation-based
        # average, which for a linear N(x) is exactly its midspan value.
        # Transversely it bends as a SIMPLY SUPPORTED span -- zero moment
        # at both joints by definition, peak wL^2/8 at midspan -- and that
        # bending is the member's own, never the structure's, because a
        # ball joint transmits no moment.
        N = mres.get('N', 0.0) + wx * (L / 2.0 - x)
        Vy = wy * (x - L / 2.0)
        Vz = wz * (x - L / 2.0)
        # The SIGNS here must match the rigid branch's convention below --
        # dMy/dx = +Vz and dMz/dx = -Vy -- and not merely the magnitudes.
        # They did not: this used to return +wz*x*(L-x)/2 and
        # -wy*x*(L-x)/2, whose derivatives are -Vz and +Vy, so a pinned rod
        # reported its sagging moment with the opposite sign to a rigid rod
        # sagging exactly the same way. Magnitudes were right, which is why
        # every check that went through abs() or hypot() passed, but
        # _rod_field_value colours the moment view by the SIGNED value, so
        # every pinned rod in the moment-along-rod view was painted as
        # though it were hogging. Most rods in a space truss are pins.
        My = -wz * x * (L - x) / 2.0
        Mz = wy * x * (L - x) / 2.0
        return N, Vy, Vz, My, Mz
    # A frame element. The end forces already carry the fixed-end vector
    # (analyze adds it), so the diagram is the straightforward integration
    # from end a. Note the two bending planes carry OPPOSITE signs: dMy/dx
    # = +Vz but dMz/dx = -Vy, which is the 3D frame element's own
    # convention, not a slip -- both are pinned down against the
    # closed-form cantilever and simply-supported cases in
    # tests/test_stereo_member_loads.py.
    Vy_a = mres.get('Vy_a', 0.0)
    Vz_a = mres.get('Vz_a', 0.0)
    N = mres.get('N', 0.0) + wx * (L - x)
    Vy = Vy_a + wy * x
    Vz = Vz_a + wz * x
    My = mres.get('My_a', 0.0) + Vz_a * x + wz * x * x / 2.0
    Mz = mres.get('Mz_a', 0.0) - Vy_a * x - wy * x * x / 2.0
    return N, Vy, Vz, My, Mz


def diagram_extremes(mres, samples=10):
    """(worst |shear|, worst |moment|) anywhere along the member, as
    magnitudes.

    Evenly spaced stations alone are not enough and quietly under-report:
    with an odd station count the midspan of a simply supported member --
    exactly where its moment peaks -- falls BETWEEN two samples, and the
    answer comes back about 1% low. Since both diagrams are at most
    quadratic, the peak is at a known place, so each parabola's own vertex
    is added to the stations and the result is exact rather than nearly.
    """
    L = mres.get('length_m', 0.0)
    wx, wy, wz = mres.get('w_local') or (0.0, 0.0, 0.0)
    stations = [k / samples for k in range(samples + 1)]
    if L > 0:
        if mres.get('conn') == 'rigid':
            for V0, w in ((mres.get('Vy_a', 0.0), wy), (mres.get('Vz_a', 0.0), wz)):
                if abs(w) > 1e-12:
                    stations.append(-V0 / w / L)
        elif abs(wy) > 1e-12 or abs(wz) > 1e-12:
            stations.append(0.5)     # a pinned bar always peaks at midspan
    best_v = best_m = 0.0
    for t in stations:
        if not 0.0 <= t <= 1.0:
            continue
        _N, Vy, Vz, My, Mz = member_diagram(mres, t)
        best_v = max(best_v, math.hypot(Vy, Vz))
        best_m = max(best_m, math.hypot(My, Mz))
    return best_v, best_m


def varies_along_the_rod(mres):
    """True when this member's shear/moment actually CHANGE along it --
    i.e. it carries a transverse distributed load. The renderer asks this
    before drawing a gradient, so a model under nodal loads alone is drawn
    with the flat colour its constant shear deserves instead of a
    fabricated ramp."""
    w = mres.get('w_local') or (0.0, 0.0, 0.0)
    return abs(w[1]) > 1e-12 or abs(w[2]) > 1e-12
