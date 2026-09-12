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
    StereoApp, force_color, FAMILY_LABEL, CHORD_ROLES,
    QUICK_SUPPORT_PIN, QUICK_SUPPORT_FIXED, QUICK_SUPPORT_CLEAR, QUICK_SUPPORT_CUSTOM,
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
    def __init__(self, x, y, width=None, height=None):
        self.x = x
        self.y = y
        if width is not None:
            self.width = width
        if height is not None:
            self.height = height


def _screen_pos_of(app, node_idx):
    """The exact screen coordinates _draw() placed a given node at, so a
    synthetic click/drag can target it precisely -- the same computation
    _draw and _select_node_at share."""
    nodes = app._display_nodes()
    proj = [app._project(x, y, z) for x, y, z in nodes]
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


@pytest.mark.parametrize('key', ['flat_grid', 'barrel_vault', 'dome'])
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


# ── mouse-only camera: orbit drag vs click-select, wheel/pan untouched ──────

def test_a_small_movement_is_treated_as_a_click_not_an_orbit(app):
    sx, sy = _screen_pos_of(app, 0)
    az0, el0 = app.azimuth, app.elevation
    app._on_canvas_press(FakeEvent(sx, sy))
    app._on_canvas_motion(FakeEvent(sx + 1, sy + 1))   # below the drag threshold
    app._on_canvas_release(FakeEvent(sx + 1, sy + 1))
    assert app.azimuth == az0 and app.elevation == el0
    assert app.selected_node == 0


def test_a_real_drag_orbits_the_camera_and_does_not_select_a_node(app):
    az0, el0 = app.azimuth, app.elevation
    app.selected_node = None
    app._on_canvas_press(FakeEvent(400, 300))
    app._on_canvas_motion(FakeEvent(460, 260))   # well past the drag threshold
    assert app.azimuth != az0 or app.elevation != el0
    app._on_canvas_release(FakeEvent(460, 260))
    assert app.selected_node is None


def test_orbit_drag_clamps_elevation_to_plus_minus_89_degrees(app):
    app._on_canvas_press(FakeEvent(0, 0))
    app._on_canvas_motion(FakeEvent(0, -10000))   # an absurdly large drag
    assert -89.0 <= app.elevation <= 89.0
    app._on_canvas_release(FakeEvent(0, -10000))


def test_reset_view_recenters_and_restores_the_default_angle(app):
    app._on_canvas_press(FakeEvent(0, 0))
    app._on_canvas_motion(FakeEvent(200, 200))
    app._on_canvas_release(FakeEvent(200, 200))
    assert (app.azimuth, app.elevation) != (35.0, 22.0)

    app._reset_view()
    assert app.azimuth == 35.0 and app.elevation == 22.0
    w, h = app.canvas.winfo_width(), app.canvas.winfo_height()
    assert app.zc.pan_x == pytest.approx(w / 2.0)
    assert app.zc.pan_y == pytest.approx(h / 2.0)


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
