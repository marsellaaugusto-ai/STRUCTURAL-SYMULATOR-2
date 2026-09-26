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

from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_math as sm
from apps.stereo import stereo_examples as sx
from apps.stereo import stereo_voronoi_surface as svs
from apps.stereo.stereo_app_constants import (
    BG, CANVAS_BG, PANEL_W, MODULE_PANEL_W,
    DOF_LABELS, PRESET_NAMES, GRID_PATTERNS, PATTERN_LABEL, GRID_FAMILIES,
    QUICK_SUPPORT_PIN, QUICK_SUPPORT_CHOICES,
    DEFORM_MODES, DEFORM_MODE_DISPLACEMENT,
    MOMENT_AXES, MOMENT_AXIS_RESULTANT,
    COLOUR_NONE, COLOUR_FORCE, COLOUR_UTIL, COLOUR_MOMENT, COLOUR_MODES,
    FILL_NONE, FILL_SHADED, FILL_VORONOI, FILL_MODES,
    SCALE_P95, SCALE_MODES,
    FILL_DENSITIES, FILL_DENSITY_DEFAULT,
    AREA_UNIFORM, AREA_GRADIENT, AREA_FIELD, AREA_LAWS,
    LOAD_DIRECTION_NAMES, AREA_SCOPE_ALL, AREA_SCOPES,
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
        self._draw()

    def _on_faces_mode_change(self):
        mode = self.faces_mode.get()
        self.shaded_faces.set(mode == FILL_SHADED)
        self.voronoi_faces.set(mode == FILL_VORONOI)
        self._draw()


class StereoPanelsMixin(_ToolbarModes):
    """Builds the toolbar, the 3D canvas and every sidebar panel."""

    def _tb_group(self, caption):
        """One captioned toolbar group.

        Every group says what it is FOR, because a row of bare checkboxes
        cannot: the caption is what tells you that 'Skin' belongs to the
        Voronoi fill and not to the rods, or that 'Only' means only the
        deformed shape. Two widget types, used consistently, carry the rest
        of the meaning -- a RADIO where exactly one choice applies, a
        CHECKBOX where something is independently on or off.
        """
        g = self.toolbar_flow.group()
        tk.Label(g, text=caption, bg=BG, font=('Helvetica', 7, 'bold'),
                 fg='#7a869a').pack(side='left', padx=(4, 5))
        return g

    def _build_ui(self):
        tb = tk.Frame(self.root, bg=BG)
        tb.pack(side='top', fill='x')
        self.toolbar_flow = FlowBar(tb)

        # ── 1 · BUILD ────────────────────────────────────────────────────────
        g = self._tb_group('BUILD')
        tk.Label(g, text='Grid family:', bg=BG).pack(side='left', padx=(0, 2))
        fam_box = ttk.Combobox(g, textvariable=self.grid_family, state='readonly', width=34,
                               values=[label for _key, label in GRID_FAMILIES])
        fam_box.pack(side='left')
        fam_box.bind('<<ComboboxSelected>>', lambda e: self._on_generator_change())
        tk.Button(g, text='Generate', font=('Helvetica', 9, 'bold'),
                  command=self._generate).pack(side='left', padx=4)
        tk.Button(g, text='Custom Surface Wizard…', command=self._open_custom_surface_wizard
                 ).pack(side='left', padx=(2, 4))
        examples_btn = tk.Menubutton(g, text='Load Example ▾', relief='raised',
                                     font=('Helvetica', 9))
        examples_menu = tk.Menu(examples_btn, tearoff=False)
        for label, builder in sx.EXAMPLES:
            examples_menu.add_command(label=label,
                                      command=lambda b=builder, lbl=label: self._load_example(b, lbl))
        examples_btn['menu'] = examples_menu
        examples_btn.pack(side='left', padx=(2, 4))
        tk.Button(g, text='Import SketchUp…', command=self._import_sketchup
                 ).pack(side='left', padx=(2, 4))
        tk.Button(g, text='Undo', command=self._undo).pack(side='left', padx=(6, 1))
        tk.Button(g, text='Redo', command=self._redo).pack(side='left', padx=1)
        self.add_rod_mode = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Add rod (click 2 nodes)', variable=self.add_rod_mode,
                       bg=BG, command=self._on_add_rod_mode_toggle).pack(side='left', padx=(6, 0))

        # ── 2 · SOLVE ────────────────────────────────────────────────────────
        self.toolbar_flow.separator()
        g = self._tb_group('SOLVE')
        tk.Button(g, text='▶ Analyze', font=('Helvetica', 9, 'bold'), bg='#dff0d8',
                  command=self._analyze).pack(side='left', padx=2)
        tk.Label(g, text='Load %:', bg=BG, font=('Helvetica', 9)).pack(side='left', padx=(8, 2))
        self.load_fraction = tk.IntVar(value=100)
        tk.Scale(g, from_=0, to=100, orient='horizontal', variable=self.load_fraction,
                length=100, showvalue=True, command=lambda _v: self._draw()
                ).pack(side='left')

        # ── 3 · COLOUR BY ────────────────────────────────────────────────────
        # One quantity at a time, so this is a radio. It replaces three
        # independent checkboxes whose mutual exclusivity was real but
        # invisible -- utilization silently won over force, which won over
        # moment, and nothing on screen said so.
        self.toolbar_flow.separator()
        g = self._tb_group('COLOUR BY')
        self.colour_by_force = tk.BooleanVar(value=True)
        self.colour_by_util = tk.BooleanVar(value=False)
        self.colour_by_moment = tk.BooleanVar(value=False)
        self.colour_mode = tk.StringVar(value=COLOUR_FORCE)
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
        self.force_scale = tk.StringVar(value=SCALE_P95)
        for label in SCALE_MODES:
            tk.Radiobutton(g, text=label, value=label, variable=self.force_scale,
                           bg=BG, command=self._draw).pack(side='left', padx=(0, 3))
        self.moment_axis = tk.StringVar(value=MOMENT_AXIS_RESULTANT)
        moment_axis_box = ttk.Combobox(g, textvariable=self.moment_axis, state='readonly',
                                       width=15, values=MOMENT_AXES)
        moment_axis_box.pack(side='left', padx=(2, 0))
        moment_axis_box.bind('<<ComboboxSelected>>', lambda e: self._draw())

        # ── 4 · DRAW RODS AS ─────────────────────────────────────────────────
        self.toolbar_flow.separator()
        g = self._tb_group('DRAW RODS AS')
        self.smooth_gradient = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Smooth gradient', variable=self.smooth_gradient,
                       bg=BG, command=self._draw).pack(side='left')
        self.thickness_by_stress = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Thickness = stress', variable=self.thickness_by_stress,
                       bg=BG, command=self._draw).pack(side='left', padx=(6, 0))
        self.hide_zero_force = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Hide ~0-force rods', variable=self.hide_zero_force, bg=BG,
                       command=self._draw).pack(side='left', padx=(6, 0))
        self.flag_slender = tk.BooleanVar(value=False)
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
        self.toolbar_flow.separator()
        g = self._tb_group('FILL')
        self.shaded_faces = tk.BooleanVar(value=False)
        self.voronoi_faces = tk.BooleanVar(value=False)
        self.faces_mode = tk.StringVar(value=FILL_NONE)
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
        self.fill_density = tk.StringVar(value=FILL_DENSITY_DEFAULT)
        dens = ttk.Combobox(g, textvariable=self.fill_density, state='readonly',
                            width=7, values=list(FILL_DENSITIES))
        dens.pack(side='left')
        dens.bind('<<ComboboxSelected>>', lambda e: self._draw())

        # ── 6 · VORONOI ──────────────────────────────────────────────────────
        # Its own group because these only mean anything once FILL is set to
        # Voronoi. There is no DOMAIN control any more: the domain is the
        # structure's own surface, which needs no choosing and no parameter
        # (see stereo_voronoi_surface). Only Section is volumetric, so the
        # cut controls belong to it alone.
        self.toolbar_flow.separator()
        g = self._tb_group('VORONOI')
        tk.Label(g, text='view', bg=BG, font=('Helvetica', 8), fg='#556')\
            .pack(side='left', padx=(0, 2))
        self.voronoi_view = tk.StringVar(value=svs.VIEW_SURFACE)
        for label in svs.VIEWS:
            tk.Radiobutton(g, text=label, value=label, variable=self.voronoi_view,
                           bg=BG, command=self._draw).pack(side='left', padx=(0, 3))
        tk.Label(g, text='section at', bg=BG, font=('Helvetica', 8), fg='#556')\
            .pack(side='left', padx=(8, 2))
        self.voronoi_axis = tk.StringVar(value='Z')
        axis_box = ttk.Combobox(g, textvariable=self.voronoi_axis, state='readonly',
                                width=2, values=('X', 'Y', 'Z'))
        axis_box.pack(side='left')
        axis_box.bind('<<ComboboxSelected>>', lambda e: self._draw())
        self.voronoi_slice = tk.IntVar(value=50)
        tk.Scale(g, from_=0, to=100, orient='horizontal', variable=self.voronoi_slice,
                length=80, showvalue=False, command=lambda _v: self._draw()
                ).pack(side='left')
        tk.Label(g, text='cut(m)', bg=BG, font=('Helvetica', 8), fg='#556')\
            .pack(side='left', padx=(4, 1))
        self.voronoi_cut = tk.DoubleVar(value=1.0)
        cut_entry = tk.Entry(g, textvariable=self.voronoi_cut, width=5)
        cut_entry.pack(side='left')
        cut_entry.bind('<Return>', lambda e: self._draw())
        cut_entry.bind('<FocusOut>', lambda e: self._draw())

        # ── 7 · DEFORMED SHAPE ───────────────────────────────────────────────
        # Kept apart from COLOUR BY on purpose: this colours a DIFFERENT
        # object -- the displaced copy drawn over the structure -- so it
        # carries its own quantity choice rather than competing for the one
        # above.
        self.toolbar_flow.separator()
        g = self._tb_group('DEFORMED SHAPE')
        self.show_deformed = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Show', variable=self.show_deformed, bg=BG,
                       command=self._draw).pack(side='left')
        tk.Label(g, text='×', bg=BG, font=('Helvetica', 9)).pack(side='left', padx=(4, 0))
        self.deform_scale = tk.IntVar(value=50)
        tk.Scale(g, from_=1, to=500, orient='horizontal', variable=self.deform_scale,
                length=80, showvalue=True, command=lambda _v: self._draw()
                ).pack(side='left')
        self.deformed_only = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Only', variable=self.deformed_only, bg=BG,
                       command=self._draw).pack(side='left', padx=(4, 0))
        tk.Label(g, text='colour', bg=BG, font=('Helvetica', 8), fg='#556'
                ).pack(side='left', padx=(6, 2))
        self.deform_color_mode = tk.StringVar(value=DEFORM_MODE_DISPLACEMENT)
        deform_mode_box = ttk.Combobox(g, textvariable=self.deform_color_mode, state='readonly',
                                       width=14, values=DEFORM_MODES)
        deform_mode_box.pack(side='left')
        deform_mode_box.bind('<<ComboboxSelected>>', lambda e: self._draw())
        tk.Label(g, text='ref. shade', bg=BG, font=('Helvetica', 8), fg='#556'
                ).pack(side='left', padx=(6, 2))
        self.reference_shade = tk.IntVar(value=78)
        tk.Scale(g, from_=0, to=100, orient='horizontal', variable=self.reference_shade,
                length=70, showvalue=False, command=lambda _v: self._draw()
                ).pack(side='left')

        # ── 8 · SHOW ─────────────────────────────────────────────────────────
        # Independent annotations drawn over whatever the groups above
        # produced -- every one of these is on or off by itself, which is why
        # they are all checkboxes and all live together.
        self.toolbar_flow.separator()
        g = self._tb_group('SHOW')
        self.show_members = tk.BooleanVar(value=True)
        tk.Checkbutton(g, text='Rods', variable=self.show_members, bg=BG,
                       command=self._draw).pack(side='left')
        self.show_nodes = tk.BooleanVar(value=True)
        tk.Checkbutton(g, text='Nodes', variable=self.show_nodes, bg=BG,
                       command=self._draw).pack(side='left', padx=(4, 0))
        self.show_node_labels = tk.BooleanVar(value=True)
        tk.Checkbutton(g, text='Node #', variable=self.show_node_labels, bg=BG,
                       command=self._draw).pack(side='left', padx=(4, 0))
        self.show_member_labels = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Rod #', variable=self.show_member_labels, bg=BG,
                       command=self._draw).pack(side='left', padx=(4, 0))
        self.show_loads = tk.BooleanVar(value=True)
        tk.Checkbutton(g, text='Loads', variable=self.show_loads, bg=BG,
                       command=self._draw).pack(side='left', padx=(4, 0))
        self.show_reactions = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Reactions', variable=self.show_reactions, bg=BG,
                       command=self._draw).pack(side='left', padx=(4, 0))
        self.show_axes = tk.BooleanVar(value=True)
        tk.Checkbutton(g, text='Axes + ground', variable=self.show_axes, bg=BG,
                       command=self._draw).pack(side='left', padx=(4, 0))
        self.load_path_anim = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Load-path arrows', variable=self.load_path_anim, bg=BG,
                      command=self._on_load_path_anim_toggle).pack(side='left', padx=(4, 0))

        # ── 9 · OUTPUT ───────────────────────────────────────────────────────
        self.toolbar_flow.separator()
        g = self._tb_group('OUTPUT')
        tk.Button(g, text='Reset view', command=self._reset_view).pack(side='left', padx=2)
        tk.Button(g, text='Member Report', command=self._show_member_report
                 ).pack(side='left', padx=2)
        tk.Button(g, text='Export Excel…', command=self._export_excel).pack(side='left', padx=2)
        tk.Button(g, text='Export 3D…', command=self._export_3d_model).pack(side='left', padx=2)
        tk.Button(g, text='Import Excel…', command=self._import_excel).pack(side='left', padx=2)
        tk.Button(g, text='Open Example', command=self._open_example).pack(side='left', padx=2)

        self.toolbar_flow.start()

        main = tk.Frame(self.root, bg=BG)
        main.pack(fill='both', expand=True, padx=6, pady=(6, 0))

        # Panel FIRST, expanding canvas SECOND: packing the canvas (or
        # anything expand=True) before a fixed-width sidebar starves the
        # sidebar of space as the window narrows -- the exact bug the rest
        # of this app's tabs standardized ScrollPanel to avoid (see its
        # docstring in common.py). It also scrolls both axes, so a row
        # wider than the panel (the deform-scale slider, a two-button row)
        # stays reachable instead of clipped.
        self.panel_outer = ScrollPanel(main, width=PANEL_W, bg=BG, bd=1, relief='solid')
        self.panel_outer.pack(side='left', fill='y', padx=(0, 6))

        # The Module Editor panel is ALSO packed before the expanding
        # canvas, same reasoning as the left sidebar above (see
        # ScrollPanel's own docstring): pack(side='right') alone is not
        # enough -- pack allocates space in PACKING ORDER regardless of
        # side, so packing it AFTER an expand=True canvas would find
        # nothing left to claim.
        self.module_panel_outer = ScrollPanel(main, width=MODULE_PANEL_W, bg=BG, bd=1,
                                              relief='solid')
        self.module_panel_outer.pack(side='right', fill='y', padx=(6, 0))

        canvas_frame = tk.Frame(main, bg=BG)
        canvas_frame.pack(side='left', fill='both', expand=True)
        self.zc = ZoomCanvas(canvas_frame, bg=CANVAS_BG, bd=1, relief='solid')
        self.zc.pack(fill='both', expand=True)
        self.zc._on_zoom_changed = self._draw_throttled
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

        self._build_panel(self.panel_outer.interior)
        self.panel_outer.fit_to_content()

        self._build_module_editor_panel(self.module_panel_outer.interior)
        self.module_panel_outer.fit_to_content()

        self._on_generator_change()

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

    def _build_panel(self, parent):
        self._build_geometry_panel(parent)
        self._build_supports_panel(parent)
        self._build_loads_panel(parent)
        self._build_connectivity_panel(parent)
        self._build_section_panel(parent, 'chord', 'Chord section (top/bottom)')
        self._build_section_panel(parent, 'web', 'Web section (diagonals)')
        self._build_selection_panel(parent)
        self._build_addons_panel(parent)
        self._build_results_panel(parent)
        self._on_connectivity_change()   # hide I/J unless Rigid is selected

    # ── Geometry (per grid family) ───────────────────────────────────────────
    def _build_geometry_panel(self, parent):
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
                               width=26, values=[label for _key, label in GRID_PATTERNS])
        pat_box.pack(side='left', padx=(4, 0))

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

        self._param_frames = {'flat_grid': self.frame_flat_grid,
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
                              'truss_bridge': self.frame_truss_bridge}

    def _pattern_row(self, parent, var):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill='x', padx=6, pady=(0, 4))
        tk.Label(row, text='Chord pattern:', bg=BG, font=('Helvetica', 9)).pack(side='left')
        box = ttk.Combobox(row, textvariable=var, state='readonly', width=26,
                           values=[label for _key, label in GRID_PATTERNS])
        box.pack(side='left', padx=(4, 0))

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

        adv = tk.LabelFrame(box, text='Per-node boundary condition -- any combination of '
                                     'the six DOFs', bg=BG, font=('Helvetica', 8, 'bold'))
        adv.pack(fill='x', padx=6, pady=(0, 6))

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
                       wraplength=PANEL_W - 30, justify='left', command=self._draw
                      ).pack(anchor='w', padx=4, pady=(4, 0))
        tk.Label(sandbox, text='Disabled supports are excluded from the next Analyze -- '
                              'build intuition for redundancy without editing the model.',
                bg=BG, fg='#666', font=('Helvetica', 8), wraplength=PANEL_W - 30,
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
                               width=20, values=list(AREA_LAWS))
        law_box.pack(side='left')
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
                     width=20, values=list(AREA_SCOPES)).pack(side='left')

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

        adv = tk.LabelFrame(box, text='Point loads (any node, any direction)', bg=BG,
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
        mag = tk.LabelFrame(adv, text='Set Fx, Fy, Fz from a size and a direction',
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
        self.sel_label = tk.Label(box, text='(click, or drag a box, to select node(s))',
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
        tk.Label(col, text='Select >=3 nodes (lasso box) for the capital to '
                          'attach to, then:', bg=BG, font=('Helvetica', 8), fg='#666',
                wraplength=PANEL_W - 40, justify='left').pack(anchor='w', padx=4, pady=(2, 0))
        self.col_style = tk.StringVar(value=sg.COLUMN_SHAFT)
        style_row = tk.Frame(col, bg=BG)
        style_row.pack(fill='x', padx=6, pady=(3, 0))
        tk.Label(style_row, text='Type:', bg=BG, width=16, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        ttk.Combobox(style_row, textvariable=self.col_style, state='readonly',
                     width=20, values=list(sg.COLUMN_STYLES)).pack(side='left')
        self.col_height = tk.DoubleVar(value=3.0)
        self._labeled_entry(col, 'Shaft height (m):', self.col_height)
        # The capital's own depth, adjustable rather than derived: it is the
        # difference between a shallow wide-spreading capital and a deep
        # steep one, and it moves load between the capital legs and the
        # grid's own chords.
        self.col_capital = tk.DoubleVar(value=0.9)
        self._labeled_entry(col, 'Capital height (m):', self.col_capital)
        self.col_width = tk.DoubleVar(value=0.6)
        self._labeled_entry(col, 'Column width (m):', self.col_width)
        self.col_panels = tk.IntVar(value=4)
        self._labeled_entry(col, 'Lattice panels:', self.col_panels)
        tk.Label(col, text='Width and panels apply to the latticed and '
                          'inclined-leg types; those stand on FOUR pinned '
                          'feet, not one.', bg=BG, font=('Helvetica', 8),
                fg='#666', wraplength=PANEL_W - 40, justify='left'
                ).pack(anchor='w', padx=4, pady=(2, 0))
        self.col_tiers = tk.IntVar(value=1)
        tier_row = tk.Frame(col, bg=BG)
        tier_row.pack(fill='x', padx=6, pady=(2, 0))
        tk.Label(tier_row, text='Capital:', bg=BG, width=16, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        tk.Radiobutton(tier_row, text='1 module', value=1, variable=self.col_tiers,
                      bg=BG, font=('Helvetica', 8)).pack(side='left')
        tk.Radiobutton(tier_row, text='2 modules thick', value=2, variable=self.col_tiers,
                      bg=BG, font=('Helvetica', 8)).pack(side='left')
        tk.Button(col, text='Add column at selected nodes', command=self._add_column
                 ).pack(padx=4, pady=(2, 4), anchor='w')

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
        tk.Label(prof_row, text='Profile:', bg=BG, width=16, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        ttk.Combobox(prof_row, textvariable=self.beam_profile, state='readonly',
                     width=22, values=list(sg.BEAM_PROFILES)).pack(side='left')
        # The depth law is a separate question from the cross-section, and
        # combinable with any of them, so it gets its own control rather than
        # doubling the profile list.
        self.beam_depth_law = tk.StringVar(value=sg.BEAM_DEPTH_CONSTANT)
        law_row = tk.Frame(beam, bg=BG)
        law_row.pack(fill='x', padx=6, pady=(3, 0))
        tk.Label(law_row, text='Depth along span:', bg=BG, width=16, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        ttk.Combobox(law_row, textvariable=self.beam_depth_law, state='readonly',
                     width=22, values=list(sg.BEAM_DEPTH_LAWS)).pack(side='left')
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
        tk.Button(beam, text='Add reinforcement beam over selected rows',
                 command=self._add_reinforcement_beam).pack(padx=4, pady=(2, 4), anchor='w')

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
