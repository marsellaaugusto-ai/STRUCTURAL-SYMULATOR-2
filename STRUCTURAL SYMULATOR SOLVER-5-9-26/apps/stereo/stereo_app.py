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

The 3D view is orbited/panned/zoomed with the MOUSE ONLY (left-drag orbit,
wheel zoom, middle-drag pan) -- there is deliberately no toolbar button for
any of the three, per that same request.
"""
import math
import copy
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import units
from common import ZoomCanvas, FlowBar, ScrollPanel, UnitsMixin, declutter_text

from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_math as sm
from apps.stereo import stereo_checks as sc
from apps.stereo import stereo_reports as sr

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

DOF_LABELS = (('ux', 'Ux'), ('uy', 'Uy'), ('uz', 'Uz'),
              ('rx', 'Rx'), ('ry', 'Ry'), ('rz', 'Rz'))
PRESET_NAMES = ('free', 'pin', 'fixed', 'rollerX', 'rollerY', 'rollerZ', 'custom')

GRID_FAMILIES = (('flat_grid', 'Flat double-layer grid'),
                 ('barrel_vault', 'Barrel vault'),
                 ('dome', 'Dome (Schwedler ribs)'))
FAMILY_KEY = {label: key for key, label in GRID_FAMILIES}
FAMILY_LABEL = {key: label for key, label in GRID_FAMILIES}

# Which member roles (stereo_geometry.py tags every member with one) act as
# CHORDS (the primary top/bottom/outer/hoop/meridian framing) vs WEBS (the
# diagonals/braces tying the two chord surfaces, or a single layer's shell,
# together). A role not listed here defaults to the web section, which is
# always the more numerous and lighter-loaded member family in practice.
CHORD_ROLES = {'bottom_chord', 'top_chord', 'outer_rib', 'inner_rib', 'purlin',
              'hoop', 'meridian'}

QUICK_SUPPORT_CUSTOM = 'Custom (edit per node below)'
QUICK_SUPPORT_PIN = 'All suggested nodes: pinned'
QUICK_SUPPORT_FIXED = 'All suggested nodes: fixed'
QUICK_SUPPORT_CLEAR = 'Clear all supports'
QUICK_SUPPORT_CHOICES = (QUICK_SUPPORT_CUSTOM, QUICK_SUPPORT_PIN,
                         QUICK_SUPPORT_FIXED, QUICK_SUPPORT_CLEAR)


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
        self.selected_node = None
        self._support_candidates = []
        self._load_nodes = {}

        self.azimuth = 35.0
        self.elevation = 22.0
        self._drag_start = None
        self._dragged = False

        self.grid_family = tk.StringVar(value=FAMILY_LABEL['flat_grid'])

        self._undo_stack = []
        self._redo_stack = []

        self._build_ui()
        self.init_units(repaint=self._on_units_changed)
        self._generate(push_undo=False)

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
        fam_box = ttk.Combobox(g, textvariable=self.grid_family, state='readonly', width=22,
                               values=[label for _key, label in GRID_FAMILIES])
        fam_box.pack(side='left')
        fam_box.bind('<<ComboboxSelected>>', lambda e: self._on_generator_change())
        tk.Button(g, text='Generate', font=('Helvetica', 9, 'bold'),
                  command=self._generate).pack(side='left', padx=4)

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
        self.show_deformed = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='Show deformed', variable=self.show_deformed, bg=BG,
                       command=self._draw).pack(side='left', padx=(8, 0))
        self.deform_scale = tk.IntVar(value=50)
        tk.Scale(g, from_=1, to=500, orient='horizontal', variable=self.deform_scale,
                length=90, showvalue=True, command=lambda _v: self._draw()
                ).pack(side='left')

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
        # Left-drag orbits the camera; wheel zoom and middle-drag pan are
        # already wired by ZoomCanvas itself -- chained (add='+') rather
        # than replaced, purely to flag that the user has now taken control
        # of the view. A plain click (no drag) still selects the nearest
        # node -- distinguished from an orbit drag by a small pixel
        # threshold in _on_canvas_motion, so neither gesture steals the
        # other.
        self.canvas.bind('<ButtonPress-1>', self._on_canvas_press)
        self.canvas.bind('<B1-Motion>', self._on_canvas_motion)
        self.canvas.bind('<ButtonRelease-1>', self._on_canvas_release)
        for seq in ('<ButtonPress-2>', '<MouseWheel>', '<Button-4>', '<Button-5>'):
            self.canvas.bind(seq, self._mark_view_touched, add='+')

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
        self.frame_flat_grid = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_flat_grid, 'Modules X (nx):', self.fg_nx)
        self._labeled_entry(self.frame_flat_grid, 'Modules Y (ny):', self.fg_ny)
        self._labeled_entry(self.frame_flat_grid, 'Module size (m):', self.fg_module)
        self._labeled_entry(self.frame_flat_grid, 'Depth (m):', self.fg_depth)
        tk.Checkbutton(self.frame_flat_grid, text='Offset top layer (square-on-square offset)',
                       variable=self.fg_offset, bg=BG, font=('Helvetica', 8)
                      ).pack(anchor='w', padx=6, pady=(2, 4))

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

        self.dm_radius = tk.DoubleVar(value=10.0)
        self.dm_rise = tk.DoubleVar(value=3.0)
        self.dm_n_rings = tk.IntVar(value=4)
        self.dm_n_sectors = tk.IntVar(value=12)
        self.frame_dome = tk.Frame(box, bg=BG)
        self._labeled_entry(self.frame_dome, 'Base radius (m):', self.dm_radius)
        self._labeled_entry(self.frame_dome, 'Rise (m):', self.dm_rise)
        self._labeled_entry(self.frame_dome, 'Rings:', self.dm_n_rings)
        self._labeled_entry(self.frame_dome, 'Sectors:', self.dm_n_sectors)

        self._param_frames = {'flat_grid': self.frame_flat_grid,
                              'barrel_vault': self.frame_barrel_vault,
                              'dome': self.frame_dome}

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
        self.self_weight_on = tk.BooleanVar(value=True)
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
        self.sel_label = tk.Label(box, text='(click a node in the view)', bg=BG, fg='#666',
                                  font=('Helvetica', 9), wraplength=PANEL_W - 24, justify='left')
        self.sel_label.pack(anchor='w', padx=6, pady=4)

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
                mesh = sg.flat_grid(nx * module, ny * module, self.fg_depth.get(),
                                    module, offset=self.fg_offset.get())
            elif key == 'barrel_vault':
                mesh = sg.barrel_vault(self.bv_span.get(), self.bv_rise.get(),
                                       self.bv_length.get(), int(self.bv_n_arch.get()),
                                       int(self.bv_n_bays.get()), self.bv_double.get(),
                                       self.bv_depth.get())
            else:
                mesh = sg.dome(self.dm_radius.get(), self.dm_rise.get(),
                               int(self.dm_n_rings.get()), int(self.dm_n_sectors.get()))
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror('Generator error', str(exc))
            return

        if push_undo:
            self._push_undo('generate ' + key)
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
        self.selected_node = None
        self._reset_view(redraw=False)
        self._refresh_all()

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

    def _apply_support(self):
        try:
            node = int(self.sup_node_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror('Boundary condition', 'Enter a valid node index.')
            return
        if not (0 <= node < len(self.nodes)):
            messagebox.showerror('Boundary condition', f'Node {node} does not exist.')
            return
        self._push_undo('apply support')
        self.sup_quick_var.set(QUICK_SUPPORT_CUSTOM)
        dofs = {d: v.get() for d, v in self.dof_vars.items()}
        preset = self.sup_preset_var.get()
        entry = {'node': node, 'dofs': dofs}
        if preset != 'custom':
            entry['type'] = preset
        self.supports = [s for s in self.supports if s['node'] != node]
        self.supports.append(entry)
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _remove_support(self):
        try:
            node = int(self.sup_node_var.get())
        except (tk.TclError, ValueError):
            return
        before = len(self.supports)
        self._push_undo('remove support')
        self.sup_quick_var.set(QUICK_SUPPORT_CUSTOM)
        self.supports = [s for s in self.supports if s['node'] != node]
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
        try:
            node = int(self.ld_node_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror('Load', 'Enter a valid node index.')
            return
        if not (0 <= node < len(self.nodes)):
            messagebox.showerror('Load', f'Node {node} does not exist.')
            return
        self._push_undo('apply load')
        entry = {'node': node, 'fx': self.ld_fx.get(), 'fy': self.ld_fy.get(),
                 'fz': self.ld_fz.get(), 'mx': self.ld_mx.get(), 'my': self.ld_my.get(),
                 'mz': self.ld_mz.get()}
        self.loads = [ld for ld in self.loads if ld['node'] != node]
        self.loads.append(entry)
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _remove_load(self):
        try:
            node = int(self.ld_node_var.get())
        except (tk.TclError, ValueError):
            return
        before = len(self.loads)
        self._push_undo('remove load')
        self.loads = [ld for ld in self.loads if ld['node'] != node]
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

    # ── camera (mouse-only: left-drag orbit, wheel zoom, middle-drag pan) ────
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

    def _on_canvas_press(self, event):
        self._drag_start = (event.x, event.y, self.azimuth, self.elevation)
        self._dragged = False

    def _on_canvas_motion(self, event):
        if self._drag_start is None:
            return
        x0, y0, az0, el0 = self._drag_start
        dx, dy = event.x - x0, event.y - y0
        if not self._dragged and (abs(dx) > self.DRAG_THRESHOLD_PX
                                  or abs(dy) > self.DRAG_THRESHOLD_PX):
            self._dragged = True
            self._view_touched = True
        if self._dragged:
            self.azimuth = (az0 + dx * self.DEG_PER_PX) % 360.0
            self.elevation = max(-89.0, min(89.0, el0 - dy * self.DEG_PER_PX))
            self._draw()

    def _on_canvas_release(self, event):
        if self._drag_start is not None and not self._dragged:
            self._select_node_at(event.x, event.y)
        self._drag_start = None
        self._dragged = False

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

    def _display_nodes(self):
        """World-space node positions to actually draw: the model as
        generated, or (Show deformed) offset by the solved displacement
        times the scale slider -- the same def_scale idiom truss_app.py
        uses, just applied directly in metres since this view already
        works in world units rather than pixels."""
        if not (self.show_deformed.get() and self.results is not None):
            return self.nodes
        scale = self.deform_scale.get()
        out = []
        for (x, y, z), nr in zip(self.nodes, self.results['node_res']):
            out.append((x + nr['ux'] / 1000.0 * scale,
                       y + nr['uy'] / 1000.0 * scale,
                       z + nr['uz'] / 1000.0 * scale))
        return out

    def _draw(self):
        c = self.canvas
        c.delete('all')
        if not self.nodes:
            return
        display_nodes = self._display_nodes()
        proj = [self._project(x, y, z) for x, y, z in display_nodes]

        xs = [p[0] for p in proj]; ys = [p[1] for p in proj]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0

        def to_screen(px, py):
            wx = (px - cx) * self.PX_PER_M
            wy = (py - cy) * self.PX_PER_M
            return self.zc.w2s(wx, wy)

        by_force = self.colour_by_force.get() and self.results is not None
        max_abs_N = 0.0
        if by_force:
            max_abs_N = max((abs(mr['N']) for mr in self.results['member_res']), default=0.0)

        order = sorted(range(len(self.members)), key=lambda i: -(
            proj[self.members[i]['a']][2] + proj[self.members[i]['b']][2]))
        for i in order:
            m = self.members[i]
            ax, ay, _ = proj[m['a']]
            bx, by, _ = proj[m['b']]
            sx0, sy0 = to_screen(ax, ay)
            sx1, sy1 = to_screen(bx, by)
            over = False
            if by_force:
                N = self.results['member_res'][i]['N']
                color = force_color(N, max_abs_N)
            else:
                color = MEMBER_RIGID_COLOR if m.get('conn') == 'rigid' else MEMBER_PIN_COLOR
            width = 2
            if self.member_checks and i < len(self.member_checks) and \
               self.member_checks[i].get('checked') and self.member_checks[i]['util'] > 1.0:
                over = True
                width = 3
            kw = {'fill': color, 'width': width, 'tags': 'member'}
            if over:
                kw['dash'] = (5, 3)
            c.create_line(sx0, sy0, sx1, sy1, **kw)

        support_nodes = {s['node'] for s in self.supports
                         if any(sm.support_restraints(s).values())}
        for i, (px, py, _) in enumerate(proj):
            sx, sy = to_screen(px, py)
            r = 5 if i == self.selected_node else 4
            color = NODE_SEL_COLOR if i == self.selected_node else (
                SUPPORT_COLOR if i in support_nodes else NODE_COLOR)
            c.create_oval(sx - r, sy - r, sx + r, sy + r, fill=color, outline='',
                         tags=('node', f'node{i}'))

        labels = []
        for i, (px, py, _) in enumerate(proj):
            sx, sy = to_screen(px, py)
            labels.append(c.create_text(sx + 8, sy - 8, text=str(i), anchor='w',
                                       font=('Helvetica', 7), fill='#555'))
        declutter_text(c, labels)

        self._draw_legend(c, by_force)
        self._to_screen_cache = to_screen   # for hit-testing on click

    def _draw_legend(self, c, by_force):
        x0, y0 = 10, 10
        lines = []
        if by_force:
            lines = [(TENSION_HIGH, 'tension'), (COMPRESSION_HIGH, 'compression'),
                    (NEAR_ZERO_COLOR, '~0 (or over capacity: dashed)')]
        else:
            lines = [(MEMBER_PIN_COLOR, 'pin'), (MEMBER_RIGID_COLOR, 'rigid'),
                    (NEAR_ZERO_COLOR, 'over capacity: dashed')]
        for i, (color, text) in enumerate(lines):
            y = y0 + i * 15
            c.create_line(x0, y, x0 + 18, y, fill=color, width=3)
            c.create_text(x0 + 24, y, text=text, anchor='w', font=('Helvetica', 8), fill='#444')
        hint_y = y0 + len(lines) * 15 + 6
        c.create_text(x0, hint_y, anchor='nw', font=('Helvetica', 8), fill='#888',
                     text='left-drag: orbit  ·  wheel: zoom  ·  middle-drag: pan')

    def _select_node_at(self, ex, ey):
        if not self.nodes:
            return
        display_nodes = self._display_nodes()
        proj = [self._project(x, y, z) for x, y, z in display_nodes]
        xs = [p[0] for p in proj]; ys = [p[1] for p in proj]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
        best, best_d = None, 12.0
        for i, (px, py, _) in enumerate(proj):
            wx = (px - cx) * self.PX_PER_M
            wy = (py - cy) * self.PX_PER_M
            sx, sy = self.zc.w2s(wx, wy)
            d = math.hypot(sx - ex, sy - ey)
            if d < best_d:
                best, best_d = i, d
        if best is None:
            return
        self.selected_node = best
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
        self._draw()

    # ── refresh / lists / results text ──────────────────────────────────────
    def _refresh_all(self):
        self._refresh_support_list()
        self._refresh_load_list()
        self._refresh_results_text()
        self._draw()

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
        self.selected_node = None
        self._refresh_all()

    # ── units ────────────────────────────────────────────────────────────────
    def _on_units_changed(self):
        self._refresh_all()
