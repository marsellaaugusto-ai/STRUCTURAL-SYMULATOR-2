"""
test_cable_web_ui_reference_shape.py -- UI-level check for the cable_web
at-rest ("At-rest shape") rendering added 2026-08-28.

This intentionally lives in its own file rather than inside
test_cable_web_math.py: that file is explicitly scoped to cable_web_math.py
(the solver engine, tested headless, no Tk) per its own docstring, whereas
the logic here -- _update_reference_result(), _reference_segments,
_solve_nominal_catenary -- lives entirely in the UI layer
(apps/cable_web/cable_web_app.py) and requires a real Tk display (or a
virtual one, e.g. Xvfb) to instantiate CableWebApp at all. Each test skips
itself (rather than erroring) if no display is available, so a normal
`pytest` run stays green in a headless environment -- only the two
pre-existing math-only test files are load-bearing for that.

1. test_slack_cable_renders_as_sagging_catenary_at_rest -- a cable whose
   true/prescribed length exceeds the chord between its two fixed endpoints
   must render, before any Analyze/Form-find, as a genuine multi-point
   self-weight catenary (not a straight line), per _solve_nominal_catenary.

2. test_taut_cable_renders_as_flagged_straight_line -- a cable whose true
   length is at or below that chord cannot physically sag: it must render
   as a straight 2-point line spanning exactly the chord distance (never
   stretched or faked into a sag), and that line must be visually
   distinguished on the canvas (WARNING color + dashed) from a genuine
   catenary, so the two cases never look alike at a glance.

3/4. test_picture_example_junction_moves_off_the_old_chord,
   test_example_junction_moves_off_the_old_chord -- Phase 2 requirement 6:
   on both of this project's own built-in diagnostic examples, a junction
   linking two or more cables must settle measurably below the straight
   chord _point_on_chord() would have pinned it to under the old
   per-segment-fixed-junction behaviour (that function itself is
   unchanged -- Phase 2 requirement 1 -- so it still gives the OLD
   position to compare against).

5. test_straight_mode_matches_old_chord_pinned_behaviour -- Phase 3:
   selecting Straight (as-drawn) mode must skip the solve entirely (an
   empty cache, not just an unused result) and must never mutate a
   junction's own stored position -- only what _draw() shows for it.
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

from apps.cable_web.cable_web_app import CableWebApp, PX_PER_M, CABLE, WARNING


def _new_root_or_skip():
    """Create a Tk root, retrying briefly before giving up.

    Creating and destroying a dozen-plus Tk roots in one pytest process
    intermittently fails on Windows with "This probably means that tk wasn't
    installed properly" -- a transient resource/timing failure, not a real
    absence of a display. The skip-if-no-display guard these tests use would
    otherwise convert that into a silent skip, which is exactly how a real
    failure hides. Retry first; only skip if it keeps failing, which is what
    a genuinely headless environment looks like.
    """
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


def _make_app_or_skip():
    root = _new_root_or_skip()
    root.geometry('900x700+0+0')
    app = CableWebApp(root)
    app.pack(fill='both', expand=True)
    # Catenary is what every test in this file is about. It stopped being the
    # app default on 2026-09-04 (it is a multi-second background solve, so the
    # user now opts into it) -- set it explicitly here rather than relying on
    # whatever the shipped default happens to be.
    app.reference_mode.set('catenary')
    root.update_idletasks()
    root.update()
    return root, app


def _teardown(root):
    """Destroy the root AND collect on the main thread -- otherwise a
    tkinter.Variable belonging to a destroyed root can be collected later on
    a background thread, whose __del__ then raises "main thread is not in
    main loop". Test-process noise only (a real run has one root for the
    process lifetime), but noise that makes a clean suite look dirty."""
    try:
        root.destroy()
    finally:
        gc.collect()


def _settle(app):
    """The at-rest preview is solved on a background thread since
    2026-09-04, so it is not finished when _update_reference_result() (or a
    loader that calls it) returns. Pump until it is -- these tests are about
    the shapes it produces, not about the threading."""
    assert app._wait_for_reference_result(timeout=600), \
        'background at-rest preview did not settle within 600 s'


def _add_two_supports(app, span_m):
    span_px = span_m * PX_PER_M
    a = app._new_node(0.0, 0.0, support=True)
    b = app._new_node(span_px, 0.0, support=True)
    return a, b


def test_slack_cable_renders_as_sagging_catenary_at_rest():
    root, app = _make_app_or_skip()
    try:
        span_m = 10.0
        true_length_m = 16.0  # well beyond the 10 m chord -- must sag
        a, b = _add_two_supports(app, span_m)
        cable = app._new_cable(a['id'], b['id'])
        cable['length_override'] = true_length_m
        app._update_reference_result()
        _settle(app)

        segs = app._reference_segments.get(cable['id'])
        assert segs, 'expected a reference segment for a cable with true length > span'
        assert len(segs) == 1, 'no interior junctions -- expected exactly one segment'
        seg = segs[0]
        assert seg['taut'] is False, 'a cable with real slack must not be flagged taut'
        assert len(seg['points']) > 2, \
            'a genuine catenary must have more than 2 sample points, not a straight line'

        # It must sag: every interior point should be BELOW the dead-straight
        # chord line joining the two endpoints (world-px y grows downward).
        (x0, y0), (x1, y1) = seg['points'][0], seg['points'][-1]
        assert approx(x0, 0.0) and approx(y0, 0.0)
        assert approx(x1, span_m * PX_PER_M) and approx(y1, 0.0)
        interior_ys = [p[1] for p in seg['points'][1:-1]]
        assert all(y > 1.0 for y in interior_ys), \
            f'expected every interior point to sag below the chord, got ys={interior_ys}'

        # The path length along the sampled points should be close to the
        # cable's true material length, not the shorter chord.
        pts = seg['points']
        sampled_len = sum(math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1])
                           for i in range(len(pts)-1)) / PX_PER_M
        assert approx(sampled_len, true_length_m, tol=true_length_m * 0.03), \
            f'sampled catenary length {sampled_len:.3f} m should be close to the true length {true_length_m} m'

        # Visual check: drawn in normal CABLE color, solid (no dash).
        app._fit_view()
        root.update()
        found = _find_reference_line(app, min_points=3)
        assert found is not None, 'expected a multi-point line item on the canvas for the sagging cable'
        fill, dash = found
        assert fill == CABLE, f'a genuine catenary should draw in CABLE color, got {fill}'
        assert not dash, f'a genuine catenary should be solid (no dash), got dash={dash!r}'

        print('test_slack_cable_renders_as_sagging_catenary_at_rest: PASS '
              f'(sampled_len={sampled_len:.3f} m, points={len(pts)})')
    finally:
        _teardown(root)


def test_taut_cable_renders_as_flagged_straight_line():
    root, app = _make_app_or_skip()
    try:
        span_m = 10.0
        true_length_m = 8.0  # shorter than the 10 m chord -- cannot reach
        a, b = _add_two_supports(app, span_m)
        cable = app._new_cable(a['id'], b['id'])
        cable['length_override'] = true_length_m
        app._update_reference_result()
        _settle(app)

        segs = app._reference_segments.get(cable['id'])
        assert segs and len(segs) == 1
        seg = segs[0]
        assert seg['taut'] is True, 'a cable whose true length <= span must be flagged taut'
        assert len(seg['points']) == 2, \
            'a taut/too-short cable must render as an exact straight 2-point line, not a sag'

        (x0, y0), (x1, y1) = seg['points']
        span_line_len = math.hypot(x1 - x0, y1 - y0) / PX_PER_M
        assert approx(span_line_len, span_m, tol=1e-6), \
            (f'the straight line must span exactly the chord/span distance ({span_m} m), '
             f'not the cable\'s own shorter true length ({true_length_m} m); got {span_line_len:.6f} m')
        assert approx(x0, 0.0) and approx(y0, 0.0)
        assert approx(x1, span_m * PX_PER_M) and approx(y1, 0.0)

        # Visual check: drawn WARNING color, dashed -- never stretched/faked,
        # and never indistinguishable from a genuine catenary.
        app._fit_view()
        root.update()
        found = _find_reference_line(app, min_points=2, max_points=2)
        assert found is not None, 'expected a 2-point line item on the canvas for the taut cable'
        fill, dash = found
        assert fill == WARNING, f'a taut/too-short cable should draw in WARNING color, got {fill}'
        assert dash, 'a taut/too-short cable should be dashed so it never looks like a genuine sag'

        print('test_taut_cable_renders_as_flagged_straight_line: PASS '
              f'(span_line_len={span_line_len:.6f} m)')
    finally:
        _teardown(root)


def _find_reference_line(app, min_points, max_points=None):
    """Find a line item on the canvas matching the given point-count range,
    restricted to CABLE/WARNING fill so grid/load/node items are ignored."""
    c = app.zc.canvas
    for item in c.find_all():
        if c.type(item) != 'line':
            continue
        fill = c.itemcget(item, 'fill')
        if fill not in (CABLE, WARNING):
            continue
        coords = c.coords(item)
        npts = len(coords) // 2
        if npts >= min_points and (max_points is None or npts <= max_points):
            return fill, c.itemcget(item, 'dash')
    return None


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def _junction_moved_off_chord(app, junction_id):
    """Phase 2 requirement 6 helper: the chord position a junction would
    have sat on under the old per-segment-fixed-junction behaviour (i.e.
    exactly what _point_on_chord still computes -- that function is
    unchanged, per Phase 2 requirement 1) versus where the connected-
    component free-junction solve actually placed it."""
    n = app._node(junction_id)
    cid, s = n['attachments'][0]
    old_x, old_y = app._point_on_chord(cid, s)
    new_x, new_y = app._reference_junction_positions[junction_id]
    return (old_x, old_y), (new_x, new_y)


def test_picture_example_junction_moves_off_the_old_chord():
    root, app = _make_app_or_skip()
    try:
        app._load_picture_example()
        _settle(app)
        for jid in (5, 6):
            assert jid in app._reference_junction_positions, \
                f'expected a solved position for junction {jid}'
            (old_x, old_y), (new_x, new_y) = _junction_moved_off_chord(app, jid)
            moved = math.hypot(new_x - old_x, new_y - old_y)
            assert moved > 1.0, (
                f'junction {jid} barely moved off its old chord position '
                f'({old_x:.1f},{old_y:.1f}) -> ({new_x:.1f},{new_y:.1f}), '
                f'moved {moved:.3f}px -- expected a measurable sag')
            # World-px y increases downward; a hanging cable's junction
            # should settle BELOW the chord it used to be pinned to.
            assert new_y > old_y, (
                f'junction {jid} moved to ({new_x:.1f},{new_y:.1f}) but not '
                f'below its old chord position ({old_x:.1f},{old_y:.1f})')
        print('test_picture_example_junction_moves_off_the_old_chord: PASS')
    finally:
        _teardown(root)


def test_example_junction_moves_off_the_old_chord():
    root, app = _make_app_or_skip()
    try:
        app._load_example()
        _settle(app)
        for jid in (5, 6):
            assert jid in app._reference_junction_positions
            (old_x, old_y), (new_x, new_y) = _junction_moved_off_chord(app, jid)
            moved = math.hypot(new_x - old_x, new_y - old_y)
            assert moved > 1.0, (
                f'junction {jid} barely moved: ({old_x:.1f},{old_y:.1f}) -> '
                f'({new_x:.1f},{new_y:.1f}), moved {moved:.3f}px')
            assert new_y > old_y
        print('test_example_junction_moves_off_the_old_chord: PASS')
    finally:
        _teardown(root)


def test_straight_mode_matches_old_chord_pinned_behaviour():
    """Phase 3: Straight (as-drawn) must still show exactly the old
    chord-pinned picture -- no solve, junction markers back at their
    stored (as-drawn) position, so it stays a free, instant fallback."""
    root, app = _make_app_or_skip()
    try:
        app._load_picture_example()
        _settle(app)
        assert app._reference_junction_positions, \
            'Catenary is the default -- expected a solved position already'
        stored_before = {jid: (app._node(jid)['x'], app._node(jid)['y']) for jid in (5, 6)}
        app.reference_mode.set('straight')
        app._on_reference_mode_changed()
        _settle(app)
        assert not app._reference_junction_positions, (
            'Straight mode must skip the solve entirely (an empty cache), '
            'not just skip drawing its result')
        for jid in (5, 6):
            n = app._node(jid)
            # Phase 2 requirement 1: the connected-component solve must
            # never mutate a junction's own stored position -- only what
            # _draw() shows for it. Confirmed here by checking the stored
            # position is bit-for-bit the same after a Catenary-preview
            # solve ran and was then switched away from, not just that it
            # happens to match some independent recomputation.
            assert (n['x'], n['y']) == stored_before[jid], (
                f"junction {jid}'s stored position changed: "
                f"{stored_before[jid]} -> {(n['x'], n['y'])}")
        print('test_straight_mode_matches_old_chord_pinned_behaviour: PASS')
    finally:
        _teardown(root)


if __name__ == '__main__':
    failures = 0
    for t in (test_slack_cable_renders_as_sagging_catenary_at_rest,
              test_taut_cable_renders_as_flagged_straight_line,
              test_picture_example_junction_moves_off_the_old_chord,
              test_example_junction_moves_off_the_old_chord,
              test_straight_mode_matches_old_chord_pinned_behaviour):
        try:
            t()
        except AssertionError as ex:
            failures += 1
            print(f'{t.__name__}: FAIL -- {ex}')
    print('All tests passed.' if not failures else f'{failures} test(s) FAILED')
    sys.exit(1 if failures else 0)
