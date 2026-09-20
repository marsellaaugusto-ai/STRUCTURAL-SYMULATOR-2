"""Bezier profiles, the surfaces built from them, and the fit that turns a
typed formula into something editable (apps/stereo/stereo_bezier.py).

The property that matters most here is not accuracy -- it is that editing
BEHAVES. A chain whose segments do not join, or whose control points do
something other than what dragging them looks like it should do, is
useless however well it fits.
"""
import math

import pytest

from apps.stereo import stereo_bezier as bz
from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_math as sm


SIN2 = (lambda x: math.sin(2 * x), 0.0, 2 * math.pi)
VASE = (lambda h: 3.0 + 1.6 * math.sin(h * 0.9), 0.0, 6.0)
COSH = (lambda x: math.cosh(x), -2.0, 2.0)


# ── the fit ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('case,segments,limit', [
    (SIN2, 12, 0.002), (SIN2, 20, 0.0005),
    (VASE, 12, 0.001), (COSH, 12, 0.0005),
])
def test_the_fit_is_as_close_as_it_claims(case, segments, limit):
    """The docstring publishes a table of errors. If the code drifts away
    from it the table becomes a lie, so the table is a test."""
    f, a, b = case
    profile = bz.fit_profile(f, a, b, segments)
    _worst, frac = bz.fit_error(profile, f)
    assert frac < limit


def test_more_segments_fit_better():
    f, a, b = SIN2
    errors = [bz.fit_error(bz.fit_profile(f, a, b, n), f)[1] for n in (4, 8, 12, 20)]
    assert errors == sorted(errors, reverse=True)


def test_the_fit_passes_exactly_through_the_function_at_every_knot():
    """Hermite INTERPOLATES. That is the property that makes the knots
    meaningful as handles -- each one is a point the curve is known to go
    through, not a number that came out of a minimisation."""
    f, a, b = SIN2
    profile = bz.fit_profile(f, a, b, 8)
    for k in range(9):
        x = a + (b - a) * k / 8
        assert bz.profile_value(profile, x) == pytest.approx(f(x), abs=1e-9)


def test_a_fitted_chain_is_smooth_everywhere():
    for case in (SIN2, VASE, COSH):
        f, a, b = case
        assert bz.is_smooth(bz.fit_profile(f, a, b, 12))


def test_segments_share_their_joining_control_point():
    """C0 is a property of the REPRESENTATION here, not something to
    maintain: there is only one number at a joint, so the two segments
    cannot disagree about it."""
    f, a, b = SIN2
    profile = bz.fit_profile(f, a, b, 6)
    assert len(profile['ctrl']) == 3 * 6 + 1
    for k in range(5):
        left = profile['ctrl'][3 * k:3 * k + 4]
        right = profile['ctrl'][3 * (k + 1):3 * (k + 1) + 4]
        assert left[-1] == right[0]


def test_a_degenerate_range_is_refused():
    with pytest.raises(ValueError):
        bz.fit_profile(lambda x: x, 4.0, 4.0, 8)


# ── editing ────────────────────────────────────────────────────────────────

def test_moving_a_knot_takes_its_handles_with_it():
    """Otherwise the curve tears away from its own tangents and the point
    you dragged is the one place the curve does not go -- which looks
    exactly like a bug."""
    f, a, b = SIN2
    profile = bz.fit_profile(f, a, b, 8)
    knot = 3            # flat index of the first interior knot
    before = list(profile['ctrl'])
    bz.set_control(profile, knot, before[knot] + 1.0)
    assert profile['ctrl'][knot] == pytest.approx(before[knot] + 1.0)
    assert profile['ctrl'][knot - 1] == pytest.approx(before[knot - 1] + 1.0)
    assert profile['ctrl'][knot + 1] == pytest.approx(before[knot + 1] + 1.0)
    x = a + (b - a) / 8
    assert bz.profile_value(profile, x) == pytest.approx(before[knot] + 1.0, abs=1e-9)


def test_moving_a_handle_keeps_the_curve_smooth():
    f, a, b = SIN2
    profile = bz.fit_profile(f, a, b, 8)
    bz.set_control(profile, 4, profile['ctrl'][4] + 2.0)
    assert bz.is_smooth(profile)


def test_a_crease_is_possible_when_it_is_asked_for():
    """Smooth by default, but a deliberate kink is a real design move and
    refusing it would be the tool deciding."""
    f, a, b = SIN2
    profile = bz.fit_profile(f, a, b, 8)
    bz.set_control(profile, 4, profile['ctrl'][4] + 2.0, keep_smooth=False)
    assert not bz.is_smooth(profile)


def test_smoothing_a_joint_averages_rather_than_picking_a_winner():
    """Mirroring one handle onto the other makes the result depend on which
    side you dragged, so dragging the same joint from alternate sides walks
    it away across repeated edits."""
    profile = {'a': 0.0, 'b': 2.0, 'segments': 2,
               'ctrl': [0.0, 1.0, 2.0, 3.0, 9.0, 5.0, 6.0]}
    bz.enforce_c1(profile, 1)
    assert bz.is_smooth(profile)
    # the knot itself did not move; only its two handles did
    assert profile['ctrl'][3] == 3.0
    assert profile['ctrl'][2] == pytest.approx(3.0 - 3.5)
    assert profile['ctrl'][4] == pytest.approx(3.0 + 3.5)


def test_moving_a_control_outside_the_profile_is_refused():
    f, a, b = SIN2
    profile = bz.fit_profile(f, a, b, 4)
    with pytest.raises(IndexError):
        bz.set_control(profile, 999, 1.0)


def test_evaluating_outside_the_range_clamps_instead_of_extrapolating():
    """A Bezier outside its own parameter range is a fantasy that grows
    fast. Clamping gives the end value, which is at least a point on the
    curve."""
    f, a, b = VASE
    profile = bz.fit_profile(f, a, b, 8)
    assert bz.profile_value(profile, a - 5.0) == pytest.approx(bz.profile_value(profile, a))
    assert bz.profile_value(profile, b + 5.0) == pytest.approx(bz.profile_value(profile, b))


# ── the surfaces ───────────────────────────────────────────────────────────

def test_a_spin_surface_puts_the_profile_on_the_radius():
    f, a, b = VASE
    profile = bz.fit_profile(f, a, b, 12)
    surface = bz.spin_surface(profile)
    for h in (0.0, 2.5, 6.0):
        r = bz.profile_value(profile, h)
        x, y, z = surface(h, 0.0)
        assert (x, y, z) == pytest.approx((r, 0.0, h))
        x, y, z = surface(h, math.pi / 2)
        assert (x, y, z) == pytest.approx((0.0, r, h), abs=1e-9)


def test_a_spin_surface_closes_on_a_full_turn():
    f, a, b = VASE
    surface = bz.spin_surface(bz.fit_profile(f, a, b, 12))
    assert surface(3.0, 0.0) == pytest.approx(surface(3.0, 2 * math.pi), abs=1e-9)


def test_an_extruded_surface_is_constant_along_y():
    f, a, b = SIN2
    surface = bz.extruded_surface(bz.fit_profile(f, a, b, 12))
    for y in (-4.0, 0.0, 7.0):
        assert surface(1.0, y)[2] == pytest.approx(surface(1.0, 0.0)[2])


@pytest.mark.parametrize('build', ['spin', 'extrude'])
def test_a_bezier_surface_goes_through_the_normal_lattice_and_solves(build):
    """The whole reason the surfaces return the same surface(p, q) shape
    everything else does: same lattices, same patterns, same plan rule, and
    a mesh that actually analyzes."""
    if build == 'spin':
        profile = bz.fit_profile(*VASE, segments=10)
        surface = bz.spin_surface(profile)
        p_range, q_range = (0.0, 6.0), (0.0, 2 * math.pi)
    else:
        profile = bz.fit_profile(lambda x: 3.0 - 0.06 * (x - 6.0) ** 2, 0.0, 12.0, 10)
        surface = bz.extruded_surface(profile)
        p_range, q_range = (0.0, 12.0), (0.0, 9.0)
    mesh = sg.custom_surface_lattice(surface, None, lattice=sg.LATTICE_SINGLE,
                                     pattern=sg.PATTERN_ISOMETRIC,
                                     p_range=p_range, q_range=q_range, n1=8, n2=8)
    for m in mesh['members']:
        m.setdefault('E', 200.0)
        m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(mesh['nodes'], mesh['members'], 78.5)
    _res, err = sm.analyze(mesh['nodes'], mesh['members'], loads, supports)
    assert err is None, err


# ── the patch ──────────────────────────────────────────────────────────────

def test_a_patch_fits_a_saddle_exactly():
    """A bilinear saddle IS a degree-1 tensor-product Bezier, so a cubic
    patch reproduces it to machine precision. If this drifts, the basis or
    the solve is wrong."""
    f = lambda x, y: x * y / 9.0
    grid = bz.fit_patch(f, (-9.0, 9.0), (-9.0, 9.0), 3, 3)
    _worst, frac = bz.patch_error(grid, f, (-9.0, 9.0), (-9.0, 9.0))
    assert frac < 1e-9


def test_a_patch_of_too_low_a_degree_says_how_wrong_it_is():
    """The hard limit of a SINGLE patch, and the reason the error readout
    is not decoration: a degree-n patch has n-1 interior bends per
    direction and cannot follow more waves than that, however many samples
    it is given. Two waves each way at degree 5 comes out about half the
    height of the surface wrong."""
    f = lambda x, y: 3.0 * math.cos(x) * math.cos(y)
    grid = bz.fit_patch(f, (-9.0, 9.0), (-9.0, 9.0), 5, 5)
    _worst, frac = bz.patch_error(grid, f, (-9.0, 9.0), (-9.0, 9.0))
    assert frac > 0.2


def test_raising_the_patch_degree_fixes_it():
    f = lambda x, y: 3.0 * math.cos(x / 3) * math.cos(y / 3)
    errors = [bz.patch_error(bz.fit_patch(f, (-9.0, 9.0), (-9.0, 9.0), n, n),
                             f, (-9.0, 9.0), (-9.0, 9.0))[1]
              for n in (3, 5, 8)]
    assert errors == sorted(errors, reverse=True)
    assert errors[-1] < 0.01


def test_a_patch_surface_plugs_into_the_lattice():
    f = lambda x, y: 3.0 * math.cos(x / 3) * math.cos(y / 3)
    grid = bz.fit_patch(f, (-9.0, 9.0), (-9.0, 9.0), 6, 6)
    surface = bz.patch_surface(grid, (-9.0, 9.0), (-9.0, 9.0))
    mesh = sg.custom_surface_lattice(surface, None, lattice=sg.LATTICE_SINGLE,
                                     pattern=sg.PATTERN_ISOMETRIC,
                                     p_range=(-9.0, 9.0), q_range=(-9.0, 9.0),
                                     n1=8, n2=8)
    assert mesh['nodes']
    zs = [n[2] for n in mesh['nodes']]
    assert max(zs) > 1.0


def test_raising_one_patch_control_lifts_that_part_of_the_surface():
    """How a Bezier patch is edited everywhere: the surface moves TOWARD
    the control without reaching it."""
    grid = [[0.0] * 5 for _ in range(5)]
    surface = bz.patch_surface(grid, (0.0, 10.0), (0.0, 10.0))
    assert surface(5.0, 5.0)[2] == pytest.approx(0.0)
    grid[2][2] = 10.0
    lifted = surface(5.0, 5.0)[2]
    assert 0.0 < lifted < 10.0
