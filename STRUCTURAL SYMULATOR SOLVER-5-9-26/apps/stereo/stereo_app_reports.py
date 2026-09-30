"""Readouts and file I/O for the Stereo tab: the refresh cycle that keeps
every list and text box in step with the model, the per-member report, and
Excel import/export.

_refresh_all is the single "the model changed, update everything" entry
point every command calls, so no caller has to remember which individual
lists, labels and canvases need redrawing after an edit.

Report/Excel formatting itself lives in stereo_reports.py.
"""
import os

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
        self._refresh_support_list()
        self._refresh_load_list()
        self._refresh_results_text()
        self._refresh_indeterminacy_label()
        self._sync_selection_fields()
        self._update_properties_panel()
        self._refresh_model_tree()
        self._me_maybe_refresh_topology()
        self._refresh_status()
        self._refresh_shape_note()
        # The control table is a view of the profile, so it has to
        # follow an undo as well as an edit -- otherwise the table
        # shows a curve that no longer exists.
        self._bz_refresh_list()
        # Only when that mode is showing: rebuilding four charts on every
        # model change costs a cell-detection pass, and nobody is looking.
        if self.active_mode.get() == 'analyse':
            self._refresh_analysis_charts()
        self._draw()

    def _model_name(self):
        """What to call this model in an exported report.

        The model's own name when it has one (an example's title, an
        imported file, a loaded variant), otherwise the Grid Family
        dropdown that generated it. Exports used to read the dropdown
        directly, so every example and every imported file was reported
        under whatever family happened to be selected.
        """
        label = getattr(self, '_model_label', None)
        return label or self.grid_family.get()

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
            # _all_loads(), NOT self.loads: self.loads holds only the point
            # loads typed into the Loads panel, while the analysis this
            # workbook reports on was run on those PLUS the area load and
            # self-weight. Exporting the short list wrote a workbook whose
            # [LOADS] table was empty on every default model (100 entries
            # and 1800 kN of applied load, gone), so re-importing it and
            # pressing Analyze produced a structure with zero displacement
            # -- and _import_excel deliberately clears area_load_on and
            # _load_nodes, so nothing downstream could put the missing load
            # back.
            sr.export_excel(self.nodes, self.members, self._all_loads(),
                            self.supports,
                            self.results, path, checks=self.member_checks,
                            meta={'grid_family': self._model_name()},
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
        self._model_label = os.path.basename(path)
        self.nodes, self.members, self.loads, self.supports = nodes, members, loads, supports
        if profiles:
            self.profiles.update(profiles)
        self._support_candidates = [s['node'] for s in supports]
        self._load_nodes = {}   # an imported model has no known roof surface
        # The workbook's [LOADS] table is the COMPLETE solved case (the
        # exporter writes _all_loads()), so leaving either generator on
        # would add a second copy of the area load or the self-weight on
        # top of the one already in the file.
        self.area_load_on.set(False)
        self.self_weight_on.set(False)
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
        self._model_label = f'SketchUp: {os.path.basename(path)}'
        self.nodes, self.members, self.loads, self.supports = nodes, members, loads, supports
        if profiles:
            self.profiles.update(profiles)
        self._support_candidates = [s['node'] for s in supports]
        self._load_nodes = {}
        # see _import_excel: the file already carries the full load case
        self.area_load_on.set(False)
        self.self_weight_on.set(False)
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

    # ── PDF export ────────────────────────────────────────────────────────────
    def _selection_member_idx(self):
        """Which members the current selection means.

        Selected rods when there are any; otherwise the rods whose BOTH
        ends are selected nodes, which is what lassoing a region of the
        grid and asking for "this group" means. A node selected on its own
        still travels (see submodel's node_idx), so an isolated joint can
        be reported too.
        """
        if self.selected_members:
            return set(self.selected_members)
        sel_n = set(self.selected_nodes)
        if not sel_n:
            return set()
        return {i for i, m in enumerate(self.members)
                if m['a'] in sel_n and m['b'] in sel_n}

    # ── which sheets to include ─────────────────────────────────────────────
    #
    # The full report is nineteen sheets on a rigid-jointed model. That is
    # the right default for a design file and the wrong one for a slide in
    # a presentation, so the report is assembled from groups the reader
    # picks, and the count of sheets they will get is shown live rather
    # than discovered after the export.
    PDF_GROUP_LABELS = (
        ('views', 'Orthographic views',
         'plan, front, back, right and left, each over its dimension grid'),
        ('force', 'Axial force',
         'general view and plan, bar thickness = axial stress'),
        ('utilization', 'Member utilization',
         'general view, plan, and one scaled to this model\'s own worst bar'),
        ('moment', 'Moments',
         'at the joints, and — on a rigid model — bending and shear along '
         'the rods'),
        ('deformed', 'Deformed shape',
         'the displaced geometry, with the serviceability verdict'),
        ('tables', 'Schedules',
         'reactions and equilibrium, governing members, maximum '
         'solicitation, steel take-off'),
    )

    def _pdf_sheet_dialog(self, title, results, checks, n_rigid):
        """Ask which groups of sheets to include; None if cancelled.

        Returns a set of PDF_SHEET_GROUPS keys. Tests replace this method
        wholesale rather than driving the widgets.
        """
        chosen = (set(sr.PDF_SHEET_GROUPS) if self._pdf_groups is None
                  else set(self._pdf_groups))
        win = tk.Toplevel(self.root)
        win.title(title)
        win.resizable(False, False)
        win.transient(self.root)

        tk.Label(win, text='Sheets to include', font=('', 12, 'bold')).pack(
            pady=(12, 2))
        tk.Label(win, text='Sheet 1, the general view and load case, is '
                           'always included.', fg='grey').pack()

        body = tk.Frame(win)
        body.pack(fill='x', padx=20, pady=(10, 0))
        vars_ = {}
        # master=win, not left to default. A tk.*Var with no master binds to
        # whatever tkinter._default_root happens to be at that moment, which
        # is not necessarily the interpreter win's own widgets live in once
        # more than one Tk() root exists in the process -- and this app's test
        # suite makes one per file. When they differ, the Checkbutton and its
        # "own" BooleanVar talk to two different interpreters: ticking the box
        # never reaches v.get(), which reads back its untouched default. That
        # is why these two tests passed alone and failed in the full suite.
        # stereo_app_wizard.py carries the same note over the same fix.
        for row, (key, label, blurb) in enumerate(self.PDF_GROUP_LABELS):
            v = tk.BooleanVar(master=win, value=key in chosen)
            vars_[key] = v
            tk.Checkbutton(body, text=label, variable=v, anchor='w').grid(
                row=row * 2, column=0, sticky='w')
            tk.Label(body, text=blurb, fg='grey', font=('', 9),
                     anchor='w', justify='left', wraplength=380).grid(
                row=row * 2 + 1, column=0, sticky='w', padx=(22, 0),
                pady=(0, 6))

        count = tk.Label(win, text='', font=('', 10, 'bold'))
        count.pack(pady=(6, 0))

        def recount(*_):
            want = {k for k, v in vars_.items() if v.get()}
            n = len(sr.plan_sheets(results, checks, n_rigid, want))
            count.config(text=f'{n} sheet{"s" if n != 1 else ""}')

        for v in vars_.values():
            v.trace_add('write', recount)
        recount()

        out = {'groups': None}

        def ok():
            out['groups'] = {k for k, v in vars_.items() if v.get()}
            win.destroy()

        btns = tk.Frame(win)
        btns.pack(pady=(10, 12))
        tk.Button(btns, text='Export…', command=ok, width=12).pack(
            side='left', padx=4)
        tk.Button(btns, text='Cancel', command=win.destroy, width=10).pack(
            side='left', padx=4)

        win.grab_set()
        try:
            self.root.wait_window(win)
        finally:
            # A modal dialog that outlives the wait keeps its grab, and a
            # grabbed window blocks every other window in the process. In
            # the app that costs an unclosable dialog; in a test run it
            # stops the whole suite on whichever test leaked it, which is
            # exactly what happened here -- a run sat at 0.2% CPU for
            # three hours holding one.
            try:
                if win.winfo_exists():
                    win.grab_release()
                    win.destroy()
            except tk.TclError:
                pass
        if out['groups'] is not None:
            self._pdf_groups = set(out['groups'])
        return out['groups']

    def _export_selection_pdf(self):
        """A report on the selected group ALONE.

        The rest of the structure is not dimmed or pushed behind the
        group, it is cut out of the model the report is built from, so
        nothing can obstruct the view of what is being analysed. The
        title block then has to carry two names -- the file and the group
        -- or the sheet cannot be traced back to anything.
        """
        from tkinter import simpledialog
        if not self.nodes or not self.members:
            messagebox.showinfo('PDF of Selection', 'No model to export.')
            return
        member_idx = self._selection_member_idx()
        node_idx = set(self.selected_nodes)
        if not member_idx and not node_idx:
            messagebox.showinfo(
                'PDF of Selection',
                'Nothing is selected.\n\n'
                'Click a rod, or left-drag a lasso over the nodes of the '
                'group you want reported, then try again.')
            return

        n_m, n_n = len(member_idx), len(node_idx)
        suggestion = (f'Group of {n_m} bars' if n_m
                      else f'Group of {n_n} nodes')
        name = simpledialog.askstring('PDF of Selection',
                                      'Name this group:', parent=self.root,
                                      initialvalue=suggestion)
        if not name:
            return
        # The chooser runs against the SUB-model's own rigid count, so a
        # pin-jointed group cut out of a rigid model is not offered sheets
        # it cannot fill.
        sub_rigid = sum(1 for i in sorted(member_idx)
                        if self.members[i].get('conn') == 'rigid')
        groups = self._pdf_sheet_dialog('PDF of Selection', self.results,
                                        self.member_checks, sub_rigid)
        if groups is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.pdf',
            filetypes=[('PDF document', '*.pdf')])
        if not path:
            return
        try:
            sub = sr.submodel(self.nodes, self.members, self._all_loads(),
                              self._active_supports(), self.results,
                              self.member_checks,
                              member_idx=member_idx, node_idx=node_idx)
            s_nodes, s_members, s_loads, s_supports, s_res, s_checks, _ = sub
            sr.export_pdf(s_nodes, s_members, s_loads, s_supports, s_res, path,
                          checks=s_checks,
                          meta={'group': name,
                                'subset_of': self._model_name(),
                                'grid_family': self._model_name()},
                          az_deg=self.azimuth, el_deg=self.elevation,
                          groups=groups,
                          unit_weight_kN_m3=self.unit_weight_var.get())
        except Exception as exc:
            messagebox.showerror('Export failed', str(exc))
            return
        messagebox.showinfo(
            'PDF of Selection',
            f'Saved to {path}\n\n'
            f'Group "{name}": {len(s_members)} bar(s), {len(s_nodes)} node(s), '
            f'shown in isolation.')

    def _export_pdf(self):
        if not self.nodes or not self.members:
            messagebox.showinfo('Export PDF', 'No model to export.')
            return
        n_rigid = sum(1 for m in self.members if m.get('conn') == 'rigid')
        groups = self._pdf_sheet_dialog('Export PDF', self.results,
                                        self.member_checks, n_rigid)
        if groups is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.pdf',
            filetypes=[('PDF document', '*.pdf')])
        if not path:
            return
        try:
            # The report has to describe the model that was actually
            # SOLVED, or its load-case sheet and its equilibrium check are
            # about some other structure: _all_loads() for the same reason
            # as the Excel export above, and _active_supports() because the
            # support sandbox can exclude a support from the analysis while
            # leaving it in self.supports.
            sr.export_pdf(self.nodes, self.members, self._all_loads(),
                          self._active_supports(),
                          self.results, path, checks=self.member_checks,
                          meta={'grid_family': self._model_name()},
                          az_deg=self.azimuth, el_deg=self.elevation,
                          groups=groups,
                          unit_weight_kN_m3=self.unit_weight_var.get())
        except Exception as exc:
            messagebox.showerror('Export failed', str(exc))
            return
        messagebox.showinfo('Export PDF', f'Saved to {path}')

    # ── SketchUp Ruby script export ──────────────────────────────────────────
    def _export_sketchup_ruby(self):
        if not self.nodes or not self.members:
            messagebox.showinfo('Export SketchUp', 'No model to export.')
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.rb',
            filetypes=[('Ruby script', '*.rb')])
        if not path:
            return
        try:
            sr.export_sketchup_ruby(self.nodes, self.members, path,
                                     supports=self.supports,
                                     results=self.results)
        except Exception as exc:
            messagebox.showerror('Export failed', str(exc))
            return
        messagebox.showinfo('Export SketchUp',
                            f'Saved to {path}\n\n'
                            'In SketchUp: Window > Ruby Console,\n'
                            'then type: load "<path>"')

    # ── IFC export ───────────────────────────────────────────────────────────
    def _export_ifc(self):
        if not self.nodes or not self.members:
            messagebox.showinfo('Export IFC', 'No model to export.')
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.ifc',
            filetypes=[('IFC file', '*.ifc')])
        if not path:
            return
        try:
            sr.export_ifc(self.nodes, self.members, path,
                          supports=self.supports,
                          profiles=self.profiles,
                          results=self.results)
        except Exception as exc:
            messagebox.showerror('Export failed', str(exc))
            return
        messagebox.showinfo('Export IFC', f'Saved to {path}')

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
        # master=win for the same reason as the sheet chooser above
        fmt_var = tk.StringVar(master=win, value='obj')
        fmt_menu = ttk.Combobox(frm, textvariable=fmt_var,
                                values=['obj', 'xlsx (SketchUp plugin)'],
                                state='readonly', width=22)
        fmt_menu.grid(row=0, column=1, sticky='w', padx=(8, 0), pady=4)

        tk.Label(frm, text='Node radius (m):').grid(row=1, column=0, sticky='w', pady=4)
        nr_var = tk.DoubleVar(master=win, value=0.0)
        nr_scale = tk.Scale(frm, variable=nr_var, from_=0.0, to=0.5,
                            resolution=0.005, orient='horizontal', length=180)
        nr_scale.grid(row=1, column=1, sticky='w', padx=(8, 0), pady=4)

        tk.Label(frm, text='Rod radius (m):').grid(row=2, column=0, sticky='w', pady=4)
        rr_var = tk.DoubleVar(master=win, value=0.0)
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
                    meta = {'grid_family': self._model_name(),
                            'node_radius_m': n_r,
                            'rod_radius_m': r_r}
                    sr.export_excel(self.nodes, self.members, self._all_loads(),
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
        self._model_label = 'Example: paraboloid dish (antenna)'
        self.nodes, self.members, self.loads, self.supports = nodes, members, loads, supports
        if profiles:
            self.profiles.update(profiles)
        self._support_candidates = [s['node'] for s in supports]
        self._load_nodes = {}
        # see _import_excel: the file already carries the full load case
        self.area_load_on.set(False)
        self.self_weight_on.set(False)
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

    # ── design variants ─────────────────────────────────────────────────────
    def _save_variant(self):
        import copy, math
        from tkinter import simpledialog
        if not self.results:
            messagebox.showinfo('Save Variant', 'Run Analyze first.')
            return
        name = simpledialog.askstring('Save Variant', 'Variant name:',
                                      parent=self.root)
        if not name:
            return
        nr = self.results['node_res']
        mr = self.results['member_res']
        max_util = 0.0
        if self.member_checks:
            for chk in self.member_checks:
                u = chk.get('util', 0.0)
                if u > max_util:
                    max_util = u
        max_force = max((abs(r['N']) for r in mr), default=0.0)
        max_disp = max(
            (math.sqrt(r['ux']**2 + r['uy']**2 + r['uz']**2) for r in nr),
            default=0.0)
        total_weight = 0.0
        for mi, m in enumerate(self.members):
            na, nb = self.nodes[m['a']], self.nodes[m['b']]
            dx, dy, dz = nb[0]-na[0], nb[1]-na[1], nb[2]-na[2]
            L = math.sqrt(dx*dx + dy*dy + dz*dz)
            A = m.get('A', self.profiles.get(m.get('profile', ''), {}).get('A', 20.0))
            total_weight += A * 1e-4 * L * 7850.0

        # The variant stores the load case that was SOLVED, flattened to
        # explicit nodal loads -- not self.loads. Restoring a variant
        # clears _load_nodes (the roof surface an area load is computed
        # over is not part of the snapshot), so a variant carrying only
        # the typed point loads would come back as an unloaded structure
        # sitting beside the results of a loaded one.
        solved_loads = self._all_loads()
        self._variants.append({
            'name': name,
            'nodes': copy.deepcopy(self.nodes),
            'members': copy.deepcopy(self.members),
            'loads': copy.deepcopy(solved_loads),
            'supports': copy.deepcopy(self.supports),
            'profiles': copy.deepcopy(self.profiles),
            'results': copy.deepcopy(self.results),
            'member_checks': copy.deepcopy(self.member_checks),
            'summary': {
                'n_nodes': len(self.nodes),
                'n_members': len(self.members),
                'n_supports': len(self.supports),
                'n_loads': len(solved_loads),
                'max_force_kN': max_force,
                'max_disp_mm': max_disp,
                'max_util': max_util,
                'weight_kg': total_weight,
            },
        })
        messagebox.showinfo('Variant Saved',
                            f'"{name}" saved ({len(self._variants)} variant'
                            f'{"s" if len(self._variants) != 1 else ""} stored).')

    def _compare_variants(self):
        if len(self._variants) < 2:
            messagebox.showinfo(
                'Compare Variants',
                'Save at least 2 variants first (Save Variant…).')
            return
        self._show_variant_comparison()

    def _show_variant_comparison(self):
        import math
        win = tk.Toplevel(self.root)
        win.title('Design Variant Comparison')
        win.geometry('900x480')
        win.resizable(True, True)

        tk.Label(win, text='Design Variant Comparison',
                 font=('', 13, 'bold')).pack(pady=(10, 2))
        tk.Label(win, text=f'{len(self._variants)} variants',
                 fg='grey').pack()

        container = tk.Frame(win)
        container.pack(fill='both', expand=True, padx=10, pady=8)

        canvas = tk.Canvas(container, highlightthickness=0)
        xscroll = tk.Scrollbar(container, orient='horizontal',
                                command=canvas.xview)
        yscroll = tk.Scrollbar(container, orient='vertical',
                                command=canvas.yview)
        canvas.configure(xscrollcommand=xscroll.set,
                         yscrollcommand=yscroll.set)
        yscroll.pack(side='right', fill='y')
        xscroll.pack(side='bottom', fill='x')
        canvas.pack(side='left', fill='both', expand=True)

        tbl = tk.Frame(canvas)
        canvas.create_window((0, 0), window=tbl, anchor='nw')

        metrics = [
            ('Nodes', 'n_nodes', '{:.0f}', False),
            ('Members', 'n_members', '{:.0f}', False),
            ('Supports', 'n_supports', '{:.0f}', False),
            ('Loads', 'n_loads', '{:.0f}', False),
            ('Max force (kN)', 'max_force_kN', '{:.2f}', True),
            ('Max disp. (mm)', 'max_disp_mm', '{:.3f}', True),
            ('Max util.', 'max_util', '{:.3f}', True),
            ('Weight (kg)', 'weight_kg', '{:.1f}', True),
        ]

        hdr_bg = '#4a6fa5'
        hdr_fg = 'white'
        best_bg = '#d4edda'
        worst_bg = '#f8d7da'

        tk.Label(tbl, text='Metric', font=('', 10, 'bold'),
                 bg=hdr_bg, fg=hdr_fg, padx=8, pady=4,
                 anchor='w').grid(row=0, column=0, sticky='nsew')
        for ci, v in enumerate(self._variants):
            tk.Label(tbl, text=v['name'], font=('', 10, 'bold'),
                     bg=hdr_bg, fg=hdr_fg, padx=8, pady=4,
                     anchor='center').grid(row=0, column=ci+1, sticky='nsew')

        for ri, (label, key, fmt, highlight) in enumerate(metrics, start=1):
            tk.Label(tbl, text=label, font=('', 10),
                     padx=8, pady=3, anchor='w',
                     relief='groove').grid(row=ri, column=0, sticky='nsew')
            vals = [v['summary'][key] for v in self._variants]
            best_i = vals.index(min(vals)) if highlight else -1
            worst_i = vals.index(max(vals)) if highlight and max(vals) != min(vals) else -1
            for ci, val in enumerate(vals):
                bg = '#ffffff'
                if ci == best_i:
                    bg = best_bg
                elif ci == worst_i:
                    bg = worst_bg
                tk.Label(tbl, text=fmt.format(val), font=('', 10),
                         padx=8, pady=3, anchor='center', bg=bg,
                         relief='groove').grid(row=ri, column=ci+1, sticky='nsew')

        tbl.update_idletasks()
        canvas.config(scrollregion=canvas.bbox('all'))

        btn_frame = tk.Frame(win)
        btn_frame.pack(pady=(0, 8))

        def load_variant(idx):
            import copy
            v = self._variants[idx]
            self._push_undo('load variant')
            self.nodes = copy.deepcopy(v['nodes'])
            self.members = copy.deepcopy(v['members'])
            self.loads = copy.deepcopy(v['loads'])
            self.supports = copy.deepcopy(v['supports'])
            self.profiles = copy.deepcopy(v['profiles'])
            self.results = copy.deepcopy(v['results'])
            self.member_checks = copy.deepcopy(v['member_checks'])
            self._model_label = f'Variant: {v["name"]}'
            self._support_candidates = [s['node'] for s in self.supports]
            self._load_nodes = {}
            # The stored loads are already the FULL solved case (see
            # _save_variant), so re-adding an area load or self-weight on
            # top of them would double-count. Same reasoning, and the same
            # two lines, as _import_excel.
            self.area_load_on.set(False)
            self.self_weight_on.set(False)
            self.selected_nodes = set()
            self.selected_member = None
            self.selected_members = set()
            self._refresh_profile_combo()
            self._refresh_all()
            win.destroy()
            messagebox.showinfo('Variant Loaded',
                                f'Loaded variant "{v["name"]}".')

        def delete_variant(idx):
            name = self._variants[idx]['name']
            if messagebox.askyesno('Delete Variant',
                                    f'Delete "{name}"?', parent=win):
                self._variants.pop(idx)
                win.destroy()
                if len(self._variants) >= 2:
                    self._show_variant_comparison()

        for ci, v in enumerate(self._variants):
            f = tk.Frame(btn_frame)
            f.pack(side='left', padx=6)
            tk.Button(f, text=f'Load "{v["name"]}"',
                      command=lambda i=ci: load_variant(i)).pack(side='left', padx=2)
            tk.Button(f, text='X', fg='red', width=2,
                      command=lambda i=ci: delete_variant(i)).pack(side='left')

    # ── units ────────────────────────────────────────────────────────────────
    def _on_units_changed(self):
        self._refresh_all()
