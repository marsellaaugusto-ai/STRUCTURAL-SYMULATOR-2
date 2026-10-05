"""
perforated_beam_views.py — the drawings the Perforated Beam tab never had.

Every other tab in this program shows you what you are designing; this one
reported numbers into a text box and nothing else. That is workable for a
catalog I-beam whose shape you already know, and useless the moment the
section is two hand-drawn profiles welded together, which is exactly when
you most need to see it.

FOUR VIEWS, each answering a question the report cannot:

  Section      what the cross-section actually is -- both profiles in
               position, holes, welds, the neutral axis, and the extreme
               fibre distances that produce S_top and S_bot.
  Elevation    where the openings, supports and loads fall along the span.
  Diagrams     V(x), M(x) and the deflected shape, with the governing
               values marked.
  Axonometric  how the arrangement reads in three dimensions -- which way
               the profiles face and where the openings line up.

All geometry comes from section_shapes.py, which is validated against each
section's own A and I. That is deliberate: a drawing that disagreed with
the computed properties would be worse than no drawing, so the two are
made to share a single source of geometry rather than being written twice.

SCALE. The elevation is drawn TRUE TO SCALE. It was exaggerated by
default at first, on the argument that a 28:1 beam is illegible drawn
honestly -- but stretching the depth turns circular openings into tall
ellipses, and a drawing that misreports the shape of the holes is worse
than one you have to zoom into. The wheel zooms. Exaggeration is still
available as a checkbox, and when it is on the drawing states the factor
and warns that the openings are no longer round.

SIGN CONVENTIONS in the diagrams follow drawing-office practice rather
than the sign of the stored number: shear positive up, but the bending
moment drawn on the TENSION side (sagging hangs below the axis) and
deflection drawn in the direction it actually moves (downward down).
Only the plotted geometry is flipped -- every printed value stays in the
module's own convention, so labels still agree with the report.
"""
import math
import tkinter as tk
from tkinter import ttk

from common import ZoomCanvas
from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import section_shapes as shapes

BG = '#f5f5f3'
PAPER = '#ffffff'
STEEL = '#c9d6e4'
STEEL_EDGE = '#1a3a5a'
HOLE_EDGE = '#b03030'
WELD = '#e08a00'
AXIS = '#9a9a95'
DIM = '#5a5a55'
LOAD = '#1a6bbd'
SUPPORT = '#2e7d32'
SHEAR = '#1a6bbd'
MOMENT = '#b03030'
DEFL = '#7a3fa0'
GRID = '#ececea'


def _m(mm, unit=' m'):
    """A SPAN-scale length in metres.

    Section dimensions stay in mm -- that is how plate and flange sizes
    are specified and how the section maths works. But a 50 400 mm span
    with supports at 16 200 mm is unreadable; those are metres to anyone
    reading a beam drawing, so spans, support positions and station
    locations are shown that way."""
    v = mm / 1000.0
    s = f'{v:.3f}'.rstrip('0').rstrip('.')
    return f'{s}{unit}'


def _fmt(v, unit=''):
    """Engineering-readable number: no exponent until it earns one.

    The obvious version of this -- divide by 1e6 and append 'e6' -- breaks
    the moment the quotient itself needs scientific notation, printing
    '2.13e+03e6' for a perfectly ordinary 2.13e9 N.mm. So the exponent is
    left to the format spec, which only ever emits one of them."""
    a = abs(v)
    if a == 0:
        return f'0{unit}'
    if a >= 1e7 or a < 1e-3:
        return f'{v:.4g}{unit}'          # 1.876e+09, never 1.88e+03e6
    if a >= 1000:
        return f'{v:,.0f}{unit}'
    return f'{v:.4g}{unit}'


class _View(tk.Frame):
    """Shared plumbing: a ZoomCanvas, a fit-to-content helper, and a world
    frame with y pointing UP (the canvas's own y points down, and every
    engineering drawing in this tab is drawn y-up)."""

    def __init__(self, master, **kw):
        super().__init__(master, bg=BG, **kw)
        self.zc = ZoomCanvas(self, bg=PAPER)
        self.zc.MIN_ZOOM = 1e-5          # a 50 m beam needs to zoom way out
        self.zc.pack(fill='both', expand=True)
        self.canvas = self.zc.canvas
        self.zc._on_zoom_changed = self.redraw
        self.canvas.bind('<Configure>', lambda e: self.redraw())
        self.beam = None
        self.report = None
        self._sy = 1.0                   # extra vertical scale (exaggeration)

    def set_model(self, beam, report):
        self.beam, self.report = beam, report
        self.fit()

    # world (y up, optional independent y scale) -> screen
    def w2s(self, wx, wy):
        return self.zc.w2s(wx, -wy * self._sy)

    def flat(self, pts):
        out = []
        for p in pts:
            out.extend(self.w2s(p[0], p[1]))
        return out

    def _fit_to(self, xmin, ymin, xmax, ymax, margin=54, sy=1.0):
        w = max(self.canvas.winfo_width(), 60)
        h = max(self.canvas.winfo_height(), 60)
        self._sy = sy
        span_x = max(xmax - xmin, 1e-6)
        span_y = max((ymax - ymin) * sy, 1e-6)
        z = min((w - 2 * margin) / span_x, (h - 2 * margin) / span_y)
        self.zc.zoom = max(self.zc.MIN_ZOOM, min(self.zc.MAX_ZOOM, z))
        cx = (xmin + xmax) / 2.0
        cy = (ymin + ymax) / 2.0 * sy
        self.zc.pan_x = w / (2 * self.zc.zoom) - cx
        self.zc.pan_y = h / (2 * self.zc.zoom) + cy
        self.redraw()

    def fit(self):
        self.redraw()

    def redraw(self, *_):
        self.canvas.delete('all')
        if self.beam is None:
            self.canvas.create_text(20, 20, anchor='nw', fill='#999',
                                    font=('Helvetica', 10),
                                    text='Run ▶ Analyze to draw this view.')
            return
        try:
            self.draw()
        except Exception as exc:               # a view must never break Analyze
            self.canvas.create_text(20, 20, anchor='nw', fill='#b03030',
                                    font=('Helvetica', 9),
                                    text=f'This view could not be drawn:\n{exc}')

    def draw(self):
        raise NotImplementedError

    # ── shared drawing helpers ──────────────────────────────────────────
    def note(self, lines, x=12, y=10, colour='#444'):
        self.canvas.create_text(x, y, anchor='nw', fill=colour, justify='left',
                                font=('Courier', 9), text='\n'.join(lines))

    def dim_line(self, x1, y1, x2, y2, label, offset=0):
        """A dimension line with ticks and a centred label."""
        c = self.canvas
        a = self.w2s(x1, y1)
        b = self.w2s(x2, y2)
        c.create_line(a[0], a[1] + offset, b[0], b[1] + offset, fill=DIM, arrow='both')
        c.create_text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + offset - 8,
                      text=label, fill=DIM, font=('Helvetica', 8))


# ─────────────────────────────────────────────────────────────────────────
# 1. Cross-section
# ─────────────────────────────────────────────────────────────────────────

class SectionView(_View):
    def fit(self):
        if self.beam is None:
            return self.redraw()
        pieces = shapes.section_pieces(self.beam.section)
        ext = shapes.section_extents(pieces)
        if ext is None:
            return self.redraw()
        pad = max(ext[2] - ext[0], ext[3] - ext[1]) * 0.18 + 10
        self._fit_to(ext[0] - pad, ext[1] - pad, ext[2] + pad, ext[3] + pad)

    def draw(self):
        c = self.canvas
        sec = self.beam.section
        pieces = shapes.section_pieces(sec)
        if not pieces:
            c.create_text(20, 20, anchor='nw', fill='#999', font=('Helvetica', 10),
                          text='No drawable geometry for this section type.')
            return
        ext = shapes.section_extents(pieces)

        # material, then holes punched back out in the paper colour (Tk
        # polygons have no hole support, so this is how a void is shown)
        for p in pieces:
            c.create_polygon(self.flat(p.outline), fill=STEEL,
                             outline=STEEL_EDGE, width=2)
        for p in pieces:
            for h in p.holes:
                c.create_polygon(self.flat(h), fill=PAPER, outline=HOLE_EDGE, width=1.5)

        # neutral axis and centroid: y = 0 by the frame contract
        x0, _ = self.w2s(ext[0], 0.0)
        x1, _ = self.w2s(ext[2], 0.0)
        _, y0 = self.w2s(0.0, 0.0)
        c.create_line(x0 - 44, y0, x1 + 8, y0, fill=AXIS, dash=(7, 4))
        # NA labelled on the LEFT: the right side carries the overall depth
        # dimension, and the two collided there.
        c.create_text(x0 - 48, y0, anchor='e', text='NA', fill=AXIS,
                      font=('Helvetica', 8, 'bold'))
        cxs, cys = self.w2s(0.0, 0.0)
        c.create_oval(cxs - 4, cys - 4, cxs + 4, cys + 4, outline=AXIS, width=2)

        # welds
        for p1, p2, label in shapes.section_welds(sec):
            a, b = self.w2s(*p1), self.w2s(*p2)
            c.create_line(a[0], a[1], b[0], b[1], fill=WELD, width=5)
            n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 11))
            dx, dy = (b[0] - a[0]) / n, (b[1] - a[1]) / n
            nx, ny = -dy, dx
            norm = math.hypot(nx, ny) or 1.0
            nx, ny = 5 * nx / norm, 5 * ny / norm
            for i in range(n):
                px, py = a[0] + dx * (i + .5), a[1] + dy * (i + .5)
                c.create_line(px, py, px + nx, py + ny, fill=WELD)
            if label:
                c.create_text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 12, text=label,
                              fill=WELD, font=('Helvetica', 8, 'bold'))

        # overall dimensions
        self.dim_line(ext[0], ext[1], ext[2], ext[1], f'{ext[2] - ext[0]:.0f} mm', offset=26)
        top = self.w2s(ext[2], ext[3])
        bot = self.w2s(ext[2], ext[1])
        c.create_line(top[0] + 26, top[1], bot[0] + 26, bot[1], fill=DIM, arrow='both')
        c.create_text(top[0] + 30, (top[1] + bot[1]) / 2, anchor='w',
                      text=f'{ext[3] - ext[1]:.0f} mm', fill=DIM, font=('Helvetica', 8))

        # extreme-fibre distances, which are what S_top / S_bot come from
        for y, name in ((ext[3], 'c_top'), (ext[1], 'c_bot')):
            fx, fy = self.w2s(ext[0], y)
            c.create_line(fx - 26, fy, fx, fy, fill=DIM)
            c.create_text(fx - 30, fy, anchor='e', fill=DIM, font=('Helvetica', 8),
                          text=f'{name}={abs(y):.0f}')

        lines = [f'{getattr(sec, "name", "section")}',
                 f'A      = {_fmt(sec.A)} mm2',
                 f'I      = {_fmt(sec.I)} mm4',
                 f'd      = {_fmt(sec.d)} mm']
        for attr, label in (('S_top', 'S_top'), ('S_bot', 'S_bot'), ('Iy', 'Iy')):
            try:
                lines.append(f'{label:6s} = {_fmt(getattr(sec, attr))}')
            except Exception:
                pass
        for attr in ('Aweb', 'J'):
            try:
                lines.append(f'{attr:6s} = {_fmt(getattr(sec, attr))}')
            except Exception:
                lines.append(f'{attr:6s} = not defined for this section')
        self.note(lines)


# ─────────────────────────────────────────────────────────────────────────
# 2. Elevation
# ─────────────────────────────────────────────────────────────────────────

class ElevationView(_View):
    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        bar = tk.Frame(self, bg=BG)
        bar.pack(side='top', fill='x', before=self.zc)
        # TRUE SCALE IS THE DEFAULT. It was the other way round at first,
        # on the argument that a 28:1 beam is illegible drawn honestly.
        # That was the wrong trade: the exaggeration turns circular
        # openings into tall ellipses, and a drawing that misreports the
        # shape of the holes is worse than one you have to zoom into. The
        # wheel zooms; the geometry should not lie by default.
        self.exaggerate = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text='Exaggerate depth for legibility',
                       variable=self.exaggerate, bg=BG, font=('Helvetica', 8),
                       command=self.fit).pack(side='left')
        self.scale_note = tk.Label(bar, text='', bg=BG, fg='#888', font=('Helvetica', 8))
        self.scale_note.pack(side='left', padx=8)

    def _exaggeration(self):
        """1.0 unless the user asks for stretching.

        When asked, the factor comes from the beam's own aspect ratio
        rather than being fixed: the target is a drawing about 6:1, which
        reads as a beam. It never squashes (>= 1), and stays 1.0 for a
        beam that is already stocky."""
        if not self.exaggerate.get():
            return 1.0
        d = max(self.beam.section.d, 1e-6)
        aspect = self.beam.L / d
        return max(1.0, aspect / 6.0)

    def fit(self):
        if self.beam is None:
            return self.redraw()
        d = self.beam.section.d
        sy = self._exaggeration()
        # Say what the exaggeration does to the openings as well as to the
        # beam: a circular hole is drawn as an ellipse under it, and
        # someone reading the shape off the picture should know that
        # before they conclude the holes are the wrong shape.
        note = ''
        if sy > 1.001:
            note = f'depth exaggerated ×{sy:.1f} for legibility'
            if self.beam.openings:
                note += ' — circular openings therefore appear elliptical'
        self.scale_note.configure(text=note)
        self._fit_to(-self.beam.L * 0.04, -d * 0.95,
                     self.beam.L * 1.04, d * 1.15, sy=sy)

    def draw(self):
        c = self.canvas
        beam = self.beam
        d = beam.section.d
        box, flanges = shapes.beam_profile_outline(beam)

        c.create_polygon(self.flat(box), fill=STEEL, outline=STEEL_EDGE, width=2)
        for fl in flanges:
            c.create_line(self.flat(fl), fill=STEEL_EDGE, width=1)

        for label, pts in shapes.opening_outlines(beam):
            c.create_polygon(self.flat(pts), fill=PAPER, outline=HOLE_EDGE, width=1.5)

        self._draw_supports()
        self._draw_loads()

        # span dimension
        self.dim_line(0.0, -d / 2.0, beam.L, -d / 2.0, f'L = {_m(beam.L)}', offset=52)
        n_op = len(beam.openings)
        lines = [f'L = {_m(beam.L)}, d = {_fmt(d)} mm',
                 f'{n_op} opening(s)' if n_op else 'no openings']
        if beam.support_specs:
            lines.append(f'{len(beam.support_specs)} supports, '
                         f'{len(beam.point_loads)} point load(s), '
                         f'{len(beam.dist_loads)} distributed')
        self.note(lines)

    def _draw_supports(self):
        c = self.canvas
        d = self.beam.section.d
        if self.beam.support_specs:
            marks = [(s.x, s.restrains_rotation) for s in self.beam.support_specs]
        else:
            xa, xb = self.beam.supports
            marks = [(xa, False), (xb, False)]
        for x, fixed in marks:
            sx, sy = self.w2s(x, -d / 2.0)
            if fixed:
                c.create_rectangle(sx - 7, sy, sx + 7, sy + 26, fill=SUPPORT, outline='')
                for i in range(5):
                    c.create_line(sx - 7, sy + 4 + i * 5, sx - 15, sy + 10 + i * 5,
                                  fill=SUPPORT)
            else:
                c.create_polygon(sx, sy, sx - 11, sy + 22, sx + 11, sy + 22,
                                 fill='', outline=SUPPORT, width=2)
                c.create_line(sx - 15, sy + 25, sx + 15, sy + 25, fill=SUPPORT, width=2)
            c.create_text(sx, sy + 40, text=_m(x), fill=SUPPORT,
                          font=('Helvetica', 8))

    def _draw_loads(self):
        c = self.canvas
        beam = self.beam
        d = beam.section.d
        top = d / 2.0
        for pl in beam.point_loads:
            sx, sy = self.w2s(pl.x, top)
            up = pl.P >= 0
            y0 = sy - 46 if up else sy - 6
            y1 = sy - 6 if up else sy - 46
            c.create_line(sx, y0, sx, y1, fill=LOAD, width=2, arrow='last')
            c.create_text(sx, y0 - 9, text=f'{abs(pl.P) / 1000:.0f} kN',
                          fill=LOAD, font=('Helvetica', 8))
        for dl in beam.dist_loads:
            n = 14
            xs = [dl.x1 + (dl.x2 - dl.x1) * i / n for i in range(n + 1)]
            band = []
            for x in xs:
                t = 0.0 if dl.x2 == dl.x1 else (x - dl.x1) / (dl.x2 - dl.x1)
                w = dl.w1 + (dl.w2 - dl.w1) * t
                sx, sy = self.w2s(x, top)
                h = 14 + 16 * (abs(w) / max(abs(dl.w1), abs(dl.w2), 1e-9))
                band.append((sx, sy - 6 - h))
                c.create_line(sx, sy - 6 - h, sx, sy - 8, fill=LOAD, arrow='last')
            c.create_line([v for pt in band for v in pt], fill=LOAD, width=1)
            mx = (dl.x1 + dl.x2) / 2.0
            sx, sy = self.w2s(mx, top)
            txt = (f'{dl.w1:g} N/mm' if dl.w1 == dl.w2
                   else f'{dl.w1:g}→{dl.w2:g} N/mm')
            c.create_text(sx, sy - 52, text=txt, fill=LOAD, font=('Helvetica', 8))


# ─────────────────────────────────────────────────────────────────────────
# 3. V / M / deflection
# ─────────────────────────────────────────────────────────────────────────

# (row title, flip) in drawing order. `flip` negates only what is PLOTTED;
# every printed value stays in the module's own sign convention.
#
#   Shear      positive UP -- the usual convention.
#   Moment     SAGGING DOWN. A bending-moment diagram is drawn on the
#              TENSION side, so a sagging span hangs below the axis and a
#              hogging support peak rises above it. Plotting +M upward,
#              which is what this did at first, puts the diagram upside
#              down against every textbook and drawing office.
#   Deflection DOWNWARD DOWN. The values are already +down; drawing them
#              upward made a sagging beam arch over its supports.
DIAGRAM_ROWS = (
    ('Shear V (N)', False),
    ('Moment M (N·mm) — sagging drawn downward', True),
    ('Deflection (mm) — downward drawn downward', True),
)


class DiagramView(_View):
    N = 321

    def fit(self):
        self.redraw()

    def draw(self):
        c = self.canvas
        beam = self.beam
        w = max(self.canvas.winfo_width(), 200)
        h = max(self.canvas.winfo_height(), 200)
        margin_l, margin_r = 82, 26
        plot_w = w - margin_l - margin_r
        rows = 3
        row_h = (h - 40) / rows

        xs = [beam.L * i / (self.N - 1) for i in range(self.N)]
        V, M = [], []
        for x in xs:
            v, m = pbm.global_V_M(beam, x)
            V.append(v)
            M.append(m)
        _, defl = pbm.deflection_profile(beam, n=self.N)

        # Sign conventions, drawn the way a beam drawing is read:
        #
        #   Shear      positive UP -- the usual convention, unchanged.
        #   Moment     SAGGING DOWN. A bending-moment diagram is drawn on
        #              the TENSION side of the member, so a sagging span
        #              hangs below the axis and a hogging support peak
        #              rises above it. Plotting +M upward, as this did at
        #              first, puts every diagram upside down against every
        #              textbook and drawing office.
        #   Deflection DOWNWARD DOWN. The values are already +down; drawing
        #              them upward made a sagging beam arch over its
        #              supports, which is simply the wrong picture.
        #
        # `flip` negates only what is PLOTTED. Every printed number stays
        # in the module's own sign convention, so the labels still agree
        # with the report and with global_V_M.
        for row, ((title, flip), ys, colour) in enumerate(
                zip(DIAGRAM_ROWS, (V, M, defl), (SHEAR, MOMENT, DEFL))):
            y_top = 22 + row * row_h
            self._plot(title, xs, ys, colour, margin_l, y_top, plot_w, row_h - 24, flip)

    def _plot(self, title, xs, ys, colour, x0, y0, pw, ph, flip=False):
        c = self.canvas
        sign = -1.0 if flip else 1.0
        plot_ys = [sign * v for v in ys]
        lo, hi = min(plot_ys), max(plot_ys)
        if abs(hi - lo) < 1e-12:
            lo, hi = lo - 1.0, hi + 1.0
        pad = (hi - lo) * 0.12
        lo, hi = lo - pad, hi + pad
        L = xs[-1] or 1.0

        def px(x):
            return x0 + pw * x / L

        def py(v):
            """v is a TRUE value; the flip is applied here so callers never
            have to remember which space they are in."""
            return y0 + ph * (hi - sign * v) / (hi - lo)

        c.create_rectangle(x0, y0, x0 + pw, y0 + ph, outline=GRID, fill=PAPER)
        c.create_text(x0, y0 - 12, anchor='w', text=title, fill='#444',
                      font=('Helvetica', 9, 'bold'))
        # zero line
        if lo < 0 < hi:
            zy = py(0.0)
            c.create_line(x0, zy, x0 + pw, zy, fill=AXIS, dash=(4, 3))
        # the curve, filled to zero so the sign reads at a glance
        pts = []
        for x, v in zip(xs, ys):
            pts.extend((px(x), py(v)))
        base = min(max(py(0.0), y0), y0 + ph)      # clamped in SCREEN space
        c.create_polygon([x0, base] + pts + [x0 + pw, base],
                         fill=colour, outline='', stipple='gray25')
        c.create_line(pts, fill=colour, width=2)
        # Extremes. Label placement follows where the point ACTUALLY sits
        # on screen, not the sign of its value -- under a flip the largest
        # value is drawn lowest, and keying off the sign would write the
        # label straight through the curve.
        for val in (max(ys), min(ys)):
            i = ys.index(val)
            mx, my = px(xs[i]), py(val)
            above = my < y0 + ph / 2.0
            dy, anchor = (-11, 's') if above else (11, 'n')
            c.create_oval(mx - 3, my - 3, mx + 3, my + 3, fill=colour, outline='')
            # An extreme at the very end of the span would otherwise write
            # its label off the edge of the pane -- which is exactly where
            # an overhang's peak deflection lands.
            c.create_text(min(max(mx, x0 + 58), x0 + pw - 58), my + dy,
                          anchor=anchor, text=f'{_fmt(val)} @ {_m(xs[i])}',
                          fill=colour, font=('Helvetica', 8))
        # Axis end labels are TRUE values: the top of the box is plot-space
        # `hi`, which under a flip is the most negative real value.
        c.create_text(x0 - 6, y0, anchor='e', text=_fmt(sign * hi), fill='#777',
                      font=('Helvetica', 7))
        c.create_text(x0 - 6, y0 + ph, anchor='e', text=_fmt(sign * lo), fill='#777',
                      font=('Helvetica', 7))
        # supports along the axis
        marks = ([s.x for s in self.beam.support_specs] if self.beam.support_specs
                 else list(self.beam.supports))
        for sx in marks:
            c.create_line(px(sx), y0 + ph, px(sx), y0 + ph + 6, fill=SUPPORT, width=2)


# ─────────────────────────────────────────────────────────────────────────
# 4. Axonometric
# ─────────────────────────────────────────────────────────────────────────

class AxonometricView(_View):
    """The beam in 3-D, with hidden edges dashed.

    Three things were wrong with this view and all three were reported as
    "out of proportion and I can't tell depth":

    1. The cross-section was ENLARGED against the span -- x3.5 on the
       50.4 m box girder -- so the drawing showed a beam that does not
       exist. True scale is now the default, with the enlargement offered
       as a checkbox that states its factor, matching the Elevation.

    2. Nothing was hidden. Every edge was drawn solid whether it was at
       the front of the section or behind 500 mm of steel, so a two-web
       box read as a single plate. Edges now go through back-face culling
       AND an occlusion test (`section_shapes.occluded_in_section`), and
       what is behind material is drawn DASHED -- the drafting convention,
       and the thing that actually conveys depth.

    3. The END FACES were painted in the wrong order. With this
       projection the visible end is the one at x = L (its outward normal
       faces the viewer); x = 0 points away. The old code drew the far end
       first and then painted the HIDDEN end opaquely on top of it.

    Openings are also drawn on EVERY web plane rather than just the front
    one, since a box has two and seeing both is most of the depth cue.
    """

    HIDDEN = '#9fb3c8'
    DASH = (5, 4)

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        bar = tk.Frame(self, bg=BG)
        bar.pack(side='top', fill='x', before=self.zc)
        for text, cmd in (('Fit', self.fit),
                          ('\u2212', lambda: self._zoom_by(1 / 1.25)),
                          ('+', lambda: self._zoom_by(1.25))):
            tk.Button(bar, text=text, relief='flat', bd=0, padx=8,
                      font=('Helvetica', 9), command=cmd).pack(side='left', padx=1)
        tk.Label(bar, text='(the wheel zooms too, middle-drag pans)', bg=BG,
                 fg='#888', font=('Helvetica', 8)).pack(side='left', padx=6)
        self.exaggerate = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text='Enlarge cross-section against the span',
                       variable=self.exaggerate, bg=BG, font=('Helvetica', 8),
                       command=self.fit).pack(side='left', padx=6)
        self.scale_note = tk.Label(bar, text='', bg=BG, fg='#888',
                                   font=('Helvetica', 8))
        self.scale_note.pack(side='left', padx=6)

    def _zoom_by(self, factor):
        self.zc.zoom = max(self.zc.MIN_ZOOM, min(self.zc.MAX_ZOOM,
                                                 self.zc.zoom * factor))
        self.redraw()

    def _section_scale(self):
        """1.0 -- TRUE SCALE -- unless the user asks otherwise.

        It used to return (L/8)/d unconditionally, which drew the box
        girder's section 3.5x too deep. A 28:1 beam is admittedly a stick
        at true scale, but the answer to that is the zoom, not a drawing
        that misreports the proportions of the thing being designed."""
        if not self.exaggerate.get() or self.beam is None:
            return 1.0
        pieces = shapes.section_pieces(self.beam.section)
        ext = shapes.section_extents(pieces)
        if ext is None:
            return 1.0
        d = max(ext[3] - ext[1], 1e-6)
        return max(1.0, (self.beam.L / 8.0) / d)

    def fit(self):
        if self.beam is None:
            return self.redraw()
        pieces = shapes.section_pieces(self.beam.section)
        ext = shapes.section_extents(pieces)
        if ext is None:
            return self.redraw()
        k = self._section_scale()
        L = self.beam.L
        corners = [shapes.isometric(x, y * k, z * k)
                   for x in (0.0, L) for y in (ext[1], ext[3])
                   for z in (0.0, ext[2] - ext[0])]
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        pad = L * 0.06
        self._fit_to(min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)

    # ── geometry helpers ────────────────────────────────────────────────
    @staticmethod
    def _edge_faces_viewer(z1, y1, z2, y2, inside_z, inside_y):
        """Does the face swept by this section edge point at the viewer?

        The outward normal is whichever of the edge's two perpendiculars
        points AWAY from the section's interior, so the winding of the
        outline does not have to be known. Toward the viewer is
        (-1, +0.25) in the section's own (z, y) plane -- see
        `section_shapes.VIEW_TOWARD_Z`."""
        dz, dy = z2 - z1, y2 - y1
        nz, ny = dy, -dz
        mz, my = 0.5 * (z1 + z2), 0.5 * (y1 + y2)
        if nz * (inside_z - mz) + ny * (inside_y - my) > 0:
            nz, ny = -nz, -ny              # it pointed inward; flip it
        return (nz * shapes.VIEW_TOWARD_Z + ny * shapes.VIEW_TOWARD_Y) > 0

    def draw(self):
        c = self.canvas
        beam = self.beam
        pieces = shapes.section_pieces(beam.section)
        if not pieces:
            c.create_text(20, 20, anchor='nw', fill='#999', font=('Helvetica', 10),
                          text='No drawable geometry for this section type.')
            return
        ext = shapes.section_extents(pieces)
        sc = self._section_scale()
        L = beam.L
        z0 = ext[0]
        cz = 0.5 * (ext[0] + ext[2])
        cy = 0.5 * (ext[1] + ext[3])

        def proj(x, y, z):
            return shapes.isometric(x, y * sc, z * sc)

        # 1. FILLS first, so the dashed hidden lines drawn later sit on top
        #    of them -- which is what a drafting drawing does, and what
        #    makes the far web readable rather than merely absent.
        for p in pieces:
            n = len(p.outline)
            for i in range(n):
                zi, yi = p.outline[i]
                zj, yj = p.outline[(i + 1) % n]
                if not self._edge_faces_viewer(zi, yi, zj, yj, cz, cy):
                    continue
                if shapes.occluded_in_section(pieces, 0.5 * (zi + zj), 0.5 * (yi + yj)):
                    continue
                quad = [proj(0.0, yi, zi - z0), proj(L, yi, zi - z0),
                        proj(L, yj, zj - z0), proj(0.0, yj, zj - z0)]
                c.create_polygon(self.flat(quad), fill=STEEL, outline='')

        # 2. the far END FACE (x = 0) is the HIDDEN one: with this
        #    projection the visible end is x = L, whose outward normal
        #    faces the viewer. Dashed outline, no fill.
        for p in pieces:
            pts = [proj(0.0, y, zx - z0) for (zx, y) in p.outline]
            c.create_polygon(self.flat(pts), fill='', outline=self.HIDDEN,
                             width=1, dash=self.DASH)

        # 3. longitudinal edges, classified
        for p in pieces:
            for (zx, y) in p.outline:
                a = proj(0.0, y, zx - z0)
                b = proj(L, y, zx - z0)
                if shapes.occluded_in_section(pieces, zx, y):
                    c.create_line(self.flat([a, b]), fill=self.HIDDEN,
                                  width=1, dash=self.DASH)
                else:
                    c.create_line(self.flat([a, b]), fill=STEEL_EDGE, width=1)

        # 4. openings, on EVERY web plane. The nearest is solid; the ones
        #    behind it are dashed, which is the whole depth cue for a box.
        planes = shapes.web_planes(beam.section) or [z0]
        outlines = shapes.opening_outlines(beam)
        for k, zplane in enumerate(planes):
            hidden = k > 0 or shapes.occluded_in_section(pieces, zplane + 1e-6, cy)
            for _label, pts in outlines:
                pp = [proj(x, y, zplane - z0) for (x, y) in pts]
                if hidden:
                    c.create_line(self.flat(pp + [pp[0]]), fill=self.HIDDEN,
                                  width=1, dash=self.DASH)
                else:
                    c.create_polygon(self.flat(pp), fill=PAPER,
                                     outline=HOLE_EDGE, width=1.2)

        # 5. the visible END FACE (x = L), on top of everything
        for p in pieces:
            pts = [proj(L, y, zx - z0) for (zx, y) in p.outline]
            c.create_polygon(self.flat(pts), fill='#e6ecf3',
                             outline=STEEL_EDGE, width=1.5)

        marks = ([(sp.x, sp.restrains_rotation) for sp in beam.support_specs]
                 if beam.support_specs else [(beam.supports[0], False),
                                             (beam.supports[1], False)])
        for x, _fixed in marks:
            a = proj(x, ext[1], 0.0)
            sx, sy = self.w2s(*a)
            c.create_polygon(sx, sy, sx - 10, sy + 20, sx + 10, sy + 20,
                             fill='', outline=SUPPORT, width=2)
            c.create_text(sx, sy + 30, text=_m(x), fill=SUPPORT,
                          font=('Helvetica', 8))

        self.scale_note.configure(
            text=(f'cross-section x{sc:.1f} against the span' if sc > 1.01
                  else 'true scale'))
        self.note([f'{getattr(beam.section, "name", "section")}',
                   f'span {_m(L)}, depth {_fmt(ext[3] - ext[1])} mm, '
                   f'width {_fmt(ext[2] - ext[0])} mm',
                   f'{len(planes)} web plane(s); dashed = behind material',
                   (f'cross-section drawn x{sc:.1f} against the span '
                    '(its own proportions are true)') if sc > 1.01 else
                   'true proportions'])


# ─────────────────────────────────────────────────────────────────────────
# The pane the app embeds
# ─────────────────────────────────────────────────────────────────────────

class BeamViewsPane(ttk.Notebook):
    """Report plus the four drawings, as tabs.

    The report stays tab 0 so nothing about the existing workflow moves;
    the drawings are added beside it rather than in place of it."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.report_frame = tk.Frame(self, bg=BG)
        self.add(self.report_frame, text='Report')

        self.section_view = SectionView(self)
        self.elevation_view = ElevationView(self)
        self.diagram_view = DiagramView(self)
        self.axon_view = AxonometricView(self)
        self.add(self.section_view, text='Section')
        self.add(self.elevation_view, text='Elevation')
        self.add(self.diagram_view, text='Diagrams')
        self.add(self.axon_view, text='3D')
        self.bind('<<NotebookTabChanged>>', self._on_tab)

    @property
    def views(self):
        return (self.section_view, self.elevation_view,
                self.diagram_view, self.axon_view)

    def set_model(self, beam, report):
        for v in self.views:
            v.set_model(beam, report)

    def _on_tab(self, _event=None):
        """Fit on first show: a view laid out while its tab was hidden has
        a 1x1 canvas and nothing sensible to fit to."""
        try:
            current = self.nametowidget(self.select())
        except Exception:
            return
        if isinstance(current, _View) and current.beam is not None:
            current.after(20, current.fit)
