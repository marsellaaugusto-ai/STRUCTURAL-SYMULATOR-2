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


def test_examples_table_has_six_distinct_entries():
    assert len(sx.EXAMPLES) == 6
    labels = [label for label, _builder in sx.EXAMPLES]
    assert len(set(labels)) == 6


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
