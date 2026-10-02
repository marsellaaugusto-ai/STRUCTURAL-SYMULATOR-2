"""The Truss tab's "is it strong enough" layer (apps/truss/truss_design):
steel sections for the rod families, CIRSOC 301 rod checks, utilisation
colours, the governing rod, Explain this rod, self-weight and the
deflection limit."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox

from . import truss_design as td

BG = '#f0f0ee'


def util_color(u):
    """Green (unused) to amber to red (at capacity and over)."""
    if u is None:
        return '#b0b0b0'
    u = max(0.0, min(u, 1.2))
    if u <= 0.6:
        t = u / 0.6
        r, g, b = int(46 + t * (240 - 46)), int(160 + t * (180 - 160)), 60
    elif u <= 1.0:
        t = (u - 0.6) / 0.4
        r, g, b = 240, int(180 - t * 150), 40
    else:
        r, g, b = 160, 0, 0
    return '#%02x%02x%02x' % (r, g, b)


class TrussDesignMixin:

    def _init_design(self, panel):
        self.rod_checks = None
        self.self_weight = tk.BooleanVar(value=False)
        self.color_util = tk.BooleanVar(value=False)
        self._deflection = None
        # Two short rows: one wide row was 65 px more than the panel, and
        # pushed Analyze itself past its right edge.
        row = tk.Frame(panel, bg=BG)
        row.pack(fill='x', padx=8, after=self._learn_row)
        row2 = tk.Frame(panel, bg=BG)
        row2.pack(fill='x', padx=8, after=row)
        self._design_rows = (row, row2)
        sw = tk.Checkbutton(row, text='Self-weight', variable=self.self_weight,
                            bg=BG, font=('Helvetica', 9),
                            command=self._on_design_option)
        sw.pack(side='left')
        self._bind_widget_tooltip(sw,
            'Add every rod\'s own weight (A × L × 78.5 kN/m³, half to each '
            'end) to the loads.')
        cu = tk.Checkbutton(row2, text='Colour by utilisation',
                            variable=self.color_util, bg=BG,
                            font=('Helvetica', 9), command=self._draw)
        cu.pack(side='left')
        self._bind_widget_tooltip(cu,
            'Green = little used, red = at capacity (CIRSOC 301). Rods whose '
            'family has no steel section stay grey.')
        tk.Button(row, text='Explain rod…', font=('Helvetica', 8),
                  command=self._explain_rod).pack(side='left', padx=(6, 0))
        bk = tk.Button(row2, text='Buckling…', font=('Helvetica', 8),
                       command=self._open_buckling)
        bk.pack(side='left', padx=(6, 0))
        self._bind_widget_tooltip(bk,
            'At what multiple of this load does the truss buckle in its own '
            'plane, and into what shape? With the second-order '
            'load-deflection curve.')

    def _on_design_option(self):
        if self.results is not None:
            self._run_analysis(quiet=True)
        else:
            self._draw()

    # ── analysis hooks ────────────────────────────────────────────────────
    def _design_loads(self):
        """The nodal loads to solve for: the model's, plus the self-weight
        when ticked, all times the Load % (TrussPlayMixin)."""
        loads = self.loads
        if self.self_weight.get():
            loads = td.with_self_weight(loads, self.nodes, self.rods)
        return self._scaled_loads(loads)

    def _compute_design(self, res):
        try:
            self.rod_checks = td.check_rods(self.nodes, self.rods,
                                            self.profiles, res, self.diagrams)
        except Exception:
            self.rod_checks = None
        try:
            self._deflection = td.deflection(self.nodes, self._active_supports(),
                                             res['node_res'])
        except Exception:
            self._deflection = None

    def _util_tag(self, i):
        c = (self.rod_checks or [None] * (i + 1))[i] if self.rod_checks and \
            i < len(self.rod_checks) else None
        if c and c.get('checked'):
            return '  u=%.2f%s' % (c['util'], '' if c['ok'] else ' OVER')
        return ''

    def _design_summary(self):
        """Lines under the results and a phrase for the status bar."""
        extra, status = [], ''
        d = self._deflection
        if d and d['span_m'] > 0:
            extra.append('Max deflection %.2f mm = L/%s (limit L/%d = %.1f mm: %s)'
                         % (d['deflection_mm'],
                            '%.0f' % d['L_over'] if d['L_over'] < 1e7 else '∞',
                            td.DEFLECTION_LIMIT, d['limit_mm'],
                            'OK' if d['ok'] else 'TOO MUCH'))
        gov = td.governing(self.rod_checks or [])
        if gov:
            i, c = gov
            extra.append('Most used rod: %d at %.2f (%s)%s'
                         % (i, c['util'], c.get('governing') or c.get('mode'),
                            '' if c['ok'] else ' -- OVER CAPACITY'))
            status = ' Most used rod: %d at %.2f.' % (i, c['util'])
        elif self.rod_checks is not None:
            extra.append('No rod is checked yet: give a family a steel '
                         'section (Rod family → Manage profiles…).')
        if extra:
            self.res_var.set(self.res_var.get() + '\n' + '\n'.join(extra))
        return status

    def _rod_draw_color(self, i, color):
        if (self.color_util.get() and self.results is not None
                and self.rod_checks and i < len(self.rod_checks)):
            c = self.rod_checks[i]
            return util_color(c['util'] if c.get('checked') else None)
        return color

    # ── Explain this rod ──────────────────────────────────────────────────
    def _explain_rod(self):
        if self.results is None or not self.rod_checks:
            messagebox.showinfo('Explain rod', 'Analyze the truss first.')
            return
        if len(self.selected_rods) == 1:
            i = next(iter(self.selected_rods))
        else:
            gov = td.governing(self.rod_checks)
            if gov is None:
                messagebox.showinfo('Explain rod', 'No rod is checked yet: give '
                                    'a family a steel section first.')
                return
            i = gov[0]
        from apps.stereo import stereo_explain as sx
        rod = self.rods[i]
        m = td.member_for(self.nodes, rod, self.profiles)
        expl = sx.explain(m, self.results['rod_res'][i]['force'],
                          self.rod_checks[i], length_m=m['_length_m'])
        text = sx.as_text(expl, 'Rod %d' % i)
        win = tk.Toplevel(self.root)
        win.title('Explain rod %d' % i)
        t = tk.Text(win, font=('Courier', 10), width=90, height=30)
        t.pack(fill='both', expand=True)
        t.insert('1.0', text)
        t.configure(state='disabled')
        return text

    # ── the PDF report ────────────────────────────────────────────────────
    def _report_title(self):
        key = getattr(self, '_example_key', None)
        if key:
            from . import truss_examples as tx
            return next(t for k, t, _b in tx.EXAMPLES if k == key)
        return 'Truss'

    def _export_pdf_report(self, path=None):
        """The report always describes the full load: a part-load solve
        from the Load % slider is put back to 100 % first."""
        from common import _ensure_matplotlib
        if not _ensure_matplotlib():
            messagebox.showerror('Export PDF', 'The PDF report needs '
                                 'matplotlib, which could not be installed. '
                                 'Run: pip install matplotlib')
            return None
        if getattr(self, 'load_pct', None) is not None and \
                self.load_pct.get() != 100:
            self.load_pct.set(100)
            self.results = None
        if self.results is None and self.rods:
            self._run_analysis(quiet=True)
        if self.results is None:
            messagebox.showinfo('Export PDF', 'Analyze the truss first: the '
                                'report is of a solved truss.')
            return None
        if path is None:
            path = filedialog.asksaveasfilename(
                defaultextension='.pdf', filetypes=[('PDF', '*.pdf')],
                title='Export the truss report')
        if not path:
            return None
        from . import truss_pdf
        try:
            out = truss_pdf.export_pdf(
                path, self.nodes, self.rods, self._active_supports(),
                self._design_loads(), self.results, self.rod_checks,
                self.profiles, title=self._report_title())
        except Exception as exc:                # noqa: BLE001
            messagebox.showerror('Export PDF', 'The report could not be '
                                 'written:\n%s' % exc)
            return None
        self.status_var.set('Wrote a %d-sheet report to %s.'
                            % (out['sheets'], os.path.basename(path)))
        return out

    # ── steel sections for the families ───────────────────────────────────
    def _pick_steel_section(self, family, on_done=None):
        from apps.stereo import stereo_profiles as sp
        win = tk.Toplevel(self.root)
        win.title('Steel section — %s' % family)
        win.configure(bg='#f5f5f3')
        tk.Label(win, text='Steel section for the family "%s"' % family,
                 bg='#f5f5f3', font=('Helvetica', 11, 'bold'),
                 fg='#1a6bbd').pack(padx=10, pady=(10, 4))
        lb = tk.Listbox(win, height=14, width=34, exportselection=False,
                        font=('Helvetica', 9))
        lb.pack(padx=10, fill='both', expand=True)
        names = sp.catalog_names()
        for n in names:
            lb.insert('end', n)
        mat = tk.StringVar(master=win, value=sp.STEEL_F24.name)
        tk.OptionMenu(win, mat, *sp.MATERIALS).pack(padx=10, pady=4)

        def apply():
            sel = lb.curselection()
            if not sel:
                messagebox.showinfo('Steel section', 'Pick a section first.')
                return
            self._set_family_section(family, names[sel[0]], mat.get())
            win.destroy()
            if on_done:
                on_done()
        tk.Button(win, text='Apply to the family', bg='#1a6bbd', fg='white',
                  font=('Helvetica', 10, 'bold'), relief='flat',
                  command=apply).pack(pady=(4, 10))
        return win

    def _set_family_section(self, family, section_name, material_name):
        """Give `family` a catalogue section: its E, A, I and the strengths
        the checks need, written onto every rod of the family."""
        from apps.stereo import stereo_profiles as sp
        self._push_undo('steel section')
        props = sp.section_to_props(sp.CATALOG[section_name],
                                    sp.MATERIALS[material_name])
        prof = self.profiles.setdefault(family, {})
        prof.update({k: props[k] for k in ('E', 'A', 'I', 'Fy', 'Fu',
                                           'r_gyr', 'c_cm')})
        prof.update(catalog=section_name, material=material_name)
        for r in self.rods:
            if r.get('profile', 'Default') == family:
                r['E'], r['A'], r['I'] = prof['E'], prof['A'], prof['I']
        self._refresh_profile_combo()
        self.results = None
        self.diagrams = None
        self._draw()
        self._draw_diagrams_only()
        self.status_var.set('Family "%s" is now %s, %s.'
                            % (family, section_name, material_name))
