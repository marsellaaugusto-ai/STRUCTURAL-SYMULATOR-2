"""Cable tab: the funicular solver against closed-form solutions.

Written with the 2026-09-10 re-diagnosis (finding C-3): the Cable tab had no
physics test of its own. The four Cable *Web* test files are easy to misread as
coverage for this tab; they are not the same solver.

The last test here is the one that matters most. Finding C-1 was that the
reported maximum tension came from the end element's chord, which is always
flatter than the cable's true slope at the support, so the reported peak was
0.5-1.7% LOW -- on the unsafe side -- and disagreed with the tab's own tension
diagram. An assertion that the two agree would have caught it outright, so
that assertion is now here.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.cable.cable_app import CableModel

SPAN = 20.0
W = 500.0        # N/m


def _rel(got, want):
    return abs(got - want) / max(abs(want), 1e-12)


def _parabola_arc_length(span, sag, n=200000):
    s = 0.0
    xp = yp = 0.0
    for k in range(1, n + 1):
        x = span * k / n
        y = -4 * sag * x * (span - x) / span ** 2
        s += math.hypot(x - xp, y - yp)
        xp, yp = x, y
    return s


def _catenary(span, w, H):
    """(arc length, sag, T_max) of the exact catenary with this H."""
    s = (2 * H / w) * math.sinh(w * span / (2 * H))
    sag = (H / w) * (math.cosh(w * span / (2 * H)) - 1)
    return s, sag, H * math.cosh(w * span / (2 * H))


# ------------------------------------------------------------------ parabola

def test_udl_per_horizontal_metre_gives_a_parabola_with_h_equal_wl2_over_8f():
    sag = 2.0
    m = CableModel(SPAN, _parabola_arc_length(SPAN, sag), n_elem=200)
    m.add_distributed_load(lambda x: W, 0.0, SPAN, measure='horizontal')
    r = m.solve()
    assert r.converged
    _, got_sag = r.max_sag()
    assert _rel(got_sag, sag) < 5e-3
    assert _rel(r.H, W * SPAN * SPAN / (8 * sag)) < 5e-3


def test_parabola_support_reactions_are_half_the_load_each():
    sag = 2.0
    m = CableModel(SPAN, _parabola_arc_length(SPAN, sag), n_elem=100)
    m.add_distributed_load(lambda x: W, 0.0, SPAN, measure='horizontal')
    r = m.solve()
    v_left, v_right = r.reactions()
    assert _rel(v_left, W * SPAN / 2) < 1e-6
    assert _rel(v_right, W * SPAN / 2) < 1e-6


# ------------------------------------------------------------------ catenary

def test_self_weight_per_arc_metre_gives_a_catenary():
    H = 4000.0
    arc, sag, _ = _catenary(SPAN, W, H)
    m = CableModel(SPAN, arc, n_elem=200)
    m.add_distributed_load(lambda x: W, 0.0, SPAN, measure='arc')
    r = m.solve()
    assert r.converged
    assert _rel(r.H, H) < 5e-3
    _, got_sag = r.max_sag()
    assert _rel(got_sag, sag) < 5e-3


def test_catenary_shape_matches_the_closed_form_at_the_quarter_points():
    H = 4000.0
    arc, sag, _ = _catenary(SPAN, W, H)
    m = CableModel(SPAN, arc, n_elem=200)
    m.add_distributed_load(lambda x: W, 0.0, SPAN, measure='arc')
    r = m.solve()
    for xq in (SPAN / 4, SPAN / 2, 3 * SPAN / 4):
        want = (H / W) * (math.cosh(W * (xq - SPAN / 2) / H)
                          - math.cosh(W * SPAN / (2 * H)))
        i = min(range(len(r.x)), key=lambda k: abs(r.x[k] - xq))
        assert abs(r.y[i] - want) < 8e-3 * abs(sag)


# ---------------------------------------------------------------- point load

def test_single_midspan_point_load_is_pure_geometry():
    P, sag = 3000.0, 1.5
    m = CableModel(SPAN, 2 * math.hypot(SPAN / 2, sag), n_elem=100)
    m.add_point_load(SPAN / 2, P)
    r = m.solve()
    assert r.converged
    _, got_sag = r.max_sag()
    assert _rel(got_sag, sag) < 5e-3
    assert _rel(r.H, P * SPAN / (4 * sag)) < 5e-3
    assert _rel(max(r.tension()), math.hypot(P * SPAN / (4 * sag), P / 2)) < 5e-3


# ------------------------------------------------------------- peak tension

def test_reported_peak_tension_matches_the_exact_value_at_every_sag():
    """Regression for C-1.

    The peak tension is at a support, where it is exactly hypot(H, V) -- no
    discretisation involved. Taking it from the end element's chord instead
    under-reported it by 0.5-1.7% at the app's default mesh, always low.
    """
    for H in (8000.0, 4000.0, 2000.0, 1000.0):
        arc, _, t_true = _catenary(SPAN, W, H)
        m = CableModel(SPAN, arc, n_elem=60)     # the app's own default mesh
        m.add_distributed_load(lambda x: W, 0.0, SPAN, measure='arc')
        r = m.solve()
        assert _rel(max(r.tension()), t_true) < 1e-3, (
            'peak tension off by more than 0.1%% at H=%g' % H)


def test_peak_tension_does_not_depend_on_the_mesh():
    """C-1's under-report converged only first-order, so a coarse mesh was
    badly wrong and refining it was the only escape. The exact end value
    removes that dependence: 10 elements must agree with 200."""
    arc, _, t_true = _catenary(SPAN, W, 4000.0)
    peaks = []
    for n in (10, 30, 60, 200):
        m = CableModel(SPAN, arc, n_elem=n)
        m.add_distributed_load(lambda x: W, 0.0, SPAN, measure='arc')
        peaks.append(max(m.solve().tension()))
    for p in peaks:
        assert _rel(p, t_true) < 5e-3
    assert _rel(peaks[0], peaks[-1]) < 5e-3


def test_the_results_table_and_the_tension_diagram_report_the_same_peak():
    """The bug that C-1 really was: the tab displayed two different maximum
    tensions at once -- 25.48 kN in the results panel and 25.66 kN in the
    diagram -- and the low one fed the stress check."""
    arc, _, _ = _catenary(SPAN, W, 4000.0)
    m = CableModel(SPAN, arc, n_elem=60)
    m.add_distributed_load(lambda x: W, 0.0, SPAN, measure='arc')
    r = m.solve()
    table_peak = max(r.tension())
    # diagram_series() -> (xs_T, T, xs_F, H, Fy); the diagram plots T and
    # labels its own maximum, which is what the user sees beside the table.
    _, t_series, _, _, _ = r.diagram_series()
    diagram_peak = max(t_series)
    assert _rel(table_peak, diagram_peak) < 2e-3, (
        'results table says %.3f, diagram says %.3f' % (table_peak, diagram_peak))


def test_interior_nodes_are_untouched_by_the_end_correction():
    """Only the two support nodes are computed exactly; the interior stays the
    averaged element value, so the fix cannot have moved the rest of the curve."""
    m = CableModel(SPAN, _parabola_arc_length(SPAN, 2.0), n_elem=20)
    m.add_distributed_load(lambda x: W, 0.0, SPAN, measure='horizontal')
    r = m.solve()
    t_elem = r.element_tension()
    t_node = r.tension()
    for i in range(1, len(t_node) - 1):
        assert t_node[i] == 0.5 * (t_elem[i - 1] + t_elem[i])


# ------------------------------------------------------------ degenerate in

def test_a_cable_shorter_than_its_span_is_refused():
    import pytest
    with pytest.raises(ValueError):
        CableModel(SPAN, SPAN - 1.0, n_elem=20)
    with pytest.raises(ValueError):
        CableModel(SPAN, SPAN, n_elem=20)


def test_a_point_load_outside_the_supports_is_refused():
    import pytest
    m = CableModel(SPAN, 22.0, n_elem=20)
    with pytest.raises(ValueError):
        m.add_point_load(0.0, 1e3)
    with pytest.raises(ValueError):
        m.add_point_load(SPAN + 5.0, 1e3)
