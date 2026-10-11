"""Readability work in the Truss tab: presets, support symbols, joint
letters, and the app-wide text size.

All four exist for the same reader -- an architecture student who knows
what steel is but not that E = 200, who recognises a roller symbol but not
the word "rollerX", who cannot tell a joint number from a member number
when both are bare digits a few pixels apart, and who may be looking at
this on a projector.
"""
import gc
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import tkinter as tk
except Exception:
    tk = None

import pytest

import units


def _root_or_skip():
    if tk is None:
        pytest.skip('tkinter not importable in this environment')
    for attempt in range(4):
        try:
            return tk.Tk()
        except Exception as ex:
            last = ex
            gc.collect()
            time.sleep(0.2 * (attempt + 1))
    pytest.skip(f'no display available ({last})')


@pytest.fixture()
def app():
    from tkinter import messagebox, filedialog
    for name in ('showerror', 'showwarning', 'showinfo'):
        setattr(messagebox, name, lambda *a, **k: None)
    filedialog.asksaveasfilename = lambda *a, **k: ''
    from apps.truss.truss_app import TrussApp
    root = _root_or_skip()
    root.geometry('1280x800+0+0')
    host = tk.Frame(root)
    host.pack(fill='both', expand=True)
    a = TrussApp(host)
    _settle(root)
    try:
        yield a
    finally:
        units.set_current('cirsoc')
        try:
            root.destroy()
        finally:
            gc.collect()


def _settle(w, n=3):
    root = w if isinstance(w, tk.Tk) else w.winfo_toplevel()
    for _ in range(n):
        root.update_idletasks()
        root.update()


# ═════════════════════════════════════════════════════════════════════════════
#  Material and section presets
# ═════════════════════════════════════════════════════════════════════════════
def test_a_material_preset_fills_E(app):
    """"Steel" is a thing a student knows; "E = 200" is not."""
    app.mat_preset.set('Steel (any grade)')
    app._apply_material_preset()
    assert app.mat_E.get() == pytest.approx(200.0)

    app.mat_preset.set('Glulam GL24h (along)')
    app._apply_material_preset()
    assert app.mat_E.get() == pytest.approx(11.5)


def test_a_section_preset_fills_A_and_I(app):
    app.sec_preset.set('IPE 300')
    app._apply_section_preset()
    assert app.mat_A.get() == pytest.approx(53.8)
    assert app.mat_I.get() == pytest.approx(8356.0)


def test_timber_is_far_softer_than_steel(app):
    """A sanity check on the table itself, not just the plumbing: if these
    ever drift into each other the preset is teaching something false."""
    table = dict(app.MATERIAL_PRESETS)
    assert table['Steel (any grade)'] > 10 * table['Glulam GL24h (along)']
    assert table['Steel (any grade)'] > table['Aluminium 6061-T6']
    assert all(E > 0 for E in table.values())


def test_sections_grow_monotonically(app):
    """A deeper IPE must have more area AND more inertia, and inertia must
    grow faster -- that is the whole reason sections are deep."""
    rows = list(app.SECTION_PRESETS)
    for (n0, a0, i0), (n1, a1, i1) in zip(rows, rows[1:]):
        assert a1 > a0, f'{n1} has no more area than {n0}'
        assert i1 > i0, f'{n1} has no more inertia than {n0}'
        assert i1 / i0 > a1 / a0, (
            f'{n1} vs {n0}: inertia should grow faster than area')


def test_a_preset_fills_the_boxes_in_the_shown_convention(app):
    """The entry boxes are in the selected convention, so the preset has
    to be written in it too -- otherwise picking AISC and then "Steel"
    would type a kN-based number into a ksi box."""
    units.set_current('aisc')
    app._on_units_changed()
    app.mat_preset.set('Steel (any grade)')
    app._apply_material_preset()
    # 200 GPa is about 29 000 ksi, nothing like 200
    assert app.mat_E.get() > 1000


def test_the_boxes_stay_editable_after_a_preset(app):
    app.mat_preset.set('Steel (any grade)')
    app._apply_material_preset()
    app.mat_E.set(123.0)
    assert app.mat_E.get() == pytest.approx(123.0)


# ═════════════════════════════════════════════════════════════════════════════
#  Support types as symbols
# ═════════════════════════════════════════════════════════════════════════════
def test_all_four_support_types_are_offered_as_symbols(app):
    assert set(app.sup_btns) == {'pin', 'rollerX', 'rollerY', 'fixed'}
    for key, cell in app.sup_btns.items():
        canvases = [c for c in cell.winfo_children()
                    if c.winfo_class() == 'Canvas']
        assert canvases, f'{key} has no drawing'
        assert canvases[0].find_all(), f'{key} drew nothing'


def test_picking_a_symbol_sets_the_stored_key(app):
    """The words on screen changed; the stored value must not, or every
    saved model and workbook changes meaning."""
    app._pick_support('rollerY')
    assert app.sup_type.get() == 'rollerY'
    app._pick_support('fixed')
    assert app.sup_type.get() == 'fixed'


def test_the_chosen_symbol_is_the_one_marked(app):
    app._pick_support('rollerX')
    _settle(app.root)
    assert app.sup_btns['rollerX'].cget('relief') == 'solid'
    for other in ('pin', 'rollerY', 'fixed'):
        assert app.sup_btns[other].cget('relief') == 'flat'


def test_applying_a_support_still_stores_the_key(app):
    app._load_example()
    app.pending_sup = {1}
    app._pick_support('rollerY')
    app._apply_support()
    assert any(s['node'] == 1 and s['type'] == 'rollerY'
               for s in app.supports)


# ═════════════════════════════════════════════════════════════════════════════
#  Joint letters
# ═════════════════════════════════════════════════════════════════════════════
def test_joint_letters_run_past_z(app):
    assert app.joint_letter(0) == 'A'
    assert app.joint_letter(25) == 'Z'
    assert app.joint_letter(26) == 'AA'
    assert app.joint_letter(27) == 'AB'
    assert app.joint_letter(51) == 'AZ'
    assert app.joint_letter(52) == 'BA'


def test_the_drawing_letters_joints_and_numbers_members(app):
    """The ambiguity this fixes: on the canvas a joint number and a member
    number sit a few pixels apart and look identical."""
    app._load_example()
    app._draw()
    _settle(app.root)
    c = app.zc.canvas
    texts = {str(c.itemcget(i, 'text')) for i in c.find_all()
             if c.type(i) == 'text'}
    assert 'A' in texts and 'B' in texts, 'joints are not lettered'
    assert any(t.isdigit() for t in texts), 'members are not numbered'


def test_turning_lettering_off_restores_numbers(app):
    app._load_example()
    app.letter_joints.set(False)
    app._draw()
    _settle(app.root)
    assert app.joint_label(2) == '2'


def test_sentences_name_both_forms(app):
    """So a reader can map the drawing to the tables without counting
    round the structure."""
    app.letter_joints.set(True)
    text = app.joint_text(2)
    assert 'Node 2' in text and 'C' in text
    app.letter_joints.set(False)
    assert app.joint_text(2) == 'Node 2'


def test_the_stored_model_never_sees_a_letter(app):
    """Letters are a drawing convention. Indices are the model."""
    app._load_example()
    assert all(isinstance(r['a'], int) and isinstance(r['b'], int)
               for r in app.rods)
    assert all(isinstance(s['node'], int) for s in app.supports)
