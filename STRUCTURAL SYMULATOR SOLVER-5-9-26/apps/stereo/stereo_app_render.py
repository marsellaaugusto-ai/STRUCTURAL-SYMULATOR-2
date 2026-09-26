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
    load_path_color,
    force_color, deform_color, util_color, moment_color,
    reaction_moment_signed,
)
from apps.stereo import stereo_voronoi_surface as svs
from apps.stereo.stereo_app_constants import (
    NODE_COLOR, NODE_SEL_COLOR, ADD_ROD_PENDING_COLOR, AXIS_EXTEND_COLOR,
    SUPPORT_COLOR, SUPPORT_DISABLED_COLOR, SUPPORT_BOX_HALF_PX,
    MEMBER_PIN_COLOR, MEMBER_RIGID_COLOR, MEMBER_SEL_COLOR,
    TENSION_HIGH, COMPRESSION_HIGH, LOAD_COLOR, REACTION_COLOR, NEAR_ZERO_FRAC,
    NEAR_ZERO_COLOR,
    DEFORM_MODE_FORCE, SLENDER_HALO_COLOR, SLENDERNESS_LIMIT,
    LOAD_PATH_NEAR_ZERO_FRAC, LOAD_PATH_ARROW_HALF_PX,
    LOAD_PATH_ANIM_TICKS, STRESS_WIDTH_MIN, STRESS_WIDTH_MAX,
    GRADIENT_SEGMENTS, GRADIENT_SEGMENTS_DENSE, GRADIENT_DENSE_MEMBERS,
    GRADIENT_DISABLE_MEMBERS, LABEL_DISABLE_NODES, LOAD_PATH_DISABLE_MEMBERS,
    MOMENT_ZERO_COLOR, MOMENT_NODE_OUTLINE, MOMENT_BACKDROP_COLOR,
    MOMENT_NODE_RADIUS_PX,
    SCALE_P95, FORCE_SCALE_PERCENTILE, CLIP_MARK_COLOR, CLIP_MARK_DASH,
    CELL_EDGE_COLOR, CELL_EDGE_WIDTH,
    FILL_DENSITY_STIPPLE, FILL_DENSITY_DEFAULT,
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

    def _force_anchor(self):
        """The value the axial-force colour ramp's two ends are pinned to.

        The literal peak keeps the legend's numbers true for every rod, but
        lets one extreme member set the scale for the whole model: measured
        across the 14 shipped grid families the MEDIAN rod carries only
        12-32% of the peak, so most of the structure lands in the pale middle
        of the ramp. The percentile anchor pins the ends lower and lifts that
        median from about 0.44 to 0.55 of the ramp; the few rods above it are
        then off the top of the scale, and _clipped_members marks them so
        they are never silently drawn as if they sat exactly at the end.
        """
        if self.results is None:
            return 0.0
        mags = sorted(abs(mr['N']) for mr in self.results['member_res'])
        if not mags:
            return 0.0
        if self.force_scale.get() != SCALE_P95 or len(mags) < 3:
            return mags[-1]
        pos = (len(mags) - 1) * FORCE_SCALE_PERCENTILE / 100.0
        lo = int(pos)
        hi = min(lo + 1, len(mags) - 1)
        return mags[lo] + (mags[hi] - mags[lo]) * (pos - lo)

    def _near_zero_counts(self, max_abs_N, frac):
        """(rods drawn grey, of those how many carry exactly zero).

        Grey means one specific thing -- below NEAR_ZERO_FRAC of the scale --
        and the legend reports it with a count so the claim can be checked
        against the member report rather than taken on trust. The second
        number matters structurally: a rod at exactly zero is doing nothing
        at all in this load case, which is a candidate for removal, and it is
        worth distinguishing from one merely carrying very little.
        """
        if self.results is None or max_abs_N <= 0.0:
            return 0, 0
        grey = exact = 0
        for mr in self.results['member_res']:
            n = abs(mr['N'] * frac)
            if n / max_abs_N < NEAR_ZERO_FRAC:
                grey += 1
                if n <= 1e-9 * max_abs_N:
                    exact += 1
        return grey, exact

    def _clipped_members(self, max_abs_N, frac):
        """The rods whose force runs off the top of the current ramp.

        Empty unless the percentile anchor is in use. They are drawn with a
        dark hairline over them, because otherwise a rod at twice the anchor
        and one exactly at it get the identical saturated end colour, and the
        picture would quietly under-report the very members that govern.
        """
        if self.results is None or max_abs_N <= 0.0:
            return set()
        if self.force_scale.get() != SCALE_P95:
            return set()
        return {i for i, mr in enumerate(self.results['member_res'])
                if abs(mr['N'] * frac) > max_abs_N * 1.0000001}

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
            max_abs_N = self._force_anchor()
        n_members = len(self.members)
        load_path_on = (self.load_path_anim.get() and self.results is not None
                        and n_members <= LOAD_PATH_DISABLE_MEMBERS)
        hide_zero_force = self.hide_zero_force.get() and self.results is not None
        max_abs_N_lp = max_abs_N
        if (load_path_on or hide_zero_force) and not by_force:
            max_abs_N_lp = max((abs(mr['N']) for mr in self.results['member_res']), default=0.0)

        # Thickness by stress is a RELATIVE measure (each member against the
        # most-stressed one), so unlike the force/utilization colours it is
        # deliberately not scaled by 'Load %': a linear solve scales every
        # member's stress by the same factor, leaving the ratios -- and so
        # the drawn widths -- identical at every setting of the slider.
        clipped = self._clipped_members(max_abs_N, frac) if by_force else set()
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
        gradient = (self.smooth_gradient.get() and self.results is not None
                    and n_members <= GRADIENT_DISABLE_MEMBERS)
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
                if i == self.selected_member or i in self.selected_members:
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
                if i in clipped:
                    # This rod's force is past the end of the ramp, so its
                    # colour is the same saturated end as one sitting exactly
                    # AT the anchor. The hairline says "there is more here
                    # than the colour can show" rather than letting the
                    # picture quietly under-report the governing members.
                    # Its own tag, not 'member': this hairline is an
                    # annotation ABOUT the rod, and anything measuring the
                    # drawn members (the thickness-by-stress widths, say)
                    # would otherwise read it as one of them.
                    c.create_line(sx0, sy0, sx1, sy1, fill=CLIP_MARK_COLOR, width=1,
                                 dash=CLIP_MARK_DASH, tags='clip_mark')
                if i == self.selected_member or i in self.selected_members:
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
                        # Coloured by the force the member is actually
                        # carrying, on the same red/tension, blue/compression
                        # ramp as everything else -- so the pulse now says HOW
                        # MUCH as well as which way, instead of painting every
                        # loaded member the one flat cyan it used to.
                        lp_color = load_path_color(N, max_abs_N_lp)
                        c.create_line(sx0, sy0, sx1, sy1, fill=lp_color, width=1,
                                     tags=('member', 'load_path'))
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
                                             fill=lp_color, width=2, arrow='last',
                                             arrowshape=(6, 7, 3),
                                             tags=('member', 'load_path'))

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

            if (self._axis_pending is not None
                    and len(self.selected_nodes) == 1):
                src = next(iter(self.selected_nodes))
                if src < len(proj):
                    dx, dy, dz = self._axis_pending
                    try:
                        length = self._axis_len_var.get()
                    except Exception:
                        length = 3.0
                    if length > 0:
                        ox, oy, oz = self.nodes[src]
                        ep = self._project(ox + dx * length,
                                           oy + dy * length,
                                           oz + dz * length)
                        sx0, sy0 = to_screen(*proj[src][:2])
                        sx1, sy1 = to_screen(ep[0], ep[1])
                        c.create_line(sx0, sy0, sx1, sy1,
                                      fill=AXIS_EXTEND_COLOR, width=2,
                                      dash=(6, 3), tags='axis_preview')
                        r = 4
                        c.create_oval(sx1 - r, sy1 - r, sx1 + r, sy1 + r,
                                      fill=AXIS_EXTEND_COLOR,
                                      outline=AXIS_EXTEND_COLOR,
                                      tags='axis_preview')

            if self.shaded_faces.get():
                self._draw_shaded_faces(c, proj, to_screen, frac, by_util, by_force,
                                        max_abs_N, by_moment, moment_by_node, max_abs_moment)

            if self.voronoi_faces.get():
                self._draw_voronoi_faces(c, proj, to_screen, frac, by_util, by_force,
                                         max_abs_N, by_moment, moment_by_node, max_abs_moment)

            n_nodes = len(self.nodes)
            if self.show_node_labels.get() and n_nodes <= LABEL_DISABLE_NODES:
                labels = []
                for i, (px, py, _) in enumerate(proj):
                    sx, sy = to_screen(px, py)
                    labels.append(c.create_text(sx + 8, sy - 8, text=str(i), anchor='w',
                                               font=('Helvetica', 7), fill='#555'))
                declutter_text(c, labels)

            if self.show_member_labels.get() and n_members <= LABEL_DISABLE_NODES:
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
                          max_abs_N=max_abs_N, max_abs_moment=max_abs_moment,
                          frac=frac, clipped=clipped)
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
        """Fill every mesh panel (stereo_geometry.find_cells's 3-/4-node
        cells) with a flat colour, so the structure reads as one continuous
        shaded sheet instead of a set of individually-coloured lines --
        closer to how an FEA contour plot presents a shell.

        This is a rendering approximation, not a new analysis: the underlying
        model is still a pin-jointed space TRUSS (discrete axial members, one
        force each), which has no continuum stress field to interpolate.
        Each panel carries ONE flat colour from the SAME colour functions the
        wireframe uses -- a coarse "low-poly" mosaic, since a Tk canvas
        polygon supports only one flat fill.

        Panels are painted BACK TO FRONT. Drawing them in find_cells order
        instead (as this did until 2026-09-14) let a panel on the far side of
        the model paint over one in front of it: across the 14 grid families
        48-84% of adjacent pairs in that order were out of depth order, which
        is what put stray wedges of the wrong colour over the near face of
        every dome and sphere.
        """
        cells = self._get_shaded_cells()
        if not cells:
            return
        drawn = []
        for cell in cells:
            color = self._panel_color(cell, frac, by_util, by_force, max_abs_N,
                                      by_moment, moment_by_node, max_abs_moment)
            if color is None:
                continue
            pts, depth = [], 0.0
            for n in cell['nodes']:
                px, py, d = proj[n]
                sx, sy = to_screen(px, py)
                pts.extend((sx, sy))
                depth += d
            drawn.append((depth / len(cell['nodes']), pts, color))
        drawn.sort(key=lambda t: -t[0])
        stipple = self._fill_stipple()
        for _depth, pts, color in drawn:
            c.create_polygon(*pts, fill=color, outline='', stipple=stipple,
                             tags='shaded_face')
        c.tag_lower('shaded_face')

    def _fill_stipple(self):
        """The Tk stipple pattern for the current 'shade' setting.

        Read through the table rather than stored as a pattern name, so the
        toolbar shows words a reader can choose between and the canvas gets
        the Tk pattern it needs. An unrecognised value falls back to the
        default rather than raising: the variable is a combobox, but nothing
        stops a saved session or a test from putting something else in it.
        """
        return FILL_DENSITY_STIPPLE.get(self.fill_density.get(),
                                        FILL_DENSITY_STIPPLE[FILL_DENSITY_DEFAULT])

    def _panel_color(self, cell, frac, by_util, by_force, max_abs_N,
                     by_moment, moment_by_node, max_abs_moment):
        """One panel's colour, or None when the active spectrum has nothing
        to say about it.

        Several rods meet on a panel and only one colour can be drawn, so
        they have to be combined. For the SIGNED spectra (axial force, nodal
        moment) that combination is the mean of the MAGNITUDES, carried back
        to the sign of whichever rod carries the most -- never the mean of
        the signed values. A truss panel normally pairs a chord in
        compression with a diagonal in tension, so a signed mean lands near
        zero and the panel is painted the near-zero grey: on the truss bridge
        that silently greyed 23% of all panels, and on the elliptic dome
        every one of those grey panels had a member carrying more than a
        quarter of the model's peak force. Utilization needs none of this --
        it is unsigned, so nothing can cancel.
        """
        if by_util and self.member_checks is not None:
            utils = [self.member_checks[mi]['util'] * frac
                     for mi in cell['members']
                     if mi < len(self.member_checks)
                     and self.member_checks[mi].get('checked')]
            return util_color(sum(utils) / len(utils)) if utils else None
        if by_force and self.results is not None:
            member_res = self.results['member_res']
            forces = [member_res[mi]['N'] * frac for mi in cell['members']
                      if mi < len(member_res)]
            return force_color(self._combine_signed(forces), max_abs_N) if forces else None
        if by_moment and moment_by_node:
            vals = [moment_by_node[n] for n in cell['nodes'] if n in moment_by_node]
            return (moment_color(self._combine_signed(vals), max_abs_moment)
                    if vals else None)
        return None

    @staticmethod
    def _combine_signed(values):
        """Mean magnitude, signed by the largest contributor -- see
        _panel_color for why a plain signed mean is wrong here."""
        if not values:
            return 0.0
        mag = sum(abs(v) for v in values) / len(values)
        governing = max(values, key=abs)
        return -mag if governing < 0 else mag

    def _draw_voronoi_faces(self, c, proj, to_screen, frac, by_util, by_force, max_abs_N,
                            by_moment, moment_by_node, max_abs_moment):
        """A Voronoi tessellation of the structure's own SURFACE, drawn
        behind the wireframe.

        The tessellation lives in MODEL space, not on the screen: the cells
        are attached to the structure and hold still while the camera moves.
        Its domain is the mesh's own panels, so it stops exactly where the
        structure stops -- see stereo_voronoi_surface for why a convex hull
        (which this replaced) invents a floor slab under every vault, and why
        the distance has to be measured along the fabric rather than through
        space. All four spectra can drive it: force, utilization, node moment
        and deformation.

        Cells carry one flat colour each -- a Tk canvas polygon cannot blend
        across itself -- so the smooth gradient remains the way to read a
        continuous field ALONG the rods.
        """
        self._voronoi_note = ''
        spec = self._voronoi_site_values(frac, by_util, by_force, max_abs_N,
                                        by_moment, moment_by_node, max_abs_moment)
        if spec is None:
            return
        sites, colours, kind = spec
        patches, edges = self._voronoi_patches(sites, kind)
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

        # Surface and Cells are both drawn STIPPLED. They wrap the outside of
        # the structure, so a solid fill lets the nearest patch hide every
        # patch behind it and the shape loses all depth. The density is
        # gray75 rather than a half-tone, chosen by comparing the four Tk
        # patterns side by side: at gray50 a Voronoi cell at the dark end of
        # the ramp came out the same pale wash as one in the middle, because
        # every stippled pixel is half canvas-white. The wireframe's own
        # legibility does not depend on this at all -- tag_lower puts the
        # whole fill beneath every rod, node and glyph on the canvas.
        # The Section plane stays solid: it is a cut FACE, and a cut you can
        # see through no longer reads as one.
        stipple = '' if self.voronoi_view.get() == svs.VIEW_SECTION \
            else self._fill_stipple()
        for _depth, pts, owner in drawn:
            c.create_polygon(*pts, fill=colours[owner], outline='',
                             stipple=stipple, tags='voronoi_face')
        # The cell OUTLINES, drawn over the fill. Without them a tessellation
        # whose neighbouring cells happen to carry similar values reads as one
        # continuous wash, which is the Surface view, not this one.
        for p0, p1 in edges:
            x0, y0, _ = self._project(*p0)
            x1, y1, _ = self._project(*p1)
            s0, s1 = to_screen(x0, y0), to_screen(x1, y1)
            c.create_line(s0[0], s0[1], s1[0], s1[1], fill=CELL_EDGE_COLOR,
                          width=CELL_EDGE_WIDTH, tags='voronoi_face')
        c.tag_lower('voronoi_face')

    def _voronoi_site_values(self, frac, by_util, by_force, max_abs_N,
                             by_moment, moment_by_node, max_abs_moment):
        """(sites, colour-per-site, kind) for whichever spectrum is active.

        `kind` is what lets the surface engine seed each panel from the sites
        lying ON it: 'member' sites are the rods of a panel, 'node' sites its
        corners. Moment and deformation are genuinely NODAL quantities, so
        their sites are the nodes. Force and utilization belong to a rod,
        which has no single point where its value uniquely lives, so the
        rod's midpoint stands in -- a reasonable choice but a genuinely
        debatable one, which is why the legend says which it used rather than
        leaving it implied.
        """
        if by_util and self.member_checks is not None:
            sites = [tuple((a + b) / 2.0 for a, b in
                           zip(self.nodes[m['a']], self.nodes[m['b']]))
                     for m in self.members]
            cols = [util_color((self.member_checks[i]['util'] * frac)
                               if i < len(self.member_checks)
                               and self.member_checks[i].get('checked') else 0.0)
                    for i in range(len(self.members))]
            return sites, cols, 'member'
        if by_force and self.results is not None:
            sites = [tuple((a + b) / 2.0 for a, b in
                           zip(self.nodes[m['a']], self.nodes[m['b']]))
                     for m in self.members]
            cols = [force_color(mr['N'] * frac, max_abs_N)
                    for mr in self.results['member_res']]
            return sites, cols, 'member'
        if by_moment and moment_by_node:
            cols = [moment_color(moment_by_node.get(i, 0.0), max_abs_moment)
                    for i in range(len(self.nodes))]
            return list(self.nodes), cols, 'node'
        if self.show_deformed.get() and self.results is not None:
            _deformed, disp_mm = self._deformed_nodes_and_disp()
            top = max(disp_mm, default=0.0)
            return list(self.nodes), [deform_color(d, top) for d in disp_mm], 'node'
        return None

    def _voronoi_cut_value(self):
        """The section's cut thickness, read defensively.

        It is bound to a typed Entry, so between two keystrokes its contents
        can be empty, half a number, or 'abc' -- and a DoubleVar raises on
        every one of those. A redraw runs on far more than the Return key
        (orbit, a toggle, the load slider), so an unguarded read turned an
        ordinary edit into a broken canvas. The last value that WAS a
        positive length is kept and used until the field makes sense again.
        """
        try:
            r = float(self.voronoi_cut.get())
        except (tk.TclError, ValueError):
            return self._voronoi_cut_last
        if r > 0:
            self._voronoi_cut_last = r
        return self._voronoi_cut_last

    def _voronoi_empty_reason(self, sites):
        """Why the tessellation came back empty -- the legend says this, so it
        has to name the actual cause rather than guess at the commonest one.
        Blaming model size for a mesh with no closed panels would send you off
        tuning a setting that was never the problem."""
        if len(sites) < 1:
            return 'there is nothing to tessellate yet'
        if not self._get_shaded_cells():
            return ('this mesh has no closed triangles or quads, so it has no '
                    'surface to tessellate')
        if self.voronoi_view.get() == svs.VIEW_SECTION:
            return (f'the cut plane misses the structure at this position '
                    f'(thickness {self._voronoi_cut_value():g} m)')
        return 'nothing to tessellate here'

    def _voronoi_patches(self, sites, kind):
        """(patches, cell-outline edges), rebuilt only when something they
        actually depend on has changed.

        Being in model space, the tessellation does NOT depend on the camera
        -- which is the whole point of moving it off the screen -- so orbiting
        reuses this cache and only re-projects.
        """
        view = self.voronoi_view.get()
        key = (len(self.nodes), len(self.members), len(sites), kind, view,
               round(self._voronoi_cut_value(), 4),
               self.voronoi_axis.get(), round(float(self.voronoi_slice.get()), 4))
        if self._voronoi_cache is not None and self._voronoi_cache[0] == key:
            return self._voronoi_cache[1]
        panels = self._get_shaded_cells()
        if view == svs.VIEW_SECTION:
            out = (svs.build_section(self.nodes, panels, sites,
                                     'XYZ'.index(self.voronoi_axis.get()),
                                     float(self.voronoi_slice.get()) / 100.0,
                                     self._voronoi_cut_value()), [])
        else:
            key_field = 'members' if kind == 'member' else 'nodes'
            panel_sites = [list(p[key_field]) for p in panels]
            # `members` is what lets the domain cover the rods no panel
            # contains -- a column shaft closes no triangle or quad, so
            # without this the fill stops at the underside of the grid and
            # the columns hang below it as bare lines.
            patches = svs.build_surface(self.nodes, panels, sites, panel_sites,
                                        members=self.members,
                                        per_node=(kind == 'node'))
            edges = []
            if view == svs.VIEW_CELLS and panels:
                polys = svs.panel_polys(self.nodes, panels)
                adj, _ = svs.panel_adjacency(panels)
                owners = svs.assign_owners(svs.panel_centroids(polys), panel_sites,
                                           sites, adj)
                edges = svs.cell_boundary_edges(self.nodes, self.members, panels, owners)
            out = (patches, edges)
        self._voronoi_cache = (key, out)
        return out

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
            max_abs_N = self._force_anchor()

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
    # How far past the model each axis line is extended, as a multiple of
    # the model's own reach from the origin. Large enough that both ends
    # leave the canvas at any zoom a user would work at, which is what makes
    # the axis read as an infinite line rather than a stub; not so large that
    # the projected coordinates lose precision.
    AXIS_REACH = 60.0

    def _draw_axes(self, c, to_screen):
        """The Cartesian X/Y/Z axes as LINES, plus a light dashed outline
        tracing the structure's own footprint at z = 0.

        Each axis is drawn right across the canvas rather than as a short
        stub at the model's corner: an axis is an infinite line, and a stub
        reads as a little arrow decoration sitting beside the structure
        instead of as the coordinate frame the model is measured in. The
        line is extended in MODEL space until both its ends are off-screen,
        so it stays a straight line under the projection and keeps arriving
        at the right vanishing direction however the camera is orbited.

        The frame is anchored at the true origin (0, 0, 0), which is what
        the coordinates in every panel, the Excel export and the member
        report are stated in -- not at the model's own lowest corner, which
        moves whenever the mesh does and would make the same rod appear to
        sit somewhere different after a regenerate.
        """
        xs = [n[0] for n in self.nodes]
        ys = [n[1] for n in self.nodes]
        zs = [n[2] for n in self.nodes]
        if not xs:
            return
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)

        corners = ((x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0))
        pts = []
        for x, y, z in corners:
            px, py, _ = self._project(x, y, z)
            pts.append(to_screen(px, py))
        for i in range(4):
            sx0, sy0 = pts[i]
            sx1, sy1 = pts[(i + 1) % 4]
            c.create_line(sx0, sy0, sx1, sy1, fill='#bbbbbb', dash=(3, 3), tags='axes')

        # Long enough that the line always leaves the canvas: the model's own
        # extent plus its distance from the origin, times a comfortable
        # margin. Derived from the model rather than fixed, so the axes read
        # at the same scale whether the structure is 3 m or 300 m across.
        # Per axis, because a model is rarely the same size in all three:
        # on a 15 m long, 3 m tall vault a single shared reach would put the
        # Z arrowhead five model-heights above the roof, off the canvas.
        reach = [max(abs(x0), abs(x1)), max(abs(y0), abs(y1)),
                 max(abs(min(zs)), abs(max(zs)))]
        span = max(x1 - x0, y1 - y0, max(zs) - min(zs), 1.0)
        far = (max(reach) + span) * self.AXIS_REACH
        tick = max(span * 0.08, 1e-3)

        p0x, p0y, _ = self._project(0.0, 0.0, 0.0)
        s_origin = to_screen(p0x, p0y)
        for axis, color, label in ((0, self.AXIS_COLOR_X, 'X'),
                                   (1, self.AXIS_COLOR_Y, 'Y'),
                                   (2, self.AXIS_COLOR_Z, 'Z')):
            ends = []
            for sign in (-1.0, 1.0):
                v = [0.0, 0.0, 0.0]
                v[axis] = sign * far
                px, py, _ = self._project(*v)
                ends.append(to_screen(px, py))
            # The negative half is drawn thin and the positive half solid, so
            # which way the axis increases is readable without hunting for
            # the arrowhead.
            c.create_line(ends[0][0], ends[0][1], s_origin[0], s_origin[1],
                         fill=color, width=1, dash=(4, 4), tags='axes')
            c.create_line(s_origin[0], s_origin[1], ends[1][0], ends[1][1],
                         fill=color, width=1, tags='axes')
            # The arrowhead sits ON the axis a little way out from the model,
            # not at the end of the line, which is off-screen by design.
            at = max(reach[axis], span * 0.25) + tick
            head = [0.0, 0.0, 0.0]
            head[axis] = at + tick
            hx, hy, _ = self._project(*head)
            s_head = to_screen(hx, hy)
            back = [0.0, 0.0, 0.0]
            back[axis] = at
            bx, by, _ = self._project(*back)
            s_back = to_screen(bx, by)
            c.create_line(s_back[0], s_back[1], s_head[0], s_head[1], fill=color,
                         width=2, arrow=tk.LAST, arrowshape=(7, 8, 3), tags='axes')
            c.create_text(s_head[0], s_head[1] - 9, text=label, fill=color,
                         font=('Helvetica', 9, 'bold'), tags='axes')

    def _draw_legend(self, c, by_force, show_def=False, deformed_only=False, by_util=False,
                     max_abs_N=0.0, max_abs_moment=0.0, frac=1.0, clipped=()):
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

        def scaled(quantity, stored):
            """A stored value written in the convention the rest of the tab
            is using. The colourbar's own COLOURS stay in stored units --
            force_color and friends only ever see a ratio, so converting
            them would change nothing -- but its tick labels and its unit
            word are read as numbers, and under AISC the tables beside this
            legend say kip while these said kN."""
            shown = self.show(quantity, stored)
            return shown, ('.0f' if abs(shown) >= 10.0 else '.2f')

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
                caption(f'Axial force, {self.u("force")} '
                        '(+ tension / − compression):')
                shown_N, spec = scaled('force', max_abs_N)
                ends = (f'−{shown_N:{spec}}', f'+{shown_N:{spec}}')
                if self.force_scale.get() == SCALE_P95:
                    ends = (f'≤−{shown_N:{spec}}', f'≥+{shown_N:{spec}}')
                colorbar(lambda N: force_color(N, max_abs_N), -max_abs_N, max_abs_N,
                        [(-max_abs_N, ends[0]), (0.0, '0'), (max_abs_N, ends[1])])
                # Grey is a claim about the structure, so the legend backs it
                # with the count. Without this, a field of grey panels reads
                # as "the drawing failed" when it in fact says "these rods
                # carry nothing" -- and on these models a good half of them
                # carry EXACTLY nothing, which is worth knowing.
                n_grey, n_exact = self._near_zero_counts(max_abs_N, frac)
                if n_grey:
                    row(NEAR_ZERO_COLOR,
                        f'~0: {n_grey} rods below {NEAR_ZERO_FRAC:.0%} of the scale'
                        + (f' ({n_exact} carry exactly zero)' if n_exact else ''))
                if clipped:
                    row(CLIP_MARK_COLOR, f'hairline: {len(clipped)} rods past the '
                                        f'end of this scale', dashed=True)
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
                view = self.voronoi_view.get()
                where = ("the structure's own surface" if view != svs.VIEW_SECTION
                         else f'a {self._voronoi_cut_value():g} m cut through the fabric')
                caption(f'Voronoi · {view} · {where}'
                       + f", sites = {'nodes' if nodal else 'rod midpoints'}")
            if self.flag_slender.get() and self.member_checks is not None:
                row(SLENDER_HALO_COLOR, f'halo = slender compression member '
                                       f'(KL/r > {SLENDERNESS_LIMIT:.0f})', dashed=True)
            if self.show_reactions.get() and self.results is not None:
                row(REACTION_COLOR, 'reaction (support pushing back)')
            if self.colour_by_moment.get() and self.results is not None:
                axis_txt = self.moment_axis.get()
                caption(f'Node moment, {self.u("moment")} ({axis_txt}):')
                shown_m, spec = scaled('moment', max_abs_moment)
                colorbar(lambda m: moment_color(m, max_abs_moment), -max_abs_moment, max_abs_moment,
                        [(-max_abs_moment, f'−{shown_m:{spec}}'), (0.0, '0'),
                         (max_abs_moment, f'+{shown_m:{spec}}')])
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
                row(TENSION_HIGH, 'moving arrows: inward = tension, outward = '
                                  'compression (not "the" load path)')
                caption('   arrow colour = that rod\'s own axial force')

        if show_def:
            if self.deform_color_mode.get() == DEFORM_MODE_FORCE:
                row(TENSION_HIGH, 'deformed shape: tension')
                row(COMPRESSION_HIGH, 'deformed shape: compression')
            else:
                _deformed, disp_mm = self._deformed_nodes_and_disp()
                max_disp = max(disp_mm, default=0.0)
                caption(f'Deformed shape, displacement ({self.u("deflection")}):')
                shown_d, spec = scaled('deflection', max_disp)
                colorbar(lambda d: deform_color(d, max_disp), 0.0, max_disp,
                        [(0.0, '0'), (max_disp, f'{shown_d:{spec}}')])

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
                          'click a rod to inspect its force/utilization\n'
                          'arrows/PgUp/PgDn: extend rod along axis from selected node\n'
                          'drag a selected node to reposition it')
