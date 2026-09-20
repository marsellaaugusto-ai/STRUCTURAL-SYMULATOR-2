"""Model commands for the Stereo tab: generate a mesh, load an example,
apply sections, place supports and loads, and run the analysis.

This is the controller layer between the panels (which only collect input)
and stereo_geometry / stereo_math (which do the real work). Everything
that MUTATES the model lives here, which is also why the undo snapshots
are pushed from here.

Boundary conditions are the one area explicitly required to be
unrestricted: _apply_support can restrain any combination of a node's six
DOFs, and the quick presets are only a shortcut that writes the same
per-DOF flags -- no node is ever ineligible for any support.
"""
import math
import tkinter as tk
from tkinter import messagebox

from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_math as sm
from apps.stereo import stereo_checks as sc
from apps.truss import truss_plates as tp
from apps.stereo import expr_math as em
from apps.stereo import stereo_member_loads as mld
from apps.stereo import stereo_bezier as bz
from apps.stereo.stereo_app_constants import (
    DOF_LABELS, FAMILY_KEY, PATTERN_KEY, BRACE_KEY, CHORD_ROLES,
    QUICK_SUPPORT_CUSTOM, QUICK_SUPPORT_PIN, QUICK_SUPPORT_FIXED,
    QUICK_SUPPORT_CLEAR,
    AREA_GRADIENT, AREA_FIELD, AREA_SCOPE_ALL, LOAD_DIRECTIONS,
    ROD_SCOPE_ALL, ROD_SCOPE_SELECTED, ROD_SCOPE_ROLES,
    SOURCE_FORMULA, SOURCE_EXTRUDE, SOURCE_SPIN, SOURCE_PATCH,
)


class StereoModelMixin:
    """Generate / load / section / support / load / analyze commands."""

    def _active_supports(self):
        """self.supports with any support the sandbox has disabled left
        out -- the set _analyze() and the indeterminacy readout both
        solve/count against, so toggling a support in the sandbox is felt
        immediately by both without touching the model's own support
        list. Filters defensively against self.supports's own current
        node set, so a stale sandbox entry for a node no longer supported
        (edited elsewhere) is simply harmless rather than needing to be
        swept every time self.supports changes."""
        if not self._disabled_supports:
            return self.supports
        return [s for s in self.supports if s['node'] not in self._disabled_supports]

    def _refresh_indeterminacy_label(self):
        if not self.nodes:
            self.indeterminacy_label.config(text='')
            return
        active = self._active_supports()
        restraint_count = sm.total_restrained_dofs(self.nodes, active)
        dsi = sm.degree_of_indeterminacy(self.nodes, self.members, active)
        sandbox_note = ''
        if self._disabled_supports & {s['node'] for s in self.supports}:
            n_off = len(self._disabled_supports & {s['node'] for s in self.supports})
            sandbox_note = f'  [sandbox: {n_off} support(s) disabled]'
        if restraint_count < 6:
            text = (f'UNSTABLE: only {restraint_count}/6 restraint components -- free-floating '
                    f'mechanism regardless of DSI (add supports){sandbox_note}')
            color = '#a3241a'
        elif dsi > 0:
            text = (f'Statically INDETERMINATE, degree {dsi} ({dsi} redundant load '
                    f'path(s)){sandbox_note}')
            color = '#17458c'
        elif dsi == 0:
            text = f'Statically DETERMINATE (degree 0){sandbox_note}'
            color = '#2e7d32'
        else:
            text = (f'UNDER-restrained by {-dsi} -- likely a mechanism (check '
                    f'supports/bracing){sandbox_note}')
            color = '#a3241a'
        self.indeterminacy_label.config(text=text, fg=color)

    # ── generator ────────────────────────────────────────────────────────────
    def _on_generator_change(self):
        key = FAMILY_KEY[self.grid_family.get()]
        for frame in self._param_frames.values():
            frame.pack_forget()
        self._param_frames[key].pack(fill='x')

    def _generate(self, push_undo=True):
        key = FAMILY_KEY[self.grid_family.get()]
        try:
            if key == 'flat_grid':
                nx, ny = int(self.fg_nx.get()), int(self.fg_ny.get())
                module = self.fg_module.get()
                pattern = PATTERN_KEY[self.fg_pattern.get()]
                mesh = sg.flat_grid(nx * module, ny * module, self.fg_depth.get(),
                                    module, offset=self.fg_offset.get(), pattern=pattern)
            elif key == 'vierendeel_grid':
                module = self.vd_module.get()
                mesh = sg.vierendeel_grid(int(self.vd_nx.get()) * module,
                                          int(self.vd_ny.get()) * module,
                                          self.vd_depth.get(), module)
            elif key == 'hypar_shell':
                nx, ny = int(self.hp_nx.get()), int(self.hp_ny.get())
                module = self.hp_module.get()
                pattern = PATTERN_KEY[self.hp_pattern.get()]
                mesh = sg.hypar_shell(nx * module, ny * module, self.hp_depth.get(), module,
                                      rise=self.hp_rise.get(), offset=self.hp_offset.get(),
                                      pattern=pattern)
            elif key == 'elliptic_paraboloid_shell':
                module = self.ep_module.get()
                mesh = sg.elliptic_paraboloid_shell(
                    int(self.ep_nx.get()) * module, int(self.ep_ny.get()) * module,
                    self.ep_depth.get(), module, rise=self.ep_rise.get(),
                    offset=self.ep_offset.get(), pattern=PATTERN_KEY[self.ep_pattern.get()])
            elif key == 'elliptic_hypar_shell':
                module = self.eh_module.get()
                mesh = sg.elliptic_hypar_shell(
                    int(self.eh_nx.get()) * module, int(self.eh_ny.get()) * module,
                    self.eh_depth.get(), module, rise_x=self.eh_rise_x.get(),
                    rise_y=self.eh_rise_y.get(), offset=self.eh_offset.get(),
                    pattern=PATTERN_KEY[self.eh_pattern.get()])
            elif key == 'conoid_shell':
                module = self.co_module.get()
                mesh = sg.conoid_shell(
                    int(self.co_nx.get()) * module, int(self.co_ny.get()) * module,
                    self.co_depth.get(), module, rise=self.co_rise.get(),
                    offset=self.co_offset.get(), pattern=PATTERN_KEY[self.co_pattern.get()])
            elif key == 'monkey_saddle_shell':
                module = self.ms_module.get()
                mesh = sg.monkey_saddle_shell(
                    int(self.ms_nx.get()) * module, int(self.ms_ny.get()) * module,
                    self.ms_depth.get(), module, rise=self.ms_rise.get(),
                    offset=self.ms_offset.get(), pattern=PATTERN_KEY[self.ms_pattern.get()])
            elif key == 'wave_shell':
                module = self.wv_module.get()
                mesh = sg.wave_shell(
                    int(self.wv_nx.get()) * module, int(self.wv_ny.get()) * module,
                    self.wv_depth.get(), module, rise=self.wv_rise.get(),
                    waves=self.wv_waves.get(), offset=self.wv_offset.get(),
                    pattern=PATTERN_KEY[self.wv_pattern.get()])
            elif key == 'billow_shell':
                module = self.bw_module.get()
                mesh = sg.billow_shell(
                    int(self.bw_nx.get()) * module, int(self.bw_ny.get()) * module,
                    self.bw_depth.get(), module, rise=self.bw_rise.get(),
                    waves_x=self.bw_waves_x.get(), waves_y=self.bw_waves_y.get(),
                    offset=self.bw_offset.get(),
                    pattern=PATTERN_KEY[self.bw_pattern.get()])
            elif key == 'catenary_vault':
                mesh = sg.catenary_vault(self.cv_span.get(), self.cv_rise.get(),
                                         self.cv_length.get(), int(self.cv_n_arch.get()),
                                         int(self.cv_n_bays.get()), self.cv_double.get(),
                                         self.cv_depth.get(), shape=self.cv_shape.get())
            elif key == 'torus_segment':
                mesh = sg.torus_segment(self.ts_major.get(), self.ts_tube.get(),
                                        sweep_deg=self.ts_sweep.get(),
                                        arc_deg=self.ts_arc.get(),
                                        n_sweep=int(self.ts_n_sweep.get()),
                                        n_arc=int(self.ts_n_arc.get()),
                                        depth=self.ts_depth.get(),
                                        pattern=PATTERN_KEY[self.ts_pattern.get()])
            elif key == 'hyperboloid_tower':
                mesh = sg.hyperboloid_tower(self.hb_radius.get(), self.hb_height.get(),
                                            int(self.hb_n_rings.get()),
                                            int(self.hb_n_sectors.get()),
                                            int(self.hb_twist.get()),
                                            brace=BRACE_KEY[self.hb_brace.get()])
            elif key == 'elliptic_hyperboloid':
                mesh = sg.elliptic_hyperboloid(self.eb_radius_x.get(), self.eb_radius_y.get(),
                                               self.eb_height.get(),
                                               int(self.eb_n_rings.get()),
                                               int(self.eb_n_sectors.get()),
                                               int(self.eb_twist.get()),
                                               brace=BRACE_KEY[self.eb_brace.get()])
            elif key == 'helicoid_ramp':
                mesh = sg.helicoid_ramp(self.hl_inner.get(), self.hl_outer.get(),
                                        turns=self.hl_turns.get(),
                                        rise_per_turn=self.hl_rise.get(),
                                        n_radial=int(self.hl_n_radial.get()),
                                        n_along=int(self.hl_n_along.get()),
                                        depth=self.hl_depth.get(),
                                        pattern=PATTERN_KEY[self.hl_pattern.get()])
            elif key == 'hip_roof_grid':
                nx, ny = int(self.hr_nx.get()), int(self.hr_ny.get())
                module = self.hr_module.get()
                pattern = PATTERN_KEY[self.hr_pattern.get()]
                mesh = sg.hip_roof_grid(nx * module, ny * module, self.hr_depth.get(), module,
                                        rise=self.hr_rise.get(), offset=self.hr_offset.get(),
                                        pattern=pattern)
            elif key == 'groin_vault':
                module = self.gv_module.get()
                span = int(self.gv_n.get()) * module
                pattern = PATTERN_KEY[self.gv_pattern.get()]
                mesh = sg.groin_vault(span, self.gv_rise.get(), module, self.gv_depth.get(),
                                      offset=self.gv_offset.get(), pattern=pattern)
            elif key == 'circular_flat_grid':
                mesh = sg.circular_flat_grid(self.cg_radius.get(), self.cg_depth.get(),
                                             int(self.cg_n_rings.get()),
                                             int(self.cg_n_sectors.get()),
                                             offset=self.cg_offset.get())
            elif key == 'barrel_vault':
                mesh = sg.barrel_vault(self.bv_span.get(), self.bv_rise.get(),
                                       self.bv_length.get(), int(self.bv_n_arch.get()),
                                       int(self.bv_n_bays.get()), self.bv_double.get(),
                                       self.bv_depth.get())
            elif key == 'parabolic_vault':
                mesh = sg.parabolic_vault(self.pv_span.get(), self.pv_rise.get(),
                                          self.pv_length.get(), int(self.pv_n_arch.get()),
                                          int(self.pv_n_bays.get()), self.pv_double.get(),
                                          self.pv_depth.get())
            elif key == 'elliptic_vault':
                mesh = sg.elliptic_vault(self.ev_span.get(), self.ev_rise.get(),
                                         self.ev_length.get(), int(self.ev_n_arch.get()),
                                         int(self.ev_n_bays.get()), self.ev_double.get(),
                                         self.ev_depth.get())
            elif key == 'dome':
                mesh = sg.dome(self.dm_radius.get(), self.dm_rise.get(),
                               int(self.dm_n_rings.get()), int(self.dm_n_sectors.get()))
            elif key == 'cone_roof':
                mesh = sg.cone_roof(self.cr_radius.get(), self.cr_rise.get(),
                                    int(self.cr_n_rings.get()), int(self.cr_n_sectors.get()))
            elif key == 'paraboloid_dish':
                mesh = sg.paraboloid_dish(self.pd_radius.get(), self.pd_rise.get(),
                                          int(self.pd_n_rings.get()),
                                          int(self.pd_n_sectors.get()))
            elif key == 'elliptic_dome':
                mesh = sg.elliptic_dome(self.ed_radius_x.get(), self.ed_radius_y.get(),
                                        self.ed_rise.get(), int(self.ed_n_rings.get()),
                                        int(self.ed_n_sectors.get()))
            elif key == 'truss_bridge':
                mesh = sg.truss_bridge(self.tb_span.get(), self.tb_depth.get(),
                                       self.tb_width.get(), int(self.tb_n_panels.get()))
            else:
                mesh = sg.sphere_shell(self.sp_radius.get(), int(self.sp_n_rings.get()),
                                       int(self.sp_n_sectors.get()))
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror('Generator error', str(exc))
            return

        self._load_mesh(mesh, push_undo=push_undo, undo_label='generate ' + key)

    def _load_mesh(self, mesh, push_undo=True, undo_label='generate'):
        """Replace the whole model with a freshly generated `mesh` dict --
        shared by every generator entry point (the per-family panel's own
        Generate button via _generate, and the Custom Surface Wizard) so
        loading a mesh always resets the same downstream state (supports
        reset to the quick-pin preset, loads/results cleared, selection
        cleared, view reset) instead of two call sites drifting apart."""
        if push_undo:
            self._push_undo(undo_label)
        self.nodes = mesh['nodes']
        self.members = mesh['members']
        self._support_candidates = mesh['support_candidates']
        self._load_nodes = mesh.get('load_nodes', {})
        # The settings that produced this mesh, if it came from an example
        # or from the wizard itself -- what the Custom Surface Wizard opens
        # pre-filled with. Cleared for a mesh that carries none, so the
        # wizard never shows the previous model's surfaces.
        self._wizard_recipe = mesh.get('wizard')
        self._apply_sections(members=self.members, redraw=False)
        # The reference module of the grid AS GENERATED -- before a node is
        # nudged, a column raised or a beam bolted on. Taken here and nowhere
        # else, which is exactly what keeps it a reference.
        self._me_capture_base_module()
        self.supports = [{'node': i, 'type': 'pin'} for i in self._support_candidates]
        self.sup_quick_var.set(QUICK_SUPPORT_PIN)
        self._disabled_supports = set()
        # A new mesh has no columns, so there is nothing for Clear columns
        # to hand back. Carrying the old model's entries over would restore
        # supports onto whatever node happens to hold those indices now.
        self._column_freed = []
        # Same reasoning, and the same trap: a panel is a list of node
        # INDICES, so one kept across a regenerate would weld itself to
        # whichever four nodes now hold those numbers.
        self.panels = []
        self.panel_checks = []
        # Same reasoning again: a rod load is a member INDEX, so one kept
        # across a regenerate would land on whatever member now holds that
        # number.
        self.member_loads = []
        self.loads = []
        self.results = None
        self.member_checks = None
        self.selected_nodes = set()
        self.selected_member = None
        self._reset_view(redraw=False)
        self._refresh_all()

    def _clear_model(self, push_undo=True):
        """Empty the display: no nodes, no members, no supports, no loads,
        no results.

        Routed through _load_mesh with an EMPTY mesh rather than zeroing the
        fields here, so clearing resets exactly the same state a regenerate
        does. A second reset path is how the two drift apart -- one of them
        forgets the panels, or the rod loads, or the freed column supports,
        and the bug only shows up two actions later.

        Undoable like any other model change, which is why it does not ask
        for confirmation: the cost of a mis-click is one press of the undo
        button, and this is meant to be a frequent way to start.
        """
        self._load_mesh({'nodes': [], 'members': [], 'support_candidates': [],
                         'load_nodes': {}},
                        push_undo=push_undo, undo_label='clear')

    # ── Shape mode: build from the surfaces and lattice in the panel ───────
    # ── Bezier profiles and patches ──────────────────────────────────────
    def _bz_formula_fn(self):
        """The typed formula as a one-argument function of the profile's own
        parameter, which is x for an extrude and HEIGHT for a spin.

        Both read the z-top box, because that box is where you write the
        shape either way -- a spin's profile is a radius, not a height, but
        it is still the one curve being described, and a second box that
        was live only for one source would be worse than reusing this one.
        """
        fn = sg.make_height_field_surface(self.shape_z_top.get())
        return lambda t: fn(t, 0.0)[2]

    def _bz_fit(self):
        """Fit a profile or a patch to the typed formula, and say how close
        it came.

        Reported, never promised: a fit is an approximation, and the only
        honest thing to do with one is put the real number for the curve in
        front of you on the screen. A patch especially -- it has a hard
        ceiling on how many waves it can follow, and silence there would
        read as success.
        """
        source = self.shape_source.get()
        try:
            p0 = self._shape_num(self.shape_p0, 'x from')
            p1 = self._shape_num(self.shape_p1, 'x to')
            q0 = self._shape_num(self.shape_q0, 'y from')
            q1 = self._shape_num(self.shape_q1, 'y to')
            if source == SOURCE_PATCH:
                surface = sg.make_height_field_surface(self.shape_z_top.get())
                f = lambda x, y: surface(x, y)[2]
                degree = max(1, int(self.bz_degree.get()))
                self._bz_grid = bz.fit_patch(f, (p0, p1), (q0, q1), degree, degree)
                self._bz_profile = None
                _worst, frac = bz.patch_error(self._bz_grid, f, (p0, p1), (q0, q1))
                n = len(self._bz_grid)
                note = (f'{n}x{n} controls, worst error {frac * 100:.2f}% of the '
                        f'surface height.')
                if frac > 0.05:
                    note += ('  That is too far off to design from -- raise the '
                             'degree, or use a profile with a spin or an extrude.')
            else:
                f = self._bz_formula_fn()
                self._bz_profile = bz.fit_profile(f, p0, p1,
                                                  int(self.bz_segments.get()))
                self._bz_grid = None
                _worst, frac = bz.fit_error(self._bz_profile, f)
                note = (f'{self._bz_profile["segments"]} segments, '
                        f'{len(self._bz_profile["ctrl"])} controls, worst error '
                        f'{frac * 100:.3f}% of the curve height.')
        except (em.ExpressionError, ValueError, tk.TclError, ZeroDivisionError) as exc:
            self._bz_profile = None
            self._bz_grid = None
            self.bz_error_note.config(text=str(exc), fg='#a3241a')
            self._bz_refresh_list()
            return
        self.bz_error_note.config(text=note, fg='#2f6f4f')
        self._bz_refresh_list()
        self._draw()

    def _bz_reset(self):
        """Throw the edits away and fit again, which is the only way back to
        the formula once a control has been dragged."""
        self._bz_fit()

    def _bz_refresh_list(self):
        """Repopulate the control table.

        Knots are marked differently from handles because they mean a
        different thing -- a point the curve passes THROUGH, against a
        direction it leaves in -- and editing them behaves differently too.
        """
        listbox = getattr(self, 'bz_list', None)
        if listbox is None:
            return
        keep = listbox.curselection()
        listbox.delete(0, 'end')
        profile = getattr(self, '_bz_profile', None)
        grid = getattr(self, '_bz_grid', None)
        if profile is not None:
            knots = set(bz.knot_indices(profile))
            for i, value in enumerate(profile['ctrl']):
                mark = 'ON ' if i in knots else '   '
                listbox.insert('end', f'{i:3d} {mark}{value:+10.4f}')
        elif grid is not None:
            for i, row in enumerate(grid):
                for j, value in enumerate(row):
                    listbox.insert('end', f'{i:2d},{j:<2d}  {value:+10.4f}')
        if keep and keep[0] < listbox.size():
            listbox.selection_set(keep[0])

    def _bz_on_pick(self):
        """Put the picked control's value in the edit box, so Set replaces
        it rather than the user retyping a number they can already see."""
        index = self._bz_selected_index()
        if index is None:
            return
        profile = getattr(self, '_bz_profile', None)
        if profile is not None:
            self.bz_value.set(f'{profile["ctrl"][index]:.4f}')
        else:
            grid = getattr(self, '_bz_grid', None)
            if grid:
                cols = len(grid[0])
                self.bz_value.set(f'{grid[index // cols][index % cols]:.4f}')
        self._draw()

    def _bz_selected_index(self):
        listbox = getattr(self, 'bz_list', None)
        if listbox is None:
            return None
        picked = listbox.curselection()
        return picked[0] if picked else None

    def _bz_apply_value(self):
        """Set the picked control to the typed value."""
        index = self._bz_selected_index()
        if index is None:
            return
        try:
            value = em.evaluate_number(self.bz_value.get(), 'value')
        except em.ExpressionError as exc:
            self.bz_error_note.config(text=str(exc), fg='#a3241a')
            return
        self._bz_set_control(index, value)

    def _bz_set_control(self, index, value):
        """The one place a control is moved, shared by the table and by the
        3D drag, so the two can never disagree about what an edit does."""
        profile = getattr(self, '_bz_profile', None)
        if profile is not None:
            bz.set_control(profile, index, value,
                           keep_smooth=bool(self.bz_keep_smooth.get()))
        else:
            grid = getattr(self, '_bz_grid', None)
            if not grid:
                return
            cols = len(grid[0])
            grid[index // cols][index % cols] = value
        self._bz_refresh_list()
        self.bz_error_note.config(
            text='Edited. The error above was measured against the formula '
                 'BEFORE these edits, so it no longer describes this curve.',
            fg='#8a6d1f')
        self._draw()

    def _bz_surface(self):
        """The current Bezier surface, or None when there is nothing fitted
        -- in which case the caller falls back to the typed formula, so an
        unfitted Bezier source still builds something rather than failing."""
        source = self.shape_source.get()
        if source == SOURCE_PATCH:
            grid = getattr(self, '_bz_grid', None)
            if not grid:
                return None
            return bz.patch_surface(grid, (self._shape_num(self.shape_p0, 'x from'),
                                           self._shape_num(self.shape_p1, 'x to')),
                                    (self._shape_num(self.shape_q0, 'y from'),
                                     self._shape_num(self.shape_q1, 'y to')))
        profile = getattr(self, '_bz_profile', None)
        if profile is None:
            return None
        if source == SOURCE_SPIN:
            return bz.spin_surface(profile)
        if source == SOURCE_EXTRUDE:
            return bz.extruded_surface(profile)
        return None

    def _shape_surfaces(self):
        """(top, bottom_or_None) for the build, from whichever source the
        panel is set to."""
        built = self._bz_surface()
        if built is not None:
            # A Bezier source is a single surface by construction: there is
            # one curve being edited, so offering a second one here would
            # be a control with nothing behind it.
            return built, None
        top = sg.make_height_field_surface(self.shape_z_top.get())
        if not self.shape_two.get():
            return top, None
        return top, sg.make_height_field_surface(self.shape_z_bot.get())

    def _shape_find_summits(self):
        """Put the polar pole on the surface's summit, and say how many it
        found -- one means polar is the right chart, several means no single
        pole can serve them."""
        try:
            top, _bottom = self._shape_surfaces()
        except em.ExpressionError as exc:
            self.shape_summit_note.config(text=str(exc))
            return
        try:
            span = abs(self._shape_num(self.shape_p1, 'x to')
                       - self._shape_num(self.shape_p0, 'x from')) or 1.0
            cx = self._shape_num(self.shape_pole_x, 'pole x')
            cy = self._shape_num(self.shape_pole_y, 'pole y')
        except (tk.TclError, ValueError):
            self.shape_summit_note.config(text='Enter a numeric range and pole first.')
            return
        # Search WIDER than the current disk. A summit sitting just outside
        # it, or exactly on its rim, is the interesting case -- it is why the
        # pole is in the wrong place -- and a window that stops at the rim
        # cannot see it, because an edge point is never a summit of the
        # surface, only of the window.
        reach = 2.0 * span
        tops = sg.surface_summits(top, (cx - reach, cx + reach), (cy - reach, cy + reach),
                                  samples=81)
        if not tops:
            self.shape_summit_note.config(
                text='No summit in this window -- the surface only rises towards its own '
                     'edge here, so a Cartesian domain suits it better.')
            return
        best = tops[0]
        self.shape_pole_x.set(round(best['x'], 4))
        self.shape_pole_y.set(round(best['y'], 4))
        self.shape_summit_note.config(
            text=(f"One summit, at ({best['x']:.2f}, {best['y']:.2f}). The pole is on it."
                  if len(tops) == 1 else
                  f"{len(tops)} summits. The pole is on the highest, but ONE polar grid "
                  f"cannot be centred on {len(tops)} -- a Cartesian or isometric domain "
                  f"has no pole to misplace."))

    def _build_shape_mesh(self):
        """Build the mesh from the Shape panel and load it."""
        self.shape_status.config(text='')
        try:
            top, bottom = self._shape_surfaces()
            p_range = (self._shape_num(self.shape_p0, 'x from'),
                       self._shape_num(self.shape_p1, 'x to'))
            q_range = (self._shape_num(self.shape_q0, 'y from'),
                       self._shape_num(self.shape_q1, 'y to'))
            pole = (self._shape_num(self.shape_pole_x, 'pole x'),
                    self._shape_num(self.shape_pole_y, 'pole y'))
            mesh = sg.custom_surface_lattice(
                top, bottom, coord=self.shape_coord.get(),
                lattice=self.shape_lattice.get(), p_range=p_range, q_range=q_range,
                n1=int(self.shape_n1.get()), n2=int(self.shape_n2.get()),
                depth=float(self.shape_depth.get()), pole=pole,
                pattern=self.shape_pattern.get())
            # The plan rule runs AFTER the lattice, not instead of it: the
            # generators lay out a rectangle because two ranges cannot
            # describe anything else, and the cut is what turns that
            # rectangle into a round, L-shaped or perforated roof.
            keep = sg.make_domain_fn(self.shape_plan.get())
            before = len(mesh['nodes'])
            mesh = sg.apply_domain_mask(mesh, keep)
        except (em.ExpressionError, ValueError, tk.TclError) as exc:
            self.shape_status.config(text=str(exc))
            return
        self._set_plan_cut_note(keep, before, len(mesh['nodes']))
        self._load_mesh(mesh, push_undo=True, undo_label='build surface')
        self._set_mode('shape')

    def _set_plan_cut_note(self, keep, before, after):
        """Say how much of the rectangle the plan rule actually removed.

        A rule that silently keeps everything looks identical to no rule at
        all, and a rule that removes almost everything is nearly always a
        typo (metres mistaken for a fraction of the domain, or a centre left
        at the origin when the domain does not contain it). Both are worth
        knowing before reading anything off the model."""
        note = getattr(self, 'shape_plan_note', None)
        if note is None:
            return
        if keep is None:
            note.config(text='')
        elif after == before:
            note.config(text='The rule kept the whole domain -- nothing was cut. '
                             'Check its centre against the x/y ranges above.')
        else:
            note.config(text=f'Plan cut: {before - after} of {before} nodes removed, '
                             f'{after} left.')

    def _load_example(self, builder, label):
        """Build and load one of stereo_examples.EXAMPLES -- a ready-made
        scene demonstrating the add-on features (columns, reinforcement
        beams) or the Custom Surface Wizard's single-/two-surface
        generators end to end, without having to lasso-select node
        targets or type an expression by hand first."""
        try:
            mesh = builder()
        except (ValueError, em.ExpressionError) as exc:
            messagebox.showerror('Load Example', str(exc))
            return
        self._load_mesh(mesh, push_undo=True, undo_label=f'load example: {label}')

    def _apply_sections(self, members=None, redraw=True):
        members = self.members if members is None else members
        if redraw:
            self._push_undo('apply sections')
        conn = self.sec_conn.get()
        chord = dict(E=self.chord_E.get(), A=self.chord_A.get(), I=self.chord_I.get(),
                    J=self.chord_J.get(), Fy=self.chord_Fy.get(), Fu=self.chord_Fu.get(),
                    K=self.chord_K.get(), r_gyr=self.chord_r.get())
        web = dict(E=self.web_E.get(), A=self.web_A.get(), I=self.web_I.get(),
                  J=self.web_J.get(), Fy=self.web_Fy.get(), Fu=self.web_Fu.get(),
                  K=self.web_K.get(), r_gyr=self.web_r.get())
        for m in members:
            # A Vierendeel beam carries its load by BENDING its members, so
            # its joints are not a preference -- pinned, it is a mechanism
            # rather than a stiff frame, and the solver returns a singular
            # matrix instead of a result. Members that say they need rigid
            # joints keep them whatever this panel is set to.
            if not m.get('rigid_required'):
                m['conn'] = conn
            m.update(chord if m.get('role') in CHORD_ROLES else web)
        if redraw:
            self.results = None
            self.member_checks = None
            self.panel_checks = []
            self._refresh_all()

    # ── boundary conditions ──────────────────────────────────────────────────
    def _apply_quick_support_preset(self):
        choice = self.sup_quick_var.get()
        if choice == QUICK_SUPPORT_CUSTOM:
            return
        self._push_undo('quick support preset')
        if choice == QUICK_SUPPORT_PIN:
            self.supports = [{'node': i, 'type': 'pin'} for i in self._support_candidates]
        elif choice == QUICK_SUPPORT_FIXED:
            self.supports = [{'node': i, 'type': 'fixed'} for i in self._support_candidates]
        elif choice == QUICK_SUPPORT_CLEAR:
            self.supports = []
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _preset_to_checkboxes(self):
        preset = self.sup_preset_var.get()
        if preset == 'custom':
            return
        restraints = sm.PRESET_SUPPORTS.get(preset, {})
        for d, _ in DOF_LABELS:
            self.dof_vars[d].set(bool(restraints.get(d, False)))

    def _target_nodes(self, var):
        """The node(s) an Apply/Remove/Add button acts on: every lasso- or
        click-selected node when there is at least one (so a box-selected
        group of supports can be edited in one shot -- the multi-select
        half of the "select supports with a lasso" request), falling back
        to the single typed node index otherwise, exactly as before
        multi-select existed. Returns None (not []) for an outright
        invalid typed index, so callers can tell "nothing selected AND
        the field is garbage" apart from "an empty, valid selection"."""
        if self.selected_nodes:
            return sorted(self.selected_nodes)
        try:
            return [int(var.get())]
        except (tk.TclError, ValueError):
            return None

    def _apply_support(self):
        nodes = self._target_nodes(self.sup_node_var)
        if not nodes:
            messagebox.showerror('Boundary condition',
                                 'Enter a valid node index, or select node(s) in the view.')
            return
        bad = [n for n in nodes if not (0 <= n < len(self.nodes))]
        if bad:
            messagebox.showerror('Boundary condition', f'Node {bad[0]} does not exist.')
            return
        self._push_undo('apply support')
        self.sup_quick_var.set(QUICK_SUPPORT_CUSTOM)
        dofs = {d: v.get() for d, v in self.dof_vars.items()}
        preset = self.sup_preset_var.get()
        target = set(nodes)
        self.supports = [s for s in self.supports if s['node'] not in target]
        for node in nodes:
            entry = {'node': node, 'dofs': dict(dofs)}
            if preset != 'custom':
                entry['type'] = preset
            self.supports.append(entry)
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _remove_support(self):
        nodes = self._target_nodes(self.sup_node_var)
        if not nodes:
            return
        target = set(nodes)
        before = len(self.supports)
        self._push_undo('remove support')
        self.sup_quick_var.set(QUICK_SUPPORT_CUSTOM)
        self.supports = [s for s in self.supports if s['node'] not in target]
        if len(self.supports) == before:
            self._undo_stack.pop()   # nothing changed; do not clutter the stack
            return
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _on_support_list_select(self, _event=None):
        sel = self.sup_list.curselection()
        if not sel:
            return
        sp = self.supports[sel[0]]
        self.sup_node_var.set(sp['node'])
        r = sm.support_restraints(sp)
        self.sup_preset_var.set(sp.get('type') or 'custom')
        for d, _ in DOF_LABELS:
            self.dof_vars[d].set(r[d])

    # ── loads ────────────────────────────────────────────────────────────────
    def _apply_load(self):
        nodes = self._target_nodes(self.ld_node_var)
        if not nodes:
            messagebox.showerror('Load', 'Enter a valid node index, or select node(s) in the view.')
            return
        bad = [n for n in nodes if not (0 <= n < len(self.nodes))]
        if bad:
            messagebox.showerror('Load', f'Node {bad[0]} does not exist.')
            return
        self._push_undo('apply load')
        target = set(nodes)
        self.loads = [ld for ld in self.loads if ld['node'] not in target]
        for node in nodes:
            self.loads.append({'node': node, 'fx': self.ld_fx.get(), 'fy': self.ld_fy.get(),
                               'fz': self.ld_fz.get(), 'mx': self.ld_mx.get(),
                               'my': self.ld_my.get(), 'mz': self.ld_mz.get()})
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _on_point_dir_change(self):
        """The typed vector is only for 'Custom'; a preset already is one."""
        if self.ld_dir.get() == 'Custom':
            self.frame_ld_dir.pack(fill='x')
        else:
            self.frame_ld_dir.pack_forget()

    def _resolve_point_load(self):
        """Turn "P kN in this direction" into the three force components.

        It fills the Fx/Fy/Fz boxes rather than applying anything: the load
        is still added by Add/update, so a resolved vector can be checked --
        and adjusted -- before it goes on the model. Moments are left alone;
        a direction does not imply one.
        """
        preset = LOAD_DIRECTIONS.get(self.ld_dir.get())
        if preset is None:
            vec = (self.ld_dx.get(), self.ld_dy.get(), self.ld_dz.get())
        else:
            vec = preset
        norm = math.sqrt(sum(c * c for c in vec))
        if norm < 1e-12:
            messagebox.showerror('Load', 'The direction vector cannot be zero.')
            return
        P = float(self.ld_mag.get())
        self.ld_fx.set(round(P * vec[0] / norm, 6))
        self.ld_fy.set(round(P * vec[1] / norm, 6))
        self.ld_fz.set(round(P * vec[2] / norm, 6))

    def _remove_load(self):
        nodes = self._target_nodes(self.ld_node_var)
        if not nodes:
            return
        target = set(nodes)
        before = len(self.loads)
        self._push_undo('remove load')
        self.loads = [ld for ld in self.loads if ld['node'] not in target]
        if len(self.loads) == before:
            self._undo_stack.pop()
            return
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _on_area_law_change(self):
        """Show only the fields the chosen law and direction actually use."""
        for frame in (self.frame_area_gradient, self.frame_area_field,
                      self.frame_area_dir):
            frame.pack_forget()
        law = self.area_law.get()
        if law == AREA_GRADIENT:
            self.frame_area_gradient.pack(fill='x')
        elif law == AREA_FIELD:
            self.frame_area_field.pack(fill='x')
        if self.area_dir.get() == 'Custom':
            self.frame_area_dir.pack(fill='x')

    def _area_direction(self):
        """The unit-ish vector the area load pushes along."""
        preset = LOAD_DIRECTIONS.get(self.area_dir.get())
        if preset is not None:
            return preset
        return (float(self.area_dx.get()), float(self.area_dy.get()),
                float(self.area_dz.get()))

    def _area_pressure_fn(self):
        """q(x, y, z) in kN/m2 for the chosen law.

        Returns None and puts the reason in the panel when a typed
        expression will not compile -- an area load that silently fell back
        to zero would look exactly like a structure that carries its own
        weight beautifully.
        """
        law = self.area_law.get()
        if law == AREA_GRADIENT:
            axis = 'XYZ'.index(self.area_axis.get())
            lo = min(n[axis] for n in self.nodes) if self.nodes else 0.0
            hi = max(n[axis] for n in self.nodes) if self.nodes else 1.0
            span = (hi - lo) or 1.0
            q0, q1 = float(self.area_q_min.get()), float(self.area_q_max.get())

            def q_at(x, y, z, axis=axis, lo=lo, span=span, q0=q0, q1=q1):
                t = ((x, y, z)[axis] - lo) / span
                return q0 + (q1 - q0) * min(1.0, max(0.0, t))
            return q_at
        if law == AREA_FIELD:
            try:
                fn = em.compile_expression(self.area_expr.get(), ('x', 'y', 'z'))
            except em.ExpressionError as exc:
                self.area_status.config(text=f'Area load: {exc}')
                return None
            self.area_status.config(text='')
            return lambda x, y, z: fn(x, y, z)
        q = float(self.area_load_var.get())
        return lambda x, y, z: q

    # ── distributed load along the rods ──────────────────────────────────
    def _rod_direction(self):
        """The unit-ish vector a rod load pushes along."""
        preset = LOAD_DIRECTIONS.get(self.rod_dir.get())
        if preset is not None:
            return preset
        return (float(self.rod_dx.get()), float(self.rod_dy.get()),
                float(self.rod_dz.get()))

    def _on_rod_dir_change(self):
        """Show the three component boxes only for a Custom direction --
        the same rule, and the same pack/pack_forget, _on_area_law_change
        uses for the area load's own."""
        if LOAD_DIRECTIONS.get(self.rod_dir.get()) is None:
            self.frame_rod_dir.pack(fill='x')
        else:
            self.frame_rod_dir.pack_forget()

    def _rods_in_scope(self):
        """Which member indices the chosen scope covers.

        Roles, not picking, because that is how such a load is specified in
        practice: cladding lands on the top chords and a service run hangs
        off the bottom ones, and nobody sits and clicks four hundred
        purlins. 'Selected rod only' is there for the one-off."""
        scope = self.rod_scope.get()
        if scope == ROD_SCOPE_SELECTED:
            return [] if self.selected_member is None else [self.selected_member]
        if scope == ROD_SCOPE_ALL:
            return list(range(len(self.members)))
        roles = ROD_SCOPE_ROLES.get(scope)
        if roles is None:
            return list(range(len(self.members)))
        return [i for i, m in enumerate(self.members) if m.get('role') in roles]

    def _apply_rod_load(self):
        """Put w kN/m on every rod in scope, REPLACING whatever this feature
        put there before rather than stacking a second copy on top -- the
        panel shows one w and one scope, so it has to mean one load."""
        try:
            w = float(self.rod_w.get())
            direction = self._rod_direction()
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror('Rod load', str(exc))
            return
        targets = self._rods_in_scope()
        if not targets:
            messagebox.showerror('Rod load',
                                 'No rods in that scope. Pick a rod on the '
                                 'canvas first, or choose a different scope.')
            return
        spread = self._rod_spread_key()
        self._push_undo('rod load')
        self.member_loads = [{'member': i, 'w': w, 'dir': direction, 'spread': spread}
                             for i in targets]
        self.results = None
        self.member_checks = None
        self._refresh_rod_load_status()
        self._refresh_all()

    def _rod_spread_key(self):
        label = self.rod_spread.get()
        for key, lbl in mld.SPREAD_LABELS:
            if lbl == label:
                return key
        return mld.ALONG

    def _clear_rod_loads(self):
        if not self.member_loads:
            return
        self._push_undo('clear rod loads')
        self.member_loads = []
        self.results = None
        self.member_checks = None
        self._refresh_rod_load_status()
        self._refresh_all()

    def _refresh_rod_load_status(self):
        if not self.member_loads:
            self.rod_load_status.config(text='No rod loads.')
            return
        total = 0.0
        for ld in self.member_loads:
            wx, wy, wz, L = mld.local_intensity(self.nodes, self.members[ld['member']], ld)
            total += math.hypot(wx, math.hypot(wy, wz)) * L
        w = self.member_loads[0]['w']
        self.rod_load_status.config(
            text=f'{len(self.member_loads)} rod(s) at {w:g} kN/m '
                 f'-- {self.fmt("force", total)} in total.')

    def _all_loads(self):
        """Point loads + (optionally) the area load over the roof/shell
        surface + (optionally) self-weight -- combined once here so _analyze
        and _export_excel never have to agree on the recipe twice."""
        loads = list(self.loads)
        if self.area_load_on.get() and self._load_nodes:
            q_at = self._area_pressure_fn()
            if q_at is not None:
                only = (set(self.selected_nodes)
                        if self.area_scope.get() != AREA_SCOPE_ALL else None)
                loads = sm.combine_loads(loads, sm.varying_area_load_to_nodal_loads(
                    self.nodes, self._load_nodes, q_at,
                    direction=self._area_direction(), only=only))
        if self.self_weight_on.get():
            loads = sm.combine_loads(loads, sm.self_weight_loads(
                self.nodes, self.members, self.unit_weight_var.get()))
        return loads

    def _valid_member_loads(self):
        """The rod loads that still point at a member that exists.

        A rod load is a member INDEX, so one kept across a regenerate or an
        undo would attach itself to whatever member now holds that number --
        the same trap a panel's node indices set, and clamped the same way
        rather than trusted."""
        n = len(self.members)
        return [ld for ld in getattr(self, 'member_loads', []) if 0 <= ld['member'] < n]

    # ── analysis ─────────────────────────────────────────────────────────────
    def _analyze(self):
        if not self.nodes:
            # Without this the boundary-condition check answers first and
            # says the structure is free to move as a rigid body, which is
            # true of nothing at all but is not what went wrong.
            self.results = None
            self.member_checks = None
            self.err = 'Nothing is built yet.'
            messagebox.showinfo('Analyze', 'There is nothing to analyze yet. '
                                           'Build a grid from Generate, or a '
                                           'surface from Shape.')
            return
        loads = self._all_loads()
        res, err = sm.analyze(self.nodes, self.members, loads,
                              self._active_supports(), panels=self.panels,
                              member_loads=self._valid_member_loads())
        self.err = err
        if err:
            self.results = None
            self.member_checks = None
            self.panel_checks = []
            messagebox.showerror('Analysis', err)
        else:
            self.results = res
            self.member_checks = sc.check_all_members(self.nodes, self.members, res['member_res'])
            # The Truss tab's own panel checks, reused rather than rewritten:
            # yield, weld and -- the one that actually governs a thin plate --
            # shear buckling. A tau on its own is not a verdict.
            self.panel_checks = [tp.panel_checks(pl, pr) for pl, pr
                                 in zip(self.panels, res.get('panel_res', []))]
        self._refresh_all()
