"""shell_app.py -- Tkinter controller for the Shell tab. 2026-09-14.

A reinforced-concrete shell designer with a GeoGebra-like "algebra view":

  * Definitions (left, first page): numbers with sliders and functions of
    (x, y), typed the way GeoGebra takes them. The surface is whatever
    function is picked as the surface (z by default), the thickness likewise
    (t). Moving a slider redraws the surface at once; the analysis runs when
    asked for.
  * Supports, edge beams, columns; load cases, loads (any of them a formula
    in x, y) and the CIRSOC 102 wind calculator; the design code and the
    thickness tools -- on the other pages.
  * A shaded 3-D view coloured by any result, orbit / zoom / pan, click an
    element to read all its numbers, section cuts.
  * The design first SHOWS where the shell must be thicker; automatic
    thickening runs only when its toggle is on (the user's choice).

Every number comes from shell_model / shell_design / shell_reports; this
file only builds widgets, converts units at the boundary, and draws.
"""
import math
import os

import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import formula
import units
import view3d
from common import ZoomCanvas, ScrollPanel, UnitsMixin, _ensure_openpyxl
from apps.shell import shell_model as sm
from apps.shell import shell_design as sd
from apps.shell import shell_codes as codes
from apps.shell import shell_wind as wind
from apps.shell import shell_reports as rp
from apps.shell import shell_fe as fe

BG = '#f5f5f3'
TB = '#ebebea'
PANEL_W = 360
OK_C, BAD_C, NOTE_C = '#1a7a3a', '#c0392b', '#888888'

ENVELOPE_MAX = 'Envelope: max of all combinations'
ENVELOPE_MIN = 'Envelope: min of all combinations'

# name -> (source, key, colour scale, unit quantity or None)
FIELDS = {
    'Surface (shaded)': ('geom', None, None, None),
    'Height z': ('geom', 'z', 'sequential', 'length'),
    'Thickness t': ('geom', 't', 'sequential', 'section_length'),
    'Vertical deflection': ('disp', 'uz', 'diverging', 'deflection'),
    'Membrane Nx': ('force', 'Nx', 'diverging', 'line_load'),
    'Membrane Ny': ('force', 'Ny', 'diverging', 'line_load'),
    'Membrane shear Nxy': ('force', 'Nxy', 'diverging', 'line_load'),
    'Principal N1 (tension)': ('force', 'N1', 'diverging', 'line_load'),
    'Principal N2 (compression)': ('force', 'N2', 'diverging', 'line_load'),
    'Moment Mx': ('force', 'Mx', 'diverging', 'moment_per_length'),
    'Moment My': ('force', 'My', 'diverging', 'moment_per_length'),
    'Twisting Mxy': ('force', 'Mxy', 'diverging', 'moment_per_length'),
    'Transverse shear |Q|': ('force', 'Q', 'sequential', 'line_load'),
    'Utilisation (structural checks)': ('design', 'util_s', 'util', None),
    'Utilisation (worst check)': ('design', 'util', 'util', None),
    'Governing check': ('design', 'gov', 'categorical', None),
    'Thickness needed': ('design', 't_req', 'sequential', 'section_length'),
    'Thickness to add': ('design', 't_add', 'sequential', 'section_length'),
    'Steel x, top': ('design', 'x_top', 'sequential', 'steel_per_length'),
    'Steel y, top': ('design', 'y_top', 'sequential', 'steel_per_length'),
    'Steel x, bottom': ('design', 'x_bot', 'sequential', 'steel_per_length'),
    'Steel y, bottom': ('design', 'y_bot', 'sequential', 'steel_per_length'),
    'Steel x, central mesh': ('design', 'x_mid', 'sequential', 'steel_per_length'),
    'Steel y, central mesh': ('design', 'y_mid', 'sequential', 'steel_per_length'),
}
for _k in sd.CHECKS:
    FIELDS[f'Utilisation: {sd.CHECK_LABELS[_k]}'] = ('design', f'u_{_k}', 'util', None)
CHECK_COLOURS = {'steel': '#8e44ad', 'concrete': '#e67e22', 'bending': '#2980b9',
                 'shear': '#c0392b', 'buckling': '#16a085', 'spacing': '#95a5a6',
                 'punching': '#7b241c'}


# ═══════════════════════════════════════════════════════════════════════════
#  A small table + form for a list of records
# ═══════════════════════════════════════════════════════════════════════════
class RecordList(tk.Frame):
    """Records shown in a table; a form below adds, updates or deletes one.
    Field spec: dict(key, label, kind 'entry'|'combo', values (list or
    callable), q (unit quantity) and factor (storage value * factor = SI),
    num (bool), col (show as a table column), width)."""

    def __init__(self, master, app, title, fields, records, on_change, new_record, help=''):
        super().__init__(master, bg=BG)
        self.app, self.fields, self.records = app, fields, records
        self.on_change, self.new_record = on_change, new_record
        tk.Label(self, text=title, bg=BG, font=('Helvetica', 10, 'bold'),
                 anchor='w').pack(fill='x', pady=(8, 1))
        if help:
            tk.Label(self, text=help, bg=BG, fg='#666', font=('Helvetica', 8),
                     anchor='w', justify='left', wraplength=PANEL_W - 30).pack(fill='x')
        cols = [f['key'] for f in fields if f.get('col', True)]
        self.tree = ttk.Treeview(self, columns=cols, show='headings', height=4,
                                 selectmode='browse')
        for f in fields:
            if f.get('col', True):
                self.tree.column(f['key'], width=f.get('width', 6) * 9, stretch=True)
        self.tree.pack(fill='x')
        self.tree.bind('<<TreeviewSelect>>', lambda e: self._load_selected())
        form = tk.Frame(self, bg=BG)
        form.pack(fill='x', pady=2)
        self.vars, self.widgets, self.labels = {}, {}, {}
        for i, f in enumerate(fields):
            r, c = divmod(i, 2)
            lb = tk.Label(form, text=f['label'], bg=BG, font=('Helvetica', 9), anchor='w')
            lb.grid(row=r, column=2 * c, sticky='w', padx=(0, 2))
            self.labels[f['key']] = lb
            v = tk.StringVar(value='')
            if f.get('kind') == 'combo':
                w = ttk.Combobox(form, textvariable=v, width=f.get('width', 8),
                                 values=self._values(f))
            else:
                w = tk.Entry(form, textvariable=v, width=f.get('width', 8),
                             font=('Consolas', 9))
            w.grid(row=r, column=2 * c + 1, sticky='we', padx=(0, 6), pady=1)
            self.vars[f['key']], self.widgets[f['key']] = v, w
        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(3, weight=1)
        br = tk.Frame(self, bg=BG)
        br.pack(fill='x')
        for text, cmd, col in (('Add', self.add, '#1a6bbd'), ('Update', self.update_sel, '#1a6bbd'),
                               ('Delete', self.delete, '#a33')):
            tk.Button(br, text=text, command=cmd, relief='flat', bd=0, padx=6,
                      fg=col, font=('Helvetica', 9)).pack(side='left')
        self.msg = tk.Label(self, text='', bg=BG, fg=BAD_C, font=('Helvetica', 8),
                            anchor='w', wraplength=PANEL_W - 30, justify='left')
        self.msg.pack(fill='x')
        self._fill_form(self.new_record())
        self.refresh()

    def _values(self, f):
        v = f.get('values')
        return list(v()) if callable(v) else list(v or [])

    def _unit(self, f):
        return f' ({units.label(f["q"])})' if f.get('q') else ''

    def _show(self, f, v):
        if v is None or v == '':
            return ''
        if f.get('q') and f.get('num'):
            try:
                return '%g' % round(units.from_si(f['q'], float(v) * f.get('factor', 1.0)), 6)
            except (TypeError, ValueError):
                return str(v)
        return '%g' % v if isinstance(v, float) else str(v)

    def _store(self, f, text):
        text = text.strip()
        if f.get('num'):
            if text == '':
                return 0.0
            x = float(text)
            if f.get('q'):
                x = units.to_si(f['q'], x) / f.get('factor', 1.0)
            return x
        return text

    def refresh(self):
        for f in self.fields:
            if f.get('col', True):
                self.tree.heading(f['key'], text=f['label'] + self._unit(f))
            self.labels[f['key']].config(text=f['label'] + self._unit(f))
            if f.get('kind') == 'combo':
                self.widgets[f['key']].config(values=self._values(f))
        self.tree.delete(*self.tree.get_children())
        for i, rec in enumerate(self.records()):
            self.tree.insert('', 'end', iid=str(i),
                             values=[self._show(f, rec.get(f['key'], ''))
                                     for f in self.fields if f.get('col', True)])

    def _fill_form(self, rec):
        for f in self.fields:
            self.vars[f['key']].set(self._show(f, rec.get(f['key'], '')))

    def _load_selected(self):
        sel = self.tree.selection()
        if sel:
            self._fill_form(self.records()[int(sel[0])])

    def _read_form(self):
        rec = {}
        for f in self.fields:
            try:
                rec[f['key']] = self._store(f, self.vars[f['key']].get())
            except ValueError:
                raise ValueError(f'{f["label"]}: "{self.vars[f["key"]].get()}" is not a number')
        return rec

    def add(self):
        try:
            rec = dict(self.new_record())
            rec.update(self._read_form())
        except ValueError as exc:
            self.msg.config(text=str(exc))
            return
        self.msg.config(text='')
        self.records().append(rec)
        self.refresh()
        self.on_change()

    def update_sel(self):
        sel = self.tree.selection()
        if not sel:
            self.msg.config(text='Select a row to update.')
            return
        original = self.records()[int(sel[0])]
        rec = {}
        try:
            for f in self.fields:
                text = self.vars[f['key']].get()
                # a field left as displayed keeps its exact stored value
                if text == self._show(f, original.get(f['key'], '')):
                    continue
                try:
                    rec[f['key']] = self._store(f, text)
                except ValueError:
                    raise ValueError(f'{f["label"]}: "{text}" is not a number')
        except ValueError as exc:
            self.msg.config(text=str(exc))
            return
        self.msg.config(text='')
        original.update(rec)
        self.refresh()
        self.on_change()

    def delete(self):
        sel = self.tree.selection()
        if not sel:
            self.msg.config(text='Select a row to delete.')
            return
        del self.records()[int(sel[0])]
        self.refresh()
        self.on_change()


# ═══════════════════════════════════════════════════════════════════════════
#  The tab
# ═══════════════════════════════════════════════════════════════════════════
class ShellApp(UnitsMixin, tk.Frame):
    #: What the model fields hold (shell_model's docstring): f'c and fy in
    #: MPa; everything else as the app-wide storage convention.
    STORAGE_UNITS = units.storage_like(stress=units.MPA)

    def __init__(self, master):
        super().__init__(master, bg=BG)
        self.model = sm.ShellModel.preset(sm.DEFAULT_PRESET)
        self.res = self.des = None
        self.thicken_log = None
        self.geom = None
        self.sel = None
        self.error = ''
        self._si_fields = []
        self._redraw_pending = None
        self._def_rows = []

        self.v_preset = tk.StringVar(value=sm.DEFAULT_PRESET)
        self.v_field = tk.StringVar(value='Surface (shaded)')
        self.v_select = tk.StringVar(value=ENVELOPE_MAX)
        self.v_auto = tk.BooleanVar(value=False)
        self.v_mesh_lines = tk.BooleanVar(value=True)
        self.v_deformed = tk.BooleanVar(value=False)
        self.v_def_scale = tk.DoubleVar(value=1.0)
        self.v_principal = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='')

        self._build_ui()
        self.init_units(repaint=self._repaint_units)
        self._load_model_into_panels()
        self._rebuild_geometry(fit=True)

    # ── state used by the app-wide unit tests ──────────────────────────────
    def _current_state(self):
        return self.model.to_dict()

    # ══════════════════════════════════════════════════════════════════════
    #  Layout
    # ══════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        tb = tk.Frame(self, bg=TB)
        tb.pack(fill='x', padx=6, pady=(6, 0))
        tk.Label(tb, text='Preset:', bg=TB, font=('Helvetica', 10)).pack(side='left', padx=(4, 2))
        pc = ttk.Combobox(tb, textvariable=self.v_preset, state='readonly', width=34,
                          values=list(sm.PRESETS))
        pc.pack(side='left', pady=3)
        pc.bind('<<ComboboxSelected>>', lambda e: self.load_preset(self.v_preset.get()))
        tk.Button(tb, text='▶ Analyze & design', relief='flat', bd=0, padx=10, pady=4,
                  font=('Helvetica', 11, 'bold'), fg='#1a7a3a',
                  command=self.analyze).pack(side='left', padx=(10, 2))
        tk.Checkbutton(tb, text='Automatic thickening', variable=self.v_auto, bg=TB,
                       font=('Helvetica', 10), command=self._on_auto_toggle).pack(side='left', padx=4)
        tk.Button(tb, text='Clear thickening', relief='flat', bd=0, padx=6,
                  font=('Helvetica', 9), fg='#a33',
                  command=self.clear_thickening).pack(side='left')
        tk.Frame(tb, width=1, bg='#ccc').pack(side='left', fill='y', padx=6, pady=3)
        tk.Label(tb, text='Show:', bg=TB, font=('Helvetica', 10)).pack(side='left')
        self.field_box = ttk.Combobox(tb, textvariable=self.v_field, state='readonly', width=30,
                                      values=list(FIELDS))
        self.field_box.pack(side='left', padx=2)
        self.field_box.bind('<<ComboboxSelected>>', lambda e: self._draw())
        tk.Label(tb, text='for:', bg=TB, font=('Helvetica', 10)).pack(side='left')
        self.select_box = ttk.Combobox(tb, textvariable=self.v_select, state='readonly', width=34)
        self.select_box.pack(side='left', padx=2)
        self.select_box.bind('<<ComboboxSelected>>', lambda e: self._draw())

        tb2 = tk.Frame(self, bg=TB)
        tb2.pack(fill='x', padx=6)
        tk.Label(tb2, text='View:', bg=TB, font=('Helvetica', 10)).pack(side='left', padx=(4, 2))
        for name in view3d.VIEWS:
            tk.Button(tb2, text=name, relief='flat', bd=0, padx=6, font=('Helvetica', 10),
                      command=lambda n=name: self.set_view(n)).pack(side='left')
        tk.Button(tb2, text='Fit', relief='flat', bd=0, padx=6, font=('Helvetica', 10),
                  command=lambda: (self._fit(), self._draw())).pack(side='left')
        for text, var in (('mesh lines', self.v_mesh_lines), ('deformed', self.v_deformed),
                          ('principal directions', self.v_principal)):
            tk.Checkbutton(tb2, text=text, variable=var, bg=TB, font=('Helvetica', 9),
                           command=self._draw).pack(side='left', padx=(6, 0))
        tk.Scale(tb2, from_=0.2, to=5.0, resolution=0.1, orient='horizontal',
                 variable=self.v_def_scale, length=80, showvalue=False, bg=TB, bd=0,
                 highlightthickness=0, command=lambda _v: self._draw()).pack(side='left')
        tk.Frame(tb2, width=1, bg='#ccc').pack(side='left', fill='y', padx=6, pady=3)
        for text, cmd in (('Section cut…', self.open_section_cut), ('Report', self.open_report),
                          ('Export Excel', self._export_dialog),
                          ('Import Excel', self._import_dialog)):
            tk.Button(tb2, text=text, relief='flat', bd=0, padx=6, font=('Helvetica', 10),
                      fg='#1a6bbd', command=cmd).pack(side='left')

        body = tk.Frame(self, bg=BG)
        body.pack(fill='both', expand=True, padx=6, pady=6)
        left = tk.Frame(body, bg=BG, width=PANEL_W)
        left.pack(side='left', fill='y', padx=(0, 6))
        left.pack_propagate(False)
        self.nb = ttk.Notebook(left)
        self.nb.pack(fill='both', expand=True)
        self.pages = {}
        for name in ('Definitions', 'Supports', 'Loads', 'Design'):
            sp_ = ScrollPanel(self.nb, width=PANEL_W - 8, bg=BG)
            self.nb.add(sp_, text=name)
            self.pages[name] = sp_.interior

        pw = tk.PanedWindow(body, orient='vertical', sashwidth=5, bg=BG)
        pw.pack(side='left', fill='both', expand=True)
        self.zc = ZoomCanvas(pw, bg='white', highlightthickness=1)
        self.zc._on_zoom_changed = self._draw
        self.cam = view3d.Orbit3D(self.zc)
        self.cam.bind_orbit(on_change=self._draw, on_click=self._on_click)
        self.zc.canvas.bind('<Configure>', self._on_configure)
        pw.add(self.zc, stretch='always', minsize=200)
        info = tk.Frame(pw, bg=BG)
        self.info = tk.Text(info, height=9, font=('Consolas', 9), wrap='none', bg='#fbfbfa')
        ys = ttk.Scrollbar(info, orient='vertical', command=self.info.yview)
        self.info.configure(yscrollcommand=ys.set)
        ys.pack(side='right', fill='y')
        self.info.pack(fill='both', expand=True)
        pw.add(info, stretch='never', minsize=80, height=170)

        sb = tk.Frame(self, bg=TB)
        sb.pack(fill='x', side='bottom')
        tk.Label(sb, textvariable=self.status, bg=TB, anchor='w',
                 font=('Helvetica', 10)).pack(fill='x', padx=8, pady=3)

        self._build_definitions(self.pages['Definitions'])
        self._build_supports(self.pages['Supports'])
        self._build_loads(self.pages['Loads'])
        self._build_design(self.pages['Design'])

    # -- numeric fields whose model value is kept in SI -------------------------
    def _si_entry(self, parent, label, q, get_si, set_si, width=9, note=''):
        """A labelled entry showing a model value in the current units; the
        value is read back and stored on <Return> / focus-out."""
        row = tk.Frame(parent, bg=BG)
        row.pack(fill='x', pady=1)
        lb = tk.Label(row, text=label, bg=BG, width=20, anchor='w', font=('Helvetica', 9))
        lb.pack(side='left')
        v = tk.StringVar()
        e = tk.Entry(row, textvariable=v, width=width, font=('Consolas', 9))
        e.pack(side='left')
        ul = tk.Label(row, text='', bg=BG, fg='#666', font=('Helvetica', 8))
        ul.pack(side='left', padx=2)
        if note:
            tk.Label(row, text=note, bg=BG, fg='#888', font=('Helvetica', 8)).pack(side='left')
        rec = {'var': v, 'q': q, 'get': get_si, 'set': set_si, 'unit': ul}
        self._si_fields.append(rec)

        def commit(_e=None):
            # untouched box: keep the exact stored figure. Converting the
            # rounded display back would turn 30 MPa into 29.99999 after a
            # look at AISC -- the drift the unit layer exists to prevent.
            if v.get() == rec.get('shown'):
                return
            try:
                x = float(v.get())
            except ValueError:
                self.status.set(f'{label}: "{v.get()}" is not a number')
                self._paint_si(rec)
                return
            val = units.to_si(q, x) if q else x
            if abs(val - rec['get']()) > 1e-12 * max(1.0, abs(val)):
                rec['set'](val)
                self._model_changed()
        e.bind('<Return>', commit)
        e.bind('<FocusOut>', commit)
        self._paint_si(rec)
        return v

    def _paint_si(self, rec):
        try:
            val = rec['get']()
        except Exception:
            return
        shown = units.from_si(rec['q'], val) if rec['q'] else val
        rec['shown'] = '%g' % round(shown, 6)
        rec['var'].set(rec['shown'])
        rec['unit'].config(text=units.label(rec['q']) if rec['q'] else '')

    def _paint_all_si(self):
        for rec in self._si_fields:
            self._paint_si(rec)

    # ── Definitions page (the algebra view) ─────────────────────────────────
    def _build_definitions(self, p):
        tk.Label(p, text='Definitions', bg=BG, font=('Helvetica', 11, 'bold'),
                 anchor='w').pack(fill='x', pady=(6, 0))
        tk.Label(p, text='Type as in GeoGebra:  a = 10   ·   z(x, y) = c x y/(a b)   ·   '
                         't = 0.08 + 0.02 (x/a)^2.  Numbers get a slider. Names used: '
                         'the surface and the thickness below; loads may use any name, '
                         'plus x0 x1 y0 y1, qz and G.',
                 bg=BG, fg='#555', font=('Helvetica', 8), justify='left', anchor='w',
                 wraplength=PANEL_W - 30).pack(fill='x')
        self.def_frame = tk.Frame(p, bg=BG)
        self.def_frame.pack(fill='x', pady=(4, 2))
        ib = tk.Frame(p, bg=BG)
        ib.pack(fill='x', pady=2)
        tk.Label(ib, text='Input:', bg=BG, font=('Helvetica', 10, 'bold')).pack(side='left')
        self.v_input = tk.StringVar()
        ie = tk.Entry(ib, textvariable=self.v_input, font=('Consolas', 10))
        ie.pack(side='left', fill='x', expand=True, padx=2)
        ie.bind('<Return>', lambda e: self.add_definition(self.v_input.get()))
        tk.Button(ib, text='Add', relief='flat', bd=0, fg='#1a6bbd',
                  command=lambda: self.add_definition(self.v_input.get())).pack(side='left')

        rr = tk.Frame(p, bg=BG)
        rr.pack(fill='x', pady=(8, 2))
        tk.Label(rr, text='Surface is', bg=BG, font=('Helvetica', 9)).pack(side='left')
        self.v_surface = tk.StringVar()
        self.surf_box = ttk.Combobox(rr, textvariable=self.v_surface, width=7)
        self.surf_box.pack(side='left', padx=2)
        tk.Label(rr, text='thickness is', bg=BG, font=('Helvetica', 9)).pack(side='left')
        self.v_thick = tk.StringVar()
        self.thick_box = ttk.Combobox(rr, textvariable=self.v_thick, width=7)
        self.thick_box.pack(side='left', padx=2)
        for box, key, var in ((self.surf_box, 'surface', self.v_surface),
                              (self.thick_box, 'thickness', self.v_thick)):
            box.bind('<<ComboboxSelected>>', lambda e, k=key, v=var: self._set_role(k, v.get()))
            box.bind('<Return>', lambda e, k=key, v=var: self._set_role(k, v.get()))
        tk.Label(p, text='(thickness in metres)', bg=BG, fg='#888',
                 font=('Helvetica', 8), anchor='w').pack(fill='x')

        tk.Label(p, text='Plan (formulas allowed)', bg=BG, font=('Helvetica', 10, 'bold'),
                 anchor='w').pack(fill='x', pady=(8, 0))
        self.plan_vars = {}
        pr = tk.Frame(p, bg=BG)
        pr.pack(fill='x')
        for i, (k, lab) in enumerate((('x0', 'x from'), ('x1', 'to'), ('y0', 'y from'), ('y1', 'to'))):
            tk.Label(pr, text=lab, bg=BG, font=('Helvetica', 9)).grid(row=i // 2, column=2 * (i % 2), sticky='w')
            v = tk.StringVar()
            e = tk.Entry(pr, textvariable=v, width=10, font=('Consolas', 9))
            e.grid(row=i // 2, column=2 * (i % 2) + 1, padx=2, pady=1)
            e.bind('<Return>', lambda ev, key=k: self._set_plan(key))
            e.bind('<FocusOut>', lambda ev, key=k: self._set_plan(key))
            self.plan_vars[k] = v
        tk.Label(p, text='(metres — formulas in the definitions are always in metres)',
                 bg=BG, fg='#888', font=('Helvetica', 8), anchor='w').pack(fill='x')
        self._si_entry(p, 'Element size', 'length',
                       lambda: float(self.model.data['mesh'].get('size') or 0.5),
                       lambda v: self.model.data['mesh'].__setitem__('size', max(v, 0.05)))
        self.mesh_note = tk.Label(p, text='', bg=BG, fg='#666', font=('Helvetica', 8), anchor='w')
        self.mesh_note.pack(fill='x')

    def _rebuild_def_rows(self):
        for w in self.def_frame.winfo_children():
            w.destroy()
        self._def_rows = []
        ws = self.model.ws
        for i, d in enumerate(ws.defs):
            row = tk.Frame(self.def_frame, bg=BG)
            row.pack(fill='x', pady=1)
            dot = tk.Label(row, text='●', bg=BG, font=('Helvetica', 10))
            dot.pack(side='left')
            v = tk.StringVar(value=d.text)
            e = tk.Entry(row, textvariable=v, font=('Consolas', 10), relief='flat')
            e.pack(side='left', fill='x', expand=True)
            e.bind('<Return>', lambda ev, idx=i, var=v: self.edit_definition(idx, var.get()))
            e.bind('<FocusOut>', lambda ev, idx=i, var=v: self.edit_definition(idx, var.get()))
            tk.Button(row, text='×', relief='flat', bd=0, fg='#a33', font=('Helvetica', 10),
                      command=lambda idx=i: self.delete_definition(idx)).pack(side='left')
            rec = {'def': d, 'var': v, 'dot': dot, 'entry': e, 'scale': None, 'err': None}
            if d.kind == formula.NUMBER and d.free:
                lo, hi, step = ws.sliders.get(d.name, formula.default_slider(d.value))
                srow = tk.Frame(self.def_frame, bg=BG)
                srow.pack(fill='x')
                tk.Label(srow, text='   ', bg=BG).pack(side='left')
                sv = tk.DoubleVar(value=d.value)
                sc = tk.Scale(srow, from_=lo, to=hi, resolution=step, orient='horizontal',
                              variable=sv, showvalue=False, length=PANEL_W - 110, bg=BG,
                              bd=0, highlightthickness=0,
                              command=lambda val, name=d.name: self.move_slider(name, float(val)))
                sc.pack(side='left')
                tk.Button(srow, text='⋯', relief='flat', bd=0, fg='#1a6bbd',
                          command=lambda name=d.name: self._slider_range_dialog(name)).pack(side='left')
                rec['scale'], rec['svar'] = sc, sv
            err = tk.Label(self.def_frame, text='', bg=BG, fg=BAD_C, font=('Helvetica', 8),
                           anchor='w', wraplength=PANEL_W - 40, justify='left')
            err.pack(fill='x')
            rec['err'] = err
            self._def_rows.append(rec)
        self._refresh_def_status()

    def _refresh_def_status(self):
        for rec in self._def_rows:
            d = rec['def']
            colour = {formula.NUMBER: OK_C, formula.FUNCTION: OK_C,
                      formula.COMMENT: NOTE_C}.get(d.kind, BAD_C)
            rec['dot'].config(fg=colour)
            if rec['var'].get() != d.text:
                rec['var'].set(d.text)
            rec['entry'].config(fg=NOTE_C if d.kind == formula.COMMENT else '#111')
            rec['err'].config(text=d.error if d.kind == formula.ERROR else '')
        names_f = [d.name for d in self.model.ws.defs if d.kind in (formula.FUNCTION, formula.NUMBER)]
        self.surf_box.config(values=names_f)
        self.thick_box.config(values=names_f)

    def _definitions_changed(self, rebuild=True):
        self.model.sync()
        if rebuild:
            self._rebuild_def_rows()
        else:
            self._refresh_def_status()
        self._model_changed()

    def add_definition(self, text):
        if not text.strip():
            return
        n_before = len(self.model.ws.defs)
        self.model.ws.add_line(text)
        self.v_input.set('')
        self._definitions_changed(rebuild=True)
        if len(self.model.ws.defs) == n_before:
            self.status.set(f'Redefined: {text}')

    def edit_definition(self, index, text):
        ws = self.model.ws
        if index >= len(ws.defs) or ws.defs[index].text == text.strip():
            return
        ws.set_line(index, text)
        self._definitions_changed(rebuild=True)

    def delete_definition(self, index):
        self.model.ws.remove(index)
        self._definitions_changed(rebuild=True)

    def move_slider(self, name, value):
        ws = self.model.ws
        d = ws.get(name)
        if d is None or (d.value is not None and abs(d.value - value) < 1e-12):
            return
        ws.set_number(name, value)
        self._definitions_changed(rebuild=False)

    def _slider_range_dialog(self, name):
        ws = self.model.ws
        lo, hi, step = ws.sliders.get(name, [0.0, 1.0, 0.01])
        win = tk.Toplevel(self)
        win.title(f'Slider range: {name}')
        win.transient(self.winfo_toplevel())
        vs = []
        for lab, val in (('min', lo), ('max', hi), ('step', step)):
            r = tk.Frame(win)
            r.pack(fill='x', padx=10, pady=2)
            tk.Label(r, text=lab, width=6, anchor='w').pack(side='left')
            v = tk.StringVar(value='%g' % val)
            tk.Entry(r, textvariable=v, width=10).pack(side='left')
            vs.append(v)

        def ok():
            try:
                a, b, c = (float(v.get()) for v in vs)
            except ValueError:
                return
            if b <= a or c <= 0:
                return
            ws.sliders[name] = [a, b, c]
            win.destroy()
            self._definitions_changed(rebuild=True)
        tk.Button(win, text='OK', width=8, command=ok).pack(pady=6)
        return win

    def _set_role(self, key, name):
        name = name.strip()
        if name and self.model.data.get(key) != name:
            self.model.data[key] = name
            self._model_changed()

    def _set_plan(self, key):
        val = self.plan_vars[key].get().strip()
        if val and self.model.data['plan'].get(key) != val:
            self.model.data['plan'][key] = val
            self._model_changed()

    # ── Supports page ──────────────────────────────────────────────────────────
    def _build_supports(self, p):
        d = lambda: self.model.data  # noqa: E731
        self.rl_supports = RecordList(
            p, self, 'Supports',
            [dict(key='at', label='at', kind='combo', values=list(sm.SUPPORT_AT), width=11),
             dict(key='which', label='which', width=8),
             dict(key='type', label='holds', kind='combo', values=list(sm.SUPPORT_TYPES), width=8),
             dict(key='block', label='block', num=True, q='length', width=5)],
            lambda: d()['supports'], self._model_changed,
            lambda: {'at': 'corners', 'which': 'all', 'type': 'pinned', 'block': sm.DEFAULT_BLOCK},
            help='at: corners / low_corners / high_corners / edge / edges / point. '
                 'which: "all" or corner names x0y0,x1y1… for corners; x0/x1/y0/y1 for an '
                 'edge; "x, y" for a point. Point supports sit on a solid block of this size.')
        self.rl_supports.pack(fill='x')
        self.rl_beams = RecordList(
            p, self, 'Edge beams and ribs',
            [dict(key='line', label='line', kind='combo',
                  values=['edges', 'x0', 'x1', 'y0', 'y1', 'x=0', 'y=0'], width=8),
             dict(key='b', label='b', num=True, q='section_length', factor=0.01, width=5),
             dict(key='h', label='h', num=True, q='section_length', factor=0.01, width=5),
             dict(key='offset', label='position', kind='combo', values=list(sm.BEAM_OFFSETS), width=7)],
            lambda: d()['beams'], self._model_changed,
            lambda: {'line': 'edges', 'b': 25.0, 'h': 50.0, 'offset': 'below'},
            help='line: an edge, all edges, or x=<value> / y=<value> for a rib across the '
                 'shell (snapped to the nearest mesh line).')
        self.rl_beams.pack(fill='x')
        self.rl_columns = RecordList(
            p, self, 'Columns',
            [dict(key='x', label='x', width=6), dict(key='y', label='y', width=6),
             dict(key='height', label='height', num=True, q='length', width=5),
             dict(key='b', label='b', num=True, q='section_length', factor=0.01, width=5),
             dict(key='h', label='h', num=True, q='section_length', factor=0.01, width=5),
             dict(key='capital', label='head', num=True, q='length', width=5),
             dict(key='base', label='base', kind='combo', values=['fixed', 'pinned'], width=6)],
            lambda: d()['columns'], self._model_changed,
            lambda: {'x': '0', 'y': '0', 'height': 4.0, 'b': 50.0, 'h': 50.0,
                     'capital': 1.2, 'base': 'fixed'},
            help='x, y may be formulas. head: plan size of the solid column head '
                 '(capital) the shell thickens into.')
        self.rl_columns.pack(fill='x')

    # ── Loads page ─────────────────────────────────────────────────────────────
    def _build_loads(self, p):
        d = lambda: self.model.data  # noqa: E731
        self.rl_cases = RecordList(
            p, self, 'Load cases',
            [dict(key='name', label='name', width=6),
             dict(key='kind', label='kind', kind='combo', values=list(codes.KINDS), width=4)],
            lambda: d()['cases'], self._cases_changed,
            lambda: {'name': 'L', 'kind': 'L'})
        self.rl_cases.pack(fill='x')
        sw = tk.Frame(p, bg=BG)
        sw.pack(fill='x', pady=2)
        self.v_selfw = tk.BooleanVar(value=True)
        tk.Checkbutton(sw, text='Self-weight in case', variable=self.v_selfw, bg=BG,
                       font=('Helvetica', 9), command=self._self_weight_changed).pack(side='left')
        self.v_selfw_case = tk.StringVar()
        self.selfw_box = ttk.Combobox(sw, textvariable=self.v_selfw_case, width=6)
        self.selfw_box.pack(side='left')
        self.selfw_box.bind('<<ComboboxSelected>>', lambda e: self._self_weight_changed())
        self.rl_loads = RecordList(
            p, self, 'Loads (values in kN/m², may be formulas in x, y)',
            [dict(key='case', label='case', kind='combo',
                  values=lambda: [c['name'] for c in self.model.data['cases']], width=5),
             dict(key='type', label='type', kind='combo', values=list(sm.LOAD_TYPES), width=14),
             dict(key='value', label='value', width=16),
             dict(key='note', label='note', width=12),
             dict(key='x', label='x (point)', col=False, width=6),
             dict(key='y', label='y (point)', col=False, width=6),
             dict(key='Px', label='Px', num=True, q='force', factor=1e3, col=False, width=6),
             dict(key='Py', label='Py', num=True, q='force', factor=1e3, col=False, width=6),
             dict(key='Pz', label='P down', num=True, q='force', factor=1e3, col=False, width=6)],
            lambda: d()['loads'], self._model_changed,
            lambda: {'case': 'D', 'type': 'surface_vertical', 'value': '1.0', 'note': '',
                     'x': '0', 'y': '0', 'Px': 0.0, 'Py': 0.0, 'Pz': 0.0},
            help='Types: ' + '; '.join(f'{k}: {v}' for k, v in sm.LOAD_TYPES.items()))
        self.rl_loads.pack(fill='x')

        tk.Label(p, text='Wind — CIRSOC 102-2005 velocity pressure', bg=BG,
                 font=('Helvetica', 10, 'bold'), anchor='w').pack(fill='x', pady=(10, 0))
        w = lambda: self.model.data['wind']  # noqa: E731
        cr = tk.Frame(p, bg=BG)
        cr.pack(fill='x')
        tk.Label(cr, text='City (Fig. 1B)', bg=BG, width=20, anchor='w', font=('Helvetica', 9)).pack(side='left')
        self.v_city = tk.StringVar()
        cb = ttk.Combobox(cr, textvariable=self.v_city, state='readonly', width=18,
                          values=list(wind.CITY_V))
        cb.pack(side='left')
        cb.bind('<<ComboboxSelected>>', lambda e: self._set_city())
        tk.Label(p, text='  V is in m/s whatever the unit convention (CIRSOC 102 tabulates m/s)',
                 bg=BG, fg='#888', font=('Helvetica', 8), anchor='w').pack(fill='x')
        self._si_entry(p, 'Basic wind speed V (m/s)', None, lambda: float(w()['V']),
                       lambda v: w().__setitem__('V', v))
        self._si_entry(p, 'Height z', 'length', lambda: float(w()['z']),
                       lambda v: w().__setitem__('z', v))
        self.wind_combos = {}
        for key, label, vals in (('exposure', 'Exposure', list(wind.EXPOSURE)),
                                 ('category', 'Category (Tabla A-1)', list(wind.IMPORTANCE)),
                                 ('basis', 'Speed from CIRSOC 102-', list(codes.WIND_BASES))):
            r = tk.Frame(p, bg=BG)
            r.pack(fill='x', pady=1)
            tk.Label(r, text=label, bg=BG, width=20, anchor='w', font=('Helvetica', 9)).pack(side='left')
            v = tk.StringVar()
            b = ttk.Combobox(r, textvariable=v, state='readonly', width=8, values=vals)
            b.pack(side='left')
            b.bind('<<ComboboxSelected>>', lambda e, k=key, var=v: self._set_wind(k, var.get()))
            self.wind_combos[key] = v
        self._si_entry(p, 'Kzt (topography)', None, lambda: float(w()['Kzt']),
                       lambda v: w().__setitem__('Kzt', v))
        self._si_entry(p, 'Kd (directionality)', None, lambda: float(w()['Kd']),
                       lambda v: w().__setitem__('Kd', v))
        self._si_entry(p, 'G (gust)', None, lambda: float(w()['G']),
                       lambda v: w().__setitem__('G', v))
        self.qz_label = tk.Label(p, text='', bg=BG, font=('Consolas', 9), anchor='w',
                                 justify='left')
        self.qz_label.pack(fill='x')
        pr = tk.Frame(p, bg=BG)
        pr.pack(fill='x', pady=2)
        tk.Label(pr, text='Cp pattern', bg=BG, font=('Helvetica', 9)).pack(side='left')
        self.v_cp = tk.StringVar(value=list(wind.CP_PRESETS)[2])
        ttk.Combobox(pr, textvariable=self.v_cp, state='readonly', width=30,
                     values=list(wind.CP_PRESETS)).pack(side='left', padx=2)
        tk.Button(p, text='Add a wind case with this pattern', relief='flat', bd=0,
                  fg='#1a6bbd', font=('Helvetica', 9),
                  command=lambda: self.add_wind_case(self.v_cp.get())).pack(anchor='w')
        tk.Label(p, text=wind.CP_NOTE, bg=BG, fg='#a0522d', font=('Helvetica', 8),
                 wraplength=PANEL_W - 30, justify='left', anchor='w').pack(fill='x')

    def _cases_changed(self):
        names = [c['name'] for c in self.model.data['cases']]
        self.selfw_box.config(values=names)
        self.rl_loads.refresh()
        self._model_changed()

    def _self_weight_changed(self):
        self.model.data['self_weight'] = bool(self.v_selfw.get())
        if self.v_selfw_case.get():
            self.model.data['self_weight_case'] = self.v_selfw_case.get()
        self._model_changed()

    def _set_city(self):
        self.model.data['wind']['V'] = wind.CITY_V[self.v_city.get()]
        self._paint_all_si()
        self._model_changed()

    def _set_wind(self, key, val):
        self.model.data['wind'][key] = val
        self._model_changed()

    def add_wind_case(self, pattern):
        """Create a W case with a normal-pressure load qz G Cp(x, y)."""
        d = self.model.data
        names = {c['name'] for c in d['cases']}
        k = 1
        while f'W{k}' in names:
            k += 1
        name = f'W{k}'
        d['cases'].append({'name': name, 'kind': 'W'})
        d['loads'].append({'case': name, 'type': 'normal',
                           'value': f'qz*G*({wind.CP_PRESETS[pattern]})',
                           'note': f'wind: {pattern} (approximate Cp)'})
        self.rl_cases.refresh()
        self._cases_changed()
        self.status.set(f'Added wind case {name}: {pattern}')
        return name

    def _refresh_qz(self):
        try:
            q = self.model.wind_pressure() * 1e3          # N/m^2
            txt = (f'  qz = {units.from_si("area_load", q):.3f} {units.label("area_load")}'
                   f'   (Kz = {wind.Kz(self.model.data["wind"]["z"], self.model.data["wind"]["exposure"]):.3f})')
        except Exception as exc:
            txt = f'  {exc}'
        self.qz_label.config(text=txt)

    # ── Design page ──────────────────────────────────────────────────────────────
    def _build_design(self, p):
        d = lambda: self.model.data['design']  # noqa: E731
        mat = lambda: self.model.data['material']  # noqa: E731
        r = tk.Frame(p, bg=BG)
        r.pack(fill='x', pady=(6, 1))
        tk.Label(r, text='Code', bg=BG, font=('Helvetica', 10, 'bold')).pack(side='left')
        self.v_code = tk.StringVar()
        cb = ttk.Combobox(r, textvariable=self.v_code, state='readonly', width=36,
                          values=[codes.CODES[k].name for k in codes.CODE_ORDER])
        cb.pack(side='left', padx=4)
        cb.bind('<<ComboboxSelected>>', lambda e: self._set_code())
        tk.Label(p, text='CIRSOC 201-2024 has no shell chapter (C 1.2.10.7): shell rules '
                         'are taken from CIRSOC 201-2005 Ch. 19 until CIRSOC 201.03 is issued.',
                 bg=BG, fg='#a0522d', font=('Helvetica', 8), wraplength=PANEL_W - 30,
                 justify='left', anchor='w').pack(fill='x')
        self._si_entry(p, "Concrete f'c", 'stress', lambda: mat()['fc'] * 1e6,
                       lambda v: mat().__setitem__('fc', v / 1e6))
        self._si_entry(p, 'Steel fy', 'stress', lambda: mat()['fy'] * 1e6,
                       lambda v: mat().__setitem__('fy', v / 1e6))
        self._si_entry(p, 'Concrete unit weight', 'unit_weight', lambda: mat()['gamma'] * 1e3,
                       lambda v: mat().__setitem__('gamma', v / 1e3))
        self._si_entry(p, 'Cover', 'detail_length', lambda: d()['cover_cm'] / 100,
                       lambda v: d().__setitem__('cover_cm', v * 100))
        self.cover_note = tk.Label(p, text='', bg=BG, fg='#666', font=('Helvetica', 8), anchor='w')
        self.cover_note.pack(fill='x')
        self._si_entry(p, 'Mesh bar diameter', 'detail_length', lambda: d()['bar_mm'] / 1000,
                       lambda v: d().__setitem__('bar_mm', v * 1000))
        self.design_combos = {}
        for key, label, vals in (('layout', 'Reinforcement', ['auto', 'single', 'two']),
                                 ('exposure_factor', 'Exposure class factor', ['1.0', '1.3', '1.5'])):
            rr = tk.Frame(p, bg=BG)
            rr.pack(fill='x', pady=1)
            tk.Label(rr, text=label, bg=BG, width=20, anchor='w', font=('Helvetica', 9)).pack(side='left')
            v = tk.StringVar()
            b = ttk.Combobox(rr, textvariable=v, state='readonly', width=8, values=vals)
            b.pack(side='left')
            b.bind('<<ComboboxSelected>>', lambda e, k=key, var=v: self._set_design(k, var.get()))
            self.design_combos[key] = v
        tk.Label(p, text='  auto = two meshes where the thickness has room, one central '
                         'mesh elsewhere. Class factor: 1.3 for A3/Q1/C1, 1.5 for CL/M/C2/Q2/Q3.',
                 bg=BG, fg='#888', font=('Helvetica', 8), wraplength=PANEL_W - 30,
                 justify='left', anchor='w').pack(fill='x')
        self.design_checks = {}
        for key, label in (('exposed', 'Exposed to the weather'),
                           ('controlled', 'Execution under control (cover table)')):
            v = tk.BooleanVar()
            tk.Checkbutton(p, text=label, variable=v, bg=BG, font=('Helvetica', 9), anchor='w',
                           command=lambda k=key, var=v: self._set_design(k, bool(var.get()))
                           ).pack(fill='x')
            self.design_checks[key] = v
        self._si_entry(p, 'Buckling reduction', None, lambda: d()['buckling_factor'],
                       lambda v: d().__setitem__('buckling_factor', v), note='× classical')
        self._si_entry(p, 'Creep coefficient', None, lambda: d().get('creep', 0.0),
                       lambda v: d().__setitem__('creep', v), note='E/(1+φ) for buckling')
        self._si_entry(p, 'Deflection limit  L /', None, lambda: d()['deflection_limit'],
                       lambda v: d().__setitem__('deflection_limit', v))
        self._si_entry(p, 'Long-term multiplier', None, lambda: d()['longterm'],
                       lambda v: d().__setitem__('longterm', v))
        tk.Label(p, text='Thickness', bg=BG, font=('Helvetica', 10, 'bold'),
                 anchor='w').pack(fill='x', pady=(8, 0))
        for key, label in (('t_min', 'Smallest allowed'), ('t_max', 'Largest allowed'),
                           ('t_step', 'Step')):
            self._si_entry(p, label, 'section_length', lambda k=key: d()[k],
                           lambda v, k=key: d().__setitem__(k, v))
        self._si_entry(p, 'Taper (per metre)', None, lambda: d()['taper'],
                       lambda v: d().__setitem__('taper', v), note='m of thickness per m')
        br = tk.Frame(p, bg=BG)
        br.pack(fill='x', pady=4)
        tk.Button(br, text='Show where thicker is needed', relief='flat', bd=0, fg='#1a6bbd',
                  font=('Helvetica', 9), command=self.show_thickness_needed).pack(side='left')
        tk.Checkbutton(p, text='Automatic thickening (re-analyse until everything passes)',
                       variable=self.v_auto, bg=BG, font=('Helvetica', 9), anchor='w',
                       command=self._on_auto_toggle).pack(fill='x')
        self.rl_zones = RecordList(
            p, self, 'Thickening zones (you draw them)',
            [dict(key='rule', label='where', width=18),
             dict(key='t', label='t at least', num=True, q='section_length', width=6)],
            lambda: self.model.data['zones'], self._model_changed,
            lambda: {'rule': 'x^2 + y^2 < 1', 't': 0.15},
            help='where: a condition in x, y (e.g. abs(x) > a/2 - 1). The shell is at least '
                 'this thick wherever it holds.')
        self.rl_zones.pack(fill='x')

    def _set_code(self):
        name = self.v_code.get()
        for k, c in codes.CODES.items():
            if c.name == name:
                self.model.data['design']['code'] = k
        self._model_changed()

    def _set_design(self, key, val):
        if key == 'exposure_factor':
            val = float(val)
        self.model.data['design'][key] = val
        self._model_changed()

    def _refresh_cover_note(self):
        try:
            S = sd.DesignSettings(self.model)
            txt = (f'  minimum cover here {units.from_si("detail_length", S.cover_min):.3g} '
                   f'{units.label("detail_length")}; detailing minimum thickness '
                   f'{units.from_si("section_length", S.t_single_min):.3g} (one mesh) / '
                   f'{units.from_si("section_length", S.t_two_min):.3g} (two) '
                   f'{units.label("section_length")}')
            self.cover_note.config(text=txt, fg=BAD_C if S.cover < S.cover_min - 1e-9 else '#666')
        except Exception as exc:
            self.cover_note.config(text=str(exc), fg=BAD_C)

    # ══════════════════════════════════════════════════════════════════════
    #  Model <-> panels
    # ══════════════════════════════════════════════════════════════════════
    def _load_model_into_panels(self):
        d = self.model.data
        self.v_surface.set(d['surface'])
        self.v_thick.set(d['thickness'])
        for k, v in self.plan_vars.items():
            v.set(d['plan'][k])
        self.v_selfw.set(bool(d.get('self_weight', True)))
        self.v_selfw_case.set(d.get('self_weight_case', 'D'))
        self.selfw_box.config(values=[c['name'] for c in d['cases']])
        for k, v in self.wind_combos.items():
            v.set(str(d['wind'].get(k, '')))
        self.v_code.set(codes.CODES[d['design']['code']].name)
        self.design_combos['layout'].set(d['design'].get('layout', 'auto'))
        self.design_combos['exposure_factor'].set('%.1f' % float(d['design'].get('exposure_factor', 1.0)))
        for k, v in self.design_checks.items():
            v.set(bool(d['design'].get(k, True)))
        self.v_auto.set(bool(d['design'].get('auto_thicken', False)))
        for rl in (self.rl_supports, self.rl_beams, self.rl_columns, self.rl_cases,
                   self.rl_loads, self.rl_zones):
            rl.refresh()
        self._rebuild_def_rows()
        self._paint_all_si()
        self._refresh_qz()
        self._refresh_cover_note()

    def load_preset(self, name):
        self.model = sm.ShellModel.preset(name)
        self.v_preset.set(name)
        self._reset_results()
        self._load_model_into_panels()
        self._rebuild_geometry(fit=True)
        self.status.set(f'Preset loaded: {name}. Press Analyze & design.')

    def set_model(self, model):
        self.model = model
        self._reset_results()
        self._load_model_into_panels()
        self._rebuild_geometry(fit=True)

    def _reset_results(self):
        self.res = self.des = None
        self.thicken_log = None
        self.sel = None
        self._refresh_select_values()

    def _model_changed(self):
        """Any edit: the answer on screen is no longer the model's answer."""
        if self.res is not None:
            self.status.set('The model changed — press Analyze & design to update the results.')
        self.res = self.des = None
        self.thicken_log = None
        self._refresh_qz()
        self._refresh_cover_note()
        self._refresh_select_values()
        self._schedule_geometry()

    def _schedule_geometry(self):
        if self._redraw_pending is not None:
            try:
                self.after_cancel(self._redraw_pending)
            except tk.TclError:
                pass
        self._redraw_pending = self.after(25, self._rebuild_geometry)

    def _rebuild_geometry(self, fit=False):
        """Mesh the surface (no analysis) so the view follows every edit."""
        self._redraw_pending = None
        try:
            g = self.model.mesh()
            self.geom = g
            self.error = ''
            self.mesh_note.config(text=f'  {g["nx"]} × {g["ny"]} = {g["nx"] * g["ny"]} elements')
        except (sm.ModelError, formula.FormulaError) as exc:
            self.error = str(exc)
            self.status.set(f'Cannot draw the surface: {exc}')
        if fit and self.geom is not None:
            self._fit()
        self._draw()
        self._write_info()

    def _refresh_select_values(self):
        vals = [ENVELOPE_MAX, ENVELOPE_MIN]
        if self.res is not None:
            vals += [f'Combination {c.name}' for c in self.res.combos]
            vals += [f'Case {c}' for c in self.res.cases]
            vals.append(f'Service {self.res.service.name}')
        self.select_box.config(values=vals)
        if self.v_select.get() not in vals:
            self.v_select.set(ENVELOPE_MAX)

    # ══════════════════════════════════════════════════════════════════════
    #  Analysis
    # ══════════════════════════════════════════════════════════════════════
    def analyze(self):
        self.model.sync()
        self.model.data['design']['auto_thicken'] = bool(self.v_auto.get())
        self.status.set('Analysing…')
        self.update_idletasks()
        try:
            if self.v_auto.get():
                def progress(msg):
                    self.status.set('Thickening: ' + msg)
                    self.update_idletasks()
                self.res, self.des, self.thicken_log = sd.auto_thicken(self.model, progress=progress)
            else:
                self.res = self.model.analyze()
                self.des = sd.design(self.model, self.res)
                self.thicken_log = None
            self.error = ''
        except (sm.ModelError, fe.MechanismError, formula.FormulaError, ValueError) as exc:
            self.res = self.des = None
            self.error = str(exc)
            self.status.set('Analysis refused: ' + str(exc)[:160])
            self._refresh_select_values()
            self._write_info()
            self._draw()
            return False
        self.geom = self.res.fem['mesh']
        self._refresh_select_values()
        n_need = int(self.des.needs_thicker.sum() + self.des.cannot.sum())
        self.status.set(
            f'Analysed: {len(self.res.cases)} cases, {len(self.res.combos)} combinations. '
            + (f'{int(self.des.fails.sum())} elements fail; {n_need} need to be thicker — '
               'shown in "Thickness needed".' if n_need or self.des.fails.any()
               else 'Every element passes.'))
        if self.v_field.get() == 'Surface (shaded)':
            self.v_field.set('Utilisation (structural checks)')
        self._draw()
        self._write_info()
        return True

    def _on_auto_toggle(self):
        self.model.data['design']['auto_thicken'] = bool(self.v_auto.get())
        if self.v_auto.get():
            self.status.set('Automatic thickening is ON: Analyze will thicken where needed '
                            'and re-analyse until everything passes.')
        else:
            self.status.set('Automatic thickening is OFF: Analyze only shows where the '
                            'shell must be thicker.')

    def clear_thickening(self):
        sd.clear_thickening(self.model)
        self._model_changed()
        self.status.set('Automatic thickening cleared; the shell is back to t(x, y) and the zones.')

    def show_thickness_needed(self):
        if self.des is None and not self.analyze():
            return
        self.v_field.set('Thickness to add')
        self._draw()

    # ══════════════════════════════════════════════════════════════════════
    #  Field values
    # ══════════════════════════════════════════════════════════════════════
    def _selection(self):
        """('env_max'|'env_min'|'combo'|'case'|'service', object)."""
        s = self.v_select.get()
        if s == ENVELOPE_MIN:
            return 'env_min', None
        if s.startswith('Combination ') and self.res is not None:
            for c in self.res.combos:
                if s == f'Combination {c.name}':
                    return 'combo', c
        if s.startswith('Case ') and self.res is not None:
            name = s[5:]
            if name in self.res.cases:
                return 'case', self.res.cases.index(name)
        if s.startswith('Service ') and self.res is not None:
            return 'combo', self.res.service
        return 'env_max', None

    def _forces_for(self, kind, obj):
        res = self.res
        if kind == 'case':
            F = dict(res.per_case[obj])
        else:
            F = res.combo_forces(obj)
        N1, N2, _ = sm.principal(F['Nx'], F['Ny'], F['Nxy'])
        F['N1'], F['N2'] = N1, N2
        F['Q'] = np.hypot(F['Qx'], F['Qy'])
        return F

    def _uz_for(self, kind, obj):
        res = self.res
        U = res.U[:, obj] if kind == 'case' else res.combo_U(obj)
        nn = len(res.fem['mesh']['X'])
        uz = U.reshape(-1, 6)[:nn, 2]
        return uz[res.fem['mesh']['elems']].mean(axis=1)

    def field_values(self, name=None):
        """(values per element in SI or None, colour scale, unit quantity).
        None when the field needs results that do not exist."""
        name = name or self.v_field.get()
        src, key, scale, q = FIELDS[name]
        g = self.geom
        if g is None:
            return None, scale, q
        if src == 'geom':
            if key is None:
                return None, None, None
            if key == 'z':
                return g['X'][g['elems']][:, :, 2].mean(axis=1), scale, q
            t = self.res.fem['shells'].a if self.res is not None else g['t']
            return t, scale, q
        if self.res is None:
            return None, scale, q
        if src in ('force', 'disp'):
            kind, obj = self._selection()
            if kind in ('env_max', 'env_min'):
                combos = self.res.combos or [self.res.service]
                getter = (lambda c: self._forces_for('combo', c)[key]) if src == 'force' \
                    else (lambda c: self._uz_for('combo', c))
                stack = np.stack([getter(c) for c in combos])
                return (stack.max(axis=0) if kind == 'env_max' else stack.min(axis=0)), scale, q
            if src == 'force':
                return self._forces_for(kind, obj)[key], scale, q
            return self._uz_for(kind, obj), scale, q
        des = self.des
        if des is None:
            return None, scale, q
        if key == 'util':
            return des.util_max, scale, q
        if key == 'util_s':
            return des.util_structural, scale, q
        if key == 'gov':
            return des.governing, scale, q
        if key == 't_req':
            return des.t_req, scale, q
        if key == 't_add':
            return np.where(np.isfinite(des.t_req), np.maximum(des.t_req - des.t, 0.0), np.nan), scale, q
        if key.startswith('u_'):
            return des.util[key[2:]], scale, q
        return des.steel[key], scale, q

    # ══════════════════════════════════════════════════════════════════════
    #  Drawing
    # ══════════════════════════════════════════════════════════════════════
    def _nodes_for_view(self):
        g = self.geom
        X = g['X'].copy()
        if self.v_deformed.get() and self.res is not None:
            kind, obj = self._selection()
            if kind in ('env_max', 'env_min'):
                obj = self.res.combos[0] if self.res.combos else self.res.service
                kind = 'combo'
            U = self.res.U[:, obj] if kind == 'case' else self.res.combo_U(obj)
            nn = len(X)
            d = U.reshape(-1, 6)[:nn, :3]
            peak = float(np.abs(d).max()) or 1.0
            span = float(np.ptp(X, axis=0).max()) or 1.0
            X = X + d * (0.10 * span / peak) * float(self.v_def_scale.get())
        return X

    def _fit(self):
        if self.geom is None:
            return
        self.cam.fit(self.geom['X'])

    def set_view(self, name):
        self.cam.set_view(name)
        self._fit()
        self._draw()

    def _on_configure(self, _e=None):
        if not getattr(self, '_fitted', False) and self.zc.canvas.winfo_width() > 10 and self.geom:
            self._fit()
            self._fitted = True
        self._draw()

    def _draw(self):
        cv = self.zc.canvas
        cv.delete('all')
        g = self.geom
        if g is None:
            cv.create_text(20, 20, anchor='nw', text=self.error or 'No surface.', fill=BAD_C,
                           font=('Helvetica', 11))
            return
        X = self._nodes_for_view()
        el = g['elems']
        sx, sy = self.cam.project(X)
        cen = X[el].mean(axis=1)
        depth = self.cam.depth(cen)
        order = np.argsort(depth)                      # far first
        vals, scale, q = self.field_values()
        if vals is not None and scale == 'categorical':
            fills = [CHECK_COLOURS.get(str(v), '#bbb') for v in vals]
        elif vals is not None:
            fills, lo, hi = view3d.colours_for(vals, scale)
        else:
            fills = ['#d9d4c7'] * len(el)
        # lighting on the face normal
        a, b_ = X[el[:, 1]] - X[el[:, 0]], X[el[:, 3]] - X[el[:, 0]]
        nrm = np.cross(a, b_)
        nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-30
        # light fixed in the SCENE (from above, a little to one side), so
        # curvature reads as a change of shade as the model is orbited
        light = np.array([-0.45, -0.35, 0.82])
        light /= np.linalg.norm(light)
        lit = 0.30 + 0.75 * np.abs(nrm @ light) ** 1.5
        outline = self.v_mesh_lines.get()
        in_head = self.res.fem.get('in_head') if self.res is not None else None
        lim = 30000
        for e in order:
            idx = el[e]
            pts = np.stack([sx[idx], sy[idx]], axis=1)
            if np.abs(pts).max() > lim:
                continue
            col = fills[e]
            if vals is None:
                col = view3d.shade(col, lit[e])
            elif in_head is not None and in_head[e]:
                col = '#555555'
            cv.create_polygon(*pts.ravel(), fill=col,
                              outline='#6b6b6b' if outline else col, width=1,
                              tags=('face', f'e{e}'))
        self._draw_structure(X, sx, sy)
        if self.v_principal.get() and self.res is not None:
            self._draw_principal(X, cen)
        if self.sel is not None and self.sel < len(el):
            idx = el[self.sel]
            cv.create_polygon(*np.stack([sx[idx], sy[idx]], 1).ravel(), fill='',
                              outline='#ff00ff', width=3)
        if vals is not None:
            self._draw_legend(vals, scale, q)
        cv.create_text(10, cv.winfo_height() - 8 if cv.winfo_height() > 20 else 500, anchor='sw',
                       text='drag: orbit · wheel: zoom · middle-drag: pan · click: read an element',
                       fill='#999', font=('Helvetica', 8))

    def _draw_structure(self, X, sx, sy):
        """Edge beams, columns, supports and blocks (from the last analysis
        when there is one, else from the model data)."""
        cv = self.zc.canvas
        if self.res is None:
            return
        fem = self.res.fem
        Xall = fem['X']
        nn = len(X)
        for fr in fem['frames']:
            if fr.tag.startswith(('head', 'block')):
                continue
            a, b = fr.a, fr.b
            pa = X[a] if a < nn else Xall[a]
            pb = X[b] if b < nn else Xall[b]
            P = np.stack([pa + fr.off, pb + fr.off])
            px, py = self.cam.project(P)
            colour = '#1f7a4d' if fr.tag.startswith('column') else '#5b2c6f'
            cv.create_line(px[0], py[0], px[1], py[1], fill=colour, width=4 if fr.tag.startswith('column') else 3)
        for n, code in fem['support_nodes']:
            p = X[n] if n < nn else Xall[n]
            px, py = self.cam.project(p[None, :])
            x, y = px[0], py[0]
            cv.create_polygon(x, y, x - 7, y + 12, x + 7, y + 12, fill='#333' if code == '111111' else '#777',
                              outline='')

    def _draw_principal(self, X, cen):
        kind, obj = self._selection()
        if kind in ('env_max', 'env_min'):
            obj = self.res.combos[0] if self.res.combos else self.res.service
            kind = 'combo'
        F = self._forces_for(kind, obj)
        N1, N2, ang = sm.principal(F['Nx'], F['Ny'], F['Nxy'])
        e1, e2, _ = self.res.frame
        L = 0.35 * self.geom['h_el']
        big = max(np.abs(N1).max(), np.abs(N2).max(), 1e-9)
        cv = self.zc.canvas
        for i in range(len(cen)):
            for val, th in ((N1[i], ang[i]), (N2[i], ang[i] + math.pi / 2)):
                if abs(val) < 0.05 * big:
                    continue
                v = math.cos(th) * e1[i] + math.sin(th) * e2[i]
                s = L * (0.3 + 0.7 * abs(val) / big)
                P = np.stack([cen[i] - v * s, cen[i] + v * s])
                px, py = self.cam.project(P)
                cv.create_line(px[0], py[0], px[1], py[1],
                               fill='#b2182b' if val > 0 else '#2166ac', width=2)

    def _fmt_q(self, q, v):
        if q is None:
            return f'{v:.2f}'
        return f'{units.from_si(q, v):.3g}'

    def _draw_legend(self, vals, scale, q):
        cv = self.zc.canvas
        x0, y0 = 12, 12
        title = self.v_field.get()
        sel = '' if FIELDS[title][0] in ('geom', 'design') else f'  [{self.v_select.get()}]'
        unit = f' ({units.label(q)})' if q else ''
        cv.create_text(x0, y0, anchor='nw', text=title + unit + sel,
                       font=('Helvetica', 10, 'bold'), fill='#222')
        if scale == 'categorical':
            present = sorted(set(str(v) for v in vals))
            for i, k in enumerate(present):
                y = y0 + 22 + 16 * i
                cv.create_rectangle(x0, y, x0 + 14, y + 12, fill=CHECK_COLOURS.get(k, '#bbb'), outline='')
                cv.create_text(x0 + 20, y + 6, anchor='w', text=sd.CHECK_LABELS.get(k, k),
                               font=('Helvetica', 9))
            return
        finite = np.isfinite(np.asarray(vals, float))
        if not finite.any():
            cv.create_text(x0, y0 + 22, anchor='nw', text='(no values)', font=('Helvetica', 9))
            return
        _, lo, hi = view3d.colours_for(vals, scale)
        stops = view3d.legend_stops(scale, lo, hi, 7)
        for i, (v, c) in enumerate(reversed(stops)):
            y = y0 + 22 + 18 * i
            cv.create_rectangle(x0, y, x0 + 16, y + 18, fill=c, outline='')
            cv.create_text(x0 + 22, y + 9, anchor='w', text=self._fmt_q(q, v), font=('Helvetica', 9))
        v = np.asarray(vals, float)[finite]
        cv.create_text(x0, y0 + 22 + 18 * 7 + 4, anchor='nw',
                       text=f'min {self._fmt_q(q, v.min())}  max {self._fmt_q(q, v.max())}',
                       font=('Helvetica', 9), fill='#444')
        if (~finite).any():
            cv.create_text(x0, y0 + 22 + 18 * 7 + 20, anchor='nw',
                           text='grey: not applicable / cannot pass', font=('Helvetica', 8), fill='#777')

    # ══════════════════════════════════════════════════════════════════════
    #  Reading an element
    # ══════════════════════════════════════════════════════════════════════
    def _on_click(self, e):
        if self.geom is None:
            return
        X = self._nodes_for_view()
        cen = X[self.geom['elems']].mean(axis=1)
        sx, sy = self.cam.project(cen)
        d2 = (sx - e.x) ** 2 + (sy - e.y) ** 2
        depth = self.cam.depth(cen)
        near = np.nonzero(d2 < 40 ** 2)[0]
        if not len(near):
            self.sel = None
        else:
            # nearest on screen, preferring the face nearer the viewer
            self.sel = int(near[np.argmin(d2[near] - 1e-3 * depth[near])])
        self._draw()
        self._write_info()

    def element_report(self, e):
        g = self.geom
        c = g['centroids'][e] if 'centroids' in g else g['X'][g['elems'][e]].mean(axis=0)
        L = [f'Element {e} at x = {c[0]:.2f}, y = {c[1]:.2f}, z = {c[2]:.2f} m']
        if self.res is None:
            t = g['t'][e]
            L.append(f'  thickness {self._fmt_q("section_length", t)} {units.label("section_length")}'
                     '  (analyse for forces and design)')
            return L
        des, res = self.des, self.res
        su = units.label('section_length')
        L.append(f'  thickness {self._fmt_q("section_length", des.t[e])} {su}; needed '
                 + (f'{self._fmt_q("section_length", des.t_req[e])} {su}' if np.isfinite(des.t_req[e])
                    else 'more than the maximum')
                 + ('   [inside a column head / support block]' if res.fem['in_head'][e] else ''))
        kind, obj = self._selection()
        if kind in ('env_max', 'env_min'):
            kind, obj = 'combo', max(res.combos, key=lambda cb: np.abs(res.combo_forces(cb)['Nxy'][e]))
            L.append(f'  forces for {obj.name} (largest shear here):')
        else:
            L.append(f'  forces for {self.v_select.get()}:')
        F = self._forces_for(kind, obj)
        ll, mm = units.label('line_load'), units.label('moment_per_length')
        L.append('   N  x {} y {} xy {} {}   N1 {} N2 {}'.format(
            *(self._fmt_q('line_load', F[k][e]) for k in ('Nx', 'Ny', 'Nxy')), ll,
            self._fmt_q('line_load', F['N1'][e]), self._fmt_q('line_load', F['N2'][e])))
        L.append('   M  x {} y {} xy {} {}   (+ = tension at the bottom face)'.format(
            *(self._fmt_q('moment_per_length', F[k][e]) for k in ('Mx', 'My', 'Mxy')), mm))
        L.append(f'   Q  {self._fmt_q("line_load", F["Q"][e])} {ll}')
        L.append('  utilisation (worst combination):')
        for k in sd.CHECKS:
            u = des.util[k][e]
            ci = des.gov_combo[k][e]
            cname = res.combos[ci].name if res.combos else ''
            L.append(f'   {sd.CHECK_LABELS[k]:48s} {u:5.2f}   {cname}')
        sp = units.label('steel_per_length')
        parts = []
        for k, lab in (('x_top', 'x top'), ('y_top', 'y top'), ('x_bot', 'x bot'),
                       ('y_bot', 'y bot'), ('x_mid', 'x mid'), ('y_mid', 'y mid')):
            v = des.steel[k][e]
            if np.isfinite(v):
                db, s = sd.suggest_bars(v, des.t[e], des.S)
                bars = f' ({db:.0f} mm @ {s:.0f})' if db else ' (does not fit)'
                parts.append(f'{lab} {self._fmt_q("steel_per_length", v)}{bars}')
        L.append(f'  steel {sp}: ' + '; '.join(parts))
        return L

    def _write_info(self):
        t = self.info
        t.config(state='normal')
        t.delete('1.0', 'end')
        if self.error:
            t.insert('end', 'PROBLEM: ' + self.error + '\n\n', 'bad')
        if self.sel is not None and self.geom is not None and self.sel < len(self.geom['elems']):
            t.insert('end', '\n'.join(self.element_report(self.sel)) + '\n\n')
        if self.des is not None:
            t.insert('end', '\n'.join(self.des.summary()) + '\n')
            for p in getattr(self.des, 'punching', []):
                what = 'column head' if p['kind'] == 'column' else 'support block'
                t.insert('end', f'{what} at ({p["xy"][0]:.2f}, {p["xy"][1]:.2f}): shear into it '
                                f'{units.from_si("force", p["Vu"]):.1f} {units.label("force")}, '
                                f'utilisation {p["util"]:.2f}, needs '
                                f'{self._fmt_q("section_length", p["t_req"])} '
                                f'{units.label("section_length")} around it'
                                + ('  (MESH TOO COARSE for this block)' if p['coarse'] else '') + '\n')
            if self.thicken_log:
                t.insert('end', 'Automatic thickening: ' + ' | '.join(self.thicken_log) + '\n')
        elif not self.error:
            t.insert('end', 'Edit the definitions or drag a slider — the surface follows. '
                            'Press "Analyze & design" for forces, steel and the thickness needed.\n')
        t.tag_config('bad', foreground=BAD_C)
        t.config(state='disabled')

    # ══════════════════════════════════════════════════════════════════════
    #  Section cut
    # ══════════════════════════════════════════════════════════════════════
    def section_values(self, axis, pos, name):
        """(positions along the cut, values) for the elements the line
        axis = pos crosses. axis 'x' means the line x = pos (values along y)."""
        g = self.geom
        vals, _, _ = self.field_values(name)
        if vals is None:
            return None, None
        c = g['X'][g['elems']].mean(axis=1)
        if axis == 'x':
            xs = g['xs']
            i = int(np.clip(np.searchsorted(xs, pos) - 1, 0, len(xs) - 2))
            sel = np.arange(g['ny']) * g['nx'] + i
            return c[sel, 1], np.asarray(vals)[sel]
        ys = g['ys']
        j = int(np.clip(np.searchsorted(ys, pos) - 1, 0, len(ys) - 2))
        sel = j * g['nx'] + np.arange(g['nx'])
        return c[sel, 0], np.asarray(vals)[sel]

    def open_section_cut(self):
        win = tk.Toplevel(self)
        win.title('Section cut')
        win.geometry('720x420')
        top = tk.Frame(win)
        top.pack(fill='x', padx=6, pady=4)
        v_axis = tk.StringVar(value='y')
        v_pos = tk.StringVar(value='0')
        v_f = tk.StringVar(value='Membrane shear Nxy')
        tk.Label(top, text='Cut along the line').pack(side='left')
        ttk.Combobox(top, textvariable=v_axis, values=['x', 'y'], width=3, state='readonly').pack(side='left')
        tk.Label(top, text='=').pack(side='left')
        tk.Entry(top, textvariable=v_pos, width=8).pack(side='left')
        tk.Label(top, text='m   show').pack(side='left')
        ttk.Combobox(top, textvariable=v_f, width=30, state='readonly',
                     values=[k for k, v in FIELDS.items() if v[0] != 'geom' or v[1]]).pack(side='left')
        cv = tk.Canvas(win, bg='white')
        cv.pack(fill='both', expand=True)

        def draw(*_a):
            cv.delete('all')
            try:
                pos = self.model.ws.scalar(v_pos.get())
            except formula.FormulaError as exc:
                cv.create_text(20, 20, anchor='nw', text=str(exc), fill=BAD_C)
                return
            s, v = self.section_values(v_axis.get(), pos, v_f.get())
            if s is None:
                cv.create_text(20, 20, anchor='nw', text='Analyse first.', fill=BAD_C)
                return
            q = FIELDS[v_f.get()][3]
            v = np.asarray(v, float)
            vv = np.array([units.from_si(q, x) if q else x for x in v])
            W, H = max(cv.winfo_width(), 400), max(cv.winfo_height(), 250)
            m = 50
            fin = np.isfinite(vv)
            lo = min(0.0, np.nanmin(vv[fin])) if fin.any() else 0.0
            hi = max(0.0, np.nanmax(vv[fin])) if fin.any() else 1.0
            if hi - lo < 1e-12:
                hi = lo + 1
            X_ = lambda a: m + (a - s.min()) / max(np.ptp(s), 1e-9) * (W - 2 * m)  # noqa: E731
            Y_ = lambda b: H - m - (b - lo) / (hi - lo) * (H - 2 * m)  # noqa: E731
            cv.create_line(m, Y_(0), W - m, Y_(0), fill='#999')
            pts = [c for a, b in zip(s, vv) if np.isfinite(b) for c in (X_(a), Y_(b))]
            if len(pts) >= 4:
                cv.create_line(*pts, fill='#1a6bbd', width=2)
            for a, b in zip(s, vv):
                if np.isfinite(b):
                    cv.create_oval(X_(a) - 2, Y_(b) - 2, X_(a) + 2, Y_(b) + 2, fill='#1a6bbd', outline='')
            for b in (lo, hi):
                cv.create_text(m - 4, Y_(b), anchor='e', text=f'{b:.3g}', font=('Helvetica', 8))
            other = 'y' if v_axis.get() == 'x' else 'x'
            cv.create_text(W / 2, H - 15, text=f'{other} (m)', font=('Helvetica', 9))
            cv.create_text(m, 15, anchor='w', font=('Helvetica', 10, 'bold'),
                           text=f'{v_f.get()}' + (f' ({units.label(q)})' if q else '')
                           + f'   along {v_axis.get()} = {pos:g} m')
        for w_ in top.winfo_children():
            if isinstance(w_, (ttk.Combobox, tk.Entry)):
                w_.bind('<<ComboboxSelected>>', draw)
                w_.bind('<Return>', draw)
        cv.bind('<Configure>', draw)
        win.draw = draw
        return win

    # ══════════════════════════════════════════════════════════════════════
    #  Report and Excel
    # ══════════════════════════════════════════════════════════════════════
    def report_text(self):
        if self.des is None:
            return 'Analyse first: the report describes an analysed model.'
        return '\n'.join(rp.report_lines(self.model, self.res, self.des, self.thicken_log))

    def open_report(self):
        if self.des is None and not self.analyze():
            return None
        win = tk.Toplevel(self)
        win.title('Shell calculation report')
        win.geometry('980x640')
        t = tk.Text(win, font=('Consolas', 9), wrap='none')
        ys = ttk.Scrollbar(win, orient='vertical', command=t.yview)
        xs = ttk.Scrollbar(win, orient='horizontal', command=t.xview)
        t.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side='right', fill='y')
        xs.pack(side='bottom', fill='x')
        t.pack(fill='both', expand=True)
        t.insert('1.0', self.report_text())
        t.config(state='disabled')
        return win

    def export_excel(self, path):
        _ensure_openpyxl()
        return rp.export_excel(path, self.model, self.res, self.des, self.thicken_log)

    def import_excel(self, path):
        _ensure_openpyxl()
        self.set_model(rp.import_excel_model(path))
        self.status.set(f'Imported {os.path.basename(path)}. Press Analyze & design.')

    def _export_dialog(self):
        path = filedialog.asksaveasfilename(defaultextension='.xlsx',
                                            filetypes=[('Excel', '*.xlsx')],
                                            initialfile='shell_model.xlsx')
        if path:
            try:
                self.export_excel(path)
                self.status.set(f'Exported {path}')
            except Exception as exc:
                messagebox.showerror('Export Excel', str(exc))

    def _import_dialog(self):
        path = filedialog.askopenfilename(filetypes=[('Excel', '*.xlsx')])
        if path:
            try:
                self.import_excel(path)
            except Exception as exc:
                messagebox.showerror('Import Excel', str(exc))

    # ══════════════════════════════════════════════════════════════════════
    #  Units
    # ══════════════════════════════════════════════════════════════════════
    def _repaint_units(self):
        self._paint_all_si()
        for rl in (self.rl_supports, self.rl_beams, self.rl_columns, self.rl_cases,
                   self.rl_loads, self.rl_zones):
            rl.refresh()
        self._refresh_qz()
        self._refresh_cover_note()
        self._draw()
        self._write_info()
