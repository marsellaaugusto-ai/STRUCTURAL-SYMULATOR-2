"""Putting a section on the rods you selected.

THE BUG THIS GUARDS. The Section panel's "Assumed material (all rods)"
box applied to no rods at all. `mat_E` / `mat_A` / `mat_I` are read in
exactly two places, both of them rod CREATION, so selecting rods and
picking "IPE 240" filled the entry boxes, printed

    IPE 240 — A = 39.10 cm², I = 3892.00 cm⁴ (strong axis).

in the status bar, changed not one rod, and left the solved results
standing so no number on screen moved either. Reported 11-10-26 as "the
array does not update properly and the information does not change".

WHAT IS ASSERTED, and why each one is the bug rather than a detail:

* the selected rods' A actually changes, and the UNSELECTED ones do not;
* a section carries Fy and a radius of gyration with it, so the rods it
  lands on become CHECKED -- the old path wrote A and I only, which moved
  the forces and left every utilisation reading "no steel section";
* the solve is redone, because "the information does not change" is not
  fixed by clearing the results and showing nothing;
* a partial selection gets a family of its own. A section lives on a
  family here, so writing it onto "Default" when three of its seven rods
  are selected would silently re-section the other four;
* and the Selection box names the section, since it is what the reader
  looks at to see whether anything happened.
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


def _root_or_skip():
    if tk is None:
        pytest.skip('tkinter not importable in this environment')
    last = None
    for attempt in range(4):
        try:
            return tk.Tk()
        except Exception as ex:
            last = ex
            gc.collect()
            time.sleep(0.2 * (attempt + 1))
    pytest.skip('no display available (%s)' % last)


def _settle(root, n=3):
    for _ in range(n):
        root.update_idletasks()
        root.update()


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
    a._load_example()
    a._run_analysis()
    _settle(root)
    try:
        yield a
    finally:
        try:
            root.destroy()
        finally:
            gc.collect()


def _areas(app):
    return [r['A'] for r in app.rods]


def _select(app, idx):
    app.selected_rods = set(idx)
    app.selected_nodes = set()
    app._show_sel()


# ═════════════════════════════════════════════════════════════════════════════
#  The reported bug
# ═════════════════════════════════════════════════════════════════════════════
def test_a_section_reaches_the_rods_you_selected(app):
    before = _areas(app)
    _select(app, [0, 1, 2])
    app.sec_preset.set('IPE 240')
    app._apply_section_preset()

    after = _areas(app)
    assert after[:3] != before[:3], (
        'picking a section with rods selected changed nothing -- this is '
        'the reported bug')
    assert len(set(after[:3])) == 1
    assert after[3:] == before[3:], 'it reached rods that were not selected'


def test_the_rods_it_lands_on_become_checked(app):
    """A section is Fy and a radius of gyration too, not just A and I.
    Writing A and I alone moved the forces and left every rod reading
    "no steel section", which looks like nothing happened."""
    _select(app, [0, 1, 2])
    app.sec_preset.set('IPE 240')
    app._apply_section_preset()
    app._run_analysis()
    checks = app.rod_checks or []
    assert checks, 'no checks were computed at all'
    assert all(checks[i].get('checked') for i in (0, 1, 2)), (
        'the sectioned rods are still unchecked: %s'
        % [checks[i].get('note') for i in (0, 1, 2)])
    assert all(checks[i]['util'] > 0 for i in (0, 1, 2))


def test_the_numbers_on_screen_are_re_solved_not_just_cleared(app):
    """"The information does not change" is not fixed by showing none."""
    _select(app, [])
    before = app.res_var.get()
    assert before.strip()
    app.mat_A.set(app.show('area', 200.0))
    app._apply_material_to_rods()
    assert app.results is not None, 'the results were cleared and left empty'
    assert app.res_var.get() != before, 'the result panel says the same thing'


def test_the_status_bar_says_what_actually_happened(app):
    _select(app, [0, 1])
    app.sec_preset.set('IPE 200')
    app._apply_section_preset()
    said = app.status_var.get()
    assert 'IPE 200' in said
    assert '2 selected rods' in said


# ═════════════════════════════════════════════════════════════════════════════
#  Families: a section belongs to one
# ═════════════════════════════════════════════════════════════════════════════
def test_a_partial_selection_gets_a_family_of_its_own(app):
    """Three of Default's four rods must not re-section the fourth."""
    default = [i for i, r in enumerate(app.rods)
               if r.get('profile', 'Default') == 'Default']
    assert len(default) > 1
    keep = default[-1]
    before = app.rods[keep]['A']

    _select(app, default[:-1])
    app.sec_preset.set('IPE 400')
    app._apply_section_preset()

    assert app.rods[keep]['A'] == before, (
        'a rod that was not selected was re-sectioned with its family')
    assert app.rods[keep].get('profile', 'Default') == 'Default'
    fam = app.rods[default[0]].get('profile', 'Default')
    assert fam != 'Default'
    assert app.profiles[fam]['catalog'] == 'IPE 400'


def test_a_whole_family_keeps_its_name(app):
    """Selecting all of a family is the ordinary case, and it must not
    litter the model with a new family for nothing."""
    default = [i for i, r in enumerate(app.rods)
               if r.get('profile', 'Default') == 'Default']
    names = set(app.profiles)
    _select(app, default)
    app.sec_preset.set('IPE 200')
    app._apply_section_preset()
    assert set(app.profiles) == names, 'a redundant family was created'
    assert app.profiles['Default']['catalog'] == 'IPE 200'
    assert all(app.rods[i].get('profile', 'Default') == 'Default'
               for i in default)


def test_a_second_section_of_the_same_name_does_not_collide(app):
    _select(app, [0])
    app.sec_preset.set('IPE 300')
    app._apply_section_preset()
    _select(app, [1])
    app.sec_preset.set('IPE 300')
    app._apply_section_preset()
    f0 = app.rods[0].get('profile')
    f1 = app.rods[1].get('profile')
    assert f0 != f1, 'the second selection joined the first one\'s family'
    assert app.profiles[f0]['catalog'] == app.profiles[f1]['catalog'] == 'IPE 300'


# ═════════════════════════════════════════════════════════════════════════════
#  Saying what it will do, and what it did
# ═════════════════════════════════════════════════════════════════════════════
def test_the_button_names_its_target_and_follows_the_selection(app):
    _select(app, [])
    assert 'all rods' in app.mat_apply_btn.cget('text')
    _select(app, [0, 1, 2])
    assert '3 selected rods' in app.mat_apply_btn.cget('text')
    _select(app, [4])
    assert '1 selected rod' in app.mat_apply_btn.cget('text')
    assert '1 selected rods' not in app.mat_apply_btn.cget('text')


def test_the_selection_box_names_the_section(app):
    _select(app, [0, 1])
    app.sec_preset.set('IPE 240')
    app._apply_section_preset()
    _select(app, [0, 1])
    text = app.sel_text.get('1.0', 'end')
    assert 'IPE 240' in text, text


def test_an_unsectioned_rod_says_so_rather_than_showing_a_blank(app):
    _select(app, [0])
    text = app.sel_text.get('1.0', 'end')
    assert 'none' in text and 'not checked' in text, text


def test_typing_an_area_over_a_catalogue_section_is_said_out_loud(app):
    """The app allows it -- overriding one number of a section is a fair
    thing to try. Finding out later that the check was still using that
    section's radius of gyration is not."""
    _select(app, [0, 1])
    app.sec_preset.set('IPE 240')
    app._apply_section_preset()
    _select(app, [0])
    app.mat_A.set(app.show('area', 999.0))
    app._apply_material_to_rods()
    assert 'overrides the section' in app.status_var.get()
    _select(app, [0])
    assert 'A overridden' in app.sel_text.get('1.0', 'end')


# ═════════════════════════════════════════════════════════════════════════════
#  Materials, and undo
# ═════════════════════════════════════════════════════════════════════════════
def test_a_material_preset_reaches_the_selected_rods_only(app):
    _select(app, [0])
    other = app.rods[1]['E']
    app.mat_preset.set('Glulam GL24h (along)')
    app._apply_material_preset()
    assert app.rods[0]['E'] == pytest.approx(11.5)
    assert app.rods[1]['E'] == other


def test_a_material_preset_with_nothing_selected_reaches_every_rod(app):
    _select(app, [])
    app.mat_preset.set('Aluminium 6061-T6')
    app._apply_material_preset()
    assert all(r['E'] == pytest.approx(70.0) for r in app.rods)


def test_undo_puts_the_old_section_back(app):
    _select(app, [0])
    before = app.rods[0]['A']
    app.sec_preset.set('IPE 160')
    app._apply_section_preset()
    assert app.rods[0]['A'] != before
    app._undo()
    assert app.rods[0]['A'] == pytest.approx(before)


def test_applying_to_an_empty_model_says_so_instead_of_raising(app):
    app.rods.clear()
    app.selected_rods = set()
    app._apply_material_to_rods()
    assert 'no rods' in app.status_var.get().lower()
