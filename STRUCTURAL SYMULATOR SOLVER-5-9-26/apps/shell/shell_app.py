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
from apps.shell import shell_solid as ssd
from apps.shell import shell_codes as codes
from apps.shell import shell_wind as wind
from apps.shell import shell_reports as rp
from apps.shell import shell_fe as fe

BG = '#f5f5f3'
TB = '#ebebea'
PANEL_W = 360
RAIL_W = 74

# The tab used to put four notebook pages and every display control on
# screen at once. You are always doing exactly ONE of these things, so only
# that one's controls are on screen; the rest are forgotten by the geometry
# manager rather than hidden, so nothing off-screen keeps claiming width.
# (key, glyph, label, what it answers)
MODES = (
    ('definitions', '∫', 'Surface', 'the shape, its numbers and their sliders'),
    ('supports', '△', 'Supports', 'where it stands, its edge beams and columns'),
    ('loads', '↓', 'Loads', 'what it carries'),
    ('design', '▤', 'Design', 'the code, the concrete, the thickening rule'),
    ('sections', '✂', 'Sections', 'cuts through the slab'),
    ('analyse', '◑', 'Analyse', 'what to colour it by, and how to draw it'),
)
# One line per colour map, shown under the list. Not every map needs one --
# "Deflection" explains itself -- so this is the ones where the name alone
# leaves a real question: what is it per, which face, and against what.
FIELD_HELP = {
    'Surface (shaded)': 'No result at all: the shape itself, lit so the curvature reads. '
                        'Useful while you are still dragging sliders.',
    'Height z': 'The mid-surface, as a height. A sanity check on the formula more than a '
                'result.',
    'Thickness t': 'What the slab IS, element by element \u2014 the t you defined, raised by any '
                   'thickening zone and by the automatic layer. Read it next to Moment Mx: '
                   'they should look related.',
    'Gaussian curvature K': 'k\u2081k\u2082 at each point, from the shape alone \u2014 no analysis needed. '
                            'Positive on a dome, negative on a hypar, ZERO where the surface '
                            'goes locally flat. A thin shell in compression buckles where it '
                            'runs out of double curvature, so a pale band is a warning the '
                            'solve cannot give you.',
    'Vertical deflection': 'How far each point dropped. Isler held his own shells to '
                           'span/300; the status bar prints the ratio.',
    'Membrane Nx': 'Force per metre of width, in the plane of the shell, on the x face. '
                   'Positive is tension. Membrane action is what a shell carries load with.',
    'Membrane Ny': 'The same on the y face. A well-shaped shell is mostly compression in '
                   'both.',
    'Membrane shear Nxy': 'In-plane shear per metre. On a hypar under uniform load this is '
                          'the whole load path \u2014 membrane theory says Nxy = q/2k and Nx, Ny '
                          'are nearly zero.',
    'Principal N1 (tension)': 'The larger principal membrane force. Where this is positive '
                              'the concrete is in tension and the steel is doing the work; '
                              'Candela kept it below the tensile strength almost everywhere.',
    'Principal N2 (compression)': 'The smaller one. Compare its peak with the concrete '
                                  'strength, and read it beside the curvature map: high '
                                  'compression where K is near zero is where buckling lives.',
    'Moment Mx': 'Bending moment per metre about the y axis \u2014 the shell acting as a plate '
                 'rather than as a shell. In pure membrane action this is nearly zero, so '
                 'wherever it is large the shape failed to carry the load in its own plane.',
    'Moment My': 'The same about the x axis.',
    'Twisting Mxy': 'The twisting moment. It is not designed for directly: it is folded into '
                    'the design moments the steel is sized from.',
    'Transverse shear |Q|': 'Out-of-plane shear per metre. It matters near supports, ribs and '
                            'edge beams, and it is the check a thin shell rarely fails and a '
                            'thick one can.',
    'Utilisation (structural checks)': 'Demand \u00f7 capacity over the real checks \u2014 steel, '
                                       'concrete, shear, buckling, punching at the blocks. '
                                       'The scale is absolute: red is 1.0 in every model, '
                                       'which makes it the one map comparable between them.',
    'Utilisation (worst check)': 'The same, with the detailing minimum folded in. A shell at '
                                 'the cover minimum reads 0.86 here and 0.1 on the structural '
                                 'map, and neither is wrong.',
    'Governing check': 'Which check decides the thickness at each element. Categorical, not '
                       'a ramp: the legend lists the checks it found.',
    'Thickness needed': 'The smallest t at which every check passes here. Zero difference '
                        'from t means the element is already fine.',
    'Thickness to add': 'Thickness needed minus what is there now. Over most of a working '
                        'shell this is zero, and the rings round the supports are the whole '
                        'answer.',
    'Deflection': 'Displacement magnitude. Isler held his own shells to a deflection of '
                  'span/300.',
}
RAIL_BG = '#eef2f6'
RAIL_ON = '#ffffff'
RAIL_STRIPE = '#1a6bbd'
OK_C, BAD_C, NOTE_C = '#1a7a3a', '#c0392b', '#888888'

ENVELOPE_MAX = 'Envelope: max of all combinations'
ENVELOPE_MIN = 'Envelope: min of all combinations'

# name -> (source, key, colour scale, unit quantity or None)
FIELDS = {
    'Surface (shaded)': ('geom', None, None, None),
    'Height z': ('geom', 'z', 'sequential', 'length'),
    'Thickness t': ('geom', 't', 'sequential', 'section_length'),
    'Gaussian curvature K': ('geom', 'K', 'diverging', None),
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

    def sel_index(self):
        """The selected row's index in the record list, or None."""
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _load_selected(self):
        sel = self.sel_index()
        if sel is not None:
            self._fill_form(self.records()[sel])

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
class InfoTip:
    """A one-line hint on hover.

    The rail is six glyphs. A glyph is a good target and a poor label, so
    each one carries the sentence the mode answers -- and its shortcut,
    because a shortcut nobody is told about is not a shortcut.
    """
    DELAY_MS = 600

    def __init__(self, widget, text):
        self.widget, self.text, self._after, self._tip = widget, text, None, None
        widget.bind('<Enter>', self._enter, add='+')
        widget.bind('<Leave>', self._leave, add='+')
        widget.bind('<Button-1>', self._leave, add='+')

    def _enter(self, _e=None):
        self._cancel()
        self._after = self.widget.after(self.DELAY_MS, self._show)

    def _leave(self, _e=None):
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    def _cancel(self):
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _show(self):
        self._after = None
        if self._tip is not None:
            return
        try:
            x = self.widget.winfo_rootx() + self.widget.winfo_width() + 6
            y = self.widget.winfo_rooty() + 6
            self._tip = tk.Toplevel(self.widget)
            self._tip.wm_overrideredirect(True)
            self._tip.wm_geometry('+%d+%d' % (x, y))
            tk.Label(self._tip, text=self.text, bg='#ffffe0', relief='solid', bd=1,
                     font=('Helvetica', 8), justify='left').pack()
        except tk.TclError:
            self._tip = None


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
        # The shell is a slab, and the tab knows how thick. Drawn as a solid
        # by default: at true scale a 10 cm shell on a 12 m span is still a
        # visible band at the free edge, and that band is the whole point.
        self.v_solid = tk.BooleanVar(value=True)
        self.v_exag = tk.DoubleVar(value=1.0)
        self.cuts = []
        self.v_cut_pos = tk.StringVar(value='0')
        self.v_cut_dims = tk.BooleanVar(value=True)
        self.v_cut_field = tk.BooleanVar(value=True)
        self.mode = 'definitions'
        self.v_pick = tk.BooleanVar(value=True)
        self.v_pick_type = tk.StringVar(value='pinned')
        self.v_pick_block = tk.DoubleVar(value=sm.DEFAULT_BLOCK)
        self.hover_node = None
        self.v_rulings = tk.BooleanVar(value=False)
        self.designs = []
        self.sweep_rows = []
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

        tb2 = tk.Frame(self, bg=TB)
        tb2.pack(fill='x', padx=6)
        tk.Label(tb2, text='View:', bg=TB, font=('Helvetica', 10)).pack(side='left', padx=(4, 2))
        for name in view3d.VIEWS:
            tk.Button(tb2, text=name, relief='flat', bd=0, padx=6, font=('Helvetica', 10),
                      command=lambda n=name: self.set_view(n)).pack(side='left')
        tk.Button(tb2, text='Fit', relief='flat', bd=0, padx=6, font=('Helvetica', 10),
                  command=lambda: (self._fit(), self._draw())).pack(side='left')
        tk.Frame(tb2, width=1, bg='#ccc').pack(side='left', fill='y', padx=6, pady=3)
        for text, cmd in (('Report', self.open_report),
                          ('Export Excel', self._export_dialog),
                          ('Import Excel', self._import_dialog)):
            tk.Button(tb2, text=text, relief='flat', bd=0, padx=6, font=('Helvetica', 10),
                      fg='#1a6bbd', command=cmd).pack(side='left')

        body = tk.Frame(self, bg=BG)
        body.pack(fill='both', expand=True, padx=6, pady=6)
        # ── the mode rail, and the one panel it drives ───────────────────
        rail = tk.Frame(body, bg=RAIL_BG, width=RAIL_W)
        rail.pack(side='left', fill='y')
        rail.pack_propagate(False)
        left = tk.Frame(body, bg=BG, width=PANEL_W)
        left.pack(side='left', fill='y', padx=(0, 6))
        left.pack_propagate(False)
        self.pages = {}
        self._panels = {}
        self._rail_buttons = {}
        for n, (key, glyph, label, tip) in enumerate(MODES, start=1):
            cell = tk.Frame(rail, bg=RAIL_BG, height=54)
            cell.pack(fill='x')
            cell.pack_propagate(False)
            stripe = tk.Frame(cell, bg=RAIL_BG, width=3)
            stripe.pack(side='left', fill='y')
            inner = tk.Frame(cell, bg=RAIL_BG)
            inner.pack(fill='both', expand=True)
            g = tk.Label(inner, text=glyph, bg=RAIL_BG, font=('Helvetica', 15))
            g.pack(pady=(6, 0))
            t_ = tk.Label(inner, text=label, bg=RAIL_BG, font=('Helvetica', 8))
            t_.pack()
            self._rail_buttons[key] = (cell, stripe, inner, g, t_)
            for w in (cell, inner, g, t_):
                w.bind('<Button-1>', lambda _e, k=key: self.set_mode(k))
            InfoTip(cell, '%s \u2014 %s   (Alt+%d)' % (label, tip, n))
            sp_ = ScrollPanel(left, width=PANEL_W - 8, bg=BG)
            self._panels[key] = sp_
            self.pages[label] = sp_.interior
            self.pages[key] = sp_.interior
        # Alt rather than a bare digit: most of the work here is typing
        # numbers into fields, and the shortcut has to fire from inside a
        # focused entry without typing into it.
        top = self.winfo_toplevel()
        for n, (key, *_r) in enumerate(MODES, start=1):
            top.bind('<Alt-Key-%d>' % n, lambda _e, k=key: self.set_mode(k))

        pw = tk.PanedWindow(body, orient='vertical', sashwidth=5, bg=BG)
        pw.pack(side='left', fill='both', expand=True)
        self._pw = pw
        self.zc = ZoomCanvas(pw, bg='white', highlightthickness=1)
        self.zc._on_zoom_changed = self._draw
        self.cam = view3d.Orbit3D(self.zc)
        self.cam.bind_orbit(on_change=self._draw, on_click=self._on_click)
        self.zc.canvas.bind('<Configure>', self._on_configure)
        self.zc.canvas.bind('<Motion>', self._on_motion)
        pw.add(self.zc, stretch='always', minsize=200)
        info = tk.Frame(pw, bg=BG)
        self.info = tk.Text(info, height=9, font=('Consolas', 9), wrap='none', bg='#fbfbfa')
        ys = ttk.Scrollbar(info, orient='vertical', command=self.info.yview)
        self.info.configure(yscrollcommand=ys.set)
        ys.pack(side='right', fill='y')
        self.info.pack(fill='both', expand=True)
        self._info_pane = info
        pw.add(info, stretch='never', minsize=80, height=170)
        # The section drawing takes the same slot, because it answers the same
        # question at the same moment: what did the last analysis find, here.
        # It is a full-width canvas rather than a 360 px panel because a
        # section at true scale is wide and short, and squeezing it into the
        # panel is what made the old dialog unreadable.
        sec = tk.Frame(pw, bg=BG)
        self._sec_pane = sec
        self.sec_canvas = tk.Canvas(sec, bg='white', highlightthickness=1,
                                    highlightbackground='#ccc')
        self.sec_canvas.pack(fill='both', expand=True)
        self.sec_canvas.bind('<Configure>', lambda _e: self._draw_bottom())

        sb = tk.Frame(self, bg=TB)
        sb.pack(fill='x', side='bottom')
        tk.Label(sb, textvariable=self.status, bg=TB, anchor='w',
                 font=('Helvetica', 10)).pack(fill='x', padx=8, pady=3)

        self._build_definitions(self.pages['definitions'])
        self._build_supports(self.pages['supports'])
        self._build_loads(self.pages['loads'])
        self._build_design(self.pages['design'])
        self._build_compare(self.pages['design'])
        self._build_sections(self.pages['sections'])
        self._build_analyse(self.pages['analyse'])
        self.set_mode('definitions')

    # ══════════════════════════════════════════════════════════════════════
    #  Modes
    # ══════════════════════════════════════════════════════════════════════
    def set_mode(self, key):
        """Show one mode's panel and forget the rest.

        `pack_forget`, not `lower()`: a hidden-but-packed panel still claims
        its width from the geometry manager, which is exactly how the old
        layout ended up with 360 px of controls on screen whatever you were
        doing.
        """
        if key not in self._panels:
            return
        self.mode = key
        for k, sp_ in self._panels.items():
            if k == key:
                sp_.pack(fill='both', expand=True)
            else:
                sp_.pack_forget()
        for k, (cell, stripe, inner, g, t_) in self._rail_buttons.items():
            on = k == key
            bg = RAIL_ON if on else RAIL_BG
            for w in (cell, inner, g, t_):
                w.configure(bg=bg)
            stripe.configure(bg=RAIL_STRIPE if on else RAIL_BG)
            t_.configure(font=('Helvetica', 8, 'bold' if on else 'normal'))
        # the bottom pane answers the mode's own question
        drawing = key in ('sections', 'design')
        want = self._sec_pane if drawing else self._info_pane
        other = self._info_pane if drawing else self._sec_pane
        # panes() hands back Tcl path names, which are not the widgets; compare
        # as strings or the forget below silently never fires and both panes
        # stay on screen sharing one slot
        here = [str(w) for w in self._pw.panes()]
        try:
            if str(other) in here:
                self._pw.forget(other)
            if str(want) not in here:
                self._pw.add(want, stretch='never', minsize=80, height=170)
        except tk.TclError:
            pass
        if drawing:
            self._draw_bottom()
        self._draw()

    # ══════════════════════════════════════════════════════════════════════
    #  Analyse: the list that used to be a combobox in the corner
    # ══════════════════════════════════════════════════════════════════════
    def _build_analyse(self, p):
        tk.Label(p, text='Colour the shell by', bg=BG,
                 font=('Helvetica', 10, 'bold')).pack(anchor='w', padx=8, pady=(8, 2))
        wrap = tk.Frame(p, bg=BG)
        wrap.pack(fill='x', padx=8)
        ys = ttk.Scrollbar(wrap, orient='vertical')
        self.field_list = tk.Listbox(wrap, height=14, exportselection=False,
                                     font=('Helvetica', 9), activestyle='none',
                                     yscrollcommand=ys.set)
        ys.config(command=self.field_list.yview)
        ys.pack(side='right', fill='y')
        self.field_list.pack(side='left', fill='x', expand=True)
        for name in FIELDS:
            self.field_list.insert('end', name)
        self.field_list.bind('<<ListboxSelect>>', self._on_field_pick)
        self.field_help = tk.Label(p, text='', bg=BG, fg='#555', wraplength=PANEL_W - 30,
                                   justify='left', font=('Helvetica', 8))
        self.field_help.pack(anchor='w', padx=8, pady=(4, 2))
        tk.Button(p, text='?  what am I looking at', font=('Helvetica', 9), fg='#1a6bbd',
                  relief='flat', bd=0, command=self.open_field_guide).pack(anchor='w', padx=8,
                                                                          pady=(0, 8))
        row = tk.Frame(p, bg=BG)
        row.pack(fill='x', padx=8)
        tk.Label(row, text='for', bg=BG, font=('Helvetica', 9)).pack(side='left')
        self.select_box = ttk.Combobox(row, textvariable=self.v_select, state='readonly', width=30)
        self.select_box.pack(side='left', padx=4)
        self.select_box.bind('<<ComboboxSelected>>', lambda e: self._draw())

        tk.Label(p, text='Draw it as', bg=BG,
                 font=('Helvetica', 10, 'bold')).pack(anchor='w', padx=8, pady=(12, 2))
        for text, var in (('mesh lines', self.v_mesh_lines),
                          ('solid — show the thickness', self.v_solid),
                          ('deformed', self.v_deformed),
                          ('principal directions', self.v_principal),
                          ('straight generators (ruled surfaces)', self.v_rulings)):
            tk.Checkbutton(p, text=text, variable=var, bg=BG, font=('Helvetica', 9),
                           command=self._draw).pack(anchor='w', padx=16)
        row = tk.Frame(p, bg=BG)
        row.pack(fill='x', padx=16, pady=(4, 0))
        tk.Label(row, text='thickness ×', bg=BG, font=('Helvetica', 9)).pack(side='left')
        self.exag_box = ttk.Combobox(row, textvariable=self.v_exag, state='readonly', width=5,
                                     values=('1', '2', '5', '10', '25'))
        self.exag_box.pack(side='left', padx=4)
        self.exag_box.bind('<<ComboboxSelected>>', lambda _e: self._draw())
        tk.Label(p, text='At ×1 the slab is drawn to scale. Anything else is a lie about a '
                         'dimension, so the canvas says so in red.', bg=BG, fg='#555',
                 wraplength=PANEL_W - 30, justify='left',
                 font=('Helvetica', 8)).pack(anchor='w', padx=16, pady=(2, 6))
        row = tk.Frame(p, bg=BG)
        row.pack(fill='x', padx=16)
        tk.Label(row, text='deformed ×', bg=BG, font=('Helvetica', 9)).pack(side='left')
        tk.Scale(row, from_=0.2, to=5.0, resolution=0.1, orient='horizontal',
                 variable=self.v_def_scale, length=120, showvalue=True, bg=BG, bd=0,
                 highlightthickness=0, command=lambda _v: self._draw()).pack(side='left')
        self._sync_field_list()
        self.v_field.trace_add('write', self._sync_field_list)

    def _sync_field_list(self, *_a):
        """Point the list at whatever v_field currently holds.

        Bound to the variable rather than called from the picker, because
        the field is also set from elsewhere -- analyse() switches to
        'Thickness to add' after a thickening run, and a list still
        highlighting the row from before would be describing the wrong map.
        """
        if not hasattr(self, 'field_list'):
            return
        try:
            i = list(FIELDS).index(self.v_field.get())
        except ValueError:
            return
        self.field_list.selection_clear(0, 'end')
        self.field_list.selection_set(i)
        self.field_list.see(i)
        self.field_help.config(text=FIELD_HELP.get(self.v_field.get(), ''))

    def _on_field_pick(self, _e=None):
        sel = self.field_list.curselection()
        if not sel:
            return
        self.v_field.set(self.field_list.get(sel[0]))
        self.field_help.config(text=FIELD_HELP.get(self.v_field.get(), ''))
        self._draw()

    # ══════════════════════════════════════════════════════════════════════
    #  Sections
    # ══════════════════════════════════════════════════════════════════════
    # The tab could already plot a RESULT along a line, in a window you
    # opened, read and threw away. This is the other half and the part that
    # was missing: the cuts are objects you keep, and the drawing is the
    # slab itself at true scale, so "where is it getting thicker" is a thing
    # you can see rather than infer from a colour map.
    CUT_COLOURS = ('#1a6bbd', '#c0561f', '#7b2fa8', '#1a7a3a', '#a8431f')

    def _build_sections(self, p):
        tk.Label(p, text='Cuts through the slab', bg=BG,
                 font=('Helvetica', 10, 'bold')).pack(anchor='w', padx=8, pady=(8, 2))
        tk.Label(p, text='Each cut keeps its colour: the line on the model, its row here and '
                         'the drawing below are the same colour, so no cut has to be hunted for.',
                 bg=BG, fg='#555', wraplength=PANEL_W - 30, justify='left',
                 font=('Helvetica', 8)).pack(anchor='w', padx=8, pady=(0, 6))
        wrap = tk.Frame(p, bg=BG)
        wrap.pack(fill='x', padx=8)
        ys = ttk.Scrollbar(wrap, orient='vertical')
        self.cut_list = tk.Listbox(wrap, height=7, exportselection=False,
                                   font=('Consolas', 9), activestyle='none',
                                   yscrollcommand=ys.set)
        ys.config(command=self.cut_list.yview)
        ys.pack(side='right', fill='y')
        self.cut_list.pack(side='left', fill='x', expand=True)
        self.cut_list.bind('<<ListboxSelect>>', lambda _e: (self._draw(), self._draw_section()))

        row = tk.Frame(p, bg=BG)
        row.pack(fill='x', padx=8, pady=(6, 0))
        tk.Label(row, text='at', bg=BG, font=('Helvetica', 9)).pack(side='left')
        self.v_cut_pos = tk.StringVar(value='0')
        tk.Entry(row, textvariable=self.v_cut_pos, width=8).pack(side='left', padx=4)
        tk.Label(row, text='m', bg=BG, font=('Helvetica', 9)).pack(side='left')
        row2 = tk.Frame(p, bg=BG)
        row2.pack(fill='x', padx=8, pady=(4, 0))
        tk.Button(row2, text='+ cut along x', font=('Helvetica', 9),
                  command=lambda: self.add_cut('x')).pack(side='left')
        tk.Button(row2, text='+ cut along y', font=('Helvetica', 9),
                  command=lambda: self.add_cut('y')).pack(side='left', padx=4)
        tk.Button(row2, text='remove', font=('Helvetica', 9), fg='#a33',
                  command=self.remove_cut).pack(side='left')
        tk.Label(p, text='A cut along x is the plane x = position, and it runs in y.',
                 bg=BG, fg='#555', wraplength=PANEL_W - 30, justify='left',
                 font=('Helvetica', 8)).pack(anchor='w', padx=8, pady=(4, 8))
        tk.Checkbutton(p, text='dimension every station', variable=self.v_cut_dims, bg=BG,
                       font=('Helvetica', 9),
                       command=self._draw_section).pack(anchor='w', padx=16)
        tk.Checkbutton(p, text='colour the cut face by the current map',
                       variable=self.v_cut_field, bg=BG, font=('Helvetica', 9),
                       command=self._draw_section).pack(anchor='w', padx=16)
        self.cut_note = tk.Label(p, text='', bg=BG, fg='#555', wraplength=PANEL_W - 30,
                                 justify='left', font=('Helvetica', 8))
        self.cut_note.pack(anchor='w', padx=8, pady=(8, 8))

    def add_cut(self, axis):
        try:
            pos = self.model.ws.scalar(self.v_cut_pos.get())
        except formula.FormulaError as exc:
            self.status.set(f'Cut position: {exc}')
            return
        self.cuts.append({'axis': axis, 'pos': float(pos),
                          'colour': self.CUT_COLOURS[len(self.cuts) % len(self.CUT_COLOURS)]})
        self._refresh_cuts()
        self.cut_list.selection_clear(0, 'end')
        self.cut_list.selection_set(len(self.cuts) - 1)
        self._draw()
        self._draw_section()

    def remove_cut(self):
        sel = self.cut_list.curselection()
        if not sel:
            return
        self.cuts.pop(sel[0])
        self._refresh_cuts()
        self._draw()
        self._draw_section()

    def _refresh_cuts(self):
        """Redraw the list, with what each cut is worth knowing about it."""
        if not hasattr(self, 'cut_list'):
            return
        self.cut_list.delete(0, 'end')
        for n, c in enumerate(self.cuts, start=1):
            t_txt = ''
            pr = self._cut_profile(c)
            if pr is not None:
                q = 'section_length'
                lo = units.from_si(q, float(np.min(pr['t'])))
                hi = units.from_si(q, float(np.max(pr['t'])))
                t_txt = '  t %.4g-%.4g' % (lo, hi)
            self.cut_list.insert('end', 'S%d  %s = %-7.4g%s' % (n, c['axis'], c['pos'], t_txt))
            self.cut_list.itemconfig(n - 1, foreground=c['colour'])

    def _selected_cut(self):
        sel = self.cut_list.curselection() if hasattr(self, 'cut_list') else ()
        if not sel or sel[0] >= len(self.cuts):
            return None
        return self.cuts[sel[0]]

    def _cut_profile(self, cut, exaggerate=True):
        g = self.geom
        if g is None or cut is None:
            return None
        idx = ssd.strip_index(g['xs'], g['ys'], cut['axis'], cut['pos'])
        k = float(self.v_exag.get() or 1.0) if exaggerate else 1.0
        return ssd.section_profile(g['X'], g['elems'], g['t'], g['ids'],
                                   cut['axis'], idx, k)

    def _draw_section(self):
        """The selected cut, drawn as the slab at true scale.

        Horizontal is the plan coordinate along the cut and vertical is z, at
        the SAME scale, because that is what a section is. The thickness is
        therefore the drawing rather than a number beside it -- which is the
        whole point, and is also why the exaggeration factor from the 3-D
        view carries over and is labelled here too.
        """
        cv = getattr(self, 'sec_canvas', None)
        if cv is None:
            return
        cv.delete('all')
        W = max(cv.winfo_width(), 400)
        H = max(cv.winfo_height(), 120)
        cut = self._selected_cut()
        if cut is None:
            cv.create_text(14, 14, anchor='nw', fill='#999', font=('Helvetica', 9),
                           text='No cut selected. Add one on the left, or pick a row.')
            return
        pr = self._cut_profile(cut)
        if pr is None:
            cv.create_text(14, 14, anchor='nw', fill=BAD_C, font=('Helvetica', 9),
                           text=self.error or 'No surface.')
            return
        s_all = np.concatenate([pr['s_top'], pr['s_bot']])
        z_all = np.concatenate([pr['z_top'], pr['z_bot']])
        m = 34
        span_s = max(np.ptp(s_all), 1e-9)
        span_z = max(np.ptp(z_all), 1e-9)
        # ONE scale for both axes: a section with two scales is a graph, and
        # a graph cannot show you a thickness
        sc = min((W - 2 * m) / span_s, (H - 2 * m - 16) / span_z)
        x0 = m + ((W - 2 * m) - span_s * sc) / 2.0 - s_all.min() * sc
        y0 = m + ((H - 2 * m - 16) - span_z * sc) / 2.0 + z_all.max() * sc

        def P(sv, zv):
            return x0 + np.asarray(sv) * sc, y0 - np.asarray(zv) * sc

        # the cut face, span by span, in the model's own colour when asked
        vals = None
        if self.v_cut_field.get():
            v, scale, _q = self.field_values()
            if v is not None and scale != 'categorical':
                cols, _lo, _hi = view3d.colours_for(np.asarray(v)[pr['elems']], scale)
                vals = cols
        xt, yt = P(pr['s_top'], pr['z_top'])
        xb, yb = P(pr['s_bot'], pr['z_bot'])
        for i in range(len(pr['elems'])):
            poly = [xt[i], yt[i], xt[i + 1], yt[i + 1],
                    xb[i + 1], yb[i + 1], xb[i], yb[i]]
            col = vals[i] if vals is not None else '#c6d3de'
            cv.create_polygon(*poly, fill=col, outline=col)
        cv.create_line(*np.stack([xt, yt], 1).ravel(), fill='#2c3740', width=2)
        cv.create_line(*np.stack([xb, yb], 1).ravel(), fill='#2c3740', width=2)
        xm, ym = P(pr['s'], pr['z'])
        cv.create_line(*np.stack([xm, ym], 1).ravel(), fill='#54606a', width=1, dash=(5, 4))

        # where the automatic layer or a zone raised the shell above its
        # own formula: the band is the answer to "where is it thickening"
        base = self._base_thickness_along(cut, pr)
        if base is not None:
            raised = pr['t'] > base + 1e-6
            for i in range(len(pr['elems'])):
                if raised[i] and raised[i + 1]:
                    cv.create_line(xt[i], m - 10, xt[i + 1], m - 10, fill='#c0561f', width=6)
            if raised.any():
                cv.create_text(x0 + (s_all.min() + 0.02 * span_s) * sc, m - 20, anchor='w',
                               fill='#a8431f', font=('Helvetica', 8),
                               text='thickened above the formula')

        if self.v_cut_dims.get():
            q = 'section_length'
            step = max(1, len(pr['s']) // 12)
            for i in range(0, len(pr['s']), step):
                cv.create_line(xt[i], yt[i], xb[i], yb[i], fill='#1a6bbd')
                cv.create_text(xb[i], yb[i] + 8, anchor='n', fill='#1a6bbd',
                               font=('Helvetica', 8),
                               text='%.4g' % units.from_si(q, float(pr['t'][i])))
            cv.create_text(W / 2, H - 6, anchor='s', fill='#1a6bbd', font=('Helvetica', 8),
                           text='thickness at each station, %s' % units.label(q))
        k = pr['exaggeration']
        head = ('S%d  ·  %s = %.4g m  ·  drawn at true scale'
                % (self.cuts.index(cut) + 1, cut['axis'], cut['pos'])) if k == 1.0 else \
               ('S%d  ·  %s = %.4g m  ·  THICKNESS DRAWN ×%g'
                % (self.cuts.index(cut) + 1, cut['axis'], cut['pos'], k))
        cv.create_text(12, 10, anchor='nw', fill=cut['colour'] if k == 1.0 else BAD_C,
                       font=('Helvetica', 9, 'bold'), text=head)

    def _base_thickness_along(self, cut, pr):
        """The thickness the FORMULA alone asks for along this cut.

        Compared with what is actually there, it is how the drawing knows
        which spans the automatic layer or a zone raised -- without which
        "show first" is still only a colour map.
        """
        g = self.geom
        try:
            cen = g['X'][g['elems'][pr['elems']]].mean(axis=1)
            base_el = self.model.element_thickness(cen[:, 0], cen[:, 1], with_auto=False)
        except Exception:
            return None
        base = np.empty(len(pr['t']))
        base[:-1] = base_el
        base[-1] = base_el[-1]
        base[1:-1] = 0.5 * (base_el[:-1] + base_el[1:])
        return base

    def _draw_cuts(self, X, sx, sy):
        """The cut lines on the 3-D model, each in its row's colour."""
        cv = self.zc.canvas
        sel = self._selected_cut()
        for c in self.cuts:
            pr = self._cut_profile(c)
            if pr is None:
                continue
            g = self.geom
            idx = ssd.strip_index(g['xs'], g['ys'], c['axis'], c['pos'])
            ids = g['ids']
            a = ids[:, idx] if c['axis'] == 'x' else ids[idx, :]
            b = ids[:, idx + 1] if c['axis'] == 'x' else ids[idx + 1, :]
            px = 0.5 * (sx[a] + sx[b])
            py = 0.5 * (sy[a] + sy[b])
            if np.abs(px).max() > 30000 or np.abs(py).max() > 30000:
                continue
            cv.create_line(*np.stack([px, py], 1).ravel(), fill=c['colour'],
                           width=4 if c is sel else 2)

    def _shape_line(self):
        """The numbers a shell designer reads first, in front of the result.

        Four of them, and none was printed anywhere before: how much
        concrete is in it, how slender it is, how far it moved, and against
        what. Isler held his own shells to span/300, so the deflection is
        shown as that ratio rather than as a millimetre count nobody can
        place.
        """
        g = self.geom
        if g is None:
            return ''
        t = np.asarray(g['t'], float)
        vol = ssd.solid_volume(g['X'], g['elems'], t)
        x0, x1, y0, y1 = g['plan']
        span = max(x1 - x0, y1 - y0)
        bits = ['%d elements' % len(g['elems']),
                't %.4g-%.4g %s' % (units.from_si('section_length', float(t.min())),
                                    units.from_si('section_length', float(t.max())),
                                    units.label('section_length')),
                'L/t %.0f' % (span / max(float(t.mean()), 1e-9)),
                '%.3g m3 concrete' % vol]
        if self.res is not None:
            try:
                d = self._peak_deflection()
                if d > 0:
                    bits.append('peak %.4g %s = span/%.0f'
                                % (units.from_si('deflection', d),
                                   units.label('deflection'), span / d))
            except Exception:
                pass
        return '  \u00b7  '.join(bits) + '  \u00b7  '

    def _peak_deflection(self):
        """Largest downward movement of the mid-surface, in metres."""
        U = self.res.U
        nn = len(self.geom['X'])
        peak = 0.0
        for c in range(U.shape[1]):
            d = U[:, c].reshape(-1, 6)[:nn, :3]
            peak = max(peak, float(np.abs(d).max()))
        return peak

    # ══════════════════════════════════════════════════════════════════════
    #  Supports: picked on the model, placed as blocks
    # ══════════════════════════════════════════════════════════════════════
    # A corner of an element IS a node of the mesh -- the point the solver
    # assembles stiffness at -- so clicking one is not an approximation of a
    # support, it is the support, where you put it. What arrives there is a
    # point support ON A BLOCK, because a shell sitting on a mathematical
    # point is a singularity whose shear grows without limit as the mesh
    # refines. You pick where a block goes; you cannot pick a point.
    PICK_PX = 22

    def nearest_node(self, px, py, limit=None):
        """The mesh node nearest a screen position, or None.

        Ties are broken towards the viewer: on a dome the near and far
        surfaces project on top of each other, and picking the one behind
        would put a support where you cannot see it.
        """
        if self.geom is None:
            return None
        X = self._nodes_for_view()
        sx, sy = self.cam.project(X)
        d2 = (sx - px) ** 2 + (sy - py) ** 2
        lim = (self.PICK_PX if limit is None else limit) ** 2
        near = np.nonzero(d2 < lim)[0]
        if not len(near):
            return None
        depth = self.cam.depth(X)
        return int(near[np.argmin(d2[near] - 1e-3 * depth[near])])

    def support_node_index(self):
        """Node -> the index of the point support standing on it."""
        out = {}
        g = self.geom
        if g is None:
            return out
        X = g['X']
        for i, spec in enumerate(self.model.data.get('supports', [])):
            if spec.get('at') != 'point':
                continue
            try:
                px, py = (self.model.ws.scalar(str(v))
                          for v in str(spec.get('which', '')).split(','))
            except Exception:
                continue
            out[int(np.argmin((X[:, 0] - px) ** 2 + (X[:, 1] - py) ** 2))] = i
        return out

    def toggle_support_at(self, px, py):
        """Click a corner: put a support there, or take the one there away."""
        n = self.nearest_node(px, py)
        if n is None:
            self.status.set('No element corner near the pointer.')
            return
        here = self.support_node_index()
        sups = self.model.data.setdefault('supports', [])
        if n in here:
            spec = sups.pop(here[n])
            self.status.set('Support removed from the corner at x = %.3g, y = %.3g.'
                            % (self.geom['X'][n, 0], self.geom['X'][n, 1]))
        else:
            X = self.geom['X']
            sups.append({'at': 'point', 'which': '%g, %g' % (X[n, 0], X[n, 1]),
                         'type': self.v_pick_type.get(),
                         'block': float(self.v_pick_block.get() or sm.DEFAULT_BLOCK)})
            self.status.set('%s support on a %.3g m block at x = %.3g, y = %.3g.'
                            % (sm.SUPPORT_LABELS.get(self.v_pick_type.get(),
                                                     self.v_pick_type.get()),
                               float(self.v_pick_block.get() or sm.DEFAULT_BLOCK),
                               X[n, 0], X[n, 1]))
        self._after_support_edit()

    def _after_support_edit(self):
        self.rl_supports.refresh()
        self._model_changed()
        self._refresh_geometry_quietly()
        self._draw()

    def _refresh_geometry_quietly(self):
        """Rebuild the mesh for the drawing without demanding an analysis."""
        try:
            self._rebuild_geometry()
        except Exception:
            pass

    def add_supports_at(self, nodes):
        """Put one point support on each of these nodes, skipping any that
        already carry one."""
        X = self.geom['X']
        here = self.support_node_index()
        sups = self.model.data.setdefault('supports', [])
        added = 0
        for n in nodes:
            if n in here:
                continue
            sups.append({'at': 'point', 'which': '%g, %g' % (X[n, 0], X[n, 1]),
                         'type': self.v_pick_type.get(),
                         'block': float(self.v_pick_block.get() or sm.DEFAULT_BLOCK)})
            added += 1
        self.status.set('%d corners supported.' % added)
        self._after_support_edit()
        return added

    def quick_support(self, what):
        """The three support sets a shell almost always wants."""
        g = self.geom
        if g is None:
            return 0
        ids, X = g['ids'], g['X']
        if what == 'corners':
            nodes = [ids[0, 0], ids[0, -1], ids[-1, -1], ids[-1, 0]]
        elif what == 'boundary':
            nodes = sorted({int(a) for a, _b, _e in ssd.boundary_edges(g['elems'])} |
                           {int(b) for _a, b, _e in ssd.boundary_edges(g['elems'])})
        elif what == 'lowest':
            # the lowest ring: boundary nodes within one element depth of the
            # lowest point, which on a vault or a hypar is the springing line
            bnd = sorted({int(a) for a, _b, _e in ssd.boundary_edges(g['elems'])} |
                         {int(b) for _a, b, _e in ssd.boundary_edges(g['elems'])})
            z = X[bnd, 2]
            nodes = [n for n, zz in zip(bnd, z) if zz <= z.min() + 0.02 * max(np.ptp(X[:, 2]), 1e-9)]
        else:
            return 0
        return self.add_supports_at(nodes)

    def clear_supports(self):
        self.model.data['supports'] = []
        self.status.set('Every support removed. The shell is a mechanism until you add one.')
        self._after_support_edit()

    def toggle_sandbox(self):
        """Switch the selected support off, or back on, without deleting it."""
        rl = self.rl_supports
        sel = rl.sel_index()
        sups = self.model.data.get('supports', [])
        if sel is None or sel >= len(sups):
            self.status.set('Pick a support row first.')
            return
        spec = sups[sel]
        spec['off'] = not spec.get('off')
        self.status.set('Support %d is %s. Press Analyze & design to see what it was carrying.'
                        % (sel + 1, 'switched OFF' if spec['off'] else 'back on'))
        self._after_support_edit()

    def _draw_pickable_corners(self, X, sx, sy):
        """In Supports mode, show what is pickable and what is taken.

        Only in that mode: 600-odd corner markers over a solved model would
        bury the result you are reading.
        """
        if self.mode != 'supports' or not self.v_pick.get():
            return
        cv = self.zc.canvas
        g = self.geom
        ids = g['ids']
        # the corners, thinned so a fine mesh does not become a field of dots
        step = max(1, int(np.ceil(max(ids.shape) / 26)))
        show = np.unique(np.concatenate([ids[::step, ::step].ravel(),
                                         ids[0, :], ids[-1, :], ids[:, 0], ids[:, -1]]))
        taken = self.support_node_index()
        for n in show:
            x, y = float(sx[n]), float(sy[n])
            if abs(x) > 30000 or abs(y) > 30000:
                continue
            if n in taken:
                continue
            cv.create_rectangle(x - 2, y - 2, x + 2, y + 2, outline='#8c979f',
                                fill='#ffffff', width=1, tags='pick')
        for n in taken:
            x, y = float(sx[n]), float(sy[n])
            cv.create_rectangle(x - 4, y - 4, x + 4, y + 4, outline='#12457a',
                                fill='#1a6bbd', width=1, tags='pick')
        if self.hover_node is not None and self.hover_node < len(sx):
            x, y = float(sx[self.hover_node]), float(sy[self.hover_node])
            cv.create_oval(x - 8, y - 8, x + 8, y + 8, outline='#c0561f', width=2, tags='pick')

    def _on_motion(self, e):
        if self.mode != 'supports' or not self.v_pick.get() or self.geom is None:
            return
        n = self.nearest_node(e.x, e.y)
        if n != self.hover_node:
            self.hover_node = n
            self._draw()

    def _draw_rulings(self, X):
        """The straight lines that lie IN the surface, where there are any.

        Drawn short and from every few nodes rather than swept end to end:
        the point is to show which way the boards run and that they are
        straight, and a full sweep of a 24 x 24 grid is a black square.
        """
        cv = self.zc.canvas
        g = self.geom
        R = ssd.ruling_directions(g['X'], g['ids'])
        ids = g['ids']
        step = max(1, int(np.ceil(max(ids.shape) / 14)))
        take = ids[::step, ::step].ravel()
        # only where the shell actually is: a plan rule leaves the cut-away
        # nodes in the grid, and a generator drawn from one runs out over
        # empty air, which reads as the shell being bigger than it is
        used = g.get('used')
        if used is not None:
            take = take[used[take]]
        h = 0.45 * float(g['h_el']) * step
        drawn = 0
        for n in take:
            for k, col in ((0, '#7b2fa8'), (1, '#1a7a3a')):
                d = R[n, k]
                if not np.all(np.isfinite(d)):
                    continue
                p0, p1 = g['X'][n] - d * h, g['X'][n] + d * h
                (ax, ay), (bx, by) = (self.cam.project(p0), self.cam.project(p1))
                cv.create_line(float(ax[0]), float(ay[0]), float(bx[0]), float(by[0]),
                               fill=col, width=2)
                drawn += 1
        if not drawn:
            cv.create_text(self.zc.canvas.winfo_width() - 12, 12, anchor='ne', fill='#a8431f',
                           font=('Helvetica', 9),
                           text='no straight line lies in this surface \u2014 it is '
                                'synclastic here')

    # ══════════════════════════════════════════════════════════════════════
    #  The guide
    # ══════════════════════════════════════════════════════════════════════
    # Three things are worth knowing about ANY map before it is trusted, and
    # none of them is in the name: what the quantity is per, what the scale
    # is anchored to, and which of the four caveats in section 4 of the build
    # report applies. One source, shown in three places -- the line under the
    # list, this card, and the guide page in REPORTS AND GUIDES.
    GUIDE_TAIL = (
        'THE SCALE. Most maps are anchored to THIS model\u2019s own range, so two '
        'models are not comparable by colour alone \u2014 the legend always prints '
        'the numbers. Two are absolute and therefore are comparable: '
        'Utilisation, where red is 1.0 in every model, and Gaussian curvature, '
        'which is a property of the shape.\n\n'
        'THE UNITS follow the selector at the top of the window: membrane '
        'forces as a line load (kN/m), moments per metre (kN\u00b7m/m), steel as '
        'area per metre (cm\u00b2/m), thickness as a section length (cm).\n\n'
        'AND THE THREE THINGS THAT CONSTRAIN ANY DESIGN HERE:\n'
        '  1. CIRSOC 201-2024 has no shell chapter. Its C 1.2.10.7 defers to '
        'Recomendaci\u00f3n CIRSOC 201.03, which is still being written, so the '
        'general rules come from the 2024 draft and the shell rules from '
        'CIRSOC 201-2005. The report lists them under \u201cverify before '
        'sign-off\u201d.\n'
        '  2. The wind speeds are CIRSOC 102-2005, which went with a 1.6 '
        'factor, while the 2024 combinations expect the larger 2024 speeds at '
        '1.0. The tab knows which edition the speed came from and scales W by '
        '1.6; get that wrong and wind is under-counted by 1.6.\n'
        '  3. Cover sets a floor on thickness. At 35 mm for a roof exposed to '
        'the weather, no shell is thinner than 8.6 cm with one central mesh or '
        '12.2 cm with two. Candela\u2019s 4 cm shells would not comply as built.\n\n'
        'A SUPPORT IS A BLOCK, NOT A POINT. A shell on a mathematical point is '
        'a singularity: the shear beside it grows without limit as the mesh '
        'refines. Every point support and column head is a rigid block of a '
        'stated size, and the check there is the code\u2019s punching check on a '
        'perimeter d/2 outside it, which is mesh-independent. The element '
        'values right beside a block still move a little with the mesh.')

    def open_field_guide(self):
        name = self.v_field.get()
        win = tk.Toplevel(self)
        win.title('What am I looking at? \u2014 %s' % name)
        win.geometry('640x540')
        head = tk.Frame(win, bg=TB)
        head.pack(fill='x')
        tk.Label(head, text=name, bg=TB, font=('Helvetica', 12, 'bold'),
                 anchor='w').pack(fill='x', padx=12, pady=(8, 2))
        q = FIELDS[name][3]
        tk.Label(head, text=('measured in %s' % units.label(q)) if q else 'no unit \u2014 a ratio '
                 'or a category', bg=TB, fg='#555', font=('Helvetica', 9),
                 anchor='w').pack(fill='x', padx=12, pady=(0, 8))
        body = tk.Text(win, wrap='word', font=('Helvetica', 10), padx=14, pady=12,
                       bg='#ffffff', relief='flat')
        ys = ttk.Scrollbar(win, orient='vertical', command=body.yview)
        body.configure(yscrollcommand=ys.set)
        ys.pack(side='right', fill='y')
        body.pack(fill='both', expand=True)
        body.insert('end', FIELD_HELP.get(name, 'No note for this map yet.') + '\n\n')
        body.insert('end', self.GUIDE_TAIL)
        body.configure(state='disabled')
        return win

    # ══════════════════════════════════════════════════════════════════════
    #  Comparing designs
    # ══════════════════════════════════════════════════════════════════════
    # Thickening, the edge beam and the concrete class are three levers on
    # the same shell, and the tab could move all three and remember none of
    # the answers. These are the numbers the published optimisation studies
    # compare -- peak tension, deflection, reinforcement -- plus the two a
    # concrete shell is actually bought with, volume and tonnage.
    STEEL_DENSITY = 7850.0          # kg/m3

    def design_metrics(self):
        """Everything worth comparing about the design on screen, in SI.

        Returns None before an analysis: every one of these is a result,
        and a table row of dashes would only invite reading it as zeros.
        """
        g = self.geom
        if g is None or self.res is None or self.des is None:
            return None
        t = np.asarray(g['t'], float)
        area = ssd.element_areas(g['X'], g['elems'])
        x0, x1, y0, y1 = g['plan']
        span = max(x1 - x0, y1 - y0)
        out = {'elements': len(g['elems']), 't_min': float(t.min()), 't_max': float(t.max()),
               'span': span, 'concrete': ssd.solid_volume(g['X'], g['elems'], t)}
        n1, _s, _q = self.field_values('Principal N1 (tension)')
        if n1 is not None:
            n1 = np.asarray(n1, float)
            # N is a force per metre; over a thickness t that is a stress, and
            # a stress is what you compare with the concrete's own strength
            out['tension_pa'] = float(np.nanmax(n1 / np.maximum(t, 1e-9)))
            hot = n1 > 0
            out['tension_area'] = float(area[hot].sum() / max(area.sum(), 1e-12))
        steel = 0.0
        # both layouts: two meshes leave the central pair NaN and one central
        # mesh leaves the four face maps NaN, so summing all six with nansum
        # is right for either without asking which the design chose
        for name in ('Steel x, top', 'Steel y, top', 'Steel x, bottom', 'Steel y, bottom',
                     'Steel x, central mesh', 'Steel y, central mesh'):
            v, _s, _q = self.field_values(name)
            if v is not None:
                # As is an area per metre of width; over an element of area A
                # the bars in one direction occupy As * A of volume
                steel += float(np.nansum(np.asarray(v, float) * area))
        out['steel_kg'] = steel * self.STEEL_DENSITY
        d = self._peak_deflection()
        out['deflection'] = d
        out['span_over'] = (span / d) if d > 0 else float('inf')
        try:
            u, _s, _q = self.field_values('Utilisation (structural checks)')
            out['util'] = float(np.nanmax(u)) if u is not None else float('nan')
        except Exception:
            out['util'] = float('nan')
        return out

    def keep_design(self, label=None):
        """Snapshot the numbers on screen so the next one can be compared."""
        m = self.design_metrics()
        if m is None:
            self.status.set('Analyse first — there is nothing to keep yet.')
            return None
        m['label'] = label or ('design %d' % (len(self.designs) + 1))
        self.designs.append(m)
        self._refresh_designs()
        self.status.set('Kept as "%s". Change something and keep another to compare.'
                        % m['label'])
        return m

    def clear_designs(self):
        self.designs = []
        self._refresh_designs()

    DESIGN_COLS = (
        ('label', 'design', ''), ('t', 't', 'section_length'),
        ('tension_pa', '\u03c3t max', 'stress'), ('span_over', '\u0394 as span/', ''),
        ('tension_area', 'in tension', ''), ('steel_kg', 'steel', ''),
        ('concrete', 'concrete', ''), ('util', 'util', ''))

    def _refresh_designs(self):
        if not hasattr(self, 'design_tree'):
            return
        tv = self.design_tree
        tv.delete(*tv.get_children())
        for i, m in enumerate(self.designs):
            tv.insert('', 'end', iid=str(i), values=self._design_row(m))

    def _design_row(self, m):
        q = 'section_length'
        return (m['label'],
                '%.4g\u2013%.4g' % (units.from_si(q, m['t_min']), units.from_si(q, m['t_max'])),
                '%.3g' % units.from_si('stress', m.get('tension_pa', float('nan'))),
                ('%.0f' % m['span_over']) if np.isfinite(m['span_over']) else '\u2014',
                '%.0f%%' % (100 * m.get('tension_area', float('nan'))),
                '%.0f kg' % m['steel_kg'],
                '%.3g m\u00b3' % m['concrete'],
                '%.2f' % m['util'])

    # ══════════════════════════════════════════════════════════════════════
    #  Sweeping one number
    # ══════════════════════════════════════════════════════════════════════
    def sweep(self, name, lo, hi, steps=5, keep=True):
        """Solve across a range of one defined number and collect the metrics.

        The published shape studies are exactly this: hold everything, move
        the rise, tabulate stress, deflection and reinforcement. Every
        number in the definitions list already has a slider, so the only
        parts missing were the loop and somewhere to put the answers.

        The original value is restored even if a step fails, because a sweep
        that leaves the model at 7.5 m when it started at 7 m has quietly
        edited the design.
        """
        ws = self.model.ws
        if name not in ws.numbers():
            self.status.set('"%s" is not one of the numbers you have defined.' % name)
            return []
        original = ws.numbers()[name]
        steps = max(2, int(steps))
        rows = []
        try:
            for k in range(steps):
                v = lo + (hi - lo) * k / (steps - 1)
                self.move_slider(name, v)
                if not self.analyze():
                    self.status.set('Sweep stopped at %s = %.4g: %s' % (name, v, self.error))
                    break
                m = self.design_metrics()
                if m is None:
                    break
                m['label'] = '%s = %.4g' % (name, v)
                m['sweep_value'] = v
                rows.append(m)
        finally:
            self.move_slider(name, original)
            self.analyze()
        if keep:
            self.designs.extend(rows)
            self._refresh_designs()
        self.sweep_rows = rows
        self._draw_sweep()
        self.status.set('Swept %s from %.4g to %.4g in %d steps.' % (name, lo, hi, len(rows)))
        return rows

    def _draw_bottom(self):
        """Whichever answer the open mode wants in the shared bottom pane.

        One entry point because the pane also redraws on <Configure>, and a
        resize that quietly swapped a sweep back to a section would look
        like the sweep had failed.
        """
        if self.mode == 'design':
            self._draw_sweep()
        else:
            self._draw_section()

    def _draw_sweep(self):
        """The sweep, as four curves against the number that moved.

        Each on its own scale, normalised, because they are in different
        units and the question is which way they GO -- the published study
        reports 23%, 34% and 20% for one 30% change of rise, and those are
        directions and magnitudes, not values.
        """
        cv = getattr(self, 'sec_canvas', None)
        if cv is None:
            return
        cv.delete('all')
        rows = self.sweep_rows
        W = max(cv.winfo_width(), 420)
        H = max(cv.winfo_height(), 120)
        if len(rows) < 2:
            cv.create_text(14, 14, anchor='nw', fill='#999', font=('Helvetica', 9),
                           text='No sweep yet. Pick one of your numbers, give it a range, '
                                'and the tab solves across it.')
            return
        series = (('peak tension', 'tension_pa', '#c0561f'),
                  ('deflection', 'deflection', '#1a6bbd'),
                  ('steel', 'steel_kg', '#7b2fa8'),
                  ('concrete', 'concrete', '#2f6f4a'))
        xs = [r['sweep_value'] for r in rows]
        m, mr = 46, 120
        x0, x1 = min(xs), max(xs)
        px = lambda v: m + (v - x0) / max(x1 - x0, 1e-12) * (W - m - mr)   # noqa: E731
        top, bot = 26, H - 34
        cv.create_line(m, bot, W - mr, bot, fill='#ccd3da')
        for k, (label, key, col) in enumerate(series):
            ys = [float(r.get(key, float('nan'))) for r in rows]
            lo, hi = min(ys), max(ys)
            rng = hi - lo
            def py(v, lo=lo, rng=rng):
                return bot - (0.08 + 0.84 * ((v - lo) / rng if rng > 1e-30 else 0.5)) * (bot - top)
            pts = []
            for v, y in zip(xs, ys):
                pts += [px(v), py(y)]
            cv.create_line(*pts, fill=col, width=2, smooth=False)
            for v, y in zip(xs, ys):
                cv.create_oval(px(v) - 2.5, py(y) - 2.5, px(v) + 2.5, py(y) + 2.5,
                               fill='#ffffff', outline=col, width=1.5)
            change = '' if abs(ys[0]) < 1e-30 else ('  %+.0f%%' % (100 * (ys[-1] - ys[0]) / abs(ys[0])))
            cv.create_text(W - mr + 8, py(ys[-1]), anchor='w', fill=col,
                           font=('Helvetica', 8), text=label + change)
        for v in xs:
            cv.create_line(px(v), bot, px(v), bot + 4, fill='#98a3ac')
            cv.create_text(px(v), bot + 7, anchor='n', fill='#666', font=('Helvetica', 8),
                           text='%.4g' % v)
        cv.create_text(12, 10, anchor='nw', fill=INK if 'INK' in globals() else '#1e2429',
                       font=('Helvetica', 9, 'bold'),
                       text='%s  \u00b7  each curve on its own scale; the label says how far it moved'
                            % rows[0]['label'].split('=')[0].strip())

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
        # Two ranges can only describe a rectangle, and almost no real shell
        # has a rectangular plan. A rule over the plan cuts that rectangle
        # into one -- and it is the tab's own open item 5, "non-rectangular
        # plans (a domain rule, as Stereo has)".
        tk.Label(p, text='keep where', bg=BG, font=('Helvetica', 9),
                 anchor='w').pack(fill='x', pady=(6, 0))
        self.v_plan_rule = tk.StringVar(value=str(self.model.data.get('plan_rule', '') or ''))
        e = tk.Entry(p, textvariable=self.v_plan_rule, font=('Consolas', 9))
        e.pack(fill='x')
        e.bind('<Return>', lambda _ev: self._set_plan_rule())
        e.bind('<FocusOut>', lambda _ev: self._set_plan_rule())
        row = tk.Frame(p, bg=BG)
        row.pack(fill='x', pady=2)
        for text, rule in (('round', 'hypot(x, y) < min(a, b)/2'),
                           ('ring', 'min(a, b)/4 < hypot(x, y) < min(a, b)/2'),
                           ('L-shape', 'not (x > 0 and y > 0)'),
                           ('clear', '')):
            tk.Button(row, text=text, font=('Helvetica', 8),
                      command=lambda r=rule: (self.v_plan_rule.set(r),
                                              self._set_plan_rule())).pack(side='left', padx=(0, 3))
        tk.Label(p, text='Empty keeps the whole rectangle. An element is judged at its centre, '
                         'so the cut overshoots the line by at most one element — that overshoot '
                         'is the framing around the opening.',
                 bg=BG, fg='#888', wraplength=PANEL_W - 30, justify='left',
                 font=('Helvetica', 8), anchor='w').pack(fill='x')
        self.plan_rule_note = tk.Label(p, text='', bg=BG, fg='#666',
                                       font=('Helvetica', 8), anchor='w')
        self.plan_rule_note.pack(fill='x')
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

    def _set_plan_rule(self):
        val = self.v_plan_rule.get().strip()
        if val == str(self.model.data.get('plan_rule', '') or ''):
            return
        self.model.data['plan_rule'] = val
        self._model_changed()
        self._refresh_geometry_quietly()
        self._refresh_plan_rule_note()
        self._draw()

    def _refresh_plan_rule_note(self):
        if not hasattr(self, 'plan_rule_note'):
            return
        g = self.geom
        if g is None or g.get('kept') is None:
            self.plan_rule_note.config(text='', fg='#666')
            return
        whole = g['nx'] * g['ny']
        self.plan_rule_note.config(
            text='Plan cut: %d of %d elements removed, %d left.'
                 % (whole - len(g['elems']), whole, len(g['elems'])), fg='#666')

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
        pick = tk.LabelFrame(p, text='Pick them on the model', bg=BG,
                             font=('Helvetica', 9, 'bold'))
        pick.pack(fill='x', pady=(6, 2))
        tk.Checkbutton(pick, text='click a corner of an element to support it',
                       variable=self.v_pick, bg=BG, font=('Helvetica', 9),
                       command=self._draw).pack(anchor='w')
        tk.Label(pick, text='A corner is a node of the mesh, so this is the support itself, '
                            'not an approximation of one. What lands there is a point support '
                            'on a solid block — a shell on a true point is a singularity.',
                 bg=BG, fg='#555', wraplength=PANEL_W - 40, justify='left',
                 font=('Helvetica', 8)).pack(anchor='w', padx=4, pady=(0, 4))
        row = tk.Frame(pick, bg=BG)
        row.pack(fill='x', pady=2)
        tk.Label(row, text='holds', bg=BG, font=('Helvetica', 9)).pack(side='left')
        ttk.Combobox(row, textvariable=self.v_pick_type, state='readonly', width=9,
                     values=list(sm.SUPPORT_TYPES)).pack(side='left', padx=4)
        tk.Label(row, text='block', bg=BG, font=('Helvetica', 9)).pack(side='left')
        tk.Entry(row, textvariable=self.v_pick_block, width=5).pack(side='left', padx=4)
        tk.Label(row, text='m', bg=BG, font=('Helvetica', 9)).pack(side='left')
        row = tk.Frame(pick, bg=BG)
        row.pack(fill='x', pady=2)
        for text, what in (('four corners', 'corners'), ('whole boundary', 'boundary'),
                           ('lowest ring', 'lowest')):
            tk.Button(row, text=text, font=('Helvetica', 9),
                      command=lambda w=what: self.quick_support(w)).pack(side='left', padx=(0, 4))
        row = tk.Frame(pick, bg=BG)
        row.pack(fill='x', pady=2)
        tk.Button(row, text='switch the selected one off / on', font=('Helvetica', 9),
                  command=self.toggle_sandbox).pack(side='left')
        tk.Button(row, text='clear', font=('Helvetica', 9), fg='#a33',
                  command=self.clear_supports).pack(side='left', padx=4)
        tk.Label(pick, text='Switching one off leaves it in the model and out of the stiffness, '
                            'so you can see what it was carrying without editing the design to ask.',
                 bg=BG, fg='#555', wraplength=PANEL_W - 40, justify='left',
                 font=('Helvetica', 8)).pack(anchor='w', padx=4, pady=(0, 4))
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

    def _build_compare(self, p):
        tk.Label(p, text='Compare designs', bg=BG,
                 font=('Helvetica', 10, 'bold')).pack(anchor='w', padx=8, pady=(12, 2))
        tk.Label(p, text='Thickening, the edge beam and the concrete class are three levers on '
                         'the same shell. Keep a design after each solve and the answers sit '
                         'side by side instead of in your memory.',
                 bg=BG, fg='#555', wraplength=PANEL_W - 30, justify='left',
                 font=('Helvetica', 8)).pack(anchor='w', padx=8)
        cols = [c[0] for c in self.DESIGN_COLS]
        self.design_tree = ttk.Treeview(p, columns=cols, show='headings', height=5)
        for key, label, q in self.DESIGN_COLS:
            self.design_tree.heading(key, text=label + (('  ' + units.label(q)) if q else ''))
            self.design_tree.column(key, width=68 if key != 'label' else 86, stretch=True)
        self.design_tree.pack(fill='x', padx=8, pady=(4, 2))
        row = tk.Frame(p, bg=BG)
        row.pack(fill='x', padx=8)
        tk.Button(row, text='keep this design', font=('Helvetica', 9),
                  command=lambda: self.keep_design()).pack(side='left')
        tk.Button(row, text='clear', font=('Helvetica', 9), fg='#a33',
                  command=self.clear_designs).pack(side='left', padx=4)

        tk.Label(p, text='Sweep one number', bg=BG,
                 font=('Helvetica', 10, 'bold')).pack(anchor='w', padx=8, pady=(12, 2))
        tk.Label(p, text='Hold everything else and move one of your own numbers across a range. '
                         'Raising a dome\u2019s rise 30% has been measured to cut peak tension 23%, '
                         'deflection 34% and reinforcement 20% \u2014 no amount of thickening would '
                         'have said so.',
                 bg=BG, fg='#555', wraplength=PANEL_W - 30, justify='left',
                 font=('Helvetica', 8)).pack(anchor='w', padx=8)
        row = tk.Frame(p, bg=BG)
        row.pack(fill='x', padx=8, pady=(4, 0))
        self.v_sweep_name = tk.StringVar()
        self.sweep_box = ttk.Combobox(row, textvariable=self.v_sweep_name, state='readonly',
                                      width=6)
        self.sweep_box.pack(side='left')
        for lab, var, default in (('from', 'v_sweep_lo', '1'), ('to', 'v_sweep_hi', '4'),
                                  ('steps', 'v_sweep_n', '5')):
            tk.Label(row, text=lab, bg=BG, font=('Helvetica', 9)).pack(side='left', padx=(6, 1))
            setattr(self, var, tk.StringVar(value=default))
            tk.Entry(row, textvariable=getattr(self, var), width=4).pack(side='left')
        tk.Button(p, text='run the sweep', font=('Helvetica', 9),
                  command=self._run_sweep).pack(anchor='w', padx=8, pady=4)
        self._refresh_sweep_names()

    def _refresh_sweep_names(self):
        if not hasattr(self, 'sweep_box'):
            return
        names = sorted(self.model.ws.numbers())
        self.sweep_box.config(values=names)
        if names and self.v_sweep_name.get() not in names:
            self.v_sweep_name.set(names[0])

    def _run_sweep(self):
        try:
            lo = float(self.v_sweep_lo.get())
            hi = float(self.v_sweep_hi.get())
            n = int(float(self.v_sweep_n.get()))
        except ValueError:
            self.status.set('The sweep range and step count have to be numbers.')
            return
        self.set_mode('design')
        self.sweep(self.v_sweep_name.get(), lo, hi, n)

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
            self.mesh_note.config(text=f'  {g["nx"]} × {g["ny"]} = {len(g["elems"])} elements')
            self._refresh_plan_rule_note()
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
        self._refresh_cuts()
        self._draw_section()
        self.status.set(
            self._shape_line() +
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
            if key == 'K':
                K = ssd.gaussian_curvature(g['X'], g['ids'])
                return K[g['elems']].mean(axis=1), scale, q
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

        def face_colour(e, role):
            """One element's colour, on whichever of its faces this is."""
            col = fills[e]
            if in_head is not None and in_head[e]:
                return '#555555'
            if vals is None:
                return view3d.shade(col, lit[e])
            if role == ssd.SIDE:
                # the cut face, darkened: it is the same element, seen through
                # its thickness, and it should read as an edge rather than as a
                # neighbouring element with a different result
                return view3d.shade(col, 0.68)
            return col

        if self.v_solid.get():
            self._draw_solid(X, el, g['t'], face_colour, outline, lim)
        else:
            for e in order:
                idx = el[e]
                pts = np.stack([sx[idx], sy[idx]], axis=1)
                if np.abs(pts).max() > lim:
                    continue
                cv.create_polygon(*pts.ravel(), fill=face_colour(e, ssd.TOP),
                                  outline='#6b6b6b' if outline else face_colour(e, ssd.TOP),
                                  width=1, tags=('face', f'e{e}'))
        self._draw_structure(X, sx, sy)
        self._draw_cuts(X, sx, sy)
        self._draw_pickable_corners(X, sx, sy)
        if self.v_rulings.get():
            self._draw_rulings(X)
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
        if self.v_solid.get():
            k = float(self.v_exag.get() or 1.0)
            t = g['t']
            note = ('thickness %.0f–%.0f mm, drawn to scale'
                    % (1000 * float(np.min(t)), 1000 * float(np.max(t)))) if k == 1.0 else \
                   ('thickness %.0f–%.0f mm, DRAWN ×%g' % (1000 * float(np.min(t)),
                                                           1000 * float(np.max(t)), k))
            cv.create_text(10, (cv.winfo_height() - 22) if cv.winfo_height() > 40 else 486,
                           anchor='sw', text=note,
                           fill='#999' if k == 1.0 else BAD_C, font=('Helvetica', 8))

    def _draw_solid(self, X, el, t, face_colour, outline, lim):
        """Paint the shell as the slab it is: a top, a soffit and a band
        round every free edge.

        Three things make this cost about what the sheet cost. Faces whose
        normal points away from the camera are dropped before anything is
        drawn, which removes the soffit whenever you are above the shell and
        the top whenever you are under it -- about half of them, always. The
        corners of every face are projected in ONE call rather than per face.
        And the mesh lines go on the top faces only: drawn on the band as
        well, a 24 x 24 shell gets a second grid along its edge that reads as
        detail and is noise.
        """
        cv = self.zc.canvas
        faces = ssd.solid_faces(X, el, t, float(self.v_exag.get() or 1.0))
        poly, own, role, nrm = faces['poly'], faces['elem'], faces['role'], faces['normal']
        if not len(poly):
            return
        toward = self.cam.basis()[2]
        facing = nrm @ toward > 0.0
        cen = poly.mean(axis=1)
        order = np.argsort(self.cam.depth(cen))          # far first
        order = order[facing[order]]
        px, py = self.cam.project(poly.reshape(-1, 3))
        px = px.reshape(-1, 4)
        py = py.reshape(-1, 4)
        light = np.array([-0.45, -0.35, 0.82])
        light /= np.linalg.norm(light)
        lit = 0.55 + 0.50 * np.abs(nrm @ light) ** 1.5
        for f in order:
            xs_, ys_ = px[f], py[f]
            if np.abs(xs_).max() > lim or np.abs(ys_).max() > lim:
                continue
            e = int(own[f])
            col = face_colour(e, role[f])
            # shade the SIDE and the soffit by their own normals so the slab
            # reads as a solid; the top keeps the field colour flat, as it
            # always has, because that is the face you read numbers off
            if role[f] != ssd.TOP:
                col = view3d.shade(col, float(lit[f]))
            edge = '#6b6b6b' if (outline and role[f] == ssd.TOP) else col
            cv.create_polygon(*np.stack([xs_, ys_], axis=1).ravel(), fill=col,
                              outline=edge, width=1, tags=('face', f'e{e}'))

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
        if self.mode == 'supports' and self.v_pick.get():
            self.toggle_support_at(e.x, e.y)
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
