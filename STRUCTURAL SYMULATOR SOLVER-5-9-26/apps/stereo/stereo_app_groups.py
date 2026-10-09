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

        # The current group in the view: pick inside it, dim the rest,
        # hide groups that are in the way (stereo_app_groupview).
        vis = tk.Frame(box, bg=BG)
        vis.pack(fill='x', padx=6, pady=(0, 2))
        tk.Button(vis, text='Hide / show', font=('Helvetica', 8),
                  command=self._group_toggle_hidden
                  ).pack(side='left', expand=True, fill='x')
        tk.Button(vis, text='Show all', font=('Helvetica', 8),
                  command=self._group_show_all
                  ).pack(side='left', expand=True, fill='x', padx=(3, 0))
        tk.Button(box, text='Leave out of analysis / put back',
                  font=('Helvetica', 8), command=self._group_toggle_excluded
                  ).pack(fill='x', padx=6, pady=(0, 2))
        tk.Button(box, text='Iterations: tags, lift plan, compare…',
                  font=('Helvetica', 8, 'bold'),
                  command=self._open_iterations
                  ).pack(fill='x', padx=6, pady=(0, 2))
        # "Pick inside group" and "Dim others" used to live here. Both now
        # follow the one thing already on screen -- whether you are inside a
        # group -- so there is nothing left to set. See _pick_filter.
        tk.Label(box, text='Click a rod to select its group. Double-click to '
                           'go inside it, Esc to come back out. Right-click '
                           'anything for what you can do with it.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W).pack(anchor='w', padx=6,
                                               pady=(0, 4))

        # The OTHER axis. Groups answer "what belongs to what"; roles answer
        # "what kind is this", which no tree can answer -- see stereo_roles.
        self._build_roles_panel(box)
        self._build_marks_panel(box)

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
        # Next to the other two group checks, because it answers the same
        # kind of question about the model as a whole -- and one the flat
        # model could not be asked at all until the scene graph was there
        # to compare groups by shape (see stereo_app_scene).
        # TWO rows, not three buttons in one: three asked for 311 px of a
        # 300 px panel, and Tk clips the overflow in silence rather than
        # complaining (which is what
        # test_no_panel_asks_for_more_width_than_the_panel_has is for).
        tk.Button(more, text='Repeated parts', font=('Helvetica', 8),
                  command=self._group_repeated_parts
                  ).pack(fill='x', padx=6, pady=(2, 0))
        scn = tk.Frame(more, bg=BG)
        scn.pack(fill='x', padx=6, pady=(3, 2))
        tk.Button(scn, text='Save scene…', font=('Helvetica', 8),
                  command=self._save_scene_file
                  ).pack(side='left', expand=True, fill='x')
        tk.Button(scn, text='Open scene…', font=('Helvetica', 8),
                  command=self._open_scene_file
                  ).pack(side='left', expand=True, fill='x', padx=(3, 0))
        rep = tk.Frame(more, bg=BG)
        rep.pack(fill='x', padx=6, pady=(2, 6))
        tk.Button(rep, text='PDF of groups…', font=('Helvetica', 8, 'bold'),
                  command=self._groups_pdf_custom
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
        # Two verbs, two names. "Delete" used to mean this one, which is why
        # nothing in the tab ever removed a group and its rods together.
        menu.add_command(label='Explode (keep the rods)',
                         command=self._group_explode)
        menu.add_command(label='Delete group and its rods',
                         command=self._group_delete_object)
        menu.add_separator()
        menu.add_command(label='Shared joints…',
                         command=self._group_shared_nodes)
        menu.add_command(label='Do the totals add up?',
                         command=self._group_reconcile)
        menu.add_separator()
        menu.add_command(label='Group the whole model by pieces…',
                         command=self._group_by_pieces)
        return menu

    def _group_by_pieces(self):
        """Replace the groups with one per piece of the model -- each truss,
        module and roof -- holding, as deep as the piece goes, its modules,
        its trusses, and every truss's top strip, bottom strip and diagonals
        (stereo_autogroup). For a file that arrives with every rod
        Ungrouped."""
        from apps.stereo import stereo_autogroup as ag
        if not self.members:
            self._group_note_action('Nothing to group: the model is empty.')
            return False
        if self.groups and not messagebox.askyesno(
                'Group by pieces',
                'This replaces the %d group(s) the model has now with one '
                'group per piece. Undo brings them back. Go ahead?'
                % len(self.groups)):
            return False
        groups = ag.auto_groups(self.nodes, self.members)
        self._push_undo('group by pieces')
        self._drop_groups()
        self.groups = groups
        self._refresh_group_list()
        plural = {'Truss': 'trusses', 'Module': 'modules', 'Roof': 'roofs'}
        kinds = {}
        for g in groups:
            if g['parent'] is None:
                kind = g['name'].split()[0]
                kinds[kind] = kinds.get(kind, 0) + 1
        self._group_note_action(
            'Grouped by pieces: %s -- %d groups in all.' % (
                ', '.join('%d %s' % (n, k.lower() if n == 1 else
                                     plural.get(k, k.lower() + 's'))
                          for k, n in kinds.items()), len(groups)))
        self._draw()
        return True

    # ── the list ───────────────────────────────────────────────────────────

    def _group_rows(self):
        """(label, gid) per row, indented by depth, Ungrouped last.

        `None` as the gid is the Ungrouped set, which is a row like any other
        so that it cannot be overlooked -- it is where the rods nobody has
        assigned still are.
        """
        rows = []
        editing = getattr(self, '_group_editing', None)
        # Piece marks when they are switched on: which groups are the same
        # part. Derived here rather than stored, so a mark can never outlive
        # the edit that made it wrong -- see stereo_marks.
        marks = (self._mark_of_group()
                 if hasattr(self, '_mark_of_group') else {})
        repeats = {}
        for gid, mark in marks.items():
            repeats[mark] = repeats.get(mark, 0) + 1
        for g, lvl in sgp.walk(self.groups):
            deep = len(sgp.rods_of(self.groups, g['id'], deep=True))
            own = len(g['members'])
            count = ('%d' % own) if deep == own else ('%d/%d' % (own, deep))
            mark = '✎ ' if g['id'] == editing else ''
            if g['id'] in (getattr(self, '_hidden_groups', None) or ()):
                mark += '◌ '
            if g.get('excluded'):
                mark += '⊘ '
            tag = ''
            if g.get('stage'):
                tag = '  {it %s · %s %s}' % (g.get('iteration') or '?',
                                             g['stage'],
                                             g.get('position') or '')
            # A component and a piece mark say nearly the same thing, and
            # showing both says it twice. The component is the stronger
            # claim -- someone DECLARED these one part, where a mark only
            # observes that they are the same shape -- so it wins, and the
            # mark is what helps you find the copies before you declare
            # them. Where the two disagree, the component window and the
            # sizing note are where the decision gets made.
            part = g.get('component')
            if part:
                n = sum(1 for o in self.groups if o.get('component') == part)
                tag = ('  ⬚%s%s' % (part, ' ×%d' % n if n > 1 else '')
                       ) + tag
            else:
                piece = marks.get(g['id'])
                if piece:
                    n = repeats.get(piece, 1)
                    tag = ('  %s%s' % (piece, ' ×%d' % n if n > 1 else '')
                           ) + tag
            rows.append(('%s%s%s  [%s]%s' % ('   ' * lvl, mark,
                                             self._group_display_name(g['id']),
                                             count, tag),
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
        """A row picked in the list is the current group in the view too
        -- the highlight, the bar and Pick inside group follow it."""
        gid = self._current_group()
        self._group_sel = None if gid is False else gid
        self._refresh_group_note()
        if hasattr(self, '_follow_current_group'):
            self._follow_current_group()
        if hasattr(self, 'canvas'):
            self._draw()

    def _group_rods(self, gid, deep=True):
        if gid is None:
            return sgp.ungrouped_rods(self.groups, len(self.members))
        return sgp.rods_of(self.groups, gid, deep=deep)

    def _group_display_name(self, gid):
        if gid is None:
            return sgp.UNGROUPED_NAME
        g = sgp.find(self.groups, gid)
        if not g:
            return '?'
        # The add-ons the group holds, by code -- unless its name already
        # says so (a group made from one add-on is named after it).
        from apps.stereo import stereo_addon_codes as sac
        codes = [c for c in sac.codes_of(self.members, g.get('members', ()))
                 if c not in g['name']]
        return g['name'] + (' · %s' % ', '.join(codes) if codes else '')

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
        # Selecting exactly one add-on's rods suggests its name.
        from apps.stereo import stereo_addon_codes as sac
        codes = sac.codes_of(self.members, idx)
        suggest = ''
        if len(codes) == 1 and set(idx) == set(sac.index(self.members)
                                               .get(codes[0], ())):
            suggest = sac.describe(codes[0])
        name = simpledialog.askstring('New group', 'Name for this group:',
                                      parent=self.root,
                                      initialvalue=suggest)
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
                                      initialvalue=sgp.find(self.groups,
                                                            gid)['name'],
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

    # ── a group as the thing you have selected ────────────────────────────
    #
    # Asked for in these words: "I should be able to select a complete group
    # by selecting a single rod that is inside that group", and "I should be
    # able to delete groups using the delete button".
    #
    # Both need one idea the tab did not have: a selection can BE a group,
    # rather than being some rods that happen to belong to one. Everything
    # below rests on that, and on its being DERIVED rather than stored --
    # see _selected_group_object.

    def _group_object_for_rod(self, rod):
        """The group a click on `rod` should select, or None for the rod alone.

        Read through `stereo_groups.object_at`, so the answer depends on the
        CONTEXT and not on how deep the rod sits: with nothing open it is the
        outermost group holding the rod; with a group open it is whichever of
        that group's own subgroups holds it, and None when the rod is one of
        the open group's own -- inside a group its own rods are the things
        you pick, which is what being inside it means.
        """
        if not self.groups:
            return None
        owner = sgp.owner_of_rod(self.groups).get(rod)
        if owner is None:
            return None                      # Ungrouped: the rod itself
        obj = sgp.object_at(self.groups, owner, self._editing_gid())
        return None if obj in (None, sgp.OWN) else obj

    def _selected_group_object(self):
        """The group this selection IS, as one object, or None.

        DERIVED, never stored. A flag would have to be cleared in every one
        of the dozen places a selection changes -- a lasso, a paste, an
        undo, a filter, the group list -- and the first one missed would
        delete a group the user had not selected. Comparing the sets cannot
        go stale, because there is nothing to keep in step.
        """
        if not self.groups or not self.selected_members or self.selected_nodes:
            return None
        sel = set(self.selected_members)
        for gid in sgp.context_objects(self.groups, self._editing_gid()):
            if set(sgp.rods_of(self.groups, gid, deep=True)) == sel:
                return gid
        return None

    def _group_select_object(self, gid, additive=False):
        """Select every rod of `gid` -- the group as one object."""
        rods = set(sgp.rods_of(self.groups, gid, deep=True))
        hidden = self._hidden_rods()
        if hidden:
            rods -= hidden
        if not rods:
            return False
        self.selected_members = (self.selected_members | rods) if additive \
            else rods
        self.selected_nodes = set()
        self.selected_member = None
        self._sync_selection_fields()
        return True

    def _group_delete_object(self, gid=None):
        """DELETE: the group, its subgroups, and all of their rods.

        The other verb -- `_group_explode`, which the panel used to call
        "Delete" -- takes the container away and leaves the rods. Two
        different things happening to a model deserve two different words,
        and calling the gentler one "Delete" is why pressing Delete never
        did what anyone expected.
        """
        gid = self._current_group() if gid is None else gid
        if gid is False or gid is None:
            return False
        name = self._group_display_name(gid)
        doomed = {gid} | sgp.descendant_ids(self.groups, gid)
        rods = set(sgp.rods_of(self.groups, gid, deep=True))
        if not messagebox.askyesno(
                'Delete group',
                'Delete %s and the %d rod(s) in it?\n\n'
                'The rods go too. To keep them and lose only the grouping, '
                'use Explode instead.' % (name, len(rods))):
            return False
        self._push_undo('delete group')
        # The group records go FIRST, for two reasons. Those rods are then
        # Ungrouped, so the lock guard does not refuse the very deletion the
        # user asked for; and the rods then travel through the model's own
        # deletion, which is the one place that remaps supports, loads,
        # _support_candidates and _load_nodes. There is no second copy of
        # that logic here, and so no second copy to drift.
        for g in list(self.groups):
            if g['id'] in doomed:
                self.groups.remove(g)
        self.selected_nodes = set()
        self.selected_members = set(rods)
        self.selected_member = None
        self._on_delete_selection(push_undo=False)
        self._group_note_action('%s deleted, with its %d rod(s).'
                                % (name, len(rods)))
        return True

    def _group_explode(self):
        """EXPLODE: the container goes, the rods stay. Was called "Delete"."""
        return self._group_delete()

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
        # A component is one drawing, so a section set on one copy is set
        # on all of them. _sizing_rods is the same list for a plain group,
        # which is why it is not conditional here: an envelope nobody has
        # to remember to ask for is one that cannot be forgotten.
        reach = self._sizing_rods(gid, rods)
        note = self._component_sizing_note(gid, rods)
        self._push_undo('section for group')
        n = sk.apply_recommendation(self.members, reach, name)
        self.results = None
        self.member_checks = None
        self._refresh_all()
        self._group_note_action(
            '%s: %d rod(s) set to %s. Analyze again -- stiffening a branch '
            'changes how the load shares out.%s'
            % (self._group_display_name(gid), n, name,
               ' ' + note if note else ''))

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
        # Sized over every copy of the part, not over the copy in front of
        # you: a component is fabricated once, so the section has to carry
        # the worst of them. For a plain group this is the same list.
        rods = self._sizing_rods(gid, rods)
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
        note = self._component_sizing_note(gid)
        if note:
            tk.Label(win, text=note, fg=HINT_FG, justify='left',
                     wraplength=420, font=('Helvetica', 8, 'bold')
                     ).pack(anchor='w', padx=16, pady=(0, 4))

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
            # `rods` already covers every copy -- _group_recommend widened
            # it before sizing, so what was sized is what is applied.
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
                                        self.member_checks, n_rigid,
                                        members=self.members)
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

    # ── the groups PDF, the way the user wants it ─────────────────────────

    def _groups_pdf_items(self):
        """The rows of the Groups PDF dialog: every group (and Ungrouped,
        when it has rods) as {'gid', 'title', 'sheets', 'on'}, in the order
        last used -- what was chosen before is kept for the groups still
        there, and new groups join at the end, ticked."""
        known = []
        for g, lvl in sgp.walk(self.groups):
            known.append((g['id'], g['name']))
        if sgp.ungrouped_rods(self.groups, len(self.members)):
            known.append((None, sgp.UNGROUPED_NAME))
        ids = {gid for gid, _n in known}
        names = dict(known)
        prev = (getattr(self, '_groups_pdf_cfg', None) or {}).get('items', [])
        out, seen = [], set()
        for it in prev:
            gid = it.get('gid')
            if gid in ids and gid not in seen:
                out.append(dict(it))
                seen.add(gid)
        for gid, name in known:
            if gid not in seen:
                out.append({'gid': gid, 'title': name, 'sheets': None,
                            'on': True})
        for it in out:
            if not (it.get('title') or '').strip():
                it['title'] = names.get(it['gid'], '?')
        return out

    def _groups_pdf_dialog(self):
        """Which groups go in the PDF, in what order, under what titles,
        with which sheets each, and one document or a PDF per group.
        Returns the choice -- {'items': [...], 'sheets': default set,
        'mode': 'one' | 'each'} -- or None if cancelled."""
        from apps.stereo import stereo_reports as sr
        prev = getattr(self, '_groups_pdf_cfg', None) or {}
        items = self._groups_pdf_items()
        default = set(prev.get('sheets') or (
            sr.PDF_SHEET_GROUPS if self._pdf_groups is None
            else self._pdf_groups))
        labels = {k: lbl for k, lbl, _b in self.PDF_GROUP_LABELS}

        win = tk.Toplevel(self.root)
        win.title('Groups PDF')
        win.transient(self.root)
        tk.Label(win, text='Groups PDF', font=('', 12, 'bold')).pack(
            pady=(12, 2))
        tk.Label(win, text='Tick the groups to include, give each the title '
                           'it should carry, set its sheets, and put them '
                           'in order. The summary and the shared joints '
                           'come first.', fg='grey', wraplength=560,
                 justify='left').pack(padx=16)

        rows_box = tk.Frame(win)
        rows_box.pack(fill='x', padx=16, pady=(8, 4))
        state = {'items': items}
        on_vars, title_vars = [], []

        def sheets_text(it):
            sh = it.get('sheets')
            return 'default sheets' if sh is None else (
                ', '.join(labels.get(k, k) for k in sr.PDF_SHEET_GROUPS
                          if k in sh) or 'general view only')

        def pick_sheets(k):
            it = state['items'][k]
            got = self._groups_pdf_sheet_picker(
                it['title'], it.get('sheets') or default)
            if got is not None:
                it['sheets'] = None if got == default else got
                build()

        def move(k, d):
            sync()
            lst = state['items']
            j = k + d
            if 0 <= j < len(lst):
                lst[k], lst[j] = lst[j], lst[k]
                build()

        def sync():
            for it, ov, tv in zip(state['items'], on_vars, title_vars):
                it['on'] = bool(ov.get())
                it['title'] = tv.get()

        def build():
            for w in rows_box.winfo_children():
                w.destroy()
            on_vars.clear()
            title_vars.clear()
            for k, it in enumerate(state['items']):
                ov = tk.BooleanVar(master=win, value=it.get('on', True))
                tv = tk.StringVar(master=win, value=it.get('title', ''))
                on_vars.append(ov)
                title_vars.append(tv)
                tk.Checkbutton(rows_box, variable=ov).grid(row=k, column=0)
                tk.Entry(rows_box, textvariable=tv, width=26).grid(
                    row=k, column=1, sticky='w', padx=(0, 6))
                tk.Button(rows_box, text='Sheets…', font=('Helvetica', 8),
                          command=lambda k=k: (sync(), pick_sheets(k))
                          ).grid(row=k, column=2)
                tk.Label(rows_box, text=sheets_text(it), fg='grey',
                         font=('Helvetica', 8), width=34, anchor='w'
                         ).grid(row=k, column=3, sticky='w', padx=4)
                tk.Button(rows_box, text='↑', width=2,
                          command=lambda k=k: move(k, -1)
                          ).grid(row=k, column=4)
                tk.Button(rows_box, text='↓', width=2,
                          command=lambda k=k: move(k, +1)
                          ).grid(row=k, column=5)
        build()

        dbox = tk.LabelFrame(win, text='Default sheets (any group set to '
                                       '"default sheets")')
        dbox.pack(fill='x', padx=16, pady=(6, 0))
        dvars = {}
        for k, (key, lbl, _b) in enumerate(self.PDF_GROUP_LABELS):
            v = tk.BooleanVar(master=win, value=key in default)
            dvars[key] = v
            tk.Checkbutton(dbox, text=lbl, variable=v).grid(
                row=k // 3, column=k % 3, sticky='w', padx=4)

        mode = tk.StringVar(master=win, value=prev.get('mode', 'one'))
        mbox = tk.Frame(win)
        mbox.pack(fill='x', padx=16, pady=(8, 0))
        tk.Radiobutton(mbox, text='One document', variable=mode,
                       value='one').pack(side='left')
        tk.Radiobutton(mbox, text='One PDF per group', variable=mode,
                       value='each').pack(side='left', padx=(12, 0))

        out = {'cfg': None}

        def ok():
            sync()
            out['cfg'] = {'items': [dict(it) for it in state['items']],
                          'sheets': {k for k, v in dvars.items() if v.get()},
                          'mode': mode.get()}
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
            try:
                if win.winfo_exists():
                    win.grab_release()
                    win.destroy()
            except tk.TclError:
                pass
        return out['cfg']

    def _groups_pdf_sheet_picker(self, title, current):
        """The sheet groups one group's section carries; None if
        cancelled."""
        win = tk.Toplevel(self.root)
        win.title('Sheets for %s' % title)
        win.transient(self.root)
        vs = {}
        for key, lbl, blurb in self.PDF_GROUP_LABELS:
            v = tk.BooleanVar(master=win, value=key in current)
            vs[key] = v
            tk.Checkbutton(win, text=lbl, variable=v, anchor='w').pack(
                fill='x', padx=14)
        out = {'s': None}

        def ok():
            out['s'] = {k for k, v in vs.items() if v.get()}
            win.destroy()
        tk.Button(win, text='OK', command=ok, width=10).pack(pady=10)
        win.grab_set()
        try:
            self.root.wait_window(win)
        finally:
            try:
                if win.winfo_exists():
                    win.grab_release()
                    win.destroy()
            except tk.TclError:
                pass
        return out['s']

    def _groups_pdf_custom(self, cfg=None, path=None):
        """The Groups PDF as chosen in its dialog (or as `cfg` says):
        the ticked groups, in their order, under their titles, each with
        its own sheets -- as one document, or one PDF per group. Returns
        [(path, contents)] for what was written, or None."""
        from tkinter import filedialog
        import os
        import re
        from apps.stereo import stereo_reports as sr
        if not self.members:
            messagebox.showinfo('Groups PDF', 'No model to export.')
            return None
        if not self.groups:
            messagebox.showinfo('Groups PDF',
                                'No groups yet. Make one from a selection '
                                'first -- a whole-model report is Export > PDF.')
            return None
        if self.results is None:
            messagebox.showinfo(
                'Groups PDF',
                'Analyze first. A group\'s section is a view of the '
                'whole-model solve, and the joints sheet reports the force '
                'each group hands across -- both need the solve.')
            return None
        if cfg is None:
            cfg = self._groups_pdf_dialog()
            if cfg is None:
                return None
        self._groups_pdf_cfg = cfg
        items = [it for it in cfg['items'] if it.get('on')]
        if not items:
            messagebox.showinfo('Groups PDF', 'No group is ticked.')
            return None
        default = set(cfg.get('sheets') or ())
        plan = [{'gid': it['gid'], 'title': it.get('title'),
                 'sheets': it.get('sheets')} for it in items]
        if path is None:
            path = filedialog.asksaveasfilename(
                defaultextension='.pdf', filetypes=[('PDF document', '*.pdf')])
        if not path:
            return None
        kw = dict(checks=self.member_checks,
                  meta={'grid_family': self._model_name(),
                        'crane_lifts': self._crane_meta()},
                  az_deg=self.azimuth, el_deg=self.elevation, groups=default,
                  ortho_views='views' in default,
                  unit_weight_kN_m3=self._unit_weight(),
                  **self._pdf_view_kwargs())
        jobs = []
        if cfg.get('mode') == 'each':
            stem, ext = os.path.splitext(path)
            used = set()
            for it in plan:
                safe = re.sub(r'[^A-Za-z0-9._-]+', '_',
                              it['title'] or 'group').strip('_') or 'group'
                name, n = safe, 2
                while name in used:
                    name, n = '%s_%d' % (safe, n), n + 1
                used.add(name)
                jobs.append(('%s_%s%s' % (stem, name, ext or '.pdf'), [it]))
        else:
            jobs.append((path, plan))
        written = []
        try:
            for out_path, part in jobs:
                contents = sr.export_groups_pdf(
                    self.nodes, self.members, self._all_loads(),
                    self._active_supports(), self.results, out_path,
                    self.groups, plan=part, **kw)
                written.append((out_path, contents))
        except Exception as exc:
            messagebox.showerror('Export failed', str(exc))
            return None
        messagebox.showinfo(
            'Groups PDF', 'Saved %d file(s):\n%s'
            % (len(written), '\n'.join(p for p, _c in written)))
        return written

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
        self._hidden_groups = set()
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
            # The button is only DONE now. Going in is a double-click or the
            # right-click menu, both of them on the object itself, so a
            # button that merely repeated them was a fourth way to do one
            # thing. It appears when it has something to do.
            btn.pack_forget()
            if state is not None:
                state.config(text='Nothing open -- every group is locked. '
                                  'Double-click a rod to go inside its group.',
                             fg=HINT_FG)
        else:
            if not btn.winfo_ismapped():
                btn.pack(side='right')
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
        # A copy of an add-on is another add-on: its rods get a code of
        # their own (C1 copied is C2), so no code names two things.
        from apps.stereo import stereo_addon_codes as sac
        sac.renumber_copies(self.members, range(first_new, len(self.members)),
                            getattr(self, 'panels', ()))
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
