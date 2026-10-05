"""Copy and paste (stereo_clipboard)."""

from apps.stereo import stereo_clipboard as scb


def _bar():
    """Two bars in a line, 0-1-2 along x, with a support, a point load, a
    rod load, a roof area and a group."""
    nodes = [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (6.0, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1, 'A': 10.0, 'profile': 'P1', 'addon': 'C1'},
               {'a': 1, 'b': 2, 'A': 20.0}]
    model = {'nodes': nodes, 'members': members,
             'loads': [{'node': 1, 'fz': -5.0}],
             'supports': [{'node': 0, 'type': 'pin'}],
             'groups': [{'id': 1, 'name': 'Bars', 'parent': None,
                         'members': {0, 1}}],
             'profiles': {'P1': {'A': 10.0}, 'P9': {'A': 1.0}},
             'member_loads': [{'member': 1, 'w': 2.0}],
             'load_nodes': {1: 4.5}}
    return model


def _clip(model, sel_nodes=(), sel_members=()):
    return scb.make_clip(model['nodes'], model['members'], sel_nodes,
                         sel_members, model['supports'], model['loads'],
                         model['load_nodes'], model['member_loads'],
                         model['groups'], model['profiles'])


def test_a_clip_holds_the_rods_their_nodes_and_what_hangs_on_them():
    m = _bar()
    c = _clip(m, sel_members=[0, 1])
    assert len(c['nodes']) == 3 and len(c['members']) == 2
    assert c['members'][0]['A'] == 10.0 and c['members'][0]['profile'] == 'P1'
    assert c['supports'] == [{'node': 0, 'type': 'pin'}]
    assert c['loads'] == [{'node': 1, 'fz': -5.0}]
    assert c['member_loads'] == [{'member': 1, 'w': 2.0}]
    assert c['load_areas'] == {'1': 4.5}
    assert c['groups'] == [{'id': 1, 'name': 'Bars', 'rods': [0, 1]}]
    assert c['profiles'] == {'P1': {'A': 10.0}}        # only what is used
    assert scb.ref_point(c) == (0.0, 0.0, 0.0)


def test_selected_nodes_bring_the_rods_between_them():
    m = _bar()
    c = _clip(m, sel_nodes=[1, 2])
    assert len(c['members']) == 1 and c['members'][0]['A'] == 20.0
    assert scb.make_clip(m['nodes'], m['members']) is None


def test_the_clipboard_text_round_trips_and_rejects_anything_else():
    c = _clip(_bar(), sel_members=[0, 1])
    assert scb.from_text(scb.to_text(c)) == scb.from_text(scb.to_text(c))
    back = scb.from_text(scb.to_text(c))
    assert back['nodes'] == c['nodes'] and back['members'] == c['members']
    assert scb.from_text('hello') is None
    assert scb.from_text(scb.MAGIC + '\n{not json') is None


def test_a_paste_alongside_joins_at_the_shared_node():
    m = _bar()
    c = _clip(m, sel_members=[0, 1])
    new, rep, rods, nodes = scb.paste(m, c, [(6.0, 0.0, 0.0)])
    # node 2 (x=6) is the copy's node 0: one joint, not two
    assert rep['nodes_merged'] == 1 and len(new['nodes']) == 5
    assert rods == [2, 3] and nodes == [3, 4]
    assert new['members'][2]['A'] == 10.0
    # nothing asked for comes along
    assert new['supports'] == m['supports'] and new['loads'] == m['loads']
    assert new['member_loads'] == m['member_loads']
    # the copied column is a column of its own
    assert new['members'][2]['addon'] == 'C2'


def test_a_paste_on_top_adds_nothing():
    m = _bar()
    c = _clip(m, sel_members=[0, 1])
    new, rep, rods, nodes = scb.paste(m, c, [(0.0, 0.0, 0.0)])
    assert rods == [] and nodes == [] and rep['members_duplicate'] == 2


def test_supports_loads_and_groups_come_along_when_asked():
    m = _bar()
    c = _clip(m, sel_members=[0, 1])
    new, rep, rods, nodes = scb.paste(m, c, [(0.0, 5.0, 0.0)],
                                      carry_supports=True, carry_loads=True,
                                      carry_groups=True)
    assert {'node': 3, 'type': 'pin'} in new['supports']
    assert {'node': 4, 'fz': -5.0} in new['loads']
    assert {'member': 3, 'w': 2.0} in new['member_loads']
    assert new['load_nodes'][4] == 4.5
    assert new['groups'][0]['members'] == {0, 1, 2, 3}


def test_an_array_pastes_count_copies_step_by_step():
    m = _bar()
    c = _clip(m, sel_members=[0])
    offs = scb.array_offsets((0.0, 3.0, 0.0), 3)
    assert offs == [(0.0, 3.0, 0.0), (0.0, 6.0, 0.0), (0.0, 9.0, 0.0)]
    new, rep, rods, nodes = scb.paste(m, c, offs)
    assert rep['copies'] == 3 and len(rods) == 3
    assert [new['members'][j]['addon'] for j in rods] == ['C2', 'C3', 'C4']
    ys = sorted({new['nodes'][n][1] for n in nodes})
    assert ys == [3.0, 6.0, 9.0]
