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
APP_NAME = 'Truss'


def _xy(p):
    """Canvas pixels (y down) -> metres (y up)."""
    return p[0] / PX_PER_M, -p[1] / PX_PER_M


class _Report:

    def __init__(self, nodes, rods, supports, loads, results, checks,
                 profiles, title, units):
        from apps.stereo.stereo_reports import ReportUnits
        self.nodes, self.rods = nodes, rods
        self.supports, self.loads = supports, loads
        self.res, self.checks = results, checks or []
        self.profiles, self.title = profiles or {}, title
        self.u = units or ReportUnits()
        self.pts = [_xy(p) for p in nodes]
        xs = [p[0] for p in self.pts]
        ys = [p[1] for p in self.pts]
        self.box = (min(xs), max(xs), min(ys), max(ys))
        self.span = max(self.box[1] - self.box[0], self.box[3] - self.box[2],
                        1e-9)
        self.defl = td.deflection(nodes, supports, results['node_res'])
        self.score = ts.score(nodes, rods, results, self.checks)
        self.sheets = []

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
        y -= 0.07
        for k, v in rows:
            fig.text(0.06, y, k, fontsize=9, color='#7a8087')
            fig.text(0.24, y, v, fontsize=9, color=INK)
            y -= 0.034
        fig.text(0.62, 0.85, 'Contents', fontsize=11, fontweight='bold',
                 color=INK)
        for i, c in enumerate(contents):
            fig.text(0.62, 0.81 - 0.03 * i, '%d. %s' % (i + 2, c),
                     fontsize=9, color=INK)
        fig.text(0.06, 0.20, 'Results are an aid to a qualified '
                 'professional, who must check them. Rod checks to CIRSOC '
                 '301 as implemented; first-order analysis; joints and '
                 'connections are not checked here.', fontsize=7.5,
                 color='#666', wrap=True)

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

    def deformed(self):
        fig = self.new_sheet('Deformed shape')
        ax = self.drawing_axes(fig)
        nr = self.res['node_res']
        dmax_m = max((math.hypot(r['ux'], r['uy']) for r in nr),
                     default=0.0) / 1000.0
        k = (0.08 * self.span / dmax_m) if dmax_m > 1e-12 else 1.0
        k = _round_factor(k)
        moved = [(x + k * r['ux'] / 1000.0, y - k * r['uy'] / 1000.0)
                 for (x, y), r in zip(self.pts, nr)]
        self.draw_rods(ax, color=GHOST, width=1.0)
        self.draw_rods(ax, color='#1D9E75', width=1.8, pts=moved)
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
        line = ('Deflected shape (green) over the truss (grey). Geometry to '
                'scale; displacements magnified × %g.' % k)
        if d and d['span_m'] > 0:
            line += ('  Largest vertical deflection %s %s against the limit '
                     'L/%d = %s %s: %s.' % (
                         self.u.f('deflection', d['deflection_mm'], 2),
                         self.u.lab('deflection'), td.DEFLECTION_LIMIT,
                         self.u.f('deflection', d['limit_mm'], 1),
                         self.u.lab('deflection'),
                         'OK' if d['ok'] else 'TOO MUCH'))
        fig.text(0.05, 0.945, line, fontsize=8, color=INK)
        self.deform_factor = k

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
        pages = [body[i:i + ROWS_PER_SHEET]
                 for i in range(0, len(body), ROWS_PER_SHEET)] or [[]]
        for k, chunk in enumerate(pages):
            fig = self.new_sheet('Rods' + (' (%d/%d)' % (k + 1, len(pages))
                                           if len(pages) > 1 else ''))
            ax = fig.add_axes((0.05, 0.17, 0.90, 0.76))
            ax.axis('off')
            _table(ax, [head] + chunk, over_col=8)
        return len(pages)

    def explain(self):
        from apps.stereo import stereo_explain as sx
        ranked = sorted((i for i, c in enumerate(self.checks)
                         if c.get('checked') and c.get('util') is not None),
                        key=lambda i: -self.checks[i]['util'])
        for i in ranked[:EXPLAIN_RODS]:
            m = td.member_for(self.nodes, self.rods[i], self.profiles)
            text = sx.as_text(sx.explain(m, self.res['rod_res'][i]['force'],
                                         self.checks[i],
                                         length_m=m['_length_m']),
                              'Rod %d' % i)
            lines = text.splitlines()
            per = 58
            for k in range(0, max(len(lines), 1), per):
                fig = self.new_sheet('Explain rod %d' % i)
                fig.text(0.05, 0.93, '\n'.join(lines[k:k + per]),
                         fontsize=6.6, family='DejaVu Sans Mono', va='top',
                         color=INK)
        return ranked[:EXPLAIN_RODS]


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


def _rect(x, y, w, h):
    from matplotlib.patches import Rectangle
    return Rectangle((x, y), w, h, color=SUPPORT, zorder=4)


def _table(ax, rows, over_col=None):
    t = ax.table(cellText=rows[1:] or [[''] * len(rows[0])],
                 colLabels=rows[0], loc='upper left', cellLoc='left')
    t.auto_set_font_size(False)
    t.set_fontsize(7)
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
               profiles, title='', units=None, buckling=True):
    """Write the report to `path`. Returns {'sheets': n, 'explained':
    [rod...], 'deform_factor': k, 'utilised': [rod...], 'buckling':
    [lambda...]}.

    `buckling=False` leaves the buckling sheet out -- it costs an
    eigenproblem, which is wasted on a test that is not about it.
    """
    from matplotlib.backends.backend_pdf import PdfPages
    if results is None:
        raise ValueError('analyse the truss first')
    rep = _Report(nodes, rods, supports, loads, results, checks, profiles,
                  title, units)
    contents = ['Geometry', 'Axial forces', 'Deformed shape', 'Reactions',
                'Utilisation']
    if buckling:
        contents.append('Buckling (λ₁, λ₂, λ₃)')
    contents.append('Rods')
    if any(c.get('checked') for c in rep.checks):
        contents.append('Explain the most used rods')
    rep.cover(contents)
    rep.geometry()
    rep.forces()
    rep.deformed()
    rep.reactions()
    utilised = rep.utilisation()
    factors = []
    if buckling:
        result, curve = buckling_for(nodes, rods, supports, loads, results)
        factors = rep.buckling(result, curve)
    rep.rod_table()
    explained = rep.explain()
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
            'headings': [h for _f, h in rep.sheets]}
