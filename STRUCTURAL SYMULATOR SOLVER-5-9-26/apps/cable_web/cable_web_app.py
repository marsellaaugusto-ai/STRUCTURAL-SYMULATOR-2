"""
Cable Web editor.

This module intentionally keeps the existing cable_web_math solver as the
analysis engine.  The editor is a graph/CAD layer on top of it: user-visible
cables may contain junctions and load break-points along their length; when a
solution is requested those continuous user cables are discretised into
straight solver segments.
"""
import math
import re
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from common import (
    SNAP, PX_PER_M, PANEL_W, INIT_CW, INIT_CH, INIT_DH, INIT_FD,
    DEFAULT_SELF_WEIGHT,
    CT, CC, CV, CZ, CN, CS, CL, CSP, CG, CG_MINOR, CG_MICRO, CR,
    ZoomCanvas,
    _nice_ticks,
    _ensure_openpyxl,
    _ensure_scipy,
)
from .cable_web_math import (
    CableWebModel, solve_force_density, solve_analysis, MissingSolverDependency,
)

BG = '#f5f5f3'
PANEL_BG = '#eeeeec'
GRID_BG = '#ffffff'
TEXT = '#222222'
MUTED = '#666666'
CABLE = '#555b63'
JUNCTION = '#333333'
SUPPORT = CSP
LOAD = CL
SELECT = CS
FUN = '#377dff'
ANTI = '#7f4bb3'
WARNING = '#a66a00'
ERROR = '#b33a3a'


def dist_seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 1e-18:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def project_seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 1e-18:
        return 0.0, ax, ay, math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    qx, qy = ax + t * dx, ay + t * dy
    return t, qx, qy, math.hypot(px - qx, py - qy)


def unit(vx, vy):
    L = math.hypot(vx, vy)
    return (vx / L, vy / L) if L > 1e-12 else (1.0, 0.0)


class InfoTooltip:
    """Small delayed help bubble used by toolbar controls."""
    DELAY_MS = 3000

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self._after_id = None
        self._tip = None
        widget.bind('<Enter>', self._enter, add='+')
        widget.bind('<Leave>', self._leave, add='+')
        widget.bind('<ButtonPress>', self._leave, add='+')

    def _enter(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(self.DELAY_MS, self._show)

    def _leave(self, _event=None):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        if self._tip is not None or not self.widget.winfo_exists():
            return
        try:
            x = self.widget.winfo_rootx()
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            tip = tk.Toplevel(self.widget)
            tip.wm_overrideredirect(True)
            tip.attributes('-topmost', True)
            tip.geometry(f'+{x}+{y}')
            frame = tk.Frame(tip, bg='#fffbe6', bd=1, relief='solid')
            frame.pack()
            tk.Label(frame, text='ⓘ', bg='#fffbe6', fg='#6b6500',
                     font=('Helvetica', 11, 'bold')).pack(side='left', padx=(7, 3), pady=6)
            tk.Label(frame, text=self.text, bg='#fffbe6', fg='#222222',
                     justify='left', wraplength=330, font=('Helvetica', 9)).pack(
                         side='left', padx=(0, 8), pady=6)
            self._tip = tip
        except Exception:
            self._tip = None

    def _hide(self):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


class CableWebApp(tk.Frame):
    """Interactive cable-web editor using the existing CableWeb solver."""

    def __init__(self, master):
        super().__init__(master, bg=BG)
        self.nodes = []
        self.cables = []
        self.loads = []
        self.next_node_id = 1
        self.next_cable_id = 1
        self.next_load_id = 1

        self.tool = tk.StringVar(value='select')
        self.selected_kind = None
        self.selected_id = None
        self.selected_items = set()  # multi-selection: {(kind, id), ...}
        self.connect_start = None
        self.drag_state = None
        self.result = None
        self.result_kind = None
        self.results_current = False
        self.show_original = tk.BooleanVar(value=True)
        # Straight, not Catenary, is the default. The Catenary preview is a
        # real per-component physics solve costing tens of seconds; measured
        # 2026-09-04, building a 3-cable web cost 90.33 s of blocked UI with
        # it on versus 0.04 s with it off, for an identical analysis
        # (residual 7.22e-09 either way). It is now solved on a background
        # thread (see _update_reference_result), so it no longer freezes
        # anything -- but it is still a several-second wait per edit, so the
        # user opts INTO it rather than paying for it unasked.
        self.reference_mode = tk.StringVar(value='straight')
        self.show_funicular = tk.BooleanVar(value=True)
        self.show_antifunicular = tk.BooleanVar(value=False)
        self.show_loads = tk.BooleanVar(value=True)
        self.show_results = tk.BooleanVar(value=True)
        # Tension/thrust diagram pane. Off by default: it costs canvas
        # height, and it has nothing to show until an Analyze has converged.
        self.show_diagrams = tk.BooleanVar(value=False)
        # How a loaded stretch is turned into a drawn curve. Two routes,
        # deliberately exclusive (see _on_curve_route_changed):
        #   'analytic' -- Route 1. Draw the exact catenary through the
        #       stretch's own endpoints. Determined by geometry alone, so it
        #       costs no second solve; this is the cheaper route and the
        #       default.
        #   'graded'   -- Route 2. Re-mesh by curvature and solve again, so
        #       the SOLVED polygon itself carries its turning evenly. Costs a
        #       second solve; the honest choice when you want the drawn line
        #       to be the solved line and nothing else.
        self.curve_route = tk.StringVar(value='analytic')
        # Equilibrium force vectors: the reaction at every support, and the
        # resolved forces at the one SELECTED joint. Off by default -- on a
        # web with several junctions, everything at once is unreadable.
        self.show_force_vectors = tk.BooleanVar(value=False)
        # Web-wide T / H / V drawn INTO the geometry, following the funicular
        # rather than a straight baseline -- in its OWN pane beside the
        # editor, not painted over it. Off by default, and one quantity at a
        # time: three bands on each of six cables is eighteen overlapping
        # ribbons plus the structure.
        self.show_web_diagrams = tk.BooleanVar(value=False)
        self.web_diagram_q = tk.StringVar(value='T')
        # That pane draws the funicular by default and its mirror on demand,
        # so the same diagram can be read as a hanging cable or as the arch it
        # is dual to.
        self.fd_flip = tk.BooleanVar(value=False)
        # Percent, matching the Arch tab's own scale sliders.
        self.fd_scale = tk.IntVar(value=100)
        # Kept as the authoritative flag for the two-pass solve. Driven by
        # curve_route, never set directly by the UI.
        self.grade_mesh = tk.BooleanVar(value=False)
        self.snap_grid = tk.BooleanVar(value=True)
        self.snap_cable = tk.BooleanVar(value=True)
        # Cable snapping has two explicit behaviors:
        #   Geometric: snap a new cable endpoint to a cable's geometry only.
        #   Attach: snap and create a real structural attachment to that cable.
        self.snap_cable_mode = tk.StringVar(value='Geometric')
        self.grid_visible = tk.BooleanVar(value=True)
        self.q_var = tk.DoubleVar(value=50.0)
        self.status_var = tk.StringVar(value='Select a tool and build the cable web.')
        self.coord_var = tk.StringVar(value='x = 0.00 m    y = 0.00 m')
        self.validation_var = tk.StringVar(value='Model not yet analysed.')
        self._solver_meta = None
        self._reference_result = None
        self._reference_meta = None
        self._reference_paths = {}
        self._reference_segments = {}
        self._reference_junction_positions = {}
        self._history = []
        self._future = []
        self._drag_checkpointed = False
        self._selection_box_start = None
        self._solving = False
        self._solve_queue = queue.Queue()
        # Background at-rest (Catenary) preview -- see _update_reference_result.
        # _reference_token is bumped by every request; a worker result whose
        # token no longer matches is discarded rather than drawn onto a model
        # that has changed underneath it.
        self._reference_token = 0
        self._reference_request = None     # (token, jobs) awaiting a solve
        self._reference_busy = False
        self._reference_queue = queue.Queue()
        self._reference_status = ''
        # Bumped once per accepted solve result; keys the zero-tension
        # display-shape cache in _draw_solver_result (see the comment there
        # for why id(result) was not safe for that).
        self._result_serial = 0
        # Bumped by _invalidate on every model mutation; snapshotted when a
        # background Analyze starts so its result can be rejected if the
        # model moved on. See _invalidate.
        self._model_serial = 0
        self._solve_model_serial = None
        # Curvature-graded meshing (see _graded_breakpoints). Analyze runs
        # twice: once on the uniform mesh, then again with each cable's FREE
        # breakpoints re-placed so every element carries roughly equal
        # direction change. _graded_bp holds that second mesh, per cable id;
        # empty means "use the uniform mesh", which is what every other
        # caller of _solver_breakpoints wants.
        self._graded_bp = {}
        self._solve_pass = 0
        self._pass1_result = None
        # y the antifunicular view is reflected about; set by _draw.
        self._anti_axis_y = None
        self._selection_box_item = None
        self._syncing_tree = False

        self._build_ui()
        self._bind_keys()
        self._update_reference_result()
        self._draw()

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------
    def _world_to_m(self, wx, wy):
        return wx / PX_PER_M, -wy / PX_PER_M

    def _m_to_world(self, x, y):
        return x * PX_PER_M, -y * PX_PER_M

    @staticmethod
    def _nice_grid_step(base_px, z, target_px=55):
        seq = (1, 2, 5)
        i = 0
        while True:
            mult = seq[i % 3] * (10 ** (i // 3))
            step = base_px * mult
            if step * z >= target_px or i > 60:
                return step
            i += 1

    @staticmethod
    def _grid_subdiv(mult):
        exp = math.floor(math.log10(mult) + 1e-9)
        lead = mult / (10 ** exp)
        return 2 if abs(lead - 2) < 0.05 else 5

    def _finest_grid_step_world(self):
        z = self.zc.zoom
        step = self._nice_grid_step(SNAP, z, target_px=55)
        # refine to the finest visible 1-2-5 subdivision, exactly like the
        # Truss tab, so the snap points coincide with visible grid points.
        mult = step / SNAP
        for _ in range(2):
            sub = self._grid_subdiv(mult)
            nxt = step / sub
            if nxt * z < 10:
                break
            step = nxt
            mult = mult / sub
        return step

    def _snap_world(self, wx, wy):
        if not self.snap_grid.get():
            return wx, wy
        step = self._finest_grid_step_world()
        return round(wx / step) * step, round(wy / step) * step

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        self._build_toolbar()
        body = tk.Frame(self, bg=BG)
        body.pack(fill='both', expand=True)
        self.bind('<Configure>', lambda e: self._update_responsive_sidebars(), add='+')

        # Pack fixed-width sidebars first and the expanding canvas last. This
        # preserves the sidebar widths on desktop windows; packing the expanding
        # canvas before the right sidebar caused the right panel to collapse.
        self.right = tk.Frame(body, width=285, bg=PANEL_BG)
        self.right.pack_propagate(False)
        self.right.pack(side='right', fill='y')
        self._build_inspector(self.right)

        self.left = tk.Frame(body, width=190, bg=PANEL_BG)
        self.left.pack_propagate(False)
        self.left.pack(side='left', fill='y')
        self._build_object_tree(self.left)

        center = tk.Frame(body, bg='white')
        center.pack(side='left', fill='both', expand=True)
        self.zc = ZoomCanvas(center, width=INIT_CW, height=INIT_CH, bg='white')

        # ── tension / thrust diagram pane ────────────────────────────────
        # Packed side='bottom' BEFORE the canvas is packed: pack gives
        # leftover space to the expand=True widget, so a bottom strip added
        # after an already-expanded canvas gets squeezed to nothing.
        self._build_diagram_pane(center)
        self._build_funicular_pane(center)
        self.zc.pack(fill='both', expand=True)
        # Wire mouse-wheel zoom and middle-drag pan to actually redraw.
        # ZoomCanvas updates zoom/pan_x/pan_y internally on wheel/B2-drag
        # and calls self._on_zoom_changed() (a no-op by default -- every
        # other tab overrides it, e.g. truss_app.py's
        # `self.zc._on_zoom_changed = self._draw`). This tab never did,
        # so the view's internal state changed but nothing repainted until
        # some unrelated redraw happened to fire (e.g. clicking a tool
        # button) -- the reported "wheel zoom/pan doesn't work" bug.
        self.zc._on_zoom_changed = self._draw
        c = self.zc.canvas
        c.bind('<ButtonPress-1>', self._canvas_press)
        c.bind('<B1-Motion>', self._canvas_drag)
        c.bind('<ButtonRelease-1>', self._canvas_release)
        c.bind('<Motion>', self._motion)
        # The canvas is constructed at INIT_CW x INIT_CH and only reaches its
        # real on-screen size once the window manager finishes its first
        # geometry pass -- which happens *after* this __init__ (and its own
        # call to self._draw() further down) has already run. Nothing
        # redrew afterward, so the very first _draw() painted the grid (and
        # everything else) for a 1x1-ish canvas that was never seen again:
        # the app's first real appearance was a blank canvas until some
        # unrelated action (loading an example, a tool click, wheel-zoom)
        # happened to call _draw() again. The same gap meant a later window
        # resize left the old, wrong-sized content on screen too -- nothing
        # was wired to the canvas's own <Configure> at all. Bind directly to
        # it so every real size change -- the first one and any later
        # resize -- gets a fresh, correctly-sized redraw.
        c.bind('<Configure>', self._on_canvas_configure)

        bottom = tk.Frame(self, bg='#e7e7e5')
        bottom.pack(fill='x')
        tk.Label(bottom, textvariable=self.status_var, anchor='w', bg='#e7e7e5',
                 fg=TEXT).pack(side='left', fill='x', expand=True, padx=7, pady=3)
        tk.Label(bottom, textvariable=self.coord_var, anchor='e', bg='#e7e7e5',
                 fg=MUTED).pack(side='right', padx=7)

    # ------------------------------------------------------------------
    # Tension / thrust diagrams
    # ------------------------------------------------------------------
    def _build_diagram_pane(self, parent):
        """Tension and thrust diagrams for one cable, in the Truss/Beam tab's
        own diagram-panel idiom rather than a new one -- MANIFESTO.md sec 5
        recommended exactly that, along with plotting result.tensions[eid]
        against arc length s and deriving thrust as the projected component
        of the same data, needing no new solver output.
        """
        self.diag_outer = tk.Frame(parent, bg=PANEL_BG, bd=1, relief='solid')
        hdr = tk.Frame(self.diag_outer, bg=PANEL_BG)
        hdr.pack(fill='x', padx=6, pady=(3, 1))
        tk.Label(hdr, text='TENSION & THRUST', bg=PANEL_BG, fg=MUTED,
                 font=('Helvetica', 8, 'bold')).pack(side='left')
        tk.Label(hdr, text='cable', bg=PANEL_BG, fg=MUTED,
                 font=('Helvetica', 8)).pack(side='left', padx=(12, 3))
        self.diag_cable = tk.StringVar(value='')
        self.diag_combo = ttk.Combobox(hdr, textvariable=self.diag_cable, width=8,
                                        state='readonly', values=())
        self.diag_combo.pack(side='left')
        self.diag_combo.bind('<<ComboboxSelected>>', lambda _e: self._draw_diagrams())
        tk.Label(hdr, text='T = cable tension · H = horizontal thrust · V = vertical shear',
                 bg=PANEL_BG, fg='#9a9a9a',
                 font=('Helvetica', 8)).pack(side='left', padx=(12, 0))
        tk.Button(hdr, text='Hide', command=lambda: self.show_diagrams.set(False),
                  relief='flat', bg=PANEL_BG, fg=MUTED,
                  font=('Helvetica', 8)).pack(side='right')
        self.diag_canvas = tk.Canvas(self.diag_outer, bg='#fafaf8', height=INIT_DH,
                                      highlightthickness=0)
        self.diag_canvas.pack(fill='both', expand=True, padx=4, pady=(0, 4))
        self.diag_canvas.bind('<Configure>', lambda _e: self._draw_diagrams())
        self._sync_diagram_pane()

    def _sync_diagram_pane(self):
        """Show/hide the pane and keep the cable list current."""
        if not hasattr(self, 'diag_outer'):
            return
        if self.show_diagrams.get():
            if not self.diag_outer.winfo_ismapped():
                self.diag_outer.pack(side='bottom', fill='x')
        else:
            self.diag_outer.pack_forget()
            return
        names = [f"C{c['id']}" for c in self.cables]
        if list(self.diag_combo['values']) != names:
            self.diag_combo['values'] = names
        if self.diag_cable.get() not in names:
            self.diag_cable.set(names[0] if names else '')
        self._draw_diagrams()

    def _diagram_series(self, cid):
        """(s0, s1, T, H, V) per solver edge of cable `cid`, ordered along s.

        T is the solved axial tension, constant within one solver edge.
        H and V are its horizontal and vertical components, taken from the
        edge's own SOLVED direction -- so H is the thrust the cable delivers
        to its anchorage, and for a cable under purely vertical load it comes
        out constant along the span, which is the classic check this diagram
        exists to make visible.
        """
        if not (self.results_current and self.result is not None and self._solver_meta):
            return []
        out = []
        for eid, owner in self._solver_meta['seg_owner'].items():
            if owner[0] != cid:
                continue
            T = self.result.tensions.get(eid)
            if T is None:
                continue
            try:
                e = self.result.model.edges[eid]
                xi, yi = self.result.positions[e.i]
                xj, yj = self.result.positions[e.j]
            except Exception:
                continue
            seg = math.hypot(xj - xi, yj - yi)
            if seg < 1e-12:
                continue
            out.append((owner[1], owner[2], float(T),
                        abs(T * (xj - xi) / seg), abs(T * (yj - yi) / seg)))
        out.sort(key=lambda r: (r[0], r[1]))
        return out

    def _cable_end_tension(self, cid, at_start):
        """The exact cable tension AT a cable end, rather than in the edge
        beside it.

        The diagram reports one tension per solver edge, and an edge's value is
        the true tension at its MIDPOINT: consistent lumping puts half of each
        element's load at each of its nodes, so the force an edge carries is
        the one acting halfway along it. At a support that under-reports the
        peak, because the real cable keeps steepening across the last half
        element -- measured -4.71% against a 64-edge reference, and worse the
        longer that element is, which is why the graded mesh made it worse
        still (-6.20%, sec 3x).

        Under a uniform load per unit arc length the vertical component varies
        linearly with s, so the end value is the edge's value plus exactly the
        half element it is missing:

            V_end = V_edge +/- q * ds / 2        T_end = hypot(H, V_end)

        and that is exact, not an extrapolation of a trend. Better, it is
        MESH-INDEPENDENT: a longer end element lowers V_edge by precisely what
        the correction adds back. Verified on the 20/22 m UDL cable -- both the
        uniform and the graded mesh give V_end = 110.0 N and T_end = 170.64 N
        against a 169.94 N 64-edge reference (+0.39%), where the raw edge
        values read 161.95 and 159.40 N (-4.71% and -6.20%).

        The sign is taken from the edge's own solved direction rather than
        assumed: a stretch whose low point lies outside it is steepest at the
        far end, and adding the half element at both ends would then be wrong
        at one of them.

        Returns None where the closed form does not apply -- the same gate
        Route 1 uses, evaluated on the pinned interval containing this edge.
        """
        if not (self.results_current and self.result is not None
                and self._solver_meta):
            return None
        owned = sorted(((o[1], o[2], eid) for eid, o in
                        self._solver_meta['seg_owner'].items() if o[0] == cid))
        if not owned:
            return None
        s0, s1, eid = owned[0] if at_start else owned[-1]
        ds = abs(s1 - s0)
        T = self.result.tensions.get(eid)
        if T is None or ds <= 1e-12:
            return None
        try:
            e = self.result.model.edges[eid]
            xi, yi = self.result.positions[e.i]
            xj, yj = self.result.positions[e.j]
        except Exception:
            return None
        seg = math.hypot(xj - xi, yj - yi)
        if seg < 1e-12:
            return None
        H = abs(T * (xj - xi) / seg)
        # Edges are built in increasing s (see _build_solver_model), so this
        # is the vertical force transmitted in the +s direction, signed.
        V = T * (yj - yi) / seg

        # The stretch this edge sits in must carry ONE uniform load, or the
        # half-element step is not exact. Use the pinned interval containing
        # the edge: the smallest scope the correction actually needs.
        pin = self._pinned_breakpoints(cid)
        lo = max([q for q in pin if q <= s0 + 1e-7], default=None)
        hi = min([q for q in pin if q >= s1 - 1e-7], default=None)
        if lo is None or hi is None or hi - lo <= 1e-12:
            return None
        q = self._group_uniform_load(cid, lo, hi)
        if q is None:
            return None
        V_end = (V - q * ds / 2.0) if at_start else (V + q * ds / 2.0)
        return math.hypot(H, V_end)

    def _draw_diagrams(self):
        if not hasattr(self, 'diag_canvas'):
            return
        c = self.diag_canvas
        c.delete('all')
        w = c.winfo_width() or 700
        h = c.winfo_height() or INIT_DH
        if w < 40 or h < 40:
            return
        name = self.diag_cable.get()
        cid = None
        if name.startswith('C'):
            try:
                cid = int(name[1:])
            except ValueError:
                cid = None
        series = self._diagram_series(cid) if cid is not None else []
        if not series:
            msg = ('Run Analyze to see tension and thrust diagrams.'
                   if cid is not None else 'No cables yet.')
            c.create_text(w / 2, h / 2, text=msg, fill=MUTED, font=('Helvetica', 9))
            return

        L = max(self._cable_length(cid), 1e-12)
        margin_l, margin_r, margin_t, margin_b = 52, 14, 16, 20
        plot_w = max(w - margin_l - margin_r, 10)
        band_h = max((h - margin_t - margin_b) / 3.0, 20)
        scale_x = plot_w / L

        # Exact tension at the two cable ends. The stepped band below shows
        # what each EDGE carries; the real cable is steeper than its last edge
        # at a support, and that gap is the peak-tension under-report. See
        # _cable_end_tension.
        t_ends = (self._cable_end_tension(cid, True),
                  self._cable_end_tension(cid, False))

        bands = (('TENSION  T (N)', 2, CT),
                  ('THRUST  H (N)  — horizontal component', 3, CC),
                  ('SHEAR  V (N)  — vertical component', 4, CV))
        for bi, (label, idx, color) in enumerate(bands):
            top = margin_t + bi * band_h
            bot = top + band_h
            base = bot - 12                     # zero line: these are magnitudes
            avail = max(band_h - 26, 8)
            peaks = [r[idx] for r in series]
            if idx == 2:
                peaks += [t for t in t_ends if t is not None]
            vmax = max(1e-9, max(peaks))

            for vt in _nice_ticks(0.0, vmax, 4):
                if vt < -1e-12 or vt > vmax * 1.001:
                    continue
                yy = base - (vt / vmax) * avail
                c.create_line(margin_l, yy, w - margin_r, yy, fill='#ececec')
                c.create_text(margin_l - 4, yy, text=f'{vt:.4g}', anchor='e',
                              font=('Helvetica', 6), fill='#a0a0a0')
            for xt in _nice_ticks(0.0, L, 6):
                if xt < -1e-12 or xt > L * 1.001:
                    continue
                xx = margin_l + xt * scale_x
                c.create_line(xx, top + 2, xx, base, fill='#ececec')
                if bi == len(bands) - 1:
                    c.create_text(xx, base + 9, text=f'{xt:g}', anchor='n',
                                  font=('Helvetica', 7), fill='#8f8f8f')
            c.create_line(margin_l, top + 2, margin_l, base, fill='#c8c8c8')
            c.create_line(margin_l, base, w - margin_r, base, fill='#b0b0b0')

            # Stepped: tension is constant within a solver edge, so a
            # piecewise-constant plot is the honest shape -- not a smooth
            # curve through midpoints, which would imply resolution the
            # solve does not have.
            poly = [(margin_l, base)]
            outline = []
            for (s0, s1, *vals) in series:
                v = vals[idx - 2]
                x0 = margin_l + max(0.0, min(L, s0)) * scale_x
                x1 = margin_l + max(0.0, min(L, s1)) * scale_x
                yy = base - (v / vmax) * avail
                poly.extend([(x0, yy), (x1, yy)])
                outline.extend([(x0, yy), (x1, yy)])
            poly.append((margin_l + L * scale_x, base))
            c.create_polygon([q for p in poly for q in p], fill=color,
                             outline='', stipple='gray25')
            for i in range(len(outline) - 1):
                c.create_line(*outline[i], *outline[i + 1], fill=color, width=2)

            # The exact end values, drawn as what they are: the continuation
            # of the tension past the last edge's midpoint to the anchorage.
            # Kept visually distinct from the stepped band so the plot never
            # implies the SOLVE has resolution it does not have.
            if idx == 2:
                for is_start, tv in zip((True, False), t_ends):
                    if tv is None:
                        continue
                    xx = margin_l + (0.0 if is_start else L * scale_x)
                    yy = base - (tv / vmax) * avail
                    edge_v = series[0][2] if is_start else series[-1][2]
                    y_edge = base - (edge_v / vmax) * avail
                    c.create_line(xx, y_edge, xx, yy, fill=color, width=1,
                                  dash=(3, 2))
                    c.create_oval(xx - 2.5, yy - 2.5, xx + 2.5, yy + 2.5,
                                  fill=color, outline='')

            c.create_text(margin_l + 4, top + 8, text=label, anchor='w',
                          font=('Helvetica', 8, 'bold'), fill='#5a5a5a')
            vmin = min(r[idx] for r in series)
            # Notes ride on the read-out line rather than floating in the
            # middle of the band: a centred item collides with the band title
            # as soon as the title is long, which both of these were.
            note = ''
            if idx == 2 and any(t is not None for t in t_ends):
                note = '   ● ends exact'
            elif idx == 3 and vmax > 1e-9 and (vmax - min(r[idx] for r in series)) / vmax < 0.01:
                # Worth calling out: under purely vertical load the horizontal
                # thrust is exactly constant along a cable, so this is a live
                # check that the solve behaved. The 1% band is discretisation
                # slack -- on the built-in Example C1 spreads 32.04-32.18 N
                # (0.44%) where the true answer is dead constant.
                note = '   — constant, vertical loading only'
            c.create_text(w - margin_r, top + 8,
                          text=f'max {vmax:.4g} N   min {vmin:.4g} N{note}',
                          anchor='e', font=('Helvetica', 8), fill='#7a7a7a')

        c.create_text(w - margin_r, h - 6, text='s (m) along cable', anchor='e',
                      font=('Helvetica', 7), fill='#9a9a9a')

    def _show_guide(self):
        dlg = tk.Toplevel(self)
        dlg.title('Cable Web — How to use')
        dlg.transient(self.winfo_toplevel())
        dlg.geometry('760x680')
        dlg.minsize(680, 560)

        outer = tk.Frame(dlg, bg='white')
        outer.pack(fill='both', expand=True, padx=10, pady=10)
        nb = ttk.Notebook(outer)
        nb.pack(fill='both', expand=True)

        quick = tk.Frame(nb, bg='white')
        ref = tk.Frame(nb, bg='white')
        nb.add(quick, text='Start here')
        nb.add(ref, text='Button reference')

        quick_text = (
            'CABLE WEB — BASIC WORKFLOW\n\n'
            '1. Create supports\n'
            '   Select Support, then click the required support locations.\n\n'
            '2. Create cables\n'
            '   Select Cable and click the two endpoints. Grid snapping is enabled by default.\n'
            '   Use Snap to cables = Geometric when you only want the endpoint to coincide visually.\n'
            '   Use Snap to cables = Attach when the new cable must physically connect to the existing cable.\n\n'
            '3. Set each cable length\n'
            '   Select a cable. In Properties, enable “Use prescribed length” and enter the natural cable length.\n'
            '   A length greater than the chord allows the solved cable to sag.\n\n'
            '4. Create interior junctions\n'
            '   Use Junction, click the cable, then enter the exact cable-local s coordinate.\n'
            '   s is measured along the prescribed cable length, not along the straight chord.\n\n'
            '5. Add loads\n'
            '   Select Load and choose Point, UDL, or Variable. Enter start/end s values and the load direction.\n\n'
            '6. Solve\n'
            '   Validate checks the model. Form-find gives a force-density form. Analyze runs the exact equilibrium solver.\n\n'
            '7. Inspect configurations\n'
            '   Original = user geometry. Funicular = loaded solved geometry.\n'
            '   Antifunicular = inverted funicular. Unloaded reference = self-weight-only reference with user loads removed.\n\n'
            '8. Save/load models\n'
            '   Export Excel saves nodes, cables, junctions and loads to a structured .xlsx workbook. Import Excel reconstructs the web from that workbook.\n\n'
            '9. Navigation and selection\n'            '   Select: click elements. Drag an empty canvas area to box-select. Drag a selected node to move it.\n'            '   Pan: activate Pan and left-drag the canvas; middle-mouse drag also pans.\n'            '   Zoom + / Zoom -: use the toolbar buttons. Mouse wheel over the canvas also zooms around the cursor.\n'            '   Fit: fit the current user web into the canvas.\n'            '   Shift-click adds/removes elements from the selection. Delete or press the Delete key to remove them.\n\n'
            '10. Edit and select\n'
            '   Shift-click adds/removes elements from the selection. Delete or press the Delete key to remove them.\n\n'
            'TIP: Example is the basic A/B/C test. Picture test is the four-support regression case that reproduces the difficult web geometry previously reported.'
        )
        box = tk.Text(quick, wrap='word', bg='white', fg=TEXT, relief='flat', font=('Helvetica', 10), padx=10, pady=10)
        box.pack(fill='both', expand=True)
        box.insert('1.0', quick_text); box.configure(state='disabled')

        refs = [
            ('Select', 'Select one or several elements. Drag an empty canvas area to box-select. Shift-click adds to the current selection.'),
            ('Cable', 'Draw a cable between two nodes/locations. The endpoint snapping settings control how it interacts with the grid and existing cables.'),
            ('Support', 'Create or convert a node into a support. Supports constrain the structural model.'),
            ('Junction', 'Create a true structural connection at an exact s position on an existing cable.'),
            ('Connect', 'Create a cable between two existing nodes.'),
            ('Load', 'Place a point load, UDL, or variable q(s) load on a cable. Positions are specified by s along that cable.'),
            ('Measure', 'Measure a distance in model metres between two points.'),
            ('Pan', 'Activate Pan, then left-drag the canvas to move the view. Middle-mouse drag remains available.'),
            ('Zoom + / Zoom -', 'Zoom the canvas around its center. Mouse-wheel zoom remains available over the canvas.'),
            ('Fit', 'Fit the current user-defined web into the available canvas.'),
            ('Undo / Redo', 'Move backward or forward through model edits.'),
            ('Delete', 'Delete selected elements. The Delete keyboard key is equivalent.'),
            ('Clear', 'Remove the entire model after confirmation.'),
            ('Reset view', 'Return the canvas to its default view.'),
            ('Example', 'Load the A/B/C diagnostic web: A has a point load, B has a UDL, and C connects them at specified s positions.'),
            ('Picture test', 'Load a second diagnostic modeled after the reported failure: two support-to-support cables with interior junctions connected by a third cable carrying both a point load and a UDL. Analyze it to verify the nonlinear solver and web geometry.'),
            ('Form-find', 'Solve a force-density form-finding problem. Useful for quickly finding a geometric equilibrium form.'),
            ('Analyze', 'Run the exact nonlinear cable equilibrium analysis.'),
            ('Validate', 'Check the model before solving.'),
            ('Guide', 'Open this usage guide.'),
            ('Import Excel', 'Import a Cable Web model from an .xlsx workbook.'),
            ('Export Excel', 'Export the current Cable Web model to an .xlsx workbook.'),
            ('At-rest shape', 'Show each cable at rest (self-weight only, no user loads): a natural catenary sag where the cable has slack at its current material length, or a straight line in WARNING color/dash where the true length is at or below the span between its ends -- that cable cannot physically sag at its current length.'),
            ('Funicular', 'Toggle the loaded funicular result. The displayed curve is a smoothed visualization of the solver nodes; the underlying analysis remains unchanged.'),
            ('Antifunicular', 'Toggle the inverted funicular visualization.'),
            ('Snap to grid', 'Snap new geometry to the currently visible grid resolution.'),
            ('Snap to cables = Off', 'Do not snap new cable endpoints to existing cables.'),
            ('Snap to cables = Geometric', 'Snap an endpoint to an existing cable’s geometric location without creating a structural attachment.'),
            ('Snap to cables = Attach', 'Snap an endpoint to an existing cable and create a structural junction at that location.'),
        ]
        rbox = tk.Text(ref, wrap='word', bg='white', fg=TEXT, relief='flat', font=('Helvetica', 10), padx=10, pady=10)
        rbox.pack(fill='both', expand=True)
        for name, desc in refs:
            rbox.insert('end', f'{name}\n', ('head',))
            rbox.insert('end', f'  {desc}\n\n')
        rbox.tag_configure('head', font=('Helvetica', 10, 'bold'), foreground=TEXT)
        rbox.configure(state='disabled')

        bottom = tk.Frame(dlg, bg='white')
        bottom.pack(fill='x', padx=10, pady=(0, 10))
        tk.Label(bottom, text='Hover over a toolbar button for 3 seconds to see its quick explanation.',
                 bg='white', fg=MUTED).pack(side='left')
        tk.Button(bottom, text='Close', command=dlg.destroy, relief='flat').pack(side='right')

    def _button(self, parent, text, command, width=9):
        b = tk.Button(parent, text=text, command=command, relief='flat', bd=0,
                      bg='#f7f7f6', activebackground='#ddddda', padx=7, pady=4,
                      font=('Helvetica', 10), width=width)
        b.pack(side='left', padx=2, pady=3)
        desc = {
            'Select': 'Select one or several elements. Drag an empty canvas area to box-select; hold Shift to add to the selection.',
            'Cable': 'Create a cable by clicking its start and end nodes. Grid/cable snapping controls where the endpoints land.',
            'Support': 'Create a support at an empty point or convert a free node into a support.',
            'Junction': 'Create a real structural attachment to an existing cable. After clicking the cable, specify the exact s position.',
            'Connect': 'Connect two existing nodes with a new cable.',
            'Load': 'Add a point load, UDL, or variable distributed load to a selected cable. Loads use cable-local s coordinates.',
            'Measure': 'Measure the distance between two points in model metres.',
            'Pan': 'Pan the canvas with left-drag. Does not edit the structural model.',
            'Zoom +': 'Zoom in around the canvas center.',
            'Zoom -': 'Zoom out around the canvas center.',
            'Fit': 'Fit the current web to the visible canvas.',
            'Pan': 'Pan: click and hold the canvas, then drag to move the view. This changes only the camera, not the structure.',
            'Zoom +': 'Zoom in around the center of the canvas.',
            'Zoom -': 'Zoom out around the center of the canvas.',
            'Fit': 'Fit the current user-defined web into the available canvas area.',
            'Undo': 'Undo the most recent model edit.',
            'Redo': 'Restore the most recently undone model edit.',
            'Delete': 'Delete all currently selected elements. The keyboard Delete key performs the same action.',
            'Clear': 'Delete the complete cable-web model after confirmation.',
            'Reset view': 'Restore the default canvas zoom and view.',
            'Example': 'Load the built-in A/B/C diagnostic example used to test point loads, UDLs, cable length and junctions.',
            'Picture test': 'Load the four-support web diagnostic based on the failure geometry. It tests two loaded support-to-support cables joined by a loaded transverse cable.',
            'Form-find': 'Run force-density form finding. This is a geometric form-finding operation, not the exact equilibrium analysis.',
            'Analyze': 'Run the exact cable-web equilibrium analysis using the existing structural solver.',
            'Validate': 'Check the model for missing supports, invalid cable lengths and invalid load positions before solving.',
            'Guide': 'Open the complete Cable Web usage guide, including step-by-step workflows and the meaning of every control.',
            'Import Excel': 'Load a previously exported Cable Web .xlsx file and reconstruct its nodes, cables, junctions and loads.',
            'Export Excel': 'Save the current Cable Web model to an .xlsx workbook so it can be reopened or edited as structured data.',
        }.get(text)
        if desc:
            InfoTooltip(b, desc)
        return b

    def _build_toolbar(self):
        # Responsive desktop toolbar. Groups are laid out left-to-right and
        # wrapped to new rows without overlapping. At narrow desktop widths
        # controls remain visible; only their row changes.
        bar = tk.Frame(self, bg='#ebebea')
        bar.pack(fill='x', padx=5, pady=(5, 0))
        self._toolbar_bar = bar
        self.tool_buttons = {}
        self._toolbar_groups = []

        def group():
            g = tk.Frame(bar, bg='#ebebea')
            self._toolbar_groups.append(g)
            return g

        def add_group_button(g, label, command, width):
            return self._button(g, label, command, width)

        tools = group()
        for label, value in [('Select', 'select'), ('Cable', 'cable'),
                             ('Support', 'support'), ('Junction', 'junction'),
                             ('Connect', 'connect'), ('Load', 'load'),
                             ('Measure', 'measure')]:
            self.tool_buttons[value] = add_group_button(tools, label, lambda v=value: self._set_tool(v), 9)

        view = group()
        self.tool_buttons['pan'] = add_group_button(view, 'Pan', lambda: self._set_tool('pan'), 7)
        add_group_button(view, 'Zoom +', self._zoom_in, 7)
        add_group_button(view, 'Zoom -', self._zoom_out, 7)
        add_group_button(view, 'Fit', self._fit_view, 6)

        edit = group()
        for label, cmd, width in [('Undo', self._undo, 7), ('Redo', self._redo, 7),
                                  ('Delete', self._delete_selected, 8), ('Clear', self._clear_all, 7),
                                  ('Reset view', self._reset_view, 10), ('Example', self._load_example, 8),
                                  ('Picture test', self._load_picture_example, 10),
                                  ('Import Excel', self._import_excel, 11), ('Export Excel', self._export_excel, 11)]:
            add_group_button(edit, label, cmd, width)

        analysis = group()
        tk.Label(analysis, text='q:', bg='#ebebea').pack(side='left', padx=(3, 0))
        tk.Entry(analysis, textvariable=self.q_var, width=7).pack(side='left', padx=2)
        self.analysis_buttons = {}
        for label, cmd, width in [('Form-find', self._solve_fd, 10), ('Analyze', self._solve_exact, 9),
                                  ('Validate', self._validate_model, 9), ('Guide', self._show_guide, 7)]:
            self.analysis_buttons[label] = add_group_button(analysis, label, cmd, width)
        self._solve_progress = ttk.Progressbar(analysis, mode='indeterminate', length=90)
        InfoTooltip(self._solve_progress, 'A solve is running in the background -- the UI stays '
                                           'responsive to viewing, but editing is paused until it finishes.')

        views = group()
        for text, var in [('At-rest shape', self.show_original), ('Funicular', self.show_funicular),
                          ('Antifunicular', self.show_antifunicular)]:
            cb = tk.Checkbutton(views, text=text, variable=var, bg='#ebebea', command=self._draw)
            cb.pack(side='left', padx=2, pady=3)
            InfoTooltip(cb, {
                'At-rest shape': 'Show each cable at rest (self-weight only, before Analyze): a natural catenary where it has slack, or a straight line flagged in warning color/dash where its true length is at or below the span -- it cannot sag.',
                'Funicular': 'Show the solved loaded funicular. If exact analysis did not converge, no invalid result is displayed.',
                'Antifunicular': 'Show the inverted funicular/arch geometry, with the same loads drawn on the mirrored web.',
            }[text])
        tk.Label(views, text='Curve:', bg='#ebebea',
                 font=('Helvetica', 8)).pack(side='left', padx=(10, 1), pady=3)
        for _text, _val, _tip in (
            ('Analytic', 'analytic',
             'Route 1, and the cheaper one. Each loaded stretch is drawn as the '
             'exact catenary through its own two endpoints -- a curve fixed by '
             'the endpoint positions and the cable length between them, both of '
             'which the model already knows exactly. It uses no solved tension '
             'or thrust, so it inherits none of their discretisation error, and '
             'it needs no second solve. Display only: the analysis, the '
             'tensions and every reported number are untouched. A stretch whose '
             'load is not uniform along it (a variable load, a UDL covering only '
             'part of it, a non-vertical load) has no such closed form and '
             'falls back to Route 2 drawing for that stretch alone.'),
            ('Graded mesh', 'graded',
             'Route 2. After the first solve, re-place the interior solver nodes '
             'of each cable so every element carries roughly the same change of '
             'direction, then solve again -- same number of unknowns, the nodes '
             'just move to where the cable actually curves. The drawn line stays '
             'exactly the solved line, which is what you want when you need the '
             'picture to be the analysis and nothing added to it. Costs a second '
             'solve.')):
            rb = tk.Radiobutton(views, text=_text, value=_val,
                                variable=self.curve_route, bg='#ebebea',
                                command=self._on_curve_route_changed)
            rb.pack(side='left', padx=1, pady=3)
            InfoTooltip(rb, _tip)
        cb = tk.Checkbutton(views, text='Funicular diagram',
                            variable=self.show_web_diagrams, bg='#ebebea',
                            command=self._sync_funicular_pane)
        cb.pack(side='left', padx=(8, 2), pady=3)
        InfoTooltip(cb, 'Open a second panel showing the solved web on its own, '
                        'with tension, thrust or shear drawn INTO that geometry '
                        '-- offset perpendicular to each cable\'s own solved '
                        'curve rather than to a straight baseline. The same idea '
                        'as the Vierendeel shear and moment diagrams, but on a '
                        'funicular. It has its own quantity selector, a flip to '
                        'read the shape as an antifunicular arch, and a scale '
                        'slider; the editing canvas is left alone.')
        cb = tk.Checkbutton(views, text='Forces', variable=self.show_force_vectors,
                            bg='#ebebea', command=self._draw)
        cb.pack(side='left', padx=2, pady=3)
        InfoTooltip(cb, 'Equilibrium force vectors, after Analyze: the reaction '
                        'at every support, and -- for the joint you have '
                        'selected -- the pull of each cable meeting there plus '
                        'any load applied at it. Green is the horizontal '
                        'component, purple the vertical, blue the resultant. '
                        'Only the selected joint is drawn, because a five-cable '
                        'junction with every arrow shown is an unreadable star. '
                        'Arrow shafts are in model units so they magnify as you '
                        'zoom in; the heads stay a fixed size on screen.')
        cb = tk.Checkbutton(views, text='Diagrams', variable=self.show_diagrams,
                             bg='#ebebea', command=self._sync_diagram_pane)
        cb.pack(side='left', padx=2, pady=3)
        InfoTooltip(cb, 'Show tension T(s) and horizontal thrust H(s) along one '
                        'cable, plotted against arc length -- the same diagram '
                        'idiom as the Truss and Beam tabs. Needs a converged '
                        'Analyze.')
        # Straight (as-drawn) vs Catenary preview (true length): which
        # rendering the "At-rest shape" checkbox above actually shows.
        # Catenary preview is the physically correct one (a junction lands
        # at its true self-weight equilibrium position instead of being
        # clamped to the straight chord between supports -- MANIFESTO.md
        # sec 6) and is the default; Straight is a free, instant fallback
        # with no solve at all -- the clearer view while actively
        # dragging/placing nodes, or if Catenary preview ever lags on a
        # large web. This choice only changes what _draw() renders
        # pre-Analyze: it never touches stored node positions, s-coordinate
        # bookkeeping, drag/snap behaviour, or solve_analysis() itself.
        for text, val in [('Straight', 'straight'), ('Catenary', 'catenary')]:
            rb = tk.Radiobutton(views, text=text, variable=self.reference_mode, value=val,
                                 bg='#ebebea', command=self._on_reference_mode_changed, indicatoron=True)
            rb.pack(side='left', padx=(0, 2), pady=3)
            InfoTooltip(rb, {
                'straight': 'At-rest shape as a straight chord between each cable\'s fixed points -- cheap, no solve, the clearest view while actively editing.',
                'catenary': 'At-rest shape as each cable\'s true self-weight equilibrium -- junctions hang at their real position instead of the straight chord. Default; falls back to Straight automatically while dragging a node.',
            }[val])

        self._toolbar_relayout_pending = False
        self._toolbar_relayout_running = False
        self._toolbar_last_width = -1
        bar.bind('<Configure>', self._schedule_toolbar_relayout, add='+')
        self.after_idle(self._relayout_toolbar)

    @staticmethod
    def _pack_responsive_group(group, available):
        """Lay out one group's own children left-to-right, wrapping to an
        internal second/third row only if the group's own content alone
        doesn't fit `available`. Uses one Frame per internal row + pack
        (not grid(row=,column=)) -- see _relayout_toolbar's note on why
        Tk's shared-column-width-across-rows behavior makes grid the
        wrong tool for a flow layout; the same fix applies here.
        """
        # Row-anchor frames from a previous call are destroyed first; the
        # real buttons are unaffected (they're children of `group` itself,
        # only geometrically placed "in" the row frame via pack(in_=...)).
        for w in list(group.winfo_children()):
            if getattr(w, '_is_wrap_row', False):
                w.destroy()
        children = [w for w in group.winfo_children() if not getattr(w, '_is_wrap_row', False)]
        for child in children:
            child.pack_forget()
            child.grid_forget()
        rows = [[]]
        used = 0
        gap = 2
        for child in children:
            req = max(child.winfo_reqwidth(), 1)
            if used and used + gap + req > available:
                rows.append([])
                used = 0
            rows[-1].append(child)
            used += req + gap
        for row_children in rows:
            row_frame = tk.Frame(group, bg=group.cget('bg'))
            row_frame._is_wrap_row = True
            row_frame.pack(side='top', anchor='w')
            # row_frame is a geometric anchor only (pack(in_=...) below
            # does not reparent the buttons -- they remain true siblings
            # of row_frame under `group`). Tk stacking order is by
            # creation time among true siblings, so this freshly-created
            # frame would otherwise paint OVER the (already-existing)
            # buttons it's meant to merely position, hiding them
            # entirely. Diagnosed 2026-08-19 as a regression introduced
            # by switching from grid(row=,column=) to this pack(in_=...)
            # scheme -- lower() pushes the anchor behind its content.
            row_frame.lower()
            for child in row_children:
                child.pack(in_=row_frame, side='left', padx=2, pady=2)

    def _relayout_toolbar(self):
        # Responsive layout must be re-entrant safe. Changing pack/grid geometry
        # generates <Configure> events; never allow those events to recursively
        # rebuild the toolbar while it is already being rebuilt.
        if not hasattr(self, '_toolbar_bar') or not self._toolbar_bar.winfo_exists():
            return
        if getattr(self, '_toolbar_relayout_running', False):
            return
        self._toolbar_relayout_pending = False
        self._toolbar_relayout_running = True
        try:
            bar = self._toolbar_bar
            available = max(1, bar.winfo_width() - 10)
            # NOTE: a previous version short-circuited here when `available`
            # matched a cached `_toolbar_last_width`, as a perf optimization.
            # That could permanently lock in a WRONG layout: the very first
            # relayout call (from after_idle, before the window's geometry
            # had fully stabilized) could read a transient/incorrect
            # bar.winfo_width(), compute a layout based on it, and cache
            # that width -- then a later, legitimate <Configure> event
            # reporting the SAME final width would hit the cache and skip
            # recomputation entirely, leaving the wrong wrap decision (e.g.
            # every group crammed into row 0, with the tail groups grid-
            # placed at columns whose x-position runs off the visible
            # toolbar area) in place indefinitely. Diagnosed 2026-08-19:
            # this is the actual mechanism behind "many buttons are
            # missing" -- they were never missing from the widget tree or
            # unbound, they were mapped at an off-screen grid position.
            # Recomputing every time is <1ms for ~25 buttons, so the cache
            # bought negligible performance at the cost of this class of
            # bug; it is removed rather than patched around.
            self._toolbar_last_width = available

            # First determine each group's requested width. If a group itself is
            # wider than the toolbar, wrap that group's children internally.
            for g in self._toolbar_groups:
                # Drop any leftover internal row-frames from a previous
                # (narrower) pass before measuring -- otherwise their
                # reqwidth contaminates this pass's fits-on-one-line
                # decision, and a stale empty row-frame could get
                # incorrectly re-packed as if it were real content.
                for w in list(g.winfo_children()):
                    if getattr(w, '_is_wrap_row', False):
                        w.destroy()
                children = [w for w in g.winfo_children() if not getattr(w, '_is_wrap_row', False)]
                for child in children:
                    child.grid_forget()
                    child.pack_forget()
                req = sum(max(ch.winfo_reqwidth(), 1) + 4 for ch in children)
                if req > available:
                    self._pack_responsive_group(g, available)
                else:
                    for child in children:
                        child.pack(side='left', padx=2, pady=3)

            # Lay groups left-to-right and wrap whole groups when necessary,
            # using one Frame per toolbar ROW (packed top-to-bottom) rather
            # than grid(row=,column=) directly on `bar`. Tk's grid geometry
            # manager shares column WIDTHS across every row of the same
            # parent -- so a wide group sitting in row 1 col 0 forces
            # column 0 to that width even for row 0, silently pushing a
            # narrower group sharing column 0's row rightward and often
            # off the visible toolbar. Diagnosed 2026-08-19 as the
            # remaining cause of buttons rendering off-screen at
            # in-between window widths, after the caching bug above was
            # fixed. Same fix as _pack_responsive_group: independent
            # per-row Frames, packed left-to-right inside each.
            for w in list(bar.winfo_children()):
                if getattr(w, '_is_toolbar_row', False):
                    w.destroy()
            for g in self._toolbar_groups:
                g.pack_forget()
                g.grid_forget()
            rows = [[]]
            used = 0
            gap = 6
            for g in self._toolbar_groups:
                req = max(g.winfo_reqwidth(), 1)
                if used and used + gap + req > available:
                    rows.append([])
                    used = 0
                rows[-1].append(g)
                used += req + gap
            for row_groups in rows:
                row_frame = tk.Frame(bar, bg=bar.cget('bg'))
                row_frame._is_toolbar_row = True
                row_frame.pack(side='top', fill='x', anchor='w', pady=1)
                # See the matching note in _pack_responsive_group: this
                # anchor frame must be pushed behind the (true-sibling)
                # group frames it positions, or it paints over them.
                row_frame.lower()
                for g in row_groups:
                    g.pack(in_=row_frame, side='left', padx=0)

            self._update_responsive_sidebars()
        finally:
            self._toolbar_relayout_running = False

    def _schedule_toolbar_relayout(self, _event=None):
        if self._toolbar_relayout_pending:
            return
        self._toolbar_relayout_pending = True
        self.after_idle(self._relayout_toolbar)

    def _update_responsive_sidebars(self):
        try:
            width = max(self.winfo_width(), 1)
            if width >= 1200:
                lw, rw = 190, 285
            elif width >= 1000:
                lw, rw = 175, 255
            elif width >= 850:
                lw, rw = 155, 235
            elif width >= 720:
                lw, rw = 135, 215
            else:
                lw, rw = 120, 195
            self.left.configure(width=lw)
            self.right.configure(width=rw)
            # Body uses a three-column grid, so sidebars retain their widths
            # while the center canvas receives all remaining desktop space.
        except Exception:
            pass

    def _build_object_tree(self, parent):
        tk.Label(parent, text='STRUCTURE', bg=PANEL_BG, fg=TEXT,
                 font=('Helvetica', 10, 'bold')).pack(anchor='w', padx=7, pady=(8, 4))
        frame = tk.Frame(parent, bg=PANEL_BG)
        frame.pack(fill='both', expand=True, padx=5)
        self.tree = ttk.Treeview(frame, show='tree', selectmode='extended')
        scroll = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self._tree_select)

        guide_btn = tk.Button(parent, text='📖 How to use Cable Web', command=self._show_guide,
                              relief='flat', bg='#f7f7f6', activebackground='#ddddda',
                              font=('Helvetica', 9, 'bold'), anchor='w')
        guide_btn.pack(fill='x', padx=7, pady=(2, 5))
        InfoTooltip(guide_btn, 'Open the interactive usage guide. It explains what each tool does, what to click, and when to use it.')

        tk.Label(parent, text='DISPLAY / SNAP', bg=PANEL_BG, fg=TEXT,
                 font=('Helvetica', 10, 'bold')).pack(anchor='w', padx=7, pady=(8, 3))
        for text, var in [('Grid', self.grid_visible), ('Snap to grid', self.snap_grid),
                          ('Show loads', self.show_loads), ('Show result labels', self.show_results)]:
            tk.Checkbutton(parent, text=text, variable=var, bg=PANEL_BG,
                           command=self._draw).pack(anchor='w', padx=7)
        tk.Label(parent, text='Snap to cables', bg=PANEL_BG, fg=MUTED).pack(anchor='w', padx=7, pady=(4,0))
        ttk.Combobox(parent, textvariable=self.snap_cable_mode,
                     values=('Off', 'Geometric', 'Attach'), state='readonly', width=16).pack(anchor='w', padx=7)
        tk.Label(parent, text='Geometric = same position only; Attach = structural junction.',
                 bg=PANEL_BG, fg=MUTED, wraplength=175, justify='left').pack(anchor='w', padx=7, pady=(2,0))

        tk.Label(parent, text='VALIDATION', bg=PANEL_BG, fg=TEXT,
                 font=('Helvetica', 10, 'bold')).pack(anchor='w', padx=7, pady=(10, 3))
        tk.Label(parent, textvariable=self.validation_var, bg=PANEL_BG,
                 fg=MUTED, justify='left', wraplength=175).pack(anchor='w', padx=7)

    def _build_inspector(self, parent):
        self.inspector_title = tk.Label(parent, text='PROPERTIES', bg=PANEL_BG,
                                        fg=TEXT, font=('Helvetica', 10, 'bold'))
        self.inspector_title.pack(anchor='w', padx=8, pady=(8, 4))
        self.inspector = tk.Frame(parent, bg=PANEL_BG)
        self.inspector.pack(fill='both', expand=True, padx=8)
        self._show_empty_inspector()

    def _clear_inspector(self):
        for w in self.inspector.winfo_children():
            w.destroy()

    def _show_empty_inspector(self):
        self._clear_inspector()
        tk.Label(self.inspector, text='Select a support, junction, cable,\nor load.',
                 bg=PANEL_BG, fg=MUTED, justify='left').pack(anchor='w', pady=8)

    def _entry_row(self, label, variable, row, readonly=False):
        tk.Label(self.inspector, text=label, bg=PANEL_BG, fg=TEXT).grid(
            row=row, column=0, sticky='w', pady=3)
        e = tk.Entry(self.inspector, textvariable=variable, width=15)
        e.grid(row=row, column=1, sticky='ew', pady=3)
        if readonly:
            e.configure(state='readonly')
        return e

    def _show_node_inspector(self, nid):
        n = self._node(nid)
        self._clear_inspector()
        tk.Label(self.inspector, text=f"{'SUPPORT' if n['support'] else 'JUNCTION'} {n['id']}",
                 bg=PANEL_BG, font=('Helvetica', 11, 'bold')).grid(row=0, column=0,
                 columnspan=2, sticky='w', pady=(0, 7))
        x, y = self._world_to_m(n['x'], n['y'])
        xv, yv = tk.DoubleVar(value=x), tk.DoubleVar(value=y)
        fxv, fyv = tk.DoubleVar(value=n['fx']), tk.DoubleVar(value=n['fy'])
        self._entry_row('X (m)', xv, 1)
        self._entry_row('Y (m)', yv, 2)
        if not n['support']:
            tk.Label(self.inspector, text='Point load', bg=PANEL_BG,
                     font=('Helvetica', 10, 'bold')).grid(row=3, column=0, columnspan=2,
                     sticky='w', pady=(10, 2))
            self._entry_row('Fx (N)', fxv, 4)
            self._entry_row('Fy (N)', fyv, 5)
        tk.Button(self.inspector, text='Apply', command=lambda: self._apply_node(nid, xv, yv, fxv, fyv),
                  relief='flat').grid(row=6, column=0, pady=8, sticky='w')
        tk.Button(self.inspector, text='Delete', command=lambda: self._delete_node(nid),
                  relief='flat').grid(row=6, column=1, pady=8, sticky='e')
        if not n['support']:
            tk.Label(self.inspector, text='Cable attachments:', bg=PANEL_BG,
                     font=('Helvetica', 10, 'bold')).grid(row=7, column=0, columnspan=2,
                     sticky='w', pady=(8, 2))
            attachment_vars=[]
            for k, (cid, s) in enumerate(n['attachments']):
                tk.Label(self.inspector, text=f'C{cid}  s (m)', bg=PANEL_BG).grid(row=8+k, column=0, sticky='w')
                sv=tk.DoubleVar(value=s); attachment_vars.append((cid,sv))
                tk.Entry(self.inspector, textvariable=sv, width=12).grid(row=8+k, column=1, sticky='e')
            if attachment_vars:
                tk.Label(self.inspector, text='Edit s precisely; the junction moves on the\nselected cable and other attachment s values are\nreprojected automatically.', bg=PANEL_BG, fg=MUTED,
                         justify='left').grid(row=8+len(attachment_vars), column=0, columnspan=2, sticky='w', pady=(5,2))
                tk.Button(self.inspector, text='Apply attachment positions', relief='flat',
                          command=lambda nid=nid, av=attachment_vars: self._apply_attachment_positions(nid,av)).grid(
                          row=9+len(attachment_vars), column=0, columnspan=2, sticky='w', pady=5)

    def _show_cable_inspector(self, cid):
        c = self._cable(cid)
        self._clear_inspector()
        tk.Label(self.inspector, text=f"CABLE C{cid}", bg=PANEL_BG,
                 font=('Helvetica', 11, 'bold')).grid(row=0, column=0, columnspan=2,
                 sticky='w', pady=(0, 7))
        a, b = self._node(c['a']), self._node(c['b'])
        geom = self._cable_length(cid)
        tk.Label(self.inspector, text=f"Endpoints: {a['id']} → {b['id']}",
                 bg=PANEL_BG, fg=MUTED).grid(row=1, column=0, columnspan=2, sticky='w')
        tk.Label(self.inspector, text=f"As-drawn span: {self._straight_distance(a,b):.4f} m",
                 bg=PANEL_BG, fg=MUTED).grid(row=2, column=0, columnspan=2, sticky='w')
        use = tk.BooleanVar(value=c['length_override'] is not None)
        lv = tk.DoubleVar(value=c['length_override'] if use.get() is not None and c['length_override'] is not None else geom)
        wv = tk.DoubleVar(value=c['w'])
        self._entry_row('Prescribed length', lv, 3)
        tk.Checkbutton(self.inspector, text='Use prescribed length', variable=use,
                       bg=PANEL_BG).grid(row=4, column=0, columnspan=2, sticky='w')
        self._entry_row('Self-weight (N/m)', wv, 5)
        # The field is in N/m and stays that way: relabelling it to kN/m would
        # silently reinterpret every saved model by 1000x. A live read-out is
        # the non-breaking half of the same convenience.
        kn = tk.Label(self.inspector, text='', bg=PANEL_BG, fg=MUTED,
                      font=('Helvetica', 8))
        kn.grid(row=5, column=2, sticky='w', padx=(4, 0))

        def _sync_kn(*_a):
            try:
                kn.config(text='= %.3f kN/m' % (float(wv.get()) / 1000.0))
            except (TypeError, ValueError):
                kn.config(text='')
        wv.trace_add('write', _sync_kn)
        _sync_kn()
        tk.Label(self.inspector, text='Junctions / load breakpoints are\nkept along this cable.',
                 bg=PANEL_BG, fg=MUTED, justify='left').grid(row=6, column=0, columnspan=2,
                 sticky='w', pady=(6, 4))
        tk.Button(self.inspector, text='Add load', command=lambda: self._open_load_dialog(cid),
                  relief='flat').grid(row=7, column=0, sticky='w', pady=4)
        tk.Button(self.inspector, text='Apply', command=lambda: self._apply_cable(cid, lv, use, wv),
                  relief='flat').grid(row=8, column=0, sticky='w', pady=8)
        tk.Button(self.inspector, text='Delete', command=lambda: self._delete_cable(cid),
                  relief='flat').grid(row=8, column=1, sticky='e', pady=8)
        row = 9
        for load in self.loads:
            if load['cable'] == cid:
                tk.Button(self.inspector, text=f"{load['id']}  {load['type']}",
                          command=lambda lid=load['id']: self._select('load', lid),
                          relief='flat', anchor='w').grid(row=row, column=0, columnspan=2,
                          sticky='ew', pady=1)
                row += 1
        if self.results_current and self.result is not None:
            tk.Label(self.inspector, text='Analysis result', bg=PANEL_BG,
                     font=('Helvetica', 10, 'bold')).grid(row=row, column=0, columnspan=2,
                     sticky='w', pady=(10, 2))
            vals = [self._result_tension(eid) for eid in self._solver_edges_for_cable(cid)]
            vals = [v for v in vals if v is not None]
            if vals:
                text = f'Tmin: {min(vals):.3g} N\nTmax: {max(vals):.3g} N'
                for eid in self._solver_edges_for_cable(cid):
                    try:
                        fx, fy = self.result.edge_force_components(eid)
                        text += f'\nSeg {eid}: Fx={fx:.3g}, Fy={fy:.3g} N'
                    except Exception:
                        pass
                tk.Label(self.inspector, text=text, bg=PANEL_BG, justify='left').grid(
                    row=row+1, column=0, columnspan=2, sticky='w')

    def _show_load_inspector(self, lid):
        load = self._load(lid)
        self._clear_inspector()
        tk.Label(self.inspector, text=f"LOAD {load['id']}", bg=PANEL_BG,
                 font=('Helvetica', 11, 'bold')).grid(row=0, column=0, columnspan=2,
                 sticky='w', pady=(0, 7))
        tk.Label(self.inspector, text=f"Cable C{load['cable']}", bg=PANEL_BG,
                 fg=MUTED).grid(row=1, column=0, columnspan=2, sticky='w')
        typ = tk.StringVar(value=load['type'])
        tk.Label(self.inspector, text='Type', bg=PANEL_BG).grid(row=2, column=0, sticky='w')
        ttk.Combobox(self.inspector, textvariable=typ, values=('Point', 'UDL', 'Variable'),
                     state='readonly', width=13).grid(row=2, column=1, sticky='ew')
        s1 = tk.DoubleVar(value=load['s1'])
        s2 = tk.DoubleVar(value=load['s2'])
        mag = tk.DoubleVar(value=load['magnitude'])
        direction = tk.StringVar(value=load['direction'])
        expr = tk.StringVar(value=load.get('expression', ''))
        angle = tk.DoubleVar(value=load.get('angle_deg', -90.0))
        self._entry_row('Start s (m)', s1, 3)
        self._entry_row('End s (m)', s2, 4)
        self._entry_row('Magnitude', mag, 5)
        tk.Label(self.inspector, text='Direction', bg=PANEL_BG).grid(row=6, column=0, sticky='w')
        ttk.Combobox(self.inspector, textvariable=direction,
                     values=('Vertical', 'Horizontal', 'Normal', 'Tangential', 'Custom'),
                     state='readonly', width=13).grid(row=6, column=1, sticky='ew')
        self._entry_row('q(s) expression', expr, 7)
        self._entry_row('Custom angle (deg)', angle, 8)
        tk.Button(self.inspector, text='Apply', relief='flat',
                  command=lambda: self._apply_load(lid, typ, s1, s2, mag, direction, expr, angle)
                  ).grid(row=9, column=0, pady=8, sticky='w')
        tk.Button(self.inspector, text='Delete', relief='flat',
                  command=lambda: self._delete_load(lid)).grid(row=9, column=1, pady=8, sticky='e')

    # ------------------------------------------------------------------
    # Tree and selection
    # ------------------------------------------------------------------
    def _refresh_diagram_cables(self):
        """Keep the diagram pane's cable list in step with the model."""
        self._sync_diagram_pane()

    def _refresh_tree(self):
        if not hasattr(self,'tree'): return
        self._syncing_tree=True
        try:
            self.tree.delete(*self.tree.get_children())
            roots={title:self.tree.insert('', 'end', text=title, open=True) for title in ('Supports','Junctions','Cables','Loads')}
            for n in self.nodes:
                self.tree.insert(roots['Supports' if n['support'] else 'Junctions'],'end',iid=f'node:{n["id"]}',text=str(n['id']))
            for c in self.cables:
                self.tree.insert(roots['Cables'],'end',iid=f'cable:{c["id"]}',text=f'C{c["id"]}')
            for l in self.loads:
                self.tree.insert(roots['Loads'],'end',iid=f'load:{l["id"]}',text=str(l['id']))
            for kind,ident in self.selected_items:
                iid=f'{kind}:{ident}'
                if self.tree.exists(iid): self.tree.selection_add(iid)
        finally:
            self._syncing_tree=False

    def _tree_select(self, _event=None):
        if self._syncing_tree:
            return
        selections=[]
        for item in self.tree.selection():
            try: kind, ident = item.split(':',1)
            except ValueError: continue
            if kind=='node': selections.append(('node',int(ident)))
            elif kind=='cable': selections.append(('cable',int(ident)))
            elif kind=='load': selections.append(('load',str(ident)))
        if not selections:
            return
        self.selected_items=set(selections)
        self.selected_kind,self.selected_id=selections[-1]
        if len(selections)==1:
            self._show_inspector_for(*selections[0])
        else:
            self._show_multi_inspector()
        self._draw()

    def _show_inspector_for(self, kind, ident):
        if kind=='node': self._show_node_inspector(int(ident))
        elif kind=='cable': self._show_cable_inspector(int(ident))
        elif kind=='load': self._show_load_inspector(str(ident))

    def _select(self, kind, ident, replace=True):
        item=(kind,ident)
        if replace: self.selected_items={item}
        else: self.selected_items.add(item)
        self.selected_kind,self.selected_id=kind,ident
        if len(self.selected_items)==1: self._show_inspector_for(kind,ident)
        else: self._show_multi_inspector()
        self._sync_tree_selection()
        self._draw()

    def _show_multi_inspector(self):
        self._clear_inspector()
        tk.Label(self.inspector,text=f'{len(self.selected_items)} ELEMENTS SELECTED',bg=PANEL_BG,fg=TEXT,font=('Helvetica',11,'bold')).pack(anchor='w',pady=5)
        counts={}
        for kind,_ in self.selected_items: counts[kind]=counts.get(kind,0)+1
        for kind in sorted(counts):
            tk.Label(self.inspector,text=f'{kind.title()}: {counts[kind]}',bg=PANEL_BG,fg=MUTED).pack(anchor='w')
        tk.Button(self.inspector,text='Delete selected',relief='flat',command=self._delete_selected).pack(anchor='w',pady=10)

    def _sync_tree_selection(self):
        if not hasattr(self,'tree') or self._syncing_tree: return
        self._syncing_tree=True
        try:
            self.tree.selection_remove(self.tree.selection())
            for kind,ident in sorted(self.selected_items,key=lambda x:(x[0],str(x[1]))):
                iid=f'{kind}:{ident}'
                if self.tree.exists(iid): self.tree.selection_add(iid)
            if self.selected_kind is not None:
                iid=f'{self.selected_kind}:{self.selected_id}'
                if self.tree.exists(iid): self.tree.see(iid)
        finally:
            self._syncing_tree=False

    # ------------------------------------------------------------------
    # Object access
    # ------------------------------------------------------------------
    def _node(self, nid):
        return next(n for n in self.nodes if n['id'] == int(nid))

    def _cable(self, cid):
        return next(c for c in self.cables if c['id'] == int(cid))

    def _load(self, lid):
        return next(l for l in self.loads if str(l['id']) == str(lid))

    def _set_tool(self, tool):
        self.tool.set(tool)
        self.connect_start = None
        for value, button in self.tool_buttons.items():
            button.configure(relief='sunken' if value == tool else 'flat', bg='#dededb' if value == tool else '#f7f7f6')
        self.status_var.set({
            'select': 'Select: click an element; drag an empty area to box-select multiple elements.',
            'cable': 'Cable: click start and end points.',
            'support': 'Support: click an empty location or existing free node.',
            'junction': 'Junction: click a cable to attach at that position.',
            'connect': 'Connect: click two existing nodes/cable endpoints.',
            'load': 'Load: select a cable, then click to place a point load.',
            'measure': 'Measure: click two points.',
            'pan': 'Pan: left-drag the canvas to move the view without editing the structure.'
        }.get(tool, ''))
        self._draw()

    # ------------------------------------------------------------------
    # Canvas interaction
    # ------------------------------------------------------------------
    def _motion(self, event):
        wx, wy = self.zc.s2w(event.x, event.y)
        mx, my = self._world_to_m(wx, wy)
        self.coord_var.set(f'x = {mx:.3f} m    y = {my:.3f} m')

    def _on_canvas_configure(self, event=None):
        self._draw()

    def _canvas_press(self, event):
        if self._solving:
            # A background Analyze/Form-find is in progress (see
            # _solve_exact) -- block canvas edits so the eventual result
            # can't end up attributed to a model that changed underneath
            # it. This is the main edit path (selecting, dragging, placing
            # new elements) but not the only one; toolbar buttons for
            # Analyze/Form-find are separately disabled for the same
            # reason, but other toolbar buttons and dialogs are not
            # blocked -- a known, deliberate scope limit, not an oversight.
            return
        wx, wy = self.zc.s2w(event.x, event.y)
        tool = self.tool.get()
        if tool == 'pan':
            self.zc._pan_start(event)
            self.drag_state = ('viewpan',)
            return
        if tool == 'select':
            hit = self._hit(wx, wy)
            if hit:
                additive = bool(event.state & 0x0001)
                self._select(*hit, replace=not additive)
                if hit[0] == 'node' and not additive:
                    self._checkpoint()
                    self._drag_checkpointed = True
                    self.drag_state = ('node', hit[1], wx, wy)
            else:
                # Empty-canvas drag becomes a CAD-style selection rectangle.
                self._selection_box_start = (wx, wy)
                self._selection_box_item = self.zc.canvas.create_rectangle(
                    event.x, event.y, event.x, event.y, outline=SELECT,
                    dash=(4, 2), width=1)
                self.drag_state = ('selectbox', wx, wy)
            return
        if tool == 'support':
            n = self._nearest_node(wx, wy)
            self._checkpoint()
            if n is not None:
                n['support'] = True
                n['fx'] = n['fy'] = 0.0
            else:
                wx, wy = self._snap_world(wx, wy)
                self._new_node(wx, wy, True)
            self._invalidate('Support changed.')
            self._draw()
            return
        if tool == 'cable':
            # Existing nodes always take priority. If the endpoint is not an
            # existing node, optionally snap to a parent cable. In Geometric
            # mode the new node merely shares the coordinate; in Attach mode
            # it is a true structural junction on the parent cable.
            n = self._nearest_node(wx, wy)
            attachment = None
            if n is None:
                mode = self.snap_cable_mode.get()
                hit = self._nearest_cable_point(wx, wy) if mode in ('Geometric', 'Attach') else None
                if hit:
                    cid, ss, qx, qy, _ = hit
                    wx, wy = qx, qy
                    attachment = (cid, ss) if mode == 'Attach' else None
                else:
                    wx, wy = self._snap_world(wx, wy)
                n = self._new_node(wx, wy, False)
                if attachment:
                    self._attach_node(n['id'], attachment[0], attachment[1])
            if self.connect_start is None:
                self.connect_start = n['id']
                self.status_var.set(f"Cable starts at {n['id']}; click the other end.")
            else:
                if n['id'] != self.connect_start:
                    self._new_cable(self.connect_start, n['id'])
                self.connect_start = None
            self._draw()
            return
        if tool == 'connect':
            n = self._nearest_node(wx, wy)
            if n is None:
                self.status_var.set('Connect requires existing nodes. Use Junction to attach to a cable.')
                return
            if self.connect_start is None:
                self.connect_start = n['id']
                self.status_var.set(f"Connect starts at {n['id']}; click the second node.")
            elif n['id'] != self.connect_start:
                if not self._cable_exists(self.connect_start, n['id']):
                    self._new_cable(self.connect_start, n['id'])
                self.connect_start = None
            self._draw()
            return
        if tool == 'junction':
            hit=self._nearest_cable_point(wx,wy)
            if hit:
                cid,s,*_=hit
                self._open_junction_dialog(cid,s)
            else:
                self.status_var.set('Click directly on a cable to create a junction.')
            return
        if tool == 'load':
            hit = self._nearest_cable_point(wx, wy)
            if hit:
                cid, s, *_ = hit
                self._open_load_dialog(cid, default_s=s)
            else:
                self.status_var.set('Click on a cable to place a load.')
            return
        if tool == 'measure':
            if self.drag_state is None:
                self.drag_state = ('measure', wx, wy)
                self.status_var.set('Click/drag to the second point.')
            return

    def _canvas_drag(self, event):
        if not self.drag_state:
            return
        wx, wy = self.zc.s2w(event.x, event.y)
        if self.drag_state[0] == 'viewpan':
            self.zc._pan_move(event)
            return
        if self.drag_state[0] == 'selectbox':
            x0, y0 = self.drag_state[1], self.drag_state[2]
            sx0, sy0 = self.zc.w2s(x0, y0)
            self.zc.canvas.coords(self._selection_box_item, sx0, sy0, event.x, event.y)
            return
        if self.drag_state[0] == 'node':
            nid = self.drag_state[1]
            n = self._node(nid)
            if n['support']:
                wx, wy = self._snap_world(wx, wy)
            else:
                # A junction attached to cables follows the nearest parent cable.
                if n['attachments']:
                    cid, _s = n['attachments'][0]
                    hit = self._nearest_cable_point(wx, wy, only=cid)
                    if hit:
                        _, s, qx, qy, _ = hit
                        wx, wy = qx, qy
                        self._set_attachment_s(nid, cid, s)
                else:
                    wx, wy = self._snap_world(wx, wy)
            n['x'], n['y'] = wx, wy
            self._invalidate('Geometry changed; results need recalculation.')
            self._draw()
        elif self.drag_state[0] == 'measure':
            x0, y0 = self.drag_state[1], self.drag_state[2]
            d = math.hypot(wx - x0, wy - y0) / PX_PER_M
            self.status_var.set(f'Measurement: {d:.3f} m')

    def _canvas_release(self, event):
        if self.drag_state and self.drag_state[0] == 'viewpan':
            self.zc._pan_end(event)
        elif self.drag_state and self.drag_state[0] == 'selectbox':
            x0, y0 = self.drag_state[1], self.drag_state[2]
            wx, wy = self.zc.s2w(event.x, event.y)
            self.selected_items = self._items_in_rect(min(x0, wx), min(y0, wy),
                                                       max(x0, wx), max(y0, wy))
            if self.selected_items:
                self.selected_kind, self.selected_id = next(iter(self.selected_items))
                if len(self.selected_items) == 1:
                    self._select(self.selected_kind, self.selected_id, replace=False)
                else:
                    self._show_multi_inspector(); self._sync_tree_selection(); self._draw()
            else:
                self.selected_items.clear(); self.selected_kind = self.selected_id = None
                self._show_empty_inspector(); self._draw()
            if self._selection_box_item is not None:
                try: self.zc.canvas.delete(self._selection_box_item)
                except Exception: pass
                self._selection_box_item = None
        elif self.drag_state and self.drag_state[0] == 'node':
            self._refresh_attachments_for_node(self.drag_state[1])
            self._update_reference_result()
            self._draw()
        elif self.drag_state and self.drag_state[0] == 'measure':
            x0, y0 = self.drag_state[1], self.drag_state[2]
            wx, wy = self.zc.s2w(event.x, event.y)
            d = math.hypot(wx - x0, wy - y0) / PX_PER_M
            self.status_var.set(f'Measurement: {d:.3f} m')
        self.drag_state = None

    def _segment_intersects_rect(self, ax, ay, bx, by, x0, y0, x1, y1):
        dx,dy=bx-ax,by-ay
        p=(-dx,dx,-dy,dy); q=(ax-x0,x1-ax,ay-y0,y1-ay)
        u0,u1=0.0,1.0
        for pi,qi in zip(p,q):
            if abs(pi)<1e-15:
                if qi<0: return False
                continue
            r=qi/pi
            if pi<0:
                if r>u1: return False
                u0=max(u0,r)
            else:
                if r<u0: return False
                u1=min(u1,r)
        return True

    def _items_in_rect(self,x0,y0,x1,y1):
        out=set()
        def inside(x,y): return x0<=x<=x1 and y0<=y<=y1
        for n in self.nodes:
            if inside(n['x'],n['y']): out.add(('node',n['id']))
        for cdata in self.cables:
            poly=self._cable_polyline(cdata['id'])
            if any(self._segment_intersects_rect(p[2],p[3],q[2],q[3],x0,y0,x1,y1) for p,q in zip(poly,poly[1:])):
                out.add(('cable',cdata['id']))
        for l in self.loads:
            try:
                L=max(self._cable_length(l['cable']),1e-12)
                cdata=self._cable(l['cable']); a=self._node(cdata['a']); b=self._node(cdata['b'])
                def pos(ss):
                    t=max(0,min(1,ss/L)); return a['x']+t*(b['x']-a['x']),a['y']+t*(b['y']-a['y'])
                if l['type']=='Point':
                    if inside(*pos(l['s1'])): out.add(('load',str(l['id'])))
                else:
                    lo,hi=sorted((l['s1'],l['s2']))
                    if self._segment_intersects_rect(*pos(lo),*pos(hi),x0,y0,x1,y1): out.add(('load',str(l['id'])))
            except Exception:
                pass
        return out

    # ------------------------------------------------------------------
    # Geometry/topology
    # ------------------------------------------------------------------
    def _new_node(self, wx, wy, support=False):
        self._checkpoint()
        n = {'id': self.next_node_id, 'x': wx, 'y': wy, 'support': support,
             'fx': 0.0, 'fy': 0.0, 'attachments': []}
        self.next_node_id += 1
        self.nodes.append(n)
        self._refresh_tree()
        return n

    def _new_cable(self, a, b):
        if a == b or self._cable_exists(a, b):
            return None
        self._checkpoint()
        c = {'id': self.next_cable_id, 'a': a, 'b': b, 'w': DEFAULT_SELF_WEIGHT,
             'length_override': None}
        self.next_cable_id += 1
        self.cables.append(c)
        self._refresh_tree()
        self._invalidate(f"Cable C{c['id']} created.")
        self._update_reference_result()
        return c

    def _cable_exists(self, a, b):
        return any((c['a'] == a and c['b'] == b) or (c['a'] == b and c['b'] == a)
                   for c in self.cables)

    def _attach_node(self, nid, cid, s):
        self._checkpoint()
        n = self._node(nid)
        # Do not duplicate attachment.
        for k, (oldcid, _olds) in enumerate(n['attachments']):
            if oldcid == cid:
                n['attachments'][k] = (cid, s)
                return
        n['attachments'].append((cid, s))
        self._set_attachment_s(nid, cid, s)

    def _set_attachment_s(self, nid, cid, s):
        n = self._node(nid)
        L = max(self._cable_length(cid), 1e-12)
        s = max(0.0, min(L, s))
        for k, (oldcid, _olds) in enumerate(n['attachments']):
            if oldcid == cid:
                n['attachments'][k] = (cid, s)
                return
        n['attachments'].append((cid, s))

    def _refresh_attachments_for_node(self, nid):
        n = self._node(nid)
        for cid, _ in list(n['attachments']):
            hit = self._nearest_cable_point(n['x'], n['y'], only=cid)
            if hit:
                self._set_attachment_s(nid, cid, hit[1])

    def _cable_polyline(self, cid):
        c = self._cable(cid)
        a, b = self._node(c['a']), self._node(c['b'])
        items = [(0.0, a['id'], a['x'], a['y']),
                 (self._cable_length(cid), b['id'], b['x'], b['y'])]
        # Base endpoints define the initial chord. Interior attachments are
        # projected onto the current chord. This keeps the UI deterministic
        # and lets the solver subsequently determine the loaded shape.
        for n in self.nodes:
            for ac, s in n['attachments']:
                if ac != cid or n['id'] in (a['id'], b['id']):
                    continue
                items.append((s, n['id'], n['x'], n['y']))
        items.sort(key=lambda z: z[0])
        # Remove duplicate ids/near-duplicate positions.
        out, seen = [], set()
        for item in items:
            if item[1] not in seen:
                out.append(item); seen.add(item[1])
        return out

    def _straight_distance(self, a, b):
        return math.hypot(a['x'] - b['x'], a['y'] - b['y']) / PX_PER_M

    def _cable_length(self, cid):
        """Reference/material length used by cable-local coordinates."""
        c = self._cable(cid)
        a, b = self._node(c['a']), self._node(c['b'])
        return c['length_override'] if c['length_override'] is not None else self._straight_distance(a, b)

    def _nearest_node(self, wx, wy, threshold=None):
        if threshold is None:
            threshold = 14 / max(self.zc.zoom, 0.1)
        best = None; bd = threshold
        for n in self.nodes:
            d = math.hypot(n['x'] - wx, n['y'] - wy)
            if d < bd:
                best, bd = n, d
        return best

    def _nearest_cable_point(self, wx, wy, only=None):
        best = None
        threshold = 9 / max(self.zc.zoom, 0.1)
        for c in self.cables:
            if only is not None and c['id'] != only:
                continue
            a, b = self._node(c['a']), self._node(c['b'])
            # Use current straight chord for attachment selection.
            t, qx, qy, d = project_seg(wx, wy, a['x'], a['y'], b['x'], b['y'])
            if d <= threshold:
                # `s` is a cable-local/material coordinate.  When a cable
                # has a prescribed length, it is NOT the same thing as the
                # straight chord length.  Using the chord here made a click
                # at the middle of a 2L cable report s=L/2 instead of s=L.
                L = max(self._cable_length(c['id']), 1e-12)
                s = t * L
                cand = (c['id'], s, qx, qy, d)
                if best is None or d < best[-1]:
                    best = cand
        return best

    def _hit_load(self, wx, wy):
        # Loads get their own hit target so clicking an arrow selects the load
        # rather than the parent cable. Returns (kind_tuple, distance) for the
        # closest matching load within tolerance, or None -- the distance is
        # needed by _hit() to arbitrate against a node/cable candidate at a
        # similar position (e.g. a load positioned right at a support).
        best = None
        best_d = None
        for l in reversed(self.loads):
            try:
                cid=l['cable']; L=max(self._cable_length(cid),1e-12)
                cdata=self._cable(cid); a=self._node(cdata['a']); b=self._node(cdata['b'])
                def pos(ss):
                    t=max(0.0,min(1.0,ss/L)); return a['x']+t*(b['x']-a['x']),a['y']+t*(b['y']-a['y'])
                thresh = 16/max(self.zc.zoom,0.1)
                if l['type']=='Point':
                    x,y=pos(l['s1'])
                    d = math.hypot(wx-x,wy-y)
                    if d <= thresh and (best_d is None or d < best_d):
                        best, best_d = ('load',str(l['id'])), d
                else:
                    lo,hi=sorted((l['s1'],l['s2']))
                    x0,y0=pos(lo); x1,y1=pos(hi)
                    d = dist_seg(wx,wy,x0,y0,x1,y1)
                    if d <= thresh and (best_d is None or d < best_d):
                        best, best_d = ('load',str(l['id'])), d
            except Exception:
                continue
        return (best, best_d) if best is not None else None

    def _hit(self, wx, wy):
        # Compare the closest candidate of EACH type (node / load / cable)
        # by actual distance, rather than a fixed type-priority order.
        # Previously this always checked loads first regardless of
        # proximity, so a support with a load positioned at or near it
        # (e.g. a UDL starting exactly at s=0, right at that support -- a
        # completely ordinary layout, see the reported bug) could never be
        # selected at all: the load, not the much-closer support, always
        # won the hit test. Diagnosed and fixed 2026-08-20.
        candidates = []  # (distance, hit_tuple)

        n = self._nearest_node(wx, wy)
        if n:
            d = math.hypot(n['x'] - wx, n['y'] - wy)
            # A node gets a small fixed "capture bonus" over loads/cables
            # in this comparison: a click still close to a node (within
            # its own hit radius) should win even if a load's or cable's
            # line is technically a hair closer. This specifically matters
            # when a load's parent cable happens to be collinear with an
            # UNRELATED node -- e.g. every node freshly drawn at the same
            # height, before any solve -- which otherwise breaks that
            # node's selection/drag the moment a click drifts even a
            # couple of pixels off its exact center, even though the
            # load has nothing to do with that node. Diagnosed 2026-08-21
            # (reported as "supports 2 and 3 don't move" in the Picture
            # Example -- node 2 and node 3 aren't part of the cable the
            # competing load belongs to at all; they just happened to
            # start out sitting on the same as-drawn line). This is a
            # comparison-only discount -- it doesn't change whether a
            # node is in range at all (_nearest_node's own threshold is
            # unchanged), only how it's ranked against a competing hit.
            capture_bonus = 6.0 / max(self.zc.zoom, 0.1)
            candidates.append((max(d - capture_bonus, 0.0), ('node', n['id'])))

        load_hit = self._hit_load(wx, wy)
        if load_hit:
            (kind_tuple, d) = load_hit
            candidates.append((d, kind_tuple))

        hit = self._nearest_cable_point(wx, wy)
        if hit:
            cid, ss, qx, qy, d = hit
            candidates.append((d, ('cable', cid)))

        if not candidates:
            return None
        # Node is listed first above, so a stable sort keeps it as the
        # winner on an exact tie (e.g. a load positioned precisely at a
        # support, distance 0 for both) -- the structural point is the more
        # sensible default when a click is genuinely ambiguous between the
        # two.
        candidates.sort(key=lambda c: c[0])
        return candidates[0][1]

    # ------------------------------------------------------------------
    # Properties actions
    # ------------------------------------------------------------------
    def _apply_node(self, nid, xv, yv, fxv, fyv):
        self._checkpoint()
        n = self._node(nid)
        n['x'], n['y'] = xv.get() * PX_PER_M, -yv.get() * PX_PER_M
        if not n['support']:
            n['fx'], n['fy'] = fxv.get(), fyv.get()
        self._refresh_attachments_for_node(nid)
        self._invalidate('Node changed.')
        self._refresh_tree(); self._draw()

    def _apply_attachment_positions(self, nid, attachment_vars):
        try:
            values=[(cid,float(var.get())) for cid,var in attachment_vars]
        except Exception:
            messagebox.showerror('Junction', 'Enter valid attachment positions.', parent=self.winfo_toplevel()); return
        if not values:
            return
        self._checkpoint()
        # A physical junction has one global position. Use the first edited
        # attachment as the authoritative coordinate, then reproject the same
        # point onto every other parent cable.
        cid, ss = values[0]
        L=self._cable_length(cid)
        if not (0 <= ss <= L):
            messagebox.showerror('Junction', f's must be between 0 and {L:.6f} m.', parent=self.winfo_toplevel()); return
        n=self._node(nid); n['x'],n['y']=self._point_on_chord(cid,ss)
        n['attachments']=[]
        for ac,_ in values:
            hit=self._nearest_cable_point(n['x'],n['y'],only=ac)
            if hit:
                self._set_attachment_s(nid,ac,hit[1])
        self._invalidate(f'Junction {n["id"]} position updated.')
        self._update_reference_result(); self._refresh_tree(); self._show_node_inspector(nid); self._draw()

    def _apply_cable(self, cid, lv, use, wv):
        self._checkpoint()
        c = self._cable(cid)
        c['w'] = max(0.0, wv.get())
        c['length_override'] = max(1e-9, lv.get()) if use.get() else None
        self._invalidate(f'C{cid} changed.')
        self._update_reference_result()
        self._show_cable_inspector(cid); self._draw()

    def _apply_load(self, lid, typ, s1, s2, mag, direction, expr, angle):
        l = self._load(lid)
        try:
            ns1=max(0.0,float(s1.get())); ns2=max(0.0,float(s2.get()))
            magnitude=float(mag.get()); angle_deg=float(angle.get())
        except Exception:
            messagebox.showerror('Load','Enter valid numeric values.',parent=self.winfo_toplevel()); return
        L=self._cable_length(l['cable'])
        if not (0.0 <= ns1 <= L and 0.0 <= ns2 <= L):
            messagebox.showerror('Load',f'Load positions must lie between 0 and {L:.6f} m.',parent=self.winfo_toplevel()); return
        ntyp=typ.get(); nexpr=expr.get().strip()
        if ntyp=='Variable' and not nexpr:
            messagebox.showerror('Load','A Variable load requires a q(s) expression.',parent=self.winfo_toplevel()); return
        self._checkpoint()
        l.update(type=ntyp,s1=ns1,s2=ns2,magnitude=magnitude,direction=direction.get(),expression=nexpr,angle_deg=angle_deg)
        if l['type']=='Point': l['s2']=l['s1']
        self._invalidate(f'Load {lid} changed.')
        self._show_load_inspector(lid); self._draw()

    def _delete_node(self, nid):
        self._checkpoint()
        nid = int(nid)
        self.cables = [c for c in self.cables if c['a'] != nid and c['b'] != nid]
        self.loads = [l for l in self.loads if l['cable'] in {c['id'] for c in self.cables}]
        self.nodes = [n for n in self.nodes if n['id'] != nid]
        self.selected_kind = self.selected_id = None
        self.selected_items.clear()
        self._invalidate(f'Node {nid} deleted.')
        self._refresh_tree(); self._show_empty_inspector(); self._draw()

    def _delete_cable(self, cid):
        self._checkpoint()
        cid = int(cid)
        self.cables = [c for c in self.cables if c['id'] != cid]
        self.loads = [l for l in self.loads if l['cable'] != cid]
        for n in self.nodes:
            n['attachments'] = [(c, s) for c, s in n['attachments'] if c != cid]
        self.selected_kind = self.selected_id = None
        self.selected_items.clear()
        self._invalidate(f'Cable C{cid} deleted.')
        self._refresh_tree(); self._show_empty_inspector(); self._draw()

    def _delete_load(self, lid):
        self._checkpoint()
        self.loads = [l for l in self.loads if str(l['id']) != str(lid)]
        self.selected_kind = self.selected_id = None
        self.selected_items.clear()
        self._invalidate(f'Load {lid} deleted.')
        self._refresh_tree(); self._show_empty_inspector(); self._draw()

    def _open_junction_dialog(self, cid, default_s):
        L = self._cable_length(cid)
        dlg = tk.Toplevel(self); dlg.title(f'Junction on Cable C{cid}'); dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        s_var = tk.DoubleVar(value=max(0.0, min(L, default_s)))
        tk.Label(dlg, text=f'Cable C{cid} length: {L:.6f} m').grid(row=0, column=0, columnspan=2, padx=10, pady=(10,4), sticky='w')
        tk.Label(dlg, text='Position s (m):').grid(row=1, column=0, padx=10, pady=5, sticky='w')
        tk.Entry(dlg, textvariable=s_var, width=18).grid(row=1, column=1, padx=10, pady=5)
        tk.Label(dlg, text='Normalized s/L:').grid(row=2, column=0, padx=10, pady=3, sticky='w')
        norm = tk.StringVar(value=f'{s_var.get()/L:.6f}' if L else '0')
        tk.Label(dlg, textvariable=norm).grid(row=2, column=1, padx=10, pady=3, sticky='w')
        def update_norm(*_):
            try: norm.set(f'{max(0,min(L,s_var.get()))/L:.6f}' if L else '0')
            except Exception: pass
        s_var.trace_add('write', update_norm)
        def create():
            try: ss=float(s_var.get())
            except Exception:
                messagebox.showerror('Junction', 'Enter a valid position s.', parent=dlg); return
            if not (0.0 <= ss <= L):
                messagebox.showerror('Junction', f's must be between 0 and {L:.6f} m.', parent=dlg); return
            xw,yw=self._point_on_chord(cid, ss)
            n=self._nearest_node(xw,yw,12/max(self.zc.zoom,0.1))
            if n is None or n['support']:
                if n is not None and n['support']:
                    messagebox.showerror('Junction', 'Cannot convert an existing support into an interior junction.', parent=dlg); return
                n=self._new_node(xw,yw,False)
            self._attach_node(n['id'],cid,ss)
            self._select('node',n['id'])
            self._invalidate(f'Junction {n["id"]} attached to C{cid} at s={ss:.6f} m.')
            self._update_reference_result(); self._draw(); dlg.destroy()
        tk.Button(dlg,text='Create junction',command=create,relief='flat').grid(row=3,column=0,padx=10,pady=10,sticky='w')
        tk.Button(dlg,text='Cancel',command=dlg.destroy,relief='flat').grid(row=3,column=1,padx=10,pady=10,sticky='e')

    # ------------------------------------------------------------------
    # Loads
    # ------------------------------------------------------------------
    def _open_load_dialog(self, cid, default_s=None):
        dlg = tk.Toplevel(self); dlg.title(f'Load on Cable C{cid}'); dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        typ = tk.StringVar(value='Point')
        s1 = tk.DoubleVar(value=default_s if default_s is not None else 0.0)
        s2 = tk.DoubleVar(value=default_s if default_s is not None else self._cable_length(cid))
        mag = tk.DoubleVar(value=10.0)
        direction = tk.StringVar(value='Vertical')
        expr = tk.StringVar(value='')
        angle = tk.DoubleVar(value=-90.0)
        fields = [('Type', typ), ('Start s (m)', s1), ('End s (m)', s2),
                  ('Magnitude', mag), ('Direction', direction), ('Custom angle (deg)', angle), ('q(s)', expr)]
        for r, (lab, var) in enumerate(fields):
            tk.Label(dlg, text=lab).grid(row=r, column=0, sticky='w', padx=8, pady=4)
            if lab == 'Type':
                ttk.Combobox(dlg, textvariable=var, values=('Point','UDL','Variable'),
                             state='readonly', width=16).grid(row=r, column=1, padx=8)
            elif lab == 'Direction':
                ttk.Combobox(dlg, textvariable=var,
                             values=('Vertical','Horizontal','Normal','Tangential','Custom'),
                             state='readonly', width=16).grid(row=r, column=1, padx=8)
            else:
                tk.Entry(dlg, textvariable=var, width=18).grid(row=r, column=1, padx=8)
        def add():
            try:
                l = {'id': f'L{self.next_load_id}', 'cable': cid, 'type': typ.get(),
                     's1': max(0.0, s1.get()), 's2': max(0.0, s2.get()),
                     'magnitude': mag.get(), 'direction': direction.get(), 'angle_deg': angle.get(),
                     'expression': expr.get().strip()}
            except Exception:
                messagebox.showerror('Load', 'Enter valid numeric values.', parent=dlg); return
            L = self._cable_length(cid)
            if not (0.0 <= l['s1'] <= L and 0.0 <= l['s2'] <= L):
                messagebox.showerror('Load', f'Load positions must lie between 0 and {L:.6f} m.', parent=dlg); return
            if l['type'] == 'Point': l['s2'] = l['s1']
            elif l['s1'] > l['s2']:
                # Store ranged loads with s1<=s2 -- a UDL/Variable entered
                # backwards (e.g. Start=17, End=0) still solved correctly
                # (downstream code already sorts internally), but showed
                # an inverted, confusing range everywhere it's displayed
                # (topology browser, inspector). Diagnosed 2026-08-21.
                l['s1'], l['s2'] = l['s2'], l['s1']
            if l['type'] == 'Variable':
                if not l['expression']:
                    messagebox.showerror('Load', 'A Variable load requires a q(s) expression.', parent=dlg); return
                # Validate the expression NOW, not only when the user
                # later clicks Analyze. Diagnosed 2026-08-21: a syntax
                # error (e.g. '5 + * 2s') was previously accepted
                # silently by this dialog and only surfaced as a failed
                # Analyze much later -- confusing when the user has since
                # moved on to other edits. Reuses the same evaluator
                # (_safe_expr) the real solve uses, so "validates here"
                # and "will work at Analyze time" mean the same thing.
                try:
                    test_s = 0.5 * (l['s1'] + l['s2'])
                    self._safe_expr(l['expression'], test_s, L)
                except Exception as ex:
                    messagebox.showerror('Load', f'Invalid q(s) expression: {ex}', parent=dlg); return
            self._checkpoint()
            self.next_load_id += 1
            self.loads.append(l)
            dlg.destroy(); self._invalidate(f"Load {l['id']} added to C{cid}.")
            self._refresh_tree(); self._draw()
        tk.Button(dlg, text='Add load', command=add, relief='flat').grid(row=7, column=0, pady=8)
        tk.Button(dlg, text='Cancel', command=dlg.destroy, relief='flat').grid(row=7, column=1, pady=8)

    # ------------------------------------------------------------------
    # Solver model construction
    # ------------------------------------------------------------------
    def _safe_expr(self, expr, s, L):
        if not expr:
            return 0.0
        expr = expr.replace('^', '**')
        env = {k: getattr(math, k) for k in dir(math) if not k.startswith('_')}
        env.update({'s': s, 'x': s, 'L': L, 'pi': math.pi})
        # Local engineering tool: explicitly reject names outside the math context.
        if re.search(r'[^0-9A-Za-z_+\-*/().,\s]', expr):
            raise ValueError(f'Unsupported character in q(s): {expr}')
        return float(eval(expr, {'__builtins__': {}}, env))

    def _direction_vector(self, direction, ax, ay, bx, by, custom_deg=90.0):
        if direction == 'Vertical': return (0.0, -1.0)
        if direction == 'Horizontal': return (1.0, 0.0)
        ux, uy = unit(bx - ax, by - ay)
        if direction == 'Tangential': return (ux, uy)
        if direction == 'Normal': return (-uy, ux)
        a = math.radians(custom_deg)
        return math.cos(a), math.sin(a)

    def _solver_breakpoints(self, cid, include_user_loads=True):
        # A graded mesh from the first Analyze pass wins, when one exists --
        # see _graded_breakpoints. It already contains every pinned point,
        # so the rest of this method would only re-derive what it holds.
        graded = self._graded_bp.get(cid) if include_user_loads else None
        if graded:
            return list(graded)
        c = self._cable(cid)
        L = max(self._cable_length(cid), 1e-12)
        pts = {0.0, L}
        # EVERY user cable is subdivided, including taut, weightless, unloaded
        # ones.  A previous version skipped the mesh for exactly that case
        # ("a load-free cable such as a short tie between two web junctions
        # should remain one solver edge"), on the reasoning that fewer free
        # nodes means a better-conditioned system.  For this solver that is
        # backwards, and it is the same finding _solve_reference_component()
        # is already built on (MANIFESTO.md sec 6): a single rigid 2-node edge
        # between free nodes is markedly harder for solve_analysis than the
        # identical rigid constraint spread over a few small sub-edges.
        #
        # Measured 2026-09-04 on four webs that differed ONLY in whether this
        # mesh was applied -- same geometry, lengths and loads:
        #   star, tie exactly taut     FAIL 3.374e-02 1.34s -> OK 4.298e-14 0.08s
        #   star, tie shorter than chord FAIL 1.944e-03 0.95s -> OK 9.257e-13 0.07s
        #   twin cables + taut tie     FAIL 4.417e-02 5.32s -> OK 3.502e-14 0.54s
        #   junction on a taut hanger  FAIL 2.194e-02 0.27s -> OK 3.601e-09 0.17s
        # 4/4 fixed, and 3-20x faster despite the extra unknowns.  The extra
        # free nodes cost far less than the conditioning they buy.
        # See REPORTS AND GUIDES/CABLE_WEB_DIAGNOSIS_2026-09-04.md.
        nseg = max(4, min(8, int(math.ceil(L / 2.5))))
        # A cable carrying a DISTRIBUTED load gets an EVEN segment count, so
        # a mesh node lands on the parametric midpoint -- which is where a
        # symmetric span's sag vertex actually is.  With an odd count the two
        # lowest nodes straddle the vertex at equal height, and the true low
        # point between them is below both: no interpolation through those
        # nodes can recover it, so the drawn funicular (and the mirrored
        # antifunicular) has a genuinely flat shelf where the curve should be
        # roundest.
        #
        # Measured 2026-09-05 by comparing the DRAWN curve's flat run against
        # the mathematically exact catenary's own flat run at the same screen
        # scale -- the necessary control, because a real catenary IS flat at
        # its vertex, so "looks flat" is not by itself a defect.  Across a
        # 28-case sweep every plateau had an odd nseg and every even nseg was
        # faithful:
        #     8 m span / 12.0 m cable (nseg=5): drawn 30.0% vs true 4.7% = 6.3x
        #     8 m span / 10.4 m cable (nseg=5): drawn 26.0% vs true 5.3% = 4.9x
        #    10 m span / 11.5 m cable (nseg=5): drawn 23.0% vs true 6.2% = 3.7x
        #    12 m span / 15.6 m cable (nseg=7): drawn 18.6% vs true 5.3% = 3.5x
        #   ...every even-nseg case: ratio 0.61-0.96, i.e. already correct.
        # After: 28/28 within 1.35x, worst 0.96x.
        #
        # This is MANIFESTO sec 3i's lesson again -- the cap is not the lever.
        # ceil(12.5/2.5) = 5 is already well under the cap of 8, so raising
        # the cap changes nothing; the PARITY is what matters.  Refining the
        # mesh generally is not an option either: measured on the same day,
        # div 2.5->1.25 takes the Picture Test's Analyze from 1.2 s to 42 s
        # and div 2.5->0.8 takes it to 240 s (sec 3k's cliff, still real).
        #
        # Restricted to cables with a distributed load on purpose.  Only those
        # have a sag vertex to miss: a point-loaded cable is straight between
        # its kinks, and an unloaded slack cable is drawn by the zero-tension
        # nominal-catenary substitution (sec 3h) with its own finer mesh.
        # Applying it to every cable instead cost the Picture Test 2 extra
        # edges and pushed its residual from 1.98e-10 (strict) to 2.42e-08
        # (inside the relaxed band) for no visual gain -- so it is scoped to
        # where it actually buys something.
        has_distributed = c['w'] > 0.0 or any(
            l['cable'] == cid and l['type'] in ('UDL', 'Variable')
            for l in (self.loads if include_user_loads else []))
        if has_distributed and nseg % 2:
            nseg += 1
        for k in range(1, nseg):
            pts.add(L * k / nseg)
        for n in self.nodes:
            for ac, s in n['attachments']:
                if ac == cid:
                    pts.add(max(0.0, min(L, s)))
        for l in (self.loads if include_user_loads else []):
            if l['cable'] != cid: continue
            pts.add(max(0.0, min(L, l['s1'])))
            pts.add(max(0.0, min(L, l['s2'])))
            # Variable loads need enough nodes to resolve q(s). Keep a modest
            # adaptive mesh so the UI remains responsive.
            if l['type'] == 'Variable':
                lo, hi = sorted((l['s1'], l['s2']))
                if hi > lo:
                    ndiv = max(4, min(20, int(math.ceil((hi-lo) / max(L/10.0, 1e-9)))))
                    for k in range(1, ndiv): pts.add(lo + (hi-lo)*k/ndiv)
        return sorted(pts)

    def _point_on_chord(self, cid, s):
        c = self._cable(cid); a, b = self._node(c['a']), self._node(c['b'])
        L = max(self._cable_length(cid), 1e-12)
        t = max(0.0, min(1.0, s / L))
        return a['x'] + t*(b['x']-a['x']), a['y'] + t*(b['y']-a['y'])

    def _build_solver_model(self, include_user_loads=True, reference_self_weight=False):
        model = CableWebModel()
        node_map = {}
        for n in self.nodes:
            x, y = self._world_to_m(n['x'], n['y'])
            node_map[n['id']] = model.add_node(x, y, is_support=n['support'],
                                                fx=n['fx'], fy=n['fy'])

        point_node = {}
        seg_owner = {}
        cable_solver_nodes = {}
        cable_bp_used = {}

        for c in self.cables:
            cid = c['id']
            bp = self._solver_breakpoints(cid, include_user_loads=include_user_loads)
            Lgeom = max(self._cable_length(cid), 1e-12)
            existing = {0.0: node_map[c['a']], Lgeom: node_map[c['b']]}
            for n in self.nodes:
                for ac, ss in n['attachments']:
                    if ac == cid:
                        existing[round(ss, 10)] = node_map[n['id']]

            ids = []
            for ss in bp:
                key = round(ss, 10)
                if abs(ss) < 1e-9:
                    ids.append(node_map[c['a']])
                elif abs(ss-Lgeom) < 1e-9:
                    ids.append(node_map[c['b']])
                elif key in existing:
                    ids.append(existing[key])
                else:
                    xw, yw = self._point_on_chord(cid, ss)
                    xm, ym = self._world_to_m(xw, yw)
                    nid = model.add_node(xm, ym, is_support=False)
                    point_node[(cid, key)] = nid
                    ids.append(nid)
            cable_solver_nodes[cid] = ids
            cable_bp_used[cid] = list(bp)

            target_total = c['length_override'] if c['length_override'] is not None else Lgeom
            # Since s is measured along the user cable's reference chord,
            # distribute a prescribed total material length proportionally.
            for k in range(len(bp)-1):
                s0, s1 = bp[k], bp[k+1]
                frac = (s1-s0) / max(Lgeom, 1e-12)
                target = target_total * frac
                mid = 0.5*(s0+s1)
                w = max(0.0, c['w'])
                if reference_self_weight and w <= 0.0:
                    ni, nj = model.nodes[ids[k]], model.nodes[ids[k+1]]
                    chord = math.hypot(nj.x - ni.x, nj.y - ni.y)
                    if target > chord + 1e-9:
                        w = 1.0  # only slack cables need a reference catenary; straight ties stay straight
                # User-applied UDLs are converted to equivalent nodal loads
                # below. Keep weight_per_length exclusively for actual cable
                # self-weight so a local UDL cannot create artificial jumps in
                # edge properties at its boundaries.
                eid = model.add_edge(ids[k], ids[k+1], target_length=target,
                                     weight_per_length=w)
                seg_owner[eid] = (cid, s0, s1)

        # Add concentrated and variable/non-vertical distributed loads as
        # equivalent nodal loads. Point loads at a breakpoint are exact.
        for l in (self.loads if include_user_loads else []):
            cid = l['cable']
            L = max(self._cable_length(cid), 1e-12)
            if l['type'] == 'Point':
                s = max(0.0, min(L, l['s1']))
                key = round(s, 10)
                nid = self._solver_node_at(model, cid, key, point_node, node_map)
                fx, fy = self._load_vector(l, cid, s, l['magnitude'])
                model.nodes[nid].fx += fx
                model.nodes[nid].fy += fy
            elif l['type'] == 'UDL':
                lo, hi = sorted((l['s1'], l['s2']))
                if hi <= lo:
                    continue
                bp = self._solver_breakpoints(cid, include_user_loads=True)
                for s0, s1 in zip(bp, bp[1:]):
                    a0, a1 = max(s0, lo), min(s1, hi)
                    if a1 <= a0:
                        continue
                    total = l['magnitude'] * (a1-a0)
                    # Consistent with the existing lumped-load convention:
                    # distribute each subinterval's resultant equally to its endpoints.
                    for ss, share in ((a0, 0.5), (a1, 0.5)):
                        key = round(ss, 10)
                        nid = self._solver_node_at(model, cid, key, point_node, node_map)
                        fx, fy = self._load_vector(l, cid, ss, total*share)
                        model.nodes[nid].fx += fx
                        model.nodes[nid].fy += fy
            elif l['type'] == 'Variable':
                lo, hi = sorted((l['s1'], l['s2']))
                if hi <= lo:
                    continue
                bp = self._solver_breakpoints(cid, include_user_loads=True)
                for s0, s1 in zip(bp, bp[1:]):
                    mid = 0.5*(s0+s1)
                    if mid < lo or mid > hi:
                        continue
                    q0 = self._safe_expr(l['expression'], s0, L)
                    q1 = self._safe_expr(l['expression'], s1, L)
                    total = 0.5*(q0+q1)*(s1-s0)
                    for ss, share in ((s0, 0.5), (s1, 0.5)):
                        key = round(ss, 10)
                        nid = self._solver_node_at(model, cid, key, point_node, node_map)
                        fx, fy = self._load_vector(l, cid, ss, total*share)
                        model.nodes[nid].fx += fx
                        model.nodes[nid].fy += fy

        self._solver_meta = {
            'node_map': node_map,
            'cable_solver_nodes': cable_solver_nodes,
            'seg_owner': seg_owner,
            # The s values this model was built on, so the grading pass can
            # re-place them without re-deriving (and without accidentally
            # re-deriving the GRADED set it is trying to replace).
            'cable_bp': cable_bp_used,
        }
        return model, seg_owner

    def _solver_node_at(self, model, cid, key, point_node, node_map):
        L = max(self._cable_length(cid), 1e-12)
        c = self._cable(cid)
        if abs(key) < 1e-8:
            return node_map[c['a']]
        if abs(key-L) < 1e-8:
            return node_map[c['b']]
        if (cid, key) in point_node:
            return point_node[(cid, key)]
        for n in self.nodes:
            for ac, s in n['attachments']:
                if ac == cid and abs(s-key) < 1e-7:
                    return node_map[n['id']]
        xw, yw = self._point_on_chord(cid, key)
        xm, ym = self._world_to_m(xw, yw)
        nid = model.add_node(xm, ym, is_support=False)
        point_node[(cid, key)] = nid
        return nid

    def _load_vector(self, load, cid, s, magnitude):
        a, b = self._node(self._cable(cid)['a']), self._node(self._cable(cid)['b'])
        vx, vy = b['x']-a['x'], b['y']-a['y']
        d = load['direction']
        if d == 'Vertical': return (0.0, -magnitude)
        if d == 'Horizontal': return (magnitude, 0.0)
        ux, uy = unit(vx, vy)
        if d == 'Tangential': return (magnitude*ux, -magnitude*uy)  # screen y -> math y
        if d == 'Normal': return (magnitude*uy, magnitude*ux)
        angle=math.radians(float(load.get('angle_deg', -90.0)))
        return (magnitude*math.cos(angle), magnitude*math.sin(angle))

    def _solve_nominal_catenary(self, x0, y0, x1, y1, target_length):
        """Solve a small, throwaway hanging-chain model with a nominal unit
        self-weight between two FIXED points, for a given total (slack)
        target_length. Used by BOTH the unloaded/ghost reference catenary
        (_update_reference_result) and the real-solve display substitution
        for a genuinely zero-tension stretch (_draw_solver_result) --
        those are the same sub-problem (a member with no true load has no
        unique shape of its own; see MANIFESTO.md sec 3h, and a nominal
        self-weight is the only way to give it a definite, physically
        sensible droop), so they share this ONE implementation rather than
        duplicating it, per the project's own stated goal of not needing
        the same fix applied twice in two places.

        Returns a list of (x, y) points from end to end (all in the
        caller's own coordinate system -- purely geometric, no unit
        conversion here), or a straight 2-point line if there's no slack,
        or None if the mini-solve fails to converge (caller should fall
        back to whatever it already had).

        nseg is chosen densely enough to avoid an under-resolved "flat
        plateau" near the true minimum -- diagnosed 2026-08-20: the old
        formula (ceil(target/2.5), capped at 8-10) gave only 5 segments
        for an 11-unit target, which put the curve's true smooth minimum
        BETWEEN two mesh points, displaying as a false flat shelf instead
        of a single smooth low point. Verified: 11 segments already give
        a proper single minimum for that case. Capped at 14 regardless of
        how large target grows, to stay safely below a measured, steep
        solve-time cliff (0.4s at 11 segments vs 11.7s at 20, for a
        comparable case) -- this is a display nicety, not worth risking
        a multi-second stall over.
        """
        built = self._build_nominal_catenary(x0, y0, x1, y1, target_length)
        if built['model'] is None:
            return built['straight']
        res = solve_analysis(built['model'])
        if not res.converged:
            return None
        return [res.positions[nid] for nid in built['chain']]

    @staticmethod
    def _build_nominal_catenary(x0, y0, x1, y1, target_length):
        """Model-building half of _solve_nominal_catenary, split out so the
        at-rest preview can build on the Tk main thread and solve on a
        worker (see _update_reference_result).

        Returns {'model': CableWebModel|None, 'chain': [node ids],
                 'straight': [(x0,y0), (x1,y1)]}. `model` is None when there
        is no slack -- that case has a closed-form answer (the chord) and
        needs no solve at all.

        Deliberately a @staticmethod touching nothing on self: whatever it
        returns is handed to a background thread, and a helper that cannot
        reach self cannot accidentally read live app state from there.
        """
        chord = math.hypot(x1 - x0, y1 - y0)
        straight = [(x0, y0), (x1, y1)]
        if target_length <= chord + 1e-9:
            return {'model': None, 'chain': [], 'straight': straight}
        nseg = max(6, min(14, int(math.ceil(target_length / 1.0))))
        model = CableWebModel()
        nodes = []
        for k in range(nseg + 1):
            t = k / nseg
            nodes.append(model.add_node(x0 + t * (x1 - x0), y0 + t * (y1 - y0),
                                         is_support=(k in (0, nseg))))
        for k in range(nseg):
            model.add_edge(nodes[k], nodes[k + 1], target_length=target_length / nseg,
                            weight_per_length=1.0)
        return {'model': model, 'chain': nodes, 'straight': straight}

    def _cable_components(self):
        """Group cables into connected components joined by a shared
        non-support node -- either a cable's own endpoint, or a node
        attached to it partway along. A shared SUPPORT does not link two
        cables into one free-junction system (a support is fixed, so
        there is no positional coupling through it). Returns a list of
        sets of cable ids.
        """
        cable_ids = [c['id'] for c in self.cables]
        node_to_cables = {}
        for c in self.cables:
            for nid in (c['a'], c['b']):
                node_to_cables.setdefault(nid, set()).add(c['id'])
        for n in self.nodes:
            for ac, ss in n['attachments']:
                node_to_cables.setdefault(n['id'], set()).add(ac)

        parent = {cid: cid for cid in cable_ids}
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for nid, cids in node_to_cables.items():
            if self._node(nid)['support']:
                continue
            cids = list(cids)
            for i in range(1, len(cids)):
                union(cids[0], cids[i])

        groups = {}
        for cid in cable_ids:
            groups.setdefault(find(cid), set()).add(cid)
        return list(groups.values())

    def _solve_reference_component(self, cable_ids):
        """Build AND solve one component, synchronously. Kept as the
        single-call form for tests and any caller that genuinely wants to
        block; the UI itself now goes through _build_reference_component()
        plus _apply_reference_component() so the solve can run off the Tk
        main thread (see _update_reference_result).
        """
        job = self._build_reference_component(cable_ids)
        result = solve_analysis(job['model'])
        if not result.converged:
            raise ValueError('Reference component solve did not converge.')
        return self._apply_reference_component(job, result)

    def _build_reference_component(self, cable_ids):
        """Build a fine-discretized network model for one
        connected component, so every junction lands at its true
        equilibrium position instead of being clamped to
        _point_on_chord()'s straight-chord interpolation (the "junction
        kink" bug -- MANIFESTO.md sec 6). Fine discretization of any
        genuinely slack segment (not just free junctions) is what makes
        this converge at all: a single edge in solve_analysis's
        formulation can only ever be taut, never slack, so a slack
        segment needs several small sub-edges, exactly as
        _solve_nominal_catenary already does for one segment on its own
        (see sec 6, third Phase-2 attempt, for how this was found).

        Returns a plain job dict -- a standalone CableWebModel plus the
        bookkeeping _apply_reference_component() needs to map a result back
        onto user cables. Everything the apply step will need about a node
        (notably `is_support`) is captured HERE, on the main thread, so the
        apply step never has to re-read self.nodes -- which may have moved
        on by then.

        Raises on failure (the caller wraps the rebuild in one try/except,
        matching the existing best-effort contract: the at-rest preview must
        never block editing/analysis).
        """
        model = CableWebModel()
        node_map = {}
        involved = set()
        for cid in cable_ids:
            c = self._cable(cid)
            involved.add(c['a']); involved.add(c['b'])
        for n in self.nodes:
            for ac, ss in n['attachments']:
                if ac in cable_ids:
                    involved.add(n['id'])
        for nid in involved:
            n = self._node(nid)
            xm, ym = self._world_to_m(n['x'], n['y'])
            node_map[nid] = model.add_node(xm, ym, is_support=n['support'])

        cable_breakpoints = {}
        segment_chains = {}
        for cid in cable_ids:
            c = self._cable(cid)
            L = max(self._cable_length(cid), 1e-12)
            points = [(0.0, c['a']), (L, c['b'])]
            for n in self.nodes:
                for ac, ss in n['attachments']:
                    if ac == cid and 1e-9 < ss < L - 1e-9:
                        points.append((ss, n['id']))
            points.sort(key=lambda p: p[0])
            clean = []
            for p in points:
                if not clean or abs(p[0] - clean[-1][0]) > 1e-8:
                    clean.append(p)
            cable_breakpoints[cid] = clean
            for seg_i, ((s0, nid0), (s1, nid1)) in enumerate(zip(clean, clean[1:])):
                target = s1 - s0
                m0, m1 = model.nodes[node_map[nid0]], model.nodes[node_map[nid1]]
                chord = math.hypot(m1.x - m0.x, m1.y - m0.y)
                taut = target <= chord + 1e-9
                # Every segment is discretized into several sub-edges, even
                # a taut one -- found empirically, not assumed: a single
                # rigid 2-node edge between two FREE junctions repeatedly
                # failed to converge on this project's own real topologies
                # (residual stuck ~0.02-0.06 on the Picture Test, or a slow
                # scipy least_squares fallback taking 30s+ on the Example)
                # even though the exact same rigid constraint, split into
                # the same number of small sub-edges the slack-segment
                # formula already gives (nseg below), converges cleanly and
                # fast. A smaller fixed count (tried: 3) converges the
                # Picture Test fine but was markedly SLOWER on the Example
                # (33s vs 7s) -- worse conditioning, not fewer unknowns,
                # dominates here, so one nseg formula is used for every
                # segment rather than trying to special-case taut ones
                # smaller. See MANIFESTO.md sec 6.
                w = 0.0 if taut else 1.0
                nseg = max(6, min(14, int(math.ceil(target / 1.0))))
                chain = [node_map[nid0]]
                prev = node_map[nid0]
                for k in range(1, nseg):
                    t = k / nseg
                    # Slight downward nudge off the straight seed line for
                    # slack segments only -- a perfectly collinear
                    # multi-junction seed was found to stall the solver on
                    # an unrelated attempt at this same problem (sec 6);
                    # costs nothing here. Not needed for the (already
                    # straight) taut case.
                    nx = m0.x + t * (m1.x - m0.x)
                    ny = m0.y + t * (m1.y - m0.y)
                    if not taut:
                        ny -= 0.05 * math.sin(math.pi * t)
                    newid = model.add_node(nx, ny, is_support=False)
                    model.add_edge(prev, newid, target_length=target / nseg,
                                    weight_per_length=w)
                    chain.append(newid)
                    prev = newid
                model.add_edge(prev, node_map[nid1], target_length=target / nseg,
                                weight_per_length=w)
                chain.append(node_map[nid1])
                segment_chains[(cid, seg_i)] = (chain, taut)

        return {
            'kind': 'component',
            'model': model,
            'cable_ids': list(cable_ids),
            'node_map': node_map,
            'cable_breakpoints': cable_breakpoints,
            'segment_chains': segment_chains,
            # Captured now, not looked up at apply time -- see the docstring.
            'free_nodes': [nid for nid in involved if not self._node(nid)['support']],
        }

    def _apply_reference_component(self, job, result):
        """Map a solved component back onto user cables. Main thread only
        (it produces world-pixel coordinates for _draw), but it reads only
        `job` and `result`, never self.nodes -- see _build_reference_component.
        """
        cable_breakpoints = job['cable_breakpoints']
        segment_chains = job['segment_chains']
        segments_by_cable = {}
        for cid in job['cable_ids']:
            clean = cable_breakpoints[cid]
            segs = []
            for seg_i in range(len(clean) - 1):
                chain, taut = segment_chains[(cid, seg_i)]
                pts = [self._m_to_world(*result.positions[mnid]) for mnid in chain]
                segs.append({'points': pts, 'taut': taut})
            segments_by_cable[cid] = segs

        junction_world_pos = {}
        for nid in job['free_nodes']:
            junction_world_pos[nid] = self._m_to_world(
                *result.positions[job['node_map'][nid]])

        return segments_by_cable, junction_world_pos

    def _build_reference_single_cable(self, cid):
        """Build half of the original single-cable reference solve -- kept
        for the trivial case it remains exactly correct for (Phase 2
        requirement 4): one cable directly between two supports, no interior
        junction at all.
        """
        c = self._cable(cid)
        L = max(self._cable_length(cid), 1e-12)
        a = self._node(c['a']); b = self._node(c['b'])
        x0, y0 = a['x'], a['y']; x1, y1 = b['x'], b['y']
        xm0, ym0 = self._world_to_m(x0, y0)
        xm1, ym1 = self._world_to_m(x1, y1)
        built = self._build_nominal_catenary(xm0, ym0, xm1, ym1, L)
        return {
            'kind': 'single',
            'cid': cid,
            'model': built['model'],       # None when the cable has no slack
            'chain': built['chain'],
            'world_endpoints': ((x0, y0), (x1, y1)),
        }

    def _apply_reference_single_cable(self, job, result):
        """Map a solved (or trivially straight) single cable back onto
        self._reference_paths / self._reference_segments. Main thread only.
        """
        cid = job['cid']
        (x0, y0), (x1, y1) = job['world_endpoints']
        if result is None:
            # No slack: the shape IS the chord. Flagged taut so _draw()
            # renders it in WARNING colour + dashed (MANIFESTO.md sec 3q).
            path = [(x0, y0), (x1, y1)]
            taut = True
        else:
            mini_pts = [result.positions[nid] for nid in job['chain']]
            path = [(xm * PX_PER_M, -ym * PX_PER_M) for xm, ym in mini_pts]
            taut = False
        self._reference_paths[cid] = path
        self._reference_segments[cid] = [{'points': list(path), 'taut': taut}]

    def _update_reference_single_cable(self, cid):
        """Synchronous build+solve+apply for one trivial cable. Retained as
        the single-call form for tests and any caller that wants to block;
        the UI goes through the build/apply pair above so the solve can run
        off the Tk main thread.
        """
        job = self._build_reference_single_cable(cid)
        result = None
        if job['model'] is not None:
            result = solve_analysis(job['model'])
            if not result.converged:
                raise ValueError(f'Reference catenary for C{cid} did not converge.')
        self._apply_reference_single_cable(job, result)

    def _on_reference_mode_changed(self):
        # Straight mode never solves (see _update_reference_result), so its
        # caches may be stale/empty from the last time Catenary was active.
        # Switching mode should show correct data immediately, not only
        # after the next edit -- refresh explicitly rather than waiting.
        self._update_reference_result()
        self._draw()

    def _update_reference_result(self):
        """Build the unloaded/self-weight-only reference geometry.

        This intentionally follows the existing Cable app convention: remove
        user-applied loads and compute each cable's natural self-weight
        catenary from its own span, material length and fixed endpoints.
        This is the PRIMARY at-rest rendering (see _draw()'s at-rest
        branch), so it also records, per segment, whether that segment
        came back straight because the cable has no slack at its current
        material length -- self._reference_segments -- so _draw() can flag
        that case visually instead of drawing it identically to a genuine
        sag.

        A cable (or group of cables) with an interior junction is solved
        as one connected-component network with every junction FREE (see
        _build_reference_component) instead of the junction being clamped
        to _point_on_chord()'s straight-chord position -- fixed 2026-08-30,
        see MANIFESTO.md sec 6. A cable with no interior junction at all
        (both endpoints on supports, one segment) keeps the original
        direct per-cable solve unchanged (Phase 2 requirement 4) since a
        connected-component solve of exactly one segment is the same
        problem, just with more bookkeeping.

        THREADED since 2026-09-04. This method used to run those solves
        synchronously, on the Tk main thread, from every one of its ~11 call
        sites (new cable, drag release, dialog Apply, delete, undo, redo,
        both example loaders, the mode toggle...). Measured: building a
        3-cable web cost 90.33 s of completely dead UI -- during a 48.9 s
        rebuild the event loop serviced exactly ONE already-queued after()
        callback, i.e. Windows greys the window out as Not Responding.
        Phase 5 threaded the Analyze button and left this one, which is both
        more expensive and far more frequent, untouched.

        It now only BUILDS the per-component models here (fast, main-thread,
        reads self.nodes/self.cables) and hands them to a worker thread,
        exactly as _solve_exact/_poll_solve_queue already do. Results come
        back over a queue.Queue and are applied by _poll_reference_queue on
        the main thread. Every request carries a token; a result whose token
        is no longer current is discarded rather than drawn onto a model
        that has changed underneath it.
        """
        self._reference_result = None
        self._reference_meta = None
        self._reference_paths = {}
        self._reference_segments = {}
        self._reference_junction_positions = {}
        # Any request invalidates whatever is in flight.
        self._reference_token += 1
        self._reference_request = None
        if self.reference_mode.get() == 'straight':
            # Straight (as-drawn) never needs a solve at all -- _draw()'s
            # at-rest branch renders straight from _cable_polyline() when
            # this mode is active, regardless of these caches. Skipping the
            # solve here (not just skipping the draw) is what makes
            # Straight mode "a free, instant fallback" (Phase 3 requirement
            # 6) rather than paying the Catenary preview solve cost on
            # every edit and just not showing the result.
            self._set_reference_status('')
            return
        try:
            jobs = self._build_reference_jobs()
        except Exception:
            # Building is pure bookkeeping and should not fail, but the
            # at-rest shape is best-effort and must never prevent editing.
            jobs = []
        if not jobs:
            self._set_reference_status('')
            return
        self._reference_request = (self._reference_token, jobs)
        self._start_reference_worker()

    def _build_reference_jobs(self):
        """Main-thread half: one standalone job per connected component."""
        jobs = []
        for cable_ids in self._cable_components():
            trivial = False
            if len(cable_ids) == 1:
                cid = next(iter(cable_ids))
                c = self._cable(cid)
                a, b = self._node(c['a']), self._node(c['b'])
                L = max(self._cable_length(cid), 1e-12)
                has_interior = any(
                    ac == cid and 1e-9 < ss < L - 1e-9
                    for n in self.nodes for ac, ss in n['attachments']
                )
                trivial = a['support'] and b['support'] and not has_interior
            if trivial:
                jobs.append(self._build_reference_single_cable(next(iter(cable_ids))))
            else:
                jobs.append(self._build_reference_component(cable_ids))
        return jobs

    def _start_reference_worker(self):
        """Start the background solve for the newest pending request.

        Only ever one worker at a time. A request arriving mid-solve does
        not start a second thread -- it just bumps the token, and
        _poll_reference_queue restarts the worker for the newest request
        once the stale one lands. That coalesces a burst of edits into one
        final solve instead of a queue of solves nobody is waiting for.
        """
        if self._reference_busy or self._reference_request is None:
            return
        if self._solving:
            # An Analyze the user explicitly asked for is already running.
            # Both are CPU-bound Python, so running them together does not
            # halve the wall time -- they contend for the GIL and each gets
            # slower (measured: Analyze 1.6 s alone versus 20.9 s alongside
            # a preview solve). The preview is a background nicety; let the
            # requested analysis have the machine and start this when
            # _poll_solve_queue finishes.
            return
        token, jobs = self._reference_request
        self._reference_busy = True
        self._set_reference_status('Computing at-rest catenary shapes in the background…')

        # Bind the queue as a local rather than reaching through `self` from
        # the worker, so the thread holds no reference to the widget at all.
        # A daemon thread that outlives root.destroy() and happens to hold
        # the last reference to the app will run tkinter.Variable.__del__ off
        # the main thread during GC, which raises "main thread is not in main
        # loop". Capturing only plain data makes that structurally impossible.
        result_queue = self._reference_queue

        def worker():
            # Off the Tk main thread: touches only `jobs`, whose models are
            # standalone CableWebModels built above -- never self.nodes,
            # self.cables or any widget.
            out, err = [], None
            try:
                for job in jobs:
                    if job['model'] is None:
                        out.append(None)        # no slack: chord, no solve
                        continue
                    res = solve_analysis(job['model'])
                    out.append(res if res.converged else False)
            except Exception as ex:
                err = ex
            result_queue.put((token, out, err))

        threading.Thread(target=worker, daemon=True).start()
        self.after(80, self._poll_reference_queue)

    def _poll_reference_queue(self):
        try:
            token, results, err = self._reference_queue.get_nowait()
        except queue.Empty:
            self.after(80, self._poll_reference_queue)
            return
        self._reference_busy = False

        if token != self._reference_token or self._reference_request is None:
            # The model changed while this was solving. Throw the answer
            # away rather than draw it, and solve the current question.
            self._start_reference_worker()
            return
        jobs = self._reference_request[1]
        self._reference_request = None

        if err is not None:
            # A missing solver package is an environment problem, not a
            # property of this web -- say which one it is instead of
            # silently drawing straight lines (the old blanket except
            # cleared the caches and reported nothing at all).
            if isinstance(err, MissingSolverDependency):
                self._set_reference_status(
                    'At-rest catenary preview needs SciPy - showing straight '
                    'chords. Install it with:  python -m pip install scipy')
            else:
                self._set_reference_status(
                    f'At-rest catenary preview unavailable ({err}) - showing '
                    'straight chords.')
            self._draw()
            return

        failed = []
        for job, result in zip(jobs, results):
            if result is False:
                # Did not converge. Per-component, so one awkward component
                # no longer silently wipes the preview for the whole web,
                # which the old single try/except around the entire rebuild
                # did.
                failed.append(job)
                continue
            try:
                if job['kind'] == 'single':
                    self._apply_reference_single_cable(job, result)
                else:
                    segs_by_cable, junction_pos = self._apply_reference_component(
                        job, result)
                    for cid, segs in segs_by_cable.items():
                        path = []
                        for seg in segs:
                            pts = list(seg['points'])
                            if path and pts:
                                pts = pts[1:]
                            path.extend(pts)
                        if len(path) >= 2:
                            self._reference_paths[cid] = path
                            self._reference_segments[cid] = segs
                    self._reference_junction_positions.update(junction_pos)
            except Exception:
                failed.append(job)

        if failed:
            names = sorted({f"C{cid}"
                            for job in failed
                            for cid in ([job['cid']] if job['kind'] == 'single'
                                        else job['cable_ids'])})
            self._set_reference_status(
                'At-rest catenary preview did not converge for '
                + ', '.join(names) + ' - showing straight chords there.')
        else:
            self._set_reference_status('At-rest catenary shapes updated.',
                                       only_if_ours=True)
        self._draw()

    def _set_reference_status(self, text, only_if_ours=False):
        """Report on the background at-rest preview without stealing the
        status line from whatever the user's own last action said.

        `only_if_ours` writes the message ONLY if the line still shows the
        text this method last wrote -- used for the quiet success case, so
        "At-rest catenary shapes updated." replaces our own "Computing..."
        note and never replaces e.g. "Analysis converged (residual 7e-09)".
        A genuine problem is always reported.
        """
        if not text:
            self._reference_status = ''
            return
        if only_if_ours and self.status_var.get() != self._reference_status:
            self._reference_status = ''
            return
        self._reference_status = text
        self.status_var.set(text)

    def _wait_for_reference_result(self, timeout=600.0):
        """Pump the event loop until the background at-rest preview settles.

        For tests and for any caller that genuinely needs the finished
        shapes rather than the live-updating UI behaviour. Returns True if
        it settled, False on timeout. Never call this from the worker.
        """
        import time as _time
        deadline = _time.perf_counter() + timeout
        while (self._reference_busy or self._reference_request is not None):
            if _time.perf_counter() > deadline:
                return False
            self.update()
            # 20 ms, not 5: the result is picked up by an after(80, ...)
            # poller, so spinning faster buys nothing, and every wake-up
            # here is a GIL handoff taken away from the worker actually
            # doing the solve. Measured: a tighter spin slowed the very
            # solve it was waiting for.
            _time.sleep(0.02)
        self.update()
        return True

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------
    def _validate_model(self):
        errors, warnings = [], []
        if not self.nodes: errors.append('No structural nodes.')
        if not self.cables: errors.append('No cables.')
        supports = [n for n in self.nodes if n['support']]
        if not supports: errors.append('No supports.')
        for c in self.cables:
            try:
                L = self._cable_length(c['id'])
                if L <= 1e-9: errors.append(f'C{c["id"]} has zero length.')
                if c['length_override'] is not None and c['length_override'] <= 0:
                    errors.append(f'C{c["id"]} has non-positive prescribed length.')
                # A cable prescribed SHORTER than the straight distance
                # between its own endpoints cannot reach. Previously this
                # passed validation silently as "structurally ready"; a
                # measured case then ground for 228 s and reported a
                # "converged" 313 kN tension under 372 N of applied load.
                # Between two fixed supports it is simply insoluble; with a
                # free endpoint it is solvable but only by dragging the
                # junctions together under enormous force, which the user
                # should be told about before waiting for it.
                a, b = self._node(c['a']), self._node(c['b'])
                chord = self._straight_distance(a, b)
                if c['length_override'] is not None and c['length_override'] < chord - 1e-9:
                    detail = (f'C{c["id"]} is prescribed {c["length_override"]:.3f} m '
                              f'but its endpoints are {chord:.3f} m apart')
                    if a['support'] and b['support']:
                        errors.append(detail + ' — it cannot reach between two '
                                               'fixed supports.')
                    else:
                        warnings.append(detail + ' — its junctions will be pulled '
                                                 'together under very high tension.')
            except Exception as ex:
                errors.append(f'C{c["id"]}: {ex}')
        for l in self.loads:
            L = self._cable_length(l['cable'])
            if not (0 <= l['s1'] <= L + 1e-8): warnings.append(f"{l['id']} starts outside C{l['cable']}.")
            if l['type'] != 'Point' and not (0 <= l['s2'] <= L + 1e-8): warnings.append(f"{l['id']} ends outside C{l['cable']}.")
            if l['type'] == 'Variable' and not l.get('expression'):
                errors.append(f"{l['id']} has no q(s) expression.")
        if errors:
            msg = 'Errors:\n• ' + '\n• '.join(errors)
            self.validation_var.set(msg)
            self.status_var.set('Validation failed.')
            return False
        msg = '✓ Model is structurally ready.'
        if warnings: msg += '\n⚠ ' + '\n⚠ '.join(warnings)
        self.validation_var.set(msg)
        self.status_var.set('Validation complete.')
        return True

    def _on_curve_route_changed(self):
        """Route 1 and Route 2 are alternatives, not layers.

        The analytic curve is built from a stretch's endpoints and its arc
        length alone -- it never looks at where the interior solver nodes
        landed -- so grading the mesh underneath it would buy the picture
        nothing and cost a second solve. Selecting one route therefore turns
        the other off, which is also what makes "Analytic" the cheaper of the
        two rather than an extra layer on top.

        Route 1 is display-only and applies to the result already on screen;
        Route 2 changes what is solved, so it needs another Analyze.
        """
        analytic = self.curve_route.get() == 'analytic'
        self.grade_mesh.set(not analytic)
        self._draw()
        if self.result is None or self.result_kind != 'analysis':
            return
        if analytic:
            self.status_var.set(
                'Analytic curve (Route 1): each uniformly loaded stretch is '
                'drawn as the exact catenary through its own endpoints.')
        else:
            self.status_var.set(
                'Graded mesh (Route 2). Run Analyze again to apply it to the '
                'result on screen.')

    def _group_uniform_load(self, cid, s_lo, s_hi):
        """Downward load per unit ARC LENGTH on the stretch of cable `cid`
        between s_lo and s_hi, or None when that stretch does not carry one
        uniform, purely vertical load.

        This is a GATE, not an input: the closed form in
        _analytic_group_points needs no value of q at all, only the knowledge
        that q is uniform, because that is exactly the condition under which
        the shape is a catenary. Both of this app's distributed loads are per
        unit arc length -- self-weight rides on each edge as
        `weight_per_length`, and a UDL is lumped as `magnitude * (a1 - a0)`
        with a0/a1 measured in s -- so either one alone, or both together,
        leaves the stretch uniformly loaded.

        Anything else has some other shape, and returning None (so the caller
        falls back to the solved polygon) is the only honest answer: drawing a
        confident catenary through a stretch that is not one would be drawing
        the wrong curve, which is worse than drawing a visibly faceted right
        one.
        """
        tol = 1e-7
        q = max(0.0, float(self._cable(cid).get('w') or 0.0))
        for l in self.loads:
            if l['cable'] != cid:
                continue
            typ = l.get('type')
            if typ == 'Point':
                # Groups are split at point loads, so one should only ever sit
                # on an end. If a stray one lands strictly inside, the stretch
                # has a real kink in it and is not a single catenary.
                if s_lo + tol < float(l['s1']) < s_hi - tol:
                    return None
                continue
            lo, hi = sorted((float(l['s1']), float(l['s2'])))
            if hi <= s_lo + tol or lo >= s_hi - tol:
                continue                      # does not touch this stretch
            if typ != 'UDL':
                return None                   # Variable: not uniform, by definition
            if lo > s_lo + tol or hi < s_hi - tol:
                return None                   # covers only part of the stretch
            if l.get('direction') != 'Vertical':
                return None                   # closed form assumes gravity-aligned
            mag = float(l.get('magnitude') or 0.0)
            if mag < 0.0:
                return None                   # net-upward load arches; not covered
            q += mag
        return q if q > 1e-12 else None

    @staticmethod
    def _catenary_chord(a, horiz):
        """2a*sinh(horiz/2a), guarded against the overflow small `a` causes."""
        z = horiz / (2.0 * a)
        if z > 350.0:
            return float('inf')
        return 2.0 * a * math.sinh(z)

    @classmethod
    def _catenary_a_from_chord(cls, horiz, c):
        """Solve 2a*sinh(horiz/2a) = c for the catenary parameter a.

        The classic two-point relation, with c = sqrt(arc^2 - dy^2). The left
        side falls monotonically from +inf towards `horiz` as a grows, so a
        root exists exactly when c > horiz -- that is, when the stretch has
        slack -- and bisection needs no derivative and cannot pick the wrong
        branch.
        """
        if horiz <= 1e-12 or c <= horiz:
            return None
        lo, hi = max(horiz, c) * 1e-9, max(horiz, c)
        for _ in range(200):
            if cls._catenary_chord(hi, horiz) <= c:
                break
            hi *= 2.0
        else:
            return None
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if cls._catenary_chord(mid, horiz) > c:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    @classmethod
    def _analytic_group_points(cls, pts, arc_len, samples=120):
        """Route 1: the exact catenary through this stretch's endpoints.

        A stretch of cable under a uniform load per unit arc length hangs in
        a catenary. That curve is fixed by three things -- the two endpoint
        positions and the arc length between them -- and this app knows all
        three exactly: the endpoints are supports, junctions or point-load
        nodes (the trustworthy points of any solved group, see the
        zero-tension note in _draw_solver_result), and the arc length is a
        model INPUT, not a solved quantity.

        So nothing here reads a solved tension or thrust, and nothing here
        inherits their discretisation error. That is the whole advantage over
        refining or re-meshing: the mesh decides how well the SOLVER
        approximates this curve, but the curve itself is already known.

        Returns points in the caller's own coordinate space (y upward, as the
        solver uses), a straight two-point line when the stretch is taut, or
        None when the closed form does not apply -- notably a near-vertical
        slack stretch, whose real shape doubles back on itself and is not a
        function of x at all.
        """
        if len(pts) < 2 or arc_len <= 1e-12:
            return None
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        dx, dy = x1 - x0, y1 - y0
        horiz = abs(dx)
        if abs(dy) >= arc_len * (1.0 - 1e-12):
            return None                       # no arc left over for any sag
        c = math.sqrt(max(arc_len * arc_len - dy * dy, 0.0))
        if c <= horiz * (1.0 + 1e-9):
            return [pts[0], pts[-1]]          # taut: the chord IS the exact shape
        a = cls._catenary_a_from_chord(horiz, c)
        if a is None or not math.isfinite(a) or a <= 0.0:
            return None

        # Arc-length position of the first endpoint, measured from the curve's
        # own vertex. Bisected rather than solved in closed form: the rise
        # over a fixed arc is strictly increasing in it, so bisection is
        # unambiguous, and this sqrt form never overflows the way cosh does.
        def rise(sa):
            return (math.sqrt(a * a + (sa + arc_len) ** 2)
                    - math.sqrt(a * a + sa * sa))

        span = 4.0 * (a + arc_len + horiz) + 1.0
        for _ in range(60):
            if rise(-span) <= dy <= rise(span):
                break
            span *= 4.0
        else:
            return None
        lo, hi = -span, span
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if rise(mid) < dy:
                lo = mid
            else:
                hi = mid
        sa = 0.5 * (lo + hi)

        # Sample at equal increments of TURN, not of arc length -- Route 2's
        # own insight applied to the exact curve. A catenary's tangent angle
        # is atan(s/a), so this is closed form, and it puts the facets where
        # the curve actually bends instead of spreading them evenly over a
        # length that is nearly straight at both ends. The count then follows
        # from the total turn at a fixed angle per facet, so a gently curved
        # stretch costs few points and a sharply curved one gets what it
        # needs, rather than both getting the same arbitrary number.
        th0 = math.atan(sa / a)
        th1 = math.atan((sa + arc_len) / a)
        turn_deg = abs(math.degrees(th1 - th0))
        n = int(max(24, min(samples, math.ceil(turn_deg / 2.0))))
        u0 = a * math.asinh(math.tan(th0))
        v0 = a / math.cos(th0)
        local = []
        for k in range(n + 1):
            th = th0 + (th1 - th0) * k / n
            local.append((a * math.asinh(math.tan(th)) - u0,
                          a / math.cos(th) - v0))

        # The sampled curve must land on its own far endpoint. It does by
        # construction when the two bisections agree, so a mismatch means this
        # stretch is not the catenary the gate believed it was -- fall back
        # rather than draw a curve that misses the anchor it was built from.
        tol = max(1e-7, 1e-5 * max(horiz, arc_len))
        if (abs(local[-1][0] - horiz) > tol
                or abs(local[-1][1] - dy) > tol):
            return None

        # Which way it bulges. The closed form always sags; the antifunicular
        # view is handed mirrored positions and must arch instead. Take the
        # direction from the SOLVED polyline being replaced rather than from
        # any knowledge of how the mirror is built, so both views come out
        # right for the same reason and neither can drift from the other.
        denom = dx * dx + dy * dy
        solved_off = 0.0
        for px, py in pts[1:-1]:
            t = (((px - x0) * dx + (py - y0) * dy) / denom) if denom > 1e-18 else 0.0
            solved_off += py - (y0 + t * dy)
        flip = solved_off > 0.0

        sgn = 1.0 if dx >= 0.0 else -1.0
        out = []
        for u, v in local:
            frac = (u / horiz) if horiz > 1e-12 else 0.0
            chord_v = dy * frac
            off = (chord_v - v) if flip else (v - chord_v)
            out.append((x0 + sgn * u, y0 + chord_v + off))
        return out

    def _pinned_breakpoints(self, cid):
        """s values that a re-mesh must not move: the cable's own ends, every
        junction attached to it, and every load boundary. Moving one of these
        would change the model, not just its discretisation."""
        L = max(self._cable_length(cid), 1e-12)
        out = {0.0, L}
        for n in self.nodes:
            for ac, ss in n['attachments']:
                if ac == cid:
                    out.add(max(0.0, min(L, ss)))
        for l in self.loads:
            if l['cable'] != cid:
                continue
            out.add(max(0.0, min(L, l['s1'])))
            out.add(max(0.0, min(L, l['s2'])))
        return sorted(out)

    @staticmethod
    def _s_at_measure(bp, M, target):
        """Invert the piecewise-linear cumulative measure M(s)."""
        if target <= M[0]:
            return bp[0]
        if target >= M[-1]:
            return bp[-1]
        for i in range(len(M) - 1):
            if M[i] <= target <= M[i + 1]:
                span = M[i + 1] - M[i]
                if span <= 1e-15:
                    return bp[i]
                t = (target - M[i]) / span
                return bp[i] + t * (bp[i + 1] - bp[i])
        return bp[-1]

    def _graded_breakpoints(self, cid, result, meta, blend=0.65):
        """Re-place a cable's FREE breakpoints so each element carries
        roughly equal direction change.

        Why: the mesh is uniform in arc length, but a loaded cable's
        curvature is concentrated at its vertex, so almost all of the turning
        lands in the one or two elements at the low point. Measured
        2026-09-05 on the built-in Example's C2, whose turn angles ran from
        5.12 to 62.94 degrees -- a ratio of 12.3. That single ~63 degree bend
        between two nearly-straight flanks is what reads as "polygonised".

        Uniform refinement is not the answer: it shrinks every corner but
        makes the distribution WORSE (measured ratio 10.4 at 8 elements
        rising to 18.4 at 48), and 48 elements on one cable costs 15.9 s.
        Total turning is a property of the shape (150.6 deg at 8 elements,
        153.6 at 48), so spreading it evenly over the SAME element count is
        the lever that actually exists.

        The measure blends arc length with turning rather than using turning
        alone -- pure equal-turning would allocate nothing at all to a
        straight run, and a straight run still needs its share of nodes for
        the length constraint. `blend` is the weight on turning, and 0.65 is
        measured, not guessed: swept over the five cases below, 0.90 beat
        0.75 on every one, while 0.98 starved the straight runs badly enough
        to make the Picture Test WORSE than no grading at all (120.31 ->
        130.31 deg).

        Measured 2026-09-05, largest turn at a FREE interior node (kinks at
        point loads and junctions are real and excluded), dof identical in
        every row:

            built-in Example        62.94 -> 33.10 deg   ratio 12.30 -> 3.2
            built-in Picture test  120.31 -> 95.66 deg
            plain UDL 10/20 m       57.09 -> 27.29 deg   ratio 10.43 -> 2.0
            self-weight 20/26 m     23.72 -> 15.59 deg   ratio  2.53 -> 1.2
            self-weight + junction  34.20 -> 27.28 deg

        Residuals stayed at or below their uniform-mesh values throughout;
        the Picture Test's actually improved, 1.98e-10 -> 5.29e-15.

        Pinned points (cable ends, junctions, load boundaries) never move,
        and the number of free points inside each pinned interval is
        preserved exactly, so the graded model has the SAME degrees of
        freedom as the uniform one. Returns None when grading is impossible
        or would change the count -- the caller then keeps the uniform mesh.
        """
        bp = (meta.get('cable_bp') or {}).get(cid)
        ids = (meta.get('cable_solver_nodes') or {}).get(cid)
        if not bp or not ids or len(bp) != len(ids) or len(bp) < 4:
            return None
        try:
            P = [result.positions[nid] for nid in ids]
        except KeyError:
            return None
        n = len(bp) - 1
        ang, ds = [], []
        for i in range(n):
            dx = P[i + 1][0] - P[i][0]
            dy = P[i + 1][1] - P[i][1]
            if math.hypot(dx, dy) < 1e-12:
                return None
            ang.append(math.atan2(dy, dx))
            ds.append(bp[i + 1] - bp[i])
        if min(ds) <= 0.0:
            return None
        node_turn = [0.0] * (n + 1)
        for i in range(1, n):
            t = ang[i] - ang[i - 1]
            while t > math.pi:
                t -= 2.0 * math.pi
            while t < -math.pi:
                t += 2.0 * math.pi
            node_turn[i] = abs(t)
        # Turning attributed to an element = half of each of its end nodes'.
        turn = [0.5 * (node_turn[i] + node_turn[i + 1]) for i in range(n)]
        tot_s, tot_t = sum(ds), sum(turn)
        if tot_s <= 0.0 or tot_t <= 1e-9:
            return None                      # already straight: nothing to grade
        m = [(1.0 - blend) * (ds[i] / tot_s) + blend * (turn[i] / tot_t)
             for i in range(n)]
        M = [0.0]
        for v in m:
            M.append(M[-1] + v)

        pinned = self._pinned_breakpoints(cid)
        pin_idx = [i for i, sv in enumerate(bp)
                   if any(abs(sv - q) < 1e-7 for q in pinned)]
        if not pin_idx or pin_idx[0] != 0:
            pin_idx.insert(0, 0)
        if pin_idx[-1] != n:
            pin_idx.append(n)

        out = [bp[0]]
        for a, b in zip(pin_idx, pin_idx[1:]):
            k = b - a - 1                    # free points strictly inside
            for j in range(1, k + 1):
                target = M[a] + (M[b] - M[a]) * j / (k + 1)
                out.append(self._s_at_measure(bp, M, target))
            out.append(bp[b])

        if len(out) != len(bp):
            return None

        # NOTE (measured 2026-09-05, do not re-attempt without new evidence):
        # grading pulls nodes toward the vertex, so the elements AT THE
        # SUPPORTS grow -- and that is where peak tension lives, so the
        # reported Tmax on the 20/22 m UDL cable moves from -4.71% to -6.76%
        # against a 64-edge reference. Two mitigations were built and swept,
        # and BOTH are strict trade-offs with no sweet spot: capping element
        # growth, and adding a tension-gradient term (turn*sec*tan) to the
        # measure. Each buys back accuracy only by giving up almost exactly
        # as much smoothing. See MANIFESTO sec 3x. The real fix is in the
        # REPORTING layer, not here: take the end tension from the support
        # reaction (T = hypot(H, V_reaction)), which is exact.
        for i in range(len(out) - 1):
            if out[i + 1] - out[i] < 1e-6:   # refuse a degenerate element
                return None
        return out

    def _apply_mesh_grading(self, result):
        """Build the graded mesh for every cable from a converged first pass.
        Returns True if anything changed."""
        meta = self._solver_meta
        if not meta:
            return False
        graded = {}
        for c in self.cables:
            g = self._graded_breakpoints(c['id'], result, meta)
            if g:
                graded[c['id']] = g
        if not graded:
            return False
        self._graded_bp = graded
        return True

    def _solve_fd(self):
        if not self._validate_model(): return
        if self._solving:
            # An Analyze solve is running in the background -- refuse to
            # start a second solve against the same model concurrently.
            return
        try:
            q = self.q_var.get()
            if q <= 0: raise ValueError('Force density q must be positive.')
            model, mapping = self._build_solver_model()
            result = solve_force_density(model, q)
            self.result = result
            self.result_kind = 'fd'; self.results_current = True
            self._result_serial += 1
            self._post_solve('Form-finding complete.')
        except Exception as ex:
            self._analysis_error('Form-finding failed', ex)

    def _solve_exact(self):
        if not self._validate_model(): return
        if self._solving:
            return
        # SciPy is required for any web with a junction (see _ensure_scipy's
        # own docstring for the measurement). Check it HERE, on an explicit
        # user action, rather than at import time: the check is free when it
        # is already installed, and when it is not, the pip install runs
        # against a visible status message instead of delaying app startup.
        if len(self.cables) > 1 and not _ensure_scipy():
            self._analysis_error(
                'Analysis failed',
                MissingSolverDependency(
                    'Cable Web needs SciPy to solve a network with junctions, '
                    'and it could not be installed automatically.\n\n'
                    'Install it yourself with:\n'
                    '    python -m pip install scipy'))
            return
        # This solve can legitimately take several seconds for a network
        # with indeterminate (degree>=3) junctions. It used to run
        # synchronously on the Tk main thread -- a busy cursor and status
        # message were set beforehand, but since nothing yielded back to
        # the event loop, neither ever actually got a chance to paint
        # until the (still blocking) call returned, and the whole UI was
        # frozen with zero feedback for the entire solve. Actually fixed
        # here by running solve_analysis() itself in a background thread;
        # this method only builds the (fast, main-thread-only) solver
        # model and starts the thread -- see _poll_solve_queue for where
        # the result comes back. This is UI plumbing only: the solver's
        # numerical behavior is completely untouched.
        try:
            model, mapping = self._build_solver_model()
        except Exception as ex:
            self._analysis_error('Analysis failed', ex)
            return

        self._solving = True
        self._solve_pass = 1
        self._graded_bp = {}          # pass 1 always runs on the uniform mesh
        self._solve_model_serial = self._model_serial
        self.analysis_buttons['Analyze'].config(state='disabled')
        self.analysis_buttons['Form-find'].config(state='disabled')
        self._solve_progress.pack(side='left', padx=(6, 2))
        self._solve_progress.start(12)
        self.status_var.set('Solving in the background -- exact analysis can take a while for '
                             'networks with indeterminate junctions (3+ cables meeting at one point).')
        self.update_idletasks()

        def worker():
            # Runs off the Tk main thread: touches only `model` (already
            # built above, a standalone CableWebModel, not self.nodes/
            # self.cables) and solve_analysis itself, which is pure
            # computation with no Tk/widget access -- never safe to do
            # from a background thread. The result crosses back via a
            # thread-safe queue.Queue, picked up by _poll_solve_queue on
            # the main thread rather than touched here directly.
            try:
                result = solve_analysis(model)
                result_queue.put(('ok', result))
            except Exception as ex:
                result_queue.put(('error', ex))

        # Bound as a local, not reached through `self` -- see the identical
        # note in _start_reference_worker: a daemon thread holding the last
        # reference to the widget runs tkinter.Variable.__del__ off the main
        # thread at GC time and raises "main thread is not in main loop".
        result_queue = self._solve_queue
        threading.Thread(target=worker, daemon=True).start()
        self.after(80, self._poll_solve_queue)

    def _poll_solve_queue(self):
        try:
            kind, payload = self._solve_queue.get_nowait()
        except queue.Empty:
            self.after(80, self._poll_solve_queue)
            return
        self._solving = False
        self.analysis_buttons['Analyze'].config(state='normal')
        self.analysis_buttons['Form-find'].config(state='normal')
        self._solve_progress.stop()
        self._solve_progress.pack_forget()
        stale = self._solve_model_serial != self._model_serial
        self._solve_model_serial = None
        # The machine is free again -- release any at-rest preview that was
        # held back while this analysis ran (see _start_reference_worker).
        self._start_reference_worker()
        if stale:
            # The model changed while this solve was running (a dialog, an
            # Undo, an example load -- none of which _solving blocks). The
            # answer is to a question nobody is asking any more; showing it
            # would attribute a result to the wrong structure.
            self.status_var.set('Model changed during the solve; result discarded. '
                                'Run Analyze again.')
            return
        if kind == 'error':
            self._analysis_error('Analysis failed', payload)
            return
        result = payload
        # Pass 1 converged and grading is on: re-place the free breakpoints
        # by curvature and solve once more on that mesh. Same dof, same
        # pinned points -- only the interior spacing changes. Done HERE, on
        # the main thread, because re-meshing reads self.nodes/self.cables,
        # which a worker must never touch.
        if (result.converged and self._solve_pass == 1
                and self.grade_mesh.get() and not stale):
            try:
                regraded = self._apply_mesh_grading(result)
            except Exception:
                regraded = False
            if regraded:
                try:
                    model2, _ = self._build_solver_model()
                except Exception:
                    model2 = None
                if model2 is not None:
                    self._pass1_result = result
                    self._solve_pass = 2
                    self._solving = True
                    self._solve_model_serial = self._model_serial
                    self.analysis_buttons['Analyze'].config(state='disabled')
                    self.analysis_buttons['Form-find'].config(state='disabled')
                    self._solve_progress.pack(side='left', padx=(6, 2))
                    self._solve_progress.start(12)
                    self.status_var.set('Refining the mesh where the cable turns '
                                        'fastest, then solving again...')
                    result_queue = self._solve_queue

                    def worker2():
                        try:
                            result_queue.put(('ok', solve_analysis(model2)))
                        except Exception as ex:
                            result_queue.put(('error', ex))

                    threading.Thread(target=worker2, daemon=True).start()
                    self.after(80, self._poll_solve_queue)
                    return
                self._graded_bp = {}
        if self._solve_pass == 2 and not result.converged:
            # The graded mesh did not converge. Fall back to the uniform
            # answer rather than reporting a failure the user cannot act on;
            # pass 1 is a genuine, converged result.
            self._graded_bp = {}
            fallback = getattr(self, '_pass1_result', None)
            self._pass1_result = None
            self._solve_pass = 0
            if fallback is not None:
                try:
                    self._build_solver_model()
                except Exception:
                    pass
                self.result = fallback
                self.result_kind = 'analysis'; self.results_current = True
                self._result_serial += 1
                self._post_solve(
                    'Analysis converged (residual %.2e). Mesh grading did not '
                    'converge; showing the uniform-mesh result.' % fallback.residual)
                return
        self._pass1_result = None
        self._solve_pass = 0
        if not result.converged:
            # Never expose a non-equilibrium Newton iterate as a valid
            # funicular. This was the source of the apparently wild red
            # geometries seen with failed analyses.
            self.result = None
            self.result_kind = None
            self.results_current = False
            self.validation_var.set(f'✕ Exact analysis did not converge (residual {result.residual:.2e}).')
            why = self._unreachable_junction_note()
            self.status_var.set(
                'Analysis did not converge (residual %.2e); invalid result '
                'hidden.%s' % (result.residual, (' ' + why) if why else ''))
            self._draw(); self._update_selected_inspector()
            return
        self.result = result
        self.result_kind = 'analysis'; self.results_current = True
        self._result_serial += 1
        note = self._implausible_result_note(result)
        if note:
            # The residual test is satisfied honestly, but a residual is a
            # statement about the EQUATIONS, not about the answer being a
            # sensible structure. A measured case (a tie prescribed shorter
            # than its own chord) passed at residual 7.15e-08 -- inside the
            # relaxed practical_tol band of CONVERGENCE_FIX_V11 -- while
            # reporting 313 kN under 372 N of load. Show the result, since
            # it does solve the stated problem, but say plainly that the
            # stated problem looks wrong.
            self.validation_var.set(
                f'⚠ Analysis converged (residual {result.residual:.2e}) but the '
                f'result is physically implausible:\n{note}')
            self._post_solve(f'Analysis converged, but check the model — {note}')
            return
        self._post_solve(f'Analysis converged (residual {self.result.residual:.2e}).')

    def _unreachable_junction_note(self):
        """Say when a failed solve failed because the model is IMPOSSIBLE.

        A junction cabled straight to several supports must lie within each
        cable's own length of its support -- it can hang slack, but it cannot
        stretch. So the junction has to sit in the intersection of those
        discs, and when that intersection is empty no configuration exists,
        for any solver.

        This is a necessary condition, not a sufficient one: it looks only at
        cables running directly from this junction to a support, so it never
        cries wolf about a web it has not fully accounted for. It exists
        because "did not converge" sends you looking for a numerical problem,
        and the answer here is that you asked for a shape that cannot be
        built. Found while closing the audit's F4: a three-cable star whose
        two suspension cables need the junction at y >= 0.86 while its 6 m tie
        needs y <= 0.

        The feasibility test minimises max_i(|p - S_i| - r_i) over p, which is
        convex, so a plain descent from the centroid reaches the true minimum.
        """
        worst = None
        for n in self.nodes:
            if n['support']:
                continue
            discs = []
            for c in self.cables:
                other = None
                if c['a'] == n['id']:
                    other = self._node(c['b'])
                elif c['b'] == n['id']:
                    other = self._node(c['a'])
                if other is None or not other['support']:
                    continue
                sx, sy = self._world_to_m(other['x'], other['y'])
                reach = c['length_override']
                if reach is None:
                    reach = self._cable_length(c['id'])
                discs.append((sx, sy, float(reach)))
            if len(discs) < 2:
                continue

            px = sum(d[0] for d in discs) / len(discs)
            py = sum(d[1] for d in discs) / len(discs)

            def worst_excess(x, y):
                return max(math.hypot(x - sx, y - sy) - r for sx, sy, r in discs)

            step = max(max(abs(d[0] - px) for d in discs),
                       max(abs(d[1] - py) for d in discs), 1.0)
            cur = worst_excess(px, py)
            for _ in range(200):
                improved = False
                for dx, dy in ((step, 0.0), (-step, 0.0), (0.0, step), (0.0, -step)):
                    cand = worst_excess(px + dx, py + dy)
                    if cand < cur - 1e-12:
                        px, py, cur = px + dx, py + dy, cand
                        improved = True
                        break
                if not improved:
                    step *= 0.5
                    if step < 1e-9:
                        break
            if cur > 1e-6 and (worst is None or cur > worst[0]):
                worst = (cur, n['id'])

        if worst is None:
            return ''
        return ('Junction %d cannot be reached: its cables are too short to '
                'meet anywhere, by %.3g m. This model has no solution at any '
                'tension -- lengthen a cable or move a support.'
                % (worst[1], worst[0]))

    @staticmethod
    def _implausible_result_note(result):
        """Sanity-check a converged result against the load that produced it.

        Returns a short description of the problem, or '' if the result
        looks reasonable.

        Where the threshold comes from: for a cable of span L carrying a
        total load W at sag f, T ~= W*L/(8f), so the tension-to-load ratio
        is set by the sag ratio alone -- ratio ~= L/(8f). A 1%-sag cable
        (already very shallow for a real structure) gives ~12; a 0.1%-sag
        cable gives ~125. RATIO_LIMIT = 200 therefore corresponds to a sag
        of about 1/1600 of the span, which no cable structure is. Measured
        headroom on this project's own cases: every legitimate web tested
        on 2026-09-04 came in below 1.0 (0.64-0.90), and the pathological
        one -- a tie prescribed 14 m between junctions 20 m apart -- came in
        at 842. Two and a half orders of magnitude of separation, so this
        gate is not a close call in either direction.
        """
        RATIO_LIMIT = 200.0
        tensions = [abs(v) for v in getattr(result, 'tensions', {}).values()
                    if v is not None and math.isfinite(v)]
        if not tensions:
            return ''
        tmax = max(tensions)
        applied = 0.0
        for n in result.model.nodes.values():
            applied += math.hypot(n.fx, n.fy)
        for e in result.model.edges.values():
            applied += abs(e.weight_per_length) * abs(e.target_length or 0.0)
        if applied <= 1e-9:
            return ''
        ratio = tmax / applied
        if ratio > RATIO_LIMIT:
            return (f'peak cable tension {tmax:,.0f} N is {ratio:,.0f}x the total '
                    f'applied load of {applied:,.1f} N. Check for a cable whose '
                    f'prescribed length is shorter than the distance it has to span.')
        return ''

    def _post_solve(self, text):
        self.status_var.set(text)
        self._draw(); self._update_selected_inspector()
        # Fresh tensions -> fresh diagrams.
        self._sync_diagram_pane()
        self._sync_funicular_pane()

    def _analysis_error(self, title, ex):
        self.result = None; self.results_current = False
        self.validation_var.set(f'✕ {title}:\n{ex}')
        self.status_var.set(title + '.')
        messagebox.showerror('Cable Web', f'{title}:\n\n{ex}', parent=self.winfo_toplevel())
        self._draw()

    def _invalidate(self, text='Structure modified.'):
        self.result = None
        self.result_kind = None
        self.results_current = False
        # Bumped by every model-mutating path in the app (all 15 of them go
        # through here). _solve_exact snapshots it and _poll_solve_queue
        # refuses a result whose snapshot no longer matches, so a background
        # solve can never be attributed to a model that changed underneath
        # it. self._solving already blocks the canvas edit path, but only
        # that one -- the dialogs, Undo/Redo, the example loaders and the
        # toolbar are all still live during a solve by design, and this
        # covers every one of them without disabling anything.
        self._model_serial += 1
        # A graded mesh belongs to the model that produced it.
        self._graded_bp = {}
        self._pass1_result = None
        self.validation_var.set('Results outdated — solve again.')
        self.status_var.set(text)
        # The diagrams plot self.result, which _invalidate has just dropped;
        # repaint so they show the "run Analyze" placeholder rather than a
        # picture of tensions belonging to a model that no longer exists.
        self._sync_diagram_pane()
        self._sync_funicular_pane()

    # ------------------------------------------------------------------
    # Result mapping helpers
    # ------------------------------------------------------------------
    def _solver_edges_for_cable(self, cid):
        if not self._solver_meta:
            return []
        ids = []
        for eid, owner in self._solver_meta['seg_owner'].items():
            if owner[0] == cid:
                ids.append(eid)
        return ids

    def _result_tension(self, eid):
        if not self.result or not hasattr(self.result, 'tensions'): return None
        return self.result.tensions.get(eid)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def _tension_color(self, T, tmax):
        if T is None: return CABLE
        f = 0.0 if tmax <= 1e-12 else max(0.0, min(1.0, T/tmax))
        def rgb(h): return tuple(int(h[i:i+2], 16) for i in (1,3,5))
        a, b = rgb(CZ), rgb(CT)
        return '#' + ''.join(f'{int(a[k] + f*(b[k]-a[k])):02x}' for k in range(3))

    def _draw_grid(self, c):
        if not self.grid_visible.get(): return
        z=self.zc.zoom
        major=self._nice_grid_step(SNAP,z,55)
        finest=self._finest_grid_step_world()
        w=self.zc.canvas.winfo_width(); h=self.zc.canvas.winfo_height()
        x0,y0=self.zc.s2w(0,0); x1,y1=self.zc.s2w(w,h)
        xmin,xmax=sorted((x0,x1)); ymin,ymax=sorted((y0,y1))
        # Draw fine grid first, then major grid. Snap uses this same finest step.
        def draw_step(step,color,width=1):
            k0=math.floor(xmin/step)-1; k1=math.ceil(xmax/step)+1
            for k in range(k0,k1+1):
                sx,_=self.zc.w2s(k*step,0); c.create_line(sx,0,sx,h,fill=color,width=width)
            k0=math.floor(ymin/step)-1; k1=math.ceil(ymax/step)+1
            for k in range(k0,k1+1):
                _,sy=self.zc.w2s(0,k*step); c.create_line(0,sy,w,sy,fill=color,width=width)
        if finest < major*0.999:
            draw_step(finest,CG_MINOR)
        draw_step(major,CG,width=1)

    def _draw(self):
        c = self.zc.canvas; c.delete('all')
        self._draw_grid(c)
        # Get result positions, if current.
        result_pos = self.result.positions if self.results_current and self.result is not None else None
        inv_pos = None
        anti_axis_y = None
        if result_pos and self.show_antifunicular.get() and hasattr(self.result, 'inverted_positions'):
            # Mirror the COMPLETE solved web about its highest mathematical y
            # coordinate, not about the mean. This makes the antifunicular a
            # true web-level reflection with a single common symmetry line.
            ys = [p[1] for p in result_pos.values()]
            anti_axis_y = max(ys) if ys else 0.0
            inv_pos = self.result.inverted_positions(anti_axis_y)
        # Remembered so _display_groups can reflect a zero-tension stretch's
        # substitute rather than re-solve it in the mirrored frame.
        self._anti_axis_y = anti_axis_y

        # Draw the at-rest (unloaded, self-weight-only) geometry -- the
        # primary pre-Analyze rendering, kept live-current by
        # _update_reference_result() on every edit. Each segment is either a
        # genuine self-weight catenary (this cable has slack at its current
        # material length) or, per _solve_nominal_catenary's own
        # target_length <= chord case, a straight line -- drawn as such
        # (never stretched or faked into a sag) but visually flagged with
        # WARNING color plus a dash, so it reads as "this cable can't reach
        # at its current length", not as an unremarkable near-zero-sag
        # catenary. Falls back to the straight as-drawn polyline (through
        # any interior attachments, wherever the user has actually dragged
        # them) only if no reference data exists yet for this cable (e.g. a
        # transient error mid-edit).
        if self.show_original.get():
            # _solve_nominal_catenary is a real per-segment physics solve
            # (order ~100ms+ per segment -- confirmed by measurement, not an
            # assumption) so it is only ever re-run on discrete edit events
            # (attachment change, dialog Apply, drag release, ...), never on
            # every mouse-move of a drag. That means self._reference_segments
            # is momentarily stale for whichever cable(s) touch the node
            # currently being dragged. Rather than show that stale, now-
            # detached curve, fall back to the plain straight polyline for
            # just those cables for the duration of the drag -- cheap, always
            # exactly attached to the node under the cursor, and honestly
            # doesn't pretend to be a physically accurate catenary mid-drag.
            # _canvas_release's own _update_reference_result() call restores
            # the true shape the instant the mouse button comes up.
            straight_mode = self.reference_mode.get() == 'straight'
            dragging_cable_ids = set()
            if self.drag_state and self.drag_state[0] == 'node':
                dn = self._node(self.drag_state[1])
                for cd in self.cables:
                    if cd['a'] == dn['id'] or cd['b'] == dn['id']:
                        dragging_cable_ids.add(cd['id'])
                for ac, _s in dn.get('attachments', []):
                    dragging_cable_ids.add(ac)
            for cdata in self.cables:
                cid = cdata['id']
                is_selected = ('cable', cid) in self.selected_items
                if straight_mode:
                    segments = None
                else:
                    segments = self._reference_segments.get(cid) if cid not in dragging_cable_ids else None
                if segments:
                    for seg in segments:
                        pts = seg['points']
                        if len(pts) < 2: continue
                        flat = []
                        for x,y in pts:
                            sx, sy = self.zc.w2s(x,y); flat += [sx,sy]
                        if seg['taut']:
                            color = SELECT if is_selected else WARNING
                            width = 4 if is_selected else 2
                            c.create_line(*flat, fill=color, width=width, dash=(6,3), smooth=False)
                        else:
                            color = SELECT if is_selected else CABLE
                            width = 4 if is_selected else 2
                            c.create_line(*flat, fill=color, width=width, smooth=False)
                else:
                    poly = self._cable_polyline(cid)
                    pts = [(p[2], p[3]) for p in poly]
                    if len(pts) >= 2:
                        flat = []
                        for x,y in pts:
                            sx, sy = self.zc.w2s(x,y); flat += [sx,sy]
                        color = SELECT if is_selected else CABLE
                        width = 4 if is_selected else 2
                        c.create_line(*flat, fill=color, width=width, smooth=False)
                # cable ID at midpoint of chord
                if self.show_results.get():
                    a,b=self._node(cdata['a']),self._node(cdata['b'])
                    sx,sy=self.zc.w2s((a['x']+b['x'])/2,(a['y']+b['y'])/2)
                    c.create_text(sx,sy-10,text=f'C{cid}',fill=MUTED,font=('Helvetica',8))

        # Loads on original geometry.
        if self.show_loads.get(): self._draw_loads(c)

        # Funicular: map solver nodes back to screen. Solver nodes include
        # load discretisation nodes; draw all solver edges.
        if self.show_funicular.get() and result_pos:
            self._draw_solver_result(c, self.result, result_pos, FUN, 'F', self._solver_meta)
            if self.show_force_vectors.get():
                self._draw_force_vectors(c)
        if self.show_antifunicular.get() and inv_pos:
            # One common axis for the entire network. Draw it before the
            # mirrored web so the reflection relationship is visually explicit.
            if anti_axis_y is not None:
                _, sy = self.zc.w2s(0.0, -anti_axis_y * PX_PER_M)
                c.create_line(0, sy, self.zc.canvas.winfo_width(), sy,
                              fill=ANTI, width=1, dash=(8,4))
                c.create_text(10, sy-8, text='Antifunicular symmetry line',
                              anchor='w', fill=ANTI, font=('Helvetica',8))
            self._draw_solver_result(c, self.result, inv_pos, ANTI, 'A', self._solver_meta)
            # The same loads, on the mirrored web. Drawn AFTER the mirrored
            # curve so the arrows sit on top of it rather than under it, and
            # in ANTI colour so they read as belonging to this view and not
            # to the funicular's own (LOAD-coloured) set.
            if self.show_loads.get():
                self._draw_loads(c, solved_positions=inv_pos, color=ANTI)

        # User nodes are drawn last so junctions remain visible. When a valid
        # result is displayed, free user nodes (especially web junctions) must
        # follow their solved positions. Drawing them at their original chord
        # coordinates makes a connected cable appear to detach or form a false
        # arch, which was the remaining visual defect in cable C.
        solved_user = {}
        if result_pos and self.show_funicular.get() and self._solver_meta:
            for n in self.nodes:
                sid=self._solver_meta['node_map'].get(n['id'])
                if sid in result_pos:
                    xm,ym=result_pos[sid]; solved_user[n['id']]=self._m_to_world(xm,ym)
        solved_anti = {}
        if inv_pos and self._solver_meta:
            for n in self.nodes:
                sid=self._solver_meta['node_map'].get(n['id'])
                if sid in inv_pos:
                    xm,ym=inv_pos[sid]; solved_anti[n['id']]=self._m_to_world(xm,ym)
        dragging_node_id = self.drag_state[1] if (self.drag_state and self.drag_state[0] == 'node') else None
        for n in self.nodes:
            if solved_user:
                wx,wy=solved_user.get(n['id'],(n['x'],n['y']))
            elif solved_anti and self.show_antifunicular.get():
                wx,wy=solved_anti.get(n['id'],(n['x'],n['y']))
            elif (self.show_original.get() and self.reference_mode.get() == 'catenary'
                  and n['id'] != dragging_node_id and n['id'] in self._reference_junction_positions):
                # Show this junction at its true self-weight equilibrium
                # position (Catenary preview -- MANIFESTO.md sec 6) rather
                # than n['x']/n['y']'s straight-chord position. This is a
                # RENDER-only substitution: n['x']/n['y'] itself is left
                # untouched, so _point_on_chord, s-coordinate bookkeeping,
                # hit-testing and dragging all keep using the stored
                # position exactly as before (Phase 2 requirement 1).
                wx,wy=self._reference_junction_positions[n['id']]
            else:
                wx,wy=n['x'],n['y']
            sx,sy=self.zc.w2s(wx,wy)
            selected = ('node', n['id']) in self.selected_items
            if n['support']:
                r=8; fill=SUPPORT
                c.create_polygon(sx,sy-r,sx-r,sy+r,sx+r,sy+r,fill=fill,outline=TEXT,width=2)
            else:
                r=7 if selected else 6
                c.create_oval(sx-r,sy-r,sx+r,sy+r,fill=JUNCTION,outline=SELECT if selected else TEXT,width=2)
            c.create_text(sx+12,sy-12,text=n['id'],fill=TEXT,font=('Helvetica',8))

        if self.connect_start is not None:
            n=self._node(self.connect_start); sx,sy=self.zc.w2s(n['x'],n['y'])
            c.create_oval(sx-11,sy-11,sx+11,sy+11,outline=SELECT,width=2)

    # (A second, dead copy of _result_user_node_positions sat here and
    # returned a SET OF NODE IDS rather than a position mapping. The real
    # one, near the end of the class, won only because it is defined later
    # in the file -- so any reordering would have silently swapped the
    # funicular's node placement for a set of integers. Removed 2026-09-04.)

    @staticmethod
    def _insert_sag_vertex(pts):
        """Display-only: add the true low (or high) point of a loaded span.

        The solver meshes each cable uniformly in arc length, so the real
        vertex of a span lands on a node only by luck -- and once a point
        load or a junction inserts its own breakpoint, the spacing is
        uneven and it essentially never does. The polyline through those
        nodes then runs flat across the vertex, which is the "plateau at
        the peak or valley" this rendering was reported for. Forcing an
        even mesh (see _solver_breakpoints) fixes the clean symmetric case;
        this covers the rest.

        A cable under distributed load is locally parabolic, so the vertex
        is recovered by fitting a parabola through the three solved nodes
        around the discrete turning point and taking its apex. That is the
        same physics the solver used, evaluated between its own nodes -- not
        invented curvature. Adds at most ONE point per drawn group, only
        where the span actually turns, and only when the apex lies strictly
        between the bracketing nodes.

        Measured 2026-09-05, 20 m span / 26 m cable / w=10 with a 150 N
        point load at s=6: flat run 94.1 px (13.1% of the group) before,
        versus 30.9 px (6.4%) for the same cable with no point load -- which
        is itself faithful, since a true catenary is ~5-7% flat at this
        scale. Works for the antifunicular too: the mirrored web turns the
        sag into a peak, and the sign test below handles both.
        """
        n = len(pts)
        if n < 3:
            return pts
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        # Needs a monotone x to talk about a parabola y(x) at all -- a
        # vertical hanger has no vertex to find.
        if not (all(xs[i] < xs[i + 1] for i in range(n - 1))
                or all(xs[i] > xs[i + 1] for i in range(n - 1))):
            return pts
        j = None
        for i in range(1, n - 1):
            d0 = ys[i] - ys[i - 1]
            d1 = ys[i + 1] - ys[i]
            if (d0 < 0.0 <= d1) or (d0 > 0.0 >= d1):
                j = i
                break
        if j is None:
            return pts
        x0, x1, x2 = xs[j - 1], xs[j], xs[j + 1]
        y0, y1, y2 = ys[j - 1], ys[j], ys[j + 1]
        denom = (x0 - x1) * (x0 - x2) * (x1 - x2)
        if abs(denom) < 1e-15:
            return pts
        A = (x2 * (y1 - y0) + x1 * (y0 - y2) + x0 * (y2 - y1)) / denom
        B = (x2 * x2 * (y0 - y1) + x1 * x1 * (y2 - y0) + x0 * x0 * (y1 - y2)) / denom
        if abs(A) < 1e-15:
            return pts
        xv = -B / (2.0 * A)
        lo, hi = (x0, x2) if x0 < x2 else (x2, x0)
        if not (lo < xv < hi):
            return pts
        C = y0 - A * x0 * x0 - B * x0
        yv = A * xv * xv + B * xv + C
        # It must reach past the nodes we already have, or it adds nothing.
        if A > 0.0 and yv >= min(y0, y1, y2):
            return pts
        if A < 0.0 and yv <= max(y0, y1, y2):
            return pts

        # Find which existing segment the apex lands in, and refuse to split
        # that segment anywhere near either of its ends.
        #
        # This guard used to read "not within 2% of the three-point WINDOW",
        # which is far too weak: the window spans two segments, so 2% of it
        # is 4% of a segment, and an apex landing there creates a sliver
        # beside a full-length neighbour. Centred (Catmull-Rom) tangents
        # across a sliver overshoot badly, and the drawn curve then visibly
        # OSCILLATES. Measured 2026-09-05 on the built-in Example's C2: the
        # apex landed 5.70 px from an existing node against 97.47 px typical
        # spacing, and the drawn curve went from 1 direction reversal
        # (correct -- a single sag) to 3, overshooting the solved envelope by
        # 2.9 px. That is the wobble reported against the 5-9-26 build, and
        # this method introduced it -- the solver was never involved.
        #
        # Requiring the apex to sit in the middle 60% of whichever segment it
        # lands in means neither resulting sub-segment is ever shorter than
        # 20% of the original, so no sliver can be created at all.
        k = None
        for i in range(len(xs) - 1):
            a_, b_ = xs[i], xs[i + 1]
            if (a_ < xv < b_) or (b_ < xv < a_):
                k = i
                break
        if k is None:
            return pts
        seg = abs(xs[k + 1] - xs[k])
        if seg < 1e-12:
            return pts
        frac = abs(xv - xs[k]) / seg
        if not (0.20 <= frac <= 0.80):
            return pts

        out = list(pts)
        out.insert(k + 1, (xv, yv))
        return out

    @staticmethod
    def _smooth_polyline(points, samples_per_segment=12):
        """Return a display-only, bounded cubic interpolation through points.

        Unlike Tk's generic ``smooth=True`` spline, this interpolation does
        not invent large overshoots between solver nodes. It uses centered
        tangents and clamps each coordinate to the local segment envelope.
        Endpoints remain exact. Point-load branches are supplied separately,
        so their kink is preserved.
        """
        if len(points) < 3:
            return list(points)
        n=len(points)
        # Chord lengths, and derivatives expressed PER UNIT CHORD.
        #
        # The Hermite basis below runs t over [0, 1] on every segment
        # regardless of how long that segment is, so a tangent handed to it
        # must be scaled by that segment's own chord. The old code used the
        # centred difference 0.5*(p[i+1]-p[i-1]) unscaled, which is correct
        # only when every chord is the same length -- true of a uniform mesh,
        # false of the curvature-graded one, where spacing ratios of 13:1 were
        # measured. There the tangents came out wildly out of scale and the
        # DRAWN curve left the true catenary by up to 3.84 px while the solved
        # nodes it interpolates were within 1.42 px. Chord-length (Catmull-Rom)
        # parameterisation fixes that, and it reduces exactly to the old
        # expression when the chords are equal, so the uniform-mesh path is
        # unchanged. See MANIFESTO sec 3x.
        d=[]
        for i in range(n-1):
            d.append(max(math.hypot(points[i+1][0]-points[i][0],
                                    points[i+1][1]-points[i][1]), 1e-12))
        deriv=[]
        for i in range(n):
            if i==0:
                deriv.append(((points[1][0]-points[0][0])/d[0],
                              (points[1][1]-points[0][1])/d[0]))
            elif i==n-1:
                deriv.append(((points[-1][0]-points[-2][0])/d[-1],
                              (points[-1][1]-points[-2][1])/d[-1]))
            else:
                dl, dr = d[i-1], d[i]
                lx=(points[i][0]-points[i-1][0])/dl; ly=(points[i][1]-points[i-1][1])/dl
                rx=(points[i+1][0]-points[i][0])/dr; ry=(points[i+1][1]-points[i][1])/dr
                w=dl+dr
                deriv.append(((dr*lx+dl*rx)/w, (dr*ly+dl*ry)/w))
        out=[points[0]]
        for i in range(n-1):
            p0=points[i]; p1=points[i+1]
            m0=(deriv[i][0]*d[i], deriv[i][1]*d[i])
            m1=(deriv[i+1][0]*d[i], deriv[i+1][1]*d[i])
            xlo,xhi=sorted((p0[0],p1[0])); ylo,yhi=sorted((p0[1],p1[1]))
            for k in range(1,samples_per_segment+1):
                t=k/samples_per_segment; t2=t*t; t3=t2*t
                h00=2*t3-3*t2+1; h10=t3-2*t2+t; h01=-2*t3+3*t2; h11=t3-t2
                x=h00*p0[0]+h10*m0[0]+h01*p1[0]+h11*m1[0]
                y=h00*p0[1]+h10*m0[1]+h01*p1[1]+h11*m1[1]
                # Limit interpolation to the local envelope to avoid visual
                # loops/overshoot while keeping the solver nodes exact.
                x=min(xhi,max(xlo,x)); y=min(yhi,max(ylo,y))
                out.append((x,y))
        return out

    def _display_groups(self, result, positions, meta, view='F',
                        mirror_axis=None):
        """The display polyline for every drawn stretch, in MODEL coordinates.

        This is the single definition of "what shape does a solved cable
        actually take on screen", and it is not a small question: a stretch is
        split at every hard point, a genuinely zero-tension stretch has its
        arbitrary interior replaced by a nominal catenary, a uniformly loaded
        one is replaced by its exact closed form (Route 1), and anything left
        gets its true vertex inserted before smoothing.

        It lives here, once, because TWO views need it -- the editing canvas
        and the funicular diagram pane. They were written separately at first
        and drew visibly different shapes for the same solve: on the built-in
        Picture test the two disagreed by 4.2 m, 13.8% of the web, because the
        pane plotted the raw solver polygon while the canvas plotted all three
        of the above. That is MANIFESTO sec 3j -- the same sub-problem solved
        in two places drifts -- caught by the user rather than by us.

        `view` names which set of positions this is ('F' funicular, 'A' the
        mirrored antifunicular), and it is not optional: it keys the
        zero-tension shape cache, which the two views used to share, so
        whichever drew first won and the other rendered its neighbour's shape
        -- measured 210-273 px out of place on the Picture test's mirrored
        view, a bug that predates the pane.

        `mirror_axis` is the y the antifunicular was reflected about. Given
        it, the mirrored view is produced by REFLECTING the funicular's own
        display groups rather than by re-deriving them from mirrored
        coordinates -- see the top of the body for why that distinction is
        load-bearing.

        Yields dicts: cid, eids, pts (model coords), s0/s1 (the stretch's arc
        range) and tmax for colouring.
        """
        if not meta or result is None:
            return

        if view == 'A' and mirror_axis is not None:
            # The antifunicular IS the reflection of the funicular, so build it
            # by reflecting rather than by re-deriving from mirrored
            # coordinates. Every substitution below picks a DIRECTION from the
            # geometry handed to it -- the nominal catenary always hangs, and
            # the analytic fit takes its bulge from the solved polyline -- so
            # re-deriving lets the two views disagree about shapes that must be
            # exact mirrors of one another. Measured before this: a slack
            # stretch 7.8 m out, an inclined analytic stretch 1.4 m out, both
            # on the built-in Picture test. Reflecting is also cheaper: the two
            # views now share one cache entry instead of solving twice.
            upright = {nid: (x, 2.0 * mirror_axis - y)
                       for nid, (x, y) in positions.items()}
            for grp in self._display_groups(result, upright, meta, view='F'):
                out = dict(grp)
                out['pts'] = [(x, 2.0 * mirror_axis - y) for x, y in grp['pts']]
                yield out
            return

        tensions = getattr(result, 'tensions', {}) if hasattr(result, 'tensions') else {}
        vals = [v for v in tensions.values() if v is not None]
        tmax = max(vals) if vals else 0.0

        # Ordered solver edges per user cable. The solver itself remains
        # piecewise-linear; everything here is display-only. Point-load nodes
        # are preserved as hard corners so a point load still appears as an
        # exact kink rather than an artificially rounded curve.
        by_cable = {}
        for eid, owner in meta['seg_owner'].items():
            by_cable.setdefault(owner[0], []).append((owner[1], owner[2], eid))

        point_s = {}
        for load in self.loads:
            if load.get('type') == 'Point':
                point_s.setdefault(load['cable'], []).append(float(load['s1']))

        for cid, edges in by_cable.items():
            edges.sort(key=lambda e: (e[0], e[1]))
            groups = []
            current = []
            hard = sorted(point_s.get(cid, []))
            # A real structural junction is also a hard geometric point: the
            # cable can change direction there because another cable carries
            # force at the node. Never smooth through a junction.
            for n in self.nodes:
                for ac, ss in n.get('attachments', []):
                    if ac == cid:
                        hard.append(float(ss))
            hard = sorted(set(hard))
            for s0, s1, eid in edges:
                if not current:
                    current = [(s0, eid)]
                else:
                    current.append((s0, eid))
                current.append((s1, eid))
                if any(abs(s1 - ps) < 1e-7 for ps in hard):
                    groups.append(current)
                    current = []
            if current:
                groups.append(current)

            for group in groups:
                eids = []
                ss = []
                for sv, eid in group:
                    if not eids or eid != eids[-1]:
                        eids.append(eid)
                    ss.append(sv)
                pts = []
                for idx, eid in enumerate(eids):
                    e = result.model.edges[eid]
                    n0, n1 = e.i, e.j
                    if idx == 0 and n0 in positions:
                        pts.append(positions[n0])
                    if n1 in positions:
                        pts.append(positions[n1])
                if len(pts) < 2:
                    continue

                # A group whose real solved tension is (numerically) zero
                # everywhere is a slack, unloaded stretch: physically, ANY
                # configuration of its free interior nodes satisfies
                # equilibrium equally (T=0 imposes no directional preference at
                # all), so the raw solved positions for its INTERIOR points
                # carry no real physical meaning -- they are wherever the
                # Newton iteration happened to land, not a real shape.
                # Diagnosed 2026-08-20: this produced a visibly wiggly path
                # instead of a clean catenary. The two ENDPOINTS of the group
                # (junctions, supports, or point-load nodes) remain
                # trustworthy -- only the interior is arbitrary. Fix: re-derive
                # a clean shape using the same technique as the unloaded
                # reference ghost -- fixed endpoints, a nominal self-weight
                # (a real rope always has SOME weight, which is what gives a
                # slack rope its real-world droop), and a tiny independent
                # solve. This never touches the real solved model, tensions or
                # reactions -- only how this one group is drawn.
                local = [tensions.get(eid) for eid in eids if tensions.get(eid) is not None]
                zero_threshold = max(tmax * 1e-6, 1e-9)
                if local and all(abs(t) < zero_threshold for t in local):
                    # Cheap only because it is cached per (result, view,
                    # group): _draw runs on every pan/zoom, the shape changes
                    # only on a fresh Analyze.
                    if not hasattr(self, '_zero_tension_shape_cache'):
                        self._zero_tension_shape_cache = {}
                    # Keyed on an explicit counter, not id(result): CPython
                    # reuses addresses and edge ids restart at 1, so a
                    # collected result's entry could be handed to an unrelated
                    # new one. `view` is in the key for the same class of
                    # reason -- the funicular and antifunicular are different
                    # shapes of the same group and must not share an entry.
                    key = (getattr(self, '_result_serial', 0), view, tuple(eids))
                    cached = self._zero_tension_shape_cache.get(key)
                    if cached is not None:
                        pts = cached
                    else:
                        try:
                            glen = sum(result.model.edges[eid].target_length
                                       for eid in eids)
                            (x0, y0), (x1, y1) = pts[0], pts[-1]
                            mini = self._solve_nominal_catenary(x0, y0, x1, y1, glen)
                            if mini is not None and len(mini) > 2:
                                pts = mini
                                self._zero_tension_shape_cache[key] = pts
                        except Exception:
                            pass   # display fallback only -- never break drawing

                # Route 1: replace the solved polygon with the exact curve it
                # was approximating, where this stretch's load makes that curve
                # a known one. Display only, and it falls back to the polygon
                # whenever the closed form does not apply.
                analytic = False
                if self.curve_route.get() == 'analytic':
                    try:
                        owners = [meta['seg_owner'][eid] for eid in eids
                                  if eid in meta['seg_owner']]
                        if owners:
                            g0 = min(o[1] for o in owners)
                            g1 = max(o[2] for o in owners)
                            if self._group_uniform_load(cid, g0, g1) is not None:
                                arc = sum(result.model.edges[eid].target_length
                                          for eid in eids)
                                fit = self._analytic_group_points(pts, arc)
                                if fit and len(fit) >= 2:
                                    pts = fit
                                    analytic = True
                    except Exception:
                        pass       # display fallback only

                # Recover the span's true vertex -- the mesh rarely puts a node
                # on it, and without this the curve shelves flat across the low
                # point. The analytic curve already carries its own vertex at
                # full resolution, so it neither needs this nor should risk the
                # sliver inserting into it could make (sec 3w).
                if not analytic:
                    pts = self._insert_sag_vertex(pts)

                owners = [meta['seg_owner'][eid] for eid in eids
                          if eid in meta['seg_owner']]
                yield {
                    'cid': cid,
                    'eids': eids,
                    'pts': pts,
                    'analytic': analytic,
                    's0': min((o[1] for o in owners), default=0.0),
                    's1': max((o[2] for o in owners), default=0.0),
                    'tmax': tmax,
                }

    def _draw_solver_result(self, canvas, result, positions, color, prefix, meta):
        if not meta or result is None:
            return
        tensions = getattr(result, 'tensions', {}) if hasattr(result, 'tensions') else {}

        for grp in self._display_groups(result, positions, meta, view=prefix,
                                        mirror_axis=self._anti_axis_y):
            eids = grp['eids']
            pts = grp['pts']
            tmax = grp['tmax']
            screen = []
            for x, y in pts:
                wx, wy = self._m_to_world(x, y)
                screen.append(self.zc.w2s(wx, wy))
            # An analytic curve is already sampled densely and evenly; running
            # it through the interpolator would multiply the point count
            # tenfold to reproduce what it already is.
            smooth_screen = self._smooth_polyline(
                screen, samples_per_segment=1 if grp['analytic'] else 10)
            flat = [v for p in smooth_screen for v in p]
            width = 2
            local = [tensions.get(eid) for eid in eids if tensions.get(eid) is not None]
            tv = max(local) if local else None
            if tv is not None and tmax > 1e-12:
                width = 2 + int(4 * tv / tmax)
            draw_color = color
            if prefix == 'F' and tv is not None:
                draw_color = self._tension_color(tv, tmax)
            dash = (5, 3) if prefix == 'A' else None
            # _smooth_polyline is already the complete display-only
            # interpolation. Do not pass it through Tk's second spline
            # interpolator, which can reintroduce overshoot and visually
            # distort a perfectly valid solved web.
            canvas.create_line(*flat, fill=draw_color, width=width, dash=dash,
                               smooth=False)
            if self.show_results.get() and local:
                mid = smooth_screen[len(smooth_screen) // 2]
                canvas.create_text(mid[0], mid[1] - 9, text=f'T={max(local):.0f}',
                                   fill=draw_color, font=('Helvetica', 7))

    # Force-vector colours, shared with the Cable and Arch tabs so the same
    # quantity is the same colour in every tab.
    CFH, CFV, CFR = '#2ecc71', '#8e44ad', '#1a6bbd'

    def _force_vector_stations(self):
        """(x_m, y_m, [(fx, fy, label), ...]) for everything worth drawing.

        Supports get their reaction. The SELECTED joint gets one arrow per
        cable pulling on it plus any load applied at it -- the set whose
        vector sum is zero, which is the property the feature exists to make
        visible. Only the selected one: a five-cable junction with every
        arrow drawn is an unreadable star.
        """
        out = []
        if not (self.results_current and self.result is not None
                and self._solver_meta):
            return out
        node_map = self._solver_meta.get('node_map') or {}
        for n in self.nodes:
            sid = node_map.get(n['id'])
            if sid is None or not n['support']:
                continue
            try:
                rx, ry = self.result.node_reaction(sid)
                x, y = self.result.positions[sid]
            except Exception:
                continue
            out.append((x, y, [(rx, ry, 'R')]))

        if self.selected_kind == 'node' and self.selected_id is not None:
            sid = node_map.get(self.selected_id)
            node = next((n for n in self.nodes if n['id'] == self.selected_id), None)
            if sid is not None and node is not None and not node['support']:
                try:
                    x, y = self.result.positions[sid]
                    mn = self.result.model.nodes[sid]
                    arrows = []
                    for e in self.result.model.incident_edges(sid):
                        if self.result.tensions.get(e.id) is None:
                            continue
                        fx, fy = self.result.edge_force_components(e.id)
                        if e.j != sid:          # components are given for node j
                            fx, fy = -fx, -fy
                        arrows.append((fx, fy, 'T'))
                    if abs(mn.fx) > 1e-12 or abs(mn.fy) > 1e-12:
                        arrows.append((mn.fx, mn.fy, 'P'))
                    # The cables meeting here also hang their own weight on
                    # this node. Leaving it out makes the arrows visibly fail
                    # to close, which would have the feature arguing against
                    # itself -- measured 20 N adrift on a 316 N junction.
                    wx, wy = self.result.node_self_weight(sid)
                    if abs(wx) > 1e-12 or abs(wy) > 1e-12:
                        arrows.append((wx, wy, 'W'))
                    if arrows:
                        out.append((x, y, arrows))
                except Exception:
                    pass
        return out

    def _draw_force_vectors(self, canvas):
        """Draw them on the funicular geometry.

        Scale: the shaft is built in MODEL units and transformed through
        zc.w2s like any other geometry, so it magnifies with the structure --
        which is what makes it readable when you zoom into a junction. The
        arrow HEAD stays a fixed pixel size, because Tk's arrowshape is in
        pixels and a head that scaled with zoom becomes grotesque. That split
        is the whole design decision here.

        Not mirrored into the antifunicular: a reaction is a property of the
        shape and would have to be mirrored rather than copied, and drawing
        two sets at once is exactly the clutter the selected-joint rule exists
        to avoid.
        """
        stations = self._force_vector_stations()
        if not stations:
            return
        biggest = max((math.hypot(fx, fy)
                       for _, _, arrows in stations for fx, fy, _ in arrows),
                      default=0.0)
        if biggest < 1e-9:
            return
        xs = [x for x, _, _ in stations]
        ys = [y for _, y, _ in stations]
        diag = max(math.hypot(max(xs) - min(xs), max(ys) - min(ys)), 1.0)
        scale = (0.18 * diag) / biggest          # model units per newton

        for x, y, arrows in stations:
            ox, oy = self.zc.w2s(*self._m_to_world(x, y))
            for fx, fy, kind in arrows:
                mag = math.hypot(fx, fy)
                if mag < biggest * 1e-3:
                    continue
                ex, ey = x + fx * scale, y + fy * scale
                sx, sy = self.zc.w2s(*self._m_to_world(ex, ey))
                if kind == 'R':
                    hxs, hys = self.zc.w2s(*self._m_to_world(x + fx * scale, y))
                    vxs, vys = self.zc.w2s(*self._m_to_world(x, y + fy * scale))
                    if abs(fx) > biggest * 1e-3:
                        canvas.create_line(ox, oy, hxs, hys, fill=self.CFH,
                                           width=2, arrow='last',
                                           arrowshape=(8, 10, 3))
                    if abs(fy) > biggest * 1e-3:
                        canvas.create_line(ox, oy, vxs, vys, fill=self.CFV,
                                           width=2, arrow='last',
                                           arrowshape=(8, 10, 3))
                colour = {'R': self.CFR, 'T': CT, 'P': CL, 'W': CZ}[kind]
                canvas.create_line(ox, oy, sx, sy, fill=colour, width=2,
                                   arrow='last', arrowshape=(9, 11, 4))
                if self.show_results.get():
                    canvas.create_text(sx, sy - 8, text=f'{mag:.0f}',
                                       fill=colour, font=('Helvetica', 7))
            canvas.create_oval(ox - 3, oy - 3, ox + 3, oy + 3,
                               fill='#333', outline='')

    def _web_diagram_rows(self, positions, idx):
        """Per-edge (s0, p0, p1, value) for every cable, plus the largest
        value anywhere. Pure data: no canvas, no transform, so the pane can
        lay it out and a test can check it without drawing.

        `idx` is _diagram_series' column -- 2 = T, 3 = H, 4 = V -- recomputed
        here from `positions` rather than read from that method, because the
        pane may be showing the MIRRORED web and the components must follow
        the geometry actually on screen.
        """
        per_cable, vmax = {}, 0.0
        if not (self.results_current and self.result is not None
                and self._solver_meta):
            return per_cable, vmax
        for c in self.cables:
            rows = []
            for eid, owner in self._solver_meta['seg_owner'].items():
                if owner[0] != c['id']:
                    continue
                T = self.result.tensions.get(eid)
                if T is None:
                    continue
                e = self.result.model.edges.get(eid)
                if e is None or e.i not in positions or e.j not in positions:
                    continue
                xi, yi = positions[e.i]
                xj, yj = positions[e.j]
                seg = math.hypot(xj - xi, yj - yi)
                if seg < 1e-12:
                    continue
                val = (abs(T) if idx == 2
                       else abs(T * (xj - xi) / seg) if idx == 3
                       else abs(T * (yj - yi) / seg))
                rows.append((owner[1], (xi, yi), (xj, yj), val, seg))
                vmax = max(vmax, val)
            if rows:
                rows.sort(key=lambda r: r[0])
                per_cable[c['id']] = rows
        return per_cable, vmax

    def _build_funicular_pane(self, parent):
        """A parallel view of the solved web with the chosen force diagram
        drawn into its own geometry.

        Deliberately its own panel rather than an overlay on the editing
        canvas: the editor is for building the model and the diagram is for
        reading it, and putting bands over the thing you are dragging makes
        both worse. This is the Vierendeel/Arch idiom -- a schematic beside
        the model -- applied to a funicular.
        """
        self.fd_outer = tk.Frame(parent, bg=PANEL_BG, bd=1, relief='solid')
        hdr = tk.Frame(self.fd_outer, bg=PANEL_BG)
        hdr.pack(fill='x', padx=6, pady=(3, 1))
        tk.Label(hdr, text='FUNICULAR DIAGRAM', bg=PANEL_BG, fg=MUTED,
                 font=('Helvetica', 8, 'bold')).pack(side='left')
        for _t in ('T', 'H', 'V'):
            rb = tk.Radiobutton(hdr, text=_t, value=_t,
                                variable=self.web_diagram_q, bg=PANEL_BG,
                                font=('Helvetica', 8),
                                command=self._draw_funicular_diagram)
            rb.pack(side='left', padx=(6 if _t == 'T' else 0, 0))
            InfoTooltip(rb, {
                'T': 'Axial tension in the cable.',
                'H': 'Horizontal component. Constant along a cable under '
                     'purely vertical load, so an even band is a live check '
                     'that the solve behaved.',
                'V': 'Vertical component. Zero at the low point, greatest at '
                     'the anchorages.'}[_t])
        cb = tk.Checkbutton(hdr, text='Antifunicular', variable=self.fd_flip,
                            bg=PANEL_BG, font=('Helvetica', 8),
                            command=self._draw_funicular_diagram)
        cb.pack(side='left', padx=(10, 0))
        InfoTooltip(cb, 'Mirror the web about its own high point, so the same '
                        'solved forces read as the compression arch the cable '
                        'is dual to. The diagram is unchanged -- only the '
                        'geometry it is drawn on is flipped.')
        tk.Label(hdr, text='scale %', bg=PANEL_BG, fg=MUTED,
                 font=('Helvetica', 8)).pack(side='left', padx=(12, 2))
        tk.Scale(hdr, from_=10, to=300, orient='horizontal',
                 variable=self.fd_scale, length=110, showvalue=True,
                 bg=PANEL_BG, bd=0, highlightthickness=0, relief='flat',
                 font=('Helvetica', 7),
                 command=lambda _v: self._draw_funicular_diagram()).pack(side='left')
        tk.Button(hdr, text='Hide',
                  command=lambda: (self.show_web_diagrams.set(False),
                                   self._sync_funicular_pane()),
                  relief='flat', bg=PANEL_BG, fg=MUTED,
                  font=('Helvetica', 8)).pack(side='right')
        self.fd_canvas = tk.Canvas(self.fd_outer, bg='#fafaf8', height=INIT_FD,
                                    highlightthickness=0)
        self.fd_canvas.pack(fill='both', expand=True, padx=4, pady=(0, 4))
        self.fd_canvas.bind('<Configure>',
                            lambda _e: self._draw_funicular_diagram())
        self._sync_funicular_pane()

    def _sync_funicular_pane(self):
        if not hasattr(self, 'fd_outer'):
            return
        if self.show_web_diagrams.get():
            if not self.fd_outer.winfo_ismapped():
                self.fd_outer.pack(side='bottom', fill='x')
            self._draw_funicular_diagram()
        else:
            self.fd_outer.pack_forget()

    def _draw_funicular_diagram(self):
        """Render the pane: the solved web, and the chosen quantity as a band
        offset perpendicular to each cable's own drawn curve.

        The geometry comes from `_display_groups` -- the SAME pipeline the
        editing canvas draws -- so the two views cannot disagree about the
        shape. They used to: the pane plotted the raw solver polygon while the
        canvas plotted the analytic curve, the zero-tension substitute and the
        inserted vertex, and on the Picture test the two were 4.2 m apart,
        13.8% of the web. That is sec 3j, and the fix is to have one
        definition rather than two that agree by inspection.

        Three decisions, each with a wrong version that looks fine until it
        does not:

        * **One shared scale across the whole web.** Per-cable scaling would
          draw a 27 N tie's band as wide as a 300 N main span, destroying the
          only comparison the drawing exists to make.
        * **Offset along the LOCAL tangent's normal** of the drawn curve, not
          vertically and not from a straight chord.
        * **Stepped in value, not smoothed.** Tension is constant within a
          solver edge, so the band's outer edge steps at every edge boundary;
          a smooth ribbon would imply resolution the solve does not have.

        The view fits itself to the model independently of the editor's zoom,
        and fits to the band AT 100% so the structure holds still while the
        scale slider moves.
        """
        if not hasattr(self, 'fd_canvas'):
            return
        c = self.fd_canvas
        c.delete('all')
        w = c.winfo_width() or 700
        h = c.winfo_height() or INIT_FD
        if w < 40 or h < 40:
            return

        def message(txt):
            c.create_text(w / 2, h / 2, text=txt, fill=MUTED,
                          font=('Helvetica', 9))

        if not (self.results_current and self.result is not None
                and self._solver_meta):
            message('Run Analyze to see the funicular diagram.')
            return

        positions = self.result.positions
        flipped = self.fd_flip.get()
        axis = None
        if flipped and hasattr(self.result, 'inverted_positions'):
            ys = [p[1] for p in positions.values()]
            axis = max(ys) if ys else 0.0
            positions = self.result.inverted_positions(axis)

        q = self.web_diagram_q.get()
        idx = {'T': 2, 'H': 3, 'V': 4}.get(q, 2)
        colour = {'T': CT, 'H': CC, 'V': CV}.get(q, CT)

        # Per-edge values, from the same geometry the pane is about to draw.
        edge_val, edge_s, vmax = {}, {}, 0.0
        for eid, owner in self._solver_meta['seg_owner'].items():
            T = self.result.tensions.get(eid)
            e = self.result.model.edges.get(eid)
            if T is None or e is None or e.i not in positions or e.j not in positions:
                continue
            xi, yi = positions[e.i]
            xj, yj = positions[e.j]
            seg = math.hypot(xj - xi, yj - yi)
            if seg < 1e-12:
                continue
            val = (abs(T) if idx == 2
                   else abs(T * (xj - xi) / seg) if idx == 3
                   else abs(T * (yj - yi) / seg))
            edge_val[eid] = val
            edge_s[eid] = (owner[1], owner[2])
            vmax = max(vmax, val)

        groups = list(self._display_groups(self.result, positions,
                                            self._solver_meta,
                                            view='A' if flipped else 'F',
                                            mirror_axis=axis))
        if not groups or vmax <= 1e-12:
            message('Nothing to plot for %s.' % q)
            return

        xs = [pt[0] for g in groups for pt in g['pts']]
        ys = [pt[1] for g in groups for pt in g['pts']]
        diag = max(math.hypot(max(xs) - min(xs), max(ys) - min(ys)), 1.0)
        pct = max(10, min(300, int(self.fd_scale.get() or 100))) / 100.0
        band = (0.10 * diag * pct) / vmax        # model units per newton
        band100 = (0.10 * diag) / vmax

        def group_intervals(grp):
            """This stretch's solver edges as sorted (s_from, s_to, value)."""
            iv = [(edge_s[eid][0], edge_s[eid][1], edge_val.get(eid, 0.0))
                  for eid in grp['eids'] if eid in edge_s]
            iv.sort()
            return iv

        def value_at(iv, s0, s1, frac):
            """The quantity at a fraction along this stretch.

            Stepped: the value belongs to whichever solver EDGE that position
            falls in, because that is the only resolution the solve has.

            The position is clamped and then matched to the NEAREST interval
            rather than skipped. A drawn point's fraction of curve length is
            not exactly its fraction of the cable's s -- the two
            parameterisations differ slightly on a steep stretch -- so a point
            can land a hair outside every interval. Falling back to the first
            edge's value there put a visible sawtooth on the band's outer
            edge; falling back to the nearest one cannot.
            """
            if not iv:
                return 0.0
            sv = min(max(s0 + (s1 - s0) * frac, iv[0][0]), iv[-1][1])
            for a, b, val in iv:
                if a - 1e-9 <= sv <= b + 1e-9:
                    return val
            return min(iv, key=lambda r: min(abs(sv - r[0]), abs(sv - r[1])))[2]

        ribbons, fitx, fity, peak = [], list(xs), list(ys), None
        for grp in groups:
            pts = grp['pts']
            if len(pts) < 2:
                continue
            # The same interpolation the canvas applies, so the two views draw
            # the same line and not merely the same points. _smooth_polyline is
            # chord-length parameterised and so commutes with the model->screen
            # map (a uniform scale, a translation and a y-flip); running it here
            # in model coordinates therefore gives exactly the canvas's curve.
            if len(pts) >= 3:
                pts = self._smooth_polyline(
                    pts, samples_per_segment=1 if grp['analytic'] else 10)
            # arc position of each drawn point along its own stretch
            cum = [0.0]
            for i in range(len(pts) - 1):
                cum.append(cum[-1] + math.hypot(pts[i + 1][0] - pts[i][0],
                                                pts[i + 1][1] - pts[i][1]))
            total = cum[-1]
            if total <= 1e-12:
                continue
            iv = group_intervals(grp)
            outer, outer100, vals, nrm = [], [], [], []
            for i, (px, py) in enumerate(pts):
                # normal to the LOCAL tangent of the drawn curve
                j0 = max(0, i - 1)
                j1 = min(len(pts) - 1, i + 1)
                tx, ty = pts[j1][0] - pts[j0][0], pts[j1][1] - pts[j0][1]
                tl = math.hypot(tx, ty)
                if tl < 1e-12:
                    nx, ny = 0.0, 1.0
                else:
                    nx, ny = -ty / tl, tx / tl
                val = value_at(iv, grp['s0'], grp['s1'], cum[i] / total)
                vals.append(val)
                nrm.append((nx, ny))
                outer.append((px + nx * val * band, py + ny * val * band))
                o100 = val * band100
                outer100.append((px + nx * o100, py + ny * o100))
                if peak is None or val > peak[0]:
                    peak = (val, px + nx * val * band, py + ny * val * band)

            # Split into one ribbon per solver EDGE. The value is constant
            # within an edge and steps between them, and drawing the whole
            # stretch as ONE outline turns each step into a spike -- measured
            # 73.6 degree turns on the built-in Example, which read as noise
            # rather than as the honest steps they are. One ribbon per edge
            # renders the same data as clean blocks with a radial riser
            # between them.
            runs, start = [], 0
            for i in range(1, len(vals) + 1):
                if i == len(vals) or abs(vals[i] - vals[start]) > 1e-12:
                    runs.append((start, i))
                    start = i
            for a, b in runs:
                # Include the boundary point so consecutive ribbons meet on the
                # curve, and use the run's ONE value throughout -- the value is
                # constant within a solver edge, so the step between edges
                # shows as a clean radial riser instead of a gap.
                hi = min(b, len(pts) - 1)
                if hi <= a:
                    continue
                v = vals[a]
                sub_pts = pts[a:hi + 1]
                sub_out = [(pts[i][0] + nrm[i][0] * v * band,
                            pts[i][1] + nrm[i][1] * v * band)
                           for i in range(a, hi + 1)]
                ribbons.append((sub_pts, sub_out, grp))
            fitx += [pt[0] for pt in outer100]
            fity += [pt[1] for pt in outer100]

        if not ribbons:
            message('Nothing to plot for %s.' % q)
            return

        bx0, bx1 = min(fitx), max(fitx)
        by0, by1 = min(fity), max(fity)
        m = 26
        k = min((w - 2 * m) / max(bx1 - bx0, 1e-9),
                (h - 2 * m - 14) / max(by1 - by0, 1e-9))
        ox = m + ((w - 2 * m) - (bx1 - bx0) * k) / 2.0
        oy = m + ((h - 2 * m - 14) - (by1 - by0) * k) / 2.0

        def TP(mx, my):
            return (ox + (mx - bx0) * k, oy + (by1 - my) * k)

        for pts, outer, grp in ribbons:
            poly = []
            for mx, my in pts:
                poly.extend(TP(mx, my))
            for mx, my in reversed(outer):
                poly.extend(TP(mx, my))
            c.create_polygon(*poly, fill=colour, outline='', stipple='gray25')
            flat = []
            for mx, my in outer:
                flat.extend(TP(mx, my))
            c.create_line(*flat, fill=colour, width=2)

        # The cable itself, once per stretch -- the ribbons above are split per
        # edge, the curve is not.
        line_col = ANTI if flipped else FUN
        for grp in groups:
            pts = grp['pts']
            if len(pts) < 2:
                continue
            if len(pts) >= 3:
                pts = self._smooth_polyline(
                    pts, samples_per_segment=1 if grp['analytic'] else 10)
            flat = []
            for mx, my in pts:
                flat.extend(TP(mx, my))
            c.create_line(*flat, fill=line_col, width=3)

        if peak is not None:
            px, py = TP(peak[1], peak[2])
            c.create_text(px, py - 10, text='%s max %.4g N' % (q, peak[0]),
                          fill=colour, font=('Helvetica', 8, 'bold'))
        label = {'T': 'TENSION T', 'H': 'THRUST H (horizontal)',
                 'V': 'SHEAR V (vertical)'}[q]
        c.create_text(10, 12, text='%s  ·  %s  ·  scale %d%%'
                      % (label, 'antifunicular' if flipped else 'funicular',
                         int(pct * 100)),
                      anchor='w', fill=colour, font=('Helvetica', 8, 'bold'))
        c.create_text(w - 8, h - 6,
                      text='band drawn perpendicular to the same curve the '
                           'canvas draws · one scale across all cables',
                      anchor='e', fill='#9a9a9a', font=('Helvetica', 7))

    def _result_point_on_cable(self, cid, s, positions):
        """Return the solved world-coordinate point at cable-local s.

        The solver uses mathematical coordinates (y upward); the editor uses
        world/screen coordinates (y downward). Interpolation is performed in
        solver space first so load markers follow the actual solved funicular,
        not the original straight chord.
        """
        if not self._solver_meta or not positions:
            return None
        edges=[]
        for eid, owner in self._solver_meta['seg_owner'].items():
            if owner[0] == cid:
                edges.append((owner[1], owner[2], eid))
        if not edges:
            return None
        edges.sort(key=lambda e:(e[0],e[1]))
        target=float(s)
        for s0,s1,eid in edges:
            if target <= s1 + 1e-9:
                e=self.result.model.edges[eid]
                p0=positions.get(e.i); p1=positions.get(e.j)
                if p0 is None or p1 is None:
                    return None
                t=0.0 if s1 <= s0 else max(0.0,min(1.0,(target-s0)/(s1-s0)))
                xm=p0[0]+t*(p1[0]-p0[0]); ym=p0[1]+t*(p1[1]-p0[1])
                return self._m_to_world(xm,ym)
        e=self.result.model.edges[edges[-1][2]]
        p=positions.get(e.j)
        return self._m_to_world(*p) if p is not None else None

    def _draw_loads(self, c, solved_positions=None, color=None, use_funicular=True):
        """Draw the load glyphs.

        `solved_positions` selects which solved geometry the markers sit on.
        Passing the antifunicular's `inverted_positions()` draws the same
        loads on the mirrored web -- added 2026-09-05, previously the
        antifunicular was the only view that showed a solved shape with no
        loads on it at all, which made it hard to read as a structure
        carrying anything.

        The load DIRECTION is deliberately not mirrored along with the
        geometry. The antifunicular is the shape that carries these same
        real, downward loads in pure compression (that is the whole point of
        an antifunicular), so an arch with the load arrows still bearing down
        on it from above is the physically meaningful picture. Mirroring the
        arrows too would draw an arch being pulled upwards, which nothing in
        the model describes.
        """
        if color is None:
            color = LOAD
        if solved_positions is None and use_funicular:
            solved_positions = (self.result.positions
                                 if (self.results_current and self.result is not None
                                     and self.show_funicular.get())
                                 else None)
        for l in self.loads:
            cid=l['cable']; L=max(self._cable_length(cid),1e-12)
            a,b=self._node(self._cable(cid)['a']),self._node(self._cable(cid)['b'])
            def pos(s):
                if solved_positions is not None:
                    rp=self._result_point_on_cable(cid,s,solved_positions)
                    if rp is not None:
                        return rp
                t=max(0,min(1,s/L)); return a['x']+t*(b['x']-a['x']),a['y']+t*(b['y']-a['y'])
            if l['type']=='Point':
                x,y=pos(l['s1']); sx,sy=self.zc.w2s(x,y)
                if l['direction']=='Vertical': dx,dy=0,1
                elif l['direction']=='Horizontal': dx,dy=1,0
                else:
                    a2,b2=a,b; ux,uy=unit(b2['x']-a2['x'], b2['y']-a2['y'])
                    if l['direction']=='Tangential': dx,dy=ux,uy
                    elif l['direction']=='Normal': dx,dy=uy,-ux
                    else:
                        ang=math.radians(float(l.get('angle_deg',-90.0))); dx,dy=math.cos(ang),-math.sin(ang)
                length=35
                c.create_line(sx-dx*length,sy-dy*length,sx,sy,fill=color,width=2,arrow='last')
                c.create_text(sx+8,sy-length-4,text=l['id'],fill=color,font=('Helvetica',7))
            else:
                lo,hi=sorted((l['s1'],l['s2']))
                if hi<=lo: continue
                n=8
                for k in range(n+1):
                    s=lo+(hi-lo)*k/n; x,y=pos(s); sx,sy=self.zc.w2s(x,y)
                    if l['direction']=='Horizontal':
                        c.create_line(sx-15,sy,sx+15,sy,fill=color,width=1,arrow='last')
                    elif l['direction']=='Tangential':
                        ux,uy=unit(b['x']-a['x'],b['y']-a['y']); c.create_line(sx-12*ux,sy-12*uy,sx,sy,fill=color,width=1,arrow='last')
                    elif l['direction']=='Normal':
                        ux,uy=unit(b['x']-a['x'],b['y']-a['y']); c.create_line(sx-12*uy,sy+12*ux,sx,sy,fill=color,width=1,arrow='last')
                    else:
                        ang=math.radians(float(l.get('angle_deg',-90.0))); dx,dy=math.cos(ang),-math.sin(ang)
                        c.create_line(sx-12*dx,sy-12*dy,sx,sy,fill=color,width=1,arrow='last')
                x,y=pos((lo+hi)/2); sx,sy=self.zc.w2s(x,y)
                c.create_text(sx,sy-28,text=f"{l['id']} {l['magnitude']:.3g}",fill=color,font=('Helvetica',7))

    # ------------------------------------------------------------------
    # Excel persistence (Cable Web only)
    # ------------------------------------------------------------------
    def _export_excel(self):
        path = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(), title='Export Cable Web to Excel',
            defaultextension='.xlsx', filetypes=[('Excel workbook','*.xlsx')])
        if not path:
            return
        if not _ensure_openpyxl():
            messagebox.showerror('Excel', 'openpyxl is required to export Excel files.', parent=self.winfo_toplevel()); return
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font
            wb=Workbook()
            ws=wb.active; ws.title='Nodes'
            ws.append(['id','x_m','y_m','support','fx_N','fy_N'])
            for n in self.nodes:
                ws.append([n['id'], n['x']/PX_PER_M, -n['y']/PX_PER_M, bool(n['support']), n.get('fx',0.0), -n.get('fy',0.0)])
            for cell in ws[1]: cell.font=Font(bold=True)

            ws=wb.create_sheet('Cables')
            ws.append(['id','start_node','end_node','prescribed_length_m','use_prescribed_length','self_weight_N_per_m'])
            for c in self.cables:
                ws.append([c['id'],c['a'],c['b'],c['length_override'] if c['length_override'] is not None else '',c['length_override'] is not None,c.get('w',0.0)])
            for cell in ws[1]: cell.font=Font(bold=True)

            ws=wb.create_sheet('Attachments')
            ws.append(['node_id','cable_id','s_m'])
            for n in self.nodes:
                for cid,sval in n.get('attachments',[]): ws.append([n['id'],cid,sval])
            for cell in ws[1]: cell.font=Font(bold=True)

            ws=wb.create_sheet('Loads')
            ws.append(['id','cable_id','type','s1_m','s2_m','magnitude','direction','angle_deg','expression'])
            for l in self.loads:
                ws.append([l['id'],l['cable'],l['type'],l['s1'],l['s2'],l['magnitude'],l['direction'],l.get('angle_deg',-90.0),l.get('expression','')])
            for cell in ws[1]: cell.font=Font(bold=True)

            ws=wb.create_sheet('README')
            rows=[
                ['Cable Web model export'],
                ['Units','Geometry/load positions in metres; forces in N; distributed loads/self-weight in N/m.'],
                ['Coordinate convention','x right, y up.'],
                ['Prescribed length','If use_prescribed_length is FALSE/blank, the cable uses its current straight-chord length.'],
                ['Attachments','Each row defines a structural junction node at cable-local material coordinate s.'],
                ['Loads','Point uses s1; UDL/Variable use s1 and s2. Variable stores q(s) in expression.'],
            ]
            for row in rows: ws.append(row)
            ws.column_dimensions['A'].width=24; ws.column_dimensions['B'].width=90
            wb.save(path)
            self.status_var.set(f'Excel exported: {path}')
        except Exception as ex:
            messagebox.showerror('Excel export failed', str(ex), parent=self.winfo_toplevel())

    def _import_excel(self):
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(), title='Import Cable Web from Excel',
            filetypes=[('Excel workbook','*.xlsx')])
        if not path:
            return
        if not _ensure_openpyxl():
            messagebox.showerror('Excel', 'openpyxl is required to import Excel files.', parent=self.winfo_toplevel()); return
        try:
            from openpyxl import load_workbook
            wb=load_workbook(path, data_only=False, read_only=True)
            required={'Nodes','Cables','Attachments','Loads'}
            missing=required-set(wb.sheetnames)
            if missing: raise ValueError('Missing required sheet(s): '+', '.join(sorted(missing)))

            def rows(sheet):
                vals=list(sheet.iter_rows(values_only=True))
                if not vals: return []
                headers=[str(x).strip() if x is not None else '' for x in vals[0]]
                return [dict(zip(headers,row)) for row in vals[1:] if any(v is not None for v in row)]
            nr,cr,ar,lr=rows(wb['Nodes']),rows(wb['Cables']),rows(wb['Attachments']),rows(wb['Loads'])

            new_nodes=[]; node_ids=set()
            for r in nr:
                nid=int(r['id']);
                if nid in node_ids: raise ValueError(f'Duplicate node id {nid}.')
                node_ids.add(nid)
                # Excel stores decimal coordinates independently of the
                # editor's pixel grid. Normalize harmless binary/Excel
                # round-off so a save/reload cannot perturb the nonlinear
                # solver's initial geometry at the 1e-15 level.
                xm=round(float(r['x_m']),12); ym=round(float(r['y_m']),12)
                new_nodes.append({'id':nid,'x':round(xm*PX_PER_M,9),'y':round(-ym*PX_PER_M,9),
                                  'support':bool(r.get('support',False)),'fx':float(r.get('fx_N') or 0.0),'fy':-float(r.get('fy_N') or 0.0),'attachments':[]})

            new_cables=[]; cable_ids=set()
            for r in cr:
                cid=int(r['id']); a=int(r['start_node']); b=int(r['end_node'])
                if cid in cable_ids: raise ValueError(f'Duplicate cable id {cid}.')
                if a not in node_ids or b not in node_ids: raise ValueError(f'C{cid} references a missing endpoint.')
                if a==b: raise ValueError(f'C{cid} has identical endpoints.')
                use=bool(r.get('use_prescribed_length',False))
                raw=r.get('prescribed_length_m')
                override=float(raw) if use and raw not in (None,'') else None
                if override is not None and override<=0: raise ValueError(f'C{cid} has non-positive prescribed length.')
                cable_ids.add(cid); new_cables.append({'id':cid,'a':a,'b':b,'length_override':override,'w':max(0.0,float(r.get('self_weight_N_per_m') or 0.0))})

            bynode={n['id']:n for n in new_nodes}
            for r in ar:
                nid=int(r['node_id']); cid=int(r['cable_id']); sval=float(r['s_m'])
                if nid not in node_ids or cid not in cable_ids: raise ValueError('Attachment references a missing node/cable.')
                cable=next(c for c in new_cables if c['id']==cid)
                # Validate against imported prescribed length when present; otherwise against chord.
                a=bynode[cable['a']]; b=bynode[cable['b']]
                L=cable['length_override'] if cable['length_override'] is not None else math.hypot(a['x']-b['x'],a['y']-b['y'])/PX_PER_M
                if not (0<=sval<=L): raise ValueError(f'Attachment at node {nid} has s outside C{cid}.')
                bynode[nid]['attachments'].append((cid,sval))

            new_loads=[]
            for r in lr:
                cid=int(r['cable_id']); typ=str(r['type']);
                if cid not in cable_ids: raise ValueError(f'Load {r.get("id")} references missing C{cid}.')
                lid=r['id']; s1=float(r['s1_m']); s2=float(r.get('s2_m') if r.get('s2_m') is not None else s1)
                if typ not in ('Point','UDL','Variable'): raise ValueError(f'Unsupported load type {typ}.')
                L=next(c for c in new_cables if c['id']==cid)['length_override']
                if L is None:
                    cc=next(c for c in new_cables if c['id']==cid); a=bynode[cc['a']]; b=bynode[cc['b']]; L=math.hypot(a['x']-b['x'],a['y']-b['y'])/PX_PER_M
                if not (0<=s1<=L and 0<=s2<=L): raise ValueError(f'Load {lid} on C{cid} has s outside the cable.')
                new_loads.append({'id':str(lid),'cable':cid,'type':typ,'s1':s1,'s2':s2,'magnitude':float(r['magnitude'] or 0.0),
                                   'direction':str(r.get('direction') or 'Vertical'),'angle_deg':float(r.get('angle_deg') if r.get('angle_deg') is not None else -90.0),
                                   'expression':str(r.get('expression') or '')})

            self._checkpoint()
            self.nodes=new_nodes; self.cables=new_cables; self.loads=new_loads
            self.next_node_id=max(node_ids,default=0)+1; self.next_cable_id=max(cable_ids,default=0)+1
            numeric_load_ids=[int(str(l['id'])[1:]) for l in new_loads if str(l['id']).startswith('L') and str(l['id'])[1:].isdigit()]
            self.next_load_id=max(numeric_load_ids,default=0)+1
            self.selected_items=set(); self.selected_kind=self.selected_id=None; self.connect_start=None
            self.result=None; self.results_current=False; self._solver_meta=None
            self._update_reference_result(); self._refresh_tree(); self._show_empty_inspector(); self._draw()
            self.validation_var.set('Excel model imported. Validate before solving.')
            self.status_var.set(f'Excel imported: {path}')
        except Exception as ex:
            messagebox.showerror('Excel import failed', str(ex), parent=self.winfo_toplevel())

    # ------------------------------------------------------------------
    # Utility / lifecycle
    # ------------------------------------------------------------------
    def _update_selected_inspector(self):
        if self.selected_kind == 'node' and any(n['id']==self.selected_id for n in self.nodes):
            self._show_node_inspector(self.selected_id)
        elif self.selected_kind == 'cable' and any(c['id']==self.selected_id for c in self.cables):
            self._show_cable_inspector(self.selected_id)
        elif self.selected_kind == 'load' and any(str(l['id'])==str(self.selected_id) for l in self.loads):
            self._show_load_inspector(self.selected_id)

    def _reset_view(self):
        self.zc.reset_view(); self._draw(); self.status_var.set('View reset.')

    def _clear_all(self):
        if self.nodes or self.cables or self.loads:
            if not messagebox.askyesno('Clear Cable Web', 'Delete the entire current model?', parent=self.winfo_toplevel()):
                return
        self._checkpoint()
        self.nodes=[]; self.cables=[]; self.loads=[]; self.result=None; self.results_current=False
        self.selected_kind=self.selected_id=self.connect_start=None
        self.selected_items=set()
        self.next_node_id=self.next_cable_id=self.next_load_id=1
        self.validation_var.set('Model cleared.')
        self._refresh_tree(); self._show_empty_inspector(); self._draw()

    def _load_example(self):
        """Load a deterministic diagnostic cable-web example.

        Geometry uses a base span L=10 m.  Cables A and B each have fixed
        supports separated by L, but prescribed cable length 2L=20 m.
        Cable C joins the points s=L/2=5 m along A and B.  A carries an
        exact point load at s=L; B carries a full-length UDL.  The example
        is intentionally simple enough that the geometry can be inspected
        against the known 2L inextensible-chain behavior.
        """
        self._checkpoint()
        self.nodes=[]; self.cables=[]; self.loads=[]; self.result=None; self.results_current=False
        self.next_node_id=self.next_cable_id=self.next_load_id=1
        self._solver_meta=None; self._reference_result=None; self._reference_meta=None; self._reference_paths={}; self._reference_segments={}; self._reference_junction_positions={}
        self.selected_items=set(); self.selected_kind=self.selected_id=None; self.connect_start=None

        L = 10.0
        span_px = L * PX_PER_M
        # Screen Y is inverted by ZoomCanvas/world conversion.  Put A above B
        # in the mathematical coordinate system so the diagnostic point-load
        # and UDL cases form a stable, physically feasible cable web.
        yA = -5.0 * PX_PER_M
        yB = 5.0 * PX_PER_M
        x0 = 100.0
        x1 = x0 + span_px

        # Four fixed supports: A1-A2 and B1-B2.
        A1=self._new_node(x0, yA, True)
        A2=self._new_node(x1, yA, True)
        B1=self._new_node(x0, yB, True)
        B2=self._new_node(x1, yB, True)

        # User-visible attachment points are at s=L/2=5 m of each 2L cable.
        # Initially this is the corresponding point on the straight chord.
        JA=self._new_node(x0 + 0.25*span_px, yA, False)
        JB=self._new_node(x0 + 0.25*span_px, yB, False)

        ca=self._new_cable(A1['id'], A2['id'])
        cb=self._new_cable(B1['id'], B2['id'])
        cc=self._new_cable(JA['id'], JB['id'])
        ca['length_override']=2.0*L
        cb['length_override']=2.0*L
        # Pinned, not inherited. This is a regression case whose every
        # reference number assumes a weightless cable, and _new_cable's
        # default is a UI convenience that is free to change (and did).
        ca['w']=cb['w']=cc['w']=0.0
        # C initially spans 10 m and has a 10 m prescribed length.
        # With the nonzero diagnostic loads it develops a small but finite
        # tension, avoiding the zero-load indeterminacy while preserving the
        # requested L/2 attachment geometry.
        cc['length_override']=10.0
        ca['w']=0.0
        cb['w']=0.0
        cc['w']=0.0

        self._attach_node(JA['id'], ca['id'], L/2.0)
        self._attach_node(JB['id'], cb['id'], L/2.0)

        # Add a point load to A at the material midpoint s=L.  This is an
        # exact load breakpoint and should produce the expected kink.
        self.loads.append({
            'id':'P-A', 'cable':ca['id'], 'type':'Point',
            's1':L, 's2':L, 'magnitude':100.0,
            'direction':'Vertical', 'angle_deg':-90.0, 'expression':''})

        # Add a full-length UDL to B.  q=10 N/m over 2L=20 m.
        self.loads.append({
            'id':'UDL-B', 'cable':cb['id'], 'type':'UDL',
            's1':0.0, 's2':2.0*L, 'magnitude':10.0,
            'direction':'Vertical', 'angle_deg':-90.0, 'expression':''})
        self.next_load_id=3

        self._invalidate('Diagnostic example loaded: A=C1 point load, B=C2 UDL, C=C3 tie; L=10 m, cable lengths=20 m.')
        self._update_reference_result()
        self._refresh_tree(); self._draw()

    def _load_picture_example(self):
        """Load the second regression example derived from the reported
        non-convergent screenshot.

        Topology:
          C1: support -> interior junction -> support
          C2: support -> interior junction -> support
          C3: junction -> junction

        C3 carries both an exact point load and a full-length UDL. C1/C2
        have prescribed length 16 m over a 10 m support span; C3 has a
        prescribed length of 20 m over a 20 m initial chord. The case was
        chosen because the old bounded LM solver repeatedly stalled near
        residual 2.4e-1 even though a valid positive-tension equilibrium
        exists. It is now a permanent regression case.
        """
        self._checkpoint()
        self.nodes=[]; self.cables=[]; self.loads=[]; self.result=None; self.results_current=False
        self.next_node_id=self.next_cable_id=self.next_load_id=1
        self._solver_meta=None; self._reference_result=None; self._reference_meta=None; self._reference_paths={}; self._reference_segments={}; self._reference_junction_positions={}
        self.selected_items=set(); self.selected_kind=self.selected_id=None; self.connect_start=None

        # Four fixed supports in two separated pairs, all on the same level.
        # Coordinates are in editor pixels; 24 px = 1 m.
        p=[(0.0,0.0),(10.0,0.0),(18.0,0.0),(28.0,0.0)]
        s3=self._new_node(p[0][0]*PX_PER_M,p[0][1]*PX_PER_M,True)
        s4=self._new_node(p[1][0]*PX_PER_M,p[1][1]*PX_PER_M,True)
        s1=self._new_node(p[2][0]*PX_PER_M,p[2][1]*PX_PER_M,True)
        s2=self._new_node(p[3][0]*PX_PER_M,p[3][1]*PX_PER_M,True)
        j6=self._new_node(3.0*PX_PER_M,0.0,False)
        j5=self._new_node(23.0*PX_PER_M,0.0,False)

        c1=self._new_cable(s3['id'],s4['id'])
        c2=self._new_cable(s1['id'],s2['id'])
        c3=self._new_cable(j6['id'],j5['id'])
        c1['length_override']=16.0
        c2['length_override']=16.0
        c3['length_override']=20.0
        # Pinned for the same reason as _load_example: a regression case must
        # not move when a default does. Forcing w=1000 here was measured to
        # take Tmax from 199.9 N to 20 100 N.
        c1['w']=c2['w']=c3['w']=0.0
        self._attach_node(j6['id'],c1['id'],5.0)
        self._attach_node(j5['id'],c2['id'],5.0)

        self.loads=[
            {'id':'P-A','cable':c3['id'],'type':'Point','s1':10.0,'s2':10.0,
             'magnitude':100.0,'direction':'Vertical','angle_deg':-90.0,'expression':''},
            {'id':'UDL-B','cable':c3['id'],'type':'UDL','s1':0.0,'s2':20.0,
             'magnitude':10.0,'direction':'Vertical','angle_deg':-90.0,'expression':''}
        ]
        self.next_load_id=3
        self._invalidate('Picture regression example loaded. Run Analyze to verify the nonlinear web solver.')
        self._update_reference_result(); self._refresh_tree(); self._draw()

    def _snapshot(self):
        return {
            'nodes': [{k: (list(v) if k == 'attachments' else v) for k,v in n.items()} for n in self.nodes],
            'cables': [dict(c) for c in self.cables],
            'loads': [dict(l) for l in self.loads],
            'next_node_id': self.next_node_id,
            'next_cable_id': self.next_cable_id,
            'next_load_id': self.next_load_id,
        }

    def _restore_snapshot(self, snap):
        self.nodes = [{k: (list(v) if k == 'attachments' else v) for k,v in n.items()} for n in snap['nodes']]
        self.cables = [dict(c) for c in snap['cables']]
        self.loads = [dict(l) for l in snap['loads']]
        self.next_node_id = snap['next_node_id']
        self.next_cable_id = snap['next_cable_id']
        self.next_load_id = snap['next_load_id']
        self.result = None; self.results_current = False; self._solver_meta = None; self._reference_result = None; self._reference_meta = None
        self._update_reference_result()
        valid=set()
        valid.update(('node',n['id']) for n in self.nodes)
        valid.update(('cable',c['id']) for c in self.cables)
        valid.update(('load',str(l['id'])) for l in self.loads)
        self.selected_items &= valid
        if self.selected_items:
            self.selected_kind,self.selected_id=next(iter(self.selected_items))
        else:
            self.selected_kind=self.selected_id=None
        self._refresh_tree(); self._update_selected_inspector(); self._draw()

    def _checkpoint(self):
        # Avoid a second history entry for nested operations such as creating
        # a node followed immediately by attaching it to a cable.
        if getattr(self, '_restoring', False):
            return
        self._history.append(self._snapshot())
        if len(self._history) > 50:
            self._history.pop(0)
        self._future.clear()

    def _undo(self):
        if not self._history:
            self.status_var.set('Nothing to undo.')
            return
        self._future.append(self._snapshot())
        snap = self._history.pop()
        self._restoring = True
        try: self._restore_snapshot(snap)
        finally: self._restoring = False
        self.status_var.set('Undo.')

    def _redo(self):
        if not self._future:
            self.status_var.set('Nothing to redo.')
            return
        self._history.append(self._snapshot())
        snap = self._future.pop()
        self._restoring = True
        try: self._restore_snapshot(snap)
        finally: self._restoring = False
        self.status_var.set('Redo.')

    def _zoom_in(self):
        self.zc.zoom_in()
        self._draw()

    def _zoom_out(self):
        self.zc.zoom_out()
        self._draw()

    def _fit_view(self):
        # Bounding box starts from the user's own nodes, then widens to cover
        # whatever else is currently visible on screen -- the solved
        # funicular and the antifunicular (which can swing well above the
        # supports -- it's a mirror of the sag, so it rises by roughly the
        # same amount) and the unloaded/natural-catenary reference -- so Fit
        # never crops something it should be framing. Each source is only
        # included while its own checkbox would actually draw it, mirroring
        # _draw()'s own visibility conditions exactly.
        xs=[n['x'] for n in self.nodes]; ys=[n['y'] for n in self.nodes]

        result_pos = self.result.positions if (self.results_current and self.result is not None) else None
        if result_pos and self.show_funicular.get():
            for xm, ym in result_pos.values():
                wx, wy = self._m_to_world(xm, ym)
                xs.append(wx); ys.append(wy)

        if result_pos and self.show_antifunicular.get() and hasattr(self.result, 'inverted_positions'):
            anti_ys = [p[1] for p in result_pos.values()]
            anti_axis_y = max(anti_ys) if anti_ys else 0.0
            for xm, ym in self.result.inverted_positions(anti_axis_y).values():
                wx, wy = self._m_to_world(xm, ym)
                xs.append(wx); ys.append(wy)

        if self.show_original.get():
            for path in self._reference_paths.values():
                for wx, wy in path:
                    xs.append(wx); ys.append(wy)

        if not xs:
            self.zc.reset_view(); self._draw(); return
        xmin,xmax=min(xs),max(xs); ymin,ymax=min(ys),max(ys)
        w=max(self.zc.canvas.winfo_width(),1); h=max(self.zc.canvas.winfo_height(),1)
        span_x=max(xmax-xmin, PX_PER_M); span_y=max(ymax-ymin, PX_PER_M)
        margin=50.0
        usable_w=max(w-2*margin,1); usable_h=max(h-2*margin,1)
        z=min(usable_w/span_x, usable_h/span_y)
        self.zc.zoom=max(self.zc.MIN_ZOOM,min(self.zc.MAX_ZOOM,z))
        cx=(xmin+xmax)/2.0; cy=(ymin+ymax)/2.0
        self.zc.pan_x=w/(2*self.zc.zoom)-cx
        self.zc.pan_y=h/(2*self.zc.zoom)-cy
        self.zc._on_zoom_changed()
        self._draw()

    def _bind_keys(self):
        self.winfo_toplevel().bind('<F1>', lambda e: self._show_guide(), add='+')
        root=self.winfo_toplevel()
        root.bind_all('<Escape>', lambda e: self._set_tool('select'), add='+')
        def nav_key(event):
            widget=event.widget
            if isinstance(widget,(tk.Entry,tk.Text,ttk.Entry,ttk.Combobox,ttk.Spinbox)):
                return None
            ch=getattr(event,'char','')
            if ch in ('+', '='):
                self._zoom_in(); return 'break'
            if ch in ('-', '_'):
                self._zoom_out(); return 'break'
            if ch in ('0',):
                self._fit_view(); return 'break'
            if ch.lower()=='p':
                self._set_tool('pan'); return 'break'
            if ch.lower()=='s':
                self._set_tool('select'); return 'break'
            return None
        root.bind_all('<Key>', nav_key, add='+')
        def delete_key(event):
            widget=event.widget
            if isinstance(widget,(tk.Entry,tk.Text,ttk.Entry,ttk.Combobox,ttk.Spinbox)):
                return None
            self._delete_selected()
            return 'break'
        root.bind_all('<Delete>', delete_key, add='+')

    def _delete_selected(self):
        items=set(self.selected_items)
        if not items and self.selected_kind is not None:
            items={(self.selected_kind,self.selected_id)}
        if not items:
            self.status_var.set('Nothing selected to delete.')
            return
        self._checkpoint()
        node_ids={int(i) for k,i in items if k=='node'}
        cable_ids={int(i) for k,i in items if k=='cable'}
        load_ids={str(i) for k,i in items if k=='load'}
        if node_ids:
            cable_ids.update(c['id'] for c in self.cables if c['a'] in node_ids or c['b'] in node_ids)
        self.cables=[c for c in self.cables if c['id'] not in cable_ids]
        self.nodes=[n for n in self.nodes if n['id'] not in node_ids]
        self.loads=[l for l in self.loads if l['cable'] not in cable_ids and str(l['id']) not in load_ids]
        for n in self.nodes:
            n['attachments']=[(cid,s) for cid,s in n['attachments'] if cid not in cable_ids]
        self.selected_items=set(); self.selected_kind=self.selected_id=None
        self._invalidate('Selected elements deleted.')
        self._refresh_tree(); self._show_empty_inspector(); self._update_reference_result(); self._draw()

    def _result_user_positions(self):
        return {}

    def _result_user_node_positions(self, result_pos):
        if not self._solver_meta:
            return {}
        out={}
        for n in self.nodes:
            sid=self._solver_meta['node_map'].get(n['id'])
            if sid in result_pos:
                out[n['id']]=result_pos[sid]
        return out


# Backward-compatible aliases are deliberately not needed: main.py imports
# CableWebApp directly, preserving the original public constructor.
