"""The unit selector, driven through the real Beam tab.

The property that makes this feature safe to have added late is that switching
conventions is PURELY cosmetic: it changes labels and displayed numbers and
never rewrites stored state. If that ever stops holding, a user who switches to
AISC and back would silently corrupt their model, and an exported workbook
would change meaning depending on which convention happened to be selected when
it was written. So the central test here is an equality on `_current_state()`
across a switch, not an assertion about any particular label.

The expected values are the standard equivalents (1 kip = 4448.22 N,
1 ft = 0.3048 m, 1 in^4 = 41.623 cm^4), not numbers read back out of units.py.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

tk = pytest.importorskip('tkinter')

import units
from apps.beam.beam_app import BeamApp


@pytest.fixture
def beam():
    units.set_current('cirsoc')
    try:
        root = tk.Tk()
    except tk.TclError:                       # pragma: no cover - headless CI
        pytest.skip('no display')
    root.geometry('1400x900')
    app = BeamApp(root)
    app.pack(fill='both', expand=True)
    root.update()
    app._load_example_overhang()
    app._analyze()
    root.update()
    try:
        yield app, root
    finally:
        units.set_current('cirsoc')
        try:
            root.destroy()
        except Exception:
            pass


def _norm(state):
    """Comparable snapshot of a tab's stored model."""
    import json
    return json.dumps(state, sort_keys=True, default=float)


@pytest.mark.parametrize('key', ['aisc', 'csa', 'eurocode', 'nbr'])
def test_switching_convention_never_rewrites_stored_state(beam, key):
    app, root = beam
    before = _norm(app._current_state())
    units.set_current(key)
    root.update()
    assert _norm(app._current_state()) == before, (
        f'switching to {key} changed the stored model')


def test_switching_there_and_back_is_a_no_op(beam):
    app, root = beam
    before = _norm(app._current_state())
    for k in ('aisc', 'csa', 'cirsoc'):
        units.set_current(k)
        root.update()
    assert _norm(app._current_state()) == before


def test_the_displayed_numbers_do_change(beam):
    """The other half of the property: cosmetic, but not inert."""
    app, root = beam
    length_si = app.len_var.get()
    units.set_current('aisc')
    root.update()
    assert app.len_var.get() != pytest.approx(length_si)
    # 10 m reads as 32.808 ft
    assert app.len_var.get() == pytest.approx(10.0 / 0.3048, rel=1e-6)


def test_section_properties_convert_to_the_us_customary_equivalents(beam):
    app, root = beam
    units.set_current('aisc')
    root.update()
    # 200 GPa is about 29 000 ksi; 8000 cm^4 is 192.2 in^4
    assert app.sec_vars['E'].get() == pytest.approx(29008.0, rel=2e-3)
    assert app.sec_vars['I'].get() == pytest.approx(8000.0 / 41.623, rel=2e-3)


def test_table_headings_follow_the_convention(beam):
    app, root = beam
    assert app.pl_tree.heading('P')['text'] == 'P (kN)'
    units.set_current('aisc')
    root.update()
    assert app.pl_tree.heading('P')['text'] == 'P (kip)'
    assert app.sup_tree.heading('x')['text'] == 'x (ft)'


def test_the_results_panel_is_written_in_the_chosen_convention(beam):
    app, root = beam
    text = app.res_text.get('1.0', 'end')
    assert 'kN' in text
    units.set_current('aisc')
    root.update()
    text = app.res_text.get('1.0', 'end')
    assert 'kip' in text and 'kN' not in text


def test_the_analysis_answer_is_the_same_whatever_the_convention(beam):
    """The selector is presentation only: the solver must return identical SI
    results either way. This is the assertion that would catch a conversion
    accidentally being applied to the model instead of to the label."""
    app, root = beam
    r_si = app.result.reaction_at(2.0)[0]
    units.set_current('aisc')
    root.update()
    app._analyze()
    root.update()
    assert app.result.reaction_at(2.0)[0] == pytest.approx(r_si, rel=1e-12)


def test_a_load_typed_in_us_customary_is_stored_in_kn(beam, monkeypatch):
    """A dialog entry goes back through the same conversion it was shown with,
    so 1 kip typed under AISC is stored as 4.44822 kN."""
    app, root = beam
    units.set_current('aisc')
    root.update()
    monkeypatch.setattr(app, '_ask', lambda *a, **k: {'x': 10.0, 'P': 1.0})
    app.point_loads.clear()
    app._add_pointload()
    assert app.point_loads[-1]['P'] == pytest.approx(4.4482216152605, rel=1e-9)
    # 10 ft is 3.048 m
    assert app.point_loads[-1]['x'] == pytest.approx(3.048, rel=1e-9)
