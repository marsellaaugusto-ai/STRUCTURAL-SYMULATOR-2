"""
beam_app.py — Beam tab: the schematic, the diagrams and the controls.

The solver moved to `beam_math.py` and the workbook to `beam_reports.py` on
2026-10-04 (R-8), leaving this file the stateful Tkinter half: widget state in,
a `beam_math.BeamModel` built from it, and the result drawn and written out.
See `beam_math.py`'s docstring for why that boundary is kept clean, and
REPORTS AND GUIDES/MODULAR_ARCHITECTURE.md for the same split in the Truss and
Perforated Beam tabs.

`BeamModel`, `BeamResult`, `export_beam_excel` and `import_beam_excel` are
re-exported here, so anything that imported them from this module before the
split -- `tests/test_excel_roundtrip.py`, and `tests/test_truss_math.py`,
which builds a BeamModel as its cross-check reference -- keeps working
unchanged.
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter import font as tkfont
import math

import units

from common import (
    _ensure_openpyxl,
    PANEL_W,
    ScrollPanel, WrapBar, UnitsMixin,
    _nice_ticks, _find_diagram_maxima, make_shape_fn, fit_caption,
    draw_moment_arrow, LoadScale, declutter_text,
)
from .beam_math import (
    BeamModel, BeamResult, _adaptive_vector_integral, _gauss_VM_integral,
)
from .beam_reports import export_beam_excel, import_beam_excel

# Names this module is expected to expose, its own plus the four re-exported
# above -- which is also what tells pyflakes those imports are deliberate.
__all__ = ['BeamApp', 'BeamModel', 'BeamResult',
           'export_beam_excel', 'import_beam_excel',
           '_adaptive_vector_integral', '_gauss_VM_integral']


class BeamApp(UnitsMixin, tk.Frame):
    """
    Beam tab — isostatic and hyperstatic beams, single and double cantilevers
    (overhangs), via the beam_math.BeamModel direct-stiffness solver.

    STORAGE units, which is what the tab holds and what a workbook written
    from it contains: lengths in m, forces in kN, moments in kN*m, distributed
    loads in kN/m, E in GPa, section I in cm^4, c (extreme fibre distance) in
    cm, areas in cm^2, stresses in kN/cm^2. That is `units.STORAGE` exactly,
    which is why STORAGE_UNITS is left at its default below. What the user
    SEES is whichever convention the selector above the notebook names, and
    `common.UnitsMixin` does that conversion -- see its docstring, which was
    written about this tab: the machinery was extracted FROM here so it would
    not be built six times, and until 2026-10-04 this tab still carried the
    original hand-rolled copy of it (R-9).
    """
    CBEAM, CSUP, CLOAD, CMOM, CDLOAD = '#333333', '#555555', '#D85A30', '#8e44ad', '#c0785a'
    CV_, CM_, CDEFL, CGRID = '#7F77DD', '#D85A30', '#1D9E75', '#e8e8e8'

    def __init__(self, master, **kw):
        super().__init__(master, bg='#f5f5f3', **kw)
        self.length = 6.0
        self.supports = []      # {'x','type'}
        self.point_loads = []   # {'x','P'}   kN, +down
        self.moments = []       # {'x','M'}   kN*m, +CCW
        self.dloads = []        # {'x1','x2','w1','w2'}  kN/m, +down
        self.nonuniform_loads = []  # {'expr','x1','x2'}  kN/m, +down, over [x1,x2] m
        self.profile = {'E': 200.0, 'I': 8000.0, 'c': 15.0, 'A': 80.0,
                        'allow_bend': 16.0, 'allow_shear': 10.0,
                        # The denominator of the span/deflection limit: 360
                        # means L/360. Dimensionless, so the unit selector
                        # leaves it alone. 0 means "do not check".
                        'defl_ratio': 360.0}
        self.result = None
        self.model = None
        # Before _build_ui, because the widgets register themselves with the
        # mixin as they are created. Nothing in the model changes when the
        # convention does -- only how it is written -- so `repaint` only has
        # to redraw what the mixin does not own: the tables, the results text
        # and the diagrams. The mixin drops its own listener when this tab
        # stops existing, so a destroyed tab cannot be left repainting.
        self.init_units(repaint=self._on_units_changed)
        self._build_ui()
        self._draw_schematic()


    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        tb = tk.Frame(self, bg='#ebebea')
        tb.pack(fill='x', padx=6, pady=(6, 0))
        self.unit_label(
            tk.Label(tb, bg='#ebebea', font=('Helvetica', 11)),
            lambda: f'Beam length ({self.u("length")}):').pack(side='left', padx=(4, 2))
        # Every Variable in this tab names its master explicitly. Without
        # one, tkinter binds it to its module-global default root, which is
        # the same interpreter as this widget in the running app -- but not
        # where several roots exist, and then an Entry writes into one
        # interpreter's copy of the variable while .get() reads another's.
        # Found 2026-10-04: the non-uniform load dialog read stale values
        # under the test suite for exactly this reason (R-4/R-9).
        self.len_var = self.unit_var(
            tk.DoubleVar(master=self, value=self.length), 'length')
        tk.Entry(tb, textvariable=self.len_var, width=7, font=('Helvetica', 11)).pack(side='left')
        tk.Button(tb, text='Set length', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), command=self._set_length).pack(side='left', padx=4)
        tk.Frame(tb, width=1, bg='#ccc').pack(side='left', fill='y', padx=6, pady=3)
        tk.Button(tb, text='Example: cantilever', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), command=self._load_example_cantilever).pack(side='left', padx=2)
        tk.Button(tb, text='Example: double overhang', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), command=self._load_example_overhang).pack(side='left', padx=2)
        tk.Button(tb, text='Example: continuous (hyperstatic)', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), command=self._load_example_continuous).pack(side='left', padx=2)
        tk.Button(tb, text='Clear', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), command=self._clear_all).pack(side='left', padx=2)
        tk.Frame(tb, width=1, bg='#ccc').pack(side='left', fill='y', padx=6, pady=3)
        tk.Button(tb, text='Export Excel', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), fg='#1a6bbd', command=self._export_excel).pack(side='left', padx=2)
        tk.Button(tb, text='Import Excel', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), fg='#1a6bbd', command=self._import_excel).pack(side='left', padx=2)
        tk.Frame(tb, width=1, bg='#ccc').pack(side='left', fill='y', padx=6, pady=3)
        tk.Button(tb, text='▶ Analyze', relief='flat', bd=0, padx=10, pady=4,
                  bg='#1a6bbd', fg='white', font=('Helvetica', 11, 'bold'),
                  command=self._analyze).pack(side='left', padx=2)

        main = tk.Frame(self, bg='#f5f5f3')
        main.pack(fill='both', expand=True, padx=6, pady=6)

        # Right panel FIRST, expanding content SECOND. Tk's pack hands each
        # slave a parcel in packing order, so the previous order (content
        # first, expand=True) left the panel whatever the content did not
        # want -- which at narrow widths was nothing, and the panel was
        # unmapped entirely with no scrollbar and no error. ScrollPanel also
        # scrolls horizontally, so a row wider than the panel stays reachable
        # instead of being clipped mid-widget.
        self.panel_outer = ScrollPanel(main, width=PANEL_W + 105, bg='#f0f0ee',
                                        bd=1, relief='solid')
        self.panel_outer.pack(side='right', fill='y', padx=(6, 0))

        left = tk.Frame(main, bg='#f5f5f3')
        left.pack(side='left', fill='both', expand=True)

        tk.Label(left, text='Beam schematic', bg='#f5f5f3', font=('Helvetica', 9, 'bold'), fg='#777').pack(anchor='w')
        self.schem = tk.Canvas(left, bg='white', height=160, bd=1, relief='solid', highlightthickness=0)
        self.schem.pack(fill='x', pady=(0, 8))
        self.schem.bind('<Configure>', lambda e: self._draw_schematic())

        diag_hdr = tk.Frame(left, bg='#f5f5f3')
        diag_hdr.pack(fill='x')
        tk.Label(diag_hdr, text='Diagrams — shear V, moment M, deflection (run ▶ Analyze)', bg='#f5f5f3',
                 font=('Helvetica', 9, 'bold'), fg='#777').pack(side='left')
        self.reverse_bmd_var = tk.BooleanVar(master=self, value=False)
        tk.Checkbutton(diag_hdr, text='Reverse BMD (sagging down / hogging up)',
                       variable=self.reverse_bmd_var, bg='#f5f5f3', font=('Helvetica', 8),
                       command=self._draw_diagrams).pack(side='left', padx=(14, 0))
        self.diag_canvas = tk.Canvas(left, bg='#fafaf8', height=420, bd=1, relief='solid', highlightthickness=0)
        self.diag_canvas.pack(fill='both', expand=True)
        self.diag_canvas.bind('<Configure>', lambda e: self._draw_diagrams())

        self._build_panel(self.panel_outer.interior)
        self._label_tree_columns()
        # Adopt whatever width the panel's own content needs, so nothing
        # starts life behind the horizontal scrollbar.
        self.panel_outer.fit_to_content()

        # The toolbar was one long row of pack(side='left') calls, so its tail
        # ran off the right edge. WrapBar flows those same widgets across as
        # many rows as the width needs, without restructuring how they were
        # built. The same <Configure> drives the panel width, so the two can
        # never disagree about how wide the window currently is.
        self.toolbar_wrap = WrapBar(tb)
        self.toolbar_wrap.start()
        self.bind('<Configure>', self._on_root_configure, add='+')
        self.after_idle(lambda: self._on_root_configure(None))

    def _on_root_configure(self, _event=None):
        """Resize the right panel to match the window. Content that no longer
        fits stays reachable through ScrollPanel's horizontal scrollbar, so
        this can never hide a control -- unlike the previous fixed-width
        panel, which was simply dropped."""
        try:
            self.panel_outer.apply_responsive_width(self.winfo_width())
        except Exception:
            pass

    def _build_panel(self, panel):
        pad = dict(padx=8, pady=(8, 2))

        tk.Label(panel, text='SUPPORTS', bg='#f0f0ee', font=('Helvetica', 10, 'bold')).pack(anchor='w', **pad)
        self.sup_tree = ttk.Treeview(panel, columns=('x', 'type'), show='headings', height=4)
        self.sup_tree.column('x', width=70)
        self.sup_tree.column('type', width=100)
        self.sup_tree.pack(fill='x', padx=8)
        sf = tk.Frame(panel, bg='#f0f0ee'); sf.pack(fill='x', padx=8, pady=(2, 8))
        tk.Button(sf, text='Add', command=self._add_support).pack(side='left', padx=2)
        tk.Button(sf, text='Delete', command=lambda: self._del_row(self.sup_tree, self.supports)).pack(side='left', padx=2)

        self.unit_label(
            tk.Label(panel, bg='#f0f0ee', font=('Helvetica', 10, 'bold')),
            lambda: f'POINT LOADS (+down, {self.u("force")})'
        ).pack(anchor='w', **pad)
        self.pl_tree = ttk.Treeview(panel, columns=('x', 'P'), show='headings', height=3)
        self.pl_tree.column('x', width=70)
        self.pl_tree.column('P', width=100)
        self.pl_tree.pack(fill='x', padx=8)
        pf = tk.Frame(panel, bg='#f0f0ee'); pf.pack(fill='x', padx=8, pady=(2, 8))
        tk.Button(pf, text='Add', command=self._add_pointload).pack(side='left', padx=2)
        tk.Button(pf, text='Delete', command=lambda: self._del_row(self.pl_tree, self.point_loads)).pack(side='left', padx=2)

        self.unit_label(
            tk.Label(panel, bg='#f0f0ee', font=('Helvetica', 10, 'bold')),
            lambda: f'POINT MOMENTS (+CCW, {self.u("moment")})'
        ).pack(anchor='w', **pad)
        self.mm_tree = ttk.Treeview(panel, columns=('x', 'M'), show='headings', height=2)
        self.mm_tree.column('x', width=70)
        self.mm_tree.column('M', width=100)
        self.mm_tree.pack(fill='x', padx=8)
        mf = tk.Frame(panel, bg='#f0f0ee'); mf.pack(fill='x', padx=8, pady=(2, 8))
        tk.Button(mf, text='Add', command=self._add_moment).pack(side='left', padx=2)
        tk.Button(mf, text='Delete', command=lambda: self._del_row(self.mm_tree, self.moments)).pack(side='left', padx=2)

        self.unit_label(
            tk.Label(panel, bg='#f0f0ee', font=('Helvetica', 10, 'bold')),
            lambda: f'DISTRIBUTED LOADS (+down, {self.u("line_load")})'
        ).pack(anchor='w', **pad)
        self.dl_tree = ttk.Treeview(panel, columns=('x1', 'x2', 'w1', 'w2'), show='headings', height=3)
        for c, w in [('x1', 70), ('x2', 70), ('w1', 80), ('w2', 80)]:
            self.dl_tree.column(c, width=w)
        self.dl_tree.pack(fill='x', padx=8)
        df = tk.Frame(panel, bg='#f0f0ee'); df.pack(fill='x', padx=8, pady=(2, 8))
        tk.Button(df, text='Add', command=self._add_dload).pack(side='left', padx=2)
        tk.Button(df, text='Delete', command=lambda: self._del_row(self.dl_tree, self.dloads)).pack(side='left', padx=2)

        tk.Label(panel, text='NON-UNIFORM DISTRIBUTED LOADS', bg='#f0f0ee',
                 font=('Helvetica', 10, 'bold')).pack(anchor='w', **pad)
        self.unit_label(
            tk.Label(panel, bg='#f0f0ee', font=('Helvetica', 8), fg='#777',
                     justify='left'),
            self._ndl_hint_text).pack(anchor='w', padx=8)
        self.ndl_tree = ttk.Treeview(panel, columns=('expr', 'x1', 'x2'), show='headings', height=3)
        for c, w in [('expr', 130), ('x1', 70), ('x2', 70)]:
            self.ndl_tree.column(c, width=w)
        self.ndl_tree.pack(fill='x', padx=8)
        ndf = tk.Frame(panel, bg='#f0f0ee'); ndf.pack(fill='x', padx=8, pady=(2, 8))
        tk.Button(ndf, text='Add', command=self._add_nonuniform_load).pack(side='left', padx=2)
        tk.Button(ndf, text='Delete',
                  command=lambda: self._del_row(self.ndl_tree, self.nonuniform_loads)).pack(side='left', padx=2)

        tk.Label(panel, text='CROSS-SECTION / MATERIAL', bg='#f0f0ee', font=('Helvetica', 10, 'bold')).pack(anchor='w', **pad)
        sec = tk.Frame(panel, bg='#f0f0ee'); sec.pack(fill='x', padx=8)
        self.sec_vars = {}
        for i, key in enumerate(self.SECTION_FIELDS):
            self.unit_label(
                tk.Label(sec, bg='#f0f0ee', font=('Helvetica', 9)),
                lambda k=key: self._sec_label(k),
            ).grid(row=i, column=0, sticky='w', pady=1)
            # The box holds the STORAGE value and the mixin writes it in the
            # selected convention; `unit_value` reads the exact stored figure
            # back, so a switch there and back cannot round-trip 200 GPa into
            # 199.99999 (see UnitsMixin.unit_value).
            quantity = self._FIELD_Q[key]
            v = tk.DoubleVar(master=sec, value=self.profile[key])
            if quantity is not None:
                self.unit_var(v, quantity)
            self.sec_vars[key] = v
            tk.Entry(sec, textvariable=v, width=8, font=('Helvetica', 9)).grid(row=i, column=1, pady=1, padx=4)

        tk.Label(panel, text='RESULTS', bg='#f0f0ee', font=('Helvetica', 10, 'bold')).pack(anchor='w', **pad)
        self.res_text = tk.Text(panel, height=16, bg='white', font=('Courier', 9), relief='solid', bd=1)
        self.res_text.pack(fill='both', expand=True, padx=8, pady=(2, 10))

    # ── row management ──────────────────────────────────────────────────────
    def _del_row(self, tree, data_list):
        sel = tree.selection()
        if not sel:
            return
        idx = tree.index(sel[0])
        del data_list[idx]
        self._refresh_tables()

    # Which physical quantity each model field is, so one table refresh can
    # convert every column without a per-column special case. This is the only
    # thing UnitsMixin asks a tab to supply, and it covers the section fields
    # too -- they were a second map with a parallel set of _sec_shown /
    # _sec_stored accessors until 2026-10-04 (R-9). Fields that are not
    # numbers (a support type, a q(x) expression) map to None and pass
    # through untouched.
    _FIELD_Q = {'x': 'length', 'x1': 'length', 'x2': 'length',
                'P': 'force', 'M': 'moment',
                'w1': 'line_load', 'w2': 'line_load',
                'type': None, 'expr': None,
                'E': 'modulus', 'I': 'inertia', 'c': 'section_length',
                'A': 'area', 'allow_bend': 'stress', 'allow_shear': 'stress',
                'defl_ratio': None}

    # The section/material boxes, in the order they are shown, and how each
    # one is named. One source for the widget label AND for the message when
    # that box cannot be read (R-5/R-6), so the two can never disagree about
    # which field the user is being told about.
    SECTION_FIELDS = ('E', 'I', 'c', 'A', 'allow_bend', 'allow_shear',
                      'defl_ratio')
    _SECTION_NAMES = {'E': 'E', 'I': 'I', 'c': 'c',
                      'A': 'Shear area',
                      'allow_bend': 'Allow. bending \u03c3',
                      'allow_shear': 'Allow. shear \u03c4',
                      'defl_ratio': 'Deflection limit L/'}

    def _sec_label(self, key):
        if key == 'defl_ratio':             # dimensionless; L/360, not L/360 m
            return f'{self._SECTION_NAMES[key]}'
        extra = ', extreme fiber' if key == 'c' else ''
        return f'{self._SECTION_NAMES[key]} ({self._u(key)}{extra})'

    def _on_units_changed(self):
        """Repaint what the mixin does not own.

        It has already converted the registered entry boxes and repainted
        every label that names a unit, so what is left is this tab's own
        furniture: the tree headings, the tables, and the results text and
        diagrams if there is a result to redraw.
        """
        self._label_tree_columns()
        self._refresh_tables()
        if self.result is not None:
            self._show_results()
            self._draw_diagrams()

    # ── reading what the user typed ─────────────────────────────────────────
    def _num(self, var, label):
        """A number out of an entry box, or a ValueError that names the box.

        `tk.DoubleVar.get()` raises TclError the moment its box holds anything
        that is not a float, and the message it raises -- *expected
        floating-point number but got "abc"* -- does not say WHICH box. Worse,
        `_set_length` and both Add dialogs read these unguarded, so the
        exception escaped into the Tk callback: the length did not change and
        NOTHING WAS SAID. In a double-clicked app that traceback goes to a
        console nobody sees (2026-10-04, R-6).
        """
        try:
            value = float(var.get())
        except Exception:
            # The raw text, so the message can quote what was actually
            # typed. Read through this tab's interpreter first and the
            # variable's own second -- these agree now that every Variable
            # here names its master, and the fallback costs two lines against
            # the day one does not.
            raw = ''
            for interp in (self, getattr(var, '_root', None)):
                try:
                    raw = str(interp.globalgetvar(str(var)))
                    break
                except Exception:
                    continue
            raise ValueError(
                f'{label} must be a number'
                + (f' — got "{raw}".' if raw else ' — the box is empty.')
            ) from None
        if not math.isfinite(value):
            raise ValueError(f'{label} must be a finite number; got {value:g}.')
        return value

    def _typed_length(self):
        """The beam length as currently typed, in storage units."""
        self._num(self.len_var, 'Beam length')     # names the box if unreadable
        return self.unit_value(self.len_var, self.length)

    def _typed_profile(self):
        """The section/material fields as currently typed, in storage units."""
        out = {}
        for key, var in self.sec_vars.items():
            # _num first, so garbage in a box is reported against that box's
            # own name (R-6); unit_value second, because it returns the exact
            # figure behind the box rather than the rounded one shown in it.
            value = self._num(var, self._sec_label(key))
            out[key] = (self.unit_value(var, self.profile[key])
                        if self._FIELD_Q[key] is not None else value)
        return out

    # ── entries that are no longer on the beam ──────────────────────────────
    # The Add dialogs refuse an off-beam station (B-5, fixed 2026-09-10), but
    # SHORTENING the beam could still strand entries that were legal when they
    # were entered: Analyze then failed wholesale, naming whichever one it
    # reached first, and nothing marked the offending rows (R-7).
    _STRAY_TABLES = (
        ('support', 'supports', ('x',)),
        ('point load', 'point_loads', ('x',)),
        ('moment', 'moments', ('x',)),
        ('distributed load', 'dloads', ('x1', 'x2')),
        ('distributed load', 'nonuniform_loads', ('x1', 'x2')),
    )

    def _entries_off_beam(self, length=None):
        """Every entry with a station outside [0, length], newest last.

        One entry can be listed once per off-beam end, which is deliberate: a
        distributed load with both ends past the new right-hand end is a
        different problem from one that merely overhangs it.
        """
        L = self.length if length is None else length
        tol = 1e-9 * max(1.0, abs(L))
        out = []
        for kind, attr, keys in self._STRAY_TABLES:
            for i, row in enumerate(getattr(self, attr)):
                for key in keys:
                    x = row.get(key)
                    if isinstance(x, (int, float)) and not (-tol <= x <= L + tol):
                        out.append({'kind': kind, 'attr': attr, 'index': i,
                                    'key': key, 'x': float(x)})
        return out

    def _stray_label(self, stray):
        """One stranded entry, as the user sees it in its own table."""
        n = stray['index'] + 1
        return (f"{stray['kind']} {n} at "
                f"{self._shown('x', stray['x']):.2f} {self._u('x')}")

    def _apply_length(self, length, strays='cancel'):
        """Set the beam length, dealing with whatever falls off it.

        `strays` is 'delete', 'clamp' or 'cancel'. Returns True if the length
        was applied. Kept separate from `_set_length` so the policy can be
        chosen by a caller -- a test, or the question the tab asks the user --
        rather than decided inside a modal dialog.
        """
        pending = self._entries_off_beam(length)
        if pending:
            if strays == 'cancel':
                return False
            if strays == 'delete':
                for attr in {s['attr'] for s in pending}:
                    drop = {s['index'] for s in pending if s['attr'] == attr}
                    rows = getattr(self, attr)
                    setattr(self, attr, [r for i, r in enumerate(rows)
                                         if i not in drop])
            elif strays == 'clamp':
                for s in pending:
                    row = getattr(self, s['attr'])[s['index']]
                    row[s['key']] = min(max(row[s['key']], 0.0), length)
                # A segment entirely beyond the new end clamps to zero width
                # and then carries no load at all. A silent no-op row is the
                # very thing this finding is about, so it goes.
                for attr in ('dloads', 'nonuniform_loads'):
                    setattr(self, attr, [
                        d for d in getattr(self, attr)
                        if abs(d['x2'] - d['x1']) > 1e-9 * max(1.0, abs(length))])
            else:
                raise ValueError(f'unknown stray policy {strays!r}')
        self.length = length
        self.len_var.set(self._shown('x', length))
        self._refresh_tables()
        return True

    def _ask_stray_policy(self, strays):
        """Ask what to do with entries the new length would strand.

        A method of its own so a test can answer it without driving a modal
        dialog, and so the decision is made ONCE for the whole set rather than
        row by row.
        """
        listed = '\n'.join(f'  • {self._stray_label(s)}' for s in strays[:8])
        if len(strays) > 8:
            listed += f'\n  • ... and {len(strays) - 8} more'
        win = tk.Toplevel(self)
        win.title('Entries beyond the new beam length')
        win.configure(bg='#f0f0ee')
        win.grab_set()
        tk.Label(win, bg='#f0f0ee', justify='left', font=('Helvetica', 10),
                 text=(f'{len(strays)} entr' + ('y' if len(strays) == 1 else 'ies')
                       + ' would lie beyond the new beam length of '
                       + f"{self._shown('x', getattr(self, 'length_pending', self.length)):.2f} "
                       + f'{self._u("x")}:')).pack(anchor='w', padx=12, pady=(12, 2))
        tk.Label(win, text=listed, bg='#f0f0ee', justify='left',
                 font=('Courier', 9)).pack(anchor='w', padx=12)
        choice = {'value': 'cancel'}

        def pick(value):
            choice['value'] = value
            win.destroy()

        row = tk.Frame(win, bg='#f0f0ee')
        row.pack(fill='x', padx=12, pady=12)
        for text, value in [('Delete them', 'delete'),
                            ('Move them onto the beam', 'clamp'),
                            ('Cancel', 'cancel')]:
            tk.Button(row, text=text, width=22,
                      command=lambda v=value: pick(v)).pack(side='left', padx=3)
        win.wait_window()
        return choice['value']

    def _ndl_hint_text(self):
        """What a q(x) expression is written in, said in so many words.

        The expression is stored verbatim, so its units CANNOT follow the
        Units selector: if they did, switching convention would silently
        change the load -- the one property units.py exists to guarantee can
        never happen (see its module docstring). So it is always in the app's
        storage units, and the tab says so whichever convention is selected,
        exactly as the Arch tab's own q(x) dialog does. The sub-domain is an
        ordinary pair of stations and does follow the selector, like every
        other station in this tab.
        """
        return (f"q(x) in {units.STORAGE.label('line_load')} (+down), with x "
                f"and L in {units.STORAGE.label('length')} \u2014 these do not "
                f"follow the Units selector,\nbecause the expression is stored "
                f"as written. Its sub-domain [x\u2081,x\u2082] is in "
                f"{self._u('x')}.")

    # Every table column that carries a unit, named in one place so none can
    # be forgotten on a switch -- the distributed-load columns read a bare
    # 'x1 x2 w1 w2', with no unit in any convention, until 2026-10-04 (R-9).
    # A ttk heading is not a widget `config`, so these cannot go through
    # UnitsMixin.unit_label and are repainted from _on_units_changed instead.
    _TREE_COLUMNS = (
        ('sup_tree',  (('x', 'x', 'x'),)),
        ('pl_tree',   (('x', 'x', 'x'), ('P', 'P', 'P'))),
        ('mm_tree',   (('x', 'x', 'x'), ('M', 'M', 'M'))),
        ('dl_tree',   (('x1', 'x\u2081', 'x1'), ('x2', 'x\u2082', 'x2'),
                       ('w1', 'w\u2081', 'w1'), ('w2', 'w\u2082', 'w2'))),
        ('ndl_tree',  (('x1', 'x\u2081', 'x1'), ('x2', 'x\u2082', 'x2'))),
    )

    def _label_tree_columns(self):
        for attr, columns in self._TREE_COLUMNS:
            tree = getattr(self, attr, None)
            if tree is None:
                continue
            for column, name, field in columns:
                tree.heading(column, text=f'{name} ({self._u(field)})')
        self.sup_tree.heading('type', text='Type')
        self.ndl_tree.heading('expr', text='q(x)')

    def _refresh_tables(self):
        for tree, rows, cols in [
            (self.sup_tree, self.supports, ('x', 'type')),
            (self.pl_tree, self.point_loads, ('x', 'P')),
            (self.mm_tree, self.moments, ('x', 'M')),
            (self.dl_tree, self.dloads, ('x1', 'x2', 'w1', 'w2')),
            (self.ndl_tree, self.nonuniform_loads, ('expr', 'x1', 'x2')),
        ]:
            tree.delete(*tree.get_children())
            # Visible before Analyze, not only in an error message afterwards.
            tree.tag_configure('stray', background='#ffe4e1', foreground='#a33')
            stray_rows = {s['index'] for s in self._entries_off_beam()
                          if getattr(self, s['attr']) is rows}
            for i, r in enumerate(rows):
                vals = []
                for c in cols:
                    v = self._shown(c, r[c])
                    vals.append(f'{v:g}' if isinstance(v, float) else v)
                tree.insert('', 'end', values=tuple(vals),
                            tags=('stray',) if i in stray_rows else ())
        self._draw_schematic()

    def _ask(self, title, fields):
        win = tk.Toplevel(self); win.title(title); win.grab_set()
        win.configure(bg='#f0f0ee')
        vars_ = {}
        for i, (key, label, default) in enumerate(fields):
            tk.Label(win, text=label, bg='#f0f0ee').grid(row=i, column=0, sticky='w', padx=8, pady=4)
            v = (tk.DoubleVar(master=win, value=default)
                 if not isinstance(default, str)
                 else tk.StringVar(master=win, value=default))
            vars_[key] = v
            if isinstance(default, str):
                cb = ttk.Combobox(win, textvariable=v, values=['pin', 'roller', 'fixed', 'guided'],
                                   width=10, state='readonly')
                cb.grid(row=i, column=1, padx=8, pady=4)
            else:
                tk.Entry(win, textvariable=v, width=10).grid(row=i, column=1, padx=8, pady=4)
        result = {}
        labels = {key: label for key, label, _ in fields}

        def ok():
            # A bad number used to raise TclError straight out of this
            # callback: the dialog stayed open with no explanation and no row
            # was added (R-6). Say which field, and keep the dialog open so
            # the number can be fixed where it was typed.
            values = {}
            for k, v in vars_.items():
                if isinstance(v, tk.StringVar):
                    values[k] = v.get()
                    continue
                try:
                    values[k] = self._num(v, labels.get(k, k))
                except ValueError as e:
                    messagebox.showwarning(title, str(e))
                    return
            result.update(values)
            win.destroy()
        tk.Button(win, text='OK', command=ok, bg='#1a6bbd', fg='white').grid(
            row=len(fields), column=0, columnspan=2, pady=8)
        win.wait_window()
        return result if result else None

    def _on_beam(self, r, *keys):
        """True if every named coordinate in a dialog result is on the beam.

        The dialogs took whatever was typed and appended it unchecked, so a
        mistyped station silently changed the structure being analysed
        (finding B-5). BeamModel refuses these too; catching it here means the
        user is told while the number is still in front of them, rather than
        at Analyze.
        """
        if not r:
            return False
        # The same tolerance BeamModel._on_beam uses, and for the same reason
        # doubled here: a station at the beam's own end does not survive a
        # round trip through a non-metric convention exactly. 6 m written as
        # 19.68503937007874 ft converts back to 6.000000000000001 m, so an
        # exact comparison REFUSED a load at the far end of the beam with
        # "19.69 is not on the beam, which spans 0 to 6" (found 2026-10-04
        # while fixing R-4). Anything inside the tolerance is snapped onto the
        # end, so the stored model -- and the workbook written from it -- holds
        # a clean 6.0 rather than that 1-in-10^16 overshoot.
        tol = 1e-9 * max(1.0, abs(self.length))
        for k in keys:
            x = r.get(k)
            if x is None:
                continue
            if not (-tol <= x <= self.length + tol):
                messagebox.showwarning(
                    'Off the beam',
                    f"{k} = {self._shown('x', x):g} {self._u('x')} is not on "
                    f"the beam, which spans 0 to "
                    f"{self._shown('x', self.length):g} {self._u('x')}."
                    f'\n\nNothing was added. Move it onto the '
                    f'beam, or set the beam length first.')
                return False
            r[k] = min(max(x, 0.0), self.length)
        return True

    def _add_support(self):
        r = self._ask('Add support',
                      [('x', f'x ({self._u("x")})',
                        self._shown('x', self.length / 2)), ('type', 'Type', 'pin')])
        if r:
            r['x'] = self._stored('x', r['x'])
        if self._on_beam(r, 'x'): self.supports.append(r); self._refresh_tables()

    def _add_pointload(self):
        r = self._ask('Add point load',
                      [('x', f'x ({self._u("x")})', self._shown('x', self.length / 2)),
                       ('P', f'P ({self._u("P")}, +down)', self._shown('P', 10.0))])
        if r:
            r['x'] = self._stored('x', r['x']); r['P'] = self._stored('P', r['P'])
        if self._on_beam(r, 'x'): self.point_loads.append(r); self._refresh_tables()

    def _add_moment(self):
        r = self._ask('Add point moment',
                      [('x', f'x ({self._u("x")})', self._shown('x', self.length / 2)),
                       ('M', f'M ({self._u("M")}, +CCW)', self._shown('M', 10.0))])
        if r:
            r['x'] = self._stored('x', r['x']); r['M'] = self._stored('M', r['M'])
        if self._on_beam(r, 'x'): self.moments.append(r); self._refresh_tables()

    def _add_dload(self):
        r = self._ask('Add distributed load', [
            ('x1', f'x1 ({self._u("x1")})', 0.0),
            ('x2', f'x2 ({self._u("x2")})', self._shown('x2', self.length)),
            ('w1', f'w1 ({self._u("w1")}, +down)', self._shown('w1', 5.0)),
            ('w2', f'w2 ({self._u("w2")}, +down)', self._shown('w2', 5.0))])
        if r:
            for k in ('x1', 'x2', 'w1', 'w2'):
                r[k] = self._stored(k, r[k])
        if self._on_beam(r, 'x1', 'x2'):
            if r['x2'] < r['x1']:      # entered right-to-left; the intensities
                r = dict(r, x1=r['x2'], x2=r['x1'], w1=r['w2'], w2=r['w1'])
            self.dloads.append(r); self._refresh_tables()

    def _add_nonuniform_load(self):
        win = tk.Toplevel(self); win.title('Add non-uniform distributed load'); win.grab_set()
        win.configure(bg='#f0f0ee')
        # The expression is in STORAGE units and says so, in both
        # conventions -- see _ndl_hint_text for why it cannot follow the
        # selector. The sub-domain is an ordinary pair of stations and does.
        tk.Label(win, text=f'q(x) in {units.STORAGE.label("line_load")}, +down, '
                           f'with x and L in {units.STORAGE.label("length")}'
                           f'  (^ or ** = power):',
                 bg='#f0f0ee',
                 font=('Helvetica', 9)).grid(row=0, column=0, columnspan=2, sticky='w', padx=8, pady=(8, 2))
        expr_var = tk.StringVar(master=win, value='10*sin(pi*x/L)')
        tk.Entry(win, textvariable=expr_var, width=28, font=('Helvetica', 9)).grid(
            row=1, column=0, columnspan=2, sticky='we', padx=8, pady=2)

        tk.Label(win, text=f'x\u2081 ({self._u("x")}):', bg='#f0f0ee',
                 font=('Helvetica', 9)).grid(
            row=2, column=0, sticky='w', padx=8, pady=4)
        x1_var = tk.DoubleVar(master=win, value=self._shown('x1', 0.0))
        tk.Entry(win, textvariable=x1_var, width=10).grid(row=2, column=1, padx=8, pady=4)

        tk.Label(win, text=f'x\u2082 ({self._u("x")}):', bg='#f0f0ee',
                 font=('Helvetica', 9)).grid(
            row=3, column=0, sticky='w', padx=8, pady=4)
        x2_var = tk.DoubleVar(master=win, value=self._shown('x2', self.length))
        tk.Entry(win, textvariable=x2_var, width=10).grid(row=3, column=1, padx=8, pady=4)

        result = {}

        def ok():
            expr = expr_var.get().strip()
            try:
                x1_ = self._stored('x1', self._num(x1_var, 'x\u2081'))
                x2_ = self._stored('x2', self._num(x2_var, 'x\u2082'))
            except ValueError as e:
                messagebox.showwarning('Add non-uniform distributed load',
                                       str(e))
                return
            # The same check every other load type got in the B-5 fix. This
            # one skipped it, and _analyze then CLAMPED the domain instead:
            # a load entered over 0-99 m on a 6 m beam quietly became a load
            # over 0-6 m (R-4).
            domain = {'x\u2081': x1_, 'x\u2082': x2_}
            if not self._on_beam(domain, 'x\u2081', 'x\u2082'):
                return
            x1_, x2_ = domain['x\u2081'], domain['x\u2082']
            if x2_ < x1_:               # entered right to left
                x1_, x2_ = x2_, x1_
            try:
                ctx = {'L': self._typed_length()}
                x_mid = (x1_ + x2_) / 2
                make_shape_fn(expr, ctx)(x_mid)   # validate it compiles & evaluates
            except Exception as e:
                messagebox.showerror('Invalid expression', str(e)); return
            result['expr'] = expr
            result['x1'] = x1_
            result['x2'] = x2_
            win.destroy()

        tk.Button(win, text='OK', command=ok, bg='#1a6bbd', fg='white').grid(
            row=4, column=0, columnspan=2, pady=8)
        win.wait_window()
        if result:
            self.nonuniform_loads.append(result)
            self._refresh_tables()

    def _set_length(self):
        try:
            length = self._typed_length()
            BeamModel._valid_length(length)
        except ValueError as e:
            messagebox.showwarning('Beam length', str(e))
            self.len_var.set(self._shown('x', self.length))
            return
        strays = self._entries_off_beam(length)
        policy = 'delete'
        if strays:
            # self.length is still the OLD length here, which is what the
            # dialog needs to quote the new one against.
            self.length_pending = length
            policy = self._ask_stray_policy(strays)
        if not self._apply_length(length, strays=policy):
            self.len_var.set(self._shown('x', self.length))
            return
        self._draw_schematic()

    def _clear_all(self):
        self.supports = []; self.point_loads = []; self.moments = []; self.dloads = []
        self.nonuniform_loads = []
        self.result = None; self.model = None
        self._refresh_tables()
        self.res_text.delete('1.0', 'end')
        self.diag_canvas.delete('all')

    # ── Excel export / import ────────────────────────────────────────────────
    def _current_state(self):
        return {
            'length': self._typed_length(),
            'supports': self.supports, 'point_loads': self.point_loads,
            'moments': self.moments, 'dloads': self.dloads,
            'nonuniform_loads': self.nonuniform_loads,
            'profile': self._typed_profile(),
        }

    def _export_excel(self):
        if not _ensure_openpyxl():
            messagebox.showerror(
                'Missing library',
                'Could not install openpyxl automatically.\n\n'
                'Please open a terminal and run:\n'
                '    pip install openpyxl\n'
                'then try again.')
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.xlsx',
            filetypes=[('Excel workbook', '*.xlsx')],
            initialfile='beam_report.xlsx',
            title='Save Excel report')
        if not path:
            return
        try:
            export_beam_excel(self._current_state(), path,
                               result=self.result, model=self.model)
            messagebox.showinfo(
                'Exported', f'Report saved to:\n{path}\n\n'
                'Includes a "Model" sheet — use "Import" to rebuild this '
                'exact beam from the file later.' +
                ('' if self.result else '\n\n(Run ▶ Analyze first to also '
                                         'include a "Results" sheet next time.)'))
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
            filetypes=[('Excel workbook', '*.xlsx')],
            title='Import beam from Excel')
        if not path:
            return
        try:
            st = import_beam_excel(path)
        except Exception as e:
            messagebox.showerror('Import failed', str(e)); return

        self._clear_all()
        self.length = st['length']; self.len_var.set(self._shown('x', st['length']))
        self.supports = st['supports']
        self.point_loads = st['point_loads']
        self.moments = st['moments']
        self.dloads = st['dloads']
        self.nonuniform_loads = st['nonuniform_loads']
        for k, v in st['profile'].items():
            if k in self.sec_vars:
                self.set_unit_value(self.sec_vars[k], v)
                self.profile[k] = v
        self._refresh_tables()
        self._draw_schematic()

    # ── examples ─────────────────────────────────────────────────────────────
    def _load_example_cantilever(self):
        self._clear_all()
        self.length = 4.0; self.len_var.set(self._shown('x', 4.0))
        self.supports = [{'x': 0.0, 'type': 'fixed'}]
        self.point_loads = [{'x': 4.0, 'P': 15.0}]
        self._refresh_tables()

    def _load_example_overhang(self):
        self._clear_all()
        self.length = 10.0; self.len_var.set(self._shown('x', 10.0))
        self.supports = [{'x': 2.0, 'type': 'pin'}, {'x': 8.0, 'type': 'roller'}]
        self.dloads = [{'x1': 0.0, 'x2': 10.0, 'w1': 6.0, 'w2': 6.0}]
        self._refresh_tables()

    def _load_example_continuous(self):
        self._clear_all()
        self.length = 10.0; self.len_var.set(self._shown('x', 10.0))
        self.supports = [{'x': 0.0, 'type': 'pin'}, {'x': 5.0, 'type': 'roller'},
                         {'x': 10.0, 'type': 'roller'}]
        self.dloads = [{'x1': 0.0, 'x2': 10.0, 'w1': 8.0, 'w2': 8.0}]
        self._refresh_tables()

    # ── analysis ─────────────────────────────────────────────────────────────
    def _model_problems(self):
        """Every reason this model cannot be analysed, in one list.

        Reporting the first problem and stopping meant fixing a model one
        modal dialog at a time -- and three of these were not reported at all
        before 2026-10-04: a zero or negative section number, a negative
        allowable, and any entry stranded beyond the beam by a later Set
        length (R-5, R-7).
        """
        problems = []

        try:
            length = self._typed_length()
            BeamModel._valid_length(length)
        except ValueError as e:
            problems.append(str(e))
            length = self.length
        else:
            self.length = length

        if not self.supports:
            problems.append('Add at least one support.')

        for stray in self._entries_off_beam(length):
            problems.append(
                f'{self._stray_label(stray).capitalize()} is beyond the beam, '
                f"which spans 0 to {self._shown('x', length):.2f} "
                f"{self._u('x')}. Move it onto the beam, or set the beam "
                f'length first.')

        labels = {k: self._sec_label(k) for k in self.SECTION_FIELDS}
        try:
            profile = self._typed_profile()
        except ValueError as e:
            problems.append(str(e))
        else:
            for key in ('E', 'I', 'c', 'A'):
                if profile[key] <= 0.0:
                    problems.append(f'{labels[key]} must be greater than '
                                    f"zero; got {profile[key]:g}.")
            if profile['defl_ratio'] < 0.0:
                problems.append('The deflection limit L/n cannot be negative; '
                                'use 0 to skip that check.')
            for key in ('allow_bend', 'allow_shear'):
                if profile[key] < 0.0:
                    problems.append(
                        f'{labels[key]} cannot be negative: an allowable '
                        f'stress is positive, or 0 to skip that check.')
            if not problems:
                self.profile = profile
        return problems

    def _analyze(self):
        problems = self._model_problems()
        if problems:
            messagebox.showwarning(
                'Cannot analyze',
                'This model cannot be analysed yet:\n\n'
                + '\n'.join(f'  \u2022 {p}' for p in problems))
            return
        try:
            E_Pa = self.profile['E'] * 1e9
            I_m4 = self.profile['I'] * 1e-8
            EI = E_Pa * I_m4

            m = BeamModel(self.length)
            m.EI = EI
            for s in self.supports:
                m.add_support(s['x'], s['type'])
            for p in self.point_loads:
                m.add_point_load(p['x'], p['P'] * 1e3)
            for mm in self.moments:
                m.add_moment(mm['x'], mm['M'] * 1e3)
            for d in self.dloads:
                m.add_dload(d['x1'], d['x2'], d['w1'] * 1e3, d['w2'] * 1e3)
            for d in self.nonuniform_loads:
                ctx = {'L': self.length}
                qfn = make_shape_fn(d['expr'], ctx)

                def scaled_fn(x, _qfn=qfn):
                    return _qfn(x) * 1e3   # storage kN/m -> SI N/m

                # No clamping. The domain is validated when it is entered and
                # again by _model_problems for a model that arrived from a
                # workbook, so anything reaching here is on the beam; add_
                # nonuniform_load normalises a reversed pair and refuses the
                # rest rather than silently trimming it (R-4).
                m.add_nonuniform_load(scaled_fn, d['x1'], d['x2'])

            self.result = m.solve()
            self.model = m
            self._draw_diagrams()
            self._show_results()
            self._draw_schematic()
        except Exception as e:
            messagebox.showerror('Analysis failed', str(e))

    def _show_results(self):
        r = self.result; m = self.model
        diag = r.sample_diagram(n_per_element=25)
        Vmax = max(diag['V'], key=abs)
        Mmax = max(diag['M'], key=abs)
        vmax = max(diag['v'], key=abs)
        # Where each extreme is, not just how big it is. The diagram marks its
        # peaks with red dots, but the TEXT is the part that gets copied into a
        # calculation, and it gave no station at all (R-16).
        x_V = self._extreme_station(diag, 'V', abs)
        x_v = self._extreme_station(diag, 'v', abs)
        M_sag, x_sag = self._signed_extreme(diag, 'M', +1)
        M_hog, x_hog = self._signed_extreme(diag, 'M', -1)

        c_m = self.profile['c'] * 1e-2
        I_m4 = self.profile['I'] * 1e-8
        A_m2 = self.profile['A'] * 1e-4
        sigma_kncm2 = (abs(Mmax) * c_m / I_m4) * 1e-7
        tau_kncm2 = (abs(Vmax) / A_m2) * 1e-7

        # r.support_reaction / the diagram are in SI; the model's own state is
        # in STORAGE units. Both are written in the convention the user picked,
        # which is the only thing the selector changes.
        fu, mu = units.label('force'), units.label('moment')
        lines = ['REACTIONS   (Ry: + up.   M: the couple the support applies,',
                 '             + counter-clockwise.)']
        for s in m.supports:
            react = r.support_reaction(s['x'])
            lines.append(
                f"  x={self._shown('x', s['x']):.2f} {self._u('x')} "
                f"({s['type']:<7}): "
                f"Ry={units.from_si('force', react['Fy']):+8.2f} {fu}   "
                f"M={units.from_si('moment', react['M']):+8.2f} {mu}")
            # Only where the support restrains rotation: elsewhere the couple
            # is zero and the internal moment runs through unbroken, so the
            # two extra numbers would say nothing. Where it does, they are
            # what a designer actually reads off -- the hogging moment the
            # section carries on each side -- and at an interior support they
            # differ, which one column could never show (R-3).
            if 'theta' in BeamModel.SUPPORT_DOF.get(s['type'], ()):
                lines.append(
                    f"      internal M: just left "
                    f"{units.from_si('moment', react['M_left']):+8.2f}, "
                    f"just right "
                    f"{units.from_si('moment', react['M_right']):+8.2f} {mu}")
        xu = self._u('x')

        def at(x):
            return f"at x = {self._shown('x', x):.2f} {xu}"

        lines += ['', 'EXTREMES',
                  f"  Max |V|    = {units.from_si('force', abs(Vmax)):9.2f} "
                  f"{fu}   {at(x_V)}"]
        # max(M, key=abs) collapsed sagging and hogging into one absolute
        # number. A continuous beam needs both, with their stations, and a
        # different section modulus may apply to each. Only the ones that
        # actually occur are printed -- a cantilever has no sagging peak.
        if M_sag is not None:
            lines.append(f"  Max +M     = {units.from_si('moment', M_sag):+9.2f} "
                         f"{mu} {at(x_sag)}  (sagging)")
        if M_hog is not None:
            lines.append(f"  Max -M     = {units.from_si('moment', M_hog):+9.2f} "
                         f"{mu} {at(x_hog)}  (hogging)")
        lines += ['']
        lines += self._equilibrium_lines(r)
        lines += ['', 'SERVICEABILITY']
        du = units.label('deflection')
        lines.append(f"  Max |defl| = {units.from_si('deflection', abs(vmax)):9.3f} "
                     f"{du}   {at(x_v)}")
        ratio_n = self.profile['defl_ratio']
        if ratio_n > 0:
            allow_m = self.length / ratio_n
            util = abs(vmax) / allow_m if allow_m else 0.0
            lines.append(
                f"    allowable = L/{ratio_n:g} = "
                f"{units.from_si('deflection', allow_m):.3f} {du}"
                f"   ({'OK' if util <= 1.0 else 'FAIL'}, ratio {util:.2f})")
        else:
            lines.append('    allowable = not checked '
                         '(no deflection limit given)')
        lines += ['', 'STRESS CHECK']
        su = units.label('stress')

        def _check(title, demand, key):
            # `ratio = demand / allow if allow else 0` turned a MISSING
            # allowable into a printed OK -- a check that cannot fail is worse
            # than no check at all (2026-10-04, R-5). Zero now reads as what
            # it is: nothing to check against.
            allow = self.profile[key]
            lines.append(f'  {title} = '
                         f'{self._shown(key, demand):6.3f} {su}')
            if allow > 0:
                ratio = demand / allow
                lines.append(
                    f'    allowable = {self._shown(key, allow):.3f} {su} '
                    f'  ({"OK" if ratio <= 1.0 else "FAIL"}, ratio {ratio:.2f})')
            else:
                lines.append('    allowable = not checked '
                             '(no allowable stress given)')

        _check('Bending sigma = M*c/I', sigma_kncm2, 'allow_bend')
        _check('Shear tau = V/A  ', tau_kncm2, 'allow_shear')
        # sigma uses max |M| and tau uses max |V|, which on almost any beam are
        # different places. The pair is conservative, but it is not a section
        # check at any ONE point, and saying nothing invited it to be read as
        # one (R-16). A real station-by-station utilisation belongs with the
        # code-check work (R-21).
        x_M = self._extreme_station(diag, 'M', abs)
        if abs(x_M - x_V) > 1e-6 * max(1.0, self.length):
            lines.append(f'  NB these two are at different stations '
                         f'({at(x_M)} and {at(x_V)}), so the pair is')
            lines.append('     conservative rather than a check at one point.')

        lines += self._model_note_lines(m)

        self.res_text.delete('1.0', 'end')
        self.res_text.insert('1.0', '\n'.join(lines))

    @staticmethod
    def _place_clear(canvas, x, y_options, text, others, bounds, **kw):
        """Draw `text` at the first y in `y_options` that hits nothing.

        `others` are canvas items already placed; `bounds` is the (top, bottom)
        the label must stay inside. If every option collides, the first is
        used: a visible overlap beats a label that was never drawn, which is
        the same reasoning as common.declutter_text's.
        """
        top, bot = bounds
        item = None
        for i, y in enumerate(y_options):
            if item is not None:
                canvas.delete(item)
            item = canvas.create_text(x, y, text=text, **kw)
            x0, y0, x1, y1 = canvas.bbox(item)
            if y0 < top or y1 > bot:
                continue
            clash = False
            for other in others:
                X0, Y0, X1, Y1 = canvas.bbox(other)
                if x0 < X1 and X0 < x1 and y0 < Y1 and Y0 < y1:
                    clash = True
                    break
            if not clash:
                return item
        canvas.delete(item)
        return canvas.create_text(x, y_options[0], text=text, **kw)

    # ── where the extremes are ──────────────────────────────────────────────
    @staticmethod
    def _extreme_station(diag, key, score):
        """The x at which `score(diag[key])` is largest."""
        values = diag[key]
        i = max(range(len(values)), key=lambda j: score(values[j]))
        return diag['x'][i]

    @staticmethod
    def _signed_extreme(diag, key, sign, rel_tol=1e-9):
        """The largest value of one SIGN and where it is, or (None, None).

        None means that sign does not occur: a cantilever has no sagging peak,
        and printing "Max +M = +0.00" for it would be noise dressed up as a
        result.
        """
        values = diag[key]
        best = max(range(len(values)), key=lambda j: sign * values[j])
        value = values[best]
        scale = max(abs(v) for v in values) if values else 0.0
        if sign * value <= rel_tol * max(scale, 1.0):
            return None, None
        return value, diag['x'][best]

    # ── what the tab says about its own answer ──────────────────────────────
    def _equilibrium_lines(self, result):
        """The EQUILIBRIUM block.

        A residual the user never sees is not a check. The tab reported
        reactions and extremes and stopped, so a result that did not balance
        looked exactly like one that did -- which is how two supports at one
        station came to report 90 kN of reaction for 60 kN of load (R-1)
        against a green suite. Written in the selected convention, like every
        other number here.
        """
        eq = result.equilibrium()
        fu, mu = units.label('force'), units.label('moment')

        def f(v):
            return units.from_si('force', v)

        def mo(v):
            return units.from_si('moment', v)

        verdict_F = 'ok' if abs(eq['residual_Fy']) <= result.EQUILIBRIUM_TOL * eq['scale_F'] \
            else '*** OUT OF BALANCE ***'
        verdict_M = 'ok' if abs(eq['residual_M0']) <= result.EQUILIBRIUM_TOL * eq['scale_M'] \
            else '*** OUT OF BALANCE ***'
        degree = eq['indeterminacy']
        if degree <= 0:
            statics = f"Statically determinate ({eq['constrained_dof']} restrained DOF)"
        else:
            statics = (f'Statically indeterminate to degree {degree} '
                       f"({eq['constrained_dof']} restrained DOF)")
        return [
            'EQUILIBRIUM',
            f"  Total load       = {f(eq['applied_down']):+9.2f} {fu} (down)",
            f"  Sum of reactions = {f(eq['reactions_up']):+9.2f} {fu} (up)",
            f"  Residual SumFy   = {f(eq['residual_Fy']):+9.2e} {fu}"
            f"   ({eq['rel_Fy']:.1e} of load)  {verdict_F}",
            f"  Residual SumM(0) = {mo(eq['residual_M0']):+9.2e} {mu}"
            f"   ({eq['rel_M0']:.1e})  {verdict_M}",
            f"  Beyond x = L     : V = {f(eq['shear_beyond_end']):+.2e} {fu}"
            f"   M = {mo(eq['moment_beyond_end']):+.2e} {mu}",
            f'  {statics}',
        ]

    def _model_note_lines(self, model):
        """Anything the solver changed about the model as described.

        Today that is only the support merge (R-1): two supports at one
        station are one support, which is almost always what the user meant,
        but the tab must not analyse a different structure than the one on
        screen without saying so.
        """
        merges = getattr(model, 'support_merges', [])
        if not merges:
            return []
        lines = ['', 'NOTES']
        for mg in merges:
            lines.append(
                f"  Two supports at x={self._shown('x', mg['x']):.2f} "
                f"{self._u('x')} were merged "
                f"({mg['kept']} + {mg['added']} -> {mg['result']}); one "
                f"reaction is reported for that station.")
        return lines

    # ── drawing ──────────────────────────────────────────────────────────────
    def _draw_schematic(self):
        c = self.schem
        c.delete('all')
        w = c.winfo_width() or 600
        h = c.winfo_height() or 160
        margin = 40
        L = max(self.length, 0.001)
        scale = (w - 2 * margin) / L
        y0 = h * 0.55

        def X(x): return margin + x * scale

        c.create_line(X(0), y0, X(L), y0, width=3, fill=self.CBEAM)

        for s in self.supports:
            x = X(s['x']); t = s['type']
            if t in ('pin', 'roller'):
                c.create_polygon(x - 10, y0 + 18, x + 10, y0 + 18, x, y0, fill='', outline=self.CSUP, width=2)
                if t == 'roller':
                    c.create_oval(x - 10, y0 + 18, x - 4, y0 + 24, outline=self.CSUP)
                    c.create_oval(x + 4, y0 + 18, x + 10, y0 + 24, outline=self.CSUP)
            elif t == 'fixed':
                c.create_line(x, y0 - 16, x, y0 + 16, width=3, fill=self.CSUP)
                for k in range(-3, 4):
                    c.create_line(x, y0 + k * 5, x - 8, y0 + k * 5 + 8, fill=self.CSUP)
            elif t == 'guided':
                c.create_rectangle(x - 10, y0 + 2, x + 10, y0 + 14, outline=self.CSUP)
            c.create_text(x, y0 + 34,
                          text=f"{self._shown('x', s['x']):.2f} {self._u('x')}",
                          font=('Helvetica', 8), fill='#555')

        # Distributed loads are drawn TO SCALE against the largest intensity in
        # the model, and the chord above them follows the real q(x). Every
        # arrow used to be a fixed 30 px whatever the load, so a 0 -> 60 kN/m
        # triangular load was drawn exactly like a uniform one and the
        # non-uniform branch computed its own shape function and then threw it
        # away (2026-09-05 finding B-3). The load picture is the check an
        # engineer makes before pressing Analyze; it has to show the shape.
        DL_H = 34.0     # px at the largest intensity in the model
        DL_MIN = 5.0    # px floor, so a tiny ordinate still reads as a load
        N_SAMPLES = 20

        def _q_profile(d):
            """[(x_world, intensity_kNm), ...] for one distributed load, or
            None if a user expression will not evaluate."""
            a, b = min(d['x1'], d['x2']), max(d['x1'], d['x2'])
            if 'expr' in d:
                try:
                    fn = make_shape_fn(d['expr'], {'L': self.length})
                except Exception:
                    return None
                pts = []
                for k in range(N_SAMPLES + 1):
                    # sample strictly inside (a, b): the expression may be
                    # singular exactly at its own domain edge
                    t = (k + 0.5) / (N_SAMPLES + 1)
                    xv = a + (b - a) * t
                    try:
                        pts.append((xv, fn(xv)))
                    except Exception:
                        return None
                return pts
            return [(a + (b - a) * k / N_SAMPLES,
                     d['w1'] + (d['w2'] - d['w1']) * (k / N_SAMPLES))
                    for k in range(N_SAMPLES + 1)]

        profiles = []
        for d in list(self.dloads) + list(self.nonuniform_loads):
            pts = _q_profile(d)
            if pts:
                profiles.append((d, pts))
        # Same compressed relative scale as the point loads and moments above,
        # but normalised against an INTENSITY of its own: two distributed loads
        # of equal intensity must draw at equal height whatever length each
        # covers, which a scale shared with the point loads would break.
        q_scale = LoadScale.of((q for _, pts in profiles for _, q in pts),
                               DL_MIN, DL_H)

        def _height(q):
            # A genuinely zero ordinate sits on the beam line, so the start of a
            # triangular load reads as zero rather than as a small load.
            if abs(q) <= 1e-12:
                return 0.0
            return q_scale(q)

        load_labels = []          # decluttered together at the end of the paint

        # Tallest ordinate actually drawn above the beam. Point-load arrows and
        # moment arcs are laid over this band, so their LABELS are lifted clear
        # of it -- the arrows themselves still run to the beam at their true
        # scaled length, which a shifted arrow would falsify.
        dl_top = max((_height(q) for _, pts in profiles for _, q in pts if q > 0),
                     default=0.0)

        for d, pts in profiles:
            # +q is downward, so it is drawn above the beam; an uplift ordinate
            # hangs below it, and a load that changes sign crosses the beam line.
            tops = [(X(xv), y0 - _height(q) if q >= 0 else y0 + _height(q))
                    for xv, q in pts]
            kw = {'dash': (3, 2)} if 'expr' in d else {}
            c.create_line(*[v for pt in tops for v in pt],
                          fill=self.CDLOAD, width=2, **kw)
            step = max(1, len(tops) // 12)
            for i in range(0, len(tops), step):
                xx, yy = tops[i]
                c.create_line(xx, yy, xx, y0, arrow='last', fill=self.CDLOAD)
            label = (f"q(x) = {d['expr']} {units.STORAGE.label('line_load')}"
                     if 'expr' in d
                     else f"{self._shown('w1', d['w1']):.1f}→"
                          f"{self._shown('w2', d['w2']):.1f} {self._u('w1')}")
            load_labels.append(c.create_text(
                (tops[0][0] + tops[-1][0]) / 2,
                min(y0 - DL_H, min(y for _, y in tops)) - 10,
                text=label, font=('Helvetica', 8, 'bold'), fill=self.CDLOAD))

        # Every load glyph is sized RELATIVE to the largest of its own kind on
        # the beam, square-root compressed. See common.LoadScale for why the
        # three families are scaled separately and why the mapping is not
        # linear. Point-load arrows used to be a flat 45 px and moment arcs a
        # flat 12 px radius, so a 500 kN load and a 5 kN load drew identically.
        p_scale = LoadScale.of((p['P'] for p in self.point_loads), 10.0, 48.0)
        m_scale = LoadScale.of((mm['M'] for mm in self.moments), 7.0, 17.0)

        for p in self.point_loads:
            x = X(p['x'])
            h = p_scale(p['P'])
            top = y0 - h if p['P'] >= 0 else y0 + h
            c.create_line(x, top, x, y0, arrow='last', fill=self.CLOAD, width=2)
            label_y = (min(top, y0 - dl_top) - 8 if p['P'] >= 0
                       else max(top, y0 + dl_top) + 8)
            load_labels.append(c.create_text(
                x, label_y,
                text=f"{self._shown('P', p['P']):.1f} {self._u('P')}",
                font=('Helvetica', 8, 'bold'), fill=self.CLOAD))

        for mm in self.moments:
            x = X(mm['x'])
            ccw = mm['M'] >= 0  # sign convention for this tab: +M = CCW
            r = m_scale(mm['M'])
            draw_moment_arrow(c, x, y0, r, ccw, self.CMOM, width=2)
            load_labels.append(c.create_text(
                x, min(y0 - r, y0 - dl_top) - 14,
                text=f"{self._shown('M', mm['M']):.1f} {self._u('M')}",
                font=('Helvetica', 8, 'bold'), fill=self.CMOM))

        # Two loads at the same station put their labels in the same place; lift
        # whichever was drawn later until nothing overlaps.
        declutter_text(c, load_labels)

    def _draw_diagrams(self):
        c = self.diag_canvas
        c.delete('all')
        if not self.result:
            return
        w = c.winfo_width() or 600
        h = c.winfo_height() or 420
        diag = self.result.sample_diagram(n_per_element=25)
        xs = diag['x']
        L = self.length
        margin = 45
        scale_x = (w - 2 * margin) / L
        cap_font = tkfont.Font(font=('Helvetica', 8, 'bold'))
        max_font = tkfont.Font(font=('Helvetica', 8))
        tick_font = tkfont.Font(font=('Helvetica', 7))
        # Room below the last band for the x-axis numbers, measured rather
        # than guessed. They were drawn at `bot + 10` into a pane whose bands
        # filled it to `h - 20`, so every one of them was clipped by a couple
        # of pixels at ANY window size -- found by the R-13 test that asserts
        # no label leaves its own canvas.
        tick_h = tick_font.metrics('linespace')
        axis_strip = tick_h + 6
        band_h = (h - 20 - axis_strip) / 3
        # How many ticks the axes can actually label. Asking for a fixed 8
        # drew labels that touched on a narrow pane -- '9' and '10'
        # overlapping by 2 px at a 340 px window -- and the same crowding
        # applies vertically in a short band. Both counts now come from the
        # space available and the font's own measurements.
        n_xticks = max(2, min(8, int((w - margin - 10)
                                     / max(1, tick_font.measure(f'{L:g}') + 14))))
        n_vticks = max(2, min(5, int(band_h / max(1, tick_h + 6))))

        M_vals = [units.from_si('moment', mv) for mv in diag['M']]
        if self.reverse_bmd_var.get():
            M_vals = [-v for v in M_vals]
            M_label = (f'MOMENT M ({units.label("moment")}) — sagging plotted DOWN,'
                        ' hogging plotted UP')
        else:
            M_label = (f'MOMENT M ({units.label("moment")}) — sagging (+) plotted UP,'
                        ' hogging (−) plotted DOWN')

        # Each band's caption, and the symbol to fall back on when the pane is
        # too narrow for the name. See common.fit_caption for the order.
        bands = [(f'SHEAR V ({units.label("force")}) — positive plotted UP',
                  f'V ({units.label("force")})',
                  [units.from_si('force', v) for v in diag['V']], self.CV_, 0),
                 (M_label, f'M ({units.label("moment")})',
                  M_vals, self.CM_, 1),
                 (f'DEFLECTION ({units.label("deflection")}) — negative = downward',
                  f'\u03b4 ({units.label("deflection")})',
                  [units.from_si('deflection', vv) for vv in diag['v']], self.CDEFL, 2)]

        last_band_idx = len(bands) - 1
        for label, symbol, ys, color, bidx in bands:
            y0 = 20 + bidx * band_h + band_h / 2
            top = 20 + bidx * band_h
            bot = 20 + (bidx + 1) * band_h
            maxabs = max(1e-9, max(abs(v) for v in ys))
            avail = band_h / 2 - 14

            v_ticks = _nice_ticks(-maxabs, maxabs, n_vticks)
            for vt in v_ticks:
                yy = y0 - (vt / maxabs) * avail
                if top + 2 <= yy <= bot - 2:
                    c.create_line(margin, yy, w - 10, yy, fill='#eee')
                    c.create_text(margin - 4, yy, text=f'{vt:g}', anchor='e',
                                  font=('Helvetica', 6), fill='#aaa')
            x_ticks = _nice_ticks(0, L, n_xticks)
            for xt in x_ticks:
                xx = margin + xt * scale_x
                if margin - 1 <= xx <= w - 9:
                    c.create_line(xx, top, xx, bot, fill='#eee')
                    if bidx == last_band_idx:
                        c.create_text(xx, bot + 3, text=f'{xt:g}', anchor='n',
                                      font=('Helvetica', 7), fill='#888')

            c.create_line(margin, top, margin, bot, fill=self.CGRID)
            c.create_line(margin, y0, w - 10, y0, fill='#bbb')

            # The caption, the max readout and the peak labels were each
            # placed from their own geometry with no regard for the others, so
            # they ran through one another as soon as the pane was not wide:
            # 1 overlapping pair at 1500 px and 4 at 700 px (R-13). The
            # caption is fitted to what is left after reserving the readout's
            # own measured width, and when even its symbol will not fit beside
            # the readout, the readout moves to the band's bottom right.
            max_text = f"max ±{maxabs:.2f}"
            max_w = max_font.measure(max_text)
            avail_cap = (w - 10 - margin) - (max_w + 14)
            if avail_cap < cap_font.measure(symbol):
                avail_cap = w - 10 - margin
                max_xy, max_anchor = (w - 10, bot - 4), 'se'
            else:
                max_xy, max_anchor = (w - 10, top + 8), 'e'
            text, _ = fit_caption(label, avail_cap, cap_font, symbol)
            keep = [c.create_text(margin, top + 8, text=text, anchor='w',
                                  font=('Helvetica', 8, 'bold'), fill='#555'),
                    c.create_text(*max_xy, text=max_text, anchor=max_anchor,
                                  font=('Helvetica', 8), fill='#777')]
            pts = []
            for x, v in zip(xs, ys):
                sx = margin + x * scale_x
                sy = y0 - (v / maxabs) * avail
                pts.append((sx, sy))
            poly = [(margin, y0)] + pts + [(margin + L * scale_x, y0)]
            flat = [c_ for pt in poly for c_ in pt]
            c.create_polygon(flat, fill=color, outline=color, stipple='gray50')
            for i in range(len(pts) - 1):
                c.create_line(*pts[i], *pts[i + 1], fill=color, width=2)

            locs, _ = _find_diagram_maxima(xs, ys)
            for xv in locs:
                idx = min(range(len(xs)), key=lambda i: abs(xs[i] - xv))
                sx, sy = pts[idx]
                c.create_oval(sx - 4, sy - 4, sx + 4, sy + 4, fill='#c0392b', outline='white', width=1)
                # Its own side of the point first, then the other side, then
                # a line further out: whichever is free. A marker is never
                # dropped for want of room -- an annotation that silently
                # disappears is the failure this finding is about.
                near = sy - 11 if ys[idx] >= 0 else sy + 11
                far = sy + 11 if ys[idx] >= 0 else sy - 11
                keep.append(self._place_clear(
                    c, sx, (near, far, far + 11, near - 11),
                    f"x={xv:.2f}", keep, (top, bot),
                    font=('Helvetica', 7), fill='#c0392b'))
