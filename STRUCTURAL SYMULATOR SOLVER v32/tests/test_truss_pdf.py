"""The Truss tab's PDF report (apps/truss/truss_pdf): the sheets it
promises, drawings to scale, numbers that balance."""
import gc
import math
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
    for h in ('Cover', 'Geometry', 'Axial forces', 'Deflection and stress',
              'Reactions', 'Rods'):
        assert h in heads
    assert heads[0] == 'Cover', (
        'the cover reports on what the other sheets found, so it is built '
        'last -- but it must still be printed first')
    # the explain pages are for the most used rods
    ranked = sorted(range(len(ch)), key=lambda i: -ch[i]['util'])
    assert out['explained'] == ranked[:tp.EXPLAIN_RODS]
    assert any(h.startswith('Explain rod')
               and str(ranked[0]) in h for h in heads)


def test_a_long_rod_table_runs_onto_more_sheets(tmp_path, monkeypatch):
    """Two tables of ROWS_PER_SHEET to a sheet, side by side: the table
    is under half the sheet's width, and one per sheet left the right
    half empty."""
    monkeypatch.setattr(tp, 'ROWS_PER_SHEET', 5)
    m, res, ch = _solved('pratt')               # 17 rods, 10 a sheet -> 2
    out = tp.export_pdf(str(tmp_path / 'r.pdf'), m['nodes'], m['rods'],
                        m['supports'], m['loads'], res, ch, m['profiles'],
                        buckling=False)
    assert sum(1 for h in out['headings'] if h.startswith('Rods')) == 2


def test_the_two_rod_tables_on_a_sheet_do_not_overlap(tmp_path, monkeypatch):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    monkeypatch.setattr(tp, 'ROWS_PER_SHEET', 9)
    m, res, ch = _solved('pratt')               # 17 rods: 9 left, 8 right
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    assert rep.rod_table() == 1
    fig = rep.sheets[0][0]
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    boxes = [tab.get_window_extent(canvas.get_renderer())
             for ax in fig.axes for tab in ax.tables]
    assert len(boxes) == 2
    left, right = sorted(boxes, key=lambda b: b.x0)
    assert left.x1 <= right.x0, 'the two halves of the rod table overlap'


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
    rep.deflection_and_stress()
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
    # Geometry, forces, the deformed panel and reactions -- four
    # equal-aspect drawings. (The two graphs on the Deflection sheet are
    # plots, not drawings, so they are not equal-aspect and are skipped
    # by the `get_aspect() != 1.0` test above.)
    assert checked == 4


def test_the_deformed_sheet_says_its_magnification():
    m, res, ch = _solved('pratt')
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    rep.deflection_and_stress()
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


def _flat(fig):
    """Every string on a sheet with its wrapping collapsed.

    The captions are hard-wrapped (matplotlib's own wrap=True runs over
    the drawn frame), so a sentence asserted here spans two strings
    joined by a newline unless the whitespace is squashed first."""
    return ' '.join(' '.join(_texts(fig)).split())


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


# ═════════════════════════════════════════════════════════════════════════════
#  Everything Analyze produces, in as few sheets as it takes
#
#  Asked for on 11-10-26: "all features of the analyze button to be in the
#  document, but trying to use the least amount of pages". Four of the
#  things ▶ Analyze computes -- the shear and moment diagrams, the fibre
#  stress, the stability verdict and the plate checks -- were not in the
#  report at all, while the sheets that were there had one subject each
#  whether or not it had anything to say.
# ═════════════════════════════════════════════════════════════════════════════
def _bending_model():
    """A model where rods actually bend, so the V/M sheets have content."""
    m = tx.get('vierendeel')[1]
    res, err = analyze(m['nodes'], m['rods'], m['loads'], m['supports'],
                       m.get('plates'))
    assert err is None
    dg = compute_diagrams(m['nodes'], m['rods'], m['loads'], res)
    ch = td.check_rods(m['nodes'], m['rods'], m['profiles'], res, dg)
    return m, res, ch, dg


def _thumbnails(fig, m):
    """The axes on a sheet that are position thumbnails: every other rod
    in the thumbnail grey, and one in the thumbnail red."""
    rest, rod = tp._Report.THUMB_REST, tp._Report.THUMB_ROD
    return [a for a in fig.axes
            if sum(1 for l in a.lines if l.get_color() == rest)
            == len(m['rods']) - 1
            and sum(1 for l in a.lines if l.get_color() == rod) == 1]


def _report(m, res, ch, dg=None, **kw):
    return tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                      ch, m['profiles'], 'r', None, diagrams=dg, **kw)


def test_a_pinned_truss_does_not_pay_for_sheets_that_would_be_blank(tmp_path):
    """The whole "least amount of pages" instruction, as one assertion.

    A classic truss -- every rod pinned, every load at a joint -- has no
    shear and no moment anywhere. Shear, Moment and the per-rod cards
    would be flat zero lines on three or four sheets, burying the ones
    that say something."""
    m, res, ch = _solved('pratt')
    out = tp.export_pdf(str(tmp_path / 'r.pdf'), m['nodes'], m['rods'],
                        m['supports'], m['loads'], res, ch, m['profiles'])
    heads = out['headings']
    assert 'Shear V' not in heads
    assert 'Moment M' not in heads
    assert not any(h.startswith('Rod detail') for h in heads)
    assert out['rod_detail'] == []
    assert out['sheets'] <= 10, heads


def test_a_bending_model_gets_all_three_and_says_so(tmp_path):
    m, res, ch, dg = _bending_model()
    out = tp.export_pdf(str(tmp_path / 'r.pdf'), m['nodes'], m['rods'],
                        m['supports'], m['loads'], res, ch, m['profiles'],
                        diagrams=dg, plates=m.get('plates'))
    heads = out['headings']
    assert 'Shear V' in heads and 'Moment M' in heads
    assert any(h.startswith('Rod detail') for h in heads)
    assert out['rod_detail']
    assert _pages(tmp_path / 'r.pdf') == out['sheets']


def test_shear_and_moment_get_a_sheet_each_not_half_a_sheet(tmp_path):
    """The tab draws them side by side, which halves the width each
    gets. On a long truss that is the difference between reading a lobe
    and guessing at it, and on paper there is no reason to pay it."""
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    rep.shear()
    rep.moment()
    assert [h for _f, h in rep.sheets] == ['Shear V', 'Moment M']
    for fig, _h in rep.sheets:
        # one drawing axes per sheet, the whole width
        big = [ax for ax in fig.axes if ax.get_position().width > 0.8]
        assert len(big) == 1


def test_the_bands_are_drawn_and_the_biggest_is_labelled():
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    hit = rep.moment()
    assert hit, 'no rod carries a moment in a model chosen for bending'
    fig = _fig(rep, 'Moment M')
    ax = next(a for a in fig.axes if a.get_position().width > 0.8)
    assert ax.patches, 'no moment band was drawn'
    assert str(hit[0]) in _flat(fig)


# ── one sheet for deflection and stress ───────────────────────────────────
def test_deflection_and_stress_is_one_sheet_with_three_graphs():
    """They were a drawing, a number buried in a caption, and nothing at
    all for the stress. They answer each other, so they share a page."""
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    rep.deflection_and_stress()
    assert [h for _f, h in rep.sheets] == ['Deflection and stress']
    fig = rep.sheets[0][0]
    said = ' '.join(_texts(fig))
    assert 'Elastic deformation' in said
    assert 'Fibre stress' in said
    assert 'Deflected shape' in said
    # the drawing plus the two graphs
    assert len([a for a in fig.axes if a.get_position().width > 0.1]) >= 3


def test_the_three_graphs_are_divided_by_rules():
    """A line and not just white space: without it the eye reads the
    axis label of the graph below as the caption of the picture above."""
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    rep.deflection_and_stress()
    fig = rep.sheets[0][0]
    lines = [a for a in fig.artists if a.__class__.__name__ == 'Line2D']
    assert len(lines) >= 2, 'the dividers are missing'
    horiz = [l for l in lines if l.get_ydata()[0] == l.get_ydata()[1]]
    vert = [l for l in lines if l.get_xdata()[0] == l.get_xdata()[1]]
    assert horiz and vert


def test_the_elastic_curve_shows_every_joint_against_the_limit():
    """One number cannot show whether a truss sags evenly or dips at one
    panel point, which is the difference between a member that is too
    small and a truss that is too shallow."""
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    rep.deflection_and_stress()
    fig = rep.sheets[0][0]
    ax = next(a for a in fig.axes
              if 'position along the span' in a.get_xlabel())
    curve = next(l for l in ax.lines if len(l.get_xdata()) == len(m['nodes']))
    assert len(curve.get_ydata()) == len(m['nodes'])
    assert any(l.get_linestyle() == '--' for l in ax.lines), (
        'the L/300 limit is not drawn')


def test_the_fibre_panel_says_a_pinned_rod_has_no_bending_to_show():
    m, res, ch = _solved('pratt')
    rep = _report(m, res, ch, compute_diagrams(m['nodes'], m['rods'],
                                               m['loads'], res))
    rep.deflection_and_stress()
    assert 'its two fibres carry the same' in _flat(rep.sheets[0][0])


# ── the per-rod cards ─────────────────────────────────────────────────────
def test_every_rod_card_carries_a_thumbnail_locating_the_rod():
    """"Rod 13 is at 0.63" is a sentence about a rod the reader cannot
    place without counting along the Geometry sheet."""
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    shown = rep.rod_detail()
    assert shown
    fig = _fig(rep, [h for _f, h in rep.sheets][0])
    # a thumbnail draws every rod, so its axes has len(rods) lines
    thumbs = _thumbnails(fig, m)
    assert thumbs, 'no row has a thumbnail of the truss'
    for t in thumbs:
        red = [l for l in t.lines if l.get_color() == tp._Report.THUMB_ROD]
        assert len(red) == 1, 'a row does not pick out exactly one rod'
    assert len(thumbs) == min(len(shown),
                              tp._Report.DETAIL_ROWS * tp._Report.DETAIL_COLS)


def test_a_rod_row_carries_its_own_shear_and_moment():
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    shown = rep.rod_detail()
    fig = rep.sheets[0][0]
    said = _flat(fig)
    assert 'Shear V (' in said and 'Moment M (' in said
    # two filled diagrams per row
    filled = [a for a in fig.axes if a.collections]
    assert len(filled) == 2 * min(len(shown), 16)


def test_the_cards_are_ordered_worst_first():
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    order = rep.rod_detail()
    peaks = [max((abs(v) for v in list(dg[i].get('M', ()))
                  + list(dg[i].get('V', ()))), default=0.0) for i in order]
    assert peaks == sorted(peaks, reverse=True)


def test_rods_that_carry_nothing_get_no_card():
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    order = rep.rod_detail()
    for i in range(len(m['rods'])):
        flat = max((abs(v) for v in list(dg[i].get('M', ()))
                    + list(dg[i].get('V', ()))), default=0.0) <= 1e-9
        assert (i not in order) == flat


# ── the explain sheets, grouped ───────────────────────────────────────────
def test_two_rods_share_an_explain_sheet_with_their_thumbnails():
    """It was one rod per sheet: a column of monospace down the left half
    of a landscape A4 with the right half empty."""
    m, res, ch = _solved('pratt')
    rep = _report(m, res, ch)
    chosen = rep.explain()
    assert len(chosen) == 2
    assert len(rep.sheets) == 1, 'two rods still take two sheets'
    fig = rep.sheets[0][0]
    said = ' '.join(_texts(fig))
    for i in chosen:
        assert 'Rod %d' % i in said
    assert len(_thumbnails(fig, m)) == 2, (
        'each column needs its own thumbnail')


def test_an_explain_column_never_runs_under_the_title_block():
    """The RIGHT column sits over the title block's x range, so a column
    that runs past it loses its last lines behind it."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from apps.stereo import stereo_reports as sr
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    rep.explain()
    fig = rep.sheets[0][0]
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    _w, h = fig.get_size_inches() * fig.dpi
    tb_top = sr.PDF_FRAME[1] + sr.PDF_TITLE_H
    for t in fig.texts:
        bb = t.get_window_extent(canvas.get_renderer())
        if bb.x0 / (fig.get_size_inches()[0] * fig.dpi) > 0.45:
            assert bb.y0 / h >= tb_top - 0.02, (
                'an explain column runs into the title block')


# ── the cover carries the verdict ─────────────────────────────────────────
def test_the_cover_reports_what_analyze_said():
    """A reader who only ever sees page one should see what the app
    said: the stability verdict and the plate checks were nowhere in the
    report at all."""
    m, res, ch, dg = _bending_model()
    from apps.truss import truss_stability as tstab
    st = tstab.check(m['nodes'], m['rods'], m['supports'], m.get('plates'))
    rep = _report(m, res, ch, dg, plates=m.get('plates'), stability=st)
    rep.buckling_factors = [2.5]
    rep.cover(['Geometry'])
    said = _flat(rep.sheets[0][0])
    assert 'Stability' in said
    assert ' '.join(st['text'][:30].split()) in said
    assert 'Most used rod' in said
    assert 'λ₁ = 2.50' in said
    assert 'Shear and moment' in said


def test_the_cover_says_why_a_pinned_truss_has_fewer_sheets():
    m, res, ch = _solved('pratt')
    rep = _report(m, res, ch, compute_diagrams(m['nodes'], m['rods'],
                                               m['loads'], res))
    rep.cover(['Geometry'])
    assert 'the axial force is the whole result' in _flat(rep.sheets[0][0])


def test_the_cover_lists_the_sheets_that_were_actually_built(tmp_path):
    """It used to list a fixed menu written before the report was, which
    is how it came to promise sheets the report did not have."""
    m, res, ch, dg = _bending_model()
    out = tp.export_pdf(str(tmp_path / 'r.pdf'), m['nodes'], m['rods'],
                        m['supports'], m['loads'], res, ch, m['profiles'],
                        diagrams=dg, plates=m.get('plates'))
    rep_heads = out['headings'][1:]          # everything after the cover
    assert rep_heads, 'no body sheets'
    assert len(set(rep_heads)) == len(rep_heads), 'a heading is repeated'


def test_a_model_with_no_plates_gets_no_plate_sheet(tmp_path):
    m, res, ch = _solved('pratt')
    out = tp.export_pdf(str(tmp_path / 'r.pdf'), m['nodes'], m['rods'],
                        m['supports'], m['loads'], res, ch, m['profiles'])
    assert 'Plates' not in out['headings']


def test_a_plate_sheet_never_hides_the_buckling_utilisation():
    """A thin plate buckles long before it yields, so a comfortable tau
    shown on its own is the most misleading output this feature has."""
    m, res, ch = _solved('pratt')
    plate = {'kind': 'panel', 'nodes': [0, 1, 2], 't_mm': 6.0}
    chk = {'valid': True, 't_mm': 6.0, 'util_yield': 0.21,
           'util_buckling': 1.35, 'util': 1.35, 'governing': 'shear buckling'}
    rep = _report(m, res, ch, plates=[plate], plate_checks=[chk])
    assert rep.plate_table() == 1
    fig = _fig(rep, 'Plates')
    cells = [t.get_text() for ax in fig.axes for tab in ax.tables
             for t in [c.get_text() for c in tab.get_celld().values()]]
    assert '1.35' in cells and '0.21' in cells
    assert 'OVER' in cells
    assert 'Buckling' in cells
    assert 'buckling' in _flat(fig).lower()


def test_an_unchecked_plate_says_why_instead_of_a_blank_row():
    m, res, ch = _solved('pratt')
    plate = {'kind': 'panel', 'nodes': [0, 1, 2]}
    rep = _report(m, res, ch, plates=[plate],
                  plate_checks=[{'valid': False, 'reason': 'panel not solved'}])
    rep.plate_table()
    cells = [t.get_text() for ax in _fig(rep, 'Plates').axes
             for tab in ax.tables
             for t in [c.get_text() for c in tab.get_celld().values()]]
    assert 'panel not solved' in cells



# ═════════════════════════════════════════════════════════════════════════════
#  Scale: the screen's proportions, whatever the size of the model
#
#  Reported 11-10-26 after t 06: "the graphs of the rods and in the
#  vierendeel case ... are too big ... I prefer similar scales to the ones
#  in the display". They were. The Vierendeel lobes reached 10 % of the
#  span where the screen draws them at 3.6-5.1 %, and the per-rod charts
#  were a seventh of the sheet wide and a sixth tall each.
# ═════════════════════════════════════════════════════════════════════════════
def _vierendeel_bays(bays, bay=3.0, h=2.5):
    from common import PX_PER_M
    base = tx.get('vierendeel')[1]
    rod = {k: base['rods'][0][k] for k in ('E', 'A', 'I', 'profile', 'conn')}
    nodes = ([[i * bay * PX_PER_M, 0.0] for i in range(bays + 1)]
             + [[i * bay * PX_PER_M, -h * PX_PER_M] for i in range(bays + 1)])
    top = lambda i: bays + 1 + i
    rods = []
    for i in range(bays):
        rods += [dict(rod, a=i, b=i + 1), dict(rod, a=top(i), b=top(i + 1))]
    rods += [dict(rod, a=i, b=top(i)) for i in range(bays + 1)]
    m = dict(nodes=nodes, rods=rods, profiles=base['profiles'],
             loads=[{'node': top(i), 'fx': 0, 'fy': 12}
                    for i in range(1, bays)],
             supports=[{'node': 0, 'type': 'pin'},
                       {'node': bays, 'type': 'rollerX'}])
    res, err = analyze(m['nodes'], m['rods'], m['loads'], m['supports'])
    assert err is None
    dg = compute_diagrams(m['nodes'], m['rods'], m['loads'], res)
    ch = td.check_rods(m['nodes'], m['rods'], m['profiles'], res, dg)
    return m, res, ch, dg


@pytest.mark.parametrize('bays', [1, 4, 12])
def test_a_lobe_reaches_the_screen_s_proportion_not_more(bays):
    """At most 4 % of the span (the screen measured 3.6-5.1 %) and at
    most 20 % of the typical member, so that a truss of many short bays
    does not get lobes wider than a bay."""
    m, res, ch, dg = _vierendeel_bays(bays)
    rep = _report(m, res, ch, dg)
    reach = rep.band_reach()
    lens = sorted(td.rod_length_m(m['nodes'], r) for r in m['rods'])
    median = lens[len(lens) // 2]
    assert reach <= 0.040 * rep.span + 1e-9
    assert reach <= 0.20 * median + 1e-9
    assert reach > 0


def test_the_biggest_lobe_drawn_is_the_reach_and_no_further():
    """Measured on the drawing, not read off the formula: the moment
    sheet's biggest lobe, measured perpendicular to its OWN member (a
    lobe at a joint touches the next member, so distance to the nearest
    member would read zero there)."""
    from matplotlib.figure import Figure
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    peak = rep._peak('M')
    ri = max(range(len(dg)), key=lambda i: max(
        (abs(v) for v in dg[i].get('M', ())), default=0.0))
    ax = Figure().add_subplot()
    rep.draw_band(ax, ri, list(dg[ri]['M']), list(dg[ri]['xs']),
                  rep.band_reach() / peak, '#9fc0e0', '#2c5f9e')
    rod = m['rods'][ri]
    (xa, ya), (xb, yb) = rep.pts[rod['a']], rep.pts[rod['b']]
    L = math.hypot(xb - xa, yb - ya)
    far = 0.0
    for poly in ax.patches:
        for x, y in poly.get_xy():
            far = max(far, abs((x - xa) * (yb - ya) - (y - ya) * (xb - xa)) / L)
    assert far == pytest.approx(rep.band_reach(), rel=0.01)


def test_a_rod_detail_panel_has_the_screen_s_proportions():
    """The tab's own V and M panels are 330 by 128 px, 2.6 : 1. The first
    rod cards were 1.6 : 1 and the single-column rows 4.3 : 1."""
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    rep.rod_detail()
    fig = rep.sheets[0][0]
    W, H = fig.get_size_inches()
    panels = [a for a in fig.axes if a.collections]
    assert panels
    for a in panels:
        b = a.get_position()
        ratio = (b.width * W) / (b.height * H)
        assert 2.0 <= ratio <= 3.2, 'a panel is %.1f : 1' % ratio
        # and small: well under a tenth of the sheet each
        assert b.width * b.height < 0.012


def test_sixteen_rods_fit_one_rod_detail_sheet():
    m, res, ch, dg = _vierendeel_bays(6)       # 6 bays: 19 rods
    rep = _report(m, res, ch, dg)
    shown = rep.rod_detail()
    per = tp._Report.DETAIL_ROWS * tp._Report.DETAIL_COLS
    assert per == 16
    assert len(rep.sheets) == -(-len(shown) // per)


def test_the_thumbnail_rod_stands_out_from_the_rest():
    """"the pictures of the references of position of the rods need more
    contrast". The rest of the truss was #cdd3d8 at 0.7 pt against the
    rod at 2 pt: on paper the truss was barely there."""
    def lum(hexcol):
        r, g, b = (int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    rest, rod = tp._Report.THUMB_REST, tp._Report.THUMB_ROD
    assert lum(rest) < 0.55, 'the rest of the truss is too pale to read'
    r, g, b = (int(rod[i:i + 2], 16) for i in (1, 3, 5))
    assert r > 200 and g < 40 and b < 60, 'the rod is not a strong red'

    m, res, ch = _solved('pratt')
    from matplotlib.figure import Figure
    ax = Figure().add_subplot()
    rep = _report(m, res, ch)
    rep.thumbnail(ax, 3)
    reds = [l for l in ax.lines if l.get_color() == rod]
    greys = [l for l in ax.lines if l.get_color() == rest]
    assert len(reds) == 1
    assert reds[0].get_linewidth() >= 2.5 * greys[0].get_linewidth()
    assert reds[0].get_zorder() > max(l.get_zorder() for l in greys), (
        'the rod must be drawn on top, or a crossing member hides it')
    casing = [l for l in ax.lines if l.get_color() == 'white']
    assert casing and casing[0].get_zorder() < reds[0].get_zorder()


def test_a_mechanism_says_why_there_is_no_report(app, tmp_path):
    """"Analyze the truss first" to someone who just did sends them round
    in a circle. The One Diagonal Missing example exists to land here."""
    app._load_library_example('missing_diagonal')
    app._run_analysis(quiet=True)
    assert app.results is None, 'the fixture is meant to be a mechanism'
    out = app._export_pdf_report(str(tmp_path / 'r.pdf'))
    assert out is None
    assert not (tmp_path / 'r.pdf').exists()
    assert 'mechanism' in app.status_var.get()
