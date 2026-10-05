"""Which part of a model a crane lifts (stereo_lift)."""

from apps.stereo import stereo_lift as sl


def _two_bars_and_a_crane():
    # piece A: 0-1-2, piece B: 3-4, a crane cable from 2 to the hook 5,
    # which also reaches 3 -- the crane must not join A and B into one
    return [{'a': 0, 'b': 1}, {'a': 1, 'b': 2}, {'a': 3, 'b': 4},
            {'a': 2, 'b': 5, 'role': 'crane_cable'},
            {'a': 3, 'b': 5, 'role': 'crane_cable'},
            {'a': 5, 'b': 6, 'role': 'crane_mast'}]


def test_the_piece_under_the_hook_is_what_the_picks_connect_to():
    m = _two_bars_and_a_crane()
    assert sl.connected_piece(m, [0]) == [0, 1]
    assert sl.connected_piece(m, [4]) == [2]
    assert sl.connected_piece(m, [0, 4]) == [0, 1, 2]
    assert sl.connected_piece(m, [99]) == []


def test_pieces_lists_each_separate_truss_once():
    assert sl.pieces(_two_bars_and_a_crane()) == [[0, 1], [2]]


def test_joined_to_rest_names_where_a_piece_is_still_attached():
    m = _two_bars_and_a_crane()
    assert sl.joined_to_rest(m, [0, 1]) == []
    assert sl.joined_to_rest(m, [0]) == [1]      # bar 1 still holds node 1
    assert sl.nodes_of(m, [0, 1]) == {0, 1, 2}


def test_rope_working_load_from_its_diameter():
    # 20 mm: 0.65 * 400 = 260 kN breaking, a fifth of it to lift with
    assert sl.rope_wll_kN(20) == 52.0
    assert sl.rope_wll_kN(0) == 0.0


def _a_two_sling_lift():
    # a bar 0-1 hanging from hook 2 by slings 0-2 and 1-2, mast 2-3
    nodes = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (2.0, 0.0, 2.0),
             (2.0, 0.0, 3.0)]
    members = [{'a': 0, 'b': 1},
               {'a': 0, 'b': 2, 'role': 'crane_cable', 'addon': 'K1'},
               {'a': 1, 'b': 2, 'role': 'crane_cable', 'addon': 'K1'},
               {'a': 2, 'b': 3, 'role': 'crane_mast', 'addon': 'K1'}]
    import math
    T = 10.0 / math.sqrt(2.0)          # 10 kN hung at 45 degrees, shared
    results = {'member_res': [{'N': -5.0}, {'N': T}, {'N': T},
                              {'N': -10.0}],
               'reactions': {3: {'Fz': 10.0}}}
    checks = [{'checked': True, 'util': 1.3}, {}, {}, {}]
    return nodes, members, results, checks, T


def test_the_crane_report_reads_the_slings_hook_and_mast():
    nodes, members, results, checks, T = _a_two_sling_lift()
    assert sl.crane_codes(members) == ['K1']
    cables, masts, hook, anchor = sl.crane_parts(members, 'K1')
    assert (cables, masts, hook, anchor) == ([1, 2], [3], 2, 3)
    r = sl.crane_report(nodes, members, results, checks, 'K1', wll_kN=6.0)
    assert [c['pick'] for c in r['cables']] == [0, 1]
    for c in r['cables']:
        assert abs(c['angle'] - 45.0) < 1e-9
        assert abs(c['length'] - 2.0 * 2 ** 0.5) < 1e-9
        assert abs(c['T'] - T) < 1e-9
    assert abs(r['sum_vertical'] - 10.0) < 1e-9     # the whole load
    assert r['mast_N'] == -10.0
    assert r['anchor_reaction'] == {'Fz': 10.0}
    assert r['lifted_rods'] == [0]
    assert r['over'] == [(1.3, 0)] and r['worst'] == (1.3, 0)
    assert r['flat'] == []                         # 45 is not below 45
    assert len(r['cable_over']) == 2               # 7.07 kN on a 6 kN rope


def test_a_flat_sling_is_flagged():
    nodes, members, results, checks, _T = _a_two_sling_lift()
    nodes[2] = (2.0, 0.0, 1.0)                     # 26.6 degrees
    r = sl.crane_report(nodes, members, results, checks, 'K1')
    assert len(r['flat']) == 2
    assert r['cable_over'] == [] and r['cables'][0]['util'] is None


# ── the hook over the centre of gravity ───────────────────────────────────

def _square():
    # a 4 x 2 m rectangle of bars at z = 0
    nodes = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 2.0, 0.0),
             (0.0, 2.0, 0.0), (9.0, 9.0, 0.0)]
    members = [{'a': 0, 'b': 1}, {'a': 1, 'b': 2}, {'a': 2, 'b': 3},
               {'a': 3, 'b': 0}]
    return nodes, members


def test_centre_of_gravity_weighs_the_downward_loads_on_the_piece():
    nodes, members = _square()
    loads = [{'node': 1, 'fz': -30.0}, {'node': 0, 'fz': -10.0},
             {'node': 4, 'fz': -500.0},      # not on the piece
             {'node': 2, 'fz': +99.0}]       # pulls up: not weight
    cx, cy = sl.centre_of_gravity(nodes, members, range(4), loads)
    assert abs(cx - 3.0) < 1e-12 and abs(cy) < 1e-12


def test_centre_of_gravity_falls_back_to_the_rods_own_lengths():
    nodes, members = _square()
    # unloaded: the rods' midpoints weighted by length -- a uniform piece
    cx, cy = sl.centre_of_gravity(nodes, members, range(4), [])
    assert abs(cx - 2.0) < 1e-12 and abs(cy - 1.0) < 1e-12
    # only the bottom bar and the right one: (4*2 + 2*4) / 6, (0 + 2*1) / 6
    cx, cy = sl.centre_of_gravity(nodes, members, [0, 1], [])
    assert abs(cx - 16.0 / 6) < 1e-12 and abs(cy - 2.0 / 6) < 1e-12
    assert sl.centre_of_gravity(nodes, members, [], []) is None


def test_cog_outside_picks_measures_how_far_out_it_is():
    nodes, _m = _square()
    picks = [0, 1, 2, 3]
    assert sl.cog_outside_picks(nodes, picks, (2.0, 1.0)) == 0.0
    assert sl.cog_outside_picks(nodes, picks, (4.0, 1.0)) == 0.0   # on edge
    assert abs(sl.cog_outside_picks(nodes, picks, (2.0, -0.5)) - 0.5) < 1e-12
    assert abs(sl.cog_outside_picks(nodes, picks, (7.0, 6.0)) - 5.0) < 1e-12
    # three picks: the triangle 0-1-2 does not hold (1, 1.5)
    assert sl.cog_outside_picks(nodes, [0, 1, 2], (1.0, 1.5)) > 0.4
    # picks in a line hold only what is on that line
    assert sl.cog_outside_picks(nodes, [0, 1], (2.0, 0.0)) == 0.0
    assert abs(sl.cog_outside_picks(nodes, [0, 1], (2.0, 1.0)) - 1.0) < 1e-12


def test_the_crane_hangs_its_hook_over_the_point_it_is_given():
    from apps.stereo import stereo_geometry as sg
    nodes, members = _square()
    sec = {'E': 200.0, 'A': 5.0, 'I': 10.0, 'J': 10.0, 'Fy': 250.0}
    n2, m2, hook, anchor = sg.add_cable_crane(nodes, members, [0, 1, 2, 3],
                                              sec, rise=3.0, mast=1.0,
                                              hook_xy=(3.0, 0.5))
    assert n2[hook] == (3.0, 0.5, 3.0)
    assert n2[anchor] == (3.0, 0.5, 4.0)
    # without it, over the picks' centroid as before
    n2, _m, hook, _a = sg.add_cable_crane(nodes, members, [0, 1, 2, 3], sec,
                                          rise=3.0, mast=1.0)
    assert n2[hook] == (2.0, 1.0, 3.0)
    # the automatic rise measures the spread from the hook's point
    assert sg.crane_auto_rise(nodes, [0, 1, 2, 3], (0.0, 0.0)) > \
        sg.crane_auto_rise(nodes, [0, 1, 2, 3])
