"""What the Beam tab does with input it cannot use (R-5, R-6, R-7).

Driven through the real tab, because every one of these is a thing the tab
*said* (or failed to say) rather than a thing the solver computed:

* **R-5** -- no validation of the beam's own numbers. A zero allowable made
  the stress check print `OK`, which is the worst possible failure mode for a
  check: a missing input read as a pass.
* **R-6** -- `tk.DoubleVar.get()` raises `TclError` when its box holds
  anything that is not a float, and `_set_length` read it unguarded, so the
  exception escaped into the Tk callback: the length did not change and
  NOTHING was said. In a double-clicked app the traceback goes to a console
  nobody sees.
* **R-7** -- the Add dialogs refuse an off-beam station (B-5), but shortening
  the beam could still strand entries that were legal when entered. Analyze
  then failed wholesale, naming whichever entry it reached first, and nothing
  marked the offending rows.

The modal dialogs are replaced rather than driven: `messagebox` is swapped for
a recorder, and the one question the tab asks about stranded rows
(`_ask_stray_policy`) is a method precisely so a test can answer it.
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


class Recorder:
    """Stands in for tkinter.messagebox and remembers what was shown."""

    def __init__(self):
        self.shown = []

    def showerror(self, title, message):
        self.shown.append(('error', title, message))

    def showwarning(self, title, message):
        self.shown.append(('warning', title, message))

    def showinfo(self, title, message):
        self.shown.append(('info', title, message))

    def text(self):
        return '\n'.join(m for _, _, m in self.shown)

    def titles(self):
        return [t for _, t, _ in self.shown]


@pytest.fixture
def beam(monkeypatch):
    units.set_current('cirsoc')
    try:
        root = tk.Tk()
    except tk.TclError:                       # pragma: no cover - headless CI
        pytest.skip('no display')
    root.geometry('1400x900')
    box = Recorder()
    monkeypatch.setattr(beam_app, 'messagebox', box)
    app = BeamApp(root)
    app.pack(fill='both', expand=True)
    root.update()
    app.length = 6.0
    app.len_var.set(6.0)
    app.supports = [{'x': 0.0, 'type': 'pin'}, {'x': 6.0, 'type': 'roller'}]
    app.dloads = [{'x1': 0.0, 'x2': 6.0, 'w1': 10.0, 'w2': 10.0}]
    app._refresh_tables()
    try:
        yield app, root, box
    finally:
        units.set_current('cirsoc')
        try:
            root.destroy()
        except Exception:
            pass


def _type_into(app, var, text):
    """Put raw text in an entry variable, as a user typing would.

    `Variable.set` passes the value through to Tcl unchecked, which is exactly
    what an Entry widget does when someone types in it -- a DoubleVar whose box
    holds "abc" is a real state the tab has to survive, not an invented one.

    It also goes through the variable's OWN interpreter, which is the only
    reliable way: writing through `app.tk.globalsetvar` set a variable the tab
    never read back when the tab's variables had no `master` and so belonged to
    tkinter's default root, and these tests passed alone and failed in the full
    suite. The tab names its masters now, but going through the variable keeps
    that irrelevant.
    """
    var.set(text)


# ------------------------------------------------------- R-6 · typed garbage

def test_garbage_in_the_length_box_is_reported_not_swallowed(beam):
    app, root, box = beam
    _type_into(app, app.len_var, 'abc')
    app._set_length()                      # must not raise
    assert box.shown, 'nothing was said at all'
    assert 'abc' in box.text()
    assert app.length == 6.0, 'the length must not change on bad input'


def test_the_message_names_the_field(beam):
    app, root, box = beam
    _type_into(app, app.len_var, '4,5')    # a comma decimal separator
    app._set_length()
    assert 'length' in box.text().lower()
    assert '4,5' in box.text()


def test_garbage_in_a_section_box_is_reported_by_name(beam):
    app, root, box = beam
    _type_into(app, app.sec_vars['I'], 'eight thousand')
    app._analyze()
    assert box.shown
    assert 'I' in box.text()
    assert app.result is None, 'a model that could not be read must not analyse'


def test_an_empty_box_reads_as_empty_not_as_zero(beam):
    app, root, box = beam
    _type_into(app, app.sec_vars['E'], '')
    app._analyze()
    assert box.shown
    assert app.result is None


def test_a_good_model_still_analyses(beam):
    """The guards must let everything that works through."""
    app, root, box = beam
    app._analyze()
    assert app.result is not None
    assert not box.shown, box.shown


def test_exporting_with_garbage_in_a_box_names_the_field(beam):
    app, root, box = beam
    _type_into(app, app.len_var, 'abc')
    with pytest.raises(ValueError, match='length'):
        app._current_state()


# ------------------------------------------------- R-5 · the model's numbers

@pytest.mark.parametrize('key,value,word', [
    ('E', 0.0, 'E'),
    ('E', -200.0, 'E'),
    ('I', 0.0, 'I'),
    ('c', 0.0, 'c'),
    ('A', 0.0, 'area'),
    ('allow_bend', -1.0, 'allowable'),
    ('allow_shear', -1.0, 'allowable'),
])
def test_an_unusable_section_number_is_refused_by_name(beam, key, value, word):
    app, root, box = beam
    app.sec_vars[key].set(value)
    app._analyze()
    assert app.result is None, f'{key}={value} analysed anyway'
    assert word.lower() in box.text().lower(), box.text()


def test_a_zero_length_beam_is_refused_before_the_solver_sees_it(beam):
    """Straight at Analyze, which is the path an imported workbook takes."""
    app, root, box = beam
    app.len_var.set(0.0)
    app._analyze()
    assert app.result is None
    assert 'length' in box.text().lower()


def test_set_length_refuses_zero_and_puts_the_old_length_back(beam):
    app, root, box = beam
    app.len_var.set(0.0)
    app._set_length()
    assert app.length == 6.0, 'the model must keep the length that worked'
    assert app.len_var.get() == 6.0, 'and the box must show it again'
    assert 'length' in box.text().lower()


def test_every_problem_is_reported_at_once(beam):
    """Fixing one number at a time, with a modal dialog between each, is what
    made this worth a finding."""
    app, root, box = beam
    app.sec_vars['E'].set(0.0)
    app.sec_vars['c'].set(0.0)
    app.point_loads = [{'x': 99.0, 'P': 10.0}]
    app._analyze()
    text = box.text()
    assert 'E' in text and 'c' in text and '99' in text, text


def test_a_missing_allowable_is_not_checked_rather_than_ok(beam):
    """`bend_ratio = sigma / allow if allow else 0` turned a missing allowable
    into a PASS -- a check that cannot fail is worse than no check."""
    app, root, box = beam
    app.sec_vars['allow_bend'].set(0.0)
    app._analyze()
    root.update()
    assert app.result is not None, 'no allowable is a choice, not an error'
    # Scoped to the stress check: SERVICEABILITY has an 'allowable' line of
    # its own (the L/n deflection limit, R-16) and it comes first.
    stress = app.res_text.get('1.0', 'end').split('STRESS CHECK')[1]
    bending = [ln for ln in stress.splitlines() if 'allowable' in ln][0]
    assert 'not checked' in bending.lower(), bending
    assert 'OK' not in bending, bending


def test_a_real_allowable_still_passes_or_fails(beam):
    app, root, box = beam
    app._analyze()
    root.update()
    text = app.res_text.get('1.0', 'end')
    assert 'ratio' in text
    assert 'OK' in text or 'FAIL' in text


def test_an_exceeded_allowable_still_fails(beam):
    app, root, box = beam
    app.sec_vars['allow_bend'].set(0.1)
    app._analyze()
    root.update()
    assert 'FAIL' in app.res_text.get('1.0', 'end')


# --------------------------------------------- R-7 · shortening the beam

def _stray_model(app):
    app.supports = [{'x': 0.0, 'type': 'pin'}, {'x': 6.0, 'type': 'roller'}]
    app.point_loads = [{'x': 2.0, 'P': 10.0}, {'x': 5.0, 'P': 10.0}]
    app.moments = [{'x': 5.5, 'M': 4.0}]
    app.dloads = [{'x1': 0.0, 'x2': 6.0, 'w1': 10.0, 'w2': 10.0},
                  {'x1': 4.0, 'x2': 5.0, 'w1': 2.0, 'w2': 2.0}]
    app._refresh_tables()


def test_the_entries_that_would_fall_off_are_found(beam):
    app, root, box = beam
    _stray_model(app)
    strays = app._entries_off_beam(3.0)
    kinds = sorted(s['kind'] for s in strays)
    # the support at 6, the point load at 5, the moment at 5.5, the far end of
    # the full-span UDL, and the whole of the 4-5 segment
    # the support at 6, the load at 5, the moment at 5.5, the far end of the
    # full-span UDL, and BOTH ends of the 4-5 segment -- six, because an
    # entry is listed once per end that is off the beam
    assert kinds == ['distributed load', 'distributed load',
                     'distributed load', 'moment', 'point load',
                     'support'], strays
    assert app._entries_off_beam(6.0) == [], 'nothing is off a 6 m beam'


def test_deleting_the_strays_leaves_a_model_that_analyses(beam):
    app, root, box = beam
    _stray_model(app)
    app.len_var.set(3.0)
    app._apply_length(3.0, strays='delete')
    assert app.length == 3.0
    assert [s['x'] for s in app.supports] == [0.0]
    assert [p['x'] for p in app.point_loads] == [2.0]
    assert app.moments == []
    assert app._entries_off_beam() == []


def test_clamping_the_strays_keeps_them_on_the_beam(beam):
    app, root, box = beam
    _stray_model(app)
    app._apply_length(3.0, strays='clamp')
    assert app.length == 3.0
    assert [s['x'] for s in app.supports] == [0.0, 3.0]
    assert [p['x'] for p in app.point_loads] == [2.0, 3.0]
    assert app._entries_off_beam() == []


def test_clamping_drops_a_distributed_load_that_would_become_a_sliver(beam):
    """A segment entirely beyond the new end clamps to zero width, which
    carries no load at all -- a silent no-op row is exactly the kind of thing
    this finding is about, so it goes instead."""
    app, root, box = beam
    _stray_model(app)
    app._apply_length(3.0, strays='clamp')
    assert [(d['x1'], d['x2']) for d in app.dloads] == [(0.0, 3.0)]


def test_cancelling_changes_nothing(beam):
    app, root, box = beam
    _stray_model(app)
    before = ([dict(s) for s in app.supports], [dict(p) for p in app.point_loads])
    assert app._apply_length(3.0, strays='cancel') is False
    assert app.length == 6.0
    assert (app.supports, app.point_loads) == before


def test_set_length_asks_once_when_entries_would_be_stranded(beam):
    app, root, box = beam
    _stray_model(app)
    asked = []

    def fake_ask(strays):
        asked.append(len(strays))
        return 'delete'

    app._ask_stray_policy = fake_ask
    app.len_var.set(3.0)
    app._set_length()
    assert asked == [6], asked
    assert app.length == 3.0
    assert app._entries_off_beam() == []


def test_set_length_does_not_ask_when_nothing_is_stranded(beam):
    app, root, box = beam
    _stray_model(app)
    asked = []
    app._ask_stray_policy = lambda strays: asked.append(1) or 'delete'
    app.len_var.set(8.0)
    app._set_length()
    assert asked == []
    assert app.length == 8.0


def test_lengthening_the_beam_never_touches_the_entries(beam):
    app, root, box = beam
    _stray_model(app)
    before = [dict(p) for p in app.point_loads]
    app.len_var.set(10.0)
    app._set_length()
    assert app.point_loads == before


def test_a_stranded_row_is_marked_in_its_table(beam):
    """So it is visible before Analyze, not only in an error message."""
    app, root, box = beam
    _stray_model(app)
    app.length = 3.0
    app._refresh_tables()
    rows = app.pl_tree.get_children()
    tags = [app.pl_tree.item(r, 'tags') for r in rows]
    assert 'stray' not in tags[0], 'the load at x=2 is on the beam'
    assert 'stray' in tags[1], 'the load at x=5 is not, and must be marked'


def test_the_marks_clear_when_the_beam_is_long_enough_again(beam):
    app, root, box = beam
    _stray_model(app)
    app.length = 3.0
    app._refresh_tables()
    app.length = 6.0
    app._refresh_tables()
    for r in app.pl_tree.get_children():
        assert 'stray' not in app.pl_tree.item(r, 'tags')


def test_analyze_names_every_stranded_row_not_just_the_first(beam):
    app, root, box = beam
    _stray_model(app)
    # The route this really happens by: _import_excel sets the length and the
    # tables together, with no validation of either (see R-17).
    app.length = 3.0
    app.len_var.set(3.0)
    app._refresh_tables()
    app._analyze()
    text = box.text()
    assert app.result is None
    for station in ('5.00', '5.50', '6.00'):
        assert station in text, (station, text)


# ------------------------------- the dialog that asks about stranded rows

def _descendants(widget):
    out = []
    for child in widget.winfo_children():
        out.append(child)
        out.extend(_descendants(child))
    return out


def _open_dialogs(root):
    return [w for w in _descendants(root) if isinstance(w, tk.Toplevel)]


@pytest.mark.parametrize('button,expected', [
    ('Delete them', 'delete'),
    ('Move them onto the beam', 'clamp'),
    ('Cancel', 'cancel'),
])
def test_the_stray_dialog_returns_what_was_pressed(beam, button, expected):
    app, root, box = beam
    _stray_model(app)
    strays = app._entries_off_beam(3.0)
    app.length_pending = 3.0

    def press():
        dialogs = _open_dialogs(root)
        assert dialogs, 'no dialog appeared'
        buttons = [b for b in _descendants(dialogs[-1])
                   if isinstance(b, tk.Button)]
        for b in buttons:
            if b.cget('text') == button:
                b.invoke()
                return
        dialogs[-1].destroy()
        raise AssertionError(f'{button!r} not among '
                             f'{[b.cget("text") for b in buttons]}')

    root.after(150, press)
    root.after(5000, lambda: [d.destroy() for d in _open_dialogs(root)])
    assert app._ask_stray_policy(strays) == expected


def test_closing_the_stray_dialog_means_cancel(beam):
    """The safe default: dismissing the question must not delete the user's
    rows or move them."""
    app, root, box = beam
    _stray_model(app)
    strays = app._entries_off_beam(3.0)
    app.length_pending = 3.0
    root.after(150, lambda: [d.destroy() for d in _open_dialogs(root)])
    root.after(5000, lambda: [d.destroy() for d in _open_dialogs(root)])
    assert app._ask_stray_policy(strays) == 'cancel'


def test_the_stray_dialog_lists_the_entries_and_the_new_length(beam):
    app, root, box = beam
    _stray_model(app)
    strays = app._entries_off_beam(3.0)
    app.length_pending = 3.0
    seen = {}

    def read_then_close():
        dialogs = _open_dialogs(root)
        assert dialogs, 'no dialog appeared'
        seen['text'] = ' | '.join(
            w.cget('text') for w in _descendants(dialogs[-1])
            if isinstance(w, tk.Label))
        dialogs[-1].destroy()

    root.after(150, read_then_close)
    root.after(5000, lambda: [d.destroy() for d in _open_dialogs(root)])
    app._ask_stray_policy(strays)
    assert '3.00' in seen['text'], seen['text']
    assert 'support' in seen['text'] and 'moment' in seen['text'], seen['text']
