"""The large-model protocol, run automatically on a ~100-member bridge.

Asked for on 13-10-26: "build a protocol for structures with around a
hundred elements, maybe test an example and provide me with the pdf and
excel so i can reproduce it too". The protocol is written out in
REPORTS AND GUIDES/LARGE_MODEL_PROTOCOL_v32_t12_2026-10-13.md; these are
its steps as assertions, on the K-truss bridge of apps/truss/truss_large
(64 m, 50 joints, 97 members), so a change that breaks the tab for a big
model fails here first.
"""
import gc
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.truss import truss_design as td
from apps.truss import truss_large as tl
from apps.truss import truss_stability as tstab
from apps.truss.truss_math import analyze, compute_diagrams


def _solve(rigid=False):
    m = tl.k_truss_bridge(rigid=rigid)
    t0 = time.perf_counter()
    res, err = analyze(m['nodes'], m['rods'], m['loads'], m['supports'])
    took = time.perf_counter() - t0
    assert err is None, err
    dg = compute_diagrams(m['nodes'], m['rods'], m['loads'], res)
    ch = td.check_rods(m['nodes'], m['rods'], m['profiles'], res, dg)
    return m, res, dg, ch, took


# ── step 1: before analysing -- the size and the stability line ──────────
def test_the_bridge_is_the_size_the_protocol_is_for():
    m = tl.k_truss_bridge()
    assert len(m['rods']) == 97 and len(m['nodes']) == 50
    assert len(m['loads']) == 15


def test_the_stability_line_says_determinate_before_any_solve():
    m = tl.k_truss_bridge()
    st = tstab.check(m['nodes'], m['rods'], m['supports'], None)
    assert st['verdict'] == 'determinate'
    assert '97 + 3 − 2×50 = 0' in st['text']


def test_an_odd_panel_count_is_refused_rather_than_built_wrong():
    with pytest.raises(ValueError):
        tl.k_truss_bridge(panels=15)


# ── step 2: the solve, and the numbers checked by hand ───────────────────
def test_it_solves_in_well_under_a_second():
    *_rest, took = _solve()
    assert took < 1.0, '%.2f s for 97 members' % took


def test_the_reactions_carry_the_whole_load_half_each():
    m, res, *_ = _solve()
    hand = tl.hand_checks()
    ry = [-r['ry'] for r in res['reactions'].values()]
    assert sum(ry) == pytest.approx(hand['total_load'])
    assert ry == pytest.approx([hand['reaction']] * 2)


def test_the_biggest_chord_force_is_m_over_d():
    m, res, *_ = _solve()
    hand = tl.hand_checks()
    rr = res['rod_res']
    chords = [i for i, r in enumerate(m['rods'])
              if r['profile'] in ('Top chord', 'Bottom chord')]
    assert max(rr[i]['force'] for i in chords) == pytest.approx(hand['chord'])
    assert min(rr[i]['force'] for i in chords) == pytest.approx(-hand['chord'])


def test_the_end_post_carries_the_reaction():
    m, res, *_ = _solve()
    posts = [abs(res['rod_res'][i]['force'])
             for i, r in enumerate(m['rods']) if r['profile'] == 'End post']
    assert max(posts) == pytest.approx(tl.hand_checks()['end_post'])


def test_a_symmetric_bridge_under_symmetric_load_has_mirrored_forces():
    m, res, *_ = _solve()
    pts = [tuple(p) for p in m['nodes']]
    xs = [p[0] for p in pts]
    mid = (min(xs) + max(xs)) / 2
    mirror = {i: pts.index((2 * mid - x, y)) for i, (x, y) in enumerate(pts)}
    key = {frozenset((r['a'], r['b'])): k for k, r in enumerate(m['rods'])}
    rr = res['rod_res']
    for k, r in enumerate(m['rods']):
        twin = key[frozenset((mirror[r['a']], mirror[r['b']]))]
        assert rr[k]['force'] == pytest.approx(rr[twin]['force'], abs=1e-6)


def test_every_family_passes_and_the_deflection_is_within_l_300():
    m, res, dg, ch, _ = _solve()
    assert all(c['checked'] and c['ok'] for c in ch)
    assert max(c['util'] for c in ch) < 0.8
    d = td.deflection(m['nodes'], m['supports'], res['node_res'])
    assert d['ok']


def test_rigid_joints_change_the_chords_by_under_one_percent():
    """A deep, triangulated truss carries its load by axial force even
    with welded joints: the reason the pinned model is a fair one."""
    m, res, *_ = _solve()
    mr, rres, *_ = _solve(rigid=True)
    a = max(abs(r['force']) for r in res['rod_res'])
    b = max(abs(r['force']) for r in rres['rod_res'])
    assert abs(b - a) / a < 0.01


# ── step 3: the report ────────────────────────────────────────────────────
def _framed(monkeypatch, tmp_path, rigid=False, **kw):
    pytest.importorskip('matplotlib')
    from apps.truss import truss_pdf as tp
    m, res, dg, ch, _ = _solve(rigid)
    seen = {}
    real = tp._Report.frame

    def spy(self):
        real(self)
        seen['rep'] = self
    monkeypatch.setattr(tp._Report, 'frame', spy)
    out = tp.export_pdf(str(tmp_path / 'bridge.pdf'), m['nodes'], m['rods'],
                        m['supports'], m['loads'], res, ch, m['profiles'],
                        title='K-truss bridge', diagrams=dg, **kw)
    return tp, seen['rep'], out


def test_the_bridge_is_drawn_as_a_slender_truss(monkeypatch, tmp_path):
    tp, rep, _out = _framed(monkeypatch, tmp_path, buckling=False)
    assert rep.slender
    assert rep.ann < rep.span, 'arrows and margins still sized off 64 m'


def test_the_drawing_uses_most_of_the_sheet_width(monkeypatch, tmp_path):
    """Sized off the span, the margins left the bridge 60 % of the sheet
    wide; the hundred labels need the width."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    tp, rep, _out = _framed(monkeypatch, tmp_path, buckling=False)
    fig = next(f for f, h in rep.sheets if h == 'Axial forces')
    FigureCanvasAgg(fig).draw()
    ax = max(fig.axes, key=lambda a: len(a.lines))
    (x0, _y0), (x1, _y1) = ax.transData.transform(
        [(rep.box[0], 0), (rep.box[1], 0)])
    width = fig.get_size_inches()[0] * fig.dpi
    assert (x1 - x0) / width > 0.70


def test_overlapping_labels_are_left_out_and_counted(monkeypatch, tmp_path):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    tp, rep, _out = _framed(monkeypatch, tmp_path, buckling=False)
    fig = next(f for f, h in rep.sheets if h == 'Axial forces')
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    r = canvas.get_renderer()
    ax = max(fig.axes, key=lambda a: len(a.texts))
    shown = [t.get_window_extent(r) for t in ax.texts
             if t.get_visible() and t.get_gid() != 'declutter'
             and t.get_text().strip()]
    for i, a in enumerate(shown):
        for b in shown[i + 1:]:
            assert not a.overlaps(b), 'two labels still print on each other'
    note = [t.get_text() for t in ax.texts if t.get_gid() == 'declutter']
    assert note and 'Rods table' in note[0]


def test_the_rigid_report_fits_its_sheets_and_its_cover(monkeypatch,
                                                        tmp_path):
    """The rigid bridge is the heaviest report there is: 21 sheets, with
    Joints and Rod detail running to several each. One export, two
    checks, because it takes twenty seconds:

    - nothing on any sheet runs into the header band or the footer;
    - the contents fit the cover -- listed one by one they ran off it, so
      runs of the same sheet are one entry now.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    tp, rep, out = _framed(monkeypatch, tmp_path, rigid=True,
                           buckling=False)
    lo, hi = tp._Report.FOOTER[1], tp._Report.BAND[0]
    for fig, heading in rep.sheets:
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        r = canvas.get_renderer()
        h = fig.get_size_inches()[1] * fig.dpi
        boxes = [t.get_window_extent(r) for t in fig.texts
                 if t.get_zorder() < 10 and t.get_text()]
        for ax in fig.axes:
            boxes.append(ax.get_window_extent(r))
            boxes += [tab.get_window_extent(r) for tab in ax.tables]
        for bb in boxes:
            assert bb.y0 / h >= lo - 0.004, heading
            if heading != 'Cover':
                assert bb.y1 / h <= hi + 0.004, heading
    assert out['sheets'] >= 18
    entries = tp._group_contents(out['headings'][1:])
    assert len(entries) <= 14
    assert any('Rod detail · ' in e for _n, e in entries)


# ── step 4: the Excel round trip, through the tab ────────────────────────
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
    m = tl.k_truss_bridge()
    a.nodes, a.rods, a.profiles = list(m['nodes']), m['rods'], m['profiles']
    a.supports, a.loads = m['supports'], m['loads']
    try:
        yield a
    finally:
        root.destroy()
        gc.collect()


def _signature(app):
    return ([tuple(map(float, n)) for n in app.nodes],
            [(r['a'], r['b'], r['profile'], r.get('conn', 'pin'))
             for r in app.rods],
            [(l['node'], l['fx'], l['fy']) for l in app.loads],
            [(s['node'], s['type']) for s in app.supports],
            sorted(app.profiles))


def test_the_excel_file_rebuilds_the_same_bridge(app, tmp_path,
                                                 monkeypatch):
    pytest.importorskip('openpyxl')
    from tkinter import filedialog
    app._run_analysis(quiet=True)
    before = _signature(app)
    forces = [r['force'] for r in app.results['rod_res']]
    path = str(tmp_path / 'K-truss bridge 64 m.xlsx')
    monkeypatch.setattr(filedialog, 'asksaveasfilename', lambda **k: path)
    monkeypatch.setattr(filedialog, 'askopenfilename', lambda **k: path)
    app._export_excel()
    app._clear_all(push_undo=False)
    app._import_excel()
    assert _signature(app) == before
    app._run_analysis(quiet=True)
    assert [r['force'] for r in app.results['rod_res']] == \
        pytest.approx(forces, abs=1e-9)
    assert app._report_title() == 'K-truss bridge 64 m', (
        'an imported model is named after its file')


def test_the_tab_traces_a_load_across_the_bridge(app):
    app._run_analysis(quiet=True)
    app.show_load_path.set(True)
    app._toggle_load_path()
    assert len(app.lp_box['values']) == 15
    first = app._lp_choices[0]
    app._trace_load_at(first)
    shares = app._lp['supports']
    assert sum(shares.values()) == pytest.approx(1.0)
    # the load nearest the pin goes mostly to the pin: 15/16 of it
    assert max(shares.values()) == pytest.approx(15 / 16, abs=1e-6)
