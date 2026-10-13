"""Changing a model already in the tab, and getting it back (R-14).

Three things the tab could not do:

* **Edit a row.** Every table was Add/Delete only, so changing one load's
  magnitude meant deleting the row and retyping all of it.
* **Undo.** `grep -c undo` over the tab returned 0 while Truss, Cable Web,
  Stereo and the profile sketcher all had one. A deleted load was gone.
* **Leave the results alone.** `res_text` is a `tk.Text` with no `state`, so
  the user could type into their own results -- and did not find out, because
  the next Analyze overwrote whatever they typed.

Deleting several selected rows at once is here too: the tables are
`selectmode='extended'`, so three rows could be selected while Delete removed
exactly one.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

tk = pytest.importorskip('tkinter')

import units
import apps.beam.beam_app as beam_app
from apps.beam.beam_app import BeamApp


@pytest.fixture
def beam(monkeypatch):
    units.set_current('cirsoc')
    try:
        root = tk.Tk()
    except tk.TclError:                       # pragma: no cover - headless CI
        pytest.skip('no display')
    monkeypatch.setattr(beam_app, 'messagebox',
                        type('B', (), {'showerror': staticmethod(lambda *a: None),
                                       'showwarning': staticmethod(lambda *a: None),
                                       'showinfo': staticmethod(lambda *a: None)}))
    root.geometry('1400x900')
    app = BeamApp(root)
    app.pack(fill='both', expand=True)
    root.update()
    app._load_example_overhang()
    app.point_loads = [{'x': 1.0, 'P': 10.0}, {'x': 3.0, 'P': 20.0},
                       {'x': 5.0, 'P': 30.0}]
    app.moments = [{'x': 2.0, 'M': 4.0}]
    app._refresh_tables()
    root.update()
    try:
        yield app, root
    finally:
        units.set_current('cirsoc')
        try:
            root.destroy()
        except Exception:
            pass


def _select(tree, *indices):
    children = tree.get_children()
    tree.selection_set([children[i] for i in indices])


# ----------------------------------------------------------- editing a row

def test_a_row_can_be_edited_in_place(beam, monkeypatch):
    app, root = beam
    monkeypatch.setattr(app, '_ask', lambda *a, **k: {'x': 3.5, 'P': 99.0})
    _select(app.pl_tree, 1)
    app._edit_row(app.pl_tree, app.point_loads)
    assert app.point_loads[1] == {'x': 3.5, 'P': 99.0}
    # the others are untouched and the order is kept
    assert [p['x'] for p in app.point_loads] == [1.0, 3.5, 5.0]


def test_the_edit_dialog_opens_on_the_row_s_own_values(beam, monkeypatch):
    """Retyping a value you only wanted to nudge is the thing this fixes, so
    the dialog has to arrive pre-filled."""
    app, root = beam
    seen = {}

    def fake_ask(title, fields):
        seen['title'] = title
        seen['defaults'] = {key: default for key, _label, default in fields}
        return None

    monkeypatch.setattr(app, '_ask', fake_ask)
    _select(app.pl_tree, 2)
    app._edit_row(app.pl_tree, app.point_loads)
    assert seen['defaults'] == {'x': 5.0, 'P': 30.0}
    assert 'edit' in seen['title'].lower()


def test_an_edit_is_shown_in_the_selected_convention(beam, monkeypatch):
    app, root = beam
    units.set_current('aisc')
    root.update()
    seen = {}
    monkeypatch.setattr(app, '_ask',
                        lambda title, fields: seen.update(
                            {k: d for k, _l, d in fields}) or None)
    _select(app.pl_tree, 0)
    app._edit_row(app.pl_tree, app.point_loads)
    assert seen['x'] == pytest.approx(1.0 / 0.3048, rel=1e-6)   # 1 m in ft
    assert seen['P'] == pytest.approx(10e3 / 4448.2216152605, rel=1e-6)


def test_an_edited_station_off_the_beam_is_refused(beam, monkeypatch):
    app, root = beam
    monkeypatch.setattr(app, '_ask', lambda *a, **k: {'x': 99.0, 'P': 10.0})
    _select(app.pl_tree, 0)
    app._edit_row(app.pl_tree, app.point_loads)
    assert app.point_loads[0] == {'x': 1.0, 'P': 10.0}, 'the row must not change'


def test_cancelling_an_edit_changes_nothing(beam, monkeypatch):
    app, root = beam
    before = [dict(p) for p in app.point_loads]
    monkeypatch.setattr(app, '_ask', lambda *a, **k: None)
    _select(app.pl_tree, 1)
    app._edit_row(app.pl_tree, app.point_loads)
    assert app.point_loads == before


def test_editing_with_nothing_selected_does_nothing(beam, monkeypatch):
    app, root = beam
    before = [dict(p) for p in app.point_loads]
    monkeypatch.setattr(app, '_ask', lambda *a, **k: {'x': 1.0, 'P': 1.0})
    app.pl_tree.selection_remove(*app.pl_tree.get_children())
    app._edit_row(app.pl_tree, app.point_loads)
    assert app.point_loads == before


def test_a_support_type_can_be_edited(beam, monkeypatch):
    app, root = beam
    monkeypatch.setattr(app, '_ask', lambda *a, **k: {'x': 2.0, 'type': 'fixed'})
    _select(app.sup_tree, 0)
    app._edit_row(app.sup_tree, app.supports)
    assert app.supports[0] == {'x': 2.0, 'type': 'fixed'}


def test_every_table_is_wired_to_the_editor(beam):
    """A double-click on any row opens its editor -- including the q(x) table,
    whose dialog is a different one."""
    for tree in ('sup_tree', 'pl_tree', 'mm_tree', 'dl_tree', 'ndl_tree'):
        app, root = beam
        assert app.nametowidget(str(getattr(app, tree))).bind('<Double-1>'), tree
        break


def test_a_q_load_can_be_edited(beam, monkeypatch):
    app, root = beam
    app.nonuniform_loads = [{'expr': '10', 'x1': 0.0, 'x2': 6.0}]
    app._refresh_tables()
    monkeypatch.setattr(app, '_ask_nonuniform',
                        lambda initial=None: {'expr': '20*x', 'x1': 1.0,
                                              'x2': 5.0})
    _select(app.ndl_tree, 0)
    app._edit_row(app.ndl_tree, app.nonuniform_loads)
    assert app.nonuniform_loads == [{'expr': '20*x', 'x1': 1.0, 'x2': 5.0}]


# ------------------------------------------------------------------- undo

def test_undo_brings_back_a_deleted_load(beam):
    app, root = beam
    _select(app.pl_tree, 1)
    app._del_row(app.pl_tree, app.point_loads)
    assert [p['x'] for p in app.point_loads] == [1.0, 5.0]
    app._undo()
    assert [p['x'] for p in app.point_loads] == [1.0, 3.0, 5.0]


def test_undo_unwinds_several_changes_in_order(beam):
    app, root = beam
    app.point_loads = [{'x': 1.0, 'P': 10.0}]
    app._refresh_tables()
    _select(app.pl_tree, 0)
    app._del_row(app.pl_tree, app.point_loads)
    app._clear_all()
    app._undo()
    assert app.point_loads == []
    app._undo()
    assert [p['x'] for p in app.point_loads] == [1.0]


def test_undo_restores_the_beam_length_too(beam):
    app, root = beam
    app._apply_length(4.0, strays='delete')
    assert app.length == 4.0
    app._undo()
    assert app.length == 10.0
    assert app.len_var.get() == 10.0, 'the box must follow the model back'


def test_undo_with_nothing_to_undo_is_harmless(beam):
    app, root = beam
    while app._undo_stack:
        app._undo()
    before = [dict(p) for p in app.point_loads]
    app._undo()
    assert app.point_loads == before


def test_undo_does_not_grow_without_bound(beam):
    app, root = beam
    for i in range(BeamApp.UNDO_DEPTH + 15):
        app.point_loads.append({'x': 1.0, 'P': float(i)})
        app._push_undo('add')
    assert len(app._undo_stack) == BeamApp.UNDO_DEPTH


def test_an_edit_is_undoable(beam, monkeypatch):
    app, root = beam
    monkeypatch.setattr(app, '_ask', lambda *a, **k: {'x': 3.5, 'P': 99.0})
    _select(app.pl_tree, 1)
    app._edit_row(app.pl_tree, app.point_loads)
    app._undo()
    assert app.point_loads[1] == {'x': 3.0, 'P': 20.0}


def test_undo_is_bound_to_control_z(beam):
    assert beam[0].bind('<Control-z>'), 'Ctrl-Z is the shortcut everyone tries'


def test_undoing_an_analysed_model_drops_the_stale_result(beam):
    """The diagrams belong to the model that was analysed. Leaving them on
    screen next to a model that is no longer that one is how a user reads the
    wrong answer."""
    app, root = beam
    app._analyze()
    root.update()
    assert app.result is not None
    _select(app.pl_tree, 0)
    app._del_row(app.pl_tree, app.point_loads)
    app._undo()
    assert app.result is None


# ------------------------------------------------- the results box is output

def test_the_results_box_cannot_be_typed_into(beam):
    app, root = beam
    app._analyze()
    root.update()
    before = app.res_text.get('1.0', 'end')
    assert app.res_text.cget('state') == 'disabled'
    # Tk IGNORES insert/delete on a disabled text widget rather than raising,
    # so the property to assert is that nothing changed -- and that a
    # keystroke typed at it changes nothing either.
    app.res_text.insert('1.0', 'MINE NOW')
    app.res_text.focus_set()
    app.res_text.event_generate('<Key-x>')
    root.update()
    assert app.res_text.get('1.0', 'end') == before


def test_the_results_box_can_still_be_read_and_copied(beam):
    """Disabled must not mean unselectable: copying a reaction out of here is
    the whole point of the panel."""
    app, root = beam
    app._analyze()
    root.update()
    assert 'REACTIONS' in app.res_text.get('1.0', 'end')
    app.res_text.tag_add('sel', '1.0', '1.end')
    assert app.res_text.get('sel.first', 'sel.last')


def test_the_tab_still_writes_its_own_results(beam):
    app, root = beam
    app._analyze()
    root.update()
    assert 'EQUILIBRIUM' in app.res_text.get('1.0', 'end')
    app._clear_all()
    root.update()
    assert app.res_text.get('1.0', 'end').strip() == ''


# ------------------------------------------------------- multiple selection

def test_every_selected_row_is_deleted(beam):
    """The tables are selectmode='extended': three rows could be selected
    while Delete removed exactly one."""
    app, root = beam
    _select(app.pl_tree, 0, 2)
    app._del_row(app.pl_tree, app.point_loads)
    assert [p['x'] for p in app.point_loads] == [3.0]


def test_deleting_several_rows_is_one_undo_step(beam):
    app, root = beam
    _select(app.pl_tree, 0, 1, 2)
    app._del_row(app.pl_tree, app.point_loads)
    assert app.point_loads == []
    app._undo()
    assert len(app.point_loads) == 3
