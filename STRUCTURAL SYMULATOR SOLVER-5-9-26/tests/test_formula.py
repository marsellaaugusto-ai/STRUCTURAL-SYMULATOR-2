"""Tests for formula.py -- the shared formula language (Stereo + Shell tabs)."""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import formula as F


# ── reading what people type ─────────────────────────────────────────────────
@pytest.mark.parametrize('text, x, y, expected', [
    ('x^2', 3, 0, 9),
    ('2x', 3, 0, 6),
    ('2 x', 3, 0, 6),
    ('x y', 2, 5, 10),
    ('3x^2y', 2, 5, 60),          # GeoGebra reads this as 3*x^2*y
    ('2(x+1)', 2, 0, 6),
    ('4 (x+1)', 2, 0, 12),
    ('(x)(y)', 2, 5, 10),
    ('2pi', 0, 0, 2 * math.pi),
    ('1e3 x', 2, 0, 2000),         # scientific notation must not split
    ('1.5E-2', 0, 0, 0.015),
    ('x·y', 2, 5, 10),
    ('x × y − 1', 2, 5, 9),
    ('x²', 3, 0, 9),
    ('sin (x)', 0, 0, 0),
    ('If(x < 0, -x, x)', -2, 0, 2),
    ('-x if x < 0 else x', -2, 0, 2),
    ('max(x, y, 3)', 1, 2, 3),
    ('abs(x) + sqrt(y)', -2, 9, 5),
])
def test_what_people_type(text, x, y, expected):
    f = F.make_surface_fn(text)
    assert abs(f(x, y) - expected) < 1e-12


def test_logic_is_elementwise_on_arrays():
    keep = F.make_domain_fn('not (x > 5 and y > 5)')
    xs = np.array([1.0, 6.0, 6.0])
    ys = np.array([1.0, 1.0, 6.0])
    assert keep(xs, ys).tolist() == [True, True, False]
    band = F.make_surface_fn('1 < x < 3')
    assert band(np.array([0.0, 2.0, 4.0]), 0.0).tolist() == [0.0, 1.0, 0.0]


def test_scalar_in_scalar_out_and_constant_broadcasts():
    assert isinstance(F.make_surface_fn('x+y')(1, 2), float)
    xs = np.linspace(0, 1, 7)
    out = F.make_surface_fn('0.06')(xs, xs)
    assert out.shape == (7,) and np.all(out == 0.06)


@pytest.mark.parametrize('bad', [
    'os.system("x")', '__import__("os")', 'x.real', 'x[0]', 'lambda: 1',
    '"text"', 'open("f")', 'q + 1',
])
def test_unsafe_or_unknown_is_refused(bad):
    with pytest.raises(ValueError):
        F.make_surface_fn(bad)


def test_non_real_values_are_reported_with_the_point():
    f = F.make_surface_fn('sqrt(x)')
    with pytest.raises(F.FormulaError) as e:
        f(-4.0, 0.0)
    assert '-4' in str(e.value)
    with pytest.raises(F.FormulaError):
        f(np.array([1.0, -1.0]), 0.0)


# ── the workspace ────────────────────────────────────────────────────────────
HYPAR = ['a = 10', 'b = 10', 'c = 2',
         'z(x, y) = c x y/(a b)',
         't = 0.06 + 0.02 (x/a)^2',
         'q = 25 t',
         'k = c/(a b)']


def test_workspace_numbers_functions_and_implicit_functions():
    ws = F.Workspace(HYPAR)
    assert ws.errors() == []
    assert ws.number('a') == 10 and ws.number('k') == pytest.approx(0.02)
    assert ws.function('z')(10, 10) == pytest.approx(2.0)
    # 't' uses x -> it is a function of (x, y); 'q' uses t bare -> also one
    assert ws.function('t')(10, 0) == pytest.approx(0.08)
    assert ws.function('q')(10, 0) == pytest.approx(2.0)
    assert [d.name for d in ws.free_numbers()] == ['a', 'b', 'c']


def test_workspace_order_does_not_matter_and_sliders_are_automatic():
    ws = F.Workspace(list(reversed(HYPAR)))
    assert ws.errors() == []
    lo, hi, step = ws.sliders['a']
    assert (lo, hi) == (0.0, 20.0) and step == pytest.approx(0.2)


def test_moving_a_slider_updates_everything_that_depends_on_it():
    ws = F.Workspace(HYPAR)
    ws.set_number('c', 3.0)
    assert ws.function('z')(10, 10) == pytest.approx(3.0)
    assert ws.number('k') == pytest.approx(0.03)
    assert ws.get('c').text == 'c = 3'


def test_errors_are_confined_to_the_lines_involved():
    ws = F.Workspace(['a = 1', 'b = a + nope', 'c = b * 2', 'd = 2a',
                      'p = r', 'r = p', 'x = 3', 'sin = 2', 'just text'])
    kinds = {d.text: d.kind for d in ws.defs}
    assert kinds['a = 1'] == F.NUMBER and kinds['d = 2a'] == F.NUMBER
    for bad in ('b = a + nope', 'c = b * 2', 'p = r', 'r = p', 'x = 3',
                'sin = 2', 'just text'):
        assert kinds[bad] == F.ERROR, bad
    msgs = dict(ws.errors())
    assert 'nope' in msgs['b = a + nope']
    assert 'Circular' in msgs['p = r']
    assert 'plan coordinates' in msgs['x = 3']


def test_redefining_by_the_input_bar_replaces():
    ws = F.Workspace(['a = 1', 'z(x, y) = a x'])
    ws.add_line('a = 4')
    assert len(ws.defs) == 2
    assert ws.function('z')(2, 0) == pytest.approx(8.0)


def test_number_times_parenthesis_is_a_product_but_a_function_is_a_call():
    ws = F.Workspace(['c = 3', 'f(u) = u^2', 'g(x, y) = c(x+1) + f(y)'])
    assert ws.errors() == []
    assert ws.function('g')(1, 2) == pytest.approx(3 * 2 + 4)


def test_extra_formulas_compile_against_the_workspace():
    ws = F.Workspace(HYPAR)
    assert ws.scalar('-a/2') == -5.0
    load = ws.compile('1.2*25*t + 1.6*0.3')
    assert load(0, 0) == pytest.approx(1.2 * 25 * 0.06 + 0.48)
    rule = ws.compile('x < a/4 and y < b/4')
    assert bool(rule(1, 1)) and not bool(rule(9, 1))


def test_round_trip_through_a_dict():
    ws = F.Workspace(HYPAR)
    ws.sliders['a'] = [5.0, 30.0, 0.5]
    ws2 = F.Workspace.from_dict(ws.to_dict())
    assert ws2.lines == ws.lines and ws2.sliders['a'] == [5.0, 30.0, 0.5]
