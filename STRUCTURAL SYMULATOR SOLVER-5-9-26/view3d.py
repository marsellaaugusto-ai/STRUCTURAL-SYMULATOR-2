"""view3d.py -- an orbiting 3-D camera for a ZoomCanvas, 2026-09-14.

The Stereo tab built its orbit view inside its own controller. The Shell
tab needs the same camera and more (shaded faces, a painter's sort, a
colour legend), so the camera lives here, where any tab can use it. It
imports no tab. (Moving the Stereo tab onto it is a follow-up; the
projection below is the same formula Stereo uses, vectorised.)

    cam = Orbit3D(zoom_canvas)
    cam.fit(points)                       # points: (n, 3) array, metres
    sx, sy = cam.project(points)          # canvas pixels, arrays
    depth = cam.depth(points)             # larger = nearer the viewer
    cam.bind_orbit(on_change=redraw, on_click=pick)

Left-drag orbits; a left press-and-release that moves less than a few
pixels is a CLICK and is passed to `on_click(event)` instead. Wheel zoom and
middle-drag pan are ZoomCanvas's own.
"""
import math

import numpy as np

VIEWS = {
    'Iso': (-62.0, 24.0),
    'Top': (-90.0, 89.9),
    'Front': (-90.0, 0.0),
    'Side': (0.0, 0.0),
}

CLICK_PX = 4


class Orbit3D:
    def __init__(self, zc, az_deg=-62.0, el_deg=24.0):
        self.zc = zc
        self.az = math.radians(az_deg)
        self.el = math.radians(el_deg)
        self.scale = 40.0
        self.center = np.zeros(3)
        self._drag = None
        self._on_change = None
        self._on_click = None

    # -- geometry -------------------------------------------------------------
    def basis(self):
        """Unit vectors (right, up, toward viewer) in world coordinates."""
        ca, sa = math.cos(self.az), math.sin(self.az)
        ce, se = math.cos(self.el), math.sin(self.el)
        right = np.array([-sa, ca, 0.0])
        toward = np.array([ca * ce, sa * ce, se])
        up = np.cross(toward, right)
        return right, up, toward

    def project(self, P):
        """World points (n, 3) -> canvas pixel coordinates (sx, sy) arrays."""
        P = np.atleast_2d(np.asarray(P, float)) - self.center
        right, up, _ = self.basis()
        wx = (P @ right) * self.scale
        wy = -(P @ up) * self.scale
        z, px, py = self.zc.zoom, self.zc.pan_x, self.zc.pan_y
        return (wx + px) * z, (wy + py) * z

    def depth(self, P):
        P = np.atleast_2d(np.asarray(P, float)) - self.center
        return P @ self.basis()[2]

    def fit(self, P, margin=0.80):
        """Centre and scale so the points fill `margin` of the canvas."""
        P = np.atleast_2d(np.asarray(P, float))
        if not len(P):
            return
        cv = self.zc.canvas
        W = cv.winfo_width()
        H = cv.winfo_height()
        W = W if W > 10 else 800
        H = H if H > 10 else 520
        self.center = 0.5 * (P.min(axis=0) + P.max(axis=0))
        right, up, _ = self.basis()
        Q = P - self.center
        xs, ys = Q @ right, -(Q @ up)
        span_x = max(xs.max() - xs.min(), 1e-9)
        span_y = max(ys.max() - ys.min(), 1e-9)
        self.scale = margin * min(W / span_x, H / span_y)
        self.zc.zoom = 1.0
        self.zc.pan_x = W / 2.0 - self.scale * (xs.max() + xs.min()) / 2.0
        self.zc.pan_y = H / 2.0 - self.scale * (ys.max() + ys.min()) / 2.0

    def set_view(self, name):
        az, el = VIEWS[name]
        self.az, self.el = math.radians(az), math.radians(el)

    # -- mouse ------------------------------------------------------------------
    def bind_orbit(self, on_change=None, on_click=None):
        self._on_change = on_change
        self._on_click = on_click
        cv = self.zc.canvas
        cv.bind('<ButtonPress-1>', self._press)
        cv.bind('<B1-Motion>', self._move)
        cv.bind('<ButtonRelease-1>', self._release)

    def _press(self, e):
        self._drag = (e.x, e.y, self.az, self.el, False)

    def _move(self, e):
        if not self._drag:
            return
        x0, y0, az0, el0, moved = self._drag
        if not moved and abs(e.x - x0) + abs(e.y - y0) < CLICK_PX:
            return
        self._drag = (x0, y0, az0, el0, True)
        self.az = az0 - (e.x - x0) * 0.01
        self.el = max(math.radians(-89.9), min(math.radians(89.9), el0 + (e.y - y0) * 0.01))
        if self._on_change:
            self._on_change()

    def _release(self, e):
        d = self._drag
        self._drag = None
        if d and not d[4] and self._on_click:
            self._on_click(e)


# ═══════════════════════════════════════════════════════════════════════════
#  Colour scales
# ═══════════════════════════════════════════════════════════════════════════
# Two scales, chosen for reading magnitudes and signs apart. Both are
# listed low -> high as RGB triples and interpolated linearly.
SEQUENTIAL = [(247, 251, 255), (198, 219, 239), (107, 174, 214),
              (33, 113, 181), (8, 48, 107)]
DIVERGING = [(33, 102, 172), (103, 169, 207), (209, 229, 240), (247, 247, 247),
             (253, 219, 199), (239, 138, 98), (178, 24, 43)]
# Utilisation: green -> yellow at 0.8 -> red at 1.0 -> dark red beyond.
UTIL = [(26, 152, 80), (145, 207, 96), (217, 239, 139), (254, 224, 139),
        (252, 141, 89), (215, 48, 39), (120, 0, 0)]
UTIL_STOPS = [0.0, 0.4, 0.6, 0.8, 0.95, 1.0, 1.5]


def _interp(stops, colours, v):
    v = np.clip(v, stops[0], stops[-1])
    out = np.empty((len(v), 3))
    for k in range(3):
        out[:, k] = np.interp(v, stops, [c[k] for c in colours])
    return out


def colours_for(values, kind='sequential', vmin=None, vmax=None):
    """Hex colours for an array of values. 'diverging' is centred on zero
    (symmetric limits); 'util' is the fixed utilisation scale."""
    v = np.asarray(values, float)
    finite = np.isfinite(v)
    if kind == 'util':
        rgb = _interp(UTIL_STOPS, UTIL, np.where(finite, v, 2.0))
        lo, hi = 0.0, 1.5
    elif kind == 'diverging':
        m = vmax if vmax is not None else (np.nanmax(np.abs(v[finite])) if finite.any() else 1.0)
        m = m or 1.0
        stops = list(np.linspace(-m, m, len(DIVERGING)))
        rgb = _interp(stops, DIVERGING, np.where(finite, v, 0.0))
        lo, hi = -m, m
    else:
        lo = vmin if vmin is not None else (np.nanmin(v[finite]) if finite.any() else 0.0)
        hi = vmax if vmax is not None else (np.nanmax(v[finite]) if finite.any() else 1.0)
        if hi - lo < 1e-12:
            hi = lo + 1.0
        stops = list(np.linspace(lo, hi, len(SEQUENTIAL)))
        rgb = _interp(stops, SEQUENTIAL, np.where(finite, v, lo))
    hexes = ['#%02x%02x%02x' % tuple(int(round(c)) for c in row) for row in rgb]
    for i in np.nonzero(~finite)[0]:
        hexes[i] = '#bbbbbb'
    return hexes, lo, hi


def legend_stops(kind, lo, hi, n=6):
    """(value, hex) pairs for drawing a legend bar."""
    vals = np.linspace(lo, hi, n)
    hexes, _, _ = colours_for(vals, kind, lo, hi)
    return list(zip(vals, hexes))


def shade(hex_colour, factor):
    """Darken/lighten a hex colour by a lighting factor in [0.3, 1.2]."""
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    f = max(0.0, factor)
    return '#%02x%02x%02x' % tuple(min(255, int(c * f)) for c in (r, g, b))
