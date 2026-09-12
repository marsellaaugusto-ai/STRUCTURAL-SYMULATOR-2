"""
common.py — shared foundation for the structural simulator.

Imports, global constants (colors, grid/canvas scale), environment-check
helpers (_ensure_openpyxl / _ensure_scipy / _ensure_matplotlib), generic
numeric utilities reused by more than one structural module
(_beam_gauss_solve, the shared 5-point Gauss-Legendre quadrature nodes,
_nice_ticks, _find_diagram_maxima, make_shape_fn, the moment-arrow glyph
helpers), and the ZoomCanvas pan/zoom widget.

Nothing in this file depends on truss_app / beam_app / arch_app / cable_app
-- it is the one module every other module imports FROM, never the reverse.
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import math, os, sys, subprocess
import numpy as np

def _ensure_openpyxl():
    try:
        import openpyxl
        return True
    except ImportError:
        pass
    try:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', 'openpyxl', '--quiet'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import openpyxl
        return True
    except Exception:
        return False

# ── auto-install scipy if missing (cable-web network solver) ──────────────────
def _ensure_scipy():
    """SciPy is NOT optional for Cable Web, despite the name of the code path
    that uses it.

    `cable_web_math.solve_analysis`'s bounded least-squares step is described
    in the source as a "fallback" behind the Newton/LM seeds, which reads as
    optional. Measured 2026-09-04 across both built-in examples and eight
    hand-built topologies: the Newton/LM seeds reach the 1e-9 tolerance on
    NO multi-cable network at all -- every converged web in the whole test
    run came from scipy.optimize.least_squares. A single cable between two
    supports still solves without it, which is exactly why a missing SciPy
    presents as an intermittent physics failure rather than as a missing
    dependency. See REPORTS AND GUIDES/CABLE_WEB_DIAGNOSIS_2026-09-04.md.
    """
    try:
        import scipy.optimize
        return True
    except ImportError:
        pass
    try:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', 'scipy', '--quiet'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import scipy.optimize
        return True
    except Exception:
        return False

# ── auto-install matplotlib+Pillow if missing (LaTeX-style equation images) ──
def _ensure_matplotlib():
    try:
        import matplotlib, PIL
        return True
    except ImportError:
        pass
    try:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', 'matplotlib', 'pillow', '--quiet'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import matplotlib, PIL
        return True
    except Exception:
        return False

def render_math(tex, fontsize=13, color='#1a1a1a', dpi=200):
    """
    Renders a math string in matplotlib's mathtext (a LaTeX-lookalike typesetter
    built into matplotlib — no separate TeX/LaTeX installation required) to a
    Tk-displayable PhotoImage. `tex` must be wrapped in $...$.
    Returns None if matplotlib/Pillow aren't available, so callers can fall
    back to a plain-text rendering instead.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import io
        from PIL import Image, ImageTk
        fig = plt.figure(figsize=(0.1, 0.1))
        fig.patch.set_alpha(0.0)
        t = fig.text(0, 0, tex, fontsize=fontsize, color=color)
        fig.canvas.draw()
        bbox = t.get_window_extent()
        w, h = bbox.width/fig.dpi, bbox.height/fig.dpi
        fig.set_size_inches(w+0.05, h+0.05)
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=dpi, transparent=True,
                    bbox_inches='tight', pad_inches=0.02)
        plt.close(fig)
        buf.seek(0)
        img = Image.open(buf).convert('RGBA')
        return ImageTk.PhotoImage(img)
    except Exception:
        return None

# ── layout ────────────────────────────────────────────────────────────────────
SNAP      = 24          # px per grid cell at zoom=1  (1 cell = 1 m)
PX_PER_M  = SNAP
PANEL_W   = 235
INIT_CW   = 860         # initial truss canvas width
INIT_CH   = 440         # initial truss canvas height
INIT_DH   = 260         # initial diagram canvas height (three bands: T, H, V)
INIT_FD   = 340         # initial funicular-diagram pane height

# Default cable self-weight, N/m. Deliberately nonzero: a cable with neither
# self-weight nor an applied load has no unique equilibrium, so before this a
# freshly drawn cable could not be analysed at all. 1 kN/m is a realistic
# heavy cable and reads as "1.000 kN/m" in the inspector. The field itself
# stays in N/m -- relabelling it would reinterpret every saved model by 1000x.
DEFAULT_SELF_WEIGHT = 1000.0

# ── colours ───────────────────────────────────────────────────────────────────
CT  = "#e24b4a"         # tension
CC  = "#378add"         # compression
CZ  = "#888888"         # zero / unanalysed
CD  = "#1D9E75"         # deformed
CN  = "#333333"         # node
CS  = "#EF9F27"         # selected / rod-start
CL  = "#D85A30"         # load arrow
CSP = "#555555"         # support
CG  = "#e8e8e8"         # grid
CG_MINOR = "#dcdcdc"    # grid — first finer LOD subdivision (dots)
CG_MICRO = "#ececec"    # grid — second finer LOD subdivision (dots)
CV  = "#7F77DD"         # shear diagram
CM  = "#D85A30"         # moment diagram
CMOM = CM                 # moment annotation/arc (legacy alias used by TrussApp)
CR  = "#2ecc71"         # reaction arrow


# ═══════════════════════════════════════════════════════════════════════════════
#  Geometry helpers
# ═══════════════════════════════════════════════════════════════════════════════
def snap(v):
    return round(v / SNAP) * SNAP

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

def _nice_ticks(vmin, vmax, target_count=6):
    """Returns a list of evenly-spaced 'nice' (1-2-5 x 10^k) tick values
    spanning at least [vmin, vmax] -- the same convention used by most
    plotting libraries, so a diagram's gridlines land on easy-to-read
    values (0, 5, 10, ... or 0, 20, 40, ...) instead of awkward fractions."""
    if vmax <= vmin:
        vmax = vmin + 1.0
    span = vmax - vmin
    raw_step = span / max(target_count, 1)
    if raw_step <= 0:
        return [vmin, vmax]
    mag = 10 ** math.floor(math.log10(raw_step))
    norm = raw_step / mag
    if norm < 1.5:
        nice = 1
    elif norm < 3:
        nice = 2
    elif norm < 7:
        nice = 5
    else:
        nice = 10
    step = nice * mag
    start = math.floor(vmin / step) * step
    ticks = []
    v = start
    while v <= vmax + step * 1e-6:
        if v >= vmin - step * 1e-6:
            ticks.append(round(v, 10))
        v += step
    return ticks


def _find_diagram_maxima(xs, ys, tol_rel=1e-3):
    """Finds every x-location where |ys| attains the diagram's maximum
    value, within a small relative tolerance -- so genuinely tied peaks
    (e.g. symmetric supports, symmetric loading) are ALL reported, not just
    the first one encountered. Adjacent/nearby samples belonging to the same
    peak (including the two twin samples straddling a jump discontinuity)
    are grouped into a single representative location, so a plateau or a
    discontinuity doesn't get reported as many separate "ties".

    Returns (locations, maxabs) where locations is a sorted list of x values.
    """
    if not ys:
        return [], 0.0
    absitems = [abs(v) for v in ys]
    maxabs = max(absitems)
    if maxabs < 1e-12:
        return [], 0.0
    tol = tol_rel * maxabs
    hits = [i for i, v in enumerate(absitems) if v >= maxabs - tol]
    if not hits:
        return [], maxabs
    groups = [[hits[0]]]
    for idx in hits[1:]:
        if idx - groups[-1][-1] <= 2:
            groups[-1].append(idx)
        else:
            groups.append([idx])
    locations = []
    for g in groups:
        best_idx = max(g, key=lambda i: absitems[i])
        locations.append(xs[best_idx])
    return locations, maxabs


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

def moment_arrow_points(cx, cy, r, ccw, n=24, sweep_deg=300.0, start_deg=100.0):
    """Pure geometry for a curved-arrow "applied moment" glyph, in SCREEN
    coordinates (y increases downward, as in a Tkinter canvas).

    Returns a flat list [x0, y0, x1, y1, ...] tracing an arc of `sweep_deg`
    degrees around (cx, cy) at radius r, ending at the point where an
    arrowhead should be drawn. Feed this straight into
    `canvas.create_line(*pts, arrow='last', ...)` -- Tk computes the
    arrowhead direction from the final segment, so the arrow naturally
    points along the curve.

    `ccw=True` traces the arc counterclockwise as the user actually SEES
    it on screen; `ccw=False` traces it clockwise. This is the one place
    that has to account for screen y being flipped relative to standard
    math convention -- callers just say which rotational sense they want
    and get the visually-correct arc back.
    """
    sign = 1.0 if ccw else -1.0
    pts = []
    for i in range(n + 1):
        theta = math.radians(start_deg + sign * sweep_deg * (i / n))
        x = cx + r * math.cos(theta)
        y = cy - r * math.sin(theta)  # flip: makes increasing theta = visually CCW on screen
        pts.extend([x, y])
    return pts


def draw_moment_arrow(canvas, cx, cy, r, ccw, color, width=2, arrowshape=(8, 10, 3)):
    """Draws a circular-arrow glyph for an applied/reaction moment at
    (cx, cy) with the given screen radius, oriented per the sign
    convention the caller has already resolved into `ccw` (True = CCW,
    False = CW -- e.g. `ccw = (M >= 0)` for a "+M = CCW" convention).
    Returns the canvas item id."""
    pts = moment_arrow_points(cx, cy, r, ccw)
    return canvas.create_line(*pts, fill=color, width=width, arrow='last',
                               arrowshape=arrowshape, capstyle='round', joinstyle='round')


class ZoomCanvas(tk.Frame):
    """
    A tk.Canvas wrapped with:
      - mouse-wheel zoom  (Ctrl+wheel or plain wheel)
      - middle-button press + drag pan
      - world ↔ screen coordinate transform helpers
    The caller draws everything in 'world' coordinates and calls
    w2s(wx,wy) to convert to screen before creating canvas items.
    """
    MIN_ZOOM = 0.15
    MAX_ZOOM = 8.0

    def __init__(self, master, zoom=1.0, **kw):
        bg = kw.pop('bg', 'white')
        super().__init__(master, bg=bg)
        self.zoom   = zoom
        self.pan_x  = 0.0      # world origin offset in pixels at zoom=1
        self.pan_y  = 0.0
        self._drag  = None

        self.canvas = tk.Canvas(self, bg=bg, **kw)
        self.canvas.pack(fill='both', expand=True)

        # scroll / zoom bindings
        self.canvas.bind('<MouseWheel>',      self._on_wheel)
        self.canvas.bind('<Button-4>',        self._on_wheel)   # Linux
        self.canvas.bind('<Button-5>',        self._on_wheel)   # Linux
        # Navigation is intentionally simple and CAD-like:
        #   wheel over the canvas = zoom
        #   press mouse wheel + drag = pan
        # Do not bind these globally; keeping them local to the canvas prevents
        # toolbar/property widgets from accidentally changing the view.
        self.canvas.bind('<ButtonPress-2>',   self._pan_start)
        self.canvas.bind('<B2-Motion>',       self._pan_move)
        self.canvas.bind('<ButtonRelease-2>', self._pan_end)

    # ── coordinate transforms ─────────────────────────────────────────────────
    def w2s(self, wx, wy):
        """world → screen"""
        sx = (wx + self.pan_x) * self.zoom
        sy = (wy + self.pan_y) * self.zoom
        return sx, sy

    def s2w(self, sx, sy):
        """screen → world"""
        wx = sx / self.zoom - self.pan_x
        wy = sy / self.zoom - self.pan_y
        return wx, wy

    # ── wheel ─────────────────────────────────────────────────────────────────
    def _on_wheel(self, event):
        # Zoom is intentionally restricted to genuine wheel events occurring
        # over this canvas. Some desktop/window-manager combinations can
        # deliver wheel notifications while focus is changing between toolbar
        # controls and the canvas; those must never alter the view.
        if getattr(event, 'widget', None) is not self.canvas:
            return 'break'
        if event.num not in (4, 5) and not getattr(event, 'delta', 0):
            return 'break'
        try:
            x, y = event.x, event.y
            w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
            if not (0 <= x <= w and 0 <= y <= h):
                return 'break'
        except Exception:
            return 'break'
        if event.num == 4 or event.delta > 0:
            factor = 1.15
        else:
            factor = 1/1.15
        new_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.zoom * factor))
        if new_zoom == self.zoom: return

        # keep mouse position fixed in world space
        sx, sy = event.x, event.y
        wx, wy = self.s2w(sx, sy)
        self.zoom   = new_zoom
        # recalculate pan so wx,wy maps back to sx,sy
        self.pan_x  = sx/self.zoom - wx
        self.pan_y  = sy/self.zoom - wy
        self._on_zoom_changed()
        return 'break'

    # ── pan ───────────────────────────────────────────────────────────────────
    def _pan_start(self, event):
        # Middle mouse is the dedicated pan command.  Capture the starting
        # pointer position and the current world offset; no model-selection
        # command is invoked by this gesture.
        self._drag = (event.x, event.y, self.pan_x, self.pan_y)
        try:
            self.canvas.configure(cursor='fleur')
        except tk.TclError:
            pass
        return 'break'

    def _pan_move(self, event):
        if self._drag is None: return 'break'
        x0,y0,px0,py0 = self._drag
        self.pan_x = px0 + (event.x-x0)/self.zoom
        self.pan_y = py0 + (event.y-y0)/self.zoom
        self._on_zoom_changed()
        return 'break'

    def _pan_end(self, event):
        self._drag = None
        try:
            self.canvas.configure(cursor='')
        except tk.TclError:
            pass
        return 'break'

    def _on_zoom_changed(self):
        """Override in subclass or bind externally."""
        pass

    def zoom_by(self, factor, center=None):
        """Zoom by *factor* around a screen point, defaulting to canvas center.

        This is a public command for UI buttons/keyboard shortcuts; it does
        not change the existing mouse-wheel behavior.
        """
        try:
            factor = float(factor)
        except Exception:
            return
        if factor <= 0:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if center is None:
            sx, sy = w / 2.0, h / 2.0
        else:
            sx, sy = center
        wx, wy = self.s2w(sx, sy)
        new_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.zoom * factor))
        if abs(new_zoom - self.zoom) < 1e-15:
            return
        self.zoom = new_zoom
        self.pan_x = sx / self.zoom - wx
        self.pan_y = sy / self.zoom - wy
        self._on_zoom_changed()

    def zoom_in(self):
        self.zoom_by(1.25)

    def zoom_out(self):
        self.zoom_by(1.0 / 1.25)

    def reset_view(self):
        self.zoom  = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._on_zoom_changed()
