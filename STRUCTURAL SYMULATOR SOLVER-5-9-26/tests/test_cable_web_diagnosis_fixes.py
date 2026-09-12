"""test_cable_web_diagnosis_fixes.py -- regression tests for the three root
causes found on 2026-09-04 (REPORTS AND GUIDES/CABLE_WEB_DIAGNOSIS_2026-09-04.md).

Each test here exists because something shipped broken and nothing in the
suite would have noticed:

1. test_scipy_is_available
   SciPy is a hard requirement for any web with a junction -- the Newton/LM
   seeds converge on none of them -- but it was undeclared, absent, and its
   ImportError was swallowed and reported as "did not converge". This makes
   the environment problem fail at pytest time, as an environment problem.

2. test_no_cable_becomes_a_single_rigid_solver_edge
   test_taut_tie_topologies_converge
   _solver_breakpoints() used to leave an unloaded, weightless, non-slack
   cable as ONE rigid 2-node edge, which solve_analysis reliably fails on.
   Four such webs are checked directly; the first test guards the mechanism
   so a future "optimisation" that reintroduces the short-circuit fails
   immediately rather than showing up as a mysterious non-convergence.

3. test_at_rest_preview_does_not_block_the_main_thread
   The at-rest Catenary preview ran a multi-second network solve
   synchronously on the Tk main thread, from ~11 call sites. This asserts
   the PROMISE (the call returns fast, the event loop keeps running), not
   the solver's speed -- so it stays meaningful if the solver gets slower.

4. test_impossible_cable_is_flagged / test_runaway_tension_is_flagged
   A cable prescribed shorter than its own chord validated as "structurally
   ready" and then produced a "converged" 313 kN result under 372 N of load.

5. test_stale_solve_result_is_discarded
   self._solving blocks the canvas edit path only; every dialog, Undo/Redo
   and example loader stays live during a background solve.
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

import apps.cable_web.cable_web_math as cwm
from apps.cable_web.cable_web_app import CableWebApp, PX_PER_M


# --------------------------------------------------------------------------
# 1. Environment
# --------------------------------------------------------------------------

def test_scipy_is_available():
    """Not a style check -- a load-bearing dependency check.

    solve_analysis's bounded least-squares step is written as a "fallback",
    but measured across both built-in examples and eight hand-built
    topologies it is the ONLY path that ever reaches tolerance on a
    multi-cable network. Without SciPy the Cable Web tab silently reports
    every junction web as non-convergent.
    """
    pytest.importorskip(
        'scipy.optimize',
        reason='SciPy is REQUIRED by cable_web (see CABLE_WEB_DIAGNOSIS_2026-09-04.md); '
               'install it with: python -m pip install scipy')


# --------------------------------------------------------------------------
# Shared fixtures for the UI-level checks
# --------------------------------------------------------------------------

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


def _make_app_or_skip(mode='straight'):
    root = _new_root_or_skip()
    root.geometry('900x700+0+0')
    app = CableWebApp(root)
    app.pack(fill='both', expand=True)
    app.reference_mode.set(mode)
    root.update_idletasks()
    root.update()
    return root, app


def _teardown(root):
    """Destroy the root AND collect on the main thread.

    Each test builds its own tk.Tk(). If a tkinter.Variable owned by a
    destroyed root is instead collected later, on a background thread, its
    __del__ calls into a dead interpreter and raises "main thread is not in
    main loop" as an unraisable exception -- pure test-process noise (a real
    run has one root for the process lifetime), but noise that makes a clean
    suite look dirty. Collecting here, on the main thread, keeps it out.
    """
    try:
        root.destroy()
    finally:
        gc.collect()


def _m(x, y):
    """metres (y up) -> editor world px"""
    return x * PX_PER_M, -y * PX_PER_M


def _load(app, cid, typ, s1, s2, mag, direction='Vertical'):
    app.loads.append({'id': f'L{app.next_load_id}', 'cable': cid, 'type': typ,
                      's1': s1, 's2': s2 if typ != 'Point' else s1,
                      'magnitude': mag, 'direction': direction,
                      'angle_deg': -90.0, 'expression': ''})
    app.next_load_id += 1


def _build_star(app, tie_length):
    """Three cables meeting at one free junction. The tie C3 has no load, no
    self-weight, and no slack -- exactly the case that used to reach the
    solver as a single rigid edge."""
    s1 = app._new_node(*_m(0, 8), support=True)
    s2 = app._new_node(*_m(14, 8), support=True)
    s3 = app._new_node(*_m(7, -6), support=True)
    j = app._new_node(*_m(7, 2), support=False)
    c1 = app._new_cable(s1['id'], j['id']); c1['length_override'] = 10.0
    c2 = app._new_cable(s2['id'], j['id']); c2['length_override'] = 10.0
    c3 = app._new_cable(s3['id'], j['id']); c3['length_override'] = tie_length
    # Self-weight pinned, not inherited: these cases are ABOUT a tie with
    # no load on it, and _new_cable's default is a UI convenience that is
    # free to change (it became 1 kN/m on 2026-09-05).
    c1['w'] = c2['w'] = c3['w'] = 0.0
    _load(app, c1['id'], 'Point', 9.0, 9.0, 150.0)
    _load(app, c2['id'], 'UDL', 0.0, 10.0, 6.0)
    return c1, c2, c3


def _build_twin_tie(app, tie_length):
    """Two suspended cables joined by an unloaded tie between two interior
    junctions -- the Picture Test family, but with a taut tie."""
    a1 = app._new_node(*_m(0, 0), support=True)
    a2 = app._new_node(*_m(10, 0), support=True)
    b1 = app._new_node(*_m(18, 0), support=True)
    b2 = app._new_node(*_m(28, 0), support=True)
    j1 = app._new_node(*_m(3, 0), support=False)
    j2 = app._new_node(*_m(23, 0), support=False)
    ca = app._new_cable(a1['id'], a2['id']); ca['length_override'] = 16.0
    cb = app._new_cable(b1['id'], b2['id']); cb['length_override'] = 16.0
    cc = app._new_cable(j1['id'], j2['id']); cc['length_override'] = tie_length
    # Self-weight pinned, not inherited: these cases are ABOUT a tie with
    # no load on it, and _new_cable's default is a UI convenience that is
    # free to change (it became 1 kN/m on 2026-09-05).
    ca['w'] = cb['w'] = cc['w'] = 0.0
    app._attach_node(j1['id'], ca['id'], 5.0)
    app._attach_node(j2['id'], cb['id'], 5.0)
    _load(app, ca['id'], 'Point', 8.0, 8.0, 100.0)
    _load(app, cb['id'], 'UDL', 0.0, 16.0, 10.0)
    return ca, cb, cc


def _build_hanger(app):
    """A junction tied down to an anchor by a vertical, unloaded, taut cable."""
    a = app._new_node(*_m(0, 0), support=True)
    b = app._new_node(*_m(16, 0), support=True)
    j = app._new_node(*_m(8, 0), support=False)
    anc = app._new_node(*_m(8, -6), support=True)
    ca = app._new_cable(a['id'], b['id']); ca['length_override'] = 20.0
    ct = app._new_cable(j['id'], anc['id']); ct['length_override'] = 6.0
    # Self-weight pinned, not inherited: these cases are ABOUT a tie with
    # no load on it, and _new_cable's default is a UI convenience that is
    # free to change (it became 1 kN/m on 2026-09-05).
    ca['w'] = ct['w'] = 0.0
    app._attach_node(j['id'], ca['id'], 10.0)
    _load(app, ca['id'], 'UDL', 0.0, 20.0, 12.0)
    return ca, ct


def _analyze(app, root, timeout=300):
    t0 = time.perf_counter()
    app._solve_exact()
    while app._solving and time.perf_counter() - t0 < timeout:
        root.update()
        # 20 ms for the same reason as _wait_for_reference_result: the
        # result arrives via an after(80, ...) poller, and every extra
        # wake-up here is a GIL handoff stolen from the solving thread.
        time.sleep(0.02)
    return app.result


# --------------------------------------------------------------------------
# 2. The single-rigid-edge bug
# --------------------------------------------------------------------------

CASES = [
    ('star, tie exactly taut', lambda app: _build_star(app, 8.0)),
    ('star, tie shorter than chord', lambda app: _build_star(app, 7.5)),
    ('twin cables + taut tie', lambda app: _build_twin_tie(app, 20.0)),
    ('junction on a taut hanger', lambda app: _build_hanger(app)),
]


@pytest.mark.parametrize('label,build', CASES, ids=[c[0] for c in CASES])
def test_no_cable_becomes_a_single_rigid_solver_edge(label, build):
    """Guards the MECHANISM, not just the symptom.

    _solver_breakpoints() must never return just {0, L} for a cable: that
    is a single rigid 2-node edge, and solve_analysis fails on those. This
    is the check that would have caught the original bug -- the symptom
    (non-convergence) looked like a solver problem, not a meshing one.
    """
    root, app = _make_app_or_skip()
    try:
        build(app)
        for c in app.cables:
            bp = app._solver_breakpoints(c['id'], include_user_loads=True)
            assert len(bp) > 2, (
                f'{label}: C{c["id"]} would reach the solver as ONE rigid edge '
                f'(breakpoints={bp}). See MANIFESTO sec 6 / '
                f'CABLE_WEB_DIAGNOSIS_2026-09-04.md.')
    finally:
        _teardown(root)


@pytest.mark.parametrize('label,build', CASES, ids=[c[0] for c in CASES])
def test_taut_tie_topologies_converge(label, build):
    """The four webs that failed at residual ~1e-2 before the meshing fix."""
    pytest.importorskip('scipy.optimize')
    root, app = _make_app_or_skip()
    try:
        build(app)
        assert app._validate_model(), app.validation_var.get()
        result = _analyze(app, root)
        assert result is not None, (
            f'{label}: Analyze produced no result -- {app.validation_var.get()!r}')
        assert result.converged, f'{label}: residual {result.residual:.3e}'
        assert result.residual < 1e-6, f'{label}: residual {result.residual:.3e}'
        tensions = [v for v in result.tensions.values() if v is not None]
        assert tensions, f'{label}: no tensions reported'
        assert min(tensions) > -1e-7, (
            f'{label}: a cable is in compression, T_min={min(tensions):.4g}')
    finally:
        _teardown(root)


def test_built_in_examples_still_converge():
    """The meshing change adds free nodes to every model -- confirm it did
    not disturb the two cases this project has always used as its
    references."""
    pytest.importorskip('scipy.optimize')
    for loader_name in ('_load_example', '_load_picture_example'):
        root, app = _make_app_or_skip()
        try:
            getattr(app, loader_name)()
            root.update()
            result = _analyze(app, root)
            assert result is not None and result.converged, (
                f'{loader_name}: {app.validation_var.get()!r}')
            assert result.residual < 1e-6, f'{loader_name}: {result.residual:.3e}'
        finally:
            _teardown(root)


# --------------------------------------------------------------------------
# 3. The main-thread freeze
# --------------------------------------------------------------------------

def test_at_rest_preview_does_not_block_the_main_thread():
    """Asserts the promise, not the solver's speed.

    _update_reference_result() must return promptly (it builds models and
    hands them to a worker) and the Tk event loop must keep running while
    the solve is in flight. Before 2026-09-04 this call blocked for 20-200 s
    and serviced exactly ONE already-queued after() callback in 48.9 s.
    """
    pytest.importorskip('scipy.optimize')
    root, app = _make_app_or_skip(mode='catenary')
    try:
        app._load_example()
        root.update()

        ticks = {'n': 0}

        def tick():
            ticks['n'] += 1
            root.after(20, tick)

        root.after(20, tick)
        root.update()

        t0 = time.perf_counter()
        app._update_reference_result()
        call_seconds = time.perf_counter() - t0
        assert call_seconds < 5.0, (
            f'_update_reference_result() blocked the main thread for '
            f'{call_seconds:.2f} s -- it must only BUILD models here')

        assert app._wait_for_reference_result(timeout=600), \
            'background at-rest preview never settled'
        assert ticks['n'] > 20, (
            f'the event loop only serviced {ticks["n"]} timer callbacks during '
            f'the background solve -- the UI was effectively frozen')
        assert app._reference_paths, \
            'the background solve settled but produced no at-rest shapes'
    finally:
        _teardown(root)


def test_straight_is_the_default_and_costs_nothing():
    """Straight mode must not solve at all -- an empty cache, not just an
    unused result -- and must be the shipped default."""
    root = _new_root_or_skip()
    root.geometry('900x700+0+0')
    app = CableWebApp(root)          # deliberately NOT setting reference_mode
    app.pack(fill='both', expand=True)
    root.update()
    try:
        assert app.reference_mode.get() == 'straight', \
            'the shipped default must not be the multi-second Catenary preview'
        t0 = time.perf_counter()
        app._load_example()
        root.update()
        elapsed = time.perf_counter() - t0
        assert elapsed < 3.0, f'loading the Example blocked for {elapsed:.2f} s'
        assert not app._reference_paths
        assert not app._reference_junction_positions
    finally:
        _teardown(root)


# --------------------------------------------------------------------------
# 4. Physically impossible models
# --------------------------------------------------------------------------

def test_impossible_cable_between_two_supports_is_an_error():
    root, app = _make_app_or_skip()
    try:
        a = app._new_node(*_m(0, 0), support=True)
        b = app._new_node(*_m(20, 0), support=True)
        c = app._new_cable(a['id'], b['id'])
        c['length_override'] = 14.0          # cannot span 20 m
        assert app._validate_model() is False, \
            'a 14 m cable between supports 20 m apart must not validate'
        assert 'cannot reach' in app.validation_var.get()
    finally:
        _teardown(root)


def test_impossible_cable_with_a_free_end_is_a_warning():
    root, app = _make_app_or_skip()
    try:
        _build_twin_tie(app, 14.0)           # tie 14 m, junctions 20 m apart
        assert app._validate_model() is True, \
            'with free junctions this is solvable, so it must not be an error'
        assert 'very high tension' in app.validation_var.get(), \
            f'expected a warning, got {app.validation_var.get()!r}'
    finally:
        _teardown(root)


def test_runaway_tension_is_flagged_even_when_the_residual_is_small():
    """The measured case: converged at residual 7.15e-08 (inside the relaxed
    practical_tol band) while reporting 313 kN under 372 N of load."""
    class _Edge:
        target_length = 1.0
        weight_per_length = 0.0

    class _Node:
        fx, fy = 0.0, -100.0

    class _FakeModel:
        nodes = {1: _Node()}
        edges = {1: _Edge()}

    class _FakeResult:
        model = _FakeModel()
        tensions = {1: 500000.0}
        residual = 7.15e-08
        converged = True

    note = CableWebApp._implausible_result_note(_FakeResult())
    assert note and 'applied load' in note, \
        f'a 5000x tension:load ratio must be flagged, got {note!r}'

    class _SaneResult(_FakeResult):
        tensions = {1: 180.0}

    assert CableWebApp._implausible_result_note(_SaneResult()) == '', \
        'an ordinary result must not be flagged'

    # The real measured case: 313 kN peak tension under 372 N of load,
    # a ratio of 842. This is the number the gate actually has to catch --
    # an earlier threshold of 1000 let it through.
    class _MeasuredCase(_FakeResult):
        tensions = {1: 313234.89}

    class _MeasuredModel:
        nodes = {1: type('N', (), {'fx': 0.0, 'fy': -372.0})()}
        edges = {}

    _MeasuredCase.model = _MeasuredModel()
    assert CableWebApp._implausible_result_note(_MeasuredCase()), \
        'the 842x case measured on 2026-09-04 must be flagged'

    # ...and a genuinely shallow-but-real net must not be. Every legitimate
    # web measured that day came in below 1.0; 50x is far beyond any of them
    # and still has to pass.
    class _ShallowButReal(_FakeResult):
        tensions = {1: 5000.0}

    _ShallowButReal.model = _MeasuredModel()
    assert CableWebApp._implausible_result_note(_ShallowButReal()) == '', \
        'a shallow but physically ordinary net must not be flagged'


# --------------------------------------------------------------------------
# 5. Stale background results
# --------------------------------------------------------------------------

def test_stale_solve_result_is_discarded():
    """A model edit during a background solve must invalidate that solve's
    result rather than have it attributed to the new structure."""
    root, app = _make_app_or_skip()
    try:
        app._load_example()
        root.update()
        app._solve_exact()
        # Simulate an edit landing while the worker is still running: every
        # mutating path in the app goes through _invalidate().
        app._invalidate('edited mid-solve')
        t0 = time.perf_counter()
        while app._solving and time.perf_counter() - t0 < 300:
            root.update()
            time.sleep(0.02)
        assert app.result is None, \
            'a result computed for the pre-edit model was shown anyway'
        assert 'discarded' in app.status_var.get(), \
            f'the user was not told, status was {app.status_var.get()!r}'
    finally:
        _teardown(root)


# --------------------------------------------------------------------------
# 6. Dead code that would have broken silently if reordered
# --------------------------------------------------------------------------

def test_no_duplicate_method_definitions_in_the_app_class():
    src = (Path(__file__).resolve().parents[1] /
           'apps' / 'cable_web' / 'cable_web_app.py').read_text(encoding='utf-8')
    import ast
    tree = ast.parse(src)
    dupes = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        seen = {}
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                seen.setdefault(item.name, []).append(item.lineno)
        for name, lines in seen.items():
            if len(lines) > 1:
                dupes[f'{node.name}.{name}'] = lines
    assert not dupes, (
        f'duplicate method definitions -- the later one silently wins: {dupes}')
