"""Bezier profiles and the surfaces built from them.

WHAT THIS IS FOR
----------------
A typed formula is exact and completely inflexible: to move one part of
the curve you have to find an algebraic expression that moves that part
and nothing else, which for anything but the simplest shapes does not
exist. A Bezier chain is the opposite -- approximate, but every point of
it is a handle you can take hold of, and moving one handle changes its
own stretch of the curve and leaves the rest alone.

So the two belong together, and the workflow this module supports is:
type the formula you can describe, FIT a chain to it, then edit the parts
you could not describe.

WHY CUBIC HERMITE RATHER THAN LEAST SQUARES
-------------------------------------------
Least squares per segment gives a slightly smaller worst error (about
0.13% against 0.15% on sin(2x) with 8 segments) and is the wrong tool
here for two reasons that matter more than a hundredth of a per cent:

  * It does not join up. Segments fitted independently agree at a knot
    only by luck, so the curve has kinks the user did not put there and
    cannot see the cause of.
  * Its control points mean nothing individually. They are whatever
    minimised a sum, so "drag this one" has no predictable effect and
    the numeric table is a list of magic numbers.

Cubic Hermite interpolates the function AT every knot and matches its
slope there. That makes the chain exactly C1 by construction, and gives
every control point a meaning: the ones at the knots are points the curve
passes through, and the two between them are tangent handles. Dragging
one does exactly what dragging it looks like it should do.

The accuracy is fine and is reported rather than promised. Measured
worst error as a percentage of the curve's own height:

                        4 segs   8 segs  12 segs  20 segs
    sin(2x), 0..2pi     10.72%   0.539%   0.154%   0.020%
    exp(-x^2), -3..3     4.42%   0.505%   0.134%   0.022%
    cosh(x), -2..2       0.23%   0.018%   0.004%   0.001%

Twelve segments is the default because it puts every one of those under
0.16%, and the panel shows the real number for the curve you actually
typed, so a shape that needs more says so instead of being quietly wrong.

REPRESENTATION
--------------
A profile is a dict:

    {'a', 'b': the parameter range,
     'segments': how many cubic pieces,
     'ctrl': a FLAT list of 3*segments + 1 values}

Flat, with segment k using ctrl[3k : 3k+4], so consecutive segments SHARE
their joining control point. C0 continuity is then a property of the
representation rather than something to maintain -- there is only one
number there, so the two segments cannot disagree about it.

C1 has to be maintained, and is: the knot value and its two neighbouring
handles sit at equally spaced parameter positions, so the curve is smooth
across a joint exactly when the two handle STEPS are equal. See
`enforce_c1`, and `set_control` which applies it on every edit unless the
caller asks for a deliberate crease.
"""
import math

#: Every segment is a cubic. Degree is not a user choice here: a cubic is
#: the lowest degree with an independent tangent at each end, which is
#: exactly what a chain needs, and raising it would add control points
#: with no clear meaning instead of accuracy the segment count gives more
#: cheaply.
DEGREE = 3
DEFAULT_SEGMENTS = 12
#: Step for the central difference that measures the fitted function's
#: slope. Small enough not to smooth a real feature, large enough that
#: subtracting two nearly equal values does not lose all its significance.
SLOPE_EPS = 1e-6


def bernstein(n, i, t):
    return math.comb(n, i) * (t ** i) * ((1.0 - t) ** (n - i))


def curve_point(ctrl, t):
    """A Bezier of any degree at parameter t, from its control values."""
    n = len(ctrl) - 1
    return sum(c * bernstein(n, i, t) for i, c in enumerate(ctrl))


def segment_of(profile, x):
    """(segment index, local t) for a parameter value x, clamped to the
    profile's own range so a point just outside it evaluates to the end
    rather than to an extrapolated fantasy."""
    a, b = profile['a'], profile['b']
    segs = profile['segments']
    if b == a:
        return 0, 0.0
    u = (x - a) / (b - a)
    u = max(0.0, min(1.0, u))
    k = min(segs - 1, int(u * segs))
    return k, u * segs - k


def profile_value(profile, x):
    """The profile's value at x."""
    k, t = segment_of(profile, x)
    return curve_point(profile['ctrl'][3 * k:3 * k + 4], t)


def fit_profile(f, a, b, segments=DEFAULT_SEGMENTS):
    """Fit a cubic Hermite chain to f over [a, b].

    Interpolates f at every knot and matches its slope there, so the
    result passes through the function at segments+1 places exactly and is
    C1 everywhere. Raises ValueError for a degenerate range rather than
    returning a chain of zero-length segments.
    """
    a = float(a)
    b = float(b)
    segments = max(1, int(segments))
    if not math.isfinite(a) or not math.isfinite(b) or abs(b - a) < 1e-12:
        raise ValueError('a Bezier profile needs a non-zero parameter range')
    h = (b - a) / segments
    ctrl = []
    for k in range(segments):
        x0 = a + k * h
        x1 = x0 + h
        p0, p3 = float(f(x0)), float(f(x1))
        m0 = (f(x0 + SLOPE_EPS) - f(x0 - SLOPE_EPS)) / (2.0 * SLOPE_EPS)
        m1 = (f(x1 + SLOPE_EPS) - f(x1 - SLOPE_EPS)) / (2.0 * SLOPE_EPS)
        piece = [p0, p0 + m0 * h / 3.0, p3 - m1 * h / 3.0, p3]
        ctrl.extend(piece[:-1] if k < segments - 1 else piece)
    return {'a': a, 'b': b, 'segments': segments, 'ctrl': ctrl}


def fit_error(profile, f, samples=400):
    """(worst absolute error, worst as a fraction of the function's own
    range) between a fitted profile and the function it came from.

    Reported rather than promised: a fit is an approximation, and the only
    honest thing to do with an approximation is say how far off it is for
    the curve actually in front of you.
    """
    a, b = profile['a'], profile['b']
    values = []
    worst = 0.0
    for i in range(samples + 1):
        x = a + (b - a) * i / samples
        try:
            truth = float(f(x))
        except (ValueError, ZeroDivisionError, OverflowError):
            continue
        values.append(truth)
        worst = max(worst, abs(profile_value(profile, x) - truth))
    if not values:
        return 0.0, 0.0
    span = max(values) - min(values)
    return worst, (worst / span if span > 1e-12 else 0.0)


def knot_indices(profile):
    """Which entries of the flat control list are ON the curve (the knots)
    rather than tangent handles. The table marks these differently because
    they mean a different thing: a point the curve passes through, against
    a direction it leaves in."""
    return [3 * k for k in range(profile['segments'] + 1)]


def enforce_c1(profile, knot):
    """Make the curve smooth across one interior joint, by averaging the
    two handle steps either side of it.

    Averaging rather than mirroring one onto the other: mirroring picks a
    winner, so which side you dragged decides where the curve ends up, and
    dragging the same joint twice from different sides walks it away.
    """
    ctrl = profile['ctrl']
    i = 3 * knot
    if knot <= 0 or knot >= profile['segments'] or i + 1 >= len(ctrl):
        return
    before = ctrl[i] - ctrl[i - 1]
    after = ctrl[i + 1] - ctrl[i]
    step = (before + after) / 2.0
    ctrl[i - 1] = ctrl[i] - step
    ctrl[i + 1] = ctrl[i] + step


def set_control(profile, index, value, keep_smooth=True):
    """Move one control point, keeping the curve smooth unless asked not to.

    Moving a KNOT drags its two handles with it, so the curve follows the
    point instead of the point tearing away from its own tangents -- which
    is what happens if you move the knot alone, and looks like a bug.
    """
    ctrl = profile['ctrl']
    if not 0 <= index < len(ctrl):
        raise IndexError(f'control {index} is outside this profile')
    if index % 3 == 0:
        shift = value - ctrl[index]
        ctrl[index] = value
        for neighbour in (index - 1, index + 1):
            if 0 <= neighbour < len(ctrl):
                ctrl[neighbour] += shift
    else:
        ctrl[index] = value
        if keep_smooth:
            # The handle's own joint is the knot it sits beside.
            enforce_c1(profile, (index + 1) // 3 if index % 3 == 2 else index // 3)
    return profile


def is_smooth(profile, tol=1e-9):
    """True when every interior joint is C1 -- used by the tests, and by
    the panel to say whether a profile still has creases in it."""
    ctrl = profile['ctrl']
    for knot in range(1, profile['segments']):
        i = 3 * knot
        if abs((ctrl[i] - ctrl[i - 1]) - (ctrl[i + 1] - ctrl[i])) > tol:
            return False
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  Surfaces built from a profile
# ═══════════════════════════════════════════════════════════════════════════
# Both return a callable in the same surface(p, q) -> (x, y, z) shape every
# other surface in this tab uses, so a Bezier surface goes through
# custom_surface_lattice exactly like a typed formula: same lattices, same
# patterns, same plan-shape rule, same everything downstream. That is the
# whole point of matching the shape rather than inventing a second path.

def extruded_surface(profile):
    """The profile as a height field, swept along y: z = profile(x).

    p is x and q is y, so the Shape panel's own domain boxes mean what
    they already say. Vaults, waves, north-light sections -- anything whose
    section is constant along one direction.
    """
    return lambda p, q: (p, q, profile_value(profile, p))


def spin_surface(profile):
    """The profile revolved about the Z axis: p is HEIGHT and q is ANGLE,
    with the profile read as the radius at that height.

    Set the domain's first range to the height and its SECOND to 0..2*pi
    for a closed solid of revolution, or to less for a segment of one. The
    angle range is typed in radians, which is exactly why the domain boxes
    now take pi multiples -- '2*pi' is the common case and 6.28318 is the
    same number with the meaning rubbed off.

    A negative radius is not refused: it is a legitimate way to pass the
    profile through its own axis, and the surface it produces is a real
    one. It is the caller's business, not this function's.
    """
    def surface(p, q):
        r = profile_value(profile, p)
        return (r * math.cos(q), r * math.sin(q), p)
    return surface


# ═══════════════════════════════════════════════════════════════════════════
#  Tensor-product patch
# ═══════════════════════════════════════════════════════════════════════════

def patch_value(grid, u, v):
    """A tensor-product Bezier surface at (u, v), both in 0..1.

    `grid[i][j]` is the height of control point (i, j) -- a rectangular net
    of heights, which is how a Bezier patch is edited everywhere: raise one
    control and the surface rises toward it, without reaching it.
    """
    nu = len(grid) - 1
    nv = len(grid[0]) - 1
    total = 0.0
    for i in range(nu + 1):
        bu = bernstein(nu, i, u)
        if bu == 0.0:
            continue
        for j in range(nv + 1):
            total += grid[i][j] * bu * bernstein(nv, j, v)
    return total


def patch_surface(grid, x_range, y_range):
    """The patch as a surface(x, y) -> (x, y, z) over a real plan
    rectangle, so it plugs into the lattice like any other."""
    x0, x1 = x_range
    y0, y1 = y_range
    dx = (x1 - x0) or 1.0
    dy = (y1 - y0) or 1.0

    def surface(p, q):
        u = max(0.0, min(1.0, (p - x0) / dx))
        v = max(0.0, min(1.0, (q - y0) / dy))
        return (p, q, patch_value(grid, u, v))
    return surface


def fit_patch(f, x_range, y_range, nu=5, nv=5, samples=24):
    """Least-squares fit of a tensor-product Bezier patch to f(x, y).

    Separable, which is not an optimisation but the exact answer: the
    Bernstein basis is a product in u and v, so fitting a grid of samples
    factorises into one solve per direction rather than a single big
    system. Solved with a pseudo-inverse so a control count larger than the
    sample count degrades instead of raising.

    A SINGLE patch, deliberately -- and this is its real limit, stated
    rather than discovered: a patch of degree n has n-1 interior bends in
    each direction, so it cannot follow a surface with more waves than
    that however many samples it is given. Measured, for
    3*cos(x)*cos(y) over -9..9, which is 2.86 waves each way:

        degree   5   8    10     12     14     16     20
        error   55% 30%  6.5%   1.4%  0.25%  0.04%  0.001%
        ctrls    36  81   121    169    225    289     441

    So a wavy surface does not merely fit badly at low degree -- it needs
    a control count that stops being editable by hand long before it
    becomes accurate. For that shape, use a profile with a spin or an
    extrude: a chain's segment count buys the same accuracy for a
    fraction of the controls, and each one still means something.
    patch_error says how far off this particular one came out.
    """
    import numpy as np
    x0, x1 = x_range
    y0, y1 = y_range
    nu = max(1, int(nu))
    nv = max(1, int(nv))
    us = [i / samples for i in range(samples + 1)]
    vs = [j / samples for j in range(samples + 1)]
    Bu = np.array([[bernstein(nu, i, u) for i in range(nu + 1)] for u in us])
    Bv = np.array([[bernstein(nv, j, v) for j in range(nv + 1)] for v in vs])
    Z = np.array([[float(f(x0 + (x1 - x0) * u, y0 + (y1 - y0) * v)) for v in vs]
                  for u in us])
    grid = np.linalg.pinv(Bu) @ Z @ np.linalg.pinv(Bv).T
    return [[float(value) for value in row] for row in grid]


def patch_error(grid, f, x_range, y_range, samples=40):
    """(worst absolute error, worst as a fraction of the surface's own
    range) for a fitted patch -- the same honesty fit_error gives a
    profile, and more necessary here because a single patch has a hard
    ceiling on how many waves it can follow."""
    x0, x1 = x_range
    y0, y1 = y_range
    worst = 0.0
    values = []
    for i in range(samples + 1):
        u = i / samples
        for j in range(samples + 1):
            v = j / samples
            try:
                truth = float(f(x0 + (x1 - x0) * u, y0 + (y1 - y0) * v))
            except (ValueError, ZeroDivisionError, OverflowError):
                continue
            values.append(truth)
            worst = max(worst, abs(patch_value(grid, u, v) - truth))
    if not values:
        return 0.0, 0.0
    span = max(values) - min(values)
    return worst, (worst / span if span > 1e-12 else 0.0)
