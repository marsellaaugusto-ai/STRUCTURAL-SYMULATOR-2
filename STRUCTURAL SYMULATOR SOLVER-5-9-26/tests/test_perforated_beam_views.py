"""
test_perforated_beam_views.py -- the four drawings in the Perforated Beam
tab actually draw, for every section type, and say true things.

A view is hard to assert on directly, so these tests check the three
things that can genuinely be wrong and that a screenshot review would not
reliably catch:

  1. It drew SOMETHING, and specifically did not draw its own error
     message. `_View.redraw` catches exceptions so a broken view can never
     take the report down with it -- which is right, but it also means a
     failure is silent unless a test looks for it.
  2. The numbers printed on the drawing are formatted legibly. The first
     version produced '2.13e+03e6' for an ordinary moment, by dividing by
     1e6 and then appending 'e6' to a quotient that itself needed an
     exponent.
  3. The scale factors are honest: >= 1 (never squashes), 1.0 when the
     beam is already stocky, and reported on the drawing.
"""
import math
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

import pytest

tk = pytest.importorskip('tkinter')

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import welded_section_math as wsm
from apps.perforated_beam import perforated_beam_views as views
from apps.perforated_beam.hyperstatic_math import SupportSpec


@pytest.fixture(scope='module')
def root():
    import time
    last = None
    for attempt in range(6):
        try:
            r = tk.Tk()
            break
        except tk.TclError as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    else:
        pytest.skip(f'no Tk display after 6 attempts: {last}')
    r.geometry('1100x760')
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


def lipped_c(mirror=False, name='C'):
    t, H, B, LT, LB = 10.0, 1800.0, 250.0, 100.0, 200.0
    pts = [(0.0, -H/2), (B, -H/2), (B, -H/2+LB), (B-t, -H/2+LB), (B-t, -H/2+t),
           (t, -H/2+t), (t, H/2-t), (B-t, H/2-t), (B-t, H/2-LT), (B, H/2-LT),
           (B, H/2), (0.0, H/2)]
    if mirror:
        pts = [(-x, y) for x, y in reversed(pts)]
    return pbm.CustomProfileSection(name, pts)


def box_girder():
    A, B = lipped_c(), lipped_c(True, 'C right')
    cx, cy = A.centroid
    return wsm.CompoundSection(
        [wsm.PlacedProfile(A, dx=cx, dy=cy, label='left'),
         wsm.PlacedProfile(B, dx=500.0 - cx, dy=cy, label='right')],
        welds=[wsm.WeldLine((0.0, -700.0), (0.0, -690.0), label='lip seam')])


def user_beam():
    """The 50.4 m three-support box girder, as described."""
    beam = pbm.BeamConfig(
        L=50400.0, section=box_girder(), material=pbm.Material(Fy=250.0, E=200000.0),
        support_specs=[SupportSpec(1800.0), SupportSpec(16200.0), SupportSpec(48600.0)])
    for i in range(8):
        x = i * 7200.0
        if x <= beam.L:
            beam.point_loads.append(pbm.PointLoad(x, 100000.0))
    beam.dist_loads.append(pbm.DistLoad(0.0, beam.L, 5.0, 5.0))
    beam.dist_loads.append(pbm.DistLoad(18000.0, 46800.0, 1.0, 1.0))
    return beam


def rolled_beam():
    return pbm.BeamConfig(
        L=8000.0, section=pbm.SECTION_CATALOG['IPE 400'], material=pbm.STEEL_A36,
        openings=pbm.uniform_layout(pbm.opening_circle(250.0), 8, 700.0, 700.0),
        point_loads=[pbm.PointLoad(4000.0, 50000.0)],
        dist_loads=[pbm.DistLoad(0.0, 8000.0, 15.0, 15.0)])


def _drawn(pane, view, beam):
    pane.set_model(beam, pbm.analyze_beam(beam))
    pane.select(view)
    pane.master.update_idletasks()
    view.fit()
    pane.master.update_idletasks()
    items = view.canvas.find_all()
    errors = [view.canvas.itemcget(i, 'text') for i in items
              if view.canvas.type(i) == 'text'
              and 'could not be drawn' in view.canvas.itemcget(i, 'text')]
    return items, errors


@pytest.fixture
def pane(root):
    p = views.BeamViewsPane(root)
    p.pack(fill='both', expand=True)
    root.update_idletasks()
    yield p
    p.destroy()


# ── 1. every view draws, for both a rolled and a compound beam ───────────

@pytest.mark.parametrize('beam_name', ['rolled', 'compound'])
@pytest.mark.parametrize('view_name', ['section_view', 'elevation_view',
                                       'diagram_view', 'axon_view'])
def test_view_draws_without_error(pane, beam_name, view_name):
    beam = rolled_beam() if beam_name == 'rolled' else user_beam()
    view = getattr(pane, view_name)
    items, errors = _drawn(pane, view, beam)
    assert not errors, f'{view_name}/{beam_name}: {errors[0]}'
    assert len(items) > 5, f'{view_name}/{beam_name}: only {len(items)} items drawn'


def test_views_before_analyze_say_so(pane):
    for v in pane.views:
        v.redraw()
        texts = [v.canvas.itemcget(i, 'text') for i in v.canvas.find_all()
                 if v.canvas.type(i) == 'text']
        assert any('Analyze' in t for t in texts)


def test_a_section_with_no_geometry_degrades(pane):
    """An unknown section type must produce a polite message, not an
    exception that empties the pane."""
    class Mystery:
        name, A, I, S, d = 'mystery', 1000.0, 1e6, 1e4, 100.0
        Zpl = 1.2e4
    beam = pbm.BeamConfig(L=4000.0, section=Mystery(), material=pbm.STEEL_A36)
    beam.dist_loads.append(pbm.DistLoad(0.0, 4000.0, 5.0, 5.0))
    pane.set_model(beam, None)
    pane.select(pane.section_view)
    pane.master.update_idletasks()
    pane.section_view.fit()
    pane.master.update_idletasks()
    texts = [pane.section_view.canvas.itemcget(i, 'text')
             for i in pane.section_view.canvas.find_all()
             if pane.section_view.canvas.type(i) == 'text']
    assert any('No drawable geometry' in t for t in texts)


# ── 2. number formatting ─────────────────────────────────────────────────

@pytest.mark.parametrize('v', [0.0, 0.5, 36.19, 999.4, 1234.5, 51200.0, 347291.0,
                               2.129e9, -1.865e9, 2.1066e10, 1e-4, -7.3])
def test_fmt_never_emits_two_exponents(v):
    """The bug this guards: dividing by 1e6 and appending 'e6' printed
    '2.13e+03e6' for an ordinary 2.13e9 N.mm moment."""
    s = views._fmt(v)
    assert s.count('e') <= 1, f'{v} -> {s}'
    assert 'e6' not in s or s.endswith('e6') is False or 'e+' not in s


@pytest.mark.parametrize('v,expect', [(0.0, '0'), (36.19, '36.19'),
                                      (51200.0, '51,200'), (347291.0, '347,291')])
def test_fmt_readable_for_ordinary_magnitudes(v, expect):
    assert views._fmt(v) == expect


def test_fmt_uses_scientific_only_when_it_earns_it():
    assert views._fmt(2.129e9) == '2.129e+09'
    assert views._fmt(-1.865e9) == '-1.865e+09'
    assert 'e' not in views._fmt(999999.0)


# ── 3. exaggeration factors ──────────────────────────────────────────────

def test_elevation_exaggeration_is_never_a_squash(pane):
    for beam in (rolled_beam(), user_beam()):
        pane.set_model(beam, pbm.analyze_beam(beam))
        for on in (False, True):
            pane.elevation_view.exaggerate.set(on)
            assert pane.elevation_view._exaggeration() >= 1.0


def test_elevation_is_true_scale_by_default(pane):
    """The default must not distort the geometry. Exaggerating the depth
    turns circular openings into tall ellipses, and a drawing that
    misreports the shape of the holes is worse than one you zoom into."""
    beam = user_beam()                      # 50.4 m / 1.8 m = 28:1
    pane.set_model(beam, pbm.analyze_beam(beam))
    assert pane.elevation_view.exaggerate.get() is False
    assert pane.elevation_view._exaggeration() == 1.0


def test_exaggeration_available_on_request(pane):
    beam = user_beam()
    pane.set_model(beam, pbm.analyze_beam(beam))
    pane.elevation_view.exaggerate.set(True)
    k = pane.elevation_view._exaggeration()
    assert k == pytest.approx(50400.0 / 1800.0 / 6.0, rel=1e-9)
    assert k > 4


def test_stocky_beam_is_drawn_true_even_when_exaggeration_is_asked_for(pane):
    """A beam that already reads as a beam must not be stretched at all,
    even with the checkbox on."""
    beam = pbm.BeamConfig(L=2000.0, section=pbm.SECTION_CATALOG['IPE 400'],
                          material=pbm.STEEL_A36)
    beam.dist_loads.append(pbm.DistLoad(0.0, 2000.0, 10.0, 10.0))
    pane.set_model(beam, pbm.analyze_beam(beam))
    pane.elevation_view.exaggerate.set(True)
    assert pane.elevation_view._exaggeration() == 1.0


def test_axonometric_scales_the_whole_section_not_just_its_width(pane):
    """When the enlargement IS asked for, it applies one factor to both
    the depth and the width. Scaling only the width -- the first attempt
    -- distorted the section's own 1800:500 proportions.

    It is no longer applied by default: drawing the box girder's section
    3.5x too deep against its span was reported as "out of proportion",
    and a drawing that misreports the thing being designed is worse than
    one you have to zoom into. True scale is the default; this checks the
    factor is still right when the user opts in."""
    beam = user_beam()
    pane.set_model(beam, pbm.analyze_beam(beam))
    assert pane.axon_view._section_scale() == 1.0, 'true scale is the default'

    pane.axon_view.exaggerate.set(True)
    k = pane.axon_view._section_scale()
    assert k == pytest.approx(50400.0 / 8.0 / 1800.0, rel=1e-9)
    assert k >= 1.0


# ── 3b. diagram sign conventions ─────────────────────────────────────────

def test_diagram_sign_convention_is_declared():
    """Shear up, moment and deflection down. The first version drew all
    three positive-up, which puts the moment diagram on the compression
    side and makes a sagging beam arch over its supports."""
    titles = [t for t, _ in views.DIAGRAM_ROWS]
    flips = [f for _, f in views.DIAGRAM_ROWS]
    assert flips == [False, True, True]
    assert 'Shear' in titles[0]
    assert 'sagging drawn downward' in titles[1]
    assert 'downward drawn downward' in titles[2]


def test_sagging_moment_is_drawn_below_the_axis(pane):
    """End to end on a simply supported UDL beam, whose moment is sagging
    everywhere and whose deflection is downward everywhere: both peaks
    must be drawn BELOW their row's zero line, and the peak shear ABOVE
    its own."""
    beam = pbm.BeamConfig(L=8000.0, section=pbm.SECTION_CATALOG['IPE 400'],
                          material=pbm.STEEL_A36,
                          dist_loads=[pbm.DistLoad(0.0, 8000.0, 20.0, 20.0)])
    v = pane.diagram_view
    _drawn(pane, v, beam)
    c = v.canvas
    # Group by PLOT BOX, not by proximity to a zero line: for a simply
    # supported beam the deflection is zero at the supports, so one of its
    # markers sits exactly ON its zero line and a distance-based grouping
    # cannot tell which row it belongs to.
    boxes = sorted((c.coords(i) for i in c.find_all()
                    if c.type(i) == 'rectangle'), key=lambda b: b[1])
    assert len(boxes) == 3, f'expected three plot boxes, got {len(boxes)}'

    def in_box(box, y):
        return box[1] - 1 <= y <= box[3] + 1

    zeros = [c.coords(i)[1] for i in c.find_all()
             if c.type(i) == 'line' and c.itemcget(i, 'dash')
             and len(c.coords(i)) == 4
             and abs(c.coords(i)[1] - c.coords(i)[3]) < 0.5]
    ovals = [(c.coords(i)[1] + c.coords(i)[3]) / 2
             for i in c.find_all() if c.type(i) == 'oval']

    rows = []
    for box in boxes:
        rows.append(([z for z in zeros if in_box(box, z)],
                     [y for y in ovals if in_box(box, y)]))
    for zs, ms in rows:
        assert len(zs) == 1 and len(ms) == 2, (zs, ms)

    (z_shear, m_shear), (z_moment, m_moment), (z_defl, m_defl) = rows
    # shear: its positive peak (at the left support) is drawn ABOVE zero
    assert min(m_shear) < z_shear[0] - 1
    # moment: sagging everywhere, so its peak is drawn BELOW zero
    assert max(m_moment) > z_moment[0] + 1
    # deflection: downward everywhere, so its peak is BELOW zero too. The
    # other marker is the zero at a support, which lands on the line.
    assert max(m_defl) > z_defl[0] + 1


# ── 3c. units ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('mm,expect', [(0.0, '0 m'), (1800.0, '1.8 m'),
                                       (16200.0, '16.2 m'), (50400.0, '50.4 m'),
                                       (16763.0, '16.763 m'), (250.0, '0.25 m')])
def test_span_lengths_are_shown_in_metres(mm, expect):
    assert views._m(mm) == expect


def test_elevation_labels_use_metres(pane):
    beam = user_beam()
    _drawn(pane, pane.elevation_view, beam)
    texts = [pane.elevation_view.canvas.itemcget(i, 'text')
             for i in pane.elevation_view.canvas.find_all()
             if pane.elevation_view.canvas.type(i) == 'text']
    joined = '\n'.join(texts)
    assert 'L = 50.4 m' in joined
    assert '1.8 m' in joined and '16.2 m' in joined and '48.6 m' in joined
    assert '50400 mm' not in joined
    # section depth stays in mm, which is how it is specified
    assert 'd = 1,800 mm' in joined


# ── 4. app integration ───────────────────────────────────────────────────

def test_app_wires_the_views_to_analyze(root):
    from apps.perforated_beam.perforated_beam_app import PerforatedBeamApp
    app = PerforatedBeamApp(root)
    app.pack(fill='both', expand=True)
    root.update_idletasks()
    app._load_example()
    app._analyze()
    root.update_idletasks()
    assert app.views.section_view.beam is not None
    assert app.views.diagram_view.beam is not None
    # the report still works, in its own tab
    assert 'Vierendeel' in app.result_text.get('1.0', 'end')
    app.destroy()


# ── the 3D view, reported 2026-09-10 --------------------------------------
#
# "it is out of proportion and i cant tell depth mabye use dashed lines for
# lines that are behind opaque planes. also allow for zoom."


def _box_beam():
    from apps.perforated_beam import welded_section_math as wsm
    from apps.perforated_beam import section_profile_math as secm
    from apps.perforated_beam.hyperstatic_math import SupportSpec
    H, B, T, LT, LB = 1800.0, 250.0, 10.0, 100.0, 200.0
    C = [(0., -H/2), (B, -H/2), (B, -H/2+LB), (B-T, -H/2+LB), (B-T, -H/2+T),
         (T, -H/2+T), (T, H/2-T), (B-T, H/2-T), (B-T, H/2-LT), (B, H/2-LT),
         (B, H/2), (0., H/2)]
    o = secm.SectionOutline(tuple(C[0]))
    for p in list(C[1:]) + [C[0]]:
        o.segments.append(secm.LineSegment(tuple(p)))
    sk = secm.SectionSketch(o)
    a = sk.to_section('A')
    b = secm.mirror_sketch(sk, horizontal=True).to_section('B')
    sec = wsm.CompoundSection(
        [wsm.PlacedProfile(a, dx=a.centroid[0], dy=a.centroid[1]),
         wsm.PlacedProfile(b, dx=2*B - a.centroid[0], dy=b.centroid[1])],
        detail=wsm.AssemblyDetail('closed', plate_thickness=T))
    L = 50400.0
    beam = pbm.BeamConfig(L=L, section=sec, material=pbm.Material(Fy=235.0, E=200000.0),
                          openings=pbm.uniform_layout(pbm.opening_circle(1350.0), 26,
                                                      1800.0, 2700.0),
                          support_specs=[SupportSpec(x) for x in (1800., 16200., 48600.)])
    beam.dist_loads.append(pbm.DistLoad(0.0, L, 6.0, 6.0))
    return beam


def _dashed(view):
    out = []
    for i in view.canvas.find_all():
        try:
            if view.canvas.itemcget(i, 'dash') not in ('', '()'):
                out.append(i)
        except tk.TclError:
            pass
    return out


def test_the_3d_view_is_true_scale_by_default(root):
    """It used to enlarge the cross-section against the span -- x3.5 on
    the box girder -- so the drawing showed a beam that does not exist."""
    beam = _box_beam()
    v = views.AxonometricView(root)
    v.pack(fill='both', expand=True)
    root.update_idletasks()
    try:
        v.set_model(beam, pbm.analyze_beam(beam))
        root.update_idletasks()
        assert v._section_scale() == 1.0
        assert 'true scale' in v.scale_note.cget('text')
    finally:
        v.destroy()


def test_the_enlargement_is_available_and_states_its_factor(root):
    beam = _box_beam()
    v = views.AxonometricView(root)
    v.pack(fill='both', expand=True)
    root.update_idletasks()
    try:
        v.set_model(beam, pbm.analyze_beam(beam))
        v.exaggerate.set(True)
        v.fit()
        root.update_idletasks()
        assert v._section_scale() > 3.0
        assert 'x3.5' in v.scale_note.cget('text')
    finally:
        v.destroy()


def test_edges_behind_material_are_drawn_dashed(root):
    """The depth cue that was missing entirely: every edge was solid
    whether it sat at the front of the section or behind 500 mm of
    steel."""
    beam = _box_beam()
    v = views.AxonometricView(root)
    v.pack(fill='both', expand=True)
    root.update_idletasks()
    try:
        v.set_model(beam, pbm.analyze_beam(beam))
        root.update_idletasks()
        assert len(_dashed(v)) > 0, 'nothing was drawn as hidden'
    finally:
        v.destroy()


def test_openings_are_drawn_on_every_web_not_just_the_front_one(root):
    """A box has two webs. Drawing the holes on one plane made it read as
    a single plate -- 26 solid outlines at the front, 26 dashed behind."""
    beam = _box_beam()
    v = views.AxonometricView(root)
    v.pack(fill='both', expand=True)
    root.update_idletasks()
    try:
        v.set_model(beam, pbm.analyze_beam(beam))
        root.update_idletasks()
        rings = [i for i in v.canvas.find_all() if len(v.canvas.coords(i)) >= 90]
        solid = [i for i in rings if v.canvas.type(i) == 'polygon']
        hidden = [i for i in rings if v.canvas.type(i) == 'line']
        assert len(solid) == len(beam.openings)
        assert len(hidden) == len(beam.openings)
    finally:
        v.destroy()


def test_the_view_has_working_zoom_controls(root):
    """The wheel always zoomed; there was nothing on screen to say so."""
    beam = _box_beam()
    v = views.AxonometricView(root)
    v.pack(fill='both', expand=True)
    root.update_idletasks()
    try:
        v.set_model(beam, pbm.analyze_beam(beam))
        root.update_idletasks()
        z0 = v.zc.zoom
        v._zoom_by(1.25)
        assert v.zc.zoom > z0
        v._zoom_by(1 / 1.25)
        assert v.zc.zoom == pytest.approx(z0, rel=1e-9)
        v.fit()
        assert v.zc.zoom > 0
    finally:
        v.destroy()


def test_occlusion_knows_the_near_web_from_the_far_one():
    """The geometric core, checked without a canvas: a point on the near
    web is visible, the matching point on the far web is not."""
    from apps.perforated_beam import section_shapes as shapes
    beam = _box_beam()
    pieces = shapes.section_pieces(beam.section)
    ext = shapes.section_extents(pieces)
    y_mid = 0.5 * (ext[1] + ext[3])
    assert not shapes.occluded_in_section(pieces, ext[0] + 1.0, y_mid)
    assert shapes.occluded_in_section(pieces, ext[2] - 1.0, y_mid)
