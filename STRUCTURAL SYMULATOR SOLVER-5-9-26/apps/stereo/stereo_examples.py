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

Each function returns the shared {'nodes','members','support_candidates'}
mesh dict, exactly like every stereo_geometry generator, so it drops
straight into StereoApp._load_mesh. Every one of them is checked in
tests/test_stereo_examples.py to actually analyze under self-weight when
pinned at its own support_candidates -- an example that doesn't solve
would be a poor advertisement for the feature it demonstrates.
"""
import math

from apps.stereo import stereo_geometry as sg


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


def planar_grid_with_columns_1():
    """A 12x12 m flat double-layer grid (square-on-square offset, 2 m
    module) on four single-tier columns at its quarter-points, with one
    single-tier reinforcement beam along the two grid lines nearest the
    centre -- the simplest version of "columns and beams added to a flat
    grid," one tier each."""
    mesh = sg.flat_grid(12.0, 12.0, 1.0, 2.0, offset=True, pattern='square')
    nodes, members = list(mesh['nodes']), list(mesh['members'])
    supports = list(mesh['support_candidates'])
    for cx, cy in ((3.0, 3.0), (9.0, 3.0), (3.0, 9.0), (9.0, 9.0)):
        targets = _nodes_near(nodes, cx, cy, z=0.0, k=4)
        nodes, members, base, _head = sg.add_column(nodes, members, targets,
                                                     height=3.0, tiers=1)
        supports.append(base)
    edge_a = _row_at(nodes, 1, 4.0, 0.0)
    edge_b = _row_at(nodes, 1, 6.0, 0.0)
    nodes, members, _apex = sg.reinforcement_beam(nodes, members, edge_a, edge_b,
                                                  depth=1.0, tiers=1)
    return {'nodes': nodes, 'members': members, 'support_candidates': supports,
            'load_nodes': mesh.get('load_nodes', {})}


def planar_grid_with_columns_2():
    """A larger, 16x16 m flat double-layer grid (diagonal-on-diagonal
    chords, aligned layers, 2 m module) on ONE central "two modules
    thick" (tiers=2) column -- a heavier load calls for a deeper, wider
    capital transition -- plus a two-layer reinforcement beam along the
    two grid lines nearest one edge."""
    mesh = sg.flat_grid(16.0, 16.0, 1.2, 2.0, offset=False, pattern='diagonal')
    nodes, members = list(mesh['nodes']), list(mesh['members'])
    supports = list(mesh['support_candidates'])
    targets = _nodes_within(nodes, 8.0, 8.0, 0.0, radius=3.1)
    nodes, members, base, _head = sg.add_column(nodes, members, targets,
                                                height=4.0, tiers=2)
    supports.append(base)
    edge_a = _row_at(nodes, 1, 2.0, 0.0)
    edge_b = _row_at(nodes, 1, 4.0, 0.0)
    nodes, members, _apex = sg.reinforcement_beam(nodes, members, edge_a, edge_b,
                                                  depth=1.5, tiers=2)
    return {'nodes': nodes, 'members': members, 'support_candidates': supports,
            'load_nodes': mesh.get('load_nodes', {})}


def single_surface_truss_1():
    """A paraboloid dish (a height field -- z = f(x, y)), Cartesian
    domain, square module pattern, sampled as a 3D (double-layer) space
    truss: the Custom Surface Wizard's simplest single-surface case."""
    surface = sg.make_height_field_surface('3.0 * (1 - (x/6)^2 - (y/6)^2)')
    return sg.custom_surface_grid(surface, coord='cartesian', pattern='square',
                                  p_range=(-6.0, 6.0), q_range=(-6.0, 6.0),
                                  n1=8, n2=8, module='3d', depth=0.6,
                                  offset_side='top')


def single_surface_truss_2():
    """An open half-cylinder -- a fully PARAMETRIC surface (x=u,
    y=4sin(v), z=4cos(v)), a shape no height field z=f(x,y) could
    express (a cylinder is vertical at its own springing lines) --
    sampled with the isometric (60-degree/equilateral-triangle) module
    pattern into a 3D space truss."""
    surface = sg.make_parametric_surface('u', '4*sin(v)', '4*cos(v)')
    return sg.custom_surface_grid(surface, coord='cartesian', pattern='isometric',
                                  p_range=(0.0, 10.0), q_range=(0.3, math.pi - 0.3),
                                  n1=10, n2=8, module='3d', depth=0.5,
                                  offset_side='top')


def two_surface_truss_1():
    """A shallow dish as the TOP surface over a flat plane as the BOTTOM
    surface, Cartesian domain, square pattern -- the Custom Surface
    Wizard's two-surface mode connecting two independently-defined
    surfaces into one double-layer grid."""
    top = sg.make_height_field_surface('3.0 * (1 - (x/6)^2 - (y/6)^2) + 1.0')
    bottom = sg.make_height_field_surface('0')
    return sg.custom_surface_between(top, bottom, coord='cartesian', pattern='square',
                                     p_range=(-6.0, 6.0), q_range=(-6.0, 6.0),
                                     n1=8, n2=8)


def two_surface_truss_2():
    """Two CONCENTRIC domes (a taller one as the top surface, a
    shallower one as the bottom), Polar domain, diagonal pattern -- the
    two-surface case exercised over a curved domain instead of a flat
    rectangle."""
    top = sg.make_height_field_surface('4.0 * (1 - (x/6)^2 - (y/6)^2) + 2.0')
    bottom = sg.make_height_field_surface('2.0 * (1 - (x/6)^2 - (y/6)^2)')
    return sg.custom_surface_between(top, bottom, coord='polar', pattern='diagonal',
                                     p_range=(0.3, 6.0), q_range=(0.0, 2.0 * math.pi),
                                     n1=6, n2=12)


EXAMPLES = (
    ('Planar grid + columns (1-tier) + beam', planar_grid_with_columns_1),
    ('Planar grid + columns (2-tier) + multilayer beam', planar_grid_with_columns_2),
    ('Single-surface truss: paraboloid dish (square)', single_surface_truss_1),
    ('Single-surface truss: half-cylinder (isometric)', single_surface_truss_2),
    ('Two-surface truss: dish over flat plane (square)', two_surface_truss_1),
    ('Two-surface truss: concentric domes (polar, diagonal)', two_surface_truss_2),
)
