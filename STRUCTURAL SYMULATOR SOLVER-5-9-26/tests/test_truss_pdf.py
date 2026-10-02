"""The Truss tab's PDF report (apps/truss/truss_pdf): the sheets it
promises, drawings to scale, numbers that balance."""
import gc
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip('matplotlib')

from apps.truss import truss_design as td
from apps.truss import truss_examples as tx
from apps.truss import truss_pdf as tp
from apps.truss.truss_math import analyze, compute_diagrams


def _solved(key):
    m = tx.get(key)[1]
    res, err = analyze(m['nodes'], m['rods'], m['loads'], m['supports'])
    assert err is None
    dg = compute_diagrams(m['nodes'], m['rods'], m['loads'], res)
    ch = td.check_rods(m['nodes'], m['rods'], m['profiles'], res, dg)
    return m, res, ch


def _pages(path):
    return len(re.findall(rb'/Type\s*/Page\b', Path(path).read_bytes()))


def test_the_report_has_every_promised_sheet(tmp_path):
    m, res, ch = _solved('pratt')
    path = tmp_path / 'r.pdf'
    out = tp.export_pdf(str(path), m['nodes'], m['rods'], m['supports'],
                        m['loads'], res, ch, m['profiles'], title='Pratt')
    assert path.read_bytes()[:5] == b'%PDF-'
    assert _pages(path) == out['sheets']
    heads = out['headings']
    for h in ('Cover', 'Geometry', 'Axial forces', 'Deformed shape',
              'Reactions', 'Rods'):
        assert h in heads
    # the explain pages are for the most used rods
    ranked = sorted(range(len(ch)), key=lambda i: -ch[i]['util'])
    assert out['explained'] == ranked[:tp.EXPLAIN_RODS]
    assert 'Explain rod %d' % ranked[0] in heads


def test_a_long_rod_table_runs_onto_more_sheets(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, 'ROWS_PER_SHEET', 5)
    m, res, ch = _solved('pratt')                     # 17 rods -> 4 sheets
    out = tp.export_pdf(str(tmp_path / 'r.pdf'), m['nodes'], m['rods'],
                        m['supports'], m['loads'], res, ch, m['profiles'])
    assert sum(1 for h in out['headings'] if h.startswith('Rods')) == 4


def test_without_sections_there_is_nothing_to_explain(tmp_path):
    m, res, _ch = _solved('pratt')
    bare = {k: {'E': p['E'], 'A': p['A']} for k, p in m['profiles'].items()}
    ch = td.check_rods(m['nodes'], m['rods'], bare, res)
    out = tp.export_pdf(str(tmp_path / 'r.pdf'), m['nodes'], m['rods'],
                        m['supports'], m['loads'], res, ch, bare)
    assert out['explained'] == []
    assert not any(h.startswith('Explain') for h in out['headings'])


def test_it_refuses_an_unsolved_truss(tmp_path):
    m = tx.pratt()
    with pytest.raises(ValueError):
        tp.export_pdf(str(tmp_path / 'r.pdf'), m['nodes'], m['rods'],
                      m['supports'], m['loads'], None, [], m['profiles'])


@pytest.mark.parametrize('key', ['pratt', 'cantilever', 'fink'])
def test_every_drawing_is_to_scale(key):
    """A metre across and a metre up are the same length on the paper,
    on every sheet that draws the truss."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    m, res, ch = _solved(key)
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], key, None)
    rep.geometry()
    rep.forces()
    rep.deformed()
    rep.reactions()
    checked = 0
    for fig, _h in rep.sheets:
        FigureCanvasAgg(fig).draw()
        for ax in fig.axes:
            if ax.get_aspect() != 1.0:
                continue
            (x0, y0), (x1, _), (_, y2) = ax.transData.transform(
                [(0, 0), (1, 0), (0, 1)])
            assert abs(x1 - x0) == pytest.approx(abs(y2 - y0), rel=0.005)
            checked += 1
    assert checked == 4


def test_the_deformed_sheet_says_its_magnification():
    m, res, ch = _solved('pratt')
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    rep.deformed()
    fig = rep.sheets[-1][0]
    texts = [t.get_text() for t in fig.texts]
    assert any('magnified × %g' % rep.deform_factor in t for t in texts)
    assert any('L/300' in t for t in texts)


def test_the_reactions_table_balances_the_loads():
    m, res, ch = _solved('cantilever')
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'c', None)
    rep.reactions()
    fig = rep.sheets[-1][0]
    cells = [t.get_text() for ax in fig.axes for tab in ax.tables
             for t in [c.get_text() for c in tab.get_celld().values()]]
    assert '25.00' in cells                      # Σ Ry = the 25 kN load
    assert not any(c.startswith('-0.00') for c in cells)


# ── from the tab ──────────────────────────────────────────────────────────

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


def test_the_tab_exports_the_full_load_report(app, tmp_path):
    app._load_library_example('howe')
    app._run_analysis(quiet=True)
    app.load_pct.set(30)
    app._apply_slide()
    out = app._export_pdf_report(path=str(tmp_path / 'howe.pdf'))
    assert out is not None and out['sheets'] >= 7
    assert app.load_pct.get() == 100              # the full load, not 30 %
    assert (tmp_path / 'howe.pdf').exists()
    assert 'sheet report' in app.status_var.get()


def test_the_tab_solves_first_when_needed(app, tmp_path):
    app._load_library_example('king_post')
    assert app.results is None
    out = app._export_pdf_report(path=str(tmp_path / 'k.pdf'))
    assert out is not None and app.results is not None
