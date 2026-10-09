"""Components where the app meets them: the menu, the list, and -- the one
that matters -- the place a section is chosen.

A component is fabricated once, so its section has to carry the worst of
its copies. Sizing it from the copy on screen leaves every copy looking
right and the heaviest one under-strength, with nothing to see. Most of
this file is about that path being impossible to take by accident.
"""
import math
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import tkinter as tk

from apps.stereo import stereo_components as scp
from apps.stereo import stereo_groups as sgp


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    seen = []
    for kind in ('showinfo', 'showerror', 'showwarning'):
        monkeypatch.setattr('apps.stereo.stereo_app.messagebox.%s' % kind,
                            lambda *a, _k=kind, **kw: seen.append((_k,) + a))
    return seen


@pytest.fixture(scope='module')
def tk_root():
    last = None
    for attempt in range(6):
        try:
            root = tk.Tk()
            break
        except tk.TclError as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    else:
        pytest.skip('no Tk display after 6 attempts: %s' % last)
    root.geometry('1400x900')
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def app(tk_root):
    from apps.stereo.stereo_app import StereoApp
    tab = tk.Frame(tk_root)
    a = StereoApp(tab)
    a._generate(push_undo=False)
    tab.pack(fill='both', expand=True)
    tk_root.update_idletasks()
    tk_root.update()
    yield a
    tab.destroy()


CHIRAL = [(0, 0, 0), (4, 0, 0), (1.7, 3.1, 0), (1.3, 0.9, 2.8),
          (3.4, 2.2, 4.1)]
BARS = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3), (3, 4), (1, 4)]


def three_trusses(app):
    nodes, members, groups = [], [], []
    for k in range(3):
        at = len(nodes)
        for p in CHIRAL:
            nodes.append((p[0] + 30 * k, p[1], p[2]))
        first = len(members)
        for a, b in BARS:
            members.append({'a': a + at, 'b': b + at, 'profile': 'IPE 200',
                            'A': 28.5, 'I': 1940.0, 'J': 400.0, 'conn': 'pin',
                            'E': 200.0, 'Fy': 235.0, 'Fu': 360.0, 'K': 1.0,
                            'r_gyr': 4.0})
        groups.append({'id': k + 1, 'name': 'Truss %s' % 'ABC'[k],
                       'parent': None,
                       'members': set(range(first, len(members)))})
    app.nodes, app.members, app.groups = nodes, members, groups
    app.loads, app.supports = [], []
    app.results = None
    app.member_checks = None
    app._refresh_group_list()
    return groups


# ── making one from the object under the pointer ─────────────────────────

def test_make_component_offers_the_groups_that_match(app, monkeypatch):
    three_trusses(app)
    asked = []
    monkeypatch.setattr('apps.stereo.stereo_app_components.messagebox'
                        '.askyesno',
                        lambda title, text, **kw: asked.append(text) or True)
    monkeypatch.setattr('apps.stereo.stereo_app_components.simpledialog'
                        '.askstring', lambda *a, **kw: 'Gable truss')
    name = app._menu_make_component(1)
    assert name == 'Gable truss'
    assert '2 other group(s)' in asked[0]
    assert 'Truss B' in asked[0] and 'Truss C' in asked[0]
    assert app._component_copies(1) == 3


def test_answering_no_makes_a_part_of_one(app, monkeypatch):
    three_trusses(app)
    monkeypatch.setattr('apps.stereo.stereo_app_components.messagebox'
                        '.askyesno', lambda *a, **kw: False)
    monkeypatch.setattr('apps.stereo.stereo_app_components.simpledialog'
                        '.askstring', lambda *a, **kw: 'Just this one')
    app._menu_make_component(1)
    assert app._component_copies(1) == 1
    assert app._component_of(2) is None


def test_cancelling_the_name_changes_nothing(app, monkeypatch):
    three_trusses(app)
    monkeypatch.setattr('apps.stereo.stereo_app_components.messagebox'
                        '.askyesno', lambda *a, **kw: True)
    monkeypatch.setattr('apps.stereo.stereo_app_components.simpledialog'
                        '.askstring', lambda *a, **kw: None)
    assert app._menu_make_component(1) is None
    assert app._component_of(1) is None


def test_make_unique_detaches_one_and_leaves_its_rods(app):
    three_trusses(app)
    scp.make_component(app.groups, [1, 2, 3], 'T')
    before = set(app.groups[1]['members'])
    app._menu_make_unique(2)
    assert app._component_of(2) is None
    assert app._component_copies(1) == 2
    assert app.groups[1]['members'] == before


def test_make_unique_on_a_plain_group_says_so(app, dialogs):
    three_trusses(app)
    assert app._menu_make_unique(1) is None
    assert any('not a copy' in str(d) for d in dialogs)


def test_both_verbs_are_undoable(app):
    three_trusses(app)
    scp.make_component(app.groups, [1, 2, 3], 'T')
    app._menu_make_unique(2)
    assert app._component_of(2) is None
    app._undo()
    assert app._component_of(2) == 'T'


# ── the menu offers whichever verb is left to do ─────────────────────────

def _labels(menu):
    out = []
    for i in range(menu.index('end') + 1):
        try:
            out.append(menu.entrycget(i, 'label'))
        except tk.TclError:
            out.append('---')
    return out


def test_a_plain_group_is_offered_make_component(app, monkeypatch):
    three_trusses(app)
    monkeypatch.setattr(app, '_select_member_at', lambda *a, **kw: 0)
    monkeypatch.setattr(app, '_group_object_for_rod', lambda r: 1)
    labels = _labels(app._object_menu_at(10, 10))
    assert any('Make component' in s for s in labels)
    assert not any('Make unique' in s for s in labels)


def test_a_copy_is_offered_make_unique_and_the_component_itself(app,
                                                                monkeypatch):
    three_trusses(app)
    scp.make_component(app.groups, [1, 2, 3], 'Gable truss')
    monkeypatch.setattr(app, '_select_member_at', lambda *a, **kw: 0)
    monkeypatch.setattr(app, '_group_object_for_rod', lambda r: 1)
    labels = _labels(app._object_menu_at(10, 10))
    assert any('Make unique' in s for s in labels)
    assert any('Gable truss (3 copies)' in s for s in labels)
    assert not any('Make component' in s for s in labels)


def test_the_list_shows_which_part_a_group_is_a_copy_of(app):
    three_trusses(app)
    scp.make_component(app.groups, [1, 2, 3], 'Gable truss')
    labels = [label for label, _gid in app._group_rows()]
    assert sum('Gable truss ×3' in s for s in labels) == 3


def test_a_declared_component_replaces_the_piece_mark_on_the_list(app):
    """Both say "three copies of one part". The component is the stronger
    claim -- someone declared it -- and the mark is what helps you find the
    copies before you do."""
    three_trusses(app)
    app.marks_on.set(True)
    before = [label for label, _gid in app._group_rows()]
    assert all('T1' in s for s in before)
    scp.make_component(app.groups, [1, 2, 3], 'Gable truss')
    after = [label for label, _gid in app._group_rows()]
    assert all('Gable truss' in s for s in after)
    assert not any('T1' in s for s in after)


def test_making_one_copy_unique_brings_its_mark_back(app):
    three_trusses(app)
    app.marks_on.set(True)
    scp.make_component(app.groups, [1, 2, 3], 'Gable truss')
    app._menu_make_unique(2)
    rows = dict((gid, label) for label, gid in app._group_rows())
    assert 'Gable truss ×2' in rows[1]
    assert 'Gable truss' not in rows[2]
    assert 'T1' in rows[2], 'it is still the same shape as the others'


# ── sizing: the part of this that matters ────────────────────────────────

def test_sizing_rods_reach_every_copy(app):
    three_trusses(app)
    scp.make_component(app.groups, [1, 2, 3], 'T')
    own = app._group_rods(1)
    reach = app._sizing_rods(1)
    assert len(reach) == 3 * len(own)
    assert set(own) <= set(reach)


def test_sizing_rods_of_a_plain_group_are_just_its_own(app):
    """Callers use it unconditionally, so it has to be right for a group
    that is not a component."""
    three_trusses(app)
    assert sorted(app._sizing_rods(1)) == sorted(app._group_rods(1))


def test_applying_a_section_to_one_copy_sets_it_on_all_of_them(app):
    three_trusses(app)
    scp.make_component(app.groups, [1, 2, 3], 'T')
    app._set_current_group(1, say=False)
    app.group_profile.set('IPE 300')
    app._group_apply_profile()
    for g in app.groups:
        for i in g['members']:
            assert app.members[i]['profile'] == 'IPE 300'


def test_applying_a_section_to_a_plain_group_leaves_the_others_alone(app):
    three_trusses(app)
    app._set_current_group(1, say=False)
    app.group_profile.set('IPE 300')
    app._group_apply_profile()
    assert all(app.members[i]['profile'] == 'IPE 300'
               for i in app.groups[0]['members'])
    assert all(app.members[i]['profile'] == 'IPE 200'
               for i in app.groups[1]['members'])


def test_the_note_says_the_part_is_sized_over_every_copy(app):
    three_trusses(app)
    scp.make_component(app.groups, [1, 2, 3], 'T')
    note = app._component_sizing_note(1)
    assert 'built 3 times' in note
    assert 'worst copy' in note
    assert '%d rods' % (3 * len(BARS)) in note


def test_a_plain_group_gets_no_sizing_note(app):
    three_trusses(app)
    assert app._component_sizing_note(1) == ''


def test_a_component_whose_copies_diverged_sizes_one_and_says_so(app):
    """Never silently: a component that no longer lines up is sized as the
    one group it can be sized as, and the note says to check it."""
    three_trusses(app)
    scp.make_component(app.groups, [1, 2, 3], 'T')
    node = app.members[sorted(app.groups[0]['members'])[0]]['b']
    x, y, z = app.nodes[node]
    app.nodes[node] = (x, y, z + 0.9)
    note = app._component_sizing_note(1)
    assert 'no longer match' in note
    assert sorted(app._sizing_rods(1)) == sorted(app._group_rods(1))


def test_the_recommendation_is_sized_over_every_copy(app, monkeypatch):
    """The whole point. recommend_for_group must be handed the rods of all
    three trusses, not the one that was clicked."""
    three_trusses(app)
    scp.make_component(app.groups, [1, 2, 3], 'T')
    app.results = {'member_res': [{'N': 0.0} for _ in app.members]}
    seen = {}

    def fake(nodes, members, res, rods, **kw):
        seen['rods'] = list(rods)
        return None

    monkeypatch.setattr('apps.stereo.stereo_app_groups.sk.recommend_for_group',
                        fake)
    app._set_current_group(1, say=False)
    app._group_recommend()
    assert len(seen['rods']) == 3 * len(BARS)


# ── the envelope window ──────────────────────────────────────────────────

def test_the_component_window_names_the_rod_that_decides_each_section(app):
    three_trusses(app)
    scp.make_component(app.groups, [1, 2, 3], 'T')
    rows = scp.correspondence(app.nodes, app.members, app.groups, 'T')
    app.member_checks = [{'util': 0.2, 'checked': True}
                         for _ in app.members]
    app.member_checks[rows[0][2]]['util'] = 1.25
    lines = app._component_report('T')
    text = '\n'.join(lines)
    assert 'COPIES' in text and 'Truss A' in text
    assert '1.250' in text
    assert 'Widest spread' in text
    assert str(rows[0][2]) in text


def test_the_window_opens_and_is_read_only(app):
    three_trusses(app)
    scp.make_component(app.groups, [1, 2, 3], 'T')
    win = app._component_dialog('T')
    app.root.update_idletasks()
    txt = win.children[[k for k in win.children if 'text' in k][0]]
    assert txt.cget('state') == 'disabled'
    win.destroy()


def test_the_window_calls_out_a_copy_that_no_longer_matches(app):
    three_trusses(app)
    scp.make_component(app.groups, [1, 2, 3], 'T')
    node = app.members[sorted(app.groups[2]['members'])[0]]['b']
    x, y, z = app.nodes[node]
    app.nodes[node] = (x, y, z + 0.9)
    text = '\n'.join(app._component_report('T'))
    assert 'NO LONGER MATCHES' in text
    assert 'Truss C' in text


def test_the_envelope_reads_before_anything_is_analysed(app):
    three_trusses(app)
    scp.make_component(app.groups, [1, 2], 'T')
    app.member_checks = None
    text = '\n'.join(app._component_report('T'))
    assert 'RODS OF THE PART' in text
    assert '--' in text


# ── the workbook ─────────────────────────────────────────────────────────

def test_the_component_survives_a_round_trip_through_excel(app, tmp_path,
                                                            monkeypatch):
    from common import _ensure_openpyxl
    if not _ensure_openpyxl():
        pytest.skip('openpyxl unavailable')
    three_trusses(app)
    scp.make_component(app.groups, [1, 2, 3], 'Gable truss')
    path = str(tmp_path / 'c.xlsx')
    monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                        lambda **kw: path)
    app._export_excel()
    monkeypatch.setattr('apps.stereo.stereo_app.filedialog.askopenfilename',
                        lambda **kw: path)
    app._import_excel()
    assert {scp.name_of(g) for g in app.groups} == {'Gable truss'}
    assert app._component_copies(app.groups[0]['id']) == 3


# ── a component that came from SketchUp ──────────────────────────────────

def _from_sketchup(scenario, tmp_path):
    """Run the plugin's own export against the stub SketchUp and return
    the workbook it wrote. See tests/test_sketchup_export_groups.py."""
    import json
    import shutil
    import subprocess
    ruby = shutil.which('ruby')
    if ruby is None:
        pytest.skip('no ruby to run the plugin sources with')
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = str(tmp_path / ('%s.xlsx' % scenario))
    proc = subprocess.run(
        [ruby, '-I', os.path.join(root, 'tests', 'ruby', 'stub'),
         os.path.join(root, 'tests', 'ruby', 'export_harness.rb'),
         'select', scenario, out],
        cwd=root, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    json.loads(proc.stdout.strip().splitlines()[-1])
    return out


def test_a_sketchup_component_arrives_usable(app, tmp_path, monkeypatch):
    """The whole chain: three instances of one definition in SketchUp, out
    through the plugin, in through Import from Excel, and a component the
    Stereo tab can size as one part."""
    from common import _ensure_openpyxl
    if not _ensure_openpyxl():
        pytest.skip('openpyxl unavailable')
    path = _from_sketchup('three_copies', tmp_path)
    monkeypatch.setattr('apps.stereo.stereo_app.filedialog.askopenfilename',
                        lambda **kw: path)
    app._import_excel()

    assert len(app.groups) == 3
    assert {scp.name_of(g) for g in app.groups} == {'Truss A'}
    first = app.groups[0]['id']
    assert app._component_copies(first) == 3

    # And it behaves like one: a section set on one copy reaches all three.
    app._set_current_group(first, say=False)
    app.group_profile.set('IPE 300')
    app._group_apply_profile()
    assert all(app.members[i]['profile'] == 'IPE 300'
               for g in app.groups for i in g['members'])


def test_sketchup_copies_are_lined_up_rod_for_rod(app, tmp_path, monkeypatch):
    """Sizing over copies needs the correspondence, and the copies came in
    as three separate sets of rods -- it has to be worked out from their
    geometry, not from anything the workbook said."""
    from common import _ensure_openpyxl
    if not _ensure_openpyxl():
        pytest.skip('openpyxl unavailable')
    path = _from_sketchup('three_copies', tmp_path)
    monkeypatch.setattr('apps.stereo.stereo_app.filedialog.askopenfilename',
                        lambda **kw: path)
    app._import_excel()
    rows = scp.correspondence(app.nodes, app.members, app.groups, 'Truss A')
    assert len(rows) == 3, 'three bars to the truss'
    assert all(len(r) == 3 for r in rows), 'three copies of each'
    owners = sgp.owner_of_rod(app.groups)
    for row in rows:
        assert len({owners[i] for i in row}) == 3, 'one from each copy'


def test_a_scaled_sketchup_instance_is_not_sized_with_the_others(app,
                                                                  tmp_path,
                                                                  monkeypatch):
    """Same drawing on screen, different steel. If these came in as one
    part the small one would be sized from the big one's loads."""
    from common import _ensure_openpyxl
    if not _ensure_openpyxl():
        pytest.skip('openpyxl unavailable')
    path = _from_sketchup('scaled_copies', tmp_path)
    monkeypatch.setattr('apps.stereo.stereo_app.filedialog.askopenfilename',
                        lambda **kw: path)
    app._import_excel()
    names = {scp.name_of(g) for g in app.groups}
    assert len(names) == 2
    for g in app.groups:
        assert app._component_copies(g['id']) == 1
        assert sorted(app._sizing_rods(g['id'])) == sorted(
            app._group_rods(g['id'])), 'sizing stays inside its own copy'
