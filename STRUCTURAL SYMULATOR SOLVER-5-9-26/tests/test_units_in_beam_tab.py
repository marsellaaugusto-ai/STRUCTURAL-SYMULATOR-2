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


# ------------------------------------------- one implementation of all this

def test_the_tab_uses_the_shared_units_machinery(beam):
    """R-9. `common.UnitsMixin` exists BECAUSE of this tab: its docstring says
    the Beam tab was wired to units.py by hand first and the machinery was
    then extracted so it would not be written six times. Arch, Cable Web and
    Stereo moved onto it; Beam kept the original copy, so there were two
    implementations of one idea -- which is how two tabs end up disagreeing
    about what a kip is (MANIFESTO s3j).
    """
    from common import UnitsMixin
    app, root = beam
    assert isinstance(app, UnitsMixin)
    for name in ('_shown', '_stored', '_u', 'show', 'store'):
        assert getattr(type(app), name) is getattr(UnitsMixin, name), (
            f'BeamApp still carries its own {name}')


def test_the_section_fields_are_registered_with_the_mixin(beam):
    app, root = beam
    for key in ('E', 'I', 'c', 'A', 'allow_bend', 'allow_shear'):
        assert app._unit_rec(app.sec_vars[key]) is not None, key
    assert app._unit_rec(app.len_var) is not None


def test_a_registered_box_keeps_its_exact_stored_value_across_a_switch(beam):
    """What `unit_value` buys over re-reading the displayed number: the box is
    rounded to stay readable, so it cannot be the authoritative copy."""
    app, root = beam
    app.set_unit_value(app.len_var, 7.3)
    for key in ('aisc', 'csa', 'eurocode', 'cirsoc'):
        units.set_current(key)
        root.update()
    assert app.unit_value(app.len_var) == 7.3
    assert app._current_state()['length'] == 7.3


# --------------------------------------------- labels that name a unit

def _labels(widget):
    out = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            out.append(child.cget('text'))
        out.extend(_labels(child))
    return out


@pytest.mark.parametrize('heading,quantity', [
    ('POINT LOADS', 'force'),
    ('POINT MOMENTS', 'moment'),
    ('DISTRIBUTED LOADS', 'line_load'),
])
def test_a_panel_heading_names_the_selected_unit(beam, heading, quantity):
    """These three spelled their unit out in SI and never repainted: under
    AISC the panel said 'POINT LOADS (+down, kN)' above a table of kip."""
    app, root = beam
    for key in ('cirsoc', 'aisc'):
        units.set_current(key)
        root.update()
        want = units.label(quantity)
        line = [t for t in _labels(app) if t.startswith(heading)]
        assert line, f'{heading} heading not found'
        assert want in line[0], (key, line[0])


def test_the_length_label_names_the_selected_unit(beam):
    app, root = beam
    units.set_current('aisc')
    root.update()
    assert any('Beam length (ft)' in t for t in _labels(app)), _labels(app)


def test_the_section_labels_name_the_selected_unit(beam):
    app, root = beam
    units.set_current('aisc')
    root.update()
    joined = ' | '.join(_labels(app))
    assert 'E (ksi)' in joined, joined
    assert 'in4' in joined.replace('⁴', '4') or 'in^4' in joined, joined


def test_the_distributed_load_columns_name_their_units(beam):
    """They read a bare 'x1 x2 w1 w2' -- no unit in any convention."""
    app, root = beam
    for key, length, load in (('cirsoc', 'm', 'kN/m'), ('aisc', 'ft', 'kip/ft')):
        units.set_current(key)
        root.update()
        assert length in app.dl_tree.heading('x1')['text'], key
        assert load in app.dl_tree.heading('w1')['text'], key
        assert load in app.dl_tree.heading('w2')['text'], key
