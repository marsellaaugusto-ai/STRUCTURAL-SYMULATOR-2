"""Ready-made example scenes for the Stereo tab's "Load Example" menu.

Six examples, demonstrating the add-on features (columns, reinforcement
beams) and the Custom Surface Wizard's single- and two-surface generators
end to end, with sensible pre-picked node selections standing in for a
lasso click:

  1-2. A planar (flat) double-layer grid with columns AND a reinforcement
       beam added on top -- #1 a single-tier capital plus a single-tier
       beam, #2 a "two modules thick" capital plus a multi-layer beam, on
       a differently-patterned, larger grid.
  3-4. A single custom surface, sampled into a 3D (double-layer) space
       truss -- #3 a height-field paraboloid dish (Cartesian, square
       pattern), #4 a parametric half-cylinder (a shape no height field
       could express), sampled with the isometric pattern.
  5-6. Two independently-defined surfaces connected as a top/bottom
       double layer -- #5 a dish over a flat plane (Cartesian, square),
       #6 two concentric domes (Polar, diagonal).
  7-8. The dedicated curved-shell generators (stereo_geometry's own
       barrel_vault/dome, not the Custom Surface Wizard) shown directly,
       each pinned along the support lines its own docstring calls out
       as the structurally correct base -- #7 a circular-arch barrel
       vault along its two springing lines, #8 a Schwedler-rib dome
       along its base ring.

Each function returns the shared {'nodes','members','support_candidates'}
mesh dict, exactly like every stereo_geometry generator, so it drops
straight into StereoApp._load_mesh. Every one of them is checked in
tests/test_stereo_examples.py to actually analyze under self-weight when
pinned at its own support_candidates -- an example that doesn't solve
would be a poor advertisement for the feature it demonstrates.
"""
import math

from apps.stereo import stereo_bezier as _bz
from apps.stereo import stereo_geometry as sg


def _fit(expr, lo, hi, segments):
    """Fit a Bezier profile to a typed expression over [lo, hi] -- the same
    two steps the Shape panel's Fit button takes, so an example and a
    hand-driven fit cannot produce different curves."""
    surface = sg.make_height_field_surface(expr)
    return _bz.fit_profile(lambda t: surface(t, 0.0)[2], lo, hi, segments)


def _nodes_near(nodes, x, y, z=None, k=4):
    """Indices of the `k` nodes nearest to (x, y[, z]) -- stands in for a
    lasso click when the target nodes need to be picked in code."""
    def key(i):
        px, py, pz = nodes[i]
        dx, dy = px - x, py - y
        dz = 0.0 if z is None else pz - z
        return dx * dx + dy * dy + dz * dz
    return sorted(range(len(nodes)), key=key)[:k]


def _nodes_within(nodes, x, y, z, radius, z_tol=1e-6):
    """Every node index within planar `radius` of (x, y) at height `z` --
    used for a 2-tier column's footprint, which needs a wide, evenly
    spread set of targets (at least 2 per angular quadrant) rather than
    just the nearest few."""
    r2 = radius * radius
    return [i for i, (px, py, pz) in enumerate(nodes)
           if abs(pz - z) <= z_tol and (px - x) ** 2 + (py - y) ** 2 <= r2]


def _row_at(nodes, axis, value, z, tol=1e-6):
    """Every node index at nodes[i][axis] == value and nodes[i][2] == z
    (both within `tol`), sorted along the OTHER planar axis -- one clean
    row of an existing grid line, for reinforcement_beam's edge_a/edge_b."""
    other = 1 - axis
    idxs = [i for i, p in enumerate(nodes)
           if abs(p[axis] - value) <= tol and abs(p[2] - z) <= tol]
    idxs.sort(key=lambda i: nodes[i][other])
    return idxs


def _wizard(mesh, note, **fields):
    """Attach the Custom Surface Wizard settings that produce this example.

    Loading an example is the fastest way to see what the tab can build, and
    the obvious next question is "how do I make one of my own like it?".
    The answer is the wizard's own controls, so each example carries them and
    the wizard opens already filled in with them.

    `note` is required and has to be TRUE of this particular example. Several
    of these meshes are not built by the wizard at all -- they come straight
    from a stereo_geometry generator -- and for those the note names the
    generator and its arguments rather than inventing a surface expression
    that would not reproduce the mesh. A pre-filled field that quietly
    generates something else is worse than an empty one.
    """
    mesh['wizard'] = dict(note=note, **fields)
    return mesh


def planar_grid_with_columns_1():
    """A 12x12 m flat double-layer grid (square-on-square offset, 2 m
    module) on four single-tier columns at its quarter-points, with one
    single-tier reinforcement beam along the two grid lines nearest the
    centre -- the simplest version of "columns and beams added to a flat
    grid," one tier each.

    Supported ONLY at the four column bases -- not also along the base
    grid's own perimeter. Keeping the perimeter supports too (as an
    earlier version of this example did) leaves the columns carrying only
    a small fraction of the roof's own weight, since a fully perimeter-
    supported grid barely needs them -- a poor advertisement for the
    column feature it exists to demonstrate. Four well-spread pin
    supports (12 restrained DOF total) are enough to keep this fully
    double-layer-braced space truss stable on their own -- verified by
    this module's own tests actually solving it under self-weight."""
    mesh = sg.flat_grid(12.0, 12.0, 1.0, 2.0, offset=True, pattern='square')
    nodes, members = list(mesh['nodes']), list(mesh['members'])
    supports = []
    for cx, cy in ((3.0, 3.0), (9.0, 3.0), (3.0, 9.0), (9.0, 9.0)):
        targets = _nodes_near(nodes, cx, cy, z=0.0, k=4)
        nodes, members, bases, _head = sg.add_column(nodes, members, targets,
                                                      height=3.0, tiers=1)
        supports.extend(bases)
    edge_a = _row_at(nodes, 1, 4.0, 0.0)
    edge_b = _row_at(nodes, 1, 6.0, 0.0)
    nodes, members, _apex = sg.reinforcement_beam(nodes, members, edge_a, edge_b,
                                                  depth=1.0, tiers=1)
    return _wizard(
        {'nodes': nodes, 'members': members, 'support_candidates': supports,
         'load_nodes': mesh.get('load_nodes', {})},
        'Not a wizard surface -- flat_grid(12, 12, depth 1, module 2, square,\n'
        'offset) with four single-tier add_column() bases and one\n'
        'single-tier reinforcement_beam() built onto it.')


def planar_grid_with_columns_2():
    """A larger, 16x16 m flat double-layer grid (diagonal-on-diagonal
    chords, aligned layers, 2 m module) on ONE central "two modules
    thick" (tiers=2) column -- a heavier load calls for a deeper, wider
    capital transition -- plus a two-layer reinforcement beam along the
    two grid lines nearest one edge.

    A single column cannot, by itself, keep a pin-jointed roof from
    rocking about it (one point support fixes translation only -- with
    every member pin-connected there is no moment path to resist
    rotation about that one point either, so the roof would still be a
    genuine mechanism, not just "lightly redundant"). Rather than fall
    back to the FULL base-grid perimeter (which would swamp the column's
    own share of the load, the same problem fixed in
    planar_grid_with_columns_1), this example supports the roof's own
    four CORNERS plus the column -- just enough extra restraint for
    overall stability while the heavier central column still ends up
    carrying most of the load (roughly 70% of the total self-weight in
    this geometry, vs. under 30% split across the four corners)."""
    mesh = sg.flat_grid(16.0, 16.0, 1.2, 2.0, offset=False, pattern='diagonal')
    nodes, members = list(mesh['nodes']), list(mesh['members'])
    perim = mesh['support_candidates']
    xs = [nodes[i][0] for i in perim]
    ys = [nodes[i][1] for i in perim]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    supports = [i for i in perim if nodes[i][0] in (xmin, xmax) and nodes[i][1] in (ymin, ymax)]
    targets = _nodes_within(nodes, 8.0, 8.0, 0.0, radius=3.1)
    nodes, members, bases, _head = sg.add_column(nodes, members, targets,
                                                 height=4.0, tiers=2)
    supports.extend(bases)
    edge_a = _row_at(nodes, 1, 2.0, 0.0)
    edge_b = _row_at(nodes, 1, 4.0, 0.0)
    nodes, members, _apex = sg.reinforcement_beam(nodes, members, edge_a, edge_b,
                                                  depth=1.5, tiers=2)
    return _wizard(
        {'nodes': nodes, 'members': members, 'support_candidates': supports,
         'load_nodes': mesh.get('load_nodes', {})},
        'Not a wizard surface -- flat_grid(16, 16, depth 1.2, module 2,\n'
        'diagonal) with two-tier add_column() bases and a multilayer\n'
        'reinforcement_beam() built onto it.')


def single_surface_truss_1():
    """A paraboloid dish (a height field -- z = f(x, y)), Cartesian
    domain, square module pattern, sampled as a 3D (double-layer) space
    truss: the Custom Surface Wizard's simplest single-surface case."""
    expr = '3.0 * (1 - (x/6)^2 - (y/6)^2)'
    surface = sg.make_height_field_surface(expr)
    mesh = sg.custom_surface_grid(surface, coord='cartesian', pattern='square',
                                  p_range=(-6.0, 6.0), q_range=(-6.0, 6.0),
                                  n1=8, n2=8, module='3d', depth=0.6,
                                  offset_side='top')
    return _wizard(mesh, 'Built by the wizard. These are its exact settings.',
                   mode='single', kind='height', z=expr,
                   coord='cartesian', pattern='square',
                   p_range=(-6.0, 6.0), q_range=(-6.0, 6.0), n1=8, n2=8,
                   module='3d', depth=0.6, side='top')


def single_surface_truss_2():
    """An open half-cylinder -- a fully PARAMETRIC surface (x=u,
    y=4sin(v), z=4cos(v)), a shape no height field z=f(x,y) could
    express (a cylinder is vertical at its own springing lines) --
    sampled with the isometric (60-degree/equilateral-triangle) module
    pattern into a 3D space truss.

    q_range is centred on v=0 (-pi/2+eps to +pi/2-eps), not (eps, pi-eps):
    with y=4sin(v)/z=4cos(v), v=0 is the CROWN (y=0, z=+4, the top of the
    circle) and v=+-pi/2 are the two SPRINGING lines (y=+-4, z=0, where
    the cylinder's surface is locally vertical -- the docstring's own
    point). The earlier (eps, pi-eps) range instead put v=pi/2 -- a
    springing line -- in the MIDDLE and swept from near the true crown
    (v~0) past it to near the circle's BOTTOM (v~pi, z=-4): half the
    surface ended up below the ground plane, y never went negative, and
    the shape read as an arch opening sideways (toward +y) rather than
    arching upward, since what should have been the crown was rendered
    at one end, not the peak."""
    fx, fy, fz = 'u', '4*sin(v)', '4*cos(v)'
    surface = sg.make_parametric_surface(fx, fy, fz)
    q_range = (-math.pi / 2.0 + 0.3, math.pi / 2.0 - 0.3)
    mesh = sg.custom_surface_grid(surface, coord='cartesian', pattern='isometric',
                                  p_range=(0.0, 10.0), q_range=q_range,
                                  n1=10, n2=8, module='3d', depth=0.5,
                                  offset_side='top')
    return _wizard(mesh, 'Built by the wizard. These are its exact settings.',
                   mode='single', kind='parametric', x=fx, y=fy, z=fz,
                   coord='cartesian', pattern='isometric',
                   p_range=(0.0, 10.0), q_range=q_range, n1=10, n2=8,
                   module='3d', depth=0.5, side='top')


def two_surface_truss_1():
    """A shallow dish as the TOP surface over a flat plane as the BOTTOM
    surface, Cartesian domain, square pattern -- the Custom Surface
    Wizard's two-surface mode connecting two independently-defined
    surfaces into one double-layer grid.

    The dish is written over a 12 m half-width rather than the domain's own
    6 m, so it is still 2.50 m clear of the plane at the CORNERS of the
    square. That is the whole trap in two-surface design: the domain is a
    square and the surfaces are radial, so the corners sit 8.49 m from the
    centre while the edge midpoints sit 6.00 m. A dish that reached zero at
    r = 6.93 -- comfortably clear all the way along each edge -- had already
    crossed the plane by 2.00 m at every corner, and past a crossing the
    webs invert and the truss is inside out. custom_surface_between now
    refuses such a pair outright; see surfaces_cross.

    The depth still varies, which is the point of defining two surfaces
    rather than offsetting one: 4.00 m over the centre, 2.50 m at a corner.
    """
    top_expr = '3.0 * (1 - (x/12)^2 - (y/12)^2) + 1.0'
    bottom_expr = '0'
    top = sg.make_height_field_surface(top_expr)
    bottom = sg.make_height_field_surface(bottom_expr)
    mesh = sg.custom_surface_between(top, bottom, coord='cartesian', pattern='square',
                                     p_range=(-6.0, 6.0), q_range=(-6.0, 6.0),
                                     n1=8, n2=8)
    return _wizard(mesh, 'Built by the wizard. These are its exact settings.',
                   mode='between', kind='height', z=top_expr,
                   bottom_kind='height', bottom_z=bottom_expr,
                   coord='cartesian', pattern='square',
                   p_range=(-6.0, 6.0), q_range=(-6.0, 6.0), n1=8, n2=8)


def two_surface_truss_2():
    """Two CONCENTRIC domes (a taller one as the top surface, a
    shallower one as the bottom), Polar domain, diagonal pattern -- the
    two-surface case exercised over a curved domain instead of a flat
    rectangle."""
    top_expr = '4.0 * (1 - (x/6)^2 - (y/6)^2) + 2.0'
    bottom_expr = '2.0 * (1 - (x/6)^2 - (y/6)^2)'
    top = sg.make_height_field_surface(top_expr)
    bottom = sg.make_height_field_surface(bottom_expr)
    mesh = sg.custom_surface_between(top, bottom, coord='polar', pattern='diagonal',
                                     p_range=(0.3, 6.0), q_range=(0.0, 2.0 * math.pi),
                                     n1=6, n2=12)
    return _wizard(mesh, 'Built by the wizard. These are its exact settings.',
                   mode='between', kind='height', z=top_expr,
                   bottom_kind='height', bottom_z=bottom_expr,
                   coord='polar', pattern='diagonal',
                   p_range=(0.3, 6.0), q_range=(0.0, 2.0 * math.pi),
                   n1=6, n2=12)


def barrel_vault_example():
    """A circular-arch barrel vault (stereo_geometry.barrel_vault directly,
    not the Custom Surface Wizard), double layer, pinned along its two
    springing lines -- the vault's own actual structural base (see that
    function's docstring for why the two long edges, not the two short
    end faces, is where a real barrel vault bears)."""
    mesh = sg.barrel_vault(span=12.0, rise=3.0, length=18.0, n_arch=8, n_bays=6,
                           double_layer=True, depth=0.5)
    return _wizard(
        mesh,
        'Not a wizard surface -- this mesh comes straight from\n'
        'stereo_geometry.barrel_vault(span=12, rise=3, length=18, n_arch=8, n_bays=6, double_layer=True, depth=0.5)')


def dome_example():
    """A Schwedler-rib dome (stereo_geometry.dome directly), pinned along
    its base ring -- every meridian rib lands there, the dome's own
    structural base."""
    mesh = sg.dome(base_radius=8.0, rise=4.0, n_rings=5, n_sectors=16)
    return _wizard(
        mesh,
        'Not a wizard surface -- this mesh comes straight from\n'
        'stereo_geometry.dome(base_radius=8, rise=4, n_rings=5, n_sectors=16)')


def cone_roof_example():
    """A conical roof (stereo_geometry.cone_roof directly) -- the same
    Schwedler apex/rings/diagonals bracing as the dome above, but on a
    straight-line (conical) profile instead of a curved one, pinned along
    its base ring."""
    mesh = sg.cone_roof(base_radius=7.0, rise=5.0, n_rings=4, n_sectors=14)
    return _wizard(
        mesh,
        'Not a wizard surface -- this mesh comes straight from\n'
        'stereo_geometry.cone_roof(base_radius=7, rise=5, n_rings=4, n_sectors=14)')


def groin_vault_example():
    """A groin (cross) vault (stereo_geometry.groin_vault directly) --
    two crossing barrel-vault profiles meeting at diagonal groin ridges,
    pinned along the full base perimeter (all four walls bear, unlike a
    plain barrel vault's two springing lines)."""
    mesh = sg.groin_vault(span=12.0, rise=3.0, module=1.5, depth=0.6,
                          offset=True, pattern='square')
    return _wizard(
        mesh,
        'Not a wizard surface -- this mesh comes straight from\n'
        "stereo_geometry.groin_vault(span=12, rise=3, module=1.5, depth=0.6, "
        "offset=True, pattern='square')")


def truss_bridge_example():
    """A Warren/Pratt-style truss bridge (stereo_geometry.truss_bridge
    directly), pinned at its four bottom-corner bearings -- span, depth
    and width deliberately non-round to steer clear of the exact
    span=40/depth=5/width=6/n_panels=4 coincidental critical-geometry
    mechanism documented in that function's own docstring."""
    mesh = sg.truss_bridge(span=42.0, depth=5.5, width=8.0, n_panels=7)
    return _wizard(
        mesh,
        'Not a wizard surface -- this mesh comes straight from\n'
        'stereo_geometry.truss_bridge(span=42, depth=5.5, width=8, n_panels=7)')


# ── the features added in the two UI stages, and the rod load ─────────────

def two_surface_isometric():
    """The isometric (60-degree, equilateral-triangle) module pattern in the
    TWO-surface interface -- a shallow dish over a flat plane, the same pair
    as two_surface_truss_1, triangulated instead of squared.

    The point of the example is what the domain does, not what the surface
    does: the pattern is isometric but the DOMAIN stays Cartesian and is
    sliced along its own x and y lines, so the mesh still fills the
    rectangle asked for instead of running past two of its edges. An
    oblique basis laid over a 12 m domain overshoots it by about 7 m; rows
    are staggered and clamped onto the edge instead, which is why the
    boundary rows here are half-cells rather than a ragged fringe.
    """
    top = sg.make_height_field_surface('2.6 - (x^2 + y^2)/34')
    bottom = sg.make_height_field_surface('-1.4')
    # Through custom_surface_lattice, which is the entry point the Shape
    # panel itself uses, so the example and a hand-driven build cannot
    # produce different meshes. LATTICE_ALIGNED is the only lattice an
    # isometric module can take: an offset lattice needs a half-module to
    # offset INTO, and the centre of a triangle is not a lattice point of
    # the triangle below it.
    mesh = sg.custom_surface_lattice(top, bottom, coord='cartesian',
                                     lattice=sg.LATTICE_ALIGNED,
                                     pattern=sg.PATTERN_ISOMETRIC,
                                     p_range=(-6.0, 6.0), q_range=(-6.0, 6.0),
                                     n1=8, n2=8, depth=1.0)
    return _wizard(mesh,
                   'Built by the wizard. These are its exact settings.',
                   mode='two', kind='height', z='2.6 - (x^2 + y^2)/34',
                   z_bottom='-1.4', coord='cartesian',
                   pattern=sg.PATTERN_ISOMETRIC, lattice=sg.LATTICE_ALIGNED,
                   p_range=(-6.0, 6.0), q_range=(-6.0, 6.0), n1=8, n2=8)


def bezier_extruded_vault():
    """A barrel-ish vault whose cross-section is a FITTED Bezier profile,
    extruded along y -- the "type what you can describe, then edit what you
    could not" path.

    The formula is a plain cosine arch, which a height field already
    expresses perfectly; that is the point. Fitting it costs almost nothing
    in accuracy (a cubic Hermite chain over 8 segments lands within a
    fraction of a percent) and buys every control point as a handle, so the
    crown can be flattened or one haunch pulled out afterwards -- a change
    no edit to the formula makes without changing the rest of the curve too.
    """
    profile = _fit('3.2 * cos(pi * x / 18)', -9.0, 9.0, segments=8)
    surface = _bz.extruded_surface(profile)
    mesh = sg.custom_surface_lattice(surface, coord='cartesian',
                                     lattice=sg.LATTICE_SOS_OFFSET,
                                     p_range=(-9.0, 9.0), q_range=(0.0, 14.0),
                                     n1=9, n2=7, depth=1.1)
    return _wizard(mesh, 'Fitted Bezier profile, extruded. Open Shape to edit '
                         'its control points.',
                   source='extrude', formula='3.2 * cos(pi * x / 18)',
                   segments=8, p_range=(-9.0, 9.0), q_range=(0.0, 14.0),
                   n1=9, n2=7, depth=1.1, lattice=sg.LATTICE_SOS_OFFSET)


def bezier_spun_tower():
    """A surface of REVOLUTION from a fitted Bezier profile: the formula is
    read as a RADIUS against height, not as a height against plan position,
    and spun about the vertical axis.

    That re-reading is the whole difference between this and the extruded
    example above, and it is why the Shape panel says so in its own note:
    the same typed expression means a different shape under the two
    sources. Here it gives a waisted tower -- wide at the base, pinched at
    mid-height, flaring again at the top -- which no height field z=f(x,y)
    can express at all, since the surface is vertical at the waist.
    """
    profile = _fit('3.4 - 1.6*sin(pi * x / 9)', 0.0, 9.0, segments=8)
    surface = _bz.spin_surface(profile)
    mesh = sg.custom_surface_grid(surface, coord='cartesian',
                                  pattern=sg.PATTERN_SQUARE,
                                  p_range=(0.0, 9.0), q_range=(0.0, 2.0 * math.pi),
                                  n1=8, n2=14, module='3d', depth=0.6,
                                  offset_side='top')
    return _wizard(mesh, 'Fitted Bezier profile, spun. The formula is the '
                         'RADIUS at each height.',
                   source='spin', formula='3.4 - 1.6*sin(pi * x / 9)',
                   segments=8, p_range=(0.0, 9.0),
                   q_range=(0.0, 2.0 * math.pi), n1=8, n2=14, depth=0.6)


def bezier_patch_dish():
    """A tensor-product Bezier PATCH fitted to a shallow dish -- a grid of
    control heights, every one of them draggable.

    Deliberately a shallow, single-hump surface. A patch of degree n has
    only n-1 interior bends per direction, so it follows a dish like this
    one closely at degree 6 (49 controls) while a two-wave surface at the
    same degree is off by tens of percent -- measured, and reported by the
    panel's own error note rather than left to be discovered. When a shape
    needs more waves than the degree can carry, a spin or an extrude buys
    the same accuracy for far fewer controls.
    """
    f = lambda x, y: 3.0 - (x * x + y * y) / 26.0
    grid = _bz.fit_patch(f, (-6.0, 6.0), (-6.0, 6.0), 6, 6)
    surface = _bz.patch_surface(grid, (-6.0, 6.0), (-6.0, 6.0))
    mesh = sg.custom_surface_lattice(surface, coord='cartesian',
                                     lattice=sg.LATTICE_SOS_OFFSET,
                                     p_range=(-6.0, 6.0), q_range=(-6.0, 6.0),
                                     n1=8, n2=8, depth=1.0)
    return _wizard(mesh, 'Fitted Bezier patch (7x7 control heights). Open '
                         'Shape to drag any of them.',
                   source='patch', formula='3 - (x^2 + y^2)/26', degree=6,
                   p_range=(-6.0, 6.0), q_range=(-6.0, 6.0), n1=8, n2=8,
                   depth=1.0, lattice=sg.LATTICE_SOS_OFFSET)


def rod_load_purlin_roof():
    """A flat double-layer grid carrying a DISTRIBUTED LOAD ALONG ITS TOP
    RODS -- the one thing that makes shear vary along a member at all.

    Under nodal loads alone every rod has a constant shear and a moment
    that runs straight from one end to the other, so the moment- and
    shear-along-rod views have nothing to show: one value per rod is not a
    field along it. Put 4 kN/m on the top chords, as a purlin line or a
    cladding rail would, and the shear ramps across each rod while the
    moment bends into a parabola. Load this example, then colour by
    "Moment along rod" with the smooth gradient on.

    The load is PER METRE OF ROD (not per plan metre) and is carried on the
    top-layer members only, which is where a real roof skin would put it.
    """
    mesh = sg.flat_grid(12.0, 12.0, 1.2, 2.0, offset=True, pattern='square')
    nodes = mesh['nodes']
    z_top = max(n[2] for n in nodes)
    top_rods = [k for k, m in enumerate(mesh['members'])
                if abs(nodes[m['a']][2] - z_top) < 1e-9
                and abs(nodes[m['b']][2] - z_top) < 1e-9]
    mesh['member_loads'] = [{'member': k, 'w': 4.0, 'dir': (0.0, 0.0, -1.0),
                             'spread': 'along'} for k in top_rods]
    return _wizard(mesh,
                   'Not a wizard surface -- stereo_geometry.flat_grid(12, 12,\n'
                   '1.2, 2.0), with 4 kN/m along each of its top-layer rods.')


def billow_shell_chapel():
    """The billowing, doubly-curved shell -- the one that reads like a
    chapel roof whose edges lift at the corners and dip between them.

    Distinct from wave_shell, which corrugates in ONE direction only: this
    one multiplies a cosine in x by a cosine in y, so every point is curved
    both ways and the boundary alternates between high corners and low
    mid-edges instead of running as straight parallel ridges.
    """
    mesh = sg.billow_shell(span_x=18.0, span_y=18.0, depth=1.2, module=2.0,
                           rise=3.0, waves_x=1.0, waves_y=1.0)
    return _wizard(mesh,
                   'Not a wizard surface -- stereo_geometry.billow_shell(\n'
                   'span 18x18, depth 1.2, module 2.0, rise 3.0, 1x1 waves)')


EXAMPLES = (
    ('Planar grid + columns (1-tier) + beam', planar_grid_with_columns_1),
    ('Planar grid + columns (2-tier) + multilayer beam', planar_grid_with_columns_2),
    ('Single-surface truss: paraboloid dish (square)', single_surface_truss_1),
    ('Single-surface truss: half-cylinder (isometric)', single_surface_truss_2),
    ('Two-surface truss: dish over flat plane (square)', two_surface_truss_1),
    ('Two-surface truss: concentric domes (polar, diagonal)', two_surface_truss_2),
    ('Barrel vault (circular arch), pinned at both springing lines', barrel_vault_example),
    ('Schwedler dome, pinned at the base ring', dome_example),
    ('Conical roof, pinned at the base ring', cone_roof_example),
    ('Groin (cross) vault, pinned at the full base perimeter', groin_vault_example),
    ('Truss bridge (Warren/Pratt-style), pinned at the four bearings', truss_bridge_example),
    ('Two-surface truss: dish over plane, ISOMETRIC pattern', two_surface_isometric),
    ('Bezier profile EXTRUDED: fitted cosine vault', bezier_extruded_vault),
    ('Bezier profile SPUN: waisted tower (formula = radius)', bezier_spun_tower),
    ('Bezier PATCH: fitted dish, 7x7 draggable controls', bezier_patch_dish),
    ('Distributed load ALONG THE RODS: purlin-loaded flat grid', rod_load_purlin_roof),
    ('Billowing doubly-curved shell (chapel-like)', billow_shell_chapel),
)
