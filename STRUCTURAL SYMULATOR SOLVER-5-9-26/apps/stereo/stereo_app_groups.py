"""The Groups panel: name branches of the model and diagnose them one by one.

Roadmap v2 4.1's UI. The model and the maths are in `stereo_groups` and
`stereo_checks.recommend_for_group`; this module is only the panel, the
right-click properties box and the handlers between them.

Everything here rests on the two rules `stereo_groups` argues in full: a ROD
belongs to exactly one group, and a NODE's membership is DERIVED from the
rods that touch it. So there is no "add node to group" control, and there is
no way to put a rod in two groups -- not because it is forbidden in the UI
but because `assign` moves it, and `assign` is the only way in.

The tree is a Listbox rather than a ttk.Treeview on purpose. Every other
list in this tab is a Listbox, `_group_rows` already has to compute the
indentation for the report, and a Treeview would bring its own selection
model and its own styling to keep in step with the rest of the panel for no
behaviour that is wanted here.
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from apps.stereo.stereo_app_shell import HINT_FG
from apps.stereo import stereo_groups as sgp
from apps.stereo import stereo_checks as sk
from apps.stereo import stereo_profiles as sp
from apps.stereo.stereo_app_constants import BG, PANEL_TEXT_W


class StereoGroupsMixin:

    # ── the panel ──────────────────────────────────────────────────────────

    def _build_groups_panel(self, parent):
        box = tk.LabelFrame(parent, text='Groups', bg=BG,
                            font=('Helvetica', 10, 'bold'))
        box.pack(fill='both', padx=6, pady=(4, 8))

        tk.Label(box, text='A group is a named set of RODS -- a branch of the '
                           'structure. Groups nest as deep as you like. The '
                           'nodes a group touches follow from its rods, so a '
                           'joint shared with another branch cannot be '
                           'forgotten. Anything unassigned is Ungrouped.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W).pack(anchor='w', padx=6, pady=(2, 4))

        self.group_list = tk.Listbox(box, height=7, exportselection=False,
                                     font=('Courier', 8), activestyle='none')
        self.group_list.pack(fill='x', padx=6, pady=(0, 2))
        self.group_list.bind('<<ListboxSelect>>', self._on_group_pick)
        self.group_list.bind('<Double-Button-1>',
                             lambda _e: self._group_select_rods())
        # The properties box the user asked for, on the row itself.
        for seq in ('<Button-3>', '<Button-2>', '<Control-Button-1>'):
            self.group_list.bind(seq, self._on_group_right_click)

        self.group_note = tk.Label(box, text='No groups yet.', bg=BG,
                                   fg=HINT_FG, font=('Helvetica', 8),
                                   justify='left', wraplength=PANEL_TEXT_W)
        self.group_note.pack(anchor='w', padx=6, pady=(0, 4))

        mk = tk.Frame(box, bg=BG)
        mk.pack(fill='x', padx=6)
        tk.Button(mk, text='New from selection', font=('Helvetica', 8),
                  command=self._group_new_from_selection
                  ).pack(side='left', expand=True, fill='x')
        tk.Button(mk, text='New subgroup', font=('Helvetica', 8),
                  command=self._group_new_subgroup
                  ).pack(side='left', expand=True, fill='x', padx=(3, 0))

        ed = tk.Frame(box, bg=BG)
        ed.pack(fill='x', padx=6, pady=(2, 0))
        tk.Button(ed, text='Rename', font=('Helvetica', 8),
                  command=self._group_rename).pack(side='left', expand=True,
                                                   fill='x')
        tk.Button(ed, text='Delete', font=('Helvetica', 8), fg='#a3241a',
                  command=self._group_delete).pack(side='left', expand=True,
                                                   fill='x', padx=(3, 0))

        asg = tk.Frame(box, bg=BG)
        asg.pack(fill='x', padx=6, pady=(4, 0))
        tk.Button(asg, text='Add selection', font=('Helvetica', 8),
                  command=self._group_assign_selection
                  ).pack(side='left', expand=True, fill='x')
        tk.Button(asg, text='Ungroup selection', font=('Helvetica', 8),
                  command=self._group_unassign_selection
                  ).pack(side='left', expand=True, fill='x', padx=(3, 0))

        tk.Button(box, text='Select this group in the view',
                  font=('Helvetica', 8), command=self._group_select_rods
                  ).pack(fill='x', padx=6, pady=(4, 0))

        # ── one section for the whole group ────────────────────────────────
        sec = tk.LabelFrame(box, text='Section for the whole group', bg=BG,
                            font=('Helvetica', 8, 'bold'))
        sec.pack(fill='x', padx=6, pady=(6, 2))
        tk.Label(sec, text='Rods in a group need not match. Setting a section '
                           'here sets every rod in the group at once.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W - 12).pack(anchor='w', padx=4,
                                                    pady=(2, 2))
        row = tk.Frame(sec, bg=BG)
        row.pack(fill='x', padx=4)
        self.group_profile = tk.StringVar(value='')
        ttk.Combobox(row, textvariable=self.group_profile, state='readonly',
                     width=16, values=sp.catalog_names()
                     ).pack(side='left', fill='x', expand=True)
        tk.Button(row, text='Apply', font=('Helvetica', 8),
                  command=self._group_apply_profile).pack(side='left',
                                                          padx=(3, 0))

        # The family to size within, because "easier to build" usually means
        # one family for the job, not the lightest thing in the catalog.
        fam = tk.Frame(sec, bg=BG)
        fam.pack(fill='x', padx=4, pady=(3, 0))
        tk.Label(fam, text='Size within:', bg=BG,
                 font=('Helvetica', 8)).pack(side='left')
        self.group_family = tk.StringVar(value='(any)')
        ttk.Combobox(fam, textvariable=self.group_family, state='readonly',
                     width=13,
                     values=['(any)'] + sp.group_names()
                     ).pack(side='left', fill='x', expand=True, padx=(3, 0))

        tk.Button(sec, text='Recommend a section for this group',
                  font=('Helvetica', 8, 'bold'),
                  command=self._group_recommend).pack(fill='x', padx=4,
                                                      pady=(4, 4))

        # ── the checks a grouped model wants ──────────────────────────────
        chk = tk.Frame(box, bg=BG)
        chk.pack(fill='x', padx=6, pady=(4, 2))
        tk.Button(chk, text='Shared joints', font=('Helvetica', 8),
                  command=self._group_shared_nodes
                  ).pack(side='left', expand=True, fill='x')
        tk.Button(chk, text='Do the totals add up?', font=('Helvetica', 8),
                  command=self._group_reconcile
                  ).pack(side='left', expand=True, fill='x', padx=(3, 0))

        self._refresh_group_list()

    # ── the list ───────────────────────────────────────────────────────────

    def _group_rows(self):
        """(label, gid) per row, indented by depth, Ungrouped last.

        `None` as the gid is the Ungrouped set, which is a row like any other
        so that it cannot be overlooked -- it is where the rods nobody has
        assigned still are.
        """
        rows = []
        for g, lvl in sgp.walk(self.groups):
            deep = len(sgp.rods_of(self.groups, g['id'], deep=True))
            own = len(g['members'])
            count = ('%d' % own) if deep == own else ('%d/%d' % (own, deep))
            rows.append(('%s%s  [%s]' % ('   ' * lvl, g['name'], count),
                         g['id']))
        rest = sgp.ungrouped_rods(self.groups, len(self.members))
        if rest:
            rows.append(('%s  [%d]' % (sgp.UNGROUPED_NAME, len(rest)), None))
        return rows

    def _refresh_group_list(self, keep=None):
        if not hasattr(self, 'group_list'):
            return
        if keep is None:
            keep = getattr(self, '_group_sel', None)
        rows = self._group_rows()
        self._group_row_ids = [gid for _label, gid in rows]
        self.group_list.delete(0, 'end')
        for label, _gid in rows:
            self.group_list.insert('end', label)
        if keep in self._group_row_ids:
            i = self._group_row_ids.index(keep)
            self.group_list.selection_clear(0, 'end')
            self.group_list.selection_set(i)
            self._group_sel = keep
        else:
            self._group_sel = None
        self._refresh_group_note()

    def _current_group(self):
        """The selected gid, or False when nothing is selected.

        False rather than None, because None is a real answer here: it is
        the Ungrouped set.
        """
        sel = self.group_list.curselection() if hasattr(self, 'group_list') else ()
        if not sel:
            return False
        ids = getattr(self, '_group_row_ids', [])
        i = sel[0]
        return ids[i] if 0 <= i < len(ids) else False

    def _on_group_pick(self, _event=None):
        gid = self._current_group()
        self._group_sel = None if gid is False else gid
        self._refresh_group_note()

    def _group_rods(self, gid, deep=True):
        if gid is None:
            return sgp.ungrouped_rods(self.groups, len(self.members))
        return sgp.rods_of(self.groups, gid, deep=deep)

    def _group_display_name(self, gid):
        if gid is None:
            return sgp.UNGROUPED_NAME
        g = sgp.find(self.groups, gid)
        return g['name'] if g else '?'

    def _refresh_group_note(self):
        if not hasattr(self, 'group_note'):
            return
        gid = self._current_group()
        if gid is False:
            n = len(self.groups)
            rest = len(sgp.ungrouped_rods(self.groups, len(self.members)))
            self.group_note.config(
                text=('%d group(s); %d rod(s) still ungrouped. '
                      'Pick a row to see it, or right-click it for '
                      'properties.' % (n, rest)) if n else
                     ('No groups yet. Select rods in the view and press '
                      '"New from selection".'))
            return
        rods = self._group_rods(gid)
        nodes = sgp.nodes_of_rods(self.members, rods)
        worst = None
        if self.member_checks:
            vals = [self.member_checks[i].get('util') for i in rods
                    if i < len(self.member_checks)
                    and self.member_checks[i].get('util') is not None]
            worst = max(vals) if vals else None
        self.group_note.config(
            text='%s: %d rod(s), %d node(s)%s' % (
                self._group_display_name(gid), len(rods), len(nodes),
                ('' if worst is None else ', worst utilisation %.2f' % worst)))

    # ── creating and editing ───────────────────────────────────────────────

    def _group_new_from_selection(self):
        idx = sorted(self._selection_member_idx())
        if not idx:
            messagebox.showinfo(
                'Groups',
                'Select the rods first -- click one, or drag a box over '
                'several. Selecting only nodes works too: the rods with BOTH '
                'ends selected are taken.')
            return
        name = simpledialog.askstring('New group', 'Name for this group:',
                                      parent=self.root)
        if not name:
            return
        self._push_undo('new group')
        g = sgp.new_group(self.groups, name, members=idx)
        self._refresh_group_list(keep=g['id'])
        self._group_note_action('%s: %d rod(s).' % (g['name'], len(idx)))

    def _group_new_subgroup(self):
        gid = self._current_group()
        if gid is False or gid is None:
            messagebox.showinfo('Groups',
                                'Pick the group to nest the new one inside. '
                                'Ungrouped cannot be a parent -- it is what '
                                'is left over, not a branch.')
            return
        idx = sorted(self._selection_member_idx())
        name = simpledialog.askstring(
            'New subgroup',
            'Name for the subgroup of %s:' % self._group_display_name(gid),
            parent=self.root)
        if not name:
            return
        self._push_undo('new subgroup')
        g = sgp.new_group(self.groups, name, parent=gid, members=idx)
        self._refresh_group_list(keep=g['id'])
        self._group_note_action(
            '%s inside %s%s.' % (g['name'], self._group_display_name(gid),
                                 (', %d rod(s)' % len(idx)) if idx else
                                 ' (empty -- add a selection to it)'))

    def _group_rename(self):
        gid = self._current_group()
        if gid is False or gid is None:
            messagebox.showinfo('Groups', 'Pick a group to rename.')
            return
        name = simpledialog.askstring('Rename group', 'New name:',
                                      initialvalue=self._group_display_name(gid),
                                      parent=self.root)
        if not name:
            return
        self._push_undo('rename group')
        sgp.rename(self.groups, gid, name)
        self._refresh_group_list(keep=gid)

    def _group_delete(self):
        gid = self._current_group()
        if gid is False or gid is None:
            messagebox.showinfo('Groups', 'Pick a group to delete.')
            return
        name = self._group_display_name(gid)
        kids = sgp.children(self.groups, gid)
        deep = False
        if kids:
            deep = messagebox.askyesno(
                'Delete group',
                '%s has %d subgroup(s).\n\nYes: delete them too.\n'
                'No: keep them, moved up to where %s was.'
                % (name, len(kids), name))
        self._push_undo('delete group')
        sgp.delete(self.groups, gid, recursive=bool(deep))
        self._refresh_group_list()
        self._group_note_action('%s deleted; its rods are Ungrouped again.'
                                % name)

    def _group_assign_selection(self):
        gid = self._current_group()
        if gid is False:
            messagebox.showinfo('Groups', 'Pick the group to add them to.')
            return
        idx = sorted(self._selection_member_idx())
        if not idx:
            messagebox.showinfo('Groups', 'Select the rods to add first.')
            return
        self._push_undo('assign to group')
        if gid is None:
            sgp.unassign(self.groups, idx)
            moved = len(idx)
        else:
            sgp.assign(self.groups, gid, idx)
            moved = len(idx)
        self._refresh_group_list(keep=gid)
        self._group_note_action(
            '%d rod(s) moved to %s. A rod is only ever in one group, so any '
            'that were elsewhere have left it.'
            % (moved, self._group_display_name(gid)))

    def _group_unassign_selection(self):
        idx = sorted(self._selection_member_idx())
        if not idx:
            messagebox.showinfo('Groups', 'Select the rods to ungroup first.')
            return
        self._push_undo('ungroup selection')
        sgp.unassign(self.groups, idx)
        self._refresh_group_list(keep=self._group_sel)
        self._group_note_action('%d rod(s) are Ungrouped.' % len(idx))

    def _group_select_rods(self):
        """Put the group's rods in the view's selection, so it can be seen.

        Reuses the selection highlight every other tool here draws, rather
        than adding a second way for a rod to look special.
        """
        gid = self._current_group()
        if gid is False:
            return
        rods = self._group_rods(gid)
        if not rods:
            self._group_note_action('%s has no rods yet.'
                                    % self._group_display_name(gid))
            return
        self.selected_members = set(rods)
        self.selected_member = rods[0] if len(rods) == 1 else None
        self.selected_nodes = set(sgp.nodes_of_rods(self.members, rods))
        self._refresh_all()
        self._group_note_action('%s selected: %d rod(s), %d node(s).'
                                % (self._group_display_name(gid), len(rods),
                                   len(self.selected_nodes)))

    def _group_note_action(self, text):
        if hasattr(self, 'group_note'):
            self.group_note.config(text=text)

    # ── the section for a whole group ─────────────────────────────────────

    def _group_candidates(self):
        fam = getattr(self, 'group_family', None)
        pick = fam.get() if fam is not None else '(any)'
        if not pick or pick == '(any)':
            return None
        names = sp.profiles_in_group(pick)
        return names or None

    def _group_apply_profile(self):
        gid = self._current_group()
        if gid is False:
            messagebox.showinfo('Groups', 'Pick a group first.')
            return
        name = self.group_profile.get()
        if not name:
            messagebox.showinfo('Groups', 'Choose a profile to apply.')
            return
        rods = self._group_rods(gid)
        if not rods:
            messagebox.showinfo('Groups', 'That group has no rods.')
            return
        self._push_undo('section for group')
        n = sk.apply_recommendation(self.members, rods, name)
        self.results = None
        self.member_checks = None
        self._refresh_all()
        self._group_note_action(
            '%s: %d rod(s) set to %s. Analyze again -- stiffening a branch '
            'changes how the load shares out.'
            % (self._group_display_name(gid), n, name))

    def _group_recommend(self):
        gid = self._current_group()
        if gid is False:
            messagebox.showinfo('Groups', 'Pick a group first.')
            return
        if not self.results:
            messagebox.showinfo(
                'Recommend a section',
                'Analyze first. A recommendation is sized from the forces '
                'in the rods, so it needs a solve to work from.')
            return
        rods = self._group_rods(gid)
        if not rods:
            messagebox.showinfo('Groups', 'That group has no rods.')
            return
        rec = sk.recommend_for_group(self.nodes, self.members,
                                     self.results['member_res'], rods,
                                     candidates=self._group_candidates())
        if rec is None:
            messagebox.showinfo('Recommend a section',
                                'Nothing in that group can be checked yet.')
            return
        self._show_group_recommendation(gid, rec, rods)

    def _show_group_recommendation(self, gid, rec, rods):
        win = tk.Toplevel(self.root)
        win.title('Section for %s' % self._group_display_name(gid))
        win.resizable(False, False)
        win.transient(self.root)

        head = ('%s  --  %d rod(s)' % (self._group_display_name(gid), len(rods)))
        tk.Label(win, text=head, font=('', 12, 'bold')).pack(pady=(12, 2))

        body = tk.Frame(win)
        body.pack(fill='both', expand=True, padx=16, pady=(4, 4))

        def line(txt, bold=False, fg='#1d2328'):
            tk.Label(body, text=txt, justify='left', anchor='w', fg=fg,
                     font=('Helvetica', 9, 'bold') if bold
                     else ('Helvetica', 9)).pack(anchor='w')

        if not rec.get('name'):
            line('No catalog section carries every rod in this group.',
                 bold=True, fg='#a3241a')
            line(rec.get('note', ''))
        else:
            line('Recommended:  %s' % rec['name'], bold=True)
            line('Governing rod %s at %.2f of capacity'
                 % (rec['governing'], rec['worst_util']))
            line('Spare at that rod: %.0f%%' % (100.0 * (rec['spare'] or 0.0)))
            if rec.get('overshoot') is not None:
                line('Unused capacity across the group: %.0f%%  '
                     '(the price of one section for the branch)'
                     % (100.0 * rec['overshoot']), fg=HINT_FG)
            if rec['governing'] != rec['largest_force']:
                line('')
                line('Note: rod %s carries the LARGEST force (%.1f kN), but '
                     'rod %s decides the section.'
                     % (rec['largest_force'],
                        rec['forces'].get(rec['largest_force'], 0.0),
                        rec['governing']), bold=True)
                line('Compression capacity depends on KL/r, so a longer rod '
                     'can need more section than a rod carrying more force. '
                     'Sizing for the largest force alone would leave rod %s '
                     'overloaded.' % rec['governing'], fg=HINT_FG)
            if rec.get('next_up'):
                line('')
                line('Next size up: %s' % rec['next_up'], fg=HINT_FG)
            line('')
            line('Sized from the forces in the current solve. Applying it '
                 'redistributes them, so Analyze again afterwards.',
                 fg=HINT_FG)

        btns = tk.Frame(win)
        btns.pack(fill='x', padx=16, pady=(6, 12))

        def apply_now(name):
            self._push_undo('section for group')
            n = sk.apply_recommendation(self.members, rods, name)
            self.results = None
            self.member_checks = None
            self.group_profile.set(name)
            win.destroy()
            self._refresh_all()
            self._group_note_action(
                '%s: %d rod(s) set to %s. Analyze again.'
                % (self._group_display_name(gid), n, name))

        if rec.get('name'):
            tk.Button(btns, text='Apply %s' % rec['name'],
                      font=('Helvetica', 9, 'bold'),
                      command=lambda: apply_now(rec['name'])
                      ).pack(side='left', expand=True, fill='x')
            if rec.get('next_up'):
                tk.Button(btns, text='Apply %s instead' % rec['next_up'],
                          font=('Helvetica', 9),
                          command=lambda: apply_now(rec['next_up'])
                          ).pack(side='left', expand=True, fill='x',
                                 padx=(6, 0))
        tk.Button(btns, text='Close', command=win.destroy
                  ).pack(side='left', padx=(6, 0))
        self._group_rec_win = win
        return win

    # ── right-click properties ────────────────────────────────────────────

    def _on_group_right_click(self, event):
        """Select the row under the pointer, then offer its actions.

        Selecting first matters: a context menu that acts on whatever was
        selected BEFORE the right-click acts on the wrong group about half
        the time.
        """
        try:
            i = self.group_list.nearest(event.y)
        except tk.TclError:
            return
        if i < 0 or i >= self.group_list.size():
            return
        self.group_list.selection_clear(0, 'end')
        self.group_list.selection_set(i)
        self._on_group_pick()

        menu = tk.Menu(self.group_list, tearoff=False)
        menu.add_command(label='Properties…', command=self._group_properties)
        menu.add_command(label='Recommend a section…',
                         command=self._group_recommend)
        menu.add_separator()
        menu.add_command(label='Select in the view',
                         command=self._group_select_rods)
        menu.add_command(label='Add the current selection',
                         command=self._group_assign_selection)
        menu.add_separator()
        menu.add_command(label='Rename…', command=self._group_rename)
        menu.add_command(label='Delete', command=self._group_delete)
        self._group_menu = menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'

    def _group_properties(self):
        gid = self._current_group()
        if gid is False:
            return
        rods = self._group_rods(gid)
        rows = sgp.group_summary(self.groups, self.nodes, self.members,
                                 self.results['member_res'] if self.results
                                 else None,
                                 self.member_checks,
                                 unit_weight_kN_m3=self.unit_weight_var.get())
        row = next((r for r in rows if r['id'] == gid), None)

        win = tk.Toplevel(self.root)
        win.title('%s — properties' % self._group_display_name(gid))
        win.resizable(False, False)
        win.transient(self.root)
        tk.Label(win, text=self._group_display_name(gid),
                 font=('', 13, 'bold')).pack(pady=(12, 0))
        sub = ('top level' if gid is None or
               sgp.find(self.groups, gid)['parent'] is None
               else 'inside %s' % self._group_display_name(
                   sgp.find(self.groups, gid)['parent']))
        tk.Label(win, text=sub, fg=HINT_FG).pack()

        grid = tk.Frame(win)
        grid.pack(fill='x', padx=18, pady=(10, 4))

        def kv(r, k, v):
            tk.Label(grid, text=k, anchor='w', width=26,
                     font=('Helvetica', 9)).grid(row=r, column=0, sticky='w')
            tk.Label(grid, text=v, anchor='w',
                     font=('Helvetica', 9, 'bold')).grid(row=r, column=1,
                                                         sticky='w')

        nodes_touched = sgp.nodes_of_rods(self.members, rods)
        kv(0, 'Rods (with subgroups)', '%d' % len(rods))
        if gid is not None:
            kv(1, 'Rods of its own', '%d' % len(sgp.find(self.groups,
                                                         gid)['members']))
        kv(2, 'Nodes touched', '%d' % len(nodes_touched))
        if row:
            kv(3, 'Total length', '%.3f m' % row['length_m'])
            kv(4, 'Weight', '%.2f kN' % row['weight_kN'])
            kv(5, 'Worst utilisation',
               'not checked' if row['worst_util'] is None
               else '%.2f at rod %s' % (row['worst_util'], row['worst_rod']))
        profiles = sorted({(self.members[i].get('profile') or '(unnamed)')
                           for i in rods if 0 <= i < len(self.members)})
        kv(6, 'Sections in use',
           ', '.join(profiles)[:44] if profiles else '-')

        shared = sgp.shared_nodes(self.groups, self.members,
                                  len(self.members))
        mine = {n: ids for n, ids in shared.items() if n in set(nodes_touched)}
        kv(7, 'Joints shared with others', '%d' % len(mine))

        tk.Label(win, text='Sections in use is a list, not a fault: a group '
                           'need not be uniform. Setting one section for the '
                           'group is what makes it so.',
                 fg=HINT_FG, justify='left', wraplength=380,
                 font=('Helvetica', 8)).pack(anchor='w', padx=18, pady=(2, 0))

        btns = tk.Frame(win)
        btns.pack(fill='x', padx=18, pady=(10, 12))
        tk.Button(btns, text='Recommend a section…',
                  font=('Helvetica', 9, 'bold'),
                  command=lambda: (win.destroy(), self._group_recommend())
                  ).pack(side='left', expand=True, fill='x')
        tk.Button(btns, text='Select in the view',
                  command=lambda: (win.destroy(), self._group_select_rods())
                  ).pack(side='left', expand=True, fill='x', padx=(6, 0))
        tk.Button(btns, text='Close', command=win.destroy
                  ).pack(side='left', padx=(6, 0))
        self._group_props_win = win
        return win

    # ── the two checks a grouped model wants ──────────────────────────────

    def _group_shared_nodes(self):
        if not self.groups:
            messagebox.showinfo('Shared joints', 'No groups yet.')
            return
        rows = sgp.shared_node_rows(
            self.groups, self.nodes, self.members,
            self.results['member_res'] if self.results else None)
        win = tk.Toplevel(self.root)
        win.title('Joints shared between groups')
        win.transient(self.root)
        tk.Label(win, text='Joints shared between groups',
                 font=('', 12, 'bold')).pack(pady=(12, 2))
        tk.Label(win, text='Every sharing is listed. CROSS is where two '
                           'separate branches meet; INTERNAL is a group with '
                           'its own subgroup, which is still a joint to '
                           'detail if the subgroup is fabricated apart. '
                           'Cross first.',
                 fg=HINT_FG, justify='left', wraplength=520,
                 font=('Helvetica', 8)).pack(anchor='w', padx=14)
        txt = tk.Text(win, width=78, height=min(22, max(6, len(rows) * 3 + 2)),
                      font=('Courier', 8), wrap='none')
        txt.pack(fill='both', expand=True, padx=14, pady=(6, 4))
        if not rows:
            txt.insert('end', 'No joint is shared between groups.\n')
        for r in rows:
            txt.insert('end', 'Node %-5d  %s  (%d groups)\n'
                       % (r['node'], r['kind'].upper(), r['n_groups']))
            for s in r['sides']:
                if 'F' in s:
                    txt.insert('end', '    %-18s rods %-22s '
                                      'F = (%8.2f, %8.2f, %8.2f) kN  |F| %.2f\n'
                               % (s['name'][:18],
                                  ','.join(str(i) for i in s['rods'])[:22],
                                  s['Fx'], s['Fy'], s['Fz'], s['F']))
                else:
                    txt.insert('end', '    %-18s rods %s\n'
                               % (s['name'][:18],
                                  ','.join(str(i) for i in s['rods'])))
            txt.insert('end', '\n')
        txt.config(state='disabled')
        tk.Button(win, text='Close', command=win.destroy).pack(pady=(0, 12))
        self._group_shared_win = win
        return win

    def _group_reconcile(self):
        rec = sgp.totals_reconcile(self.groups, self.nodes, self.members,
                                   unit_weight_kN_m3=self.unit_weight_var.get())
        if rec['ok']:
            messagebox.showinfo(
                'Totals',
                'Every rod is accounted for exactly once.\n\n'
                '%d in groups + %d ungrouped = %d, and the model has %d.\n'
                'Total length %.3f m, matching the model.'
                % (rec['rods_in_groups'], rec['rods_ungrouped'],
                   rec['rods_counted'], rec['rods_in_model'],
                   rec['length_counted_m']))
        else:
            messagebox.showerror(
                'Totals',
                'The per-group figures do NOT account for the model.\n\n'
                '%d in groups + %d ungrouped = %d, but the model has %d.\n'
                'Length counted %.3f m against %.3f m.\n\n'
                'A rod belongs to exactly one group, so this is a bug rather '
                'than a rounding question -- please report it.'
                % (rec['rods_in_groups'], rec['rods_ungrouped'],
                   rec['rods_counted'], rec['rods_in_model'],
                   rec['length_counted_m'], rec['length_in_model_m']))
        return rec
