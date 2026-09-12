"""Construction geometry and node arrays for the Truss tab.

Arc length is the part worth testing hardest. "Evenly spaced along the curve"
means equal distance ALONG THE CURVE, not equal steps in x, and on a parabola
those differ a lot -- equal-x spacing bunches nodes where the curve is steep,
which is exactly where a bridge chord needs them spread evenly. Every check
below that involves spacing therefore compares against a CLOSED FORM for the
arc length, not against the sampler's own output:

    line     L = |p1 - p0|
    arc      L = R * theta
    parabola L = [ x*sqrt(1+4a^2x^2)/2 + asinh(2ax)/(4a) ]  for y = a*x^2

The chord-summation table converges from below with error ~1/n^2, so the
tolerances here are loose enough to allow that and tight enough that a real
error in the formulation cannot hide inside them.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.truss import truss_guides as g


LINE = {'kind': 'line', 'p0': (0.0, 0.0), 'p1': (3.0, 4.0)}
ARC = {'kind': 'circle', 'c': (1.0, 2.0), 'r': 5.0, 'a0': 0.0, 'a1': 90.0}
CIRCLE = {'kind': 'circle', 'c': (0.0, 0.0), 'r': 2.0, 'a0': 0.0, 'a1': 360.0}
PARABOLA = {'kind': 'func', 'expr': 'a*x^2', 'x0': 0.0, 'x1': 4.0,
            'params': {'a': 0.25}}
BRIDGE = {'kind': 'func', 'expr': '4*f*x*(L-x)/L^2', 'x0': 0.0, 'x1': 20.0,
          'params': {'L': 20.0, 'f': 4.0}}


def parabola_length(a, b):
    """Exact arc length of y = a*x^2 from x=0 to x=b."""
    u = 2 * a * b
    return b * math.sqrt(1 + u * u) / 2 + math.asinh(u) / (4 * a)


# ── lengths against closed forms ─────────────────────────────────────────────

def test_line_length_is_the_distance_between_its_points():
    assert g.total_length(LINE) == pytest.approx(5.0, rel=1e-12)


def test_arc_length_is_R_theta():
    assert g.total_length(ARC) == pytest.approx(5.0 * math.pi / 2, rel=1e-6)
    assert g.total_length(CIRCLE) == pytest.approx(2 * math.pi * 2.0, rel=1e-6)


def test_parabola_length_matches_the_analytic_integral():
    """Measured error at the default 2000 samples is 1.3e-8 relative -- about
    0.07 microns on a 6 m curve. The tolerance is set just above that
    measured value rather than at a round number, so a real regression in the
    sampler shows up instead of being absorbed."""
    exact = parabola_length(0.25, 4.0)
    got = g.total_length(PARABOLA)
    assert got == pytest.approx(exact, rel=2e-8)
    assert got < exact                       # chords are always short


def test_chord_summation_converges_from_below_as_samples_increase():
    """A polyline through points ON a curve is always shorter than the curve,
    so the table must approach the true length from below and never overshoot
    -- an overshoot would mean the sampler is leaving the curve."""
    exact = parabola_length(0.25, 4.0)
    prev = 0.0
    for n in (8, 32, 128, 512, 2048):
        L = g.total_length(PARABOLA, n)
        assert L < exact + 1e-12, (n, L, exact)
        assert L > prev, (n, L, prev)
        prev = L
    assert prev == pytest.approx(exact, rel=2e-8)


# ── point_at_arclength ───────────────────────────────────────────────────────

def test_point_at_arclength_on_a_line_is_exact():
    p = g.point_at_arclength(LINE, 2.5)          # halfway along a 5 m line
    assert p[0] == pytest.approx(1.5, abs=1e-9)
    assert p[1] == pytest.approx(2.0, abs=1e-9)


def test_point_at_arclength_on_an_arc_is_exact():
    L = g.total_length(ARC)
    p = g.point_at_arclength(ARC, L / 2)         # 45 degrees round
    r2 = math.sqrt(2) / 2
    assert p[0] == pytest.approx(1.0 + 5.0 * r2, abs=1e-4)
    assert p[1] == pytest.approx(2.0 + 5.0 * r2, abs=1e-4)


def test_arclength_is_clamped_not_wrapped():
    L = g.total_length(LINE)
    assert g.point_at_arclength(LINE, -10.0) == pytest.approx((0.0, 0.0), abs=1e-9)
    assert g.point_at_arclength(LINE, L + 10.0) == pytest.approx((3.0, 4.0), abs=1e-9)


# ── path array ───────────────────────────────────────────────────────────────

def bridge_arc(x_a, x_b, n=20001):
    """Arc length of the BRIDGE parabola between two x values, by Simpson on
    the exact integrand sqrt(1 + y'^2). Deliberately independent of
    truss_guides: measuring the module's evenness with the module's own
    arc-length table would only prove it agrees with itself."""
    L, f = 20.0, 4.0

    def dydx(x):
        return 4 * f * (L - 2 * x) / L ** 2

    def integrand(x):
        return math.sqrt(1 + dydx(x) ** 2)

    if n % 2 == 0:
        n += 1
    h = (x_b - x_a) / (n - 1)
    total = integrand(x_a) + integrand(x_b)
    for i in range(1, n - 1):
        total += integrand(x_a + i * h) * (4 if i % 2 else 2)
    return total * h / 3


def test_path_array_by_count_is_evenly_spaced_along_the_curve():
    """THE point of the feature. Consecutive gaps measured along the curve
    must be equal; measured in x they must NOT be, on a parabola."""
    pts = g.path_array(BRIDGE, count=9)
    assert len(pts) == 9
    gaps = [bridge_arc(a[0], b[0]) for a, b in zip(pts, pts[1:])]
    assert max(gaps) - min(gaps) < 1e-6 * max(gaps), gaps
    # ...and the x-steps must NOT be uniform, or this is spacing in x
    dxs = [b[0] - a[0] for a, b in zip(pts, pts[1:])]
    assert max(dxs) - min(dxs) > 0.15 * max(dxs), dxs
    # the gaps really are the whole curve divided evenly
    total = bridge_arc(0.0, 20.0)
    assert sum(gaps) == pytest.approx(total, rel=1e-9)
    assert gaps[0] == pytest.approx(total / 8, rel=1e-6)


def test_path_array_endpoints_land_on_the_requested_stations():
    L = g.total_length(BRIDGE)
    pts = g.path_array(BRIDGE, count=5)
    assert pts[0] == pytest.approx(g.point_at_arclength(BRIDGE, 0.0), abs=1e-9)
    assert pts[-1] == pytest.approx(g.point_at_arclength(BRIDGE, L), abs=1e-9)
    # and a sub-range starts and ends where asked
    sub = g.path_array(BRIDGE, count=4, s_start=5.0, s_end=15.0)
    assert sub[0] == pytest.approx(g.point_at_arclength(BRIDGE, 5.0), abs=1e-6)
    assert sub[-1] == pytest.approx(g.point_at_arclength(BRIDGE, 15.0), abs=1e-6)


def test_path_array_by_spacing_steps_by_that_distance_along_the_curve():
    pts = g.path_array(LINE, spacing=1.0)        # 5 m line
    assert len(pts) == 6                          # 0,1,2,3,4,5
    for a, b in zip(pts, pts[1:]):
        assert math.hypot(b[0]-a[0], b[1]-a[1]) == pytest.approx(1.0, rel=1e-9)


def test_path_array_refuses_impossible_requests_instead_of_guessing():
    assert g.path_array(LINE, count=0) == []
    assert g.path_array(LINE, spacing=0.0) == []
    assert g.path_array(LINE, spacing=-2.0) == []
    assert g.path_array(LINE) == []                       # neither given
    assert g.path_array({'kind': 'func', 'expr': 'nonsense('}, count=3) == []
    # a count of 1 is legal and gives the start station
    assert g.path_array(LINE, count=1) == [pytest.approx((0.0, 0.0), abs=1e-9)]


def test_reversed_stations_are_normalised_rather_than_returning_nothing():
    a = g.path_array(BRIDGE, count=4, s_start=15.0, s_end=5.0)
    b = g.path_array(BRIDGE, count=4, s_start=5.0, s_end=15.0)
    assert len(a) == len(b) == 4
    assert a[0] == pytest.approx(b[0], abs=1e-9)


# ── grid array ───────────────────────────────────────────────────────────────

def test_grid_array_includes_the_original_and_steps_by_the_spacing():
    src = [(0.0, 0.0), (1.0, 0.0)]
    out = g.grid_array(src, nx=3, ny=2, dx=2.0, dy=5.0)
    assert len(out) == 6
    assert out[0] == [pytest.approx(p, abs=1e-12) for p in src]
    xs = sorted({round(p[0], 6) for copy in out for p in copy})
    ys = sorted({round(p[1], 6) for copy in out for p in copy})
    assert xs == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    assert ys == [0.0, 5.0]


def test_a_one_by_one_grid_returns_the_input_unchanged():
    src = [(1.0, 2.0), (3.0, 4.0)]
    assert g.grid_array(src, 1, 1, 9.0, 9.0) == [src]


# ── polar array ──────────────────────────────────────────────────────────────

def test_polar_array_over_a_full_circle_does_not_double_the_start():
    """360 degrees is periodic, so the step is total/count -- otherwise the
    last copy lands exactly on the first."""
    out = g.polar_array([(1.0, 0.0)], centre=(0.0, 0.0), count=4)
    assert len(out) == 4
    got = sorted((round(c[0][0], 9), round(c[0][1], 9)) for c in out)
    want = sorted((round(math.cos(math.radians(a)), 9),
                   round(math.sin(math.radians(a)), 9))
                  for a in (0, 90, 180, 270))
    assert got == want


def test_polar_array_over_a_partial_sweep_lands_on_the_end_angle():
    out = g.polar_array([(1.0, 0.0)], centre=(0.0, 0.0), count=3,
                        total_angle_deg=90.0)
    assert len(out) == 3
    assert out[-1][0][0] == pytest.approx(0.0, abs=1e-9)
    assert out[-1][0][1] == pytest.approx(1.0, abs=1e-9)


def test_polar_array_preserves_the_radius_of_every_copy():
    src = [(2.0, 0.0), (3.0, 1.0)]
    out = g.polar_array(src, centre=(0.0, 0.0), count=7, total_angle_deg=360.0)
    for copy in out:
        for (x, y), (sx, sy) in zip(copy, src):
            assert math.hypot(x, y) == pytest.approx(math.hypot(sx, sy), rel=1e-9)


def test_polar_array_without_rotation_keeps_item_orientation():
    """rotate_items=False moves each copy round the circle but does not turn
    it, so the vector between two points in a copy is unchanged."""
    src = [(2.0, 0.0), (2.0, 1.0)]
    out = g.polar_array(src, centre=(0.0, 0.0), count=4, rotate_items=False)
    for copy in out:
        vx = copy[1][0] - copy[0][0]
        vy = copy[1][1] - copy[0][1]
        assert vx == pytest.approx(0.0, abs=1e-9)
        assert vy == pytest.approx(1.0, abs=1e-9)


# ── guide compilation and errors ─────────────────────────────────────────────

def test_a_broken_expression_reports_why_instead_of_raising():
    bad = {'kind': 'func', 'expr': '4*x +', 'x0': 0.0, 'x1': 1.0}
    assert g.guide_callable(bad) is None
    assert g.guide_error(bad)
    assert g.sample(bad) == []
    assert g.total_length(bad) == 0.0


def test_degenerate_guides_report_why():
    assert g.guide_error({'kind': 'circle', 'c': (0, 0), 'r': 0.0})
    assert g.guide_error({'kind': 'line', 'p0': (1, 1), 'p1': (1, 1)})
    assert g.guide_error({'kind': 'func', 'expr': 'x', 'x0': 2.0, 'x1': 2.0})
    assert g.guide_error(LINE) is None
    assert g.guide_error(BRIDGE) is None


def test_expressions_accept_the_notation_people_actually_write():
    """`make_shape_fn` allows ^ for powers and implicit multiplication; the
    bridge parabola is the case that matters and it must compile."""
    fn = g.guide_callable(BRIDGE)
    assert fn is not None
    # apex of 4f x(L-x)/L^2 at x = L/2 is y = f
    assert fn(0.5)[1] == pytest.approx(4.0, rel=1e-12)
    assert fn(0.0)[1] == pytest.approx(0.0, abs=1e-12)
    assert fn(1.0)[1] == pytest.approx(0.0, abs=1e-12)


def test_closest_point_finds_the_curve():
    p, d = g.closest_point(LINE, 1.5, 2.0)       # a point ON the line
    assert d < 1e-3
    assert p[0] == pytest.approx(1.5, abs=1e-2)
    p2, d2 = g.closest_point(LINE, 0.0, 5.0)
    assert d2 > 0.5 and p2 is not None


# ── fitted guides: 2 points + one property ───────────────────────────────────
#
# These are checked against what was ASKED FOR, not against a stored answer: a
# fit is correct exactly when the resulting curve passes through both points
# and actually has the rise / radius / length that was requested. That keeps
# the tests independent of how the fit is computed, so a rewrite of the solver
# is still held to the same standard.

P0, P1 = (0.0, 0.0), (20.0, 0.0)


def fit(family, by, value, p0=P0, p1=P1, **kw):
    return dict({'kind': 'fit', 'family': family, 'p0': p0, 'p1': p1,
                 'by': by, 'value': value}, **kw)


def endpoints_of(f):
    fn = g.guide_callable(f)
    assert fn is not None, g.fit_error(f)
    return fn(0.0), fn(1.0)


def peak_offset(f, n=400):
    """Largest perpendicular offset of the curve from its chord."""
    fn = g.guide_callable(f)
    (x0, y0), (x1, y1) = fn(0.0), fn(1.0)
    L = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    best = 0.0
    for i in range(n + 1):
        px, py = fn(i / n)
        best = max(best, abs(-(px - x0) * uy + (py - y0) * ux))
    return best


@pytest.mark.parametrize('family,by,value', [
    ('parabola', 'rise', 4.0),
    ('arc', 'rise', 4.0),
    ('arc', 'radius', 15.0),
    ('arc', 'length', 24.0),
    ('semiellipse', 'rise', 5.0),
    ('semiellipse', 'length', 26.0),
    ('catenary', 'length', 24.0),
    ('catenary', 'sag', 4.0),
])
def test_every_fit_passes_through_both_of_its_points(family, by, value):
    """Whatever else a fit gets right, it must hit the two points it was
    given. This is the check that catches a sign error in the placement."""
    f = fit(family, by, value)
    assert g.fit_error(f) is None, g.fit_error(f)
    first, last = endpoints_of(f)
    assert first == pytest.approx(P0, abs=1e-7), (family, by)
    assert last == pytest.approx(P1, abs=1e-7), (family, by)


def test_parabola_rise_is_exactly_what_was_asked_for():
    f = fit('parabola', 'rise', 4.0)
    fn = g.guide_callable(f)
    assert fn(0.5)[1] == pytest.approx(4.0, abs=1e-9)
    # and it really is a parabola: the second difference is constant
    ys = [fn(t / 20)[1] for t in range(21)]
    d2 = [ys[i + 2] - 2 * ys[i + 1] + ys[i] for i in range(len(ys) - 2)]
    assert max(d2) - min(d2) < 1e-9


def test_arc_by_radius_has_that_radius_and_by_rise_that_rise():
    prim = g.resolve_fit(fit('arc', 'radius', 15.0))
    assert prim['r'] == pytest.approx(15.0, rel=1e-12)
    assert peak_offset(fit('arc', 'rise', 4.0)) == pytest.approx(4.0, abs=1e-3)


def test_arc_by_length_has_that_arc_length_exactly():
    """Checked as R*theta, which is exact, rather than through the sampled arc
    table -- that table converges from below and its 1e-6 error would
    otherwise be mistaken for an error in the fit itself."""
    prim = g.resolve_fit(fit('arc', 'length', 24.0))
    sweep = math.radians(abs(prim['a1'] - prim['a0']))
    assert prim['r'] * sweep == pytest.approx(24.0, rel=1e-9)


def test_arc_radius_smaller_than_half_the_chord_is_refused_with_a_reason():
    err = g.fit_error(fit('arc', 'radius', 5.0))     # the chord is 20
    assert err and 'half the chord' in err
    assert g.resolve_fit(fit('arc', 'radius', 5.0)) is None


def test_semiellipse_is_the_arch_form_with_a_fixed_by_the_points():
    """Two points and a perimeter do NOT determine a general ellipse -- it has
    five degrees of freedom. This family is the semi-elliptical arch: centre on
    the chord midpoint, major axis along the chord, so `a` is fixed by the
    points and only `b` is solved for."""
    prim = g.resolve_fit(fit('semiellipse', 'rise', 5.0))
    assert prim['kind'] == 'ellipse'
    assert prim['a'] == pytest.approx(10.0, rel=1e-12)      # half the chord
    assert prim['b'] == pytest.approx(5.0, rel=1e-12)
    assert prim['c'] == pytest.approx((10.0, 0.0), abs=1e-12)


def test_semiellipse_by_length_gives_that_arc_length():
    """The input is the length of the ARCH ITSELF -- the half-ellipse that is
    drawn -- not the full ellipse circumference. That is the number someone
    setting the curve out actually measures."""
    f = fit('semiellipse', 'length', 26.0)
    assert g.total_length(f) == pytest.approx(26.0, rel=1e-4)
    # a longer arc means a taller arch, over the same two points
    b_small = g.resolve_fit(fit('semiellipse', 'length', 22.0))['b']
    b_big = g.resolve_fit(fit('semiellipse', 'length', 30.0))['b']
    assert b_small < b_big


def test_catenary_by_length_and_by_sag():
    f = fit('catenary', 'length', 24.0)
    assert g.total_length(f) == pytest.approx(24.0, rel=1e-5)
    prim = g.resolve_fit(fit('catenary', 'sag', 4.0))
    a = prim['params']['A']
    x0 = prim['params']['X0']
    C = prim['params']['C']
    sag = 0.0 - (a * math.cosh((10.0 - x0) / a) + C)
    assert sag == pytest.approx(4.0, abs=1e-6)


def test_catenary_handles_unequal_end_heights():
    """The level-span relation 2a*sinh(X/2a) = L is not enough once the ends
    differ in height; the length term becomes sqrt(L^2 - dy^2)."""
    f = fit('catenary', 'length', 26.0, p1=(20.0, 6.0))
    assert g.fit_error(f) is None
    first, last = endpoints_of(f)
    assert first[1] == pytest.approx(0.0, abs=1e-9)
    assert last[1] == pytest.approx(6.0, abs=1e-9)
    assert g.total_length(f) == pytest.approx(26.0, rel=1e-5)


def test_a_catenary_shorter_than_its_chord_is_refused():
    err = g.fit_error(fit('catenary', 'length', 15.0))   # the chord is 20
    assert err and 'longer than the straight chord' in err


def test_fits_are_associative_moving_a_point_re_solves_the_curve():
    """The reason constraints are stored instead of coefficients: move an end
    point and the curve re-fits, keeping the property that was asked for."""
    f = fit('parabola', 'rise', 4.0)
    assert g.guide_callable(f)(1.0)[0] == pytest.approx(20.0)
    f['p1'] = (30.0, 2.0)                       # drag the right-hand end
    fn = g.guide_callable(f)
    assert fn(0.0) == pytest.approx((0.0, 0.0), abs=1e-9)
    assert fn(1.0) == pytest.approx((30.0, 2.0), abs=1e-9)
    # the rise it was given is still the rise it has, above the NEW chord
    assert fn(0.5)[1] - 1.0 == pytest.approx(4.0, abs=1e-9)


def test_a_fit_works_everywhere_a_primitive_guide_does():
    """Arc length, path arrays and the Curve snap must not care whether the
    guide was fitted or typed."""
    f = fit('parabola', 'rise', 4.0)
    assert g.total_length(f) > 20.0
    pts = g.path_array(f, count=5)
    assert len(pts) == 5
    assert pts[0] == pytest.approx(P0, abs=1e-6)
    assert pts[-1] == pytest.approx(P1, abs=1e-6)
    p, d = g.closest_point(f, 10.0, 4.2)
    assert d < 0.25 and p is not None


def test_unsolvable_fits_report_why_and_sample_to_nothing():
    for bad in (fit('parabola', 'rise', 4.0, p0=(0.0, 0.0), p1=(0.0, 5.0)),
                fit('arc', 'length', 10.0),
                fit('semiellipse', 'length', 12.0),
                fit('catenary', 'length', 5.0),
                fit('parabola', 'radius', 4.0)):
        assert g.fit_error(bad), bad
        assert g.guide_callable(bad) is None
        assert g.sample(bad) == []
        assert g.total_length(bad) == 0.0


# ── conic through five points ────────────────────────────────────────────────
#
# Checked by REBUILDING a curve whose equation is already known, and asking
# whether the fit recovers it. That is stronger than comparing to stored
# coefficients: the coefficient vector is only defined up to scale, so two
# correct answers can look completely different.

def on_conic(coef, p):
    """A x^2 + Bxy + Cy^2 + Dx + Ey + F, which is zero on the curve."""
    A, B, C, D, E, F = coef
    x, y = p
    return A * x * x + B * x * y + C * y * y + D * x + E * y + F


def circle_pts(cx, cy, r, angles):
    return [(cx + r * math.cos(a), cy + r * math.sin(a)) for a in angles]


def test_five_points_on_a_circle_give_back_that_circle():
    pts = circle_pts(2.0, 1.0, 5.0, (0.3, 1.1, 2.0, 3.4, 5.0))
    coef = g.conic_from_points(pts)
    assert coef is not None
    assert g.conic_kind(coef) == g.CONIC_ELLIPSE      # a circle is an ellipse
    fn = g.guide_callable({'kind': 'conic5', 'pts': pts, 'branch': 0})
    for i in range(51):
        x, y = fn(i / 50)
        assert math.hypot(x - 2.0, y - 1.0) == pytest.approx(5.0, abs=1e-9)


def test_a_rotated_ellipse_is_recovered_including_its_tilt():
    th = math.radians(30.0)
    ct, st = math.cos(th), math.sin(th)

    def ell(t):
        u, v = 8.0 * math.cos(t), 3.0 * math.sin(t)
        return (1.0 + u * ct - v * st, -2.0 + u * st + v * ct)

    pts = [ell(a) for a in (0.2, 1.0, 2.2, 3.6, 5.1)]
    coef = g.conic_from_points(pts)
    assert g.conic_kind(coef) == g.CONIC_ELLIPSE
    fn = g.guide_callable({'kind': 'conic5', 'pts': pts, 'branch': 0})
    # every sampled point satisfies the conic equation
    assert max(abs(on_conic(coef, fn(i / 80))) for i in range(81)) < 1e-12
    # ...and the curve really is 16 x 6, tilted: its extreme radius from the
    # centre is the major semi-axis
    rs = [math.hypot(fn(i / 200)[0] - 1.0, fn(i / 200)[1] + 2.0)
          for i in range(201)]
    assert max(rs) == pytest.approx(8.0, abs=1e-6)
    assert min(rs) == pytest.approx(3.0, abs=1e-6)


def test_a_parabola_is_classified_and_reproduced():
    def f(x):
        return 0.4 * x * x - 2.0 * x + 1.0

    pts = [(x, f(x)) for x in (-3.0, -1.0, 0.0, 2.0, 5.0)]
    coef = g.conic_from_points(pts)
    assert g.conic_kind(coef) == g.CONIC_PARABOLA
    fn = g.guide_callable({'kind': 'conic5', 'pts': pts, 'branch': 0})
    worst = max(abs(fn(i / 100)[1] - f(fn(i / 100)[0])) for i in range(101))
    assert worst < 1e-9, worst


def hyperbola_pts():
    def h(s, t):
        return (s * 2.0 * math.cosh(t), 3.0 * math.sinh(t))
    return [h(1, -1.0), h(1, -0.2), h(1, 0.5), h(1, 1.2), h(-1, 0.4)]


def test_a_hyperbola_gives_two_branches_and_they_are_separate():
    """The branches must not be joined. A sampler that stepped x would bridge
    the gap between them with a phantom segment, and the arc-length table
    would then measure that segment as real curve -- putting path-array nodes
    at meaningless spacings on a part of the conic that does not exist."""
    pts = hyperbola_pts()
    coef = g.conic_from_points(pts)
    assert g.conic_kind(coef) == g.CONIC_HYPERBOLA
    branches = g.conic_branches(coef, g.conic_extent(pts))
    assert len(branches) == 2

    left, right = [], []
    for b in branches:
        xs = [b(i / 40)[0] for i in range(41)]
        (right if max(xs) > 0 else left).append(xs)
    assert len(left) == 1 and len(right) == 1
    # the two branches live on opposite sides of the asymptote gap, and
    # neither one crosses it
    assert max(left[0]) <= -2.0 + 1e-9
    assert min(right[0]) >= 2.0 - 1e-9
    # every sampled point is on the conic
    for b in branches:
        assert max(abs(on_conic(coef, b(i / 40))) for i in range(41)) < 1e-10


def test_arc_length_along_a_hyperbola_branch_never_jumps_the_gap():
    """The practical consequence of the branches being separate: consecutive
    samples stay close, so the arc-length table measures real curve only."""
    pts = hyperbola_pts()
    for branch in (0, 1):
        gd = {'kind': 'conic5', 'pts': pts, 'branch': branch}
        samples = [p for p in g.sample(gd, 400) if p is not None]
        steps = [math.hypot(b[0] - a[0], b[1] - a[1])
                 for a, b in zip(samples, samples[1:])]
        assert max(steps) < 20 * (sum(steps) / len(steps)), max(steps)


def test_the_two_branches_are_different_curves():
    pts = hyperbola_pts()
    a = g.guide_callable({'kind': 'conic5', 'pts': pts, 'branch': 0})(0.5)
    b = g.guide_callable({'kind': 'conic5', 'pts': pts, 'branch': 1})(0.5)
    assert math.hypot(a[0] - b[0], a[1] - b[1]) > 1.0
    assert 'branch 1 of 2' in g.conic_describe({'kind': 'conic5', 'pts': pts,
                                                'branch': 0})
    assert 'branch 2 of 2' in g.conic_describe({'kind': 'conic5', 'pts': pts,
                                                'branch': 1})


def test_a_conic_passes_through_all_five_of_its_points():
    pts = [(0.0, 0.0), (1.0, 2.0), (3.0, 1.0), (4.0, 5.0), (6.0, 2.0)]
    coef = g.conic_from_points(pts)
    assert coef is not None
    for p in pts:
        assert abs(on_conic(coef, p)) < 1e-10, p


def test_degenerate_five_point_sets_are_refused_with_a_reason():
    """Refused at the GUIDE level, which is what the UI asks. Three collinear
    points still determine a unique conic -- it is just a degenerate line
    pair, which has no branch to draw and must not be presented as a curve."""
    for pts, why in (
            ([(0, 0), (1, 1), (2, 2), (3, 7), (5, 1)], 'collinear triple'),
            ([(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)], 'all collinear'),
            ([(0, 0), (0, 0), (2, 2), (3, 7), (5, 1)], 'repeated point'),
            ([(0, 0), (1, 1), (2, 4)], 'too few points')):
        gd = {'kind': 'conic5', 'pts': pts, 'branch': 0}
        assert g.guide_error(gd), why
        assert g.guide_callable(gd) is None, why
        assert g.sample(gd) == [], why


def test_a_conic_works_with_path_arrays_and_the_curve_snap():
    """Same requirement as a fitted guide: once defined, the rest of the
    module must not care how the curve came to exist."""
    pts = circle_pts(0.0, 0.0, 6.0, (0.2, 1.3, 2.4, 3.9, 5.2))
    gd = {'kind': 'conic5', 'pts': pts, 'branch': 0}
    L = g.total_length(gd)
    assert L == pytest.approx(2 * math.pi * 6.0, rel=1e-5)
    nodes = g.path_array(gd, count=8)
    assert len(nodes) == 8
    for x, y in nodes:
        assert math.hypot(x, y) == pytest.approx(6.0, abs=1e-6)
    p, d = g.closest_point(gd, 6.4, 0.0)
    assert d == pytest.approx(0.4, abs=1e-3)


@pytest.mark.parametrize('family,by,value', [
    ('parabola', 'rise', 4.0),
    ('arc', 'rise', 4.0),
    ('arc', 'radius', 15.0),
    ('arc', 'length', 24.0),
    ('semiellipse', 'rise', 5.0),
    ('semiellipse', 'length', 26.0),
])
def test_rise_means_up_for_every_arch_family(family, by, value):
    """One convention across families, because the alternative is a UI where
    "rise 5" raises a parabola and lowers an ellipse. The semi-ellipse was
    exactly that until its sweep direction was corrected: 180 -> 360 also runs
    p0 to p1, but bulges the wrong way."""
    f = fit(family, by, value)
    fn = g.guide_callable(f)
    ys = [fn(t / 100.0)[1] for t in range(101)]
    assert max(ys, key=abs) > 0, '%s by %s bulges downward for a positive rise' % (family, by)


@pytest.mark.parametrize('by,value', [('sag', 4.0), ('length', 24.0)])
def test_sag_means_down_for_a_catenary(by, value):
    """And the catenary is NOT an exception to fix: its parameter is sag, not
    rise, and a hanging cable goes down. The word carries the sign."""
    fn = g.guide_callable(fit('catenary', by, value))
    ys = [fn(t / 100.0)[1] for t in range(101)]
    assert max(ys, key=abs) < 0


def test_flip_mirrors_a_fit_about_its_chord():
    up = g.guide_callable(fit('semiellipse', 'rise', 5.0))
    down = g.guide_callable(dict(fit('semiellipse', 'rise', 5.0), flip=True))
    a = max((up(t / 100.0)[1] for t in range(101)), key=abs)
    b = max((down(t / 100.0)[1] for t in range(101)), key=abs)
    assert a == pytest.approx(-b, rel=1e-9)


def test_every_fit_runs_from_p0_to_p1_not_backwards():
    """Path arrays measure arc length from the start of the curve, so a
    family that ran p1 -> p0 would put 'start s = 2 m' at the wrong end."""
    for family, by, value in (('parabola', 'rise', 4.0), ('arc', 'rise', 4.0),
                              ('semiellipse', 'rise', 5.0),
                              ('catenary', 'sag', 4.0)):
        fn = g.guide_callable(fit(family, by, value))
        assert fn(0.0) == pytest.approx(P0, abs=1e-7), family
        assert fn(1.0) == pytest.approx(P1, abs=1e-7), family
