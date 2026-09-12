"""
Custom section-profile designer -- Tkinter UI.

Draws a SINGLE continuous closed outline (a cross-section's own outer
boundary) using Line and 3-point-Arc segments, then converts it to a
perforated_beam_math.CustomProfileSection on Apply. Companion to
profile_sketcher_ui.py (which draws web OPENINGS instead) -- built on the
same ZoomCanvas foundation and reusing profile_sketcher_math's snapping
and typed-entry helpers, but the data model here is one path, not several
independent shapes, so the tool surface is simpler (no select/move/array).
"""
import math
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from common import ZoomCanvas
from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import profile_sketcher_math as psm
from apps.perforated_beam import section_profile_math as secm

BG = '#f5f5f3'
ACCENT = '#1a6bbd'
GRID_COLOR = '#e3e3e0'
AXIS_COLOR = '#b5b5b0'
OUTLINE_COLOR = '#1a1a1a'
CONSTRUCTION_COLOR = '#7fb3e0'
CLOSE_HINT_COLOR = '#2e9e4f'
SNAP_TOL_PX = 10

TOOLS = ['line', 'arc']
TOOL_LABELS = {'line': 'Line (L)', 'arc': '3-point Arc (A)'}


class SectionProfileDesigner(tk.Toplevel):
    def __init__(self, master, on_apply=None, grid_size=10.0, existing_outline=None):
        super().__init__(master)
        self.title('Design custom section profile')
        self.geometry('1000x650')
        self.configure(bg=BG)

        self.on_apply = on_apply
        self.grid_size = grid_size
        self.outline = existing_outline if existing_outline is not None else secm.SectionOutline()
        self.tool = tk.StringVar(value='line')
        self.snap_grid = tk.BooleanVar(value=True)
        self.snap_points = tk.BooleanVar(value=True)
        self._pending_arc_through = None

        self._build_ui()
        self.after(50, self._fit_view)
        self.bind('<Key>', self._on_key)

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
        tk.Checkbutton(toolbar, text='Grid snap', variable=self.snap_grid, bg=BG).pack(side='left')
        tk.Checkbutton(toolbar, text='Point snap', variable=self.snap_points, bg=BG).pack(side='left')

        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=6)
        tk.Label(toolbar, text='Grid (mm):', bg=BG).pack(side='left')
        self.grid_var = tk.DoubleVar(value=self.grid_size)
        tk.Entry(toolbar, textvariable=self.grid_var, width=5).pack(side='left', padx=2)
        tk.Button(toolbar, text='Set', relief='flat', bd=0, command=self._set_grid_size).pack(side='left')

        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=6)
        tk.Button(toolbar, text='Undo', relief='flat', bd=0, command=self._undo).pack(side='left', padx=2)
        tk.Button(toolbar, text='Clear all', relief='flat', bd=0, command=self._clear_all).pack(side='left', padx=2)
        tk.Button(toolbar, text='Close loop', relief='flat', bd=0, command=self._close_loop).pack(side='left', padx=2)

        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=6)
        tk.Button(toolbar, text='Save…', relief='flat', bd=0, command=self._save).pack(side='left', padx=2)
        tk.Button(toolbar, text='Load…', relief='flat', bd=0, command=self._load).pack(side='left', padx=2)

        main = tk.Frame(self, bg=BG)
        main.pack(fill='both', expand=True, padx=4)

        canvas_frame = tk.Frame(main, bg=BG)
        canvas_frame.pack(side='left', fill='both', expand=True)
        self.zc = ZoomCanvas(canvas_frame, bg='white')
        self.zc.pack(fill='both', expand=True)
        self.zc.MIN_ZOOM = min(self.zc.MIN_ZOOM, 0.01)  # section profiles can be large; see profile_sketcher_ui
        self.canvas = self.zc.canvas
        self.zc._on_zoom_changed = self._redraw
        self.canvas.bind('<Motion>', self._on_motion)
        self.canvas.bind('<Button-1>', self._on_click)
        self.canvas.bind('<Configure>', lambda e: self._redraw())

        side = tk.Frame(main, bg=BG, width=240)
        side.pack(side='left', fill='y', padx=(6, 0))
        side.pack_propagate(False)

        tk.Label(side, text='Section properties', bg=BG, font=('Helvetica', 9, 'bold')).pack(anchor='w')
        self.props_label = tk.Label(side, text='(not closed yet)', bg=BG, justify='left',
                                     font=('Courier', 9), fg='#444')
        self.props_label.pack(anchor='w', pady=(2, 8))

        tk.Label(side, text='Precision entry:', bg=BG, font=('Helvetica', 8)).pack(anchor='w')
        tk.Label(side, text='x,y | @dx,dy | length<angle', bg=BG, fg='#888',
                 font=('Helvetica', 7)).pack(anchor='w')
        self.entry_var = tk.StringVar()
        entry = tk.Entry(side, textvariable=self.entry_var)
        entry.pack(fill='x', pady=2)
        entry.bind('<Return>', self._on_typed_entry)
        tk.Label(side, text='Arc tool: first typed/clicked point after the\n'
                             'start is the "through" point, second is the end.',
                 bg=BG, fg='#888', font=('Helvetica', 7), justify='left',
                 wraplength=220).pack(anchor='w', pady=(4, 8))

        ttk.Separator(side, orient='horizontal').pack(fill='x', pady=6)
        tk.Button(side, text='Apply as section', relief='flat', bd=0, bg=ACCENT, fg='white',
                  command=self._apply).pack(fill='x', pady=2)
        tk.Button(side, text='Cancel', relief='flat', bd=0, command=self.destroy).pack(fill='x', pady=2)

        self.status = tk.Label(self, text='', bg=BG, anchor='w', font=('Helvetica', 8))
        self.status.pack(side='bottom', fill='x', padx=4)

        self._set_tool('line')
        self._update_props_label()

    # ── tool state ───────────────────────────────────────────────────────
    def _set_tool(self, t):
        self.tool.set(t)
        self._pending_arc_through = None
        for name, btn in self._tool_buttons.items():
            btn.configure(relief='sunken' if name == t else 'flat',
                          bg=ACCENT if name == t else BG,
                          fg='white' if name == t else 'black')
        if hasattr(self, 'canvas'):
            self._redraw()

    def _set_grid_size(self):
        try:
            self.grid_size = max(1.0, float(self.grid_var.get()))
        except (TypeError, ValueError, tk.TclError):
            self.status.configure(text='Grid size must be a number -- ignored.')
            return
        self._redraw()

    def _on_key(self, event):
        focused = self.focus_get()
        if isinstance(focused, (tk.Entry, tk.Spinbox, tk.Text)) and event.keysym.lower() != 'escape':
            return
        key = event.keysym.lower()
        if key == 'escape':
            self._pending_arc_through = None
            self._redraw()
        elif key == 'l':
            self._set_tool('line')
        elif key == 'a':
            self._set_tool('arc')
        elif key == 'z' and (event.state & 0x4):
            self._undo()
        elif key == 'return':
            self._close_loop()

    # ── coordinates (y-up world, matching profile_sketcher_ui's convention) ──
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
    def _snap(self, world_pt):
        pt = world_pt
        tol = self._px_to_world(SNAP_TOL_PX)
        if self.snap_points.get():
            pts = self.outline.flatten()
            if self.outline.start_point:
                pts.append(self.outline.start_point)
            hit = psm.nearest_candidate(pt, pts, tol)
            if hit is not None:
                return hit, True
        if self.snap_grid.get():
            return psm.snap_to_grid(pt, self.grid_size), False
        return pt, False

    # ── editing ──────────────────────────────────────────────────────────
    def _undo(self):
        if self._pending_arc_through is not None:
            self._pending_arc_through = None
            self._redraw()
            return
        self.outline.undo_last()
        self._update_props_label()
        self._redraw()

    def _clear_all(self):
        self.outline.clear()
        self._pending_arc_through = None
        self._update_props_label()
        self._redraw()

    # ── mouse events ─────────────────────────────────────────────────────
    def _on_motion(self, event):
        wx, wy = self._event_world(event)
        pt, snapped = self._snap((wx, wy))
        ref = self.outline.last_point() if self._pending_arc_through is None else self._pending_arc_through
        if ref is not None:
            length = math.hypot(pt[0] - ref[0], pt[1] - ref[1])
            angle = math.degrees(math.atan2(pt[1] - ref[1], pt[0] - ref[0]))
            self.status.configure(
                text=f'x={pt[0]:.1f}  y={pt[1]:.1f} mm   |   length={length:.1f} mm  angle={angle:.1f}°'
                     + ('   [snap]' if snapped else ''))
        else:
            self.status.configure(text=f'x={pt[0]:.1f}  y={pt[1]:.1f} mm' + ('   [snap]' if snapped else ''))
        self._redraw(preview_point=pt)

    def _on_click(self, event):
        wx, wy = self._event_world(event)
        pt, _ = self._snap((wx, wy))

        if self.outline.start_point is None:
            self.outline.start_point = pt
            self._update_props_label()
            self._redraw()
            return

        tol = self._px_to_world(SNAP_TOL_PX)
        tool = self.tool.get()
        if tool == 'line':
            if self.outline.segments and psm._dist(pt, self.outline.start_point) <= tol:
                self._close_loop()
                return
            self.outline.add_line(pt)
        elif tool == 'arc':
            if self._pending_arc_through is None:
                self._pending_arc_through = pt
                self._redraw()
                return
            if psm._dist(pt, self.outline.start_point) <= tol:
                # closing via arc back to the start point
                self.outline.add_arc(self._pending_arc_through, self.outline.start_point)
                self._pending_arc_through = None
                self._finish_close()
                return
            self.outline.add_arc(self._pending_arc_through, pt)
            self._pending_arc_through = None
        self._update_props_label()
        self._redraw()

    # ── typed precision entry ───────────────────────────────────────────
    def _on_typed_entry(self, event):
        text = self.entry_var.get()
        self.entry_var.set('')
        if not text.strip():
            self._close_loop()
            return 'break'
        ref = self.outline.last_point() if self._pending_arc_through is None else self._pending_arc_through
        try:
            pt = psm.parse_typed_entry(text, ref_point=ref)
        except ValueError as exc:
            messagebox.showerror('Precision entry', str(exc), parent=self)
            return 'break'

        if self.outline.start_point is None:
            self.outline.start_point = pt
            self._update_props_label()
            self._redraw()
            return 'break'

        tool = self.tool.get()
        if tool == 'line':
            if self.outline.segments and psm._dist(pt, self.outline.start_point) <= 1e-6:
                self._close_loop()
                return 'break'
            self.outline.add_line(pt)
        elif tool == 'arc':
            if self._pending_arc_through is None:
                self._pending_arc_through = pt
                self._redraw()
                return 'break'
            self.outline.add_arc(self._pending_arc_through, pt)
            self._pending_arc_through = None
        self._update_props_label()
        self._redraw()
        return 'break'

    # ── closing / properties ─────────────────────────────────────────────
    def _close_loop(self):
        if self.outline.start_point is None or not self.outline.segments:
            return
        self._finish_close()

    def _finish_close(self):
        ok, msg = self.outline.validate()
        if not ok:
            messagebox.showwarning('Not a valid closed shape', msg, parent=self)
            return
        self._update_props_label()
        self._redraw()
        self.status.configure(text='Outline closed. Review the properties, then Apply, or keep editing.')

    def _update_props_label(self):
        ok, msg = self.outline.validate()
        if not ok:
            self.props_label.configure(text=f'(not ready: {msg})')
            return
        try:
            sec = self.outline.to_section('preview')
        except ValueError as exc:
            self.props_label.configure(text=f'(not ready: {exc})')
            return
        cx, cy = sec.centroid
        self.props_label.configure(text=(
            f'A     = {sec.A:10.1f} mm^2\n'
            f'I     = {sec.I:10.1f} mm^4\n'
            f'd     = {sec.d:10.1f} mm\n'
            f'S_top = {sec.S_top:10.1f} mm^3\n'
            f'S_bot = {sec.S_bot:10.1f} mm^3\n'
            f'centroid = ({cx:.1f}, {cy:.1f})'
        ))

    # ── save / load ──────────────────────────────────────────────────────
    def _save(self):
        path = filedialog.asksaveasfilename(defaultextension='.json',
                                             filetypes=[('Section profile JSON', '*.json')], parent=self)
        if not path:
            return
        try:
            with open(path, 'w') as f:
                f.write(secm.serialize_outline(self.outline))
        except OSError as exc:
            messagebox.showerror('Save', f'Could not save: {exc}', parent=self)

    def _load(self):
        path = filedialog.askopenfilename(filetypes=[('Section profile JSON', '*.json')], parent=self)
        if not path:
            return
        try:
            with open(path) as f:
                text = f.read()
            outline, _meta = secm.deserialize_outline(text)
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror('Load', f'Could not load: {exc}', parent=self)
            return
        self.outline = outline
        self._pending_arc_through = None
        self._update_props_label()
        self._redraw()

    # ── apply ────────────────────────────────────────────────────────────
    def _apply(self):
        try:
            sec = self.outline.to_section('custom')
        except ValueError as exc:
            messagebox.showerror('Cannot apply', str(exc), parent=self)
            return
        if self.on_apply:
            self.on_apply(sec, self.outline)
        self.destroy()

    # ── drawing ──────────────────────────────────────────────────────────
    def _fit_view(self):
        w = max(self.canvas.winfo_width(), 100)
        h = max(self.canvas.winfo_height(), 100)
        margin = 60
        pts = self.outline.flatten()
        if len(pts) < 2:
            self.zc.zoom = 1.0
            self.zc.pan_x = w / (2 * self.zc.zoom)
            self.zc.pan_y = h / (2 * self.zc.zoom)
            self._redraw()
            return
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        span_x = max(max(xs) - min(xs), 1.0)
        span_y = max(max(ys) - min(ys), 1.0)
        zx = (w - 2 * margin) / span_x
        zy = (h - 2 * margin) / span_y
        self.zc.zoom = max(self.zc.MIN_ZOOM, min(self.zc.MAX_ZOOM, min(zx, zy)))
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
        self.zc.pan_x = w / (2 * self.zc.zoom) - cx
        self.zc.pan_y = h / (2 * self.zc.zoom) - cy
        self._redraw()

    def _redraw(self, preview_point=None):
        c = self.canvas
        c.delete('all')
        self._draw_grid()
        self._draw_axes()
        self._draw_outline()
        self._draw_in_progress(preview_point)

    def _draw_grid(self):
        if not self.snap_grid.get():
            return
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        g = self.grid_size
        if g * self.zc.zoom < 6:
            return
        x0w, y0w = self._s2w(0, 0)
        x1w, y1w = self._s2w(w, h)
        xmin, xmax = sorted((x0w, x1w))
        ymin, ymax = sorted((y0w, y1w))
        x = math.floor(xmin / g) * g
        while x <= xmax:
            sx, _ = self._w2s(x, ymin)
            c.create_line(sx, 0, sx, h, fill=GRID_COLOR)
            x += g
        y = math.floor(ymin / g) * g
        while y <= ymax:
            _, sy = self._w2s(xmin, y)
            c.create_line(0, sy, w, sy, fill=GRID_COLOR)
            y += g

    def _draw_axes(self):
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        ox, oy = self._w2s(0, 0)
        c.create_line(0, oy, w, oy, fill=AXIS_COLOR, dash=(4, 2))
        c.create_line(ox, 0, ox, h, fill=AXIS_COLOR, dash=(4, 2))

    def _draw_outline(self):
        c = self.canvas
        pts = self.outline.flatten()
        if len(pts) < 2:
            if self.outline.start_point:
                sx, sy = self._w2s(*self.outline.start_point)
                c.create_oval(sx - 4, sy - 4, sx + 4, sy + 4, fill=OUTLINE_COLOR, outline='')
            return
        flat = []
        for p in pts:
            flat.extend(self._w2s(*p))
        ok, _ = self.outline.validate()
        if ok:
            c.create_polygon(flat, outline=OUTLINE_COLOR, fill='#dbe9f7', width=2)
        else:
            flat.extend(self._w2s(*pts[0]))
            c.create_line(flat, fill=OUTLINE_COLOR, width=2)
        for p in pts:
            sx, sy = self._w2s(*p)
            c.create_oval(sx - 2.5, sy - 2.5, sx + 2.5, sy + 2.5, fill=OUTLINE_COLOR, outline='')

    def _draw_in_progress(self, preview_point):
        c = self.canvas
        if self.outline.start_point is None:
            return
        last = self.outline.last_point()
        if self._pending_arc_through is not None:
            tx, ty = self._w2s(*self._pending_arc_through)
            c.create_oval(tx - 3, ty - 3, tx + 3, ty + 3, outline=CONSTRUCTION_COLOR)
            if preview_point is not None:
                pts = secm.discretize_arc(last, self._pending_arc_through, preview_point, n=16)
                flat = []
                for p in pts:
                    flat.extend(self._w2s(*p))
                c.create_line(*flat, fill=CONSTRUCTION_COLOR, dash=(3, 2))
        elif preview_point is not None:
            lx, ly = self._w2s(*last)
            px, py = self._w2s(*preview_point)
            c.create_line(lx, ly, px, py, fill=CONSTRUCTION_COLOR, dash=(2, 2))
            if psm._dist(preview_point, self.outline.start_point) <= self._px_to_world(SNAP_TOL_PX) and self.outline.segments:
                sx, sy = self._w2s(*self.outline.start_point)
                c.create_oval(sx - 6, sy - 6, sx + 6, sy + 6, outline=CLOSE_HINT_COLOR, width=2)
