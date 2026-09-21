"""The design strip, and the surface a piece was cut from.

The strip is the hand calculation every shell on a drawing board is
designed by: a metre-wide band treated as an arch or a cable of span L
and rise f, with H = q' L² / 8f. The tab can now work out the same band
from the finite element result and print the two together. What these
tests protect is that the hand side really is the hand method -- above
all the q', which is the load SHARE this family of parabolas carries.
Feeding the whole load to one family doubles the answer and is the
commonest arithmetic mistake in a hand check of a hypar.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

tk = pytest.importorskip('tkinter')

import units
from apps.shell import shell_app as sa
from apps.shell import shell_model as sm

ELLIPSE = '(2x/a)^2 + (2y/b)^2 - 1'


@pytest.fixture
def app():
    units.set_current('cirsoc')
    try:
        root = tk.Tk()
    except tk.TclError:                          # pragma: no cover
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


@pytest.fixture
def ran(app):
    assert app.analyze() is True
    return app


# ── the strip's geometry ───────────────────────────────────────────────────

def test_the_chord_and_the_rise_are_the_real_ones(app):
    """The 12 x 12 preset is z = x y / 24. Its diagonal is 12*sqrt(2) long
    and its mid-point sits 1.5 m below the chord."""
    span, rise = app._chord_rise((-6, -6), (6, 6))
    assert span == pytest.approx(12 * np.sqrt(2))
    assert rise == pytest.approx(-1.5, abs=1e-9)


def test_the_other_diagonal_is_the_arch(app):
    _span, rise = app._chord_rise((-6, 6), (6, -6))
    assert rise == pytest.approx(+1.5, abs=1e-9)


def test_the_buttons_find_the_two_parabolas_by_sampling(app):
    app.strip_on_parabola('tension')
    assert app.design_strip()['rise'] < 0
    assert 'tension' in app.design_strip()['kind']
    app.strip_on_parabola('compression')
    assert app.design_strip()['rise'] > 0
    assert 'compression' in app.design_strip()['kind']


def test_a_strip_of_no_length_is_refused(app):
    for k, v in zip(('x1', 'y1', 'x2', 'y2'), ('0', '0', '0', '0')):
        app.v_strip[k].set(v)
    with pytest.raises(sm.ModelError, match='no length'):
        app.design_strip()


def test_a_flat_strip_is_refused_rather_than_dividing_by_zero(app):
    """H = q L² / 8f has no answer when f is zero, and a shell with a flat
    line across it is not carrying anything as an arch along that line."""
    for k, v in zip(('x1', 'y1', 'x2', 'y2'), ('-6', '0', '6', '0')):
        app.v_strip[k].set(v)          # z = x y / 24 is zero all along y = 0
    with pytest.raises(sm.ModelError, match='flat'):
        app.design_strip()


def test_a_negative_width_is_refused(app):
    app.v_strip_w.set('-1')
    with pytest.raises(sm.ModelError, match='width must be positive'):
        app.design_strip()


def test_the_strip_collects_only_the_elements_under_it(ran):
    ran.strip_on_parabola('tension')
    ran.v_strip_w.set('1.0')
    st = ran.design_strip()
    cen = ran.geom['centroids'][st['elems']]
    rel = cen[:, :2] - np.array(st['p1'])
    across = rel @ np.array([-st['dir'][1], st['dir'][0]])
    assert len(st['elems']) > 10
    assert np.abs(across).max() <= 0.5 + 1e-9


def test_a_wider_strip_collects_more(ran):
    ran.strip_on_parabola('tension')
    ran.v_strip_w.set('1.0')
    narrow = len(ran.design_strip()['elems'])
    ran.v_strip_w.set('3.0')
    assert len(ran.design_strip()['elems']) > narrow


# ── the hand calculation ───────────────────────────────────────────────────

def test_the_load_is_the_one_the_solver_actually_saw(ran):
    """Taken from the equilibrium of the assembled model, not by re-reading
    the load panel: a second implementation of the loading could disagree
    with the first and there would be no way to tell which was right."""
    q = ran.strip_load()
    fac = ran.res.factors_vector(ran.res.service)
    fz = sum(fac[j] * ran.res.equilibrium[j]['applied'][2]
             for j in range(len(ran.res.cases)))
    area = float(np.abs(sm._plan_area(ran.geom['X'], ran.geom['elems'])).sum())
    assert q == pytest.approx(abs(fz) / area)
    assert q > 0


def test_the_family_carries_half_the_load_by_default(ran):
    ran.strip_on_parabola('tension')
    st = ran.design_strip()
    assert st['share'] == 0.5
    assert st['q_strip'] == pytest.approx(0.5 * st['q'])


def test_the_hand_thrust_is_q_prime_L_squared_over_8f(ran):
    ran.strip_on_parabola('tension')
    st = ran.design_strip()
    assert st['H'] == pytest.approx(st['q_strip'] * st['span'] ** 2
                                    / (8 * abs(st['rise'])))


def test_the_hand_value_is_the_exact_membrane_answer_for_a_hypar(ran):
    """On z = k x y the membrane solution is a pure shear of q / 2k, and
    q' L² / 8f on the diagonal reduces to exactly that. If the share were
    1.0 instead of 0.5 this would be out by a factor of two -- which is the
    whole reason the share is a visible number and not a constant."""
    k = ran.res.hypar_fit()
    assert k is not None
    ran.strip_on_parabola('tension')
    st = ran.design_strip()
    assert st['H'] == pytest.approx(st['q'] / (2 * abs(k)), rel=1e-6)


def test_the_whole_load_on_one_family_doubles_it(ran):
    ran.strip_on_parabola('tension')
    half = ran.design_strip()['H']
    ran.v_strip_share.set('1.0')
    assert ran.design_strip()['H'] == pytest.approx(2 * half)


# ── the two answers together ───────────────────────────────────────────────

def test_the_model_agrees_with_the_hand_value_within_a_quarter(ran):
    for which in ('tension', 'compression'):
        ran.strip_on_parabola(which)
        st = ran.design_strip()
        assert abs(abs(st['N']) - st['H']) < 0.25 * st['H'], which


def test_the_two_families_come_out_opposite_in_sign(ran):
    ran.strip_on_parabola('tension')
    a = ran.design_strip()['N']
    ran.strip_on_parabola('compression')
    b = ran.design_strip()['N']
    assert a > 0 > b


def test_the_report_says_both_and_says_they_agree(ran):
    ran.strip_on_parabola('tension')
    txt = ran.strip_report()
    for want in ('span L', "q'", 'by hand', 'the model, same strip', 'N along',
                 'against your hand value'):
        assert want in txt, want
    assert 'agrees' in txt


def test_the_report_asks_for_an_analysis_before_it_has_one(app):
    app.strip_on_parabola('tension')
    txt = app.strip_report()
    assert 'analyse to get the load' in txt
    assert 'by hand' not in txt


def test_the_report_returns_the_refusal_rather_than_raising(app):
    app.v_strip_w.set('0')
    assert 'width must be positive' in app.strip_report()


# ── drawing ────────────────────────────────────────────────────────────────

def test_the_strip_is_drawn_only_where_it_is_being_used(ran):
    ran.strip_on_parabola('tension')
    ran.set_mode('analyse')
    assert not ran.zc.canvas.find_withtag('strip')
    ran.set_mode('sections')
    assert len(ran.zc.canvas.find_withtag('strip')) == 3   # centre + two edges


def test_the_strip_can_be_switched_off(ran):
    ran.set_mode('sections')
    ran.v_strip_show.set(False)
    ran._draw()
    assert not ran.zc.canvas.find_withtag('strip')


# ── the surface it was cut from ────────────────────────────────────────────

def test_there_is_no_parent_surface_without_a_cut(app):
    assert app.parent_mesh() is None
    app.v_ghost.set(True)
    app._draw()
    assert not app.zc.canvas.find_withtag('ghost')


def test_the_parent_is_the_whole_rectangle(app):
    app.v_edge_rule.set(ELLIPSE)
    app._set_edge_rule()
    gp = app.parent_mesh()
    assert gp is not None
    assert len(gp['elems']) == gp['nx'] * gp['ny']
    assert len(gp['elems']) > len(app.geom['elems'])


def test_the_ghost_is_drawn_behind_and_says_what_it_is(app):
    app.v_edge_rule.set(ELLIPSE)
    app._set_edge_rule()
    app.v_ghost.set(True)
    app._draw()
    ghosts = app.zc.canvas.find_withtag('ghost')
    assert len(ghosts) == app.geom['nx'] * app.geom['ny']
    faces = app.zc.canvas.find_withtag('face')
    if faces:
        assert max(ghosts) < min(faces)          # painted first: never on top
    texts = [app.zc.canvas.itemcget(i, 'text')
             for i in app.zc.canvas.find_all()
             if app.zc.canvas.type(i) == 'text']
    assert any('reference only' in t for t in texts)


def test_the_parent_mesh_is_cached_until_something_changes_it(app):
    app.v_edge_rule.set(ELLIPSE)
    app._set_edge_rule()
    first = app.parent_mesh()
    assert app.parent_mesh() is first
    app.model.data['mesh'] = dict(app.model.data['mesh'], size=1.0)
    assert app.parent_mesh() is not first


def test_clearing_the_cut_takes_the_ghost_away(app):
    app.v_edge_rule.set(ELLIPSE)
    app._set_edge_rule()
    app.v_ghost.set(True)
    app._draw()
    assert app.zc.canvas.find_withtag('ghost')
    app.v_edge_rule.set('')
    app._set_edge_rule()
    assert not app.zc.canvas.find_withtag('ghost')


# ── the element under the cut ──────────────────────────────────────────────

def test_a_cut_names_the_worst_element_under_it(ran):
    ran.set_mode('sections')
    ran.v_cut_pos.set('3')
    ran.add_cut('x')
    txt = ran.cut_note.cget('text')
    assert 'Under this cut:' in txt
    assert 'worst here: el' in txt
    assert 'most tension' in txt and 'most compression' in txt


def test_the_worst_element_named_is_really_the_worst_on_the_line(ran):
    ran.set_mode('sections')
    ran.v_cut_pos.set('3')
    ran.add_cut('x')
    el = ran.cut_elements(ran._selected_cut())
    want = int(el[np.argmax(ran.des.util_max[el])])
    assert ('worst here: el %d' % want) in ran.cut_note.cget('text')


def test_removing_the_cut_empties_the_note(ran):
    ran.set_mode('sections')
    ran.add_cut('x')
    assert ran.cut_note.cget('text')
    ran.remove_cut()
    assert ran.cut_note.cget('text') == ''


def test_a_cut_that_misses_the_shell_says_so(ran):
    """Easy to do once the plan is cut: x = 5 crosses nothing of a disc of
    radius 4."""
    ran.v_edge_rule.set('hypot(x, y) - 4')
    ran._set_edge_rule()
    assert ran.analyze() is True
    ran.set_mode('sections')
    ran.v_cut_pos.set('5')
    ran.add_cut('x')
    assert 'misses the shell' in ran.cut_note.cget('text')


def test_the_sector_between_the_asymptotes_is_a_preset(app):
    names = [lab for row in sa.EDGE_PRESET_ROWS for lab, _r in row]
    assert 'sector bajo paraboloide' in names
    rule = dict((lab, r) for row in sa.EDGE_PRESET_ROWS for lab, r in row)
    app.v_edge_rule.set(rule['sector bajo paraboloide'])
    app._set_edge_rule()
    c = app.geom['centroids']
    assert np.all(c[:, 0] > 0) and np.all(c[:, 1] > 0)
