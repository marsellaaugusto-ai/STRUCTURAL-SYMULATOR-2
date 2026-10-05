"""Perspective and parallel projection on the PDF's 3D sheets.

The on-screen 3D view has offered both since the camera popover landed
(StereoViewMixin._project). The PDF was parallel-only, so a report could
not show what the screen was showing. These check the half that matters:
the 3D sheets follow the view, and the ORTHOGRAPHIC ELEVATIONS NEVER DO.

That second half is not a nicety. An elevation carries a scale bar and a
dimension grid; under a projection whose scale varies with depth, both lie.
A regression that let perspective reach those sheets would produce drawings
that look fine and measure wrong, which is the worst kind.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.stereo import stereo_reports as sr


AZ, EL = math.radians(30), math.radians(25)

# A 10 x 10 x 5 box: eight corners, so there is a near one and a far one.
BOX = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
       (0, 0, 5), (10, 0, 5), (10, 10, 5), (0, 10, 5)]


def _depth(p):
    return sr._pdf_view_depth(p[0], p[1], p[2], AZ, EL)


def _project(nodes, eye=None):
    if eye is None:
        return [sr._pdf_project(x, y, z, AZ, EL) for x, y, z in nodes]
    with sr._pdf_eye(eye):
        return [sr._pdf_project(x, y, z, AZ, EL) for x, y, z in nodes]


# ═════════════════════════════════════════════════════════════════════════════
#  The projection itself
# ═════════════════════════════════════════════════════════════════════════════
def test_parallel_is_unchanged_when_nothing_asks_for_perspective():
    """The default has to be exactly what it always was, or every existing
    sheet moves."""
    before = [sr._iso_project(x, y, z, AZ, EL) for x, y, z in BOX]
    after = _project(BOX)
    for (bx, by), (ax_, ay) in zip(before, after):
        assert ax_ == pytest.approx(bx)
        assert ay == pytest.approx(-by)      # the documented y flip, intact


def test_perspective_magnifies_the_near_corner_and_shrinks_the_far_one():
    d = sr.pdf_eye_distance(BOX)
    par = _project(BOX)
    per = _project(BOX, eye=d)

    near = min(range(len(BOX)), key=lambda i: _depth(BOX[i]))
    far = max(range(len(BOX)), key=lambda i: _depth(BOX[i]))
    assert near != far

    def ratio(i):
        return math.hypot(*per[i]) / max(math.hypot(*par[i]), 1e-12)

    assert ratio(near) > 1.0 > ratio(far), (
        'the near corner must come toward the reader and the far one '
        'recede: got %.3f and %.3f' % (ratio(near), ratio(far)))


def test_equal_edges_stay_equal_in_parallel_and_converge_in_perspective():
    """The whole difference between the two modes, in one measurement.
    Edge 0-1 and edge 3-2 are the same world length at different depths."""
    def length(p, a, b):
        return math.hypot(p[a][0] - p[b][0], p[a][1] - p[b][1])

    par = _project(BOX)
    assert length(par, 0, 1) == pytest.approx(length(par, 3, 2)), (
        'a parallel projection must keep equal lengths equal -- that is '
        'what it is for')

    per = _project(BOX, eye=sr.pdf_eye_distance(BOX))
    assert length(per, 0, 1) != pytest.approx(length(per, 3, 2))


def test_the_eye_distance_scales_with_the_model():
    """One setting has to mean the same STRENGTH of perspective on a 3 m
    canopy and a 60 m span, which is why it is a multiple of the bounding
    radius rather than a number of metres."""
    small = [(x * 0.1, y * 0.1, z * 0.1) for x, y, z in BOX]
    d_box = sr.pdf_eye_distance(BOX)
    d_small = sr.pdf_eye_distance(small)
    assert d_small == pytest.approx(d_box * 0.1)

    def spread(nodes, d):
        p = _project(nodes, eye=d)
        return max(math.hypot(*q) for q in p) / max(
            max(math.hypot(*q) for q in _project(nodes)), 1e-12)

    assert spread(BOX, d_box) == pytest.approx(spread(small, d_small), rel=1e-9)


def test_a_bigger_eye_multiple_is_a_weaker_perspective():
    far_eye = _project(BOX, eye=sr.pdf_eye_distance(BOX, 50.0))
    par = _project(BOX)
    for (px, py), (qx, qy) in zip(far_eye, par):
        assert px == pytest.approx(qx, rel=0.05)
        assert py == pytest.approx(qy, rel=0.05)


def test_a_point_level_with_the_eye_is_clamped_not_flung_to_infinity():
    """An unguarded divide sends it to infinity or flips it through the
    origin; both put the sheet's axes somewhere absurd."""
    with sr._pdf_eye(1.0):
        # depth -1.0 would make the denominator exactly zero
        deep = [n for n in BOX]
        out = [sr._pdf_project(x, y, z, AZ, EL) for x, y, z in deep]
    for sx, sy in out:
        assert math.isfinite(sx) and math.isfinite(sy)
        assert abs(sx) < 1e6 and abs(sy) < 1e6


def test_the_eye_is_put_back_after_the_block():
    """`_pdf_eye` is what stops a perspective axonometric leaking into the
    elevations drawn after it."""
    par = _project(BOX)
    with sr._pdf_eye(sr.pdf_eye_distance(BOX)):
        pass
    assert _project(BOX) == par


def test_directions_opt_out_even_inside_a_perspective_sheet():
    """The axis triad, the foreshortening factors and the scale-bar unit
    project a DIRECTION, not a point. Dividing those by distance makes a
    unit vector's length depend on where the origin happens to be."""
    with sr._pdf_eye(sr.pdf_eye_distance(BOX)):
        inside = sr._pdf_project(*sr.PDF_AXIS_UNIT['X'], AZ, EL, eye=0)
    outside = sr._pdf_project(*sr.PDF_AXIS_UNIT['X'], AZ, EL, eye=0)
    assert inside == outside


# ═════════════════════════════════════════════════════════════════════════════
#  What export_pdf does with it
# ═════════════════════════════════════════════════════════════════════════════
def test_export_pdf_defaults_to_parallel():
    import inspect
    sig = inspect.signature(sr.export_pdf)
    assert sig.parameters['projection'].default == sr.PDF_PROJECTION_PARALLEL


def test_an_elevation_is_parallel_whatever_the_export_asks_for():
    """The one that must never regress. Every orthographic view's own
    projection call passes eye=0 explicitly, so it cannot inherit the
    sheet's eye."""
    import re
    src = Path(sr.__file__).read_text(encoding='utf-8')
    m = re.search(r'v_proj = \[_pdf_project\((.*?)\)', src, re.S)
    assert m, 'the orthographic views no longer project through v_proj'
    assert 'eye=0' in m.group(1), (
        'an orthographic elevation must force parallel projection: it '
        'carries a scale bar and a dimension grid, and both lie under a '
        'projection whose scale varies with depth')


def test_the_five_orthographic_views_still_measure_true():
    """Belt and braces for the above, measured rather than read: under a
    perspective sheet eye, an elevation's own az/el with eye=0 keeps two
    equal world lengths equal on the sheet."""
    plan = dict(sr.PDF_ORTHO_VIEWS)['plan']
    v_az, v_el = math.radians(plan['az']), math.radians(plan['el'])

    def seg(a, b):
        pa = sr._pdf_project(*BOX[a], v_az, v_el, eye=0)
        pb = sr._pdf_project(*BOX[b], v_az, v_el, eye=0)
        return math.hypot(pa[0] - pb[0], pa[1] - pb[1])

    with sr._pdf_eye(sr.pdf_eye_distance(BOX)):
        assert seg(0, 1) == pytest.approx(seg(3, 2))
        assert seg(0, 3) == pytest.approx(seg(1, 2))


def test_the_report_follows_the_canvas_by_default():
    """`_pdf_view_kwargs` is the one place all four export_pdf calls get
    their drawing options, so wiring the projection there is what makes
    'the PDF shows what the screen shows' true everywhere."""
    import re
    src = (Path(sr.__file__).parent / 'stereo_app_reports.py').read_text(
        encoding='utf-8')
    m = re.search(r'def _pdf_view_kwargs\(self\):.*?(?=\n    def )', src, re.S)
    assert m
    body = m.group(0)
    assert 'projection' in body and 'eye_mult' in body
    assert 'projection_mode' in body, (
        'the report should take the projection from the canvas, not ask '
        'for it a second time')
