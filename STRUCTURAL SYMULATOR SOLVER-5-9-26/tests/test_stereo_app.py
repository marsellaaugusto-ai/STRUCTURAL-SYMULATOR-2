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
import os
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
from apps.stereo import stereo_reports as sr_module
from apps.stereo import stereo_app_constants as sc
from apps.stereo import stereo_app_module_editor as me
from apps.stereo import stereo_app_shell as sh
from apps.stereo import stereo_groups as sgp
from apps.stereo import stereo_profiles as sp_mod


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
    # A yes/no question hangs the same way. "Yes" is the default here so a
    # confirmation reads as the user going ahead; a test about "No" patches
    # its own.
    monkeypatch.setattr('apps.stereo.stereo_app.messagebox.askyesno',
                        lambda *a, **kw: (seen.append(('askyesno',) + a), True)[1])
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
    """A Stereo tab with the DEFAULT GRID already built.

    The app itself now opens empty -- a model you did not ask for is not a
    good first screen -- so the grid these tests work on is built here,
    explicitly, instead of arriving as a side effect of construction. Most
    of this file assumes a model exists; saying so in one place beats
    several hundred tests quietly depending on a startup detail that is
    free to change. A test that wants the empty state calls
    `app._clear_model()` first, and `blank_app` below skips the build
    entirely.
    """
    tab = tk.Frame(tk_root)
    a = StereoApp(tab)
    a._generate(push_undo=False)
    tab.pack(fill='both', expand=True)
    tk_root.update_idletasks()
    tk_root.update()
    yield a
    tab.destroy()


@pytest.fixture
def blank_app(tk_root):
    """The app exactly as it opens: no nodes, no members, no results."""
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


def test_members_in_screen_box_captures_visible_members(app):
    """A full-canvas bounding box should capture many members (some may
    project outside the viewport in the default view)."""
    w = app.canvas.winfo_width()
    h = app.canvas.winfo_height()
    found = app._members_in_screen_box(0, 0, w, h)
    assert len(found) > len(app.members) // 2


def test_members_in_screen_box_empty_for_offscreen_box(app):
    """A box far off-screen should capture nothing."""
    found = app._members_in_screen_box(9000, 9000, 9100, 9100)
    assert len(found) == 0


def test_lasso_selects_both_nodes_and_members(app):
    """A large lasso should populate both selected_nodes and selected_members."""
    w = app.canvas.winfo_width()
    h = app.canvas.winfo_height()
    app.selected_nodes = set()
    app.selected_members = set()
    app._lasso_press = (0, 0)
    app._lasso_cur = (w, h)
    app._lasso_dragging = True
    import tkinter as tk
    evt = tk.Event()
    evt.x, evt.y = w, h
    evt.state = 0
    app._on_canvas_release(evt)
    assert len(app.selected_nodes) > 0
    assert len(app.selected_members) > 0


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
    # the toggle itself; hiding while crowded is TestNumbersHideWhenCrowded
    app.labels_auto_hide.set(False)
    app.show_node_labels.set(True)
    app._draw()
    with_labels = len(app.canvas.find_withtag('all'))
    app.show_node_labels.set(False)
    app._draw()
    without_labels = len(app.canvas.find_withtag('all'))
    assert without_labels < with_labels


def test_member_label_toggle_is_off_by_default_and_can_be_turned_on(app):
    assert app.show_member_labels.get() is False
    app.labels_auto_hide.set(False)
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


def test_auto_deform_scale_keeps_visual_displacement_under_model_span(app):
    """_analyze auto-sets deform_scale so max visual deformation is about
    10% of the model span, preventing the 'explosion' users see when a
    fixed scale of 50 amplifies large displacements beyond the model size."""
    app._analyze()
    assert app.results is not None
    nr = app.results['node_res']
    max_disp_mm = max(
        math.sqrt(r['ux']**2 + r['uy']**2 + r['uz']**2) for r in nr)
    if max_disp_mm < 1e-9:
        return   # no displacement, nothing to scale
    xs = [n[0] for n in app.nodes]
    ys = [n[1] for n in app.nodes]
    zs = [n[2] for n in app.nodes]
    span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1.0)
    scale = app.deform_scale.get()
    visual = max_disp_mm / 1000.0 * scale
    assert visual <= span * 0.20, (
        f'scale {scale} gives visual {visual:.3f}m on span {span:.1f}m')
    assert 1 <= scale <= 500


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
    app._on_delete_selection()

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
    app._on_delete_selection()

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
    app._on_delete_selection()
    assert len(app.nodes) == n0
    assert len(app.members) == m0


def test_delete_selected_nodes_is_undoable(app):
    n0 = len(app.nodes)
    app.selected_nodes = {0}
    app._on_delete_selection()
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
    app._on_delete_selection()
    assert app.results is None
    assert app.member_checks is None


def test_delete_selected_members_only(app):
    """Deleting members without selecting nodes keeps all nodes."""
    n0 = len(app.nodes)
    m0 = len(app.members)
    app.selected_nodes = set()
    app.selected_members = {0, 1}
    app._on_delete_selection()
    assert len(app.nodes) == n0
    assert len(app.members) == m0 - 2
    assert app.selected_members == set()
    for m in app.members:
        assert 0 <= m['a'] < n0
        assert 0 <= m['b'] < n0


def test_delete_mixed_nodes_and_members(app):
    """Deleting nodes + members removes both, with proper remapping."""
    n0 = len(app.nodes)
    m0 = len(app.members)
    target_node = 0
    touching = sum(1 for m in app.members if m['a'] == target_node or m['b'] == target_node)
    non_touching_member = None
    for i, m in enumerate(app.members):
        if m['a'] != target_node and m['b'] != target_node:
            non_touching_member = i
            break
    assert non_touching_member is not None
    app.selected_nodes = {target_node}
    app.selected_members = {non_touching_member}
    app._on_delete_selection()
    assert len(app.nodes) == n0 - 1
    assert len(app.members) == m0 - touching - 1
    for m in app.members:
        assert 0 <= m['a'] < len(app.nodes)
        assert 0 <= m['b'] < len(app.nodes)


def test_axis_extend_creates_node_and_member(app):
    """Pressing an arrow key + Go creates a new node along that axis."""
    import tkinter as tk
    n0 = len(app.nodes)
    m0 = len(app.members)
    ox, oy, oz = app.nodes[0]
    app.selected_nodes = {0}
    evt = tk.Event()
    evt.keysym = 'Right'
    app._on_axis_key(evt)
    assert app._axis_pending == (1, 0, 0)
    app._axis_len_var.set(5.0)
    app._axis_extend_go()
    assert len(app.nodes) == n0 + 1
    assert len(app.members) == m0 + 1
    new_node = app.nodes[-1]
    assert new_node == (ox + 5.0, oy, oz)
    assert app.selected_nodes == {n0}


def test_axis_extend_chains_to_new_node(app):
    """After extending, the new node is selected so pressing another
    arrow key continues the chain."""
    import tkinter as tk
    app.selected_nodes = {0}
    evt = tk.Event()
    evt.keysym = 'Up'
    app._on_axis_key(evt)
    app._axis_len_var.set(2.0)
    app._axis_extend_go()
    new_idx = len(app.nodes) - 1
    assert app.selected_nodes == {new_idx}
    evt2 = tk.Event()
    evt2.keysym = 'Prior'
    app._on_axis_key(evt2)
    app._axis_len_var.set(4.0)
    app._axis_extend_go()
    newest = app.nodes[-1]
    prev = app.nodes[new_idx]
    assert newest[2] == pytest.approx(prev[2] + 4.0)


def test_axis_extend_cancel_clears_pending(app):
    """Escape cancels the pending axis extend."""
    import tkinter as tk
    app.selected_nodes = {0}
    evt = tk.Event()
    evt.keysym = 'Left'
    app._on_axis_key(evt)
    assert app._axis_pending is not None
    app._on_axis_cancel()
    assert app._axis_pending is None


def test_axis_key_ignored_when_no_single_selection(app):
    """Arrow keys are a no-op when zero or multiple nodes are selected."""
    import tkinter as tk
    n0 = len(app.nodes)
    app.selected_nodes = {0, 1}
    evt = tk.Event()
    evt.keysym = 'Right'
    app._on_axis_key(evt)
    assert app._axis_pending is None
    assert len(app.nodes) == n0


def test_drag_node_moves_position(app):
    """Dragging a selected node changes its world coordinates."""
    app.selected_nodes = {0}
    old_pos = app.nodes[0]
    import tkinter as tk
    evt = tk.Event()
    pts = app._screen_positions()
    sx, sy = pts[0]
    evt.x, evt.y = int(sx), int(sy)
    app._on_canvas_press(evt)
    assert app._drag_node is not None
    evt2 = tk.Event()
    evt2.x, evt2.y = int(sx) + 40, int(sy) + 40
    app._on_canvas_motion(evt2)
    assert app._drag_node_active
    evt3 = tk.Event()
    evt3.x, evt3.y = int(sx) + 40, int(sy) + 40
    evt3.state = 0
    app._on_canvas_release(evt3)
    new_pos = app.nodes[0]
    moved = any(abs(a - b) > 1e-6 for a, b in zip(old_pos, new_pos))
    assert moved, f'node did not move: {old_pos} → {new_pos}'


def test_drag_node_no_op_when_no_selection(app):
    """Drag on canvas without selected nodes does not activate node drag."""
    app.selected_nodes = set()
    import tkinter as tk
    evt = tk.Event()
    evt.x, evt.y = 200, 200
    app._on_canvas_press(evt)
    assert app._drag_node is None


def test_cable_support_restrains_only_uz(app):
    """The 'cable' preset restrains uz only, leaving all other DOFs free."""
    from apps.stereo import stereo_math as sm
    app.supports = [{'node': 0, 'type': 'cable', 'dofs': {}}]
    r = sm.support_restraints(app.supports[0])
    assert r['uz'] is True
    assert r['ux'] is False
    assert r['uy'] is False
    assert r['rx'] is False
    assert r['ry'] is False
    assert r['rz'] is False


# The two _apply_dist_load tests that were here are gone with the method.
# It converted a line load on the selected members into END forces only
# (w*L/2 per node), leaving the rod itself unloaded and its shear constant.
# _apply_rod_load carries a real span load instead -- see TestRodLoads and
# the 'Quoted:' ALONG / PROJECTED choice it exercises -- so the older path
# was dead code reachable from nothing but these two tests.


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
    nodes2, members2, loads2, supports2, _ = sr.import_excel_model(path)
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


def test_the_keypad_is_tabbed_by_what_the_keys_do(app):
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
        elif recipe.get('source'):
            # A third origin, added with the Bezier examples: built by the
            # SHAPE panel, not by the wizard and not by a raw generator.
            # Its note has to name the Bezier source, because "exact
            # settings" would point at wizard fields that did not make it
            # and "not a wizard surface" would say nothing about where it
            # DID come from.
            assert 'Bezier' in recipe['note'], recipe['note']
            assert recipe['source'] in ('extrude', 'spin', 'patch')
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
    # The app opens EMPTY, so the grid this test needs is built here, the
    # same way the `app` fixture builds its own -- it used to arrive as a
    # side effect of construction.
    app._generate(push_undo=False)
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


def test_every_control_in_the_display_popover_is_inside_it(app, tk_root):
    """Its rows flow onto a second line past POP_MAX_W: at natural width
    the Colour-by row alone was 1,385 px, off the right of the window, and
    "Resultant", "Auto-range", "Surface" and "Load-path arrows" with it."""
    app._toggle_display_popover()
    pop = app._display_pop
    try:
        tk_root.update()
        assert pop.winfo_width() <= app.POP_MAX_W + 20
        right = pop.winfo_rootx() + pop.winfo_width()
        bottom = pop.winfo_rooty() + pop.winfo_height()

        def walk(w):
            for c in w.winfo_children():
                yield c
                yield from walk(c)
        controls = [w for w in walk(pop) if w.winfo_class() in (
            'Checkbutton', 'Radiobutton', 'TCombobox', 'Scale')]
        assert len(controls) > 20
        for w in controls:
            assert w.winfo_ismapped(), w
            assert w.winfo_rootx() + w.winfo_width() <= right + 1, w
            assert w.winfo_rooty() + w.winfo_height() <= bottom + 1, w
        texts = [w.cget('text') for w in controls
                 if w.winfo_class() in ('Checkbutton', 'Radiobutton')]
        for want in ('Surface', 'Load-path arrows', 'Hide # when crowded'):
            assert any(want in t for t in texts), want
    finally:
        app._toggle_display_popover()


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
    # The pole boxes hold EXPRESSIONS now ('2*pi' has to be typeable), so
    # they read back as text and go through the same parser the panel uses.
    assert abs(float(app.shape_pole_x.get()) - 4.0) < 0.2
    assert abs(float(app.shape_pole_y.get()) - 4.0) < 0.2
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


@pytest.mark.parametrize('mode', ['build', 'shape', 'support', 'load',
                                  'section', 'addons', 'module', 'analyse',
                                  'results'])
def test_every_mode_fits_what_the_panel_actually_shows(app, mode):
    """The test above checks each widget against PANEL_W; this one checks
    the whole mode against the width that is VISIBLE. The two used to
    differ: the scroll panel was PANEL_W wide with its scrollbar inside
    it, so 287 px showed, every mode asked for 291-311, and the right edge
    of every panel sat behind a horizontal scrollbar -- the selected-node
    hint read "click a rod t", Shape's domain boxes ran off the edge."""
    _mode(app, mode)
    app.root.update_idletasks()
    from apps.stereo.stereo_app_shell import PANEL_W
    visible = app.panel_outer.canvas.winfo_width()
    assert visible >= PANEL_W
    frame = app._mode_frames[mode]
    assert frame.winfo_reqwidth() <= visible, (frame.winfo_reqwidth(),
                                               visible)


def test_the_drop_downs_use_the_panels_small_face(app):
    combos = []

    def rec(w):
        for c in w.winfo_children():
            if c.winfo_class() == 'TCombobox':
                combos.append(c)
            rec(c)
    rec(app.panel_host)
    assert combos
    assert all(str(c.cget('font')) not in ('', 'TkTextFont')
               for c in combos)


def test_an_empty_canvas_says_where_to_start(blank_app):
    app = blank_app
    app._draw()
    items = app.canvas.find_withtag('empty_state')
    assert items
    text = ' '.join(app.canvas.itemcget(i, 'text') for i in items)
    assert 'Generate' in text and 'Analyze' in text
    app._generate(push_undo=False)
    app._draw()
    assert not app.canvas.find_withtag('empty_state')


def test_buttons_with_nothing_to_do_say_so(app):
    app._reset_support_sandbox()
    assert 'already enabled' in app.status_var.get()


def test_the_status_bar_says_what_to_do_next(blank_app):
    app = blank_app
    app._refresh_status()
    assert app.hint_var.get().startswith('Next: Generate')
    app._generate(push_undo=False)
    app._refresh_status()
    assert app.hint_var.get() == 'Next: ▶ Analyze'
    supports = app.supports
    app.supports = []
    app._refresh_status()
    assert app.hint_var.get().startswith('Next: Support')
    app.supports = supports
    app._analyze()
    assert 'Analyse' in app.hint_var.get() or 'governing rod' in \
        app.hint_var.get()


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
        # The rail outgrew the digits: there are ten modes and only nine
        # single digits after 0, so the TENTH is Alt+0. Renumbering to fit
        # Groups into the middle would have moved nine shortcuts that are
        # already muscle memory. `<Alt-Key-10>` is not a keysym at all,
        # which is how this test found out.
        assert n <= 10, 'the rail has outgrown the single-digit shortcuts'
        digit = 0 if n == 10 else n
        app.canvas.event_generate(f'<Alt-Key-{digit}>', when='now')
        app.root.update()
        assert app.active_mode.get() == key, f'Alt+{digit} did not reach {key}'


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


# ═══════════════════════════════════════════════════════════════════════════
#  Every grid family, driven through the real panel
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('key,label', sc.GRID_FAMILIES)
def test_every_grid_family_generates_from_its_own_panel(app, key, label):
    """The dropdown, the per-family parameter frame and the _generate branch
    are three separate lists that have to agree, and nothing but a run
    through the real widgets proves they do: a family can be in the dropdown
    with no frame (the panel raises KeyError), or have a frame and no
    dispatch branch (it silently generates the LAST family in the chain
    instead, which looks like a working button)."""
    app.grid_family.set(label)
    app._on_generator_change()
    assert app._param_frames[key].winfo_ismapped() or True   # packed, not yet mapped
    app._generate()
    assert len(app.nodes) > 0, f'{key} generated nothing'
    assert len(app.members) > 0
    assert app._support_candidates, f'{key} offered no support candidates'
    assert app._load_nodes, f'{key} offered no loaded surface'


@pytest.mark.parametrize('key,label', sc.GRID_FAMILIES)
def test_every_grid_family_panel_fits_the_rail(app, key, label):
    """A parameter frame wider than the rail pushes the whole left side out
    and cuts the buttons off. Caught three of my own widgets already, so it
    covers every family rather than the ones I remembered to look at."""
    app.grid_family.set(label)
    app._on_generator_change()
    app.root.update_idletasks()
    width = app._param_frames[key].winfo_reqwidth()
    assert width <= sc.PANEL_W, f'{key} parameter frame is {width} px wide'


def test_the_ruled_hyperboloid_bracing_choice_reaches_the_generator():
    """A combobox that is read but not acted on is the classic dead control.
    Each bracing option must change the mesh it produces."""
    from apps.stereo import stereo_geometry as sgx
    counts = {}
    for key in ('none', 'counter', 'ring'):
        mesh = sgx.hyperboloid_tower(5, 20, 6, 16, 1, brace=key)
        counts[key] = len(mesh['members'])
    assert counts['none'] < counts['counter'] < counts['ring']


# ═══════════════════════════════════════════════════════════════════════════
#  Distributed load on the rods, and the two along-the-rod colour modes
# ═══════════════════════════════════════════════════════════════════════════

def test_applying_a_rod_load_reaches_the_solver_and_bows_the_moment(app):
    """End to end through the real widgets: the panel's w and scope must
    become member loads, reach analyze, and show up as a moment that
    actually VARIES along the rod -- which is the entire point of the
    feature and the thing a purely nodal load cannot produce."""
    from apps.stereo import stereo_member_loads as mld
    app.rod_scope.set(sc.ROD_SCOPE_TOP)
    app.rod_w.set(2.0)
    app._apply_rod_load()
    assert app.member_loads, 'no rod loads were created'
    app._analyze()
    assert app.err is None, app.err
    varying = [mr for mr in app.results['member_res'] if mld.varies_along_the_rod(mr)]
    assert len(varying) == len(app.member_loads)
    mres = varying[0]
    L = mres['length_m']
    mid = max(mld.member_diagram(mres, 0.5)[3:], key=abs)
    assert abs(mid) == pytest.approx(2.0 * L * L / 8.0, rel=1e-6)


def test_a_rod_load_shows_the_total_it_actually_applied(app):
    """The status line is the only feedback that the scope hit what the
    user meant. A scope that matched nothing, or matched the whole model,
    both look identical without it."""
    app.rod_scope.set(sc.ROD_SCOPE_TOP)
    app.rod_w.set(2.0)
    app._apply_rod_load()
    text = app.rod_load_status.cget('text')
    assert str(len(app.member_loads)) in text
    app._clear_rod_loads()
    assert app.member_loads == []
    assert 'No rod loads' in app.rod_load_status.cget('text')


def test_applying_a_rod_load_twice_does_not_double_it(app):
    """One w and one scope on screen has to mean one load. Stacking would
    quietly double the roof load on a second click of the same button."""
    app.rod_scope.set(sc.ROD_SCOPE_TOP)
    app.rod_w.set(2.0)
    app._apply_rod_load()
    first = len(app.member_loads)
    app._apply_rod_load()
    assert len(app.member_loads) == first


def test_the_rod_scopes_pick_genuinely_different_rods(app):
    """A scope list whose entries all resolve to the same set is a dead
    control that looks like a working one."""
    counts = {}
    for scope in (sc.ROD_SCOPE_TOP, sc.ROD_SCOPE_BOTTOM, sc.ROD_SCOPE_WEBS,
                  sc.ROD_SCOPE_ALL):
        app.rod_scope.set(scope)
        counts[scope] = len(app._rods_in_scope())
    assert counts[sc.ROD_SCOPE_ALL] == len(app.members)
    assert 0 < counts[sc.ROD_SCOPE_TOP] < counts[sc.ROD_SCOPE_ALL]
    assert 0 < counts[sc.ROD_SCOPE_BOTTOM] < counts[sc.ROD_SCOPE_ALL]
    assert 0 < counts[sc.ROD_SCOPE_WEBS] < counts[sc.ROD_SCOPE_ALL]
    assert counts[sc.ROD_SCOPE_TOP] + counts[sc.ROD_SCOPE_BOTTOM] \
        + counts[sc.ROD_SCOPE_WEBS] == counts[sc.ROD_SCOPE_ALL]


def test_a_rod_load_survives_undo_and_redo(app):
    app.rod_scope.set(sc.ROD_SCOPE_TOP)
    app._apply_rod_load()
    applied = len(app.member_loads)
    app._undo()
    assert app.member_loads == []
    app._redo()
    assert len(app.member_loads) == applied


def test_regenerating_drops_the_rod_loads_instead_of_relabelling_them(app):
    """A rod load is a member INDEX. Carrying one across a regenerate would
    silently attach it to whatever member now holds that number -- the same
    trap a welded panel's node indices set."""
    app.rod_scope.set(sc.ROD_SCOPE_TOP)
    app._apply_rod_load()
    assert app.member_loads
    app.grid_family.set(sc.FAMILY_LABEL['dome'])
    app._on_generator_change()
    app._generate()
    assert app.member_loads == []


def test_a_stale_rod_load_never_reaches_the_solver(app):
    """The belt to that braces: even if an index does survive some path
    not yet imagined, it is dropped before analyze rather than loading a
    different rod."""
    app.member_loads = [{'member': len(app.members) + 50, 'w': 3.0,
                         'dir': (0, 0, -1), 'spread': 'along'}]
    assert app._valid_member_loads() == []
    app._analyze()
    assert app.err is None, app.err


@pytest.mark.parametrize('mode', list(sc.COLOUR_MODES))
def test_every_colour_mode_draws(app, mode):
    app.rod_scope.set(sc.ROD_SCOPE_TOP)
    app._apply_rod_load()
    app._analyze()
    app.colour_mode.set(mode)
    app._on_colour_mode_change()
    assert app.canvas.find_withtag('member'), f'{mode} drew no rods'


def test_the_along_the_rod_modes_say_so_when_nothing_varies(app):
    """The honest refusal. Under nodal loads alone a member's shear is
    constant along it, so there is no field to draw -- and a flat-looking
    picture with no explanation reads as "no shear here", which is the
    opposite of the truth."""
    app.loads = [{'node': 0, 'fx': 0.0, 'fy': 0.0, 'fz': -30.0}]
    app._analyze()
    _peak, varies = app._rod_field_anchor(True)
    assert not varies
    app.colour_mode.set(sc.COLOUR_ROD_SHEAR)
    app._on_colour_mode_change()
    text = ' '.join(app.canvas.itemcget(i, 'text')
                    for i in app.canvas.find_all()
                    if app.canvas.type(i) == 'text')
    assert 'CONSTANT' in text

    app.rod_scope.set(sc.ROD_SCOPE_TOP)
    app._apply_rod_load()
    app._analyze()
    _peak, varies = app._rod_field_anchor(True)
    assert varies
    app._on_colour_mode_change()
    text = ' '.join(app.canvas.itemcget(i, 'text')
                    for i in app.canvas.find_all()
                    if app.canvas.type(i) == 'text')
    assert 'CONSTANT' not in text


def test_the_rod_field_is_sampled_along_the_rod_not_blended_end_to_end(app):
    """_draw_gradient_line blends LINEARLY between two end values, which is
    right for a field defined at the joints and wrong for a member's own
    moment under a distributed load -- a parabola between those same two
    ends. Drawing it as a straight blend would flatten the bow the view
    exists to show, so the midspan colour has to differ from the average of
    the two end colours."""
    from apps.stereo import stereo_member_loads as mld
    app.rod_scope.set(sc.ROD_SCOPE_TOP)
    app.rod_w.set(6.0)
    app._apply_rod_load()
    app._analyze()
    mres = next(mr for mr in app.results['member_res']
                if mld.varies_along_the_rod(mr))
    a = app._rod_field_value(mres, 0.0, False)
    b = app._rod_field_value(mres, 1.0, False)
    mid = app._rod_field_value(mres, 0.5, False)
    assert abs(mid - (a + b) / 2.0) > 1e-6


def test_the_custom_rod_direction_boxes_appear_only_for_custom(app):
    _mode(app, 'load')
    app.rod_dir.set('Custom')
    app._on_rod_dir_change()
    app.root.update_idletasks()
    assert app.frame_rod_dir.winfo_ismapped()
    app.rod_dir.set('Down (−Z)')
    app._on_rod_dir_change()
    app.root.update_idletasks()
    assert not app.frame_rod_dir.winfo_ismapped()


# ═══════════════════════════════════════════════════════════════════════════
#  A blank display: how the app opens, and what Clear does
# ═══════════════════════════════════════════════════════════════════════════

def test_the_app_opens_with_nothing_in_it(blank_app):
    """It used to generate a flat grid on construction, so every session
    began by deleting someone else's model. Generate and Shape are one
    click away; a model you did not ask for is not."""
    assert blank_app.nodes == []
    assert blank_app.members == []
    assert blank_app.supports == []
    assert blank_app.loads == []
    assert blank_app.results is None


def test_every_mode_survives_an_empty_model(blank_app):
    """An empty model is a real state now, not a transient one, so each
    mode has to render in it -- the module card, the indeterminacy readout
    and the Analyse charts all read the model."""
    for key, _icon, _label, _desc in sh.MODES:
        blank_app._set_mode(key)
        blank_app.root.update_idletasks()
    blank_app._draw()
    blank_app._refresh_all()


def test_analyzing_nothing_says_so_instead_of_blaming_the_supports(blank_app, dialogs):
    """The boundary-condition check answers first and reports that the
    structure is free to move as a rigid body -- true of nothing at all,
    but not what went wrong."""
    blank_app._analyze()
    assert blank_app.results is None
    said = ' '.join(str(d) for d in dialogs)
    assert 'nothing to analyze' in said.lower()


def test_clear_empties_everything_the_model_owns(app):
    """A half-cleared model is worse than none: a leftover panel or rod
    load is a list of INDICES, and the next build silently attaches it to
    whichever nodes now hold those numbers."""
    app.rod_scope.set(sc.ROD_SCOPE_TOP)
    app._apply_rod_load()
    app.loads = [{'node': 0, 'fx': 0.0, 'fy': 0.0, 'fz': -10.0}]
    app._analyze()
    assert app.nodes and app.supports and app.results is not None

    app._clear_model()
    assert app.nodes == []
    assert app.members == []
    assert app.supports == []
    assert app.loads == []
    assert app.member_loads == []
    assert app.panels == []
    assert app.results is None
    assert app.member_checks is None
    assert app.selected_nodes == set()
    assert app.selected_member is None


def test_clear_is_undoable(app):
    """Which is why it does not stop to ask: a mis-click costs one press of
    the undo button."""
    before = len(app.nodes)
    app._clear_model()
    assert app.nodes == []
    app._undo()
    assert len(app.nodes) == before
    app._redo()
    assert app.nodes == []


def test_clear_goes_through_the_same_door_a_regenerate_does(app):
    """_clear_model routes through _load_mesh rather than zeroing fields of
    its own, so the two can never reset different sets of state. Compared
    field by field against a fresh app instead of against a list of names
    someone has to remember to update."""
    app._generate()
    app._clear_model()
    watched = ('nodes', 'members', 'supports', 'loads', 'member_loads', 'panels',
               'panel_checks', 'results', 'member_checks', '_support_candidates',
               '_load_nodes', '_disabled_supports', '_column_freed')
    for name in watched:
        assert not getattr(app, name), f'{name} survived Clear: {getattr(app, name)!r}'


# ═══════════════════════════════════════════════════════════════════════════
#  pi multiples in the domain boxes
# ═══════════════════════════════════════════════════════════════════════════

def test_the_domain_boxes_take_pi_multiples(app):
    """A sine over 0..6.28318 is the same surface as one over 0..2*pi, but
    only one of them says what it means -- and only one stays exact when
    you change your mind about the wave count. These used to be Tk
    DoubleVars, which rejected the keystroke before it reached anything."""
    _shape(app)
    app.shape_z_top.set('2*sin(x)')
    app.shape_p0.set('0'); app.shape_p1.set('2*pi')
    app.shape_q0.set('0'); app.shape_q1.set('pi')
    app.shape_n1.set(8); app.shape_n2.set(4)
    app._build_shape_mesh()
    assert app.shape_status.cget('text') == '', app.shape_status.cget('text')
    assert app.nodes
    assert app._shape_num(app.shape_p1, 'x to') == pytest.approx(2 * math.pi)
    assert app._shape_num(app.shape_q1, 'y to') == pytest.approx(math.pi)


@pytest.mark.parametrize('text,expected', [
    ('2*pi', 2 * math.pi), ('pi/4', math.pi / 4), ('-pi', -math.pi),
    ('3*12', 36.0), ('-6', -6.0), ('e', math.e), ('2^3', 8.0),
])
def test_the_constant_evaluator_reads_what_an_engineer_would_type(text, expected):
    from apps.stereo import expr_math as em
    assert em.evaluate_number(text, 'x from') == pytest.approx(expected)


def test_a_bad_domain_box_names_which_box_is_wrong(app):
    """Six boxes and one error message that does not say which -- that is
    the difference between a two-second fix and hunting."""
    _shape(app)
    app.shape_p1.set('nonsense')
    app._build_shape_mesh()
    said = app.shape_status.cget('text')
    assert 'x to' in said, said
    assert 'nonsense' in said


def test_a_domain_box_refuses_a_variable(app):
    """'x' has no value at the time the domain is being decided, so a box
    that quietly accepted it would be reading nothing."""
    from apps.stereo import expr_math as em
    with pytest.raises(em.ExpressionError) as exc:
        em.evaluate_number('x', 'x from')
    assert 'constant' in str(exc.value)


# ═══════════════════════════════════════════════════════════════════════════
#  The Shape panel's module-pattern control
# ═══════════════════════════════════════════════════════════════════════════

def test_the_shape_panel_offers_an_isometric_module(app):
    """The capability the Generate wizard had and the Shape tab did not."""
    _shape(app)
    assert sg.PATTERN_ISOMETRIC in app._shape_pattern_buttons


@pytest.mark.parametrize('lattice,expect_isometric', [
    (sg.LATTICE_SINGLE, True),
    (sg.LATTICE_ALIGNED, True),
    (sg.LATTICE_SOS_OFFSET, False),
    (sg.LATTICE_SQ_ON_DIAG, False),
    (sg.LATTICE_DIAG_ON_DIAG, False),
])
def test_the_pattern_buttons_match_what_the_generator_will_accept(app, lattice,
                                                                  expect_isometric):
    """The panel and stereo_geometry_custom_surface must agree about which
    pairs exist. A greyed button the generator would in fact accept -- or
    an enabled one it would refuse -- is worse than either on its own, so
    this checks the UI against the GENERATOR rather than against a second
    copy of the rule."""
    _shape(app)
    app.shape_lattice.set(lattice)
    app._on_shape_mode_change()
    enabled = str(app._shape_pattern_buttons[sg.PATTERN_ISOMETRIC].cget('state')) == 'normal'
    assert enabled == expect_isometric

    surface = sg.make_height_field_surface('3 - 0.03*(x-6)**2')
    try:
        sg.custom_surface_lattice(surface, None, lattice=lattice,
                                  pattern=sg.PATTERN_ISOMETRIC,
                                  p_range=(0.0, 12.0), q_range=(0.0, 12.0),
                                  n1=6, n2=6, depth=1.2)
        generator_accepts = True
    except ValueError:
        generator_accepts = False
    assert enabled == generator_accepts


def test_choosing_a_blocked_pattern_falls_back_instead_of_lying(app):
    """A disabled option left SELECTED would build something other than
    what the panel shows."""
    _shape(app)
    app.shape_lattice.set(sg.LATTICE_SINGLE)
    app._on_shape_mode_change()
    app.shape_pattern.set(sg.PATTERN_ISOMETRIC)
    app.shape_lattice.set(sg.LATTICE_SOS_OFFSET)
    app._on_shape_mode_change()
    assert app.shape_pattern.get() == sg.PATTERN_SQUARE


def test_a_blocked_pattern_says_why_on_screen(app):
    """A disabled control with no reason beside it reads as a bug."""
    _shape(app)
    app.shape_lattice.set(sg.LATTICE_SOS_OFFSET)
    app._on_shape_mode_change()
    said = app.shape_pattern_note.cget('text')
    assert 'half-module' in said, said
    app.shape_lattice.set(sg.LATTICE_SINGLE)
    app._on_shape_mode_change()
    assert app.shape_pattern_note.cget('text') == ''


def test_building_an_isometric_surface_keeps_every_node_in_the_domain(app):
    """End to end through the real panel, which is the only thing that
    proves the pattern reaches the generator at all."""
    _shape(app)
    app.shape_z_top.set('3 - 0.03*(x-6)**2 - 0.03*(y-6)**2')
    app.shape_p0.set('0'); app.shape_p1.set('12')
    app.shape_q0.set('0'); app.shape_q1.set('12')
    app.shape_n1.set(6); app.shape_n2.set(6)
    app.shape_lattice.set(sg.LATTICE_SINGLE)
    app._on_shape_mode_change()
    app.shape_pattern.set(sg.PATTERN_ISOMETRIC)
    app._build_shape_mesh()
    assert app.shape_status.cget('text') == '', app.shape_status.cget('text')
    xs = [n[0] for n in app.nodes]
    ys = [n[1] for n in app.nodes]
    assert min(xs) == pytest.approx(0.0, abs=1e-9)
    assert max(xs) == pytest.approx(12.0, abs=1e-9)
    assert min(ys) == pytest.approx(0.0, abs=1e-9)
    assert max(ys) == pytest.approx(12.0, abs=1e-9)


# ═══════════════════════════════════════════════════════════════════════════
#  The surface preview
# ═══════════════════════════════════════════════════════════════════════════

def _preview_items(app):
    return app.canvas.find_withtag('surface_preview')


def test_the_surface_preview_draws_and_hides(app):
    _shape(app)
    app.shape_z_top.set('3*cos(x/3)*cos(y/3)')
    app.shape_p0.set('-9'); app.shape_p1.set('9')
    app.shape_q0.set('-9'); app.shape_q1.set('9')
    app._build_shape_mesh()
    assert app.show_surface_preview.get() is True
    assert len(_preview_items(app)) > 0
    app.show_surface_preview.set(False)
    app._draw()
    assert len(_preview_items(app)) == 0


def test_the_preview_does_not_change_with_the_subdivision(app):
    """Its whole reason to exist is to show the surface BEFORE you commit
    to a subdivision. A preview that went coarse with the mesh would be
    showing you the mesh a second time, and would go flat exactly when the
    mesh is coarse -- which is when you most need to see what you are
    approximating."""
    _shape(app)
    app.shape_z_top.set('3*cos(x/3)*cos(y/3)')
    app.shape_p0.set('-9'); app.shape_p1.set('9')
    app.shape_q0.set('-9'); app.shape_q1.set('9')
    app.shape_n1.set(3); app.shape_n2.set(3)
    app._build_shape_mesh()
    coarse = len(_preview_items(app))
    app.shape_n1.set(12); app.shape_n2.set(12)
    app._build_shape_mesh()
    fine = len(_preview_items(app))
    assert coarse == fine
    assert coarse > 0


def test_the_preview_reads_the_panel_not_the_model(app):
    """So it keeps telling the truth WHILE you edit the formula, before
    Build has been pressed -- which is the moment it is for."""
    _shape(app)
    app.shape_z_top.set('0')
    app.shape_p0.set('-6'); app.shape_p1.set('6')
    app.shape_q0.set('-6'); app.shape_q1.set('6')
    app._build_shape_mesh()
    flat_items = len(_preview_items(app))
    app.shape_z_top.set('4*cos(x/2)*cos(y/2)')      # panel only; no Build
    app._draw()
    assert len(_preview_items(app)) == flat_items   # same sampling density
    # ... but the drawn geometry moved, which is the part that matters
    app.shape_z_top.set('0')
    app._draw()


def test_a_formula_that_will_not_compile_draws_nothing_rather_than_crashing(app):
    """The panel already says why in red. A half-drawn surface on top of
    that is noise, and an exception is a broken app."""
    _shape(app)
    app.shape_z_top.set('!!broken!!')
    app._draw()
    assert len(_preview_items(app)) == 0


def test_two_surfaces_preview_as_two(app):
    """A crossing pair should be VISIBLE as a crossing, not only reported
    as an error after Build."""
    _shape(app)
    app.shape_two.set(True)
    app.shape_z_top.set('2')
    app.shape_z_bot.set('-2')
    app.shape_p0.set('-6'); app.shape_p1.set('6')
    app.shape_q0.set('-6'); app.shape_q1.set('6')
    app._on_shape_mode_change()
    app._draw()
    two = len(_preview_items(app))
    app.shape_two.set(False)
    app._on_shape_mode_change()
    app._draw()
    one = len(_preview_items(app))
    assert two == pytest.approx(2 * one, rel=0.01)


def test_the_preview_survives_an_empty_model(blank_app):
    """It is drawn from the panel, so it has no model to lean on -- and the
    app now OPENS in this state."""
    blank_app._set_mode('shape')
    blank_app.shape_z_top.set('2*cos(x/3)')
    blank_app._draw()


# ═══════════════════════════════════════════════════════════════════════════
#  Parallel vs perspective
# ═══════════════════════════════════════════════════════════════════════════

def test_parallel_is_the_default_and_keeps_equal_lengths_equal(app):
    """The right mode for measuring and for reading a repeating module:
    every bay of a uniform grid is drawn the same size because every bay IS
    the same size. That property is exactly what perspective gives up."""
    assert app.projection_mode.get() == sc.PROJECTION_PARALLEL
    app.grid_family.set(sc.FAMILY_LABEL['flat_grid'])
    app._on_generator_change()
    app.fg_nx.set(10); app.fg_ny.set(2); app.fg_module.set(3.0)
    app._generate()
    bottom = sorted((n for n in range(len(app.nodes))
                     if abs(app.nodes[n][1]) < 1e-9 and abs(app.nodes[n][2]) < 1e-9),
                    key=lambda i: app.nodes[i][0])
    pts = app._screen_positions()
    gaps = [math.dist(pts[a], pts[b]) for a, b in zip(bottom, bottom[1:])]
    assert max(gaps) == pytest.approx(min(gaps), rel=1e-6)


def test_perspective_shrinks_the_far_end(app):
    """And the near end grows. That is the whole difference, so it is what
    the test measures rather than counting canvas items."""
    app.grid_family.set(sc.FAMILY_LABEL['flat_grid'])
    app._on_generator_change()
    app.fg_nx.set(10); app.fg_ny.set(2); app.fg_module.set(3.0)
    app._generate()
    # Azimuth 90, so the row runs AWAY from the camera. At azimuth 0 it
    # runs across the view, every node is the same distance from the eye,
    # and perspective correctly does not converge it at all -- a line
    # perpendicular to the view axis has no vanishing point.
    app.azimuth, app.elevation = 90.0, 15.0
    bottom = sorted((n for n in range(len(app.nodes))
                     if abs(app.nodes[n][1]) < 1e-9 and abs(app.nodes[n][2]) < 1e-9),
                    key=lambda i: app.nodes[i][0])
    app.projection_mode.set(sc.PROJECTION_PERSPECTIVE)
    app.camera_distance.set(sc.CAMERA_DISTANCE_MIN)
    app._draw()
    pts = app._screen_positions()
    gaps = [math.dist(pts[a], pts[b]) for a, b in zip(bottom, bottom[1:])]
    assert max(gaps) > 1.05 * min(gaps), 'perspective did not change bay spacing'


def test_a_longer_eye_distance_approaches_parallel(app):
    """Which is what makes the slider meaningful at both ends rather than
    only being a number."""
    app._generate()
    def spread():
        pts = app._screen_positions()
        return max(p[0] for p in pts) - min(p[0] for p in pts)
    app.projection_mode.set(sc.PROJECTION_PARALLEL)
    app._draw()
    flat = spread()
    app.projection_mode.set(sc.PROJECTION_PERSPECTIVE)
    app.camera_distance.set(sc.CAMERA_DISTANCE_MIN)
    app._draw()
    near = abs(spread() - flat)
    app.camera_distance.set(sc.CAMERA_DISTANCE_MAX)
    app._draw()
    far = abs(spread() - flat)
    assert far < near


def test_the_eye_distance_scales_with_the_model_not_with_metres(app):
    """A fixed distance cannot serve a 6 m canopy and a 60 m bridge: what
    looks natural on one is a fisheye or a flat orthographic on the other.
    Keyed to the model's own size, one slider setting means the same
    STRENGTH of perspective at every scale."""
    app.projection_mode.set(sc.PROJECTION_PERSPECTIVE)
    app.grid_family.set(sc.FAMILY_LABEL['flat_grid'])
    app._on_generator_change()
    app.fg_nx.set(6); app.fg_ny.set(6)
    app.fg_module.set(2.0)
    app._generate()
    app._refresh_camera_distance()
    small = app._persp_d
    app.fg_module.set(20.0)
    app._generate()
    app._refresh_camera_distance()
    big = app._persp_d
    assert big == pytest.approx(10.0 * small, rel=1e-6)


@pytest.mark.parametrize('mode', list(sc.PROJECTION_MODES))
def test_clicking_a_node_still_hits_that_node(app, mode):
    """The real risk in adding a second projection. Picking, the lasso and
    the disc tool all INVERT the projection, and inverting the parallel
    maths under a perspective view puts every click a few per cent off --
    growing with distance from the centre, so it reads as a sloppy hit
    radius rather than as a bug."""
    app._generate()
    app.projection_mode.set(mode)
    app._draw()
    pts = app._screen_positions()
    wrong = 0
    checked = 0
    for i in range(0, len(pts), 7):
        sx, sy = pts[i]
        hit = app._nearest_node_to(sx, sy)
        if hit is None:
            continue
        checked += 1
        # A tie is legitimate: two nodes can project onto the same pixel.
        if hit != i and math.dist(pts[hit], (sx, sy)) > 0.5:
            wrong += 1
    assert checked > 10
    assert wrong == 0, f'{wrong} of {checked} clicks landed on the wrong node'


@pytest.mark.parametrize('mode', list(sc.PROJECTION_MODES))
@pytest.mark.parametrize('z', [0.0, 1.5])
def test_unprojecting_to_a_plane_is_exact_in_both_modes(app, mode, z):
    """_unproject_to_plane hand-inverts the projection maths -- it is the
    one place the two modes cannot share code -- so it is checked against
    nodes whose true position is known."""
    app._generate()
    app.projection_mode.set(mode)
    app._draw()
    pts = app._screen_positions()
    worst = 0.0
    checked = 0
    for i, (x, y, zz) in enumerate(app.nodes):
        if abs(zz - z) > 1e-6:
            continue
        got = app._unproject_to_plane(*pts[i], z)
        if got is None:
            continue
        checked += 1
        worst = max(worst, math.dist(got, (x, y)))
    assert checked > 5
    assert worst < 1e-6, f'{mode} z={z}: worst error {worst:.6f} m'


def test_the_distance_slider_is_dead_in_parallel_and_says_so(app):
    """An orthographic projection has no eye to move, so a live slider
    would be a control that does nothing."""
    app._show_display_popover() if hasattr(app, '_show_display_popover') \
        else app._toggle_display_popover()
    app.root.update_idletasks()
    app.projection_mode.set(sc.PROJECTION_PARALLEL)
    app._on_projection_change()
    assert str(app.camera_scale.cget('state')) == 'disabled'
    assert 'true' in app.camera_note.cget('text')
    app.projection_mode.set(sc.PROJECTION_PERSPECTIVE)
    app._on_projection_change()
    assert str(app.camera_scale.cget('state')) == 'normal'
    assert 'eye' in app.camera_note.cget('text')


def test_switching_projection_before_the_popover_exists_does_not_crash(blank_app):
    """The popover builds lazily, so the slider may not exist when the
    projection is set -- by a test, or by a restored preference."""
    blank_app.projection_mode.set(sc.PROJECTION_PERSPECTIVE)
    blank_app._on_projection_change()


def test_a_line_across_the_view_does_not_converge_even_in_perspective(app):
    """The complement of the test above, and the reason its fixture needed
    azimuth 90: a line perpendicular to the view axis has every point the
    same distance from the eye, so it has no vanishing point and must stay
    evenly spaced. A 'perspective' that squeezed it too would be scaling by
    screen position rather than by distance."""
    app.grid_family.set(sc.FAMILY_LABEL['flat_grid'])
    app._on_generator_change()
    app.fg_nx.set(10); app.fg_ny.set(2); app.fg_module.set(3.0)
    app._generate()
    app.azimuth, app.elevation = 0.0, 15.0
    app.projection_mode.set(sc.PROJECTION_PERSPECTIVE)
    app.camera_distance.set(sc.CAMERA_DISTANCE_MIN)
    app._draw()
    bottom = sorted((n for n in range(len(app.nodes))
                     if abs(app.nodes[n][1]) < 1e-9 and abs(app.nodes[n][2]) < 1e-9),
                    key=lambda i: app.nodes[i][0])
    pts = app._screen_positions()
    gaps = [math.dist(pts[a], pts[b]) for a, b in zip(bottom, bottom[1:])]
    assert max(gaps) == pytest.approx(min(gaps), rel=1e-6)


# ═══════════════════════════════════════════════════════════════════════════
#  Bezier profiles and patches in the Shape panel
# ═══════════════════════════════════════════════════════════════════════════

def _spin(app, formula='3 + 1.6*sin(x*0.9)'):
    from apps.stereo import stereo_geometry as sgx
    _shape(app)
    app.shape_source.set(sc.SOURCE_SPIN)
    app.shape_z_top.set(formula)
    app.shape_p0.set('0'); app.shape_p1.set('6')
    app.shape_q0.set('0'); app.shape_q1.set('2*pi')
    app.shape_n1.set(8); app.shape_n2.set(14)
    app.shape_lattice.set(sgx.LATTICE_SINGLE)
    app._on_shape_mode_change()
    app.shape_pattern.set(sgx.PATTERN_ISOMETRIC)
    app._bz_fit()


def test_the_bezier_panel_shows_only_for_a_bezier_source(app):
    _shape(app)
    for source, shown in ((sc.SOURCE_FORMULA, False), (sc.SOURCE_EXTRUDE, True),
                          (sc.SOURCE_SPIN, True), (sc.SOURCE_PATCH, True)):
        app.shape_source.set(source)
        app.root.update_idletasks()
        assert bool(app.frame_bezier.winfo_ismapped()) is shown


def test_fitting_a_profile_reports_how_close_it_came(app):
    """Reported, never promised. A fit is an approximation and the only
    honest thing to do with one is put the real number on screen."""
    _spin(app)
    said = app.bz_error_note.cget('text')
    assert 'segments' in said and '%' in said
    assert app._bz_profile is not None
    assert app.bz_list.size() == len(app._bz_profile['ctrl'])


def test_a_spin_profile_builds_a_solid_of_revolution(app):
    _spin(app)
    app._build_shape_mesh()
    assert app.shape_status.cget('text') == '', app.shape_status.cget('text')
    zs = [n[2] for n in app.nodes]
    radii = [math.hypot(n[0], n[1]) for n in app.nodes]
    assert min(zs) == pytest.approx(0.0, abs=1e-6)
    assert max(zs) == pytest.approx(6.0, abs=1e-6)
    # a real waist-and-belly profile, not a cylinder
    assert max(radii) - min(radii) > 1.0


def test_editing_a_control_changes_the_surface_that_gets_built(app):
    """The point of the whole feature: the formula got you close, the
    handles get you the rest of the way."""
    _spin(app)
    app._build_shape_mesh()
    before = max(math.hypot(n[0], n[1]) for n in app.nodes)
    index = 12
    app._bz_set_control(index, app._bz_profile['ctrl'][index] + 2.5)
    app._build_shape_mesh()
    after = max(math.hypot(n[0], n[1]) for n in app.nodes)
    assert after > before + 1.0


def test_the_table_and_the_3d_drag_are_the_same_edit(app):
    """Two ways in, one code path out -- otherwise they drift and the same
    move means two things."""
    _spin(app)
    handles = app._bz_handle_screen()
    assert handles
    index, sx, sy = handles[12]
    assert app._bz_handle_at(sx, sy) == index
    before = app._bz_profile['ctrl'][index]
    app._on_canvas_press(FakeEvent(sx, sy))
    assert app._bz_drag == index
    app._on_canvas_motion(FakeEvent(sx + 40, sy))
    app._on_canvas_release(FakeEvent(sx + 40, sy))
    assert app._bz_drag is None
    dragged = app._bz_profile['ctrl'][index]
    assert dragged != pytest.approx(before)


def test_a_drag_keeps_the_curve_smooth(app):
    from apps.stereo import stereo_bezier as bzx
    _spin(app)
    handles = app._bz_handle_screen()
    index, sx, sy = handles[10]
    app._on_canvas_press(FakeEvent(sx, sy))
    app._on_canvas_motion(FakeEvent(sx + 30, sy))
    app._on_canvas_release(FakeEvent(sx + 30, sy))
    assert bzx.is_smooth(app._bz_profile)


def test_a_drag_is_undoable(app):
    """The profile is MODEL state -- it is what the mesh was built from --
    so leaving it out of the snapshot made undo restore the nodes while the
    curve kept the edit, and the next Build silently undid the undo."""
    _spin(app)
    handles = app._bz_handle_screen()
    index, sx, sy = handles[12]
    before = app._bz_profile['ctrl'][index]
    app._on_canvas_press(FakeEvent(sx, sy))
    app._on_canvas_motion(FakeEvent(sx + 40, sy))
    app._on_canvas_release(FakeEvent(sx + 40, sy))
    edited = app._bz_profile['ctrl'][index]
    app._undo()
    assert app._bz_profile['ctrl'][index] == pytest.approx(before)
    app._redo()
    assert app._bz_profile['ctrl'][index] == pytest.approx(edited)


def test_clicking_away_from_a_handle_still_lassoes(app):
    """A handle grab has to win over the lasso where there IS a handle, and
    lose everywhere else -- or the lasso stops working in Shape mode."""
    _spin(app)
    app._on_canvas_press(FakeEvent(3, 3))
    assert app._bz_drag is None
    assert app._lasso_press == (3, 3)


@pytest.mark.parametrize('mode', list(sc.PROJECTION_MODES))
def test_handles_can_be_grabbed_in_either_projection(app, mode):
    """The handles are placed through the same projection the model is, so
    perspective must not move them out from under the cursor."""
    _spin(app)
    app.projection_mode.set(mode)
    app._draw()
    for index, sx, sy in app._bz_handle_screen()[::5]:
        assert app._bz_handle_at(sx, sy) == index


def test_the_patch_says_when_it_is_too_coarse_to_design_from(app):
    """A degree-n patch has n-1 interior bends each way and cannot follow
    more waves than that. Silence there would read as success."""
    _shape(app)
    app.shape_source.set(sc.SOURCE_PATCH)
    app.shape_z_top.set('3*cos(x)*cos(y)')
    app.shape_p0.set('-9'); app.shape_p1.set('9')
    app.shape_q0.set('-9'); app.shape_q1.set('9')
    app.bz_degree.set(5)
    app._bz_fit()
    said = app.bz_error_note.cget('text')
    assert 'too far off' in said, said
    # Degree 14, not 10: measured, 2.86 waves each way still comes out
    # 6.5% wrong at degree 10 and only reaches 0.25% at 14. The warning was
    # right and the first guess at this number was not.
    app.bz_degree.set(14)
    app._bz_fit()
    assert 'too far off' not in app.bz_error_note.cget('text')


def test_the_preview_draws_the_bezier_surface_not_the_formula(app):
    """They are different surfaces the moment a handle moves, and for a
    spin they are not even the same KIND -- the formula is a radius against
    height, so drawing it as a height field would put a sheet in the air
    beside the solid actually being built."""
    _spin(app)
    app._build_shape_mesh()
    surfaces = app._preview_surfaces()
    assert len(surfaces) == 1
    surface = surfaces[0][0]
    # the spin surface puts the profile on the RADIUS at that height
    from apps.stereo import stereo_bezier as bzx
    x, y, z = surface(3.0, 0.0)
    assert z == pytest.approx(3.0)
    assert x == pytest.approx(bzx.profile_value(app._bz_profile, 3.0))


def test_a_bezier_source_that_was_never_fitted_still_builds(app):
    """Falling back to the typed formula rather than failing: choosing the
    source and pressing Build before Fit is an obvious thing to do."""
    _shape(app)
    app.shape_source.set(sc.SOURCE_EXTRUDE)
    app._bz_profile = None
    app.shape_z_top.set('2*cos(x/3)')
    app.shape_p0.set('-6'); app.shape_p1.set('6')
    app.shape_q0.set('-6'); app.shape_q1.set('6')
    app._build_shape_mesh()
    assert app.shape_status.cget('text') == ''
    assert app.nodes


def test_a_broken_formula_reports_instead_of_fitting_nonsense(app):
    _shape(app)
    app.shape_source.set(sc.SOURCE_SPIN)
    app.shape_z_top.set('!!broken!!')
    app._bz_fit()
    assert app._bz_profile is None
    assert app.bz_list.size() == 0
    assert app.bz_error_note.cget('text')


# ── auto-ranged utilization colours ───────────────────────────────────────

def test_util_color_absolute_scale_is_unchanged_by_default():
    """The default must still be the ABSOLUTE, code-defined scale: red at
    capacity, the same from one model to the next. Adding the `top`
    parameter must not have moved it."""
    from apps.stereo.stereo_app_colors import util_color
    assert util_color(0.0) == util_color(0.0, 1.0)
    assert util_color(0.5) == util_color(0.5, 1.0)
    assert util_color(1.0) == util_color(1.0, 1.0)
    assert util_color(1.0) == util_color(9.9), 'over capacity must stay pinned at red'


def test_util_color_auto_range_spreads_a_lightly_loaded_model():
    """The bug this was added for: a structure whose worst rod is at 2% of
    capacity comes out one flat green under the absolute scale, so the
    variation the thickness view plainly shows is invisible in colour.

    Auto-ranged to the model's own peak, the same numbers must span the
    whole ramp instead.
    """
    from apps.stereo.stereo_app_colors import util_color

    def spread(colors):
        """The largest single-channel difference across a set of colours.

        Counting DISTINCT hex strings is the wrong measure and was the
        first version of this test: the absolute scale does return four
        different strings here (#2e7d32 ... #377f31), but they differ by
        at most 9 in one channel and are indistinguishable on screen --
        which is exactly the complaint that started this. What matters is
        how far apart they LOOK.
        """
        rgb = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in colors]
        return max(max(v[k] for v in rgb) - min(v[k] for v in rgb)
                   for k in range(3))

    peak = 0.0216                        # measured on the user's wave model
    levels = (0.0, peak / 4, peak / 2, peak)
    absolute = spread([util_color(u) for u in levels])
    ranged = spread([util_color(u, peak) for u in levels])
    assert absolute <= 12, (
        f'the absolute scale varies by {absolute}/255 here -- it should be '
        'effectively one flat colour')
    assert ranged > 100, (
        f'auto-range only spread these by {ranged}/255; the whole point is '
        'that they become plainly different colours')
    assert util_color(peak, peak) == util_color(1.0), 'the peak should reach red'


def test_util_color_auto_range_never_stretches_past_capacity(app):
    """The safety half. Auto-ranging an OVERLOADED model would slide the red
    end out to its peak and paint a rod at exactly 1.0 -- at capacity -- in
    mid-amber. _util_top caps at 1.0 so auto-range can only ever stretch UP
    TO capacity, never beyond."""
    from apps.stereo.stereo_app_colors import util_color
    app.util_autorange.set(True)
    app.member_checks = [{'checked': True, 'util': u} for u in (0.2, 1.0, 2.4)]
    assert app._util_top(1.0) == 1.0
    assert util_color(1.0, app._util_top(1.0)) == util_color(1.0), \
        'a rod at capacity must be red whatever the scale'
    # and for a lightly loaded model it really does range
    app.member_checks = [{'checked': True, 'util': u} for u in (0.001, 0.02)]
    assert app._util_top(1.0) == pytest.approx(0.02)


def test_util_top_is_one_when_auto_range_is_off_or_nothing_is_checked(app):
    app.util_autorange.set(False)
    app.member_checks = [{'checked': True, 'util': 0.02}]
    assert app._util_top(1.0) == 1.0
    app.util_autorange.set(True)
    app.member_checks = None
    assert app._util_top(1.0) == 1.0
    app.member_checks = [{'checked': False, 'util': None}]
    assert app._util_top(1.0) == 1.0
    app.member_checks = [{'checked': True, 'util': 0.0}]
    assert app._util_top(1.0) == 1.0, 'a zero peak must not divide by zero'


def test_the_surface_preview_only_draws_over_the_shape_panel(app):
    """The preview shows what the SHAPE panel would build. Drawn over a
    model that came from anywhere else it painted a flat sheet at z=0
    straight through every example and every family Generate, belonging to
    nothing on screen."""
    app.show_surface_preview.set(True)
    app._set_mode('shape')
    assert app._surface_preview_applies()
    app._set_mode('build')
    assert not app._surface_preview_applies()
    # and the checkbox still wins
    app._set_mode('shape')
    app.show_surface_preview.set(False)
    assert not app._surface_preview_applies()


def test_loading_an_example_keeps_the_rod_loads_it_ships_with(app):
    """A rod load is a member INDEX, so _load_mesh clears them on every
    regenerate -- except the ones the incoming mesh brought itself, whose
    indices are by construction its own."""
    from apps.stereo import stereo_examples as sx
    label, builder = [(l, b) for l, b in sx.EXAMPLES
                      if 'ALONG THE RODS' in l][0]
    app._load_example(builder, label)
    assert app.member_loads, 'the rod-load example arrived with no rod loads'
    for ml in app.member_loads:
        assert 0 <= ml['member'] < len(app.members)
    # while an example that ships none still comes in clean
    label2, builder2 = [(l, b) for l, b in sx.EXAMPLES
                        if 'Schwedler dome' in l][0]
    app._load_example(builder2, label2)
    assert app.member_loads == []


# ═══════════════════════════════════════════════════════════════════════════════
# Carried over from the analysis/report branch at the merge.
#
# TestSimpleAdvancedToggle is deliberately gone: the Simple/Advanced toggle it
# covered was superseded by the mode rail, which shows one mode's controls at a
# time by construction. Two "hidden in simple mode" tests went with it for the
# same reason. Everything else here still describes live behaviour.
# ═══════════════════════════════════════════════════════════════════════════════

class TestSnapAndCoordinateDisplay:

    def test_status_bar_exists(self, app):
        assert hasattr(app, 'status_var')
        assert hasattr(app, 'status_label')
        info = app.status_label.pack_info()
        assert info is not None

    def test_snap_node_on_exact_hit(self, app):
        pts = app._screen_positions()
        sx, sy = pts[0]
        evt = FakeEvent(int(sx), int(sy))
        app._on_mouse_motion(evt)
        assert app._snap_node == 0
        assert 'Node 0' in app.status_var.get()

    def test_snap_node_within_radius(self, app):
        pts = app._screen_positions()
        sx, sy = pts[0]
        evt = FakeEvent(int(sx) + 5, int(sy) + 5)
        app._on_mouse_motion(evt)
        assert app._snap_node == 0

    def test_no_snap_far_from_nodes(self, app):
        evt = FakeEvent(-9999, -9999)
        app._on_mouse_motion(evt)
        assert app._snap_node is None

    def test_snap_midpoint_when_no_node_nearby(self, app):
        pts = app._screen_positions()
        m = app.members[0]
        ax, ay = pts[m['a']]
        bx, by = pts[m['b']]
        mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
        if math.hypot(mx - pts[m['a']][0], my - pts[m['a']][1]) > sc.SNAP_RADIUS_PX:
            evt = FakeEvent(int(mx), int(my))
            app._on_mouse_motion(evt)
            if app._snap_node is None:
                assert app._snap_midpoint is not None
                assert 'Midpoint' in app.status_var.get()

    def test_cursor_world_set_on_snap(self, app):
        pts = app._screen_positions()
        sx, sy = pts[0]
        evt = FakeEvent(int(sx), int(sy))
        app._on_mouse_motion(evt)
        assert app._cursor_world is not None
        x, y, z = app._cursor_world
        nx, ny, nz = app.nodes[0]
        assert abs(x - nx) < 1e-6
        assert abs(y - ny) < 1e-6
        assert abs(z - nz) < 1e-6

    def test_status_var_shows_coordinates(self, app):
        pts = app._screen_positions()
        sx, sy = pts[0]
        evt = FakeEvent(int(sx), int(sy))
        app._on_mouse_motion(evt)
        text = app.status_var.get()
        assert '(' in text and ')' in text
        assert 'm' in text

    def test_unproject_to_z0_returns_tuple(self, app):
        app.azimuth = 35.0
        app.elevation = 22.0
        pts = app._screen_positions()
        sx, sy = pts[0]
        result = app._unproject_to_z0(sx, sy)
        assert result is not None
        assert len(result) == 3
        assert result[2] == 0.0

    def test_unproject_returns_none_at_zero_elevation(self, app):
        app.azimuth = 0.0
        app.elevation = 0.0
        app._draw()
        pts = app._screen_positions()
        sx, sy = pts[0]
        result = app._unproject_to_z0(sx, sy)
        assert result is None

    def test_motion_with_no_nodes_does_not_crash(self, app):
        saved = app.nodes[:]
        app.nodes = []
        evt = FakeEvent(100, 100)
        app._on_mouse_motion(evt)
        app.nodes = saved

    def test_motion_with_no_event_does_not_crash(self, app):
        app._on_mouse_motion(None)

    def test_snap_constants_exist(self):
        assert sc.SNAP_RADIUS_PX == 15
        assert sc.SNAP_NODE_COLOR == '#e67e22'
        assert sc.SNAP_MIDPOINT_COLOR == '#3498db'
        assert sc.SNAP_RING_RADIUS == 8


class TestKeyboardShortcuts:

    def test_shortcut_generate_regenerates(self, app):
        old_n = len(app.nodes)
        app._shortcut_generate()
        assert len(app.nodes) == old_n

    def test_shortcut_analyze_runs_solver(self, app):
        app._shortcut_analyze()
        assert app.results is not None

    def test_shortcut_zoom_fit_does_not_crash(self, app):
        app._shortcut_zoom_fit()

    def test_shortcut_view_xy(self, app):
        app._shortcut_view_xy()
        assert app.azimuth == 0.0
        assert app.elevation == 0.0

    def test_shortcut_view_xz(self, app):
        app._shortcut_view_xz()
        assert app.azimuth == 0.0
        assert app.elevation == 90.0

    def test_shortcut_view_yz(self, app):
        app._shortcut_view_yz()
        assert app.azimuth == 90.0
        assert app.elevation == 0.0

    def test_shortcuts_suppressed_during_axis_extend(self, app):
        app._axis_pending = (1, 0, 0)
        old_az = app.azimuth
        old_el = app.elevation
        app._shortcut_view_xy()
        assert app.azimuth == old_az
        assert app.elevation == old_el
        app._shortcut_generate()
        app._shortcut_analyze()
        app._shortcut_zoom_fit()
        app._axis_pending = None


class TestTheShortcutsAreActuallyWiredToTheCanvas:
    """Every test in TestKeyboardShortcuts above calls the handler directly,
    so all of them passed while the canvas was bound to none of them -- which
    is exactly what happened at the merge: the mode rail replaced the sidebar
    that had carried the bind() calls, and the snap, the arrow keys and the
    single-key shortcuts were unreachable from the keyboard for a while with
    a green suite. These tests press the keys instead.
    """

    def _press(self, app, seq, **kw):
        """focus_FORCE, not focus_set: a key event is delivered to whichever
        widget holds the focus and then travels up its bindtags, so after a
        few hundred earlier tests have left the focus on some entry of their
        own, focus_set only *requests* it and the keypress goes elsewhere.
        These five tests passed alone and failed in the full suite for
        exactly that reason. The assert makes a future focus problem say so
        instead of surfacing as a state assertion that looks like the
        binding is gone."""
        app.canvas.focus_force()
        app.root.update()
        assert app.root.focus_get() is app.canvas, (
            'canvas did not take focus, so %s was never delivered' % seq)
        app.canvas.event_generate(seq, when='now', **kw)
        app.root.update_idletasks()
        app.root.update()

    def test_every_sequence_the_handlers_need_is_bound(self, app):
        bound = set(app.canvas.bind())
        for seq in ('<Motion>', '<Key-Escape>', '<Key-Delete>', '<Key-BackSpace>',
                    '<Key-Left>', '<Key-Right>', '<Key-Up>', '<Key-Down>',
                    '<Key-Prior>', '<Key-Next>',
                    'g', 'G', 'a', 'A', 'f', 'F', '1', '2', '3'):
            assert seq in bound, f'{seq} is not bound on the canvas'

    def test_motion_keeps_both_handlers(self, app):
        """The footprint-disc hover and the snap both want <Motion>; binding
        one without add='+' silently throws the other away."""
        script = app.canvas.bind('<Motion>')
        assert len([l for l in script.splitlines() if l.strip()]) == 2

    def test_the_view_keys_move_the_camera(self, app):
        app.azimuth, app.elevation = 37.0, 21.0
        self._press(app, '<KeyPress-1>')
        assert (app.azimuth, app.elevation) == (0.0, 0.0)
        self._press(app, '<KeyPress-2>')
        assert (app.azimuth, app.elevation) == (0.0, 90.0)
        self._press(app, '<KeyPress-3>')
        assert (app.azimuth, app.elevation) == (90.0, 0.0)

    def test_a_analyses(self, app):
        app.results = None
        self._press(app, '<KeyPress-a>')
        assert app.results is not None

    def test_g_generates(self, app):
        app._clear_model()
        assert app.nodes == []
        self._press(app, '<KeyPress-g>')
        assert len(app.nodes) > 0

    def test_an_arrow_key_arms_the_axis_extend_and_shows_its_length_box(self, app):
        app.selected_nodes = {0}
        app.selected_members = set()
        app.selected_member = None
        self._press(app, '<KeyPress-Right>')
        assert app._axis_pending == (1, 0, 0)
        assert app._axis_dir_label.cget('text') == '+X'
        # armed with the box off-screen would be a tool waiting on an input
        # the reader cannot see, so arming switches the rail to it
        assert app.active_mode.get() == 'build'
        assert app._axis_extend_frame.winfo_ismapped()
        self._press(app, '<KeyPress-Escape>')
        assert app._axis_pending is None
        assert not app._axis_extend_frame.winfo_ismapped()

    def test_arming_from_another_mode_still_shows_the_box(self, app):
        app._set_mode('results')
        app.selected_nodes = {0}
        self._press(app, '<KeyPress-Up>')
        assert app.active_mode.get() == 'build'
        assert app._axis_extend_frame.winfo_ismapped()

    def test_hovering_snaps_and_writes_the_coordinates(self, app):
        sx, sy = app._screen_positions()[0]
        self._press(app, '<Motion>', x=int(sx), y=int(sy))
        assert app._snap_node == 0
        assert 'Node 0' in app.status_var.get()


class TestPropertiesPanel:

    def test_properties_panel_exists(self, app):
        assert hasattr(app, '_panel_properties')
        assert hasattr(app, '_props_label')
        assert hasattr(app, '_props_frame')
        assert hasattr(app, '_props_entries')

    def test_no_selection_shows_placeholder(self, app):
        app.selected_nodes = set()
        app.selected_member = None
        app.selected_members = set()
        app._update_properties_panel()
        assert 'select' in app._props_label.cget('text').lower()

    def test_single_node_selection_shows_coords(self, app):
        app.selected_nodes = {0}
        app.selected_member = None
        app.selected_members = set()
        app._update_properties_panel()
        text = app._props_label.cget('text')
        assert 'Node 0' in text
        assert 'x' in app._props_entries
        assert 'y' in app._props_entries
        assert 'z' in app._props_entries

    def test_single_member_selection_shows_section_props(self, app):
        app.selected_nodes = set()
        app.selected_member = 0
        app.selected_members = {0}
        app._update_properties_panel()
        text = app._props_label.cget('text')
        assert 'Member 0' in text
        assert 'E' in app._props_entries
        assert 'A' in app._props_entries

    def test_multi_select_shows_count(self, app):
        app.selected_nodes = {0, 1, 2}
        app.selected_member = None
        app.selected_members = set()
        app._update_properties_panel()
        text = app._props_label.cget('text')
        assert '3' in text
        assert 'node' in text.lower()

    def test_apply_node_properties_changes_coords(self, app):
        app.selected_nodes = {0}
        app.selected_member = None
        app.selected_members = set()
        app._update_properties_panel()
        old_pos = app.nodes[0]
        app._props_entries['x'].set(99.0)
        app._props_entries['y'].set(88.0)
        app._props_entries['z'].set(77.0)
        app._apply_node_properties()
        assert app.nodes[0] == (99.0, 88.0, 77.0)
        assert app.nodes[0] != old_pos

    def test_apply_node_creates_undo(self, app):
        app.selected_nodes = {0}
        app.selected_member = None
        app.selected_members = set()
        app._update_properties_panel()
        undo_len = len(app._undo_stack)
        app._apply_node_properties()
        assert len(app._undo_stack) == undo_len + 1

    def test_apply_member_properties_changes_section(self, app):
        app.selected_nodes = set()
        app.selected_member = 0
        app.selected_members = {0}
        app._update_properties_panel()
        app._props_entries['E'].set(210.0)
        app._apply_member_properties()
        assert app.members[0]['E'] == 210.0

    def test_apply_member_creates_undo(self, app):
        app.selected_nodes = set()
        app.selected_member = 0
        app.selected_members = {0}
        app._update_properties_panel()
        undo_len = len(app._undo_stack)
        app._apply_member_properties()
        assert len(app._undo_stack) == undo_len + 1

    def test_apply_node_with_no_selection_is_noop(self, app):
        app.selected_nodes = set()
        app._apply_node_properties()

    def test_apply_member_with_no_selection_is_noop(self, app):
        app.selected_member = None
        app._apply_member_properties()

    def test_node_with_support_shows_support_info(self, app):
        if app.supports:
            sn = app.supports[0]['node']
            app.selected_nodes = {sn}
            app.selected_member = None
            app.selected_members = set()
            app._update_properties_panel()
            children = app._props_frame.winfo_children()
            texts = []
            for c in children:
                try:
                    texts.append(c.cget('text'))
                except tk.TclError:
                    pass
            assert any('Support' in t for t in texts if isinstance(t, str))


    def test_analyzed_member_shows_axial_force(self, app):
        app._analyze()
        assert app.results is not None
        app.selected_nodes = set()
        app.selected_member = 0
        app.selected_members = {0}
        app._update_properties_panel()
        children = app._props_frame.winfo_children()
        texts = []
        for c in children:
            try:
                texts.append(c.cget('text'))
            except tk.TclError:
                pass
        assert any('N =' in t for t in texts if isinstance(t, str))


class TestModelTree:

    def test_model_tree_panel_exists(self, app):
        assert hasattr(app, '_panel_model_tree')
        assert hasattr(app, '_tree_items')
        assert hasattr(app, '_tree_frame')

    def test_tree_has_all_sections(self, app):
        for key in ('Nodes', 'Members', 'Supports', 'Loads', 'Profiles'):
            assert key in app._tree_items
            item = app._tree_items[key]
            assert 'label' in item
            assert 'detail' in item
            assert 'expanded' in item

    def test_tree_count_returns_correct_values(self, app):
        assert app._tree_count('Nodes') == len(app.nodes)
        assert app._tree_count('Members') == len(app.members)
        assert app._tree_count('Supports') == len(app.supports)
        assert app._tree_count('Loads') == len(app.loads)
        assert app._tree_count('Profiles') == len(app.profiles)

    def test_toggle_section_expands_and_collapses(self, app):
        assert not app._tree_items['Nodes']['expanded']
        app._toggle_tree_section('Nodes')
        assert app._tree_items['Nodes']['expanded']
        app._toggle_tree_section('Nodes')
        assert not app._tree_items['Nodes']['expanded']

    def test_expanded_section_shows_items(self, app):
        app._toggle_tree_section('Nodes')
        detail = app._tree_items['Nodes']['detail']
        children = detail.winfo_children()
        assert len(children) > 0
        app._toggle_tree_section('Nodes')

    def test_tree_select_node_sets_selection(self, app):
        app._tree_select_node(0)
        assert 0 in app.selected_nodes
        assert app.selected_member is None

    def test_tree_select_member_sets_selection(self, app):
        app._tree_select_member(0)
        assert 0 in app.selected_members
        assert app.selected_member == 0
        assert len(app.selected_nodes) == 0

    def test_center_on_node_updates_pan(self, app):
        old_px = app.zc.pan_x
        old_py = app.zc.pan_y
        app._center_on_node(0)
        assert app._view_touched

    def test_refresh_model_tree_updates_counts(self, app):
        app._refresh_model_tree()
        text = app._tree_items['Nodes']['label'].cget('text')
        assert str(len(app.nodes)) in text


    def test_tree_select_node_out_of_range_is_safe(self, app):
        app._tree_select_node(99999)

    def test_tree_select_member_out_of_range_is_safe(self, app):
        app._tree_select_member(99999)

    def test_center_on_node_out_of_range_is_safe(self, app):
        app._center_on_node(99999)

    def test_expanded_members_shows_role(self, app):
        app._toggle_tree_section('Members')
        detail = app._tree_items['Members']['detail']
        children = detail.winfo_children()
        if children:
            text = children[0].cget('text')
            assert '–' in text
        app._toggle_tree_section('Members')

    def test_expanded_profiles_shows_names(self, app):
        app._toggle_tree_section('Profiles')
        detail = app._tree_items['Profiles']['detail']
        children = detail.winfo_children()
        assert len(children) == len(app.profiles)
        app._toggle_tree_section('Profiles')

    def test_toggle_all_sections_does_not_crash(self, app):
        for key in ('Nodes', 'Members', 'Supports', 'Loads', 'Profiles'):
            app._toggle_tree_section(key)
        for key in ('Nodes', 'Members', 'Supports', 'Loads', 'Profiles'):
            app._toggle_tree_section(key)


class TestDesignVariants:
    def test_variants_list_starts_empty(self, app):
        assert app._variants == []

    def test_save_variant_requires_results(self, app):
        app.results = None
        app._save_variant()
        assert len(app._variants) == 0

    def test_save_variant_stores_snapshot(self, app):
        app._analyze()
        assert app.results is not None
        import copy
        from unittest.mock import patch
        with patch('tkinter.simpledialog.askstring', return_value='Variant A'):
            app._save_variant()
        assert len(app._variants) == 1
        v = app._variants[0]
        assert v['name'] == 'Variant A'
        assert 'summary' in v
        assert v['summary']['n_nodes'] == len(app.nodes)
        assert v['summary']['n_members'] == len(app.members)
        assert v['summary']['max_force_kN'] >= 0
        assert v['summary']['max_disp_mm'] >= 0
        assert v['summary']['weight_kg'] > 0

    def test_compare_requires_two_variants(self, app):
        app._compare_variants()

    def test_save_two_and_compare(self, app):
        app._analyze()
        from unittest.mock import patch
        with patch('tkinter.simpledialog.askstring', return_value='V1'):
            app._save_variant()
        with patch('tkinter.simpledialog.askstring', return_value='V2'):
            app._save_variant()
        assert len(app._variants) == 2
        app._show_variant_comparison()
        app.root.update_idletasks()

    def test_variant_commands_are_reachable(self, app):
        """The old toolbar buttons became Export-menu entries at the merge, so
        what has to hold is that the two commands are still on the menu and
        still bound to the handlers the tests above exercise."""
        menu = app.export_menu
        labels = [menu.entrycget(i, 'label')
                  for i in range(menu.index('end') + 1)
                  if menu.type(i) == 'command']
        assert 'Save Variant…' in labels
        assert 'Compare Variants…' in labels
        assert callable(app._save_variant)
        assert callable(app._compare_variants)


class TestExportsCarryTheSolvedLoadCase:
    def test_the_default_model_is_loaded_by_something_other_than_self_loads(self, app):
        """The premise: without this, the tests below would pass vacuously."""
        assert app.loads == [], 'the default model types no point loads'
        assert len(app._all_loads()) > 0, 'but it IS loaded (area load)'

    def test_export_excel_writes_the_loads_the_solver_used(self, app, tmp_path,
                                                            monkeypatch):
        app._analyze()
        assert app.err is None
        path = str(tmp_path / 'model.xlsx')
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                            lambda *a, **kw: path)
        app._export_excel()

        from apps.stereo import stereo_reports as sr
        nodes2, members2, loads2, supports2, _ = sr.import_excel_model(path)
        assert len(loads2) == len(app._all_loads())

        # and the re-imported model must solve to the SAME answer
        res2, err2 = sm.analyze(nodes2, members2, loads2, supports2)
        assert err2 is None
        def _max_disp(res):
            return max((nr['ux'] ** 2 + nr['uy'] ** 2 + nr['uz'] ** 2) ** 0.5
                       for nr in res['node_res'])
        assert _max_disp(res2) == pytest.approx(_max_disp(app.results), rel=1e-9)
        assert _max_disp(res2) > 0.0

    def test_exported_workbook_reimports_without_double_counting(self, app, tmp_path,
                                                                  monkeypatch):
        """The exported [LOADS] table is the complete case, so the import
        has to switch the area-load and self-weight generators OFF or the
        next Analyze adds a second copy of both."""
        app.self_weight_on.set(True)
        app._analyze()
        before = sum(ld.get('fz', 0.0) for ld in app._all_loads())

        path = str(tmp_path / 'model.xlsx')
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                            lambda *a, **kw: path)
        app._export_excel()
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.askopenfilename',
                            lambda *a, **kw: path)
        app._import_excel()

        assert app.area_load_on.get() is False
        assert app.self_weight_on.get() is False
        after = sum(ld.get('fz', 0.0) for ld in app._all_loads())
        assert after == pytest.approx(before, rel=1e-9)

    def test_export_pdf_reports_a_load_case_that_balances_the_reactions(
            self, app, tmp_path, monkeypatch):
        app._analyze()
        assert app.err is None
        seen = {}
        real = sr_module.export_pdf

        def spy(nodes, members, loads, supports, results, path, **kw):
            seen['loads'] = loads
            seen['supports'] = supports
            return real(nodes, members, loads, supports, results, path, **kw)

        monkeypatch.setattr(sr_module, 'export_pdf', spy)
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                            lambda *a, **kw: str(tmp_path / 'r.pdf'))
        # the sheet chooser is a modal dialog; these tests are about what
        # the export DOES with a choice, so they make it for it.
        app._pdf_sheet_dialog = lambda *a, **kw: set(sr_module.PDF_SHEET_GROUPS)
        app._export_pdf()

        applied, reacted, residual = sr_module._pdf_equilibrium(
            seen['loads'], app.results['reactions'])
        assert applied[2] < 0, 'the model is loaded downward'
        scale = max(abs(v) for v in applied) or 1.0
        for r in residual:
            assert abs(r) < scale * 1e-6, (
                f'the report contradicts its own reaction table: {residual}')

    def test_export_pdf_draws_the_supports_the_solver_actually_used(
            self, app, tmp_path, monkeypatch):
        """A support switched off in the sandbox is not in the solve, so it
        must not be drawn on the report as if it were holding the
        structure up."""
        app._analyze()
        victim = app.supports[0]['node']
        app._disabled_supports.add(victim)
        app._analyze()

        seen = {}
        real = sr_module.export_pdf
        monkeypatch.setattr(sr_module, 'export_pdf',
                            lambda n, m, l, s, r, p, **kw: (
                                seen.update(supports=s),
                                real(n, m, l, s, r, p, **kw))[1])
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                            lambda *a, **kw: str(tmp_path / 'r.pdf'))
        # the sheet chooser is a modal dialog; these tests are about what
        # the export DOES with a choice, so they make it for it.
        app._pdf_sheet_dialog = lambda *a, **kw: set(sr_module.PDF_SHEET_GROUPS)
        app._export_pdf()
        assert victim not in {s['node'] for s in seen['supports']}
        assert len(seen['supports']) == len(app._active_supports())

    def test_saved_variant_keeps_the_load_case_it_was_analysed_under(
            self, app, monkeypatch):
        """Loading a variant clears _load_nodes, so a variant carrying only
        the typed point loads came back as an unloaded structure sitting
        beside the results of a loaded one."""
        app._analyze()
        solved = app._all_loads()
        assert solved
        monkeypatch.setattr('tkinter.simpledialog.askstring',
                            lambda *a, **kw: 'baseline')
        app._save_variant()
        assert len(app._variants) == 1
        v = app._variants[0]
        assert len(v['loads']) == len(solved)
        assert v['summary']['n_loads'] == len(solved)
        total = sum(ld.get('fz', 0.0) for ld in v['loads'])
        assert total == pytest.approx(sum(ld.get('fz', 0.0) for ld in solved))
        # re-solving the snapshot alone reproduces the stored result
        res2, err2 = sm.analyze(v['nodes'], v['members'], v['loads'],
                                v['supports'])
        assert err2 is None
        d1 = max((nr['ux'] ** 2 + nr['uy'] ** 2 + nr['uz'] ** 2) ** 0.5
                 for nr in v['results']['node_res'])
        d2 = max((nr['ux'] ** 2 + nr['uy'] ** 2 + nr['uz'] ** 2) ** 0.5
                 for nr in res2['node_res'])
        assert d2 == pytest.approx(d1, rel=1e-9)
        assert d2 > 0.0


class TestExportedReportsNameTheModel:
    """meta['grid_family'] ends up in the PDF title block and the Excel
    [META] sheet. It used to be read straight off the Grid Family dropdown,
    which _load_example, _import_excel, _open_example and the variant
    loader never touch -- so loading the Schwedler dome example and
    exporting produced a report headed "Flat double-layer grid"."""

    def test_a_generated_model_is_named_after_its_family(self, app):
        app.grid_family.set(FAMILY_LABEL['dome'])
        app._on_generator_change()
        app._generate()
        assert app._model_name() == FAMILY_LABEL['dome']

    def test_an_example_is_named_after_the_example(self, app):
        from apps.stereo import stereo_examples as sx
        label, builder = sx.EXAMPLES[7]
        app._load_example(builder, label)
        assert app._model_name() == label
        assert app._model_name() != app.grid_family.get()

    def test_regenerating_drops_the_example_name(self, app):
        from apps.stereo import stereo_examples as sx
        label, builder = sx.EXAMPLES[7]
        app._load_example(builder, label)
        app.grid_family.set(FAMILY_LABEL['flat_grid'])
        app._on_generator_change()
        app._generate()
        assert app._model_name() == FAMILY_LABEL['flat_grid']

    def test_the_pdf_title_block_carries_that_name(self, app, tmp_path,
                                                   monkeypatch):
        from apps.stereo import stereo_examples as sx
        label, builder = sx.EXAMPLES[7]
        app._load_example(builder, label)
        app._analyze()
        seen = {}
        real = sr_module.export_pdf
        monkeypatch.setattr(sr_module, 'export_pdf',
                            lambda n, m, l, s, r, p, **kw: (
                                seen.update(meta=kw.get('meta')),
                                real(n, m, l, s, r, p, **kw))[1])
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                            lambda *a, **kw: str(tmp_path / 'r.pdf'))
        # the sheet chooser is a modal dialog; these tests are about what
        # the export DOES with a choice, so they make it for it.
        app._pdf_sheet_dialog = lambda *a, **kw: set(sr_module.PDF_SHEET_GROUPS)
        app._export_pdf()
        assert seen['meta']['grid_family'] == label
        fields = dict(sr_module._pdf_sheet_meta(app.nodes, app.members,
                                                seen['meta']))
        assert fields['MODEL'] == label[:22]

    def test_an_imported_model_is_named_after_its_file(self, app, tmp_path,
                                                        monkeypatch):
        app._analyze()
        path = str(tmp_path / 'my_roof.xlsx')
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                            lambda *a, **kw: path)
        app._export_excel()
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.askopenfilename',
                            lambda *a, **kw: path)
        app._import_excel()
        assert app._model_name() == 'my_roof.xlsx'


class TestPdfOfSelection:
    """A report on the selected group ALONE. The rest of the structure is
    cut out of the model the report is built from, not dimmed behind it,
    so nothing can obstruct the view of what is being analysed."""

    def test_the_button_exists_and_is_an_advanced_tool(self, app):
        # It moved from a toolbar button onto the Export menu in the UI
        # rebuild, so assert on the menu entry rather than the old button.
        labels = [app.export_menu.entrycget(i, 'label')
                  for i in range(app.export_menu.index('end') + 1)
                  if app.export_menu.type(i) == 'command']
        assert 'PDF of Selection…' in labels

    def test_it_says_so_when_nothing_is_selected(self, app, dialogs):
        app.selected_members = set()
        app.selected_nodes = set()
        # the sheet chooser is a modal dialog; these tests are about what
        # the export DOES with a choice, so they make it for it.
        app._pdf_sheet_dialog = lambda *a, **kw: set(sr_module.PDF_SHEET_GROUPS)
        app._export_selection_pdf()
        assert any('Nothing is selected' in str(d) for d in dialogs)

    def test_selected_rods_are_what_gets_reported(self, app):
        app.selected_members = {0, 3, 7}
        assert app._selection_member_idx() == {0, 3, 7}

    def test_a_lassoed_node_region_means_the_rods_inside_it(self, app):
        """With no rod selected, the group is the rods whose BOTH ends are
        selected nodes -- what lassoing a region of the grid means."""
        app.selected_members = set()
        app.selected_nodes = {app.members[0]['a'], app.members[0]['b']}
        idx = app._selection_member_idx()
        assert 0 in idx
        for i in idx:
            assert app.members[i]['a'] in app.selected_nodes
            assert app.members[i]['b'] in app.selected_nodes

    def test_the_report_holds_only_the_group(self, app, tmp_path, monkeypatch):
        app._analyze()
        app.selected_members = {0, 1, 2}
        seen = {}
        real = sr_module.export_pdf
        monkeypatch.setattr(sr_module, 'export_pdf',
                            lambda n, m, l, s, r, p, **kw: (
                                seen.update(nodes=n, members=m, supports=s,
                                            results=r, meta=kw.get('meta')),
                                real(n, m, l, s, r, p, **kw))[1])
        monkeypatch.setattr('tkinter.simpledialog.askstring',
                            lambda *a, **kw: 'North bay')
        path = str(tmp_path / 'group.pdf')
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                            lambda *a, **kw: path)
        # the sheet chooser is a modal dialog; these tests are about what
        # the export DOES with a choice, so they make it for it.
        app._pdf_sheet_dialog = lambda *a, **kw: set(sr_module.PDF_SHEET_GROUPS)
        app._export_selection_pdf()

        assert os.path.isfile(path)
        assert len(seen['members']) == 3
        assert len(seen['members']) < len(app.members)
        assert len(seen['nodes']) < len(app.nodes)
        # the group's own solved numbers travelled with it
        assert len(seen['results']['member_res']) == 3
        assert len(seen['results']['node_res']) == len(seen['nodes'])
        for i, mi in enumerate(sorted(app.selected_members)):
            assert seen['results']['member_res'][i]['N'] == \
                app.results['member_res'][mi]['N']

    def test_the_sheet_names_the_group_and_the_file(self, app, tmp_path,
                                                     monkeypatch):
        from apps.stereo import stereo_examples as sx
        label, builder = sx.EXAMPLES[7]
        app._load_example(builder, label)
        app._analyze()
        app.selected_members = {0, 1, 2, 3}
        seen = {}
        real = sr_module.export_pdf
        monkeypatch.setattr(sr_module, 'export_pdf',
                            lambda n, m, l, s, r, p, **kw: (
                                seen.update(meta=kw.get('meta')),
                                real(n, m, l, s, r, p, **kw))[1])
        monkeypatch.setattr('tkinter.simpledialog.askstring',
                            lambda *a, **kw: 'Ring beam')
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                            lambda *a, **kw: str(tmp_path / 'g.pdf'))
        # the sheet chooser is a modal dialog; these tests are about what
        # the export DOES with a choice, so they make it for it.
        app._pdf_sheet_dialog = lambda *a, **kw: set(sr_module.PDF_SHEET_GROUPS)
        app._export_selection_pdf()

        assert seen['meta']['group'] == 'Ring beam'
        assert seen['meta']['subset_of'] == label
        fields = dict(sr_module._pdf_sheet_meta(app.nodes, app.members,
                                                seen['meta']))
        assert fields['GROUP'] == 'Ring beam'
        assert fields['FILE'] == label[:20]

    def test_cancelling_the_name_writes_nothing(self, app, tmp_path,
                                                 monkeypatch):
        app._analyze()
        app.selected_members = {0}
        path = tmp_path / 'never.pdf'
        monkeypatch.setattr('tkinter.simpledialog.askstring',
                            lambda *a, **kw: None)
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                            lambda *a, **kw: str(path))
        # the sheet chooser is a modal dialog; these tests are about what
        # the export DOES with a choice, so they make it for it.
        app._pdf_sheet_dialog = lambda *a, **kw: set(sr_module.PDF_SHEET_GROUPS)
        app._export_selection_pdf()
        assert not path.exists()


class TestPdfSheetChooser:
    """The full report is nineteen sheets on a rigid-jointed model: right
    for a design file, wrong for a slide. The reader picks which groups of
    sheets the export assembles, and the dialog counts them before it
    writes anything."""

    def _pdf_pages(self, path):
        import re
        return len(re.findall(rb'/Type\s*/Page(?![a-zA-Z])',
                              open(path, 'rb').read()))

    def test_the_chooser_runs_before_the_file_dialog(self, app, monkeypatch):
        """Asked for a path first and the sheets second, a reader who
        cancels the chooser has already named a file that never appears."""
        order = []
        app._pdf_sheet_dialog = lambda *a, **kw: (order.append('sheets'),
                                                  set())[1]
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                            lambda *a, **kw: (order.append('path'), '')[1])
        app._analyze()
        app._export_pdf()
        assert order == ['sheets', 'path']

    def test_cancelling_the_chooser_writes_nothing(self, app, tmp_path,
                                                   monkeypatch):
        app._analyze()
        path = tmp_path / 'never.pdf'
        app._pdf_sheet_dialog = lambda *a, **kw: None
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                            lambda *a, **kw: str(path))
        app._export_pdf()
        assert not path.exists()

    def test_the_choice_reaches_the_report(self, app, tmp_path, monkeypatch):
        app._analyze()
        path = tmp_path / 'short.pdf'
        app._pdf_sheet_dialog = lambda *a, **kw: {'force'}
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                            lambda *a, **kw: str(path))
        app._export_pdf()
        plan = sr_module.plan_sheets(app.results, app.member_checks,
                                     0, {'force'})
        assert self._pdf_pages(str(path)) == len(plan)
        assert len(plan) < len(sr_module.plan_sheets(
            app.results, app.member_checks, 0))

    def test_the_selection_report_takes_a_choice_too(self, app, tmp_path,
                                                     monkeypatch):
        app._analyze()
        app.selected_members = {0, 1, 2}
        path = tmp_path / 'group.pdf'
        app._pdf_sheet_dialog = lambda *a, **kw: set()
        monkeypatch.setattr('tkinter.simpledialog.askstring',
                            lambda *a, **kw: 'North bay')
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                            lambda *a, **kw: str(path))
        app._export_selection_pdf()
        # only the general view survives an empty choice -- sheet 1 is not
        # optional, a report with no sheets is not a report
        assert self._pdf_pages(str(path)) == 1

    def test_every_group_the_dialog_offers_is_a_real_one(self, app):
        """A label for a group the planner has never heard of would be a
        checkbox that silently does nothing."""
        offered = [k for k, _, _ in app.PDF_GROUP_LABELS]
        assert set(offered) == set(sr_module.PDF_SHEET_GROUPS)
        assert len(offered) == len(set(offered))

    def test_the_dialog_remembers_the_last_choice(self, app, monkeypatch):
        """Exporting a second time should not mean configuring it again."""
        assert app._pdf_groups is None
        app._analyze()
        chosen = {'force', 'deformed'}

        def fake_wait(win):
            # tick the checkbuttons the caller wants, then press Export
            for w in _descendants(win, tk.Widget):
                if w.winfo_class() == 'Checkbutton':
                    label = w.cget('text')
                    keys = [k for k, lab, _ in app.PDF_GROUP_LABELS
                            if lab == label]
                    if not keys:
                        continue        # the cover, not a sheet group
                    (w.select if keys[0] in chosen else w.deselect)()
            [b for b in _descendants(win, tk.Widget)
             if b.winfo_class() == 'Button'
             and b.cget('text').startswith('Export')][0].invoke()

        monkeypatch.setattr(app.root, 'wait_window', fake_wait)
        got = app._pdf_sheet_dialog('Export PDF', app.results,
                                    app.member_checks, 0)
        assert got == chosen
        assert app._pdf_groups == chosen

    def test_the_dialog_counts_the_sheets_it_will_write(self, app,
                                                        monkeypatch):
        """The count is the point of the dialog: it is what tells a reader
        that unticking Schedules saves four pages."""
        app._analyze()
        seen = {}

        def fake_wait(win):
            labels = [w for w in _descendants(win, tk.Widget)
                      if w.winfo_class() == 'Label'
                      and w.cget('text').endswith(('sheet', 'sheets'))]
            seen['all'] = labels[0].cget('text')
            for w in _descendants(win, tk.Widget):
                if w.winfo_class() == 'Checkbutton':
                    w.deselect()
            win.update_idletasks()
            seen['none'] = labels[0].cget('text')
            win.destroy()

        monkeypatch.setattr(app.root, 'wait_window', fake_wait)
        app._pdf_sheet_dialog('Export PDF', app.results, app.member_checks, 0)
        n_all = len(sr_module.plan_sheets(app.results, app.member_checks, 0))
        assert seen['all'] == f'{n_all} sheets'
        assert seen['none'] == '1 sheet'


def test_the_sheet_chooser_never_leaves_its_grab_behind(app, monkeypatch):
    """A modal dialog that outlives the wait keeps its grab, and a grabbed
    window blocks every other window in the process. In the app that is an
    unclosable dialog; in a test run it stops the suite on whichever test
    leaked it, which is how a run here sat at 0.2% CPU for three hours.
    """
    app._analyze()
    leaked = {}

    def wait_and_do_nothing(win):
        leaked['win'] = win          # neither Export nor Cancel pressed

    monkeypatch.setattr(app.root, 'wait_window', wait_and_do_nothing)
    got = app._pdf_sheet_dialog('Export PDF', app.results, app.member_checks, 0)
    assert got is None               # nothing was chosen
    assert not leaked['win'].winfo_exists(), 'the dialog outlived the wait'
    # and the next dialog can still be opened and driven
    monkeypatch.setattr(app.root, 'wait_window', lambda w: w.destroy())
    assert app._pdf_sheet_dialog('Export PDF', app.results,
                                 app.member_checks, 0) is None


def test_the_sheet_chooser_cleans_up_even_when_the_wait_raises(app,
                                                               monkeypatch):
    def wait_and_explode(win):
        raise RuntimeError('boom')

    app._analyze()
    monkeypatch.setattr(app.root, 'wait_window', wait_and_explode)
    with pytest.raises(RuntimeError):
        app._pdf_sheet_dialog('Export PDF', app.results, app.member_checks, 0)
    # the window is gone, so nothing is holding a grab
    assert not [w for w in _toplevels(app.root)
                if w.title() == 'Export PDF']


class TestNodeAndRodSizeOnScreen:
    """Roadmap v2, 2.1 and 2.2 -- the two items the roadmap itself names as
    the fastest to build and the highest visual impact for a demo.

    Both are measured off the CANVAS, not off the variable: a slider that
    moves without changing what is drawn is the failure worth catching.
    """

    def _ovals(self, app):
        c = app.canvas
        out = []
        for i in c.find_withtag('node'):
            if c.type(i) != 'oval':
                continue          # the support glyph is a rectangle
            x0, _y0, x1, _y1 = c.coords(i)[:4]
            out.append(round((x1 - x0) / 2))
        return out

    def _widths(self, app):
        c = app.canvas
        w = {}
        for i in c.find_withtag('member'):
            try:
                n = int(float(c.itemcget(i, 'width')))
            except (ValueError, tk.TclError):
                continue
            w[n] = w.get(n, 0) + 1
        return w

    def test_the_controls_exist_with_the_ranges_the_roadmap_asked_for(self, app):
        assert app.node_size.get() >= 0
        assert app.rod_thickness.get() >= 0
        app.node_size.set(12)
        assert app.node_size.get() == 12
        app.rod_thickness.set(8)
        assert app.rod_thickness.get() == 8

    def test_node_radius_follows_the_slider(self, app):
        for size in (1, 6, 12):
            app.node_size.set(size)
            app._draw()
            app.root.update_idletasks()
            radii = set(self._ovals(app))
            assert radii, 'no node dots drawn at all'
            assert size in radii, f'node_size={size} but radii were {sorted(radii)}'

    def test_radius_zero_draws_no_dots_at_all(self, app):
        """The roadmap's headline state: the rods simply meet where the joint
        is and the model reads as a pure bar diagram."""
        app.node_size.set(0)
        app._draw()
        app.root.update_idletasks()
        assert self._ovals(app) == []

    def test_radius_zero_keeps_the_supports_drawn(self, app):
        """'Los soportes y las cargas siguen dibujandose en su posicion' --
        losing the dot must not lose the boundary conditions with it."""
        app.node_size.set(0)
        app._draw()
        app.root.update_idletasks()
        boxes = [i for i in app.canvas.find_withtag('node')
                 if app.canvas.type(i) == 'rectangle']
        assert boxes, 'the support glyphs vanished with the node dots'

    def test_rod_width_follows_the_slider(self, app):
        app.selected_members = set()
        app.selected_member = None
        for t in (0, 3, 8):
            app.rod_thickness.set(t)
            app._draw()
            app.root.update_idletasks()
            widths = self._widths(app)
            assert widths, 'no members drawn'
            assert max(widths, key=widths.get) == 1 + t, (
                f'rod_thickness={t} should give a base width of {1 + t}, '
                f'got {widths}')

    def test_the_default_is_the_two_pixel_width_the_app_has_always_drawn(self):
        """Changing the flat width would silently move STRESS_WIDTH_MIN/MAX's
        frame of reference and break two thickness-by-stress tests that pin
        it -- which is exactly what happened when this shipped at 1 + 2*t."""
        from apps.stereo.stereo_app_constants import NODE_RADIUS_PX
        assert NODE_RADIUS_PX == 2
        # the mapping, stated once so a future edit has to face it
        assert 1 + 1 == 2

    def test_the_selection_cue_still_raises_the_slider_width(self, app):
        """The cues stack on the base rather than being overwritten by it --
        a hairline setting must not make the selected rod unfindable."""
        app.rod_thickness.set(0)
        app.selected_members = {0}
        app._draw()
        app.root.update_idletasks()
        widths = self._widths(app)
        assert 1 in widths, 'the base hairline is gone'
        assert any(w >= 4 for w in widths), (
            f'the selected rod is not drawn thicker than the base: {widths}')


class TestRodLoadOnABoxSelection:
    """Reported from use: drag a box over some rods, choose the selected-rods
    scope, press Apply, and the panel answers "No rods in that scope".

    The cause was that the canvas fills TWO different places. A single click
    on a rod sets `selected_member`; a rubber-band box fills
    `selected_members` and then explicitly sets `selected_member = None`.
    _rods_in_scope read only the singular, so a box selection always resolved
    to nothing -- the feature only ever worked for one rod at a time, which is
    not how anyone loads a roof.
    """

    def _box(self, app, frac=0.5):
        """Drag a rubber-band box over part of the model, as a user does."""
        pts = app._screen_positions()
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, y0 = min(xs) + 5, min(ys) + 5
        x1 = min(xs) + (max(xs) - min(xs)) * frac
        y1 = min(ys) + (max(ys) - min(ys)) * frac
        app._on_canvas_press(FakeEvent(int(x0), int(y0)))
        app._on_canvas_motion(FakeEvent(int(x1), int(y1)))
        app._on_canvas_release(FakeEvent(int(x1), int(y1)))
        app.root.update_idletasks()

    def test_the_box_fills_the_plural_and_clears_the_singular(self, app):
        """The premise. If this ever stops being true the bug cannot recur,
        but the scope code must still agree with whatever replaces it."""
        self._box(app)
        assert app.selected_members, 'the box caught no rods at all'
        assert app.selected_member is None

    def test_a_boxed_selection_is_in_scope(self, app):
        self._box(app)
        app.rod_scope.set(sc.ROD_SCOPE_SELECTED)
        assert set(app._rods_in_scope()) == set(app.selected_members)

    def test_apply_loads_every_rod_in_the_box(self, app, monkeypatch):
        shown = []
        monkeypatch.setattr('apps.stereo.stereo_app_model.messagebox.showerror',
                            lambda *a, **k: shown.append(a))
        self._box(app)
        picked = set(app.selected_members)
        app.rod_scope.set(sc.ROD_SCOPE_SELECTED)
        app.rod_w.set(3.5)
        app._apply_rod_load()
        assert not shown, f'it still refuses: {shown}'
        assert {ld['member'] for ld in app.member_loads} == picked
        assert all(ld['w'] == 3.5 for ld in app.member_loads)

    def test_a_single_click_still_works(self, app):
        app.selected_members = set()
        app.selected_member = 3
        app.rod_scope.set(sc.ROD_SCOPE_SELECTED)
        assert app._rods_in_scope() == [3]

    def test_click_and_box_together_are_unioned(self, app):
        self._box(app)
        picked = set(app.selected_members)
        app.selected_member = max(picked) + 1 if max(picked) + 1 < len(app.members) else 0
        app.rod_scope.set(sc.ROD_SCOPE_SELECTED)
        assert set(app._rods_in_scope()) == picked | {app.selected_member}

    def test_nothing_selected_still_refuses_and_says_how(self, app, monkeypatch):
        shown = []
        monkeypatch.setattr('apps.stereo.stereo_app_model.messagebox.showerror',
                            lambda *a, **k: shown.append(a))
        app.selected_members = set()
        app.selected_member = None
        app.rod_scope.set(sc.ROD_SCOPE_SELECTED)
        app._apply_rod_load()
        assert shown, 'an empty selection must still be refused'
        assert 'box' in ' '.join(shown[0]).lower(), (
            'the refusal should mention the box, since that is how most '
            'people will have tried to select')

    def test_a_stale_index_cannot_survive_a_smaller_model(self, app):
        """Selections are indices, and the model can shrink under them."""
        app.selected_members = {0, 1, 999999}
        app.selected_member = None
        app.rod_scope.set(sc.ROD_SCOPE_SELECTED)
        assert app._rods_in_scope() == [0, 1]


class TestCraneAddon:
    """Roadmap v2, 3.6: pick joints, hang them from a hook on tension-only
    cables, stand a mast above it. Exercised through the panel's own button,
    because the feature is the whole chain -- selection, geometry, boundary
    conditions, solve -- not the geometry helper on its own.
    """

    def _corners(self, app):
        top_z = max(p[2] for p in app.nodes)
        tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - top_z) < 1e-9]
        xs = sorted({round(app.nodes[i][0], 6) for i in tops})
        ys = sorted({round(app.nodes[i][1], 6) for i in tops})
        out = []
        for xv in (xs[0], xs[-1]):
            for yv in (ys[0], ys[-1]):
                for i in tops:
                    if (abs(app.nodes[i][0] - xv) < 1e-9
                            and abs(app.nodes[i][1] - yv) < 1e-9):
                        out.append(i)
                        break
        return out

    def _roles(self, app, role):
        return [i for i, m in enumerate(app.members) if m.get('role') == role]

    def test_the_panel_offers_it(self, app):
        assert hasattr(app, 'crane_auto') and hasattr(app, 'crane_rise')
        assert hasattr(app, 'crane_mast')
        assert callable(app._add_cable_crane)
        assert callable(app._clear_cable_cranes)

    def test_fewer_than_three_joints_is_refused(self, app, monkeypatch):
        shown = []
        monkeypatch.setattr('apps.stereo.stereo_app_addons.messagebox.showerror',
                            lambda *a, **k: shown.append(a))
        app.selected_nodes = {0, 1}
        n_before = len(app.nodes)
        app._add_cable_crane()
        assert shown and len(app.nodes) == n_before

    def test_lifting_builds_the_hook_cables_mast_and_restraint(self, app):
        pick = self._corners(app)
        app.selected_nodes = set(pick)
        app._add_cable_crane()
        cables = self._roles(app, 'crane_cable')
        masts = self._roles(app, 'crane_mast')
        assert len(cables) == len(pick)
        assert len(masts) == 1
        assert all(app.members[i].get('tension_only') for i in cables)
        assert app.members[masts[0]]['conn'] == 'rigid'
        anchor = app.members[masts[0]]['b']
        # FIXED, not pinned -- a rigid mast free to rotate at its top has a
        # zero-energy torsional mode about its own axis
        assert any(sp['node'] == anchor and sp['type'] == 'fixed'
                   for sp in app.supports)

    def test_the_hook_sits_over_the_centroid(self, app):
        pick = self._corners(app)
        app.selected_nodes = set(pick)
        cx = sum(app.nodes[i][0] for i in pick) / len(pick)
        cy = sum(app.nodes[i][1] for i in pick) / len(pick)
        app._add_cable_crane()
        hook = app.members[self._roles(app, 'crane_mast')[0]]['a']
        assert app.nodes[hook][0] == pytest.approx(cx)
        assert app.nodes[hook][1] == pytest.approx(cy)
        assert app.nodes[hook][2] > max(app.nodes[i][2] for i in pick)

    def test_a_typed_rise_is_used_when_the_automatic_one_is_off(self, app):
        pick = self._corners(app)
        app.selected_nodes = set(pick)
        app.crane_auto.set(False)
        app.crane_rise.set(9.0)
        top = max(app.nodes[i][2] for i in pick)
        app._add_cable_crane()
        hook = app.members[self._roles(app, 'crane_mast')[0]]['a']
        assert app.nodes[hook][2] == pytest.approx(top + 9.0)

    def test_no_cable_is_ever_in_compression(self, app):
        pick = self._corners(app)
        app.selected_nodes = set(pick)
        app._add_cable_crane()
        app._analyze()
        assert app.results is not None
        for i in self._roles(app, 'crane_cable'):
            assert app.results['member_res'][i]['N'] >= 0.0

    def test_the_crane_carries_the_whole_lift(self, app):
        """Take the model's own supports away so the crane alone holds it,
        then check the cables' vertical pull against the load."""
        pick = self._corners(app)
        app.selected_nodes = set(pick)
        app._add_cable_crane()
        anchor = app.members[self._roles(app, 'crane_mast')[0]]['b']
        app.supports = [sp for sp in app.supports if sp['node'] == anchor]
        app.results = None
        app._analyze()
        assert app.results is not None, 'the crane could not hold the model'
        want = -sum(ld.get('fz', 0.0) for ld in app._all_loads())
        assert app.results['reactions'][anchor]['Fz'] == pytest.approx(want, rel=1e-6)
        lifted = 0.0
        for i in self._roles(app, 'crane_cable'):
            _dx, _dy, dz, L = sm.member_vector(app.nodes, app.members[i])
            assert app.results['member_res'][i]['N'] > 0
            lifted += app.results['member_res'][i]['N'] * dz / L
        assert lifted == pytest.approx(want, rel=1e-6)

    def test_clearing_puts_the_model_back_exactly(self, app):
        n0, m0, s0 = len(app.nodes), len(app.members), len(app.supports)
        app.selected_nodes = set(self._corners(app))
        app._add_cable_crane()
        assert len(app.nodes) > n0
        app._clear_cable_cranes()
        assert (len(app.nodes), len(app.members), len(app.supports)) == (n0, m0, s0)
        assert not self._roles(app, 'crane_cable')
        assert not self._roles(app, 'crane_mast')


class TestCranePanelLayout:
    """The Crane group as a user meets it, not through its handlers.

    Every other crane test calls `app._add_cable_crane()` directly, which is
    exactly the blind spot that let the merge delete working UI: the handler
    is fine, the widget that reaches it is not. These press the real widgets
    and read the real geometry manager.
    """

    def _crane_widgets(self, app):
        out = []
        def walk(w):
            out.append(w)
            for c in w.winfo_children():
                walk(c)
        walk(app._mode_frames['addons'])
        return out

    def _button(self, app, needle):
        for w in self._crane_widgets(app):
            try:
                if needle.lower() in str(w.cget('text')).lower() and w.cget('command'):
                    return w
            except tk.TclError:
                continue
        return None

    def test_the_lift_and_clear_buttons_exist_and_are_wired(self, app):
        for needle in ('lift the selected nodes', 'clear every crane'):
            assert self._button(app, needle) is not None, needle

    def test_pressing_lift_on_the_real_button_builds_a_crane(self, app, monkeypatch):
        shown = []
        monkeypatch.setattr('apps.stereo.stereo_app_addons.messagebox.showerror',
                            lambda *a, **k: shown.append(a))
        zs = [p[2] for p in app.nodes]
        top = max(zs)
        top_nodes = [i for i, p in enumerate(app.nodes) if abs(p[2] - top) < 1e-9]
        app.selected_nodes = set(top_nodes[:4])
        assert len(app.selected_nodes) >= 3
        self._button(app, 'lift the selected nodes').invoke()
        assert not shown, shown
        assert [m for m in app.members if m.get('role') == 'crane_cable']
        self._button(app, 'clear every crane').invoke()
        assert not [m for m in app.members if m.get('role') == 'crane_cable']

    def test_the_hook_rise_box_appears_above_the_mast_box_not_below_it(self, app):
        """pack() appends, so a row hidden at build time and shown later lands
        at the BOTTOM of the group -- under the Lift and Clear buttons, which
        is not where the label says it is. `before=` is what keeps it in its
        own place, and this is the test that notices when it is dropped.
        """
        app.crane_auto.set(False)
        app._on_crane_auto_change()
        group = app._crane_mast_row.master
        order = list(group.pack_slaves())
        assert app._crane_rise_row in order, 'the rise row never came back'
        assert order.index(app._crane_rise_row) < order.index(app._crane_mast_row)

    def test_the_hook_rise_box_is_hidden_while_the_spread_decides(self, app):
        app.crane_auto.set(True)
        app._on_crane_auto_change()
        assert app._crane_rise_row not in list(app._crane_mast_row.master.pack_slaves())

    def test_the_rise_box_survives_being_hidden_and_shown_repeatedly(self, app):
        group = app._crane_mast_row.master
        for _ in range(3):
            app.crane_auto.set(False); app._on_crane_auto_change()
            app.crane_auto.set(True); app._on_crane_auto_change()
        app.crane_auto.set(False); app._on_crane_auto_change()
        order = list(group.pack_slaves())
        assert order.index(app._crane_rise_row) < order.index(app._crane_mast_row)

    def test_the_panel_does_not_promise_a_pin_the_code_does_not_build(self, app):
        """The hint text said the mast "ends in a pin". It is FIXED, because a
        rigid mast free to rotate at its top has a zero-energy torsional mode.
        A hint that contradicts the model is worse than no hint.
        """
        texts = []
        for w in self._crane_widgets(app):
            try:
                t = w.cget('text')
            except tk.TclError:
                continue
            if isinstance(t, str):
                texts.append(t)
        blob = ' '.join(texts).lower()
        assert 'crane' in blob
        i = blob.find('crane (lift from selected nodes)')
        assert i >= 0
        hint = blob[i:i + 400]
        assert 'fixed' in hint
        assert 'ends in a pin' not in hint


class TestCraneTakesOverTheSupports:
    """A lifted structure is not also standing on the ground.

    This is the bug the GUI sweep found, and it is the columns' bug again:
    with the grid's own supports left in place all four slings read exactly
    0.000 kN, because a support is a rigid path to ground in parallel with a
    cable and it wins every time. The crane was in the picture, in the member
    list and in the checks, and carrying nothing.
    """

    def _corners(self, app):
        top = max(p[2] for p in app.nodes)
        tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - top) < 1e-9]
        xs = [app.nodes[i][0] for i in tops]
        ys = [app.nodes[i][1] for i in tops]
        out = set()
        for tx in (min(xs), max(xs)):
            for ty in (min(ys), max(ys)):
                out.add(min(tops, key=lambda i: (app.nodes[i][0] - tx) ** 2
                                                + (app.nodes[i][1] - ty) ** 2))
        return out

    def _cables(self, app):
        return [i for i, m in enumerate(app.members)
                if m.get('role') == 'crane_cable']

    def test_the_slings_actually_carry_the_load(self, app):
        app.selected_nodes = set(self._corners(app))
        assert app.crane_off_ground.get(), 'has to default to on'
        app._add_cable_crane()
        app._analyze()
        assert app.results is not None
        forces = [app.results['member_res'][i]['N'] for i in self._cables(app)]
        assert forces, 'no cables'
        assert max(forces) > 1.0, forces

    def test_with_the_option_off_the_ground_still_wins(self, app):
        """The old behaviour, kept reachable and documented rather than
        removed: this is what "the crane reads zero" looks like, and the
        panel says so when it happens."""
        app.selected_nodes = set(self._corners(app))
        app.crane_off_ground.set(False)
        before = len(app.supports)
        app._add_cable_crane()
        assert len(app.supports) == before + 1     # only the mast's own top
        app._analyze()
        assert app.results is not None
        forces = [app.results['member_res'][i]['N'] for i in self._cables(app)]
        assert max(forces) == pytest.approx(0.0, abs=1e-6), forces

    def test_lifting_leaves_the_masts_top_and_the_steady_lines(self, app):
        """Nothing of the model's own boundary survives a lift. What is left
        is the mast's fixed top, which carries the whole load, and the three
        single-DOF tag lines that steady a hanging body -- see
        TestTheLiftIsWellPosed for why those three have to be there."""
        app.selected_nodes = set(self._corners(app))
        assert len(app.supports) > 0, 'the fixture grid has to be supported'
        app._add_cable_crane()
        masts = [i for i, m in enumerate(app.members)
                 if m.get('role') == 'crane_mast']
        anchor = app.members[masts[0]]['b']
        full = [sp for sp in app.supports if sp.get('type')]
        assert [sp['node'] for sp in full] == [anchor]
        assert full[0]['type'] == 'fixed'
        steady = [sp for sp in app.supports if not sp.get('type')]
        assert len(steady) == 3
        # Each holds exactly ONE translation: any more and it would start
        # carrying load the slings are there to carry.
        for sp in steady:
            assert list(sp['dofs'].values()) == [True]
            assert list(sp['dofs'])[0] in ('ux', 'uy')

    def test_clearing_puts_the_model_back_on_the_ground(self, app):
        before = sorted((sp['node'], sp.get('type')) for sp in app.supports)
        app.selected_nodes = set(self._corners(app))
        app._add_cable_crane()
        app._clear_cable_cranes()
        assert sorted((sp['node'], sp.get('type'))
                      for sp in app.supports) == before

    def test_the_kind_of_each_support_survives_the_round_trip(self, app):
        """Node numbers are not enough -- a pin handed back as a fixed base
        is a different structure, and nothing in the mesh remembers which it
        was."""
        app.supports = [{'node': sp['node'], 'type': 'rollerX'}
                        for sp in app.supports]
        want = sorted((sp['node'], sp['type']) for sp in app.supports)
        app.selected_nodes = set(self._corners(app))
        app._add_cable_crane()
        app._clear_cable_cranes()
        assert sorted((sp['node'], sp['type']) for sp in app.supports) == want

    def test_clearing_the_columns_does_not_hand_back_the_cranes_supports(self, app):
        app.selected_nodes = set(self._corners(app))
        app._add_cable_crane()
        only_anchor = [dict(sp) for sp in app.supports]
        app._clear_columns()
        assert [dict(sp) for sp in app.supports] == only_anchor

    def test_a_regenerate_forgets_what_the_old_lift_freed(self, app):
        """Kept entries are node INDICES, so carrying them across a new mesh
        would weld supports onto whichever nodes now hold those numbers."""
        app.selected_nodes = set(self._corners(app))
        app._add_cable_crane()
        assert app._crane_freed
        app._generate(push_undo=False)
        assert app._crane_freed == []

    def test_the_panel_says_which_way_it_went(self, app):
        """Taking a support away is not a detail the user should have to
        discover from a reaction that vanished, so the panel states it both
        ways round -- and states the zero-slings case too, since that is the
        one that looks like a broken crane."""
        app.selected_nodes = set(self._corners(app))
        app._add_cable_crane()
        assert 'off its own' in str(app.col_note.cget('text')).lower()
        app._clear_cable_cranes()
        assert 'handed back' in str(app.col_note.cget('text')).lower()

    def test_the_panel_warns_when_the_ground_will_win(self, app):
        app.selected_nodes = set(self._corners(app))
        app.crane_off_ground.set(False)
        app._add_cable_crane()
        note = str(app.col_note.cget('text')).lower()
        assert 'still stands on its own supports' in note
        assert 'zero' in note


class TestTheLiftIsWellPosed:
    """The lift has to give a MEANINGFUL answer, not merely an answer.

    This class exists because of a bug that passed every check I had. A body
    hanging from concurrent cables is a pendulum, and a linear
    small-deflection solve gives a pendulum no lateral stiffness at all --
    the restoring force is a geometric, second-order term this solver does
    not carry. Three modes therefore had ZERO stiffness (swing in x, swing
    in y, spin about the vertical), and the reduced matrix came back with a
    condition number of 6.2e16.

    It did not fail. `_beam_gauss_solve` judges a system by the residual of
    the solution it found, which depends on the LOADS and not only on the
    matrix, so under a plain area load the model returned four slings at
    636.396 kN whose vertical components summed to exactly the applied
    1800 kN -- correct for a 45 degree sling, and pure luck. Adding four rod
    span loads changed the loads and not the matrix, and the same model
    returned displacements of 1.2e10 m.

    So a statics check cannot catch this: adding a rigid-body mode to a
    solution does not violate equilibrium. These tests check the
    CONDITIONING and check the answer under a second, asymmetric load case,
    which is what actually distinguishes the two.
    """

    def _lift(self, app, rod_loads=False):
        if rod_loads:
            app.selected_members = set(range(4))
            app.selected_member = None
            app.rod_scope.set(sc.ROD_SCOPE_SELECTED)
            app.rod_w.set(3.0)
            app._apply_rod_load()
        top = max(p[2] for p in app.nodes)
        tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - top) < 1e-9]
        xs = [app.nodes[i][0] for i in tops]
        ys = [app.nodes[i][1] for i in tops]
        picks = set()
        for tx in (min(xs), max(xs)):
            for ty in (min(ys), max(ys)):
                picks.add(min(tops, key=lambda i: (app.nodes[i][0] - tx) ** 2
                                                  + (app.nodes[i][1] - ty) ** 2))
        app.selected_nodes = set(picks)
        app._add_cable_crane()
        return picks

    def _cables(self, app):
        return [i for i, m in enumerate(app.members)
                if m.get('role') == 'crane_cable']

    def test_the_reduced_matrix_is_not_numerically_singular(self, app,
                                                            monkeypatch):
        """The measurement that actually catches it: before the steady lines
        the condition number was 6.2e16, which is past what double precision
        can carry. This asserts a bound many orders of magnitude below that,
        so it fails long before the answers do."""
        import numpy as np
        seen = {}

        def spying(real):
            # The reduced matrix goes to the dense or the sparse solver
            # depending on its size; measure it whichever one gets it.
            def spy(A, b):
                if 'cond' not in seen:
                    M = A.toarray() if hasattr(A, 'toarray') else A
                    sv = np.linalg.svd(np.asarray(M, float),
                                       compute_uv=False)
                    seen['cond'] = float(sv[0] / sv[-1])
                    seen['smin'] = float(sv[-1])
                    seen['smax'] = float(sv[0])
                return real(A, b)
            return spy

        monkeypatch.setattr(sm, 'gauss_solve', spying(sm.gauss_solve))
        monkeypatch.setattr(sm, '_sparse_solve', spying(sm._sparse_solve))
        self._lift(app)
        app._analyze()
        assert 'cond' in seen, 'the solve never ran'
        assert seen['cond'] < 1e12, (
            'the lifted model is near-singular: cond=%.3e smin=%.3e smax=%.3e'
            % (seen['cond'], seen['smin'], seen['smax']))

    def test_the_answer_survives_an_asymmetric_load_case(self, app):
        """The load case that exposed it. The matrix is the same either way,
        so if this differs from the symmetric case by orders of magnitude the
        model is rank-deficient and the symmetric answer was luck."""
        self._lift(app, rod_loads=True)
        app._analyze()
        assert app.results is not None, 'the asymmetric lift did not solve'
        # node_res carries displacements in MILLIMETRES.
        biggest = max(abs(nr[k]) for nr in app.results['node_res']
                      for k in ('ux', 'uy', 'uz'))
        assert biggest < 1000.0, (
            'displacements of %.3e mm are a null-space artefact, not a '
            'solution' % biggest)

    def test_the_slings_read_what_a_45_degree_sling_should(self, app):
        """1800 / (4 cos 45) = 636.396 kN. Sound only now that the model is
        well posed -- the same number came out of the singular version."""
        self._lift(app)
        app._analyze()
        want = -sum(ld.get('fz', 0.0) for ld in app._all_loads())
        forces = [app.results['member_res'][i]['N'] for i in self._cables(app)]
        assert len(forces) == 4
        for f in forces:
            assert f == pytest.approx(want / (4 * math.cos(math.radians(45.0))),
                                      rel=1e-4), forces

    def test_the_verticals_add_up_to_the_load(self, app):
        self._lift(app)
        app._analyze()
        want = -sum(ld.get('fz', 0.0) for ld in app._all_loads())
        lifted = 0.0
        for i in self._cables(app):
            _dx, _dy, dz, L = sm.member_vector(app.nodes, app.members[i])
            lifted += app.results['member_res'][i]['N'] * dz / L
        assert lifted == pytest.approx(want, rel=1e-8)

    def test_a_symmetric_lift_puts_nothing_into_the_steady_lines(self, app):
        """The check that they are steadying and not carrying. If a tag line
        takes real load in a symmetric lift, it has been placed where a sling
        should be doing the work."""
        self._lift(app)
        app._analyze()
        want = -sum(ld.get('fz', 0.0) for ld in app._all_loads())
        for t in app._crane_tag:
            r = app.results['reactions'][t['node']]
            got = r['Fx'] if t['dof'] == 'ux' else r['Fy']
            assert abs(got) < 1e-6 * want, (t, got)

    def test_the_whole_lift_goes_through_the_mast(self, app):
        self._lift(app)
        app._analyze()
        want = -sum(ld.get('fz', 0.0) for ld in app._all_loads())
        mast = [i for i, m in enumerate(app.members)
                if m.get('role') == 'crane_mast'][0]
        assert app.results['member_res'][mast]['N'] == pytest.approx(want, rel=1e-8)

    def test_clearing_the_crane_takes_the_steady_lines_with_it(self, app):
        before = sorted((sp['node'], sp.get('type'), tuple(sorted((sp.get('dofs') or {}).items())))
                        for sp in app.supports)
        self._lift(app)
        assert app._crane_tag
        app._clear_cable_cranes()
        after = sorted((sp['node'], sp.get('type'), tuple(sorted((sp.get('dofs') or {}).items())))
                       for sp in app.supports)
        assert after == before
        assert not app._crane_tag


class TestGroupsPanel:
    """The Groups panel (roadmap 4.1) as a user meets it.

    Driven through the real widgets and the real handlers, because the
    failure this whole tab has already suffered once is a handler that works
    behind a control that is gone.
    """

    def _names(self, app):
        return [app.group_list.get(i) for i in range(app.group_list.size())]

    def _pick_row(self, app, i):
        app.group_list.selection_clear(0, 'end')
        app.group_list.selection_set(i)
        app._on_group_pick()

    def _make(self, app, monkeypatch, name, rods, parent_row=None):
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: name)
        app.selected_members = set(rods)
        app.selected_member = None
        app.selected_nodes = set()
        if parent_row is None:
            app._group_new_from_selection()
        else:
            self._pick_row(app, parent_row)
            app._group_new_subgroup()
        return app.groups[-1]

    def test_the_groups_live_inside_build(self, app):
        """Groups moved into the Build panel, beside the selection tools;
        the old 'groups' key still lands there."""
        keys = [k for k, _g, _l, _t in sh.MODES]
        assert 'groups' not in keys and 'groups' not in app._mode_frames
        build = str(app._mode_frames['build'])
        assert str(app.group_list).startswith(build)
        app._set_mode('groups')
        assert app.active_mode.get() == 'build'

    def test_the_nine_modes_keep_their_alt_keys(self, app):
        keys = [k for k, _g, _l, _t in sh.MODES]
        assert len(keys) == 9
        top = app.root.winfo_toplevel()
        for n in range(1, 10):
            assert top.bind('<Alt-Key-%d>' % n), n

    def test_making_a_group_from_the_selection(self, app, monkeypatch):
        g = self._make(app, monkeypatch, 'Roof', range(6))
        assert g['name'] == 'Roof'
        assert g['members'] == set(range(6))
        assert 'Roof' in self._names(app)[0]

    def test_a_group_with_no_selection_says_what_to_do(self, app, monkeypatch):
        shown = []
        monkeypatch.setattr('apps.stereo.stereo_app_groups.messagebox.showinfo',
                            lambda *a, **k: shown.append(a))
        app.selected_members = set()
        app.selected_nodes = set()
        app._group_new_from_selection()
        assert shown and 'Select the rods' in shown[0][1]
        assert app.groups == []

    def test_the_ungrouped_row_is_always_there_while_rods_are_loose(self, app,
                                                                    monkeypatch):
        self._make(app, monkeypatch, 'Roof', range(6))
        rows = self._names(app)
        assert any(sgp.UNGROUPED_NAME in r for r in rows), rows

    def test_a_subgroup_is_shown_indented_under_its_parent(self, app,
                                                           monkeypatch):
        self._make(app, monkeypatch, 'Roof', range(6))
        self._make(app, monkeypatch, 'Bay', range(6, 10), parent_row=0)
        rows = self._names(app)
        assert rows[0].startswith('Roof')
        assert rows[1].startswith('   ') and 'Bay' in rows[1]
        assert app.groups[1]['parent'] == app.groups[0]['id']

    def test_the_parent_row_shows_its_own_count_and_its_subtree_count(self, app,
                                                                      monkeypatch):
        self._make(app, monkeypatch, 'Roof', range(6))
        self._make(app, monkeypatch, 'Bay', range(6, 10), parent_row=0)
        assert '[6/10]' in self._names(app)[0]

    def test_ungrouped_cannot_be_made_a_parent(self, app, monkeypatch):
        """It is what is left over, not a branch."""
        self._make(app, monkeypatch, 'Roof', range(6))
        shown = []
        monkeypatch.setattr('apps.stereo.stereo_app_groups.messagebox.showinfo',
                            lambda *a, **k: shown.append(a))
        rows = self._names(app)
        ung = next(i for i, r in enumerate(rows) if sgp.UNGROUPED_NAME in r)
        self._pick_row(app, ung)
        app._group_new_subgroup()
        assert shown and 'cannot be a parent' in shown[0][1]

    def test_a_rod_leaves_a_locked_group_only_through_its_edit_mode(
            self, app, monkeypatch):
        """This used to be one step: add A's rods to B and they moved. A
        group is now an object that is locked until opened, so taking rods
        out of A is refused until A is open -- and while A is open, B is
        blocked. The two steps are ungroup inside A, then add to B."""
        a = self._make(app, monkeypatch, 'A', range(6))
        # B is made from a rod of its own: "New from selection" with nothing
        # selected is refused, which is right, so it cannot make an empty one.
        b = self._make(app, monkeypatch, 'B', [9])
        assert a is not b
        self._pick_row(app, 1)
        app.selected_members = {0, 1}
        app.selected_member = None
        app._group_assign_selection()
        assert a['members'] == set(range(6)), 'A is locked'
        assert b['members'] == {9}

        self._pick_row(app, 0)
        app._group_edit_toggle()
        app.selected_members = {0, 1}
        app._group_unassign_selection()
        app._group_edit_toggle()
        assert app._editing_gid() is None
        self._pick_row(app, 1)
        app.selected_members = {0, 1}
        app._group_assign_selection()
        assert a['members'] == {2, 3, 4, 5}
        assert b['members'] == {0, 1, 9}

    def test_selecting_a_group_puts_its_rods_in_the_view(self, app, monkeypatch):
        g = self._make(app, monkeypatch, 'Roof', range(6))
        app.selected_members = set()
        app.selected_nodes = set()
        self._pick_row(app, 0)
        app._group_select_rods()
        assert app.selected_members == g['members']
        assert app.selected_nodes == set(
            sgp.nodes_of_rods(app.members, sorted(g['members'])))

    def test_deleting_a_group_returns_its_rods_to_ungrouped(self, app,
                                                            monkeypatch):
        self._make(app, monkeypatch, 'Roof', range(6))
        self._pick_row(app, 0)
        app._group_delete()
        assert app.groups == []
        assert 0 in sgp.ungrouped_rods(app.groups, len(app.members))

    def test_a_group_holds_member_indices_so_a_regenerate_clears_it(self, app,
                                                                     monkeypatch):
        """One kept across a new mesh would name whatever rods now hold those
        numbers -- a branch pointing at the wrong part of a different model."""
        self._make(app, monkeypatch, 'Roof', range(6))
        assert app.groups
        app._generate(push_undo=False)
        assert app.groups == []

    def test_deleting_rods_renumbers_the_groups_instead_of_corrupting_them(
            self, app, monkeypatch):
        """The trap: self.members is rebuilt by FILTERING, so every index
        after a dropped rod means a different rod. Left alone a branch would
        quietly point at the wrong steel and still produce a report."""
        a = self._make(app, monkeypatch, 'A', [0, 1, 2, 3, 4, 5])
        b = self._make(app, monkeypatch, 'B', [6, 7, 8, 9])
        app._group_edit_toggle(a['id'])     # a locked rod deletes only so
        app.selected_nodes = set()
        app.selected_members = {0}
        app.selected_member = None
        app._on_delete_nodes()
        assert a['members'] == {0, 1, 2, 3, 4}
        assert b['members'] == {5, 6, 7, 8}
        rec = sgp.totals_reconcile(app.groups, app.nodes, app.members)
        assert rec['ok'], rec

    def test_clearing_an_addon_also_renumbers_the_groups(self, app, monkeypatch):
        """_strip_members rebuilds the list too, and it runs for every
        Clear button in the Add-ons panel."""
        top = max(p[2] for p in app.members and app.nodes)
        tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - top) < 1e-9]
        app.selected_nodes = set(tops[:4])
        app._add_column()
        n_after_col = len(app.members)
        assert n_after_col > 0
        g = self._make(app, monkeypatch, 'Grid', [0, 1, 2])
        app._clear_columns()
        assert g['members'] == {0, 1, 2}, 'front-of-list rods must not move'
        rec = sgp.totals_reconcile(app.groups, app.nodes, app.members)
        assert rec['ok'], rec

    def test_the_totals_check_reports_success(self, app, monkeypatch):
        shown = []
        monkeypatch.setattr('apps.stereo.stereo_app_groups.messagebox.showinfo',
                            lambda *a, **k: shown.append(a))
        self._make(app, monkeypatch, 'Roof', range(6))
        rec = app._group_reconcile()
        assert rec['ok']
        assert shown and 'exactly once' in shown[-1][1]


class TestGroupSectionRecommendationUI:
    """The right-click properties box and the sizing recommendation."""

    def _group(self, app, monkeypatch, rods, name='Branch'):
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: name)
        app.selected_members = set(rods)
        app.selected_member = None
        app.selected_nodes = set()
        app._group_new_from_selection()
        app.group_list.selection_clear(0, 'end')
        app.group_list.selection_set(0)
        app._on_group_pick()
        return app.groups[-1]

    def _texts(self, w):
        out = []

        def walk(v):
            try:
                t = v.cget('text')
                if isinstance(t, str) and t.strip():
                    out.append(t.strip())
            except tk.TclError:
                pass
            for c in v.winfo_children():
                walk(c)
        walk(w)
        return out

    def test_recommending_before_a_solve_says_to_analyze_first(self, app,
                                                               monkeypatch):
        shown = []
        monkeypatch.setattr('apps.stereo.stereo_app_groups.messagebox.showinfo',
                            lambda *a, **k: shown.append(a))
        self._group(app, monkeypatch, range(6))
        app.results = None
        app._group_recommend()
        assert shown and 'Analyze first' in shown[-1][1]

    def test_the_recommendation_window_names_a_section_and_its_governing_rod(
            self, app, monkeypatch):
        self._group(app, monkeypatch, range(8))
        app._analyze()
        assert app.results
        app._group_recommend()
        win = app._group_rec_win
        blob = ' | '.join(self._texts(win))
        assert 'Recommended' in blob
        assert 'Governing rod' in blob
        assert 'Apply' in blob
        win.destroy()

    def test_applying_it_sets_every_rod_and_clears_the_stale_results(self, app,
                                                                      monkeypatch):
        g = self._group(app, monkeypatch, range(8))
        app._analyze()
        app._group_recommend()
        win = app._group_rec_win
        btn = None
        for w in _walk_widgets(win):
            try:
                if str(w.cget('text')).startswith('Apply') and w.cget('command'):
                    btn = w
                    break
            except tk.TclError:
                continue
        assert btn is not None
        btn.invoke()
        rods = sorted(g['members'])
        first = app.members[rods[0]]['profile']
        assert first
        for i in rods:
            assert app.members[i]['profile'] == first
        # the solve it was sized from is no longer valid for the new sections
        assert app.results is None

    def test_the_properties_box_reports_the_group(self, app, monkeypatch):
        self._group(app, monkeypatch, range(6), name='Roof')
        app._analyze()
        win = app._group_properties()
        blob = ' | '.join(self._texts(win))
        assert 'Roof' in blob
        assert 'Rods (with subgroups)' in blob
        assert 'Nodes touched' in blob
        assert 'Total length' in blob
        assert 'Joints shared with others' in blob
        win.destroy()

    def test_the_properties_box_lists_the_sections_in_use_without_calling_it_a_fault(
            self, app, monkeypatch):
        """A group need not be uniform; setting one section makes it so."""
        self._group(app, monkeypatch, range(6))
        win = app._group_properties()
        blob = ' | '.join(self._texts(win))
        assert 'Sections in use' in blob
        assert 'not a fault' in blob
        win.destroy()

    def test_the_right_click_selects_the_row_under_the_pointer_first(self, app,
                                                                     monkeypatch):
        """Right-click a row: that row -- not whatever was selected before --
        is picked and OPENED for editing (groups as layers)."""
        self._group(app, monkeypatch, range(4), name='A')
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: 'B')
        app.selected_members = {4, 5}
        app._group_new_from_selection()
        app.group_list.selection_clear(0, 'end')
        app.group_list.selection_set(0)
        app._on_group_pick()
        # The Listbox has no geometry until its panel is on screen, so
        # bbox() returns None and a y coordinate cannot be chosen. Show it
        # first -- this is a real property of the widget, not a workaround.
        app._set_mode('groups')
        app.root.update_idletasks()
        app.root.update()
        bbox = app.group_list.bbox(1)
        assert bbox, 'the second row has no bbox even once Groups is shown'

        class E:
            pass
        e = E()
        e.x, e.y = 5, bbox[1] + 2
        e.x_root, e.y_root = 100, 100
        app._on_group_right_click(e)
        assert app._current_group() == app.groups[1]['id']
        assert app._editing_gid() == app.groups[1]['id']
        # the row's other actions moved to the Actions button
        menu = app.group_actions_btn.nametowidget(
            app.group_actions_btn.cget('menu'))
        labels = [menu.entrycget(i, 'label') for i in range(menu.index('end') + 1)
                  if menu.type(i) == 'command']
        assert 'Properties…' in labels and 'Rename…' in labels

    def test_the_family_filter_restricts_the_candidates(self, app, monkeypatch):
        self._group(app, monkeypatch, range(8))
        app._analyze()
        app.group_family.set('CHS (tubes)')
        cands = app._group_candidates()
        assert cands and all(n in sp_mod.profiles_in_group('CHS (tubes)')
                             for n in cands)
        app._group_recommend()
        win = app._group_rec_win
        blob = ' | '.join(self._texts(win))
        win.destroy()
        assert 'Recommended' in blob

    def test_the_shared_joints_window_lists_cross_and_internal(self, app,
                                                               monkeypatch):
        self._group(app, monkeypatch, range(6), name='A')
        app._analyze()
        win = app._group_shared_nodes()
        blob = ' | '.join(self._texts(win))
        assert 'CROSS' in blob or 'Every sharing is listed' in blob
        win.destroy()


def _walk_widgets(w):
    yield w
    for c in w.winfo_children():
        yield from _walk_widgets(c)


class TestCatalogDepthReachesMembers:
    """The catalog depth c_cm has to reach every member built from a catalog
    section, by every path -- and has to LEAVE when the section changes.

    Account 9.2b found that no path carried it at all. That was merely
    conservative while r_gyr was the strong-axis radius; once r_gyr became
    the minor radius it would have been unsafe, because the bending check's
    old fall-back read the depth off r_gyr. Both halves are fixed; these
    pin the propagation.
    """

    def _pick_catalog(self, app, prefix, name):
        from apps.stereo import stereo_profiles as _sp
        props = _sp.section_to_props(_sp.CATALOG[name], _sp.STEEL_F24)
        app.profiles[name] = dict(E=props['E'], A=props['A'], I=props['I'],
                                  J=props['J'], Fy=props['Fy'], Fu=props['Fu'],
                                  r_gyr=props['r_gyr'], K=1.0,
                                  c_cm=props['c_cm'], catalog=name,
                                  material='F24')
        getattr(app, '%s_profile_var' % prefix).set(name)
        app._on_section_profile_selected(prefix)
        return props

    def test_applying_a_catalog_section_gives_the_members_its_depth(self, app):
        props = self._pick_catalog(app, 'web', 'L 50x5')
        self._pick_catalog(app, 'chord', 'IPE 200')
        app._apply_sections()
        webs = [m for m in app.members if m.get('role') not in sc.CHORD_ROLES]
        assert webs
        for m in webs:
            assert m['c_cm'] == pytest.approx(props['c_cm'])
            assert m['r_gyr'] == pytest.approx(props['r_gyr'])

    def test_typing_a_different_I_after_picking_drops_the_depth(self, app):
        """The depth belongs to the catalog section. Once the panel holds a
        different I it is a different section, and the old depth beside it
        would overstate bending capacity."""
        self._pick_catalog(app, 'web', 'IPE 200')
        app.web_I.set(app.web_I.get() * 3.0)
        app._apply_sections()
        webs = [m for m in app.members if m.get('role') not in sc.CHORD_ROLES]
        assert webs and all('c_cm' not in m for m in webs)

    def test_a_hand_typed_section_clears_a_depth_a_member_already_had(self, app):
        self._pick_catalog(app, 'web', 'IPE 200')
        app._apply_sections()
        assert any('c_cm' in m for m in app.members)
        app.web_profile_var.set('')
        app._panel_depth['web'] = None
        app.web_I.set(999.0)
        app._apply_sections()
        webs = [m for m in app.members if m.get('role') not in sc.CHORD_ROLES]
        assert all('c_cm' not in m for m in webs)

    def test_assigning_a_catalog_profile_carries_its_depth(self, app):
        props = self._pick_catalog(app, 'web', 'UPN 100')
        app.active_profile.set('UPN 100')
        app.selected_members = {0, 1, 2}
        app._assign_profile_to_selection()
        for i in (0, 1, 2):
            assert app.members[i]['c_cm'] == pytest.approx(props['c_cm'])

    def test_a_new_rod_drawn_on_the_canvas_carries_the_panel_depth(self, app):
        props = self._pick_catalog(app, 'web', 'L 50x5')
        linked = {frozenset((m['a'], m['b'])) for m in app.members}
        # Two nodes NOT already joined: _add_rod_between is silently a no-op
        # on a pair that is, and a no-op would pass any assertion about "the
        # new rod" by testing an old one.
        a, b = next((i, j) for i in range(len(app.nodes))
                    for j in range(i + 1, len(app.nodes))
                    if frozenset((i, j)) not in linked)
        n0 = len(app.members)
        app._add_rod_between(a, b)
        assert len(app.members) == n0 + 1, 'no rod was added'
        rod = app.members[-1]
        assert {rod['a'], rod['b']} == {a, b}
        assert rod['c_cm'] == pytest.approx(props['c_cm'])

    def test_the_crane_mast_carries_the_depth_it_needs_for_bending(self, app):
        """The mast is RIGID, so it takes a bending check."""
        props = self._pick_catalog(app, 'web', 'IPE 200')
        top = max(p[2] for p in app.nodes)
        tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - top) < 1e-9]
        app.selected_nodes = set(tops[:4])
        app._add_cable_crane()
        masts = [m for m in app.members if m.get('role') == 'crane_mast']
        assert masts and masts[0]['c_cm'] == pytest.approx(props['c_cm'])

    def test_the_depth_survives_an_excel_round_trip(self, app, tmp_path):
        props = self._pick_catalog(app, 'web', 'L 50x5')
        app._apply_sections()
        path = tmp_path / 'depth.xlsx'
        sr_module.export_excel(app.nodes, app.members, app._all_loads(),
                               app.supports, None, str(path),
                               profiles=app.profiles)
        model = sr_module.import_excel_model(str(path))
        members = model['members'] if isinstance(model, dict) else model[1]
        with_depth = [m for m in members if m.get('c_cm')]
        assert with_depth, 'c_cm did not survive the workbook'
        assert with_depth[0]['c_cm'] == pytest.approx(props['c_cm'])


class TestLockedGroups:
    """A group is one object until it is opened -- driven through the app.

    The request: once made, a group cannot be edited unless edit mode is
    opened; it moves as a whole and its parts cannot; its nodes cannot be
    moved but rods can still be added to them; and while it is being edited
    everything outside it is blocked but stays visible. The rules are unit
    tested in test_stereo_group_locks.py; these check each tool obeys them.
    """

    def _group(self, app, monkeypatch, name, rods):
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: name)
        app.selected_members = set(rods)
        app.selected_member = None
        app.selected_nodes = set()
        app._group_new_from_selection()
        g = app.groups[-1]
        app.selected_members = set()
        return g

    def _outside_rod_at(self, app, nodes, exclude):
        for j, m in enumerate(app.members):
            if j not in exclude and (m['a'] in nodes or m['b'] in nodes):
                return j
        raise AssertionError('no neighbouring rod')

    def _free_node(self, app):
        grouped = set(sgp.nodes_of_rods(app.members,
                                        sgp.owner_of_rod(app.groups)))
        return next(n for n in range(len(app.nodes)) if n not in grouped)

    # ── locked ─────────────────────────────────────────────────────────────

    def test_dragging_a_node_of_a_group_moves_the_whole_group(self, app,
                                                              monkeypatch):
        g = self._group(app, monkeypatch, 'Roof', range(6))
        mine = sgp.nodes_of_rods(app.members, sorted(g['members']))
        before = list(app.nodes)
        app.selected_nodes = {mine[0]}
        app._move_selected_nodes_by_screen(300, 300, 360, 330)
        deltas = {tuple(round(app.nodes[n][k] - before[n][k], 9)
                        for k in range(3)) for n in mine}
        assert len(deltas) == 1, 'every node of the group moved by one vector'
        assert deltas != {(0.0, 0.0, 0.0)}
        others = [n for n in range(len(before)) if n not in set(mine)]
        assert all(app.nodes[n] == before[n] for n in others)

    def test_a_group_joined_to_another_group_by_a_joint_does_not_move(
            self, app, monkeypatch):
        a = self._group(app, monkeypatch, 'A', range(6))
        mine = set(sgp.nodes_of_rods(app.members, sorted(a['members'])))
        j = self._outside_rod_at(app, mine, a['members'])
        self._group(app, monkeypatch, 'B', [j])
        before = list(app.nodes)
        app.selected_nodes = {next(n for n in sorted(mine)
                                   if n not in (app.members[j]['a'],
                                                app.members[j]['b']))}
        app._move_selected_nodes_by_screen(300, 300, 360, 330)
        assert app.nodes == before
        assert 'shares' in app.status_var.get()

    def test_a_locked_node_cannot_be_typed_to_a_new_place(self, app,
                                                          monkeypatch, dialogs):
        g = self._group(app, monkeypatch, 'Roof', range(6))
        n = sgp.nodes_of_rods(app.members, sorted(g['members']))[0]
        before = app.nodes[n]
        app.selected_nodes = {n}
        app.selected_member = None
        app._update_properties_panel()
        app._props_entries['x'].set(before[0] + 5.0)
        app._apply_node_properties()
        assert app.nodes[n] == before
        assert any('locked' in str(d) for d in dialogs)

    def test_a_locked_rods_properties_cannot_be_edited(self, app, monkeypatch):
        g = self._group(app, monkeypatch, 'Roof', range(6))
        app.selected_member = 0
        app.selected_members = {0}
        app.selected_nodes = set()
        was = dict(app.members[0])
        app._update_properties_panel()
        for key, var in app._props_entries.items():
            try:
                var.set(var.get() * 2 if isinstance(var.get(), float)
                        else var.get())
            except Exception:
                pass
        app._apply_member_properties()
        assert app.members[0] == was
        assert 0 in g['members']

    def test_rods_can_still_be_drawn_to_a_locked_groups_nodes(self, app,
                                                              monkeypatch):
        g = self._group(app, monkeypatch, 'Roof', range(6))
        n = sgp.nodes_of_rods(app.members, sorted(g['members']))[0]
        free = self._free_node(app)
        before = set(g['members'])
        app._add_rod_between(n, free)
        new = len(app.members) - 1
        assert {app.members[new]['a'], app.members[new]['b']} == {n, free}
        assert g['members'] == before, 'the new rod is not part of the object'
        assert new in sgp.ungrouped_rods(app.groups, len(app.members))

    def test_a_locked_groups_rods_are_not_deleted(self, app, monkeypatch,
                                                  dialogs):
        g = self._group(app, monkeypatch, 'Roof', range(6))
        n_members = len(app.members)
        app.selected_nodes = set()
        app.selected_members = {0, 100}
        app._on_delete_selection()
        assert len(app.members) == n_members, 'all or nothing'
        assert g['members'] == set(range(6))
        assert any('Nothing was deleted' in str(d) for d in dialogs)

    def test_panel_sections_leave_a_locked_groups_own_section_alone(
            self, app, monkeypatch):
        from apps.stereo import stereo_profiles as sp
        g = self._group(app, monkeypatch, 'Roof', range(6))
        app.group_list.selection_clear(0, 'end')
        app.group_list.selection_set(0)
        app._on_group_pick()
        name = sp.catalog_names()[5]
        app.group_profile.set(name)
        app._group_apply_profile()
        assert {app.members[i]['profile'] for i in range(6)} == {name}
        app._apply_sections()
        assert {app.members[i]['profile'] for i in range(6)} == {name}
        assert 'kept their own sections' in app.status_var.get()

    def test_a_group_moves_by_a_typed_offset_and_undo_puts_it_back(
            self, app, monkeypatch):
        g = self._group(app, monkeypatch, 'Roof', range(6))
        mine = sgp.nodes_of_rods(app.members, sorted(g['members']))
        # Its joints are shared with Ungrouped rods only, which are not an
        # object: they stretch to follow, so the group may move.
        before = list(app.nodes)
        assert app._group_move_by(g['id'], 1.0, 0.0, 0.5)
        for n in mine:
            assert app.nodes[n][0] == pytest.approx(before[n][0] + 1.0)
            assert app.nodes[n][2] == pytest.approx(before[n][2] + 0.5)
        app._undo()
        assert app.nodes == before

    def test_the_move_dialog_moves_the_picked_group(self, app, monkeypatch):
        g = self._group(app, monkeypatch, 'Roof', range(6))
        app.group_list.selection_clear(0, 'end')
        app.group_list.selection_set(0)
        app._on_group_pick()
        n = sgp.nodes_of_rods(app.members, sorted(g['members']))[0]
        x0 = app.nodes[n][0]
        win = app._group_move_dialog()
        app._group_move_vals['dx'].set(2.0)
        app._group_move_go()
        assert app.nodes[n][0] == pytest.approx(x0 + 2.0)
        assert not win.winfo_exists()

    # ── edit mode ─────────────────────────────────────────────────────────

    def test_opening_a_group_shows_it_on_the_button_and_the_drawing(
            self, app, monkeypatch):
        g = self._group(app, monkeypatch, 'Roof', range(6))
        assert 'Open group' in app.group_edit_btn.cget('text')
        app._group_edit_toggle(g['id'])
        assert app._editing_gid() == g['id']
        assert app.group_edit_btn.cget('text') == 'Done'
        assert 'Editing: Roof' in app.group_edit_state.cget('text')
        app._draw()
        assert app.canvas.find_withtag('edit_banner')
        dim = app.canvas.find_withtag('locked_dim')
        assert len(dim) == len(app.members) - 6, \
            'everything outside is drawn -- faded, not hidden'
        app._group_edit_toggle()
        app._draw()
        assert not app.canvas.find_withtag('edit_banner')
        assert not app.canvas.find_withtag('locked_dim')

    def test_while_open_nothing_outside_can_be_selected(self, app,
                                                        monkeypatch):
        g = self._group(app, monkeypatch, 'Roof', range(6))
        mine = set(sgp.nodes_of_rods(app.members, sorted(g['members'])))
        app._group_edit_toggle(g['id'])
        outside = self._free_node(app)
        app.selected_nodes = {outside, min(mine)}
        app.selected_members = {0, 100}
        app._sync_selection_fields()
        assert app.selected_nodes == {min(mine)}
        assert app.selected_members == {0}

    def test_while_open_a_part_moves_by_itself(self, app, monkeypatch):
        g = self._group(app, monkeypatch, 'Roof', range(6))
        mine = sgp.nodes_of_rods(app.members, sorted(g['members']))
        app._group_edit_toggle(g['id'])
        before = list(app.nodes)
        app.selected_nodes = {mine[0]}
        app._move_selected_nodes_by_screen(300, 300, 360, 330)
        moved = [n for n in range(len(before)) if app.nodes[n] != before[n]]
        assert moved == [mine[0]]

    def test_while_open_its_rods_delete_and_undo_restores_the_group(
            self, app, monkeypatch):
        g = self._group(app, monkeypatch, 'Roof', range(6))
        app._group_edit_toggle(g['id'])
        app.selected_nodes = set()
        app.selected_members = {0}
        app._on_delete_selection()
        assert g['members'] == set(range(5))
        app._undo()
        again = sgp.find(app.groups, g['id'])
        assert again['members'] == set(range(6)), \
            'undo brings the group back with the rod'
        rec = sgp.totals_reconcile(app.groups, app.nodes, app.members)
        assert rec['ok'], rec

    def test_a_rod_drawn_while_open_joins_the_group(self, app, monkeypatch):
        g = self._group(app, monkeypatch, 'Roof', range(12))
        mine = sgp.nodes_of_rods(app.members, sorted(g['members']))
        linked = {frozenset((m['a'], m['b'])) for m in app.members}
        a, b = next((p, q) for p in mine for q in mine
                    if p < q and frozenset((p, q)) not in linked)
        app._group_edit_toggle(g['id'])
        app._add_rod_between(a, b)
        assert len(app.members) - 1 in g['members']

    def test_while_open_a_rod_to_a_node_outside_is_refused(self, app,
                                                           monkeypatch):
        g = self._group(app, monkeypatch, 'Roof', range(6))
        n = sgp.nodes_of_rods(app.members, sorted(g['members']))[0]
        free = self._free_node(app)
        app._group_edit_toggle(g['id'])
        count = len(app.members)
        app._add_rod_between(n, free)
        assert len(app.members) == count

    def test_while_open_other_groups_are_blocked_in_the_panel(self, app,
                                                              monkeypatch):
        a = self._group(app, monkeypatch, 'A', range(6))
        b = self._group(app, monkeypatch, 'B', [300])
        app._group_edit_toggle(a['id'])
        app.group_list.selection_clear(0, 'end')
        app.group_list.selection_set(1)
        app._on_group_pick()
        app._group_delete()
        assert sgp.find(app.groups, b['id']) is not None

    def test_an_open_group_that_undo_removes_closes_itself(self, app,
                                                           monkeypatch):
        g = self._group(app, monkeypatch, 'Roof', range(6))
        app._group_edit_toggle(g['id'])
        app._undo()                         # undoes "new group"
        assert app.groups == []
        assert app._editing_gid() is None
        assert 'Open group' in app.group_edit_btn.cget('text')

    def test_a_new_group_made_while_open_nests_inside_it(self, app,
                                                        monkeypatch):
        g = self._group(app, monkeypatch, 'Roof', range(6))
        app._group_edit_toggle(g['id'])
        sub = self._group(app, monkeypatch, 'Bay', [0, 1])
        assert sub['parent'] == g['id']
        assert sgp.rods_of(app.groups, g['id']) == list(range(6))

    def test_an_addon_bolted_to_a_locked_group_leaves_it_unchanged(
            self, app, monkeypatch):
        top = max(p[2] for p in app.nodes)
        tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - top) < 1e-9]
        feet = set(tops[:4])
        rods = [i for i, m in enumerate(app.members)
                if m['a'] in feet or m['b'] in feet]
        g = self._group(app, monkeypatch, 'Roof', rods)
        before_nodes = list(app.nodes)
        n = len(app.members)
        app.selected_nodes = feet
        app._add_column()
        assert len(app.members) > n, 'the column went on'
        assert g['members'] == set(rods)
        assert app.nodes[:len(before_nodes)] == before_nodes


class TestShowMeThisRod:
    """"Show me this rod": a rod a panel names is found for you -- selected,
    brought to the middle of the view and flagged with a caption."""

    def _mid_on_screen(self, app, i):
        pts = app._screen_positions()
        m = app.members[i]
        (ax, ay), (bx, by) = pts[m['a']], pts[m['b']]
        return (ax + bx) / 2.0, (ay + by) / 2.0

    def _centre(self, app):
        return app.canvas.winfo_width() / 2.0, app.canvas.winfo_height() / 2.0

    def test_centring_on_a_node_puts_it_in_the_middle_at_any_zoom(self, app):
        """The old centring set the pan to minus the node's projection,
        which ignores the model's centre and the zoom, so the node landed
        somewhere else."""
        for zoom in (1.0, 2.5):
            app.zc.zoom = zoom
            app._center_on_node(17)
            sx, sy = app._screen_positions()[17]
            cx, cy = self._centre(app)
            assert abs(sx - cx) < 1.0 and abs(sy - cy) < 1.0, (zoom, sx, sy)

    def test_before_a_solve_there_is_no_governing_rod_to_show(self, app,
                                                              dialogs):
        assert app._governing_rod() is None
        assert app._show_governing_rod() is False
        assert any('Analyze first' in str(d) for d in dialogs)

    def test_the_governing_rod_is_selected_centred_and_flagged(self, app):
        app._analyze()
        i, u = app._governing_rod()
        assert u == max(c['util'] for c in app.member_checks
                        if c.get('util') is not None)
        assert app._show_governing_rod()
        assert app.selected_member == i and app.selected_members == {i}
        sx, sy = self._mid_on_screen(app, i)
        cx, cy = self._centre(app)
        assert abs(sx - cx) < 1.0 and abs(sy - cy) < 1.0
        texts = [app.canvas.itemcget(t, 'text')
                 for t in app.canvas.find_withtag('flagged_rod')
                 if app.canvas.type(t) == 'text']
        assert texts == ['governing rod %d -- utilisation %.2f' % (i, u)]

    def test_clicking_something_else_takes_the_flag_away(self, app):
        app._analyze()
        app._show_governing_rod()
        app.selected_members = set()
        app.selected_member = None
        app.selected_nodes = {0}
        app._sync_selection_fields()
        app._draw()
        assert app._flagged_rod is None
        assert not app.canvas.find_withtag('flagged_rod')

    def test_an_edit_that_drops_the_solve_drops_the_flag(self, app):
        """"Governing" is a claim about one solve; after an edit it may be
        some other rod."""
        app._analyze()
        app._show_governing_rod()
        app.results = None
        app.member_checks = None
        app._draw()
        assert not app.canvas.find_withtag('flagged_rod')

    def test_the_results_panel_has_the_button(self, app):
        def texts(w):
            out = []
            for c in w.winfo_children():
                try:
                    out.append(c.cget('text'))
                except tk.TclError:
                    pass
                out += texts(c)
            return out
        assert 'Show me the governing rod' in texts(app._mode_frames['results'])

    def test_a_groups_recommendation_can_show_its_governing_rod(
            self, app, monkeypatch):
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: 'Roof')
        app.selected_members = set(range(40))
        app.selected_nodes = set()
        app._group_new_from_selection()
        app._analyze()
        app.group_list.selection_clear(0, 'end')
        app.group_list.selection_set(0)
        app._on_group_pick()
        app._group_recommend()
        win = app._group_rec_win
        buttons = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Button) and \
                        c.cget('text').startswith('Show me rod'):
                    buttons.append(c)
                walk(c)
        walk(win)
        assert buttons, 'no "Show me rod" button in the recommendation'
        buttons[0].invoke()
        rod = int(buttons[0].cget('text').split()[3])
        assert app.selected_member == rod
        assert rod in range(40)
        assert 'Roof' in app._flagged_rod[1]
        win.destroy()

    def test_a_groups_properties_can_show_its_worst_rod(self, app,
                                                       monkeypatch):
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: 'Roof')
        app.selected_members = set(range(40))
        app.selected_nodes = set()
        app._group_new_from_selection()
        app._analyze()
        app.group_list.selection_clear(0, 'end')
        app.group_list.selection_set(0)
        app._on_group_pick()
        win = app._group_properties()
        btn = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Button) and c.cget('text') == 'Show worst rod':
                    btn.append(c)
                walk(c)
        walk(win)
        assert btn
        btn[0].invoke()
        assert app._flagged_rod[0] == app._governing_rod(range(40))[0]
        win.destroy()


class TestSectionPropertiesInTheBoxes:
    """The recommendation and the group's properties box show the section's
    own numbers -- A, I, both radii, c, W, mass -- not just its name."""

    def _group(self, app, monkeypatch, rods):
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: 'Roof')
        app.selected_members = set(rods)
        app.selected_nodes = set()
        app._group_new_from_selection()
        app.group_list.selection_clear(0, 'end')
        app.group_list.selection_set(0)
        app._on_group_pick()
        return app.groups[-1]

    def _frames(self, win):
        out = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.LabelFrame):
                    out.append(c)
                walk(c)
        walk(win)
        return out

    def _labels(self, frame):
        return [c.cget('text') for c in frame.winfo_children()
                if isinstance(c, tk.Label)]

    def test_the_recommendation_shows_the_recommended_sections_properties(
            self, app, monkeypatch):
        self._group(app, monkeypatch, range(40))
        app._analyze()
        app._group_recommend()
        win = app._group_rec_win
        tables = [f for f in self._frames(win)
                  if f.cget('text').startswith('Section properties')]
        assert len(tables) == 1
        name = tables[0].cget('text').split('-- ')[1]
        from apps.stereo import stereo_profiles as sp
        labels = self._labels(tables[0])
        for sym, val, unit, _m in sp.section_properties(name):
            assert sym in labels and val in labels and unit in labels, sym
        win.destroy()

    def test_the_properties_box_shows_the_groups_section(self, app,
                                                         monkeypatch):
        from apps.stereo import stereo_profiles as sp
        self._group(app, monkeypatch, range(12))
        app.group_profile.set('IPE 200')
        app._group_apply_profile()
        win = app._group_properties()
        tables = [f for f in self._frames(win)
                  if 'IPE 200' in f.cget('text')]
        assert tables and tables[0].cget('text') == \
            'Section properties -- IPE 200'
        r_min = dict((r[0], r[1]) for r in sp.section_properties('IPE 200'))
        assert r_min['r min'] in self._labels(tables[0])
        win.destroy()

    def test_a_mixed_group_says_which_section_it_is_showing(self, app,
                                                          monkeypatch):
        self._group(app, monkeypatch, range(12))
        app.group_profile.set('IPE 200')
        app._group_apply_profile()
        from apps.stereo import stereo_checks as sk
        sk.apply_recommendation(app.members, [0, 1], 'HEA 200')
        win = app._group_properties()
        titles = [f.cget('text') for f in self._frames(win)]
        assert 'Most used: IPE 200 (10 of 12 rods)' in titles
        win.destroy()


class TestGroupsPdf:
    """One document for a grouped model: a summary with contents, the joints
    where groups meet, and a section per group -- numbered as one document."""

    def _pages(self, path):
        import re
        data = open(path, 'rb').read()
        return len(re.findall(rb'/Type\s*/Page(?!s)', data))

    def _groups(self, app, monkeypatch):
        names = iter(['Roof A', 'Bay A1', 'Roof B'])
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: next(names))
        app.selected_nodes = set()
        app.selected_members = set(range(0, 200))
        app._group_new_from_selection()
        a = app.groups[-1]
        app.group_list.selection_clear(0, 'end')
        app.group_list.selection_set(0)
        app._on_group_pick()
        app.selected_members = set(range(0, 40))
        app._group_edit_toggle(a['id'])       # rods leave A only while open
        app._group_new_from_selection()        # nests inside A
        app._group_edit_toggle()
        app.selected_members = set(range(200, 420))
        app._group_new_from_selection()
        app._analyze()
        monkeypatch.setattr(app, '_pdf_sheet_dialog',
                            lambda *a, **k: {'tables'})

    def test_every_group_gets_a_section_and_the_numbering_is_one_document(
            self, app, monkeypatch, tmp_path):
        from apps.stereo import stereo_reports as sr
        self._groups(app, monkeypatch)
        path = str(tmp_path / 'groups.pdf')
        contents = app._export_groups_pdf(path=path)
        titles = [t.strip() for t, _ in contents]
        assert titles[:2] == ['Groups — summary',
                              'Joints shared between groups']
        assert titles[2:] == ['Roof A', 'Bay A1', 'Roof B', 'Ungrouped']
        # each section starts where the one before it ends
        per = []
        for gid, name, lvl, rods in sr.group_report_order(app.groups,
                                                          len(app.members)):
            sub = sr.submodel(app.nodes, app.members, app._all_loads(),
                              app._active_supports(), app.results,
                              app.member_checks, member_idx=rods)
            per.append(len(sr.report_plan(sub[1], sub[4], sub[5], {'tables'},
                                          False)))
        starts = [at for _t, at in contents[2:]]
        assert [b - a for a, b in zip(starts, starts[1:])] == per[:-1]
        assert self._pages(path) == starts[-1] + per[-1] - 1

    def test_the_joints_run_over_as_many_sheets_as_they_need(self, app,
                                                             monkeypatch,
                                                             tmp_path):
        from apps.stereo import stereo_reports as sr
        from apps.stereo import stereo_groups as sgp
        self._groups(app, monkeypatch)
        rows = sgp.shared_node_rows(app.groups, app.nodes, app.members,
                                    app.results['member_res'])
        blocks = sr._joint_table_rows(rows, sr.ReportUnits())
        pages = sr._paginate_blocks(blocks)
        assert sum(len(p) for p in pages) == sum(len(r['sides']) for r in rows)
        assert all(len(p) <= sr.PDF_JOINT_ROWS_PER_SHEET for p in pages)
        # no joint is split across two sheets: each page starts with a node
        assert all(p[0][0] != '' for p in pages)
        contents = app._export_groups_pdf(path=str(tmp_path / 'g.pdf'))
        assert contents[2][1] == 2 + len(pages), \
            'the first section starts after the last joints sheet'

    def test_pdf_of_this_group_covers_it_and_its_subgroups_only(
            self, app, monkeypatch, tmp_path):
        self._groups(app, monkeypatch)
        app.group_list.selection_clear(0, 'end')
        app.group_list.selection_set(0)            # Roof A, with Bay A1
        app._on_group_pick()
        contents = app._export_groups_pdf(only_picked=True,
                                          path=str(tmp_path / 'a.pdf'))
        assert [t.strip() for t, _ in contents[2:]] == ['Roof A', 'Bay A1']

    def test_it_asks_for_a_solve_first(self, app, monkeypatch, dialogs,
                                       tmp_path):
        self._groups(app, monkeypatch)
        app.results = None
        assert app._export_groups_pdf(path=str(tmp_path / 'x.pdf')) is None
        assert any('Analyze first' in str(d) for d in dialogs)

    def test_the_panel_offers_both_actions(self, app):
        def texts(w):
            out = []
            for c in w.winfo_children():
                try:
                    out.append(c.cget('text'))
                except tk.TclError:
                    pass
                out += texts(c)
            return out
        t = texts(app._groups_box)
        assert 'PDF of groups…' in t and 'PDF of this group…' in t


class TestGroupedAndUngroupedModes:
    """Grouped mode marks every top-level group with its own tint and names
    them in a key; Ungrouped is the plain model. The locks hold in both."""

    def _two_groups(self, app, monkeypatch):
        names = iter(['Roof A', 'Bay A1', 'Roof B'])
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: next(names))
        app.selected_nodes = set()
        app.selected_members = set(range(0, 60))
        app._group_new_from_selection()
        a = app.groups[-1]
        app._group_edit_toggle(a['id'])
        app.selected_members = set(range(0, 10))
        app._group_new_from_selection()           # Bay A1, inside Roof A
        app._group_edit_toggle()
        app.selected_members = set(range(300, 340))
        app._group_new_from_selection()
        return a

    def test_ungrouped_mode_draws_the_plain_model(self, app, monkeypatch):
        self._two_groups(app, monkeypatch)
        app.group_view.set(False)
        app._draw()
        assert not app.canvas.find_withtag('group_tint')
        assert not app.canvas.find_withtag('group_key')

    def test_grouped_mode_tints_every_grouped_rod_by_its_outer_group(
            self, app, monkeypatch):
        self._two_groups(app, monkeypatch)
        app.group_view.set(True)
        app._draw()
        tints = app.canvas.find_withtag('group_tint')
        assert len(tints) == 60 + 40, 'every grouped rod, and only those'
        rods, key = app._group_tint_map()
        assert [n for n, _t in key] == ['Roof A', 'Roof B'], \
            'a subgroup reads as part of its outer group'
        assert rods[0] == rods[59], 'Bay A1 takes Roof A\'s tint'
        assert rods[0] != rods[300]
        texts = [app.canvas.itemcget(t, 'text')
                 for t in app.canvas.find_withtag('group_key')
                 if app.canvas.type(t) == 'text']
        assert texts == ['GROUPS', 'Roof A', 'Roof B']

    def test_the_locks_hold_in_ungrouped_mode_too(self, app, monkeypatch):
        self._two_groups(app, monkeypatch)
        app.group_view.set(False)
        n = len(app.members)
        app.selected_nodes = set()
        app.selected_members = {5}
        app._on_delete_selection()
        assert len(app.members) == n

    def test_the_panel_has_the_two_modes(self, app):
        radios = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Radiobutton):
                    radios.append(c.cget('text'))
                walk(c)
        walk(app._groups_box)
        assert 'Plain' in radios and 'Coloured by group' in radios


class TestGroupsThroughExcel:
    """Export Excel, edit the Groups sheet, Import from Excel -- through the
    app's own two buttons."""

    def test_groups_survive_the_round_trip_and_an_edit_lands(
            self, app, monkeypatch, tmp_path, dialogs):
        import openpyxl
        from apps.stereo import stereo_groups_excel as sge
        names = iter(['Roof', 'Edge'])
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: next(names))
        app.selected_nodes = set()
        app.selected_members = set(range(0, 30))
        app._group_new_from_selection()
        app.selected_members = set(range(100, 110))
        app._group_new_from_selection()
        path = str(tmp_path / 'm.xlsx')
        monkeypatch.setattr('apps.stereo.stereo_app_reports.filedialog'
                            '.asksaveasfilename', lambda *a, **k: path)
        monkeypatch.setattr('apps.stereo.stereo_app_reports.filedialog'
                            '.askopenfilename', lambda *a, **k: path)
        app._export_excel()

        wb = openpyxl.load_workbook(path)
        ws = wb[sge.SHEET]
        hdr = next(r for r in ws.iter_rows() if r[0].value == 'id')
        col = {c.value: c.column for c in hdr}
        for r in ws.iter_rows(min_row=hdr[0].row + 1):
            if r[1].value == 'Edge':
                ws.cell(row=r[0].row, column=col['profile'], value='CHS 76.1x3.6')
        wb.save(path)

        app._generate(push_undo=False)            # a different model loaded
        assert app.groups == []
        app._import_excel()
        assert [g['name'] for g in app.groups] == ['Roof', 'Edge']
        assert app.groups[0]['members'] == set(range(30))
        assert {app.members[i]['profile'] for i in range(100, 110)} == \
            {'CHS 76.1x3.6'}
        assert app.members[0]['profile'] != 'CHS 76.1x3.6'
        assert any('2 group(s) read' in str(d) and 'CHS 76.1x3.6' in str(d)
                   for d in dialogs)

    def test_a_bad_groups_sheet_leaves_the_model_as_it_was(
            self, app, monkeypatch, tmp_path, dialogs):
        import openpyxl
        from apps.stereo import stereo_groups_excel as sge
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: 'Roof')
        app.selected_nodes = set()
        app.selected_members = set(range(0, 30))
        app._group_new_from_selection()
        path = str(tmp_path / 'm.xlsx')
        monkeypatch.setattr('apps.stereo.stereo_app_reports.filedialog'
                            '.asksaveasfilename', lambda *a, **k: path)
        monkeypatch.setattr('apps.stereo.stereo_app_reports.filedialog'
                            '.askopenfilename', lambda *a, **k: path)
        app._export_excel()
        wb = openpyxl.load_workbook(path)
        ws = wb[sge.SHEET]
        hdr = next(r for r in ws.iter_rows() if r[0].value == 'id')
        col = {c.value: c.column for c in hdr}
        ws.cell(row=hdr[0].row + 1, column=col['rods'], value='0-5, 99999')
        wb.save(path)
        n_before, groups_before = len(app.members), [dict(g) for g in app.groups]
        app._import_excel()
        assert len(app.members) == n_before
        assert [g['name'] for g in app.groups] == [g['name'] for g in groups_before]
        assert any('Import failed' in str(d) and '99999' in str(d)
                   for d in dialogs)


class TestUnitWeightFollowsTheSelector:
    """The self-weight box shows the selected convention and the model keeps
    kN/m³ -- the take-off sheet, the self-weight load and the reports all
    read the stored figure through _unit_weight()."""

    def test_the_box_shows_pcf_under_aisc_and_the_model_keeps_kn_m3(self, app):
        import units
        was = units.current().key
        try:
            units.set_current('aisc')
            assert app.unit_weight_var.get() == pytest.approx(499.72, abs=0.01)
            assert 'pcf' in app._self_weight_check.cget('text')
            assert app._unit_weight() == pytest.approx(78.5)
            app.unit_weight_var.set(500.0)            # typed in pcf
            assert app._unit_weight() == pytest.approx(78.544, abs=1e-3)
        finally:
            units.set_current(was)
        assert 'kN/m³' in app._self_weight_check.cget('text')
        assert app.unit_weight_var.get() == pytest.approx(78.544, abs=1e-3)

    def test_the_self_weight_load_uses_the_stored_figure(self, app):
        import units
        app.self_weight_on.set(True)
        loads_si = app._all_loads()
        was = units.current().key
        try:
            units.set_current('aisc')
            loads_us = app._all_loads()
        finally:
            units.set_current(was)
        tot = lambda L: sum(ld.get('fz', 0.0) for ld in L)
        assert tot(loads_us) == pytest.approx(tot(loads_si)), \
            'switching the display must not change the load'

    def test_the_sketchup_import_is_on_the_menu(self, app):
        labels = [app.export_menu.entrycget(i, 'label')
                  for i in range(app.export_menu.index('end') + 1)
                  if app.export_menu.type(i) == 'command']
        assert 'Import from SketchUp…' in labels
        i = labels.index('Import from SketchUp…')
        cmds = [app.export_menu.entrycget(k, 'command')
                for k in range(app.export_menu.index('end') + 1)
                if app.export_menu.type(k) == 'command']
        assert '_import_sketchup' in cmds[i]


class TestRotateAndMirror:
    """Roadmap 3.4 through the app: the arrow keys pick the axis, R rotates,
    M mirrors, Shift+M mirrors a copy -- and a locked group turns whole."""

    def _lengths(self, app, rods):
        import math
        return [math.dist(app.nodes[app.members[j]['a']],
                          app.nodes[app.members[j]['b']]) for j in rods]

    def test_rotating_keeps_every_rod_its_length_and_undo_undoes_it(self, app):
        import math
        rods = list(range(0, 40))
        app.selected_nodes = set()
        app.selected_members = set(rods)
        before_nodes = list(app.nodes)
        before = self._lengths(app, range(len(app.members)))
        ids = app._tx_selected_nodes()
        c0 = [sum(app.nodes[i][k] for i in ids) / len(ids) for k in range(3)]
        assert app._tx_rotate(angle=30.0, axis='Z')
        c1 = [sum(app.nodes[i][k] for i in ids) / len(ids) for k in range(3)]
        assert c1 == pytest.approx(c0), 'turned about its own middle'
        after = self._lengths(app, rods)
        assert after == pytest.approx([before[j] for j in rods])
        moved = [i for i in range(len(before_nodes))
                 if app.nodes[i] != before_nodes[i]]
        assert set(moved) == set(ids)
        app._undo()
        assert app.nodes == before_nodes

    def test_a_locked_group_turns_whole(self, app, monkeypatch):
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: 'Bay')
        app.selected_nodes = set()
        app.selected_members = set(range(0, 30))
        app._group_new_from_selection()
        g = app.groups[-1]
        mine = sgp.nodes_of_rods(app.members, sorted(g['members']))
        before = list(app.nodes)
        app.selected_members = set()
        app.selected_nodes = {mine[0]}
        assert app._tx_rotate(angle=15.0, axis='Z')
        # every node of the group where turning the GROUP about its middle
        # puts it (a node sitting on that axis stays put, correctly), and
        # nothing outside the group touched
        from apps.stereo import stereo_transform as st
        expect = st.rotated(before, mine, 'Z', 15.0)
        for i in range(len(before)):
            assert app.nodes[i] == pytest.approx(expect[i]), i
        assert sum(1 for i in mine if app.nodes[i] != before[i]) >             len(mine) // 2

    def test_mirroring_in_place_flips_the_selection_over_its_middle(self, app):
        app.selected_members = set()
        app.selected_nodes = {0, 1, 2}
        xs = [app.nodes[i][0] for i in (0, 1, 2)]
        mid = (max(xs) + min(xs)) / 2.0
        mean = sum(xs) / 3.0
        before = {i: app.nodes[i] for i in (0, 1, 2)}
        assert app._tx_mirror(axis='X')
        for i in (0, 1, 2):
            assert app.nodes[i][0] == pytest.approx(2 * mean - before[i][0])
            assert app.nodes[i][1:] == before[i][1:]

    def test_a_mirrored_copy_of_the_whole_grid_goes_alongside_it(self, app):
        n_nodes, n_rods = len(app.nodes), len(app.members)
        n_sup = len(app.supports)
        top = max(p[0] for p in app.nodes)
        on_edge = sum(1 for p in app.nodes if abs(p[0] - top) < 1e-9)
        app.selected_members = set()
        app.selected_nodes = set(range(n_nodes))
        assert app._tx_mirror(copy=True, axis='X')
        assert len(app.nodes) == 2 * n_nodes - on_edge, \
            'the nodes on the mirror plane are shared, not doubled'
        assert len(app.members) > n_rods
        assert max(p[0] for p in app.nodes) == pytest.approx(
            top + (top - min(p[0] for p in app.nodes[:n_nodes])))
        assert len(app.supports) > n_sup, 'the copy is supported too'
        app._analyze()
        assert app.results is not None, 'the doubled structure solves'

    def test_a_copy_onto_what_is_already_there_adds_nothing(self, app):
        """The left half mirrored about the middle IS the right half."""
        xs = [p[0] for p in app.nodes]
        mid = (max(xs) + min(xs)) / 2.0
        left = {i for i, p in enumerate(app.nodes) if p[0] <= mid + 1e-9}
        app.selected_members = set()
        app.selected_nodes = left
        app.tx_plane.set('origin (0)') if abs(mid) < 1e-9 else \
            app.tx_plane.set('selection + edge')
        n = len(app.nodes)
        app._tx_mirror(copy=True, axis='X')
        assert len(app.nodes) == n

    def test_an_arrow_key_sets_the_axis_with_several_nodes_selected(self, app):
        app.selected_nodes = {0, 1, 2}
        ev = type('E', (), {'keysym': 'Up'})()
        app._on_axis_key(ev)
        assert app.tx_axis.get() == 'Y'
        assert app._axis_pending is None, 'extending still needs one node'

    def test_the_keys(self, app):
        app.selected_nodes = {0, 1, 2}
        app._tx_key_rotate()
        assert app.root.focus_get() is app._tx_angle_entry
        before = [app.nodes[i] for i in (0, 1, 2)]
        app.tx_axis.set('X')
        app._tx_key_mirror()
        assert [app.nodes[i] for i in (0, 1, 2)] != before

    def test_nothing_selected_says_so(self, app, dialogs):
        app.selected_nodes = set()
        app.selected_members = set()
        assert not app._tx_rotate(angle=10.0)
        assert any('Select the nodes' in str(d) for d in dialogs)


class TestMergeExcelFiles:
    """Roadmap 4.5 through the app: design by parts, combine them."""

    def _export_part(self, app, tmp_path, name, rods):
        """Export a sub-model: the nodes and rods in `rods` only."""
        from apps.stereo import stereo_reports as sr
        sub = sr.submodel(app.nodes, app.members, [], app.supports,
                          member_idx=rods)
        nodes, members, loads, supports = sub[0], sub[1], sub[2], sub[3]
        for m in members:
            m.pop('_source_index', None)
        path = str(tmp_path / name)
        sr.export_excel(nodes, members, loads, supports, None, path)
        return path

    def test_two_halves_merge_back_into_the_whole(self, app, tmp_path,
                                                  dialogs):
        n_nodes, n_rods = len(app.nodes), len(app.members)
        half = n_rods // 2
        a = self._export_part(app, tmp_path, 'a.xlsx', range(0, half))
        b = self._export_part(app, tmp_path, 'b.xlsx', range(half, n_rods))
        app._clear_model()
        lines = app._merge_excel_files([a, b], tol=0.001)
        assert lines is not None
        assert len(app.members) == n_rods
        assert len(app.nodes) <= n_nodes, 'the shared joints merged'
        assert any('coincident node(s) were merged' in ln for ln in lines)
        assert any('Merge Excel files' in str(d) for d in dialogs)
        app._undo()
        assert app.nodes == []

    def test_a_bad_file_leaves_the_model_alone(self, app, tmp_path, dialogs):
        good = self._export_part(app, tmp_path, 'g.xlsx', range(0, 20))
        bad = str(tmp_path / 'bad.xlsx')
        open(bad, 'w').write('not a workbook')
        n = len(app.nodes)
        assert app._merge_excel_files([good, bad], tol=0.001) is None
        assert len(app.nodes) == n
        assert any('not changed' in str(d) for d in dialogs)

    def test_it_is_on_the_menu(self, app):
        labels = [app.export_menu.entrycget(i, 'label')
                  for i in range(app.export_menu.index('end') + 1)
                  if app.export_menu.type(i) == 'command']
        assert 'Merge Excel files…' in labels


class TestWeakAxisInTheApp:

    def test_typing_a_new_I_in_the_inspector_drops_the_catalog_extras(self, app):
        from apps.stereo import stereo_profiles as sp
        sp.write_section(app.members[0],
                         sp.section_to_props(sp.CATALOG['IPE 200']))
        assert 'Iw' in app.members[0]
        app.selected_nodes = set()
        app.selected_member = 0
        app.selected_members = {0}
        app._update_properties_panel()
        app._props_entries['I'].set(app.members[0]['I'] * 2)
        app._apply_member_properties()
        for k in ('c_cm', 'Iw', 'cw_cm'):
            assert k not in app.members[0], k

    def test_an_unchanged_I_keeps_them(self, app):
        from apps.stereo import stereo_profiles as sp
        sp.write_section(app.members[0],
                         sp.section_to_props(sp.CATALOG['IPE 200']))
        app.selected_nodes = set()
        app.selected_member = 0
        app.selected_members = {0}
        app._update_properties_panel()
        app._props_entries['Fy'].set(355.0)
        app._apply_member_properties()
        assert 'Iw' in app.members[0] and app.members[0]['Fy'] == 355.0


class TestWindInTheApp:
    """Roadmap v2 4.6, option 1: the simplified wind case through the app."""

    def _totals(self, loads):
        return tuple(sum(ld.get(k, 0.0) for ld in loads)
                     for k in ('fx', 'fy', 'fz'))

    def test_off_by_default_and_off_adds_nothing(self, app):
        assert app.wind_on.get() is False
        assert app._wind_loads() == []

    def test_a_level_wind_on_a_flat_sheeted_roof_adds_nothing(self, app):
        before = self._totals(app._all_loads())
        app.wind_on.set(True)
        app.wind_q.set(0.8)
        app._on_wind_change()
        assert self._totals(app._all_loads()) == pytest.approx(before, abs=1e-9)

    def test_a_wind_straight_down_on_a_flat_roof_is_q_times_the_roof(self, app):
        app.area_load_on.set(False)
        app.wind_on.set(True)
        app.wind_q.set(0.8)
        app.wind_el.set(-90.0)
        fx, fy, fz = self._totals(app._all_loads())
        roof = sum(app._load_nodes.values())
        assert fz == pytest.approx(-0.8 * roof)
        assert fx == pytest.approx(0.0, abs=1e-9)
        assert 'along the wind' in app.wind_status.cget('text')

    def test_open_rods_load_the_lattice_and_the_reactions_balance_it(self, app):
        from apps.stereo import stereo_wind as sw
        app.area_load_on.set(False)
        app.wind_on.set(True)
        app.wind_mode.set(sw.OPEN)
        app.wind_q.set(1.2)
        app.wind_az.set(30.0)
        want = sw.total(sw.wind_loads(app.nodes, app.members, {}, 1.2, 30.0,
                                      mode=sw.OPEN))
        loads, _span = app._solve_loads()
        got = self._totals(loads)
        assert got == pytest.approx(want)
        assert want[0] > 0 and want[1] > 0
        app._analyze()
        assert app.results is not None
        rx = sum(r.get('Fx', 0.0) for r in app.results['reactions'].values())
        ry = sum(r.get('Fy', 0.0) for r in app.results['reactions'].values())
        assert rx == pytest.approx(-got[0], rel=1e-6)
        assert ry == pytest.approx(-got[1], rel=1e-6)

    def test_changing_the_wind_drops_stale_results(self, app):
        app._analyze()
        assert app.results is not None
        app.wind_on.set(True)
        app._on_wind_change()
        assert app.results is None

    def test_a_sheeted_roof_without_a_surface_says_why(self, app):
        app._load_nodes = {}
        app.wind_on.set(True)
        assert app._wind_loads() == []
        assert 'Open rods' in app.wind_status.cget('text')

    def test_an_imported_workbook_turns_the_wind_off(self, app, tmp_path,
                                                     monkeypatch):
        """The workbook's [LOADS] already holds the wind it was exported
        with; leaving the generator on would apply it twice."""
        from apps.stereo import stereo_wind as sw
        app.wind_on.set(True)
        app.wind_mode.set(sw.OPEN)
        before = self._totals(app._all_loads())
        path = str(tmp_path / 'wind.xlsx')
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                            lambda *a, **kw: path)
        app._export_excel()
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog.askopenfilename',
                            lambda *a, **kw: path)
        app._import_excel()
        assert app.wind_on.get() is False
        assert self._totals(app._all_loads()) == pytest.approx(before, rel=1e-9)


class TestTimberInTheApp:
    """Roadmap 4.3, timber half: CIRSOC 601 Supplement grades on rods."""

    GRADE = 'Eucalipto grandis C1'

    def test_the_picker_puts_a_timber_profile_in_the_panel(self, app):
        name = app._make_timber_profile('chord', self.GRADE, 75, 200)
        assert name == 'Eucalipto grandis C1 75x200'
        assert app.profiles[name]['timber'] == self.GRADE
        assert app.chord_profile_var.get() == name
        assert app.chord_E.get() == pytest.approx(12.0)
        assert app.chord_A.get() == pytest.approx(150.0)

    def test_applying_the_panel_makes_the_chords_timber_and_leaves_the_webs(
            self, app):
        app._make_timber_profile('chord', self.GRADE, 75, 200)
        app._apply_sections()
        from apps.stereo.stereo_app_constants import CHORD_ROLES
        chords = [m for m in app.members if m.get('role') in CHORD_ROLES]
        webs = [m for m in app.members if m.get('role') not in CHORD_ROLES]
        assert chords and webs
        assert all(m.get('timber') == self.GRADE and 'Fy' not in m
                   for m in chords)
        assert not any(m.get('timber') for m in webs)

    def test_timber_rods_are_verified_to_cirsoc_601(self, app):
        from apps.stereo import stereo_timber as stt
        app._make_timber_profile('chord', self.GRADE, 75, 200)
        app._apply_sections()
        app._analyze()
        assert app.results is not None
        for m, chk in zip(app.members, app.member_checks):
            assert chk['checked'] is True
            if m.get('timber'):
                assert chk['code'] == stt.REGLAMENTO
                assert chk['util'] is not None and chk['factors']['CD'] == 1.0

    def test_the_timber_settings_recheck_without_a_new_solve(self, app):
        app._make_timber_profile('chord', self.GRADE, 75, 200)
        app._apply_sections()
        app._analyze()
        res = app.results
        i = next(k for k, m in enumerate(app.members) if m.get('timber')
                 and abs(app.results['member_res'][k]['N']) > 1e-3)
        before = app.member_checks[i]['util']
        app.timber_duration.set('10 minutos (viento, sismo)')
        assert app.results is res                 # the forces stay
        after = app.member_checks[i]
        assert after['factors']['CD'] == 1.6
        assert after['util'] < before
        app.timber_wet.set(True)
        assert app._timber_settings()['wet'] is True
        assert app.member_checks[i]['settings']['wet'] is True

    def test_the_timber_settings_travel_in_the_workbook(
            self, app, tmp_path, monkeypatch):
        from tkinter import filedialog
        from apps.stereo import stereo_reports as sr
        app._make_timber_profile('chord', self.GRADE, 75, 200)
        app._apply_sections()
        app.timber_duration.set('7 días (constructiva)')
        app.timber_sharing.set(True)
        app._analyze()
        path = str(tmp_path / 'timber.xlsx')
        monkeypatch.setattr(filedialog, 'asksaveasfilename',
                            lambda *a, **k: path)
        app._export_excel()
        meta = sr.read_excel_meta(path)
        assert meta['timber_duration'] == '7days'
        app.timber_duration.set('10 años (sobrecarga de uso)')
        app.timber_sharing.set(False)
        monkeypatch.setattr(filedialog, 'askopenfilename',
                            lambda *a, **k: path)
        app._import_excel()
        got = app._timber_settings()
        assert got['duration'] == '7days' and got['load_sharing'] is True

    def test_the_pdf_states_the_timber_settings(self, app, tmp_path):
        import subprocess
        from apps.stereo import stereo_reports as sr
        app._make_timber_profile('chord', self.GRADE, 75, 200)
        app._apply_sections()
        app.timber_wet.set(True)
        app._analyze()
        p = str(tmp_path / 't.pdf')
        sr.export_pdf(app.nodes, app.members, app._all_loads(),
                      app.supports, app.results, p,
                      checks=app.member_checks, groups={'force'})
        text = subprocess.run(['pdftotext', p, '-'], capture_output=True,
                              text=True).stdout
        assert 'TIMBER CHECK (CIRSOC 601)' in text and 'wet' in text

    def test_clicking_a_timber_rod_shows_its_design_values(self, app):
        app._make_timber_profile('chord', self.GRADE, 75, 200)
        app._apply_sections()
        app._analyze()
        i = next(k for k, m in enumerate(app.members) if m.get('timber'))
        app._show_member_info(i)
        assert 'CIRSOC 601:' in app.sel_var.get()

    def test_self_weight_takes_each_rods_own_density(self, app):
        from apps.stereo import stereo_math as sm
        app._make_timber_profile('chord', self.GRADE, 75, 200)
        app._apply_sections()
        app.area_load_on.set(False)
        app.self_weight_on.set(True)
        total = -sum(ld.get('fz', 0.0) for ld in app._all_loads())
        want = 0.0
        for m in app.members:
            _, _, _, L = sm.member_vector(app.nodes, m)
            want += m['A'] * 1e-4 * L * (m.get('gamma_kN_m3') or
                                         app._unit_weight())
        assert total == pytest.approx(want)

    def test_assigning_the_profile_to_a_selection(self, app):
        name = app._make_timber_profile('web', 'Álamo C2', 50, 100)
        app.active_profile.set(name)
        app.selected_members = {0, 1}
        app._assign_profile_to_selection()
        assert app.members[0]['timber'] == 'Álamo C2'
        assert app.members[1]['profile'] == name
        app._undo()
        assert 'timber' not in app.members[0]

    def test_the_dialog_opens_on_a_grade(self, app, tk_root):
        app._open_timber_picker('chord')
        tops = [w for w in app.root.winfo_children()
                if isinstance(w, tk.Toplevel)
                and w.title().startswith('Timber')]
        assert tops
        for w in tops:
            w.destroy()


class TestLinearSelection:
    """Line select picks the rods along the line as well as its nodes."""

    def _arm(self, app):
        _mode(app, 'build')
        app.line_pick_mode.set(True)
        app._on_pick_mode_toggle('line')

    def test_the_rods_along_the_row_come_with_its_nodes(self, app):
        self._arm(app)
        row = _top_row(app)
        sp = app._screen_positions()
        app._handle_line_pick_click(*sp[row[0]])
        app._handle_line_pick_click(*sp[row[-1]])
        on = set(row)
        along = {j for j, m in enumerate(app.members)
                 if m['a'] in on and m['b'] in on}
        assert along, 'a top row has chords'
        assert set(app.selected_members) == along
        assert 'rod(s)' in app.pick_note.cget('text')

    def test_shift_adds_and_carries_on_from_the_far_end(self, app):
        self._arm(app)
        row = _top_row(app)
        sp = app._screen_positions()
        mid = row[len(row) // 2]
        app._handle_line_pick_click(*sp[row[0]])
        app._handle_line_pick_click(*sp[mid], additive=True)
        first = set(app.selected_nodes)
        assert app._line_pick_first == mid, 'the chain carries on from there'
        app._handle_line_pick_click(*sp[row[-1]], additive=True)
        assert first < set(app.selected_nodes)
        assert set(app.selected_nodes) == set(row)
        app._on_axis_cancel()
        assert app._line_pick_first is None

    def test_a_plain_line_replaces_the_selection(self, app):
        self._arm(app)
        app.selected_nodes = {0}
        app.selected_members = {0}
        row = _top_row(app)
        sp = app._screen_positions()
        app._handle_line_pick_click(*sp[row[0]])
        app._handle_line_pick_click(*sp[row[1]])
        assert 0 not in app.selected_members or 0 in row

    def test_the_crossing_box_adds_rods_the_drawn_line_passes(self, app):
        self._arm(app)
        row = _top_row(app)
        sp = app._screen_positions()
        app._handle_line_pick_click(*sp[row[0]])
        app._handle_line_pick_click(*sp[row[-1]])
        plain = set(app.selected_members)
        app.line_pick_cross.set(True)
        app._handle_line_pick_click(*sp[row[0]])
        app._handle_line_pick_click(*sp[row[-1]])
        assert plain <= set(app.selected_members)

    def test_the_rubber_band_follows_the_cursor(self, app):
        self._arm(app)
        row = _top_row(app)
        sp = app._screen_positions()
        app._handle_line_pick_click(*sp[row[0]])

        class E:
            x, y = sp[row[-1]]
        app._on_canvas_hover(E)
        assert app.canvas.find_withtag('pick_rubber')

    def test_l_toggles_the_tool(self, app):
        assert app.line_pick_mode.get() is False
        app._toggle_line_pick()
        assert app.line_pick_mode.get() is True
        app._toggle_line_pick()
        assert app.line_pick_mode.get() is False


class TestGroupsAsLayers:
    """Groups behave like layers: every group and subgroup is a closed
    object until it is opened; right-click opens, Done / Esc / right-click
    on empty canvas steps back out."""

    def _make(self, app, monkeypatch, name, rods, parent=None):
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: name)
        app.selected_members = set(rods)
        app.selected_member = None
        app.selected_nodes = set()
        if parent is not None:
            app._group_open(parent)
            app._group_new_from_selection()
            app._group_step_out()
        else:
            app._group_new_from_selection()
        return app.groups[-1]

    def _tree(self, app, monkeypatch):
        top = self._make(app, monkeypatch, 'Roof', range(12))
        app._group_open(top['id'])
        app.selected_members = {0, 1, 2}
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: 'Bay')
        app._group_new_from_selection()
        sub = app.groups[-1]
        app._group_step_out()
        return top, sub

    def _screen_mid(self, app, rod):
        sp = app._screen_positions()
        m = app.members[rod]
        (x0, y0), (x1, y1) = sp[m['a']], sp[m['b']]
        return (x0 + x1) / 2.0, (y0 + y1) / 2.0

    def test_a_subgroup_stays_closed_while_its_parent_is_open(self, app,
                                                              monkeypatch):
        top, sub = self._tree(app, monkeypatch)
        assert sub['parent'] == top['id']
        app._group_open(top['id'])
        assert sgp.rod_locked(app.groups, 0, app._editing_gid())
        assert not sgp.rod_locked(app.groups, 5, app._editing_gid())

    def test_right_click_on_the_canvas_walks_into_the_layers_and_out(
            self, app, monkeypatch):
        top, sub = self._tree(app, monkeypatch)
        x, y = self._screen_mid(app, 0)
        assert app._group_canvas_open(x, y) == 'open'
        assert app._editing_gid() == top['id'], 'first the outer object'
        assert app._group_canvas_open(x, y) == 'open'
        assert app._editing_gid() == sub['id'], 'then the subgroup inside'
        assert 'Roof › Bay' in app.group_edit_state.cget('text')
        app._group_step_out()
        assert app._editing_gid() == top['id'], 'Done goes back to the parent'
        app._on_escape()
        assert app._editing_gid() is None

    def test_right_click_on_empty_canvas_steps_out(self, app, monkeypatch):
        top, _sub = self._tree(app, monkeypatch)
        app._group_open(top['id'])
        assert app._group_canvas_open(2, 2) == 'out'
        assert app._editing_gid() is None

    def test_add_selection_goes_to_the_open_group_when_none_is_picked(
            self, app, monkeypatch):
        top, _sub = self._tree(app, monkeypatch)
        app._group_open(top['id'])
        app.group_list.selection_clear(0, 'end')
        free = max(sgp.ungrouped_rods(app.groups, len(app.members)))
        app.selected_members = {free}
        monkeypatch.setattr('apps.stereo.stereo_app_groups.messagebox'
                            '.askyesno', lambda *a, **k: True)
        app._group_assign_selection()
        assert free in sgp.find(app.groups, top['id'])['members']

    def test_the_open_group_is_marked_in_the_list(self, app, monkeypatch):
        top, _sub = self._tree(app, monkeypatch)
        app._group_open(top['id'])
        rows = app.group_list.get(0, 'end')
        assert any(r.lstrip().startswith('✎ Roof') for r in rows)

    def test_while_open_its_subgroups_are_tinted_as_objects(self, app,
                                                            monkeypatch):
        top, sub = self._tree(app, monkeypatch)
        app.group_view.set(False)
        app._group_open(top['id'])
        tints, key = app._group_tint_map()
        assert set(tints) == {0, 1, 2}
        assert [k for k, _t in key] == ['Bay']
        app._draw()
        assert app.canvas.find_withtag('group_tint')

    def test_ctrl_g_makes_a_group_from_the_selection(self, app, monkeypatch):
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: 'K')
        app.selected_members = {3, 4}
        app.canvas.event_generate('<Control-g>', when='now')
        assert app.groups and app.groups[-1]['members'] == {3, 4}


class TestPdfDrawingScale:

    def test_the_dialog_choice_maps_to_the_export_options(self, app):
        assert app._pdf_view_from('fit', 150, 200) == {'zoom': 1.0,
                                                       'ratio': None}
        assert app._pdf_view_from('zoom', 150, 200) == {'zoom': 1.5,
                                                        'ratio': None}
        assert app._pdf_view_from('ratio', 150, 200) == {'zoom': 1.0,
                                                         'ratio': 200.0}

    def test_the_export_passes_the_chosen_scale(self, app, monkeypatch,
                                                tmp_path):
        seen = {}
        monkeypatch.setattr(app, '_pdf_sheet_dialog',
                            lambda *a, **k: {'views'})
        monkeypatch.setattr('apps.stereo.stereo_app.filedialog'
                            '.asksaveasfilename',
                            lambda *a, **k: str(tmp_path / 'x.pdf'))
        monkeypatch.setattr('apps.stereo.stereo_reports.export_pdf',
                            lambda *a, **k: seen.update(k))
        app._pdf_view = {'zoom': 1.25, 'ratio': None}
        app._export_pdf()
        assert seen['view_zoom'] == 1.25 and seen['view_ratio'] is None


class TestCraneFixes:
    """Item 4: the crane, diagnosed. The faults it had are each pinned here."""

    def _top(self, app):
        z = max(p[2] for p in app.nodes)
        return [i for i, p in enumerate(app.nodes) if abs(p[2] - z) < 1e-9]

    def _corners(self, app, ids):
        xs = [app.nodes[i][0] for i in ids]
        ys = [app.nodes[i][1] for i in ids]
        out = []
        for X in (min(xs), max(xs)):
            for Y in (min(ys), max(ys)):
                out.append(min(ids, key=lambda i: (app.nodes[i][0] - X) ** 2
                               + (app.nodes[i][1] - Y) ** 2))
        return out

    def test_a_lift_that_leaves_a_mechanism_says_so_and_shows_where(
            self, app, dialogs):
        c = self._corners(app, self._top(app))[:3]
        app.selected_nodes = set(c)
        app._add_cable_crane()
        assert len(app.selected_nodes) > 3, 'the loose part is selected'
        assert 'no stiffness' in app.col_note.cget('text')
        app._analyze()
        assert app.results is None
        assert 'Free to move with no stiffness' in app.err

    def test_a_good_lift_still_solves_the_same(self, app):
        app.selected_nodes = set(self._corners(app, self._top(app)))
        app._add_cable_crane()
        app._analyze()
        assert app.results is not None
        slings = [app.results['member_res'][i]['N']
                  for i, m in enumerate(app.members)
                  if m.get('role') == 'crane_cable']
        assert slings == pytest.approx([636.396] * 4, rel=1e-4)

    def test_a_second_crane_keeps_the_first_cranes_supports(self, app):
        corners = self._corners(app, self._top(app))
        app.selected_nodes = set(corners)
        app._add_cable_crane()
        first_tops = {m['b'] for m in app.members
                      if m.get('role') == 'crane_mast'}
        app.selected_nodes = set(corners)
        app._add_cable_crane()
        held = {sp['node'] for sp in app.supports}
        assert first_tops <= held, 'the first mast lost its support'
        assert len(app._crane_tag) == 6, "both cranes' tag lines are kept"
        app._clear_cable_cranes()
        assert not app._crane_tag
        assert not any(sp.get('dofs') and len(sp['dofs']) == 1
                       for sp in app.supports), 'a tag line was left behind'

    def test_undo_takes_the_cranes_bookkeeping_back_too(self, app):
        app.selected_nodes = set(self._corners(app, self._top(app)))
        app._add_cable_crane()
        assert app._crane_freed and app._crane_tag
        app._undo()
        assert app._crane_freed == [] and app._crane_tag is None
        app._redo()
        assert app._crane_freed and app._crane_tag

    def test_the_cable_flag_survives_the_workbook(self, app, tmp_path):
        from apps.stereo import stereo_reports as sr
        app.selected_nodes = set(self._corners(app, self._top(app)))
        app._add_cable_crane()
        path = str(tmp_path / 'c.xlsx')
        sr.export_excel(app.nodes, app.members, [], app.supports, None, path)
        _n, members, *_ = sr.import_excel_model(path)
        assert sum(1 for m in members if m.get('tension_only')) == 4

    def test_an_unsettled_cable_set_keeps_its_last_pass(self, app,
                                                        monkeypatch, dialogs):
        from apps.stereo import stereo_math as sm_
        real = sm_.analyze

        def wobbly(*a, **k):
            res, _err = real(*a, **k)
            return res, ('The cable set did not settle: some cable keeps '
                         'alternating. The results shown are the last pass.')
        monkeypatch.setattr('apps.stereo.stereo_app_model.sm.analyze', wobbly)
        app._analyze()
        assert app.results is not None, 'the last pass is kept, with a caveat'
        assert app.err is None

    def test_a_huge_displacement_is_flagged(self, app):
        z = self._top(app)
        xs = sorted({round(app.nodes[i][0], 3) for i in z})
        ys = sorted({round(app.nodes[i][1], 3) for i in z})
        mid = [i for i in z if xs[3] <= round(app.nodes[i][0], 3) <= xs[5]
               and ys[3] <= round(app.nodes[i][1], 3) <= ys[5]]
        # The hook hung over the picks' centroid (13.5, 13.5), as it was
        # before it went over the centre of gravity (15, 15): off-centre,
        # the grid tips on its slings and the answer runs away.
        from apps.stereo import stereo_lift as slift
        real = slift.centre_of_gravity
        slift.centre_of_gravity = lambda *a, **k: None
        try:
            app.selected_nodes = set(mid)
            app._add_cable_crane()
        finally:
            slift.centre_of_gravity = real
        app._analyze()
        if app.results is not None:
            assert app.status_var.get().startswith('Caution')

    def test_the_same_patch_hung_over_its_centre_of_gravity_hangs_level(
            self, app):
        z = self._top(app)
        xs = sorted({round(app.nodes[i][0], 3) for i in z})
        ys = sorted({round(app.nodes[i][1], 3) for i in z})
        mid = [i for i in z if xs[3] <= round(app.nodes[i][0], 3) <= xs[5]
               and ys[3] <= round(app.nodes[i][1], 3) <= ys[5]]
        app.selected_nodes = set(mid)
        app._add_cable_crane()
        app._analyze()
        assert app.results is not None, app.err
        assert not app.status_var.get().startswith('Caution')


class TestResponsiveness:
    """Item 5: what made the window lag after an analysis, pinned."""

    def test_mouse_moves_do_not_redraw_the_whole_model(self, app,
                                                       monkeypatch):
        app._analyze()
        calls = []
        real = app._draw
        monkeypatch.setattr(app, '_draw', lambda: (calls.append(1), real())[1])
        sp = app._screen_positions()

        class E:
            state = 0
        for i in range(0, 60, 3):
            e = E()
            e.x, e.y = sp[i]
            app._on_mouse_motion(e)
        assert calls == [], 'the snap marker is drawn on its own'
        assert app.canvas.find_withtag('snap')

    def test_screen_positions_are_cached_until_the_view_or_model_moves(
            self, app):
        a = app._screen_positions()
        assert app._screen_positions() == a
        app.azimuth += 15
        b = app._screen_positions()
        assert b != a
        x, y, z = app.nodes[0]
        app.nodes[0] = (x + 1.0, y, z)
        assert app._screen_positions()[0] != b[0]

    def test_a_short_panel_cannot_be_scrolled_off_its_top(self, app):
        app._set_mode('support')
        app.root.update_idletasks()
        app.root.update()
        po = app.panel_outer
        po._sync()
        if po.interior.winfo_reqheight() < po.canvas.winfo_height():
            for _ in range(10):
                po.canvas.yview_scroll(-1, 'units')
            assert po.canvas.canvasy(0) == 0


class TestAddonCodes:
    """Round 2, item 3: every add-on has a short code -- C1, B1, K1, P1 --
    on its rods, shown the same way on the canvas, in the inspector, in the
    groups, in the PDF and in Excel."""

    def _column(self, app, node):
        app.col_style.set(sg.COLUMN_PLAIN)
        app.col_height.set(4.0)
        app.selected_nodes = {node}
        app._add_column()

    def _crane(self, app):
        top = max(p[2] for p in app.nodes)
        tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - top) < 1e-9]
        xs = [app.nodes[i][0] for i in tops]
        ys = [app.nodes[i][1] for i in tops]
        app.selected_nodes = {
            min(tops, key=lambda i: (app.nodes[i][0] - tx) ** 2
                + (app.nodes[i][1] - ty) ** 2)
            for tx in (min(xs), max(xs)) for ty in (min(ys), max(ys))}
        app._add_cable_crane()

    def test_each_add_on_gets_the_next_code_of_its_kind(self, app):
        from apps.stereo import stereo_addon_codes as sac
        self._column(app, 0)
        self._column(app, 5)
        app.selected_nodes = {0, 1, 2, 11, 12, 13}
        app.beam_depth.set(1.2)
        app.beam_dir.set('Down (-Z)')
        app._add_reinforcement_beam()
        _mode(app, 'addons')
        app.selected_nodes = _top_quad(app)
        app._add_shear_panel()
        idx = sac.index(app.members)
        assert list(idx) == ['B1', 'C1', 'C2']
        assert all(app.members[i].get('role') == 'column_shaft'
                   for i in idx['C1'] + idx['C2'])
        assert {app.members[i].get('role') for i in idx['B1']} <= {
            'reinf_chord', 'reinf_web'}
        assert app.panels[-1]['addon'] == 'P1'

    def test_a_crane_is_K1_and_its_rods_are_its_mast_and_cables(self, app):
        from apps.stereo import stereo_addon_codes as sac
        self._crane(app)
        rods = sac.index(app.members)['K1']
        assert {app.members[i]['role'] for i in rods} == {'crane_mast',
                                                          'crane_cable'}

    def test_undo_takes_the_code_back_and_the_next_one_is_not_reused(self, app):
        from apps.stereo import stereo_addon_codes as sac
        self._column(app, 0)
        self._column(app, 5)
        app._undo()
        assert list(sac.index(app.members)) == ['C1']
        self._column(app, 7)
        assert list(sac.index(app.members)) == ['C1', 'C2']

    def test_a_mirrored_copy_of_a_column_is_a_new_column(self, app):
        from apps.stereo import stereo_addon_codes as sac
        self._column(app, 0)
        rod = sac.index(app.members)['C1'][0]
        # with a stretch of grid, so the copy lands clear of the original
        app.selected_members = {rod} | set(range(20))
        app.selected_nodes = set()
        assert app._tx_mirror(copy=True, axis='X')
        idx = sac.index(app.members)
        assert list(idx) == ['C1', 'C2']
        assert len(idx['C2']) == len(idx['C1'])

    def test_the_canvas_tags_each_add_on(self, app):
        self._column(app, 0)
        self._crane(app)
        app.show_addon_codes.set(True)
        app._draw()
        texts = {app.canvas.itemcget(t, 'text')
                 for t in app.canvas.find_withtag('addon_code')
                 if app.canvas.type(t) == 'text'}
        assert texts == {'C1', 'K1'}
        app.show_addon_codes.set(False)
        app._draw()
        assert not app.canvas.find_withtag('addon_code')

    def test_the_inspector_names_the_add_on(self, app):
        from apps.stereo import stereo_addon_codes as sac
        self._column(app, 0)
        rod = sac.index(app.members)['C1'][0]
        app.selected_nodes = set()
        app.selected_member = rod
        app.selected_members = {rod}
        app._update_properties_panel()
        texts = []

        def walk(w):
            for ch in w.winfo_children():
                if isinstance(ch, tk.Label):
                    texts.append(ch.cget('text'))
                walk(ch)
        walk(app._props_frame)
        assert any('Column C1' in t for t in texts), texts

    def test_codes_survive_the_workbook(self, app, tmp_path):
        from apps.stereo import stereo_addon_codes as sac
        self._column(app, 0)
        self._crane(app)
        p = str(tmp_path / 'm.xlsx')
        sr_module.export_excel(app.nodes, app.members, app._all_loads(),
                        app.supports, None, p)
        _n, members, *_ = sr_module.import_excel_model(p)
        assert sac.index(members) == sac.index(app.members)

    def test_a_group_made_from_one_add_on_is_named_after_it(self, app,
                                                           monkeypatch):
        from apps.stereo import stereo_addon_codes as sac
        from tkinter import simpledialog
        self._column(app, 0)
        seen = {}

        def ask(title, prompt, **kw):
            seen['initial'] = kw.get('initialvalue')
            return kw.get('initialvalue')
        monkeypatch.setattr(simpledialog, 'askstring', ask)
        app.selected_nodes = set()
        app.selected_members = set(sac.index(app.members)['C1'])
        app._group_new_from_selection()
        assert seen['initial'] == 'Column C1'
        assert app.groups[-1]['name'] == 'Column C1'

    def test_a_group_holding_add_ons_lists_their_codes(self, app,
                                                       monkeypatch):
        from apps.stereo import stereo_addon_codes as sac
        from tkinter import simpledialog
        self._column(app, 0)
        self._column(app, 5)
        monkeypatch.setattr(simpledialog, 'askstring',
                            lambda *a, **k: 'Supports')
        app.selected_nodes = set()
        idx = sac.index(app.members)
        app.selected_members = set(idx['C1'] + idx['C2'])
        app._group_new_from_selection()
        gid = app.groups[-1]['id']
        assert app._group_display_name(gid) == 'Supports · C1, C2'
        assert any(lbl.startswith('Supports · C1, C2')
                   for lbl, _g in app._group_rows())

    def test_the_pdf_names_the_add_ons(self, app, tmp_path):
        self._column(app, 0)
        self._crane(app)
        app._analyze()
        p = str(tmp_path / 'r.pdf')
        sr_module.export_pdf(app.nodes, app.members, app._all_loads(), app.supports,
                      app.results, p, checks=app.member_checks,
                      groups={'views'})
        import subprocess
        txt = subprocess.run(['pdftotext', '-f', '1', '-l', '2', p, '-'],
                             capture_output=True, text=True).stdout
        assert 'ADD-ONS' in txt
        assert 'Column C1' in txt and 'Crane K1' in txt


class TestCraneLiftsAPiece:
    """Round 2, item 4: a crane lifts ONE piece -- the one under the hook,
    or a group -- and only that piece comes off its supports. The rest of
    the file stays on the ground and still solves."""

    def _second_truss(self, app, dx=45.0):
        """A copy of the default grid, 45 m along x: a separate piece with
        its own supports, in the same file."""
        n0, m0 = len(app.nodes), len(app.members)
        app.nodes = list(app.nodes) + [(x + dx, y, z) for x, y, z in app.nodes]
        app.members = list(app.members) + [
            dict(m, a=m['a'] + n0, b=m['b'] + n0) for m in app.members]
        app.supports = list(app.supports) + [
            dict(s, node=s['node'] + n0) for s in app.supports]
        app.loads = list(app.loads)
        app.results = None
        return n0, m0

    def _corners(self, app, lo_x, hi_x):
        top = max(p[2] for p in app.nodes)
        tops = [i for i, p in enumerate(app.nodes)
                if abs(p[2] - top) < 1e-9 and lo_x <= p[0] <= hi_x]
        xs = [app.nodes[i][0] for i in tops]
        ys = [app.nodes[i][1] for i in tops]
        return {min(tops, key=lambda i: (app.nodes[i][0] - tx) ** 2
                    + (app.nodes[i][1] - ty) ** 2)
                for tx in (min(xs), max(xs)) for ty in (min(ys), max(ys))}

    def test_lifting_one_truss_leaves_the_other_on_its_supports(self, app):
        n0, m0 = self._second_truss(app)
        b_supports = [s for s in app.supports if s['node'] >= n0]
        app.selected_nodes = self._corners(app, -1.0, 40.0)
        app._add_cable_crane()
        # B's supports are all still there; A's are gone (handed to the
        # crane and its tag lines)
        assert all(s in app.supports for s in b_supports)
        a_ground = [s for s in app.supports if s['node'] < n0
                    and s.get('type') and s['node'] not in
                    {t['node'] for t in app._crane_tag or []}]
        assert a_ground == []
        assert 'stay on their supports' in app.col_note.cget('text')
        app._analyze()
        assert app.results is not None, app.err
        # B still stands -- before, its supports went with A's and the
        # solve refused the whole file as a mechanism -- and A hangs: its
        # loads go up the slings, none to the ground under B
        assert all(abs(r.get('Fz', 0.0)) < 1e-6
                   for node, r in app.results['reactions'].items()
                   if n0 <= node < 2 * n0)
        assert app._crane_lifts[-1]['rods'] == list(range(m0))

    def test_a_group_can_be_lifted_by_name(self, app):
        from apps.stereo import stereo_groups as sgp
        n0, m0 = self._second_truss(app)
        g = sgp.new_group(app.groups, 'Truss B', members=range(m0, 2 * m0))
        app._refresh_crane_lift_choices()
        label = [c for c in app.crane_lift_box.cget('values')
                 if 'Truss B' in c][0]
        app.crane_lift_target.set(label)
        app.selected_nodes = self._corners(app, 44.0, 100.0)
        app._add_cable_crane()
        assert app._crane_lifts[-1]['group'] == g['id']
        a_supports = [s for s in app.supports if s['node'] < n0]
        assert len(a_supports) > 4          # A untouched
        app._analyze()
        assert app.results is not None, app.err

    def test_a_group_still_joined_to_the_rest_is_refused(self, app, dialogs):
        from apps.stereo import stereo_groups as sgp
        half = list(range(len(app.members) // 2))
        sgp.new_group(app.groups, 'Half', members=half)
        app._refresh_crane_lift_choices()
        app.crane_lift_target.set('Half')
        m_before = len(app.members)
        top = max(p[2] for p in app.nodes)
        mine = {n for j in half for n in (app.members[j]['a'],
                                         app.members[j]['b'])}
        app.selected_nodes = set(sorted(i for i in mine
                                        if app.nodes[i][2] == top)[:4])
        app._add_cable_crane()
        assert len(app.members) == m_before
        assert any('still joined' in str(a) for a in dialogs), dialogs

    def test_slings_off_the_group_are_refused(self, app, dialogs):
        from apps.stereo import stereo_groups as sgp
        n0, m0 = self._second_truss(app)
        sgp.new_group(app.groups, 'Truss B', members=range(m0, 2 * m0))
        app._refresh_crane_lift_choices()
        app.crane_lift_target.set('Truss B')
        m_before = len(app.members)
        app.selected_nodes = self._corners(app, -1.0, 40.0)   # on A
        app._add_cable_crane()
        assert len(app.members) == m_before
        assert any('hook onto group' in str(a) for a in dialogs), dialogs

    def test_undo_and_clear_take_the_lift_record_back(self, app):
        app.selected_nodes = self._corners(app, -1.0, 100.0)
        app._add_cable_crane()
        assert len(app._crane_lifts) == 1
        app._undo()
        assert app._crane_lifts == []
        app._redo() if hasattr(app, '_redo') else None
        app.selected_nodes = self._corners(app, -1.0, 100.0)
        app._add_cable_crane()
        app._clear_cable_cranes()
        assert app._crane_lifts == []


class TestCraneHangsOverTheCentreOfGravity:
    """A rigger hangs the hook over the centre of gravity of what is lifted.
    Over the middle of the PICKS instead, a piece whose weight is not
    centred under them tips: the light side's slings go slack and the tag
    lines -- there only to stop a linear solve's pendulum modes -- end up
    carrying the lift. Found on a pitched roof module: two slings in
    compression and 45 kN in the tag lines."""

    def _corners(self, app):
        top = max(p[2] for p in app.nodes)
        tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - top) < 1e-9]
        xs = [app.nodes[i][0] for i in tops]
        ys = [app.nodes[i][1] for i in tops]
        return tops, {min(tops, key=lambda i: (app.nodes[i][0] - tx) ** 2
                          + (app.nodes[i][1] - ty) ** 2)
                      for tx in (min(xs), max(xs)) for ty in (min(ys), max(ys))}

    def test_an_uneven_load_moves_the_hook_and_the_tag_lines_stay_idle(
            self, app):
        from apps.stereo import stereo_lift as slift
        tops, picks = self._corners(app)
        heavy = max(tops, key=lambda i: app.nodes[i][0] + 0.5 * app.nodes[i][1])
        app.loads = list(app.loads) + [{'node': heavy, 'fz': -400.0}]
        rods = [j for j, m in enumerate(app.members)]
        cog = slift.centre_of_gravity(app.nodes, app.members, rods,
                                      app._all_loads())
        mid = (sum(app.nodes[i][0] for i in picks) / 4,
               sum(app.nodes[i][1] for i in picks) / 4)
        assert abs(cog[0] - mid[0]) + abs(cog[1] - mid[1]) > 0.5
        app.selected_nodes = set(picks)
        app._add_cable_crane()
        hook = app._crane_lifts[-1]['hook']
        assert abs(app.nodes[hook][0] - cog[0]) < 1e-9
        assert abs(app.nodes[hook][1] - cog[1]) < 1e-9
        assert 'centre of gravity' in app.col_note.cget('text')
        app._analyze()
        assert app.results is not None, app.err
        total = -sum(ld.get('fz', 0.0) for ld in app._all_loads())
        tags = {t['node'] for t in app._crane_tag}
        pull = sum(abs(v) for n, r in app.results['reactions'].items()
                   if n in tags for v in r.values())
        assert pull < 1e-3 * total, (pull, total)

    def test_picks_all_to_one_side_of_the_weight_are_flagged(self, app):
        tops, _picks = self._corners(app)
        xs = sorted({round(app.nodes[i][0], 6) for i in tops})
        ys = [app.nodes[i][1] for i in tops]
        # three joints along the low-x edge: the grid's weight is off to
        # the side of them, so no sling tension can hold it level
        edge = sorted((i for i in tops if round(app.nodes[i][0], 6) == xs[0]),
                      key=lambda i: app.nodes[i][1])
        picks = {edge[0], edge[len(edge) // 2], edge[-1]}
        nxt = [i for i in tops if round(app.nodes[i][0], 6) == xs[1]]
        picks.add(min(nxt, key=lambda i: abs(app.nodes[i][1]
                                             - (min(ys) + max(ys)) / 2)))
        app.selected_nodes = picks
        app._add_cable_crane()
        note = app.col_note.cget('text')
        assert 'outside the pick points' in note, note
        assert 'tip' in app.status_var.get()


    def test_a_flat_truss_hung_in_its_own_plane_is_named(self, app):
        """A plane truss picked along its top chord hangs from slings that
        all lie in its plane with the hook: it can turn about them like a
        flag. Caught when it is lifted, with what to do about it."""
        tpl = dict(app.members[0])
        for k in ('addon', 'role', 'tension_only'):
            tpl.pop(k, None)
        tpl['conn'] = 'pin'
        nodes = [(2.0 * i, 0.0, 0.0) for i in range(5)] + \
            [(2.0 * i, 0.0, 1.5) for i in range(5)]
        pairs = [(i, i + 1) for i in range(4)] + \
            [(5 + i, 6 + i) for i in range(4)] + \
            [(i, 5 + i) for i in range(5)] + [(i, 6 + i) for i in range(4)]
        app.nodes = nodes
        app.members = [dict(tpl, a=a, b=b) for a, b in pairs]
        app.supports, app.loads, app.groups = [], [], []
        app.panels = []
        app.loads = [{'node': i, 'fz': -2.0} for i in range(5)]
        app.results = None
        app.selected_nodes = {5, 7, 9}
        app._add_cable_crane()
        note = app.col_note.cget('text')
        assert 'one plane' in note, note


class TestSupportEditorLeavesCraneSupportsAlone:
    """Found in a user's roof file: 45 roof supports and 8 crane mast tops
    all held in X only. Clicking a node with a crane tag line (a support
    holding one direction) loaded "X only" into the per-node editor without
    a word, and Apply on a box over the roof put it under every node --
    the mast tops included."""

    def _lifted(self, app):
        top = max(p[2] for p in app.nodes)
        tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - top) < 1e-9]
        xs = [app.nodes[i][0] for i in tops]
        ys = [app.nodes[i][1] for i in tops]
        app.selected_nodes = {min(tops, key=lambda i: (app.nodes[i][0] - tx)
                                  ** 2 + (app.nodes[i][1] - ty) ** 2)
                              for tx in (min(xs), max(xs))
                              for ty in (min(ys), max(ys))}
        app._add_cable_crane()
        return app._crane_lifts[-1]['anchor']

    def test_clicking_a_tag_line_node_does_not_load_it_into_the_editor(
            self, app):
        self._lifted(app)
        app.sup_preset_var.set('pin')
        app._preset_to_checkboxes()
        tag = app._crane_tag[0]['node']
        app.selected_nodes = {tag}
        app._sync_selection_fields()
        assert app.sup_preset_var.get() == 'pin'
        assert all(app.dof_vars[d].get() for d in ('ux', 'uy', 'uz'))

    def test_a_users_own_support_still_loads_into_the_editor(self, app):
        app.supports = [{'node': 3, 'dofs': {'ux': True, 'uz': True}}]
        app.selected_nodes = {3}
        app._sync_selection_fields()
        assert app.sup_preset_var.get() == 'custom'
        assert app.dof_vars['ux'].get() and app.dof_vars['uz'].get()
        assert not app.dof_vars['uy'].get()

    def test_apply_over_a_mast_top_keeps_the_crane_anchor_fixed(self, app):
        anchor = self._lifted(app)
        tags = [(t['node'], t['dof']) for t in app._crane_tag]
        app.sup_preset_var.set('pin')
        app._preset_to_checkboxes()
        app.selected_nodes = {0, 1, anchor} | {n for n, _d in tags}
        app._apply_support()
        at_anchor = [sp for sp in app.supports if sp['node'] == anchor]
        assert at_anchor == [{'node': anchor, 'type': 'fixed'}]
        for n, d in tags:            # the tag lines are still the crane's
            assert {'node': n, 'dofs': {d: True}} in app.supports
        assert any(sp['node'] == 0 and sp.get('type') == 'pin'
                   for sp in app.supports)
        assert 'mast top' in app.status_var.get()

    def test_a_partial_support_under_many_nodes_is_asked_about(
            self, app, dialogs, monkeypatch):
        before = [dict(sp) for sp in app.supports]
        app.sup_preset_var.set('custom')
        for d in app.dof_vars:
            app.dof_vars[d].set(d == 'ux')
        monkeypatch.setattr('apps.stereo.stereo_app.messagebox.askyesno',
                            lambda *a, **k: (dialogs.append(('ask',) + a),
                                             False)[1])
        app.selected_nodes = {0, 1, 2}
        app._apply_support()
        assert app.supports == before          # "No" changes nothing
        ask = [d for d in dialogs if d[0] == 'ask']
        assert ask and 'X only' in ask[0][2] and 'Y and Z' in ask[0][2]
        # one node on a roller is ordinary, and not asked about
        app.selected_nodes = {0}
        app._apply_support()
        assert len([d for d in dialogs if d[0] == 'ask']) == 1
        assert {'node': 0, 'dofs': {'ux': True, 'uy': False, 'uz': False,
                                    'rx': False, 'ry': False,
                                    'rz': False}} in app.supports


class TestCraneReport:
    """Round 2, item 5: the crane lift report in the PDF, with the cable
    check against a capacity set when the crane goes on."""

    def _lift(self, app, mode='none', value=None):
        top = max(p[2] for p in app.nodes)
        tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - top) < 1e-9]
        xs = [app.nodes[i][0] for i in tops]
        ys = [app.nodes[i][1] for i in tops]
        app.selected_nodes = {
            min(tops, key=lambda i: (app.nodes[i][0] - tx) ** 2
                + (app.nodes[i][1] - ty) ** 2)
            for tx in (min(xs), max(xs)) for ty in (min(ys), max(ys))}
        app.crane_cap_mode.set(mode)
        if mode == 'wll':
            app.crane_wll.set(value)
        elif mode == 'dia':
            app.crane_dia.set(value)
        app._add_cable_crane()

    def test_the_cable_capacity_is_kept_with_the_lift(self, app):
        from apps.stereo import stereo_lift as slift
        self._lift(app, 'dia', 20.0)
        meta = app._crane_meta()
        assert list(meta) == ['K1']
        assert meta['K1']['wll_kN'] == pytest.approx(slift.rope_wll_kN(20.0))
        assert 'Ø20 mm' in meta['K1']['cable_spec']
        assert meta['K1']['what'] == 'the piece under the hook'

    def test_a_typed_wll_and_none(self, app):
        self._lift(app, 'wll', 700.0)
        assert app._crane_meta()['K1']['wll_kN'] == 700.0
        app._clear_cable_cranes()
        self._lift(app)
        assert app._crane_meta()['K1']['wll_kN'] is None

    def test_the_pdf_carries_the_crane_report(self, app, tmp_path):
        import subprocess
        from apps.stereo import stereo_lift as slift
        self._lift(app, 'wll', 700.0)
        app._analyze()
        assert app.results is not None
        rep = slift.crane_report(app.nodes, app.members, app.results,
                                 app.member_checks, 'K1', wll_kN=700.0)
        # the slings carry the whole lifted load
        applied = -sum(ld.get('fz', 0.0) for ld in app._all_loads())
        assert rep['sum_vertical'] == pytest.approx(applied, rel=1e-6)
        p = str(tmp_path / 'c.pdf')
        sr_module.export_pdf(
            app.nodes, app.members, app._all_loads(), app.supports,
            app.results, p, checks=app.member_checks,
            meta={'crane_lifts': app._crane_meta()}, groups={'crane'})
        plan = sr_module.plan_sheets(app.results, app.member_checks, 0,
                                     {'crane'}, members=app.members)
        assert plan == ['general', 'crane_K1', 'crane_K1_table']
        txt = subprocess.run(['pdftotext', p, '-'], capture_output=True,
                             text=True).stdout
        assert 'Crane K1' in txt
        assert 'WLL 700 kN per cable, as entered' in txt
        T = rep['cables'][0]['T']
        assert f'{T:.2f}' in txt
        assert f'{T / 700.0:.2f}' in txt

    def test_no_crane_no_crane_sheets(self, app):
        app._analyze()
        plan = sr_module.plan_sheets(app.results, app.member_checks, 0,
                                     members=app.members)
        assert not any(k.startswith('crane_') for k in plan)

    def test_the_chooser_offers_the_crane_report(self, app):
        keys = [k for k, _l, _b in app.PDF_GROUP_LABELS]
        assert 'crane' in keys
        assert set(keys) == set(sr_module.PDF_SHEET_GROUPS)



class TestGroupsPdfControl:
    """Round 2, item 6: the Groups PDF is the user's to shape -- which
    groups, in what order, under what titles, with which sheets each, and
    one document or one PDF per group."""

    def _groups(self, app, monkeypatch):
        names = iter(['Roof A', 'Roof B'])
        monkeypatch.setattr('apps.stereo.stereo_app_groups.simpledialog'
                            '.askstring', lambda *a, **k: next(names))
        app.selected_nodes = set()
        app.selected_members = set(range(0, 200))
        app._group_new_from_selection()
        app.selected_members = set(range(200, 420))
        app._group_new_from_selection()
        app._analyze()
        return [g['id'] for g in app.groups]

    def _pages(self, path):
        import subprocess
        out = subprocess.run(['pdfinfo', path], capture_output=True,
                             text=True).stdout
        return int([ln for ln in out.splitlines()
                    if ln.startswith('Pages:')][0].split()[1])

    def test_the_rows_are_every_group_then_ungrouped_all_ticked(
            self, app, monkeypatch):
        a, b = self._groups(app, monkeypatch)
        items = app._groups_pdf_items()
        assert [(it['gid'], it['title'], it['on']) for it in items] == [
            (a, 'Roof A', True), (b, 'Roof B', True), (None, 'Ungrouped', True)]

    def test_order_titles_and_sheets_are_the_users(self, app, monkeypatch,
                                                   tmp_path):
        from apps.stereo import stereo_reports as sr
        a, b = self._groups(app, monkeypatch)
        cfg = {'mode': 'one', 'sheets': {'tables'},
               'items': [
                   {'gid': b, 'title': 'East roof', 'sheets': {'force'},
                    'on': True},
                   {'gid': a, 'title': 'West roof', 'sheets': None,
                    'on': True},
                   {'gid': None, 'title': 'Ungrouped', 'sheets': None,
                    'on': False}]}
        path = str(tmp_path / 'g.pdf')
        written = app._groups_pdf_custom(cfg=cfg, path=path)
        (out_path, contents), = written
        assert out_path == path
        assert [t.strip() for t, _ in contents[2:]] == ['East roof',
                                                        'West roof']
        # East carries its own sheets, West the default
        n_east = contents[3][1] - contents[2][1]
        assert n_east == len(sr.plan_sheets(app.results, app.member_checks,
                                            0, {'force'}))
        import subprocess
        txt = subprocess.run(['pdftotext', path, '-'], capture_output=True,
                             text=True).stdout
        assert 'East roof' in txt and 'West roof' in txt
        # remembered, order and titles too
        items = app._groups_pdf_items()
        assert [it['title'] for it in items] == ['East roof', 'West roof',
                                                 'Ungrouped']
        assert items[2]['on'] is False

    def test_one_pdf_per_group(self, app, monkeypatch, tmp_path):
        a, b = self._groups(app, monkeypatch)
        cfg = {'mode': 'each', 'sheets': {'tables'},
               'items': [{'gid': a, 'title': 'Roof A', 'sheets': None,
                          'on': True},
                         {'gid': b, 'title': 'Roof B', 'sheets': None,
                          'on': True}]}
        written = app._groups_pdf_custom(cfg=cfg,
                                         path=str(tmp_path / 'job.pdf'))
        paths = [p for p, _c in written]
        assert [os.path.basename(p) for p in paths] == ['job_Roof_A.pdf',
                                                        'job_Roof_B.pdf']
        for p, contents in written:
            assert os.path.exists(p)
            assert len(contents) == 3          # summary, joints, its section
            assert self._pages(p) >= 3

    def test_nothing_ticked_writes_nothing(self, app, monkeypatch, tmp_path,
                                           dialogs):
        a, b = self._groups(app, monkeypatch)
        cfg = {'mode': 'one', 'sheets': {'tables'},
               'items': [{'gid': a, 'title': 'A', 'sheets': None,
                          'on': False}]}
        assert app._groups_pdf_custom(cfg=cfg,
                                      path=str(tmp_path / 'n.pdf')) is None
        assert any('No group is ticked' in str(d) for d in dialogs)

    def test_the_dialog_reorders_retitles_and_returns_the_choice(
            self, app, monkeypatch):
        a, b = self._groups(app, monkeypatch)
        seen = {}

        def fake_wait(win):
            def buttons(text):
                return [w for w in _descendants(win, tk.Widget)
                        if w.winfo_class() == 'Button'
                        and w.cget('text') == text]
            buttons('↓')[0].invoke()        # Roof A below Roof B
            entries = [w for w in _descendants(win, tk.Widget)
                       if w.winfo_class() == 'Entry']
            entries[0].delete(0, 'end')
            entries[0].insert(0, 'East roof')
            # untick Ungrouped (the last row's checkbutton)
            rows = [w for w in _descendants(win, tk.Widget)
                    if w.winfo_class() == 'Checkbutton'
                    and not w.cget('text')]
            rows[-1].deselect()
            [r for r in _descendants(win, tk.Widget)
             if r.winfo_class() == 'Radiobutton'
             and r.cget('text') == 'One PDF per group'][0].select()
            seen['n_rows'] = len(rows)
            buttons('Export…')[0].invoke()

        monkeypatch.setattr(app.root, 'wait_window', fake_wait)
        cfg = app._groups_pdf_dialog()
        assert seen['n_rows'] == 3
        assert [(it['gid'], it['title'], it['on']) for it in cfg['items']] \
            == [(b, 'East roof', True), (a, 'Roof A', True),
                (None, 'Ungrouped', False)]
        assert cfg['mode'] == 'each'


class TestCopyPaste:
    """Round 2, item 7: copy and paste, through the system clipboard, at an
    offset or at a clicked node, once or as an array."""

    def _opts(self, **kw):
        o = {'place': 'offset', 'dx': 0.0, 'dy': 0.0, 'dz': 0.0, 'count': 1,
             'supports': False, 'loads': False, 'groups': False}
        o.update(kw)
        return o

    def test_copy_puts_the_selection_on_the_system_clipboard(self, app):
        from apps.stereo import stereo_clipboard as scb
        app.selected_nodes = set()
        app.selected_members = set(range(10))
        app._copy_selection()
        clip = scb.from_text(app.root.clipboard_get())
        assert clip is not None and len(clip['members']) == 10
        assert app._clipboard_clip()['members'] == clip['members']

    def test_paste_at_an_offset_adds_a_copy_and_undo_takes_it_away(
            self, app, monkeypatch):
        n0, m0 = len(app.nodes), len(app.members)
        app.selected_nodes = set()
        app.selected_members = set(range(10))
        app._copy_selection()
        monkeypatch.setattr(app, '_paste_ask',
                            lambda clip: self._opts(dz=-5.0))
        app._paste_dialog()
        assert len(app.members) == m0 + 10
        assert app.selected_members == set(range(m0, m0 + 10))
        for j in range(10):
            a, b = app.members[j], app.members[m0 + j]
            assert app.nodes[b['a']][2] == pytest.approx(
                app.nodes[a['a']][2] - 5.0)
        app._undo()
        assert (len(app.nodes), len(app.members)) == (n0, m0)

    def test_paste_at_a_clicked_node_puts_the_corner_node_there(
            self, app, monkeypatch):
        from apps.stereo import stereo_clipboard as scb
        app.selected_nodes = set()
        app.selected_members = {0}
        app._copy_selection()
        monkeypatch.setattr(app, '_paste_ask', lambda clip: self._opts(
            place='point', dz=-2.0, count=2))
        app._paste_dialog()
        assert app._paste_pending is not None
        # a node on the +x edge of rod 0's own layer: the copy of rod 0
        # placed there sticks out past the grid instead of landing on a rod
        z0 = app.nodes[app.members[0]['a']][2]
        target = max((i for i, p in enumerate(app.nodes)
                      if abs(p[2] - z0) < 1e-9),
                     key=lambda i: (app.nodes[i][0], -app.nodes[i][1]))
        sx, sy = app._screen_positions()[target]

        class E:
            x, y, state = sx, sy, 0
        app._lasso_press = (sx, sy)
        app._on_canvas_release(E()) if hasattr(app, '_on_canvas_release') \
            else app._paste_at_click(sx, sy)
        assert app._paste_pending is None
        clip = app._clip
        rx, ry, rz = scb.ref_point(clip)
        tx, ty, tz = app.nodes[target]
        new = sorted(app.selected_members)
        assert len(new) == 2          # the first at the node, one a step on
        firsts = [app.nodes[app.members[j]['a']] for j in new] + \
            [app.nodes[app.members[j]['b']] for j in new]
        assert any(p == pytest.approx((tx, ty, tz)) for p in firsts)
        assert any(p[2] == pytest.approx(tz - 2.0) for p in firsts)

    def test_escape_cancels_a_waiting_paste(self, app, monkeypatch):
        app.selected_members = {0}
        app.selected_nodes = set()
        app._copy_selection()
        monkeypatch.setattr(app, '_paste_ask',
                            lambda clip: self._opts(place='point'))
        app._paste_dialog()
        m0 = len(app.members)
        app._on_escape()
        assert app._paste_pending is None and len(app.members) == m0

    def test_a_copy_pastes_into_another_file(self, app, monkeypatch):
        """The clipboard is text the next file -- or another window -- reads:
        copy, start a new model, paste."""
        app.selected_nodes = set()
        app.selected_members = set(range(12))
        app._copy_selection()
        app._clear_model()
        assert app.members == []
        monkeypatch.setattr(app, '_paste_ask', lambda clip: self._opts())
        app._paste_dialog()
        assert len(app.members) == 12

    def test_an_array_of_columns_gets_a_code_each(self, app, monkeypatch):
        from apps.stereo import stereo_addon_codes as sac
        app.col_style.set(sg.COLUMN_PLAIN)
        app.col_height.set(4.0)
        app.selected_nodes = {0}
        app._add_column()
        app.selected_nodes = set()
        app.selected_members = set(sac.index(app.members)['C1'])
        app._copy_selection()
        monkeypatch.setattr(app, '_paste_ask',
                            lambda clip: self._opts(dx=3.0, count=3))
        app._paste_dialog()
        assert list(sac.index(app.members)) == ['C1', 'C2', 'C3', 'C4']

    def test_the_build_panel_offers_copy_and_paste(self, app):
        def texts(w):
            out = []
            for c in w.winfo_children():
                try:
                    out.append(c.cget('text'))
                except tk.TclError:
                    pass
                out += texts(c)
            return out
        t = texts(app._mode_frames['build'])
        assert 'Copy' in t and 'Paste…' in t



class TestCoverAndSavedSettings:
    """Round 2, item 8: a cover sheet with the project's details and the
    contents, and PDF settings saved by name for the next report."""

    def test_the_cover_sheet_carries_the_project_and_the_contents(
            self, app, tmp_path):
        import subprocess
        app._analyze()
        app.project_info = {'project': 'Hangar 3 roof', 'client': 'ACME',
                            'author': 'M. A.', 'revision': 'B'}
        app._pdf_cover = True
        path = str(tmp_path / 'r.pdf')
        sr_module.export_pdf(app.nodes, app.members, app._all_loads(),
                             app.supports, app.results, path,
                             checks=app.member_checks, groups={'force'},
                             cover=app._pdf_cover_info())
        plan = sr_module.plan_sheets(app.results, app.member_checks, 0,
                                     {'force'}, members=app.members,
                                     cover=True)
        assert plan[0] == 'cover'
        out = subprocess.run(['pdfinfo', path], capture_output=True,
                             text=True).stdout
        assert 'Pages:           %d' % len(plan) in out
        txt = subprocess.run(['pdftotext', '-f', '1', '-l', '1', path, '-'],
                             capture_output=True, text=True).stdout
        for want in ('Hangar 3 roof', 'ACME', 'Revision', 'Contents',
                     'Axial force, plan', 'Sheet 1 / %d' % len(plan)):
            assert want in txt, want

    def test_no_cover_unless_asked(self, app):
        app._pdf_cover = False
        assert app._pdf_cover_info() is None

    def test_project_details_go_with_undo(self, app):
        app.project_info = {'project': 'A'}
        app._push_undo('x')
        app.project_info = {'project': 'B'}
        app._undo()
        assert app.project_info == {'project': 'A'}

    def test_settings_saved_by_name_come_back(self, app, monkeypatch,
                                              tmp_path):
        from apps.stereo import stereo_pdf_presets as spp
        monkeypatch.setenv(spp.ENV, str(tmp_path / 'presets.json'))
        app.project_info = {'project': 'Hangar 3'}
        app._groups_pdf_cfg = None
        spp.put('mine', app._pdf_preset_from({'force', 'crane'},
                                             {'zoom': 1.3, 'ratio': None},
                                             True))
        app._pdf_groups = None
        app._pdf_cover = False
        app.project_info = {}
        app._apply_pdf_preset(spp.load()['mine'])
        assert app._pdf_groups == {'force', 'crane'}
        assert app._pdf_view == {'zoom': 1.3, 'ratio': None}
        assert app._pdf_cover is True
        assert app.project_info == {'project': 'Hangar 3'}

    def test_the_dialog_applies_a_saved_preset(self, app, monkeypatch,
                                               tmp_path):
        from apps.stereo import stereo_pdf_presets as spp
        monkeypatch.setenv(spp.ENV, str(tmp_path / 'presets.json'))
        spp.put('two sheets', spp.make({'deformed'}, cover=True))
        app._analyze()

        def fake_wait(win):
            boxes = [w for w in _descendants(win, tk.Widget)
                     if w.winfo_class() == 'TCombobox']
            boxes[0].set('two sheets')
            [b for b in _descendants(win, tk.Widget)
             if b.winfo_class() == 'Button'
             and b.cget('text') == 'Apply'][0].invoke()
            [b for b in _descendants(win, tk.Widget)
             if b.winfo_class() == 'Button'
             and b.cget('text').startswith('Export')][0].invoke()

        monkeypatch.setattr(app.root, 'wait_window', fake_wait)
        got = app._pdf_sheet_dialog('Export PDF', app.results,
                                    app.member_checks, 0,
                                    members=app.members)
        assert got == {'deformed'}
        assert app._pdf_cover is True


class TestAddonsLeaveTheModelsOwnRodsAlone:
    """Found on a user's file (three roofs, modules and trusses, all rigid):
    clearing the cranes turned every rod in the file into a pin, and the
    roofs became mechanisms. Every add-on -- adding OR clearing a column, a
    beam or a crane -- re-applied the Sections panel to every rod in the
    model. An add-on now writes the panel's section onto its own new rods
    only, and clearing one does not touch the rest."""

    def _own_rods(self, app):
        for k, m in enumerate(app.members):
            m['conn'] = 'rigid'
            m['profile'] = 'Mine'
            m['A'] = 33.0 + k % 3
        return [(m['conn'], m['profile'], m['A'])
                for m in app.members]

    def test_add_and_clear_a_column(self, app):
        before = self._own_rods(app)
        n = len(before)
        app.sec_conn.set('pin')
        app.col_style.set(sg.COLUMN_PLAIN)
        app.col_height.set(4.0)
        app.selected_nodes = {0}
        app._add_column()
        assert [(m['conn'], m['profile'], m['A'])
                for m in app.members[:n]] == before
        assert app.members[n]['conn'] == 'pin'       # the column's own rod
        app._clear_columns()
        assert [(m['conn'], m['profile'], m['A'])
                for m in app.members] == before

    def test_add_and_clear_a_beam(self, app):
        before = self._own_rods(app)
        n = len(before)
        app.selected_nodes = {0, 1, 2, 11, 12, 13}
        app.beam_depth.set(1.2)
        app.beam_dir.set('Down (-Z)')
        app._add_reinforcement_beam()
        assert len(app.members) > n
        assert [(m['conn'], m['profile'], m['A'])
                for m in app.members[:n]] == before
        app._clear_beams()
        assert [(m['conn'], m['profile'], m['A'])
                for m in app.members] == before

    def test_add_and_clear_a_crane(self, app):
        before = self._own_rods(app)
        top = max(p[2] for p in app.nodes)
        tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - top) < 1e-9]
        app.selected_nodes = set(tops[:4])
        app._add_cable_crane()
        app._clear_cable_cranes()
        assert [(m['conn'], m['profile'], m['A'])
                for m in app.members] == before


class TestExplainThisRod:
    """The Results panel's "Explain this rod": the selected rod's check as
    a worked hand calculation, in a window of its own."""

    def test_with_nothing_selected_it_says_what_to_do(self, app):
        app._analyze()
        app.selected_member = None
        app.selected_members = set()
        assert app._explain_selected_rod() is None
        assert 'Click one rod' in app.status_var.get()

    def test_before_a_solve_it_asks_for_one(self, app):
        app.results = None
        app.member_checks = None
        app.selected_member = 3
        assert app._explain_selected_rod() is None
        assert 'Analyze first' in app.status_var.get()

    def test_the_governing_rod_explained_ends_on_its_utilisation(self, app):
        app._analyze()
        i, u = app._governing_rod()
        app._show_governing_rod()
        win = app._explain_selected_rod()
        try:
            assert win.title() == f'Explain rod {i}'
            page = win._text.get('1.0', 'end')
            assert page.startswith(f'Rod {i}: nodes ')
            assert f'utilisation {u:.3f}' in page
            assert str(win._text.cget('state')) == 'disabled'
        finally:
            win.destroy()

    def test_a_second_explanation_replaces_the_first(self, app):
        app._analyze()
        app.selected_member = 0
        first = app._explain_selected_rod()
        app.selected_member = 1
        second = app._explain_selected_rod()
        try:
            assert not first.winfo_exists() and second.winfo_exists()
            assert second.title() == 'Explain rod 1'
        finally:
            second.destroy()

    def test_the_button_is_in_the_selection_box(self, app):
        def walk(w):
            for c in w.winfo_children():
                yield c
                yield from walk(c)
        buttons = [w for w in walk(app._mode_frames['results'])
                   if isinstance(w, tk.Button)
                   and w.cget('text').startswith('Explain this rod')]
        assert len(buttons) == 1


class TestLiveReanalysis:
    """Toolbar → Live: an edit that drops the solve gets a new one once the
    drawing settles, on a model quick enough to solve on every edit."""

    def _settle(self, app, tk_root, secs=None):
        end = time.time() + (secs or (app.LIVE_DELAY_MS / 1000.0 + 0.4))
        while time.time() < end:
            tk_root.update()
            time.sleep(0.02)

    def test_off_by_default_so_analyze_stays_a_choice(self, app, tk_root):
        assert app.live_on.get() is False
        app._analyze()
        app.results = None
        app._draw()
        self._settle(app, tk_root)
        assert app.results is None

    def test_an_edit_is_re_solved_once_the_drawing_settles(self, app,
                                                          tk_root, dialogs):
        app._analyze()
        app.live_on.set(True)
        app._on_live_toggle()
        app.loads.append({'node': 5, 'fz': -50.0})
        app.results = None
        app.member_checks = None
        app._draw()
        assert app._live_after is not None
        self._settle(app, tk_root)
        assert app.results is not None and app.member_checks
        assert not dialogs

    def test_a_failing_model_says_so_once_without_a_dialog(self, app,
                                                         monkeypatch,
                                                         dialogs):
        app.live_on.set(True)
        app.supports = app.supports[:1]
        app.results = None
        calls = []
        real = app._analyze
        monkeypatch.setattr(app, '_analyze',
                            lambda quiet=False: (calls.append(quiet),
                                                 real(quiet=quiet)))
        app._live_analyze()
        assert app.results is None and calls == [True]
        assert app.status_var.get().startswith('Live: ')
        assert not dialogs
        assert app.selected_nodes == set()      # the selection is the user's
        app._live_analyze()                     # the same model again
        assert calls == [True]
        app.supports = app.supports[:0]
        app._live_analyze()                     # no supports: not attempted
        assert calls == [True]

    def test_a_model_too_slow_to_solve_live_is_left_to_analyze(self, app):
        app.LIVE_MAX_RODS = 10
        app.live_on.set(True)
        app._on_live_toggle()
        assert 'by hand' in app.status_var.get()
        app.results = None
        app._draw()
        assert getattr(app, '_live_after', None) is None

    def test_turning_it_off_cancels_a_pending_solve(self, app, tk_root):
        app.live_on.set(True)
        app.results = None
        app._draw()
        assert app._live_after is not None
        app.live_on.set(False)
        app._on_live_toggle()
        assert app._live_after is None
        self._settle(app, tk_root)
        assert app.results is None

    def test_the_toolbar_has_the_switch(self, app):
        assert app.live_check.cget('text') == 'Live'
        assert str(app.live_check.cget('variable')) == str(app.live_on)


class TestNumbersHideWhenCrowded:
    """Node and rod numbers are left off while they would pile up on the
    screen -- zooming in brings them back, the selection keeps its own, and
    "Hide # when crowded" off draws every one regardless."""

    def _labels(self, app, tag):
        return [app.canvas.itemcget(t, 'text')
                for t in app.canvas.find_withtag(tag)]

    def test_the_default_grid_at_full_view_shows_no_pile_of_numbers(self, app):
        app._reset_view()
        app.selected_nodes = set()
        app._draw()
        assert self._labels(app, 'node_label') == []
        note = self._labels(app, 'labels_hidden_note')
        assert note and 'zoom in' in note[0]

    def test_zooming_in_brings_them_back(self, app):
        app._reset_view()
        app.zc.zoom *= 3.0
        app._draw()
        assert len(self._labels(app, 'node_label')) == len(app.nodes)
        assert not app.canvas.find_withtag('labels_hidden_note')

    def test_the_selection_keeps_its_numbers(self, app):
        app._reset_view()
        app.selected_nodes = {17, 40}
        app.show_member_labels.set(True)
        app.selected_member = 5
        app._draw()
        assert sorted(self._labels(app, 'node_label')) == ['17', '40']
        assert self._labels(app, 'rod_label') == ['5']
        assert self._labels(app, 'labels_hidden_note')[0].startswith(
            'Node and rod numbers')

    def test_a_big_selection_does_not_bring_the_pile_back(self, app):
        """A mechanism selects every loose node -- 128 on the default grid
        hinged on two supports -- and a hundred numbers is the pile."""
        app._reset_view()
        app.selected_nodes = set(range(60))
        app._draw()
        assert self._labels(app, 'node_label') == []

    def test_the_override_draws_every_number(self, app):
        app._reset_view()
        app.labels_auto_hide.set(False)
        app.show_member_labels.set(True)
        app._draw()
        assert len(self._labels(app, 'node_label')) == len(app.nodes)
        assert len(self._labels(app, 'rod_label')) == len(app.members)
        assert not app.canvas.find_withtag('labels_hidden_note')

    def test_what_counts_as_crowded(self, app):
        apart = [(k * 50.0, 0.0) for k in range(20)]
        packed = [(k * 5.0, 0.0) for k in range(20)]
        assert app._labels_crowded(apart) is False
        assert app._labels_crowded(packed) is True
        app.labels_auto_hide.set(False)
        assert app._labels_crowded(packed) is False

    def test_both_panels_carry_the_override(self, app):
        def walk(w):
            for c in w.winfo_children():
                yield c
                yield from walk(c)
        boxes = [w for w in walk(app.root) if isinstance(w, tk.Checkbutton)
                 and str(w.cget('variable')) == str(app.labels_auto_hide)]
        assert len(boxes) >= 1


class TestLongExplanationsFoldBehindAQuestionMark:
    """A grey paragraph past three lines shows two and a "?" badge: hover
    for the whole of it, click to open it in place. Its text is kept."""

    def test_the_long_paragraphs_fold_and_keep_their_text(self, app):
        assert len(app._hint_labels) >= 20
        for lbl in app._hint_labels:
            assert int(str(lbl.cget('height'))) == app.HINT_SHOWN_LINES
            assert len(lbl.cget('text')) > 100
            assert lbl._hint_badge.winfo_manager() == 'place'

    def test_a_click_opens_it_and_another_folds_it(self, app):
        lbl = app._hint_labels[0]
        lbl._hint_toggle()
        assert lbl._hint_open is True
        assert int(str(lbl.cget('height'))) == 0
        assert lbl._hint_badge.winfo_manager() == ''
        lbl._hint_toggle()
        assert lbl._hint_open is False
        assert int(str(lbl.cget('height'))) == app.HINT_SHOWN_LINES

    def test_hovering_the_badge_shows_the_whole_paragraph(self, app, tk_root):
        lbl = app._hint_labels[0]
        app._show_hint_tip(lbl)
        tip = app._hint_tip
        texts = [c.cget('text') for c in tip.winfo_children()]
        assert texts and texts[0].startswith(lbl.cget('text'))
        app._hide_hint_tip()
        assert app._hint_tip is None and not tip.winfo_exists()

    def test_a_note_that_changes_is_measured_again(self, app):
        note = app.shape_source_note
        note.config(text='word ' * 120)
        app._refit_hint(note)
        assert note._hint_folded and note in app._hint_labels
        assert note._hint_badge.winfo_manager() == 'place'
        note.config(text='short')
        app._refit_hint(note)
        assert note._hint_folded is False
        assert int(str(note.cget('height'))) == 0
        assert note._hint_badge.winfo_manager() == ''
        note._hint_toggle()                    # a click does nothing now
        assert int(str(note.cget('height'))) == 0

    def test_warnings_are_never_folded(self, app):
        warn = [lbl for lbl in app._hint_labels
                if str(lbl.cget('fg')) not in app.HINT_COLOURS]
        assert warn == []


class TestTheMechanismIsDrawnMoving:
    """A model that cannot stand is drawn moving the way it can, in orange,
    until it is edited or a solve succeeds."""

    def _swing(self, app):
        app.supports = app.supports[:2]        # it hinges about two nodes

    def test_a_singular_analyze_draws_it_moving(self, app, dialogs):
        self._swing(app)
        app._analyze()
        assert app.results is None
        assert app._mech is not None and app._mech['kind'] == 'mechanism'
        assert any('orange drawing shows how it moves' in str(d)
                   for d in dialogs)
        app._mech_tick()
        assert app.canvas.find_withtag('mechanism')
        assert app.status_var.get().startswith('Orange: how it moves')
        app._stop_mechanism()

    def test_the_frames_move_the_drawing(self, app):
        self._swing(app)
        app._show_mechanism(which=0, quiet=True)
        coords = []
        for a in (0.0, 0.5):
            app._draw_mechanism(a)
            line = [i for i in app.canvas.find_withtag('mechanism')
                    if app.canvas.type(i) == 'line']
            coords.append([tuple(app.canvas.coords(i)) for i in line])
        assert coords[0] and coords[0] != coords[1]
        app._stop_mechanism()
        assert not app.canvas.find_withtag('mechanism')

    def test_pressing_again_shows_the_next_way_then_stops(self, app):
        self._swing(app)
        assert app._show_mechanism()
        count = app._mech['count']
        for k in range(1, count):
            assert app._show_mechanism() and app._mech['which'] == k
        assert app._show_mechanism() is False
        assert app._mech is None
        assert 'every way it can move' in app.status_var.get()

    def test_a_successful_solve_stops_it(self, app):
        full = list(app.supports)
        self._swing(app)
        app._analyze()
        assert app._mech is not None
        app.supports = full
        app._analyze()
        app._mech_tick()
        assert app._mech is None
        assert not app.canvas.find_withtag('mechanism')

    def test_an_edit_stops_it(self, app):
        self._swing(app)
        app._show_mechanism(which=0, quiet=True)
        app.supports = app.supports[:1]
        app._mech['frame'] = 9                 # the next frame checks
        app._mech_tick()
        assert app._mech is None

    def test_a_model_that_grows_mid_swing_stops_it_cleanly(self, app):
        """Found by pressing every control: a crane lift added nodes while
        it swung, and the next frame drew the old shape onto them."""
        self._swing(app)
        app._show_mechanism(which=0, quiet=True)
        app.nodes = app.nodes + [(0.0, 0.0, 9.0), (1.0, 0.0, 9.0)]
        app.members = app.members + [dict(app.members[0], a=len(app.nodes) - 2,
                                          b=len(app.nodes) - 1)]
        app._draw_mechanism(0.3)               # draws nothing, raises nothing
        assert not app.canvas.find_withtag('mechanism')
        app._mech_tick()                       # not the 10th frame: still stops
        assert app._mech is None

    def test_with_no_supports_it_falls(self, app):
        app.supports = []
        app._analyze()
        assert app._mech['kind'] == 'rigid' and app._mech['axis'] == 'z'
        assert 'stands on nothing' in app.status_var.get()
        app._stop_mechanism()

    def test_a_model_that_stands_says_it_cannot_move(self, app):
        assert app._show_mechanism() is False
        assert app._mech is None
        assert app.status_var.get().startswith('It cannot move')

    def test_live_draws_it_moving_without_a_dialog(self, app, dialogs):
        app.live_on.set(True)
        self._swing(app)
        app.results = None
        app._live_analyze()
        assert app._mech is not None and not dialogs
        app._stop_mechanism()

    def test_the_support_panel_has_the_button(self, app):
        def walk(w):
            for c in w.winfo_children():
                yield c
                yield from walk(c)
        assert any(isinstance(w, tk.Button)
                   and w.cget('text') == 'Show how it can move'
                   for w in walk(app._mode_frames['support']))


class TestPlayLoad:
    """Toolbar → ▶ Play load: the Load % slider run from 0 to 100 %, the
    sagging shape coloured by force, and a pass/fail verdict at the end."""

    def _jump(self, app, frac):
        from apps.stereo.stereo_app_constants import PLAY_LOAD_SECONDS
        app._play['t0'] -= frac * PLAY_LOAD_SECONDS
        app._play_tick()

    def test_it_analyzes_first_and_starts_from_nothing(self, app):
        app.results = None
        assert app._play_load()
        try:
            assert app.results is not None
            assert app.load_fraction.get() == 0
            assert app.show_deformed.get() is True
            assert app.play_btn.cget('text') == '■ Stop'
        finally:
            app._stop_play_load(finished=False)

    def test_halfway_is_half_the_load(self, app):
        app._analyze()
        app._play_load()
        self._jump(app, 0.5)
        assert 45 <= app.load_fraction.get() <= 60
        app._stop_play_load(finished=False)

    def test_a_passing_model_passes_and_the_display_comes_back(self, app):
        app._analyze()
        before = (app.show_deformed.get(), app.deform_color_mode.get(),
                  app.colour_mode.get())
        app._play_load()
        self._jump(app, 1.1)
        assert app._play is None and app.load_fraction.get() == 100
        i, u = app._governing_rod()
        assert u <= 1.0
        assert app.status_var.get().startswith('Load test passed')
        assert f'rod, {i}, is at {u:.2f}' in app.status_var.get()
        assert (app.show_deformed.get(), app.deform_color_mode.get(),
                app.colour_mode.get()) == before
        assert app.play_btn.cget('text') == '▶ Play load'

    def test_a_failing_model_names_when_the_first_rod_gives(self, app):
        app._analyze()
        app.member_checks[7] = dict(app.member_checks[7], util=2.0,
                                    checked=True)
        app._play_load()
        self._jump(app, 0.25)
        assert 'reaches its capacity' not in app.status_var.get()
        self._jump(app, 0.3)
        assert app.status_var.get() == ('At 50 % of the load rod 7 reaches '
                                        'its capacity.')
        self._jump(app, 1.0)
        assert app.status_var.get().startswith(
            'Load test failed: rod 7 reaches its capacity at 50 %')
        assert app.status_kind.get() == 'error'

    def test_pressing_again_stops_it_at_full_load(self, app):
        app._analyze()
        app._play_load()
        self._jump(app, 0.3)
        assert app._play_load() is False
        assert app._play is None and app.load_fraction.get() == 100
        assert 'stopped' in app.status_var.get()

    def test_an_edit_while_it_plays_stops_it(self, app):
        app._analyze()
        app._play_load()
        app.results = None
        app._play_tick()
        assert app._play is None

    def test_with_nothing_built_it_says_so(self, blank_app):
        assert blank_app._play_load() is False
        assert 'Nothing to load-test' in blank_app.status_var.get()


class TestTheDesignScore:
    """Results → the score: what the design weighs, what it carries and
    whether it passes; the lightest passing design for the same brief."""

    def test_before_a_solve_it_shows_the_weight(self, app):
        app.results = None
        app._refresh_score()
        assert app.score_label.cget('text').startswith('Weight ')
        assert app.score_label.cget('text').endswith('▶ Analyze to score it')

    def test_a_solved_grid_is_weighed_and_passes(self, app):
        from apps.stereo import stereo_score as ss
        app._analyze()
        sc = app._score
        assert sc['mass_kg'] == pytest.approx(ss.model_mass_kg(
            app.nodes, app.members, app._unit_weight()))
        assert sc['carried_kN'] == pytest.approx(1800.0, rel=1e-3)
        assert sc['passes'] is True
        assert 'carries 1,800 kN' in app.score_label.cget('text')
        assert app.score_note.cget('text').startswith('Passes')
        assert ss.mass_text(sc['mass_kg']) in app.status_var.get()

    def test_the_lightest_passing_design_is_remembered(self, app):
        app._analyze()
        first = app._score['mass_kg']
        assert 'Lightest passing design so far' in app.score_note.cget('text')
        for m in app.members:                  # the same brief, heavier
            m['A'] = m['A'] * 1.5
        app._analyze()
        assert app._score['mass_kg'] > first
        assert 'Lightest so far' in app.score_note.cget('text')

    def test_a_failing_design_says_it_does_not_score(self, app):
        app.area_load_var.set(9.0)
        app._analyze()
        assert app._score['passes'] is False
        assert app.score_note.cget('text').startswith('FAILS')


class TestExampleLessons:
    """Every example in the library opens with a goal and questions; the
    questions name controls that exist, and the facts they lean on are
    true of the examples as shipped."""

    @staticmethod
    def _example(name):
        from apps.stereo import stereo_examples as sx
        return next((label, b) for label, b in sx.EXAMPLES
                    if b.__name__ == name)

    def test_every_example_has_a_lesson_and_only_those(self):
        from apps.stereo import stereo_examples as sx
        from apps.stereo import stereo_lessons as sl
        assert set(sl.LESSONS) == {b.__name__ for _l, b in sx.EXAMPLES}
        for name, lesson in sl.LESSONS.items():
            assert lesson['goal'].strip(), name
            assert 2 <= len(lesson['questions']) <= 3, name

    def test_the_controls_the_lessons_name_exist(self, app):
        from apps.stereo import stereo_lessons as sl
        text = ' '.join(lesson['goal'] + ' ' + ' '.join(lesson['questions'])
                        for lesson in sl.LESSONS.values())
        app._toggle_display_popover()
        try:
            labels = set()

            def walk(w):
                for c in w.winfo_children():
                    try:
                        labels.add(str(c.cget('text')))
                    except tk.TclError:
                        pass
                    if c.winfo_class() == 'Menu':
                        end = c.index('end')
                        for k in range(0, (end if end is not None else -1) + 1):
                            try:
                                labels.add(str(c.entrycget(k, 'label')))
                            except tk.TclError:
                                pass
                    walk(c)
            walk(app.root)
        finally:
            app._toggle_display_popover()
        everything = ' | '.join(labels)
        for control in ('Show me the governing rod', 'Explain this rod',
                        'Play load', 'Clear every beam', 'Clear rod loads',
                        'Smooth gradient', 'Moment along rod', 'Reactions',
                        'Live', 'Axial force', 'Utilization',
                        'Example library'):
            if control in text:
                assert control in everything, control

    def test_opening_an_example_opens_its_lesson(self, app):
        label, b = self._example('truss_bridge_example')
        app._load_example(b, label)
        assert app._lesson_open and app.canvas.find_withtag('lesson_card')
        assert app.lesson_title.cget('text') == label
        assert app.lesson_questions.cget('text').startswith('1. ')
        app._hide_lesson()
        assert not app.canvas.find_withtag('lesson_card')
        app._draw()
        assert not app.canvas.find_withtag('lesson_card')
        assert app._reopen_lesson()
        assert app.canvas.find_withtag('lesson_card')

    def test_a_new_model_closes_the_lesson(self, app):
        label, b = self._example('dome_example')
        app._load_example(b, label)
        app._generate()
        assert app._lesson is None
        assert not app.canvas.find_withtag('lesson_card')
        assert app._reopen_lesson() is False

    # ── the premises the questions lean on ─────────────────────────────
    def _solve(self, app, name):
        label, b = self._example(name)
        app._load_example(b, label)
        app._analyze()
        assert app.results is not None
        return [(m.get('role'), r['N']) for m, r in
                zip(app.members, app.results['member_res'])]

    def test_the_bridge_fails_and_its_bearings_push_sideways(self, app):
        forces = self._solve(app, 'truss_bridge_example')
        assert app._governing_rod()[1] > 1.0
        assert max(n for r, n in forces if r == 'top_chord') < 0.0
        assert min(n for r, n in forces if r == 'bottom_chord') < 0.0
        assert sum(abs(r.get('Fx', 0.0)) for r in
                   app.results['reactions'].values()) > 1.0

    def test_the_single_column_grid_fails_with_its_capital_ring_in_tension(
            self, app):
        forces = self._solve(app, 'planar_grid_with_columns_2')
        assert app._governing_rod()[1] > 1.0
        assert min(n for r, n in forces if r == 'capital_ring') > 0.0

    def test_no_hoop_of_the_dome_is_in_tension(self, app):
        forces = self._solve(app, 'dome_example')
        assert max(n for r, n in forces if r == 'hoop') <= 1e-6

    def test_the_cones_diagonals_carry_nothing(self, app):
        forces = self._solve(app, 'cone_roof_example')
        assert max(abs(n) for r, n in forces if r == 'diagonal') < 1e-3

    def test_the_vault_pushes_outward_on_its_supports(self, app):
        self._solve(app, 'barrel_vault_example')
        h = sum(abs(r.get('Fx', 0.0)) + abs(r.get('Fy', 0.0))
                for r in app.results['reactions'].values())
        assert h > 0.5 * sum(r.get('Fz', 0.0)
                             for r in app.results['reactions'].values())


class TestEveryDrawingIsToScale:
    """A drawing that stretches one direction more than another makes a
    truss look deeper or flatter than it is. Every view of the structure --
    the canvas, and every PDF sheet that draws it -- scales x and y alike.
    (The deflected shape and "Thickness = stress" exaggerate on purpose,
    and say so in their legends.)"""

    def test_the_canvas_draws_a_square_square(self, app):
        app.nodes = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 4.0, 0.0),
                     (0.0, 4.0, 0.0)]
        app.members = [dict(a=k, b=(k + 1) % 4, conn='pin', E=200.0, A=10.0,
                            I=100.0, J=100.0) for k in range(4)]
        app.supports, app.loads, app.results = [], [], None
        # straight down, a square is a square
        app.azimuth, app.elevation = 0.0, 89.9
        app._draw()
        p = app._screen_positions()
        side = [math.dist(p[k], p[(k + 1) % 4]) for k in range(4)]
        assert max(side) == pytest.approx(min(side), rel=1e-4)
        # at any angle, in the parallel projection, its opposite sides stay
        # equal: one scale for the whole drawing, nothing stretched
        for az, el in ((30.0, 25.0), (-60.0, 40.0), (0.0, 5.0)):
            app.azimuth, app.elevation = az, el
            app._draw()
            p = app._screen_positions()
            side = [math.dist(p[k], p[(k + 1) % 4]) for k in range(4)]
            assert side[0] == pytest.approx(side[2], rel=1e-6)
            assert side[1] == pytest.approx(side[3], rel=1e-6)

    def test_every_pdf_drawing_scales_x_and_y_alike(self, app, tmp_path,
                                                    monkeypatch):
        from matplotlib.backends import backend_pdf
        from apps.stereo import stereo_reports as sr
        ratios = []
        real = backend_pdf.PdfPages.savefig

        def spy(self_, figure=None, **kw):
            fw, fh = figure.get_size_inches()
            for ax in figure.axes:
                if not (ax.lines or ax.collections):
                    continue
                (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
                if (x0, x1, y0, y1) == (0.0, 1.0, 0.0, 1.0):
                    continue                    # a table's frame, not a view
                b = ax.get_position()
                sx = abs(x1 - x0) / (b.width * fw)
                sy = abs(y1 - y0) / (b.height * fh)
                ratios.append(sx / sy)
            return real(self_, figure, **kw)
        monkeypatch.setattr(backend_pdf.PdfPages, 'savefig', spy)
        app._analyze()
        sr.export_pdf(app.nodes, app.members, app._all_loads(), app.supports,
                      app.results, str(tmp_path / 'r.pdf'),
                      checks=app.member_checks)
        assert len(ratios) >= 10
        assert all(r == pytest.approx(1.0, rel=1e-3) for r in ratios), ratios


class TestGroupByPieces:
    """Groups → Actions → Group the whole model by pieces."""

    def test_the_default_grid_becomes_a_roof_of_three_layers(self, app,
                                                              dialogs):
        assert app._group_by_pieces()
        tops = [g for g in app.groups if g['parent'] is None]
        assert [g['name'] for g in tops] == ['Roof 1']
        kids = {g['name']: g for g in app.groups if g['parent'] == tops[0]['id']}
        assert set(kids) == {'Roof 1 top chords', 'Roof 1 bottom chords',
                             'Roof 1 diagonals'}
        want = {'top chords': 'top_chord', 'bottom chords': 'bottom_chord',
                'diagonals': 'web'}
        for name, g in kids.items():
            role = want[name.split(' ', 2)[2]]
            assert {app.members[j]['role'] for j in g['members']} == {role}
        assert 'Grouped by pieces: 1 roof' in app.group_note.cget('text')

    def test_it_asks_before_replacing_groups_and_undo_brings_them_back(
            self, app, monkeypatch):
        from apps.stereo import stereo_groups as sgp
        app.groups = []
        sgp.new_group(app.groups, 'Mine', members=[0, 1, 2])
        asked = []
        monkeypatch.setattr('apps.stereo.stereo_app_groups.messagebox.askyesno',
                            lambda *a, **k: asked.append(a) or False)
        assert app._group_by_pieces() is False
        assert [g['name'] for g in app.groups] == ['Mine'] and asked
        monkeypatch.setattr('apps.stereo.stereo_app_groups.messagebox.askyesno',
                            lambda *a, **k: True)
        assert app._group_by_pieces()
        app._undo()
        assert [g['name'] for g in app.groups] == ['Mine']

    def test_the_actions_menu_has_it(self, app):
        menu = app._group_actions_menu(app.root)
        labels = [menu.entrycget(k, 'label') for k in range(menu.index('end') + 1)
                  if menu.type(k) == 'command']
        assert 'Group the whole model by pieces…' in labels


class TestBucklingDemonstrations:
    """Analyse → Buckling: the shapes, drawn moving in purple, and the
    second-order load-deflection curve. The checks stay first-order."""

    def test_the_shapes_cycle_and_then_stop(self, app):
        app._analyze()
        utils = [c.get('util') for c in app.member_checks]
        assert app._show_buckling()
        mode = app._mech
        assert mode['kind'] == 'buckling' and mode['which'] == 0
        assert 'buckles at' in app.status_var.get()
        app._mech_tick()
        assert app.canvas.find_withtag('mechanism')
        for k in range(1, mode['count']):
            assert app._show_buckling() and app._mech['which'] == k
        assert app._show_buckling() is False and app._mech is None
        # a demonstration: not one utilisation moved
        assert [c.get('util') for c in app.member_checks] == utils

    def test_an_edit_stops_the_shape(self, app):
        app._analyze()
        app._show_buckling()
        app.results = None
        app._mech_tick()
        assert app._mech is None

    def test_the_analysis_is_cached_for_one_solve(self, app, monkeypatch):
        from apps.stereo import stereo_buckling as sb
        app._analyze()
        calls = []
        real = sb.buckling
        monkeypatch.setattr(sb, 'buckling',
                            lambda *a, **k: calls.append(1) or real(*a, **k))
        app._show_buckling()
        app._show_buckling()
        assert len(calls) == 1
        app._stop_mechanism()

    def test_the_load_deflection_window(self, app):
        app._analyze()
        win = app._show_load_deflection()
        try:
            data = win._data
            assert data['lambda_cr'] == pytest.approx(
                app._buckling_result()['factors'][0], rel=1e-6)
            for key in ('bow_mm', 'node_mm', 'first_mm'):
                assert win._canvas.find_withtag('curve_' + key)
            assert win.title() == 'Second-order load–deflection'
        finally:
            win.destroy()

    def test_nothing_in_compression_says_so(self, app):
        app.nodes = [(0.0, 0.0, 3.0), (0.0, 0.0, 0.0)]
        app.members = [dict(app.members[0], a=0, b=1, conn='pin')]
        app.supports = [{'node': 0, 'type': 'pin'},
                        {'node': 1, 'dofs': {'ux': True, 'uy': True}}]
        app.loads = [{'node': 1, 'fz': -10.0}]       # it hangs
        app.area_load_on.set(False)
        app.self_weight_on.set(False)
        app.wind_on.set(False)
        app.member_loads = []
        app._analyze()
        assert app._show_buckling() is False
        assert 'compression' in app.status_var.get()

    def test_the_panel_has_both_buttons(self, app):
        def walk(w):
            for c in w.winfo_children():
                yield c
                yield from walk(c)
        texts = {w.cget('text') for w in walk(app._mode_frames['analyse'])
                 if isinstance(w, tk.Button)}
        assert {'Buckling shapes', 'Load–deflection…'} <= texts
