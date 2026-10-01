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
from apps.stereo.stereo_app_constants import (BG, PANEL_TEXT_W, GROUP_TINTS,
                                              EDIT_BANNER_COLOR)


class StereoGroupsMixin:

    # ── the panel ──────────────────────────────────────────────────────────

    def _build_groups_panel(self, parent):
        """Groups as LAYERS, in the Build panel.

        Everyday work is four buttons and the list: make a group from the
        selection, add the selection to a group, take it out again, and
        open a group -- right-click its row, or right-click one of its rods
        on the canvas. Everything rarer (a section for the whole group, the
        checks, the reports) is one click further, under More group tools
        and the Actions menu, so the panel reads at a glance.
        """
        box = tk.LabelFrame(parent, text='Groups (layers)', bg=BG,
                            font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=(6, 4))
        self._groups_box = box

        tk.Label(box, text='Every group -- and every subgroup -- is a closed '
                           'object: it moves whole, its parts stay put. '
                           'Right-click a group (here or on the canvas) to '
                           'open it; right-click empty canvas or press Done '
                           'to close it again.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W).pack(anchor='w', padx=6, pady=(2, 4))

        # Grouped / Ungrouped: how the model is DRAWN. The locks hold in
        # both -- switching the view is not a way round them.
        mode = tk.Frame(box, bg=BG)
        mode.pack(fill='x', padx=6, pady=(0, 2))
        tk.Label(mode, text='Show:', bg=BG,
                 font=('Helvetica', 8, 'bold')).pack(side='left')
        for text, val in (('Plain', False), ('Coloured by group', True)):
            tk.Radiobutton(mode, text=text, variable=self.group_view,
                           value=val, bg=BG, font=('Helvetica', 8),
                           command=self._draw).pack(side='left', padx=(4, 0))

        self.group_list = tk.Listbox(box, height=7, exportselection=False,
                                     font=('Courier', 8), activestyle='none')
        self.group_list.pack(fill='x', padx=6, pady=(0, 2))
        self.group_list.bind('<<ListboxSelect>>', self._on_group_pick)
        self.group_list.bind('<Double-Button-1>',
                             lambda _e: self._group_select_rods())
        # Right-click a row: open that group for editing (the request, in
        # so many words). The other actions are on the Actions menu.
        for seq in ('<Button-3>', '<Button-2>', '<Control-Button-1>'):
            self.group_list.bind(seq, self._on_group_right_click)

        # The one line that says what is open, with the way out beside it.
        edit_row = tk.Frame(box, bg=BG)
        edit_row.pack(fill='x', padx=6, pady=(0, 2))
        self.group_edit_state = tk.Label(edit_row, text='', bg=BG,
                                         fg='#1d2328', anchor='w',
                                         font=('Helvetica', 8, 'bold'),
                                         justify='left',
                                         wraplength=PANEL_TEXT_W - 90)
        self.group_edit_state.pack(side='left', fill='x', expand=True)
        self.group_edit_btn = tk.Button(edit_row, font=('Helvetica', 8, 'bold'),
                                        command=self._group_edit_toggle)
        self.group_edit_btn.pack(side='right')

        self.group_note = tk.Label(box, text='No groups yet.', bg=BG,
                                   fg=HINT_FG, font=('Helvetica', 8),
                                   justify='left', wraplength=PANEL_TEXT_W)
        self.group_note.pack(anchor='w', padx=6, pady=(0, 4))

        mk = tk.Frame(box, bg=BG)
        mk.pack(fill='x', padx=6)
        tk.Button(mk, text='New group from selection', font=('Helvetica', 8),
                  command=self._group_new_from_selection
                  ).pack(side='left', expand=True, fill='x')
        tk.Button(mk, text='New subgroup', font=('Helvetica', 8),
                  command=self._group_new_subgroup
                  ).pack(side='left', expand=True, fill='x', padx=(3, 0))

        asg = tk.Frame(box, bg=BG)
        asg.pack(fill='x', padx=6, pady=(3, 0))
        tk.Button(asg, text='Add selection to group', font=('Helvetica', 8),
                  command=self._group_assign_selection
                  ).pack(side='left', expand=True, fill='x')
        tk.Button(asg, text='Remove from group', font=('Helvetica', 8),
                  command=self._group_unassign_selection
                  ).pack(side='left', expand=True, fill='x', padx=(3, 0))

        act = tk.Frame(box, bg=BG)
        act.pack(fill='x', padx=6, pady=(3, 4))
        tk.Button(act, text='Select in view', font=('Helvetica', 8),
                  command=self._group_select_rods
                  ).pack(side='left', expand=True, fill='x')
        self.group_actions_btn = tk.Menubutton(act, text='Actions ▾',
                                               font=('Helvetica', 8),
                                               relief='raised')
        self.group_actions_btn.pack(side='left', expand=True, fill='x',
                                    padx=(3, 0))
        self.group_actions_btn['menu'] = self._group_actions_menu(
            self.group_actions_btn)

        # ── rarer tools, folded away ──────────────────────────────────────
        self.group_more_open = tk.BooleanVar(value=False)
        tk.Checkbutton(box, text='More group tools (section, checks, PDF)',
                       variable=self.group_more_open, bg=BG,
                       font=('Helvetica', 8), anchor='w',
                       command=self._group_toggle_more).pack(fill='x', padx=6)
        more = self._group_more = tk.Frame(box, bg=BG)

        sec = tk.LabelFrame(more, text='Section for the whole group', bg=BG,
                            font=('Helvetica', 8, 'bold'))
        sec.pack(fill='x', padx=6, pady=(4, 2))
        tk.Label(sec, text='Rods in a group need not match. Setting a section '
                           'here sets every rod in the group at once, locked '
                           'or not.',
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

        chk = tk.Frame(more, bg=BG)
        chk.pack(fill='x', padx=6, pady=(4, 2))
        tk.Button(chk, text='Shared joints', font=('Helvetica', 8),
                  command=self._group_shared_nodes
                  ).pack(side='left', expand=True, fill='x')
        tk.Button(chk, text='Do the totals add up?', font=('Helvetica', 8),
                  command=self._group_reconcile
                  ).pack(side='left', expand=True, fill='x', padx=(3, 0))
        rep = tk.Frame(more, bg=BG)
        rep.pack(fill='x', padx=6, pady=(2, 6))
        tk.Button(rep, text='PDF of all groups…', font=('Helvetica', 8, 'bold'),
                  command=self._export_groups_pdf
                  ).pack(side='left', expand=True, fill='x')
        tk.Button(rep, text='PDF of this group…', font=('Helvetica', 8),
                  command=lambda: self._export_groups_pdf(only_picked=True)
                  ).pack(side='left', expand=True, fill='x', padx=(3, 0))

        self._refresh_group_edit_controls()
        self._refresh_group_list()

    def _group_toggle_more(self):
        if self.group_more_open.get():
            self._group_more.pack(fill='x')
        else:
            self._group_more.pack_forget()
        outer = getattr(self, 'panel_outer', None)
        if outer is not None:
            outer.fit_to_content()

    def _group_actions_menu(self, master):
        """The picked group's actions -- the list's old right-click menu,
        now on a button, since right-click opens the group instead."""
        menu = tk.Menu(master, tearoff=False)
        menu.add_command(label='Open for editing',
                         command=lambda: self._group_open(self._current_group()))
        menu.add_command(label='Properties…', command=self._group_properties)
        menu.add_command(label='Recommend a section…',
                         command=self._group_recommend)
        menu.add_separator()
        menu.add_command(label='Select in the view',
                         command=self._group_select_rods)
        menu.add_command(label='Add the current selection',
                         command=self._group_assign_selection)
        menu.add_command(label='PDF of this group…',
                         command=lambda: self._export_groups_pdf(
                             only_picked=True))
        menu.add_separator()
        menu.add_command(label='Move group…', command=self._group_move_dialog)
        menu.add_command(label='Rename…', command=self._group_rename)
        menu.add_command(label='Delete', command=self._group_delete)
        menu.add_separator()
        menu.add_command(label='Shared joints…',
                         command=self._group_shared_nodes)
        menu.add_command(label='Do the totals add up?',
                         command=self._group_reconcile)
        return menu

    # ── the list ───────────────────────────────────────────────────────────

    def _group_rows(self):
        """(label, gid) per row, indented by depth, Ungrouped last.

        `None` as the gid is the Ungrouped set, which is a row like any other
        so that it cannot be overlooked -- it is where the rods nobody has
        assigned still are.
        """
        rows = []
        editing = getattr(self, '_group_editing', None)
        for g, lvl in sgp.walk(self.groups):
            deep = len(sgp.rods_of(self.groups, g['id'], deep=True))
            own = len(g['members'])
            count = ('%d' % own) if deep == own else ('%d/%d' % (own, deep))
            mark = '✎ ' if g['id'] == editing else ''
            rows.append(('%s%s%s  [%s]' % ('   ' * lvl, mark, g['name'], count),
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
        if not self._guard_membership('New group', idx, target=-1):
            return
        # While a group is open, a new one is made INSIDE it: everything
        # outside is locked, so that is the only place it could go.
        parent = self._editing_gid()
        name = simpledialog.askstring('New group', 'Name for this group:',
                                      parent=self.root)
        if not name:
            return
        self._push_undo('new group')
        g = sgp.new_group(self.groups, name, parent=parent, members=idx)
        self._refresh_group_list(keep=g['id'])
        self._group_note_action('%s: %d rod(s).' % (g['name'], len(idx)))
        self._draw()

    def _group_new_subgroup(self):
        gid = self._current_group()
        if gid is False or gid is None:
            messagebox.showinfo('Groups',
                                'Pick the group to nest the new one inside. '
                                'Ungrouped cannot be a parent -- it is what '
                                'is left over, not a branch.')
            return
        idx = sorted(self._selection_member_idx())
        if not self._guard_outside_edit('New subgroup', gid):
            return
        if not self._guard_membership('New subgroup', idx, target=-1):
            return
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
        self._draw()

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
        self._draw()

    def _group_delete(self):
        gid = self._current_group()
        if gid is False or gid is None:
            messagebox.showinfo('Groups', 'Pick a group to delete.')
            return
        if not self._guard_outside_edit('Delete group', gid):
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
        self._draw()

    def _group_assign_selection(self):
        gid = self._current_group()
        if gid is False and self._editing_gid() is not None:
            gid = self._editing_gid()     # the open group, when none is picked
        if gid is False:
            messagebox.showinfo('Groups', 'Pick the group to add them to.')
            return
        idx = sorted(self._selection_member_idx())
        if not idx:
            messagebox.showinfo('Groups', 'Select the rods to add first.')
            return
        if not self._guard_outside_edit('Add to group', gid):
            return
        if not self._guard_membership('Add to group', idx, target=gid):
            return
        if gid is not None and not sgp.target_open(self.groups, gid,
                                                   self._editing_gid()):
            fresh = [i for i in idx
                     if i not in sgp.find(self.groups, gid)['members']]
            if fresh and not messagebox.askyesno(
                    'Add to a locked group',
                    '%s is locked. Add %d rod(s) to it?'
                    % (self._group_display_name(gid), len(fresh))):
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
        self._draw()

    def _group_unassign_selection(self):
        idx = sorted(self._selection_member_idx())
        if not idx:
            messagebox.showinfo('Groups', 'Select the rods to ungroup first.')
            return
        if not self._guard_membership('Ungroup selection', idx, target=None):
            return
        self._push_undo('ungroup selection')
        sgp.unassign(self.groups, idx)
        self._refresh_group_list(keep=self._group_sel)
        self._group_note_action('%d rod(s) are Ungrouped.' % len(idx))
        self._draw()

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

    def _guard_outside_edit(self, title, gid):
        """While a group is open, every other group -- and Ungrouped -- is
        blocked, including from the panel."""
        editing = self._editing_gid()
        if editing is None or gid is False:
            return True
        if gid is not None and (gid == editing or gid in
                                sgp.descendant_ids(self.groups, editing)):
            return True
        return self._group_refuse(
            title, '%s is outside the group being edited (%s). Press Done '
            'editing first.' % (self._group_display_name(gid),
                                self._group_display_name(editing)))

    def _guard_membership(self, title, idx, target):
        """A rod leaves a locked group only while that group is open."""
        block = sgp.assign_blockers(self.groups, idx, target,
                                    self._editing_gid())
        if not block:
            return True
        return self._group_refuse(
            title,
            'Those rods are part of a locked group -- %s.\n\nA rod is only '
            'ever in one group, so this would take them out of it. Open that '
            'group with Edit group first.'
            % sgp.describe_rods(self.groups, block))

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
        if not self._guard_outside_edit('Section for the group', gid):
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
        if not self._guard_outside_edit('Recommend a section', gid):
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

    def _section_table(self, parent, name, title=None):
        """A steel-table block for catalog section `name`: symbol, value,
        unit and what it means, one row each. Returns the frame, or None
        for a name the catalog does not have (a hand-typed section)."""
        rows = sp.section_properties(name)
        if not rows:
            return None
        box = tk.LabelFrame(parent, text=title or name,
                            font=('Helvetica', 8, 'bold'))
        for r, (sym, val, unit, meaning) in enumerate(rows):
            tk.Label(box, text=sym, font=('Helvetica', 8, 'bold'), anchor='w',
                     width=6).grid(row=r, column=0, sticky='w', padx=(6, 0))
            tk.Label(box, text=val, font=('Courier', 8), anchor='e',
                     width=9).grid(row=r, column=1, sticky='e')
            tk.Label(box, text=unit, font=('Helvetica', 8), anchor='w',
                     width=5).grid(row=r, column=2, sticky='w', padx=(3, 0))
            tk.Label(box, text=meaning, font=('Helvetica', 8), fg=HINT_FG,
                     anchor='w').grid(row=r, column=3, sticky='w', padx=(4, 6))
        tk.Label(box, text=sp.SECTION_PROPERTIES_NOTE, fg=HINT_FG,
                 font=('Helvetica', 7), justify='left', wraplength=360
                 ).grid(row=len(rows), column=0, columnspan=4, sticky='w',
                        padx=6, pady=(2, 3))
        return box

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

        def show_button(rod, caption, text):
            tk.Button(body, text=text, font=('Helvetica', 8),
                      command=lambda: self._show_rod(rod, caption)
                      ).pack(anchor='w', pady=(1, 3))

        if not rec.get('name'):
            line('No catalog section carries every rod in this group.',
                 bold=True, fg='#a3241a')
            line(rec.get('note', ''))
        else:
            line('Recommended:  %s' % rec['name'], bold=True)
            table = self._section_table(body, rec['name'],
                                        'Section properties -- %s' % rec['name'])
            if table is not None:
                table.pack(anchor='w', fill='x', pady=(2, 6))
            line('Governing rod %s at %.2f of capacity'
                 % (rec['governing'], rec['worst_util']))
            show_button(rec['governing'],
                        'governing rod %s of %s' % (
                            rec['governing'], self._group_display_name(gid)),
                        'Show me rod %s' % rec['governing'])
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
                show_button(rec['largest_force'],
                            'rod %s -- largest force in %s' % (
                                rec['largest_force'],
                                self._group_display_name(gid)),
                            'Show me rod %s (largest force)'
                            % rec['largest_force'])
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
        """Right-click a row: select it and open that group for editing.

        Selecting first matters: acting on whatever was selected BEFORE the
        right-click would act on the wrong group about half the time. The
        row's other actions are on the Actions menu.
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
        gid = self._current_group()
        if gid is False or gid is None:
            self._group_note_action('Ungrouped rods are not locked -- there '
                                    'is nothing to open.')
            return 'break'
        self._group_open(gid)
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
                                 unit_weight_kN_m3=self._unit_weight())
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

        # The properties of the section the group is built from. A group need
        # not be uniform, so with several in use this shows the one most of
        # its rods carry and says so.
        counts = {}
        for i in rods:
            if 0 <= i < len(self.members):
                p = self.members[i].get('profile') or ''
                counts[p] = counts.get(p, 0) + 1
        in_catalog = sorted(((n, p) for p, n in counts.items()
                             if sp.section_properties(p)), reverse=True)
        if in_catalog:
            n, name = in_catalog[0]
            title = ('Section properties -- %s' % name if len(counts) == 1
                     else 'Most used: %s (%d of %d rods)' % (name, n, len(rods)))
            table = self._section_table(win, name, title)
            table.pack(fill='x', padx=18, pady=(6, 0))

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
        if row and row['worst_rod'] is not None:
            tk.Button(btns, text='Show worst rod',
                      command=lambda: self._show_rod(
                          row['worst_rod'],
                          'worst rod %s of %s -- utilisation %.2f'
                          % (row['worst_rod'], self._group_display_name(gid),
                             row['worst_util']))
                      ).pack(side='left', expand=True, fill='x', padx=(6, 0))
        tk.Button(btns, text='Close', command=win.destroy
                  ).pack(side='left', padx=(6, 0))
        self._group_props_win = win
        return win

    # ── the grouped report ────────────────────────────────────────────────

    def _export_groups_pdf(self, only_picked=False, path=None):
        """One PDF: the groups summary, their shared joints, and a section
        per group (stereo_reports.export_groups_pdf). `only_picked` limits
        it to the group picked in the list -- with its subgroups, and with
        the joints it shares -- which is the "PDF of this group" action.
        """
        from tkinter import filedialog
        from apps.stereo import stereo_reports as sr
        if not self.members:
            messagebox.showinfo('Groups PDF', 'No model to export.')
            return None
        if not self.groups:
            messagebox.showinfo('Groups PDF',
                                'No groups yet. Make one from a selection '
                                'first -- a whole-model report is Export > PDF.')
            return None
        gids = None
        if only_picked:
            gid = self._current_group()
            if gid is False:
                messagebox.showinfo('Groups PDF', 'Pick a group first.')
                return None
            if gid is None:
                messagebox.showinfo(
                    'Groups PDF', 'Ungrouped is in the all-groups PDF; to '
                    'report part of it alone, select it and use Export > '
                    'PDF of Selection.')
                return None
            gids = {gid} | sgp.descendant_ids(self.groups, gid)
        if self.results is None:
            messagebox.showinfo(
                'Groups PDF',
                'Analyze first. A group\'s section is a view of the '
                'whole-model solve, and the joints sheet reports the force '
                'each group hands across -- both need the solve.')
            return None
        n_rigid = sum(1 for m in self.members if m.get('conn') == 'rigid')
        sheets = self._pdf_sheet_dialog('Groups PDF', self.results,
                                        self.member_checks, n_rigid)
        if sheets is None:
            return None
        if path is None:
            path = filedialog.asksaveasfilename(
                defaultextension='.pdf', filetypes=[('PDF document', '*.pdf')])
        if not path:
            return None
        try:
            contents = sr.export_groups_pdf(
                self.nodes, self.members, self._all_loads(),
                self._active_supports(), self.results, path, self.groups,
                checks=self.member_checks,
                meta={'grid_family': self._model_name()}, gids=gids,
                az_deg=self.azimuth, el_deg=self.elevation, groups=sheets,
                ortho_views='views' in sheets,
                unit_weight_kN_m3=self._unit_weight(),
                **self._pdf_view_kwargs())
        except Exception as exc:
            messagebox.showerror('Export failed', str(exc))
            return None
        lines = '\n'.join('  sheet %-3d %s' % (at, title)
                          for title, at in contents)
        messagebox.showinfo('Groups PDF', 'Saved to %s\n\n%s' % (path, lines))
        return contents

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
                                   unit_weight_kN_m3=self._unit_weight())
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

    # ── locking and edit mode ──────────────────────────────────────────────
    # The rules are stereo_groups' (see the block headed "locking"); what is
    # here is where each one is enforced. Every group is locked; the one bit
    # of state is which group, if any, is open for editing.

    def _editing_gid(self):
        """The open group's id, or None. A group that no longer exists (an
        undo, a delete, a regenerate) closes itself rather than leaving the
        window stuck in an edit mode with nothing to edit."""
        gid = getattr(self, '_group_editing', None)
        if gid is not None and sgp.find(self.groups, gid) is None:
            self._group_editing = None
            self._group_edit_stack = []
            gid = None
        return gid

    def _group_refuse(self, title, text, quiet=False):
        """Say no, in the status bar always and in a box when it was a button.

        A drag gets the status line only: a modal box in the middle of a
        mouse gesture takes the mouse with it.
        """
        self._set_status(text.split('\n')[0], 'error')
        self._group_note_action(text.split('\n')[0])
        if not quiet:
            messagebox.showinfo(title, text)
        return False

    def _clip_selection_to_edit(self):
        """While a group is open, nothing outside it can be selected."""
        gid = self._editing_gid()
        if gid is None:
            return
        rods = set(sgp.rods_of(self.groups, gid, deep=True))
        nodes = set(sgp.nodes_of_rods(self.members, rods))
        self.selected_nodes = {n for n in self.selected_nodes if n in nodes}
        self.selected_members = {i for i in self.selected_members if i in rods}
        if self.selected_member is not None and self.selected_member not in rods:
            self.selected_member = None

    def _group_edit_toggle(self, gid=False):
        """The Edit / Done button: open the picked group, or step out of the
        open one (back to the group it was opened from, if any)."""
        if self._editing_gid() is not None:
            return self._group_step_out()
        if gid is False:
            gid = self._current_group()
        if gid is False or gid is None:
            return self._group_refuse(
                'Edit group',
                'Pick a group to edit. Ungrouped rods are not locked, so there '
                'is nothing to open.')
        return self._group_open(gid)

    def _group_open(self, gid, nested=False):
        """Open `gid` for editing.

        `nested`: opened from INSIDE the group currently open (a subgroup
        right-clicked on the canvas), so Done comes back out to it -- the
        way into a nest of layers is the way back out. Otherwise this
        replaces whatever was open.
        """
        if gid is False or gid is None or sgp.find(self.groups, gid) is None:
            return self._group_refuse('Edit group', 'Pick a group to open.')
        stack = list(getattr(self, '_group_edit_stack', []) or [])
        if nested and self._editing_gid() is not None:
            stack.append(gid)
        else:
            stack = [gid]
        self._group_edit_stack = stack
        self._group_editing = gid
        self._clip_selection_to_edit()
        self._refresh_group_list(keep=gid)
        self._refresh_group_edit_controls()
        self._refresh_all()
        name = self._group_display_name(gid)
        subs = len(sgp.children(self.groups, gid))
        self._group_note_action(
            'Editing %s. Its own nodes and rods can be moved, added and '
            'deleted%s; everything else is locked until you press Done.'
            % (name, ('; its %d subgroup(s) stay closed -- right-click one '
                      'to open it' % subs) if subs else ''))
        self._set_status('Editing %s -- everything outside it is locked.'
                         % name, 'ok')
        return gid

    def _group_step_out(self):
        """Close the open group: back to the one it was opened from, or to
        the whole model."""
        gid = self._editing_gid()
        if gid is None:
            return None
        name = self._group_display_name(gid)
        stack = [g for g in (getattr(self, '_group_edit_stack', []) or [])
                 if sgp.find(self.groups, g) is not None]
        if stack and stack[-1] == gid:
            stack.pop()
        self._group_edit_stack = stack
        self._group_editing = stack[-1] if stack else None
        self._clip_selection_to_edit()
        self._refresh_group_list(keep=self._group_editing
                                 if self._group_editing is not None else gid)
        self._refresh_group_edit_controls()
        self._refresh_all()
        back = self._group_editing
        text = ('%s is locked again; back in %s.'
                % (name, self._group_display_name(back)) if back is not None
                else '%s is locked again.' % name)
        self._group_note_action(text)
        self._set_status(text, 'ok')
        return back

    def _group_canvas_open(self, ex, ey):
        """Right-click on the canvas without dragging.

        On a grouped rod: open the object it belongs to in the current
        context -- its top-level group, or, inside an open group, the
        subgroup it is part of. On empty canvas (or on a rod outside the
        open group): step out of the open group. Returns what it did.
        """
        if not self.groups:
            return None
        rod = self._select_member_at(ex, ey)
        editing = self._editing_gid()
        if rod is not None:
            owner = sgp.owner_of_rod(self.groups).get(rod)
            if owner is not None:
                obj = sgp.object_at(self.groups, owner, editing)
                if obj not in (None, sgp.OWN):
                    self._group_open(obj, nested=editing is not None)
                    return 'open'
                if obj == sgp.OWN:
                    return None         # already open: nothing to do
        if editing is not None:
            self._group_step_out()
            return 'out'
        return None

    def _group_tint_map(self):
        """{rod: tint} for Grouped mode, and [(name, tint)] for its key.

        By OBJECT in the current context -- the top-level groups, or, with
        a group open, its subgroups -- so what is tinted alike is exactly
        what a drag moves alike. Ungrouped rods (and the open group's own
        rods) get no tint at all.
        """
        editing = self._editing_gid()
        tops = [sgp.find(self.groups, g)
                for g in sgp.context_objects(self.groups, editing)]
        tint = {g['id']: GROUP_TINTS[k % len(GROUP_TINTS)]
                for k, g in enumerate(tops)}
        rods = {}
        for rod, gid in sgp.owner_of_rod(self.groups).items():
            t = tint.get(sgp.object_at(self.groups, gid, editing))
            if t:
                rods[rod] = t
        return rods, [(g['name'], tint[g['id']]) for g in tops]

    def _drop_groups(self):
        """Forget every group -- for a model replaced by one they do not
        describe (an import, a variant). Closes any edit in progress."""
        self.groups = []
        self._group_sel = None
        self._group_editing = None
        self._group_edit_stack = []
        self._refresh_group_list()
        self._refresh_group_edit_controls()

    def _group_path(self, gid):
        """[outermost, ..., gid] -- where the open group sits."""
        path, seen = [], set()
        g = sgp.find(self.groups, gid)
        while g is not None and g['id'] not in seen:
            seen.add(g['id'])
            path.append(g['id'])
            g = sgp.find(self.groups, g['parent']) if g['parent'] is not None \
                else None
        return path[::-1]

    def _refresh_group_edit_controls(self):
        btn = getattr(self, 'group_edit_btn', None)
        if btn is None:
            return
        gid = self._editing_gid()
        state = getattr(self, 'group_edit_state', None)
        if gid is None:
            btn.config(text='Open group', relief='raised')
            if state is not None:
                state.config(text='Nothing open -- every group is locked.',
                             fg=HINT_FG)
        else:
            btn.config(text='Done', relief='sunken')
            path = [self._group_display_name(g)
                    for g in self._group_path(gid)]
            if state is not None:
                state.config(text='Editing: ' + ' › '.join(path),
                             fg=EDIT_BANNER_COLOR)

    # ── moving a whole group ──────────────────────────────────────────────

    def _node_move_plan(self):
        if not self.groups:
            return {'nodes': sorted(self.selected_nodes), 'groups': [],
                    'conflicts': {}}
        return sgp.move_plan(self.groups, self.members, self.selected_nodes,
                             self._editing_gid())

    def _node_move_ids(self, quiet=True):
        """The nodes a drag of the selection may move, or [] if it may not."""
        plan = self._node_move_plan()
        if plan['conflicts']:
            self._refuse_move(plan, quiet=quiet)
            return []
        if plan['groups']:
            self._set_status(
                'Moving %s as a whole.' % ' + '.join(
                    self._group_display_name(g) for g in plan['groups']), 'ok')
        return plan['nodes']

    def _refuse_move(self, plan, quiet=True):
        joints = sgp.describe_conflicts(self.groups, plan['conflicts'])
        what = (' + '.join(self._group_display_name(g) for g in plan['groups'])
                or 'That node')
        return self._group_refuse(
            'Move group',
            '%s shares %s with another locked group, so moving it would move '
            'that group too.\n\nSelect a node of each group to move them '
            'together, or open the group with Edit group to detach it.'
            % (what, joints), quiet=quiet)

    def _group_move_by(self, gid, dx, dy, dz):
        """Translate a whole group -- subgroups included -- by (dx, dy, dz) m."""
        if gid is None or sgp.find(self.groups, gid) is None:
            return self._group_refuse('Move group', 'Pick a group to move.')
        editing = self._editing_gid()
        if editing is not None and gid != editing and \
                gid not in sgp.descendant_ids(self.groups, editing):
            return self._group_refuse(
                'Move group', '%s is outside the group being edited.'
                % self._group_display_name(gid))
        plan = sgp.group_move_plan(self.groups, self.members, gid, editing)
        if plan['conflicts']:
            return self._refuse_move(plan, quiet=False)
        if not plan['nodes'] or (dx, dy, dz) == (0.0, 0.0, 0.0):
            return False
        self._push_undo('move group')
        for n in plan['nodes']:
            x, y, z = self.nodes[n]
            self.nodes[n] = (x + dx, y + dy, z + dz)
        self.results = None
        self.member_checks = None
        self._refresh_all()
        self._group_note_action('%s moved by (%.3f, %.3f, %.3f) m.'
                                % (self._group_display_name(gid), dx, dy, dz))
        return True

    def _group_move_dialog(self):
        gid = self._current_group()
        if gid is False or gid is None:
            return self._group_refuse('Move group', 'Pick a group to move.')
        win = tk.Toplevel(self.root)
        win.title('Move %s' % self._group_display_name(gid))
        win.resizable(False, False)
        win.transient(self.root)
        tk.Label(win, text='Move %s as a whole' % self._group_display_name(gid),
                 font=('', 11, 'bold')).pack(padx=14, pady=(12, 2))
        tk.Label(win, text='Its subgroups come with it. Ungrouped rods at its '
                           'joints stretch to follow.', fg=HINT_FG,
                 font=('Helvetica', 8)).pack(padx=14)
        grid = tk.Frame(win)
        grid.pack(padx=14, pady=8)
        vals = {}
        for r, axis in enumerate(('dx', 'dy', 'dz')):
            tk.Label(grid, text='%s (m)' % axis).grid(row=r, column=0, sticky='w')
            vals[axis] = tk.DoubleVar(value=0.0)
            tk.Entry(grid, textvariable=vals[axis], width=10
                     ).grid(row=r, column=1, padx=(6, 0), pady=1)

        def go():
            try:
                d = [vals[k].get() for k in ('dx', 'dy', 'dz')]
            except (tk.TclError, ValueError):
                messagebox.showerror('Move group', 'Enter three numbers.')
                return
            if self._group_move_by(gid, *d):
                win.destroy()

        btns = tk.Frame(win)
        btns.pack(fill='x', padx=14, pady=(0, 12))
        tk.Button(btns, text='Move', font=('Helvetica', 9, 'bold'),
                  command=go).pack(side='left', expand=True, fill='x')
        tk.Button(btns, text='Cancel', command=win.destroy
                  ).pack(side='left', padx=(6, 0))
        self._group_move_win = win
        self._group_move_vals = vals
        self._group_move_go = go
        return win

    # ── the guards the other editing tools call ──────────────────────────

    def _guard_rebuild(self, title, nodes_after, members_after):
        """True when an operation's new lists leave every locked group as it
        was; otherwise say what it would have changed and return False."""
        if not self.groups:
            return True
        bad = sgp.geometry_violations(self.groups, self.nodes, self.members,
                                      nodes_after, members_after,
                                      self._editing_gid())
        if not bad:
            return True
        by = {}
        for gid, rod, _why in bad:
            by.setdefault(gid, []).append(rod)
        return self._group_refuse(
            title,
            'This would change rods of a locked group -- %s.\n\n'
            'Open that group with Edit group to change its parts.'
            % sgp.describe_rods(self.groups, by))

    def _carry_groups(self, members_before, members_after):
        """Keep every group on its own rods across a rebuild of the list."""
        if self.groups:
            sgp.remap_by_endpoints(self.groups, members_before, members_after)

    def _adopt_new_rods(self, first_new):
        """Rods made while a group is open join it; otherwise they are
        Ungrouped, which is what adding a rod to a locked group's node means
        -- the rod is new, the object it was drawn from is unchanged."""
        gid = self._editing_gid()
        if gid is not None and first_new < len(self.members):
            sgp.assign(self.groups, gid, range(first_new, len(self.members)))
        if hasattr(self, 'group_list'):
            self._refresh_group_list()

    def _guard_rods(self, title, rod_idx, verb='change'):
        """True if every one of these rods may be changed on its own now."""
        if not self.groups:
            return True
        editing = self._editing_gid()
        own = sgp.owner_of_rod(self.groups)
        by = {}
        for i in sorted(rod_idx):
            if sgp.rod_locked(self.groups, i, editing):
                by.setdefault(own.get(i), []).append(i)
        if not by:
            return True
        return self._group_refuse(
            title,
            'Cannot %s rods of a locked group -- %s.\n\nUse the Groups panel to '
            'set a section for the whole group, or open it with Edit group.'
            % (verb, sgp.describe_rods(self.groups, by)))

    def _guard_nodes(self, title, node_idx):
        """True if every one of these nodes may be moved on its own now."""
        if not self.groups:
            return True
        editing = self._editing_gid()
        bad = [n for n in sorted(node_idx)
               if sgp.node_locked(self.groups, self.members, n, editing)]
        if editing is not None:
            plan = sgp.move_plan(self.groups, self.members,
                                 set(node_idx) - set(bad), editing)
            if plan['conflicts']:
                return self._refuse_move(plan, quiet=False)
        if not bad:
            return True
        where = sorted({g for n in bad
                        for g in sgp.node_groups(self.groups, self.members, n)})
        return self._group_refuse(
            title,
            'Node%s %s belong%s to %s, which %s locked. Move the whole group '
            '(drag it, or Groups > Move group), or open it with Edit group.'
            % ('s' if len(bad) != 1 else '',
               ', '.join(str(n) for n in bad[:8]),
               's' if len(bad) == 1 else '',
               ', '.join(self._group_display_name(g) for g in where)
               or 'the outside of the group being edited',
               'is' if len(where) <= 1 else 'are'))
