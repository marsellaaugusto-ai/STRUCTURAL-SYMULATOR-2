"""The rebuilt window: one mode at a time, and cuts you can keep.

Driven through the real widgets, like test_shell_app.py. The questions
these answer are the ones the rebuild could get quietly wrong: does a mode
that is not on screen still claim its width; does the colour list in the
panel actually drive the drawing; does a cut survive being made; and does
the section drawing come out at true scale with the thickness in it.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

tk = pytest.importorskip('tkinter')

import units
from apps.shell import shell_app as sa


@pytest.fixture
def app():
    units.set_current('cirsoc')
    try:
        root = tk.Tk()
    except tk.TclError:                        # pragma: no cover
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


# ── the mode rail ──────────────────────────────────────────────────────────

def test_it_opens_on_the_surface_and_only_that_panel_is_packed(app):
    assert app.mode == 'definitions'
    packed = [k for k, sp in app._panels.items() if sp.winfo_manager()]
    assert packed == ['definitions']


@pytest.mark.parametrize('key', [m[0] for m in sa.MODES])
def test_every_mode_opens_and_forgets_the_others(app, key):
    app.set_mode(key)
    app.update()
    packed = [k for k, sp in app._panels.items() if sp.winfo_manager()]
    assert packed == [key], 'a mode that is not on screen is still claiming width'


def test_an_unknown_mode_is_ignored_rather_than_crashing(app):
    app.set_mode('definitions')
    app.set_mode('no-such-mode')
    assert app.mode == 'definitions'


def test_the_rail_marks_the_open_mode(app):
    app.set_mode('loads')
    app.update()
    _cell, stripe, _inner, _g, label = app._rail_buttons['loads']
    assert stripe.cget('bg') == sa.RAIL_STRIPE
    assert 'bold' in str(label.cget('font'))
    _c2, stripe2, _i2, _g2, _l2 = app._rail_buttons['design']
    assert stripe2.cget('bg') == sa.RAIL_BG


def test_alt_digits_reach_every_mode(app):
    top = app.winfo_toplevel()
    bound = top.bind()
    for n in range(1, len(sa.MODES) + 1):
        assert '<Alt-Key-%d>' % n in bound


def test_the_readout_and_the_section_share_one_slot(app):
    """Sections is the only mode that answers with a drawing, so it takes the
    bottom pane -- and gives it back."""
    app.set_mode('sections')
    app.update()
    panes = [str(w) for w in app._pw.panes()]
    assert str(app._sec_pane) in panes and str(app._info_pane) not in panes
    app.set_mode('design')
    app.update()
    panes = [str(w) for w in app._pw.panes()]
    assert str(app._info_pane) in panes and str(app._sec_pane) not in panes


# ── the colour list, out of the toolbar ────────────────────────────────────

def test_the_colour_list_is_a_visible_list_of_every_map(app):
    app.set_mode('analyse')
    app.update()
    assert app.field_list.size() == len(sa.FIELDS)
    assert app.field_list.get(0) in sa.FIELDS


def test_picking_a_row_changes_what_is_drawn(app):
    app.set_mode('analyse')
    app.update()
    i = list(sa.FIELDS).index('Thickness t')
    app.field_list.selection_clear(0, 'end')
    app.field_list.selection_set(i)
    app._on_field_pick()
    assert app.v_field.get() == 'Thickness t'
    assert app.zc.canvas.find_withtag('face')


def test_the_row_carries_its_own_sentence(app):
    app.set_mode('analyse')
    app.v_field.set('Thickness needed')
    app._sync_field_list()
    assert 'passes' in app.field_help.cget('text')


def test_the_list_follows_the_field_when_something_else_sets_it(app):
    """analyse() switches the map after a thickening run; a list still
    highlighting the row from before would describe the wrong picture."""
    app.set_mode('analyse')
    app.update()
    app.v_field.set('Thickness to add')
    app.update()
    sel = app.field_list.curselection()
    assert sel and app.field_list.get(sel[0]) == 'Thickness to add'
    assert 'minus' in app.field_help.cget('text')


# ── cuts ───────────────────────────────────────────────────────────────────

def test_a_cut_is_kept_listed_and_drawn(app):
    app.set_mode('sections')
    app.update()
    assert app.cut_list.size() == 0
    app.v_cut_pos.set('0')
    app.add_cut('y')
    app.update()
    assert len(app.cuts) == 1 and app.cut_list.size() == 1
    row = app.cut_list.get(0)
    assert row.startswith('S1') and 'y = 0' in row
    assert app.cut_list.itemcget(0, 'foreground') == app.cuts[0]['colour']


def test_each_cut_gets_its_own_colour(app):
    app.set_mode('sections')
    for pos in ('0', '1', '2'):
        app.v_cut_pos.set(pos)
        app.add_cut('x')
    assert len({c['colour'] for c in app.cuts}) == 3


def test_a_cut_position_that_is_not_a_number_is_refused_not_stored(app):
    app.set_mode('sections')
    app.v_cut_pos.set('not a number')
    app.add_cut('x')
    assert app.cuts == []
    assert app.status.get()


def test_the_position_may_be_a_formula_like_everything_else_here(app):
    app.set_mode('sections')
    app.v_cut_pos.set('a/4')
    app.add_cut('x')
    assert len(app.cuts) == 1
    assert app.cuts[0]['pos'] == pytest.approx(3.0)      # the preset's a = 12


def test_removing_a_cut_takes_it_off_the_model_too(app):
    app.set_mode('sections')
    app.v_cut_pos.set('0')
    app.add_cut('x')
    app.cut_list.selection_set(0)
    app.remove_cut()
    assert app.cuts == [] and app.cut_list.size() == 0


def test_the_section_says_so_when_nothing_is_selected(app):
    app.set_mode('sections')
    app.update()
    texts = [app.sec_canvas.itemcget(i, 'text')
             for i in app.sec_canvas.find_all()
             if app.sec_canvas.type(i) == 'text']
    assert any('No cut selected' in t for t in texts)


def test_the_section_draws_the_slab_and_labels_its_scale(app):
    assert app.analyze(), app.error
    app.set_mode('sections')
    app.v_cut_pos.set('0')
    app.add_cut('y')
    app.cut_list.selection_set(0)
    app._draw_section()
    app.update()
    items = app.sec_canvas.find_all()
    assert len(items) > 10
    polys = [i for i in items if app.sec_canvas.type(i) == 'polygon']
    assert polys, 'the cut face is not drawn'
    texts = ' '.join(app.sec_canvas.itemcget(i, 'text') for i in items
                     if app.sec_canvas.type(i) == 'text')
    assert 'true scale' in texts
    assert 'thickness at each station' in texts


def test_exaggerating_the_thickness_is_said_out_loud(app):
    assert app.analyze(), app.error
    app.set_mode('sections')
    app.v_cut_pos.set('0')
    app.add_cut('y')
    app.cut_list.selection_set(0)
    app.v_exag.set(10.0)
    app._draw_section()
    texts = ' '.join(app.sec_canvas.itemcget(i, 'text') for i in app.sec_canvas.find_all()
                     if app.sec_canvas.type(i) == 'text')
    assert '×10' in texts and 'true scale' not in texts


def test_the_cut_list_reports_the_thickness_along_each_cut(app):
    assert app.analyze(), app.error
    app.set_mode('sections')
    app.v_cut_pos.set('0')
    app.add_cut('y')
    app.update()
    assert 't ' in app.cut_list.get(0)


def test_a_cut_is_drawn_on_the_model_in_its_own_colour(app):
    assert app.analyze(), app.error
    app.set_mode('sections')
    app.v_cut_pos.set('0')
    app.add_cut('y')
    app._draw()
    cv = app.zc.canvas
    colours = {cv.itemcget(i, 'fill') for i in cv.find_all() if cv.type(i) == 'line'}
    assert app.cuts[0]['colour'] in colours


# ── the status line ────────────────────────────────────────────────────────

def test_the_status_line_carries_the_numbers_a_designer_reads_first(app):
    assert app.analyze(), app.error
    s = app.status.get()
    for probe in ('elements', 't ', 'L/t', 'concrete', 'span/'):
        assert probe in s, '%r missing from %r' % (probe, s)


def test_the_deflection_is_given_against_the_span_not_only_in_millimetres(app):
    assert app.analyze(), app.error
    s = app.status.get()
    i = s.index('span/')
    assert float(s[i + 5:].split()[0].rstrip('·').strip()) > 1.0
