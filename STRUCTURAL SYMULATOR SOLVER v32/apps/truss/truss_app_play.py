"""The Truss tab's "play and compare" layer: the Load % slider and
▶ Play load, the score with a best-so-far for each example, the example
library with its lessons, and design variants side by side.

Play load re-solves at each step rather than scaling one answer: a truss
solve is a few milliseconds, and re-solving keeps every number on screen
-- forces, deformed shape, reactions, utilisation -- the true one for that
share of the load, including the combined axial + bending check, which is
not proportional to the load.
"""
import copy
import math
import time
import tkinter as tk
from tkinter import messagebox

from common import CT, CC, CZ
from . import truss_examples as tx
from . import truss_score as ts

BG = '#f0f0ee'
CARD_BG = '#fffdf3'
PLAY_SECONDS = 3.0
PLAY_FRAME_MS = 60
MAX_VARIANTS = 3


class TrussPlayMixin:

    def _init_play(self, panel, after):
        self.load_pct = tk.IntVar(value=100)
        self._play = None
        self._slide_job = None
        self._example_key = None
        self.best_scores = {}           # example key -> score dict
        self.variants = []
        self._last_score = None
        self._lesson_card = None

        row = tk.Frame(panel, bg=BG)
        row.pack(fill='x', padx=8, pady=(2, 0), after=after)
        tk.Label(row, text='Load %', bg=BG,
                 font=('Helvetica', 9)).pack(side='left')
        self.load_scale = tk.Scale(
            row, from_=0, to=100, orient='horizontal', variable=self.load_pct,
            length=110, showvalue=True, bg=BG, bd=0, highlightthickness=0,
            font=('Helvetica', 8), command=self._on_load_slide)
        self.load_scale.pack(side='left')
        self.play_btn = tk.Button(row, text='▶ Play load',
                                  font=('Helvetica', 8),
                                  command=self._play_load)
        self.play_btn.pack(side='left', padx=(4, 0))
        self._bind_widget_tooltip(self.play_btn,
            'Raise the load from 0 to 100 % and watch the forces and the '
            'shape grow. The first rod to reach its capacity is named.')

        vrow = tk.Frame(panel, bg=BG)
        vrow.pack(fill='x', padx=8, pady=(2, 0), after=row)
        keep = tk.Button(vrow, text='Keep variant', font=('Helvetica', 8),
                         command=self._keep_variant)
        keep.pack(side='left')
        self._bind_widget_tooltip(keep,
            'Keep this solved design (up to %d) to compare it with others '
            'side by side.' % MAX_VARIANTS)
        tk.Button(vrow, text='Compare…', font=('Helvetica', 8),
                  command=self._compare_variants).pack(side='left',
                                                        padx=(4, 0))
        self.variant_var = tk.StringVar(value='')
        tk.Label(vrow, textvariable=self.variant_var, bg=BG, fg='#666',
                 font=('Helvetica', 8)).pack(side='left', padx=(6, 0))
        self._play_rows = (row, vrow)

    # ── the share of the load ─────────────────────────────────────────────
    def _load_factor(self):
        try:
            return max(0.0, min(1.0, self.load_pct.get() / 100.0))
        except (tk.TclError, AttributeError):
            return 1.0

    def _scaled_loads(self, loads):
        f = self._load_factor()
        if f >= 1.0:
            return loads
        return [dict(ld, fx=ld['fx'] * f, fy=ld['fy'] * f) for ld in loads]

    def _design_rods(self):
        """The rods as the solver should see them: their span loads scaled
        by the Load %. Copies only when something is scaled."""
        f = self._load_factor()
        if f >= 1.0:
            return self.rods
        out = []
        for r in self.rods:
            if r.get('udl') or r.get('point_loads'):
                r = dict(r)
                if r.get('udl'):
                    r['udl'] = r['udl'] * f
                if r.get('point_loads'):
                    r['point_loads'] = [dict(p, P=p.get('P', 0.0) * f)
                                        for p in r['point_loads']]
            out.append(r)
        return out

    def _load_note(self):
        f = self._load_factor()
        return '' if f >= 1.0 else ' (at %d %% of the load)' % round(100 * f)

    def _on_load_slide(self, _value=None):
        if self._play is not None:
            return
        if self._slide_job is not None:
            self.root.after_cancel(self._slide_job)
        self._slide_job = self.root.after(40, self._apply_slide)

    def _apply_slide(self):
        self._slide_job = None
        if self.results is not None or (self.live_var.get() and self.rods):
            self._run_analysis(quiet=True)

    # ── ▶ Play load ───────────────────────────────────────────────────────
    def _play_load(self):
        """Pressed while playing, it stops."""
        if self._play is not None:
            self._stop_play(finished=False)
            return False
        self.load_pct.set(100)
        if self.results is None and self.rods:
            self._run_analysis(quiet=True)
        if self.results is None:
            self.status_var.set('Nothing to load-test yet: build a truss and '
                                '▶ Analyze it first.')
            return False
        self._play = {'t0': time.perf_counter(), 'after': None,
                      'cross': None, 'prev': (0.0, 0.0)}
        self.play_btn.config(text='■ Stop')
        self._play_tick()
        return True

    def _play_tick(self):
        p = self._play
        if p is None:
            return
        f = min(1.0, (time.perf_counter() - p['t0']) / PLAY_SECONDS)
        self.load_pct.set(max(1, int(round(100 * f))))
        self._run_analysis(quiet=True)
        if self.results is None:            # it stopped standing up
            self._stop_play(finished=False)
            return
        from . import truss_design as td
        gov = td.governing(self.rod_checks or [])
        u = gov[1]['util'] if gov else 0.0
        fa = self._load_factor()
        if gov and u >= 1.0 and p['cross'] is None:
            f0, u0 = p['prev']
            # between the last two steps, where it reached 1.0
            fc = fa if u <= u0 else f0 + (1.0 - u0) * (fa - f0) / (u - u0)
            p['cross'] = (gov[0], fc)
        p['prev'] = (fa, u)
        if p['cross'] is not None:
            self.status_var.set('Load test: at about %.0f %% of the load rod '
                                '%d reaches its capacity.'
                                % (100 * p['cross'][1], p['cross'][0]))
        else:
            self.status_var.set('Load test: %d %% of the load.'
                                % self.load_pct.get())
        if f >= 1.0:
            self._stop_play(finished=True)
            return
        p['after'] = self.root.after(PLAY_FRAME_MS, self._play_tick)

    def _stop_play(self, finished=True):
        p, self._play = self._play, None
        if p is not None and p.get('after') is not None:
            try:
                self.root.after_cancel(p['after'])
            except tk.TclError:
                pass
        self.play_btn.config(text='▶ Play load')
        if self.load_pct.get() != 100:
            self.load_pct.set(100)
            if self.results is not None:
                self._run_analysis(quiet=True)
        if not finished or p is None:
            return
        from . import truss_design as td
        gov = td.governing(self.rod_checks or [])
        if p['cross'] is not None:
            self.status_var.set('Load test done: rod %d reached its capacity '
                                'at about %.0f %% of the load.'
                                % (p['cross'][0], 100 * p['cross'][1]))
        elif gov:
            u = gov[1]['util']
            self.status_var.set('Load test done: no rod reached its capacity. '
                                'The most used, rod %d, is at %.2f -- about '
                                '%.1f × this load would bring it there.'
                                % (gov[0], u, 1 / u if u > 1e-9 else 0))
        else:
            self.status_var.set('Load test done. Give the rod families steel '
                                'sections to see when a rod would fail.')

    # ── the score ─────────────────────────────────────────────────────────
    def _score_summary(self):
        """A line under the results; records the example's best design."""
        s = ts.score(self.nodes, self.rods, self.results, self.rod_checks,
                     self_weight_on=self.self_weight.get())
        self._last_score = s
        line = 'Score: ' + ts.describe(s) + self._load_note()
        key = self._example_key
        if key and self._load_factor() >= 1.0:
            best = self.best_scores.get(key)
            if ts.better(s, best):
                if best is not None:
                    line += '\nNew best for this example (was %.0f kg).' \
                            % best['mass_kg']
                self.best_scores[key] = dict(s)
            elif best is not None:
                line += '\nBest for this example so far: %.0f kg.' \
                        % best['mass_kg']
        self.res_var.set(self.res_var.get() + '\n' + line)
        return s

    # ── the example library ───────────────────────────────────────────────
    def _open_examples(self):
        win = tk.Toplevel(self.root)
        win.title('Examples')
        win.configure(bg='#f5f5f3')
        left = tk.Frame(win, bg='#f5f5f3')
        left.pack(side='left', fill='y', padx=(10, 4), pady=10)
        lb = tk.Listbox(left, height=len(tx.EXAMPLES), width=26,
                        exportselection=False, font=('Helvetica', 10))
        lb.pack(fill='y', expand=True)
        for _k, title, _b in tx.EXAMPLES:
            lb.insert('end', title)
        right = tk.Frame(win, bg='#f5f5f3')
        right.pack(side='left', fill='both', expand=True, padx=(4, 10),
                   pady=10)
        text = tk.Label(right, text='', bg='#f5f5f3', justify='left',
                        anchor='nw', wraplength=340, font=('Helvetica', 9))
        text.pack(fill='both', expand=True)

        def show(_e=None):
            sel = lb.curselection()
            if not sel:
                return
            key = tx.EXAMPLES[sel[0]][0]
            text.configure(text=self._lesson_text(key))

        def load():
            sel = lb.curselection()
            if not sel:
                messagebox.showinfo('Examples', 'Pick an example first.',
                                    parent=win)
                return
            self._load_library_example(tx.EXAMPLES[sel[0]][0])
            win.destroy()
        lb.bind('<<ListboxSelect>>', show)
        lb.bind('<Double-Button-1>', lambda _e: load())
        tk.Button(right, text='Load this example', bg='#1a6bbd', fg='white',
                  font=('Helvetica', 10, 'bold'), relief='flat',
                  command=load).pack(anchor='e', pady=(6, 0))
        lb.selection_set(0)
        show()
        win.listbox, win.load = lb, load
        return win

    def _lesson_text(self, key):
        lesson = tx.LESSONS[key]
        lines = [lesson['goal'], '']
        lines += ['%d. %s' % (i + 1, q)
                  for i, q in enumerate(lesson['questions'])]
        best = self.best_scores.get(key)
        if best:
            lines += ['', 'Your best passing design: %.0f kg.'
                      % best['mass_kg']]
        return '\n'.join(lines)

    def _load_library_example(self, key):
        title, model, _lesson = tx.get(key)
        self._push_undo('load example')
        self._clear_all(push_undo=False)
        self.nodes = list(model['nodes'])
        self.rods = model['rods']
        self.profiles = model['profiles']
        self.supports = model['supports']
        self.loads = model['loads']
        self._example_key = key
        self._refresh_profile_combo()
        self._draw()
        self._show_lesson(key)
        self.status_var.set('%s loaded — click ▶ Analyze.' % title)

    # ── the lesson card, over the drawing ─────────────────────────────────
    def _show_lesson(self, key=None):
        key = key or self._example_key
        self._hide_lesson()
        if not key:
            return None
        title = next(t for k, t, _b in tx.EXAMPLES if k == key)
        card = tk.Frame(self.zc.canvas, bg=CARD_BG, bd=1, relief='solid')
        head = tk.Frame(card, bg=CARD_BG)
        head.pack(fill='x')
        tk.Label(head, text=title, bg=CARD_BG, fg='#1a6bbd',
                 font=('Helvetica', 10, 'bold')).pack(side='left', padx=6)
        tk.Button(head, text='×', relief='flat', bg=CARD_BG, bd=0,
                  command=self._hide_lesson).pack(side='right')
        tk.Label(card, text=self._lesson_text(key), bg=CARD_BG, fg='#333',
                 justify='left', anchor='w', wraplength=330,
                 font=('Helvetica', 9)).pack(fill='x', padx=6, pady=(0, 6))
        card.place(relx=1.0, x=-8, y=8, anchor='ne')
        self._lesson_card = card
        return card

    def _hide_lesson(self):
        card, self._lesson_card = self._lesson_card, None
        if card is not None:
            try:
                card.destroy()
            except tk.TclError:
                pass

    def _forget_example(self):
        """Clear and Import start a model that is no longer the example."""
        self._example_key = None
        self._hide_lesson()

    # ── design variants ───────────────────────────────────────────────────
    def _keep_variant(self):
        if self.results is None:
            self.status_var.set('▶ Analyze first: a variant is a solved '
                                'design.')
            return None
        if self._load_factor() < 1.0:
            self.status_var.set('Set the Load % back to 100 before keeping a '
                                'variant, so variants compare at full load.')
            return None
        s = ts.score(self.nodes, self.rods, self.results, self.rod_checks,
                     self_weight_on=self.self_weight.get())
        from . import truss_design as td
        d = td.deflection(self.nodes, self._active_supports(),
                          self.results['node_res'])
        self._variant_n = getattr(self, '_variant_n', 0) + 1
        v = {'name': 'Variant %d' % self._variant_n,
             'nodes': list(self.nodes),
             'rods': copy.deepcopy(self.rods),
             'supports': copy.deepcopy(self._active_supports()),
             'loads': copy.deepcopy(self._design_loads()),
             'forces': [r['force'] for r in self.results['rod_res']],
             'score': s, 'deflection': d}
        self.variants.append(v)
        dropped = None
        if len(self.variants) > MAX_VARIANTS:
            dropped = self.variants.pop(0)['name']
        self.variant_var.set('%d kept' % len(self.variants))
        self.status_var.set('Kept as %s.%s' % (
            v['name'], ' (%s dropped: %d at most.)' % (dropped, MAX_VARIANTS)
            if dropped else ''))
        return v

    def _compare_variants(self):
        if len(self.variants) < 2:
            messagebox.showinfo('Compare variants',
                                'Keep at least two solved designs first '
                                '(Keep variant).')
            return None
        win = tk.Toplevel(self.root)
        win.title('Variants side by side')
        win.configure(bg='white')
        vs = self.variants
        xs = [p[0] for v in vs for p in v['nodes']]
        ys = [p[1] for v in vs for p in v['nodes']]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        W, H, pad = 380, 260, 30
        # one scale and one force range for all of them
        scale = min((W - 2 * pad) / max(x1 - x0, 1e-9),
                    (H - 2 * pad) / max(y1 - y0, 1e-9))
        nmax = max((abs(f) for v in vs for f in v['forces']), default=0) or 1
        win.canvases = []
        best = min((v for v in vs if v['score'].get('passes')),
                   key=lambda v: v['score']['mass_kg'], default=None)
        for col, v in enumerate(vs):
            frame = tk.Frame(win, bg='white')
            frame.grid(row=0, column=col, padx=6, pady=6, sticky='n')
            title = v['name'] + ('  ★ lightest that passes'
                                 if v is best else '')
            tk.Label(frame, text=title, bg='white',
                     font=('Helvetica', 10, 'bold')).pack(anchor='w')
            c = tk.Canvas(frame, width=W, height=H, bg='white',
                          highlightthickness=1, highlightbackground='#ccc')
            c.pack()
            self._draw_variant(c, v, x0, y1, scale, pad, H, nmax)
            d = v['deflection']
            lines = [ts.describe(v['score'])]
            if d and d['span_m'] > 0:
                lines.append('Deflection %.1f mm = L/%s' % (
                    d['deflection_mm'],
                    '%.0f' % d['L_over'] if d['L_over'] < 1e7 else '∞'))
            tk.Label(frame, text='\n'.join(lines), bg='white', fg='#333',
                     justify='left', wraplength=W,
                     font=('Helvetica', 9)).pack(anchor='w')
            win.canvases.append(c)
        tk.Label(win, text='Same scale and same force range in every view: '
                 'red pulls, blue pushes, thicker carries more (largest '
                 '%.1f kN).' % nmax, bg='white', fg='#666',
                 font=('Helvetica', 8)).grid(row=1, column=0,
                                             columnspan=len(vs), sticky='w',
                                             padx=6, pady=(0, 6))
        return win

    @staticmethod
    def _draw_variant(c, v, x0, y1, scale, pad, H, nmax):
        def s(p):
            return (pad + (p[0] - x0) * scale, H - pad - (y1 - p[1]) * scale)
        for r, f in zip(v['rods'], v['forces']):
            (ax, ay), (bx, by) = s(v['nodes'][r['a']]), s(v['nodes'][r['b']])
            col = CT if f > 0.01 else CC if f < -0.01 else CZ
            w = 1 + 5 * abs(f) / nmax
            c.create_line(ax, ay, bx, by, fill=col, width=w,
                          dash=() if abs(f) > 0.01 else (4, 3))
        for sp in v['supports']:
            x, y = s(v['nodes'][sp['node']])
            c.create_polygon(x, y, x - 6, y + 10, x + 6, y + 10,
                             fill='#555', outline='')
        for ld in v['loads']:
            x, y = s(v['nodes'][ld['node']])
            m = math.hypot(ld['fx'], ld['fy'])
            if m < 1e-9:
                continue
            ux, uy = ld['fx'] / m, ld['fy'] / m
            c.create_line(x - 22 * ux, y - 22 * uy, x, y, arrow='last',
                          fill='#222', width=1.5)
