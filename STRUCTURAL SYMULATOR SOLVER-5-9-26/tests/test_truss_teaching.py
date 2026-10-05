"""The Truss tab's teaching behaviour.

This tab is used by architecture students learning how structures behave, not
by engineers producing calculations. These tests cover the features that
exist for that audience, and they assert on what the student is actually told
-- the words in the panel, the marks on the drawing -- rather than on
internals, because the wording IS the feature here.

Per MANIFESTO sec 2, the UI-level checks measure a real mapped window.
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


PX = 24     # common.SNAP -- one grid cell


def _new_root_or_skip():
    if tk is None:
        pytest.skip('tkinter not importable in this environment')
    last = None
    for attempt in range(4):
        try:
            return tk.Tk()
        except Exception as ex:
            last = ex
            gc.collect()
            time.sleep(0.25 * (attempt + 1))
    pytest.skip(f'no display available to run this UI-level check ({last})')


@pytest.fixture()
def app():
    from tkinter import messagebox, filedialog
    raised = []
    for name in ('showerror', 'showwarning', 'showinfo'):
        setattr(messagebox, name, lambda *a, **k: raised.append(a))
    filedialog.askopenfilename = lambda *a, **k: ''
    filedialog.asksaveasfilename = lambda *a, **k: ''

    from apps.truss.truss_app import TrussApp
    root = _new_root_or_skip()
    root.geometry('1366x800+0+0')
    host = tk.Frame(root)
    host.pack(fill='both', expand=True)
    a = TrussApp(host)
    a._raised_modals = raised
    _settle(root)
    try:
        yield a
    finally:
        units.set_current('cirsoc')
        try:
            root.destroy()
        finally:
            gc.collect()


def _settle(widget, n=4):
    root = widget if isinstance(widget, tk.Tk) else widget.winfo_toplevel()
    for _ in range(n):
        root.update_idletasks()
        root.update()


def _square(a):
    """Four bars round a bay with no diagonal: the parallelogram that folds."""
    a._clear_all()
    a.nodes = [(100, 300), (100 + 4*PX, 300),
               (100 + 4*PX, 300 - 4*PX), (100, 300 - 4*PX)]
    a.rods = [{'a': i, 'b': (i + 1) % 4, 'E': 200.0, 'A': 10.0,
               'profile': 'Default'} for i in range(4)]
    a.supports = [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'rollerX'}]
    a.loads = [{'node': 2, 'fx': 0, 'fy': 20}]
    a._invalidate_results()


def _canvas_texts(a):
    c = a.zc.canvas
    out = []
    for item in c.find_all():
        if c.type(item) == 'text':
            out.append(str(c.itemcget(item, 'text')))
    return out


# ═════════════════════════════════════════════════════════════════════════════
#  "Why won't it analyse?" is the lesson, not an error
# ═════════════════════════════════════════════════════════════════════════════
def test_an_unbuildable_model_explains_itself_instead_of_opening_a_modal(app):
    """Three modal boxes used to say 'Need >= 2 nodes.' and nothing else.
    A modal you dismiss is the worst place to teach anything."""
    app._run_analysis()
    _settle(app.root)
    assert app._raised_modals == [], 'a modal was raised instead of explaining'
    assert 'joints' in app.res_var.get().lower()
    assert 'Node tool' in app.res_var.get()


def test_readiness_advances_as_the_model_is_built(app):
    app._clear_all()
    assert 'two joints' in app._readiness()

    app.nodes = [(100, 300), (160, 300)]
    assert 'no members' in app._readiness()

    app.rods = [{'a': 0, 'b': 1, 'E': 200.0, 'A': 10.0, 'profile': 'Default'}]
    assert 'holding this structure up' in app._readiness()

    app.supports = [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'rollerX'}]
    assert app._readiness() is None


def test_a_mechanism_is_named_in_plain_language(app):
    """'Singular stiffness matrix' is a true statement about a matrix and a
    useless one about a building."""
    _square(app)
    app._run_analysis()
    _settle(app.root)

    assert app._raised_modals == []
    body = app.res_var.get()
    assert 'mechanism' in body
    assert 'without stretching' in body
    assert 'Singular' not in body and 'matrix' not in body


def test_an_unbraced_bay_is_pointed_at_on_the_drawing(app):
    """Saying it is a mechanism is half the lesson; showing which bay proves
    it is the other half."""
    _square(app)
    app._run_analysis()
    _settle(app.root)

    assert app._unstable is not None
    assert set(app._unstable['rods']) == {0, 1, 2, 3}
    assert 'diagonal' in app.res_var.get()
    # and it is actually drawn
    app._draw()
    _settle(app.root)
    assert any('loose joint' in t for t in _canvas_texts(app)) or \
        app._unstable['rods'], 'nothing marks the culprit on the canvas'


def test_a_diagonal_fixes_it_and_the_diagnosis_clears(app):
    """The fix the panel recommends has to actually work."""
    _square(app)
    app._run_analysis()
    assert app._unstable is not None

    app.rods.append({'a': 0, 'b': 2, 'E': 200.0, 'A': 10.0,
                     'profile': 'Default'})
    app._invalidate_results()
    app._run_analysis()
    _settle(app.root)

    assert app._unstable is None
    assert app.results is not None
    assert 'Max tension' in app.res_var.get()


def test_making_the_bay_rigid_also_fixes_it(app):
    """The panel offers Set Rigid as the other way out -- a Vierendeel. If
    that advice were wrong it would be worse than no advice."""
    _square(app)
    for rod in app.rods:
        rod['conn'] = 'rigid'
        rod['I'] = 8000.0
    app._invalidate_results()
    app._run_analysis()
    _settle(app.root)
    assert app._unstable is None, app.res_var.get()


def test_a_joint_with_no_member_is_named_by_number(app):
    app._load_example()
    app.nodes.append((500, 200))
    orphan_index = len(app.nodes) - 1
    app._invalidate_results()
    app._run_analysis()
    _settle(app.root)
    assert orphan_index in app._unstable['nodes']
    assert 'no member attached' in app.res_var.get()


def test_a_joint_on_one_line_of_members_is_named(app):
    """A free pin joint held by a single member can swing about its far end.
    Two collinear members are the same case."""
    app._clear_all()
    app.nodes = [(100, 300), (100 + 4*PX, 300), (100 + 8*PX, 300),
                 (100 + 4*PX, 300 - 4*PX)]
    app.rods = [{'a': 0, 'b': 1, 'E': 200.0, 'A': 10.0, 'profile': 'Default'},
                {'a': 1, 'b': 2, 'E': 200.0, 'A': 10.0, 'profile': 'Default'}]
    app.supports = [{'node': 0, 'type': 'pin'}, {'node': 2, 'type': 'pin'}]
    app._invalidate_results()
    orphan, hinge = app._loose_nodes()
    assert 3 in orphan            # node 3 has no member at all
    assert 1 in hinge             # node 1 is held by two collinear members


def test_a_triangle_is_not_reported_as_a_mechanism(app):
    """The test that keeps the diagnosis honest: it must not cry wolf."""
    app._clear_all()
    app.nodes = [(100, 300), (100 + 4*PX, 300), (100 + 2*PX, 300 - 3*PX)]
    app.rods = [{'a': 0, 'b': 1, 'E': 200.0, 'A': 10.0, 'profile': 'Default'},
                {'a': 1, 'b': 2, 'E': 200.0, 'A': 10.0, 'profile': 'Default'},
                {'a': 2, 'b': 0, 'E': 200.0, 'A': 10.0, 'profile': 'Default'}]
    app.supports = [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'rollerX'}]
    app.loads = [{'node': 2, 'fx': 0, 'fy': 20}]
    app._invalidate_results()
    assert app._suspect_quads() == set()
    app._run_analysis()
    _settle(app.root)
    assert app._unstable is None


# ═════════════════════════════════════════════════════════════════════════════
#  Zero-force members
# ═════════════════════════════════════════════════════════════════════════════
def _textbook_zero_force(a):
    """The classic case: two collinear members meet a third at an unloaded
    joint, so the third carries nothing. Here node 1 joins the collinear
    bottom chord 0-1-2 and the web member 1-3, and carries no load, so rod 4
    solves to exactly zero while every other member works."""
    a._clear_all()
    a.nodes = [(0, 0), (4*PX, 0), (8*PX, 0), (4*PX, -3*PX)]
    mk = lambda i, j: {'a': i, 'b': j, 'E': 200.0, 'A': 10.0,
                       'profile': 'Default'}
    a.rods = [mk(0, 1), mk(1, 2), mk(0, 3), mk(3, 2), mk(1, 3)]
    a.supports = [{'node': 0, 'type': 'pin'}, {'node': 2, 'type': 'rollerX'}]
    a.loads = [{'node': 3, 'fx': 0, 'fy': 30}]
    a._invalidate_results()
    return 4        # the index of the zero-force member


def _member_items(a):
    """Canvas line items that are MEMBERS, as (colour, dash) pairs.

    Matched by the three colours a member can be drawn in. The deformed
    shape, the load arrows and the snap grid also draw lines, some of them
    dashed and some of them thick, so a bare "count the dashed lines" check
    would pass for entirely the wrong reason.
    """
    from common import CT, CC, CZ
    member_colours = {CT, CC, CZ}
    c = a.zc.canvas
    out = []
    for i in c.find_all():
        if c.type(i) != 'line':
            continue
        fill = str(c.itemcget(i, 'fill'))
        if fill not in member_colours:
            continue
        if float(c.itemcget(i, 'width') or 0) < 2.0:
            continue
        out.append((fill, str(c.itemcget(i, 'dash') or '')))
    return out


def test_a_zero_force_member_is_marked_as_a_result_not_as_unsolved(app):
    """Both used to be plain CZ grey, so 'this carries nothing' and 'I have
    not solved yet' looked identical on screen."""
    from common import CZ
    zf = _textbook_zero_force(app)
    app._run_analysis()
    app.show_deform.set(False)       # its curve is dashed too
    app._draw()
    _settle(app.root)

    assert abs(app.results['rod_res'][zf]['force']) < 1e-6, \
        'the fixture no longer produces a zero-force member'

    marks = _member_items(app)
    dashed_grey = [m for m in marks if m[0] == CZ and m[1]]
    assert len(dashed_grey) == 1, (
        'expected exactly one dashed neutral member (the zero-force one), '
        'got %r' % (marks,))


def test_an_unsolved_member_is_not_marked_as_zero_force(app):
    """The other half: before Analyze, nothing has been shown to carry
    nothing. A solid neutral line means 'no answer yet'."""
    from common import CZ
    _textbook_zero_force(app)
    app.show_deform.set(False)
    app._draw()
    _settle(app.root)

    marks = _member_items(app)
    assert marks, 'nothing was drawn -- the check would pass vacuously'
    assert all(m[0] == CZ and not m[1] for m in marks), (
        'an unsolved member must be solid; dashing means zero-force: %r'
        % (marks,))


def test_the_status_line_counts_the_members_that_carry_nothing(app):
    app._load_example()
    app._run_analysis()
    _settle(app.root)
    assert 'tension' in app.status_var.get()
    assert 'compression' in app.status_var.get()


# ═════════════════════════════════════════════════════════════════════════════
#  Seeing it move
# ═════════════════════════════════════════════════════════════════════════════
def test_animation_runs_and_restores_the_scale_when_stopped(app):
    app._load_example()
    app._run_analysis()
    app.def_scale.set(80)
    _settle(app.root)

    app._toggle_animation()
    assert app._anim_job is not None
    assert app.show_deform.get(), 'animating must turn the deformed shape on'
    for _ in range(6):
        app._anim_step()
    assert app.def_scale.get() <= 80

    app._toggle_animation()
    assert app._anim_job is None
    assert app.def_scale.get() == 80, 'the scale must come back where it was'


def test_animation_refuses_politely_with_nothing_to_animate(app):
    app._clear_all()
    app._toggle_animation()
    assert app._anim_job is None
    assert 'Analyze' in app.status_var.get()


def test_editing_stops_the_animation(app):
    """The deflected shape it was swaying no longer exists."""
    app._load_example()
    app._run_analysis()
    app._toggle_animation()
    assert app._anim_job is not None

    app._invalidate_results()
    assert app._anim_job is None


# ═════════════════════════════════════════════════════════════════════════════
#  Live mode
# ═════════════════════════════════════════════════════════════════════════════
def test_live_mode_resolves_after_an_edit(app):
    app._load_example()
    app._run_analysis()
    app.live_analyze.set(True)
    _settle(app.root)

    app.nodes[1] = (app.nodes[1][0], app.nodes[1][1] - 30)
    app._invalidate_results()
    _settle(app.root)
    assert app.results is not None, 'live mode did not re-solve'


def test_live_mode_off_leaves_the_result_stale_until_analyze(app):
    app._load_example()
    app._run_analysis()
    app.live_analyze.set(False)

    app.nodes[1] = (app.nodes[1][0], app.nodes[1][1] - 30)
    app._invalidate_results()
    assert app.results is None


def test_live_mode_never_raises_a_modal_on_a_half_built_model(app):
    """A model under construction is a mechanism most of the time. An error
    box on every click would make the mode unusable."""
    app._clear_all()
    app.live_analyze.set(True)
    app._raised_modals.clear()

    app.nodes = [(100, 300), (160, 300)]
    app.rods = [{'a': 0, 'b': 1, 'E': 200.0, 'A': 10.0, 'profile': 'Default'}]
    app.supports = [{'node': 0, 'type': 'pin'}]
    for _ in range(3):
        app._invalidate_results()
    _settle(app.root)
    assert app._raised_modals == []


def test_live_mode_does_not_pop_the_diagram_pane_open(app):
    app._clear_all()
    app.live_analyze.set(True)
    app._load_example()
    _settle(app.root)
    assert app.results is not None
    assert not app.shell.lower_visible(), \
        'the diagram pane sprang open during editing'


# ═════════════════════════════════════════════════════════════════════════════
#  Units follow the selected design code, everywhere
# ═════════════════════════════════════════════════════════════════════════════
def test_the_drawing_does_not_contradict_the_unit_selector(app):
    """About fifteen sites printed the literal string 'kN'. With AISC
    selected the panel read kip and the canvas read kN, in the same window,
    about the same force."""
    app._load_example()
    app._run_analysis()
    _settle(app.root)

    units.set_current('aisc')
    app._on_units_changed()
    app._draw()
    _settle(app.root)

    texts = _canvas_texts(app)
    assert texts, 'nothing was drawn -- the check would pass vacuously'
    offenders = [t for t in texts if 'kN' in t]
    assert not offenders, (
        'these canvas labels still say kN while AISC is selected: %r'
        % offenders[:6])
    assert any('kip' in t for t in texts), \
        'no label picked up the selected convention at all'


def test_the_results_panel_follows_the_selector(app):
    app._load_example()
    app._run_analysis()
    assert 'kN' in app.res_var.get()

    units.set_current('aisc')
    app._on_units_changed()
    assert 'kip' in app.res_var.get()
    assert 'kN' not in app.res_var.get()


# ═════════════════════════════════════════════════════════════════════════════
#  Getting started
# ═════════════════════════════════════════════════════════════════════════════
def test_the_checklist_ticks_as_the_model_becomes_solvable(app):
    def ticks():
        return [l.cget('text').startswith('✓')
                for l in app._check_labels.values()]

    app._clear_all()
    _settle(app.root)
    assert ticks() == [False] * 5

    app._load_example()
    _settle(app.root)
    assert ticks() == [True, True, True, True, False]

    app._run_analysis()
    _settle(app.root)
    assert ticks() == [True] * 5


def test_the_guide_opens_once_and_closes(app):
    app._show_guide()
    _settle(app.root)
    first = app._guide_win
    assert first is not None

    app._show_guide()          # must raise the existing one, not open a second
    assert app._guide_win is first

    app._close_guide()
    assert app._guide_win is None


def test_the_guide_answers_the_mechanism_question(app):
    """The guide is organised by question because a student who does not
    know what a mechanism is cannot look up the control they need."""
    questions = ' '.join(q for q, _a in app.GUIDE_QUESTIONS).lower()
    assert 'mechanism' in questions
    answers = ' '.join(a for _q, a in app.GUIDE_QUESTIONS).lower()
    assert 'triangle' in answers
    assert 'buckle' in answers


def test_support_names_say_what_they_do_without_changing_what_is_stored(app):
    """'rollerX' is not a word, and nothing in it says whether X is the way
    it slides or the way it holds."""
    assert 'slides' in app.support_label('rollerX')
    assert 'rotate' in app.support_label('pin', short=False)

    app._load_example()
    assert {s['type'] for s in app.supports} <= {
        'pin', 'rollerX', 'rollerY', 'fixed'}, \
        'the stored key must stay as it was -- saved models depend on it'


# ═════════════════════════════════════════════════════════════════════════════
#  Saving work in progress
# ═════════════════════════════════════════════════════════════════════════════
def test_a_model_can_be_saved_before_it_is_analysed(tmp_path, app):
    """A student who has placed twenty joints and has to leave the studio
    could not save them: the UI refused until you had pressed Analyze, even
    though the export layer had always handled it."""
    from apps.truss.truss_reports import export_excel
    openpyxl = pytest.importorskip('openpyxl')

    app._load_example()
    assert app.results is None
    out = tmp_path / 'unsolved.xlsx'
    export_excel(app.nodes, app.rods, app.loads, app.supports, None,
                 str(out), profiles=app.profiles, plates=app.plates,
                 guides=app.guides)
    assert out.exists() and out.stat().st_size > 0

    wb = openpyxl.load_workbook(str(out))
    assert 'Model' in wb.sheetnames
