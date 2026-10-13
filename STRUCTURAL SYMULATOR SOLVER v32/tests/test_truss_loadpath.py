"""Where one load goes, and the reason it is computed by superposition.

The structure is linear elastic, so the answer for all the loads together
is exactly the sum of the answers for each one alone. `truss_loadpath`
re-solves the model with a single load applied and reports the member
forces and reactions that come back. That is not an estimate, and the
tests below pin it against hand statics.

THE VERSION THIS REPLACED walked the joints, splitting the load at each
one between the members that resisted it. It looked reasonable and it
reported a quarter-point load on the Warren truss going 100% to the near
support, where statics says 75/25. `test_a_quarter_point_load_splits_75_25`
is here because of that: a load path that disagrees with the reactions is
worse than none, since the student has no way to catch it.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.truss.truss_math import analyze
from apps.truss import truss_loadpath as lp


def _warren():
    """The tab's own Warren truss: a 20 m span on a pin and a roller, with
    joints at the quarter points."""
    nodes = [(96, 288), (216, 192), (336, 288), (456, 192), (576, 288)]
    mk = lambda a, b, A: {'a': a, 'b': b, 'E': 200.0, 'A': A}
    rods = [mk(0, 1, 10), mk(1, 2, 10), mk(2, 3, 10), mk(3, 4, 10),
            mk(0, 2, 8), mk(2, 4, 8), mk(1, 3, 8)]
    supports = [{'node': 0, 'type': 'pin'}, {'node': 4, 'type': 'rollerX'}]
    loads = [{'node': 1, 'fx': 0, 'fy': 30},
             {'node': 2, 'fx': 0, 'fy': 60},
             {'node': 3, 'fx': 0, 'fy': 30}]
    return nodes, rods, supports, loads


def _trace(node):
    nodes, rods, supports, loads = _warren()
    return lp.trace(nodes, rods, supports, [], loads, node, analyze)


# ═════════════════════════════════════════════════════════════════════════════
#  It must agree with statics
# ═════════════════════════════════════════════════════════════════════════════
def test_a_quarter_point_load_splits_75_25():
    """Hand statics: a load a quarter of the way along a simply supported
    span puts three quarters of itself on the near support."""
    r = _trace(1)
    assert r['note'] is None
    assert r['supports'][0] == pytest.approx(0.75, abs=0.01)
    assert r['supports'][4] == pytest.approx(0.25, abs=0.01)


def test_a_central_load_splits_evenly():
    r = _trace(2)
    assert r['supports'][0] == pytest.approx(0.5, abs=0.01)
    assert r['supports'][4] == pytest.approx(0.5, abs=0.01)


def test_the_far_quarter_point_is_the_mirror_image():
    left, right = _trace(1), _trace(3)
    assert left['supports'][0] == pytest.approx(right['supports'][4], abs=0.01)
    assert left['supports'][4] == pytest.approx(right['supports'][0], abs=0.01)


def test_the_shares_account_for_the_whole_load():
    for node in (1, 2, 3):
        total = sum(_trace(node)['supports'].values())
        assert total == pytest.approx(1.0, abs=0.01), node


def test_superposition_reconstructs_the_real_solve():
    """The property the whole approach rests on. If the single-load solves
    do not add back up to the full one, the traces are describing some
    other structure."""
    nodes, rods, supports, loads = _warren()
    full, err = analyze(nodes, rods, loads, supports, [])
    assert err is None

    total = [0.0] * len(rods)
    for load in loads:
        r = lp.trace(nodes, rods, supports, [], loads, load['node'], analyze)
        for i, v in r['forces'].items():
            total[i] += v

    for i, rr in enumerate(full['rod_res']):
        assert total[i] == pytest.approx(rr['force'], abs=1e-9), f'rod {i}'


# ═════════════════════════════════════════════════════════════════════════════
#  What it reports
# ═════════════════════════════════════════════════════════════════════════════
def test_the_carrying_members_are_ranked_outward_from_the_load():
    """So an animation runs the way the load travels, not in index order."""
    r = _trace(1)
    assert r['order'], 'no members were ordered'
    # the first member out of joint 1 must actually touch joint 1
    nodes, rods, _s, _l = _warren()
    first = rods[r['order'][0]]
    assert 1 in (first['a'], first['b'])


def test_shares_are_normalised_to_the_hardest_working_member():
    r = _trace(2)
    assert r['share'], 'nothing was reported as carrying the load'
    assert max(r['share'].values()) == pytest.approx(1.0)
    assert all(0.0 <= v <= 1.0 for v in r['share'].values())


def test_a_joint_with_no_load_says_so_rather_than_guessing():
    r = _trace(0)
    assert r['note'] and 'No load' in r['note']
    assert not r['share']


def test_a_zero_load_says_so():
    nodes, rods, supports, _loads = _warren()
    r = lp.trace(nodes, rods, supports, [],
                 [{'node': 1, 'fx': 0.0, 'fy': 0.0}], 1, analyze)
    assert r['note'] and 'zero' in r['note']


def test_an_unsolvable_structure_reports_the_solver_s_reason():
    """A mechanism must come back as a message, not as an empty drawing."""
    nodes = [(0, 0), (100, 0)]
    rods = [{'a': 0, 'b': 1, 'E': 200.0, 'A': 10.0}]
    r = lp.trace(nodes, rods, [], [], [{'node': 1, 'fx': 0, 'fy': 10}],
                 1, analyze)
    assert r['note']
    assert not r['share']


def test_the_summary_names_the_joints_the_way_the_drawing_does():
    r = _trace(1)
    text = lp.summary(r, joint_name=lambda i: 'ABCDE'[i])
    assert text.startswith('The load at B lands on')
    assert 'A 75%' in text and 'E 25%' in text


def test_the_summary_can_quote_the_hardest_working_member():
    r = _trace(1)
    text = lp.summary(r, joint_name=str, force_fmt=lambda v: f'{v:+.1f} kN')
    assert 'hardest-working member' in text


def test_a_cantilever_puts_everything_on_its_one_support():
    nodes = [(0, 0), (120, 0), (240, 0), (120, 96)]
    mk = lambda a, b: {'a': a, 'b': b, 'E': 200.0, 'A': 10.0}
    rods = [mk(0, 1), mk(1, 2), mk(0, 3), mk(3, 1), mk(3, 2)]
    supports = [{'node': 0, 'type': 'pin'}, {'node': 3, 'type': 'pin'}]
    loads = [{'node': 2, 'fx': 0, 'fy': 20}]
    r = lp.trace(nodes, rods, supports, [], loads, 2, analyze)
    assert r['note'] is None
    assert sum(r['supports'].values()) == pytest.approx(1.0, abs=0.01)


def test_tracing_does_not_disturb_the_model():
    """It runs an extra solve; the caller's lists must come back untouched."""
    nodes, rods, supports, loads = _warren()
    before = ([tuple(n) for n in nodes], [dict(r) for r in rods],
              [dict(s) for s in supports], [dict(l) for l in loads])
    lp.trace(nodes, rods, supports, [], loads, 1, analyze)
    assert [tuple(n) for n in nodes] == before[0]
    assert [dict(r) for r in rods] == before[1]
    assert [dict(s) for s in supports] == before[2]
    assert [dict(l) for l in loads] == before[3]


# ═════════════════════════════════════════════════════════════════════════════
#  Choosing the load (v32 t 11)
#
#  Asked for on 12-10-26: "i would like to be able to select the force that
#  it is describing the path of". The trace used to choose for you -- the
#  selected joint if it was loaded, else the biggest load -- and only at the
#  moment it was switched on.
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture()
def app(monkeypatch):
    import gc
    import time
    tk = pytest.importorskip('tkinter')
    from tkinter import messagebox
    for name in ('showerror', 'showwarning', 'showinfo'):
        monkeypatch.setattr(messagebox, name, lambda *a, **k: None)
    from apps.truss.truss_app import TrussApp
    root = None
    for attempt in range(4):
        try:
            root = tk.Tk()
            break
        except Exception:
            gc.collect()
            time.sleep(0.25 * (attempt + 1))
    if root is None:
        pytest.skip('no display')
    root.geometry('1440x900+0+0')
    host = tk.Frame(root)
    host.pack(fill='both', expand=True)
    a = TrussApp(host)
    root.update()
    a._load_library_example('pratt')          # three loads, at G, H and I
    a._run_analysis(quiet=True)
    try:
        yield a
    finally:
        root.destroy()
        gc.collect()


def _on(app):
    app.show_load_path.set(True)
    app._toggle_load_path()
    app.root.update()


def test_the_chooser_lists_every_load_and_appears_with_the_switch(app):
    # Packed or not -- not "on screen", which also depends on which mode
    # the rail happens to be showing.
    assert not app.lp_row.winfo_manager()
    _on(app)
    assert app.lp_row.winfo_manager()
    values = list(app.lp_box['values'])
    assert len(values) == len(app._traceable_loads()) == 3
    assert all('↓' in v and 'kN' in v for v in values)
    assert app.lp_choice.get() in values, 'the traced load is not shown'
    app.show_load_path.set(False)
    app._toggle_load_path()
    app.root.update()
    assert not app.lp_row.winfo_manager()


def test_picking_a_load_in_the_list_traces_that_load(app):
    _on(app)
    for i, node in enumerate(app._lp_choices):
        app.lp_box.current(i)
        app._on_load_path_choice()
        assert app._lp['start'] == node
        assert app.joint_label(node) in app.status_var.get()


def test_the_arrows_step_through_the_loads_and_wrap_round(app):
    _on(app)
    nodes = list(app._traceable_loads())
    app._trace_load_at(nodes[0])
    seen = []
    for _ in range(len(nodes)):
        app._step_load_path(1)
        seen.append(app._lp['start'])
    assert seen == nodes[1:] + nodes[:1]
    app._step_load_path(-1)
    assert app._lp['start'] == nodes[-1]


def test_clicking_a_loaded_joint_traces_it(app):
    _on(app)
    target = list(app._traceable_loads())[-1]
    app._trace_load_at(list(app._traceable_loads())[0])
    app._set_tool('select')
    wx, wy = app.nodes[target][:2]
    app._press_wx, app._press_wy = wx, wy
    app._press_sx, app._press_sy = 0, 0
    app._dragging_box, app._box_cur = False, None

    class E:
        state = 0
        x = y = 0
    app._on_release(E())
    assert app._lp['start'] == target


def test_the_chosen_load_survives_an_edit_and_a_fresh_solve(app):
    _on(app)
    target = list(app._traceable_loads())[1]
    app._trace_load_at(target)
    app._invalidate_results()                 # an edit drops the trace
    assert app._lp is None
    app._run_analysis(quiet=True)
    assert app._lp is not None and app._lp['start'] == target


def test_a_chosen_load_that_is_deleted_falls_back_to_another(app):
    _on(app)
    nodes = list(app._traceable_loads())
    app._trace_load_at(nodes[0])
    app.loads = [l for l in app.loads if l['node'] != nodes[0]]
    app._invalidate_results()
    app._run_analysis(quiet=True)
    assert app._lp['start'] in nodes[1:]
    assert len(app.lp_box['values']) == 2


# ── "Force on each member" (v32 t 11) ─────────────────────────────────────
#  Asked on 12-10-26: "are you sure the force on each member button is
#  working properly??" It was not: the switch was declared and wired to a
#  redraw, and nothing ever read it, so the forces stayed on regardless.
def _rod_labels(app):
    c = app.zc.canvas
    return [c.itemcget(i, 'text') for i in c.find_withtag('rod_label')
            if c.itemcget(i, 'fill') != 'white']


def test_force_on_each_member_switches_the_forces_off_and_back_on(app):
    app.show_force_labels.set(True)
    app._draw()
    on = _rod_labels(app)
    assert on and all(':' in t for t in on)
    app.show_force_labels.set(False)
    app._draw()
    off = _rod_labels(app)
    assert off, 'the rod numbers must stay, to tell the rods apart'
    assert all(t.isdigit() for t in off), off
    key = [app.zc.canvas.itemcget(i, 'text')
           for i in app.zc.canvas.find_withtag('force_key')
           if app.zc.canvas.type(i) == 'text']
    assert 'rod labels: number' in key
    app.show_force_labels.set(True)
    app._draw()
    assert all(':' in t for t in _rod_labels(app))


# ── the traced load's own arrow (v32 t 12) ────────────────────────────────
#  Asked on 13-10-26: "highlight the traced load's arrow on the drawing".
def test_the_traced_load_s_arrow_stands_out_and_the_others_step_back(app):
    c = app.zc.canvas
    app._draw()
    assert not c.find_withtag('load_arrow_traced')
    _on(app)
    target = app._lp_choices[1]
    app._trace_load_at(target)
    traced = c.find_withtag('load_arrow_traced')
    assert len(traced) == 1
    assert c.itemcget(traced[0], 'fill') == app.LP_COLOUR
    assert float(c.itemcget(traced[0], 'width')) > 2
    assert c.find_withtag('load_halo')
    others = c.find_withtag('load_arrow')
    assert len(others) == len(app._traceable_loads()) - 1
    assert all(c.itemcget(i, 'fill') == app.LOAD_DIMMED for i in others)
    # the arrow follows the choice
    sx, sy = app.zc.w2s(*app.nodes[target][:2])
    _x0, _y0, x1, y1 = c.coords(traced[0])
    assert (x1, y1) == pytest.approx((sx, sy), abs=1.0)
    app.show_load_path.set(False)
    app._toggle_load_path()
    assert not c.find_withtag('load_arrow_traced')
    assert all(c.itemcget(i, 'fill') != app.LOAD_DIMMED
               for i in c.find_withtag('load_arrow'))
