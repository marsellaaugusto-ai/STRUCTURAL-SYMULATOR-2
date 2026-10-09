"""Seeing and selecting groups in the 3D view.

What group am I working on? Before this the answer was a highlighted row
in a list on a panel that is often closed. Now:

  * the CURRENT GROUP is one piece of state, the row picked in the Groups
    list (self._group_sel): picking a row, double-clicking a rod and
    clicking a name on the group bar all set it, and each shows in the
    other two places;
  * the GROUP BAR over the view says, in every mode, which group is
    current and where it sits (Module 1 › Truss 3), what is selected, and
    what the crane's Lift would take -- clicking a name in it steps back up
    to that level;
  * the view highlights the current group (a halo and a name tag), and can
    dim everything else;
  * group names can be drawn on the model (Display: Group #), and the
    group colours switched on from Display too;
  * hovering a rod names it, its group and its section on the status line;
  * double-clicking a rod picks its group, and double-clicking again goes
    up a level;
  * with "Pick inside group" on, clicking and lassoing joints stays inside
    the current group -- picking the joints a module is lifted by no longer
    catches the neighbour's;
  * a group can be hidden.

Picking joints never changes the current group.
"""
import tkinter as tk

from common import declutter_text

from apps.stereo import stereo_groups as sgp
from apps.stereo import stereo_lift as slift

GROUP_HALO_COLOR = '#ffcc33'
GROUP_TAG_FG = '#6b4a00'
GROUP_TAG_BG = '#fff4cc'
GROUP_LABEL_FG = '#3b4a5a'
GROUP_BAR_BG = '#eef2f6'
GROUP_BAR_LINK = '#1a6bbd'
GROUP_LABEL_DEPTHS = ('top level', 'one level down', 'all')
# Up to this many group names are always drawn (nudged apart if they
# overlap); more are hidden while crowded, like node and rod numbers.
GROUP_LABELS_ALWAYS = 12


class StereoGroupViewMixin:

    # ── state ──────────────────────────────────────────────────────────────

    def _init_group_view_state(self):
        # `group_dim_others` and `pick_inside_group` were here. Both asked
        # the user to manage, by checkbox, something the tab already knows:
        # whether they are inside a group. Dimming and pick-restriction now
        # follow that, so there is nothing to set and nothing to forget --
        # see _pick_filter and the dim block in stereo_app_render.
        self.show_group_labels = tk.BooleanVar(value=False)
        self.group_label_depth = tk.StringVar(value=GROUP_LABEL_DEPTHS[0])
        self._hidden_groups = set()
        self._dbl_click = False

    def _cur_gid(self):
        """The current group's id, or None. A row that no longer names a
        group (an undo, a delete) is not current any more."""
        gid = getattr(self, '_group_sel', None)
        if gid is None or not getattr(self, 'groups', None):
            return None
        if sgp.find(self.groups, gid) is None:
            self._group_sel = None
            return None
        return gid

    def _cur_rods(self):
        gid = self._cur_gid()
        return set(sgp.rods_of(self.groups, gid, deep=True)) \
            if gid is not None else set()

    def _set_current_group(self, gid, say=True):
        """Make `gid` (or None) the current group: the list row, the bar,
        the highlight -- one state, shown in all three."""
        if gid is not None and sgp.find(self.groups, gid) is None:
            gid = None
        self._group_sel = gid
        lst = getattr(self, 'group_list', None)
        if lst is not None:
            ids = getattr(self, '_group_row_ids', [])
            lst.selection_clear(0, 'end')
            if gid is not None and gid in ids:
                i = ids.index(gid)
                lst.selection_set(i)
                lst.see(i)
        self._refresh_group_note()
        if hasattr(self, '_follow_current_group'):
            self._follow_current_group()
        if say:
            if gid is None:
                self._set_status('No current group.', 'idle')
            else:
                self._set_status('Current group: %s (%d rods).' % (
                    ' › '.join(self._group_display_name(g)
                               for g in self._group_path(gid)),
                    len(self._cur_rods())), 'ok')
        self._draw()
        return gid

    # ── what is hidden, what can be picked ─────────────────────────────────

    def _hidden_rods(self):
        """Everything hidden, from both axes.

        A group hides a BRANCH; a role or a rule hides a KIND, wherever it
        sits. The two are unioned here, which is the only place that has to
        know there are two -- every caller just asks what is hidden.
        """
        hidden = set()
        for gid in list(getattr(self, '_hidden_groups', ()) or ()):
            if sgp.find(self.groups, gid) is None:
                self._hidden_groups.discard(gid)
                continue
            hidden.update(sgp.rods_of(self.groups, gid, deep=True))
        by_role = getattr(self, '_hidden_by_role', None)
        if by_role is not None:
            hidden.update(by_role())
        return hidden

    def _hidden_nodes(self, hidden_rods=None):
        """Nodes only hidden rods reach -- hidden with them."""
        hidden_rods = self._hidden_rods() if hidden_rods is None \
            else hidden_rods
        if not hidden_rods:
            return set()
        shown = {n for j, m in enumerate(self.members) if j not in hidden_rods
                 for n in (m['a'], m['b'])}
        return {n for j in hidden_rods for n in
                (self.members[j]['a'], self.members[j]['b'])} - shown

    def _pick_filter(self):
        """(allowed nodes or None, allowed rods or None) for a click or lasso.

        Hidden groups are never picked, and while a group is OPEN only its
        own contents are.

        It used to be a checkbox ("Pick inside group") over whichever group
        was highlighted in the list. That made merely LOOKING at a group in
        the panel change what the canvas would let you touch, which is a
        rule you cannot see -- and it is why the panel needed a checkbox to
        turn it off again. Now the restriction follows the one thing that is
        already visible: whether you have gone inside a group. Outside, the
        whole model is pickable; inside, its contents are. Nothing to set.
        """
        hidden = self._hidden_rods()
        nodes = rods = None
        if hidden:
            rods = set(range(len(self.members))) - hidden
            nodes = set(range(len(self.nodes))) - self._hidden_nodes(hidden)
        editing = self._editing_gid()
        if editing is not None:
            mine = set(sgp.rods_of(self.groups, editing, deep=True))
            mine_nodes = set(sgp.nodes_of_rods(self.members, mine))
            rods = mine if rods is None else rods & mine
            nodes = mine_nodes if nodes is None else nodes & mine_nodes
        return nodes, rods

    # ── the group bar ──────────────────────────────────────────────────────

    def _build_group_bar(self, parent):
        bar = tk.Frame(parent, bg=GROUP_BAR_BG, bd=0)
        bar.pack(side='top', fill='x')
        self._group_bar = bar
        self._group_bar_items = []
        self._refresh_group_bar()

    def _group_bar_text(self):
        """The bar's parts: [(text, gid or False)] -- False for plain text,
        None for the whole model. Kept apart from the widgets so it can be
        read (and tested) on its own."""
        parts = [('Group:', False), ('Model', None)]
        gid = self._cur_gid()
        if gid is not None:
            for g in self._group_path(gid):
                parts += [('›', False), (self._group_display_name(g), g)]
        rods = self._cur_rods()
        if gid is not None:
            parts.append(('(%d rods)' % len(rods), False))
        sel = []
        if self.selected_nodes:
            sel.append('%d node%s' % (len(self.selected_nodes),
                                      '' if len(self.selected_nodes) == 1
                                      else 's'))
        if self.selected_members:
            sel.append('%d rod%s' % (len(self.selected_members),
                                     '' if len(self.selected_members) == 1
                                     else 's'))
        parts.append(('· Selected: %s' % (', '.join(sel) or 'nothing'),
                      False))
        lift = self._lift_takes_text()
        if lift:
            parts.append(('· Lift takes: %s' % lift, False))
        if getattr(self, '_hidden_groups', None):
            parts.append(('· %d group(s) hidden' % len(self._hidden_groups),
                          False))
        return parts

    def _lift_takes_text(self):
        """What "Lift the selected nodes" would lift, now."""
        target = getattr(self, 'crane_lift_target', None)
        if target is None or not self.members:
            return ''
        gids = getattr(self, '_crane_lift_gids', None) or {}
        gid = gids.get(target.get())
        if gid is not None and sgp.find(self.groups, gid):
            return '%s (%d rods)' % (
                self._group_display_name(gid),
                len(sgp.rods_of(self.groups, gid, deep=True)))
        if not self.selected_nodes:
            return 'the piece under the hook'
        rods = slift.connected_piece(self.members, sorted(self.selected_nodes))
        return 'the piece under the hook (%d rods)' % len(rods)

    def _refresh_group_bar(self):
        bar = getattr(self, '_group_bar', None)
        if bar is None:
            return
        try:
            if not bar.winfo_exists():
                return
        except tk.TclError:
            return
        parts = self._group_bar_text()
        if parts == getattr(self, '_group_bar_parts', None):
            return
        self._group_bar_parts = parts
        for w in self._group_bar_items:
            w.destroy()
        self._group_bar_items = []
        for text, gid in parts:
            link = gid is not False
            lbl = tk.Label(bar, text=text, bg=GROUP_BAR_BG,
                           fg=GROUP_BAR_LINK if link else '#1d2328',
                           font=('Helvetica', 9, 'underline' if link
                                 else 'normal'),
                           cursor='hand2' if link else '')
            lbl.pack(side='left', padx=(4 if text != '›' else 1, 0), pady=2)
            if link:
                lbl.bind('<Button-1>',
                         lambda _e, g=gid: self._group_bar_goto(g))
            self._group_bar_items.append(lbl)

    def _group_bar_goto(self, gid):
        """A name on the bar: step back up to that level. An open group the
        target is outside of is closed on the way."""
        while True:
            editing = self._editing_gid()
            if editing is None:
                break
            if gid is not None and (editing == gid
                                    or gid not in self._group_path(editing)):
                break
            self._group_step_out()
        return self._set_current_group(gid)

    # ── double-click: a rod's group, then up a level ───────────────────────

    def _on_canvas_double(self, event):
        """Double-click a rod: GO INSIDE the group it belongs to.

        It used to only move a highlight in the side panel, which is why
        nothing you did on the canvas ever changed where you were standing.
        Esc comes back out, and the breadcrumb says where you are.
        """
        self._dbl_click = True
        gid = self._group_double_click(event.x, event.y)
        if gid is not None and gid is not False:
            inside = self._editing_gid() is not None
            self._group_open(gid, nested=inside)
        return gid

    def _group_double_click(self, ex, ey):
        """Double-click a rod: its group (the innermost one). Again, on a
        rod of the current group: the group above it. On empty canvas: up
        a level. Returns the new current group."""
        hidden = self._hidden_rods()
        rod = self._select_member_at(ex, ey, allowed=(
            set(range(len(self.members))) - hidden) if hidden else None)
        cur = self._cur_gid()
        if rod is None:
            if cur is None:
                return None
            g = sgp.find(self.groups, cur)
            return self._set_current_group(g['parent'] if g else None)
        owner = sgp.owner_of_rod(self.groups).get(rod) if self.groups \
            else None
        if owner is None:
            self._set_status('Rod %d is not in any group.' % rod, 'idle')
            return self._set_current_group(None, say=False)
        chain = self._group_path(owner)
        if cur in chain:
            k = chain.index(cur)
            new = chain[k - 1] if k > 0 else cur
            if k == 0:
                self._set_current_group(new, say=False)
                self._set_status('%s is a top-level group.'
                                 % self._group_display_name(new), 'idle')
                return new
            return self._set_current_group(new)
        return self._set_current_group(owner)

    # ── hover: what is under the pointer ───────────────────────────────────

    def _rod_hover_text(self, rod):
        m = self.members[rod]
        bits = ['Rod %d' % rod]
        if self.groups:
            owner = sgp.owner_of_rod(self.groups).get(rod)
            if owner is not None:
                path = self._group_path(owner)
                leaf = self._group_display_name(owner)
                bits.append(leaf if len(path) < 2 else '%s (%s)' % (
                    leaf, self._group_display_name(path[0])))
            else:
                bits.append(sgp.UNGROUPED_NAME)
        if m.get('role') == 'crane_cable':
            bits.append('crane sling %s' % (m.get('addon') or ''))
        bits.append(m.get('profile') or 'unnamed section')
        chk = (self.member_checks[rod] if self.member_checks
               and rod < len(self.member_checks) else None)
        if chk and chk.get('checked') and chk.get('util') is not None:
            bits.append('u %.2f' % chk['util'])
        return ' · '.join(bits)

    def _node_hover_group(self, node):
        if not self.groups:
            return ''
        own = sgp.owner_of_rod(self.groups)
        names = []
        for j, m in enumerate(self.members):
            if node in (m['a'], m['b']) and own.get(j) is not None:
                n = self._group_display_name(own[j])
                if n not in names:
                    names.append(n)
        return (' · ' + ', '.join(names[:3])
                + (' …' if len(names) > 3 else '')) if names else ''

    # ── drawing ────────────────────────────────────────────────────────────

    def _group_label_ids(self):
        """The groups whose names Group # draws, by the depth chosen."""
        depth = self.group_label_depth.get()
        out = []
        for g, lvl in sgp.walk(self.groups):
            if depth == GROUP_LABEL_DEPTHS[0] and lvl > 0:
                continue
            if depth == GROUP_LABEL_DEPTHS[1] and lvl > 1:
                continue
            out.append(g['id'])
        return out

    def _group_anchor(self, gid, proj, to_screen):
        """Where a group's name goes: the screen centre of its nodes."""
        nodes = sgp.nodes_of_rods(self.members,
                                  sgp.rods_of(self.groups, gid, deep=True))
        pts = [to_screen(proj[n][0], proj[n][1]) for n in nodes
               if n < len(proj)]
        if not pts:
            return None
        return (sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts))

    def _draw_group_overlays(self, c, proj, to_screen):
        """The current group's name tag and the Group # labels -- drawn on
        top of the model."""
        if not self.groups:
            return
        hidden = getattr(self, '_hidden_groups', set())
        if self.show_group_labels.get():
            ids = [g for g in self._group_label_ids() if g not in hidden]
            spots = [(g, self._group_anchor(g, proj, to_screen)) for g in ids]
            spots = [(g, p) for g, p in spots if p is not None]
            # A few names are nudged apart; many piled up are hidden, as
            # node and rod numbers are -- zoom in, or untick Hide # when
            # crowded.
            few = len(spots) <= GROUP_LABELS_ALWAYS
            if few or not self._labels_crowded([p for _g, p in spots]):
                items = [c.create_text(x, y, text=self._group_display_name(g),
                                       fill=GROUP_LABEL_FG,
                                       font=('Helvetica', 8, 'bold'),
                                       tags='group_label')
                         for g, (x, y) in spots]
                if few:
                    declutter_text(c, items)
        gid = self._cur_gid()
        if gid is not None and gid not in hidden:
            p = self._group_anchor(gid, proj, to_screen)
            if p is not None:
                x, y = p
                t = c.create_text(x, y - 14, text=self._group_display_name(gid),
                                  fill=GROUP_TAG_FG,
                                  font=('Helvetica', 9, 'bold'),
                                  tags='group_tag')
                x0, y0, x1, y1 = c.bbox(t)
                r = c.create_rectangle(x0 - 4, y0 - 2, x1 + 4, y1 + 2,
                                       fill=GROUP_TAG_BG, outline=GROUP_HALO_COLOR,
                                       tags='group_tag')
                c.tag_lower(r, t)

    # ── hide / show ────────────────────────────────────────────────────────

    def _group_toggle_hidden(self, gid=False):
        if gid is False:
            gid = self._current_group() if hasattr(self, 'group_list') \
                else self._cur_gid()
        if gid is False or gid is None:
            return self._group_refuse('Hide group', 'Pick a group to hide '
                                                    'or show.')
        if gid in self._hidden_groups:
            self._hidden_groups.discard(gid)
            what = 'shown'
        else:
            self._hidden_groups.add(gid)
            what = 'hidden -- it is still in the model and the analysis'
        self._refresh_group_list(keep=gid)
        self._set_status('%s %s.' % (self._group_display_name(gid), what),
                         'ok')
        self._draw()
        return gid in self._hidden_groups

    def _group_show_all(self):
        n = len(self._hidden_groups)
        self._hidden_groups = set()
        self._refresh_group_list()
        self._set_status('%d group(s) shown again.' % n if n
                         else 'No group is hidden.', 'ok')
        self._draw()

    # ── F1: a group left out of the analysis ──────────────────────────────

    def _excluded_rods(self):
        """Rods of every group marked "leave out of the analysis" (its
        subgroups' too)."""
        out = set()
        for g in getattr(self, 'groups', None) or []:
            if g.get('excluded'):
                out.update(sgp.rods_of(self.groups, g['id'], deep=True))
        return out

    def _group_toggle_excluded(self, gid=False):
        """Leave the picked group out of the analysis, or put it back. The
        rods stay in the model, the drawings and the workbook; the solve
        carries on without them (and without nodes only they reach)."""
        if gid is False:
            gid = self._current_group() if hasattr(self, 'group_list') \
                else self._cur_gid()
        if gid is False or gid is None or sgp.find(self.groups, gid) is None:
            return self._group_refuse('Leave out of analysis',
                                      'Pick a group to leave out of the '
                                      'analysis, or to put back.')
        self._push_undo('leave group out of analysis')
        g = sgp.find(self.groups, gid)
        if g.get('excluded'):
            g.pop('excluded', None)
            what = 'is back in the analysis'
        else:
            g['excluded'] = True
            what = 'is left out of the analysis -- still in the model'
        self.results = None
        self.member_checks = None
        self._refresh_group_list(keep=gid)
        self._refresh_all()
        self._set_status('%s %s.' % (self._group_display_name(gid), what),
                         'ok')
        return bool(g.get('excluded'))

    # ── F2: pieces that stand on nothing ──────────────────────────────────

    def _floating_pieces(self, skip=None):
        from apps.stereo import stereo_floating as sf
        skip = self._excluded_rods() if skip is None else skip
        return sf.floating_pieces(self.members, self._active_supports(),
                                  skip=skip)

    def _piece_groups(self, rods):
        """(top-level group ids the piece's rods are in, ungrouped count)."""
        own = sgp.owner_of_rod(self.groups) if self.groups else {}
        tops, loose = [], 0
        for j in rods:
            g = own.get(j)
            if g is None:
                loose += 1
                continue
            top = self._group_path(g)[0]
            if top not in tops:
                tops.append(top)
        return tops, loose

    def _piece_name(self, rods):
        tops, loose = self._piece_groups(rods)
        names = [self._group_display_name(g) for g in tops[:4]]
        if len(tops) > 4:
            names.append('+%d more' % (len(tops) - 4))
        if loose:
            names.append('%d ungrouped rod%s' % (loose, '' if loose == 1
                                                 else 's'))
        return ', '.join(names)

    def _floating_text(self, pieces):
        lines = ['%d piece(s) of the model stand on nothing -- no support '
                 'reaches them, so the analysis cannot hold them:'
                 % len(pieces)]
        for p in pieces[:8]:
            lines.append('  • %s (%d rods)' % (self._piece_name(p), len(p)))
        if len(pieces) > 8:
            lines.append('  … and %d more' % (len(pieces) - 8))
        return '\n'.join(lines)

    def _offer_floating_fixes(self, pieces, err=None):
        """A window naming the floating pieces, with three ways forward.
        Not modal: the drawing stays usable behind it."""
        self._floating_last = pieces
        old = getattr(self, '_floating_win', None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
        win = tk.Toplevel(self.canvas)
        win.title('Analyze: pieces with no support')
        self._floating_win = win
        tk.Label(win, text=self._floating_text(pieces), justify='left',
                 anchor='w', font=('Helvetica', 9)).pack(fill='x', padx=12,
                                                        pady=(10, 6))

        def act(fn):
            def go():
                try:
                    win.destroy()
                except tk.TclError:
                    pass
                fn(pieces)
            return go
        for text, fn, why in (
                ('Leave them out of the analysis', self._floating_leave_out,
                 'their groups stay in the model, marked "left out"'),
                ('Lift them with a crane', self._floating_lift,
                 'pick their corners and open the Crane panel'),
                ('Give them supports', self._floating_support,
                 'select their lowest joints and open Support')):
            row = tk.Frame(win)
            row.pack(fill='x', padx=12, pady=2)
            tk.Button(row, text=text, width=28, command=act(fn)
                      ).pack(side='left')
            tk.Label(row, text=why, fg='#5f6368',
                     font=('Helvetica', 8)).pack(side='left', padx=(6, 0))
        tk.Button(win, text='Close', command=win.destroy).pack(pady=(6, 10))
        self._set_status('%d piece(s) stand on nothing -- see the window.'
                         % len(pieces), 'error')
        return win

    def _floating_leave_out(self, pieces):
        """Mark each floating piece's groups "left out", and analyse again.
        A piece of ungrouped rods becomes a group of its own first; a piece
        that is only part of a group is not taken -- that would leave the
        rest of the group hanging."""
        changed, skipped = [], []
        self._push_undo('leave floating pieces out')
        for k, p in enumerate(pieces, 1):
            tops, loose = self._piece_groups(p)
            if not tops:
                g = sgp.new_group(self.groups, 'Left out %d' % k, members=p)
                g['excluded'] = True
                changed.append(g['name'])
                continue
            cover = set()
            for t in tops:
                cover.update(sgp.rods_of(self.groups, t, deep=True))
            if loose or cover != set(p):
                skipped.append(self._piece_name(p))
                continue
            for t in tops:
                sgp.find(self.groups, t)['excluded'] = True
                changed.append(self._group_display_name(t))
        self._refresh_group_list()
        self.results = None
        self.member_checks = None
        msg = ('Left out of the analysis: %s.' % ', '.join(changed)
               if changed else 'Nothing was left out.')
        if skipped:
            msg += (' Not left out (only part of a group floats): %s.'
                    % ', '.join(skipped))
        self._analyze(quiet=True)
        self._set_status(msg + (' Analyzed.' if self.results is not None
                                else ''), 'ok' if changed else 'error')
        return changed

    def _floating_lift(self, pieces):
        """Pick the first floating piece's corners, make its group current
        and open the Crane panel."""
        from apps.stereo import stereo_floating as sf
        p = pieces[0]
        tops, loose = self._piece_groups(p)
        if len(tops) == 1 and not loose and set(
                sgp.rods_of(self.groups, tops[0], deep=True)) == set(p):
            self._set_current_group(tops[0], say=False)
        picks = sf.pick_nodes(self.nodes, self.members, p, 'corners')
        self.selected_nodes = set(picks)
        self.selected_members = set()
        self.selected_member = None
        self._sync_selection_fields()
        self._set_mode('addons')
        self._draw()
        self._set_status('%s: %d corner joints picked -- press "Lift the '
                         'selected nodes" in the Crane panel.'
                         % (self._piece_name(p), len(picks)), 'ok')
        return picks

    def _floating_support(self, pieces):
        """Select the lowest joints of every floating piece and open the
        Support panel."""
        from apps.stereo import stereo_floating as sf
        sel = set()
        for p in pieces:
            sel.update(sf.lowest_nodes(self.nodes, self.members, p))
        self.selected_nodes = sel
        self.selected_members = set()
        self.selected_member = None
        self._sync_selection_fields()
        self._set_mode('support')
        self._draw()
        self._set_status('%d lowest joint(s) of the floating piece(s) '
                         'selected -- choose a support and Apply.' % len(sel),
                         'ok')
        return sorted(sel)

    def _say_pick_inside(self):
        """Why a pick took less than was under the pointer."""
        gid = self._editing_gid()
        if gid is not None:
            self._set_status('You are inside %s, so only its own parts can '
                             'be picked. Press Esc to come back out.'
                             % self._group_display_name(gid), 'idle')
        else:
            self._set_status('Hidden groups cannot be picked -- Show all in '
                             'the Groups panel.', 'idle')
