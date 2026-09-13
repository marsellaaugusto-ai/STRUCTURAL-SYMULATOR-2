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

import units

# NumPy is imported LAZILY, inside `_beam_gauss_solve` -- the one function
# in this file that uses it. Read that function's docstring first: it warns
# against silently reverting the numpy solve to interpreted-Python
# elimination, and this is NOT that. The solve is untouched and every caller
# still gets numpy; only the import moved.
#
# Why it moved: this module is imported by EVERY tab, so an unconditional
# top-level `import numpy` means one unavailable dependency takes the whole
# application down -- including the Perforated Beam tab, which never calls
# `_beam_gauss_solve` and whose maths is stdlib-only by MANIFESTO s2. That
# happened for real on 2026-09-09: a Windows Application Control policy
# blocked numpy's _multiarray_umath DLL and no tab would start, not even the
# ones that do not use it. A tab that needs numpy now fails when it SOLVES,
# with a message naming numpy, instead of at import time on behalf of tabs
# that do not.
#
# 2026-09-09, second pass: the same import also sat at the top of
# `apps/cable_web/cable_web_math.py`, so the Cable Web tab still took the
# whole app down. Rather than write the same guard a second time -- MANIFESTO
# s3j, the same sub-problem solved in two places drifts -- the raise lives
# here, in `_require_numpy`, and both callers go through it.


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


DECLUTTER_MAX_ITEMS = 80   # see declutter_text's own docstring for why


def declutter_text(canvas, item_ids, step=14, max_passes=8, top_margin=2):
    """Nudge overlapping canvas TEXT items apart, upwards, in place.

    Load labels are placed relative to the thing they annotate, so two of them
    collide whenever two loads happen to sit at the same station -- a moment at
    x = 9 under a distributed load centred on x = 9 draws one label straight
    through the other. Rather than invent a placement rule per label type, this
    lifts whichever item is drawn later until nothing overlaps.

    Later items move, earlier ones stay put, so the reading order of a diagram
    is preserved: the first label placed keeps the position its own geometry
    asked for. An item is never lifted above `top_margin`, so decluttering
    cannot push a label off the canvas -- on a pane too short to separate them
    the labels stay overlapped, which is visible, rather than disappearing,
    which is not.

    Each pairwise comparison costs a real canvas.bbox() round-trip into the
    Tk/Tcl bridge, so the all-pairs loop below is fine for the handful of load
    labels this was designed for but becomes ruinously expensive on a dense
    mesh's node/member labels -- a 221-node grid is ~24k pairs per pass, times
    up to max_passes, i.e. hundreds of thousands of round-trips, observed to
    take minutes under a loaded display server. Past DECLUTTER_MAX_ITEMS this
    is skipped entirely and the labels are left exactly where they were drawn
    (the same "stays overlapped rather than disappearing" degrade mode the
    function already falls back to when it runs out of vertical room).
    """
    ids = [i for i in item_ids if canvas.type(i) == 'text']
    if len(ids) > DECLUTTER_MAX_ITEMS:
        return
    for _ in range(max_passes):
        moved = False
        boxes = {}
        for i in ids:
            b = canvas.bbox(i)
            if b:
                boxes[i] = b
        live = [i for i in ids if i in boxes]
        for a in range(len(live)):
            for b in range(a + 1, len(live)):
                ia, ib = live[a], live[b]
                A, B = boxes.get(ia), boxes.get(ib)
                if not A or not B:
                    continue
                overlap_x = min(A[2], B[2]) - max(A[0], B[0])
                overlap_y = min(A[3], B[3]) - max(A[1], B[1])
                if overlap_x > 2 and overlap_y > 2:
                    if B[1] - step < top_margin:
                        continue           # no room left; leave it visible
                    canvas.move(ib, 0, -step)
                    nb = canvas.bbox(ib)
                    if nb:
                        boxes[ib] = nb
                    moved = True
        if not moved:
            break


class LoadScale:
    """Relative, compressed glyph sizing for the loads in one diagram.

    Every load is drawn RELATIVE to the largest of its own kind currently on
    the model -- never at a fixed size, and never in linear proportion.

    Why not linear. A model routinely carries loads two or three orders of
    magnitude apart. Drawn 1:1, either the small load collapses to a stub too
    short to see or the large one runs off the canvas; there is no scale factor
    that avoids both. A square-root compression (`gamma=0.5`) keeps the
    ordering and a clearly visible ratio while bounding both ends. Measured
    against the default band, a 2:1 force ratio draws about 1.44:1 -- visibly
    different at a glance -- a 10:1 ratio about 2.7:1, and a 1000:1 ratio about
    4.7:1, with the smallest glyph still 10 px so it never vanishes.

    Why each kind of load gets its own scale. Point loads are a force (kN),
    distributed loads are a force per unit length (kN/m), and applied moments
    are a moment (kN*m). These are different physical quantities and there is
    no honest linear scale between them. Sharing one would also break a
    property that matters more: two distributed loads of EQUAL INTENSITY must
    draw at equal height whatever length each covers, and they only do so when
    the distributed family is normalised against an intensity of its own.
    So each family is normalised separately and mapped into the same pixel
    band, which makes the families visually comparable without pretending kN
    and kN/m are the same thing.

    `px_min` is a floor, not zero: a load of negligible magnitude beside a
    dominant one still has to be visible as a load, and a zero ordinate at the
    end of a triangular load still has to show where the load starts.
    """

    def __init__(self, vmax, px_min, px_max, gamma=0.70):
        self.vmax = abs(vmax or 0.0)
        self.px_min = float(px_min)
        self.px_max = float(px_max)
        self.gamma = gamma

    @classmethod
    def of(cls, values, px_min, px_max, gamma=0.70):
        """Build a scale from every magnitude of one family present."""
        vals = [abs(v) for v in values if v is not None]
        return cls(max(vals, default=0.0), px_min, px_max, gamma)

    @property
    def is_flat(self):
        """True when there is nothing to compare against, so every glyph in
        this family draws at full size rather than at the floor."""
        return self.vmax <= 1e-12

    def __call__(self, v):
        """Glyph size in px for a load of magnitude `v` (sign ignored)."""
        if self.is_flat:
            return self.px_max
        frac = min(1.0, abs(v) / self.vmax) ** self.gamma
        return self.px_min + (self.px_max - self.px_min) * frac


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


# ══════════════════════════════════════════════════════════════════════════════
#  Responsive layout helpers
# ══════════════════════════════════════════════════════════════════════════════
#
# Every tab in this project built the same two things by hand: a single-row
# toolbar, and a fixed-width right-hand sidebar packed AFTER the expanding
# canvas. Both fail the same way as the window narrows -- the toolbar's tail
# runs off the right edge, and the sidebar is squeezed to zero width and
# unmapped entirely, taking the Analyze button with it (measured on the Truss
# tab, 2026-09-05: at 800 px the whole right panel was gone).
#
# Cable Web solved the toolbar half first and paid for it three separate
# times -- see MANIFESTO sec 3c (a cached layout decision that locked in a
# wrong answer), sec 3d (grid() shares column widths across rows, so it is
# the wrong tool for a flow layout) and sec 3e (a pack(in_=...) anchor frame
# paints over the very widgets it positions unless you lower() it). Those
# three lessons are baked into FlowBar below.
#
# They live HERE, not in a tab, because the same sub-problem solved in two
# places will drift until it is actually the same code (MANIFESTO sec 3j).


class FlowBar:
    """Wrap a bar of control GROUPS onto as many rows as the current width
    needs, instead of letting the tail run off the right edge.

    Usage:
        bar = tk.Frame(parent, bg='#ebebea'); bar.pack(fill='x')
        flow = FlowBar(bar)
        g = flow.group()                       # a new group frame, registered
        tk.Button(g, text='Analyze', ...)      # build into it normally
        flow.add(some_frame_built_elsewhere)   # or register an existing one
        flow.start()                           # bind <Configure>, first layout

    A "group" is a set of controls that should stay together on one row (a
    tool palette, one labelled entry plus its button, ...). Groups wrap as
    units; a group too wide for the bar on its own wraps internally.

    `on_relayout` runs after every relayout -- use it for anything else that
    depends on the current width (e.g. resizing a sidebar to match).
    """

    def __init__(self, bar, on_relayout=None, group_gap=6, item_pad=2):
        self.bar = bar
        self.groups = []
        self.on_relayout = on_relayout
        self.group_gap = group_gap
        self.item_pad = item_pad
        self._pending = False
        self._running = False

    # -- construction ---------------------------------------------------------
    def group(self, **kw):
        """Create, register and return a new group frame."""
        kw.setdefault('bg', self.bar.cget('bg'))
        g = tk.Frame(self.bar, **kw)
        self.groups.append(g)
        return g

    def add(self, frame):
        """Register a group frame that was built elsewhere."""
        self.groups.append(frame)
        return frame

    def separator(self, color='#ccc', height=20):
        """A thin vertical rule as its own group, so it wraps with the flow
        instead of stranding itself at the end of a row."""
        g = self.group()
        tk.Frame(g, width=1, height=height, bg=color).pack(padx=4, pady=3)
        return g

    def start(self):
        """Bind the bar's <Configure> and perform the first layout."""
        self.bar.bind('<Configure>', self._schedule, add='+')
        self.bar.after_idle(self.relayout)

    # -- layout ---------------------------------------------------------------
    def _schedule(self, _event=None):
        if self._pending:
            return
        self._pending = True
        try:
            self.bar.after_idle(self.relayout)
        except Exception:
            self._pending = False

    def relayout(self):
        # Responsive layout must be re-entrant safe. Changing pack geometry
        # generates <Configure> events; never let those recursively rebuild
        # the bar while it is already being rebuilt.
        try:
            if not self.bar.winfo_exists():
                return
        except Exception:
            return
        if self._running:
            return
        self._pending = False
        self._running = True
        try:
            available = max(1, self.bar.winfo_width() - 10)
            # NOTE: deliberately NOT cached on `available`. A cache keyed only
            # on "the width did not change" once locked in a WRONG layout
            # here: the first call (from after_idle, before the window's
            # geometry had stabilised) read a transient width, computed a
            # layout from it, and cached it -- so a later, legitimate
            # <Configure> reporting the same FINAL width hit the cache and
            # never recomputed, leaving groups placed off-screen indefinitely.
            # MANIFESTO sec 3c. Recomputing costs <1 ms for a few dozen
            # widgets, so the cache bought nothing and cost that bug class.
            live = []
            for g in self.groups:
                try:
                    if g.winfo_exists():
                        live.append(g)
                except Exception:
                    pass
            self.groups = live

            # 1. Lay out each group's own children, wrapping internally only
            #    if the group alone is wider than the bar. Each group's
            #    effective width is recorded here in `group_width` rather
            #    than re-read from winfo_reqwidth() in step 2 below: pack()
            #    only SCHEDULES Tk's geometry recomputation, it does not run
            #    it, so querying reqwidth() on a group _wrap_children just
            #    finished re-packing (destroying its old internal rows and
            #    creating new ones) can observe a transient ~1px placeholder
            #    from between the two -- which corrupted step 2's row-wrap
            #    decision for exactly that group on exactly that pass,
            #    changing how many rows the bar needs, which resizes the
            #    canvas below it, which fires ANOTHER <Configure> that
            #    schedules ANOTHER relayout: observed in practice as the
            #    bar's width cycling through a fixed set of values forever
            #    instead of settling. (An earlier fix forced the recompute
            #    with a mid-relayout bar.update_idletasks() call instead --
            #    that resolved the oscillation too, but it flushes Tk's
            #    whole pending-idle queue from inside an already-running
            #    relayout, which can silently run and discard a second
            #    relayout call queued by an earlier _schedule() before this
            #    one's own reentrancy guard was reached, dropping a pass
            #    that was needed to fully map every control -- reproduced as
            #    test_truss_layout.py's widest-window case losing 8 controls.
            #    Recording each group's already-known width sidesteps the
            #    stale read directly, with no extra Tk event processing.)
            group_width = {}
            for g in self.groups:
                for w in list(g.winfo_children()):
                    if getattr(w, '_is_wrap_row', False):
                        w.destroy()
                children = [w for w in g.winfo_children()
                            if not getattr(w, '_is_wrap_row', False)]
                for child in children:
                    child.pack_forget()
                    child.grid_forget()
                req = sum(max(ch.winfo_reqwidth(), 1) + 2 * self.item_pad
                          for ch in children)
                if req > available:
                    group_width[g] = self._wrap_children(g, available, self.item_pad)
                else:
                    for child in children:
                        child.pack(side='left', padx=self.item_pad, pady=3)
                    group_width[g] = req

            # 2. Lay the groups out left-to-right, wrapping whole groups onto
            #    new ROWS. One Frame per row, packed top-to-bottom -- NOT
            #    grid(row=, column=) on the bar: Tk's grid shares each
            #    column's width across every row of the same parent, so a
            #    wide group in row 1 silently pushes a narrow group sharing
            #    that column in row 0 off the visible bar. MANIFESTO sec 3d.
            for w in list(self.bar.winfo_children()):
                if getattr(w, '_is_flow_row', False):
                    w.destroy()
            for g in self.groups:
                g.pack_forget()
                g.grid_forget()
            rows = [[]]
            used = 0
            for g in self.groups:
                req = max(group_width.get(g, 1), 1)
                if used and used + self.group_gap + req > available:
                    rows.append([])
                    used = 0
                rows[-1].append(g)
                used += req + self.group_gap
            for row_groups in rows:
                row_frame = tk.Frame(self.bar, bg=self.bar.cget('bg'))
                row_frame._is_flow_row = True
                row_frame.pack(side='top', fill='x', anchor='w', pady=1)
                # See _wrap_children: this anchor frame must be pushed BEHIND
                # the (true-sibling) groups it positions, or it paints over
                # them and the bar renders blank. MANIFESTO sec 3e.
                row_frame.lower()
                for g in row_groups:
                    g.pack(in_=row_frame, side='left', padx=0)

            if self.on_relayout is not None:
                self.on_relayout()
        finally:
            self._running = False

    @staticmethod
    def _wrap_children(group, available, pad):
        """Lay out one group's own children left-to-right, wrapping to an
        internal second/third row only if the group's content alone does not
        fit `available`. One Frame per internal row + pack -- see relayout's
        note on why grid() is the wrong tool here (MANIFESTO sec 3d).
        """
        for w in list(group.winfo_children()):
            if getattr(w, '_is_wrap_row', False):
                w.destroy()
        children = [w for w in group.winfo_children()
                    if not getattr(w, '_is_wrap_row', False)]
        for child in children:
            child.pack_forget()
            child.grid_forget()
        rows = [[]]
        row_widths = [0]
        used = 0
        for child in children:
            req = max(child.winfo_reqwidth(), 1)
            if used and used + pad + req > available:
                rows.append([])
                row_widths.append(0)
                used = 0
            rows[-1].append(child)
            used += req + pad
            row_widths[-1] = used
        for row_children in rows:
            row_frame = tk.Frame(group, bg=group.cget('bg'))
            row_frame._is_wrap_row = True
            row_frame.pack(side='top', anchor='w')
            # row_frame is a geometric anchor only: pack(in_=...) does NOT
            # reparent the buttons, they stay true siblings of row_frame under
            # `group`. Tk stacks true siblings by creation time, so this
            # freshly-created frame would paint OVER the (older) buttons it is
            # meant merely to position, hiding them completely while every one
            # of them still reports itself correctly mapped. MANIFESTO sec 3e.
            row_frame.lower()
            for child in row_children:
                child.pack(in_=row_frame, side='left', padx=pad, pady=2)
        # The group's own effective width, once stacked into these rows, is
        # its WIDEST row -- returned so relayout() can use this already-known
        # value instead of re-reading winfo_reqwidth() (see relayout's own
        # note on why that reread is unsafe immediately after this repack).
        return max(row_widths)


class ScrollPanel(tk.Frame):
    """A fixed-width side panel whose content stays reachable at every window
    width: it scrolls in BOTH axes, and it is never squeezed out of existence
    by an expanding sibling canvas.

    Build into `.interior`, exactly as you would into a plain panel Frame::

        panel = ScrollPanel(main, width=PANEL_W)
        panel.pack(side='right', fill='y')     # BEFORE the expanding canvas
        self._build_panel(panel.interior)

    Two failure modes this exists to prevent, both measured on the Truss tab:

    1. **The panel disappears.** Tk's pack allocates a parcel per slave *in
       packing order*. A panel packed AFTER an expand=True canvas gets
       whatever the canvas left over -- which at narrow widths is nothing, so
       the panel is unmapped entirely and every control in it (including
       Analyze) becomes unreachable, with no scrollbar and no warning. Pack
       this panel BEFORE the expanding canvas. Cable Web hit and documented
       the same ordering trap in its own `_build_ui`.

    2. **The panel's content is clipped.** Pinning the scrolled interior to
       exactly the panel width means any row wider than the panel (a slider
       next to its label, a two-button row) is cut off mid-widget with no way
       to reach it. Here the interior keeps its natural requested width and a
       horizontal scrollbar appears only when it exceeds the visible width.
    """

    #: Largest share of the window the panel may take. Below this the panel
    #: keeps its full content width; above it, the panel yields to the
    #: drawing canvas and the horizontal scrollbar covers the difference.
    MAX_WINDOW_SHARE = 0.45

    def __init__(self, master, width=PANEL_W, bg='#f0f0ee', **kw):
        super().__init__(master, width=width, bg=bg, **kw)
        self.base_width = width
        self.pack_propagate(False)
        self.grid_propagate(False)
        self._syncing = False

        self.vsb = tk.Scrollbar(self, orient='vertical')
        self.hsb = tk.Scrollbar(self, orient='horizontal')
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, width=width,
                                yscrollcommand=self.vsb.set,
                                xscrollcommand=self.hsb.set)
        self.vsb.configure(command=self.canvas.yview)
        self.hsb.configure(command=self.canvas.xview)
        # grid, not pack, for these three: the horizontal scrollbar appears
        # and disappears with need, and a pack()ed latecomer is allocated
        # AFTER the expand=True canvas has already taken the whole cavity --
        # so it silently gets zero height and never shows. (Measured while
        # building this: hsb reported _hsb_shown=True with a correct
        # scrollregion and was still invisible.) That is the same packing-
        # order trap this class exists to prevent, one level down; grid's
        # row/column weights are immune to it. This is a fixed 2x2 frame,
        # not a flow layout, so MANIFESTO sec 3d does not apply.
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.vsb.grid(row=0, column=1, sticky='ns')
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._hsb_shown = False

        self.interior = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.interior,
                                              anchor='nw')
        self.interior.bind('<Configure>', self._sync)
        self.canvas.bind('<Configure>', self._sync)

        # Same wheel idiom as every other panel in this project (Beam, Arch,
        # Cable, Perforated Beam): bind_all while the pointer is over the
        # panel, so the wheel scrolls the panel rather than whatever happens
        # to hold focus, released again on <Leave>.
        self.canvas.bind('<Enter>', lambda e: self.canvas.bind_all(
            '<MouseWheel>', self._on_wheel))
        self.canvas.bind('<Leave>', lambda e: self.canvas.unbind_all(
            '<MouseWheel>'))

    # -- scrolling ------------------------------------------------------------
    def _on_wheel(self, event):
        # Shift+wheel scrolls horizontally -- the usual convention, and the
        # only way to reach clipped content on a device with no h-wheel.
        try:
            if event.state & 0x0001:
                self.canvas.xview_scroll(int(-1 * (event.delta / 120)), 'units')
            else:
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        except Exception:
            pass

    def _sync(self, _event=None):
        # Packing/unpacking the horizontal scrollbar changes the canvas size,
        # which fires <Configure>, which re-enters here. Guard it.
        if self._syncing:
            return
        self._syncing = True
        try:
            req_w = max(self.interior.winfo_reqwidth(), 1)
            view_w = max(self.canvas.winfo_width(), 1)
            # Stretch the interior to fill the panel when it is narrower than
            # the view (so fill='x' children still span the panel), but never
            # squeeze it below its natural width -- that is what clipped the
            # wrapped help text and the slider rows before.
            self.canvas.itemconfigure(self._win, width=max(req_w, view_w))
            need_h = req_w > view_w + 1
            if need_h and not self._hsb_shown:
                self.hsb.grid(row=1, column=0, sticky='ew')
                self._hsb_shown = True
            elif not need_h and self._hsb_shown:
                self.hsb.grid_remove()
                self._hsb_shown = False
            bbox = self.canvas.bbox('all')
            if bbox:
                self.canvas.configure(scrollregion=bbox)
        except Exception:
            pass
        finally:
            self._syncing = False

    # -- sizing ---------------------------------------------------------------
    def fit_to_content(self, max_width=None):
        """Grow the panel so its content's natural width fits, and adopt that
        as the new base width for `apply_responsive_width`.

        Call this once, right after building into `.interior`. It is what
        keeps this class from quietly regressing: a later change that adds a
        slightly wider row widens the panel to suit instead of pushing that
        row under the horizontal scrollbar where nobody looks for it. The cap
        stops one runaway widget from eating the drawing canvas -- past it,
        the horizontal scrollbar takes over as intended.
        """
        try:
            self.update_idletasks()
            need = self.interior.winfo_reqwidth() + self.vsb.winfo_reqwidth()
            cap = max_width if max_width is not None else int(self.base_width * 1.6)
            w = max(self.base_width, min(need, cap))
            self.base_width = w
            self.configure(width=w)
            self.canvas.configure(width=w)
            self._sync()
            return w
        except Exception:
            return self.base_width

    # -- responsive width -----------------------------------------------------
    def apply_responsive_width(self, window_width):
        """Set the panel width from the containing window's width.

        Two rules, no breakpoint table:

        * never wider than its content needs (`base_width`, which
          `fit_to_content` set from the content itself), and
        * never more than `MAX_WINDOW_SHARE` of the window.

        The first is what a scaled-by-breakpoint sidebar gets wrong. Cable
        Web's `_update_responsive_sidebars` shrinks its panels by a fixed
        percentage at each step, which on this panel pushed Analyze, Set
        Pinned and Clear UDL 12-20 px past the right edge on a 700 px window
        -- reachable only by scrolling sideways to find the button you were
        already looking at. Shrinking below the content buys canvas width at
        exactly the price the content is worth; so shrink only once the panel
        would otherwise dominate a small window, and let the horizontal
        scrollbar cover that last case rather than every case.
        """
        w = self.base_width
        if window_width > 1:
            w = min(w, max(120, int(window_width * self.MAX_WINDOW_SHARE)))
        try:
            if int(self.cget('width')) != w:
                self.configure(width=w)
                self.canvas.configure(width=w)
                self._sync()
        except Exception:
            pass
        return w


class WrapBar:
    """Flow the direct children of an EXISTING single-row bar across as many
    rows as the current width needs, without restructuring how that bar was
    built.

    `FlowBar` is the better tool when you are writing the bar: it keeps
    related controls together as groups, so a wrap never splits a labelled
    entry from its button. But three tabs already had a toolbar built as one
    long run of `.pack(side='left')` calls, and rewriting each into groups is
    a large diff with nothing to show for it beyond nicer wrap points. This
    adopts such a bar as-is:

        bar = tk.Frame(...); bar.pack(fill='x')
        ...   # existing tk.Button(bar, ...).pack(side='left') calls, untouched
        self.toolbar_wrap = WrapBar(bar)
        self.toolbar_wrap.start()

    It reuses FlowBar's own row-wrapping, so it inherits the same three
    lessons (MANIFESTO 3c/3d/3e): no cached layout decision, one Frame per
    row rather than a shared-column grid, and `.lower()` on every anchor
    frame so it does not paint over the widgets it positions.
    """

    def __init__(self, bar, on_relayout=None, item_pad=2):
        self.bar = bar
        self.on_relayout = on_relayout
        self.item_pad = item_pad
        self._pending = False
        self._running = False

    def start(self):
        self.bar.bind('<Configure>', self._schedule, add='+')
        self.bar.after_idle(self.relayout)

    def _schedule(self, _event=None):
        if self._pending:
            return
        self._pending = True
        try:
            self.bar.after_idle(self.relayout)
        except Exception:
            self._pending = False

    def relayout(self):
        try:
            if not self.bar.winfo_exists():
                return
        except Exception:
            return
        if self._running:
            return
        self._pending = False
        self._running = True
        try:
            available = max(1, self.bar.winfo_width() - 10)
            FlowBar._wrap_children(self.bar, available, self.item_pad)
            if self.on_relayout is not None:
                self.on_relayout()
        finally:
            self._running = False


# ═════════════════════════════════════════════════════════════════════════════
class UnitsMixin:
    """Show a tab's numbers in the unit convention chosen above the notebook.

    The Beam tab was wired to `units.py` by hand first. Doing that five more
    times would mean six copies of the same four ideas, which is exactly how
    two tabs end up disagreeing about what a kip is (MANIFESTO s3j). So the
    machinery lives here and each tab supplies only what is genuinely its own:
    which of its fields are which physical quantity, and what to repaint.

    A tab mixes this in, calls `init_units(repaint=...)` once its widgets
    exist, and then:

        self.unit_label(lb, lambda: f'E ({self.u("modulus")}):')
        self.unit_var(self.mat_E, 'modulus')
        text = self.fmt('force', N, digits=2)

    -- the property this must never break -----------------------------------
    Switching conventions is PRESENTATION ONLY. It converts on the way to a
    label and back from an entry box; it must never rewrite the tab's model.
    Registered *entry variables* are inputs -- a value about to be applied, not
    the model itself -- so they are converted in place and rounded for
    legibility. The model is re-read and repainted from storage instead, which
    is why `init_units` takes a repaint callback rather than trying to convert
    stored state.

    -- storage is not uniform across the tabs -------------------------------
    `STORAGE_UNITS` says what THIS tab holds its numbers in. It defaults to
    `units.STORAGE` (kN, m, cm2, cm4, GPa, kN/cm2), which is what the Beam,
    Arch and Cable tabs use, but the Truss tab has always held plate yield in
    MPa and plate thickness in mm. Declaring the difference is safer than
    changing either tab's storage, which would silently reinterpret every
    model already saved.
    """

    STORAGE_UNITS = units.STORAGE

    # field name -> quantity, so one table refresh converts every column
    # without a per-column special case. Fields that are not numbers (a
    # support type, a q(x) expression, a name) map to None and pass through.
    _FIELD_Q = {}

    # Significant figures kept when an entry box is rewritten in a new
    # convention. Six is far beyond any meaningful input precision -- a
    # modulus is not known to one part in a million -- and stops a switch to
    # AISC from turning "10" into "32.808398950131235".
    UNIT_ENTRY_SIGFIGS = 6

    # -- setup --------------------------------------------------------------
    def init_units(self, repaint=None):
        """Start following the selector. `repaint` is called after every
        switch, once labels and entry variables have been updated, and is
        where a tab redraws its results text, tables and diagrams."""
        self._unit_labels = []
        self._unit_vars = []
        self._unit_shown_in = units.current()
        self._unit_repaint = repaint
        self._units_listener = units.on_change(self._units_changed)
        return self._units_listener

    def stop_units(self):
        """Detach from the selector. Tabs are never destroyed in the running
        app, but the tests build and tear down hundreds of them, and a
        listener holding a dead widget would be called forever."""
        fn = getattr(self, '_units_listener', None)
        if fn is not None:
            units.off_change(fn)
            self._units_listener = None

    # -- the four things a tab asks for -------------------------------------
    def u(self, quantity):
        """The label the current convention writes this quantity in."""
        return units.label(quantity)

    def show(self, quantity, stored):
        """A value as this tab stores it -> the number to show the user."""
        if isinstance(stored, bool) or not isinstance(stored, (int, float)):
            return stored
        return units.current().from_si(
            quantity, self.STORAGE_UNITS.to_si(quantity, stored))

    def store(self, quantity, shown):
        """The inverse of `show`, for a number the user typed."""
        if isinstance(shown, bool) or not isinstance(shown, (int, float)):
            return shown
        return self.STORAGE_UNITS.from_si(
            quantity, units.current().to_si(quantity, shown))

    def fmt(self, quantity, stored, digits=2, with_label=True, sign=False,
            width=0):
        """Format a STORED value in the current convention, e.g. '12.50 kN'."""
        spec = f'{"+" if sign else ""}{width or ""}.{digits}f'
        text = format(self.show(quantity, stored), spec)
        return f'{text} {self.u(quantity)}' if with_label else text

    # -- the same three, keyed by model field name --------------------------
    def _shown(self, field, stored):
        q = self._FIELD_Q.get(field)
        return stored if q is None else self.show(q, stored)

    def _stored(self, field, shown):
        q = self._FIELD_Q.get(field)
        return shown if q is None else self.store(q, shown)

    def _u(self, field):
        q = self._FIELD_Q.get(field)
        return units.label(q) if q else ''

    # -- registration -------------------------------------------------------
    def unit_label(self, widget, build, option='text'):
        """Register a widget whose text names a unit, and paint it now.

        `build` is called with no arguments and returns the full text, so the
        wording stays next to the widget it belongs to instead of being
        reassembled from fragments inside the repaint routine.
        """
        self._unit_labels.append((widget, build, option))
        try:
            widget.config(**{option: build()})
        except tk.TclError:
            pass
        return widget

    def unit_var(self, var, quantity, digits=None):
        """Register a Tk entry variable holding a value in STORAGE units.

        The variable then SHOWS the value in whatever convention is selected,
        while the mixin keeps the exact storage figure. Read it back with
        `unit_value(var)` and write it with `set_unit_value(var, ...)`; both
        deal in storage units, so nothing that feeds a solver has to know a
        convention was ever chosen.
        """
        rec = {'var': var, 'q': quantity, 'digits': digits,
               'stored': self._var_get(var), 'shown': None}
        self._unit_vars.append(rec)
        self._paint_var(rec)
        return var

    def unit_value(self, var, default=0.0):
        """The STORAGE value behind a registered box.

        Exactly the figure last put there if the box has not been edited, and
        the typed number converted out of the displayed convention if it has.
        Going through the record rather than through `store(var.get())` is
        what stops a switch to AISC and back from turning 20 m into
        20.00000064 m: the displayed number is rounded to stay readable, so it
        can never be the authoritative copy.
        """
        rec = self._unit_rec(var)
        if rec is None:
            v = self._var_get(var)
            return default if v is None else v
        self._sync_var(rec)
        return default if rec['stored'] is None else rec['stored']

    def set_unit_value(self, var, stored):
        """Put a STORAGE value into a registered box, written in the current
        convention."""
        rec = self._unit_rec(var)
        if rec is None:
            var.set(stored)
            return
        rec['stored'] = stored
        self._paint_var(rec)

    # -- repainting ---------------------------------------------------------
    def _units_alive(self):
        """Whether this tab still exists. Most tabs ARE widgets; the Truss tab
        is a plain object that owns a root, so ask whichever of the two can
        answer and assume alive if neither can."""
        for owner in (self, getattr(self, 'root', None), getattr(self, 'master', None)):
            exists = getattr(owner, 'winfo_exists', None)
            if exists is not None:
                try:
                    return bool(exists())
                except Exception:
                    return False
        return True

    def _units_changed(self, system):
        if not self._units_alive():
            self.stop_units()
            return
        # Adopt anything the user typed BEFORE the convention changes, since
        # what they typed was written in the old one.
        for rec in list(self._unit_vars):
            self._sync_var(rec)
        self._unit_shown_in = system
        for rec in list(self._unit_vars):
            self._paint_var(rec)
        for widget, build, option in list(self._unit_labels):
            try:
                if widget.winfo_exists():
                    widget.config(**{option: build()})
            except tk.TclError:
                pass
        if self._unit_repaint is not None:
            self._unit_repaint()

    # -- small helpers ------------------------------------------------------
    def _unit_rec(self, var):
        for rec in getattr(self, '_unit_vars', ()):
            if rec['var'] is var:
                return rec
        return None

    def _sync_var(self, rec):
        """Adopt what the box says, if it differs from what we last wrote
        there. The number is read in the convention it was DISPLAYED in, which
        is not necessarily the one now selected."""
        now = self._var_get(rec['var'])
        if now is None:                      # half-typed; keep what we have
            return
        written = rec['shown']
        if isinstance(written, str):
            try:
                written = float(written)
            except ValueError:
                written = None
        if written is None or now != written:
            was = getattr(self, '_unit_shown_in', None) or units.current()
            rec['stored'] = self.STORAGE_UNITS.from_si(
                rec['q'], was.to_si(rec['q'], now))

    def _paint_var(self, rec):
        if rec['stored'] is None:
            return
        rec['shown'] = self._set_rounded(
            rec['var'], self.show(rec['q'], rec['stored']), rec['digits'])

    @staticmethod
    def _var_get(var):
        """A Tk variable's value, or None if the box holds something that is
        not a number yet. A user mid-keystroke must not be able to make the
        unit selector raise."""
        try:
            return float(var.get())
        except (tk.TclError, ValueError, TypeError):
            return None

    def _set_rounded(self, var, value, digits=None):
        """Write a legible version of `value` and return what was written, so
        a later edit can be told apart from our own rounding.

        A StringVar gets a `%g` STRING, not a float: those boxes are the ones
        where blank means "not set", and writing 1350.0 where the user had
        typed 1350 is a visible change for no reason.
        """
        try:
            if digits is not None:
                shown = round(value, digits)
            else:
                shown = float('%.*g' % (self.UNIT_ENTRY_SIGFIGS, value))
            if isinstance(var, tk.StringVar):
                text = '%g' % shown
                var.set(text)
                return text
            var.set(shown)
            return shown
        except (tk.TclError, ValueError, OverflowError):
            return None
