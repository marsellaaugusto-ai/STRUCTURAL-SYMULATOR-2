"""Saving and loading the scene graph (apps/stereo/scene/{document,records,
persist}.py).

A round trip that "does not raise" proves nothing: an import that drops a
section, or reads a column into the wrong key, produces a model that loads
cleanly, analyses cleanly, and is NOT the model that was saved. That is the
failure worth testing for -- the same reasoning tests/test_excel_roundtrip.py
gives for the Model sheet -- so these compare what actually matters:

  * the BAKED model, field by field, before and after. Two documents that
    bake to the same nodes, members, sections, joint names and provenance are
    the same model whatever their internal ids happen to be.
  * the definition/instance structure, because a file that loses the sharing
    loads as a model that looks identical and behaves differently the moment
    someone edits a component.
  * what a DAMAGED file does. A persistence layer is judged on its worst
    input, not its best.
"""
import json
import os

import pytest

from apps.stereo.scene import (
    FORMAT, GroupNode, InstanceNode, JointPrimitive, MeshPrimitive,
    RodPrimitive, SceneDocument, Transform, TransformPolicy, bake,
    content_digest, duplicate_definitions, from_records, load_json,
    make_definition, make_unique, read_scene_sheet, restore, save_excel,
    save_json, snapshot, to_records, to_text, validate,
)
from apps.stereo.scene import persist, records


def _model():
    """One document exercising every record kind and every sharing case."""
    doc = SceneDocument(meta={'title': 'test roof', 'units': 'm'})

    truss = GroupNode('truss')
    truss.add(RodPrimitive((0, 0, 0), (6, 0, 0), 'bottom',
                           meta={'A': 1e-3, 'E': 2.1e8, 'conn': 'pin'},
                           joint_a='L', joint_b='R'))
    truss.add(RodPrimitive((0, 0, 0), (3, 0, 2), 'left', meta={'A': 5e-4}))
    truss.add(RodPrimitive((3, 0, 2), (6, 0, 0), 'right', meta={'A': 5e-4}))
    truss.add(JointPrimitive((0, 0, 0), 'bearing'))
    doc.root.add(truss)
    make_definition(doc.library, truss, 'Truss T1')

    # A second placement, rotated, with a per-instance override.
    doc.root.add(doc.library.place(
        'def1', local=Transform.rotation('Z', 15) @ Transform.translation(0, 4, 0),
        overrides={'A': 9e-3}))
    # A unique group that is nobody's component, nested two deep.
    bay = doc.root.add(GroupNode('bay', local=Transform.translation(0, 0, 3)))
    inner = bay.add(GroupNode('inner', local=Transform.rotation('X', 10)))
    inner.add(RodPrimitive((0, 0, 0), (0, 4, 0), 'tie', meta={'A': 2e-4}))
    inner.add(MeshPrimitive([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)],
                            'gusset', meta={'t_mm': 8}))
    # A free-policy component, so the policy itself has to survive.
    stretchy = GroupNode('mast', children=[RodPrimitive((0, 0, 0), (0, 0, 5))])
    doc.root.add(stretchy)
    make_definition(doc.library, stretchy, 'Mast',
                    policy=TransformPolicy.FREE)
    return doc


def _fingerprint(doc):
    """Everything about a model that a save must not change.

    Deliberately NOT the ids: a load makes fresh objects, and a canonical
    save renumbers on purpose, so comparing ids would fail on a correct
    round trip and pass on one that scrambled the geometry.
    """
    baked = doc.bake()
    return {
        'nodes': [tuple(round(c, 12) for c in n) for n in baked.nodes],
        'members': [(m['a'], m['b'], m.get('conn'), m.get('A'), m.get('E'),
                     round(m['length_m'], 12)) for m in baked.members],
        'joints': dict(sorted(baked.joint_nodes.items())),
        'origins': [(o.definition_id, len(o.path), len(o.instance_path))
                    for o in baked.origins],
        'meshes': [(tuple(tuple(round(c, 12) for c in v) for v in verts),
                    tuple(map(tuple, faces)), tuple(sorted(meta.items())))
                   for _path, verts, faces, meta in baked.meshes],
        'warnings': baked.warnings,
        'doc_meta': dict(sorted(doc.meta.items())),
        'definitions': sorted(
            (d.name, d.policy, content_digest(d, doc.library))
            for d in doc.library.all()),
        'tree': _shape(doc.root),
    }


def _shape(obj):
    return (obj.KIND, obj.name,
            getattr(obj, 'definition_id', None),
            tuple(_shape(c) for c in obj.children()))


# ── the document container ─────────────────────────────────────────────────

def test_canonical_renumber_is_derived_from_position_only():
    """Two documents built by the same steps must number identically, or a
    saved model cannot be diffed against one built the same way."""
    one, two = _model(), _model()
    one.canonical_renumber()
    two.canonical_renumber()
    assert [o.id for o in one.walk_all()] == [o.id for o in two.walk_all()]
    assert [d.id for d in one.library.all()] == [d.id for d in two.library.all()]


def test_the_same_model_built_twice_saves_byte_for_byte_identically():
    first, _, _ = to_records(_model())
    second, _, _ = to_records(_model())
    assert to_text(first) == to_text(second)


def test_renumbering_hands_back_a_map_the_caller_can_follow():
    doc = _model()
    before = {o.id: o for o in doc.walk_all()}
    obj_map, def_map = doc.canonical_renumber()
    assert set(obj_map) == set(before)
    for old, new in obj_map.items():
        assert before[old].id == new, 'the map must describe what was done'
    assert set(def_map) == {'def1', 'def2'}


def test_an_object_made_after_a_renumber_cannot_collide_with_one():
    doc = _model()
    doc.canonical_renumber()
    taken = {o.id for o in doc.walk_all()}
    fresh = [GroupNode('new %d' % i) for i in range(5)]
    assert not (taken & {o.id for o in fresh})


def test_a_definition_made_after_a_load_does_not_reuse_a_saved_id():
    doc = _model()
    data, _, _ = to_records(doc)
    loaded, _, _ = from_records(data)
    new = make_definition(loaded.library,
                          loaded.root.add(GroupNode('late', children=[
                              RodPrimitive((0, 0, 0), (1, 0, 0))])), 'Late')
    assert new.definition_id not in {'def1', 'def2'}
    assert len(loaded.library.all()) == 3


def test_content_digest_sees_the_part_not_the_name():
    doc = SceneDocument()
    for name in ('A', 'B'):
        g = doc.root.add(GroupNode(name, children=[
            RodPrimitive((0, 0, 0), (6, 0, 0))]))
        make_definition(doc.library, g, name)
    dupes = duplicate_definitions(doc.library)
    assert len(dupes) == 1 and len(next(iter(dupes.values()))) == 2
    # And a real difference in geometry separates them again.
    doc.library.get('def2').content.children()[0].b = (6.5, 0.0, 0.0)
    assert not duplicate_definitions(doc.library)


def test_content_digest_ignores_a_sign_on_zero():
    """-0.0 and 0.0 place geometry identically, so they must hash alike --
    otherwise a mirror operation makes a part stop matching itself."""
    doc = SceneDocument()
    a = doc.root.add(GroupNode('a', children=[RodPrimitive((0.0, 0, 0), (1, 0, 0))]))
    b = doc.root.add(GroupNode('b', children=[RodPrimitive((-0.0, 0, 0), (1, 0, 0))]))
    make_definition(doc.library, a, 'a')
    make_definition(doc.library, b, 'b')
    assert len(duplicate_definitions(doc.library)) == 1


# ── records ────────────────────────────────────────────────────────────────

def test_a_full_model_round_trips_through_records_unchanged():
    doc = _model()
    want = _fingerprint(doc)
    data, _, _ = to_records(doc)
    back, warnings, _ = from_records(data)
    assert warnings == []
    assert _fingerprint(back) == want


def test_defaults_are_omitted_so_a_diff_shows_only_what_was_set():
    doc = SceneDocument()
    doc.root.add(RodPrimitive((0, 0, 0), (1, 0, 0)))
    data, _, _ = to_records(doc)
    rod = [r for r in data['objects'] if r['kind'] == 'rod'][0]
    assert 'xform' not in rod, 'an identity transform is not written'
    assert 'meta' not in rod and 'name' not in rod
    assert 'joint_a' not in rod


def test_a_record_with_nothing_but_the_essentials_still_loads():
    """The other side of the same rule: absent means default, never error --
    which is what lets a file written by an older build load."""
    data = {'format': FORMAT, 'root': 1, 'definitions': [],
            'objects': [{'id': 1, 'kind': 'group', 'parent': None},
                        {'id': 2, 'kind': 'rod', 'parent': 1,
                         'a': [0, 0, 0], 'b': [3, 0, 0]}]}
    doc, warnings, _ = from_records(data)
    assert warnings == []
    assert doc.root.local.is_identity() and doc.root.name == ''
    baked = doc.bake()
    assert len(baked.members) == 1 and baked.members[0]['length_m'] == 3.0


def test_child_order_is_file_order():
    doc = SceneDocument()
    for i in range(6):
        doc.root.add(RodPrimitive((i, 0, 0), (i + 1, 0, 0), 'rod %d' % i))
    data, _, _ = to_records(doc)
    back, _, _ = from_records(data)
    assert [c.name for c in back.root.children()] == ['rod %d' % i for i in range(6)]
    # And reordering the records reorders the children, with nothing else
    # needing to change -- there is no second ordering to disagree with.
    data['objects'] = [data['objects'][0]] + list(reversed(data['objects'][1:]))
    shuffled, _, _ = from_records(data)
    assert [c.name for c in shuffled.root.children()] == \
        ['rod %d' % i for i in reversed(range(6))]


def test_the_transform_is_stored_as_twelve_numbers():
    doc = SceneDocument()
    doc.root.add(GroupNode('g', local=Transform.translation(1, 2, 3)
                           @ Transform.rotation('Z', 30)))
    data, _, _ = to_records(doc)
    rec = [r for r in data['objects'] if r.get('name') == 'g'][0]
    assert len(rec['xform']) == 12, 'the implied bottom row is not written'
    back, _, _ = from_records(data)
    assert back.root.children()[0].local.approx_equal(
        doc.root.children()[0].local)


def test_a_hand_pasted_sixteen_float_matrix_is_tolerated():
    doc = SceneDocument()
    doc.root.add(GroupNode('g'))
    data, _, _ = to_records(doc)
    rec = [r for r in data['objects'] if r.get('name') == 'g'][0]
    rec['xform'] = list(Transform.translation(0, 0, 9).m)
    back, _, _ = from_records(data)
    assert back.root.children()[0].local.translation_part == (0.0, 0.0, 9.0)


def test_floats_survive_exactly():
    """A persistence layer that rounds is a persistence layer that moves the
    model a little every time it is opened."""
    awkward = 1.0 / 3.0
    doc = SceneDocument()
    doc.root.add(RodPrimitive((awkward, -awkward, 1e-9),
                              (1e12, 2.5e-15, -0.0)))
    back, _, _ = from_records(json.loads(to_text(to_records(doc)[0])))
    rod = back.root.children()[0]
    assert rod.a == (awkward, -awkward, 1e-9)
    assert rod.b == (1e12, 2.5e-15, -0.0)


def test_sharing_survives_the_round_trip():
    """A file that loses the sharing loads as a model that looks identical
    and behaves differently the moment someone edits a component."""
    doc = _model()
    data, _, _ = to_records(doc)
    back, _, _ = from_records(data)
    instances = [o for o in back.root.walk() if o.is_instance()]
    assert len(instances) == 3
    shared = [o for o in instances if o.definition_id == 'def1']
    assert len(shared) == 2
    # One edit to the definition must still reach both placements.
    back.library.get('def1').content.children()[0].meta['A'] = 4e-3
    baked = back.bake()
    bottoms = [m['A'] for m, o in zip(baked.members, baked.origins)
               if o.definition_id == 'def1' and m.get('A') in (4e-3, 9e-3)]
    assert 4e-3 in bottoms, 'the shared edit reached the un-overridden copy'


def test_a_policy_survives_so_a_loaded_part_is_still_protected():
    doc = _model()
    back, _, _ = from_records(to_records(doc)[0])
    rigid = [d for d in back.library.all() if d.name == 'Truss T1'][0]
    free = [d for d in back.library.all() if d.name == 'Mast'][0]
    assert rigid.policy == TransformPolicy.RIGID
    assert free.policy == TransformPolicy.FREE
    with pytest.raises(ValueError):
        back.library.place(rigid.id, local=Transform.scale(2, 1, 1))
    back.library.place(free.id, local=Transform.scale(2, 1, 1))


def test_make_unique_after_a_load_behaves_as_it_did_before_one():
    doc = _model()
    back, _, _ = from_records(to_records(doc)[0])
    inst = [o for o in back.root.children()
            if o.is_instance() and o.definition_id == 'def1'][0]
    before = sorted(back.bake().nodes)
    group = make_unique(back.library, inst)
    assert sorted(back.bake().nodes) == pytest.approx(before)
    group.children()[0].meta['A'] = 1.0
    assert back.library.get('def1').content.children()[0].meta['A'] != 1.0


# ── a damaged file ─────────────────────────────────────────────────────────

def _minimal():
    return {'format': FORMAT, 'root': 1, 'definitions': [],
            'objects': [{'id': 1, 'kind': 'group', 'parent': None}]}


@pytest.mark.parametrize('break_it, expect', [
    (lambda d: d.update(format='SOMETHING-ELSE/1'), 'not a scene file'),
    (lambda d: d.update(format='STEREO-SCENE/99'), 'no migration'),
    (lambda d: d.update(objects=[]), 'no objects'),
    (lambda d: d.update(root=77), 'no such object'),
    (lambda d: d['objects'].append({'id': 1, 'kind': 'group', 'parent': None}),
     'share the id'),
    (lambda d: d['objects'].append({'id': 2, 'kind': 'group', 'parent': 9}),
     'no such object'),
    (lambda d: d['objects'].append({'id': 2, 'kind': 'rod', 'parent': 1,
                                    'a': [0, 0, 0]}), 'no usable'),
    (lambda d: d['objects'].append({'id': 2, 'kind': 'joint', 'parent': 1,
                                    'at': [0, 0, 0], 'key': ''}), 'no key'),
    (lambda d: d['objects'].append({'id': 2, 'kind': 'mesh', 'parent': 1,
                                    'vertices': [[0, 0, 0]],
                                    'faces': [[0, 1, 2]]}), 'does not have'),
    (lambda d: d['objects'].append({'id': 2, 'kind': 'group', 'parent': 1,
                                    'xform': [1, 2, 3]}), 'unusable transform'),
    (lambda d: d['definitions'].append({'id': 'def1', 'content': 99}),
     'no such object'),
    (lambda d: (d['objects'].append({'id': 2, 'kind': 'rod', 'parent': 1,
                                     'a': [0, 0, 0], 'b': [1, 0, 0]}),
                d['definitions'].append({'id': 'def1', 'content': 2})),
     'must be a group'),
])
def test_an_impossible_file_is_refused_with_a_message_for_a_person(break_it, expect):
    data = _minimal()
    break_it(data)
    with pytest.raises(ValueError) as caught:
        from_records(data)
    assert expect in str(caught.value), str(caught.value)


def test_a_loop_of_parents_is_refused_rather_than_hung_on():
    data = _minimal()
    data['objects'] += [{'id': 2, 'kind': 'group', 'parent': 3},
                        {'id': 3, 'kind': 'group', 'parent': 2}]
    with pytest.raises(ValueError) as caught:
        from_records(data)
    assert 'loop of parents' in str(caught.value)


def test_a_definition_claimed_by_two_definitions_is_refused():
    data = _minimal()
    data['objects'].append({'id': 2, 'kind': 'group', 'parent': None})
    data['definitions'] += [{'id': 'def1', 'content': 2},
                            {'id': 'def2', 'content': 2}]
    with pytest.raises(ValueError) as caught:
        from_records(data)
    assert 'both claim' in str(caught.value)


@pytest.mark.parametrize('definitions, objects, loop', [
    # Direct: a definition whose content places itself.
    ([{'id': 'def1', 'content': 2}],
     [{'id': 2, 'kind': 'group', 'parent': None},
      {'id': 3, 'kind': 'instance', 'parent': 2, 'definition': 'def1'}],
     "'def1' -> 'def1'"),
    # Indirect, which is the one a person could plausibly hand-edit into
    # being without noticing.
    ([{'id': 'def1', 'content': 2}, {'id': 'def2', 'content': 4}],
     [{'id': 2, 'kind': 'group', 'parent': None},
      {'id': 3, 'kind': 'instance', 'parent': 2, 'definition': 'def2'},
      {'id': 4, 'kind': 'group', 'parent': None},
      {'id': 5, 'kind': 'instance', 'parent': 4, 'definition': 'def1'}],
     "'def1' -> 'def2' -> 'def1'"),
])
def test_a_definition_containing_itself_is_refused_at_load(definitions,
                                                           objects, loop):
    """The library refuses to BUILD one, so this can only arrive from a
    hand-edited or half-merged file. Without the check the file loads, and
    the bake finds out 64 levels down having already emitted what it met on
    the way."""
    data = _minimal()
    data['definitions'] += definitions
    data['objects'] += objects
    with pytest.raises(ValueError) as caught:
        from_records(data)
    assert 'contains itself' in str(caught.value)
    assert loop in str(caught.value), 'the message names the loop'


def test_one_definition_nested_inside_another_round_trips():
    """A bay holding truss instances is the case definitions exist for, and
    the one the cycle check must not mistake for a loop."""
    doc = SceneDocument()
    truss = GroupNode('truss', children=[RodPrimitive((0, 0, 0), (6, 0, 0))])
    doc.root.add(truss)
    truss_inst = make_definition(doc.library, truss, 'Truss')
    bay = GroupNode('bay', children=[truss_inst])
    bay.add(doc.library.place(truss_inst.definition_id,
                              local=Transform.translation(0, 3, 0)))
    doc.root.add(bay)
    bay_inst = make_definition(doc.library, bay, 'Bay')
    doc.root.add(doc.library.place(bay_inst.definition_id,
                                   local=Transform.translation(12, 0, 0)))
    want = _fingerprint(doc)

    back, warnings, _ = from_records(to_records(doc)[0])
    assert warnings == []
    assert _fingerprint(back) == want
    assert len(back.bake().members) == 4
    # The inner definition must still be shared by the outer one's content,
    # not copied into it -- one edit, four rods.
    inner = [d for d in back.library.all() if d.name == 'Truss'][0]
    assert len(back.library.instances_of(back.root, inner.id)) == 2
    inner.content.children()[0].meta['A'] = 5e-3
    assert all(m['A'] == 5e-3 for m in back.bake().members)


def test_definitions_are_written_before_the_ones_that_place_them():
    """Depth-first order, so a loader never meets a reference it cannot
    resolve yet -- and so a diff of the table reads in dependency order."""
    doc = SceneDocument()
    truss = doc.root.add(GroupNode('truss', children=[
        RodPrimitive((0, 0, 0), (6, 0, 0))]))
    truss_inst = make_definition(doc.library, truss, 'Truss')
    bay = doc.root.add(GroupNode('bay', children=[truss_inst]))
    make_definition(doc.library, bay, 'Bay')
    data, _, _ = to_records(doc)
    names = [d['name'] for d in data['definitions']]
    assert names.index('Truss') < names.index('Bay')


def test_a_recoverable_gap_loads_the_rest_and_says_what_it_lost():
    """A user with a damaged file wants the other 99% of their work back,
    not a dialog."""
    data = _minimal()
    data['objects'] += [
        {'id': 2, 'kind': 'rod', 'parent': 1, 'a': [0, 0, 0], 'b': [6, 0, 0]},
        {'id': 3, 'kind': 'instance', 'parent': 1, 'definition': 'gone'},
        {'id': 4, 'kind': 'teleporter', 'parent': 1},
        {'id': 5, 'kind': 'rod', 'parent': 4, 'a': [0, 0, 0], 'b': [1, 0, 0]},
        {'id': 6, 'kind': 'group', 'parent': None, 'name': 'orphan'},
    ]
    doc, warnings, _ = from_records(data)
    assert len(warnings) == 3
    assert any('does not contain' in w for w in warnings)
    assert any('unknown kind' in w for w in warnings)
    assert any('no parent' in w for w in warnings)
    # The one good rod survived; the rod under the unknown kind did NOT come
    # back re-parented to the root, where it would sit at the wrong place
    # with nothing on screen to say so.
    baked = doc.bake()
    assert len(baked.members) == 1
    assert baked.members[0]['length_m'] == 6.0


def test_strict_refuses_what_lenient_salvages():
    data = _minimal()
    data['objects'].append({'id': 2, 'kind': 'instance', 'parent': 1,
                            'definition': 'gone'})
    doc, warnings, _ = from_records(data, strict=False)
    assert len(warnings) == 1
    with pytest.raises(ValueError) as caught:
        from_records(data, strict=True)
    assert 'strict' in str(caught.value)


def test_validate_does_not_build_anything():
    """Validation runs before construction, so an impossible file never
    leaves a half-built document behind -- which looks like a model."""
    data = _minimal()
    data['objects'].append({'id': 2, 'kind': 'group', 'parent': 99})
    with pytest.raises(ValueError):
        validate(data)


def test_an_unknown_policy_is_read_as_the_safe_one():
    data = _minimal()
    data['objects'].append({'id': 2, 'kind': 'group', 'parent': None})
    data['definitions'].append({'id': 'def1', 'content': 2,
                                'policy': 'whatever'})
    doc, warnings, _ = from_records(data)
    assert any('unknown policy' in w for w in warnings)
    assert doc.library.get('def1').policy == TransformPolicy.RIGID


# ── JSON on disk ───────────────────────────────────────────────────────────

def test_a_file_round_trips_through_the_disk(tmp_path):
    doc = _model()
    want = _fingerprint(doc)
    path = tmp_path / ('roof' + persist.SUFFIX)
    save_json(doc, path)
    back, warnings, _ = load_json(path)
    assert warnings == []
    assert _fingerprint(back) == want


def test_a_saved_file_is_sorted_indented_text_a_person_can_diff(tmp_path):
    path = tmp_path / 'a.scene.json'
    save_json(_model(), path)
    text = path.read_text(encoding='utf-8')
    assert text.endswith('\n')
    assert '\n  "definitions"' in text and '\n  "format"' in text
    assert text.index('"definitions"') < text.index('"format"'), 'keys sorted'
    # One field per line is what makes a diff readable.
    assert text.count('\n') > len(_model().root.walk().__sizeof__().__str__())


def test_a_failed_save_leaves_the_previous_file_intact(tmp_path):
    path = tmp_path / 'keep.scene.json'
    save_json(_model(), path)
    good = path.read_text(encoding='utf-8')

    class Unwritable:
        """A document whose records raise half way through being written."""
        def canonical_renumber(self):
            raise OSError('disk full')

    with pytest.raises(OSError):
        save_json(Unwritable(), path)
    assert path.read_text(encoding='utf-8') == good
    # And no temp file is left lying beside it.
    assert [p.name for p in tmp_path.iterdir()] == ['keep.scene.json']


def test_an_interrupted_write_leaves_no_debris(tmp_path):
    """The temp file must go whether the write succeeded or not, or a folder
    fills up with half-written models that look like recoverable saves."""
    path = tmp_path / 'x.scene.json'
    with pytest.raises(TypeError):
        persist.write_text(path, 12345)        # not text; fh.write refuses
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_truncated_json_says_what_to_do_about_it(tmp_path):
    path = tmp_path / 'bad.scene.json'
    save_json(_model(), path)
    text = path.read_text(encoding='utf-8')
    path.write_text(text[:len(text) // 2], encoding='utf-8')
    with pytest.raises(ValueError) as caught:
        load_json(path)
    assert 'previous save' in str(caught.value)


def test_a_missing_file_is_a_message_not_a_traceback(tmp_path):
    with pytest.raises(ValueError) as caught:
        load_json(tmp_path / 'nope.scene.json')
    assert 'cannot read' in str(caught.value)


def test_saving_creates_the_folder_it_was_pointed_at(tmp_path):
    path = tmp_path / 'new' / 'deeper' / 'a.scene.json'
    save_json(_model(), path)
    assert path.exists()


# ── undo snapshots ─────────────────────────────────────────────────────────

def test_a_snapshot_restores_the_model_and_its_library():
    """An undo across "make component" has to put the definition back too."""
    doc = _model()
    want = _fingerprint(doc)
    shot = snapshot(doc)
    # Wreck it thoroughly: explode a component, move a bay, delete a rod.
    inst = [o for o in doc.root.children()
            if o.is_instance() and o.definition_id == 'def1'][0]
    make_unique(doc.library, inst)
    doc.root.children()[0].apply_local(Transform.translation(0, 0, 99))
    bay = [o for o in doc.root.children() if o.name == 'bay'][0]
    bay.children()[0].remove(bay.children()[0].children()[0])
    assert _fingerprint(doc) != want

    back, id_map = restore(shot)
    assert _fingerprint(back) == want
    assert id_map, 'a caller holding ids must be able to follow them'


def test_a_snapshot_does_not_renumber_the_document_being_edited():
    """Pressing Ctrl+Z once must not invalidate the user's selection as a
    side effect of taking a snapshot."""
    doc = _model()
    before = [o.id for o in doc.walk_all()]
    snapshot(doc)
    assert [o.id for o in doc.walk_all()] == before


def test_a_snapshot_is_inert():
    """It must not share mutable state with the document it came from, or an
    undo would restore the edits it was meant to undo."""
    doc = _model()
    shot = snapshot(doc)
    doc.root.children()[0].meta['touched'] = True
    for obj in doc.walk_all():
        if obj.meta:
            obj.meta.clear()
    back, _ = restore(shot)
    assert any(o.meta for o in back.walk_all())


# ── the Excel sheet ────────────────────────────────────────────────────────

def test_a_snapshot_shares_no_nested_state_with_its_document():
    """The shallow-copy trap: dict(meta) leaves a nested mutable shared, so
    an undo would carry the very edits it exists to roll back."""
    doc = SceneDocument(meta={'notes': {'by': 'me'}})
    g = doc.root.add(GroupNode('bay', meta={'checks': {'buckling': 'ok'},
                                            'tags': ['a']}))
    group = doc.root.add(GroupNode('t', children=[
        RodPrimitive((0, 0, 0), (1, 0, 0))]))
    inst = make_definition(doc.library, group, 'T')
    inst.overrides['limits'] = {'N_kN': 10}
    shot = snapshot(doc)

    g.meta['checks']['buckling'] = 'FAILED'
    g.meta['tags'].append('b')
    doc.meta['notes']['by'] = 'someone else'
    inst.overrides['limits']['N_kN'] = 999

    back, _ = restore(shot)
    bay = [o for o in back.walk_all() if o.name == 'bay'][0]
    assert bay.meta['checks'] == {'buckling': 'ok'}
    assert bay.meta['tags'] == ['a']
    assert back.meta['notes'] == {'by': 'me'}
    restored = [o for o in back.root.walk() if o.is_instance()][0]
    assert restored.overrides['limits'] == {'N_kN': 10}


def test_a_restored_document_does_not_write_back_into_its_snapshot():
    """The same trap the other way: editing a restored model must not
    corrupt the snapshot, or a second undo gives a different answer."""
    doc = SceneDocument()
    doc.root.add(GroupNode('bay', meta={'checks': {'buckling': 'ok'}}))
    shot = snapshot(doc)
    first, _ = restore(shot)
    [o for o in first.walk_all()
     if o.name == 'bay'][0].meta['checks']['buckling'] = 'FAILED'
    second, _ = restore(shot)
    assert [o for o in second.walk_all()
            if o.name == 'bay'][0].meta['checks'] == {'buckling': 'ok'}


def test_a_long_chain_of_parents_validates_in_one_pass():
    """Not a timing test -- a correctness one over a shape that used to be
    quadratic: the cycle walk climbed from every object independently, so a
    single deep chain cost one climb per object on every load."""
    data = _minimal()
    depth = 4000
    for i in range(2, depth + 2):
        data['objects'].append({'id': i, 'kind': 'group', 'parent': i - 1})
    assert validate(data) == []
    # A loop at the very bottom of that chain must still be found, and the
    # message must name only the loop, not the thousands of innocent
    # objects above it.
    data['objects'] += [{'id': depth + 2, 'kind': 'group', 'parent': depth + 3},
                        {'id': depth + 3, 'kind': 'group', 'parent': depth + 2}]
    with pytest.raises(ValueError) as caught:
        validate(data)
    assert 'loop of parents' in str(caught.value)
    assert str(depth + 2) in str(caught.value)
    assert ' 2,' not in str(caught.value), 'only the loop is named'


def test_the_scene_sheet_round_trips(tmp_path):
    pytest.importorskip('openpyxl')
    doc = _model()
    want = _fingerprint(doc)
    path = tmp_path / 'scene.xlsx'
    save_excel(doc, path)
    back, warnings, _ = read_scene_sheet(path)
    assert warnings == []
    assert _fingerprint(back) == want


def test_the_scene_sheet_travels_beside_the_model_sheet(tmp_path):
    """A model split across two files is a model that gets separated."""
    openpyxl = pytest.importorskip('openpyxl')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Model'
    ws.cell(row=1, column=1, value='[NODES]')
    persist.write_scene_sheet(wb, _model())
    path = tmp_path / 'both.xlsx'
    wb.save(path)
    reopened = openpyxl.load_workbook(path)
    assert reopened.sheetnames == ['Model', 'Scene']
    back, warnings, _ = read_scene_sheet(path)
    assert warnings == [] and len(back.bake().members) > 0


def test_columns_are_read_by_name_so_an_older_sheet_still_loads(tmp_path):
    """The rule the existing Model sheet follows: a column added later must
    not shift the ones before it, and one absent must not be an error."""
    openpyxl = pytest.importorskip('openpyxl')
    path = tmp_path / 'scene.xlsx'
    save_excel(_model(), path)
    wb = openpyxl.load_workbook(path)
    ws = wb['Scene']
    header_row = next(r for r in range(1, ws.max_row + 1)
                      if ws.cell(row=r, column=1).value == 'id'
                      and ws.cell(row=r - 1, column=1).value == '[OBJECTS]')
    headers = [ws.cell(row=header_row, column=c).value
               for c in range(1, ws.max_column + 1)]
    # Insert a column a future build might add, in the middle.
    ws.insert_cols(5)
    ws.cell(row=header_row, column=5, value='something_new')
    wb.save(path)
    back, warnings, _ = read_scene_sheet(path)
    assert warnings == []
    # 3 truss rods x 2 placements, the bay's tie, and the mast = 8.
    assert len(back.bake().members) == 8
    assert 'kind' in headers and 'tx_m' in headers


def test_a_workbook_without_a_scene_sheet_says_so(tmp_path):
    openpyxl = pytest.importorskip('openpyxl')
    wb = openpyxl.Workbook()
    path = tmp_path / 'plain.xlsx'
    wb.save(path)
    with pytest.raises(ValueError) as caught:
        read_scene_sheet(path)
    assert 'no "Scene" sheet' in str(caught.value)


def test_a_cell_too_big_for_a_spreadsheet_is_refused_not_truncated(tmp_path):
    """A silently clipped vertex list is a model that loads and is not the
    model that was saved."""
    pytest.importorskip('openpyxl')
    doc = SceneDocument()
    doc.root.add(MeshPrimitive([(i, i, i) for i in range(4000)], []))
    with pytest.raises(ValueError) as caught:
        save_excel(doc, tmp_path / 'huge.xlsx')
    assert 'spreadsheet cell holds' in str(caught.value)
    assert persist.SUFFIX in str(caught.value)


def _scene_header(ws):
    """The [OBJECTS] header row and its column numbers, by name."""
    row = next(r for r in range(1, ws.max_row + 1)
               if ws.cell(row=r, column=1).value == 'id'
               and ws.cell(row=r - 1, column=1).value == '[OBJECTS]')
    return row, {ws.cell(row=row, column=c).value: c
                 for c in range(1, ws.max_column + 1)}


@pytest.mark.parametrize('label, expect', [
    ('root', "root should be a whole number"),
])
def test_a_careless_meta_edit_reads_as_a_sentence(tmp_path, label, expect):
    """A hand-edited sheet is the EXPECTED input for this codec, so a
    careless edit must come back as something a person can act on, not as
    int()'s own complaint about a literal."""
    openpyxl = pytest.importorskip('openpyxl')
    path = tmp_path / 'edit.xlsx'
    save_excel(_model(), path)
    wb = openpyxl.load_workbook(path)
    ws = wb['Scene']
    for r in range(1, ws.max_row + 1):
        if ws.cell(row=r, column=1).value == label:
            ws.cell(row=r, column=2, value='not a number')
    wb.save(path)
    with pytest.raises(ValueError) as caught:
        read_scene_sheet(path)
    assert expect in str(caught.value), str(caught.value)


def test_a_broken_formula_in_a_coordinate_says_what_to_do(tmp_path):
    """Excel writes a cached result, not a formula, only once it has
    recalculated and saved -- so this is a real way for a sheet to arrive."""
    openpyxl = pytest.importorskip('openpyxl')
    path = tmp_path / 'formula.xlsx'
    save_excel(_model(), path)
    wb = openpyxl.load_workbook(path)
    ws = wb['Scene']
    header, cols = _scene_header(ws)
    for r in range(header + 1, ws.max_row + 1):
        if ws.cell(row=r, column=cols['kind']).value == 'rod':
            ws.cell(row=r, column=cols['bx_m'], value='#REF!')
            break
    wb.save(path)
    with pytest.raises(ValueError) as caught:
        read_scene_sheet(path)
    assert 'not a number' in str(caught.value)
    assert 'recalculated' in str(caught.value)


def test_a_definition_with_no_content_cell_names_the_definition(tmp_path):
    openpyxl = pytest.importorskip('openpyxl')
    path = tmp_path / 'nocontent.xlsx'
    save_excel(_model(), path)
    wb = openpyxl.load_workbook(path)
    ws = wb['Scene']
    header = next(r for r in range(1, ws.max_row + 1)
                  if ws.cell(row=r, column=1).value == 'id'
                  and ws.cell(row=r - 1, column=1).value == '[DEFINITIONS]')
    cols = {ws.cell(row=header, column=c).value: c
            for c in range(1, ws.max_column + 1)}
    # Assigning .value clears it; cell(value=None) is read by openpyxl as
    # "no value given" and leaves what was there.
    ws.cell(row=header + 1, column=cols['content']).value = None
    wb.save(path)
    with pytest.raises(ValueError) as caught:
        read_scene_sheet(path)
    assert 'content of definition' in str(caught.value)


def test_resaving_replaces_the_scene_sheet_rather_than_stacking_them(tmp_path):
    openpyxl = pytest.importorskip('openpyxl')
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    doc = _model()
    persist.write_scene_sheet(wb, doc)
    persist.write_scene_sheet(wb, doc)
    assert wb.sheetnames == ['Scene']


def test_a_hand_typed_translation_does_what_it_looks_like(tmp_path):
    """Someone opening the sheet and typing one number into tz_m means "move
    it up", not "collapse it to a zero matrix"."""
    openpyxl = pytest.importorskip('openpyxl')
    doc = SceneDocument()
    doc.root.add(GroupNode('bay', children=[
        RodPrimitive((0, 0, 0), (6, 0, 0))]))
    path = tmp_path / 'edit.xlsx'
    save_excel(doc, path)
    wb = openpyxl.load_workbook(path)
    ws = wb['Scene']
    header_row, headers = _scene_header(ws)
    bay_row = next(r for r in range(header_row + 1, ws.max_row + 1)
                   if ws.cell(row=r, column=headers['name']).value == 'bay')
    ws.cell(row=bay_row, column=headers['tz_m'], value=3.0)
    wb.save(path)
    back, _, _ = read_scene_sheet(path)
    baked = back.bake()
    assert all(abs(n[2] - 3.0) < 1e-12 for n in baked.nodes)
    assert baked.members[0]['length_m'] == pytest.approx(6.0), \
        'the rest of the matrix was read as the identity, not as zeros'


# ── the bridge to what already exists ──────────────────────────────────────

def test_a_loaded_model_still_solves(tmp_path):
    pytest.importorskip('tkinter')
    from apps.stereo import stereo_math as sm
    doc = SceneDocument()
    section = {'A': 2e-3, 'E': 2.1e8, 'conn': 'pin'}
    g = doc.root.add(GroupNode('frame'))
    for a, b in (((0, 0, 0), (6, 0, 0)), ((0, 0, 0), (3, 0, 2)),
                 ((3, 0, 2), (6, 0, 0)), ((0, 0, 0), (0, 1, 0)),
                 ((6, 0, 0), (6, 1, 0)), ((3, 0, 2), (3, 1, 2)),
                 ((0, 1, 0), (6, 1, 0)), ((0, 1, 0), (3, 1, 2)),
                 ((3, 1, 2), (6, 1, 0)), ((0, 0, 0), (3, 1, 2)),
                 ((3, 0, 2), (6, 1, 0)), ((0, 1, 0), (3, 0, 2))):
        g.add(RodPrimitive(a, b, meta=dict(section)))
    for at, key in (((0, 0, 0), 'A'), ((6, 0, 0), 'B'),
                    ((0, 1, 0), 'C'), ((6, 1, 0), 'D'),
                    ((3, 0, 2), 'apex')):
        g.add(JointPrimitive(at, key))
    path = tmp_path / 'solvable.scene.json'
    save_json(doc, path)
    back, _, _ = load_json(path)
    baked = back.bake()
    assert not baked.warnings
    at = baked.joint_nodes
    supports = [{'node': at['frame/%s' % k], 'type': 'pin'} for k in 'ABCD']
    loads = [{'node': at['frame/apex'], 'fz': -10.0}]
    res, err = sm.analyze(baked.nodes, baked.members, loads, supports)
    assert err is None, err
    assert len(res['member_res']) == 12


def test_legacy_group_records_still_come_out_of_a_loaded_model(tmp_path):
    doc = _model()
    back, _, _ = load_json(_saved(doc, tmp_path))
    baked = back.bake()
    groups = baked.legacy_groups(back.root)
    assigned = [m for g in groups for m in g['members']]
    assert len(assigned) == len(set(assigned)), 'a rod in two groups'
    assert set(assigned) == set(range(len(baked.members)))


def _saved(doc, tmp_path):
    path = tmp_path / 'tmp.scene.json'
    save_json(doc, path)
    return path
