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
import tkinter as tk
import math

from apps.stereo import stereo_math as sm
from apps.stereo import expr_math as em
from apps.stereo.stereo_app_canvas_geom import _point_segment_distance
from apps.stereo.stereo_app_constants import (
    DOF_LABELS, LASSO_DRAG_THRESHOLD_PX, MEMBER_SEL_HIT_PX,
    PROJECTION_PERSPECTIVE, PERSPECTIVE_MIN_DENOM,
    SOURCE_SPIN, SOURCE_EXTRUDE, BZ_HANDLE_GRAB_PX,
)


class StereoViewMixin:
    """Camera, projection, selection and the rod-drawing tool."""

    # ── camera (mouse-only: right-drag orbit, wheel zoom, middle-drag pan) ───
    DRAG_THRESHOLD_PX = 3
    DEG_PER_PX = 0.4

    def _mark_view_touched(self, _event=None):
        self._view_touched = True

    def _on_canvas_configure(self, event):
        if not self._view_touched and event.width > 10 and event.height > 10:
            self._reset_view()
        else:
            self._draw()

    VIEW_FIT_MARGIN = 0.82

    def _fit_zoom(self, w, h):
        """The zoom that makes the current model fill most of the canvas.

        PX_PER_M is a fixed 20 px/m, so the size a model appears at is
        decided entirely by how many metres across it is: a 6 m module
        filled the canvas and a 40 m dome ran off it, and a freshly built
        12 m surface landed as a small clump in the middle of a lot of
        empty white. Fit the zoom to the model's own projected extent
        instead, so "reset view" means "show me the model" at any scale.

        Returns None when there is nothing to fit (no model, or a canvas
        that has not been laid out yet), and the caller keeps zoom = 1.
        """
        if not self.nodes or w <= 1 or h <= 1:
            return None
        proj = [self._project(x, y, z) for x, y, z in self.nodes]
        xs = [p[0] for p in proj]
        ys = [p[1] for p in proj]
        span_x = (max(xs) - min(xs)) * self.PX_PER_M
        span_y = (max(ys) - min(ys)) * self.PX_PER_M
        # A single node, or a model seen exactly edge-on, has no extent in
        # one direction; that direction simply does not constrain the fit.
        fits = []
        if span_x > 1.0:
            fits.append(w * self.VIEW_FIT_MARGIN / span_x)
        if span_y > 1.0:
            fits.append(h * self.VIEW_FIT_MARGIN / span_y)
        if not fits:
            return None
        return max(self.zc.MIN_ZOOM, min(self.zc.MAX_ZOOM, min(fits)))

    def _reset_view(self, redraw=True):
        """Reset the camera angle, then fit the zoom to the model and CENTER
        it in the canvas.

        ZoomCanvas.reset_view() alone sets pan to (0, 0), which maps the
        model's own centroid (already subtracted out in _draw's
        `to_screen`) to screen pixel (0, 0) -- the canvas's top-left
        CORNER, not its center. Left uncorrected, most of a freshly
        generated mesh renders half off-screen above and to the left of
        the visible area, which would make mouse orbiting feel broken
        (nothing to see) even though the camera math is fine.

        The centring pan is NOT half the canvas: w2s multiplies by zoom
        AFTER adding the pan, so the pan that lands the centroid in the
        middle is w / (2 * zoom). Those agree only at zoom = 1, which is
        why this has to be computed after the fit, not before it.
        """
        self.azimuth = 35.0
        self.elevation = 22.0
        self.zc.reset_view()
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        w = w if w > 1 else 400
        h = h if h > 1 else 400
        self.zc.zoom = self._fit_zoom(w, h) or 1.0
        self.zc.pan_x = w / (2.0 * self.zc.zoom)
        self.zc.pan_y = h / (2.0 * self.zc.zoom)
        self._view_touched = False
        if redraw:
            self._draw()

    def _on_orbit_press(self, event):
        self._orbit_start = (event.x, event.y, self.azimuth, self.elevation)
        self._orbit_dragged = False

    def _on_orbit_motion(self, event):
        self._clear_named_view()
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
            self._draw()

    def _on_orbit_release(self, event):
        self._orbit_start = None
        self._orbit_dragged = False

    # ── lasso (rubber-band) multi-select, mirroring truss_app.py's own
    # _on_press/_on_drag_motion/_on_release box-select ──────────────────────
    def _on_canvas_press(self, event):
        # A handle grab has to win over the lasso, or dragging a control
        # would box-select the model behind it instead.
        grabbed = self._bz_handle_at(event.x, event.y)
        if grabbed is not None:
            self._bz_drag = grabbed
            self._push_undo('drag control point')
            return
        self._lasso_press = (event.x, event.y)
        self._lasso_dragging = False
        self._lasso_cur = None

    def _on_canvas_motion(self, event):
        if getattr(self, '_bz_drag', None) is not None:
            self._bz_drag_to(event.x, event.y)
            return
        if self._lasso_press is None:
            return
        x0, y0 = self._lasso_press
        dx, dy = event.x - x0, event.y - y0
        if not self._lasso_dragging and (abs(dx) > LASSO_DRAG_THRESHOLD_PX
                                         or abs(dy) > LASSO_DRAG_THRESHOLD_PX):
            self._lasso_dragging = True
        if self._lasso_dragging:
            self._lasso_cur = (event.x, event.y)
            self._draw()

    def _on_canvas_release(self, event):
        if getattr(self, '_bz_drag', None) is not None:
            self._bz_drag = None
            self.canvas.focus_set()
            return
        self.canvas.focus_set()   # so a following Delete/Backspace reaches us
        additive = bool(event.state & 0x0001)   # Shift held: add to selection
        if self.disc_pick_mode.get():
            # Commit whatever the hover disc is currently covering. The
            # highlight the user has been watching IS the selection, so
            # there is nothing to re-compute here and no way for the two to
            # disagree.
            if self._disc_hits:
                self.selected_nodes = set(self._disc_hits)
                self.selected_member = None
                self._sync_selection_fields()
            self._lasso_press = None
            self._lasso_dragging = False
            self._lasso_cur = None
            self._draw()
            return
        if self.line_pick_mode.get():
            self._handle_line_pick_click(event.x, event.y)
            self._lasso_press = None
            self._lasso_dragging = False
            self._lasso_cur = None
            return
        if self.add_rod_mode.get():
            # A plain click-to-pick tool, deliberately bypassing the lasso/
            # select machinery below entirely (including the support-
            # sandbox click-to-disable behaviour) so the two clicks that
            # place a rod can never be misread as a box-select or a
            # sandbox toggle while this mode is on.
            self._handle_add_rod_click(event.x, event.y)
            self._lasso_press = None
            self._lasso_dragging = False
            self._lasso_cur = None
            return
        if self._lasso_dragging and self._lasso_cur is not None:
            x0, y0 = self._lasso_press
            x1, y1 = self._lasso_cur
            found = set(self._nodes_in_screen_box(x0, y0, x1, y1))
            self.selected_nodes = (self.selected_nodes | found) if additive else found
            self.selected_member = None
            self._sync_selection_fields()
        else:
            self._select_node_at(event.x, event.y, additive=additive)
        self._lasso_press = None
        self._lasso_dragging = False
        self._lasso_cur = None
        self._draw()

    # ── line pick: every node a straight run passes through ─────────────────
    LINE_PICK_TOL_FRAC = 0.35     # of the model's own module size

    def _handle_line_pick_click(self, ex, ey):
        """Two clicks, both on nodes: the first sets the start, the second
        selects every node the straight run between them passes through.

        Deliberately node-to-node rather than freehand. A support line, a
        row of purlins or a bracing run is defined by the joints at its
        ends; asking for a hand-drawn stroke would make an exact selection
        depend on how steady the mouse was.
        """
        hit = self._nearest_node_to(ex, ey)
        if hit is None:
            self._set_pick_note('Click ON a node to start the line.')
            self._draw()
            return
        if self._line_pick_first is None:
            self._line_pick_first = hit
            self._set_pick_note(f'Line from node {hit} -- now click the far end.')
            self._draw()
            return
        if hit == self._line_pick_first:
            self._set_pick_note('Pick a different node for the far end.')
            self._draw()
            return
        tol = self.LINE_PICK_TOL_FRAC * self._typical_spacing()
        found = self._nodes_near_segment(self._line_pick_first, hit, tol)
        self.selected_nodes = set(found)
        self.selected_member = None
        self._line_pick_first = None
        self._sync_selection_fields()
        self._set_pick_note(f'{len(found)} nodes on that line.')
        self._draw()

    def _nearest_node_to(self, ex, ey, max_px=14):
        best, bestd = None, None
        for i, (sx, sy) in enumerate(self._screen_positions()):
            d = (sx - ex) ** 2 + (sy - ey) ** 2
            if bestd is None or d < bestd:
                best, bestd = i, d
        if best is None or bestd > max_px * max_px:
            return None
        return best

    # ── disc pick: a footprint drawn under the cursor ───────────────────────
    def _on_canvas_hover(self, event):
        """Follow the cursor with the footprint disc while it is armed.

        Bound to plain <Motion>, so it costs nothing when the tool is off --
        the first line returns before any projection work is done.
        """
        if not self.disc_pick_mode.get():
            return
        hits, centre = self._disc_under_cursor(event.x, event.y)
        if hits == self._disc_hits and centre == self._disc_centre:
            return                      # nothing moved: do not redraw
        self._disc_hits, self._disc_centre = hits, centre
        self._draw()

    def _disc_under_cursor(self, ex, ey):
        """(nodes covered, (cx, cy, z) of the disc) for the cursor position.

        The disc lies ON the chosen layer, not on the screen: its centre is
        the cursor unprojected onto that layer's own plane, so it stays the
        same size in METRES as the model is orbited and zoomed, and it
        covers the joints it looks like it covers.
        """
        layer = self._layer_nodes(self.disc_layer.get())
        if not layer:
            return [], None
        z = (max if self.disc_layer.get() == 'top' else min)(
            self.nodes[i][2] for i in layer)
        world = self._unproject_to_plane(ex, ey, z)
        if world is None:
            return [], None
        cx, cy = world
        try:
            factor = float(self.disc_radius.get())
        except (tk.TclError, ValueError):
            factor = 0.8
        radius = max(1e-6, factor) * self._typical_spacing(layer)
        try:
            cap = max(1, int(self.disc_limit.get()))
        except (tk.TclError, ValueError):
            cap = 4
        return self._nodes_in_disc(cx, cy, radius, layer, limit=cap), (cx, cy, z, radius)

    def _set_pick_note(self, text):
        note = getattr(self, 'pick_note', None)
        if note is not None:
            note.config(text=text)

    def _on_pick_mode_toggle(self, which):
        """Only one picking tool at a time, and a half-finished line never
        survives its tool being switched off -- a click made minutes later,
        with nothing on screen to explain it, would otherwise complete a
        selection nobody asked for."""
        if which != 'line':
            self.line_pick_mode.set(False)
        if which != 'disc':
            self.disc_pick_mode.set(False)
        if which != 'rod':
            self.add_rod_mode.set(False)
        self._line_pick_first = None
        self._disc_hits, self._disc_centre = [], None
        self._draw()

    def _project(self, x, y, z):
        """Rotating projection: azimuth about the global Z axis, then
        elevation as a tilt about the resulting horizontal axis.

        Returns (screen_x_world_units, screen_y_world_units, depth), where
        depth (bigger = farther from the viewer) drives draw order and
        node-size hinting, not true hidden-line removal.

        PARALLEL (orthographic) is the default and was for a long time the
        only mode. It keeps equal lengths equal on screen wherever they
        sit, which is what you want for measuring and for reading a
        repeating module -- every bay of a grid is drawn the same size
        because every bay IS the same size.

        PERSPECTIVE divides by distance, so the far end shrinks and
        parallel chords converge. That is how the eye and a camera see, and
        it is the honest answer to "how will this actually look" on a long
        span -- but it makes two equal members different lengths on screen,
        so it is the wrong mode to measure in. One line of maths, two
        completely different questions answered.
        """
        az = math.radians(self.azimuth)
        el = math.radians(self.elevation)
        xr = x * math.cos(az) - y * math.sin(az)
        yr = x * math.sin(az) + y * math.cos(az)
        zr = z
        y2 = yr * math.cos(el) - zr * math.sin(el)          # toward the viewer
        drop = yr * math.sin(el) + zr * math.cos(el)        # screen vertical
        if self.projection_mode.get() == PROJECTION_PERSPECTIVE:
            d = self._persp_d
            denom = d + y2
            if denom < PERSPECTIVE_MIN_DENOM:
                # Behind, or level with, the eye. Clamping rather than
                # dividing keeps the point on screen instead of hurling it
                # to infinity or flipping it through the origin, which is
                # what an unguarded divide does to anything the camera has
                # moved past.
                denom = PERSPECTIVE_MIN_DENOM
            scale = d / denom
            return xr * scale, -drop * scale, y2
        return xr, -drop, y2   # (screen_x, screen_y, depth-for-sorting)

    def _on_projection_change(self):
        """Grey the distance slider in parallel mode, where it means
        nothing -- an orthographic projection has no eye to move."""
        perspective = self.projection_mode.get() == PROJECTION_PERSPECTIVE
        # The popover builds itself lazily the first time it is opened, so
        # these two may not exist yet -- and the projection can be set
        # before then, by a test or by a restored preference.
        scale = getattr(self, 'camera_scale', None)
        if scale is not None:
            scale.config(state='normal' if perspective else 'disabled')
        note = getattr(self, 'camera_note', None)
        if note is not None:
            note.config(text=(f'eye {self.camera_distance.get() / 10.0:.1f}x the model'
                              if perspective else 'no eye position: sizes are true'))
        self._draw()

    def _bz_handle_geometry(self):
        """[(index, (x, y, z), (ux, uy, uz))] for the profile's control
        points: where each one sits in the world, and the unit direction
        its VALUE moves along.

        The parameter position of a control is fixed by the fit -- a chain
        of cubics over a uniform parameter range -- so only the value is
        editable, and it moves along ONE known axis. That is what makes a
        two-dimensional screen drag unambiguous here without asking the
        user to pick a plane first: for a spin the value is a radius, so it
        moves along +X in the theta=0 plane; for an extrude it is a height,
        so it moves along +Z. A full Bezier PATCH has its controls spread
        over a surface with no such single axis, which is why the patch is
        edited in the table and not by dragging.
        """
        profile = getattr(self, '_bz_profile', None)
        if profile is None:
            return []
        source = self.shape_source.get()
        if source not in (SOURCE_SPIN, SOURCE_EXTRUDE):
            return []
        a, b = profile['a'], profile['b']
        ctrl = profile['ctrl']
        last = len(ctrl) - 1
        try:
            edge = self._shape_num(self.shape_q0, 'y from')
        except em.ExpressionError:
            edge = 0.0
        out = []
        for i, value in enumerate(ctrl):
            t = a + (b - a) * (i / last if last else 0.0)
            if source == SOURCE_SPIN:
                out.append((i, (value, 0.0, t), (1.0, 0.0, 0.0)))
            else:
                out.append((i, (t, edge, value), (0.0, 0.0, 1.0)))
        return out

    def _bz_handle_screen(self):
        """[(index, sx, sy)] -- the handles in canvas pixels, through the
        SAME projection and centring the model is drawn with, so a click
        lands where the handle looks like it is."""
        if not self.nodes:
            return []
        geometry = self._bz_handle_geometry()
        if not geometry:
            return []
        self._refresh_camera_distance()
        proj = [self._project(x, y, z) for x, y, z in self.nodes]
        xs = [p[0] for p in proj]
        ys = [p[1] for p in proj]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
        out = []
        for index, point, _direction in geometry:
            px, py, _d = self._project(*point)
            sx, sy = self.zc.w2s((px - cx) * self.PX_PER_M, (py - cy) * self.PX_PER_M)
            out.append((index, sx, sy))
        return out

    def _bz_handle_at(self, ex, ey, max_px=BZ_HANDLE_GRAB_PX):
        """The control under the cursor, nearest first."""
        best = None
        best_d = max_px
        for index, sx, sy in self._bz_handle_screen():
            d = math.hypot(sx - ex, sy - ey)
            if d <= best_d:
                best_d = d
                best = index
        return best

    def _bz_drag_to(self, ex, ey):
        """Move the grabbed control so it follows the cursor along its own
        value axis.

        Projected onto that axis rather than solved for: the handle can
        only move one way, so the honest reading of a two-dimensional drag
        is how far along that way the cursor went. Taking the screen
        direction from the projection means it stays correct as the camera
        orbits, and under perspective as well as parallel, instead of
        assuming screen-up is world-up.
        """
        index = getattr(self, '_bz_drag', None)
        profile = getattr(self, '_bz_profile', None)
        if index is None or profile is None:
            return
        geometry = {i: (p, d) for i, p, d in self._bz_handle_geometry()}
        if index not in geometry:
            return
        point, direction = geometry[index]
        self._refresh_camera_distance()
        proj = [self._project(x, y, z) for x, y, z in self.nodes]
        if not proj:
            return
        xs = [p[0] for p in proj]
        ys = [p[1] for p in proj]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0

        def to_screen(world):
            px, py, _d = self._project(*world)
            return self.zc.w2s((px - cx) * self.PX_PER_M, (py - cy) * self.PX_PER_M)

        here = to_screen(point)
        ahead = to_screen(tuple(point[k] + direction[k] for k in range(3)))
        axis = (ahead[0] - here[0], ahead[1] - here[1])
        length2 = axis[0] ** 2 + axis[1] ** 2
        if length2 < 1e-9:
            # The value axis points straight at the camera, so a drag says
            # nothing about it. Refusing beats moving the control by an
            # arbitrary amount.
            return
        moved = ((ex - here[0]) * axis[0] + (ey - here[1]) * axis[1]) / length2
        self._bz_set_control(index, profile['ctrl'][index] + moved)

    def _refresh_camera_distance(self):
        """Set the eye distance for perspective, as a MULTIPLE of the
        model's own size rather than a fixed number of metres.

        A fixed distance cannot serve both a 6 m canopy and a 60 m bridge:
        whatever looks natural on one is either a fisheye or a flat
        orthographic on the other. Keyed to the model's bounding radius,
        one slider setting means the same STRENGTH of perspective at every
        scale, which is what the setting is actually for.

        Recomputed rather than cached: it is one O(n) pass over the nodes,
        and the three call sites (_draw, _screen_points, _unproject_to_plane)
        already make one. A cache would have to be invalidated by every
        node move -- the module editor, a column, a rebuilt mesh -- and a
        stale camera silently mis-places every click.
        """
        if not self.nodes:
            self._persp_d = 1.0
            return
        xs = [n[0] for n in self.nodes]
        ys = [n[1] for n in self.nodes]
        zs = [n[2] for n in self.nodes]
        radius = max((max(xs) - min(xs)), (max(ys) - min(ys)), (max(zs) - min(zs))) / 2.0
        self._persp_d = max(1e-3, radius * self.camera_distance.get() / 10.0)

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
        self._refresh_camera_distance()
        proj = [self._project(x, y, z) for x, y, z in self.nodes]
        xs = [p[0] for p in proj]; ys = [p[1] for p in proj]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
        out = []
        for px, py, _ in proj:
            wx = (px - cx) * self.PX_PER_M
            wy = (py - cy) * self.PX_PER_M
            out.append(self.zc.w2s(wx, wy))
        return out

    def _unproject_to_plane(self, sx, sy, z):
        """The world (x, y) that screen point (sx, sy) lands on, on the
        horizontal plane at height `z`.

        _project is a rotation by azimuth, then a tilt by elevation, then an
        orthographic drop -- all invertible when the target plane is not
        edge-on. Screen y carries -(yr*sin(el) + z*cos(el)), so once z is
        fixed, yr follows, and undoing the azimuth gives (x, y).

        Returns None when sin(elevation) is ~0, which is the honest answer:
        looking along the horizon, a horizontal plane projects to a LINE and
        one screen point is every point on a ray. Nothing should guess a
        position there.
        """
        el = math.radians(self.elevation)
        if abs(math.sin(el)) < 1e-6:
            return None
        self._refresh_camera_distance()
        proj = [self._project(x, y, zz) for x, y, zz in self.nodes]
        if not proj:
            return None
        xs = [p[0] for p in proj]
        ys = [p[1] for p in proj]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
        wx, wy = self.zc.s2w(sx, sy)
        px = wx / self.PX_PER_M + cx
        py = wy / self.PX_PER_M + cy
        az = math.radians(self.azimuth)
        if self.projection_mode.get() == PROJECTION_PERSPECTIVE:
            # Perspective scales BOTH screen axes by d/(d + y2), and y2
            # itself depends on yr -- so screen y cannot be inverted one
            # axis at a time the way the parallel case can. Substituting
            # the scale into py and solving the resulting linear equation
            # for yr:
            #
            #   py = -(yr*sin el + z*cos el) * d / (d + yr*cos el - z*sin el)
            #   =>  yr = (py*z*sin el - d*z*cos el - py*d)
            #            / (py*cos el + d*sin el)
            #
            # Inverting the PARALLEL maths here instead would put every
            # click a few per cent off, growing with distance from the
            # centre -- the kind of wrong that looks like a sloppy hit
            # radius rather than a bug.
            d = self._persp_d
            denom = py * math.cos(el) + d * math.sin(el)
            if abs(denom) < 1e-9:
                return None
            yr = (py * z * math.sin(el) - d * z * math.cos(el) - py * d) / denom
            scale_denom = d + yr * math.cos(el) - z * math.sin(el)
            if abs(scale_denom) < PERSPECTIVE_MIN_DENOM:
                return None
            xr = px * scale_denom / d
        else:
            xr = px
            yr = (-py - z * math.cos(el)) / math.sin(el)
        x = xr * math.cos(az) + yr * math.sin(az)
        y = -xr * math.sin(az) + yr * math.cos(az)
        return x, y

    def _layer_nodes(self, which):
        """Node indices on the top or bottom chord layer.

        "Layer" is by ELEVATION, with a tolerance of a twentieth of the
        model's own height: a curved roof's top layer is not one flat z, and
        an exact comparison would find only the handful of nodes at the
        extreme.
        """
        if not self.nodes:
            return []
        zs = [p[2] for p in self.nodes]
        lo, hi = min(zs), max(zs)
        tol = max(1e-6, (hi - lo) * 0.05)
        if which == 'top':
            return [i for i, p in enumerate(self.nodes) if p[2] >= hi - tol]
        return [i for i, p in enumerate(self.nodes) if p[2] <= lo + tol]

    def _typical_spacing(self, among=None):
        """The median distance from a node to its nearest neighbour -- the
        model's own module size, whatever family built it. Every radius and
        tolerance in the picking tools is a multiple of this, so one setting
        behaves the same on a 1 m module and a 5 m one."""
        ids = list(among if among is not None else range(len(self.nodes)))
        if len(ids) < 2:
            return 1.0
        gaps = []
        for i in ids[:400]:
            xi, yi, zi = self.nodes[i]
            best = None
            for j in ids:
                if j == i:
                    continue
                xj, yj, zj = self.nodes[j]
                d = (xj - xi) ** 2 + (yj - yi) ** 2 + (zj - zi) ** 2
                if best is None or d < best:
                    best = d
            if best:
                gaps.append(math.sqrt(best))
        gaps.sort()
        return gaps[len(gaps) // 2] if gaps else 1.0

    def _nodes_near_segment(self, a, b, tol):
        """Every node within `tol` of the straight segment from node `a` to
        node `b`, in WORLD space.

        World space, not screen space, on purpose: a line drawn across a
        perspective-less but tilted view passes near nodes on other layers
        that merely look close. Measuring in the model's own coordinates
        selects the row you meant rather than everything behind it.
        """
        if not (0 <= a < len(self.nodes) and 0 <= b < len(self.nodes)):
            return []
        ax, ay, az_ = self.nodes[a]
        bx, by, bz = self.nodes[b]
        dx, dy, dz = bx - ax, by - ay, bz - az_
        L2 = dx * dx + dy * dy + dz * dz
        if L2 < 1e-12:
            return [a]
        out = []
        for i, (x, y, z) in enumerate(self.nodes):
            t = ((x - ax) * dx + (y - ay) * dy + (z - az_) * dz) / L2
            t = max(0.0, min(1.0, t))
            px, py, pz = ax + dx * t, ay + dy * t, az_ + dz * t
            if (x - px) ** 2 + (y - py) ** 2 + (z - pz) ** 2 <= tol * tol:
                out.append(i)
        return out

    def _nodes_in_disc(self, cx, cy, radius, layer_ids, limit=4):
        """The nodes of `layer_ids` whose PLAN position falls inside a disc,
        nearest first, capped at `limit`.

        Plan distance, not 3D: the disc is a footprint drawn on the ground
        under the roof, so a node's height must not decide whether it is
        inside it. The cap is what makes this a column-footprint tool --
        a latticed column takes 3 or 4 chords and no more.
        """
        hits = []
        for i in layer_ids:
            x, y, _z = self.nodes[i]
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            if d2 <= radius * radius:
                hits.append((d2, i))
        hits.sort()
        return [i for _d, i in hits[:max(1, int(limit))]]

    def _nodes_in_screen_box(self, sx0, sy0, sx1, sy1):
        xlo, xhi = sorted((sx0, sx1))
        ylo, yhi = sorted((sy0, sy1))
        return [i for i, (sx, sy) in enumerate(self._screen_positions())
                if xlo <= sx <= xhi and ylo <= sy <= yhi]

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
            elif len(self.selected_nodes) > 1:
                self.sel_var.set(f'{len(self.selected_nodes)} nodes selected.')
            else:
                self.sel_var.set(
                    '(click, or drag a box, to select node(s); click a rod to inspect it)')
            return
        self.sup_node_var.set(best)
        self.ld_node_var.set(best)
        x, y, z = self.nodes[best]
        self.sel_var.set(f'Node {best}: ({x:.3f}, {y:.3f}, {z:.3f}) m')
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
        self.sel_var.set('\n'.join(lines))

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
            self._sync_selection_fields()
            self._draw()
            return
        # No node close enough -- try the nearest rod instead, so a click
        # on empty space near a member still does something useful.
        mi = self._select_member_at(ex, ey)
        if mi is not None:
            self.selected_member = mi
            if not additive:
                self.selected_nodes = set()
            self._sync_selection_fields()
            self._draw()
            return
        if not additive:
            self.selected_nodes = set()
            self.selected_member = None
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

    def _on_delete_nodes(self, event=None):
        """Delete every currently selected node, and (transitively) every
        member touching one, remapping every remaining reference to a node
        INDEX -- other members' a/b, supports, loads, support_candidates,
        load_nodes -- down past the removed indices. Node identity in this
        tab is the list index (as in truss_app.py's own _on_delete, which
        this mirrors), so anything left referring to a stale index once
        the list has shifted would be silent corruption, not a crash.
        Deleting a support node (or enough of the mesh) can leave the rest
        of the structure a genuine mechanism -- that surfaces the normal
        way, as Analyze reporting a singular stiffness matrix, rather than
        being auto-patched here."""
        targets = set(self.selected_nodes)
        if not targets:
            return
        self._push_undo('delete node' + ('s' if len(targets) != 1 else ''))

        remap = {}
        new_nodes = []
        for i, n in enumerate(self.nodes):
            if i in targets:
                continue
            remap[i] = len(new_nodes)
            new_nodes.append(n)
        self.nodes = new_nodes
        self.members = [{**m, 'a': remap[m['a']], 'b': remap[m['b']]}
                       for m in self.members if m['a'] not in targets and m['b'] not in targets]
        self.supports = [{**s, 'node': remap[s['node']]}
                        for s in self.supports if s['node'] not in targets]
        self.loads = [{**ld, 'node': remap[ld['node']]}
                    for ld in self.loads if ld['node'] not in targets]
        self._support_candidates = [remap[i] for i in self._support_candidates
                                    if i not in targets]
        self._load_nodes = {remap[i]: v for i, v in self._load_nodes.items()
                           if i not in targets}

        self.selected_nodes = set()
        self.selected_member = None
        self.results = None
        self.member_checks = None
        self._refresh_all()
