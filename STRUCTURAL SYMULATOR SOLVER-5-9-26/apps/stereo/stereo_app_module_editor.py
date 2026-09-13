"""The Module Editor: a panel that finds the repeating CELL of the current
mesh, groups congruent cells into roles, and applies an edit to every cell
of a role at once.

Two linked views are drawn here: an orbit-able 3D view of the selected
module (with CAD-style dimension lines to its neighbouring ring), and a
flattened (u, v) editing canvas where nodes are dragged and members are
toggled. Both are plain Tk canvases drawn by hand -- see _me_render_3d and
_me_render.

The cell/role mathematics itself (detection, congruence classification,
local frames, and the role-wide propagating edits) lives in
stereo_geometry_cells.py; this module is the UI over it.
"""
import math
import tkinter as tk
from tkinter import ttk, messagebox

from common import ZoomCanvas

from apps.stereo import stereo_geometry as sg
from apps.stereo.stereo_app_colors import _lerp_hex
from apps.stereo.stereo_app_constants import (
    BG, MODULE_PANEL_W, MODULE_CANVAS_SIZE, MODULE_RING_COLOR,
    MODULE_APEX_EDGE_COLOR, MODULE_APEX_NODE_COLOR, MODULE_FACE_FILL,
    MODULE_DIM_COLOR,
)


class StereoModuleEditorMixin:
    """Module Editor panel: cell/role detection display and role-wide edits."""

    def _build_module_editor_panel(self, parent):
        """The right-hand 'Module Editor' panel: shows one representative
        cell of the grid's own dominant repeating shape (or, via the
        keystone list below, a one-off shape like a dome's apex fan or a
        vault's end panel), locally flattened onto that cell's own (u, v)
        plane -- see stereo_geometry.cell_local_basis -- so it reads the
        same whether the real grid is flat or wrapped around a dome.
        Every edit here (drag a node, set/lock a rod's length, toggle a
        rod on/off, rescale) is applied immediately and PROPAGATED to
        every other cell sharing that same role -- see
        stereo_geometry.move_role_node/set_role_member_length/
        toggle_role_member/rescale_role_cells for exactly what that means
        for a corner shared between cells, and for a locked rod."""
        tk.Label(parent, text='Module Editor', bg=BG, font=('Helvetica', 10, 'bold')
                ).pack(anchor='w', padx=6, pady=(6, 2))

        role_row = tk.Frame(parent, bg=BG)
        role_row.pack(fill='x', padx=6, pady=2)
        tk.Label(role_row, text='Editing:', bg=BG, font=('Helvetica', 9)).pack(side='left')
        self.me_role_var = tk.StringVar(master=parent, value='')
        self.me_role_combo = ttk.Combobox(role_row, textvariable=self.me_role_var,
                                          state='readonly', width=22)
        self.me_role_combo.pack(side='left', padx=(4, 0))
        self.me_role_combo.bind('<<ComboboxSelected>>', lambda e: self._me_on_role_picked())

        self.me_warning = tk.Label(parent, text='', bg='#fdf0e0', fg='#a3241a',
                                   font=('Helvetica', 8), wraplength=MODULE_PANEL_W - 20,
                                   justify='left')

        # A separate, ABOVE (not overlaid on) the flattened editing view
        # below it: a true 3D rendering of the same cell -- its actual
        # geometry, topology (exactly which corners are connected) and
        # proportions, using the model's own real (x, y, z) coordinates
        # rather than the flattened view's own local (u, v) plane. Mouse-
        # interactive (left-drag orbits, wheel zooms, middle-drag pans via
        # ZoomCanvas) so a complex module can be inspected from any angle,
        # not just one fixed view -- separate camera state from the main
        # canvas's own (self.azimuth/self.elevation) so orbiting one never
        # moves the other.
        tk.Label(parent, text='3D module (drag to orbit, wheel to zoom):', bg=BG,
                fg='#666', font=('Helvetica', 8)).pack(anchor='w', padx=6, pady=(2, 0))
        self.me3d_azimuth = 35.0
        self.me3d_elevation = 22.0
        self._me3d_orbit_start = None
        self.me3d_zc = ZoomCanvas(parent, width=MODULE_CANVAS_SIZE, height=MODULE_CANVAS_SIZE,
                                  bg='#ffffff', bd=1, relief='solid')
        self.me3d_zc.pack(padx=6, pady=(2, 4))
        self.me3d_zc._on_zoom_changed = self._me_render_3d
        self.me3d_canvas = self.me3d_zc.canvas
        self.me3d_canvas.bind('<ButtonPress-1>', self._me3d_orbit_press)
        self.me3d_canvas.bind('<B1-Motion>', self._me3d_orbit_motion)
        self.me3d_canvas.bind('<ButtonRelease-1>', self._me3d_orbit_release)

        self.me_canvas = tk.Canvas(parent, width=MODULE_CANVAS_SIZE, height=MODULE_CANVAS_SIZE,
                                   bg='#ffffff', bd=1, relief='solid')
        self.me_canvas.pack(padx=6, pady=(4, 2))
        self.me_canvas.bind('<ButtonPress-1>', self._me_on_press)
        self.me_canvas.bind('<B1-Motion>', self._me_on_drag)
        self.me_canvas.bind('<ButtonRelease-1>', self._me_on_release)

        self.me_info = tk.Label(parent, text='(no module to show yet -- generate a grid)',
                                bg=BG, fg='#666', font=('Helvetica', 8),
                                wraplength=MODULE_PANEL_W - 20, justify='left')
        self.me_info.pack(fill='x', padx=6, pady=(0, 4))

        # -- node editing (shown when a node is selected) --
        self.me_node_box = tk.LabelFrame(parent, text='Selected node', bg=BG,
                                         font=('Helvetica', 8, 'bold'))
        tk.Label(self.me_node_box, text='Drag it above, or nudge by (m):', bg=BG,
                font=('Helvetica', 8), fg='#666').pack(anchor='w', padx=4, pady=(2, 0))
        self.me_du = tk.DoubleVar(master=parent, value=0.0)
        self.me_dv = tk.DoubleVar(master=parent, value=0.0)
        self.me_dn = tk.DoubleVar(master=parent, value=0.0)
        for label, var in (('du:', self.me_du), ('dv:', self.me_dv), ('dn:', self.me_dn)):
            row = tk.Frame(self.me_node_box, bg=BG)
            row.pack(fill='x', padx=4, pady=1)
            tk.Label(row, text=label, bg=BG, width=4, anchor='w', font=('Helvetica', 8)
                    ).pack(side='left')
            tk.Entry(row, textvariable=var, width=8, font=('Helvetica', 8)).pack(side='left')
        tk.Button(self.me_node_box, text='Move', command=self._me_apply_move
                 ).pack(padx=4, pady=(2, 4), anchor='w')

        # -- edge editing (shown when a rod is selected) --
        self.me_edge_box = tk.LabelFrame(parent, text='Selected rod', bg=BG,
                                         font=('Helvetica', 8, 'bold'))
        len_row = tk.Frame(self.me_edge_box, bg=BG)
        len_row.pack(fill='x', padx=4, pady=1)
        tk.Label(len_row, text='Length (m):', bg=BG, font=('Helvetica', 8)).pack(side='left')
        self.me_length = tk.DoubleVar(master=parent, value=0.0)
        tk.Entry(len_row, textvariable=self.me_length, width=8, font=('Helvetica', 8)
                ).pack(side='left', padx=(4, 0))
        tk.Button(self.me_edge_box, text='Set length', command=self._me_apply_length
                 ).pack(padx=4, pady=(2, 2), anchor='w')
        self.me_locked_var = tk.BooleanVar(master=parent, value=False)
        tk.Checkbutton(self.me_edge_box, text='Lock this rod\'s length', bg=BG,
                      variable=self.me_locked_var, font=('Helvetica', 8),
                      command=self._me_toggle_lock).pack(anchor='w', padx=4, pady=(0, 4))

        # -- toggle-diagonal editing (shown when a potential rod is selected) --
        self.me_toggle_box = tk.LabelFrame(parent, text='Potential rod', bg=BG,
                                           font=('Helvetica', 8, 'bold'))
        tk.Label(self.me_toggle_box, text='This diagonal does not exist yet.', bg=BG,
                font=('Helvetica', 8), fg='#666').pack(anchor='w', padx=4, pady=(2, 0))
        tk.Button(self.me_toggle_box, text='Add it (every matching cell)',
                 command=self._me_apply_toggle).pack(padx=4, pady=(2, 4), anchor='w')

        # -- whole-module rescale --
        rescale_box = tk.LabelFrame(parent, text='Rescale this module', bg=BG,
                                    font=('Helvetica', 8, 'bold'))
        rescale_box.pack(fill='x', padx=6, pady=4)
        tk.Label(rescale_box, text='Keeps its current shape, just bigger/smaller.', bg=BG,
                font=('Helvetica', 8), fg='#666', wraplength=MODULE_PANEL_W - 30,
                justify='left').pack(anchor='w', padx=4, pady=(2, 0))
        rrow = tk.Frame(rescale_box, bg=BG)
        rrow.pack(fill='x', padx=4, pady=(2, 4))
        tk.Label(rrow, text='Factor:', bg=BG, font=('Helvetica', 8)).pack(side='left')
        self.me_rescale = tk.DoubleVar(master=parent, value=1.0)
        tk.Entry(rrow, textvariable=self.me_rescale, width=6, font=('Helvetica', 8)
                ).pack(side='left', padx=(4, 4))
        tk.Button(rrow, text='Apply', command=self._me_apply_rescale).pack(side='left')

        # -- keystone / singular modules --
        keystone_box = tk.LabelFrame(parent, text='Keystone / singular modules', bg=BG,
                                     font=('Helvetica', 9, 'bold'))
        keystone_box.pack(fill='x', padx=6, pady=(4, 8))
        tk.Label(keystone_box, text="Shapes that occur only once, or far less often than "
                               "the grid's main module (an apex fan, an end panel...). "
                               "Editing one of these can break the topology or coordinate "
                               "system in ways that don't apply anywhere else.",
                bg=BG, fg='#666', font=('Helvetica', 8), wraplength=MODULE_PANEL_W - 30,
                justify='left').pack(anchor='w', padx=4, pady=(2, 2))
        self.me_keystone_list = tk.Listbox(keystone_box, height=5, font=('Helvetica', 8),
                                           exportselection=False)
        self.me_keystone_list.pack(fill='x', padx=4, pady=(0, 4))
        self.me_keystone_list.bind('<<ListboxSelect>>', lambda e: self._me_on_keystone_picked())

    def _me_maybe_refresh_topology(self):
        """Recompute cells/roles only when the node/member COUNT has
        actually changed since the last check -- a cheap fingerprint that
        catches every real topology change this tab makes (generate,
        delete, undo/redo, add-on features, this editor's own edits)
        without re-running find_cells (O(members * degree^2)) on every
        _refresh_all call, most of which touch neither."""
        fingerprint = (len(self.nodes), len(self.members))
        if fingerprint == getattr(self, '_me_fingerprint', None):
            return
        self._me_fingerprint = fingerprint
        self._me_refresh_topology()

    def _me_refresh_topology(self):
        if not self.nodes:
            self._me_cells, self._me_roles = [], {}
            self._me_populate_role_list()
            self._me_render()
            return
        self._me_cells = sg.find_cells(self.nodes, self.members)
        classified = sg.classify_cell_roles(self.nodes, self._me_cells)
        self._me_roles = classified['roles']
        if self._me_role_id not in self._me_roles:
            self._me_role_id = 0 if self._me_roles else None
        self._me_selection = None
        self._me_populate_role_list()
        self._me_render()

    def _me_role_label(self, role_id):
        n = len(self._me_roles.get(role_id, ()))
        shape = 'triangle' if self._me_cells and self._me_roles.get(role_id) and \
            len(self._me_cells[self._me_roles[role_id][0]]['nodes']) == 3 else 'quad'
        tag = ' (dominant)' if role_id == 0 else ''
        return f'Module {role_id} -- {shape}, {n} cell(s){tag}'

    def _me_populate_role_list(self):
        role_ids = sorted(self._me_roles)
        labels = [self._me_role_label(r) for r in role_ids]
        self.me_role_combo['values'] = labels
        if self._me_role_id is not None and self._me_role_id in role_ids:
            self.me_role_var.set(self._me_role_label(self._me_role_id))
        elif labels:
            self._me_role_id = role_ids[0]
            self.me_role_var.set(labels[0])
        else:
            self.me_role_var.set('')

        self.me_keystone_list.delete(0, tk.END)
        for r in role_ids:
            if r == 0:
                continue
            self.me_keystone_list.insert(tk.END, self._me_role_label(r))

    def _me_on_role_picked(self):
        role_ids = sorted(self._me_roles)
        try:
            idx = self.me_role_combo['values'].index(self.me_role_var.get())
            self._me_role_id = role_ids[idx]
        except (ValueError, IndexError):
            return
        self._me_selection = None
        self._me_render()

    def _me_on_keystone_picked(self):
        sel = self.me_keystone_list.curselection()
        if not sel:
            return
        role_ids = [r for r in sorted(self._me_roles) if r != 0]
        role_id = role_ids[sel[0]]
        self._me_role_id = role_id
        self.me_role_var.set(self._me_role_label(role_id))
        self._me_selection = None
        self._me_render()

    # -- rendering --------------------------------------------------------
    def _me_current_cell_nodes(self):
        if self._me_role_id is None or self._me_role_id not in self._me_roles:
            return None
        idxs = self._me_roles[self._me_role_id]
        if not idxs:
            return None
        return self._me_cells[idxs[0]]['nodes']

    def _me3d_cell_nodes(self):
        """The 3D panel always prefers the canonical QUAD ring (the plain
        top-chord square, whose own apex reconstructs the full inverted-
        pyramid module -- see _me_ring_context) even when a TRIANGULAR
        face role is what's currently selected for the flat 2D editor --
        so orbiting the 3D view always shows the same complete module
        regardless of which of its 4 triangular faces happens to be
        selected there. Falls back to the current selection's own ring
        when no such quad exists anywhere sharing an edge with it (e.g. a
        single-layer triangulated dome, which has no pyramid structure to
        reconstruct)."""
        cell_nodes = self._me_current_cell_nodes()
        if cell_nodes is None or len(cell_nodes) != 3:
            return cell_nodes
        current = set(cell_nodes)
        for cell in self._me_cells:
            nodes = cell['nodes']
            if len(nodes) == 4 and len(current & set(nodes)) >= 2:
                return nodes
        return cell_nodes

    def _me_to_screen_fn(self, cell_nodes):
        coords = [sg.cell_local_coords(self.nodes, cell_nodes, k)
                 for k in range(len(cell_nodes))]
        us = [p[0] for p in coords] + [0.0]
        vs = [p[1] for p in coords] + [0.0]
        umin, umax = min(us), max(us)
        vmin, vmax = min(vs), max(vs)
        span = max(umax - umin, vmax - vmin, 1e-6)
        size = MODULE_CANVAS_SIZE
        margin = 34
        scale = (size - 2 * margin) / span

        def to_screen(u, v):
            return (margin + (u - umin) * scale, size - margin - (v - vmin) * scale)
        return coords, to_screen, scale

    def _me_render(self):
        c = self.me_canvas
        c.delete('all')
        self.me_warning.pack_forget()
        self.me_node_box.pack_forget()
        self.me_edge_box.pack_forget()
        self.me_toggle_box.pack_forget()

        cell_nodes = self._me_current_cell_nodes()
        if cell_nodes is None:
            self.me_info.config(text='(no module to show yet -- generate a grid)')
            return
        if self._me_role_id != 0:
            self.me_warning.config(
                text='Editing a KEYSTONE/SINGULAR module: this shape does not repeat '
                    'elsewhere, so an edit here only affects this one spot -- but it can '
                    'still break the surrounding topology or coordinate system if the '
                    'result no longer fits where this cell sits in the grid.')
            self.me_warning.pack(fill='x', padx=6, pady=(0, 4), before=self.me3d_zc)

        n = len(cell_nodes)
        coords, to_screen, scale = self._me_to_screen_fn(cell_nodes)
        role_edges = {(i, (i + 1) % n) for i in range(n)}

        # potential (missing) diagonals -- quads only, and guaranteed
        # absent (see find_cells: a quad is never reported if either of
        # its diagonals already exists)
        if n == 4:
            for pos_a, pos_b in ((0, 2), (1, 3)):
                x0, y0 = to_screen(*coords[pos_a][:2])
                x1, y1 = to_screen(*coords[pos_b][:2])
                sel = self._me_selection == ('toggle', (pos_a, pos_b))
                c.create_line(x0, y0, x1, y1, fill='#bbbbbb', dash=(4, 3),
                             width=(3 if sel else 1.5),
                             tags=('toggle', f'toggle{pos_a}_{pos_b}'))

        # existing ring edges
        for i in range(n):
            pos_a, pos_b = i, (i + 1) % n
            x0, y0 = to_screen(*coords[pos_a][:2])
            x1, y1 = to_screen(*coords[pos_b][:2])
            locked = (self._me_role_id, min(pos_a, pos_b), max(pos_a, pos_b)) \
                in self._me_locked_edges
            sel = self._me_selection == ('edge', (pos_a, pos_b))
            color = '#a3241a' if locked else ('#1a6bbd' if sel else '#333333')
            c.create_line(x0, y0, x1, y1, fill=color, width=(4 if sel else 2.5),
                         tags=('edge', f'edge{pos_a}_{pos_b}'))

        # nodes, coloured by their own n (out-of-plane) coordinate --
        # amber toward +n, blue toward -n, greyish near the (u, v) plane
        max_n = max((abs(p[2]) for p in coords), default=0.0) or 1.0
        for k in range(n):
            x, y = to_screen(*coords[k][:2])
            frac = coords[k][2] / max_n
            if abs(frac) < 0.05:
                color = '#555555'
            elif frac > 0:
                color = _lerp_hex('#cccccc', '#c98a00', min(1.0, frac))
            else:
                color = _lerp_hex('#cccccc', '#1a6bbd', min(1.0, -frac))
            sel = self._me_selection == ('node', k)
            r = 8 if sel else 6
            c.create_oval(x - r, y - r, x + r, y + r, fill=color,
                         outline=('#e0522b' if sel else ''), width=2,
                         tags=('node', f'node{k}'))
            c.create_text(x, y - r - 8, text=str(k), font=('Helvetica', 8, 'bold'),
                         fill='#333333')

        self._me_render_3d()
        self._me_show_selection_info(cell_nodes, coords)

    # -- 3D module view: a separate, orbit-able panel ABOVE the flattened
    # (u, v) editing canvas, not overlaid on it -----------------------------
    ME3D_DEG_PER_PX = 0.4
    ME3D_DRAG_THRESHOLD_PX = 3

    def _me3d_orbit_press(self, event):
        self._me3d_orbit_start = (event.x, event.y, self.me3d_azimuth, self.me3d_elevation)

    def _me3d_orbit_motion(self, event):
        if self._me3d_orbit_start is None:
            return
        x0, y0, az0, el0 = self._me3d_orbit_start
        dx, dy = event.x - x0, event.y - y0
        if abs(dx) < self.ME3D_DRAG_THRESHOLD_PX and abs(dy) < self.ME3D_DRAG_THRESHOLD_PX:
            return
        self.me3d_azimuth = (az0 + dx * self.ME3D_DEG_PER_PX) % 360.0
        self.me3d_elevation = max(-89.0, min(89.0, el0 - dy * self.ME3D_DEG_PER_PX))
        self._me_render_3d()

    def _me3d_orbit_release(self, event):
        self._me3d_orbit_start = None

    def _me3d_project(self, x, y, z):
        """The exact same rotate-then-orthographic-project maths as the
        main 3D view's own _project (see its docstring), using this
        panel's OWN camera state (self.me3d_azimuth/elevation) -- entirely
        separate from the main canvas's own (self.azimuth/elevation) so
        orbiting one view never moves the other."""
        az = math.radians(self.me3d_azimuth)
        el = math.radians(self.me3d_elevation)
        xr = x * math.cos(az) - y * math.sin(az)
        yr = x * math.sin(az) + y * math.cos(az)
        zr = z
        y2 = yr * math.cos(el) - zr * math.sin(el)
        depth = yr * math.sin(el) + zr * math.cos(el)
        return xr, -depth, y2

    def _me_ring_context(self, cell_nodes):
        """{node_id: [ring node ids]} for every OTHER node in the model
        connected to EVERY one of the ring's own nodes. For the classic
        offset square-pyramid module (a top chord square ring, 4
        diagonals converging to ONE bottom apex), this is exactly that
        apex -- reconstructed from whichever ring the caller happens to
        have (normally always the quad face itself, since _me3d_cell_nodes
        prefers it over any one of the pyramid's 4 triangular side faces)
        -- rendered as part of the module's own SOLID (shaded triangular
        faces to the ring, not just thin lines).

        Purely topological (this model's own member connectivity), so it
        degrades gracefully for a family with no pyramid structure at all
        (e.g. a single-layer triangulated dome): nothing qualifies as an
        apex there.
        """
        ring = set(cell_nodes)
        n = len(cell_nodes)
        touching = {}
        for m in self.members:
            a, b = m['a'], m['b']
            if a in ring and b not in ring:
                touching.setdefault(b, set()).add(a)
            elif b in ring and a not in ring:
                touching.setdefault(a, set()).add(b)
        return {ext: sorted(ids) for ext, ids in touching.items() if len(ids) == n}

    def _me_draw_dimension(self, c, s0, s1, text, away_from, offset_px=15):
        """One CAD-style dimension: short dashed extension lines from each
        endpoint out past it, a double-headed arrow between them at that
        offset, and the length text centred on it -- the same convention
        the course's own guide sheet uses for its 2.50m/1.77m callouts.
        `away_from` is the screen point the dimension is pushed away from
        (typically the module's own on-screen centroid), so it always
        reads outside the solid rather than overlapping it."""
        dx, dy = s1[0] - s0[0], s1[1] - s0[1]
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return
        mx, my = (s0[0] + s1[0]) / 2.0, (s0[1] + s1[1]) / 2.0
        ox, oy = mx - away_from[0], my - away_from[1]
        onorm = math.hypot(ox, oy)
        if onorm < 1e-6:
            ox, oy = -dy / length, dx / length
        else:
            ox, oy = ox / onorm, oy / onorm
        ext_len = offset_px + 6
        for (sx, sy) in (s0, s1):
            c.create_line(sx, sy, sx + ox * ext_len, sy + oy * ext_len,
                         fill=MODULE_DIM_COLOR, width=1, dash=(2, 2))
        d0 = (s0[0] + ox * offset_px, s0[1] + oy * offset_px)
        d1 = (s1[0] + ox * offset_px, s1[1] + oy * offset_px)
        c.create_line(d0[0], d0[1], d1[0], d1[1], fill=MODULE_DIM_COLOR, width=1,
                     arrow=tk.BOTH, arrowshape=(6, 7, 3))
        tx, ty = (d0[0] + d1[0]) / 2.0 + ox * 11, (d0[1] + d1[1]) / 2.0 + oy * 11
        c.create_text(tx, ty, text=text, fill=MODULE_DIM_COLOR, font=('Helvetica', 8))

    def _me_render_3d(self):
        """A true 3D rendering of the CURRENT module as the actual
        repeating POLYHEDRON it belongs to -- not just its own flat ring
        (a triangle or quad silhouette), but the ring's own edges plus
        the ONE node elsewhere in the model connected to every one of
        them (see _me_ring_context), which for the classic offset
        square-pyramid module is exactly its bottom apex -- rendered as a
        shaded solid with the same real-world geometry (actual edge
        lengths/angles, never a simplified or assumed shape) the flat
        rendering always used. Dimensioned like the course's own
        reference drawings: dashed CAD-style callouts for two top-chord
        edge lengths, one diagonal's length, the module's own height, and
        the angle between two adjacent diagonals at the apex -- all
        computed from the model's actual coordinates, never hard-coded.
        Nodes use each node's REAL world (x, y, z) position, re-centred
        on the module's own centroid (ring + apex) so it always sits
        nicely in view, then this panel's own orbit camera (see
        _me3d_project) and ZoomCanvas's own pan/zoom."""
        c = self.me3d_canvas
        c.delete('all')
        cell_nodes = self._me3d_cell_nodes()
        if cell_nodes is None:
            return
        n = len(cell_nodes)
        apex = self._me_ring_context(cell_nodes)

        centroid_pts = [self.nodes[nid] for nid in cell_nodes] + \
            [self.nodes[e] for e in apex]
        m = len(centroid_pts)
        cx = sum(p[0] for p in centroid_pts) / m
        cy = sum(p[1] for p in centroid_pts) / m
        cz = sum(p[2] for p in centroid_pts) / m

        def proj_of(nid):
            p = self.nodes[nid]
            return self._me3d_project(p[0] - cx, p[1] - cy, p[2] - cz)

        ring_proj = [proj_of(nid) for nid in cell_nodes]
        apex_proj = {e: proj_of(e) for e in apex}

        all_proj = ring_proj + list(apex_proj.values())
        xs = [p[0] for p in all_proj]
        ys = [p[1] for p in all_proj]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)

        size = MODULE_CANVAS_SIZE
        inner_pad = 82   # extra room for the dimension callouts around the solid
        fit_scale = (size - 2 * inner_pad) / span

        def to_screen(px, py):
            wx = px * fit_scale
            wy = -py * fit_scale
            return self.me3d_zc.w2s(wx, wy)

        cx0, cy0 = self.me3d_zc.w2s(0.0, 0.0)
        # re-centre the ZoomCanvas's own pan so (0, 0) (the module's own
        # centroid) sits in the middle of the panel rather than its
        # top-left corner, the same correction the main canvas's own
        # _reset_view applies for the same reason.
        if not getattr(self, '_me3d_centered', False):
            self.me3d_zc.pan_x += (size / 2.0 - cx0) / self.me3d_zc.zoom
            self.me3d_zc.pan_y += (size / 2.0 - cy0) / self.me3d_zc.zoom
            self._me3d_centered = True

        ring_scr = [to_screen(*p[:2]) for p in ring_proj]
        apex_scr = {e: to_screen(*p[:2]) for e, p in apex_proj.items()}
        centroid_scr = (sum(p[0] for p in ring_scr) / n, sum(p[1] for p in ring_scr) / n)

        # -- solid faces first, underneath everything else -- one shaded
        # triangle per (ring edge, apex) pair, so a quad ring reconstructs
        # all 4 pyramid sides. A triangle ring IS itself one flat face of
        # the pyramid, so it gets shaded directly rather than needing an
        # apex of its own (its 3rd node already IS the apex in that case).
        if n == 3:
            c.create_polygon(ring_scr[0][0], ring_scr[0][1], ring_scr[1][0], ring_scr[1][1],
                            ring_scr[2][0], ring_scr[2][1], fill=MODULE_FACE_FILL, outline='')
        for e in apex:   # connects to EVERY ring node, by construction
            for i in range(n):
                a_scr, b_scr, e_scr = ring_scr[i], ring_scr[(i + 1) % n], apex_scr[e]
                c.create_polygon(a_scr[0], a_scr[1], b_scr[0], b_scr[1], e_scr[0], e_scr[1],
                                fill=MODULE_FACE_FILL, outline='')

        # -- ring edges --
        for i in range(n):
            ax, ay = ring_scr[i]
            bx, by = ring_scr[(i + 1) % n]
            c.create_line(ax, ay, bx, by, fill=MODULE_RING_COLOR, width=2.5)

        # any diagonal a quad currently has, drawn distinctly (thinner,
        # grey) from the ring edges -- exactly what find_cells' own
        # "never report a quad with an existing diagonal" rule guarantees
        # is the ONLY extra connectivity a cell can have beyond its ring
        if n == 4:
            for pos_a, pos_b in ((0, 2), (1, 3)):
                a_id, b_id = cell_nodes[pos_a], cell_nodes[pos_b]
                if any({m2['a'], m2['b']} == {a_id, b_id} for m2 in self.members):
                    ax, ay = ring_scr[pos_a]
                    bx, by = ring_scr[pos_b]
                    c.create_line(ax, ay, bx, by, fill='#888888', width=1.5, dash=(3, 2))

        # -- apex node: solid diagonal edges + a prominent marker --
        for e, ring_ids in apex.items():
            ex, ey = apex_scr[e]
            for i in range(n):
                rx, ry = ring_scr[i]
                c.create_line(rx, ry, ex, ey, fill=MODULE_APEX_EDGE_COLOR, width=2.2)
            c.create_oval(ex - 5, ey - 5, ex + 5, ey + 5, fill=MODULE_APEX_NODE_COLOR,
                         outline='')

        # -- ring nodes + numbers, drawn before dimensions so the dashed
        # extension lines and arrows read clearly on top --
        for i in range(n):
            px, py = ring_scr[i]
            c.create_oval(px - 5, py - 5, px + 5, py + 5, fill=MODULE_RING_COLOR, outline='')
            c.create_text(px, py - 12, text=str(i), font=('Helvetica', 8, 'bold'),
                         fill=MODULE_RING_COLOR)

        # -- dimensions: real edge lengths/angle, computed from the
        # model's own coordinates -- two adjacent top-chord edges (enough
        # to show the module is regular or not, without labelling every
        # redundant edge), one diagonal, the module's own height, and the
        # angle between two adjacent diagonals at the apex --
        for i in (0, 1) if n >= 2 else ():
            j = (i + 1) % n
            real_len = math.dist(self.nodes[cell_nodes[i]], self.nodes[cell_nodes[j]])
            self._me_draw_dimension(c, ring_scr[i], ring_scr[j], f'{real_len:.2f}m',
                                    centroid_scr)
        for e, ring_ids in apex.items():
            r0 = ring_ids[0]
            pos0 = cell_nodes.index(r0)
            real_len = math.dist(self.nodes[r0], self.nodes[e])
            self._me_draw_dimension(c, ring_scr[pos0], apex_scr[e], f'{real_len:.2f}m',
                                    centroid_scr)

            centroid_world = tuple(sum(self.nodes[nid][k] for nid in cell_nodes) / n
                                   for k in range(3))
            height = math.dist(centroid_world, self.nodes[e])
            # a plain vertical callout pinned to the LEFT of the whole
            # drawing (like the course's own "1.77m" side dimension),
            # rather than offset from the centroid-apex line itself --
            # that line runs right past the diagonals in screen space at
            # most orbit angles and the label would collide with theirs
            apex_x, apex_y = apex_scr[e]
            ring_top_y = min(p[1] for p in ring_scr)
            ring_top_x = next(p[0] for p in ring_scr if p[1] == ring_top_y)
            side_x = min(min(p[0] for p in ring_scr), apex_x) - 30
            c.create_line(ring_top_x, ring_top_y, side_x, ring_top_y,
                         fill=MODULE_DIM_COLOR, width=1, dash=(2, 2))
            c.create_line(apex_x, apex_y, side_x, apex_y,
                         fill=MODULE_DIM_COLOR, width=1, dash=(2, 2))
            c.create_line(side_x, ring_top_y, side_x, apex_y, fill=MODULE_DIM_COLOR,
                         width=1, arrow=tk.BOTH, arrowshape=(6, 7, 3))
            c.create_text(side_x - 6, (ring_top_y + apex_y) / 2.0, text=f'H={height:.2f}m',
                         fill=MODULE_DIM_COLOR, font=('Helvetica', 8), anchor='e')

            if n >= 2:
                r1 = ring_ids[1 % len(ring_ids)] if len(ring_ids) > 1 else ring_ids[0]
                if r1 != r0:
                    v0 = tuple(self.nodes[r0][k] - self.nodes[e][k] for k in range(3))
                    v1 = tuple(self.nodes[r1][k] - self.nodes[e][k] for k in range(3))
                    dot = sum(v0[k] * v1[k] for k in range(3))
                    n0 = math.sqrt(sum(v0[k] ** 2 for k in range(3)))
                    n1 = math.sqrt(sum(v1[k] ** 2 for k in range(3)))
                    if n0 > 1e-9 and n1 > 1e-9:
                        cos_ang = max(-1.0, min(1.0, dot / (n0 * n1)))
                        ang_deg = math.degrees(math.acos(cos_ang))
                        ax_, ay_ = apex_scr[e]
                        c.create_text(ax_, ay_ + 16, text=f'∠ {ang_deg:.1f}°',
                                     fill=MODULE_DIM_COLOR, font=('Helvetica', 8))

    def _me_show_selection_info(self, cell_nodes, coords):
        sel = self._me_selection
        if sel is None:
            role_txt = self._me_role_label(self._me_role_id)
            self.me_info.config(text=f'{role_txt}\nClick a node to move it, a rod to '
                                     'set/lock its length, or a dashed line to add it.')
            return
        kind, payload = sel
        if kind == 'node':
            k = payload
            u, v, n = coords[k]
            self.me_info.config(text=f'Node {k}: u={u:.3f}  v={v:.3f}  n={n:.3f} (m, '
                                     "in this cell's own local frame)")
            self.me_du.set(0.0); self.me_dv.set(0.0); self.me_dn.set(0.0)
            self.me_node_box.pack(fill='x', padx=6, pady=4, after=self.me_info)
        elif kind == 'edge':
            pos_a, pos_b = payload
            length = math.dist(self.nodes[cell_nodes[pos_a]], self.nodes[cell_nodes[pos_b]])
            locked = (self._me_role_id, min(pos_a, pos_b), max(pos_a, pos_b)) \
                in self._me_locked_edges
            self.me_info.config(text=f'Rod {pos_a}-{pos_b}: {length:.3f} m'
                                     + (' (LOCKED)' if locked else ''))
            self.me_length.set(round(length, 6))
            self.me_locked_var.set(locked)
            self.me_edge_box.pack(fill='x', padx=6, pady=4, after=self.me_info)
        elif kind == 'toggle':
            pos_a, pos_b = payload
            self.me_info.config(text=f'Potential diagonal {pos_a}-{pos_b} (not present).')
            self.me_toggle_box.pack(fill='x', padx=6, pady=4, after=self.me_info)

    # -- mouse interaction --------------------------------------------------
    def _me_hit_test(self, ex, ey):
        for tag in ('node', 'edge', 'toggle'):
            items = self.me_canvas.find_withtag(tag)
            for item in items:
                x0, y0, x1, y1 = self.me_canvas.bbox(item)
                pad = 6
                if x0 - pad <= ex <= x1 + pad and y0 - pad <= ey <= y1 + pad:
                    tags = self.me_canvas.gettags(item)
                    spec = next((t for t in tags if t != tag and t != 'current'), None)
                    if spec is None:
                        continue
                    suffix = spec[len(tag):]   # e.g. 'toggle0_2' -> '0_2', 'node3' -> '3'
                    if tag == 'node':
                        return ('node', int(suffix))
                    nums = suffix.split('_')
                    return (tag, (int(nums[0]), int(nums[1])))
        return None

    def _me_on_press(self, event):
        hit = self._me_hit_test(event.x, event.y)
        cell_nodes = self._me_current_cell_nodes()
        if hit is None or cell_nodes is None:
            self._me_selection = None
            self._me_drag = None
            self._me_render()
            return
        self._me_selection = hit
        if hit[0] == 'node':
            _coords, _to_screen, scale = self._me_to_screen_fn(cell_nodes)
            self._me_drag = {'start': (event.x, event.y), 'scale': scale, 'moved': False}
        else:
            self._me_drag = None
        self._me_render()

    def _me_on_drag(self, event):
        if self._me_drag is None or self._me_selection is None \
                or self._me_selection[0] != 'node':
            return
        sx, sy = self._me_drag['start']
        ddx, ddy = event.x - sx, event.y - sy
        if abs(ddx) > 2 or abs(ddy) > 2:
            self._me_drag['moved'] = True
        scale = self._me_drag['scale']
        # screen y is flipped relative to local v (see _me_to_screen_fn)
        self.me_du.set(round(ddx / scale, 4))
        self.me_dv.set(round(-ddy / scale, 4))

    def _me_on_release(self, event):
        if self._me_drag and self._me_drag.get('moved') and self._me_selection \
                and self._me_selection[0] == 'node':
            self._me_apply_move()
        self._me_drag = None

    # -- edit actions ---------------------------------------------------------
    def _me_locked_member_idxs(self):
        """Every CURRENT member index that a lock in self._me_locked_edges
        (keyed by role/canonical-position, which stays meaningful across
        edits) resolves to right now, across every cell of every role --
        a locked rod protects its length under ANY role's edit, not just
        edits made to its own role."""
        idxs = []
        for role_id, pos_a, pos_b in self._me_locked_edges:
            for ci in self._me_roles.get(role_id, ()):
                cell_nodes = self._me_cells[ci]['nodes']
                if pos_a >= len(cell_nodes) or pos_b >= len(cell_nodes):
                    continue
                a_id, b_id = cell_nodes[pos_a], cell_nodes[pos_b]
                for mi, m in enumerate(self.members):
                    if {m['a'], m['b']} == {a_id, b_id}:
                        idxs.append(mi)
                        break
        return idxs

    def _me_apply_move(self):
        if self._me_selection is None or self._me_selection[0] != 'node':
            return
        position = self._me_selection[1]
        try:
            delta = (float(self.me_du.get()), float(self.me_dv.get()), float(self.me_dn.get()))
        except (tk.TclError, ValueError):
            return
        if delta == (0.0, 0.0, 0.0):
            return
        self._push_undo('module editor: move node')
        self.nodes = sg.move_role_node(self.nodes, self.members, self._me_cells,
                                       self._me_roles, self._me_role_id, position, delta,
                                       locked_member_idxs=self._me_locked_member_idxs())
        self.results = None
        self.member_checks = None
        # Deliberately NOT _me_refresh_topology() here: a move changes
        # WHERE nodes sit, never WHICH nodes are members of each other --
        # self._me_cells (node-id and member-index tuples) is still
        # exactly as valid as before. Re-running find_cells/
        # classify_cell_roles after every geometric nudge would instead
        # re-derive roles from the now slightly-less-congruent shapes a
        # shared-corner average can produce, fragmenting what was one
        # role into many tiny ones after a single edit -- a real failure
        # mode found by actually exercising this on a densely-shared role
        # (a flat_grid's own pyramidal web) rather than assuming it away.
        # _refresh_all's own fingerprint-based check (member/node COUNT)
        # correctly leaves the role grouping alone here too, for the same
        # reason. _me_render() alone keeps the mini-canvas and the
        # current SELECTION (still meaningful -- it's the same node) in
        # sync with the new positions.
        self._me_render()
        self._refresh_all()

    def _me_apply_length(self):
        if self._me_selection is None or self._me_selection[0] != 'edge':
            return
        pos_a, pos_b = self._me_selection[1]
        key = (self._me_role_id, min(pos_a, pos_b), max(pos_a, pos_b))
        if key in self._me_locked_edges:
            messagebox.showinfo('Module Editor', 'This rod is locked -- uncheck '
                                '"Lock this rod\'s length" first.')
            return
        try:
            new_length = float(self.me_length.get())
        except (tk.TclError, ValueError):
            return
        if new_length <= 0:
            messagebox.showerror('Module Editor', 'Length must be positive.')
            return
        self._push_undo('module editor: set rod length')
        self.nodes = sg.set_role_member_length(self.nodes, self._me_cells, self._me_roles,
                                               self._me_role_id, pos_a, pos_b, new_length)
        self.results = None
        self.member_checks = None
        # Not _me_refresh_topology() -- see _me_apply_move's own comment;
        # a length edit is geometric, not topological.
        self._me_render()
        self._refresh_all()

    def _me_toggle_lock(self):
        if self._me_selection is None or self._me_selection[0] != 'edge':
            self.me_locked_var.set(False)
            return
        pos_a, pos_b = self._me_selection[1]
        key = (self._me_role_id, min(pos_a, pos_b), max(pos_a, pos_b))
        if self.me_locked_var.get():
            self._me_locked_edges.add(key)
        else:
            self._me_locked_edges.discard(key)
        self._me_render()

    def _me_apply_toggle(self):
        if self._me_selection is None or self._me_selection[0] != 'toggle':
            return
        pos_a, pos_b = self._me_selection[1]
        self._push_undo('module editor: toggle rod')
        self.members = sg.toggle_role_member(self.members, self._me_cells, self._me_roles,
                                             self._me_role_id, pos_a, pos_b)
        self._apply_sections(members=self.members, redraw=False)
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _me_apply_rescale(self):
        if self._me_role_id is None:
            return
        try:
            factor = float(self.me_rescale.get())
        except (tk.TclError, ValueError):
            return
        if factor <= 0:
            messagebox.showerror('Module Editor', 'Scale factor must be positive.')
            return
        self._push_undo('module editor: rescale')
        self.nodes = sg.rescale_role_cells(self.nodes, self._me_cells, self._me_roles,
                                           self._me_role_id, factor)
        self.results = None
        self.member_checks = None
        # Not _me_refresh_topology() -- see _me_apply_move's own comment;
        # a rescale is geometric, not topological.
        self._me_render()
        self._refresh_all()
