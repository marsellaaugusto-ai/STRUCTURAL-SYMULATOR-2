"""The Stereo tab's mechanism animation.

"Singular stiffness matrix" is the most common thing a student sees and
the least helpful: it says THAT the model cannot stand, not how. The solver
already finds the motion that meets no stiffness (stereo_math
.mechanism_mode); this draws it, the loose part swinging in orange over the
model at rest, so the missing rod or support is the one you can see it
needs. It runs while the model stays as it is and stops the moment it is
edited or a solve succeeds.
"""
import math
import time
import tkinter as tk

from apps.stereo import stereo_math as sm
from apps.stereo.stereo_app_constants import (
    MECH_COLOR, MECH_AMPLITUDE_FRAC, MECH_FRAME_MS, MECH_PERIOD_S)


class StereoMechanismMixin:

    def _mech_signature(self):
        """The model as far as how it can move goes."""
        return hash(repr((self.nodes,
                          [(m['a'], m['b'], m.get('conn', 'pin'))
                           for m in self.members],
                          self._active_supports())))

    def _show_mechanism(self, which=None, quiet=False):
        """Start drawing the model moving, or -- pressed again while it
        moves -- the next independent way it can move; after the last one
        it stops. Returns True while something is shown moving."""
        cur = getattr(self, '_mech', None)
        sig = self._mech_signature() if self.nodes else None
        if which is None:
            if cur is not None and cur['sig'] == sig:
                which = cur['which'] + 1
                if which >= cur['count']:
                    self._stop_mechanism()
                    self._set_status('Stopped -- that was every way it '
                                     'can move.', 'idle')
                    return False
            else:
                which = 0
        try:
            mode = sm.mechanism_mode(self.nodes, self.members,
                                     self._active_supports(),
                                     panels=self.panels, which=which)
        except Exception:                   # a diagnosis must never crash
            mode = None
        self._stop_mechanism(redraw=False)
        if mode is None:
            if not quiet:
                self._set_status(
                    'It cannot move: every way it could go meets a rod or '
                    'a support.' if self.nodes else 'Nothing is built yet.',
                    'ok' if self.nodes else 'idle')
            self._draw()
            return False
        span = max((max(p[k] for p in self.nodes) - min(p[k] for p in self.nodes)
                    for k in range(3)), default=1.0)
        mode.update(sig=sig, t0=time.perf_counter(), frame=0, after=None,
                    amp=MECH_AMPLITUDE_FRAC * max(span, 1.0))
        self._mech = mode
        if not quiet:
            self._set_status(self._mech_caption(), 'error')
        self._mech_tick()
        return True

    def _mech_caption(self):
        mode = getattr(self, '_mech', None)
        if mode is None:
            return ''
        if mode.get('caption'):
            return mode['caption']
        if mode['kind'] == 'rigid':
            if not self._active_supports():
                return ('It stands on nothing, so it falls (orange): give it '
                        'supports in Support mode.')
            return ('Nothing holds it along %s, so it slides that way as one '
                    'piece (orange): restrain %s at a support.'
                    % (mode['axis'], mode['axis']))
        more = (' -- 1 of %d ways; "Show how it can move" again for the next'
                % mode['count'] if mode['count'] > 1 else '')
        if mode['count'] > 1 and mode['which']:
            more = (' -- %d of %d ways; "Show how it can move" again for the '
                    'next' % (mode['which'] + 1, mode['count']))
        return ('Orange: how it moves with no stiffness%s. Brace it with a '
                'rod or hold it with a support.' % more)

    def _mech_tick(self):
        mode = getattr(self, '_mech', None)
        if mode is None:
            return
        try:
            if not self.canvas.winfo_exists():
                self._mech = None
                return
        except tk.TclError:
            self._mech = None
            return
        mode['frame'] += 1
        # the model as solved, or edited since: either way not this motion.
        # The node count every frame (a crane lift adds nodes, and the next
        # frame must not draw the old shape onto them); the full signature,
        # which costs more, every tenth.
        # A buckling mode is OF a solve, so it is the opposite: it goes
        # when the solve does.
        stale = (self.results is None if mode['kind'] == 'buckling'
                 else self.results is not None)
        if stale or len(mode['shape']) != len(self.nodes) \
                or (mode['frame'] % 10 == 0
                    and mode['sig'] != self._mech_signature()):
            self._stop_mechanism()
            return
        t = time.perf_counter() - mode['t0']
        phase = 2.0 * math.pi * t / MECH_PERIOD_S
        if mode['kind'] == 'rigid' and mode['axis'] == 'z':
            # it falls, and comes back to fall again -- never up
            self._draw_mechanism(mode['amp'] * 1.5
                                 * (1.0 - math.cos(phase)) / 2.0)
        else:
            self._draw_mechanism(mode['amp'] * math.sin(phase))
        mode['after'] = self.canvas.after(MECH_FRAME_MS, self._mech_tick)

    def _draw_mechanism(self, a):
        """The moving part at offset `a` (metres, times the mode shape),
        through the same projection as the model at rest."""
        mode = self._mech
        c = self.canvas
        c.delete('mechanism')
        if len(mode['shape']) != len(self.nodes) or any(
                m['a'] >= len(self.nodes) or m['b'] >= len(self.nodes)
                for m in self.members):
            return
        self._screen_positions()                # fills the centring cache
        cx, cy = self._screen_cache[2]
        shape = mode['shape']
        pts = []
        for (x, y, z), (dx, dy, dz) in zip(self.nodes, shape):
            px, py, _ = self._project(x + a * dx, y + a * dy, z + a * dz)
            pts.append(self.zc.w2s((px - cx) * self.PX_PER_M,
                                   (py - cy) * self.PX_PER_M))
        colour = mode.get('color', MECH_COLOR)
        moving = [dx * dx + dy * dy + dz * dz > 0.05 ** 2
                  for dx, dy, dz in shape]
        # A buckling shape also moves each rod's MIDDLE: a rod that bows
        # between two joints that stay put is drawn bent through it.
        mids = mode.get('mids') or {}
        for i, m in enumerate(self.members):
            mid = mids.get(i)
            bows = mid is not None and (mid[0] ** 2 + mid[1] ** 2
                                        + mid[2] ** 2) > 0.05 ** 2
            if not (moving[m['a']] or moving[m['b']] or bows):
                continue
            (x0, y0), (x1, y1) = pts[m['a']], pts[m['b']]
            if mid is not None:
                pa, pb = self.nodes[m['a']], self.nodes[m['b']]
                mx, my, mz = ((pa[k] + pb[k]) / 2.0 + a * mid[k]
                              for k in range(3))
                px, py, _ = self._project(mx, my, mz)
                xm, ym = self.zc.w2s((px - cx) * self.PX_PER_M,
                                     (py - cy) * self.PX_PER_M)
                c.create_line(x0, y0, xm, ym, x1, y1, fill=colour,
                              width=3 if bows else 2, smooth=True,
                              tags='mechanism')
            else:
                c.create_line(x0, y0, x1, y1, fill=colour, width=2,
                              tags='mechanism')
        for k, mv in enumerate(moving):
            if mv:
                x, y = pts[k]
                c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=colour,
                              outline='', tags='mechanism')
        # bottom centre: the legend and the view cube hold the top corners
        c.create_text(c.winfo_width() / 2.0, c.winfo_height() - 26,
                      anchor='s', justify='center',
                      text=self._mech_caption(), fill=colour,
                      font=('Helvetica', 9, 'bold'), tags='mechanism',
                      width=max(300, c.winfo_width() - 640))

    def _stop_mechanism(self, redraw=True):
        mode = getattr(self, '_mech', None)
        self._mech = None
        if mode is not None and mode.get('after') is not None:
            try:
                self.canvas.after_cancel(mode['after'])
            except tk.TclError:
                pass
        try:
            self.canvas.delete('mechanism')
        except tk.TclError:
            pass
