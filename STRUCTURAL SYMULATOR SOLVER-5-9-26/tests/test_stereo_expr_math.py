"""Tests for the restricted math-expression compiler (apps/stereo/expr_math.py)
backing the Stereo tab's GeoGebra-style surface input."""
import math

import pytest

from apps.stereo import expr_math as em


def test_compiles_a_simple_polynomial():
    f = em.compile_expression('x**2 + y**2', ('x', 'y'))
    assert f(3.0, 4.0) == pytest.approx(25.0)


def test_caret_reads_as_power_not_xor():
    f = em.compile_expression('x^2', ('x', 'y'))
    assert f(3.0, 0.0) == pytest.approx(9.0)


def test_trig_and_constants():
    f = em.compile_expression('sin(pi * x) + cos(0)', ('x',))
    assert f(0.5) == pytest.approx(1.0 + 1.0)


def test_sqrt_exp_log():
    f = em.compile_expression('sqrt(x) + exp(0) + log(e)', ('x',))
    assert f(4.0) == pytest.approx(2.0 + 1.0 + 1.0)


def test_unary_minus_and_precedence():
    f = em.compile_expression('-x^2 + 1', ('x',))
    assert f(3.0) == pytest.approx(-9.0 + 1.0)


def test_multi_argument_functions():
    f = em.compile_expression('atan2(y, x)', ('x', 'y'))
    assert f(1.0, 1.0) == pytest.approx(math.pi / 4.0)
    f2 = em.compile_expression('max(x, y, 2)', ('x', 'y'))
    assert f2(1.0, 5.0) == 5.0


def test_parametric_style_three_variables_not_needed_but_uv_names_work():
    fx = em.compile_expression('(2 + cos(v)) * cos(u)', ('u', 'v'))
    assert fx(0.0, 0.0) == pytest.approx(3.0)


def test_empty_expression_is_rejected():
    with pytest.raises(em.ExpressionError):
        em.compile_expression('', ('x', 'y'))
    with pytest.raises(em.ExpressionError):
        em.compile_expression('   ', ('x', 'y'))


def test_unknown_name_is_rejected_at_compile_time():
    with pytest.raises(em.ExpressionError, match='unknown name'):
        em.compile_expression('x + z', ('x', 'y'))


def test_disallowed_function_is_rejected():
    with pytest.raises(em.ExpressionError):
        em.compile_expression('__import__("os")', ('x',))


def test_attribute_access_is_rejected():
    with pytest.raises(em.ExpressionError):
        em.compile_expression('x.real', ('x',))


def test_syntax_error_is_rejected_cleanly():
    with pytest.raises(em.ExpressionError, match='invalid expression'):
        em.compile_expression('x +* y', ('x', 'y'))


def test_division_by_zero_raises_expression_error_not_python_exception():
    f = em.compile_expression('1 / x', ('x',))
    with pytest.raises(em.ExpressionError):
        f(0.0)


def test_math_domain_error_at_a_specific_point_raises_expression_error():
    f = em.compile_expression('sqrt(x)', ('x',))
    assert f(4.0) == pytest.approx(2.0)
    with pytest.raises(em.ExpressionError, match='undefined'):
        f(-1.0)


def test_log_of_zero_is_a_runtime_error_not_a_compile_time_rejection():
    # log(x) is a perfectly valid expression whose real domain excludes 0 --
    # it must compile fine and only fail when actually sampled there.
    f = em.compile_expression('log(x)', ('x',))
    assert f(1.0) == pytest.approx(0.0)
    with pytest.raises(em.ExpressionError):
        f(0.0)


def test_wrong_arity_call_is_rejected():
    with pytest.raises(em.ExpressionError):
        em.compile_expression('sin(x, y)', ('x', 'y'))


def test_keyword_arguments_are_rejected():
    with pytest.raises(em.ExpressionError):
        em.compile_expression('max(x, y=2)', ('x', 'y'))


def test_wrong_number_of_call_arguments_is_rejected():
    f = em.compile_expression('x + 1', ('x', 'y'))
    with pytest.raises(em.ExpressionError):
        f(1.0)


def test_list_comprehension_and_lambda_are_rejected():
    with pytest.raises(em.ExpressionError):
        em.compile_expression('[i for i in range(10)]', ('x',))
    with pytest.raises(em.ExpressionError):
        em.compile_expression('(lambda: 1)()', ('x',))


def test_string_and_bytes_literals_are_rejected():
    with pytest.raises(em.ExpressionError):
        em.compile_expression("'a'", ('x',))


# ── comparisons and booleans (what makes a plan-shape rule expressible) ──────

def test_a_comparison_is_a_region_not_a_height():
    f = em.compile_expression('x^2 + y^2 < 36', ('x', 'y'))
    assert f(0, 0) is True
    assert f(6, 6) is False


def test_and_or_not_compose_regions():
    ell = em.compile_expression('not (x > 6 and y > 6)', ('x', 'y'))
    assert ell(0, 0) and ell(7, 0) and ell(0, 7)
    assert not ell(7, 7)
    either = em.compile_expression('x < 1 or y < 1', ('x', 'y'))
    assert either(0, 9) and not either(9, 9)


def test_a_chained_comparison_reads_the_way_it_is_written():
    """Python parses `0 < x < 6` as ONE node with two operators; evaluating
    it as `(0 < x) < 6` would compare a bool against 6 and be true almost
    everywhere."""
    f = em.compile_expression('0 < x < 6', ('x',))
    assert not f(-1)
    assert f(3)
    assert not f(9)


def test_boolean_operators_short_circuit_past_an_undefined_branch():
    """`x > 0 and sqrt(x) > 1` must not evaluate sqrt(-4). Short-circuiting
    is what lets a rule guard its own domain."""
    f = em.compile_expression('x > 0 and sqrt(x) > 1', ('x',))
    assert f(-4) is False
    assert f(4) is True


@pytest.mark.parametrize('expr', ['x is y', 'x in y', 'x if y else 1',
                                  'lambda x: x', '[x for x in y]'])
def test_the_whitelist_still_refuses_everything_else(expr):
    """Adding comparisons must not open the door to the rest of Python: the
    node-type whitelist is what keeps eval() out of a field anyone can type
    into."""
    with pytest.raises(em.ExpressionError):
        em.compile_expression(expr, ('x', 'y'))
