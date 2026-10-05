"""Short codes for add-ons (stereo_addon_codes): C1, B1, K1, P1."""

from apps.stereo import stereo_addon_codes as sac


def _rods(*codes):
    return [{'a': 0, 'b': 1, 'addon': c} if c else {'a': 0, 'b': 1}
            for c in codes]


def test_codes_parse_and_describe():
    assert sac.parse('C12') == ('C', 12)
    assert sac.parse('X1') is None and sac.parse('C') is None
    assert sac.parse(None) is None
    assert sac.describe('K2') == 'Crane K2'
    assert sac.describe('B1') == 'Beam B1'
    assert sac.kind_of('P3') == sac.PANEL


def test_next_code_is_one_past_the_highest_and_never_reuses_a_gap():
    rods = _rods('C1', 'C3', 'B1', None)
    assert sac.next_code(sac.COLUMN, rods) == 'C4'
    assert sac.next_code(sac.BEAM, rods) == 'B2'
    assert sac.next_code(sac.CRANE, rods) == 'K1'
    assert sac.next_code(sac.PANEL, rods, [{'addon': 'P2'}]) == 'P3'


def test_index_is_in_natural_order():
    rods = _rods('C10', 'C2', 'B1', 'C2')
    assert list(sac.index(rods)) == ['B1', 'C2', 'C10']
    assert sac.index(rods)['C2'] == [1, 3]
    assert sac.codes_of(rods, [0, 1, 3]) == ['C2', 'C10']


def test_a_copy_gets_codes_of_its_own_but_keeps_its_rods_together():
    rods = _rods('C1', 'C1', 'K1', 'C1', 'C1', 'K1', 'B4')
    # rods 3..6 are a copy of rods 0..2 plus a beam nobody else has
    mapping = sac.renumber_copies(rods, [3, 4, 5, 6])
    assert mapping == {'C1': 'C2', 'K1': 'K2'}
    assert [r['addon'] for r in rods] == ['C1', 'C1', 'K1', 'C2', 'C2',
                                          'K2', 'B4']


def test_anchor_is_the_middle_of_the_rods():
    nodes = [(0.0, 0.0, 0.0), (0.0, 0.0, 4.0), (2.0, 0.0, 4.0)]
    members = [{'a': 0, 'b': 1}, {'a': 1, 'b': 2}]
    x, y, z = sac.anchor(nodes, members, [0, 1])
    assert (round(x, 6), y, z) == (0.5, 0.0, 3.0)
    assert sac.anchor(nodes, members, []) is None


def test_a_file_from_before_codes_gets_them_on_opening():
    """Two cranes (cables meeting at their own hooks, a mast each) and a
    column -- none coded -- become K1, K2 and C1; a coded rod keeps its."""
    members = [
        {'a': 0, 'b': 9, 'role': 'crane_cable'},
        {'a': 1, 'b': 9, 'role': 'crane_cable'},
        {'a': 9, 'b': 10, 'role': 'crane_mast'},
        {'a': 3, 'b': 19, 'role': 'crane_cable'},
        {'a': 4, 'b': 19, 'role': 'crane_cable'},
        {'a': 19, 'b': 20, 'role': 'crane_mast'},
        {'a': 5, 'b': 6, 'role': 'column_shaft'},
        {'a': 6, 'b': 7, 'role': 'capital'},
        {'a': 7, 'b': 8, 'role': 'beam_like', 'addon': 'B3'},
        {'a': 0, 'b': 1}]
    assert sac.backfill(members) == ['K1', 'K2', 'C1']
    assert [m.get('addon') for m in members] == [
        'K1', 'K1', 'K1', 'K2', 'K2', 'K2', 'C1', 'C1', 'B3', None]
    assert sac.backfill(members) == []              # already done
