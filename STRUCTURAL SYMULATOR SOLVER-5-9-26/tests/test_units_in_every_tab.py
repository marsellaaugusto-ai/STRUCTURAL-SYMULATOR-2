"""The unit selector, driven through the other five real tabs.

`test_units_in_beam_tab.py` does this for the Beam tab, which was wired first
and by hand. This file covers the five that followed, and asserts the same
property on each: switching conventions is PURELY cosmetic. A tab may write
its numbers differently, but the model behind them must come back byte for
byte identical, or a user who tries AISC and switches back has silently
corrupted their work and an exported workbook has changed meaning.

The tabs do not all store the same units, and that is the point of the
`STORAGE_UNITS` declaration each one carries: the Beam and Cable tabs hold kN
and metres, the Truss tab holds plate yield in MPa, the Perforated Beam tab
holds mm and newtons throughout, and the Cable Web tab holds newtons. A single
assumed storage convention would put a Perforated Beam span out by a factor of
a thousand, so every expected value below is written as the published
equivalent (1 kip = 4448.22 N, 1 ft = 0.3048 m, 1 in^4 = 41.623 cm^4,
1 ksi = 6.894757 MPa) rather than read back out of units.py.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

tk = pytest.importorskip('tkinter')

import units


def _root():
    try:
        root = tk.Tk()
    except tk.TclError:                       # pragma: no cover - headless CI
        pytest.skip('no display')
    root.geometry('1400x900')
    return root


def _snapshot(app):
    """A comparable picture of the tab's stored model, whatever it calls it."""
    for name in ('_current_state', '_model_snapshot', '_gather_state',
                 '_snapshot'):
        if hasattr(app, name):
            return json.dumps(getattr(app, name)(), sort_keys=True, default=repr)
    raise AssertionError(f'{type(app).__name__} exposes no state to compare')


# ── the five tabs, each built and loaded with its own example ────────────────

@pytest.fixture
def truss():
    from apps.truss.truss_app import TrussApp
    units.set_current('cirsoc')
    root = _root()
    app = TrussApp(root)
    root.update()
    app._load_example()
    app._run_analysis()
    root.update()
    try:
        yield app, root
    finally:
        units.set_current('cirsoc')
        app.stop_units()
        try:
            root.destroy()
        except Exception:
            pass


@pytest.fixture
def arch():
    from apps.arch.arch_app import ArchApp
    units.set_current('cirsoc')
    root = _root()
    app = ArchApp(root)
    app.pack(fill='both', expand=True)
    root.update()
    app._load_example_two_hinged()
    app._analyze()
    root.update()
    try:
        yield app, root
    finally:
        units.set_current('cirsoc')
        app.stop_units()
        try:
            root.destroy()
        except Exception:
            pass


@pytest.fixture
def cable():
    from apps.cable.cable_app import CableApp
    units.set_current('cirsoc')
    root = _root()
    app = CableApp(root)
    app.pack(fill='both', expand=True)
    root.update()
    app._load_example_point()
    app._analyze()
    root.update()
    try:
        yield app, root
    finally:
        units.set_current('cirsoc')
        app.stop_units()
        try:
            root.destroy()
        except Exception:
            pass


@pytest.fixture
def perforated():
    from apps.perforated_beam.perforated_beam_app import PerforatedBeamApp
    units.set_current('cirsoc')
    root = _root()
    app = PerforatedBeamApp(root)
    app.pack(fill='both', expand=True)
    root.update()
    app._load_example()
    app._apply_widget_state()
    root.update()
    try:
        yield app, root
    finally:
        units.set_current('cirsoc')
        app.stop_units()
        try:
            root.destroy()
        except Exception:
            pass


@pytest.fixture
def cable_web():
    from apps.cable_web.cable_web_app import CableWebApp
    units.set_current('cirsoc')
    root = _root()
    app = CableWebApp(root)
    app.pack(fill='both', expand=True)
    root.update()
    try:
        yield app, root
    finally:
        units.set_current('cirsoc')
        app.stop_units()
        try:
            root.destroy()
        except Exception:
            pass


ALL_TABS = ('truss', 'arch', 'cable', 'perforated', 'cable_web')


# ── the property every tab has to hold ───────────────────────────────────────

@pytest.mark.parametrize('tab', ALL_TABS)
@pytest.mark.parametrize('key', ['aisc', 'csa', 'eurocode', 'nbr'])
def test_switching_convention_never_rewrites_stored_state(request, tab, key):
    app, root = request.getfixturevalue(tab)
    before = _snapshot(app)
    units.set_current(key)
    root.update()
    assert _snapshot(app) == before, (
        f'switching the {tab} tab to {key} changed its stored model')


@pytest.mark.parametrize('tab', ALL_TABS)
def test_switching_there_and_back_is_a_no_op(request, tab):
    """The round trip is the one a user actually makes, and the one a rounded
    display would quietly break: 20 m shown as 65.6168 ft and read back is
    20.00000064 m unless the exact figure is kept."""
    app, root = request.getfixturevalue(tab)
    before = _snapshot(app)
    for k in ('aisc', 'csa', 'cirsoc'):
        units.set_current(k)
        root.update()
    assert _snapshot(app) == before


@pytest.mark.parametrize('tab', ALL_TABS)
def test_every_tab_declares_what_it_stores(request, tab):
    """A tab that inherits the default storage without meaning to is the one
    way this layer could corrupt data, so the declaration is asserted rather
    than assumed."""
    app, _root = request.getfixturevalue(tab)
    storage = app.STORAGE_UNITS
    for quantity in units.QUANTITIES:
        assert storage.label(quantity), f'{tab}: no storage unit for {quantity}'


# ── that the numbers really do change, and to the right numbers ──────────────

def test_truss_shows_us_customary_material_properties(truss):
    app, root = truss
    assert app.mat_E.get() == pytest.approx(200.0)          # GPa
    units.set_current('aisc')
    root.update()
    # 200 GPa is about 29 000 ksi; 10 cm^2 is 1.55 in^2
    assert app.mat_E.get() == pytest.approx(29008.0, rel=2e-3)
    assert app.mat_A.get() == pytest.approx(10.0 / 6.4516, rel=1e-4)


def test_truss_plate_details_stay_in_millimetres_under_the_si_codes(truss):
    """A plate thickness is written in mm on a CIRSOC or Eurocode drawing,
    never in cm, even though a fibre distance on the same drawing is in cm.
    They are the same physical quantity and a different unit, which is why
    `detail_length` exists separately from `section_length`."""
    app, root = truss
    for key in ('cirsoc', 'eurocode', 'nbr', 'csa'):
        units.set_current(key)
        root.update()
        assert app.plate_t.get() == pytest.approx(8.0), key
        assert app.bolt_pitch.get() == pytest.approx(60.0), key
    units.set_current('aisc')
    root.update()
    assert app.plate_t.get() == pytest.approx(8.0 / 25.4, rel=1e-4)


def test_truss_results_are_written_in_the_chosen_convention(truss):
    app, root = truss
    assert 'kN' in app.res_var.get()
    units.set_current('aisc')
    root.update()
    assert 'kip' in app.res_var.get() and 'kN' not in app.res_var.get()


def test_arch_section_panel_converts(arch):
    app, root = arch
    units.set_current('aisc')
    root.update()
    # 20000 cm^4 is 480.5 in^4; a 20 cm fibre distance is 7.874 in
    assert app.sec_vars['I'].get() == pytest.approx(20000.0 / 41.623, rel=2e-3)
    assert app.sec_vars['c_top'].get() == pytest.approx(20.0 / 2.54, rel=1e-4)


def test_arch_answer_is_the_same_whatever_the_convention(arch):
    """The assertion that would catch a conversion applied to the model
    instead of to the label."""
    app, root = arch
    H_si = app.result.reaction(0)[0]
    units.set_current('aisc')
    root.update()
    app._analyze()
    root.update()
    assert app.result.reaction(0)[0] == pytest.approx(H_si, rel=1e-12)


def test_cable_headings_and_results_follow_the_convention(cable):
    app, root = cable
    assert app.pl_tree.heading('P')['text'] == 'P (kN)'
    units.set_current('aisc')
    root.update()
    assert app.pl_tree.heading('P')['text'] == 'P (kip)'
    assert 'kip' in app.res_text.get('1.0', 'end')


def test_cable_answer_is_the_same_whatever_the_convention(cable):
    app, root = cable
    H_si = app.result.H
    units.set_current('aisc')
    root.update()
    app._analyze()
    root.update()
    assert app.result.H == pytest.approx(H_si, rel=1e-12)


def test_perforated_beam_span_reads_in_metres_not_millimetres(perforated):
    """This tab stores mm. Shown in the app's own SI convention that is
    metres, and under AISC feet -- an 8000 in the box would mean the storage
    number had leaked through unconverted."""
    app, root = perforated
    assert float(app.len_var.get()) == pytest.approx(8.0)
    units.set_current('aisc')
    root.update()
    assert float(app.len_var.get()) == pytest.approx(8.0 / 0.3048, rel=1e-5)


def test_perforated_beam_material_converts(perforated):
    app, root = perforated
    assert float(app.fy_var.get()) == pytest.approx(250.0)      # MPa
    assert float(app.e_var.get()) == pytest.approx(200.0)       # GPa, from MPa
    units.set_current('aisc')
    root.update()
    # 250 MPa is 36.26 ksi; 200 GPa is about 29 000 ksi
    assert float(app.fy_var.get()) == pytest.approx(36.2594, rel=1e-4)
    assert float(app.e_var.get()) == pytest.approx(29008.0, rel=2e-3)


def test_perforated_beam_opening_diameters_stay_in_millimetres(perforated):
    app, root = perforated
    assert float(app.p1_var.get()) == pytest.approx(250.0)
    units.set_current('eurocode')
    root.update()
    assert float(app.p1_var.get()) == pytest.approx(250.0)
    units.set_current('aisc')
    root.update()
    assert float(app.p1_var.get()) == pytest.approx(250.0 / 25.4, rel=1e-4)


def test_cable_web_stores_newtons_not_kilonewtons(cable_web):
    """The one tab whose force unit is the newton. Reading its storage as kN
    would show every tension a thousand times too small."""
    app, _root = cable_web
    assert app.STORAGE_UNITS.label('force') == 'N'
    assert app.STORAGE_UNITS.to_si('force', 1000.0) == pytest.approx(1000.0)
    # and 1000 N is 1 kN under the app's own SI convention
    assert app.show('force', 1000.0) == pytest.approx(1.0)
    units.set_current('aisc')
    assert app.show('force', 4448.2216152605) == pytest.approx(1.0, rel=1e-9)


def test_a_tab_stops_listening_once_it_is_gone():
    """Hundreds of tabs are built and destroyed across this suite. A listener
    still holding a dead widget would be called on every switch for the rest
    of the session, which is how a passing suite starts leaking time."""
    from apps.cable.cable_app import CableApp
    units.set_current('cirsoc')
    root = _root()
    app = CableApp(root)
    app.pack()
    root.update()
    before = len(units._listeners)
    root.destroy()
    units.set_current('aisc')       # the tab is gone; this must clean it up
    units.set_current('cirsoc')
    assert len(units._listeners) < before
