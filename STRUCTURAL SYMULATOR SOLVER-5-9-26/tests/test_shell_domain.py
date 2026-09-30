"""The domain: a contour instead of a condition, and a mesh fitted to it.

The question behind every test here is the one that made the change worth
making. A plan cut judged element-by-element gives a staircase, and a
staircase's perimeter does not converge: the taxicab boundary of a circle
is 8r however fine the mesh gets, against 2*pi*r. An edge beam laid on it
would be 27 % too long and too heavy, forever. So the tests measure the
boundary, not the picture.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.shell import shell_model as sm
from apps.shell import shell_solid as solid

R = 6.0                       # the inscribed circle of the 12 x 12 preset
ELLIPSE = '(2x/a)^2 + (2y/b)^2 - 1'


def hypar(**over):
    m = sm.ShellModel.preset('Hypar saddle on four edge beams')
    m.data.update(over)
    return m


def perimeter(g):
    X = g['X']
    out = 0.0
    for loop in solid.boundary_loops(g['elems']):
        P = X[np.asarray(loop, int), :2]
        out += float(np.hypot(*(P[1:] - P[:-1]).T).sum())
    return out


def plan_area(g):
    return float(np.abs(sm._plan_area(g['X'], g['elems'])).sum())


# ── the contour itself ─────────────────────────────────────────────────────

def test_no_edge_rule_leaves_the_whole_rectangle():
    g = hypar().mesh()
    assert g['kept'] is None
    assert not g['has_edge_rule']
    assert len(g['elems']) == g['nx'] * g['ny']


def test_the_rule_keeps_what_is_negative_and_drops_what_is_not():
    g = hypar(edge_rule=ELLIPSE).mesh()
    c = g['centroids']
    assert np.all(np.hypot(c[:, 0], c[:, 1]) < R)
    assert len(g['elems']) < g['nx'] * g['ny']


def test_an_edge_rule_that_keeps_nothing_says_so():
    with pytest.raises(sm.ModelError, match='keeps no elements'):
        hypar(edge_rule='hypot(x, y) + 1').mesh()


def test_a_misspelt_edge_rule_names_the_rule():
    with pytest.raises(sm.ModelError, match='Edge rule'):
        hypar(edge_rule='hypot(x, y) - rr').mesh()


def test_the_rule_may_use_the_numbers_you_defined():
    m = hypar(edge_rule='hypot(x, y) - f')          # f = 3 in the preset
    c = m.mesh()['centroids']
    assert np.hypot(c[:, 0], c[:, 1]).max() < 3.0


def test_max_of_two_regions_is_their_intersection():
    """How the sector presets are built: a disc AND two half-planes."""
    g = hypar(edge_rule='max(hypot(x, y) - 5, -x, -y)').mesh()
    c = g['centroids']
    assert np.all(c[:, 0] > 0) and np.all(c[:, 1] > 0)
    assert np.hypot(c[:, 0], c[:, 1]).max() < 5.0


# ── the fit: the point of the whole exercise ───────────────────────────────

def test_every_boundary_node_lands_on_the_curve():
    g = hypar(edge_rule=ELLIPSE).mesh()
    bn = np.unique(np.asarray([[a, b] for a, b, _e in
                               solid.boundary_edges(g['elems'])], int).ravel())
    r = np.hypot(g['X'][bn, 0], g['X'][bn, 1])
    assert np.abs(r - R).max() < 1e-6


def test_the_fitted_perimeter_is_the_real_perimeter():
    g = hypar(edge_rule=ELLIPSE).mesh()
    assert perimeter(g) == pytest.approx(2 * np.pi * R, rel=2e-3)


def test_the_unfitted_perimeter_is_the_taxicab_one_and_stays_wrong():
    """The reason the fit exists. 8r, not 2*pi*r, at any mesh size."""
    coarse = hypar(edge_rule=ELLIPSE, fit_edge=False,
                   mesh={'nx': 24, 'ny': 24, 'size': 0.5}).mesh()
    fine = hypar(edge_rule=ELLIPSE, fit_edge=False,
                 mesh={'nx': 48, 'ny': 48, 'size': 0.25}).mesh()
    for g in (coarse, fine):
        assert perimeter(g) == pytest.approx(8 * R, rel=1e-6)
    assert perimeter(fine) > 1.25 * 2 * np.pi * R


def test_the_area_is_right_either_way_but_better_fitted():
    true = np.pi * R * R
    fitted = plan_area(hypar(edge_rule=ELLIPSE).mesh())
    stair = plan_area(hypar(edge_rule=ELLIPSE, fit_edge=False).mesh())
    assert abs(fitted - true) < abs(stair - true)
    assert fitted == pytest.approx(true, rel=2e-3)


def test_the_fit_moves_nodes_and_says_which():
    g = hypar(edge_rule=ELLIPSE).mesh()
    assert g['fitted'].sum() > 50
    assert not g['fitted'][~g['used']].any()      # never an unused node


def test_turning_the_fit_off_moves_nothing():
    g = hypar(edge_rule=ELLIPSE, fit_edge=False).mesh()
    assert not g['fitted'].any()


def test_no_element_is_turned_inside_out():
    for rule in (ELLIPSE, 'hypot(x, y) - 4.3', 'max(x y - 9, -x, -y)',
                 'max(hypot(x, y) - 5.1, 2.4 - hypot(x, y))'):
        g = hypar(edge_rule=rule).mesh()
        A = sm._plan_area(g['X'], g['elems'])
        assert np.all(A > 0), rule
        assert A.min() > 0.02 * np.median(A), rule


def test_a_node_further_than_the_guard_is_left_alone():
    """The corner of a 12 x 12 plan is 2.5 m from a radius-6 disc: far past
    0.55 of an element, so it stays where it is rather than being dragged
    across its neighbours."""
    g = hypar(edge_rule=ELLIPSE).mesh()
    d = np.hypot(g['X'][:, 0], g['X'][:, 1])
    far = np.nonzero(d > R + 1.0)[0]
    assert len(far) and not g['fitted'][far].any()


def test_a_moved_node_is_put_back_onto_the_surface():
    """Moving a node in plan without re-evaluating z would leave it hanging
    off the surface it is supposed to be on."""
    m = hypar(edge_rule=ELLIPSE)
    g = m.mesh()
    X = g['X'][g['fitted']]
    z = np.asarray(m.surface_fn()(X[:, 0], X[:, 1]), float)
    assert np.abs(z - X[:, 2]).max() < 1e-9


def test_both_rules_may_be_given_and_an_element_must_pass_both():
    g = hypar(edge_rule=ELLIPSE, plan_rule='not (x > 0 and y > 0)').mesh()
    c = g['centroids']
    assert np.all(np.hypot(c[:, 0], c[:, 1]) < R)
    assert not np.any((c[:, 0] > 0) & (c[:, 1] > 0))


# ── the boundary as a thing you can build on ───────────────────────────────

def test_a_disc_gives_one_loop_and_a_ring_gives_two():
    one = solid.boundary_loops(hypar(edge_rule='hypot(x, y) - 5').mesh()['elems'])
    two = solid.boundary_loops(
        hypar(edge_rule='max(hypot(x, y) - 5, 2.5 - hypot(x, y))').mesh()['elems'])
    assert len(one) == 1 and one[0][0] == one[0][-1]
    assert len(two) == 2 and all(l[0] == l[-1] for l in two)


def test_the_edge_beam_follows_the_cut():
    f = hypar(edge_rule=ELLIPSE).build()
    used = f['mesh']['used']
    assert [b['line'] for b in f['beam_lines']] == ['cut']
    nodes = np.asarray(f['beam_lines'][0]['nodes'], int)
    assert used[nodes].all()
    r = np.hypot(f['mesh']['X'][nodes, 0], f['mesh']['X'][nodes, 1])
    assert np.abs(r - R).max() < 1e-6


def test_the_rectangle_is_still_available_on_purpose():
    f = hypar(edge_rule=ELLIPSE,
              beams=[{'line': 'rectangle', 'b': 25.0, 'h': 50.0, 'offset': 'below'}]).build()
    assert sorted(b['line'] for b in f['beam_lines']) == ['x0', 'x1', 'y0', 'y1']


def test_an_uncut_plan_still_names_its_four_sides():
    f = hypar().build()
    assert sorted(b['line'] for b in f['beam_lines']) == ['x0', 'x1', 'y0', 'y1']


def test_the_corner_supports_move_onto_the_cut():
    f = hypar(edge_rule=ELLIPSE).build()
    X = f['mesh']['X']
    ns = [n for n, _code in f['support_nodes']]
    assert len(ns) == 4
    r = np.hypot(X[ns, 0], X[ns, 1])
    assert np.abs(r - R).max() < 1e-6
    assert f['mesh']['used'][ns].all()


def test_a_support_can_ask_for_the_whole_cut():
    f = hypar(edge_rule=ELLIPSE,
              supports=[{'at': 'cut', 'which': 'all', 'type': 'pinned'}]).build()
    ns = [n for n, _code in f['support_nodes']]
    r = np.hypot(f['mesh']['X'][ns, 0], f['mesh']['X'][ns, 1])
    assert len(ns) > 50 and np.abs(r - R).max() < 1e-6


def test_supporting_the_real_edge_stiffens_the_shell():
    """Not a cosmetic claim: on the rectangle the shell hangs off four
    tangent points of a beam ring and bends it; on the cut it is held where
    it ends."""
    on_cut = hypar(edge_rule=ELLIPSE)
    on_box = hypar(edge_rule=ELLIPSE,
                   beams=[{'line': 'rectangle', 'b': 25.0, 'h': 50.0, 'offset': 'below'}])
    peak = []
    for m in (on_cut, on_box):
        r = m.analyze()
        U = r.combo_U(r.service).reshape(-1, 6)
        peak.append(float(np.abs(U[:len(r.fem['mesh']['X']), 2]).max()))
    assert peak[0] < 0.25 * peak[1]


def test_the_cut_model_analyses_and_designs():
    from apps.shell import shell_design as sd
    m = hypar(edge_rule=ELLIPSE)
    r = m.analyze()
    D = sd.design(m, r)
    assert np.isfinite(D.util_max).all()
    assert D.ok


# ── the panel ──────────────────────────────────────────────────────────────

tk = pytest.importorskip('tkinter')

import units                                            # noqa: E402
from apps.shell import shell_app as sa                  # noqa: E402


@pytest.fixture
def app():
    units.set_current('cirsoc')
    try:
        root = tk.Tk()
    except tk.TclError:                                 # pragma: no cover
        pytest.skip('no display')
    root.geometry('1400x900')
    a = sa.ShellApp(root)
    a.pack(fill='both', expand=True)
    root.update()
    try:
        yield a
    finally:
        units.set_current('cirsoc')
        a.stop_units()
        try:
            root.destroy()
        except Exception:
            pass


@pytest.mark.parametrize('label,rule',
                         [p for row in sa.EDGE_PRESET_ROWS for p in row])
def test_every_contour_preset_meshes(app, label, rule):
    app.v_edge_rule.set(rule)
    app._set_edge_rule()
    assert app.error == '', (label, app.error)
    assert app.geom is not None
    assert len(app.geom['elems']) > 4


def test_the_band_shortcut_writes_one_signed_expression(app):
    app.v_band_lo.set('-(x/2)^2')
    app.v_band_hi.set('(x/2)^2 + 1')
    app._set_band()
    assert app.v_edge_rule.get() == 'max((-(x/2)^2) - y, y - ((x/2)^2 + 1))'
    assert app.error == ''
    c = app.geom['centroids']
    assert np.all(c[:, 1] >= -(c[:, 0] / 2) ** 2 - 1e-9)


def test_the_band_shortcut_asks_for_both_curves(app):
    app.v_band_lo.set('0')
    app.v_band_hi.set('')
    app._set_band()
    assert app.v_edge_rule.get() == ''
    assert 'both' in app.status.get()


def test_the_note_reports_the_boundary_length(app):
    app.v_edge_rule.set(ELLIPSE)
    app._set_edge_rule()
    txt = app.edge_rule_note.cget('text')
    assert 'boundary 37.7' in txt.replace('37.69', '37.7')
    assert 'moved onto the curve' in txt


def test_the_note_warns_in_red_when_the_edge_is_not_fitted(app):
    app.v_edge_rule.set(ELLIPSE)
    app._set_edge_rule()
    app.v_fit_edge.set(False)
    app._set_fit_edge()
    txt = app.edge_rule_note.cget('text')
    assert 'staircase' in txt
    assert app.edge_rule_note.cget('fg') == '#a33'
    assert 'boundary 48.0' in txt


def test_setting_a_cut_says_the_beams_moved(app):
    app.v_edge_rule.set(ELLIPSE)
    app._set_edge_rule()
    assert 'follow the cut' in app.status.get()


def test_clearing_the_rule_gives_the_rectangle_back(app):
    app.v_edge_rule.set(ELLIPSE)
    app._set_edge_rule()
    app.v_edge_rule.set('')
    app._set_edge_rule()
    assert app.edge_rule_note.cget('text') == ''
    assert len(app.geom['elems']) == app.geom['nx'] * app.geom['ny']


def test_a_preset_change_reloads_the_box(app):
    app.v_edge_rule.set(ELLIPSE)
    app._set_edge_rule()
    app.load_preset('Barrel vault (cylinder)')
    assert app.v_edge_rule.get() == ''
