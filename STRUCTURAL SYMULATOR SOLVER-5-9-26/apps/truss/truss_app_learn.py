"""The Truss tab's teaching aids, kept out of truss_app.py's 5,000 lines.

  * Simple / Advanced -- Simple (the default) shows what a first truss
    needs: material, selection, connection type and Analyze. Advanced adds
    the CAD bar, construction geometry, arrays, plates and rod families.
    Nothing is removed; it is one tick away.
  * The stability line under Analyze -- determinate, indeterminate to
    degree n, or a mechanism, kept current as the model is edited
    (apps/truss/truss_stability).
  * A mechanism is drawn moving when Analyze fails on it, with the joints
    that move ringed and a sentence saying what is missing.
  * The support sandbox -- right-click a support to switch it off and
    re-solve; right-click again to bring it back. The support itself is
    never deleted.
  * Live -- small models re-solve a quarter-second after every edit.
  * Zero-force rods are drawn dashed, and can be hidden.
"""
import math
import tkinter as tk

from . import truss_stability

BG = '#f0f0ee'
MECH_COLOR = '#d35400'
MECH_FRAME_MS = 40
LIVE_DELAY_MS = 250
LIVE_MAX_RODS = 300
HINT_FOLD_CHARS = 110       # a grey explanation longer than this folds


class TrussLearnMixin:

    # ── construction ──────────────────────────────────────────────────────
    def _build_learn_toolbar(self):
        """Called while the toolbar is built, before its FlowBar starts."""
        self.advanced = tk.BooleanVar(value=False)
        # State the drawing code reads; set here, the earliest point in
        # __init__, so a redraw can never find it missing.
        self.disabled_supports = set()
        self.hide_zero = tk.BooleanVar(value=False)
        self.live_var = tk.BooleanVar(value=False)
        self._mech = None
        self._mech_job = None
        self._live_job = None
        self._live_sig = None
        self._stab_sig = None
        self._stab = None
        g = self.toolbar_flow.group()
        cb = tk.Checkbutton(g, text='Advanced tools', variable=self.advanced,
                            bg='#ebebea', font=('Helvetica', 10),
                            command=self._apply_mode)
        self._bind_widget_tooltip(cb,
            'Simple shows what a first truss needs. Advanced adds the CAD '
            'bar, construction geometry, arrays, plates and rod families.')

    def _init_learn(self, panel):
        """Called once the panel and the canvas exist."""
        self.stability_var = tk.StringVar(value='')
        self.stability_label = tk.Label(
            panel, textvariable=self.stability_var, bg=BG, fg='#555',
            font=('Helvetica', 9), justify='left', anchor='w',
            wraplength=200)
        self.stability_label.pack(fill='x', padx=12, pady=(0, 2),
                                  after=self.analyze_btn)
        row = tk.Frame(panel, bg=BG)
        row.pack(fill='x', padx=8, after=self.stability_label)
        self._learn_row = row
        live = tk.Checkbutton(row, text='Live', variable=self.live_var,
                              bg=BG, font=('Helvetica', 9),
                              command=self._on_live_toggle)
        live.pack(side='left')
        self._bind_widget_tooltip(live,
            'Re-solve a quarter of a second after every edit (models up to '
            '%d rods), so the forces move with the drawing.' % LIVE_MAX_RODS)
        hz = tk.Checkbutton(row, text='Hide zero-force rods',
                            variable=self.hide_zero, bg=BG,
                            font=('Helvetica', 9), command=self._draw)
        hz.pack(side='left', padx=(6, 0))
        self._bind_widget_tooltip(hz,
            'Rods that carry no force are drawn dashed; tick this to hide '
            'them and see the path the load actually takes.')

        # The sections Simple mode hides, in their panel order, each with
        # the pack options it was built with, so Advanced puts every one
        # back exactly where it was.
        order = [self.dload_frame, self.pload_frame, self.guide_frame,
                 self.array_frame, self.plate_frame, self.family_frame]
        self._adv_sections = [(f, self._pack_opts(f)) for f in order]
        self._adv_anchor = self.analyze_btn
        self._cad_pack = self._pack_opts(self.cad_bar)

        self.zc.canvas.bind('<Button-3>', self._on_support_right_click, add='+')
        self._fold_long_hints(panel)
        self._apply_mode()

    @staticmethod
    def _pack_opts(w):
        info = dict(w.pack_info())
        info.pop('in', None)
        return info

    # ── Simple / Advanced ─────────────────────────────────────────────────
    def _rigid_in_model(self):
        return any(r.get('conn', 'pin') == 'rigid' for r in self.rods)

    def _apply_mode(self):
        adv = bool(self.advanced.get())
        rigid = self._rigid_in_model()
        for f, opts in self._adv_sections:
            # Span loads only mean something on a rigid rod, so Simple mode
            # still shows them once the model has one.
            show = adv or (rigid and f in (self.dload_frame, self.pload_frame))
            packed = f.winfo_manager() == 'pack'
            if show and not packed:
                f.pack(before=self._next_packed_after(f), **opts)
            elif not show and packed:
                f.pack_forget()
        cad_packed = self.cad_bar.winfo_manager() == 'pack'
        if adv and not cad_packed:
            before = (self.diag_outer if self.diag_outer.winfo_manager() == 'pack'
                      else self.status_bar)
            self.cad_bar.pack(before=before, **self._cad_pack)
        elif not adv and cad_packed:
            self.cad_bar.pack_forget()
        # No fit_to_content() here: the panel was sized once with every
        # section showing, so Advanced never needs it wider than it is.

    def _next_packed_after(self, frame):
        seen = False
        for f, _opts in self._adv_sections:
            if f is frame:
                seen = True
                continue
            if seen and f.winfo_manager() == 'pack':
                return f
        return self._adv_anchor

    # ── folding long grey explanations ────────────────────────────────────
    def _fold_long_hints(self, widget):
        """Every grey explanation longer than HINT_FOLD_CHARS shows its
        first sentence and "more…"; a click shows the rest and folds it
        back. The words are all still there, one click away."""
        for w in widget.winfo_children():
            self._fold_long_hints(w)
            if w.winfo_class() != 'Label':
                continue
            try:
                text = str(w.cget('text'))
                fg = str(w.cget('fg')).lower()
            except tk.TclError:
                continue
            if str(w.cget('textvariable')) or len(text) <= HINT_FOLD_CHARS:
                continue
            if fg not in ('#555', '#666', '#777', '#888', '#999', 'gray', 'grey'):
                continue
            cut = text.find('. ')
            if cut < 0 or cut > HINT_FOLD_CHARS:
                cut = text.rfind(' ', 0, HINT_FOLD_CHARS)
            short = text[:cut + 1].rstrip() + '  more…'
            w._hint_full, w._hint_short, w._hint_open = text, short, False
            w.configure(text=short, cursor='hand2')

            def toggle(_e=None, w=w):
                w._hint_open = not w._hint_open
                w.configure(text=w._hint_full + '  less' if w._hint_open
                            else w._hint_short)
                return 'break'
            w.bind('<Button-1>', toggle)

    # ── the stability line, live analysis, mechanism life-cycle ──────────
    def _model_sig(self):
        return (tuple(map(tuple, self.nodes)),
                tuple((r['a'], r['b'], r.get('conn', 'pin')) for r in self.rods),
                tuple((s['node'], s['type']) for s in self._active_supports()),
                tuple((p.get('kind'), tuple(p.get('nodes', ()))) for p in self.plates),
                tuple((l['node'], l['fx'], l['fy']) for l in self.loads),
                tuple((r.get('udl', 0.0), len(r.get('point_loads', [])))
                      for r in self.rods))

    def _refresh_learn(self):
        """After every redraw: keep the stability line current, stop a
        mechanism animation the model has moved on from, and schedule a
        live solve."""
        if not hasattr(self, 'stability_var'):
            return
        # A switched-off support is remembered by node number; deleting a
        # node renumbers the rest, so forget the experiment rather than let
        # it land on the wrong joint.
        n = len(self.nodes)
        if getattr(self, '_learn_n_nodes', n) != n:
            self.disabled_supports.clear()
        self._learn_n_nodes = n
        self.disabled_supports &= {s['node'] for s in self.supports}
        try:
            sig = self._model_sig()
        except Exception:
            return
        geo = sig[:4]
        if geo != self._stab_sig:
            self._stab_sig = geo
            self._update_stability()
            self._apply_mode()
        if self._mech is not None and self._mech['sig'] != geo:
            self._stop_mechanism()
        if (self.live_var.get() and self.results is None
                and sig != self._live_sig and len(self.rods) <= LIVE_MAX_RODS):
            if self._live_job is not None:
                self.root.after_cancel(self._live_job)
            self._live_job = self.root.after(LIVE_DELAY_MS, self._live_analyze)

    def _update_stability(self):
        if len(self.nodes) < 2 or not self.rods:
            self.stability_var.set('')
            self._stab = None
            return
        if not self._active_supports():
            self._stab = None
            self.stability_var.set('No supports yet: add at least a pin and '
                                   'a roller with the Support tool.')
            self.stability_label.configure(fg='#b03a2e')
            return
        try:
            st = truss_stability.check(self.nodes, self.rods,
                                       self._active_supports(), self.plates)
        except Exception:
            self._stab = None
            self.stability_var.set('')
            return
        self._stab = st
        self.stability_var.set(st['text'])
        self.stability_label.configure(
            fg={'mechanism': '#b03a2e', 'determinate': '#1e7b34',
                'indeterminate': '#1a5fa8'}[st['verdict']])

    def _on_live_toggle(self):
        self._live_sig = None
        if self.live_var.get() and self.results is None:
            self._refresh_learn()

    def _live_analyze(self):
        self._live_job = None
        try:
            self._live_sig = self._model_sig()
        except Exception:
            return
        if (len(self.nodes) < 2 or not self.rods or not self._active_supports()
                or (self._stab and self._stab['verdict'] == 'mechanism')):
            return
        self._run_analysis(quiet=True)

    # ── labels that never overlap ─────────────────────────────────────────
    def _place_labels(self, c, queue, W, H):
        """Draw the queued numbers, most important first (joints, then rods
        by the size of their force), skipping any that would land on one
        already drawn. Zooming in makes room, so they come back."""
        placed, hidden = [], 0
        for prio, x, y, text, fill, tag in sorted(queue, key=lambda q: -q[0]):
            halo = tag == 'rod_label'
            items = []
            if halo:
                items.append(c.create_text(x, y, text=text, fill='white',
                                           font=('Helvetica', 9, 'bold'),
                                           tags=(tag,)))
            items.append(c.create_text(
                x, y, text=text, fill=fill, tags=(tag,),
                font=('Helvetica', 8, 'bold') if halo else ('Helvetica', 9)))
            bb = c.bbox(items[-1])
            if bb and any(bb[0] < p[2] and p[0] < bb[2] and
                          bb[1] < p[3] and p[1] < bb[3] for p in placed):
                for it in items:
                    c.delete(it)
                hidden += 1
                continue
            if bb:
                placed.append(bb)
        self._labels_hidden = hidden
        if hidden:
            c.create_text(W - 8, H - 8, anchor='se', fill='#999',
                          font=('Helvetica', 8), tags=('labels_hidden',),
                          text='%d number%s hidden where %s would overlap '
                               '-- zoom in to read %s'
                               % (hidden, '' if hidden == 1 else 's',
                                  'it' if hidden == 1 else 'they',
                                  'it' if hidden == 1 else 'them'))

    # ── support sandbox ───────────────────────────────────────────────────
    def _active_supports(self):
        off = getattr(self, 'disabled_supports', set())
        return [s for s in self.supports if s['node'] not in off]

    def _on_support_right_click(self, event):
        wx, wy = self.zc.s2w(event.x, event.y)
        thr = 14 / max(self.zc.zoom, 1e-9)
        for s in self.supports:
            nx, ny = self.nodes[s['node']]
            if math.hypot(nx - wx, ny - wy) < thr:
                break
        else:
            return None
        ni = s['node']
        # An experiment started on a solved model keeps re-solving at every
        # click -- including the click that brings the support back after
        # the model fell over -- until every support is on again.
        had = self.results is not None or getattr(self, '_sandbox_solving', False)
        self._sandbox_solving = had
        if ni in self.disabled_supports:
            self.disabled_supports.discard(ni)
            msg = 'Support at node %d is back on.' % ni
        else:
            self.disabled_supports.add(ni)
            msg = ('Support at node %d switched off for this experiment '
                   '(right-click it again to bring it back).' % ni)
        self.results = None
        self.diagrams = None
        self._draw()
        self._draw_diagrams_only()
        if had or self.live_var.get():
            self._run_analysis(quiet=True)
        if not self.disabled_supports:
            self._sandbox_solving = False
        if self.results is not None:
            self.status_var.set(msg + ' ' + self.status_var.get())
        elif not had:
            self.status_var.set(msg)
        return 'break'

    def _draw_disabled_support(self, c, sx, sy):
        r = 11
        c.create_line(sx - r, sy - r, sx + r, sy + r, fill='#b03a2e', width=3)
        c.create_line(sx - r, sy + r, sx + r, sy - r, fill='#b03a2e', width=3)

    # ── the mechanism, drawn moving ───────────────────────────────────────
    def _show_mechanism(self, quiet=False):
        """Called when Analyze finds the stiffness singular. Returns the
        sentence that says what is missing, or None."""
        try:
            mm = truss_stability.mechanism_mode(self.nodes, self.rods,
                                                self._active_supports(),
                                                self.plates)
        except Exception:
            mm = None
        if mm is None:
            return None
        if not quiet:
            self._start_mechanism(mm)
        return mm['text']

    def _start_mechanism(self, mm):
        self._stop_mechanism()
        xs = [p[0] for p in self.nodes]
        ys = [p[1] for p in self.nodes]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        self._mech = {'mm': mm, 'sig': self._model_sig()[:4], 'frame': 0,
                      'amp': 0.08 * span}
        self._mech_tick()

    def _stop_mechanism(self):
        if self._mech_job is not None:
            try:
                self.root.after_cancel(self._mech_job)
            except Exception:
                pass
        self._mech_job = None
        self._mech = None
        try:
            self.zc.canvas.delete('mech')
        except Exception:
            pass

    def _mech_tick(self):
        self._mech_job = None
        m = self._mech
        if m is None:
            return
        try:
            if self._model_sig()[:4] != m['sig'] or self.results is not None:
                self._stop_mechanism()
                return
        except Exception:
            self._stop_mechanism()
            return
        self._draw_mechanism()
        m['frame'] += 1
        self._mech_job = self.root.after(MECH_FRAME_MS, self._mech_tick)

    def _draw_mechanism(self):
        m = self._mech
        c, w2s = self.zc.canvas, self.zc.w2s
        c.delete('mech')
        if m is None:
            return
        mm = m['mm']
        if len(mm['motion']) != len(self.nodes):
            return
        k = m['amp'] * math.sin(m['frame'] * 2 * math.pi / 50)
        moved = [(x + k * dx, y + k * dy)
                 for (x, y), (dx, dy) in zip(self.nodes, mm['motion'])]
        for r in self.rods:
            a, b = moved[r['a']], moved[r['b']]
            sa, sb = w2s(*a), w2s(*b)
            c.create_line(*sa, *sb, fill=MECH_COLOR, width=3, dash=(6, 3),
                          tags=('mech',))
        for i in mm['moving'] + list(mm.get('loose', [])):
            if i < len(moved):
                sx, sy = w2s(*moved[i])
                c.create_oval(sx - 9, sy - 9, sx + 9, sy + 9,
                              outline=MECH_COLOR, width=2, tags=('mech',))
        c.create_text(10, 22, anchor='nw', fill=MECH_COLOR,
                      font=('Helvetica', 10, 'bold'), tags=('mech',),
                      text='It moves: ' + mm['kind'].replace('_', ' ')
                      .replace('internal', 'a panel folds')
                      .replace('slide x', 'it slides sideways')
                      .replace('slide y', 'it moves up and down')
                      .replace('turn', 'it turns as one piece')
                      .replace('loose', 'a node is loose'))
