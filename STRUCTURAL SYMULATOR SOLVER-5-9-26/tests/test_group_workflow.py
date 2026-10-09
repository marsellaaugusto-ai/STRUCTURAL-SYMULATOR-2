"""The group workflow: a group is a thing you select, enter, delete and own.

Stage 1 made a group selectable and deletable. Stage 2 (task 1) puts its
verbs under the pointer, lets the context decide what a new rod belongs to,
and retires the controls that asked the user to manage, by checkbox, what
the tab already knew.

The two complaints this answers, in the words they were made in: "I should be
able to delete groups using the delete button", and "I should be able to
select a complete group by selecting a single rod that is inside that group".

Driven through a real StereoApp, because the whole point is what a CLICK and
a KEYPRESS do -- a test that called the methods directly would pass while the
canvas still did nothing.
"""
import time

import pytest

pytest.importorskip('tkinter')
import tkinter as tk                                            # noqa: E402

from apps.stereo import stereo_groups as sgp                    # noqa: E402
from apps.stereo.stereo_app import StereoApp                    # noqa: E402


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    """Popups into a list, and askyesno says yes -- a modal with no mainloop
    behind it does not fail a test, it HANGS."""
    seen = []
    for where in ('apps.stereo.stereo_app_groups.messagebox',
                  'apps.stereo.stereo_app.messagebox'):
        for kind in ('showinfo', 'showerror', 'showwarning'):
            monkeypatch.setattr('%s.%s' % (where, kind),
                                lambda *a, _k=kind, **kw: seen.append((_k,) + a))
        for kind in ('askyesno', 'askokcancel'):
            monkeypatch.setattr('%s.%s' % (where, kind), lambda *a, **kw: True)
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
    tab = tk.Frame(tk_root)
    a = StereoApp(tab)
    # Three separate trusses, each its own group, plus loose rods -- so
    # "the group" is always a strict subset of the model.
    nodes, members, groups = [], [], []
    for k in range(3):
        b = len(nodes)
        y = k * 4.0
        nodes.extend([(0, y, 0), (6, y, 0), (3, y, 2)])
        start = len(members)
        for i, j in ((0, 1), (0, 2), (2, 1)):
            members.append({'a': b + i, 'b': b + j, 'conn': 'pin', 'E': 200.0,
                            'A': 20.0, 'I': 400.0, 'J': 400.0, 'Fy': 235.0,
                            'Fu': 360.0, 'r_gyr': 4.0, 'K': 1.0})
        sgp.new_group(groups, 'Truss %d' % (k + 1),
                      members=range(start, len(members)))
    b = len(nodes)
    nodes.extend([(0, 20, 0), (6, 20, 0)])
    members.append({'a': b, 'b': b + 1, 'conn': 'pin', 'E': 200.0, 'A': 20.0,
                    'I': 400.0, 'J': 400.0, 'Fy': 235.0, 'Fu': 360.0,
                    'r_gyr': 4.0, 'K': 1.0})          # Ungrouped
    a.nodes, a.members, a.groups = nodes, members, groups
    a._refresh_group_list()
    tab.pack(fill='both', expand=True)
    tk_root.update_idletasks()
    tk_root.update()
    yield a
    tab.destroy()


def _rod_of(app, gid):
    return sgp.rods_of(app.groups, gid, deep=True)[0]


# ── selecting a group ──────────────────────────────────────────────────────

def test_one_rod_resolves_to_the_group_that_owns_it(app):
    gid = app.groups[0]['id']
    assert app._group_object_for_rod(_rod_of(app, gid)) == gid


def test_an_ungrouped_rod_resolves_to_itself(app):
    loose = len(app.members) - 1
    assert app._group_object_for_rod(loose) is None


def test_selecting_the_group_selects_every_rod_in_it(app):
    gid = app.groups[0]['id']
    assert app._group_select_object(gid)
    assert app.selected_members == set(sgp.rods_of(app.groups, gid, deep=True))
    assert len(app.selected_members) == 3
    assert not app.selected_nodes


def test_the_selection_reports_itself_as_that_group(app):
    gid = app.groups[1]['id']
    app._group_select_object(gid)
    assert app._selected_group_object() == gid


def test_a_part_of_a_group_is_not_the_group(app):
    """The whole point of deriving it: Delete must not take a group away
    because two of its three rods happened to be selected."""
    gid = app.groups[0]['id']
    rods = sgp.rods_of(app.groups, gid, deep=True)
    app.selected_members = set(rods[:-1])
    app.selected_nodes = set()
    assert app._selected_group_object() is None


def test_rods_of_two_groups_are_not_one_group(app):
    app.selected_members = {_rod_of(app, app.groups[0]['id']),
                            _rod_of(app, app.groups[1]['id'])}
    app.selected_nodes = set()
    assert app._selected_group_object() is None


def test_a_selection_with_nodes_in_it_is_not_a_group(app):
    gid = app.groups[0]['id']
    app._group_select_object(gid)
    app.selected_nodes = {0}
    assert app._selected_group_object() is None, \
        'deleting would then take nodes nobody asked about'


def test_inside_a_group_its_own_rods_are_picked_one_by_one(app):
    """Being inside a group is exactly what makes its own rods the things
    you pick -- otherwise you could never touch a single one."""
    gid = app.groups[0]['id']
    app._group_open(gid)
    assert app._group_object_for_rod(_rod_of(app, gid)) is None
    app._group_step_out()
    assert app._group_object_for_rod(_rod_of(app, gid)) == gid


def test_a_subgroup_inside_the_open_group_is_still_one_object(app):
    """One rule at every depth: inside a group, its SUBgroups are still
    closed objects."""
    parent = app.groups[0]['id']
    sub = sgp.new_group(app.groups, 'Node brace', parent=parent,
                        members=[_rod_of(app, parent)])['id']
    app._group_open(parent)
    rod = sgp.rods_of(app.groups, sub, deep=True)[0]
    assert app._group_object_for_rod(rod) == sub


# ── deleting a group ───────────────────────────────────────────────────────

def test_delete_takes_the_group_and_its_rods(app):
    gid = app.groups[0]['id']
    rods = set(sgp.rods_of(app.groups, gid, deep=True))
    before_rods, before_groups = len(app.members), len(app.groups)
    app._group_select_object(gid)
    app._on_delete_selection()
    assert len(app.members) == before_rods - len(rods)
    assert len(app.groups) == before_groups - 1
    assert sgp.find(app.groups, gid) is None


def test_delete_leaves_the_other_groups_holding_their_own_rods(app):
    """Groups hold member INDICES, so a deletion that did not remap them
    would leave every surviving group pointing at the wrong rods."""
    doomed = app.groups[0]['id']
    keep = app.groups[2]['id']
    kept_rods = {tuple(sorted((app.members[i]['a'], app.members[i]['b'])))
                 for i in sgp.rods_of(app.groups, keep, deep=True)}
    app._group_select_object(doomed)
    app._on_delete_selection()
    now = {tuple(sorted((app.members[i]['a'], app.members[i]['b'])))
           for i in sgp.rods_of(app.groups, keep, deep=True)}
    assert now == kept_rods, 'the surviving group moved onto other rods'


def test_delete_takes_subgroups_with_it(app):
    parent = app.groups[0]['id']
    sgp.new_group(app.groups, 'Brace', parent=parent, members=[])
    n_before = len(app.groups)
    app._group_select_object(parent)
    app._on_delete_selection()
    assert len(app.groups) == n_before - 2


def test_explode_keeps_the_rods(app):
    """The other verb. It is what "Delete group" used to do, and the reason
    nothing in the tab removed a group and its rods together."""
    gid = app.groups[0]['id']
    before = len(app.members)
    app._set_current_group(gid)
    app._group_explode()
    assert len(app.members) == before, 'explode must not touch geometry'
    assert sgp.find(app.groups, gid) is None


def test_deleting_a_group_is_one_step_of_undo(app):
    gid = app.groups[0]['id']
    before_rods, before_groups = len(app.members), len(app.groups)
    app._group_select_object(gid)
    app._on_delete_selection()
    assert len(app.members) < before_rods
    app._undo()
    assert len(app.members) == before_rods
    assert len(app.groups) == before_groups
    assert sgp.find(app.groups, gid) is not None


def test_deleting_rods_that_are_not_a_group_still_deletes_rods(app):
    """The ordinary path must be untouched: a part of a group is still
    rods, and Delete still removes rods."""
    loose = len(app.members) - 1
    before = len(app.members)
    app.selected_members = {loose}
    app.selected_nodes = set()
    app._on_delete_selection()
    assert len(app.members) == before - 1
    assert len(app.groups) == 3


def test_delete_with_nothing_selected_does_nothing(app):
    app.selected_members = set()
    app.selected_nodes = set()
    before = len(app.members), len(app.groups)
    app._on_delete_selection()
    assert (len(app.members), len(app.groups)) == before


# ── stage 2: the verbs are where the object is ─────────────────────────────

def test_right_click_offers_the_group_its_own_verbs(app):
    """It used to OPEN the group -- one verb out of eight, on the gesture
    every other program uses for "what can I do with this"."""
    gid = app.groups[0]['id']
    rod = _rod_of(app, gid)
    sp = app._screen_positions()
    m = app.members[rod]
    ex = (sp[m['a']][0] + sp[m['b']][0]) / 2
    ey = (sp[m['a']][1] + sp[m['b']][1]) / 2
    menu = app._object_menu_at(int(ex), int(ey))
    labels = [menu.entrycget(i, 'label') for i in range(menu.index('end') + 1)
              if menu.type(i) != 'separator']
    joined = ' | '.join(labels)
    for verb in ('Enter', 'Select it', 'Rename', 'Hide it', 'Explode', 'Delete it'):
        assert verb in joined, '%r missing from %r' % (verb, joined)
    # And opening is still reachable, just no longer the whole gesture.
    assert any(l.startswith('Enter ') for l in labels)


def test_the_menu_offers_the_way_out_while_inside_a_group(app):
    gid = app.groups[0]['id']
    app._group_open(gid)
    menu = app._object_menu_at(5, 5)          # empty canvas
    labels = [menu.entrycget(i, 'label') for i in range(menu.index('end') + 1)
              if menu.type(i) != 'separator']
    assert any(l.startswith('Leave ') for l in labels), labels


def test_entering_from_the_menu_is_the_same_as_double_clicking(app):
    gid = app.groups[0]['id']
    assert app._menu_enter(gid) == gid
    assert app._editing_gid() == gid


# ── stage 2: picking and dimming follow the context, not a checkbox ────────

def test_the_two_checkboxes_are_gone(app):
    """Both asked the user to manage something the tab already knew."""
    assert not hasattr(app, 'pick_inside_group')
    assert not hasattr(app, 'group_dim_others')


def test_picking_is_restricted_only_while_inside_a_group(app):
    gid = app.groups[0]['id']
    mine = set(sgp.rods_of(app.groups, gid, deep=True))

    # Outside: the whole model is pickable, even with a group highlighted.
    app._set_current_group(gid)
    _nodes, rods = app._pick_filter()
    assert rods is None, 'merely highlighting a row must not restrict picking'

    # Inside: only its own parts.
    app._group_open(gid)
    _nodes, rods = app._pick_filter()
    assert rods == mine
    app._group_step_out()
    assert app._pick_filter()[1] is None


def test_the_view_dims_only_while_inside_a_group(app):
    gid = app.groups[0]['id']
    app._set_current_group(gid)
    app._draw()
    assert not app.canvas.find_withtag('group_dim'), \
        'highlighting a row is not going inside it'
    app._group_open(gid)
    app._draw()
    dimmed = len(app.canvas.find_withtag('group_dim'))
    assert dimmed == len(app.members) - len(sgp.rods_of(app.groups, gid, deep=True))
    app._group_step_out()
    app._draw()
    assert not app.canvas.find_withtag('group_dim')


# ── stage 2: ownership follows the context ────────────────────────────────

def test_a_rod_drawn_inside_a_group_belongs_to_it(app):
    gid = app.groups[0]['id']
    before = set(sgp.rods_of(app.groups, gid, deep=True))
    app._group_open(gid)
    app.members.append({'a': 0, 'b': 2, 'conn': 'pin', 'role': 'user_rod'})
    claimed = app._claim_new_rod()
    assert claimed == gid
    now = set(sgp.rods_of(app.groups, gid, deep=True))
    assert now == before | {len(app.members) - 1}


def test_a_rod_drawn_outside_every_group_stays_ungrouped(app):
    app.members.append({'a': 0, 'b': 2, 'conn': 'pin', 'role': 'user_rod'})
    assert app._claim_new_rod() is None
    assert sgp.owner_of_rod(app.groups).get(len(app.members) - 1) is None


def test_taking_a_rod_out_of_its_group_from_the_menu(app):
    gid = app.groups[0]['id']
    rod = _rod_of(app, gid)
    app._menu_unassign(rod)
    assert sgp.owner_of_rod(app.groups).get(rod) is None
    assert len(app.members) == 10, 'the rod itself is untouched'
