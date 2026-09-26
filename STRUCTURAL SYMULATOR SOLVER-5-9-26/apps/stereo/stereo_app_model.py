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
from apps.stereo import expr_math as em
from apps.stereo import stereo_voronoi_surface as svs
from apps.stereo.stereo_app_constants import (
    DOF_LABELS, FAMILY_KEY, PATTERN_KEY, CHORD_ROLES,
    QUICK_SUPPORT_CUSTOM, QUICK_SUPPORT_PIN, QUICK_SUPPORT_FIXED,
    QUICK_SUPPORT_CLEAR,
    AREA_GRADIENT, AREA_FIELD, AREA_SCOPE_ALL, LOAD_DIRECTIONS,
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
            elif key == 'hypar_shell':
                nx, ny = int(self.hp_nx.get()), int(self.hp_ny.get())
                module = self.hp_module.get()
                pattern = PATTERN_KEY[self.hp_pattern.get()]
                mesh = sg.hypar_shell(nx * module, ny * module, self.hp_depth.get(), module,
                                      rise=self.hp_rise.get(), offset=self.hp_offset.get(),
                                      pattern=pattern)
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
        # The Voronoi band's radius is a length in MODEL units, so a default
        # carried over from a 9 m grid would be meaningless on a 40 m bridge.
        # Re-derived from the new mesh's own rod spacing instead.
        self._voronoi_cut_last = svs.default_cut_thickness(
            self.nodes, svs.panels_of(self.nodes, self.members)) or 1.0
        self.voronoi_cut.set(self._voronoi_cut_last)
        self._apply_sections(members=self.members, redraw=False)
        # The reference module of the grid AS GENERATED -- before a node is
        # nudged, a column raised or a beam bolted on. Taken here and nowhere
        # else, which is exactly what keeps it a reference.
        self._me_capture_base_module()
        self.supports = [{'node': i, 'type': 'pin'} for i in self._support_candidates]
        self.sup_quick_var.set(QUICK_SUPPORT_PIN)
        self._disabled_supports = set()
        self.loads = []
        self.results = None
        self.member_checks = None
        self.selected_nodes = set()
        self.selected_member = None
        self.selected_members = set()
        self._reset_view(redraw=False)
        self._refresh_all()

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

    def _apply_dist_load(self):
        """Convert a uniform line load on selected members to nodal forces.

        Each member of length L with load intensity w (kN/m) produces
        w*L/2 at each endpoint, applied in the chosen direction.
        """
        targets = set(self.selected_members)
        if not targets:
            messagebox.showinfo('Distributed load',
                                'Select one or more members first.')
            return
        try:
            w = float(self.dist_w_var.get())
        except (ValueError, tk.TclError):
            messagebox.showerror('Distributed load',
                                 'Enter a valid number for w.')
            return
        if w == 0:
            return
        direction = LOAD_DIRECTIONS.get(self.dist_dir_var.get())
        if direction is None:
            messagebox.showerror('Distributed load',
                                 'Choose a direction preset.')
            return
        dx_d, dy_d, dz_d = direction
        self._push_undo('distributed load')
        totals = {}
        for mi in targets:
            if mi >= len(self.members):
                continue
            m = self.members[mi]
            _, _, _, L = sm.member_vector(self.nodes, m)
            if L < 1e-12:
                continue
            half = w * L / 2.0
            for nid in (m['a'], m['b']):
                prev = totals.get(nid, (0.0, 0.0, 0.0))
                totals[nid] = (prev[0] + half * dx_d,
                               prev[1] + half * dy_d,
                               prev[2] + half * dz_d)
        for nid, (fx, fy, fz) in totals.items():
            self.loads.append({'node': nid,
                               'fx': round(fx, 6),
                               'fy': round(fy, 6),
                               'fz': round(fz, 6)})
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

    # ── analysis ─────────────────────────────────────────────────────────────
    def _analyze(self):
        loads = self._all_loads()
        res, err = sm.analyze(self.nodes, self.members, loads, self._active_supports())
        self.err = err
        if err:
            self.results = None
            self.member_checks = None
            messagebox.showerror('Analysis', err)
        else:
            self.results = res
            self.member_checks = sc.check_all_members(self.nodes, self.members, res['member_res'])
            self._auto_deform_scale()
        self._refresh_all()

    def _auto_deform_scale(self):
        """Set the deformation scale so the max visual displacement is about
        10% of the model's bounding-box diagonal — the same convention
        SAP2000 / ETABS / Robot use to keep the deformed shape readable at
        first glance, regardless of the model's real stiffness."""
        if not self.results or not self.nodes:
            return
        import math
        nr = self.results['node_res']
        max_disp_mm = max(
            (math.sqrt(r['ux']**2 + r['uy']**2 + r['uz']**2) for r in nr),
            default=0.0)
        if max_disp_mm < 1e-9:
            return
        xs = [n[0] for n in self.nodes]
        ys = [n[1] for n in self.nodes]
        zs = [n[2] for n in self.nodes]
        span = max(max(xs) - min(xs), max(ys) - min(ys),
                   max(zs) - min(zs), 1.0)
        ideal = span * 0.10 / (max_disp_mm / 1000.0)
        clamped = max(1, min(500, int(round(ideal))))
        self.deform_scale.set(clamped)
