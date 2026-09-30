"""formula.py -- the app's shared formula language, 2026-09-14.

Two tabs let the user type mathematics: the Stereo Structure tab (surfaces
z(x, y) and plan-domain rules) and the Shell tab (the surface, the thickness,
every load, the wind pressure coefficient, thickening zones). They used to be
headed for two copies of the same compiler, which is exactly how two tabs end
up disagreeing about what "2x" means (MANIFESTO s3j). This module is the one
copy. It imports no tab and no Tkinter.

WHAT THE LANGUAGE ACCEPTS -- written to feel like GeoGebra's input bar:

    ^ for power              x^2          (also ², ³)
    implicit multiplication  2x, 2(x+1), (a)(b), x y, c(x+1) when c is a number
    ·  ×  − (typographic)    read as *  *  -
    functions                sin cos tan asin acos atan atan2 sinh cosh tanh
                             sqrt exp ln log log10 log2 abs sign floor ceil
                             hypot min max clamp If(cond, a, b) ...
    constants                pi, e       (a user definition may shadow these)
    comparisons / logic      x < 2 and y > 1,   not (...),   1 < x < 3
    conditional              If(x < 0, -x, x)    or    (-x if x < 0 else x)

SAFETY. The text is parsed to a Python AST, every node type is checked
against a short allow-list, and every name must be a coordinate, a user
definition, or one of the functions above. There are no attribute accesses,
no subscripts, no builtins -- `os.system("x")` is refused before anything is
evaluated. This is a local desktop tool, but a formula a colleague sends in
a spreadsheet should still not be able to do anything but arithmetic.

VECTORISED. Every compiled function works on plain floats AND on numpy
arrays, so the Shell tab evaluates a surface over a whole mesh in one call.
Boolean logic is rewritten to its element-wise numpy form (`and` ->
logical_and, `a < x < b` -> two comparisons joined, `if/else` -> where), since
Python's own `and` cannot be applied to an array.

THE WORKSPACE (the "algebra view"). A list of definitions, one per line,
exactly as GeoGebra keeps them:

    a = 10                         a number (gets a slider)
    c = a/5                        a number computed from others (no slider)
    z(x, y) = c*x*y/(a*b)          a function
    t = 0.06 + 0.02*(x/a)^2        a function too: it uses x, so it is one

Definitions may use each other in any order; a cycle or an unknown name marks
only the lines involved as errors and leaves the rest usable.
"""
import ast
import functools
import keyword
import math
import re

import numpy as np

__all__ = ['FormulaError', 'compile_function', 'make_surface_fn',
           'make_domain_fn', 'Workspace', 'Definition', 'FUNCTIONS']


class FormulaError(ValueError):
    """A formula that cannot be read or evaluated. A ValueError, so callers
    that already catch ValueError around user input keep working."""


# ═══════════════════════════════════════════════════════════════════════════
#  The vocabulary
# ═══════════════════════════════════════════════════════════════════════════
def _variadic(np_fn):
    def fn(*args):
        if not args:
            raise FormulaError('min/max need at least one argument')
        return functools.reduce(np_fn, args)
    return fn


def _if(cond, a, b=np.nan):
    return np.where(cond, a, b)


def _clamp(v, lo, hi):
    return np.clip(v, lo, hi)


def _step(v):
    """Heaviside step: 0 for v < 0, 1 for v >= 0."""
    return np.where(np.asarray(v) >= 0, 1.0, 0.0)


#: Functions a formula may call. numpy versions, so they broadcast.
FUNCTIONS = {
    'sin': np.sin, 'cos': np.cos, 'tan': np.tan,
    'asin': np.arcsin, 'acos': np.arccos, 'atan': np.arctan, 'atan2': np.arctan2,
    'arcsin': np.arcsin, 'arccos': np.arccos, 'arctan': np.arctan,
    'sinh': np.sinh, 'cosh': np.cosh, 'tanh': np.tanh,
    'asinh': np.arcsinh, 'acosh': np.arccosh, 'atanh': np.arctanh,
    'sqrt': np.sqrt, 'cbrt': np.cbrt, 'exp': np.exp,
    'ln': np.log, 'log': np.log, 'log10': np.log10, 'log2': np.log2,
    'abs': np.abs, 'fabs': np.abs, 'sign': np.sign, 'sgn': np.sign,
    'floor': np.floor, 'ceil': np.ceil, 'round': np.round,
    'hypot': np.hypot, 'pow': np.power,
    'radians': np.radians, 'degrees': np.degrees,
    'min': _variadic(np.minimum), 'max': _variadic(np.maximum),
    'clamp': _clamp, 'heaviside': _step,
    'If': _if, 'if_': _if,
}

CONSTANTS = {'pi': math.pi, 'e': math.e, 'tau': math.tau}

# internal helpers the AST rewrite calls; never reachable from typed text
# because the typed text is validated BEFORE the rewrite introduces them
_INTERNAL = {'_and': lambda *a: functools.reduce(np.logical_and, a),
             '_or': lambda *a: functools.reduce(np.logical_or, a),
             '_not': np.logical_not,
             '_where': np.where}

_KEYWORDS = set(keyword.kwlist) | {'True', 'False', 'None'}

#: The coordinates a surface formula is written in.
COORDS = ('x', 'y')


# ═══════════════════════════════════════════════════════════════════════════
#  Text -> Python expression text
# ═══════════════════════════════════════════════════════════════════════════
_TYPO = {'·': '*', '×': '*', '−': '-', '÷': '/', '²': '**2', '³': '**3',
         '≤': '<=', '≥': '>=', '≠': '!=', 'π': 'pi'}

_NUM = r'(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?'
_TOKEN = re.compile(rf'\s*(?:(?P<num>{_NUM})|(?P<name>[A-Za-z_]\w*)|'
                    r'(?P<op>\*\*|//|<=|>=|==|!=|\S))')


def _tokens(s):
    pos, out = 0, []
    s = s.rstrip()
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m:
            raise FormulaError(f'Cannot read the formula near "{s[pos:pos+10]}"')
        pos = m.end()
        if m.group('num') is not None:
            out.append(('num', m.group('num')))
        elif m.group('name') is not None:
            out.append(('name', m.group('name')))
        else:
            out.append(('op', m.group('op')))
    return out


def normalise(text):
    """Rewrite what a person types into Python expression syntax: '^' to
    '**', typographic symbols to ASCII, and implicit multiplication made
    explicit.

    Implicit multiplication is decided token by token, never by a blanket
    regex: the naive regex version of this rewrote 'not (x > 1 and y > 2)'
    into 'not*(x > 1*and y > 2)' (the Stereo tab's regression test pins
    that), and a regex also splits '1e5' into '1*e5'. The rule:

      number|name|')'  followed by  number|name   ->  insert '*'
      number           followed by  '('            ->  insert '*'
      name|')'         followed by  '('            ->  left alone: it is a
                          call, and the AST pass turns it into a product if
                          the name turns out to be a number, not a function
      a Python keyword on either side               ->  never
    """
    s = str(text)
    for k, v in _TYPO.items():
        s = s.replace(k, v)
    s = s.replace('^', '**')
    toks = _tokens(s)
    out = []
    for i, (kind, val) in enumerate(toks):
        if i:
            pk, pv = toks[i - 1]
            left_val = (pk == 'num' or (pk == 'name' and pv not in _KEYWORDS)
                        or (pk == 'op' and pv == ')'))
            right_val = kind == 'num' or (kind == 'name' and val not in _KEYWORDS)
            if left_val and right_val and not (pk == 'num' and kind == 'num'):
                out.append('*')
            elif pk == 'num' and kind == 'op' and val == '(':
                out.append('*')
        out.append(val)
    return ' '.join(out)


# ═══════════════════════════════════════════════════════════════════════════
#  Python expression text -> checked, vectorised code
# ═══════════════════════════════════════════════════════════════════════════
_ALLOWED_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp,
                  ast.Compare, ast.IfExp, ast.Call, ast.Name, ast.Load,
                  ast.Constant, ast.Tuple,
                  ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
                  ast.FloorDiv, ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or,
                  ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)


class _Rewrite(ast.NodeTransformer):
    """Validate names, turn number-calls into products, and make logic
    element-wise. `callables` maps a name to its arity (None = any);
    `values` is every non-callable name the formula may use; `autocall` is
    the set of user functions of (x, y) that may be written bare -- 't'
    meaning t(x, y) -- wherever x and y are themselves in scope."""

    def __init__(self, callables, values, autocall=()):
        self.callables = callables
        self.values = values
        self.autocall = set(autocall) if all(c in values for c in COORDS) else set()
        self.used = set()

    def generic_visit(self, node):
        if not isinstance(node, _ALLOWED_NODES):
            raise FormulaError(f'"{type(node).__name__}" is not allowed in a formula')
        return super().generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, bool):
            return ast.copy_location(ast.Constant(float(node.value)), node)
        if not isinstance(node.value, (int, float)):
            raise FormulaError(f'Only numbers are allowed, not {node.value!r}')
        return node

    def visit_Name(self, node):
        if node.id in self.autocall and node.id not in self.values:
            self.used.add(node.id)
            self.used.update(COORDS)
            return ast.copy_location(
                ast.Call(ast.Name(node.id, ast.Load()),
                         [ast.Name(c, ast.Load()) for c in COORDS], []), node)
        if node.id in self.callables and node.id not in self.values:
            raise FormulaError(f'"{node.id}" is a function; call it with '
                               f'arguments, e.g. {node.id}(x, y)')
        if node.id not in self.values:
            raise FormulaError(f'Unknown name "{node.id}"')
        self.used.add(node.id)
        return node

    def visit_Call(self, node):
        if node.keywords:
            raise FormulaError('Named arguments are not allowed in a formula')
        func = node.func
        if isinstance(func, ast.Name) and func.id in self.callables \
                and func.id not in self.values:
            arity = self.callables[func.id]
            if arity is not None and len(node.args) != arity:
                raise FormulaError(f'{func.id} takes {arity} argument'
                                   f'{"s" if arity != 1 else ""}, '
                                   f'got {len(node.args)}')
            self.used.add(func.id)
            node.args = [self.visit(a) for a in node.args]
            return node
        # Not a function: "c(x+1)" with c a number, "2(x)" or "(a)(b)".
        if len(node.args) != 1:
            name = func.id if isinstance(func, ast.Name) else 'this'
            raise FormulaError(f'"{name}" is not a function')
        left = self.visit(func)
        right = self.visit(node.args[0])
        return ast.copy_location(ast.BinOp(left, ast.Mult(), right), node)

    def visit_BoolOp(self, node):
        fn = '_and' if isinstance(node.op, ast.And) else '_or'
        return ast.copy_location(
            ast.Call(ast.Name(fn, ast.Load()), [self.visit(v) for v in node.values], []),
            node)

    def visit_UnaryOp(self, node):
        if isinstance(node.op, ast.Not):
            return ast.copy_location(
                ast.Call(ast.Name('_not', ast.Load()), [self.visit(node.operand)], []),
                node)
        return self.generic_visit(node)

    def visit_Compare(self, node):
        left = self.visit(node.left)
        comps = [self.visit(c) for c in node.comparators]
        for op in node.ops:
            if not isinstance(op, _ALLOWED_NODES):
                raise FormulaError(f'"{type(op).__name__}" is not allowed in a formula')
        parts, a = [], left
        for op, b in zip(node.ops, comps):
            parts.append(ast.Compare(a, [op], [b]))
            a = b
        if len(parts) == 1:
            return ast.copy_location(parts[0], node)
        return ast.copy_location(
            ast.Call(ast.Name('_and', ast.Load()), parts, []), node)

    def visit_IfExp(self, node):
        return ast.copy_location(
            ast.Call(ast.Name('_where', ast.Load()),
                     [self.visit(node.test), self.visit(node.body),
                      self.visit(node.orelse)], []), node)

    def visit_Tuple(self, node):
        raise FormulaError('A formula must give one value, not a list '
                           '(check for a stray comma)')


def _parse(text):
    src = normalise(text)
    if not src.strip():
        raise FormulaError('Empty formula')
    try:
        return ast.parse(src, mode='eval')
    except SyntaxError as exc:
        raise FormulaError(f'Cannot read "{text}": {exc.msg}') from None


def _raw_names(text):
    """(names used bare, names called) -- a lenient first look at a formula,
    used only to work out dependencies before anything is compiled."""
    tree = _parse(text)
    funcs = [n.func for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    func_ids = {id(f) for f in funcs}
    bare = {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and id(n) not in func_ids}
    return bare, {f.id for f in funcs}


def _compile(text, callables, values, autocall=()):
    """normalise -> parse -> validate/rewrite -> code object. Returns
    (code, names used)."""
    tree = _parse(text)
    rw = _Rewrite(callables, values, autocall)
    tree = rw.visit(tree)
    ast.fix_missing_locations(tree)
    return compile(tree, '<formula>', 'eval'), rw.used


def _finish(value, args):
    """Broadcast a result to the shape of its inputs and refuse anything that
    is not a finite real number."""
    arr = np.asarray(value, dtype=float) if not np.iscomplexobj(value) else None
    if arr is None:
        raise FormulaError('The formula gives a complex (non-real) value')
    shapes = [np.shape(a) for a in args if np.ndim(a)]
    if shapes:
        shape = np.broadcast_shapes(*shapes)
        if arr.shape != shape:
            arr = np.broadcast_to(arr, shape).copy()
    if not np.all(np.isfinite(arr)):
        if arr.ndim == 0:
            where = ', '.join(f'{float(a):g}' for a in args)
            raise FormulaError(f'The formula is not a finite real number at ({where})')
        bad = np.argwhere(~np.isfinite(arr))[0]
        pt = ', '.join(f'{float(np.broadcast_to(a, arr.shape)[tuple(bad)]):g}'
                       for a in args)
        raise FormulaError(f'The formula is not a finite real number at ({pt})'
                           ' -- e.g. a square root of a negative number, or a '
                           'division by zero')
    return arr


def compile_function(expr, params=COORDS, names=None, functions=None,
                     autocall=None):
    """Compile one formula into a vectorised function of `params`.

    `names` maps extra value names (numbers) to their values; `functions`
    maps extra callable names to (callable, arity). `autocall` lists the
    functions of (x, y) that may be written bare (default: every 2-argument
    entry of `functions`). Returns fn(*args) giving a float for scalar
    inputs and an array for array inputs."""
    names = dict(names or {})
    functions = dict(functions or {})
    values = set(params) | set(names) | set(CONSTANTS)
    callables = {k: None for k in FUNCTIONS}
    callables.update({k: ar for k, (_f, ar) in functions.items()})
    if autocall is None:
        autocall = {k for k, (_f, ar) in functions.items() if ar == 2}
    code, _used = _compile(expr, callables, values, autocall)
    base = dict(FUNCTIONS)
    base.update({k: f for k, (f, _ar) in functions.items()})
    base.update(_INTERNAL)
    base.update(CONSTANTS)
    base.update(names)

    def fn(*args):
        if len(args) != len(params):
            raise FormulaError(f'expected {len(params)} arguments, got {len(args)}')
        ns = dict(base)
        ns.update(zip(params, args))
        with np.errstate(all='ignore'):
            v = eval(code, {'__builtins__': {}}, ns)
        out = _finish(v, args)
        return float(out) if out.ndim == 0 else out
    fn.expr = expr
    fn.params = tuple(params)
    return fn


def make_surface_fn(expr, ctx=None):
    """A user 'z = f(x, y)' string -> f(x, y) returning a float (or an array
    for array inputs). `ctx` supplies extra names. An empty string is the
    flat surface z = 0. Kept with the Stereo tab's original signature."""
    s = str(expr).strip() or '0'
    return compile_function(s, COORDS, ctx or {})


def make_domain_fn(expr, ctx=None):
    """A 'keep this point?' rule over the plan -> f(x, y) -> bool (or a
    boolean array). An empty rule means 'keep everything' and returns None."""
    if expr is None or str(expr).strip() == '':
        return None
    inner = make_surface_fn(expr, ctx)

    def keep(x, y):
        v = inner(x, y)
        return bool(v) if np.ndim(v) == 0 else np.asarray(v, dtype=bool)
    return keep


# ═══════════════════════════════════════════════════════════════════════════
#  The workspace ("algebra view")
# ═══════════════════════════════════════════════════════════════════════════
_DEF_RE = re.compile(r'^\s*(?P<name>[A-Za-z_]\w*)\s*'
                     r'(?:\(\s*(?P<params>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)?\s*\))?'
                     r'\s*(?::=|=)(?!=)\s*(?P<expr>.*)$')

NUMBER, FUNCTION, ERROR, COMMENT = 'number', 'function', 'error', 'comment'


class Definition:
    """One line of the algebra view."""

    __slots__ = ('text', 'name', 'params', 'expr', 'kind', 'value', 'error',
                 'deps', 'free', 'fn')

    def __init__(self, text):
        self.text = text.rstrip()
        self.name = None
        self.params = None       # tuple of parameter names for a function
        self.expr = ''
        self.kind = ERROR
        self.value = None        # float, for a number
        self.error = ''
        self.deps = set()
        self.free = False        # a plain literal number -> gets a slider
        self.fn = None           # compiled callable, for a function

    def __repr__(self):
        return f'Definition({self.text!r}, kind={self.kind!r})'


def _is_literal(expr):
    try:
        tree = ast.parse(normalise(expr), mode='eval')
    except (SyntaxError, FormulaError):
        return False
    node = tree.body
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        node = node.operand
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float))


def nice_step(span):
    """A round slider step about 1/100 of the span: 1, 2 or 5 x 10^k."""
    if span <= 0 or not math.isfinite(span):
        return 0.1
    raw = span / 100.0
    k = math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if m * 10 ** k >= raw:
            return m * 10 ** k
    return 10 ** (k + 1)


def default_slider(value):
    """GeoGebra-style automatic slider range for a number: 0..2v for a
    positive value, 2v..0 for a negative one, -5..5 for zero."""
    v = float(value)
    if v > 0:
        lo, hi = 0.0, 2.0 * v
    elif v < 0:
        lo, hi = 2.0 * v, 0.0
    else:
        lo, hi = -5.0, 5.0
    return [lo, hi, nice_step(hi - lo)]


class Workspace:
    """An ordered list of definitions, evaluated together.

    `lines` is the text the user sees; everything else is derived from it by
    `evaluate()`, which runs automatically on every change. Slider ranges are
    kept per name in `sliders` ([min, max, step]) and survive re-evaluation.
    """

    def __init__(self, lines=None, sliders=None):
        self.defs = []
        self.sliders = {k: list(v) for k, v in (sliders or {}).items()}
        self._ns_values = {}
        self._ns_funcs = {}
        self._autocall = set()
        self.set_lines(lines or [])

    # -- editing --------------------------------------------------------------
    @property
    def lines(self):
        return [d.text for d in self.defs]

    def set_lines(self, lines):
        if isinstance(lines, str):
            lines = lines.splitlines()
        self.defs = [Definition(t) for t in lines if t.strip()]
        self.evaluate()

    def add_line(self, text):
        """Add a definition; if one with the same name exists it is REPLACED,
        as typing 'a = 5' into GeoGebra's input bar redefines a."""
        d = Definition(text)
        m = _DEF_RE.match(text)
        if m:
            for i, old in enumerate(self.defs):
                if old.name == m.group('name'):
                    self.defs[i] = d
                    self.evaluate()
                    return d
        self.defs.append(d)
        self.evaluate()
        return d

    def set_line(self, index, text):
        if not text.strip():
            return self.remove(index)
        self.defs[index] = Definition(text)
        self.evaluate()

    def remove(self, index):
        del self.defs[index]
        self.evaluate()

    def set_number(self, name, value):
        """Move a slider: rewrite that number's definition to the new value."""
        d = self.get(name)
        if d is None:
            raise KeyError(name)
        txt = f'{float(value):.10g}'
        d.text = f'{name} = {txt}'
        self.evaluate()

    # -- lookup ---------------------------------------------------------------
    def get(self, name):
        for d in self.defs:
            if d.name == name:
                return d
        return None

    def has_function(self, name):
        d = self.get(name)
        return d is not None and d.kind == FUNCTION

    def has_number(self, name):
        d = self.get(name)
        return d is not None and d.kind == NUMBER

    def number(self, name):
        d = self.get(name)
        if d is None:
            raise FormulaError(f'"{name}" is not defined')
        if d.kind != NUMBER:
            raise FormulaError(f'"{name}" is not a number' +
                               (f': {d.error}' if d.error else ''))
        return d.value

    def function(self, name):
        d = self.get(name)
        if d is None:
            raise FormulaError(f'"{name}" is not defined')
        if d.kind != FUNCTION:
            raise FormulaError(f'"{name}" is not a valid function' +
                               (f': {d.error}' if d.error else ''))
        return d.fn

    def numbers(self):
        return {d.name: d.value for d in self.defs if d.kind == NUMBER}

    def free_numbers(self):
        return [d for d in self.defs if d.kind == NUMBER and d.free]

    def errors(self):
        return [(d.text, d.error) for d in self.defs if d.kind == ERROR]

    def compile(self, expr, params=COORDS):
        """Compile an extra formula (a load, a zone rule, a plan limit) that
        may use every valid definition in the workspace."""
        return compile_function(expr, params, self._ns_values,
                                dict(self._ns_funcs), self._autocall)

    def scalar(self, expr):
        """Evaluate a formula with no coordinates, e.g. a plan limit '-a/2'."""
        return float(self.compile(expr, params=())())

    # -- evaluation -----------------------------------------------------------
    def evaluate(self):
        self._ns_values, self._ns_funcs = {}, {}
        by_name = {}
        for d in self.defs:
            d.kind, d.error, d.value, d.fn, d.deps, d.free = ERROR, '', None, None, set(), False
            d.name = d.params = None
            s = d.text.strip()
            if s.startswith('#'):
                d.kind = COMMENT
                continue
            m = _DEF_RE.match(s)
            if not m:
                d.error = 'Write a definition like  a = 10  or  z(x, y) = x*y'
                continue
            name = m.group('name')
            d.name = name
            d.expr = m.group('expr').strip()
            if name in _KEYWORDS or name in FUNCTIONS or name in COORDS \
                    or name.startswith('_'):
                d.error = (f'"{name}" is reserved' +
                           (' -- x and y are the plan coordinates' if name in COORDS else ''))
                continue
            if name in by_name:
                d.error = f'"{name}" is defined twice; the first definition is used'
                continue
            if m.group('params') is not None:
                d.params = tuple(p.strip() for p in m.group('params').split(','))
                if len(set(d.params)) != len(d.params):
                    d.error = 'A parameter name is repeated'
                    continue
            if not d.expr:
                d.error = 'Nothing after "="'
                continue
            by_name[name] = d

        # First look: which names each formula uses, bare or called.
        raw = {}
        for name, d in list(by_name.items()):
            try:
                raw[name] = _raw_names(d.expr)
            except FormulaError as exc:
                d.error = str(exc)
                del by_name[name]

        # Which param-less definitions are really functions of (x, y)? One
        # that uses x or y bare, or uses bare another function of (x, y) --
        # 'q = 25 t' with 't = 0.06 + 0.02x' -- is one, as in GeoGebra.
        # Found by a fixed point, since that can chain.
        xy_funcs = {n for n, d in by_name.items() if d.params == COORDS}
        changed = True
        while changed:
            changed = False
            for n, d in by_name.items():
                if d.params is None and n not in xy_funcs:
                    bare, _called = raw[n]
                    if bare & set(COORDS) or bare & (xy_funcs - {n}):
                        xy_funcs.add(n)
                        changed = True
        for n in xy_funcs:
            if by_name[n].params is None:
                by_name[n].params = COORDS

        for n, d in by_name.items():
            bare, called = raw[n]
            own = set(d.params or ())
            d.deps = {u for u in (bare | called) if u in by_name and u not in own}
            d.free = d.params is None and not d.deps and _is_literal(d.expr)
        autocall = {n for n, d in by_name.items() if d.params == COORDS}

        # evaluate in dependency order; a cycle or a broken dependency marks
        # the definitions involved, and only them
        state = {}

        def visit(name, stack):
            d = by_name[name]
            if state.get(name) == 'done':
                return d.kind != ERROR
            if state.get(name) == 'active':
                cyc = stack[stack.index(name):] + [name]
                for n in cyc[:-1]:
                    by_name[n].error = 'Circular definition: ' + ' -> '.join(cyc)
                    by_name[n].kind = ERROR
                    state[n] = 'done'
                return False
            if d.error:
                state[name] = 'done'
                return False
            state[name] = 'active'
            ok = True
            for dep in sorted(d.deps):
                if not visit(dep, stack + [name]):
                    ok = False
            if state.get(name) == 'done':     # closed by a cycle
                return False
            state[name] = 'done'
            if not ok:
                bad = [dep for dep in sorted(d.deps) if by_name[dep].kind == ERROR]
                d.error = 'Uses ' + ', '.join(f'"{b}"' for b in bad) + ', which has an error'
                d.kind = ERROR
                return False
            try:
                if d.params is None:
                    fn = compile_function(d.expr, (), self._ns_values, self._ns_funcs,
                                          autocall)
                    d.value = float(fn())
                    d.kind = NUMBER
                    self._ns_values[name] = d.value
                    if d.free and name not in self.sliders:
                        self.sliders[name] = default_slider(d.value)
                else:
                    d.fn = compile_function(d.expr, d.params, self._ns_values,
                                            self._ns_funcs, autocall)
                    d.kind = FUNCTION
                    self._ns_funcs[name] = (d.fn, len(d.params))
            except FormulaError as exc:
                d.error = str(exc)
                d.kind = ERROR
                return False
            return True

        for name in by_name:
            visit(name, [])
        self._autocall = {n for n in autocall if n in self._ns_funcs}
        for d in self.defs:
            if d.kind == ERROR and not d.error:
                d.error = 'Cannot evaluate'
        return self.errors()

    # -- persistence ----------------------------------------------------------
    def to_dict(self):
        return {'lines': self.lines,
                'sliders': {k: list(v) for k, v in self.sliders.items()
                            if self.has_number(k)}}

    @classmethod
    def from_dict(cls, data):
        return cls(data.get('lines', []), data.get('sliders', {}))
