"""The Piece marks panel: which of these are the same, and how many.

See stereo_marks for the comparison itself and for why a mark is derived
and never stored. This file is only the surface: a toggle that puts the
mark beside each group in the list, the tolerance that comparison uses, and
a window showing the whole schedule.

The schedule is recomputed on every use rather than cached. That is the
point of a derived number: a cache is a second copy of the answer, and the
one failure that matters here is a mark that outlives the edit that made it
wrong.
"""
import tkinter as tk
from tkinter import messagebox

from apps.stereo import stereo_marks as sm
from apps.stereo.stereo_app_constants import BG, PANEL_TEXT_W
from apps.stereo.stereo_app_shell import HINT_FG

META_TOL_KEY = 'mark_tol_mm'


class StereoMarksMixin:
    """Piece marks on the groups, and the schedule behind them."""

    def _init_marks_state(self):
        self.marks_on = tk.BooleanVar(value=False)
        self.mark_tol = tk.StringVar(value='%g' % sm.DEFAULT_TOL_MM)
        # What the numbers meant when the drawings went out, or None while
        # they are still free to be worked out. See stereo_marks.
        self.mark_register = None

    # ── the tolerance ──────────────────────────────────────────────────────

    def _mark_tol_mm(self):
        """The comparison tolerance, always usable. Typing nonsense into the
        box falls back to the default rather than refusing to compare."""
        return sm.clamp_tol(getattr(self, 'mark_tol', None)
                            and self.mark_tol.get())

    def _set_mark_tol(self, mm):
        if hasattr(self, 'mark_tol'):
            self.mark_tol.set('%g' % sm.clamp_tol(mm))

    def _on_mark_tol_changed(self, _event=None):
        """Re-read the box, show what was actually understood, redraw."""
        self._set_mark_tol(self._mark_tol_mm())
        self._refresh_marks()

    # ── the schedule, recomputed ───────────────────────────────────────────

    def _marks_now(self):
        return sm.schedule(self.nodes, self.members,
                           getattr(self, 'groups', ()) or (),
                           self._mark_tol_mm(),
                           getattr(self, 'mark_register', None))

    def _mark_of_group(self):
        """{gid: mark} when marks are on, {} when they are off.

        Off means off: a model with thousands of groups should not pay for
        a comparison nobody asked to see.
        """
        if not (getattr(self, 'marks_on', None) and self.marks_on.get()):
            return {}
        if not getattr(self, 'groups', None) or not self.members:
            return {}
        try:
            by_gid, _rows = sm.assembly_marks(
                self.nodes, self.members, self.groups, self._mark_tol_mm(),
                getattr(self, 'mark_register', None))
        except Exception:                             # noqa: BLE001
            # A mark is a convenience on a list; never a reason the panel
            # cannot be drawn.
            return {}
        return by_gid

    def _refresh_marks(self):
        if hasattr(self, '_refresh_group_list'):
            self._refresh_group_list()
        self._refresh_issue_button()
        self._refresh_marks_note()

    # ── the panel ──────────────────────────────────────────────────────────

    def _build_marks_panel(self, parent):
        box = tk.LabelFrame(parent, text='Piece marks', bg=BG,
                            font=('Helvetica', 8, 'bold'))
        box.pack(fill='x', padx=6, pady=(6, 2))
        tk.Label(box, text='Identical groups get one mark and a count, the '
                           'way a fabricator orders them. A mark ending /m '
                           'is the mirror image: same shape, other hand.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W - 12).pack(anchor='w', padx=4,
                                                    pady=(2, 3))
        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=4)
        tk.Checkbutton(row, text='Show on the list', variable=self.marks_on,
                       bg=BG, font=('Helvetica', 8),
                       command=self._refresh_marks).pack(side='left')
        tk.Label(row, text='same to', bg=BG, fg=HINT_FG,
                 font=('Helvetica', 8)).pack(side='left', padx=(6, 2))
        ent = tk.Entry(row, textvariable=self.mark_tol, width=5,
                       font=('Helvetica', 8), justify='right')
        ent.pack(side='left')
        ent.bind('<Return>', self._on_mark_tol_changed)
        ent.bind('<FocusOut>', self._on_mark_tol_changed)
        tk.Label(row, text='mm', bg=BG, fg=HINT_FG,
                 font=('Helvetica', 8)).pack(side='left', padx=(1, 0))

        self.marks_note = tk.Label(box, text='', bg=BG, fg=HINT_FG,
                                   font=('Helvetica', 8), justify='left',
                                   wraplength=PANEL_TEXT_W - 12)
        self.marks_note.pack(anchor='w', padx=4, pady=(2, 1))
        row2 = tk.Frame(box, bg=BG)
        row2.pack(fill='x', padx=4, pady=(2, 4))
        tk.Button(row2, text='Schedule…', font=('Helvetica', 8),
                  command=self._marks_dialog).pack(side='left', expand=True,
                                                   fill='x')
        self.mark_issue_btn = tk.Button(row2, font=('Helvetica', 8),
                                        command=self._marks_issue_toggle)
        self.mark_issue_btn.pack(side='left', expand=True, fill='x',
                                 padx=(3, 0))
        self._refresh_issue_button()
        self._refresh_marks_note()
        return box

    # ── issuing the numbers ────────────────────────────────────────────────

    def _refresh_issue_button(self):
        btn = getattr(self, 'mark_issue_btn', None)
        if btn is not None:
            btn.config(text='Release numbers' if self.mark_register
                       else 'Issue numbers…')

    def _marks_issue_toggle(self):
        return self._marks_release() if self.mark_register \
            else self._marks_issue()

    def _marks_issue(self):
        """Hold every part to the number it carries now.

        A commitment rather than a setting, so it is asked for: from here
        on the numbering has to live with its own history, and a number
        that goes out is reserved even once its part is gone.
        """
        if not self.members:
            messagebox.showinfo('Issue numbers', 'There is nothing to issue.')
            return None
        data = self._marks_now()
        n = len(data['parts']) + len(data['assemblies'])
        if not messagebox.askyesno(
                'Issue numbers',
                'Hold these %d mark(s) to the numbers they carry now?\n\n'
                'Each part then keeps its number however the model changes '
                'around it, which is what makes this revision comparable '
                'with the next.\n\n'
                'A number that goes out is reserved for good -- even once '
                'the part it names is gone, nothing else is given it. The '
                'list will have holes in it, and that is the point.'
                % n):
            return None
        self._push_undo('issue marks')
        self.mark_register = sm.issue(data, self.mark_register)
        self._refresh_issue_button()
        self._refresh_marks()
        self._set_status('%d mark(s) issued. The numbers are held from '
                         'here.' % n, 'ok')
        return self.mark_register

    def _marks_release(self):
        """Let the numbers be worked out freely again.

        Everything the register was holding is let go, so the next
        schedule may well number differently. Said plainly, because a
        drawing already issued does not change when this does.
        """
        held = len((self.mark_register or {}).get(sm.PART_PREFIX) or {}) \
            + len((self.mark_register or {}).get(sm.ASSEMBLY_PREFIX) or {})
        if not messagebox.askyesno(
                'Release numbers',
                'Let the %d held number(s) go?\n\n'
                'Marks are worked out freely again, so this model may '
                'number differently from the drawings already issued from '
                'it. Those drawings do not change.' % held):
            return None
        self._push_undo('release marks')
        self.mark_register = None
        self._refresh_issue_button()
        self._refresh_marks()
        self._set_status('Numbers released; they are worked out freely '
                         'again.', 'ok')
        return None

    def _register_from_workbook(self, path):
        """The register a workbook carries, or None. Never a reason for an
        import to fail: a model without its register is a model whose
        numbers are free, which is how every model used to be."""
        try:
            import openpyxl
            from apps.stereo.stereo_marks_excel import read_register_sheet
            wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
            try:
                return read_register_sheet(wb)
            finally:
                wb.close()
        except Exception:                             # noqa: BLE001
            return None

    def _refresh_marks_note(self):
        """The counts under the toggle -- and nothing at all until it is on.

        This runs from _refresh_all, so it runs on every edit and every
        undo. Comparing a 12,000-rod model takes about a tenth of a second,
        which is a stutter on every keystroke for an answer nobody asked
        for. Off costs nothing; on costs what it costs, once, because the
        list is showing the same marks anyway.
        """
        note = getattr(self, 'marks_note', None)
        if note is None:
            return
        if not (getattr(self, 'marks_on', None) and self.marks_on.get()):
            note.config(text='Not comparing. Tick to find the groups that '
                             'are the same piece.')
            return
        if not self.members:
            note.config(text='No rods yet.')
            return
        try:
            data = self._marks_now()
        except Exception:                             # noqa: BLE001
            note.config(text='')
            return
        parts = len(data['parts'])
        repeated = sum(1 for r in data['assemblies'] if r['qty'] > 1)
        bits = ['%d part%s' % (parts, '' if parts == 1 else 's')]
        if data['assemblies']:
            bits.append('%d assembl%s' % (len(data['assemblies']),
                                          'y' if len(data['assemblies']) == 1
                                          else 'ies'))
            bits.append('%d built more than once' % repeated)
        said = ' · '.join(bits)
        if self.mark_register:
            said += '\nNumbers issued: each part keeps the one it went out '\
                    'under.'
            if not sm.register_applies(self.mark_register,
                                       self._mark_tol_mm()):
                said += ('\nIssued at %g mm, comparing at %g mm -- none of '
                         'the held numbers apply at this setting.'
                         % (sm.clamp_tol(self.mark_register.get('tol_mm')),
                            self._mark_tol_mm()))
            if data['withdrawn']:
                said += '\nIssued and no longer built: %s (still reserved).'\
                    % ', '.join(data['withdrawn'][:6])
        note.config(text=said)

    # ── the schedule window ────────────────────────────────────────────────

    def _marks_dialog(self):
        data = self._marks_now()
        win = tk.Toplevel(self.root)
        win.title('Piece marks')
        win.transient(self.root)
        tk.Label(win, text='Piece marks', font=('', 12, 'bold')).pack(
            pady=(12, 2))
        tk.Label(win,
                 text='Worked out from the geometry, not stored, so these '
                      'always agree with the steel in front of you -- and '
                      'they are not comparable with a schedule exported '
                      'before the model changed. Compared to the nearest '
                      '%g mm. A mark ending %s is the mirror image: a '
                      'different piece that cannot go in the other one\'s '
                      'place.' % (data['tol_mm'], sm.MIRROR_SUFFIX),
                 fg=HINT_FG, justify='left', wraplength=560,
                 font=('Helvetica', 8)).pack(anchor='w', padx=14)
        txt = tk.Text(win, width=78, height=24, font=('Courier', 8),
                      wrap='none')
        txt.pack(fill='both', expand=True, padx=14, pady=(6, 4))
        for line in self._marks_report(data):
            txt.insert('end', line + '\n')
        txt.config(state='disabled')
        tk.Button(win, text='Close', command=win.destroy).pack(pady=(0, 12))
        return win

    def _marks_report(self, data=None):
        """The schedule as plain lines -- the window, and anything else that
        wants it in text."""
        data = data or self._marks_now()
        out = ['ASSEMBLIES  (groups fabricated as one piece)', '']
        if data['assemblies']:
            out.append('%-8s %4s %6s %10s %10s   %s'
                       % ('mark', 'qty', 'rods', 'length m', 'mass kg',
                          'groups'))
            for r in data['assemblies']:
                out.append('%-8s %4d %6d %10.3f %10.1f   %s'
                           % (r['mark'], r['qty'], r['n_rods'],
                              r['length_m'], r['mass_kg'],
                              ', '.join(r['names'])))
        else:
            out.append('  No group has rods of its own, so there is nothing')
            out.append('  to fabricate as an assembly yet.')
        out += ['', 'PARTS  (single rods -- the list steel is ordered from)',
                '']
        out.append('%-8s %4s %-16s %10s %10s   %s'
                   % ('mark', 'qty', 'profile', 'length m', 'mass kg',
                      'role(s)'))
        for r in data['parts']:
            out.append('%-8s %4d %-16s %10.3f %10.1f   %s'
                       % (r['mark'], r['qty'], r['profile'][:16],
                          r['length_m'], r['mass_kg'],
                          ', '.join(r['roles'])))
        out += ['', '%-8s %4d %-16s %10.3f %10.1f'
                % ('TOTAL', sum(r['qty'] for r in data['parts']), '',
                   sum(r['total_length_m'] for r in data['parts']),
                   sum(r['total_mass_kg'] for r in data['parts']))]
        return out
