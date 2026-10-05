"""Arch tab: the frame solver against closed-form solutions.

Written with the 2026-09-10 re-diagnosis (finding A-4). This tab's solver is
the most accurate in the project -- it reproduces the three-hinged arch
closed forms to about 1e-14 -- and nothing in the suite would have noticed if
that changed. Accuracy that good is worth pinning precisely because it is the
tab's best feature.

The two strongest tests here need no reference values at all:

  * a parabolic arch under a full uniform load is funicular, so the bending
    moment must be zero EVERYWHERE along it;
  * a three-hinged arch has, by construction, zero moment AT its crown hinge.

Both are properties of the structure rather than numbers copied from a table,
so they keep working if the mesh, the element or the units ever change.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.arch.arch_app import ArchModel

SPAN = 20.0
RISE = 4.0
W = 10e3        # N/m, horizontal-projected, +down
P = 50e3        # N
N_ELEM = 60


def _parabola(x):
    return 4 * RISE * x * (SPAN - x) / SPAN ** 2


def _arch(hinge=None, supports='pin', **kw):
    m = ArchModel(_parabola, SPAN, n_elem=N_ELEM)
    m.support_a = m.support_b = supports
    m.hinge_x = hinge
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def _udl(w=W):
    return [{'fn': (lambda x: w), 'x1': 0.0, 'x2': SPAN, 'direction': 'vertical'}]


def _rel(got, want):
    return abs(got - want) / max(abs(want), 1e-12)


# ------------------------------------------------------------- three-hinged

def test_three_hinged_parabolic_arch_under_udl_gives_h_equal_wl2_over_8f():
    r = _arch(hinge=SPAN / 2, distributed_loads=_udl()).solve()
    rax, ray, _ = r.reaction(0)
    rbx, rby, _ = r.reaction(N_ELEM)
    assert _rel(abs(rax), W * SPAN ** 2 / (8 * RISE)) < 1e-9
    assert _rel(ray, W * SPAN / 2) < 1e-9
    assert _rel(rby, W * SPAN / 2) < 1e-9
    assert abs(ray + rby - W * SPAN) < 1e-6 * W * SPAN
    assert abs(rax + rbx) < 1e-6 * W * SPAN ** 2 / (8 * RISE)


def test_a_parabolic_arch_under_udl_is_funicular_so_m_is_zero_everywhere():
    """No reference value: a funicular shape carries its load in pure
    compression, so every station's moment must vanish against wL^2/8."""
    r = _arch(hinge=SPAN / 2, distributed_loads=_udl()).solve()
    samp = r.sample(6)
    reference = W * SPAN ** 2 / 8
    assert max(abs(v) for v in samp['M']) < 1e-9 * reference


def test_three_hinged_arch_under_a_crown_load_gives_h_equal_pl_over_4f():
    r = _arch(hinge=SPAN / 2,
              point_loads=[{'x': SPAN / 2, 'fx': 0.0, 'fy': -P}]).solve()
    rax, ray, _ = r.reaction(0)
    assert _rel(abs(rax), P * SPAN / (4 * RISE)) < 1e-9
    assert _rel(ray, P / 2) < 1e-9


def test_the_moment_at_a_crown_hinge_is_zero_by_construction():
    r = _arch(hinge=SPAN / 2,
              point_loads=[{'x': SPAN / 2, 'fx': 0.0, 'fy': -P}]).solve()
    samp = r.sample(6)
    i = min(range(len(samp['x'])), key=lambda k: abs(samp['x'][k] - SPAN / 2))
    assert abs(samp['M'][i]) < 1e-9 * P * SPAN / 8


# ---------------------------------------------------------------- two-hinged

def test_two_hinged_thrust_approaches_the_inextensible_value_as_ea_grows():
    """H -> wL^2/8f as axial stiffness -> infinity. The shortfall at a realistic
    area is elastic shortening appearing at the right magnitude and sign, not
    an error -- it is also why a FIXED arch shows a small non-zero springing
    moment under a load its shape is funicular for."""
    inextensible = W * SPAN ** 2 / (8 * RISE)
    ratios = []
    for area in (1e-2, 1e0, 1e2):
        r = _arch(distributed_loads=_udl(), A=area).solve()
        rax, _, _ = r.reaction(0)
        ratios.append(abs(rax) / inextensible)
    assert ratios[0] < ratios[1] < ratios[2] <= 1.0 + 1e-9
    assert ratios[0] > 0.99          # even a slender arch is within 1%
    assert abs(ratios[-1] - 1.0) < 1e-5


def test_global_equilibrium_under_an_off_centre_point_load():
    r = _arch(point_loads=[{'x': SPAN / 4, 'fx': 0.0, 'fy': -P}]).solve()
    rax, ray, _ = r.reaction(0)
    rbx, rby, _ = r.reaction(N_ELEM)
    assert abs(ray + rby - P) < 1e-6 * P
    assert abs(rax + rbx) < 1e-6 * P
    assert abs(rby * SPAN - P * (SPAN / 4)) < 1e-6 * P * SPAN


# ------------------------------------------------------------- other loading

def test_self_weight_behaves_as_a_full_span_udl():
    r = _arch(hinge=SPAN / 2, w_weight=W).solve()
    rax, ray, _ = r.reaction(0)
    assert _rel(abs(rax), W * SPAN ** 2 / (8 * RISE)) < 1e-9
    assert _rel(ray, W * SPAN / 2) < 1e-9


@pytest.mark.parametrize('use_wind', [True, False])
def test_a_horizontal_load_is_carried_horizontally(use_wind):
    """w_wind and an explicit direction='horizontal' load must both balance."""
    ww = 5e3
    if use_wind:
        m = _arch(w_wind=ww)
    else:
        m = _arch(distributed_loads=[{'fn': (lambda x: ww), 'x1': 0.0,
                                      'x2': SPAN, 'direction': 'horizontal'}])
    r = m.solve()
    rax, ray, _ = r.reaction(0)
    rbx, rby, _ = r.reaction(N_ELEM)
    assert abs(rax + rbx + ww * SPAN) < 1e-6 * ww * SPAN
    assert abs(ray + rby) < 1e-6 * ww * SPAN


def test_fixed_supports_still_balance_globally():
    r = _arch(supports='fixed', distributed_loads=_udl()).solve()
    rax, ray, _ = r.reaction(0)
    rbx, rby, _ = r.reaction(N_ELEM)
    assert abs(ray + rby - W * SPAN) < 1e-6 * W * SPAN
    assert abs(rax + rbx) < 1e-6 * W * SPAN ** 2 / (8 * RISE)


def test_thrust_is_mesh_independent_for_the_three_hinged_udl_case():
    exact = W * SPAN ** 2 / (8 * RISE)
    for n in (10, 20, 60, 120):
        m = ArchModel(_parabola, SPAN, n_elem=n)
        m.support_a = m.support_b = 'pin'
        m.hinge_x = SPAN / 2
        m.distributed_loads = _udl()
        rax, _, _ = m.solve().reaction(0)
        assert _rel(abs(rax), exact) < 1e-9


# ------------------------------------------------------------ input handling

def test_a_point_load_off_the_arch_is_refused():
    """Regression for A-6. An out-of-span load was assembled onto the NEAREST
    node -- a springing -- so it was silently relocated onto a support and
    carried by nothing, while global equilibrium still closed."""
    for x in (-2.0, SPAN + 5.0, 999.0):
        m = _arch(point_loads=[{'x': x, 'fx': 0.0, 'fy': -P}])
        with pytest.raises(ValueError):
            m.solve()


def test_the_springings_themselves_are_valid_load_positions():
    for x in (0.0, SPAN):
        _arch(point_loads=[{'x': x, 'fx': 0.0, 'fy': -P}]).solve()


def test_a_distributed_load_entirely_off_the_arch_is_refused():
    """Regression for A-7: it used to integrate to zero and vanish silently."""
    m = _arch(distributed_loads=[{'fn': (lambda x: W), 'x1': SPAN + 10,
                                  'x2': SPAN + 30, 'direction': 'vertical'}])
    with pytest.raises(ValueError):
        m.solve()


def test_a_distributed_load_entered_right_to_left_still_works():
    fwd = _arch(distributed_loads=[{'fn': (lambda x: W), 'x1': 0.0,
                                    'x2': SPAN, 'direction': 'vertical'}]).solve()
    rev = _arch(distributed_loads=[{'fn': (lambda x: W), 'x1': SPAN,
                                    'x2': 0.0, 'direction': 'vertical'}]).solve()
    assert _rel(rev.reaction(0)[1], fwd.reaction(0)[1]) < 1e-9


def test_an_arch_needs_at_least_one_element():
    """Regression for A-2: n_elem = 0 divided by zero inside nodes()."""
    for n in (0, -3):
        with pytest.raises(ValueError):
            ArchModel(_parabola, SPAN, n_elem=n)
