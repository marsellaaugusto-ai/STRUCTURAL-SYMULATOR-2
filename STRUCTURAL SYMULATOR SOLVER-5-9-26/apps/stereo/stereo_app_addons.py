"""Add-on features that augment an existing Stereo mesh from the UI:
columns (shaft + capital) and reinforcement beams.

Thin controller layer over stereo_geometry_addons -- it reads the current
node selection and the add-on panel's fields, calls the geometry helper,
and pushes an undo entry. The structural work (and the reasoning about
which offset directions stay rigid) lives in the geometry module.
"""
import tkinter as tk
from tkinter import messagebox

from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_math as sm
from apps.stereo import stereo_plates as splates
from apps.stereo import stereo_addon_codes as sac
from apps.stereo import stereo_lift as slift
from apps.stereo import stereo_groups as sgp
from apps.stereo import stereo_lift_calc as slc



# How far (m) outside the pick points the centre of gravity may sit before a
# lift is flagged as one that tips -- rounding, not engineering.
CRANE_COG_TOL = 1e-3

class StereoAddonsMixin:
    """Column and reinforcement-beam commands for the Add-ons panel."""

    # Only the two OUT-OF-SURFACE directions are offered: reinforcing a
    # roof/floor by hanging or raising a triangular truss girder below/
    # above it (offset perpendicular to the surface, apex pointing away --
    # base flush against the two selected rows) is both the realistic use
    # case and the one verified rigid for every row length in
    # tests/test_stereo_geometry.py. An in-plane offset (still within the
    # surface's own z=0 plane, say) was tested and found to leave a soft/
    # singular mode for this triangulation, so it is deliberately not
    # offered here even though reinforcement_beam() itself accepts any
    # non-edge-parallel direction for callers who need it.
    BEAM_DIRECTIONS = {'Down (-Z)': (0.0, 0.0, -1.0), 'Up (+Z)': (0.0, 0.0, 1.0)}

    # Which member roles belong to which add-on, so one removal routine can
    # serve both Clear buttons. These are the roles stereo_geometry_addons
    # tags its own members with and nothing else uses.
    COLUMN_ROLES = frozenset({'column_shaft', 'column_tie', 'column_chord',
                              'column_web', 'capital', 'capital_ring'})
    BEAM_ROLES = frozenset({'reinf_chord', 'reinf_web'})
    CRANE_ROLES = frozenset({'crane_cable', 'crane_mast'})
    CRANE_LIFT_PIECE = 'Piece under the hook'

    def _add_column(self):
        targets = sorted(self.selected_nodes)
        # The plain strut has no capital to attach, so it needs no footprint
        # to attach one to -- one node is a column, and each node selected
        # gets its own post.
        plain = self.col_style.get() == sg.COLUMN_PLAIN
        if not targets:
            messagebox.showerror('Column', 'Select the node(s) the column stands under '
                                           'first.')
            return
        if not plain and len(targets) < 3:
            messagebox.showerror('Column',
                                 'Select at least 3 nodes (a lasso box) for the capital '
                                 'to attach to first -- or choose the plain vertical '
                                 'strut, which needs no capital.')
            return
        try:
            height = float(self.col_height.get())
            tiers = int(self.col_tiers.get())
            capital_height = float(self.col_capital.get())
            width = float(self.col_width.get())
            panels = int(self.col_panels.get())
        except (tk.TclError, ValueError):
            messagebox.showerror('Column', 'Enter valid column dimensions.')
            return
        try:
            nodes, members, bases, head = sg.add_column(
                self.nodes, self.members, targets, height, tiers=tiers,
                style=self.col_style.get(), capital_height=capital_height,
                width=width, panels=panels)
        except ValueError as exc:
            messagebox.showerror('Column', str(exc))
            return
        # An add-on bolts new rods ON; it must not move or drop a locked
        # group's. Checked against the lists it built, not assumed.
        if not self._guard_rebuild('Column', nodes, members):
            return
        self._push_undo('add column')
        n_before = len(self.members)
        self._carry_groups(self.members, members)
        self.nodes, self.members = nodes, members
        self._adopt_new_rods(n_before)
        code = sac.tag(self.members, range(n_before, len(self.members)),
                        sac.next_code(sac.COLUMN, self.members[:n_before],
                                      self.panels))
        self._set_status(f'{sac.describe(code)} added -- its rods carry '
                         f'the code {code}.', 'ok')
        # EVERY foot is pinned, not just the first. A latticed or splay-
        # footed column is rigid as a body, so restraining one node of it
        # leaves three rotations free and the solver reports a mechanism
        # instead of a result.
        self._support_candidates = list(self._support_candidates) + list(bases)
        self.supports = [s for s in self.supports if s['node'] not in set(bases)]
        self.supports.extend({'node': b, 'type': 'pin'} for b in bases)
        # The nodes the column now carries must STOP being supports of their
        # own. A pin left at the head is a rigid path to ground sitting in
        # parallel with the column, and it wins every time: measured on a
        # flat grid, a plain post under a pinned corner carried exactly
        # 0.00 kN with the pin still there and 23.17 kN once it was gone.
        # The column was in the picture and in the member list, and carried
        # nothing. Standing a column under a joint is a statement about how
        # that joint reaches the ground, so the old pin goes.
        freed = sorted({s['node'] for s in self.supports} & set(targets))
        if freed:
            # Keep the entries themselves, not just the node numbers: Clear
            # columns hands them back, and nothing in the mesh afterwards
            # remembers that a pin was ever there -- least of all what KIND
            # of pin it was.
            self._column_freed = list(getattr(self, '_column_freed', [])) + [
                dict(sp) for sp in self.supports if sp['node'] in set(freed)]
            self.supports = [s for s in self.supports if s['node'] not in set(freed)]
            self._support_candidates = [i for i in self._support_candidates
                                        if i not in set(freed)]
        if self.col_braced.get():
            # A pin-ended column gives the structure no sway restraint at
            # all. "Braced" models the usual real detail -- the roof plane
            # or a bracing bay holds the capital horizontally -- by
            # restraining ux and uy at the head and LEAVING uz free, so the
            # column's own axial shortening and its E3 buckling check still
            # govern. Holding uz too would be a rigid prop, which is the
            # very thing the column is there instead of.
            heads = sorted(set(targets))
            self.supports.extend({'node': h, 'dofs': {'ux': True, 'uy': True}}
                                 for h in heads)
        self._set_column_note(freed, bases, code)
        self._apply_sections(members=self.members, redraw=False,
                             only=range(n_before, len(self.members)))
        self.selected_nodes = set(bases)
        self.results = None
        self.member_checks = None
        self._refresh_all()

    # ── welded shear panels ─────────────────────────────────────────────────
    def _add_shear_panel(self):
        """Weld a plate into the polygon the selected nodes close.

        The plate is not decoration: its in-plane shear stiffness goes into
        the solve, so adding one visibly stiffens the bay, and it is checked
        for yield, weld and -- the one that governs a thin plate -- shear
        buckling.
        """
        loop, why = splates.panel_loop_from_nodes(self.members, self.selected_nodes)
        if loop is None:
            messagebox.showerror('Shear panel', why)
            return
        try:
            t_mm = float(self.panel_t.get())
            Fy = float(self.panel_fy.get())
            weld_lines = int(self.panel_weld_lines.get())
        except (tk.TclError, ValueError):
            messagebox.showerror('Shear panel', 'Enter a valid thickness and Fy.')
            return
        if t_mm <= 0:
            messagebox.showerror('Shear panel', 'Thickness must be positive.')
            return
        panel = {'nodes': list(loop), 'thickness_mm': t_mm, 'Fy': Fy,
                 'weld_lines': weld_lines, 'E_GPa': 200.0, 'nu': 0.3}
        # Refuse it HERE, where the nodes are still selected and the message
        # can name what is wrong, rather than letting the solver drop it
        # silently and leave a panel in the list that never carries anything.
        geom, bad = splates.panel_geometry(self.nodes, panel)
        if geom is None:
            messagebox.showerror('Shear panel', bad)
            return
        if any(sorted(p['nodes']) == sorted(loop) for p in self.panels):
            self._set_addon_note('There is already a panel on those nodes.')
            return
        self._push_undo('add shear panel')
        panel['addon'] = sac.next_code(sac.PANEL, self.members, self.panels)
        self.panels.append(panel)
        self.results = None
        self.member_checks = None
        self.panel_checks = []
        area = geom[2]
        self._set_addon_note(f'{sac.describe(panel["addon"])} welded over '
                             f'{len(loop)} nodes, '
                             f'{abs(area):.2f} m\u00b2. Analyze to solve it.')
        self._refresh_all()

    def _clear_shear_panels(self):
        if not self.panels:
            self._set_addon_note('No shear panels to clear.')
            return
        self._push_undo('clear shear panels')
        n = len(self.panels)
        self.panels = []
        self.results = None
        self.member_checks = None
        self.panel_checks = []
        self._set_addon_note(f'{n} shear panel(s) removed.')
        self._refresh_all()

    # ── clearing add-ons, and building a column array ───────────────────────
    def _strip_members(self, roles, label, codes=None):
        """Remove every member in `roles`, then every node they leave with
        nothing attached, and renumber what is left.

        Only ORPHANS go. A grid node a capital fanned to still carries its
        own chords, so it stays exactly where it was -- deleting it would
        tear a hole in the roof to remove the column under it.

        Returns the number of members removed.
        """
        victims = [i for i, m in enumerate(self.members)
                   if m.get('role') in roles
                   and (codes is None or m.get('addon') in codes)]
        if not victims:
            return 0
        if getattr(self, 'groups', None):
            from apps.stereo import stereo_groups as _sgp
            locked = _sgp.protected_rods(self.groups, self._editing_gid())
            hit = [i for i in victims if i in locked]
            if hit:
                own = _sgp.owner_of_rod(self.groups)
                by = {}
                for i in hit:
                    by.setdefault(own[i], []).append(i)
                self._group_refuse(
                    'Clear',
                    'Nothing was cleared: those rods are part of a locked '
                    'group -- %s.\n\nOpen the group with Edit group, or '
                    'ungroup them, first.' % _sgp.describe_rods(self.groups, by))
                return 0
        self._push_undo(label)
        drop = set(victims)
        kept = [m for i, m in enumerate(self.members) if i not in drop]

        used = set()
        for m in kept:
            used.add(m['a'])
            used.add(m['b'])
        order = sorted(used)
        remap = {old: new for new, old in enumerate(order)}

        self.nodes = [self.nodes[i] for i in order]
        # Groups hold MEMBER indices, and this rebuild shifts every index
        # after a dropped rod. Remap before the list is replaced, or a branch
        # silently comes to mean different rods -- see
        # stereo_groups.remap_members.
        if getattr(self, 'groups', None):
            from apps.stereo import stereo_groups as _sgp
            _sgp.remap_members(self.groups,
                               _sgp.member_remap(len(self.members), drop))
        self.members = [dict(m, a=remap[m['a']], b=remap[m['b']]) for m in kept]
        self.supports = [dict(sp, node=remap[sp['node']])
                         for sp in self.supports if sp['node'] in remap]
        self.loads = [dict(ld, node=remap[ld['node']])
                      for ld in self.loads if ld['node'] in remap]
        self._support_candidates = sorted(
            {remap[i] for i in self._support_candidates if i in remap})
        self._load_nodes = {remap[i]: a for i, a in (self._load_nodes or {}).items()
                            if i in remap}
        self._disabled_supports = {remap[i] for i in self._disabled_supports
                                   if i in remap}
        self.selected_nodes = {remap[i] for i in self.selected_nodes if i in remap}
        self.selected_member = None
        self.results = None
        self.member_checks = None
        return len(victims)


    # ── cable crane: the lift calculator (stereo_lift_calc) ────────────────

    def _crane_settings(self):
        """The Crane panel's settings as numbers; ValueError, with the
        reason, for one that cannot be used."""
        try:
            mode = self._crane_hook_mode()
            value = None if mode == 'auto' else float(self.crane_rise.get())
            daf = float(self.crane_daf.get())
            allow = float(self.crane_allowance.get())
        except (tk.TclError, ValueError):
            raise ValueError('Type the hook setting, the dynamic factor and '
                             'the connections allowance as numbers.')
        if daf < 1.0:
            raise ValueError('The dynamic factor is 1.0 or more: a lift never '
                             'weighs less than the piece.')
        if allow < 0.0:
            raise ValueError('The connections allowance is a percentage of '
                             'the rods\' weight, zero or more.')
        sizes = slc.parse_sizes(self.crane_sizes.get())
        wll, spec = self._crane_cable_capacity()
        return {'hook_mode': mode, 'hook_value': value, 'daf': daf,
                'allowance': allow / 100.0, 'wll_kN': wll,
                'cable_spec': spec, 'sizes': sizes}

    def _add_cable_crane(self):
        """Hang the selected joints from a hook straight over the lifted
        piece's centre of gravity.

        No mast and no supports: the hook is the fixed point the lift is
        solved from, and the piece only goes up (stereo_lift_calc). Nothing
        is added to or taken from the model's supports.
        """
        targets = sorted(self.selected_nodes)
        if len(targets) < 3:
            messagebox.showerror(
                'Crane',
                'Select at least 3 joints to lift -- drag a box over the '
                'joints the slings hook onto. The hook goes over the piece\'s '
                'centre of gravity, and fewer than three slings cannot hold '
                'it level.')
            return
        try:
            settings = self._crane_settings()
        except ValueError as exc:
            messagebox.showerror('Crane', str(exc))
            return
        lift = self._crane_lift_rods(targets)
        if lift is None:
            return
        lift_rods, lift_gid = lift
        weight, cog = slc.piece_weight(self.nodes, self.members, lift_rods,
                                       settings['allowance'],
                                       self._unit_weight())
        if cog is None:
            messagebox.showerror(
                'Crane', 'The piece weighs nothing: give its rods a section '
                         'first, so it has a weight and a centre of gravity.')
            return
        # Refused BEFORE anything is built: with the hook over the centre of
        # gravity, a centre of gravity outside the picks means the far
        # slings would have to push. They go slack and the piece tips.
        off = slift.cog_outside_picks(self.nodes, targets, cog[:2])
        if off > CRANE_COG_TOL:
            messagebox.showerror(
                'Crane',
                'The piece\'s centre of gravity, at x %.2f, y %.2f, is %.2f m '
                'outside the pick points seen from above. Hung from a hook '
                'over it, the slings on the far side would have to push: '
                'they go slack and the piece tips. Pick joints all round the '
                'centre of gravity -- the outer corners usually are.'
                % (cog[0], cog[1], off))
            return
        try:
            rise = slc.hook_rise(self.nodes, targets, cog[:2],
                                 settings['hook_mode'], settings['hook_value'])
        except ValueError as exc:
            messagebox.showerror('Crane', str(exc))
            return
        top = max(self.nodes[i][2] for i in targets)
        hook_xyz = (cog[0], cog[1], top + rise)
        nodes, members, hook = slc.add_slings(
            self.nodes, self.members, targets, self._panel_section('web'),
            hook_xyz)
        # An add-on bolts new rods ON; it must not move or drop a locked
        # group's. Checked against the lists it built, not assumed.
        if not self._guard_rebuild('Crane', nodes, members):
            return
        self._push_undo('add crane')
        n_before = len(self.members)
        self._carry_groups(self.members, members)
        self.nodes, self.members = nodes, members
        self._adopt_new_rods(n_before)
        code = sac.tag(self.members, range(n_before, len(self.members)),
                       sac.next_code(sac.CRANE, self.members[:n_before],
                                     self.panels))
        self._crane_lifts = list(getattr(self, '_crane_lifts', None) or []) + [{
            'code': code, 'picks': list(targets), 'rods': list(lift_rods),
            'group': lift_gid, 'hook': hook, 'hook_xyz': hook_xyz,
            'hook_mode': settings['hook_mode'],
            'hook_value': settings['hook_value'], 'daf': settings['daf'],
            'allowance': settings['allowance'], 'wll_kN': settings['wll_kN'],
            'cable_spec': settings['cable_spec'],
            'sizes': settings['sizes']}]
        self.results = None
        self.member_checks = None
        self._me_maybe_refresh_topology()
        # Solved now, on its own -- it is small -- so the summary is there
        # at once and a lift that cannot hang is caught here, not later.
        solved = self._solve_one_lift(self._crane_lifts[-1], settings['sizes'])
        what = (f'group {self._group_display_name(lift_gid)}'
                if lift_gid is not None else 'the piece under the hook')
        self._set_status(f'{sac.describe(code)} added -- its rods carry '
                         f'the code {code}.', 'ok')
        if solved['ok']:
            self._show_lift_summary([solved])
            s = solved['summary']
            self._set_addon_note(
                f'{sac.describe(code)} lifts {what} ({len(lift_rods)} rods, '
                f'{s["weight"]:.2f} kN) on {len(targets)} slings to a hook '
                f'{rise:.2f} m above the highest pick, over the centre of '
                f'gravity. No supports were added or removed. ▶ Analyze lift '
                f'shows what the lift does to the piece.')
            warn = None
            if s['verdict'] != 'OK':
                warn = f'{code}: {s["verdict"]} -- see the lift summary.'
        else:
            self._show_lift_summary([solved])
            loose = solved.get('loose') or []
            if loose:
                self.selected_nodes = set(loose)
                self.selected_members = set()
                self.selected_member = None
                self._sync_selection_fields()
            flat = self._picks_in_one_plane_with_hook(targets, hook)
            self._set_addon_note(
                f'{sac.describe(code)} cannot hold {what}: '
                + ('%d node(s) of it can move with no stiffness -- selected '
                   'on the drawing. ' % len(loose) if loose else
                   (solved.get('error') or '') + ' ')
                + ('The slings all hang in one plane, so the piece can turn '
                   'about them like a flag: hook onto joints off that plane.'
                   if flat else
                   'Hook slings to that part too (the corners usually do '
                   'it), or lift it with what holds it together.'))
            warn = f'{code}: the lifted piece is a mechanism on these slings.'
        self._refresh_all()
        # after the refresh, which rewrites the status line from the model
        if warn:
            self._set_status(warn, 'error')

    def _picks_in_one_plane_with_hook(self, picks, hook, tol=1e-3):
        """True when the pick points and the hook all lie in one plane --
        the slings form a fan, and the piece can rotate about it."""
        import numpy as np
        pts = np.array([self.nodes[n] for n in list(picks) + [hook]], float)
        if len(pts) < 4:
            return True
        c = pts - pts.mean(axis=0)
        sv = np.linalg.svd(c, compute_uv=False)
        return sv[-1] <= tol * max(sv[0], 1e-9)

    def _crane_cable_capacity(self):
        """(working load limit kN or None, how it was arrived at)."""
        mode = self.crane_cap_mode.get() if hasattr(self, 'crane_cap_mode') \
            else 'none'
        try:
            if mode == 'wll':
                w = float(self.crane_wll.get())
                if w > 0:
                    return w, f'WLL {w:g} kN per cable, as entered'
            elif mode == 'dia':
                d = float(self.crane_dia.get())
                w = slift.rope_wll_kN(d)
                if w > 0:
                    return w, (f'wire rope Ø{d:g} mm, 6x36 IWRC grade 1770: '
                               f'breaking force ≈ {slift.ROPE_MBF_K:g}·d² = '
                               f'{slift.ROPE_MBF_K * d * d:,.0f} kN, '
                               f'÷ {slift.ROPE_FACTOR:g} → WLL '
                               f'{w:,.1f} kN per cable')
        except (tk.TclError, ValueError):
            pass
        return None, 'no cable capacity set -- tensions only'

    def _crane_records(self):
        """One record per crane in the model, in code order, with the rods
        it lifts re-read NOW -- from its group, or else from the piece its
        slings hook onto -- so it follows every edit made since. A crane
        with no record (a workbook from before the Cranes sheet) gets the
        defaults."""
        by_code = {r.get('code'): r for r in
                   getattr(self, '_crane_lifts', None) or []}
        out = []
        for code in slift.crane_codes(self.members):
            rec = dict(by_code.get(code) or {'code': code})
            cables, picks, hook = slc.lift_parts(self.members, code)
            gid = rec.get('group')
            if gid is not None and getattr(self, 'groups', None) \
                    and sgp.find(self.groups, gid):
                rods = sorted(sgp.rods_of(self.groups, gid, deep=True))
                rec['group_name'] = self._group_display_name(gid)
                rec['what'] = f'group {rec["group_name"]}'
            else:
                rods = slift.connected_piece(self.members, picks)
                rec['group'] = None
                rec['group_name'] = None
                rec['what'] = 'the piece under the hook'
            rec.update(rods=rods, picks=picks, hook=hook,
                       hook_xyz=tuple(self.nodes[hook]) if hook is not None
                       else None)
            rec.setdefault('daf', 1.0)
            rec.setdefault('allowance', 0.0)
            rec.setdefault('wll_kN', None)
            rec.setdefault('cable_spec', 'no cable capacity set -- tensions '
                                         'only')
            rec.setdefault('hook_mode', 'auto')
            rec.setdefault('hook_value', None)
            out.append(rec)
        return out

    def _solve_one_lift(self, record, sizes=None):
        return slc.solve_lift(
            self.nodes, self.members, record, unit_weight=self._unit_weight(),
            timber=self._timber_settings(),
            sizes=sizes or record.get('sizes') or slc.STANDARD_ROPE_MM)

    def _solve_lifts(self, sizes=None):
        """Every crane's lift, each solved on its own."""
        return [self._solve_one_lift(r, sizes) for r in self._crane_records()]

    def _analyze_lifts(self):
        """Solve every lift on its own and show it: the lifted pieces carry
        their lift forces, everything else is greyed out. The panel's
        factors and cable capacity apply to every crane."""
        if not slift.crane_codes(self.members):
            messagebox.showinfo(
                'Analyze lift', 'There is no crane yet. Select the joints the '
                                'slings hook onto and press "Lift the '
                                'selected nodes".')
            return
        try:
            settings = self._crane_settings()
        except ValueError as exc:
            messagebox.showerror('Analyze lift', str(exc))
            return
        recs = self._crane_records()
        for r in recs:
            for k in ('daf', 'allowance', 'wll_kN', 'cable_spec', 'sizes'):
                r[k] = settings[k]
        self._crane_lifts = [
            {k: v for k, v in r.items() if k not in ('what',)} for r in recs]
        solved = [self._solve_one_lift(r, settings['sizes']) for r in recs]
        self._show_lift_summary(solved)
        bad = [s for s in solved if not s['ok']]
        if bad:
            loose = sorted({n for s in bad for n in s.get('loose') or ()})
            if loose:
                self.selected_nodes = set(loose)
                self.selected_members = set()
                self.selected_member = None
                self._sync_selection_fields()
            self._refresh_all()
            messagebox.showerror(
                'Analyze lift', '\n'.join(
                    f'Crane {s["code"]}: ' + (
                        f'{len(s["loose"])} node(s) of the lifted piece can '
                        f'move with no stiffness on these slings.'
                        if s.get('loose') else (s.get('error') or 'did not '
                                                'solve.'))
                    for s in bad)
                + ('\n\nThose nodes are selected on the drawing.'
                   if loose else ''))
            return
        res, checks = slc.combine(len(self.nodes), self.members, solved)
        self.results, self.member_checks = res, checks
        self.panel_checks = []
        self.err = None
        self._lift_solved = solved
        self._auto_deform_scale()
        self._refresh_all()
        verdicts = ', '.join(f'{s["code"]} {s["summary"]["verdict"]}'
                             for s in solved)
        ok = all(s['summary']['verdict'] == 'OK' for s in solved)
        self._set_status(f'Lift results -- {verdicts}. Grey rods are not '
                         f'lifted; ▶ Analyze returns to the service loads.',
                         'ok' if ok else 'error')

    def _show_lift_summary(self, solved):
        """The lift summary in the Crane panel -- one block per crane."""
        box = getattr(self, 'crane_summary', None)
        blocks = []
        for s in solved:
            if s.get('ok'):
                blocks.append(slc.summary_text(s['summary']))
            else:
                blocks.append('Crane %s — did not solve: %s' % (
                    s.get('code'), s.get('error') or 'a mechanism'))
        text = '\n\n'.join(blocks)
        self._lift_summary_text = text
        verdicts = dict(getattr(self, '_lift_verdicts', None) or {})
        verdicts.update({s.get('code'): (s['summary']['verdict']
                                         if s.get('ok') else 'did not solve')
                         for s in solved})
        self._lift_verdicts = verdicts
        if box is None:
            return text
        box.configure(state='normal')
        box.delete('1.0', 'end')
        box.insert('1.0', text)
        box.configure(state='disabled')
        return text

    def _copy_lift_summary(self):
        text = getattr(self, '_lift_summary_text', '') or ''
        if not text:
            self._set_status('No lift summary yet: Lift or ▶ Analyze lift '
                             'first.', 'error')
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._set_status('Lift summary copied to the clipboard.', 'ok')

    # ── C10: the Lift box follows the group; live check; pick rules ────────

    def _follow_current_group(self):
        """The current group becomes what Lift takes."""
        gid = self._cur_gid() if hasattr(self, '_cur_gid') else None
        if gid is None or not hasattr(self, 'crane_lift_target'):
            return
        self._refresh_crane_lift_choices()
        for label, g in self._crane_lift_gids.items():
            if g == gid:
                self.crane_lift_target.set(label)
                return

    def _crane_preview(self):
        """What "Lift the selected nodes" would do now, without building
        anything or opening a dialog: {'ok', 'text', 'picks', 'hook_xyz'}."""
        targets = sorted(n for n in self.selected_nodes if n < len(self.nodes))
        out = {'ok': False, 'text': '', 'picks': targets, 'hook_xyz': None}
        if len(targets) < 3:
            out['text'] = ('Select 3 or more joints to lift by -- or use a '
                           'Pick button.' if self.members else '')
            return out
        self._refresh_crane_lift_choices()
        gid = self._crane_lift_gids.get(self.crane_lift_target.get())
        if gid is not None and sgp.find(self.groups, gid):
            rods = sorted(sgp.rods_of(self.groups, gid, deep=True))
            mine = slift.nodes_of(self.members, rods)
            off = [n for n in targets if n not in mine]
            if off:
                out['text'] = ('%d of the selected joints are not on group %s.'
                               % (len(off), self._group_display_name(gid)))
                return out
        else:
            rods = slift.connected_piece(self.members, targets)
        try:
            s = self._crane_settings()
        except ValueError as exc:
            out['text'] = str(exc)
            return out
        weight, cog = slc.piece_weight(self.nodes, self.members, rods,
                                       s['allowance'], self._unit_weight())
        if cog is None:
            out['text'] = 'The piece weighs nothing: give its rods a section.'
            return out
        off = slift.cog_outside_picks(self.nodes, targets, cog[:2])
        if off > CRANE_COG_TOL:
            out['text'] = ('✗ Centre of gravity %.2f m outside the picks -- '
                           'the piece would tip.' % off)
            return out
        try:
            rise = slc.hook_rise(self.nodes, targets, cog[:2],
                                 s['hook_mode'], s['hook_value'])
        except ValueError as exc:
            out['text'] = '✗ ' + str(exc)
            return out
        import math
        top = max(self.nodes[i][2] for i in targets)
        hook = (cog[0], cog[1], top + rise)
        L = [math.dist(self.nodes[p], hook) for p in targets]
        ang = [math.degrees(math.asin((hook[2] - self.nodes[p][2]) / l))
               for p, l in zip(targets, L)]
        out.update(ok=True, hook_xyz=hook, text=(
            '✓ %d picks · %d rods, %.2f kN (lift %.2f kN) · centre of gravity '
            'inside · hook +%.2f m · slings %.0f–%.0f° · longest %.2f m'
            % (len(targets), len(rods), weight, weight * s['daf'], rise,
               min(ang), max(ang), max(L))))
        return out

    def _refresh_crane_check(self):
        """The live check line, and the preview it draws -- only while the
        Add-ons panel is open."""
        lbl = getattr(self, 'crane_check', None)
        if lbl is None:
            return None
        self._refresh_crane_list()
        mode = getattr(self, 'active_mode', None)
        if mode is not None and mode.get() != 'addons':
            self._crane_preview_now = None
            return None
        try:
            prev = self._crane_preview()
        except Exception as exc:                            # noqa: BLE001
            prev = {'ok': False, 'text': str(exc), 'hook_xyz': None,
                    'picks': []}
        self._crane_preview_now = prev
        lbl.config(text=prev['text'], fg='#1d6b2e' if prev['ok'] else
                   ('#a3241a' if prev['text'].startswith('✗') else '#1d2328'))
        return prev

    def _draw_lift_preview(self, c, to_screen):
        """Dashed slings from the selected joints to where the hook would
        go, while the Add-ons panel is open."""
        prev = self._refresh_crane_check()
        if not prev or not prev.get('ok'):
            return
        hx, hy, _ = self._project(*prev['hook_xyz'])
        sx, sy = to_screen(hx, hy)
        for p in prev['picks']:
            px, py, _ = self._project(*self.nodes[p])
            ax, ay = to_screen(px, py)
            c.create_line(ax, ay, sx, sy, fill='#b8860b', dash=(4, 3),
                          width=1, tags='lift_preview')
        c.create_polygon(sx - 6, sy - 6, sx + 6, sy - 6, sx, sy + 3,
                         fill='#b8860b', outline='', tags='lift_preview')

    def _crane_rule_rods(self):
        """The piece a pick rule works on: the Lift box's group, else the
        current group, else the piece under the selected joints."""
        self._refresh_crane_lift_choices()
        gid = self._crane_lift_gids.get(self.crane_lift_target.get())
        if gid is None and hasattr(self, '_cur_gid'):
            gid = self._cur_gid()
        if gid is not None and sgp.find(self.groups, gid):
            return sorted(sgp.rods_of(self.groups, gid, deep=True)), gid
        if self.selected_nodes:
            return slift.connected_piece(self.members,
                                         sorted(self.selected_nodes)), None
        return [], None

    def _crane_pick_rule(self, rule):
        """Select the joints a pick rule gives on the piece to lift."""
        from apps.stereo import stereo_floating as sf
        rods, gid = self._crane_rule_rods()
        if not rods:
            self._set_status('Pick a group first (double-click one of its '
                             'rods, or choose it in the Lift box) -- or one '
                             'joint of the piece.', 'error')
            return []
        picks = sf.pick_nodes(self.nodes, self.members, rods, rule)
        self.selected_nodes = set(picks)
        self.selected_members = set()
        self.selected_member = None
        self._sync_selection_fields()
        self._draw()
        what = (self._group_display_name(gid) if gid is not None
                else 'the piece')
        self._set_status('%s: %d joint(s) picked on %s.' % (
            sf.PICK_RULE_LABELS[rule], len(picks), what),
            'ok' if len(picks) >= 3 else 'error')
        return picks

    def _crane_list_rows(self):
        last = getattr(self, '_lift_verdicts', None) or {}
        rows = []
        for r in self._crane_records():
            rows.append(('%-3s %s · %d slings%s' % (
                r['code'], r['what'], len(r['picks']),
                (' · ' + last[r['code']]) if r['code'] in last else ''),
                r['code']))
        return rows

    def _refresh_crane_list(self):
        lst = getattr(self, 'crane_list', None)
        if lst is None:
            return
        rows = self._crane_list_rows()
        if rows == getattr(self, '_crane_list_rows_now', None):
            return
        keep = self._crane_list_code()
        self._crane_list_rows_now = rows
        lst.delete(0, 'end')
        for text, _code in rows:
            lst.insert('end', text)
        codes = [c for _t, c in rows]
        if keep in codes:
            lst.selection_set(codes.index(keep))

    def _crane_list_code(self):
        lst = getattr(self, 'crane_list', None)
        rows = getattr(self, '_crane_list_rows_now', None) or []
        if lst is None or not lst.curselection():
            return None
        i = lst.curselection()[0]
        return rows[i][1] if i < len(rows) else None

    def _remove_crane(self, code=None):
        """Take one crane out -- its slings and hook -- and keep the rest."""
        code = code or self._crane_list_code()
        if code is None:
            self._set_status('Pick a crane in the list to remove.', 'error')
            return 0
        n = self._strip_members(self.CRANE_ROLES, 'remove crane %s' % code,
                                codes={code})
        if not n:
            return 0
        self._crane_lifts = [r for r in getattr(self, '_crane_lifts', [])
                             if r.get('code') != code]
        (getattr(self, '_lift_verdicts', None) or {}).pop(code, None)
        self._me_maybe_refresh_topology()
        self._set_addon_note(f'{sac.describe(code)} removed ({n} slings).')
        self._refresh_all()
        return n

    def _crane_meta(self):
        """{code: what the crane report needs to know about each lift} --
        what it lifts (re-read now, so it follows edits made since), its
        settings, and its lift solved on its own."""
        out = {}
        for r in self._crane_records():
            solved = self._solve_one_lift(r)
            out[r['code']] = {'rods': r['rods'], 'what': r['what'],
                              'wll_kN': r.get('wll_kN'),
                              'cable_spec': r.get('cable_spec', ''),
                              'solved': solved}
        return out

    def _lift_export(self):
        """What Export Excel writes about the cranes: their settings, each
        lift solved on its own, and the group each rod belongs to. None
        without a crane."""
        if not slift.crane_codes(self.members):
            return None
        recs = self._crane_records()
        group_of = {}
        if getattr(self, 'groups', None):
            group_of = {j: self._group_display_name(g) for j, g in
                        sgp.owner_of_rod(self.groups).items()}
        return {'records': recs,
                'solved': [self._solve_one_lift(r) for r in recs],
                'group_of': group_of}

    def _crane_lifts_from_sheet(self, by_code):
        """Lift records from a workbook's Cranes sheet, each crane's group
        found again by its name. Cranes the sheet does not list get the
        defaults when they are solved."""
        names = {}
        for g, _lvl in sgp.walk(getattr(self, 'groups', None) or []):
            names.setdefault(self._group_display_name(g['id']), g['id'])
            names.setdefault(g.get('name'), g['id'])
        out = []
        for code in slift.crane_codes(self.members):
            rec = by_code.get(code)
            if not rec:
                continue
            rec = dict(rec)
            rec['group'] = names.get(rec.pop('group_name', None))
            out.append(rec)
        return out

    def _refresh_crane_lift_choices(self):
        """'Piece under the hook', then every group, by name."""
        choices = [self.CRANE_LIFT_PIECE]
        self._crane_lift_gids = {}
        for g, lvl in sgp.walk(getattr(self, 'groups', None) or []):
            label = '   ' * lvl + self._group_display_name(g['id'])
            self._crane_lift_gids[label] = g['id']
            choices.append(label)
        box = getattr(self, 'crane_lift_box', None)
        if box is not None:
            box.configure(values=choices)
        if self.crane_lift_target.get() not in choices:
            self.crane_lift_target.set(self.CRANE_LIFT_PIECE)
        return choices

    def _crane_lift_rods(self, targets):
        """(rods lifted, group id or None) for a lift from `targets`, or
        None -- after saying why -- when it cannot be lifted."""
        self._refresh_crane_lift_choices()
        gid = self._crane_lift_gids.get(self.crane_lift_target.get())
        if gid is None:
            return slift.connected_piece(self.members, targets), None
        rods = sorted(sgp.rods_of(self.groups, gid, deep=True))
        name = self._group_display_name(gid)
        if not rods:
            messagebox.showerror('Crane', f'Group {name} has no rods to lift.')
            return None
        mine = slift.nodes_of(self.members, rods)
        off = [n for n in targets if n not in mine]
        if off:
            messagebox.showerror(
                'Crane',
                f'The slings have to hook onto group {name}: '
                f'{len(off)} of the selected joints are not on it '
                f'(node {", ".join(str(n) for n in off[:6])}'
                f'{" ..." if len(off) > 6 else ""}).')
            return None
        joined = slift.joined_to_rest(self.members, rods)
        if joined:
            messagebox.showerror(
                'Crane',
                f'Group {name} is still joined to the rest of the model at '
                f'{len(joined)} node(s) (node '
                f'{", ".join(str(n) for n in joined[:6])}'
                f'{" ..." if len(joined) > 6 else ""}). A lift shows how a '
                f'piece takes being picked up on its own; joined to rods '
                f'that stay on the ground it is held, not lifted. Lift a '
                f'group that is a separate piece -- or put the rods it shares '
                f'those nodes with into the group too.')
            return None
        return rods, gid

    def _crane_support_ids(self):
        """id() of each support that belongs to a crane: the fixed top of a
        mast, in a model saved before the crane lost its mast."""
        tops = set()
        for m in self.members:
            if m.get('role') == 'crane_mast':
                tops.update((m['a'], m['b']))
        return {id(sp) for sp in self.supports if sp.get('node') in tops}

    def _clear_cable_cranes(self):
        n = self._strip_members(self.CRANE_ROLES, 'clear cranes')
        if not n:
            self._set_addon_note('No cranes to clear.')
            return
        # The hook goes with its slings: _strip_members drops the orphaned
        # node and keeps only the supports whose node survived. The model's
        # own supports were never touched.
        self._crane_lifts = []
        self._lift_verdicts = {}
        self._show_lift_summary([])
        self._me_maybe_refresh_topology()
        self._set_addon_note(f'{n} crane member(s) removed.')
        self._refresh_all()

    def _clear_columns(self):
        """Remove every column and capital at once.

        Undo already covers removing ONE, but a model with a dozen columns
        needs a dozen undos to get back to the bare grid, and by then the
        undo stack has eaten everything else you did in between.

        Supports the columns took over are handed back: a joint whose pin
        was removed because a column was carrying it would otherwise be
        left hanging, and the next Analyze would report a mechanism for a
        reason nothing on screen explains.
        """
        n = self._strip_members(self.COLUMN_ROLES, 'clear columns')
        if not n:
            self._set_addon_note('No columns to clear.')
            return
        restored = self._restore_freed_supports()
        self._me_maybe_refresh_topology()
        self._set_addon_note(
            f'{n} column member(s) removed.'
            + (f' {restored} support(s) handed back.' if restored else ''))
        self._refresh_all()

    def _clear_beams(self):
        n = self._strip_members(self.BEAM_ROLES, 'clear reinforcement beams')
        if not n:
            self._set_addon_note('No reinforcement beams to clear.')
            return
        self._me_maybe_refresh_topology()
        self._set_addon_note(f'{n} beam member(s) removed.')
        self._refresh_all()

    def _restore_freed_supports(self):
        """Put back the supports the columns took over, for the nodes that
        still exist. Recorded at the moment each column took them, because
        nothing in the mesh afterwards remembers that a pin was ever
        there."""
        have = {sp['node'] for sp in self.supports}
        back = 0
        for entry in getattr(self, '_column_freed', []):
            node = entry.get('node')
            if node is not None and 0 <= node < len(self.nodes) and node not in have:
                self.supports.append(dict(entry))
                self._support_candidates = sorted(set(self._support_candidates) | {node})
                have.add(node)
                back += 1
        self._column_freed = []
        return back

    def _build_column_array(self):
        """Stand a regular n x m array of columns under the model.

        The original placed them at plan coordinates, because its grid was
        always a rectangle of known module size. This mesh may be a cut
        plan, a dome or a vault, so the array is laid out over the model's
        OWN plan extent and each station then snaps to real nodes -- an
        (x, y) with no node under it is not somewhere a column can stand.
        """
        try:
            ncx = max(1, int(self.col_array_x.get()))
            ncy = max(1, int(self.col_array_y.get()))
        except (tk.TclError, ValueError):
            messagebox.showerror('Column array', 'Enter whole numbers for the array.')
            return
        if not self.nodes:
            messagebox.showerror('Column array', 'Generate a model first.')
            return
        plain = self.col_style.get() == sg.COLUMN_PLAIN
        per_station = 1 if plain else 4

        # Columns stand under the LOWEST layer; picking from every node
        # would let a station snap to the top chord and hang a column in
        # mid-air below it.
        zs = [p[2] for p in self.nodes]
        floor = min(zs)
        band = (max(zs) - floor) * 0.05
        candidates = [i for i, p in enumerate(self.nodes) if p[2] <= floor + band]
        if len(candidates) < per_station:
            messagebox.showerror('Column array',
                                 'Not enough nodes in the bottom layer to stand '
                                 'a column on.')
            return

        xs = [self.nodes[i][0] for i in candidates]
        ys = [self.nodes[i][1] for i in candidates]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        stations = [(x0 + (x1 - x0) * (a + 1) / (ncx + 1),
                     y0 + (y1 - y0) * (b + 1) / (ncy + 1))
                    for a in range(ncx) for b in range(ncy)]

        added, taken = 0, set()
        for sx, sy in stations:
            pool = [i for i in candidates if i not in taken]
            if len(pool) < per_station:
                break
            pool.sort(key=lambda i: (self.nodes[i][0] - sx) ** 2
                                    + (self.nodes[i][1] - sy) ** 2)
            pick = pool[:per_station]
            taken.update(pick)
            self.selected_nodes = set(pick)
            before = len(self.members)
            self._add_column()
            if len(self.members) > before:
                added += 1
        self._set_addon_note(
            f'{added} of {len(stations)} column(s) placed '
            f'({ncx} \u00d7 {ncy} array).' if added else
            'No column could be placed -- try fewer, or the plain strut.')

    def _set_addon_note(self, text):
        note = getattr(self, 'col_note', None)
        if note is not None:
            note.config(text=text)

    def _set_column_note(self, freed, bases, code=None):
        """Say what the column did to the boundary conditions.

        Removing a support is not a detail the user should have to discover
        from a reaction that moved: they asked for a column, and got a
        different set of supports than they had. A dialog on every column
        would be worse -- it is a normal consequence, not an error -- so it
        is stated in the panel, next to the button that caused it.
        """
        note = getattr(self, 'col_note', None)
        if note is None:
            return
        feet = f"{len(bases)} {'foot' if len(bases) == 1 else 'feet'} pinned"
        if code:
            feet = f'{sac.describe(code)}: {feet}'
        if freed:
            which = ', '.join(str(i) for i in freed[:6])
            more = f" (+{len(freed) - 6} more)" if len(freed) > 6 else ''
            note.config(text=f'{feet}. Node{"" if len(freed) == 1 else "s"} {which}'
                             f'{more} no longer pinned -- the column carries '
                             f'{"it" if len(freed) == 1 else "them"} to the ground now.')
        else:
            note.config(text=f'{feet}.')

    def _split_selection_into_two_rows(self):
        """Split the current lasso selection into two equal-length,
        correspondingly-ordered rows for the reinforcement beam: the axis
        with exactly two distinct coordinate values (rounded) is treated as
        "across" the two rows -- e.g. two adjacent bottom-chord rows of a
        flat_grid differ only in y -- and each side is then ordered along
        whichever remaining axis actually varies, so row A's k-th node
        lines up with row B's k-th the way two parallel grid rows do.
        Returns (edge_a, edge_b), each possibly empty if the selection
        does not look like two clean parallel rows."""
        ids = sorted(self.selected_nodes)
        if len(ids) < 4:
            return [], []
        pts = [self.nodes[i] for i in ids]
        axis_values = [sorted({round(p[k], 6) for p in pts}) for k in range(3)]
        row_axis = next((k for k in range(3) if len(axis_values[k]) == 2), None)
        if row_axis is None:
            return [], []
        v0, v1 = axis_values[row_axis]
        group0 = [i for i in ids if round(self.nodes[i][row_axis], 6) == v0]
        group1 = [i for i in ids if round(self.nodes[i][row_axis], 6) == v1]
        if len(group0) != len(group1) or len(group0) < 2:
            return [], []
        remaining = [k for k in range(3) if k != row_axis]
        order_axis = max(remaining, key=lambda k: len(axis_values[k]))
        group0.sort(key=lambda i: self.nodes[i][order_axis])
        group1.sort(key=lambda i: self.nodes[i][order_axis])
        return group0, group1

    def _add_reinforcement_beam(self):
        edge_a, edge_b = self._split_selection_into_two_rows()
        if not edge_a:
            messagebox.showerror('Reinforcement beam',
                                 'Select two parallel rows of >=2 nodes each (a lasso box '
                                 'spanning both rows) first.')
            return
        try:
            depth = float(self.beam_depth.get())
            tiers = int(self.beam_tiers.get())
        except (tk.TclError, ValueError):
            messagebox.showerror('Reinforcement beam', 'Enter a valid offset depth.')
            return
        direction = self.BEAM_DIRECTIONS[self.beam_dir.get()]
        try:
            nodes, members, apex = sg.reinforcement_beam(
                self.nodes, self.members, edge_a, edge_b, depth, direction,
                tiers=tiers, profile=self.beam_profile.get(),
                depth_law=self.beam_depth_law.get())
        except ValueError as exc:
            messagebox.showerror('Reinforcement beam', str(exc))
            return
        # An add-on bolts new rods ON; it must not move or drop a locked
        # group's. Checked against the lists it built, not assumed.
        if not self._guard_rebuild('Reinforcement beam', nodes, members):
            return
        self._push_undo('add reinforcement beam')
        n_before = len(self.members)
        self._carry_groups(self.members, members)
        self.nodes, self.members = nodes, members
        self._adopt_new_rods(n_before)
        code = sac.tag(self.members, range(n_before, len(self.members)),
                        sac.next_code(sac.BEAM, self.members[:n_before],
                                      self.panels))
        self._set_status(f'{sac.describe(code)} added -- its rods carry '
                         f'the code {code}.', 'ok')
        self._apply_sections(members=self.members, redraw=False,
                             only=range(n_before, len(self.members)))
        self.selected_nodes = set(apex)
        self.results = None
        self.member_checks = None
        self._refresh_all()
