"""Tests for the ready-made example scenes in apps/stereo/stereo_examples.py
(the Stereo tab's "Load Example" menu) -- each demonstrates either the
column/reinforcement-beam add-ons or the Custom Surface Wizard's single-/
two-surface generators, and every one of them must actually analyze under
self-weight: an example that doesn't solve would be a poor advertisement
for the feature it exists to demonstrate."""
import pytest

from apps.stereo import stereo_examples as sx
from apps.stereo import stereo_math as sm


def _solves(mesh):
    nodes, members = mesh['nodes'], mesh['members']
    for m in members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    _res, err = sm.analyze(nodes, members, loads, supports)
    return err


def test_examples_table_has_eight_distinct_entries():
    assert len(sx.EXAMPLES) == 8
    labels = [label for label, _builder in sx.EXAMPLES]
    assert len(set(labels)) == 8


@pytest.mark.parametrize('label,builder', sx.EXAMPLES)
def test_example_returns_a_well_formed_mesh(label, builder):
    mesh = builder()
    assert mesh['nodes']
    assert mesh['members']
    assert mesh['support_candidates']
    for i in mesh['support_candidates']:
        assert 0 <= i < len(mesh['nodes'])
    for m in mesh['members']:
        assert 0 <= m['a'] < len(mesh['nodes'])
        assert 0 <= m['b'] < len(mesh['nodes'])
        assert m['a'] != m['b']


@pytest.mark.parametrize('label,builder', sx.EXAMPLES)
def test_example_analyzes_under_self_weight(label, builder):
    mesh = builder()
    assert _solves(mesh) is None, f'{label} does not analyze'


def test_planar_examples_actually_contain_a_column_and_a_beam():
    # sanity check that the add-on features were actually exercised, not
    # just a plain flat_grid with no columns/beam attached
    for builder in (sx.planar_grid_with_columns_1, sx.planar_grid_with_columns_2):
        mesh = builder()
        roles = {m.get('role') for m in mesh['members']}
        assert 'column_shaft' in roles
        assert 'capital' in roles
        assert 'reinf_chord' in roles


def test_planar_example_2_uses_a_two_tier_capital():
    mesh = sx.planar_grid_with_columns_2()
    roles = {m.get('role') for m in mesh['members']}
    assert 'capital_ring' in roles   # only added for tiers=2


def test_planar_example_1_is_supported_only_by_its_four_columns():
    # the actual bug report this fixes: an earlier version ALSO pinned the
    # base grid's own perimeter, so the columns carried almost none of the
    # roof's own weight -- a poor demonstration of the column feature.
    mesh = sx.planar_grid_with_columns_1()
    assert len(mesh['support_candidates']) == 4
    roles = {mesh['members'][i].get('role') for i in range(len(mesh['members']))}
    # every support candidate must actually be a column base, i.e. touched
    # by a 'column_shaft' member
    shaft_nodes = {m['a'] for m in mesh['members'] if m.get('role') == 'column_shaft'} | \
                  {m['b'] for m in mesh['members'] if m.get('role') == 'column_shaft'}
    assert set(mesh['support_candidates']) <= shaft_nodes


def test_planar_example_2_is_supported_by_its_column_plus_only_the_four_corners():
    # a single column cannot stabilize a pin-jointed roof alone (see the
    # example's own docstring) -- it needs a LITTLE extra restraint, but
    # not the base grid's full perimeter, which would swamp the column's
    # own share of the load the same way example 1's bug did.
    mesh = sx.planar_grid_with_columns_2()
    nodes = mesh['nodes']
    assert len(mesh['support_candidates']) == 5
    shaft_nodes = {m['a'] for m in mesh['members'] if m.get('role') == 'column_shaft'} | \
                  {m['b'] for m in mesh['members'] if m.get('role') == 'column_shaft'}
    column_supports = [i for i in mesh['support_candidates'] if i in shaft_nodes]
    assert len(column_supports) == 1
    corner_supports = [i for i in mesh['support_candidates'] if i not in shaft_nodes]
    assert len(corner_supports) == 4
    xs = [nodes[i][0] for i in corner_supports]
    ys = [nodes[i][1] for i in corner_supports]
    assert len(set(xs)) == 2 and len(set(ys)) == 2   # the four extreme corners


def test_planar_example_2_column_carries_most_of_the_load():
    mesh = sx.planar_grid_with_columns_2()
    nodes, members = mesh['nodes'], mesh['members']
    for m in members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    shaft_nodes = {m['a'] for m in members if m.get('role') == 'column_shaft'} | \
                  {m['b'] for m in members if m.get('role') == 'column_shaft'}
    column_base = [i for i in mesh['support_candidates'] if i in shaft_nodes][0]
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None
    col_fz = -res['reactions'][column_base]['Fz']
    total_fz = sum(-r['Fz'] for r in res['reactions'].values())
    assert col_fz / total_fz > 0.5   # the column, not the corners, dominates


def test_single_surface_examples_are_double_layer():
    for builder in (sx.single_surface_truss_1, sx.single_surface_truss_2):
        mesh = builder()
        zs = sorted({round(z, 3) for x, y, z in mesh['nodes']})
        assert len(zs) > 1   # a 3D module has more than one z level present


def test_two_surface_examples_connect_two_distinct_surfaces():
    top1 = sx.two_surface_truss_1
    mesh = top1()
    # the two surfaces differ by exactly +1.0 in z (dish+1.0 over flat=0)
    zs = [z for x, y, z in mesh['nodes']]
    assert max(zs) - min(zs) > 0.5


def test_half_cylinder_example_arches_upward_not_sideways():
    # the actual bug report this guards: q_range used to sweep v from near
    # the true crown (v~0) past a springing line (v=pi/2) to near the
    # circle's own BOTTOM (v~pi) instead of being centred on the crown, so
    # half the "vault" sat below the ground plane and the whole shape read
    # as an arch opening sideways (toward +y) rather than pointing up.
    mesh = sx.single_surface_truss_2()
    zs = [z for _x, _y, z in mesh['nodes']]
    ys = [y for _x, y, _z in mesh['nodes']]
    assert min(zs) >= 0.0   # nothing below the ground plane
    assert min(ys) < 0.0 < max(ys)   # the arc straddles its own centreline


def test_barrel_vault_example_rise_is_along_z():
    mesh = sx.barrel_vault_example()
    zs = [z for _x, _y, z in mesh['nodes']]
    ys = [y for _x, y, _z in mesh['nodes']]
    assert max(zs) - min(zs) > 2.0   # a real rise, not a flattened arc
    assert min(ys) < 0.0 < max(ys)   # springs on both sides of the centreline


def test_dome_example_apex_is_the_highest_point():
    mesh = sx.dome_example()
    nodes = mesh['nodes']
    apex = max(range(len(nodes)), key=lambda i: nodes[i][2])
    assert abs(nodes[apex][0]) < 1e-6 and abs(nodes[apex][1]) < 1e-6   # apex sits on the axis
    assert apex not in mesh['support_candidates']   # the base ring, not the apex, is supported
