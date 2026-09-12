"""
truss_app.py — Truss / Vierendeel tab.

Pin-jointed OR rigid-jointed 2D frame solver (analyze()), the Truss/
Vierendeel schematic + diagram UI (TrussApp), and this tab's Excel
report/import (export_excel / import_excel_model). A rod left "pin" behaves
exactly like a classic truss bar; a rod set to "rigid" carries N, V and end
moments Ma/Mb via a full 2D frame element -- the mechanism a Vierendeel
girder uses in place of diagonals. See TrussApp's docstrings and the
"Vierendeel diagram" toggle for the rest.
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import math, os, sys, subprocess

from common import (
    _ensure_openpyxl, _ensure_matplotlib, render_math,
    SNAP, PX_PER_M, PANEL_W, INIT_CW, INIT_CH, INIT_DH,
    CT, CC, CZ, CD, CN, CS, CL, CSP, CG, CG_MINOR, CG_MICRO, CV, CM, CR, CMOM,
    _beam_gauss_solve, _nice_ticks, _find_diagram_maxima, make_shape_fn,
    ZoomCanvas,
)
gauss_solve = _beam_gauss_solve  # truss's analyze() historically calls this
                                  # name; both solvers are the same algorithm

def _nice_grid_step(base_px, z, target_px=55):
    """Smallest 1-2-5x10^k multiple of base_px whose screen spacing (at the
    given zoom z) is at least target_px. Shared by the adaptive LOD grid
    drawing and the grid-snap increment, so they always stay in sync."""
    seq = (1, 2, 5)
    i = 0
    while True:
        mult = seq[i % 3] * (10 ** (i // 3))
        step = base_px * mult
        if step * z >= target_px or i > 60:
            return step, mult
        i += 1

def _grid_subdiv_of(mult):
    """1-2-5 convention: a '1' or '5' leading digit subdivides by 5, a '2'
    leading digit subdivides by 2 (keeps every intermediate step itself a
    'nice' 1-2-5 multiple)."""
    exp = math.floor(math.log10(mult) + 1e-9)
    lead = mult / (10 ** exp)
    return 2 if abs(lead - 2) < 0.05 else 5

def dist_seg(px, py, ax, ay, bx, by):
    dx, dy = bx-ax, by-ay
    l2 = dx*dx+dy*dy
    if l2 == 0:
        return math.hypot(px-ax, py-ay)
    t = max(0.0, min(1.0, ((px-ax)*dx+(py-ay)*dy)/l2))
    return math.hypot(px-ax-t*dx, py-ay-t*dy)

def near_node(nodes, wx, wy, thr=14):
    """world-space hit test"""
    for i in range(len(nodes)-1, -1, -1):
        if math.hypot(nodes[i][0]-wx, nodes[i][1]-wy) < thr:
            return i
    return -1

def near_rod(nodes, rods, wx, wy, thr=7):
    for i in range(len(rods)-1, -1, -1):
        r = rods[i]
        a, b = nodes[r['a']], nodes[r['b']]
        if dist_seg(wx, wy, a[0], a[1], b[0], b[1]) < thr:
            return i
    return -1

from .truss_math import (analyze, compute_diagrams, compute_node_force_vectors,
                          udl_local_components, find_zero_crossings,
                          deformed_shape_points, deformed_point_at,
                          compute_node_moments, compute_fiber_stress)
from .truss_reports import export_excel, import_excel_model, pil_draw_node_fbd, pil_draw_rod_context

class TrussApp:
    def __init__(self, root):
        self.root = root

        # model data
        self.nodes    = []
        self.rods     = []
        self.loads    = []
        self.supports = []
        self.results  = None
        self.diagrams = None
        self.profiles = {'Default': {'E': 200.0, 'A': 10.0, 'I': 8000.0}}   # rod "families"

        # interaction
        self.tool         = tk.StringVar(value='node')
        self.rod_start    = None
        self.selected_nodes = set()     # multi-select capable (box or piece)
        self.selected_rods  = set()
        self.pending_load = set()
        self.pending_sup  = set()
        self.active_profile = tk.StringVar(value='Default')
        self._tip_win     = None
        self._tip_after   = None

        # box-select drag state
        self._press_sx = self._press_sy = None
        self._press_wx = self._press_wy = None
        self._dragging_box = False
        self._box_cur = None

        # CAD precision state
        self.cad_mode       = tk.StringVar(value='free')  # free|coord|polar|angle_snap
        self.snap_grid      = tk.BooleanVar(value=True)
        self.snap_node      = tk.BooleanVar(value=True)
        self.snap_angle     = tk.BooleanVar(value=False)
        self.snap_angle_deg = tk.IntVar(value=15)
        self.cad_x          = tk.DoubleVar(value=0.0)
        self.cad_y          = tk.DoubleVar(value=0.0)
        self.cad_dist       = tk.DoubleVar(value=1.0)
        self.cad_angle      = tk.DoubleVar(value=0.0)
        self.ruler_active   = tk.BooleanVar(value=False)
        self.ruler_start    = None   # world (wx,wy) or None
        self._mouse_wx      = 0.0   # live world cursor position
        self._mouse_wy      = 0.0
        self._ghost_wx      = None  # where next node would land
        self._ghost_wy      = None
        self._build_ui()
        self._draw()

    # ══════════════════════════════════════════════════════════════════════════
    #  UI
    # ══════════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        root = self.root
        root.configure(bg='#f5f5f3')

        # ── toolbar ──────────────────────────────────────────────────────────
        tb = tk.Frame(root, bg='#ebebea')
        tb.pack(fill='x', padx=6, pady=(6,0))

        self.tool_btns = {}
        for label, val in [('Node','node'),('Rod','rod'),('Support','support'),
                            ('Load','load'),('Select','select')]:
            b = tk.Button(tb, text=label, width=7, relief='flat', bd=0,
                          padx=8, pady=4, font=('Helvetica',11),
                          command=lambda v=val: self._set_tool(v))
            b.pack(side='left', padx=2, pady=3)
            self.tool_btns[val] = b

        tk.Frame(tb, width=1, bg='#ccc').pack(side='left', fill='y', padx=5, pady=3)
        tk.Button(tb, text='Example', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica',11),
                  command=self._load_example).pack(side='left', padx=2)
        tk.Button(tb, text='Example: Vierendeel', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica',11),
                  command=self._load_example_vierendeel).pack(side='left', padx=2)
        tk.Button(tb, text='Clear', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica',11),
                  command=self._clear_all).pack(side='left', padx=2)
        tk.Button(tb, text='Reset view', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica',11),
                  command=self._reset_view).pack(side='left', padx=2)
        tk.Frame(tb, width=1, bg='#ccc').pack(side='left', fill='y', padx=5, pady=3)
        self.show_deform = tk.BooleanVar(value=False)
        tk.Checkbutton(tb, text='Show deformed', variable=self.show_deform,
                       bg='#ebebea', font=('Helvetica',11),
                       command=self._draw).pack(side='left', padx=4)
        self.show_contraflexure = tk.BooleanVar(value=True)
        cf_chk = tk.Checkbutton(tb, text='\u25cb inflection pts', variable=self.show_contraflexure,
                       bg='#ebebea', font=('Helvetica',10), fg='#555',
                       command=self._draw)
        cf_chk.pack(side='left', padx=(0,4))
        self._bind_widget_tooltip(cf_chk,
            'Marks points of contraflexure (M = 0) on the deformed shape, '
            'where the bending curvature reverses. Only shown while '
            '"Show deformed" is also on.')
        self.show_node_moments = tk.BooleanVar(value=False)
        nm_chk = tk.Checkbutton(tb, text='M@nodes', variable=self.show_node_moments,
                       bg='#ebebea', font=('Helvetica',10), fg='#555',
                       command=self._draw)
        nm_chk.pack(side='left', padx=(0,4))
        self._bind_widget_tooltip(nm_chk,
            'Shows the largest individual rod end-moment at each rigid '
            'joint (the moment the connection actually has to be designed '
            'for) as a small label next to the node. Off by default so '
            'plain pin-jointed trusses -- where this is always zero -- '
            'stay uncluttered.')
        tk.Label(tb, text='Scale:', bg='#ebebea',
                 font=('Helvetica',11)).pack(side='left', padx=(8,2))
        self.def_scale = tk.IntVar(value=50)
        tk.Scale(tb, from_=1, to=300, orient='horizontal',
                 variable=self.def_scale, length=90, showvalue=True,
                 bg='#ebebea', bd=0, highlightthickness=0, relief='flat',
                 font=('Helvetica',9),
                 command=lambda _: self._draw()).pack(side='left')
        tk.Frame(tb, width=1, bg='#ccc').pack(side='left', fill='y', padx=5, pady=3)
        tk.Button(tb, text='Export Excel', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica',11), fg='#1a6bbd',
                  command=self._export_excel).pack(side='left', padx=2)
        tk.Button(tb, text='Import Excel', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica',11), fg='#1a6bbd',
                  command=self._import_excel).pack(side='left', padx=2)
        tk.Button(tb, text='Node Force Vectors', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica',11), fg='#1a6bbd',
                  command=self._show_node_vectors_report).pack(side='left', padx=2)
        tk.Button(tb, text='Rod Calculations', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica',11), fg='#1a6bbd',
                  command=self._show_rod_calculations_report).pack(side='left', padx=2)

        # ── main paned area ───────────────────────────────────────────────────
        main = tk.Frame(root, bg='#f5f5f3')
        main.pack(fill='both', expand=True, padx=6, pady=(6,0))

        # truss zoom canvas
        self.zc = ZoomCanvas(main, bg='white', bd=1, relief='solid',
                             highlightthickness=0, cursor='crosshair')
        self.zc._on_zoom_changed = self._draw
        self.zc.pack(side='left', fill='both', expand=True)
        c = self.zc.canvas
        c.configure(width=INIT_CW, height=INIT_CH)
        c.bind('<ButtonPress-1>',   self._on_press)
        c.bind('<B1-Motion>',       self._on_drag_motion)
        c.bind('<ButtonRelease-1>', self._on_release)
        c.bind('<Delete>',     self._on_delete)
        c.bind('<BackSpace>',  self._on_delete)
        c.bind('<Motion>',     self._on_motion)
        c.bind('<Leave>',      self._on_leave)
        c.focus_set()

        # right panel — scrollable (canvas + scrollbar wrapping the real panel)
        panel_outer = tk.Frame(main, width=PANEL_W, bg='#f0f0ee', bd=1, relief='solid')
        panel_outer.pack(side='right', fill='y', padx=(6,0))
        panel_outer.pack_propagate(False)

        panel_canvas = tk.Canvas(panel_outer, bg='#f0f0ee', highlightthickness=0,
                                 width=PANEL_W)
        panel_sb = tk.Scrollbar(panel_outer, orient='vertical', command=panel_canvas.yview)
        panel_canvas.configure(yscrollcommand=panel_sb.set)
        panel_sb.pack(side='right', fill='y')
        panel_canvas.pack(side='left', fill='both', expand=True)

        panel = tk.Frame(panel_canvas, width=PANEL_W, bg='#f0f0ee')
        panel_win = panel_canvas.create_window((0,0), window=panel, anchor='nw',
                                                width=PANEL_W)

        def _panel_on_configure(event):
            panel_canvas.configure(scrollregion=panel_canvas.bbox('all'))
        panel.bind('<Configure>', _panel_on_configure)

        def _panel_mousewheel(event):
            panel_canvas.yview_scroll(int(-1*(event.delta/120)), 'units')
        panel_canvas.bind('<Enter>', lambda e: panel_canvas.bind_all('<MouseWheel>', _panel_mousewheel))
        panel_canvas.bind('<Leave>', lambda e: panel_canvas.unbind_all('<MouseWheel>'))

        self._build_panel(panel)

        # ── diagram pane (shown after analysis) ───────────────────────────────
        self.diag_outer = tk.Frame(root, bg='#f5f5f3')
        diag_hdr = tk.Frame(self.diag_outer, bg='#f5f5f3')
        diag_hdr.pack(fill='x', pady=(0,2))
        tk.Label(diag_hdr, text='Diagrams', bg='#f5f5f3',
                 font=('Helvetica',9,'bold'), fg='#777').pack(side='left')
        self.diagram_mode = tk.StringVar(value='truss')
        # Switching between modes resets the diagram canvas's zoom/pan
        # rather than reusing _draw_diagrams_only directly: each mode uses
        # a differently-shaped "world" layout (per-rod panel grid vs.
        # auto-fit structure silhouette), so carrying over a zoom/pan
        # tuned for one mode into another would show something oddly
        # scaled/off-screen. reset_view() already redraws afterward (it's
        # wired to diag_zc's _on_zoom_changed below).
        dm_chk = tk.Radiobutton(diag_hdr, text='Truss diagrams', variable=self.diagram_mode,
                       value='truss', bg='#f5f5f3', font=('Helvetica',9),
                       command=lambda: self.diag_zc.reset_view())
        dm_chk.pack(side='left', padx=(14,2))
        dm_chk2 = tk.Radiobutton(diag_hdr, text='Vierendeel diagram', variable=self.diagram_mode,
                       value='vierendeel', bg='#f5f5f3', font=('Helvetica',9),
                       command=lambda: self.diag_zc.reset_view())
        dm_chk2.pack(side='left', padx=2)
        dm_chk3 = tk.Radiobutton(diag_hdr, text='Compression/Tension fibers', variable=self.diagram_mode,
                       value='fiber', bg='#f5f5f3', font=('Helvetica',9),
                       command=lambda: self.diag_zc.reset_view())
        dm_chk3.pack(side='left', padx=2)
        tk.Label(diag_hdr, text='(shear silhouette left, moment silhouette right — rigid rods only)',
                 bg='#f5f5f3', fg='#999', font=('Helvetica',8)).pack(side='left', padx=(10,0))
        zoom_hint = tk.Label(diag_hdr, text='🔍 scroll to zoom, middle-drag to pan',
                             bg='#f5f5f3', fg='#aaa', font=('Helvetica',8))
        zoom_hint.pack(side='right', padx=(0,8))
        # paned so diagram area can be resized
        self.diag_zc = ZoomCanvas(self.diag_outer, bg='#fafaf8',
                                  bd=1, relief='solid', highlightthickness=0)
        self.diag_zc._on_zoom_changed = self._draw_diagrams_only
        self.diag_zc.canvas.configure(height=INIT_DH)
        self.diag_zc.pack(fill='both', expand=True)

        # ── CAD precision panel ──────────────────────────────────────────────
        cad = tk.Frame(root, bg='#dde3ec', bd=1, relief='solid')
        cad.pack(fill='x', padx=6, pady=(2,0))

        # --- snap options ---
        snap_f = tk.Frame(cad, bg='#dde3ec')
        snap_f.pack(side='left', padx=(6,0), pady=3)
        tk.Label(snap_f, text='SNAP:', bg='#dde3ec',
                 font=('Helvetica',9,'bold')).pack(side='left', padx=(0,4))
        tk.Checkbutton(snap_f, text='Grid', variable=self.snap_grid,
                       bg='#dde3ec', font=('Helvetica',9),
                       command=self._draw).pack(side='left')
        tk.Checkbutton(snap_f, text='Node', variable=self.snap_node,
                       bg='#dde3ec', font=('Helvetica',9),
                       command=self._draw).pack(side='left')
        tk.Checkbutton(snap_f, text='Angle', variable=self.snap_angle,
                       bg='#dde3ec', font=('Helvetica',9),
                       command=self._draw).pack(side='left')
        tk.Entry(snap_f, textvariable=self.snap_angle_deg, width=3,
                 font=('Helvetica',9)).pack(side='left', padx=(0,2))
        tk.Label(snap_f, text='°', bg='#dde3ec',
                 font=('Helvetica',9)).pack(side='left', padx=(0,8))

        tk.Frame(cad, width=1, bg='#aab', relief='solid').pack(
            side='left', fill='y', pady=2, padx=4)

        # --- coordinate entry ---
        coord_f = tk.Frame(cad, bg='#dde3ec')
        coord_f.pack(side='left', padx=4, pady=3)
        tk.Label(coord_f, text='COORD (m):', bg='#dde3ec',
                 font=('Helvetica',9,'bold')).pack(side='left', padx=(0,4))
        tk.Label(coord_f, text='X', bg='#dde3ec',
                 font=('Helvetica',9)).pack(side='left')
        tk.Entry(coord_f, textvariable=self.cad_x, width=6,
                 font=('Helvetica',9)).pack(side='left', padx=(2,4))
        tk.Label(coord_f, text='Y', bg='#dde3ec',
                 font=('Helvetica',9)).pack(side='left')
        tk.Entry(coord_f, textvariable=self.cad_y, width=6,
                 font=('Helvetica',9)).pack(side='left', padx=(2,4))
        tk.Button(coord_f, text='Place node', relief='flat',
                  bg='#1a6bbd', fg='white', font=('Helvetica',9,'bold'),
                  command=self._cad_place_coord).pack(side='left', padx=(0,4))

        tk.Frame(cad, width=1, bg='#aab', relief='solid').pack(
            side='left', fill='y', pady=2, padx=4)

        # --- polar entry (compass) ---
        polar_f = tk.Frame(cad, bg='#dde3ec')
        polar_f.pack(side='left', padx=4, pady=3)
        tk.Label(polar_f, text='POLAR from node:', bg='#dde3ec',
                 font=('Helvetica',9,'bold')).pack(side='left', padx=(0,4))
        self.polar_ref_var = tk.StringVar(value='—')
        tk.Label(polar_f, textvariable=self.polar_ref_var,
                 bg='#dde3ec', fg='#1a6bbd',
                 font=('Helvetica',9,'bold')).pack(side='left', padx=(0,4))
        tk.Button(polar_f, text='Pick ref', relief='flat',
                  bg='#555', fg='white', font=('Helvetica',9),
                  command=self._cad_pick_ref).pack(side='left', padx=(0,4))
        tk.Label(polar_f, text='Dist (m)', bg='#dde3ec',
                 font=('Helvetica',9)).pack(side='left')
        tk.Entry(polar_f, textvariable=self.cad_dist, width=6,
                 font=('Helvetica',9)).pack(side='left', padx=(2,4))
        tk.Label(polar_f, text='Angle (°)', bg='#dde3ec',
                 font=('Helvetica',9)).pack(side='left')
        tk.Entry(polar_f, textvariable=self.cad_angle, width=6,
                 font=('Helvetica',9)).pack(side='left', padx=(2,4))
        tk.Button(polar_f, text='Place node', relief='flat',
                  bg='#1a6bbd', fg='white', font=('Helvetica',9,'bold'),
                  command=self._cad_place_polar).pack(side='left', padx=(0,4))

        tk.Frame(cad, width=1, bg='#aab', relief='solid').pack(
            side='left', fill='y', pady=2, padx=4)

        # --- ruler toggle ---
        ruler_f = tk.Frame(cad, bg='#dde3ec')
        ruler_f.pack(side='left', padx=4, pady=3)
        tk.Checkbutton(ruler_f, text='📏 Ruler', variable=self.ruler_active,
                       bg='#dde3ec', font=('Helvetica',9,'bold'),
                       command=self._ruler_toggle).pack(side='left')
        self.ruler_label = tk.Label(ruler_f, text='', bg='#dde3ec',
                                     fg='#c0392b', font=('Helvetica',9,'bold'))
        self.ruler_label.pack(side='left', padx=4)

        # --- live cursor readout ---
        self.cursor_var = tk.StringVar(value='x=0.00  y=0.00 m')
        tk.Label(cad, textvariable=self.cursor_var, bg='#dde3ec',
                 font=('Courier',9), fg='#333').pack(side='right', padx=8)

        # polar reference node index
        self._polar_ref_node = None
        self._picking_ref    = False

        # ── status bar ────────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value='Select "Node" and click canvas to start.')
        tk.Label(root, textvariable=self.status_var, anchor='w',
                 bg='#ebebea', font=('Helvetica',10),
                 relief='flat', padx=8, pady=3).pack(fill='x', padx=6, pady=(4,6))

        self._refresh_tool_buttons()

    def _build_panel(self, panel):
        # material
        mf = tk.LabelFrame(panel, text='Assumed material (all rods)', bg='#f0f0ee',
                           font=('Helvetica',10,'bold'), padx=6, pady=4)
        mf.pack(fill='x', padx=8, pady=(8,4))
        tk.Label(mf, text='E and A below are only auxiliary inputs\n'
                          'required to run the stiffness solver — the\n'
                          'output you want is the pure axial force N\n'
                          '(kN) per rod, which you then use to size the\n'
                          'real material and cross-section yourself.\n'
                          'I only matters for rods set to "Rigid" (see\n'
                          'Selection below) — Vierendeel-style members\n'
                          'that also carry shear V and moment M.',
                 bg='#f0f0ee', fg='#666', font=('Helvetica',8),
                 justify='left', wraplength=PANEL_W-30).grid(
                     row=0, column=0, columnspan=2, sticky='w', pady=(0,4))
        tk.Label(mf, text='E (GPa):', bg='#f0f0ee',
                 font=('Helvetica',10)).grid(row=1,column=0,sticky='w')
        self.mat_E = tk.DoubleVar(value=200.0)
        tk.Entry(mf, textvariable=self.mat_E, width=8,
                 font=('Helvetica',10)).grid(row=1,column=1,sticky='e',padx=4)
        tk.Label(mf, text='A (cm²):', bg='#f0f0ee',
                 font=('Helvetica',10)).grid(row=2,column=0,sticky='w')
        self.mat_A = tk.DoubleVar(value=10.0)
        tk.Entry(mf, textvariable=self.mat_A, width=8,
                 font=('Helvetica',10)).grid(row=2,column=1,sticky='e',padx=4)
        tk.Label(mf, text='I (cm⁴, rigid only):', bg='#f0f0ee',
                 font=('Helvetica',10)).grid(row=3,column=0,sticky='w')
        self.mat_I = tk.DoubleVar(value=8000.0)
        tk.Entry(mf, textvariable=self.mat_I, width=8,
                 font=('Helvetica',10)).grid(row=3,column=1,sticky='e',padx=4)

        # load editor
        self.load_frame = tk.LabelFrame(panel, text='Load on node —', bg='#f0f0ee',
                                        font=('Helvetica',10,'bold'), padx=6, pady=4)
        tk.Label(self.load_frame, text='Fx (kN, →+):', bg='#f0f0ee',
                 font=('Helvetica',10)).grid(row=0,column=0,sticky='w')
        self.led_fx = tk.DoubleVar(value=0.0)
        tk.Entry(self.load_frame, textvariable=self.led_fx, width=8,
                 font=('Helvetica',10)).grid(row=0,column=1,padx=4)
        tk.Label(self.load_frame, text='Fy (kN, ↓+):', bg='#f0f0ee',
                 font=('Helvetica',10)).grid(row=1,column=0,sticky='w')
        self.led_fy = tk.DoubleVar(value=10.0)
        tk.Entry(self.load_frame, textvariable=self.led_fy, width=8,
                 font=('Helvetica',10)).grid(row=1,column=1,padx=4)
        tk.Button(self.load_frame, text='Apply load', bg='#1a6bbd', fg='white',
                  font=('Helvetica',10,'bold'), relief='flat',
                  command=self._apply_load).grid(row=2,column=0,columnspan=2,
                                                  sticky='ew',pady=(6,2))
        tk.Button(self.load_frame, text='Remove load', relief='flat',
                  font=('Helvetica',10),
                  command=self._remove_load).grid(row=3,column=0,columnspan=2,
                                                   sticky='ew',pady=2)

        # support editor
        self.sup_frame = tk.LabelFrame(panel, text='Support on node —', bg='#f0f0ee',
                                       font=('Helvetica',10,'bold'), padx=6, pady=4)
        tk.Label(self.sup_frame, text='Type:', bg='#f0f0ee',
                 font=('Helvetica',10)).grid(row=0,column=0,sticky='w')
        self.sup_type = tk.StringVar(value='pin')
        ttk.Combobox(self.sup_frame, textvariable=self.sup_type, width=12,
                     values=['pin','rollerX','rollerY','fixed'], state='readonly',
                     font=('Helvetica',10)).grid(row=0,column=1,padx=4)
        tk.Button(self.sup_frame, text='Apply support', bg='#1a6bbd', fg='white',
                  font=('Helvetica',10,'bold'), relief='flat',
                  command=self._apply_support).grid(row=1,column=0,columnspan=2,
                                                     sticky='ew',pady=(6,2))
        tk.Button(self.sup_frame, text='Remove support', relief='flat',
                  font=('Helvetica',10),
                  command=self._remove_support).grid(row=2,column=0,columnspan=2,
                                                      sticky='ew',pady=2)

        # selection
        self.sel_frame = tk.LabelFrame(panel, text='Selection', bg='#f0f0ee',
                                       font=('Helvetica',10,'bold'), padx=6, pady=4)
        self.sel_frame.pack(fill='x', padx=8, pady=4)
        self.sel_text = tk.Text(self.sel_frame, width=22, height=12, relief='flat',
                                bg='#f0f0ee', font=('Helvetica',9), state='disabled')
        self.sel_text.pack(fill='x')

        # connection type (rigid = Vierendeel-style moment connection, vs
        # pin = classic truss bar) — bulk-applies to selected rods, so you
        # can drag a selection box over many members at once
        self.conn_frame = tk.LabelFrame(panel, text='Connection type (selected rods)',
                                        bg='#f0f0ee', font=('Helvetica',10,'bold'),
                                        padx=6, pady=4)
        self.conn_frame.pack(fill='x', padx=8, pady=4)
        tk.Label(self.conn_frame,
                 text='Pin = classic truss bar (axial only).\n'
                      'Rigid = moment connection (N, V, M) —\n'
                      'use this for Vierendeel-style panels\n'
                      'with no diagonals.',
                 bg='#f0f0ee', fg='#666', font=('Helvetica',8),
                 justify='left', wraplength=PANEL_W-30).pack(anchor='w', pady=(0,4))
        connbtn = tk.Frame(self.conn_frame, bg='#f0f0ee'); connbtn.pack(fill='x')
        tk.Button(connbtn, text='Set Rigid', bg='#1a6bbd', fg='white',
                  font=('Helvetica',9,'bold'), relief='flat',
                  command=lambda: self._set_connection_type('rigid')).pack(
                      side='left', fill='x', expand=True, padx=(0,2))
        tk.Button(connbtn, text='Set Pinned', relief='flat', font=('Helvetica',9),
                  command=lambda: self._set_connection_type('pin')).pack(
                      side='left', fill='x', expand=True, padx=(2,0))

        # uniformly distributed load along selected rods --
        # only meaningful on rigid rods, so applying one auto-converts the
        # selected rods to Rigid if they weren't already
        self.dload_frame = tk.LabelFrame(panel, text='Distributed load (selected rods)',
                                         bg='#f0f0ee', font=('Helvetica',10,'bold'),
                                         padx=6, pady=4)
        self.dload_frame.pack(fill='x', padx=8, pady=4)
        tk.Label(self.dload_frame,
                 text='Positive load follows the orange arrows (kN/m).\n'
                      'Requires "Rigid" — applying one auto-sets\n'
                      'the selected rods to Rigid.',
                 bg='#f0f0ee', fg='#666', font=('Helvetica',8),
                 justify='left', wraplength=PANEL_W-30).pack(anchor='w', pady=(0,4))
        dl_row = tk.Frame(self.dload_frame, bg='#f0f0ee'); dl_row.pack(fill='x')
        tk.Label(dl_row, text='w (kN/m):', bg='#f0f0ee',
                 font=('Helvetica',9)).pack(side='left')
        self.udl_var = tk.DoubleVar(value=10.0)
        tk.Entry(dl_row, textvariable=self.udl_var, width=7,
                 font=('Helvetica',9)).pack(side='left', padx=4)

        self.udl_rotation_var = tk.DoubleVar(value=0.0)
        mode_row = tk.Frame(self.dload_frame, bg='#f0f0ee'); mode_row.pack(fill='x', pady=(2,0))
        tk.Label(mode_row, text='Load direction:', bg='#f0f0ee',
                 font=('Helvetica',9,'bold')).pack(side='left')
        tk.Radiobutton(mode_row, text='Perpendicular', variable=self.udl_rotation_var,
                       value=0.0, bg='#f0f0ee', font=('Helvetica',8),
                       command=self._sync_udl_angle).pack(side='left', padx=(4,0))
        tk.Radiobutton(mode_row, text='Rotated', variable=self.udl_rotation_var,
                       value=90.0, bg='#f0f0ee', font=('Helvetica',8),
                       command=self._sync_udl_angle).pack(side='left', padx=(2,0))

        angle_row = tk.Frame(self.dload_frame, bg='#f0f0ee'); angle_row.pack(fill='x')
        tk.Label(angle_row, text='Rotation from ⟂ (°):', bg='#f0f0ee',
                 font=('Helvetica',9)).pack(side='left')
        self.udl_angle_entry = tk.Entry(angle_row, textvariable=self.udl_rotation_var, width=7,
                                        font=('Helvetica',9))
        self.udl_angle_entry.pack(side='left', padx=4)
        tk.Scale(angle_row, from_=-180, to=180, resolution=1, orient='horizontal',
                 variable=self.udl_rotation_var, length=105, showvalue=False,
                 bg='#f0f0ee', bd=0, highlightthickness=0,
                 command=lambda _: self._draw()).pack(side='left', padx=2)
        tk.Label(angle_row, text='0° ⟂   +90° along A→B   -90° opposite',
                 bg='#f0f0ee', fg='#666', font=('Helvetica',7)).pack(side='left')
        tk.Label(self.dload_frame,
                 text='Default: perpendicular to every rod. Rotate the load direction to\n'
                      'apply horizontal, vertical, or any diagonal distributed load.',
                 bg='#f0f0ee', fg='#666', font=('Helvetica',8), justify='left',
                 wraplength=PANEL_W-30).pack(anchor='w', pady=(1,0))

        dl_btns = tk.Frame(self.dload_frame, bg='#f0f0ee'); dl_btns.pack(fill='x', pady=(4,0))
        tk.Button(dl_btns, text='Apply UDL', bg='#1a6bbd', fg='white',
                  font=('Helvetica',9,'bold'), relief='flat',
                  command=self._apply_udl).pack(side='left', fill='x', expand=True, padx=(0,2))
        tk.Button(dl_btns, text='Clear UDL', relief='flat', font=('Helvetica',9),
                  command=self._clear_udl).pack(side='left', fill='x', expand=True, padx=(2,0))

        # point load on selected rods
        self.pload_frame = tk.LabelFrame(panel, text='Point load on selected rods',
                                          bg='#f0f0ee', font=('Helvetica',10,'bold'),
                                          padx=6, pady=4)
        self.pload_frame.pack(fill='x', padx=8, pady=4)
        pl1 = tk.Frame(self.pload_frame, bg='#f0f0ee'); pl1.pack(fill='x')
        tk.Label(pl1, text='P (kN):', bg='#f0f0ee', font=('Helvetica',9)).pack(side='left')
        self.pload_var = tk.DoubleVar(value=10.0)
        tk.Entry(pl1, textvariable=self.pload_var, width=7,
                 font=('Helvetica',9)).pack(side='left', padx=4)
        tk.Label(pl1, text='% from A:', bg='#f0f0ee', font=('Helvetica',9)).pack(side='left')
        self.pload_pos_var = tk.DoubleVar(value=50.0)
        tk.Entry(pl1, textvariable=self.pload_pos_var, width=6,
                 font=('Helvetica',9)).pack(side='left', padx=4)
        pl2 = tk.Frame(self.pload_frame, bg='#f0f0ee'); pl2.pack(fill='x', pady=(3,0))
        tk.Label(pl2, text='Angle (°):', bg='#f0f0ee', font=('Helvetica',9)).pack(side='left')
        self.pload_angle_var = tk.DoubleVar(value=90.0)
        tk.Entry(pl2, textvariable=self.pload_angle_var, width=7,
                 font=('Helvetica',9)).pack(side='left', padx=4)
        tk.Label(pl2, text='0° = right, 90° = down', bg='#f0f0ee',
                 fg='#666', font=('Helvetica',8)).pack(side='left')
        plbtn = tk.Frame(self.pload_frame, bg='#f0f0ee'); plbtn.pack(fill='x', pady=(4,0))
        tk.Button(plbtn, text='Add point load', bg='#1a6bbd', fg='white',
                  font=('Helvetica',9,'bold'), relief='flat',
                  command=self._apply_point_load).pack(side='left', fill='x', expand=True, padx=(0,2))
        tk.Button(plbtn, text='Clear point loads', relief='flat', font=('Helvetica',9),
                  command=self._clear_point_loads).pack(side='left', fill='x', expand=True, padx=(2,0))

        # rod family / profile management
        self.family_frame = tk.LabelFrame(panel, text='Rod family / profile', bg='#f0f0ee',
                                          font=('Helvetica',10,'bold'), padx=6, pady=4)
        self.family_frame.pack(fill='x', padx=8, pady=4)
        tk.Label(self.family_frame, text='Profile:', bg='#f0f0ee',
                 font=('Helvetica',10)).grid(row=0,column=0,sticky='w')
        self.family_combo = ttk.Combobox(self.family_frame, textvariable=self.active_profile,
                                         width=11, state='readonly', font=('Helvetica',10))
        self.family_combo.grid(row=0,column=1,padx=4)
        tk.Button(self.family_frame, text='Apply to selected rods', bg='#1a6bbd', fg='white',
                  font=('Helvetica',9,'bold'), relief='flat',
                  command=self._assign_profile_to_selection).grid(
                      row=1,column=0,columnspan=2,sticky='ew',pady=(6,2))
        tk.Button(self.family_frame, text='Select same family', relief='flat',
                  font=('Helvetica',9),
                  command=self._select_same_family).grid(
                      row=2,column=0,columnspan=2,sticky='ew',pady=2)
        tk.Button(self.family_frame, text='Manage profiles…', relief='flat',
                  font=('Helvetica',9),
                  command=self._open_profile_manager).grid(
                      row=3,column=0,columnspan=2,sticky='ew',pady=2)
        self._refresh_profile_combo()

        self.analyze_btn = tk.Button(panel, text='▶  Analyze structure', bg='#9e9e9e', fg='white',
                  font=('Helvetica',11,'bold'), relief='flat', pady=6,
                  command=self._run_analysis)
        self.analyze_btn.pack(fill='x', padx=8, pady=(6,2))

        self.res_var = tk.StringVar(value='')
        tk.Label(panel, textvariable=self.res_var, bg='#f0f0ee',
                 font=('Helvetica',10), justify='left',
                 wraplength=PANEL_W-20).pack(fill='x', padx=12, pady=2)

        self.rod_res_frame = tk.LabelFrame(panel, text='Rod forces', bg='#f0f0ee',
                                           font=('Helvetica',10,'bold'), padx=4, pady=4)
        self.rod_res_text = tk.Text(self.rod_res_frame, width=22, height=7,
                                    relief='flat', bg='#f0f0ee',
                                    font=('Courier',9), state='disabled')
        self.rod_res_text.pack(fill='both')

        self.rxn_frame = tk.LabelFrame(panel, text='Support reactions', bg='#f0f0ee',
                                       font=('Helvetica',10,'bold'), padx=4, pady=4)
        self.rxn_text  = tk.Text(self.rxn_frame, width=22, height=5,
                                  relief='flat', bg='#f0f0ee',
                                  font=('Courier',9), state='disabled')
        self.rxn_text.pack(fill='both')

        # legend
        lf = tk.Frame(panel, bg='#f0f0ee')
        lf.pack(side='bottom', fill='x', padx=8, pady=4)
        for col, lbl in [(CT,'Tension'),(CC,'Compression'),(CZ,'Zero/unanalysed'),
                          (CD,'Deformed'),(CR,'Reaction'),(CV,'Shear V'),(CM,'Moment M')]:
            row = tk.Frame(lf, bg='#f0f0ee')
            row.pack(anchor='w', pady=1)
            tk.Canvas(row, width=22, height=4, bg=col, bd=0,
                      highlightthickness=0).pack(side='left', padx=(0,4))
            tk.Label(row, text=lbl, bg='#f0f0ee',
                     font=('Helvetica',9)).pack(side='left')

    # ══════════════════════════════════════════════════════════════════════════
    #  CAD precision helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _world_to_metres(self, wx, wy):
        """Canvas world coords → metres (origin top-left, y flipped)."""
        return wx / PX_PER_M, -wy / PX_PER_M

    def _metres_to_world(self, mx, my):
        return mx * PX_PER_M, -my * PX_PER_M

    def _finest_grid_step_world(self):
        """The finest currently-VISIBLE grid unit, in world units (the same
        SNAP-scaled coordinate system as self.nodes) -- mirrors exactly the
        major/minor/micro step computation used by _draw_adaptive_grid, so
        grid-snap placement always lands on a grid point you can actually
        see on screen at the current zoom, instead of always the fixed 1m
        base unit."""
        z = self.zc.zoom
        step, mult = _nice_grid_step(SNAP, z, target_px=55)
        for _ in range(2):
            sub = _grid_subdiv_of(mult)
            next_step = step / sub
            if next_step * z < 10:
                break
            step, mult = next_step, mult / sub
        return step

    def _compute_ghost(self, wx, wy):
        """
        Given raw world cursor position, apply active snaps and return
        the snapped world position that will be used for node placement.
        """
        # 1. node snap: if close to an existing node, lock to it
        if self.snap_node.get():
            ni = near_node(self.nodes, wx, wy, thr=18/self.zc.zoom)
            if ni >= 0:
                return self.nodes[ni]

        # 2. angle snap: if a rod is being drawn, constrain direction from rod_start
        if self.snap_angle.get() and self.rod_start is not None:
            ref = self.nodes[self.rod_start]
            dx, dy = wx - ref[0], wy - ref[1]
            dist = math.hypot(dx, dy)
            if dist > 0.5:
                deg = self.snap_angle_deg.get()
                raw_angle = math.degrees(math.atan2(-dy, dx))  # y flipped
                snapped   = round(raw_angle / deg) * deg
                rad       = math.radians(snapped)
                wx = ref[0] + dist * math.cos(rad)
                wy = ref[1] - dist * math.sin(rad)  # re-flip y

        # 3. grid snap -- to whatever grid unit is currently visible (scales
        # with the adaptive LOD grid, so zooming in lets you snap to finer
        # subdivisions, just like the grid you actually see)
        if self.snap_grid.get():
            unit = self._finest_grid_step_world()
            wx = round(wx / unit) * unit
            wy = round(wy / unit) * unit

        return wx, wy

    def _cad_place_coord(self):
        """Place a node at the typed absolute coordinates (metres)."""
        try:
            mx = self.cad_x.get()
            my = self.cad_y.get()
        except (tk.TclError, ValueError):
            messagebox.showwarning('Place node',
                'Enter valid numbers for X and Y before placing a node.')
            return
        wx, wy = self._metres_to_world(mx, my)
        self.nodes.append((wx, wy))
        self.results = None; self.diagrams = None
        self._draw_diagrams_only()
        self._draw()
        self.status_var.set(
            f'Node {len(self.nodes)-1} placed at ({mx:.3f}, {my:.3f}) m')

    def _cad_pick_ref(self):
        """Switch canvas into "pick reference node" mode for polar entry."""
        self._picking_ref = True
        self.polar_ref_var.set('click node…')
        self.status_var.set(
            'POLAR REF: click a node on the canvas to use as origin')

    def _cad_place_polar(self):
        """Place a node at distance + angle from the reference node."""
        if self._polar_ref_node is None:
            messagebox.showwarning('Polar', 'Pick a reference node first.')
            return
        ref  = self.nodes[self._polar_ref_node]
        try:
            dist = self.cad_dist.get()   # metres
            ang  = math.radians(self.cad_angle.get())  # 0°=right, CCW positive
        except (tk.TclError, ValueError):
            messagebox.showwarning('Place node',
                'Enter a valid distance and angle before placing a node.')
            return
        dx_m =  dist * math.cos(ang)
        dy_m =  dist * math.sin(ang)
        wx   = ref[0] + dx_m * PX_PER_M
        wy   = ref[1] - dy_m * PX_PER_M  # y flipped in canvas
        self.nodes.append((wx, wy))
        self.results = None; self.diagrams = None
        self._draw_diagrams_only()
        self._draw()
        mx, my = self._world_to_metres(wx, wy)
        self.status_var.set(
            f'Node {len(self.nodes)-1} placed at ({mx:.3f}, {my:.3f}) m  '
            f'[dist={dist:.3f} m, angle={self.cad_angle.get():.1f}°]')

    def _ruler_toggle(self):
        """Reset ruler state when toggled."""
        self.ruler_start = None
        self.ruler_label.configure(text='')
        self._draw()

    # ══════════════════════════════════════════════════════════════════════════
    #  Tooltip
    # ══════════════════════════════════════════════════════════════════════════
    def _show_tooltip(self, sx, sy, text):
        self._hide_tooltip()
        rx = self.zc.canvas.winfo_rootx() + sx + 14
        ry = self.zc.canvas.winfo_rooty() + sy - 10
        tw = tk.Toplevel(self.root)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f'+{rx}+{ry}')
        fr = tk.Frame(tw, bg='#fffde7', bd=1, relief='solid')
        fr.pack()
        tk.Label(fr, text=text, bg='#fffde7', fg='#333',
                 font=('Helvetica',9), justify='left', padx=6, pady=4).pack()
        self._tip_win = tw

    def _hide_tooltip(self):
        if self._tip_after:
            self.root.after_cancel(self._tip_after); self._tip_after = None
        if self._tip_win:
            try: self._tip_win.destroy()
            except: pass
            self._tip_win = None

    def _bind_widget_tooltip(self, widget, text):
        """Small standalone hover tooltip for a plain toolbar widget (as
        opposed to `_show_tooltip`, which is positioned from canvas-space
        coordinates for hovering over model elements)."""
        state = {'win': None}
        def show(_e=None):
            hide()
            rx = widget.winfo_rootx() + 4
            ry = widget.winfo_rooty() + widget.winfo_height() + 4
            tw = tk.Toplevel(self.root)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f'+{rx}+{ry}')
            fr = tk.Frame(tw, bg='#fffde7', bd=1, relief='solid')
            fr.pack()
            tk.Label(fr, text=text, bg='#fffde7', fg='#333', wraplength=260,
                     font=('Helvetica',9), justify='left', padx=6, pady=4).pack()
            state['win'] = tw
        def hide(_e=None):
            if state['win'] is not None:
                try: state['win'].destroy()
                except: pass
                state['win'] = None
        widget.bind('<Enter>', show)
        widget.bind('<Leave>', hide)

    def _on_motion(self, event):
        sx, sy = event.x, event.y
        wx, wy = self.zc.s2w(sx, sy)
        self._mouse_wx, self._mouse_wy = wx, wy

        # live cursor readout in metres
        mx, my = self._world_to_metres(wx, wy)
        self.cursor_var.set(f'x={mx:.2f}  y={my:.2f} m')

        # compute ghost (snapped) position and trigger redraw for preview
        gx, gy = self._compute_ghost(wx, wy)
        self._ghost_wx, self._ghost_wy = gx, gy

        # ruler live measurement
        if self.ruler_active.get() and self.ruler_start is not None:
            rx, ry = self.ruler_start
            dm = math.hypot((gx-rx)/PX_PER_M, (gy-ry)/PX_PER_M)
            ang = math.degrees(math.atan2(-(gy-ry), gx-rx))
            self.ruler_label.configure(
                text=f'd={dm:.3f} m  α={ang:.1f}°')

        # if angle snap is on and drawing a rod, update ghost constantly
        needs_redraw = (self.snap_angle.get() and self.rod_start is not None
                        or self.ruler_active.get()
                        or self.tool.get() in ('node', 'rod'))
        if needs_redraw:
            self._draw()

        self._hide_tooltip()

        ni = near_node(self.nodes, wx, wy, thr=14/self.zc.zoom)
        if ni >= 0:
            n   = self.nodes[ni]
            sup = next((s for s in self.supports if s['node']==ni), None)
            ld  = next((l for l in self.loads    if l['node']==ni), None)
            res = self.results['node_res'][ni] if self.results else None
            rxn = self.results['reactions'].get(ni) if self.results else None
            nm_x, nm_y = self._world_to_metres(n[0], n[1])
            lines = [f'Node {ni}  ({nm_x:.3f}, {nm_y:.3f}) m']
            if sup: lines.append(f'Support: {sup["type"]}')
            if ld:  lines.append(f'Load  Fx={ld["fx"]}  Fy={ld["fy"]} kN')
            if rxn: lines.append(f'Rx={rxn.get("rx",0):.2f}  Ry={rxn.get("ry",0):.2f} kN')
            if res: lines.append(f'ux={res["ux"]:.3f}  uy={res["uy"]:.3f} mm')
            self._tip_after = self.root.after(
                280, lambda t='\n'.join(lines),x=sx,y=sy: self._show_tooltip(x,y,t))
            return

        ri = near_rod(self.nodes, self.rods, wx, wy, thr=7/self.zc.zoom)
        if ri >= 0:
            rod = self.rods[ri]
            na, nb = self.nodes[rod['a']], self.nodes[rod['b']]
            L   = math.hypot(nb[0]-na[0], nb[1]-na[1]) / PX_PER_M
            res = self.results['rod_res'][ri] if self.results else None
            lines = [f'Rod {ri}  ({rod["a"]} → {rod["b"]})',
                     f'L={L:.2f} m   E={rod["E"]} GPa   A={rod["A"]} cm²']
            if res:
                f    = res['force']
                kind = 'Tension' if f>0.01 else ('Compression' if f<-0.01 else 'Zero')
                lines += [f'N = {f:+.2f} kN  [{kind}]']
            self._tip_after = self.root.after(
                280, lambda t='\n'.join(lines),x=sx,y=sy: self._show_tooltip(x,y,t))
            return

        for ld in self.loads:
            n = self.nodes[ld['node']]
            ns, _ = self.zc.w2s(n[0], n[1])
            if math.hypot(ns-sx, _-sy) < 55:
                mag = math.hypot(ld['fx'], ld['fy'])
                lines = [f'Load on node {ld["node"]}',
                         f'Fx={ld["fx"]}  Fy={ld["fy"]} kN',
                         f'|F|={mag:.2f} kN']
                self._tip_after = self.root.after(
                    280, lambda t='\n'.join(lines),x=sx,y=sy: self._show_tooltip(x,y,t))
                return

        for s in self.supports:
            n = self.nodes[s['node']]
            ns, ms = self.zc.w2s(n[0], n[1])
            if math.hypot(ns-sx, ms-sy) < 30:
                rxn  = self.results['reactions'].get(s['node']) if self.results else None
                lines = [f'Support on node {s["node"]}', f'Type: {s["type"]}']
                if rxn: lines.append(f'Rx={rxn.get("rx",0):.2f}  Ry={rxn.get("ry",0):.2f} kN')
                self._tip_after = self.root.after(
                    280, lambda t='\n'.join(lines),x=sx,y=sy: self._show_tooltip(x,y,t))
                return

    def _on_leave(self, event):
        self._hide_tooltip()

    # ══════════════════════════════════════════════════════════════════════════
    #  Tool management
    # ══════════════════════════════════════════════════════════════════════════
    def _set_tool(self, t):
        self.tool.set(t); self.rod_start = None
        msgs = {
            'node':    'Click canvas to place joints (snaps to grid)',
            'rod':     'Click first node then second to connect with a rod',
            'support': 'Click a node, configure support in the panel',
            'load':    'Click a node, set Fx/Fy in the panel, click Apply',
            'select':  'Click nodes/rods to inspect. Delete key removes.',
        }
        self.status_var.set(msgs[t])
        self.load_frame.pack_forget(); self.sup_frame.pack_forget()
        self._refresh_tool_buttons(); self._draw()

    def _refresh_tool_buttons(self):
        act = self.tool.get()
        for k, b in self.tool_btns.items():
            b.configure(bg='#1a6bbd' if k==act else '#ebebea',
                        fg='white'   if k==act else '#333333')

    def _reset_view(self):
        self.zc.reset_view()
        self.diag_zc.reset_view()
        self._draw()
        if self.diagrams: self._draw_diagrams_only()

    # ══════════════════════════════════════════════════════════════════════════
    #  Canvas interaction  (clicks in screen space → convert to world)
    # ══════════════════════════════════════════════════════════════════════════
    def _on_press(self, event):
        sx, sy = event.x, event.y
        wx, wy = self.zc.s2w(sx, sy)
        self._press_sx, self._press_sy = sx, sy
        self._press_wx, self._press_wy = wx, wy
        self._dragging_box = False
        self._box_cur = None
        t = self.tool.get()

        # ── polar ref pick mode ───────────────────────────────────────────
        if self._picking_ref:
            ni = near_node(self.nodes, wx, wy, thr=18/self.zc.zoom)
            if ni >= 0:
                self._polar_ref_node = ni
                nm_x, nm_y = self._world_to_metres(
                    self.nodes[ni][0], self.nodes[ni][1])
                self.polar_ref_var.set(f'N{ni} ({nm_x:.2f},{nm_y:.2f})')
                self.status_var.set(
                    f'Polar reference set to node {ni}. '
                    f'Enter distance + angle then click "Place node".')
            else:
                self.status_var.set('No node found — click closer to a node.')
            self._picking_ref = False
            return

        # ── ruler click ───────────────────────────────────────────────────
        if self.ruler_active.get():
            gx, gy = self._compute_ghost(wx, wy)
            if self.ruler_start is None:
                self.ruler_start = (gx, gy)
                mx, my = self._world_to_metres(gx, gy)
                self.ruler_label.configure(text='measuring…')
                self.status_var.set(
                    f'Ruler start: ({mx:.3f}, {my:.3f}) m — click end point')
            else:
                rx, ry = self.ruler_start
                dm  = math.hypot((gx-rx)/PX_PER_M, (gy-ry)/PX_PER_M)
                ang = math.degrees(math.atan2(-(gy-ry), gx-rx))
                mx0,my0 = self._world_to_metres(rx, ry)
                mx1,my1 = self._world_to_metres(gx, gy)
                self.ruler_label.configure(
                    text=f'd={dm:.4f} m  α={ang:.2f}°')
                self.status_var.set(
                    f'Ruler: ({mx0:.3f},{my0:.3f}) → ({mx1:.3f},{my1:.3f})'
                    f'  dist={dm:.4f} m  angle={ang:.2f}°')
                self.ruler_start = None   # reset for next measurement
            self._draw()
            return

        # 'node' and 'rod' tools act immediately on press — a drag doesn't
        # make sense for either, so their behaviour is unchanged.
        if t == 'node':
            self.results = None; self.diagrams = None
            self._draw_diagrams_only()
            gx, gy = self._compute_ghost(wx, wy)
            self.nodes.append((gx, gy))
            mx, my = self._world_to_metres(gx, gy)
            self._draw()
            self.status_var.set(
                f'Node {len(self.nodes)-1} placed at ({mx:.3f}, {my:.3f}) m')
            return

        if t == 'rod':
            self.results = None; self.diagrams = None
            self._draw_diagrams_only()
            ni = near_node(self.nodes, wx, wy, 14/self.zc.zoom)
            if ni < 0:
                self.status_var.set('Click on an existing node'); return
            if self.rod_start is None:
                self.rod_start = ni; self._draw()
                nm_x,nm_y = self._world_to_metres(
                    self.nodes[ni][0], self.nodes[ni][1])
                self.status_var.set(
                    f'Rod from node {ni} ({nm_x:.3f},{nm_y:.3f}) m — click second node')
                return
            if self.rod_start == ni:
                self.rod_start = None; self._draw(); return
            dup = any((r['a']==self.rod_start and r['b']==ni) or
                      (r['a']==ni and r['b']==self.rod_start) for r in self.rods)
            if not dup:
                self.rods.append({'a':self.rod_start,'b':ni,
                                  'E':self.mat_E.get(),'A':self.mat_A.get(),
                                  'I':self.mat_I.get(),'conn':'pin','udl':0.0,
                                  'udl_rotation_deg':0.0,
                                  'point_loads':[],
                                  'profile':'Default'})
                na = self.nodes[self.rod_start]; nb = self.nodes[ni]
                L_m = math.hypot(nb[0]-na[0],nb[1]-na[1])/PX_PER_M
                ang = math.degrees(math.atan2(-(nb[1]-na[1]),nb[0]-na[0]))
                self.status_var.set(
                    f'Rod {len(self.rods)-1} added: L={L_m:.4f} m  α={ang:.2f}°')
            self.rod_start = None; self._draw()
            if dup: self.status_var.set('Rod already exists.')
            return

        # 'select', 'load', 'support' → decided in _on_release (click vs box-drag)

    def _on_drag_motion(self, event):
        if self.tool.get() not in ('select','load','support'):
            return
        if self._press_sx is None:
            return
        dx = event.x - self._press_sx; dy = event.y - self._press_sy
        if math.hypot(dx, dy) > 4:
            self._dragging_box = True
        self._box_cur = self.zc.s2w(event.x, event.y)
        self._draw()

    def _on_release(self, event):
        t = self.tool.get()
        if t not in ('select','load','support'):
            self._press_sx = self._press_sy = None
            return
        if self._press_wx is None:
            return
        shift = bool(event.state & 0x0001)   # Shift held → "piece" accumulate

        if self._dragging_box and self._box_cur is not None:
            wx0, wy0 = self._press_wx, self._press_wy
            wx1, wy1 = self._box_cur
            node_ids = set(self._nodes_in_box(wx0, wy0, wx1, wy1))
            if t == 'select':
                rod_ids = set(self._rods_in_box(wx0, wy0, wx1, wy1))
                if shift:
                    self.selected_nodes |= node_ids
                    self.selected_rods  |= rod_ids
                else:
                    self.selected_nodes = node_ids
                    self.selected_rods  = rod_ids
                self.status_var.set(
                    f'Box-selected {len(node_ids)} node(s), {len(rod_ids)} rod(s) '
                    f'[{len(self.selected_nodes)} / {len(self.selected_rods)} total].')
                self._show_sel()
            elif t == 'load':
                self.pending_load = (self.pending_load | node_ids) if shift else node_ids
                self.load_frame['text'] = f'Load on {len(self.pending_load)} node(s)'
                self.sup_frame.pack_forget()
                self.load_frame.pack(fill='x', padx=8, pady=4, before=self.sel_frame)
                self.status_var.set(f'{len(self.pending_load)} node(s) selected for load →')
            elif t == 'support':
                self.pending_sup = (self.pending_sup | node_ids) if shift else node_ids
                self.sup_frame['text'] = f'Support on {len(self.pending_sup)} node(s)'
                self.load_frame.pack_forget()
                self.sup_frame.pack(fill='x', padx=8, pady=4, before=self.sel_frame)
                self.status_var.set(f'{len(self.pending_sup)} node(s) selected for support →')
            self.zc.canvas.focus_set()
        else:
            wx, wy = self._press_wx, self._press_wy
            if t == 'select':
                ni = near_node(self.nodes, wx, wy, 16/self.zc.zoom)
                if ni >= 0:
                    if shift:
                        if ni in self.selected_nodes: self.selected_nodes.discard(ni)
                        else: self.selected_nodes.add(ni)
                    else:
                        self.selected_nodes = {ni}; self.selected_rods = set()
                    self.zc.canvas.focus_set(); self._show_sel(); self._draw()
                    self._press_sx=self._press_sy=None; self._dragging_box=False
                    return
                ri = near_rod(self.nodes, self.rods, wx, wy, 7/self.zc.zoom)
                if ri >= 0:
                    if shift:
                        if ri in self.selected_rods: self.selected_rods.discard(ri)
                        else: self.selected_rods.add(ri)
                    else:
                        self.selected_rods = {ri}; self.selected_nodes = set()
                elif not shift:
                    self.selected_nodes = set(); self.selected_rods = set()
                self.zc.canvas.focus_set(); self._show_sel()

            elif t == 'support':
                ni = near_node(self.nodes, wx, wy, 14/self.zc.zoom)
                if ni < 0:
                    self.status_var.set('Click on a node (or drag a box) to assign support')
                else:
                    self.pending_sup = (self.pending_sup | {ni}) if shift else {ni}
                    self.sup_frame['text'] = f'Support on {len(self.pending_sup)} node(s)'
                    if len(self.pending_sup) == 1:
                        ex = next((s for s in self.supports if s['node']==ni), None)
                        if ex: self.sup_type.set(ex['type'])
                    self.load_frame.pack_forget()
                    self.sup_frame.pack(fill='x', padx=8, pady=4, before=self.sel_frame)
                    self.status_var.set(f'Configure support for {len(self.pending_sup)} node(s) →')

            elif t == 'load':
                ni = near_node(self.nodes, wx, wy, 14/self.zc.zoom)
                if ni < 0:
                    self.status_var.set('Click on a node (or drag a box) to assign load')
                else:
                    self.pending_load = (self.pending_load | {ni}) if shift else {ni}
                    self.load_frame['text'] = f'Load on {len(self.pending_load)} node(s)'
                    if len(self.pending_load) == 1:
                        ex = next((l for l in self.loads if l['node']==ni), None)
                        self.led_fx.set(ex['fx'] if ex else 0.0)
                        self.led_fy.set(ex['fy'] if ex else 10.0)
                    self.sup_frame.pack_forget()
                    self.load_frame.pack(fill='x', padx=8, pady=4, before=self.sel_frame)
                    self.status_var.set(f'Set load for {len(self.pending_load)} node(s) →')

        self._press_sx = self._press_sy = None
        self._dragging_box = False
        self._box_cur = None
        self._draw()

    def _nodes_in_box(self, wx0, wy0, wx1, wy1):
        xlo, xhi = sorted((wx0, wx1)); ylo, yhi = sorted((wy0, wy1))
        return [i for i,(nx,ny) in enumerate(self.nodes)
                if xlo <= nx <= xhi and ylo <= ny <= yhi]

    def _rods_in_box(self, wx0, wy0, wx1, wy1):
        xlo, xhi = sorted((wx0, wx1)); ylo, yhi = sorted((wy0, wy1))
        ids = []
        for i, rod in enumerate(self.rods):
            na, nb = self.nodes[rod['a']], self.nodes[rod['b']]
            if (xlo<=na[0]<=xhi and ylo<=na[1]<=yhi and
                xlo<=nb[0]<=xhi and ylo<=nb[1]<=yhi):
                ids.append(i)
        return ids

    def _on_delete(self, event):
        if not self.selected_nodes and not self.selected_rods: return

        # delete explicitly-selected rods first (by value, not stale index)
        rods_to_remove = [self.rods[ri] for ri in self.selected_rods
                           if 0 <= ri < len(self.rods)]
        for r in rods_to_remove:
            if r in self.rods: self.rods.remove(r)

        # delete nodes, highest index first so remaining indices stay valid
        for ni in sorted(self.selected_nodes, reverse=True):
            self.rods = [r for r in self.rods if r['a']!=ni and r['b']!=ni]
            self.rods = [{**r,'a':r['a']-1 if r['a']>ni else r['a'],
                              'b':r['b']-1 if r['b']>ni else r['b']} for r in self.rods]
            self.loads = [l for l in self.loads if l['node']!=ni]
            self.loads = [{**l,'node':l['node']-1 if l['node']>ni else l['node']}
                          for l in self.loads]
            self.supports = [s for s in self.supports if s['node']!=ni]
            self.supports = [{**s,'node':s['node']-1 if s['node']>ni else s['node']}
                             for s in self.supports]
            self.nodes.pop(ni)

        n_nodes, n_rods = len(self.selected_nodes), len(self.selected_rods)
        self.selected_nodes = set(); self.selected_rods = set()
        # Any node indices staged in the Load/Support panels are now stale
        # (deletion shifts every index above a removed node down by one, and
        # a staged node may have been removed outright) -- carrying them
        # forward could silently apply a load/support to the wrong node, or
        # reference a node index that no longer exists. Safest fix: drop the
        # staged selection and let the user re-pick, which is one click.
        if self.pending_load or self.pending_sup:
            self.pending_load = set(); self.pending_sup = set()
            self.load_frame['text'] = 'Load on 0 node(s)'
            self.sup_frame['text']  = 'Support on 0 node(s)'
            self.load_frame.pack_forget(); self.sup_frame.pack_forget()
        self.results=None; self.diagrams=None
        self._draw_diagrams_only()
        self._show_sel(); self._draw()
        self.status_var.set(f'Deleted {n_nodes} node(s), {n_rods} rod(s).')

    # ══════════════════════════════════════════════════════════════════════════
    #  Load / support panel actions
    # ══════════════════════════════════════════════════════════════════════════
    def _apply_load(self):
        ids = self.pending_load
        if not ids: return
        fx, fy = self.led_fx.get(), self.led_fy.get()
        for ni in ids:
            idx = next((i for i,l in enumerate(self.loads) if l['node']==ni), -1)
            if idx >= 0: self.loads[idx] = {'node':ni,'fx':fx,'fy':fy}
            else:        self.loads.append({'node':ni,'fx':fx,'fy':fy})
        self.results=None; self.diagrams=None; self._draw(); self._draw_diagrams_only()
        self.status_var.set(f'Load applied to {len(ids)} node(s): Fx={fx} Fy={fy} kN')

    def _remove_load(self):
        ids = self.pending_load
        self.loads=[l for l in self.loads if l['node'] not in ids]
        self.results=None; self.diagrams=None; self.load_frame.pack_forget(); self._draw(); self._draw_diagrams_only()

    def _apply_support(self):
        ids = self.pending_sup
        if not ids: return
        stype=self.sup_type.get()
        for ni in ids:
            idx=next((i for i,s in enumerate(self.supports) if s['node']==ni),-1)
            if idx>=0: self.supports[idx]={'node':ni,'type':stype}
            else:      self.supports.append({'node':ni,'type':stype})
        self.results=None; self.diagrams=None; self._draw(); self._draw_diagrams_only()
        self.status_var.set(f'Support "{stype}" applied to {len(ids)} node(s)')

    def _remove_support(self):
        ids = self.pending_sup
        self.supports=[s for s in self.supports if s['node'] not in ids]
        self.results=None; self.diagrams=None; self.sup_frame.pack_forget(); self._draw(); self._draw_diagrams_only()

    # ══════════════════════════════════════════════════════════════════════════
    #  Rod family / profile management
    # ══════════════════════════════════════════════════════════════════════════
    def _refresh_profile_combo(self):
        names = sorted(self.profiles.keys())
        if hasattr(self, 'family_combo'):
            self.family_combo['values'] = names
        if self.active_profile.get() not in names and names:
            self.active_profile.set(names[0])

    def _assign_profile_to_selection(self):
        if not self.selected_rods:
            messagebox.showinfo('Rod family',
                'Select one or more rods first (click, shift-click, or box-select '
                'with the Select tool), then apply a profile.')
            return
        name = self.active_profile.get()
        prof = self.profiles.get(name)
        if not prof:
            messagebox.showwarning('Rod family', f'Profile "{name}" not found.'); return
        for ri in self.selected_rods:
            self.rods[ri]['profile'] = name
            self.rods[ri]['E'] = prof['E']
            self.rods[ri]['A'] = prof['A']
            self.rods[ri]['I'] = prof.get('I', 8000.0)
        self.results = None; self.diagrams = None
        self._draw_diagrams_only()
        self._draw(); self._show_sel()
        self.status_var.set(f'Assigned family "{name}" to {len(self.selected_rods)} rod(s).')

    def _set_connection_type(self, conn):
        if not self.selected_rods:
            messagebox.showinfo('Connection type',
                'Select one or more rods first (click, shift-click, or drag a '
                'selection box), then set Rigid or Pinned.')
            return
        for ri in self.selected_rods:
            self.rods[ri]['conn'] = conn
        self.results = None; self.diagrams = None
        self._draw_diagrams_only()
        self._draw(); self._show_sel()
        label = 'Rigid (moment connection)' if conn == 'rigid' else 'Pinned (axial only)'
        self.status_var.set(f'Set {len(self.selected_rods)} rod(s) to {label}.')

    def _sync_udl_angle(self):
        # Radio buttons are shortcuts; the numeric field/slider remains the
        # authoritative angle so arbitrary rotations can be entered.
        self._draw()

    def _apply_udl(self):
        if not self.selected_rods:
            messagebox.showinfo('Distributed load',
                'Select one or more rods first (click, shift-click, or drag a '
                'selection box), then apply a UDL.')
            return
        w = self.udl_var.get()
        angle = float(self.udl_rotation_var.get())
        n_converted = 0
        for ri in self.selected_rods:
            if self.rods[ri].get('conn') != 'rigid':
                self.rods[ri]['conn'] = 'rigid'
                n_converted += 1
            self.rods[ri]['udl'] = w
            self.rods[ri]['udl_rotation_deg'] = angle
        self.results = None; self.diagrams = None
        self._draw_diagrams_only()
        self._draw(); self._show_sel()
        direction = 'perpendicular to rod' if abs(angle) < 1e-12 else f'rotated {angle:g}° from perpendicular'
        msg = f'Applied {w:g} kN/m ({direction}) to {len(self.selected_rods)} rod(s).'
        if n_converted:
            msg += f' ({n_converted} auto-set to Rigid.)'
        self.status_var.set(msg)

    def _clear_udl(self):
        if not self.selected_rods:
            messagebox.showinfo('Distributed load', 'Select one or more rods first.')
            return
        for ri in self.selected_rods:
            self.rods[ri]['udl'] = 0.0
            self.rods[ri]['udl_rotation_deg'] = 0.0
        self.results = None; self.diagrams = None
        self._draw_diagrams_only()
        self._draw(); self._show_sel()
        self.status_var.set(f'Cleared UDL on {len(self.selected_rods)} rod(s).')

    def _apply_point_load(self):
        if not self.selected_rods:
            messagebox.showinfo('Point load',
                'Select one or more rods first, then add a point load.')
            return
        P = self.pload_var.get()
        pos = self.pload_pos_var.get()
        angle = self.pload_angle_var.get()
        if not (0.0 <= pos <= 100.0):
            messagebox.showerror('Point load', 'Position must be between 0% and 100% from end A.')
            return
        n_converted = 0
        for ri in self.selected_rods:
            if self.rods[ri].get('conn') != 'rigid':
                self.rods[ri]['conn'] = 'rigid'
                n_converted += 1
            self.rods[ri].setdefault('point_loads', []).append({
                'P': P, 't': pos/100.0, 'angle_deg': angle
            })
        self.results = None; self.diagrams = None
        self._draw_diagrams_only()
        self._draw(); self._show_sel()
        msg = f'Added {P:g} kN point load at {pos:g}% from A ({angle:g}°) to {len(self.selected_rods)} rod(s).'
        if n_converted:
            msg += f' ({n_converted} auto-set to Rigid.)'
        self.status_var.set(msg)

    def _clear_point_loads(self):
        if not self.selected_rods:
            messagebox.showinfo('Point load', 'Select one or more rods first.')
            return
        for ri in self.selected_rods:
            self.rods[ri]['point_loads'] = []
        self.results = None; self.diagrams = None
        self._draw_diagrams_only()
        self._draw(); self._show_sel()
        self.status_var.set(f'Cleared point loads on {len(self.selected_rods)} rod(s).')

    def _select_same_family(self):
        if len(self.selected_rods) != 1:
            messagebox.showinfo('Rod family',
                'Select exactly one rod first, then use this to grab the rest of its family.')
            return
        ri = next(iter(self.selected_rods))
        name = self.rods[ri].get('profile', 'Default')
        self.selected_rods = {i for i,r in enumerate(self.rods)
                              if r.get('profile','Default') == name}
        self.selected_nodes = set()
        self._show_sel(); self._draw()
        self.status_var.set(f'Selected {len(self.selected_rods)} rod(s) in family "{name}".')

    def _open_profile_manager(self):
        win = tk.Toplevel(self.root)
        win.title('Profile / Family Manager')
        win.geometry('400x500')
        win.configure(bg='#f5f5f3')
        tk.Label(win, text='Profile / Family Manager', bg='#f5f5f3',
                 font=('Helvetica',12,'bold'), fg='#1a6bbd').pack(pady=(10,4))
        tk.Label(win,
                 text='A "family" is just a named profile (E, A, I) shared by\n'
                      'every rod tagged with it. Editing a profile here updates\n'
                      'every rod currently assigned to it, all at once. I only\n'
                      'matters for rods set to "Rigid".',
                 bg='#f5f5f3', fg='#555', font=('Helvetica',9),
                 justify='center').pack(pady=(0,8))

        listfr = tk.Frame(win, bg='#f5f5f3'); listfr.pack(fill='both', expand=True, padx=10)
        lb = tk.Listbox(listfr, font=('Helvetica',10), height=10)
        lb.pack(side='left', fill='both', expand=True)
        sb = tk.Scrollbar(listfr, orient='vertical', command=lb.yview)
        sb.pack(side='right', fill='y')
        lb.configure(yscrollcommand=sb.set)

        def refresh_list():
            lb.delete(0, 'end')
            for name in sorted(self.profiles.keys()):
                p = self.profiles[name]
                n_members = sum(1 for r in self.rods if r.get('profile','Default')==name)
                lb.insert('end', f'{name}   (E={p["E"]:g}GPa, A={p["A"]:g}cm², '
                                 f'I={p.get("I",8000.0):g}cm⁴, {n_members} rod(s))')
        refresh_list()

        editfr = tk.Frame(win, bg='#f5f5f3'); editfr.pack(fill='x', padx=10, pady=8)
        tk.Label(editfr, text='Name:', bg='#f5f5f3', font=('Helvetica',9)).grid(row=0,column=0,sticky='w')
        name_var = tk.StringVar(value='Default')
        tk.Entry(editfr, textvariable=name_var, width=16, font=('Helvetica',9)).grid(row=0,column=1,padx=4)
        tk.Label(editfr, text='E (GPa):', bg='#f5f5f3', font=('Helvetica',9)).grid(row=1,column=0,sticky='w')
        e_var = tk.DoubleVar(value=200.0)
        tk.Entry(editfr, textvariable=e_var, width=10, font=('Helvetica',9)).grid(row=1,column=1,padx=4)
        tk.Label(editfr, text='A (cm²):', bg='#f5f5f3', font=('Helvetica',9)).grid(row=2,column=0,sticky='w')
        a_var = tk.DoubleVar(value=10.0)
        tk.Entry(editfr, textvariable=a_var, width=10, font=('Helvetica',9)).grid(row=2,column=1,padx=4)
        tk.Label(editfr, text='I (cm⁴, rigid only):', bg='#f5f5f3', font=('Helvetica',9)).grid(row=3,column=0,sticky='w')
        i_var = tk.DoubleVar(value=8000.0)
        tk.Entry(editfr, textvariable=i_var, width=10, font=('Helvetica',9)).grid(row=3,column=1,padx=4)

        def on_select(_e=None):
            sel = lb.curselection()
            if not sel: return
            name = sorted(self.profiles.keys())[sel[0]]
            name_var.set(name)
            e_var.set(self.profiles[name]['E'])
            a_var.set(self.profiles[name]['A'])
            i_var.set(self.profiles[name].get('I', 8000.0))
        lb.bind('<<ListboxSelect>>', on_select)

        def save_profile():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning('Rod family', 'Name cannot be empty.'); return
            self.profiles[name] = {'E': e_var.get(), 'A': a_var.get(), 'I': i_var.get()}
            for r in self.rods:
                if r.get('profile','Default') == name:
                    r['E'] = e_var.get(); r['A'] = a_var.get(); r['I'] = i_var.get()
            self._refresh_profile_combo(); refresh_list()
            self.results = None; self.diagrams = None; self._draw(); self._draw_diagrams_only()
            n = sum(1 for r in self.rods if r.get('profile','Default')==name)
            self.status_var.set(f'Profile "{name}" saved ({n} rod(s) updated).')

        def delete_profile():
            name = name_var.get().strip()
            if name == 'Default':
                messagebox.showwarning('Rod family', 'Cannot delete the Default profile.'); return
            in_use = sum(1 for r in self.rods if r.get('profile','Default')==name)
            if in_use and not messagebox.askyesno('Rod family',
                    f'{in_use} rod(s) use "{name}". Reassign them to Default and delete?'):
                return
            for r in self.rods:
                if r.get('profile','Default') == name:
                    r['profile'] = 'Default'
                    r['E'] = self.profiles['Default']['E']
                    r['A'] = self.profiles['Default']['A']
                    r['I'] = self.profiles['Default'].get('I', 8000.0)
            self.profiles.pop(name, None)
            self._refresh_profile_combo(); refresh_list()
            self.results = None; self.diagrams = None; self._draw(); self._draw_diagrams_only()

        btnfr = tk.Frame(win, bg='#f5f5f3'); btnfr.pack(fill='x', padx=10, pady=4)
        tk.Button(btnfr, text='New / Save profile', bg='#1a6bbd', fg='white',
                  font=('Helvetica',9,'bold'), relief='flat',
                  command=save_profile).pack(side='left', padx=2)
        tk.Button(btnfr, text='Delete profile', relief='flat',
                  font=('Helvetica',9), command=delete_profile).pack(side='left', padx=2)
        tk.Button(win, text='Close', relief='flat', bg='#1a6bbd', fg='white',
                  font=('Helvetica',10,'bold'), command=win.destroy).pack(pady=(4,10))

    # ══════════════════════════════════════════════════════════════════════════
    #  Analysis
    # ══════════════════════════════════════════════════════════════════════════
    def _run_analysis(self):
        if len(self.nodes)<2:
            messagebox.showwarning('Truss','Need ≥ 2 nodes.'); return
        if len(self.rods)<1:
            messagebox.showwarning('Truss','Need ≥ 1 rod.'); return
        if len(self.supports)<1:
            messagebox.showwarning('Truss','Need ≥ 1 support.'); return

        res, err = analyze(self.nodes, self.rods, self.loads, self.supports)
        if err:
            messagebox.showerror('Analysis failed', err)
            self.res_var.set(f'Failed: {err}'); return

        self.results  = res
        self.diagrams = compute_diagrams(self.nodes, self.rods, self.loads, res)

        nr, rr, rxns = res['node_res'], res['rod_res'], res['reactions']
        max_t = max((r['force'] for r in rr), default=0)
        max_c = min((r['force'] for r in rr), default=0)
        max_d = max(math.hypot(r['ux'],r['uy']) for r in nr) if nr else 0

        self.res_var.set(
            f'Max tension:      {max_t:.2f} kN\n'
            f'Max compression:  {abs(max_c):.2f} kN\n'
            f'Max displacement: {max_d:.3f} mm')

        # rod table
        self.rod_res_text.configure(state='normal')
        self.rod_res_text.delete('1.0','end')
        for i, r in enumerate(rr):
            f=r['force']
            k='T' if f>0.01 else ('C' if f<-0.01 else '0')
            if r.get('conn') == 'rigid':
                self.rod_res_text.insert('end',
                    f'Rod {i:2d} [rigid]: N={f:+7.2f} [{k}]  V={r["V"]:+7.2f}  '
                    f'Ma={r["Ma"]:+7.2f}  Mb={r["Mb"]:+7.2f} kN·m\n')
            else:
                self.rod_res_text.insert('end',f'Rod {i:2d}: {f:+8.2f} kN [{k}]\n')
        self.rod_res_text.configure(state='disabled')
        self.rod_res_frame.pack(fill='x', padx=8, pady=4)

        # reaction table
        self.rxn_text.configure(state='normal')
        self.rxn_text.delete('1.0','end')
        for ni, rxn in rxns.items():
            rx = rxn.get('rx', 0); ry = rxn.get('ry', 0)
            if rxn.get('type') == 'fixed':
                self.rxn_text.insert('end',
                    f'Node {ni:2d} (fixed  ): '
                    f'Rx={rx:+7.2f}  Ry={ry:+7.2f}  M={rxn.get("m",0):+7.2f} kN·m\n')
            else:
                self.rxn_text.insert('end',
                    f'Node {ni:2d} ({rxn["type"]:7s}): '
                    f'Rx={rx:+7.2f}  Ry={ry:+7.2f} kN\n')
        self.rxn_text.configure(state='disabled')
        self.rxn_frame.pack(fill='x', padx=8, pady=4)

        self.show_deform.set(True)
        self._draw()
        self._show_diagrams()
        n_t=sum(1 for r in rr if r['force']>0.01)
        n_c=sum(1 for r in rr if r['force']<-0.01)
        self.status_var.set(
            f'Done — {n_t} tension, {n_c} compression. '
            f'Reactions and diagrams shown. Scroll/zoom both canvases freely.')
        if self.selected_nodes or self.selected_rods: self._show_sel()

    # ══════════════════════════════════════════════════════════════════════════
    #  Selection panel
    # ══════════════════════════════════════════════════════════════════════════
    def _show_sel(self):
        t=self.sel_text
        t.configure(state='normal'); t.delete('1.0','end')
        n_sel_nodes = len(self.selected_nodes)
        n_sel_rods  = len(self.selected_rods)

        if n_sel_nodes==0 and n_sel_rods==0:
            t.insert('end','Click a node/rod. Shift-click to\n'
                           'add one at a time ("piece"), or\n'
                           'drag a box to multi-select.')
        elif n_sel_nodes==1 and n_sel_rods==0:
            ni=next(iter(self.selected_nodes)); n=self.nodes[ni]
            sup=next((s for s in self.supports if s['node']==ni),None)
            ld =next((l for l in self.loads    if l['node']==ni),None)
            res=self.results['node_res'][ni] if self.results else None
            rxn=self.results['reactions'].get(ni) if self.results else None
            t.insert('end',f'Node {ni}  ({n[0]//SNAP:.0f}, {-n[1]//SNAP:.0f}) m\n')
            if sup: t.insert('end',f'Support: {sup["type"]}\n')
            if ld:  t.insert('end',f'Load Fx={ld["fx"]} Fy={ld["fy"]} kN\n')
            if rxn:
                if rxn.get('type') == 'fixed':
                    t.insert('end', f'Rx={rxn.get("rx",0):.2f}  Ry={rxn.get("ry",0):.2f}  '
                                    f'M={rxn.get("m",0):.2f} kN·m\n')
                else:
                    t.insert('end', f'Rx={rxn.get("rx",0):.2f}  Ry={rxn.get("ry",0):.2f} kN\n')
            if res: t.insert('end',
                f'\nux={res["ux"]:.3f} mm\nuy={res["uy"]:.3f} mm')
            vecs = self.results['node_vectors'].get(ni) if self.results else None
            if vecs:
                t.insert('end', '\n\nRod forces on this node:\n')
                for v in vecs:
                    t.insert('end',
                        f'  Rod {v["rod"]:>2d} [{v["kind"]}]  '
                        f'|F|={v["magnitude"]:.2f} kN  θ={v["angle_deg"]:.1f}°\n'
                        f'     Fx={v["Fx"]:+.2f}  Fy={v["Fy"]:+.2f} kN\n')
            t.insert('end','\n[Delete] to remove')
        elif n_sel_rods==1 and n_sel_nodes==0:
            ri=next(iter(self.selected_rods)); rod=self.rods[ri]
            na,nb=self.nodes[rod['a']],self.nodes[rod['b']]
            L=math.hypot(nb[0]-na[0],nb[1]-na[1])/PX_PER_M
            res=self.results['rod_res'][ri] if self.results else None
            conn = rod.get('conn','pin')
            t.insert('end',f'Rod {ri}  ({rod["a"]} → {rod["b"]})\n')
            t.insert('end',f'L={L:.2f}m  family="{rod.get("profile","Default")}"\n')
            t.insert('end',f'Connection: {"Rigid (moment)" if conn=="rigid" else "Pinned (axial)"}\n')
            if conn == 'rigid':
                t.insert('end',f'(E={rod["E"]}GPa A={rod["A"]}cm² I={rod.get("I",8000.0)}cm⁴)\n')
                if rod.get('udl', 0.0):
                    rot = rod.get('udl_rotation_deg', 0.0)
                    if abs(rot) < 1e-12:
                        t.insert('end', f'UDL = {rod["udl"]:g} kN/m (⊥ rod)\n')
                    else:
                        t.insert('end', f'UDL = {rod["udl"]:g} kN/m (rot. {rot:g}° from ⊥)\n')
                for pi, pl in enumerate(rod.get('point_loads', []), 1):
                    t.insert('end', f'Point load {pi}: {pl.get("P",0):g} kN @ {pl.get("t",0.5)*100:g}% / {pl.get("angle_deg",90):g}°\n')
            else:
                t.insert('end',f'(E={rod["E"]}GPa A={rod["A"]}cm² assumed)\n')
            if res:
                f=res['force']
                kind='Tension' if f>0.01 else('Compression' if f<-0.01 else 'Zero')
                t.insert('end',f'\nAxial force N = {f:+.2f} kN [{kind}]')
                if conn == 'rigid':
                    t.insert('end', f'\nShear V = {res["V"]:+.2f} kN'
                                    f'\nMoment Ma = {res["Ma"]:+.2f} kN·m'
                                    f'\nMoment Mb = {res["Mb"]:+.2f} kN·m')
            t.insert('end','\n\n[Delete] to remove')
        else:
            t.insert('end', f'{n_sel_nodes} node(s), {n_sel_rods} rod(s) selected.\n')
            if n_sel_rods:
                fams = {self.rods[ri].get('profile','Default') for ri in self.selected_rods}
                t.insert('end', f'Families: {", ".join(sorted(fams))}\n')
                conns = {self.rods[ri].get('conn','pin') for ri in self.selected_rods}
                t.insert('end', f'Connections: {", ".join(sorted(conns))}\n')
                t.insert('end', '\nUse "Rod family / profile" or\n'
                                '"Connection type" below to bulk-\n'
                                'assign to these rods.')
            t.insert('end', '\n\n[Delete] to remove all selected')
        t.configure(state='disabled')

    # ══════════════════════════════════════════════════════════════════════════
    #  Drawing — truss canvas  (everything in WORLD coords → w2s before draw)
    # ══════════════════════════════════════════════════════════════════════════
    def _draw_adaptive_grid(self, c, w2s, z, W, H):
        """Adaptive / level-of-detail grid, AutoCAD-style:
          - MAJOR lines at a "nice" (1-2-5-10-20-50-...) world spacing,
            re-chosen every redraw so their on-screen spacing stays close to
            a fixed target regardless of zoom (no clutter when zoomed out,
            no overly-sparse grid when zoomed in).
          - Below that, one or two recursively finer levels of grid POINTS
            (not full lines, to avoid visual clutter) fade in once their
            on-screen spacing would actually be legible -- so as you zoom
            in, smaller subdivisions of the grid unit progressively appear,
            exactly like AutoCAD's adaptive grid.
        """
        base_px = SNAP   # 1 world metre, in px at zoom=1
        sx0, sy0 = w2s(0, 0)

        major_step, major_mult = _nice_grid_step(base_px, z, target_px=55)

        # ── major grid lines ──
        step_px = major_step * z
        ox = sx0 % step_px
        if ox < 0: ox += step_px
        x = ox
        while x < W:
            c.create_line(x, 0, x, H, fill=CG, width=0.5)
            x += step_px
        oy = sy0 % step_px
        if oy < 0: oy += step_px
        y = oy
        while y < H:
            c.create_line(0, y, W, y, fill=CG, width=0.5)
            y += step_px

        # ── recursively finer grid POINTS (dots), fading in level by level ──
        level_style = [(CG_MINOR, 1.1), (CG_MICRO, 0.8)]
        cur_step, cur_mult = major_step, major_mult
        for color, r in level_style:
            sub = _grid_subdiv_of(cur_mult)
            next_step = cur_step / sub
            next_px = next_step * z
            if next_px < 10:
                break   # not legible yet at this zoom -- stop subdividing
            n_est = (W / next_px + 2) * (H / next_px + 2)
            if n_est > 20000:
                break   # defensive cap, shouldn't normally trigger
            oxp = sx0 % next_px
            if oxp < 0: oxp += next_px
            oyp = sy0 % next_px
            if oyp < 0: oyp += next_px
            xp = oxp
            while xp < W:
                yp = oyp
                while yp < H:
                    c.create_oval(xp - r, yp - r, xp + r, yp + r, fill=color, outline='')
                    yp += next_px
                xp += next_px
            cur_step, cur_mult = next_step, next_step / base_px

    def _draw(self):
        if hasattr(self, 'analyze_btn'):
            self.analyze_btn.configure(
                bg='#1a6bbd' if self.results is not None else '#9e9e9e',
                state='normal')   # always clickable — grey just means "not solved yet"
        c  = self.zc.canvas
        w2s = self.zc.w2s
        z  = self.zc.zoom
        c.delete('all')
        W  = c.winfo_width()  or INIT_CW
        H  = c.winfo_height() or INIT_CH

        # adaptive / level-of-detail grid: "nice" (1-2-5) major spacing that
        # re-normalizes to stay legible at any zoom, plus recursively finer
        # grid-point subdivisions that fade in as you zoom in (AutoCAD-style)
        self._draw_adaptive_grid(c, w2s, z, W, H)

        show_def  = self.show_deform.get() and self.results is not None
        def_scale = self.def_scale.get()

        if show_def:
            nr = self.results['node_res']
            rod_res = self.results['rod_res']
            curves = deformed_shape_points(self.nodes, self.rods, nr, rod_res, def_scale)
            for pts in curves:
                flat = []
                for (px, py) in pts:
                    sx, sy = w2s(px, py)
                    flat.extend([sx, sy])
                if len(pts) > 2:
                    c.create_line(*flat, fill=CD, width=2.5, smooth=True)
                else:
                    c.create_line(*flat, fill=CD, width=2.5, dash=(6,4))

            # Points of contraflexure (M=0): drawn on the true deformed
            # curve, from the same M(x) the diagram pane already computed,
            # so a marker here always matches the sign-change point shown
            # in the moment diagram.
            if self.show_contraflexure.get() and self.diagrams:
                for i, rod in enumerate(self.rods):
                    if rod.get('conn') != 'rigid' or i >= len(self.diagrams):
                        continue
                    diag = self.diagrams[i]
                    Lm = diag.get('Lm', 0.0)
                    if Lm <= 0:
                        continue
                    xs_cross = find_zero_crossings(diag['xs'], diag['M'])
                    na, nb = self.nodes[rod['a']], self.nodes[rod['b']]
                    ra, rb = nr[rod['a']], nr[rod['b']]
                    rr = rod_res[i] if i < len(rod_res) else None
                    for xc in xs_cross:
                        t = max(0.0, min(1.0, xc / Lm))
                        # Skip the very ends -- a crossing at t=0 or t=1
                        # means the moment is zero AT the joint (e.g. a
                        # pinned-looking end of a cantilever), not a true
                        # reversal of curvature along the span.
                        if t < 0.02 or t > 0.98:
                            continue
                        wx, wy = deformed_point_at(na, nb, ra, rb, rr, def_scale, t)
                        sx, sy = w2s(wx, wy)
                        c.create_oval(sx-4, sy-4, sx+4, sy+4,
                                     fill='white', outline=CD, width=2)

            for i,(nx,ny) in enumerate(self.nodes):
                r=nr[i]
                dx=r['ux']/1000*PX_PER_M*def_scale
                dy=r['uy']/1000*PX_PER_M*def_scale
                if math.hypot(dx,dy)>0.3:
                    sx0,sy0=w2s(nx,ny); sx1,sy1=w2s(nx+dx,ny+dy)
                    c.create_line(sx0,sy0,sx1,sy1,fill=CD,width=1,dash=(2,2))
                    c.create_oval(sx1-4,sy1-4,sx1+4,sy1+4,fill=CD,outline='')

        # rods
        for i, rod in enumerate(self.rods):
            na,nb = self.nodes[rod['a']],self.nodes[rod['b']]
            res   = self.results['rod_res'][i] if self.results else None
            color = CZ; lw = 2.5
            if res:
                f=res['force']
                if   f> 0.01: color=CT; lw=2+min(5,abs(f)/8)
                elif f<-0.01: color=CC; lw=2+min(5,abs(f)/8)
            sx0,sy0=w2s(na[0],na[1]); sx1,sy1=w2s(nb[0],nb[1])
            c.create_line(sx0,sy0,sx1,sy1,fill=color,width=lw)

            if rod.get('conn') == 'rigid':
                ddx0=sx1-sx0; ddy0=sy1-sy0
                Lr0=math.hypot(ddx0,ddy0) or 1
                ux0,uy0=ddx0/Lr0,ddy0/Lr0
                px0,py0=-uy0,ux0
                tick=7
                for (tx,ty) in [(sx0+ux0*14,sy0+uy0*14), (sx1-ux0*14,sy1-uy0*14)]:
                    c.create_line(tx-px0*tick,ty-py0*tick,tx+px0*tick,ty+py0*tick,
                                  fill='#333333',width=2)

            if rod.get('udl', 0.0):
                n_arrows = max(3, int(math.hypot(sx1-sx0, sy1-sy0)//30))
                ddx, ddy = sx1-sx0, sy1-sy0
                Ld = math.hypot(ddx, ddy) or 1.0
                ux_d, uy_d = ddx/Ld, ddy/Ld
                nx_d, ny_d = -uy_d, ux_d
                rot = math.radians(float(rod.get('udl_rotation_deg', 0.0)))
                dux = ux_d*math.sin(rot) + nx_d*math.cos(rot)
                duy = uy_d*math.sin(rot) + ny_d*math.cos(rot)
                for k in range(n_arrows+1):
                    t = k/n_arrows
                    axp, ayp = sx0+(sx1-sx0)*t, sy0+(sy1-sy0)*t
                    c.create_line(axp-dux*16, ayp-duy*16, axp, ayp,
                                  fill='#D85A30', width=1.5, arrow='last',
                                  arrowshape=(5,6,2))
                rot = float(rod.get('udl_rotation_deg', 0.0))
                label = (f"{rod['udl']:g} kN/m ⟂" if abs(rot) < 1e-12
                         else f"{rod['udl']:g} kN/m  rot {rot:g}°")
                c.create_text((sx0+sx1)/2, (sy0+sy1)/2-20,
                             text=label, fill='#D85A30',
                             font=('Helvetica',8,'bold'))

            # Point loads on rigid rods
            for pl in rod.get('point_loads', []):
                t = max(0.0, min(1.0, float(pl.get('t', 0.5))))
                qx = sx0 + (sx1-sx0)*t
                qy = sy0 + (sy1-sy0)*t
                ang = math.radians(float(pl.get('angle_deg', 90.0)))
                pux, puy = math.cos(ang), math.sin(ang)
                c.create_line(qx-pux*22, qy-puy*22, qx, qy,
                              fill='#7A3E9D', width=2, arrow='last',
                              arrowshape=(6,7,2))
                c.create_text(qx+pux*28, qy+puy*28,
                              text=f"{pl.get('P',0):g} kN",
                              fill='#7A3E9D', font=('Helvetica',8,'bold'))

            if self.selected_rods and i in self.selected_rods:
                c.create_line(sx0,sy0,sx1,sy1,fill=CS,width=4,dash=(5,3))

            # rod number — constant screen size regardless of zoom
            mx=(sx0+sx1)/2; my=(sy0+sy1)/2
            ddx=sx1-sx0; ddy=sy1-sy0
            Lr=math.hypot(ddx,ddy) or 1
            px,py=-ddy/Lr,ddx/Lr
            off=11
            c.create_text(mx+px*off,my+py*off,text=str(i),fill='white',
                           font=('Helvetica',9,'bold'))
            c.create_text(mx+px*off,my+py*off,text=str(i),
                           fill=color if color!=CZ else '#555',
                           font=('Helvetica',8,'bold'))

        # supports
        for s in self.supports:
            n=self.nodes[s['node']]; sx,sy=w2s(n[0],n[1])
            self._draw_support(c,sx,sy,s['type'],z)

        # reaction arrows
        if self.results:
            for ni, rxn in self.results['reactions'].items():
                n=self.nodes[ni]; sx,sy=w2s(n[0],n[1])
                self._draw_reaction(c,sx,sy,rxn.get('rx',0),rxn.get('ry',0),z)

        # load arrows
        for ld in self.loads:
            n=self.nodes[ld['node']]; sx,sy=w2s(n[0],n[1])
            self._draw_load(c,sx,sy,ld['fx'],ld['fy'],z)

        # nodes
        for i,(nx,ny) in enumerate(self.nodes):
            sx,sy=w2s(nx,ny)
            is_sel   = i in self.selected_nodes
            is_start = self.rod_start==i
            is_pload = i in self.pending_load and self.tool.get()=='load'
            is_psup  = i in self.pending_sup  and self.tool.get()=='support'
            r    = 9 if (is_sel or is_start) else 6      # constant on-screen size
            fill = CS if (is_sel or is_start) else CN
            c.create_oval(sx-r,sy-r,sx+r,sy+r,fill=fill,outline='#aaa',width=1)
            c.create_text(sx,sy-r-4,text=str(i),fill='#555',
                           font=('Helvetica',9))
            if is_pload:
                c.create_oval(sx-13,sy-13,sx+13,sy+13,outline=CL,width=2,dash=(3,2))
            if is_psup:
                c.create_oval(sx-13,sy-13,sx+13,sy+13,outline='#7F77DD',width=2,dash=(3,2))
            if (self.show_node_moments.get() and self.results is not None
                    and 'node_moments' in self.results):
                # Shows the largest INDIVIDUAL rod moment at this joint, not
                # the net sum -- the net is guaranteed to read ~0 at any
                # free joint by pure equilibrium (see compute_node_moments),
                # which would make this toggle look broken at exactly the
                # joints carrying real Vierendeel moment.
                mdata = self.results['node_moments'].get(i, {'max_abs': 0.0, 'max_signed': 0.0})
                m = mdata.get('max_signed', 0.0)
                if abs(m) > 0.05:
                    # Same circular-arrow glyph used everywhere else a node
                    # moment is shown (Node Force Vectors / Rod Calculations
                    # reports) -- CCW for a positive moment, CW for negative,
                    # so every depiction in the app agrees on which way a
                    # given moment actually curls.
                    arc_r = r + 9
                    self._draw_moment_arc(c, sx, sy, arc_r, m, color=CMOM,
                                          width=2, start_angle=20, extent_mag=250,
                                          head_len=6)
                    c.create_text(sx+arc_r+4, sy+arc_r+2, text=f'M={m:+.1f}',
                                 fill=CMOM, font=('Helvetica',8,'bold'), anchor='w')

        if self.rod_start is not None:
            nx,ny=self.nodes[self.rod_start]; sx,sy=w2s(nx,ny)
            c.create_oval(sx-14,sy-14,sx+14,sy+14,outline=CS,width=2,dash=(4,3))

        # ── ghost node preview ───────────────────────────────────────────────
        t_now = self.tool.get()
        gx, gy = self._ghost_wx, self._ghost_wy
        if gx is not None and t_now in ('node', 'rod'):
            gsx, gsy = w2s(gx, gy)
            # ghost circle — constant on-screen size regardless of zoom
            r_g = 7
            c.create_oval(gsx-r_g, gsy-r_g, gsx+r_g, gsy+r_g,
                           outline='#1a6bbd', fill='', width=1.5, dash=(3,2))
            # coordinates callout
            gmx, gmy = self._world_to_metres(gx, gy)
            c.create_text(gsx+r_g+4, gsy,
                           text=f'({gmx:.3f}, {gmy:.3f})',
                           fill='#1a6bbd', font=('Helvetica',8),
                           anchor='w')
            # if drawing a rod, show live distance + angle line
            if t_now == 'rod' and self.rod_start is not None:
                ref = self.nodes[self.rod_start]
                rsx, rsy = w2s(ref[0], ref[1])
                c.create_line(rsx, rsy, gsx, gsy,
                               fill='#1a6bbd', width=1.5, dash=(6,3))
                L_m = math.hypot(gx-ref[0], gy-ref[1]) / PX_PER_M
                ang = math.degrees(math.atan2(-(gy-ref[1]), gx-ref[0]))
                mid_sx = (rsx+gsx)/2; mid_sy = (rsy+gsy)/2
                c.create_text(mid_sx, mid_sy-12,
                               text=f'L={L_m:.3f}m  α={ang:.1f}°',
                               fill='#1a6bbd',
                               font=('Helvetica',max(7,int(9*z)),'bold'))

        # ── angle snap rays ──────────────────────────────────────────────────
        if (self.snap_angle.get() and self.rod_start is not None
                and t_now == 'rod'):
            ref = self.nodes[self.rod_start]
            rsx, rsy = w2s(ref[0], ref[1])
            deg_step = self.snap_angle_deg.get()
            ray_len  = max(c.winfo_width(), c.winfo_height()) * 2
            for a_deg in range(0, 360, deg_step):
                rad  = math.radians(a_deg)
                ex   = rsx + ray_len * math.cos(rad)
                ey   = rsy - ray_len * math.sin(rad)
                c.create_line(rsx, rsy, ex, ey,
                               fill='#c8d8f0', width=0.5, dash=(4,6))
                # label every step
                lx = rsx + 44*z * math.cos(rad)
                ly = rsy - 44*z * math.sin(rad)
                c.create_text(lx, ly, text=f'{a_deg}°',
                               fill='#9ab', font=('Helvetica', max(6,int(7*z))))

        # ── ruler overlay ────────────────────────────────────────────────────
        if self.ruler_active.get() and self.ruler_start is not None:
            rs = self.ruler_start
            rsx0, rsy0 = w2s(rs[0], rs[1])
            if gx is not None:
                rsx1, rsy1 = w2s(gx, gy)
            else:
                rsx1, rsy1 = w2s(self._mouse_wx, self._mouse_wy)
            # main ruler line
            c.create_line(rsx0, rsy0, rsx1, rsy1,
                           fill='#c0392b', width=2*z, dash=(8,4))
            # end ticks
            for ex, ey in [(rsx0,rsy0),(rsx1,rsy1)]:
                c.create_line(ex, ey-8*z, ex, ey+8*z,
                               fill='#c0392b', width=2)
            # start dot
            c.create_oval(rsx0-4,rsy0-4,rsx0+4,rsy0+4, fill='#c0392b', outline='')
            # measurement label on line
            if gx is not None:
                dm  = math.hypot((gx-rs[0])/PX_PER_M, (gy-rs[1])/PX_PER_M)
                ang = math.degrees(math.atan2(-(gy-rs[1]), gx-rs[0]))
                mx0, my0 = self._world_to_metres(rs[0], rs[1])
                mx1, my1 = self._world_to_metres(gx, gy)
                lbl = f'd={dm:.4f} m  α={ang:.2f}°'
                msx = (rsx0+rsx1)/2; msy = (rsy0+rsy1)/2
                # white halo
                c.create_text(msx, msy-14, text=lbl, fill='white',
                               font=('Helvetica',max(8,int(10*z)),'bold'))
                c.create_text(msx, msy-14, text=lbl, fill='#c0392b',
                               font=('Helvetica',max(8,int(10*z)),'bold'))
            # origin crosshair
            ch = 10*z
            c.create_line(rsx0-ch,rsy0,rsx0+ch,rsy0, fill='#c0392b',width=1)
            c.create_line(rsx0,rsy0-ch,rsx0,rsy0+ch, fill='#c0392b',width=1)

        # ── protractor overlay (shown when angle-snap is on, no rod drawing) ─
        if (self.snap_angle.get() and t_now == 'node'
                and gx is not None and self.nodes):
            # draw a small protractor arc around the ghost node
            gsx2, gsy2 = w2s(gx, gy)
            R = max(30, int(40*z))
            deg_step = self.snap_angle_deg.get()
            c.create_oval(gsx2-R, gsy2-R, gsx2+R, gsy2+R,
                           outline='#aad', width=0.8, dash=(2,4))
            for a_deg in range(0, 360, deg_step):
                rad  = math.radians(a_deg)
                tx   = gsx2 + (R+8) * math.cos(rad)
                ty   = gsy2 - (R+8) * math.sin(rad)
                c.create_text(tx, ty, text=f'{a_deg}°',
                               fill='#99a',
                               font=('Helvetica', max(5, int(6*z))))

        # zoom hint
        c.create_text(6,6,anchor='nw',
                       text=f'zoom {self.zc.zoom:.2f}×  |  scroll=zoom  mid-drag=pan',
                       fill='#aaa',font=('Helvetica',8))

    def _draw_support(self, c, x, y, stype, z=1):
        sc=1.0   # constant on-screen size regardless of zoom
        pts=[x,y, x-14*sc,y+22*sc, x+14*sc,y+22*sc]
        c.create_polygon(pts,fill='#cccccc',outline=CSP,width=1.5*sc)
        c.create_line(x-18*sc,y+22*sc,x+18*sc,y+22*sc,fill=CSP,width=1.5*sc)
        if stype=='pin':
            for k in range(-3,4):
                c.create_line(x+k*5*sc,y+22*sc,x+k*5*sc-4*sc,y+29*sc,
                               fill=CSP,width=1.5*sc)
        elif stype=='rollerX':
            c.create_oval(x-11*sc,y+23*sc,x-4*sc,y+30*sc,outline=CSP,width=1.5*sc)
            c.create_oval(x+4*sc,y+23*sc,x+11*sc,y+30*sc,outline=CSP,width=1.5*sc)
            c.create_line(x-18*sc,y+31*sc,x+18*sc,y+31*sc,fill=CSP,width=1.5*sc)
        else:
            c.create_oval(x-4*sc,y+23*sc,x+4*sc,y+30*sc,outline=CSP,width=1.5*sc)
            c.create_line(x-18*sc,y+31*sc,x+18*sc,y+31*sc,fill=CSP,width=1.5*sc)
        c.create_text(x,y+36*sc,text=stype,fill='#777',font=('Helvetica',8))

    def _draw_load(self, c, x, y, fx, fy, z=1):
        mag=math.hypot(fx,fy)
        if mag<0.001: return
        sc=1.0   # constant on-screen size regardless of zoom
        nx_,ny_=fx/mag,fy/mag
        ox,oy=x-nx_*44*sc,y-ny_*44*sc
        c.create_line(ox,oy,x,y,fill=CL,width=2*sc,arrow='last',
                       arrowshape=(10*sc,12*sc,4*sc))
        c.create_text(ox-ny_*14*sc,oy+nx_*14*sc,
                       text=f'{mag:.1f}kN',fill=CL,
                       font=('Helvetica',9,'bold'))

    def _draw_reaction(self, c, x, y, rx, ry, z=1):
        """Green arrows pointing away from the support node."""
        sc=1.0   # constant on-screen size regardless of zoom
        mag=math.hypot(rx,ry)
        if mag<0.01: return
        nx_=rx/mag; ny_=ry/mag
        # arrow points outward (reaction direction)
        ex,ey=x+nx_*44*sc,y+ny_*44*sc
        c.create_line(x,y,ex,ey,fill=CR,width=2*sc,arrow='last',
                       arrowshape=(10*sc,12*sc,4*sc),dash=(4,2))
        lx=ex+ny_*14*sc; ly=ey-nx_*14*sc
        c.create_text(lx,ly,text=f'R={mag:.1f}kN',fill=CR,
                       font=('Helvetica',8,'bold'))

    # ══════════════════════════════════════════════════════════════════════════
    #  Diagram canvas
    # ══════════════════════════════════════════════════════════════════════════
    def _show_diagrams(self):
        self.diag_outer.pack(fill='x', padx=6, pady=(2,0),
                             before=self.root.winfo_children()[-1])
        self._draw_diagrams_only()

    def _draw_vierendeel_diagram(self):
        """Draws two silhouettes of the actual structure side by side: shear
        (red) on the left, bending moment (blue) on the right -- following
        the classic Vierendeel-girder diagram convention. Each rigid rod is
        sampled at several points along its own length so a UDL's linear
        shear / parabolic moment variation renders correctly (not just the
        two end values) -- and the global maximum |V| and |M|, including
        every tied location, are marked directly on the diagram. Pin rods
        are pure axial (no V/M), so only rigid rods get a diagram overlay,
        though every rod still gets its outline drawn."""
        dc = self.diag_zc.canvas
        dc.delete('all')
        DW = dc.winfo_width() or INIT_CW
        DH = dc.winfo_height() or INIT_DH

        if not self.results or not self.nodes:
            dc.create_text(DW/2, DH/2, text='Run ▶ Analyze first', fill='#999',
                           font=('Helvetica', 11))
            return

        rod_res = self.results['rod_res']
        xs = [n[0] for n in self.nodes]; ys = [n[1] for n in self.nodes]
        xmin, xmax = min(xs), max(xs); ymin, ymax = min(ys), max(ys)
        span_w = max(xmax-xmin, 1); span_h = max(ymax-ymin, 1)

        pad = 40
        half_w = DW/2
        avail_w = max(half_w - 2*pad, 10)
        avail_h = max(DH - 2*pad - 30, 10)
        scale_geo = min(avail_w/span_w, avail_h/span_h)

        # Zoom/pan: this view uses the SAME ZoomCanvas mouse-wheel-zoom /
        # middle-drag-pan already wired up for the main canvas and the
        # ordinary "Truss diagrams" panel -- it was just never actually
        # wired into this diagram's own transform before, so scrolling had
        # no visible effect here even though the zoom value was updating.
        # Fix: treat the auto-fit layout below as the "world" coordinates
        # fed into diag_zc's own w2s(), exactly like the per-rod panel view
        # already does for its own (differently-shaped) layout space. At
        # zoom=1.0, pan=(0,0) -- diag_zc's default state -- this reduces
        # EXACTLY to the previous fixed auto-fit rendering.
        zc_w2s = self.diag_zc.w2s
        z = self.diag_zc.zoom

        def make_T(origin_x):
            def T(wx, wy):
                return zc_w2s(origin_x + pad + (wx-xmin)*scale_geo,
                              pad + 30 + (wy-ymin)*scale_geo)
            return T
        T_left, T_right = make_T(0), make_T(half_w)

        dc.create_text(half_w/2, 14, text='SHEAR V (kN)', fill='#c0392b',
                      font=('Helvetica', 11, 'bold'))
        dc.create_text(half_w + half_w/2, 14, text='MOMENT M (kN·m)', fill='#2c5f9e',
                      font=('Helvetica', 11, 'bold'))
        dc.create_line(half_w, 0, half_w, DH, fill='#ccc')

        NSAMP = 13   # samples per rod along its own length
        def sample_rod(res):
            """Returns (v_samples, m_samples), each a list of (frac_0_1, value).
            Point-load positions are inserted with left/right samples so the
            shear jump is visible without changing the continuous UDL curve.
            """
            Lm, wt, V1, Ma = res['length_m'], res.get('w_t', 0.0), res['V'], res['Ma']
            pts = res.get('point_loads_local', [])
            fracs = [k/(NSAMP-1) for k in range(NSAMP)]
            for pl in pts:
                t = max(0.0, min(1.0, pl.get('t', 0.5)))
                eps = 1e-6
                fracs.extend([max(0.0, t-eps), t, min(1.0, t+eps)])
            # Exact M extrema occur where the piecewise-linear shear is zero.
            # Add those stations so the Vierendeel overlay's maximum is not
            # limited by its visual sampling density.
            if abs(wt) > 1e-12:
                breaks = [0.0] + sorted(
                    max(0.0, min(1.0, pl.get('t', 0.5))) for pl in pts
                ) + [1.0]
                for left, right in zip(breaks, breaks[1:]):
                    p_before = sum(pl.get('pt', 0.0) for pl in pts
                                   if pl.get('t', 0.5) <= left + 1e-10)
                    x_zero_v = (V1 - p_before) / wt
                    frac_zero_v = x_zero_v / Lm if Lm else 0.0
                    if left + 1e-10 < frac_zero_v < right - 1e-10:
                        fracs.append(frac_zero_v)
            fracs = sorted(set(fracs))
            vs, ms = [], []
            for frac in fracs:
                x = Lm * frac
                shear = V1 - wt*x
                moment = Ma + V1*x - wt*x**2/2
                for pl in pts:
                    t = max(0.0, min(1.0, pl.get('t', 0.5)))
                    a = Lm * t
                    pt = pl.get('pt', 0.0)
                    if frac >= t:
                        shear -= pt
                        moment -= pt*(x-a)
                vs.append((frac, shear))
                ms.append((frac, moment))
            return vs, ms

        rigid_items = [(rod, res, *sample_rod(res)) for rod, res in zip(self.rods, rod_res)
                       if res.get('conn') == 'rigid']

        max_V = max((max(abs(v) for _, v in vs) for _, _, vs, _ in rigid_items), default=1) or 1
        max_M = max((max(abs(m) for _, m in ms) for _, _, _, ms in rigid_items), default=1) or 1
        max_offset = min(avail_w, avail_h) * 0.16
        amp_V = max_offset / max_V * z
        amp_M = max_offset / max_M * z

        for T in (T_left, T_right):
            for rod in self.rods:
                na, nb = self.nodes[rod['a']], self.nodes[rod['b']]
                pa, pb = T(na[0], na[1]), T(nb[0], nb[1])
                dc.create_line(*pa, *pb, fill='#999', width=2)
            for n in self.nodes:
                px, py = T(n[0], n[1])
                dc.create_oval(px-3, py-3, px+3, py+3, fill='#555', outline='')

        def draw_band(pa, pb, nx, ny, samples, amp, fill, outline):
            segs, cur = [], [samples[0]]
            for i in range(1, len(samples)):
                f0, v0 = samples[i-1]; f1, v1 = samples[i]
                if v0*v1 < 0:
                    fc = f0 + (f1-f0)*(-v0)/(v1-v0)
                    cur.append((fc, 0.0)); segs.append(cur); cur = [(fc, 0.0)]
                cur.append((f1, v1))
            segs.append(cur)
            for seg in segs:
                if len(seg) < 2: continue
                base_pts = [(pa[0]+(pb[0]-pa[0])*f, pa[1]+(pb[1]-pa[1])*f) for f, _ in seg]
                off_pts = [(px+nx*v*amp, py+ny*v*amp) for (px, py), (_, v) in zip(base_pts, seg)]
                poly = base_pts + off_pts[::-1]
                dc.create_polygon(*[c for p in poly for c in p], fill=fill, outline=outline, width=1)

        for rod, res, vs, ms in rigid_items:
            na, nb = self.nodes[rod['a']], self.nodes[rod['b']]
            dx, dy = nb[0]-na[0], nb[1]-na[1]
            Lr = math.hypot(dx, dy) or 1
            nx, ny = -dy/Lr, dx/Lr

            paL, pbL = T_left(na[0], na[1]), T_left(nb[0], nb[1])
            draw_band(paL, pbL, nx, ny, vs, amp_V, '#e8a49c', '#c0392b')
            mxv, myv = (paL[0]+pbL[0])/2, (paL[1]+pbL[1])/2
            dc.create_text(mxv, myv, text=f'{res["V"]:.1f}', font=('Helvetica',7), fill='#c0392b')

            paR, pbR = T_right(na[0], na[1]), T_right(nb[0], nb[1])
            draw_band(paR, pbR, nx, ny, ms, amp_M, '#9fc0e0', '#2c5f9e')
            oxA, oyA = nx*res['Ma']*amp_M, ny*res['Ma']*amp_M
            oxB, oyB = nx*res['Mb']*amp_M, ny*res['Mb']*amp_M
            dc.create_text(paR[0]+oxA*1.2, paR[1]+oyA*1.2, text=f'{res["Ma"]:.1f}',
                          font=('Helvetica',7), fill='#2c5f9e')
            dc.create_text(pbR[0]+oxB*1.2, pbR[1]+oyB*1.2, text=f'{res["Mb"]:.1f}',
                          font=('Helvetica',7), fill='#2c5f9e')

        # ── mark the global maximum |V| and |M|, including every tied location ──
        if rigid_items:
            tol = 1e-3
            v_hits, m_hits = [], []
            for ridx, (rod, res, vs, ms) in enumerate(rigid_items):
                v_abs_max = max(abs(v) for _, v in vs)
                if v_abs_max >= max_V - tol*max_V - 1e-9:
                    f, v = max(vs, key=lambda fv: abs(fv[1]))
                    v_hits.append((ridx, f, v))
                m_abs_max = max(abs(m) for _, m in ms)
                if m_abs_max >= max_M - tol*max_M - 1e-9:
                    f, m = max(ms, key=lambda fm: abs(fm[1]))
                    m_hits.append((ridx, f, m))

            for ridx, f, v in v_hits:
                rod = rigid_items[ridx][0]
                na, nb = self.nodes[rod['a']], self.nodes[rod['b']]
                wx, wy = na[0]+(nb[0]-na[0])*f, na[1]+(nb[1]-na[1])*f
                sx, sy = T_left(wx, wy)
                dc.create_oval(sx-5, sy-5, sx+5, sy+5, fill='white', outline='#c0392b', width=2)
            for ridx, f, m in m_hits:
                rod = rigid_items[ridx][0]
                na, nb = self.nodes[rod['a']], self.nodes[rod['b']]
                wx, wy = na[0]+(nb[0]-na[0])*f, na[1]+(nb[1]-na[1])*f
                sx, sy = T_right(wx, wy)
                dc.create_oval(sx-5, sy-5, sx+5, sy+5, fill='white', outline='#2c5f9e', width=2)

            dc.create_text(half_w/2, DH-10, text=f'max |V| = {max_V:.2f} kN'
                           + (f'  ({len(v_hits)} locations)' if len(v_hits) > 1 else ''),
                           fill='#c0392b', font=('Helvetica', 9, 'bold'))
            dc.create_text(half_w+half_w/2, DH-10, text=f'max |M| = {max_M:.2f} kN·m'
                           + (f'  ({len(m_hits)} locations)' if len(m_hits) > 1 else ''),
                           fill='#2c5f9e', font=('Helvetica', 9, 'bold'))
        else:
            dc.create_text(DW/2, DH-14,
                          text='No rigid rods in this model — Vierendeel diagram needs at least one "Rigid" connection.',
                          fill='#999', font=('Helvetica', 9))

    def _draw_fiber_diagram(self):
        """Draws the whole structure once, with each rigid rod rendered as
        two thin parallel fiber bands (top = local '-v' side, bottom =
        local '+v' side -- see compute_fiber_stress docstring) colored
        red/blue per-station for tension/compression, splitting at every
        sign change exactly like the Vierendeel band renderer. Combines
        axial force with bending (N/A +/- M*c/I), so a member in heavy
        axial tension can show a compression-colored patch near a local
        moment peak if bending doesn't fully overcome the axial tension
        there, and vice versa. Pin rods have no bending distinction and
        draw as a single uniformly-colored line, using the same tension/
        compression coloring rule already used for pin rods on the main
        canvas.
        """
        dc = self.diag_zc.canvas
        dc.delete('all')
        DW = dc.winfo_width() or INIT_CW
        DH = dc.winfo_height() or INIT_DH

        if not self.results or not self.nodes or self.diagrams is None:
            dc.create_text(DW/2, DH/2, text='Run ▶ Analyze first', fill='#999',
                           font=('Helvetica', 11))
            return

        rod_res = self.results['rod_res']
        xs_n = [n[0] for n in self.nodes]; ys_n = [n[1] for n in self.nodes]
        xmin, xmax = min(xs_n), max(xs_n); ymin, ymax = min(ys_n), max(ys_n)
        span_w = max(xmax-xmin, 1); span_h = max(ymax-ymin, 1)

        pad = 40
        avail_w = max(DW - 2*pad, 10)
        avail_h = max(DH - 2*pad - 30, 10)
        scale_geo = min(avail_w/span_w, avail_h/span_h)

        # Same fix as _draw_vierendeel_diagram: compose the auto-fit layout
        # with diag_zc's own zoom/pan (already wired to mouse wheel + middle
        # drag) instead of a fixed transform that silently ignored it.
        zc_w2s = self.diag_zc.w2s
        z = self.diag_zc.zoom

        def T(wx, wy):
            return zc_w2s(pad + (wx-xmin)*scale_geo, pad + 30 + (wy-ymin)*scale_geo)

        dc.create_text(DW/2, 14, text='FIBER STRESS (top/bottom of each member)',
                       fill='#555', font=('Helvetica', 11, 'bold'))
        dc.create_text(DW/2, 30,
                       text='red = tension   blue = compression   (combines axial force with bending; '
                            'flips at points of contraflexure)',
                       fill='#888', font=('Helvetica', 8))

        THICK = 6 * z  # band thickness in pixels -- this is a color-coded
                       # strip, not a stress-magnitude-scaled offset, matching
                       # the classic isostatic-beam top/bottom picture.
                       # Scaled by the current zoom so the strip stays
                       # visually proportionate to the rest of the diagram
                       # as the user zooms in or out.

        def draw_fiber_band(pa, pb, nx, ny, xs_m, Lm, sigmas, sign):
            """One band (sign=+1 offsets toward +[nx,ny], sign=-1 toward
            -[nx,ny]) split into red/blue segments at every zero crossing."""
            if Lm <= 0 or not xs_m:
                return
            fracs = [x/Lm for x in xs_m]
            samples = list(zip(fracs, sigmas))
            segs, cur = [], [samples[0]]
            for i in range(1, len(samples)):
                f0, v0 = samples[i-1]; f1, v1 = samples[i]
                if v0*v1 < 0:
                    fc = f0 + (f1-f0)*(-v0)/(v1-v0)
                    cur.append((fc, 0.0)); segs.append(cur); cur = [(fc, 0.0)]
                cur.append((f1, v1))
            segs.append(cur)
            for seg in segs:
                if len(seg) < 2:
                    continue
                avg = sum(v for _, v in seg) / len(seg)
                color = CT if avg > 1e-6 else (CC if avg < -1e-6 else CZ)
                base_pts = [(pa[0]+(pb[0]-pa[0])*f, pa[1]+(pb[1]-pa[1])*f) for f, _ in seg]
                off_pts = [(px+nx*THICK*sign, py+ny*THICK*sign) for (px, py) in base_pts]
                poly = base_pts + off_pts[::-1]
                dc.create_polygon(*[c for p in poly for c in p],
                                  fill=color, outline='', width=0)

        for i, rod in enumerate(self.rods):
            na, nb = self.nodes[rod['a']], self.nodes[rod['b']]
            pa, pb = T(na[0], na[1]), T(nb[0], nb[1])
            rr = rod_res[i] if i < len(rod_res) else None

            if not rr or rr.get('conn', 'pin') != 'rigid' or i >= len(self.diagrams):
                force = rr.get('force', 0.0) if rr else 0.0
                color = CT if force > 0.01 else (CC if force < -0.01 else CZ)
                dc.create_line(*pa, *pb, fill=color, width=3)
                continue

            diag = self.diagrams[i]
            Lm = diag.get('Lm', 0.0)
            dx, dy = nb[0]-na[0], nb[1]-na[1]
            Lr = math.hypot(dx, dy) or 1
            nx, ny = -dy/Lr, dx/Lr   # same local-transverse direction used for Ma/Mb labels

            sigma_neg, sigma_pos = compute_fiber_stress(rod, rr, diag['M'])

            dc.create_line(*pa, *pb, fill='#bbb', width=1)
            draw_fiber_band(pa, pb, nx, ny, diag['xs'], Lm, sigma_neg, sign=-1)
            draw_fiber_band(pa, pb, nx, ny, diag['xs'], Lm, sigma_pos, sign=+1)

        for n in self.nodes:
            px, py = T(n[0], n[1])
            dc.create_oval(px-3, py-3, px+3, py+3, fill='#555', outline='')

    def _draw_diagrams_only(self):
        """Draw one shear/moment row per rod; never overlay member plots."""
        if getattr(self, 'diagram_mode', None) is not None and self.diagram_mode.get() == 'vierendeel':
            self._draw_vierendeel_diagram()
            return
        if getattr(self, 'diagram_mode', None) is not None and self.diagram_mode.get() == 'fiber':
            self._draw_fiber_diagram()
            return
        if not self.diagrams:
            # The model was edited (or nodes/rods removed) since the last
            # analysis -- these diagrams would otherwise just keep showing
            # whatever was last computed, silently out of sync with the
            # current model. Make that explicit instead of leaving the old
            # drawing on screen.
            dc = self.diag_zc.canvas
            dc.delete('all')
            DW = dc.winfo_width() or INIT_CW
            DH = dc.winfo_height() or INIT_DH
            dc.create_text(DW/2, DH/2,
                           text='Model changed — re-run ▶ Analyze to refresh diagrams',
                           fill='#999', font=('Helvetica', 11))
            return

        dc = self.diag_zc.canvas
        w2s = self.diag_zc.w2s
        z = self.diag_zc.zoom
        dc.delete('all')

        # A member row has two independent, side-by-side panels.  Their X/Y
        # locations are calculated from the rod INDEX only, never from node
        # coordinates, member midpoint, or member orientation.  This makes
        # coincident/parallel rods impossible to overlay.
        LEFT = 88.0
        PANEL_W = 330.0
        PANEL_GAP = 88.0
        ROW_H = 128.0
        ROW_GAP = 46.0
        TOP = 42.0
        x_v0 = LEFT
        x_m0 = LEFT + PANEL_W + PANEL_GAP

        def text(wx, wy, value, color='#444', bold=False, anchor='center'):
            sx, sy = w2s(wx, wy)
            dc.create_text(sx, sy, text=value, fill=color, anchor=anchor,
                           font=('Helvetica', max(7, int(8*z)), 'bold' if bold else 'normal'))

        def panel(rod_index, x0, y0, values, xs, length_m, color, title):
            half_h = ROW_H * 0.39
            zero_y = y0 + ROW_H / 2
            max_abs = max((abs(v) for v in values), default=0.0)
            # Keep an unloaded/pin member readable without dividing by zero.
            amplitude = half_h / (max_abs if max_abs > 1e-12 else 1.0)
            p0 = w2s(x0, y0)
            p1 = w2s(x0 + PANEL_W, y0 + ROW_H)
            dc.create_rectangle(p0[0], p0[1], p1[0], p1[1], outline='#dddddd')
            a0 = w2s(x0, zero_y)
            a1 = w2s(x0 + PANEL_W, zero_y)
            dc.create_line(a0[0], a0[1], a1[0], a1[1], fill='#bbbbbb')
            text(x0 + PANEL_W/2, y0 - 13, title, color, bold=True)
            text(x0 - 9, y0 + ROW_H/2, f'{max_abs:.2f}', color, anchor='e')
            text(x0 - 9, zero_y, '0', '#777', anchor='e')

            points = []
            for x, value in zip(xs, values):
                frac = x / length_m if length_m > 1e-12 else 0.0
                sx, sy = w2s(x0 + max(0.0, min(1.0, frac))*PANEL_W,
                             zero_y - value*amplitude)
                points.extend((sx, sy))
            if len(points) >= 4:
                base_l = w2s(x0, zero_y)
                base_r = w2s(x0 + PANEL_W, zero_y)
                dc.create_polygon([base_l[0], base_l[1], *points, base_r[0], base_r[1]],
                                  fill=color, outline='', stipple='gray25')
                dc.create_line(points, fill=color, width=max(1, int(1.5*z)))
            if values:
                peak_i = max(range(len(values)), key=lambda i: abs(values[i]))
                peak = values[peak_i]
                if abs(peak) > 1e-12:
                    frac = xs[peak_i] / length_m if length_m > 1e-12 else 0.0
                    text(x0 + frac*PANEL_W, zero_y - peak*amplitude - (10 if peak >= 0 else -10),
                         f'{peak:.2f}', color, bold=True)

        text(LEFT, 12, 'Ordered rod diagrams — one row per member', '#555', bold=True, anchor='w')
        rod_res_list = self.results.get('rod_res', []) if self.results else []
        for i, diag in enumerate(self.diagrams):
            y0 = TOP + i * (ROW_H + ROW_GAP)
            length_m = diag.get('Lm', 1.0) or 1.0
            rr = rod_res_list[i] if i < len(rod_res_list) else None
            is_rigid = bool(rr) and rr.get('conn', 'pin') == 'rigid'
            # A flat zero line here has two very different causes -- a pin
            # rod that structurally cannot carry bending at all, versus a
            # rigid rod that happens to have solved to ~zero moment. Label
            # which one this is so a flat line is never ambiguous.
            kind_lbl = 'rigid — M\u22480' if is_rigid else 'pin — no bending'
            text(LEFT - 12, y0 + ROW_H/2 - 8, f'Rod {i}', '#333', bold=True, anchor='e')
            text(LEFT - 12, y0 + ROW_H/2 + 8, kind_lbl, '#999', bold=False, anchor='e')
            panel(i, x_v0, y0, diag.get('V', []), diag.get('xs', []), length_m, CV, 'Shear V (kN)')
            panel(i, x_m0, y0, diag.get('M', []), diag.get('xs', []), length_m, CM, 'Moment M (kN·m)')

        dc.create_text(6, 6, anchor='nw', text='scroll=zoom  mid-drag=pan',
                       fill='#aaa', font=('Helvetica', 8))

    def _draw_diagrams_legacy_overview(self):
        if getattr(self, 'diagram_mode', None) is not None and self.diagram_mode.get() == 'vierendeel':
            self._draw_vierendeel_diagram()
            return
        if not self.diagrams: return
        dc  = self.diag_zc.canvas
        w2s = self.diag_zc.w2s
        z   = self.diag_zc.zoom
        dc.delete('all')
        DW = dc.winfo_width()  or INIT_CW
        DH = dc.winfo_height() or INIT_DH

        n_rods = len(self.rods)
        if n_rods == 0: return

        # ── ordered member layout ─────────────────────────────────────────────
        # This is intentionally NOT a structural-plan overlay.  Several rods
        # can share the same midpoint in the truss geometry (especially
        # verticals and diagonals), which previously made their diagrams draw
        # on top of one another.  Give every rod its own sequential slot:
        # Rod 0, Rod 1, …, in the same order as the model/rod table.
        max_member_px = max((d.get('Lm', 1.0) * PX_PER_M for d in self.diagrams),
                            default=1.0)
        slot_w = max(160.0, max_member_px + 80.0)
        x_min_w = 0.0
        x_max_w = slot_w * n_rods
        span_w = x_max_w - x_min_w

        # world height: each sub-diagram gets ROW_H world units
        ROW_H  = 120      # world units per diagram row (V and M)
        GAP    = 24
        MARG_L = 60       # world units left margin
        MARG_T = 20

        # place the diagram canvas origin to align with the truss canvas
        # by using the same pan_x as the truss canvas but independent zoom
        # The user can pan/zoom the diagram independently.

        all_V = [v for d in self.diagrams for v in d['V']]
        all_M = [m for d in self.diagrams for m in d['M']]
        max_V  = max((abs(v) for v in all_V), default=1) or 1
        max_M  = max((abs(m) for m in all_M), default=1) or 1
        amp_V  = (ROW_H/2 - 12) / max_V
        amp_M  = (ROW_H/2 - 12) / max_M

        zero_V_w = MARG_T + ROW_H/2
        zero_M_w = MARG_T + ROW_H + GAP + ROW_H/2
        bot_w    = MARG_T + ROW_H*2 + GAP + 20   # world height needed

        # Each member receives a distinct column, regardless of its physical
        # location or orientation in the truss.
        truss_cx_w = [(i + 0.5) * slot_w for i in range(n_rods)]
        col_hw_w = slot_w * 0.40

        # draw grid / baseline
        def ws2sc(wx, wy):   # world space of diagram → screen
            return w2s(wx, wy)

        # axis labels (in screen coords)
        def draw_text_s(sx, sy, text, color, bold=False):
            font = ('Helvetica', max(6, int(8*z)), 'bold' if bold else 'normal')
            dc.create_text(sx, sy, text=text, fill=color, font=font, anchor='center')

        # horizontal zero lines
        for zy_w, color in [(zero_V_w, CV), (zero_M_w, CM)]:
            x0s,y0s = ws2sc(x_min_w - MARG_L, zy_w)
            x1s,y1s = ws2sc(x_max_w + MARG_L, zy_w)
            dc.create_line(x0s, y0s, x1s, y1s, fill='#ccc', width=0.8)

        # bounding boxes
        for zy_w, color in [(zero_V_w, CV), (zero_M_w, CM)]:
            top_s = ws2sc(x_min_w - MARG_L, zy_w - ROW_H/2)
            bot_s = ws2sc(x_min_w - MARG_L, zy_w + ROW_H/2)
            dc.create_line(top_s[0], top_s[1], bot_s[0], bot_s[1], fill='#ddd')

        # axis tick labels
        for zy_w, amp, max_val, color, unit in [
            (zero_V_w, amp_V, max_V, CV, 'kN'),
            (zero_M_w, amp_M, max_M, CM, 'kNm')]:
            for val, lbl in [(max_val, f'+{max_val:.2f}'),
                              (0,        '0'),
                              (-max_val, f'-{max_val:.2f}')]:
                sx,sy = ws2sc(x_min_w - MARG_L + 8, zy_w - val*amp)
                draw_text_s(sx, sy, lbl, color)
            # unit label
            tsx,tsy = ws2sc(x_min_w - MARG_L + 4, zy_w - ROW_H/2 - 8)
            draw_text_s(tsx, tsy, f'V ({unit})' if color==CV else f'M ({unit})',
                         color, bold=True)

        # draw each rod column
        for i, (rod, diag) in enumerate(zip(self.rods, self.diagrams)):
            cx_w = truss_cx_w[i]
            hw_w = col_hw_w
            xs   = diag['xs']
            Vs   = diag['V']
            Ms   = diag['M']
            Lm   = diag.get('Lm',1) or 1

            def make_poly_pts(zero_w, data, amp):
                pts = []
                s0x,s0y = ws2sc(cx_w - hw_w, zero_w)
                pts += [s0x, s0y]
                for x,val in zip(xs, data):
                    wx_ = cx_w - hw_w + (x/Lm)*2*hw_w
                    wy_ = zero_w - val*amp
                    sx_,sy_ = ws2sc(wx_, wy_)
                    pts += [sx_, sy_]
                sex,sey = ws2sc(cx_w + hw_w, zero_w)
                pts += [sex, sey]
                return pts

            def make_line_pts(zero_w, data, amp):
                pts=[]
                for x,val in zip(data[0],data[1]):
                    wx_=cx_w-hw_w+(x/Lm)*2*hw_w
                    wy_=zero_w-val*amp
                    sx_,sy_=ws2sc(wx_,wy_)
                    pts+=[sx_,sy_]
                return pts

            # shear
            if len(Vs)>=2:
                poly = make_poly_pts(zero_V_w, Vs, amp_V)
                dc.create_polygon(poly, fill=CV, outline='', stipple='gray25')
                lpts = []
                for x,v in zip(xs,Vs):
                    wx_=cx_w-hw_w+(x/Lm)*2*hw_w; wy_=zero_V_w-v*amp_V
                    sx_,sy_=ws2sc(wx_,wy_); lpts+=[sx_,sy_]
                if len(lpts)>=4:
                    dc.create_line(lpts, fill=CV, width=max(1,1.5*z))

            # moment
            if len(Ms)>=2:
                poly = make_poly_pts(zero_M_w, Ms, amp_M)
                dc.create_polygon(poly, fill=CM, outline='', stipple='gray25')
                lpts=[]
                for x,m in zip(xs,Ms):
                    wx_=cx_w-hw_w+(x/Lm)*2*hw_w; wy_=zero_M_w-m*amp_M
                    sx_,sy_=ws2sc(wx_,wy_); lpts+=[sx_,sy_]
                if len(lpts)>=4:
                    dc.create_line(lpts, fill=CM, width=max(1,1.5*z))

            # column separator
            if i>0:
                sep_wx = cx_w - hw_w - 4
                s0x,s0y=ws2sc(sep_wx,MARG_T-4)
                s1x,s1y=ws2sc(sep_wx,bot_w)
                dc.create_line(s0x,s0y,s1x,s1y,fill='#ddd',width=0.5,dash=(3,3))

            # peak annotations
            for data, zero_w, amp, color in [
                (Vs, zero_V_w, amp_V, CV),
                (Ms, zero_M_w, amp_M, CM)]:
                if not data: continue
                pk = max(data, key=abs)
                if abs(pk) > (max_V if color==CV else max_M)*0.04:
                    pj = data.index(pk)
                    wx_=cx_w-hw_w+(xs[pj]/Lm)*2*hw_w
                    wy_=zero_w - pk*amp
                    sx_,sy_=ws2sc(wx_,wy_)
                    off = -9 if pk>=0 else 9
                    draw_text_s(sx_,sy_+off,f'{pk:.2f}',color)

            # rod label at bottom
            bsx,bsy = ws2sc(cx_w, bot_w)
            draw_text_s(bsx, bsy, f'Rod {i}', '#555', bold=True)

        # zoom hint
        dc.create_text(6,6,anchor='nw',
                        text='scroll=zoom  mid-drag=pan',
                        fill='#aaa',font=('Helvetica',8))

    # ══════════════════════════════════════════════════════════════════════════
    #  Excel export
    # ══════════════════════════════════════════════════════════════════════════
    def _show_node_vectors_report(self):
        """
        Opens a report window listing, for every node, the individual force
        vector that each connected rod applies to that node — magnitude,
        Fx/Fy components and angle w.r.t. the global coordinate system —
        together with a small free-body diagram (all vectors drawn from the
        node's center). This is the data needed to dimension each node's
        welded gusset plate (every rod converging on a node loads the plate
        along its own axis).
        """
        if not self.results:
            messagebox.showwarning('Node Force Vectors',
                'Run the analysis first.'); return

        win = tk.Toplevel(self.root)
        win.title('Node Force Vectors — for gusset plate design')
        win.geometry('620x680')
        win.configure(bg='#f5f5f3')

        tk.Label(win, text='Node Force Vectors', bg='#f5f5f3',
                 font=('Helvetica',13,'bold'), fg='#1a6bbd').pack(pady=(10,0))
        tk.Label(win,
                 text='Convention: global X→ right, Y↑ up, angle θ measured\n'
                      'counter-clockwise from +X. Each vector is the force that\n'
                      'rod exerts ON the node (tension pulls, compression pushes).\n'
                      'Diagram: all vectors drawn from the node center (free-body).',
                 bg='#f5f5f3', font=('Helvetica',9), fg='#555',
                 justify='center').pack(pady=(2,8))

        # ── scrollable area ──────────────────────────────────────────────────
        outer = tk.Frame(win, bg='#f5f5f3')
        outer.pack(fill='both', expand=True, padx=10, pady=(0,10))
        sb = tk.Scrollbar(outer, orient='vertical')
        sc = tk.Canvas(outer, bg='#f5f5f3', highlightthickness=0,
                       yscrollcommand=sb.set)
        sb.config(command=sc.yview)
        sb.pack(side='right', fill='y')
        sc.pack(side='left', fill='both', expand=True)

        inner = tk.Frame(sc, bg='#f5f5f3')
        inner_id = sc.create_window((0,0), window=inner, anchor='nw')

        def _sync_scroll(_e=None):
            sc.configure(scrollregion=sc.bbox('all'))
        def _sync_width(e):
            sc.itemconfig(inner_id, width=e.width)
        inner.bind('<Configure>', _sync_scroll)
        sc.bind('<Configure>', _sync_width)
        # mouse-wheel scrolling -- bind_all is needed (not a plain widget
        # bind) because <MouseWheel> only fires on the exact widget under
        # the cursor and won't bubble up from the labels/frames stacked
        # inside `inner`, so this is the only way to make the wheel work
        # anywhere over the report window. The half of this that was
        # missing before: explicitly unbinding it again when the window
        # closes, so a closed report doesn't leave a global handler firing
        # against a destroyed canvas every time the user scrolls anywhere
        # else in the app afterwards.
        def _wheel(e):
            sc.yview_scroll(int(-1*(e.delta/120)), 'units')
        sc.bind_all('<MouseWheel>', _wheel)
        def _on_close():
            sc.unbind_all('<MouseWheel>')
            win.destroy()
        win.protocol('WM_DELETE_WINDOW', _on_close)

        nv   = self.results['node_vectors']
        rxns = self.results['reactions']
        nmom = self.results.get('node_moments', {})
        FBD_SIZE = 190

        for ni in range(len(self.nodes)):
            vecs = nv.get(ni, [])
            ld   = next((l for l in self.loads if l['node']==ni), None)
            rxn  = rxns.get(ni)
            mom  = nmom.get(ni, {'members': [], 'net': 0.0})
            mom_by_rod = {m['rod']: m for m in mom['members']}

            block = tk.LabelFrame(inner, text=f'Node {ni}', bg='#ffffff',
                                  font=('Helvetica',10,'bold'), padx=6, pady=6)
            block.pack(fill='x', padx=4, pady=5)

            if not vecs:
                tk.Label(block, text='(no rods connected)', bg='#ffffff',
                         font=('Helvetica',9), fg='#888').pack(anchor='w')
                continue

            row = tk.Frame(block, bg='#ffffff')
            row.pack(fill='x')

            # -- free-body diagram canvas --------------------------------------
            cv = tk.Canvas(row, width=FBD_SIZE, height=FBD_SIZE, bg='white',
                          highlightthickness=1, highlightbackground='#ddd')
            cv.pack(side='left', padx=(0,10))
            self._draw_node_fbd(cv, vecs, ld, rxn, size=FBD_SIZE, net_moment=mom['net'],
                                max_moment=mom.get('max_signed', 0.0),
                                max_moment_rod=mom.get('max_abs_rod'))

            # -- numeric listing -------------------------------------------------
            info = tk.Text(row, width=34, height=max(12, len(vecs)*4+9),
                          relief='flat', bg='#ffffff', font=('Courier',9))
            info.pack(side='left', fill='both', expand=True)
            for v in vecs:
                mrec = mom_by_rod.get(v['rod'])
                if mrec is not None and mrec['conn'] == 'rigid':
                    m_str = f'{mrec["moment"]:+7.2f} kN\u00b7m'
                else:
                    m_str = ' 0.00 kN\u00b7m (pin)'
                info.insert('end',
                    f'Rod {v["rod"]:>2d}→N{v["other"]:<2d} [{v["kind"]}]\n'
                    f'  |F|={v["magnitude"]:7.2f} kN  θ={v["angle_deg"]:6.1f}°\n'
                    f'  Fx={v["Fx"]:+7.2f}  Fy={v["Fy"]:+7.2f} kN\n'
                    f'  M={m_str}\n')
            sum_fx = sum(v['Fx'] for v in vecs)
            sum_fy = sum(v['Fy'] for v in vecs)
            if ld:
                info.insert('end', f'Load   Fx={ld["fx"]:+7.2f}  Fy={-ld["fy"]:+7.2f} kN\n')
            if rxn:
                info.insert('end', f'Rxn({rxn["type"]}):\n')
                info.insert('end',
                    f'  Fx={rxn.get("rx",0):+7.2f}  Fy={-rxn.get("ry",0):+7.2f} kN\n')
            info.insert('end', f'ΣF(rods) Fx={sum_fx:+7.2f}  Fy={sum_fy:+7.2f} kN\n')
            info.insert('end', f'\u03a3M(node) = {mom["net"]:+7.2f} kN\u00b7m\n')
            info.insert('end', ' (equilib check; ~0 unless\n fixed support)\n')
            if mom['max_abs_rod'] is not None:
                info.insert('end', f'Max |M| = {mom["max_abs"]:6.2f} kN\u00b7m '
                                    f'(rod {mom["max_abs_rod"]})\n')
                info.insert('end', '  <- design moment for this joint\n')
            info.configure(state='disabled')

        tk.Button(win, text='Close', relief='flat', bg='#1a6bbd', fg='white',
                  font=('Helvetica',10,'bold'),
                  command=win.destroy).pack(pady=(0,10))

    def _draw_moment_arc(self, canvas, cx, cy, r, moment, color=CMOM, width=2.5,
                         start_angle=20, extent_mag=260, head_len=None):
        """
        Draws a circular-arrow glyph representing a moment: an arc plus a
        real, clearly visible arrowhead at its terminal end, centered at
        (cx, cy) with radius r on `canvas`. This is the ONE place that
        decides which way a moment arrow curls, so every depiction of a
        node moment in the app (main canvas, Node Force Vectors report,
        Rod Calculations report) uses the same rule and always agrees with
        the others.

        Convention: a positive moment (the sagging-positive convention used
        throughout this module) is drawn COUNTER-clockwise; a negative
        moment is drawn CLOCKWISE -- so the arrow always visually curls the
        way the moment would actually rotate the joint, not just a fixed
        color/side code. Tkinter's canvas angle system is already
        counter-clockwise-positive with 0 deg pointing right, so a positive
        `extent` directly gives a CCW arc with no extra sign bookkeeping.

        Arrowhead implementation note: an early version of this drew the
        head as a plain unstyled line segment tangent to the arc, which
        rendered as a barely-visible stub the same width as the arc itself
        -- it had no actual triangular head shape. This version instead
        draws the final short stretch of the sweep as its own straight
        chord with Tkinter's native `arrow='last'` line style (the exact
        same filled-triangle arrowhead already used for the force vectors
        elsewhere in this FBD, via `arrowshape`), which is what actually
        produces a real, clearly visible pointed head rather than an
        approximation of one.

        Returns (tip_x, tip_y) of the arrowhead tip, so callers can anchor
        a text label just outside the glyph without recomputing geometry.
        """
        extent = extent_mag if moment > 0 else -extent_mag
        # Reserve the last `head_span_deg` of the sweep for the arrowhead
        # chord instead of the full arc, so the head sits cleanly at the
        # tip without the arc's own stroke overlapping/burying it. Capped
        # so a small radius (e.g. the compact main-canvas glyph) doesn't
        # reserve more sweep than the arc actually has.
        head_span_deg = max(10, min(24, abs(extent) * 0.12))
        head_span = head_span_deg if extent > 0 else -head_span_deg
        arc_extent = extent - head_span

        canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=start_angle, extent=arc_extent,
                          style='arc', outline=color, width=width)

        a0 = math.radians(start_angle + arc_extent)
        a1 = math.radians(start_angle + extent)
        x0, y0 = cx + r*math.cos(a0), cy - r*math.sin(a0)
        x1, y1 = cx + r*math.cos(a1), cy - r*math.sin(a1)
        hl = head_len if head_len is not None else max(9, width*4)
        hw = max(6, hl*0.7)
        canvas.create_line(x0, y0, x1, y1, fill=color, width=width,
                           arrow='last', arrowshape=(hl, hl+2, hw))
        return x1, y1

    def _draw_node_fbd(self, canvas, vecs, load=None, rxn=None, size=190,
                       net_moment=0.0, max_moment=0.0, max_moment_rod=None):
        """
        Draws a small free-body diagram on `canvas`: every force vector
        acting on the node originates at the canvas center (representing the
        node), scaled so the largest vector spans most of the canvas.
        Colors match the main canvas legend: tension=CT, compression=CC,
        load=CL, reaction=CR. Coordinates are global (Y-up); the canvas
        itself is screen space (Y-down), so vertical components are flipped
        only for drawing.

        Moment glyph: drawn from `max_moment` (the largest individual rod
        end-moment at this joint, signed) rather than `net_moment`. `net`
        is a pure equilibrium check that is mathematically guaranteed to
        read ~0 at any free joint no matter how much moment its rods
        actually carry (see compute_node_moments docstring) -- using it to
        drive the visible arc would make the glyph disappear at exactly the
        joints where there's real Vierendeel action to show. `max_moment`
        is the number a connection actually needs to be designed for.
        `net_moment` is still shown as a small secondary text label so the
        equilibrium check remains visible (and becomes the informative one
        at a fixed-support node, where it captures the reaction moment).
        """
        canvas.delete('all')
        cx = cy = size/2

        # light crosshair through the node
        canvas.create_line(4, cy, size-4, cy, fill='#eee')
        canvas.create_line(cx, 4, cx, size-4, fill='#eee')

        mags = [v['magnitude'] for v in vecs]
        if load: mags.append(math.hypot(load['fx'], load['fy']))
        if rxn:  mags.append(math.hypot(rxn.get('rx',0), rxn.get('ry',0)))
        maxmag = max(mags) if mags else 1.0
        if maxmag < 1e-9: maxmag = 1.0
        Rmax = size*0.36
        Rmin = size*0.14

        def draw_arrow(Fx, Fy, color, label, dash=None):
            mag = math.hypot(Fx, Fy)
            if mag < 1e-6: return
            length = Rmin + (Rmax-Rmin)*(mag/maxmag)
            ux, uy = Fx/mag, Fy/mag           # global (y-up)
            ex, ey = cx + ux*length, cy - uy*length   # flip y for canvas
            canvas.create_line(cx, cy, ex, ey, fill=color, width=2,
                               arrow='last', arrowshape=(9,11,4), dash=dash)
            lx, ly = cx + ux*(length+16), cy - uy*(length+16)
            canvas.create_text(lx, ly, text=label, fill=color,
                               font=('Helvetica',7,'bold'), justify='center')

        for v in vecs:
            color = CT if v['kind']=='T' else (CC if v['kind']=='C' else CZ)
            draw_arrow(v['Fx'], v['Fy'], color,
                      f'R{v["rod"]}\n{v["magnitude"]:.1f}kN')
        if load and math.hypot(load['fx'], load['fy']) > 1e-6:
            draw_arrow(load['fx'], -load['fy'], CL,
                      f'Load\n{math.hypot(load["fx"],load["fy"]):.1f}kN',
                      dash=(3,2))
        if rxn and math.hypot(rxn.get('rx',0), rxn.get('ry',0)) > 1e-6:
            draw_arrow(rxn.get('rx',0), -rxn.get('ry',0), CR,
                      f'Rxn\n{math.hypot(rxn.get("rx",0),rxn.get("ry",0)):.1f}kN',
                      dash=(4,2))

        # design moment at this joint -- a circular-arrow glyph, sized/
        # oriented from the LARGEST individual rod moment meeting here (not
        # the net sum -- see docstring above).
        if abs(max_moment) > 0.05:
            r = size*0.22
            self._draw_moment_arc(canvas, cx, cy, r, max_moment, color=CMOM, width=2.5)
            rod_tag = f' (R{max_moment_rod})' if max_moment_rod is not None else ''
            canvas.create_text(cx, cy-r-20, text=f'M_max={max_moment:+.1f} kN\u00b7m{rod_tag}',
                              fill=CMOM, font=('Helvetica',7,'bold'))
            if abs(net_moment) > 0.05:
                canvas.create_text(cx, cy-r-9, text=f'\u03a3M={net_moment:+.1f} (equilib.)',
                                  fill='#aaa', font=('Helvetica',6))

        # node dot on top
        canvas.create_oval(cx-4, cy-4, cx+4, cy+4, fill=CN, outline='')

    def _draw_rod_context(self, canvas, rod_idx, size=170):
        """
        Small schematic of the WHOLE truss (all rods in light gray) with the
        rod at `rod_idx` highlighted — gives visual context for where this
        member sits, for the Rod Calculations report.
        """
        canvas.delete('all')
        if not self.nodes: return
        xs = [n[0] for n in self.nodes]; ys = [n[1] for n in self.nodes]
        minx, maxx = min(xs), max(xs); miny, maxy = min(ys), max(ys)
        spanx = (maxx-minx) or 1; spany = (maxy-miny) or 1
        pad = 18
        scale = min((size-2*pad)/spanx, (size-2*pad)/spany)
        cx0, cy0 = (minx+maxx)/2, (miny+maxy)/2

        def tx(pt):
            return size/2 + (pt[0]-cx0)*scale, size/2 + (pt[1]-cy0)*scale

        for i, rod in enumerate(self.rods):
            if i == rod_idx: continue
            x0, y0 = tx(self.nodes[rod['a']]); x1, y1 = tx(self.nodes[rod['b']])
            canvas.create_line(x0, y0, x1, y1, fill='#cfcfcf', width=2)

        rod = self.rods[rod_idx]
        x0, y0 = tx(self.nodes[rod['a']]); x1, y1 = tx(self.nodes[rod['b']])
        color = CZ
        if self.results:
            f = self.results['rod_res'][rod_idx]['force']
            color = CT if f>0.01 else (CC if f<-0.01 else CZ)
        canvas.create_line(x0, y0, x1, y1, fill=color, width=4)

        for i, n in enumerate(self.nodes):
            x, y = tx(n)
            if i in (rod['a'], rod['b']):
                canvas.create_oval(x-5, y-5, x+5, y+5, fill=CS, outline='#333')
                canvas.create_text(x, y-10, text=str(i), fill='#333',
                                   font=('Helvetica',7,'bold'))
            else:
                canvas.create_oval(x-3, y-3, x+3, y+3, fill='#999', outline='')

    def _show_rod_calculations_report(self):
        """
        Opens a report window with one block per rod: a small context
        diagram (where this member sits in the whole truss), the axial-
        force calculation typeset with matplotlib's mathtext (a built-in
        LaTeX-style renderer — no separate TeX installation needed), and
        the complete free-body diagram at BOTH end nodes — i.e. every other
        rod, load, and reaction converging at that joint. This is meant to
        let you check one member and both of its gusset-plate connections
        at a glance.
        """
        if not self.results:
            messagebox.showwarning('Rod Calculations', 'Run the analysis first.'); return

        have_math = _ensure_matplotlib()
        win = tk.Toplevel(self.root)
        win._math_refs = []   # keep PhotoImage references alive for this window
        win.title('Rod / Member Calculations')
        win.geometry('960x720')
        win.configure(bg='#f5f5f3')

        tk.Label(win, text='Rod / Member Calculations', bg='#f5f5f3',
                 font=('Helvetica',13,'bold'), fg='#1a6bbd').pack(pady=(10,0))
        tk.Label(win,
                 text='Left: where this member sits in the truss. Middle: its axial-force\n'
                      'calculation. Right: the full free-body diagram at each end node —\n'
                      'every other rod + load + reaction converging at that joint.',
                 bg='#f5f5f3', font=('Helvetica',9), fg='#555',
                 justify='center').pack(pady=(2,8))
        if not have_math:
            tk.Label(win,
                     text='(Couldn\'t load matplotlib/Pillow for LaTeX-style equations — '
                          'showing plain text instead. Run: pip install matplotlib pillow)',
                     bg='#f5f5f3', font=('Helvetica',8,'italic'), fg='#b33').pack()

        outer = tk.Frame(win, bg='#f5f5f3')
        outer.pack(fill='both', expand=True, padx=10, pady=(0,10))
        sb = tk.Scrollbar(outer, orient='vertical')
        sc = tk.Canvas(outer, bg='#f5f5f3', highlightthickness=0, yscrollcommand=sb.set)
        sb.config(command=sc.yview); sb.pack(side='right', fill='y')
        sc.pack(side='left', fill='both', expand=True)
        inner = tk.Frame(sc, bg='#f5f5f3')
        inner_id = sc.create_window((0,0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda e: sc.configure(scrollregion=sc.bbox('all')))
        sc.bind('<Configure>', lambda e: sc.itemconfig(inner_id, width=e.width))
        # See the matching comment in _show_node_vectors_report: bind_all is
        # required for wheel-scroll to work over the whole report, but it
        # must be torn down when the window closes or it keeps firing
        # against a destroyed canvas afterwards.
        def _wheel(e):
            sc.yview_scroll(int(-1*(e.delta/120)), 'units')
        sc.bind_all('<MouseWheel>', _wheel)
        def _on_close():
            sc.unbind_all('<MouseWheel>')
            win.destroy()
        win.protocol('WM_DELETE_WINDOW', _on_close)

        nv, rxns = self.results['node_vectors'], self.results['reactions']
        nmom = self.results.get('node_moments', {})
        CTX_SIZE, FBD_SIZE = 170, 170

        for ri, rod in enumerate(self.rods):
            a, b = rod['a'], rod['b']
            na, nb = self.nodes[a], self.nodes[b]
            dxp, dyp = nb[0]-na[0], nb[1]-na[1]
            Lm = math.hypot(dxp, dyp) / PX_PER_M
            theta = math.degrees(math.atan2(-dyp, dxp)) % 360   # global CCW from +X
            f = self.results['rod_res'][ri]['force']
            kind = 'Tension' if f>0.01 else ('Compression' if f<-0.01 else 'Zero')
            color = CT if f>0.01 else (CC if f<-0.01 else CZ)

            block = tk.LabelFrame(inner,
                text=f'Rod {ri}   (Node {a} → Node {b})   [{kind}]',
                bg='#ffffff', font=('Helvetica',10,'bold'),
                fg=(color if color!=CZ else '#333'), padx=6, pady=6)
            block.pack(fill='x', padx=4, pady=6)
            row = tk.Frame(block, bg='#ffffff'); row.pack(fill='x')

            # -- context diagram --------------------------------------------------
            ctx_col = tk.Frame(row, bg='#ffffff'); ctx_col.pack(side='left', padx=(0,10))
            tk.Label(ctx_col, text='Location in truss', bg='#ffffff',
                     font=('Helvetica',8,'bold'), fg='#777').pack()
            ctx = tk.Canvas(ctx_col, width=CTX_SIZE, height=CTX_SIZE, bg='white',
                           highlightthickness=1, highlightbackground='#ddd')
            ctx.pack()
            self._draw_rod_context(ctx, ri, size=CTX_SIZE)

            # -- calculation (LaTeX-style via matplotlib mathtext) -----------------
            calc_col = tk.Frame(row, bg='#ffffff')
            calc_col.pack(side='left', fill='both', expand=True, padx=(0,10))
            tk.Label(calc_col, text='Calculation', bg='#ffffff',
                     font=('Helvetica',8,'bold'), fg='#777').pack(anchor='w')

            cos_t, sin_t = math.cos(math.radians(theta)), math.sin(math.radians(theta))
            eqs = [
                rf'$L=\sqrt{{\Delta x^2+\Delta y^2}}={Lm:.3f}\ m$',
                rf'$\theta={theta:.1f}^\circ,\ \ \cos\theta={cos_t:.3f},\ \ \sin\theta={sin_t:.3f}$',
                rf'$N_{{{ri}}}={f:+.2f}\ kN$',
                rf'$F_{{x,{a}}}=N\cos\theta={f*cos_t:+.2f}\ kN,\quad'
                rf' F_{{y,{a}}}=N\sin\theta={f*sin_t:+.2f}\ kN$',
                rf'$F_{{x,{b}}}=-N\cos\theta={-f*cos_t:+.2f}\ kN,\quad'
                rf' F_{{y,{b}}}=-N\sin\theta={-f*sin_t:+.2f}\ kN$',
            ]
            rr = self.results['rod_res'][ri]
            if rr.get('conn') == 'rigid':
                # Vierendeel moment: the end moments this rigid connection
                # carries, plus the peak moment anywhere along its span
                # (from the same M(x) the diagram pane and fiber-stress
                # feature both already use, so this number always agrees
                # with what's plotted elsewhere).
                Ma, Mb = rr.get('Ma', 0.0), rr.get('Mb', 0.0)
                peak_M = 0.0
                if self.diagrams and ri < len(self.diagrams):
                    Ms = self.diagrams[ri].get('M', [])
                    if Ms:
                        peak_M = max(Ms, key=abs)
                eqs.append(
                    rf'$\mathrm{{Vierendeel\ moment:}}\ \ M_{{a}}={Ma:+.2f}\ kN{{\cdot}}m,'
                    rf'\quad M_{{b}}={Mb:+.2f}\ kN{{\cdot}}m$')
                eqs.append(rf'$\mathrm{{Peak}}\ M(x)={peak_M:+.2f}\ kN{{\cdot}}m'
                           rf'\ \mathrm{{along\ span}}$')
            else:
                eqs.append(r'$\mathrm{Vierendeel\ moment:}\ \ N/A\ \mathrm{-\ pinned\ connection,\ no\ bending}$')
            for eq in eqs:
                img = render_math(eq, fontsize=12, color='#222222') if have_math else None
                if img is not None:
                    win._math_refs.append(img)
                    tk.Label(calc_col, image=img, bg='#ffffff').pack(anchor='w', pady=2)
                else:
                    plain = (eq.replace('$','').replace(r'\Delta','d')
                               .replace(r'\theta','theta').replace(r'^\circ','deg')
                               .replace(r'\sqrt','sqrt').replace(r'\quad','   ')
                               .replace(r'\mathrm','').replace(r'\cdot','\u00b7')
                               .replace(r'\ ',' ').replace('{','').replace('}',''))
                    tk.Label(calc_col, text=plain, bg='#ffffff', fg='#222',
                            font=('Courier',10), justify='left').pack(anchor='w', pady=1)

            # -- end-node free-body diagrams ---------------------------------------
            for end_node, end_lbl in [(a,'A'), (b,'B')]:
                end_col = tk.Frame(row, bg='#ffffff'); end_col.pack(side='left', padx=(0,4))
                tk.Label(end_col, text=f'End {end_lbl} — Node {end_node}', bg='#ffffff',
                         font=('Helvetica',8,'bold'), fg='#777').pack()
                cv = tk.Canvas(end_col, width=FBD_SIZE, height=FBD_SIZE, bg='white',
                              highlightthickness=1, highlightbackground='#ddd')
                cv.pack()
                vecs_end = nv.get(end_node, [])
                ld_end   = next((l for l in self.loads if l['node']==end_node), None)
                rxn_end  = rxns.get(end_node)
                nmom_end = nmom.get(end_node, {'net':0.0, 'max_signed':0.0, 'max_abs_rod':None})
                self._draw_node_fbd(cv, vecs_end, ld_end, rxn_end, size=FBD_SIZE,
                                    net_moment=nmom_end['net'],
                                    max_moment=nmom_end.get('max_signed', 0.0),
                                    max_moment_rod=nmom_end.get('max_abs_rod'))

        tk.Button(win, text='Close', relief='flat', bg='#1a6bbd', fg='white',
                  font=('Helvetica',10,'bold'),
                  command=win.destroy).pack(pady=(0,10))

    def _export_excel(self):
        if not self.results:
            messagebox.showwarning('Export',
                'Run the analysis first before exporting.'); return
        # install openpyxl automatically if it is missing
        if not _ensure_openpyxl():
            messagebox.showerror(
                'Missing library',
                'Could not install openpyxl automatically.\n\n'
                'Please open a terminal and run:\n'
                '    pip install openpyxl\n'
                'then try again.')
            return
        if not _ensure_matplotlib():
            self.status_var.set(
                'Note: matplotlib/Pillow unavailable — Excel export will skip '
                'the per-rod picture sheet but everything else still works.')
        path = filedialog.asksaveasfilename(
            defaultextension='.xlsx',
            filetypes=[('Excel workbook','*.xlsx')],
            initialfile='truss_report.xlsx',
            title='Save Excel report')
        if not path: return
        try:
            export_excel(self.nodes, self.rods, self.loads, self.supports,
                         self.results, path, profiles=self.profiles)
            self.status_var.set(f'Excel report saved → {os.path.basename(path)}')
            messagebox.showinfo('Exported', f'Report saved to:\n{path}\n\n'
                                'Includes a "Model" sheet — use "Import Excel" '
                                'to rebuild this exact truss from the file later.')
        except Exception as e:
            messagebox.showerror('Export failed', str(e))

    def _import_excel(self):
        if not _ensure_openpyxl():
            messagebox.showerror(
                'Missing library',
                'Could not install openpyxl automatically.\n\n'
                'Please open a terminal and run:\n'
                '    pip install openpyxl\n'
                'then try again.')
            return
        path = filedialog.askopenfilename(
            filetypes=[('Excel workbook','*.xlsx')],
            title='Import truss from Excel')
        if not path: return
        try:
            nodes, rods, loads, supports, profiles = import_excel_model(path)
        except Exception as e:
            messagebox.showerror('Import failed', str(e)); return

        self._clear_all()
        self.nodes = [list(n) for n in nodes]
        self.rods = rods
        self.loads = loads
        self.supports = supports
        self.profiles = profiles
        self._refresh_profile_combo()
        self._draw()
        self.status_var.set(
            f'Imported {len(nodes)} node(s), {len(rods)} rod(s) from '
            f'{os.path.basename(path)} — click ▶ Analyze.')

    # ══════════════════════════════════════════════════════════════════════════
    #  Example / clear
    # ══════════════════════════════════════════════════════════════════════════
    def _load_example(self):
        self._clear_all()
        ox,oy,sp,h = 96,288,120,96
        self.nodes=[
            (ox,oy),(ox+sp,oy-h),(ox+2*sp,oy),
            (ox+3*sp,oy-h),(ox+4*sp,oy)]
        self.rods=[
            {'a':0,'b':1,'E':200,'A':10,'profile':'Default'},
            {'a':1,'b':2,'E':200,'A':10,'profile':'Default'},
            {'a':2,'b':3,'E':200,'A':10,'profile':'Default'},
            {'a':3,'b':4,'E':200,'A':10,'profile':'Default'},
            {'a':0,'b':2,'E':200,'A':8,'profile':'Diagonal'},
            {'a':2,'b':4,'E':200,'A':8,'profile':'Diagonal'},
            {'a':1,'b':3,'E':200,'A':8,'profile':'Diagonal'}]
        self.profiles = {'Default': {'E':200.0,'A':10.0},
                         'Diagonal': {'E':200.0,'A':8.0}}
        self.supports=[{'node':0,'type':'pin'},{'node':4,'type':'rollerX'}]
        self.loads=[{'node':1,'fx':0,'fy':30},
                    {'node':2,'fx':0,'fy':60},
                    {'node':3,'fx':0,'fy':30}]
        self._refresh_profile_combo()
        self._draw()
        self.status_var.set('Warren truss loaded — click ▶ Analyze.')

    def _load_example_vierendeel(self):
        self._clear_all()
        ox, oy, sp, h = 96, 288, 120, 96
        # bottom chord: nodes 0-4 ; top chord: nodes 5-9 ; no diagonals —
        # every rod is 'rigid' (moment-connected), which is what lets a
        # Vierendeel girder carry load without any diagonal bracing.
        self.nodes = [(ox+i*sp, oy) for i in range(5)] + \
                     [(ox+i*sp, oy-h) for i in range(5)]

        def rigid(a, b):
            return {'a': a, 'b': b, 'E': 200.0, 'A': 10.0, 'I': 8000.0,
                    'conn': 'rigid', 'profile': 'Default'}

        self.rods = (
            [rigid(i, i+1) for i in range(4)] +        # bottom chord
            [rigid(5+i, 6+i) for i in range(4)] +       # top chord
            [rigid(i, 5+i) for i in range(5)]           # verticals (no diagonals)
        )
        self.profiles = {'Default': {'E': 200.0, 'A': 10.0, 'I': 8000.0}}
        self.supports = [{'node': 0, 'type': 'pin'}, {'node': 4, 'type': 'rollerX'}]
        self.loads = [{'node': 6, 'fx': 0, 'fy': 20},
                      {'node': 7, 'fx': 0, 'fy': 20},
                      {'node': 8, 'fx': 0, 'fy': 20}]
        self._refresh_profile_combo()
        self._draw()
        self.status_var.set(
            'Vierendeel girder loaded (all rods rigid, no diagonals) — click ▶ Analyze. '
            'Select rods + "Set Pinned" to turn any of them back into a classic truss bar.')

    def _clear_all(self):
        self.nodes=[];self.rods=[];self.loads=[];self.supports=[]
        self.results=None;self.diagrams=None
        self.selected_nodes=set();self.selected_rods=set();self.rod_start=None
        self.pending_load=set();self.pending_sup=set()
        self.profiles={'Default': {'E':200.0,'A':10.0,'I':8000.0}}
        self.load_frame.pack_forget();self.sup_frame.pack_forget()
        self.rod_res_frame.pack_forget();self.rxn_frame.pack_forget()
        self.res_var.set('')
        self.show_deform.set(False)
        self.diag_outer.pack_forget()
        self.diag_zc.canvas.delete('all')
        if hasattr(self, '_refresh_profile_combo'): self._refresh_profile_combo()
        self._show_sel();self._draw()
        self.status_var.set('Cleared. Start with the Node tool.')
