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


def test_the_readout_and_the_drawing_share_one_slot(app):
    """Sections and Design are the two modes that answer with a drawing, so
    they take the bottom pane -- and give it back."""
    app.set_mode('sections')
    app.update()
    panes = [str(w) for w in app._pw.panes()]
    assert str(app._sec_pane) in panes and str(app._info_pane) not in panes
    app.set_mode('loads')
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


# ── supports, picked on the model ──────────────────────────────────────────

def _screen_of(app, node):
    sx, sy = app.cam.project(app.geom['X'])
    return float(sx[node]), float(sy[node])


def test_clicking_a_corner_puts_a_support_on_it(app):
    app.set_mode('supports')
    app.update()
    n = app.geom['ids'][0, 0]
    before = len(app.model.data['supports'])
    app.toggle_support_at(*_screen_of(app, n))
    assert len(app.model.data['supports']) == before + 1
    assert n in app.support_node_index()


def test_what_lands_there_is_a_block_not_a_point(app):
    """A shell on a mathematical point is a singularity; the tab has always
    known that, and picking must not be a way around it."""
    app.set_mode('supports')
    app.v_pick_block.set(1.5)
    app.toggle_support_at(*_screen_of(app, app.geom['ids'][0, 0]))
    spec = app.model.data['supports'][-1]
    assert spec['at'] == 'point'
    assert spec['block'] == pytest.approx(1.5)


def test_clicking_the_same_corner_again_takes_it_away(app):
    app.set_mode('supports')
    n = app.geom['ids'][-1, -1]
    app.toggle_support_at(*_screen_of(app, n))
    assert n in app.support_node_index()
    app.toggle_support_at(*_screen_of(app, n))
    assert n not in app.support_node_index()


def test_clicking_empty_space_says_so_and_changes_nothing(app):
    app.set_mode('supports')
    before = list(app.model.data['supports'])
    app.toggle_support_at(-500.0, -500.0)
    assert app.model.data['supports'] == before
    assert 'No element corner' in app.status.get()


def test_the_type_chosen_in_the_panel_is_what_arrives(app):
    app.set_mode('supports')
    app.v_pick_type.set('vertical')
    app.toggle_support_at(*_screen_of(app, app.geom['ids'][0, -1]))
    assert app.model.data['supports'][-1]['type'] == 'vertical'


@pytest.mark.parametrize('what,least', [('corners', 4), ('boundary', 8), ('lowest', 1)])
def test_the_quick_actions_support_what_they_say(app, what, least):
    app.set_mode('supports')
    app.model.data['supports'] = []
    n = app.quick_support(what)
    assert n >= least
    assert len(app.support_node_index()) == n


def test_a_quick_action_does_not_double_up_on_a_corner_already_taken(app):
    app.set_mode('supports')
    app.model.data['supports'] = []
    app.quick_support('corners')
    again = app.quick_support('corners')
    assert again == 0
    assert len(app.model.data['supports']) == 4


def test_clearing_leaves_a_mechanism_and_says_so(app):
    app.clear_supports()
    assert app.model.data['supports'] == []
    assert 'mechanism' in app.status.get()
    assert app.analyze() is False       # refused, with a reason, not a crash
    assert app.error


def test_the_sandbox_switches_a_support_off_without_deleting_it(app):
    app.set_mode('supports')
    app.model.data['supports'] = []
    app.quick_support('corners')
    assert app.analyze(), app.error
    before = app._peak_deflection()
    app.rl_supports.tree.selection_set('0')
    app.toggle_sandbox()
    assert len(app.model.data['supports']) == 4      # still there
    assert app.model.data['supports'][0]['off'] is True
    assert app.analyze(), app.error
    assert app._peak_deflection() > before, 'removing a support should not stiffen it'
    app.rl_supports.tree.selection_set('0')
    app.toggle_sandbox()
    assert app.model.data['supports'][0]['off'] is False


def test_the_sandbox_needs_a_row_picked(app):
    app.set_mode('supports')
    app.rl_supports.tree.selection_remove(*app.rl_supports.tree.selection())
    app.toggle_sandbox()
    assert 'Pick a support row' in app.status.get()


def test_the_corners_are_only_drawn_where_you_are_placing_them(app):
    app.set_mode('supports')
    app.update()
    assert app.zc.canvas.find_withtag('pick')
    app.set_mode('loads')
    app.update()
    assert not app.zc.canvas.find_withtag('pick')


# ── what the shape alone knows ─────────────────────────────────────────────

def test_the_curvature_map_needs_no_analysis(app):
    """It is a property of the surface, so it must draw before any solve."""
    assert app.res is None
    app.v_field.set('Gaussian curvature K')
    app._draw()
    vals, scale, _q = app.field_values()
    assert vals is not None and len(vals) == len(app.geom['elems'])
    assert scale == 'diverging'
    assert app.zc.canvas.find_withtag('face')


def test_the_preset_hypar_reads_as_a_saddle_everywhere(app):
    vals, _s, _q = app.field_values('Gaussian curvature K')
    assert np.all(vals < 0), 'z = k x y is anticlastic at every point'


def test_the_generators_are_drawn_on_a_hypar_and_only_when_asked(app):
    app.v_rulings.set(False)
    app._draw()
    n_plain = len(app.zc.canvas.find_all())
    app.v_rulings.set(True)
    app._draw()
    assert len(app.zc.canvas.find_all()) > n_plain


def test_a_dome_is_told_it_has_no_straight_lines(app):
    app.add_definition('zz(x, y) = 3 - 0.04 (x^2 + y^2)')
    app._set_role('surface', 'zz')
    app._rebuild_geometry()
    app.v_rulings.set(True)
    app._draw()
    texts = ' '.join(app.zc.canvas.itemcget(i, 'text') for i in app.zc.canvas.find_all()
                     if app.zc.canvas.type(i) == 'text')
    assert 'synclastic' in texts


def test_a_dome_reads_as_synclastic_in_the_curvature_map(app):
    app.add_definition('zz(x, y) = 3 - 0.04 (x^2 + y^2)')
    app._set_role('surface', 'zz')
    app._rebuild_geometry()
    vals, _s, _q = app.field_values('Gaussian curvature K')
    assert np.all(vals > 0)


# ── the plan rule: the end of the rectangle ────────────────────────────────

def test_no_rule_keeps_the_whole_rectangle(app):
    g = app.geom
    assert len(g['elems']) == g['nx'] * g['ny']
    assert g['kept'] is None


def test_a_rule_cuts_the_rectangle_into_a_plan(app):
    whole = len(app.geom['elems'])
    app.v_plan_rule.set('hypot(x, y) < 5')
    app._set_plan_rule()
    assert len(app.geom['elems']) < whole
    assert 'removed' in app.plan_rule_note.cget('text')


def test_the_cut_is_element_granular_and_judged_at_the_centre(app):
    app.v_plan_rule.set('x < 0')
    app._set_plan_rule()
    cen = app.geom['centroids']
    assert np.all(cen[:, 0] < 0), 'an element whose centre fails the rule is out'


def test_clearing_the_rule_puts_the_rectangle_back(app):
    whole = len(app.geom['elems'])
    app.v_plan_rule.set('hypot(x, y) < 4')
    app._set_plan_rule()
    assert len(app.geom['elems']) < whole
    app.v_plan_rule.set('')
    app._set_plan_rule()
    assert len(app.geom['elems']) == whole


def test_a_rule_that_keeps_nothing_is_refused_with_a_reason(app):
    app.v_plan_rule.set('hypot(x, y) < 0.0001')
    app._set_plan_rule()
    assert app.error
    assert 'no elements' in app.error


def test_a_rule_that_will_not_compile_reports_instead_of_crashing(app):
    app.v_plan_rule.set('hypot(x, ) <<')
    app._set_plan_rule()
    assert app.error
    assert app.analyze() is False


def test_a_cut_plan_supported_on_its_own_new_edge_solves(app):
    app.v_plan_rule.set('hypot(x, y) < 5')
    app._set_plan_rule()
    app.model.data['supports'] = []
    app.model.data['beams'] = []
    app._rebuild_geometry()
    n = app.quick_support('boundary')
    assert n > 20, 'the new boundary should have found the round edge'
    assert app.analyze(), app.error


def test_the_cut_away_nodes_do_not_make_the_system_singular(app):
    """They carry nothing, so they are held still -- which must not be
    mistaken for the shell being supported there."""
    app.v_plan_rule.set('hypot(x, y) < 5')
    app._set_plan_rule()
    used = app.geom['used']
    assert not used.all(), 'the cut should leave some nodes unused'
    app.model.data['supports'] = []
    app.model.data['beams'] = []
    app._rebuild_geometry()
    assert app.analyze() is False, 'an unsupported disc is still a mechanism'
    assert 'support' in app.error or 'mechanism' in app.error


def test_a_rib_that_pokes_outside_the_cut_is_not_anchored_to_ground(app):
    """The orphan nodes are held still, but never one a beam uses: that
    would tie the rib to ground at whichever end poked out."""
    app.v_plan_rule.set('hypot(x, y) < 5')
    app.model.data['beams'] = [{'line': 'x=0', 'b': 25.0, 'h': 50.0, 'offset': 'below'}]
    app._set_plan_rule()
    # One pinned corner inside the disc: enough for the model to get as far
    # as assembling, not enough to hold a disc. The rib runs the whole width,
    # so its ends are outside the cut -- if those were pinned the shell would
    # hang off them and solve. It must still read as a mechanism.
    app.model.data['supports'] = [{'at': 'point', 'which': '0, 0',
                                   'type': 'pinned', 'block': 1.0}]
    app._rebuild_geometry()
    assert app.analyze() is False
    assert 'mechanism' in app.error


def test_a_cut_plan_weighs_less(app):
    app.v_plan_rule.set('hypot(x, y) < 5')
    app._set_plan_rule()
    g = app.geom
    import apps.shell.shell_solid as _ss
    cut = _ss.solid_volume(g['X'], g['elems'], g['t'])
    app.v_plan_rule.set('')
    app._set_plan_rule()
    g = app.geom
    whole = _ss.solid_volume(g['X'], g['elems'], g['t'])
    assert cut < whole


# ── the guide ──────────────────────────────────────────────────────────────

def test_every_colour_map_has_a_sentence(app):
    """A list of thirty names with no explanation is the complaint this whole
    mode exists to answer; a map added later without a note would quietly
    bring it back."""
    missing = [name for name in sa.FIELDS
               if name not in sa.FIELD_HELP and not name.startswith(('Steel', 'Utilisation: '))]
    assert not missing, 'no note for: %s' % missing


def test_the_guide_card_opens_on_the_map_you_are_reading(app):
    app.set_mode('analyse')
    app.v_field.set('Membrane shear Nxy')
    win = app.open_field_guide()
    app.update()
    assert 'Nxy' in win.title()
    text = win.winfo_children()[1].get('1.0', 'end')
    assert 'q/2k' in text or 'shear' in text
    win.destroy()


def test_the_guide_always_carries_the_three_caveats_and_the_block(app):
    win = app.open_field_guide()
    text = win.winfo_children()[1].get('1.0', 'end')
    for probe in ('201.03', 'CIRSOC 102-2005', '8.6 cm', 'singularity'):
        assert probe in text, probe
    win.destroy()


def test_the_guide_says_which_scales_are_comparable_between_models(app):
    app.v_field.set('Utilisation (structural checks)')
    win = app.open_field_guide()
    text = win.winfo_children()[1].get('1.0', 'end')
    assert 'red is 1.0 in every model' in text
    win.destroy()


# ── comparing designs, and sweeping one number ─────────────────────────────

def test_there_is_nothing_to_compare_before_a_solve(app):
    assert app.design_metrics() is None
    assert app.keep_design() is None
    assert 'Analyse first' in app.status.get()


def test_a_kept_design_carries_the_numbers_the_studies_compare(app):
    assert app.analyze(), app.error
    m = app.keep_design('as built')
    for key in ('tension_pa', 'deflection', 'span_over', 'steel_kg', 'concrete',
                'tension_area', 'util', 't_min', 't_max'):
        assert key in m, key
    assert m['concrete'] > 0
    assert m['steel_kg'] > 0, 'the steel maps were not counted'
    assert app.design_tree.get_children()


def test_the_steel_is_counted_whichever_mesh_layout_the_design_chose(app):
    """One central mesh leaves the four face maps NaN and two meshes leave
    the central pair NaN; either way there is steel in the shell."""
    assert app.analyze(), app.error
    m = app.design_metrics()
    assert np.isfinite(m['steel_kg']) and m['steel_kg'] > 0


def test_keeping_two_designs_puts_them_side_by_side(app):
    assert app.analyze(), app.error
    app.keep_design('thin')
    app.add_definition('t2 = 0.18')
    app._set_role('thickness', 't2')
    assert app.analyze(), app.error
    app.keep_design('thick')
    assert len(app.designs) == 2
    assert app.designs[1]['concrete'] > app.designs[0]['concrete']
    assert len(app.design_tree.get_children()) == 2
    app.clear_designs()
    assert app.designs == [] and not app.design_tree.get_children()


def test_a_sweep_moves_one_number_and_puts_it_back(app):
    assert app.analyze(), app.error
    before = app.model.ws.numbers()['f']
    rows = app.sweep('f', 2.0, 4.0, 3)
    assert len(rows) == 3
    assert app.model.ws.numbers()['f'] == pytest.approx(before), \
        'a sweep that leaves the model somewhere else has edited the design'


def test_a_higher_rise_carries_the_load_better(app):
    """The published shape study in one button: hold everything, move the
    rise, and the tension, the deflection and the steel all come down."""
    assert app.analyze(), app.error
    rows = app.sweep('f', 2.0, 4.0, 3)
    assert rows[-1]['tension_pa'] < rows[0]['tension_pa']
    assert rows[-1]['span_over'] > rows[0]['span_over']
    assert rows[-1]['steel_kg'] < rows[0]['steel_kg']


def test_sweeping_a_name_that_is_not_a_number_is_refused(app):
    assert app.analyze(), app.error
    assert app.sweep('z', 1.0, 2.0, 3) == []
    assert 'not one of the numbers' in app.status.get()


def test_the_sweep_is_drawn_with_how_far_each_curve_moved(app):
    assert app.analyze(), app.error
    app.sweep('f', 2.0, 4.0, 3)
    app.set_mode('design')
    app.update()
    texts = ' '.join(app.sec_canvas.itemcget(i, 'text') for i in app.sec_canvas.find_all()
                     if app.sec_canvas.type(i) == 'text')
    assert 'peak tension' in texts and '%' in texts


def test_the_design_pane_says_so_before_any_sweep(app):
    app.set_mode('design')
    app.update()
    texts = ' '.join(app.sec_canvas.itemcget(i, 'text') for i in app.sec_canvas.find_all()
                     if app.sec_canvas.type(i) == 'text')
    assert 'No sweep yet' in texts
