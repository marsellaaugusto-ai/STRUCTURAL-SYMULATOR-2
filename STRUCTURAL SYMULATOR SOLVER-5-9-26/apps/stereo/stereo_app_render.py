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
from apps.stereo.stereo_app_canvas_geom import _voronoi_cells_2d
from apps.stereo.stereo_app_constants import (
    NODE_COLOR, NODE_SEL_COLOR, ADD_ROD_PENDING_COLOR,
    SUPPORT_COLOR, SUPPORT_DISABLED_COLOR, SUPPORT_BOX_HALF_PX,
    MEMBER_PIN_COLOR, MEMBER_RIGID_COLOR, MEMBER_SEL_COLOR,
    TENSION_HIGH, COMPRESSION_HIGH, LOAD_COLOR, REACTION_COLOR,
    DEFORM_MODE_FORCE, SLENDER_HALO_COLOR, SLENDERNESS_LIMIT,
    LOAD_PATH_COLOR, LOAD_PATH_NEAR_ZERO_FRAC, LOAD_PATH_ARROW_HALF_PX,
    LOAD_PATH_ANIM_TICKS,
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
                    # Same near-zero threshold force_color already uses to
                    # flag a member NEAR_ZERO_COLOR -- this hides exactly
                    # the members that colouring already calls "~0", so the
                    # two stay consistent: a member never reads as "~0" in
                    # one and "clearly carrying load" in the other. Skipped
                    # entirely (no line, no halo) rather than dimmed, since
                    # the point is decluttering the path, not softening it.
                    N_hide = self.results['member_res'][i]['N'] * frac
                    if abs(N_hide) / max_abs_N_lp < LOAD_PATH_NEAR_ZERO_FRAC:
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
                if chk and chk.get('checked') and chk['util'] * frac > 1.0:
                    over = True
                    width = 3
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
            # Nodes-by-moment: every rigid (moment-transmitting) joint in
            # the grid gets its own value, not just supports -- a support's
            # own reaction Mx/My/Mz (SOMETHING must transfer moment into it:
            # a rigid connection scheme, or a directly-applied point
            # moment), and every ordinary interior joint touched by at
            # least one rigid member gets sm.node_moment_vectors's own
            # value (the largest-magnitude incident member end, expressed
            # in the same global axes reactions already use -- see that
            # function's own docstring for why a plain sum across incident
            # members would be wrong here). A purely pin-jointed model
            # reacts to force alone, so every node reads ~0 here regardless
            # of load -- an accurate reflection of the physics, not a sign
            # the feature is broken on that kind of model. max_abs_moment
            # spans the WHOLE grid (supports and interior joints alike) so
            # the colour of any one node is always relative to every other
            # node currently in the structure, not to supports alone.
            moment_by_node = {}
            if by_moment:
                moment_axis = self.moment_axis.get()
                # The structure's own planar centroid -- see
                # reaction_moment_signed's own docstring for why the
                # RESULTANT mode's sign is projected relative to it
                # (symmetric nodes must read the same colour, which a raw
                # Mx/My component cannot guarantee).
                centroid_xy = (sum(n[0] for n in self.nodes) / len(self.nodes),
                              sum(n[1] for n in self.nodes) / len(self.nodes))
                for i in support_nodes:
                    r = self.results['reactions'].get(i)
                    if r is not None:
                        node_xy = (self.nodes[i][0], self.nodes[i][1])
                        m = reaction_moment_signed(r, moment_axis, node_xy, centroid_xy) * frac
                        moment_by_node[i] = m
                        max_abs_moment = max(max_abs_moment, abs(m))
                node_vecs = sm.node_moment_vectors(self.nodes, self.members,
                                                   self.results['member_res'])
                for i, vec in node_vecs.items():
                    if i in moment_by_node:
                        continue   # a support's own reaction already wins
                    node_xy = (self.nodes[i][0], self.nodes[i][1])
                    m = reaction_moment_signed(vec, moment_axis, node_xy, centroid_xy) * frac
                    moment_by_node[i] = m
                    max_abs_moment = max(max_abs_moment, abs(m))
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
        """An alternative to _draw_shaded_faces that needs no mesh-topology
        cells at all: a 2D Voronoi tessellation of whichever points the
        active colour mode is actually about, each cell filled with that
        point's own colour. Since it works from bare proximity rather
        than find_cells's panels, it still produces a continuous-looking
        shaded sheet on a mesh with no clean quad/triangle faces to find
        (a sparse dome, a one-off rod added by hand, ...) -- the same
        "read it as one sheet" goal as the shaded-faces mode, by a
        different, cell-free means.

        Moment mode's sites are the NODES themselves -- moment is a
        nodal quantity, so this is the natural choice. Force/utilization
        mode's sites are each member's own MIDPOINT: a member has no
        single point that is uniquely "where its value lives", so this
        is a reasonable but genuinely debatable stand-in, flagged as such
        in the legend caption this mode adds rather than presented as
        the one correct answer.

        Same precedence as _draw_shaded_faces (utilization, then force,
        then moment -- at most one fill layer at a time), same flat-
        colour-per-cell caveat (Tk canvas polygons cannot blend a smooth
        gradient across a cell), and drawn then tag_lower'd behind
        everything else the same way.
        """
        points, colors = [], []
        if by_util and self.member_checks is not None:
            for i, m in enumerate(self.members):
                if i >= len(self.member_checks) or not self.member_checks[i].get('checked'):
                    continue
                ax, ay, _ = proj[m['a']]
                bx, byy, _ = proj[m['b']]
                sx0, sy0 = to_screen(ax, ay)
                sx1, sy1 = to_screen(bx, byy)
                points.append(((sx0 + sx1) / 2.0, (sy0 + sy1) / 2.0))
                colors.append(util_color(self.member_checks[i]['util'] * frac))
        elif by_force and self.results is not None:
            for i, m in enumerate(self.members):
                ax, ay, _ = proj[m['a']]
                bx, byy, _ = proj[m['b']]
                sx0, sy0 = to_screen(ax, ay)
                sx1, sy1 = to_screen(bx, byy)
                points.append(((sx0 + sx1) / 2.0, (sy0 + sy1) / 2.0))
                N = self.results['member_res'][i]['N'] * frac
                colors.append(force_color(N, max_abs_N))
        elif by_moment and moment_by_node:
            for n, m_val in moment_by_node.items():
                px, py, _ = proj[n]
                points.append(to_screen(px, py))
                colors.append(moment_color(m_val, max_abs_moment))
        else:
            return

        for idx, poly in _voronoi_cells_2d(points):
            c.create_polygon(*poly, fill=colors[idx], outline='', tags='voronoi_face')
        c.tag_lower('voronoi_face')

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

        for i, m in enumerate(self.members):
            a, b = m['a'], m['b']
            ax, ay, _ = proj_def[a]
            bx, by, _ = proj_def[b]
            sx0, sy0 = to_screen(ax, ay)
            sx1, sy1 = to_screen(bx, by)
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
            row('#555555', 'dashed = over capacity (utilisation > 1.0)', dashed=True)
            if self.hide_zero_force.get() and self.results is not None:
                caption('Rods reading ~0 force are hidden entirely (not just dimmed)')
            if self.shaded_faces.get() and self.results is not None:
                caption('Shaded faces: flat colour/panel (approx., not a shell FEA)')
            if self.voronoi_faces.get() and self.results is not None:
                caption('Voronoi cells: by node (moment) or rod midpoint (force/util.)')
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
                row(MOMENT_BACKDROP_COLOR, 'members faded to backdrop (node colour is the content)')
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
