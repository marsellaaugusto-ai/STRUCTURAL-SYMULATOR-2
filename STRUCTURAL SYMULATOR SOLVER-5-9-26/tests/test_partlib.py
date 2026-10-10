"""A part saved to a file, and placed in another model.

A component says two groups in one model are the same fabricated part.
This is the same idea across files, and the two things worth guarding are
that the STEEL travels with the geometry -- a truss that arrives without
its sections is a sketch -- and that two placements of one file come out
as one component rather than as look-alikes.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from apps.stereo import stereo_components as scp
from apps.stereo import stereo_merge as smg
from apps.stereo import stereo_partlib as spl


def truss(ox=0.0, oy=0.0, oz=0.0):
    nodes = [(ox, oy, oz), (ox + 3, oy, oz), (ox + 1.5, oy, oz + 1.2)]
    members = [
        {'a': 0, 'b': 1, 'profile': 'IPE 200', 'A': 28.5, 'I': 1940.0,
         'conn': 'pin', 'E': 200.0, 'Fy': 235.0, 'role': 'bottom_chord'},
        {'a': 1, 'b': 2, 'profile': 'IPE 200', 'A': 28.5, 'I': 1940.0,
         'conn': 'pin', 'E': 200.0, 'Fy': 235.0, 'role': 'diagonal'},
        {'a': 2, 'b': 0, 'profile': 'CHS 76', 'A': 8.2, 'I': 50.0,
         'conn': 'rigid', 'E': 200.0, 'Fy': 275.0, 'role': 'diagonal'},
    ]
    return nodes, members


PROFILES = {'IPE 200': {'A': 28.5, 'I': 1940.0},
            'CHS 76': {'A': 8.2, 'I': 50.0},
            'NOT USED HERE': {'A': 1.0}}


def a_part(name='Mini truss'):
    nodes, members = truss()
    return spl.make_part(nodes, members, range(len(members)), name, PROFILES)


def empty():
    return {'nodes': [], 'members': [], 'loads': [], 'supports': [],
            'groups': [], 'profiles': {}}


# ── making one ───────────────────────────────────────────────────────────

def test_a_part_carries_its_rods_and_their_steel(a_part_=None):
    part = a_part()
    assert part['n_rods'] == 3
    assert [m['profile'] for m in part['members']] == \
        ['IPE 200', 'IPE 200', 'CHS 76']
    assert part['members'][2]['conn'] == 'rigid'
    assert part['members'][0]['role'] == 'bottom_chord'


def test_only_the_sections_it_actually_uses_come_along():
    """A library part should not drag a whole project's section list."""
    part = a_part()
    assert sorted(part['profiles']) == ['CHS 76', 'IPE 200']


def test_a_node_sits_at_the_origin():
    """A NODE, not a corner of the bounding box. Anchoring on a box
    corner would mean placing the part on a joint of the structure lands
    nothing on that joint, so nothing fuses and the part floats beside
    the model instead of being bolted to it."""
    nodes, members = truss(ox=100, oy=-40, oz=7)
    part = spl.make_part(nodes, members, range(3), 'Moved', PROFILES)
    assert part['nodes'][spl.anchor_of(part)] == [0, 0, 0]
    assert part['nodes'].count([0, 0, 0]) == 1


def test_where_it_was_drawn_does_not_travel():
    """The one thing about a part that cannot transfer.

    The coordinates come back the same to within the drift of having been
    subtracted from a large offset, and the SIGNATURE comes back equal
    outright -- which is the comparison that decides whether two parts are
    one part, and the reason it is quantised rather than exact.
    """
    here = spl.make_part(*truss(), range(3), 'A', PROFILES)
    there = spl.make_part(*truss(50, 60, 70), range(3), 'A', PROFILES)
    for mine, yours in zip(here['nodes'], there['nodes']):
        assert mine == pytest.approx(yours, abs=1e-9)
    assert here['signature'] == there['signature']


def test_it_knows_how_big_it_is():
    assert spl.size(a_part()) == pytest.approx((3.0, 0.0, 1.2))


def test_a_part_needs_something_in_it():
    nodes, members = truss()
    with pytest.raises(spl.PartError):
        spl.make_part(nodes, members, [], 'Nothing', PROFILES)
    with pytest.raises(spl.PartError):
        spl.make_part(nodes, members, [99], 'Gone', PROFILES)


def test_part_of_a_model_can_be_saved_on_its_own():
    nodes, members = truss()
    part = spl.make_part(nodes, members, [0], 'One bar', PROFILES)
    assert part['n_rods'] == 1
    assert len(part['nodes']) == 2


# ── the file ─────────────────────────────────────────────────────────────

def test_a_part_survives_being_written_and_read(tmp_path):
    part = a_part()
    path = spl.save_part(part, str(tmp_path / ('m' + spl.SUFFIX)))
    assert spl.load_part(path) == part


def test_the_file_is_readable_by_a_person(tmp_path):
    path = spl.save_part(a_part(), str(tmp_path / ('m' + spl.SUFFIX)))
    text = open(path, encoding='utf-8').read()
    assert '\n' in text and 'Mini truss' in text
    assert json.loads(text)['format'] == spl.FORMAT


def test_a_failed_write_does_not_destroy_what_was_there(tmp_path,
                                                         monkeypatch):
    """A library someone adds to over months must not be left with half a
    file where a part used to be."""
    path = str(tmp_path / ('m' + spl.SUFFIX))
    spl.save_part(a_part('Good'), path)
    broken = dict(a_part('Bad'))
    broken['members'] = [{'a': object()}]      # not serialisable
    with pytest.raises(Exception):
        spl.save_part(broken, path)
    assert spl.load_part(path)['name'] == 'Good'
    assert not [n for n in os.listdir(str(tmp_path)) if n.endswith('.tmp')]


@pytest.mark.parametrize('damage,says', [
    ({'format': 'SOMETHING ELSE'}, 'this version reads'),
    ({'nodes': []}, 'nothing to place'),
    ({'members': []}, 'nothing to place'),
    ({'nodes': [[0, 0, 0], 'nope']}, 'not a point'),
    ({'members': [{'a': 0}]}, 'no ends'),
    ({'members': [{'a': 0, 'b': 99}]}, 'does not have'),
])
def test_a_file_that_is_wrong_is_refused_with_a_reason(tmp_path, damage,
                                                        says):
    """Refused rather than placing geometry that references nodes it does
    not have."""
    part = dict(a_part())
    part.update(damage)
    path = str(tmp_path / ('bad' + spl.SUFFIX))
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(part, fh)
    with pytest.raises(spl.PartError, match=says):
        spl.load_part(path)


def test_something_that_is_not_json_at_all_is_refused(tmp_path):
    path = str(tmp_path / ('junk' + spl.SUFFIX))
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('not json')
    with pytest.raises(spl.PartError, match='could not be read'):
        spl.load_part(path)


def test_a_library_lists_what_is_in_it(tmp_path):
    spl.save_part(a_part('Alpha'), str(tmp_path / ('a' + spl.SUFFIX)))
    spl.save_part(a_part('Beta'), str(tmp_path / ('b' + spl.SUFFIX)))
    found = spl.list_parts(str(tmp_path))
    assert [p['name'] for _path, p, _err in found] == ['Alpha', 'Beta']


def test_one_bad_file_does_not_hide_the_rest_of_the_library(tmp_path):
    spl.save_part(a_part('Good'), str(tmp_path / ('a' + spl.SUFFIX)))
    with open(str(tmp_path / ('b' + spl.SUFFIX)), 'w') as fh:
        fh.write('junk')
    found = spl.list_parts(str(tmp_path))
    assert len(found) == 2
    assert [p['name'] for _p, p, e in found if p] == ['Good']
    assert [e for _p, p, e in found if e]


def test_a_folder_that_is_not_there_is_an_empty_library(tmp_path):
    assert spl.list_parts(str(tmp_path / 'nowhere')) == []


def test_other_files_in_the_folder_are_left_alone(tmp_path):
    spl.save_part(a_part(), str(tmp_path / ('a' + spl.SUFFIX)))
    (tmp_path / 'notes.txt').write_text('hello')
    assert len(spl.list_parts(str(tmp_path))) == 1


# ── placing it ───────────────────────────────────────────────────────────

def test_placing_puts_a_node_where_it_was_asked_for():
    part = a_part()
    model = spl.as_model(part, at=(10.0, 5.0, 2.0))
    assert model['nodes'][spl.anchor_of(part)] == \
        pytest.approx((10.0, 5.0, 2.0))


def test_a_part_written_before_there_was_an_anchor_still_places():
    """Then the geometry was stored against the bounding-box corner, and
    a plain offset is what that file meant."""
    part = dict(a_part())
    part.pop('anchor')
    assert spl.anchor_of(part) is None
    model = spl.as_model(part, at=(10.0, 0.0, 0.0))
    assert min(p[0] for p in model['nodes']) == pytest.approx(10.0)


def test_placing_brings_the_sections_with_it():
    merged, _rep = smg.merge_models(empty(), spl.as_model(a_part()))
    assert sorted(merged['profiles']) == ['CHS 76', 'IPE 200']
    assert [m['profile'] for m in merged['members']] == \
        ['IPE 200', 'IPE 200', 'CHS 76']
    assert merged['members'][2]['conn'] == 'rigid'


def test_two_placements_of_one_file_are_one_component():
    """What makes a library worth having rather than a way of duplicating
    geometry: sized together, marked once."""
    part = a_part()
    model, _r = smg.merge_models(empty(), spl.as_model(part, at=(0, 0, 0)))
    model, _r = smg.merge_models(model, spl.as_model(part, at=(20, 0, 0)))
    assert len(model['members']) == 6
    assert len(model['groups']) == 2
    assert {scp.name_of(g) for g in model['groups']} == {'Mini truss'}
    assert scp.copies(model['groups'], model['groups'][0]['id']) == 2


def test_the_second_placement_is_renamed_but_still_the_same_part():
    """Two groups cannot share a name, but the component is what ties
    them -- not the name."""
    part = a_part()
    model, _r = smg.merge_models(empty(), spl.as_model(part))
    model, _r = smg.merge_models(model, spl.as_model(part, at=(20, 0, 0)))
    names = [g['name'] for g in model['groups']]
    assert names[0] != names[1]
    assert scp.name_of(model['groups'][0]) == scp.name_of(model['groups'][1])


def test_a_part_placed_touching_the_structure_is_bolted_to_it():
    """A container bounds ownership and never connection: two rod ends at
    one point become one node, or the model has a hinge nobody drew."""
    nodes, members = truss()
    base = dict(empty(), nodes=list(nodes), members=[dict(m) for m in members])
    merged, rep = smg.merge_models(base, spl.as_model(a_part(), at=(0, 0, 0)))
    assert rep['nodes_merged'] == 3, 'every node landed on an existing one'
    assert len(merged['nodes']) == 3


def test_a_part_placed_clear_of_the_structure_stays_separate():
    nodes, members = truss()
    base = dict(empty(), nodes=list(nodes), members=[dict(m) for m in members])
    merged, rep = smg.merge_models(base, spl.as_model(a_part(), at=(50, 0, 0)))
    assert rep['nodes_merged'] == 0
    assert len(merged['nodes']) == 6


def test_the_rods_of_a_placement_all_belong_to_its_group():
    merged, _rep = smg.merge_models(empty(), spl.as_model(a_part()))
    assert merged['groups'][0]['members'] == {0, 1, 2}
