"""numerics.py — the small numeric core, with no user interface in it.

SHARED and root-level, like `units.py` and `cirsoc_301.py`: no tab owns it
(see REPORTS AND GUIDES/MODULAR_ARCHITECTURE.md on why cross-tab imports are
not an option).

WHY THIS IS NOT IN common.py. `common.py` imports tkinter at module scope,
because most of what it holds is widgets. Anything importing it therefore
needs a working Tk, and these four names are the ones a SOLVER needs -- so a
solver that reached for them through `common` could not be imported, or
tested, without a display. That is not hypothetical: `apps/beam/beam_math.py`
exists to be the Beam tab's tkinter-free engine, and
`tests/test_beam_math.py` could not be collected at all on a Python built
without Tk, to test code with no UI in it (2026-10-04, R-8).

`common.py` re-exports every name below, so `from common import
_beam_gauss_solve` keeps working and keeps returning THIS function object --
`tests/tools/appdiag.py` reads its docstring to check which backend is live.

`apps/truss/truss_math.py` and `apps/cable_web/cable_web_math.py` are
described as pure engines but still import from `common`, so they still need
Tk; pointing them here instead is a one-line change each whenever someone is
next in those files.
"""
import math


def _require_numpy(note=''):
    """Return numpy, importing it on first use.

    Raises a message that names the package and what it is for, instead of
    letting an ImportError from module-import time surface somewhere
    unrelated. `note` adds a caller-specific line, since what a reader should
    do about it differs by tab. Cached, so a machine without numpy pays one
    failed import rather than one per solve.
    """
    global _np
    if _np is None:
        try:
            import numpy as _numpy
        except ImportError as exc:                  # pragma: no cover
            raise ImportError(
                'This solver needs NumPy, which could not be imported: '
                f'{exc}. Install it with "pip install numpy". If NumPy IS '
                'installed, a security policy may be blocking its compiled '
                'extension -- on Windows check Smart App Control under '
                'Windows Security > App & browser control.'
                + (' ' + note if note else '')
            ) from exc
        _np = _numpy
    return _np


_np = None


def _beam_gauss_solve(A, b):
    """Dense linear solve for the small (per-beam / per-cable-mini-solve)
    systems used throughout this project.

    Backed by numpy.linalg.solve (LAPACK's partial-pivoted LU) instead of
    the original interpreted-Python Gaussian elimination -- same algorithm
    family, same input/output contract, just a compiled backend. Preserves
    the original's safety behaviour of returning None for a
    singular/unreliable system (checked here via the actual solution
    residual, since a compiled LU solve doesn't expose the elimination's
    intermediate pivots the way the hand-written version did) rather than
    silently handing back a numerically meaningless "solution".

    RESTORED 2026-09-05. This is MANIFESTO Phase 1, and the version of the
    app this tree was merged from had reverted it to the hand-rolled
    interpreted-Python elimination (and dropped `import numpy as np` with
    it). That revert is invisible in normal use -- same answers, no error --
    but it is a measured ~40% slowdown on the cable-web test suite and ~33%
    wall-clock on the one UI case big enough to show it, and it applies to
    EVERY tab, since all five call this one function. See
    CABLE_WEB_DIAGNOSIS_2026-09-04.md and the note in sec 3t of
    MANIFESTO.md about silent reverts of shared code.
    """
    n = len(b)
    if n == 0:
        return []
    np = _require_numpy('(The Perforated Beam tab does not use this '
                        'function and works without it.)')
    Anp = np.asarray(A, dtype=float)
    bnp = np.asarray(b, dtype=float)
    try:
        x = np.linalg.solve(Anp, bnp)
    except np.linalg.LinAlgError:
        return None
    if not np.all(np.isfinite(x)):
        return None
    residual = Anp @ x - bnp
    scale = max(1.0, float(np.max(np.abs(bnp))))
    if np.max(np.abs(residual)) > 1e-8 * scale:
        return None
    return x.tolist()

_GAUSS5_NODES = (0.0, 0.5384693101056831, -0.5384693101056831,
                  0.9061798459386640, -0.9061798459386640)
_GAUSS5_WEIGHTS = (0.5688888888888889, 0.4786286704993665, 0.4786286704993665,
                    0.2369268850561891, 0.2369268850561891)


def make_shape_fn(expr, ctx):
    """
    Compiles a user-supplied 'y = f(x)' expression string into a callable.
    `ctx` is a dict of extra names allowed in the expression (e.g. L, f for
    span/rise). Only math-module names, names in ctx, and 'x' are permitted —
    no builtins — so this is safe for a local desktop tool.
    '^' is accepted as a power operator (translated to Python's '**') since
    that's the more familiar notation for most users writing math by hand.
    """
    expr = expr.replace('^', '**')

    # Accept common mathematical implicit multiplication, e.g.
    #   4 (x+1)  -> 4*(x+1)
    #   2x       -> 2*x
    #   x(x+1)   -> x*(x+1)
    # without breaking function calls such as sin(x).  Python's eval() does
    # not understand implicit multiplication, while users naturally write
    # expressions in conventional mathematical notation.
    import re
    expr = re.sub(r'(?<=[0-9\)])\s*(?=[A-Za-z_(])', '*', expr)
    expr = re.sub(r'(?<=[A-Za-z_])\s+(?=[0-9(])', '*', expr)

    code = compile(expr, '<arch shape>', 'eval')
    math_names = {k for k in dir(math) if not k.startswith('_')}
    allowed = set(ctx.keys()) | {'x', 'xc'} | math_names
    for name in code.co_names:
        if name not in allowed:
            raise ValueError(f"Unknown name in shape expression: '{name}'")
    math_ns = {k: getattr(math, k) for k in math_names}

    def fn(x):
        local = dict(ctx)
        local.update(math_ns)
        local['x'] = x
        # xc is the span-centered coordinate: -L/2 ... +L/2.
        # Keeping x as the global 0 ... L coordinate preserves compatibility.
        if 'L' in ctx:
            local['xc'] = x - float(ctx['L']) / 2.0
        else:
            local['xc'] = x
        value = eval(code, {'__builtins__': {}}, local)
        if isinstance(value, complex):
            if abs(value.imag) > 1e-10 * max(1.0, abs(value.real)):
                raise ValueError(f'Expression became non-real at x={x:g}. Check the domain or use xc=x-L/2 for centered equations.')
            value = value.real
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f'Expression is not finite at x={x:g}. Move the integration domain away from the singularity.')
        return value
    return fn
