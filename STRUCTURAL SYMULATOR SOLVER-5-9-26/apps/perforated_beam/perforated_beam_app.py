"""
perforated_beam_app.py — Perforated Beam / Cellular Beam tab.

UI/controller only. All engineering math (statics, net-section, Vierendeel,
web-post, combined bending+torsion, reinforcement sizing) lives in
perforated_beam_math.py and is never duplicated here -- this file builds a
BeamConfig from widget state, calls perforated_beam_math.analyze_beam, and
renders the returned report. Units follow perforated_beam_math.py: mm, N,
MPa, N*mm (shown in every relevant label since this differs from the other
tabs' units -- see MANIFESTO).
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import units

from common import PANEL_W, _ensure_openpyxl, UnitsMixin
from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import hyperstatic_math as hym
from apps.perforated_beam import welded_section_math as wsm
from apps.perforated_beam import perforated_beam_excel as pbx
from apps.perforated_beam import section_profile_math as secm
from apps.perforated_beam import opening_reinforcement as ringmod
from apps.perforated_beam import load_combinations as loadcomb
from apps.perforated_beam import vierendeel_hand as vhand
from apps.perforated_beam import assembly_check as asmcheck
from apps.perforated_beam.profile_sketcher_ui import ProfileSketcher
from apps.perforated_beam.section_profile_ui import SectionProfileDesigner
from apps.perforated_beam.perforated_beam_views import BeamViewsPane


SHAPE_TYPES = ['Circle', 'Hexagon', 'Rectangle', 'Custom polygon']

# The two Vierendeel methods, as the combobox spells them.
VIER_STATION = 'Station scan (refined)'
VIER_HAND = 'Hand method (closed form)'
VIER_KEY = {VIER_STATION: 'station', VIER_HAND: 'hand'}
SECTION_MODES = [
    ('Rolled I/W (catalog)', 'catalog'),
    ('Rolled I/W (custom dims)', 'custom_ibeam'),
    ('Double channel (built-up)', 'double_channel'),
    ('Double profile (any base, built-up)', 'double_profile'),
    ('Two profiles, freely placed (welded)', 'compound'),
    ('Custom profile (drawn)', 'custom_profile'),
]
SECTION_MODE_BY_LABEL = dict(SECTION_MODES)
SECTION_MODE_LABEL_BY_KEY = {v: k for k, v in SECTION_MODES}

SUPPORT_KINDS = [
    ('Pin / roller (vertical only)', hym.PIN),
    ('Fixed / built-in (vertical + rotation)', hym.FIXED),
]
SUPPORT_KIND_BY_LABEL = dict(SUPPORT_KINDS)
SUPPORT_LABEL_BY_KIND = {v: k for k, v in SUPPORT_KINDS}

DP_BASE_KINDS = [
    ('Rolled I/W (catalog)', 'catalog'),
    ('Rolled I/W (custom dims)', 'custom_ibeam'),
    ('Channel (catalog)', 'channel_catalog'),
    ('Channel (custom dims)', 'channel_custom'),
    ('Custom drawn profile', 'custom_profile'),
]
DP_BASE_KIND_BY_LABEL = dict(DP_BASE_KINDS)
DP_BASE_LABEL_BY_KIND = {v: k for k, v in DP_BASE_KINDS}


def _m(mm):
    """A SPAN-scale length, written in the selected convention.

    Section dimensions (d, bf, tf, plate thickness, weld legs) stay in mm,
    which is how they are specified and how the section maths works. But a
    50 400 mm span with supports at 16 200 mm reads as noise; along the beam
    the answer is metres, or feet under AISC -- whichever the unit selector
    above the notebook is set to."""
    v = units.from_si('length', mm / 1000.0)
    return f"{f'{v:.3f}'.rstrip('0').rstrip('.')} {units.label('length')}"


def _shape_vertices(shape_type, p1, p2, p3, poly_text):
    if shape_type == 'Circle':
        return pbm.opening_circle(p1)
    if shape_type == 'Hexagon':
        return pbm.opening_hexagon(p1, p2, p3 if p3 else None)
    if shape_type == 'Rectangle':
        return pbm.opening_rectangle(p1, p2)
    if shape_type == 'Custom polygon':
        pts = []
        for pair in poly_text.replace('\n', ';').split(';'):
            pair = pair.strip()
            if not pair:
                continue
            x_str, y_str = pair.split(',')
            pts.append((float(x_str), float(y_str)))
        return pbm.opening_polygon(pts)
    raise ValueError(f'unknown shape type {shape_type}')


class PerforatedBeamApp(UnitsMixin, tk.Frame):
    """
    Perforated Beam tab — Vierendeel moment, web-post buckling, and combined
    bending+torsion reinforcement sizing for long-span beams with an
    arbitrary number/distribution of web openings.
    Units: mm, N, MPa (=N/mm^2), N*mm.

    That is what this tab STORES and what its maths works in, and it stays
    that way whatever convention is selected above the notebook -- CIRSOC 301
    is written in mm and MPa and so is every equation here. The selector
    changes how those numbers are shown: a span typed in feet under AISC
    reaches the solver in mm, and a result computed in N is written as kip.

    One deliberate exception, stated on the report itself: fabrication-detail
    lines that come back from the section modules as finished text (weld legs,
    part gaps, ring thicknesses) stay in mm. Those modules are unit-pure by
    design and none of them imports this presentation layer.
    """

    # mm, N, N*mm, MPa -- nothing like what the Beam or Truss tabs hold, so it
    # is declared rather than assumed. Getting this wrong would not be a
    # cosmetic error: it would put a span out by a factor of a thousand.
    STORAGE_UNITS = units.storage_like(
        'perforated-beam storage',
        length=units.MM,
        section_length=units.MM,
        detail_length=units.MM,
        force=units.Unit('N', 1.0),
        moment=units.Unit('N\u00b7mm', 1e3),
        line_load=units.Unit('N/mm', 1e-3),
        stress=units.MPA,
        modulus=units.MPA,
        area=units.MM2,
        inertia=units.MM4,
        deflection=units.MM,
    )

    def __init__(self, master, **kw):
        super().__init__(master, bg='#f5f5f3', **kw)
        self.init_units(repaint=self._on_units_changed)
        self.length = 8000.0
        self.section_name = 'IPE 400'
        self.custom_section = None   # RolledSection or None -> use catalog
        self.channel_name = 'UPN 220'
        self.custom_channel = None   # ChannelSection or None -> use channel catalog
        self.double_channel_width = 350.0
        self.double_profile_gap = 200.0
        self.custom_profile_section = None  # CustomProfileSection or None, from the profile designer
        self.custom_profile_sketch = None   # the SectionSketch behind it, so its welds survive
        self.compound_offsets = {'cp_a': (0.0, 0.0), 'cp_b': (0.0, 0.0)}
        self.compound_welds = []     # [wsm.WeldLine] added by hand in compound coordinates
        self.Fy = 250.0
        self.E = 200000.0
        self.stiffener_spacing = None   # None = unstiffened web (kv = 5)
        self.Lb = 0.0                # 0 = compression flange continuously braced
        self.Cb = 1.0                # CIRSOC F.1(3); 1.0 is the permitted conservative value
        self.load_on_top_flange = False
        self.openings = []           # list of OpeningInstance
        self.supports = None         # (xA, xB) or None -> defaults to (0, L), i.e. supports at both ends
        # Advanced support list. Empty -> the determinate 2-support model
        # above; non-empty -> the beam goes through the stiffness solver,
        # which is what allows a third support or a built-in end.
        self.support_specs = []
        self.loads = []              # list of dicts describing each load (for the listbox + rebuild)
        self.report = None
        self._build_ui()

    # ── model assembly ──────────────────────────────────────────────────
    def _current_channel(self):
        if self.custom_channel is not None:
            return self.custom_channel
        return pbm.CHANNEL_CATALOG[self.channel_name]

    def _apply_orientation(self, base, rotate_var, mirror_var):
        rotate90, mirror = rotate_var.get(), mirror_var.get()
        if rotate90 or mirror:
            return pbm.OrientedSection(base, rotate90=rotate90, mirror=mirror)
        return base

    def _read_base_picker(self, prefix):
        """Reads back whatever `_build_base_picker(parent, prefix)` built,
        constructing (and orienting, if requested) the actual section
        object it currently describes."""
        kind = DP_BASE_KIND_BY_LABEL[getattr(self, f'{prefix}_base_kind_var').get()]
        if kind == 'catalog':
            base = pbm.SECTION_CATALOG[getattr(self, f'{prefix}_section_var').get()]
        elif kind == 'custom_ibeam':
            vals = {k: v.get() for k, v in getattr(self, f'{prefix}_custom_vars').items()}
            if not all(vals.values()):
                raise ValueError('Enter all four custom I-beam dimensions (d, bf, tf, tw).')
            base = pbm.RolledSection('custom', float(vals['d']), float(vals['bf']),
                                      float(vals['tf']), float(vals['tw']))
        elif kind == 'channel_catalog':
            base = pbm.CHANNEL_CATALOG[getattr(self, f'{prefix}_channel_var').get()]
        elif kind == 'channel_custom':
            vals = {k: v.get() for k, v in getattr(self, f'{prefix}_custom_channel_vars').items()}
            if not all(vals.values()):
                raise ValueError('Enter all four custom channel dimensions (h, bf, tf, tw).')
            base = pbm.ChannelSection('custom', float(vals['h']), float(vals['bf']),
                                       float(vals['tf']), float(vals['tw']))
        elif kind == 'custom_profile':
            base = getattr(self, f'{prefix}_custom_profile_section')
            if base is None:
                raise ValueError('Design a custom profile first ("Design profile…" button) to use it here.')
        else:
            raise ValueError(f'unknown base profile kind {kind}')
        return self._apply_orientation(base, getattr(self, f'{prefix}_rotate90_var'),
                                        getattr(self, f'{prefix}_mirror_var'))

    def _current_section(self):
        mode = SECTION_MODE_BY_LABEL[self.section_mode_var.get()]
        if mode == 'catalog':
            base = pbm.SECTION_CATALOG[self.section_name]
            return self._apply_orientation(base, self.catalog_rotate90_var, self.catalog_mirror_var)
        if mode == 'custom_ibeam':
            if self.custom_section is None:
                raise ValueError('Enter all four custom I-beam dimensions (d, bf, tf, tw).')
            return self._apply_orientation(self.custom_section, self.custom_ibeam_rotate90_var,
                                            self.custom_ibeam_mirror_var)
        if mode == 'double_channel':
            return pbm.BuiltUpDoubleChannelSection(self._current_channel(), overall_width=self.double_channel_width)
        if mode == 'double_profile':
            base_a = self._read_base_picker('dp_a')
            base_b = self._read_base_picker('dp_b')
            return pbm.BuiltUpDoubleSection(base_a, gap=self.double_profile_gap, base_b=base_b)
        if mode == 'compound':
            return self._build_compound_section()
        if mode == 'custom_profile':
            if self.custom_profile_section is None:
                raise ValueError('Design a custom profile first (see "Design profile…" button).')
            if self.custom_profile_sketch is not None and self.custom_profile_sketch.welds:
                # Drawn welds make this a WeldedProfile: it delegates every
                # section property to the profile itself, and additionally
                # lets check_welds run against the joints as drawn.
                return wsm.WeldedProfile(self.custom_profile_section,
                                          [w.to_weld_line() for w in self.custom_profile_sketch.welds])
            return self.custom_profile_section
        raise ValueError(f'unknown section mode {mode}')

    @staticmethod
    def _welds_into_frame(sketch, section, dx, dy):
        """A drawn profile's own welds, moved from the frame they were
        drawn in into the compound's frame.

        This is exactly the shift PlacedProfile applies to the outline
        (its centroid goes to dx, dy), so a weld drawn along a flange stays
        on that flange once the piece is positioned. Without it the welds
        would silently stay near the origin while the profile moved away
        from it -- and a weld line that misses its own profile reports zero
        shear flow, which reads as a passing check."""
        if sketch is None or not sketch.welds or not hasattr(section, 'centroid'):
            return []
        cx, cy = section.centroid
        ox, oy = dx - cx, dy - cy
        out = []
        for w in sketch.welds:
            wl = w.to_weld_line()
            wl.p1 = (wl.p1[0] + ox, wl.p1[1] + oy)
            wl.p2 = (wl.p2[0] + ox, wl.p2[1] + oy)
            out.append(wl)
        return out

    def _build_compound_section(self):
        parts, welds = [], []
        for prefix, label in (('cp_a', 'Profile A'), ('cp_b', 'Profile B')):
            base = self._read_base_picker(prefix)
            dx, dy = self.compound_offsets[prefix]
            parts.append(wsm.PlacedProfile(base, dx=dx, dy=dy,
                                            label=getattr(base, 'name', label)))
            welds.extend(self._welds_into_frame(
                getattr(self, f'{prefix}_custom_profile_sketch', None), base, dx, dy))
        welds.extend(self.compound_welds)
        return wsm.CompoundSection(parts, welds=welds, detail=self._assembly_detail())

    def _assembly_detail(self):
        """The declared joint between the two profiles, or None.

        None is a real answer, not a missing one: without it the section
        keeps refusing to report J and Aweb, so the combined check stays
        bending-only and says so -- which is the honest outcome when
        nobody has said whether the seam is continuous."""
        kind = self.assembly_kind_var.get()
        if kind == 'none':
            return None
        try:
            t = float(self.assembly_t_var.get() or 0.0)
        except (TypeError, ValueError):
            t = 0.0
        return wsm.AssemblyDetail(kind, plate_thickness=max(0.0, t))

    def _current_material(self):
        return pbm.Material(Fy=self.Fy, E=self.E)

    def _build_beam(self):
        # An advanced support list wins when there is one: it can express
        # everything the (xA, xB) pair can and more, so there is no case
        # where both should be honoured at once.
        specs = [hym.SupportSpec(s['x'], s['kind'], s['torsion']) for s in self.support_specs]
        beam = pbm.BeamConfig(L=self.length, section=self._current_section(),
                               material=self._current_material(), openings=list(self.openings),
                               supports=None if specs else self.supports,
                               support_specs=specs or None,
                               Lb=self.Lb, Cb=self.Cb,
                               stiffener_spacing=self.stiffener_spacing,
                               load_on_top_flange=self.load_on_top_flange)
        for ld in self.loads:
            t = ld['type']
            c = ld.get('case') or loadcomb.DEFAULT_CASE
            if t == 'Point load':
                beam.point_loads.append(pbm.PointLoad(ld['x1'], ld['v1'], ld.get('e', 0.0), c))
            elif t == 'Point moment':
                beam.point_moments.append(pbm.PointMoment(ld['x1'], ld['v1'], c))
            elif t == 'Point torque':
                beam.point_torques.append(pbm.PointTorque(ld['x1'], ld['v1'], c))
            elif t == 'Distributed load':
                beam.dist_loads.append(pbm.DistLoad(ld['x1'], ld['x2'], ld['v1'], ld['v2'],
                                                    ld.get('e', 0.0), c))
            elif t == 'Distributed torque':
                beam.dist_torques.append(pbm.DistTorque(ld['x1'], ld['x2'], ld['v1'],
                                                        ld['v2'], c))
        return beam

    # ── UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        tb = tk.Frame(self, bg='#ebebea')
        tb.pack(fill='x', padx=6, pady=(6, 0))
        tk.Button(tb, text='Example: uniform circular openings', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), command=self._load_example).pack(side='left', padx=2)
        tk.Button(tb, text='Clear', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), command=self._clear_all).pack(side='left', padx=2)
        tk.Frame(tb, width=1, bg='#ccc').pack(side='left', fill='y', padx=6, pady=3)
        tk.Button(tb, text='▶ Analyze', relief='flat', bd=0, padx=10, pady=4,
                  bg='#1a6bbd', fg='white', font=('Helvetica', 11, 'bold'),
                  command=self._analyze).pack(side='left', padx=2)
        tk.Button(tb, text='Save report (.txt)', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), fg='#1a6bbd', command=self._save_report).pack(side='left', padx=2)
        tk.Frame(tb, width=1, bg='#ccc').pack(side='left', fill='y', padx=6, pady=3)
        tk.Button(tb, text='Export Excel', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), fg='#1a6bbd', command=self._export_excel).pack(side='left', padx=2)
        tk.Button(tb, text='Import Excel', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), fg='#1a6bbd', command=self._import_excel).pack(side='left', padx=2)

        # Left column and results pane share a PanedWindow, so the divider
        # between them can be DRAGGED. The column was a fixed PANEL_W + 60
        # and its own contents did not fit: the widest panel asked for
        # 358 px inside 278 px, so every group box, every button label and
        # every help note was clipped by about 80 px. A fixed width cannot
        # be right for everyone -- the tab is used at 1280 and at 2560 --
        # so the width became the user's to set, with a default measured
        # from the content rather than guessed.
        main = tk.PanedWindow(self, orient='horizontal', bg='#d8d8d4',
                              sashwidth=7, sashrelief='raised', sashpad=0,
                              borderwidth=0, opaqueresize=False)
        main.pack(fill='both', expand=True, padx=6, pady=6)
        self._main_paned = main

        # SCROLLABLE, the same canvas + scrollbar arrangement the Truss,
        # Beam, Arch and Cable tabs use: the panels together are taller
        # than a normal display, and without it the loads and the opening
        # list simply could not be reached.
        left_outer = tk.Frame(main, bg='#f5f5f3', width=PANEL_W + 60)
        left_canvas = tk.Canvas(left_outer, bg='#f5f5f3', highlightthickness=0,
                                 width=PANEL_W + 42)
        left_sb = tk.Scrollbar(left_outer, orient='vertical', command=left_canvas.yview)
        left_hsb = tk.Scrollbar(left_outer, orient='horizontal', command=left_canvas.xview)
        left_canvas.configure(yscrollcommand=left_sb.set, xscrollcommand=left_hsb.set)
        # grid, not pack: the horizontal bar is shown and hidden as the
        # user drags the divider, and grid_remove() puts it back in its own
        # cell every time. Re-packing would append it after the expanding
        # canvas, which had already taken the space.
        left_canvas.grid(row=0, column=0, sticky='nsew')
        left_sb.grid(row=0, column=1, sticky='ns')
        left_hsb.grid(row=1, column=0, sticky='ew')
        left_hsb.grid_remove()
        left_outer.rowconfigure(0, weight=1)
        left_outer.columnconfigure(0, weight=1)

        left = tk.Frame(left_canvas, bg='#f5f5f3')
        left_win = left_canvas.create_window((0, 0), window=left, anchor='nw')
        # kept for the layout regression tests: the inner frame's origin is
        # the canvas origin, so a child's offset within it IS its canvas
        # y-coordinate, which is what makes visibility checkable without
        # depending on when the window manager gets round to redrawing.
        self._left_canvas = left_canvas
        self._left_inner = left
        self._left_hsb = left_hsb
        self._left_win = left_win

        def _left_scrollregion(event=None):
            left_canvas.configure(scrollregion=left_canvas.bbox('all'))
        left.bind('<Configure>', _left_scrollregion)

        def _left_width(event=None):
            # ORDER MATTERS. Re-wrap the notes to the canvas width FIRST,
            # then measure: measuring first and wrapping second lets a note
            # keep the width it was just handed, so the panel grows by its
            # own padding on every pass.
            cw = left_canvas.winfo_width()
            self._sync_wraplengths(cw)
            left.update_idletasks()
            # Give the inner frame the LARGER of the canvas width and what
            # the CONTROLS need. Pinning it to the canvas width (what this
            # did before) is precisely what squeezed the panels and clipped
            # their text; the horizontal scrollbar is the honest way out
            # when the user drags the divider in past what they need.
            want = max(cw, left.winfo_reqwidth())
            left_canvas.itemconfigure(left_win, width=want)
            _left_scrollregion()
            # The horizontal bar appears only when it is load-bearing --
            # that is, only when the user has dragged the divider in past
            # what the controls need.
            if want > cw + 1:
                left_hsb.grid()
            else:
                left_hsb.grid_remove()
        left_canvas.bind('<Configure>', _left_width)
        self._left_relayout = _left_width

        def _left_wheel(event):
            left_canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        left_canvas.bind('<Enter>',
                          lambda e: left_canvas.bind_all('<MouseWheel>', _left_wheel))
        left_canvas.bind('<Leave>',
                          lambda e: left_canvas.unbind_all('<MouseWheel>'))

        self._build_beam_panel(left)
        self._build_support_panel(left)
        self._build_opening_panel(left)
        self._build_load_panel(left)

        right = tk.Frame(main, bg='#f5f5f3')
        main.add(left_outer, minsize=self.PANEL_MIN_W, width=PANEL_W + 60,
                 stretch='never')
        main.add(right, minsize=360, stretch='always')
        # Double-clicking the divider snaps the column back to exactly what
        # its contents need -- the width a user would otherwise hunt for by
        # dragging, and the one that guarantees nothing is clipped.
        main.bind('<Double-Button-1>', lambda e: self.fit_left_panel())
        self.after_idle(self.fit_left_panel)
        self.unit_label(
            tk.Label(right, bg='#f5f5f3', font=('Helvetica', 9, 'bold'), fg='#777'),
            lambda: f'Results ({self.u("length")}, {self.u("force")}, '
                    f'{self.u("stress")}, {self.u("moment")}) — '
                    f'fabrication detail in {units.STORAGE.label("detail_length")}'
        ).pack(anchor='w')

        # Report plus the four drawings. The report keeps its own tab and its
        # own widget, so nothing about the existing workflow (or the tests
        # that read `result_text`) moves -- the views are added beside it.
        self.views = BeamViewsPane(right)
        self.views.pack(fill='both', expand=True)

        text_frame = tk.Frame(self.views.report_frame)
        text_frame.pack(fill='both', expand=True)
        sb = tk.Scrollbar(text_frame)
        sb.pack(side='right', fill='y')
        self.result_text = tk.Text(text_frame, wrap='word', font=('Courier', 10), yscrollcommand=sb.set)
        self.result_text.pack(fill='both', expand=True)
        sb.config(command=self.result_text.yview)
        self._set_results_text('Set up the beam, section, openings and loads on the left, then click ▶ Analyze.\n\n'
                                'The Section, Elevation, Diagrams and 3D tabs above draw whatever is '
                                'currently defined — wheel to zoom, middle-drag to pan.')

    # ── left panel width ────────────────────────────────────────────────
    PANEL_MIN_W = 200
    PANEL_MAX_W = 560

    def fit_left_panel(self):
        """Set the divider to exactly what the controls need.

        Measured, not guessed: `winfo_reqwidth()` on the inner frame IS
        the width below which Tk starts clipping its children, so asking
        for that plus the scrollbar is the narrowest setting at which
        nothing is cut. Clamped at the top so a very wide help note
        cannot swallow the drawing area."""
        try:
            want = None
            # Iterate to a fixed point. One pass set the divider from a
            # measurement taken before the geometry manager had settled
            # the widest panel, and landed 86 px short -- a horizontal
            # scrollbar on a freshly opened window. This terminates on the
            # second pass because notes no longer drive the width; the
            # cap is only there so a pathological layout cannot spin.
            for _ in range(4):
                # Measure with the notes wrapped as narrow as the panel is
                # ever allowed to be, so what comes back is the width the
                # CONTROLS need. A note can re-wrap; a combobox cannot.
                self._sync_wraplengths(self.PANEL_MIN_W)
                self._left_inner.update_idletasks()
                need = self._left_inner.winfo_reqwidth() + 22      # scrollbar
                new_want = max(self.PANEL_MIN_W, min(self.PANEL_MAX_W, need))
                if want is not None and abs(new_want - want) <= 1:
                    break
                want = new_want
                self._main_paned.sash_place(0, want, 0)
                self._main_paned.update_idletasks()
            self._left_relayout()      # re-wraps the notes to the final width
        except (tk.TclError, AttributeError):
            pass      # window not realised yet; after_idle will come round again

    def _sync_wraplengths(self, width):
        """Re-wrap the panel's help notes to its current width.

        Found by walking the tree rather than by registration: every long
        note in this column was already built with a `wraplength`, and a
        non-zero wraplength is exactly the marker for "this label is meant
        to wrap". Asking each one to opt in would mean editing fifteen
        call sites and silently missing the ones built later, such as the
        mirror-status note.

        Without this, widening the column leaves the notes in a narrow
        ribbon down the left and narrowing it clips them -- resizing would
        look broken in both directions."""
        try:
            base_x = self._left_inner.winfo_rootx()
        except tk.TclError:
            base_x = None
        stack = [self._left_inner]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            if not isinstance(w, tk.Label):
                continue
            # Wrap to what is left of the panel AT THIS LABEL'S OWN x, not
            # to the whole panel: a note indented three group boxes deep,
            # or packed to the right of a button, has less room than the
            # column is wide. The offset comes from the widget tree rather
            # than from any assumption about who its siblings are.
            offset = 0
            if base_x is not None:
                try:
                    offset = max(0, w.winfo_rootx() - base_x)
                except tk.TclError:
                    offset = 0
                if offset >= width:            # not laid out yet: ignore it
                    offset = 0
            target = max(120, width - offset - 16)
            try:
                current = int(w.cget('wraplength'))
                # A note already declared as wrapping simply follows the
                # width. One that did NOT declare a wraplength is adopted
                # too, but only when it is genuinely too wide and has a
                # space to break at: those were written with hard newlines
                # and, left alone, neither re-flow when the panel is
                # widened nor stop clipping when it is narrowed. A short
                # field label ('Fy (MPa):') never trips this.
                if current > 0:
                    w.configure(wraplength=target)
                elif (w.winfo_reqwidth() > target
                        and ' ' in str(w.cget('text'))):
                    w.configure(wraplength=target)
            except (tk.TclError, ValueError):
                pass

    def _build_beam_panel(self, parent):
        box = tk.LabelFrame(parent, text='Beam & section', bg='#f5f5f3', font=('Helvetica', 9, 'bold'))
        box.pack(fill='x', pady=(0, 6))

        row = tk.Frame(box, bg='#f5f5f3'); row.pack(fill='x', padx=4, pady=2)
        self.unit_label(tk.Label(row, bg='#f5f5f3'),
                        lambda: f'Length L ({self.u("length")}):').pack(side='left')
        self.len_var = self.unit_var(tk.DoubleVar(value=self.length), 'length')
        tk.Entry(row, textvariable=self.len_var, width=9).pack(side='left', padx=4)

        row = tk.Frame(box, bg='#f5f5f3'); row.pack(fill='x', padx=4, pady=2)
        tk.Label(row, text='Section type:', bg='#f5f5f3').pack(side='left')
        self.section_mode_var = tk.StringVar(value=SECTION_MODES[0][0])
        mode_combo = ttk.Combobox(row, textvariable=self.section_mode_var,
                                   values=[lbl for lbl, _ in SECTION_MODES],
                                   width=20, state='readonly')
        mode_combo.pack(side='left', padx=4)
        mode_combo.bind('<<ComboboxSelected>>', lambda e: self._on_section_mode_change())

        # -- mode 1: catalog --
        self.catalog_frame = tk.Frame(box, bg='#f5f5f3')
        row = tk.Frame(self.catalog_frame, bg='#f5f5f3'); row.pack(fill='x', padx=4, pady=2)
        tk.Label(row, text='Section:', bg='#f5f5f3').pack(side='left')
        self.section_var = tk.StringVar(value=self.section_name)
        ttk.Combobox(row, textvariable=self.section_var, values=list(pbm.SECTION_CATALOG.keys()),
                     width=16, state='readonly').pack(side='left', padx=4)
        self.catalog_rotate90_var, self.catalog_mirror_var = self._build_orientation_row(self.catalog_frame)

        # -- mode 2: custom rolled I-beam --
        self.custom_ibeam_frame = tk.LabelFrame(box, text='Custom rolled section (mm)', bg='#f5f5f3')
        self.custom_vars = {k: tk.StringVar(value='') for k in ('d', 'bf', 'tf', 'tw')}
        for k in ('d', 'bf', 'tf', 'tw'):
            r = tk.Frame(self.custom_ibeam_frame, bg='#f5f5f3'); r.pack(fill='x')
            tk.Label(r, text=f'{k}:', bg='#f5f5f3', width=4, anchor='w').pack(side='left')
            tk.Entry(r, textvariable=self.custom_vars[k], width=8).pack(side='left')
        self.custom_ibeam_rotate90_var, self.custom_ibeam_mirror_var = self._build_orientation_row(self.custom_ibeam_frame)

        # -- mode 3: built-up double channel --
        self.double_channel_frame = tk.LabelFrame(box, text='Double channel (built-up, toes-in)', bg='#f5f5f3')
        row = tk.Frame(self.double_channel_frame, bg='#f5f5f3'); row.pack(fill='x', padx=2, pady=2)
        tk.Label(row, text='Channel:', bg='#f5f5f3').pack(side='left')
        self.channel_var = tk.StringVar(value=self.channel_name)
        ttk.Combobox(row, textvariable=self.channel_var, values=list(pbm.CHANNEL_CATALOG.keys()),
                     width=12, state='readonly').pack(side='left', padx=4)
        cust_ch = tk.LabelFrame(self.double_channel_frame, text='...or custom channel (mm)', bg='#f5f5f3')
        cust_ch.pack(fill='x', padx=2, pady=2)
        self.custom_channel_vars = {k: tk.StringVar(value='') for k in ('h', 'bf', 'tf', 'tw')}
        for k in ('h', 'bf', 'tf', 'tw'):
            r = tk.Frame(cust_ch, bg='#f5f5f3'); r.pack(fill='x')
            tk.Label(r, text=f'{k}:', bg='#f5f5f3', width=4, anchor='w').pack(side='left')
            tk.Entry(r, textvariable=self.custom_channel_vars[k], width=8).pack(side='left')
        tk.Label(cust_ch, text='(leave all blank to use the catalog channel above)',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8)).pack(anchor='w', padx=2)
        row = tk.Frame(self.double_channel_frame, bg='#f5f5f3'); row.pack(fill='x', padx=2, pady=2)
        tk.Label(row, text='Overall width (mm):', bg='#f5f5f3').pack(side='left')
        self.double_channel_width_var = tk.DoubleVar(value=self.double_channel_width)
        tk.Entry(row, textvariable=self.double_channel_width_var, width=8).pack(side='left', padx=4)
        tk.Label(self.double_channel_frame,
                 text='Flanges face inward across a central gap; tie plates welded\n'
                      'across that gap connect the two channels -- see "Design\n'
                      'connector plates…" after Analyze. (Need to orient this channel?\n'
                      'Use "Double profile" mode instead, with Channel as both profiles.)',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8), justify='left').pack(anchor='w', padx=2, pady=(2, 0))
        tk.Button(self.double_channel_frame, text='Design connector plates…', relief='flat', bd=0,
                  command=self._open_connector_designer).pack(anchor='w', padx=2, pady=4)

        # -- mode 4: double profile (any two bases, built-up) --
        self.double_profile_frame = tk.LabelFrame(box, text='Double profile (built-up, any base)', bg='#f5f5f3')
        pick_a = tk.LabelFrame(self.double_profile_frame, text='Profile A', bg='#f5f5f3')
        pick_a.pack(fill='x', padx=2, pady=2)
        self._build_base_picker(pick_a, 'dp_a')
        pick_b = tk.LabelFrame(self.double_profile_frame, text='Profile B (defaults to Profile A if left the same)', bg='#f5f5f3')
        pick_b.pack(fill='x', padx=2, pady=2)
        self._build_base_picker(pick_b, 'dp_b')

        row = tk.Frame(self.double_profile_frame, bg='#f5f5f3'); row.pack(fill='x', padx=2, pady=(6, 2))
        tk.Label(row, text='Gap (mm):', bg='#f5f5f3').pack(side='left')
        self.double_profile_gap_var = tk.DoubleVar(value=self.double_profile_gap)
        tk.Entry(row, textvariable=self.double_profile_gap_var, width=8).pack(side='left', padx=4)
        tk.Label(self.double_profile_frame,
                 text='Two profiles, side by side, tied by welded plates spanning\n'
                      'the gap -- pick two different (or two identical) profiles\n'
                      'above, and orient each independently. See "Design connector\n'
                      'plates…" after Analyze.',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8), justify='left').pack(anchor='w', padx=2, pady=(2, 0))
        tk.Button(self.double_profile_frame, text='Design connector plates…', relief='flat', bd=0,
                  command=self._open_connector_designer).pack(anchor='w', padx=2, pady=4)

        # -- mode 5: two profiles, freely placed --
        self.compound_frame = tk.LabelFrame(box, text='Two profiles, freely placed (welded)', bg='#f5f5f3')
        self.compound_offset_vars = {}
        for prefix, title in (('cp_a', 'Profile A'), ('cp_b', 'Profile B')):
            pick = tk.LabelFrame(self.compound_frame, text=title, bg='#f5f5f3')
            pick.pack(fill='x', padx=2, pady=2)
            self._build_base_picker(pick, prefix)
            off = tk.Frame(pick, bg='#f5f5f3'); off.pack(fill='x', pady=(2, 0))
            tk.Label(off, text='offset dx:', bg='#f5f5f3', font=('Helvetica', 8)).pack(side='left')
            dx_var = tk.StringVar(value='0')
            tk.Entry(off, textvariable=dx_var, width=7).pack(side='left', padx=2)
            tk.Label(off, text='dy:', bg='#f5f5f3', font=('Helvetica', 8)).pack(side='left')
            dy_var = tk.StringVar(value='0')
            tk.Entry(off, textvariable=dy_var, width=7).pack(side='left', padx=2)
            tk.Label(off, text='mm', bg='#f5f5f3', fg='#888', font=('Helvetica', 8)).pack(side='left')
            self.compound_offset_vars[prefix] = (dx_var, dy_var)
        tk.Label(self.compound_frame,
                 text='dx/dy place each profile\'s own CENTROID. Unlike "Double\n'
                      'profile", the two pieces need not sit at the same height --\n'
                      'so a channel capping an I-beam, or a plate welded to one\n'
                      'flange, comes out singly symmetric with S_top != S_bot.\n'
                      'Welds drawn on a profile move with it. The composite I\n'
                      'assumes the welds hold: check them in the report.',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8), justify='left').pack(anchor='w', padx=2, pady=(2, 0))

        mrow = tk.Frame(self.compound_frame, bg='#f5f5f3')
        mrow.pack(fill='x', padx=2, pady=(2, 0))
        tk.Button(mrow, text='Profile B = mirror of Profile A', relief='flat', bd=0,
                  padx=6, bg='#eef4fb', command=self._mirror_a_into_b).pack(side='left')
        tk.Label(self.compound_frame,
                 text='Mirrors A left-for-right into B and places the two so their\n'
                      'lips meet — the whole of a symmetric box from one drawing.\n'
                      'B keeps its own copy, so editing A afterwards does not\n'
                      'change it; press this again to re-sync.',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8),
                 justify='left').pack(anchor='w', padx=2)

        detail = tk.LabelFrame(self.compound_frame, text='How the profiles are joined',
                                bg='#f5f5f3')
        detail.pack(fill='x', padx=2, pady=3)
        self.assembly_kind_var = tk.StringVar(value='none')
        for val, lbl in (('none', 'Not stated — torsion and shear left unevaluated'),
                         ('closed', 'Continuous seam along the full length → closed cell'),
                         ('open', 'Joined only at the stitch plates → open section')):
            tk.Radiobutton(detail, text=lbl, value=val, variable=self.assembly_kind_var,
                           bg='#f5f5f3', font=('Helvetica', 8),
                           justify='left', anchor='w').pack(anchor='w', padx=2)
        row = tk.Frame(detail, bg='#f5f5f3'); row.pack(fill='x', padx=2, pady=1)
        tk.Label(row, text='plate thickness t (mm):', bg='#f5f5f3',
                 font=('Helvetica', 8)).pack(side='left')
        self.assembly_t_var = tk.StringVar(value='0')
        tk.Entry(row, textvariable=self.assembly_t_var, width=6).pack(side='left', padx=2)
        tk.Label(detail,
                 text='This is the most consequential choice on this panel. A closed\n'
                      'cell carries torque by Bredt shear flow; the same two profiles\n'
                      'stitched at intervals do not, and their J is thousands of times\n'
                      'smaller. There is no safe default, so leaving it unstated keeps\n'
                      'torsion and shear out of the check rather than guessing.',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8),
                 justify='left').pack(anchor='w', padx=2, pady=(0, 3))

        wf = tk.LabelFrame(self.compound_frame, text='Extra weld lines (compound coordinates)', bg='#f5f5f3')
        wf.pack(fill='x', padx=2, pady=3)
        wrow = tk.Frame(wf, bg='#f5f5f3'); wrow.pack(fill='x')
        self.cw_vars = {}
        for key, label, width, default in (('x1', 'x1', 5, '0'), ('y1', 'y1', 5, '0'),
                                            ('x2', 'x2', 5, '0'), ('y2', 'y2', 5, '0'),
                                            ('leg', 'leg', 4, '0'), ('n', 'x', 2, '1')):
            tk.Label(wrow, text=label, bg='#f5f5f3', font=('Helvetica', 8)).pack(side='left')
            v = tk.StringVar(value=default)
            tk.Entry(wrow, textvariable=v, width=width).pack(side='left', padx=1)
            self.cw_vars[key] = v
        trow = tk.Frame(wf, bg='#f5f5f3'); trow.pack(fill='x', pady=1)
        tk.Label(trow, text='plate t: thicker', bg='#f5f5f3',
                 font=('Helvetica', 8)).pack(side='left')
        self.cw_vars['t_thick'] = tk.StringVar(value='0')
        tk.Entry(trow, textvariable=self.cw_vars['t_thick'], width=5).pack(side='left', padx=1)
        tk.Label(trow, text='thinner', bg='#f5f5f3', font=('Helvetica', 8)).pack(side='left')
        self.cw_vars['t_thin'] = tk.StringVar(value='0')
        tk.Entry(trow, textvariable=self.cw_vars['t_thin'], width=5).pack(side='left', padx=1)
        self.cw_flange_web_var = tk.BooleanVar(value=False)
        tk.Checkbutton(trow, text='flange-to-web', variable=self.cw_flange_web_var,
                       bg='#f5f5f3', font=('Helvetica', 8)).pack(side='left')
        tk.Label(wf, text='Thicknesses drive the Tabla J.2.4 minimum and J.2.2(b) maximum\n'
                          'fillet sizes. Left at 0 they are MEASURED from the geometry at\n'
                          'the line; type them only when you know something the drawing\n'
                          'does not. "flange-to-web" applies J.2.2(b)\'s exemption from\n'
                          'the minimum-size table.',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8), justify='left').pack(anchor='w', padx=2)

        brow = tk.Frame(wf, bg='#f5f5f3'); brow.pack(fill='x', pady=1)
        tk.Button(brow, text='Weld the seam', relief='flat', bd=0, padx=6,
                  bg='#1a6bbd', fg='white',
                  command=self._weld_the_seam).pack(side='left', padx=2)
        tk.Button(brow, text='Add weld', relief='flat', bd=0,
                  command=self._add_compound_weld).pack(side='left', padx=2)
        tk.Button(brow, text='Remove selected', relief='flat', bd=0,
                  command=self._remove_compound_weld).pack(side='left', padx=2)
        self.compound_weld_list = tk.Listbox(wf, height=3, font=('Courier', 8))
        self.compound_weld_list.pack(fill='x', padx=2, pady=2)
        tk.Label(wf, text='"Weld the seam" finds every line along which the two profiles\n'
                          'actually TOUCH and puts a weld on each -- which is where a seam\n'
                          'weld goes. If it finds nothing, the profiles are not in contact:\n'
                          'adjust their dx/dy above until they meet. A weld drawn where\n'
                          'there is no seam reports q = 0, which reads like a pass.',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8), justify='left').pack(anchor='w', padx=2)

        # -- mode 6: custom drawn profile --
        self.custom_profile_frame = tk.LabelFrame(box, text='Custom profile', bg='#f5f5f3')
        tk.Button(self.custom_profile_frame, text='Design profile…', relief='flat', bd=0, padx=6,
                  bg='#1a6bbd', fg='white', command=self._open_profile_designer).pack(anchor='w', padx=2, pady=4)
        self.custom_profile_status = tk.Label(self.custom_profile_frame, text='(no profile designed yet)',
                                               bg='#f5f5f3', fg='#888', font=('Helvetica', 8), justify='left')
        self.custom_profile_status.pack(anchor='w', padx=2, pady=(0, 4))

        row = tk.Frame(box, bg='#f5f5f3'); row.pack(fill='x', padx=4, pady=2)
        self.unit_label(tk.Label(row, bg='#f5f5f3'),
                        lambda: f'Fy ({self.u("stress")}):').pack(side='left')
        self.fy_var = self.unit_var(tk.DoubleVar(value=self.Fy), 'stress')
        tk.Entry(row, textvariable=self.fy_var, width=7).pack(side='left', padx=4)
        self.unit_label(tk.Label(row, bg='#f5f5f3'),
                        lambda: f'E ({self.u("modulus")}):').pack(side='left')
        self.e_var = self.unit_var(tk.DoubleVar(value=self.E), 'modulus')
        tk.Entry(row, textvariable=self.e_var, width=8).pack(side='left', padx=4)

        ltb = tk.LabelFrame(box, text='Lateral-torsional bracing (CIRSOC F.2.2)', bg='#f5f5f3')
        ltb.pack(fill='x', padx=4, pady=2)
        row = tk.Frame(ltb, bg='#f5f5f3'); row.pack(fill='x', padx=2, pady=1)
        self.unit_label(tk.Label(row, bg='#f5f5f3'),
                        lambda: f'Lb ({self.u("length")}):').pack(side='left')
        self.lb_var = self.unit_var(tk.StringVar(value='0'), 'length')
        tk.Entry(row, textvariable=self.lb_var, width=8).pack(side='left', padx=2)
        tk.Label(row, text='Cb:', bg='#f5f5f3').pack(side='left')
        self.cb_var = tk.StringVar(value='1.0')
        tk.Entry(row, textvariable=self.cb_var, width=5).pack(side='left', padx=2)
        row = tk.Frame(box, bg='#f5f5f3'); row.pack(fill='x', padx=4, pady=(4, 0))
        self.unit_label(tk.Label(row, bg='#f5f5f3'),
                        lambda: f'Transverse stiffener spacing a '
                                f'({self.u("detail_length")}):').pack(side='left')
        self.stiff_var = self.unit_var(tk.StringVar(value=''), 'detail_length')
        tk.Entry(row, textvariable=self.stiff_var, width=8).pack(side='left', padx=4)
        tk.Label(box, text='Blank = unstiffened web (kv = 5, G.2.1(b)). Enter the real '
                           'spacing and kv = 5 + 5/(a/h)^2 (G.2.6): stiffeners at a = h '
                           'double kv, and with a slender web that doubles the shear '
                           'buckling capacity. Blank is the conservative default, not a '
                           'guess that there are none.',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_W).pack(anchor='w', padx=4)

        self.top_flange_load_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ltb, text='Load applied on the top flange (uses F.2.5b for Lp)',
                       variable=self.top_flange_load_var, bg='#f5f5f3',
                       font=('Helvetica', 8)).pack(anchor='w', padx=2)
        tk.Label(ltb, text='Lb = 0 means the compression flange is continuously braced\n'
                           '(a floor beam under a slab) -- the usual case. If it is not,\n'
                           'enter the real distance between braces: LTB can govern well\n'
                           'below Mp. Cb = 1.0 is the conservative value F.1(3) permits.',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8), justify='left').pack(anchor='w', padx=2)

        self._on_section_mode_change()

    def _build_support_panel(self, parent):
        """Support arrangement: either the determinate 2-support model, or
        an explicit list that routes the beam through the stiffness solver.

        Kept as two explicit modes rather than one always-visible list
        because the simple case is the overwhelmingly common one, and the
        sketcher already places those two supports graphically. Switching
        to Advanced SEEDS the list from whatever the simple model
        currently says, so the choice never costs the user work already
        done."""
        box = tk.LabelFrame(parent, text='Supports', bg='#f5f5f3', font=('Helvetica', 9, 'bold'))
        box.pack(fill='x', pady=(0, 6))

        self.support_mode_var = tk.StringVar(value='simple')
        row = tk.Frame(box, bg='#f5f5f3'); row.pack(fill='x', padx=4, pady=2)
        tk.Radiobutton(row, text='Simple (2 supports)', value='simple',
                       variable=self.support_mode_var, bg='#f5f5f3',
                       command=self._on_support_mode_change).pack(side='left')
        tk.Radiobutton(row, text='Advanced (continuous / fixed ends)', value='advanced',
                       variable=self.support_mode_var, bg='#f5f5f3',
                       command=self._on_support_mode_change).pack(side='left')

        self.support_status_label = tk.Label(box, text='', bg='#f5f5f3', fg='#666',
                                              font=('Helvetica', 8), justify='left')
        self.support_status_label.pack(anchor='w', padx=4)

        self.advanced_support_frame = tk.Frame(box, bg='#f5f5f3')
        add = tk.Frame(self.advanced_support_frame, bg='#f5f5f3'); add.pack(fill='x', padx=4, pady=2)
        self.unit_label(tk.Label(add, bg='#f5f5f3'),
                        lambda: f'x ({self.u("length")}):').pack(side='left')
        self.sup_x_var = self.unit_var(tk.StringVar(value='0'), 'length')
        tk.Entry(add, textvariable=self.sup_x_var, width=8).pack(side='left', padx=2)
        self.sup_kind_var = tk.StringVar(value=SUPPORT_KINDS[0][0])
        ttk.Combobox(add, textvariable=self.sup_kind_var, width=24, state='readonly',
                     values=[lbl for lbl, _ in SUPPORT_KINDS]).pack(side='left', padx=2)

        add2 = tk.Frame(self.advanced_support_frame, bg='#f5f5f3'); add2.pack(fill='x', padx=4)
        self.sup_torsion_var = tk.BooleanVar(value=True)
        tk.Checkbutton(add2, text='Forked against twist (torsional restraint)',
                       variable=self.sup_torsion_var, bg='#f5f5f3',
                       font=('Helvetica', 8)).pack(side='left')

        btns = tk.Frame(self.advanced_support_frame, bg='#f5f5f3'); btns.pack(fill='x', padx=4, pady=2)
        for label, cmd in (('Add support', self._add_support),
                           ('Remove selected', self._remove_support),
                           ('Clear', self._clear_supports)):
            tk.Button(btns, text=label, relief='flat', bd=0, padx=6, command=cmd).pack(side='left', padx=2)

        self.support_list = tk.Listbox(self.advanced_support_frame, height=4, font=('Courier', 9))
        self.support_list.pack(fill='x', padx=4, pady=2)
        tk.Label(self.advanced_support_frame,
                 text='Pin and roller are the same restraint here: the beam is\n'
                      'analysed in bending, with no axial degree of freedom for a\n'
                      'horizontal restraint to act on. A fixed support adds the\n'
                      'rotational restraint, and so a reaction couple.',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8), justify='left').pack(anchor='w', padx=4)

        self._update_support_status()

    def _on_support_mode_change(self):
        if self.support_mode_var.get() == 'advanced':
            if not self.support_specs:
                xa, xb = self.supports if self.supports else (0.0, self.length)
                self.support_specs = [{'x': xa, 'kind': hym.PIN, 'torsion': True},
                                      {'x': xb, 'kind': hym.PIN, 'torsion': True}]
            self.advanced_support_frame.pack(fill='x')
        else:
            self.support_specs = []
            self.advanced_support_frame.pack_forget()
        self._refresh_support_list()
        self._update_support_status()

    def _add_support(self):
        try:
            x = self.unit_value(self.sup_x_var)
        except (TypeError, ValueError):
            messagebox.showerror('Add support', 'Support position x must be a number.')
            return
        self.support_specs.append({'x': x,
                                   'kind': SUPPORT_KIND_BY_LABEL[self.sup_kind_var.get()],
                                   'torsion': bool(self.sup_torsion_var.get())})
        self.support_specs.sort(key=lambda s: s['x'])
        self._refresh_support_list()
        self._update_support_status()

    def _remove_support(self):
        sel = self.support_list.curselection()
        if sel:
            self.support_specs.pop(sel[0])
            self._refresh_support_list()
            self._update_support_status()

    def _clear_supports(self):
        self.support_specs = []
        self._refresh_support_list()
        self._update_support_status()

    def _refresh_support_list(self):
        self.support_list.delete(0, tk.END)
        for i, s in enumerate(self.support_specs, 1):
            twist = '' if s['torsion'] else '  (free to twist)'
            kind = 'fixed' if s['kind'] == hym.FIXED else 'pin/roller'
            self.support_list.insert(tk.END, f'{i}. x={s["x"]:>8.0f} mm   {kind}{twist}')

    def _build_orientation_row(self, parent):
        """Adds a 'Rotate 90° / Mirror' checkbox pair to `parent`, applying
        to whatever section that frame otherwise describes -- lets a
        catalog (or custom) section be installed rotated relative to
        gravity, since this module has no way to know how it actually
        sits on site. Returns (rotate90_var, mirror_var)."""
        row = tk.Frame(parent, bg='#f5f5f3'); row.pack(fill='x', padx=2, pady=(4, 2))
        rotate_var = tk.BooleanVar(value=False)
        mirror_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text='Rotate 90° (use weak axis as vertical)', variable=rotate_var,
                       bg='#f5f5f3', font=('Helvetica', 8)).pack(anchor='w')
        tk.Checkbutton(row, text='Mirror top/bottom', variable=mirror_var,
                       bg='#f5f5f3', font=('Helvetica', 8)).pack(anchor='w')
        return rotate_var, mirror_var

    def _build_base_picker(self, parent, prefix):
        """Builds a self-contained 'pick a base profile, with orientation'
        widget set inside `parent`, storing everything needed to read it
        back later as attributes named `{prefix}_...` -- see
        `_read_base_picker`. Used twice (prefixes 'dp_a'/'dp_b') for
        Double profile mode's two independently-choosable profiles."""
        setattr(self, f'{prefix}_custom_profile_section', None)
        setattr(self, f'{prefix}_custom_profile_sketch', None)

        row = tk.Frame(parent, bg='#f5f5f3'); row.pack(fill='x', pady=1)
        tk.Label(row, text='Kind:', bg='#f5f5f3').pack(side='left')
        kind_var = tk.StringVar(value=DP_BASE_KINDS[0][0])
        setattr(self, f'{prefix}_base_kind_var', kind_var)
        combo = ttk.Combobox(row, textvariable=kind_var, values=[lbl for lbl, _ in DP_BASE_KINDS],
                              width=16, state='readonly')
        combo.pack(side='left', padx=4)

        catalog_frame = tk.Frame(parent, bg='#f5f5f3')
        r = tk.Frame(catalog_frame, bg='#f5f5f3'); r.pack(fill='x')
        tk.Label(r, text='Section:', bg='#f5f5f3').pack(side='left')
        section_var = tk.StringVar(value='IPE 400')
        setattr(self, f'{prefix}_section_var', section_var)
        ttk.Combobox(r, textvariable=section_var, values=list(pbm.SECTION_CATALOG.keys()),
                     width=12, state='readonly').pack(side='left', padx=4)

        custom_ibeam_frame = tk.Frame(parent, bg='#f5f5f3')
        custom_vars = {k: tk.StringVar(value='') for k in ('d', 'bf', 'tf', 'tw')}
        setattr(self, f'{prefix}_custom_vars', custom_vars)
        for k in ('d', 'bf', 'tf', 'tw'):
            r = tk.Frame(custom_ibeam_frame, bg='#f5f5f3'); r.pack(fill='x')
            tk.Label(r, text=f'{k}:', bg='#f5f5f3', width=4, anchor='w').pack(side='left')
            tk.Entry(r, textvariable=custom_vars[k], width=7).pack(side='left')

        channel_catalog_frame = tk.Frame(parent, bg='#f5f5f3')
        r = tk.Frame(channel_catalog_frame, bg='#f5f5f3'); r.pack(fill='x')
        tk.Label(r, text='Channel:', bg='#f5f5f3').pack(side='left')
        channel_var = tk.StringVar(value='UPN 220')
        setattr(self, f'{prefix}_channel_var', channel_var)
        ttk.Combobox(r, textvariable=channel_var, values=list(pbm.CHANNEL_CATALOG.keys()),
                     width=10, state='readonly').pack(side='left', padx=4)

        channel_custom_frame = tk.Frame(parent, bg='#f5f5f3')
        custom_channel_vars = {k: tk.StringVar(value='') for k in ('h', 'bf', 'tf', 'tw')}
        setattr(self, f'{prefix}_custom_channel_vars', custom_channel_vars)
        for k in ('h', 'bf', 'tf', 'tw'):
            r = tk.Frame(channel_custom_frame, bg='#f5f5f3'); r.pack(fill='x')
            tk.Label(r, text=f'{k}:', bg='#f5f5f3', width=4, anchor='w').pack(side='left')
            tk.Entry(r, textvariable=custom_channel_vars[k], width=7).pack(side='left')

        custom_profile_frame = tk.Frame(parent, bg='#f5f5f3')
        status_label = tk.Label(custom_profile_frame, text='(no profile designed yet)',
                                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8), justify='left', wraplength=200)

        def open_designer():
            def on_apply(sec, sketch):
                setattr(self, f'{prefix}_custom_profile_section', sec)
                setattr(self, f'{prefix}_custom_profile_sketch', sketch)
                extra = ''
                n_holes = len(getattr(sketch, 'holes', []) or [])
                n_welds = len(getattr(sketch, 'welds', []) or [])
                if n_holes:
                    extra += f', {n_holes} hole(s)'
                if n_welds:
                    extra += f', {n_welds} weld(s)'
                status_label.configure(
                    text=f'A={sec.A:.0f} mm^2, I={sec.I:.3g} mm^4{extra}', fg='#2e9e4f')
            SectionProfileDesigner(
                self, on_apply=on_apply,
                existing_sketch=getattr(self, f'{prefix}_custom_profile_sketch', None),
                opening_ctx=self._opening_ctx())

        tk.Button(custom_profile_frame, text='Design profile…', relief='flat', bd=0,
                  command=open_designer).pack(anchor='w')
        status_label.pack(anchor='w')
        setattr(self, f'{prefix}_profile_status', status_label)

        subframes = {'catalog': catalog_frame, 'custom_ibeam': custom_ibeam_frame,
                     'channel_catalog': channel_catalog_frame, 'channel_custom': channel_custom_frame,
                     'custom_profile': custom_profile_frame}

        def on_kind_change(event=None):
            for f in subframes.values():
                f.pack_forget()
            subframes[DP_BASE_KIND_BY_LABEL[kind_var.get()]].pack(fill='x', pady=2)

        combo.bind('<<ComboboxSelected>>', on_kind_change)
        setattr(self, f'{prefix}_on_kind_change', on_kind_change)
        on_kind_change()

        rotate_var, mirror_var = self._build_orientation_row(parent)
        setattr(self, f'{prefix}_rotate90_var', rotate_var)
        setattr(self, f'{prefix}_mirror_var', mirror_var)

    def _on_section_mode_change(self):
        mode = SECTION_MODE_BY_LABEL[self.section_mode_var.get()]
        frames = {'catalog': self.catalog_frame, 'custom_ibeam': self.custom_ibeam_frame,
                  'double_channel': self.double_channel_frame,
                  'double_profile': self.double_profile_frame,
                  'compound': self.compound_frame,
                  'custom_profile': self.custom_profile_frame}
        for frame in frames.values():
            frame.pack_forget()
        if mode in frames:
            frames[mode].pack(fill='x', padx=4, pady=2)

    # ── compound weld list ──────────────────────────────────────────────
    def _mirror_a_into_b(self):
        """Build Profile B as the mirror image of Profile A.

        The box girder -- and most built-up sections worth drawing -- is
        symmetric, so drawing the second half by hand is duplicated work
        and a second chance to mistype a coordinate. Mirroring is done on
        the SKETCH, so B arrives editable rather than as a frozen point
        list, and B's offset is set so the two profiles meet edge to edge.
        """
        sketch = getattr(self, 'cp_a_custom_profile_sketch', None)
        if sketch is None:
            messagebox.showinfo(
                'Mirror A into B',
                'Profile A is not a drawn profile yet. Set its Kind to "Custom drawn '
                'profile", draw it, then press this to build B from it.')
            return
        try:
            mirrored = secm.mirror_sketch(sketch, horizontal=True)
            sec_b = mirrored.to_section('custom')
            sec_a = sketch.to_section('custom')
        except ValueError as ex:
            messagebox.showerror('Mirror A into B', str(ex))
            return

        self.cp_b_custom_profile_sketch = mirrored
        self.cp_b_custom_profile_section = sec_b
        self.cp_b_base_kind_var.set(DP_BASE_LABEL_BY_KIND['custom_profile'])
        self.cp_b_on_kind_change()
        status = getattr(self, 'cp_b_profile_status', None)
        if status is not None:
            status.configure(text=f'A={sec_b.A:.0f} mm^2, I={sec_b.I:.3g} mm^4 '
                                   f'(mirror of A)', fg='#2e9e4f')

        # Place them so A's right edge meets B's left edge. PlacedProfile
        # positions each piece by its CENTROID, so the offsets are the
        # centroid distances from the shared seam, not the outline extents.
        xs_a = [p[0] for p in sketch.outline_points()]
        width = max(xs_a) - min(xs_a)
        cxa = sec_a.centroid[0]
        # A occupies [0, width], its centroid sitting (cxa - min) from its
        # left edge. B is A reflected, so the same distance measures from
        # B's RIGHT edge -- which is why B's offset is the width mirrored
        # rather than the same number shifted along.
        dx_a = cxa - min(xs_a)
        dx_b = 2.0 * width - (cxa - min(xs_a))
        self.compound_offsets['cp_a'] = (dx_a, sec_a.centroid[1])
        self.compound_offsets['cp_b'] = (dx_b, sec_b.centroid[1])
        for prefix, (dx, dy) in self.compound_offsets.items():
            if prefix in self.compound_offset_vars:
                vx, vy = self.compound_offset_vars[prefix]
                vx.set(f'{dx:g}')
                vy.set(f'{dy:g}')
        self._set_results_text(
            f'Profile B built as the mirror of Profile A.\n\n'
            f'Each profile: A={sec_a.A:.0f} mm2, overall width {width:.0f} mm.\n'
            f'Offsets set so the two meet at x={width:.0f} mm '
            f'(total width {2 * width:.0f} mm).\n\n'
            f'Now choose how they are joined, then click Analyze.')

    def _weld_the_seam(self):
        """Put a weld on every line where the two profiles touch.

        The frame is the trap, and it is handled inside `seam_welds`:
        contact runs are found in the CENTROID frame that
        `section_pieces` renders, while `WeldLine` is read in the PLACED
        frame. A weld generated in the wrong one lands a centroid-offset
        from its seam -- 179.5 mm on the box girder that prompted this --
        and then reports a comfortable q = 0 rather than an error."""
        try:
            self._apply_widget_state()
            section = self._current_section()
        except Exception as ex:
            messagebox.showerror('Weld the seam', str(ex))
            return
        welds = asmcheck.seam_welds(section)
        if not welds:
            gaps = [g for g in asmcheck.part_gaps(section) if not g.touching]
            if gaps:
                worst = max(g.gap for g in gaps)
                messagebox.showwarning(
                    'Nothing to weld',
                    f'The profiles are not in contact anywhere -- the closest they come '
                    f'is {worst:.2f} mm apart.\n\nThere is no seam to weld until they '
                    f'meet. Adjust dx/dy above.\n\nUntil then every section property '
                    f'this tab reports -- A, I, S, the shear area, and J if you have '
                    f'declared a closed cell -- describes a single piece that does not '
                    f'exist.')
            else:
                messagebox.showinfo(
                    'Nothing to weld',
                    'No contact line long enough to weld was found. This panel joins '
                    'the two profiles of a COMPOUND section; a single profile has no '
                    'seam.')
            return
        self.compound_welds = [w for w in self.compound_welds
                               if not str(w.label or '').startswith('SEAM')]
        self.compound_welds.extend(welds)
        self._refresh_compound_weld_list()
        total = sum(w.length for w in welds)
        messagebox.showinfo(
            'Seam welded',
            f'{len(welds)} seam(s) found, {total:.0f} mm of contact in the cross-section.'
            '\n\nPress Analyze: the report sizes each one, measures the plate '
            'thicknesses at the line for the Tabla J.2.4 minimum, and says which of '
            'strength or that minimum governs.')

    def _add_compound_weld(self):
        try:
            v = {k: float(var.get() or 0.0) for k, var in self.cw_vars.items()}
            weld = wsm.WeldLine((v['x1'], v['y1']), (v['x2'], v['y2']),
                                 leg=max(0.0, v['leg']), n_lines=max(1, int(v['n'])),
                                 label=f'CW{len(self.compound_welds) + 1}',
                                 t_thicker=max(0.0, v.get('t_thick', 0.0)),
                                 t_thinner=max(0.0, v.get('t_thin', 0.0)),
                                 flange_to_web=bool(self.cw_flange_web_var.get()))
        except ValueError as ex:
            messagebox.showerror('Add weld', str(ex))
            return
        self.compound_welds.append(weld)
        self._refresh_compound_weld_list()

    def _remove_compound_weld(self):
        sel = self.compound_weld_list.curselection()
        if sel:
            self.compound_welds.pop(sel[0])
            self._refresh_compound_weld_list()

    def _refresh_compound_weld_list(self):
        self.compound_weld_list.delete(0, tk.END)
        for w in self.compound_welds:
            leg = f'{w.leg:g} mm' if w.leg > 0 else 'size me'
            self.compound_weld_list.insert(
                tk.END, f'{w.label}: ({w.p1[0]:.0f},{w.p1[1]:.0f})-'
                        f'({w.p2[0]:.0f},{w.p2[1]:.0f})  {leg} x{w.n_lines}')

    def _opening_ctx(self):
        """What the profile designer needs to preview and set the beam's
        web openings from inside its own window.

        Web openings belong to the BEAM, not to a profile, so this is a
        callback into the tab rather than anything the sketch carries. It
        is passed to every designer this tab opens -- including the two
        base pickers -- because the question 'will a 1.35 m circle fit
        through what I am drawing' is asked while drawing the profile, and
        the tab's own panel cannot answer it."""
        return {
            'count': len(self.openings),
            'apply': self._openings_from_designer,
        }

    def _openings_from_designer(self, dia, spacing, xstart, n):
        self.openings = pbm.uniform_layout(pbm.opening_circle(dia), int(n),
                                            spacing, xstart)
        # Keep the tab's own panel showing what was just applied, so the
        # two places that can set openings never disagree on screen.
        self.shape_var.set('Circle')
        self.set_unit_value(self.p1_var, dia)
        self.p2_var.set('')
        self.p3_var.set('')
        self.op_mode.set('Uniform')
        self.n_var.set(int(n))
        self.set_unit_value(self.spacing_var, spacing)
        self.set_unit_value(self.xstart_var, xstart)
        self._refresh_opening_list()

    def _open_profile_designer(self):
        def on_apply(sec, sketch):
            self.custom_profile_section = sec
            self.custom_profile_sketch = sketch
            extra = ''
            if getattr(sketch, 'holes', None):
                extra += f'\n{len(sketch.holes)} hole(s) deducted'
            if getattr(sketch, 'welds', None):
                extra += f'\n{len(sketch.welds)} weld(s) will be checked'
            self.custom_profile_status.configure(
                text=(f'A={sec.A:.0f} mm^2, I={sec.I:.3g} mm^4, d={sec.d:.0f} mm\n'
                      f'S_top={sec.S_top:.3g}, S_bot={sec.S_bot:.3g} mm^3{extra}'),
                fg='#2e9e4f')
        SectionProfileDesigner(self, on_apply=on_apply,
                               existing_sketch=self.custom_profile_sketch,
                               opening_ctx=self._opening_ctx())

    def _open_connector_designer(self):
        try:
            self._apply_widget_state()
            sec = self._current_section()
        except Exception as ex:
            messagebox.showerror('Design connector plates', str(ex))
            return
        if not isinstance(sec, (pbm.BuiltUpDoubleChannelSection, pbm.BuiltUpDoubleSection)):
            messagebox.showinfo('Design connector plates',
                                 'Switch section type to "Double channel (built-up)" or '
                                 '"Double profile (any base, built-up)" first.')
            return
        try:
            sec.enclosed_area  # BuiltUpDoubleSection can raise AttributeError if the base has no width
        except AttributeError as ex:
            messagebox.showerror('Design connector plates', str(ex))
            return
        beam = self._build_beam()
        xs = [i * beam.L / 200 for i in range(201)]
        T_max = max(abs(pbm.global_T(beam, x)) for x in xs)

        win = tk.Toplevel(self)
        win.title('Design connector (tie) plates')
        win.configure(bg='#f5f5f3')
        tk.Label(win, text=f'Governing |T| along the beam: {T_max:.0f} N·mm', bg='#f5f5f3').grid(
            row=0, column=0, columnspan=2, padx=8, pady=(8, 4), sticky='w')
        tk.Label(win, text=f'Enclosed area Am = {sec.enclosed_area:.0f} mm^2, plate span (gap) = {sec.gap:.0f} mm',
                 bg='#f5f5f3', fg='#666', font=('Helvetica', 8)).grid(row=1, column=0, columnspan=2, padx=8, sticky='w')

        tk.Label(win, text='Target spacing (mm):', bg='#f5f5f3').grid(row=2, column=0, padx=8, pady=(8, 2), sticky='w')
        spacing_var = tk.DoubleVar(value=500.0)
        tk.Entry(win, textvariable=spacing_var, width=8).grid(row=2, column=1, padx=8, pady=(8, 2), sticky='w')
        result_label = tk.Label(win, text='', bg='#f5f5f3', justify='left', font=('Courier', 9))
        result_label.grid(row=4, column=0, columnspan=2, padx=8, pady=8, sticky='w')

        def compute_weld():
            try:
                spacing = float(spacing_var.get())
            except (TypeError, ValueError, tk.TclError):
                result_label.configure(text='Enter a valid spacing (mm).')
                return
            r = pbm.design_builtup_connector(sec, T_max, spacing=spacing)
            result_label.configure(text=(
                f"Shear flow q = {r['q']:.2f} N/mm\n"
                f"Required weld force per plate = {r['F_required']:.0f} N\n"
                f"Required 2-sided fillet weld leg = {r['weld_leg_required']:.1f} mm\n"
                f"Plate must span >= {r['plate_span']:.0f} mm (the gap)"))

        def compute_max_spacing():
            r = pbm.design_builtup_connector(sec, T_max, spacing=None)
            result_label.configure(text=(
                f"Shear flow q = {r['q']:.2f} N/mm\n"
                f"With a practical {r['weld_leg_required']:.0f} mm 2-sided fillet weld:\n"
                f"Maximum plate spacing ~= {r['spacing']:.0f} mm\n"
                f"Plate must span >= {r['plate_span']:.0f} mm (the gap)"))

        btns = tk.Frame(win, bg='#f5f5f3'); btns.grid(row=3, column=0, columnspan=2, padx=8, sticky='w')
        tk.Button(btns, text='Required weld for this spacing', relief='flat', bd=0,
                  command=compute_weld).pack(side='left', padx=2)
        tk.Button(btns, text='Max spacing for min. weld', relief='flat', bd=0,
                  command=compute_max_spacing).pack(side='left', padx=2)

    def _build_opening_panel(self, parent):
        box = tk.LabelFrame(parent, text='Web openings', bg='#f5f5f3', font=('Helvetica', 9, 'bold'))
        box.pack(fill='x', pady=(0, 6))

        self.op_mode = tk.StringVar(value='Uniform')
        modes = tk.Frame(box, bg='#f5f5f3'); modes.pack(fill='x', padx=4)
        tk.Radiobutton(modes, text='Uniform', variable=self.op_mode, value='Uniform',
                        bg='#f5f5f3').pack(side='left')
        tk.Radiobutton(modes, text='Variable', variable=self.op_mode, value='Variable',
                        bg='#f5f5f3').pack(side='left')

        shp = tk.Frame(box, bg='#f5f5f3'); shp.pack(fill='x', padx=4, pady=2)
        tk.Label(shp, text='Shape:', bg='#f5f5f3').pack(side='left')
        self.shape_var = tk.StringVar(value='Circle')
        ttk.Combobox(shp, textvariable=self.shape_var, values=SHAPE_TYPES, width=14,
                     state='readonly').pack(side='left', padx=4)

        dims = tk.Frame(box, bg='#f5f5f3'); dims.pack(fill='x', padx=4)
        self.p1_var = tk.StringVar(value='250')
        self.p2_var = tk.StringVar(value='')
        self.p3_var = tk.StringVar(value='')
        for nm, v in (('p1', self.p1_var), ('p2', self.p2_var), ('p3', self.p3_var)):
            self.unit_label(tk.Label(dims, bg='#f5f5f3'),
                            (lambda t=nm: f'{t} ({self.u("detail_length")}):')).pack(side='left')
            self.unit_var(v, 'detail_length')
            tk.Entry(dims, textvariable=v, width=6).pack(side='left')
        tk.Label(box, text='Circle: p1=diameter. Hexagon: p1=width,p2=height,p3=flat (opt). '
                            'Rectangle: p1=width,p2=height.', bg='#f5f5f3', fg='#888',
                 font=('Helvetica', 8), wraplength=PANEL_W).pack(anchor='w', padx=4)

        poly_row = tk.Frame(box, bg='#f5f5f3'); poly_row.pack(fill='x', padx=4)
        tk.Label(poly_row, text='Custom polygon (x,y; x,y; ...):', bg='#f5f5f3', fg='#888',
                 font=('Helvetica', 8)).pack(anchor='w')
        self.poly_var = tk.StringVar(value='')
        tk.Entry(poly_row, textvariable=self.poly_var, width=30).pack(fill='x')

        uni = tk.Frame(box, bg='#f5f5f3'); uni.pack(fill='x', padx=4, pady=2)
        tk.Label(uni, text='n:', bg='#f5f5f3').pack(side='left')
        self.n_var = tk.IntVar(value=6)
        tk.Entry(uni, textvariable=self.n_var, width=4).pack(side='left')
        self.unit_label(tk.Label(uni, bg='#f5f5f3'),
                        lambda: f'spacing ({self.u("detail_length")}):').pack(side='left')
        self.spacing_var = self.unit_var(tk.DoubleVar(value=600.0), 'detail_length')
        tk.Entry(uni, textvariable=self.spacing_var, width=6).pack(side='left')
        self.unit_label(tk.Label(uni, bg='#f5f5f3'),
                        lambda: f'x start ({self.u("length")}):').pack(side='left')
        self.xstart_var = self.unit_var(tk.DoubleVar(value=1000.0), 'length')
        tk.Entry(uni, textvariable=self.xstart_var, width=6).pack(side='left')

        var_row = tk.Frame(box, bg='#f5f5f3'); var_row.pack(fill='x', padx=4)
        self.unit_label(tk.Label(var_row, bg='#f5f5f3'),
                        lambda: f'x_center ({self.u("length")}, variable mode):'
                        ).pack(side='left')
        self.xc_var = self.unit_var(tk.DoubleVar(value=1000.0), 'length')
        tk.Entry(var_row, textvariable=self.xc_var, width=7).pack(side='left', padx=4)

        btns = tk.Frame(box, bg='#f5f5f3'); btns.pack(fill='x', padx=4, pady=2)
        tk.Button(btns, text='Generate / Add', relief='flat', bd=0, padx=6,
                  command=self._add_opening).pack(side='left', padx=2)
        tk.Button(btns, text='Remove selected', relief='flat', bd=0, padx=6,
                  command=self._remove_opening).pack(side='left', padx=2)
        tk.Button(btns, text='Clear openings', relief='flat', bd=0, padx=6,
                  command=self._clear_openings).pack(side='left', padx=2)

        ttk.Separator(box, orient='horizontal').pack(fill='x', padx=4, pady=3)
        vm = tk.Frame(box, bg='#f5f5f3'); vm.pack(fill='x', padx=4)
        tk.Label(vm, text='Vierendeel method:', bg='#f5f5f3').pack(side='left')
        self.vier_method_var = tk.StringVar(value=VIER_STATION)
        ttk.Combobox(vm, textvariable=self.vier_method_var,
                     values=[VIER_STATION, VIER_HAND], width=22,
                     state='readonly').pack(side='left', padx=4)
        tk.Label(box, text='"Station scan" checks nine stations across each hole against '
                           'the real net section there. "Hand method" is the closed form '
                           'most written calculations use: the tee depth at the hole '
                           'centre paired with a lever of half the opening width, and the '
                           'flange left out of the local modulus. On a CIRCLE the hand '
                           'method runs about 4x higher, because those two never happen at '
                           'the same place. Both are reported whichever you pick.',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_W).pack(anchor='w', padx=4)

        rr = tk.Frame(box, bg='#f5f5f3'); rr.pack(fill='x', padx=4)
        self.rings_var = tk.BooleanVar(value=False)
        tk.Checkbutton(rr, text='Size doubler rings for the openings that fail',
                       variable=self.rings_var, bg='#f5f5f3').pack(anchor='w')
        rr2 = tk.Frame(box, bg='#f5f5f3'); rr2.pack(fill='x', padx=4)
        tk.Label(rr2, text='stock plate (mm):', bg='#f5f5f3').pack(side='left')
        self.ring_stock_var = tk.StringVar(value='8, 12, 16, 20, 25, 30, 40')
        tk.Entry(rr2, textvariable=self.ring_stock_var, width=22).pack(side='left', padx=2)
        tk.Label(box, text='A ring is a plate welded on each web around a hole, over the '
                           'height of the tee. It fixes the few openings that fail '
                           'without thickening the web for the whole span. Each required '
                           'thickness is rounded UP to the nearest stock plate listed. '
                           'Sizing every opening takes a few seconds.',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_W).pack(anchor='w', padx=4)

        sketch_row = tk.Frame(box, bg='#f5f5f3'); sketch_row.pack(fill='x', padx=4)
        tk.Button(sketch_row, text='Sketch profile…', relief='flat', bd=0, padx=6,
                  bg='#1a6bbd', fg='white', command=self._open_sketcher).pack(side='left', padx=2, pady=(0, 2))
        tk.Label(sketch_row, text='Draw openings, and place supports, instead of typing dimensions',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8),
                 wraplength=PANEL_W).pack(side='left', padx=4)

        self.opening_list = tk.Listbox(box, height=5)
        self.opening_list.pack(fill='x', padx=4, pady=2)

    def _build_load_panel(self, parent):
        # fill='x', not expand='both': inside the scrolling column there is no
        # leftover vertical space to expand into, and asking for it makes the
        # panel's height depend on layout order rather than on its content.
        box = tk.LabelFrame(parent, text='Loads', bg='#f5f5f3', font=('Helvetica', 9, 'bold'))
        box.pack(fill='x', pady=(0, 6))

        cmb = tk.Frame(box, bg='#f5f5f3'); cmb.pack(fill='x', padx=4, pady=2)
        tk.Label(cmb, text='Combination:', bg='#f5f5f3').pack(side='left')
        self.combo_var = tk.StringVar(value=loadcomb.DEFAULT.label)
        ttk.Combobox(cmb, textvariable=self.combo_var,
                     values=[c.label for c in loadcomb.COMBINATIONS], width=24,
                     state='readonly').pack(side='left', padx=4)
        tk.Label(box, text='The loads below are SERVICE actions when a factored '
                           'combination is chosen; the factors are applied for you. '
                           'Leave it "As entered" if you have already factored them '
                           'yourself. ASD compares against Rn/Omega instead of phi*Rn.',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_W).pack(anchor='w', padx=4)

        row = tk.Frame(box, bg='#f5f5f3'); row.pack(fill='x', padx=4, pady=2)
        tk.Label(row, text='Type:', bg='#f5f5f3').pack(side='left')
        self.load_type_var = tk.StringVar(value='Point load')
        ttk.Combobox(row, textvariable=self.load_type_var,
                     values=['Point load', 'Point moment', 'Point torque',
                             'Distributed load', 'Distributed torque'],
                     width=15, state='readonly').pack(side='left', padx=4)
        self.load_type_var.trace_add('write', lambda *_: self._on_load_type_change())

        f1 = tk.Frame(box, bg='#f5f5f3'); f1.pack(fill='x', padx=4)
        self.unit_label(tk.Label(f1, bg='#f5f5f3'),
                        lambda: f'x1 ({self.u("length")}):').pack(side='left')
        self.lx1_var = self.unit_var(tk.DoubleVar(value=self.length / 2.0), 'length')
        tk.Entry(f1, textvariable=self.lx1_var, width=7).pack(side='left')
        self.unit_label(tk.Label(f1, bg='#f5f5f3'),
                        lambda: f'x2 ({self.u("length")}, dist. only):').pack(side='left')
        self.lx2_var = self.unit_var(tk.StringVar(value=''), 'length')
        tk.Entry(f1, textvariable=self.lx2_var, width=7).pack(side='left')

        # v1 and v2 are whatever the chosen load TYPE makes them -- a force, a
        # moment, or a force per unit length -- so their unit is looked up from
        # the type rather than fixed, and the box is rewritten when either the
        # type or the convention changes.
        f2 = tk.Frame(box, bg='#f5f5f3'); f2.pack(fill='x', padx=4)
        self.lv1_label = self.unit_label(tk.Label(f2, bg='#f5f5f3'),
                                          lambda: f'v1 ({self._load_unit()}):')
        self.lv1_label.pack(side='left')
        self.lv1_var = tk.DoubleVar(value=self.show('force', 10000.0))
        # Which convention v1/v2 are currently WRITTEN in, so the next switch
        # converts from the right one rather than assuming storage units.
        self._load_entry_shown_in = units.current()
        tk.Entry(f2, textvariable=self.lv1_var, width=8).pack(side='left')

        f3 = tk.Frame(box, bg='#f5f5f3'); f3.pack(fill='x', padx=4)
        self.lv2_label = self.unit_label(
            tk.Label(f3, bg='#f5f5f3'),
            lambda: f'v2 ({self._load_unit()}, dist. only, blank=v1):')
        self.lv2_label.pack(side='left')
        self.lv2_var = tk.StringVar(value='')
        tk.Entry(f3, textvariable=self.lv2_var, width=8).pack(side='left')

        f4 = tk.Frame(box, bg='#f5f5f3'); f4.pack(fill='x', padx=4)
        self.unit_label(tk.Label(f4, bg='#f5f5f3'),
                        lambda: f'eccentricity e ({self.u("detail_length")}, '
                                f'load cases only):').pack(side='left')
        self.le_var = self.unit_var(tk.DoubleVar(value=0.0), 'detail_length')
        tk.Entry(f4, textvariable=self.le_var, width=6).pack(side='left')

        f5 = tk.Frame(box, bg='#f5f5f3'); f5.pack(fill='x', padx=4)
        tk.Label(f5, text='case:', bg='#f5f5f3').pack(side='left')
        self.load_case_var = tk.StringVar(value=loadcomb.DEFAULT_CASE)
        for case in loadcomb.CASES:
            tk.Radiobutton(f5, text=loadcomb.CASE_LABELS[case], variable=self.load_case_var,
                           value=case, bg='#f5f5f3').pack(side='left')

        btns = tk.Frame(box, bg='#f5f5f3'); btns.pack(fill='x', padx=4, pady=2)
        tk.Button(btns, text='Add load', relief='flat', bd=0, padx=6,
                  command=self._add_load).pack(side='left', padx=2)
        tk.Button(btns, text='Remove selected', relief='flat', bd=0, padx=6,
                  command=self._remove_load).pack(side='left', padx=2)

        self.load_list = tk.Listbox(box, height=6)
        self.load_list.pack(fill='x', padx=4, pady=2)

    # ── opening/load list handlers ───────────────────────────────────────
    def _shape_vertices_from_ui(self):
        p1 = self.unit_value(self.p1_var) if self.p1_var.get() else 0.0
        p2 = self.unit_value(self.p2_var) if self.p2_var.get() else 0.0
        p3 = self.unit_value(self.p3_var) if self.p3_var.get() else 0.0
        return _shape_vertices(self.shape_var.get(), p1, p2, p3, self.poly_var.get())

    def _add_opening(self):
        try:
            verts = self._shape_vertices_from_ui()
            if self.op_mode.get() == 'Uniform':
                self.openings = pbm.uniform_layout(verts, int(self.n_var.get()),
                                                    self.unit_value(self.spacing_var),
                                                    self.unit_value(self.xstart_var))
            else:
                self.openings.append(pbm.OpeningInstance(self.unit_value(self.xc_var), verts,
                                                           label=f'H{len(self.openings) + 1}'))
        except Exception as ex:
            messagebox.showerror('Opening error', str(ex))
            return
        self._refresh_opening_list()

    def _refresh_opening_list(self):
        self.opening_list.delete(0, 'end')
        l_ = lambda v: self.show('length', v)
        for op in sorted(self.openings, key=lambda o: o.x_center):
            x0, x1 = op.x_span()
            self.opening_list.insert('end',
                f'{op.label}  x_center={l_(op.x_center):.3g}  '
                f'extent=[{l_(x0):.3g},{l_(x1):.3g}] {self.u("length")}')

    def _remove_opening(self):
        sel = self.opening_list.curselection()
        if not sel:
            return
        ordered = sorted(self.openings, key=lambda o: o.x_center)
        del ordered[sel[0]]
        self.openings = ordered
        self._refresh_opening_list()

    def _clear_openings(self):
        self.openings = []
        self._refresh_opening_list()

    def _open_sketcher(self):
        try:
            self._apply_widget_state()
            length = self.unit_value(self.len_var, self.length)
            sec = self._current_section()
        except Exception as ex:
            messagebox.showerror('Sketch profile', f'Fix the beam length/section first: {ex}')
            return
        if not isinstance(sec, pbm.RolledSection):
            messagebox.showinfo('Sketch profile',
                                 'Web openings (perforations) are only supported for a Rolled I/W section '
                                 '-- switch Section type back to catalog or custom rolled dimensions first.')
            return
        ProfileSketcher(self, length=length, section_depth=sec.d,
                         existing_openings=list(self.openings),
                         existing_supports=self.supports,
                         on_apply=self._apply_sketch_openings)

    def _apply_sketch_openings(self, openings, supports):
        """Callback from ProfileSketcher.Apply: replaces the current
        opening set with whatever was sketched (the sketcher is seeded
        with the existing openings, so this is an edit, not an append),
        and updates the support positions the same way."""
        self.openings = openings
        self.supports = supports
        self._refresh_opening_list()
        self._update_support_status()

    def _update_support_status(self):
        if self.support_specs:
            try:
                specs = [hym.SupportSpec(s['x'], s['kind'], s['torsion'])
                         for s in self.support_specs]
                # The same validation the solver would run, so a mechanism
                # is caught here, in the panel where it can be fixed,
                # rather than at Analyze. Constructing the SupportSpecs
                # alone is not enough: each one is valid on its own, and
                # what makes a lone pin a mechanism is the ARRANGEMENT.
                specs = hym.normalize_supports(specs, self.length)
                n_red = hym.degree_of_indeterminacy(specs)
            except ValueError as ex:
                self.support_status_label.configure(text=f'Support list not valid: {ex}',
                                                     fg='#b03030')
                return
            if n_red > 0:
                desc = f'hyperstatic, {n_red} redundant reaction(s) -- solved by stiffness'
            else:
                desc = 'statically determinate'
            self.support_status_label.configure(
                text=f'{len(specs)} support(s): {desc}', fg='#666')
            return
        xa, xb = self.supports if self.supports else (0.0, self.length)
        overhang_note = ''
        if self.supports and (xa > 1e-6 or xb < self.length - 1e-6):
            overhang_note = '  (overhangs)'
        self.support_status_label.configure(
            text=f'Supports: A = {xa:.0f} mm, B = {xb:.0f} mm{overhang_note}', fg='#666')

    def _add_load(self):
        t = self.load_type_var.get()
        try:
            q = self._LOAD_Q[t]
            ld = {'type': t, 'x1': self.unit_value(self.lx1_var)}
            if t in ('Distributed load', 'Distributed torque'):
                ld['x2'] = self.unit_value(self.lx2_var)
            v1 = self.store(q, float(self.lv1_var.get()))
            ld['v1'] = v1
            if t in ('Distributed load', 'Distributed torque'):
                v2s = self.lv2_var.get()
                ld['v2'] = self.store(q, float(v2s)) if v2s else v1
            if t in ('Point load', 'Distributed load'):
                ld['e'] = self.unit_value(self.le_var)
            ld['case'] = self.load_case_var.get()
        except Exception as ex:
            messagebox.showerror('Load error', str(ex))
            return
        self.loads.append(ld)
        self._refresh_load_list()

    def _refresh_load_list(self):
        self.load_list.delete(0, 'end')
        for ld in self.loads:
            # Each row is written in the unit ITS OWN type implies: a moment
            # row and a point-load row on the same list are different
            # quantities and cannot share one conversion.
            q = self._LOAD_Q.get(ld['type'], 'force')
            ld = dict(ld,
                      x1=self.show('length', ld['x1']),
                      v1=self.show(q, ld['v1']),
                      **({'x2': self.show('length', ld['x2'])} if 'x2' in ld else {}),
                      **({'v2': self.show(q, ld['v2'])} if 'v2' in ld else {}),
                      **({'e': self.show('detail_length', ld['e'])} if ld.get('e') else {}))
            # The case is shown on every row: a load factored 1.6 when it
            # should have been 1.2 is invisible everywhere else, and the
            # list is the only place the whole set can be scanned at once.
            case = f"  [{ld.get('case') or loadcomb.DEFAULT_CASE}]"
            if 'x2' in ld:
                self.load_list.insert('end', f"{ld['type']}  [{ld['x1']:.3g},{ld['x2']:.3g}]  "
                                              f"{ld['v1']:.1f}->{ld['v2']:.1f}{case}")
            else:
                extra = f" e={ld['e']:.3g}" if ld.get('e') else ''
                self.load_list.insert('end', f"{ld['type']}  x={ld['x1']:.3g}  "
                                              f"{ld['v1']:.1f}{extra}{case}")

    def _remove_load(self):
        sel = self.load_list.curselection()
        if not sel:
            return
        del self.loads[sel[0]]
        self._refresh_load_list()

    # ── actions ──────────────────────────────────────────────────────────
    def _clear_all(self):
        self.openings = []
        self.loads = []
        self.supports = None
        self.support_specs = []
        self.compound_welds = []
        self.support_mode_var.set('simple')
        self.advanced_support_frame.pack_forget()
        self._refresh_opening_list()
        self._refresh_load_list()
        self._refresh_support_list()
        self._refresh_compound_weld_list()
        self._update_support_status()
        self._set_results_text('Cleared.')

    def _load_example(self):
        self.length = 8000.0
        self.set_unit_value(self.len_var, self.length)
        self.section_mode_var.set(SECTION_MODES[0][0])  # 'Rolled I/W (catalog)'
        self._on_section_mode_change()
        self.section_var.set('IPE 400')
        for k in self.custom_vars:
            self.custom_vars[k].set('')
        self.openings = pbm.uniform_layout(pbm.opening_circle(250.0), 8, 700.0, 700.0)
        self.supports = None
        self.support_specs = []
        self.support_mode_var.set('simple')
        self.advanced_support_frame.pack_forget()
        self.loads = [{'type': 'Distributed load', 'x1': 0.0, 'x2': self.length, 'v1': 15.0, 'v2': 15.0, 'e': 40.0}]
        self._refresh_opening_list()
        self._refresh_load_list()
        self._refresh_support_list()
        self._update_support_status()
        self._set_results_text('Example loaded (8 x 250 mm circular openings, UDL 15 N/mm with 40 mm '
                                'eccentricity -> a small torque). Click ▶ Analyze.')

    def _apply_widget_state(self):
        self.length = self.unit_value(self.len_var, self.length)
        self.section_name = self.section_var.get()
        self.Fy = self.unit_value(self.fy_var, self.Fy)
        self.E = self.unit_value(self.e_var, self.E)
        try:
            self.Lb = max(0.0, self.unit_value(self.lb_var, 0.0))
            self.Cb = max(1e-3, float(self.cb_var.get() or 1.0))
        except (TypeError, ValueError, tk.TclError):
            pass  # keep the previous values
        self.load_on_top_flange = bool(self.top_flange_load_var.get())
        try:
            raw = self.stiff_var.get().strip()
            self.stiffener_spacing = self.unit_value(self.stiff_var) if raw else None
        except (TypeError, ValueError, tk.TclError):
            self.stiffener_spacing = None

        dvals = {k: v.get() for k, v in self.custom_vars.items()}
        if all(dvals.values()):
            self.custom_section = pbm.RolledSection('custom', float(dvals['d']), float(dvals['bf']),
                                                      float(dvals['tf']), float(dvals['tw']))
        else:
            self.custom_section = None

        self.channel_name = self.channel_var.get()
        cvals = {k: v.get() for k, v in self.custom_channel_vars.items()}
        if all(cvals.values()):
            self.custom_channel = pbm.ChannelSection('custom', float(cvals['h']), float(cvals['bf']),
                                                       float(cvals['tf']), float(cvals['tw']))
        else:
            self.custom_channel = None
        try:
            self.double_channel_width = float(self.double_channel_width_var.get())
        except (TypeError, ValueError, tk.TclError):
            pass  # keep the previous value; _current_section() will surface any real problem

        try:
            self.double_profile_gap = float(self.double_profile_gap_var.get())
        except (TypeError, ValueError, tk.TclError):
            pass

        for prefix, (dx_var, dy_var) in self.compound_offset_vars.items():
            try:
                self.compound_offsets[prefix] = (float(dx_var.get() or 0.0),
                                                  float(dy_var.get() or 0.0))
            except (TypeError, ValueError, tk.TclError):
                pass  # keep the previous offsets; _current_section surfaces real problems

    def _analyze(self):
        try:
            self._apply_widget_state()
            self.combo = loadcomb.combination(self.combo_var.get())
            # The USER'S beam is kept as entered; the analysed beam is a
            # factored copy. Scaling in place would compound on the next
            # press of Analyze, and nothing on screen would say so.
            self.service_beam = self._build_beam()
            beam = loadcomb.apply(self.service_beam, self.combo)
            self.report = pbm.analyze_beam(beam)
        except Exception as ex:
            messagebox.showerror('Analysis error', str(ex))
            return
        self._render_report(beam)
        # Drawings last: a view that fails must not lose you the report.
        try:
            self.views.set_model(beam, self.report)
        except Exception as ex:
            self.result_text.insert('end', f'\n\n(views could not be drawn: {ex})')

    def _render_report(self, beam):
        r = self.report
        lines = []
        code = r.get('code')
        if code is not None:
            lines.append(f'DESIGN BASIS: {code.citation}')
            lines.extend(loadcomb.summarise(getattr(self, 'service_beam', beam),
                                            self._combo()))
            if not self._combo().is_factored and not self._combo().asd:
                lines.append('Demands come from the loads as entered -- it remains your '
                              'responsibility that they are FACTORED actions per '
                              'CIRSOC 101/102.')
            lines.append('')
        lines.append(f'Beam L={_m(beam.L)}, section={beam.section.name}, '
                      f'Fy={beam.material.Fy:.0f} MPa')

        if beam.support_specs:
            n_red = r.get('indeterminacy', 0)
            if n_red > 0:
                lines.append(f'Supports: {len(beam.support_specs)} -- HYPERSTATIC, {n_red} '
                              'redundant reaction(s), solved by the stiffness method with the '
                              'netted I(x) of the openings included.')
            else:
                lines.append(f'Supports: {len(beam.support_specs)} -- statically determinate.')
            lines.append('Reactions (R positive UP; M is the INTERNAL bending moment at the')
            lines.append('support, sagging positive -- so a built-in end reads negative):')
            for x, R_up, _M_ccw in r['support_reactions']:
                spec = min(beam.support_specs, key=lambda s: abs(s.x - x))
                kind = 'fixed' if spec.restrains_rotation else 'pin/roller'
                couple = ''
                if spec.restrains_rotation:
                    couple = f', M={self._support_moment(beam, x):+.4g} N.mm'
                lines.append(f'    x={_m(x):>10s}  ({kind:<10}) R={R_up:+12.1f} N{couple}')
        else:
            xA, xB = beam.supports
            R0, RL = r['reactions']
            overhang_note = '' if (xA == 0.0 and xB == beam.L) else '  (overhanging beam)'
            lines.append(f'Supports: A at x={_m(xA)}, B at x={_m(xB)}{overhang_note}')
            lines.append(f'Reactions: RA={R0:.1f} N, RB={RL:.1f} N')

        detail = getattr(beam.section, 'detail', None)
        if detail is not None:
            lines.append(f'Assembly: {detail.describe()}')
            try:
                lines.append(f'          t={detail.plate_thickness:g} mm, '
                              f'J={beam.section.J:.4g} mm^4, '
                              f'Aweb={beam.section.Aweb:.4g} mm^2')
            except AttributeError as ex:
                lines.append(f'          {ex}')

        # Before any capacity is quoted: do the parts of this section even
        # touch? Every number above assumes they act as one piece.
        try:
            audit = asmcheck.audit(beam.section, detail=detail)
        except Exception:
            audit = []
        if audit:
            lines.append('')
            lines.extend(audit)

        self._append_member_report(lines, r)
        self._append_weld_report(lines, beam)

        self._append_vierendeel_report(lines, beam, r)
        lines.append('')
        lines.append('--- Web-post shear/buckling between adjacent openings ---')
        if not r['webposts']:
            lines.append('(no web openings on this beam)')
        for wp in r['webposts']:
            flag = '  <<< GOVERNS' if wp is r['governing_webpost'] else ''
            lines.append(f'[{_m(wp.x_left)} - {_m(wp.x_right)}] width={wp.width:.0f} mm, '
                          f'tau_demand={wp.tau_demand:.1f} MPa, Fcr={wp.Fcr:.1f} MPa, util={wp.util:.2f}{flag}')
            if wp.warning:
                lines.append(f'    WARNING: {wp.warning}')
        lines.append('')
        c = r['combined']
        lines.append('--- Combined bending + torsion check (at Vierendeel-governing station) ---')
        lines.append(f'x={_m(c.x)}: sigma_bending={c.sigma_bending:.1f} MPa, '
                      f'tau_shear={c.tau_shear:.1f} MPa, tau_torsion={c.tau_torsion:.1f} MPa, util={c.util:.2f}')
        if c.doubler_t > 0:
            lines.append(f'Reinforcement required: web doubler plate t={c.doubler_t:.0f} mm ({c.note})')
        else:
            lines.append(f'No reinforcement required ({c.note})')
        self._append_ring_report(lines, beam)
        self._set_results_text('\n'.join(lines))

    def _combo(self):
        """The combination in force. Read from the widget rather than
        stored, so a report rendered without a preceding Analyze -- which
        the tests do -- still agrees with what is on screen."""
        return getattr(self, 'combo', None) or loadcomb.combination(
            getattr(self, 'combo_var', None) and self.combo_var.get())

    def _vier_method(self):
        label = getattr(self, 'vier_method_var', None)
        return VIER_KEY.get(label.get() if label else VIER_STATION, 'station')

    def _append_vierendeel_report(self, lines, beam, r):
        """The Vierendeel block, with BOTH methods on the page.

        Whichever is selected governs the ring schedule and the verdict;
        the other is printed as a single comparison line. Two documents
        that disagree by 4x are impossible to reconcile if each shows only
        its own number, and this check is the one place this tab and every
        hand calculation of a cellular beam part company."""
        combo = self._combo()
        k = combo.util_ratio
        method = self._vier_method()
        lines.append('')
        title = ('--- Vierendeel check per opening (CIRSOC H.3.3, governing station) ---'
                 if method == 'station' else
                 '--- Vierendeel check per opening (hand method, closed form) ---')
        lines.append(title)
        if not r['openings']:
            lines.append('(no web openings on this beam)')

        hand = {}
        try:
            for h in vhand.check_all(beam):
                hand[h.opening.label] = h
        except Exception:
            hand = {}

        if method == 'hand':
            worst = None
            for rep in r['openings']:
                op = rep['opening']
                h = hand.get(op.label)
                if h is None:
                    continue
                if worst is None or h.util > worst.util:
                    worst = h
            for rep in r['openings']:
                op = rep['opening']
                h = hand.get(op.label)
                if h is None:
                    lines.append(f'{op.label}: the hand method needs a tee above and below '
                                 'the hole; this opening leaves none')
                    continue
                flag = '  <<< GOVERNS' if h is worst else ''
                lines.append(f'{op.label} (x_center={_m(op.x_center)}): '
                             f'f_ax={h.f_ax:.1f} + f_loc={h.f_loc:.1f} MPa, '
                             f'util={h.util * k:.2f}{flag}')
            if worst is not None:
                lines.append('')
                lines.append(f'Worst opening, worked through ({worst.opening.label} at '
                             f'{worst.opening.x_center / 1000.0:.1f} m):')
                for line in worst.working():
                    lines.append(line)
                st = r.get('governing_opening')
                if st and st.get('governing'):
                    u_st = max(st['governing'].util_top, st['governing'].util_bot) * k
                    lines.append(f'  For comparison, the station scan gives {u_st:.2f} on '
                                 f'{st["opening"].label}, {worst.util * k / max(u_st, 1e-9):.1f}x '
                                 'lower -- see the note below.')
        else:
            for rep in r['openings']:
                op = rep['opening']
                g = rep['governing']
                if g is None:
                    lines.append(f'{op.label}: no valid station found '
                                 '(check opening geometry vs. web depth)')
                    continue
                flag = '  <<< GOVERNS' if rep is r['governing_opening'] else ''
                lines.append(f'{op.label} (x_center={_m(op.x_center)}): governing '
                             f'x={_m(g.x)}, util_top={g.util_top * k:.2f}, '
                             f'util_bot={g.util_bot * k:.2f}{flag}')
            worst_hand = vhand.governing(list(hand.values())) if hand else None
            st = r.get('governing_opening')
            if worst_hand is not None and st and st.get('governing'):
                u_st = max(st['governing'].util_top, st['governing'].util_bot) * k
                lines.append('')
                lines.append(f'The HAND METHOD on the same beam gives {worst_hand.util * k:.2f} '
                             f'at {worst_hand.opening.label} against {u_st:.2f} here, '
                             f'{worst_hand.util * k / max(u_st, 1e-9):.1f}x higher.')

        # The reconciliation note, printed under either method. This is the
        # answer to "why does my hand calculation disagree with this tab",
        # and it belongs on the report rather than in the source.
        deep = any(h.depth_ratio > 0.70 for h in hand.values()) if hand else False
        if hand:
            lines.append('    The two differ because the hand method takes the tee depth at the')
            lines.append('    hole CENTRE and the lever out to the hole EDGE. For a rectangular')
            lines.append('    opening both hold at once. For a circular one they never do: at the')
            lines.append('    centre the lever is zero, at the edge the tee is the full')
            lines.append('    half-depth. It also leaves the flange out of the local modulus.')
            lines.append('    Both simplifications are conservative, so the hand method is a safe')
            lines.append('    upper bound, and the station scan is the more faithful number.')
            if deep:
                lines.append('    NEITHER checks local buckling of the tee, which at these hole')
                lines.append('    depths is very likely what really governs. Treat both as')
                lines.append('    indicative and confirm with a shell model at one opening.')

        # Warnings, deduplicated across the whole beam rather than repeated
        # under every opening. On a uniform layout they are geometric and
        # identical, and 26 openings x 2 warnings was 52 lines saying one
        # thing twice. But a VARIABLE layout can raise a warning for one
        # opening only, and collapsing that to a bare sentence would lose
        # the one fact the reader needs -- so the openings are named
        # whenever the warning does not apply to all of them.
        where = {}
        order = []
        for rep in r['openings']:
            for w in (rep.get('warnings') or []):
                if w not in where:
                    where[w] = []
                    order.append(w)
                where[w].append(rep['opening'].label)
        total = len(r['openings'])
        for w in order:
            who = where[w]
            tag = '' if len(who) >= total else f' [{", ".join(who[:8])}' +                   (f' and {len(who) - 8} more]' if len(who) > 8 else ']')
            lines.append(f'    WARNING:{tag} {w}')

    def _stock_plates(self):
        out = []
        for part in str(self.ring_stock_var.get()).replace(';', ',').split(','):
            part = part.strip()
            if not part:
                continue
            try:
                v = float(part)
            except ValueError:
                continue
            if v > 0:
                out.append(v)
        return sorted(set(out))

    def _append_ring_report(self, lines, beam):
        """The doubler schedule -- which openings need a ring, how thick,
        and what holds it on.

        Off by default because it costs a full re-evaluation of every
        opening at several trial thicknesses, and most beams do not need
        it. When a beam DOES fail at its openings this is the alternative
        to thickening the web over the whole span, so the report says so
        even when the box is unticked."""
        # WHAT COUNTS AS FAILING has to match what the rest of the report
        # just printed, or the schedule contradicts the page above it. Two
        # things bend it:
        #
        #   * the METHOD -- the hand method runs about 4x the station scan
        #     on a circular opening, so it is the difference between "none
        #     of the 26 needs a ring" and a schedule of 19;
        #   * the COMBINATION -- an ASD utilisation is phi*Omega times the
        #     LRFD-form one, so the sizing target is divided by that ratio
        #     rather than the utilisations being multiplied by it. The
        #     search runs in LRFD form throughout and only the threshold
        #     moves, which keeps one number scaled instead of hundreds.
        combo = self._combo()
        method = self._vier_method()
        target = ringmod.TARGET_UTIL / max(combo.util_ratio, 1e-9)
        failing = []
        if method == ringmod.METHOD_HAND:
            try:
                failing = [h.opening for h in vhand.check_all(beam) if h.util > target]
            except Exception:
                failing = []
        else:
            # Read the utilisations off the report rather than recomputing
            # them: analyze_beam has already evaluated every opening, and
            # doing it again doubled the cost of pressing Analyze.
            for rep in (self.report or {}).get('openings', ()):
                g = rep.get('governing')
                if g is not None and max(g.util_top, g.util_bot) > target:
                    failing.append(rep['opening'])
        if not self.rings_var.get():
            if failing:
                lines.append('')
                lines.append(f'{len(failing)} opening(s) exceed util 1.0. Tick "Size '
                             'doubler rings" in the Web openings panel to have the '
                             'required ring thickness worked out for each.')
            return

        lines.append('')
        lines.append('--- Doubler rings at the openings ---')
        lines.append(f'Sized on the {"hand method" if method == ringmod.METHOD_HAND else "station scan"}, '
                     f'{combo.label}.')
        if not beam.openings:
            lines.append('(no web openings on this beam)')
            return
        sched = ringmod.ring_schedule(beam, method=method, target=target)
        stock = self._stock_plates()
        grouped = ringmod.group_schedule(sched, steps=stock) if stock else \
            [(r, r.t_required) for r in sched]

        need = [(r, t) for r, t in grouped if r.needs_ring]
        if not need:
            lines.append(f'None of the {len(sched)} openings needs a ring '
                         '(every one is at or below util 1.0).')
            if method != ringmod.METHOD_HAND:
                lines.append('    That is the STATION SCAN\'s answer. Most written '
                             'calculations use the hand method, which runs about 4x '
                             'higher on a circular opening and will ask for rings '
                             'where this does not. Switch the Vierendeel method in '
                             'the Web openings panel to see that schedule.')
            return

        lines.append(f'{len(need)} of {len(sched)} openings need one. A ring is a plate '
                     'on EACH web, over the full height of the tee above and below the '
                     'hole (SCI P100 practice; slightly conservative where the real '
                     'ring would be narrower than the tee).')
        lines.append('')
        for r, t in need:
            if not r.solved:
                lines.append(f'  {r.describe(combo.util_ratio)}')
                if r.note:
                    lines.append(f'      {r.note}')
                continue
            extra = (f' -> use {t:.0f} mm stock' if t and abs(t - r.t_required) > 0.05
                     else '')
            lines.append(f'  {r.describe(combo.util_ratio)}{extra}')
        lines.append('')
        counts = {}
        for r, t in need:
            if r.solved and t:
                counts[t] = counts.get(t, 0) + 1
        if counts:
            lines.append('Schedule: ' + ', '.join(
                f'{n} x {t:.0f} mm' for t, n in sorted(counts.items())))
        worst = max((r for r, _t in need if r.solved),
                    key=lambda r: r.t_required, default=None)
        if worst is not None:
            t_use = max(t for r, t in need if r.solved and t) if counts else worst.t_required
            w = ringmod.ring_weld_leg(beam, worst.opening, t_use, method=method)
            if w is not None:
                lines.append(f'Perimeter weld (thickest ring): {w.describe()}')
        lines.append('NOTE: the ring plate\'s own local buckling is not checked, nor is '
                     'the practicality of welding a thick doubler to a thin web -- that '
                     'needs a bevel and several passes.')

    @staticmethod
    def _append_member_report(lines, r):
        """Member-level flexure and shear on the GROSS section, CIRSOC
        Chapters F and G. Distinct from the local net-section checks at the
        openings, and reported first because it is the check that decides
        whether the beam is the right size at all."""
        m = r.get('member')
        lines.append('')
        lines.append('--- Member check on the gross section (CIRSOC Cap. F / Cap. G) ---')
        if m is None:
            lines.append('(only evaluated for a rolled I/W section -- Chapter F needs Zx and')
            lines.append(' a compactness class, Chapter G an identifiable web)')
            return
        fx, sh = m.flexure, m.shear
        lines.append(f'Section class: flange {fx.flange_class}, web {fx.web_class} '
                      f'(Tabla B.4.1b)')
        lines.append(f'Flexure : Mu={abs(m.Mu):.4g} N.mm at x={_m(m.x_Mu)}   '
                      f'Md=phi_b*Mn={fx.Md:.4g}   util={m.util_flexure:.2f}')
        lines.append(f'          Mn={fx.Mn:.4g} by {fx.governing}; Mp={fx.Mp:.4g}, '
                      f'Lp={_m(fx.Lp)}, Lr={_m(fx.Lr)}, Lb={_m(fx.Lb)}')
        lines.append(f'Shear   : Vu={abs(m.Vu):.4g} N at x={_m(m.x_Vu)}       '
                      f'Vd=phi_v*Vn={sh.Vd:.4g}   util={m.util_shear:.2f}')
        lines.append(f'          Vn=0.6*Fy*Aw*Cv, Aw={sh.Aw:.0f} mm2, Cv={sh.Cv:.3f} '
                      f'({sh.governing}), h/tw={sh.h_tw:.1f}')
        verdict = 'ADEQUATE' if m.util <= 1.0 else 'OVERSTRESSED'
        lines.append(f'Governing: {m.governing}, util={m.util:.2f}  {verdict}')
        for note in (fx.note, sh.note):
            if note:
                lines.append(f'    NOTE: {note}')

    @staticmethod
    def _support_moment(beam, x):
        """The internal bending moment AT a support -- the number a
        designer sizes the section for.

        Reported instead of the raw reaction couple because the couple is
        only equal to the internal moment at the LEFT end: at the right
        end it is its negative (the diagram has to close to zero past the
        last support), so printing the couple would show a fixed-fixed
        beam under gravity as hogging at one end and sagging at the other.
        Taking the larger-magnitude one-sided limit avoids that, and also
        gives the right answer over an interior support of a continuous
        beam, where the moment peaks exactly at the support."""
        eps = max(beam.L * 1e-4, 1e-6)
        candidates = []
        if x - eps >= 0.0:
            candidates.append(pbm.global_V_M(beam, x - eps)[1])
        if x + eps <= beam.L:
            candidates.append(pbm.global_V_M(beam, x + eps)[1])
        if not candidates:
            return pbm.global_V_M(beam, x)[1]
        return max(candidates, key=abs)

    def _append_weld_report(self, lines, beam):
        """Longitudinal shear-flow check of every weld on a built-up or
        drawn-with-welds section.

        Checked at the station of MAXIMUM |V|, not at the bending-governing
        station: shear flow scales with V, so the weld is worst where the
        shear is worst, and that is generally not where the moment is."""
        sec = beam.section
        welds = getattr(sec, 'welds', None)
        if not welds:
            return
        n = 241
        x_worst, V_worst = 0.0, 0.0
        for i in range(n):
            x = beam.L * i / (n - 1)
            V, _ = pbm.global_V_M(beam, x)
            if abs(V) > abs(V_worst):
                x_worst, V_worst = x, V
        try:
            results = wsm.check_welds(sec, V_worst)
        except ValueError as ex:
            lines.append('')
            lines.append(f'--- Weld check --- could not be run: {ex}')
            return
        code = wsm.DEFAULT_WELD_CODE
        lines.append('')
        lines.append('--- Weld check (longitudinal shear flow q = V*Q/I) ---')
        lines.append(f'Design basis: {code.name} -- phi={code.phi}, Fnw=0.60*Fexx with '
                      f'Fexx={code.Fexx:.0f} MPa,')
        lines.append(f'effective throat 0.707*leg (J.2.2a). Note CIRSOC uses phi=0.60 here, '
                      'not the AISC 0.75.')
        lines.append(f'Checked at x={_m(x_worst)}, where |V| is largest: V={V_worst:+.1f} N')
        governing = wsm.governing_weld(results)
        for res in results:
            flag = '  <<< GOVERNS' if res is governing else ''
            if res.leg_provided > 0:
                verdict = 'OK' if res.ok else 'NOT ADEQUATE'
                lines.append(f'{res.label}: q={res.q:8.1f} N/mm  leg={res.leg_provided:.1f} mm '
                              f'x{res.n_lines}  util={res.util:.2f}  {verdict}{flag}')
            else:
                lines.append(f'{res.label}: q={res.q:8.1f} N/mm  -> {res.leg_required:.2f} mm '
                              f'leg on strength alone, x{res.n_lines}{flag}')
            lines.append(f'    Q={res.Q:.4g} mm^3 from A_held={res.A_held:.0f} mm^2; {res.note}')
            if res.leg_min_code > 0:
                src = 'measured' if res.t_measured else 'stated'
                lines.append(f'    Tabla J.2.4 minimum leg for a {res.t_thicker:.0f} mm '
                              f'part ({src}): {res.leg_min_code:.0f} mm; J.2.2(b) maximum '
                              f'on the {res.t_thinner:.0f} mm edge: {res.leg_max_code:.1f} mm')
                lines.append(f'    SPECIFY {res.leg_to_specify:.1f} mm -- governed by '
                              f'{res.size_governed_by}')
            if res.size_warning:
                lines.append(f'    NOTE: {res.size_warning}')
        lines.append('    Not covered: base-metal rupture at the fusion face (CIRSOC J.4),')
        lines.append('    intermittent-weld spacing, or transverse/eccentric weld-group effects.')

    # Which physical quantity each load type's magnitude is. A distributed
    # torque is a torque per unit length, N*mm/mm, which is dimensionally a
    # force -- so it converts as one.
    _LOAD_Q = {'Point load': 'force', 'Point moment': 'moment',
               'Point torque': 'moment', 'Distributed load': 'line_load',
               'Distributed torque': 'force'}

    def _load_unit(self):
        return self.u(self._LOAD_Q.get(self.load_type_var.get(), 'force'))

    def _on_load_type_change(self):
        """Relabel v1/v2 when the load type changes.

        The number in the box has not moved, but what it MEANS has, so only
        the unit beside it follows. Converting the number too would silently
        turn a 10 kN point load into a 10 kN.m moment of a different size.
        """
        for widget, build, option in list(getattr(self, '_unit_labels', ())):
            if widget in (getattr(self, 'lv1_label', None),
                           getattr(self, 'lv2_label', None)):
                try:
                    widget.config(**{option: build()})
                except tk.TclError:
                    pass

    def _on_units_changed(self):
        """Repaint the lists and, if there is a report, write it again.

        Re-running `_analyze` would be wrong as well as slow: it would fold in
        any edit made since, so the report would stop matching the numbers it
        was produced from. The lists are re-rendered from the model instead.
        """
        try:
            self._reexpress_load_entries()
            self._refresh_load_list()
            self._refresh_opening_list()
            self._update_support_status()
            self._on_load_type_change()
        except Exception:
            pass

    def _reexpress_load_entries(self):
        """Rewrite v1 and v2 in the newly selected convention.

        `unit_var` cannot own these: their quantity is whatever the load TYPE
        makes them, so the conversion has to be looked up at the moment it is
        needed rather than fixed when the box was built.
        """
        q = self._LOAD_Q.get(self.load_type_var.get(), 'force')
        was = getattr(self, '_load_entry_shown_in', None) or units.STORAGE
        for var in (self.lv1_var, self.lv2_var):
            raw = str(var.get()).strip()
            if not raw:
                continue
            try:
                var.set(float('%.6g' % units.reexpress(q, float(raw), was,
                                                        units.current())))
            except (ValueError, tk.TclError):
                pass
        self._load_entry_shown_in = units.current()

    def _set_results_text(self, s):
        self.result_text.delete('1.0', 'end')
        self.result_text.insert('1.0', s)

    def _save_report(self):
        if self.report is None:
            messagebox.showwarning('No report', 'Run ▶ Analyze first.')
            return
        path = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Text', '*.txt')])
        if not path:
            return
        with open(path, 'w') as f:
            f.write(self.result_text.get('1.0', 'end'))

    # ── Excel round-trip ────────────────────────────────────
    # The whole model in one file. Every other tab already had this; this
    # one did not, and a cellular beam is the model that costs the most to
    # re-enter -- a drawn profile, a support list, an opening layout and a
    # load set. `pbx` owns the format and the conversions, so both halves
    # below are only the widget side of it.

    def _gather_state(self):
        """Everything the tab currently describes, as a pbx state dict."""
        self._apply_widget_state()
        bases = {}
        for prefix in pbx.BASE_PREFIXES:
            bases[prefix] = {
                'kind': DP_BASE_KIND_BY_LABEL[getattr(self, f'{prefix}_base_kind_var').get()],
                'section': getattr(self, f'{prefix}_section_var').get(),
                'channel': getattr(self, f'{prefix}_channel_var').get(),
                'ibeam': {k: v.get() for k, v in getattr(self, f'{prefix}_custom_vars').items()},
                'channel_dims': {k: v.get() for k, v
                                 in getattr(self, f'{prefix}_custom_channel_vars').items()},
                'rotate90': bool(getattr(self, f'{prefix}_rotate90_var').get()),
                'mirror': bool(getattr(self, f'{prefix}_mirror_var').get()),
                'sketch': pbx.sketch_to_text(
                    getattr(self, f'{prefix}_custom_profile_sketch', None)),
            }
        return {
            'length': self.length, 'Fy': self.Fy, 'E': self.E,
            'Lb': self.Lb, 'Cb': self.Cb,
            'load_on_top_flange': self.load_on_top_flange,
            'stiffener_spacing': self.stiffener_spacing,
            'load_combination': loadcomb.combination(self.combo_var.get()).key,
            'vierendeel_method': self._vier_method(),
            'section_mode': SECTION_MODE_BY_LABEL[self.section_mode_var.get()],
            'catalog': {'section': self.section_var.get(),
                        'rotate90': bool(self.catalog_rotate90_var.get()),
                        'mirror': bool(self.catalog_mirror_var.get())},
            'custom_ibeam': dict(
                {k: v.get() for k, v in self.custom_vars.items()},
                rotate90=bool(self.custom_ibeam_rotate90_var.get()),
                mirror=bool(self.custom_ibeam_mirror_var.get())),
            'double_channel': {'channel': self.channel_name,
                               'overall_width': self.double_channel_width,
                               'custom': {k: v.get() for k, v
                                          in self.custom_channel_vars.items()}},
            'double_profile': {'gap': self.double_profile_gap},
            'bases': bases,
            'compound_offsets': dict(self.compound_offsets),
            'assembly': {'kind': self.assembly_kind_var.get(),
                         'plate_t': float(self.assembly_t_var.get() or 0.0)},
            'compound_welds': list(self.compound_welds),
            'support_mode': self.support_mode_var.get(),
            'supports': self.supports,
            'support_specs': [dict(s) for s in self.support_specs],
            'openings': list(self.openings),
            'loads': [dict(ld) for ld in self.loads],
            'main_sketch': pbx.sketch_to_text(self.custom_profile_sketch),
        }

    def _apply_state(self, st):
        """Push a pbx state dict back into the widgets.

        A drawn profile is rebuilt from its sketch through the same
        `to_section` the designer's Apply uses, so an imported profile and
        a drawn one are the same object by the same route -- there is no
        second way to turn a drawing into a section."""
        self.length = float(st['length'])
        self.set_unit_value(self.len_var, self.length)
        self.Fy, self.E = float(st['Fy']), float(st['E'])
        self.set_unit_value(self.fy_var, self.Fy)
        self.set_unit_value(self.e_var, self.E)
        self.Lb, self.Cb = float(st['Lb']), float(st['Cb'])
        self.set_unit_value(self.lb_var, self.Lb)
        self.cb_var.set(f'{self.Cb:g}')
        self.load_on_top_flange = bool(st['load_on_top_flange'])
        self.top_flange_load_var.set(self.load_on_top_flange)
        self.stiffener_spacing = st.get('stiffener_spacing')
        self.combo_var.set(loadcomb.combination(st.get('load_combination')).label)
        self.vier_method_var.set(VIER_HAND if st.get('vierendeel_method') == 'hand'
                                 else VIER_STATION)
        if self.stiffener_spacing in (None, ''):
            self.stiff_var.set('')
        else:
            self.set_unit_value(self.stiff_var, float(self.stiffener_spacing))

        self.section_mode_var.set(SECTION_MODE_LABEL_BY_KEY.get(
            st['section_mode'], SECTION_MODES[0][0]))
        self._on_section_mode_change()

        cat = st['catalog']
        self.section_name = cat['section']
        self.section_var.set(self.section_name)
        self.catalog_rotate90_var.set(bool(cat['rotate90']))
        self.catalog_mirror_var.set(bool(cat['mirror']))

        ci = st['custom_ibeam']
        for k, var in self.custom_vars.items():
            var.set(ci.get(k, ''))
        self.custom_ibeam_rotate90_var.set(bool(ci.get('rotate90')))
        self.custom_ibeam_mirror_var.set(bool(ci.get('mirror')))

        dc = st['double_channel']
        self.channel_name = dc['channel']
        self.channel_var.set(self.channel_name)
        self.double_channel_width = float(dc['overall_width'])
        self.double_channel_width_var.set(self.double_channel_width)
        for k, var in self.custom_channel_vars.items():
            var.set(dc.get('custom', {}).get(k, ''))

        self.double_profile_gap = float(st['double_profile']['gap'])
        self.double_profile_gap_var.set(self.double_profile_gap)

        for prefix in pbx.BASE_PREFIXES:
            b = st['bases'][prefix]
            getattr(self, f'{prefix}_base_kind_var').set(
                DP_BASE_LABEL_BY_KIND.get(b['kind'], DP_BASE_KINDS[0][0]))
            getattr(self, f'{prefix}_section_var').set(b['section'])
            getattr(self, f'{prefix}_channel_var').set(b['channel'])
            for k, var in getattr(self, f'{prefix}_custom_vars').items():
                var.set(b.get('ibeam', {}).get(k, ''))
            for k, var in getattr(self, f'{prefix}_custom_channel_vars').items():
                var.set(b.get('channel_dims', {}).get(k, ''))
            getattr(self, f'{prefix}_rotate90_var').set(bool(b['rotate90']))
            getattr(self, f'{prefix}_mirror_var').set(bool(b['mirror']))
            self._install_sketch(prefix, b.get('sketch'))
            getattr(self, f'{prefix}_on_kind_change')()

        for prefix, (dx, dy) in st['compound_offsets'].items():
            if prefix in self.compound_offset_vars:
                dx_var, dy_var = self.compound_offset_vars[prefix]
                dx_var.set(f'{float(dx):g}')
                dy_var.set(f'{float(dy):g}')
        self.compound_offsets = {k: (float(v[0]), float(v[1]))
                                 for k, v in st['compound_offsets'].items()}

        self.assembly_kind_var.set(st['assembly']['kind'])
        self.assembly_t_var.set(f"{float(st['assembly']['plate_t']):g}")
        self.compound_welds = list(st['compound_welds'])

        self.supports = tuple(st['supports']) if st['supports'] else None
        self.support_specs = [dict(s) for s in st['support_specs']]
        self.support_mode_var.set(st['support_mode'])
        if st['support_mode'] == 'advanced':
            self.advanced_support_frame.pack(fill='x')
        else:
            self.advanced_support_frame.pack_forget()

        self.openings = list(st['openings'])
        self.loads = [dict(ld) for ld in st['loads']]
        self._install_sketch(None, st.get('main_sketch'))

        self._refresh_opening_list()
        self._refresh_load_list()
        self._refresh_support_list()
        self._refresh_compound_weld_list()
        self._update_support_status()

    def _install_sketch(self, prefix, text):
        """Rebuild one drawn profile from its stored JSON. `prefix` None
        is the tab's own Custom profile; otherwise it is a base picker."""
        status = (self.custom_profile_status if prefix is None
                  else getattr(self, f'{prefix}_profile_status', None))
        if not text:
            if prefix is None:
                self.custom_profile_section = self.custom_profile_sketch = None
            else:
                setattr(self, f'{prefix}_custom_profile_section', None)
                setattr(self, f'{prefix}_custom_profile_sketch', None)
            if status is not None:
                status.configure(text='(no profile designed yet)', fg='#888')
            return
        sec, sketch = pbx.sketch_to_section(text)
        if prefix is None:
            self.custom_profile_section, self.custom_profile_sketch = sec, sketch
        else:
            setattr(self, f'{prefix}_custom_profile_section', sec)
            setattr(self, f'{prefix}_custom_profile_sketch', sketch)
        if status is not None:
            extra = ''
            if sketch.holes:
                extra += f', {len(sketch.holes)} hole(s)'
            if sketch.welds:
                extra += f', {len(sketch.welds)} weld(s)'
            status.configure(text=f'A={sec.A:.0f} mm^2, I={sec.I:.3g} mm^4{extra}',
                             fg='#2e9e4f')

    def _export_excel(self):
        if not _ensure_openpyxl():
            messagebox.showerror(
                'Excel export',
                'Could not install openpyxl automatically.\n\n'
                'Install it and try again:\n\n'
                '    pip install openpyxl\n')
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.xlsx', filetypes=[('Excel workbook', '*.xlsx')],
            initialfile='perforated_beam.xlsx', title='Export beam to Excel')
        if not path:
            return
        try:
            state = self._gather_state()
        except Exception as ex:
            messagebox.showerror('Excel export', f'Could not read the current model:\n\n{ex}')
            return
        # The Results sheet is written only from a report that still
        # matches what is on screen. Exporting stale results beside fresh
        # inputs would produce a workbook that disagrees with itself.
        report, beam = self.report, None
        if report is not None:
            try:
                beam = self._build_beam()
            except Exception:
                report = None
        try:
            pbx.export_state(state, path, report=report, beam=beam)
        except Exception as ex:
            messagebox.showerror('Excel export', str(ex))
            return
        messagebox.showinfo(
            'Excel export',
            f'Model written to:\n{path}\n\n'
            + ('With a Results sheet from the last analysis.'
               if report is not None else
               'Inputs only — run ▶ Analyze before exporting to include results.'))

    def _import_excel(self):
        if not _ensure_openpyxl():
            messagebox.showerror(
                'Excel import',
                'Could not install openpyxl automatically.\n\n'
                'Install it and try again:\n\n'
                '    pip install openpyxl\n')
            return
        path = filedialog.askopenfilename(
            filetypes=[('Excel workbook', '*.xlsx')], title='Import beam from Excel')
        if not path:
            return
        try:
            state = pbx.import_state(path)
        except Exception as ex:
            messagebox.showerror('Excel import', str(ex))
            return
        # Nothing above this line has touched a widget, so a workbook that
        # fails to read leaves the current model exactly as it was.
        try:
            self._apply_state(state)
        except Exception as ex:
            messagebox.showerror('Excel import',
                                 f'The workbook was read, but could not be applied:\n\n{ex}')
            return
        self.report = None
        self._set_results_text(
            f'Imported from {path}\n\n'
            f'{len(self.openings)} opening(s), {len(self.loads)} load(s), '
            f'span {_m(self.length)}.\n\nClick ▶ Analyze.')
