"""The card that says which element decides the design.

The numbers were always computed; they were printed at the bottom of the
window where nobody looks. What these tests protect is the part that is
easy to get wrong and easy to not notice: a support is a stress
singularity, so the worst element anywhere is almost always the corner
one, and a card that only ever says "the corner" says nothing about the
shape. Every row therefore carries a second answer, clear of the support
blocks, and these tests check that the second answer is really a
different element and really outside them.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

tk = pytest.importorskip('tkinter')

import units
from apps.shell import shell_app as sa
from apps.shell import shell_design as sd


@pytest.fixture
def app():
    units.set_current('cirsoc')
    try:
        root = tk.Tk()
    except tk.TclError:                          # pragma: no cover
        pytest.skip('no display')
    root.geometry('1400x900')
    a = sa.ShellApp(root)
    a.pack(fill='both', expand=True)
    root.update()
    try:
        yield a
    finally:
        units.set_current('cirsoc')
        a.stop_units()
        try:
            root.destroy()
        except Exception:
            pass


@pytest.fixture
def ran(app):
    assert app.analyze() is True
    return app


def test_the_card_is_empty_until_something_has_been_analysed(app):
    for key, *_ in sa.ShellApp.GOV_ROWS:
        assert app.gov_rows[key]['value'].cget('text') == '—'
        assert app.gov_rows[key]['elem'] is None
    assert app.gov_note.cget('text') == ''


def test_every_row_fills_in_after_a_run(ran):
    for key, label, _c, _f in sa.ShellApp.GOV_ROWS:
        box = ran.gov_rows[key]
        assert box['elem'] is not None
        assert box['value'].cget('text') != '—'
        assert 'el %d' % box['elem'] in box['sub'].cget('text')


def test_the_tension_row_is_the_most_tensioned_element(ran):
    rows = ran.governing_rows()
    e = rows['tension']['elem']
    peak = None
    for cb in ran.res.combos:
        F = ran.res.combo_forces(cb)
        N1, _N2, _ = sa.sm.principal(F['Nx'], F['Ny'], F['Nxy'])
        peak = N1 if peak is None else np.maximum(peak, N1)
    assert e == int(np.argmax(peak))
    assert rows['tension']['value'] == pytest.approx(peak.max())


def test_the_compression_row_is_the_most_compressed_element(ran):
    rows = ran.governing_rows()
    low = None
    for cb in ran.res.combos:
        F = ran.res.combo_forces(cb)
        _N1, N2, _ = sa.sm.principal(F['Nx'], F['Ny'], F['Nxy'])
        low = N2 if low is None else np.minimum(low, N2)
    assert rows['compression']['elem'] == int(np.argmin(low))
    assert rows['compression']['value'] < 0


def test_the_governing_row_is_the_one_the_report_names(ran):
    rows = ran.governing_rows()
    assert rows['governing']['elem'] == int(np.argmax(ran.des.util_max))
    assert rows['governing']['combo'] in sd.CHECK_LABELS.values()
    assert ('Worst element %d' % rows['governing']['elem']) in '\n'.join(ran.des.summary())


def test_the_head_zone_covers_the_blocks_and_a_little_more(ran):
    zone = ran.head_zone()
    assert zone.any(), 'the preset has support blocks'
    assert not zone.all()
    assert zone[np.asarray(ran.res.fem['in_head'], bool)].all()


def test_the_second_answer_really_is_clear_of_the_supports(ran):
    zone = ran.head_zone()
    rows = ran.governing_rows()
    for key in ('tension', 'compression', 'governing'):
        e = rows[key]['elem_away']
        assert e is not None
        assert not zone[e], key


def test_the_second_answer_is_never_worse_than_the_first(ran):
    rows = ran.governing_rows()
    assert rows['tension']['value_away'] <= rows['tension']['value']
    assert rows['compression']['value_away'] >= rows['compression']['value']
    assert rows['governing']['value_away'] <= rows['governing']['value']


def test_the_corner_really_does_dominate_so_the_second_answer_earns_its_place(ran):
    """The reason two numbers, not one: on this preset the headline element
    is inside the support zone and the shape's own worst element is a
    different one somewhere else."""
    zone = ran.head_zone()
    rows = ran.governing_rows()
    assert zone[rows['governing']['elem']]
    assert rows['governing']['elem_away'] != rows['governing']['elem']
    assert 'clear of the supports' in ran.gov_rows['governing']['sub'].cget('text')


def test_clicking_a_row_selects_it_colours_by_it_and_cuts_through_it(ran):
    ran.set_mode('definitions')
    ran.show_governing('tension')
    e = ran.gov_rows['tension']['elem']
    assert ran.sel == e
    assert ran.mode == 'analyse'
    assert ran.v_field.get() == 'Principal N1 (tension)'
    assert len(ran.cuts) == 1
    assert ran.cuts[0]['axis'] == 'y'
    assert ran.cuts[0]['pos'] == pytest.approx(ran.geom['centroids'][e][1])


def test_clicking_the_same_row_twice_does_not_stack_cuts(ran):
    ran.show_governing('governing')
    ran.show_governing('governing')
    ran.show_governing('governing')
    assert len(ran.cuts) == 1


def test_each_row_colours_by_its_own_field(ran):
    for key, _l, _c, field in sa.ShellApp.GOV_ROWS:
        ran.show_governing(key)
        assert ran.v_field.get() == field


def test_clicking_an_unfilled_row_does_nothing(app):
    app.show_governing('tension')
    assert app.sel is None
    assert app.cuts == []


def test_a_refused_analysis_empties_the_card(ran):
    assert ran.gov_rows['tension']['elem'] is not None
    ran.model.data['supports'] = []
    ran.model.data['columns'] = []
    assert ran.analyze() is False
    assert ran.gov_rows['tension']['elem'] is None
    assert ran.gov_rows['tension']['value'].cget('text') == '—'


def test_the_card_follows_a_cut_plan(ran):
    """The elliptical hypar is held on its own rim, so nothing about the
    card may assume a rectangle or the four grid corners."""
    ran.v_edge_rule.set('(2x/a)^2 + (2y/b)^2 - 1')
    ran._set_edge_rule()
    assert ran.analyze() is True
    rows = ran.governing_rows()
    c = ran.geom['centroids']
    for key in ('tension', 'compression', 'governing'):
        e = rows[key]['elem']
        assert np.hypot(c[e, 0], c[e, 1]) < 6.0 + 1e-6
