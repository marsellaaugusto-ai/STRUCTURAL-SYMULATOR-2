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
    # Geometry, forces, reactions, and on the Deflection sheet the elastic
    # line AND the fibre stress drawing -- five equal-aspect drawings. (The
    # two graphs under them are plots, not drawings, so they are not
    # equal-aspect and are skipped by the `get_aspect() != 1.0` test.)
    assert checked == 5


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
    # The node force vectors and rod calculations (asked for on 13-10-26)
    # are content, not blank sheets; they are held to their own budget:
    # eight joints and sixteen rods to a sheet.
    cards = [h for h in heads if h.startswith(('Node force vectors',
                                               'Rod calculations'))]
    assert len(cards) == (-(-len(m['nodes']) // 8)
                          + -(-len(m['rods']) // 16))
    assert out['sheets'] - len(cards) <= 10, heads


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
    said = _flat(fig)
    assert 'Elastic line' in said
    assert 'Deflection along the span' in said
    assert 'Fibre stress' in said
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



# ═════════════════════════════════════════════════════════════════════════════
#  The elastic line, with its points of contraflexure
#
#  Reported 12-10-26 with a screenshot of the canvas: "it still does not
#  have the elastic deformation graph with the contraflexural points". It
#  drew straight segments between the displaced joints -- exact for a pin
#  bar, and for a rigid rod it threw away the S-bend and the M = 0 point
#  the canvas marks with a circle.
# ═════════════════════════════════════════════════════════════════════════════
def test_a_rigid_rod_is_drawn_as_the_curve_it_bends_into():
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    rep.deflection_and_stress()
    ax = rep.sheets[0][0].axes[0]
    green = [l for l in ax.lines if l.get_color() == '#1D9E75'
             and l.get_linestyle() == '-']
    curved = [l for l in green if len(l.get_xdata()) > 2]
    rigid = sum(1 for r in m['rods'] if r.get('conn') == 'rigid')
    assert len(curved) == rigid, (
        '%d rigid rods but %d curves' % (rigid, len(curved)))
    # and it really bends: the middle of some curve is off the chord
    off = 0.0
    for l in curved:
        xs, ys = l.get_xdata(), l.get_ydata()
        (x0, y0), (x1, y1) = (xs[0], ys[0]), (xs[-1], ys[-1])
        L = math.hypot(x1 - x0, y1 - y0) or 1.0
        k = len(xs) // 2
        off = max(off, abs((xs[k] - x0) * (y1 - y0)
                           - (ys[k] - y0) * (x1 - x0)) / L)
    assert off > 1e-3, 'every "curve" is a straight line'


def test_every_contraflexure_point_is_where_the_moment_changes_sign():
    """From the same M(x) the Moment sheet draws, so a circle on the
    elastic line always sits where the moment diagram crosses zero."""
    from apps.truss.truss_math import find_zero_crossings
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    rep.deflection_and_stress()
    pts = rep.flex_points
    assert pts, 'a Vierendeel has double curvature and so contraflexure'
    for ri, t, _xy in pts:
        assert m['rods'][ri].get('conn') == 'rigid'
        assert 0.02 <= t <= 0.98
        crossings = [x / dg[ri]['Lm']
                     for x in find_zero_crossings(dg[ri]['xs'], dg[ri]['M'])]
        assert any(abs(c - t) < 1e-9 for c in crossings)
    ax = rep.sheets[0][0].axes[0]
    circles = [l for l in ax.lines if l.get_marker() == 'o'
               and l.get_markerfacecolor() == 'white']
    assert len(circles) == len(pts)
    assert ('point of contraflexure' in _flat(rep.sheets[0][0]))


def test_a_pinned_truss_has_straight_members_and_says_why():
    m, res, ch = _solved('pratt')
    rep = _report(m, res, ch, compute_diagrams(m['nodes'], m['rods'],
                                               m['loads'], res))
    rep.deflection_and_stress()
    assert rep.flex_points == []
    assert 'every member stays straight' in _flat(rep.sheets[0][0])


def test_the_report_uses_the_screen_s_magnification_when_given_it(tmp_path):
    """The owner compares the sheet against the canvas at its own slider
    setting; an automatic factor made a different picture."""
    m, res, ch, dg = _bending_model()
    out = tp.export_pdf(str(tmp_path / 'r.pdf'), m['nodes'], m['rods'],
                        m['supports'], m['loads'], res, ch, m['profiles'],
                        diagrams=dg, deform_scale=50, buckling=False)
    assert out['deform_factor'] == 50
    out2 = tp.export_pdf(str(tmp_path / 's.pdf'), m['nodes'], m['rods'],
                         m['supports'], m['loads'], res, ch, m['profiles'],
                         diagrams=dg, buckling=False)
    assert out2['deform_factor'] > 0


def test_a_big_magnification_stays_on_the_drawing():
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg, deform_scale=300)
    rep.deflection_and_stress()
    ax = rep.sheets[0][0].axes[0]
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    for l in ax.lines:
        for x, y in zip(l.get_xdata(), l.get_ydata()):
            assert x0 <= x <= x1 and y0 <= y <= y1


# ═════════════════════════════════════════════════════════════════════════════
#  Which face the moment is drawn on
#
#  Found while building the Joints sheet: the tab draws M on the face it
#  puts in TENSION (sagging below a horizontal rod), and the t 06 / t 07
#  Moment and Shear sheets drew every lobe on the OPPOSITE face -- the
#  tab's normal (-dy/L, dx/L) applied to y-UP points flips it.
# ═════════════════════════════════════════════════════════════════════════════
def test_a_sagging_moment_is_drawn_on_the_tension_face():
    from matplotlib.figure import Figure
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    # rod 0 runs left to right along the bottom chord
    (xa, ya), (xb, yb) = rep.pts[m['rods'][0]['a']], rep.pts[m['rods'][0]['b']]
    assert xb > xa and abs(yb - ya) < 1e-9
    ax = Figure().add_subplot()
    rep.draw_band(ax, 0, [1.0, 1.0], [0.0, 1.0], 0.5, 'b', 'b')
    ys = [y for poly in ax.patches for _x, y in poly.get_xy()]
    assert min(ys) < ya - 0.4, 'a sagging lobe is not BELOW its rod'
    assert max(ys) <= ya + 1e-9, 'a sagging lobe reaches ABOVE its rod'


def test_the_report_puts_each_lobe_on_the_same_side_as_the_screen():
    """The tab's own rule, applied in its own y-down frame, against the
    report's, mapped back: they must agree for every rod, whatever its
    direction."""
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    for ri, rod in enumerate(m['rods']):
        (ax_, ay), (bx, by) = m['nodes'][rod['a']], m['nodes'][rod['b']]
        L = math.hypot(bx - ax_, by - ay)
        screen = (-(by - ay) / L, (bx - ax_) / L)        # y down
        nx, ny = rep.normal(ri)                          # y up
        assert screen[0] == pytest.approx(nx, abs=1e-9)
        assert screen[1] == pytest.approx(-ny, abs=1e-9)


# ═════════════════════════════════════════════════════════════════════════════
#  The joints
#
#  "there is not a sheet dedicated to the nodes, the nature of the maximum
#  moment they experience and the sign".
# ═════════════════════════════════════════════════════════════════════════════
def test_a_bending_model_gets_a_joints_sheet_and_a_pinned_one_does_not(
        tmp_path):
    m, res, ch, dg = _bending_model()
    out = tp.export_pdf(str(tmp_path / 'r.pdf'), m['nodes'], m['rods'],
                        m['supports'], m['loads'], res, ch, m['profiles'],
                        diagrams=dg, buckling=False)
    assert 'Joints' in out['headings']
    assert out['joints']
    m2, res2, ch2 = _solved('pratt')
    out2 = tp.export_pdf(str(tmp_path / 's.pdf'), m2['nodes'], m2['rods'],
                         m2['supports'], m2['loads'], res2, ch2,
                         m2['profiles'], buckling=False)
    assert 'Joints' not in out2['headings']


def test_a_joint_reports_the_largest_single_rod_moment_not_the_sum():
    """By equilibrium the rods' moments at a free joint cancel, so the
    SUM reads ~0 at exactly the joints working hardest."""
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    rows = rep.joint_moments()
    assert rows == sorted(rows, key=lambda e: -e['max_abs'])
    for e in rows:
        members = res['node_moments'][e['node']]['members']
        assert e['max_abs'] == pytest.approx(
            max(abs(x['moment']) for x in members))
        if e['support'] != 'fixed':
            assert abs(e['net']) < 1e-6, 'a free joint is not in equilibrium'
        assert e['max_abs'] > 10 * abs(e['net']) + 1e-9


def test_the_sense_follows_the_sign_and_the_arrow_turns_that_way():
    """Anticlockwise for +, clockwise for -, as on the canvas."""
    from matplotlib.figure import Figure
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    for m_ in (+5.0, -5.0):
        ax = Figure().add_subplot()
        rep._moment_arc(ax, 0.0, 0.0, m_, 1.0, 'k')
        xs, ys = ax.lines[0].get_xdata(), ax.lines[0].get_ydata()
        # signed area of the swept polyline: > 0 means anticlockwise
        area = sum(xs[i] * ys[i + 1] - xs[i + 1] * ys[i]
                   for i in range(len(xs) - 1))
        assert (area > 0) == (m_ > 0)
    rep.joints()
    cells = [t.get_text() for ax in rep.sheets[-1][0].axes for tab in ax.tables
             for t in [c.get_text() for c in tab.get_celld().values()]]
    for e in rep.joint_moments():
        want = 'anticlockwise' if e['signed'] > 0 else 'clockwise'
        assert want in cells


def test_the_tension_face_agrees_with_the_moment_sheet():
    """The table's "tension face" and the Moment sheet's lobe are the
    same fact said two ways; they must point the same way."""
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    for e in rep.joint_moments():
        ri = e['rod']
        rod = m['rods'][ri]
        M = dg[ri]['M']
        m_int = M[0] if rod['a'] == e['node'] else M[-1]
        nx, ny = rep.normal(ri)
        lobe = (nx * m_int, ny * m_int)          # where the band is drawn
        word = {'top': (0, 1), 'bottom': (0, -1),
                'right': (1, 0), 'left': (-1, 0)}[e['face']]
        assert lobe[0] * word[0] + lobe[1] * word[1] > 0, (
            'joint %d: table says %s, the lobe points the other way'
            % (e['node'], e['face']))


def test_the_cover_names_the_biggest_joint_moment():
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    rep.cover(['Geometry'])
    said = _flat(rep.sheets[0][0])
    top = rep.joint_moments()[0]
    assert 'Joint moment' in said
    assert 'joint %d' % top['node'] in said



# ═════════════════════════════════════════════════════════════════════════════
#  The fibre stress drawing
#
#  Reported 12-10-26 with a screenshot of the tab's fibre view: "this is
#  the fiber stress diagram, why is it missing from the pdf?". The sheet
#  carried a ranked chart of each rod's two extreme stresses -- the
#  numbers -- but not the picture: the structure with every rigid rod as
#  two coloured bands, one per face, flipping colour at contraflexure.
# ═════════════════════════════════════════════════════════════════════════════
def _fibre_polygons(fig):
    from matplotlib.patches import Polygon
    return [p for a in fig.axes for p in a.patches
            if isinstance(p, Polygon)
            and str(p.get_gid() or '').startswith('fibre')]


def test_the_deflection_sheet_carries_the_fibre_stress_drawing():
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    rep.deflection_and_stress()
    fig = rep.sheets[0][0]
    polys = _fibre_polygons(fig)
    rigid = [i for i, r in enumerate(m['rods']) if r.get('conn') == 'rigid']
    # at least one band on EACH face of every rigid rod
    assert sum(1 for p in polys if p.get_gid() == 'fibre+1') >= len(rigid)
    assert sum(1 for p in polys if p.get_gid() == 'fibre-1') >= len(rigid)
    cols = {tuple(round(c, 3) for c in p.get_facecolor()[:3]) for p in polys}
    assert len(cols) >= 2, 'the drawing has no tension and compression both'
    said = _flat(fig)
    assert 'Fibre stress' in said and 'contraflexure' in said
    assert 'Fibre stress values' in said, 'the numbers went missing'


def test_a_band_flips_colour_where_its_stress_changes_sign():
    from apps.truss.truss_math import compute_fiber_stress, find_zero_crossings
    m, res, ch, dg = _bending_model()
    flips = 0
    for ri, rod in enumerate(m['rods']):
        if rod.get('conn') != 'rigid':
            continue
        neg, pos = compute_fiber_stress(rod, res['rod_res'][ri], dg[ri]['M'])
        flips += len(find_zero_crossings(dg[ri]['xs'], pos))
        flips += len(find_zero_crossings(dg[ri]['xs'], neg))
    rep = _report(m, res, ch, dg)
    rep.deflection_and_stress()
    rigid = sum(1 for r in m['rods'] if r.get('conn') == 'rigid')
    # one polygon per face per rod, plus one more for every sign change
    assert len(_fibre_polygons(rep.sheets[0][0])) == 2 * rigid + flips


def test_a_pinned_truss_draws_each_rod_in_its_axial_colour():
    m, res, ch = _solved('pratt')
    rep = _report(m, res, ch, compute_diagrams(m['nodes'], m['rods'],
                                               m['loads'], res))
    rep.deflection_and_stress()
    fig = rep.sheets[0][0]
    assert _fibre_polygons(fig) == []
    assert 'Every rod is pinned' in _flat(fig)


def test_the_fibre_drawing_matches_the_screen_face_for_face(app):
    """The real check, made against the tab itself rather than against a
    description of it: every rigid rod's two faces sampled along their
    length, the colour the CANVAS drew read back with find_overlapping,
    the colour the REPORT drew read back at the same visual spot. The
    report's spot is found from the screen's own offset direction with
    y flipped -- not from `normal()`, so this does not test the code
    with itself. Measured 260 of 260 on the Vierendeel."""
    import math as _m
    from matplotlib.patches import Polygon
    app._load_library_example('vierendeel')
    app._hide_lesson()
    app._run_analysis(quiet=True)
    app.diagram_mode.set('fiber')
    root = app.root
    # A canvas big enough to sample. The tab's bands are a FIXED 6 px
    # whatever the zoom, so on a small canvas the band of one member
    # reaches over its neighbour near every joint -- measured in a full
    # suite run, where an earlier test left the window state such that
    # the middle vertical's band covered the top chord 0.75 m from the
    # joint. That is the screen being cramped, not a disagreement.
    root.winfo_toplevel().geometry('1600x1000+0+0')
    app.shell.set_panel_width(180)
    # Settle the window FIRST and draw after: the canvas size this test
    # rebuilds the transform from must be the one the drawing was made at.
    for _ in range(8):
        root.update_idletasks()
        root.update()
    app._draw_diagrams_only()
    for _ in range(4):
        root.update_idletasks()
        root.update()
    dc = app.diag_zc.canvas
    # Where the canvas ACTUALLY drew each joint, read off the drawing --
    # its node dots are the last ovals, in node order -- rather than
    # rebuilt from the canvas size, which can change between the drawing
    # and the reading (measured: drawn at 233 px tall, read at 259).
    ovals = [i for i in dc.find_all() if dc.type(i) == 'oval']
    assert len(ovals) >= len(app.nodes), 'the fibre view drew no joints'
    at = []
    for i in ovals[-len(app.nodes):]:
        x0, y0, x1, y1 = dc.coords(i)
        at.append(((x0 + x1) / 2, (y0 + y1) / 2))
    thick = 6 * app.diag_zc.zoom

    def canvas_colour(x, y):
        for item in reversed(dc.find_overlapping(x - .5, y - .5, x + .5, y + .5)):
            if dc.type(item) == 'polygon':
                return dc.itemcget(item, 'fill').lower()
        return None

    rep = tp._Report(app.nodes, app.rods, app._active_supports(),
                     app._design_loads(), app.results, app.rod_checks,
                     app.profiles, 'v', None, diagrams=app.diagrams)
    rep.deflection_and_stress()
    polys = _fibre_polygons(rep.sheets[0][0])
    th = rep.FIBRE_BAND * rep.span

    def report_colour(x, y):
        for p in reversed(polys):                  # topmost first, as drawn
            if p.get_path().contains_point((x, y)):
                return '#%02x%02x%02x' % tuple(
                    int(round(c * 255)) for c in p.get_facecolor()[:3])
        return None

    from apps.truss.truss_math import compute_fiber_stress, find_zero_crossings
    checked = skipped = 0
    for ri, rod in enumerate(app.rods):
        if rod.get('conn') != 'rigid':
            continue
        pa, pb = at[rod['a']], at[rod['b']]
        L = _m.hypot(pb[0] - pa[0], pb[1] - pa[1])
        nsx, nsy = -(pb[1] - pa[1]) / L, (pb[0] - pa[0]) / L
        qa, qb = rep.pts[rod['a']], rep.pts[rod['b']]
        d = app.diagrams[ri]
        neg, pos = compute_fiber_stress(rod, app.results['rod_res'][ri],
                                        d['M'])
        for side in (1, -1):
            # Where this face changes sign. A sample within 3 px of one
            # is on the boundary between two segments, where the canvas's
            # own hit test (its `closeenough` halo is a pixel) can report
            # the neighbour: measured as a false mismatch at t 0.65 on a
            # face that flips at 0.663, on a canvas smaller than usual.
            flips = [x / d['Lm'] for x in
                     find_zero_crossings(d['xs'], pos if side > 0 else neg)]
            for k in range(10):
                t = 0.05 + k / 10
                near_flip = any(abs(t - f) * L < 3.0 for f in flips)
                # ...and the joint zones, where every member meeting there
                # paints its own band and the topmost one wins on screen.
                near_joint = min(t, 1 - t) * L < 2 * thick + 2
                if near_flip or near_joint:
                    skipped += 1
                    continue
                sx = pa[0] + (pb[0] - pa[0]) * t + nsx * side * thick / 2
                sy = pa[1] + (pb[1] - pa[1]) * t + nsy * side * thick / 2
                px = qa[0] + (qb[0] - qa[0]) * t + nsx * side * th / 2
                py = qa[1] + (qb[1] - qa[1]) * t - nsy * side * th / 2
                a, b = canvas_colour(sx, sy), report_colour(px, py)
                assert a and b and a == b, (
                    'rod %d, face %+d, t %.2f: screen %s, report %s '
                    '(canvas %dx%d, rod drawn %.0f px)'
                    % (ri, side, t, a, b, dc.winfo_width(),
                       dc.winfo_height(), L))
                checked += 1
    assert checked >= 180, (
        'only %d samples checked (%d skipped as boundaries or joints) on a '
        '%dx%d canvas' % (checked, skipped, dc.winfo_width(),
                          dc.winfo_height()))


# ═════════════════════════════════════════════════════════════════════════════
#  The modern sheet (v32 t10)
#
#  Asked for on 12-10-26: "polish the pdf presentation so it is more
#  aesthetically pleasing". The owner chose a modern report -- a coloured
#  header band per sheet, cards for the key numbers on the cover -- kept
#  the captions in full, and asked for the author and the course on
#  every sheet, asked for once and remembered.
# ═════════════════════════════════════════════════════════════════════════════
def _framed(monkeypatch, tmp_path, m, res, ch, dg=None, **kw):
    """Export a report and hand back the _Report as it was framed."""
    seen = {}
    real = tp._Report.frame

    def spy(self):
        real(self)
        seen['rep'] = self
    monkeypatch.setattr(tp._Report, 'frame', spy)
    out = tp.export_pdf(str(tmp_path / 'r.pdf'), m['nodes'], m['rods'],
                        m['supports'], m['loads'], res, ch, m['profiles'],
                        diagrams=dg, **kw)
    return seen['rep'], out


def test_every_sheet_carries_its_band_and_a_footer_with_author_and_course(
        monkeypatch, tmp_path):
    m, res, ch, dg = _bending_model()
    rep, out = _framed(monkeypatch, tmp_path, m, res, ch, dg,
                       title='Girder', author='A. Student',
                       course='Structures I', buckling=False)
    n = len(rep.sheets)
    assert n == out['sheets']
    for i, (fig, heading) in enumerate(rep.sheets, start=1):
        said = _flat(fig)
        assert 'A. Student' in said and 'Structures I' in said, heading
        assert 'Sheet %d / %d' % (i, n) in said, heading
        if heading != 'Cover':
            assert heading in said and '%02d' % i in said, heading
    cover = _flat(rep.sheets[0][0])
    assert 'Author A. Student' in cover and 'Course Structures I' in cover


def test_a_report_without_an_author_prints_a_dash_not_a_blank(
        monkeypatch, tmp_path):
    m, res, ch = _solved('king_post')
    rep, _out = _framed(monkeypatch, tmp_path, m, res, ch, buckling=False)
    fields = dict(rep.footer_fields())
    assert fields['AUTHOR'] == '—' and fields['COURSE'] == '—'


def test_the_band_colour_says_what_kind_of_sheet_it_is():
    c = tp._Report.chapter_colour
    assert c('Geometry') == c('Axial forces') == c('Reactions')
    assert c('Shear V') == c('Moment M') == c('Joints')
    assert c('Rods (1/2)') == c('Utilisation')
    assert len({c('Geometry'), c('Deflection and stress'), c('Utilisation'),
                c('Buckling'), c('Moment M')}) == 5


def test_the_cover_shows_the_key_numbers_as_cards():
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    rep.buckling_factors = [0.8]
    rep.cover(['Geometry'])
    said = _flat(rep.sheets[0][0]).upper()
    for label in ('MAX TENSION', 'MAX COMPRESSION', 'DEFLECTION',
                  'MOST USED ROD', 'BUCKLING', 'WEIGHT'):
        assert label in said, label
    stripes = {c[-1] for c in rep._cover_cards()}
    assert tp._Report.BAD in stripes, 'λ₁ below 1 is not shown as a failure'


@pytest.mark.parametrize('bays', [4, 12])
def test_nothing_on_a_sheet_runs_into_the_band_or_the_footer(
        monkeypatch, tmp_path, bays):
    """`frame()` moves every sheet down under the band; anything composed
    too low then lands on the footer. 12 bays is 37 rods: two rod tables
    side by side, two Rod detail sheets."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    m, res, ch, dg = _vierendeel_bays(bays)
    rep, _out = _framed(monkeypatch, tmp_path, m, res, ch, dg,
                        buckling=False)
    lo, hi = tp._Report.FOOTER[1], tp._Report.BAND[0]
    tol = 0.004
    for fig, heading in rep.sheets:
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        r = canvas.get_renderer()
        _w, h = fig.get_size_inches() * fig.dpi
        boxes = [(t.get_text()[:30], t.get_window_extent(r))
                 for t in fig.texts if t.get_zorder() < 10 and t.get_text()]
        for ax in fig.axes:
            boxes.append(('axes', ax.get_window_extent(r)))
            boxes += [('table', tab.get_window_extent(r))
                      for tab in ax.tables]
            boxes += [(t.get_text()[:30], t.get_window_extent(r))
                      for t in ax.texts if t.get_text() and t.get_visible()]
        for what, bb in boxes:
            assert bb.y0 / h >= lo - tol, (
                '%s: %r runs into the footer' % (heading, what))
            if heading != 'Cover':
                assert bb.y1 / h <= hi + tol, (
                    '%s: %r runs into the header band' % (heading, what))


def test_the_caption_box_sits_between_the_band_and_the_drawing(
        monkeypatch, tmp_path):
    m, res, ch = _solved('pratt')
    rep, _out = _framed(monkeypatch, tmp_path, m, res, ch, buckling=False)
    for fig, heading in rep.sheets[1:]:
        cap = [t for t in fig.texts if t.get_gid() == 'caption']
        assert len(cap) <= 1, heading
        if cap:
            assert cap[0].get_position()[1] < tp._Report.BAND[0], heading


# ── the author and the course, remembered ─────────────────────────────────
def test_the_report_prefs_round_trip_and_survive_a_damaged_file(tmp_path):
    from apps.truss import truss_report_prefs as prefs
    p = str(tmp_path / 'sub' / 'r.json')
    assert prefs.load(p) == {'author': '', 'course': ''}
    assert not prefs.is_set(p)
    assert prefs.save('  Ana  ', 'Estructuras I', p)
    assert prefs.is_set(p)
    assert prefs.load(p) == {'author': 'Ana', 'course': 'Estructuras I'}
    Path(p).write_text('{not json')
    assert prefs.load(p) == {'author': '', 'course': ''}
    Path(p).write_text('["a list"]')
    assert prefs.load(p) == {'author': '', 'course': ''}


def test_the_tab_prints_the_remembered_author_on_the_report(
        app, tmp_path, monkeypatch):
    from apps.truss import truss_report_prefs as prefs
    monkeypatch.setenv(prefs.ENV, str(tmp_path / 'prefs.json'))
    prefs.save('A. Student', 'Structures I')
    seen = {}
    real = tp.export_pdf

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)
    monkeypatch.setattr(tp, 'export_pdf', spy)
    app._load_library_example('king_post')
    assert app._export_pdf_report(path=str(tmp_path / 'k.pdf')) is not None
    assert seen['author'] == 'A. Student'
    assert seen['course'] == 'Structures I'


def test_the_author_dialog_saves_what_was_typed(app, tmp_path, monkeypatch):
    from apps.truss import truss_report_prefs as prefs
    monkeypatch.setenv(prefs.ENV, str(tmp_path / 'prefs.json'))

    def answer():
        win = app._report_author_win
        win._author.set('B. Student')
        win._course.set('Trusses 101')
        win._save()
    app.root.after(200, answer)
    assert app._ask_report_author() is True
    assert prefs.load() == {'author': 'B. Student', 'course': 'Trusses 101'}


def test_cancelling_the_author_dialog_the_first_time_is_remembered(
        app, tmp_path, monkeypatch):
    """So the export that asked does not ask again on the next one."""
    from apps.truss import truss_report_prefs as prefs
    monkeypatch.setenv(prefs.ENV, str(tmp_path / 'prefs.json'))
    app.root.after(200, lambda: app._report_author_win.destroy())
    assert app._ask_report_author() is False
    assert prefs.is_set()
    assert prefs.load() == {'author': '', 'course': ''}


def test_the_export_menu_offers_the_author_and_course(app):
    import tkinter as tk
    found = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Menubutton):
                menu = c.nametowidget(c.cget('menu'))
                for i in range((menu.index('end') or 0) + 1):
                    try:
                        found.append(menu.entrycget(i, 'label'))
                    except tk.TclError:
                        pass
            walk(c)
    walk(app.root.winfo_toplevel())
    assert 'Report author and course…' in found


# ═════════════════════════════════════════════════════════════════════════════
#  The aesthetic pass on the rigid bridge (v32 t 13)
# ═════════════════════════════════════════════════════════════════════════════
def _bbox(fig, artist):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    if not isinstance(fig.canvas, FigureCanvasAgg):
        FigureCanvasAgg(fig)
    fig.canvas.draw()
    return artist.get_window_extent(fig.canvas.get_renderer())


@pytest.mark.parametrize('title', ['Pratt', 'K-truss bridge 64 m (rigid joints)',
                                   'A very long model name for a footbridge '
                                   'over the river, second scheme'])
def test_the_cover_title_never_runs_into_the_drawing(title):
    m, res, ch = _solved('pratt')
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], title, None)
    rep.cover(['Geometry'])
    fig = rep.sheets[0][0]
    t = next(t for t in fig.texts if t.get_text().replace('\n', ' ') == title)
    hero = next(a for a in fig.axes)
    bb, hb = _bbox(fig, t), _bbox(fig, hero)
    assert bb.x1 < hb.x0, 'the title runs under the truss drawing'
    assert t.get_fontsize() >= 14
    if title == 'Pratt':
        assert t.get_fontsize() == 26, 'a short title keeps its full size'


def test_the_footer_keeps_a_long_model_name_whole():
    m, res, ch = _solved('pratt')
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'K-truss bridge 64 m (rigid joints)',
                     None)
    assert dict(rep.footer_fields())['MODEL'] == \
        'K-truss bridge 64 m (rigid joints)'


def test_each_reaction_arrow_says_its_value_clear_of_the_scale_bar():
    m, res, ch = _solved('pratt')
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    rep.reactions()
    fig = rep.sheets[0][0]
    ax = fig.axes[0]
    vals = [t for t in ax.texts if t.get_text().endswith('kN')
            and t.get_color() == tp.REACTION]
    assert len(vals) == 2                       # two vertical reactions
    bar = [t for t in ax.texts if 'true to scale' in t.get_text()]
    for v in vals:
        for b in bar:
            assert not _bbox(fig, v).overlaps(_bbox(fig, b))


def test_the_deflection_limit_label_sits_inside_its_graph():
    m, res, ch = _solved('pratt')
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    rep.deflection_and_stress()
    fig = rep.sheets[0][0]
    ax = next(a for a in fig.axes
              if any('limit L/' in t.get_text() for t in a.texts))
    lab = next(t for t in ax.texts if 'limit L/' in t.get_text())
    assert _bbox(fig, lab).y0 >= ax.get_window_extent().y0 - 0.5


# ═════════════════════════════════════════════════════════════════════════════
#  Node force vectors and rod calculations (v32 t 15)
#
#  Asked for on 13-10-26: "can you add a node member vector report sheet
#  and a rod member report sheet to the pdf documents" -- then "the max
#  moment with the sign and arrow should be there in the cards".
# ═════════════════════════════════════════════════════════════════════════════
def _cards(rep, prefix):
    return [f for f, h in rep.sheets if h.startswith(prefix)]


def test_every_joint_gets_a_card_whose_sums_close():
    import re
    m, res, ch = _solved('pratt')
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    assert rep.node_vectors() == list(range(len(m['nodes'])))
    tables = [t.get_text() for f in _cards(rep, 'Node force vectors')
              for t in f.texts if t.get_gid() == 'node_table']
    assert len(tables) == len(m['nodes'])
    for body in tables:
        assert body.rstrip().endswith('✓'), body
        fx, fy = re.search(r'Fx (\S+)\s+Fy (\S+)', body.splitlines()[-1]
                           ).groups()
        assert abs(float(fx)) < 0.01 and abs(float(fy)) < 0.01


def test_a_node_card_lists_what_compute_node_design_actions_says():
    from apps.truss.truss_math import compute_node_design_actions
    m, res, ch = _solved('pratt')
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    rep.node_vectors()
    acts = compute_node_design_actions(m['nodes'], m['rods'],
                                       res['rod_res'])
    for ni, act in acts.items():
        for v in act['members']:
            assert any('r%d→%d' % (v['rod'], v['other']) in t.get_text()
                       and rep.u.f('force', tp._z(v['N']), 1, sign=True)
                       in t.get_text()
                       for f in _cards(rep, 'Node force vectors')
                       for t in f.texts if t.get_gid() == 'node_table')


def test_a_rigid_joint_card_carries_its_max_moment_sign_and_arrow():
    m, res, ch, dg = _bending_model()
    rep = _report(m, res, ch, dg)
    carded = rep.node_vectors()
    rows = {e['node']: e for e in rep.joint_moments()}
    e = rows[3]                                  # 43.44 kN·m, clockwise
    # one table per card, created in joint order
    tables = [t.get_text() for f in _cards(rep, 'Node force vectors')
              for t in f.texts if t.get_gid() == 'node_table']
    body = tables[carded.index(3)]
    line = next(l for l in body.splitlines() if l.startswith('max M'))
    assert rep.u.f('moment', e['signed'], 2, sign=True) in line
    assert ('clockwise' in line) and (('anti' in line) == (e['signed'] > 0))
    # and the turning arrow is drawn round the joint, in the moment purple
    fig = _cards(rep, 'Node force vectors')[0]
    arcs = [l for a in fig.axes for l in a.lines
            if l.get_color() == '#7b2d8e' and len(l.get_xdata()) > 10]
    assert len(arcs) >= 4


def test_every_rod_gets_a_calculation_row_with_its_end_components():
    m, res, ch = _solved('pratt')
    rep = tp._Report(m['nodes'], m['rods'], m['supports'], m['loads'], res,
                     ch, m['profiles'], 'p', None)
    assert rep.rod_calculations() == list(range(len(m['rods'])))
    sheets = _cards(rep, 'Rod calculations')
    assert len(sheets) == 2                       # 17 rods, 16 to a sheet
    texts = [t.get_text() for f in sheets for t in f.texts]
    N = res['rod_res'][13]['force']
    assert any('N = %s kN' % rep.u.f('force', N, 2, sign=True) in t
               for t in texts)
    assert sum(1 for t in texts if t.startswith('Rod ')) == len(m['rods'])


# ── the same cards in the tab's two report windows ────────────────────────
#  "please update the apps ui to show the nodes and member rods like you
#  are doing for the pdf"
def test_the_node_window_shows_the_report_s_cards(app, tmp_path,
                                                  monkeypatch):
    from tkinter import filedialog
    app._load_library_example('vierendeel')
    app._run_analysis(quiet=True)
    win = app._show_node_vectors_report()
    app.root.update()
    assert win.sheet_count == 2                      # 10 joints, 8 a sheet
    assert len(win.card_texts) == len(app.nodes)
    assert len(win._images) == win.sheet_count
    assert all('max M' in t for t in win.card_texts), (
        'every Vierendeel joint carries moment; its card must say so')
    out = tmp_path / 'cards.pdf'
    monkeypatch.setattr(filedialog, 'asksaveasfilename', lambda **k: str(out))
    win.save_pdf()
    assert _pages(out) == win.sheet_count
    win.destroy()


def test_the_rod_window_shows_one_row_per_rod(app):
    app._load_library_example('pratt')
    app._run_analysis(quiet=True)
    win = app._show_rod_calculations_report()
    app.root.update()
    assert win.sheet_count == 2                      # 17 rods, 16 a sheet
    assert len(win.card_texts) == len(app.rods)
    win.destroy()


def test_the_card_windows_ask_for_an_analysis_first(app):
    app._load_library_example('pratt')
    assert app._show_node_vectors_report() is None
    assert app._show_rod_calculations_report() is None
