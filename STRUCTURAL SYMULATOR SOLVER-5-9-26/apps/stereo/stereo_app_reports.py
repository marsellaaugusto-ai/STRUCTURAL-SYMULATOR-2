"""Readouts and file I/O for the Stereo tab: the refresh cycle that keeps
every list and text box in step with the model, the per-member report, and
Excel import/export.

_refresh_all is the single "the model changed, update everything" entry
point every command calls, so no caller has to remember which individual
lists, labels and canvases need redrawing after an edit.

Report/Excel formatting itself lives in stereo_reports.py.
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from apps.stereo import stereo_math as sm
from apps.stereo import stereo_reports as sr
from apps.stereo.stereo_app_constants import DOF_LABELS, QUICK_SUPPORT_CUSTOM, TENSION_HIGH


class StereoReportsMixin:
    """Refresh cycle, member report and Excel import/export."""

    # ── refresh / lists / results text ──────────────────────────────────────
    def _refresh_all(self):
        self._load_glyphs = self._combined_loads_by_node()
        self._shaded_cells = None
        self._voronoi_cache = None   # invalidate; recomputed lazily on next
                                     # draw that actually needs it (see
                                     # _get_shaded_cells) -- find_cells is
                                     # O(members x degree^2) and this runs
                                     # after every mesh edit, not every frame
        self._refresh_support_list()
        self._refresh_load_list()
        self._refresh_results_text()
        self._refresh_indeterminacy_label()
        self._sync_selection_fields()
        self._me_maybe_refresh_topology()
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
                  'N': f'N ({self.u("force")})', 'mode': 'Mode', 'util': 'Util.',
                  'status': 'Status',
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
                                        m.get('conn', 'pin'),
                                        self.fmt('force', mr['N'], sign=True,
                                                 with_label=False),
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
                            meta={'grid_family': self.grid_family.get()},
                            profiles=self.profiles)
        except Exception as exc:
            messagebox.showerror('Export failed', str(exc))
            return
        messagebox.showinfo('Export', f'Saved to {path}')

    def _import_excel(self):
        path = filedialog.askopenfilename(filetypes=[('Excel workbook', '*.xlsx')])
        if not path:
            return
        try:
            nodes, members, loads, supports, profiles = sr.import_excel_model(path)
        except Exception as exc:
            messagebox.showerror('Import failed', str(exc))
            return
        self._push_undo('import excel')
        self.nodes, self.members, self.loads, self.supports = nodes, members, loads, supports
        if profiles:
            self.profiles.update(profiles)
        self._support_candidates = [s['node'] for s in supports]
        self._load_nodes = {}   # an imported model has no known roof surface
        self.area_load_on.set(False)
        self.sup_quick_var.set(QUICK_SUPPORT_CUSTOM)
        self.results = None
        self.member_checks = None
        self.selected_nodes = set()
        self.selected_member = None
        self.selected_members = set()
        self._refresh_profile_combo()
        self._refresh_all()

    def _import_sketchup(self):
        path = filedialog.askopenfilename(
            title='Import SketchUp model',
            filetypes=[('SketchUp Excel export', '*.xlsx')])
        if not path:
            return
        try:
            nodes, members, loads, supports, profiles = sr.import_excel_model(path)
        except Exception as exc:
            messagebox.showerror('Import failed', str(exc))
            return
        self._push_undo('import sketchup')
        self.nodes, self.members, self.loads, self.supports = nodes, members, loads, supports
        if profiles:
            self.profiles.update(profiles)
        self._support_candidates = [s['node'] for s in supports]
        self._load_nodes = {}
        self.area_load_on.set(False)
        self.sup_quick_var.set(QUICK_SUPPORT_CUSTOM)
        self.results = None
        self.member_checks = None
        self.selected_nodes = set()
        self.selected_member = None
        self.selected_members = set()
        self._refresh_profile_combo()
        self._refresh_all()
        self._reset_view()
        n_n, n_m = len(nodes), len(members)
        messagebox.showinfo(
            'Import from SketchUp',
            f'Imported {n_n} nodes and {n_m} members.\n\n'
            'SketchUp does not export loads or supports — '
            'add them in the panel before analyzing.')

    # ── 3D export ─────────────────────────────────────────────────────────────
    def _export_3d_model(self):
        if not self.nodes or not self.members:
            messagebox.showinfo('Export 3D', 'No model to export.')
            return

        win = tk.Toplevel(self.root)
        win.title('Export 3D Model')
        win.geometry('380x310')
        win.resizable(False, False)

        tk.Label(win, text='Export 3D Model', font=('', 12, 'bold')).pack(pady=(12, 4))
        tk.Label(win, text='Configure geometry for the exported file',
                 fg='grey').pack()

        frm = tk.Frame(win)
        frm.pack(fill='x', padx=20, pady=(12, 0))

        tk.Label(frm, text='Format:').grid(row=0, column=0, sticky='w', pady=4)
        fmt_var = tk.StringVar(value='obj')
        fmt_menu = ttk.Combobox(frm, textvariable=fmt_var,
                                values=['obj', 'xlsx (SketchUp plugin)'],
                                state='readonly', width=22)
        fmt_menu.grid(row=0, column=1, sticky='w', padx=(8, 0), pady=4)

        tk.Label(frm, text='Node radius (m):').grid(row=1, column=0, sticky='w', pady=4)
        nr_var = tk.DoubleVar(value=0.0)
        nr_scale = tk.Scale(frm, variable=nr_var, from_=0.0, to=0.5,
                            resolution=0.005, orient='horizontal', length=180)
        nr_scale.grid(row=1, column=1, sticky='w', padx=(8, 0), pady=4)

        tk.Label(frm, text='Rod radius (m):').grid(row=2, column=0, sticky='w', pady=4)
        rr_var = tk.DoubleVar(value=0.0)
        rr_scale = tk.Scale(frm, variable=rr_var, from_=0.0, to=0.3,
                            resolution=0.005, orient='horizontal', length=180)
        rr_scale.grid(row=2, column=1, sticky='w', padx=(8, 0), pady=4)

        hint = tk.Label(win, text='Radius = 0 → wireframe (lines only)',
                        fg='grey', font=('', 9))
        hint.pack(pady=(4, 0))

        def do_export():
            fmt = fmt_var.get()
            n_r = nr_var.get()
            r_r = rr_var.get()
            if fmt == 'obj':
                path = filedialog.asksaveasfilename(
                    defaultextension='.obj',
                    filetypes=[('Wavefront OBJ', '*.obj')],
                    parent=win)
                if not path:
                    return
                try:
                    sr.export_obj(self.nodes, self.members, path,
                                 node_radius=n_r, rod_radius=r_r)
                except Exception as exc:
                    messagebox.showerror('Export failed', str(exc), parent=win)
                    return
            else:
                path = filedialog.asksaveasfilename(
                    defaultextension='.xlsx',
                    filetypes=[('Excel workbook', '*.xlsx')],
                    parent=win)
                if not path:
                    return
                try:
                    meta = {'grid_family': self.grid_family.get(),
                            'node_radius_m': n_r,
                            'rod_radius_m': r_r}
                    sr.export_excel(self.nodes, self.members, self.loads,
                                   self.supports, self.results, path,
                                   checks=self.member_checks, meta=meta,
                                   profiles=self.profiles)
                except Exception as exc:
                    messagebox.showerror('Export failed', str(exc), parent=win)
                    return
            win.destroy()
            messagebox.showinfo('Export 3D', f'Saved to {path}')

        tk.Button(win, text='Export', command=do_export,
                  width=14).pack(pady=(12, 8))

    # ── Example ──────────────────────────────────────────────────────────────
    def _open_example(self):
        import os
        example_path = os.path.join(os.path.dirname(__file__),
                                    'example_stereo_model.xlsx')
        if not os.path.isfile(example_path):
            messagebox.showerror('Example', 'example_stereo_model.xlsx not found.')
            return
        try:
            nodes, members, loads, supports, profiles = sr.import_excel_model(example_path)
        except Exception as exc:
            messagebox.showerror('Import failed', str(exc))
            return
        self._push_undo('open example')
        self.nodes, self.members, self.loads, self.supports = nodes, members, loads, supports
        if profiles:
            self.profiles.update(profiles)
        self._support_candidates = [s['node'] for s in supports]
        self._load_nodes = {}
        self.area_load_on.set(False)
        self.sup_quick_var.set(QUICK_SUPPORT_CUSTOM)
        self.results = None
        self.member_checks = None
        self.selected_nodes = set()
        self.selected_member = None
        self.selected_members = set()
        self._refresh_profile_combo()
        self._refresh_all()
        self._reset_view()
        messagebox.showinfo(
            'Example Model',
            f'Loaded paraboloid dish (antenna):\n'
            f'{len(nodes)} nodes, {len(members)} members,\n'
            f'{len(loads)} loads, {len(supports)} supports.\n\n'
            f'Click Analyze to run the solver.')

    # ── units ────────────────────────────────────────────────────────────────
    def _on_units_changed(self):
        self._refresh_all()
