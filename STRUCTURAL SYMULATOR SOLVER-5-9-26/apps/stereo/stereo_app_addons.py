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

    def _add_column(self):
        targets = sorted(self.selected_nodes)
        if len(targets) < 3:
            messagebox.showerror('Column',
                                 'Select at least 3 nodes (a lasso box) for the capital '
                                 'to attach to first.')
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
        self._apply_sections(members=self.members, redraw=False)
        self.selected_nodes = set(bases)
        self.results = None
        self.member_checks = None
        self._refresh_all()

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
