"""units.py: every conversion pinned against a published equivalent.

A unit table is exactly the kind of code that looks right and is not. The first
draft of `units.py` had Pa -> ksi out by a factor of 1000, which would have
printed every AISC stress a thousand times too large while every other number
on the screen stayed correct -- the sort of defect that survives casual review
because nothing crashes and most of the interface still looks fine.

So the numbers below are not copied from the module. They are the standard
equivalents an engineer would look up, and the round-trip tests check the
inverse independently of them.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import units


@pytest.fixture(autouse=True)
def _restore_default():
    """Never leave a switched convention behind for the next test."""
    before = units.current().key
    yield
    units.set_current(before)


def _close(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-30)


# ------------------------------------------------------------------ SI side

def test_si_force_and_moment():
    s = units.SYSTEMS['cirsoc']
    assert _close(s.from_si('force', 1000.0), 1.0)            # 1 kN = 1000 N
    assert _close(s.from_si('moment', 1000.0), 1.0)           # 1 kN.m = 1000 N.m
    assert _close(s.from_si('line_load', 1000.0), 1.0)        # 1 kN/m = 1000 N/m


def test_si_stress_and_modulus():
    s = units.SYSTEMS['cirsoc']
    assert _close(s.from_si('stress', 1e6), 1.0)              # 1 MPa = 1e6 Pa
    assert _close(s.from_si('modulus', 200e9), 200.0)         # steel E = 200 GPa


def test_si_section_properties():
    cirsoc = units.SYSTEMS['cirsoc']
    csa = units.SYSTEMS['csa']
    assert _close(cirsoc.from_si('area', 1e-4), 1.0)          # 1 cm^2 = 1e-4 m^2
    assert _close(cirsoc.from_si('inertia', 1e-8), 1.0)       # 1 cm^4 = 1e-8 m^4
    assert _close(csa.from_si('area', 1e-6), 1.0)             # 1 mm^2 = 1e-6 m^2
    assert _close(csa.from_si('inertia', 1e-12), 1.0)         # 1 mm^4 = 1e-12 m^4


def test_the_app_s_own_kn_per_cm2_is_ten_mpa():
    """The Beam/Arch/Cable allowables are entered in kN/cm^2, and 1 kN/cm^2 is
    10 MPa -- the factor that would silently be off by ten if it were guessed."""
    assert _close(units._KN_CM2, units._MPA / 10.0)


# ---------------------------------------------------------- US customary side

def test_aisc_force():
    s = units.SYSTEMS['aisc']
    assert _close(s.from_si('force', 4448.2216152605), 1.0)   # 1 kip
    assert _close(s.to_si('force', 1.0), 4448.2216152605)


def test_aisc_length():
    s = units.SYSTEMS['aisc']
    assert _close(s.from_si('length', 0.3048), 1.0)           # 1 ft
    assert _close(s.to_si('length', 1.0), 0.3048)
    assert _close(s.from_si('deflection', 0.0254), 1.0)       # 1 in


def test_aisc_stress_is_not_out_by_a_thousand():
    """1 ksi = 6 894 757.29 Pa. The regression this whole module exists for."""
    s = units.SYSTEMS['aisc']
    assert _close(s.to_si('stress', 1.0), 6894757.293168, tol=1e-9)
    assert _close(s.from_si('stress', 6894757.293168), 1.0)
    # steel: 29 000 ksi is 199.9 GPa, the AISC value for the same material
    # whose SI value the app already uses as 200 GPa
    assert abs(s.to_si('modulus', 29000.0) / 1e9 - 200.0) < 0.15


def test_aisc_moment_and_line_load():
    s = units.SYSTEMS['aisc']
    assert _close(s.to_si('moment', 1.0), 1355.8179483314004)     # 1 kip.ft
    assert _close(s.to_si('line_load', 1.0), 14593.902937206364)  # 1 kip/ft


def test_aisc_section_properties():
    s = units.SYSTEMS['aisc']
    assert _close(s.to_si('area', 1.0), 0.00064516)               # 1 in^2
    assert _close(s.to_si('inertia', 1.0), 0.0254 ** 4)           # 1 in^4


def test_shell_quantities_si():
    """The four quantities added for the Shell tab, SI side."""
    cirsoc, csa = units.SYSTEMS['cirsoc'], units.SYSTEMS['csa']
    assert _close(cirsoc.from_si('area_load', 1000.0), 1.0)           # 1 kN/m²
    assert _close(cirsoc.from_si('moment_per_length', 1000.0), 1.0)   # 1 kN·m/m
    assert _close(cirsoc.from_si('steel_per_length', 1e-4), 1.0)      # 1 cm²/m
    assert _close(csa.from_si('steel_per_length', 1e-6), 1.0)         # 1 mm²/m
    assert _close(cirsoc.from_si('unit_weight', 25000.0), 25.0)       # concrete


def test_shell_quantities_us_customary_against_published_equivalents():
    """Pinned against published equivalents, not against the module:
    1 psf = 47.880 259 Pa, 1 pcf = 157.087 5 N/m³, 1 in²/ft = 2116.67 mm²/m,
    1 kip·ft/ft = 4.448 222 kN·m/m."""
    s = units.SYSTEMS['aisc']
    assert _close(s.to_si('area_load', 1.0), 47.880258980, tol=1e-8)
    assert _close(s.to_si('unit_weight', 1.0), 157.08746384, tol=1e-8)
    assert _close(s.to_si('steel_per_length', 1.0), 2116.6666667e-6, tol=1e-8)
    assert _close(s.to_si('moment_per_length', 1.0), 4448.2216152605)
    # 150 pcf normal-weight concrete is about 23.6 kN/m³
    assert abs(s.to_si('unit_weight', 150.0) / 1e3 - 23.56) < 0.01


# -------------------------------------------------------------- round trips

@pytest.mark.parametrize('key', list(units.SYSTEMS))
@pytest.mark.parametrize('quantity', units.QUANTITIES)
def test_every_conversion_round_trips(key, quantity):
    s = units.SYSTEMS[key]
    for v in (0.0, 1.0, -3.5, 1234.5678, 1e-9, 1e9):
        assert _close(s.to_si(quantity, s.from_si(quantity, v)), v, tol=1e-12)


@pytest.mark.parametrize('key', list(units.SYSTEMS))
def test_every_system_defines_every_quantity_with_a_label(key):
    s = units.SYSTEMS[key]
    for q in units.QUANTITIES:
        assert s.label(q), f'{key}: {q} has no label'


def test_a_missing_quantity_is_refused_at_construction():
    with pytest.raises(ValueError):
        units.UnitSystem('x', 'X', '', length=units.Unit('m', 1.0))


def test_an_unknown_quantity_names_what_was_expected():
    with pytest.raises(KeyError) as e:
        units.SYSTEMS['cirsoc']['torque']
    assert 'torque' in str(e.value)


# ------------------------------------------------------------ the live switch

def test_switching_changes_what_the_helpers_report():
    units.set_current('cirsoc')
    assert units.label('force') == 'kN'
    assert _close(units.from_si('force', 1000.0), 1.0)
    units.set_current('aisc')
    assert units.label('force') == 'kip'
    assert _close(units.from_si('force', 4448.2216152605), 1.0)


def test_listeners_are_told_which_system_was_chosen():
    seen = []
    fn = units.on_change(lambda s: seen.append(s.key))
    try:
        units.set_current('aisc')
        units.set_current('csa')
        assert seen == ['aisc', 'csa']
    finally:
        units.off_change(fn)


def test_one_failing_listener_does_not_stop_the_others():
    """A half-converted interface -- some panels in kip, others in kN -- is
    worse than one panel failing to repaint, so a raising listener is isolated."""
    seen = []

    def bad(_s):
        raise RuntimeError('boom')

    good = units.on_change(lambda s: seen.append(s.key))
    units.on_change(bad)
    try:
        units.set_current('aisc')
        assert seen == ['aisc']
    finally:
        units.off_change(good)
        units.off_change(bad)


def test_an_unknown_system_is_refused_and_the_current_one_survives():
    units.set_current('cirsoc')
    with pytest.raises(KeyError):
        units.set_current('imperial-ish')
    assert units.current().key == 'cirsoc'


def test_order_lists_every_system_once():
    assert sorted(units.ORDER) == sorted(units.SYSTEMS)
    assert units.DEFAULT_SYSTEM in units.SYSTEMS


def test_fmt_writes_value_and_label():
    units.set_current('cirsoc')
    assert units.fmt('force', 12500.0, digits=2) == '12.50 kN'
    assert units.fmt('force', 12500.0, digits=1, with_label=False) == '12.5'


def test_the_four_si_profiles_agree_on_force_and_length():
    """They are all SI; if these ever diverge it is a mistake, not a code
    difference. Only AISC is a different system."""
    si = [units.SYSTEMS[k] for k in ('cirsoc', 'eurocode', 'nbr', 'csa')]
    for s in si[1:]:
        assert s.label('force') == si[0].label('force')
        assert s.label('length') == si[0].label('length')
        assert _close(s['force'].factor, si[0]['force'].factor)
    assert units.SYSTEMS['aisc'].label('force') != si[0].label('force')


# ------------------------------------------- the storage <-> display bridge

def test_storage_is_what_the_tabs_have_always_held():
    """kN, m, cm^2, cm^4, GPa -- and kN/cm^2 for allowables, which is the one
    place storage differs from the CIRSOC display profile."""
    s = units.STORAGE
    assert s.label('force') == 'kN'
    assert s.label('length') == 'm'
    assert s.label('area') == 'cm²'
    assert s.label('inertia') == 'cm⁴'
    assert s.label('modulus') == 'GPa'
    assert s.label('stress') == 'kN/cm²'
    assert units.SYSTEMS['cirsoc'].label('stress') == 'MPa'


def test_storage_values_are_unchanged_when_shown_in_the_matching_system():
    """Under CIRSOC everything except stress is already the storage unit, so
    the displayed number must be the stored number untouched."""
    units.set_current('cirsoc')
    for q in ('length', 'force', 'moment', 'line_load', 'area', 'inertia',
              'modulus', 'deflection'):
        assert _close(units.to_display(q, 12.5), 12.5), q
    # stress is the exception: 1.6 kN/cm^2 stored is 16 MPa shown
    assert _close(units.to_display('stress', 1.6), 16.0)


def test_a_stored_value_reads_correctly_in_aisc():
    units.set_current('aisc')
    assert _close(units.to_display('force', 1.0), 1000.0 / 4448.2216152605)
    assert _close(units.to_display('length', 1.0), 1.0 / 0.3048)
    # 200 GPa stored reads as about 29 000 ksi
    assert abs(units.to_display('modulus', 200.0) - 29008.0) < 5.0


@pytest.mark.parametrize('key', list(units.SYSTEMS))
@pytest.mark.parametrize('quantity', units.QUANTITIES)
def test_display_round_trips_back_to_the_same_stored_value(key, quantity):
    """Switching conventions must never rewrite stored state: whatever is
    shown, typing it back yields the value the tab already held."""
    units.set_current(key)
    for stored in (0.0, 1.0, -3.5, 1234.5678):
        assert _close(units.from_display(quantity, units.to_display(quantity, stored)),
                      stored, tol=1e-12)


def test_show_formats_a_stored_value():
    units.set_current('cirsoc')
    assert units.show('force', 12.5, digits=2) == '12.50'
    assert units.show('force', 12.5, digits=1, with_label=True) == '12.5 kN'
