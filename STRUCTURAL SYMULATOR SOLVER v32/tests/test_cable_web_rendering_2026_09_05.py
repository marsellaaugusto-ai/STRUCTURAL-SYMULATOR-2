"""Regression tests for the 2026-09-05 Cable Web rendering work:

1. The plateau at the sag vertex (reported: "the cables with self weight are
   not smooth, they plateau around the peak or valley").
   Two independent causes, so two guards:
     a. an ODD solver mesh puts two equal-height nodes either side of the
        vertex, and the true low point between them is unreachable;
     b. even with an even mesh, a point load inserts its own breakpoint and
        the vertex stops landing on a node.
   The control that makes these testable at all: a real catenary IS flat at
   its vertex, so "looks flat" is not by itself a defect. Every assertion
   below compares the DRAWN curve's flat run against the flat run of the
   mathematically exact catenary at the same on-screen scale.

2. Loads are drawn on the antifunicular, not only on the funicular.

3. The tension/thrust diagram series is physically right -- in particular
   the horizontal thrust H is constant along a cable under vertical load,
   which is the classic check the diagram exists to make visible.
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

from apps.cable_web.cable_web_app import CableWebApp, PX_PER_M, LOAD, ANTI
from common import CT, CL, CZ
from apps.cable_web.cable_web_math import CableWebResult


# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------

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


def _make_app():
    root = _new_root_or_skip()
    root.geometry('1100x800+0+0')
    app = CableWebApp(root)
    app.pack(fill='both', expand=True)
    app.reference_mode.set('straight')
    root.update_idletasks()
    root.update()
    return root, app


def _teardown(root):
    try:
        root.destroy()
    finally:
        gc.collect()


def _m(x, y):
    return x * PX_PER_M, -y * PX_PER_M


def _reset(app):
    app.nodes = []; app.cables = []; app.loads = []
    app.result = None; app.results_current = False; app._solver_meta = None
    app.next_node_id = app.next_cable_id = app.next_load_id = 1
    app._history = []; app._future = []


def _analyze(app, root, timeout=200):
    t0 = time.perf_counter()
    app._solve_exact()
    while app._solving and time.perf_counter() - t0 < timeout:
        root.update()
        time.sleep(0.02)
    return app.result


def _catenary_a(span, arc):
    """Solve 2a*sinh(span/2a) = arc for the catenary parameter."""
    lo, hi = 1e-6, 1e6
    for _ in range(300):
        a = 0.5 * (lo + hi)
        if 2.0 * a * math.sinh(span / (2.0 * a)) > arc:
            lo = a
        else:
            hi = a
    return 0.5 * (lo + hi)


def _flat_run_fraction(points, tol=0.75):
    """Longest horizontal run within `tol` px of the extreme y, as a
    fraction of the drawn width -- i.e. how much of the span reads flat."""
    if len(points) < 2:
        return 0.0
    ymax = max(p[1] for p in points)
    near = sorted(p[0] for p in points if ymax - p[1] <= tol)
    width = max(p[0] for p in points) - min(p[0] for p in points)
    if len(near) < 2 or width <= 1e-9:
        return 0.0
    return (near[-1] - near[0]) / width


def _true_catenary_flat_fraction(span, arc, scale, tol=0.75):
    a = _catenary_a(span, arc)
    top = math.cosh(span / (2 * a))
    n = 3000
    ys = [-(a * (math.cosh((span * i / n - span / 2.0) / a) - top)) * scale
          for i in range(n + 1)]
    ymax = max(ys)
    near = [span * i / n for i, y in enumerate(ys) if ymax - y <= tol]
    return (max(near) - min(near)) / span if len(near) > 1 else 0.0


def _capture_drawn_group(app, root):
    """The longest polyline actually handed to the canvas for the funicular."""
    captured = []
    original = CableWebApp._smooth_polyline

    def spy(points, samples_per_segment=12):
        out = original(points, samples_per_segment)
        captured.append((list(points), list(out)))
        return out

    CableWebApp._smooth_polyline = staticmethod(spy)
    try:
        app._fit_view()
        app._draw()
        root.update()
    finally:
        CableWebApp._smooth_polyline = staticmethod(original)
    if not captured:
        return None, None
    return max(captured, key=lambda t: len(t[0]))


def _build_cable(app, span, arc, w=10.0, point_load_s=None, point_load=150.0):
    a = app._new_node(*_m(0, 0), support=True)
    b = app._new_node(*_m(span, 0), support=True)
    c = app._new_cable(a['id'], b['id'])
    c['length_override'] = arc
    c['w'] = w
    if point_load_s is not None:
        app.loads.append({'id': 'L1', 'cable': c['id'], 'type': 'Point',
                          's1': point_load_s, 's2': point_load_s,
                          'magnitude': point_load, 'direction': 'Vertical',
                          'angle_deg': -90.0, 'expression': ''})
    return c


# --------------------------------------------------------------------------
# 1. the plateau
# --------------------------------------------------------------------------

PLATEAU_CASES = [
    # (label, span, arc, point_load_s) -- the first three had an ODD mesh
    # before the fix and drew 2.1x-6.3x flatter than a true catenary.
    ('8 m span, 12.0 m cable  (was nseg=5, 6.3x)', 8.0, 12.0, None),
    ('8 m span, 10.4 m cable  (was nseg=5, 4.9x)', 8.0, 10.4, None),
    ('10 m span, 11.5 m cable (was nseg=5, 3.7x)', 10.0, 11.5, None),
    ('12 m span, 15.6 m cable (was nseg=7, 3.5x)', 12.0, 15.6, None),
    ('16 m span, 16.8 m cable (was nseg=7, 2.1x)', 16.0, 16.8, None),
]


@pytest.mark.parametrize('label,span,arc,pls', PLATEAU_CASES,
                         ids=[c[0].split('(')[0].strip() for c in PLATEAU_CASES])
def test_self_weight_cable_is_not_flatter_than_a_real_catenary(label, span, arc, pls):
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        _build_cable(app, span, arc, point_load_s=pls)
        root.update()
        assert _analyze(app, root) is not None, f'{label}: Analyze failed'
        raw, drawn = _capture_drawn_group(app, root)
        assert drawn, f'{label}: nothing drawn'
        scale = (drawn[-1][0] - drawn[0][0]) / span
        got = _flat_run_fraction(drawn)
        true = _true_catenary_flat_fraction(span, arc, scale)
        assert true > 0.0
        assert got <= 1.35 * true, (
            f'{label}: drawn curve is flat over {got*100:.1f}% of the span but '
            f'a true catenary is only flat over {true*100:.1f}% -- a plateau '
            f'({got/true:.1f}x). See _solver_breakpoints and _insert_sag_vertex.')
    finally:
        _teardown(root)


def test_point_load_does_not_reintroduce_the_plateau():
    """A point load inserts its own breakpoint, so the mesh either side of it
    is no longer symmetric and the vertex stops landing on a node. Measured
    before _insert_sag_vertex: 13.1% of the group flat, versus 6.4% for the
    same cable with no point load (which is itself faithful)."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        _build_cable(app, 20.0, 26.0, point_load_s=6.0)
        root.update()
        assert _analyze(app, root) is not None
        raw, drawn = _capture_drawn_group(app, root)
        assert drawn
        got = _flat_run_fraction(drawn)
        assert got <= 0.10, (
            f'point-loaded cable draws flat over {got*100:.1f}% of its longest '
            f'group; the unloaded control is ~6.4% and a true catenary ~5-7%')
    finally:
        _teardown(root)


def test_sag_vertex_insertion_is_conservative():
    """_insert_sag_vertex must add at most one point, only where the span
    actually turns, and never touch a monotone run (a straight hanger, or a
    branch either side of a kink)."""
    f = CableWebApp._insert_sag_vertex
    monotone = [(0.0, 0.0), (1.0, -1.0), (2.0, -2.0), (3.0, -3.0)]
    assert f(monotone) == monotone, 'a monotone run has no vertex to insert'
    vertical = [(0.0, 0.0), (0.0, -1.0), (0.0, -2.0)]
    assert f(vertical) == vertical, 'a vertical hanger has no y(x) vertex'
    assert f([(0.0, 0.0), (1.0, -1.0)]) == [(0.0, 0.0), (1.0, -1.0)]
    # A symmetric sag whose vertex already sits ON a node must be left alone.
    on_node = [(-2.0, 4.0), (-1.0, 1.0), (0.0, 0.0), (1.0, 1.0), (2.0, 4.0)]
    assert f(on_node) == on_node, 'vertex already on a node -- nothing to add'
    # A sag whose vertex falls BETWEEN nodes gains exactly one point, in
    # order, below both neighbours.
    between = [(-3.0, 9.0), (-1.0, 1.0), (1.0, 1.0), (3.0, 9.0)]
    out = f(between)
    assert len(out) == len(between) + 1, 'expected exactly one inserted point'
    xs = [p[0] for p in out]
    assert xs == sorted(xs), 'inserted point must keep x order'
    inserted = [p for p in out if p not in between]
    assert len(inserted) == 1
    xv, yv = inserted[0]
    assert -1.0 < xv < 1.0
    assert yv < 1.0, 'the recovered vertex must lie below the nodes it sits between'
    assert abs(xv) < 1e-9, f'symmetric data should put the vertex at x=0, got {xv}'


# --------------------------------------------------------------------------
# 2. antifunicular loads
# --------------------------------------------------------------------------

def _fill_count(app, fill):
    c = app.zc.canvas
    return sum(1 for it in c.find_all()
               if c.type(it) in ('line', 'text') and c.itemcget(it, 'fill') == fill)


def test_antifunicular_shows_the_loads():
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        app._load_example()
        root.update()
        assert _analyze(app, root) is not None

        app.show_antifunicular.set(False)
        app._fit_view(); app._draw(); root.update()
        anti_off = _fill_count(app, ANTI)
        fun_loads = _fill_count(app, LOAD)
        assert fun_loads > 0, 'the funicular should have load glyphs to begin with'

        app.show_antifunicular.set(True)
        app._fit_view(); app._draw(); root.update()
        anti_on_with_loads = _fill_count(app, ANTI)

        app.show_loads.set(False)
        app._draw(); root.update()
        anti_on_no_loads = _fill_count(app, ANTI)

        assert anti_on_with_loads > anti_off, 'antifunicular drew nothing'
        assert anti_on_with_loads > anti_on_no_loads, (
            'turning loads off changed nothing in the antifunicular -- its '
            'load glyphs are missing')
        assert anti_on_with_loads - anti_on_no_loads == fun_loads, (
            'the antifunicular should carry the same number of load glyphs as '
            'the funicular: got '
            f'{anti_on_with_loads - anti_on_no_loads} vs {fun_loads}')
    finally:
        _teardown(root)


# --------------------------------------------------------------------------
# 3. tension / thrust diagrams
# --------------------------------------------------------------------------

def test_thrust_is_constant_under_vertical_load():
    """H = T*cos(theta) is exactly constant along a cable carrying only
    vertical load. That is the physical invariant the thrust diagram exists
    to show, so it is worth asserting on the series the diagram plots."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        c = _build_cable(app, 20.0, 26.0, point_load_s=6.0)
        root.update()
        assert _analyze(app, root) is not None
        series = app._diagram_series(c['id'])
        assert len(series) >= 4, 'expected several solver edges to plot'
        Ts = [r[2] for r in series]
        Hs = [r[3] for r in series]
        assert min(Ts) > 0.0, 'a loaded cable must be in tension everywhere'
        assert max(Ts) > min(Ts), 'tension should vary along a sagging cable'
        spread = (max(Hs) - min(Hs)) / max(Hs)
        assert spread < 0.01, (
            f'horizontal thrust varies by {spread*100:.2f}% along a cable under '
            f'purely vertical load; it should be constant')
        # s must cover the cable, in order
        assert series[0][0] == pytest.approx(0.0, abs=1e-6)
        assert series[-1][1] == pytest.approx(app._cable_length(c['id']), rel=1e-6)
    finally:
        _teardown(root)


def test_diagram_pane_is_off_by_default_and_clears_on_edit():
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        assert app.show_diagrams.get() is False, \
            'the diagram pane costs canvas height; it must be opt-in'
        assert not app.diag_outer.winfo_ismapped()
        app._load_example(); root.update()
        app.show_diagrams.set(True); app._sync_diagram_pane(); root.update()
        assert app.diag_outer.winfo_ismapped()
        assert list(app.diag_combo['values']) == ['C1', 'C2', 'C3']
        assert _analyze(app, root) is not None
        app._sync_diagram_pane(); root.update()
        assert app._diagram_series(1), 'expected a series after a converged solve'
        app._invalidate('edited')
        root.update()
        assert app._diagram_series(1) == [], \
            'the diagrams must not keep plotting tensions from a stale model'
    finally:
        _teardown(root)


def test_sag_vertex_never_creates_a_sliver_segment():
    """The apex must never split a segment near either of its ends.

    A sliver beside a full-length neighbour makes the centred (Catmull-Rom)
    tangents in _smooth_polyline overshoot, and the drawn curve then
    oscillates. Measured 2026-09-05 on the built-in Example's C2 with the
    original 2%-of-window guard: the apex landed 5.70 px from a node against
    97.47 px typical spacing, and the drawn curve went from 1 direction
    reversal (a correct single sag) to 3, overshooting the solved envelope by
    2.9 px.

    The guarantee is deliberately RELATIVE to the segment being split, not
    absolute: a short segment in a well-formed mesh has short neighbours, so
    what matters is that neither resulting sub-segment is a small fraction of
    the one it came from.
    """
    f = CableWebApp._insert_sag_vertex
    cases = [
        [(-3.0, 9.0), (-1.0, 1.0), (1.0, 1.0), (3.0, 9.0)],
        [(0.0, 16.0), (2.0, 4.0), (6.0, 4.0), (8.0, 16.0)],
        [(0.0, 25.0), (3.0, 4.0), (5.0, 1.0), (9.0, 16.0)],
        [(0.0, 100.0), (10.0, 0.02), (10.4, 0.0), (20.0, 100.0)],
        [(0.0, 60.0), (9.5, 1.0), (10.0, 0.9), (10.5, 1.1), (20.0, 60.0)],
    ]
    inserted_any = False
    for pts in cases:
        out = f(pts)
        if out == pts:
            continue
        inserted_any = True
        assert len(out) == len(pts) + 1
        extra = [i for i, q in enumerate(out) if q not in pts]
        assert len(extra) == 1, 'expected exactly one new point'
        i = extra[0]
        before = abs(out[i][0] - out[i - 1][0])
        after = abs(out[i + 1][0] - out[i][0])
        parent = before + after
        assert parent > 0
        assert min(before, after) >= 0.18 * parent, (
            f'apex split its segment {min(before, after) / parent:.1%} from an '
            f'end, creating a sliver: {[round(q[0], 3) for q in out]}')
    assert inserted_any, 'no case inserted anything; the test checked nothing'


def test_drawn_curve_adds_no_direction_reversals():
    """The drawn funicular must not oscillate where the solved data does not.

    Counts direction reversals in the offset from each drawn group's own
    chord, RAW versus DRAWN. A single sag has exactly one; more in the drawn
    curve than in the data is the reported wobble.
    """
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        app._load_example()
        root.update()
        assert _analyze(app, root) is not None

        captured = []
        original = CableWebApp._smooth_polyline

        def spy(points, samples_per_segment=12):
            out = original(points, samples_per_segment)
            captured.append((list(points), list(out)))
            return out

        CableWebApp._smooth_polyline = staticmethod(spy)
        try:
            app._fit_view(); app._draw(); root.update()
        finally:
            CableWebApp._smooth_polyline = staticmethod(original)

        def offsets(pts):
            (x0, y0), (x1, y1) = pts[0], pts[-1]
            dx, dy = x1 - x0, y1 - y0
            L = max(math.hypot(dx, dy), 1e-12)
            ux, uy = dx / L, dy / L
            return [(-(p[1] - y0) * ux + (p[0] - x0) * uy) for p in pts]

        def reversals(v, tol=0.02):
            d = [v[i + 1] - v[i] for i in range(len(v) - 1)]
            d = [x for x in d if abs(x) > tol]
            return sum(1 for i in range(len(d) - 1) if (d[i] > 0) != (d[i + 1] > 0))

        checked = 0
        for raw, drawn in captured:
            if len(raw) < 3:
                continue
            o_raw = offsets(raw)
            if max(abs(v) for v in o_raw) < 1.0:
                continue                       # a straight stretch
            checked += 1
            r_raw = reversals(o_raw)
            r_drawn = reversals(offsets(drawn))
            assert r_drawn <= r_raw, (
                f'the drawn curve has {r_drawn} direction reversals where the '
                f'solved polyline has {r_raw} -- the smoothing is oscillating')
        assert checked, 'no sagging group was drawn; the test checked nothing'
    finally:
        _teardown(root)


# --------------------------------------------------------------------------
# 4. curvature-graded mesh (Route 2)
# --------------------------------------------------------------------------

def _free_turns(app, cid):
    """Turn angles at FREE interior nodes of a cable, in degrees.

    Kinks at point loads and junctions are physically real and excluded --
    grading neither can nor should remove them, and counting them would
    measure the structure instead of the discretisation.
    """
    meta = app._solver_meta
    ids = meta['cable_solver_nodes'].get(cid)
    bp = (meta.get('cable_bp') or {}).get(cid)
    if not ids or not bp or len(ids) != len(bp) or len(ids) < 3:
        return []
    pinned = app._pinned_breakpoints(cid)
    P = [app.result.positions[i] for i in ids]
    ang = []
    for i in range(len(P) - 1):
        dx, dy = P[i+1][0] - P[i][0], P[i+1][1] - P[i][1]
        ang.append(math.atan2(dy, dx) if math.hypot(dx, dy) > 1e-12 else None)
    out = []
    for i in range(len(ang) - 1):
        if ang[i] is None or ang[i+1] is None:
            continue
        if any(abs(bp[i+1] - q) < 1e-7 for q in pinned):
            continue
        t = ang[i+1] - ang[i]
        while t > math.pi:
            t -= 2 * math.pi
        while t < -math.pi:
            t += 2 * math.pi
        out.append(abs(math.degrees(t)))
    return [t for t in out if t > 1e-9]


def _dof(app):
    model, _ = app._build_solver_model()
    nf = len([n for n in model.nodes.values() if not n.is_support])
    return 2 * nf + len(model.edges)


def test_graded_mesh_evens_out_the_turning_at_the_same_dof():
    """The point of Route 2: spread a loaded span's turning across its
    elements instead of letting it pile up at the vertex -- WITHOUT spending
    any extra unknowns, which is what uniform refinement cannot do.

    Measured 2026-09-05 on a plain UDL cable at 2:1 slack: largest free-node
    turn 57.09 deg uniform vs 27.29 deg graded, evenness ratio 10.43 -> 2.0.
    """
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        a = app._new_node(*_m(0, 0), support=True)
        b = app._new_node(*_m(10, 0), support=True)
        c = app._new_cable(a['id'], b['id'])
        c['length_override'] = 20.0
        app.loads.append({'id': 'UDL', 'cable': c['id'], 'type': 'UDL',
                          's1': 0.0, 's2': 20.0, 'magnitude': 10.0,
                          'direction': 'Vertical', 'angle_deg': -90.0,
                          'expression': ''})
        root.update()

        app.grade_mesh.set(False)
        assert _analyze(app, root) is not None, 'uniform-mesh solve failed'
        plain = _free_turns(app, c['id'])
        dof_plain = _dof(app)
        res_plain = app.result.residual
        assert plain, 'no free-node turns to measure'

        app._invalidate('re-solve')
        app.grade_mesh.set(True)
        assert _analyze(app, root) is not None, 'graded-mesh solve failed'
        graded = _free_turns(app, c['id'])
        dof_graded = _dof(app)
        assert graded

        assert dof_graded == dof_plain, (
            f'grading must not change the number of unknowns: '
            f'{dof_plain} -> {dof_graded}')
        assert max(graded) < 0.75 * max(plain), (
            f'largest free-node turn barely improved: '
            f'{max(plain):.2f} -> {max(graded):.2f} deg')
        ratio_plain = max(plain) / max(min(plain), 1e-9)
        ratio_graded = max(graded) / max(min(graded), 1e-9)
        assert ratio_graded < ratio_plain, (
            f'turning is no more evenly spread: ratio {ratio_plain:.1f} -> '
            f'{ratio_graded:.1f}')
        assert app.result.residual < 1e-6, (
            f'graded mesh solved to a poor residual {app.result.residual:.2e}')
    finally:
        _teardown(root)


def test_grading_never_moves_a_pinned_breakpoint():
    """Cable ends, junctions and load boundaries define the model. Only the
    free interior points may be re-placed."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        # Two suspended cables joined by a tie, with junction attachments and
        # a point load -- pinned breakpoints of every kind to protect.
        a1 = app._new_node(*_m(0, 0), support=True)
        a2 = app._new_node(*_m(12, 0), support=True)
        b1 = app._new_node(*_m(20, 0), support=True)
        b2 = app._new_node(*_m(32, 0), support=True)
        j1 = app._new_node(*_m(4, 0))
        j2 = app._new_node(*_m(24, 0))
        ca = app._new_cable(a1['id'], a2['id']); ca['length_override'] = 18.0
        cb = app._new_cable(b1['id'], b2['id']); cb['length_override'] = 18.0
        cc = app._new_cable(j1['id'], j2['id']); cc['length_override'] = 22.0
        ca['w'] = cb['w'] = cc['w'] = 8.0
        app._attach_node(j1['id'], ca['id'], 6.0)
        app._attach_node(j2['id'], cb['id'], 6.0)
        app.loads.append({'id': 'P', 'cable': cc['id'], 'type': 'Point',
                          's1': 9.0, 's2': 9.0, 'magnitude': 120.0,
                          'direction': 'Vertical', 'angle_deg': -90.0,
                          'expression': ''})
        root.update()
        app.grade_mesh.set(True)
        assert _analyze(app, root) is not None
        assert app._graded_bp, 'nothing was graded; the test checked nothing'
        for cid, bp in app._graded_bp.items():
            pinned = app._pinned_breakpoints(cid)
            for q in pinned:
                assert any(abs(sv - q) < 1e-7 for sv in bp), (
                    f'C{cid}: graded mesh dropped pinned breakpoint s={q:.6f}')
            assert bp == sorted(bp), f'C{cid}: graded breakpoints out of order'
            gaps = [bp[i+1] - bp[i] for i in range(len(bp) - 1)]
            assert min(gaps) > 1e-6, f'C{cid}: graded mesh has a degenerate element'
    finally:
        _teardown(root)


def test_grading_is_cleared_when_the_model_changes():
    """A graded mesh belongs to the model that produced it."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        _build_cable(app, 10.0, 20.0, w=10.0)
        root.update()
        app.grade_mesh.set(True)
        assert _analyze(app, root) is not None
        assert app._graded_bp, 'expected a graded mesh after a converged solve'
        app._invalidate('edited')
        assert app._graded_bp == {}, \
            'a stale graded mesh survived a model edit'
        assert app._solver_breakpoints(1) == app._solver_breakpoints(1)
    finally:
        _teardown(root)


def test_both_examples_still_converge_with_grading():
    """Grading changes the mesh under both built-in regression cases."""
    pytest.importorskip('scipy.optimize')
    for loader in ('_load_example', '_load_picture_example'):
        root, app = _make_app()
        try:
            app.grade_mesh.set(True)
            getattr(app, loader)()
            root.update()
            r = _analyze(app, root)
            assert r is not None and r.converged, f'{loader}: {app.validation_var.get()!r}'
            assert r.residual < 1e-6, f'{loader}: residual {r.residual:.2e}'
        finally:
            _teardown(root)


def _drawn_deviation_from_catenary(app, drawn, span, arc):
    """Largest gap, in screen px, between the drawn curve and the EXACT
    catenary through the same supports. This is the metric that matches what
    the user sees -- the solved polyline improving does not imply the drawn
    curve improves, because the interpolator sits between them."""
    A = _catenary_a(span, arc)
    true_pts = []
    for i in range(1201):
        x = span * i / 1200.0
        y = A * math.cosh((x - span / 2.0) / A) - A * math.cosh(span / (2.0 * A))
        true_pts.append(app.zc.w2s(*app._m_to_world(x, y)))
    # Distance to the reference CURVE, through its segments -- not to its
    # sample points. Distance-to-vertices overstates the gap by up to half the
    # reference's own sample spacing, which on a steep slack cable is larger
    # than the quantity being measured: it reported 0.79 px for a curve that
    # is exact (measured 2026-09-05, while building Route 1).
    worst = 0.0
    for px, py in drawn:
        best = float('inf')
        for i in range(len(true_pts) - 1):
            ax, ay = true_pts[i]
            bx, by = true_pts[i + 1]
            vx, vy = bx - ax, by - ay
            L2 = vx * vx + vy * vy
            t = 0.0 if L2 < 1e-18 else ((px - ax) * vx + (py - ay) * vy) / L2
            t = max(0.0, min(1.0, t))
            best = min(best, math.hypot(px - (ax + t * vx), py - (ay + t * vy)))
        worst = max(worst, best)
    return worst


def test_graded_mesh_draws_closer_to_the_true_catenary():
    """The user-facing claim, measured against closed form rather than against
    another discretisation.

    A slack self-weight cable (10 m span, 20 m arc) concentrates almost all of
    its curvature at the vertex, which is exactly the case a uniform mesh
    handles worst. Measured 2026-09-05: drawn deviation 7.93 px uniform vs
    2.31 px graded, at the same number of unknowns.
    """
    pytest.importorskip('scipy.optimize')
    devs = {}
    for grade in (False, True):
        root, app = _make_app()
        try:
            _reset(app)
            _build_cable(app, 10.0, 20.0, w=10.0)
            root.update()
            # Pin the DRAWING to Route 2 for both arms. With Route 1 (the
            # default) the drawn curve is the closed form either way, so this
            # test would be comparing a mesh change it cannot see.
            app.curve_route.set('graded')
            app.grade_mesh.set(grade)
            assert _analyze(app, root) is not None
            raw, drawn = _capture_drawn_group(app, root)
            assert drawn, 'nothing was drawn'
            devs[grade] = _drawn_deviation_from_catenary(app, drawn, 10.0, 20.0)
        finally:
            _teardown(root)
    assert devs[True] < 0.6 * devs[False], (
        'graded mesh did not bring the DRAWN curve closer to the true '
        'catenary: %.2f px -> %.2f px' % (devs[False], devs[True]))


def test_smoothing_is_unchanged_on_an_evenly_spaced_polyline():
    """`_smooth_polyline` was moved to chord-length parameterisation so the
    graded (deliberately uneven) mesh interpolates correctly. That change must
    be INERT on an even mesh -- it reduces to the centred difference it
    replaced -- so the grading-off path cannot have moved."""
    pts = [(0.0, 0.0), (10.0, -6.0), (20.0, -9.0), (30.0, -9.5),
           (40.0, -8.0), (50.0, -4.0), (60.0, 0.0)]

    # the previous implementation, verbatim: uniform parameterisation with
    # centred tangents and the same envelope clamp
    def legacy(points, samples_per_segment=12):
        n = len(points)
        tangents = []
        for i in range(n):
            if i == 0:
                t = (points[1][0] - points[0][0], points[1][1] - points[0][1])
            elif i == n - 1:
                t = (points[-1][0] - points[-2][0], points[-1][1] - points[-2][1])
            else:
                t = (0.5 * (points[i+1][0] - points[i-1][0]),
                     0.5 * (points[i+1][1] - points[i-1][1]))
            tangents.append(t)
        out = [points[0]]
        for i in range(n - 1):
            p0, p1 = points[i], points[i+1]
            m0, m1 = tangents[i], tangents[i+1]
            xlo, xhi = sorted((p0[0], p1[0])); ylo, yhi = sorted((p0[1], p1[1]))
            for k in range(1, samples_per_segment + 1):
                t = k / samples_per_segment; t2 = t*t; t3 = t2*t
                h00 = 2*t3 - 3*t2 + 1; h10 = t3 - 2*t2 + t
                h01 = -2*t3 + 3*t2; h11 = t3 - t2
                x = h00*p0[0] + h10*m0[0] + h01*p1[0] + h11*m1[0]
                y = h00*p0[1] + h10*m0[1] + h01*p1[1] + h11*m1[1]
                out.append((min(xhi, max(xlo, x)), min(yhi, max(ylo, y))))
        return out

    # Equal x steps and a gentle profile: chord lengths differ only slightly,
    # so the two must agree closely. On a genuinely equal-chord polyline they
    # agree exactly, which the second case checks.
    a = CableWebApp._smooth_polyline(pts)
    b = legacy(pts)
    assert len(a) == len(b)
    assert max(math.hypot(p[0]-q[0], p[1]-q[1]) for p, q in zip(a, b)) < 0.75

    square = [(0.0, 0.0), (10.0, 10.0), (20.0, 20.0), (30.0, 30.0)]
    a = CableWebApp._smooth_polyline(square)
    b = legacy(square)
    assert max(math.hypot(p[0]-q[0], p[1]-q[1]) for p, q in zip(a, b)) < 1e-9


# --------------------------------------------------------------------------
# 5. Route 1 -- the analytic curve
# --------------------------------------------------------------------------

def test_analytic_route_draws_the_exact_catenary():
    """Route 1's whole claim: a uniformly loaded stretch is drawn as the curve
    it actually is, not as an approximation of it.

    The closed form takes only the endpoint positions and the arc length
    between them -- both exact model quantities -- so its accuracy does not
    depend on the mesh at all. Measured 2026-09-05 against closed form, in
    screen px: 7.93 uniform / 2.31 graded / 0.00 analytic on the slack case.
    """
    pytest.importorskip('scipy.optimize')
    for span, arc in ((20.0, 22.0), (20.0, 26.0), (10.0, 20.0)):
        devs = {}
        for route in ('graded', 'analytic'):
            root, app = _make_app()
            try:
                _reset(app)
                _build_cable(app, span, arc, w=10.0)
                root.update()
                app.curve_route.set(route)
                app.grade_mesh.set(False)
                assert _analyze(app, root) is not None
                raw, drawn = _capture_drawn_group(app, root)
                assert drawn
                devs[route] = _drawn_deviation_from_catenary(app, drawn, span, arc)
            finally:
                _teardown(root)
        assert devs['analytic'] < 0.05, (
            '%.0f/%.0f: analytic curve is not exact: %.3f px'
            % (span, arc, devs['analytic']))
        assert devs['analytic'] < devs['graded'], (
            '%.0f/%.0f: analytic %.3f px is no better than the mesh %.3f px'
            % (span, arc, devs['analytic'], devs['graded']))


def test_the_two_routes_are_exclusive_and_analytic_is_the_cheap_one():
    """Selecting a route turns the other off. Route 1 needs no second solve,
    which is exactly why it is the default."""
    root, app = _make_app()
    try:
        assert app.curve_route.get() == 'analytic', 'Route 1 should be default'
        assert app.grade_mesh.get() is False, (
            'the default route must not be paying for a second solve')
        app.curve_route.set('graded')
        app._on_curve_route_changed()
        assert app.grade_mesh.get() is True
        app.curve_route.set('analytic')
        app._on_curve_route_changed()
        assert app.grade_mesh.get() is False
    finally:
        _teardown(root)


def test_analytic_route_runs_one_solve_pass_only():
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        _build_cable(app, 10.0, 20.0, w=10.0)
        root.update()
        app.curve_route.set('analytic')
        app.grade_mesh.set(False)
        assert _analyze(app, root) is not None
        assert app._graded_bp == {}, (
            'Route 1 re-meshed anyway; it is supposed to cost one solve')
    finally:
        _teardown(root)


def test_analytic_gate_refuses_the_loads_it_cannot_draw():
    """The closed form is a catenary, which is the shape of a stretch under a
    UNIFORM load per unit arc length and nothing else. Anything else must fall
    back to the solved polygon: drawing a confident curve that is the wrong
    curve is worse than drawing a visibly faceted right one."""
    root, app = _make_app()
    try:
        def build(extra=None):
            _reset(app)
            a = app._new_node(*_m(0, 0), support=True)
            b = app._new_node(*_m(20, 0), support=True)
            c = app._new_cable(a['id'], b['id'])
            c['length_override'] = 26.0
            c['w'] = 8.0
            if extra:
                app.loads.append(dict(extra, cable=c['id']))
            root.update()
            return c['id'], app._cable_length(c['id'])

        base = {'id': 'X', 'type': 'UDL', 's1': 0.0, 's2': 26.0,
                'magnitude': 10.0, 'direction': 'Vertical',
                'angle_deg': -90.0, 'expression': ''}

        cid, L = build()
        assert app._group_uniform_load(cid, 0.0, L) == pytest.approx(8.0), \
            'self-weight alone is uniform and must be accepted'

        cid, L = build(base)
        assert app._group_uniform_load(cid, 0.0, L) == pytest.approx(18.0), \
            'self-weight plus a covering UDL is still uniform'

        for name, extra in (
                ('a UDL covering only part', dict(base, s1=4.0, s2=15.0)),
                ('a Variable load', dict(base, type='Variable', expression='s')),
                ('a non-vertical UDL', dict(base, direction='Normal')),
                ('an upward UDL', dict(base, magnitude=-30.0))):
            cid, L = build(extra)
            assert app._group_uniform_load(cid, 0.0, L) is None, \
                '%s must be refused, not drawn as a catenary' % name
    finally:
        _teardown(root)


def test_analytic_route_falls_back_without_breaking_the_drawing():
    """A refused stretch must still be drawn -- by the other route."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        a = app._new_node(*_m(0, 0), support=True)
        b = app._new_node(*_m(20, 0), support=True)
        c = app._new_cable(a['id'], b['id'])
        c['length_override'] = 26.0
        c['w'] = 8.0
        app.loads.append({'id': 'V', 'cable': c['id'], 'type': 'Variable',
                          's1': 0.0, 's2': 26.0, 'magnitude': 10.0,
                          'direction': 'Vertical', 'angle_deg': -90.0,
                          'expression': 's'})
        root.update()
        app.curve_route.set('analytic')
        assert _analyze(app, root) is not None
        raw, drawn = _capture_drawn_group(app, root)
        assert drawn and len(drawn) > 3, 'a refused stretch was not drawn at all'
    finally:
        _teardown(root)


def test_analytic_curve_arches_in_the_antifunicular():
    """The closed form always sags; the antifunicular view is handed mirrored
    positions and must arch. The direction is taken from the solved polyline
    being replaced, so both views are right for the same reason."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        _build_cable(app, 20.0, 26.0, w=8.0)
        root.update()
        app.curve_route.set('analytic')
        assert _analyze(app, root) is not None
        app.show_antifunicular.set(True)

        captured = []
        original = CableWebApp._smooth_polyline

        def spy(points, samples_per_segment=12):
            out = original(points, samples_per_segment)
            captured.append(list(out))
            return out

        CableWebApp._smooth_polyline = staticmethod(spy)
        try:
            app._fit_view(); app._draw(); root.update()
        finally:
            CableWebApp._smooth_polyline = staticmethod(original)

        def bulge(pts):
            x0, y0 = pts[0]; x1, y1 = pts[-1]
            dx, dy = x1 - x0, y1 - y0
            den = dx * dx + dy * dy
            tot = 0.0
            for px, py in pts[1:-1]:
                t = (((px - x0) * dx + (py - y0) * dy) / den) if den > 1e-18 else 0.0
                tot += py - (y0 + t * dy)
            return tot

        groups = [g for g in captured if len(g) >= 5]
        assert groups, 'nothing was drawn'
        # screen y grows downward: a sagging cable bulges positive
        assert any(bulge(g) > 0 for g in groups), 'no sagging (funicular) curve'
        assert any(bulge(g) < 0 for g in groups), 'no arching (antifunicular) curve'
    finally:
        _teardown(root)


# --------------------------------------------------------------------------
# 6. exact tension at the anchorage
# --------------------------------------------------------------------------

def _closed_form_end_tension(span, arc, q):
    """T at the support of a cable hanging under a uniform load per unit ARC
    length, from closed form: a is the catenary parameter, H = q*a, the sag is
    a*(cosh(span/2a) - 1), and T = H + q*sag = q*a*cosh(span/2a)."""
    a = _catenary_a(span, arc)
    return q * a * math.cosh(span / (2.0 * a))


def test_end_tension_matches_closed_form_where_the_edge_value_does_not():
    """Peak tension lives at the support, and the diagram's per-edge value is
    the tension at that edge's MIDPOINT -- half an element short of the peak.

    Measured 2026-09-05 on a 20 m span / 22 m arc cable under 10 N/m: closed
    form 171.05 N, raw edge value 161.95 N (-5.3%), corrected end value
    170.48 N (-0.3%). For anyone sizing a cable the raw number is the
    unconservative one, which is why this correction exists.
    """
    pytest.importorskip('scipy.optimize')
    span, arc, q = 20.0, 22.0, 10.0
    exact = _closed_form_end_tension(span, arc, q)
    root, app = _make_app()
    try:
        _reset(app)
        a = app._new_node(*_m(0, 0), support=True)
        b = app._new_node(*_m(span, 0), support=True)
        c = app._new_cable(a['id'], b['id'])
        c['length_override'] = arc
        c['w'] = 0.0          # the closed form below is for q alone
        app.loads.append({'id': 'U', 'cable': c['id'], 'type': 'UDL',
                          's1': 0.0, 's2': arc, 'magnitude': q,
                          'direction': 'Vertical', 'angle_deg': -90.0,
                          'expression': ''})
        root.update()
        app.grade_mesh.set(False)
        assert _analyze(app, root) is not None

        series = app._diagram_series(c['id'])
        raw = max(r[2] for r in series)
        corrected = app._cable_end_tension(c['id'], True)
        assert corrected is not None, 'a plain uniform UDL must be corrected'

        raw_err = abs(raw - exact) / exact
        cor_err = abs(corrected - exact) / exact
        assert raw_err > 0.03, (
            'the raw edge value is suspiciously good (%.4f vs %.4f); this test '
            'no longer proves anything' % (raw, exact))
        assert cor_err < 0.01, (
            'corrected end tension %.4f N is not close to the closed form '
            '%.4f N (%.2f%%)' % (corrected, exact, 100 * cor_err))
        assert cor_err < raw_err / 5.0, (
            'correction barely helped: %.2f%% -> %.2f%%'
            % (100 * raw_err, 100 * cor_err))

        # both ends of a level, symmetrically loaded cable carry the same peak
        other = app._cable_end_tension(c['id'], False)
        assert other == pytest.approx(corrected, rel=1e-6)
    finally:
        _teardown(root)


def test_end_tension_is_mesh_independent():
    """The point of the correction, and the reason it belongs in the reporting
    layer rather than the mesh: a longer end element lowers the edge value by
    exactly what the correction adds back. So the graded mesh, which lengthens
    the elements at the supports and made the raw peak WORSE (sec 3x), cannot
    move the corrected one."""
    pytest.importorskip('scipy.optimize')
    span, arc, q = 20.0, 22.0, 10.0
    raw, corrected = {}, {}
    for grade in (False, True):
        root, app = _make_app()
        try:
            _reset(app)
            a = app._new_node(*_m(0, 0), support=True)
            b = app._new_node(*_m(span, 0), support=True)
            c = app._new_cable(a['id'], b['id'])
            c['length_override'] = arc
            c['w'] = 0.0          # the closed form below is for q alone
            app.loads.append({'id': 'U', 'cable': c['id'], 'type': 'UDL',
                              's1': 0.0, 's2': arc, 'magnitude': q,
                              'direction': 'Vertical', 'angle_deg': -90.0,
                              'expression': ''})
            root.update()
            app.curve_route.set('graded')
            app.grade_mesh.set(grade)
            assert _analyze(app, root) is not None
            raw[grade] = max(r[2] for r in app._diagram_series(c['id']))
            corrected[grade] = app._cable_end_tension(c['id'], True)
        finally:
            _teardown(root)
    assert corrected[False] and corrected[True]
    raw_shift = abs(raw[True] - raw[False]) / raw[False]
    cor_shift = abs(corrected[True] - corrected[False]) / corrected[False]
    assert raw_shift > 0.01, (
        'the raw peak did not move with the mesh, so this test proves nothing')
    assert cor_shift < 0.002, (
        'corrected end tension moved with the mesh: %.4f -> %.4f (%.3f%%)'
        % (corrected[False], corrected[True], 100 * cor_shift))


def test_end_tension_is_refused_when_the_load_is_not_uniform():
    """The half-element step is exact only for a uniform load per unit arc
    length. Where it is not, report the edge value rather than a confident
    wrong one."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        a = app._new_node(*_m(0, 0), support=True)
        b = app._new_node(*_m(20, 0), support=True)
        c = app._new_cable(a['id'], b['id'])
        c['length_override'] = 26.0
        c['w'] = 8.0
        app.loads.append({'id': 'V', 'cable': c['id'], 'type': 'Variable',
                          's1': 0.0, 's2': 26.0, 'magnitude': 10.0,
                          'direction': 'Vertical', 'angle_deg': -90.0,
                          'expression': 's'})
        root.update()
        assert _analyze(app, root) is not None
        assert app._cable_end_tension(c['id'], True) is None
    finally:
        _teardown(root)


def test_a_freshly_drawn_cable_can_be_analysed_with_the_default_self_weight():
    """Why the default is nonzero.

    A cable with neither self-weight nor an applied load has no unique
    equilibrium -- there is nothing to set its tension -- so before this it
    could not be analysed at all. Measured 2026-09-05: at w=0 a fresh cable
    FAILS at 5%, 10%, 30% and 100% slack; at the default every one converges.
    """
    pytest.importorskip('scipy.optimize')
    from common import DEFAULT_SELF_WEIGHT
    assert DEFAULT_SELF_WEIGHT > 0.0

    outcome = {}
    for w in (0.0, None):               # None = leave the shipped default
        root, app = _make_app()
        try:
            _reset(app)
            a = app._new_node(*_m(0, 0), support=True)
            b = app._new_node(*_m(20, 0), support=True)
            c = app._new_cable(a['id'], b['id'])
            c['length_override'] = 26.0
            if w is not None:
                c['w'] = w
            else:
                assert c['w'] == pytest.approx(DEFAULT_SELF_WEIGHT),                     'a new cable did not pick up the default self-weight'
            root.update()
            r = _analyze(app, root)
            outcome[w] = r is not None and r.converged
        finally:
            _teardown(root)
    assert outcome[None], 'a freshly drawn cable must be analysable as drawn'
    assert not outcome[0.0], (
        'a weightless unloaded cable now converges, so the default is no '
        'longer load-bearing -- re-check whether it is still wanted')


def test_both_built_in_examples_pin_their_own_self_weight():
    """Regression cases must not move when a UI default moves. Both examples
    were relying on _new_cable's 0.0 rather than stating it; the 2026-09-05
    report wrongly claimed one of them pinned it."""
    for loader in ('_load_example', '_load_picture_example'):
        root, app = _make_app()
        try:
            getattr(app, loader)()
            root.update()
            assert all(c['w'] == 0.0 for c in app.cables), (
                '%s: %r' % (loader, [c['w'] for c in app.cables]))
        finally:
            _teardown(root)


# --------------------------------------------------------------------------
# 7. equilibrium force vectors
# --------------------------------------------------------------------------

def _build_force_web(app):
    a = app._new_node(*_m(0, 0), support=True)
    b = app._new_node(*_m(20, 0), support=True)
    anch = app._new_node(*_m(6, 9), support=True)
    j = app._new_node(*_m(6, 0))
    c = app._new_cable(a['id'], b['id']); c['length_override'] = 24.0; c['w'] = 8.0
    t = app._new_cable(j['id'], anch['id']); t['length_override'] = 8.0; t['w'] = 8.0
    app._attach_node(j['id'], c['id'], 7.0)
    app.loads.append({'id': 'P', 'cable': c['id'], 'type': 'Point', 's1': 14.0,
                      's2': 14.0, 'magnitude': 250.0, 'direction': 'Vertical',
                      'angle_deg': -90.0, 'expression': ''})
    return c, t, j


def test_support_reactions_balance_everything_applied():
    """The property that makes the vectors worth drawing, asserted as a number
    rather than looked at: every reaction plus every applied load plus all the
    self-weight must sum to zero."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        _build_force_web(app)
        root.update()
        assert _analyze(app, root) is not None

        rx = ry = 0.0
        for x, y, arrows in app._force_vector_stations():
            for fx, fy, kind in arrows:
                if kind == 'R':
                    rx += fx
                    ry += fy

        model = app.result.model
        ax = ay = 0.0
        for n in model.nodes.values():
            ax += n.fx
            ay += n.fy
        for e in model.edges.values():
            ay -= abs(e.weight_per_length) * abs(e.target_length or 0.0)

        scale = max(abs(ay), 1.0)
        assert abs(rx + ax) < 1e-6 * scale, 'horizontal: %g vs %g' % (rx, -ax)
        assert abs(ry + ay) < 1e-6 * scale, 'vertical: %g vs %g' % (ry, -ay)
    finally:
        _teardown(root)


def test_the_selected_joint_is_in_equilibrium():
    """At a free junction the cable pulls plus any applied load must cancel.
    That set is exactly what the feature draws, so this checks the drawing's
    own data, not just the solver's."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        c, t, j = _build_force_web(app)
        root.update()
        assert _analyze(app, root) is not None
        app.selected_kind, app.selected_id = 'node', j['id']

        stations = app._force_vector_stations()
        joints = [st for st in stations
                  if any(k in ('T', 'P') for _, _, k in st[2])]
        assert len(joints) == 1, 'expected exactly the one selected joint'
        _x, _y, arrows = joints[0]
        assert len(arrows) >= 3, 'a junction of three cables should show three pulls'
        sx = sum(fx for fx, _fy, _k in arrows)
        sy = sum(fy for _fx, fy, _k in arrows)
        biggest = max(math.hypot(fx, fy) for fx, fy, _k in arrows)
        assert math.hypot(sx, sy) < 1e-6 * biggest, (
            'selected joint is not in equilibrium: residual %g against %g'
            % (math.hypot(sx, sy), biggest))
    finally:
        _teardown(root)


def test_force_vectors_are_off_by_default_and_draw_nothing_until_analyzed():
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        assert app.show_force_vectors.get() is False
        _reset(app)
        _build_force_web(app)
        root.update()
        assert app._force_vector_stations() == [], (
            'force vectors reported stations before any Analyze')
        app.show_force_vectors.set(True)
        app._draw()
        root.update()          # must not raise with no result
        assert _analyze(app, root) is not None
        app._draw()
        root.update()
        assert app._force_vector_stations(), 'nothing to draw after Analyze'
    finally:
        _teardown(root)


def test_force_vector_shafts_scale_with_zoom_but_heads_do_not():
    """The settled spec: the shaft is model geometry and magnifies with the
    structure; the head is a fixed pixel size because Tk's arrowshape is in
    pixels and a scaled head becomes grotesque."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        _build_force_web(app)
        root.update()
        assert _analyze(app, root) is not None
        app.show_force_vectors.set(True)

        def longest_shaft():
            got = []
            real = app.zc.canvas.create_line

            force_colours = {app.CFH, app.CFV, app.CFR, CT, CL, CZ}

            def spy(*args, **kw):
                # Only the force vectors -- load arrows are drawn with
                # arrow='last' too and are not what this measures.
                if (kw.get('arrowshape') is not None
                        and kw.get('fill') in force_colours and len(args) >= 4):
                    got.append(math.hypot(args[2] - args[0], args[3] - args[1]))
                return real(*args, **kw)

            app.zc.canvas.create_line = spy
            try:
                app._draw(); root.update()      # NOT _fit_view: it resets zoom
            finally:
                app.zc.canvas.create_line = real
            return max(got) if got else 0.0

        app._fit_view(); root.update()
        base = longest_shaft()
        assert base > 0.0
        app.zc.zoom *= 3.0
        zoomed = longest_shaft()
        assert zoomed > base * 2.5, (
            'shaft did not scale with zoom: %.1f -> %.1f px' % (base, zoomed))
    finally:
        _teardown(root)


# --------------------------------------------------------------------------
# 8. web-wide T / H / V drawn into the geometry
# --------------------------------------------------------------------------

def _capture_web_bands(app, root, open_pane=True):
    """Band widths, in screen px, from the FUNICULAR DIAGRAM pane.

    The quad is [p0, p1, p1+off, p0+off], so the width is the gap between the
    two long sides. The pane must be packed AND laid out before it is drawn --
    an unmapped canvas reports width 1 and the renderer bails.
    """
    if open_pane:
        app.show_web_diagrams.set(True)
        app._sync_funicular_pane()
        root.update()

    got = []
    real = app.fd_canvas.create_polygon

    def spy(*args, **kw):
        # The band is a ribbon [curve..., reversed(outer)...], so its width at
        # a station is the gap between point i and its partner from the other
        # end. It used to be a 4-point quad per edge; it now follows the whole
        # drawn curve, which is the point of the fix.
        if kw.get('stipple') and len(args) >= 8 and len(args) % 4 == 0:
            n = len(args) // 4
            for i in range(n):
                ax, ay = args[2 * i], args[2 * i + 1]
                bx, by = args[len(args) - 2 * i - 2], args[len(args) - 2 * i - 1]
                got.append(math.hypot(bx - ax, by - ay))
        return real(*args, **kw)

    app.fd_canvas.create_polygon = spy
    try:
        app._draw_funicular_diagram()
        root.update()
    finally:
        app.fd_canvas.create_polygon = real
    return got


def test_web_diagram_is_off_by_default_and_draws_nothing_before_analyze():
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        assert app.show_web_diagrams.get() is False
        assert app.web_diagram_q.get() == 'T'
        assert app.fd_flip.get() is False
        assert app.fd_scale.get() == 100
        assert not app.fd_outer.winfo_ismapped(), 'pane is open by default'
        _reset(app)
        _build_force_web(app)
        root.update()
        assert _capture_web_bands(app, root) == [], (
            'bands were drawn before any Analyze')
    finally:
        _teardown(root)


def test_funicular_pane_opens_and_closes_with_its_toggle():
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        _build_force_web(app)
        root.update()
        assert _analyze(app, root) is not None
        app.show_web_diagrams.set(True)
        app._sync_funicular_pane()
        root.update()
        assert app.fd_outer.winfo_ismapped(), 'pane did not open'
        app.show_web_diagrams.set(False)
        app._sync_funicular_pane()
        root.update()
        assert not app.fd_outer.winfo_ismapped(), 'pane did not close'
    finally:
        _teardown(root)


def test_funicular_pane_leaves_the_editing_canvas_alone():
    """The diagram belongs in its own panel. Opening it must not add anything
    to the canvas you build the model on -- that was the whole point of moving
    it out of there."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        _build_force_web(app)
        root.update()
        assert _analyze(app, root) is not None
        app.show_web_diagrams.set(True)
        app._sync_funicular_pane()
        root.update()

        # Count band quads landing on the EDITING canvas -- the item total is
        # not the test, because opening the pane takes canvas height and so
        # legitimately changes how many grid lines are drawn.
        bands = []
        real = app.zc.canvas.create_polygon

        def spy(*args, **kw):
            if kw.get('stipple') and len(args) == 8:
                bands.append(args)
            return real(*args, **kw)

        app.zc.canvas.create_polygon = spy
        try:
            app._fit_view(); app._draw(); root.update()
        finally:
            app.zc.canvas.create_polygon = real
        assert bands == [], (
            '%d diagram bands were painted onto the editing canvas' % len(bands))
    finally:
        _teardown(root)


def test_funicular_pane_flip_mirrors_the_geometry():
    """The flip reads the same solved forces as the compression arch the cable
    is dual to. The diagram values must not change -- only the shape."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        _build_cable(app, 20.0, 26.0, w=10.0)
        root.update()
        assert _analyze(app, root) is not None

        def sag_sign():
            pos = app.result.positions
            if app.fd_flip.get():
                ys = [p[1] for p in pos.values()]
                pos = app.result.inverted_positions(max(ys) if ys else 0.0)
            ys = [p[1] for p in pos.values()]
            mid = 0.5 * (max(ys) + min(ys))
            return 1 if sum(1 for y in ys if y < mid) > len(ys) / 2 else -1

        app.fd_flip.set(False)
        down = sag_sign()
        vals_down = app._web_diagram_rows(app.result.positions, 2)[1]
        app.fd_flip.set(True)
        up = sag_sign()
        assert down != up, 'flipping did not mirror the geometry'

        ys = [p[1] for p in app.result.positions.values()]
        inv = app.result.inverted_positions(max(ys) if ys else 0.0)
        vals_up = app._web_diagram_rows(inv, 2)[1]
        assert vals_up == pytest.approx(vals_down, rel=1e-9), (
            'flipping changed the tensions; it must only change the shape')

        bands = _capture_web_bands(app, root)
        assert bands, 'nothing drawn in the flipped view'
    finally:
        _teardown(root)


def test_funicular_pane_scale_slider_changes_band_width():
    """A scale control has to visibly scale. The view is fitted to the
    geometry plus a FIXED allowance rather than to the bands, so the structure
    holds still and the band grows against it -- fitting to the bands would
    shrink the view by exactly as much as the band grew and the slider would
    look inert."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        _build_cable(app, 20.0, 26.0, w=10.0)
        root.update()
        assert _analyze(app, root) is not None

        app.fd_scale.set(100)
        base = _capture_web_bands(app, root)
        app.fd_scale.set(200)
        wide = _capture_web_bands(app, root, open_pane=False)
        assert base and wide
        ratio = max(wide) / max(base)
        assert ratio == pytest.approx(2.0, rel=0.05), (
            'doubling the scale did not double the band: ratio %.3f' % ratio)
    finally:
        _teardown(root)


def test_web_diagram_uses_one_scale_across_every_cable():
    """Per-cable scaling would draw a light tie's band as wide as a heavily
    loaded main span, which destroys the comparison the drawing exists to
    make. So the widest band anywhere must correspond to the largest value
    anywhere, and the ratio of band widths must match the ratio of values.
    """
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        c, t, j = _build_force_web(app)
        root.update()
        assert _analyze(app, root) is not None
        app.show_web_diagrams.set(True)
        app.web_diagram_q.set('T')

        widths = _capture_web_bands(app, root)
        assert widths, 'nothing drawn'

        vals = []
        for cid in (c['id'], t['id']):
            vals += [r[2] for r in app._diagram_series(cid)]
        assert vals

        # one scale: widest band / narrowest band == largest T / smallest T
        wr = max(widths) / max(min(widths), 1e-9)
        vr = max(vals) / max(min(vals), 1e-9)
        assert wr == pytest.approx(vr, rel=0.02), (
            'band widths are not on a single shared scale: width ratio %.3f '
            'vs value ratio %.3f' % (wr, vr))
    finally:
        _teardown(root)


def test_web_diagram_h_band_is_even_along_a_vertically_loaded_cable():
    """A free correctness check the drawing gives away: under purely vertical
    load the horizontal thrust is constant along a cable, so its band must
    come out an even ribbon. If it visibly tapers, the solve is wrong."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        _build_cable(app, 20.0, 26.0, w=10.0)
        root.update()
        assert _analyze(app, root) is not None
        app.show_web_diagrams.set(True)
        app.web_diagram_q.set('H')
        widths = _capture_web_bands(app, root)
        assert widths
        spread = (max(widths) - min(widths)) / max(widths)
        assert spread < 0.01, (
            'H band is not even along a vertically loaded cable: %.2f%% spread'
            % (100 * spread))
    finally:
        _teardown(root)


def test_web_diagram_quantity_switch_changes_what_is_drawn():
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        _build_cable(app, 20.0, 26.0, w=10.0)
        root.update()
        assert _analyze(app, root) is not None
        app.show_web_diagrams.set(True)
        seen = {}
        for q in ('T', 'H', 'V'):
            app.web_diagram_q.set(q)
            seen[q] = _capture_web_bands(app, root)
            assert seen[q], '%s drew nothing' % q
        # V is zero at the low point and greatest at the ends; T and H are not
        assert min(seen['V']) < 0.5 * max(seen['V'])
        assert min(seen['H']) > 0.99 * max(seen['H'])
    finally:
        _teardown(root)


# --------------------------------------------------------------------------
# 9. the two views must agree (found by audit, 2026-09-05)
# --------------------------------------------------------------------------

def _pane_curves_model(app, flip=False):
    """Exactly the geometry the funicular pane draws, in model coordinates."""
    positions = app.result.positions
    axis = None
    if flip:
        ys = [p[1] for p in positions.values()]
        axis = max(ys) if ys else 0.0
        positions = app.result.inverted_positions(axis)
    out = []
    for g in app._display_groups(app.result, positions, app._solver_meta,
                                 view='A' if flip else 'F', mirror_axis=axis):
        pts = g['pts']
        if len(pts) < 2:
            continue
        if len(pts) >= 3:
            pts = app._smooth_polyline(
                pts, samples_per_segment=1 if g['analytic'] else 10)
        out.append(list(pts))
    return out


def _canvas_curves_model(app, root):
    """The funicular as DRAWN on the editing canvas, back in model metres."""
    got = []
    original = CableWebApp._smooth_polyline

    def spy(points, samples_per_segment=12):
        out = original(points, samples_per_segment)
        got.append(list(out))
        return out

    CableWebApp._smooth_polyline = staticmethod(spy)
    try:
        app._fit_view(); app._draw(); root.update()
    finally:
        CableWebApp._smooth_polyline = staticmethod(original)
    out = []
    for grp in got:
        if len(grp) < 2:
            continue
        out.append([app._world_to_m(*app.zc.s2w(sx, sy)) for sx, sy in grp])
    return out


def _gap_between(a_groups, b_groups):
    worst = 0.0
    for grp in a_groups:
        for px, py in grp:
            best = float('inf')
            for poly in b_groups:
                for i in range(len(poly) - 1):
                    ax, ay = poly[i]; bx, by = poly[i + 1]
                    vx, vy = bx - ax, by - ay
                    L2 = vx * vx + vy * vy
                    t = 0.0 if L2 < 1e-18 else ((px - ax) * vx + (py - ay) * vy) / L2
                    t = max(0.0, min(1.0, t))
                    best = min(best, math.hypot(px - (ax + t * vx),
                                                py - (ay + t * vy)))
            worst = max(worst, best)
    return worst


@pytest.mark.parametrize('route', ['analytic', 'graded'])
def test_the_pane_and_the_canvas_draw_the_same_curve(route):
    """The bug the user found. The editing canvas and the funicular pane were
    two independently written renderers of one solve, and they disagreed: on
    the built-in Picture test by 4.2 m, 13.8% of the web, because the pane
    plotted the raw solver polygon while the canvas plotted the analytic
    curve, the zero-tension substitute and the inserted vertex.

    Both now go through `_display_groups`, so this asserts they agree exactly
    rather than approximately -- an approximate assertion would let the two
    drift apart again by small steps.
    """
    pytest.importorskip('scipy.optimize')
    for loader in ('_load_example', '_load_picture_example'):
        root, app = _make_app()
        try:
            app.curve_route.set(route)
            app.grade_mesh.set(route == 'graded')
            getattr(app, loader)()
            root.update()
            assert _analyze(app, root) is not None
            gap = _gap_between(_canvas_curves_model(app, root),
                               _pane_curves_model(app))
            assert gap < 1e-9, (
                '%s/%s: canvas and pane disagree by %.4f m' % (loader, route, gap))
        finally:
            _teardown(root)


def test_zero_tension_shape_is_not_shared_between_the_two_views():
    """A slack, unloaded stretch has its arbitrary interior replaced by a
    nominal catenary, and that substitute was cached WITHOUT a view key -- so
    whichever of the funicular and antifunicular drew first won, and the other
    rendered its neighbour's shape. Measured 210-273 px out of place on the
    Picture test's mirrored view. Predates the pane.

    The mirrored substitute must be the MIRROR of the upright one, not a copy
    of it.
    """
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        app._load_picture_example()
        root.update()
        assert _analyze(app, root) is not None

        ys = [p[1] for p in app.result.positions.values()]
        axis = max(ys) if ys else 0.0
        inv = app.result.inverted_positions(axis)

        up = {tuple(g['eids']): list(g['pts']) for g in app._display_groups(
            app.result, app.result.positions, app._solver_meta, view='F')}
        down = {tuple(g['eids']): list(g['pts']) for g in app._display_groups(
            app.result, inv, app._solver_meta, view='A', mirror_axis=axis)}
        assert up and down and set(up) == set(down)

        checked = 0
        for key, upts in up.items():
            dpts = down[key]
            if len(upts) != len(dpts):
                continue
            # every drawn point must satisfy y_down == 2*axis - y_up
            worst = max(abs(d[1] - (2 * axis - u[1])) + abs(d[0] - u[0])
                        for u, d in zip(upts, dpts))
            assert worst < 1e-9, (
                'group %s is not the mirror of its funicular self: %.4f m off'
                % (key, worst))
            checked += 1
        assert checked, 'no comparable groups; the test checked nothing'
    finally:
        _teardown(root)


# --------------------------------------------------------------------------
# 10. slack members -- the complementarity stage (audit F4, 2026-09-05)
# --------------------------------------------------------------------------

def _build_star(app):
    """Three cables at one free junction, the third anchored BELOW it."""
    s1 = app._new_node(*_m(0, 8), support=True)
    s2 = app._new_node(*_m(14, 8), support=True)
    s3 = app._new_node(*_m(7, -6), support=True)
    j = app._new_node(*_m(7, 2))
    for s, L in ((s1, 10.0), (s2, 10.0), (s3, 9.0)):
        c = app._new_cable(s['id'], j['id'])
        c['length_override'] = L
        c['w'] = 6.0
    return j


def _build_tied_down(app):
    """A junction attached mid-cable and tied DOWN to an anchor beneath it."""
    a = app._new_node(*_m(0, 0), support=True)
    b = app._new_node(*_m(20, 0), support=True)
    anc = app._new_node(*_m(8, -7), support=True)
    j = app._new_node(*_m(8, 0))
    ca = app._new_cable(a['id'], b['id'])
    ca['length_override'] = 24.0
    ca['w'] = 8.0
    ct = app._new_cable(j['id'], anc['id'])
    ct['length_override'] = 7.0
    ct['w'] = 8.0
    app._attach_node(j['id'], ca['id'], 10.0)
    app.loads.append({'id': 'U', 'cable': ca['id'], 'type': 'UDL',
                      's1': 0.0, 's2': 20.0, 'magnitude': 10.0,
                      'direction': 'Vertical', 'angle_deg': -90.0,
                      'expression': ''})
    return j


def _cable_law_violations(result):
    """(worst overstretch, worst complementarity product) in model units.

    A cable may not be longer than its own length, may not push, and may not
    be both slack AND tensioned. Those three ARE the constitutive law.
    """
    over = 0.0
    comp = 0.0
    neg = 0.0
    for eid, e in result.model.edges.items():
        T = result.tensions.get(eid)
        if T is None or e.i not in result.positions or e.j not in result.positions:
            continue
        xi, yi = result.positions[e.i]
        xj, yj = result.positions[e.j]
        L = math.hypot(xj - xi, yj - yi)
        over = max(over, L - e.target_length)
        neg = min(neg, T)
        comp = max(comp, T * max(0.0, e.target_length - L))
    return over, comp, neg


@pytest.mark.parametrize('name,build', [('three-cable star', _build_star),
                                        ('junction tied down', _build_tied_down)])
def test_a_network_with_a_slack_member_converges(name, build):
    """Audit finding F4. Every solver stage but the last imposes
    L == target_length as an EQUALITY on every edge. That is right for a taut
    member and wrong for a slack one -- a cable carries no compression, so a
    member with more length than the gap it spans must be free to sit at
    L < target with T = 0. Such a model had NO solution as posed.

    Both of these had never converged, on any code version: the solver drove
    exactly one edge to T ~ 1e-28 with L a few millimetres under its target --
    the correct slack state -- and stalled at residual 1e-2 because the
    equality could not accept it.
    """
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        build(app)
        root.update()
        r = _analyze(app, root)
        assert r is not None and r.converged, (
            '%s did not converge: %s' % (name, app.validation_var.get()))
        assert r.residual < 1e-6, '%s residual %.2e' % (name, r.residual)

        over, comp, neg = _cable_law_violations(r)
        scale = max(e.target_length for e in r.model.edges.values())
        assert over < 1e-6 * scale, '%s: a member is stretched %.4g m past its length' % (name, over)
        assert neg > -1e-6, '%s: a member is in compression (T = %.4g)' % (name, neg)
        tmax = max((t for t in r.tensions.values() if t is not None), default=0.0)
        assert comp < 1e-6 * max(tmax, 1.0) * scale, (
            '%s: a member is both slack and tensioned (T*slack = %.4g)' % (name, comp))
    finally:
        _teardown(root)


@pytest.mark.parametrize('name,build', [('three-cable star', _build_star),
                                        ('junction tied down', _build_tied_down)])
def test_a_slack_solution_is_still_in_equilibrium(name, build):
    """Converging is not the claim -- being right is. Every reaction plus
    every applied load plus all the self-weight must still sum to zero."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        build(app)
        root.update()
        assert _analyze(app, root) is not None

        rx = ry = 0.0
        for _x, _y, arrows in app._force_vector_stations():
            for fx, fy, kind in arrows:
                if kind == 'R':
                    rx += fx
                    ry += fy
        model = app.result.model
        ax = ay = 0.0
        for n in model.nodes.values():
            ax += n.fx
            ay += n.fy
        for e in model.edges.values():
            ay -= abs(e.weight_per_length) * abs(e.target_length or 0.0)
        scale = max(abs(ay), abs(ax), 1.0)
        assert abs(rx + ax) < 1e-6 * scale, '%s horizontal: %g' % (name, rx + ax)
        assert abs(ry + ay) < 1e-6 * scale, '%s vertical: %g' % (name, ry + ay)
    finally:
        _teardown(root)


def test_an_all_slack_network_is_still_reported_as_unsolved():
    """The complementarity system is satisfied trivially when every member is
    slack: nothing is carried, so every configuration with L <= target is an
    equilibrium and the shape is arbitrary. That is the absence of a
    constraint, not a solution, and reporting it as converged would hand back
    a meaningless geometry with a 1e-13 residual attached.

    This is also why a nonzero default self-weight is load-bearing --
    see test_a_freshly_drawn_cable_can_be_analysed_with_the_default_self_weight.
    """
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        a = app._new_node(*_m(0, 0), support=True)
        b = app._new_node(*_m(20, 0), support=True)
        c = app._new_cable(a['id'], b['id'])
        c['length_override'] = 26.0
        c['w'] = 0.0                      # nothing applied anywhere
        root.update()
        r = _analyze(app, root)
        assert r is None or not r.converged, (
            'an unloaded weightless network reported a definite shape')
    finally:
        _teardown(root)


def test_an_impossible_model_says_so_instead_of_blaming_the_solver():
    """A junction cabled to several supports must lie within each cable's own
    length of its support. When those discs do not intersect, no configuration
    exists for any solver, and "did not converge" sends the user hunting for a
    numerical problem that is not there.

    Here two 10 m suspension cables need the junction at y >= 0.86 while a 6 m
    tie needs y <= 0 -- flatly contradictory.
    """
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        _reset(app)
        s1 = app._new_node(*_m(0, 8), support=True)
        s2 = app._new_node(*_m(14, 8), support=True)
        s3 = app._new_node(*_m(7, -6), support=True)
        j = app._new_node(*_m(7, 2))
        for sup, L in ((s1, 10.0), (s2, 10.0), (s3, 6.0)):
            c = app._new_cable(sup['id'], j['id'])
            c['length_override'] = L
            c['w'] = 6.0
        root.update()
        note = app._unreachable_junction_note()
        assert note, 'an impossible model was not identified as impossible'
        assert 'cannot be reached' in note

        _analyze(app, root)
        assert 'cannot be reached' in app.status_var.get(), (
            'the failure message does not say why: %r' % app.status_var.get())
    finally:
        _teardown(root)


def test_a_solvable_model_is_never_called_impossible():
    """The check must be a necessary condition only -- it looks at cables
    running straight from a junction to a support and nothing else, so it can
    never cry wolf about a web it has not fully accounted for."""
    pytest.importorskip('scipy.optimize')
    for build in (_build_star, _build_tied_down, _build_force_web):
        root, app = _make_app()
        try:
            _reset(app)
            build(app)
            root.update()
            assert app._unreachable_junction_note() == '', (
                '%s was wrongly called impossible' % build.__name__)
        finally:
            _teardown(root)


# --------------------------------------------------------------------------
# 11. smooth (closed-form) diagrams
# --------------------------------------------------------------------------
#
# These deliberately need NO solver. A synthetic result whose nodes sit on an
# EXACT catenary, with the exact tension at each edge midpoint, is a stronger
# input than a solved one: a solved case carries discretisation error, so
# agreement to 1e-9 would be impossible and any disagreement ambiguous. Here
# the input is exact, so the identities must come out exact -- and they run on
# a machine where SciPy cannot load.

_SM_SPAN, _SM_ARC, _SM_Q = 20.0, 22.0, 10.0


def _exact_catenary_result(app, nseg=None):
    """Give `app` a synthetic result lying on an exact catenary.

    Returns (cid, a, sag, H_exact, T_support_exact).
    """
    _reset(app)
    a_node = app._new_node(*_m(0, 0), support=True)
    b_node = app._new_node(*_m(_SM_SPAN, 0), support=True)
    c = app._new_cable(a_node['id'], b_node['id'])
    c['length_override'] = _SM_ARC
    c['w'] = _SM_Q

    A = _catenary_a(_SM_SPAN, _SM_ARC)
    sag = A * (math.cosh(_SM_SPAN / (2.0 * A)) - 1.0)

    def point_at(sv):
        u = sv - _SM_ARC / 2.0
        return (_SM_SPAN / 2.0 + A * math.asinh(u / A),
                -sag + A * (math.sqrt(1.0 + (u / A) ** 2) - 1.0))

    model, seg_owner = app._build_solver_model()
    meta = app._solver_meta
    cid = c['id']
    positions = {nid: point_at(sv) for nid, sv in
                 zip(meta['cable_solver_nodes'][cid], meta['cable_bp'][cid])}
    tensions = {}
    for eid, owner in seg_owner.items():
        if owner[0] != cid:
            continue
        u_mid = 0.5 * (owner[1] + owner[2]) - _SM_ARC / 2.0
        tensions[eid] = _SM_Q * math.hypot(A, u_mid)
    app.result = CableWebResult(model, positions, tensions, True, 0.0)
    app.result_kind = 'analysis'
    app.results_current = True
    app._result_serial = 1
    return (cid, A, sag, _SM_Q * A,
            _SM_Q * A * math.cosh(_SM_SPAN / (2.0 * A)))


def test_smooth_diagram_is_off_by_default():
    """The stepped band is what the solve literally produced, so it stays the
    default -- the toggle exists to add a reading, not to replace one."""
    root, app = _make_app()
    try:
        assert app.diagram_smooth.get() is False
    finally:
        _teardown(root)


def test_smooth_diagram_satisfies_the_statics_exactly():
    """The identities the closed form rests on, at the shipped mesh.

    Under vertical load H is constant along a cable and V varies linearly with
    arc length at the rate of the applied load, so on a symmetric span V is
    zero at the vertex, T there equals H, and V at each anchorage is half the
    total weight. None of those can be read off a stepped band, which only
    ever samples edge midpoints.
    """
    root, app = _make_app()
    try:
        cid, A, sag, H_exact, T_support = _exact_catenary_result(app)
        seg_owner = app._solver_meta['seg_owner']
        eids = [eid for eid, o in seg_owner.items() if o[0] == cid]
        params = app._analytic_group_params(cid, eids, 0.0, _SM_ARC,
                                            app.result.positions, seg_owner)
        assert params is not None, 'a uniformly loaded cable was refused'
        H, v0, q = params
        val = app._analytic_diagram_value

        assert q == pytest.approx(_SM_Q, abs=1e-12)
        assert v0 == pytest.approx(-_SM_Q * _SM_ARC / 2.0, abs=1e-9)
        assert val(4, H, v0, q, _SM_ARC / 2.0) == pytest.approx(0.0, abs=1e-9), \
            'V is not zero at the vertex'
        assert val(2, H, v0, q, _SM_ARC / 2.0) == pytest.approx(H, abs=1e-12), \
            'T at the vertex must equal H'
        assert val(4, H, v0, q, 0.0) == pytest.approx(_SM_Q * _SM_ARC / 2.0, abs=1e-9), \
            'V at the anchorage must be half the total weight'
        assert val(3, H, v0, q, 3.7) == pytest.approx(val(3, H, v0, q, 17.3), abs=1e-12), \
            'H must be constant along the cable'
        assert val(2, H, v0, q, 4.1) == pytest.approx(math.hypot(H, v0 + q * 4.1), abs=1e-12)
    finally:
        _teardown(root)


def test_smooth_diagram_reaches_a_peak_the_steps_cannot():
    """The reason this matters for sizing a cable. An edge's value is the true
    value at its MIDPOINT, so the stepped band's highest step is always short
    of the real peak at the anchorage. Measured on a 20 m / 22 m cable at
    10 N/m against the closed form q*a*cosh(span/2a): stepped -4.97%, smooth
    +0.03%.
    """
    root, app = _make_app()
    try:
        cid, A, sag, H_exact, T_support = _exact_catenary_result(app)
        seg_owner = app._solver_meta['seg_owner']
        eids = [eid for eid, o in seg_owner.items() if o[0] == cid]
        H, v0, q = app._analytic_group_params(cid, eids, 0.0, _SM_ARC,
                                              app.result.positions, seg_owner)

        stepped_peak = max(app.result.tensions.values())
        smooth_peak = app._analytic_diagram_value(2, H, v0, q, 0.0)
        stepped_err = abs(stepped_peak - T_support) / T_support
        smooth_err = abs(smooth_peak - T_support) / T_support

        assert stepped_err > 0.02, (
            'the stepped peak is suspiciously good (%.4f vs %.4f); this test '
            'no longer proves anything' % (stepped_peak, T_support))
        assert smooth_err < 0.002, (
            'smooth peak %.4f N is not close to the closed form %.4f N'
            % (smooth_peak, T_support))
        assert smooth_err < stepped_err / 10.0
    finally:
        _teardown(root)


def test_smooth_diagram_curve_matches_its_own_closed_form():
    """The drawing path, not just the formula: every point _diagram_curve
    emits must be the closed form evaluated there, and the points must run in
    order of s."""
    root, app = _make_app()
    try:
        cid, A, sag, H_exact, T_support = _exact_catenary_result(app)
        seg_owner = app._solver_meta['seg_owner']
        eids = [eid for eid, o in seg_owner.items() if o[0] == cid]
        params = app._analytic_group_params(cid, eids, 0.0, _SM_ARC,
                                            app.result.positions, seg_owner)
        for idx in (2, 3, 4):
            curve = app._diagram_curve(cid, idx)
            assert curve, 'no curve for idx %d' % idx
            ss = [p[0] for p in curve]
            assert all(ss[i] <= ss[i + 1] + 1e-12 for i in range(len(ss) - 1)), \
                'curve %d is not ordered along s' % idx
            worst = max(abs(v - app._analytic_diagram_value(idx, *params, sv))
                        for sv, v in curve)
            assert worst < 1e-9, 'curve %d departs from the closed form by %g' % (idx, worst)
    finally:
        _teardown(root)


def test_smooth_diagram_falls_back_where_the_load_is_not_uniform():
    """No closed form, no smooth curve. A variable load has no uniform q, so
    that stretch keeps its per-edge steps -- the picture must never claim
    resolution the solve does not have there."""
    root, app = _make_app()
    try:
        cid, A, sag, H_exact, T_support = _exact_catenary_result(app)
        app.loads.append({'id': 'V1', 'cable': cid, 'type': 'Variable',
                          's1': 0.0, 's2': _SM_ARC, 'magnitude': 5.0,
                          'direction': 'Vertical', 'angle_deg': -90.0,
                          'expression': 's'})
        seg_owner = app._solver_meta['seg_owner']
        eids = [eid for eid, o in seg_owner.items() if o[0] == cid]
        assert app._analytic_group_params(cid, eids, 0.0, _SM_ARC,
                                          app.result.positions, seg_owner) is None, \
            'a variable load was accepted by the closed form'

        curve = app._diagram_curve(cid, 2)
        assert curve, 'the fallback drew nothing at all'
        # a stepped run repeats each value at both ends of its edge
        vals = [v for _s, v in curve]
        assert any(abs(vals[i] - vals[i + 1]) < 1e-12 for i in range(len(vals) - 1)), \
            'the fallback does not look stepped'
    finally:
        _teardown(root)


def test_stepped_diagram_data_is_unchanged():
    """_diagram_series is the measured path and must be exactly what it was."""
    root, app = _make_app()
    try:
        cid, A, sag, H_exact, T_support = _exact_catenary_result(app)
        series = app._diagram_series(cid)
        assert series, 'no series'
        for _s0, _s1, T, H, V in series:
            assert math.hypot(H, V) == pytest.approx(T, rel=1e-12)
    finally:
        _teardown(root)


# --------------------------------------------------------------------------
# 12. the smooth diagram on a REAL solve
# --------------------------------------------------------------------------
#
# Section 11 feeds the diagram code an exact catenary, which pins down the
# formulae but says nothing about what the app actually shows after a solve.
# These two run solve_analysis and measure against q*a*cosh(span/2a), the
# number an engineer would size the cable with.

_SM_REAL_CASES = [
    # (label, span, arc, q) -- measured stepped error at the shipped mesh
    ('20 m span, 22 m arc   (stepped -5.3%)', 20.0, 22.0, 10.0),
    ('20 m span, 26 m arc   (stepped -9.2%)', 20.0, 26.0, 10.0),
    ('30 m span, 31 m arc   (stepped -2.7%)', 30.0, 31.0, 25.0),
    ('12 m span, 18 m arc  (stepped -10.6%)', 12.0, 18.0, 4.0),
]


def _solved_cable(app, root, span, arc, q):
    """Solve one uniformly loaded cable; return (cid, eids, params, result)."""
    _reset(app)
    c = _build_cable(app, span, arc, w=q)
    res = _analyze(app, root)
    assert res is not None and res.converged, 'the solve did not converge'
    cid = c['id']
    seg_owner = app._solver_meta['seg_owner']
    eids = [eid for eid, o in seg_owner.items() if o[0] == cid]
    params = app._analytic_group_params(cid, eids, 0.0, arc,
                                        res.positions, seg_owner)
    assert params is not None, 'a uniformly loaded cable was refused'
    return cid, eids, params, res


@pytest.mark.parametrize('label,span,arc,q', _SM_REAL_CASES,
                         ids=[c[0].split('(')[0].strip() for c in _SM_REAL_CASES])
def test_smooth_peak_beats_the_stepped_peak_on_a_real_solve(label, span, arc, q):
    """Peak tension is at the anchorage, which is the one place no edge
    midpoint ever lands, so the stepped band always under-reports it -- and
    under-reporting is the dangerous direction for sizing. Measured against
    the closed form, smooth is within a fraction of a percent where stepped is
    off by 2.7% to 10.6%, and it is low in every case, never high.
    """
    pytest.importorskip('scipy.optimize')
    root, app = _make_app()
    try:
        cid, eids, params, res = _solved_cable(app, root, span, arc, q)
        a = _catenary_a(span, arc)
        t_exact = q * a * math.cosh(span / (2.0 * a))

        stepped = max(res.tensions[e] for e in eids)
        smooth = app._analytic_diagram_value(2, *params, 0.0)
        e_step = abs(stepped - t_exact) / t_exact
        e_smooth = abs(smooth - t_exact) / t_exact

        assert stepped < t_exact, (
            'the stepped peak is no longer low; trapezoidal lumping should '
            'always under-report the anchorage')
        assert e_smooth < 0.01, (
            'smooth peak %.4f N is %.3f%% from the closed form %.4f N'
            % (smooth, 100 * e_smooth, t_exact))
        assert e_smooth < e_step / 4.0, (
            'smooth (%.3f%%) is not clearly better than stepped (%.3f%%)'
            % (100 * e_smooth, 100 * e_step))
    finally:
        _teardown(root)


def test_smooth_peak_converges_at_second_order_and_stepped_at_first():
    """The finding that makes this more than a drawing choice.

    The smooth reading is recovered from edge CHORDS, so it carries the mesh's
    own discretisation error -- which is why it lands near, not on, the closed
    form. Refining decides where that error lives. Measured on a 30 m / 31 m
    cable at 25 N/m, error ratios per doubling: smooth 4.01, 4.00, 4.00
    (second order); stepped 2.20, 2.10, 2.05 (first). Refining the mesh
    therefore buys four times as much from the smooth reading as from the
    stepped one.

    Asserted as a RATE, not a value: the value cannot equal the continuum's,
    and demanding that it should is what made the first version of this test
    wrong.
    """
    pytest.importorskip('scipy.optimize')
    span, arc, q = 30.0, 31.0, 25.0
    a = _catenary_a(span, arc)
    t_exact = q * a * math.cosh(span / (2.0 * a))

    root, app = _make_app()
    try:
        smooth_err, stepped_err = [], []
        for n in (8, 16, 32):
            _reset(app)
            app._graded_bp = {}
            c = _build_cable(app, span, arc, w=q)
            # Force an exactly uniform mesh of n edges: _solver_breakpoints
            # hands back a stored graded mesh verbatim when one exists, which
            # is the only seam here that does not need the solver touched.
            app._graded_bp[c['id']] = [arc * k / n for k in range(n + 1)]
            res = _analyze(app, root)
            assert res is not None and res.converged, 'n=%d did not converge' % n
            cid = c['id']
            seg_owner = app._solver_meta['seg_owner']
            eids = [eid for eid, o in seg_owner.items() if o[0] == cid]
            assert len(eids) == n, 'the forced mesh did not take (%d edges)' % len(eids)
            params = app._analytic_group_params(cid, eids, 0.0, arc,
                                                res.positions, seg_owner)
            assert params is not None
            smooth_err.append(abs(app._analytic_diagram_value(2, *params, 0.0)
                                  - t_exact) / t_exact)
            stepped_err.append(abs(max(res.tensions[e] for e in eids)
                                   - t_exact) / t_exact)

        for i in range(len(smooth_err) - 1):
            r = smooth_err[i] / smooth_err[i + 1]
            assert 3.4 < r < 4.6, (
                'smooth is not second order between %d and %d edges (%.2fx)'
                % (2 ** (i + 3), 2 ** (i + 4), r))
        for i in range(len(stepped_err) - 1):
            r = stepped_err[i] / stepped_err[i + 1]
            assert r < 2.6, (
                'stepped improved faster than first order (%.2fx); if the '
                'lumping changed, this comparison needs rewriting' % r)
    finally:
        _teardown(root)
