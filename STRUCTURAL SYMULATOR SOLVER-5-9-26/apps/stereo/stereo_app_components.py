"""Components in the interface: make one, detach one, and size it right.

See stereo_components for what a component is and why only the SECTION is
shared. The job of this file is to put that where someone meets it:

  * Make component, offered from the object under the pointer, which finds
    the other copies by shape rather than asking anyone to select them.
  * Make unique, to detach one copy.
  * The sizing envelope AT THE PLACE SIZING HAPPENS. That is the part no
    drawing tool has and the part that matters: a recommendation for a
    component is computed over every copy and applied to every copy, so
    the section carries the worst of them. Size it from the copy on screen
    and nothing looks wrong -- which is exactly why it has to be here
    rather than in a report someone reads afterwards.
"""
import tkinter as tk
from tkinter import messagebox, simpledialog

from apps.stereo import stereo_components as scp
from apps.stereo import stereo_groups as sgp
from apps.stereo.stereo_app_constants import BG
from apps.stereo.stereo_app_shell import HINT_FG


class StereoComponentsMixin:
    """Make component / Make unique, and sizing over every copy."""

    # ── what the rest of the tab asks ──────────────────────────────────────

    def _component_of(self, gid):
        return scp.name_of(sgp.find(self.groups, gid))

    def _component_copies(self, gid):
        return scp.copies(self.groups, gid) if self.groups else 1

    def _sizing_rods(self, gid, rods=None):
        """The rods a SIZING decision for this group has to consider.

        Its own, plus the matching rod of every other copy. For a group
        that is not a component this is just its own rods, so callers can
        use it unconditionally -- which is the point: the envelope must not
        be something a caller has to remember to ask for.
        """
        rods = list(self._group_rods(gid) if rods is None else rods)
        if not self.groups or not self._component_of(gid):
            return rods
        try:
            return scp.matching_rods(self.nodes, self.members, self.groups,
                                     rods, self._mark_tol_mm())
        except Exception:                             # noqa: BLE001
            # A correspondence we cannot work out is a reason to size this
            # group alone and say so, never a reason to refuse to size.
            return rods

    def _component_sizing_note(self, gid, rods=None):
        """One line for a sizing dialog, or '' for a plain group."""
        name = self._component_of(gid)
        if not name:
            return ''
        n = self._component_copies(gid)
        if n <= 1:
            return ''
        own = list(self._group_rods(gid))
        reach = self._sizing_rods(gid, own)
        if len(reach) <= len(own):
            return ('%s is built %d times, but the copies no longer match, '
                    'so this sizes only the one you picked. Check the '
                    'component before trusting it.' % (name, n))
        return ('%s is built %d times. Sized over all %d copies (%d rods) '
                'and applied to all of them: the part is fabricated once, '
                'so it has to carry the worst copy, never this one.'
                % (name, n, n, len(reach)))

    # ── the two verbs ──────────────────────────────────────────────────────

    def _menu_make_component(self, gid):
        """Offer the groups that are the same shape, then name the part."""
        g = sgp.find(self.groups, gid)
        if g is None or not g['members']:
            messagebox.showinfo('Make component',
                                'A group with no rods of its own is a branch '
                                'of the tree, not a part to fabricate.')
            return None
        try:
            found = scp.matching_groups(self.nodes, self.members, self.groups,
                                        gid, self._mark_tol_mm())
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror('Make component', str(exc))
            return None
        here = self._group_display_name(gid)
        others = [o['name'] for o in found]
        if found:
            question = ('%d other group(s) are the same shape as %s:\n\n  %s'
                        '\n\nMake them all one part?\n\nThey are compared to '
                        'the nearest %g mm. Answer No to make %s a part on '
                        'its own.'
                        % (len(found), here, '\n  '.join(others[:12]),
                           self._mark_tol_mm(), here))
            take_all = messagebox.askyesno('Make component', question)
        else:
            take_all = False
            if not messagebox.askyesno(
                    'Make component',
                    'Nothing else in the model is the same shape as %s.\n\n'
                    'Make it a part on its own anyway? A part with one copy '
                    'is still a drawing you can place again.' % here):
                return None
        name = simpledialog.askstring(
            'Make component', 'Name this part:', initialvalue=here,
            parent=self.root)
        if not name:
            return None
        gids = [gid] + ([o['id'] for o in found] if take_all else [])
        self._push_undo('make component')
        try:
            made = scp.make_component(self.groups, gids, name)
        except ValueError as exc:
            messagebox.showerror('Make component', str(exc))
            return None
        self._refresh_group_list()
        self._set_status('%s: %d copy(ies) of one part.' % (made, len(gids)),
                         'ok')
        self._draw()
        return made

    def _menu_make_unique(self, gid):
        name = self._component_of(gid)
        if not name:
            messagebox.showinfo('Make unique',
                                '%s is not a copy of anything.'
                                % self._group_display_name(gid))
            return None
        n = self._component_copies(gid)
        self._push_undo('make unique')
        scp.make_unique(self.groups, gid)
        self._refresh_group_list()
        self._set_status(
            '%s is its own part now; %d copy(ies) of %s left. Its rods are '
            'untouched.' % (self._group_display_name(gid), n - 1, name), 'ok')
        self._draw()
        return name

    # ── the envelope, where it can be read ─────────────────────────────────

    def _component_dialog(self, name):
        """Every copy of a part, rod by rod, worst first."""
        report = scp.verify(self.nodes, self.members, self.groups, name,
                            self._mark_tol_mm())
        rows = scp.envelope(self.nodes, self.members, self.groups, name,
                            self.member_checks, self._mark_tol_mm())
        win = tk.Toplevel(self.root)
        win.title('Component: %s' % name)
        win.transient(self.root)
        tk.Label(win, text=name, font=('', 12, 'bold')).pack(pady=(12, 2))
        tk.Label(win,
                 text='Built %d time(s). A component is fabricated ONCE, so '
                      'every section has to carry the worst of its copies -- '
                      'not the copy you happen to be looking at. The rod '
                      'that decides each one is named below.'
                      % report['instances'],
                 fg=HINT_FG, justify='left', wraplength=560,
                 font=('Helvetica', 8)).pack(anchor='w', padx=14)
        if report['differ']:
            tk.Label(win,
                     text='%d copy(ies) no longer match the rest (%s) and '
                          'are left out of the sizing. Either put them back '
                          'or make them unique.'
                          % (len(report['differ']),
                             ', '.join(g['name'] for g in report['differ'])),
                     fg='#9a3412', justify='left', wraplength=560,
                     font=('Helvetica', 8, 'bold')).pack(anchor='w', padx=14,
                                                         pady=(4, 0))
        txt = tk.Text(win, width=76, height=min(26, max(8, len(rows) + 6)),
                      font=('Courier', 8), wrap='none')
        txt.pack(fill='both', expand=True, padx=14, pady=(6, 4))
        for line in self._component_report(name, report, rows):
            txt.insert('end', line + '\n')
        txt.config(state='disabled')
        tk.Button(win, text='Close', command=win.destroy).pack(pady=(0, 12))
        self._last_component_win = win
        return win

    def _component_report(self, name, report=None, rows=None):
        if report is None:
            report = scp.verify(self.nodes, self.members, self.groups, name,
                                self._mark_tol_mm())
        if rows is None:
            rows = scp.envelope(self.nodes, self.members, self.groups, name,
                                self.member_checks, self._mark_tol_mm())
        out = ['COPIES', '']
        for g in report['agree']:
            flag = ' (mirrored)' if g in report['mirrored'] else ''
            out.append('  %s%s' % (g['name'], flag))
        for g in report['differ']:
            out.append('  %s  -- NO LONGER MATCHES' % g['name'])
        out += ['', 'RODS OF THE PART  (worst copy decides each one)', '']
        if not rows:
            out.append('  Nothing to line up: the copies do not agree on a')
            out.append('  shape, so there is no part to size.')
            return out
        out.append('%4s %10s %-14s %8s %8s   %s'
                   % ('#', 'length m', 'section', 'worst', 'spread',
                      'decided by rod'))
        for r in sorted(rows, key=lambda r: (-(r['worst_util'] or -1),
                                             r['position'])):
            out.append('%4d %10.3f %-14s %8s %8s   %d'
                       % (r['position'], r['length_m'], r['profile'][:14],
                          '--' if r['worst_util'] is None
                          else '%.3f' % r['worst_util'],
                          '--' if r['spread'] is None
                          else '%.3f' % r['spread'],
                          r['worst_rod']))
        worst = max((r for r in rows if r['spread'] is not None),
                    key=lambda r: r['spread'], default=None)
        if worst is not None and worst['spread'] > 0:
            out += ['',
                    'Widest spread: rod %d of the part runs from %.3f to '
                    '%.3f across' % (worst['position'], worst['best_util'],
                                     worst['worst_util']),
                    'the copies. Sizing from the lightest would leave the '
                    'heaviest at %.3f.' % worst['worst_util']]
        return out
