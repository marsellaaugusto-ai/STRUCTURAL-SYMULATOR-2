"""
Profile sketcher -- Tkinter UI.

A CAD-like Toplevel for drawing a beam's web-opening layout with lines,
circles, rectangles and polygons instead of numeric shape-parameter
fields. Built on top of common.ZoomCanvas for pan/zoom; all geometry,
snapping, validation and data-model conversion live in the tkinter-free
profile_sketcher_math module.

Usage (see perforated_beam_app.py):

    ProfileSketcher(root, length=self.length, section_depth=section.d,
                     existing_openings=self.openings,
                     on_apply=self._apply_sketch_openings)

`on_apply` is called with a list of pbm.OpeningInstance on Apply.
"""
import math
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from common import ZoomCanvas
from apps.perforated_beam import profile_sketcher_math as psm

BG = '#f5f5f3'
ACCENT = '#1a6bbd'
GRID_COLOR = '#e3e3e0'
AXIS_COLOR = '#b5b5b0'
SHAPE_COLOR = '#1a1a1a'
SHAPE_SELECTED = '#d9534f'
CONSTRUCTION_COLOR = '#7fb3e0'
SNAP_MARK_COLOR = '#e8940c'
SUPPORT_COLOR = '#555555'

TOOLS = ['select', 'line', 'circle', 'rectangle', 'polygon']
TOOL_LABELS = {
    'select': 'Select / Move (Esc)',
    'line': 'Line/Polyline (L)',
    'circle': 'Circle (C)',
    'rectangle': 'Rectangle (R)',
    'polygon': 'Polygon (P)',
}
SNAP_TOL_PX = 10


class ProfileSketcher(tk.Toplevel):
    def __init__(self, master, length, section_depth, existing_openings=None,
                 on_apply=None, grid_size=50.0, existing_supports=None):
        super().__init__(master)
        self.title('Sketch opening profile')
        self.geometry('1050x680')
        self.configure(bg=BG)

        self.length = float(length)
        self.section_depth = float(section_depth)
        self.on_apply = on_apply
        self.grid_size = grid_size

        self.shapes = []          # list of CircleShape / PolygonShape
        self.selected = None
        self.tool = tk.StringVar(value='select')
        self.snap_grid = tk.BooleanVar(value=True)
        self.snap_points = tk.BooleanVar(value=True)
        self.ortho = tk.BooleanVar(value=False)
        self._label_seq = 1

        self._draw_pts = []       # vertices placed so far for line/polygon
        self._drag_shape = None
        self._drag_start = None
        self._drag_undo_pushed = False
        self._undo_stack = []
        self._redo_stack = []

        xa, xb = existing_supports if existing_supports else (0.0, self.length)
        self.support_a = xa
        self.support_b = xb
        self._placing_support = None  # None | 'A' | 'B' -- armed by the toolbar buttons

        if existing_openings:
            self._seed_from_openings(existing_openings)

        self._build_ui()
        self.after(50, self._fit_view)
        self.bind('<Key>', self._on_key)

    # ── seeding from existing OpeningInstance list ─────────────────────
    def _seed_from_openings(self, openings):
        mid = self.section_depth / 2.0
        for op in openings:
            verts_abs = [(op.x_center + vx, mid + vy) for vx, vy in op.vertices_local]
            self.shapes.append(psm.PolygonShape(verts_abs, op.label))
            self._bump_label_seq(op.label)

    def _bump_label_seq(self, label):
        digits = ''.join(ch for ch in label if ch.isdigit())
        if digits.isdigit():
            self._label_seq = max(self._label_seq, int(digits) + 1)

    def _next_label(self):
        lbl = f'H{self._label_seq}'
        self._label_seq += 1
        return lbl

    # ── UI layout ────────────────────────────────────────────────────────
    def _build_ui(self):
        toolbar = tk.Frame(self, bg=BG)
        toolbar.pack(side='top', fill='x', padx=4, pady=4)

        self._tool_buttons = {}
        for t in TOOLS:
            b = tk.Button(toolbar, text=TOOL_LABELS[t], relief='flat', bd=0, padx=8,
                          command=lambda t=t: self._set_tool(t))
            b.pack(side='left', padx=2)
            self._tool_buttons[t] = b

        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=6)

        tk.Checkbutton(toolbar, text='Grid snap', variable=self.snap_grid,
                       bg=BG).pack(side='left')
        tk.Checkbutton(toolbar, text='Point snap', variable=self.snap_points,
                       bg=BG).pack(side='left')
        tk.Checkbutton(toolbar, text='Ortho', variable=self.ortho,
                       bg=BG).pack(side='left')

        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=6)
        tk.Label(toolbar, text='Grid (mm):', bg=BG).pack(side='left')
        self.grid_var = tk.DoubleVar(value=self.grid_size)
        tk.Entry(toolbar, textvariable=self.grid_var, width=5).pack(side='left', padx=2)
        tk.Button(toolbar, text='Set', relief='flat', bd=0,
                  command=self._set_grid_size).pack(side='left')

        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=6)
        tk.Button(toolbar, text='Undo', relief='flat', bd=0, command=self._undo).pack(side='left', padx=2)
        tk.Button(toolbar, text='Redo', relief='flat', bd=0, command=self._redo).pack(side='left', padx=2)
        tk.Button(toolbar, text='Array…', relief='flat', bd=0, command=self._array_dialog).pack(side='left', padx=2)
        tk.Button(toolbar, text='Mirror', relief='flat', bd=0, command=self._mirror_selected).pack(side='left', padx=2)
        tk.Button(toolbar, text='Delete', relief='flat', bd=0, command=self._delete_selected).pack(side='left', padx=2)

        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=6)
        tk.Button(toolbar, text='Save sketch…', relief='flat', bd=0, command=self._save_sketch).pack(side='left', padx=2)
        tk.Button(toolbar, text='Load sketch…', relief='flat', bd=0, command=self._load_sketch).pack(side='left', padx=2)

        support_bar = tk.Frame(self, bg=BG)
        support_bar.pack(side='top', fill='x', padx=4, pady=(0, 4))
        tk.Label(support_bar, text='Supports:', bg=BG, font=('Helvetica', 9, 'bold')).pack(side='left')
        self._support_a_btn = tk.Button(support_bar, text='Place support A', relief='flat', bd=0,
                                         command=lambda: self._arm_support('A'))
        self._support_a_btn.pack(side='left', padx=(6, 2))
        self._support_b_btn = tk.Button(support_bar, text='Place support B', relief='flat', bd=0,
                                         command=lambda: self._arm_support('B'))
        self._support_b_btn.pack(side='left', padx=2)
        tk.Button(support_bar, text='Reset to ends', relief='flat', bd=0,
                  command=self._reset_supports).pack(side='left', padx=2)
        self.support_label = tk.Label(support_bar, text='', bg=BG, fg='#444', font=('Helvetica', 8))
        self.support_label.pack(side='left', padx=8)
        tk.Label(support_bar, text='(click a button, then click on the beam to place that support -- '
                                    'overhangs are fine, just keep A left of B)',
                 bg=BG, fg='#888', font=('Helvetica', 7)).pack(side='left', padx=4)

        main = tk.Frame(self, bg=BG)
        main.pack(fill='both', expand=True, padx=4)

        # canvas
        canvas_frame = tk.Frame(main, bg=BG)
        canvas_frame.pack(side='left', fill='both', expand=True)
        self.zc = ZoomCanvas(canvas_frame, bg='white')
        self.zc.pack(fill='both', expand=True)
        # The shared ZoomCanvas' default MIN_ZOOM (0.15) is tuned for
        # smaller diagrams; beam lengths here run into the thousands of
        # mm, so the fit-to-window zoom for a realistic beam can need to
        # go well below that. Loosen it for this instance only.
        self.zc.MIN_ZOOM = min(self.zc.MIN_ZOOM, 0.01)
        self.canvas = self.zc.canvas
        self.zc._on_zoom_changed = self._redraw
        self.canvas.bind('<Motion>', self._on_motion)
        self.canvas.bind('<Button-1>', self._on_click)
        self.canvas.bind('<Double-Button-1>', self._on_double_click)
        self.canvas.bind('<B1-Motion>', self._on_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_release)
        self.canvas.bind('<Configure>', lambda e: self._redraw())

        # side panel
        side = tk.Frame(main, bg=BG, width=220)
        side.pack(side='left', fill='y', padx=(6, 0))
        side.pack_propagate(False)

        tk.Label(side, text='Shapes', bg=BG, font=('Helvetica', 9, 'bold')).pack(anchor='w')
        self.shape_list = tk.Listbox(side, height=14)
        self.shape_list.pack(fill='x', pady=2)
        self.shape_list.bind('<<ListboxSelect>>', self._on_list_select)

        tk.Label(side, text='Precision entry:', bg=BG, font=('Helvetica', 8)).pack(anchor='w', pady=(8, 0))
        tk.Label(side, text='x,y | @dx,dy | length<angle', bg=BG, fg='#888',
                 font=('Helvetica', 7)).pack(anchor='w')
        self.entry_var = tk.StringVar()
        entry = tk.Entry(side, textvariable=self.entry_var)
        entry.pack(fill='x', pady=2)
        entry.bind('<Return>', self._on_typed_entry)

        tk.Label(side, text='For Circle: type diameter after placing center.\n'
                             'For Rectangle: type width,height after first corner.',
                 bg=BG, fg='#888', font=('Helvetica', 7), justify='left',
                 wraplength=200).pack(anchor='w', pady=(4, 8))

        ttk.Separator(side, orient='horizontal').pack(fill='x', pady=6)
        tk.Button(side, text='Apply to analysis', relief='flat', bd=0, bg=ACCENT, fg='white',
                  command=self._apply).pack(fill='x', pady=2)
        tk.Button(side, text='Cancel', relief='flat', bd=0,
                  command=self.destroy).pack(fill='x', pady=2)

        self.status = tk.Label(self, text='', bg=BG, anchor='w', font=('Helvetica', 8))
        self.status.pack(side='bottom', fill='x', padx=4)

        self._refresh_shape_list()
        self._update_support_label()
        self._set_tool('select')

    # ── tool state ───────────────────────────────────────────────────────
    def _set_tool(self, t):
        self.tool.set(t)
        self._draw_pts = []
        for name, btn in self._tool_buttons.items():
            btn.configure(relief='sunken' if name == t else 'flat',
                          bg=ACCENT if name == t else BG,
                          fg='white' if name == t else 'black')
        if hasattr(self, 'canvas'):
            self._redraw()

    def _set_grid_size(self):
        try:
            self.grid_size = max(1.0, float(self.grid_var.get()))
        except (TypeError, ValueError):
            pass
        self._redraw()

    def _on_key(self, event):
        # Don't let single-key tool shortcuts (or Delete/Ctrl+Z/Ctrl+Y)
        # fire while the user is typing into a text field -- Escape is
        # the one exception, since "cancel/get me out of this" should
        # always work regardless of focus.
        focused = self.focus_get()
        if isinstance(focused, (tk.Entry, tk.Spinbox, tk.Text)) and event.keysym.lower() != 'escape':
            return
        key = event.keysym.lower()
        if key == 'escape':
            self._draw_pts = []
            self._disarm_support_buttons()
            self._set_tool('select')
        elif key == 'l':
            self._set_tool('line')
        elif key == 'c':
            self._set_tool('circle')
        elif key == 'r':
            self._set_tool('rectangle')
        elif key == 'p':
            self._set_tool('polygon')
        elif key == 'delete':
            self._delete_selected()
        elif key == 'z' and (event.state & 0x4):
            self._undo()
        elif key == 'y' and (event.state & 0x4):
            self._redo()
        elif key == 'return':
            self._close_loop()

    # ── coordinate helpers (world y-up, unlike raw ZoomCanvas which is y-down) ──
    def _w2s(self, wx, wy):
        return self.zc.w2s(wx, -wy)

    def _s2w(self, sx, sy):
        wx, wy = self.zc.s2w(sx, sy)
        return wx, -wy

    def _event_world(self, event):
        return self._s2w(event.x, event.y)

    def _px_to_world(self, px):
        return px / self.zc.zoom

    # ── snapping ─────────────────────────────────────────────────────────
    def _snap(self, world_pt, exclude=None):
        pt = world_pt
        tol = self._px_to_world(SNAP_TOL_PX)
        if self.snap_points.get():
            cands = (psm.endpoint_candidates(self.shapes) +
                     psm.midpoint_candidates(self.shapes) +
                     psm.center_candidates(self.shapes))
            hit = psm.nearest_candidate(pt, cands, tol)
            if hit is not None:
                return hit, True
        if self.snap_grid.get():
            return psm.snap_to_grid(pt, self.grid_size), False
        return pt, False

    def _apply_ortho(self, ref, pt):
        if not self.ortho.get() or ref is None:
            return pt
        dx, dy = pt[0] - ref[0], pt[1] - ref[1]
        if abs(dx) >= abs(dy):
            return pt[0], ref[1]
        return ref[0], pt[1]

    # ── history ──────────────────────────────────────────────────────────
    def _push_undo(self):
        self._undo_stack.append(psm.serialize_shapes(self.shapes))
        self._redo_stack.clear()

    def _undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(psm.serialize_shapes(self.shapes))
        text = self._undo_stack.pop()
        self.shapes, _ = psm.deserialize_shapes(text)
        self.selected = None
        self._refresh_shape_list()
        self._redraw()

    def _redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(psm.serialize_shapes(self.shapes))
        text = self._redo_stack.pop()
        self.shapes, _ = psm.deserialize_shapes(text)
        self.selected = None
        self._refresh_shape_list()
        self._redraw()

    # ── mouse events ─────────────────────────────────────────────────────
    def _on_motion(self, event):
        wx, wy = self._event_world(event)
        pt, snapped = self._snap((wx, wy))
        if self._placing_support is not None:
            x = max(0.0, min(self.length, pt[0]))
            self.status.configure(text=f'Click to place support {self._placing_support} at x={x:.1f} mm '
                                        '(Esc to cancel)')
            self._redraw(preview_point=pt)
            self._draw_support(x, self._placing_support, preview=True)
            return
        ref = self._draw_pts[-1] if self._draw_pts else None
        if ref is not None:
            pt = self._apply_ortho(ref, pt)
            length = math.hypot(pt[0] - ref[0], pt[1] - ref[1])
            angle = math.degrees(math.atan2(pt[1] - ref[1], pt[0] - ref[0]))
            self.status.configure(
                text=f'x={pt[0]:.1f}  y={pt[1]:.1f} mm   |   length={length:.1f} mm  angle={angle:.1f}°'
                     + ('   [snap]' if snapped else ''))
        else:
            self.status.configure(text=f'x={pt[0]:.1f}  y={pt[1]:.1f} mm' + ('   [snap]' if snapped else ''))
        self._redraw(preview_point=pt)

    # ── supports ─────────────────────────────────────────────────────────
    def _arm_support(self, which):
        self._placing_support = which
        self._support_a_btn.configure(relief='sunken' if which == 'A' else 'flat',
                                       bg=ACCENT if which == 'A' else BG,
                                       fg='white' if which == 'A' else 'black')
        self._support_b_btn.configure(relief='sunken' if which == 'B' else 'flat',
                                       bg=ACCENT if which == 'B' else BG,
                                       fg='white' if which == 'B' else 'black')
        self.status.configure(text=f'Click on the beam to place support {which}.')

    def _disarm_support_buttons(self):
        self._placing_support = None
        self._support_a_btn.configure(relief='flat', bg=BG, fg='black')
        self._support_b_btn.configure(relief='flat', bg=BG, fg='black')

    def _reset_supports(self):
        self.support_a, self.support_b = 0.0, self.length
        self._disarm_support_buttons()
        self._update_support_label()
        self._redraw()

    def _update_support_label(self):
        self.support_label.configure(text=f'A = {self.support_a:.0f} mm    B = {self.support_b:.0f} mm')

    def _on_click(self, event):
        wx, wy = self._event_world(event)
        pt, _ = self._snap((wx, wy))

        if self._placing_support is not None:
            x = max(0.0, min(self.length, pt[0]))
            if self._placing_support == 'A':
                self.support_a = x
            else:
                self.support_b = x
            self._placing_support = None
            self._update_support_label()
            self._redraw()
            return

        tool = self.tool.get()

        if tool == 'select':
            self._select_at(pt)
            if self.selected is not None:
                self._drag_shape = self.selected
                self._drag_start = pt
                self._drag_undo_pushed = False  # push lazily, only if it actually moves
            return

        ref = self._draw_pts[-1] if self._draw_pts else None
        pt = self._apply_ortho(ref, pt) if ref else pt

        if tool == 'line' or tool == 'polygon':
            if self._draw_pts and psm._dist(pt, self._draw_pts[0]) <= self._px_to_world(SNAP_TOL_PX):
                self._close_loop()
                return
            self._draw_pts.append(pt)
        elif tool == 'circle':
            self._draw_pts.append(pt)
            if len(self._draw_pts) == 2:
                center, edge = self._draw_pts
                diameter = 2 * psm._dist(center, edge)
                self._finish_circle(center, diameter)
        elif tool == 'rectangle':
            self._draw_pts.append(pt)
            if len(self._draw_pts) == 2:
                self._finish_rectangle(self._draw_pts[0], self._draw_pts[1])
        self._redraw()

    def _on_double_click(self, event):
        if self.tool.get() in ('line', 'polygon'):
            self._close_loop()

    def _on_drag(self, event):
        if self.tool.get() != 'select' or self._drag_shape is None:
            return
        wx, wy = self._event_world(event)
        pt, _ = self._snap((wx, wy))
        if not self._drag_undo_pushed:
            # Snapshot BEFORE the first actual move of this drag, so undo
            # restores the pre-drag position. A plain click-with-no-move
            # (just selecting) never touches the undo stack at all.
            self._push_undo()
            self._drag_undo_pushed = True
        dx, dy = pt[0] - self._drag_start[0], pt[1] - self._drag_start[1]
        self._drag_start = pt
        idx = self.shapes.index(self._drag_shape)
        self.shapes[idx] = psm.translate_shape(self._drag_shape, dx, dy)
        self._drag_shape = self.shapes[idx]
        self.selected = self._drag_shape
        self._redraw()

    def _on_release(self, event):
        self._drag_shape = None
        self._drag_start = None
        self._drag_undo_pushed = False

    # ── typed precision entry ───────────────────────────────────────────
    def _on_typed_entry(self, event):
        text = self.entry_var.get()
        self.entry_var.set('')
        tool = self.tool.get()
        # Enter on an empty box is the AutoCAD-style "done, close the
        # loop now" gesture for Line/Polyline/Polygon -- handle it
        # directly instead of letting it fall through to parse_typed_entry
        # (which would just raise "empty entry").
        if not text.strip():
            if tool in ('line', 'polygon'):
                self._close_loop()
            return 'break'
        try:
            if tool == 'circle' and len(self._draw_pts) == 1:
                diameter = float(text)
                self._finish_circle(self._draw_pts[0], diameter)
                return 'break'
            if tool == 'rectangle' and len(self._draw_pts) == 1:
                w, h = (float(v) for v in text.split(','))
                x0, y0 = self._draw_pts[0]
                self._finish_rectangle((x0, y0), (x0 + w, y0 + h))
                return 'break'
            ref = self._draw_pts[-1] if self._draw_pts else None
            pt = psm.parse_typed_entry(text, ref_point=ref)
        except ValueError as exc:
            messagebox.showerror('Precision entry', str(exc), parent=self)
            return 'break'
        if tool in ('line', 'polygon'):
            if self._draw_pts and psm._dist(pt, self._draw_pts[0]) <= 1e-6:
                self._close_loop()
                return 'break'
            self._draw_pts.append(pt)
        self._redraw()
        return 'break'

    # ── finishing shapes ─────────────────────────────────────────────────
    def _finish_circle(self, center, diameter):
        if diameter <= 0:
            self._draw_pts = []
            self.status.configure(text='Circle needs a nonzero radius -- discarded.')
            return
        self._push_undo()
        self.shapes.append(psm.CircleShape(center, diameter, self._next_label()))
        self._draw_pts = []
        self._refresh_shape_list()
        self._set_tool('select')

    def _finish_rectangle(self, c1, c2):
        x0, y0 = c1
        x1, y1 = c2
        if abs(x1 - x0) < 1e-6 or abs(y1 - y0) < 1e-6:
            self._draw_pts = []
            self.status.configure(text='Rectangle needs nonzero width and height -- discarded.')
            return
        verts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        self._push_undo()
        self.shapes.append(psm.PolygonShape(verts, self._next_label()))
        self._draw_pts = []
        self._refresh_shape_list()
        self._set_tool('select')

    def _close_loop(self):
        if len(self._draw_pts) < 3:
            self._draw_pts = []
            self._redraw()
            return
        ok, msg = psm.validate_polygon(self._draw_pts)
        if not ok:
            if not messagebox.askyesno(
                    'Invalid shape',
                    f'This outline is {msg}.\n\n'
                    'It cannot be used in the analysis until fixed. Keep it in the '
                    'sketch anyway (edit later), or discard it?',
                    parent=self):
                self._draw_pts = []
                self._redraw()
                return
        self._push_undo()
        self.shapes.append(psm.PolygonShape(list(self._draw_pts), self._next_label()))
        self._draw_pts = []
        self._refresh_shape_list()
        self._set_tool('select')

    # ── selection / editing ──────────────────────────────────────────────
    def _select_at(self, pt):
        """Picks the topmost shape actually under/near `pt`, or None if
        the click didn't land close enough to anything. Circles hit-test
        against "inside the disc, or within tol of the ring"; polygons
        hit-test against "inside the outline, or within tol of an edge" --
        there is always a real distance cutoff, so clicking empty canvas
        correctly selects nothing."""
        tol = self._px_to_world(8)
        best = None
        best_d = None
        for s in self.shapes:
            if s.kind == 'circle':
                cx, cy = s.center
                r = s.diameter / 2.0
                dist_c = psm._dist(pt, (cx, cy))
                if dist_c > r + tol:
                    continue
                d = dist_c
            else:
                inside = psm.point_in_polygon(pt, s.vertices)
                edge_d = psm.point_to_polygon_distance(pt, s.vertices)
                if not inside and edge_d > tol:
                    continue
                cx, cy = psm.polygon_centroid(s.vertices)
                d = psm._dist(pt, (cx, cy))
            if best_d is None or d < best_d:
                best, best_d = s, d
        self.selected = best
        self._sync_list_selection()
        self._redraw()

    def _sync_list_selection(self):
        self.shape_list.selection_clear(0, tk.END)
        if self.selected in self.shapes:
            self.shape_list.selection_set(self.shapes.index(self.selected))

    def _on_list_select(self, event):
        sel = self.shape_list.curselection()
        if sel:
            self.selected = self.shapes[sel[0]]
        self._redraw()

    def _delete_selected(self):
        if self.selected is None:
            return
        self._push_undo()
        self.shapes.remove(self.selected)
        self.selected = None
        self._refresh_shape_list()
        self._redraw()

    def _mirror_selected(self):
        if self.selected is None:
            messagebox.showinfo('Mirror', 'Select a shape first.', parent=self)
            return
        self._push_undo()
        mirrored = psm.mirror_shape_vertically(self.selected, self.section_depth / 2.0)
        mirrored.label = self._next_label()
        self.shapes.append(mirrored)
        self._refresh_shape_list()
        self._redraw()

    def _array_dialog(self):
        if self.selected is None:
            messagebox.showinfo('Array', 'Select a shape first.', parent=self)
            return
        win = tk.Toplevel(self)
        win.title('Array along beam')
        win.configure(bg=BG)
        tk.Label(win, text='Count (incl. original):', bg=BG).grid(row=0, column=0, padx=4, pady=4, sticky='w')
        count_var = tk.IntVar(value=6)
        tk.Entry(win, textvariable=count_var, width=6).grid(row=0, column=1, padx=4)
        tk.Label(win, text='Spacing, c-c (mm):', bg=BG).grid(row=1, column=0, padx=4, pady=4, sticky='w')
        spacing_var = tk.DoubleVar(value=600.0)
        tk.Entry(win, textvariable=spacing_var, width=6).grid(row=1, column=1, padx=4)

        def do_array():
            try:
                n = int(count_var.get())
                spacing = float(spacing_var.get())
            except (TypeError, ValueError):
                return
            self._push_undo()
            base = self.selected
            for i in range(1, n):
                copy = psm.translate_shape(base, spacing * i, 0.0)
                copy.label = self._next_label()
                self.shapes.append(copy)
            self._refresh_shape_list()
            self._redraw()
            win.destroy()

        tk.Button(win, text='Create array', command=do_array, relief='flat', bd=0,
                  bg=ACCENT, fg='white').grid(row=2, column=0, columnspan=2, pady=8)

    def _refresh_shape_list(self):
        self.shape_list.delete(0, tk.END)
        for s in self.shapes:
            desc = f'⌀{s.diameter:.0f}' if s.kind == 'circle' else f'{len(s.vertices)}-gon'
            self.shape_list.insert(tk.END, f'{s.label}  ({desc})')

    # ── save / load ──────────────────────────────────────────────────────
    def _save_sketch(self):
        path = filedialog.asksaveasfilename(defaultextension='.json',
                                             filetypes=[('Sketch JSON', '*.json')],
                                             parent=self)
        if not path:
            return
        meta = {'length': self.length, 'section_depth': self.section_depth}
        with open(path, 'w') as f:
            f.write(psm.serialize_shapes(self.shapes, meta=meta))

    def _load_sketch(self):
        path = filedialog.askopenfilename(filetypes=[('Sketch JSON', '*.json')], parent=self)
        if not path:
            return
        with open(path) as f:
            text = f.read()
        try:
            shapes, meta = psm.deserialize_shapes(text)
        except (ValueError, KeyError) as exc:
            messagebox.showerror('Load sketch', f'Could not read file: {exc}', parent=self)
            return
        self._push_undo()
        self.shapes = shapes
        self.selected = None
        for s in self.shapes:
            self._bump_label_seq(s.label)
        self._refresh_shape_list()
        self._redraw()

    # ── apply to analysis ────────────────────────────────────────────────
    def _apply(self):
        try:
            openings = psm.shapes_to_openings(self.shapes, self.section_depth)
        except ValueError as exc:
            messagebox.showerror('Cannot apply', str(exc), parent=self)
            return
        if self.support_a >= self.support_b:
            messagebox.showerror('Cannot apply', 'Support A must be to the left of support B '
                                                   f'(currently A={self.support_a:.0f}, B={self.support_b:.0f}).',
                                  parent=self)
            return
        if self.on_apply:
            self.on_apply(openings, (self.support_a, self.support_b))
        self.destroy()

    # ── drawing ──────────────────────────────────────────────────────────
    def _fit_view(self):
        w = max(self.canvas.winfo_width(), 100)
        h = max(self.canvas.winfo_height(), 100)
        margin = 60
        pad = self.section_depth * 0.6
        zx = (w - 2 * margin) / max(self.length, 1.0)
        zy = (h - 2 * margin) / max(self.section_depth + 2 * pad, 1.0)
        self.zc.zoom = max(self.zc.MIN_ZOOM, min(self.zc.MAX_ZOOM, min(zx, zy)))
        # screen_x = (wx + pan_x) * zoom  -> put beam start `margin` px from the left
        self.zc.pan_x = margin / self.zc.zoom
        # our _w2s flips y (screen_y = (-wy + pan_y) * zoom) -> center the
        # beam's mid-depth vertically in the canvas
        self.zc.pan_y = (h / (2.0 * self.zc.zoom)) + self.section_depth / 2.0
        self._redraw()

    def _redraw(self, preview_point=None):
        c = self.canvas
        c.delete('all')
        self._draw_grid()
        self._draw_envelope()
        for s in self.shapes:
            self._draw_shape(s, selected=(s is self.selected))
        self._draw_in_progress(preview_point)

    def _draw_grid(self):
        if not self.snap_grid.get():
            return
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        g = self.grid_size
        if g * self.zc.zoom < 6:
            return  # too dense to be useful, skip
        x0w, y0w = self._s2w(0, 0)
        x1w, y1w = self._s2w(w, h)
        xmin, xmax = sorted((x0w, x1w))
        ymin, ymax = sorted((y0w, y1w))
        start_x = math.floor(xmin / g) * g
        x = start_x
        while x <= xmax:
            sx0, _ = self._w2s(x, ymin)
            sx1, _ = self._w2s(x, ymax)
            c.create_line(sx0, 0, sx1, h, fill=GRID_COLOR)
            x += g
        start_y = math.floor(ymin / g) * g
        y = start_y
        while y <= ymax:
            _, sy0 = self._w2s(xmin, y)
            c.create_line(0, sy0, w, sy0, fill=GRID_COLOR)
            y += g

    def _draw_envelope(self):
        c = self.canvas
        x0, y0 = self._w2s(0, 0)
        x1, y1 = self._w2s(self.length, self.section_depth)
        c.create_rectangle(x0, y0, x1, y1, outline=AXIS_COLOR, width=1, dash=(4, 2))
        mx0, my = self._w2s(0, self.section_depth / 2.0)
        mx1, _ = self._w2s(self.length, self.section_depth / 2.0)
        c.create_line(mx0, my, mx1, my, fill=AXIS_COLOR, dash=(6, 3))
        c.create_text(x0 + 4, y1 - 10, anchor='w', fill='#999',
                       text=f'Beam envelope {self.length:.0f} × {self.section_depth:.0f} mm '
                            '(reference only, not exported)',
                       font=('Helvetica', 7))
        self._draw_support(self.support_a, 'A')
        self._draw_support(self.support_b, 'B')

    def _draw_support(self, x, label, preview=False):
        c = self.canvas
        sx, sy = self._w2s(x, 0.0)
        size = 9
        color = CONSTRUCTION_COLOR if preview else SUPPORT_COLOR
        c.create_polygon(sx, sy, sx - size, sy + size * 1.6, sx + size, sy + size * 1.6,
                          outline=color, fill='' if preview else color, width=2)
        c.create_text(sx, sy + size * 1.6 + 10, text=label, fill=color, font=('Helvetica', 8, 'bold'))

    def _draw_shape(self, s, selected=False):
        c = self.canvas
        color = SHAPE_SELECTED if selected else SHAPE_COLOR
        width = 2 if selected else 1
        if s.kind == 'circle':
            cx, cy = s.center
            r = s.diameter / 2.0
            x0, y0 = self._w2s(cx - r, cy - r)
            x1, y1 = self._w2s(cx + r, cy + r)
            c.create_oval(x0, y0, x1, y1, outline=color, width=width)
            lx, ly = self._w2s(cx, cy)
        else:
            pts = []
            for vx, vy in s.vertices:
                pts.extend(self._w2s(vx, vy))
            c.create_polygon(pts, outline=color, fill='', width=width)
            cx, cy = psm.polygon_centroid(s.vertices)
            lx, ly = self._w2s(cx, cy)
        c.create_text(lx, ly, text=s.label, fill=color, font=('Helvetica', 8, 'bold'))

    def _draw_in_progress(self, preview_point):
        c = self.canvas
        tool = self.tool.get()
        if not self._draw_pts:
            return
        pts_screen = [self._w2s(*p) for p in self._draw_pts]
        if tool in ('line', 'polygon'):
            flat = [v for p in pts_screen for v in p]
            if len(pts_screen) > 1:
                c.create_line(*flat, fill=CONSTRUCTION_COLOR, width=1, dash=(3, 2))
            if preview_point is not None:
                lastx, lasty = self._w2s(*self._draw_pts[-1])
                px, py = self._w2s(*preview_point)
                c.create_line(lastx, lasty, px, py, fill=CONSTRUCTION_COLOR, width=1, dash=(2, 2))
            for sx, sy in pts_screen:
                c.create_oval(sx - 3, sy - 3, sx + 3, sy + 3, outline=CONSTRUCTION_COLOR)
        elif tool == 'circle' and len(self._draw_pts) == 1 and preview_point is not None:
            cx, cy = self._draw_pts[0]
            r = psm._dist(self._draw_pts[0], preview_point)
            x0, y0 = self._w2s(cx - r, cy - r)
            x1, y1 = self._w2s(cx + r, cy + r)
            c.create_oval(x0, y0, x1, y1, outline=CONSTRUCTION_COLOR, dash=(3, 2))
        elif tool == 'rectangle' and len(self._draw_pts) == 1 and preview_point is not None:
            x0, y0 = self._w2s(*self._draw_pts[0])
            x1, y1 = self._w2s(*preview_point)
            c.create_rectangle(x0, y0, x1, y1, outline=CONSTRUCTION_COLOR, dash=(3, 2))
