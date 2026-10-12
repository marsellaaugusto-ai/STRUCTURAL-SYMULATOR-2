"""The Truss tab's PDF report: the sheets an engineer hands in.

  1. cover    -- the model, its sections and loads, the verdict, contents
  2. geometry -- nodes and rods, numbered, with overall and bay dimensions
  3. forces   -- the axial force in every rod: colour, width and number
  4. deformed -- the deflected shape against the span/300 limit
  5. reactions-- the support reactions, drawn and tabulated
  6. rods     -- every rod: section, length, force, governing check, use
  7. explain  -- the CIRSOC 301 check of the most used rods, step by step

A4 landscape, in the frame and title block of the Stereo report
(apps/stereo/stereo_reports), so both tabs hand in the same kind of sheet.
Every drawing is to scale -- equal aspect, so a metre across is a metre up
-- with a graphic scale bar; the deformed shape alone is magnified, and
says by how much. Numbers are written in the app's selected units
(ReportUnits). Needs matplotlib.
"""
import math
import time

from common import PX_PER_M, CT, CC, CZ
from . import truss_design as td
from . import truss_score as ts

INK = '#333333'
GHOST = '#c2c8cd'
SUPPORT = '#555555'
LOAD = '#222222'
REACTION = '#1e8f4e'
ROWS_PER_SHEET = 26
EXPLAIN_RODS = 2
#: Lines of a step-by-step check that fit one column of an Explain sheet
#: above the title block. Measured, not guessed: 6.0 pt monospace from
#: y 0.790 down to y 0.175 on an A4 landscape sheet.
EXPLAIN_LINES = 49
APP_NAME = 'Truss'


def _xy(p):
    """Canvas pixels (y down) -> metres (y up)."""
    return p[0] / PX_PER_M, -p[1] / PX_PER_M


class _Report:

    def __init__(self, nodes, rods, supports, loads, results, checks,
                 profiles, title, units, diagrams=None, plates=None,
                 plate_checks=None, stability=None, deform_scale=None):
        from apps.stereo.stereo_reports import ReportUnits
        self.nodes, self.rods = nodes, rods
        self.supports, self.loads = supports, loads
        self.res, self.checks = results, checks or []
        self.profiles, self.title = profiles or {}, title
        self.u = units or ReportUnits()
        self.diagrams = diagrams or []
        self.plates = plates or []
        self.plate_checks = plate_checks or []
        self.stability = stability
        self.deform_scale = deform_scale
        self.pts = [_xy(p) for p in nodes]
        xs = [p[0] for p in self.pts]
        ys = [p[1] for p in self.pts]
        self.box = (min(xs), max(xs), min(ys), max(ys))
        self.span = max(self.box[1] - self.box[0], self.box[3] - self.box[2],
                        1e-9)
        self.defl = td.deflection(nodes, supports, results['node_res'])
        self.score = ts.score(nodes, rods, results, self.checks)
        #: Filled in by `buckling()`; the cover reads it, so the sheets
        #: are built in an order that puts the cover last and renumbers
        #: nothing (`new_sheet` appends, `cover` inserts at 0).
        self.buckling_factors = []
        self.flex_points = []
        self.sheets = []

    # ── does anything bend? ───────────────────────────────────────────────
    def bends(self):
        """True when any rod carries shear or moment.

        THE REASON THIS EXISTS. A classic truss -- every rod pinned, every
        load at a joint -- has NO shear and NO moment anywhere: the axial
        force is the whole result, which is the single most important
        thing the tab teaches. Printing a Shear sheet, a Moment sheet and
        a per-rod V/M card for such a model is three or four pages of
        flat zero lines that say nothing and bury the pages that do.
        Those sheets are skipped, and the cover says why instead.
        """
        if getattr(self, '_bends', None) is None:
            self._bends = any(
                max((abs(v) for v in list(d.get('V', ())) +
                     list(d.get('M', ()))), default=0.0) > 1e-9
                for d in self.diagrams)
        return self._bends

    def _peak(self, key):
        return max((max((abs(v) for v in d.get(key, ())), default=0.0)
                    for d in self.diagrams), default=0.0)

    # ── sheet furniture ───────────────────────────────────────────────────
    def meta(self):
        return [('MODEL', (self.title or 'user model')[:22]),
                ('SIZE', '%d nodes / %d rods' % (len(self.nodes),
                                                  len(self.rods))),
                ('UNITS', self.u.title_block()),
                ('CODE', 'CIRSOC 301'),
                ('DATE', time.strftime('%Y-%m-%d %H:%M'))]

    def new_sheet(self, heading):
        # A bare Figure, never pyplot: inside the running Tk app pyplot's
        # backend could open a window of its own for every sheet.
        from matplotlib.figure import Figure
        from apps.stereo import stereo_reports as sr
        fig = Figure(figsize=sr.PDF_SHEET_IN)
        self.sheets.append((fig, heading))
        return fig

    def drawing_axes(self, fig, rect=(0.05, 0.19, 0.90, 0.74), pad=0.24):
        """Axes for a to-scale drawing of the truss, with room around it
        for the dimension lines, the load and reaction arrows (each at most
        0.14 and 0.12 of the span long) and, below them all, the scale
        bar."""
        ax = fig.add_axes(rect)
        x0, x1, y0, y1 = self.box
        m = pad * self.span
        ax.set_xlim(x0 - m, x1 + m)
        ax.set_ylim(y0 - m, y1 + m)
        # A metre across is a metre up: the axes box shrinks to fit.
        ax.set_aspect('equal', adjustable='box')
        ax.axis('off')
        return ax

    def scale_bar(self, ax):
        from apps.stereo import stereo_reports as sr
        x0, x1, y0, y1 = ax.get_xlim() + ax.get_ylim()
        sr._pdf_scale_bar(ax, self.span,
                          (x0 + 0.02 * (x1 - x0), y0 + 0.02 * (y1 - y0)),
                          u=self.u)

    def frame(self):
        from apps.stereo import stereo_reports as sr
        n = len(self.sheets)
        for i, (fig, heading) in enumerate(self.sheets):
            sr._pdf_sheet(fig, i + 1, n, '%s — %s' % (APP_NAME, heading),
                          self.meta())

    # ── the drawing primitives ────────────────────────────────────────────
    def draw_rods(self, ax, color=None, width=1.6, pts=None, numbers=False):
        pts = pts or self.pts
        for i, r in enumerate(self.rods):
            (ax_, ay), (bx, by) = pts[r['a']], pts[r['b']]
            c = color(i) if callable(color) else (color or INK)
            w = width(i) if callable(width) else width
            ax.plot([ax_, bx], [ay, by], color=c, lw=w,
                    solid_capstyle='round', zorder=3)
            if numbers:
                ax.text((ax_ + bx) / 2, (ay + by) / 2, str(i), fontsize=6.5,
                        color='#1a5fa8', ha='center', va='center', zorder=6,
                        bbox=dict(boxstyle='round,pad=0.12', fc='white',
                                  ec='none', alpha=0.85))

    def draw_nodes(self, ax, numbers=False):
        for i, (x, y) in enumerate(self.pts):
            ax.plot([x], [y], 'o', ms=3.2, color=INK, zorder=5)
            if numbers:
                ax.annotate(str(i), (x, y), xytext=(4, 4),
                            textcoords='offset points', fontsize=6.5,
                            color='#7a2e8e', zorder=6)

    def draw_supports(self, ax):
        s = 0.025 * self.span
        for sp in self.supports:
            x, y = self.pts[sp['node']]
            if sp['type'] == 'fixed':
                ax.add_patch(_rect(x - s, y - 0.6 * s, 2 * s, 0.6 * s))
            else:
                ax.fill([x, x - s, x + s], [y, y - 1.6 * s, y - 1.6 * s],
                        color=SUPPORT, zorder=4)
                if sp['type'].startswith('roller'):
                    ax.plot([x - s, x + s], [y - 2.0 * s, y - 2.0 * s],
                            color=SUPPORT, lw=1.2, zorder=4)

    def draw_loads(self, ax, label=True):
        if not self.loads:
            return
        big = max(math.hypot(l['fx'], l['fy']) for l in self.loads) or 1.0
        for ld in self.loads:
            x, y = self.pts[ld['node']]
            fx, fy = ld['fx'], -ld['fy']           # metres frame: y up
            m = math.hypot(fx, fy)
            if m < 1e-9:
                continue
            L = 0.10 * self.span * (0.5 + 0.5 * m / big)
            ux, uy = fx / m, fy / m
            ax.annotate('', xy=(x, y), xytext=(x - L * ux, y - L * uy),
                        arrowprops=dict(arrowstyle='-|>', color=LOAD,
                                        lw=1.2), zorder=7)
            if label:
                ax.text(x - L * ux, y - L * uy, ' %s %s'
                        % (self.u.f('force', m, 1), self.u.lab('force')),
                        fontsize=6.5, color=LOAD, va='bottom', zorder=7)

    # ── shear and moment, as silhouettes along the members ────────────────
    def normal(self, ri):
        """The member's local +v direction, in THIS SHEET'S y-up frame.

        The tab defines +v as (-dy/L, dx/L) on its y-DOWN canvas: for a
        rod drawn left to right that points DOWN, and it is the side a
        positive (sagging) moment puts in tension -- so the screen draws
        the moment diagram on the TENSION face, the usual convention in
        Argentina.

        The same formula applied to this sheet's y-UP points points the
        OTHER way. t 06 and t 07 did exactly that, with a docstring
        claiming it matched the screen: every lobe on the Shear and
        Moment sheets sat on the opposite face of its member to the
        tab's. Flipping y flips the normal, so here it is
        ((yb - ya)/L, -(xb - xa)/L). `test_a_sagging_moment_is_drawn_on_
        the_tension_face` pins it.
        """
        rod = self.rods[ri]
        (xa, ya), (xb, yb) = self.pts[rod['a']], self.pts[rod['b']]
        L = math.hypot(xb - xa, yb - ya) or 1.0
        return (yb - ya) / L, -(xb - xa) / L

    def draw_band(self, ax, ri, values, xs, amp, face, edge, lw=0.8):
        """One rod's V or M, drawn as a filled band off the member.

        The offset is along `normal(ri)`, the member's local +v side as
        the tab defines it, so a positive lobe lands on the same face of
        the member on paper as on screen: a sagging moment below a
        horizontal rod, on the face it puts in tension.

        The band is SPLIT at every sign change, so a lobe that crosses
        zero draws as two polygons meeting on the member rather than one
        bow-tie across it.
        """
        rod = self.rods[ri]
        (xa, ya), (xb, yb) = self.pts[rod['a']], self.pts[rod['b']]
        nx, ny = self.normal(ri)
        span = xs[-1] if xs and xs[-1] > 1e-12 else 1.0
        samples = [(x / span, v) for x, v in zip(xs, values)]
        if len(samples) < 2:
            return
        segs, cur = [], [samples[0]]
        for i in range(1, len(samples)):
            f0, v0 = samples[i - 1]
            f1, v1 = samples[i]
            if v0 * v1 < 0:
                fc = f0 + (f1 - f0) * (-v0) / (v1 - v0)
                cur.append((fc, 0.0))
                segs.append(cur)
                cur = [(fc, 0.0)]
            cur.append((f1, v1))
        segs.append(cur)
        from matplotlib.patches import Polygon
        for seg in segs:
            if len(seg) < 2:
                continue
            base = [(xa + (xb - xa) * f, ya + (yb - ya) * f) for f, _ in seg]
            off = [(px + nx * v * amp, py + ny * v * amp)
                   for (px, py), (_, v) in zip(base, seg)]
            ax.add_patch(Polygon(base + off[::-1], closed=True,
                                 facecolor=face, edgecolor=edge,
                                 linewidth=lw, alpha=0.85, zorder=4))

    def band_reach(self):
        """How far off its member the biggest V or M lobe reaches, metres.

        MATCHED TO THE SCREEN, MEASURED. The tab's Vierendeel view puts
        its biggest lobe at 0.16 of the smaller canvas dimension, which
        on the Vierendeel example comes to 5.1 % of the truss's width at
        1366x768 and 3.6 % at 1920x1080 -- 14-20 % of one bay. The first
        version of this sheet used 10 % of the span, two to three times
        that, and on a Vierendeel, where every bay bends, the lobes of
        neighbouring members reached into each other.

        Two limits, and the smaller one wins:

          * 4 % of the span -- the middle of what the screen draws, for
            a truss of a few long members;
          * 20 % of the MEDIAN member length -- for a truss of many short
            ones, where 4.5 % of a long span would still be wider than a
            bay and the lobes would overlap again.

        The median and not the shortest member: one short stub (a
        vertical at a support, say) would otherwise shrink every lobe in
        the drawing to nothing.
        """
        lens = sorted(td.rod_length_m(self.nodes, r) for r in self.rods)
        median = lens[len(lens) // 2] if lens else self.span
        return min(0.040 * self.span, 0.20 * median)

    def _action_sheet(self, heading, key, face, edge, unit, what):
        """The Shear sheet and the Moment sheet, which are the same sheet
        twice over different data.

        TWO SHEETS AND NOT ONE. The tab draws them side by side, which
        halves the width each gets; on a 30-bay truss that is the
        difference between reading a lobe and guessing at it. On paper
        there is no reason to pay that: each gets the whole sheet.
        """
        fig = self.new_sheet(heading)
        # pad 0.10, not the 0.24 the other drawings use: that margin is for
        # dimension lines and load arrows, neither of which is on this
        # sheet, and a lobe now reaches at most 4.5 % of the span. With the
        # wide margin a long truss came out a narrow strip across the
        # middle of the sheet; this way it uses the width, and the lobes
        # keep the screen's proportion to it.
        ax = self.drawing_axes(fig, pad=0.10)
        # A strip more at the bottom for the scale bar, which with the
        # tighter margin otherwise sat under the labels of the bottom
        # chord's lobes.
        lo, hi = ax.get_ylim()
        ax.set_ylim(lo - 0.10 * self.span, hi)
        self.draw_rods(ax, color=GHOST, width=1.2)
        self.draw_nodes(ax)
        self.draw_supports(ax)
        peak = self._peak(key)
        amp = (self.band_reach() / peak) if peak > 1e-12 else 0.0
        hits = []
        for ri, d in enumerate(self.diagrams):
            vals, xs = list(d.get(key, ())), list(d.get('xs', ()))
            if len(vals) < 2 or max((abs(v) for v in vals), default=0.0) <= 1e-9:
                continue
            self.draw_band(ax, ri, vals, xs, amp, face, edge)
            j = max(range(len(vals)), key=lambda k: abs(vals[k]))
            frac = xs[j] / xs[-1] if xs and xs[-1] > 1e-12 else 0.5
            # A value that does not change along the rod -- the shear of
            # a rod with no load on its span -- has no peak to point at:
            # "the first station" is the joint, where the label landed in
            # the next member's band. Mid-length says the same number and
            # says unambiguously which rod it belongs to.
            if max(vals) - min(vals) <= 0.05 * abs(vals[j]):
                frac = 0.5
            hits.append((abs(vals[j]), ri, vals[j], frac))
        hits.sort(reverse=True)
        for _a, ri, v, frac in hits[:6]:
            # AT THE PEAK, just past the tip of the lobe -- as the tab
            # writes them. At the member's midpoint, which is where a
            # Vierendeel member's moment crosses ZERO, the label sat on
            # the one point of the rod with nothing to report, and on a
            # vertical it was hard to tell which member it belonged to.
            rod = self.rods[ri]
            (xa, ya), (xb, yb) = self.pts[rod['a']], self.pts[rod['b']]
            nx, ny = self.normal(ri)
            px, py = xa + (xb - xa) * frac, ya + (yb - ya) * frac
            out = v * amp + math.copysign(0.03 * self.span, v)
            ax.text(px + nx * out, py + ny * out,
                    '%d: %s' % (ri, self.u.f(unit, v, 2, sign=True)),
                    fontsize=6.4, color=edge, ha='center', va='center',
                    zorder=8, bbox=dict(boxstyle='round,pad=0.12', fc='white',
                                        ec='none', alpha=0.9))
        self.scale_bar(ax)
        if hits:
            line = ('%s. Biggest %s %s in rod %d; the band is drawn off each '
                    'member, proportional to the value, and labelled on the '
                    'six largest.'
                    % (what, self.u.f(unit, hits[0][2], 2, sign=True),
                       self.u.lab(unit), hits[0][1]))
        else:
            line = '%s. Every rod reads zero.' % what
        fig.text(0.05, 0.945, _wrap(line, 160), fontsize=8, color=INK,
                 va='top')
        return [ri for _a, ri, _v, _f in hits]

    def shear(self):
        return self._action_sheet(
            'Shear V', 'V', '#e8a49c', '#c0392b', 'force',
            'Shear force V along every rigid rod')

    def moment(self):
        return self._action_sheet(
            'Moment M', 'M', '#9fc0e0', '#2c5f9e', 'moment',
            'Bending moment M along every rigid rod, drawn on the face it '
            'puts in TENSION, as on screen (sagging positive: below a '
            'horizontal rod)')

    # ── the sheets ────────────────────────────────────────────────────────
    def cover(self, contents):
        fig = self.new_sheet('Cover')
        y = 0.90
        fig.text(0.06, y, self.title or 'Truss', fontsize=20,
                 fontweight='bold', color='#1a1a1a')
        y -= 0.05
        fig.text(0.06, y, 'Plane truss — analysis and CIRSOC 301 rod '
                 'checks', fontsize=11, color=INK)
        x0, x1, y0, y1 = self.box
        rows = [('Span', '%s %s' % (self.u.f('length', x1 - x0, 2),
                                    self.u.lab('length'))),
                ('Height', '%s %s' % (self.u.f('length', y1 - y0, 2),
                                      self.u.lab('length'))),
                ('Nodes / rods', '%d / %d' % (len(self.nodes),
                                              len(self.rods))),
                ('Supports', ', '.join('%s at %d' % (s['type'], s['node'])
                                       for s in self.supports)),
                ('Loads', '%d nodal, total %s %s' % (
                    len(self.loads),
                    self.u.f('force', sum(math.hypot(l['fx'], l['fy'])
                                          for l in self.loads), 1),
                    self.u.lab('force')))]
        fams = sorted({r.get('profile', 'Default') for r in self.rods})
        for f in fams:
            p = self.profiles.get(f, {})
            rows.append(('Family "%s"' % f,
                         '%s %s' % (p.get('catalog') or 'no section',
                                    ('(' + p['material'] + ')')
                                    if p.get('material') else '')))
        s = self.score
        rows.append(('Weight', ts.describe(s)))
        if self.defl and self.defl['span_m'] > 0:
            d = self.defl
            rows.append(('Deflection', '%s %s = L/%s, limit L/%d: %s' % (
                self.u.f('deflection', d['deflection_mm'], 2),
                self.u.lab('deflection'),
                '%.0f' % d['L_over'] if d['L_over'] < 1e7 else '∞',
                td.DEFLECTION_LIMIT, 'OK' if d['ok'] else 'TOO MUCH')))
        # THE WHOLE VERDICT, on the first page. Everything ▶ Analyze puts
        # on screen used to be spread over the sheets that follow, or --
        # for the stability line and the plate checks -- nowhere in the
        # report at all. A reader who only ever sees page one should see
        # what the app said.
        if self.stability and self.stability.get('text'):
            rows.append(('Stability', self.stability['text']))
        gov = td.governing(self.checks)
        if gov:
            i, c = gov
            rows.append(('Most used rod', 'rod %d at %.2f (%s)%s' % (
                i, c['util'], c.get('governing') or c.get('mode') or '',
                '' if c['ok'] else ' — OVER CAPACITY')))
            over = sum(1 for ch in self.checks
                       if ch.get('checked') and not ch.get('ok'))
            rows.append(('Rods over capacity', '%d of %d checked' % (
                over, sum(1 for ch in self.checks if ch.get('checked')))))
        elif self.checks:
            rows.append(('Rod checks',
                         'none — no family has a steel section yet'))
        if self.buckling_factors:
            rows.append(('Buckling', 'λ₁ = %.2f%s' % (
                self.buckling_factors[0],
                ' — BELOW 1, it buckles before the full load is on'
                if self.buckling_factors[0] < 1.0 else '')))
        if self.plates:
            ok = sum(1 for c in self.plate_checks
                     if c and c.get('ok', True))
            bad = sum(1 for c in self.plate_checks
                      if c and not c.get('ok', True))
            rows.append(('Plates', '%d checked, %d over%s' % (
                ok + bad, bad,
                ' (%d could not be checked)' % (len(self.plates) - ok - bad)
                if len(self.plates) > ok + bad else '')))
        rows.append(('Shear and moment',
                     'present — see the Shear, Moment, Joints and Rod '
                     'detail sheets' if self.bends() else
                     'none: every rod is pinned and loaded only at its '
                     'nodes, so the axial force is the whole result'))
        jm = self.joint_moments()
        if jm:
            e = jm[0]
            rows.append(('Joint moment', 'largest %s %s at joint %d (%s, '
                         'from rod %s)' % (
                             self.u.f('moment', e['signed'], 2, sign=True),
                             self.u.lab('moment'), e['node'],
                             'anticlockwise' if e['signed'] > 0
                             else 'clockwise', e['rod'])))
        y -= 0.07
        for k, v in rows:
            fig.text(0.06, y, k, fontsize=9, color='#7a8087')
            fig.text(0.24, y, _wrap(v, 62), fontsize=9, color=INK,
                     va='top')
            y -= 0.034 * (1 + v.count('\n') + len(v) // 62)
        fig.text(0.62, 0.85, 'Contents', fontsize=11, fontweight='bold',
                 color=INK)
        for i, c in enumerate(contents):
            fig.text(0.62, 0.81 - 0.026 * i, '%d. %s' % (i + 2, c),
                     fontsize=9, color=INK)
        # y 0.235 and not 0.145: the ISO title block owns everything
        # below 0.158 from x 0.414 rightwards, and a full-width line down
        # there loses its right half behind it.
        fig.text(0.06, 0.235, _wrap(
            'Results are an aid to a qualified professional, who must '
            'check them. Rod checks to CIRSOC 301 as implemented; '
            'first-order analysis; joints and connections are not checked '
            'here.', 150), fontsize=7.5, color='#666', va='top')

    def geometry(self):
        fig = self.new_sheet('Geometry')
        ax = self.drawing_axes(fig)
        self.draw_rods(ax, numbers=True)
        self.draw_nodes(ax, numbers=True)
        self.draw_supports(ax)
        self._dimensions(ax)
        self.scale_bar(ax)
        fig.text(0.05, 0.945, 'Node numbers in purple, rod numbers in blue. '
                 'Dimensions in %s.' % self.u.lab('length'), fontsize=8,
                 color=INK)

    def _dimensions(self, ax):
        x0, x1, y0, y1 = self.box
        off = 0.07 * self.span
        tick = 0.012 * self.span

        def hdim(xa, xb, y, text):
            ax.annotate('', xy=(xa, y), xytext=(xb, y),
                        arrowprops=dict(arrowstyle='<->', color=INK, lw=0.7))
            ax.text((xa + xb) / 2, y + tick, text, fontsize=6.5, color=INK,
                    ha='center', va='bottom')
        # the bays along the bottom, then the overall span
        bottom = sorted({round(x, 6) for x, y in self.pts
                         if abs(y - y0) < 1e-6})
        if len(bottom) > 2:
            for xa, xb in zip(bottom, bottom[1:]):
                hdim(xa, xb, y0 - off, self.u.f('length', xb - xa, 2))
        hdim(x0, x1, y0 - 2 * off, self.u.f('length', x1 - x0, 2))
        if y1 - y0 > 1e-6:
            xd = x1 + off
            ax.annotate('', xy=(xd, y0), xytext=(xd, y1),
                        arrowprops=dict(arrowstyle='<->', color=INK, lw=0.7))
            ax.text(xd + tick, (y0 + y1) / 2, self.u.f('length', y1 - y0, 2),
                    fontsize=6.5, color=INK, rotation=90, va='center')

    def forces(self):
        fig = self.new_sheet('Axial forces')
        ax = self.drawing_axes(fig)
        N = [r['force'] for r in self.res['rod_res']]
        big = max((abs(n) for n in N), default=0.0) or 1.0

        def col(i):
            return CT if N[i] > 0.01 else CC if N[i] < -0.01 else CZ
        self.draw_rods(ax, color=col, width=lambda i: 1.0 + 4.0 * abs(N[i]) / big)
        self.draw_supports(ax)
        self.draw_loads(ax)
        for i, r in enumerate(self.rods):
            (xa, ya), (xb, yb) = self.pts[r['a']], self.pts[r['b']]
            ax.text((xa + xb) / 2, (ya + yb) / 2, '%d: %s' % (
                i, self.u.f('force', _z(N[i]), 1, sign=True)), fontsize=6.2,
                color=col(i), ha='center', va='center', zorder=8,
                bbox=dict(boxstyle='round,pad=0.12', fc='white', ec='none',
                          alpha=0.85))
        self.scale_bar(ax)
        fig.text(0.05, 0.945, 'Axial force N (%s): red pulls (+), blue '
                 'pushes (−), grey carries nothing; line width follows |N| '
                 '(largest %s).' % (self.u.lab('force'),
                                    self.u.f('force', big, 1)),
                 fontsize=8, color=INK)

    def deflection_and_stress(self):
        """Three graphs on one sheet, divided: the deflected shape, the
        elastic curve through the joints, and the fibre stress in every
        rod.

        ONE SHEET BECAUSE THEY ARE ONE QUESTION. "How far does it move
        and how hard is the material working" was three sheets --
        a drawing, a number buried in a caption, and nothing at all for
        the stress. They answer each other: the shape says WHERE it
        moves, the curve says HOW MUCH against the limit, and the fibre
        stress says what that costs the steel. Read together they take
        one page; read apart they take three and lose the connection.
        """
        fig = self.new_sheet('Deflection and stress')
        self._deformed_panel(fig, rect=(0.04, 0.47, 0.92, 0.45))
        # The dividers. A sheet carrying three graphs has to say so with
        # a line, or the eye reads the nearest axis label as the caption
        # of the picture above it. One across, under the drawing, and
        # one down between the two graphs -- NOT a second across one,
        # which at this height could only run through their captions or
        # under the title block.
        _hrule(fig, 0.455)
        _vrule(fig, 0.505, 0.19, 0.44)
        self._elastic_curve_panel(fig, rect=(0.075, 0.255, 0.355, 0.155))
        self._fibre_stress_panel(fig, rect=(0.575, 0.255, 0.355, 0.155))
        return self.deform_factor

    @staticmethod
    def _panel_title(fig, x, y, text, note=''):
        fig.text(x, y, text, fontsize=8.5, fontweight='bold', color=INK)
        if note:
            fig.text(x + 0.150, y, note, fontsize=7, color='#777')

    def _elastic_curve_panel(self, fig, rect):
        """Every joint's vertical deflection against its position along
        the span, with the span/300 limit drawn.

        The deflection used to be ONE NUMBER in a caption -- the largest.
        A single number cannot show whether the truss sags evenly or
        dips at one panel point, which is the difference between a
        member that is too small and a truss that is too shallow.
        """
        self._panel_title(fig, rect[0], rect[1] + rect[3] + 0.018,
                          'Deflection along the span',
                          'vertical movement of every joint')
        ax = fig.add_axes(rect)
        nr = self.res['node_res']
        rows = sorted(((self.pts[i][0], -r['uy'])
                       for i, r in enumerate(nr)), key=lambda t: t[0])
        xs = [x for x, _d in rows]
        ds = [d for _x, d in rows]
        ax.plot(xs, ds, '-o', color='#1D9E75', lw=1.3, ms=2.6,
                label='joints, in order along the span')
        ax.axhline(0, color='#bbb', lw=0.7)
        d = self.defl
        if d and d['limit_mm'] > 0:
            ax.axhline(-d['limit_mm'], color='#b03a2e', lw=0.9, ls='--')
            ax.text(xs[0] if xs else 0, -d['limit_mm'],
                    ' limit L/%d = %s %s' % (
                        td.DEFLECTION_LIMIT,
                        self.u.f('deflection', d['limit_mm'], 1),
                        self.u.lab('deflection')),
                    fontsize=6, color='#b03a2e', va='top')
            worst = min(ds) if ds else 0.0
            if worst < -d['limit_mm']:
                ax.set_ylim(min(worst * 1.15, -d['limit_mm'] * 1.3),
                            max(max(ds) * 1.15 if ds else 1.0, 1.0))
        ax.set_xlabel('position along the span (%s)' % self.u.lab('length'),
                      fontsize=6.5)
        ax.set_ylabel('uy (%s, down −)' % self.u.lab('deflection'),
                      fontsize=6.5)
        ax.tick_params(labelsize=6)
        for sp in ('top', 'right'):
            ax.spines[sp].set_visible(False)
        if d and d['span_m'] > 0:
            fig.text(rect[0], rect[1] - 0.062, _wrap(
                'Largest %s %s at joint %d = L/%s. %s' % (
                    self.u.f('deflection', d['deflection_mm'], 2),
                    self.u.lab('deflection'), d['node'],
                    '%.0f' % d['L_over'] if d['L_over'] < 1e7 else '∞',
                    'Within the limit.' if d['ok'] else 'OVER the limit.'),
                82), fontsize=6.8, color='#555', va='top')

    def _fibre_stress_panel(self, fig, rect):
        """The stress at the two extreme fibres of every rod.

        A pinned rod has no bending, so both fibres carry the same N/A
        and the two bars coincide -- which is the point, and is said in
        the note rather than hidden by drawing only one of them. A rigid
        rod separates: N/A ± M·c/I, and the gap between the pair IS the
        bending.
        """
        from .truss_math import compute_fiber_stress
        self._panel_title(fig, rect[0], rect[1] + rect[3] + 0.018,
                          'Fibre stress',
                          'N/A ± M·c/I at each rod\'s extreme fibres')
        ax = fig.add_axes(rect)
        rod_res = self.res['rod_res']
        rows = []
        for ri, rod in enumerate(self.rods):
            if ri >= len(rod_res):
                continue
            Ms = (self.diagrams[ri].get('M', [0.0])
                  if ri < len(self.diagrams) else [0.0])
            try:
                neg, pos = compute_fiber_stress(rod, rod_res[ri], Ms)
            except Exception:
                continue
            lo = min(list(neg) + list(pos)) if neg or pos else 0.0
            hi = max(list(neg) + list(pos)) if neg or pos else 0.0
            rows.append((ri, lo, hi))
        if not rows:
            ax.axis('off')
            ax.text(0, 0.5, 'No fibre stress to show.', fontsize=7,
                    color='#777')
            return
        rows.sort(key=lambda t: -max(abs(t[1]), abs(t[2])))
        rows = rows[:16]
        ys = list(range(len(rows)))[::-1]
        for y, (ri, lo, hi) in zip(ys, rows):
            ax.plot([lo, hi], [y, y], color='#9aa3ab', lw=0.8, zorder=1)
            ax.plot([lo], [y], 'o', ms=3.4, color=CC if lo < 0 else CT,
                    zorder=3)
            ax.plot([hi], [y], 'o', ms=3.4, color=CT if hi > 0 else CC,
                    zorder=3)
        ax.axvline(0, color='#bbb', lw=0.7)
        fys = {self.profiles.get(r.get('profile', 'Default'), {}).get('Fy')
               for r in self.rods}
        fys.discard(None)
        if len(fys) == 1:
            fy = fys.pop()
            for sign in (1, -1):
                ax.axvline(sign * fy, color='#b03a2e', lw=0.9, ls='--')
            ax.text(fy, len(rows) - 0.4, ' Fy = %g MPa' % fy, fontsize=6,
                    color='#b03a2e', va='top')
        ax.set_yticks(ys)
        ax.set_yticklabels(['Rod %d' % ri for ri, _l, _h in rows],
                           fontsize=6)
        ax.set_xlabel('stress (MPa, tension +)', fontsize=6.5)
        ax.tick_params(axis='x', labelsize=6)
        for sp in ('top', 'right'):
            ax.spines[sp].set_visible(False)
        note = ('The %d most stressed rods; the bar between a rod\'s two '
                'dots is its bending.' % len(rows))
        if not self.bends():
            note = ('Every rod is pinned, so its two fibres carry the same '
                    'N/A and coincide: no bending opens the pair.')
        fig.text(rect[0], rect[1] - 0.062, _wrap(note, 82), fontsize=6.8,
                 color='#555', va='top')

    def contraflexure(self, k):
        """[(rod, x/L, (x, y) on the deformed curve)] for every point where
        a rigid rod's moment changes sign along its span.

        From the SAME M(x) the Moment sheet draws (`find_zero_crossings`
        on `diagrams[i]['M']`), placed on the SAME Hermite curve the tab
        draws (`deformed_point_at`), so a marker here always sits where
        the moment diagram crosses zero and where the curve changes the
        way it bends. Crossings within 2 % of an end are left out, as on
        screen: zero moment AT a joint is a pinned-looking end, not a
        reversal of curvature along the span.
        """
        from .truss_math import find_zero_crossings, deformed_point_at
        out = []
        nr, rr_all = self.res['node_res'], self.res['rod_res']
        for i, rod in enumerate(self.rods):
            if rod.get('conn') != 'rigid' or i >= len(self.diagrams):
                continue
            d = self.diagrams[i]
            Lm = d.get('Lm', 0.0)
            if Lm <= 0 or not d.get('M'):
                continue
            for xc in find_zero_crossings(d['xs'], d['M']):
                t = max(0.0, min(1.0, xc / Lm))
                if t < 0.02 or t > 0.98:
                    continue
                px, py = deformed_point_at(
                    self.nodes[rod['a']], self.nodes[rod['b']],
                    nr[rod['a']], nr[rod['b']],
                    rr_all[i] if i < len(rr_all) else None, k, t)
                out.append((i, t, _xy((px, py))))
        return out

    def _deformed_panel(self, fig, rect):
        """The ELASTIC LINE: the deflected shape with every rigid rod
        drawn as the curve it actually bends into, and its points of
        contraflexure marked.

        WHAT IT WAS. Straight segments between the displaced joints. For
        a pinned truss that is exact -- a pin bar does not bend -- but
        for a rigid rod it threw away the whole point: a Vierendeel
        member bends in DOUBLE curvature, S-shaped, and the place where
        it changes the way it bends (M = 0) is what the tab marks with a
        ○ and what the owner asked for by name.

        WHAT IT IS. `truss_math.deformed_shape_points`, the tab's own
        function: the Euler-Bernoulli cubic of each rigid rod driven by
        its solved end displacements AND end rotations, straight lines
        for pin rods. Magnified by the same factor k for both, which at
        a joint reduces exactly to the displaced node, so the curves meet
        where the joints are.
        """
        from .truss_math import deformed_shape_points
        ax = self.drawing_axes(fig, rect=rect)
        nr = self.res['node_res']
        dmax_m = max((math.hypot(r['ux'], r['uy']) for r in nr),
                     default=0.0) / 1000.0
        # THE SCREEN'S MAGNIFICATION when the tab hands it over: the
        # owner compared this sheet against the canvas at its own slider
        # setting (×50 by default), and at an automatic ×20 a Vierendeel
        # member's double curvature was too flat to see. A report written
        # by a script has no slider, and gets enough to put the biggest
        # movement at 12 % of the span -- where an S-bend reads.
        if self.deform_scale:
            k = float(self.deform_scale)
        else:
            k = (0.12 * self.span / dmax_m) if dmax_m > 1e-12 else 1.0
            k = _round_factor(k)
        moved = [(x + k * r['ux'] / 1000.0, y - k * r['uy'] / 1000.0)
                 for (x, y), r in zip(self.pts, nr)]
        self.draw_rods(ax, color=GHOST, width=1.0)
        curves = deformed_shape_points(self.nodes, self.rods, nr,
                                       self.res['rod_res'], k)
        # A big slider value can throw the shape past the margin the
        # drawing was sized for; widen the view to hold it rather than
        # clip it. Equal aspect is kept, so it stays to scale.
        allx = [p[0] for c_ in curves for p in (_xy(q) for q in c_)]
        ally = [p[1] for c_ in curves for p in (_xy(q) for q in c_)]
        if allx:
            m_ = 0.06 * self.span
            x0, x1 = ax.get_xlim()
            y0, y1 = ax.get_ylim()
            ax.set_xlim(min(x0, min(allx) - m_), max(x1, max(allx) + m_))
            ax.set_ylim(min(y0, min(ally) - m_), max(y1, max(ally) + m_))
        for pts in curves:
            xy = [_xy(p) for p in pts]
            ax.plot([p[0] for p in xy], [p[1] for p in xy],
                    color='#1D9E75', lw=1.9, zorder=4,
                    solid_capstyle='round')
        ax.plot([p[0] for p in moved], [p[1] for p in moved], 'o',
                ms=3.0, color='#1D9E75', zorder=5)
        flex = self.contraflexure(k)
        for _i, _t, (x, y) in flex:
            ax.plot([x], [y], 'o', ms=5.6, mfc='white', mec='#1D9E75',
                    mew=1.6, zorder=6)
        self.draw_supports(ax)
        d = self.defl
        if d:
            x, y = moved[d['node']]
            ax.annotate('%s %s = L/%s' % (
                self.u.f('deflection', d['deflection_mm'], 2),
                self.u.lab('deflection'),
                '%.0f' % d['L_over'] if d['L_over'] < 1e7 else '∞'),
                (x, y), xytext=(10, -18), textcoords='offset points',
                fontsize=7, color=INK,
                arrowprops=dict(arrowstyle='-', color=INK, lw=0.6))
        self.scale_bar(ax)
        line = ('Elastic line: the deflected shape (green) over the truss '
                '(grey), every rigid rod drawn as the curve it bends into. '
                'Geometry to scale; displacements magnified × %g.' % k)
        if flex:
            line += ('  ○ = point of contraflexure (M = 0), where a rod '
                     'changes the way it bends: %d of them.' % len(flex))
        elif not self.bends():
            line += ('  Every rod is pinned, so every member stays straight: '
                     'there is no curvature, and no contraflexure.')
        if d and d['span_m'] > 0:
            line += ('  Largest vertical deflection %s %s against the limit '
                     'L/%d = %s %s: %s.' % (
                         self.u.f('deflection', d['deflection_mm'], 2),
                         self.u.lab('deflection'), td.DEFLECTION_LIMIT,
                         self.u.f('deflection', d['limit_mm'], 1),
                         self.u.lab('deflection'),
                         'OK' if d['ok'] else 'TOO MUCH'))
        fig.text(0.05, 0.955, _wrap(line, 165), fontsize=7.8, color=INK,
                 va='top')
        self.deform_factor = k
        self.flex_points = flex

    def reactions(self):
        fig = self.new_sheet('Reactions')
        ax = self.drawing_axes(fig, rect=(0.05, 0.19, 0.60, 0.74))
        self.draw_rods(ax, color=GHOST, width=1.2)
        self.draw_supports(ax)
        self.draw_loads(ax)
        rx = self.res['reactions']
        big = max((math.hypot(r['rx'], r['ry']) for r in rx.values()),
                  default=0.0) or 1.0
        glyph = 0.025 * self.span * 2.2      # below the support symbol
        for n, r in rx.items():
            x, y = self.pts[n]
            for fx, fy in ((r['rx'], 0.0), (0.0, -r['ry'])):
                m = math.hypot(fx, fy)
                if m < 1e-6:
                    continue
                L = 0.12 * self.span * (0.4 + 0.6 * m / big)
                ux, uy = fx / m, fy / m
                # an upward push ends under the symbol, where its head shows
                tip = (x, y - glyph) if uy > 0.5 else (x, y)
                ax.annotate('', xy=tip,
                            xytext=(tip[0] - L * ux, tip[1] - L * uy),
                            arrowprops=dict(arrowstyle='-|>', color=REACTION,
                                            lw=1.4), zorder=7)
        self.scale_bar(ax)
        tab = fig.add_axes((0.67, 0.30, 0.29, 0.60))
        tab.axis('off')
        F = self.u.lab('force')
        rows = [['Node', 'Type', 'Rx (%s)' % F, 'Ry (%s)' % F]]
        for n in sorted(rx):
            r = rx[n]
            rows.append([str(n), r.get('type', ''),
                         self.u.f('force', _z(r['rx']), 2),
                         self.u.f('force', _z(-r['ry']), 2)])
        sx = sum(r['rx'] for r in rx.values())
        sy = sum(-r['ry'] for r in rx.values())
        rows.append(['Σ', '', self.u.f('force', _z(sx), 2),
                     self.u.f('force', _z(sy), 2)])
        _table(tab, rows)
        fig.text(0.05, 0.945, 'Support reactions (green arrows), as the '
                 'supports push on the truss; Ry positive upwards. The sums '
                 'balance the loads.', fontsize=8, color=INK)

    def utilisation(self):
        """How hard each rod is working, drawn and ranked.

        The rod table already carries the utilisation as a column of
        numbers, and a column of numbers is not how anyone finds the rod
        that is in trouble. This is the same information as a picture:
        the truss in the Tab's own green-amber-red ramp, and the rods
        ranked beside it so the worst one is the top bar.

        Rods whose family has no steel section are GREY and are said to
        be grey, rather than being left out: "no section" is a state of
        the model the reader has to know about, not a gap in the drawing.
        """
        checked = [(i, c['util']) for i, c in enumerate(self.checks)
                   if c.get('checked') and c.get('util') is not None]
        fig = self.new_sheet('Utilisation')
        ax = self.drawing_axes(fig, rect=(0.05, 0.19, 0.56, 0.74))
        util = {i: u for i, u in checked}

        def col(i):
            return td.util_color(util.get(i))
        self.draw_rods(ax, color=col, width=3.0)
        self.draw_supports(ax)
        self.draw_loads(ax, label=False)
        for i, u in checked:
            r = self.rods[i]
            (xa, ya), (xb, yb) = self.pts[r['a']], self.pts[r['b']]
            ax.text((xa + xb) / 2, (ya + yb) / 2, '%.2f' % u, fontsize=6.2,
                    color=INK, ha='center', va='center', zorder=8,
                    bbox=dict(boxstyle='round,pad=0.12', fc='white',
                              ec='none', alpha=0.85))
        self.scale_bar(ax)
        self._util_key(fig)

        if not checked:
            fig.text(0.05, 0.945, 'No rod is checked: no family has a steel '
                     'section yet, so every rod is drawn grey. Give one a '
                     'section (Section → Material and section) and the '
                     'utilisations appear here.', fontsize=8, color=INK)
            return []

        # The ranking, worst first: the only order worth reading.
        order = sorted(checked, key=lambda t: -t[1])
        show = order[:18]
        bx = fig.add_axes((0.66, 0.235, 0.29, 0.675))
        ys = list(range(len(show)))[::-1]
        bx.barh(ys, [u for _i, u in show],
                color=[td.util_color(u) for _i, u in show], height=0.72)
        bx.axvline(1.0, color='#b03a2e', lw=1.0, ls='--')
        bx.text(1.0, len(show) - 0.2, ' capacity', fontsize=6.5,
                color='#b03a2e', va='top')
        bx.set_yticks(ys)
        bx.set_yticklabels(['Rod %d' % i for i, _u in show], fontsize=6.5)
        bx.set_xlim(0, max(1.15, min(1.6, max(u for _i, u in show) * 1.12)))
        bx.tick_params(axis='x', labelsize=6.5)
        bx.set_xlabel('utilisation (demand / capacity)', fontsize=7)
        for spine in ('top', 'right'):
            bx.spines[spine].set_visible(False)
        for y, (_i, u) in zip(ys, show):
            bx.text(u, y, ' %.2f' % u, fontsize=6.2, va='center', color=INK)

        worst_i, worst_u = order[0]
        gov = self.checks[worst_i].get('governing') or \
            self.checks[worst_i].get('mode') or ''
        over = [i for i, u in order if u > 1.0]
        line = ('Utilisation: demand over CIRSOC 301 capacity. Most used '
                'rod %d at %.2f (%s).' % (worst_i, worst_u, gov))
        if over:
            line += ('  %d rod(s) OVER capacity: %s.'
                     % (len(over), ', '.join(str(i) for i in over[:10])))
        else:
            line += '  Every checked rod is within capacity.'
        n_grey = len(self.rods) - len(checked)
        if n_grey:
            line += ('  %d rod(s) are grey: their family has no steel '
                     'section, so they are not checked.' % n_grey)
        fig.text(0.05, 0.945, _wrap(line, 160), fontsize=8, color=INK,
                 va='top')
        if len(order) > len(show):
            fig.text(0.66, 0.195, 'The %d most used of %d checked rods; '
                     'the rest are in the Rods table.'
                     % (len(show), len(order)), fontsize=6.5, color='#777')
        return [i for i, _u in order]

    def _util_key(self, fig):
        """The colour ramp, with what each end means written on it."""
        import numpy as np
        from matplotlib.colors import ListedColormap
        # x < 0.414 and y > 0.158, which is the strip the ISO title
        # block (stereo_reports.PDF_TITLE_W/H) leaves free.
        kx = fig.add_axes((0.05, 0.088, 0.30, 0.022))
        steps = np.linspace(0.0, 1.2, 120)
        cmap = ListedColormap([td.util_color(u) for u in steps])
        kx.imshow(steps.reshape(1, -1), aspect='auto', cmap=cmap,
                  extent=(0.0, 1.2, 0.0, 1.0))
        kx.set_yticks([])
        kx.set_xticks([0.0, 0.6, 1.0, 1.2])
        kx.set_xticklabels(['0', '0.6', '1.0 capacity', '1.2+'], fontsize=6.5)
        kx.tick_params(length=2)
        fig.text(0.05, 0.048, 'grey = no steel section, not checked',
                 fontsize=6.5, color='#777')

    def buckling(self, result, curve):
        """The three lowest buckling factors, their shapes, and the
        second-order curve.

        WHY THREE. One number ("it buckles at 3.7x") says whether there is
        room; three say how much room there is BETWEEN the modes. Modes at
        3.7, 3.8 and 3.9 mean a structure with no single weak link and
        nothing much to gain by bracing one rod, while 1.4, 6.0 and 6.2
        means one member decides everything -- and that is a design
        reading, not a number.

        Elastic and ideal, so each lambda is an UPPER bound; that is said
        on the sheet rather than left for the reader to remember.
        """
        fig = self.new_sheet('Buckling')
        if not result or 'error' in (result or {}):
            fig.text(0.05, 0.93, 'Buckling', fontsize=13, color=INK)
            fig.text(0.05, 0.86, (result or {}).get(
                'error', 'Buckling was not computed for this report.'),
                fontsize=9, color=INK, wrap=True)
            return []
        factors = result['factors']
        modes = result['modes']
        n = min(len(factors), 3)
        self.buckling_factors = list(factors[:n])
        width = 0.90 / max(n, 1)
        for j in range(n):
            ax = fig.add_axes((0.05 + j * width, 0.52, width * 0.94, 0.30))
            self._draw_mode(ax, modes[j])
            lam = factors[j]
            tone = '#b03a2e' if lam < 1.0 else INK
            where = modes[j]['peak']
            what = ('rod %d bows' % where[1] if where[0] == 'mid'
                    else 'node %d moves most' % where[1])
            ax.set_title('Mode %d:  λ = %.2f\n%s' % (j + 1, lam, what),
                         fontsize=8.5, color=tone)
        head = 'λ is the factor on the load as it stands. '
        if factors[0] < 1.0:
            head += ('λ₁ = %.2f is BELOW 1: it buckles before the full load '
                     'is on.' % factors[0])
        else:
            head += ('λ₁ = %.2f, so the load can grow %.1f× before it '
                     'buckles.' % (factors[0], factors[0]))
        if n >= 2:
            gap = factors[1] / factors[0] if factors[0] > 1e-9 else 0.0
            same = sum(1 for lam in factors if lam <= factors[0] * 1.001)
            head += '  '
            if same >= 2:
                # Equal eigenvalues are not a numerical accident here:
                # identical members under identical force buckle at
                # identical load, and saying so is the reading. Bracing
                # one of them moves nothing; all of them have to go.
                head += ('%d modes share that λ: that many equal members '
                         'buckle at the same load, so stiffening one of '
                         'them buys nothing.' % same)
            elif gap > 1.3:
                head += ('Mode 2 is %.2f, %.0f %% higher: one member '
                         'decides the buckling load.'
                         % (factors[1], 100 * (gap - 1)))
            else:
                head += ('Mode 2 is %.2f, only %.0f %% higher: no single '
                         'member decides it.'
                         % (factors[1], 100 * (gap - 1)))
        fig.text(0.05, 0.945, _wrap(head, 160), fontsize=8, color=INK,
                 va='top')
        self._load_deflection(fig, curve)
        fig.text(0.45, 0.325, _wrap(
                 'Elastic buckling of the IDEAL truss, so every λ is an '
                 'UPPER bound: imperfections, residual stresses and '
                 'yielding are not modelled, and each rod is cut in two so '
                 'it can bow between its joints. Buckling OUT of the plane '
                 'is the rod check\'s job (CIRSOC 301 E3, minor radius) and '
                 'is in the Utilisation and Rods sheets, not here. A mode '
                 'has a shape, not a size: the shapes are drawn '
                 'exaggerated.', 88), fontsize=6.6, color='#777', va='top')
        return factors[:n]

    def _draw_mode(self, ax, mode):
        """One buckling shape: the truss in grey, the mode in red.

        The mode's (dx, dy) are metres in the CANVAS frame, y down
        (truss_buckling.Model), and this sheet's points are y up -- hence
        the minus on dy. Getting that wrong flips the shape vertically,
        which for a mode (±φ are the same mode) looks plausible and is
        still wrong next to the loads and supports.
        """
        amp = 0.07 * self.span
        moved = [(x + amp * dx, y - amp * dy)
                 for (x, y), (dx, dy) in zip(self.pts, mode['nodes'])]
        for r in self.rods:
            (xa, ya), (xb, yb) = self.pts[r['a']], self.pts[r['b']]
            ax.plot([xa, xb], [ya, yb], color=GHOST, lw=1.1, zorder=2)
        for k, r in enumerate(self.rods):
            (xa, ya) = moved[r['a']]
            (xb, yb) = moved[r['b']]
            mx0 = (self.pts[r['a']][0] + self.pts[r['b']][0]) / 2
            my0 = (self.pts[r['a']][1] + self.pts[r['b']][1]) / 2
            dx, dy = mode['mids'][k]
            mx, my = mx0 + amp * dx, my0 - amp * dy
            # Three points through a quadratic Bezier, so a bowing rod
            # reads as a bow and not as two straight segments.
            ts = [i / 12.0 for i in range(13)]
            xs = [(1 - t) ** 2 * xa + 2 * (1 - t) * t * (2 * mx - (xa + xb) / 2)
                  + t ** 2 * xb for t in ts]
            ys = [(1 - t) ** 2 * ya + 2 * (1 - t) * t * (2 * my - (ya + yb) / 2)
                  + t ** 2 * yb for t in ts]
            ax.plot(xs, ys, color='#c0392b', lw=1.6, zorder=3)
        for sp in self.supports:
            x, y = self.pts[sp['node']]
            s = 0.03 * self.span
            ax.fill([x, x - s, x + s], [y, y - 1.6 * s, y - 1.6 * s],
                    color=SUPPORT, zorder=4)
        ax.set_aspect('equal', adjustable='datalim')
        ax.axis('off')

    def _load_deflection(self, fig, curve):
        """The second-order curve: how the bow runs away as λ nears λ_cr."""
        ax = fig.add_axes((0.08, 0.24, 0.30, 0.26))
        if not curve or 'error' in curve or not curve.get('factors'):
            ax.axis('off')
            ax.text(0.0, 0.5, (curve or {}).get(
                'error', 'No second-order curve.'), fontsize=7, color='#777')
            return
        lcr = curve['lambda_cr']
        ax.plot(curve['first_mm'], curve['factors'], color='#888', lw=1.0,
                label='first order (straight)')
        ax.plot(curve['node_mm'], curve['factors'], color='#1a6bbd', lw=1.4,
                label='second order')
        ax.plot(curve['bow_mm'], curve['factors'], color='#c0392b', lw=1.4,
                ls='--', label='bow of the rod that buckles')
        ax.axhline(lcr, color='#c0392b', lw=0.8, ls=':')
        ax.text(0.0, lcr, ' λ_cr = %.2f' % lcr, fontsize=6.5,
                color='#c0392b', va='bottom')
        ax.set_xlabel('movement (mm)', fontsize=7)
        ax.set_ylabel('load factor λ', fontsize=7)
        ax.tick_params(labelsize=6.5)
        ax.legend(fontsize=6, frameon=False, loc='lower right')
        for spine in ('top', 'right'):
            ax.spines[spine].set_visible(False)
        fig.text(0.45, 0.495, _wrap('The second-order line bends away from the '
                 'first-order one and runs off as λ nears λ_cr: that gap IS '
                 'the amplification every second-order design rule is '
                 'about. Started from an initial bow of L/1000 = %.2f mm in '
                 'the first mode\'s shape.' % curve.get('bow0_mm', 0.0), 86),
                 fontsize=6.8, color='#555', va='top')

    # ── the joints: how much moment each one carries, and which way ──────
    #: Joints listed per Joints sheet beside the drawing, above the
    #: title block.
    JOINT_ROWS = 22

    def joint_moments(self):
        """One entry per joint that carries moment, worst first.

        THE NUMBER THAT MATTERS AT A JOINT is the largest moment any ONE
        rod hands it -- what a rigid connection has to be designed for --
        and NOT the sum: by equilibrium the rods' moments at a free joint
        cancel, so the sum reads ~0 at exactly the joints that work
        hardest. The sum is still reported, because it is the check: ~0
        at a free joint, and at a fixed support the moment the support
        has to supply.

        Sign and sense follow the tab (`compute_node_moments` and its
        circular arrows): the moment the rod applies to the joint,
        positive ANTICLOCKWISE. The TENSION FACE says the same thing the
        way it matters to a member: which face of that rod, at that
        joint, the moment stretches -- from the rod's internal moment at
        that end (M(0) at end A, M(L) at end B; note rod_res 'Mb' is the
        END ACTION, minus the internal moment) and the rod's +v side.
        """
        nm = (self.res or {}).get('node_moments') or {}
        rxn = (self.res or {}).get('reactions') or {}
        out = []
        for ni in range(len(self.nodes)):
            d = nm.get(ni)
            if not d:
                continue
            members = d.get('members', [])
            rigid = [m for m in members if m.get('conn') == 'rigid']
            sup = next((s_ for s_ in self.supports if s_['node'] == ni), None)
            r_m = float((rxn.get(ni) or {}).get('m', 0.0) or 0.0)
            big = float(d.get('max_abs', 0.0))
            if big <= 0.05 and abs(r_m) <= 0.05:
                continue
            ri = d.get('max_abs_rod')
            signed = float(d.get('max_signed', 0.0))
            face = '—'
            if ri is not None and ri < len(self.diagrams):
                rod = self.rods[ri]
                M = self.diagrams[ri].get('M') or [0.0]
                m_int = M[0] if rod['a'] == ni else M[-1]
                if abs(m_int) > 1e-9:
                    nx, ny = self.normal(ri)
                    tx, ty = (nx, ny) if m_int > 0 else (-nx, -ny)
                    face = (('top' if ty > 0 else 'bottom')
                            if abs(ty) >= abs(tx) else
                            ('right' if tx > 0 else 'left'))
            kind = ('rigid' if len(rigid) == len(members) else
                    'pinned' if not rigid else 'mixed')
            out.append({'node': ni, 'kind': kind,
                        'support': sup['type'] if sup else '',
                        'max_abs': big, 'signed': signed, 'rod': ri,
                        'face': face, 'net': float(d.get('net', 0.0)),
                        'reaction_m': r_m})
        out.sort(key=lambda e: -e['max_abs'])
        return out

    def _moment_arc(self, ax, x, y, m, r, color):
        """The tab's circular arrow: anticlockwise for a positive moment,
        clockwise for a negative one -- the way the moment turns the
        joint, not a colour code (`_draw_moment_arc` on screen)."""
        start, sweep = math.radians(20), math.radians(250)
        sgn = 1.0 if m > 0 else -1.0
        n = 28
        angs = [start + sgn * sweep * k / (n - 1) for k in range(n)]
        xs = [x + r * math.cos(a) for a in angs]
        ys = [y + r * math.sin(a) for a in angs]
        ax.plot(xs, ys, color=color, lw=1.4, zorder=7,
                solid_capstyle='round')
        ax.annotate('', xy=(xs[-1], ys[-1]), xytext=(xs[-3], ys[-3]),
                    arrowprops=dict(arrowstyle='-|>', color=color, lw=1.4,
                                    mutation_scale=9), zorder=7)

    def joints(self):
        """Every joint that carries moment: how much, the sign, which way
        it turns the joint, and which face of the rod it stretches.

        Produced only when some joint carries moment -- a rigid rod, or a
        fixed support. On a pinned truss no joint carries any, and the
        cover says so.
        """
        rows = self.joint_moments()
        if not rows:
            return []
        MOM = '#7b2d8e'
        per = self.JOINT_ROWS
        pages = [rows[i:i + per] for i in range(0, len(rows), per)]
        unit = self.u.lab('moment')
        head = ['Joint', 'Type', 'Max |M| (%s)' % unit, '±', 'Turns it',
                'Rod', 'Tension', 'Σ M check']
        for pno, chunk in enumerate(pages):
            fig = self.new_sheet('Joints' + (
                ' (%d/%d)' % (pno + 1, len(pages)) if len(pages) > 1 else ''))
            ax = self.drawing_axes(fig, rect=(0.04, 0.19, 0.50, 0.72),
                                   pad=0.16)
            self.draw_rods(ax, color='#9aa3ab', width=1.4)
            self.draw_supports(ax)
            r = 0.035 * self.span
            shown = {e['node'] for e in rows}
            for i, (x, y) in enumerate(self.pts):
                on = i in shown
                ax.plot([x], [y], 'o', ms=4.2 if on else 3.0,
                        color=MOM if on else INK, zorder=6)
                # Below-left, clear of the arrow, which sweeps from the
                # right round over the top.
                ax.annotate(str(i), (x, y), xytext=(-11, -11),
                            textcoords='offset points', fontsize=6.5,
                            color='#555', zorder=8)
            for e in rows:
                x, y = self.pts[e['node']]
                m = e['signed'] if e['max_abs'] > 0.05 else -e['reaction_m']
                self._moment_arc(ax, x, y, m, r, MOM)
                ax.text(x + 1.3 * r, y - 1.3 * r, '%s' % self.u.f(
                    'moment', m, 1, sign=True), fontsize=6.4, color=MOM,
                    zorder=8, bbox=dict(boxstyle='round,pad=0.1', fc='white',
                                        ec='none', alpha=0.85))
            self.scale_bar(ax)
            body = []
            for e in chunk:
                sign = '+' if e['signed'] > 0 else '−'
                where = e['kind'] + (' · ' + e['support']
                                     if e['support'] else '')
                net = e['net']
                # At a fixed support the support's own moment is what
                # closes the sum, so that is what is printed -- read from
                # the reactions, not inferred from the sum's sign.
                check = ('%s  support' % self.u.f('moment', e['reaction_m'],
                                                  2, sign=True)
                         if e['support'] == 'fixed' else
                         '%s  ✓' % self.u.f('moment', _z(net), 2))
                body.append([str(e['node']), where,
                             self.u.f('moment', e['max_abs'], 2),
                             sign,
                             'anticlockwise' if e['signed'] > 0
                             else 'clockwise',
                             str(e['rod']) if e['rod'] is not None else '—',
                             e['face'], check])
            tx = fig.add_axes((0.545, 0.20, 0.40, 0.71))
            tx.axis('off')
            _table(tx, [head] + body, fontsize=6.5)
            fig.text(0.05, 0.955, _wrap(
                'The moment at each joint: the largest one any single rod '
                'hands it -- what a rigid connection is designed for -- '
                'with its sign, which way it turns the joint (the arrow, '
                'anticlockwise = +, as on screen), and which face of that '
                'rod it puts in tension. Σ M is the check: ~0 at a free '
                'joint by equilibrium, the support\'s own moment at a '
                'fixed one.', 165), fontsize=7.8, color=INK, va='top')
            pinned = [i for i in range(len(self.nodes)) if i not in shown]
            if pinned and pno == len(pages) - 1:
                fig.text(0.565, 0.185, _wrap(
                    'No moment at joint%s %s: %s.' % (
                        's' if len(pinned) > 1 else '',
                        ', '.join(str(i) for i in pinned[:24])
                        + ('…' if len(pinned) > 24 else ''),
                        'every rod there is pinned' if not self.bends()
                        else 'pinned, or the moments there solved to zero'),
                    80), fontsize=6.6, color='#666', va='top')
        return [e['node'] for e in rows]

    def plate_table(self):
        """Every plate's check, when the model has plates.

        A SHEET THAT USUALLY DOES NOT EXIST. Most teaching models have
        no plates at all, so this costs nothing in the common case and
        is the only place the plate checks appear when it does -- they
        were in the panel on screen and nowhere in the report.

        A panel's shear-BUCKLING utilisation is printed on the same row
        as its yield one, never separately: a thin plate buckles long
        before it yields, so a comfortable tau on its own is the most
        misleading number this feature can produce.
        """
        if not self.plates:
            return 0
        head = ['Plate', 'Where', 't (mm)', 'Governing', 'Yield',
                'Buckling', 'Use', '']
        body = []
        for i, plate in enumerate(self.plates):
            chk = (self.plate_checks[i]
                   if i < len(self.plate_checks) else None)
            kind = plate.get('kind', '?')
            if kind == 'panel':
                where = 'nodes ' + '-'.join(str(n)
                                            for n in plate.get('nodes', []))
            else:
                where = 'node %s' % plate.get('node', '?')
            if not chk or chk.get('valid') is False:
                body.append([str(i), where, '—',
                             (chk or {}).get('reason', 'not checked'),
                             '—', '—', '—', ''])
                continue
            u = chk.get('util')
            body.append([
                str(i), where, '%.1f' % chk.get('t_mm', 0.0),
                str(chk.get('governing') or '')[:30],
                '%.2f' % chk['util_yield'] if 'util_yield' in chk else '—',
                '%.2f' % chk['util_buckling']
                if chk.get('util_buckling') is not None else '—',
                '%.2f' % u if u is not None else '—',
                '' if u is None or u <= 1 + 1e-9 else 'OVER'])
        fig = self.new_sheet('Plates')
        ax = fig.add_axes((0.05, 0.22, 0.90, 0.68))
        ax.axis('off')
        _table(ax, [head] + body, over_col=7)
        fig.text(0.05, 0.945, _wrap(
            'Gusset and shear-panel checks to CIRSOC 301. A panel\'s '
            'shear-BUCKLING utilisation is shown beside its yield one: a '
            'thin plate buckles long before it yields, so a comfortable '
            'tau on its own would be the most misleading number here.',
            160), fontsize=8, color=INK, va='top')
        return 1

    def rod_table(self):
        F = self.u.lab('force')
        Lb = self.u.lab('length')
        head = ['Rod', 'Nodes', 'Family', 'Section', 'L (%s)' % Lb,
                'N (%s)' % F, 'Governing check', 'Use', '']
        body = []
        for i, r in enumerate(self.rods):
            p = self.profiles.get(r.get('profile', 'Default'), {})
            c = self.checks[i] if i < len(self.checks) else {}
            N = self.res['rod_res'][i]['force']
            if c.get('checked'):
                use, ok = '%.2f' % c['util'], 'OK' if c['ok'] else 'OVER'
                gov = str(c.get('governing') or c.get('mode') or '')[:34]
            else:
                use, ok, gov = '—', '', 'no steel section'
            body.append([str(i), '%d–%d' % (r['a'], r['b']),
                         r.get('profile', 'Default')[:12],
                         (p.get('catalog') or '—')[:16],
                         self.u.f('length', td.rod_length_m(self.nodes, r), 2),
                         self.u.f('force', _z(N), 2, sign=True), gov, use,
                         ok])
        # TWO TABLES TO A SHEET, side by side. The table is under half the
        # sheet's width, so one per sheet left the right half empty -- and
        # a model just past ROWS_PER_SHEET rods got a second sheet carrying
        # eleven rows and nothing else.
        per = 2 * ROWS_PER_SHEET
        pages = [body[i:i + per] for i in range(0, len(body), per)] or [[]]
        for k, chunk in enumerate(pages):
            fig = self.new_sheet('Rods' + (' (%d/%d)' % (k + 1, len(pages))
                                           if len(pages) > 1 else ''))
            halves = [chunk[:ROWS_PER_SHEET], chunk[ROWS_PER_SHEET:]]
            for h, rows in enumerate(halves):
                if not rows and h:
                    continue
                ax = fig.add_axes((0.05 + 0.46 * h, 0.17, 0.44, 0.76))
                ax.axis('off')
                _table(ax, [head] + rows, over_col=8)
        return len(pages)

    # ── one card per rod, with its own shear and moment ───────────────────
    #: The position thumbnails. The rest of the truss at a mid grey that
    #: still reads on a laser print, and the rod itself in a saturated red
    #: three times as thick. The first version used #cdd3d8 at 0.7 pt
    #: against #c0392b at 2 pt: on screen it looked fine, on paper the
    #: truss was barely there and the red did not stand out from it.
    THUMB_REST = '#6f7880'
    THUMB_ROD = '#e0001b'

    def thumbnail(self, ax, ri, lw=1.0):
        """The whole truss, small, with rod `ri` picked out in red.

        WHY EVERY CARD CARRIES ONE. "Rod 13 is at 0.63" is a sentence
        about a rod the reader cannot place. On a 17-rod Pratt there is
        no way to know which member that is without counting along the
        Geometry sheet, and on a 60-rod model nobody does. A thumbnail
        answers it at once, and costs almost no space because it shares
        the row it labels.

        Drawn with the rod LAST, on top, and with a white casing under
        it, so where it crosses another member it is never the one that
        disappears.
        """
        for k, r in enumerate(self.rods):
            if k == ri:
                continue
            (xa, ya), (xb, yb) = self.pts[r['a']], self.pts[r['b']]
            ax.plot([xa, xb], [ya, yb], color=self.THUMB_REST, lw=lw,
                    zorder=2, solid_capstyle='round')
        r = self.rods[ri]
        (xa, ya), (xb, yb) = self.pts[r['a']], self.pts[r['b']]
        ax.plot([xa, xb], [ya, yb], color='white', lw=5.2, zorder=3,
                solid_capstyle='round')
        ax.plot([xa, xb], [ya, yb], color=self.THUMB_ROD, lw=3.0, zorder=4,
                solid_capstyle='round')
        for sp in self.supports:
            x, y = self.pts[sp['node']]
            ax.plot([x], [y], marker='^', ms=3.4, color='#222222', zorder=5)
        ax.set_aspect('equal', adjustable='datalim')
        ax.axis('off')

    #: The Rod detail grid: two columns of eight rows, sixteen rods to a
    #: sheet. Eight rows of 0.091 from y 0.905 end at 0.177, clear of the
    #: ISO title block (0.158). TWO columns because one gave each V and
    #: M panel 4.3 : 1 -- a long thin strip -- where the tab's own panels
    #: are 2.6 : 1; two columns bring them to 2.5 : 1 and halve the
    #: sheet count (37 bending rods: 5 sheets -> 3).
    DETAIL_ROWS = 8
    DETAIL_COLS = 2
    DETAIL_ROW_H = 0.091
    DETAIL_COL_X = (0.045, 0.515)

    def rod_detail(self):
        """One ROW per rod that bends -- its numbers, where it is, and its
        shear and moment along its length -- the way the tab's diagram
        pane lays them out.

        THE FIRST VERSION WAS CARDS, three across and two down, each with
        two charts a seventh of the sheet wide and a sixth tall. Six rods
        to a sheet with charts bigger than the truss drawing they belong
        to: the information was right and the proportions were not. The
        screen draws one row per member with the V and M panels at about
        2.6 : 1, and a row reads left to right like a table; this does the
        same, eight rods to a sheet.

        Each panel is scaled to ITS OWN rod, as on screen, so a lightly
        loaded rod's shape is still readable -- and its peak is written at
        the peak, so the size of the curve is never mistaken for the size
        of the force. It is only produced when something actually bends:
        on a pinned truss every row would be two flat lines (see `bends`).
        """
        def peak_of(i):
            if i >= len(self.diagrams):
                return 0.0
            d = self.diagrams[i]
            return max((abs(v) for v in list(d.get('M', ()))
                        + list(d.get('V', ()))), default=0.0)
        order = [i for i in sorted(range(len(self.rods)),
                                   key=lambda i: -peak_of(i))
                 if peak_of(i) > 1e-9]
        if not order:
            return []
        rows, ncol = self.DETAIL_ROWS, self.DETAIL_COLS
        per = rows * ncol
        pages = [order[i:i + per] for i in range(0, len(order), per)]
        top0 = 0.905
        for pno, chunk in enumerate(pages):
            fig = self.new_sheet('Rod detail' + (
                ' (%d/%d)' % (pno + 1, len(pages)) if len(pages) > 1 else ''))
            fig.text(0.05, 0.958, _wrap(
                'One row per rod that bends, worst first, down the left '
                'column and then the right. The thumbnail shows where the '
                'rod is; each diagram is scaled to its own rod, as on '
                'screen, with its largest value written at the peak. Rods '
                'with no shear or moment are in the Rods table.',
                165), fontsize=7.5, color=INK, va='top')
            used = (len(chunk) + rows - 1) // rows      # columns in use
            for col in range(used):
                cols = self._detail_columns(self.DETAIL_COL_X[col])
                x_lo = self.DETAIL_COL_X[col]
                x_hi = x_lo + 0.44
                # Column headings once per column, as a table has, instead
                # of a title over every small chart.
                for key, x, label in (
                        ('where', cols['thumb'][0], 'Where'),
                        ('V', cols['V'][0],
                         'Shear V (%s)' % self.u.lab('force')),
                        ('M', cols['M'][0],
                         'Moment M (%s)' % self.u.lab('moment'))):
                    fig.text(x, top0 + 0.006, label, fontsize=6.8,
                             fontweight='bold', va='bottom',
                             color={'V': '#c0392b',
                                    'M': '#2c5f9e'}.get(key, INK))
                _hrule(fig, top0, x_lo, x_hi)
                for k, ri in enumerate(chunk[col * rows:(col + 1) * rows]):
                    top = top0 - k * self.DETAIL_ROW_H
                    self._rod_row(fig, ri, top, cols)
                    _hrule(fig, top - self.DETAIL_ROW_H, x_lo, x_hi,
                           color='#e3e7ea')
            if used > 1:
                n_right = len(chunk) - rows
                _vrule(fig, 0.497,
                       top0 - max(rows, n_right) * self.DETAIL_ROW_H,
                       top0 + 0.02)
        return order

    @staticmethod
    def _detail_columns(x0=0.045):
        """x0, width of each part of a Rod detail row, figure fractions,
        for the column starting at `x0`. The V and M panels are 0.115 by
        0.063 -- 1.34 by 0.52 inches, 2.6 : 1, the tab's own proportion."""
        return {'text': (x0, 0.105), 'thumb': (x0 + 0.110, 0.072),
                'V': (x0 + 0.193, 0.115), 'M': (x0 + 0.320, 0.115)}

    def _rod_row(self, fig, ri, top, cols):
        rod = self.rods[ri]
        d = self.diagrams[ri]
        c = self.checks[ri] if ri < len(self.checks) else {}
        p = self.profiles.get(rod.get('profile', 'Default'), {})
        N = self.res['rod_res'][ri]['force']
        L = td.rod_length_m(self.nodes, rod)
        h = self.DETAIL_ROW_H
        x0 = cols['text'][0]

        over = c.get('checked') and not c.get('ok', True)
        fig.text(x0, top - 0.010, 'Rod %d' % ri, fontsize=8.6,
                 fontweight='bold', color=INK, va='top')
        if c.get('checked'):
            fig.text(x0 + 0.050, top - 0.012, 'use %.2f%s'
                     % (c['util'], ' OVER' if over else ''),
                     fontsize=6.4, va='top',
                     color='#b03a2e' if over else '#555')
        fig.text(x0, top - 0.030,
                 '%d–%d · %s %s' % (rod['a'], rod['b'],
                                    self.u.f('length', L, 2),
                                    self.u.lab('length')),
                 fontsize=6.0, color='#666', va='top')
        fig.text(x0, top - 0.045, (p.get('catalog') or 'no section')[:20],
                 fontsize=6.0, color='#666', va='top')
        fig.text(x0, top - 0.062, 'N %s %s'
                 % (self.u.f('force', _z(N), 2, sign=True),
                    self.u.lab('force')), fontsize=6.4, va='top', color=INK)

        tx, tw = cols['thumb']
        ax = fig.add_axes((tx, top - h + 0.012, tw, h - 0.024))
        self.thumbnail(ax, ri)

        xs = list(d.get('xs', ()))
        for key, face, edge, unit in (('V', '#e8a49c', '#c0392b', 'force'),
                                      ('M', '#9fc0e0', '#2c5f9e', 'moment')):
            cx, cw = cols[key]
            ax = fig.add_axes((cx, top - h + 0.014, cw, h - 0.028))
            self._mini_diagram(ax, xs, list(d.get(key, ())), face, edge,
                               unit)

    def _mini_diagram(self, ax, xs, vals, face, edge, unit):
        """One rod's V or M in the style of the tab's own panels: a light
        frame, the zero line, the filled curve, and the peak written at
        the peak. No tick labels -- at this size they were most of the
        ink and none of the information, and the values that matter are
        written on the curve."""
        for sp in ax.spines.values():
            sp.set_color('#dddddd')
            sp.set_linewidth(0.6)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.axhline(0, color='#bbbbbb', lw=0.6, zorder=1)
        if len(vals) < 2 or len(xs) != len(vals):
            return
        big = max((abs(v) for v in vals), default=0.0)
        if big <= 1e-12:
            ax.text(0.5, 0.5, 'zero', transform=ax.transAxes, fontsize=6,
                    color='#999', ha='center', va='center')
            return
        ax.fill_between(xs, vals, 0, color=face, alpha=0.75, lw=0, zorder=2)
        ax.plot(xs, vals, color=edge, lw=0.9, zorder=3)
        # A little headroom so the peak label never sits on the frame.
        ax.set_ylim(-big * 1.45, big * 1.45)
        ax.set_xlim(xs[0], xs[-1] if xs[-1] > xs[0] else xs[0] + 1.0)
        j = max(range(len(vals)), key=lambda k: abs(vals[k]))
        # Anchored to the side the peak is on. Centred on a peak at the
        # very end of the rod -- where a joint moment always is -- half
        # the label hung outside the frame.
        span = (xs[-1] - xs[0]) or 1.0
        f = (xs[j] - xs[0]) / span
        ha = 'left' if f < 0.15 else 'right' if f > 0.85 else 'center'
        ax.text(xs[j], vals[j] + (0.12 if vals[j] >= 0 else -0.12) * big,
                self.u.f(unit, vals[j], 2, sign=True), fontsize=6.2,
                color=edge, fontweight='bold', ha=ha,
                va='bottom' if vals[j] >= 0 else 'top', zorder=4)
        # The other end too, when it says something the peak does not:
        # for a rigid rod the two ends are the joint moments, which is
        # what a connection is designed for. NOT when it repeats the peak
        # -- a constant shear wrote the same number at both ends.
        for k, ha in ((0, 'left'), (len(vals) - 1, 'right')):
            if k == j or abs(vals[k]) <= 0.15 * big:
                continue
            if abs(vals[k] - vals[j]) <= 0.02 * big:
                continue
            ax.text(xs[k], vals[k] + (0.12 if vals[k] >= 0 else -0.12) * big,
                    self.u.f(unit, vals[k], 1, sign=True),
                    fontsize=5.8, color=edge, ha=ha,
                    va='bottom' if vals[k] >= 0 else 'top', zorder=4)

    # ── the step-by-step checks, grouped ──────────────────────────────────
    def explain(self):
        """The CIRSOC 301 check of the most used rods, two to a sheet.

        It was ONE ROD PER SHEET -- a column of monospace down the left
        half of a landscape A4 with the right half empty. Two columns
        side by side halve the page count and lose nothing, and each
        gets the thumbnail that says which rod it is talking about.
        """
        from apps.stereo import stereo_explain as sx
        ranked = sorted((i for i, c in enumerate(self.checks)
                         if c.get('checked') and c.get('util') is not None),
                        key=lambda i: -self.checks[i]['util'])
        chosen = ranked[:EXPLAIN_RODS]
        for k in range(0, len(chosen), 2):
            pair = chosen[k:k + 2]
            fig = self.new_sheet('Explain rod %s'
                                 % ' and '.join(str(i) for i in pair))
            if len(pair) > 1:
                fig.add_artist(__import__('matplotlib').lines.Line2D(
                    [0.5, 0.5], [0.17, 0.93], color='#ccd2d8',
                    linewidth=0.9, transform=fig.transFigure))
            for col, i in enumerate(pair):
                x0 = 0.05 + col * 0.47
                m = td.member_for(self.nodes, self.rods[i], self.profiles)
                text = sx.as_text(
                    sx.explain(m, self.res['rod_res'][i]['force'],
                               self.checks[i], length_m=m['_length_m']),
                    'Rod %d' % i)
                tx = fig.add_axes((x0, 0.815, 0.20, 0.10))
                self.thumbnail(tx, i)
                fig.text(x0 + 0.215, 0.910, 'Rod %d' % i, fontsize=11,
                         fontweight='bold', color=INK, va='top')
                fig.text(x0 + 0.215, 0.882, 'utilisation %.2f%s'
                         % (self.checks[i]['util'],
                            '' if self.checks[i]['ok'] else '  OVER'),
                         fontsize=8,
                         color=INK if self.checks[i]['ok'] else '#b03a2e',
                         va='top')
                fig.text(x0 + 0.215, 0.860,
                         self.checks[i].get('governing')
                         or self.checks[i].get('mode') or '',
                         fontsize=7, color='#777', va='top')
                # EXPLAIN_LINES and not "as many as fit": the RIGHT
                # column sits over the title block's x range, so a column
                # that runs past y 0.175 loses its last lines behind it --
                # and the left column, which does not, would then show
                # more of the same check than the right one. The overflow
                # note is part of the text so it cannot be the line that
                # falls off.
                lines = text.splitlines()
                if len(lines) > EXPLAIN_LINES:
                    # Kept SHORT and on one line: the note is monospace
                    # at the column's own width, and a long one ran
                    # straight across the divider into the other column.
                    lines = lines[:EXPLAIN_LINES - 1] + [
                        '... %d more lines; the verdict is in the heading.'
                        % (len(lines) - EXPLAIN_LINES + 1)]
                fig.text(x0, 0.790, '\n'.join(lines), fontsize=6.0,
                         family='DejaVu Sans Mono', va='top', color=INK)
        return chosen


def _wrap(text, chars):
    """Hard-wrap at `chars`, because matplotlib's own `wrap=True` wraps at
    the FIGURE edge and these sheets have a drawn frame 2.6 % inside it --
    so an auto-wrapped caption runs its first line over the frame rule and
    off the paper."""
    import textwrap
    return '\n'.join(textwrap.fill(para, chars)
                     for para in text.split('\n'))


def _z(v):
    """No "-0.00" in a table: a force below half a hundredth is zero."""
    return 0.0 if abs(v) < 0.005 else v


def _round_factor(k):
    """A magnification a reader can say: 1, 2 or 5 times a power of 10."""
    if k <= 1.0:
        return 1.0
    e = 10 ** math.floor(math.log10(k))
    for m in (5, 2, 1):
        if m * e <= k:
            return m * e
    return e


def _vrule(fig, x, y0, y1, color='#ccd2d8'):
    """`_hrule` the other way, for two graphs side by side."""
    from matplotlib.lines import Line2D
    line = Line2D([x, x], [y0, y1], color=color, linewidth=0.9,
                  transform=fig.transFigure, zorder=1)
    fig.add_artist(line)
    return line


def _hrule(fig, y, x0=0.04, x1=0.96, color='#ccd2d8'):
    """A divider across a sheet that carries more than one graph.

    A line and not just white space: without it the eye reads the axis
    label of the graph below as the caption of the picture above it.

    `transform=fig.transFigure` is not optional -- an artist added to a
    figure otherwise draws in display pixels and lands off the paper.
    """
    from matplotlib.lines import Line2D
    line = Line2D([x0, x1], [y, y], color=color, linewidth=0.9,
                  transform=fig.transFigure, zorder=1)
    fig.add_artist(line)
    return line


def _rect(x, y, w, h):
    from matplotlib.patches import Rectangle
    return Rectangle((x, y), w, h, color=SUPPORT, zorder=4)


def _table(ax, rows, over_col=None, fontsize=7):
    t = ax.table(cellText=rows[1:] or [[''] * len(rows[0])],
                 colLabels=rows[0], loc='upper left', cellLoc='left')
    t.auto_set_font_size(False)
    t.set_fontsize(fontsize)
    t.scale(1.0, 1.25)
    t.auto_set_column_width(list(range(len(rows[0]))))
    for (r, c), cell in t.get_celld().items():
        cell.set_edgecolor('#c8ccd0')
        if r == 0:
            cell.set_facecolor('#eef1f4')
            cell.set_text_props(fontweight='bold')
        elif over_col is not None and c == over_col and \
                cell.get_text().get_text() == 'OVER':
            cell.get_text().set_color('#b03a2e')
    return t


def buckling_for(nodes, rods, supports, loads, results, n_modes=3):
    """(the lowest `n_modes` buckling factors and shapes, the second-order
    curve) for the report, or ({'error': ...}, {'error': ...}).

    Computed here rather than taken from the app so a report written by a
    script has the same sheets as one exported from the window. It is one
    eigenproblem on a handful of degrees of freedom.
    """
    try:
        from . import truss_buckling as tb
    except Exception as exc:                    # noqa: BLE001
        err = {'error': 'Buckling needs numpy (%s).' % exc}
        return err, err
    try:
        result = tb.buckling(nodes, rods, supports, results, n_modes=n_modes)
    except Exception as exc:                    # noqa: BLE001
        result = {'error': 'The buckling analysis failed: %s' % exc}
    if 'error' in result:
        return result, {'error': result['error']}
    try:
        curve = tb.load_deflection(nodes, rods, supports, loads, results)
    except Exception as exc:                    # noqa: BLE001
        curve = {'error': 'The second-order curve failed: %s' % exc}
    return result, curve


def export_pdf(path, nodes, rods, supports, loads, results, checks,
               profiles, title='', units=None, buckling=True,
               diagrams=None, plates=None, plate_checks=None,
               stability=None, deform_scale=None):
    """Write the report to `path`.

    EVERYTHING ▶ ANALYZE PRODUCES, IN AS FEW SHEETS AS IT TAKES. What
    the button computes is the axial forces, the deflected shape, the
    reactions, the CIRSOC checks, the shear and moment diagrams, the
    fibre stress, the stability verdict, the plate checks and the score.
    Four of those were not in the report at all, and the ones that were
    had a sheet each whether or not they had anything to say.

    So the sheets are packed by SUBJECT rather than by data structure:
    the deflected shape, the elastic curve and the fibre stress are one
    sheet, because they are one question; the explain pages are two to a
    sheet instead of one; the per-rod cards are six to a sheet. And the
    three sheets that only make sense for a bending model -- Shear,
    Moment, Rod detail -- are produced only when something bends, which
    on a classic pinned truss is never. A Pratt truss's report is 9
    sheets; the same model with rigid rods is 12.

    `diagrams`, `plates`, `plate_checks` and `stability` come from the
    tab when it has them and are computed here when it does not, so a
    report written by a script carries the same sheets as one exported
    from the window.

    Returns {'sheets', 'headings', 'explained', 'deform_factor',
    'utilised', 'buckling', 'rod_detail'}.
    """
    from matplotlib.backends.backend_pdf import PdfPages
    if results is None:
        raise ValueError('analyse the truss first')
    if diagrams is None:
        try:
            from .truss_math import compute_diagrams
            diagrams = compute_diagrams(nodes, rods, loads, results)
        except Exception:
            diagrams = []
    if stability is None:
        try:
            from . import truss_stability as tstab
            stability = tstab.check(nodes, rods, supports, plates)
        except Exception:
            stability = None
    if plates and plate_checks is None:
        try:
            from . import truss_plates as tpl
            plate_checks = tpl.check_all(nodes, rods, plates, results)
        except Exception:
            plate_checks = None

    rep = _Report(nodes, rods, supports, loads, results, checks, profiles,
                  title, units, diagrams=diagrams, plates=plates,
                  plate_checks=plate_checks, stability=stability,
                  deform_scale=deform_scale)

    rep.geometry()
    rep.forces()
    rep.deflection_and_stress()
    rep.reactions()
    utilised = rep.utilisation()
    factors = []
    if buckling:
        result, curve = buckling_for(nodes, rods, supports, loads, results)
        factors = rep.buckling(result, curve)
    if rep.bends():
        rep.shear()
        rep.moment()
    joint_rows = rep.joints()
    rep.rod_table()
    rep.plate_table()
    detail = rep.rod_detail() if rep.bends() else []
    explained = rep.explain()

    # The cover LAST, because it reports on what the other sheets found
    # (the buckling factors above all), then moved to the front. Writing
    # it first meant it could only describe what was already known
    # before the report was built, which is how the stability line and
    # the plate checks came to be missing from it.
    rep.cover([h for _f, h in rep.sheets])
    rep.sheets.insert(0, rep.sheets.pop())
    rep.frame()
    with PdfPages(path) as pdf:
        d = pdf.infodict()
        d['Title'] = 'Truss report — %s' % (title or 'user model')
        d['Creator'] = 'Structural Simulator, Truss tab'
        for fig, _h in rep.sheets:
            pdf.savefig(fig)
    return {'sheets': len(rep.sheets), 'explained': explained,
            'deform_factor': rep.deform_factor,
            'utilised': utilised, 'buckling': factors,
            'rod_detail': detail, 'joints': joint_rows,
            'flex_points': len(rep.flex_points),
            'headings': [h for _f, h in rep.sheets]}
