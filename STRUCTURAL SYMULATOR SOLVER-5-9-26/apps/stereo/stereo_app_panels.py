"""Sidebar panel and toolbar construction for the Stereo tab.

Everything in here is pure WIDGET LAYOUT: it creates frames, labels,
entries and dropdowns, and binds them to the Tk variables StereoApp
.__init__ already created. It deliberately holds no model logic -- a
button here calls a method that lives in the mixin owning that behaviour
(stereo_app_model, stereo_app_addons, ...), so "what the panel looks like"
and "what the button does" can be read and changed separately.

_build_ui is the entry point and the map of the whole tab: toolbar, canvas
and the ordered stack of sidebar panels.
"""
import tkinter as tk
from tkinter import ttk

from common import ZoomCanvas, FlowBar, ScrollPanel
from apps.stereo.stereo_app_shell import HINT_FG

from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_math as sm
from apps.stereo import stereo_examples as sx
from apps.stereo import stereo_app_analysis as sa
from apps.stereo import stereo_member_loads as mld
from apps.stereo.stereo_app_constants import (
    BG, CANVAS_BG, PANEL_W, MODULE_PANEL_W,
    DOF_LABELS, PRESET_NAMES, GRID_PATTERNS, PATTERN_LABEL, GRID_FAMILIES,
    QUICK_SUPPORT_PIN, QUICK_SUPPORT_CHOICES,
    DEFORM_MODES, DEFORM_MODE_DISPLACEMENT,
    MOMENT_AXES, MOMENT_AXIS_RESULTANT,
    COLOUR_NONE, COLOUR_FORCE, COLOUR_UTIL, COLOUR_MOMENT, COLOUR_MODES,
    COLOUR_ROD_MOMENT, COLOUR_ROD_SHEAR,
    FILL_NONE, FILL_SHADED, FILL_MODES,
    SCALE_P95, SCALE_MODES,
    FILL_DENSITIES, FILL_DENSITY_DEFAULT,
    AREA_UNIFORM, AREA_GRADIENT, AREA_FIELD, AREA_LAWS,
    LOAD_DIRECTION_NAMES, AREA_SCOPE_ALL, AREA_SCOPES,
    ROD_SCOPES, ROD_SCOPE_TOP,
    SHAPE_PLAN_PRESETS, PANEL_TEXT_W,
    HYPERBOLOID_BRACES, BRACE_LABEL,
)


class _ToolbarModes:
    """Translates the toolbar's two radio groups into the boolean flags the
    renderer reads.

    The radios are what a person sees and the booleans are what the drawing
    code asks, and keeping both means the exclusivity is enforced in ONE
    obvious place -- setting a radio clears the others by construction --
    instead of being re-derived as a precedence rule at every draw.
    """

    def _on_colour_mode_change(self):
        mode = self.colour_mode.get()
        self.colour_by_force.set(mode == COLOUR_FORCE)
        self.colour_by_util.set(mode == COLOUR_UTIL)
        self.colour_by_moment.set(mode == COLOUR_MOMENT)
        self.colour_by_rod_moment.set(mode == COLOUR_ROD_MOMENT)
        self.colour_by_rod_shear.set(mode == COLOUR_ROD_SHEAR)
        self._draw()

    def _on_faces_mode_change(self):
        mode = self.faces_mode.get()
        self.shaded_faces.set(mode == FILL_SHADED)
        self._draw()


class StereoPanelsMixin(_ToolbarModes):
    """Builds the toolbar, the 3D canvas and every sidebar panel."""

    def _pop_group(self, parent, caption):
        """One captioned row inside the Display popover.

        The caption is what tells you a row is FOR something -- a bare strip
        of checkboxes cannot say that 'Only' means only the deformed shape.
        Same two widget types throughout: a RADIO where exactly one choice
        applies, a CHECKBOX where something is independently on or off.
        """
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill='x', padx=10, pady=(8, 0))
        tk.Label(wrap, text=caption, bg=BG, font=('Helvetica', 7, 'bold'),
                 fg='#7a869a', anchor='w').pack(fill='x')
        row = tk.Frame(wrap, bg=BG)
        row.pack(fill='x')
        return row

    def _init_display_vars(self):
        """Every display-state variable, created before anything draws.

        These used to be created while building the toolbar, which was
        fine when the toolbar was always there. The popover is built on
        demand and destroyed on close, so its widgets cannot own the
        state: _draw reads show_deformed on the very first frame, long
        before anyone opens Display, and closing the popover must not
        throw a setting away.
        """
        # What the click-to-inspect readout currently says. It drives BOTH
        # the Results panel's label and the canvas card, so the two cannot
        # disagree about what is selected.
        self.sel_var = tk.StringVar(
            value='(click, or drag a box, to select node(s))')
        self.show_selection_card = tk.BooleanVar(value=True)
        self.colour_by_force = tk.BooleanVar(value=True)
        self.colour_by_util = tk.BooleanVar(value=False)
        self.colour_by_moment = tk.BooleanVar(value=False)
        self.colour_by_rod_moment = tk.BooleanVar(value=False)
        self.colour_by_rod_shear = tk.BooleanVar(value=False)
        self.colour_mode = tk.StringVar(value=COLOUR_FORCE)
        self.force_scale = tk.StringVar(value=SCALE_P95)
        self.moment_axis = tk.StringVar(value=MOMENT_AXIS_RESULTANT)
        self.smooth_gradient = tk.BooleanVar(value=False)
        self.thickness_by_stress = tk.BooleanVar(value=False)
        self.hide_zero_force = tk.BooleanVar(value=False)
        self.flag_slender = tk.BooleanVar(value=False)
        self.shaded_faces = tk.BooleanVar(value=False)
        self.faces_mode = tk.StringVar(value=FILL_NONE)
        self.fill_density = tk.StringVar(value=FILL_DENSITY_DEFAULT)
        self.show_deformed = tk.BooleanVar(value=False)
        self.deform_scale = tk.IntVar(value=50)
        self.deformed_only = tk.BooleanVar(value=False)
        self.deform_color_mode = tk.StringVar(value=DEFORM_MODE_DISPLACEMENT)
        self.reference_shade = tk.IntVar(value=78)
        self.show_members = tk.BooleanVar(value=True)
        self.show_nodes = tk.BooleanVar(value=True)
        self.show_node_labels = tk.BooleanVar(value=True)
        self.show_member_labels = tk.BooleanVar(value=False)
        self.show_loads = tk.BooleanVar(value=True)
        self.show_reactions = tk.BooleanVar(value=False)
        self.show_axes = tk.BooleanVar(value=True)
        self.show_module_card = tk.BooleanVar(value=True)
        self.load_path_anim = tk.BooleanVar(value=False)

    def _fill_display_popover(self, body):
        """Everything that is display STATE rather than a verb.

        These were four permanent toolbar rows. Nothing here changes the
        model, so none of it earns space that the model itself could use --
        it is one button away instead.
        """
        # ── 3 · COLOUR BY ────────────────────────────────────────────────────
        # One quantity at a time, so this is a radio. It replaces three
        # independent checkboxes whose mutual exclusivity was real but
        # invisible -- utilization silently won over force, which won over
        # moment, and nothing on screen said so.
        g = self._pop_group(body, 'COLOUR BY')
        for label in COLOUR_MODES:
            tk.Radiobutton(g, text=label, value=label, variable=self.colour_mode,
                           bg=BG, command=self._on_colour_mode_change
                           ).pack(side='left', padx=(0, 4))
        # Where the force ramp's ends are pinned. Anchoring at the literal
        # peak lets one extreme member set the scale for the whole model --
        # the median rod carries 12-32% of it across the shipped families --
        # so the percentile anchor is offered alongside, with the members
        # above it marked rather than silently flattened against the end.
        tk.Label(g, text='scale', bg=BG, font=('Helvetica', 8), fg='#556')\
            .pack(side='left', padx=(8, 2))
        for label in SCALE_MODES:
            tk.Radiobutton(g, text=label, value=label, variable=self.force_scale,
                           bg=BG, command=self._draw).pack(side='left', padx=(0, 3))
        moment_axis_box = ttk.Combobox(g, textvariable=self.moment_axis, state='readonly',
                                       width=15, values=MOMENT_AXES)
        moment_axis_box.pack(side='left', padx=(2, 0))
        moment_axis_box.bind('<<ComboboxSelected>>', lambda e: self._draw())

        # ── 4 · DRAW RODS AS ─────────────────────────────────────────────────
        g = self._pop_group(body, 'DRAW RODS AS')
        tk.Checkbutton(g, text='Smooth gradient', variable=self.smooth_gradient,
                       bg=BG, command=self._draw).pack(side='left')
        tk.Checkbutton(g, text='Thickness = stress', variable=self.thickness_by_stress,
                       bg=BG, command=self._draw).pack(side='left', padx=(6, 0))
        tk.Checkbutton(g, text='Hide ~0-force rods', variable=self.hide_zero_force, bg=BG,
                       command=self._draw).pack(side='left', padx=(6, 0))
        # Short on purpose: the KL/r threshold itself is shown in the legend
        # once this is on (see _draw_legend), not repeated in the checkbox
        # text -- a long label here pushed this toolbar group's requested
        # width right to FlowBar's row-wrap threshold, and re-measuring that
        # borderline width on every relayout pass (see FlowBar.relayout's own
        # notes on why it never caches) made the row wrap and un-wrap forever
        # instead of settling, which looked like the whole app hanging.
        tk.Checkbutton(g, text='Flag slender compression members',
                       variable=self.flag_slender, bg=BG,
                       command=self._draw).pack(side='left', padx=(6, 0))

        # ── 5 · FILL ─────────────────────────────────────────────────────────
        # One fill at a time, so again a radio. Whichever is chosen takes its
        # colours from the COLOUR BY group above -- the fill decides the
        # SHAPE being coloured, never the quantity.
        g = self._pop_group(body, 'FILL')
        for label in FILL_MODES:
            tk.Radiobutton(g, text=label, value=label, variable=self.faces_mode,
                           bg=BG, command=self._on_faces_mode_change
                           ).pack(side='left', padx=(0, 4))
        # How opaque a fill is drawn. Tk has no alpha channel, so a fill is
        # made see-through with a stipple pattern; this picks which one.
        # Solid hides everything behind the nearest patch, and the densest
        # half-tone flattens the dark end of the colour ramp, so the default
        # sits between them.
        tk.Label(g, text='shade', bg=BG, font=('Helvetica', 8), fg='#556')\
            .pack(side='left', padx=(8, 2))
        dens = ttk.Combobox(g, textvariable=self.fill_density, state='readonly',
                            width=7, values=list(FILL_DENSITIES))
        dens.pack(side='left')
        dens.bind('<<ComboboxSelected>>', lambda e: self._draw())

        # ── 7 · DEFORMED SHAPE ───────────────────────────────────────────────
        # Kept apart from COLOUR BY on purpose: this colours a DIFFERENT
        # object -- the displaced copy drawn over the structure -- so it
        # carries its own quantity choice rather than competing for the one
        # above.
        g = self._pop_group(body, 'DEFORMED SHAPE')
        tk.Checkbutton(g, text='Show', variable=self.show_deformed, bg=BG,
                       command=self._draw).pack(side='left')
        tk.Label(g, text='×', bg=BG, font=('Helvetica', 9)).pack(side='left', padx=(4, 0))
        tk.Scale(g, from_=1, to=500, orient='horizontal', variable=self.deform_scale,
                length=80, showvalue=True, command=lambda _v: self._draw()
                ).pack(side='left')
        tk.Checkbutton(g, text='Only', variable=self.deformed_only, bg=BG,
                       command=self._draw).pack(side='left', padx=(4, 0))
        tk.Label(g, text='colour', bg=BG, font=('Helvetica', 8), fg='#556'
                ).pack(side='left', padx=(6, 2))
        deform_mode_box = ttk.Combobox(g, textvariable=self.deform_color_mode, state='readonly',
                                       width=14, values=DEFORM_MODES)
        deform_mode_box.pack(side='left')
        deform_mode_box.bind('<<ComboboxSelected>>', lambda e: self._draw())
        tk.Label(g, text='ref. shade', bg=BG, font=('Helvetica', 8), fg='#556'
                ).pack(side='left', padx=(6, 2))
        tk.Scale(g, from_=0, to=100, orient='horizontal', variable=self.reference_shade,
                length=70, showvalue=False, command=lambda _v: self._draw()
                ).pack(side='left')

        # ── 8 · SHOW ─────────────────────────────────────────────────────────
        # Independent annotations drawn over whatever the groups above
        # produced -- every one of these is on or off by itself, which is why
        # they are all checkboxes and all live together.
        g = self._pop_group(body, 'SHOW')
        tk.Checkbutton(g, text='Rods', variable=self.show_members, bg=BG,
                       command=self._draw).pack(side='left')
        tk.Checkbutton(g, text='Nodes', variable=self.show_nodes, bg=BG,
                       command=self._draw).pack(side='left', padx=(4, 0))
        tk.Checkbutton(g, text='Node #', variable=self.show_node_labels, bg=BG,
                       command=self._draw).pack(side='left', padx=(4, 0))
        tk.Checkbutton(g, text='Rod #', variable=self.show_member_labels, bg=BG,
                       command=self._draw).pack(side='left', padx=(4, 0))
        tk.Checkbutton(g, text='Loads', variable=self.show_loads, bg=BG,
                       command=self._draw).pack(side='left', padx=(4, 0))
        tk.Checkbutton(g, text='Reactions', variable=self.show_reactions, bg=BG,
                       command=self._draw).pack(side='left', padx=(4, 0))
        tk.Checkbutton(g, text='Axes + ground', variable=self.show_axes, bg=BG,
                       command=self._draw).pack(side='left', padx=(4, 0))
        tk.Checkbutton(g, text='Load-path arrows', variable=self.load_path_anim, bg=BG,
                      command=self._on_load_path_anim_toggle).pack(side='left', padx=(4, 0))


        tk.Frame(body, bg='#ccd4db', height=1).pack(fill='x', pady=(10, 0))
        tk.Label(body, text='Esc or Display again to close', bg=BG, fg='#78848e',
                 font=('Helvetica', 8, 'italic')).pack(anchor='w', padx=10, pady=(4, 8))

    # ── Analyse mode: how to draw it, and what the solve found ──────────────
    ANALYSIS_CHART_H = 460

    def _build_analysis_panel(self, parent):
        """The display controls, and charts of what the solve found.

        These controls existed, but only inside the Display popover -- one
        button away, and therefore, for anyone who had not found that button,
        not there at all. A popover is the right home for something you
        already know exists; it is the wrong home for the whole visual
        vocabulary of the tab. They live here now, in the rail like every
        other group of controls, and the popover keeps working for reaching
        them without leaving the mode you are in. Both bind the SAME Tk
        variables, so the two can never disagree.
        """
        box = tk.LabelFrame(parent, text='Colour the rods by', bg=BG,
                            font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=4)
        for label in COLOUR_MODES:
            tk.Radiobutton(box, text=label, value=label, variable=self.colour_mode,
                           bg=BG, font=('Helvetica', 9), anchor='w',
                           command=self._on_colour_mode_change
                           ).pack(fill='x', padx=6)
        srow = tk.Frame(box, bg=BG)
        srow.pack(fill='x', padx=6, pady=(4, 0))
        tk.Label(srow, text='scale:', bg=BG, font=('Helvetica', 8), fg=HINT_FG,
                 width=6, anchor='w').pack(side='left')
        for label in SCALE_MODES:
            tk.Radiobutton(srow, text=label, value=label, variable=self.force_scale,
                           bg=BG, font=('Helvetica', 8),
                           command=self._draw).pack(side='left')
        mrow = tk.Frame(box, bg=BG)
        mrow.pack(fill='x', padx=6, pady=(2, 6))
        tk.Label(mrow, text='moment:', bg=BG, font=('Helvetica', 8), fg=HINT_FG,
                 width=8, anchor='w').pack(side='left')
        axis_box = ttk.Combobox(mrow, textvariable=self.moment_axis, state='readonly',
                                width=8, values=MOMENT_AXES)
        axis_box.pack(side='left', fill='x', expand=True)
        axis_box.bind('<<ComboboxSelected>>', lambda _e: self._draw())

        box = tk.LabelFrame(parent, text='Draw the rods as', bg=BG,
                            font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=4)
        for text, var in (('Smooth gradient along each rod', self.smooth_gradient),
                          ('Thickness = stress', self.thickness_by_stress),
                          ('Hide ~0-force rods', self.hide_zero_force),
                          ('Flag slender compression members', self.flag_slender)):
            tk.Checkbutton(box, text=text, variable=var, bg=BG,
                           font=('Helvetica', 9), anchor='w', justify='left',
                           wraplength=PANEL_TEXT_W, command=self._draw
                           ).pack(fill='x', padx=6)

        box = tk.LabelFrame(parent, text='Fill the cells', bg=BG,
                            font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=4)
        tk.Label(box, text='Shades each closed cell of the mesh by its own '
                           'governing member, so the structure reads as a '
                           'surface rather than as a cloud of rods.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W).pack(anchor='w', padx=6, pady=(2, 2))
        for label in FILL_MODES:
            tk.Radiobutton(box, text=label, value=label, variable=self.faces_mode,
                           bg=BG, font=('Helvetica', 9), anchor='w',
                           command=self._on_faces_mode_change).pack(fill='x', padx=6)
        drow = tk.Frame(box, bg=BG)
        drow.pack(fill='x', padx=6, pady=(2, 6))
        tk.Label(drow, text='shade:', bg=BG, font=('Helvetica', 8), fg=HINT_FG,
                 width=7, anchor='w').pack(side='left')
        dens = ttk.Combobox(drow, textvariable=self.fill_density, state='readonly',
                            width=7, values=list(FILL_DENSITIES))
        dens.pack(side='left', fill='x', expand=True)
        dens.bind('<<ComboboxSelected>>', lambda _e: self._draw())

        box = tk.LabelFrame(parent, text='Deformed shape', bg=BG,
                            font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=4)
        tk.Checkbutton(box, text='Show the deflected model', variable=self.show_deformed,
                       bg=BG, font=('Helvetica', 9), anchor='w',
                       command=self._draw).pack(fill='x', padx=6)
        tk.Checkbutton(box, text='Only the deflected model', variable=self.deformed_only,
                       bg=BG, font=('Helvetica', 9), anchor='w',
                       command=self._draw).pack(fill='x', padx=6)
        drow = tk.Frame(box, bg=BG)
        drow.pack(fill='x', padx=6, pady=(2, 0))
        tk.Label(drow, text='scale ×', bg=BG, font=('Helvetica', 8),
                 fg=HINT_FG).pack(side='left')
        tk.Scale(drow, from_=1, to=500, orient='horizontal',
                 variable=self.deform_scale, bg=BG, font=('Helvetica', 7),
                 length=170, showvalue=True, command=lambda _v: self._draw()
                 ).pack(side='left', fill='x', expand=True)
        crow = tk.Frame(box, bg=BG)
        crow.pack(fill='x', padx=6, pady=(2, 6))
        tk.Label(crow, text='colour:', bg=BG, font=('Helvetica', 8),
                 fg=HINT_FG, width=7, anchor='w').pack(side='left')
        dbox = ttk.Combobox(crow, textvariable=self.deform_color_mode, state='readonly',
                            width=8, values=list(DEFORM_MODES))
        dbox.pack(side='left', fill='x', expand=True)
        dbox.bind('<<ComboboxSelected>>', lambda _e: self._draw())

        box = tk.LabelFrame(parent, text='Show', bg=BG,
                            font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=4)
        grid = tk.Frame(box, bg=BG)
        grid.pack(fill='x', padx=6, pady=(0, 6))
        toggles = (('Rods', self.show_members), ('Nodes', self.show_nodes),
                   ('Rod #', self.show_member_labels),
                   ('Node #', self.show_node_labels),
                   ('Loads', self.show_loads), ('Reactions', self.show_reactions),
                   ('Axes + ground', self.show_axes),
                   ('Load-path arrows', self.load_path_anim))
        for k, (text, var) in enumerate(toggles):
            cmd = (self._on_load_path_anim_toggle
                   if var is self.load_path_anim else self._draw)
            tk.Checkbutton(grid, text=text, variable=var, bg=BG,
                           font=('Helvetica', 8), anchor='w', command=cmd
                           ).grid(row=k // 2, column=k % 2, sticky='w')
        tk.Checkbutton(box, text='Base module card', variable=self.show_module_card,
                       bg=BG, font=('Helvetica', 8), anchor='w',
                       command=self._draw).pack(fill='x', padx=6, pady=(0, 4))

        box = tk.LabelFrame(parent, text='Analysis', bg=BG,
                            font=('Helvetica', 10, 'bold'))
        box.pack(fill='both', expand=True, padx=6, pady=4)
        self.analysis_canvas = tk.Canvas(box, width=PANEL_W - 30,
                                         height=self.ANALYSIS_CHART_H,
                                         bg=BG, highlightthickness=0)
        self.analysis_canvas.pack(fill='both', expand=True, padx=4, pady=4)

    def _refresh_analysis_charts(self):
        """Redraw every chart from the CURRENT results.

        Called on entering the mode and after each solve, never on a timer:
        a chart that is one solve behind the model is worse than no chart,
        because it looks authoritative.
        """
        c = getattr(self, 'analysis_canvas', None)
        if c is None:
            return
        c.delete('all')
        width = max(160, c.winfo_width() or (PANEL_W - 30))
        frac = self._load_frac()
        res = self.results or {}
        y = 0
        for draw in (
            # The cell census FIRST: it is a reading of the geometry, so it
            # is the only one of the four that says anything before Analyze
            # has ever been pressed. Fourth, it sat below the fold of a
            # scrolling panel and looked like a missing feature.
            lambda: self._draw_cell_census(c, width),
            lambda: sa.utilisation_histogram(c, width, self.member_checks, frac),
            lambda: sa.force_split(c, width, res.get('member_res'), frac),
            lambda: sa.support_reactions(c, width, res.get('reactions'),
                                         self.u('force'), frac),
        ):
            y += self._chart_at(c, y, draw)
        # Grow the canvas to whatever the charts needed. A fixed height cut
        # the reactions chart off on any model with more than a few supports,
        # and the panel scrolls anyway.
        c.configure(height=max(80, int(y)), scrollregion=(0, 0, width, max(y, 1)))
        self.panel_outer.fit_to_content()

    def _chart_at(self, c, y, draw):
        """Draw one chart, then slide everything it just created down to y.

        The chart functions all draw from the top of the canvas because that
        keeps them independent of each other and testable on their own; the
        stacking is this caller's job.
        """
        before = set(c.find_all())
        height = draw()
        for item in c.find_all():
            if item not in before:
                c.move(item, 0, y)
        return height

    def _draw_cell_census(self, c, width):
        """The buildability reading: how many DIFFERENT cells this mesh is
        made of. Uses the Module Editor's own classification so the two can
        never report different role counts for the same mesh."""
        try:
            cells = sg.find_cells(self.nodes, self.members)
            roles = sg.classify_cell_roles(self.nodes, cells)['roles']
        except (ValueError, KeyError, IndexError):
            cells, roles = [], {}
        return sa.cell_census(c, width, roles, cells)

    def _build_canvas(self, parent):

        canvas_frame = tk.Frame(parent, bg=BG)
        canvas_frame.pack(side='left', fill='both', expand=True)
        self.zc = ZoomCanvas(canvas_frame, bg=CANVAS_BG, bd=1, relief='solid')
        self.zc.pack(fill='both', expand=True)
        self.zc._on_zoom_changed = self._draw
        self.canvas = self.zc.canvas
        self.canvas.configure(cursor='fleur')
        # The canvas is a 1x1 stub until Tk actually lays the window out,
        # and that layout can take SEVERAL <Configure> events to settle
        # (the sidebar and canvas resolving their widths against each
        # other) -- each reporting a different intermediate size. Keep
        # re-centering on every Configure, using whatever size it reports
        # at that moment, until the user actually touches the view (pans,
        # zooms or orbits): that way the final settle is always centered
        # correctly regardless of how many intermediate passes happened,
        # but nothing ever overrides a view the user deliberately set up.
        self._view_touched = False
        self.canvas.bind('<Configure>', self._on_canvas_configure)
        # Left-drag is a Truss-style rubber-band LASSO that multi-selects
        # nodes; a plain left-click (no drag) still single-selects the
        # nearest node -- distinguished from a lasso drag by a small pixel
        # threshold in _on_canvas_motion, so neither gesture steals the
        # other. Orbit moves to RIGHT-drag so it no longer competes with
        # the lasso for the same button. Wheel zoom and middle-drag pan are
        # already wired by ZoomCanvas itself -- chained (add='+') rather
        # than replaced, purely to flag that the user has now taken control
        # of the view.
        self.canvas.bind('<Motion>', self._on_canvas_hover)
        self.canvas.bind('<ButtonPress-1>', self._on_canvas_press)
        self.canvas.bind('<B1-Motion>', self._on_canvas_motion)
        self.canvas.bind('<ButtonRelease-1>', self._on_canvas_release)
        self.canvas.bind('<ButtonPress-3>', self._on_orbit_press)
        self.canvas.bind('<B3-Motion>', self._on_orbit_motion)
        self.canvas.bind('<ButtonRelease-3>', self._on_orbit_release)
        for seq in ('<ButtonPress-2>', '<MouseWheel>', '<Button-4>', '<Button-5>'):
            self.canvas.bind(seq, self._mark_view_touched, add='+')

        # Delete/Backspace remove the selected node(s) -- bound on the
        # canvas itself (not root.bind_all), matching truss_app.py, so a
        # keypress only ever hits this while the canvas -- not a text entry
        # elsewhere in the panel -- actually has focus.
        self.canvas.bind('<Delete>', self._on_delete_nodes)
        self.canvas.bind('<BackSpace>', self._on_delete_nodes)
        self.canvas.focus_set()
        self._build_module_card(self.canvas)



    def _labeled_entry(self, parent, label, var, width=10):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill='x', padx=6, pady=1)
        tk.Label(row, text=label, bg=BG, width=16, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        tk.Entry(row, textvariable=var, width=width, font=('Helvetica', 9)).pack(side='left')
        return row

    def _section_label(self, box, text):
        tk.Label(box, text=text, bg=BG, font=('Helvetica', 10, 'bold')
                ).pack(anchor='w', padx=6, pady=(6, 2))

    # ── Geometry (per grid family) ───────────────────────────────────────────
    def _build_shape_panel(self, parent):
        """Surfaces, domain and lattice, edited in place.

        These used to live behind a modal wizard, which meant you could not
        see the model while changing the thing that makes it. Here they are
        a mode like any other: change a number, press Build, watch it
        change. The modal is still reachable from Generate for the keypad
        and the two-surface recipes an example carries.
        """
        surf = tk.LabelFrame(parent, text='Surface', bg=BG, font=('Helvetica', 10, 'bold'))
        surf.pack(fill='x', padx=6, pady=(6, 4))

        self.shape_two = tk.BooleanVar(value=False)
        tk.Radiobutton(surf, text='One surface', value=False, variable=self.shape_two,
                       bg=BG, font=('Helvetica', 9), command=self._on_shape_mode_change
                      ).pack(anchor='w', padx=6)
        tk.Radiobutton(surf, text='Two surfaces (top + bottom)', value=True,
                       variable=self.shape_two, bg=BG, font=('Helvetica', 9),
                       command=self._on_shape_mode_change).pack(anchor='w', padx=6)

        self.shape_z_top = tk.StringVar(value='0')
        self.shape_z_bot = tk.StringVar(value='0')
        self.shape_depth = tk.DoubleVar(value=1.5)
        self._shape_entry(surf, 'z top (x, y) =', self.shape_z_top)
        self.frame_shape_bot = tk.Frame(surf, bg=BG)
        self._shape_entry(self.frame_shape_bot, 'z bottom =', self.shape_z_bot)
        self.frame_shape_depth = tk.Frame(surf, bg=BG)
        self._labeled_entry(self.frame_shape_depth, 'Depth (m):', self.shape_depth)
        tk.Label(surf, text='x, y are metres in plan. Use the wizard under Generate for '
                            'parametric surfaces and the maths keypad.',
                 bg=BG, fg='#666', font=('Helvetica', 8), wraplength=PANEL_W - 44,
                 justify='left').pack(anchor='w', padx=6, pady=(2, 6))

        # ── lattice ──────────────────────────────────────────────────────
        lat = tk.LabelFrame(parent, text='Lattice', bg=BG, font=('Helvetica', 10, 'bold'))
        lat.pack(fill='x', padx=6, pady=(0, 4))
        tk.Label(lat, text='How the two layers register against each other -- the question '
                           'that actually names a space frame.',
                 bg=BG, fg='#666', font=('Helvetica', 8), wraplength=PANEL_W - 44,
                 justify='left').pack(anchor='w', padx=6, pady=(4, 2))
        self.shape_lattice = tk.StringVar(value=sg.LATTICE_SOS_OFFSET)
        for label in sg.LATTICE_TYPES:
            tk.Radiobutton(lat, text=label, value=label, variable=self.shape_lattice,
                           bg=BG, font=('Helvetica', 9), anchor='w',
                           command=self._on_shape_mode_change
                          ).pack(fill='x', padx=6)
        self.shape_lattice_note = tk.Label(lat, text='', bg=BG, fg='#a3241a',
                                           font=('Helvetica', 8),
                                           wraplength=PANEL_W - 44, justify='left')
        self.shape_lattice_note.pack(anchor='w', padx=6, pady=(2, 6))

        # ── domain ───────────────────────────────────────────────────────
        dom = tk.LabelFrame(parent, text='Domain', bg=BG, font=('Helvetica', 10, 'bold'))
        dom.pack(fill='x', padx=6, pady=(0, 4))
        self.shape_coord = tk.StringVar(value='cartesian')
        row = tk.Frame(dom, bg=BG)
        row.pack(fill='x', padx=6, pady=(4, 2))
        for label, value in (('Cartesian', 'cartesian'), ('Polar', 'polar')):
            tk.Radiobutton(row, text=label, value=value, variable=self.shape_coord,
                           bg=BG, font=('Helvetica', 9),
                           command=self._on_shape_mode_change).pack(side='left')
        self.shape_p0 = tk.DoubleVar(value=0.0)
        self.shape_p1 = tk.DoubleVar(value=12.0)
        self.shape_q0 = tk.DoubleVar(value=0.0)
        self.shape_q1 = tk.DoubleVar(value=12.0)
        self.shape_n1 = tk.IntVar(value=6)
        self.shape_n2 = tk.IntVar(value=6)
        self.shape_p_label = tk.StringVar(value='x from / to:')
        self.shape_q_label = tk.StringVar(value='y from / to:')
        self._shape_range(dom, self.shape_p_label, self.shape_p0, self.shape_p1, self.shape_n1)
        self._shape_range(dom, self.shape_q_label, self.shape_q0, self.shape_q1, self.shape_n2)
        self.shape_module_note = tk.Label(dom, text='', bg=BG, fg='#2f6f4f',
                                          font=('Helvetica', 8))
        self.shape_module_note.pack(anchor='w', padx=6, pady=(0, 4))

        self.shape_pole_x = tk.DoubleVar(value=0.0)
        self.shape_pole_y = tk.DoubleVar(value=0.0)
        self.frame_shape_pole = tk.Frame(dom, bg=BG)
        prow = tk.Frame(self.frame_shape_pole, bg=BG)
        prow.pack(fill='x', padx=6, pady=2)
        tk.Label(prow, text='pole:', bg=BG, width=9, anchor='w',
                 font=('Helvetica', 9)).pack(side='left')
        tk.Entry(prow, textvariable=self.shape_pole_x, width=7).pack(side='left')
        tk.Entry(prow, textvariable=self.shape_pole_y, width=7).pack(side='left', padx=(3, 0))
        tk.Button(self.frame_shape_pole, text='Find the summit(s)',
                  command=self._shape_find_summits).pack(anchor='w', padx=6, pady=(0, 2))
        self.shape_summit_note = tk.Label(self.frame_shape_pole, text='', bg=BG, fg='#666',
                                          font=('Helvetica', 8), wraplength=PANEL_W - 44,
                                          justify='left')
        self.shape_summit_note.pack(anchor='w', padx=6, pady=(0, 4))

        plan = self._pop_group(parent, 'Plan shape')
        tk.Label(plan, text='The domain above is a rectangle (or, in polar, a '
                            'sector), because two ranges cannot describe '
                            'anything else. This cuts that rectangle to a real '
                            'plan. Leave it empty to keep the whole of it.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_W - 40).pack(anchor='w', padx=6, pady=(2, 2))
        self.shape_plan = tk.StringVar(value='')
        self._shape_entry(plan, 'keep where:', self.shape_plan)
        for label, rule in SHAPE_PLAN_PRESETS:
            tk.Button(plan, text=label, font=('Helvetica', 8), anchor='w',
                      command=lambda r=rule: self._set_plan_rule(r)
                     ).pack(fill='x', padx=6, pady=1)
        self.shape_plan_note = tk.Label(plan, text='', bg=BG, fg='#666',
                                        font=('Helvetica', 8),
                                        wraplength=PANEL_W - 44, justify='left')
        self.shape_plan_note.pack(anchor='w', padx=6, pady=(2, 4))

        tk.Button(parent, text='Build this surface', font=('Helvetica', 9, 'bold'),
                  bg='#dff0d8', command=self._build_shape_mesh
                 ).pack(fill='x', padx=6, pady=(2, 4))
        self.shape_status = tk.Label(parent, text='', bg=BG, fg='#a3241a',
                                     font=('Helvetica', 8), wraplength=PANEL_W - 30,
                                     justify='left')
        self.shape_status.pack(anchor='w', padx=6)

        self.shape_recipe_var = tk.StringVar(value='')
        tk.Label(parent, textvariable=self.shape_recipe_var, bg=BG, fg='#2f6f4f',
                 font=('Helvetica', 8, 'italic'), wraplength=PANEL_W - 30,
                 justify='left').pack(anchor='w', padx=6, pady=(4, 8))
        self._on_shape_mode_change()

    # How many nodes each column style wants, and which of its fields mean
    # anything. A field that does nothing is worse than a missing one: it
    # invites you to set it and then ignores you.
    COLUMN_STYLE_HINTS = {
        sg.COLUMN_PLAIN: 'One post straight down from every node you select. '
                         'Any number of nodes.',
        sg.COLUMN_SHAFT: 'One shaft to a head, then a capital fanning up to '
                         'every node you select. At least 3 nodes.',
        sg.COLUMN_LATTICE: 'One chord straight down from each node you select, '
                           'X-braced between them. Exactly 3 or 4 nodes, and '
                           'no capital.',
        sg.COLUMN_TAPERED: 'As the latticed column, narrowing to 45% of your '
                           'footprint at the ground. Exactly 3 or 4 nodes.',
        sg.COLUMN_LEGS: 'Four inclined legs from their own square footprint up '
                        'to a head and capital. At least 3 nodes.',
        sg.COLUMN_TRIPOD: 'Three legs at 120 degrees, which cannot rock on an '
                          'uneven footing. At least 3 nodes.',
    }

    def _on_col_style_change(self):
        """Show only the fields the chosen column style actually reads."""
        style = self.col_style.get()
        latticed = style in (sg.COLUMN_LATTICE, sg.COLUMN_TAPERED)
        plain = style == sg.COLUMN_PLAIN
        footed = style in (sg.COLUMN_LEGS, sg.COLUMN_TRIPOD)
        # The latticed styles take their footprint from the selection and go
        # straight to the grid, so neither a width nor a capital means
        # anything to them; the plain strut has neither either.
        # Forget them all, then pack the wanted ones in a FIXED order, so the
        # panel reads the same whichever style you arrived from.
        order = ((self.frame_col_capital, not (latticed or plain)),
                 (self.frame_col_width, footed),
                 (self.frame_col_panels, latticed),
                 (self.frame_col_tiers, not (latticed or plain)))
        for frame, _wanted in order:
            frame.pack_forget()
        for frame, wanted in order:
            if wanted:
                frame.pack(fill='x', pady=(0, 1))
        self._col_hint.config(text=self.COLUMN_STYLE_HINTS.get(style, ''))

    def _set_plan_rule(self, rule):
        """Drop a ready-made plan rule into the field, centred on the domain
        the panel currently describes -- a circle written in raw metres is
        wrong the moment the domain moves, and nobody wants to re-derive
        the centre by hand to try a round roof."""
        try:
            x0, x1 = float(self.shape_p0.get()), float(self.shape_p1.get())
            y0, y1 = float(self.shape_q0.get()), float(self.shape_q1.get())
        except (tk.TclError, ValueError):
            x0, x1, y0, y1 = 0.0, 12.0, 0.0, 12.0
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        r = min(abs(x1 - x0), abs(y1 - y0)) / 2.0
        self.shape_plan.set(rule.format(cx=f'{cx:g}', cy=f'{cy:g}', r=f'{r:g}',
                                        rin=f'{r / 2.0:g}'))
        self.shape_plan_note.config(text='')

    def _shape_entry(self, parent, label, var):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill='x', padx=6, pady=2)
        tk.Label(row, text=label, bg=BG, width=12, anchor='w',
                 font=('Helvetica', 9)).pack(side='left')
        tk.Entry(row, textvariable=var, font=('Helvetica', 9)).pack(side='left',
                                                                    fill='x', expand=True)
        return row

    def _shape_range(self, parent, label_var, v0, v1, n):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill='x', padx=6, pady=2)
        tk.Label(row, textvariable=label_var, bg=BG, width=11, anchor='w',
                 font=('Helvetica', 9)).pack(side='left')
        tk.Entry(row, textvariable=v0, width=6).pack(side='left')
        tk.Entry(row, textvariable=v1, width=6).pack(side='left', padx=(3, 6))
        tk.Label(row, text='÷', bg=BG, font=('Helvetica', 9)).pack(side='left')
        tk.Entry(row, textvariable=n, width=4).pack(side='left', padx=(3, 0))

    def _on_shape_mode_change(self):
        """Show only the fields the chosen surface mode, lattice and domain
        actually use, and say what the resulting module size will be."""
        two = bool(self.shape_two.get())
        single = self.shape_lattice.get() == sg.LATTICE_SINGLE
        for frame in (self.frame_shape_bot, self.frame_shape_depth, self.frame_shape_pole):
            frame.pack_forget()
        if not single:
            (self.frame_shape_bot if two else self.frame_shape_depth).pack(fill='x')
        polar = self.shape_coord.get() == 'polar'
        self.shape_p_label.set('r from / to:' if polar else 'x from / to:')
        self.shape_q_label.set('θ from / to:' if polar else 'y from / to:')
        if polar:
            self.frame_shape_pole.pack(fill='x')
        self.shape_lattice_note.config(
            text=('A flat single layer of PINNED bars is a mechanism -- no out-of-plane '
                  'stiffness at all. Give it curvature, or set Rigid under Section.')
            if single else '')
        try:
            dp = (float(self.shape_p1.get()) - float(self.shape_p0.get())) / max(1, int(self.shape_n1.get()))
            dq = (float(self.shape_q1.get()) - float(self.shape_q0.get())) / max(1, int(self.shape_n2.get()))
            self.shape_module_note.config(text=f'module ≈ {abs(dp):.2f} × {abs(dq):.2f}')
        except (tk.TclError, ValueError, ZeroDivisionError):
            self.shape_module_note.config(text='')

    def _refresh_shape_note(self):
        """Keep the Shape mode honest about where the current model came
        from -- several models are generator output that no expression would
        reproduce, and saying otherwise would be worse than saying nothing."""
        recipe = getattr(self, '_wizard_recipe', None)
        if not recipe:
            self.shape_recipe_var.set('')
            return
        note = recipe.get('note', '')
        bits = []
        if recipe.get('mode') == 'between':
            bits.append('two surfaces')
        elif recipe.get('mode'):
            bits.append('one surface')
        if recipe.get('coord'):
            bits.append(f"{recipe['coord']} domain")
        if recipe.get('pattern'):
            bits.append(f"{recipe['pattern']} pattern")
        self.shape_recipe_var.set((' · '.join(bits) + '\n' + note) if bits else note)

    def _build_geometry_panel(self, parent):
        # Add-rod is a canvas TOOL, not display state: it edits the mesh, so
        # it lives with the mesh rather than behind the Display button.
        tools = tk.Frame(parent, bg=BG)
        tools.pack(fill='x', padx=6, pady=(6, 0))
        self.line_pick_mode = tk.BooleanVar(value=False)
        self.disc_pick_mode = tk.BooleanVar(value=False)
        self.disc_layer = tk.StringVar(value='top')
        self.disc_radius = tk.DoubleVar(value=0.8)
        self.disc_limit = tk.IntVar(value=4)
        self.add_rod_mode = tk.BooleanVar(value=False)
        tk.Checkbutton(tools, text='Line select (click two nodes)',
                       variable=self.line_pick_mode, bg=BG, font=('Helvetica', 9),
                       anchor='w',
                       command=lambda: self._on_pick_mode_toggle('line')).pack(anchor='w')
        tk.Label(tools, text='Selects every node the straight run between them '
                             'passes through -- a support line or a bracing row '
                             'in two clicks.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W).pack(anchor='w', padx=(18, 0))
        self.pick_note = tk.Label(tools, text='', bg=BG, fg='#2f6f4f',
                                  font=('Helvetica', 8), justify='left',
                                  wraplength=PANEL_TEXT_W, anchor='w')
        self.pick_note.pack(anchor='w', padx=(18, 0))
        tk.Checkbutton(tools, text='Add rod (click two nodes)', variable=self.add_rod_mode,
                       bg=BG, font=('Helvetica', 9),
                       command=self._on_add_rod_mode_toggle).pack(anchor='w')

        box = tk.LabelFrame(parent, text='Geometry', bg=BG, font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=(6, 4))

        self.fg_nx = tk.IntVar(value=10)
        self.fg_ny = tk.IntVar(value=10)
        self.fg_module = tk.DoubleVar(value=3.0)
        self.fg_depth = tk.DoubleVar(value=1.5)
        self.fg_offset = tk.BooleanVar(value=True)
        self.fg_pattern = tk.StringVar(value=PATTERN_LABEL['square'])
        self.frame_flat_grid = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_flat_grid, 'Modules X (nx):', self.fg_nx)
        self._labeled_entry(self.frame_flat_grid, 'Modules Y (ny):', self.fg_ny)
        self._labeled_entry(self.frame_flat_grid, 'Module size (m):', self.fg_module)
        self._labeled_entry(self.frame_flat_grid, 'Depth (m):', self.fg_depth)
        tk.Checkbutton(self.frame_flat_grid, text='Offset top layer (square-on-square offset)',
                       variable=self.fg_offset, bg=BG, font=('Helvetica', 8)
                      ).pack(anchor='w', padx=6, pady=(2, 4))
        pat_row = tk.Frame(self.frame_flat_grid, bg=BG)
        pat_row.pack(fill='x', padx=6, pady=(0, 4))
        tk.Label(pat_row, text='Chord pattern:', bg=BG, font=('Helvetica', 9)
                ).pack(side='left')
        pat_box = ttk.Combobox(pat_row, textvariable=self.fg_pattern, state='readonly',
                               width=8, values=[label for _key, label in GRID_PATTERNS])
        pat_box.pack(side='left', padx=(4, 0), fill='x', expand=True)

        self.bv_span = tk.DoubleVar(value=10.0)
        self.bv_rise = tk.DoubleVar(value=2.5)
        self.bv_length = tk.DoubleVar(value=15.0)
        self.bv_depth = tk.DoubleVar(value=0.6)
        self.bv_n_arch = tk.IntVar(value=8)
        self.bv_n_bays = tk.IntVar(value=8)
        self.bv_double = tk.BooleanVar(value=True)
        self.frame_barrel_vault = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_barrel_vault, 'Span (m):', self.bv_span)
        self._labeled_entry(self.frame_barrel_vault, 'Rise (m):', self.bv_rise)
        self._labeled_entry(self.frame_barrel_vault, 'Length (m):', self.bv_length)
        self._labeled_entry(self.frame_barrel_vault, 'Arch segments:', self.bv_n_arch)
        self._labeled_entry(self.frame_barrel_vault, 'Bays:', self.bv_n_bays)
        tk.Checkbutton(self.frame_barrel_vault, text='Double layer', variable=self.bv_double,
                       bg=BG, font=('Helvetica', 8)).pack(anchor='w', padx=6, pady=(2, 0))
        self._labeled_entry(self.frame_barrel_vault, 'Layer depth (m):', self.bv_depth)

        self.hp_nx = tk.IntVar(value=10)
        self.hp_ny = tk.IntVar(value=10)
        self.hp_module = tk.DoubleVar(value=3.0)
        self.hp_depth = tk.DoubleVar(value=1.5)
        self.hp_rise = tk.DoubleVar(value=2.0)
        self.hp_offset = tk.BooleanVar(value=True)
        self.hp_pattern = tk.StringVar(value=PATTERN_LABEL['square'])
        self.frame_hypar_shell = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_hypar_shell, 'Modules X (nx):', self.hp_nx)
        self._labeled_entry(self.frame_hypar_shell, 'Modules Y (ny):', self.hp_ny)
        self._labeled_entry(self.frame_hypar_shell, 'Module size (m):', self.hp_module)
        self._labeled_entry(self.frame_hypar_shell, 'Depth (m):', self.hp_depth)
        self._labeled_entry(self.frame_hypar_shell, 'Corner rise (m):', self.hp_rise)
        tk.Checkbutton(self.frame_hypar_shell, text='Offset top layer', variable=self.hp_offset,
                       bg=BG, font=('Helvetica', 8)).pack(anchor='w', padx=6, pady=(2, 4))
        self._pattern_row(self.frame_hypar_shell, self.hp_pattern)

        self.hr_nx = tk.IntVar(value=10)
        self.hr_ny = tk.IntVar(value=10)
        self.hr_module = tk.DoubleVar(value=3.0)
        self.hr_depth = tk.DoubleVar(value=1.5)
        self.hr_rise = tk.DoubleVar(value=3.0)
        self.hr_offset = tk.BooleanVar(value=True)
        self.hr_pattern = tk.StringVar(value=PATTERN_LABEL['square'])
        self.frame_hip_roof_grid = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_hip_roof_grid, 'Modules X (nx):', self.hr_nx)
        self._labeled_entry(self.frame_hip_roof_grid, 'Modules Y (ny):', self.hr_ny)
        self._labeled_entry(self.frame_hip_roof_grid, 'Module size (m):', self.hr_module)
        self._labeled_entry(self.frame_hip_roof_grid, 'Depth (m):', self.hr_depth)
        self._labeled_entry(self.frame_hip_roof_grid, 'Ridge rise (m):', self.hr_rise)
        tk.Checkbutton(self.frame_hip_roof_grid, text='Offset top layer', variable=self.hr_offset,
                       bg=BG, font=('Helvetica', 8)).pack(anchor='w', padx=6, pady=(2, 4))
        self._pattern_row(self.frame_hip_roof_grid, self.hr_pattern)

        self.gv_n = tk.IntVar(value=10)
        self.gv_module = tk.DoubleVar(value=1.2)
        self.gv_depth = tk.DoubleVar(value=0.5)
        self.gv_rise = tk.DoubleVar(value=3.0)
        self.gv_offset = tk.BooleanVar(value=True)
        self.gv_pattern = tk.StringVar(value=PATTERN_LABEL['square'])
        self.frame_groin_vault = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_groin_vault, 'Modules per side (n):', self.gv_n)
        self._labeled_entry(self.frame_groin_vault, 'Module size (m):', self.gv_module)
        self._labeled_entry(self.frame_groin_vault, 'Depth (m):', self.gv_depth)
        self._labeled_entry(self.frame_groin_vault, 'Crown rise (m):', self.gv_rise)
        tk.Checkbutton(self.frame_groin_vault, text='Offset top layer', variable=self.gv_offset,
                       bg=BG, font=('Helvetica', 8)).pack(anchor='w', padx=6, pady=(2, 4))
        self._pattern_row(self.frame_groin_vault, self.gv_pattern)

        self.cg_radius = tk.DoubleVar(value=10.0)
        self.cg_depth = tk.DoubleVar(value=1.5)
        self.cg_n_rings = tk.IntVar(value=4)
        self.cg_n_sectors = tk.IntVar(value=12)
        self.cg_offset = tk.BooleanVar(value=True)
        self.frame_circular_flat_grid = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_circular_flat_grid, 'Outer radius (m):', self.cg_radius)
        self._labeled_entry(self.frame_circular_flat_grid, 'Depth (m):', self.cg_depth)
        self._labeled_entry(self.frame_circular_flat_grid, 'Rings:', self.cg_n_rings)
        self._labeled_entry(self.frame_circular_flat_grid, 'Sectors:', self.cg_n_sectors)
        tk.Checkbutton(self.frame_circular_flat_grid, text='Offset top layer',
                       variable=self.cg_offset, bg=BG, font=('Helvetica', 8)
                      ).pack(anchor='w', padx=6, pady=(2, 4))

        self.dm_radius = tk.DoubleVar(value=10.0)
        self.dm_rise = tk.DoubleVar(value=3.0)
        self.dm_n_rings = tk.IntVar(value=4)
        self.dm_n_sectors = tk.IntVar(value=12)
        self.frame_dome = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_dome, 'Base radius (m):', self.dm_radius)
        self._labeled_entry(self.frame_dome, 'Rise (m):', self.dm_rise)
        self._labeled_entry(self.frame_dome, 'Rings:', self.dm_n_rings)
        self._labeled_entry(self.frame_dome, 'Sectors:', self.dm_n_sectors)

        self.cr_radius = tk.DoubleVar(value=8.0)
        self.cr_rise = tk.DoubleVar(value=5.0)
        self.cr_n_rings = tk.IntVar(value=4)
        self.cr_n_sectors = tk.IntVar(value=12)
        self.frame_cone_roof = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_cone_roof, 'Base radius (m):', self.cr_radius)
        self._labeled_entry(self.frame_cone_roof, 'Rise (m):', self.cr_rise)
        self._labeled_entry(self.frame_cone_roof, 'Rings:', self.cr_n_rings)
        self._labeled_entry(self.frame_cone_roof, 'Sectors:', self.cr_n_sectors)

        self.pv_span = tk.DoubleVar(value=10.0)
        self.pv_rise = tk.DoubleVar(value=2.5)
        self.pv_length = tk.DoubleVar(value=15.0)
        self.pv_depth = tk.DoubleVar(value=0.6)
        self.pv_n_arch = tk.IntVar(value=8)
        self.pv_n_bays = tk.IntVar(value=8)
        self.pv_double = tk.BooleanVar(value=True)
        self.frame_parabolic_vault = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_parabolic_vault, 'Span (m):', self.pv_span)
        self._labeled_entry(self.frame_parabolic_vault, 'Rise (m):', self.pv_rise)
        self._labeled_entry(self.frame_parabolic_vault, 'Length (m):', self.pv_length)
        self._labeled_entry(self.frame_parabolic_vault, 'Arch segments:', self.pv_n_arch)
        self._labeled_entry(self.frame_parabolic_vault, 'Bays:', self.pv_n_bays)
        tk.Checkbutton(self.frame_parabolic_vault, text='Double layer', variable=self.pv_double,
                       bg=BG, font=('Helvetica', 8)).pack(anchor='w', padx=6, pady=(2, 0))
        self._labeled_entry(self.frame_parabolic_vault, 'Layer depth (m):', self.pv_depth)

        self.ev_span = tk.DoubleVar(value=10.0)
        self.ev_rise = tk.DoubleVar(value=3.5)
        self.ev_length = tk.DoubleVar(value=15.0)
        self.ev_depth = tk.DoubleVar(value=0.6)
        self.ev_n_arch = tk.IntVar(value=8)
        self.ev_n_bays = tk.IntVar(value=8)
        self.ev_double = tk.BooleanVar(value=True)
        self.frame_elliptic_vault = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_elliptic_vault, 'Span (m):', self.ev_span)
        self._labeled_entry(self.frame_elliptic_vault, 'Rise (m):', self.ev_rise)
        self._labeled_entry(self.frame_elliptic_vault, 'Length (m):', self.ev_length)
        self._labeled_entry(self.frame_elliptic_vault, 'Arch segments:', self.ev_n_arch)
        self._labeled_entry(self.frame_elliptic_vault, 'Bays:', self.ev_n_bays)
        tk.Checkbutton(self.frame_elliptic_vault, text='Double layer', variable=self.ev_double,
                       bg=BG, font=('Helvetica', 8)).pack(anchor='w', padx=6, pady=(2, 0))
        self._labeled_entry(self.frame_elliptic_vault, 'Layer depth (m):', self.ev_depth)

        self.pd_radius = tk.DoubleVar(value=10.0)
        self.pd_rise = tk.DoubleVar(value=3.0)
        self.pd_n_rings = tk.IntVar(value=4)
        self.pd_n_sectors = tk.IntVar(value=12)
        self.frame_paraboloid_dish = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_paraboloid_dish, 'Rim radius (m):', self.pd_radius)
        self._labeled_entry(self.frame_paraboloid_dish, 'Rise (m):', self.pd_rise)
        self._labeled_entry(self.frame_paraboloid_dish, 'Rings:', self.pd_n_rings)
        self._labeled_entry(self.frame_paraboloid_dish, 'Sectors:', self.pd_n_sectors)

        self.ed_radius_x = tk.DoubleVar(value=10.0)
        self.ed_radius_y = tk.DoubleVar(value=6.0)
        self.ed_rise = tk.DoubleVar(value=3.0)
        self.ed_n_rings = tk.IntVar(value=4)
        self.ed_n_sectors = tk.IntVar(value=12)
        self.frame_elliptic_dome = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_elliptic_dome, 'Base radius X (m):', self.ed_radius_x)
        self._labeled_entry(self.frame_elliptic_dome, 'Base radius Y (m):', self.ed_radius_y)
        self._labeled_entry(self.frame_elliptic_dome, 'Rise (m):', self.ed_rise)
        self._labeled_entry(self.frame_elliptic_dome, 'Rings:', self.ed_n_rings)
        self._labeled_entry(self.frame_elliptic_dome, 'Sectors:', self.ed_n_sectors)

        self.sp_radius = tk.DoubleVar(value=5.0)
        self.sp_n_rings = tk.IntVar(value=4)
        self.sp_n_sectors = tk.IntVar(value=12)
        self.frame_sphere_shell = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_sphere_shell, 'Radius (m):', self.sp_radius)
        self._labeled_entry(self.frame_sphere_shell, 'Rings per hemisphere:', self.sp_n_rings)
        self._labeled_entry(self.frame_sphere_shell, 'Sectors:', self.sp_n_sectors)

        self.tb_span = tk.DoubleVar(value=40.0)
        self.tb_depth = tk.DoubleVar(value=5.0)
        self.tb_width = tk.DoubleVar(value=8.0)
        self.tb_n_panels = tk.IntVar(value=8)
        self.frame_truss_bridge = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_truss_bridge, 'Span (m):', self.tb_span)
        self._labeled_entry(self.frame_truss_bridge, 'Truss depth (m):', self.tb_depth)
        self._labeled_entry(self.frame_truss_bridge, 'Deck width (m):', self.tb_width)
        self._labeled_entry(self.frame_truss_bridge, 'Panels:', self.tb_n_panels)

        self.vd_nx = tk.IntVar(value=6)
        self.vd_ny = tk.IntVar(value=6)
        self.vd_module = tk.DoubleVar(value=3.0)
        self.vd_depth = tk.DoubleVar(value=2.0)
        self.frame_vierendeel_grid = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_vierendeel_grid, 'Modules X (nx):', self.vd_nx)
        self._labeled_entry(self.frame_vierendeel_grid, 'Modules Y (ny):', self.vd_ny)
        self._labeled_entry(self.frame_vierendeel_grid, 'Module size (m):', self.vd_module)
        self._labeled_entry(self.frame_vierendeel_grid, 'Depth (m):', self.vd_depth)
        tk.Label(self.frame_vierendeel_grid,
                 text='Two aligned layers joined by vertical posts, and no '
                      'diagonals anywhere -- rectangular openings you can run '
                      'a duct or a walkway through. It carries load by BENDING '
                      'its members, so its joints are forced rigid (pinned, a '
                      'rectangle of four bars lozenges) and its members need I '
                      'and J, not just E and A. Expect it to deflect several '
                      'times more than a triangulated grid of the same depth: '
                      'that is the price of the openings, not a fault.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W).pack(anchor='w', padx=6, pady=(2, 4))

        # ── the ten geometrically-controlled families ───────────────────
        # Five of them are height fields over the same rectangular plan
        # flat_grid already brackets, so they reuse its whole bracing
        # scheme and differ only in z; the vault is one more arch profile
        # on the extruded-arch engine; the last four need their own
        # revolved/swept lattices (see stereo_geometry_surfaces).
        self.ep_nx = tk.IntVar(value=6)
        self.ep_ny = tk.IntVar(value=6)
        self.ep_module = tk.DoubleVar(value=3.0)
        self.ep_depth = tk.DoubleVar(value=1.2)
        self.ep_rise = tk.DoubleVar(value=4.0)
        self.ep_offset = tk.BooleanVar(value=True)
        self.ep_pattern = tk.StringVar(value=PATTERN_LABEL['square'])
        self.frame_elliptic_paraboloid_shell = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_elliptic_paraboloid_shell, 'Modules X (nx):', self.ep_nx)
        self._labeled_entry(self.frame_elliptic_paraboloid_shell, 'Modules Y (ny):', self.ep_ny)
        self._labeled_entry(self.frame_elliptic_paraboloid_shell, 'Module size (m):', self.ep_module)
        self._labeled_entry(self.frame_elliptic_paraboloid_shell, 'Depth (m):', self.ep_depth)
        self._labeled_entry(self.frame_elliptic_paraboloid_shell, 'Crown rise (m):', self.ep_rise)
        tk.Checkbutton(self.frame_elliptic_paraboloid_shell, text='Offset top layer',
                       variable=self.ep_offset, bg=BG, font=('Helvetica', 8)
                      ).pack(anchor='w', padx=6, pady=(2, 4))
        self._pattern_row(self.frame_elliptic_paraboloid_shell, self.ep_pattern)
        self._family_hint(self.frame_elliptic_paraboloid_shell,
                          'A dish, not a saddle: both curvatures bend the same '
                          'way, so a downward load goes into compression along '
                          'BOTH spans. Zero at the four plan corners and rise/2 '
                          'halfway along each edge -- a quadratic cannot be level '
                          'all the way round, which is why a real one takes an '
                          'edge beam or bears on the corners alone.')

        self.eh_nx = tk.IntVar(value=6)
        self.eh_ny = tk.IntVar(value=6)
        self.eh_module = tk.DoubleVar(value=3.0)
        self.eh_depth = tk.DoubleVar(value=1.2)
        self.eh_rise_x = tk.DoubleVar(value=3.0)
        self.eh_rise_y = tk.DoubleVar(value=2.0)
        self.eh_offset = tk.BooleanVar(value=True)
        self.eh_pattern = tk.StringVar(value=PATTERN_LABEL['square'])
        self.frame_elliptic_hypar_shell = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_elliptic_hypar_shell, 'Modules X (nx):', self.eh_nx)
        self._labeled_entry(self.frame_elliptic_hypar_shell, 'Modules Y (ny):', self.eh_ny)
        self._labeled_entry(self.frame_elliptic_hypar_shell, 'Module size (m):', self.eh_module)
        self._labeled_entry(self.frame_elliptic_hypar_shell, 'Depth (m):', self.eh_depth)
        self._labeled_entry(self.frame_elliptic_hypar_shell, 'Rise along X (m):', self.eh_rise_x)
        self._labeled_entry(self.frame_elliptic_hypar_shell, 'Fall along Y (m):', self.eh_rise_y)
        tk.Checkbutton(self.frame_elliptic_hypar_shell, text='Offset top layer',
                       variable=self.eh_offset, bg=BG, font=('Helvetica', 8)
                      ).pack(anchor='w', padx=6, pady=(2, 4))
        self._pattern_row(self.frame_elliptic_hypar_shell, self.eh_pattern)
        self._family_hint(self.frame_elliptic_hypar_shell,
                          'The general saddle: it ARCHES along one span and HANGS '
                          'along the other, with the two curvatures set '
                          'independently instead of the plain hypar\'s equal and '
                          'opposite pair. Set the two equal for a rotated plain '
                          'hypar; set them far apart for a deep arch across a '
                          'short span with a shallow suspension along a long one.')

        self.co_nx = tk.IntVar(value=6)
        self.co_ny = tk.IntVar(value=4)
        self.co_module = tk.DoubleVar(value=3.0)
        self.co_depth = tk.DoubleVar(value=1.2)
        self.co_rise = tk.DoubleVar(value=4.0)
        self.co_offset = tk.BooleanVar(value=True)
        self.co_pattern = tk.StringVar(value=PATTERN_LABEL['square'])
        self.frame_conoid_shell = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_conoid_shell, 'Modules X (nx):', self.co_nx)
        self._labeled_entry(self.frame_conoid_shell, 'Modules Y (ny):', self.co_ny)
        self._labeled_entry(self.frame_conoid_shell, 'Module size (m):', self.co_module)
        self._labeled_entry(self.frame_conoid_shell, 'Depth (m):', self.co_depth)
        self._labeled_entry(self.frame_conoid_shell, 'Arch rise (m):', self.co_rise)
        tk.Checkbutton(self.frame_conoid_shell, text='Offset top layer',
                       variable=self.co_offset, bg=BG, font=('Helvetica', 8)
                      ).pack(anchor='w', padx=6, pady=(2, 4))
        self._pattern_row(self.frame_conoid_shell, self.co_pattern)
        self._family_hint(self.frame_conoid_shell,
                          'Straight and level along the y=0 edge, a full sine arch '
                          'at the far one, and every line between them dead '
                          'straight -- a ruled surface, so the formwork and every '
                          'y-direction chord is a straight member. The classic '
                          'north-light saw-tooth bay: stiff at the tall edge, flat '
                          'at the low one, meant to be repeated.')

        self.ms_nx = tk.IntVar(value=6)
        self.ms_ny = tk.IntVar(value=6)
        self.ms_module = tk.DoubleVar(value=3.0)
        self.ms_depth = tk.DoubleVar(value=1.2)
        self.ms_rise = tk.DoubleVar(value=1.5)
        self.ms_offset = tk.BooleanVar(value=True)
        self.ms_pattern = tk.StringVar(value=PATTERN_LABEL['square'])
        self.frame_monkey_saddle_shell = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_monkey_saddle_shell, 'Modules X (nx):', self.ms_nx)
        self._labeled_entry(self.frame_monkey_saddle_shell, 'Modules Y (ny):', self.ms_ny)
        self._labeled_entry(self.frame_monkey_saddle_shell, 'Module size (m):', self.ms_module)
        self._labeled_entry(self.frame_monkey_saddle_shell, 'Depth (m):', self.ms_depth)
        self._labeled_entry(self.frame_monkey_saddle_shell, 'Amplitude (m):', self.ms_rise)
        tk.Checkbutton(self.frame_monkey_saddle_shell, text='Offset top layer',
                       variable=self.ms_offset, bg=BG, font=('Helvetica', 8)
                      ).pack(anchor='w', padx=6, pady=(2, 4))
        self._pattern_row(self.frame_monkey_saddle_shell, self.ms_pattern)
        self._family_hint(self.frame_monkey_saddle_shell,
                          'Three rises and three falls around the centre instead '
                          'of a saddle\'s two of each. Worth generating for the '
                          'warning as much as the sculpture: the centre is a '
                          'monkey point, where BOTH curvatures vanish, so there is '
                          'no shell action there at all and the middle leans on the '
                          'grid depth alone. Run Analyze and look at it.')

        self.wv_nx = tk.IntVar(value=12)
        self.wv_ny = tk.IntVar(value=6)
        self.wv_module = tk.DoubleVar(value=2.0)
        self.wv_depth = tk.DoubleVar(value=1.0)
        self.wv_rise = tk.DoubleVar(value=3.0)
        self.wv_waves = tk.DoubleVar(value=2.0)
        self.wv_offset = tk.BooleanVar(value=True)
        self.wv_pattern = tk.StringVar(value=PATTERN_LABEL['square'])
        self.frame_wave_shell = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_wave_shell, 'Modules X (nx):', self.wv_nx)
        self._labeled_entry(self.frame_wave_shell, 'Modules Y (ny):', self.wv_ny)
        self._labeled_entry(self.frame_wave_shell, 'Module size (m):', self.wv_module)
        self._labeled_entry(self.frame_wave_shell, 'Depth (m):', self.wv_depth)
        self._labeled_entry(self.frame_wave_shell, 'Crest height (m):', self.wv_rise)
        self._labeled_entry(self.frame_wave_shell, 'Waves across X:', self.wv_waves)
        tk.Checkbutton(self.frame_wave_shell, text='Offset top layer',
                       variable=self.wv_offset, bg=BG, font=('Helvetica', 8)
                      ).pack(anchor='w', padx=6, pady=(2, 4))
        self._pattern_row(self.frame_wave_shell, self.wv_pattern)
        self._family_hint(self.frame_wave_shell,
                          'The undulating white shell roof -- Bosjes Chapel and its '
                          'kind. Each trough-to-trough wave is an arch, and the '
                          'crest-to-trough corrugation gives the roof far more '
                          'effective depth than the grid itself has, which is why '
                          'such a roof can be thin and still span. Support it at '
                          'the TROUGHS and let the crests fly. A whole number of '
                          'waves starts and ends in a trough; a half gives crests '
                          'at both ends. It is straight along y, so give the ends '
                          'a diaphragm or an edge arch.')

        self.bw_nx = tk.IntVar(value=12)
        self.bw_ny = tk.IntVar(value=12)
        self.bw_module = tk.DoubleVar(value=2.0)
        self.bw_depth = tk.DoubleVar(value=1.2)
        self.bw_rise = tk.DoubleVar(value=4.0)
        self.bw_waves_x = tk.DoubleVar(value=2.0)
        self.bw_waves_y = tk.DoubleVar(value=2.0)
        self.bw_offset = tk.BooleanVar(value=True)
        self.bw_pattern = tk.StringVar(value=PATTERN_LABEL['square'])
        self.frame_billow_shell = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_billow_shell, 'Modules X (nx):', self.bw_nx)
        self._labeled_entry(self.frame_billow_shell, 'Modules Y (ny):', self.bw_ny)
        self._labeled_entry(self.frame_billow_shell, 'Module size (m):', self.bw_module)
        self._labeled_entry(self.frame_billow_shell, 'Depth (m):', self.bw_depth)
        self._labeled_entry(self.frame_billow_shell, 'Crest height (m):', self.bw_rise)
        self._labeled_entry(self.frame_billow_shell, 'Half waves X:', self.bw_waves_x)
        self._labeled_entry(self.frame_billow_shell, 'Half waves Y:', self.bw_waves_y)
        tk.Checkbutton(self.frame_billow_shell, text='Offset top layer',
                       variable=self.bw_offset, bg=BG, font=('Helvetica', 8)
                      ).pack(anchor='w', padx=6, pady=(2, 4))
        self._pattern_row(self.frame_billow_shell, self.bw_pattern)
        self._family_hint(self.frame_billow_shell,
                          'The cloth pinned at its low points -- Bosjes Chapel '
                          'and its kind. It waves in BOTH directions, so unlike '
                          'the one-way wave it has curvature everywhere and '
                          'carries load by shell action rather than as a row of '
                          'parallel arches. At 2 and 2 the surface dips to '
                          '-crest at the MIDDLE OF EACH EDGE and rises to +crest '
                          'at all four CORNERS and at the centre: support it at '
                          'those four edge lows ONLY and the corners fly. 1 and '
                          '1 gives a single bubble, zero all round the edge. The '
                          'zero lines a quarter and three quarters across each '
                          'span are where the chords swap tension for '
                          'compression -- look at them in Analyse before sizing.')

        self.cv_span = tk.DoubleVar(value=12.0)
        self.cv_rise = tk.DoubleVar(value=5.0)
        self.cv_length = tk.DoubleVar(value=18.0)
        self.cv_depth = tk.DoubleVar(value=0.6)
        self.cv_shape = tk.DoubleVar(value=2.0)
        self.cv_n_arch = tk.IntVar(value=8)
        self.cv_n_bays = tk.IntVar(value=8)
        self.cv_double = tk.BooleanVar(value=True)
        self.frame_catenary_vault = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_catenary_vault, 'Span (m):', self.cv_span)
        self._labeled_entry(self.frame_catenary_vault, 'Rise (m):', self.cv_rise)
        self._labeled_entry(self.frame_catenary_vault, 'Length (m):', self.cv_length)
        self._labeled_entry(self.frame_catenary_vault, 'Catenary shape:', self.cv_shape)
        self._labeled_entry(self.frame_catenary_vault, 'Arch segments:', self.cv_n_arch)
        self._labeled_entry(self.frame_catenary_vault, 'Bays:', self.cv_n_bays)
        tk.Checkbutton(self.frame_catenary_vault, text='Double layer', variable=self.cv_double,
                       bg=BG, font=('Helvetica', 8)).pack(anchor='w', padx=6, pady=(2, 0))
        self._labeled_entry(self.frame_catenary_vault, 'Layer depth (m):', self.cv_depth)
        self._family_hint(self.frame_catenary_vault,
                          'A hanging chain takes a catenary under its own weight, '
                          'so an arch of that curve inverted carries its own weight '
                          'in PURE COMPRESSION, thrust line exactly on the axis. '
                          'That is the masonry and concrete vault form, and it is '
                          'not the parabola (which suits a load uniform per '
                          'horizontal metre -- a suspension deck). Shape sets how '
                          'pointed it is: small approaches a parabola, large gives '
                          'the steep Gaudi arch. The pure-compression property is '
                          'for SELF-WEIGHT ONLY; wind or drift puts bending back.')

        self.ts_major = tk.DoubleVar(value=14.0)
        self.ts_tube = tk.DoubleVar(value=5.0)
        self.ts_sweep = tk.DoubleVar(value=180.0)
        self.ts_arc = tk.DoubleVar(value=180.0)
        self.ts_n_sweep = tk.IntVar(value=16)
        self.ts_n_arc = tk.IntVar(value=6)
        self.ts_depth = tk.DoubleVar(value=0.6)
        self.ts_pattern = tk.StringVar(value=PATTERN_LABEL['square'])
        self.frame_torus_segment = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_torus_segment, 'Plan radius (m):', self.ts_major)
        self._labeled_entry(self.frame_torus_segment, 'Tube radius (m):', self.ts_tube)
        self._labeled_entry(self.frame_torus_segment, 'Plan sweep (deg):', self.ts_sweep)
        self._labeled_entry(self.frame_torus_segment, 'Section arc (deg):', self.ts_arc)
        self._labeled_entry(self.frame_torus_segment, 'Bays round sweep:', self.ts_n_sweep)
        self._labeled_entry(self.frame_torus_segment, 'Segments across:', self.ts_n_arc)
        self._labeled_entry(self.frame_torus_segment, 'Layer depth (m):', self.ts_depth)
        self._pattern_row(self.frame_torus_segment, self.ts_pattern)
        self._family_hint(self.frame_torus_segment,
                          'A vault section swept round a circular plan: the curved '
                          'arcade, the annular concourse. Doubly curved where it '
                          'counts -- the section arches across and the plan arches '
                          'along -- so unlike a straight barrel vault, which is '
                          'developable and wants an end diaphragm, a full 360 sweep '
                          'braces itself: the hoops cannot lengthen without the '
                          'whole ring growing. Set the sweep to exactly 360 to '
                          'close the seam. Layer depth 0 gives a single layer.')

        self.hb_radius = tk.DoubleVar(value=5.0)
        self.hb_height = tk.DoubleVar(value=24.0)
        self.hb_n_rings = tk.IntVar(value=6)
        self.hb_n_sectors = tk.IntVar(value=16)
        self.hb_twist = tk.IntVar(value=1)
        self.hb_brace = tk.StringVar(value=BRACE_LABEL['counter'])
        self.frame_hyperboloid_tower = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_hyperboloid_tower, 'Waist radius (m):', self.hb_radius)
        self._labeled_entry(self.frame_hyperboloid_tower, 'Height (m):', self.hb_height)
        self._labeled_entry(self.frame_hyperboloid_tower, 'Ring courses:', self.hb_n_rings)
        self._labeled_entry(self.frame_hyperboloid_tower, 'Sectors:', self.hb_n_sectors)
        self._labeled_entry(self.frame_hyperboloid_tower, 'Twist (sectors):', self.hb_twist)
        self._brace_row(self.frame_hyperboloid_tower, self.hb_brace)
        self._family_hint(self.frame_hyperboloid_tower,
                          'Shukhov\'s tower: a doubly curved shell made ENTIRELY of '
                          'straight bars, because a hyperboloid of one sheet is '
                          'doubly ruled -- two straight lines of the surface run '
                          'through every point of it. Every diagonal here lies on '
                          'the surface exactly, not as a chord approximating a '
                          'curve. Twist sets the flare: half-angle = rings x twist '
                          'x 90 / sectors degrees, and the end rings are 1/cos of '
                          'that times the waist.')

        self.eb_radius_x = tk.DoubleVar(value=6.0)
        self.eb_radius_y = tk.DoubleVar(value=3.5)
        self.eb_height = tk.DoubleVar(value=20.0)
        self.eb_n_rings = tk.IntVar(value=6)
        self.eb_n_sectors = tk.IntVar(value=16)
        self.eb_twist = tk.IntVar(value=1)
        self.eb_brace = tk.StringVar(value=BRACE_LABEL['counter'])
        self.frame_elliptic_hyperboloid = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_elliptic_hyperboloid, 'Waist radius X (m):', self.eb_radius_x)
        self._labeled_entry(self.frame_elliptic_hyperboloid, 'Waist radius Y (m):', self.eb_radius_y)
        self._labeled_entry(self.frame_elliptic_hyperboloid, 'Height (m):', self.eb_height)
        self._labeled_entry(self.frame_elliptic_hyperboloid, 'Ring courses:', self.eb_n_rings)
        self._labeled_entry(self.frame_elliptic_hyperboloid, 'Sectors:', self.eb_n_sectors)
        self._labeled_entry(self.frame_elliptic_hyperboloid, 'Twist (sectors):', self.eb_twist)
        self._brace_row(self.frame_elliptic_hyperboloid, self.eb_brace)
        self._family_hint(self.frame_elliptic_hyperboloid,
                          'The same ruled surface squashed to an elliptical plan. '
                          'An ellipse is a circle under an affine map and an affine '
                          'map takes straight lines to straight lines, so every '
                          'diagonal is STILL an exact generator. What changes is '
                          'that the nodes stop being equivalent: member lengths vary '
                          'round each ring, and the flatter sides of the plan are '
                          'the softer ones against a horizontal load.')

        self.hl_inner = tk.DoubleVar(value=4.0)
        self.hl_outer = tk.DoubleVar(value=9.0)
        self.hl_turns = tk.DoubleVar(value=1.0)
        self.hl_rise = tk.DoubleVar(value=3.2)
        self.hl_n_radial = tk.IntVar(value=4)
        self.hl_n_along = tk.IntVar(value=24)
        self.hl_depth = tk.DoubleVar(value=0.8)
        self.hl_pattern = tk.StringVar(value=PATTERN_LABEL['square'])
        self.frame_helicoid_ramp = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_helicoid_ramp, 'Inner radius (m):', self.hl_inner)
        self._labeled_entry(self.frame_helicoid_ramp, 'Outer radius (m):', self.hl_outer)
        self._labeled_entry(self.frame_helicoid_ramp, 'Turns:', self.hl_turns)
        self._labeled_entry(self.frame_helicoid_ramp, 'Rise per turn (m):', self.hl_rise)
        self._labeled_entry(self.frame_helicoid_ramp, 'Bays across:', self.hl_n_radial)
        self._labeled_entry(self.frame_helicoid_ramp, 'Bays along run:', self.hl_n_along)
        self._labeled_entry(self.frame_helicoid_ramp, 'Deck depth (m):', self.hl_depth)
        self._pattern_row(self.frame_helicoid_ramp, self.hl_pattern)
        self._family_hint(self.frame_helicoid_ramp,
                          'A car-park ramp, a spiral stair: a minimal surface whose '
                          'every radial line is straight and level. That is also '
                          'the problem -- it has NO arch action in either '
                          'direction, so it spans by bending and torsion, and a '
                          'load on the outer edge twists the deck. Give it real '
                          'depth and watch the outer edge. Deck depth 0 gives a '
                          'single layer, which is forced to RIGID joints: a pinned '
                          'one is not a structure.')

        self._param_frames = {'flat_grid': self.frame_flat_grid,
                              'vierendeel_grid': self.frame_vierendeel_grid,
                              'hypar_shell': self.frame_hypar_shell,
                              'hip_roof_grid': self.frame_hip_roof_grid,
                              'groin_vault': self.frame_groin_vault,
                              'circular_flat_grid': self.frame_circular_flat_grid,
                              'barrel_vault': self.frame_barrel_vault,
                              'parabolic_vault': self.frame_parabolic_vault,
                              'elliptic_vault': self.frame_elliptic_vault,
                              'dome': self.frame_dome,
                              'cone_roof': self.frame_cone_roof,
                              'paraboloid_dish': self.frame_paraboloid_dish,
                              'elliptic_dome': self.frame_elliptic_dome,
                              'sphere_shell': self.frame_sphere_shell,
                              'truss_bridge': self.frame_truss_bridge,
                              'elliptic_paraboloid_shell': self.frame_elliptic_paraboloid_shell,
                              'elliptic_hypar_shell': self.frame_elliptic_hypar_shell,
                              'conoid_shell': self.frame_conoid_shell,
                              'monkey_saddle_shell': self.frame_monkey_saddle_shell,
                              'wave_shell': self.frame_wave_shell,
                              'billow_shell': self.frame_billow_shell,
                              'catenary_vault': self.frame_catenary_vault,
                              'torus_segment': self.frame_torus_segment,
                              'hyperboloid_tower': self.frame_hyperboloid_tower,
                              'elliptic_hyperboloid': self.frame_elliptic_hyperboloid,
                              'helicoid_ramp': self.frame_helicoid_ramp}

    def _family_hint(self, parent, text):
        """The one-paragraph "what is this shape FOR, and what does it cost
        you" note under a family's own parameters. Every one of these says
        something the parameter names cannot: which way the surface carries
        load, where it is soft, and what a real one needs that the generator
        does not draw."""
        tk.Label(parent, text=text, bg=BG, fg=HINT_FG, font=('Helvetica', 8),
                 justify='left', wraplength=PANEL_TEXT_W
                ).pack(anchor='w', padx=6, pady=(2, 4))

    def _brace_row(self, parent, var):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill='x', padx=6, pady=(0, 4))
        tk.Label(row, text='Bracing:', bg=BG, font=('Helvetica', 9)).pack(side='left')
        ttk.Combobox(row, textvariable=var, state='readonly', width=8,
                     values=[label for _key, label in HYPERBOLOID_BRACES]
                    ).pack(side='left', padx=(4, 0), fill='x', expand=True)

    def _pattern_row(self, parent, var):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill='x', padx=6, pady=(0, 4))
        tk.Label(row, text='Chord pattern:', bg=BG, font=('Helvetica', 9)).pack(side='left')
        box = ttk.Combobox(row, textvariable=var, state='readonly', width=8,
                           values=[label for _key, label in GRID_PATTERNS])
        box.pack(side='left', padx=(4, 0), fill='x', expand=True)

    # ── Supports ─────────────────────────────────────────────────────────────
    def _build_supports_panel(self, parent):
        box = tk.LabelFrame(parent, text='Supports', bg=BG, font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=4)

        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=6, pady=(4, 6))
        self.sup_quick_var = tk.StringVar(value=QUICK_SUPPORT_PIN)
        quick_box = ttk.Combobox(row, textvariable=self.sup_quick_var, state='readonly',
                                 width=24, values=QUICK_SUPPORT_CHOICES)
        quick_box.pack(fill='x')
        quick_box.bind('<<ComboboxSelected>>', lambda e: self._apply_quick_support_preset())

        adv = tk.LabelFrame(box, text='Per node', bg=BG, font=('Helvetica', 8, 'bold'))
        adv.pack(fill='x', padx=6, pady=(0, 6))
        tk.Label(adv, text='Any combination of the six DOFs.', bg=BG, fg='#666',
                 font=('Helvetica', 8), wraplength=PANEL_W - 40, justify='left'
                 ).pack(anchor='w', padx=4, pady=(2, 0))

        row = tk.Frame(adv, bg=BG)
        row.pack(fill='x', padx=4, pady=2)
        tk.Label(row, text='Node:', bg=BG, width=8, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        self.sup_node_var = tk.IntVar(value=0)
        tk.Entry(row, textvariable=self.sup_node_var, width=6).pack(side='left')
        tk.Label(row, text='Preset:', bg=BG, font=('Helvetica', 9)).pack(side='left', padx=(8, 2))
        self.sup_preset_var = tk.StringVar(value='pin')
        preset_box = ttk.Combobox(row, textvariable=self.sup_preset_var, state='readonly',
                                  width=8, values=PRESET_NAMES)
        preset_box.pack(side='left')
        preset_box.bind('<<ComboboxSelected>>', lambda e: self._preset_to_checkboxes())

        dof_row = tk.Frame(adv, bg=BG)
        dof_row.pack(fill='x', padx=4, pady=4)
        self.dof_vars = {}
        for d, lbl in DOF_LABELS:
            v = tk.BooleanVar(value=False)
            self.dof_vars[d] = v
            tk.Checkbutton(dof_row, text=lbl, variable=v, font=('Helvetica', 8),
                          command=lambda: self.sup_preset_var.set('custom')
                          ).pack(side='left')
        self._preset_to_checkboxes()

        btn_row = tk.Frame(adv, bg=BG)
        btn_row.pack(fill='x', padx=4, pady=(2, 4))
        tk.Button(btn_row, text='Apply to node', command=self._apply_support).pack(side='left', padx=2)
        tk.Button(btn_row, text='Remove', command=self._remove_support).pack(side='left', padx=2)

        self.sup_list = tk.Listbox(adv, height=5, font=('Courier', 8))
        self.sup_list.pack(fill='x', padx=4, pady=(0, 4))
        self.sup_list.bind('<<ListboxSelect>>', self._on_support_list_select)

        sandbox = tk.LabelFrame(box, text='Support sandbox', bg=BG,
                                font=('Helvetica', 8, 'bold'))
        sandbox.pack(fill='x', padx=6, pady=(0, 6))
        self.support_sandbox = tk.BooleanVar(value=False)
        tk.Checkbutton(sandbox, text='Click a support to disable/enable it (no re-solve '
                                     'needed to try again)',
                       variable=self.support_sandbox, bg=BG, font=('Helvetica', 8),
                       wraplength=PANEL_TEXT_W, justify='left', command=self._draw
                      ).pack(anchor='w', padx=4, pady=(4, 0))
        tk.Label(sandbox, text='Disabled supports are excluded from the next Analyze -- '
                              'build intuition for redundancy without editing the model.',
                bg=BG, fg='#666', font=('Helvetica', 8), wraplength=PANEL_TEXT_W,
                justify='left').pack(anchor='w', padx=4, pady=(2, 4))
        tk.Button(sandbox, text='Reset sandbox (re-enable all)',
                 command=self._reset_support_sandbox).pack(anchor='w', padx=4, pady=(0, 4))

    def _reset_support_sandbox(self):
        if not self._disabled_supports:
            return
        self._disabled_supports = set()
        self._refresh_indeterminacy_label()
        self._draw()

    # ── Loads ────────────────────────────────────────────────────────────────
    def _build_loads_panel(self, parent):
        box = tk.LabelFrame(parent, text='Loads', bg=BG, font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=4)

        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=6, pady=(4, 2))
        tk.Label(row, text='Area load q (kN/m²):', bg=BG, font=('Helvetica', 9)
                ).pack(side='left')
        self.area_load_var = tk.DoubleVar(value=2.0)
        tk.Entry(row, textvariable=self.area_load_var, width=8).pack(side='left', padx=4)

        # How the pressure varies, which way it pushes, and where it lands.
        # Three separate questions, so three separate controls rather than
        # one list of every combination.
        self.area_law = tk.StringVar(value=AREA_UNIFORM)
        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=6, pady=(2, 0))
        tk.Label(row, text='Varies:', bg=BG, width=9, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        law_box = ttk.Combobox(row, textvariable=self.area_law, state='readonly',
                               width=8, values=list(AREA_LAWS))
        law_box.pack(side='left', fill='x', expand=True)
        law_box.bind('<<ComboboxSelected>>', lambda e: self._on_area_law_change())

        # gradient: q runs from one end of the chosen axis to the other
        self.area_axis = tk.StringVar(value='X')
        self.area_q_min = tk.DoubleVar(value=0.0)
        self.area_q_max = tk.DoubleVar(value=4.0)
        self.frame_area_gradient = tk.Frame(box, bg=BG)
        grow = tk.Frame(self.frame_area_gradient, bg=BG)
        grow.pack(fill='x', padx=6, pady=(2, 0))
        tk.Label(grow, text='along', bg=BG, font=('Helvetica', 8)).pack(side='left')
        ttk.Combobox(grow, textvariable=self.area_axis, state='readonly', width=2,
                     values=('X', 'Y', 'Z')).pack(side='left', padx=2)
        tk.Label(grow, text='from', bg=BG, font=('Helvetica', 8)).pack(side='left')
        tk.Entry(grow, textvariable=self.area_q_min, width=6).pack(side='left', padx=2)
        tk.Label(grow, text='to', bg=BG, font=('Helvetica', 8)).pack(side='left')
        tk.Entry(grow, textvariable=self.area_q_max, width=6).pack(side='left', padx=2)
        tk.Label(grow, text='kN/m²', bg=BG, font=('Helvetica', 8)).pack(side='left')

        # field: q as a typed expression, same parser as the wizard
        self.area_expr = tk.StringVar(value='2.0')
        self.frame_area_field = tk.Frame(box, bg=BG)
        frow = tk.Frame(self.frame_area_field, bg=BG)
        frow.pack(fill='x', padx=6, pady=(2, 0))
        tk.Label(frow, text='q(x,y,z) =', bg=BG, font=('Helvetica', 9)).pack(side='left')
        tk.Entry(frow, textvariable=self.area_expr).pack(side='left', fill='x',
                                                         expand=True, padx=2)

        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=6, pady=(2, 0))
        tk.Label(row, text='Pushes:', bg=BG, width=9, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        self.area_dir = tk.StringVar(value='Down (−Z)')
        dir_box = ttk.Combobox(row, textvariable=self.area_dir, state='readonly',
                               width=11, values=list(LOAD_DIRECTION_NAMES))
        dir_box.pack(side='left')
        dir_box.bind('<<ComboboxSelected>>', lambda e: self._on_area_law_change())
        self.area_dx = tk.DoubleVar(value=0.0)
        self.area_dy = tk.DoubleVar(value=0.0)
        self.area_dz = tk.DoubleVar(value=-1.0)
        self.frame_area_dir = tk.Frame(box, bg=BG)
        drow = tk.Frame(self.frame_area_dir, bg=BG)
        drow.pack(fill='x', padx=6, pady=(2, 0))
        for lbl, var in (('dx', self.area_dx), ('dy', self.area_dy), ('dz', self.area_dz)):
            tk.Label(drow, text=lbl, bg=BG, font=('Helvetica', 8)).pack(side='left')
            tk.Entry(drow, textvariable=var, width=5).pack(side='left', padx=(1, 5))

        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=6, pady=(2, 0))
        tk.Label(row, text='Over:', bg=BG, width=9, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        self.area_scope = tk.StringVar(value=AREA_SCOPE_ALL)
        ttk.Combobox(row, textvariable=self.area_scope, state='readonly',
                     width=8, values=list(AREA_SCOPES)).pack(side='left', fill='x',
                                                             expand=True)

        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=6, pady=(0, 4))
        self.area_load_on = tk.BooleanVar(value=True)
        tk.Checkbutton(row, text='Apply area load',
                       variable=self.area_load_on, bg=BG, font=('Helvetica', 8)
                      ).pack(anchor='w')
        self.area_status = tk.Label(box, text='', bg=BG, fg='#a3241a',
                                    font=('Helvetica', 8), wraplength=PANEL_W - 30,
                                    justify='left')
        self.area_status.pack(anchor='w', padx=6)
        # Off by default: the area load above already covers the roof/
        # shell surface (top layer only -- see stereo_geometry's load_nodes
        # docstring), so the DEFAULT view shows load only there, not also
        # spread across the bottom layer and every web by self-weight.
        # Self-weight stays one checkbox away for anyone who wants it.
        self.self_weight_on = tk.BooleanVar(value=False)
        self.unit_weight_var = tk.DoubleVar(value=sm.DEFAULT_STEEL_UNIT_WEIGHT)
        row2 = tk.Frame(box, bg=BG)
        row2.pack(fill='x', padx=6, pady=(0, 6))
        tk.Checkbutton(row2, text='Include self-weight, unit wt (kN/m³):',
                       variable=self.self_weight_on, bg=BG, font=('Helvetica', 8)
                      ).pack(side='left')
        tk.Entry(row2, textvariable=self.unit_weight_var, width=7).pack(side='left', padx=4)

        # ── distributed load ALONG the rods ─────────────────────────────
        # The area load above lands on NODES by tributary area, which is
        # the right idealisation for a space truss and has one consequence
        # worth stating: nothing then acts on a member between its ends, so
        # its shear is CONSTANT along it and there is no such thing as a
        # shear gradient to draw. This group is what puts a load ON the rod
        # itself -- cladding on a purlin, a service run hung off a chord --
        # and it is what makes the shear fall and the moment bow along the
        # member the way any loaded beam's does.
        rods = tk.LabelFrame(box, text='Distributed load on rods',
                             bg=BG, font=('Helvetica', 8, 'bold'))
        rods.pack(fill='x', padx=6, pady=(0, 6))
        row = tk.Frame(rods, bg=BG)
        row.pack(fill='x', padx=4, pady=(2, 0))
        tk.Label(row, text='w (kN/m):', bg=BG, width=9, anchor='w',
                 font=('Helvetica', 9)).pack(side='left')
        self.rod_w = tk.DoubleVar(value=1.5)
        tk.Entry(row, textvariable=self.rod_w, width=8).pack(side='left')

        row = tk.Frame(rods, bg=BG)
        row.pack(fill='x', padx=4, pady=(2, 0))
        tk.Label(row, text='On:', bg=BG, width=9, anchor='w',
                 font=('Helvetica', 9)).pack(side='left')
        self.rod_scope = tk.StringVar(value=ROD_SCOPE_TOP)
        ttk.Combobox(row, textvariable=self.rod_scope, state='readonly', width=13,
                     values=list(ROD_SCOPES)).pack(side='left', fill='x', expand=True)

        row = tk.Frame(rods, bg=BG)
        row.pack(fill='x', padx=4, pady=(2, 0))
        tk.Label(row, text='Pushes:', bg=BG, width=9, anchor='w',
                 font=('Helvetica', 9)).pack(side='left')
        self.rod_dir = tk.StringVar(value='Down (−Z)')
        rdir = ttk.Combobox(row, textvariable=self.rod_dir, state='readonly',
                            width=11, values=list(LOAD_DIRECTION_NAMES))
        rdir.pack(side='left')
        rdir.bind('<<ComboboxSelected>>', lambda e: self._on_rod_dir_change())
        self.rod_dx = tk.DoubleVar(value=0.0)
        self.rod_dy = tk.DoubleVar(value=0.0)
        self.rod_dz = tk.DoubleVar(value=-1.0)
        self.frame_rod_dir = tk.Frame(rods, bg=BG)
        drow = tk.Frame(self.frame_rod_dir, bg=BG)
        drow.pack(fill='x', padx=4, pady=(2, 0))
        for lbl, var in (('dx', self.rod_dx), ('dy', self.rod_dy), ('dz', self.rod_dz)):
            tk.Label(drow, text=lbl, bg=BG, font=('Helvetica', 8)).pack(side='left')
            tk.Entry(drow, textvariable=var, width=5).pack(side='left', padx=(1, 5))

        row = tk.Frame(rods, bg=BG)
        row.pack(fill='x', padx=4, pady=(2, 0))
        tk.Label(row, text='Quoted:', bg=BG, width=9, anchor='w',
                 font=('Helvetica', 9)).pack(side='left')
        self.rod_spread = tk.StringVar(value=mld.SPREAD_LABELS[0][1])
        ttk.Combobox(row, textvariable=self.rod_spread, state='readonly', width=13,
                     values=[lbl for _k, lbl in mld.SPREAD_LABELS]
                    ).pack(side='left', fill='x', expand=True)

        btn = tk.Frame(rods, bg=BG)
        btn.pack(fill='x', padx=4, pady=(3, 2))
        tk.Button(btn, text='Apply to rods', command=self._apply_rod_load
                 ).pack(side='left', padx=2)
        tk.Button(btn, text='Clear rod loads', command=self._clear_rod_loads
                 ).pack(side='left', padx=2)
        self.rod_load_status = tk.Label(rods, text='No rod loads.', bg=BG, fg=HINT_FG,
                                        font=('Helvetica', 8), justify='left',
                                        wraplength=PANEL_TEXT_W)
        self.rod_load_status.pack(anchor='w', padx=6, pady=(0, 4))
        tk.Label(rods,
                 text='"Per metre of rod" is the load the member carries '
                      'itself -- self weight, a hung service, an ice coating. '
                      '"Per metre projected" is how snow and most code roof '
                      'loads are quoted: a sloping rod picks up what falls on '
                      'its PLAN length, not on its true length, so a steeper '
                      'one carries no more of it and a vertical one carries '
                      'none at all.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W).pack(anchor='w', padx=6, pady=(0, 4))

        adv = tk.LabelFrame(box, text='Point loads', bg=BG,
                            font=('Helvetica', 8, 'bold'))
        adv.pack(fill='x', padx=6, pady=(0, 6))
        row = tk.Frame(adv, bg=BG)
        row.pack(fill='x', padx=4, pady=2)
        tk.Label(row, text='Node:', bg=BG, width=8, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        self.ld_node_var = tk.IntVar(value=0)
        tk.Entry(row, textvariable=self.ld_node_var, width=6).pack(side='left')

        self.ld_fx = tk.DoubleVar(value=0.0)
        self.ld_fy = tk.DoubleVar(value=0.0)
        self.ld_fz = tk.DoubleVar(value=-10.0)
        self.ld_mx = tk.DoubleVar(value=0.0)
        self.ld_my = tk.DoubleVar(value=0.0)
        self.ld_mz = tk.DoubleVar(value=0.0)
        for lbl, var in (('Fx (kN):', self.ld_fx), ('Fy (kN):', self.ld_fy),
                         ('Fz (kN):', self.ld_fz), ('Mx (kN·m):', self.ld_mx),
                         ('My (kN·m):', self.ld_my), ('Mz (kN·m):', self.ld_mz)):
            self._labeled_entry(adv, lbl, var)

        # Size and direction, the way a load is usually quoted -- "40 kN down
        # the slope" rather than three components someone has to resolve by
        # hand. It WRITES into Fx/Fy/Fz above rather than becoming a second
        # way to store a load, so the six boxes stay the single truth and
        # what it computed is visible and still editable afterwards.
        mag = tk.LabelFrame(adv, text='From a size and a direction',
                            bg=BG, font=('Helvetica', 8, 'bold'))
        mag.pack(fill='x', padx=4, pady=(2, 2))
        row = tk.Frame(mag, bg=BG)
        row.pack(fill='x', padx=4, pady=2)
        tk.Label(row, text='P (kN):', bg=BG, font=('Helvetica', 9)).pack(side='left')
        self.ld_mag = tk.DoubleVar(value=10.0)
        tk.Entry(row, textvariable=self.ld_mag, width=7).pack(side='left', padx=(2, 6))
        self.ld_dir = tk.StringVar(value=LOAD_DIRECTION_NAMES[0])
        dir_box = ttk.Combobox(row, textvariable=self.ld_dir, state='readonly',
                               width=10, values=list(LOAD_DIRECTION_NAMES))
        dir_box.pack(side='left')
        dir_box.bind('<<ComboboxSelected>>', lambda e: self._on_point_dir_change())
        self.frame_ld_dir = tk.Frame(mag, bg=BG)
        drow = tk.Frame(self.frame_ld_dir, bg=BG)
        drow.pack(fill='x', padx=4, pady=2)
        self.ld_dx = tk.DoubleVar(value=0.0)
        self.ld_dy = tk.DoubleVar(value=0.0)
        self.ld_dz = tk.DoubleVar(value=-1.0)
        for lbl, var in (('dx', self.ld_dx), ('dy', self.ld_dy), ('dz', self.ld_dz)):
            tk.Label(drow, text=lbl, bg=BG, font=('Helvetica', 8)).pack(side='left')
            tk.Entry(drow, textvariable=var, width=5).pack(side='left', padx=(1, 5))
        tk.Button(mag, text='Resolve into Fx, Fy, Fz',
                  command=self._resolve_point_load).pack(anchor='w', padx=4, pady=(0, 4))

        btn_row = tk.Frame(adv, bg=BG)
        btn_row.pack(fill='x', padx=4, pady=(2, 4))
        tk.Button(btn_row, text='Add/update', command=self._apply_load).pack(side='left', padx=2)
        tk.Button(btn_row, text='Remove', command=self._remove_load).pack(side='left', padx=2)

        self.load_list = tk.Listbox(adv, height=4, font=('Courier', 8))
        self.load_list.pack(fill='x', padx=4, pady=(0, 4))

    # ── Connectivity + sections ──────────────────────────────────────────────
    def _build_connectivity_panel(self, parent):
        box = tk.LabelFrame(parent, text='Connectivity', bg=BG, font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=4)
        self.sec_conn = tk.StringVar(value='pin')
        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=6, pady=4)
        tk.Radiobutton(row, text='Pin (space truss)', value='pin', variable=self.sec_conn,
                       bg=BG, font=('Helvetica', 9), command=self._on_connectivity_change
                      ).pack(side='left')
        tk.Radiobutton(row, text='Rigid (Vierendeel)', value='rigid', variable=self.sec_conn,
                       bg=BG, font=('Helvetica', 9), command=self._on_connectivity_change
                      ).pack(side='left')

    def _build_section_panel(self, parent, prefix, title):
        box = tk.LabelFrame(parent, text=title, bg=BG, font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=4)
        setattr(self, f'{prefix}_A', tk.DoubleVar(value=20.0))
        setattr(self, f'{prefix}_r', tk.DoubleVar(value=4.0))
        setattr(self, f'{prefix}_E', tk.DoubleVar(value=200.0))
        setattr(self, f'{prefix}_Fy', tk.DoubleVar(value=235.0))
        setattr(self, f'{prefix}_Fu', tk.DoubleVar(value=360.0))
        setattr(self, f'{prefix}_K', tk.DoubleVar(value=1.0))
        setattr(self, f'{prefix}_I', tk.DoubleVar(value=400.0))
        setattr(self, f'{prefix}_J', tk.DoubleVar(value=400.0))
        self._labeled_entry(box, 'A (cm²):', getattr(self, f'{prefix}_A'))
        self._labeled_entry(box, 'r (cm):', getattr(self, f'{prefix}_r'))
        self._labeled_entry(box, 'E (GPa):', getattr(self, f'{prefix}_E'))
        self._labeled_entry(box, 'Fy (MPa):', getattr(self, f'{prefix}_Fy'))
        self._labeled_entry(box, 'Fu (MPa):', getattr(self, f'{prefix}_Fu'))
        self._labeled_entry(box, 'K:', getattr(self, f'{prefix}_K'))
        ij_frame = tk.Frame(box, bg=BG)
        self._labeled_entry(ij_frame, 'I (cm⁴):', getattr(self, f'{prefix}_I'))
        self._labeled_entry(ij_frame, 'J (cm⁴):', getattr(self, f'{prefix}_J'))
        setattr(self, f'_{prefix}_ij_frame', ij_frame)
        if prefix == 'web':
            # only need to trigger _apply_sections once for the pair; the
            # chord panel's own button would just redo the same work.
            tk.Button(box, text='Apply sections to all members',
                     command=self._apply_sections).pack(padx=6, pady=(4, 6), anchor='w')

    def _on_connectivity_change(self):
        show = self.sec_conn.get() == 'rigid'
        for prefix in ('chord', 'web'):
            frame = getattr(self, f'_{prefix}_ij_frame')
            if show:
                frame.pack(fill='x')
            else:
                frame.pack_forget()

    def _build_selection_panel(self, parent):
        box = tk.LabelFrame(parent, text='Selected node', bg=BG, font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=4)
        self.sel_label = tk.Label(box, textvariable=self.sel_var,
                                  bg=BG, fg='#666', font=('Helvetica', 9),
                                  wraplength=PANEL_W - 24, justify='left')
        self.sel_label.pack(anchor='w', padx=6, pady=4)
        tk.Button(box, text='Delete selected node(s)', command=self._on_delete_nodes
                 ).pack(anchor='w', padx=6, pady=(0, 4))

    # ── add-on features: column (capital + shaft) and reinforcement beam ────
    def _build_addons_panel(self, parent):
        box = tk.LabelFrame(parent, text='Add-ons', bg=BG, font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=4)

        col = tk.LabelFrame(box, text='Column', bg=BG,
                            font=('Helvetica', 8, 'bold'))
        col.pack(fill='x', padx=6, pady=(4, 4))
        tk.Label(col, text='Lasso the nodes the column stands under, then:',
                bg=BG, font=('Helvetica', 8), fg='#666',
                wraplength=PANEL_TEXT_W, justify='left').pack(anchor='w', padx=4, pady=(2, 0))
        self.col_style = tk.StringVar(value=sg.COLUMN_SHAFT)
        style_row = tk.Frame(col, bg=BG)
        style_row.pack(fill='x', padx=6, pady=(3, 0))
        tk.Label(style_row, text='Type:', bg=BG, width=12, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        style_box = ttk.Combobox(style_row, textvariable=self.col_style,
                                 state='readonly', width=8,
                                 values=list(sg.COLUMN_STYLES))
        style_box.pack(side='left', fill='x', expand=True)
        # A trace on the VARIABLE, not a <<ComboboxSelected>> binding: the
        # binding only fires for a real click, so anything that sets the
        # style in code -- an example, a restored model, a test -- would
        # leave the panel showing the previous style's fields.
        self.col_style.trace_add('write', lambda *_a: self._on_col_style_change())
        self.col_height = tk.DoubleVar(value=3.0)
        self._labeled_entry(col, 'Shaft height (m):', self.col_height)
        # The capital's own depth, adjustable rather than derived: it is the
        # difference between a shallow wide-spreading capital and a deep
        # steep one, and it moves load between the capital legs and the
        # grid's own chords.
        # Every field that only SOME styles read lives in this one container,
        # so hiding and showing them cannot reorder them: pack_forget then
        # pack appends to the end of the parent, which is how "Lattice
        # panels" ended up below the status note.
        opt = tk.Frame(col, bg=BG)
        opt.pack(fill='x')
        self._col_optional = opt
        self.col_capital = tk.DoubleVar(value=0.9)
        self.frame_col_capital = tk.Frame(opt, bg=BG)
        self._labeled_entry(self.frame_col_capital, 'Capital height (m):',
                            self.col_capital)
        self.col_width = tk.DoubleVar(value=0.6)
        self.frame_col_width = tk.Frame(opt, bg=BG)
        self._labeled_entry(self.frame_col_width, 'Column width (m):', self.col_width)
        self.col_panels = tk.IntVar(value=4)
        self.frame_col_panels = tk.Frame(opt, bg=BG)
        self._labeled_entry(self.frame_col_panels, 'Lattice panels:', self.col_panels)
        self.col_tiers = tk.IntVar(value=1)
        tier_row = tk.Frame(opt, bg=BG)
        self.frame_col_tiers = tier_row
        tk.Label(tier_row, text='Capital:', bg=BG, width=12, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        tk.Radiobutton(tier_row, text='1 module', value=1, variable=self.col_tiers,
                      bg=BG, font=('Helvetica', 8)).pack(side='left')
        tk.Radiobutton(tier_row, text='2 thick', value=2, variable=self.col_tiers,
                      bg=BG, font=('Helvetica', 8)).pack(side='left')
        # Off by default, unlike the original, which had it on. Turning it
        # on adds restraints, which changes the answer for every column
        # model ever built in this version -- that is the user's call to
        # make deliberately, not a default that quietly moves their numbers.
        self.col_braced = tk.BooleanVar(value=False)
        tk.Checkbutton(col, text='Laterally braced at the capital',
                       variable=self.col_braced, bg=BG, font=('Helvetica', 9),
                       anchor='w', justify='left', wraplength=PANEL_TEXT_W
                       ).pack(fill='x', padx=6)
        tk.Label(col, text='Holds the head against sway (ux, uy) but leaves uz '
                           'free, so the column still shortens and still has to '
                           'pass its buckling check.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W).pack(anchor='w', padx=6, pady=(0, 2))
        tk.Checkbutton(col, text='Pick a footprint with the disc',
                       variable=self.disc_pick_mode, bg=BG, font=('Helvetica', 9),
                       anchor='w',
                       command=lambda: self._on_pick_mode_toggle('disc')
                      ).pack(fill='x', padx=6, pady=(2, 0))
        tk.Label(col, text='A disc follows the cursor on the chosen layer and '
                           'lights the joints under it. Click to take them.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W).pack(anchor='w', padx=6)
        drow = tk.Frame(col, bg=BG)
        drow.pack(fill='x', padx=6, pady=(1, 0))
        tk.Label(drow, text='on:', bg=BG, width=4, anchor='w',
                 font=('Helvetica', 8)).pack(side='left')
        for label, val in (('top', 'top'), ('bottom', 'bottom')):
            tk.Radiobutton(drow, text=label, value=val, variable=self.disc_layer,
                           bg=BG, font=('Helvetica', 8),
                           command=self._draw).pack(side='left')
        tk.Label(drow, text='r\u00d7', bg=BG, font=('Helvetica', 8)
                ).pack(side='left', padx=(5, 1))
        tk.Entry(drow, textvariable=self.disc_radius, width=4,
                 font=('Helvetica', 8)).pack(side='left')
        tk.Label(drow, text='\u2264', bg=BG, font=('Helvetica', 8)).pack(side='left', padx=(4, 1))
        tk.Entry(drow, textvariable=self.disc_limit, width=3,
                 font=('Helvetica', 8)).pack(side='left')
        tk.Button(col, text='Add column at selected nodes', command=self._add_column
                 ).pack(fill='x', padx=6, pady=(3, 2))

        self.col_array_x = tk.IntVar(value=2)
        self.col_array_y = tk.IntVar(value=2)
        arow = tk.Frame(col, bg=BG)
        arow.pack(fill='x', padx=6, pady=(2, 0))
        tk.Label(arow, text='Array:', bg=BG, width=7, anchor='w',
                 font=('Helvetica', 9)).pack(side='left')
        tk.Entry(arow, textvariable=self.col_array_x, width=4,
                 font=('Helvetica', 9)).pack(side='left')
        tk.Label(arow, text='\u00d7', bg=BG, font=('Helvetica', 9)).pack(side='left', padx=2)
        tk.Entry(arow, textvariable=self.col_array_y, width=4,
                 font=('Helvetica', 9)).pack(side='left')
        tk.Button(col, text='Build the array',
                  command=self._build_column_array
                 ).pack(fill='x', padx=6, pady=(2, 2))
        tk.Label(col, text='The array places its own columns -- no selection needed.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W).pack(anchor='w', padx=6, pady=(0, 2))
        tk.Button(col, text='Clear every column', fg='#a3241a',
                  command=self._clear_columns).pack(fill='x', padx=6, pady=(0, 4))
        self._col_hint = tk.Label(col, text='', bg=BG, fg=HINT_FG,
                                  font=('Helvetica', 8), justify='left',
                                  wraplength=PANEL_TEXT_W, anchor='w')
        self._col_hint.pack(anchor='w', padx=6, pady=(0, 2))
        self.col_note = tk.Label(col, text='', bg=BG, fg='#2f6f4f',
                                 font=('Helvetica', 8), justify='left',
                                 wraplength=250, anchor='w')
        self.col_note.pack(anchor='w', padx=6, pady=(0, 4))

        pan = tk.LabelFrame(box, text='Welded shear panel', bg=BG,
                            font=('Helvetica', 8, 'bold'))
        pan.pack(fill='x', padx=6, pady=(0, 4))
        tk.Label(pan, text='Lasso 3 or 4 nodes that a closed ring of rods '
                           'already joins, then weld a plate into it. Its '
                           'in-plane shear stiffness goes into the solve, so '
                           'the bay really does get stiffer, and it is checked '
                           'for yield, weld and shear buckling.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W).pack(anchor='w', padx=4, pady=(2, 0))
        self.panel_t = tk.DoubleVar(value=6.0)
        self.panel_fy = tk.DoubleVar(value=235.0)
        self.panel_weld_lines = tk.IntVar(value=2)
        self._labeled_entry(pan, 'Thickness (mm):', self.panel_t)
        self._labeled_entry(pan, 'Fy (MPa):', self.panel_fy)
        self._labeled_entry(pan, 'Weld lines:', self.panel_weld_lines)
        tk.Button(pan, text='Weld a panel here',
                  command=self._add_shear_panel).pack(fill='x', padx=6, pady=(2, 2))
        tk.Button(pan, text='Clear every panel', fg='#a3241a',
                  command=self._clear_shear_panels).pack(fill='x', padx=6, pady=(0, 4))

        beam = tk.LabelFrame(box, text='Reinforcement beam', bg=BG,
                             font=('Helvetica', 8, 'bold'))
        beam.pack(fill='x', padx=6, pady=(0, 6))
        tk.Label(beam, text='Select TWO adjacent rows of nodes (lasso a box '
                          'spanning both rows), then:', bg=BG, font=('Helvetica', 8),
                fg='#666', wraplength=PANEL_W - 40, justify='left'
               ).pack(anchor='w', padx=4, pady=(2, 0))
        self.beam_profile = tk.StringVar(value=sg.BEAM_TRIANGLE)
        prof_row = tk.Frame(beam, bg=BG)
        prof_row.pack(fill='x', padx=6, pady=(3, 0))
        tk.Label(prof_row, text='Profile:', bg=BG, width=12, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        ttk.Combobox(prof_row, textvariable=self.beam_profile, state='readonly',
                     width=8, values=list(sg.BEAM_PROFILES)).pack(side='left', fill='x',
                                                                  expand=True)
        # The depth law is a separate question from the cross-section, and
        # combinable with any of them, so it gets its own control rather than
        # doubling the profile list.
        self.beam_depth_law = tk.StringVar(value=sg.BEAM_DEPTH_CONSTANT)
        law_row = tk.Frame(beam, bg=BG)
        law_row.pack(fill='x', padx=6, pady=(3, 0))
        tk.Label(law_row, text='Depth law:', bg=BG, width=12, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        ttk.Combobox(law_row, textvariable=self.beam_depth_law, state='readonly',
                     width=8, values=list(sg.BEAM_DEPTH_LAWS)).pack(side='left', fill='x',
                                                                    expand=True)
        tk.Label(beam, text='Grid strip puts the offset chord under each '
                           'MODULE centre, so every bay is the same half-'
                           'octahedron the flat grid is built from. '
                           'Vierendeel forces its own joints rigid -- pinned '
                           'it is a mechanism, not a frame.',
                bg=BG, font=('Helvetica', 8), fg='#666',
                wraplength=PANEL_W - 40, justify='left'
                ).pack(anchor='w', padx=4, pady=(2, 0))
        self.beam_depth = tk.DoubleVar(value=1.0)
        self.beam_dir = tk.StringVar(value='Down (-Z)')
        self.beam_tiers = tk.IntVar(value=1)
        self._labeled_entry(beam, 'Offset depth (m):', self.beam_depth)
        row = tk.Frame(beam, bg=BG)
        row.pack(fill='x', padx=6, pady=1)
        tk.Label(row, text='Direction:', bg=BG, width=16, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        ttk.Combobox(row, textvariable=self.beam_dir, state='readonly', width=14,
                    values=list(self.BEAM_DIRECTIONS)).pack(side='left')
        self._labeled_entry(beam, 'Layers (tiers):', self.beam_tiers)
        tk.Button(beam, text='Add beam over selected rows',
                 command=self._add_reinforcement_beam).pack(fill='x', padx=6, pady=(2, 2))
        tk.Button(beam, text='Clear every beam', fg='#a3241a',
                  command=self._clear_beams).pack(fill='x', padx=6, pady=(0, 4))

    def _build_results_panel(self, parent):
        box = tk.LabelFrame(parent, text='Results', bg=BG, font=('Helvetica', 10, 'bold'))
        box.pack(fill='both', padx=6, pady=(4, 8))
        # A property of the STRUCTURE (geometry/connectivity/supports)
        # alone, not of any solved load case -- shown even before Analyze
        # has ever run, and kept live as supports/members change.
        self.indeterminacy_label = tk.Label(box, text='', bg=BG, font=('Helvetica', 9, 'bold'),
                                            wraplength=PANEL_W - 20, justify='left')
        self.indeterminacy_label.pack(fill='x', padx=6, pady=(6, 0), anchor='w')
        self.results_text = tk.Text(box, height=8, width=32, wrap='word',
                                    font=('Helvetica', 9), relief='flat', bg=BG)
        self.results_text.pack(fill='both', padx=6, pady=6)
