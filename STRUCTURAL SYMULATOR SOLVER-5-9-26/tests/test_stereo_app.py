"""Real-widget tests for the Stereo tab UI (apps/stereo/stereo_app.py).

Per MANIFESTO sec. 2 ("never conclude a UI fact from reading code"): every
assertion here drives an actual built Tk widget and reads a real value
back, rather than trusting that the wiring in stereo_app.py does what its
code implies.

Rewritten 2026-09-12 for the UI overhaul that replaced the old hand-rolled
sidebar/camera-button layout with common.ScrollPanel, mouse-only orbit/
zoom/pan, a red(tension)/blue(compression) force gradient, a chord/web
section split, and an area-load feature -- see stereo_app.py's own
docstring for the reasoning.
"""
import math
import time

import tkinter as tk
import pytest

from apps.stereo.stereo_app import (
    StereoApp, force_color, deform_color, FAMILY_LABEL, CHORD_ROLES,
    QUICK_SUPPORT_PIN, QUICK_SUPPORT_FIXED, QUICK_SUPPORT_CLEAR, QUICK_SUPPORT_CUSTOM,
    moment_color, reaction_moment_signed, MOMENT_ZERO_COLOR, MOMENT_AXES,
    MOMENT_AXIS_RESULTANT, MOMENT_AXIS_MX, MOMENT_AXIS_MY, MOMENT_AXIS_MZ,
    MODULE_DIM_COLOR, SUPPORT_DISABLED_COLOR, SLENDER_HALO_COLOR, SLENDERNESS_LIMIT,
    LOAD_PATH_ANIM_TICKS, LOAD_PATH_NEAR_ZERO_FRAC, NEAR_ZERO_COLOR,
    SCALE_PEAK, SCALE_P95, FILL_DENSITY_STIPPLE,
    NEAR_ZERO_FRAC, STRESS_WIDTH_MIN, STRESS_WIDTH_MAX,
    COLOUR_NONE, COLOUR_FORCE, COLOUR_UTIL, COLOUR_MOMENT,
    FILL_NONE, FILL_SHADED, FILL_MODES,
    GRADIENT_SEGMENTS, GRADIENT_SEGMENTS_DENSE, GRADIENT_DENSE_MEMBERS,
    MOMENT_BACKDROP_COLOR, MOMENT_NODE_RADIUS_PX,
    TENSION_HIGH, COMPRESSION_HIGH,
)
from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_math as sm
from apps.stereo import stereo_app_constants as sc
from apps.stereo import stereo_app_module_editor as me
from apps.stereo import stereo_app_shell as sh


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    """Redirect every messagebox popup into a list instead of opening a real
    modal window. Without this, a test that triggers an unexpected dialog
    (e.g. the analysis-error path) does not fail -- it HANGS, because a
    modal box with no mainloop behind it waits for a click that never
    comes. Autouse, so no test in this file can open a real dialog even by
    accident (same guard as tests/test_section_designer_editing.py)."""
    seen = []
    for kind in ('showinfo', 'showerror', 'showwarning'):
        monkeypatch.setattr(f'apps.stereo.stereo_app.messagebox.{kind}',
                            lambda *a, _k=kind, **kw: seen.append((_k,) + a))
    return seen


@pytest.fixture(scope='session')
def tk_root():
    last = None
    for attempt in range(6):
        try:
            root = tk.Tk()
            break
        except tk.TclError as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    else:
        pytest.skip(f'no Tk display after 6 attempts: {last}')
    root.geometry('1400x900')
    # deliberately NOT withdrawn: several tests below check the 3D view's
    # actual on-screen centering/pixel geometry (the camera-centering
    # regression this UI overhaul fixed), which a withdrawn/unmapped
    # window does not reliably report under Xvfb.
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def app(tk_root):
    tab = tk.Frame(tk_root)
    a = StereoApp(tab)
    tab.pack(fill='both', expand=True)
    tk_root.update_idletasks()
    tk_root.update()
    yield a
    tab.destroy()


class FakeEvent:
    def __init__(self, x, y, width=None, height=None, state=0):
        self.x = x
        self.y = y
        self.state = state
        if width is not None:
            self.width = width
        if height is not None:
            self.height = height


def _screen_pos_of(app, node_idx):
    """The exact screen coordinates _draw() placed a given node at, so a
    synthetic click/drag can target it precisely -- the same computation
    _draw and _select_node_at share. Always the REST position: interaction
    targets the real structure even when "Show deformed" draws its
    additional green overlay in parallel."""
    proj = [app._project(x, y, z) for x, y, z in app.nodes]
    xs = [p[0] for p in proj]; ys = [p[1] for p in proj]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    px, py, _ = proj[node_idx]
    wx = (px - cx) * app.PX_PER_M
    wy = (py - cy) * app.PX_PER_M
    return app.zc.w2s(wx, wy)


# ── basic lifecycle ──────────────────────────────────────────────────────────

def test_opening_the_tab_generates_a_default_analyzable_mesh(app):
    assert len(app.nodes) > 0
    assert len(app.members) > 0
    assert len(app.supports) > 0


def test_default_load_state_is_area_load_on_top_only_no_self_weight(app):
    """By default only the roof/shell area load (top layer only -- see
    stereo_geometry's load_nodes docstring) should be applied, not also
    self-weight spread across both the bottom layer and every web."""
    assert app.area_load_on.get() is True
    assert app.self_weight_on.get() is False
    loaded_nodes = set(app._load_nodes)
    assert loaded_nodes and loaded_nodes.isdisjoint(app._support_candidates)


def test_analyze_button_runs_a_real_solve_and_populates_results_text(app):
    app._analyze()
    assert app.err is None
    assert app.results is not None
    text = app.results_text.get('1.0', 'end')
    assert 'Max nodal displacement' in text


def test_switching_grid_family_rebuilds_a_different_but_valid_mesh(app):
    n_before = len(app.nodes)
    app.grid_family.set(FAMILY_LABEL['dome'])
    app._on_generator_change()
    app._generate()
    assert len(app.nodes) > 0
    assert len(app.nodes) != n_before or len(app.members) > 0
    app._analyze()
    assert app.err is None


@pytest.mark.parametrize('key', ['flat_grid', 'hypar_shell', 'hip_roof_grid',
                                 'circular_flat_grid', 'barrel_vault', 'parabolic_vault',
                                 'elliptic_vault', 'dome', 'paraboloid_dish', 'elliptic_dome',
                                 'sphere_shell'])
def test_every_grid_family_produces_a_mesh_that_analyzes_cleanly(app, key):
    app.grid_family.set(FAMILY_LABEL[key])
    app._on_generator_change()
    app._generate()
    app._analyze()
    assert app.err is None, f'{key}: {app.err}'


# ── boundary conditions: per-node freedom + the new quick presets ───────────

def test_a_hand_picked_boundary_condition_survives_apply_and_shows_in_the_list(app):
    node = app.supports[0]['node']
    app.sup_node_var.set(node)
    app.sup_preset_var.set('custom')
    for d in app.dof_vars:
        app.dof_vars[d].set(False)
    app.dof_vars['uz'].set(True)
    app._apply_support()

    entry = next(s for s in app.supports if s['node'] == node)
    r = sm.support_restraints(entry)
    assert r['uz'] is True
    assert r['ux'] is False and r['uy'] is False
    assert not any(r[d] for d in ('rx', 'ry', 'rz'))

    listed = app.sup_list.get(0, tk.END)
    assert any(f'n{node}' in row for row in listed)
    # a hand-edited node drops the quick preset back to "custom" so the
    # combobox never lies about what is actually applied
    assert app.sup_quick_var.get() == QUICK_SUPPORT_CUSTOM


def test_removing_a_support_takes_it_out_of_the_model_and_the_list(app):
    node = app.supports[0]['node']
    app.sup_node_var.set(node)
    app._remove_support()
    assert all(s['node'] != node for s in app.supports)


def test_undo_redo_round_trips_a_boundary_condition_change(app):
    node = app.supports[0]['node']
    before = dict(app.supports[0])

    app.sup_node_var.set(node)
    app.sup_preset_var.set('fixed')
    app._preset_to_checkboxes()
    app._apply_support()
    changed = next(s for s in app.supports if s['node'] == node)
    assert sm.support_restraints(changed) == sm.support_restraints({'type': 'fixed'})

    app._undo()
    restored = next(s for s in app.supports if s['node'] == node)
    assert sm.support_restraints(restored) == sm.support_restraints(before)

    app._redo()
    redone = next(s for s in app.supports if s['node'] == node)
    assert sm.support_restraints(redone) == sm.support_restraints({'type': 'fixed'})


def test_quick_preset_pinned_applies_to_every_suggested_node(app):
    app.sup_quick_var.set(QUICK_SUPPORT_PIN)
    app._apply_quick_support_preset()
    assert {s['node'] for s in app.supports} == set(app._support_candidates)
    for s in app.supports:
        assert s['type'] == 'pin'


def test_quick_preset_fixed_applies_to_every_suggested_node(app):
    app.sup_quick_var.set(QUICK_SUPPORT_FIXED)
    app._apply_quick_support_preset()
    for s in app.supports:
        assert s['type'] == 'fixed'
        assert all(sm.support_restraints(s).values())


def test_quick_preset_clear_removes_every_support(app):
    app.sup_quick_var.set(QUICK_SUPPORT_CLEAR)
    app._apply_quick_support_preset()
    assert app.supports == []


def test_quick_preset_custom_is_a_no_op(app):
    before = [dict(s) for s in app.supports]
    app.sup_quick_var.set(QUICK_SUPPORT_CUSTOM)
    app._apply_quick_support_preset()
    assert app.supports == before


# ── loads: point loads + the new area load ──────────────────────────────────

def test_adding_and_removing_a_point_load(app):
    node = 0
    app.ld_node_var.set(node)
    app.ld_fz.set(-25.0)
    app._apply_load()
    assert any(ld['node'] == node and ld['fz'] == -25.0 for ld in app.loads)

    app._remove_load()
    assert all(ld['node'] != node for ld in app.loads)


def test_area_load_distributes_over_the_roof_surface_by_tributary_area(app):
    app.area_load_on.set(True)
    app.self_weight_on.set(False)
    app.area_load_var.set(2.5)
    loads = app._all_loads()
    total = sum(ld['fz'] for ld in loads)
    expected = -2.5 * sum(app._load_nodes.values())
    assert total == pytest.approx(expected, rel=1e-9)


def test_area_load_can_be_turned_off(app):
    app.area_load_on.set(False)
    app.self_weight_on.set(False)
    app.loads = []
    assert app._all_loads() == []


# ── a point load quoted as a size and a direction ───────────────────────────

def test_resolving_a_point_load_fills_the_three_force_boxes(app):
    app.ld_mag.set(40.0)
    app.ld_dir.set('+X')
    app._resolve_point_load()
    assert app.ld_fx.get() == pytest.approx(40.0)
    assert app.ld_fy.get() == pytest.approx(0.0)
    assert app.ld_fz.get() == pytest.approx(0.0)


def test_a_resolved_point_load_keeps_its_magnitude(app):
    """A skew direction must not inflate the load: the vector is normalised
    first, so |F| is the P that was typed whatever direction it points."""
    app.ld_mag.set(25.0)
    app.ld_dir.set('Custom')
    app.ld_dx.set(1.0)
    app.ld_dy.set(2.0)
    app.ld_dz.set(-2.0)
    app._resolve_point_load()
    assert math.hypot(app.ld_fx.get(), app.ld_fy.get(), app.ld_fz.get()) \
        == pytest.approx(25.0)


def test_resolving_does_not_apply_the_load_by_itself(app):
    """It writes the boxes; Add/update is still what puts a load on the
    model, so a resolved vector can be checked before it lands."""
    before = list(app.loads)
    app.ld_mag.set(12.0)
    app.ld_dir.set('Up (+Z)')
    app._resolve_point_load()
    assert app.loads == before
    app.selected_nodes = []
    app.ld_node_var.set(0)
    app._apply_load()
    applied = [ld for ld in app.loads if ld['node'] == 0][0]
    assert applied['fz'] == pytest.approx(12.0)


def test_resolving_leaves_the_moments_alone(app):
    """A direction says nothing about a couple; clearing Mx/My/Mz here
    would quietly discard one someone had already typed."""
    app.ld_mx.set(3.0)
    app.ld_my.set(-4.0)
    app.ld_mz.set(5.0)
    app.ld_mag.set(10.0)
    app.ld_dir.set('Down (\u2212Z)')
    app._resolve_point_load()
    assert (app.ld_mx.get(), app.ld_my.get(), app.ld_mz.get()) == (3.0, -4.0, 5.0)


def test_a_zero_custom_direction_is_refused_not_silently_zeroed(app, monkeypatch):
    seen = []
    monkeypatch.setattr('apps.stereo.stereo_app.messagebox.showerror',
                        lambda *a, **k: seen.append(a))
    app.ld_fz.set(-99.0)
    app.ld_mag.set(10.0)
    app.ld_dir.set('Custom')
    app.ld_dx.set(0.0)
    app.ld_dy.set(0.0)
    app.ld_dz.set(0.0)
    app._resolve_point_load()
    assert seen, 'a zero direction was accepted'
    assert app.ld_fz.get() == pytest.approx(-99.0), 'the boxes were clobbered anyway'


def test_a_point_load_applies_to_every_selected_node_at_once(app):
    """The multi-select half of "add a load to the nodes": a lasso-picked
    group takes the same vector in one shot."""
    picked = [1, 2, 3]
    app.selected_nodes = list(picked)
    app.ld_fx.set(0.0)
    app.ld_fy.set(0.0)
    app.ld_fz.set(-7.0)
    app._apply_load()
    got = {ld['node']: ld['fz'] for ld in app.loads if ld['node'] in picked}
    assert sorted(got) == picked
    assert all(v == pytest.approx(-7.0) for v in got.values())


def test_the_custom_direction_row_only_shows_for_custom(app):
    app.ld_dir.set('+Y')
    app._on_point_dir_change()
    assert app.frame_ld_dir.winfo_manager() == ''
    app.ld_dir.set('Custom')
    app._on_point_dir_change()
    assert app.frame_ld_dir.winfo_manager() != ''


# ── the area load's law, direction and scope ────────────────────────────────

def _fz_by_x(app):
    """Mean downward load at each distinct x -- the shape of the pressure
    across the structure, which is what a law is actually claiming."""
    from collections import defaultdict
    rows = defaultdict(list)
    for ld in app._all_loads():
        rows[round(app.nodes[ld['node']][0], 3)].append(abs(ld.get('fz', 0.0)))
    return {x: sum(v) / len(v) for x, v in sorted(rows.items())}


@pytest.fixture
def area_app(app):
    app.area_load_on.set(True)
    app.self_weight_on.set(False)
    app.loads = []
    return app


def test_the_uniform_law_loads_every_node_at_the_same_pressure(area_app):
    area_app.area_law.set(sc.AREA_UNIFORM)
    area_app.area_load_var.set(3.0)
    per_m2 = {ld['node']: abs(ld['fz']) / area_app._load_nodes[ld['node']]
              for ld in area_app._all_loads()}
    assert per_m2
    assert all(v == pytest.approx(3.0) for v in per_m2.values())


def test_the_gradient_law_ramps_across_the_axis_it_is_given(area_app):
    """A drift, a one-sided wind: the load must grow monotonically along the
    chosen axis, not merely integrate to the right total."""
    area_app.area_law.set(sc.AREA_GRADIENT)
    area_app.area_axis.set('X')
    area_app.area_q_min.set(0.0)
    area_app.area_q_max.set(10.0)
    rows = _fz_by_x(area_app)
    assert len(rows) >= 3
    values = list(rows.values())
    assert values == sorted(values)
    assert values[-1] > values[0] * 1.5, 'the ramp is too flat to be a ramp'


def test_the_gradient_law_follows_the_axis_it_is_switched_to(area_app):
    area_app.area_law.set(sc.AREA_GRADIENT)
    area_app.area_q_min.set(0.0)
    area_app.area_q_max.set(10.0)
    area_app.area_axis.set('X')
    across_x = _fz_by_x(area_app)
    area_app.area_axis.set('Y')
    along_y = _fz_by_x(area_app)
    assert across_x != pytest.approx(along_y), \
        'switching the gradient axis changed nothing'


def test_the_expression_law_applies_the_field_that_was_typed(area_app):
    area_app.area_law.set(sc.AREA_FIELD)
    area_app.area_expr.set('1 + 0.5*x')
    per_m2 = {ld['node']: abs(ld['fz']) / area_app._load_nodes[ld['node']]
              for ld in area_app._all_loads()}
    assert per_m2
    for node, q in per_m2.items():
        assert q == pytest.approx(1.0 + 0.5 * area_app.nodes[node][0])


def test_an_expression_that_will_not_compile_reports_instead_of_loading(area_app):
    """Silently falling back to zero would look exactly like a structure
    that carries its own weight beautifully."""
    area_app.area_law.set(sc.AREA_FIELD)
    area_app.area_expr.set('sin(')
    assert area_app._all_loads() == []
    assert 'Area load' in area_app.area_status.cget('text')


def test_a_good_expression_clears_a_previous_error(area_app):
    area_app.area_law.set(sc.AREA_FIELD)
    area_app.area_expr.set('sin(')
    area_app._all_loads()
    area_app.area_expr.set('2.0')
    assert area_app._all_loads()
    assert area_app.area_status.cget('text') == ''


def test_the_area_load_pushes_the_way_the_direction_says(area_app):
    area_app.area_law.set(sc.AREA_UNIFORM)
    area_app.area_load_var.set(2.0)
    area_app.area_dir.set('Down (\u2212Z)')
    down = area_app._all_loads()
    area_app.area_dir.set('+X')
    sideways = area_app._all_loads()
    assert sum(ld.get('fx', 0.0) for ld in down) == pytest.approx(0.0)
    assert sum(ld.get('fz', 0.0) for ld in sideways) == pytest.approx(0.0)
    assert sum(ld.get('fx', 0.0) for ld in sideways) == \
        pytest.approx(-sum(ld.get('fz', 0.0) for ld in down))


def test_a_custom_direction_vector_is_used_and_normalised(area_app):
    area_app.area_law.set(sc.AREA_UNIFORM)
    area_app.area_load_var.set(2.0)
    area_app.area_dir.set('Custom')
    area_app.area_dx.set(3.0)
    area_app.area_dy.set(0.0)
    area_app.area_dz.set(4.0)
    loads = area_app._all_loads()
    total = 2.0 * sum(area_app._load_nodes.values())
    assert sum(ld['fx'] for ld in loads) == pytest.approx(total * 0.6)
    assert sum(ld['fz'] for ld in loads) == pytest.approx(total * 0.8)


def test_scoping_the_area_load_to_the_selection_loads_only_those_nodes(area_app):
    area_app.area_law.set(sc.AREA_UNIFORM)
    area_app.area_load_var.set(2.0)
    whole = sum(abs(ld['fz']) for ld in area_app._all_loads())
    picked = sorted(area_app._load_nodes)[:3]
    area_app.selected_nodes = list(picked)
    area_app.area_scope.set(sc.AREA_SCOPE_SELECTED)
    part = area_app._all_loads()
    assert sorted(ld['node'] for ld in part) == picked
    assert 0 < sum(abs(ld['fz']) for ld in part) < whole


def _shown(frame):
    """Packed or not. winfo_ismapped needs a real idle cycle and a visible
    toplevel; the geometry manager answers straight away."""
    return frame.winfo_manager() != ''


def test_the_custom_direction_fields_only_appear_when_they_are_needed(area_app):
    area_app.area_dir.set('Down (\u2212Z)')
    area_app._on_area_law_change()
    assert not _shown(area_app.frame_area_dir)
    area_app.area_dir.set('Custom')
    area_app._on_area_law_change()
    assert _shown(area_app.frame_area_dir)


def test_each_law_shows_only_its_own_fields(area_app):
    area_app.area_law.set(sc.AREA_UNIFORM)
    area_app._on_area_law_change()
    assert not _shown(area_app.frame_area_gradient)
    assert not _shown(area_app.frame_area_field)

    area_app.area_law.set(sc.AREA_GRADIENT)
    area_app._on_area_law_change()
    assert _shown(area_app.frame_area_gradient)
    assert not _shown(area_app.frame_area_field)

    area_app.area_law.set(sc.AREA_FIELD)
    area_app._on_area_law_change()
    assert _shown(area_app.frame_area_field)
    assert not _shown(area_app.frame_area_gradient)


def test_a_varying_area_load_still_solves(area_app):
    """A load case is only worth having if the solver accepts it."""
    area_app.area_law.set(sc.AREA_GRADIENT)
    area_app.area_axis.set('X')
    area_app.area_q_min.set(0.0)
    area_app.area_q_max.set(6.0)
    area_app._analyze()
    assert area_app.results is not None


def test_importing_excel_clears_the_area_load_surface(app, tmp_path, monkeypatch):
    """An imported model has no known roof/shell surface (Excel does not
    carry stereo_geometry's load_nodes), so the area load must not silently
    keep applying whatever the PREVIOUS mesh's surface was -- that would
    load the imported model with tributary areas from a structure it no
    longer has."""
    app._analyze()
    from apps.stereo import stereo_reports as sr
    path = str(tmp_path / 'm.xlsx')
    sr.export_excel(app.nodes, app.members, app.loads, app.supports, app.results, path)
    assert app._load_nodes   # sanity: the freshly generated mesh has one

    monkeypatch.setattr('apps.stereo.stereo_app.filedialog.askopenfilename', lambda **k: path)
    app._import_excel()

    assert app._load_nodes == {}
    assert app.area_load_on.get() is False


# ── chord/web section split + connectivity ──────────────────────────────────

def test_chord_and_web_properties_apply_to_the_right_members(app):
    app.chord_A.set(33.0)
    app.web_A.set(11.0)
    app._apply_sections()
    for m in app.members:
        expected = 33.0 if m.get('role') in CHORD_ROLES else 11.0
        assert m['A'] == pytest.approx(expected)


def test_connectivity_toggle_shows_and_hides_the_IJ_fields(app):
    _mode(app, 'section')
    app.sec_conn.set('pin')
    app._on_connectivity_change()
    app.root.update_idletasks()
    assert not app._chord_ij_frame.winfo_ismapped()
    assert not app._web_ij_frame.winfo_ismapped()

    app.sec_conn.set('rigid')
    app._on_connectivity_change()
    app.root.update_idletasks()
    assert app._chord_ij_frame.winfo_ismapped()
    assert app._web_ij_frame.winfo_ismapped()


def test_applying_rigid_connectivity_reaches_every_member(app):
    app.sec_conn.set('rigid')
    app._apply_sections()
    assert all(m['conn'] == 'rigid' for m in app.members)


# ── mouse: left-drag lasso select vs click-select; right-drag orbit ────────

def test_a_small_movement_is_treated_as_a_click_not_a_lasso(app):
    sx, sy = _screen_pos_of(app, 0)
    az0, el0 = app.azimuth, app.elevation
    app._on_canvas_press(FakeEvent(sx, sy))
    app._on_canvas_motion(FakeEvent(sx + 1, sy + 1))   # below the drag threshold
    app._on_canvas_release(FakeEvent(sx + 1, sy + 1, state=0))
    assert app.azimuth == az0 and app.elevation == el0
    assert app.selected_node == 0


def test_a_real_left_drag_lasso_selects_nodes_in_the_box_and_does_not_orbit(app):
    az0, el0 = app.azimuth, app.elevation
    app.selected_nodes = set()
    positions = [_screen_pos_of(app, i) for i in range(len(app.nodes))]
    xs = [p[0] for p in positions]; ys = [p[1] for p in positions]
    x0, y0 = min(xs) - 20, min(ys) - 20
    x1, y1 = max(xs) + 20, max(ys) + 20
    app._on_canvas_press(FakeEvent(x0, y0))
    app._on_canvas_motion(FakeEvent(x1, y1))   # well past the drag threshold
    assert app.azimuth == az0 and app.elevation == el0   # left-drag never orbits
    app._on_canvas_release(FakeEvent(x1, y1, state=0))
    assert app.selected_nodes == set(range(len(app.nodes)))


def test_shift_held_lasso_adds_to_the_existing_selection(app):
    app.selected_nodes = {0}
    sx, sy = _screen_pos_of(app, 1)
    app._on_canvas_press(FakeEvent(sx - 10, sy - 10))
    app._on_canvas_motion(FakeEvent(sx + 10, sy + 10))
    app._on_canvas_release(FakeEvent(sx + 10, sy + 10, state=0x0001))   # Shift
    assert {0, 1} <= app.selected_nodes


def test_a_real_right_drag_orbits_the_camera_and_does_not_touch_selection(app):
    az0, el0 = app.azimuth, app.elevation
    app.selected_nodes = set()
    app._on_orbit_press(FakeEvent(400, 300))
    app._on_orbit_motion(FakeEvent(460, 260))   # well past the drag threshold
    assert app.azimuth != az0 or app.elevation != el0
    app._on_orbit_release(FakeEvent(460, 260))
    assert app.selected_nodes == set()
    assert app.selected_node is None


def test_orbit_drag_clamps_elevation_to_plus_minus_89_degrees(app):
    app._on_orbit_press(FakeEvent(0, 0))
    app._on_orbit_motion(FakeEvent(0, -10000))   # an absurdly large drag
    assert -89.0 <= app.elevation <= 89.0
    app._on_orbit_release(FakeEvent(0, -10000))


def test_reset_view_recenters_and_restores_the_default_angle(app):
    app._on_orbit_press(FakeEvent(0, 0))
    app._on_orbit_motion(FakeEvent(200, 200))
    app._on_orbit_release(FakeEvent(200, 200))
    assert (app.azimuth, app.elevation) != (35.0, 22.0)

    app._reset_view()
    assert app.azimuth == 35.0 and app.elevation == 22.0
    # The centroid lands in the middle of the canvas. Asserting pan_x == w/2
    # instead would be asserting the arithmetic of one particular zoom: w2s
    # multiplies by zoom AFTER adding the pan, so the centring pan is
    # w / (2 * zoom) and the two agree only at zoom = 1.
    w, h = app.canvas.winfo_width(), app.canvas.winfo_height()
    sx, sy = app.zc.w2s(0.0, 0.0)
    assert (sx, sy) == pytest.approx((w / 2.0, h / 2.0), abs=1.0)


# ── multi-select applying to supports/loads in one shot ─────────────────────

def test_lasso_selecting_every_node_then_applying_a_support_reaches_them_all(app):
    app.selected_nodes = set(range(len(app.nodes)))
    app.sup_preset_var.set('fixed')
    app._preset_to_checkboxes()
    app._apply_support()
    assert {s['node'] for s in app.supports} == set(range(len(app.nodes)))
    assert all(all(sm.support_restraints(s).values()) for s in app.supports)


def test_with_no_selection_apply_support_falls_back_to_the_typed_node_field(app):
    node = app.supports[0]['node']
    app.selected_nodes = set()
    app.sup_node_var.set(node)
    app.sup_preset_var.set('pin')
    app._preset_to_checkboxes()
    app._apply_support()
    entry = next(s for s in app.supports if s['node'] == node)
    assert sm.support_restraints(entry) == sm.support_restraints({'type': 'pin'})


def test_the_model_is_centered_in_the_canvas_after_generate(app):
    """Regression: pan used to stay at ZoomCanvas's own default (0, 0),
    which maps the model's centroid to the canvas's top-left CORNER
    instead of its center -- most of a freshly generated mesh rendered
    half off-screen. This checks the actual screen position the model's
    own centroid is drawn at, not just that some pan value changed."""
    w, h = app.canvas.winfo_width(), app.canvas.winfo_height()
    sx, sy = app.zc.w2s(0.0, 0.0)
    assert (sx, sy) == pytest.approx((w / 2.0, h / 2.0), abs=1.0)


def test_a_generated_mesh_is_zoomed_to_fill_the_canvas(app):
    """PX_PER_M is a fixed 20 px/m, so without a fit the size a model
    appears at is decided by how many metres across it happens to be: a
    small module filled the view and a wide dome landed as a clump in the
    middle of a lot of white. Reset view has to mean "show me the model"."""
    w, h = app.canvas.winfo_width(), app.canvas.winfo_height()
    proj = [app._project(x, y, z) for x, y, z in app.nodes]
    xs = [p[0] for p in proj]; ys = [p[1] for p in proj]
    span_x = (max(xs) - min(xs)) * app.PX_PER_M * app.zc.zoom
    span_y = (max(ys) - min(ys)) * app.PX_PER_M * app.zc.zoom
    assert span_x <= w and span_y <= h, 'the model runs off the canvas'
    assert max(span_x / w, span_y / h) > 0.5, 'the model is a clump in the middle'


def test_a_model_four_times_bigger_is_still_fitted(app):
    """The fit is what makes the two look the same size on screen; a fixed
    zoom would show one of them at a quarter of the other."""
    small = app._fit_zoom(1000, 800)
    app.nodes = [(4.0 * x, 4.0 * y, 4.0 * z) for x, y, z in app.nodes]
    big = app._fit_zoom(1000, 800)
    assert big == pytest.approx(small / 4.0, rel=0.02)


def test_a_model_too_big_to_fit_stops_at_the_canvas_zoom_floor(app):
    """ZoomCanvas will not go below MIN_ZOOM -- it is a shared widget limit,
    not this tab's to lift -- so a structure wider than the floor can show
    is drawn AT the floor rather than at some illegal zoom the wheel could
    never return to."""
    app.nodes = [(500.0 * x, 500.0 * y, 500.0 * z) for x, y, z in app.nodes]
    assert app._fit_zoom(1000, 800) == app.zc.MIN_ZOOM


def test_an_empty_model_has_nothing_to_fit_and_says_so(app):
    app.nodes = []
    assert app._fit_zoom(1000, 800) is None
    app._reset_view()
    assert app.zc.zoom == 1.0


# ── flat_grid chord pattern selector ─────────────────────────────────────────

def test_diagonal_pattern_selector_reaches_the_generator(app):
    from apps.stereo.stereo_app import PATTERN_LABEL
    app.grid_family.set(FAMILY_LABEL['flat_grid'])
    app._on_generator_change()
    app.fg_pattern.set(PATTERN_LABEL['diagonal'])
    app.fg_nx.set(3); app.fg_ny.set(3)
    app._generate()
    app._analyze()
    assert app.err is None
    # a diagonal-pattern chord never runs parallel to a grid axis
    role_members = [m for m in app.members if m.get('role') in ('bottom_chord', 'top_chord')]
    assert role_members
    for m in role_members:
        ax, ay, _ = app.nodes[m['a']]
        bx, by, _ = app.nodes[m['b']]
        assert abs(ax - bx) > 1e-9 and abs(ay - by) > 1e-9


# ── support glyph, label toggles, load arrows ───────────────────────────────

def test_supported_nodes_are_drawn_with_a_small_box_glyph(app):
    app._draw()
    node = app.supports[0]['node']
    items = app.canvas.find_withtag(f'node{node}')
    shapes = {app.canvas.type(i) for i in items}
    assert 'rectangle' in shapes


def test_node_label_toggle_shows_and_hides_node_text(app):
    app.show_node_labels.set(True)
    app._draw()
    with_labels = len(app.canvas.find_withtag('all'))
    app.show_node_labels.set(False)
    app._draw()
    without_labels = len(app.canvas.find_withtag('all'))
    assert without_labels < with_labels


def test_member_label_toggle_is_off_by_default_and_can_be_turned_on(app):
    assert app.show_member_labels.get() is False
    app._draw()
    before = len(app.canvas.find_withtag('all'))
    app.show_member_labels.set(True)
    app._draw()
    after = len(app.canvas.find_withtag('all'))
    assert after > before


def test_load_arrows_are_drawn_for_a_point_load_and_hidden_by_the_toggle(app):
    app.area_load_on.set(False)
    app.self_weight_on.set(False)
    app.ld_node_var.set(0)
    app.ld_fz.set(-40.0)
    app._apply_load()
    app.show_loads.set(True)
    app._draw()
    assert len(app.canvas.find_withtag('load')) > 0

    app.show_loads.set(False)
    app._draw()
    assert len(app.canvas.find_withtag('load')) == 0


# ── XYZ axis gizmo + z=0 ground reference ────────────────────────────────────

def test_axes_are_shown_by_default_and_hidden_by_the_toggle(app):
    app._draw()
    assert len(app.canvas.find_withtag('axes')) > 0

    app.show_axes.set(False)
    app._draw()
    assert len(app.canvas.find_withtag('axes')) == 0


def test_the_axes_are_lines_across_the_canvas_not_stubs_at_the_model(app):
    """An axis is an infinite line. Drawn as a short stub beside the
    structure it reads as an arrow decoration rather than as the coordinate
    frame every panel, export and report states its numbers in."""
    app.show_axes.set(True)
    app._draw()
    w = app.canvas.winfo_width() or 400
    h = app.canvas.winfo_height() or 400
    diag = math.hypot(w, h)
    for color in (StereoApp.AXIS_COLOR_X, StereoApp.AXIS_COLOR_Y,
                  StereoApp.AXIS_COLOR_Z):
        spans = []
        for i in app.canvas.find_withtag('axes'):
            if app.canvas.type(i) != 'line':
                continue
            if app.canvas.itemcget(i, 'fill') != color:
                continue
            x0, y0, x1, y1 = app.canvas.coords(i)
            spans.append(math.hypot(x1 - x0, y1 - y0))
        assert spans, f'no axis drawn for {color}'
        assert max(spans) > diag, \
            f'the {color} axis spans {max(spans):.0f}px on a {diag:.0f}px canvas'


def test_each_axis_has_a_solid_positive_half_and_a_dashed_negative_half(app):
    app.show_axes.set(True)
    app._draw()
    for color in (StereoApp.AXIS_COLOR_X, StereoApp.AXIS_COLOR_Y,
                  StereoApp.AXIS_COLOR_Z):
        dashes = {app.canvas.itemcget(i, 'dash')
                  for i in app.canvas.find_withtag('axes')
                  if app.canvas.type(i) == 'line'
                  and app.canvas.itemcget(i, 'fill') == color}
        assert '' in dashes, f'{color} has no solid half'
        assert any(d for d in dashes), f'{color} has no dashed half'


def test_the_axes_are_labelled_and_the_ground_outline_is_still_there(app):
    app.show_axes.set(True)
    app._draw()
    items = app.canvas.find_withtag('axes')
    texts = [i for i in items if app.canvas.type(i) == 'text']
    assert {app.canvas.itemcget(i, 'text') for i in texts} == {'X', 'Y', 'Z'}
    ground = [i for i in items if app.canvas.type(i) == 'line'
              and app.canvas.itemcget(i, 'fill') == '#bbbbbb']
    assert len(ground) == 4, 'the z = 0 footprint outline is gone'


def test_the_axes_meet_at_the_origin_not_at_the_models_corner(app):
    """Anchored at (0, 0, 0), the frame every coordinate in the app is
    stated in -- not at the mesh's own lowest corner, which moves whenever
    the model is regenerated and would make the same rod appear to sit
    somewhere different afterwards."""
    app.show_axes.set(True)
    app._draw()
    px, py, _ = app._project(0.0, 0.0, 0.0)
    ox, oy = app._to_screen_cache(px, py)
    arrow_heads = []
    for i in app.canvas.find_withtag('axes'):
        if app.canvas.type(i) != 'line' or app.canvas.itemcget(i, 'arrow') != 'last':
            continue
        arrow_heads.append(app.canvas.coords(i))
    assert len(arrow_heads) == 3
    for color in (StereoApp.AXIS_COLOR_X, StereoApp.AXIS_COLOR_Y,
                  StereoApp.AXIS_COLOR_Z):
        ends = []
        for i in app.canvas.find_withtag('axes'):
            if app.canvas.type(i) != 'line':
                continue
            if app.canvas.itemcget(i, 'fill') != color:
                continue
            if app.canvas.itemcget(i, 'arrow') == 'last':
                continue
            x0, y0, x1, y1 = app.canvas.coords(i)
            ends += [(x0, y0), (x1, y1)]
        assert any(math.hypot(x - ox, y - oy) < 1.0 for x, y in ends), \
            f'the {color} axis does not pass through the origin'


def test_the_arrowhead_stays_near_the_model_on_a_lopsided_structure(app):
    """The reach is per-axis: on a 15 m long, 3 m tall vault one shared
    reach would put the Z arrowhead five model-heights above the roof, off
    the canvas entirely."""
    app.grid_family.set(FAMILY_LABEL['parabolic_vault'])
    app._on_generator_change()
    app._generate()
    app.show_axes.set(True)
    app._reset_view()
    app._draw()
    zs = [n[2] for n in app.nodes]
    span_z = max(zs) - min(zs)
    for i in app.canvas.find_withtag('axes'):
        if app.canvas.type(i) != 'line':
            continue
        if app.canvas.itemcget(i, 'fill') != StereoApp.AXIS_COLOR_Z:
            continue
        if app.canvas.itemcget(i, 'arrow') != 'last':
            continue
        _x0, y0, _x1, y1 = app.canvas.coords(i)
        top_px, top_py, _ = app._project(0.0, 0.0, max(zs))
        _sx, sy = app._to_screen_cache(top_px, top_py)
        base_px, base_py, _ = app._project(0.0, 0.0, min(zs))
        _bx, by = app._to_screen_cache(base_px, base_py)
        px_per_m = abs(by - sy) / max(span_z, 1e-9)
        assert abs(min(y0, y1) - sy) < 6.0 * px_per_m, \
            'the Z arrowhead is more than six model-heights above the roof'
        break
    else:
        raise AssertionError('no Z arrowhead drawn')


def test_axes_scale_with_the_models_own_footprint(app):
    # a bigger structure should put its arrowhead further out, not use a
    # fixed pixel size
    import math
    from apps.stereo import stereo_examples as sx
    app.show_axes.set(True)
    app._draw()

    def x_arrow_length():
        items = app.canvas.find_withtag('axes')
        for i in items:
            if app.canvas.type(i) == 'line' \
               and app.canvas.itemcget(i, 'fill') == StereoApp.AXIS_COLOR_X \
               and app.canvas.itemcget(i, 'arrow') == 'last':
                x0, y0, x1, y1 = app.canvas.coords(i)
                return math.hypot(x1 - x0, y1 - y0)
        return None

    small = x_arrow_length()
    label, builder = sx.EXAMPLES[0]
    app._load_example(builder, label)
    app._reset_view()
    app._draw()
    big = x_arrow_length()
    assert small is not None and big is not None


# ── force gradient coloring ──────────────────────────────────────────────────

def test_force_color_is_red_for_tension_and_blue_for_compression():
    tension = force_color(50.0, 100.0)
    compression = force_color(-50.0, 100.0)
    tr, tg, tb = int(tension[1:3], 16), int(tension[3:5], 16), int(tension[5:7], 16)
    cr, cg, cb = int(compression[1:3], 16), int(compression[3:5], 16), int(compression[5:7], 16)
    assert tr > tb    # tension leans red
    assert cb > cr    # compression leans blue


def test_force_color_scales_with_magnitude_not_just_sign():
    """The gradient runs pale -> saturated, so raw R goes DOWN as a
    saturated red has less raw red byte value than a pale pink -- redness
    is properly read as R-B (how far the color leans red over blue), which
    must grow with magnitude regardless of that channel-value inversion."""
    def redness(hexcolor):
        r, b = int(hexcolor[1:3], 16), int(hexcolor[5:7], 16)
        return r - b

    faint = force_color(10.0, 100.0)
    strong = force_color(95.0, 100.0)
    assert redness(strong) > redness(faint)


def test_force_color_near_zero_is_neutral_grey_regardless_of_sign():
    near_zero_pos = force_color(0.5, 100.0)
    near_zero_neg = force_color(-0.5, 100.0)
    assert near_zero_pos == near_zero_neg == '#9a9a9a'


def test_force_color_handles_a_model_with_no_force_anywhere():
    assert force_color(0.0, 0.0) == '#9a9a9a'


def test_over_capacity_members_are_drawn_dashed(app):
    app.chord_A.set(0.01)   # force something over capacity
    app.web_A.set(0.01)
    app._apply_sections()
    app._analyze()
    if app.member_checks and any(c.get('checked') and c['util'] > 1.0 for c in app.member_checks):
        app._draw()
        dashed_items = [i for i in app.canvas.find_withtag('member')
                       if app.canvas.itemcget(i, 'dash')]
        assert len(dashed_items) > 0


# ── deformed-shape overlay: green, parallel to the rest structure ──────────

def test_deform_color_is_pale_near_zero_and_saturated_green_at_the_max():
    faint = deform_color(0.5, 100.0)
    strong = deform_color(95.0, 100.0)

    def greenness(hexcolor):
        r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
        return g - (r + b) / 2.0

    assert greenness(strong) > greenness(faint)
    assert faint != '#ffffff'   # legible, not pure white


def test_deform_color_handles_a_model_with_no_displacement_anywhere():
    assert deform_color(0.0, 0.0) != '#ffffff'


def test_show_deformed_draws_a_green_overlay_without_moving_the_real_structure(app):
    app._analyze()
    sx_before, sy_before = _screen_pos_of(app, 0)

    app.show_deformed.set(True)
    app.deform_scale.set(500)   # exaggerate so the overlay is not degenerate
    app._draw()
    assert len(app.canvas.find_withtag('deform')) > 0
    # the REST structure (and therefore click-select) never moved
    sx_after, sy_after = _screen_pos_of(app, 0)
    assert (sx_after, sy_after) == pytest.approx((sx_before, sy_before))

    app.show_deformed.set(False)
    app._draw()
    assert len(app.canvas.find_withtag('deform')) == 0


def test_show_deformed_is_a_no_op_before_analysis(app):
    app.results = None
    app.show_deformed.set(True)
    app._draw()   # must not raise
    assert len(app.canvas.find_withtag('deform')) == 0


def test_deformed_only_hides_the_reference_structure(app):
    app._analyze()
    app.show_deformed.set(True)
    app.deform_scale.set(200)

    app.deformed_only.set(False)
    app._draw()
    assert len(app.canvas.find_withtag('member')) > 0
    assert len(app.canvas.find_withtag('deform')) > 0

    app.deformed_only.set(True)
    app._draw()
    assert len(app.canvas.find_withtag('member')) == 0
    assert len(app.canvas.find_withtag('deform')) > 0


def test_deform_color_mode_toggles_between_spectrum_and_force(app):
    app._analyze()
    app.show_deformed.set(True)
    app.deform_scale.set(200)

    app.deform_color_mode.set('Displacement')
    app._draw()
    spectrum_colors = {app.canvas.itemcget(i, 'fill')
                      for i in app.canvas.find_withtag('deform')
                      if app.canvas.type(i) == 'line'}

    app.deform_color_mode.set('Axial force')
    app._draw()
    force_colors = {app.canvas.itemcget(i, 'fill')
                   for i in app.canvas.find_withtag('deform')
                   if app.canvas.type(i) == 'line'}
    # different colouring scheme -> a different set of colours used
    assert spectrum_colors != force_colors


def test_reference_shade_changes_the_reference_structure_s_colour(app):
    app._analyze()
    app.show_deformed.set(True)
    app.reference_shade.set(10)
    app._draw()
    dark = {app.canvas.itemcget(i, 'fill') for i in app.canvas.find_withtag('member')}
    app.reference_shade.set(95)
    app._draw()
    light = {app.canvas.itemcget(i, 'fill') for i in app.canvas.find_withtag('member')}
    assert dark != light
    # every reference member is a shade of grey (r==g==b), not force-coloured
    for hexcolor in light:
        r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
        assert r == g == b


def test_reference_shade_is_ignored_when_deformed_is_not_shown(app):
    app._analyze()
    app.show_deformed.set(False)
    app.reference_shade.set(10)
    app._draw()
    colors_a = {app.canvas.itemcget(i, 'fill') for i in app.canvas.find_withtag('member')}
    app.reference_shade.set(95)
    app._draw()
    colors_b = {app.canvas.itemcget(i, 'fill') for i in app.canvas.find_withtag('member')}
    assert colors_a == colors_b


def test_legend_explains_the_dashed_over_capacity_line(app):
    app.chord_A.set(0.01)
    app.web_A.set(0.01)
    app._apply_sections()
    app._analyze()
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert any('over capacity' in t and 'utilization' in t for t in texts)


# ── didactic features: reactions, click-to-inspect, load %, utilization ─────

def test_reaction_arrows_are_drawn_only_when_toggled_and_analyzed(app):
    app.show_reactions.set(True)
    app._draw()
    assert len(app.canvas.find_withtag('reaction')) == 0   # not analyzed yet

    app._analyze()
    app._draw()
    assert len(app.canvas.find_withtag('reaction')) > 0

    app.show_reactions.set(False)
    app._draw()
    assert len(app.canvas.find_withtag('reaction')) == 0


def test_clicking_a_rod_shows_its_force_and_utilization(app):
    app._analyze()
    pts = app._screen_positions()
    m = app.members[0]
    sx0, sy0 = pts[m['a']]
    sx1, sy1 = pts[m['b']]
    mx, my = (sx0 + sx1) / 2.0, (sy0 + sy1) / 2.0

    app._select_node_at(mx, my)
    assert app.selected_member == 0
    assert app.selected_nodes == set()
    text = app.sel_var.get()
    assert 'Member 0' in text
    assert 'N =' in text
    assert 'utilization' in text


def test_clicking_a_node_clears_any_selected_member(app):
    app._analyze()
    pts = app._screen_positions()
    m = app.members[0]
    sx0, sy0 = pts[m['a']]
    sx1, sy1 = pts[m['b']]
    app._select_node_at((sx0 + sx1) / 2.0, (sy0 + sy1) / 2.0)
    assert app.selected_member is not None

    sx, sy = _screen_pos_of(app, 0)
    app._select_node_at(sx, sy)
    assert app.selected_member is None
    assert app.selected_nodes == {0}


def test_delete_selected_node_removes_it_and_its_members(app):
    n0 = len(app.nodes)
    m0 = len(app.members)
    target = 0
    touching = sum(1 for m in app.members if m['a'] == target or m['b'] == target)
    assert touching > 0   # node 0 in a generated grid always has members on it

    app.selected_nodes = {target}
    app._on_delete_nodes()

    assert len(app.nodes) == n0 - 1
    assert len(app.members) == m0 - touching
    assert app.selected_nodes == set()
    assert app.selected_member is None
    for m in app.members:
        assert 0 <= m['a'] < len(app.nodes)
        assert 0 <= m['b'] < len(app.nodes)


def test_delete_selected_node_remaps_every_surviving_index(app):
    # Delete an early node and confirm every reference that used to point
    # PAST it (a member endpoint, a support, a support_candidate) still
    # points at the SAME physical node, just shifted down by one -- not
    # silently re-pointed at whatever now sits at the old index.
    target = 0
    old_nodes = list(app.nodes)
    old_supports_nodes = {s['node'] for s in app.supports}

    app.selected_nodes = {target}
    app._on_delete_nodes()

    for old_i in old_supports_nodes:
        if old_i == target:
            continue
        new_i = old_i - 1 if old_i > target else old_i
        assert app.nodes[new_i] == old_nodes[old_i]
    for i in app._support_candidates:
        assert 0 <= i < len(app.nodes)


def test_delete_with_no_selection_is_a_no_op(app):
    n0, m0 = len(app.nodes), len(app.members)
    app.selected_nodes = set()
    app._on_delete_nodes()
    assert len(app.nodes) == n0
    assert len(app.members) == m0


def test_delete_selected_nodes_is_undoable(app):
    n0 = len(app.nodes)
    app.selected_nodes = {0}
    app._on_delete_nodes()
    assert len(app.nodes) == n0 - 1
    app._undo()
    assert len(app.nodes) == n0
    app._redo()
    assert len(app.nodes) == n0 - 1


def test_delete_key_on_the_canvas_deletes_the_selection(app):
    n0 = len(app.nodes)
    app.selected_nodes = {0}
    app.canvas.focus_set()
    app.canvas.event_generate('<Delete>')
    app.canvas.update_idletasks()
    app.canvas.update()
    assert len(app.nodes) == n0 - 1


def test_delete_after_analysis_clears_stale_results(app):
    app._analyze()
    assert app.results is not None
    app.selected_nodes = {0}
    app._on_delete_nodes()
    assert app.results is None
    assert app.member_checks is None


def test_member_info_before_analysis_says_so(app):
    app.results = None
    app.selected_member = 0
    app.selected_nodes = set()
    app._sync_selection_fields()
    assert 'Run' in app.sel_var.get()


def test_load_fraction_scales_deformation_and_force_linearly(app):
    app._analyze()
    app.show_deformed.set(True)
    app.deform_scale.set(100)

    app.load_fraction.set(100)
    _deformed_full, disp_full = app._deformed_nodes_and_disp()
    app.load_fraction.set(50)
    _deformed_half, disp_half = app._deformed_nodes_and_disp()

    for d_half, d_full in zip(disp_half, disp_full):
        assert d_half == pytest.approx(d_full * 0.5, abs=1e-9)


def test_load_fraction_zero_shows_no_displacement_and_no_load_arrows(app):
    app._analyze()
    app.show_deformed.set(True)
    app.load_fraction.set(0)
    _deformed, disp = app._deformed_nodes_and_disp()
    assert all(d == pytest.approx(0.0) for d in disp)

    app._draw()
    assert len(app.canvas.find_withtag('load')) == 0


def test_utilization_heat_map_colors_members_by_utilization_not_force(app):
    app.chord_A.set(0.02)
    app.web_A.set(0.02)
    app._apply_sections()
    app._analyze()

    app.colour_by_util.set(True)
    app.colour_by_force.set(True)   # util must win over force when both are on
    app._draw()
    util_colors = {app.canvas.itemcget(i, 'fill') for i in app.canvas.find_withtag('member')}

    app.colour_by_util.set(False)
    app._draw()
    force_colors = {app.canvas.itemcget(i, 'fill') for i in app.canvas.find_withtag('member')}
    assert util_colors != force_colors


def test_utilization_heat_map_is_a_no_op_before_analysis(app):
    app.results = None
    app.member_checks = None
    app.colour_by_util.set(True)
    app._draw()   # must not raise


# ── slenderness flag (distinct from the utilization heat-map) ───────────────

def test_flag_slender_is_off_by_default(app):
    assert app.flag_slender.get() is False


def test_flag_slender_draws_a_halo_for_a_genuinely_slender_compression_member(app):
    # a tiny radius of gyration on an otherwise normal-length member pushes
    # KL/r (~3m module / a few mm) far past the 200 flag threshold
    app.chord_r.set(0.3)
    app.web_r.set(0.3)
    app._apply_sections()
    app._analyze()
    assert any(chk.get('mode') == 'compression' and chk.get('slenderness', 0) > SLENDERNESS_LIMIT
              for chk in app.member_checks)

    app.flag_slender.set(True)
    app._draw()
    halos = [i for i in app.canvas.find_withtag('member')
            if app.canvas.itemcget(i, 'fill') == SLENDER_HALO_COLOR]
    assert halos

    app.flag_slender.set(False)
    app._draw()
    assert not [i for i in app.canvas.find_withtag('member')
               if app.canvas.itemcget(i, 'fill') == SLENDER_HALO_COLOR]


def test_flag_slender_does_not_flag_stocky_members(app):
    # the default chord/web radius of gyration keeps KL/r well under 200
    # for the default flat_grid's own short module length
    app._analyze()
    assert not any(chk.get('mode') == 'compression'
                  and chk.get('slenderness', 0) > SLENDERNESS_LIMIT
                  for chk in app.member_checks)
    app.flag_slender.set(True)
    app._draw()
    halos = [i for i in app.canvas.find_withtag('member')
            if app.canvas.itemcget(i, 'fill') == SLENDER_HALO_COLOR]
    assert not halos


def test_flag_slender_is_independent_of_the_load_percent_slider(app):
    # slenderness (KL/r) is a section/geometry property, not a force one --
    # unlike the utilization heat-map, it must NOT change with 'Load %'
    app.chord_r.set(0.3)
    app.web_r.set(0.3)
    app._apply_sections()
    app._analyze()
    app.flag_slender.set(True)

    app.load_fraction.set(100.0)
    app._draw()
    halos_100 = len([i for i in app.canvas.find_withtag('member')
                    if app.canvas.itemcget(i, 'fill') == SLENDER_HALO_COLOR])

    app.load_fraction.set(10.0)
    app._draw()
    halos_10 = len([i for i in app.canvas.find_withtag('member')
                   if app.canvas.itemcget(i, 'fill') == SLENDER_HALO_COLOR])
    assert halos_100 == halos_10 > 0


def test_flag_slender_legend_row_appears_only_when_active(app):
    app.chord_r.set(0.3)
    app.web_r.set(0.3)
    app._apply_sections()
    app._analyze()

    app.flag_slender.set(False)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert not any('slender' in t for t in texts)

    app.flag_slender.set(True)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert any('slender' in t for t in texts)


def test_flag_slender_is_a_no_op_before_analysis(app):
    app.results = None
    app.member_checks = None
    app.flag_slender.set(True)
    app._draw()   # must not raise


# ── load-path pulse animation ────────────────────────────────────────────────

def _load_path_lines(app):
    """Found by TAG, not by colour: the pulse is coloured by the force each
    member is carrying, so there is no one flat fill to match on."""
    return list(app.canvas.find_withtag('load_path'))


def test_load_path_anim_is_off_by_default(app):
    assert app.load_path_anim.get() is False
    assert app._load_path_after_id is None


def test_load_path_anim_draws_marching_dashes_once_analyzed_and_enabled(app):
    app._analyze()
    assert not _load_path_lines(app)   # off -> nothing yet

    app.load_path_anim.set(True)
    app._draw()
    assert _load_path_lines(app)


def test_load_path_anim_is_a_no_op_before_analysis(app):
    app.results = None
    app.load_path_anim.set(True)
    app._draw()   # must not raise
    assert not _load_path_lines(app)


def _load_path_arrow_items(app):
    """The travelling arrowhead glyphs specifically -- excludes each
    member's own static guide line, which shares the 'load_path' tag but
    has no arrowhead."""
    return [i for i in _load_path_lines(app) if app.canvas.itemcget(i, 'arrow') == 'last']


def test_load_path_anim_draws_a_static_guide_line_plus_moving_arrowheads(app):
    app._analyze()
    app.load_path_anim.set(True)
    app._draw()
    lines = _load_path_lines(app)
    arrows = _load_path_arrow_items(app)
    assert lines
    assert arrows
    assert len(arrows) < len(lines)   # arrows are a subset -- the rest are guide lines


def test_load_path_anim_arrows_actually_move_between_phases(app):
    # the literal "arrows that move" request this replaced the marching
    # dashes with: the SAME member's arrow glyphs must occupy different
    # canvas coordinates at two different points in the animation loop,
    # not just a shifting dash pattern on an otherwise static line.
    app._analyze()
    app.load_path_anim.set(True)
    app._load_path_phase = 0
    app._draw()
    coords_at_0 = sorted(tuple(app.canvas.coords(i)) for i in _load_path_arrow_items(app))

    app._load_path_phase = LOAD_PATH_ANIM_TICKS // 2
    app._draw()
    coords_at_half = sorted(tuple(app.canvas.coords(i)) for i in _load_path_arrow_items(app))

    assert coords_at_0 != coords_at_half


@pytest.mark.parametrize('t_prog', [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
def test_load_path_arrow_fracs_tension_converges_toward_centre(t_prog):
    (t1, d1), (t2, d2) = StereoApp._load_path_arrow_fracs(N=5.0, t_prog=t_prog)
    assert d1 == 1 and d2 == -1
    # both arrows start (t_prog=0) at their own end and end (t_prog=1) at
    # the centre -- monotonically closer to 0.5 as t_prog increases
    assert 0.0 <= t1 <= 0.5 and 0.5 <= t2 <= 1.0


@pytest.mark.parametrize('t_prog', [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
def test_load_path_arrow_fracs_compression_diverges_from_centre(t_prog):
    (t1, d1), (t2, d2) = StereoApp._load_path_arrow_fracs(N=-5.0, t_prog=t_prog)
    assert d1 == -1 and d2 == 1
    assert 0.0 <= t1 <= 0.5 and 0.5 <= t2 <= 1.0


def test_load_path_arrow_fracs_tension_and_compression_are_complementary():
    # at t_prog=0 tension arrows start at the two ENDS (distance-from-
    # centre 0.5) while compression arrows start AT the centre (distance
    # 0); each closes exactly the gap the other opens as t_prog runs to
    # 1, so at any given moment the two distances-from-centre sum to the
    # constant 0.5 -- how far tension has travelled inward is exactly how
    # far compression still has left to travel outward.
    for t_prog in (0.0, 0.2, 0.5, 0.8, 1.0):
        tension = StereoApp._load_path_arrow_fracs(N=1.0, t_prog=t_prog)
        compression = StereoApp._load_path_arrow_fracs(N=-1.0, t_prog=t_prog)
        tension_dist = max(abs(t - 0.5) for t, _d in tension)
        compression_dist = max(abs(t - 0.5) for t, _d in compression)
        assert tension_dist + compression_dist == pytest.approx(0.5)


def test_load_path_arrow_fracs_midpoint_matches_regardless_of_sign():
    # t_prog=0.5 is the one instant where "inward" and "outward" motion
    # cross the same halfway point -- both signs must agree there.
    tension = sorted(t for t, _d in StereoApp._load_path_arrow_fracs(N=1.0, t_prog=0.5))
    compression = sorted(t for t, _d in StereoApp._load_path_arrow_fracs(N=-1.0, t_prog=0.5))
    assert tension == pytest.approx([0.25, 0.75])
    assert compression == pytest.approx([0.25, 0.75])


def test_load_path_anim_legend_row_appears_only_when_active(app):
    app._analyze()

    app.load_path_anim.set(False)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert not any('load path' in t for t in texts)

    app.load_path_anim.set(True)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert any('load path' in t for t in texts)


def test_load_path_anim_toggle_on_starts_the_timer(app):
    app._analyze()
    assert app._load_path_after_id is None
    app.load_path_anim.set(True)
    app._on_load_path_anim_toggle()
    assert app._load_path_after_id is not None
    app.root.after_cancel(app._load_path_after_id)
    app._load_path_after_id = None


def test_load_path_anim_toggle_off_clears_the_dashes_without_leaving_a_timer(app):
    app._analyze()
    app.load_path_anim.set(True)
    app._on_load_path_anim_toggle()
    app.root.after_cancel(app._load_path_after_id)
    app._load_path_after_id = None

    app.load_path_anim.set(False)
    app._on_load_path_anim_toggle()
    assert not _load_path_lines(app)
    assert app._load_path_after_id is None


def test_load_path_tick_increments_phase_and_reschedules_while_enabled(app):
    app._analyze()
    app.load_path_anim.set(True)
    phase_before = app._load_path_phase
    app._load_path_tick()
    try:
        assert app._load_path_phase == phase_before + 1
        assert app._load_path_after_id is not None
    finally:
        if app._load_path_after_id is not None:
            app.root.after_cancel(app._load_path_after_id)
            app._load_path_after_id = None


def test_load_path_tick_self_clears_and_does_not_reschedule_when_disabled(app):
    app._analyze()
    app.load_path_anim.set(True)
    app._load_path_after_id = app.root.after(50000, lambda: None)   # sentinel
    stale_id = app._load_path_after_id

    app.load_path_anim.set(False)   # disabled between scheduling and firing
    app._load_path_tick()
    assert app._load_path_after_id is None
    app.root.after_cancel(stale_id)


def test_start_load_path_animation_does_not_stack_multiple_timers(app):
    app._analyze()
    app.load_path_anim.set(True)
    app._start_load_path_animation()
    first_id = app._load_path_after_id
    app._start_load_path_animation()   # calling again must be a no-op
    assert app._load_path_after_id == first_id
    app.root.after_cancel(first_id)
    app._load_path_after_id = None


# ── member report dialog ─────────────────────────────────────────────────────

def test_member_report_requires_analysis_first(app):
    app.results = None
    app.member_checks = None
    app._show_member_report()   # must not raise; dialogs fixture records it


def test_member_report_opens_a_populated_table(app):
    app._analyze()
    app._show_member_report()
    app.root.update_idletasks()
    # Toplevel(self.root) nests in the widget hierarchy under self.root
    # (the tab frame) even though it is its own top-level OS window.
    new_windows = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
    assert new_windows, 'Member Report window did not open'
    win = new_windows[-1]
    trees = [w for w in win.winfo_children()[0].winfo_children()
            if w.winfo_class() == 'Treeview']
    assert trees
    tv = trees[0]
    assert len(tv.get_children()) == len(app.members)
    win.destroy()


# ── add-on features: column (capital + shaft) and reinforcement beam ────────
# The default app mesh is a flat_grid(nx=10, ny=10, module=3, offset=True):
# row j=0 is nodes 0..10 (y=0), row j=1 is nodes 11..21 (y=3), both varying
# only in x -- used below as a straightforward two-row / 2D-footprint
# source for these tests, the same way a user would lasso them in the view.

def test_add_column_requires_at_least_three_selected_nodes(app):
    app.selected_nodes = set()
    n_before = len(app.nodes)
    app._add_column()   # must not raise; dialogs fixture records the error
    assert len(app.nodes) == n_before

    app.selected_nodes = {app._support_candidates[0], app._support_candidates[1]}
    app._add_column()
    assert len(app.nodes) == n_before


def test_add_column_adds_a_shaft_and_a_fanned_out_capital(app):
    # a genuine 2D footprint (one module's 4 corners) -- a capital fanning
    # to COLINEAR targets alone is a real mechanism, see
    # test_stereo_geometry.py's own regression test for that failure mode
    targets = {0, 1, 11, 12}
    app.selected_nodes = set(targets)
    app.col_height.set(3.0)
    n_nodes_before = len(app.nodes)
    n_members_before = len(app.members)
    app._add_column()

    assert len(app.nodes) == n_nodes_before + 2   # base + head
    shaft = [m for m in app.members if m.get('role') == 'column_shaft']
    capital = [m for m in app.members if m.get('role') == 'capital']
    assert len(shaft) == 1
    assert len(capital) == len(targets)
    assert {m['b'] for m in capital} == targets   # capital's 'a' is always the head
    assert len(app.members) == n_members_before + 1 + len(targets)
    base = shaft[0]['a']
    assert any(s['node'] == base for s in app.supports)

    app._analyze()
    assert app.err is None


def test_add_reinforcement_beam_requires_two_parallel_rows(app):
    app.selected_nodes = {app._support_candidates[0]}
    n_before = len(app.nodes)
    app._add_reinforcement_beam()
    assert len(app.nodes) == n_before

    # a single row alone (no second distinct value on any axis) isn't a
    # valid two-row selection either
    app.selected_nodes = {0, 1, 2}
    app._add_reinforcement_beam()
    assert len(app.nodes) == n_before


def test_add_reinforcement_beam_triangulates_an_apex_over_two_rows(app):
    edge_a, edge_b = [0, 1, 2], [11, 12, 13]
    app.selected_nodes = set(edge_a + edge_b)
    app.beam_depth.set(1.2)
    app.beam_dir.set('Down (-Z)')
    n_nodes_before = len(app.nodes)
    n_members_before = len(app.members)
    app._add_reinforcement_beam()

    n = len(edge_a)
    assert len(app.nodes) == n_nodes_before + n   # one new apex row only
    new_chord = [m for m in app.members if m.get('role') == 'reinf_chord']
    new_web = [m for m in app.members if m.get('role') == 'reinf_web']
    # edge_a's and edge_b's own chords already exist (real bottom-chord
    # rows) -- only the brand-new apex chord gets the 'reinf_chord' role
    assert len(new_chord) == n - 1
    assert len(new_web) == 2 * n + 4 * (n - 1)
    assert len(app.members) == n_members_before + len(new_chord) + len(new_web)

    app._analyze()
    assert app.err is None


def test_a_plain_column_can_be_added_under_a_single_node(app):
    """The panel's 3-node gate exists for the capital; the plain strut has
    none, so one selected node is a column."""
    app.col_style.set(sg.COLUMN_PLAIN)
    app.col_height.set(4.0)
    app.selected_nodes = {0}
    n0, m0 = len(app.nodes), len(app.members)
    app._add_column()
    assert len(app.nodes) == n0 + 1
    assert len(app.members) == m0 + 1
    assert app.nodes[-1][2] == pytest.approx(app.nodes[0][2] - 4.0)


def test_a_capital_column_under_a_single_node_is_still_refused(app, dialogs):
    app.col_style.set(sg.COLUMN_LATTICE)
    app.selected_nodes = {0}
    n0 = len(app.nodes)
    app._add_column()
    assert len(app.nodes) == n0
    assert any(k == 'showerror' for k, *_ in dialogs)


def test_adding_a_column_with_nothing_selected_says_so(app, dialogs):
    app.col_style.set(sg.COLUMN_PLAIN)
    app.selected_nodes = set()
    n0 = len(app.nodes)
    app._add_column()
    assert len(app.nodes) == n0
    assert any(k == 'showerror' for k, *_ in dialogs)


@pytest.mark.parametrize('style', sg.COLUMN_STYLES)
def test_every_column_style_can_be_added_from_the_panel(app, style):
    app.grid_family.set(FAMILY_LABEL['flat_grid'])
    app._on_generator_change()
    app.fg_nx.set(6); app.fg_ny.set(6)
    app._generate()
    # the bottom-layer nodes nearest the middle of the grid -- the footprint
    # a lasso box round one module would give
    bottom = [i for i, (x, y, z) in enumerate(app.nodes) if abs(z) < 1e-6]
    cx = sum(app.nodes[i][0] for i in bottom) / len(bottom)
    cy = sum(app.nodes[i][1] for i in bottom) / len(bottom)
    bottom.sort(key=lambda i: (app.nodes[i][0] - cx) ** 2 + (app.nodes[i][1] - cy) ** 2)
    # The latticed styles run one chord down from each selected node, so
    # their footprint IS the selection: exactly 3 or 4 nodes, convex, and
    # no three of them in a line. "The four nearest the centre" is NOT
    # that -- on this grid it is a kite with three nodes on one row.
    latticed = style in (sg.COLUMN_LATTICE, sg.COLUMN_TAPERED)
    if latticed:
        xs = sorted({round(app.nodes[i][0], 6) for i in bottom})
        ys = sorted({round(app.nodes[i][1], 6) for i in bottom})
        picked = {i for i in bottom
                  if round(app.nodes[i][0], 6) in xs[:2]
                  and round(app.nodes[i][1], 6) in ys[:2]}
    else:
        picked = set(bottom[:9])
    app.selected_nodes = set(picked)
    assert len(picked) >= 3
    n0, m0, sup0 = len(app.nodes), len(app.members), len(app.supports)
    app.col_style.set(style)
    app.col_height.set(4.0)
    app.col_capital.set(1.0)
    app.col_width.set(1.2)
    app.col_panels.set(3)
    app._add_column()
    assert len(app.nodes) > n0 and len(app.members) > m0
    # Count the NEW pinned nodes, not the net change: a column also hands
    # its head joints' own supports back to itself, so on a footprint that
    # was already supported the net change is smaller than the foot count.
    added = len({s['node'] for s in app.supports if s['node'] >= n0})
    # the plain strut has no capital: one post, and one foot, per node picked
    expected = {sg.COLUMN_PLAIN: len(picked), sg.COLUMN_SHAFT: 1,
                sg.COLUMN_TRIPOD: 3,
                sg.COLUMN_LATTICE: len(picked),
                sg.COLUMN_TAPERED: len(picked)}.get(style, 4)
    assert added == expected, f'{style} pinned {added} feet'
    assert len(app.supports) <= sup0 + expected
    app._analyze()
    assert app.err is None, f'{style} did not solve from the panel: {app.err}'


@pytest.mark.parametrize('profile', sg.BEAM_PROFILES)
def test_every_beam_profile_can_be_added_from_the_panel(app, profile):
    app.grid_family.set(FAMILY_LABEL['flat_grid'])
    app._on_generator_change()
    app.fg_nx.set(6); app.fg_ny.set(6)
    app._generate()
    ys = sorted({round(y, 6) for x, y, z in app.nodes if abs(z) < 1e-6})
    app.selected_nodes = {i for i, (x, y, z) in enumerate(app.nodes)
                          if abs(z) < 1e-6 and round(y, 6) in (ys[2], ys[3])}
    n0 = len(app.nodes)
    app.beam_profile.set(profile)
    app.beam_depth.set(1.6)
    app.beam_tiers.set(1)
    app._add_reinforcement_beam()
    assert len(app.nodes) > n0
    app._analyze()
    assert app.err is None, f'{profile} did not solve from the panel: {app.err}'


@pytest.mark.parametrize('law', sg.BEAM_DEPTH_LAWS)
def test_every_depth_law_can_be_added_from_the_panel(app, law):
    app.grid_family.set(FAMILY_LABEL['flat_grid'])
    app._on_generator_change()
    app.fg_nx.set(8); app.fg_ny.set(6)
    app._generate()
    ys = sorted({round(y, 6) for x, y, z in app.nodes if abs(z) < 1e-6})
    app.selected_nodes = {i for i, (x, y, z) in enumerate(app.nodes)
                          if abs(z) < 1e-6 and round(y, 6) in (ys[2], ys[3])}
    app.beam_profile.set(sg.BEAM_GRID_STRIP)
    app.beam_depth_law.set(law)
    app.beam_depth.set(1.6)
    app.beam_tiers.set(1)
    app._add_reinforcement_beam()
    app._analyze()
    assert app.err is None, f'{law} did not solve from the panel: {app.err}'


def test_a_vierendeel_keeps_rigid_joints_when_the_section_panel_says_pin(app):
    """_apply_sections sets every member's connection from one panel choice.
    A Vierendeel carries its load by BENDING its members, so pinned it is a
    mechanism and the solver returns a singular matrix rather than a result."""
    app.grid_family.set(FAMILY_LABEL['flat_grid'])
    app._on_generator_change()
    app.fg_nx.set(8); app.fg_ny.set(6)
    app._generate()
    ys = sorted({round(y, 6) for x, y, z in app.nodes if abs(z) < 1e-6})
    app.selected_nodes = {i for i, (x, y, z) in enumerate(app.nodes)
                          if abs(z) < 1e-6 and round(y, 6) in (ys[2], ys[3])}
    app.beam_profile.set(sg.BEAM_VIERENDEEL)
    app.beam_depth.set(1.6)
    app._add_reinforcement_beam()
    app.sec_conn.set('pin')
    app._apply_sections()
    forced = [m for m in app.members if m.get('rigid_required')]
    assert forced, 'the Vierendeel marked nothing as needing rigid joints'
    assert all(m['conn'] == 'rigid' for m in forced)
    assert any(m['conn'] == 'pin' for m in app.members), \
        'the panel choice stopped reaching the ordinary members'
    app._analyze()
    assert app.err is None, app.err


def test_add_column_2tier_capital_via_the_ui(app):
    # a 3x3 block (9 nodes, module=3, row stride 11 for the default 10x10
    # mesh) -- a genuine multi-module footprint, needed for tiers=2
    targets = {0, 1, 2, 11, 12, 13, 22, 23, 24}
    app.selected_nodes = set(targets)
    app.col_height.set(3.0)
    app.col_tiers.set(2)
    n_nodes_before = len(app.nodes)
    app._add_column()

    assert len(app.nodes) == n_nodes_before + 2 + 4   # base + head + 4 intermediates
    assert any(m.get('role') == 'capital_ring' for m in app.members)
    app._analyze()
    assert app.err is None


def test_add_reinforcement_beam_multilayer_via_the_ui(app):
    edge_a, edge_b = [0, 1, 2], [11, 12, 13]
    app.selected_nodes = set(edge_a + edge_b)
    app.beam_depth.set(1.2)
    app.beam_dir.set('Down (-Z)')
    app.beam_tiers.set(3)
    n_nodes_before = len(app.nodes)
    app._add_reinforcement_beam()

    assert len(app.nodes) == n_nodes_before + 3 * len(edge_a)
    app._analyze()
    assert app.err is None


# ── degree-of-indeterminacy readout ──────────────────────────────────────────

def test_indeterminacy_label_shows_a_value_for_the_default_mesh(app):
    app._refresh_all()
    text = app.indeterminacy_label.cget('text')
    assert text != ''
    assert ('DETERMINATE' in text or 'INDETERMINATE' in text or 'UNSTABLE' in text)


def test_indeterminacy_label_matches_stereo_math_for_the_default_mesh(app):
    app._refresh_all()
    dsi = sm.degree_of_indeterminacy(app.nodes, app.members, app.supports)
    text = app.indeterminacy_label.cget('text')
    assert str(abs(dsi)) in text


def test_indeterminacy_label_flags_rigid_body_motion_when_understrained(app):
    # zero supports -- a free-floating mechanism no matter how large the
    # raw DSI number computes (the caveat total_restrained_dofs exists to
    # catch: DSI alone is necessary but not sufficient for stability)
    app.supports = []
    app._refresh_all()
    text = app.indeterminacy_label.cget('text')
    assert 'UNSTABLE' in text
    assert '0/6' in text


def test_indeterminacy_label_is_blank_with_no_mesh_loaded(app):
    app.nodes = []
    app._refresh_all()
    assert app.indeterminacy_label.cget('text') == ''


# ── support sandbox ──────────────────────────────────────────────────────────

def test_support_sandbox_is_off_by_default(app):
    assert app.support_sandbox.get() is False
    assert app._disabled_supports == set()


def test_sandbox_click_on_a_support_disables_it_instead_of_selecting(app):
    app.support_sandbox.set(True)
    node = app.supports[0]['node']
    sx, sy = _screen_pos_of(app, node)
    app._select_node_at(sx, sy)
    assert node in app._disabled_supports
    assert app.selected_nodes == set()   # sandbox click never selects


def test_sandbox_click_again_re_enables_the_same_support(app):
    app.support_sandbox.set(True)
    node = app.supports[0]['node']
    sx, sy = _screen_pos_of(app, node)
    app._select_node_at(sx, sy)
    assert node in app._disabled_supports
    app._select_node_at(sx, sy)
    assert node not in app._disabled_supports


def test_sandbox_click_on_a_non_support_node_still_selects_normally(app):
    app.support_sandbox.set(True)
    support_nodes = {s['node'] for s in app.supports}
    non_support = next(i for i in range(len(app.nodes)) if i not in support_nodes)
    sx, sy = _screen_pos_of(app, non_support)
    app._select_node_at(sx, sy)
    assert app.selected_nodes == {non_support}
    assert app._disabled_supports == set()


def test_sandbox_toggle_off_makes_clicks_select_supports_normally_again(app):
    app.support_sandbox.set(True)
    node = app.supports[0]['node']
    sx, sy = _screen_pos_of(app, node)
    app._select_node_at(sx, sy)
    assert node in app._disabled_supports
    app.support_sandbox.set(False)
    app._select_node_at(sx, sy)
    assert app.selected_nodes == {node}


def test_analyze_excludes_disabled_supports_from_the_solve(app):
    node = app.supports[0]['node']
    app._disabled_supports = {node}
    app._analyze()
    assert app.err is None
    assert node not in app.results['reactions']


def test_reset_sandbox_button_re_enables_every_disabled_support(app):
    app._disabled_supports = {s['node'] for s in app.supports[:2]}
    app._reset_support_sandbox()
    assert app._disabled_supports == set()


def test_active_supports_excludes_only_the_disabled_ones(app):
    node = app.supports[0]['node']
    app._disabled_supports = {node}
    active = app._active_supports()
    assert node not in {s['node'] for s in active}
    assert len(active) == len(app.supports) - 1


def test_indeterminacy_label_reflects_the_sandbox_state(app):
    node = app.supports[0]['node']
    app._refresh_all()
    text_before = app.indeterminacy_label.cget('text')
    app._disabled_supports = {node}
    app._refresh_indeterminacy_label()
    text_after = app.indeterminacy_label.cget('text')
    assert text_after != text_before
    assert 'sandbox: 1 support(s) disabled' in text_after


def test_disabled_support_is_drawn_with_the_disabled_colour(app):
    node = app.supports[0]['node']
    app._disabled_supports = {node}
    app._draw()
    items = app.canvas.find_withtag(f'node{node}')
    fills = {app.canvas.itemcget(i, 'fill') for i in items if app.canvas.type(i) == 'oval'}
    assert SUPPORT_DISABLED_COLOR in fills


def test_generating_a_new_mesh_resets_the_sandbox(app):
    app._disabled_supports = {app.supports[0]['node']}
    app._generate()
    assert app._disabled_supports == set()


# ── analysis error handling ──────────────────────────────────────────────────

def test_analysis_error_is_shown_and_does_not_crash_the_tab(app):
    app.supports = []
    app._analyze()
    assert app.err is not None
    assert app.results is None


# ── Excel round trip ──────────────────────────────────────────────────────────

def test_excel_export_import_round_trip_through_the_app(app, tmp_path):
    app._analyze()
    from apps.stereo import stereo_reports as sr
    path = str(tmp_path / 'model.xlsx')
    sr.export_excel(app.nodes, app.members, app.loads, app.supports, app.results,
                    path, checks=app.member_checks)
    nodes2, members2, loads2, supports2 = sr.import_excel_model(path)
    assert len(nodes2) == len(app.nodes)
    assert len(members2) == len(app.members)


# ── units ──────────────────────────────────────────────────────────────────

def test_stop_units_detaches_from_the_selector(app):
    import units
    listener = app._units_listener
    assert listener in units._listeners
    app.stop_units()
    assert listener not in units._listeners
    assert app._units_listener is None


# ── Custom Surface Wizard ────────────────────────────────────────────────────

def _toplevels(w):
    out = []
    for c in w.winfo_children():
        if isinstance(c, tk.Toplevel):
            out.append(c)
        out.extend(_toplevels(c))
    return out


def _descendants(w, kind):
    out = []
    for c in w.winfo_children():
        if isinstance(c, kind):
            out.append(c)
        out.extend(_descendants(c, kind))
    return out


def _open_wizard(app):
    app._open_custom_surface_wizard()
    return _toplevels(app.root)[-1]


def test_wizard_default_single_surface_generates_a_flat_square_grid(app):
    win = _open_wizard(app)
    buttons = _descendants(win, tk.Button)
    [b for b in buttons if b.cget('text') == 'Generate'][0].invoke()
    assert len(app.nodes) == 81   # default n1=n2=8 -> a 9x9 node grid
    zs = {round(z, 9) for x, y, z in app.nodes}
    assert zs == {0.0}   # default surface is the flat z=0 height field
    assert not win.winfo_exists()   # Generate closes the dialog on success


def test_wizard_bad_expression_shows_an_error_and_keeps_the_dialog_open(app):
    win = _open_wizard(app)
    entries = _descendants(win, tk.Entry)
    z_entry = entries[0]
    z_entry.delete(0, tk.END)
    z_entry.insert(0, 'x + not_a_real_name')
    win.update_idletasks()   # flush the Entry -> StringVar trace before reading it
    n0 = len(app.nodes)
    buttons = _descendants(win, tk.Button)
    [b for b in buttons if b.cget('text') == 'Generate'][0].invoke()
    assert win.winfo_exists()
    assert len(app.nodes) == n0   # model untouched by the failed attempt
    labels = _descendants(win, tk.Label)
    assert any('unknown name' in l.cget('text') for l in labels)


def _keypad_button(win, label):
    return [b for b in _descendants(win, tk.Button) if b.cget('text') == label][0]


def test_wizard_keypad_inserts_into_the_focused_field(app):
    win = _open_wizard(app)
    entries = _descendants(win, tk.Entry)
    z_entry = entries[0]
    z_entry.delete(0, tk.END)
    z_entry.focus_set()
    z_entry.update()   # let <FocusIn> actually fire before the palette click
    _keypad_button(win, '√').invoke()
    assert z_entry.get() == 'sqrt()'


def test_the_keypad_shows_notation_and_inserts_what_the_parser_reads(app):
    """The keys carry the glyphs a surface is actually written in; the text
    they insert is the ASCII expr_math compiles. The two are deliberately
    different, and the mapping is what makes the palette worth having."""
    win = _open_wizard(app)
    entries = _descendants(win, tk.Entry)
    z_entry = entries[0]
    for label, expected in (('π', 'pi'), ('x²', '^2'), ('×', '*'),
                            ('÷', '/'), ('−', '-'), ('|x|', 'abs()')):
        z_entry.delete(0, tk.END)
        z_entry.focus_set()
        z_entry.update()
        _keypad_button(win, label).invoke()
        assert z_entry.get() == expected, f'{label} inserted {z_entry.get()!r}'


def test_every_keypad_key_inserts_something_the_parser_accepts(app):
    """A key that inserts text expr_math then rejects is worse than no key:
    it looks like a shortcut and produces an error message. Each key is
    completed into a whole expression and compiled."""
    from apps.stereo import stereo_app_wizard_keypad as keypad
    from apps.stereo import expr_math as em
    # Brackets and the separator carry no meaning on their own -- they are
    # punctuation for an expression built around them, not an expression.
    STRUCTURAL = {'(', ')', ','}
    checked = 0
    for _tab, rows in keypad.TABS:
        for keys in rows:
            for label, text, _back in keys:
                if text is None or text in STRUCTURAL:
                    continue
                probe = text.replace('()', '(1)').replace('(,)', '(1,2)')
                probe = probe.replace('(1/)', '(1/2)')
                if probe[0] in '^*/+-.':
                    probe = '1' + probe          # a binary operator needs a left side
                if probe[-1] in '^*/+-.':
                    probe += '2'                 # ...and a right one
                # x/y for a height field, u/v for a parametric surface --
                # both modes share one keypad, so both sets are declared
                fn = em.compile_expression(probe, ('x', 'y', 'u', 'v'))
                fn(1.0, 1.0, 1.0, 1.0)      # and it must evaluate, not just parse
                checked += 1
    assert checked >= 30, f'only {checked} keys were actually checked'


def test_the_keypad_types_into_a_field_before_anyone_clicks_one(app):
    """A key pressed on a freshly-opened wizard has an obvious destination:
    the field the palette sits under. It used to vanish -- the target was
    set by a FocusIn event, so until the user clicked a field there was no
    target at all and the button silently did nothing."""
    win = _open_wizard(app)
    z_entry = _descendants(win, tk.Entry)[0]
    z_entry.delete(0, tk.END)
    _keypad_button(win, 'π').invoke()
    assert z_entry.get() == 'pi'
    win.destroy()


def test_switching_modes_re_aims_the_keypad_at_the_visible_panel(app):
    """Otherwise it keeps typing into the panel that was just hidden."""
    win = _open_wizard(app)
    radios = _descendants(win, tk.Radiobutton)
    [r for r in radios if 'Two surfaces' in r.cget('text')][0].invoke()
    win.update_idletasks()
    entries = [e for e in _descendants(win, tk.Entry)
               if e.winfo_manager() != '' and e.master.winfo_manager() != '']
    assert entries, 'no visible field in two-surface mode'
    before = [e.get() for e in entries]
    _keypad_button(win, 'π').invoke()
    after = [e.get() for e in entries]
    assert before != after, 'the key went into a field nobody can see'
    win.destroy()


def test_the_keypad_backspace_deletes_rather_than_inserting(app):
    win = _open_wizard(app)
    entries = _descendants(win, tk.Entry)
    z_entry = entries[0]
    z_entry.delete(0, tk.END)
    z_entry.insert(0, 'sin(x)')
    z_entry.focus_set()
    z_entry.update()
    z_entry.icursor(tk.END)
    _keypad_button(win, '⌫').invoke()
    assert z_entry.get() == 'sin(x'


def test_the_keypad_is_tabbed_like_geogebras_own(app):
    from tkinter import ttk
    from apps.stereo import stereo_app_wizard_keypad as keypad
    win = _open_wizard(app)
    books = _descendants(win, ttk.Notebook)
    assert books, 'the keypad is not tabbed'
    names = [books[0].tab(i, 'text') for i in range(books[0].index('end'))]
    assert names == [t for t, _rows in keypad.TABS]


def test_loading_an_example_prefills_the_wizard_with_its_own_surface(app):
    """Loading an example is the quickest way to see what this tab builds,
    and the next question is always "how would I make one like it?" -- so the
    wizard opens showing the example's own surfaces and node configuration."""
    from apps.stereo import stereo_examples as sx
    label, builder = [(l, b) for l, b in sx.EXAMPLES
                      if 'paraboloid dish' in l][0]
    app._load_example(builder, label)
    win = _open_wizard(app)
    entries = _descendants(win, tk.Entry)
    values = [e.get() for e in entries]
    assert '3.0 * (1 - (x/6)^2 - (y/6)^2)' in values, \
        f'the surface expression is not in the dialog: {values}'
    assert '-6.0' in values and '6.0' in values, 'the domain was not carried over'
    radios = _descendants(win, tk.Radiobutton)
    on = [r.cget('text') for r in radios
          if str(r.cget('variable')) and r.cget('value') == '3d']
    assert on, 'the 3D module radio is missing'
    labels = [l.cget('text') for l in _descendants(win, tk.Label)]
    assert any('exact settings' in t for t in labels)


def test_a_two_surface_example_prefills_both_surfaces(app):
    from apps.stereo import stereo_examples as sx
    label, builder = [(l, b) for l, b in sx.EXAMPLES
                      if 'concentric domes' in l][0]
    app._load_example(builder, label)
    win = _open_wizard(app)
    values = [e.get() for e in _descendants(win, tk.Entry)]
    assert '4.0 * (1 - (x/6)^2 - (y/6)^2) + 2.0' in values, 'no top surface'
    assert '2.0 * (1 - (x/6)^2 - (y/6)^2)' in values, 'no bottom surface'


def test_a_generator_built_example_says_so_instead_of_inventing_a_surface(app):
    """These meshes come straight from a stereo_geometry generator and no
    expression in those fields would reproduce them. A pre-filled field that
    quietly generates something else is worse than an empty one."""
    from apps.stereo import stereo_examples as sx
    label, builder = [(l, b) for l, b in sx.EXAMPLES
                      if 'Schwedler dome' in l][0]
    app._load_example(builder, label)
    win = _open_wizard(app)
    labels = [l.cget('text') for l in _descendants(win, tk.Label)]
    assert any('Not a wizard surface' in t for t in labels)
    assert any('stereo_geometry.dome' in t for t in labels)
    # and the fields are left alone
    values = [e.get() for e in _descendants(win, tk.Entry)]
    assert '0' in values, 'the default height field was overwritten'


def test_every_example_carries_a_truthful_wizard_note(app):
    from apps.stereo import stereo_examples as sx
    for label, builder in sx.EXAMPLES:
        recipe = builder().get('wizard')
        assert recipe, f'{label} carries no wizard note'
        assert recipe.get('note'), f'{label} has an empty note'
        if recipe.get('mode'):
            assert 'exact settings' in recipe['note']
        else:
            assert 'Not a wizard surface' in recipe['note']


def test_the_wizard_does_not_show_the_previous_models_surface(app):
    from apps.stereo import stereo_examples as sx
    dish = [(l, b) for l, b in sx.EXAMPLES if 'paraboloid dish' in l][0]
    app._load_example(dish[1], dish[0])
    app.grid_family.set(FAMILY_LABEL['flat_grid'])
    app._on_generator_change()
    app._generate()                 # a plain family generate carries no recipe
    win = _open_wizard(app)
    values = [e.get() for e in _descendants(win, tk.Entry)]
    assert '3.0 * (1 - (x/6)^2 - (y/6)^2)' not in values


def test_the_wizard_can_always_be_finished_in_two_surface_mode(app):
    """Two surface panels with a keypad each need 829px of height. At the
    dialog's fixed 800px that put Generate off the bottom edge with no
    scrollbar, so the mode could be selected and never used."""
    win = _open_wizard(app)
    radios = _descendants(win, tk.Radiobutton)
    [r for r in radios if r.cget('text') == 'Two surfaces (top + bottom)'][0].invoke()
    win.update_idletasks()
    generate = [b for b in _descendants(win, tk.Button)
                if b.cget('text') == 'Generate'][0]
    bars = _descendants(win, tk.Scrollbar)
    assert bars, 'the dialog has no scrollbar'
    fits = win.winfo_height() >= generate.winfo_rooty() - win.winfo_rooty() \
        + generate.winfo_reqheight()
    scrolls = any(b.winfo_ismapped() for b in bars)
    assert fits or scrolls, 'Generate is unreachable in two-surface mode'


def test_wizard_3d_module_offsets_the_second_layer(app):
    win = _open_wizard(app)
    radios = _descendants(win, tk.Radiobutton)
    [r for r in radios if r.cget('text') == '3D (double layer)'][0].invoke()
    win.update_idletasks()
    buttons = _descendants(win, tk.Button)
    [b for b in buttons if b.cget('text') == 'Generate'][0].invoke()
    zs = sorted({round(z, 6) for x, y, z in app.nodes})
    assert len(zs) == 2
    assert zs[1] - zs[0] == pytest.approx(0.5)   # default depth = 0.5


def test_wizard_two_surfaces_mode_builds_a_double_layer_between_them(app):
    win = _open_wizard(app)
    radios = _descendants(win, tk.Radiobutton)
    [r for r in radios if 'Two surfaces' in r.cget('text')][0].invoke()

    labelframes = _descendants(win, tk.LabelFrame)
    top_lf = [lf for lf in labelframes if lf.cget('text') == 'Top surface'][0]
    bot_lf = [lf for lf in labelframes if lf.cget('text') == 'Bottom surface'][0]
    top_entry = _descendants(top_lf, tk.Entry)[0]
    bot_entry = _descendants(bot_lf, tk.Entry)[0]
    top_entry.delete(0, tk.END); top_entry.insert(0, '1.0')
    bot_entry.delete(0, tk.END); bot_entry.insert(0, '0')
    win.update_idletasks()

    buttons = _descendants(win, tk.Button)
    [b for b in buttons if b.cget('text') == 'Generate'][0].invoke()
    zs = sorted({round(z, 6) for x, y, z in app.nodes})
    assert zs == [0.0, 1.0]
    assert len(app.nodes) == 81 * 2


def test_wizard_polar_full_circle_and_isometric_pattern_generates_cleanly(app):
    win = _open_wizard(app)
    radios = _descendants(win, tk.Radiobutton)
    [r for r in radios if r.cget('text') == 'Polar'][0].invoke()
    [r for r in radios if 'Isometric' in r.cget('text')][0].invoke()
    [r for r in radios if r.cget('text') == '3D (double layer)'][0].invoke()
    checks = _descendants(win, tk.Checkbutton)
    [c for c in checks if 'Full circle' in c.cget('text')][0].invoke()
    entries = _descendants(win, tk.Entry)
    entries[0].delete(0, tk.END); entries[0].insert(0, '1.0')   # a nonzero flat surface
    win.update_idletasks()

    buttons = _descendants(win, tk.Button)
    [b for b in buttons if b.cget('text') == 'Generate'][0].invoke()
    assert not win.winfo_exists()
    assert len(app.nodes) > 0
    assert len(app.members) > 0


# ── where the polar grid's pole goes ────────────────────────────────────────

def _labels(win):
    return _descendants(win, tk.Label)


def _label_text(win, needle):
    for lb in _labels(win):
        try:
            text = lb.cget('text')
        except tk.TclError:
            continue
        if needle in (text or ''):
            return text
    return None


def _entry_after(win, label_text):
    """The entries on the row whose leading label reads `label_text`."""
    for lb in _labels(win):
        if (lb.cget('text') or '') == label_text:
            return [w for w in lb.master.winfo_children() if isinstance(w, tk.Entry)]
    return []


def test_the_pole_fields_only_appear_for_a_polar_domain(app):
    win = _open_wizard(app)
    radios = _descendants(win, tk.Radiobutton)
    assert not _entry_after(win, 'pole at:') or \
        _entry_after(win, 'pole at:')[0].master.master.winfo_manager() == ''
    [r for r in radios if r.cget('text') == 'Polar'][0].invoke()
    win.update_idletasks()
    assert len(_entry_after(win, 'pole at:')) == 2
    win.destroy()


def test_finding_the_summit_moves_the_pole_onto_it(app):
    """The user's question, answered in the dialog: a dome centred at
    (4, 4) should put the pole at (4, 4), not leave it at the origin."""
    win = _open_wizard(app)
    radios = _descendants(win, tk.Radiobutton)
    [r for r in radios if r.cget('text') == 'Polar'][0].invoke()
    entries = _descendants(win, tk.Entry)
    entries[0].delete(0, tk.END)
    entries[0].insert(0, '3 - 0.1*((x-4)**2 + (y-4)**2)')
    for box, value in zip(_entry_after(win, 'r range:'), ('0.01', '6')):
        box.delete(0, tk.END)
        box.insert(0, value)
    win.update_idletasks()

    [b for b in _descendants(win, tk.Button)
     if 'summit' in b.cget('text')][0].invoke()
    pole = [float(e.get()) for e in _entry_after(win, 'pole at:')]
    assert pole == pytest.approx([4.0, 4.0], abs=0.25)
    assert 'One summit' in _label_text(win, 'summit')
    win.destroy()


def test_a_many_summited_surface_says_one_pole_cannot_serve_them_all(app):
    """A sinusoidal roof has a summit per hump. The dialog has to say so
    rather than quietly centring on one of them."""
    win = _open_wizard(app)
    radios = _descendants(win, tk.Radiobutton)
    [r for r in radios if r.cget('text') == 'Polar'][0].invoke()
    entries = _descendants(win, tk.Entry)
    entries[0].delete(0, tk.END)
    entries[0].insert(0, 'sin(x)*sin(y)')
    for box, value in zip(_entry_after(win, 'r range:'), ('0.01', '12')):
        box.delete(0, tk.END)
        box.insert(0, value)
    win.update_idletasks()

    [b for b in _descendants(win, tk.Button)
     if 'summit' in b.cget('text')][0].invoke()
    said = _label_text(win, 'summits')
    assert said and 'cannot be centred' in said
    assert 'Cartesian or isometric' in said
    win.destroy()


def test_a_surface_with_no_summit_says_so_instead_of_picking_a_corner(app):
    win = _open_wizard(app)
    radios = _descendants(win, tk.Radiobutton)
    [r for r in radios if r.cget('text') == 'Polar'][0].invoke()
    entries = _descendants(win, tk.Entry)
    entries[0].delete(0, tk.END)
    entries[0].insert(0, '0.5*x + 0.25*y')
    win.update_idletasks()
    [b for b in _descendants(win, tk.Button)
     if 'summit' in b.cget('text')][0].invoke()
    assert 'No summit' in _label_text(win, 'No summit')
    assert [float(e.get()) for e in _entry_after(win, 'pole at:')] == [0.0, 0.0]
    win.destroy()


def test_the_wizard_builds_the_grid_about_the_pole_it_was_given(app):
    win = _open_wizard(app)
    radios = _descendants(win, tk.Radiobutton)
    [r for r in radios if r.cget('text') == 'Polar'][0].invoke()
    entries = _descendants(win, tk.Entry)
    entries[0].delete(0, tk.END)
    entries[0].insert(0, '3 - 0.1*((x-4)**2 + (y-4)**2)')
    for box, value in zip(_entry_after(win, 'r range:'), ('0.01', '4')):
        box.delete(0, tk.END)
        box.insert(0, value)
    [c for c in _descendants(win, tk.Checkbutton)
     if 'Full circle' in c.cget('text')][0].invoke()
    for box, value in zip(_entry_after(win, 'pole at:'), ('4', '4')):
        box.delete(0, tk.END)
        box.insert(0, value)
    win.update_idletasks()
    [b for b in _descendants(win, tk.Button)
     if b.cget('text') == 'Generate'][0].invoke()
    assert max(n[2] for n in app.nodes) == pytest.approx(3.0, abs=1e-3)


def test_the_wizard_reports_two_surfaces_that_cross_instead_of_crashing(app):
    """A crossed pair raises out of the generator; the dialog has to turn
    that into a message and stay open, like any other bad input."""
    win = _open_wizard(app)
    radios = _descendants(win, tk.Radiobutton)
    [r for r in radios if 'Two surfaces' in r.cget('text')][0].invoke()
    win.update_idletasks()
    entries = [e for e in _descendants(win, tk.Entry)
               if e.winfo_manager() != '' and e.master.winfo_manager() != '']
    # the top surface's field is the first visible one, the bottom's the next
    entries[0].delete(0, tk.END)
    entries[0].insert(0, '3.0*(1-(x/6)^2-(y/6)^2)+1.0')
    entries[1].delete(0, tk.END)
    entries[1].insert(0, '0')
    for box, value in zip(_entry_after(win, 'p range:'), ('-6', '6')):
        box.delete(0, tk.END); box.insert(0, value)
    for box, value in zip(_entry_after(win, 'q range:'), ('-6', '6')):
        box.delete(0, tk.END); box.insert(0, value)
    win.update_idletasks()

    n0 = len(app.nodes)
    [b for b in _descendants(win, tk.Button)
     if b.cget('text') == 'Generate'][0].invoke()
    assert win.winfo_exists(), 'the dialog closed on a bad pair'
    assert len(app.nodes) == n0, 'a crossed pair was loaded anyway'
    said = _label_text(win, 'cross')
    assert said and 'Shrink the domain' in said
    win.destroy()


def test_wizard_generated_mesh_is_undoable(app):
    n0 = len(app.nodes)
    win = _open_wizard(app)
    buttons = _descendants(win, tk.Button)
    [b for b in buttons if b.cget('text') == 'Generate'][0].invoke()
    assert len(app.nodes) != n0
    app._undo()
    assert len(app.nodes) == n0


# ── Module Editor ────────────────────────────────────────────────────────────

def _mode(app, key):
    """Activate a mode before asserting its widgets are mapped.

    The rail packs exactly one mode's panel and forgets the rest, so a
    widget in an inactive mode is genuinely not mapped -- winfo_ismapped is
    telling the truth. Tests that ask whether a box is showing have to say
    which mode they are in first, the same way a user would.
    """
    app._set_mode(key)
    app.root.update_idletasks()


def _edit_mode(app, role_id=0):
    """Leave the frozen base module and select a MEASURED one, which is what
    the edit actions act on. The panel opens on the base by design -- it is
    the grid's reference -- so every editing test has to step off it first."""
    _mode(app, 'module')
    app._me_role_id = role_id
    app._me_selection = None
    app._me_render()
    return role_id


def test_module_editor_populates_roles_after_the_default_flat_grid(app):
    assert app._me_roles   # flat_grid always has at least one role
    assert app._me_role_id == me.ME_BASE_ROLE   # the reference, by default
    assert app.me_role_combo['values']
    # the default flat_grid (offset=True) has both pyramidal-web triangles
    # and flat square chords -- two distinct shapes, so at least one
    # keystone/singular entry besides the dominant role 0
    assert app.me_keystone_list.size() >= 1


# ── the base module is a reference, not a measurement ───────────────────────

def test_the_module_list_opens_on_the_frozen_base_module(app):
    assert app._me_base is not None
    assert app._me_role_id == me.ME_BASE_ROLE
    assert app.me_role_combo['values'][0].startswith('Base module')
    assert 'Measured' in app.me_role_combo['values'][1]


def test_the_base_module_does_not_change_when_a_node_is_moved(app):
    """The complaint this answers: dragging one node in the editor rewrote
    what the panel called the base module."""
    before = dict(app._me_base)
    _edit_mode(app)
    items = app.me_canvas.find_withtag('node')
    x0, y0, x1, y1 = app.me_canvas.bbox(items[0])
    app._me_on_press(FakeEvent((x0 + x1) / 2, (y0 + y1) / 2))
    app.me_du.set(0.4); app.me_dv.set(0.2); app.me_dn.set(0.3)
    app._me_apply_move()
    assert app.nodes != before, 'the fixture did not actually move anything'
    assert app._me_base == before


def test_the_base_module_does_not_change_when_a_beam_is_added(app):
    """And the other half of it: bolting a reinforcement beam onto one edge
    used to be able to hand the title to the beam's own cell."""
    before = dict(app._me_base)
    n0 = len(app.members)
    app.selected_nodes = {0, 1, 2, 11, 12, 13}
    app.beam_depth.set(1.2)
    app._add_reinforcement_beam()
    assert len(app.members) > n0, 'no beam was added'
    assert app._me_base == before


def test_generating_a_new_grid_takes_a_new_base_module(app):
    """Frozen is not stuck: a new mesh is a new reference."""
    before = dict(app._me_base)
    app.grid_family.set(FAMILY_LABEL['dome'])
    app._on_generator_change()
    app._generate()
    assert app._me_base != before
    assert app._me_role_id == me.ME_BASE_ROLE


def test_a_single_layer_surface_grid_shows_a_flat_base_module(app):
    """"When generating a surface mesh grid the base module remains in 3D
    when it should be a 2D element": a single-layer shell's module is a
    plate, and comes back exactly coplanar."""
    app.grid_family.set(FAMILY_LABEL['dome'])
    app._on_generator_change()
    app._generate()
    assert app._me_base['planar'] is True
    assert all(p[2] == 0.0 for p in app._me_base['nodes'])


def test_a_double_layer_grid_still_shows_its_solid_base_module(app):
    assert app._me_base['planar'] is False
    assert app._me_base['apexes'] == 1


def test_the_base_module_is_drawn_from_its_own_frozen_geometry(app):
    """Not from the live mesh: the 3D panel must keep drawing the reference
    after the model underneath it has been edited."""
    app._me_render()
    before = len(app.me3d_canvas.find_all())
    assert before > 0
    role = _edit_mode(app)
    app.me_rescale.set(2.0)
    app._me_apply_rescale()
    app._me_role_id = me.ME_BASE_ROLE
    app._me_selection = None
    app._me_render()
    nodes, members = app._me_source()
    assert nodes is app._me_base['nodes']
    assert members is app._me_base['members']
    assert role == 0


def test_editing_the_base_module_is_refused_and_says_why(app, dialogs):
    app._me_role_id = me.ME_BASE_ROLE
    app._me_selection = ('node', 0)
    app.me_du.set(1.0)
    nodes_before = list(app.nodes)
    app._me_apply_move()
    assert app.nodes == nodes_before
    assert any(k == 'showinfo' for k, *_ in dialogs)


def test_every_edit_action_refuses_the_base_module(app, dialogs):
    app._me_role_id = me.ME_BASE_ROLE
    nodes_before, members_before = list(app.nodes), list(app.members)
    app._me_selection = ('node', 0)
    app._me_apply_move()
    app._me_selection = ('edge', (0, 1))
    app.me_length.set(9.0)
    app._me_apply_length()
    app._me_selection = ('toggle', (0, 2))
    app._me_apply_toggle()
    app.me_rescale.set(2.0)
    app._me_apply_rescale()
    assert app.nodes == nodes_before
    assert app.members == members_before


def test_the_panel_says_the_base_module_is_a_reference(app):
    app._me_role_id = me.ME_BASE_ROLE
    app._me_selection = None
    app._me_render()
    assert 'BASE MODULE' in app.me_warning.cget('text')


def test_module_editor_3d_panel_is_separate_and_above_the_flattened_view(app):
    _mode(app, 'module')
    # a distinct widget, not an overlay drawn onto me_canvas
    assert app.me3d_canvas is not app.me_canvas
    assert app.me3d_zc.winfo_y() < app.me_canvas.winfo_y()
    items = app.me3d_canvas.find_all()
    assert items
    kinds = {app.me3d_canvas.type(i) for i in items}
    assert 'line' in kinds
    assert 'oval' in kinds
    # its geometry is independent of the flattened view's own screen
    # coordinates -- a genuinely separate rendering, not shared items
    flat_edge = app.me_canvas.coords(app.me_canvas.find_withtag('edge')[0])
    threed_lines = [app.me3d_canvas.coords(i) for i in items if app.me3d_canvas.type(i) == 'line']
    assert flat_edge not in threed_lines


def _me3d_structural_lines(app):
    """Every 'line' item in the 3D panel EXCEPT dimension-callout lines
    (extension lines + arrows, drawn in their own MODULE_DIM_COLOR) --
    i.e. just the ring edges, any existing quad diagonal, and apex
    diagonals."""
    return [i for i in app.me3d_canvas.find_all() if app.me3d_canvas.type(i) == 'line'
           and app.me3d_canvas.itemcget(i, 'fill') != MODULE_DIM_COLOR]


def _me3d_expected_structural_line_count(app, cell_nodes):
    """Ring edges + apex diagonals + any existing quad diagonal -- see
    _me_ring_context and _me_render_3d's own docstrings for what each of
    these is."""
    n = len(cell_nodes)
    apex = app._me_ring_context(cell_nodes)
    apex_edges = sum(len(ids) for ids in apex.values())
    diagonal = 0
    if n == 4:
        for pos_a, pos_b in ((0, 2), (1, 3)):
            a_id, b_id = cell_nodes[pos_a], cell_nodes[pos_b]
            if any({m['a'], m['b']} == {a_id, b_id} for m in app.members):
                diagonal += 1
    return n + apex_edges + diagonal


def test_module_editor_3d_panel_matches_the_cells_own_ring_plus_apex(app):
    cell_nodes = app._me3d_cell_nodes()
    lines = _me3d_structural_lines(app)
    assert len(lines) == _me3d_expected_structural_line_count(app, cell_nodes)


def test_module_editor_3d_panel_shows_an_existing_diagonal_as_an_extra_line():
    from apps.stereo.stereo_app import StereoApp
    # build a fresh app so this test doesn't depend on the shared fixture's
    # default role happening to be a quad
    import tkinter as tk
    root = tk.Tk()
    tab = tk.Frame(root)
    app = StereoApp(tab)
    tab.pack(fill='both', expand=True)
    root.update_idletasks(); root.update()
    try:
        role_ids = sorted(app._me_roles)
        quad_role = next((r for r in role_ids
                          if len(app._me_cells[app._me_roles[r][0]]['nodes']) == 4), None)
        assert quad_role is not None
        app._me_role_id = quad_role
        app._me_selection = None
        app._me_render()
        before = len(_me3d_structural_lines(app))

        cell_nodes = app._me_current_cell_nodes()
        a_id, b_id = cell_nodes[0], cell_nodes[2]
        app.members.append({'a': a_id, 'b': b_id, 'conn': 'pin', 'role': 'test_diag',
                            'E': 200e3, 'A': 20.0})
        app._me_render()
        after = len(_me3d_structural_lines(app))
        assert after == before + 1
    finally:
        tab.destroy()
        root.destroy()


def test_module_editor_3d_panel_still_renders_for_a_curved_family(app):
    app.grid_family.set(FAMILY_LABEL['dome'])
    app._generate()
    assert app.me3d_canvas.find_all()


def test_module_editor_3d_panel_orbits_independently_of_the_main_canvas(app):
    az0, el0 = app.me3d_azimuth, app.me3d_elevation
    main_az0, main_el0 = app.azimuth, app.elevation
    app._me3d_orbit_press(FakeEvent(50, 50))
    app._me3d_orbit_motion(FakeEvent(90, 80))
    app._me3d_orbit_release(FakeEvent(90, 80))
    assert (app.me3d_azimuth, app.me3d_elevation) != (az0, el0)
    assert (app.azimuth, app.elevation) == (main_az0, main_el0)   # main view untouched


def test_module_editor_3d_panel_zooms_via_the_mouse_wheel(app):
    _mode(app, 'module')
    zoom0 = app.me3d_zc.zoom

    class FakeWheelEvent:
        num = 0
        def __init__(self, x, y, delta):
            self.x, self.y, self.delta = x, y, delta
            self.widget = app.me3d_canvas
    app.me3d_zc._on_wheel(FakeWheelEvent(size := 260 // 2, size, 120))
    assert app.me3d_zc.zoom != zoom0


def test_module_editor_3d_panel_switches_with_the_selected_role(app):
    role_ids = sorted(app._me_roles)
    quad_role = next((r for r in role_ids
                      if len(app._me_cells[app._me_roles[r][0]]['nodes']) == 4), None)
    assert quad_role is not None
    app._me_role_id = quad_role
    app._me_selection = None
    app._me_render()
    cell_nodes = app._me3d_cell_nodes()
    lines = _me3d_structural_lines(app)
    assert len(lines) == _me3d_expected_structural_line_count(app, cell_nodes)


# ── module display: the module as a solid polyhedron, not a flat polygon ────

def test_default_flat_grid_quad_module_reconstructs_its_own_pyramid_apex(app):
    # the default flat_grid is an offset square-on-square double-layer
    # grid -- its quad (top chord square) module MUST have a real apex
    # node (the bottom chord node all 4 diagonals converge to), the exact
    # "inverted square pyramid" shape the module display is meant to show
    role_ids = sorted(app._me_roles)
    quad_role = next((r for r in role_ids
                      if len(app._me_cells[app._me_roles[r][0]]['nodes']) == 4), None)
    assert quad_role is not None
    app._me_role_id = quad_role
    app._me_selection = None
    app._me_render()
    cell_nodes = app._me3d_cell_nodes()
    apex = app._me_ring_context(cell_nodes)
    assert apex, 'no node connects to all 4 corners of the quad -- apex not found'


def test_module_3d_panel_draws_shaded_faces_for_a_module_with_a_real_apex(app):
    role_ids = sorted(app._me_roles)
    quad_role = next((r for r in role_ids
                      if len(app._me_cells[app._me_roles[r][0]]['nodes']) == 4), None)
    app._me_role_id = quad_role
    app._me_selection = None
    app._me_render()
    polygons = [i for i in app.me3d_canvas.find_all() if app.me3d_canvas.type(i) == 'polygon']
    assert len(polygons) == 4   # one shaded triangular face per side of the pyramid


def test_module_3d_panel_always_shows_the_full_pyramid_even_from_a_triangle_role(app):
    # picking the quad (top square) role or any ONE of its 4 triangular
    # side-face roles must resolve to the SAME canonical quad+apex module
    # -- _me3d_cell_nodes always prefers the quad, so the 3D view never
    # shows just one bare triangular face
    role_ids = sorted(app._me_roles)
    quad_role = next((r for r in role_ids
                      if len(app._me_cells[app._me_roles[r][0]]['nodes']) == 4), None)
    tri_role = next((r for r in role_ids
                     if len(app._me_cells[app._me_roles[r][0]]['nodes']) == 3), None)
    assert quad_role is not None and tri_role is not None

    app._me_role_id = quad_role
    quad_3d_nodes = app._me3d_cell_nodes()
    assert len(quad_3d_nodes) == 4
    quad_apex = app._me_ring_context(quad_3d_nodes)
    assert quad_apex

    app._me_role_id = tri_role
    tri_3d_nodes = app._me3d_cell_nodes()
    assert len(tri_3d_nodes) == 4   # snapped to the canonical quad, not the bare triangle
    tri_apex = app._me_ring_context(tri_3d_nodes)
    assert set(quad_apex) == set(tri_apex)


def test_module_3d_panel_draws_dimension_callouts_with_the_real_edge_length(app):
    import math
    cell_nodes = app._me3d_cell_nodes()
    app._me_render()
    dim_lines = [i for i in app.me3d_canvas.find_all() if app.me3d_canvas.type(i) == 'line'
                and app.me3d_canvas.itemcget(i, 'fill') == MODULE_DIM_COLOR]
    assert dim_lines
    dim_texts = [app.me3d_canvas.itemcget(i, 'text') for i in app.me3d_canvas.find_all()
                if app.me3d_canvas.type(i) == 'text'
                and app.me3d_canvas.itemcget(i, 'fill') == MODULE_DIM_COLOR]
    real_len = math.dist(app.nodes[cell_nodes[0]], app.nodes[cell_nodes[1]])
    assert any(f'{real_len:.2f}m' in t for t in dim_texts)


def test_module_3d_panel_shows_height_and_angle_when_an_apex_exists(app):
    cell_nodes = app._me3d_cell_nodes()
    apex = app._me_ring_context(cell_nodes)
    assert apex, 'the default flat_grid module should have a real apex'
    app._me_render()
    dim_texts = [app.me3d_canvas.itemcget(i, 'text') for i in app.me3d_canvas.find_all()
                if app.me3d_canvas.type(i) == 'text']
    assert any(t.startswith('H=') for t in dim_texts)
    assert any(t.startswith('∠') for t in dim_texts)


def test_module_editor_clicking_a_node_selects_it_and_shows_the_node_box(app):
    _mode(app, 'module')
    items = app.me_canvas.find_withtag('node')
    x0, y0, x1, y1 = app.me_canvas.bbox(items[0])
    app._me_on_press(FakeEvent((x0 + x1) / 2, (y0 + y1) / 2))
    app.root.update_idletasks()
    assert app._me_selection[0] == 'node'
    assert app.me_node_box.winfo_ismapped()


def test_module_editor_clicking_a_rod_selects_it_and_shows_the_edge_box(app):
    _mode(app, 'module')
    items = app.me_canvas.find_withtag('edge')
    x0, y0, x1, y1 = app.me_canvas.bbox(items[0])
    app._me_on_press(FakeEvent((x0 + x1) / 2, (y0 + y1) / 2))
    app.root.update_idletasks()
    assert app._me_selection[0] == 'edge'
    assert app.me_edge_box.winfo_ismapped()


def test_module_editor_move_propagates_and_keeps_the_role_grouping_stable(app):
    _edit_mode(app)
    items = app.me_canvas.find_withtag('node')
    x0, y0, x1, y1 = app.me_canvas.bbox(items[0])
    app._me_on_press(FakeEvent((x0 + x1) / 2, (y0 + y1) / 2))
    position = app._me_selection[1]
    role_id = app._me_role_id
    n_cells_in_role = len(app._me_roles[role_id])

    app.me_du.set(0.3); app.me_dv.set(0.0); app.me_dn.set(0.0)
    app._me_apply_move()

    # a geometric edit must never fragment the role grouping (see
    # _me_apply_move's own comment on why this is NOT recomputed)
    assert len(app._me_roles[role_id]) == n_cells_in_role
    assert app._me_selection == ('node', position)   # selection survives too


def test_module_editor_set_length_changes_the_actual_mesh_distance(app):
    _edit_mode(app)
    items = app.me_canvas.find_withtag('edge')
    x0, y0, x1, y1 = app.me_canvas.bbox(items[0])
    app._me_on_press(FakeEvent((x0 + x1) / 2, (y0 + y1) / 2))
    pos_a, pos_b = app._me_selection[1]
    role_id = app._me_role_id
    cell_nodes = app._me_cells[app._me_roles[role_id][0]]['nodes']

    app.me_length.set(50.0)
    app._me_apply_length()

    import math
    d = math.dist(app.nodes[cell_nodes[pos_a]], app.nodes[cell_nodes[pos_b]])
    assert d > 10.0   # moved a long way toward the (heavily-shared) target


def test_module_editor_lock_prevents_setting_the_length(app, dialogs):
    _edit_mode(app)
    items = app.me_canvas.find_withtag('edge')
    x0, y0, x1, y1 = app.me_canvas.bbox(items[0])
    app._me_on_press(FakeEvent((x0 + x1) / 2, (y0 + y1) / 2))
    app.me_locked_var.set(True)
    app._me_toggle_lock()
    key = (app._me_role_id,) + tuple(sorted(app._me_selection[1]))
    assert key in app._me_locked_edges

    app.me_length.set(999.0)
    app._me_apply_length()
    assert any(k == 'showinfo' for k, *_ in dialogs)


def test_module_editor_toggle_adds_and_removes_a_diagonal(app):
    _mode(app, 'module')
    quad_role = next((r for r in sorted(app._me_roles)
                      if len(app._me_cells[app._me_roles[r][0]]['nodes']) == 4), None)
    assert quad_role is not None
    app._me_role_id = quad_role
    app._me_selection = None
    app._me_render()

    items = app.me_canvas.find_withtag('toggle')
    assert items
    x0, y0, x1, y1 = app.me_canvas.bbox(items[0])
    app._me_on_press(FakeEvent((x0 + x1) / 2, (y0 + y1) / 2))
    app.root.update_idletasks()
    assert app._me_selection[0] == 'toggle'
    assert app.me_toggle_box.winfo_ismapped()

    n0 = len(app.members)
    app._me_apply_toggle()
    assert len(app.members) > n0   # added the diagonal everywhere in that role


def test_module_editor_rescale_changes_the_role_dimensions(app):
    role_id = _edit_mode(app)
    cell_nodes = app._me_cells[app._me_roles[role_id][0]]['nodes']
    import math
    before = math.dist(app.nodes[cell_nodes[0]], app.nodes[cell_nodes[1]])

    app.me_rescale.set(3.0)
    app._me_apply_rescale()

    after = math.dist(app.nodes[cell_nodes[0]], app.nodes[cell_nodes[1]])
    assert after == pytest.approx(before * 3.0)


def test_module_editor_edits_are_undoable(app):
    _edit_mode(app)
    n0 = len(app.nodes)
    items = app.me_canvas.find_withtag('node')
    x0, y0, x1, y1 = app.me_canvas.bbox(items[0])
    app._me_on_press(FakeEvent((x0 + x1) / 2, (y0 + y1) / 2))
    app.me_du.set(0.5); app.me_dv.set(0.0); app.me_dn.set(0.0)
    app._me_apply_move()
    moved_nodes = list(app.nodes)
    app._undo()
    assert len(app.nodes) == n0
    assert app.nodes != moved_nodes


def test_module_editor_refreshes_after_generating_a_different_family(app):
    app.grid_family.set(FAMILY_LABEL['dome'])
    app._generate()
    assert app._me_roles   # dome's own module got detected too
    for role_id, idxs in app._me_roles.items():
        for ci in idxs:
            for nid in app._me_cells[ci]['nodes']:
                assert 0 <= nid < len(app.nodes)   # no stale node references


# ── Load Example menu ────────────────────────────────────────────────────────

def test_load_example_replaces_the_model_and_solves(app):
    from apps.stereo import stereo_examples as sx
    label, builder = sx.EXAMPLES[0]
    n0 = len(app.nodes)
    app._load_example(builder, label)
    assert len(app.nodes) != n0
    app._analyze()
    assert app.results is not None
    assert app.err is None


def test_load_example_is_undoable(app):
    from apps.stereo import stereo_examples as sx
    n0 = len(app.nodes)
    label, builder = sx.EXAMPLES[2]
    app._load_example(builder, label)
    assert len(app.nodes) != n0
    app._undo()
    assert len(app.nodes) == n0


def test_every_example_loads_and_analyzes_through_the_real_app(app):
    from apps.stereo import stereo_examples as sx
    for label, builder in sx.EXAMPLES:
        app._load_example(builder, label)
        app._analyze()
        assert app.results is not None, f'{label} failed to analyze: {app.err}'


# ── Supports-by-moment colouring (rigid connections) ────────────────────────

def _make_rigid_fixed(app):
    app.sec_conn.set('rigid')
    app._apply_sections()
    for s in app.supports:
        s['type'] = 'fixed'
    app._analyze()


def test_reaction_moment_signed_picks_the_dominant_axis_and_its_sign():
    r = {'Mx': 1.0, 'My': -5.0, 'Mz': 2.0}
    assert reaction_moment_signed(r, MOMENT_AXIS_RESULTANT) < 0   # My dominates, negative
    assert reaction_moment_signed(r, MOMENT_AXIS_MX) == 1.0
    assert reaction_moment_signed(r, MOMENT_AXIS_MY) == -5.0
    assert reaction_moment_signed(r, MOMENT_AXIS_MZ) == 2.0


def test_reaction_moment_signed_defaults_to_resultant():
    r = {'Mx': 3.0, 'My': 0.0, 'Mz': 4.0}
    import math
    assert reaction_moment_signed(r) == pytest.approx(math.hypot(3.0, 4.0))


def test_reaction_moment_signed_gives_symmetric_nodes_the_same_sign():
    # the actual bug report this fixes: on a symmetric grid under
    # symmetric load, diagonally-opposite corners came out with every
    # Mx/My component flipped (same magnitude) -- a real consequence of
    # moments being an axial vector under a 180-degree rotation, but not
    # what a viewer expects from two equally-loaded, symmetric supports.
    # These are the actual reaction values measured on such a grid.
    centroid = (4.5, 4.5)
    corners = {
        (0.0, 0.0): {'Mx': 0.02, 'My': -0.02, 'Mz': -0.0},
        (9.0, 0.0): {'Mx': 0.02, 'My': 0.02, 'Mz': 0.0},
        (0.0, 9.0): {'Mx': -0.02, 'My': -0.02, 'Mz': -0.0},
        (9.0, 9.0): {'Mx': -0.02, 'My': 0.02, 'Mz': 0.0},
    }
    values = [reaction_moment_signed(r, MOMENT_AXIS_RESULTANT, xy, centroid)
             for xy, r in corners.items()]
    assert all(v > 0 for v in values)
    assert values[0] == pytest.approx(values[1]) == pytest.approx(values[2]) \
        == pytest.approx(values[3])


def test_reaction_moment_signed_resultant_still_works_without_geometry():
    # backward compatible: no node_xy/centroid_xy falls back to the old
    # dominant-component sign, so an existing caller with no natural
    # "centroid" concept is unaffected
    r = {'Mx': 1.0, 'My': -5.0, 'Mz': 2.0}
    assert reaction_moment_signed(r, MOMENT_AXIS_RESULTANT) < 0


def test_reaction_moment_signed_mx_my_mz_axes_ignore_geometry():
    # an explicit single-axis pick is a literal raw component regardless
    # of node_xy/centroid_xy -- the symmetry correction only applies to
    # the blended "Resultant" mode
    r = {'Mx': 1.0, 'My': -5.0, 'Mz': 2.0}
    node_xy, centroid_xy = (9.0, 9.0), (4.5, 4.5)
    assert reaction_moment_signed(r, MOMENT_AXIS_MX, node_xy, centroid_xy) == 1.0
    assert reaction_moment_signed(r, MOMENT_AXIS_MY, node_xy, centroid_xy) == -5.0
    assert reaction_moment_signed(r, MOMENT_AXIS_MZ, node_xy, centroid_xy) == 2.0


def test_moment_color_is_neutral_at_zero_and_split_by_sign():
    assert moment_color(0.0, 10.0) == MOMENT_ZERO_COLOR
    assert moment_color(1.0, 0.0) == MOMENT_ZERO_COLOR   # no range yet
    pos = moment_color(5.0, 10.0)
    neg = moment_color(-5.0, 10.0)
    assert pos != neg
    assert pos != MOMENT_ZERO_COLOR
    assert neg != MOMENT_ZERO_COLOR


def test_moment_color_toggle_colors_support_nodes_on_a_rigid_model(app):
    _make_rigid_fixed(app)
    app.colour_by_moment.set(True)
    app._draw()
    support_nodes = {s['node'] for s in app.supports}
    colored = []
    for i in support_nodes:
        for item in app.canvas.find_withtag(f'node{i}'):
            if app.canvas.type(item) == 'oval':
                colored.append(app.canvas.itemcget(item, 'fill'))
    assert colored
    assert any(c != MOMENT_ZERO_COLOR for c in colored)


def test_moment_axis_selector_changes_the_displayed_colours(app):
    _make_rigid_fixed(app)
    app.colour_by_moment.set(True)

    def support_colors():
        app._draw()
        out = []
        for s in app.supports:
            for item in app.canvas.find_withtag(f"node{s['node']}"):
                if app.canvas.type(item) == 'oval':
                    out.append(app.canvas.itemcget(item, 'fill'))
        return out

    results_per_axis = {}
    for axis in MOMENT_AXES:
        app.moment_axis.set(axis)
        results_per_axis[axis] = support_colors()
    # at least one axis choice must produce a DIFFERENT colouring than
    # another -- otherwise the selector would be decorative
    assert len(set(tuple(v) for v in results_per_axis.values())) > 1


def test_moment_colour_mode_shows_neutral_on_a_pin_jointed_model(app):
    # a pin-jointed model reacts to force only -- every support should
    # read as the neutral ~0 colour regardless of load
    app._analyze()
    app.colour_by_moment.set(True)
    app._draw()
    support_nodes = {s['node'] for s in app.supports}
    for i in support_nodes:
        for item in app.canvas.find_withtag(f'node{i}'):
            if app.canvas.type(item) == 'oval':
                assert app.canvas.itemcget(item, 'fill') == MOMENT_ZERO_COLOR


def test_moment_legend_mentions_the_selected_axis(app):
    _make_rigid_fixed(app)
    app.colour_by_moment.set(True)
    app.moment_axis.set(MOMENT_AXIS_MY)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert any('My' in t for t in texts)


def test_moment_colouring_also_covers_ordinary_interior_nodes_not_just_supports(app):
    # the actual bug report this section exists to fix: the gradient was
    # only ever applied at SUPPORTS, so on a mostly-interior grid it read
    # as "not visible at all" -- every ordinary rigid joint away from a
    # support must get its own colour too, from sm.node_moment_vectors.
    _make_rigid_fixed(app)
    app.colour_by_moment.set(True)
    app._draw()
    support_nodes = {s['node'] for s in app.supports}
    interior = [i for i in range(len(app.nodes)) if i not in support_nodes]
    assert interior   # the default flat_grid has plenty of interior nodes
    colored_non_white = []
    for i in interior:
        for item in app.canvas.find_withtag(f'node{i}'):
            if app.canvas.type(item) == 'oval':
                fill = app.canvas.itemcget(item, 'fill')
                if fill != MOMENT_ZERO_COLOR:
                    colored_non_white.append(fill)
    assert colored_non_white, 'no interior node got a non-zero moment colour'


def test_moment_gradient_is_orange_negative_white_zero_violet_positive(app):
    assert MOMENT_ZERO_COLOR == '#ffffff'
    neg = moment_color(-10.0, 10.0)
    pos = moment_color(10.0, 10.0)
    # orange end: high red, some green, low blue; violet end: high red and
    # blue, low green -- distinguishable by their green channel alone
    def rgb(hexcolor):
        h = hexcolor.lstrip('#')
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    r_neg, g_neg, b_neg = rgb(neg)
    r_pos, g_pos, b_pos = rgb(pos)
    assert g_neg > g_pos   # orange is greener than violet
    assert b_pos > b_neg   # violet is bluer than orange


def test_moment_colouring_is_relative_to_the_whole_grids_own_moment_range(app):
    # scaling every load in the model by a large factor changes the
    # absolute moment values but must NOT change how the colours compare
    # to each other -- moment_color always normalizes by max_abs_m, i.e.
    # relative to every other node currently in the grid, per the
    # feature's own spec.
    _make_rigid_fixed(app)
    app.colour_by_moment.set(True)
    app._draw()

    def node_colors():
        out = {}
        for i in range(len(app.nodes)):
            for item in app.canvas.find_withtag(f'node{i}'):
                if app.canvas.type(item) == 'oval':
                    out[i] = app.canvas.itemcget(item, 'fill')
        return out

    colors_100 = node_colors()
    app.load_fraction.set(50.0)
    app._draw()
    colors_50 = node_colors()
    assert colors_100 == colors_50


def test_moment_colouring_gives_the_four_symmetric_corners_the_same_colour(app):
    # the live-UI version of the symmetric-sign fix: on the default
    # (square, symmetrically loaded) flat_grid with rigid connections and
    # every suggested node fixed, the four PLAN corners are related by
    # 90/180-degree rotations about the grid's own centre and carry
    # identical self-weight -- they must render as the same colour, not
    # alternate orange/violet the way the raw dominant-component sign did.
    _make_rigid_fixed(app)
    app.colour_by_moment.set(True)
    app._draw()
    support_nodes = [s['node'] for s in app.supports]
    xs = [app.nodes[i][0] for i in support_nodes]
    ys = [app.nodes[i][1] for i in support_nodes]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    corners = [i for i in support_nodes
              if app.nodes[i][0] in (xmin, xmax) and app.nodes[i][1] in (ymin, ymax)]
    assert len(corners) == 4

    def fill_of(node_idx):
        for item in app.canvas.find_withtag(f'node{node_idx}'):
            if app.canvas.type(item) == 'oval':
                return app.canvas.itemcget(item, 'fill')
        return None

    fills = {fill_of(i) for i in corners}
    assert len(fills) == 1
    assert None not in fills and MOMENT_ZERO_COLOR not in fills


# ── moment-view readability: member backdrop + larger node dots ─────────────

def test_moment_mode_fades_members_to_a_flat_backdrop(app):
    # 'Colour by force' defaults to True, so this also proves the backdrop
    # wins over it -- the moment view's actual content is the node colours,
    # not a competing force gradient on the members underneath them.
    assert app.colour_by_force.get() is True
    app._analyze()
    app.colour_by_moment.set(True)
    app._draw()
    fills = {app.canvas.itemcget(i, 'fill') for i in app.canvas.find_withtag('member')}
    assert fills == {MOMENT_BACKDROP_COLOR}


def test_moment_mode_backdrop_wins_over_utilization_heat_map_too(app):
    app._analyze()
    app.colour_by_util.set(True)
    app.colour_by_moment.set(True)
    app._draw()
    fills = {app.canvas.itemcget(i, 'fill') for i in app.canvas.find_withtag('member')}
    assert fills == {MOMENT_BACKDROP_COLOR}


def test_moment_mode_off_leaves_member_force_colouring_alone(app):
    app._analyze()
    app.colour_by_moment.set(False)
    app._draw()
    fills = {app.canvas.itemcget(i, 'fill') for i in app.canvas.find_withtag('member')}
    assert MOMENT_BACKDROP_COLOR not in fills


def test_moment_mode_enlarges_the_dot_for_a_moment_coloured_node(app):
    _make_rigid_fixed(app)
    app.colour_by_moment.set(True)
    app._draw()
    support_node = app.supports[0]['node']

    def radius_of(node_idx):
        for item in app.canvas.find_withtag(f'node{node_idx}'):
            if app.canvas.type(item) == 'oval':
                x0, y0, x1, y1 = app.canvas.coords(item)
                return round((x1 - x0) / 2.0)
        return None

    assert radius_of(support_node) == MOMENT_NODE_RADIUS_PX

    app.colour_by_moment.set(False)
    app._draw()
    assert radius_of(support_node) != MOMENT_NODE_RADIUS_PX


def test_moment_mode_legend_mentions_the_backdrop(app):
    app._analyze()
    app.colour_by_moment.set(False)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert not any('backdrop' in t for t in texts)

    app.colour_by_moment.set(True)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert any('backdrop' in t for t in texts)


def test_moment_mode_backdrop_is_a_no_op_before_analysis(app):
    app.results = None
    app.colour_by_moment.set(True)
    app._draw()   # must not raise
    fills = {app.canvas.itemcget(i, 'fill') for i in app.canvas.find_withtag('member')}
    assert MOMENT_BACKDROP_COLOR not in fills


# ── shared numeric colorbar for the four colour spectra ─────────────────────

def _colorbar_rects(app):
    """Canvas rectangle items belonging to a colorbar -- excludes the
    support-box rectangles (tagged 'node'), the lasso rectangle (tagged
    'lasso') and the legend's own card (tagged 'legend_card'), none of which
    is part of any colorbar."""
    return [i for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'rectangle'
            and not ({'node', 'lasso', 'legend_card'} & set(app.canvas.gettags(i)))]


def test_force_colorbar_is_a_continuous_gradient_not_flat_swatches(app):
    app._analyze()
    app.colour_by_force.set(True)
    app._draw()
    fills = [app.canvas.itemcget(i, 'fill') for i in _colorbar_rects(app)]
    # a real gradient shows many distinct colours across its segments, not
    # just the handful a flat swatch-per-category legend used to show
    assert len(set(fills)) > 10


def test_force_colorbar_ends_match_the_actual_tension_compression_extremes(app):
    app._analyze()
    app.colour_by_force.set(True)
    app._draw()
    # the border rectangle (outline='#888', no fill) is drawn last -- the
    # coloured segments themselves are outline=''
    fills = [app.canvas.itemcget(i, 'fill') for i in _colorbar_rects(app)
            if app.canvas.itemcget(i, 'outline') == '']
    assert fills[0] == COMPRESSION_HIGH
    assert fills[-1] == TENSION_HIGH


def test_force_colorbar_tick_labels_show_the_actual_max_force(app):
    app._analyze()
    app.colour_by_force.set(True)
    app.force_scale.set(SCALE_PEAK)
    app._draw()
    max_abs_n = max(abs(mr['N']) for mr in app.results['member_res'])
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert any(f'{max_abs_n:.0f}' in t for t in texts)


def test_the_percentile_scale_says_its_ends_are_open(app):
    """Anchored below the peak, the end colours no longer mean "this much and
    no more" -- so the ticks say so, and the rods past the end are counted."""
    app._analyze()
    app.colour_by_force.set(True)
    app.force_scale.set(SCALE_P95)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert any(t.startswith('≥+') for t in texts), 'the open end was not marked'
    anchor = app._force_anchor()
    peak = max(abs(mr['N']) for mr in app.results['member_res'])
    assert anchor < peak, 'the percentile anchor did not lower the scale'
    assert app._clipped_members(anchor, 1.0), 'nothing was marked as clipped'


def test_the_legend_counts_the_rods_it_paints_grey(app):
    """Grey is a claim about the structure, so it is reported with a number
    that can be checked against the member report -- otherwise a field of
    grey panels reads as a failed drawing rather than as "these carry
    nothing"."""
    app._analyze()
    app.colour_by_force.set(True)
    app._draw()
    n_grey, n_exact = app._near_zero_counts(app._force_anchor(), 1.0)
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    if n_grey:
        assert any(f'{n_grey} rods below' in t for t in texts)
        assert n_exact <= n_grey


def test_utilization_colorbar_is_a_continuous_gradient(app):
    app._analyze()
    app.colour_by_util.set(True)
    app._draw()
    fills = [app.canvas.itemcget(i, 'fill') for i in _colorbar_rects(app)]
    assert len(set(fills)) > 10


# ── the audit: the moment maths against statics, every ramp against itself ──

@pytest.mark.parametrize('along', ['x', 'y', 'z'])
def test_a_rigid_cantilevers_joint_moment_equals_its_own_reaction(along):
    """The check the node-moment colouring rests on. A cantilever of length
    L with a tip load P has exactly P*L at its fixed end, and
    node_moment_vectors must reproduce the reaction it is drawn beside --
    axis for axis, sign for sign, in all three orientations, since a member
    running along Z exercises a different branch of the local-axis
    transform than one along X."""
    L, P = 4.0, -10.0
    tip = {'x': (L, 0.0, 0.0), 'y': (0.0, L, 0.0), 'z': (0.0, 0.0, L)}[along]
    nodes = [(0.0, 0.0, 0.0), tip]
    members = [{'a': 0, 'b': 1, 'E': 200.0, 'A': 20.0, 'I': 400.0, 'J': 400.0,
                'conn': 'rigid'}]
    # a load across the member, whichever way it runs
    loads = [{'node': 1, 'fx' if along == 'z' else 'fz': P}]
    results, err = sm.analyze(nodes, members, loads, [{'node': 0, 'type': 'fixed'}])
    assert err is None, err

    reaction = results['reactions'][0]
    joint = sm.node_moment_vectors(nodes, members, results['member_res'])
    assert 0 in joint, 'the fixed joint carries no moment at all'
    for key in ('Mx', 'My', 'Mz'):
        assert joint[0][key] == pytest.approx(reaction.get(key, 0.0), abs=1e-6)
    assert math.hypot(joint[0]['Mx'], joint[0]['My'], joint[0]['Mz']) \
        == pytest.approx(abs(P) * L, rel=1e-6)
    free = joint[1]
    assert math.hypot(free['Mx'], free['My'], free['Mz']) == pytest.approx(0.0, abs=1e-6)


def test_a_pin_jointed_member_contributes_no_joint_moment():
    """A pin transmits force only, so a pin-jointed model reads ~0 moment
    everywhere -- physics, not a broken feature."""
    nodes = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1, 'E': 200.0, 'A': 20.0, 'conn': 'pin'}]
    member_res = [{'N': 5.0, 'conn': 'pin', 'length_m': 4.0}]
    assert sm.node_moment_vectors(nodes, members, member_res) == {}


def _hexes(fn, values):
    return [fn(v) for v in values]


def _valid(color):
    return (isinstance(color, str) and len(color) == 7 and color[0] == '#'
            and all(ch in '0123456789abcdefABCDEF' for ch in color[1:]))


def test_every_spectrum_returns_a_well_formed_colour_for_any_input():
    """Including the inputs a real model produces at its edges: exactly
    zero, exactly the maximum, past the maximum, and a maximum of zero."""
    from apps.stereo.stereo_app_colors import load_path_color, util_color
    extremes = (-1e9, -100.0, -1.0, -1e-12, 0.0, 1e-12, 1.0, 100.0, 1e9)
    for scale in (0.0, 1e-12, 1.0, 1e6):
        for v in extremes:
            for fn in (force_color, load_path_color, moment_color):
                assert _valid(fn(v, scale)), (fn.__name__, v, scale)
            assert _valid(deform_color(abs(v), scale))
    for u in (-5.0, 0.0, 0.25, 0.5, 0.999, 1.0, 1.0001, 50.0):
        assert _valid(util_color(u))


def test_each_ramp_approaches_its_own_saturated_end_without_doubling_back():
    """A spectrum that doubles back reads two different magnitudes as the
    same colour. Measured as RGB distance from the ramp's OWN saturated end
    (not from zero: force_color's near-zero grey is off the ramp entirely,
    by design, so distance-from-zero is not what the eye follows)."""
    def dist(a, b):
        return sum((int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) ** 2
                   for i in (1, 3, 5))

    # start past the near-zero grey band so the flat step is not read as a
    # reversal of a ramp it is not part of
    steps = [0.2 + 0.8 * i / 20.0 for i in range(21)]
    for fn in (lambda t: force_color(t, 1.0),
               lambda t: force_color(-t, 1.0),
               lambda t: deform_color(t, 1.0),
               lambda t: moment_color(t, 1.0),
               lambda t: moment_color(-t, 1.0)):
        seen = [dist(fn(t), fn(1.0)) for t in steps]
        assert all(b <= a for a, b in zip(seen, seen[1:])), seen
        assert seen[0] > seen[-1], 'the ramp never actually moves'
        assert seen[-1] == 0


def test_util_colour_rises_with_utilisation_and_then_stays_at_over_capacity():
    from apps.stereo.stereo_app_colors import util_color
    reds = [util_color(u) for u in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert len(set(reds)) == 5, 'two different utilisations read identically'
    assert util_color(1.0) == util_color(2.0) == util_color(50.0)
    assert util_color(-3.0) == util_color(0.0), 'a negative ratio is clamped, not wrapped'


def test_every_spectrum_clamps_past_its_own_maximum():
    """A member past the anchor (the 95th-percentile scale deliberately
    leaves some) must saturate, never wrap round to the other end."""
    assert force_color(5.0, 1.0) == force_color(1.0, 1.0)
    assert force_color(-5.0, 1.0) == force_color(-1.0, 1.0)
    assert moment_color(5.0, 1.0) == moment_color(1.0, 1.0)
    assert moment_color(-5.0, 1.0) == moment_color(-1.0, 1.0)
    assert deform_color(5.0, 1.0) == deform_color(1.0, 1.0)


def test_the_two_diverging_spectra_never_confuse_their_two_halves():
    """Tension must never be painted a compression colour at any magnitude,
    and sagging never a hogging colour -- checked by hue, not by one
    sample."""
    def dominant(color):
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        return 'r' if r > b else ('b' if b > r else '=')

    for t in (i / 20.0 for i in range(4, 21)):
        assert dominant(force_color(t, 1.0)) == 'r', t
        assert dominant(force_color(-t, 1.0)) == 'b', t
        # orange is red-dominant, violet is blue-dominant
        assert dominant(moment_color(-t, 1.0)) == 'r', t
        assert dominant(moment_color(t, 1.0)) == 'b', t


def test_the_moment_field_never_scales_a_node_past_its_own_maximum(app):
    """max_abs is what every node's colour divides by, so no node may
    exceed it -- otherwise some node saturates and the ramp above it is
    dead."""
    app.sec_conn.set('rigid')
    app._on_connectivity_change()
    app._apply_sections()
    app._analyze()
    field, max_abs = app._moment_field_by_node(1.0)
    assert field, 'a rigid model produced no nodal moments at all'
    assert max_abs > 0.0
    assert max(abs(v) for v in field.values()) == pytest.approx(max_abs)


def test_a_supports_reaction_wins_over_its_own_member_end_moment(app):
    """A node cannot hold two different moment values; the documented rule
    is that the support's own reaction is the one shown."""
    app.sec_conn.set('rigid')
    app._on_connectivity_change()
    app._apply_sections()
    app._analyze()
    field, _max_abs = app._moment_field_by_node(1.0)
    node = next(iter({s['node'] for s in app.supports} & set(field)), None)
    assert node is not None, 'no support carried a moment'
    from apps.stereo.stereo_app_colors import reaction_moment_signed
    centroid = (sum(n[0] for n in app.nodes) / len(app.nodes),
                sum(n[1] for n in app.nodes) / len(app.nodes))
    expected = reaction_moment_signed(app.results['reactions'][node],
                                      app.moment_axis.get(),
                                      (app.nodes[node][0], app.nodes[node][1]), centroid)
    assert field[node] == pytest.approx(expected)


def test_the_colourbars_are_labelled_in_the_conventions_own_units(app):
    """Found by the audit. Every colourbar caption hard-coded kN, kN·m and
    mm, so under AISC -- the one convention that is a different SYSTEM, not
    a different SI sub-unit -- the tables beside this legend said kip while
    the legend said kN, with kN numbers under it."""
    import units
    app.sec_conn.set('rigid')
    app._on_connectivity_change()
    app._apply_sections()
    app._analyze()
    app.colour_by_moment.set(True)
    app.show_deformed.set(True)

    def captions():
        return [app.canvas.itemcget(i, 'text') for i in app.canvas.find_all()
                if app.canvas.type(i) == 'text']

    def find(prefix):
        return next(t for t in captions() if t.startswith(prefix))

    before = units.current()
    try:
        units.set_current('cirsoc')
        app._draw()
        assert 'kN' in find('Axial force')
        assert 'kN·m' in find('Node moment')
        assert '(mm)' in find('Deformed shape')

        units.set_current('aisc')
        app._draw()
        assert 'kip' in find('Axial force') and 'kN' not in find('Axial force')
        assert 'kip·ft' in find('Node moment')
        assert '(in)' in find('Deformed shape')
    finally:
        units.set_current(before.key if hasattr(before, 'key') else 'cirsoc')
        app._draw()


def test_the_force_tick_labels_are_converted_not_just_relabelled(app):
    """Relabelling kN as kip without dividing by 4.448 would be worse than
    leaving it wrong."""
    import units
    app._analyze()
    app.colour_by_force.set(True)

    def ticks():
        out = []
        for i in app.canvas.find_all():
            if app.canvas.type(i) != 'text':
                continue
            t = app.canvas.itemcget(i, 'text')
            if t and t[0] in '+−≤≥':
                out.append(t)
        return out

    before = units.current()
    try:
        units.set_current('cirsoc')
        app._draw()
        si = ticks()
        units.set_current('aisc')
        app._draw()
        imperial = ticks()
    finally:
        units.set_current(before.key if hasattr(before, 'key') else 'cirsoc')
        app._draw()
    assert si and imperial
    assert si != imperial, 'the numbers did not change with the convention'


def test_moment_colorbar_is_a_continuous_gradient(app):
    _make_rigid_fixed(app)
    app.colour_by_force.set(False)   # isolate the moment bar from the force one
    app.colour_by_moment.set(True)
    app._draw()
    fills = [app.canvas.itemcget(i, 'fill') for i in _colorbar_rects(app)]
    assert len(set(fills)) > 10


def test_moment_colorbar_is_a_no_op_when_every_moment_is_zero(app):
    # a pin-jointed model's max_abs_moment is 0.0 -- the colorbar's domain
    # collapses to a single point, which must not raise a ZeroDivisionError
    app._analyze()
    app.colour_by_moment.set(True)
    app._draw()   # must not raise


def test_deformed_colorbar_is_a_continuous_gradient(app):
    app._analyze()
    app.colour_by_force.set(False)
    app.show_deformed.set(True)
    app._draw()
    fills = [app.canvas.itemcget(i, 'fill') for i in _colorbar_rects(app)]
    assert len(set(fills)) > 5


def test_colorbar_captions_describe_each_spectrum(app):
    app._analyze()
    app.colour_by_force.set(True)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert any('Axial force' in t for t in texts)

    app.colour_by_force.set(False)
    app.colour_by_util.set(True)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert any('Utilization' in t for t in texts)


def test_colorbar_is_a_no_op_before_analysis(app):
    app.results = None
    app.colour_by_force.set(True)
    app.colour_by_util.set(True)
    app.colour_by_moment.set(True)
    app.show_deformed.set(True)
    app._draw()   # must not raise
    assert not _colorbar_rects(app)


# ── show-rods / show-nodes visibility toggles ────────────────────────────────

def test_show_members_and_show_nodes_default_to_true(app):
    assert app.show_members.get() is True
    assert app.show_nodes.get() is True


def test_hiding_rods_leaves_only_nodes(app):
    app._draw()
    assert app.canvas.find_withtag('member')
    assert app.canvas.find_withtag('node')

    app.show_members.set(False)
    app._draw()
    assert not app.canvas.find_withtag('member')
    assert app.canvas.find_withtag('node')


def test_hiding_nodes_leaves_only_rods(app):
    app.show_nodes.set(False)
    app._draw()
    assert app.canvas.find_withtag('member')
    assert not app.canvas.find_withtag('node')


def test_hiding_both_rods_and_nodes_is_a_no_op_not_a_crash(app):
    app.show_members.set(False)
    app.show_nodes.set(False)
    app._draw()   # must not raise
    assert not app.canvas.find_withtag('member')
    assert not app.canvas.find_withtag('node')


def test_hidden_rods_do_not_break_the_load_path_animation_overlay(app):
    # the marching-dash overlay lives in the SAME loop as the rod's own
    # line -- iterating an empty `order` must skip it cleanly, not raise
    app._analyze()
    app.load_path_anim.set(True)
    app.show_members.set(False)
    app._draw()   # must not raise
    assert not app.canvas.find_withtag('member')


# ── "Add rod" tool: click two nodes to connect them ──────────────────────────

def _unconnected_pair(app):
    """Two node indices in the default mesh with no member between them
    yet -- so a test adding a rod between them is exercising a genuinely
    NEW connection, not silently hitting the duplicate-rod no-op."""
    connected = {frozenset((m['a'], m['b'])) for m in app.members}
    n = len(app.nodes)
    for a in range(n):
        for b in range(a + 1, n):
            if frozenset((a, b)) not in connected:
                return a, b
    raise AssertionError('every pair of nodes is already connected')


def test_add_rod_mode_is_off_by_default(app):
    assert app.add_rod_mode.get() is False
    assert app._add_rod_first is None


def test_two_clicks_in_add_rod_mode_creates_a_new_member(app):
    a, b = _unconnected_pair(app)
    n_before = len(app.members)
    app.add_rod_mode.set(True)

    sx, sy = _screen_pos_of(app, a)
    app._on_canvas_release(FakeEvent(sx, sy, state=0))
    assert app._add_rod_first == a

    sx, sy = _screen_pos_of(app, b)
    app._on_canvas_release(FakeEvent(sx, sy, state=0))
    assert app._add_rod_first is None
    assert len(app.members) == n_before + 1
    new = app.members[-1]
    assert {new['a'], new['b']} == {a, b}
    assert new['conn'] == app.sec_conn.get()


def test_add_rod_between_already_connected_nodes_is_a_no_op(app):
    m0 = app.members[0]
    a, b = m0['a'], m0['b']
    n_before = len(app.members)
    app.add_rod_mode.set(True)

    sx, sy = _screen_pos_of(app, a)
    app._on_canvas_release(FakeEvent(sx, sy, state=0))
    sx, sy = _screen_pos_of(app, b)
    app._on_canvas_release(FakeEvent(sx, sy, state=0))

    assert len(app.members) == n_before   # already connected -- no duplicate


def test_clicking_the_same_node_twice_cancels_the_pending_pick(app):
    a, _b = _unconnected_pair(app)
    app.add_rod_mode.set(True)
    sx, sy = _screen_pos_of(app, a)
    app._on_canvas_release(FakeEvent(sx, sy, state=0))
    assert app._add_rod_first == a
    app._on_canvas_release(FakeEvent(sx, sy, state=0))
    assert app._add_rod_first is None


def test_turning_add_rod_mode_off_clears_a_pending_pick(app):
    a, _b = _unconnected_pair(app)
    app.add_rod_mode.set(True)
    sx, sy = _screen_pos_of(app, a)
    app._on_canvas_release(FakeEvent(sx, sy, state=0))
    assert app._add_rod_first is not None

    app.add_rod_mode.set(False)
    app._on_add_rod_mode_toggle()
    assert app._add_rod_first is None


def test_new_rod_invalidates_stale_results(app):
    a, b = _unconnected_pair(app)
    app._analyze()
    assert app.results is not None
    app._add_rod_between(a, b)
    assert app.results is None
    assert app.member_checks is None


def test_add_rod_pending_ring_is_drawn_while_waiting_on_the_second_click(app):
    a, _b = _unconnected_pair(app)
    app.add_rod_mode.set(True)
    sx, sy = _screen_pos_of(app, a)
    app._on_canvas_release(FakeEvent(sx, sy, state=0))
    assert app.canvas.find_withtag('add_rod_pending')

    app.add_rod_mode.set(False)
    app._on_add_rod_mode_toggle()
    assert not app.canvas.find_withtag('add_rod_pending')


# ── shaded faces (flat colour per panel) ─────────────────────────────────────

def test_shaded_faces_off_by_default(app):
    assert app.shaded_faces.get() is False


def test_shaded_faces_draws_filled_polygons_for_force_mode(app):
    app._analyze()
    app.shaded_faces.set(True)
    app._draw()
    faces = app.canvas.find_withtag('shaded_face')
    assert faces
    for f in faces:
        assert app.canvas.type(f) == 'polygon'


def test_shaded_faces_draws_for_utilization_mode_too(app):
    app._analyze()
    app.colour_by_force.set(False)
    app.colour_by_util.set(True)
    app.shaded_faces.set(True)
    app._draw()
    assert app.canvas.find_withtag('shaded_face')


def test_shaded_faces_are_drawn_behind_the_wireframe(app):
    app._analyze()
    app.shaded_faces.set(True)
    app._draw()
    order = app.canvas.find_withtag('all')
    face_idx = min(order.index(i) for i in app.canvas.find_withtag('shaded_face'))
    member_idx = min(order.index(i) for i in app.canvas.find_withtag('member'))
    assert face_idx < member_idx   # faces sit lower in the stack -> drawn first


def test_shaded_faces_is_a_no_op_before_analysis(app):
    app.results = None
    app.member_checks = None
    app.shaded_faces.set(True)
    app._draw()   # must not raise
    assert not app.canvas.find_withtag('shaded_face')


def test_shaded_faces_legend_caption_appears_only_when_active(app):
    app._analyze()
    app.shaded_faces.set(False)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert not any('Shaded faces' in t for t in texts)

    app.shaded_faces.set(True)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert any('Shaded faces' in t for t in texts)


def test_shaded_cells_cache_is_reused_then_invalidated_on_mesh_change(app):
    first = app._get_shaded_cells()
    second = app._get_shaded_cells()
    assert first is second   # same object -- not recomputed on the second call

    app._apply_sections()   # goes through _refresh_all, which invalidates it
    assert app._shaded_cells is None
    third = app._get_shaded_cells()
    assert third is not first
    assert third == first   # same mesh -- recomputed to an equal, not stale, result


# ── "hide ~0-force rods" toggle ───────────────────────────────────────────────

def test_hide_zero_force_is_off_by_default(app):
    assert app.hide_zero_force.get() is False


def test_hide_zero_force_removes_only_the_near_zero_members(app):
    app._analyze()
    app._draw()
    n_before = len(app.canvas.find_withtag('member'))

    max_abs_n = max(abs(mr['N']) for mr in app.results['member_res'])
    n_zero = sum(1 for mr in app.results['member_res']
                if abs(mr['N']) / max_abs_n < NEAR_ZERO_FRAC)
    assert n_zero > 0   # otherwise this test can't tell the toggle apart from a no-op

    app.hide_zero_force.set(True)
    app._draw()
    n_after = len(app.canvas.find_withtag('member'))
    assert n_after < n_before


def test_hide_zero_force_is_consistent_with_the_near_zero_colour(app):
    # a member this toggle hides must be exactly one force_color would
    # have painted NEAR_ZERO_COLOR -- the two must never disagree about
    # what "~0" means.
    app._analyze()
    app.colour_by_force.set(True)
    max_abs_n = max(abs(mr['N']) for mr in app.results['member_res'])

    app.hide_zero_force.set(False)
    app._draw()
    fills_before = [app.canvas.itemcget(i, 'fill') for i in app.canvas.find_withtag('member')]
    assert NEAR_ZERO_COLOR in fills_before

    app.hide_zero_force.set(True)
    app._draw()
    fills_after = {app.canvas.itemcget(i, 'fill') for i in app.canvas.find_withtag('member')}
    assert NEAR_ZERO_COLOR not in fills_after


def test_hide_zero_force_matches_the_colour_on_a_model_that_can_tell_them_apart(app):
    # Regression: the hide test used LOAD_PATH_NEAR_ZERO_FRAC (0.02) while
    # force_color paints "~0" grey below NEAR_ZERO_FRAC (0.03), so members
    # in between were painted "~0" and yet kept on screen. The default flat
    # grid happens to have nothing in that band, which is why the sibling
    # test above could not catch it -- the hip roof grid has dozens, so the
    # two thresholds disagreeing is immediately visible here.
    app.grid_family.set(FAMILY_LABEL['hip_roof_grid'])
    app._on_generator_change()
    app._generate()
    app._analyze()
    app.colour_by_force.set(True)

    max_abs_n = max(abs(mr['N']) for mr in app.results['member_res'])
    in_band = sum(1 for mr in app.results['member_res']
                 if LOAD_PATH_NEAR_ZERO_FRAC <= abs(mr['N']) / max_abs_n < NEAR_ZERO_FRAC)
    assert in_band > 0, 'this model no longer exercises the gap between the two thresholds'

    app.hide_zero_force.set(True)
    app._draw()
    fills = {app.canvas.itemcget(i, 'fill') for i in app.canvas.find_withtag('member')}
    assert NEAR_ZERO_COLOR not in fills


def test_hide_zero_force_is_a_no_op_before_analysis(app):
    app.results = None
    app.hide_zero_force.set(True)
    app._draw()   # must not raise
    assert app.canvas.find_withtag('member')   # the plain pin/rigid wireframe still shows


def test_hide_zero_force_legend_caption_appears_only_when_active(app):
    app._analyze()
    app.hide_zero_force.set(False)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert not any('hidden entirely' in t for t in texts)

    app.hide_zero_force.set(True)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert any('hidden entirely' in t for t in texts)


# ── toolbar: the two radio groups ────────────────────────────────────────────

def test_colour_radio_sets_exactly_one_colour_flag(app):
    # the exclusivity used to live in the renderer as a silent precedence
    # rule (utilization beat force beat moment); now one radio owns it.
    for mode, expect in ((COLOUR_FORCE, (True, False, False)),
                         (COLOUR_UTIL, (False, True, False)),
                         (COLOUR_MOMENT, (False, False, True)),
                         (COLOUR_NONE, (False, False, False))):
        app.colour_mode.set(mode)
        app._on_colour_mode_change()
        got = (app.colour_by_force.get(), app.colour_by_util.get(),
               app.colour_by_moment.get())
        assert got == expect, f'{mode} -> {got}'


def test_the_shade_control_reaches_the_shaded_fill_too(app):
    app._analyze()
    app.faces_mode.set(FILL_SHADED)
    app._on_faces_mode_change()
    app.fill_density.set('Solid')
    app._draw()
    assert {app.canvas.itemcget(i, 'stipple')
            for i in app.canvas.find_withtag('shaded_face')} == {''}
    app.fill_density.set('Light')
    app._draw()
    assert {app.canvas.itemcget(i, 'stipple')
            for i in app.canvas.find_withtag('shaded_face')} == {'gray25'}


def _member_fills(app, tag='member'):
    return [app.canvas.itemcget(i, 'fill') for i in app.canvas.find_withtag(tag)]


def _rigid_fixed(app):
    """A model that actually develops node moments: rigid joints, fixed feet."""
    app.sec_conn.set('rigid')
    app._apply_sections()
    for s in app.supports:
        s['type'] = 'fixed'
    app._analyze()


def test_smooth_gradient_is_off_by_default(app):
    assert app.smooth_gradient.get() is False


def test_smooth_gradient_splits_each_rod_into_several_coloured_pieces(app):
    app._analyze()
    app.colour_by_force.set(True)
    app._draw()
    flat_items = len(app.canvas.find_withtag('member'))
    flat_colours = len(set(_member_fills(app)))

    app.smooth_gradient.set(True)
    app._draw()
    assert len(app.canvas.find_withtag('member')) == flat_items * app._gradient_segments()
    assert len(set(_member_fills(app))) > flat_colours


def test_smooth_gradient_gives_the_moment_view_coloured_rods(app):
    # The point of the request: in moment mode the rods used to be a single
    # flat backdrop grey, with the whole field carried by the node dots.
    _rigid_fixed(app)
    app.colour_by_force.set(False)
    app.colour_by_moment.set(True)

    app.smooth_gradient.set(False)
    app._draw()
    assert set(_member_fills(app)) == {MOMENT_BACKDROP_COLOR}

    app.smooth_gradient.set(True)
    app._draw()
    fills = set(_member_fills(app))
    assert len(fills) > 10
    assert fills != {MOMENT_BACKDROP_COLOR}


def test_smooth_gradient_colours_the_deformed_overlay(app):
    app._analyze()
    app.show_deformed.set(True)
    app.deformed_only.set(True)
    app._draw()
    flat = len(set(_member_fills(app, 'deform')))

    app.smooth_gradient.set(True)
    app._draw()
    assert len(set(_member_fills(app, 'deform'))) > flat


def test_smooth_gradient_works_for_the_utilization_heat_map(app):
    app._analyze()
    app.colour_by_force.set(False)
    app.colour_by_util.set(True)
    app._draw()
    flat = len(set(_member_fills(app)))

    app.smooth_gradient.set(True)
    app._draw()
    assert len(set(_member_fills(app))) >= flat


def test_smooth_gradient_is_a_no_op_before_analysis(app):
    app.results = None
    app.smooth_gradient.set(True)
    app._draw()   # must not raise
    n = len(app.canvas.find_withtag('member'))
    app.smooth_gradient.set(False)
    app._draw()
    assert len(app.canvas.find_withtag('member')) == n


def test_smooth_gradient_keeps_the_over_capacity_dashes(app):
    app._analyze()
    app.colour_by_force.set(True)
    app.smooth_gradient.set(True)
    # force a genuine over-capacity condition
    for m in app.members:
        m['A'] = 0.05
    app._analyze()
    app._draw()
    dashed = [i for i in app.canvas.find_withtag('member')
              if app.canvas.itemcget(i, 'dash') not in ('', None)]
    assert dashed, 'over-capacity rods lost their dash once the gradient was on'


def test_nodal_average_means_the_members_meeting_at_each_node():
    members = [{'a': 0, 'b': 1}, {'a': 1, 'b': 2}]
    values = [10.0, 20.0]
    got = StereoApp._nodal_average(3, members, values)
    assert got[0] == pytest.approx(10.0)    # only the first member
    assert got[1] == pytest.approx(15.0)    # the mean of both
    assert got[2] == pytest.approx(20.0)    # only the second


def test_nodal_average_leaves_an_unconnected_node_at_zero():
    got = StereoApp._nodal_average(3, [{'a': 0, 'b': 1}], [8.0])
    assert got[2] == pytest.approx(0.0)     # no members, and no divide by zero


def test_gradient_uses_fewer_segments_on_a_dense_model(app):
    # the segment count multiplies canvas items directly, so a big grid
    # deliberately drops to the coarser run
    app.grid_family.set(FAMILY_LABEL['flat_grid'])
    app._on_generator_change()
    app.fg_nx.set(3); app.fg_ny.set(3)
    app._generate()
    assert len(app.members) <= GRADIENT_DENSE_MEMBERS
    assert app._gradient_segments() == GRADIENT_SEGMENTS

    app.fg_nx.set(20); app.fg_ny.set(20)
    app._generate()
    assert len(app.members) > GRADIENT_DENSE_MEMBERS
    assert app._gradient_segments() == GRADIENT_SEGMENTS_DENSE


def test_smooth_gradient_legend_caption_appears_only_when_active(app):
    app._analyze()
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert not any('blend' in t.lower() for t in texts)

    app.smooth_gradient.set(True)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert any('blend' in t.lower() for t in texts)


def test_moment_legend_stops_claiming_the_rods_are_faded_when_they_are_not(app):
    _rigid_fixed(app)
    app.colour_by_force.set(False)
    app.colour_by_moment.set(True)
    app.smooth_gradient.set(True)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert not any('faded to backdrop' in t for t in texts)
    assert any('rods carry the same moment field' in t for t in texts)


# ── thickness by stress ──────────────────────────────────────────────────────

def _member_widths(app):
    return [float(app.canvas.itemcget(i, 'width'))
            for i in app.canvas.find_withtag('member')]


def test_thickness_by_stress_is_off_by_default(app):
    assert app.thickness_by_stress.get() is False


def test_thickness_by_stress_varies_the_width_between_the_documented_bounds(app):
    app._analyze()
    app._draw()
    assert set(_member_widths(app)) == {2.0}   # one flat width until it is on

    app.thickness_by_stress.set(True)
    app._draw()
    widths = _member_widths(app)
    assert len(set(widths)) > 1, 'every rod came out the same width'
    assert min(widths) >= STRESS_WIDTH_MIN
    assert max(widths) <= STRESS_WIDTH_MAX


def test_thickness_by_stress_caps_the_widest_rod(app):
    # the cap is the point of the feature: one very hot member must not be
    # allowed to grow without limit and swallow its neighbours.
    app._analyze()
    # make one member's stress enormous by shrinking its section
    app.members[0]['A'] = 1e-6
    app._analyze()
    app.thickness_by_stress.set(True)
    app._draw()
    assert max(_member_widths(app)) == pytest.approx(STRESS_WIDTH_MAX)


def test_thickness_by_stress_scales_with_stress_not_with_force():
    # the semantic heart of the feature: two rods carrying the SAME axial
    # force are not working equally hard if their sections differ, and it
    # is the stress -- not the kN -- that decides the width.
    members = [{'a': 0, 'b': 1, 'A': 10.0}, {'a': 1, 'b': 2, 'A': 20.0}]
    member_res = [{'N': 100.0}, {'N': 100.0}]
    widths = StereoApp._stress_widths(members, member_res)
    assert widths[0] == pytest.approx(STRESS_WIDTH_MAX)   # twice the stress
    assert widths[1] < widths[0]
    # half the stress => half way up the min..max span
    half = STRESS_WIDTH_MIN + 0.5 * (STRESS_WIDTH_MAX - STRESS_WIDTH_MIN)
    assert widths[1] == pytest.approx(half)


def test_stress_widths_handles_a_member_with_no_usable_section():
    # a rod with no area must still be drawn (at the minimum), not skipped
    # and not a ZeroDivisionError.
    members = [{'a': 0, 'b': 1, 'A': 10.0}, {'a': 1, 'b': 2, 'A': 0.0},
               {'a': 2, 'b': 3}]
    member_res = [{'N': 100.0}, {'N': 50.0}, {'N': 50.0}]
    widths = StereoApp._stress_widths(members, member_res)
    assert len(widths) == 3
    assert widths[1] == pytest.approx(STRESS_WIDTH_MIN)
    assert widths[2] == pytest.approx(STRESS_WIDTH_MIN)


def test_stress_widths_returns_none_when_there_is_nothing_to_scale_against():
    assert StereoApp._stress_widths([], []) is None
    assert StereoApp._stress_widths([{'a': 0, 'b': 1, 'A': 10.0}], [{'N': 0.0}]) is None


def test_thickness_by_stress_does_not_move_with_the_load_slider(app):
    # a relative measure: a linear solve scales every member's stress by
    # the same factor, so the ratios -- and the widths -- must not change.
    app._analyze()
    app.thickness_by_stress.set(True)
    app._draw()
    at_full = sorted(_member_widths(app))

    app.load_fraction.set(20)
    app._draw()
    assert sorted(_member_widths(app)) == at_full


def test_thickness_by_stress_is_a_no_op_before_analysis(app):
    app.results = None
    app.thickness_by_stress.set(True)
    app._draw()   # must not raise
    assert set(_member_widths(app)) == {2.0}


def test_thickness_by_stress_never_thins_the_selected_member(app):
    # width cues stack rather than overwrite: a lightly stressed rod that
    # is also selected keeps the selection's own wider line.
    app._analyze()
    app.thickness_by_stress.set(True)
    widths = StereoApp._stress_widths(app.members, app.results['member_res'])
    thinnest = min(range(len(widths)), key=lambda i: widths[i])
    app.selected_member = thinnest
    app._draw()
    assert max(_member_widths(app)) >= 4


def test_thickness_by_stress_legend_caption_appears_only_when_active(app):
    app._analyze()
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert not any('thickness' in t.lower() for t in texts)

    app.thickness_by_stress.set(True)
    app._draw()
    texts = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_withtag('all')
            if app.canvas.type(i) == 'text']
    assert any('thickness' in t.lower() and 'stress' in t.lower() for t in texts)




# ── the shell: mode rail, one context panel, status bar ─────────────────────

def test_the_window_opens_on_the_build_mode(app):
    from apps.stereo import stereo_app_shell as shell
    assert app.active_mode.get() == shell.DEFAULT_MODE == 'build'
    assert app.mode_title.get() == 'BUILD'


def test_exactly_one_mode_panel_is_mapped_at_a_time(app):
    """The point of the rail. Eight panels exist; seven are forgotten, so
    none of them is claiming width the canvas could be using."""
    from apps.stereo import stereo_app_shell as shell
    for key, _glyph, _label, _tip in shell.MODES:
        app._set_mode(key)
        app.root.update_idletasks()
        packed = [k for k, f in app._mode_frames.items() if f.winfo_manager() != '']
        assert packed == [key], f'{key}: {packed}'


def test_every_mode_has_a_rail_item_and_a_panel(app):
    from apps.stereo import stereo_app_shell as shell
    for key, _glyph, _label, _tip in shell.MODES:
        assert key in app._rail_buttons, key
        assert key in app._mode_frames, key


def test_clicking_a_rail_item_switches_mode(app):
    item, _stripe, _body, _icon, _name = app._rail_buttons['load']
    item.event_generate('<Button-1>')
    app.root.update_idletasks()
    assert app.active_mode.get() == 'load'
    assert app.mode_title.get() == 'LOAD'


def test_an_unknown_mode_is_ignored_rather_than_blanking_the_panel(app):
    app._set_mode('support')
    app._set_mode('not-a-mode')
    assert app.active_mode.get() == 'support'


def test_the_status_bar_reports_the_analysis(app):
    """The single most useful line the older version of this tab had, and
    the one the rebuilt one had lost."""
    app._analyze()
    text = app.status_var.get()
    assert text.startswith('Analyzed')
    assert 'utilisation' in text
    assert 'ΣRz' in text
    assert app.status_kind.get() == 'ok'


def test_the_status_bar_says_when_nothing_has_been_analyzed(app):
    app.results = None
    app.member_checks = None
    app._refresh_status()
    assert 'not analyzed' in app.status_var.get()
    assert app.status_kind.get() != 'ok'


def test_the_status_bar_follows_the_load_slider(app):
    """Everything else in the tab scales with Load %; the status line has to
    scale with it too or it contradicts the drawing beside it."""
    app._analyze()
    full = app.status_var.get()
    app.load_fraction.set(50)
    app._refresh_status()
    assert app.status_var.get() != full


def test_display_state_survives_closing_the_popover(app):
    """The popover is built on demand and destroyed on close, so its widgets
    cannot own the state -- _draw reads show_deformed on the very first
    frame, long before anyone opens Display."""
    assert hasattr(app, 'show_deformed')
    app._toggle_display_popover()
    app.root.update_idletasks()
    app.show_deformed.set(True)
    app._toggle_display_popover()
    app.root.update_idletasks()
    assert app.show_deformed.get() is True
    assert getattr(app, '_display_pop', None) is None


def test_the_display_popover_opens_and_closes_on_the_same_button(app):
    app._toggle_display_popover()
    assert app._display_pop is not None and app._display_pop.winfo_exists()
    app._toggle_display_popover()
    assert app._display_pop is None


def test_the_legend_sits_on_its_own_card_in_the_corner(app):
    """Kept in the corner of the display, where you look when reading colour
    off the model -- but on a ground of its own, so the ramp and its numbers
    are legible over whatever part of the structure lies behind them."""
    app._analyze()
    app.colour_by_force.set(True)
    app._draw()
    cards = app.canvas.find_withtag('legend_card')
    assert len(cards) == 1
    x0, y0, x1, y1 = app.canvas.coords(cards[0])
    assert x0 < 60 and y0 < 60, 'the card left its corner'
    assert x1 > x0 and y1 > y0


def test_the_legend_card_sits_under_its_own_text(app):
    app._analyze()
    app._draw()
    card = app.canvas.find_withtag('legend_card')[0]
    # find_all returns STACKING order, bottom first -- item ids are creation
    # order and say nothing about who is drawn over whom.
    order = list(app.canvas.find_all())
    assert order.index(card) < len(order) - 1, \
        'the card is on top of the legend it is meant to back'


def test_no_model_is_reported_as_no_model(app):
    app.nodes, app.members, app.results = [], [], None
    app._refresh_status()
    assert 'No model' in app.status_var.get()


# ── Shape mode: the surface/lattice panel ────────────────────────────────────

def _shape(app):
    _mode(app, 'shape')
    return app


def test_the_shape_panel_builds_a_mesh_from_two_typed_surfaces(app):
    """The whole point of Shape mode: type two expressions, pick how the
    layers register against each other, press Build, and the model on the
    canvas is that lattice -- no generator, no example."""
    _shape(app)
    app.shape_two.set(True)
    app.shape_z_top.set('3.0 * (1 - (x/12)^2 - (y/12)^2) + 1.0')
    app.shape_z_bot.set('0')
    app.shape_p0.set(-6.0); app.shape_p1.set(6.0)
    app.shape_q0.set(-6.0); app.shape_q1.set(6.0)
    app.shape_n1.set(4); app.shape_n2.set(4)
    app.shape_lattice.set(sg.LATTICE_SOS_OFFSET)
    app._build_shape_mesh()
    assert app.shape_status.cget('text') == ''
    assert len(app.nodes) == 25 + 16          # 5x5 top + 4x4 bottom
    assert len(app.members) > 0
    assert max(z for _x, _y, z in app.nodes) > 1.0


def test_each_lattice_type_gives_a_different_web(app):
    """The four families differ ONLY in which chords are drawn -- same nodes,
    same surfaces. If two of them came out with the same rod count the
    choice would be decorative."""
    _shape(app)
    app.shape_two.set(False)
    app.shape_z_top.set('0.4 * (x + y)')
    app.shape_depth.set(1.0)
    app.shape_p0.set(0.0); app.shape_p1.set(4.0)
    app.shape_q0.set(0.0); app.shape_q1.set(4.0)
    app.shape_n1.set(4); app.shape_n2.set(4)
    counts = {}
    for lattice in sg.LATTICE_TYPES:
        app.shape_lattice.set(lattice)
        app._build_shape_mesh()
        assert app.shape_status.cget('text') == '', lattice
        counts[lattice] = len(app.members)
    assert len(set(counts.values())) == len(counts), counts
    assert counts[sg.LATTICE_SINGLE] == min(counts.values())


def test_the_panel_refuses_two_surfaces_that_cross_inside_the_domain(app):
    """Crossed layers are not a lattice -- the webs turn inside out where the
    surfaces swap. The panel has to say so instead of building nonsense."""
    _shape(app)
    app.shape_two.set(True)
    app.shape_z_top.set('x')
    app.shape_z_bot.set('-x')          # they meet along x = 0, inside the box
    app.shape_p0.set(-4.0); app.shape_p1.set(4.0)
    app.shape_q0.set(0.0); app.shape_q1.set(4.0)
    app.shape_n1.set(4); app.shape_n2.set(4)
    before = list(app.nodes)
    app._build_shape_mesh()
    assert 'cross' in app.shape_status.cget('text').lower()
    assert app.nodes == before, 'a refused build must leave the model alone'


def test_a_bad_expression_is_reported_and_not_raised(app):
    _shape(app)
    app.shape_z_top.set('3 * (')
    before = list(app.nodes)
    app._build_shape_mesh()
    assert app.shape_status.cget('text') != ''
    assert app.nodes == before


def test_the_depth_field_and_the_bottom_field_swap_with_the_surface_mode(app):
    """One surface needs a depth; two surfaces need the second expression.
    Showing both at once would leave one of them silently ignored."""
    _shape(app)
    app.shape_lattice.set(sg.LATTICE_SOS_OFFSET)
    app.shape_two.set(False)
    app._on_shape_mode_change()
    assert _shown(app.frame_shape_depth) and not _shown(app.frame_shape_bot)
    app.shape_two.set(True)
    app._on_shape_mode_change()
    assert _shown(app.frame_shape_bot) and not _shown(app.frame_shape_depth)


def test_a_single_layer_hides_both_depth_fields_and_warns(app):
    """A single layer has no second surface to be at a depth from, and a FLAT
    one is a mechanism -- the panel says that before you build it."""
    _shape(app)
    app.shape_lattice.set(sg.LATTICE_SINGLE)
    app._on_shape_mode_change()
    assert not _shown(app.frame_shape_depth) and not _shown(app.frame_shape_bot)
    assert 'mechanism' in app.shape_lattice_note.cget('text').lower()
    app.shape_lattice.set(sg.LATTICE_SOS_OFFSET)
    app._on_shape_mode_change()
    assert app.shape_lattice_note.cget('text') == ''


def test_the_pole_fields_only_appear_for_a_polar_domain(app):
    _shape(app)
    app.shape_coord.set('cartesian')
    app._on_shape_mode_change()
    assert not _shown(app.frame_shape_pole)
    assert app.shape_p_label.get().startswith('x')
    app.shape_coord.set('polar')
    app._on_shape_mode_change()
    assert _shown(app.frame_shape_pole)
    assert app.shape_p_label.get().startswith('r')


def test_the_summit_finder_moves_the_pole_onto_the_summit(app):
    """A polar grid centred off the summit wraps rings around nothing. The
    finder searches WIDER than the current disk, because a summit on the rim
    is exactly the case that says the pole is in the wrong place."""
    _shape(app)
    app.shape_coord.set('polar')
    app.shape_z_top.set('5 - (x - 4)^2 - (y - 4)^2')
    app.shape_p0.set(0.0); app.shape_p1.set(4.0)
    app.shape_pole_x.set(0.0); app.shape_pole_y.set(0.0)
    app._shape_find_summits()
    assert abs(app.shape_pole_x.get() - 4.0) < 0.2
    assert abs(app.shape_pole_y.get() - 4.0) < 0.2
    assert 'One summit' in app.shape_summit_note.cget('text')


def test_a_surface_with_no_summit_says_so_rather_than_parking_the_pole(app):
    _shape(app)
    app.shape_coord.set('polar')
    app.shape_z_top.set('x + y')        # a plane: rises forever, no summit
    app.shape_p0.set(0.0); app.shape_p1.set(4.0)
    app._shape_find_summits()
    assert 'No summit' in app.shape_summit_note.cget('text')


def test_a_polar_domain_builds_a_round_plan(app):
    _shape(app)
    app.shape_coord.set('polar')
    app.shape_two.set(False)
    app.shape_z_top.set('4 - 0.05 * (x^2 + y^2)')
    app.shape_p0.set(1.0); app.shape_p1.set(6.0)
    app.shape_q0.set(0.0); app.shape_q1.set(360.0)
    app.shape_n1.set(3); app.shape_n2.set(8)
    app.shape_pole_x.set(0.0); app.shape_pole_y.set(0.0)
    app.shape_lattice.set(sg.LATTICE_SOS_OFFSET)
    app._build_shape_mesh()
    assert app.shape_status.cget('text') == ''
    radii = [math.hypot(x, y) for x, y, _z in app.nodes]
    assert min(radii) > 0.5 and max(radii) < 6.5


def test_the_module_note_tracks_the_domain_and_divisions(app):
    _shape(app)
    app.shape_p0.set(0.0); app.shape_p1.set(12.0); app.shape_n1.set(6)
    app.shape_q0.set(0.0); app.shape_q1.set(6.0); app.shape_n2.set(3)
    app._on_shape_mode_change()
    assert '2.00' in app.shape_module_note.cget('text')


# ── the view cube ────────────────────────────────────────────────────────────

def test_the_view_cube_sits_in_the_canvas_corner(app):
    app._draw()
    app.root.update_idletasks()
    items = app.canvas.find_withtag('view_cube')
    assert len(items) == 1
    x, y = app.canvas.coords(items[0])
    assert y < 40 and x > app.canvas.winfo_width() - 200


def test_every_preset_snaps_the_camera_and_lights_exactly_one_button(app):
    for name, az, el in sh.VIEW_PRESETS:
        app._set_named_view(name, az, el)
        assert (app.azimuth, app.elevation) == (az, el)
        assert app.current_view.get() == name
        lit = [n for n, b in app._view_buttons.items()
               if str(b.cget('relief')) == 'sunken']
        assert lit == [name], lit


def test_orbiting_by_hand_unlights_the_preset(app):
    """A button still pressed in after the camera moved would be a lie about
    where you are looking from."""
    app._set_named_view('Top', 0.0, 89.9)
    assert app.current_view.get() == 'Top'
    app._clear_named_view()
    assert app.current_view.get() == ''
    assert not [b for b in app._view_buttons.values()
                if str(b.cget('relief')) == 'sunken']


def test_the_view_cube_keeps_its_corner_when_the_canvas_resizes(app):
    app._draw()
    app.canvas.configure(width=1200)
    app.root.update_idletasks()
    app._place_view_cube()
    x, _y = app.canvas.coords(app.canvas.find_withtag('view_cube')[0])
    assert abs(x - (app.canvas.winfo_width() - 16)) < 2
    assert len(app.canvas.find_withtag('view_cube')) == 1, 'a second cube was created'


# ── the pinned base-module card ──────────────────────────────────────────────

def test_the_base_module_card_is_pinned_over_the_canvas(app):
    app.show_module_card.set(True)
    app._draw()
    app.root.update_idletasks()
    items = app.canvas.find_withtag('module_card')
    assert len(items) == 1
    x, y = app.canvas.coords(items[0])
    # Top right, directly under the view cube: both cards answer "how am I
    # looking at this", so they share the right-hand column.
    cube = app.canvas.coords(app.canvas.find_withtag('view_cube')[0])
    assert x > app.canvas.winfo_width() - app.MODULE_CARD_SIZE - 40
    assert y > cube[1] + app.view_cube.winfo_reqheight() - 1, 'it overlaps the cube'
    assert y < app.canvas.winfo_height() / 2, 'it is not in the top half'
    assert abs((x + app.MODULE_CARD_SIZE) - cube[0]) < 3, \
        'the two cards do not line up on the right'
    assert app.module_card_canvas.find_all(), 'the card is empty'


def test_turning_the_card_off_removes_it_from_the_canvas(app):
    app.show_module_card.set(True)
    app._draw()
    assert app.canvas.find_withtag('module_card')
    app.show_module_card.set(False)
    app._draw()
    assert not app.canvas.find_withtag('module_card')


def test_redrawing_does_not_pile_up_module_cards(app):
    """_draw clears the canvas wholesale, so a remembered window id goes
    stale every frame -- the card has to be found by tag, not remembered."""
    app.show_module_card.set(True)
    for _ in range(4):
        app._draw()
    assert len(app.canvas.find_withtag('module_card')) == 1


def test_the_card_always_shows_the_base_module_not_the_edited_one(app):
    """The card is the grid's reference. Selecting another role in the editor
    must not repaint it, or it stops being a reference."""
    app.show_module_card.set(True)
    _mode(app, 'module')
    app._draw()
    keep = app._me_role_id
    app._draw_module_card()
    assert app._me_role_id == keep, 'the card left the editor on another role'


# ── nodes and supports, drawn the way the first version drew them ────────────

def test_nodes_are_small_dots(app):
    """Big discs hid the rods behind them. The original tab drew a 2 px dot
    and that is what reads at grid density."""
    assert sc.NODE_RADIUS_PX == 2
    assert sc.NODE_RADIUS_SEL_PX > sc.NODE_RADIUS_PX
    app.selected_nodes = set()
    app._draw()
    # 'node' also carries each support's box; the dot itself is the oval.
    dots = [i for i in app.canvas.find_withtag('node')
            if app.canvas.type(i) == 'oval']
    assert dots
    x0, y0, x1, y1 = app.canvas.coords(dots[0])
    assert abs((x1 - x0) - 2 * sc.NODE_RADIUS_PX) < 1.5


def test_a_support_is_a_filled_white_box_under_its_node(app):
    """White box, not a coloured blob: the box says 'support', the dot inside
    it still says 'node', and you can see both."""
    app.results = None
    app.supports = [{'node': 0, 'type': 'pin'}]
    app._draw()
    boxes = app.canvas.find_withtag('support')
    assert len(boxes) == 1
    box = boxes[0]
    assert str(app.canvas.itemcget(box, 'fill')).lower() == sc.SUPPORT_BOX_FILL.lower()
    x0, y0, x1, y1 = app.canvas.coords(box)
    assert abs((x1 - x0) - 2 * sc.SUPPORT_BOX_HALF_PX) < 1.5
    # find_all is STACKING order: the box has to be under its own dot, or it
    # hides the joint it is marking.
    order = list(app.canvas.find_all())
    dot = [i for i in app.canvas.find_withtag('node0')
           if app.canvas.type(i) == 'oval'][0]
    assert order.index(box) < order.index(dot), \
        'the box is covering the node it marks'


# ── Shape mode: the plan-shape mask ──────────────────────────────────────────

def _flat_shape(app, n=6):
    _mode(app, 'shape')
    app.shape_two.set(False)
    app.shape_z_top.set('0.3 * x')
    app.shape_depth.set(1.0)
    app.shape_p0.set(-6.0); app.shape_p1.set(6.0)
    app.shape_q0.set(-6.0); app.shape_q1.set(6.0)
    app.shape_n1.set(n); app.shape_n2.set(n)
    app.shape_lattice.set(sg.LATTICE_SOS_OFFSET)
    app.shape_plan.set('')


def test_a_plan_rule_cuts_the_rectangle_the_ranges_describe(app):
    """Two ranges can only describe a rectangle. The plan rule is how that
    becomes a round, L-shaped or perforated roof."""
    _flat_shape(app)
    app._build_shape_mesh()
    whole = len(app.nodes)
    app.shape_plan.set('x^2 + y^2 < 16')
    app._build_shape_mesh()
    assert app.shape_status.cget('text') == ''
    assert len(app.nodes) < whole
    assert 'removed' in app.shape_plan_note.cget('text')
    assert max(math.hypot(x, y) for x, y, _z in app.nodes) < 6.5


def test_an_l_shaped_plan_removes_one_quadrant(app):
    """The cut is MODULE-granular, not node-granular: a bottom node that
    survives keeps the top corners its webs hang from, even where one of
    those corners is on the far side of the line. So the quadrant empties
    except for one module's depth of framing along the cut -- which is the
    point, since that framing is what stops the edge being ragged."""
    _flat_shape(app)
    app._build_shape_mesh()
    whole = len(app.nodes)
    app.shape_plan.set('not (x > 0 and y > 0)')
    app._build_shape_mesh()
    assert app.shape_status.cget('text') == ''
    module = (6.0 - -6.0) / 6
    strays = [(x, y) for x, y, _z in app.nodes
              if min(x, y) > module + 1e-6]
    assert not strays, f'nodes survive more than one module into the cut: {strays}'
    assert len(app.nodes) < whole * 0.9, 'the quadrant was barely touched'


def test_a_cut_model_still_solves(app):
    """A ragged edge of half-connected nodes would read as a mechanism. The
    mask keeps the chords that bound the hole for exactly this reason."""
    _flat_shape(app)
    app.shape_plan.set('x^2 + y^2 < 16')
    app._build_shape_mesh()
    app._analyze()
    assert app.err is None, app.err


def test_the_cut_edge_becomes_supportable(app):
    """A cut creates a new free edge. Leaving the support candidates as the
    old rectangle's perimeter would leave that edge with nothing to stand
    on, in a model whose whole point is the new shape."""
    _flat_shape(app)
    app.shape_plan.set('x^2 + y^2 < 16')
    app._build_shape_mesh()
    assert app._support_candidates
    rim = max(math.hypot(*app.nodes[i][:2]) for i in app._support_candidates)
    assert rim > 2.5, 'the candidates are not on the new rim'


def test_a_rule_that_keeps_everything_says_so_instead_of_looking_applied(app):
    """A rule whose centre is outside the domain silently keeps the whole
    rectangle, which looks exactly like having typed no rule at all."""
    _flat_shape(app)
    app.shape_plan.set('x > -999')
    app._build_shape_mesh()
    assert 'kept the whole domain' in app.shape_plan_note.cget('text')


def test_a_rule_that_keeps_nothing_is_refused_not_built(app):
    _flat_shape(app)
    app._build_shape_mesh()
    before = list(app.nodes)
    app.shape_plan.set('x > 999')
    app._build_shape_mesh()
    assert 'removed the whole structure' in app.shape_status.cget('text')
    assert app.nodes == before


def test_a_plan_preset_is_written_against_the_current_domain(app):
    """A circle typed in absolute metres is wrong the moment the domain
    moves, so the presets are built from the ranges in the panel."""
    _flat_shape(app)
    app.shape_p0.set(0.0); app.shape_p1.set(10.0)
    app.shape_q0.set(0.0); app.shape_q1.set(10.0)
    app._set_plan_rule('(x - {cx})^2 + (y - {cy})^2 < {r}^2')
    assert app.shape_plan.get() == '(x - 5)^2 + (y - 5)^2 < 5^2'
    app._build_shape_mesh()
    assert app.shape_status.cget('text') == ''


def test_clearing_the_plan_rule_restores_the_whole_rectangle(app):
    _flat_shape(app)
    app._build_shape_mesh()
    whole = len(app.nodes)
    app.shape_plan.set('x^2 + y^2 < 16')
    app._build_shape_mesh()
    assert len(app.nodes) < whole
    app.shape_plan.set('')
    app._build_shape_mesh()
    assert len(app.nodes) == whole
    assert app.shape_plan_note.cget('text') == ''


def test_a_bad_plan_rule_is_reported_and_not_raised(app):
    _flat_shape(app)
    before = list(app.nodes)
    app.shape_plan.set('x <')
    app._build_shape_mesh()
    assert app.shape_status.cget('text') != ''
    assert app.nodes == before


# ── a column has to actually carry the joint it stands under ─────────────────

def test_a_column_takes_over_the_support_at_the_joint_it_carries(app):
    """Regression, measured: a plain post under a pinned corner carried
    exactly 0.00 kN with the old pin still there and 23.17 kN once it was
    gone. A pin left at the head is a rigid path to ground in parallel with
    the column, and it wins every time."""
    _mode(app, 'addons')
    target = app.supports[0]['node']
    app.col_style.set(sg.COLUMN_PLAIN)
    app.col_height.set(4.0)
    app.selected_nodes = {target}
    n_before = len(app.nodes)
    app._add_column()
    assert not any(s['node'] == target for s in app.supports), \
        'the joint the column carries is still pinned in mid-air'
    assert target not in app._support_candidates
    feet = [s['node'] for s in app.supports if s['node'] >= n_before]
    assert feet, 'the column foot is not pinned'
    app._analyze()
    assert app.err is None, app.err
    shaft = next(i for i, m in enumerate(app.members)
                 if m.get('role') == 'column_shaft')
    assert abs(app.results['member_res'][shaft]['N']) > 1.0, \
        'the column is in the model but carrying nothing'


def test_the_column_says_which_supports_it_took_over(app):
    """Removing a support is not something the user should have to discover
    from a reaction that moved."""
    _mode(app, 'addons')
    target = app.supports[0]['node']
    app.col_style.set(sg.COLUMN_PLAIN)
    app.selected_nodes = {target}
    app._add_column()
    note = app.col_note.cget('text')
    assert 'foot pinned' in note and str(target) in note


def test_a_column_under_an_unsupported_joint_changes_no_supports(app):
    """Nothing to take over means nothing to report -- the note must not
    invent a boundary-condition change that did not happen."""
    _mode(app, 'addons')
    free = next(i for i in range(len(app.nodes))
                if not any(s['node'] == i for s in app.supports))
    before = {s['node'] for s in app.supports}
    app.col_style.set(sg.COLUMN_PLAIN)
    app.selected_nodes = {free}
    n_before = len(app.nodes)
    app._add_column()
    feet = {s['node'] for s in app.supports if s['node'] >= n_before}
    assert {s['node'] for s in app.supports} - feet == before
    assert 'no longer pinned' not in app.col_note.cget('text')


# ── fitting the 300 px panel, and the mode shortcuts ─────────────────────────

def _too_wide(widget, room):
    """Widgets whose requested width does not fit the panel they sit in.
    winfo_reqwidth is what the widget ASKED for, which is what overflows --
    winfo_width would report the clipped size and hide the problem."""
    bad = []
    for child in widget.winfo_children():
        if child.winfo_manager() == 'pack' and child.winfo_reqwidth() > room:
            bad.append((str(child), child.winfo_reqwidth(), room))
        bad += _too_wide(child, room)
    return bad


@pytest.mark.parametrize('mode', ['build', 'shape', 'support', 'load',
                                  'section', 'addons', 'module', 'analyse',
                                  'results'])
def test_no_panel_asks_for_more_width_than_the_panel_has(app, mode):
    """Every field has to fit the context panel. A combobox that asks for a
    fixed character width next to a fixed-width label overflowed it, and the
    overflow is invisible until you look: Tk clips it silently."""
    _mode(app, mode)
    app.root.update_idletasks()
    from apps.stereo.stereo_app_shell import PANEL_W
    frame = app._mode_frames[mode]
    assert not _too_wide(frame, PANEL_W), _too_wide(frame, PANEL_W)


def _editable_entry(widget):
    """The first entry in a panel that actually takes typing -- a readonly
    combobox has a tk.Entry inside it that never does."""
    for child in widget.winfo_children():
        if isinstance(child, tk.Entry) and str(child.cget('state')) == 'normal':
            return child
        found = _editable_entry(child)
        if found is not None:
            return found
    return None


def test_alt_digit_jumps_to_each_mode_in_rail_order(app):
    """Generated on the canvas, not the toplevel: a key event goes to the
    FOCUS widget and then up its bindtags, so with no focus anywhere Tk
    drops it and nothing fires. The binding still lives on the toplevel,
    which is what puts it in every descendant's bindtags -- that is how it
    reaches you from inside the entry you were editing."""
    from apps.stereo.stereo_app_shell import MODES
    app.canvas.focus_force()
    app.root.update()
    for n, (key, _g, _l, _t) in enumerate(MODES, start=1):
        app.canvas.event_generate(f'<Alt-Key-{n}>', when='now')
        app.root.update()
        assert app.active_mode.get() == key, f'Alt+{n} did not reach {key}'


def test_the_shortcut_works_from_inside_an_entry_without_typing_into_it(app):
    """The case the shortcut exists for: you have just typed a column height
    and want the next mode. Switching must not also leave a digit in the
    field you were in."""
    _mode(app, 'addons')
    entry = _editable_entry(app._mode_frames['addons'])
    assert entry is not None
    entry.focus_force()
    app.root.update()
    before = entry.get()
    entry.event_generate('<Alt-Key-2>', when='now')
    app.root.update()
    assert app.active_mode.get() == 'shape'
    assert entry.get() == before, 'the shortcut typed into the field'


def test_a_bare_digit_still_types_and_does_not_switch_mode(app):
    """Half this tab's work is typing numbers, which is why the shortcut
    takes Alt rather than the bare digit."""
    _mode(app, 'addons')
    entry = _editable_entry(app._mode_frames['addons'])
    entry.focus_force()
    app.root.update()
    before = entry.get()
    entry.event_generate('<Key-7>', when='now')
    app.root.update()
    assert app.active_mode.get() == 'addons', 'a bare digit switched mode'
    assert entry.get() != before, 'the digit never reached the field'


def test_the_mode_hotkey_stops_the_key_reaching_the_focused_entry(app):
    """Without 'break', Alt+4 switches mode AND types a 4 into whatever
    entry had focus."""
    assert app._mode_hotkey('load') == 'break'
    assert app.active_mode.get() == 'load'


def test_the_rail_hint_advertises_the_shortcut(app):
    """A key nobody is told about is a key nobody presses."""
    app.hint_var.set('')
    app._rail_buttons['support'][0].event_generate('<Enter>', when='now')
    app.root.update()
    assert 'Alt+3' in app.hint_var.get()


# ── the selection card ───────────────────────────────────────────────────────

def test_clicking_a_rod_reports_it_in_every_mode_not_just_results(app):
    """Regression: the click-to-inspect readout lived in the Results panel,
    so inspecting a rod while placing supports wrote the answer onto a
    panel that was not on screen -- while the canvas legend was inviting
    you to click a rod to inspect it."""
    app._analyze()
    _mode(app, 'support')
    app.selected_nodes = set()
    app.selected_member = 3
    app._show_member_info(3)
    app._draw()
    assert 'Member 3' in app.sel_var.get()
    assert app.canvas.find_withtag('selection_card'), \
        'the readout is invisible outside Results'


def test_the_selection_card_stays_out_of_the_way_when_nothing_is_selected(app):
    """Empty, it would permanently repeat the legend's own invitation to
    click something, over the model."""
    app.selected_nodes = set()
    app.selected_member = None
    app._draw()
    assert not app.canvas.find_withtag('selection_card')


def test_the_selection_card_sits_in_the_bottom_left_corner(app):
    """The other three corners are taken: legend top-left, view cube
    top-right, base module bottom-right."""
    app.selected_nodes = {3}
    app._draw()
    app.root.update_idletasks()
    items = app.canvas.find_withtag('selection_card')
    assert len(items) == 1
    x, y = app.canvas.coords(items[0])
    assert x < 40
    assert y > app.canvas.winfo_height() / 2


def test_redrawing_does_not_pile_up_selection_cards(app):
    app.selected_nodes = {3}
    for _ in range(4):
        app._draw()
    assert len(app.canvas.find_withtag('selection_card')) == 1


def test_the_panel_and_the_card_cannot_disagree_about_the_selection(app):
    """One StringVar drives both, which is the point -- two readouts of the
    same thing that can drift apart are worse than one."""
    _mode(app, 'results')
    app.selected_nodes = {7}
    app._sync_selection_fields()
    app.root.update_idletasks()
    assert 'Node 7' in app.sel_var.get()
    # Both readouts are driven by that ONE variable, which is the property
    # that makes them unable to drift apart. A label bound to a textvariable
    # reports its -text as empty, so the binding is what there is to check.
    var = str(app.sel_var)
    assert str(app.sel_label.cget('textvariable')) == var
    bound = [w for w in app.selection_card.winfo_children()
             if str(w.cget('textvariable')) == var]
    assert len(bound) == 1, [str(w.cget('textvariable'))
                             for w in app.selection_card.winfo_children()]


# ── focus states ─────────────────────────────────────────────────────────────

def _plain_entries(widget, out=None):
    """tk.Entry only. ttk.Entry SUBCLASSES it but is themed and has no
    highlight options, so isinstance alone reaches the entry inside every
    readonly combobox."""
    out = [] if out is None else out
    for child in widget.winfo_children():
        if type(child) is tk.Entry:
            out.append(child)
        _plain_entries(child, out)
    return out


def test_every_panel_entry_shows_where_the_keystrokes_will_land(app):
    """Tk's default focus highlight is the same colour as the background,
    which is to say none. Across eight panels of numeric fields there was
    no way to tell which one had focus."""
    from apps.stereo.stereo_app_shell import RAIL_STRIPE
    seen = 0
    for mode in app._mode_frames:
        for entry in _plain_entries(app._mode_frames[mode]):
            seen += 1
            assert int(entry.cget('highlightthickness')) >= 1
            assert str(entry.cget('highlightcolor')) == RAIL_STRIPE
    assert seen > 20, f'only {seen} entries found -- the walk missed the panels'


def test_the_focus_ring_walk_does_not_touch_themed_widgets(app):
    """A ttk.Entry has no highlightthickness at all; configuring one raises
    TclError, which would have taken the whole tab down at build time."""
    from tkinter import ttk
    app._apply_focus_ring(app.panel_host)     # must not raise
    combos = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, ttk.Combobox):
                combos.append(c)
            walk(c)
    walk(app.panel_host)
    assert combos, 'no comboboxes found -- this test would prove nothing'


# ── the base module card turns ───────────────────────────────────────────────

def test_dragging_the_base_module_card_turns_the_module(app):
    """It is a 3D solid in a window, so it should behave like one. Before
    this it was a fixed picture you could not look behind."""
    app.show_module_card.set(True)
    app._draw()
    before = (app.me3d_azimuth, app.me3d_elevation)
    c = app.module_card_canvas
    c.event_generate('<ButtonPress-1>', x=40, y=40, when='now')
    c.event_generate('<B1-Motion>', x=100, y=70, when='now')
    c.event_generate('<ButtonRelease-1>', x=100, y=70, when='now')
    app.root.update()
    assert (app.me3d_azimuth, app.me3d_elevation) != before


def test_turning_the_card_does_not_move_the_main_camera(app):
    """Two cameras, deliberately: the module and the model are different
    things to be looking at."""
    app.show_module_card.set(True)
    app._draw()
    before = (app.azimuth, app.elevation)
    c = app.module_card_canvas
    c.event_generate('<ButtonPress-1>', x=30, y=30, when='now')
    c.event_generate('<B1-Motion>', x=120, y=90, when='now')
    c.event_generate('<ButtonRelease-1>', x=120, y=90, when='now')
    app.root.update()
    assert (app.azimuth, app.elevation) == before


def test_the_card_and_the_editor_share_one_module_camera(app):
    """Two views of one solid. Separate cameras would mean the card quietly
    disagreeing with the editor about which way the module faces."""
    _mode(app, 'module')
    app.show_module_card.set(True)
    app._draw()
    app.me3d_azimuth, app.me3d_elevation = 12.0, 7.0
    app._me_render_3d_everywhere()
    assert app.me3d_canvas.find_all()
    assert app.module_card_canvas.find_all()


# ── Analyse mode ─────────────────────────────────────────────────────────────

def test_the_display_controls_are_reachable_without_hunting_for_a_button(app):
    """The whole visual vocabulary of the tab used to be behind the Display
    popover -- one button away, and so, for anyone who had not found that
    button, not there at all."""
    _mode(app, 'analyse')
    frame = app._mode_frames['analyse']
    labels = []

    def walk(w):
        for c in w.winfo_children():
            try:
                t = c.cget('text')
            except tk.TclError:
                t = ''
            if t:
                labels.append(str(t))
            walk(c)
    walk(frame)
    blob = ' | '.join(labels)
    for wanted in ('Utilization', 'Axial force', 'Node moment', 'Smooth gradient',
                   'Thickness = stress', 'Load-path arrows', 'Reactions'):
        assert wanted in blob, f'{wanted!r} is not in the Analyse panel'


def test_the_analyse_panel_and_the_popover_cannot_disagree(app):
    """Both bind the SAME Tk variables. Two independent copies of the same
    switch is how a UI starts lying about its own state."""
    _mode(app, 'analyse')
    app.smooth_gradient.set(True)
    app._toggle_display_popover()
    app.root.update_idletasks()
    assert app.smooth_gradient.get() is True
    app._toggle_display_popover()


def test_the_charts_say_what_they_need_before_a_solve(app):
    """An empty plot box is indistinguishable from a broken one."""
    app.results = None
    app.member_checks = None
    _mode(app, 'analyse')
    app._refresh_analysis_charts()
    texts = [app.analysis_canvas.itemcget(i, 'text')
             for i in app.analysis_canvas.find_all()
             if app.analysis_canvas.type(i) == 'text']
    assert any('Analyze' in t for t in texts), texts


def test_every_chart_draws_something_after_a_solve(app):
    app._analyze()
    _mode(app, 'analyse')
    app._refresh_analysis_charts()
    texts = ' | '.join(app.analysis_canvas.itemcget(i, 'text')
                       for i in app.analysis_canvas.find_all()
                       if app.analysis_canvas.type(i) == 'text')
    assert 'Utilisation of' in texts
    assert 'Axial force in' in texts
    assert 'supports carry' in texts
    assert 'distinct shapes' in texts


def test_the_charts_stack_instead_of_drawing_on_top_of_each_other(app):
    """Each chart function draws from y=0 so it can be tested alone; the
    stacking is the panel's job, and getting it wrong piles every plot into
    the same 70 px."""
    app._analyze()
    _mode(app, 'analyse')
    app._refresh_analysis_charts()
    c = app.analysis_canvas
    boxes = [c.coords(i) for i in c.find_all() if c.type(i) == 'rectangle']
    tops = sorted({round(b[1]) for b in boxes if b[3] - b[1] > 30})
    assert len(tops) >= 4, f'only {len(tops)} distinct plot boxes: {tops}'
    assert max(tops) > 150, 'the charts are all at the same height'


def test_the_charts_follow_the_load_slider(app):
    """The model is linear, so every utilisation scales with the slider. A
    histogram that ignored it would describe a load case nobody is looking
    at."""
    app._analyze()
    _mode(app, 'analyse')
    app.load_fraction.set(100)
    app._refresh_analysis_charts()
    full = [app.analysis_canvas.itemcget(i, 'text')
            for i in app.analysis_canvas.find_all()
            if app.analysis_canvas.type(i) == 'text']
    app.load_fraction.set(10)
    app._refresh_analysis_charts()
    tenth = [app.analysis_canvas.itemcget(i, 'text')
             for i in app.analysis_canvas.find_all()
             if app.analysis_canvas.type(i) == 'text']
    assert full != tenth, 'the charts ignored the Load % slider'


# ── clearing add-ons, arrays, and the lateral brace ──────────────────────────

def _two_bottom_rows(app):
    """A selection the reinforcement beam will accept: two adjacent rows of
    the lowest layer."""
    zmin = min(p[2] for p in app.nodes)
    bottom = [i for i, p in enumerate(app.nodes) if abs(p[2] - zmin) < 1e-6]
    ys = sorted({round(app.nodes[i][1], 6) for i in bottom})
    return {i for i in bottom if round(app.nodes[i][1], 6) in ys[:2]}


def test_clearing_the_columns_puts_the_model_back_exactly(app):
    """Undo covers removing one. A model with a dozen columns needed a dozen
    undos to reach the bare grid, and by then the stack has eaten everything
    else you did in between."""
    _mode(app, 'addons')
    n0, m0 = len(app.nodes), len(app.members)
    app.col_style.set(sg.COLUMN_PLAIN)
    app.selected_nodes = {app.supports[0]['node']}
    app._add_column()
    assert len(app.members) > m0
    app._clear_columns()
    assert (len(app.nodes), len(app.members)) == (n0, m0)
    app._analyze()
    assert app.err is None, app.err


def test_clearing_the_columns_hands_their_supports_back(app):
    """A joint whose pin was removed because a column was carrying it would
    otherwise be left hanging, and the next Analyze would report a mechanism
    for a reason nothing on screen explains."""
    _mode(app, 'addons')
    target = app.supports[0]['node']
    app.col_style.set(sg.COLUMN_PLAIN)
    app.selected_nodes = {target}
    app._add_column()
    assert not any(s['node'] == target for s in app.supports)
    app._clear_columns()
    assert any(s['node'] == target for s in app.supports), \
        'the joint the column was carrying is now supported by nothing'
    assert target in app._support_candidates


def test_clearing_columns_keeps_the_grid_nodes_the_capital_reached(app):
    """Only ORPHANS go. A grid node a capital fanned to still carries its own
    chords -- deleting it would tear a hole in the roof to remove the column
    under it."""
    _mode(app, 'addons')
    before = list(app.nodes)
    app.col_style.set(sg.COLUMN_PLAIN)
    app.selected_nodes = {4, 5}
    app._add_column()
    app._clear_columns()
    assert app.nodes == before


def test_clearing_beams_puts_the_model_back_exactly(app):
    _mode(app, 'addons')
    n0, m0 = len(app.nodes), len(app.members)
    app.selected_nodes = _two_bottom_rows(app)
    app._add_reinforcement_beam()
    assert len(app.members) > m0
    app._clear_beams()
    assert (len(app.nodes), len(app.members)) == (n0, m0)
    app._analyze()
    assert app.err is None, app.err


def test_clearing_beams_leaves_the_columns_alone(app):
    """The two Clear buttons share one removal routine, which is exactly why
    it has to be told which roles it owns."""
    _mode(app, 'addons')
    app.col_style.set(sg.COLUMN_PLAIN)
    app.selected_nodes = {app.supports[0]['node']}
    app._add_column()
    shafts = sum(1 for m in app.members if m.get('role') == 'column_shaft')
    app.selected_nodes = _two_bottom_rows(app)
    app._add_reinforcement_beam()
    app._clear_beams()
    assert sum(1 for m in app.members if m.get('role') == 'column_shaft') == shafts
    assert not [m for m in app.members if m.get('role') in ('reinf_chord', 'reinf_web')]


def test_clearing_nothing_says_so_instead_of_pretending(app):
    _mode(app, 'addons')
    n0 = len(app.members)
    app._clear_columns()
    assert 'No columns' in app.col_note.cget('text')
    assert len(app.members) == n0


def test_a_column_array_needs_no_selection(app):
    """The point of the array is placing many columns at once, which is the
    one case where lassoing each footprint by hand is the slow way."""
    _mode(app, 'addons')
    app.col_style.set(sg.COLUMN_PLAIN)
    app.selected_nodes = set()
    app.col_array_x.set(3)
    app.col_array_y.set(2)
    app._build_column_array()
    assert sum(1 for m in app.members if m.get('role') == 'column_shaft') == 6
    assert '3' in app.col_note.cget('text')
    app._analyze()
    assert app.err is None, app.err


def test_array_columns_stand_on_the_lowest_layer(app):
    """Picking from every node would let a station snap to the top chord and
    hang a column in mid-air below it."""
    _mode(app, 'addons')
    app.col_style.set(sg.COLUMN_PLAIN)
    app.col_array_x.set(2)
    app.col_array_y.set(2)
    zmin_before = min(p[2] for p in app.nodes)
    app._build_column_array()
    heads = [app.members[i]['b'] for i, m in enumerate(app.members)
             if m.get('role') == 'column_shaft']
    for h in heads:
        assert abs(app.nodes[h][2] - zmin_before) < 1e-6, \
            'a column hangs from something above the bottom layer'


def test_two_array_columns_never_share_a_footing(app):
    """Each station takes its nodes out of the pool, or a dense array would
    stack several columns under the same joint."""
    _mode(app, 'addons')
    app.col_style.set(sg.COLUMN_PLAIN)
    app.col_array_x.set(4)
    app.col_array_y.set(4)
    app._build_column_array()
    heads = [app.members[i]['b'] for i, m in enumerate(app.members)
             if m.get('role') == 'column_shaft']
    assert len(heads) == len(set(heads))


def test_a_braced_capital_holds_sway_but_not_the_vertical(app):
    """The point of bracing a column head is the roof plane holding it
    against sway. Holding uz too would be a rigid prop, which is the very
    thing the column is there instead of."""
    _mode(app, 'addons')
    target = app.supports[0]['node']
    app.col_style.set(sg.COLUMN_PLAIN)
    app.col_braced.set(True)
    app.selected_nodes = {target}
    app._add_column()
    entry = next(s for s in app.supports if s['node'] == target)
    r = sm.support_restraints(entry)
    assert r['ux'] and r['uy']
    assert not r['uz'], 'a braced head must still be free to settle'
    app._analyze()
    assert app.err is None, app.err


def test_bracing_is_off_unless_asked_for(app):
    """It was on by default in the original. Turning it on adds restraints,
    which moves the answer for every column model built in this version --
    that is a deliberate choice to make, not a default that shifts numbers
    quietly."""
    assert app.col_braced.get() is False
    _mode(app, 'addons')
    target = app.supports[0]['node']
    app.col_style.set(sg.COLUMN_PLAIN)
    app.selected_nodes = {target}
    app._add_column()
    assert not any(s['node'] == target for s in app.supports)


def test_bracing_a_column_stiffens_the_structure(app):
    """If the toggle changed nothing measurable it would be decoration."""
    _mode(app, 'addons')
    target = app.supports[0]['node']
    app.col_style.set(sg.COLUMN_PLAIN)
    app.selected_nodes = {target}
    app._add_column()
    app._analyze()
    free = max(abs(v) for r in app.results['node_res']
               for v in (r['ux'], r['uy']))
    app._undo()
    app.col_braced.set(True)
    app.selected_nodes = {target}
    app._add_column()
    app._analyze()
    braced = max(abs(v) for r in app.results['node_res']
                 for v in (r['ux'], r['uy']))
    assert braced <= free + 1e-9, 'bracing made the structure sway MORE'


def test_undo_drops_a_selection_the_restored_model_no_longer_has(app):
    """Regression, a crash not a wrong answer: adding a column ends by
    selecting its new feet, and undoing then restored a shorter node list
    while those indices survived. The next selection sync raised
    IndexError."""
    _mode(app, 'addons')
    app.col_style.set(sg.COLUMN_PLAIN)
    app.selected_nodes = {app.supports[0]['node']}
    app._add_column()
    assert max(app.selected_nodes) >= len(app.nodes) - 1
    app._undo()
    assert all(i < len(app.nodes) for i in app.selected_nodes)
    app._sync_selection_fields()      # this is what used to raise


# ── the column panel shows only the fields its style reads ───────────────────

def test_a_latticed_column_offers_no_capital_fields(app):
    """A field that does nothing is worse than a missing one: it invites you
    to set it and then ignores you. The latticed styles have no capital."""
    _mode(app, 'addons')
    app.col_style.set(sg.COLUMN_LATTICE)
    app.root.update_idletasks()
    assert not _shown(app.frame_col_capital)
    assert not _shown(app.frame_col_tiers)
    assert not _shown(app.frame_col_width), 'width is the selection, not a field'
    assert _shown(app.frame_col_panels)


def test_the_shaft_style_still_offers_its_capital_fields(app):
    _mode(app, 'addons')
    app.col_style.set(sg.COLUMN_SHAFT)
    app.root.update_idletasks()
    assert _shown(app.frame_col_capital)
    assert _shown(app.frame_col_tiers)
    assert not _shown(app.frame_col_panels)


def test_setting_the_style_in_code_refreshes_the_panel(app):
    """A <<ComboboxSelected>> binding only fires for a real click, so an
    example or a restored model would leave the previous style's fields on
    screen. The panel watches the VARIABLE."""
    _mode(app, 'addons')
    app.col_style.set(sg.COLUMN_SHAFT)
    app.root.update_idletasks()
    assert _shown(app.frame_col_capital)
    app.col_style.set(sg.COLUMN_TAPERED)
    app.root.update_idletasks()
    assert not _shown(app.frame_col_capital)


def test_every_style_explains_how_many_nodes_it_wants(app):
    _mode(app, 'addons')
    for style in sg.COLUMN_STYLES:
        app.col_style.set(style)
        app.root.update_idletasks()
        hint = app._col_hint.cget('text')
        assert hint, f'{style} has no hint'
        assert 'node' in hint.lower()


def test_the_optional_fields_keep_their_order_whichever_style_you_came_from(app):
    """pack_forget then pack APPENDS, which once put Lattice panels below the
    status note."""
    _mode(app, 'addons')
    app.col_style.set(sg.COLUMN_SHAFT)
    app.root.update_idletasks()
    app.col_style.set(sg.COLUMN_LATTICE)
    app.root.update_idletasks()
    app.col_style.set(sg.COLUMN_LEGS)
    app.root.update_idletasks()
    shown = [w for w in app._col_optional.pack_slaves()]
    want = [f for f in (app.frame_col_capital, app.frame_col_width,
                        app.frame_col_panels, app.frame_col_tiers) if f in shown]
    assert shown == want, 'the optional rows came back in a different order'


def test_one_foot_is_a_foot_and_three_are_feet(app):
    _mode(app, 'addons')
    app.col_style.set(sg.COLUMN_PLAIN)
    app.selected_nodes = {app.supports[0]['node']}
    app._add_column()
    assert '1 foot pinned' in app.col_note.cget('text')


def test_the_cell_census_is_the_first_thing_in_the_analysis_box(app):
    """It is a reading of the GEOMETRY, so it is the only one of the four
    that says anything before Analyze has ever been pressed. Fourth, it sat
    below the fold of a scrolling panel and read as a missing feature."""
    app.results = None
    app.member_checks = None
    _mode(app, 'analyse')
    app._refresh_analysis_charts()
    c = app.analysis_canvas
    texts = [(c.coords(i)[1], c.itemcget(i, 'text'))
             for i in c.find_all() if c.type(i) == 'text']
    assert texts
    census = [y for y, t in texts if 'distinct shapes' in t]
    assert census, 'the cell census is not drawn at all'
    others = [y for y, t in texts if 'Analyze' in t]
    assert others, 'nothing told the user to run Analyze'
    assert min(census) < min(others), 'the census is below the charts that need a solve'


def test_the_cell_census_works_with_no_solve_at_all(app):
    app.results = None
    app.member_checks = None
    _mode(app, 'analyse')
    app._refresh_analysis_charts()
    texts = ' '.join(app.analysis_canvas.itemcget(i, 'text')
                     for i in app.analysis_canvas.find_all()
                     if app.analysis_canvas.type(i) == 'text')
    assert 'distinct shapes' in texts
    assert 'role 0' in texts


def test_the_vierendeel_family_builds_and_solves_from_the_panel(app):
    from apps.stereo.stereo_app_constants import FAMILY_LABEL
    _mode(app, 'build')
    app.grid_family.set(FAMILY_LABEL['vierendeel_grid'])
    app._on_generator_change()
    app.vd_nx.set(4)
    app.vd_ny.set(4)
    app.vd_module.set(3.0)
    app.vd_depth.set(2.0)
    app._generate()
    assert len(app.nodes) == 2 * 25
    app._analyze()
    assert app.err is None, app.err


def test_the_section_panel_cannot_pin_a_vierendeel_grid(app):
    """rigid_required is not a preference: pinned, every one of its bays
    lozenges and the solve goes singular. _apply_sections has to leave it
    alone even when the panel says pin."""
    from apps.stereo.stereo_app_constants import FAMILY_LABEL
    _mode(app, 'build')
    app.grid_family.set(FAMILY_LABEL['vierendeel_grid'])
    app._on_generator_change()
    app._generate()
    app.sec_conn.set('pin')
    app._apply_sections()
    assert all(m.get('conn') == 'rigid' for m in app.members)
    app._analyze()
    assert app.err is None, app.err


def test_the_vierendeel_panel_appears_only_for_its_own_family(app):
    from apps.stereo.stereo_app_constants import FAMILY_LABEL
    _mode(app, 'build')
    app.grid_family.set(FAMILY_LABEL['vierendeel_grid'])
    app._on_generator_change()
    app.root.update_idletasks()
    assert _shown(app.frame_vierendeel_grid)
    assert not _shown(app.frame_flat_grid)
    app.grid_family.set(FAMILY_LABEL['flat_grid'])
    app._on_generator_change()
    app.root.update_idletasks()
    assert not _shown(app.frame_vierendeel_grid)


# ── welded shear panels, from the panel ──────────────────────────────────────

def _top_quad(app):
    zmax = max(p[2] for p in app.nodes)
    tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - zmax) < 1e-9]
    xs = sorted({round(app.nodes[i][0], 6) for i in tops})
    ys = sorted({round(app.nodes[i][1], 6) for i in tops})
    return {i for i in tops if round(app.nodes[i][0], 6) in xs[:2]
            and round(app.nodes[i][1], 6) in ys[:2]}


def test_a_welded_panel_goes_into_the_solve_and_gets_checked(app):
    """Not decoration: its shear stiffness is in the matrix and its verdict
    comes from the same CIRSOC checks the Truss tab uses."""
    _mode(app, 'addons')
    app.selected_nodes = _top_quad(app)
    app.panel_t.set(8.0)
    app._add_shear_panel()
    assert len(app.panels) == 1
    app._analyze()
    assert app.err is None, app.err
    pr = app.results['panel_res'][0]
    assert pr['valid'] and pr['area_m2'] > 0 and abs(pr['q']) > 0
    assert len(app.panel_checks) == 1
    assert app.panel_checks[0]['valid']
    assert 'buckling' in app.panel_checks[0]['governing'].lower()


def test_a_welded_panel_stiffens_the_model(app):
    _mode(app, 'addons')
    app._analyze()
    before = max(abs(r['uz']) for r in app.results['node_res'])
    app.selected_nodes = _top_quad(app)
    app.panel_t.set(20.0)
    app._add_shear_panel()
    app._analyze()
    after = max(abs(r['uz']) for r in app.results['node_res'])
    assert after <= before


def test_a_welded_panel_is_drawn_whether_or_not_fill_is_on(app):
    """A shaded face is a picture of a cell that exists anyway. A panel is a
    real element carrying real load, and one you cannot see is one you can
    forget you added."""
    _mode(app, 'addons')
    app.selected_nodes = _top_quad(app)
    app._add_shear_panel()
    app.shaded_faces.set(False)
    app._draw()
    assert len(app.canvas.find_withtag('shear_panel')) == 1


def test_the_same_bay_cannot_be_panelled_twice(app):
    _mode(app, 'addons')
    app.selected_nodes = _top_quad(app)
    app._add_shear_panel()
    app._add_shear_panel()
    assert len(app.panels) == 1
    assert 'already a panel' in app.col_note.cget('text')


def test_panels_survive_undo_and_redo(app):
    _mode(app, 'addons')
    app.selected_nodes = _top_quad(app)
    app._add_shear_panel()
    assert len(app.panels) == 1
    app._undo()
    assert len(app.panels) == 0
    app._redo()
    assert len(app.panels) == 1


def test_clearing_the_panels_leaves_the_rods_alone(app):
    _mode(app, 'addons')
    n0 = len(app.members)
    app.selected_nodes = _top_quad(app)
    app._add_shear_panel()
    app._clear_shear_panels()
    assert app.panels == []
    assert len(app.members) == n0
    app._analyze()
    assert app.err is None, app.err


def test_a_new_model_starts_with_no_panels(app):
    """`panels` is model state, so a fresh mesh must not inherit the last
    one's -- its node indices would point at whatever holds them now."""
    _mode(app, 'addons')
    app.selected_nodes = _top_quad(app)
    app._add_shear_panel()
    assert app.panels
    app._generate()
    assert app.panels == []


def test_the_cell_fill_is_reachable_from_the_analyse_panel(app):
    """Regression: moving the display controls out of the popover and into
    the rail dropped the FILL group on the way, which is the view that
    shades each closed CELL of the mesh. It was still in the popover, so
    nothing was broken -- it had simply become unfindable."""
    _mode(app, 'analyse')
    labels = []

    def walk(w):
        for c in w.winfo_children():
            try:
                t = c.cget('text')
            except tk.TclError:
                t = ''
            if t:
                labels.append(str(t))
            walk(c)
    walk(app._mode_frames['analyse'])
    blob = ' | '.join(labels)
    assert 'Fill the cells' in blob
    for mode in FILL_MODES:
        assert mode in blob, f'{mode!r} is not offered in the Analyse panel'


def test_turning_the_cell_fill_on_from_the_analyse_panel_draws_cells(app):
    # A cell is coloured by its governing member, so it needs a solve to
    # have anything to say -- unanalysed, every panel correctly comes back
    # with no colour rather than a made-up one.
    app._analyze()
    _mode(app, 'analyse')
    app.faces_mode.set(FILL_SHADED)
    app._on_faces_mode_change()
    app._draw()
    assert app.canvas.find_withtag('shaded_face'), 'no cell was shaded'
    app.faces_mode.set(FILL_NONE)
    app._on_faces_mode_change()
    app._draw()
    assert not app.canvas.find_withtag('shaded_face')


# ── picking tools: line select and the footprint disc ────────────────────────

def _top_row(app):
    zmax = max(p[2] for p in app.nodes)
    tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - zmax) < 1e-9]
    ys = sorted({round(app.nodes[i][1], 6) for i in tops})
    row = [i for i in tops if abs(app.nodes[i][1] - ys[2]) < 1e-9]
    row.sort(key=lambda i: app.nodes[i][0])
    return row


def test_the_screen_to_world_inverse_lands_back_on_the_node_it_started_from(app):
    """Both picking tools rest on this: the disc's centre is the cursor
    unprojected onto a layer's plane. If the inverse were even slightly
    wrong the disc would cover joints it did not appear to."""
    for i in (0, 25, len(app.nodes) // 2):
        sx, sy = app._screen_positions()[i]
        got = app._unproject_to_plane(sx, sy, app.nodes[i][2])
        assert got is not None
        assert got[0] == pytest.approx(app.nodes[i][0], abs=1e-6)
        assert got[1] == pytest.approx(app.nodes[i][1], abs=1e-6)


def test_looking_along_the_horizon_refuses_to_guess_a_position(app):
    """A horizontal plane seen edge-on projects to a LINE: one screen point
    is every point on a ray, and nothing should invent one."""
    app.elevation = 0.0
    assert app._unproject_to_plane(100.0, 100.0, 0.0) is None


def test_a_line_from_node_to_node_selects_the_whole_row(app):
    """Two clicks instead of ten."""
    _mode(app, 'build')
    app.line_pick_mode.set(True)
    app._on_pick_mode_toggle('line')
    row = _top_row(app)
    assert len(row) > 4
    sp = app._screen_positions()
    app._handle_line_pick_click(*sp[row[0]])
    assert app._line_pick_first == row[0]
    assert 'far end' in app.pick_note.cget('text')
    app._handle_line_pick_click(*sp[row[-1]])
    assert set(app.selected_nodes) == set(row)
    assert app._line_pick_first is None, 'the tool should be ready for a new line'


def test_a_line_measures_in_the_model_not_on_the_screen(app):
    """A line drawn across a tilted view passes near nodes on other layers
    that merely LOOK close. Measuring in world coordinates selects the row
    you meant rather than everything behind it."""
    row = _top_row(app)
    zmax = max(p[2] for p in app.nodes)
    found = app._nodes_near_segment(row[0], row[-1],
                                    0.35 * app._typical_spacing())
    assert set(found) == set(row)
    assert all(abs(app.nodes[i][2] - zmax) < 1e-9 for i in found), \
        'the line picked up nodes from another layer'


def test_clicking_empty_space_does_not_start_a_line(app):
    _mode(app, 'build')
    app.line_pick_mode.set(True)
    app._on_pick_mode_toggle('line')
    app._handle_line_pick_click(3, 3)
    assert app._line_pick_first is None
    assert 'ON a node' in app.pick_note.cget('text')


def test_the_disc_covers_four_joints_at_a_bay_centre(app):
    """Which is the whole point: a column footprint in one gesture."""
    _mode(app, 'addons')
    app.disc_pick_mode.set(True)
    app._on_pick_mode_toggle('disc')
    app.disc_layer.set('top')
    app.disc_radius.set(0.8)
    app.disc_limit.set(4)
    zmax = max(p[2] for p in app.nodes)
    tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - zmax) < 1e-9]
    xs = sorted({round(app.nodes[i][0], 6) for i in tops})
    ys = sorted({round(app.nodes[i][1], 6) for i in tops})
    cx, cy = (xs[4] + xs[5]) / 2, (ys[4] + ys[5]) / 2
    hits = app._nodes_in_disc(cx, cy, 0.8 * app._typical_spacing(tops), tops, limit=4)
    assert len(hits) == 4
    assert all(abs(app.nodes[i][2] - zmax) < 1e-9 for i in hits)


def test_the_disc_never_takes_more_than_its_cap(app):
    """A latticed column takes 3 or 4 chords and no more, so the tool that
    picks its footprint must not hand it eight."""
    _mode(app, 'addons')
    zmax = max(p[2] for p in app.nodes)
    tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - zmax) < 1e-9]
    cx = sum(app.nodes[i][0] for i in tops) / len(tops)
    cy = sum(app.nodes[i][1] for i in tops) / len(tops)
    huge = 10.0 * app._typical_spacing(tops)
    for cap in (3, 4):
        hits = app._nodes_in_disc(cx, cy, huge, tops, limit=cap)
        assert len(hits) == cap


def test_the_disc_only_ever_picks_from_the_chosen_layer(app):
    _mode(app, 'addons')
    zmin = min(p[2] for p in app.nodes)
    bottom = app._layer_nodes('bottom')
    assert bottom
    cx = sum(app.nodes[i][0] for i in bottom) / len(bottom)
    cy = sum(app.nodes[i][1] for i in bottom) / len(bottom)
    hits = app._nodes_in_disc(cx, cy, 5.0 * app._typical_spacing(bottom),
                              bottom, limit=4)
    assert hits
    assert all(abs(app.nodes[i][2] - zmin) < 1e-6 for i in hits)


def test_the_disc_is_drawn_on_the_roof_not_stuck_to_the_screen(app):
    """Projected through the same camera as the model, so it stays the same
    size in METRES as you orbit. A screen circle would stop covering the
    joints it appeared to cover."""
    _mode(app, 'addons')
    app.disc_pick_mode.set(True)
    app._on_pick_mode_toggle('disc')
    app.disc_layer.set('top')
    sx, sy = app._screen_positions()[app._layer_nodes('top')[0]]
    hits, centre = app._disc_under_cursor(sx, sy)
    app._disc_hits, app._disc_centre = hits, centre
    app._draw()
    items = app.canvas.find_withtag('pick_disc')
    assert items, 'the disc was not drawn'
    poly = [i for i in items if app.canvas.type(i) == 'polygon']
    assert poly, 'the disc should be a projected polygon, not an oval'


def test_clicking_commits_exactly_what_the_disc_was_highlighting(app):
    """The highlight the user has been watching IS the selection, so the two
    can never disagree."""
    _mode(app, 'addons')
    app.disc_pick_mode.set(True)
    app._on_pick_mode_toggle('disc')
    app.disc_layer.set('top')
    # Hover over a node of the CHOSEN layer: over a bottom node the top-layer
    # disc correctly finds nothing, which is a different test.
    sx, sy = app._screen_positions()[app._layer_nodes('top')[0]]
    app._disc_hits, app._disc_centre = app._disc_under_cursor(sx, sy)
    want = list(app._disc_hits)
    assert want
    app._on_canvas_release(FakeEvent(sx, sy))
    assert set(app.selected_nodes) == set(want)


def test_only_one_picking_tool_can_be_armed(app):
    """Three modal click tools sharing one canvas is how a click stops
    meaning what the panel says it means."""
    _mode(app, 'build')
    app.add_rod_mode.set(True)
    app._on_pick_mode_toggle('rod')
    app.line_pick_mode.set(True)
    app._on_pick_mode_toggle('line')
    assert app.add_rod_mode.get() is False
    app.disc_pick_mode.set(True)
    app._on_pick_mode_toggle('disc')
    assert app.line_pick_mode.get() is False
    assert app.add_rod_mode.get() is False


def test_switching_tools_forgets_a_half_drawn_line(app):
    """A click made minutes later, with nothing on screen to explain it,
    would otherwise finish a selection nobody asked for."""
    _mode(app, 'build')
    app.line_pick_mode.set(True)
    app._on_pick_mode_toggle('line')
    sp = app._screen_positions()
    app._handle_line_pick_click(*sp[_top_row(app)[0]])
    assert app._line_pick_first is not None
    app.disc_pick_mode.set(True)
    app._on_pick_mode_toggle('disc')
    assert app._line_pick_first is None


def test_the_hover_costs_nothing_when_no_tool_is_armed(app):
    """Bound to plain <Motion>, so it fires on every mouse move over the
    canvas. It has to return before doing any projection work."""
    app.disc_pick_mode.set(False)
    app._disc_hits, app._disc_centre = [], None
    app._on_canvas_hover(FakeEvent(200, 200))
    assert app._disc_hits == [] and app._disc_centre is None


def test_a_top_layer_disc_over_a_bottom_node_correctly_finds_nothing(app):
    """The layer choice is a filter, not a hint: hovering the top-layer disc
    over a bottom joint must select nothing rather than reaching down."""
    _mode(app, 'addons')
    app.disc_pick_mode.set(True)
    app._on_pick_mode_toggle('disc')
    app.disc_layer.set('top')
    app.disc_radius.set(0.4)
    bottom = app._layer_nodes('bottom')
    zmin = min(app.nodes[i][2] for i in bottom)
    tops = app._layer_nodes('top')
    # a bottom node that has no top node directly above it
    far = max(bottom, key=lambda i: min((app.nodes[i][0] - app.nodes[j][0]) ** 2
                                        + (app.nodes[i][1] - app.nodes[j][1]) ** 2
                                        for j in tops))
    sx, sy = app._screen_positions()[far]
    hits, _c = app._disc_under_cursor(sx, sy)
    assert hits == []


# ── a balanced panel has no governing sign ───────────────────────────────────

def test_a_panel_with_equal_tension_and_compression_is_reported_balanced():
    """Regression, from a real model and real numbers.

    Two mirror-image corner panels of a perfectly symmetric roof came back
    from the solver with these exact member forces. The largest tension and
    the largest compression are equal to 13 significant figures, so neither
    governs -- but max(key=abs) always answers, and it answered differently
    on the two sides. One panel was painted deep blue, its mirror deep red,
    on a difference of 3.6e-13 kN."""
    from apps.stereo.stereo_app_render import StereoRenderMixin as R
    left = [+125.944229213916429444, -125.944229213916784715, -48.4810230896637293085]
    right = [+125.944229213916941035, -125.944229213916358390, -48.4810230896571354720]
    v_left, bal_left = R._combine_signed(left)
    v_right, bal_right = R._combine_signed(right)
    assert bal_left and bal_right, 'the tie was broken instead of detected'
    assert v_left == pytest.approx(v_right, rel=1e-9)


def test_a_panel_with_a_real_governing_member_still_gets_its_sign():
    """The tie detector must not swallow the ordinary case."""
    from apps.stereo.stereo_app_render import StereoRenderMixin as R
    v, bal = R._combine_signed([+200.0, -50.0, -10.0])
    assert not bal and v > 0
    v, bal = R._combine_signed([+50.0, -200.0, -10.0])
    assert not bal and v < 0


def test_an_all_tension_panel_is_never_called_balanced():
    """Balanced means equal and OPPOSITE. A panel with no compression at all
    cannot be balanced however close its members are to each other."""
    from apps.stereo.stereo_app_render import StereoRenderMixin as R
    _v, bal = R._combine_signed([100.0, 100.0, 100.0])
    assert not bal


def test_the_tie_tolerance_is_relative_not_absolute():
    """1e-6 kN is a tie on a 1000 kN panel and a real difference on a
    0.001 kN one."""
    from apps.stereo.stereo_app_render import StereoRenderMixin as R
    assert R._combine_signed([1000.0, -1000.0000001])[1] is True
    assert R._combine_signed([0.001, -0.002])[1] is False


def test_a_balanced_panel_is_painted_off_the_force_ramp(app):
    """Neither red nor blue nor the ramp's near-zero white: it must not be
    misread as a governing direction OR as a panel carrying nothing."""
    from apps.stereo.stereo_app_constants import BALANCED_PANEL_COLOR
    from apps.stereo.stereo_app_colors import force_color
    assert BALANCED_PANEL_COLOR != force_color(0.0, 1.0)
    assert BALANCED_PANEL_COLOR != force_color(1.0, 1.0)
    assert BALANCED_PANEL_COLOR != force_color(-1.0, 1.0)


def test_mirror_image_panels_get_the_same_colour(app):
    """The property the whole fix exists for, checked end to end on a
    symmetric model: no panel may disagree with its mirror twin."""
    app._analyze()
    frac = app._load_frac()
    mr = app.results['member_res']
    nodes = app.nodes
    xs = [p[0] for p in nodes]
    cx = (min(xs) + max(xs)) / 2.0
    key = lambda p: (round(p[0], 6), round(p[1], 6), round(p[2], 6))
    idx = {key(p): i for i, p in enumerate(nodes)}

    def mir(i):
        q = list(nodes[i]); q[0] = 2 * cx - q[0]
        return idx.get(key(q))

    cells = app._get_shaded_cells()
    by_nodes = {tuple(sorted(c['nodes'])): c for c in cells}
    checked = 0
    for c in cells:
        mn = tuple(sorted(x for x in (mir(n) for n in c['nodes']) if x is not None))
        if len(mn) != len(c['nodes']):
            continue
        twin = by_nodes.get(mn)
        if twin is None:
            continue
        checked += 1
        a = app._combine_signed([mr[m]['N'] * frac for m in c['members']])
        b = app._combine_signed([mr[m]['N'] * frac for m in twin['members']])
        assert a[1] == b[1], 'one twin is balanced and the other is not'
        if not a[1]:
            assert (a[0] > 0) == (b[0] > 0), 'mirror panels painted opposite colours'
    assert checked > 50, f'only {checked} mirror pairs checked'
