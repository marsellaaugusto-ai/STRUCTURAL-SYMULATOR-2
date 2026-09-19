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
        self._push_undo('add column')
        self.nodes, self.members = nodes, members
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
        self._set_column_note(freed, bases)
        self._apply_sections(members=self.members, redraw=False)
        self.selected_nodes = set(bases)
        self.results = None
        self.member_checks = None
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
        self._apply_sections(members=self.members, redraw=False)
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
        self._apply_sections(members=self.members, redraw=False)
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

    def _set_column_note(self, freed, bases):
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
        self._push_undo('add reinforcement beam')
        self.nodes, self.members = nodes, members
        self._apply_sections(members=self.members, redraw=False)
        self.selected_nodes = set(apex)
        self.results = None
        self.member_checks = None
        self._refresh_all()
