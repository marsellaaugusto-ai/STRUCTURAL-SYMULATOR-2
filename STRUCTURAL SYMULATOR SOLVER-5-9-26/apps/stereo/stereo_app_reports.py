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
        self._refresh_support_list()
        self._refresh_load_list()
        self._refresh_results_text()
        self._refresh_indeterminacy_label()
        self._sync_selection_fields()
        self._me_maybe_refresh_topology()
        self._refresh_status()
        self._refresh_shape_note()
        # Only when that mode is showing: rebuilding four charts on every
        # model change costs a cell-detection pass, and nobody is looking.
        if self.active_mode.get() == 'analyse':
            self._refresh_analysis_charts()
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
