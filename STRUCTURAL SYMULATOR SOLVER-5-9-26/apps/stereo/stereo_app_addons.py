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
    def _strip_members(self, roles, label):
        """Remove every member in `roles`, then every node they leave with
        nothing attached, and renumber what is left.

        Only ORPHANS go. A grid node a capital fanned to still carries its
        own chords, so it stays exactly where it was -- deleting it would
        tear a hole in the roof to remove the column under it.

        Returns the number of members removed.
        """
        victims = [i for i, m in enumerate(self.members)
                   if m.get('role') in roles]
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


    # ── cable crane (roadmap v2, 3.6) ──────────────────────────────────────

    def _add_cable_crane(self):
        """Hang the selected nodes from a crane and FIX the top of its mast.

        Fixed, not pinned -- see the comment at the support below, which is
        where the reason lives.
        """
        targets = sorted(self.selected_nodes)
        if len(targets) < 3:
            messagebox.showerror(
                'Crane',
                'Select at least 3 nodes to lift -- drag a box over the '
                'joints the slings hook onto. The hook goes over their '
                'centroid, and two nodes have no centroid to speak of.')
            return
        try:
            auto = bool(self.crane_auto.get())
            rise = None if auto else float(self.crane_rise.get())
            mast = float(self.crane_mast.get())
        except (tk.TclError, ValueError):
            messagebox.showerror('Crane', 'Enter a valid hook rise and mast length.')
            return
        if mast <= 0:
            messagebox.showerror('Crane', 'The mast has to have some length.')
            return

        # Which piece is lifted -- decided BEFORE the crane's own rods exist.
        lift = self._crane_lift_rods(targets)
        if lift is None:
            return
        lift_rods, lift_gid = lift
        lifted_nodes = slift.nodes_of(self.members, lift_rods)

        # Through _panel_section so the mast -- which is RIGID and so takes a
        # bending check -- carries the catalog depth when there is one.
        section = self._panel_section('web')
        # The hook over the piece's centre of gravity, as a rigger hangs it,
        # not over the middle of the picks: on a pitched or lopsided piece
        # those differ, the piece tips, the light side's slings go slack and
        # the tag lines carry the lift (45 kN on a pitched module).
        try:
            cog = slift.centre_of_gravity(self.nodes, self.members, lift_rods,
                                          self._all_loads())
        except Exception:
            cog = None
        try:
            nodes, members, hook, anchor = sg.add_cable_crane(
                self.nodes, self.members, targets, section,
                rise=rise, mast=mast, hook_xy=cog)
        except ValueError as exc:
            messagebox.showerror('Crane', str(exc))
            return

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
        self._set_status(f'{sac.describe(code)} added -- its rods carry '
                         f'the code {code}.', 'ok')
        # FIXED, where the roadmap says "pin", and the difference is not
        # cosmetic. A lone rigid mast whose top can rotate has a zero-energy
        # TORSIONAL mode about its own axis: the cables are pin-jointed and
        # add no rotational stiffness at the hook, so nothing anywhere
        # resists that rotation and the solve is singular before a single
        # cable has gone slack -- which is exactly what happened when this
        # was first written with a pin. Free rotations also let the whole
        # mast swing about its top the moment the cables DO go slack, which
        # is the state a tension-only member exists to represent. Fixing the
        # anchor removes both, and a mast built into its mounting is the
        # more honest idealisation of a crane anyway.
        self.supports.append({'node': anchor, 'type': 'fixed'})

        # A lifted structure is not also standing on the ground, and leaving
        # its own supports in place is not a harmless extra: it is a rigid
        # path to ground in parallel with the slings, and it wins every time.
        # Measured on the default grid -- with the grid's own supports left
        # in, ALL FOUR slings read 0.000 kN, so the crane is in the picture,
        # in the member list and in the checks, and carrying nothing. This is
        # the same trap the columns had, and it gets the same answer: the
        # add-on takes the supports over, says so in the panel, and Clear
        # every crane hands them back.
        lifted_off = 0
        tag = None
        if self.crane_off_ground.get():
            # The ground is every support that is not the crane's own: the
            # mast tops (this one and any earlier crane's) and the tag lines
            # an earlier lift added stay. A second lift used to take the
            # first crane's mast support and tag lines off as if they were
            # ground, leaving the first mast hanging from nothing.
            own = self._crane_support_ids()
            # Only the LIFTED piece's supports. Another truss in the same
            # file stays on the ground: taking its supports too left it
            # floating, and the whole model was refused as a mechanism.
            drop = [sp for sp in self.supports if id(sp) not in own
                    and sp.get('node') in lifted_nodes]
            ground = [dict(sp) for sp in drop]
            if ground:
                gone = {id(sp) for sp in drop}
                self._crane_freed = list(getattr(self, '_crane_freed', [])) + ground
                self.supports = [sp for sp in self.supports
                                 if id(sp) not in gone]
                lifted_off = len(ground)
            # Once it is off the ground the lifted body is a PENDULUM, and a
            # linear analysis gives a pendulum no lateral stiffness: the
            # restoring force of a hanging load is a geometric, second-order
            # term this solver does not carry. Three modes therefore have
            # ZERO stiffness -- swing in x, swing in y, and spin about the
            # vertical through the hook. Measured on the default grid:
            # condition number 6.2e16, with singular values dropping from
            # 1.3e+04 to 1.9e-06 and 5.0e-08.
            #
            # The trap is that it does not reliably FAIL, because
            # _beam_gauss_solve judges a system by its solution's RESIDUAL,
            # which depends on the loads and not only on the matrix. Under a
            # plain area load this returned a clean, plausible answer; with
            # four rod span loads added -- changing the loads and not the
            # matrix -- the same model returned displacements of 1.2e10 m,
            # and equilibrium checks pass either way. A real rig steadies the
            # load with tag lines while it hangs, and so does this: three
            # restraints, the minimum that removes all three modes and no
            # more. See crane_steady_lines for which, and why each.
            steady = sg.crane_steady_lines(self.nodes, targets)
            for node, dof in steady:
                self.supports.append({'node': node, 'dofs': {dof: True}})
            # every crane's tag lines, not just the last one's, or Clear
            # leaves the earlier ones behind
            self._crane_tag = list(getattr(self, '_crane_tag', None) or []) + \
                [{'node': n, 'dof': d} for n, d in steady]
            tag = steady

        self.results = None
        self.member_checks = None
        self._me_maybe_refresh_topology()
        # What this lift is, for the crane report: its code, the joints the
        # slings hook onto, the rods of the piece it lifts.
        wll, spec = self._crane_cable_capacity()
        self._crane_lifts = list(getattr(self, '_crane_lifts', None) or []) + [{
            'code': code, 'picks': list(targets), 'rods': list(lift_rods),
            'group': lift_gid, 'hook': hook, 'anchor': anchor,
            'wll_kN': wll, 'cable_spec': spec}]

        # Off its supports, the lifted body has to be stable ON ITS OWN, and
        # a grid often is not: the default square-on-square grid has a free-
        # edge mechanism that its perimeter supports were hiding (a free
        # body with 7 zero modes, not 6). Hung from three corners, or from a
        # patch in the middle, that part has nothing holding it and the
        # solve is singular. Say so now, and show where, instead of leaving
        # it to a generic error at Analyze.
        # Checked on the lifted piece with its own crane -- small, so the
        # search always runs -- and on every lift, not only one that took
        # supports away: a piece that had none (a truss lying in the file to
        # be lifted) is just as able to swing loose. A flat truss hung from
        # slings in its own plane can turn about them, and this is where
        # that is caught rather than as a singular matrix at Analyze.
        try:
            loose = self._crane_loose_nodes(code, lift_rods)
        except Exception:
            loose = []
        used = (sg.crane_auto_rise(self.nodes, targets, cog) if rise is None
                else rise)
        n_struct = sum(1 for m in self.members
                       if m.get('role') not in slift.CRANE_ROLES)
        what = (f'group {self._group_display_name(lift_gid)}'
                if lift_gid is not None else 'the piece under the hook')
        stays = n_struct - len(lift_rods)
        self._set_addon_note(
            f'{sac.describe(code)} lifts {what} ({len(lift_rods)} rods)'
            + (f'; the other {stays} rod(s) stay on their supports. '
               if stays > 0 else '. ')
            + f'On {len(targets)} node(s): {len(targets)} tension-only '
            f'cable(s) to a hook {used:.2f} m up over the piece\'s centre of '
            f'gravity, a {mast:.2f} m mast, and a '
            f'fixed top at node {anchor}. A cable goes slack rather than push, so '
            f'Analyze solves it in passes.'
            + (f' The model is off its own {lifted_off} support(s) -- it is '
               f'hanging from the crane, and Clear every crane puts them back.'
               if lifted_off else '')
            + ((' Tag lines steady it: '
                + ', '.join(f'{d} at node {n}' for n, d in tag)
                + '. A hanging load swings and spins, and a linear solve '
                  'gives those no stiffness at all, so without them the '
                  'answer is numerically meaningless. In a symmetric lift '
                  'they carry almost nothing -- check their reactions.')
               if tag else
               ' The model still stands on its own supports, so the slings may '
               'well read zero: the ground is a stiffer path than a cable.'))
        off = (slift.cog_outside_picks(self.nodes, targets, cog)
               if cog is not None else 0.0)
        tips = ''
        if off > CRANE_COG_TOL:
            tips = ('The piece\'s centre of gravity, at x %.2f, y %.2f, is '
                    '%.2f m outside the pick points seen from above. The hook '
                    'hangs over it, so the slings on the far side would have '
                    'to push: they go slack, the piece tips, and Analyze will '
                    'say so. Pick points around the centre of gravity -- the '
                    'outer corners of the piece usually are.'
                    % (cog[0], cog[1], off))
        warn = None
        if loose:
            self.selected_nodes = set(loose)
            self.selected_members = set()
            self.selected_member = None
            self._sync_selection_fields()
            flat = self._picks_in_one_plane_with_hook(targets, hook)
            self._set_addon_note(
                'Hung from these %d point(s), part of the lifted piece can '
                'move with no stiffness at all -- %d node(s), selected on the '
                'drawing -- so Analyze will refuse it. '
                % (len(targets), len(loose))
                + ('The slings all hang in one plane, so the piece can turn '
                   'about them like a flag: hook onto points off that plane '
                   '(a flat truss needs a spreader or a second line), or '
                   'lift it together with what holds it upright.'
                   if flat else
                   'On the ground its supports held them; in the air '
                   'nothing does. Hook slings to that part too (the corners '
                   'usually do it), or untick "Take it off its own '
                   'supports".')
                + (' ' + tips if tips else ''))
            warn = ('The lifted model is a mechanism: %d node(s) have '
                    'nothing holding them -- they are selected.' % len(loose)
                    + (' And the piece would tip.' if tips else ''))
        elif tips:
            self._set_addon_note(tips)
            warn = ('%s: the centre of gravity is outside the pick points '
                    '-- the piece would tip.' % sac.describe(code))
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

    def _crane_loose_nodes(self, code, lift_rods):
        """Nodes of the lifted piece (with crane `code`) that can move with
        no stiffness, as model node numbers; [] if it hangs stable."""
        rods = sorted(set(lift_rods) | set(sac.index(self.members)
                                           .get(code, ())))
        ns = sorted(slift.nodes_of(self.members, rods))
        idx = {n: k for k, n in enumerate(ns)}
        sub_n = [self.nodes[n] for n in ns]
        sub_m = [dict(self.members[j], a=idx[self.members[j]['a']],
                      b=idx[self.members[j]['b']]) for j in rods]
        sub_s = [dict(sp, node=idx[sp['node']]) for sp in self.supports
                 if sp.get('node') in idx]
        return [ns[k] for k in sm.mechanism(sub_n, sub_m, sub_s)]

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

    def _crane_meta(self):
        """{code: what the crane report needs to know about each lift} --
        what it lifts (re-read now, so it follows edits made since), and
        the cables' capacity."""
        out = {}
        for lift in getattr(self, '_crane_lifts', None) or []:
            code = lift.get('code')
            gid = lift.get('group')
            if gid is not None and sgp.find(self.groups, gid):
                rods = sorted(sgp.rods_of(self.groups, gid, deep=True))
                what = f'group {self._group_display_name(gid)}'
            else:
                picks = [p for p in lift.get('picks', ())
                         if p < len(self.nodes)]
                rods = slift.connected_piece(self.members, picks)
                what = 'the piece under the hook'
            out[code] = {'rods': rods, 'what': what,
                         'wll_kN': lift.get('wll_kN'),
                         'cable_spec': lift.get('cable_spec', '')}
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
        """id() of each support that belongs to a crane: a mast top, or a
        tag line one of them added."""
        tops = set()
        for m in self.members:
            if m.get('role') == 'crane_mast':
                tops.update((m['a'], m['b']))
        tags = {(t['node'], t['dof']) for t in
                (getattr(self, '_crane_tag', None) or [])}
        own = set()
        for sp in self.supports:
            if sp.get('node') in tops:
                own.add(id(sp))
                continue
            d = sp.get('dofs') or {}
            if len(d) == 1 and not sp.get('type') and \
                    (sp.get('node'), next(iter(d))) in tags:
                own.add(id(sp))
        return own

    def _clear_cable_cranes(self):
        n = self._strip_members(self.CRANE_ROLES, 'clear cranes')
        if not n:
            self._set_addon_note('No cranes to clear.')
            return
        # The mast's own fixed top goes with it: _strip_members drops the
        # orphaned hook and anchor nodes and rebuilds supports through its
        # own remap, keeping only those whose node survived.
        #
        # The model's OWN supports are a different matter. The lift took
        # them away, so putting the crane back in the box has to put them
        # back, or the next Analyze reports a mechanism for a reason nothing
        # on screen explains -- the model is on the ground again with
        # nothing holding it.
        # The tag line goes with the crane. Its node is an ordinary grid
        # node, so _strip_members' remap keeps it -- it would otherwise be
        # left holding a translation nothing on screen explains, and the
        # model back on the ground with one corner pinned sideways.
        tagged = getattr(self, '_crane_tag', None) or []
        if tagged:
            drop = {(t['node'], t['dof']) for t in tagged}
            self.supports = [
                sp for sp in self.supports
                if not any(sp.get('node') == n and sp.get('dofs') == {d: True}
                           for n, d in drop)]
            self._crane_tag = None
        self._crane_lifts = []
        back = self._restore_crane_supports()
        self._me_maybe_refresh_topology()
        self._set_addon_note(
            f'{n} crane member(s) removed.'
            + (f' {back} support(s) handed back -- the model is back on the '
               f'ground.' if back else ''))
        self._refresh_all()

    def _restore_crane_supports(self):
        """Put back the supports the lift took away.

        The entries themselves are kept, not just the node numbers: what
        KIND of support each one was is not recoverable from the mesh
        afterwards. Same reasoning as _restore_freed_supports for columns,
        and kept separate from it so clearing one add-on cannot hand back
        the other's.
        """
        have = {sp['node'] for sp in self.supports}
        back = 0
        for entry in getattr(self, '_crane_freed', []):
            node = entry.get('node')
            if node is not None and 0 <= node < len(self.nodes) and node not in have:
                self.supports.append(dict(entry))
                self._support_candidates = sorted(
                    set(self._support_candidates) | {node})
                have.add(node)
                back += 1
        self._crane_freed = []
        return back

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
