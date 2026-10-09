"""The way back: a Stereo model into SketchUp, with its organisation.

tests/test_sketchup_export_groups.py covers SketchUp -> Stereo. This is
the other direction, and it closes the loop: the groups someone made
arrive as groups the Outliner shows, the parts built more than once arrive
as one component placed many times, and every container is named after the
piece mark it carries.

The hard part, and most of what is checked here, is PLACING a copy. The
workbook says two groups are one part; it does not say what motion carries
one onto the other, because the Stereo tab has no use for such a thing.
model_groups_in recovers it from the shape and then verifies it -- and
where verification fails, builds that copy on its own rather than placing
an instance somewhere wrong.
"""
import json
import math
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from common import _ensure_openpyxl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(ROOT, 'tests', 'ruby', 'import_harness.rb')
STUB = os.path.join(ROOT, 'tests', 'ruby', 'stub')
RUBY = shutil.which('ruby')
M_TO_IN = 39.3700787402

pytestmark = [
    pytest.mark.skipif(not _ensure_openpyxl(), reason='openpyxl unavailable'),
    pytest.mark.skipif(RUBY is None,
                       reason='no ruby to run the plugin sources with'),
]

# A truss with no symmetry, so a frame built from it is unambiguous, and
# chiral, so a mirrored copy is genuinely a different placement.
CHIRAL = [(0, 0, 0), (4, 0, 0), (1.7, 3.1, 0), (1.3, 0.9, 2.8),
          (3.4, 2.2, 4.1)]
BARS = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3), (3, 4), (1, 4)]


def spin(degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def place(pts, matrix=None, offset=(0, 0, 0), mirror=False):
    out = []
    for p in pts:
        q = (p[0], p[1], -p[2]) if mirror else p
        if matrix:
            q = tuple(sum(matrix[i][j] * q[j] for j in range(3))
                      for i in range(3))
        out.append(tuple(q[i] + offset[i] for i in range(3)))
    return out


def bar(a, b):
    return {'a': a, 'b': b, 'profile': 'IPE 200', 'A': 28.5, 'I': 1940.0,
            'J': 400.0, 'conn': 'pin', 'E': 200.0, 'Fy': 235.0, 'Fu': 360.0,
            'K': 1.0, 'r_gyr': 4.0}


def build(copies, component=None, extras=None, meta=None, marks=1.0,
          with_groups=True):
    """(nodes, members, groups) for N placements of the truss.

    `copies` is a list of (matrix, offset, mirror). `component` names the
    group ids that are declared one part.
    """
    nodes, members, groups = [], [], []
    for k, (matrix, offset, mirror) in enumerate(copies):
        at = len(nodes)
        nodes.extend(place(CHIRAL, matrix, offset, mirror))
        first = len(members)
        for a, b in BARS:
            members.append(bar(a + at, b + at))
        groups.append({'id': k + 1, 'name': 'Truss %s' % 'ABCDE'[k],
                       'parent': None,
                       'members': set(range(first, len(members)))})
    for how in (extras or ()):
        how(nodes, members, groups)
    if component:
        from apps.stereo import stereo_components as scp
        scp.make_component(groups, component[1], component[0])
    return nodes, members, (groups if with_groups else None)


def written(tmp_path, nodes, members, groups, meta=None, marks=1.0,
            name='m.xlsx'):
    from apps.stereo import stereo_reports as sr
    path = str(tmp_path / name)
    sr.export_excel(nodes, members, [], [], None, path, groups=groups,
                    meta=meta, mark_tol_mm=marks)
    return path


def imported(path):
    proc = subprocess.run([RUBY, '-I', STUB, HARNESS, path],
                          cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def names(tree, kind=None):
    return [t['name'] for t in tree if kind is None or t['kind'] == kind]


# ── the groups themselves ────────────────────────────────────────────────

def test_groups_arrive_as_groups(tmp_path):
    nodes, members, groups = build([(None, (0, 0, 0), False),
                                    (None, (30, 0, 0), False)])
    out = imported(written(tmp_path, nodes, members, groups))
    assert sorted(names(out['tree'], 'group')) == ['Truss A [T1]',
                                                   'Truss B [T1]']
    assert all(t['edges'] == len(BARS) for t in out['tree'])


def test_nesting_survives_the_trip_back(tmp_path):
    def add_child(nodes, members, groups):
        at = len(nodes)
        nodes.extend([(90, 0, 0), (94, 0, 0)])
        members.append(bar(at, at + 1))
        groups.append({'id': 9, 'name': 'Bay', 'parent': 1,
                       'members': {len(members) - 1}})

    nodes, members, groups = build([(None, (0, 0, 0), False)],
                                   extras=[add_child])
    out = imported(written(tmp_path, nodes, members, groups))
    by_depth = {t['depth']: t for t in out['tree']}
    assert by_depth[0]['name'].startswith('Truss A')
    assert by_depth[1]['name'].startswith('Bay')
    assert by_depth[1]['edges'] == 1


def test_rods_in_no_group_stay_loose(tmp_path):
    """They are the Stereo tab's Ungrouped set, which is not a container
    and must not become one."""
    def add_loose(nodes, members, groups):
        at = len(nodes)
        nodes.extend([(0, -20, 0), (4, -20, 0)])
        members.append(bar(at, at + 1))

    nodes, members, groups = build([(None, (0, 0, 0), False)],
                                   extras=[add_loose])
    out = imported(written(tmp_path, nodes, members, groups))
    assert out['loose_edges'] == 1
    assert len(out['tree']) == 1


def test_every_rod_is_built_exactly_once(tmp_path):
    def add_loose(nodes, members, groups):
        at = len(nodes)
        nodes.extend([(0, -20, 0), (4, -20, 0)])
        members.append(bar(at, at + 1))

    nodes, members, groups = build([(None, (0, 0, 0), False),
                                    (None, (30, 0, 0), False)],
                                   extras=[add_loose])
    out = imported(written(tmp_path, nodes, members, groups))
    drawn = out['loose_edges'] + sum(t['edges'] for t in out['tree'])
    assert drawn == len(members)


def test_a_workbook_with_no_groups_imports_flat(tmp_path):
    """Every workbook written before groups existed. The import is the one
    it always was, and says nothing about groups."""
    nodes, members, _g = build([(None, (0, 0, 0), False)])
    path = written(tmp_path, nodes, members, None, marks=None)
    out = imported(path)
    assert out['tree'] == []
    assert out['loose_edges'] == len(members)
    assert 'group(s)' not in out['messages'][-1]


def test_solid_mode_still_groups(tmp_path):
    """A radius in [META] switches the drawing from edges to cylinders.
    The organisation is the same question and must not depend on it."""
    nodes, members, groups = build([(None, (0, 0, 0), False),
                                    (None, (30, 0, 0), False)])
    path = written(tmp_path, nodes, members, groups,
                   meta={'node_radius_m': 0.05, 'rod_radius_m': 0.03})
    out = imported(path)
    assert len(names(out['tree'], 'group')) == 2
    assert 'solid' in out['messages'][-1]


# ── the marks ────────────────────────────────────────────────────────────

def test_the_piece_mark_is_on_the_name(tmp_path):
    """SketchUp has no idea what a piece mark is and does not need one:
    the name is what the Outliner shows and what someone reads."""
    nodes, members, groups = build([(None, (0, 0, 0), False),
                                    (None, (30, 0, 0), False)])
    out = imported(written(tmp_path, nodes, members, groups))
    assert all('[T1]' in n for n in names(out['tree']))


def test_two_different_parts_carry_different_marks(tmp_path):
    def add_other(nodes, members, groups):
        at = len(nodes)
        nodes.extend([(0, -20, 0), (4, -20, 0)])
        members.append(bar(at, at + 1))
        groups.append({'id': 9, 'name': 'Strut', 'parent': None,
                       'members': {len(members) - 1}})

    nodes, members, groups = build([(None, (0, 0, 0), False)],
                                   extras=[add_other])
    out = imported(written(tmp_path, nodes, members, groups))
    marks = {n.split('[')[1] for n in names(out['tree']) if '[' in n}
    assert len(marks) == 2


def test_without_marks_the_names_are_plain(tmp_path):
    """A workbook exported with no piece-mark tolerance has no marks to
    carry, and a name should not grow empty brackets."""
    nodes, members, groups = build([(None, (0, 0, 0), False)])
    out = imported(written(tmp_path, nodes, members, groups, marks=None))
    assert names(out['tree']) == ['Truss A']


# ── components: one definition, placed ───────────────────────────────────

def test_copies_of_one_part_share_one_definition(tmp_path):
    nodes, members, groups = build(
        [(None, (0, 0, 0), False), (None, (30, 0, 0), False)],
        component=('Gable truss', [1, 2]))
    out = imported(written(tmp_path, nodes, members, groups))
    assert out['definitions'] == ['Gable truss']
    inst = [t for t in out['tree'] if t['kind'] == 'instance']
    assert len(inst) == 2
    assert {t['definition'] for t in inst} == {'Gable truss'}
    assert all(t['edges'] == len(BARS) for t in inst)


def _lands_on_the_model(out, nodes):
    want = {tuple(round(c * M_TO_IN, 3) for c in p) for p in nodes}
    seen = 0
    for t in out['tree']:
        if t['kind'] != 'instance':
            continue
        seen += 1
        for p in t['at']:
            assert tuple(p) in want, 'instance placed off the model: %r' % (p,)
    return seen


def test_a_copy_that_was_moved_is_placed_where_it_belongs(tmp_path):
    nodes, members, groups = build(
        [(None, (0, 0, 0), False), (None, (30, 7, -2), False)],
        component=('Gable truss', [1, 2]))
    out = imported(written(tmp_path, nodes, members, groups))
    assert _lands_on_the_model(out, nodes) == 2


def test_a_copy_that_was_turned_is_placed_where_it_belongs(tmp_path):
    """The workbook does not record the motion between two copies -- the
    Stereo tab has no use for one -- so it is recovered from the shape."""
    nodes, members, groups = build(
        [(None, (0, 0, 0), False), (spin(52), (30, 0, 0), False)],
        component=('Gable truss', [1, 2]))
    out = imported(written(tmp_path, nodes, members, groups))
    assert _lands_on_the_model(out, nodes) == 2


def test_a_mirrored_copy_is_placed_where_it_belongs(tmp_path):
    """A left-hand copy is a real thing the Stereo tab already marks, so
    the placement has to be allowed to reflect."""
    nodes, members, groups = build(
        [(None, (0, 0, 0), False), (None, (30, 0, 0), True)],
        component=('Gable truss', [1, 2]))
    out = imported(written(tmp_path, nodes, members, groups))
    assert _lands_on_the_model(out, nodes) == 2


def test_three_copies_all_land(tmp_path):
    nodes, members, groups = build(
        [(None, (0, 0, 0), False), (spin(90), (30, 0, 0), False),
         (None, (60, 0, 0), True)],
        component=('Gable truss', [1, 2, 3]))
    out = imported(written(tmp_path, nodes, members, groups))
    assert _lands_on_the_model(out, nodes) == 3
    assert out['definitions'] == ['Gable truss']


def test_a_group_that_is_not_a_component_stays_a_group(tmp_path):
    nodes, members, groups = build(
        [(None, (0, 0, 0), False), (None, (30, 0, 0), False),
         (None, (60, 0, 0), False)],
        component=('Gable truss', [1, 2]))
    out = imported(written(tmp_path, nodes, members, groups))
    assert len(names(out['tree'], 'instance')) == 2
    assert names(out['tree'], 'group') == ['Truss C [T1]']


def test_a_part_with_one_copy_is_not_made_a_component(tmp_path):
    """A definition with a single instance is noise in the Component
    Browser; the group says the same thing."""
    nodes, members, groups = build([(None, (0, 0, 0), False)],
                                   component=('Lonely', [1]))
    out = imported(written(tmp_path, nodes, members, groups))
    assert out['definitions'] == []
    assert names(out['tree'], 'group') == ['Truss A [T1]']


def test_a_component_group_with_children_is_built_plainly(tmp_path):
    """Every copy shares one definition, and children differ from copy to
    copy -- so such a group cannot be an instance, and is left as what it
    already was rather than silently losing its child."""
    def add_child(nodes, members, groups):
        at = len(nodes)
        nodes.extend([(90, 0, 0), (94, 0, 0)])
        members.append(bar(at, at + 1))
        groups.append({'id': 9, 'name': 'Bay', 'parent': 1,
                       'members': {len(members) - 1}})

    nodes, members, groups = build(
        [(None, (0, 0, 0), False), (None, (30, 0, 0), False)],
        extras=[add_child], component=('Gable truss', [1, 2]))
    out = imported(written(tmp_path, nodes, members, groups))
    assert out['definitions'] == []
    assert 'Bay [T2]' in names(out['tree'])


def test_a_copy_that_does_not_line_up_is_built_on_its_own(tmp_path):
    """The sheet can say two groups are one part when they no longer are
    -- someone edited one. Geometry in the wrong place is worse than
    geometry that is not shared, so that copy becomes a plain group."""
    nodes, members, groups = build(
        [(None, (0, 0, 0), False), (None, (30, 0, 0), False)],
        component=('Gable truss', [1, 2]))
    # Pull one node of the second copy well out of shape.
    moved = sorted(groups[1]['members'])[0]
    node = members[moved]['b']
    x, y, z = nodes[node]
    nodes[node] = (x, y, z + 3.0)
    out = imported(written(tmp_path, nodes, members, groups))
    assert names(out['tree'], 'group') == ['Truss B [T2]']
    assert len(names(out['tree'], 'instance')) == 1


def test_a_copy_that_does_not_line_up_is_named_out_loud(tmp_path):
    """Silently leaving a copy out of its part is a drawing that disagrees
    with the model."""
    nodes, members, groups = build(
        [(None, (0, 0, 0), False), (None, (30, 0, 0), False)],
        component=('Gable truss', [1, 2]))
    moved = sorted(groups[1]['members'])[0]
    node = members[moved]['b']
    x, y, z = nodes[node]
    nodes[node] = (x, y, z + 3.0)
    out = imported(written(tmp_path, nodes, members, groups))
    said = out['messages'][-1]
    assert 'did not line up' in said
    assert 'Truss B' in said


def test_the_summary_counts_what_was_built(tmp_path):
    nodes, members, groups = build(
        [(None, (0, 0, 0), False), (None, (30, 0, 0), False)],
        component=('Gable truss', [1, 2]))
    out = imported(written(tmp_path, nodes, members, groups))
    said = out['messages'][-1]
    assert '2 group(s)' in said
    assert '1 shared component(s)' in said
    assert '2 instance(s)' in said


# ── the two pieces of plumbing worth checking on their own ───────────────

def _ruby(expr):
    """Evaluate an expression against the loaded plugin and return JSON."""
    script = (
        "require 'json'; require 'sketchup.rb'; "
        "require File.join(%r, 'main'); "
        "M = CoordinateCoordinatorTrussAppAMAC; "
        "puts JSON.generate(v: (%s))"
        % (os.path.join(ROOT, 'sketchup_plugin',
                        'coordinate_coordinator_truss_app_amac'), expr)
    )
    proc = subprocess.run([RUBY, '-I', STUB, '-e', script],
                          cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])['v']


@pytest.mark.parametrize('text,expect', [
    ('0-3, 7, 9-10', [0, 1, 2, 3, 7, 9, 10]),
    ('5', [5]),
    ('', []),
    ('  ', []),
    ('3, 1, 2', [1, 2, 3]),
    ('1, 1, 1', [1]),
    ('0-2; 4 5', [0, 1, 2, 4, 5]),
    ('7-3', []),
    ('2.0', [2]),
])
def test_rod_ranges_read_the_way_they_are_written(text, expect):
    """The third reader of this spelling, and the only one in Ruby --
    stereo_groups_excel writes and reads it, model_export writes it."""
    assert _ruby('M.parse_rod_ranges(%r)' % text) == expect


def test_a_child_listed_before_its_parent_is_still_built_after_it():
    """The sheet is written parents-first, but a hand-edited one need not
    be, and a child built first would land in the wrong place."""
    records = ('[{id: 2, parent: 1, name: "child", rods: []}, '
               ' {id: 1, parent: nil, name: "parent", rods: []}]')
    assert _ruby('M.ordered(%s).map { |r| r[:name] }' % records) == \
        ['parent', 'child']


def test_a_parent_that_is_not_there_does_not_hang_the_import():
    records = '[{id: 2, parent: 77, name: "orphan", rods: []}]'
    assert _ruby('M.ordered(%s).map { |r| r[:name] }' % records) == ['orphan']


def test_a_cycle_in_the_parents_does_not_hang_the_import():
    """A hand-edited sheet can say anything. It must not spin."""
    records = ('[{id: 1, parent: 2, name: "a", rods: []}, '
               ' {id: 2, parent: 1, name: "b", rods: []}]')
    assert sorted(_ruby('M.ordered(%s).map { |r| r[:name] }' % records)) == \
        ['a', 'b']
