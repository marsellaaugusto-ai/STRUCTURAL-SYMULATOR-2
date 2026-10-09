"""The outliner: the group tree as a tree.

The rows themselves are covered by TestGroupsPanel in test_stereo_app.py,
which drives them through the same handlers it always did. This file is
about the three things a real tree can do that a flat list of indented
strings could not:

  * put a branch away, and have it stay away across the refreshes that
    happen on almost every edit;
  * change the nesting by dragging a group onto another;
  * be the selection -- the same current group shown in the tree and in
    the view, whichever one you touched.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import tkinter as tk

from apps.stereo import stereo_groups as sgp
from apps.stereo.stereo_app_outliner import DRAG_SLOP_PX, UNGROUPED_IID


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    seen = []
    for kind in ('showinfo', 'showerror', 'showwarning'):
        monkeypatch.setattr('apps.stereo.stereo_app.messagebox.%s' % kind,
                            lambda *a, _k=kind, **kw: seen.append((_k,) + a))
    monkeypatch.setattr('apps.stereo.stereo_app_outliner.messagebox.showinfo',
                        lambda *a, **kw: seen.append(('showinfo',) + a))
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
def tree(app):
    """Roof > Bay 1, Bay 2, and a separate Columns group."""
    sgp.new_group(app.groups, 'Roof', members=[])
    roof = app.groups[-1]['id']
    sgp.new_group(app.groups, 'Bay 1', parent=roof, members=range(0, 20))
    bay1 = app.groups[-1]['id']
    sgp.new_group(app.groups, 'Bay 2', parent=roof, members=range(20, 40))
    bay2 = app.groups[-1]['id']
    sgp.new_group(app.groups, 'Columns', members=range(40, 60))
    cols = app.groups[-1]['id']
    app._refresh_group_list()
    # The tree has no geometry until its panel is on screen, and without
    # geometry every pointer event lands in empty space -- which is a real
    # drop target, so a broken drag would look exactly like a refused one
    # and half of these tests would pass for the wrong reason.
    app._set_mode('groups')
    app.root.update_idletasks()
    app.root.update()
    return {'roof': roof, 'bay1': bay1, 'bay2': bay2, 'cols': cols}


def iid(app, gid):
    return app._group_row_iid(gid)


class At:
    """A pointer event over a row."""

    def __init__(self, x, y):
        self.x = x
        self.y = y


def over(app, gid):
    """The middle of a row, insisting the row really is on screen."""
    box = app.group_list.bbox(iid(app, gid))
    assert box, 'the outliner is not laid out, so this would not be a drag'
    return At(20, box[1] + box[3] // 2)


def below_everything(app):
    """Clear of every row: the drop that means "out, to the top"."""
    return At(20, app.group_list.winfo_height() + 200)


def drag(app, gid_from, to):
    """Drag one row onto another, the way a pointer would.

    `to` is a gid, or None for the empty space below the rows.
    """
    end = below_everything(app) if to is None else over(app, to)
    app._on_outliner_press(over(app, gid_from))
    app._on_outliner_drag(At(end.x + DRAG_SLOP_PX + 4, end.y))
    app._on_outliner_drop(At(end.x, end.y))
    app.root.update_idletasks()


# ── the tree is a tree ───────────────────────────────────────────────────

def test_the_rows_nest_the_way_the_groups_do(app, tree):
    t = app.group_list
    assert t.parent(iid(app, tree['roof'])) == ''
    assert set(t.get_children(iid(app, tree['roof']))) == {
        iid(app, tree['bay1']), iid(app, tree['bay2'])}
    assert t.parent(iid(app, tree['cols'])) == ''


def test_ungrouped_is_a_row_but_never_a_parent(app, tree):
    """It is where the rods nobody assigned still are, not a container."""
    app.groups[:] = [g for g in app.groups if g['id'] != tree['cols']]
    app._refresh_group_list()
    assert app.group_list.exists(UNGROUPED_IID)
    assert app.group_list.parent(UNGROUPED_IID) == ''
    assert app.group_list.get_children(UNGROUPED_IID) == ()


def test_a_row_is_found_by_its_group_not_its_position(app, tree):
    for gid in tree.values():
        assert app._group_row_gid(iid(app, gid)) == gid
    assert app._group_row_gid(UNGROUPED_IID) is None
    assert app._group_row_gid('') is None
    assert app._group_row_gid('nonsense') is None


# ── putting a branch away ────────────────────────────────────────────────

def close_branch(app, gid):
    """Collapse a branch the way the widget does: focus, then the event."""
    app.group_list.focus(iid(app, gid))
    app.group_list.item(iid(app, gid), open=False)
    app._on_outliner_close()
    app.root.update_idletasks()


def test_a_closed_branch_stays_closed_across_a_refresh(app, tree):
    """Refreshes happen on almost every edit. A tree that sprang open each
    time would never stay put long enough to be worth closing."""
    close_branch(app, tree['roof'])
    for _ in range(3):
        app._refresh_group_list()
    assert not app.group_list.item(iid(app, tree['roof']), 'open')


def test_opening_it_again_is_remembered_too(app, tree):
    close_branch(app, tree['roof'])
    app.group_list.focus(iid(app, tree['roof']))
    app.group_list.item(iid(app, tree['roof']), open=True)
    app._on_outliner_open()
    app._refresh_group_list()
    assert app.group_list.item(iid(app, tree['roof']), 'open')


def test_closing_a_branch_takes_the_selection_with_it(app, tree):
    """Otherwise the two rules fight: closing a branch that holds the
    current group hides the selection, and the next refresh opens the
    branch again to show it."""
    app._set_current_group(tree['bay1'], say=False)
    assert app._current_group() == tree['bay1']
    close_branch(app, tree['roof'])
    assert app._current_group() == tree['roof']
    app._refresh_group_list()
    assert not app.group_list.item(iid(app, tree['roof']), 'open')


def test_a_group_outside_the_closed_branch_keeps_the_selection(app, tree):
    app._set_current_group(tree['cols'], say=False)
    close_branch(app, tree['roof'])
    assert app._current_group() == tree['cols']


def test_choosing_a_hidden_row_opens_what_it_is_inside(app, tree):
    """A row selected invisibly would have the panel disagreeing with the
    view while looking as though it did not."""
    close_branch(app, tree['roof'])
    app._set_current_group(tree['bay2'], say=False)
    assert app._current_group() == tree['bay2']
    assert app.group_list.item(iid(app, tree['roof']), 'open')


# ── two-way selection ────────────────────────────────────────────────────

def test_the_view_points_the_tree_at_the_current_group(app, tree):
    app._set_current_group(tree['bay2'], say=False)
    assert app.group_list.selection() == (iid(app, tree['bay2']),)


def test_the_tree_points_the_view_at_the_picked_group(app, tree):
    app.group_list.selection_set(iid(app, tree['bay1']))
    app._on_group_pick()
    assert app._group_sel == tree['bay1']
    assert app._current_group() == tree['bay1']


def test_nothing_selected_reads_as_nothing_not_as_ungrouped(app, tree):
    """False, not None: None is a real answer here -- it is Ungrouped."""
    app._group_row_clear()
    assert app._current_group() is False


def test_the_ungrouped_row_reads_as_ungrouped(app, tree):
    app.groups[:] = [g for g in app.groups if g['id'] != tree['cols']]
    app._refresh_group_list()
    app.group_list.selection_set(UNGROUPED_IID)
    assert app._current_group() is None


def test_a_row_for_a_group_that_is_gone_reads_as_nothing(app, tree):
    """A stale selection must not answer with an id nothing has."""
    app.group_list.selection_set(iid(app, tree['bay1']))
    app.groups[:] = [g for g in app.groups if g['id'] != tree['bay1']]
    assert app._current_group() is False


# ── dragging a group somewhere else ──────────────────────────────────────

def test_dragging_a_group_onto_another_nests_it(app, tree):
    drag(app, tree['cols'], tree['roof'])
    assert sgp.find(app.groups, tree['cols'])['parent'] == tree['roof']
    assert app.group_list.parent(iid(app, tree['cols'])) == \
        iid(app, tree['roof'])


def test_dragging_a_group_clear_of_every_row_takes_it_to_the_top(app, tree):
    drag(app, tree['bay1'], None)
    assert sgp.find(app.groups, tree['bay1'])['parent'] is None


def test_a_drag_is_undoable(app, tree):
    drag(app, tree['cols'], tree['roof'])
    assert sgp.find(app.groups, tree['cols'])['parent'] == tree['roof']
    app._undo()
    assert sgp.find(app.groups, tree['cols'])['parent'] is None


def test_dragging_moves_no_rods(app, tree):
    """Nesting says which branch OWNS a rod, not where the steel is."""
    before = {g['id']: set(g['members']) for g in app.groups}
    drag(app, tree['cols'], tree['roof'])
    after = {g['id']: set(g['members']) for g in app.groups}
    assert after == before


def test_a_group_cannot_be_dragged_into_itself(app, tree):
    drag(app, tree['roof'], tree['roof'])
    assert sgp.find(app.groups, tree['roof'])['parent'] is None


def test_a_group_cannot_be_dragged_into_its_own_child(app, tree):
    """A cycle would make every recursive walk loop forever."""
    drag(app, tree['roof'], tree['bay1'])
    assert sgp.find(app.groups, tree['roof'])['parent'] is None
    assert sgp.find(app.groups, tree['bay1'])['parent'] == tree['roof']


def test_nothing_can_be_dragged_into_ungrouped(app, tree):
    """Ungrouped is not a group; nothing goes inside it."""
    app.groups[:] = [g for g in app.groups if g['id'] != tree['cols']]
    app._refresh_group_list()
    app.root.update_idletasks()
    box = app.group_list.bbox(UNGROUPED_IID)
    assert box, 'the Ungrouped row is not on screen'
    at = At(20, box[1] + box[3] // 2)
    app._on_outliner_press(over(app, tree['bay1']))
    app._on_outliner_drag(At(at.x + DRAG_SLOP_PX + 4, at.y))
    app._on_outliner_drop(at)
    assert sgp.find(app.groups, tree['bay1'])['parent'] == tree['roof']


def test_the_ungrouped_row_cannot_be_dragged_at_all(app, tree):
    app.groups[:] = [g for g in app.groups if g['id'] != tree['cols']]
    app._refresh_group_list()
    app.root.update_idletasks()

    box = app.group_list.bbox(UNGROUPED_IID)
    assert box, 'the Ungrouped row is not on screen'
    app._on_outliner_press(At(20, box[1] + box[3] // 2))
    assert app._drag_from is None


def test_a_click_that_does_not_move_is_not_a_drag(app, tree):
    """Every click lands on a row. Without a threshold every one of them
    would be a one-pixel reparent."""
    start = over(app, tree['cols'])
    app._on_outliner_press(start)
    nudge = At(start.x + 1, start.y + 1)
    app._on_outliner_drag(nudge)
    app._on_outliner_drop(nudge)
    assert sgp.find(app.groups, tree['cols'])['parent'] is None


def test_dropping_a_group_where_it_already_is_changes_nothing(app, tree):
    depth = len(app._undo_stack)
    drag(app, tree['bay1'], tree['roof'])
    assert sgp.find(app.groups, tree['bay1'])['parent'] == tree['roof']
    assert len(app._undo_stack) == depth, 'no undo step for a non-move'


def test_a_drag_while_a_group_is_open_is_refused(app, tree, dialogs):
    """The same lock every other verb respects: what is open is being
    edited, and its place in the tree is not up for grabs."""
    app._group_edit_toggle(tree['bay1'])
    assert app._editing_gid() == tree['bay1']
    assert app._reparent_group(tree['cols'], tree['roof']) is False
    assert sgp.find(app.groups, tree['cols'])['parent'] is None


# ── the long-name case ───────────────────────────────────────────────────

def test_short_names_cost_no_sideways_scrollbar(app, tree):
    app.root.update_idletasks()
    app._refresh_group_list()
    app.root.update_idletasks()
    assert not app._group_xbar.winfo_ismapped()


def test_a_name_too_long_for_the_panel_can_still_be_reached(app, tree):
    sgp.rename(app.groups, tree['bay1'], 'Bay 1 ' + 'very long name ' * 8)
    app.root.update_idletasks()
    app._refresh_group_list()
    app.root.update_idletasks()
    app.root.update()
    assert app._group_xbar.winfo_ismapped()


def test_a_new_model_does_not_inherit_a_collapsed_branch(app, tree):
    """Group ids start again at 1 for a new list, so keeping which
    branches were put away would collapse a group of the new model
    because an unrelated one of the old model was collapsed."""
    close_branch(app, tree['roof'])
    assert app._group_closed
    app._drop_groups()
    assert app._group_closed == set()
    sgp.new_group(app.groups, 'Fresh', members=range(0, 10))
    sgp.new_group(app.groups, 'Inside', parent=app.groups[-1]['id'],
                  members=range(10, 20))
    app._refresh_group_list()
    assert app.group_list.item(iid(app, app.groups[0]['id']), 'open')
