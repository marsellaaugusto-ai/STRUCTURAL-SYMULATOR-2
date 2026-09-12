"""Stereo tab -- Tkinter UI for the 3D space-structure calculator.

One interface over every geometry typology stereo_geometry.py can build
(flat double-layer grid, barrel vault, dome), full CIRSOC-checked 3D
direct-stiffness analysis (stereo_math.py), and Excel/report export
(stereo_reports.py) -- the same "geometry generator + analysis + CIRSOC
checks + report/Excel export" pipeline the Truss tab has, generalized to
3D, per the 2026-09 handoff conversation this tab was requested from.

Boundary conditions are the one area that conversation asked to be bug-free
and unrestricted: every node's six DOFs (ux,uy,uz,rx,ry,rz) can be
restrained in ANY combination, independent of the six preset buttons this
UI also offers as a shortcut -- see `_apply_support` below and
`stereo_math.support_restraints`.

Structured after apps/truss/truss_app.py (a plain object mixing in
UnitsMixin, built directly into the tab Frame main.py hands it) for
consistency with the rest of the app; see that file and
common.FlowBar/ZoomCanvas/UnitsMixin for the shared idioms this reuses.
"""
import math
import copy
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import units
from common import ZoomCanvas, FlowBar, UnitsMixin, declutter_text

from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_math as sm
from apps.stereo import stereo_checks as sc
from apps.stereo import stereo_reports as sr

BG = '#f5f5f3'
CANVAS_BG = '#ffffff'
NODE_COLOR = '#1a1a1a'
NODE_SEL_COLOR = '#e0522b'
SUPPORT_COLOR = '#1a6bbd'
MEMBER_PIN_COLOR = '#2a2a2a'
MEMBER_RIGID_COLOR = '#7a3fb8'
TENSION_COLOR = '#1a7a3c'
COMPRESSION_COLOR = '#c0392b'
OVER_COLOR = '#ff0000'
UNDO_LIMIT = 60

DOF_LABELS = (('ux', 'Ux'), ('uy', 'Uy'), ('uz', 'Uz'),
              ('rx', 'Rx'), ('ry', 'Ry'), ('rz', 'Rz'))

PRESET_NAMES = ('free', 'pin', 'fixed', 'rollerX', 'rollerY', 'rollerZ', 'custom')


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

        self.azimuth = 35.0
        self.elevation = 22.0

        self._undo_stack = []
        self._redo_stack = []

        self.generator = tk.StringVar(value='flat_grid')

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
        tk.Label(g, text='Generator:', bg=BG).pack(side='left', padx=(4, 2))
        gen_box = ttk.Combobox(g, textvariable=self.generator, state='readonly', width=14,
                                values=['flat_grid', 'barrel_vault', 'dome'])
        gen_box.pack(side='left')
        gen_box.bind('<<ComboboxSelected>>', lambda e: self._on_generator_change())
        tk.Button(g, text='Generate', command=self._generate).pack(side='left', padx=4)

        g = self.toolbar_flow.group()
        tk.Button(g, text='Undo', command=self._undo).pack(side='left', padx=2)
        tk.Button(g, text='Redo', command=self._redo).pack(side='left', padx=2)
        tk.Button(g, text='Analyze', command=self._analyze, bg='#dff0d8').pack(side='left', padx=4)

        g = self.toolbar_flow.group()
        tk.Label(g, text='View az:', bg=BG).pack(side='left')
        tk.Button(g, text='◀', command=lambda: self._rotate(-15, 0), width=2).pack(side='left')
        tk.Button(g, text='▶', command=lambda: self._rotate(15, 0), width=2).pack(side='left')
        tk.Label(g, text='el:', bg=BG).pack(side='left', padx=(6, 0))
        tk.Button(g, text='▲', command=lambda: self._rotate(0, 10), width=2).pack(side='left')
        tk.Button(g, text='▼', command=lambda: self._rotate(0, -10), width=2).pack(side='left')

        g = self.toolbar_flow.group()
        tk.Button(g, text='Export Excel…', command=self._export_excel).pack(side='left', padx=2)
        tk.Button(g, text='Import Excel…', command=self._import_excel).pack(side='left', padx=2)

        self.toolbar_flow.start()

        main = tk.Frame(self.root, bg=BG)
        main.pack(fill='both', expand=True)

        # ── sidebar (scrollable-by-fixed-width, matching the rest of the app's
        # left-panel convention) ────────────────────────────────────────────
        side = tk.Frame(main, bg=BG, width=360)
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        side_canvas = tk.Canvas(side, bg=BG, highlightthickness=0, width=360)
        side_scroll = ttk.Scrollbar(side, orient='vertical', command=side_canvas.yview)
        side_inner = tk.Frame(side_canvas, bg=BG)
        side_inner.bind('<Configure>', lambda e: side_canvas.configure(scrollregion=side_canvas.bbox('all')))
        side_canvas.create_window((0, 0), window=side_inner, anchor='nw')
        side_canvas.configure(yscrollcommand=side_scroll.set)
        side_canvas.pack(side='left', fill='both', expand=True)
        side_scroll.pack(side='right', fill='y')

        self._build_generator_params(side_inner)
        self._build_section_panel(side_inner)
        self._build_selection_panel(side_inner)
        self._build_supports_panel(side_inner)
        self._build_loads_panel(side_inner)
        self._build_results_panel(side_inner)

        # ── 3D canvas ────────────────────────────────────────────────────────
        canvas_frame = tk.Frame(main, bg=BG)
        canvas_frame.pack(side='left', fill='both', expand=True)
        self.zc = ZoomCanvas(canvas_frame, bg=CANVAS_BG, bd=1, relief='solid')
        self.zc.pack(fill='both', expand=True)
        self.zc._on_zoom_changed = self._draw
        self.canvas = self.zc.canvas
        self.canvas.bind('<Configure>', lambda e: self._draw())
        self.canvas.bind('<Button-1>', self._on_canvas_click)

        self._on_generator_change()

    def _labeled_entry(self, parent, label, var, width=10):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill='x', padx=6, pady=1)
        lb = tk.Label(row, text=label, bg=BG, width=16, anchor='w')
        lb.pack(side='left')
        tk.Entry(row, textvariable=var, width=width).pack(side='left')
        return lb

    def _build_generator_params(self, parent):
        box = tk.LabelFrame(parent, text='Geometry generator', bg=BG)
        box.pack(fill='x', padx=6, pady=4)

        # flat grid
        self.fg_span_x = tk.DoubleVar(value=12.0)
        self.fg_span_y = tk.DoubleVar(value=9.0)
        self.fg_depth = tk.DoubleVar(value=1.2)
        self.fg_module = tk.DoubleVar(value=3.0)
        self.fg_offset = tk.BooleanVar(value=True)
        self.frame_flat_grid = tk.Frame(box, bg=BG)
        self._lb_fg_span_x = self._labeled_entry(self.frame_flat_grid, 'Span X:', self.fg_span_x)
        self._lb_fg_span_y = self._labeled_entry(self.frame_flat_grid, 'Span Y:', self.fg_span_y)
        self._lb_fg_depth = self._labeled_entry(self.frame_flat_grid, 'Depth:', self.fg_depth)
        self._lb_fg_module = self._labeled_entry(self.frame_flat_grid, 'Module:', self.fg_module)
        tk.Checkbutton(self.frame_flat_grid, text='Offset top layer (square-on-square offset)',
                       variable=self.fg_offset, bg=BG).pack(anchor='w', padx=6)

        # barrel vault
        self.bv_span = tk.DoubleVar(value=10.0)
        self.bv_rise = tk.DoubleVar(value=2.5)
        self.bv_length = tk.DoubleVar(value=15.0)
        self.bv_depth = tk.DoubleVar(value=0.6)
        self.bv_n_arch = tk.IntVar(value=8)
        self.bv_n_bays = tk.IntVar(value=8)
        self.bv_double = tk.BooleanVar(value=True)
        self.frame_barrel_vault = tk.Frame(box, bg=BG)
        self._lb_bv_span = self._labeled_entry(self.frame_barrel_vault, 'Span:', self.bv_span)
        self._lb_bv_rise = self._labeled_entry(self.frame_barrel_vault, 'Rise:', self.bv_rise)
        self._lb_bv_length = self._labeled_entry(self.frame_barrel_vault, 'Length:', self.bv_length)
        self._labeled_entry(self.frame_barrel_vault, 'Arch segments:', self.bv_n_arch)
        self._labeled_entry(self.frame_barrel_vault, 'Bays:', self.bv_n_bays)
        tk.Checkbutton(self.frame_barrel_vault, text='Double layer', variable=self.bv_double,
                       bg=BG, command=self._on_generator_change).pack(anchor='w', padx=6)
        self._lb_bv_depth = self._labeled_entry(self.frame_barrel_vault, 'Layer depth:', self.bv_depth)

        # dome
        self.dm_radius = tk.DoubleVar(value=10.0)
        self.dm_rise = tk.DoubleVar(value=3.0)
        self.dm_n_rings = tk.IntVar(value=4)
        self.dm_n_sectors = tk.IntVar(value=12)
        self.frame_dome = tk.Frame(box, bg=BG)
        self._lb_dm_radius = self._labeled_entry(self.frame_dome, 'Base radius:', self.dm_radius)
        self._lb_dm_rise = self._labeled_entry(self.frame_dome, 'Rise:', self.dm_rise)
        self._labeled_entry(self.frame_dome, 'Rings:', self.dm_n_rings)
        self._labeled_entry(self.frame_dome, 'Sectors:', self.dm_n_sectors)

        self._param_frames = {'flat_grid': self.frame_flat_grid,
                              'barrel_vault': self.frame_barrel_vault,
                              'dome': self.frame_dome}

    def _build_section_panel(self, parent):
        box = tk.LabelFrame(parent, text='Member section (applied to every member on Generate)', bg=BG)
        box.pack(fill='x', padx=6, pady=4)
        self.sec_E = tk.DoubleVar(value=200.0)
        self.sec_A = tk.DoubleVar(value=15.0)
        self.sec_I = tk.DoubleVar(value=400.0)
        self.sec_J = tk.DoubleVar(value=400.0)
        self.sec_Fy = tk.DoubleVar(value=250.0)
        self.sec_Fu = tk.DoubleVar(value=400.0)
        self.sec_K = tk.DoubleVar(value=1.0)
        self.sec_r_gyr = tk.DoubleVar(value=2.5)
        self.sec_conn = tk.StringVar(value='pin')

        self._lb_sec_E = self._labeled_entry(box, 'E:', self.sec_E)
        self._lb_sec_A = self._labeled_entry(box, 'A:', self.sec_A)
        self._lb_sec_I = self._labeled_entry(box, 'I (rigid only):', self.sec_I)
        self._lb_sec_J = self._labeled_entry(box, 'J (rigid only):', self.sec_J)
        self._lb_sec_Fy = self._labeled_entry(box, 'Fy:', self.sec_Fy)
        self._lb_sec_Fu = self._labeled_entry(box, 'Fu:', self.sec_Fu)
        self._labeled_entry(box, 'K (eff. length):', self.sec_K)
        self._lb_sec_r = self._labeled_entry(box, 'r_gyr (pin compr.):', self.sec_r_gyr)

        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=6, pady=(2, 4))
        tk.Label(row, text='Connectivity:', bg=BG, width=16, anchor='w').pack(side='left')
        tk.Radiobutton(row, text='Pin (space truss)', value='pin', variable=self.sec_conn,
                       bg=BG).pack(side='left')
        tk.Radiobutton(row, text='Rigid (Vierendeel)', value='rigid', variable=self.sec_conn,
                       bg=BG).pack(side='left')

        tk.Button(box, text='Apply section to all members', command=self._apply_section_to_all
                  ).pack(padx=6, pady=(0, 6), anchor='w')

        row2 = tk.Frame(box, bg=BG)
        row2.pack(fill='x', padx=6, pady=(0, 6))
        self.self_weight_on = tk.BooleanVar(value=True)
        tk.Checkbutton(row2, text='Include self-weight, unit wt (kN/m³):',
                       variable=self.self_weight_on, bg=BG).pack(side='left')
        self.unit_weight_var = tk.DoubleVar(value=sm.DEFAULT_STEEL_UNIT_WEIGHT)
        tk.Entry(row2, textvariable=self.unit_weight_var, width=8).pack(side='left', padx=4)

    def _build_selection_panel(self, parent):
        box = tk.LabelFrame(parent, text='Selected node', bg=BG)
        box.pack(fill='x', padx=6, pady=4)
        self.sel_label = tk.Label(box, text='(click a node in the view)', bg=BG, fg='#666')
        self.sel_label.pack(anchor='w', padx=6, pady=4)

    def _build_supports_panel(self, parent):
        box = tk.LabelFrame(
            parent, text='Boundary conditions -- any combination of the six DOFs', bg=BG)
        box.pack(fill='x', padx=6, pady=4)

        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=6, pady=2)
        tk.Label(row, text='Node:', bg=BG, width=16, anchor='w').pack(side='left')
        self.sup_node_var = tk.IntVar(value=0)
        tk.Entry(row, textvariable=self.sup_node_var, width=6).pack(side='left')

        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=6, pady=2)
        tk.Label(row, text='Preset:', bg=BG, width=16, anchor='w').pack(side='left')
        self.sup_preset_var = tk.StringVar(value='pin')
        preset_box = ttk.Combobox(row, textvariable=self.sup_preset_var, state='readonly',
                                  width=10, values=PRESET_NAMES)
        preset_box.pack(side='left')
        preset_box.bind('<<ComboboxSelected>>', lambda e: self._preset_to_checkboxes())

        # the six independent DOF checkboxes -- this row IS "any boundary
        # condition the user pleases": a preset only pre-fills it, nothing
        # here is disabled or restricted by that choice.
        dof_row = tk.Frame(box, bg=BG)
        dof_row.pack(fill='x', padx=6, pady=4)
        self.dof_vars = {}
        for d, lbl in DOF_LABELS:
            v = tk.BooleanVar(value=False)
            self.dof_vars[d] = v
            tk.Checkbutton(dof_row, text=lbl, variable=v,
                          command=lambda: self.sup_preset_var.set('custom')
                          ).pack(side='left')
        self._preset_to_checkboxes()

        btn_row = tk.Frame(box, bg=BG)
        btn_row.pack(fill='x', padx=6, pady=(2, 6))
        tk.Button(btn_row, text='Apply to node', command=self._apply_support).pack(side='left', padx=2)
        tk.Button(btn_row, text='Remove support', command=self._remove_support).pack(side='left', padx=2)

        self.sup_list = tk.Listbox(box, height=6)
        self.sup_list.pack(fill='x', padx=6, pady=(0, 6))
        self.sup_list.bind('<<ListboxSelect>>', self._on_support_list_select)

    def _build_loads_panel(self, parent):
        box = tk.LabelFrame(parent, text='Nodal loads', bg=BG)
        box.pack(fill='x', padx=6, pady=4)

        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=6, pady=2)
        tk.Label(row, text='Node:', bg=BG, width=10, anchor='w').pack(side='left')
        self.ld_node_var = tk.IntVar(value=0)
        tk.Entry(row, textvariable=self.ld_node_var, width=6).pack(side='left')

        self.ld_fx = tk.DoubleVar(value=0.0)
        self.ld_fy = tk.DoubleVar(value=0.0)
        self.ld_fz = tk.DoubleVar(value=-10.0)
        self.ld_mx = tk.DoubleVar(value=0.0)
        self.ld_my = tk.DoubleVar(value=0.0)
        self.ld_mz = tk.DoubleVar(value=0.0)
        for lbl, var in (('Fx:', self.ld_fx), ('Fy:', self.ld_fy), ('Fz:', self.ld_fz),
                         ('Mx:', self.ld_mx), ('My:', self.ld_my), ('Mz:', self.ld_mz)):
            self._labeled_entry(box, lbl, var)

        btn_row = tk.Frame(box, bg=BG)
        btn_row.pack(fill='x', padx=6, pady=(2, 6))
        tk.Button(btn_row, text='Add/update load', command=self._apply_load).pack(side='left', padx=2)
        tk.Button(btn_row, text='Remove load', command=self._remove_load).pack(side='left', padx=2)

        self.load_list = tk.Listbox(box, height=6)
        self.load_list.pack(fill='x', padx=6, pady=(0, 6))

    def _build_results_panel(self, parent):
        box = tk.LabelFrame(parent, text='Results', bg=BG)
        box.pack(fill='both', padx=6, pady=4, expand=False)
        self.results_text = tk.Text(box, height=10, width=42, wrap='word')
        self.results_text.pack(fill='both', padx=6, pady=6)

        self.checks_list = tk.Listbox(box, height=8)
        self.checks_list.pack(fill='x', padx=6, pady=(0, 6))

    # ── generator ────────────────────────────────────────────────────────────
    def _on_generator_change(self):
        for frame in self._param_frames.values():
            frame.pack_forget()
        self._param_frames[self.generator.get()].pack(fill='x')

    def _generate(self, push_undo=True):
        gen = self.generator.get()
        try:
            if gen == 'flat_grid':
                mesh = sg.flat_grid(self.fg_span_x.get(), self.fg_span_y.get(),
                                    self.fg_depth.get(), self.fg_module.get(),
                                    offset=self.fg_offset.get())
            elif gen == 'barrel_vault':
                mesh = sg.barrel_vault(self.bv_span.get(), self.bv_rise.get(),
                                       self.bv_length.get(), int(self.bv_n_arch.get()),
                                       int(self.bv_n_bays.get()), self.bv_double.get(),
                                       self.bv_depth.get())
            else:
                mesh = sg.dome(self.dm_radius.get(), self.dm_rise.get(),
                               int(self.dm_n_rings.get()), int(self.dm_n_sectors.get()))
        except ValueError as exc:
            messagebox.showerror('Generator error', str(exc))
            return

        if push_undo:
            self._push_undo('generate ' + gen)
        self.nodes = mesh['nodes']
        self.members = mesh['members']
        self._apply_section_to_all(members=self.members, redraw=False)
        self.supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
        self.loads = []
        self.results = None
        self.member_checks = None
        self.selected_node = None
        self._refresh_all()

    def _apply_section_to_all(self, members=None, redraw=True):
        members = self.members if members is None else members
        if redraw:
            self._push_undo('apply section')
        conn = self.sec_conn.get()
        for m in members:
            m['conn'] = conn
            m['E'] = self.sec_E.get()
            m['A'] = self.sec_A.get()
            m['I'] = self.sec_I.get()
            m['J'] = self.sec_J.get()
            m['Fy'] = self.sec_Fy.get()
            m['Fu'] = self.sec_Fu.get()
            m['K'] = self.sec_K.get()
            m['r_gyr'] = self.sec_r_gyr.get()
        if redraw:
            self.results = None
            self.member_checks = None
            self._refresh_all()

    # ── boundary conditions ──────────────────────────────────────────────────
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

    # ── analysis ─────────────────────────────────────────────────────────────
    def _analyze(self):
        loads = list(self.loads)
        if self.self_weight_on.get():
            loads = sm.combine_loads(loads, sm.self_weight_loads(
                self.nodes, self.members, self.unit_weight_var.get()))
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

    # ── camera / drawing ─────────────────────────────────────────────────────
    def _rotate(self, d_az, d_el):
        self.azimuth = (self.azimuth + d_az) % 360.0
        self.elevation = max(-89.0, min(89.0, self.elevation + d_el))
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

    def _draw(self):
        c = self.canvas
        c.delete('all')
        if not self.nodes:
            return
        proj = [self._project(x, y, z) for x, y, z in self.nodes]

        # centre the view on the model's own projected bounding box the
        # first time it is drawn at this geometry, so a freshly generated
        # mesh is visible without the user having to hunt for it with pan.
        xs = [p[0] for p in proj]; ys = [p[1] for p in proj]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0

        def to_screen(px, py):
            wx = (px - cx) * self.PX_PER_M
            wy = (py - cy) * self.PX_PER_M
            return self.zc.w2s(wx, wy)

        order = sorted(range(len(self.members)), key=lambda i: -(
            proj[self.members[i]['a']][2] + proj[self.members[i]['b']][2]))
        for i in order:
            m = self.members[i]
            ax, ay, _ = proj[m['a']]
            bx, by, _ = proj[m['b']]
            sx0, sy0 = to_screen(ax, ay)
            sx1, sy1 = to_screen(bx, by)
            color = MEMBER_RIGID_COLOR if m.get('conn') == 'rigid' else MEMBER_PIN_COLOR
            width = 2
            if self.results is not None and i < len(self.results['member_res']):
                N = self.results['member_res'][i]['N']
                color = TENSION_COLOR if N >= 0 else COMPRESSION_COLOR
                if self.member_checks and self.member_checks[i].get('checked') and \
                   self.member_checks[i]['util'] > 1.0:
                    color = OVER_COLOR
                    width = 3
            c.create_line(sx0, sy0, sx1, sy1, fill=color, width=width, tags='member')

        support_nodes = {s['node'] for s in self.supports
                         if any(sm.support_restraints(s).values())}
        for i, (px, py, _) in enumerate(proj):
            sx, sy = to_screen(px, py)
            r = 5 if i == self.selected_node else 4
            color = NODE_SEL_COLOR if i == self.selected_node else (
                SUPPORT_COLOR if i in support_nodes else NODE_COLOR)
            c.create_oval(sx - r, sy - r, sx + r, sy + r, fill=color, outline='', tags=('node', f'node{i}'))

        labels = []
        for i, (px, py, _) in enumerate(proj):
            sx, sy = to_screen(px, py)
            labels.append(c.create_text(sx + 8, sy - 8, text=str(i), anchor='w',
                                        font=('Helvetica', 7), fill='#555'))
        declutter_text(c, labels)

        self._to_screen_cache = to_screen  # for hit-testing on click

    def _on_canvas_click(self, event):
        if not self.nodes or not hasattr(self, '_to_screen_cache'):
            return
        proj = [self._project(x, y, z) for x, y, z in self.nodes]
        xs = [p[0] for p in proj]; ys = [p[1] for p in proj]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
        best, best_d = None, 12.0
        for i, (px, py, _) in enumerate(proj):
            wx = (px - cx) * self.PX_PER_M
            wy = (py - cy) * self.PX_PER_M
            sx, sy = self.zc.w2s(wx, wy)
            d = math.hypot(sx - event.x, sy - event.y)
            if d < best_d:
                best, best_d = i, d
        if best is not None:
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
            self.sup_list.insert(tk.END, f"node {s['node']:>3}  {s.get('type') or 'custom':<8} {flags}")

    def _refresh_load_list(self):
        self.load_list.delete(0, tk.END)
        for ld in self.loads:
            self.load_list.insert(
                tk.END,
                f"node {ld['node']:>3}  Fx={ld.get('fx', 0):.2f} Fy={ld.get('fy', 0):.2f} "
                f"Fz={ld.get('fz', 0):.2f} kN")

    def _refresh_results_text(self):
        self.results_text.delete('1.0', tk.END)
        text = sr.summary_text(self.nodes, self.members, self.results, self.member_checks)
        self.results_text.insert('1.0', text)

        self.checks_list.delete(0, tk.END)
        if self.member_checks:
            order = sorted(range(len(self.member_checks)),
                           key=lambda i: -(self.member_checks[i]['util'] or -1
                                          if self.member_checks[i].get('checked') else -1))
            for i in order:
                chk = self.member_checks[i]
                m = self.members[i]
                if not chk.get('checked'):
                    continue
                flag = '  OVER!' if chk['util'] > 1.0 else ''
                self.checks_list.insert(
                    tk.END, f"member {i} ({m['a']}-{m['b']}) {chk['mode']:<11} "
                            f"util={chk['util']:.2f}{flag}")

    # ── Excel ────────────────────────────────────────────────────────────────
    def _export_excel(self):
        path = filedialog.asksaveasfilename(defaultextension='.xlsx',
                                            filetypes=[('Excel workbook', '*.xlsx')])
        if not path:
            return
        try:
            sr.export_excel(self.nodes, self.members, self.loads, self.supports,
                            self.results, path, checks=self.member_checks,
                            meta={'generator': self.generator.get()})
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
        self.results = None
        self.member_checks = None
        self.selected_node = None
        self._refresh_all()

    # ── units ────────────────────────────────────────────────────────────────
    def _on_units_changed(self):
        self._refresh_all()
