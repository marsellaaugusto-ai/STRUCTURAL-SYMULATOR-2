"""The Beam tab's q(x) loads: units and validation (R-4).

The non-uniform load was the one entry path in this tab wired to nothing. Its
dialog hard-coded "(m)" in its labels and stored what was typed RAW, with no
`_stored` conversion -- while `_refresh_tables` converts those same columns
for display, so under AISC the dialog offered a default of `6.0` labelled "m"
next to a table reading `19.69 ft`, and a user who typed `20` meaning feet got
a 20-metre load. It also skipped the `_on_beam` check every other load type
got in the B-5 fix, and `_analyze` silently CLAMPED an off-beam domain instead
of refusing it.

The expression itself is a different question, and the answer here is the one
the Arch tab already uses: a stored q(x) string is always in the app's storage
units (kN/m, with x and L in m) and the dialog says so in those words, whatever
the Units selector is set to. It cannot follow the selector, because the
expression is stored verbatim: if its meaning depended on which convention
happened to be selected, switching convention would silently change the load --
exactly the property units.py exists to guarantee can never happen.

The dialog is driven rather than replaced: it is a modal Toplevel, so these
tests find it, type into its real Entry widgets and press its real OK button.
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
    app.len_var.set(app._shown('x', 6.0))
    app.supports = [{'x': 0.0, 'type': 'pin'}, {'x': 6.0, 'type': 'roller'}]
    app._refresh_tables()
    try:
        yield app, root, box
    finally:
        units.set_current('cirsoc')
        try:
            root.destroy()
        except Exception:
            pass


def _descendants(widget):
    out = []
    for child in widget.winfo_children():
        out.append(child)
        out.extend(_descendants(child))
    return out


def _add_nonuniform(app, root, expr=None, x1=None, x2=None, read_only=False):
    """Drive the real Add dialog. Returns what its labels said.

    Each field is left alone when its argument is None, so a test can check
    the defaults the dialog offers as well as what it does with new input.
    """
    seen = {}

    def fill():
        dialogs = [w for w in _descendants(root) if isinstance(w, tk.Toplevel)]
        assert dialogs, 'the Add dialog did not open'
        dlg = dialogs[-1]
        seen['labels'] = ' | '.join(w.cget('text') for w in _descendants(dlg)
                                    if isinstance(w, tk.Label))
        entries = {}
        for w in _descendants(dlg):
            if isinstance(w, tk.Entry):
                entries[w.grid_info()['row']] = w
        rows = sorted(entries)
        seen['defaults'] = [entries[r].get() for r in rows]
        if not read_only:
            for row, value in zip(rows, (expr, x1, x2)):
                if value is None:
                    continue
                entries[row].delete(0, 'end')
                entries[row].insert(0, str(value))
        for b in _descendants(dlg):
            if isinstance(b, tk.Button) and b.cget('text') == 'OK':
                if read_only:
                    dlg.destroy()
                else:
                    b.invoke()
                return
        dlg.destroy()
        raise AssertionError('no OK button')

    root.after(150, fill)
    root.after(5000, lambda: [d.destroy() for d in _descendants(root)
                              if isinstance(d, tk.Toplevel)])
    app._add_nonuniform_load()
    return seen


# ------------------------------------------------------- the stored domain

def test_the_domain_is_stored_in_metres_whatever_is_selected(beam):
    """The property: the same physical load, entered under two conventions,
    must come out as the same stored model."""
    app, root, box = beam
    _add_nonuniform(app, root, expr='10', x1=0, x2=6)
    assert app.nonuniform_loads == [{'expr': '10', 'x1': 0.0, 'x2': 6.0}]

    app.nonuniform_loads = []
    units.set_current('aisc')
    root.update()
    # 6 m is 19.685 ft; entered in feet, it must store as 6 m again
    _add_nonuniform(app, root, expr='10', x1=0, x2=6.0 / 0.3048)
    stored = app.nonuniform_loads[0]
    assert stored['x1'] == pytest.approx(0.0)
    assert stored['x2'] == pytest.approx(6.0, rel=1e-9), stored


def test_the_dialog_labels_the_domain_in_the_selected_unit(beam):
    app, root, box = beam
    units.set_current('aisc')
    root.update()
    seen = _add_nonuniform(app, root, read_only=True)
    assert 'ft' in seen['labels'], seen['labels']
    assert '(m)' not in seen['labels'], seen['labels']


def test_the_dialog_offers_the_beam_end_as_a_default_in_display_units(beam):
    app, root, box = beam
    units.set_current('aisc')
    root.update()
    seen = _add_nonuniform(app, root, read_only=True)
    # x2 defaults to the far end of the beam: 19.685 ft, not 6
    assert float(seen['defaults'][2]) == pytest.approx(6.0 / 0.3048, rel=1e-6)


def test_switching_convention_does_not_rewrite_a_stored_q_load(beam):
    app, root, box = beam
    _add_nonuniform(app, root, expr='10*sin(pi*x/L)', x1=1, x2=5)
    before = [dict(d) for d in app.nonuniform_loads]
    for key in ('aisc', 'csa', 'cirsoc'):
        units.set_current(key)
        root.update()
    assert app.nonuniform_loads == before


def test_the_table_and_the_dialog_agree_about_the_domain(beam):
    """The visible symptom of the bug: the row said one number and the dialog
    that made it said another."""
    app, root, box = beam
    units.set_current('aisc')
    root.update()
    _add_nonuniform(app, root, expr='10', x1=0, x2=10)
    row = app.ndl_tree.item(app.ndl_tree.get_children()[0], 'values')
    assert float(row[2]) == pytest.approx(10.0, rel=1e-6), row


# ------------------------------------------------- the expression's own unit

def test_the_dialog_states_the_expression_is_in_storage_units(beam):
    """A stored expression cannot follow the selector, so the dialog has to say
    what it IS -- in both conventions, including the one where the stations
    beside it read in feet."""
    app, root, box = beam
    for key, station_unit in (('cirsoc', 'm'), ('aisc', 'ft')):
        units.set_current(key)
        root.update()
        seen = _add_nonuniform(app, root, read_only=True)
        labels = seen['labels']
        assert units.STORAGE.label('line_load') in labels, labels
        assert station_unit in labels, labels
        app.nonuniform_loads = []


def test_the_panel_heading_states_it_too(beam):
    app, root, box = beam
    units.set_current('aisc')
    root.update()
    headings = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Label):
                headings.append(c.cget('text'))
            walk(c)

    walk(app)
    joined = ' | '.join(headings)
    assert units.STORAGE.label('line_load') in joined, joined


def test_a_q_load_is_read_as_storage_units_under_any_convention(beam):
    """q(x) = 10 over the whole span is 10 kN/m, so each reaction is 30 kN on a
    6 m beam -- the same answer with AISC selected, since the expression means
    kN/m either way."""
    app, root, box = beam
    results = {}
    for key in ('cirsoc', 'aisc'):
        units.set_current(key)
        root.update()
        app.nonuniform_loads = [{'expr': '10', 'x1': 0.0, 'x2': 6.0}]
        app._refresh_tables()
        app._analyze()
        assert app.result is not None, box.text()
        results[key] = app.result.equilibrium()['applied_down']
    assert results['cirsoc'] == pytest.approx(60e3, rel=1e-6)
    assert results['aisc'] == pytest.approx(results['cirsoc'], rel=1e-12)


# -------------------------------------------------------- on the beam or not

def test_a_domain_off_the_beam_is_refused_not_clamped(beam):
    """Every other load type refuses an off-beam station (B-5). This one
    silently clamped it in _analyze, so a load entered over 0-99 m on a 6 m
    beam became a load over 0-6 m and nothing said so."""
    app, root, box = beam
    _add_nonuniform(app, root, expr='10', x1=0, x2=99)
    assert app.nonuniform_loads == [], 'the row must not be added'
    assert box.shown, 'and the user must be told'
    assert '99' in box.text(), box.text()


def test_the_beam_ends_are_still_a_valid_domain(beam):
    app, root, box = beam
    _add_nonuniform(app, root, expr='10', x1=0, x2=6)
    assert len(app.nonuniform_loads) == 1
    assert not box.shown, box.text()


def test_a_reversed_domain_is_normalised(beam):
    app, root, box = beam
    _add_nonuniform(app, root, expr='10', x1=5, x2=1)
    stored = app.nonuniform_loads[0]
    assert (stored['x1'], stored['x2']) == (1.0, 5.0), stored


def test_an_analyze_no_longer_clamps_a_stale_domain(beam):
    """An imported workbook can still carry one, and it must be reported with
    every other problem rather than quietly trimmed (R-5/R-7 route)."""
    app, root, box = beam
    app.nonuniform_loads = [{'expr': '10', 'x1': 0.0, 'x2': 99.0}]
    app._refresh_tables()
    app._analyze()
    assert app.result is None
    assert '99' in box.text(), box.text()


def test_a_bad_expression_is_still_refused_by_the_dialog(beam):
    app, root, box = beam
    _add_nonuniform(app, root, expr='10*wibble(x)', x1=0, x2=6)
    assert app.nonuniform_loads == []
    assert box.shown


def test_a_non_numeric_station_is_refused_by_name(beam):
    app, root, box = beam
    _add_nonuniform(app, root, expr='10', x1='abc', x2=6)
    assert app.nonuniform_loads == []
    assert 'abc' in box.text(), box.text()


# ------------------------------------------------------------ the schematic

def test_the_schematic_labels_a_q_load_with_its_unit(beam):
    """The load picture is the check made before pressing Analyze, and the
    q(x) label carried no unit at all."""
    app, root, box = beam
    app.nonuniform_loads = [{'expr': '10*sin(pi*x/L)', 'x1': 0.0, 'x2': 6.0}]
    app._refresh_tables()
    root.update()
    texts = [app.schem.itemcget(i, 'text') for i in app.schem.find_all()
             if app.schem.type(i) == 'text']
    label = [t for t in texts if 'q(x)' in t]
    assert label, texts
    assert units.STORAGE.label('line_load') in label[0], label


# ------------------------------------- a station at the beam's own end
#
# Found while fixing R-4, and it was never specific to q(x) loads: the tab's
# own on-beam check compared EXACTLY, while BeamModel's allows a tolerance.
# A beam end does not survive a round trip through a non-metric convention
# exactly -- 6 m is 19.68503937007874 ft, which converts back to
# 6.000000000000001 m -- so every Add dialog refused a station at the far end
# of the beam under AISC, with a message quoting numbers in two different
# units at once.

@pytest.mark.parametrize('key', ['aisc', 'cirsoc', 'csa'])
def test_a_station_at_the_far_end_is_accepted_in_every_convention(beam, key):
    app, root, box = beam
    units.set_current(key)
    root.update()
    far_end = app._shown('x', 6.0)
    assert app._on_beam({'x': app._stored('x', far_end)}, 'x'), box.text()


def test_the_far_end_is_stored_as_the_end_and_not_a_hair_beyond_it(beam):
    """So the stored model, and the workbook written from it, hold 6.0."""
    app, root, box = beam
    units.set_current('aisc')
    root.update()
    r = {'x': app._stored('x', 6.0 / 0.3048)}
    assert r['x'] != 6.0, 'the round trip really does overshoot'
    app._on_beam(r, 'x')
    assert r['x'] == 6.0


def test_a_station_genuinely_past_the_end_is_still_refused(beam):
    """The tolerance must not become a licence."""
    app, root, box = beam
    assert not app._on_beam({'x': 6.001}, 'x')
    assert not app._on_beam({'x': -0.001}, 'x')


def test_the_off_the_beam_message_is_written_in_the_selected_unit(beam):
    app, root, box = beam
    units.set_current('aisc')
    root.update()
    app._on_beam({'x': 30.0}, 'x')          # 30 m, well past a 6 m beam
    text = box.text()
    assert 'ft' in text, text
    assert ' m ' not in text and 'm.' not in text, text
    assert '98.4' in text, text             # 30 m read in feet
