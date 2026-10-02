"""The Stereo tab's buckling demonstrations (stereo_buckling): the shapes
the structure buckles into, drawn moving, and the second-order load-
deflection curve in a window of its own. Analyse → Buckling.

Demonstrations: the code checks stay first-order; nothing here changes a
utilisation.
"""
import time
import tkinter as tk

from apps.stereo import stereo_buckling as sb
from apps.stereo import stereo_math as sm
from apps.stereo.stereo_app_constants import BUCKLE_COLOR, MECH_AMPLITUDE_FRAC


class StereoBucklingMixin:

    def _buckling_key(self):
        return (self._mech_signature(), id(self.results))

    def _buckling_result(self):
        """The buckling analysis of the current solve, cached."""
        if self.results is None and self.nodes:
            self._analyze()
        if self.results is None:
            return None
        key = self._buckling_key()
        cached = getattr(self, '_buckling_cache', None)
        if cached is not None and cached[0] == key:
            return cached[1]
        self._set_status('Finding how it buckles…', 'idle')
        try:
            self.canvas.update_idletasks()
        except tk.TclError:
            pass
        loads, member_loads = self._solve_loads()
        got = sb.buckling(self.nodes, self.members, loads,
                          self._active_supports(), panels=self.panels,
                          member_loads=member_loads, n_modes=3,
                          results=self.results)
        self._buckling_cache = (key, got)
        return got

    def _show_buckling(self):
        """Analyse → Buckling modes: draw mode 1 moving; pressed again, the
        next; after the last it stops. Returns True while one is shown."""
        got = self._buckling_result()
        if got is None:
            return False
        if 'error' in got:
            self._stop_mechanism()
            self._set_status('Buckling: ' + got['error'], 'error')
            return False
        cur = getattr(self, '_mech', None)
        which = 0
        if cur is not None and cur.get('kind') == 'buckling' and \
                cur.get('key') == self._buckling_key():
            which = cur['which'] + 1
            if which >= len(got['factors']):
                self._stop_mechanism()
                self._set_status('Stopped -- that was every buckling shape '
                                 'found.', 'idle')
                return False
        self._stop_mechanism(redraw=False)
        mode = got['modes'][which]
        lam = got['factors'][which]
        span = max((max(p[k] for p in self.nodes)
                    - min(p[k] for p in self.nodes) for k in range(3)),
                   default=1.0)
        kind, at = mode['peak']
        if kind == 'mid':
            L = sm.member_vector(self.nodes, self.members[at])[3]
        else:
            L = max((sm.member_vector(self.nodes, m)[3] for m in self.members
                     if at in (m['a'], m['b'])), default=span)
        n = len(got['factors'])
        caption = ('Buckling shape %d of %d: it buckles at %.2f × this load '
                   '(elastic, ideal structure)%s.'
                   % (which + 1, n, lam,
                      '; Buckling shapes again for the next' if which + 1 < n
                      else ''))
        self._mech = {'kind': 'buckling', 'shape': mode['nodes'],
                      'mids': mode['mids'], 'count': n, 'which': which,
                      'axis': None, 'color': BUCKLE_COLOR,
                      'caption': caption, 'factor': lam,
                      'key': self._buckling_key(),
                      'sig': self._mech_signature(),
                      't0': time.perf_counter(), 'frame': 0, 'after': None,
                      'amp': min(MECH_AMPLITUDE_FRAC * 0.5 * max(span, 1.0),
                                 0.25 * L)}
        self._set_status(caption, 'idle')
        # bring the place that buckles first to the middle of the view: in
        # a big grid one bowing rod is otherwise easy to miss
        if kind == 'mid':
            m = self.members[at]
            pa, pb = self.nodes[m['a']], self.nodes[m['b']]
            self._center_on_point(*((pa[k] + pb[k]) / 2.0 for k in range(3)))
        else:
            self._center_on_point(*self.nodes[at])
        self._draw()
        self._mech_tick()
        return True

    # ── the load-deflection curve ─────────────────────────────────────────
    def _show_load_deflection(self):
        """Analyse → Load–deflection curve: a window with the second-order
        curves (stereo_buckling.load_deflection). Returns the window."""
        if self.results is None and self.nodes:
            self._analyze()
        if self.results is None:
            return None
        self._set_status('Stepping the load up to the buckling load…', 'idle')
        try:
            self.canvas.update_idletasks()
        except tk.TclError:
            pass
        loads, member_loads = self._solve_loads()
        data = sb.load_deflection(self.nodes, self.members, loads,
                                  self._active_supports(), panels=self.panels,
                                  member_loads=member_loads,
                                  results=self.results)
        if 'error' in data:
            self._set_status('Load–deflection: ' + data['error'], 'error')
            return None
        old = getattr(self, '_ld_win', None)
        try:
            if old is not None and old.winfo_exists():
                old.destroy()
        except tk.TclError:
            pass
        win = tk.Toplevel(self.root)
        win.title('Second-order load–deflection')
        self._ld_win = win
        c = tk.Canvas(win, width=680, height=440, bg='#ffffff',
                      highlightthickness=0)
        c.pack(fill='both', expand=True)
        draw_load_deflection(c, 680, 440, data)
        win._canvas, win._data = c, data
        where = ('the middle of rod %d' % data['where'][1]
                 if data['where'][0] == 'mid' else 'node %d' % data['where'][1])
        tk.Label(win, justify='left', wraplength=660, font=('Helvetica', 9),
                 text=('Purple: %s, the first thing to buckle, given an '
                       'initial bow of %.1f mm (L/1000) in its buckling '
                       'shape. It grows as (λ/λcr)/(1 − λ/λcr) and runs away '
                       'at λcr = %.2f. Red: node %d, the node that moves most '
                       'under the load, second-order; grey: the same node '
                       'first-order, a straight line. A demonstration: the '
                       'code checks stay first-order.'
                       % (where, data['bow0_mm'], data['lambda_cr'],
                          data['node']))).pack(padx=10, pady=(0, 6))
        tk.Button(win, text='Close', command=win.destroy).pack(pady=(0, 8))
        self._set_status('Second-order: it buckles at %.2f × this load.'
                         % data['lambda_cr'], 'idle')
        return win


def draw_load_deflection(c, w, h, data):
    """Load factor (up) against deflection (across), MASTAN2's way round."""
    left, right, top, bottom = 64, w - 24, 34, h - 52
    lam_cr = data['lambda_cr']
    ymax = lam_cr * 1.08
    xs = data['bow_mm'] + data['node_mm'] + data['first_mm']
    xmax = max(max(xs, default=1.0), 1e-6) * 1.05

    def X(v):
        return left + (right - left) * v / xmax

    def Y(v):
        return bottom - (bottom - top) * v / ymax
    c.create_text(w / 2, 14, text='Second-order load–deflection',
                  font=('Helvetica', 11, 'bold'))
    c.create_line(left, bottom, right, bottom, fill='#333')
    c.create_line(left, bottom, left, top, fill='#333')
    for k in range(6):
        v = xmax * k / 5
        c.create_line(X(v), bottom, X(v), bottom + 4, fill='#333')
        c.create_text(X(v), bottom + 14, text='%.0f' % v,
                      font=('Helvetica', 8))
        lv = ymax * k / 5
        c.create_line(left - 4, Y(lv), left, Y(lv), fill='#333')
        c.create_text(left - 8, Y(lv), text='%.2f' % lv, anchor='e',
                      font=('Helvetica', 8))
    c.create_text((left + right) / 2, h - 18, text='deflection (mm)',
                  font=('Helvetica', 9))
    c.create_text(16, (top + bottom) / 2, text='load factor λ', angle=90,
                  font=('Helvetica', 9))
    c.create_line(left, Y(lam_cr), right, Y(lam_cr), fill=BUCKLE_COLOR,
                  dash=(5, 3))
    c.create_text(right, Y(lam_cr) - 8, anchor='e', fill=BUCKLE_COLOR,
                  text='buckles at λcr = %.2f' % lam_cr,
                  font=('Helvetica', 9, 'bold'))
    if lam_cr > 1.0:
        c.create_line(left, Y(1.0), right, Y(1.0), fill='#999', dash=(2, 3))
        c.create_text(right, Y(1.0) - 8, anchor='e', fill='#666',
                      text='this load, λ = 1', font=('Helvetica', 8))
    for key, colour, width, dash in (('first_mm', '#9aa0a6', 1, (4, 3)),
                                     ('node_mm', '#c0392b', 2, None),
                                     ('bow_mm', BUCKLE_COLOR, 2, None)):
        pts = []
        for lam, v in zip(data['factors'], data[key]):
            pts += [X(v), Y(lam)]
        if len(pts) >= 4:
            c.create_line(*pts, fill=colour, width=width, dash=dash,
                          tags='curve_' + key)
