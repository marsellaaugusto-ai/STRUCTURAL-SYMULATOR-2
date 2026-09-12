"""Stereo tab -- Tkinter UI for the 3D space-structure calculator.

One interface over every geometry typology stereo_geometry.py can build
(flat double-layer grid, barrel vault, dome), full CIRSOC-checked 3D
direct-stiffness analysis (stereo_math.py), and Excel/report export
(stereo_reports.py) -- the same "geometry generator + analysis + CIRSOC
checks + report/Excel export" pipeline the Truss tab has, generalized to
3D.

Boundary conditions are the one area explicitly asked to be bug-free and
unrestricted: every node's six DOFs (ux,uy,uz,rx,ry,rz) can be restrained
in ANY combination, independent of the quick presets this UI also offers
as a shortcut -- see `_apply_support` below and
`stereo_math.support_restraints`.

Structured after apps/truss/truss_app.py (a plain object mixing in
UnitsMixin, built directly into the tab Frame main.py hands it) and using
common.ScrollPanel/FlowBar for the sidebar and toolbar, exactly like every
other tab, per the 2026-09-12 request that this tab's left panel and
legibility match "the standard of the others" instead of its own
hand-rolled layout.

The 3D view is orbited/panned/zoomed with the MOUSE ONLY (right-drag orbit,
wheel zoom, middle-drag pan) -- there is deliberately no toolbar button for
any of the three, per that same request. Left-drag is reserved for a
Truss-style rubber-band LASSO that multi-selects nodes (a plain left-click
still single-selects), per the 2026-09-12 request to select supports "with
a laso function like in the truss app".
"""
import math
import copy
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import units
from common import ZoomCanvas, FlowBar, ScrollPanel, UnitsMixin, declutter_text, LoadScale

from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_math as sm
from apps.stereo import stereo_checks as sc
from apps.stereo import stereo_reports as sr
from apps.stereo import expr_math as em

BG = '#f0f0ee'
CANVAS_BG = '#ffffff'
PANEL_W = 300

NODE_COLOR = '#1a1a1a'
NODE_SEL_COLOR = '#e0522b'
SUPPORT_COLOR = '#1a6bbd'
MEMBER_PIN_COLOR = '#555555'
MEMBER_RIGID_COLOR = '#7a3fb8'
NEAR_ZERO_COLOR = '#9a9a9a'
NEAR_ZERO_FRAC = 0.03
TENSION_LOW = '#f6cec4'
TENSION_HIGH = '#a3241a'
COMPRESSION_LOW = '#c9dcf5'
COMPRESSION_HIGH = '#17458c'
GAMMA = 0.6   # perceptual compression, same idiom as common.LoadScale's gamma
UNDO_LIMIT = 60
LOAD_COLOR = '#e07b1f'
SUPPORT_BOX_HALF_PX = 7
LASSO_DRAG_THRESHOLD_PX = 4
DEFORM_LOW = '#eaf6ee'    # pale green -- legible, deliberately not pure white
DEFORM_HIGH = '#0e7a3d'   # saturated green -- the largest displacement present
DEFORM_GAMMA = 0.6
DEFORM_MODE_DISPLACEMENT = 'Displacement'
DEFORM_MODE_FORCE = 'Axial force'
DEFORM_MODES = (DEFORM_MODE_DISPLACEMENT, DEFORM_MODE_FORCE)
REACTION_COLOR = '#c2185b'
UTIL_LOW = '#2e7d32'    # green -- well within capacity
UTIL_MID = '#f9a825'    # amber -- approaching capacity
UTIL_HIGH = '#c62828'   # red -- at or over capacity
MEMBER_SEL_COLOR = '#e0522b'
MEMBER_SEL_HIT_PX = 8

DOF_LABELS = (('ux', 'Ux'), ('uy', 'Uy'), ('uz', 'Uz'),
              ('rx', 'Rx'), ('ry', 'Ry'), ('rz', 'Rz'))
PRESET_NAMES = ('free', 'pin', 'fixed', 'rollerX', 'rollerY', 'rollerZ', 'custom')
GRID_PATTERNS = (('square', 'Square (grid-aligned chords)'),
                 ('diagonal', 'Diagonal (diagonal-on-diagonal chords)'))
PATTERN_KEY = {label: key for key, label in GRID_PATTERNS}
PATTERN_LABEL = {key: label for key, label in GRID_PATTERNS}

GRID_FAMILIES = (('flat_grid', 'Flat double-layer grid'),
                 ('hypar_shell', 'Hyperbolic paraboloid (hypar) shell'),
                 ('hip_roof_grid', 'Hip (pyramidal) roof grid'),
                 ('circular_flat_grid', 'Circular flat grid'),
                 ('barrel_vault', 'Barrel vault (circular arch)'),
                 ('parabolic_vault', 'Parabolic vault'),
                 ('elliptic_vault', 'Elliptic vault'),
                 ('dome', 'Dome (Schwedler ribs)'),
                 ('paraboloid_dish', 'Paraboloid dish (antenna)'),
                 ('elliptic_dome', 'Elliptic dome'),
                 ('sphere_shell', 'Full sphere'))
FAMILY_KEY = {label: key for key, label in GRID_FAMILIES}
FAMILY_LABEL = {key: label for key, label in GRID_FAMILIES}

# Which member roles (stereo_geometry.py tags every member with one) act as
# CHORDS (the primary top/bottom/outer/hoop/meridian framing) vs WEBS (the
# diagonals/braces tying the two chord surfaces, or a single layer's shell,
# together). A role not listed here defaults to the web section, which is
# always the more numerous and lighter-loaded member family in practice.
CHORD_ROLES = {'bottom_chord', 'top_chord', 'outer_rib', 'inner_rib', 'purlin',
              'hoop', 'meridian', 'reinf_chord', 'surface_chord'}

QUICK_SUPPORT_CUSTOM = 'Custom (edit per node below)'
QUICK_SUPPORT_PIN = 'All suggested nodes: pinned'
QUICK_SUPPORT_FIXED = 'All suggested nodes: fixed'
QUICK_SUPPORT_CLEAR = 'Clear all supports'
QUICK_SUPPORT_CHOICES = (QUICK_SUPPORT_CUSTOM, QUICK_SUPPORT_PIN,
                         QUICK_SUPPORT_FIXED, QUICK_SUPPORT_CLEAR)


def _point_segment_distance(px, py, ax, ay, bx, by):
    """Shortest distance from point (px, py) to the line SEGMENT (not
    infinite line) from (ax, ay) to (bx, by) -- used for click-to-inspect
    hit-testing against a member's own screen-space line."""
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    nx, ny = ax + t * dx, ay + t * dy
    return math.hypot(px - nx, py - ny)


def _lerp_hex(c1, c2, t):
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return f'#{r:02x}{g:02x}{b:02x}'


def force_color(N, max_abs_N):
    """Red for tension, blue for compression, a gradient by |N| relative to
    the largest force anywhere in the current results -- gamma-compressed
    the same way common.LoadScale sizes a load glyph, so a model with
    forces spanning orders of magnitude still shows visible contrast
    instead of one saturated member and everything else looking ~0. Forces
    below NEAR_ZERO_FRAC of the model's max are drawn a flat neutral grey
    ("~0" in the legend) rather than a barely-tinted color no one could
    read as tension or compression anyway."""
    if max_abs_N < 1e-9:
        return NEAR_ZERO_COLOR
    frac = abs(N) / max_abs_N
    if frac < NEAR_ZERO_FRAC:
        return NEAR_ZERO_COLOR
    frac = min(1.0, frac) ** GAMMA
    if N >= 0:
        return _lerp_hex(TENSION_LOW, TENSION_HIGH, frac)
    return _lerp_hex(COMPRESSION_LOW, COMPRESSION_HIGH, frac)


def deform_color(disp_mm, max_disp_mm):
    """White-to-green spectrum for the deformed-shape overlay: pale (but
    not pure white -- that would be illegible against the canvas
    background) for near-zero displacement, saturated green for whatever
    moved the most, gamma-compressed the same way force_color and
    common.LoadScale size/color everything else in this app so a model
    with displacements spanning orders of magnitude still shows visible
    contrast instead of one saturated member and a field of invisible
    near-white ones."""
    if max_disp_mm < 1e-9:
        return DEFORM_LOW
    frac = min(1.0, disp_mm / max_disp_mm) ** DEFORM_GAMMA
    return _lerp_hex(DEFORM_LOW, DEFORM_HIGH, frac)


def util_color(util):
    """Green-amber-red heat-map for a member's utilization (demand/
    capacity ratio): green at 0, amber at 0.5, red at 1.0 and beyond --
    unlike force_color (which reads sign and relative magnitude within
    THIS model's own force range), this reads an ABSOLUTE, code-defined
    threshold that is the same from one model to the next, so "red" always
    means the same thing: at or over capacity."""
    util = max(0.0, util)
    if util <= 0.5:
        return _lerp_hex(UTIL_LOW, UTIL_MID, util / 0.5)
    if util <= 1.0:
        return _lerp_hex(UTIL_MID, UTIL_HIGH, (util - 0.5) / 0.5)
    return UTIL_HIGH


class StereoApp(UnitsMixin):
    STORAGE_UNITS = units.storage_like('stereo storage', stress=units.MPA)

    def __init__(self, root):
        self.root = root
        self.nodes = []
        self.members = []
        self.loads = []
        self.supports = []
        self.results = None
        self.member_checks = None
        self.err = None
        self.selected_nodes = set()
        self.selected_member = None
        self._support_candidates = []
        self._load_nodes = {}
        self._load_glyphs = {}

        self.azimuth = 35.0
        self.elevation = 22.0
        self._orbit_start = None
        self._orbit_dragged = False
        self._lasso_press = None
        self._lasso_dragging = False
        self._lasso_cur = None

        self.grid_family = tk.StringVar(value=FAMILY_LABEL['flat_grid'])

        self._undo_stack = []
        self._redo_stack = []

        self._build_ui()
        self.init_units(repaint=self._on_units_changed)
        self._generate(push_undo=False)

    @property
    def selected_node(self):
        """The single selected node, for the many single-node code paths
        (the selection panel, the typed node fields' auto-sync) that
        predate multi-select -- None whenever zero or more than one node
        is selected, since neither has one unambiguous "the" node.
        `selected_nodes` (a set) is the real, multi-select-capable state;
        this is a read-only convenience view over it."""
        if len(self.selected_nodes) == 1:
            return next(iter(self.selected_nodes))
        return None

    # ── model snapshot / undo-redo (same shape as truss_app.py) ─────────────
    def _model_snapshot(self):
        return {'nodes': copy.deepcopy(self.nodes), 'members': copy.deepcopy(self.members),
                'loads': copy.deepcopy(self.loads), 'supports': copy.deepcopy(self.supports)}

    def _restore_snapshot(self, snap):
        self.nodes = snap['nodes']
        self.members = snap['members']
        self.loads = snap['loads']
        self.supports = snap['supports']
        self.results = None
        self.member_checks = None

    def _push_undo(self, label=''):
        self._undo_stack.append((label, self._model_snapshot()))
        if len(self._undo_stack) > UNDO_LIMIT:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self):
        if not self._undo_stack:
            return
        _, snap = self._undo_stack.pop()
        self._redo_stack.append(('redo', self._model_snapshot()))
        self._restore_snapshot(snap)
        self._refresh_all()

    def _redo(self):
        if not self._redo_stack:
            return
        _, snap = self._redo_stack.pop()
        self._undo_stack.append(('undo', self._model_snapshot()))
        self._restore_snapshot(snap)
        self._refresh_all()

    # ── UI construction ──────────────────────────────────────────────────────
    def _build_ui(self):
        tb = tk.Frame(self.root, bg=BG)
        tb.pack(side='top', fill='x')
        self.toolbar_flow = FlowBar(tb)

        g = self.toolbar_flow.group()
        tk.Label(g, text='Grid family:', bg=BG).pack(side='left', padx=(4, 2))
        fam_box = ttk.Combobox(g, textvariable=self.grid_family, state='readonly', width=34,
                               values=[label for _key, label in GRID_FAMILIES])
        fam_box.pack(side='left')
        fam_box.bind('<<ComboboxSelected>>', lambda e: self._on_generator_change())
        tk.Button(g, text='Generate', font=('Helvetica', 9, 'bold'),
                  command=self._generate).pack(side='left', padx=4)
        tk.Button(g, text='Custom Surface Wizard…', command=self._open_custom_surface_wizard
                 ).pack(side='left', padx=(2, 4))

        self.toolbar_flow.separator()
        g = self.toolbar_flow.group()
        tk.Button(g, text='▶ Analyze', font=('Helvetica', 9, 'bold'), bg='#dff0d8',
                  command=self._analyze).pack(side='left', padx=2)
        tk.Button(g, text='Reset view', command=self._reset_view).pack(side='left', padx=2)

        self.toolbar_flow.separator()
        g = self.toolbar_flow.group()
        self.colour_by_force = tk.BooleanVar(value=True)
        tk.Checkbutton(g, text='Colour by force', variable=self.colour_by_force, bg=BG,
                       command=self._draw).pack(side='left')
        self.colour_by_util = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Utilization heat-map', variable=self.colour_by_util, bg=BG,
                       command=self._draw).pack(side='left', padx=(6, 0))
        self.show_deformed = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Show deformed', variable=self.show_deformed, bg=BG,
                       command=self._draw).pack(side='left', padx=(8, 0))
        self.deform_scale = tk.IntVar(value=50)
        tk.Scale(g, from_=1, to=500, orient='horizontal', variable=self.deform_scale,
                length=90, showvalue=True, command=lambda _v: self._draw()
                ).pack(side='left')
        self.deformed_only = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Deformed only', variable=self.deformed_only, bg=BG,
                       command=self._draw).pack(side='left', padx=(8, 0))

        self.toolbar_flow.separator()
        g = self.toolbar_flow.group()
        tk.Label(g, text='Deformed colour:', bg=BG, font=('Helvetica', 9)
                ).pack(side='left', padx=(0, 2))
        self.deform_color_mode = tk.StringVar(value=DEFORM_MODE_DISPLACEMENT)
        deform_mode_box = ttk.Combobox(g, textvariable=self.deform_color_mode, state='readonly',
                                       width=16, values=DEFORM_MODES)
        deform_mode_box.pack(side='left')
        deform_mode_box.bind('<<ComboboxSelected>>', lambda e: self._draw())
        tk.Label(g, text='Reference shade:', bg=BG, font=('Helvetica', 9)
                ).pack(side='left', padx=(8, 2))
        self.reference_shade = tk.IntVar(value=78)
        tk.Scale(g, from_=0, to=100, orient='horizontal', variable=self.reference_shade,
                length=80, showvalue=False, command=lambda _v: self._draw()
                ).pack(side='left')

        self.toolbar_flow.separator()
        g = self.toolbar_flow.group()
        self.show_node_labels = tk.BooleanVar(value=True)
        tk.Checkbutton(g, text='Node #', variable=self.show_node_labels, bg=BG,
                       command=self._draw).pack(side='left')
        self.show_member_labels = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Member #', variable=self.show_member_labels, bg=BG,
                       command=self._draw).pack(side='left', padx=(6, 0))
        self.show_loads = tk.BooleanVar(value=True)
        tk.Checkbutton(g, text='Load arrows', variable=self.show_loads, bg=BG,
                       command=self._draw).pack(side='left', padx=(6, 0))
        self.show_reactions = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Reaction arrows', variable=self.show_reactions, bg=BG,
                       command=self._draw).pack(side='left', padx=(6, 0))

        self.toolbar_flow.separator()
        g = self.toolbar_flow.group()
        tk.Label(g, text='Load %:', bg=BG, font=('Helvetica', 9)).pack(side='left', padx=(0, 2))
        self.load_fraction = tk.IntVar(value=100)
        tk.Scale(g, from_=0, to=100, orient='horizontal', variable=self.load_fraction,
                length=110, showvalue=True, command=lambda _v: self._draw()
                ).pack(side='left')
        tk.Label(g, text='(steps through the applied load; the solved '
                       'model is linear, so this just scales the results)',
                bg=BG, font=('Helvetica', 7), fg='#888').pack(side='left', padx=(4, 0))

        self.toolbar_flow.separator()
        g = self.toolbar_flow.group()
        tk.Button(g, text='Undo', command=self._undo).pack(side='left', padx=1)
        tk.Button(g, text='Redo', command=self._redo).pack(side='left', padx=1)

        self.toolbar_flow.separator()
        g = self.toolbar_flow.group()
        tk.Button(g, text='Export Excel…', command=self._export_excel).pack(side='left', padx=2)
        tk.Button(g, text='Import Excel…', command=self._import_excel).pack(side='left', padx=2)
        tk.Button(g, text='Member Report', command=self._show_member_report).pack(side='left', padx=2)

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

        canvas_frame = tk.Frame(main, bg=BG)
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

        self._param_frames = {'flat_grid': self.frame_flat_grid,
                              'hypar_shell': self.frame_hypar_shell,
                              'hip_roof_grid': self.frame_hip_roof_grid,
                              'circular_flat_grid': self.frame_circular_flat_grid,
                              'barrel_vault': self.frame_barrel_vault,
                              'parabolic_vault': self.frame_parabolic_vault,
                              'elliptic_vault': self.frame_elliptic_vault,
                              'dome': self.frame_dome,
                              'paraboloid_dish': self.frame_paraboloid_dish,
                              'elliptic_dome': self.frame_elliptic_dome,
                              'sphere_shell': self.frame_sphere_shell}

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

        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=6, pady=(0, 4))
        self.area_load_on = tk.BooleanVar(value=True)
        tk.Checkbutton(row, text='Apply area load to the roof/shell surface',
                       variable=self.area_load_on, bg=BG, font=('Helvetica', 8)
                      ).pack(anchor='w')
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

        col = tk.LabelFrame(box, text='Column (shaft + capital)', bg=BG,
                            font=('Helvetica', 8, 'bold'))
        col.pack(fill='x', padx=6, pady=(4, 4))
        tk.Label(col, text='Select >=3 nodes (lasso box) for the capital to '
                          'attach to, then:', bg=BG, font=('Helvetica', 8), fg='#666',
                wraplength=PANEL_W - 40, justify='left').pack(anchor='w', padx=4, pady=(2, 0))
        self.col_height = tk.DoubleVar(value=3.0)
        self._labeled_entry(col, 'Shaft height (m):', self.col_height)
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

    # Only the two OUT-OF-SURFACE directions are offered: reinforcing a
    # roof/floor by hanging or raising a triangular truss girder below/
    # above it (offset perpendicular to the surface, apex pointing away --
    # base flush against the two selected rows) is both the realistic use
    # case and the one verified rigid for every row length in
    # tests/test_stereo_geometry.py. An in-plane offset (still within the
    # surface's own z=0 plane, say) was tested and found to leave a soft/
    # singular mode for this triangulation, so it is deliberately not
    # offered here even though reinforcement_beam() itself accepts any
    # non-edge-parallel direction for callers who need it.
    BEAM_DIRECTIONS = {'Down (-Z)': (0.0, 0.0, -1.0), 'Up (+Z)': (0.0, 0.0, 1.0)}

    def _add_column(self):
        targets = sorted(self.selected_nodes)
        if len(targets) < 3:
            messagebox.showerror('Column',
                                 'Select at least 3 nodes (a lasso box) for the capital '
                                 'to attach to first.')
            return
        try:
            height = float(self.col_height.get())
            tiers = int(self.col_tiers.get())
        except (tk.TclError, ValueError):
            messagebox.showerror('Column', 'Enter a valid shaft height.')
            return
        try:
            nodes, members, base, head = sg.add_column(self.nodes, self.members, targets,
                                                        height, tiers=tiers)
        except ValueError as exc:
            messagebox.showerror('Column', str(exc))
            return
        self._push_undo('add column')
        self.nodes, self.members = nodes, members
        self._support_candidates = list(self._support_candidates) + [base]
        self.supports = [s for s in self.supports if s['node'] != base]
        self.supports.append({'node': base, 'type': 'pin'})
        self._apply_sections(members=self.members, redraw=False)
        self.selected_nodes = {base}
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _split_selection_into_two_rows(self):
        """Split the current lasso selection into two equal-length,
        correspondingly-ordered rows for the reinforcement beam: the axis
        with exactly two distinct coordinate values (rounded) is treated as
        "across" the two rows -- e.g. two adjacent bottom-chord rows of a
        flat_grid differ only in y -- and each side is then ordered along
        whichever remaining axis actually varies, so row A's k-th node
        lines up with row B's k-th the way two parallel grid rows do.
        Returns (edge_a, edge_b), each possibly empty if the selection
        does not look like two clean parallel rows."""
        ids = sorted(self.selected_nodes)
        if len(ids) < 4:
            return [], []
        pts = [self.nodes[i] for i in ids]
        axis_values = [sorted({round(p[k], 6) for p in pts}) for k in range(3)]
        row_axis = next((k for k in range(3) if len(axis_values[k]) == 2), None)
        if row_axis is None:
            return [], []
        v0, v1 = axis_values[row_axis]
        group0 = [i for i in ids if round(self.nodes[i][row_axis], 6) == v0]
        group1 = [i for i in ids if round(self.nodes[i][row_axis], 6) == v1]
        if len(group0) != len(group1) or len(group0) < 2:
            return [], []
        remaining = [k for k in range(3) if k != row_axis]
        order_axis = max(remaining, key=lambda k: len(axis_values[k]))
        group0.sort(key=lambda i: self.nodes[i][order_axis])
        group1.sort(key=lambda i: self.nodes[i][order_axis])
        return group0, group1

    def _add_reinforcement_beam(self):
        edge_a, edge_b = self._split_selection_into_two_rows()
        if not edge_a:
            messagebox.showerror('Reinforcement beam',
                                 'Select two parallel rows of >=2 nodes each (a lasso box '
                                 'spanning both rows) first.')
            return
        try:
            depth = float(self.beam_depth.get())
            tiers = int(self.beam_tiers.get())
        except (tk.TclError, ValueError):
            messagebox.showerror('Reinforcement beam', 'Enter a valid offset depth.')
            return
        direction = self.BEAM_DIRECTIONS[self.beam_dir.get()]
        try:
            nodes, members, apex = sg.reinforcement_beam(self.nodes, self.members,
                                                          edge_a, edge_b, depth, direction,
                                                          tiers=tiers)
        except ValueError as exc:
            messagebox.showerror('Reinforcement beam', str(exc))
            return
        self._push_undo('add reinforcement beam')
        self.nodes, self.members = nodes, members
        self._apply_sections(members=self.members, redraw=False)
        self.selected_nodes = set(apex)
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _build_results_panel(self, parent):
        box = tk.LabelFrame(parent, text='Results', bg=BG, font=('Helvetica', 10, 'bold'))
        box.pack(fill='both', padx=6, pady=(4, 8))
        self.results_text = tk.Text(box, height=8, width=32, wrap='word',
                                    font=('Helvetica', 9), relief='flat', bg=BG)
        self.results_text.pack(fill='both', padx=6, pady=6)

    # ── generator ────────────────────────────────────────────────────────────
    def _on_generator_change(self):
        key = FAMILY_KEY[self.grid_family.get()]
        for frame in self._param_frames.values():
            frame.pack_forget()
        self._param_frames[key].pack(fill='x')

    def _generate(self, push_undo=True):
        key = FAMILY_KEY[self.grid_family.get()]
        try:
            if key == 'flat_grid':
                nx, ny = int(self.fg_nx.get()), int(self.fg_ny.get())
                module = self.fg_module.get()
                pattern = PATTERN_KEY[self.fg_pattern.get()]
                mesh = sg.flat_grid(nx * module, ny * module, self.fg_depth.get(),
                                    module, offset=self.fg_offset.get(), pattern=pattern)
            elif key == 'hypar_shell':
                nx, ny = int(self.hp_nx.get()), int(self.hp_ny.get())
                module = self.hp_module.get()
                pattern = PATTERN_KEY[self.hp_pattern.get()]
                mesh = sg.hypar_shell(nx * module, ny * module, self.hp_depth.get(), module,
                                      rise=self.hp_rise.get(), offset=self.hp_offset.get(),
                                      pattern=pattern)
            elif key == 'hip_roof_grid':
                nx, ny = int(self.hr_nx.get()), int(self.hr_ny.get())
                module = self.hr_module.get()
                pattern = PATTERN_KEY[self.hr_pattern.get()]
                mesh = sg.hip_roof_grid(nx * module, ny * module, self.hr_depth.get(), module,
                                        rise=self.hr_rise.get(), offset=self.hr_offset.get(),
                                        pattern=pattern)
            elif key == 'circular_flat_grid':
                mesh = sg.circular_flat_grid(self.cg_radius.get(), self.cg_depth.get(),
                                             int(self.cg_n_rings.get()),
                                             int(self.cg_n_sectors.get()),
                                             offset=self.cg_offset.get())
            elif key == 'barrel_vault':
                mesh = sg.barrel_vault(self.bv_span.get(), self.bv_rise.get(),
                                       self.bv_length.get(), int(self.bv_n_arch.get()),
                                       int(self.bv_n_bays.get()), self.bv_double.get(),
                                       self.bv_depth.get())
            elif key == 'parabolic_vault':
                mesh = sg.parabolic_vault(self.pv_span.get(), self.pv_rise.get(),
                                          self.pv_length.get(), int(self.pv_n_arch.get()),
                                          int(self.pv_n_bays.get()), self.pv_double.get(),
                                          self.pv_depth.get())
            elif key == 'elliptic_vault':
                mesh = sg.elliptic_vault(self.ev_span.get(), self.ev_rise.get(),
                                         self.ev_length.get(), int(self.ev_n_arch.get()),
                                         int(self.ev_n_bays.get()), self.ev_double.get(),
                                         self.ev_depth.get())
            elif key == 'dome':
                mesh = sg.dome(self.dm_radius.get(), self.dm_rise.get(),
                               int(self.dm_n_rings.get()), int(self.dm_n_sectors.get()))
            elif key == 'paraboloid_dish':
                mesh = sg.paraboloid_dish(self.pd_radius.get(), self.pd_rise.get(),
                                          int(self.pd_n_rings.get()),
                                          int(self.pd_n_sectors.get()))
            elif key == 'elliptic_dome':
                mesh = sg.elliptic_dome(self.ed_radius_x.get(), self.ed_radius_y.get(),
                                        self.ed_rise.get(), int(self.ed_n_rings.get()),
                                        int(self.ed_n_sectors.get()))
            else:
                mesh = sg.sphere_shell(self.sp_radius.get(), int(self.sp_n_rings.get()),
                                       int(self.sp_n_sectors.get()))
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror('Generator error', str(exc))
            return

        self._load_mesh(mesh, push_undo=push_undo, undo_label='generate ' + key)

    def _load_mesh(self, mesh, push_undo=True, undo_label='generate'):
        """Replace the whole model with a freshly generated `mesh` dict --
        shared by every generator entry point (the per-family panel's own
        Generate button via _generate, and the Custom Surface Wizard) so
        loading a mesh always resets the same downstream state (supports
        reset to the quick-pin preset, loads/results cleared, selection
        cleared, view reset) instead of two call sites drifting apart."""
        if push_undo:
            self._push_undo(undo_label)
        self.nodes = mesh['nodes']
        self.members = mesh['members']
        self._support_candidates = mesh['support_candidates']
        self._load_nodes = mesh.get('load_nodes', {})
        self._apply_sections(members=self.members, redraw=False)
        self.supports = [{'node': i, 'type': 'pin'} for i in self._support_candidates]
        self.sup_quick_var.set(QUICK_SUPPORT_PIN)
        self.loads = []
        self.results = None
        self.member_checks = None
        self.selected_nodes = set()
        self.selected_member = None
        self._reset_view(redraw=False)
        self._refresh_all()

    # ── Custom Surface Wizard: typed-expression surfaces + domain/module ────
    def _open_custom_surface_wizard(self):
        """A Toplevel dialog for defining a surface by typed expression
        (a GeoGebra-style calculator palette inserts operators/functions
        into whichever expression field last had focus) and sampling it
        into a mesh: a domain coordinate system (Cartesian or Polar), a
        module pattern (square/diagonal/isometric), and either a single
        surface (2D one layer, or 3D that surface plus an auto-offset
        second layer) or two independently-defined surfaces connected as
        a top/bottom double layer -- see stereo_geometry.custom_surface_grid
        and custom_surface_between for what each choice actually builds.
        """
        win = tk.Toplevel(self.root)
        win.title('Custom Surface Wizard')
        win.geometry('660x800')

        # Every tk.*Var below is created with master=win explicitly, not
        # left to default: a StringVar/IntVar/etc. with no master binds
        # itself to whatever tkinter._default_root happens to be at THAT
        # moment, which is not necessarily the Tcl interpreter `win`'s own
        # widgets actually live in when more than one Tk() root exists in
        # the process (e.g. one per test file's own session fixture, as
        # in this app's own test suite) -- when it is not, the widget and
        # its "own" Python Variable object silently talk to two different
        # interpreters, so editing an Entry never reaches var.get() at all
        # (found by running this dialog's tests as part of the FULL suite
        # rather than alone: every field read back as its untouched
        # default, no matter what the widget visibly showed).
        active_entry = {'widget': None}

        def insert_token(text, cursor_back=0):
            w = active_entry['widget']
            if w is None:
                return
            w.insert(tk.INSERT, text)
            if cursor_back:
                w.icursor(w.index(tk.INSERT) - cursor_back)
            w.focus_set()

        def make_expr_row(parent, label_text, var):
            row = tk.Frame(parent, bg=BG)
            row.pack(fill='x', padx=6, pady=2)
            tk.Label(row, text=label_text, bg=BG, width=9, anchor='w',
                    font=('Helvetica', 9)).pack(side='left')
            entry = tk.Entry(row, textvariable=var, font=('Helvetica', 9))
            entry.pack(side='left', fill='x', expand=True)
            entry.bind('<FocusIn>', lambda e, w=entry: active_entry.__setitem__('widget', w))
            return entry

        def make_palette(parent):
            box = tk.LabelFrame(parent, text='Insert (into the last-focused field above)',
                                bg=BG, font=('Helvetica', 8, 'bold'))
            box.pack(fill='x', padx=6, pady=(2, 6))
            buttons = [
                ('x', 'x', 0), ('y', 'y', 0), ('u', 'u', 0), ('v', 'v', 0),
                ('pi', 'pi', 0), ('e', 'e', 0),
                ('+', '+', 0), ('-', '-', 0), ('*', '*', 0), ('/', '/', 0), ('^', '^', 0),
                ('(', '(', 0), (')', ')', 0),
                ('sin', 'sin()', 1), ('cos', 'cos()', 1), ('tan', 'tan()', 1),
                ('sqrt', 'sqrt()', 1), ('exp', 'exp()', 1), ('log', 'log()', 1),
                ('abs', 'abs()', 1),
                ('atan2', 'atan2(,)', 2), ('min', 'min(,)', 2),
                ('max', 'max(,)', 2), ('hypot', 'hypot(,)', 2),
            ]
            row = None
            for idx, (label, text, back) in enumerate(buttons):
                if idx % 8 == 0:
                    row = tk.Frame(box, bg=BG)
                    row.pack(anchor='w')
                tk.Button(row, text=label, width=5, font=('Helvetica', 8),
                         command=lambda t=text, b=back: insert_token(t, b)
                        ).pack(side='left', padx=1, pady=1)

        def make_surface_panel(parent, title):
            """One surface's own definition block: height-field or
            parametric, its own expression field(s), and its own copy of
            the calculator palette. Returns a zero-arg callable that
            compiles the CURRENT field contents into a surface(p, q) ->
            (x, y, z) callable, raising expr_math.ExpressionError for a
            bad expression -- compiled fresh on every call (not once at
            panel-build time) so editing a field after an earlier failed
            Generate attempt is picked up without reopening the dialog."""
            box = tk.LabelFrame(parent, text=title, bg=BG, font=('Helvetica', 9, 'bold'))
            box.pack(fill='x', padx=6, pady=4)

            surf_type = tk.StringVar(master=win, value='height')
            type_row = tk.Frame(box, bg=BG)
            type_row.pack(fill='x', padx=6, pady=2)
            tk.Radiobutton(type_row, text='Height field: z = f(x, y)', value='height',
                          variable=surf_type, bg=BG, font=('Helvetica', 8),
                          command=lambda: toggle()).pack(anchor='w')
            tk.Radiobutton(type_row, text='Parametric: x, y, z of (u, v) -- for a shape '
                                         'no height field can express (a torus, a cylinder...)',
                          value='param', variable=surf_type, bg=BG, font=('Helvetica', 8),
                          wraplength=520, justify='left',
                          command=lambda: toggle()).pack(anchor='w')

            z_var = tk.StringVar(master=win, value='0')
            height_frame = tk.Frame(box, bg=BG)
            make_expr_row(height_frame, 'z(x,y) =', z_var)

            x_var = tk.StringVar(master=win, value='u')
            y_var = tk.StringVar(master=win, value='v')
            zp_var = tk.StringVar(master=win, value='0')
            param_frame = tk.Frame(box, bg=BG)
            make_expr_row(param_frame, 'x(u,v) =', x_var)
            make_expr_row(param_frame, 'y(u,v) =', y_var)
            make_expr_row(param_frame, 'z(u,v) =', zp_var)

            def toggle():
                if surf_type.get() == 'height':
                    param_frame.pack_forget()
                    height_frame.pack(fill='x')
                else:
                    height_frame.pack_forget()
                    param_frame.pack(fill='x')

            height_frame.pack(fill='x')
            make_palette(box)

            def build():
                if surf_type.get() == 'height':
                    return sg.make_height_field_surface(z_var.get())
                return sg.make_parametric_surface(x_var.get(), y_var.get(), zp_var.get())
            return build

        # ── mode: one surface, or two connected as a top/bottom double layer ──
        mode_var = tk.StringVar(master=win, value='single')
        mode_row = tk.Frame(win, bg=BG)
        mode_row.pack(fill='x', padx=6, pady=(6, 2))
        tk.Radiobutton(mode_row, text='Single surface', value='single', variable=mode_var,
                      bg=BG, command=lambda: on_mode_change()).pack(side='left', padx=(0, 12))
        tk.Radiobutton(mode_row, text='Two surfaces (top + bottom)', value='between',
                      variable=mode_var, bg=BG, command=lambda: on_mode_change()
                     ).pack(side='left')

        surfaces_frame = tk.Frame(win, bg=BG)
        surfaces_frame.pack(fill='x')
        single_frame = tk.Frame(surfaces_frame, bg=BG)
        single_build = make_surface_panel(single_frame, 'Surface')
        between_frame = tk.Frame(surfaces_frame, bg=BG)
        top_build = make_surface_panel(between_frame, 'Top surface')
        bottom_build = make_surface_panel(between_frame, 'Bottom surface')
        single_frame.pack(fill='x')

        # ── domain ──────────────────────────────────────────────────────────
        domain_box = tk.LabelFrame(win, text='Domain', bg=BG, font=('Helvetica', 9, 'bold'))
        domain_box.pack(fill='x', padx=6, pady=4)
        coord_var = tk.StringVar(master=win, value='cartesian')
        coord_row = tk.Frame(domain_box, bg=BG)
        coord_row.pack(fill='x', padx=6, pady=2)
        tk.Radiobutton(coord_row, text='Cartesian', value='cartesian', variable=coord_var,
                      bg=BG, command=lambda: on_coord_change()).pack(side='left')
        tk.Radiobutton(coord_row, text='Polar', value='polar', variable=coord_var,
                      bg=BG, command=lambda: on_coord_change()).pack(side='left')
        coord_hint = tk.Label(domain_box, text='', bg=BG, fg='#666', font=('Helvetica', 8))
        coord_hint.pack(anchor='w', padx=6)

        p0_var = tk.DoubleVar(master=win, value=-5.0)
        p1_var = tk.DoubleVar(master=win, value=5.0)
        q0_var = tk.DoubleVar(master=win, value=-5.0)
        q1_var = tk.DoubleVar(master=win, value=5.0)
        n1_var = tk.IntVar(master=win, value=8)
        n2_var = tk.IntVar(master=win, value=8)

        p_label_var = tk.StringVar(master=win, value='p range:')
        prow = tk.Frame(domain_box, bg=BG)
        prow.pack(fill='x', padx=6, pady=2)
        tk.Label(prow, textvariable=p_label_var, bg=BG, width=10, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        tk.Entry(prow, textvariable=p0_var, width=8).pack(side='left')
        tk.Label(prow, text='to', bg=BG).pack(side='left', padx=2)
        tk.Entry(prow, textvariable=p1_var, width=8).pack(side='left')
        tk.Label(prow, text='n1:', bg=BG).pack(side='left', padx=(10, 2))
        tk.Entry(prow, textvariable=n1_var, width=5).pack(side='left')

        q_label_var = tk.StringVar(master=win, value='q range:')
        qrow = tk.Frame(domain_box, bg=BG)
        qrow.pack(fill='x', padx=6, pady=2)
        tk.Label(qrow, textvariable=q_label_var, bg=BG, width=10, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        tk.Entry(qrow, textvariable=q0_var, width=8).pack(side='left')
        tk.Label(qrow, text='to', bg=BG).pack(side='left', padx=2)
        tk.Entry(qrow, textvariable=q1_var, width=8).pack(side='left')
        tk.Label(qrow, text='n2:', bg=BG).pack(side='left', padx=(10, 2))
        tk.Entry(qrow, textvariable=n2_var, width=5).pack(side='left')

        full_circle_var = tk.BooleanVar(master=win, value=False)

        def on_full_circle():
            if full_circle_var.get():
                q0_var.set(0.0)
                q1_var.set(round(2.0 * math.pi, 6))
        full_circle_chk = tk.Checkbutton(domain_box, text='Full circle (q: 0 to 2*pi)',
                                         variable=full_circle_var, bg=BG,
                                         command=on_full_circle)

        def on_coord_change():
            if coord_var.get() == 'polar':
                p_label_var.set('r range:')
                q_label_var.set('theta range:')
                coord_hint.config(text='Polar: p is read as radius, q as angle (radians).')
                full_circle_chk.pack(anchor='w', padx=6, pady=(0, 4))
            else:
                p_label_var.set('p range:')
                q_label_var.set('q range:')
                coord_hint.config(text='Cartesian: p, q ARE the surface\'s own x, y (or u, v).')
                full_circle_chk.pack_forget()
        on_coord_change()

        # ── pattern ─────────────────────────────────────────────────────────
        pattern_box = tk.LabelFrame(win, text='Module pattern', bg=BG,
                                    font=('Helvetica', 9, 'bold'))
        pattern_box.pack(fill='x', padx=6, pady=4)
        pattern_var = tk.StringVar(master=win, value='square')
        for val, label in (('square', 'Square'), ('diagonal', 'Diagonal'),
                          ('isometric', 'Isometric (60°/equilateral)')):
            tk.Radiobutton(pattern_box, text=label, value=val, variable=pattern_var,
                          bg=BG, font=('Helvetica', 9)).pack(side='left', padx=6)

        # ── module (single-surface mode only) ──────────────────────────────
        module_box = tk.LabelFrame(win, text='Module', bg=BG, font=('Helvetica', 9, 'bold'))
        module_var = tk.StringVar(master=win, value='2d')
        mrow = tk.Frame(module_box, bg=BG)
        mrow.pack(fill='x', padx=6, pady=2)
        tk.Radiobutton(mrow, text='2D (single layer)', value='2d', variable=module_var,
                      bg=BG, command=lambda: on_module_change()).pack(side='left', padx=(0, 12))
        tk.Radiobutton(mrow, text='3D (double layer)', value='3d', variable=module_var,
                      bg=BG, command=lambda: on_module_change()).pack(side='left')

        depth_var = tk.DoubleVar(master=win, value=0.5)
        depth_row = tk.Frame(module_box, bg=BG)
        tk.Label(depth_row, text='Offset depth (m):', bg=BG, width=18, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        tk.Entry(depth_row, textvariable=depth_var, width=8).pack(side='left')

        side_var = tk.StringVar(master=win, value='top')
        side_row = tk.Frame(module_box, bg=BG)
        tk.Label(side_row, text='This surface is the:', bg=BG, width=18, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        tk.Radiobutton(side_row, text='Top', value='top', variable=side_var,
                      bg=BG, font=('Helvetica', 9)).pack(side='left')
        tk.Radiobutton(side_row, text='Bottom', value='bottom', variable=side_var,
                      bg=BG, font=('Helvetica', 9)).pack(side='left')

        def on_module_change():
            if module_var.get() == '3d':
                depth_row.pack(fill='x', padx=6, pady=2)
                side_row.pack(fill='x', padx=6, pady=2)
            else:
                depth_row.pack_forget()
                side_row.pack_forget()
        module_box.pack(fill='x', padx=6, pady=4)
        on_module_change()

        def on_mode_change():
            if mode_var.get() == 'single':
                between_frame.pack_forget()
                single_frame.pack(fill='x')
                module_box.pack(fill='x', padx=6, pady=4)
            else:
                single_frame.pack_forget()
                between_frame.pack(fill='x')
                module_box.pack_forget()

        status_var = tk.StringVar(master=win, value='')
        status_label = tk.Label(win, textvariable=status_var, bg=BG, fg='#a3241a',
                                wraplength=620, justify='left', font=('Helvetica', 9))
        status_label.pack(fill='x', padx=6, pady=(2, 4))

        def on_generate():
            status_var.set('')
            try:
                p_range = (float(p0_var.get()), float(p1_var.get()))
                q_range = (float(q0_var.get()), float(q1_var.get()))
                n1, n2 = int(n1_var.get()), int(n2_var.get())
                coord, pattern = coord_var.get(), pattern_var.get()
                if mode_var.get() == 'single':
                    surface = single_build()
                    mesh = sg.custom_surface_grid(
                        surface, coord=coord, pattern=pattern, p_range=p_range,
                        q_range=q_range, n1=n1, n2=n2, module=module_var.get(),
                        depth=float(depth_var.get()), offset_side=side_var.get())
                else:
                    mesh = sg.custom_surface_between(
                        top_build(), bottom_build(), coord=coord, pattern=pattern,
                        p_range=p_range, q_range=q_range, n1=n1, n2=n2)
            except (em.ExpressionError, ValueError, tk.TclError) as exc:
                status_var.set(str(exc))
                return
            self._load_mesh(mesh, push_undo=True, undo_label='custom surface wizard')
            win.destroy()

        tk.Button(win, text='Generate', font=('Helvetica', 9, 'bold'), bg='#dff0d8',
                 command=on_generate).pack(pady=8)

    def _apply_sections(self, members=None, redraw=True):
        members = self.members if members is None else members
        if redraw:
            self._push_undo('apply sections')
        conn = self.sec_conn.get()
        chord = dict(E=self.chord_E.get(), A=self.chord_A.get(), I=self.chord_I.get(),
                    J=self.chord_J.get(), Fy=self.chord_Fy.get(), Fu=self.chord_Fu.get(),
                    K=self.chord_K.get(), r_gyr=self.chord_r.get())
        web = dict(E=self.web_E.get(), A=self.web_A.get(), I=self.web_I.get(),
                  J=self.web_J.get(), Fy=self.web_Fy.get(), Fu=self.web_Fu.get(),
                  K=self.web_K.get(), r_gyr=self.web_r.get())
        for m in members:
            m['conn'] = conn
            m.update(chord if m.get('role') in CHORD_ROLES else web)
        if redraw:
            self.results = None
            self.member_checks = None
            self._refresh_all()

    # ── boundary conditions ──────────────────────────────────────────────────
    def _apply_quick_support_preset(self):
        choice = self.sup_quick_var.get()
        if choice == QUICK_SUPPORT_CUSTOM:
            return
        self._push_undo('quick support preset')
        if choice == QUICK_SUPPORT_PIN:
            self.supports = [{'node': i, 'type': 'pin'} for i in self._support_candidates]
        elif choice == QUICK_SUPPORT_FIXED:
            self.supports = [{'node': i, 'type': 'fixed'} for i in self._support_candidates]
        elif choice == QUICK_SUPPORT_CLEAR:
            self.supports = []
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _preset_to_checkboxes(self):
        preset = self.sup_preset_var.get()
        if preset == 'custom':
            return
        restraints = sm.PRESET_SUPPORTS.get(preset, {})
        for d, _ in DOF_LABELS:
            self.dof_vars[d].set(bool(restraints.get(d, False)))

    def _target_nodes(self, var):
        """The node(s) an Apply/Remove/Add button acts on: every lasso- or
        click-selected node when there is at least one (so a box-selected
        group of supports can be edited in one shot -- the multi-select
        half of the "select supports with a lasso" request), falling back
        to the single typed node index otherwise, exactly as before
        multi-select existed. Returns None (not []) for an outright
        invalid typed index, so callers can tell "nothing selected AND
        the field is garbage" apart from "an empty, valid selection"."""
        if self.selected_nodes:
            return sorted(self.selected_nodes)
        try:
            return [int(var.get())]
        except (tk.TclError, ValueError):
            return None

    def _apply_support(self):
        nodes = self._target_nodes(self.sup_node_var)
        if not nodes:
            messagebox.showerror('Boundary condition',
                                 'Enter a valid node index, or select node(s) in the view.')
            return
        bad = [n for n in nodes if not (0 <= n < len(self.nodes))]
        if bad:
            messagebox.showerror('Boundary condition', f'Node {bad[0]} does not exist.')
            return
        self._push_undo('apply support')
        self.sup_quick_var.set(QUICK_SUPPORT_CUSTOM)
        dofs = {d: v.get() for d, v in self.dof_vars.items()}
        preset = self.sup_preset_var.get()
        target = set(nodes)
        self.supports = [s for s in self.supports if s['node'] not in target]
        for node in nodes:
            entry = {'node': node, 'dofs': dict(dofs)}
            if preset != 'custom':
                entry['type'] = preset
            self.supports.append(entry)
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _remove_support(self):
        nodes = self._target_nodes(self.sup_node_var)
        if not nodes:
            return
        target = set(nodes)
        before = len(self.supports)
        self._push_undo('remove support')
        self.sup_quick_var.set(QUICK_SUPPORT_CUSTOM)
        self.supports = [s for s in self.supports if s['node'] not in target]
        if len(self.supports) == before:
            self._undo_stack.pop()   # nothing changed; do not clutter the stack
            return
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _on_support_list_select(self, _event=None):
        sel = self.sup_list.curselection()
        if not sel:
            return
        sp = self.supports[sel[0]]
        self.sup_node_var.set(sp['node'])
        r = sm.support_restraints(sp)
        self.sup_preset_var.set(sp.get('type') or 'custom')
        for d, _ in DOF_LABELS:
            self.dof_vars[d].set(r[d])

    # ── loads ────────────────────────────────────────────────────────────────
    def _apply_load(self):
        nodes = self._target_nodes(self.ld_node_var)
        if not nodes:
            messagebox.showerror('Load', 'Enter a valid node index, or select node(s) in the view.')
            return
        bad = [n for n in nodes if not (0 <= n < len(self.nodes))]
        if bad:
            messagebox.showerror('Load', f'Node {bad[0]} does not exist.')
            return
        self._push_undo('apply load')
        target = set(nodes)
        self.loads = [ld for ld in self.loads if ld['node'] not in target]
        for node in nodes:
            self.loads.append({'node': node, 'fx': self.ld_fx.get(), 'fy': self.ld_fy.get(),
                               'fz': self.ld_fz.get(), 'mx': self.ld_mx.get(),
                               'my': self.ld_my.get(), 'mz': self.ld_mz.get()})
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _remove_load(self):
        nodes = self._target_nodes(self.ld_node_var)
        if not nodes:
            return
        target = set(nodes)
        before = len(self.loads)
        self._push_undo('remove load')
        self.loads = [ld for ld in self.loads if ld['node'] not in target]
        if len(self.loads) == before:
            self._undo_stack.pop()
            return
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _all_loads(self):
        """Point loads + (optionally) the area load spread over the roof/
        shell surface + (optionally) self-weight -- combined once here so
        _analyze and _export_excel never have to agree on the recipe
        twice."""
        loads = list(self.loads)
        if self.area_load_on.get() and self._load_nodes:
            loads = sm.combine_loads(loads, sm.area_load_to_nodal_loads(
                self._load_nodes, self.area_load_var.get()))
        if self.self_weight_on.get():
            loads = sm.combine_loads(loads, sm.self_weight_loads(
                self.nodes, self.members, self.unit_weight_var.get()))
        return loads

    # ── analysis ─────────────────────────────────────────────────────────────
    def _analyze(self):
        loads = self._all_loads()
        res, err = sm.analyze(self.nodes, self.members, loads, self.supports)
        self.err = err
        if err:
            self.results = None
            self.member_checks = None
            messagebox.showerror('Analysis', err)
        else:
            self.results = res
            self.member_checks = sc.check_all_members(self.nodes, self.members, res['member_res'])
        self._refresh_all()

    # ── camera (mouse-only: right-drag orbit, wheel zoom, middle-drag pan) ───
    DRAG_THRESHOLD_PX = 3
    DEG_PER_PX = 0.4

    def _mark_view_touched(self, _event=None):
        self._view_touched = True

    def _on_canvas_configure(self, event):
        if not self._view_touched and event.width > 10 and event.height > 10:
            self._reset_view()
        else:
            self._draw()

    def _reset_view(self, redraw=True):
        """Reset camera angle, zoom and pan -- and, critically, CENTER the
        model in the canvas. ZoomCanvas.reset_view() alone sets pan to
        (0, 0), which maps the model's own centroid (already subtracted
        out in _draw's `to_screen`) to screen pixel (0, 0) -- the canvas's
        top-left CORNER, not its center. Left uncorrected, most of a
        freshly generated mesh renders half off-screen above and to the
        left of the visible area, which would make mouse orbiting feel
        broken (nothing to see) even though the camera math is fine."""
        self.azimuth = 35.0
        self.elevation = 22.0
        self.zc.reset_view()
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        self.zc.pan_x = (w if w > 1 else 400) / 2.0
        self.zc.pan_y = (h if h > 1 else 400) / 2.0
        self._view_touched = False
        if redraw:
            self._draw()

    def _on_orbit_press(self, event):
        self._orbit_start = (event.x, event.y, self.azimuth, self.elevation)
        self._orbit_dragged = False

    def _on_orbit_motion(self, event):
        if self._orbit_start is None:
            return
        x0, y0, az0, el0 = self._orbit_start
        dx, dy = event.x - x0, event.y - y0
        if not self._orbit_dragged and (abs(dx) > self.DRAG_THRESHOLD_PX
                                        or abs(dy) > self.DRAG_THRESHOLD_PX):
            self._orbit_dragged = True
            self._view_touched = True
        if self._orbit_dragged:
            self.azimuth = (az0 + dx * self.DEG_PER_PX) % 360.0
            self.elevation = max(-89.0, min(89.0, el0 - dy * self.DEG_PER_PX))
            self._draw()

    def _on_orbit_release(self, event):
        self._orbit_start = None
        self._orbit_dragged = False

    # ── lasso (rubber-band) multi-select, mirroring truss_app.py's own
    # _on_press/_on_drag_motion/_on_release box-select ──────────────────────
    def _on_canvas_press(self, event):
        self._lasso_press = (event.x, event.y)
        self._lasso_dragging = False
        self._lasso_cur = None

    def _on_canvas_motion(self, event):
        if self._lasso_press is None:
            return
        x0, y0 = self._lasso_press
        dx, dy = event.x - x0, event.y - y0
        if not self._lasso_dragging and (abs(dx) > LASSO_DRAG_THRESHOLD_PX
                                         or abs(dy) > LASSO_DRAG_THRESHOLD_PX):
            self._lasso_dragging = True
        if self._lasso_dragging:
            self._lasso_cur = (event.x, event.y)
            self._draw()

    def _on_canvas_release(self, event):
        self.canvas.focus_set()   # so a following Delete/Backspace reaches us
        additive = bool(event.state & 0x0001)   # Shift held: add to selection
        if self._lasso_dragging and self._lasso_cur is not None:
            x0, y0 = self._lasso_press
            x1, y1 = self._lasso_cur
            found = set(self._nodes_in_screen_box(x0, y0, x1, y1))
            self.selected_nodes = (self.selected_nodes | found) if additive else found
            self.selected_member = None
            self._sync_selection_fields()
        else:
            self._select_node_at(event.x, event.y, additive=additive)
        self._lasso_press = None
        self._lasso_dragging = False
        self._lasso_cur = None
        self._draw()

    def _project(self, x, y, z):
        """Rotating orthographic projection: azimuth about the global Z
        axis, then elevation as a tilt about the resulting horizontal axis.
        Returns (screen_x_world_units, screen_y_world_units, depth) --
        depth (bigger = farther from the viewer) is used only for simple
        draw-order and node-size hinting, not true hidden-line removal."""
        az = math.radians(self.azimuth)
        el = math.radians(self.elevation)
        xr = x * math.cos(az) - y * math.sin(az)
        yr = x * math.sin(az) + y * math.cos(az)
        zr = z
        y2 = yr * math.cos(el) - zr * math.sin(el)
        depth = yr * math.sin(el) + zr * math.cos(el)
        return xr, -depth, y2   # (screen_x, screen_y, depth-for-sorting)

    PX_PER_M = 20.0

    def _load_frac(self):
        """The 'Load %' slider as a 0..1 fraction. The solved model is
        linear-elastic (small-deflection direct stiffness), so scaling
        every applied load by this fraction scales every displacement,
        member force and reaction by the EXACT same fraction (this is
        superposition, not an approximation) -- letting the whole display
        step through the load from 0% to 100% by just multiplying the
        already-solved results, with no need to re-run the solver for
        every slider tick."""
        return max(0, min(100, self.load_fraction.get())) / 100.0

    def _deformed_nodes_and_disp(self):
        """World-space node positions offset by the solved displacement
        times the scale slider AND the load-fraction slider, and each
        node's own (unscaled by def_scale, but load-fraction-scaled)
        displacement magnitude in mm -- the same def_scale idiom
        truss_app.py uses, just applied directly in metres since this view
        already works in world units rather than pixels. Used only by the
        deformed-shape overlay: the REST structure (self.nodes) is what
        everything else -- the main render, click-select, the lasso --
        always uses, so "Show deformed" draws an additional green overlay
        in parallel rather than moving the real structure out from under
        the mouse."""
        scale = self.deform_scale.get() * self._load_frac()
        deformed, disp_mm = [], []
        for (x, y, z), nr in zip(self.nodes, self.results['node_res']):
            ux, uy, uz = nr['ux'], nr['uy'], nr['uz']
            deformed.append((x + ux / 1000.0 * scale,
                            y + uy / 1000.0 * scale,
                            z + uz / 1000.0 * scale))
            disp_mm.append(math.sqrt(ux * ux + uy * uy + uz * uz) * self._load_frac())
        return deformed, disp_mm

    def _draw(self):
        c = self.canvas
        c.delete('all')
        if not self.nodes:
            return
        # Always the REST structure -- "Show deformed" draws an ADDITIONAL
        # green overlay in parallel (see _draw_deformed_overlay), it never
        # replaces this, so the real structure stays exactly where clicks,
        # the lasso and everything else expect to find it.
        proj = [self._project(x, y, z) for x, y, z in self.nodes]

        xs = [p[0] for p in proj]; ys = [p[1] for p in proj]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0

        def to_screen(px, py):
            wx = (px - cx) * self.PX_PER_M
            wy = (py - cy) * self.PX_PER_M
            return self.zc.w2s(wx, wy)

        # Drawn FIRST (underneath), same convention as truss_app.py's own
        # "Show deformed": the real structure then draws on top of it --
        # UNLESS "Deformed only" asks to see the deformed shape by itself,
        # in which case the reference structure (and everything keyed to
        # it -- labels, load arrows) is skipped entirely below.
        show_def = self.show_deformed.get() and self.results is not None
        deformed_only = show_def and self.deformed_only.get()
        if show_def:
            self._draw_deformed_overlay(c, to_screen)

        frac = self._load_frac()
        by_util = self.colour_by_util.get() and self.member_checks is not None
        by_force = self.colour_by_force.get() and self.results is not None and not by_util
        max_abs_N = 0.0
        if by_force:
            max_abs_N = max((abs(mr['N']) for mr in self.results['member_res']), default=0.0)

        if not deformed_only:
            # While comparing against the deformed overlay, the reference
            # structure fades to a single adjustable grey (rather than its
            # usual force/pin-rigid colours) so it reads as a faint
            # backdrop instead of competing with the overlay for attention.
            ref_grey = self._reference_grey() if show_def else None

            order = sorted(range(len(self.members)), key=lambda i: -(
                proj[self.members[i]['a']][2] + proj[self.members[i]['b']][2]))
            for i in order:
                m = self.members[i]
                ax, ay, _ = proj[m['a']]
                bx, by, _ = proj[m['b']]
                sx0, sy0 = to_screen(ax, ay)
                sx1, sy1 = to_screen(bx, by)
                over = False
                chk = self.member_checks[i] if self.member_checks and i < len(self.member_checks) \
                    else None
                # 'Load %' scales linearly through: N and utilization both
                # scale exactly with the applied load in a linear-elastic
                # solve (see _load_frac's own docstring), so stepping the
                # slider down shows the SAME model at a lighter load,
                # colours included, not just a smaller deformed shape.
                if ref_grey is not None:
                    color = ref_grey
                elif by_util:
                    util = chk['util'] * frac if chk and chk.get('checked') else 0.0
                    color = util_color(util)
                elif by_force:
                    N = self.results['member_res'][i]['N'] * frac
                    color = force_color(N, max_abs_N)
                else:
                    color = MEMBER_RIGID_COLOR if m.get('conn') == 'rigid' else MEMBER_PIN_COLOR
                width = 2
                if chk and chk.get('checked') and chk['util'] * frac > 1.0:
                    over = True
                    width = 3
                if i == self.selected_member:
                    width = max(width, 4)
                kw = {'fill': color, 'width': width, 'tags': 'member'}
                if over:
                    kw['dash'] = (5, 3)
                c.create_line(sx0, sy0, sx1, sy1, **kw)
                if i == self.selected_member:
                    # A halo drawn on top so the selected member reads
                    # clearly regardless of whatever colour mode is active.
                    c.create_line(sx0, sy0, sx1, sy1, fill=MEMBER_SEL_COLOR, width=1,
                                 dash=(2, 2), tags='member')

            support_nodes = {s['node'] for s in self.supports
                             if any(sm.support_restraints(s).values())}
            for i, (px, py, _) in enumerate(proj):
                sx, sy = to_screen(px, py)
                sel = i in self.selected_nodes
                r = 5 if sel else 4
                color = NODE_SEL_COLOR if sel else (
                    ref_grey if ref_grey is not None else (
                    SUPPORT_COLOR if i in support_nodes else NODE_COLOR))
                c.create_oval(sx - r, sy - r, sx + r, sy + r, fill=color, outline='',
                             tags=('node', f'node{i}'))
                # A small box drawn AROUND a supported node -- the "box
                # that symbolises the support" asked for, instead of
                # relying on dot-color alone (which a selection highlight
                # would otherwise override/obscure).
                if i in support_nodes:
                    h = SUPPORT_BOX_HALF_PX
                    box_color = ref_grey if ref_grey is not None else SUPPORT_COLOR
                    c.create_rectangle(sx - h, sy - h, sx + h, sy + h, outline=box_color,
                                       width=2, tags=('node', f'node{i}'))

            if self.show_node_labels.get():
                labels = []
                for i, (px, py, _) in enumerate(proj):
                    sx, sy = to_screen(px, py)
                    labels.append(c.create_text(sx + 8, sy - 8, text=str(i), anchor='w',
                                               font=('Helvetica', 7), fill='#555'))
                declutter_text(c, labels)

            if self.show_member_labels.get():
                mlabels = []
                for i, m in enumerate(self.members):
                    ax, ay, _ = proj[m['a']]
                    bx, by, _ = proj[m['b']]
                    sx0, sy0 = to_screen(ax, ay)
                    sx1, sy1 = to_screen(bx, by)
                    mlabels.append(c.create_text((sx0 + sx1) / 2.0, (sy0 + sy1) / 2.0,
                                                text=str(i), font=('Helvetica', 7, 'italic'),
                                                fill='#8a5a00'))
                declutter_text(c, mlabels)

            if self.show_loads.get():
                self._draw_load_arrows(c, to_screen)

            if self.show_reactions.get() and self.results is not None:
                self._draw_reaction_arrows(c, to_screen, proj)

        if self._lasso_dragging and self._lasso_cur is not None:
            x0, y0 = self._lasso_press
            x1, y1 = self._lasso_cur
            c.create_rectangle(x0, y0, x1, y1, outline='#333333', dash=(5, 3),
                               stipple='gray12', fill='#333333', tags='lasso')

        self._draw_legend(c, by_force, show_def, deformed_only, by_util)
        self._to_screen_cache = to_screen   # for hit-testing on click

    def _reference_grey(self):
        """The reference (rest) structure's adjustable grey shade, used
        instead of its usual force/pin-rigid colouring whenever the
        deformed overlay is also on screen, so the reference reads as a
        faint backdrop rather than competing with the overlay for
        attention. 0 = black, 100 = near-white (never pure white, so it
        stays visible against the canvas background)."""
        v = max(0, min(100, self.reference_shade.get()))
        level = int(round(v / 100.0 * 235))
        return f'#{level:02x}{level:02x}{level:02x}'

    def _draw_deformed_overlay(self, c, to_screen):
        """A wireframe copy of the structure, offset by the solved
        displacement (times the scale slider) and drawn through the SAME
        `to_screen` closure the rest structure uses -- so it deforms "in
        parallel to the at-rest structure and in the same place" rather
        than being independently re-centered (which would visually hide
        the very offset it is meant to show). Colour mode is a toggle:
        DEFORM_MODE_DISPLACEMENT colors each member/node along a white-to-
        green spectrum by how much it actually moved (deform_color), so
        the AMOUNT of displacement is visible at a glance and not just its
        direction -- mirroring truss_app.py's green deformed-shape
        overlay, with that added per-element spectrum; DEFORM_MODE_FORCE
        instead colors each member by its own axial force (the same red/
        blue force_color every other view in this app uses), so the
        deformed shape can be read together with which members are in
        tension vs compression. Support nodes get the same small box
        glyph the reference structure uses, so a support's (typically
        zero) displacement reads clearly even with the reference hidden
        ("Deformed only")."""
        deformed, disp_mm = self._deformed_nodes_and_disp()
        proj_def = [self._project(x, y, z) for x, y, z in deformed]
        max_disp = max(disp_mm, default=0.0)
        by_force_mode = self.deform_color_mode.get() == DEFORM_MODE_FORCE
        frac = self._load_frac()
        max_abs_N = 0.0
        if by_force_mode:
            max_abs_N = max((abs(mr['N']) for mr in self.results['member_res']), default=0.0)

        for i, m in enumerate(self.members):
            a, b = m['a'], m['b']
            ax, ay, _ = proj_def[a]
            bx, by, _ = proj_def[b]
            sx0, sy0 = to_screen(ax, ay)
            sx1, sy1 = to_screen(bx, by)
            if by_force_mode:
                color = force_color(self.results['member_res'][i]['N'] * frac, max_abs_N)
            else:
                color = deform_color((disp_mm[a] + disp_mm[b]) / 2.0, max_disp)
            c.create_line(sx0, sy0, sx1, sy1, fill=color, width=2, tags='deform')

        for i, (px, py, _) in enumerate(proj_def):
            sx, sy = to_screen(px, py)
            color = '#333333' if by_force_mode else deform_color(disp_mm[i], max_disp)
            c.create_oval(sx - 3, sy - 3, sx + 3, sy + 3, fill=color, outline='', tags='deform')

        support_nodes = {s['node'] for s in self.supports
                         if any(sm.support_restraints(s).values())}
        for i in support_nodes:
            px, py, _ = proj_def[i]
            sx, sy = to_screen(px, py)
            h = SUPPORT_BOX_HALF_PX
            c.create_rectangle(sx - h, sy - h, sx + h, sy + h, outline=SUPPORT_COLOR,
                               width=2, tags='deform')

    def _draw_load_arrows(self, c, to_screen):
        """Arrows for every node currently carrying nonzero net load (point
        loads + area load + self-weight, whichever are enabled -- the same
        combined recipe _all_loads() feeds to the solver), sized with
        common.LoadScale exactly the way every other tab draws a load
        glyph, so a model with loads spanning orders of magnitude still
        shows visible contrast at every node instead of one huge arrow and
        a field of invisible stubs. Shrinks with the 'Load %' slider (the
        arrows show the load actually being analyzed right now, not just
        the full specified load) while the underlying LoadScale keeps
        using the FULL-load magnitudes as its reference band, so easing
        the slider down shrinks the arrows smoothly instead of having them
        all rescale relative to a shrinking max."""
        if not self._load_glyphs:
            return
        frac = self._load_frac()
        if frac < 1e-9:
            return
        mags = [math.sqrt(fx * fx + fy * fy + fz * fz)
               for fx, fy, fz in self._load_glyphs.values()]
        scale = LoadScale.of(mags, 6.0, 20.0)
        eps = 1e-3
        for i, (fx, fy, fz) in self._load_glyphs.items():
            mag = math.sqrt(fx * fx + fy * fy + fz * fz)
            if mag < 1e-9 or not (0 <= i < len(self.nodes)):
                continue
            x, y, z = self.nodes[i]
            ux_, uy_, uz_ = fx / mag, fy / mag, fz / mag
            px0, py0, _ = self._project(x, y, z)
            px1, py1, _ = self._project(x + ux_ * eps, y + uy_ * eps, z + uz_ * eps)
            sx0, sy0 = to_screen(px0, py0)
            sx1, sy1 = to_screen(px1, py1)
            ddx, ddy = sx1 - sx0, sy1 - sy0
            d = math.hypot(ddx, ddy)
            if d < 1e-9:
                continue
            length = scale(mag) * frac
            ddx, ddy = ddx / d * length, ddy / d * length
            # Arrowhead points AT the node (the load acts ON it); the tail
            # trails away in the load's own direction.
            c.create_line(sx0 - ddx, sy0 - ddy, sx0, sy0, fill=LOAD_COLOR, width=1.5,
                         arrow=tk.LAST, arrowshape=(5, 6, 2), tags='load')

    def _draw_reaction_arrows(self, c, to_screen, proj):
        """Arrows at every support showing its solved reaction force
        (Fx, Fy, Fz -- moments are not drawn, there is no clean glyph for
        a 3D couple), sized the same LoadScale way as the applied-load
        arrows so the two are visually comparable, and drawn in a distinct
        colour so the two are never confused with each other. The tail
        sits at the support node and the arrow points AWAY from it, in the
        reaction's own direction -- the opposite convention from load
        arrows (which point INTO the node) -- since a reaction is the
        support pushing back on the structure, not a load acting on it.
        Scales with the 'Load %' slider exactly like everything else that
        reads self.results, since a reaction scales linearly with the
        applied load in a linear-elastic solve."""
        reactions = self.results.get('reactions', {})
        if not reactions:
            return
        frac = self._load_frac()
        if frac < 1e-9:
            return
        mags = {i: math.sqrt(r.get('Fx', 0.0) ** 2 + r.get('Fy', 0.0) ** 2
                             + r.get('Fz', 0.0) ** 2) for i, r in reactions.items()}
        scale = LoadScale.of(mags.values(), 6.0, 24.0)
        eps = 1e-3
        for i, mag in mags.items():
            if mag < 1e-9 or not (0 <= i < len(self.nodes)):
                continue
            r = reactions[i]
            fx, fy, fz = r.get('Fx', 0.0), r.get('Fy', 0.0), r.get('Fz', 0.0)
            x, y, z = self.nodes[i]
            ux_, uy_, uz_ = fx / mag, fy / mag, fz / mag
            px0, py0, _ = self._project(x, y, z)
            px1, py1, _ = self._project(x + ux_ * eps, y + uy_ * eps, z + uz_ * eps)
            sx0, sy0 = to_screen(px0, py0)
            sx1, sy1 = to_screen(px1, py1)
            ddx, ddy = sx1 - sx0, sy1 - sy0
            d = math.hypot(ddx, ddy)
            if d < 1e-9:
                continue
            length = scale(mag) * frac
            ddx, ddy = ddx / d * length, ddy / d * length
            c.create_line(sx0, sy0, sx0 + ddx, sy0 + ddy, fill=REACTION_COLOR, width=2,
                         arrow=tk.LAST, arrowshape=(6, 7, 3), tags='reaction')

    def _draw_legend(self, c, by_force, show_def=False, deformed_only=False, by_util=False):
        x0, y0 = 10, 10
        y = y0

        def row(color, text, dashed=False):
            nonlocal y
            kw = {'fill': color, 'width': 3}
            if dashed:
                kw['dash'] = (5, 3)
            c.create_line(x0, y, x0 + 18, y, **kw)
            c.create_text(x0 + 24, y, text=text, anchor='w', font=('Helvetica', 8), fill='#444')
            y += 15

        if not deformed_only:
            if by_util:
                row(UTIL_LOW, 'utilization ~0')
                row(UTIL_MID, 'utilization 0.5')
                row(UTIL_HIGH, 'utilization >= 1.0 (at/over capacity)')
            elif by_force:
                row(TENSION_HIGH, 'tension')
                row(COMPRESSION_HIGH, 'compression')
                row(NEAR_ZERO_COLOR, '~0 force')
            else:
                row(MEMBER_PIN_COLOR, 'pin connection')
                row(MEMBER_RIGID_COLOR, 'rigid connection')
            # Its own row, with an ACTUAL dashed swatch: dashed members
            # were previously folded into the "~0" colour row's text,
            # which never explained what the dashes themselves meant (a
            # point of real confusion -- e.g. supporting only two opposite
            # edges of a grid concentrates force until many members go
            # over capacity and turn dashed, with no visible link back to
            # this line otherwise).
            row('#555555', 'dashed = over capacity (utilisation > 1.0)', dashed=True)
            if self.show_reactions.get() and self.results is not None:
                row(REACTION_COLOR, 'reaction (support pushing back)')

        if show_def:
            if self.deform_color_mode.get() == DEFORM_MODE_FORCE:
                row(TENSION_HIGH, 'deformed shape: tension')
                row(COMPRESSION_HIGH, 'deformed shape: compression')
            else:
                _deformed, disp_mm = self._deformed_nodes_and_disp()
                max_disp = max(disp_mm, default=0.0)
                c.create_line(x0, y, x0 + 18, y, fill=DEFORM_LOW, width=3)
                c.create_line(x0 + 18, y, x0 + 36, y, fill=DEFORM_HIGH, width=3)
                c.create_text(x0 + 42, y, anchor='w', font=('Helvetica', 8), fill='#444',
                             text=f'deformed shape (white→green: 0–{max_disp:.1f} mm)')
                y += 15

        frac = self._load_frac()
        if frac < 0.999:
            c.create_text(x0, y, anchor='w', font=('Helvetica', 8, 'bold'), fill='#a3241a',
                         text=f'Load: {frac * 100:.0f}% of applied')
            y += 15

        hint_y = y + 6
        c.create_text(x0, hint_y, anchor='nw', font=('Helvetica', 8), fill='#888',
                     text='left-drag: lasso select (+Shift: add)  ·  right-drag: orbit\n'
                          'wheel: zoom  ·  middle-drag: pan  ·  □ box = support\n'
                          'click a rod to inspect its force/utilization')

    def _screen_positions(self):
        """Every node's current on-screen (sx, sy) at its REST position, in
        the exact same projection+centering _draw() uses -- shared by
        click-select, lasso box-select and _draw() itself so all three
        agree on where a node actually is. Always the rest position, even
        with "Show deformed" on: that overlay is an ADDITIONAL green copy
        drawn in parallel, not a replacement, so interaction always targets
        the real structure."""
        proj = [self._project(x, y, z) for x, y, z in self.nodes]
        xs = [p[0] for p in proj]; ys = [p[1] for p in proj]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
        out = []
        for px, py, _ in proj:
            wx = (px - cx) * self.PX_PER_M
            wy = (py - cy) * self.PX_PER_M
            out.append(self.zc.w2s(wx, wy))
        return out

    def _nodes_in_screen_box(self, sx0, sy0, sx1, sy1):
        xlo, xhi = sorted((sx0, sx1))
        ylo, yhi = sorted((sy0, sy1))
        return [i for i, (sx, sy) in enumerate(self._screen_positions())
                if xlo <= sx <= xhi and ylo <= sy <= yhi]

    def _sync_selection_fields(self):
        """Push the current single-node selection (if exactly one node is
        selected) into the typed node fields and the selection/BC panels --
        the same sync a click always did, now shared with the lasso path
        too so a one-node lasso box behaves identically to a plain click.
        Falls through to showing the selected MEMBER's own force/
        utilization readout when a rod, not a node, was clicked."""
        best = self.selected_node
        if best is None:
            if self.selected_member is not None:
                self._show_member_info(self.selected_member)
            elif len(self.selected_nodes) > 1:
                self.sel_label.config(text=f'{len(self.selected_nodes)} nodes selected.')
            else:
                self.sel_label.config(
                    text='(click, or drag a box, to select node(s); click a rod to inspect it)')
            return
        self.sup_node_var.set(best)
        self.ld_node_var.set(best)
        x, y, z = self.nodes[best]
        self.sel_label.config(text=f'Node {best}: ({x:.3f}, {y:.3f}, {z:.3f}) m')
        existing = next((s for s in self.supports if s['node'] == best), None)
        if existing is not None:
            r = sm.support_restraints(existing)
            self.sup_preset_var.set(existing.get('type') or 'custom')
            for d, _ in DOF_LABELS:
                self.dof_vars[d].set(r[d])

    def _show_member_info(self, i):
        """The click-to-inspect readout for member `i`: its endpoints/
        role/connectivity always, plus its solved axial force and CIRSOC
        utilization/governing check once ▶ Analyze has run -- the quick,
        one-click alternative to opening the full Member Report table for
        just one rod. Scales N and utilization by the 'Load %' slider like
        every other results display in this tab."""
        m = self.members[i]
        frac = self._load_frac()
        lines = [f'Member {i}: nodes {m["a"]}–{m["b"]}',
                f'role={m.get("role", "web")}  conn={m.get("conn", "pin")}']
        if self.results is not None and i < len(self.results['member_res']):
            N = self.results['member_res'][i]['N'] * frac
            sense = 'tension' if N >= 0 else 'compression'
            lines.append(f'N = {N:+.2f} kN ({sense})')
            if self.member_checks and i < len(self.member_checks):
                chk = self.member_checks[i]
                if chk.get('checked'):
                    util = chk['util'] * frac
                    status = 'OVER' if util > 1.0 else 'OK'
                    lines.append(f'utilization = {util:.2f} ({status})')
                    if chk.get('governing'):
                        lines.append(f'governs: {chk["governing"]}')
                elif chk.get('note'):
                    lines.append(chk['note'])
        else:
            lines.append('Run ▶ Analyze for force/utilization.')
        self.sel_label.config(text='\n'.join(lines))

    def _select_node_at(self, ex, ey, additive=False):
        if not self.nodes:
            return
        best, best_d = None, 12.0
        for i, (sx, sy) in enumerate(self._screen_positions()):
            d = math.hypot(sx - ex, sy - ey)
            if d < best_d:
                best, best_d = i, d
        if best is not None:
            if additive:
                self.selected_nodes.symmetric_difference_update({best})
            else:
                self.selected_nodes = {best}
            self.selected_member = None
            self._sync_selection_fields()
            self._draw()
            return
        # No node close enough -- try the nearest rod instead, so a click
        # on empty space near a member still does something useful.
        mi = self._select_member_at(ex, ey)
        if mi is not None:
            self.selected_member = mi
            if not additive:
                self.selected_nodes = set()
            self._sync_selection_fields()
            self._draw()
            return
        if not additive:
            self.selected_nodes = set()
            self.selected_member = None
            self._sync_selection_fields()
            self._draw()

    def _select_member_at(self, ex, ey):
        """The nearest member to screen point (ex, ey), within
        MEMBER_SEL_HIT_PX of its own line segment, or None -- shares
        _screen_positions()'s REST-position frame so a rod click always
        targets the same geometry a node click would."""
        pts = self._screen_positions()
        best, best_d = None, MEMBER_SEL_HIT_PX
        for i, m in enumerate(self.members):
            sx0, sy0 = pts[m['a']]
            sx1, sy1 = pts[m['b']]
            d = _point_segment_distance(ex, ey, sx0, sy0, sx1, sy1)
            if d < best_d:
                best, best_d = i, d
        return best

    def _on_delete_nodes(self, event=None):
        """Delete every currently selected node, and (transitively) every
        member touching one, remapping every remaining reference to a node
        INDEX -- other members' a/b, supports, loads, support_candidates,
        load_nodes -- down past the removed indices. Node identity in this
        tab is the list index (as in truss_app.py's own _on_delete, which
        this mirrors), so anything left referring to a stale index once
        the list has shifted would be silent corruption, not a crash.
        Deleting a support node (or enough of the mesh) can leave the rest
        of the structure a genuine mechanism -- that surfaces the normal
        way, as Analyze reporting a singular stiffness matrix, rather than
        being auto-patched here."""
        targets = set(self.selected_nodes)
        if not targets:
            return
        self._push_undo('delete node' + ('s' if len(targets) != 1 else ''))

        remap = {}
        new_nodes = []
        for i, n in enumerate(self.nodes):
            if i in targets:
                continue
            remap[i] = len(new_nodes)
            new_nodes.append(n)
        self.nodes = new_nodes
        self.members = [{**m, 'a': remap[m['a']], 'b': remap[m['b']]}
                       for m in self.members if m['a'] not in targets and m['b'] not in targets]
        self.supports = [{**s, 'node': remap[s['node']]}
                        for s in self.supports if s['node'] not in targets]
        self.loads = [{**ld, 'node': remap[ld['node']]}
                    for ld in self.loads if ld['node'] not in targets]
        self._support_candidates = [remap[i] for i in self._support_candidates
                                    if i not in targets]
        self._load_nodes = {remap[i]: v for i, v in self._load_nodes.items()
                           if i not in targets}

        self.selected_nodes = set()
        self.selected_member = None
        self.results = None
        self.member_checks = None
        self._refresh_all()

    # ── refresh / lists / results text ──────────────────────────────────────
    def _refresh_all(self):
        self._load_glyphs = self._combined_loads_by_node()
        self._refresh_support_list()
        self._refresh_load_list()
        self._refresh_results_text()
        self._sync_selection_fields()
        self._draw()

    def _combined_loads_by_node(self):
        """Every node's net (fx, fy, fz) from _all_loads() -- point loads
        plus, when enabled, the area load and self-weight -- collapsed to
        one vector per node so _draw_load_arrows can draw a single glyph
        per node rather than one per load entry. Computed here (only on
        the discrete events that actually change loads or geometry) and
        cached in self._load_glyphs, NOT inside _draw() itself, since
        _draw() also runs on every mouse-move frame while orbiting/panning/
        zooming and self-weight recomputes over every member."""
        by_node = {}
        for ld in self._all_loads():
            n = ld['node']
            cx, cy, cz = by_node.get(n, (0.0, 0.0, 0.0))
            by_node[n] = (cx + ld.get('fx', 0.0), cy + ld.get('fy', 0.0),
                         cz + ld.get('fz', 0.0))
        return by_node

    def _refresh_support_list(self):
        self.sup_list.delete(0, tk.END)
        for s in self.supports:
            r = sm.support_restraints(s)
            flags = ''.join(lbl[0] if r[d] else '-' for d, lbl in DOF_LABELS)
            self.sup_list.insert(tk.END, f"n{s['node']:<4}{s.get('type') or 'custom':<8}{flags}")

    def _refresh_load_list(self):
        self.load_list.delete(0, tk.END)
        for ld in self.loads:
            self.load_list.insert(
                tk.END,
                f"n{ld['node']:<4}Fx={ld.get('fx', 0):.1f} Fy={ld.get('fy', 0):.1f} "
                f"Fz={ld.get('fz', 0):.1f}")

    def _refresh_results_text(self):
        self.results_text.delete('1.0', tk.END)
        text = sr.summary_text(self.nodes, self.members, self.results, self.member_checks)
        self.results_text.insert('1.0', text)

    # ── Member Report ────────────────────────────────────────────────────────
    def _show_member_report(self):
        if self.results is None or self.member_checks is None:
            messagebox.showinfo('Member Report', 'Run ▶ Analyze first.')
            return
        win = tk.Toplevel(self.root)
        win.title('Member Report')
        win.geometry('760x440')

        cols = ('idx', 'a', 'b', 'role', 'conn', 'N', 'mode', 'util', 'status', 'governing')
        headers = {'idx': '#', 'a': 'A', 'b': 'B', 'role': 'Role', 'conn': 'Conn',
                  'N': 'N (kN)', 'mode': 'Mode', 'util': 'Util.', 'status': 'Status',
                  'governing': 'Governing'}
        widths = {'idx': 40, 'a': 40, 'b': 40, 'role': 90, 'conn': 55, 'N': 75,
                 'mode': 90, 'util': 60, 'status': 60, 'governing': 220}

        frame = tk.Frame(win)
        frame.pack(fill='both', expand=True, padx=6, pady=6)
        tv = ttk.Treeview(frame, columns=cols, show='headings', height=18)
        for col in cols:
            tv.heading(col, text=headers[col])
            tv.column(col, width=widths[col], anchor='center')
        vsb = ttk.Scrollbar(frame, orient='vertical', command=tv.yview)
        tv.configure(yscrollcommand=vsb.set)
        tv.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        def sort_key(i):
            chk = self.member_checks[i]
            return -(chk['util']) if chk.get('checked') else 1.0

        for i in sorted(range(len(self.members)), key=sort_key):
            m = self.members[i]
            mr = self.results['member_res'][i]
            chk = self.member_checks[i]
            if chk.get('checked'):
                util_text = f"{chk['util']:.2f}"
                status = 'OVER' if chk['util'] > 1.0 else 'OK'
                governing = chk.get('governing', '')
            else:
                util_text = '—'
                status = '—'
                governing = chk.get('note', '')
            tv.insert('', 'end', values=(i, m['a'], m['b'], m.get('role', ''),
                                        m.get('conn', 'pin'), f"{mr['N']:+.2f}",
                                        chk.get('mode', '') or '', util_text, status,
                                        governing),
                     tags=('over',) if status == 'OVER' else ())
        tv.tag_configure('over', foreground=TENSION_HIGH)

    # ── Excel ────────────────────────────────────────────────────────────────
    def _export_excel(self):
        path = filedialog.asksaveasfilename(defaultextension='.xlsx',
                                            filetypes=[('Excel workbook', '*.xlsx')])
        if not path:
            return
        try:
            sr.export_excel(self.nodes, self.members, self.loads, self.supports,
                            self.results, path, checks=self.member_checks,
                            meta={'grid_family': self.grid_family.get()})
        except Exception as exc:
            messagebox.showerror('Export failed', str(exc))
            return
        messagebox.showinfo('Export', f'Saved to {path}')

    def _import_excel(self):
        path = filedialog.askopenfilename(filetypes=[('Excel workbook', '*.xlsx')])
        if not path:
            return
        try:
            nodes, members, loads, supports = sr.import_excel_model(path)
        except Exception as exc:
            messagebox.showerror('Import failed', str(exc))
            return
        self._push_undo('import excel')
        self.nodes, self.members, self.loads, self.supports = nodes, members, loads, supports
        self._support_candidates = [s['node'] for s in supports]
        self._load_nodes = {}   # an imported model has no known roof surface
        self.area_load_on.set(False)
        self.sup_quick_var.set(QUICK_SUPPORT_CUSTOM)
        self.results = None
        self.member_checks = None
        self.selected_nodes = set()
        self.selected_member = None
        self._refresh_all()

    # ── units ────────────────────────────────────────────────────────────────
    def _on_units_changed(self):
        self._refresh_all()
