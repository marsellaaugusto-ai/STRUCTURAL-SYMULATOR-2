"""The Truss tab's buckling demonstration (apps/truss/truss_buckling):
held to Euler's two classic columns, and to what the second-order curve
must do near the buckling load."""
import gc
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from common import PX_PER_M
from apps.truss import truss_buckling as tb
from apps.truss import truss_examples as tx
from apps.truss.truss_math import analyze

E, A, I, L, P = 200.0, 10.0, 100.0, 4.0, 10.0
NODES = [(0.0, 0.0), (0.0, -L * PX_PER_M)]


def _column(conn, supports):
    rods = [{'a': 0, 'b': 1, 'E': E, 'A': A, 'I': I, 'conn': conn}]
    loads = [{'node': 1, 'fx': 0.0, 'fy': P}]
    res, err = analyze(NODES, rods, loads, supports)
    assert err is None
    return rods, loads, res


def _euler(K):
    return math.pi ** 2 * E * 1e9 * I * 1e-8 / (K * L) ** 2 / 1e3


def test_a_pinned_column_buckles_at_euler_within_1_percent():
    sups = [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'rollerY'}]
    rods, _loads, res = _column('pin', sups)
    b = tb.buckling(NODES, rods, sups, res)
    assert b['factors'][0] * P == pytest.approx(_euler(1.0), rel=0.01)
    assert b['modes'][0]['peak'] == ('mid', 0)       # it bows


def test_a_cantilever_buckles_at_euler_with_k_2():
    sups = [{'node': 0, 'type': 'fixed'}]
    rods, _loads, res = _column('rigid', sups)
    b = tb.buckling(NODES, rods, sups, res)
    assert b['factors'][0] * P == pytest.approx(_euler(2.0), rel=0.01)
    assert b['modes'][0]['peak'] == ('node', 1)      # its tip sways


def test_the_second_order_curve_runs_away_near_the_buckling_load():
    sups = [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'rollerY'}]
    rods, loads, res = _column('pin', sups)
    ld = tb.load_deflection(NODES, rods, sups, loads, res)
    lcr = ld['lambda_cr']
    assert ld['factors'][-1] == pytest.approx(0.95 * lcr)
    # bow = bow0 / (1 - lambda/lcr): 20 x at 95 %
    assert ld['bow_mm'][-1] == pytest.approx(ld['bow0_mm'] / 0.05, rel=0.05)
    assert ld['bow_mm'][0] == pytest.approx(ld['bow0_mm'], rel=1e-6)
    # first-order is a straight line through the origin
    for lam, d in zip(ld['factors'], ld['first_mm']):
        assert d == pytest.approx(ld['first_mm'][-1] * lam / ld['factors'][-1],
                                  abs=1e-9)


def test_tension_only_says_nothing_can_buckle():
    sups = [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'rollerY'}]
    rods = [{'a': 0, 'b': 1, 'E': E, 'A': A, 'I': I}]
    loads = [{'node': 1, 'fx': 0.0, 'fy': -P}]           # pulls up
    res, _ = analyze(NODES, rods, loads, sups)
    assert 'nothing can buckle' in tb.buckling(NODES, rods, sups, res)['error']
    assert 'Analyze first' in tb.buckling(NODES, rods, sups, None)['error']


def test_the_failing_warren_buckles_below_its_load_and_the_pratt_above():
    for key, below in (('warren', True), ('pratt', False)):
        m = tx.get(key)[1]
        res, _ = analyze(m['nodes'], m['rods'], m['loads'], m['supports'])
        lam = tb.buckling(m['nodes'], m['rods'], m['supports'],
                          res)['factors'][0]
        assert (lam < 1.0) == below, (key, lam)


# ── in the tab ────────────────────────────────────────────────────────────

@pytest.fixture()
def app(monkeypatch):
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
    try:
        yield a
    finally:
        root.destroy()
        gc.collect()


def test_the_window_needs_a_solve_then_draws_shape_and_curve(app):
    app._load_library_example('fink')
    assert app._open_buckling() is None
    assert 'Analyze first' in app.status_var.get()
    app._run_analysis(quiet=True)
    win = app._open_buckling()
    assert win is not None and win.result['factors'][0] > 1.0
    assert win.shape_canvas.find_all() and win.plot_canvas.find_all()
    win.mode_var.set(1)
    win.destroy()


def test_the_window_warns_when_it_buckles_before_the_full_load(app):
    app._load_library_example('warren')
    app._run_analysis(quiet=True)
    win = app._open_buckling()
    texts = [w.cget('text') for w in win.winfo_children()
             if w.winfo_class() == 'Label']
    assert any('BEFORE the full load' in t for t in texts)
    win.destroy()
