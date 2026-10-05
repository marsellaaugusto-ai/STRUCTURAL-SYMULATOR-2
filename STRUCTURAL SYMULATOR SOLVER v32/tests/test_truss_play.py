"""The Truss tab's "play and compare" layer: the example library and its
lessons, the score, Play load and the Load % slider, design variants.

The lesson tests hold each question to what its truss actually does: a
question whose premise the solver contradicts would teach the wrong thing.
"""
import gc
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import tkinter as tk
except Exception:
    tk = None

import pytest

from apps.truss import truss_examples as tx
from apps.truss import truss_design as td
from apps.truss import truss_score as ts
from apps.truss import truss_stability
from apps.truss.truss_math import analyze, compute_diagrams


def _solve(m, rods=None):
    rods = m['rods'] if rods is None else rods
    res, err = analyze(m['nodes'], rods, m['loads'], m['supports'], [])
    if err:
        return None, None
    diags = compute_diagrams(m['nodes'], rods, m['loads'], res)
    return res, td.check_rods(m['nodes'], rods, m['profiles'], res, diags)


def _forces(m, family):
    res, _ = _solve(m)
    return [rr['force'] for r, rr in zip(m['rods'], res['rod_res'])
            if r['profile'] == family]


# ── the library ───────────────────────────────────────────────────────────

def test_nine_examples_each_with_a_lesson():
    keys = [k for k, _t, _b in tx.EXAMPLES]
    assert len(keys) == 9 and len(set(keys)) == 9
    assert set(keys) == set(tx.LESSONS)
    for k in keys:
        lesson = tx.LESSONS[k]
        assert lesson['goal'] and 2 <= len(lesson['questions']) <= 3


def test_every_example_has_steel_on_every_rod():
    for k, _t, build in tx.EXAMPLES:
        m = build()
        for r in m['rods']:
            prof = m['profiles'][r['profile']]
            assert prof.get('Fy') and prof.get('r_gyr') and prof.get('catalog')
            assert r['A'] == prof['A'] and r['E'] == prof['E']


def test_every_example_but_the_mechanism_stands_and_is_checked():
    for k, _t, build in tx.EXAMPLES:
        m = build()
        res, checks = _solve(m)
        if k == 'missing_diagonal':
            assert res is None
            continue
        assert res is not None, k
        assert all(c.get('checked') for c in checks), k


def test_only_the_warren_truss_fails_as_shipped():
    """Its lesson starts from "as shipped it fails"; the others pass, so
    their scores can be compared."""
    for k, _t, build in tx.EXAMPLES:
        if k == 'missing_diagonal':
            continue
        _res, checks = _solve(build())
        u = td.governing(checks)[1]['util']
        assert (u > 1.0) == (k == 'warren'), (k, u)


def test_warren_a_heavier_web_makes_it_pass():
    m = tx.warren()
    p = tx.family('CHS 101.6x4.0')
    m['profiles']['Web'] = p
    for r in m['rods']:
        if r['profile'] == 'Web':
            r.update(E=p['E'], A=p['A'], I=p['I'])
    _res, checks = _solve(m)
    assert td.governing(checks)[1]['util'] <= 1.0


def test_warren_bottom_chord_pulls_and_top_chord_pushes():
    m = tx.warren()
    res, _ = _solve(m)
    f = {(r['a'], r['b']): rr['force'] for r, rr in zip(m['rods'], res['rod_res'])}
    assert f[(0, 2)] > 0 and f[(2, 4)] > 0      # bottom
    assert f[(1, 3)] < 0                         # top


def test_warren_deleting_rod_1_makes_a_mechanism():
    m = tx.warren()
    rods = [r for i, r in enumerate(m['rods']) if i != 1]
    st = truss_stability.check(m['nodes'], rods, m['supports'], [])
    assert st['verdict'] == 'mechanism'


def test_pratt_diagonals_pull_and_verticals_push():
    m = tx.pratt()
    assert all(f > 0.01 for f in _forces(m, 'Diagonal'))
    assert all(f < -0.01 for f in _forces(m, 'Vertical'))


def test_howe_turns_the_signs_round():
    m = tx.howe()
    assert all(f < -0.01 for f in _forces(m, 'Diagonal'))
    assert all(f > -0.01 for f in _forces(m, 'Vertical'))
    assert any(f > 0.01 for f in _forces(m, 'Vertical'))


def test_howe_needs_more_steel_than_pratt():
    s = {}
    for k in ('pratt', 'howe'):
        m = getattr(tx, k)()
        res, checks = _solve(m)
        s[k] = ts.score(m['nodes'], m['rods'], res, checks)
    assert s['howe']['mass_kg'] > s['pratt']['mass_kg']


def test_king_post_carries_nothing_until_the_tie_is_loaded():
    m = tx.king_post()
    assert abs(_forces(m, 'Post')[0]) < 0.01
    m['loads'].append({'node': 1, 'fx': 0.0, 'fy': 10.0})
    assert _forces(m, 'Post')[0] > 0.01             # it hangs the load
    m2 = tx.king_post()
    rods = [r for i, r in enumerate(m2['rods']) if i != 1]
    st = truss_stability.check(m2['nodes'], rods, m2['supports'], [])
    assert st['verdict'] == 'mechanism'


def test_fink_has_reserve_and_webs_both_ways():
    m = tx.fink()
    _res, checks = _solve(m)
    assert td.governing(checks)[1]['util'] < 1.0
    webs = _forces(m, 'Web')
    assert any(f > 0.01 for f in webs) and any(f < -0.01 for f in webs)


def test_cantilever_top_chord_pulls():
    m = tx.cantilever()
    res, _ = _solve(m)
    top = [rr['force'] for r, rr in zip(m['rods'], res['rod_res'])
           if r['profile'] == 'Chord' and m['nodes'][r['a']][1] ==
           m['nodes'][r['b']][1] == m['nodes'][1][1]]
    bottom = [rr['force'] for r, rr in zip(m['rods'], res['rod_res'])
              if r['profile'] == 'Chord' and rr['force'] < 0]
    assert top and all(f > 0 for f in top) and bottom
    ry = {n: r['ry'] for n, r in res['reactions'].items()}
    rx = {n: r['rx'] for n, r in res['reactions'].items()}
    assert rx[0] * rx[1] < 0                        # one pulls, one pushes


def test_vierendeel_is_rigid_and_pinning_it_is_a_mechanism():
    m = tx.vierendeel()
    assert all(r.get('conn') == 'rigid' for r in m['rods'])
    res, _ = _solve(m)
    assert res is not None
    pinned = [dict(r, conn='pin') for r in m['rods']]
    st = truss_stability.check(m['nodes'], pinned, m['supports'], [])
    assert st['verdict'] == 'mechanism'


def test_missing_diagonal_is_one_mechanism_and_one_rod_fixes_it():
    m = tx.missing_diagonal()
    st = truss_stability.check(m['nodes'], m['rods'], m['supports'], [])
    assert st['verdict'] == 'mechanism' and st['mechanisms'] == 1
    for a, b in ((6, 2), (1, 7)):                    # either diagonal
        rods = m['rods'] + [dict(m['rods'][0], a=a, b=b)]
        st = truss_stability.check(m['nodes'], rods, m['supports'], [])
        assert st['verdict'] != 'mechanism'


def _idle(m):
    res, _ = _solve(m)
    return {i for i, rr in enumerate(res['rod_res'])
            if abs(rr['force']) <= 0.01}


def test_single_load_idle_rods_follow_the_joints_not_the_load():
    m = tx.single_load()
    idle = _idle(m)
    assert len(idle) >= 3
    for n in (2, 3):                                  # other bottom nodes
        m['loads'] = [{'node': n, 'fx': 0.0, 'fy': 60.0}]
        assert _idle(m) == idle
    # on node 7 the centre vertical (rod 10) starts working
    m['loads'] = [{'node': 7, 'fx': 0.0, 'fy': 60.0}]
    on_top = _idle(m)
    assert 10 in idle and 10 not in on_top and on_top < idle
    r = m['rods'][10]
    assert {r['a'], r['b']} == {2, 7}


# ── the score ─────────────────────────────────────────────────────────────

def test_score_mass_and_carried_load():
    m = tx.pratt()
    res, checks = _solve(m)
    s = ts.score(m['nodes'], m['rods'], res, checks)
    by_hand = sum(r['A'] * 1e-4 * td.rod_length_m(m['nodes'], r)
                  for r in m['rods']) * 7850 * 78.5 / (7850 * 9.80665 / 1000) \
        / 1000 * 1000
    assert s['mass_kg'] == pytest.approx(by_hand, rel=1e-9)
    assert s['carried_kN'] == pytest.approx(120.0, rel=1e-6)
    assert s['passes'] is True and s['ratio'] > 1
    assert 'passes' in ts.describe(s)


def test_better_needs_a_pass_and_less_steel():
    a = {'passes': True, 'mass_kg': 100.0}
    assert ts.better(a, None)
    assert not ts.better({'passes': False, 'mass_kg': 10.0}, a)
    assert ts.better({'passes': True, 'mass_kg': 90.0}, a)
    assert not ts.better({'passes': True, 'mass_kg': 110.0}, a)


# ── in the tab ────────────────────────────────────────────────────────────

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
    pytest.skip(f'no display available ({last})')


@pytest.fixture()
def app(monkeypatch):
    from tkinter import messagebox
    for name in ('showerror', 'showwarning', 'showinfo'):
        monkeypatch.setattr(messagebox, name, lambda *a, **k: None)
    from apps.truss.truss_app import TrussApp
    root = _new_root_or_skip()
    root.geometry('1440x900+0+0')
    host = tk.Frame(root)
    host.pack(fill='both', expand=True)
    a = TrussApp(host)
    _settle(root)
    try:
        yield a
    finally:
        try:
            if a._play is not None:
                a._stop_play(finished=False)
            a._stop_mechanism()
            root.destroy()
        finally:
            gc.collect()


def _settle(root, n=6):
    for _ in range(n):
        root.update_idletasks()
        root.update()


def test_the_library_loads_an_example_with_its_lesson(app):
    win = app._open_examples()
    win.listbox.selection_clear(0, 'end')
    win.listbox.selection_set(1)                      # Pratt
    win.load()
    assert app._example_key == 'pratt'
    assert len(app.rods) == len(tx.pratt()['rods'])
    assert app._lesson_card is not None
    app._clear_all()
    assert app._example_key is None and app._lesson_card is None


def test_every_library_example_analyses_in_the_tab(app):
    for k, _t, _b in tx.EXAMPLES:
        app._load_library_example(k)
        app._run_analysis(quiet=True)
        if k == 'missing_diagonal':
            assert app.results is None
        else:
            assert app.results is not None, k
            assert 'Score: Weighs' in app.res_var.get(), k


def test_the_load_slider_scales_every_force(app):
    app._load_library_example('pratt')
    app._run_analysis(quiet=True)
    full = [r['force'] for r in app.results['rod_res']]
    app.load_pct.set(40)
    app._apply_slide()
    part = [r['force'] for r in app.results['rod_res']]
    for f, p in zip(full, part):
        assert p == pytest.approx(0.4 * f, abs=1e-9)
    assert '40 % of the load' in app.status_var.get()


def test_the_load_slider_scales_span_loads_too(app):
    app._load_library_example('vierendeel')
    for r in app.rods[:4]:
        r['udl'] = 5.0
    app._run_analysis(quiet=True)
    m_full = max(abs(v) for d in app.diagrams[:4] for v in d['M'])
    app.load_pct.set(50)
    app._apply_slide()
    m_half = max(abs(v) for d in app.diagrams[:4] for v in d['M'])
    assert m_half == pytest.approx(0.5 * m_full, rel=1e-9)
    assert app.rods[0]['udl'] == 5.0                  # the model is unchanged


def test_play_load_names_the_first_rod_to_fail(app, monkeypatch):
    from apps.truss import truss_app_play as tp
    app._load_library_example('warren')
    app._run_analysis(quiet=True)
    gov = td.governing(app.rod_checks)
    # run the clock by hand: one tick per tenth of the play
    clock = [0.0]
    monkeypatch.setattr(tp.time, 'perf_counter', lambda: clock[0])
    monkeypatch.setattr(app.root, 'after', lambda ms, fn: 'job')
    assert app._play_load()
    for i in range(1, 11):
        clock[0] = tp.PLAY_SECONDS * i / 10
        app._play_tick()
    assert app._play is None
    assert app.load_pct.get() == 100
    msg = app.status_var.get()
    assert 'rod %d reached its capacity' % gov[0] in msg
    pct = 100 / gov[1]['util']
    assert ('about %.0f %%' % pct) in msg


def test_play_load_on_a_passing_truss_reports_its_reserve(app, monkeypatch):
    from apps.truss import truss_app_play as tp
    app._load_library_example('fink')
    clock = [0.0]
    monkeypatch.setattr(tp.time, 'perf_counter', lambda: clock[0])
    monkeypatch.setattr(app.root, 'after', lambda ms, fn: 'job')
    app._play_load()
    clock[0] = tp.PLAY_SECONDS
    app._play_tick()
    assert 'no rod reached its capacity' in app.status_var.get()


def test_the_best_score_is_kept_per_example(app):
    app._load_library_example('pratt')
    app._run_analysis(quiet=True)
    first = app.best_scores['pratt']['mass_kg']
    # lighter diagonals that still pass
    app._set_family_section('Diagonal', 'CHS 48.3x3.2', tx.STEEL)
    app._run_analysis(quiet=True)
    assert app._last_score['passes'] is True
    assert app.best_scores['pratt']['mass_kg'] < first
    assert 'New best for this example' in app.res_var.get()
    # a failing design never becomes the best
    app._set_family_section('Vertical', 'L 25x3', tx.STEEL)
    app._run_analysis(quiet=True)
    assert app._last_score['passes'] is False
    assert app.best_scores['pratt']['mass_kg'] <= first


def test_variants_keep_three_and_compare_at_one_scale(app):
    assert app._keep_variant() is None                # nothing solved
    for k in ('pratt', 'howe', 'fink', 'warren'):
        app._load_library_example(k)
        app._run_analysis(quiet=True)
        app._keep_variant()
    assert [v['name'] for v in app.variants] == ['Variant 2', 'Variant 3',
                                                 'Variant 4']
    win = app._compare_variants()
    assert len(win.canvases) == 3
    for c in win.canvases:
        assert c.find_all()
    win.destroy()


def test_a_variant_is_not_kept_at_part_load(app):
    app._load_library_example('pratt')
    app._run_analysis(quiet=True)
    app.load_pct.set(50)
    app._apply_slide()
    assert app._keep_variant() is None
    assert 'Load % back to 100' in app.status_var.get()
