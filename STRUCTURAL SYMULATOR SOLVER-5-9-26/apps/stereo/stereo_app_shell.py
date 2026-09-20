"""The window: one toolbar row, a mode rail, one context panel, a status bar.

The tab used to put every control on screen at once -- five stacked toolbar
rows, a 400 px sidebar holding eight sections in a single scroll, and a
300 px Module Editor open whether or not anyone was editing a module. That
is 196 px of chrome before a rod is drawn and about forty controls
competing, none louder than any other.

The organising idea here is that you are always doing exactly ONE thing --
building the mesh, or restraining it, or loading it, or reading what came
out -- and only that thing's controls belong on screen. So:

  toolbar (46 px)   the verbs that apply at any moment: Generate, Analyze,
                    undo/redo, Display, Export, the load slider, the unit
                    convention. Nothing here is display STATE.
  mode rail (76)    eight modes down the left edge. Exactly one is active.
  context panel     the active mode's controls, and nothing else.
  canvas            everything that is left, which is most of it.
  status bar (30)   what the last analysis found, and what to do next.

Display state -- colour ramp, what to draw, the deformed overlay -- is not
a mode and does not deserve permanent chrome either: it lives in a popover
hung off one toolbar button (see _build_display_popover).

The legend stays where it has always been, in the corner of the canvas,
because that is where you look when you are reading colour off the model.
"""
import tkinter as tk
from tkinter import ttk

from apps.stereo.stereo_app_constants import BG, LEGEND_CARD_BG, LEGEND_CARD_EDGE

# ── the rail ────────────────────────────────────────────────────────────────
# (key, glyph, label, tooltip). The glyphs are plain Unicode, not an icon
# font: Tk has no icon font and a bitmap set would need shipping, while
# these render on every platform the rest of the app already runs on.
MODES = (
    ('build',   '▦', 'Build',   'grid family, dimensions, examples'),
    ('shape',   '∿', 'Shape',   'custom surfaces and their domain'),
    ('support', '△', 'Support', 'where the structure stands'),
    ('load',    '↓', 'Load',    'what it carries'),
    ('section', '▤', 'Section', 'what it is made of'),
    ('addons',  '⊥', 'Add-ons', 'columns and reinforcement beams'),
    ('module',  '◫', 'Module',  'the repeating cell'),
    ('analyse', '◑', 'Analyse', 'how to draw it, and what the solve found'),
    ('results', 'Σ', 'Results', 'what came out'),
)
DEFAULT_MODE = 'build'

# ── named views ─────────────────────────────────────────────────────────────
# (azimuth, elevation) per preset, restored from the first version of this
# tab -- it had them and the rebuild had lost them. A view cube is the one
# piece of CAD furniture everybody already knows how to use, and typing two
# angles is not a substitute for it.
VIEW_PRESETS = (
    ('Iso',    35.0,  22.0),
    ('Top',     0.0,  89.9),
    ('Front',  90.0,   0.0),
    ('Right',   0.0,   0.0),
    ('Back',  270.0,   0.0),
    ('Left',  180.0,   0.0),
)

RAIL_W = 76
PANEL_W = 300
TOOLBAR_H = 46
STATUS_H = 30

RAIL_BG = '#eef2f6'
RAIL_ACTIVE_BG = '#ffffff'
RAIL_STRIPE = '#1a6bbd'
RAIL_ICON = '#7a8794'
RAIL_ICON_ACTIVE = '#1a6bbd'
RAIL_TEXT = '#4b555e'
RAIL_TEXT_ACTIVE = '#1d2328'
TOOLBAR_BG = '#ffffff'
RULE = '#ccd4db'
STATUS_BG = '#eef2f6'
STATUS_OK = '#1a7a3a'
STATUS_WARN = '#b3271e'
HINT_FG = '#78848e'


class StereoShellMixin:
    """Window chrome: toolbar, mode rail, context panel, status bar."""

    # ── the window ──────────────────────────────────────────────────────────
    def _build_ui(self):
        self._mode_frames = {}
        self._rail_buttons = {}
        self.active_mode = tk.StringVar(value=DEFAULT_MODE)
        self.status_var = tk.StringVar(value='Ready. Pick a grid family and press Generate.')
        self.status_kind = tk.StringVar(value='idle')
        self.hint_var = tk.StringVar(value='')

        self._init_display_vars()
        self._build_toolbar()

        # The status bar is packed BEFORE the main body so it keeps its
        # 30 px at the bottom of the window: pack gives space in packing
        # order, so an expand=True body packed first would eat the lot.
        self._build_status_bar()

        main = tk.Frame(self.root, bg=BG)
        main.pack(fill='both', expand=True)

        self._build_mode_rail(main)
        self._build_context_panel(main)
        self._build_canvas(main)
        self._build_view_cube()
        self._build_selection_card()

        self._populate_modes()
        self._apply_focus_ring(self.panel_host)
        self._set_mode(DEFAULT_MODE)
        self._on_generator_change()
        self._refresh_status()

    # ── toolbar ─────────────────────────────────────────────────────────────
    def _build_toolbar(self):
        """One row. Only verbs, plus the two global settings (how much load
        to show, and which unit convention to show it in)."""
        tb = tk.Frame(self.root, bg=TOOLBAR_BG, height=TOOLBAR_H,
                      highlightbackground=RULE, highlightthickness=1)
        tb.pack(side='top', fill='x')
        tb.pack_propagate(False)
        self.toolbar = tb

        tk.Label(tb, text='STEREO', bg=TOOLBAR_BG, fg=RAIL_STRIPE,
                 font=('Helvetica', 10, 'bold')).pack(side='left', padx=(12, 14))

        self.grid_family_btn = tk.Menubutton(
            tb, text='Generate  ▾', relief='raised', bd=1, padx=10, pady=3,
            font=('Helvetica', 9), bg='#ffffff')
        self.grid_family_btn.pack(side='left', padx=2)
        self._build_generate_menu()

        tk.Button(tb, text='▶  Analyze', font=('Helvetica', 9, 'bold'), bg='#e8f4ec',
                  fg=STATUS_OK, relief='raised', bd=1, padx=10, pady=3,
                  command=self._analyze).pack(side='left', padx=(6, 2))

        # Clear sits with Undo, not with Generate: it is the same KIND of
        # verb (it changes the model and is undoable), and putting it beside
        # the undo button is what makes it obvious that a mis-click costs
        # one keystroke rather than a rebuild.
        tk.Button(tb, text='Clear', font=('Helvetica', 9), relief='raised', bd=1,
                  padx=9, pady=3, command=self._clear_model).pack(side='left', padx=(10, 2))

        tk.Button(tb, text='⟲', font=('Helvetica', 11), relief='raised', bd=1,
                  padx=7, pady=1, command=self._undo).pack(side='left', padx=(8, 1))
        tk.Button(tb, text='⟳', font=('Helvetica', 11), relief='raised', bd=1,
                  padx=7, pady=1, command=self._redo).pack(side='left', padx=1)

        self.display_btn = tk.Button(tb, text='Display  ▾', font=('Helvetica', 9),
                                     relief='raised', bd=1, padx=10, pady=3,
                                     command=self._toggle_display_popover)
        self.display_btn.pack(side='left', padx=(10, 2))

        export_btn = tk.Menubutton(tb, text='Export  ▾', relief='raised', bd=1,
                                   padx=10, pady=3, font=('Helvetica', 9), bg='#ffffff')
        menu = tk.Menu(export_btn, tearoff=False)
        menu.add_command(label='Member Report…', command=self._show_member_report)
        menu.add_separator()
        menu.add_command(label='Export Excel…', command=self._export_excel)
        menu.add_command(label='Import Excel…', command=self._import_excel)
        export_btn['menu'] = menu
        export_btn.pack(side='left', padx=2)

        # right-hand end: the two settings that apply to the whole window
        tk.Button(tb, text='Reset view', font=('Helvetica', 9), relief='raised', bd=1,
                  padx=8, pady=3, command=self._reset_view).pack(side='right', padx=(4, 12))
        self.load_fraction = tk.IntVar(value=100)
        tk.Scale(tb, from_=0, to=100, orient='horizontal', variable=self.load_fraction,
                 length=150, showvalue=True, bg=TOOLBAR_BG, bd=0, highlightthickness=0,
                 font=('Helvetica', 8), command=lambda _=None: self._draw()
                 ).pack(side='right', padx=(2, 8))
        tk.Label(tb, text='Load %', bg=TOOLBAR_BG, fg=HINT_FG,
                 font=('Helvetica', 9)).pack(side='right', padx=(8, 2))

    def _build_generate_menu(self):
        """Family choice, the surface wizard and the example library all hang
        off Generate, because they are three answers to one question -- where
        does the mesh come from."""
        from apps.stereo.stereo_app_constants import GRID_FAMILIES
        from apps.stereo import stereo_examples as sx
        menu = tk.Menu(self.grid_family_btn, tearoff=False)
        fam = tk.Menu(menu, tearoff=False)
        for _key, label in GRID_FAMILIES:
            fam.add_radiobutton(label=label, value=label, variable=self.grid_family,
                                command=self._on_family_pick)
        menu.add_cascade(label='Grid family', menu=fam)
        menu.add_command(label='Generate now', command=self._generate)
        menu.add_separator()
        menu.add_command(label='Custom surface…', command=self._open_custom_surface_wizard)
        ex = tk.Menu(menu, tearoff=False)
        for label, builder in sx.EXAMPLES:
            ex.add_command(label=label,
                           command=lambda b=builder, l=label: self._load_example(b, l))
        menu.add_cascade(label='Example library', menu=ex)
        self.grid_family_btn['menu'] = menu

    def _on_family_pick(self):
        """Picking a family from the menu shows its own fields in Build and
        jumps you there -- otherwise the choice would appear to do nothing
        until you noticed the panel behind you had changed."""
        self._on_generator_change()
        self._set_mode('build')

    # ── mode rail ───────────────────────────────────────────────────────────
    def _build_mode_rail(self, parent):
        rail = tk.Frame(parent, bg=RAIL_BG, width=RAIL_W,
                        highlightbackground=RULE, highlightthickness=1)
        rail.pack(side='left', fill='y')
        rail.pack_propagate(False)
        self.mode_rail = rail

        for n, (key, glyph, label, tip) in enumerate(MODES, start=1):
            # The hint carries the shortcut: a key nobody is told about
            # is a key nobody presses.
            tip = f'{tip}   (Alt+{n})' if n <= 9 else tip
            item = tk.Frame(rail, bg=RAIL_BG, height=62, cursor='hand2')
            item.pack(fill='x', pady=(4, 0))
            item.pack_propagate(False)
            stripe = tk.Frame(item, bg=RAIL_BG, width=4)
            stripe.pack(side='left', fill='y')
            body = tk.Frame(item, bg=RAIL_BG)
            body.pack(side='left', fill='both', expand=True)
            icon = tk.Label(body, text=glyph, bg=RAIL_BG, fg=RAIL_ICON,
                            font=('Helvetica', 15, 'bold'))
            icon.pack(pady=(9, 0))
            name = tk.Label(body, text=label, bg=RAIL_BG, fg=RAIL_TEXT,
                            font=('Helvetica', 8))
            name.pack()
            self._rail_buttons[key] = (item, stripe, body, icon, name)
            for w in (item, body, icon, name):
                w.bind('<Button-1>', lambda _e, k=key: self._set_mode(k))
                w.bind('<Enter>', lambda _e, t=tip: self.hint_var.set(t))
                w.bind('<Leave>', lambda _e: self.hint_var.set(''))
        self._bind_mode_keys()

    def _bind_mode_keys(self):
        """Alt+1..8 jump straight to a mode, in rail order.

        Deliberately Alt and not the bare digit: half this tab's work is
        typing numbers into entry fields, and a bare digit shortcut would
        swallow them. The binding goes on the TOPLEVEL rather than the
        canvas, because a mode switch is meaningful wherever the focus
        happens to be -- including inside the entry you were just editing,
        which is exactly when you want to move on to the next mode.
        """
        top = self.root.winfo_toplevel()
        for n, (key, _glyph, _label, _tip) in enumerate(MODES, start=1):
            if n > 9:
                break
            top.bind(f'<Alt-Key-{n}>', lambda _e, k=key: self._mode_hotkey(k))

    def _mode_hotkey(self, key):
        """'break' stops the keypress reaching the widget that had focus, so
        Alt+4 switches mode instead of also typing a 4 into an entry."""
        self._set_mode(key)
        return 'break'

    def _apply_focus_ring(self, widget):
        """Give every entry in the panels a visible focus ring.

        Tk's default is a focus highlight the same colour as the
        background, which is to say none: with eight panels of numeric
        fields there was no way to tell which one a keystroke was about to
        land in. Applied by walking the built panels once rather than at
        each of the seventeen Entry call sites, so a field added later gets
        it without anyone having to remember.
        """
        for child in widget.winfo_children():
            # ttk.Entry SUBCLASSES tk.Entry but is themed and has no
            # highlight options at all, so isinstance alone would reach the
            # entry inside every readonly combobox and raise.
            if isinstance(child, tk.Entry) and not isinstance(child, ttk.Entry):
                child.configure(highlightthickness=1, highlightbackground=BG,
                                highlightcolor=RAIL_STRIPE)
            self._apply_focus_ring(child)

    def _set_mode(self, key):
        """Show one mode's panel and mark its rail item. Every other panel is
        forgotten rather than hidden, so nothing off-screen keeps claiming
        space from the canvas."""
        if key not in self._mode_frames:
            return
        self.active_mode.set(key)
        for k, (item, stripe, body, icon, name) in self._rail_buttons.items():
            on = (k == key)
            bg = RAIL_ACTIVE_BG if on else RAIL_BG
            for w in (item, body, icon, name):
                w.configure(bg=bg)
            stripe.configure(bg=RAIL_STRIPE if on else bg)
            icon.configure(fg=RAIL_ICON_ACTIVE if on else RAIL_ICON)
            name.configure(fg=RAIL_TEXT_ACTIVE if on else RAIL_TEXT,
                           font=('Helvetica', 8, 'bold') if on else ('Helvetica', 8))
        for k, frame in self._mode_frames.items():
            if k == key:
                frame.pack(fill='both', expand=True)
            else:
                frame.pack_forget()
        label = next(m[2] for m in MODES if m[0] == key)
        self.mode_title.set(label.upper())
        if key == 'analyse':
            # The charts are pictures of the last solve, which may have
            # happened while another mode was showing.
            self._refresh_analysis_charts()
        self.panel_outer.fit_to_content()

    # ── context panel ───────────────────────────────────────────────────────
    def _build_context_panel(self, parent):
        from common import ScrollPanel
        holder = tk.Frame(parent, bg=BG, width=PANEL_W)
        holder.pack(side='left', fill='y')
        holder.pack_propagate(False)

        self.mode_title = tk.StringVar(value='')
        head = tk.Frame(holder, bg='#ffffff')
        head.pack(fill='x')
        tk.Label(head, textvariable=self.mode_title, bg='#ffffff', fg=HINT_FG,
                 font=('Helvetica', 8, 'bold'), anchor='w').pack(fill='x', padx=12, pady=(9, 6))
        tk.Frame(holder, bg=RULE, height=1).pack(fill='x')

        self.panel_outer = ScrollPanel(holder, width=PANEL_W, bg=BG)
        self.panel_outer.pack(fill='both', expand=True)
        self.panel_host = self.panel_outer.interior

    def _populate_modes(self):
        """One frame per mode, each built by the panel builders that already
        existed -- this is a relocation, not a rewrite of the controls."""
        for key, _glyph, _label, _tip in MODES:
            self._mode_frames[key] = tk.Frame(self.panel_host, bg=BG)

        self._build_geometry_panel(self._mode_frames['build'])
        self._build_shape_panel(self._mode_frames['shape'])
        self._build_supports_panel(self._mode_frames['support'])
        self._build_loads_panel(self._mode_frames['load'])
        self._build_connectivity_panel(self._mode_frames['section'])
        self._build_section_panel(self._mode_frames['section'], 'chord',
                                  'Chord section (top/bottom)')
        self._build_section_panel(self._mode_frames['section'], 'web',
                                  'Web section (diagonals)')
        self._build_addons_panel(self._mode_frames['addons'])
        self._build_module_editor_panel(self._mode_frames['module'])
        self._build_analysis_panel(self._mode_frames['analyse'])
        self._build_selection_panel(self._mode_frames['results'])
        self._build_results_panel(self._mode_frames['results'])
        self._on_connectivity_change()   # hide I/J unless Rigid is selected
        self._on_col_style_change()      # hide the fields this style ignores

    # ── status bar ──────────────────────────────────────────────────────────
    def _build_status_bar(self):
        """What the last analysis found, and -- on the right -- what to do
        next. The older version of this tab had the first half and it was
        the single most useful line on screen; the second half is new."""
        sb = tk.Frame(self.root, bg=STATUS_BG, height=STATUS_H,
                      highlightbackground=RULE, highlightthickness=1)
        sb.pack(side='bottom', fill='x')
        sb.pack_propagate(False)
        self.status_label = tk.Label(sb, textvariable=self.status_var, bg=STATUS_BG,
                                     anchor='w', font=('Helvetica', 9))
        self.status_label.pack(side='left', padx=12)
        tk.Label(sb, textvariable=self.hint_var, bg=STATUS_BG, fg=HINT_FG, anchor='e',
                 font=('Helvetica', 9, 'italic')).pack(side='right', padx=12)

    def _set_status(self, text, kind='idle'):
        self.status_kind.set(kind)
        self.status_var.set(text)
        self.status_label.configure(
            fg={'ok': STATUS_OK, 'error': STATUS_WARN}.get(kind, '#1d2328'))

    def _refresh_status(self):
        """Recompute the status line from whatever state the model is in.

        Called after every command, so it is the one place that decides what
        the window claims about itself.
        """
        if not self.nodes:
            self._set_status('No model. Pick a grid family under Generate.')
            return
        n = f'{len(self.nodes)} nodes · {len(self.members)} rods'
        if self.results is None:
            self._set_status(f'{n} · not analyzed')
            return
        if getattr(self, 'err', None):
            self._set_status(f'{n} · {self.err}', 'error')
            return
        frac = self._load_frac()
        bits = [n]
        checks = self.member_checks or []
        utils = [c['util'] for c in checks if c.get('checked')]
        if utils:
            bits.append(f'governing utilisation {max(utils) * frac:.2f}')
        _deformed, disp = self._deformed_nodes_and_disp()
        if disp:
            bits.append(self.fmt('deflection', max(disp), digits=1))
        rz = sum(r.get('Fz', 0.0) for r in self.results['reactions'].values())
        bits.append('ΣRz ' + self.fmt('force', rz * frac, digits=0))
        self._set_status('Analyzed · ' + '  ·  '.join(bits), 'ok')


    # ── view cube ───────────────────────────────────────────────────────────
    def _build_view_cube(self):
        """Named views, parked over the canvas corner.

        They were a row of toolbar buttons in the first version of this tab
        and the rebuild dropped them. They belong on the canvas, not in the
        chrome: they are about what you are looking at, and a card over the
        model costs the model nothing.
        """
        self.view_cube = tk.Frame(self.canvas, bg='#fbfcfd',
                                  highlightbackground=RULE, highlightthickness=1)
        tk.Label(self.view_cube, text='VIEW', bg='#fbfcfd', fg=HINT_FG,
                 font=('Helvetica', 7, 'bold')).grid(row=0, column=0, columnspan=2,
                                                     sticky='w', padx=6, pady=(4, 2))
        self._view_buttons = {}
        for k, (name, az, el) in enumerate(VIEW_PRESETS):
            b = tk.Button(self.view_cube, text=name, font=('Helvetica', 8),
                          relief='raised', bd=1, width=5, padx=2, pady=1,
                          command=lambda a=az, e=el, n=name: self._set_named_view(n, a, e))
            b.grid(row=1 + k // 2, column=k % 2, padx=3, pady=2)
            self._view_buttons[name] = b
        self._view_window = None
        self.current_view = tk.StringVar(value='')

    # ── selection card ──────────────────────────────────────────────────────
    SELECTION_CARD_W = 268

    def _build_selection_card(self):
        """The click-to-inspect readout, on the canvas rather than in a panel.

        It lived in the Results panel, which meant that clicking a rod while
        placing supports wrote the answer onto a panel that was not on
        screen -- and the canvas legend was meanwhile inviting you to click
        a rod to inspect it. A readout about the thing under the cursor
        belongs next to the cursor, in every mode.
        """
        self.selection_card = tk.Frame(self.canvas, bg=LEGEND_CARD_BG,
                                       highlightbackground=LEGEND_CARD_EDGE,
                                       highlightthickness=1)
        tk.Label(self.selection_card, text='SELECTION', bg=LEGEND_CARD_BG, fg=HINT_FG,
                 font=('Helvetica', 7, 'bold')).pack(anchor='w', padx=8, pady=(4, 0))
        tk.Label(self.selection_card, textvariable=self.sel_var, bg=LEGEND_CARD_BG,
                 fg='#1d2328', font=('Helvetica', 8), justify='left',
                 wraplength=self.SELECTION_CARD_W - 20
                 ).pack(anchor='w', padx=8, pady=(0, 6))

    def _place_selection_card(self):
        """Bottom-left of the canvas, and only while something is selected.

        Empty, it would just repeat the legend's own invitation to click
        something, permanently, over the model.
        """
        c = self.canvas
        want = (bool(self.show_selection_card.get())
                and (self.selected_nodes or self.selected_member is not None))
        if not want:
            c.delete('selection_card')
            return
        y = c.winfo_height() - self.selection_card.winfo_reqheight() - 16
        existing = c.find_withtag('selection_card')
        if existing:
            c.coords(existing[0], 16, y)
        else:
            c.create_window(16, y, window=self.selection_card, anchor='nw',
                            tags='selection_card')

    def _place_view_cube(self):
        """Keep the cube in its corner as the window resizes. Called from
        _draw, like the other canvas cards."""
        c = self.canvas
        existing = c.find_withtag('view_cube')
        x = c.winfo_width() - 16
        if existing:
            c.coords(existing[0], x, 16)
        else:
            c.create_window(x, 16, window=self.view_cube, anchor='ne', tags='view_cube')

    def _set_named_view(self, name, az, el):
        """Snap the camera to a preset and mark which one is showing."""
        self.azimuth, self.elevation = az, el
        self.current_view.set(name)
        for other, b in self._view_buttons.items():
            on = (other == name)
            b.configure(relief='sunken' if on else 'raised',
                        fg=RAIL_STRIPE if on else '#1d2328',
                        font=('Helvetica', 8, 'bold') if on else ('Helvetica', 8))
        self._mark_view_touched()
        self._draw()

    def _clear_named_view(self):
        """Orbiting by hand leaves every preset unlit -- the camera is no
        longer at any of them, and a button still pressed in would be a lie."""
        if not self.current_view.get():
            return
        self.current_view.set('')
        for b in self._view_buttons.values():
            b.configure(relief='raised', fg='#1d2328', font=('Helvetica', 8))

    # ── display popover ─────────────────────────────────────────────────────
    def _toggle_display_popover(self):
        """Display state is not a mode and does not deserve permanent chrome:
        four toolbar rows of it now live behind this one button."""
        pop = getattr(self, '_display_pop', None)
        if pop is not None and pop.winfo_exists():
            pop.destroy()
            self._display_pop = None
            return
        self._build_display_popover()

    def _build_display_popover(self):
        pop = tk.Toplevel(self.root)
        pop.transient(self.root.winfo_toplevel())
        pop.overrideredirect(True)
        pop.configure(bg=RULE)
        self._display_pop = pop
        body = tk.Frame(pop, bg=BG)
        body.pack(padx=1, pady=1)
        self._fill_display_popover(body)
        pop.update_idletasks()
        x = self.display_btn.winfo_rootx()
        y = self.display_btn.winfo_rooty() + self.display_btn.winfo_height() + 2
        pop.geometry(f'+{x}+{y}')
        pop.bind('<Escape>', lambda _e: self._toggle_display_popover())
        pop.focus_set()
