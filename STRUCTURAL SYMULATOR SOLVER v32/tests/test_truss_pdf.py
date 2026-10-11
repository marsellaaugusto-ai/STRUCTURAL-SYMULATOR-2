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


# ═════════════════════════════════════════════════════════════════════════════
#  Utilisation and buckling
#
#  Asked for on 11-10-26: "add to the truss pdf the utilization and the
#  buckling under the three variations of lambda". The rod table already
#  carried a Use column; what was missing was the PICTURE of it, and
#  buckling was not in the report at all.
# ═════════════════════════════════════════════════════════════════════════════
def _fig(rep, heading):
    return next(f for f, h in rep.sheets if h == heading)


def _texts(fig):
    out = [t.get_text() for t in fig.texts]
    for ax in fig.axes:
        out.append(ax.get_title())
        out.extend(t.get_text() for t in ax.texts)
    return [t for t in out if t]


def test_the_report_carries_a_utilisation_and_a_buckling_sheet(tmp_path):
    m, res, ch = _solved('pratt')
    out = tp.export_pdf(str(tmp_path / 'r.pdf'), m['nodes'], m['rods'],
                        m['supports'], m['loads'], res, ch, m['profiles'])
    assert 'Utilisation' in out['headings']
    assert 'Buckling' in out['headings']
    assert _pages(tmp_path / 'r.pdf') == out['sheets']


def test_the_utilisation_sheet_ranks_the_rods_worst_first(tmp_path):
    m, res, ch = _solved('pratt')
    out = tp.export_pdf(str(tmp_path / 'r.pdf'), m['nodes'], m['rods'],
                        m['supports'], m['loads'], res, ch, m['profiles'],
                        buckling=False)
    ranked = out['utilised']
    assert ranked, 'nothing was ranked on a model whose rods are checked'
    utils = [ch[i]['util'] for i in ranked]
    assert utils == sorted(utils, reverse=True)
    assert ranked[0] == td.governing(ch)[0], (
        'the top of the ranking must be the governing rod the rest of the '
        'app names')


def test_the_utilisation_sheet_colours_a_rod_by_how_hard_it_works():
    """The same ramp as the canvas, so a sheet and the screen cannot
    disagree about what amber means."""
    m, res, ch = _solved('pratt')
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    rep.utilisation()
    fig = _fig(rep, 'Utilisation')
    drawn = {tuple(round(v, 4) for v in l.get_color())
             if not isinstance(l.get_color(), str) else l.get_color()
             for ax in fig.axes for l in ax.lines}
    worst = td.governing(ch)[1]['util']
    assert td.util_color(worst) in drawn, (
        'no rod is drawn in the governing rod\'s utilisation colour')
    assert td.util_color(0.0) != td.util_color(1.1)


def test_an_over_capacity_rod_is_named_on_the_utilisation_sheet():
    """A sheet that only colours the problem makes the reader hunt for
    it; this one has to say which rod."""
    m, res, ch = _solved('pratt')
    ch = [dict(c) for c in ch]
    ch[2].update(checked=True, util=1.4, ok=False, governing='made up')
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    rep.utilisation()
    said = ' '.join(_texts(_fig(rep, 'Utilisation')))
    assert 'OVER capacity' in said
    assert 'rod 2' in said.lower()


def test_unchecked_rods_are_counted_rather_than_quietly_left_grey():
    m, res, _ch = _solved('pratt')
    bare = {k: {'E': p['E'], 'A': p['A']} for k, p in m['profiles'].items()}
    ch = td.check_rods(m['nodes'], m['rods'], bare, res)
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, bare, 'p', None)
    assert rep.utilisation() == []
    said = ' '.join(_texts(_fig(rep, 'Utilisation')))
    assert 'No rod is checked' in said and 'grey' in said


# ── buckling ──────────────────────────────────────────────────────────────
def test_three_lambdas_are_reported_each_with_its_own_shape():
    """"the buckling under the three variations of lambda" -- three
    modes, ascending, each drawn and each naming what moves."""
    pytest.importorskip('scipy')
    m, res, ch = _solved('pratt')
    result, curve = tp.buckling_for(m['nodes'], m['rods'], m['supports'],
                                    m['loads'], res)
    assert 'error' not in result, result
    assert len(result['factors']) == 3
    assert result['factors'] == sorted(result['factors'])
    assert len(result['modes']) == len(result['factors'])

    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    got = rep.buckling(result, curve)
    assert got == result['factors'][:3]
    said = ' '.join(_texts(_fig(rep, 'Buckling')))
    for j, lam in enumerate(result['factors'][:3], start=1):
        assert 'Mode %d:  λ = %.2f' % (j, lam) in said, said


def test_a_lambda_below_one_is_called_out_as_such():
    """A truss that buckles before its own load is on is the one case a
    reader must not be able to skim past."""
    pytest.importorskip('scipy')
    m, res, ch = _solved('warren')
    result, curve = tp.buckling_for(m['nodes'], m['rods'], m['supports'],
                                    m['loads'], res)
    assert result['factors'][0] < 1.0, (
        'this fixture is meant to buckle below its own load; it now gives '
        '%.3f, so the test no longer tests what it says' % result['factors'][0])
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'w', None)
    rep.buckling(result, curve)
    said = ' '.join(_texts(_fig(rep, 'Buckling')))
    assert 'BELOW 1' in said


def test_the_sheet_says_lambda_is_an_upper_bound():
    """It is elastic buckling of an ideal truss. A sheet that hands an
    architecture student 3.5 without that sentence is teaching a number
    they will believe."""
    pytest.importorskip('scipy')
    m, res, ch = _solved('pratt')
    result, curve = tp.buckling_for(m['nodes'], m['rods'], m['supports'],
                                    m['loads'], res)
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    rep.buckling(result, curve)
    said = ' '.join(_texts(_fig(rep, 'Buckling')))
    assert 'UPPER bound' in said
    assert 'out of the plane' in said.lower()


def test_equal_lambdas_are_explained_rather_than_left_looking_broken():
    """Four identical compressed members buckle at one load, so the
    report shows the same number three times. That is the reading, not a
    bug, and the sheet has to say so."""
    pytest.importorskip('scipy')
    m, res, ch = _solved('pratt')
    result, curve = tp.buckling_for(m['nodes'], m['rods'], m['supports'],
                                    m['loads'], res)
    f = result['factors']
    assert f[1] <= f[0] * 1.001, (
        'this fixture is meant to be degenerate; it now gives %s' % f)
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    rep.buckling(result, curve)
    said = ' '.join(_texts(_fig(rep, 'Buckling')))
    assert 'modes share that λ' in said


def test_a_truss_with_nothing_in_compression_says_why_instead_of_a_blank():
    m, res, ch = _solved('pratt')
    flat = {'rod_res': [dict(r, force=abs(r['force'])) for r in res['rod_res']],
            'node_res': res['node_res'], 'reactions': res['reactions']}
    result, curve = tp.buckling_for(m['nodes'], m['rods'], m['supports'],
                                    m['loads'], flat)
    assert 'error' in result
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    assert rep.buckling(result, curve) == []
    said = ' '.join(_texts(_fig(rep, 'Buckling')))
    assert 'compression' in said


def test_buckling_can_be_switched_off(tmp_path):
    m, res, ch = _solved('pratt')
    out = tp.export_pdf(str(tmp_path / 'r.pdf'), m['nodes'], m['rods'],
                        m['supports'], m['loads'], res, ch, m['profiles'],
                        buckling=False)
    assert 'Buckling' not in out['headings']
    assert out['buckling'] == []


def test_every_caption_stays_inside_the_drawn_frame():
    """matplotlib's own wrap=True wraps at the FIGURE edge, and these
    sheets have a frame 2.6 % inside it -- an auto-wrapped caption runs
    its first line over the rule and off the paper."""
    pytest.importorskip('scipy')
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from apps.stereo import stereo_reports as sr
    m, res, ch = _solved('pratt')
    result, curve = tp.buckling_for(m['nodes'], m['rods'], m['supports'],
                                    m['loads'], res)
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    rep.utilisation()
    rep.buckling(result, curve)
    _x0, _y0, x1, y1 = sr.PDF_FRAME
    for fig, heading in rep.sheets:
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        w, h = fig.get_size_inches() * fig.dpi
        for t in fig.texts:
            bb = t.get_window_extent(canvas.get_renderer())
            assert bb.x1 / w <= x1 + 0.005, (
                '%s: a caption runs %.3f past the frame'
                % (heading, bb.x1 / w - x1))
            assert bb.y1 / h <= y1 + 0.005, heading
