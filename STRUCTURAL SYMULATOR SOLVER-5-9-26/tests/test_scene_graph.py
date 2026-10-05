"""The scene graph: composite nesting, definition/instance sharing, and the
recursive transforms that hold the two together (apps/stereo/scene/).

These are the checks that would catch the mistakes the design is FOR, not a
restatement of the code:

  * a transform convention that disagrees with the rest of the app (the
    rotations here are pinned against the proven `stereo_transform` ones, so
    the two can never drift into mirroring each other);
  * an edit inside a nested frame that moves the object (the inverse half);
  * a unique group whose edit leaks into another copy, or a definition edit
    that fails to reach one;
  * a bake that loses a joint, invents one, or renumbers non-deterministically;
  * a component sized from one instance instead of the worst of them.
"""
import math

import pytest

from apps.stereo import stereo_transform as st
from apps.stereo.scene import (
    DefinitionLibrary, GroupNode, InstanceNode, JointPrimitive, MeshPrimitive,
    RodPrimitive, Transform, TransformPolicy, bake, edit_in_place,
    make_definition, make_unique,
)


def _near(p, q, tol=1e-9):
    assert len(p) == len(q)
    for a, b in zip(p, q):
        assert abs(a - b) <= tol, '%r != %r' % (p, q)


def _truss(name='truss'):
    """A three-rod triangle, 6 m span, apex 2 m up, in its own coordinates."""
    g = GroupNode(name)
    g.add(RodPrimitive((0, 0, 0), (6, 0, 0), 'bottom', meta={'A': 1e-3}))
    g.add(RodPrimitive((0, 0, 0), (3, 0, 2), 'left', meta={'A': 5e-4}))
    g.add(RodPrimitive((3, 0, 2), (6, 0, 0), 'right', meta={'A': 5e-4}))
    return g


# ── transforms ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize('axis', ['X', 'Y', 'Z'])
@pytest.mark.parametrize('angle', [0.0, 30.0, 90.0, -45.0, 180.0])
def test_rotation_matches_the_existing_app_convention(axis, angle):
    """The one test that cannot be skipped: a new transform layer whose
    handedness disagrees with `stereo_transform` would mirror every nested
    group against every un-nested one, and look plausible doing it."""
    pivot = (1.5, -2.0, 0.75)
    p = (2.0, 3.0, -1.0)
    want = st.rotate_point(p, axis, angle, pivot)
    got = Transform.about(pivot, Transform.rotation(axis, angle)).apply_point(p)
    _near(got, want)


def test_mirror_matches_and_flips_handedness():
    pivot = (1.0, 2.0, 3.0)
    p = (4.0, -1.0, 0.5)
    for axis in 'XYZ':
        want = st.mirror_point(p, axis, pivot)
        m = Transform.about(pivot, Transform.mirror(axis))
        _near(m.apply_point(p), want)
        assert m.handedness() == -1
        assert m.is_rigid(), 'a mirror stretches nothing; it only flips'


def test_composition_order_is_other_first():
    t = Transform.translation(10, 0, 0)
    r = Transform.rotation('Z', 90)
    _near((t @ r).apply_point((1, 0, 0)), (10.0, 1.0, 0.0))
    _near((r @ t).apply_point((1, 0, 0)), (0.0, 11.0, 0.0))


def test_inverse_round_trips_and_refuses_collapse():
    t = (Transform.translation(3, -4, 5) @ Transform.rotation('Y', 37)
         @ Transform.scale(2, 2, 2))
    assert (t.inverse() @ t).is_identity()
    p = (1.0, 2.0, 3.0)
    _near(t.inverse().apply_point(t.apply_point(p)), p)
    with pytest.raises(ValueError):
        Transform.scale(1, 0, 1).inverse()


def test_direction_and_normal_are_not_points():
    t = Transform.translation(100, 0, 0) @ Transform.scale(1, 1, 4)
    # A direction ignores the translation...
    _near(t.apply_direction((0, 0, 1)), (0.0, 0.0, 4.0))
    # ...and a normal follows the inverse-transpose, so it stays square to
    # the surface a non-uniform scale has just reshaped.
    _near(t.apply_normal((0, 0, 1)), (0.0, 0.0, 0.25))


def test_policy_questions_are_answered_correctly():
    assert Transform.rotation('X', 12).is_rigid()
    assert Transform.mirror('Y').is_uniform_scale()
    assert Transform.scale(3).is_uniform_scale()
    assert not Transform.scale(3, 1, 1).is_uniform_scale()
    assert not Transform.scale(3, 1, 1).is_rigid()


# ── the composite ──────────────────────────────────────────────────────────

def test_world_transform_accumulates_down_the_hierarchy():
    root = GroupNode('model')
    bay = root.add(GroupNode('bay', local=Transform.translation(10, 0, 0)))
    sub = bay.add(GroupNode('sub', local=Transform.rotation('Z', 90)))
    rod = sub.add(RodPrimitive((2, 0, 0), (2, 0, 1), 'post'))
    _near(rod.world_transform().apply_point(rod.a), (10.0, 2.0, 0.0))
    assert rod.path() == (root.id, bay.id, sub.id, rod.id)
    assert rod.depth() == 3


def test_a_child_has_exactly_one_parent():
    """Rule 1 of stereo_groups, as a fact about trees rather than a rule
    anything has to enforce: adding to a second group MOVES the child."""
    a, b = GroupNode('a'), GroupNode('b')
    rod = a.add(RodPrimitive((0, 0, 0), (1, 0, 0)))
    b.add(rod)
    assert rod.parent is b
    assert rod not in a.children()
    assert len(b.children()) == 1


def test_a_group_cannot_contain_itself():
    root = GroupNode('root')
    bay = root.add(GroupNode('bay'))
    with pytest.raises(ValueError):
        bay.add(root)
    with pytest.raises(ValueError):
        bay.add(bay)


def test_moving_a_group_moves_its_whole_subtree_and_nothing_else():
    root = GroupNode('model')
    bay = root.add(GroupNode('bay'))
    rod = bay.add(RodPrimitive((0, 0, 0), (1, 0, 0)))
    other = root.add(RodPrimitive((0, 0, 0), (1, 0, 0)))
    bay.apply_local(Transform.translation(0, 0, 7))
    _near(rod.world_transform().apply_point(rod.a), (0.0, 0.0, 7.0))
    _near(other.world_transform().apply_point(other.a), (0.0, 0.0, 0.0))


def test_set_world_divides_out_the_ancestors():
    """The failure this prevents: a nested object JUMPS when dragged,
    because it picks up its ancestors' transforms a second time."""
    root = GroupNode('model')
    bay = root.add(GroupNode('bay', local=Transform.translation(5, 0, 0)))
    sub = bay.add(GroupNode('sub', local=Transform.rotation('Z', 45)))
    rod = sub.add(RodPrimitive((1, 0, 0), (2, 0, 0)))
    target = Transform.translation(-3, 8, 1)
    rod.set_world(target)
    assert rod.world_transform().approx_equal(target)
    _near(rod.world_transform().apply_point(rod.a), (-2.0, 8.0, 1.0))


def test_reparenting_keeps_the_object_where_it_was():
    root = GroupNode('model')
    a = root.add(GroupNode('a', local=Transform.translation(10, 0, 0)))
    b = root.add(GroupNode('b', local=Transform.rotation('Z', 90)
                           @ Transform.translation(0, 0, 3)))
    rod = a.add(RodPrimitive((1, 0, 0), (2, 0, 0)))
    before = rod.world_transform().apply_point(rod.a)
    a.reparent(rod, b, keep_world=True)
    assert rod.parent is b
    _near(rod.world_transform().apply_point(rod.a), before)


def test_cached_frames_are_dropped_when_an_ancestor_moves():
    root = GroupNode('model')
    bay = root.add(GroupNode('bay'))
    rod = bay.add(RodPrimitive((1, 0, 0), (2, 0, 0)))
    _near(rod.world_transform().apply_point(rod.a), (1.0, 0.0, 0.0))
    bay.set_local(Transform.translation(0, 0, 4))
    _near(rod.world_transform().apply_point(rod.a), (1.0, 0.0, 4.0))


def test_clone_is_deep_and_independent():
    g = _truss()
    copy = g.clone()
    assert copy.parent is None
    assert [c.name for c in copy.children()] == [c.name for c in g.children()]
    assert all(c.id != o.id for c, o in zip(copy.children(), g.children()))
    copy.children()[0].meta['A'] = 99.0
    assert g.children()[0].meta['A'] == 1e-3


def test_visitor_dispatches_on_kind():
    class Counter:
        def __init__(self):
            self.seen = []

        def visit_object(self, obj):
            self.seen.append('other')

        def visit_rod(self, obj):
            self.seen.append('rod')

        def visit_group(self, obj):
            self.seen.append('group')

    v, g = Counter(), _truss()
    g.add(MeshPrimitive([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)]))
    for obj in g.walk():
        obj.accept(v)
    assert v.seen == ['group', 'rod', 'rod', 'rod', 'other']


def test_mesh_refuses_a_face_index_it_has_no_vertex_for():
    with pytest.raises(ValueError):
        MeshPrimitive([(0, 0, 0), (1, 0, 0)], [(0, 1, 2)])


# ── definitions and instances ──────────────────────────────────────────────

def test_making_a_definition_does_not_move_anything():
    lib, root = DefinitionLibrary(), GroupNode('model')
    g = root.add(_truss())
    g.set_local(Transform.translation(0, 0, 5))
    apex_before = g.children()[1].world_transform().apply_point((3, 0, 2))
    inst = make_definition(lib, g, 'Truss A')
    assert isinstance(inst, InstanceNode)
    assert inst.parent is root
    assert lib.get(inst.definition_id).content.local.is_identity()
    baked = bake(root, lib)
    assert any(abs(n[2] - apex_before[2]) < 1e-9 for n in baked.nodes)


def test_editing_a_definition_reaches_every_instance():
    """The point of an instance: one edit, every copy."""
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, root.add(_truss()), 'T')
    root.add(lib.place('def1', local=Transform.translation(0, 4, 0)))
    root.add(lib.place('def1', local=Transform.translation(0, 8, 0)))
    lib.get('def1').content.children()[0].meta['A'] = 7e-3
    baked = bake(root, lib)
    bottoms = [m['A'] for m, o in zip(baked.members, baked.origins)
               if o.primitive_id == lib.get('def1').content.children()[0].id]
    assert len(bottoms) == 3 and all(a == 7e-3 for a in bottoms)


def test_editing_a_unique_group_reaches_nothing_else():
    """The point of a unique group: the other half of requirement 2."""
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, root.add(_truss()), 'T')
    keep = root.add(lib.place('def1', local=Transform.translation(0, 4, 0)))
    freed = root.add(lib.place('def1', local=Transform.translation(0, 8, 0)))
    group = make_unique(lib, freed)
    assert isinstance(group, GroupNode)
    group.children()[0].meta['A'] = 7e-3
    group.add(RodPrimitive((0, 0, 0), (0, 0, -1), 'extra prop'))

    baked = bake(root, lib)
    unique_members = baked.members_under((group.id,))
    assert len(unique_members) == 4, 'the added rod belongs to this copy only'
    assert len(baked.members_under((keep.id,))) == 3
    assert lib.get('def1').content.children()[0].meta['A'] == 1e-3


def test_make_unique_leaves_the_copy_exactly_where_it_was():
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, root.add(_truss()), 'T')
    inst = root.add(lib.place('def1', local=Transform.rotation('Z', 31)
                              @ Transform.translation(2, 4, 6)))
    before = sorted(bake(root, lib).nodes)
    make_unique(lib, inst)
    assert sorted(bake(root, lib).nodes) == pytest.approx(before)


def test_cloning_an_instance_shares_while_cloning_a_group_does_not():
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, root.add(_truss()), 'T')
    inst = root.add(lib.place('def1'))
    twin = root.add(inst.clone())
    assert twin.definition_id == inst.definition_id
    # make_definition left one instance behind, place() added a second, and
    # the clone is the third -- all of them one definition.
    assert lib.reference_count(root, 'def1') == 3
    assert len(lib.all()) == 1


def test_a_definition_cannot_contain_itself():
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, root.add(_truss()), 'T')
    content = lib.get('def1').content
    assert lib.would_cycle('def1', GroupNode('x', children=[lib.place('def1')]))
    with pytest.raises(ValueError):
        if lib.would_cycle('def1', GroupNode('x', children=[lib.place('def1')])):
            raise ValueError('refused')
    # And a definition that merely holds a DIFFERENT definition is fine.
    inner = make_definition(lib, GroupNode('inner', children=[
        RodPrimitive((0, 0, 0), (1, 0, 0))]), 'Inner')
    content.add(inner)
    assert not lib.would_cycle('def1', content)


def test_the_policy_refuses_a_placement_that_changes_the_part():
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, root.add(_truss()), 'T')
    with pytest.raises(ValueError):
        lib.place('def1', local=Transform.scale(2, 1, 1))
    lib.place('def1', local=Transform.rotation('Z', 20))        # fine: rigid
    lib.place('def1', local=Transform.mirror('Y'))              # fine: rigid
    free = make_definition(lib, GroupNode('f', children=[
        RodPrimitive((0, 0, 0), (1, 0, 0))]), 'Stretchy',
        policy=TransformPolicy.FREE)
    lib.set_instance_transform(free, Transform.scale(2, 1, 1))  # opted in


def test_edit_in_place_reports_how_many_copies_an_edit_will_touch():
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, root.add(_truss()), 'T')
    for i in range(1, 5):
        root.add(lib.place('def1', local=Transform.translation(0, 4 * i, 0)))
    content, count = edit_in_place(lib, root.children()[0])
    assert content is lib.get('def1').content
    assert count == 5


def test_nested_instances_are_counted_where_they_are_really_built():
    """A bay definition holding truss instances: the trusses actually built
    are not only the ones placed in the document."""
    lib, root = DefinitionLibrary(), GroupNode('model')
    truss_inst = make_definition(lib, GroupNode('t', children=[
        RodPrimitive((0, 0, 0), (6, 0, 0))]), 'Truss')
    bay = GroupNode('bay', children=[truss_inst])
    bay.add(lib.place(truss_inst.definition_id,
                      local=Transform.translation(0, 3, 0)))
    bay_inst = make_definition(lib, bay, 'Bay')
    root.add(bay_inst)
    root.add(lib.place(bay_inst.definition_id,
                       local=Transform.translation(12, 0, 0)))
    assert lib.reference_count(root, 'Truss') == 0        # none placed directly
    assert len(lib.instances_of(root, truss_inst.definition_id)) == 2
    assert len(bake(root, lib).members) == 4              # what gets fabricated


def test_purge_unused_collects_a_whole_dead_chain():
    lib, root = DefinitionLibrary(), GroupNode('model')
    inner = make_definition(lib, GroupNode('i', children=[
        RodPrimitive((0, 0, 0), (1, 0, 0))]), 'Inner')
    outer = make_definition(lib, GroupNode('o', children=[inner]), 'Outer')
    root.add(outer)
    assert lib.purge_unused(root) == []
    root.remove(outer)
    assert {d.name for d in lib.purge_unused(root)} == {'Inner', 'Outer'}


def test_mirrored_instances_are_reported_as_different_parts():
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, root.add(_truss()), 'T')
    plain = root.add(lib.place('def1'))
    flipped = root.add(lib.place('def1', local=Transform.mirror('Y')))
    # A mirror inside a mirror is the right way round again, and what gets
    # fabricated is what the WORLD matrix says.
    nested = GroupNode('flipped bay', local=Transform.mirror('Y'))
    root.add(nested)
    twice = nested.add(lib.place('def1', local=Transform.mirror('Y')))
    found = lib.mirrored_instances(root)
    assert flipped in found
    assert plain not in found and twice not in found


# ── the bake ───────────────────────────────────────────────────────────────

def test_coincident_endpoints_weld_into_one_joint():
    root = GroupNode('model')
    root.add(RodPrimitive((0, 0, 0), (1, 0, 0)))
    root.add(RodPrimitive((1, 0, 0), (2, 0, 0)))
    baked = bake(root)
    assert len(baked.nodes) == 3
    assert baked.members[0]['b'] == baked.members[1]['a']


def test_welding_does_not_depend_on_where_the_grid_falls():
    """A model whose node count changes when it is moved by half a tolerance
    is a model whose connectivity depends on where it happens to sit."""
    for shift in (0.0, 5e-7, 1e-7, 0.25):
        root = GroupNode('model', local=Transform.translation(shift, 0, 0))
        root.add(RodPrimitive((0, 0, 0), (1, 0, 0)))
        root.add(RodPrimitive((1, 0, 0), (2, 0, 0)))
        assert len(bake(root).nodes) == 3, 'shift %r split a joint' % shift


def test_a_joint_key_welds_what_tolerance_would_miss():
    root = GroupNode('model')
    root.add(RodPrimitive((0, 0, 0), (1.0, 0, 0), joint_b='apex'))
    root.add(RodPrimitive((1.0005, 0, 0), (2, 0, 0), joint_a='apex'))
    baked = bake(root)
    assert len(baked.nodes) == 3
    assert baked.members[0]['b'] == baked.members[1]['a']


def test_separate_instances_weld_to_each_other_but_keep_their_own_keys():
    """Two copies of one truss, bolted together by a tie. The tie's ends
    weld to each copy; the copies' own internal joint keys do not merge."""
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, GroupNode('t', children=[
        RodPrimitive((0, 0, 0), (6, 0, 0), joint_a='left', joint_b='right'),
    ]), 'T')
    root.add(lib.place('def1'))
    root.add(lib.place('def1', local=Transform.translation(0, 4, 0)))
    root.add(RodPrimitive((0, 0, 0), (0, 4, 0), 'tie'))
    baked = bake(root, lib)
    assert len(baked.nodes) == 4, 'the keyed joints must not merge across copies'
    shared = baked.shared_nodes()
    assert len(shared) == 2 and all(len(v) == 2 for v in shared.values())


def test_a_zero_length_rod_is_reported_not_dropped_in_silence():
    root = GroupNode('model')
    root.add(RodPrimitive((0, 0, 0), (1, 0, 0)))
    root.add(RodPrimitive((2, 0, 0), (2, 0, 0), 'collapsed'))
    baked = bake(root)
    assert len(baked.members) == 1
    assert len(baked.warnings) == 1 and 'zero length' in baked.warnings[0]


def test_the_bake_is_deterministic():
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, root.add(_truss()), 'T')
    root.add(lib.place('def1', local=Transform.translation(0, 4, 0)))
    first, second = bake(root, lib), bake(root, lib)
    assert first.nodes == second.nodes
    assert [m['a'] for m in first.members] == [m['a'] for m in second.members]
    assert [o.path for o in first.origins] == [o.path for o in second.origins]


def test_the_bake_leaves_the_graph_alone():
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, root.add(_truss()), 'T')
    inst = root.add(lib.place('def1', local=Transform.translation(0, 4, 0),
                              overrides={'A': 9e-3}))
    bake(root, lib)
    assert inst.local.approx_equal(Transform.translation(0, 4, 0))
    assert lib.get('def1').content.children()[0].meta['A'] == 1e-3, \
        'an override must not write back into the shared definition'


def test_an_override_is_per_instance():
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, root.add(_truss()), 'T')
    root.add(lib.place('def1', local=Transform.translation(0, 4, 0),
                       overrides={'A': 9e-3}))
    baked = bake(root, lib)
    plain = [baked.members[i]['A'] for i in baked.members_under((root.children()[0].id,))]
    heavy = [baked.members[i]['A'] for i in baked.members_under((root.children()[1].id,))]
    assert set(heavy) == {9e-3}
    assert 9e-3 not in plain


def test_members_under_replaces_a_stored_membership_set():
    lib, root = DefinitionLibrary(), GroupNode('model')
    roof = root.add(GroupNode('roof'))
    bay = roof.add(GroupNode('bay'))
    bay.add(_truss())
    roof.add(RodPrimitive((0, 0, 0), (0, 0, 1), 'post'))
    baked = bake(root, lib)
    assert len(baked.members_under((roof.id,))) == 4       # rolls up
    assert len(baked.members_under((roof.id, bay.id))) == 3
    assert baked.nodes_under((roof.id, bay.id)) == [0, 1, 2]


def test_legacy_group_records_are_disjoint_and_add_up():
    """The migration seam: the per-group totals must still add up to the
    model, which is the one check that catches a mis-assigned rod."""
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, root.add(_truss()), 'T')
    root.add(lib.place('def1', local=Transform.translation(0, 4, 0)))
    root.add(GroupNode('braces', children=[RodPrimitive((0, 0, 0), (0, 4, 0))]))
    root.add(RodPrimitive((6, 0, 0), (6, 4, 0), 'ungrouped tie'))
    baked = bake(root, lib)
    groups = baked.legacy_groups(root)
    assigned = [m for g in groups for m in g['members']]
    assert len(assigned) == len(set(assigned)), 'a rod in two groups'
    assert set(assigned) == set(range(len(baked.members))) - {
        len(baked.members) - 1}, 'only the ungrouped tie is unassigned'
    assert {g['name'] for g in groups} == {'T', 'braces'}


def test_a_joint_name_survives_what_a_node_index_would_not():
    """Supports keyed by index are lost on every renumber. Keyed by name,
    they are not -- which is the practical payoff of the whole bake."""
    root = GroupNode('model')
    bay = root.add(GroupNode('bay'))
    bay.add(RodPrimitive((0, 0, 0), (6, 0, 0)))
    bay.add(JointPrimitive((0, 0, 0), 'support_left'))
    before = bake(root).joint_nodes['bay/support_left']
    # Insert a rod EARLIER in the tree, which renumbers every node after it.
    root.add(RodPrimitive((-9, 0, 0), (-8, 0, 0), 'new'), index=0)
    after = bake(root).joint_nodes['bay/support_left']
    assert before != after, 'the node index really did move'
    baked = bake(root)
    assert baked.nodes[after] == (0.0, 0.0, 0.0)


def test_sibling_members_find_the_same_part_in_every_copy():
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, root.add(_truss()), 'T')
    root.add(lib.place('def1', local=Transform.translation(0, 4, 0)))
    root.add(RodPrimitive((0, 0, 0), (0, 4, 0), 'unique tie'))
    baked = bake(root, lib)
    assert len(baked.sibling_members(0)) == 2
    tie = len(baked.members) - 1
    assert baked.sibling_members(tie) == [tie], 'a unique rod has no siblings'


def test_a_component_is_sized_by_its_worst_copy():
    """The design consequence of sharing a definition. Sizing from the
    selected instance leaves no trace on screen when it is wrong."""
    lib, root = DefinitionLibrary(), GroupNode('model')
    make_definition(lib, root.add(_truss()), 'T')
    root.add(lib.place('def1', local=Transform.translation(0, 4, 0)))
    baked = bake(root, lib)
    member_res = [{'N': 10.0}, {'N': 2.0}, {'N': 2.0},
                  {'N': -180.0}, {'N': 2.0}, {'N': 2.0}]
    env = baked.part_envelope(member_res)
    bottom = baked.origins[0].part_key()
    assert env[bottom]['instances'] == 2
    assert env[bottom]['min'] == -180.0 and env[bottom]['max'] == 10.0
    assert env[bottom]['worst_member'] == 3, 'the worst copy, not the first'


def test_rollup_gives_a_branch_its_quantities_without_a_second_solve():
    lib, root = DefinitionLibrary(), GroupNode('model')
    bay = root.add(GroupNode('bay'))
    bay.add(RodPrimitive((0, 0, 0), (3, 0, 0), meta={'A': 1e-3}))
    bay.add(RodPrimitive((3, 0, 0), (3, 4, 0), meta={'A': 1e-3}))
    baked = bake(root, lib)
    out = baked.rollup((bay.id,), member_res=[{'N': 5.0}, {'N': -8.0}])
    assert out['members'] == 2
    assert out['length_m'] == pytest.approx(7.0)
    assert out['nodes'] == 3
    assert out['mass_kg'] == pytest.approx(7.0 * 1e-3 * 78.5 * 1000 / 9.80665)
    assert out['N_min_kN'] == -8.0 and out['N_max_kN'] == 5.0


def test_an_instance_pointing_at_nothing_is_reported_not_crashed():
    root = GroupNode('model')
    root.add(InstanceNode('missing', 'ghost'))
    baked = bake(root, DefinitionLibrary())
    assert not baked.members
    assert len(baked.warnings) == 1 and 'not in the library' in baked.warnings[0]


def test_a_baked_member_carries_exactly_the_keys_the_solver_reads():
    """The contract, checked without importing the solver: stereo_math reads
    m['a'], m['b'], m.get('conn') and the section keys off each member, and
    nodes as (x, y, z) triples. This is what makes the bake drop-in."""
    root = GroupNode('model')
    root.add(RodPrimitive((0, 0, 0), (6, 0, 0),
                          meta={'A': 2e-3, 'E': 2.1e8, 'conn': 'rigid',
                                'I': 1e-6, 'J': 2e-6}))
    baked = bake(root)
    assert all(len(n) == 3 and all(isinstance(c, float) for c in n)
               for n in baked.nodes)
    m = baked.members[0]
    assert isinstance(m['a'], int) and isinstance(m['b'], int)
    assert m['conn'] == 'rigid'
    for key in ('A', 'E', 'I', 'J'):
        assert key in m, 'section key %r did not reach the member' % key
    assert m['length_m'] == pytest.approx(6.0)


def test_the_baked_model_is_what_the_solver_already_takes():
    """The whole point of the bake: no adapter between it and the solver."""
    # stereo_math reaches common.py, which imports Tk at module level, so on
    # a headless box without Tk this is skipped rather than failed -- the
    # same call tests/test_cable_web_diagnosis_fixes.py makes for scipy.
    pytest.importorskip('tkinter')
    from apps.stereo import stereo_math as sm
    lib, root = DefinitionLibrary(), GroupNode('model')
    section = {'A': 2e-3, 'E': 2.1e8, 'conn': 'pin'}
    truss = GroupNode('t')
    truss.add(RodPrimitive((0, 0, 0), (6, 0, 0), meta=dict(section)))
    truss.add(RodPrimitive((0, 0, 0), (3, 0, 2), meta=dict(section)))
    truss.add(RodPrimitive((3, 0, 2), (6, 0, 0), meta=dict(section)))
    truss.add(RodPrimitive((0, 0, 0), (0, 1, 0), meta=dict(section)))
    truss.add(RodPrimitive((6, 0, 0), (6, 1, 0), meta=dict(section)))
    truss.add(RodPrimitive((3, 0, 2), (3, 1, 2), meta=dict(section)))
    truss.add(RodPrimitive((0, 1, 0), (6, 1, 0), meta=dict(section)))
    truss.add(RodPrimitive((0, 1, 0), (3, 1, 2), meta=dict(section)))
    truss.add(RodPrimitive((3, 1, 2), (6, 1, 0), meta=dict(section)))
    truss.add(RodPrimitive((0, 0, 0), (3, 1, 2), meta=dict(section)))
    truss.add(RodPrimitive((3, 0, 2), (6, 1, 0), meta=dict(section)))
    truss.add(RodPrimitive((0, 1, 0), (3, 0, 2), meta=dict(section)))
    # Supports and loads are declared against JOINT NAMES, which is the
    # practical payoff: no node index appears anywhere in this test, so
    # nothing here has to be rewritten when the mesh renumbers.
    truss.add(JointPrimitive((0, 0, 0), 'A'))
    truss.add(JointPrimitive((6, 0, 0), 'B'))
    truss.add(JointPrimitive((0, 1, 0), 'C'))
    truss.add(JointPrimitive((6, 1, 0), 'D'))
    truss.add(JointPrimitive((3, 0, 2), 'apex'))
    root.add(truss)
    baked = bake(root, lib)
    assert not baked.warnings

    at = baked.joint_nodes
    supports = [{'node': at['t/%s' % k], 'type': 'pin'} for k in 'ABCD']
    loads = [{'node': at['t/apex'], 'fz': -10.0}]
    res, err = sm.analyze(baked.nodes, baked.members, loads, supports)
    assert err is None, err
    assert len(res['member_res']) == len(baked.members)
    assert any(abs(r['N']) > 1e-6 for r in res['member_res']), \
        'the structure carried the load'

    # And the provenance still lines the results back up with the graph, so
    # a per-branch diagnosis is a lookup rather than a second solve.
    assert len(baked.members_under((truss.id,))) == len(baked.members)
    assert baked.rollup((truss.id,), res['member_res'])['members'] == 12
