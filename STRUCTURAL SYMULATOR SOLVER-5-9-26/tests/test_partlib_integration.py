"""Saving a part from the app and placing it back.

The engine is covered by tests/test_partlib.py. This is the wiring, and
the two things it has to get right: the steel and the component travel
with the geometry, and a part placed touching the structure is bolted to
it rather than left floating beside it.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import tkinter as tk

from apps.stereo import stereo_components as scp
from apps.stereo import stereo_groups as sgp
from apps.stereo import stereo_partlib as spl


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    seen = []
    for kind in ('showinfo', 'showerror', 'showwarning'):
        monkeypatch.setattr('apps.stereo.stereo_app.messagebox.%s' % kind,
                            lambda *a, _k=kind, **kw: seen.append((_k,) + a))
        monkeypatch.setattr('apps.stereo.stereo_app_partlib.messagebox.%s'
                            % kind,
                            lambda *a, _k=kind, **kw: seen.append((_k,) + a))
    monkeypatch.setattr('apps.stereo.stereo_app_partlib.messagebox.askyesno',
                        lambda *a, **kw: True)
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


@pytest.fixture
def saved(app, tmp_path, monkeypatch):
    """A group of the model, written out as a part file."""
    sgp.new_group(app.groups, 'Bay', members=range(0, 12))
    gid = app.groups[-1]['id']
    app._refresh_group_list()
    path = str(tmp_path / ('bay' + spl.SUFFIX))
    monkeypatch.setattr('apps.stereo.stereo_app_partlib.filedialog'
                        '.asksaveasfilename', lambda **kw: path)
    app._set_current_group(gid, say=False)
    assert app._part_save() == path
    return path


def place(app, monkeypatch, path, at=None):
    monkeypatch.setattr('apps.stereo.stereo_app_partlib.filedialog'
                        '.askopenfilename', lambda **kw: path)
    return app._part_place(at=at)


# ── saving ───────────────────────────────────────────────────────────────

def test_a_group_can_be_saved_as_a_part(saved):
    part = spl.load_part(saved)
    assert part['name'] == 'Bay'
    assert part['n_rods'] == 12
    assert part['length_m'] > 0


def test_the_steel_goes_with_it(saved):
    """A truss that arrives without its sections is a sketch."""
    part = spl.load_part(saved)
    assert all('A' in m for m in part['members'])
    assert any(m.get('role') for m in part['members'])


def test_a_group_with_no_rods_is_refused(app, dialogs):
    sgp.new_group(app.groups, 'Empty', members=[])
    app._refresh_group_list()
    app._set_current_group(app.groups[-1]['id'], say=False)
    assert app._part_save() is None
    assert any('no rods' in str(d) for d in dialogs)


def test_nothing_picked_is_refused(app, dialogs):
    app._group_row_clear()
    assert app._part_save() is None
    assert any('Pick a group' in str(d) for d in dialogs)


def test_a_subtree_is_saved_whole(app, tmp_path, monkeypatch):
    """A part is what gets fabricated, and a group's subgroups are part
    of it -- unlike a component, which is a group's own rods."""
    sgp.new_group(app.groups, 'Roof', members=range(0, 6))
    top = app.groups[-1]['id']
    sgp.new_group(app.groups, 'Bay', parent=top, members=range(6, 12))
    app._refresh_group_list()
    path = str(tmp_path / ('roof' + spl.SUFFIX))
    monkeypatch.setattr('apps.stereo.stereo_app_partlib.filedialog'
                        '.asksaveasfilename', lambda **kw: path)
    app._set_current_group(top, say=False)
    app._part_save()
    assert spl.load_part(path)['n_rods'] == 12


# ── placing ──────────────────────────────────────────────────────────────

def test_placing_adds_the_rods(app, monkeypatch, saved):
    before = len(app.members)
    assert place(app, monkeypatch, saved, at=(500.0, 0.0, 0.0)) is not None
    assert len(app.members) == before + 12


def test_placing_is_undoable(app, monkeypatch, saved):
    before = len(app.members)
    place(app, monkeypatch, saved, at=(500.0, 0.0, 0.0))
    assert len(app.members) > before
    app._undo()
    assert len(app.members) == before


def test_a_placed_part_lands_where_it_was_asked_for(app, monkeypatch, saved):
    place(app, monkeypatch, saved, at=(500.0, 60.0, 7.0))
    fresh = sorted(app.selected_members)
    pts = {app.nodes[n] for m in (app.members[i] for i in fresh)
           for n in (m['a'], m['b'])}
    assert (500.0, 60.0, 7.0) in pts, 'a joint of the part is on the point'


def test_the_placed_rods_are_selected(app, monkeypatch, saved):
    before = len(app.members)
    place(app, monkeypatch, saved, at=(500.0, 0.0, 0.0))
    assert app.selected_members == set(range(before, len(app.members)))


def test_a_placed_part_arrives_as_a_group(app, monkeypatch, saved):
    place(app, monkeypatch, saved, at=(500.0, 0.0, 0.0))
    added = [g for g in app.groups if scp.name_of(g) == 'Bay']
    assert len(added) == 1
    assert len(added[0]['members']) == 12


def test_two_placements_of_one_file_are_one_component(app, monkeypatch,
                                                       saved):
    """What makes a library worth having: the two are sized together and
    marked once, without anyone saying so afterwards."""
    place(app, monkeypatch, saved, at=(500.0, 0.0, 0.0))
    place(app, monkeypatch, saved, at=(600.0, 0.0, 0.0))
    copies = [g for g in app.groups if scp.name_of(g) == 'Bay']
    assert len(copies) == 2
    assert app._component_copies(copies[0]['id']) == 2
    # and the sizing really does reach both
    own = app._group_rods(copies[0]['id'])
    assert len(app._sizing_rods(copies[0]['id'], own)) == 2 * len(own)


def test_a_part_placed_on_the_structure_is_bolted_to_it(app, monkeypatch,
                                                         saved):
    """A container bounds ownership and never connection: rod ends that
    meet become one joint, or the model has a hinge nobody drew.

    Landed on the model's far corner, so the part reaches into empty
    space and exactly the corner it was placed on is shared.
    """
    part = spl.load_part(saved)
    corner = max(range(len(app.nodes)), key=lambda i: app.nodes[i][0])
    before_nodes = len(app.nodes)
    before_rods = len(app.members)
    place(app, monkeypatch, saved, at=tuple(app.nodes[corner]))
    assert len(app.members) == before_rods + part['n_rods'], 'the rods are new'
    # At least the joint it was placed on is shared. How many MORE line up
    # depends on the grid it landed against, which is not what this is
    # about -- the claim is that it is attached, not floating.
    assert len(app.nodes) < before_nodes + len(part['nodes'])


def test_a_part_placed_exactly_where_it_came_from_adds_nothing(
        app, monkeypatch, saved):
    """Not a special case -- the merge recognises a rod it already has,
    and the alternative is a second rod hidden inside the first, which
    doubles a stiffness and nothing on screen shows it."""
    before_rods = len(app.members)
    before_nodes = len(app.nodes)
    place(app, monkeypatch, saved, at=tuple(app.nodes[0]))
    assert len(app.members) == before_rods
    assert len(app.nodes) == before_nodes


def test_a_part_placed_clear_of_the_structure_stays_separate(app, monkeypatch,
                                                              saved):
    before = len(app.nodes)
    place(app, monkeypatch, saved, at=(900.0, 900.0, 900.0))
    assert len(app.nodes) > before


def test_the_landing_point_is_the_one_selected_node(app, monkeypatch, saved):
    app.selected_nodes = {5}
    assert app._part_landing() == tuple(app.nodes[5])


def test_a_lassoed_dozen_nodes_is_not_a_place_to_put_it(app):
    """One selected node is a deliberate "put it here"; a dozen is not."""
    app.selected_nodes = {1, 2, 3}
    assert app._part_landing() == (0.0, 0.0, 0.0)
    app.selected_nodes = set()
    assert app._part_landing() == (0.0, 0.0, 0.0)


def test_a_part_file_that_is_wrong_leaves_the_model_alone(app, monkeypatch,
                                                           tmp_path, dialogs):
    path = str(tmp_path / ('bad' + spl.SUFFIX))
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('{"format": "SOMETHING ELSE"}')
    before = len(app.members)
    assert place(app, monkeypatch, path) is None
    assert len(app.members) == before
    assert any('this version reads' in str(d) for d in dialogs)


def test_declining_the_question_places_nothing(app, monkeypatch, saved):
    monkeypatch.setattr('apps.stereo.stereo_app_partlib.messagebox.askyesno',
                        lambda *a, **kw: False)
    before = len(app.members)
    assert place(app, monkeypatch, saved, at=(500.0, 0.0, 0.0)) is None
    assert len(app.members) == before


def test_what_is_about_to_happen_is_said_first(app, monkeypatch, saved):
    asked = []
    monkeypatch.setattr('apps.stereo.stereo_app_partlib.messagebox.askyesno',
                        lambda title, text, **kw: asked.append(text) or True)
    place(app, monkeypatch, saved, at=(500.0, 60.0, 7.0))
    said = asked[0]
    assert 'corner joint lands at (500.00, 60.00, 7.00)' in said
    assert '12 rod(s)' in said
    assert 'bolted to it' in said


def test_the_seam_is_reported_after(app, monkeypatch, saved, dialogs):
    place(app, monkeypatch, saved, at=tuple(app.nodes[0]))
    assert any('coincident' in str(d) or 'Merged' in str(d) for d in dialogs)


# ── the whole way round ──────────────────────────────────────────────────

def test_a_part_saved_from_one_model_places_into_an_empty_one(app, saved,
                                                               monkeypatch):
    """The point of a library: the next project, not the same one."""
    app._clear_model()
    assert not app.members
    place(app, monkeypatch, saved, at=(0.0, 0.0, 0.0))
    assert len(app.members) == 12
    assert [scp.name_of(g) for g in app.groups] == ['Bay']
    assert all(m.get('A') for m in app.members)
