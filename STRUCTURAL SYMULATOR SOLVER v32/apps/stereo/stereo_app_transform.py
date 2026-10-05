"""Rotate and mirror the selection (roadmap v2 3.4) -- the panel and keys.

The geometry is stereo_transform's. What is here is which nodes move, and
the model state that has to travel with them:

  * WHICH nodes: the selected nodes and the ends of the selected rods,
    through the same rule a drag uses (stereo_groups.move_plan), so a node
    of a locked group turns its whole group, and a group glued to another by
    a shared joint does not turn at all.
  * A mirrored COPY also copies what hangs on its originals: supports, and
    the roof-load tributary area, so the new half is supported and loaded
    like the old. Point loads are copied UNCHANGED, not reflected -- a
    mirror across a horizontal plane would otherwise turn gravity upward.
  * Turning or mirroring in place moves geometry only; loads stay as they
    are, for the same reason.
"""
import tkinter as tk
from tkinter import messagebox, ttk

from apps.stereo import stereo_transform as st
from apps.stereo import stereo_groups as sgp
from apps.stereo.stereo_app_constants import BG, PANEL_TEXT_W
from apps.stereo.stereo_app_shell import HINT_FG


class StereoTransformMixin:

    # ── the panel ──────────────────────────────────────────────────────────

    def _build_transform_panel(self, parent):
        box = tk.LabelFrame(parent, text='Rotate / mirror selection', bg=BG,
                            font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=(4, 8))
        tk.Label(box, text='Turns or flips the selected nodes (and the ends '
                           'of selected rods) about their own middle. The '
                           'arrow keys pick the axis: ←→ X, ↑↓ Y, PgUp/PgDn '
                           'Z. Keys: R rotate, M mirror, Shift+M mirror a '
                           'copy. A locked group turns whole.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W).pack(anchor='w', padx=6, pady=(2, 4))
        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=6)
        tk.Label(row, text='Axis:', bg=BG,
                 font=('Helvetica', 8, 'bold')).pack(side='left')
        for ax in ('X', 'Y', 'Z'):
            tk.Radiobutton(row, text=ax, value=ax, variable=self.tx_axis,
                           bg=BG, font=('Helvetica', 8)
                           ).pack(side='left', padx=(2, 0))
        prow = tk.Frame(box, bg=BG)
        prow.pack(fill='x', padx=6, pady=(3, 0))
        tk.Label(prow, text='Mirror plane:', bg=BG,
                 font=('Helvetica', 8)).pack(side='left')
        ttk.Combobox(prow, textvariable=self.tx_plane, state='readonly',
                     width=20, values=list(self.TX_PLANES)
                     ).pack(side='left', padx=(3, 0))
        tk.Label(row, text='  Angle (°):', bg=BG,
                 font=('Helvetica', 8)).pack(side='left')
        self.tx_angle = tk.DoubleVar(value=90.0)
        self._tx_angle_entry = tk.Entry(row, textvariable=self.tx_angle,
                                        width=6)
        self._tx_angle_entry.pack(side='left', padx=(2, 0))
        self._tx_angle_entry.bind('<Return>', lambda _e: self._tx_rotate())
        btns = tk.Frame(box, bg=BG)
        btns.pack(fill='x', padx=6, pady=(4, 6))
        tk.Button(btns, text='Rotate', font=('Helvetica', 8),
                  command=self._tx_rotate).pack(side='left', expand=True,
                                                fill='x')
        tk.Button(btns, text='Mirror', font=('Helvetica', 8),
                  command=self._tx_mirror).pack(side='left', expand=True,
                                                fill='x', padx=(3, 0))
        tk.Button(btns, text='Mirror a copy', font=('Helvetica', 8),
                  command=lambda: self._tx_mirror(copy=True)
                  ).pack(side='left', expand=True, fill='x', padx=(3, 0))

    # ── keys ───────────────────────────────────────────────────────────────

    def _tx_key_rotate(self, _event=None):
        """R: go to the angle box, so typing the angle and Enter rotates."""
        if not self._tx_selected_nodes():
            return
        self._set_mode('build')
        self._tx_angle_entry.focus_set()
        self._tx_angle_entry.select_range(0, 'end')
        self._set_status('Rotate about %s: type the angle and press Enter.'
                         % self.tx_axis.get(), 'ok')
        return 'break'

    def _tx_key_mirror(self, _event=None):
        self._tx_mirror()
        return 'break'

    def _tx_key_mirror_copy(self, _event=None):
        self._tx_mirror(copy=True)
        return 'break'

    # Where the mirror plane sits along the active axis. "auto" is the one
    # people mean: flipping IN PLACE turns the selection over its own
    # middle, while a mirrored COPY goes alongside -- through the middle it
    # would land on top of its original, which is never what is wanted.
    TX_PLANES = ('auto', 'selection middle', 'selection + edge',
                 'selection − edge', 'origin (0)')

    def _tx_pivot(self, ids, axis, copy):
        pts = [self.nodes[i] for i in ids]
        k = st.AXES[axis]
        mid = st.centroid(pts)
        choice = self.tx_plane.get()
        if choice == 'auto':
            choice = 'selection + edge' if copy else 'selection middle'
        at = {'selection middle': mid[k],
              'selection + edge': max(p[k] for p in pts),
              'selection − edge': min(p[k] for p in pts),
              'origin (0)': 0.0}[choice]
        pivot = list(mid)
        pivot[k] = at
        return tuple(pivot)

    # ── what moves ─────────────────────────────────────────────────────────

    def _tx_selected_nodes(self):
        ids = set(self.selected_nodes)
        for j in self.selected_members:
            if 0 <= j < len(self.members):
                ids.add(self.members[j]['a'])
                ids.add(self.members[j]['b'])
        return sorted(i for i in ids if 0 <= i < len(self.nodes))

    def _tx_moving_nodes(self, title):
        """The nodes a rotate or mirror in place may move, or None.

        A drag's rule: nodes of a locked group bring the whole group, and a
        group sharing a joint with another group is refused.
        """
        ids = self._tx_selected_nodes()
        if not ids:
            messagebox.showinfo(title, 'Select the nodes or rods to %s first.'
                                % title.lower())
            return None
        if not self.groups:
            return ids
        plan = sgp.move_plan(self.groups, self.members, ids,
                             self._editing_gid())
        if plan['conflicts']:
            self._refuse_move(plan, quiet=False)
            return None
        return plan['nodes'] or None

    # ── the three operations ──────────────────────────────────────────────

    def _tx_rotate(self, angle=None, axis=None):
        try:
            angle = float(self.tx_angle.get() if angle is None else angle)
        except (tk.TclError, ValueError):
            messagebox.showerror('Rotate', 'Enter the angle in degrees.')
            return False
        axis = axis or self.tx_axis.get()
        ids = self._tx_moving_nodes('Rotate')
        if not ids or angle == 0.0:
            return False
        self._push_undo('rotate selection')
        self.nodes = st.rotated(self.nodes, ids, axis, angle)
        self._tx_done('Rotated %d node(s) %g° about %s.'
                      % (len(ids), angle, axis))
        return True

    def _tx_mirror(self, copy=False, axis=None):
        axis = axis or self.tx_axis.get()
        if not copy:
            ids = self._tx_moving_nodes('Mirror')
            if not ids:
                return False
            self._push_undo('mirror selection')
            self.nodes = st.mirrored(self.nodes, ids, axis,
                                     self._tx_pivot(ids, axis, copy=False))
            self._tx_done('Mirrored %d node(s) across the plane square to %s.'
                          % (len(ids), axis))
            return True

        ids = self._tx_selected_nodes()
        if not ids:
            messagebox.showinfo('Mirror a copy',
                                'Select the nodes or rods to copy first.')
            return False
        if self._editing_gid() is not None:
            inside = sgp.editable_nodes(self.groups, self.members,
                                        self._editing_gid())
            ids = [i for i in ids if i in inside]
        if not ids:
            return False
        new_nodes, new_members, node_map, new_rods = st.mirror_copy(
            self.nodes, self.members, ids, axis,
            pivot=self._tx_pivot(ids, axis, copy=True),
            member_ids=sorted(self.selected_members))
        added = len(new_nodes) - len(self.nodes)
        if not added and not new_rods:
            self._set_status('The mirrored copy lands exactly on what is '
                             'already there -- nothing to add.', 'ok')
            return False
        self._push_undo('mirror a copy')
        n_before = len(self.members)
        self.nodes, self.members = new_nodes, new_members
        fresh = {old: new for old, new in node_map.items() if new >= len(
            self.nodes) - added}
        # What hangs on the originals comes with the copy.
        sup_by_node = {s['node']: s for s in self.supports}
        for old, new in fresh.items():
            if old in sup_by_node and new not in sup_by_node:
                self.supports.append(dict(sup_by_node[old], node=new))
        if self._load_nodes:
            for old, new in fresh.items():
                if old in self._load_nodes:
                    self._load_nodes[new] = self._load_nodes[old]
        for ld in [ld for ld in self.loads if ld['node'] in fresh]:
            self.loads.append(dict(ld, node=fresh[ld['node']]))
        self._adopt_new_rods(n_before)
        self.selected_nodes = set(fresh.values())
        self.selected_members = set(new_rods)
        self.selected_member = None
        self._tx_done('Mirrored a copy across the plane square to %s: %d new '
                      'node(s), %d new rod(s). Supports, roof-load areas and '
                      'point loads were copied; point loads unreflected.'
                      % (axis, added, len(new_rods)))
        return True

    def _tx_done(self, text):
        self.results = None
        self.member_checks = None
        self._refresh_all()
        self._set_status(text, 'ok')
