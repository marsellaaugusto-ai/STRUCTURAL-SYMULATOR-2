"""The Stereo tab's 3D drawing pipeline -- everything that puts pixels on
the main canvas.

_draw is the single entry point and runs the whole pass in painter order:
optional shaded or Voronoi faces behind, then members, then nodes,
supports, load and reaction arrows, the axis gizmo, the deformed overlay
and finally the legend.

Four colour spectra can drive it (axial force, utilisation, moment,
deformation) and two fill modes can back it (shaded cell faces, Voronoi
tessellation); the colour ramps themselves are in stereo_app_colors.py, so
the legend's numeric colourbar samples the exact same functions the
wireframe uses instead of reimplementing them.

The load-path arrow animation lives here too: _load_path_arrow_fracs is
deliberately a pure static method (positions from a member's axial force
and the tick phase alone) so it can be tested without a canvas.
"""
import math
import tkinter as tk

from common import declutter_text, LoadScale

from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_math as sm
from apps.stereo.stereo_app_colors import (
    force_color, deform_color, util_color, moment_color,
    reaction_moment_signed,
)
from apps.stereo import stereo_voronoi3d as sv3
from apps.stereo.stereo_app_constants import (
    NODE_COLOR, NODE_SEL_COLOR, ADD_ROD_PENDING_COLOR,
    SUPPORT_COLOR, SUPPORT_DISABLED_COLOR, SUPPORT_BOX_HALF_PX,
    MEMBER_PIN_COLOR, MEMBER_RIGID_COLOR, MEMBER_SEL_COLOR,
    TENSION_HIGH, COMPRESSION_HIGH, LOAD_COLOR, REACTION_COLOR, NEAR_ZERO_FRAC,
    DEFORM_MODE_FORCE, SLENDER_HALO_COLOR, SLENDERNESS_LIMIT,
    LOAD_PATH_COLOR, LOAD_PATH_NEAR_ZERO_FRAC, LOAD_PATH_ARROW_HALF_PX,
    LOAD_PATH_ANIM_TICKS, STRESS_WIDTH_MIN, STRESS_WIDTH_MAX,
    GRADIENT_SEGMENTS, GRADIENT_SEGMENTS_DENSE, GRADIENT_DENSE_MEMBERS,
    MOMENT_ZERO_COLOR, MOMENT_NODE_OUTLINE, MOMENT_BACKDROP_COLOR,
    MOMENT_NODE_RADIUS_PX,
)


class StereoRenderMixin:
    """Draws the 3D view: wireframe, faces, glyphs, overlays and legend."""

    # ── load-path pulse animation ─────────────────────────────────────────────
    LOAD_PATH_TICK_MS = 150

    def _on_load_path_anim_toggle(self):
        if self.load_path_anim.get():
            self._start_load_path_animation()
        else:
            self._draw()   # one immediate redraw to clear the marching dashes

    def _start_load_path_animation(self):
        # only one ticking timer at a time -- toggling the checkbox off and
        # back on quickly must not stack up multiple self-rescheduling loops
        if self._load_path_after_id is not None:
            return
        self._load_path_tick()

    def _load_path_tick(self):
        self._load_path_after_id = None
        # the checkbox and the canvas can both go away between one tick
        # being scheduled and it firing (the tab closed, a new mesh loaded
        # elsewhere) -- checking both here is what makes this loop
        # self-terminating instead of a runaway after() chain outliving
        # the widget it draws on. The try/except is the last line of
        # defence for the same reason: a fully torn-down Tcl interpreter
        # can make even .get()/winfo_exists() themselves raise, at which
        # point there is nothing left to redraw or reschedule onto anyway.
        try:
            if not self.load_path_anim.get() or not self.canvas.winfo_exists():
                return
            self._load_path_phase += 1
            self._draw()
            self._load_path_after_id = self.root.after(self.LOAD_PATH_TICK_MS,
                                                        self._load_path_tick)
        except tk.TclError:
            pass

    @staticmethod
    def _load_path_arrow_fracs(N, t_prog):
        """The two travelling arrowheads' positions for one member in the
        load-path animation, as (fraction along a->b in 0..1, direction
        +1/-1 along that same axis) pairs -- a pure function of the
        member's own signed force and how far through the loop the
        animation currently is, with no drawing or canvas access, so the
        tension-converges/compression-diverges behaviour is directly
        testable without reproducing screen geometry.

        N >= 0 (tension): both arrows travel INWARD from their own end
        toward the centre (t=0.5) -- the member pulling its two endpoints
        together. N < 0 (compression): both travel OUTWARD from the
        centre toward their own end -- the member pushing them apart.
        """
        if N >= 0:
            return ((t_prog * 0.5, 1), (1.0 - t_prog * 0.5, -1))
        return ((0.5 - t_prog * 0.5, -1), (0.5 + t_prog * 0.5, 1))

    def _moment_field_by_node(self, frac):
        """Signed nodal moment for every joint that carries one, plus the
        largest magnitude present. Returns ({node: value}, max_abs).

        Every rigid (moment-transmitting) joint gets a value, not just the
        supports: a support's own reaction Mx/My/Mz (SOMETHING must transfer
        moment into it -- a rigid connection scheme, or a directly applied
        point moment), and every ordinary interior joint touched by at least
        one rigid member gets sm.node_moment_vectors's own value (the
        largest-magnitude incident member end, expressed in the same global
        axes the reactions already use -- see that function's docstring for
        why a plain sum across incident members would be wrong here).

        A purely pin-jointed model reacts to force alone, so every node
        reads ~0 regardless of load: an accurate reflection of the physics,
        not a sign the feature is broken on that kind of model.

        The maximum spans the WHOLE grid (supports and interior joints
        alike), so any one node's colour is always relative to every other
        node currently in the structure rather than to the supports alone.
        """
        moment_by_node, max_abs = {}, 0.0
        if self.results is None or not self.nodes:
            return moment_by_node, max_abs
        moment_axis = self.moment_axis.get()
        # The structure's own planar centroid -- see reaction_moment_signed's
        # docstring for why the RESULTANT mode's sign is projected relative
        # to it (symmetric nodes must read the same colour, which a raw
        # Mx/My component cannot guarantee).
        centroid_xy = (sum(n[0] for n in self.nodes) / len(self.nodes),
                      sum(n[1] for n in self.nodes) / len(self.nodes))
        support_nodes = {s['node'] for s in self.supports
                        if any(sm.support_restraints(s).values())}
        for i in support_nodes:
            r = self.results['reactions'].get(i)
            if r is not None:
                node_xy = (self.nodes[i][0], self.nodes[i][1])
                m = reaction_moment_signed(r, moment_axis, node_xy, centroid_xy) * frac
                moment_by_node[i] = m
                max_abs = max(max_abs, abs(m))
        node_vecs = sm.node_moment_vectors(self.nodes, self.members,
                                           self.results['member_res'])
        for i, vec in node_vecs.items():
            if i in moment_by_node:
                continue   # a support's own reaction already wins
            node_xy = (self.nodes[i][0], self.nodes[i][1])
            m = reaction_moment_signed(vec, moment_axis, node_xy, centroid_xy) * frac
            moment_by_node[i] = m
            max_abs = max(max_abs, abs(m))
        return moment_by_node, max_abs

    @staticmethod
    def _nodal_average(n_nodes, members, values):
        """Average a per-MEMBER quantity onto the nodes, for the smooth
        gradient.

        Axial force and utilization are properties of a rod, not of a
        joint, so a continuous field over the structure needs a value at
        each joint: the mean over the rods meeting there. This is ordinary
        nodal averaging, the same smoothing an FEA post-processor applies
        to element results before contouring them -- honest as a picture of
        how load hands over at a joint, but note it is a SMOOTHED reading,
        not raw data: a joint where a heavily loaded chord meets three idle
        braces averages down to something neither rod actually carries.
        Node moment and displacement need none of this -- they are nodal
        quantities already, so their gradient interpolates real values.

        A node with no members keeps 0.0 rather than dividing by zero.
        """
        total = [0.0] * n_nodes
        count = [0] * n_nodes
        for i, m in enumerate(members):
            v = values[i]
            for end in (m['a'], m['b']):
                total[end] += v
                count[end] += 1
        return [total[k] / count[k] if count[k] else 0.0 for k in range(n_nodes)]

    def _gradient_segments(self):
        """How many straight pieces each rod is split into for the smooth
        gradient. A rod is drawn as a run of short lines, each a slightly
        different colour, so the count is a direct multiplier on canvas
        items -- dense models drop to a coarser run rather than paying
        eight times the item count for a blend that is only a few pixels
        long anyway."""
        return (GRADIENT_SEGMENTS if len(self.members) <= GRADIENT_DENSE_MEMBERS
                else GRADIENT_SEGMENTS_DENSE)

    def _draw_gradient_line(self, c, sx0, sy0, sx1, sy1, va, vb, color_fn,
                            width, tags, dash=None, segments=None):
        """One rod drawn as a colour blend from `va` at its first end to
        `vb` at its second, instead of a single flat colour."""
        n = segments or self._gradient_segments()
        for k in range(n):
            t0, t1 = k / n, (k + 1) / n
            x0, y0 = sx0 + (sx1 - sx0) * t0, sy0 + (sy1 - sy0) * t0
            x1, y1 = sx0 + (sx1 - sx0) * t1, sy0 + (sy1 - sy0) * t1
            kw = {'fill': color_fn(va + (vb - va) * (t0 + t1) / 2.0),
                  'width': width, 'tags': tags, 'capstyle': tk.ROUND}
            if dash:
                kw['dash'] = dash
            c.create_line(x0, y0, x1, y1, **kw)

    @staticmethod
    def _stress_widths(members, member_res):
        """One drawn line width per member, scaled by how hard that member
        is working compared with every other member in the model.

        The quantity is axial STRESS, |N|/A -- not axial force. Two rods
        carrying the same kN are not working equally hard if one of them
        has twice the section, and it is the stress that decides whether
        the material is close to yielding, so a thick line here means
        "this rod's material is highly stressed" rather than merely "a big
        number of kN passes through it". That also makes this genuinely
        different information from the force colouring, which maps N.

        Widths are LINEAR in the stress ratio: perceived line weight
        tracks pixel width closely enough that the gamma compression the
        colour ramps need would only misstate the ratio here. The scale
        runs from STRESS_WIDTH_MIN at zero stress to STRESS_WIDTH_MAX at
        the model's own maximum, and cannot exceed that cap -- see the
        constants' own note on why an uncapped width is unreadable.

        A member with no usable section (A missing or <= 0) contributes no
        stress and is drawn at the minimum width rather than skipped, so
        the picture never silently loses a rod. Returns None when there is
        nothing to scale against (no results, or every member unstressed),
        which is the caller's signal to use its own default width.
        """
        if not member_res:
            return None
        stresses = []
        for i, m in enumerate(members):
            area = m.get('A') or 0.0
            N = member_res[i]['N'] if i < len(member_res) else 0.0
            stresses.append(abs(N) / area if area > 0 else 0.0)
        peak = max(stresses, default=0.0)
        if peak <= 0.0:
            return None
        span = STRESS_WIDTH_MAX - STRESS_WIDTH_MIN
        return [STRESS_WIDTH_MIN + span * min(1.0, s / peak) for s in stresses]

    def _draw(self):
        c = self.canvas
        c.delete('all')
        if not self.nodes:
            return
        # Always the REST structure -- "Show deformed" draws an ADDITIONAL
        # green overlay in parallel (see _draw_deformed_overlay), it never
        # replaces this, so the real structure stays exactly where clicks,
        # the lasso and everything else expect to find it.
        proj = [self._project(x, y, z) for x, y, z in self.nodes]

        xs = [p[0] for p in proj]; ys = [p[1] for p in proj]
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0

        def to_screen(px, py):
            wx = (px - cx) * self.PX_PER_M
            wy = (py - cy) * self.PX_PER_M
            return self.zc.w2s(wx, wy)

        # Drawn FIRST (underneath), same convention as truss_app.py's own
        # "Show deformed": the real structure then draws on top of it --
        # UNLESS "Deformed only" asks to see the deformed shape by itself,
        # in which case the reference structure (and everything keyed to
        # it -- labels, load arrows) is skipped entirely below.
        show_def = self.show_deformed.get() and self.results is not None
        deformed_only = show_def and self.deformed_only.get()
        if show_def:
            self._draw_deformed_overlay(c, to_screen)

        frac = self._load_frac()
        by_util = self.colour_by_util.get() and self.member_checks is not None
        by_force = self.colour_by_force.get() and self.results is not None and not by_util
        by_moment = self.colour_by_moment.get() and self.results is not None
        max_abs_N = 0.0
        max_abs_moment = 0.0   # stays 0.0 unless by_moment computes it below;
                                # declared here (not inside the deformed_only-
                                # guarded block that actually fills it in) so
                                # it is always defined by the time it reaches
                                # _draw_legend's colorbar, even when
                                # deformed_only skips that block entirely
        if by_force:
            max_abs_N = max((abs(mr['N']) for mr in self.results['member_res']), default=0.0)
        load_path_on = self.load_path_anim.get() and self.results is not None
        hide_zero_force = self.hide_zero_force.get() and self.results is not None
        max_abs_N_lp = max_abs_N
        if (load_path_on or hide_zero_force) and not by_force:
            max_abs_N_lp = max((abs(mr['N']) for mr in self.results['member_res']), default=0.0)

        # Thickness by stress is a RELATIVE measure (each member against the
        # most-stressed one), so unlike the force/utilization colours it is
        # deliberately not scaled by 'Load %': a linear solve scales every
        # member's stress by the same factor, leaving the ratios -- and so
        # the drawn widths -- identical at every setting of the slider.
        stress_widths = None
        if self.thickness_by_stress.get() and self.results is not None:
            stress_widths = self._stress_widths(self.members,
                                                self.results['member_res'])

        # The node-moment field is needed BEFORE the member loop as well as
        # after it: with the smooth gradient on, the rods carry the moment
        # blend between their two joints, and only then do the node dots go
        # on top of them.
        moment_by_node = {}
        if by_moment and not deformed_only:
            moment_by_node, max_abs_moment = self._moment_field_by_node(frac)

        # Smooth gradient: instead of one flat colour per rod, blend each rod
        # between the values at its own two ends, so the field reads as
        # continuous across joints. For moment (and, in the deformed overlay,
        # displacement) the end values are genuine nodal results; for force
        # and utilization they are averaged onto the joints -- see
        # _nodal_average on what that averaging does and does not claim.
        gradient = self.smooth_gradient.get() and self.results is not None
        grad_values = grad_color_fn = None
        if gradient and not deformed_only:
            n_nodes = len(self.nodes)
            if by_util and self.member_checks is not None:
                utils = [(self.member_checks[i]['util'] * frac
                          if i < len(self.member_checks) and self.member_checks[i]
                          and self.member_checks[i].get('checked') else 0.0)
                         for i in range(len(self.members))]
                grad_values = self._nodal_average(n_nodes, self.members, utils)
                grad_color_fn = util_color
            elif by_force:
                forces = [mr['N'] * frac for mr in self.results['member_res']]
                grad_values = self._nodal_average(n_nodes, self.members, forces)
                grad_color_fn = lambda v: force_color(v, max_abs_N)
            elif by_moment:
                grad_values = [moment_by_node.get(i, 0.0) for i in range(n_nodes)]
                grad_color_fn = lambda v: moment_color(v, max_abs_moment)

        if not deformed_only:
            # While comparing against the deformed overlay, the reference
            # structure fades to a single adjustable grey (rather than its
            # usual force/pin-rigid colours) so it reads as a faint
            # backdrop instead of competing with the overlay for attention.
            ref_grey = self._reference_grey() if show_def else None

            # An empty `order` when rods are hidden -- rather than wrapping
            # this whole loop in an `if` -- keeps every per-member branch
            # below (halos, load-path dashes, over-capacity dashing) as a
            # single indentation level, unchanged whether rods show or not.
            order = sorted(range(len(self.members)), key=lambda i: -(
                proj[self.members[i]['a']][2] + proj[self.members[i]['b']][2])) \
                if self.show_members.get() else []
            for i in order:
                if hide_zero_force and max_abs_N_lp > 1e-9:
                    # NEAR_ZERO_FRAC -- force_color's OWN threshold for
                    # painting a member NEAR_ZERO_COLOR -- so this hides
                    # exactly the members the colouring already calls "~0"
                    # and a member can never read as "~0" in one and
                    # "clearly carrying load" in the other. Deliberately NOT
                    # LOAD_PATH_NEAR_ZERO_FRAC: that is the (slightly
                    # tighter) cutoff for which members the load-path
                    # animation leaves still, a separate question from which
                    # ones are worth drawing at all. Using it here left a
                    # band of members painted the "~0" grey that the toggle
                    # nonetheless kept on screen.
                    #
                    # Both sides of the ratio scale with 'Load %' exactly as
                    # the colouring does (N by frac, the max held at its
                    # full-load value), so hidden == grey at every setting
                    # of the slider, not just at 100%.
                    N_hide = self.results['member_res'][i]['N'] * frac
                    if abs(N_hide) / max_abs_N_lp < NEAR_ZERO_FRAC:
                        continue
                m = self.members[i]
                ax, ay, _ = proj[m['a']]
                bx, by, _ = proj[m['b']]
                sx0, sy0 = to_screen(ax, ay)
                sx1, sy1 = to_screen(bx, by)
                over = False
                chk = self.member_checks[i] if self.member_checks and i < len(self.member_checks) \
                    else None
                # 'Load %' scales linearly through: N and utilization both
                # scale exactly with the applied load in a linear-elastic
                # solve (see _load_frac's own docstring), so stepping the
                # slider down shows the SAME model at a lighter load,
                # colours included, not just a smaller deformed shape.
                if ref_grey is not None:
                    color = ref_grey
                elif by_moment:
                    # The moment view's actual content is the NODE colours
                    # below, not the members -- left at their usual dark
                    # rigid/pin (or force/utilization) colouring, a busy
                    # joint's converging rod lines visually swallow the
                    # small moment-coloured dot sitting on top of them. Fade
                    # to a flat pale backdrop instead, the same idea as
                    # ref_grey above for the deformed overlay.
                    color = MOMENT_BACKDROP_COLOR
                elif by_util:
                    util = chk['util'] * frac if chk and chk.get('checked') else 0.0
                    color = util_color(util)
                elif by_force:
                    N = self.results['member_res'][i]['N'] * frac
                    color = force_color(N, max_abs_N)
                else:
                    color = MEMBER_RIGID_COLOR if m.get('conn') == 'rigid' else MEMBER_PIN_COLOR
                width = 2
                if stress_widths is not None:
                    width = stress_widths[i]
                # Both of these RAISE the width rather than setting it, so a
                # heavily stressed member never gets thinner for also being
                # over capacity or selected -- the two cues stack instead of
                # overwriting each other.
                if chk and chk.get('checked') and chk['util'] * frac > 1.0:
                    over = True
                    width = max(width, 3)
                if i == self.selected_member:
                    width = max(width, 4)
                # Slenderness is a purely geometric/section property (KL/r),
                # independent of the applied load -- unlike the utilization
                # overlay above, it never scales with 'Load %'. Drawn as a
                # wide dashed halo UNDERNEATH the member's own normal-
                # coloured line (i.e. BEFORE it, so the halo peeks out from
                # behind), so it stays visible regardless of which colour
                # mode -- force, utilization, or plain -- is currently
                # active, instead of competing with it for the same line.
                if self.flag_slender.get() and chk and chk.get('mode') == 'compression' \
                        and chk.get('slenderness', 0.0) > SLENDERNESS_LIMIT:
                    c.create_line(sx0, sy0, sx1, sy1, fill=SLENDER_HALO_COLOR,
                                 width=width + 5, dash=(4, 3), tags='member')
                if grad_values is not None and ref_grey is None:
                    self._draw_gradient_line(c, sx0, sy0, sx1, sy1,
                                             grad_values[m['a']], grad_values[m['b']],
                                             grad_color_fn, width, 'member',
                                             dash=(5, 3) if over else None)
                else:
                    kw = {'fill': color, 'width': width, 'tags': 'member'}
                    if over:
                        kw['dash'] = (5, 3)
                    c.create_line(sx0, sy0, sx1, sy1, **kw)
                if i == self.selected_member:
                    # A halo drawn on top so the selected member reads
                    # clearly regardless of whatever colour mode is active.
                    c.create_line(sx0, sy0, sx1, sy1, fill=MEMBER_SEL_COLOR, width=1,
                                 dash=(2, 2), tags='member')
                # Load-path pulse: a genuinely unambiguous single "load
                # path" doesn't exist in a statically indeterminate
                # structure (load splits across every parallel path in
                # proportion to relative stiffness -- see this feature's
                # own design notes), so this deliberately does not claim
                # to show which way "the" load flows. What it DOES show:
                # every member actually carrying force gets a thin static
                # guide line (so a still screenshot still answers "which
                # members"), plus two small arrowheads animated along it
                # in a continuous loop -- pointing INWARD from both ends
                # toward the centre for a member in TENSION (pulling its
                # own two endpoints together) and OUTWARD from the centre
                # toward both ends for COMPRESSION (pushing them apart).
                # Direction of travel encodes tension vs compression only,
                # same as the marching dashes this replaces -- clearer to
                # read as actual motion than a shifting dash pattern was.
                # Independent of the member's own colour mode, like the
                # slenderness halo.
                if load_path_on and max_abs_N_lp > 1e-9:
                    N = self.results['member_res'][i]['N'] * frac
                    if abs(N) / max_abs_N_lp > LOAD_PATH_NEAR_ZERO_FRAC:
                        c.create_line(sx0, sy0, sx1, sy1, fill=LOAD_PATH_COLOR, width=1,
                                     tags='member')
                        mlen = math.hypot(sx1 - sx0, sy1 - sy0)
                        half = min(LOAD_PATH_ARROW_HALF_PX, mlen / 2.0 - 1.0)
                        if mlen > 1e-6 and half > 1.0:
                            ux, uy = (sx1 - sx0) / mlen, (sy1 - sy0) / mlen
                            t_prog = (self._load_path_phase % LOAD_PATH_ANIM_TICKS) \
                                / LOAD_PATH_ANIM_TICKS
                            for t, d in self._load_path_arrow_fracs(N, t_prog):
                                px, py = sx0 + t * (sx1 - sx0), sy0 + t * (sy1 - sy0)
                                c.create_line(px - d * ux * half, py - d * uy * half,
                                             px + d * ux * half, py + d * uy * half,
                                             fill=LOAD_PATH_COLOR, width=2, arrow='last',
                                             arrowshape=(6, 7, 3), tags='member')

            support_nodes = {s['node'] for s in self.supports
                             if any(sm.support_restraints(s).values())}
            # Same empty-iterable trick as `order` above for show_members --
            # keeps every per-node branch (selection, support box, moment
            # colouring) at its existing indentation regardless of the toggle.
            for i, (px, py, _) in (enumerate(proj) if self.show_nodes.get() else []):
                sx, sy = to_screen(px, py)
                sel = i in self.selected_nodes
                if by_moment and i in moment_by_node:
                    r = MOMENT_NODE_RADIUS_PX + 1 if sel else MOMENT_NODE_RADIUS_PX
                else:
                    r = 5 if sel else 4
                if sel:
                    color = NODE_SEL_COLOR
                elif i in self._disabled_supports and i in support_nodes:
                    color = SUPPORT_DISABLED_COLOR
                elif by_moment and i in moment_by_node:
                    color = moment_color(moment_by_node.get(i, 0.0), max_abs_moment)
                elif ref_grey is not None:
                    color = ref_grey
                elif i in support_nodes:
                    color = SUPPORT_COLOR
                else:
                    color = NODE_COLOR
                # A thin grey outline is drawn only in moment mode: the
                # gradient's own zero-point is white (MOMENT_ZERO_COLOR),
                # the same colour as the canvas background, so a
                # near-zero-moment node would otherwise vanish entirely
                # against it without a border to still mark its position.
                node_outline = MOMENT_NODE_OUTLINE if (by_moment and i in moment_by_node) else ''
                c.create_oval(sx - r, sy - r, sx + r, sy + r, fill=color,
                             outline=node_outline, tags=('node', f'node{i}'))
                # A small box drawn AROUND a supported node -- the "box
                # that symbolises the support" asked for, instead of
                # relying on dot-color alone (which a selection highlight
                # would otherwise override/obscure).
                if i in support_nodes:
                    h = SUPPORT_BOX_HALF_PX
                    disabled = i in self._disabled_supports
                    if disabled:
                        # the sandbox toggle wins over every other colour
                        # mode -- a support you just switched off must
                        # stay visibly distinct regardless of what else
                        # the view is colouring by
                        box_color = SUPPORT_DISABLED_COLOR
                    elif by_moment:
                        box_color = moment_color(moment_by_node.get(i, 0.0), max_abs_moment)
                        # a white (zero-moment) outline would be invisible
                        # against the canvas's own white background
                        if box_color == MOMENT_ZERO_COLOR:
                            box_color = MOMENT_NODE_OUTLINE
                    elif ref_grey is not None:
                        box_color = ref_grey
                    else:
                        box_color = SUPPORT_COLOR
                    kw = {'dash': (3, 2)} if disabled else {}
                    c.create_rectangle(sx - h, sy - h, sx + h, sy + h, outline=box_color,
                                       width=2, tags=('node', f'node{i}'), **kw)

            if self.add_rod_mode.get() and self._add_rod_first is not None \
                    and self._add_rod_first < len(proj):
                # The first-picked node's own pending state, waiting on a
                # second click -- drawn every frame regardless of
                # show_nodes so it never silently vanishes mid-pick.
                px, py, _ = proj[self._add_rod_first]
                sx, sy = to_screen(px, py)
                r = MOMENT_NODE_RADIUS_PX + 3
                c.create_oval(sx - r, sy - r, sx + r, sy + r, outline=ADD_ROD_PENDING_COLOR,
                             width=2, dash=(3, 2), tags='add_rod_pending')

            if self.shaded_faces.get():
                self._draw_shaded_faces(c, proj, to_screen, frac, by_util, by_force,
                                        max_abs_N, by_moment, moment_by_node, max_abs_moment)

            if self.voronoi_faces.get():
                self._draw_voronoi_faces(c, proj, to_screen, frac, by_util, by_force,
                                         max_abs_N, by_moment, moment_by_node, max_abs_moment)

            if self.show_node_labels.get():
                labels = []
                for i, (px, py, _) in enumerate(proj):
                    sx, sy = to_screen(px, py)
                    labels.append(c.create_text(sx + 8, sy - 8, text=str(i), anchor='w',
                                               font=('Helvetica', 7), fill='#555'))
                declutter_text(c, labels)

            if self.show_member_labels.get():
                mlabels = []
                for i, m in enumerate(self.members):
                    ax, ay, _ = proj[m['a']]
                    bx, by, _ = proj[m['b']]
                    sx0, sy0 = to_screen(ax, ay)
                    sx1, sy1 = to_screen(bx, by)
                    mlabels.append(c.create_text((sx0 + sx1) / 2.0, (sy0 + sy1) / 2.0,
                                                text=str(i), font=('Helvetica', 7, 'italic'),
                                                fill='#8a5a00'))
                declutter_text(c, mlabels)

            if self.show_loads.get():
                self._draw_load_arrows(c, to_screen)

            if self.show_reactions.get() and self.results is not None:
                self._draw_reaction_arrows(c, to_screen, proj)

        if self.show_axes.get():
            self._draw_axes(c, to_screen)

        if self._lasso_dragging and self._lasso_cur is not None:
            x0, y0 = self._lasso_press
            x1, y1 = self._lasso_cur
            c.create_rectangle(x0, y0, x1, y1, outline='#333333', dash=(5, 3),
                               stipple='gray12', fill='#333333', tags='lasso')

        self._draw_legend(c, by_force, show_def, deformed_only, by_util,
                          max_abs_N=max_abs_N, max_abs_moment=max_abs_moment)
        self._to_screen_cache = to_screen   # for hit-testing on click

    def _get_shaded_cells(self):
        """The mesh's minimal 3-/4-node closed cells (stereo_geometry's own
        find_cells -- the same routine the Module Editor uses to find its
        own faces), cached until the next _refresh_all invalidates it.
        find_cells is O(members x degree^2); with the 'Shaded faces' mode
        off (its only caller) this is never computed at all, and with it
        on the cost is paid once per mesh EDIT, not once per _draw() --
        _draw() itself runs on every mouse-move while orbiting/panning."""
        if self._shaded_cells is None:
            self._shaded_cells = sg.find_cells(self.nodes, self.members)
        return self._shaded_cells

    def _draw_shaded_faces(self, c, proj, to_screen, frac, by_util, by_force, max_abs_N,
                           by_moment, moment_by_node, max_abs_moment):
        """Fill every mesh cell (stereo_geometry.find_cells's 3-/4-node
        panels) with a flat colour, so the structure reads as one
        continuous shaded sheet instead of a set of individually-coloured
        lines -- closer to how an FEA contour plot presents a shell.

        This is a rendering approximation, not a new analysis: the
        underlying model is still a pin-jointed space TRUSS (discrete
        axial members, one force each), which has no continuum stress
        field to interpolate in the first place. Each cell is filled with
        ONE flat colour, averaged from the same per-member/per-node values
        and the SAME colour functions (force_color/util_color/
        moment_color) the wireframe itself uses -- a coarse, "low-poly"
        mosaic, not a smooth per-pixel gradient (Tk canvas polygons only
        support one flat fill colour each; a true smooth interpolation
        would need per-pixel rendering this canvas API cannot do).

        Criterion picked by the same precedence the members already use --
        utilization, then force, then (independently, since it is a NODE
        quantity) moment -- so at most one fill layer is ever drawn; two
        overlapping semi-transparent-looking fills from two criteria at
        once would be harder to read, not more integral. Drawn last and
        then sent behind every other item on the canvas (tag_lower), so
        the wireframe/nodes/labels drawn earlier keep the structure's own
        rod definition legible on top of the shaded sheet.
        """
        cells = self._get_shaded_cells()
        if not cells:
            return
        member_res = self.results['member_res'] if self.results else None
        for cell in cells:
            if by_util and self.member_checks is not None:
                utils = [self.member_checks[mi]['util'] * frac
                        for mi in cell['members']
                        if mi < len(self.member_checks) and self.member_checks[mi].get('checked')]
                if not utils:
                    continue
                color = util_color(sum(utils) / len(utils))
            elif by_force and member_res is not None:
                forces = [member_res[mi]['N'] * frac for mi in cell['members']]
                color = force_color(sum(forces) / len(forces), max_abs_N)
            elif by_moment and moment_by_node:
                vals = [moment_by_node[n] for n in cell['nodes'] if n in moment_by_node]
                if not vals:
                    continue
                color = moment_color(sum(vals) / len(vals), max_abs_moment)
            else:
                continue
            pts = []
            for n in cell['nodes']:
                px, py, _ = proj[n]
                sx, sy = to_screen(px, py)
                pts.extend((sx, sy))
            c.create_polygon(*pts, fill=color, outline='', tags='shaded_face')
        c.tag_lower('shaded_face')

    def _draw_voronoi_faces(self, c, proj, to_screen, frac, by_util, by_force, max_abs_N,
                            by_moment, moment_by_node, max_abs_moment):
        """A true 3D Voronoi tessellation of the model, drawn behind it.

        The tessellation lives in MODEL space, not on the screen: the cells
        are attached to the structure and hold still while the camera moves,
        and they are confined to the volume the structure actually occupies
        (see stereo_voronoi3d for the domain and view choices, both of which
        are the user's to make). All four spectra can drive it -- force,
        utilization, node moment and deformation.

        Needs no mesh topology at all, which is what it offers over
        _draw_shaded_faces: bare proximity still produces a continuous sheet
        on a mesh with no clean quad/triangle faces to find (a sparse dome, a
        rod added by hand). Cells carry one flat colour each -- a Tk canvas
        polygon cannot blend across itself -- so the smooth gradient remains
        the way to read a continuous field along the rods.
        """
        self._voronoi_note = ''
        spec = self._voronoi_site_values(frac, by_util, by_force, max_abs_N,
                                        by_moment, moment_by_node, max_abs_moment)
        if spec is None:
            return
        sites, colours = spec
        patches = self._voronoi_patches(sites)
        self._voronoi_note = '' if patches else self._voronoi_empty_reason(sites)
        if not patches:
            return

        # Painter's algorithm: the tessellation is solid geometry, so a patch
        # behind another has to be drawn first. Depth comes from the same
        # projection the wireframe uses, so the two always agree about what
        # is in front.
        drawn = []
        for poly, owner in patches:
            pts, depth = [], 0.0
            for x, y, z in poly:
                px, py, d = self._project(x, y, z)
                sx, sy = to_screen(px, py)
                pts += [sx, sy]
                depth += d
            drawn.append((depth / max(1, len(poly)), pts, owner))
        drawn.sort(key=lambda t: -t[0])

        # Skin and Cells are both drawn STIPPLED: they wrap the outside of
        # the structure, so a solid fill hides everything on the far side of
        # it -- the back rods, the far supports, the load arrows. A 50%
        # stipple keeps the fill readable as a field while leaving the
        # structure visible through it. The Section plane stays solid: it is
        # a cut FACE, and a cut you can see through no longer reads as one.
        stipple = '' if self.voronoi_view.get() == sv3.VIEW_SECTION else 'gray50'
        for _depth, pts, owner in drawn:
            c.create_polygon(*pts, fill=colours[owner], outline='',
                             stipple=stipple, tags='voronoi_face')
        c.tag_lower('voronoi_face')

    def _voronoi_site_values(self, frac, by_util, by_force, max_abs_N,
                             by_moment, moment_by_node, max_abs_moment):
        """(sites, colour-per-site) for whichever spectrum is active.

        Moment and deformation are NODAL quantities, so their sites are the
        nodes themselves. Force and utilization belong to a rod, which has no
        single point where its value uniquely lives, so the rod's midpoint
        stands in -- a reasonable choice but a genuinely debatable one, which
        is why the legend says which it used rather than leaving it implied.
        """
        if by_util and self.member_checks is not None:
            sites = sv3.member_midpoints(self.nodes, self.members)
            cols = [util_color((self.member_checks[i]['util'] * frac)
                               if i < len(self.member_checks)
                               and self.member_checks[i].get('checked') else 0.0)
                    for i in range(len(self.members))]
            return sites, cols
        if by_force and self.results is not None:
            sites = sv3.member_midpoints(self.nodes, self.members)
            cols = [force_color(mr['N'] * frac, max_abs_N)
                    for mr in self.results['member_res']]
            return sites, cols
        if by_moment and moment_by_node:
            sites = [self.nodes[i] for i in range(len(self.nodes))]
            cols = [moment_color(moment_by_node.get(i, 0.0), max_abs_moment)
                    for i in range(len(self.nodes))]
            return sites, cols
        if self.show_deformed.get() and self.results is not None:
            _deformed, disp_mm = self._deformed_nodes_and_disp()
            top = max(disp_mm, default=0.0)
            return list(self.nodes), [deform_color(d, top) for d in disp_mm]
        return None

    def _voronoi_band_value(self):
        """The band radius, read defensively.

        It is bound to a typed Entry, so between two keystrokes its contents
        can be empty, half a number, or 'abc' -- and a DoubleVar raises on
        every one of those. A redraw runs on far more than the Return key
        (orbit, a toggle, the load slider), so an unguarded read turned an
        ordinary edit into a broken canvas. The last value that WAS a
        positive length is kept and used until the field makes sense again.
        """
        try:
            r = float(self.voronoi_band.get())
        except (tk.TclError, ValueError):
            return self._voronoi_band_last
        if r > 0:
            self._voronoi_band_last = r
        return self._voronoi_band_last

    def _voronoi_empty_reason(self, sites):
        """Why the tessellation came back empty -- the legend says this, so
        it has to name the actual cause rather than guess at the commonest
        one. Blaming model size for a degenerate hull sends you off tuning a
        setting that was never the problem."""
        if self.voronoi_view.get() == sv3.VIEW_CELLS and len(sites) > sv3.CELLS_SITE_LIMIT:
            return (f'{len(sites)} cells is past the interactive limit '
                    f'({sv3.CELLS_SITE_LIMIT}) — use Skin or Section')
        if sv3.hull_of(self.nodes) is None:
            return 'the model is flat or too small to enclose a volume'
        if self.voronoi_domain.get() == sv3.DOMAIN_BAND:
            return (f'nothing lies within r={self._voronoi_band_value():g} m of a rod '
                    f'— try a larger radius')
        return 'nothing to tessellate here'

    def _voronoi_patches(self, sites):
        """The tessellation's patches, rebuilt only when something it
        actually depends on has changed.

        Being in model space, the tessellation does NOT depend on the camera
        -- which is the whole point of moving it off the screen -- so orbiting
        reuses this cache and only re-projects.
        """
        key = (len(self.nodes), len(self.members), len(sites),
               self.voronoi_view.get(), self.voronoi_domain.get(),
               round(self._voronoi_band_value(), 4),
               self.voronoi_axis.get(), round(float(self.voronoi_slice.get()), 4))
        if self._voronoi_cache is not None and self._voronoi_cache[0] == key:
            return self._voronoi_cache[1]
        patches = sv3.build(
            self.nodes, self.members, sites,
            self.voronoi_view.get(), self.voronoi_domain.get(),
            band_r=self._voronoi_band_value(),
            section_axis='XYZ'.index(self.voronoi_axis.get()),
            section_position=float(self.voronoi_slice.get()) / 100.0)
        self._voronoi_cache = (key, patches)
        return patches

    def _reference_grey(self):
        """The reference (rest) structure's adjustable grey shade, used
        instead of its usual force/pin-rigid colouring whenever the
        deformed overlay is also on screen, so the reference reads as a
        faint backdrop rather than competing with the overlay for
        attention. 0 = black, 100 = near-white (never pure white, so it
        stays visible against the canvas background)."""
        v = max(0, min(100, self.reference_shade.get()))
        level = int(round(v / 100.0 * 235))
        return f'#{level:02x}{level:02x}{level:02x}'

    def _draw_deformed_overlay(self, c, to_screen):
        """A wireframe copy of the structure, offset by the solved
        displacement (times the scale slider) and drawn through the SAME
        `to_screen` closure the rest structure uses -- so it deforms "in
        parallel to the at-rest structure and in the same place" rather
        than being independently re-centered (which would visually hide
        the very offset it is meant to show). Colour mode is a toggle:
        DEFORM_MODE_DISPLACEMENT colors each member/node along a white-to-
        green spectrum by how much it actually moved (deform_color), so
        the AMOUNT of displacement is visible at a glance and not just its
        direction -- mirroring truss_app.py's green deformed-shape
        overlay, with that added per-element spectrum; DEFORM_MODE_FORCE
        instead colors each member by its own axial force (the same red/
        blue force_color every other view in this app uses), so the
        deformed shape can be read together with which members are in
        tension vs compression. Support nodes get the same small box
        glyph the reference structure uses, so a support's (typically
        zero) displacement reads clearly even with the reference hidden
        ("Deformed only")."""
        deformed, disp_mm = self._deformed_nodes_and_disp()
        proj_def = [self._project(x, y, z) for x, y, z in deformed]
        max_disp = max(disp_mm, default=0.0)
        by_force_mode = self.deform_color_mode.get() == DEFORM_MODE_FORCE
        frac = self._load_frac()
        max_abs_N = 0.0
        if by_force_mode:
            max_abs_N = max((abs(mr['N']) for mr in self.results['member_res']), default=0.0)

        # The displacement gradient needs no averaging: displacement IS a
        # nodal result, so each rod interpolates between two real solved
        # values. Colouring by force instead averages onto the joints the
        # same way the rest structure does.
        gradient = self.smooth_gradient.get()
        grad_values = grad_color_fn = None
        if gradient:
            if by_force_mode:
                forces = [mr['N'] * frac for mr in self.results['member_res']]
                grad_values = self._nodal_average(len(self.nodes), self.members, forces)
                grad_color_fn = lambda v: force_color(v, max_abs_N)
            else:
                grad_values = list(disp_mm)
                grad_color_fn = lambda v: deform_color(v, max_disp)

        for i, m in enumerate(self.members):
            a, b = m['a'], m['b']
            ax, ay, _ = proj_def[a]
            bx, by, _ = proj_def[b]
            sx0, sy0 = to_screen(ax, ay)
            sx1, sy1 = to_screen(bx, by)
            if grad_values is not None:
                self._draw_gradient_line(c, sx0, sy0, sx1, sy1,
                                         grad_values[a], grad_values[b],
                                         grad_color_fn, 2, 'deform')
                continue
            if by_force_mode:
                color = force_color(self.results['member_res'][i]['N'] * frac, max_abs_N)
            else:
                color = deform_color((disp_mm[a] + disp_mm[b]) / 2.0, max_disp)
            c.create_line(sx0, sy0, sx1, sy1, fill=color, width=2, tags='deform')

        for i, (px, py, _) in enumerate(proj_def):
            sx, sy = to_screen(px, py)
            color = '#333333' if by_force_mode else deform_color(disp_mm[i], max_disp)
            c.create_oval(sx - 3, sy - 3, sx + 3, sy + 3, fill=color, outline='', tags='deform')

        support_nodes = {s['node'] for s in self.supports
                         if any(sm.support_restraints(s).values())}
        for i in support_nodes:
            px, py, _ = proj_def[i]
            sx, sy = to_screen(px, py)
            h = SUPPORT_BOX_HALF_PX
            c.create_rectangle(sx - h, sy - h, sx + h, sy + h, outline=SUPPORT_COLOR,
                               width=2, tags='deform')

    def _draw_load_arrows(self, c, to_screen):
        """Arrows for every node currently carrying nonzero net load (point
        loads + area load + self-weight, whichever are enabled -- the same
        combined recipe _all_loads() feeds to the solver), sized with
        common.LoadScale exactly the way every other tab draws a load
        glyph, so a model with loads spanning orders of magnitude still
        shows visible contrast at every node instead of one huge arrow and
        a field of invisible stubs. Shrinks with the 'Load %' slider (the
        arrows show the load actually being analyzed right now, not just
        the full specified load) while the underlying LoadScale keeps
        using the FULL-load magnitudes as its reference band, so easing
        the slider down shrinks the arrows smoothly instead of having them
        all rescale relative to a shrinking max."""
        if not self._load_glyphs:
            return
        frac = self._load_frac()
        if frac < 1e-9:
            return
        mags = [math.sqrt(fx * fx + fy * fy + fz * fz)
               for fx, fy, fz in self._load_glyphs.values()]
        scale = LoadScale.of(mags, 6.0, 20.0)
        eps = 1e-3
        for i, (fx, fy, fz) in self._load_glyphs.items():
            mag = math.sqrt(fx * fx + fy * fy + fz * fz)
            if mag < 1e-9 or not (0 <= i < len(self.nodes)):
                continue
            x, y, z = self.nodes[i]
            ux_, uy_, uz_ = fx / mag, fy / mag, fz / mag
            px0, py0, _ = self._project(x, y, z)
            px1, py1, _ = self._project(x + ux_ * eps, y + uy_ * eps, z + uz_ * eps)
            sx0, sy0 = to_screen(px0, py0)
            sx1, sy1 = to_screen(px1, py1)
            ddx, ddy = sx1 - sx0, sy1 - sy0
            d = math.hypot(ddx, ddy)
            if d < 1e-9:
                continue
            length = scale(mag) * frac
            ddx, ddy = ddx / d * length, ddy / d * length
            # Arrowhead points AT the node (the load acts ON it); the tail
            # trails away in the load's own direction.
            c.create_line(sx0 - ddx, sy0 - ddy, sx0, sy0, fill=LOAD_COLOR, width=1.5,
                         arrow=tk.LAST, arrowshape=(5, 6, 2), tags='load')

    def _draw_reaction_arrows(self, c, to_screen, proj):
        """Arrows at every support showing its solved reaction force
        (Fx, Fy, Fz -- moments are not drawn, there is no clean glyph for
        a 3D couple), sized the same LoadScale way as the applied-load
        arrows so the two are visually comparable, and drawn in a distinct
        colour so the two are never confused with each other. The tail
        sits at the support node and the arrow points AWAY from it, in the
        reaction's own direction -- the opposite convention from load
        arrows (which point INTO the node) -- since a reaction is the
        support pushing back on the structure, not a load acting on it.
        Scales with the 'Load %' slider exactly like everything else that
        reads self.results, since a reaction scales linearly with the
        applied load in a linear-elastic solve."""
        reactions = self.results.get('reactions', {})
        if not reactions:
            return
        frac = self._load_frac()
        if frac < 1e-9:
            return
        mags = {i: math.sqrt(r.get('Fx', 0.0) ** 2 + r.get('Fy', 0.0) ** 2
                             + r.get('Fz', 0.0) ** 2) for i, r in reactions.items()}
        scale = LoadScale.of(mags.values(), 6.0, 24.0)
        eps = 1e-3
        for i, mag in mags.items():
            if mag < 1e-9 or not (0 <= i < len(self.nodes)):
                continue
            r = reactions[i]
            fx, fy, fz = r.get('Fx', 0.0), r.get('Fy', 0.0), r.get('Fz', 0.0)
            x, y, z = self.nodes[i]
            ux_, uy_, uz_ = fx / mag, fy / mag, fz / mag
            px0, py0, _ = self._project(x, y, z)
            px1, py1, _ = self._project(x + ux_ * eps, y + uy_ * eps, z + uz_ * eps)
            sx0, sy0 = to_screen(px0, py0)
            sx1, sy1 = to_screen(px1, py1)
            ddx, ddy = sx1 - sx0, sy1 - sy0
            d = math.hypot(ddx, ddy)
            if d < 1e-9:
                continue
            length = scale(mag) * frac
            ddx, ddy = ddx / d * length, ddy / d * length
            c.create_line(sx0, sy0, sx0 + ddx, sy0 + ddy, fill=REACTION_COLOR, width=2,
                         arrow=tk.LAST, arrowshape=(6, 7, 3), tags='reaction')

    AXIS_COLOR_X = '#c0392b'
    AXIS_COLOR_Y = '#1e8449'
    AXIS_COLOR_Z = '#2456c4'

    def _draw_axes(self, c, to_screen):
        """A small red/green/blue X/Y/Z gizmo anchored at the structure's
        OWN lowest corner (not a fixed on-screen HUD), plus a light dashed
        outline tracing the structure's own X/Y footprint at z=0 -- an
        explicit "this is the ground, this is up" reference so a shell or
        vault's own orientation is never ambiguous at a glance, regardless
        of camera angle. Sized off the model's own plan diagonal so the
        gizmo reads at a sensible scale whether the structure is 3m or
        300m across, instead of a fixed pixel size that would be
        imperceptible on a large model or overwhelming on a small one."""
        xs = [n[0] for n in self.nodes]
        ys = [n[1] for n in self.nodes]
        zs = [n[2] for n in self.nodes]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        z0 = min(0.0, min(zs))
        diag = math.hypot(x1 - x0, y1 - y0)
        axis_len = max(1.0, diag * 0.15)

        corners = ((x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0))
        pts = []
        for x, y, z in corners:
            px, py, _ = self._project(x, y, z)
            pts.append(to_screen(px, py))
        for i in range(4):
            sx0, sy0 = pts[i]
            sx1, sy1 = pts[(i + 1) % 4]
            c.create_line(sx0, sy0, sx1, sy1, fill='#bbbbbb', dash=(3, 3), tags='axes')

        origin = (x0, y0, z0)
        ox, oy, oz = origin
        p0x, p0y, _ = self._project(ox, oy, oz)
        s0 = to_screen(p0x, p0y)
        for (dx, dy, dz), color, label in (((axis_len, 0.0, 0.0), self.AXIS_COLOR_X, 'X'),
                                           ((0.0, axis_len, 0.0), self.AXIS_COLOR_Y, 'Y'),
                                           ((0.0, 0.0, axis_len), self.AXIS_COLOR_Z, 'Z')):
            p1x, p1y, _ = self._project(ox + dx, oy + dy, oz + dz)
            s1 = to_screen(p1x, p1y)
            c.create_line(s0[0], s0[1], s1[0], s1[1], fill=color, width=2,
                         arrow=tk.LAST, arrowshape=(6, 7, 3), tags='axes')
            c.create_text(s1[0], s1[1], text=label, fill=color,
                         font=('Helvetica', 9, 'bold'), tags='axes')

    def _draw_legend(self, c, by_force, show_def=False, deformed_only=False, by_util=False,
                     max_abs_N=0.0, max_abs_moment=0.0):
        x0, y0 = 10, 10
        y = y0
        BAR_W, BAR_H = 130, 10

        def row(color, text, dashed=False, outline=None):
            nonlocal y
            if outline:
                # a border drawn first, wider, so a white/near-white swatch
                # (e.g. the moment gradient's own zero-point) still shows
                # up against the canvas's own white background
                c.create_line(x0, y, x0 + 18, y, fill=outline, width=5)
            kw = {'fill': color, 'width': 3}
            if dashed:
                kw['dash'] = (5, 3)
            c.create_line(x0, y, x0 + 18, y, **kw)
            c.create_text(x0 + 24, y, text=text, anchor='w', font=('Helvetica', 8), fill='#444')
            y += 15

        def caption(text):
            nonlocal y
            c.create_text(x0, y, text=text, anchor='w', font=('Helvetica', 8, 'bold'), fill='#333')
            y += 13

        def colorbar(color_fn, lo, hi, ticks, n_segs=44):
            # A CONTINUOUS gradient strip standing in for what used to be 2-3
            # flat, hand-picked swatches (e.g. "tension" / "compression" /
            # "~0"): those never showed WHERE a given colour sat on the
            # actual numeric range, or that the mapping is a smooth gradient
            # rather than three discrete buckets. Segments call the SAME
            # colour function the model itself is drawn with (force_color /
            # util_color / moment_color / deform_color), each with the real
            # domain value that segment represents, so this can never drift
            # out of sync with what the drawing shows the way a separately
            # hand-picked set of swatch colours could. `ticks` are (value,
            # label) pairs placed at their proportional position along the
            # bar rather than assumed to sit at the two ends, since e.g.
            # utilization's "0.5" tick is not the domain's midpoint.
            nonlocal y
            span = (hi - lo) or 1.0
            for i in range(n_segs):
                # Colour sampled at i/(n_segs-1) -- NOT the segment's own
                # t0/t1 span -- so the first and last segments land exactly
                # on color_fn(lo) and color_fn(hi) rather than one step
                # short of hi (a real, if minor, mismatch against the
                # actual member/node colouring at the model's true extreme).
                frac_sample = i / (n_segs - 1) if n_segs > 1 else 0.0
                color = color_fn(lo + frac_sample * span)
                sx0 = x0 + (i / n_segs) * BAR_W
                sx1 = x0 + ((i + 1) / n_segs) * BAR_W + 1   # +1: no seam between segments
                c.create_rectangle(sx0, y, sx1, y + BAR_H, fill=color, outline='')
            c.create_rectangle(x0, y, x0 + BAR_W, y + BAR_H, outline='#888')
            ty = y + BAR_H + 9
            for value, label in ticks:
                frac_pos = (value - lo) / span
                tx = x0 + frac_pos * BAR_W
                anchor = 'w' if frac_pos <= 0.02 else ('e' if frac_pos >= 0.98 else 'center')
                c.create_text(tx, ty, text=label, anchor=anchor, font=('Helvetica', 8), fill='#444')
            y = ty + 12

        if not deformed_only:
            if by_util:
                caption('Utilization (demand ÷ capacity):')
                colorbar(util_color, 0.0, 1.2, [(0.0, '0'), (0.5, '0.5'), (1.0, '≥1.0 (over)')])
            elif by_force:
                caption('Axial force, kN (+ tension / − compression):')
                colorbar(lambda N: force_color(N, max_abs_N), -max_abs_N, max_abs_N,
                        [(-max_abs_N, f'−{max_abs_N:.0f}'), (0.0, '0'),
                         (max_abs_N, f'+{max_abs_N:.0f}')])
            else:
                row(MEMBER_PIN_COLOR, 'pin connection')
                row(MEMBER_RIGID_COLOR, 'rigid connection')
            # Its own row, with an ACTUAL dashed swatch: dashed members
            # were previously folded into the "~0" colour row's text,
            # which never explained what the dashes themselves meant (a
            # point of real confusion -- e.g. supporting only two opposite
            # edges of a grid concentrates force until many members go
            # over capacity and turn dashed, with no visible link back to
            # this line otherwise).
            row('#555555', 'dashed = over capacity (utilization > 1.0)', dashed=True)
            if self.hide_zero_force.get() and self.results is not None:
                caption('Rods reading ~0 force are hidden entirely (not just dimmed)')
            if self.smooth_gradient.get() and self.results is not None:
                caption('Rods blend between their two end values — joint values '
                       'are exact for moment/deformation, averaged for force/util.')
            if self.thickness_by_stress.get() and self.results is not None:
                caption(f'Rod thickness = axial stress |N|/A vs the model\'s own '
                       f'max (capped at {STRESS_WIDTH_MAX:.0f}px)')
            if self.shaded_faces.get() and self.results is not None:
                caption('Shaded faces: flat colour/panel (approx., not a shell FEA)')
            if self.voronoi_faces.get() and self.results is not None and self._voronoi_note:
                caption(f'Voronoi: {self._voronoi_note}')
            if self.voronoi_faces.get() and self.results is not None:
                nodal = self.colour_by_moment.get() or (
                    self.show_deformed.get() and not self.colour_by_force.get()
                    and not self.colour_by_util.get())
                caption(f'3D Voronoi · {self.voronoi_view.get()} of the '
                       f'{self.voronoi_domain.get().lower()}'
                       + (f" (r={self._voronoi_band_value():g} m)"
                          if self.voronoi_domain.get() == sv3.DOMAIN_BAND else '')
                       + f", sites = {'nodes' if nodal else 'rod midpoints'}")
            if self.flag_slender.get() and self.member_checks is not None:
                row(SLENDER_HALO_COLOR, f'halo = slender compression member '
                                       f'(KL/r > {SLENDERNESS_LIMIT:.0f})', dashed=True)
            if self.show_reactions.get() and self.results is not None:
                row(REACTION_COLOR, 'reaction (support pushing back)')
            if self.colour_by_moment.get() and self.results is not None:
                axis_txt = self.moment_axis.get()
                caption(f'Node moment, kN·m ({axis_txt}):')
                colorbar(lambda m: moment_color(m, max_abs_moment), -max_abs_moment, max_abs_moment,
                        [(-max_abs_moment, f'−{max_abs_moment:.1f}'), (0.0, '0'),
                         (max_abs_moment, f'+{max_abs_moment:.1f}')])
                # With the smooth gradient on, the rods carry the moment field
                # themselves rather than fading out of the way of the nodes,
                # so the backdrop note would be describing the opposite of
                # what is on screen.
                if self.smooth_gradient.get():
                    row(MOMENT_BACKDROP_COLOR, 'rods carry the same moment field, blended '
                                               'between their joints', outline='#999999')
                else:
                    row(MOMENT_BACKDROP_COLOR,
                        'members faded to backdrop (node colour is the content)')
            if self._disabled_supports & {s['node'] for s in self.supports}:
                row(SUPPORT_DISABLED_COLOR, 'sandbox: support disabled (excluded from Analyze)',
                   dashed=True)
            if self.load_path_anim.get() and self.results is not None:
                row(LOAD_PATH_COLOR, 'moving arrows: inward = tension, outward = '
                                    'compression (not "the" load path)')

        if show_def:
            if self.deform_color_mode.get() == DEFORM_MODE_FORCE:
                row(TENSION_HIGH, 'deformed shape: tension')
                row(COMPRESSION_HIGH, 'deformed shape: compression')
            else:
                _deformed, disp_mm = self._deformed_nodes_and_disp()
                max_disp = max(disp_mm, default=0.0)
                caption('Deformed shape, displacement (mm):')
                colorbar(lambda d: deform_color(d, max_disp), 0.0, max_disp,
                        [(0.0, '0'), (max_disp, f'{max_disp:.1f}')])

        if self.add_rod_mode.get():
            msg = ('Add rod: click a SECOND node to connect (dashed ring = pending)'
                  if self._add_rod_first is not None else
                  'Add rod: click a node to start a new rod')
            c.create_text(x0, y, anchor='w', font=('Helvetica', 8, 'bold'), fill='#a35a12',
                         text=msg)
            y += 15

        frac = self._load_frac()
        if frac < 0.999:
            c.create_text(x0, y, anchor='w', font=('Helvetica', 8, 'bold'), fill='#a3241a',
                         text=f'Load: {frac * 100:.0f}% of applied')
            y += 15

        hint_y = y + 6
        c.create_text(x0, hint_y, anchor='nw', font=('Helvetica', 8), fill='#888',
                     text='left-drag: lasso select (+Shift: add)  ·  right-drag: orbit\n'
                          'wheel: zoom  ·  middle-drag: pan  ·  □ box = support\n'
                          'click a rod to inspect its force/utilization')
