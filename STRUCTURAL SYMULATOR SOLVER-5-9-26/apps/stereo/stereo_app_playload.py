"""The Stereo tab's load test: "Play load".

A load test tells the story of a structure: the load
rising from nothing, the rods' colours deepening, the shape sagging, and
the moment -- if there is one -- the first rod reaches its capacity. The
solve is linear, so every frame is the solved answer times the Load %
(see _load_frac): nothing is re-solved while it plays.
"""
import time
import tkinter as tk

from apps.stereo.stereo_app_constants import (
    COLOUR_NONE, COLOUR_FORCE, DEFORM_MODE_FORCE, PLAY_LOAD_SECONDS,
    PLAY_FRAME_MS)


class StereoPlayLoadMixin:

    def _play_load(self):
        """The toolbar's ▶ Play load; pressed while playing, it stops."""
        if getattr(self, '_play', None) is not None:
            self._stop_play_load(finished=False)
            return False
        if self.results is None and self.nodes:
            self._analyze()
        if self.results is None:
            if not self.nodes:
                self._set_status('Nothing to load-test yet: build a structure '
                                 'first.', 'error')
            return False
        self._play = {'t0': time.perf_counter(), 'after': None,
                      'gov': self._governing_rod(), 'crossed': False,
                      # put back as they were when it ends
                      'restore': (self.show_deformed.get(),
                                  self.deform_color_mode.get(),
                                  self.colour_mode.get())}
        # the shape sags and its rods' colours deepen: the sagging copy is
        # coloured by force, so both are seen in the one drawing
        self.show_deformed.set(True)
        self.deform_color_mode.set(DEFORM_MODE_FORCE)
        if self.colour_mode.get() == COLOUR_NONE:
            self.colour_mode.set(COLOUR_FORCE)
            self._on_colour_mode_change()
        self.play_btn.config(text='■ Stop')
        self._set_status('Load test: the load rises from 0 to 100 %.', 'idle')
        self._play_tick()
        return True

    def _play_tick(self):
        p = getattr(self, '_play', None)
        if p is None:
            return
        try:
            if not self.canvas.winfo_exists():
                self._play = None
                return
        except tk.TclError:
            self._play = None
            return
        if self.results is None:             # edited while it played
            self._stop_play_load(finished=False)
            return
        f = min(1.0, (time.perf_counter() - p['t0']) / PLAY_LOAD_SECONDS)
        self.load_fraction.set(int(round(100 * f)))
        self._draw()
        gov = p['gov']
        if gov and gov[1] > 1.0 and not p['crossed'] and f * gov[1] >= 1.0:
            p['crossed'] = True
            self._set_status('At %.0f %% of the load rod %d reaches its '
                             'capacity.' % (100.0 / gov[1], gov[0]), 'error')
        if f >= 1.0:
            self._stop_play_load(finished=True)
            return
        p['after'] = self.canvas.after(PLAY_FRAME_MS, self._play_tick)

    def _stop_play_load(self, finished=True):
        p = getattr(self, '_play', None)
        self._play = None
        if p is not None and p.get('after') is not None:
            try:
                self.canvas.after_cancel(p['after'])
            except tk.TclError:
                pass
        self.load_fraction.set(100)
        if p is not None:
            deformed, deform_mode, colour = p['restore']
            self.show_deformed.set(deformed)
            self.deform_color_mode.set(deform_mode)
            if self.colour_mode.get() != colour:
                self.colour_mode.set(colour)
                self._on_colour_mode_change()
        try:
            self.play_btn.config(text='▶ Play load')
        except (AttributeError, tk.TclError):
            pass
        self._draw()
        if not finished or p is None:
            self._set_status('Load test stopped -- the drawing is at 100 %.',
                             'idle')
            return
        self._set_status(*self._load_test_verdict(p['gov']))

    def _load_test_verdict(self, gov):
        """(status line, kind) for a load test that reached 100 %."""
        if gov is None:
            return ('Load test done: 100 % of the load is on. No rod has a '
                    'section to check.', 'idle')
        i, u = gov
        if u <= 1.0:
            return ('Load test passed: at 100 %% the most used rod, %d, is at '
                    '%.2f of its capacity.' % (i, u), 'ok')
        over = sum(1 for c in self.member_checks or ()
                   if c.get('checked') and (c.get('util') or 0.0) > 1.0)
        return ('Load test failed: rod %d reaches its capacity at %.0f %% of '
                'the load, and %d rod%s %s over at 100 %%.'
                % (i, 100.0 / u, over, '' if over == 1 else 's',
                   'is' if over == 1 else 'are'), 'error')
