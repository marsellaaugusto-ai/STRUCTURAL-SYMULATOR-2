"""
truss_guides.py — construction geometry and node arrays for the Truss tab.

GUIDES are drawing aids, not structure. They are never analysed, never become
members, and contribute nothing to the stiffness matrix; they exist so you can
lay a curve down and build a truss onto it — a parabolic bridge chord, a
circular arch, a sloped roof line. The Truss tab already calls something else
"ghost" (`_compute_ghost`, the marker showing where your next node will land),
so this is deliberately called a GUIDE to keep the two apart in the code.

Three kinds, which together cover the reticulated-bridge and arch cases:

    {'kind': 'func',   'expr': '4*f*x*(L-x)/L**2', 'x0':.., 'x1':..,
                       'params': {'L': 20.0, 'f': 4.0}}
    {'kind': 'line',   'p0': (x, y), 'p1': (x, y)}
    {'kind': 'circle', 'c': (x, y), 'r': R, 'a0': deg, 'a1': deg}

EVERYTHING HERE IS IN METRES, y-UP -- the frame the user types coordinates in
and the CAD readouts show. The canvas works in pixels with y DOWN; that
conversion belongs to the UI, and doing it here would put a display concern
inside the geometry.

ARC LENGTH IS THE POINT. "Evenly spaced along the curve" means equal distance
ALONG THE CURVE, not equal steps in x. On a parabola the two are very
different -- equal-x spacing bunches nodes up where the curve is steep, which
is exactly where a bridge chord needs them spread evenly. Every path-array
function below therefore works in arc length, and `arc_table` is the shared
machinery for it.

No Tkinter, no drawing, no Excel: same rule as truss_math.py.
"""
import copy
import math

import numpy as np

from common import make_shape_fn, _beam_gauss_solve

#: Samples used to build a guide's arc-length table. A parabola over a 20 m
#: span converges to ~1e-9 relative by a few hundred; 2000 is cheap (a few
#: hundred microseconds) and leaves headroom for wigglier user expressions.
ARC_SAMPLES = 2000


# ═════════════════════════════════════════════════════════════════════════
#  Evaluation
# ═════════════════════════════════════════════════════════════════════════

def guide_callable(guide):
    """A function t -> (x, y) in metres, with t running 0..1 over the guide's
    own extent, or None if the guide cannot be compiled.

    Returning None rather than raising is deliberate: a half-typed expression
    is the normal state of an input box, and the UI should draw nothing and
    say why, not throw.
    """
    kind = guide.get('kind')
    if kind == 'line':
        (x0, y0), (x1, y1) = guide['p0'], guide['p1']
        return lambda t: (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)

    if kind == 'circle':
        cx, cy = guide['c']
        r = float(guide['r'])
        a0 = math.radians(float(guide.get('a0', 0.0)))
        a1 = math.radians(float(guide.get('a1', 360.0)))
        return lambda t: (cx + r * math.cos(a0 + (a1 - a0) * t),
                          cy + r * math.sin(a0 + (a1 - a0) * t))

    if kind == 'ellipse':
        cx, cy = guide['c']
        a = float(guide['a']); b = float(guide['b'])
        rot = math.radians(float(guide.get('rot', 0.0)))
        a0 = math.radians(float(guide.get('a0', 0.0)))
        a1 = math.radians(float(guide.get('a1', 360.0)))
        cr, sr = math.cos(rot), math.sin(rot)

        def at_ell(t, a=a, b=b, a0=a0, a1=a1, cx=cx, cy=cy, cr=cr, sr=sr):
            th = a0 + (a1 - a0) * t
            lx, ly = a * math.cos(th), b * math.sin(th)
            return (cx + lx * cr - ly * sr, cy + lx * sr + ly * cr)
        return at_ell

    if kind == 'conic5':
        return conic_callable(guide)

    if kind == 'fit':
        # A fitted guide is stored as its CONSTRAINTS; solve them now. Doing
        # it here rather than at edit time is what makes fits associative:
        # move an end point and the next redraw re-solves with the same rise.
        prim = resolve_fit(guide)
        return guide_callable(prim) if prim else None

    if kind == 'func':
        x0 = float(guide.get('x0', 0.0))
        x1 = float(guide.get('x1', 1.0))
        try:
            fn = make_shape_fn(str(guide.get('expr', '0')),
                               dict(guide.get('params') or {}))
            fn(0.5 * (x0 + x1))          # fail now, not mid-draw
        except Exception:
            return None
        ox = float(guide.get('ox', 0.0))
        oy = float(guide.get('oy', 0.0))

        def at(t, fn=fn, x0=x0, x1=x1, ox=ox, oy=oy):
            # The curve is evaluated in its own frame and then offset, which
            # is what lets a typed y = f(x) be dragged around: shifting it by
            # editing the expression would mean rewriting the algebra.
            x = x0 + (x1 - x0) * t
            return (ox + x, oy + fn(x))
        return at
    return None


def guide_error(guide):
    """A human-readable reason the guide cannot be drawn, or None."""
    if guide.get('kind') == 'fit':
        return fit_error(guide)
    if guide.get('kind') == 'conic5':
        pts = [tuple(q) for q in guide.get('pts', [])]
        if len(pts) != 5:
            return 'a conic needs exactly five points (%d given).' % len(pts)
        if conic_from_points(pts) is None:
            return ('those five points do not determine a conic -- check for '
                    'repeated points, or three or more on a straight line.')
        if not conic_branches(conic_from_points(pts), conic_extent(pts)):
            return 'those five points give a degenerate conic.'
        return None
    if guide.get('kind') == 'ellipse':
        if float(guide.get('a', 0)) <= 0 or float(guide.get('b', 0)) <= 0:
            return 'both semi-axes must be positive.'
        return None
    if guide.get('kind') == 'func':
        try:
            fn = make_shape_fn(str(guide.get('expr', '')),
                               dict(guide.get('params') or {}))
            x0 = float(guide.get('x0', 0.0)); x1 = float(guide.get('x1', 1.0))
            if x1 == x0:
                return 'x range is empty (x₀ equals x₁).'
            fn(0.5 * (x0 + x1))
        except Exception as ex:
            return str(ex)
    if guide.get('kind') == 'circle' and float(guide.get('r', 0)) <= 0:
        return 'radius must be positive.'
    if guide.get('kind') == 'line':
        if guide['p0'] == guide['p1']:
            return 'the two points are the same.'
    return None


def sample(guide, n=None):
    """`n` points along the guide, in metres, evenly spaced in the guide's
    own parameter (NOT in arc length -- that is `points_by_count`). Used for
    drawing, and as the basis of the arc-length table."""
    fn = guide_callable(guide)
    if fn is None:
        return []
    n = int(n or ARC_SAMPLES)
    n = max(n, 2)
    out = []
    for i in range(n):
        try:
            out.append(fn(i / (n - 1)))
        except Exception:
            # A pole inside the range (1/x at 0, say) kills one sample, not
            # the whole curve; the drawing just breaks there.
            out.append(None)
    return out


# ═════════════════════════════════════════════════════════════════════════
#  Arc length
# ═════════════════════════════════════════════════════════════════════════

def arc_table(guide, n=ARC_SAMPLES):
    """(points, cumulative_lengths) along the guide.

    `cumulative_lengths[i]` is the distance along the curve from its start to
    `points[i]`, so `cumulative_lengths[-1]` is the total length. Chord
    summation: it converges from below, and its error falls as 1/n^2, which
    at 2000 samples is far below anything a fabricator can set out.
    """
    pts = [p for p in sample(guide, n) if p is not None]
    if len(pts) < 2:
        return pts, [0.0] * len(pts)
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + math.hypot(pts[i][0] - pts[i-1][0],
                                        pts[i][1] - pts[i-1][1]))
    return pts, cum


def total_length(guide, n=ARC_SAMPLES):
    _pts, cum = arc_table(guide, n)
    return cum[-1] if cum else 0.0


def point_at_arclength(guide, s, table=None):
    """The point a distance `s` ALONG the curve from its start, in metres.
    `s` is clamped to the curve. Pass `table` to reuse one arc table across
    many queries -- building it per point would make an N-node path array
    N times more expensive than it needs to be."""
    pts, cum = table if table is not None else arc_table(guide)
    if not pts:
        return None
    if len(pts) == 1:
        return pts[0]
    s = max(0.0, min(float(s), cum[-1]))
    # binary search for the segment containing s
    lo, hi = 0, len(cum) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if cum[mid] <= s:
            lo = mid
        else:
            hi = mid
    span = cum[hi] - cum[lo]
    f = 0.0 if span < 1e-15 else (s - cum[lo]) / span

    # Interpolate the PARAMETER and re-evaluate the curve there, rather than
    # interpolating between the two sampled positions. Interpolating positions
    # puts the result on the chord between them -- inside the curve by the
    # sagitta, 7.4 um on a 6 m circle at the default sampling. That is small,
    # but a node placed by a path array should be ON the curve it was arrayed
    # along, not merely near it, and re-evaluating costs one function call.
    fn = guide_callable(guide)
    if fn is not None and len(pts) > 1:
        t = (lo + f) / (len(pts) - 1)
        try:
            return fn(min(max(t, 0.0), 1.0))
        except Exception:
            pass
    return (pts[lo][0] + (pts[hi][0] - pts[lo][0]) * f,
            pts[lo][1] + (pts[hi][1] - pts[lo][1]) * f)


def closest_point(guide, x, y, table=None):
    """(point, distance) on the guide nearest (x, y), in metres, or
    (None, inf). This is what the 'Curve' snap uses.

    Projects onto each SEGMENT of the sampled polyline rather than just
    testing the sample points. Testing points alone caps the accuracy at half
    the sample spacing -- 1.25 mm on a 5 m guide at 2000 samples -- which is
    visible when you are trying to land a node exactly on a curve, and is
    exactly the kind of "close enough" that makes a CAD tool feel imprecise.
    Projection is exact for a line and to second order for anything else.
    """
    pts, _cum = table if table is not None else arc_table(guide)
    if not pts:
        return None, float('inf')
    if len(pts) == 1:
        return pts[0], math.hypot(pts[0][0] - x, pts[0][1] - y)
    best, bd = None, float('inf')
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < 1e-18:
            px, py = ax, ay
        else:
            t = ((x - ax) * dx + (y - ay) * dy) / L2
            t = max(0.0, min(1.0, t))
            px, py = ax + t * dx, ay + t * dy
        d = math.hypot(px - x, py - y)
        if d < bd:
            best, bd = (px, py), d
    return best, bd


# ═════════════════════════════════════════════════════════════════════════
#  Fitted guides — defined by what they must satisfy, not by an equation
# ═════════════════════════════════════════════════════════════════════════
#
# "Through these two points, with this rise" is how an arch or a bridge chord
# is actually specified, and it is a far better thing to store than the
# fitted coefficients: keep the CONSTRAINTS and the curve can be re-solved
# when a point moves, so dragging an end handle keeps the rise you asked for.
# Store only the coefficients and the first drag breaks the relationship the
# curve was built on.
#
# A fitted guide therefore looks like:
#
#     {'kind': 'fit', 'family': 'parabola', 'p0': (x, y), 'p1': (x, y),
#      'by': 'rise', 'value': 4.0, 'flip': False}
#
# and `resolve_fit` turns it into one of the primitive guides the rest of
# this module already knows how to sample. Everything downstream -- arc
# length, path arrays, the Curve snap -- works unchanged.
#
# WHAT IS AND IS NOT WELL POSED. Two points plus one scalar determines:
#   parabola   (vertical axis)      3 unknowns, 3 constraints
#   circle     (arc through both)   3 unknowns, 3 constraints
#   catenary   y = a cosh((x-x0)/a) + C, 3 unknowns, 3 constraints
#   ellipse    ONLY once you fix the axis and centre -- see below.
#
# A general ellipse has FIVE degrees of freedom, so two points and a
# perimeter leaves a two-parameter family, not a curve. `semiellipse` here is
# the semi-elliptical arch: centre at the midpoint of the two points, major
# axis along the chord between them. That fixes a = half-chord and leaves b
# as the single unknown, which the perimeter or the rise then determines.
# The general case is `conic5` further down: five points, any conic.

FIT_FAMILIES = ('parabola', 'arc', 'semiellipse', 'catenary')

#: How each family may be pinned down, beyond its two points.
FIT_BY = {
    'parabola':    ('rise',),
    'arc':         ('rise', 'radius', 'length'),
    'semiellipse': ('rise', 'length'),
    'catenary':    ('sag', 'length'),
}


def _chord(p0, p1):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    return math.hypot(dx, dy), dx, dy


def fit_error(fit):
    """Why this fit cannot be solved, or None. Every message says what to
    change, because 'invalid input' in a design tool is a dead end."""
    fam = fit.get('family')
    if fam not in FIT_FAMILIES:
        return 'unknown curve family %r' % (fam,)
    p0, p1 = tuple(fit.get('p0', (0, 0))), tuple(fit.get('p1', (0, 0)))
    c, dx, dy = _chord(p0, p1)
    if c < 1e-9:
        return 'the two points are the same.'
    by = fit.get('by')
    if by not in FIT_BY[fam]:
        return 'a %s cannot be set by %r (use %s)' % (
            fam, by, ' or '.join(FIT_BY[fam]))
    v = float(fit.get('value', 0.0))

    if fam == 'parabola':
        if abs(dx) < 1e-9:
            return ('a vertical-axis parabola needs the two points at '
                    'different x. Rotate the guide or use an arc.')
        if abs(v) < 1e-12:
            return 'rise must be non-zero (zero rise is the straight chord).'
    if fam == 'arc':
        if by == 'radius' and abs(v) < c / 2 - 1e-12:
            return ('radius %.4f is smaller than half the chord (%.4f), so no '
                    'arc can reach both points.' % (abs(v), c / 2))
        if by == 'length' and v <= c + 1e-12:
            return ('arc length must exceed the straight chord (%.4f).' % c)
        if by == 'rise' and abs(v) < 1e-12:
            return 'rise must be non-zero.'
    if fam == 'semiellipse':
        if by == 'length' and v <= c + 1e-12:
            return ('the arc length must exceed the chord (%.4f); as the rise '
                    'goes to zero the half-ellipse collapses onto it.' % c)
        if by == 'rise' and abs(v) < 1e-12:
            return 'rise must be non-zero.'
    if fam == 'catenary':
        if abs(dx) < 1e-9:
            return 'a catenary needs the two points at different x.'
        if by == 'length' and v <= c + 1e-12:
            return ('the cable must be longer than the straight chord '
                    '(%.4f).' % c)
        if by == 'sag' and abs(v) < 1e-12:
            return 'sag must be non-zero.'
    return None


def _bisect(f, lo, hi, tol=1e-12, iters=200):
    """Root of a monotonic f on [lo, hi], or None if it is not bracketed.
    Bisection rather than Newton: every function it is used on here is
    monotonic and cheap, and bisection cannot run away on a bad derivative."""
    flo, fhi = f(lo), f(hi)
    if flo == 0:
        return lo
    if fhi == 0:
        return hi
    if flo * fhi > 0:
        return None
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if fm == 0 or (hi - lo) < tol * max(1.0, abs(mid)):
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return 0.5 * (lo + hi)


def _arc_from_rise(p0, p1, h, flip=False):
    """Circular arc through both points with sagitta h."""
    c, dx, dy = _chord(p0, p1)
    R = (c * c / 4.0 + h * h) / (2.0 * abs(h))
    # centre sits on the perpendicular bisector, |R - h| from the midpoint,
    # on the side away from the bulge
    mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    ux, uy = -dy / c, dx / c                       # unit normal to the chord
    s = -1.0 if (h > 0) != bool(flip) else 1.0
    d = R - abs(h)
    cx, cy = mx + s * ux * d, my + s * uy * d
    a0 = math.degrees(math.atan2(p0[1] - cy, p0[0] - cx))
    a1 = math.degrees(math.atan2(p1[1] - cy, p1[0] - cx))
    # take the sweep that passes through the bulge, not the long way round
    if abs(h) > R:                                  # major arc
        if abs(a1 - a0) < 180:
            a1 = a1 + 360 if a1 < a0 else a1 - 360
    else:
        while a1 - a0 > 180:
            a1 -= 360
        while a1 - a0 < -180:
            a1 += 360
    return {'kind': 'circle', 'c': (cx, cy), 'r': R, 'a0': a0, 'a1': a1}


def resolve_fit(fit):
    """Turn a fitted guide into a primitive guide, or None if unsolvable.

    Everything downstream -- sampling, arc length, path arrays, the Curve
    snap -- then works on the primitive with no knowledge that a fit was
    involved.
    """
    if fit_error(fit) is not None:
        return None
    fam = fit['family']
    p0, p1 = tuple(fit['p0']), tuple(fit['p1'])
    by, v = fit['by'], float(fit['value'])
    flip = bool(fit.get('flip', False))
    c, dx, dy = _chord(p0, p1)

    if fam == 'parabola':
        # y = a x^2 + b x + k through the two points and the rise above the
        # chord midpoint. Three points, one exact linear solve, no iteration.
        xm = (p0[0] + p1[0]) / 2.0
        ym = (p0[1] + p1[1]) / 2.0 + (v if not flip else -v)
        pts = [p0, p1, (xm, ym)]
        A = [[p[0] ** 2, p[0], 1.0] for p in pts]
        b = [p[1] for p in pts]
        sol = _beam_gauss_solve(A, b)
        if sol is None:
            return None
        a_, b_, k_ = sol
        return {'kind': 'func', 'expr': 'A*x^2 + B*x + K',
                'x0': min(p0[0], p1[0]), 'x1': max(p0[0], p1[0]),
                'params': {'A': a_, 'B': b_, 'K': k_}}

    if fam == 'arc':
        if by == 'rise':
            h = v
        elif by == 'radius':
            R = abs(v)
            # sagitta of the minor arc of radius R on this chord
            h = R - math.sqrt(max(R * R - c * c / 4.0, 0.0))
            if flip:
                h = -h
        else:                                   # by == 'length'
            # L = R*theta, c = 2R sin(theta/2)  ->  L/c = theta / (2 sin(theta/2))
            # monotonically increasing in theta on (0, 2pi), so bisect
            target = v / c
            th = _bisect(lambda t: t / (2.0 * math.sin(t / 2.0)) - target,
                         1e-9, 2 * math.pi - 1e-9)
            if th is None:
                return None
            R = v / th
            h = R * (1 - math.cos(th / 2.0))
            if flip:
                h = -h
        return _arc_from_rise(p0, p1, h, flip=False if by != 'rise' else flip)

    if fam == 'semiellipse':
        # Semi-elliptical arch: centre at the chord midpoint, major axis along
        # the chord, so a is fixed by the points and only b is unknown.
        a = c / 2.0
        if by == 'rise':
            b = abs(v)
        else:                                   # by == 'length'
            def half_len(bb):
                return _ellipse_half_length(a, bb)
            hi = max(a, 1.0)
            while half_len(hi) < v and hi < 1e7:
                hi *= 2.0
            b = _bisect(lambda bb: half_len(bb) - v, 1e-9, hi)
            if b is None:
                return None
        ang = math.degrees(math.atan2(dy, dx))
        return {'kind': 'ellipse',
                'c': ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0),
                'a': a, 'b': b, 'rot': ang,
                # 180 -> 0 sweeps from p0 to p1 with sin(theta) >= 0, i.e.
                # bulging to the +normal side of the chord -- UP for a
                # left-to-right chord. Going 180 -> 360 would also run p0 to
                # p1 but bulge DOWN, which would make a positive `rise` mean
                # the opposite of what it means for a parabola and an arc.
                # `flip` is how you ask for the downward one.
                'a0': 180.0,
                'a1': 0.0 if not flip else 360.0}

    if fam == 'catenary':
        X = abs(dx)
        if by == 'length':
            L = v
            k = math.sqrt(max(L * L - dy * dy, 0.0))    # 2a sinh(X/2a)
            if k <= X:
                return None
            # monotonically DECREASING in a: 2a sinh(X/2a) -> inf as a -> 0
            # and -> X as a -> inf, so the root is bracketed for any k > X
            a = _bisect(lambda aa: _two_a_sinh(aa, X) - k, 1e-9, 1e9)
        else:                                   # by == 'sag'
            # Sag measured vertically from the chord at mid-span. Decreasing
            # in a (a flat, stiff catenary is a large a), so the bracket runs
            # the same way as the length case.
            def sag_of(aa):
                try:
                    x0, C = _catenary_place(p0, p1, aa)
                    if x0 is None:
                        return float('inf')
                    xm = (p0[0] + p1[0]) / 2.0
                    ym_chord = (p0[1] + p1[1]) / 2.0
                    return ym_chord - (aa * math.cosh((xm - x0) / aa) + C)
                except (OverflowError, ValueError):
                    return float('inf')
            a = _bisect(lambda aa: sag_of(aa) - abs(v), 1e-6, 1e9)
        if a is None or a <= 0:
            return None
        x0, C = _catenary_place(p0, p1, a)
        if x0 is None:
            return None
        return {'kind': 'func', 'expr': 'A*cosh((x - X0)/A) + C',
                'x0': min(p0[0], p1[0]), 'x1': max(p0[0], p1[0]),
                'params': {'A': a, 'X0': x0, 'C': C}}
    return None


def _two_a_sinh(a, X):
    """2a*sinh(X/2a), guarded against the overflow that small `a` causes.

    The bisection bracket has to start near a = 0, where X/(2a) is enormous
    and sinh overflows a double long before the search gets anywhere useful.
    Returning +inf there is correct in the limit and keeps the root bracketed,
    so bisection walks straight in from the finite side. Cable Web guards the
    same expression for the same reason.
    """
    if a <= 0:
        return float('inf')
    z = X / (2.0 * a)
    if z > 350.0:                # sinh overflows a double around 710
        return float('inf')
    return 2.0 * a * math.sinh(z)


def _catenary_place(p0, p1, a):
    """(x0, C) placing y = a cosh((x-x0)/a) + C through both points, or
    (None, None). Closed form: cosh A - cosh B = 2 sinh((A+B)/2) sinh((A-B)/2)
    turns the two endpoint equations into one asinh."""
    X = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    if abs(X) < 1e-12:
        return None, None
    k = _two_a_sinh(a, abs(X))
    if X < 0:
        k = -k
    if abs(k) < 1e-15 or not math.isfinite(k):
        return None, None
    try:
        x0 = (p0[0] + p1[0]) / 2.0 - a * math.asinh(dy / k)
    except (ValueError, OverflowError):
        return None, None
    C = p0[1] - a * math.cosh((p0[0] - x0) / a)
    return x0, C


def _ellipse_half_length(a, b, n=4000):
    """Arc length of half an ellipse with semi-axes a, b -- i.e. the length
    of the arch itself, which is what a fabricator measures and orders, not
    the full circumference. Numeric rather than Ramanujan's approximation, so
    it agrees exactly with the arc-length table used everywhere else."""
    total = 0.0
    prev = (a, 0.0)
    for i in range(1, n + 1):
        t = math.pi * i / n
        cur = (a * math.cos(t), b * math.sin(t))
        total += math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        prev = cur
    return total


# ═════════════════════════════════════════════════════════════════════════
#  Conic through five points  (GeoGebra's Conic[A,B,C,D,E])
# ═════════════════════════════════════════════════════════════════════════
#
# Five points determine a unique conic. Every row of
#
#     [ x^2  xy  y^2  x  y  1 ]
#
# must annihilate the coefficient vector (A,B,C,D,E,F) of
#
#     A x^2 + B xy + C y^2 + D x + E y + F = 0,
#
# so the coefficients are the null space of a 5x6 matrix -- the last right
# singular vector. This gives ellipse, parabola, hyperbola and circle alike;
# which one you got is decided afterwards by the discriminant B^2 - 4AC.
#
# WHY SAMPLING IS THE HARD PART. A general conic is IMPLICIT, not y = f(x).
# It can be vertical, it can close on itself, and a hyperbola has TWO
# DISCONNECTED BRANCHES. Nothing here can be plotted by stepping x, and a
# naive sampler that did would join the branches of a hyperbola with a
# phantom segment straight across the gap -- which would then be measured as
# real length by the arc-length table and place path-array nodes at
# meaningless spacings, on a part of the curve that does not exist.
#
# So the conic is reduced to canonical form (rotate the xy term away,
# translate to the centre), each branch is parametrised separately, and a
# guide names the ONE branch it refers to. `branch` is ignored by the closed
# forms (ellipse, circle) which have only one.

CONIC_ELLIPSE = 'ellipse'
CONIC_PARABOLA = 'parabola'
CONIC_HYPERBOLA = 'hyperbola'
CONIC_DEGENERATE = 'degenerate'


def conic_from_points(pts):
    """(A, B, C, D, E, F) for the conic through five points, or None.

    Returns None when the points do not determine one: fewer than five, two
    coincident, or a set whose matrix is rank deficient (three or more
    collinear, which admits a whole family of degenerate conics).
    """
    if len(pts) != 5:
        return None
    for i in range(5):
        for j in range(i + 1, 5):
            if math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) < 1e-12:
                return None
    M = np.array([[x * x, x * y, y * y, x, y, 1.0] for (x, y) in pts],
                 dtype=float)
    # Scale each column to unit norm before the SVD. Raw x^2 terms dwarf the
    # constant column on a 20 m span, and that conditioning alone can lose
    # three or four digits of the answer.
    scale = np.linalg.norm(M, axis=0)
    scale[scale < 1e-300] = 1.0
    try:
        _u, sv, vt = np.linalg.svd(M / scale)
    except np.linalg.LinAlgError:
        return None
    # The null space must be exactly ONE dimensional. If sv[-2] is also near
    # zero the system is rank deficient and a whole FAMILY of conics passes
    # through the points -- which is what three or more collinear points give
    # you, since every conic containing that line qualifies. Picking one
    # arbitrarily out of a family and drawing it as "the" conic would be worse
    # than refusing: it looks authoritative and is meaningless.
    if len(sv) >= 2 and sv[-2] <= 1e-9 * max(sv[0], 1e-300):
        return None
    coef = vt[-1] / scale
    n = np.linalg.norm(coef)
    if n < 1e-300 or not np.all(np.isfinite(coef)):
        return None
    coef = coef / n
    A, B, C = coef[0], coef[1], coef[2]
    if max(abs(A), abs(B), abs(C)) < 1e-12:
        return None                     # a straight line, not a conic
    return tuple(float(v) for v in coef)


def conic_kind(coef):
    """Which conic these coefficients describe, by the discriminant."""
    if coef is None:
        return CONIC_DEGENERATE
    A, B, C = coef[0], coef[1], coef[2]
    disc = B * B - 4.0 * A * C
    scale = max(abs(A), abs(B), abs(C), 1e-300)
    if abs(disc) < 1e-9 * scale * scale:
        return CONIC_PARABOLA
    return CONIC_HYPERBOLA if disc > 0 else CONIC_ELLIPSE


def _conic_canonical(coef):
    """Rotate the cross term away and locate the centre/vertex.

    Returns (kind, theta, A2, C2, D2, E2, F2, h, k) in the ROTATED frame,
    where a point is mapped back by
        x = (h + u) cos(theta) - (k + v) sin(theta)
        y = (h + u) sin(theta) + (k + v) cos(theta)
    """
    A, B, C, D, E, F = coef
    theta = 0.0 if abs(B) < 1e-15 else 0.5 * math.atan2(B, A - C)
    ct, st = math.cos(theta), math.sin(theta)
    A2 = A * ct * ct + B * ct * st + C * st * st
    C2 = A * st * st - B * ct * st + C * ct * ct
    D2 = D * ct + E * st
    E2 = -D * st + E * ct
    F2 = F
    return theta, A2, C2, D2, E2, F2


def conic_branches(coef, extent):
    """Parametrisations of the conic, one per branch.

    `extent` is the half-size of the region of interest, used to decide how
    far along an unbounded branch to run. Each entry is a callable
    t in 0..1 -> (x, y).
    """
    kind = conic_kind(coef)
    if kind == CONIC_DEGENERATE:
        return []
    theta, A2, C2, D2, E2, F2 = _conic_canonical(coef)
    ct, st = math.cos(theta), math.sin(theta)

    def back(u, v):
        return (u * ct - v * st, u * st + v * ct)

    tiny = 1e-12 * max(abs(A2), abs(C2), 1.0)

    # ── parabola: one of the squared terms vanishes ──────────────────────
    if abs(A2) <= tiny or abs(C2) <= tiny:
        if abs(A2) <= tiny:
            # C2 v^2 + D2 u + E2 v + F2 = 0  ->  u = -(C2 v^2 + E2 v + F2)/D2
            if abs(D2) < 1e-15:
                return []
            vmax = extent
            def para(t, vmax=vmax):
                v = -vmax + 2 * vmax * t
                u = -(C2 * v * v + E2 * v + F2) / D2
                return back(u, v)
            return [para]
        if abs(E2) < 1e-15:
            return []
        umax = extent
        def para2(t, umax=umax):
            u = -umax + 2 * umax * t
            v = -(A2 * u * u + D2 * u + F2) / E2
            return back(u, v)
        return [para2]

    # ── centred conics: complete both squares ────────────────────────────
    h = -D2 / (2.0 * A2)
    k = -E2 / (2.0 * C2)
    G = -F2 + A2 * h * h + C2 * k * k
    if abs(G) < 1e-15:
        return []                           # a point or a crossed pair

    ra, rc = G / A2, G / C2
    if ra > 0 and rc > 0:                   # ellipse
        a, b = math.sqrt(ra), math.sqrt(rc)
        def ell(t, a=a, b=b, h=h, k=k):
            ang = 2.0 * math.pi * t
            return back(h + a * math.cos(ang), k + b * math.sin(ang))
        return [ell]

    # hyperbola: one positive, one negative
    if ra > 0:
        a, b = math.sqrt(ra), math.sqrt(-rc)
        tmax = math.asinh(max(extent / max(b, 1e-9), 1e-9))
        def hyp(t, s=1.0, a=a, b=b, h=h, k=k, tmax=tmax):
            z = -tmax + 2 * tmax * t
            return back(h + s * a * math.cosh(z), k + b * math.sinh(z))
        return [lambda t: hyp(t, +1.0), lambda t: hyp(t, -1.0)]

    a, b = math.sqrt(-ra), math.sqrt(rc)
    tmax = math.asinh(max(extent / max(a, 1e-9), 1e-9))

    def hyp2(t, s=1.0, a=a, b=b, h=h, k=k, tmax=tmax):
        z = -tmax + 2 * tmax * t
        return back(h + a * math.sinh(z), k + s * b * math.cosh(z))
    return [lambda t: hyp2(t, +1.0), lambda t: hyp2(t, -1.0)]


def conic_extent(pts, margin=1.6):
    """How far to run an unbounded branch: the spread of the defining points,
    scaled. A parabola or hyperbola has no natural end, so the honest choice
    is to draw the part near the points that defined it."""
    if not pts:
        return 10.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    return span * margin


def conic_callable(guide):
    """t -> (x, y) for a 'conic5' guide's selected branch, or None."""
    pts = [tuple(p) for p in guide.get('pts', [])]
    coef = conic_from_points(pts)
    if coef is None:
        return None
    branches = conic_branches(coef, conic_extent(pts))
    if not branches:
        return None
    i = int(guide.get('branch', 0))
    return branches[i % len(branches)]


def conic_describe(guide):
    """'ellipse' / 'parabola' / 'hyperbola (branch 1 of 2)' etc., for the UI."""
    coef = conic_from_points([tuple(p) for p in guide.get('pts', [])])
    kind = conic_kind(coef)
    if kind == CONIC_DEGENERATE:
        return 'degenerate'
    n = len(conic_branches(coef, conic_extent(guide.get('pts', []))))
    if n > 1:
        return '%s (branch %d of %d)' % (kind,
                                         int(guide.get('branch', 0)) % n + 1, n)
    return kind


# ═════════════════════════════════════════════════════════════════════════
#  Handles: what you grab, and what happens when you drag it
# ═════════════════════════════════════════════════════════════════════════
#
# "Where do I grab a curve?" only has a good answer if the grab points MEAN
# something. So a guide's handles are its DEFINING points -- the two ends a
# fitted arch springs from, the five points a conic passes through -- and
# dragging one changes exactly the thing that point defines. Nothing here is
# an arbitrary bounding-box corner.
#
#   y = f(x)   one anchor. A typed expression cannot be reshaped by dragging
#              without rewriting its algebra, so it can be MOVED and its
#              x-range edited numerically, and that is all this pretends to.
#   line       its two endpoints
#   circle     its centre (radius and sweep stay numeric)
#   ellipse    its centre
#   fit        the two points it passes through, plus -- when the fit is by
#              rise or sag -- a shape handle at the crown that sets that
#              value directly
#   conic5     all five points
#
# `set_handle` returns a NEW guide rather than mutating: the caller pushes
# the old one onto the undo stack, and a half-applied drag can never leave a
# guide in a state that was never valid.

HANDLE_END = 'end'          # a defining point
HANDLE_ANCHOR = 'anchor'    # translates the whole guide
HANDLE_SHAPE = 'shape'      # sets the fit's rise/sag


def guide_handles(guide):
    """[(role, (x, y)), ...] in metres, in the order `set_handle` indexes."""
    kind = guide.get('kind')
    if kind == 'line':
        return [(HANDLE_END, tuple(guide['p0'])),
                (HANDLE_END, tuple(guide['p1']))]
    if kind in ('circle', 'ellipse'):
        return [(HANDLE_ANCHOR, tuple(guide['c']))]
    if kind == 'conic5':
        return [(HANDLE_END, tuple(p)) for p in guide.get('pts', [])]
    if kind == 'fit':
        out = [(HANDLE_END, tuple(guide['p0'])),
               (HANDLE_END, tuple(guide['p1']))]
        if guide.get('by') in ('rise', 'sag'):
            crown = _fit_crown(guide)
            if crown is not None:
                out.append((HANDLE_SHAPE, crown))
        return out
    if kind == 'func':
        fn = guide_callable(guide)
        if fn is None:
            return []
        try:
            return [(HANDLE_ANCHOR, fn(0.0))]
        except Exception:
            return []
    return []


def _fit_crown(fit):
    """The point on a fitted curve furthest from its chord -- where the rise
    or sag is measured, and so where its handle belongs."""
    fn = guide_callable(fit)
    if fn is None:
        return None
    p0, p1 = tuple(fit['p0']), tuple(fit['p1'])
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if L < 1e-12:
        return None
    ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
    best, bd = None, -1.0
    for i in range(101):
        try:
            p = fn(i / 100.0)
        except Exception:
            continue
        d = abs(-(p[0] - p0[0]) * uy + (p[1] - p0[1]) * ux)
        if d > bd:
            best, bd = p, d
    return best


def move_guide(guide, dx, dy):
    """A copy of `guide` translated by (dx, dy) metres.

    Every kind can be moved, including `func` -- which is why a func guide
    carries an origin (`ox`, `oy`). A typed y = f(x) is tied to the axes, so
    without that offset "shift this parabola 3 m right" would mean rewriting
    the expression, and a guide you cannot move is not much of a drawing aid.
    """
    gd = copy.deepcopy(guide)
    kind = gd.get('kind')
    if kind == 'line':
        gd['p0'] = (gd['p0'][0] + dx, gd['p0'][1] + dy)
        gd['p1'] = (gd['p1'][0] + dx, gd['p1'][1] + dy)
    elif kind in ('circle', 'ellipse'):
        gd['c'] = (gd['c'][0] + dx, gd['c'][1] + dy)
    elif kind == 'conic5':
        gd['pts'] = [(p[0] + dx, p[1] + dy) for p in gd.get('pts', [])]
    elif kind == 'fit':
        gd['p0'] = (gd['p0'][0] + dx, gd['p0'][1] + dy)
        gd['p1'] = (gd['p1'][0] + dx, gd['p1'][1] + dy)
    elif kind == 'func':
        gd['ox'] = float(gd.get('ox', 0.0)) + dx
        gd['oy'] = float(gd.get('oy', 0.0)) + dy
    return gd


def set_handle(guide, index, x, y):
    """A copy of `guide` with handle `index` moved to (x, y) metres.

    For a fitted guide this re-solves: drag an end point and the curve
    re-fits through the new position keeping the rise you asked for, because
    the guide stores the constraints and not the coefficients.
    """
    handles = guide_handles(guide)
    if not (0 <= index < len(handles)):
        return copy.deepcopy(guide)
    role, old = handles[index]
    gd = copy.deepcopy(guide)
    kind = gd.get('kind')

    if role == HANDLE_ANCHOR:
        return move_guide(gd, x - old[0], y - old[1])

    if kind == 'line':
        gd['p0' if index == 0 else 'p1'] = (x, y)
        return gd
    if kind == 'conic5':
        pts = [tuple(p) for p in gd.get('pts', [])]
        if index < len(pts):
            pts[index] = (x, y)
        gd['pts'] = pts
        return gd
    if kind == 'fit':
        if role == HANDLE_SHAPE:
            # perpendicular distance from the chord IS the rise/sag
            p0, p1 = tuple(gd['p0']), tuple(gd['p1'])
            L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if L < 1e-12:
                return gd
            ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
            off = -(x - p0[0]) * uy + (y - p0[1]) * ux
            gd['value'] = abs(off)
            gd['flip'] = off < 0
            return gd
        gd['p0' if index == 0 else 'p1'] = (x, y)
        return gd
    return gd


def guide_hit(guide, x, y, tol):
    """True when (x, y) is within `tol` metres of the guide's curve. Used to
    click a guide on the canvas rather than only from the list."""
    p, d = closest_point(guide, x, y)
    return p is not None and d <= tol


# ═════════════════════════════════════════════════════════════════════════
#  Arrays
# ═════════════════════════════════════════════════════════════════════════

def path_array(guide, count=None, spacing=None, s_start=0.0, s_end=None):
    """Points evenly spaced ALONG the guide between two arc-length stations.

    Give either `count` (that many points, the first at `s_start` and the
    last at `s_end`) or `spacing` (points every `spacing` metres of curve,
    starting at `s_start`, never past `s_end`).

    `s_start`/`s_end` are distances along the curve in metres; `s_end`
    defaults to the curve's full length. Returns [] rather than raising for
    a request that cannot be honoured -- a count of 1, a negative spacing, a
    guide that will not compile.
    """
    table = arc_table(guide)
    pts, cum = table
    if not pts:
        return []
    L = cum[-1]
    s0 = max(0.0, min(float(s_start), L))
    s1 = L if s_end is None else max(0.0, min(float(s_end), L))
    if s1 < s0:
        s0, s1 = s1, s0
    span = s1 - s0

    if count is not None:
        n = int(count)
        if n < 1:
            return []
        if n == 1:
            return [point_at_arclength(guide, s0, table)]
        step = span / (n - 1)
        return [point_at_arclength(guide, s0 + i * step, table)
                for i in range(n)]

    if spacing is not None:
        d = float(spacing)
        if d <= 1e-12:
            return []
        out = []
        s = s0
        # <= with a tolerance so a span that is an exact multiple of the
        # spacing includes its final point instead of losing it to rounding
        while s <= s1 + 1e-9:
            out.append(point_at_arclength(guide, s, table))
            s += d
        return out
    return []


def grid_array(points, nx, ny, dx, dy):
    """Rectangular array: `points` repeated nx times along x and ny along y,
    at spacings dx, dy (metres). Includes the originals (i=j=0), so nx=ny=1
    returns the input unchanged."""
    nx, ny = max(int(nx), 1), max(int(ny), 1)
    out = []
    for j in range(ny):
        for i in range(nx):
            ox, oy = i * float(dx), j * float(dy)
            out.append([(x + ox, y + oy) for (x, y) in points])
    return out


def polar_array(points, centre, count, total_angle_deg=360.0,
                rotate_items=True):
    """Circular array of `points` about `centre`.

    `count` includes the original. With `total_angle_deg` = 360 the step is
    360/count, so the first and last copies do not land on top of each other;
    with any other sweep the step is `total_angle/(count-1)`, which puts the
    last copy exactly on the end angle. That is the behaviour every CAD tool
    has, and the reason is the same: a full circle is periodic and a partial
    sweep has two distinct ends.

    `rotate_items` also turns each copy about the centre, which is what you
    want for spokes; with it False the copies keep their original
    orientation and are only translated.
    """
    n = max(int(count), 1)
    cx, cy = centre
    full = abs(abs(float(total_angle_deg)) - 360.0) < 1e-9
    step = (float(total_angle_deg) / n if full
            else (float(total_angle_deg) / (n - 1) if n > 1 else 0.0))
    # The un-rotated case needs ONE reference point for the whole item, not a
    # per-point offset: offsetting each point by its own rotation is
    # arithmetically identical to rotating the item, which is the opposite of
    # what rotate_items=False asks for. The item's centroid is the reference.
    if points:
        gx = sum(px for px, _ in points) / len(points)
        gy = sum(py for _, py in points) / len(points)
    else:
        gx = gy = 0.0
    out = []
    for k in range(n):
        a = math.radians(step * k)
        ca, sa = math.cos(a), math.sin(a)
        if rotate_items:
            copy_pts = []
            for (x, y) in points:
                rx, ry = x - cx, y - cy
                copy_pts.append((cx + rx * ca - ry * sa,
                                 cy + rx * sa + ry * ca))
        else:
            rx, ry = gx - cx, gy - cy
            ox = (cx + rx * ca - ry * sa) - gx
            oy = (cy + rx * sa + ry * ca) - gy
            copy_pts = [(x + ox, y + oy) for (x, y) in points]
        out.append(copy_pts)
    return out
