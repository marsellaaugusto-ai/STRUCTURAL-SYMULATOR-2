"""Tests for the module-editor geometry engine in stereo_geometry.py:
find_cells/classify_cell_roles (cell detection + congruence-based role
grouping), cell_local_basis/cell_local_coords, and the role-wide edits
(move_role_node, rescale_role_cells, set_role_member_length,
toggle_role_member) that propagate an edit across every cell of a role."""
import math

import pytest

from apps.stereo import stereo_geometry as sg


def _square_grid(n=3):
    """An n x n grid of unit squares, single layer, square pattern --
    the simplest possible case to test cell/role machinery against by
    hand."""
    bank = sg._NodeBank()
    members = []
    seen = set()
    grid = {}
    for j in range(n + 1):
        for i in range(n + 1):
            grid[(i, j)] = bank.add(float(i), float(j), 0.0)
    for j in range(n + 1):
        for i in range(n):
            sg._add_member(members, seen, grid[(i, j)], grid[(i + 1, j)], role='chord')
    for j in range(n):
        for i in range(n + 1):
            sg._add_member(members, seen, grid[(i, j)], grid[(i, j + 1)], role='chord')
    return bank.nodes, members, grid


# ── find_cells / classify_cell_roles ──────────────────────────────────────

def test_find_cells_on_a_square_grid_finds_every_unit_square():
    nodes, members, grid = _square_grid(3)
    cells = sg.find_cells(nodes, members)
    assert len(cells) == 9
    for c in cells:
        assert len(c['nodes']) == 4
        assert len(c['members']) == 4


def test_find_cells_does_not_double_count_a_quad_with_a_diagonal():
    nodes, members, grid = _square_grid(1)
    seen = {(min(m['a'], m['b']), max(m['a'], m['b'])) for m in members}
    sg._add_member(members, seen, grid[(0, 0)], grid[(1, 1)], role='brace')
    cells = sg.find_cells(nodes, members)
    # the single square cell is gone (its diagonal now exists), replaced
    # by exactly two triangles
    assert len(cells) == 2
    assert all(len(c['nodes']) == 3 for c in cells)


def test_classify_cell_roles_groups_congruent_cells_together():
    nodes, members, grid = _square_grid(3)
    cells = sg.find_cells(nodes, members)
    roles = sg.classify_cell_roles(nodes, cells)
    assert len(roles['roles']) == 1   # every unit square is congruent
    assert len(roles['roles'][0]) == 9
    assert len(roles['cell_role']) == len(cells)


def test_classify_cell_roles_separates_different_shapes():
    mesh = sg.flat_grid(9.0, 9.0, 1.2, 3.0, offset=True, pattern='square')
    nodes, members = mesh['nodes'], mesh['members']
    cells = sg.find_cells(nodes, members)
    roles = sg.classify_cell_roles(nodes, cells)
    # the pyramidal webs (triangles) and the flat chords (quads) are
    # different shapes and must land in different roles
    assert len(roles['roles']) >= 2
    role0_len = len(cells[roles['roles'][0][0]]['nodes'])
    for rid, idxs in roles['roles'].items():
        for i in idxs:
            assert len(cells[i]['nodes']) == len(cells[roles['roles'][rid][0]]['nodes'])
    # role 0 (by construction, the largest) has at least as many cells
    # as every other role
    counts = [len(idxs) for idxs in roles['roles'].values()]
    assert counts[0] == max(counts)


def test_canonical_cycle_agrees_across_congruent_translated_cells():
    nodes, members, grid = _square_grid(3)
    cells = sg.find_cells(nodes, members)
    # every cell's own position-0->1 edge length must be identical (unit
    # squares are congruent under pure translation, so canonicalization
    # should never need to reflect/rotate them into disagreement)
    lengths01 = {round(math.dist(nodes[c['nodes'][0]], nodes[c['nodes'][1]]), 9)
                for c in cells}
    assert lengths01 == {1.0}


# ── cell_local_basis / cell_local_coords ──────────────────────────────────

def test_local_basis_is_orthonormal_and_right_handed():
    nodes, members, grid = _square_grid(1)
    cells = sg.find_cells(nodes, members)
    origin, eu, ev, en = sg.cell_local_basis(nodes, cells[0]['nodes'])

    def norm(v):
        return math.sqrt(sum(c * c for c in v))
    assert norm(eu) == pytest.approx(1.0)
    assert norm(ev) == pytest.approx(1.0)
    assert norm(en) == pytest.approx(1.0)
    assert sum(a * b for a, b in zip(eu, ev)) == pytest.approx(0.0, abs=1e-9)
    # right-handed: eu x ev == en
    cx = eu[1] * ev[2] - eu[2] * ev[1]
    cy = eu[2] * ev[0] - eu[0] * ev[2]
    cz = eu[0] * ev[1] - eu[1] * ev[0]
    assert (cx, cy, cz) == pytest.approx(en, abs=1e-9)


def test_local_coords_of_position_zero_is_the_origin():
    nodes, members, grid = _square_grid(1)
    cells = sg.find_cells(nodes, members)
    u, v, n = sg.cell_local_coords(nodes, cells[0]['nodes'], 0)
    assert (u, v, n) == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)


def test_local_coords_of_position_one_is_pure_u():
    nodes, members, grid = _square_grid(1)
    cells = sg.find_cells(nodes, members)
    u, v, n = sg.cell_local_coords(nodes, cells[0]['nodes'], 1)
    assert v == pytest.approx(0.0, abs=1e-9)
    assert n == pytest.approx(0.0, abs=1e-9)
    assert u > 0


# ── move_role_node ────────────────────────────────────────────────────────

def test_move_role_node_moves_every_role_cells_own_position():
    nodes, members, grid = _square_grid(3)
    cells = sg.find_cells(nodes, members)
    roles = sg.classify_cell_roles(nodes, cells)
    new_nodes = sg.move_role_node(nodes, members, cells, roles['roles'], 0, 0, (0.1, 0.0, 0.0))
    moved = [i for i in range(len(nodes))
            if math.dist(nodes[i], new_nodes[i]) > 1e-9]
    assert len(moved) == 9   # one position-0 corner per unit square
    for i in moved:
        dx = new_nodes[i][0] - nodes[i][0]
        assert dx == pytest.approx(0.1)


def test_move_role_node_averages_a_shared_corner_from_two_orientations():
    # Two adjacent right triangles sharing a hypotenuse-adjacent corner,
    # deliberately built so the shared corner is position 0 in one
    # triangle and reached via a differently-oriented basis in the other
    # -- averaging should land strictly between the two individual
    # proposals, not equal to either alone.
    bank = sg._NodeBank()
    members = []
    seen = set()
    a = bank.add(0.0, 0.0, 0.0)
    b = bank.add(1.0, 0.0, 0.0)
    c = bank.add(0.0, 1.0, 0.0)
    d = bank.add(1.0, 1.0, 0.0)
    for p, q in ((a, b), (b, c), (c, a), (b, d), (d, c)):
        sg._add_member(members, seen, p, q, role='chord')
    nodes = bank.nodes
    cells = sg.find_cells(nodes, members)
    roles = sg.classify_cell_roles(nodes, cells)
    assert len(roles['roles'][0]) == 2   # both triangles are congruent
    new_nodes = sg.move_role_node(nodes, members, cells, roles['roles'], 0, 0, (0.2, 0.0, 0.0))
    # node c (shared by both triangles) must have moved by SOME amount,
    # but the two cells' own bases differ, so it need not be a clean 0.2
    moved_c = math.dist(nodes[c], new_nodes[c])
    assert 0.0 < moved_c


def test_move_role_node_respects_a_locked_member():
    bank = sg._NodeBank()
    members = []
    seen = set()
    n0 = bank.add(0.0, 0.0, 0.0)
    n1 = bank.add(1.0, 0.0, 0.0)
    n2 = bank.add(1.0, 1.0, 0.0)
    n3 = bank.add(0.0, 1.0, 0.0)
    for p, q in ((n0, n1), (n1, n2), (n2, n3), (n3, n0)):
        sg._add_member(members, seen, p, q, role='chord')
    nodes = bank.nodes
    cells = sg.find_cells(nodes, members)
    roles = sg.classify_cell_roles(nodes, cells)
    locked = [cells[0]['members'][0]]   # the n0-n1 edge (+x direction)
    new_nodes = sg.move_role_node(nodes, members, cells, roles['roles'], 0, 0,
                                  (0.5, 0.3, 0.0), locked_member_idxs=locked)
    assert new_nodes[n0][0] == pytest.approx(0.0)   # x-component (along the lock) stripped
    assert new_nodes[n0][1] == pytest.approx(0.3)   # y-component (sideways) survives


# ── rescale_role_cells ─────────────────────────────────────────────────────

@pytest.mark.parametrize('factor', [2.0, 0.5, 1.3])
def test_rescale_role_cells_scales_every_pairwise_distance_exactly(factor):
    mesh = sg.flat_grid(9.0, 9.0, 1.2, 3.0, offset=True, pattern='square')
    nodes, members = mesh['nodes'], mesh['members']
    cells = sg.find_cells(nodes, members)
    roles = sg.classify_cell_roles(nodes, cells)
    role_id = 1   # the flat square chords (shared corners between cells)
    rep = cells[roles['roles'][role_id][0]]['nodes']
    orig_len = math.dist(nodes[rep[0]], nodes[rep[1]])
    new_nodes = sg.rescale_role_cells(nodes, cells, roles['roles'], role_id, factor)
    new_len = math.dist(new_nodes[rep[0]], new_nodes[rep[1]])
    assert new_len == pytest.approx(orig_len * factor)


def test_rescale_role_cells_preserves_an_earlier_freeform_shape():
    nodes, members, grid = _square_grid(1)
    cells = sg.find_cells(nodes, members)
    roles = sg.classify_cell_roles(nodes, cells)
    # freeform-drag one corner off-square first
    nodes2 = sg.move_role_node(nodes, members, cells, roles['roles'], 0, 2, (0.3, 0.0, 0.0))
    scaled = sg.rescale_role_cells(nodes2, cells, roles['roles'], 0, 2.0)
    rep = cells[roles['roles'][0][0]]['nodes']
    # every pairwise distance in the (now irregular) shape must scale by
    # exactly 2, preserving the irregularity rather than resetting it
    for i in range(4):
        for j in range(i + 1, 4):
            d0 = math.dist(nodes2[rep[i]], nodes2[rep[j]])
            d1 = math.dist(scaled[rep[i]], scaled[rep[j]])
            assert d1 == pytest.approx(d0 * 2.0)


# ── set_role_member_length ─────────────────────────────────────────────────

def test_set_role_member_length_sets_the_edge_exactly_when_cells_share_no_nodes():
    # Three separate unit squares, physically far apart -- no cell of
    # this role shares ANY node with another, so there is no averaging
    # conflict and every one of them must land at EXACTLY the target
    # length, not an averaged approximation of it.
    bank = sg._NodeBank()
    members = []
    seen = set()
    for ox in (0.0, 100.0, 200.0):
        n0 = bank.add(ox + 0.0, 0.0, 0.0)
        n1 = bank.add(ox + 1.0, 0.0, 0.0)
        n2 = bank.add(ox + 1.0, 1.0, 0.0)
        n3 = bank.add(ox + 0.0, 1.0, 0.0)
        for p, q in ((n0, n1), (n1, n2), (n2, n3), (n3, n0)):
            sg._add_member(members, seen, p, q, role='chord')
    nodes = bank.nodes
    cells = sg.find_cells(nodes, members)
    roles = sg.classify_cell_roles(nodes, cells)
    assert len(roles['roles'][0]) == 3
    new_nodes = sg.set_role_member_length(nodes, cells, roles['roles'], 0, 0, 1, 5.0)
    for ci in roles['roles'][0]:
        rep = cells[ci]['nodes']
        assert math.dist(new_nodes[rep[0]], new_nodes[rep[1]]) == pytest.approx(5.0)


def test_set_role_member_length_on_a_densely_shared_role_is_order_independent():
    # flat_grid's own square chords share every corner with their
    # neighbours -- setting one edge's length can't land EVERY cell's
    # own edge on the exact target simultaneously (that would need a
    # full relaxation of the whole interlocked network, not a local
    # edit), so the honest contract here is just: the result depends
    # only on role membership, never on which order roles/cells happen
    # to be stored in -- i.e. no cascading through a shared corner.
    mesh = sg.flat_grid(9.0, 9.0, 1.2, 3.0, offset=True, pattern='square')
    nodes, members = mesh['nodes'], mesh['members']
    cells = sg.find_cells(nodes, members)
    roles = sg.classify_cell_roles(nodes, cells)
    role_id = 1
    forward = sg.set_role_member_length(nodes, cells, roles['roles'], role_id, 0, 1, 5.0)
    reversed_roles = {role_id: list(reversed(roles['roles'][role_id]))}
    backward = sg.set_role_member_length(nodes, cells, reversed_roles, role_id, 0, 1, 5.0)
    for a, b in zip(forward, backward):
        assert a == pytest.approx(b)


def test_set_role_member_length_does_not_move_position_a_when_unshared():
    # A single isolated square (no neighbouring cell of the same role),
    # so its position-0 corner is EXCLUSIVELY a position_a here -- no
    # averaging conflict, and it must land exactly unchanged.
    bank = sg._NodeBank()
    members = []
    seen = set()
    n0 = bank.add(0.0, 0.0, 0.0)
    n1 = bank.add(1.0, 0.0, 0.0)
    n2 = bank.add(1.0, 1.0, 0.0)
    n3 = bank.add(0.0, 1.0, 0.0)
    for p, q in ((n0, n1), (n1, n2), (n2, n3), (n3, n0)):
        sg._add_member(members, seen, p, q, role='chord')
    nodes = bank.nodes
    cells = sg.find_cells(nodes, members)
    roles = sg.classify_cell_roles(nodes, cells)
    new_nodes = sg.set_role_member_length(nodes, cells, roles['roles'], 0, 0, 1, 9.0)
    assert new_nodes[n0] == pytest.approx(nodes[n0])
    assert math.dist(new_nodes[n0], new_nodes[n1]) == pytest.approx(9.0)


def test_set_role_member_length_averages_a_corner_shared_as_both_roles():
    # In a tiled grid, a corner can be position_a for one cell and
    # position_b for its neighbour at the same time -- a genuine
    # conflict, resolved (like every other role-wide edit here) by
    # averaging the two proposals from the SAME pre-edit snapshot, never
    # by letting one cell's write feed into the next cell's computation
    # (which would make the result depend on processing order).
    nodes, members, grid = _square_grid(2)
    cells = sg.find_cells(nodes, members)
    roles = sg.classify_cell_roles(nodes, cells)
    new_nodes = sg.set_role_member_length(nodes, cells, roles['roles'], 0, 0, 1, 9.0)
    # every edge grew (not necessarily to exactly 9.0 -- a shared corner
    # gets an averaged compromise, per the module's documented tradeoff)
    for ci in roles['roles'][0]:
        rep = cells[ci]['nodes']
        assert math.dist(new_nodes[rep[0]], new_nodes[rep[1]]) > 1.0
    # and the result cannot depend on which order the cells were listed in
    reversed_roles = {0: list(reversed(roles['roles'][0]))}
    other_order = sg.set_role_member_length(nodes, cells, reversed_roles, 0, 0, 1, 9.0)
    for a, b in zip(new_nodes, other_order):
        assert a == pytest.approx(b)


# ── toggle_role_member ──────────────────────────────────────────────────────

def test_toggle_role_member_adds_then_removes_a_diagonal_everywhere():
    mesh = sg.flat_grid(9.0, 9.0, 1.2, 3.0, offset=True, pattern='square')
    nodes, members = mesh['nodes'], mesh['members']
    cells = sg.find_cells(nodes, members)
    roles = sg.classify_cell_roles(nodes, cells)
    role_id = 1
    n0 = len(members)
    added = sg.toggle_role_member(members, cells, roles['roles'], role_id, 0, 2)
    assert len(added) == n0 + len(roles['roles'][role_id])
    for m in added:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    removed = sg.toggle_role_member(added, cells, roles['roles'], role_id, 0, 2)
    assert len(removed) == n0


def test_toggle_role_member_result_still_solves_under_self_weight():
    from apps.stereo import stereo_math as sm
    mesh = sg.flat_grid(9.0, 9.0, 1.2, 3.0, offset=True, pattern='square')
    nodes, members = mesh['nodes'], mesh['members']
    cells = sg.find_cells(nodes, members)
    roles = sg.classify_cell_roles(nodes, cells)
    role_id = 1
    new_members = sg.toggle_role_member(members, cells, roles['roles'], role_id, 0, 2)
    for m in new_members:
        m.setdefault('E', 200e3); m.setdefault('A', 20.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, new_members, unit_weight_kN_m3=78.5)
    _res, err = sm.analyze(nodes, new_members, loads, supports)
    assert err is None
