"""Editing features on the Truss tab: the selection box, undo/redo, move,
copy/paste about a reference point, and the three arrays.

The keyboard map, which is not the usual one and is deliberate:

    Ctrl+Z  undo
    Ctrl+X  REDO   -- not cut. There is no cut; the clipboard is C/V only.
    Ctrl+C  copy with a base point
    Ctrl+V  paste at the cursor

`test_every_mutator_pushes_undo` is the load-bearing one. Undo here is
snapshot-based, so a new model-mutating method that forgets to call
`_push_undo` does not crash and does not misbehave -- it just silently
becomes un-undoable, and nobody notices until they need it. That test walks
the mutators and fails if one stops recording.
"""
import gc
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import tkinter as tk
except Exception:
    tk = None

import pytest

from common import PX_PER_M


def _new_root_or_skip():
    if tk is None:
        pytest.skip('tkinter not importable in this environment')
    last = None
    for attempt in range(4):
        try:
            return tk.Tk()
        except Exception as ex:
            last = ex
            gc.collect()
            time.sleep(0.25 * (attempt + 1))
    pytest.skip(f'no display available to run this UI-level check ({last})')


@pytest.fixture()
def app():
    from tkinter import messagebox, filedialog
    for name in ('showerror', 'showwarning', 'showinfo'):
        setattr(messagebox, name, lambda *a, **k: None)
    filedialog.askopenfilename = lambda *a, **k: ''
    filedialog.asksaveasfilename = lambda *a, **k: ''
    from apps.truss.truss_app import TrussApp
    root = _new_root_or_skip()
    root.geometry('1300x850+0+0')
    host = tk.Frame(root)
    host.pack(fill='both', expand=True)
    a = TrussApp(host)
    root.update_idletasks()
    root.update()
    try:
        yield a, root
    finally:
        try:
            root.destroy()
        finally:
            gc.collect()


class Ev:
    """A stand-in for a Tk event."""
    def __init__(self, x=0, y=0, state=0):
        self.x, self.y, self.state = x, y, state


# ── the selection box ────────────────────────────────────────────────────────

def test_the_selection_box_is_actually_drawn(app):
    """THE BUG. `_on_drag_motion` always stored the far corner and redrew, and
    `_on_release` always computed the right selection from it -- but nothing
    ever drew the box, so you were selecting blind. Asserting on the canvas
    item is the only way to catch that: every geometric query was already
    correct while nothing was visible."""
    a, root = app
    a._load_example()
    a._set_tool('select')
    root.update_idletasks(); root.update()
    c = a.zc.canvas

    def rects():
        return [i for i in c.find_all() if c.type(i) == 'rectangle']

    assert not rects(), 'a box is drawn before any drag has started'
    a._on_press(Ev(80, 200))
    a._on_drag_motion(Ev(620, 420))
    root.update_idletasks(); root.update()
    got = rects()
    assert got, 'dragging a selection box draws nothing'
    xs = [round(v) for v in c.coords(got[0])]
    assert xs == [80, 200, 620, 420], xs
    # ...and it goes away once the drag ends
    a._on_release(Ev(620, 420))
    root.update_idletasks(); root.update()
    assert not rects(), 'the box outlives the drag'


def test_the_box_selects_what_it_encloses(app):
    a, root = app
    a._load_example()
    a._set_tool('select')
    sx0, sy0 = a.zc.w2s(-50, -50)
    sx1, sy1 = a.zc.w2s(10_000, 10_000)
    a._on_press(Ev(int(sx0), int(sy0)))
    a._on_drag_motion(Ev(int(sx1), int(sy1)))
    a._on_release(Ev(int(sx1), int(sy1)))
    assert len(a.selected_nodes) == len(a.nodes)


# ── undo / redo ──────────────────────────────────────────────────────────────

MUTATORS = [
    ('_load_example', ()),
    ('_apply_load', ()),
    ('_apply_support', ()),
    ('_set_connection_type', ('rigid',)),
    ('_apply_udl', ()),
    ('_clear_udl', ()),
    ('_apply_point_load', ()),
    ('_clear_point_loads', ()),
    ('_assign_profile_to_selection', ()),
    ('_on_delete', (None,)),
    ('_add_gusset', ()),
    ('_remove_plates', ()),
    ('_clear_all', ()),
]


@pytest.mark.parametrize('name,args', MUTATORS)
def test_every_mutator_pushes_undo(app, name, args):
    """A mutator that forgets `_push_undo` does not fail loudly -- it just
    stops being undoable. This walks them so that silence is caught."""
    a, root = app
    a._load_example()
    a.selected_nodes = {1, 2}
    a.selected_rods = {0, 1}
    a.pending_load = {1}
    a.pending_sup = {2}
    depth = len(a._undo_stack)
    getattr(a, name)(*args)
    assert len(a._undo_stack) > depth, (
        '%s changed the model without recording an undo step' % name)


def test_undo_and_redo_walk_the_history(app):
    a, root = app
    a._load_example()
    n0 = len(a.nodes)
    a.selected_nodes = {1}; a.selected_rods = set()
    a._on_delete(None)
    n1 = len(a.nodes)
    assert n1 == n0 - 1
    a._undo()
    assert len(a.nodes) == n0
    a._redo()
    assert len(a.nodes) == n1
    a._undo()
    assert len(a.nodes) == n0


def test_a_new_edit_discards_the_redo_branch(app):
    """Standard editor behaviour: once you diverge, there is no future to
    redo into."""
    a, root = app
    a._load_example()
    a.selected_nodes = {1}; a._on_delete(None)
    a._undo()
    assert a._redo_stack
    a.selected_nodes = {2}; a._on_delete(None)
    assert not a._redo_stack
    before = len(a.nodes)
    a._redo()
    assert len(a.nodes) == before


def test_undo_clears_stale_results_rather_than_showing_them(app):
    """Results belong to the model that produced them. Restoring an older
    model while leaving the analysis on screen would show numbers that do not
    describe what is drawn."""
    a, root = app
    a._load_example()
    a._run_analysis()
    assert a.results is not None
    a.selected_nodes = {1}; a._on_delete(None)
    a._undo()
    assert a.results is None
    assert a.diagrams is None


def test_undo_on_an_empty_history_is_harmless(app):
    a, root = app
    a._undo(); a._redo()
    assert a.nodes == [] and a.rods == []


def test_the_history_is_bounded(app):
    a, root = app
    a._load_example()
    for _ in range(a.UNDO_LIMIT + 30):
        a._push_undo('spam')
    assert len(a._undo_stack) <= a.UNDO_LIMIT


# ── move a selection ─────────────────────────────────────────────────────────

def test_dragging_a_selected_node_moves_the_whole_selection(app):
    a, root = app
    a._load_example()
    a._set_tool('select')
    a.snap_grid.set(False); a.snap_node.set(False); a.snap_curve.set(False)
    a.selected_nodes = {1, 2, 3}
    before = {i: tuple(a.nodes[i]) for i in a.selected_nodes}
    others = {i: tuple(a.nodes[i]) for i in (0, 4)}
    sx, sy = a.zc.w2s(*a.nodes[1])
    a._on_press(Ev(int(sx), int(sy)))
    assert a._moving_sel
    a._on_drag_motion(Ev(int(sx) + 72, int(sy) - 48))
    a._on_release(Ev(int(sx) + 72, int(sy) - 48))
    for i, (ox, oy) in before.items():
        assert a.nodes[i][0] == pytest.approx(ox + 72, abs=1e-6)
        assert a.nodes[i][1] == pytest.approx(oy - 48, abs=1e-6)
    for i, xy in others.items():
        assert tuple(a.nodes[i]) == xy, 'an unselected node moved'


def test_a_move_is_one_undo_step_back_to_the_start(app):
    """Not back to some intermediate drag position."""
    a, root = app
    a._load_example()
    a._set_tool('select')
    a.snap_grid.set(False); a.snap_node.set(False); a.snap_curve.set(False)
    a.selected_nodes = {1}
    start = tuple(a.nodes[1])
    sx, sy = a.zc.w2s(*a.nodes[1])
    a._on_press(Ev(int(sx), int(sy)))
    for step in (20, 40, 60):
        a._on_drag_motion(Ev(int(sx) + step, int(sy)))
    a._on_release(Ev(int(sx) + 60, int(sy)))
    assert a.nodes[1][0] == pytest.approx(start[0] + 60, abs=1e-6)
    a._undo()
    assert tuple(a.nodes[1]) == start


def test_pressing_an_unselected_node_starts_a_box_not_a_move(app):
    a, root = app
    a._load_example()
    a._set_tool('select')
    a.selected_nodes = {1}
    sx, sy = a.zc.w2s(*a.nodes[3])          # a node that is NOT selected
    a._on_press(Ev(int(sx), int(sy)))
    assert not a._moving_sel


# ── copy / paste about a base point ──────────────────────────────────────────

def test_copy_paste_lands_exactly_at_the_offset(app):
    a, root = app
    a._load_example()
    a.selected_nodes = {0, 1, 2}
    a._ghost_wx, a._ghost_wy = a.nodes[0]        # base point = node 0
    a._copy_selection()
    assert len(a._clipboard['nodes']) == 3
    src = [tuple(a.nodes[i]) for i in (0, 1, 2)]
    a._ghost_wx, a._ghost_wy = a.nodes[0][0] + 240, a.nodes[0][1] - 96
    a._paste_clipboard()
    dst = sorted(a.selected_nodes)
    assert len(dst) == 3
    for d, (ox, oy) in zip(dst, src):
        assert a.nodes[d][0] == pytest.approx(ox + 240, abs=1e-9)
        assert a.nodes[d][1] == pytest.approx(oy - 96, abs=1e-9)


def test_paste_brings_the_rods_between_the_copied_nodes(app):
    a, root = app
    a._load_example()
    a.selected_nodes = set(range(len(a.nodes)))
    a._ghost_wx, a._ghost_wy = a.nodes[0]
    a._copy_selection()
    n0, r0 = len(a.nodes), len(a.rods)
    a._ghost_wx, a._ghost_wy = a.nodes[0][0] + 600, a.nodes[0][1]
    a._paste_clipboard()
    assert len(a.nodes) == 2 * n0
    assert len(a.rods) == 2 * r0


def test_paste_carries_rod_properties_but_not_supports_or_loads(app):
    """The agreed rule: geometry and member properties travel, boundary
    conditions do not. A silently duplicated support would change how the
    structure behaves in a way that is easy to miss."""
    a, root = app
    a._load_example()
    a.rods[0].update(conn='rigid', udl=7.5, udl_rotation_deg=30.0, A=42.0)
    n_sup, n_load = len(a.supports), len(a.loads)
    a.selected_nodes = {0, 1}
    a._ghost_wx, a._ghost_wy = a.nodes[0]
    a._copy_selection()
    a._ghost_wx, a._ghost_wy = a.nodes[0][0] + 400, a.nodes[0][1]
    a._paste_clipboard()
    new_rod = a.rods[-1]
    assert new_rod['conn'] == 'rigid'
    assert new_rod['udl'] == pytest.approx(7.5)
    assert new_rod['udl_rotation_deg'] == pytest.approx(30.0)
    assert new_rod['A'] == pytest.approx(42.0)
    assert len(a.supports) == n_sup, 'supports were duplicated'
    assert len(a.loads) == n_load, 'loads were duplicated'


def test_paste_is_one_undo_step(app):
    a, root = app
    a._load_example()
    n0, r0 = len(a.nodes), len(a.rods)
    a.selected_nodes = {0, 1, 2}
    a._ghost_wx, a._ghost_wy = a.nodes[0]
    a._copy_selection()
    a._ghost_wx, a._ghost_wy = a.nodes[0][0] + 300, a.nodes[0][1]
    a._paste_clipboard()
    a._undo()
    assert len(a.nodes) == n0 and len(a.rods) == r0


def test_copy_with_nothing_selected_is_a_no_op(app):
    a, root = app
    a._load_example()
    a.selected_nodes = set()
    a._copy_selection()
    assert a._clipboard is None
    n0 = len(a.nodes)
    a._paste_clipboard()
    assert len(a.nodes) == n0


# ── guides and arrays through the UI ─────────────────────────────────────────

def add_bridge_guide(a, L=20.0, f=4.0):
    a.guide_kind.set('func'); a._sync_guide_fields()
    a.guide_expr.set('4*f*x*(L-x)/L^2')
    a.guide_params.set('L=%g, f=%g' % (L, f))
    a.guide_x0.set(0.0); a.guide_x1.set(L)
    a._add_guide()


def test_a_guide_is_added_and_is_not_structure(app):
    a, root = app
    add_bridge_guide(a)
    assert len(a.guides) == 1
    assert a.nodes == [] and a.rods == []
    # and it survives undo/redo like anything else
    a._undo(); assert a.guides == []
    a._redo(); assert len(a.guides) == 1


def test_a_broken_guide_expression_is_refused_with_a_reason(app):
    a, root = app
    a.guide_kind.set('func'); a._sync_guide_fields()
    a.guide_expr.set('4*x +')
    a.guide_params.set('')
    a._add_guide()
    assert a.guides == []


def test_path_array_builds_a_chord_evenly_spaced_along_the_curve(app):
    a, root = app
    add_bridge_guide(a, L=20.0, f=4.0)
    a.path_guide.set(a._guide_label(0, a.guides[0]))
    a.path_mode.set('count'); a.path_n.set(9)
    a.path_s0.set(0.0); a.path_s1.set(0.0)      # 0 = whole guide
    a.path_chain.set(True)
    a._array_path()
    assert len(a.nodes) == 9
    assert len(a.rods) == 8
    ms = [a._world_to_metres(*n) for n in a.nodes]
    assert ms[0][0] == pytest.approx(0.0, abs=1e-6)
    assert ms[-1][0] == pytest.approx(20.0, abs=1e-6)
    assert max(y for _x, y in ms) == pytest.approx(4.0, rel=1e-5)
    # x-steps must NOT be uniform -- that is the difference between spacing
    # along the curve and spacing in x
    dxs = [ms[i + 1][0] - ms[i][0] for i in range(len(ms) - 1)]
    assert max(dxs) - min(dxs) > 0.15 * max(dxs), dxs


def test_path_array_without_chaining_makes_no_rods(app):
    a, root = app
    add_bridge_guide(a)
    a.path_guide.set(a._guide_label(0, a.guides[0]))
    a.path_n.set(5); a.path_chain.set(False)
    a._array_path()
    assert len(a.nodes) == 5 and a.rods == []


def test_grid_array_repeats_the_selection(app):
    a, root = app
    a._load_example()
    n0, r0 = len(a.nodes), len(a.rods)
    a.selected_nodes = set(range(n0))
    a.grid_nx.set(3); a.grid_ny.set(2)
    a.grid_dx.set(15.0); a.grid_dy.set(8.0)
    a._array_grid()
    # 3x2 = 6 copies, the first of which is the originals already present
    assert len(a.nodes) == n0 * 6
    assert len(a.rods) == r0 * 6
    a._undo()
    assert len(a.nodes) == n0 and len(a.rods) == r0


def test_polar_array_places_copies_on_a_circle(app):
    a, root = app
    a._push_undo('seed')
    a.nodes = [a._metres_to_world(3.0, 0.0), a._metres_to_world(4.0, 0.0)]
    a.rods = [a._new_rod(0, 1)]
    a.selected_nodes = {0, 1}
    a.polar_cx.set(0.0); a.polar_cy.set(0.0)
    a.polar_n.set(6); a.polar_deg.set(360.0); a.polar_rot.set(True)
    a._array_polar()
    assert len(a.nodes) == 12
    assert len(a.rods) == 6
    radii = sorted(round(math.hypot(*a._world_to_metres(*n)), 6) for n in a.nodes)
    assert radii[:6] == [pytest.approx(3.0, abs=1e-6)] * 6
    assert radii[6:] == [pytest.approx(4.0, abs=1e-6)] * 6


def test_arrays_refuse_an_empty_selection_instead_of_doing_nothing_silently(app):
    a, root = app
    a._load_example()
    a.selected_nodes = set()
    n0 = len(a.nodes)
    a._array_grid()
    a._array_polar()
    assert len(a.nodes) == n0


def test_curve_snap_pulls_a_point_onto_the_guide(app):
    a, root = app
    add_bridge_guide(a, L=20.0, f=4.0)
    a.snap_curve.set(True); a.snap_grid.set(False); a.snap_node.set(False)
    # a point a little above the apex (10, 4)
    wx, wy = a._metres_to_world(10.0, 4.3)
    gx, gy = a._compute_ghost(wx, wy)
    mx, my = a._world_to_metres(gx, gy)
    assert my == pytest.approx(4.0, abs=1e-2), (mx, my)
    # far away, it must NOT snap
    wx2, wy2 = a._metres_to_world(10.0, 12.0)
    gx2, gy2 = a._compute_ghost(wx2, wy2)
    assert a._world_to_metres(gx2, gy2)[1] == pytest.approx(12.0, abs=1e-6)


def test_curve_snap_off_leaves_the_point_alone(app):
    a, root = app
    add_bridge_guide(a)
    a.snap_curve.set(False); a.snap_grid.set(False); a.snap_node.set(False)
    wx, wy = a._metres_to_world(10.0, 4.3)
    gx, gy = a._compute_ghost(wx, wy)
    assert (gx, gy) == pytest.approx((wx, wy), abs=1e-9)


# ── guides: selecting, handles, dragging, Re-array ───────────────────────────

def add_fit(a, family='parabola', by='rise', value=4.0,
            p0=(0.0, 0.0), p1=(20.0, 0.0)):
    a.guide_kind.set('fit')
    a._sync_guide_fields()
    a.fit_family.set(family)
    a._sync_fit_by()
    a.fit_by.set(by)
    a.fit_value.set(value)
    a.guide_x0.set(p0[0]); a.guide_y0.set(p0[1])
    a.guide_x1.set(p1[0]); a.guide_y1.set(p1[1])
    a._add_guide()


def free_snaps(a):
    a.snap_grid.set(False)
    a.snap_node.set(False)
    a.snap_curve.set(False)


def test_a_fitted_guide_is_added_from_the_panel(app):
    from apps.truss import truss_guides as tg
    a, root = app
    add_fit(a, 'parabola', 'rise', 4.0)
    assert len(a.guides) == 1
    gd = a.guides[0]
    assert gd['kind'] == 'fit' and gd['family'] == 'parabola'
    assert tg.guide_callable(gd)(0.5)[1] == pytest.approx(4.0, abs=1e-9)


def test_set_by_offers_only_what_pins_that_family_down(app):
    """A parabola through two points is fixed by its rise; asking for its
    radius is not a harder question, it is a meaningless one."""
    a, root = app
    a.guide_kind.set('fit'); a._sync_guide_fields()
    a.fit_family.set('parabola'); a._sync_fit_by()
    assert tuple(a.fit_by_combo['values']) == ('rise',)
    a.fit_family.set('arc'); a._sync_fit_by()
    assert set(a.fit_by_combo['values']) == {'rise', 'radius', 'length'}
    a.fit_family.set('catenary'); a._sync_fit_by()
    assert set(a.fit_by_combo['values']) == {'sag', 'length'}
    # and a stale choice is corrected rather than left invalid
    assert a.fit_by.get() in ('sag', 'length')


def test_a_guide_has_handles_at_its_defining_points(app):
    from apps.truss import truss_guides as tg
    a, root = app
    add_fit(a)
    roles = [r for r, _p in tg.guide_handles(a.guides[0])]
    assert roles == ['end', 'end', 'shape']
    pts = [p for _r, p in tg.guide_handles(a.guides[0])]
    assert pts[0] == pytest.approx((0.0, 0.0), abs=1e-9)
    assert pts[1] == pytest.approx((20.0, 0.0), abs=1e-9)
    assert pts[2] == pytest.approx((10.0, 4.0), abs=1e-6)   # the crown


def test_clicking_a_guide_selects_it_and_clicking_a_handle_grabs_that(app):
    a, root = app
    add_fit(a)
    a._set_tool('select')
    # a point on the curve, away from any handle
    gi, hi = a._guide_hit_at(*a._metres_to_world(5.0, 3.0))
    assert gi == 0 and hi is None
    # the left end handle
    gi, hi = a._guide_hit_at(*a._metres_to_world(0.0, 0.0))
    assert gi == 0 and hi == 0
    # somewhere far from the guide
    gi, hi = a._guide_hit_at(*a._metres_to_world(60.0, 60.0))
    assert gi is None and hi is None


def test_dragging_an_end_handle_re_solves_the_fit(app):
    """The payoff of storing constraints rather than coefficients: the curve
    re-fits through the moved point and KEEPS the rise that was asked for."""
    from apps.truss import truss_guides as tg
    a, root = app
    free_snaps(a)
    add_fit(a, 'parabola', 'rise', 4.0)
    a.sel_guide = 0
    a._begin_guide_drag(0, 1, *a._metres_to_world(20.0, 0.0))
    a._drag_guide_to(*a._metres_to_world(26.0, 2.0))
    a._end_guide_drag()
    gd = a.guides[0]
    assert gd['p1'] == pytest.approx((26.0, 2.0), abs=1e-9)
    fn = tg.guide_callable(gd)
    assert fn(0.0) == pytest.approx((0.0, 0.0), abs=1e-9)
    assert fn(1.0) == pytest.approx((26.0, 2.0), abs=1e-9)
    # the rise is still 4 m, now above the NEW chord
    assert fn(0.5)[1] - 1.0 == pytest.approx(4.0, abs=1e-9)


def test_dragging_the_shape_handle_sets_the_rise(app):
    from apps.truss import truss_guides as tg
    a, root = app
    free_snaps(a)
    add_fit(a, 'parabola', 'rise', 4.0)
    a.sel_guide = 0
    a._begin_guide_drag(0, 2, *a._metres_to_world(10.0, 4.0))
    a._drag_guide_to(*a._metres_to_world(10.0, 7.0))
    a._end_guide_drag()
    assert a.guides[0]['value'] == pytest.approx(7.0, abs=1e-9)
    assert tg.guide_callable(a.guides[0])(0.5)[1] == pytest.approx(7.0, abs=1e-9)


def test_dragging_the_curve_body_translates_the_whole_guide(app):
    from apps.truss import truss_guides as tg
    a, root = app
    free_snaps(a)
    add_fit(a)
    a.sel_guide = 0
    a._begin_guide_drag(0, None, *a._metres_to_world(5.0, 3.0))
    a._drag_guide_to(*a._metres_to_world(8.0, 5.0))
    a._end_guide_drag()
    gd = a.guides[0]
    assert gd['p0'] == pytest.approx((3.0, 2.0), abs=1e-9)
    assert gd['p1'] == pytest.approx((23.0, 2.0), abs=1e-9)
    assert tg.guide_callable(gd)(0.5)[1] == pytest.approx(6.0, abs=1e-9)


def test_a_typed_function_guide_can_be_moved_too(app):
    """y = f(x) is tied to the axes, so without an origin offset it could not
    be translated at all without rewriting its algebra."""
    from apps.truss import truss_guides as tg
    a, root = app
    free_snaps(a)
    a.guide_kind.set('func'); a._sync_guide_fields()
    a.guide_expr.set('4*f*x*(L-x)/L^2'); a.guide_params.set('L=20, f=4')
    a.guide_x0.set(0.0); a.guide_x1.set(20.0)
    a._add_guide()
    before = tg.guide_callable(a.guides[0])(0.5)
    a.sel_guide = 0
    a._begin_guide_drag(0, 0, *a._metres_to_world(*tg.guide_handles(a.guides[0])[0][1]))
    a._drag_guide_to(*a._metres_to_world(3.0, 2.0))
    a._end_guide_drag()
    after = tg.guide_callable(a.guides[0])(0.5)
    assert after[0] - before[0] == pytest.approx(3.0, abs=1e-9)
    assert after[1] - before[1] == pytest.approx(2.0, abs=1e-9)


def test_a_guide_move_is_one_undo_step(app):
    a, root = app
    free_snaps(a)
    add_fit(a)
    start = tuple(a.guides[0]['p1'])
    a.sel_guide = 0
    a._begin_guide_drag(0, 1, *a._metres_to_world(20.0, 0.0))
    for x in (22.0, 24.0, 26.0):
        a._drag_guide_to(*a._metres_to_world(x, 0.0))
    a._end_guide_drag()
    assert a.guides[0]['p1'] != start
    a._undo()
    assert tuple(a.guides[0]['p1']) == start


def test_moving_a_guide_does_not_move_nodes_arrayed_onto_it(app):
    """A construction line quietly dragging real structure with it is the kind
    of surprise that makes a model untrustworthy. Re-array is the deliberate
    way to bring them along."""
    a, root = app
    free_snaps(a)
    add_fit(a)
    a.path_guide.set(a._guide_label(0, a.guides[0]))
    a.path_mode.set('count'); a.path_n.set(5)
    a.path_s0.set(0.0); a.path_s1.set(0.0); a.path_chain.set(False)
    a._array_path()
    assert len(a.nodes) == 5
    before = [tuple(n) for n in a.nodes]

    a.sel_guide = 0
    a._begin_guide_drag(0, None, *a._metres_to_world(5.0, 3.0))
    a._drag_guide_to(*a._metres_to_world(5.0, 9.0))
    a._end_guide_drag()
    assert [tuple(n) for n in a.nodes] == before, 'the guide dragged nodes with it'

    a._re_array()
    after = [tuple(n) for n in a.nodes]
    assert after != before
    # every node moved by the same 6 m the guide did
    for (bx, by_), (ax, ay) in zip(before, after):
        assert ax - bx == pytest.approx(0.0, abs=1e-6)
        assert ay - by_ == pytest.approx(-6.0 * PX_PER_M, abs=1e-6)


def test_re_array_refuses_when_the_node_count_would_change(app):
    """Rather than silently re-wiring which rods attach to what."""
    a, root = app
    free_snaps(a)
    add_fit(a, 'arc', 'length', 24.0)
    a.path_guide.set(a._guide_label(0, a.guides[0]))
    a.path_mode.set('spacing'); a.path_step.set(3.0)
    a.path_s0.set(0.0); a.path_s1.set(0.0); a.path_chain.set(False)
    a._array_path()
    n0 = len(a.nodes)
    assert n0 > 2
    # make the guide much longer: the same spacing now yields more nodes
    a.guides[0]['value'] = 60.0
    a._re_array()
    assert len(a.nodes) == n0, 'nodes were added or removed by a re-array'


def test_deleting_a_guide_remaps_the_array_history(app):
    """Guide indices shift down past a deleted one, exactly as node indices
    do. An un-remapped history would let a later Re-array rewrite nodes from
    the wrong curve."""
    a, root = app
    free_snaps(a)
    add_fit(a, 'parabola', 'rise', 3.0)          # guide 0
    add_fit(a, 'parabola', 'rise', 6.0)          # guide 1
    a.path_guide.set(a._guide_label(1, a.guides[1]))
    a.path_mode.set('count'); a.path_n.set(4)
    a.path_s0.set(0.0); a.path_s1.set(0.0); a.path_chain.set(False)
    a._array_path()
    assert 1 in a._array_history
    a.guide_list.selection_set(0)
    a._delete_guide()
    assert 0 in a._array_history and 1 not in a._array_history
    assert len(a.guides) == 1


def test_five_point_conic_pick_builds_a_guide(app):
    from apps.truss import truss_guides as tg
    a, root = app
    free_snaps(a)
    a._start_conic_pick()
    assert a._picking_conic
    for ang in (0.3, 1.1, 2.0, 3.4, 5.0):
        a._conic_pick_click(*a._metres_to_world(2 + 5 * math.cos(ang),
                                                 1 + 5 * math.sin(ang)))
    assert not a._picking_conic
    assert len(a.guides) == 1 and a.guides[0]['kind'] == 'conic5'
    assert tg.conic_describe(a.guides[0]) == 'ellipse'
    for x, y in tg.path_array(a.guides[0], count=6):
        assert math.hypot(x - 2.0, y - 1.0) == pytest.approx(5.0, abs=1e-6)


def test_a_degenerate_five_point_pick_is_rejected_and_reset(app):
    a, root = app
    free_snaps(a)
    a._start_conic_pick()
    for x in (0.0, 1.0, 2.0, 3.0, 4.0):          # all collinear
        a._conic_pick_click(*a._metres_to_world(x, x))
    assert a.guides == []
    assert a.conic_pts == []
    assert not a._picking_conic


def test_escape_cancels_a_five_point_pick(app):
    a, root = app
    a._start_conic_pick()
    a._conic_pick_click(*a._metres_to_world(1.0, 1.0))
    assert len(a.conic_pts) == 1
    a._cancel_conic_pick()
    assert not a._picking_conic and a.conic_pts == []
    assert a.guides == []
