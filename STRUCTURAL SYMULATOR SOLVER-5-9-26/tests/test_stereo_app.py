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
import time

import tkinter as tk
import pytest

from apps.stereo.stereo_app import (
    StereoApp, force_color, deform_color, FAMILY_LABEL, CHORD_ROLES,
    QUICK_SUPPORT_PIN, QUICK_SUPPORT_FIXED, QUICK_SUPPORT_CLEAR, QUICK_SUPPORT_CUSTOM,
    moment_color, reaction_moment_signed, MOMENT_ZERO_COLOR, MOMENT_AXES,
    MOMENT_AXIS_RESULTANT, MOMENT_AXIS_MX, MOMENT_AXIS_MY, MOMENT_AXIS_MZ,
)
from apps.stereo import stereo_math as sm


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
    w, h = app.canvas.winfo_width(), app.canvas.winfo_height()
    assert app.zc.pan_x == pytest.approx(w / 2.0)
    assert app.zc.pan_y == pytest.approx(h / 2.0)


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
    half off-screen. This checks the actual screen position of the
    model's own centroid node bounding box middle, not just that some pan
    value changed."""
    w, h = app.canvas.winfo_width(), app.canvas.winfo_height()
    assert app.zc.pan_x == pytest.approx(w / 2.0, abs=1.0)
    assert app.zc.pan_y == pytest.approx(h / 2.0, abs=1.0)


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
    assert any('over capacity' in t and 'utilisation' in t for t in texts)


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
    text = app.sel_label.cget('text')
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
    assert 'Run' in app.sel_label.cget('text')


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


def test_wizard_calculator_palette_inserts_into_the_focused_field(app):
    win = _open_wizard(app)
    entries = _descendants(win, tk.Entry)
    z_entry = entries[0]
    z_entry.delete(0, tk.END)
    z_entry.focus_set()
    z_entry.update()   # let <FocusIn> actually fire before the palette click
    buttons = _descendants(win, tk.Button)
    [b for b in buttons if b.cget('text') == 'sqrt'][0].invoke()
    assert z_entry.get() == 'sqrt()'


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


def test_wizard_generated_mesh_is_undoable(app):
    n0 = len(app.nodes)
    win = _open_wizard(app)
    buttons = _descendants(win, tk.Button)
    [b for b in buttons if b.cget('text') == 'Generate'][0].invoke()
    assert len(app.nodes) != n0
    app._undo()
    assert len(app.nodes) == n0


# ── Module Editor ────────────────────────────────────────────────────────────

def test_module_editor_populates_roles_after_the_default_flat_grid(app):
    assert app._me_roles   # flat_grid always has at least one role
    assert app._me_role_id == 0
    assert app.me_role_combo['values']
    # the default flat_grid (offset=True) has both pyramidal-web triangles
    # and flat square chords -- two distinct shapes, so at least one
    # keystone/singular entry besides the dominant role 0
    assert app.me_keystone_list.size() >= 1


def test_module_editor_draws_an_axonometric_inset(app):
    axo_items = app.me_canvas.find_withtag('axo')
    assert axo_items
    kinds = {app.me_canvas.type(i) for i in axo_items}
    assert 'rectangle' in kinds   # the inset's own background panel
    assert 'line' in kinds        # the cell's ring edges, in 3D
    assert 'oval' in kinds        # the cell's nodes, in 3D
    # every inset line/oval is a distinct set of screen coordinates from
    # the flattened (u, v) view -- i.e. actually a second, separate
    # rendering, not just re-tagging the same items
    flat_edge = app.me_canvas.coords(app.me_canvas.find_withtag('edge')[0])
    axo_lines = [app.me_canvas.coords(i) for i in axo_items if app.me_canvas.type(i) == 'line']
    assert flat_edge not in axo_lines


def test_axonometric_inset_matches_the_cells_own_triangle_or_quad_count(app):
    cell_nodes = app._me_current_cell_nodes()
    n = len(cell_nodes)
    axo_lines = [i for i in app.me_canvas.find_withtag('axo') if app.me_canvas.type(i) == 'line']
    assert len(axo_lines) == n   # one ring edge per side, no diagonal present initially


def test_axonometric_inset_shows_an_existing_diagonal_as_an_extra_line():
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
        before = len([i for i in app.me_canvas.find_withtag('axo')
                     if app.me_canvas.type(i) == 'line'])

        cell_nodes = app._me_current_cell_nodes()
        a_id, b_id = cell_nodes[0], cell_nodes[2]
        app.members.append({'a': a_id, 'b': b_id, 'conn': 'pin', 'role': 'test_diag',
                            'E': 200e3, 'A': 20.0})
        app._me_render()
        after = len([i for i in app.me_canvas.find_withtag('axo')
                    if app.me_canvas.type(i) == 'line'])
        assert after == before + 1
    finally:
        tab.destroy()
        root.destroy()


def test_axonometric_inset_still_renders_for_a_curved_family(app):
    app.grid_family.set(FAMILY_LABEL['dome'])
    app._generate()
    axo_items = app.me_canvas.find_withtag('axo')
    assert axo_items


def test_module_editor_clicking_a_node_selects_it_and_shows_the_node_box(app):
    items = app.me_canvas.find_withtag('node')
    x0, y0, x1, y1 = app.me_canvas.bbox(items[0])
    app._me_on_press(FakeEvent((x0 + x1) / 2, (y0 + y1) / 2))
    app.root.update_idletasks()
    assert app._me_selection[0] == 'node'
    assert app.me_node_box.winfo_ismapped()


def test_module_editor_clicking_a_rod_selects_it_and_shows_the_edge_box(app):
    items = app.me_canvas.find_withtag('edge')
    x0, y0, x1, y1 = app.me_canvas.bbox(items[0])
    app._me_on_press(FakeEvent((x0 + x1) / 2, (y0 + y1) / 2))
    app.root.update_idletasks()
    assert app._me_selection[0] == 'edge'
    assert app.me_edge_box.winfo_ismapped()


def test_module_editor_move_propagates_and_keeps_the_role_grouping_stable(app):
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
    role_id = app._me_role_id
    cell_nodes = app._me_cells[app._me_roles[role_id][0]]['nodes']
    import math
    before = math.dist(app.nodes[cell_nodes[0]], app.nodes[cell_nodes[1]])

    app.me_rescale.set(3.0)
    app._me_apply_rescale()

    after = math.dist(app.nodes[cell_nodes[0]], app.nodes[cell_nodes[1]])
    assert after == pytest.approx(before * 3.0)


def test_module_editor_edits_are_undoable(app):
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
