"""The Truss tab's buckling window: the first buckling shapes with their
load factors, and the second-order load-deflection curve
(apps/truss/truss_buckling). A demonstration -- the rod checks are not
changed by it."""
import math
import tkinter as tk

from . import truss_buckling as tb

BG = 'white'
GREY = '#b8b8b8'
MODE = '#c0392b'
FIRST = '#888888'
SECOND = '#1a6bbd'


def _nice(x):
    """1, 2 or 5 times a power of ten, at least x."""
    if x <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 5, 10):
        if m * e >= x - 1e-12:
            return m * e
    return 10 * e


class TrussBucklingMixin:

    def _open_buckling(self):
        if self.results is None:
            self.status_var.set('▶ Analyze first: buckling starts from the '
                                'rod forces of a solved truss.')
            return None
        sups = self._active_supports()
        b = tb.buckling(self.nodes, self.rods, sups, self.results)
        if 'error' in b:
            self.status_var.set('Buckling: ' + b['error'])
            return None
        ld = tb.load_deflection(self.nodes, self.rods, sups,
                                self._design_loads(), self.results)
        win = tk.Toplevel(self.root)
        win.title('Buckling (in the plane of the truss)')
        win.configure(bg=BG)
        win.result, win.curve = b, ld
        top = tk.Frame(win, bg=BG)
        top.pack(fill='x', padx=8, pady=(8, 0))
        mode = tk.IntVar(master=win, value=0)
        for j, lam in enumerate(b['factors']):
            tk.Radiobutton(top, text='Mode %d: λ = %.2f' % (j + 1, lam),
                           variable=mode, value=j, bg=BG,
                           font=('Helvetica', 9),
                           command=lambda: draw()).pack(side='left')
        msg = tk.Label(win, text='', bg=BG, font=('Helvetica', 10, 'bold'),
                       justify='left', anchor='w', wraplength=760)
        msg.pack(fill='x', padx=8)
        body = tk.Frame(win, bg=BG)
        body.pack(padx=8, pady=4)
        shape = tk.Canvas(body, width=440, height=300, bg=BG,
                          highlightthickness=1, highlightbackground='#ccc')
        shape.grid(row=0, column=0, padx=(0, 6))
        plot = tk.Canvas(body, width=340, height=300, bg=BG,
                         highlightthickness=1, highlightbackground='#ccc')
        plot.grid(row=0, column=1)
        tk.Label(win, text='λ is the factor on the load as it stands: the '
                 'truss buckles in its own plane at λ times this load. '
                 'Elastic, ideal truss -- an upper bound. Buckling out of '
                 'the plane is the rod check\'s job (CIRSOC 301, minor '
                 'radius). The shape is drawn exaggerated: a buckling mode '
                 'has a shape, not a size.', bg=BG, fg='#666',
                 justify='left', wraplength=780,
                 font=('Helvetica', 8)).pack(fill='x', padx=8, pady=(0, 8))
        win.shape_canvas, win.plot_canvas, win.mode_var = shape, plot, mode

        def draw():
            j = mode.get()
            lam = b['factors'][j]
            where = b['modes'][j]['peak']
            what = ('rod %d bows' % where[1] if where[0] == 'mid'
                    else 'node %d moves most' % where[1])
            if lam < 1.0:
                msg.configure(fg='#b03a2e', text=(
                    'Mode %d: it buckles at %.2f × this load -- BEFORE the '
                    'full load is on (%s).' % (j + 1, lam, what)))
            else:
                msg.configure(fg='#1e7b34', text=(
                    'Mode %d: it buckles at %.2f × this load (%s).'
                    % (j + 1, lam, what)))
            self._draw_buckled(shape, b['modes'][j])
        draw()
        self._draw_load_deflection(plot, ld)
        return win

    def _draw_buckled(self, c, mode):
        c.delete('all')
        W, H, pad = int(c['width']), int(c['height']), 30
        xs = [p[0] for p in self.nodes]
        ys = [p[1] for p in self.nodes]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        span = max(x1 - x0, y1 - y0, 1e-9)
        amp = 0.10 * span                      # 10 % of the model's size
        s = min((W - 2 * pad) / max(x1 - x0 + 2 * amp, 1e-9),
                (H - 2 * pad) / max(y1 - y0 + 2 * amp, 1e-9))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

        def sc(x, y):
            return (W / 2 + (x - cx) * s, H / 2 + (y - cy) * s)
        for r in self.rods:
            (ax, ay), (bx, by) = self.nodes[r['a']], self.nodes[r['b']]
            c.create_line(*sc(ax, ay), *sc(bx, by), fill=GREY, width=2)
        moved = [(x + amp * dx, y + amp * dy)
                 for (x, y), (dx, dy) in zip(self.nodes, mode['nodes'])]
        for k, r in enumerate(self.rods):
            (ax, ay), (bx, by) = moved[r['a']], moved[r['b']]
            (mx0, my0) = ((self.nodes[r['a']][0] + self.nodes[r['b']][0]) / 2,
                          (self.nodes[r['a']][1] + self.nodes[r['b']][1]) / 2)
            dx, dy = mode['mids'][k]
            mx, my = mx0 + amp * dx, my0 + amp * dy
            c.create_line(*sc(ax, ay), *sc(mx, my), *sc(bx, by),
                          fill=MODE, width=2, smooth=True)
        for sp in self._active_supports():
            x, y = sc(*self.nodes[sp['node']])
            c.create_polygon(x, y, x - 6, y + 10, x + 6, y + 10,
                             fill='#555', outline='')
        c.create_text(8, H - 8, anchor='sw', fill='#666',
                      font=('Helvetica', 8),
                      text='grey: the truss   red: the buckled shape')

    def _draw_load_deflection(self, c, ld):
        c.delete('all')
        W, H = int(c['width']), int(c['height'])
        if 'error' in ld or not ld['factors']:
            c.create_text(W / 2, H / 2, width=W - 20, fill='#666',
                          text=ld.get('error', 'No curve.'))
            return
        L, R, T, B = 48, 12, 30, 36
        lcr = ld['lambda_cr']
        ymax = _nice(lcr * 1.05)
        xmax = _nice(max(max(ld['bow_mm']), max(ld['node_mm']),
                         max(ld['first_mm'])) * 1.05)

        def p(x, y):
            return (L + x / xmax * (W - L - R), H - B - y / ymax * (H - T - B))
        c.create_line(*p(0, 0), *p(xmax, 0), fill='#333')
        c.create_line(*p(0, 0), *p(0, ymax), fill='#333')
        for k in range(5):
            xv, yv = xmax * k / 4, ymax * k / 4
            x, y = p(xv, 0)
            c.create_line(x, y, x, y + 4, fill='#333')
            c.create_text(x, y + 6, anchor='n', font=('Helvetica', 7),
                          text='%g' % round(xv, 6))
            x, y = p(0, yv)
            c.create_line(x - 4, y, x, y, fill='#333')
            c.create_text(x - 6, y, anchor='e', font=('Helvetica', 7),
                          text='%g' % round(yv, 6))
        c.create_text((L + W - R) / 2, H - 4, anchor='s',
                      font=('Helvetica', 8), text='movement (mm)')
        c.create_text(4, 4, anchor='nw', font=('Helvetica', 8),
                      text='λ (× this load)')
        x0, y = p(0, lcr)
        x1, _ = p(xmax, lcr)
        c.create_line(x0, y, x1, y, fill=MODE, dash=(5, 3))
        c.create_text(x1 - 2, y - 2, anchor='se', fill=MODE,
                      font=('Helvetica', 8), text='buckles: λ = %.2f' % lcr)
        if lcr > 1.0 and ymax >= 1.0:
            x0, y = p(0, 1.0)
            x1, _ = p(xmax, 1.0)
            c.create_line(x0, y, x1, y, fill='#999', dash=(2, 3))
            c.create_text(x1 - 2, y - 2, anchor='se', fill='#777',
                          font=('Helvetica', 7), text='the full load')
        for key, col, dash, label in (
                ('first_mm', FIRST, (4, 3), 'first-order'),
                ('node_mm', SECOND, (), 'second-order'),
                ('bow_mm', MODE, (), 'bow, from L/1000')):
            pts = [q for xv, yv in zip(ld[key], ld['factors'])
                   for q in p(min(xv, xmax), yv)]
            if len(pts) >= 4:
                c.create_line(*pts, fill=col, width=2, dash=dash)
        for i, (col, label) in enumerate(((FIRST, 'node, first-order'),
                                          (SECOND, 'node, second-order'),
                                          (MODE, 'bow, from L/1000'))):
            y = T + 4 + 13 * i
            c.create_line(W - 130, y, W - 112, y, fill=col, width=2)
            c.create_text(W - 108, y, anchor='w', font=('Helvetica', 7),
                          text=label)
