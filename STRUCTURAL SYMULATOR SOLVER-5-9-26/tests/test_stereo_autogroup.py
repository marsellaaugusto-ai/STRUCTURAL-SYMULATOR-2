"""Grouping a model by its pieces: trusses, modules and roofs, and in every
truss its top strip, bottom strip and diagonals."""
import math

import pytest

from apps.stereo import stereo_autogroup as ag
from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_groups as sgp


def _wedge(nodes, members, origin, along, up, n=6, length=12.0, depth=3.0):
    """A wedge truss in the plane (along, up) from `origin`: top and bottom
    strips meeting at a point at the start, an end post at the deep end,
    and a zig-zag of diagonals. Returns (top_rods, bottom_rods, web_rods,
    tip, top_nodes, bottom_nodes)."""
    def at(s, h):
        return tuple(origin[k] + s * along[k] + h * up[k] for k in range(3))

    def node(p):
        for i, q in enumerate(nodes):
            if math.dist(p, q) < 1e-9:
                return i
        nodes.append(p)
        return len(nodes) - 1

    def rod(a, b):
        members.append({'a': a, 'b': b, 'conn': 'pin', 'E': 200.0, 'A': 10.0,
                        'I': 100.0, 'J': 100.0})
        return len(members) - 1
    tip = node(at(0.0, 0.0))
    tops = [tip] + [node(at(length * k / n, depth / 2 * k / n))
                    for k in range(1, n + 1)]
    bots = [tip] + [node(at(length * k / n, -depth / 2 * k / n))
                    for k in range(1, n + 1)]
    top = [rod(p, q) for p, q in zip(tops, tops[1:])]
    bot = [rod(p, q) for p, q in zip(bots, bots[1:])]
    web = [rod(tops[k], bots[k + 1]) for k in range(1, n)]
    web += [rod(tops[k], bots[k]) for k in range(1, n + 1)]
    return top, bot, web, tip, tops, bots


def test_a_wedge_trusss_strips_meet_at_its_tip():
    nodes, members = [], []
    top, bot, web, *_ = _wedge(nodes, members, (0, 0, 0), (1, 0, 0),
                               (0, 0, 1))
    parts = ag.truss_parts(nodes, members, list(range(len(members))))
    assert parts['top'] == sorted(top)
    assert parts['bottom'] == sorted(bot)
    # the end post closes the outline but is not a strip
    assert parts['diagonals'] == sorted(web)


def test_a_truss_tilted_in_space_reads_the_same():
    nodes, members = [], []
    s = 1 / math.sqrt(2)
    top, bot, web, *_ = _wedge(nodes, members, (5, 3, 1), (s, s, 0),
                               (-0.3 * s, 0.3 * s, 0.954))
    parts = ag.truss_parts(nodes, members, list(range(len(members))))
    assert parts['top'] == sorted(top) and parts['bottom'] == sorted(bot)


def test_a_double_layer_grid_reads_as_its_own_roles():
    for mesh in (sg.flat_grid(30, 30, 1.5, 3.0, offset=True,
                              pattern='square'),
                 sg.flat_grid(16, 16, 1.2, 2.0, offset=False,
                              pattern='diagonal')):
        n, m = mesh['nodes'], mesh['members']
        assert not ag.is_truss_assembly(n, m, list(range(len(m))))
        parts = ag.grid_parts(n, m, list(range(len(m))))
        want = {'top': 'top_chord', 'bottom': 'bottom_chord',
                'diagonals': 'web'}
        for key, rods in parts.items():
            assert {m[j]['role'] for j in rods} == {want[key]}


def _on_strip(nodes, members, strip, offset):
    """A planar truss built on an existing strip (tip first): its other
    strip is the first moved by `offset`, growing from nothing at the tip.
    The two trusses then SHARE that strip, as the roof file's do."""
    n = len(strip) - 1
    new = [strip[0]]
    for k in range(1, n + 1):
        p = nodes[strip[k]]
        nodes.append(tuple(p[c] + offset[c] * k / n for c in range(3)))
        new.append(len(nodes) - 1)

    def rod(a, b):
        members.append({'a': a, 'b': b, 'conn': 'pin', 'E': 200.0, 'A': 10.0,
                        'I': 100.0, 'J': 100.0})
    for a, b in zip(new, new[1:]):
        rod(a, b)
    for k in range(1, n):
        rod(strip[k], new[k + 1])
    for k in range(1, n + 1):
        rod(strip[k], new[k])
    return new


def _module(nodes, members, y0):
    """Four planar trusses, neighbours sharing a strip: a wedge, a truss on
    its top strip, one on its bottom strip, and one on the second's."""
    _t, _b, _w, _tip, tops, bots = _wedge(nodes, members, (0, y0, 0),
                                          (1, 0, 0), (0, 0, 1), n=4,
                                          length=8.0)
    b_new = _on_strip(nodes, members, tops, (0.0, 2.0, 2.0))
    _on_strip(nodes, members, bots, (0.0, 2.0, -2.0))
    _on_strip(nodes, members, b_new, (0.0, 2.0, -1.0))


def test_a_module_of_trusses_comes_apart_into_its_trusses():
    nodes, members = [], []
    _module(nodes, members, 0.0)
    rods = list(range(len(members)))
    assert ag.is_truss_assembly(nodes, members, rods)
    trusses, shared, loose = ag.planar_trusses(nodes, members, rods)
    assert len(trusses) == 4 and not loose


def test_every_rod_lands_in_exactly_one_group():
    nodes, members = [], []
    _wedge(nodes, members, (0, -20, 0), (1, 0, 0), (0, 0, 1))
    _module(nodes, members, 0.0)
    groups = ag.auto_groups(nodes, members)
    seen = [j for g in groups for j in g['members']]
    assert sorted(seen) == list(range(len(members)))
    names = [g['name'] for g in groups if g['parent'] is None]
    # the only grid in the file is, by itself, the roof
    assert names == ['Truss 1', 'Roof 1']
    roof = next(g for g in groups if g['name'] == 'Roof 1')
    trusses = sgp.children(groups, roof['id'])
    assert [g['name'] for g in trusses] == ['R1 Truss %d' % k
                                            for k in range(1, 5)]
    leaves = [g['name'] for g in groups
              if g['parent'] in {t['id'] for t in trusses}]
    assert any(name.endswith('diagonals') for name in leaves)
    assert any('(shared with' in name for name in leaves)


def test_a_roof_of_modules_is_read_by_its_module():
    nodes, members = [], []
    _module(nodes, members, 100.0)                       # the module alone
    first = len(nodes)
    for y in (0.0, 14.0, 28.0):                          # a roof of three
        _module(nodes, members, y)
    tips = [n for n in range(first, len(nodes))
            if nodes[n][0] == 0.0 and nodes[n][2] == 0.0]
    for a, b in zip(tips, tips[1:]):                     # tied at the tips
        members.append({'a': a, 'b': b, 'conn': 'pin', 'E': 200.0,
                        'A': 10.0, 'I': 100.0, 'J': 100.0})
    pieces = ag.classify(nodes, members)
    assert [p['kind'] for p in pieces] == ['module', 'roof']
    roof = pieces[1]
    assert len(roof['trusses']) == 12
    assert [len(m) for m in roof['modules']] == [4, 4, 4]
    groups = ag.auto_groups(nodes, members)
    names = [g['name'] for g in groups]
    assert 'R1 Module 3' in names and 'R1 M3 Truss 4' in names
    assert sorted(j for g in groups for j in g['members']) == \
        list(range(len(members)))
