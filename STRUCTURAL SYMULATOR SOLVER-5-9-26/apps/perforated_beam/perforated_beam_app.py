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

from common import PANEL_W
from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam.profile_sketcher_ui import ProfileSketcher
from apps.perforated_beam.section_profile_ui import SectionProfileDesigner


SHAPE_TYPES = ['Circle', 'Hexagon', 'Rectangle', 'Custom polygon']
SECTION_MODES = [
    ('Rolled I/W (catalog)', 'catalog'),
    ('Rolled I/W (custom dims)', 'custom_ibeam'),
    ('Double channel (built-up)', 'double_channel'),
    ('Double profile (any base, built-up)', 'double_profile'),
    ('Custom profile (drawn)', 'custom_profile'),
]
SECTION_MODE_BY_LABEL = dict(SECTION_MODES)

DP_BASE_KINDS = [
    ('Rolled I/W (catalog)', 'catalog'),
    ('Rolled I/W (custom dims)', 'custom_ibeam'),
    ('Channel (catalog)', 'channel_catalog'),
    ('Channel (custom dims)', 'channel_custom'),
    ('Custom drawn profile', 'custom_profile'),
]
DP_BASE_KIND_BY_LABEL = dict(DP_BASE_KINDS)


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


class PerforatedBeamApp(tk.Frame):
    """
    Perforated Beam tab — Vierendeel moment, web-post buckling, and combined
    bending+torsion reinforcement sizing for long-span beams with an
    arbitrary number/distribution of web openings.
    Units: mm, N, MPa (=N/mm^2), N*mm.
    """

    def __init__(self, master, **kw):
        super().__init__(master, bg='#f5f5f3', **kw)
        self.length = 8000.0
        self.section_name = 'IPE 400'
        self.custom_section = None   # RolledSection or None -> use catalog
        self.channel_name = 'UPN 220'
        self.custom_channel = None   # ChannelSection or None -> use channel catalog
        self.double_channel_width = 350.0
        self.double_profile_gap = 200.0
        self.custom_profile_section = None  # CustomProfileSection or None, from the profile designer
        self.Fy = 250.0
        self.E = 200000.0
        self.openings = []           # list of OpeningInstance
        self.supports = None         # (xA, xB) or None -> defaults to (0, L), i.e. supports at both ends
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
        if mode == 'custom_profile':
            if self.custom_profile_section is None:
                raise ValueError('Design a custom profile first (see "Design profile…" button).')
            return self.custom_profile_section
        raise ValueError(f'unknown section mode {mode}')

    def _current_material(self):
        return pbm.Material(Fy=self.Fy, E=self.E)

    def _build_beam(self):
        beam = pbm.BeamConfig(L=self.length, section=self._current_section(),
                               material=self._current_material(), openings=list(self.openings),
                               supports=self.supports)
        for ld in self.loads:
            t = ld['type']
            if t == 'Point load':
                beam.point_loads.append(pbm.PointLoad(ld['x1'], ld['v1'], ld.get('e', 0.0)))
            elif t == 'Point moment':
                beam.point_moments.append(pbm.PointMoment(ld['x1'], ld['v1']))
            elif t == 'Point torque':
                beam.point_torques.append(pbm.PointTorque(ld['x1'], ld['v1']))
            elif t == 'Distributed load':
                beam.dist_loads.append(pbm.DistLoad(ld['x1'], ld['x2'], ld['v1'], ld['v2'], ld.get('e', 0.0)))
            elif t == 'Distributed torque':
                beam.dist_torques.append(pbm.DistTorque(ld['x1'], ld['x2'], ld['v1'], ld['v2']))
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

        main = tk.Frame(self, bg='#f5f5f3')
        main.pack(fill='both', expand=True, padx=6, pady=6)

        left = tk.Frame(main, bg='#f5f5f3', width=PANEL_W + 60)
        left.pack(side='left', fill='y')
        left.pack_propagate(False)

        self._build_beam_panel(left)
        self._build_opening_panel(left)
        self._build_load_panel(left)

        right = tk.Frame(main, bg='#f5f5f3')
        right.pack(side='left', fill='both', expand=True, padx=(8, 0))
        tk.Label(right, text='Results (mm, N, MPa, N·mm)', bg='#f5f5f3',
                 font=('Helvetica', 9, 'bold'), fg='#777').pack(anchor='w')
        text_frame = tk.Frame(right)
        text_frame.pack(fill='both', expand=True)
        sb = tk.Scrollbar(text_frame)
        sb.pack(side='right', fill='y')
        self.result_text = tk.Text(text_frame, wrap='word', font=('Courier', 10), yscrollcommand=sb.set)
        self.result_text.pack(fill='both', expand=True)
        sb.config(command=self.result_text.yview)
        self._set_results_text('Set up the beam, section, openings and loads on the left, then click ▶ Analyze.')

    def _build_beam_panel(self, parent):
        box = tk.LabelFrame(parent, text='Beam & section', bg='#f5f5f3', font=('Helvetica', 9, 'bold'))
        box.pack(fill='x', pady=(0, 6))

        row = tk.Frame(box, bg='#f5f5f3'); row.pack(fill='x', padx=4, pady=2)
        tk.Label(row, text='Length L (mm):', bg='#f5f5f3').pack(side='left')
        self.len_var = tk.DoubleVar(value=self.length)
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

        # -- mode 5: custom drawn profile --
        self.custom_profile_frame = tk.LabelFrame(box, text='Custom profile', bg='#f5f5f3')
        tk.Button(self.custom_profile_frame, text='Design profile…', relief='flat', bd=0, padx=6,
                  bg='#1a6bbd', fg='white', command=self._open_profile_designer).pack(anchor='w', padx=2, pady=4)
        self.custom_profile_status = tk.Label(self.custom_profile_frame, text='(no profile designed yet)',
                                               bg='#f5f5f3', fg='#888', font=('Helvetica', 8), justify='left')
        self.custom_profile_status.pack(anchor='w', padx=2, pady=(0, 4))

        row = tk.Frame(box, bg='#f5f5f3'); row.pack(fill='x', padx=4, pady=2)
        tk.Label(row, text='Fy (MPa):', bg='#f5f5f3').pack(side='left')
        self.fy_var = tk.DoubleVar(value=self.Fy)
        tk.Entry(row, textvariable=self.fy_var, width=7).pack(side='left', padx=4)
        tk.Label(row, text='E (MPa):', bg='#f5f5f3').pack(side='left')
        self.e_var = tk.DoubleVar(value=self.E)
        tk.Entry(row, textvariable=self.e_var, width=8).pack(side='left', padx=4)

        self._on_section_mode_change()

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
            def on_apply(sec, outline):
                setattr(self, f'{prefix}_custom_profile_section', sec)
                status_label.configure(text=f'A={sec.A:.0f} mm^2, I={sec.I:.3g} mm^4', fg='#2e9e4f')
            SectionProfileDesigner(self, on_apply=on_apply)

        tk.Button(custom_profile_frame, text='Design profile…', relief='flat', bd=0,
                  command=open_designer).pack(anchor='w')
        status_label.pack(anchor='w')

        subframes = {'catalog': catalog_frame, 'custom_ibeam': custom_ibeam_frame,
                     'channel_catalog': channel_catalog_frame, 'channel_custom': channel_custom_frame,
                     'custom_profile': custom_profile_frame}

        def on_kind_change(event=None):
            for f in subframes.values():
                f.pack_forget()
            subframes[DP_BASE_KIND_BY_LABEL[kind_var.get()]].pack(fill='x', pady=2)

        combo.bind('<<ComboboxSelected>>', on_kind_change)
        on_kind_change()

        rotate_var, mirror_var = self._build_orientation_row(parent)
        setattr(self, f'{prefix}_rotate90_var', rotate_var)
        setattr(self, f'{prefix}_mirror_var', mirror_var)

    def _on_section_mode_change(self):
        mode = SECTION_MODE_BY_LABEL[self.section_mode_var.get()]
        for frame in (self.catalog_frame, self.custom_ibeam_frame, self.double_channel_frame,
                      self.double_profile_frame, self.custom_profile_frame):
            frame.pack_forget()
        if mode == 'catalog':
            self.catalog_frame.pack(fill='x', padx=4, pady=2)
        elif mode == 'custom_ibeam':
            self.custom_ibeam_frame.pack(fill='x', padx=4, pady=2)
        elif mode == 'double_channel':
            self.double_channel_frame.pack(fill='x', padx=4, pady=2)
        elif mode == 'double_profile':
            self.double_profile_frame.pack(fill='x', padx=4, pady=2)
        elif mode == 'custom_profile':
            self.custom_profile_frame.pack(fill='x', padx=4, pady=2)

    def _open_profile_designer(self):
        def on_apply(sec, outline):
            self.custom_profile_section = sec
            self.custom_profile_status.configure(
                text=(f'A={sec.A:.0f} mm^2, I={sec.I:.3g} mm^4, d={sec.d:.0f} mm\n'
                      f'S_top={sec.S_top:.3g}, S_bot={sec.S_bot:.3g} mm^3'),
                fg='#2e9e4f')
        SectionProfileDesigner(self, on_apply=on_apply)

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
        tk.Label(dims, text='p1:', bg='#f5f5f3').pack(side='left')
        self.p1_var = tk.StringVar(value='250')
        tk.Entry(dims, textvariable=self.p1_var, width=6).pack(side='left')
        tk.Label(dims, text='p2:', bg='#f5f5f3').pack(side='left')
        self.p2_var = tk.StringVar(value='')
        tk.Entry(dims, textvariable=self.p2_var, width=6).pack(side='left')
        tk.Label(dims, text='p3:', bg='#f5f5f3').pack(side='left')
        self.p3_var = tk.StringVar(value='')
        tk.Entry(dims, textvariable=self.p3_var, width=6).pack(side='left')
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
        tk.Label(uni, text='spacing:', bg='#f5f5f3').pack(side='left')
        self.spacing_var = tk.DoubleVar(value=600.0)
        tk.Entry(uni, textvariable=self.spacing_var, width=6).pack(side='left')
        tk.Label(uni, text='x start:', bg='#f5f5f3').pack(side='left')
        self.xstart_var = tk.DoubleVar(value=1000.0)
        tk.Entry(uni, textvariable=self.xstart_var, width=6).pack(side='left')

        var_row = tk.Frame(box, bg='#f5f5f3'); var_row.pack(fill='x', padx=4)
        tk.Label(var_row, text='x_center (variable mode):', bg='#f5f5f3').pack(side='left')
        self.xc_var = tk.DoubleVar(value=1000.0)
        tk.Entry(var_row, textvariable=self.xc_var, width=7).pack(side='left', padx=4)

        btns = tk.Frame(box, bg='#f5f5f3'); btns.pack(fill='x', padx=4, pady=2)
        tk.Button(btns, text='Generate / Add', relief='flat', bd=0, padx=6,
                  command=self._add_opening).pack(side='left', padx=2)
        tk.Button(btns, text='Remove selected', relief='flat', bd=0, padx=6,
                  command=self._remove_opening).pack(side='left', padx=2)
        tk.Button(btns, text='Clear openings', relief='flat', bd=0, padx=6,
                  command=self._clear_openings).pack(side='left', padx=2)

        sketch_row = tk.Frame(box, bg='#f5f5f3'); sketch_row.pack(fill='x', padx=4)
        tk.Button(sketch_row, text='Sketch profile…', relief='flat', bd=0, padx=6,
                  bg='#1a6bbd', fg='white', command=self._open_sketcher).pack(side='left', padx=2, pady=(0, 2))
        tk.Label(sketch_row, text='Draw openings, and place supports, instead of typing dimensions',
                 bg='#f5f5f3', fg='#888', font=('Helvetica', 8),
                 wraplength=PANEL_W).pack(side='left', padx=4)

        self.support_status_label = tk.Label(box, text='', bg='#f5f5f3', fg='#666', font=('Helvetica', 8))
        self.support_status_label.pack(anchor='w', padx=4)
        self._update_support_status()

        self.opening_list = tk.Listbox(box, height=5)
        self.opening_list.pack(fill='x', padx=4, pady=2)

    def _build_load_panel(self, parent):
        box = tk.LabelFrame(parent, text='Loads', bg='#f5f5f3', font=('Helvetica', 9, 'bold'))
        box.pack(fill='both', expand=True, pady=(0, 6))

        row = tk.Frame(box, bg='#f5f5f3'); row.pack(fill='x', padx=4, pady=2)
        tk.Label(row, text='Type:', bg='#f5f5f3').pack(side='left')
        self.load_type_var = tk.StringVar(value='Point load')
        ttk.Combobox(row, textvariable=self.load_type_var,
                     values=['Point load', 'Point moment', 'Point torque',
                             'Distributed load', 'Distributed torque'],
                     width=15, state='readonly').pack(side='left', padx=4)

        f1 = tk.Frame(box, bg='#f5f5f3'); f1.pack(fill='x', padx=4)
        tk.Label(f1, text='x1:', bg='#f5f5f3').pack(side='left')
        self.lx1_var = tk.DoubleVar(value=self.length / 2.0)
        tk.Entry(f1, textvariable=self.lx1_var, width=7).pack(side='left')
        tk.Label(f1, text='x2 (dist. only):', bg='#f5f5f3').pack(side='left')
        self.lx2_var = tk.StringVar(value='')
        tk.Entry(f1, textvariable=self.lx2_var, width=7).pack(side='left')

        f2 = tk.Frame(box, bg='#f5f5f3'); f2.pack(fill='x', padx=4)
        tk.Label(f2, text='v1 (N, N·mm, or N/mm):', bg='#f5f5f3').pack(side='left')
        self.lv1_var = tk.DoubleVar(value=10000.0)
        tk.Entry(f2, textvariable=self.lv1_var, width=8).pack(side='left')

        f3 = tk.Frame(box, bg='#f5f5f3'); f3.pack(fill='x', padx=4)
        tk.Label(f3, text='v2 (dist. only, blank=v1):', bg='#f5f5f3').pack(side='left')
        self.lv2_var = tk.StringVar(value='')
        tk.Entry(f3, textvariable=self.lv2_var, width=8).pack(side='left')

        f4 = tk.Frame(box, bg='#f5f5f3'); f4.pack(fill='x', padx=4)
        tk.Label(f4, text='eccentricity e (mm, load cases only):', bg='#f5f5f3').pack(side='left')
        self.le_var = tk.DoubleVar(value=0.0)
        tk.Entry(f4, textvariable=self.le_var, width=6).pack(side='left')

        btns = tk.Frame(box, bg='#f5f5f3'); btns.pack(fill='x', padx=4, pady=2)
        tk.Button(btns, text='Add load', relief='flat', bd=0, padx=6,
                  command=self._add_load).pack(side='left', padx=2)
        tk.Button(btns, text='Remove selected', relief='flat', bd=0, padx=6,
                  command=self._remove_load).pack(side='left', padx=2)

        self.load_list = tk.Listbox(box, height=6)
        self.load_list.pack(fill='both', expand=True, padx=4, pady=2)

    # ── opening/load list handlers ───────────────────────────────────────
    def _shape_vertices_from_ui(self):
        p1 = float(self.p1_var.get()) if self.p1_var.get() else 0.0
        p2 = float(self.p2_var.get()) if self.p2_var.get() else 0.0
        p3 = float(self.p3_var.get()) if self.p3_var.get() else 0.0
        return _shape_vertices(self.shape_var.get(), p1, p2, p3, self.poly_var.get())

    def _add_opening(self):
        try:
            verts = self._shape_vertices_from_ui()
            if self.op_mode.get() == 'Uniform':
                self.openings = pbm.uniform_layout(verts, int(self.n_var.get()),
                                                    float(self.spacing_var.get()), float(self.xstart_var.get()))
            else:
                self.openings.append(pbm.OpeningInstance(float(self.xc_var.get()), verts,
                                                           label=f'H{len(self.openings) + 1}'))
        except Exception as ex:
            messagebox.showerror('Opening error', str(ex))
            return
        self._refresh_opening_list()

    def _refresh_opening_list(self):
        self.opening_list.delete(0, 'end')
        for op in sorted(self.openings, key=lambda o: o.x_center):
            x0, x1 = op.x_span()
            self.opening_list.insert('end', f'{op.label}  x_center={op.x_center:.0f}  '
                                             f'extent=[{x0:.0f},{x1:.0f}]')

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
            length = float(self.len_var.get())
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
        xa, xb = self.supports if self.supports else (0.0, self.length)
        overhang_note = ''
        if self.supports and (xa > 1e-6 or xb < self.length - 1e-6):
            overhang_note = '  (overhangs)'
        self.support_status_label.configure(text=f'Supports: A = {xa:.0f} mm, B = {xb:.0f} mm{overhang_note}')

    def _add_load(self):
        t = self.load_type_var.get()
        try:
            ld = {'type': t, 'x1': float(self.lx1_var.get())}
            if t in ('Distributed load', 'Distributed torque'):
                ld['x2'] = float(self.lx2_var.get())
            v1 = float(self.lv1_var.get())
            ld['v1'] = v1
            if t in ('Distributed load', 'Distributed torque'):
                v2s = self.lv2_var.get()
                ld['v2'] = float(v2s) if v2s else v1
            if t in ('Point load', 'Distributed load'):
                ld['e'] = float(self.le_var.get())
        except Exception as ex:
            messagebox.showerror('Load error', str(ex))
            return
        self.loads.append(ld)
        self._refresh_load_list()

    def _refresh_load_list(self):
        self.load_list.delete(0, 'end')
        for ld in self.loads:
            if 'x2' in ld:
                self.load_list.insert('end', f"{ld['type']}  [{ld['x1']:.0f},{ld['x2']:.0f}]  "
                                              f"{ld['v1']:.1f}->{ld['v2']:.1f}")
            else:
                extra = f" e={ld['e']:.0f}" if ld.get('e') else ''
                self.load_list.insert('end', f"{ld['type']}  x={ld['x1']:.0f}  {ld['v1']:.1f}{extra}")

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
        self._refresh_opening_list()
        self._refresh_load_list()
        self._update_support_status()
        self._set_results_text('Cleared.')

    def _load_example(self):
        self.length = 8000.0
        self.len_var.set(self.length)
        self.section_mode_var.set(SECTION_MODES[0][0])  # 'Rolled I/W (catalog)'
        self._on_section_mode_change()
        self.section_var.set('IPE 400')
        for k in self.custom_vars:
            self.custom_vars[k].set('')
        self.openings = pbm.uniform_layout(pbm.opening_circle(250.0), 8, 700.0, 700.0)
        self.supports = None
        self.loads = [{'type': 'Distributed load', 'x1': 0.0, 'x2': self.length, 'v1': 15.0, 'v2': 15.0, 'e': 40.0}]
        self._refresh_opening_list()
        self._refresh_load_list()
        self._update_support_status()
        self._set_results_text('Example loaded (8 x 250 mm circular openings, UDL 15 N/mm with 40 mm '
                                'eccentricity -> a small torque). Click ▶ Analyze.')

    def _apply_widget_state(self):
        self.length = float(self.len_var.get())
        self.section_name = self.section_var.get()
        self.Fy = float(self.fy_var.get())
        self.E = float(self.e_var.get())

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

    def _analyze(self):
        try:
            self._apply_widget_state()
            beam = self._build_beam()
            self.report = pbm.analyze_beam(beam)
        except Exception as ex:
            messagebox.showerror('Analysis error', str(ex))
            return
        self._render_report(beam)

    def _render_report(self, beam):
        r = self.report
        lines = []
        R0, RL = r['reactions']
        xA, xB = beam.supports
        lines.append(f'Beam L={beam.L:.0f} mm, section={beam.section.name}, '
                      f'Fy={beam.material.Fy:.0f} MPa')
        overhang_note = '' if (xA == 0.0 and xB == beam.L) else '  (overhanging beam)'
        lines.append(f'Supports: A at x={xA:.0f} mm, B at x={xB:.0f} mm{overhang_note}')
        lines.append(f'Reactions: RA={R0:.1f} N, RB={RL:.1f} N')
        lines.append('')
        lines.append('--- Vierendeel check per opening (governing station shown) ---')
        if not r['openings']:
            lines.append('(no web openings on this beam)')
        for rep in r['openings']:
            op = rep['opening']
            g = rep['governing']
            if g is None:
                lines.append(f'{op.label}: no valid station found (check opening geometry vs. web depth)')
                continue
            flag = '  <<< GOVERNS' if rep is r['governing_opening'] else ''
            lines.append(f'{op.label} (x_center={op.x_center:.0f}): governing x={g.x:.0f} mm, '
                          f'util_top={g.util_top:.2f}, util_bot={g.util_bot:.2f}{flag}')
            if g.warning:
                lines.append(f'    WARNING: {g.warning}')
        lines.append('')
        lines.append('--- Web-post shear/buckling between adjacent openings ---')
        if not r['webposts']:
            lines.append('(no web openings on this beam)')
        for wp in r['webposts']:
            flag = '  <<< GOVERNS' if wp is r['governing_webpost'] else ''
            lines.append(f'[{wp.x_left:.0f} - {wp.x_right:.0f}] width={wp.width:.0f} mm, '
                          f'tau_demand={wp.tau_demand:.1f} MPa, Fcr={wp.Fcr:.1f} MPa, util={wp.util:.2f}{flag}')
            if wp.warning:
                lines.append(f'    WARNING: {wp.warning}')
        lines.append('')
        c = r['combined']
        lines.append('--- Combined bending + torsion check (at Vierendeel-governing station) ---')
        lines.append(f'x={c.x:.0f} mm: sigma_bending={c.sigma_bending:.1f} MPa, '
                      f'tau_shear={c.tau_shear:.1f} MPa, tau_torsion={c.tau_torsion:.1f} MPa, util={c.util:.2f}')
        if c.doubler_t > 0:
            lines.append(f'Reinforcement required: web doubler plate t={c.doubler_t:.0f} mm ({c.note})')
        else:
            lines.append(f'No reinforcement required ({c.note})')
        self._set_results_text('\n'.join(lines))

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
