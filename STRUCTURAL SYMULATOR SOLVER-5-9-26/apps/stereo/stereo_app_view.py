"""Camera, projection and picking for the Stereo canvas -- the layer that
maps between the 3D model and screen pixels, and interprets mouse input.

Three responsibilities, all sharing the same projection:

  camera    -- mouse-only orbit (right-drag), zoom (wheel) and pan
               (middle-drag), plus _project and the view reset
  picking   -- click a node or a rod, rubber-band lasso multi-select
               (left-drag), and the 'Add rod' two-click tool
  deformed  -- the displaced node positions the renderer overlays

Drawing itself lives in stereo_app_render.py; this module never paints,
it only decides where things are and what the user just clicked.
"""
import math
import time as _time

from apps.stereo import stereo_math as sm
from apps.stereo.stereo_app_canvas_geom import (
    _point_segment_distance, _seg_intersects_rect,
)
from apps.stereo.stereo_app_constants import (
    DOF_LABELS, LASSO_DRAG_THRESHOLD_PX, MEMBER_SEL_HIT_PX,
    DRAW_THROTTLE_MS,
)


class StereoViewMixin:
    """Camera, projection, selection and the rod-drawing tool."""

    # ── camera (mouse-only: right-drag orbit, wheel zoom, middle-drag pan) ───
    DRAG_THRESHOLD_PX = 3
    DEG_PER_PX = 0.4

    def _mark_view_touched(self, _event=None):
        self._view_touched = True

    _last_draw_t = 0.0
    _draw_trailing_id = None

    def _draw_throttled(self):
        """Rate-limited _draw for continuous mouse-drag events (orbit, pan,
        lasso). Caps redraws at ~30 fps so dense models stay responsive
        during camera manipulation instead of queueing a redraw per
        mouse-move pixel."""
        now = _time.monotonic()
        interval = DRAW_THROTTLE_MS / 1000.0
        if now - self._last_draw_t >= interval:
            self._last_draw_t = now
            if self._draw_trailing_id is not None:
                self.canvas.after_cancel(self._draw_trailing_id)
                self._draw_trailing_id = None
            self._draw()
        else:
            if self._draw_trailing_id is None:
                remaining_ms = max(1, int((interval - (now - self._last_draw_t)) * 1000))
                self._draw_trailing_id = self.canvas.after(remaining_ms, self._draw_trailing)

    def _draw_trailing(self):
        self._draw_trailing_id = None
        self._last_draw_t = _time.monotonic()
        self._draw()

    def _on_canvas_configure(self, event):
        if not self._view_touched and event.width > 10 and event.height > 10:
            self._reset_view()
        else:
            self._draw()

    def _reset_view(self, redraw=True):
        """Reset camera angle, zoom and pan -- and, critically, CENTER the
        model in the canvas. ZoomCanvas.reset_view() alone sets pan to
        (0, 0), which maps the model's own centroid (already subtracted
        out in _draw's `to_screen`) to screen pixel (0, 0) -- the canvas's
        top-left CORNER, not its center. Left uncorrected, most of a
        freshly generated mesh renders half off-screen above and to the
        left of the visible area, which would make mouse orbiting feel
        broken (nothing to see) even though the camera math is fine."""
        self.azimuth = 35.0
        self.elevation = 22.0
        self.zc.reset_view()
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        self.zc.pan_x = (w if w > 1 else 400) / 2.0
        self.zc.pan_y = (h if h > 1 else 400) / 2.0
        self._view_touched = False
        if redraw:
            self._draw()

    def _on_orbit_press(self, event):
        self._orbit_start = (event.x, event.y, self.azimuth, self.elevation)
        self._orbit_dragged = False

    def _on_orbit_motion(self, event):
        if self._orbit_start is None:
            return
        x0, y0, az0, el0 = self._orbit_start
        dx, dy = event.x - x0, event.y - y0
        if not self._orbit_dragged and (abs(dx) > self.DRAG_THRESHOLD_PX
                                        or abs(dy) > self.DRAG_THRESHOLD_PX):
            self._orbit_dragged = True
            self._view_touched = True
        if self._orbit_dragged:
            self.azimuth = (az0 + dx * self.DEG_PER_PX) % 360.0
            self.elevation = max(-89.0, min(89.0, el0 - dy * self.DEG_PER_PX))
            self._draw_throttled()

    def _on_orbit_release(self, event):
        self._orbit_start = None
        self._orbit_dragged = False

    # ── lasso (rubber-band) multi-select, mirroring truss_app.py's own
    # _on_press/_on_drag_motion/_on_release box-select ──────────────────────
    def _on_canvas_press(self, event):
        self._lasso_press = (event.x, event.y)
        self._lasso_dragging = False
        self._lasso_cur = None
        self._drag_node = None
        self._drag_node_active = False
        if self.selected_nodes and not self.add_rod_mode.get():
            pts = self._screen_positions()
            for i in self.selected_nodes:
                if i < len(pts):
                    sx, sy = pts[i]
                    if math.hypot(sx - event.x, sy - event.y) < 12.0:
                        self._drag_node = (event.x, event.y)
                        break

    def _on_canvas_motion(self, event):
        if self._lasso_press is None:
            return
        x0, y0 = self._lasso_press
        dx, dy = event.x - x0, event.y - y0
        if self._drag_node is not None:
            if not self._drag_node_active and (abs(dx) > LASSO_DRAG_THRESHOLD_PX
                                               or abs(dy) > LASSO_DRAG_THRESHOLD_PX):
                self._drag_node_active = True
                self._push_undo('drag node')
            if self._drag_node_active:
                prev_sx, prev_sy = self._drag_node
                self._move_selected_nodes_by_screen(prev_sx, prev_sy,
                                                    event.x, event.y)
                self._drag_node = (event.x, event.y)
                self._draw_throttled()
            return
        if not self._lasso_dragging and (abs(dx) > LASSO_DRAG_THRESHOLD_PX
                                         or abs(dy) > LASSO_DRAG_THRESHOLD_PX):
            self._lasso_dragging = True
        if self._lasso_dragging:
            self._lasso_cur = (event.x, event.y)
            self._draw_throttled()

    def _on_canvas_release(self, event):
        self.canvas.focus_set()   # so a following Delete/Backspace reaches us
        if self._drag_node_active:
            self._drag_node = None
            self._drag_node_active = False
            self._lasso_press = None
            self.results = None
            self.member_checks = None
            self._refresh_all()
            return
        self._drag_node = None
        self._drag_node_active = False
        additive = bool(event.state & 0x0001)   # Shift held: add to selection
        if self.add_rod_mode.get():
            self._handle_add_rod_click(event.x, event.y)
            self._lasso_press = None
            self._lasso_dragging = False
            self._lasso_cur = None
            return
        if self._lasso_dragging and self._lasso_cur is not None:
            x0, y0 = self._lasso_press
            x1, y1 = self._lasso_cur
            found_nodes = set(self._nodes_in_screen_box(x0, y0, x1, y1))
            found_members = set(self._members_in_screen_box(x0, y0, x1, y1))
            if additive:
                self.selected_nodes = self.selected_nodes | found_nodes
                self.selected_members = self.selected_members | found_members
            else:
                self.selected_nodes = found_nodes
                self.selected_members = found_members
            self.selected_member = None
            self._sync_selection_fields()
        else:
            self._select_node_at(event.x, event.y, additive=additive)
        self._lasso_press = None
        self._lasso_dragging = False
        self._lasso_cur = None
        self._draw()

    def _move_selected_nodes_by_screen(self, sx0, sy0, sx1, sy1):
        """Move all selected nodes by the world-space delta corresponding
        to a screen-pixel drag from (sx0,sy0) to (sx1,sy1), keeping
        each node's depth (view-direction component) constant."""
        wx0, wy0 = self.zc.s2w(sx0, sy0)
        wx1, wy1 = self.zc.s2w(sx1, sy1)
        dpx = (wx1 - wx0) / self.PX_PER_M
        dpy = (wy1 - wy0) / self.PX_PER_M
        az = math.radians(self.azimuth)
        el = math.radians(self.elevation)
        c, s = math.cos(az), math.sin(az)
        ce, se = math.cos(el), math.sin(el)
        dx = c * dpx - s * se * dpy
        dy = -s * dpx - c * se * dpy
        dz = -ce * dpy
        for i in self.selected_nodes:
            if i < len(self.nodes):
                ox, oy, oz = self.nodes[i]
                self.nodes[i] = (ox + dx, oy + dy, oz + dz)

    def _project(self, x, y, z):
        """Rotating orthographic projection: azimuth about the global Z
        axis, then elevation as a tilt about the resulting horizontal axis.
        Returns (screen_x_world_units, screen_y_world_units, depth) --
        depth (bigger = farther from the viewer) is used only for simple
        draw-order and node-size hinting, not true hidden-line removal."""
        az = math.radians(self.azimuth)
        el = math.radians(self.elevation)
        xr = x * math.cos(az) - y * math.sin(az)
        yr = x * math.sin(az) + y * math.cos(az)
        zr = z
        y2 = yr * math.cos(el) - zr * math.sin(el)
        depth = yr * math.sin(el) + zr * math.cos(el)
        return xr, -depth, y2   # (screen_x, screen_y, depth-for-sorting)

    PX_PER_M = 20.0

    def _load_frac(self):
        """The 'Load %' slider as a 0..1 fraction. The solved model is
        linear-elastic (small-deflection direct stiffness), so scaling
        every applied load by this fraction scales every displacement,
        member force and reaction by the EXACT same fraction (this is
        superposition, not an approximation) -- letting the whole display
        step through the load from 0% to 100% by just multiplying the
        already-solved results, with no need to re-run the solver for
        every slider tick."""
        return max(0, min(100, self.load_fraction.get())) / 100.0

    def _deformed_nodes_and_disp(self):
        """World-space node positions offset by the solved displacement
        times the scale slider AND the load-fraction slider, and each
        node's own (unscaled by def_scale, but load-fraction-scaled)
        displacement magnitude in mm -- the same def_scale idiom
        truss_app.py uses, just applied directly in metres since this view
        already works in world units rather than pixels. Used only by the
        deformed-shape overlay: the REST structure (self.nodes) is what
        everything else -- the main render, click-select, the lasso --
        always uses, so "Show deformed" draws an additional green overlay
        in parallel rather than moving the real structure out from under
        the mouse."""
        scale = self.deform_scale.get() * self._load_frac()
        deformed, disp_mm = [], []
        for (x, y, z), nr in zip(self.nodes, self.results['node_res']):
            ux, uy, uz = nr['ux'], nr['uy'], nr['uz']
            deformed.append((x + ux / 1000.0 * scale,
                            y + uy / 1000.0 * scale,
                            z + uz / 1000.0 * scale))
            disp_mm.append(math.sqrt(ux * ux + uy * uy + uz * uz) * self._load_frac())
        return deformed, disp_mm

    def _screen_positions(self):
        """Every node's current on-screen (sx, sy) at its REST position, in
        the exact same projection+centering _draw() uses -- shared by
        click-select, lasso box-select and _draw() itself so all three
        agree on where a node actually is. Always the rest position, even
        with "Show deformed" on: that overlay is an ADDITIONAL green copy
        drawn in parallel, not a replacement, so interaction always targets
        the real structure."""
        proj = [self._project(x, y, z) for x, y, z in self.nodes]
        xs = [p[0] for p in proj]; ys = [p[1] for p in proj]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
        out = []
        for px, py, _ in proj:
            wx = (px - cx) * self.PX_PER_M
            wy = (py - cy) * self.PX_PER_M
            out.append(self.zc.w2s(wx, wy))
        return out

    def _nodes_in_screen_box(self, sx0, sy0, sx1, sy1):
        xlo, xhi = sorted((sx0, sx1))
        ylo, yhi = sorted((sy0, sy1))
        return [i for i, (sx, sy) in enumerate(self._screen_positions())
                if xlo <= sx <= xhi and ylo <= sy <= yhi]

    def _members_in_screen_box(self, sx0, sy0, sx1, sy1):
        """Members whose line segment intersects the screen-space rectangle.
        A member qualifies when at least one endpoint is inside the box OR
        the segment crosses one of the box edges."""
        xlo, xhi = sorted((sx0, sx1))
        ylo, yhi = sorted((sy0, sy1))
        pts = self._screen_positions()
        result = []
        for i, m in enumerate(self.members):
            ax, ay = pts[m['a']]
            bx, by = pts[m['b']]
            a_in = xlo <= ax <= xhi and ylo <= ay <= yhi
            b_in = xlo <= bx <= xhi and ylo <= by <= yhi
            if a_in or b_in:
                result.append(i)
                continue
            if _seg_intersects_rect(ax, ay, bx, by, xlo, ylo, xhi, yhi):
                result.append(i)
        return result

    def _sync_selection_fields(self):
        """Push the current single-node selection (if exactly one node is
        selected) into the typed node fields and the selection/BC panels --
        the same sync a click always did, now shared with the lasso path
        too so a one-node lasso box behaves identically to a plain click.
        Falls through to showing the selected MEMBER's own force/
        utilization readout when a rod, not a node, was clicked."""
        best = self.selected_node
        if best is None:
            if self.selected_member is not None:
                self._show_member_info(self.selected_member)
            elif len(self.selected_nodes) > 1 or self.selected_members:
                parts = []
                if self.selected_nodes:
                    parts.append(f'{len(self.selected_nodes)} node{"s" if len(self.selected_nodes) != 1 else ""}')
                if self.selected_members:
                    parts.append(f'{len(self.selected_members)} member{"s" if len(self.selected_members) != 1 else ""}')
                self.sel_label.config(text=f'{" + ".join(parts)} selected.')
            else:
                self.sel_label.config(
                    text='(click, or drag a box, to select node(s); click a rod to inspect it)')
            return
        self.sup_node_var.set(best)
        self.ld_node_var.set(best)
        x, y, z = self.nodes[best]
        self.sel_label.config(text=f'Node {best}: ({x:.3f}, {y:.3f}, {z:.3f}) m')
        existing = next((s for s in self.supports if s['node'] == best), None)
        if existing is not None:
            r = sm.support_restraints(existing)
            self.sup_preset_var.set(existing.get('type') or 'custom')
            for d, _ in DOF_LABELS:
                self.dof_vars[d].set(r[d])

    def _show_member_info(self, i):
        """The click-to-inspect readout for member `i`: its endpoints/
        role/connectivity always, plus its solved axial force and CIRSOC
        utilization/governing check once ▶ Analyze has run -- the quick,
        one-click alternative to opening the full Member Report table for
        just one rod. Scales N and utilization by the 'Load %' slider like
        every other results display in this tab."""
        m = self.members[i]
        frac = self._load_frac()
        lines = [f'Member {i}: nodes {m["a"]}–{m["b"]}',
                f'role={m.get("role", "web")}  conn={m.get("conn", "pin")}']
        if self.results is not None and i < len(self.results['member_res']):
            N = self.results['member_res'][i]['N'] * frac
            sense = 'tension' if N >= 0 else 'compression'
            lines.append(f'N = {self.fmt("force", N, sign=True)} ({sense})')
            if self.member_checks and i < len(self.member_checks):
                chk = self.member_checks[i]
                if chk.get('checked'):
                    util = chk['util'] * frac
                    status = 'OVER' if util > 1.0 else 'OK'
                    lines.append(f'utilization = {util:.2f} ({status})')
                    if chk.get('governing'):
                        lines.append(f'governs: {chk["governing"]}')
                elif chk.get('note'):
                    lines.append(chk['note'])
        else:
            lines.append('Run ▶ Analyze for force/utilization.')
        self.sel_label.config(text='\n'.join(lines))

    def _on_add_rod_mode_toggle(self):
        # Any pending first-picked node from a previous session with the
        # mode on must not survive turning it off and back on -- otherwise
        # a click made minutes later, with no visible highlight left over
        # to explain why, could silently complete a rod the user never
        # intended.
        self._add_rod_first = None
        self._draw()

    def _handle_add_rod_click(self, ex, ey):
        """One click while 'Add rod' mode is on. The FIRST click within
        hit range of a node picks it (held in self._add_rod_first and
        drawn with an ADD_ROD_PENDING_COLOR ring so the pending state is
        never invisible); the SECOND click on a DIFFERENT node completes
        the rod and resets, ready for the next pair. Clicking the SAME
        node again, or empty space with nothing in range, cancels the
        pending pick instead of leaving it stuck until some later
        unrelated click accidentally completes it."""
        best, best_d = None, 12.0
        for i, (sx, sy) in enumerate(self._screen_positions()):
            d = math.hypot(sx - ex, sy - ey)
            if d < best_d:
                best, best_d = i, d
        if best is None or best == self._add_rod_first:
            self._add_rod_first = None
            self._draw()
            return
        if self._add_rod_first is None:
            self._add_rod_first = best
            self._draw()
            return
        a, b = self._add_rod_first, best
        self._add_rod_first = None
        self._add_rod_between(a, b)

    def _add_rod_between(self, a, b):
        """Add a new pin-connected member directly between two EXISTING
        nodes -- for exploring "what if I brace this" without regenerating
        the whole mesh. Silently a no-op if the two nodes are already
        connected (adding a parallel duplicate rod would just double-count
        that path's stiffness, not brace anything new). Takes the WEB
        section's current E/A/etc, and a role ('user_rod') that is not in
        CHORD_ROLES, so a later Apply Sections call classifies it exactly
        the way _apply_sections already treats any non-chord role -- it
        solves immediately, not only after a manual re-apply."""
        if a == b:
            return
        if any((m['a'] == a and m['b'] == b) or (m['a'] == b and m['b'] == a)
               for m in self.members):
            return
        self._push_undo('add rod')
        web = dict(E=self.web_E.get(), A=self.web_A.get(), I=self.web_I.get(),
                  J=self.web_J.get(), Fy=self.web_Fy.get(), Fu=self.web_Fu.get(),
                  K=self.web_K.get(), r_gyr=self.web_r.get())
        self.members.append({'a': a, 'b': b, 'conn': self.sec_conn.get(),
                            'role': 'user_rod', **web})
        self.results = None
        self.member_checks = None
        self._refresh_all()

    # ── keyboard axis extend ────────────────────────────────────────────────
    _AXIS_KEYS = {
        'Left':  (-1, 0, 0, '-X'),
        'Right': ( 1, 0, 0, '+X'),
        'Up':    ( 0, 1, 0, '+Y'),
        'Down':  ( 0,-1, 0, '-Y'),
        'Prior': ( 0, 0, 1, '+Z'),
        'Next':  ( 0, 0,-1, '-Z'),
    }

    def _on_axis_key(self, event=None):
        if not event or len(self.selected_nodes) != 1:
            return
        info = self._AXIS_KEYS.get(event.keysym)
        if not info:
            return
        dx, dy, dz, label = info
        self._axis_pending = (dx, dy, dz)
        self._axis_dir_label.config(text=label)
        self._axis_extend_frame.pack(fill='x', pady=(0, 4))
        self._axis_len_entry.focus_set()
        self._axis_len_entry.select_range(0, 'end')
        self._draw()

    def _on_axis_cancel(self, event=None):
        self._axis_pending = None
        self._axis_extend_frame.pack_forget()
        self.canvas.focus_set()
        self._draw()

    def _axis_extend_go(self):
        if self._axis_pending is None or len(self.selected_nodes) != 1:
            self._on_axis_cancel()
            return
        try:
            length = self._axis_len_var.get()
        except Exception:
            return
        if length <= 0:
            return
        dx, dy, dz = self._axis_pending
        src = next(iter(self.selected_nodes))
        ox, oy, oz = self.nodes[src]
        new_pos = (ox + dx * length, oy + dy * length, oz + dz * length)
        self._push_undo('extend along axis')
        new_idx = len(self.nodes)
        self.nodes.append(new_pos)
        web = dict(E=self.web_E.get(), A=self.web_A.get(), I=self.web_I.get(),
                  J=self.web_J.get(), Fy=self.web_Fy.get(), Fu=self.web_Fu.get(),
                  K=self.web_K.get(), r_gyr=self.web_r.get())
        self.members.append({'a': src, 'b': new_idx,
                            'conn': self.sec_conn.get(),
                            'role': 'user_rod', **web})
        self.results = None
        self.member_checks = None
        self.selected_nodes = {new_idx}
        self.selected_member = None
        self.selected_members = set()
        self._axis_pending = None
        self._axis_extend_frame.pack_forget()
        self.canvas.focus_set()
        self._refresh_all()

    def _select_node_at(self, ex, ey, additive=False):
        if not self.nodes:
            return
        best, best_d = None, 12.0
        for i, (sx, sy) in enumerate(self._screen_positions()):
            d = math.hypot(sx - ex, sy - ey)
            if d < best_d:
                best, best_d = i, d
        if best is not None and self.support_sandbox.get():
            support_nodes = {s['node'] for s in self.supports}
            if best in support_nodes:
                self._disabled_supports.symmetric_difference_update({best})
                self._refresh_indeterminacy_label()
                self._draw()
                return
        if best is not None:
            if additive:
                self.selected_nodes.symmetric_difference_update({best})
            else:
                self.selected_nodes = {best}
            self.selected_member = None
            if not additive:
                self.selected_members = set()
            self._sync_selection_fields()
            self._draw()
            return
        # No node close enough -- try the nearest rod instead, so a click
        # on empty space near a member still does something useful.
        mi = self._select_member_at(ex, ey)
        if mi is not None:
            self.selected_member = mi
            if additive:
                self.selected_members.symmetric_difference_update({mi})
            else:
                self.selected_nodes = set()
                self.selected_members = {mi}
            self._sync_selection_fields()
            self._draw()
            return
        if not additive:
            self.selected_nodes = set()
            self.selected_member = None
            self.selected_members = set()
            self._sync_selection_fields()
            self._draw()

    def _select_member_at(self, ex, ey):
        """The nearest member to screen point (ex, ey), within
        MEMBER_SEL_HIT_PX of its own line segment, or None -- shares
        _screen_positions()'s REST-position frame so a rod click always
        targets the same geometry a node click would."""
        pts = self._screen_positions()
        best, best_d = None, MEMBER_SEL_HIT_PX
        for i, m in enumerate(self.members):
            sx0, sy0 = pts[m['a']]
            sx1, sy1 = pts[m['b']]
            d = _point_segment_distance(ex, ey, sx0, sy0, sx1, sy1)
            if d < best_d:
                best, best_d = i, d
        return best

    def _on_delete_selection(self, event=None):
        """Delete selected nodes and/or members.

        When nodes are selected their connected members are removed
        transitively and every surviving node-index reference is remapped.
        When only members are selected (no nodes) just those members are
        removed -- nodes at their endpoints are kept."""
        node_targets = set(self.selected_nodes)
        member_targets = set(self.selected_members)
        if not node_targets and not member_targets:
            return

        if node_targets:
            what = 'node' + ('s' if len(node_targets) != 1 else '')
            if member_targets:
                what += ' + member' + ('s' if len(member_targets) != 1 else '')
        else:
            what = 'member' + ('s' if len(member_targets) != 1 else '')
        self._push_undo('delete ' + what)

        if node_targets:
            remap = {}
            new_nodes = []
            for i, n in enumerate(self.nodes):
                if i in node_targets:
                    continue
                remap[i] = len(new_nodes)
                new_nodes.append(n)
            self.nodes = new_nodes
            self.members = [
                {**m, 'a': remap[m['a']], 'b': remap[m['b']]}
                for j, m in enumerate(self.members)
                if m['a'] not in node_targets
                and m['b'] not in node_targets
                and j not in member_targets]
            self.supports = [{**s, 'node': remap[s['node']]}
                            for s in self.supports if s['node'] not in node_targets]
            self.loads = [{**ld, 'node': remap[ld['node']]}
                        for ld in self.loads if ld['node'] not in node_targets]
            self._support_candidates = [remap[i] for i in self._support_candidates
                                        if i not in node_targets]
            self._load_nodes = {remap[i]: v for i, v in self._load_nodes.items()
                               if i not in node_targets}
        else:
            self.members = [m for j, m in enumerate(self.members)
                           if j not in member_targets]

        self.selected_nodes = set()
        self.selected_member = None
        self.selected_members = set()
        self.results = None
        self.member_checks = None
        self._refresh_all()
