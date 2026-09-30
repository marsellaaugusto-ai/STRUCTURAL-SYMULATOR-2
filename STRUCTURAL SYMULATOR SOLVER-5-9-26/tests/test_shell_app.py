"""Shell tab -- driven through the real widgets (MANIFESTO s2: build the real
Tk widget, drive it through the controller's own methods, read the real value
back). A sweep over every preset, every colour map, every page, the invalid
inputs, the show-first / automatic thickening switch, the section cut, the
report, the Excel round trip and the unit selector. 2026-09-14."""
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

tk = pytest.importorskip('tkinter')

import units
from apps.shell import shell_app as sa
from apps.shell import shell_model as sm


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


def _pump(a, n=5):
    for _ in range(n):
        a.update()


def _state(a):
    return json.dumps(a._current_state(), sort_keys=True, default=repr)


# ── presets and every colour map ────────────────────────────────────────────
@pytest.mark.parametrize('name', list(sm.PRESETS))
def test_every_preset_analyses_and_every_map_draws(app, name):
    app.load_preset(name)
    assert app.analyze(), app.error
    for field in sa.FIELDS:
        app.v_field.set(field)
        app._draw()
        vals, _scale, _q = app.field_values()
        if field != 'Surface (shaded)':
            assert vals is not None, field
            assert len(vals) == len(app.geom['elems'])
    for sel in app.select_box.cget('values'):
        app.v_select.set(sel)
        app.v_field.set('Membrane shear Nxy')
        app._draw()
    assert app.zc.canvas.find_withtag('face')


def test_the_surface_follows_a_slider_without_analysing(app):
    app.analyze()
    z0 = app.geom['X'][:, 2].copy()
    app.move_slider('f', 5.0)
    _pump(app)
    app._rebuild_geometry()
    assert app.res is None                               # results marked stale
    assert np.abs(app.geom['X'][:, 2]).max() > np.abs(z0).max() * 1.5
    assert app.model.ws.get('f').text == 'f = 5'


def test_a_bad_definition_is_marked_and_analysis_refused_politely(app):
    idx = [d.name for d in app.model.ws.defs].index('z')
    app.edit_definition(idx, 'z(x, y) = 2 f x y / (a b) + nope')
    row = app._def_rows[idx]
    assert row['dot'].cget('fg') == sa.BAD_C
    assert 'nope' in row['err'].cget('text')
    assert app.analyze() is False
    assert 'nope' in app.error


def test_the_input_bar_redefines_like_geogebra(app):
    n = len(app.model.ws.defs)
    app.add_definition('f = 4')
    assert len(app.model.ws.defs) == n
    assert app.model.ws.number('f') == 4.0
    app.add_definition('w(x, y) = 0.2 sin(pi x / a)')
    assert app.model.ws.has_function('w')


def test_choosing_another_function_as_the_surface(app):
    app.add_definition('z2(x, y) = 0.05 (x^2 - y^2)')
    app._set_role('surface', 'z2')
    app._rebuild_geometry()
    X = app.geom['X']
    assert np.allclose(X[:, 2], 0.05 * (X[:, 0] ** 2 - X[:, 1] ** 2))
    assert app.analyze()


def test_plan_limits_and_mesh_size_from_the_panel(app):
    app.plan_vars['x1'].set('a')
    app._set_plan('x1')
    app._rebuild_geometry()
    assert app.geom['plan'][1] == pytest.approx(12.0)
    rec = [r for r in app._si_fields if r['q'] == 'length'][0]     # element size
    rec['var'].set('1.0')
    rec['var'].get()
    app.model.data['mesh']['size'] = 1.0
    app._model_changed()
    app._rebuild_geometry()
    assert app.geom['nx'] == 18 and app.geom['ny'] == 12


# ── supports, beams, columns, loads ─────────────────────────────────────────
def test_vertical_supports_only_are_refused_with_a_reason(app):
    app.model.data['supports'] = [{'at': 'corners', 'which': 'all', 'type': 'vertical', 'block': 0}]
    app.rl_supports.refresh()
    assert app.analyze() is False
    assert 'move freely' in app.error


def test_record_lists_add_and_delete(app):
    rl = app.rl_beams
    n = len(app.model.data['beams'])
    rl.vars['line'].set('x=0')
    rl.vars['b'].set('20')
    rl.vars['h'].set('40')
    rl.add()
    assert len(app.model.data['beams']) == n + 1
    assert app.model.data['beams'][-1]['b'] == pytest.approx(20.0)
    assert app.analyze()
    assert any(f.tag.endswith('x=0') for f in app.res.fem['frames'])
    rl.tree.selection_set(str(n))
    rl.delete()
    assert len(app.model.data['beams']) == n


def test_a_bad_number_in_a_record_is_reported_not_stored(app):
    rl = app.rl_beams
    n = len(app.model.data['beams'])
    rl.vars['b'].set('wide')
    rl.add()
    assert len(app.model.data['beams']) == n
    assert 'not a number' in rl.msg.cget('text')


def test_point_load_is_stored_in_kN(app):
    rl = app.rl_loads
    rl._fill_form({'case': 'Lr', 'type': 'point', 'value': '', 'note': 'hanging lamp',
                   'x': '0', 'y': '0', 'Px': 0.0, 'Py': 0.0, 'Pz': 10.0})
    rl.add()
    assert app.model.data['loads'][-1]['Pz'] == pytest.approx(10.0)
    assert app.analyze()
    j = app.res.cases.index('Lr')
    assert -app.res.equilibrium[j]['applied'][2] == pytest.approx(0.96e3 * 144 + 10e3, rel=1e-9)


def test_wind_case_from_a_pattern_enters_the_combinations(app):
    name = app.add_wind_case(list(sm.wind.CP_PRESETS)[2])
    assert app.analyze()
    assert any(name in c.factors for c in app.res.combos)
    # 2005-basis speeds under the 2024 code: W combined at 1.6
    assert any(c.factors.get(name) == pytest.approx(1.6) for c in app.res.combos)
    assert 'qz' in app.qz_label.cget('text')


def test_switching_to_the_2005_code(app):
    app.v_code.set(sm.codes.CODES['cirsoc201_2005'].name)
    app._set_code()
    assert app.analyze()
    assert all(c.formula.startswith('(9-') for c in app.res.combos)


# ── show first, then the automatic toggle ───────────────────────────────────
def test_show_first_then_automatic_thickening(app):
    app.load_preset('Inverted umbrella (4 hypars on one column)')
    assert app.analyze()
    assert app.des.needs_thicker.any()
    assert app.model.data['auto_layer'] is None           # nothing changed
    app.show_thickness_needed()
    assert app.v_field.get() == 'Thickness to add'
    app.v_auto.set(True)
    app._on_auto_toggle()
    assert app.analyze()
    assert not app.des.fails.any()
    assert app.model.data['auto_layer']['points']
    assert app.thicken_log
    app.clear_thickening()
    assert app.model.data['auto_layer'] is None
    assert app.res is None


def test_a_drawn_zone_thickens_the_shell_there(app):
    rl = app.rl_zones
    rl.vars['rule'].set('abs(x) < 1 and abs(y) < 1')
    rl.vars['t'].set('20')                                # cm in the CIRSOC convention
    rl.add()
    assert app.model.data['zones'][-1]['t'] == pytest.approx(0.20)
    assert app.analyze()
    c = app.res.fem['mesh']['centroids']
    inside = (np.abs(c[:, 0]) < 1) & (np.abs(c[:, 1]) < 1)
    assert np.all(app.res.fem['shells'].a[inside] == pytest.approx(0.20))
    assert np.all(app.res.fem['shells'].a[~inside] == pytest.approx(0.10))


# ── reading results ─────────────────────────────────────────────────────────
def test_clicking_an_element_reports_it_and_clicking_nothing_clears(app):
    app.analyze()
    app._pump = None
    _pump(app)
    X = app._nodes_for_view()
    cen = X[app.geom['elems']].mean(axis=1)
    sx, sy = app.cam.project(cen)
    e = 100

    class Ev:
        pass
    ev = Ev()
    ev.x, ev.y = float(sx[e]), float(sy[e])
    app._on_click(ev)
    assert app.sel is not None
    lines = app.element_report(app.sel)
    assert any('utilisation' in ln for ln in lines)
    ev.x, ev.y = -500.0, -500.0
    app._on_click(ev)
    assert app.sel is None


def test_section_cut_takes_one_row_of_elements(app):
    app.analyze()
    s, v = app.section_values('y', 0.1, 'Membrane shear Nxy')
    assert len(s) == app.geom['nx'] and np.all(np.isfinite(v))
    s, v = app.section_values('x', 0.1, 'Thickness needed')
    assert len(s) == app.geom['ny']
    win = app.open_section_cut()
    _pump(app)
    win.draw()
    assert win.winfo_children()
    win.destroy()


def test_report_contains_every_section(app):
    app.analyze()
    txt = app.report_text()
    for head in ('1. GEOMETRY', '3. LOADS', '4. LOAD COMBINATIONS', '5. EQUILIBRIUM',
                 '6. MEMBRANE THEORY', '7. SHELL DESIGN', '8. CODE CLAUSES', '9. ASSUMPTIONS'):
        assert head in txt
    assert 'CIRSOC 201.03' in txt
    win = app.open_report()
    win.destroy()


def test_excel_round_trip_through_the_tab(app, tmp_path):
    pytest.importorskip('openpyxl')
    app.load_preset('Inverted umbrella (4 hypars on one column)')
    app.analyze()
    U0 = app.res.U.copy()
    p = str(tmp_path / 'shell.xlsx')
    app.export_excel(p)
    app.load_preset('Barrel vault (cylinder)')
    app.import_excel(p)
    assert app.analyze()
    assert np.allclose(app.res.U, U0)


def test_drawing_survives_extreme_zoom_deformed_and_principal(app):
    app.analyze()
    app.v_deformed.set(True)
    app.v_principal.set(True)
    app.v_field.set('Principal N2 (compression)')
    for _ in range(40):
        app.zc.zoom_in()
    app._draw()
    for _ in range(80):
        app.zc.zoom_out()
    app._draw()
    for v in sa.view3d.VIEWS:
        app.set_view(v)


# ── units ───────────────────────────────────────────────────────────────────
def test_units_switch_is_cosmetic_and_boxes_do_not_drift(app):
    app.analyze()
    before = _state(app)
    units.set_current('aisc')
    _pump(app)
    # focus-out of every box without typing must not rewrite anything
    for rec in app._si_fields:
        rec['var'].set(rec['var'].get())
    for rl in (app.rl_beams, app.rl_columns, app.rl_zones):
        if rl.records():
            rl.tree.selection_set('0')
            rl._load_selected()
            rl.update_sel()
    units.set_current('cirsoc')
    _pump(app)
    assert _state(app) == before
    fc_box = [r for r in app._si_fields if r['q'] == 'stress'][0]
    assert fc_box['var'].get() == '30'


def test_legend_and_readout_follow_the_convention(app):
    app.analyze()
    app.v_field.set('Membrane shear Nxy')
    units.set_current('aisc')
    _pump(app)
    app._draw()
    texts = [app.zc.canvas.itemcget(i, 'text') for i in app.zc.canvas.find_all()
             if app.zc.canvas.type(i) == 'text']
    assert any('kip/ft' in t for t in texts)
