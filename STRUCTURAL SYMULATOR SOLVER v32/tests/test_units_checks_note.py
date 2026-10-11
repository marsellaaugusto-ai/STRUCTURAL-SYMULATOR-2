"""The unit selector is named after design codes; say which one the CHECKS
come from.

Each entry really is the convention its code tabulates in, so the selector
is honest about units. It was silent about strength: the resistance
factors, nominal strengths and weld rules every tab applies come from
`cirsoc_301.py` whichever entry is picked, so choosing "AISC 360 (US
customary)" changed kN to kip and nothing else. A student could reasonably
have read the selector as switching codes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import units


@pytest.fixture(autouse=True)
def _restore():
    before = units.current().key
    yield
    units.set_current(before)


def test_the_code_the_checks_use_is_named_in_one_place():
    assert units.CHECKS_CODE.startswith('CIRSOC 301')
    import cirsoc_301
    assert cirsoc_301.CIRSOC_301 is not None, (
        'CHECKS_CODE names a code object that must exist')


def test_no_caveat_when_the_convention_and_the_checks_agree():
    units.set_current('cirsoc')
    assert units.checks_note() is None, (
        'the bar should stay quiet when the chosen convention IS the code '
        'the checks come from')


@pytest.mark.parametrize('key', ('eurocode', 'nbr', 'csa', 'aisc'))
def test_every_other_convention_says_whose_factors_are_being_used(key):
    units.set_current(key)
    note = units.checks_note()
    assert note, f'{key} gives no caveat'
    assert units.CHECKS_CODE in note
    assert units.SYSTEMS[key].name in note, (
        'the caveat should name the convention the reader picked, so it is '
        'clear which half of the selector is doing what')


def test_the_caveat_follows_the_selection():
    units.set_current('aisc')
    assert 'AISC' in units.checks_note()
    units.set_current('eurocode')
    assert 'Eurocode' in units.checks_note()
    units.set_current('cirsoc')
    assert units.checks_note() is None


def test_every_selectable_system_is_covered():
    """No entry may fall through: either it is native to the checks, or it
    gets a caveat."""
    for key in units.ORDER:
        units.set_current(key)
        native = key in units.CHECKS_NATIVE_TO
        assert (units.checks_note() is None) == native, key


def test_checks_note_can_be_asked_about_a_system_it_is_not_set_to():
    units.set_current('cirsoc')
    assert units.checks_note('aisc')
    assert units.checks_note('cirsoc') is None


def test_the_units_bar_shows_it():
    """The declaration is only worth having if it reaches the screen."""
    import re
    src = (Path(__file__).resolve().parents[1] / 'main.py').read_text(
        encoding='utf-8')
    assert 'checks_note' in src, 'main.py never asks for the caveat'
    m = re.search(r'self\.checks_note\s*=\s*tk\.Label\((.*?)\)', src, re.S)
    assert m, 'the caveat has no label in the units bar'
    assert 'units_bar' in m.group(1), (
        'the caveat belongs beside the selector it qualifies')
