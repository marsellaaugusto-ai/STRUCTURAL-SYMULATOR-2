"""
Custom section-profile designer -- Tkinter UI.

Draws a cross-section as a SectionSketch: one closed boundary loop, any
number of holes cut through it, and the weld lines marked on it. Converts
to a perforated_beam_math.CustomProfileSection on Apply.

Companion to profile_sketcher_ui.py (which draws web OPENINGS along the
beam instead) -- built on the same ZoomCanvas foundation and reusing
profile_sketcher_math's snapping and typed-entry helpers.

TOOL SET
--------
Path tools continue the loop currently being drawn:
    Line (L)            straight segment
    3-point Arc (A)     arc through a point, then to an end point
    Center Arc (C)      centre first, then the end point -- the tool you
                        want for a fillet or a rounded flange tip, where
                        what you know is the radius and centre, not some
                        third point along the curve

Circle tools drop a complete closed loop in one go, needing no path:
    Circle c+r (R)      centre, then any point on it
    Circle 2pt (D)      two ends of a DIAMETER
    Circle 3pt (T)      through three points

    Weld (W)            two points marking a welded joint

    Select (S)          pick what to mirror, move or delete

WHERE A LOOP LANDS is controlled by the Outline/Hole selector, not by the
tool: the same circle tool draws a round bar's boundary or a bolt hole
through a plate depending on that setting. The first loop drawn always
becomes the outline regardless, since a hole with nothing to be cut from
is meaningless.

SELECTION AND MIRRORING (2026-09-07)
------------------------------------
Click with Select to pick the outline, a hole or a weld; shift-click adds
to the selection. Mirroring runs on the SKETCH through
`section_profile_math`, so a mirrored arc stays an arc and a mirrored
circle stays a circle -- the drawing is still editable afterwards.

"Horizontal" flips left-for-right, "vertical" top-for-bottom: the label
names what MOVES, which is the way CAD tools label the buttons. The
mirror line is either a drawing axis (x=0 or y=0), the selection's own
centre, or a typed coordinate -- the seam of a two-profile box being the
case that motivated the typed option.

"As a copy" duplicates holes and welds instead of moving them. It does
NOT duplicate the outline: a sketch has exactly one boundary, so a second
one would have nowhere to live. The outline is mirrored in place and the
status line says so, rather than the checkbox silently doing nothing.

WEB OPENINGS vs HOLES (2026-09-07)
----------------------------------
These are different things and the designer now says so, because the
overlap in everyday language is a real trap:

  * A HOLE is a void through the cross-section, present at EVERY station
    along the beam -- a bolt hole, a service void. It changes A and I.
  * A WEB OPENING is a hole through the web at intervals ALONG the beam
    -- the 1.35 m circles of a cellular beam. The section between
    openings is solid.

Holes are drawn here. Web openings are laid out in the tab's own panel,
and the panel mirrored into this window previews one on the section at
mid-depth so their size relative to the profile can be judged while
drawing, which is the thing that was impossible before.

EVERY TOOL ACCEPTS TYPED INPUT on the same footing as clicks (x,y | @dx,dy
| length<angle), through one shared `_consume_point`. Mouse and keyboard
used to be two parallel code paths that each knew every tool; folding
them together is what keeps a seven-tool palette from becoming fourteen
branches, and means a new tool cannot work by mouse but not by typing.
"""
import math
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from common import ZoomCanvas, FlowBar
from apps.perforated_beam import profile_sketcher_math as psm
from apps.perforated_beam import section_profile_math as secm
from apps.perforated_beam import welded_section_math as wsm

BG = '#f5f5f3'
ACCENT = '#1a6bbd'
GRID_COLOR = '#e3e3e0'
AXIS_COLOR = '#b5b5b0'
OUTLINE_COLOR = '#1a1a1a'
FILL_COLOR = '#dbe9f7'
HOLE_FILL = '#ffffff'
HOLE_COLOR = '#b03030'
WELD_COLOR = '#e08a00'
CONSTRUCTION_COLOR = '#7fb3e0'
CLOSE_HINT_COLOR = '#2e9e4f'
SNAP_TOL_PX = 10

# tool -> (label, accelerator, how many points it collects after any start)
TOOLS = [
    ('line',      'Line (L)',          'l', 1),
    ('arc',       '3-pt Arc (A)',      'a', 2),
    ('carc',      'Center Arc (C)',    'c', 2),
    ('circle_cr', 'Circle c+r (R)',    'r', 2),
    ('circle_2p', 'Circle 2pt (D)',    'd', 2),
    ('circle_3p', 'Circle 3pt (T)',    't', 3),
    ('weld',      'Weld (W)',          'w', 2),
    ('select',    'Select (S)',        's', 0),
]
TOOL_LABEL = {t: lbl for t, lbl, _, _ in TOOLS}
TOOL_KEY = {key: t for t, _, key, _ in TOOLS}
TOOL_NPTS = {t: n for t, _, _, n in TOOLS}
PATH_TOOLS = ('line', 'arc', 'carc')
CIRCLE_TOOLS = ('circle_cr', 'circle_2p', 'circle_3p')
SELECT_TOL_PX = 12

TOOL_HINTS = {
    'line': 'Click each corner. Click the start point again to close.',
    'arc': 'Click a point the arc passes THROUGH, then its end point.',
    'carc': 'Click the arc CENTRE, then the end point (pulled onto the radius).',
    'circle_cr': 'Click the centre, then any point on the circle.',
    'circle_2p': 'Click two opposite points -- they are a DIAMETER.',
    'circle_3p': 'Click three points the circle passes through.',
    'weld': 'Click the two ends of the welded joint.',
    'select': 'Click the outline, a hole or a weld. Shift-click to add. '
              'Then mirror, move or delete it below.',
}

SELECT_COLOR = '#0aa5c8'
OPENING_COLOR = '#c0392b'


class SectionProfileDesigner(tk.Toplevel):
    def __init__(self, master, on_apply=None, grid_size=10.0,
                 existing_outline=None, existing_sketch=None, opening_ctx=None):
        super().__init__(master)
        self.title('Design custom section profile')
        self.geometry('1280x820')
        self.configure(bg=BG)

        self.on_apply = on_apply
        self.grid_size = grid_size
        if existing_sketch is not None:
            self.sketch = existing_sketch
        elif existing_outline is not None:
            # accepts a bare SectionOutline from a caller that predates holes
            self.sketch = secm.SectionSketch(existing_outline)
        else:
            self.sketch = secm.SectionSketch()

        self.tool = tk.StringVar(value='line')
        self.target = tk.StringVar(value='outline')   # 'outline' | 'hole'
        self.snap_grid = tk.BooleanVar(value=True)
        self.snap_points = tk.BooleanVar(value=True)
        self.arc_ccw = tk.BooleanVar(value=True)
        self._pending = []          # points collected so far for a multi-click tool
        self._active_hole = None    # the hole path currently being drawn
        # Selection entries are ('outline', None) | ('hole', i) | ('weld', i).
        # Indices, not object identities, because the lists they point into
        # are rebuilt by undo and by Load.
        self.selection = []
        self.opening_ctx = opening_ctx

        self._build_ui()
        self.after(50, self._fit_view)
        self.bind('<Key>', self._on_key)

    # ── UI layout ────────────────────────────────────────────────────────
    def _build_ui(self):
        # Every bar below used to be one un-wrapping row of pack(side='left')
        # calls. Packed together with the seven drawing tools, the row ran
        # off the right edge of the window (measured: 1483px of controls in
        # a 1280px default window), putting Save/Load and the selection
        # tools out of reach entirely. FlowBar (common.py) is the project's
        # own fix for exactly this -- see its docstring and
        # REPORTS AND GUIDES/HANDOFF_MANIFESTO_2026-09-10.md sec. on
        # responsive layout -- so every bar here wraps its groups onto a new
        # row instead of running off the edge.
        toolbar = tk.Frame(self, bg=BG)
        toolbar.pack(side='top', fill='x', padx=4, pady=4)
        toolbar_flow = FlowBar(toolbar)

        g = toolbar_flow.group()
        self._tool_buttons = {}
        for t, label, _key, _n in TOOLS:
            b = tk.Button(g, text=label, relief='flat', bd=0, padx=6,
                          command=lambda t=t: self._set_tool(t))
            b.pack(side='left', padx=1)
            self._tool_buttons[t] = b

        toolbar_flow.separator()
        g = toolbar_flow.group()
        tk.Label(g, text='Draw into:', bg=BG).pack(side='left')
        for val, lbl in (('outline', 'Outline'), ('hole', 'Hole')):
            tk.Radiobutton(g, text=lbl, value=val, variable=self.target,
                           bg=BG, command=self._on_target_change).pack(side='left')

        toolbar_flow.separator()
        g = toolbar_flow.group()
        tk.Checkbutton(g, text='Arc CCW', variable=self.arc_ccw, bg=BG,
                       command=self._redraw).pack(side='left')
        tk.Checkbutton(g, text='Grid snap', variable=self.snap_grid, bg=BG).pack(side='left')
        tk.Checkbutton(g, text='Point snap', variable=self.snap_points, bg=BG).pack(side='left')

        toolbar_flow.separator()
        g = toolbar_flow.group()
        tk.Label(g, text='Grid:', bg=BG).pack(side='left')
        self.grid_var = tk.DoubleVar(value=self.grid_size)
        tk.Entry(g, textvariable=self.grid_var, width=5).pack(side='left', padx=2)
        tk.Button(g, text='Set', relief='flat', bd=0, command=self._set_grid_size).pack(side='left')
        toolbar_flow.start()

        # File/history actions.
        filebar = tk.Frame(self, bg=BG)
        filebar.pack(side='top', fill='x', padx=4)
        filebar_flow = FlowBar(filebar)
        g = filebar_flow.group()
        for label, cmd in (('Undo', self._undo), ('Clear all', self._clear_all),
                           ('Close loop', self._close_loop),
                           ('Save…', self._save), ('Load…', self._load)):
            tk.Button(g, text=label, relief='flat', bd=0, command=cmd).pack(side='left', padx=2)
        filebar_flow.start()

        # Second toolbar row: everything that acts on the SELECTION.
        selbar = tk.Frame(self, bg=BG)
        selbar.pack(side='top', fill='x', padx=4)
        selbar_flow = FlowBar(selbar)

        g = selbar_flow.group()
        tk.Label(g, text='Selection:', bg=BG,
                 font=('Helvetica', 9, 'bold')).pack(side='left')
        self.sel_label = tk.Label(g, text='nothing selected', bg=BG, fg='#666',
                                   font=('Helvetica', 8), width=22, anchor='w')
        self.sel_label.pack(side='left', padx=(2, 6))
        tk.Button(g, text='Select all', relief='flat', bd=0,
                  command=self._select_all).pack(side='left', padx=1)
        tk.Button(g, text='Clear sel.', relief='flat', bd=0,
                  command=self._clear_selection).pack(side='left', padx=1)

        selbar_flow.separator()
        g = selbar_flow.group()
        tk.Button(g, text='Mirror ⇔ left/right', relief='flat', bd=0, bg='#eef4fb',
                  command=lambda: self._mirror_selection(True)).pack(side='left', padx=1)
        tk.Button(g, text='Mirror ⇕ top/bottom', relief='flat', bd=0, bg='#eef4fb',
                  command=lambda: self._mirror_selection(False)).pack(side='left', padx=1)

        g = selbar_flow.group()
        tk.Label(g, text=' about:', bg=BG, font=('Helvetica', 8)).pack(side='left')
        self.mirror_about = tk.StringVar(value='axis')
        for val, lbl in (('axis', 'the axis (x=0 / y=0)'),
                         ('centre', "selection's centre"),
                         ('custom', 'this coordinate:')):
            tk.Radiobutton(g, text=lbl, value=val, variable=self.mirror_about,
                           bg=BG, font=('Helvetica', 8)).pack(side='left')
        self.mirror_at_var = tk.StringVar(value='0')
        tk.Entry(g, textvariable=self.mirror_at_var, width=7).pack(side='left', padx=2)

        g = selbar_flow.group()
        self.mirror_copy = tk.BooleanVar(value=False)
        tk.Checkbutton(g, text='as a copy', variable=self.mirror_copy, bg=BG,
                       font=('Helvetica', 8)).pack(side='left', padx=(6, 0))

        selbar_flow.separator()
        g = selbar_flow.group()
        tk.Button(g, text='Move…', relief='flat', bd=0,
                  command=self._move_selection).pack(side='left', padx=1)
        tk.Button(g, text='Delete sel.', relief='flat', bd=0,
                  command=self._delete_selection).pack(side='left', padx=1)
        selbar_flow.start()

        main = tk.Frame(self, bg=BG)
        main.pack(fill='both', expand=True, padx=4)

        canvas_frame = tk.Frame(main, bg=BG)
        canvas_frame.pack(side='left', fill='both', expand=True)
        self.zc = ZoomCanvas(canvas_frame, bg='white')
        self.zc.pack(fill='both', expand=True)
        self.zc.MIN_ZOOM = min(self.zc.MIN_ZOOM, 0.01)  # sections can be large
        self.canvas = self.zc.canvas
        self.zc._on_zoom_changed = self._redraw
        self.canvas.bind('<Motion>', self._on_motion)
        self.canvas.bind('<Button-1>', self._on_click)
        self.canvas.bind('<Shift-Button-1>', lambda e: self._on_click(e, add=True))
        self.canvas.bind('<Configure>', lambda e: self._redraw())
        # The side panel binds the wheel globally while the pointer is over
        # it; leaving it re-binds nothing, so the drawing canvas restores
        # its own zoom binding on entry rather than losing the wheel.
        self.canvas.bind('<Enter>', lambda e: self.canvas.unbind_all('<MouseWheel>'))

        # SCROLLABLE side panel. It gained the weld readout, the weld
        # scope note and the whole web-openings block, which together push
        # it past the height of the window -- and an unreachable control is
        # exactly the complaint that put a scrollbar on the tab's own left
        # column. Same canvas + scrollbar arrangement, for the same reason.
        side_outer = tk.Frame(main, bg=BG, width=300)
        side_outer.pack(side='left', fill='y', padx=(6, 0))
        side_outer.pack_propagate(False)
        side_canvas = tk.Canvas(side_outer, bg=BG, highlightthickness=0, width=300)
        side_sb = tk.Scrollbar(side_outer, orient='vertical', command=side_canvas.yview)
        side_canvas.configure(yscrollcommand=side_sb.set)
        side_sb.pack(side='right', fill='y')
        side_canvas.pack(side='left', fill='both', expand=True)

        side = tk.Frame(side_canvas, bg=BG)
        side_win = side_canvas.create_window((0, 0), window=side, anchor='nw')
        self._side_canvas = side_canvas
        self._side_inner = side

        side.bind('<Configure>',
                  lambda e: side_canvas.configure(scrollregion=side_canvas.bbox('all')))
        # Match the inner frame to the canvas's CURRENT width: the
        # scrollbar takes real pixels once it appears, and a fixed width
        # would push the panel's right edge underneath it.
        side_canvas.bind('<Configure>',
                         lambda e: side_canvas.itemconfigure(side_win, width=e.width))

        def _side_wheel(event):
            side_canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        side_canvas.bind('<Enter>',
                         lambda e: side_canvas.bind_all('<MouseWheel>', _side_wheel))
        side_canvas.bind('<Leave>', lambda e: side_canvas.unbind_all('<MouseWheel>'))

        tk.Label(side, text='Section properties', bg=BG, font=('Helvetica', 9, 'bold')).pack(anchor='w')
        self.props_label = tk.Label(side, text='(not closed yet)', bg=BG, justify='left',
                                     font=('Courier', 9), fg='#444')
        self.props_label.pack(anchor='w', pady=(2, 6))

        tk.Label(side, text='Precision entry:', bg=BG, font=('Helvetica', 8)).pack(anchor='w')
        tk.Label(side, text='x,y | @dx,dy | length<angle', bg=BG, fg='#888',
                 font=('Helvetica', 7)).pack(anchor='w')
        self.entry_var = tk.StringVar()
        entry = tk.Entry(side, textvariable=self.entry_var)
        entry.pack(fill='x', pady=2)
        entry.bind('<Return>', self._on_typed_entry)
        self.hint_label = tk.Label(side, text='', bg=BG, fg='#666', font=('Helvetica', 7),
                                    justify='left', wraplength=270)
        self.hint_label.pack(anchor='w', pady=(2, 6))

        ttk.Separator(side, orient='horizontal').pack(fill='x', pady=4)
        tk.Label(side, text='Holes', bg=BG, font=('Helvetica', 9, 'bold')).pack(anchor='w')
        self.hole_list = tk.Listbox(side, height=4, font=('Courier', 8))
        self.hole_list.pack(fill='x', pady=2)
        hrow = tk.Frame(side, bg=BG); hrow.pack(fill='x')
        tk.Button(hrow, text='Delete hole', relief='flat', bd=0,
                  command=self._delete_hole).pack(side='left')

        ttk.Separator(side, orient='horizontal').pack(fill='x', pady=4)
        tk.Label(side, text='Welds', bg=BG, font=('Helvetica', 9, 'bold')).pack(anchor='w')
        self.weld_list = tk.Listbox(side, height=4, font=('Courier', 8))
        self.weld_list.pack(fill='x', pady=2)
        self.weld_list.bind('<<ListboxSelect>>', self._on_weld_select)

        wrow = tk.Frame(side, bg=BG); wrow.pack(fill='x', pady=1)
        tk.Label(wrow, text='leg', bg=BG, width=4, anchor='w',
                 font=('Helvetica', 8)).pack(side='left')
        self.weld_leg_var = tk.StringVar(value='0')
        tk.Entry(wrow, textvariable=self.weld_leg_var, width=6).pack(side='left')
        tk.Label(wrow, text='mm  lines', bg=BG, font=('Helvetica', 8)).pack(side='left')
        self.weld_n_var = tk.StringVar(value='1')
        tk.Entry(wrow, textvariable=self.weld_n_var, width=3).pack(side='left')

        wrow2 = tk.Frame(side, bg=BG); wrow2.pack(fill='x', pady=1)
        tk.Label(wrow2, text='holds', bg=BG, width=5, anchor='w',
                 font=('Helvetica', 8)).pack(side='left')
        self.weld_side_var = tk.StringVar(value='auto')
        ttk.Combobox(wrow2, textvariable=self.weld_side_var, width=9, state='readonly',
                     values=['auto', 'positive', 'negative']).pack(side='left', padx=2)
        tk.Button(wrow2, text='Apply', relief='flat', bd=0,
                  command=self._apply_weld_edit).pack(side='left', padx=2)
        tk.Button(wrow2, text='Delete', relief='flat', bd=0,
                  command=self._delete_weld).pack(side='left')

        tk.Label(side, text='Leg 0 = "size it for me": the report gives the leg '
                            'the shear flow requires instead of checking one.',
                 bg=BG, fg='#888', font=('Helvetica', 7), justify='left',
                 wraplength=270).pack(anchor='w', pady=(2, 4))

        # What the selected weld actually holds. Without this the only way
        # to find out a weld line missed the steel -- and so reports no
        # shear flow at all, which reads exactly like a passing check --
        # was to Apply, analyse, and read the report.
        self.weld_effect = tk.Label(side, text='', bg=BG, fg='#444',
                                     font=('Courier', 8), justify='left', wraplength=270)
        self.weld_effect.pack(anchor='w', pady=(0, 4))

        tk.Label(side, text='A weld drawn HERE joins two parts of THIS profile.\n'
                            'It does not join profile A to profile B — that is\n'
                            'the "How the profiles are joined" choice plus the\n'
                            '"Extra weld lines" list, both on the tab itself,\n'
                            'because a line joining two profiles has to be given\n'
                            'in the assembled section\'s coordinates, not in one\n'
                            'profile\'s own.',
                 bg=BG, fg='#7a5a00', font=('Helvetica', 7), justify='left',
                 wraplength=270).pack(anchor='w', pady=(0, 4))

        self._build_opening_panel(side)

        ttk.Separator(side, orient='horizontal').pack(fill='x', pady=6)
        tk.Button(side, text='Apply as section', relief='flat', bd=0, bg=ACCENT, fg='white',
                  command=self._apply).pack(fill='x', pady=2)
        tk.Button(side, text='Cancel', relief='flat', bd=0, command=self.destroy).pack(fill='x', pady=2)

        self.status = tk.Label(self, text='', bg=BG, anchor='w', font=('Helvetica', 8))
        self.status.pack(side='bottom', fill='x', padx=4)

        self._set_tool('line')
        self._refresh_side_lists()
        self._update_props_label()

    # ── tool / target state ──────────────────────────────────────────────
    def _set_tool(self, t):
        self.tool.set(t)
        self._pending = []
        for name, btn in self._tool_buttons.items():
            btn.configure(relief='sunken' if name == t else 'flat',
                          bg=ACCENT if name == t else BG,
                          fg='white' if name == t else 'black')
        if hasattr(self, 'hint_label'):
            self.hint_label.configure(text=TOOL_HINTS.get(t, ''))
        if hasattr(self, 'canvas'):
            self._redraw()

    def _selection_summary(self):
        if not self.selection:
            return 'nothing selected'
        kinds = {}
        for kind, _i in self.selection:
            kinds[kind] = kinds.get(kind, 0) + 1
        return ', '.join(f'{n} {k}' + ('s' if n > 1 and k != 'outline' else '')
                         for k, n in sorted(kinds.items()))

    def _on_target_change(self):
        """Switching between outline and hole abandons any half-drawn
        multi-click action, since the points collected so far were meant
        for the other loop."""
        self._pending = []
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
            self._pending = []
            self._redraw()
        elif key == 'z' and (event.state & 0x4):
            self._undo()
        elif key == 'return':
            self._close_loop()
        elif key in TOOL_KEY:
            self._set_tool(TOOL_KEY[key])

    # ── which loop am I drawing into ─────────────────────────────────────
    def _drawing_a_hole(self):
        """True only when the Hole target is selected AND there is already
        an outline for the hole to be cut from. The first loop drawn is
        always the outline: a void with no surrounding material is not a
        section, and silently accepting one would only fail later with a
        more confusing message."""
        return self.target.get() == 'hole' and self._outline_exists()

    def _outline_exists(self):
        o = self.sketch.outline
        if isinstance(o, secm.CircleLoop):
            return True
        return o.start_point is not None and len(o.segments) >= 2

    def _active_path(self):
        """The SectionOutline that path tools extend, created on demand."""
        if self._drawing_a_hole():
            if self._active_hole is None:
                self._active_hole = secm.SectionOutline()
                self.sketch.holes.append(self._active_hole)
            return self._active_hole
        if isinstance(self.sketch.outline, secm.CircleLoop):
            raise ValueError(
                'The outline is currently a circle, which is already closed, so there '
                'is nothing to extend. Switch "Draw into" to Hole, or use Clear all to '
                'start the boundary again.')
        return self.sketch.outline

    # ── snapping ─────────────────────────────────────────────────────────
    def _snap_candidates(self):
        pts = []
        for loop in [self.sketch.outline] + list(self.sketch.holes):
            try:
                pts.extend(secm.loop_points(loop))
            except (ValueError, AttributeError):
                continue
            start = getattr(loop, 'start_point', None)
            if start:
                pts.append(start)
            centre = getattr(loop, 'center', None)
            if centre:
                pts.append(centre)
        for w in self.sketch.welds:
            pts.extend([w.p1, w.p2])
        pts.extend(self._pending)
        return pts

    def _snap(self, world_pt):
        tol = self._px_to_world(SNAP_TOL_PX)
        if self.snap_points.get():
            hit = psm.nearest_candidate(world_pt, self._snap_candidates(), tol)
            if hit is not None:
                return hit, True
        if self.snap_grid.get():
            return psm.snap_to_grid(world_pt, self.grid_size), False
        return world_pt, False

    # ── coordinates (y-up world, matching profile_sketcher_ui) ───────────
    def _w2s(self, wx, wy):
        return self.zc.w2s(wx, -wy)

    def _s2w(self, sx, sy):
        wx, wy = self.zc.s2w(sx, sy)
        return wx, -wy

    def _event_world(self, event):
        return self._s2w(event.x, event.y)

    def _px_to_world(self, px):
        return px / self.zc.zoom

    # ── editing ──────────────────────────────────────────────────────────
    def _undo(self):
        # Undo rebuilds the lists selection indices point into.
        self.selection = []
        if self._pending:
            self._pending.pop()
            self._redraw()
            return
        if self._active_hole is not None:
            self._active_hole.undo_last()
            if self._active_hole.start_point is None and not self._active_hole.segments:
                if self._active_hole in self.sketch.holes:
                    self.sketch.holes.remove(self._active_hole)
                self._active_hole = None
        elif isinstance(self.sketch.outline, secm.CircleLoop):
            self.sketch.outline = secm.SectionOutline()
        elif self.sketch.holes and self.target.get() == 'hole':
            self.sketch.holes.pop()
        else:
            self.sketch.outline.undo_last()
        self._after_change()

    def _clear_all(self):
        self.sketch.clear()
        self._active_hole = None
        self._pending = []
        self.selection = []
        self._after_change()

    def _after_change(self):
        self._refresh_side_lists()
        self._update_props_label()
        if hasattr(self, 'sel_label'):
            self.sel_label.configure(text=self._selection_summary())
        self._update_opening_status()
        self._update_weld_effect()
        self._redraw()

    # ── mouse / typed input, unified ─────────────────────────────────────
    def _on_motion(self, event):
        pt, snapped = self._snap(self._event_world(event))
        ref = self._pending[-1] if self._pending else None
        if ref is None and self.tool.get() in PATH_TOOLS:
            try:
                ref = self._active_path().last_point()
            except ValueError:
                ref = None
        if ref is not None:
            length = math.hypot(pt[0] - ref[0], pt[1] - ref[1])
            angle = math.degrees(math.atan2(pt[1] - ref[1], pt[0] - ref[0]))
            self.status.configure(
                text=f'x={pt[0]:.1f}  y={pt[1]:.1f} mm   |   length={length:.1f} mm  '
                     f'angle={angle:.1f}°' + ('   [snap]' if snapped else ''))
        else:
            self.status.configure(text=f'x={pt[0]:.1f}  y={pt[1]:.1f} mm'
                                        + ('   [snap]' if snapped else ''))
        self._redraw(preview_point=pt)

    def _on_click(self, event, add=False):
        if self.tool.get() == 'select':
            # Raw world point, not snapped: picking asks "what did I click
            # on", and snapping to a grid node would move the query away
            # from the thing under the cursor.
            self._pick_at(self._event_world(event), add=add)
            return
        pt, _ = self._snap(self._event_world(event))
        self._consume_point(pt)

    def _on_typed_entry(self, event):
        text = self.entry_var.get()
        self.entry_var.set('')
        if not text.strip():
            self._close_loop()
            return 'break'
        ref = self._pending[-1] if self._pending else None
        if ref is None and self.tool.get() in PATH_TOOLS:
            try:
                ref = self._active_path().last_point()
            except ValueError:
                ref = None
        try:
            pt = psm.parse_typed_entry(text, ref_point=ref)
        except ValueError as exc:
            messagebox.showerror('Precision entry', str(exc), parent=self)
            return 'break'
        self._consume_point(pt)
        return 'break'

    def _consume_point(self, pt):
        """One point, from anywhere, routed to the active tool.

        Single entry point for clicks and typed coordinates alike, so a
        tool cannot end up working by mouse but not by keyboard."""
        tool = self.tool.get()
        try:
            if tool in PATH_TOOLS:
                self._consume_path_point(tool, pt)
            else:
                self._pending.append(pt)
                if len(self._pending) >= TOOL_NPTS[tool]:
                    pts, self._pending = self._pending[:], []
                    if tool in CIRCLE_TOOLS:
                        self._commit_circle(tool, pts)
                    elif tool == 'weld':
                        self._commit_weld(pts)
        except ValueError as exc:
            self._pending = []
            messagebox.showwarning('Cannot draw that', str(exc), parent=self)
        self._after_change()

    def _consume_path_point(self, tool, pt):
        path = self._active_path()
        if path.start_point is None:
            path.start_point = pt
            return
        tol = self._px_to_world(SNAP_TOL_PX)
        closing = bool(path.segments) and psm._dist(pt, path.start_point) <= tol

        if tool == 'line':
            if closing:
                self._close_loop()
                return
            path.add_line(pt)
            return

        self._pending.append(pt)
        if len(self._pending) < TOOL_NPTS[tool]:
            return
        a, b = self._pending[0], self._pending[1]
        self._pending = []
        end = path.start_point if psm._dist(b, path.start_point) <= tol else b
        if tool == 'arc':
            path.add_arc(a, end)
        else:                                    # 'carc' -- a is the centre
            path.add_center_arc(a, end, ccw=self.arc_ccw.get())
        if end is path.start_point or psm._dist(path.last_point(), path.start_point) <= tol:
            self._close_loop()

    def _commit_circle(self, tool, pts):
        if tool == 'circle_cr':
            center, radius = secm.circle_from_center_point(pts[0], pts[1])
        elif tool == 'circle_2p':
            center, radius = secm.circle_from_2_points(pts[0], pts[1])
        else:
            found = secm.circle_from_3_points(*pts)
            if found is None:
                raise ValueError('Those three points lie on a straight line, so they '
                                  'do not define a circle. Move one of them off the line.')
            center, radius = found
        if radius <= 1e-9:
            raise ValueError('That circle has zero radius -- the points coincide.')
        if self._drawing_a_hole():
            self.sketch.add_circle_hole(center, radius, label=f'H{len(self.sketch.holes) + 1}')
        else:
            if self._outline_exists():
                raise ValueError(
                    'There is already an outline. A circle drawn now would replace it. '
                    'Switch "Draw into" to Hole to cut this circle through the profile, '
                    'or press Clear all first to start the boundary again.')
            self.sketch.set_circle_outline(center, radius)
        self._active_hole = None

    def _commit_weld(self, pts):
        try:
            leg = max(0.0, float(self.weld_leg_var.get() or 0.0))
            n_lines = max(1, int(self.weld_n_var.get() or 1))
        except ValueError:
            leg, n_lines = 0.0, 1
        self.sketch.add_weld(pts[0], pts[1], leg=leg, n_lines=n_lines,
                             side=self.weld_side_var.get(),
                             label=f'W{len(self.sketch.welds) + 1}')

    # ── closing a loop ───────────────────────────────────────────────────
    def _close_loop(self):
        try:
            path = self._active_path()
        except ValueError:
            return
        if path.start_point is None or not path.segments:
            return
        ok, msg = path.validate()
        if not ok:
            messagebox.showwarning('Not a valid closed shape', msg, parent=self)
            return
        if path is self._active_hole:
            self._active_hole = None
            self.status.configure(text='Hole closed. Draw another, or switch back to Outline.')
        else:
            self.status.configure(text='Outline closed. Review the properties, then Apply.')
        self._after_change()

    # ── side panel ───────────────────────────────────────────────────────
    def _refresh_side_lists(self):
        # Rebuilding a Listbox clears its selection, and the weld readout
        # is driven by that selection -- so without restoring it the
        # "what does this weld hold" panel blanked itself on every edit,
        # including the edits made to the weld being read. Remember and
        # put it back.
        keep_hole = self.hole_list.curselection()
        keep_weld = self.weld_list.curselection()
        self.hole_list.delete(0, tk.END)
        for i, h in enumerate(self.sketch.holes, 1):
            if isinstance(h, secm.CircleLoop):
                desc = f'circle r={h.radius:.1f} at ({h.center[0]:.0f},{h.center[1]:.0f})'
            else:
                desc = f'path, {len(h.segments) + 1} pts'
            self.hole_list.insert(tk.END, f'{i}. {desc}')
        self.weld_list.delete(0, tk.END)
        for w in self.sketch.welds:
            leg = f'{w.leg:.0f}mm' if w.leg > 0 else 'size me'
            self.weld_list.insert(
                tk.END, f'{w.label}: L={w.length:.0f} {leg} x{w.n_lines} [{w.side}]')
        if keep_hole and keep_hole[0] < self.hole_list.size():
            self.hole_list.selection_set(keep_hole[0])
        if keep_weld and keep_weld[0] < self.weld_list.size():
            self.weld_list.selection_set(keep_weld[0])

    def _on_weld_select(self, _event=None):
        sel = self.weld_list.curselection()
        if not sel:
            return
        w = self.sketch.welds[sel[0]]
        self.weld_leg_var.set(f'{w.leg:g}')
        self.weld_n_var.set(str(w.n_lines))
        self.weld_side_var.set(w.side)
        self._update_weld_effect()

    def _apply_weld_edit(self):
        sel = self.weld_list.curselection()
        if not sel:
            self.status.configure(text='Select a weld in the list first.')
            return
        w = self.sketch.welds[sel[0]]
        try:
            w.leg = max(0.0, float(self.weld_leg_var.get() or 0.0))
            w.n_lines = max(1, int(self.weld_n_var.get() or 1))
        except ValueError:
            messagebox.showerror('Weld', 'Leg and line count must be numbers.', parent=self)
            return
        w.side = self.weld_side_var.get()
        self._after_change()

    def _delete_weld(self):
        sel = self.weld_list.curselection()
        if sel:
            self.sketch.welds.pop(sel[0])
            self._after_change()

    def _delete_hole(self):
        sel = self.hole_list.curselection()
        if sel:
            removed = self.sketch.holes.pop(sel[0])
            if removed is self._active_hole:
                self._active_hole = None
            self._after_change()


    # ── selection ────────────────────────────────────────────────────────
    #
    # Entities are addressed by (kind, index) rather than by object, so a
    # selection survives the list rebuilding that Undo and Load do. Every
    # mutation that can shift those indices clears the selection instead of
    # trying to remap it -- a stale index that still resolves is far worse
    # than an empty selection, because it would silently mirror the wrong
    # hole.

    def _entities(self):
        """[(kind, index, loop_or_weld)] for everything pickable."""
        out = []
        if self._outline_exists():
            out.append(('outline', None, self.sketch.outline))
        for i, h in enumerate(self.sketch.holes):
            out.append(('hole', i, h))
        for i, w in enumerate(self.sketch.welds):
            out.append(('weld', i, w))
        return out

    @staticmethod
    def _dist_to_segment(pt, a, b):
        px, py = pt
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        den = dx * dx + dy * dy
        if den < 1e-12:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / den))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    def _entity_distance(self, pt, kind, obj):
        """Distance from `pt` to an entity's boundary, or 0 when the point
        is inside a closed loop -- clicking the middle of a hole should
        pick that hole, not whatever edge happens to be nearest."""
        if kind == 'weld':
            return self._dist_to_segment(pt, obj.p1, obj.p2)
        try:
            pts = secm.loop_points(obj)
        except (ValueError, AttributeError):
            return float('inf')
        if len(pts) < 2:
            return float('inf')
        if len(pts) >= 3 and psm.is_simple_polygon(pts) and psm.point_in_polygon(pt, pts):
            return 0.0
        return min(self._dist_to_segment(pt, pts[i], pts[(i + 1) % len(pts)])
                   for i in range(len(pts)))

    def _pick_at(self, pt, add=False):
        tol = self._px_to_world(SELECT_TOL_PX)
        best, best_d = None, float('inf')
        for kind, idx, obj in self._entities():
            d = self._entity_distance(pt, kind, obj)
            # Ties go to the LAST candidate, which is a weld before a hole
            # before the outline -- the small thing drawn on top of the big
            # one is the thing the user aimed at.
            if d <= best_d:
                best, best_d = (kind, idx), d
        if best is None or best_d > tol:
            if not add:
                self.selection = []
                self.status.configure(text='Selection cleared.')
            self._after_change()
            return
        if add:
            if best in self.selection:
                self.selection.remove(best)
            else:
                self.selection.append(best)
        else:
            self.selection = [best]
        self.status.configure(text=f'Selected: {self._selection_summary()}')
        self._after_change()

    def _select_all(self):
        self.selection = [(k, i) for k, i, _o in self._entities()]
        self.status.configure(text=f'Selected: {self._selection_summary()}')
        self._after_change()

    def _clear_selection(self):
        self.selection = []
        self._after_change()

    def _selected_objects(self):
        """[(kind, index, obj)] for the current selection, skipping any
        index that no longer resolves."""
        out = []
        for kind, idx in self.selection:
            if kind == 'outline' and self._outline_exists():
                out.append((kind, idx, self.sketch.outline))
            elif kind == 'hole' and 0 <= idx < len(self.sketch.holes):
                out.append((kind, idx, self.sketch.holes[idx]))
            elif kind == 'weld' and 0 <= idx < len(self.sketch.welds):
                out.append((kind, idx, self.sketch.welds[idx]))
        return out

    def _selection_bbox(self):
        boxes = []
        for kind, _i, obj in self._selected_objects():
            if kind == 'weld':
                boxes.append((min(obj.p1[0], obj.p2[0]), min(obj.p1[1], obj.p2[1]),
                              max(obj.p1[0], obj.p2[0]), max(obj.p1[1], obj.p2[1])))
            else:
                boxes.append(secm.loop_bbox(obj))
        return secm.bbox_union(boxes)

    # ── mirror / move / delete ───────────────────────────────────────────
    def _mirror_line(self, horizontal):
        """Where the mirror line sits, in world units. Returns None with a
        message already shown when the choice cannot be honoured."""
        mode = self.mirror_about.get()
        if mode == 'axis':
            return 0.0
        if mode == 'centre':
            box = self._selection_bbox()
            if box is None:
                messagebox.showwarning('Mirror', 'Nothing is selected, so there is no '
                                        'centre to mirror about.', parent=self)
                return None
            return (box[0] + box[2]) / 2.0 if horizontal else (box[1] + box[3]) / 2.0
        try:
            return float(self.mirror_at_var.get())
        except (TypeError, ValueError):
            messagebox.showerror('Mirror', 'The mirror coordinate must be a number.',
                                 parent=self)
            return None

    def _mirror_selection(self, horizontal):
        picked = self._selected_objects()
        if not picked:
            messagebox.showinfo('Mirror', 'Select something first — click the outline, '
                                 'a hole or a weld with the Select tool.', parent=self)
            return
        about = self._mirror_line(horizontal)
        if about is None:
            return
        as_copy = bool(self.mirror_copy.get())
        outline_in_place = False

        for kind, idx, obj in picked:
            if kind == 'outline':
                # A sketch has exactly ONE boundary, so a mirrored copy of
                # it would have nowhere to live. Transform in place and say
                # so, rather than letting the checkbox appear to do nothing.
                self.sketch.outline = secm.mirror_loop(obj, horizontal, about)
                outline_in_place = as_copy
            elif kind == 'hole':
                m = secm.mirror_loop(obj, horizontal, about)
                if as_copy:
                    self.sketch.holes.append(m)
                else:
                    self.sketch.holes[idx] = m
            else:
                m = secm.mirror_weld(obj, horizontal, about)
                if as_copy:
                    m.label = f'W{len(self.sketch.welds) + 1}'
                    self.sketch.welds.append(m)
                else:
                    self.sketch.welds[idx] = m

        axis = 'left/right' if horizontal else 'top/bottom'
        note = (f'Mirrored {axis} about {"x" if horizontal else "y"}={about:g}.')
        if outline_in_place:
            note += (' The outline was mirrored in place — a sketch has only one '
                     'boundary, so it cannot be copied.')
        # Indices have moved if anything was appended.
        self.selection = []
        self.status.configure(text=note)
        self._active_hole = None
        self._after_change()

    def _move_selection(self):
        picked = self._selected_objects()
        if not picked:
            messagebox.showinfo('Move', 'Select something first.', parent=self)
            return
        raw = self.entry_var.get().strip()
        if not raw:
            messagebox.showinfo(
                'Move', 'Type the shift into the "Precision entry" box first, as '
                        '"dx,dy" (for example 250,0), then press Move.', parent=self)
            return
        try:
            parts = raw.lstrip('@').split(',')
            dx, dy = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            messagebox.showerror('Move', f'Could not read "{raw}" as dx,dy.', parent=self)
            return
        for kind, idx, obj in picked:
            if kind == 'outline':
                self.sketch.outline = secm.translate_loop(obj, dx, dy)
            elif kind == 'hole':
                self.sketch.holes[idx] = secm.translate_loop(obj, dx, dy)
            else:
                self.sketch.welds[idx] = secm.translate_weld(obj, dx, dy)
        self.entry_var.set('')
        self.status.configure(text=f'Moved by ({dx:g}, {dy:g}) mm.')
        self._active_hole = None
        self._after_change()

    def _delete_selection(self):
        picked = self._selected_objects()
        if not picked:
            return
        # Delete from the highest index down so the earlier ones stay valid.
        for kind, idx, _obj in sorted(picked, key=lambda t: -(t[1] if t[1] is not None else -1)):
            if kind == 'hole':
                self.sketch.holes.pop(idx)
            elif kind == 'weld':
                self.sketch.welds.pop(idx)
            else:
                self.sketch.outline = secm.SectionOutline()
        self.selection = []
        self._active_hole = None
        self.status.configure(text='Deleted.')
        self._after_change()

    # ── web openings (along the beam) ────────────────────────────────────
    def _build_opening_panel(self, side):
        """Mirrors the tab's Web openings panel, plus the thing the tab
        cannot show: the opening drawn ON the section, at mid-depth, so
        its size relative to the profile is visible while drawing.

        Hidden entirely when no context is supplied, since openings
        belong to the beam and a designer opened without a beam behind it
        has nothing to apply them to. The tab passes one from every entry
        point it has, base-profile pickers included: 'will a 1.35 m circle
        fit through what I am drawing' is just as much the question when
        drawing profile A of a compound as when drawing a single one."""
        if self.opening_ctx is None:
            return
        ttk.Separator(side, orient='horizontal').pack(fill='x', pady=4)
        tk.Label(side, text='Web openings (along the beam)', bg=BG,
                 font=('Helvetica', 9, 'bold')).pack(anchor='w')
        tk.Label(side, text='NOT the same as a Hole. A hole is a void through the\n'
                            'section at EVERY station; a web opening is a hole through\n'
                            'the web at intervals along the span, with solid section\n'
                            'between. Cellular-beam circles are web openings.',
                 bg=BG, fg='#7a5a00', font=('Helvetica', 7), justify='left',
                 wraplength=270).pack(anchor='w', pady=(0, 3))

        self.op_vars = {}
        for key, label, default, unit in (('dia', 'diameter', '1350', 'mm'),
                                           ('spacing', 'spacing', '1800', 'mm'),
                                           ('xstart', 'x start', '2700', 'mm'),
                                           ('n', 'count', '26', 'openings')):
            row = tk.Frame(side, bg=BG); row.pack(fill='x')
            tk.Label(row, text=label, bg=BG, width=9, anchor='w',
                     font=('Helvetica', 8)).pack(side='left')
            v = tk.StringVar(value=default)
            tk.Entry(row, textvariable=v, width=9).pack(side='left')
            tk.Label(row, text=unit, bg=BG, fg='#888',
                     font=('Helvetica', 7)).pack(side='left')
            # Both, not just the redraw: the preview circle and the
            # depth-ratio text describe the same opening, and letting the
            # drawing update while the numbers beside it went stale would
            # be worse than neither moving.
            v.trace_add('write', lambda *_a: self._opening_changed())
            self.op_vars[key] = v

        self.op_preview = tk.BooleanVar(value=True)
        tk.Checkbutton(side, text='Preview one opening on the section',
                       variable=self.op_preview, bg=BG, font=('Helvetica', 8),
                       command=self._redraw).pack(anchor='w')
        self.op_status = tk.Label(side, text='', bg=BG, fg='#444', justify='left',
                                   font=('Courier', 8), wraplength=270)
        self.op_status.pack(anchor='w', pady=2)
        tk.Button(side, text='Apply these openings to the beam', relief='flat', bd=0,
                  bg='#2e9e4f', fg='white',
                  command=self._apply_openings).pack(fill='x', pady=2)

        existing = self.opening_ctx.get('count', 0)
        if existing:
            tk.Label(side, text=f'The beam currently has {existing} opening(s). '
                                f'Applying replaces them.',
                     bg=BG, fg='#888', font=('Helvetica', 7), justify='left',
                     wraplength=270).pack(anchor='w')

    def _opening_changed(self):
        self._update_opening_status()
        self._redraw()

    def _opening_params(self):
        try:
            return (float(self.op_vars['dia'].get()), float(self.op_vars['spacing'].get()),
                    float(self.op_vars['xstart'].get()), int(float(self.op_vars['n'].get())))
        except (TypeError, ValueError, KeyError):
            return None

    def _update_opening_status(self):
        if self.opening_ctx is None or not hasattr(self, 'op_status'):
            return
        p = self._opening_params()
        if p is None:
            self.op_status.configure(text='(enter numbers to preview)', fg='#888')
            return
        dia, spacing, xstart, n = p
        box = secm.sketch_bbox(self.sketch, include_welds=False)
        if box is None:
            self.op_status.configure(text='(draw the profile first)', fg='#888')
            return
        depth = box[3] - box[1]
        ratio = dia / depth if depth > 1e-9 else float('inf')
        post = spacing - dia
        msg = [f'section depth {depth:8.0f} mm',
               f'opening/depth {ratio * 100:7.1f} %',
               f'web post      {post:8.0f} mm',
               f'last opening at x = {(xstart + (n - 1) * spacing) / 1000.0:.3f} m']
        colour = '#2e9e4f'
        if ratio > 0.70:
            colour = '#b03030'
            msg.append('>70% of the depth: beyond where the')
            msg.append('Vierendeel model is normally used.')
        if post <= 0:
            colour = '#b03030'
            msg.append('Openings overlap — spacing <= diameter.')
        self.op_status.configure(text='\n'.join(msg), fg=colour)

    def _apply_openings(self):
        p = self._opening_params()
        if p is None:
            messagebox.showerror('Web openings',
                                 'Diameter, spacing, x start and count must all be '
                                 'numbers.', parent=self)
            return
        dia, spacing, xstart, n = p
        if dia <= 0 or spacing <= 0 or n < 1:
            messagebox.showerror('Web openings',
                                 'Diameter and spacing must be positive and the count '
                                 'at least 1.', parent=self)
            return
        if spacing <= dia:
            messagebox.showerror(
                'Web openings',
                f'Spacing ({spacing:g} mm) must exceed the diameter ({dia:g} mm), or '
                'the openings overlap and there is no web post between them.',
                parent=self)
            return
        self.opening_ctx['apply'](dia, spacing, xstart, n)
        self.status.configure(
            text=f'{n} openings of {dia:g} mm at {spacing:g} mm centres sent to the beam.')

    def _draw_opening_preview(self):
        """One web opening drawn on the section at mid-depth, which is
        where `OpeningInstance.vertices_abs` puts it."""
        if (self.opening_ctx is None or not hasattr(self, 'op_preview')
                or not self.op_preview.get()):
            return
        p = self._opening_params()
        if p is None:
            return
        dia = p[0]
        box = secm.sketch_bbox(self.sketch, include_welds=False)
        if box is None or dia <= 0:
            return
        cx = (box[0] + box[2]) / 2.0
        cy = (box[1] + box[3]) / 2.0          # mid-DEPTH, the model's assumption
        pts = [(cx + dia / 2.0 * math.cos(2 * math.pi * i / 96),
                cy + dia / 2.0 * math.sin(2 * math.pi * i / 96)) for i in range(96)]
        self.canvas.create_line(self._flat(pts + [pts[0]]), fill=OPENING_COLOR,
                                width=2, dash=(6, 3))
        tx, ty = self._w2s(cx, cy)
        self.canvas.create_text(tx, ty, text=f'web opening\nØ{dia:g}', fill=OPENING_COLOR,
                                font=('Helvetica', 8), justify='center')

    # ── what a weld actually holds ───────────────────────────────────────
    def _update_weld_effect(self):
        """The selected weld's held area, computed the same way the report
        will. A line that misses the steel reports no shear flow, which
        reads exactly like a passing check -- so it is said here, in the
        window where it can still be dragged."""
        if not hasattr(self, 'weld_effect'):
            return
        sel = self.weld_list.curselection()
        if not sel or sel[0] >= len(self.sketch.welds):
            self.weld_effect.configure(text='')
            return
        w = self.sketch.welds[sel[0]]
        try:
            sec = self.sketch.to_section('preview')
            prof = wsm.WeldedProfile(sec, [w.to_weld_line()])
            res = wsm.check_welds(prof, 1000.0)[0]
        except Exception as exc:
            self.weld_effect.configure(text=f'{w.label}: cannot evaluate ({exc})',
                                        fg='#b03030')
            return
        if res.A_held <= 1e-9:
            self.weld_effect.configure(
                text=f'{w.label}: this line does not cut the\nsection — it holds nothing.',
                fg='#b03030')
            return
        pct = 100.0 * res.A_held / sec.A if sec.A > 1e-9 else 0.0
        self.weld_effect.configure(
            text=(f'{w.label} holds {res.A_held:,.0f} mm² ({pct:.0f}% of\n'
                  f'the section), Q={res.Q:,.0f} mm³.\n'
                  f'Needs {res.leg_required:.1f} mm leg per 1 kN of shear.'),
            fg='#2e9e4f')

    def _update_props_label(self):
        try:
            sec = self.sketch.to_section('preview')
        except ValueError as exc:
            self.props_label.configure(text=f'(not ready: {exc})')
            return
        cx, cy = sec.centroid
        lines = [f'A     = {sec.A:10.1f} mm^2',
                 f'I     = {sec.I:10.1f} mm^4',
                 f'Iy    = {sec.Iy:10.1f} mm^4',
                 f'd     = {sec.d:10.1f} mm',
                 f'S_top = {sec.S_top:10.1f} mm^3',
                 f'S_bot = {sec.S_bot:10.1f} mm^3',
                 f'centroid = ({cx:.1f}, {cy:.1f})']
        if self.sketch.holes:
            lines.append(f'{len(self.sketch.holes)} hole(s) deducted')
        if self.sketch.welds:
            lines.append(f'{len(self.sketch.welds)} weld(s) marked')
        self.props_label.configure(text='\n'.join(lines))

    # ── save / load ──────────────────────────────────────────────────────
    def _save(self):
        path = filedialog.asksaveasfilename(defaultextension='.json',
                                             filetypes=[('Section profile JSON', '*.json')],
                                             parent=self)
        if not path:
            return
        try:
            with open(path, 'w') as f:
                f.write(secm.serialize_sketch(self.sketch))
        except OSError as exc:
            messagebox.showerror('Save', f'Could not save: {exc}', parent=self)

    def _load(self):
        path = filedialog.askopenfilename(filetypes=[('Section profile JSON', '*.json')],
                                           parent=self)
        if not path:
            return
        try:
            with open(path) as f:
                sketch, _meta = secm.deserialize_sketch(f.read())
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror('Load', f'Could not load: {exc}', parent=self)
            return
        self.sketch = sketch
        self._active_hole = None
        self._pending = []
        self.selection = []
        self._after_change()
        self._fit_view()

    # ── apply ────────────────────────────────────────────────────────────
    def _apply(self):
        try:
            sec = self.sketch.to_section('custom')
        except ValueError as exc:
            messagebox.showerror('Cannot apply', str(exc), parent=self)
            return
        if self.on_apply:
            self.on_apply(sec, self.sketch)
        self.destroy()

    # ── drawing ──────────────────────────────────────────────────────────
    def _all_points(self):
        pts = []
        for loop in [self.sketch.outline] + list(self.sketch.holes):
            try:
                pts.extend(secm.loop_points(loop))
            except (ValueError, AttributeError):
                continue
        return pts

    def _fit_view(self):
        w = max(self.canvas.winfo_width(), 100)
        h = max(self.canvas.winfo_height(), 100)
        margin = 60
        pts = self._all_points()
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
        self._draw_holes()
        self._draw_welds()
        self._draw_opening_preview()
        self._draw_selection()
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

    def _flat(self, pts):
        out = []
        for p in pts:
            out.extend(self._w2s(*p))
        return out

    def _draw_outline(self):
        c = self.canvas
        loop = self.sketch.outline
        pts = secm.loop_points(loop)
        if len(pts) < 2:
            start = getattr(loop, 'start_point', None)
            if start:
                sx, sy = self._w2s(*start)
                c.create_oval(sx - 4, sy - 4, sx + 4, sy + 4, fill=OUTLINE_COLOR, outline='')
            return
        flat = self._flat(pts)
        ok = loop.validate()[0] if hasattr(loop, 'validate') else True
        if ok and (isinstance(loop, secm.CircleLoop) or psm.is_simple_polygon(pts)):
            c.create_polygon(flat, outline=OUTLINE_COLOR, fill=FILL_COLOR, width=2)
        else:
            flat = flat + list(self._w2s(*pts[0]))
            c.create_line(flat, fill=OUTLINE_COLOR, width=2)
        for p in pts:
            sx, sy = self._w2s(*p)
            c.create_oval(sx - 2, sy - 2, sx + 2, sy + 2, fill=OUTLINE_COLOR, outline='')

    def _draw_holes(self):
        c = self.canvas
        for h in self.sketch.holes:
            pts = secm.loop_points(h)
            if len(pts) < 3:
                if len(pts) == 2:
                    c.create_line(self._flat(pts), fill=HOLE_COLOR, width=2, dash=(3, 2))
                continue
            c.create_polygon(self._flat(pts), outline=HOLE_COLOR, fill=HOLE_FILL, width=2)

    def _draw_welds(self):
        c = self.canvas
        for w in self.sketch.welds:
            x1, y1 = self._w2s(*w.p1)
            x2, y2 = self._w2s(*w.p2)
            c.create_line(x1, y1, x2, y2, fill=WELD_COLOR, width=4)
            # small ticks along the line, the conventional weld symbol
            n = max(2, int(math.hypot(x2 - x1, y2 - y1) / 12))
            dx, dy = (x2 - x1) / n, (y2 - y1) / n
            nx, ny = -dy, dx
            norm = math.hypot(nx, ny) or 1.0
            nx, ny = 5 * nx / norm, 5 * ny / norm
            for i in range(n):
                px, py = x1 + dx * (i + 0.5), y1 + dy * (i + 0.5)
                c.create_line(px, py, px + nx, py + ny, fill=WELD_COLOR, width=1)
            c.create_text((x1 + x2) / 2, (y1 + y2) / 2 - 10, text=w.label,
                          fill=WELD_COLOR, font=('Helvetica', 7))

    def _draw_selection(self):
        c = self.canvas
        for kind, _i, obj in self._selected_objects():
            if kind == 'weld':
                x1, y1 = self._w2s(*obj.p1)
                x2, y2 = self._w2s(*obj.p2)
                c.create_line(x1, y1, x2, y2, fill=SELECT_COLOR, width=7)
                c.create_line(x1, y1, x2, y2, fill=WELD_COLOR, width=3)
                continue
            try:
                pts = secm.loop_points(obj)
            except (ValueError, AttributeError):
                continue
            if len(pts) < 2:
                continue
            c.create_line(self._flat(pts + [pts[0]]), fill=SELECT_COLOR, width=3)
            for p in pts:
                sx, sy = self._w2s(*p)
                c.create_rectangle(sx - 3, sy - 3, sx + 3, sy + 3,
                                   outline=SELECT_COLOR, fill='white', width=1)

    def _draw_in_progress(self, preview_point):
        c = self.canvas
        tool = self.tool.get()
        for p in self._pending:
            px, py = self._w2s(*p)
            c.create_oval(px - 3, py - 3, px + 3, py + 3, outline=CONSTRUCTION_COLOR, width=2)
        if preview_point is None:
            return

        if tool in CIRCLE_TOOLS and self._pending:
            self._preview_circle(tool, preview_point)
            return
        if tool == 'weld' and self._pending:
            x1, y1 = self._w2s(*self._pending[0])
            x2, y2 = self._w2s(*preview_point)
            c.create_line(x1, y1, x2, y2, fill=WELD_COLOR, width=2, dash=(4, 2))
            return
        if tool not in PATH_TOOLS:
            return

        try:
            path = self._active_path()
        except ValueError:
            return
        if path.start_point is None:
            return
        last = path.last_point()
        if tool == 'arc' and self._pending:
            pts = secm.discretize_arc(last, self._pending[0], preview_point, n=16)
            c.create_line(self._flat(pts), fill=CONSTRUCTION_COLOR, dash=(3, 2))
        elif tool == 'carc' and self._pending:
            centre = self._pending[0]
            r = psm._dist(centre, last)
            if r > 1e-9:
                try:
                    end = secm.project_to_circle(centre, r, preview_point)
                except ValueError:
                    return
                pts = secm.discretize_center_arc(centre, last, end, self.arc_ccw.get())
                c.create_line(self._flat(pts), fill=CONSTRUCTION_COLOR, dash=(3, 2))
                cxs, cys = self._w2s(*centre)
                c.create_line(cxs - 5, cys, cxs + 5, cys, fill=CONSTRUCTION_COLOR)
                c.create_line(cxs, cys - 5, cxs, cys + 5, fill=CONSTRUCTION_COLOR)
        else:
            lx, ly = self._w2s(*last)
            px, py = self._w2s(*preview_point)
            c.create_line(lx, ly, px, py, fill=CONSTRUCTION_COLOR, dash=(2, 2))
            if (path.segments
                    and psm._dist(preview_point, path.start_point) <= self._px_to_world(SNAP_TOL_PX)):
                sx, sy = self._w2s(*path.start_point)
                c.create_oval(sx - 6, sy - 6, sx + 6, sy + 6, outline=CLOSE_HINT_COLOR, width=2)

    def _preview_circle(self, tool, preview_point):
        c = self.canvas
        pts = self._pending + [preview_point]
        try:
            if tool == 'circle_cr' and len(pts) >= 2:
                centre, r = secm.circle_from_center_point(pts[0], pts[1])
            elif tool == 'circle_2p' and len(pts) >= 2:
                centre, r = secm.circle_from_2_points(pts[0], pts[1])
            elif tool == 'circle_3p' and len(pts) >= 3:
                found = secm.circle_from_3_points(*pts[:3])
                if found is None:
                    return
                centre, r = found
            else:
                return
        except (ValueError, ZeroDivisionError):
            return
        if r <= 1e-9:
            return
        loop = secm.CircleLoop(centre, r)
        c.create_line(self._flat(loop.flatten() + [loop.flatten()[0]]),
                      fill=CONSTRUCTION_COLOR, dash=(3, 2))
