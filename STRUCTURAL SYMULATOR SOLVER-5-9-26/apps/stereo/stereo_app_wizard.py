"""The Custom Surface Wizard dialog: build a mesh from a typed expression.

A self-contained Toplevel that lets the user define a surface either as a
height field z = f(x, y) or as a full parametric x/y/z triple, choose the
sampling domain (Cartesian or polar), the module pattern and the layer
depth, and generate either one surface or a double layer between two.

Expression parsing lives in expr_math.py and the sampling itself in
stereo_geometry_custom_surface.py -- this module is only the dialog.
"""
import math
import tkinter as tk

from apps.stereo import stereo_geometry as sg
from apps.stereo import expr_math as em
from apps.stereo.stereo_app_constants import BG


class StereoWizardMixin:
    """The Custom Surface Wizard dialog."""

    def _open_custom_surface_wizard(self):
        """A Toplevel dialog for defining a surface by typed expression
        (a GeoGebra-style calculator palette inserts operators/functions
        into whichever expression field last had focus) and sampling it
        into a mesh: a domain coordinate system (Cartesian or Polar), a
        module pattern (square/diagonal/isometric), and either a single
        surface (2D one layer, or 3D that surface plus an auto-offset
        second layer) or two independently-defined surfaces connected as
        a top/bottom double layer -- see stereo_geometry.custom_surface_grid
        and custom_surface_between for what each choice actually builds.
        """
        win = tk.Toplevel(self.root)
        win.title('Custom Surface Wizard')
        win.geometry('660x800')

        # Every tk.*Var below is created with master=win explicitly, not
        # left to default: a StringVar/IntVar/etc. with no master binds
        # itself to whatever tkinter._default_root happens to be at THAT
        # moment, which is not necessarily the Tcl interpreter `win`'s own
        # widgets actually live in when more than one Tk() root exists in
        # the process (e.g. one per test file's own session fixture, as
        # in this app's own test suite) -- when it is not, the widget and
        # its "own" Python Variable object silently talk to two different
        # interpreters, so editing an Entry never reaches var.get() at all
        # (found by running this dialog's tests as part of the FULL suite
        # rather than alone: every field read back as its untouched
        # default, no matter what the widget visibly showed).
        active_entry = {'widget': None}

        def insert_token(text, cursor_back=0):
            w = active_entry['widget']
            if w is None:
                return
            w.insert(tk.INSERT, text)
            if cursor_back:
                w.icursor(w.index(tk.INSERT) - cursor_back)
            w.focus_set()

        def make_expr_row(parent, label_text, var):
            row = tk.Frame(parent, bg=BG)
            row.pack(fill='x', padx=6, pady=2)
            tk.Label(row, text=label_text, bg=BG, width=9, anchor='w',
                    font=('Helvetica', 9)).pack(side='left')
            entry = tk.Entry(row, textvariable=var, font=('Helvetica', 9))
            entry.pack(side='left', fill='x', expand=True)
            entry.bind('<FocusIn>', lambda e, w=entry: active_entry.__setitem__('widget', w))
            return entry

        def make_palette(parent):
            box = tk.LabelFrame(parent, text='Insert (into the last-focused field above)',
                                bg=BG, font=('Helvetica', 8, 'bold'))
            box.pack(fill='x', padx=6, pady=(2, 6))
            buttons = [
                ('x', 'x', 0), ('y', 'y', 0), ('u', 'u', 0), ('v', 'v', 0),
                ('pi', 'pi', 0), ('e', 'e', 0),
                ('+', '+', 0), ('-', '-', 0), ('*', '*', 0), ('/', '/', 0), ('^', '^', 0),
                ('(', '(', 0), (')', ')', 0),
                ('sin', 'sin()', 1), ('cos', 'cos()', 1), ('tan', 'tan()', 1),
                ('sqrt', 'sqrt()', 1), ('exp', 'exp()', 1), ('log', 'log()', 1),
                ('abs', 'abs()', 1),
                ('atan2', 'atan2(,)', 2), ('min', 'min(,)', 2),
                ('max', 'max(,)', 2), ('hypot', 'hypot(,)', 2),
            ]
            row = None
            for idx, (label, text, back) in enumerate(buttons):
                if idx % 8 == 0:
                    row = tk.Frame(box, bg=BG)
                    row.pack(anchor='w')
                tk.Button(row, text=label, width=5, font=('Helvetica', 8),
                         command=lambda t=text, b=back: insert_token(t, b)
                        ).pack(side='left', padx=1, pady=1)

        def make_surface_panel(parent, title):
            """One surface's own definition block: height-field or
            parametric, its own expression field(s), and its own copy of
            the calculator palette. Returns a zero-arg callable that
            compiles the CURRENT field contents into a surface(p, q) ->
            (x, y, z) callable, raising expr_math.ExpressionError for a
            bad expression -- compiled fresh on every call (not once at
            panel-build time) so editing a field after an earlier failed
            Generate attempt is picked up without reopening the dialog."""
            box = tk.LabelFrame(parent, text=title, bg=BG, font=('Helvetica', 9, 'bold'))
            box.pack(fill='x', padx=6, pady=4)

            surf_type = tk.StringVar(master=win, value='height')
            type_row = tk.Frame(box, bg=BG)
            type_row.pack(fill='x', padx=6, pady=2)
            tk.Radiobutton(type_row, text='Height field: z = f(x, y)', value='height',
                          variable=surf_type, bg=BG, font=('Helvetica', 8),
                          command=lambda: toggle()).pack(anchor='w')
            tk.Radiobutton(type_row, text='Parametric: x, y, z of (u, v) -- for a shape '
                                         'no height field can express (a torus, a cylinder...)',
                          value='param', variable=surf_type, bg=BG, font=('Helvetica', 8),
                          wraplength=520, justify='left',
                          command=lambda: toggle()).pack(anchor='w')

            z_var = tk.StringVar(master=win, value='0')
            height_frame = tk.Frame(box, bg=BG)
            make_expr_row(height_frame, 'z(x,y) =', z_var)

            x_var = tk.StringVar(master=win, value='u')
            y_var = tk.StringVar(master=win, value='v')
            zp_var = tk.StringVar(master=win, value='0')
            param_frame = tk.Frame(box, bg=BG)
            make_expr_row(param_frame, 'x(u,v) =', x_var)
            make_expr_row(param_frame, 'y(u,v) =', y_var)
            make_expr_row(param_frame, 'z(u,v) =', zp_var)

            def toggle():
                if surf_type.get() == 'height':
                    param_frame.pack_forget()
                    height_frame.pack(fill='x')
                else:
                    height_frame.pack_forget()
                    param_frame.pack(fill='x')

            height_frame.pack(fill='x')
            make_palette(box)

            def build():
                if surf_type.get() == 'height':
                    return sg.make_height_field_surface(z_var.get())
                return sg.make_parametric_surface(x_var.get(), y_var.get(), zp_var.get())
            return build

        # ── mode: one surface, or two connected as a top/bottom double layer ──
        mode_var = tk.StringVar(master=win, value='single')
        mode_row = tk.Frame(win, bg=BG)
        mode_row.pack(fill='x', padx=6, pady=(6, 2))
        tk.Radiobutton(mode_row, text='Single surface', value='single', variable=mode_var,
                      bg=BG, command=lambda: on_mode_change()).pack(side='left', padx=(0, 12))
        tk.Radiobutton(mode_row, text='Two surfaces (top + bottom)', value='between',
                      variable=mode_var, bg=BG, command=lambda: on_mode_change()
                     ).pack(side='left')

        surfaces_frame = tk.Frame(win, bg=BG)
        surfaces_frame.pack(fill='x')
        single_frame = tk.Frame(surfaces_frame, bg=BG)
        single_build = make_surface_panel(single_frame, 'Surface')
        between_frame = tk.Frame(surfaces_frame, bg=BG)
        top_build = make_surface_panel(between_frame, 'Top surface')
        bottom_build = make_surface_panel(between_frame, 'Bottom surface')
        single_frame.pack(fill='x')

        # ── domain ──────────────────────────────────────────────────────────
        domain_box = tk.LabelFrame(win, text='Domain', bg=BG, font=('Helvetica', 9, 'bold'))
        domain_box.pack(fill='x', padx=6, pady=4)
        coord_var = tk.StringVar(master=win, value='cartesian')
        coord_row = tk.Frame(domain_box, bg=BG)
        coord_row.pack(fill='x', padx=6, pady=2)
        tk.Radiobutton(coord_row, text='Cartesian', value='cartesian', variable=coord_var,
                      bg=BG, command=lambda: on_coord_change()).pack(side='left')
        tk.Radiobutton(coord_row, text='Polar', value='polar', variable=coord_var,
                      bg=BG, command=lambda: on_coord_change()).pack(side='left')
        coord_hint = tk.Label(domain_box, text='', bg=BG, fg='#666', font=('Helvetica', 8))
        coord_hint.pack(anchor='w', padx=6)

        p0_var = tk.DoubleVar(master=win, value=-5.0)
        p1_var = tk.DoubleVar(master=win, value=5.0)
        q0_var = tk.DoubleVar(master=win, value=-5.0)
        q1_var = tk.DoubleVar(master=win, value=5.0)
        n1_var = tk.IntVar(master=win, value=8)
        n2_var = tk.IntVar(master=win, value=8)

        p_label_var = tk.StringVar(master=win, value='p range:')
        prow = tk.Frame(domain_box, bg=BG)
        prow.pack(fill='x', padx=6, pady=2)
        tk.Label(prow, textvariable=p_label_var, bg=BG, width=10, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        tk.Entry(prow, textvariable=p0_var, width=8).pack(side='left')
        tk.Label(prow, text='to', bg=BG).pack(side='left', padx=2)
        tk.Entry(prow, textvariable=p1_var, width=8).pack(side='left')
        tk.Label(prow, text='n1:', bg=BG).pack(side='left', padx=(10, 2))
        tk.Entry(prow, textvariable=n1_var, width=5).pack(side='left')

        q_label_var = tk.StringVar(master=win, value='q range:')
        qrow = tk.Frame(domain_box, bg=BG)
        qrow.pack(fill='x', padx=6, pady=2)
        tk.Label(qrow, textvariable=q_label_var, bg=BG, width=10, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        tk.Entry(qrow, textvariable=q0_var, width=8).pack(side='left')
        tk.Label(qrow, text='to', bg=BG).pack(side='left', padx=2)
        tk.Entry(qrow, textvariable=q1_var, width=8).pack(side='left')
        tk.Label(qrow, text='n2:', bg=BG).pack(side='left', padx=(10, 2))
        tk.Entry(qrow, textvariable=n2_var, width=5).pack(side='left')

        full_circle_var = tk.BooleanVar(master=win, value=False)

        def on_full_circle():
            if full_circle_var.get():
                q0_var.set(0.0)
                q1_var.set(round(2.0 * math.pi, 6))
        full_circle_chk = tk.Checkbutton(domain_box, text='Full circle (q: 0 to 2*pi)',
                                         variable=full_circle_var, bg=BG,
                                         command=on_full_circle)

        def on_coord_change():
            if coord_var.get() == 'polar':
                p_label_var.set('r range:')
                q_label_var.set('theta range:')
                coord_hint.config(text='Polar: p is read as radius, q as angle (radians).')
                full_circle_chk.pack(anchor='w', padx=6, pady=(0, 4))
            else:
                p_label_var.set('p range:')
                q_label_var.set('q range:')
                coord_hint.config(text='Cartesian: p, q ARE the surface\'s own x, y (or u, v).')
                full_circle_chk.pack_forget()
        on_coord_change()

        # ── pattern ─────────────────────────────────────────────────────────
        pattern_box = tk.LabelFrame(win, text='Module pattern', bg=BG,
                                    font=('Helvetica', 9, 'bold'))
        pattern_box.pack(fill='x', padx=6, pady=4)
        pattern_var = tk.StringVar(master=win, value='square')
        for val, label in (('square', 'Square'), ('diagonal', 'Diagonal'),
                          ('isometric', 'Isometric (60°/equilateral)')):
            tk.Radiobutton(pattern_box, text=label, value=val, variable=pattern_var,
                          bg=BG, font=('Helvetica', 9)).pack(side='left', padx=6)

        # ── module (single-surface mode only) ──────────────────────────────
        module_box = tk.LabelFrame(win, text='Module', bg=BG, font=('Helvetica', 9, 'bold'))
        module_var = tk.StringVar(master=win, value='2d')
        mrow = tk.Frame(module_box, bg=BG)
        mrow.pack(fill='x', padx=6, pady=2)
        tk.Radiobutton(mrow, text='2D (single layer)', value='2d', variable=module_var,
                      bg=BG, command=lambda: on_module_change()).pack(side='left', padx=(0, 12))
        tk.Radiobutton(mrow, text='3D (double layer)', value='3d', variable=module_var,
                      bg=BG, command=lambda: on_module_change()).pack(side='left')

        depth_var = tk.DoubleVar(master=win, value=0.5)
        depth_row = tk.Frame(module_box, bg=BG)
        tk.Label(depth_row, text='Offset depth (m):', bg=BG, width=18, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        tk.Entry(depth_row, textvariable=depth_var, width=8).pack(side='left')

        side_var = tk.StringVar(master=win, value='top')
        side_row = tk.Frame(module_box, bg=BG)
        tk.Label(side_row, text='This surface is the:', bg=BG, width=18, anchor='w',
                font=('Helvetica', 9)).pack(side='left')
        tk.Radiobutton(side_row, text='Top', value='top', variable=side_var,
                      bg=BG, font=('Helvetica', 9)).pack(side='left')
        tk.Radiobutton(side_row, text='Bottom', value='bottom', variable=side_var,
                      bg=BG, font=('Helvetica', 9)).pack(side='left')

        def on_module_change():
            if module_var.get() == '3d':
                depth_row.pack(fill='x', padx=6, pady=2)
                side_row.pack(fill='x', padx=6, pady=2)
            else:
                depth_row.pack_forget()
                side_row.pack_forget()
        module_box.pack(fill='x', padx=6, pady=4)
        on_module_change()

        def on_mode_change():
            if mode_var.get() == 'single':
                between_frame.pack_forget()
                single_frame.pack(fill='x')
                module_box.pack(fill='x', padx=6, pady=4)
            else:
                single_frame.pack_forget()
                between_frame.pack(fill='x')
                module_box.pack_forget()

        status_var = tk.StringVar(master=win, value='')
        status_label = tk.Label(win, textvariable=status_var, bg=BG, fg='#a3241a',
                                wraplength=620, justify='left', font=('Helvetica', 9))
        status_label.pack(fill='x', padx=6, pady=(2, 4))

        def on_generate():
            status_var.set('')
            try:
                p_range = (float(p0_var.get()), float(p1_var.get()))
                q_range = (float(q0_var.get()), float(q1_var.get()))
                n1, n2 = int(n1_var.get()), int(n2_var.get())
                coord, pattern = coord_var.get(), pattern_var.get()
                if mode_var.get() == 'single':
                    surface = single_build()
                    mesh = sg.custom_surface_grid(
                        surface, coord=coord, pattern=pattern, p_range=p_range,
                        q_range=q_range, n1=n1, n2=n2, module=module_var.get(),
                        depth=float(depth_var.get()), offset_side=side_var.get())
                else:
                    mesh = sg.custom_surface_between(
                        top_build(), bottom_build(), coord=coord, pattern=pattern,
                        p_range=p_range, q_range=q_range, n1=n1, n2=n2)
            except (em.ExpressionError, ValueError, tk.TclError) as exc:
                status_var.set(str(exc))
                return
            self._load_mesh(mesh, push_undo=True, undo_label='custom surface wizard')
            win.destroy()

        tk.Button(win, text='Generate', font=('Helvetica', 9, 'bold'), bg='#dff0d8',
                 command=on_generate).pack(pady=8)
