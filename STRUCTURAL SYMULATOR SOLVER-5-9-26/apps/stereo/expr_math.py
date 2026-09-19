"""A restricted math-expression compiler for the Stereo tab's GeoGebra-style
surface input (a height field z = f(x, y), or a parametric surface's three
component functions x(u, v)/y(u, v)/z(u, v)).

Deliberately NOT `eval()` on the raw string: `eval` would run arbitrary
Python (attribute access, imports, comprehensions, calls to anything in
scope) for a string the user typed into a text box. Instead this parses the
expression with `ast` and WALKS THE WHOLE TREE AT COMPILE TIME against an
explicit node-type whitelist -- not just checking names -- so a disallowed
construct (an attribute access, a lambda, a comprehension, a wrong-arity or
keyword call) is rejected before the expression is ever evaluated, not only
if/when a code path happens to reach it.
"""
import ast
import math


class ExpressionError(ValueError):
    """Raised for any expression this module refuses to compile or
    evaluate -- a syntax error, a disallowed construct, an unknown name, a
    wrong-arity function call, or a runtime math error (e.g. sqrt of a
    negative number) at a specific sample point."""


# Function names available inside an expression, mapped to (callable,
# min_args, max_args) -- max_args=None means unbounded (min..open ended).
# Deliberately a small, math-only surface: no __import__, no attribute
# access of any kind reaches this dict, and arity is checked at COMPILE
# time so a wrong-arity call never even reaches evaluation.
_FUNCTIONS = {
    'sin': (math.sin, 1, 1), 'cos': (math.cos, 1, 1), 'tan': (math.tan, 1, 1),
    'asin': (math.asin, 1, 1), 'acos': (math.acos, 1, 1), 'atan': (math.atan, 1, 1),
    'atan2': (math.atan2, 2, 2),
    'sinh': (math.sinh, 1, 1), 'cosh': (math.cosh, 1, 1), 'tanh': (math.tanh, 1, 1),
    'sqrt': (math.sqrt, 1, 1), 'exp': (math.exp, 1, 1),
    'log': (math.log, 1, 1), 'log10': (math.log10, 1, 1), 'log2': (math.log2, 1, 1),
    'abs': (abs, 1, 1), 'floor': (math.floor, 1, 1), 'ceil': (math.ceil, 1, 1),
    'min': (min, 2, None), 'max': (max, 2, None),
    'pow': (pow, 2, 2), 'hypot': (math.hypot, 2, None),
}

# Bare names available inside an expression besides the declared variables.
_CONSTANTS = {'pi': math.pi, 'e': math.e}

_BIN_OPS = {
    ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a ** b, ast.Mod: lambda a, b: a % b,
}
_UNARY_OPS = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a,
              ast.Not: lambda a: not a}

# Comparisons and and/or/not, which turn this from a height-field compiler
# into one that can also express a REGION: `x**2 + y**2 < 36` is a circular
# plan, `not (x > 6 and y > 6)` is an L. A height field never needs them, so
# they cost nothing where they are not used, and the same whitelist that
# keeps `eval` out of the surface fields keeps it out of the plan rules.
_COMPARE_OPS = {
    ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
    ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b,
}


def _validate(node, allowed_names, declared):
    """Compile-time structural check: recursively reject any node whose
    TYPE is not one of the handful whitelisted below, any Name not in
    `allowed_names`, any Call not to a whitelisted function with an arity
    that fits its (min, max), and any Call carrying keywords, *args or
    **kwargs (none of _FUNCTIONS accepts any of those, so a call using
    them can never be valid regardless of the name)."""
    if isinstance(node, ast.Expression):
        _validate(node.body, allowed_names, declared)
    elif isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
            raise ExpressionError(f'unsupported constant {node.value!r}')
    elif isinstance(node, ast.Name):
        if node.id not in allowed_names:
            raise ExpressionError(f"unknown name '{node.id}' "
                                  f"(expected one of {', '.join(declared)})")
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _BIN_OPS:
            raise ExpressionError(f'operator {type(node.op).__name__} is not allowed')
        _validate(node.left, allowed_names, declared)
        _validate(node.right, allowed_names, declared)
    elif isinstance(node, ast.UnaryOp):
        if type(node.op) not in _UNARY_OPS:
            raise ExpressionError(f'operator {type(node.op).__name__} is not allowed')
        _validate(node.operand, allowed_names, declared)
    elif isinstance(node, ast.Compare):
        for op in node.ops:
            if type(op) not in _COMPARE_OPS:
                raise ExpressionError(f'comparison {type(op).__name__} is not allowed')
        _validate(node.left, allowed_names, declared)
        for c in node.comparators:
            _validate(c, allowed_names, declared)
    elif isinstance(node, ast.BoolOp):
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise ExpressionError(f'operator {type(node.op).__name__} is not allowed')
        for v in node.values:
            _validate(v, allowed_names, declared)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise ExpressionError('only a fixed set of math functions may be called')
        if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            raise ExpressionError(f'{node.func.id}(): keyword/starred arguments '
                                  'are not allowed')
        _fn, lo, hi = _FUNCTIONS[node.func.id]
        n = len(node.args)
        if n < lo or (hi is not None and n > hi):
            want = f'{lo}' if hi == lo else (f'at least {lo}' if hi is None else f'{lo}-{hi}')
            raise ExpressionError(f'{node.func.id}() takes {want} argument(s), got {n}')
        for a in node.args:
            _validate(a, allowed_names, declared)
    else:
        raise ExpressionError(f'{type(node).__name__} is not allowed in an expression')


def _evaluate(node, env):
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, env)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return env[node.id] if node.id in env else _CONSTANTS[node.id]
    if isinstance(node, ast.BinOp):
        a, b = _evaluate(node.left, env), _evaluate(node.right, env)
        try:
            return _BIN_OPS[type(node.op)](a, b)
        except ZeroDivisionError:
            raise ExpressionError('division by zero')
    if isinstance(node, ast.UnaryOp):
        return _UNARY_OPS[type(node.op)](_evaluate(node.operand, env))
    if isinstance(node, ast.Compare):
        # Chained comparisons are one Compare node with several ops, and
        # they short-circuit: `0 < x < 6` must not evaluate x twice with a
        # different answer, and must stop at the first false link.
        left = _evaluate(node.left, env)
        for op, comparator in zip(node.ops, node.comparators):
            right = _evaluate(comparator, env)
            if not _COMPARE_OPS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for v in node.values:
                if not _evaluate(v, env):
                    return False
            return True
        for v in node.values:
            if _evaluate(v, env):
                return True
        return False
    if isinstance(node, ast.Call):
        fn, _lo, _hi = _FUNCTIONS[node.func.id]
        args = [_evaluate(a, env) for a in node.args]
        return float(fn(*args))
    raise ExpressionError(f'{type(node).__name__} is not allowed in an expression')


def compile_expression(expr, var_names):
    """Parse `expr` once and return a callable(*values) -> float, evaluating
    it against `var_names` bound (in order) to the callable's own
    positional arguments. Raises ExpressionError immediately for anything
    the compile-time structural check already rejects (bad syntax, a
    disallowed construct, an unknown name, a wrong-arity or keyword
    function call) -- NOT deferred to first call -- so a wizard field can
    validate on keystroke/blur rather than only when the mesh is finally
    generated. A runtime-only failure (e.g. sqrt of a negative number at
    some sample point) still raises ExpressionError, just when that
    specific call is made -- deliberately never probed eagerly at compile
    time, since an expression's real domain may legitimately exclude the
    point a fixed probe would pick (log(x) over x in [1, 5] is valid and
    would fail a probe at x=0 for no real reason)."""
    text = (expr or '').strip()
    if not text:
        raise ExpressionError('expression is empty')
    # '^' reads as "power" to anyone coming from GeoGebra/calculator
    # notation; Python's own '^' is bitwise XOR, which has no sensible
    # meaning on floats and nobody typing a surface formula means anyway.
    text = text.replace('^', '**')
    try:
        tree = ast.parse(text, mode='eval')
    except SyntaxError as exc:
        raise ExpressionError(f'invalid expression: {exc.msg}')

    declared = tuple(var_names)
    allowed_names = set(declared) | set(_CONSTANTS)
    _validate(tree, allowed_names, declared)

    def fn(*values):
        if len(values) != len(declared):
            raise ExpressionError(f'expected {len(declared)} argument(s), got {len(values)}')
        env = dict(zip(declared, (float(v) for v in values)))
        try:
            return _evaluate(tree, env)
        except ExpressionError:
            raise
        except (ValueError, OverflowError) as exc:
            args = ', '.join(f'{n}={v:.4g}' for n, v in zip(declared, values))
            raise ExpressionError(f'expression is undefined at {args}: {exc}')

    return fn
