"""
test_section_shapes.py -- the drawn outline must agree with the numbers.

The whole point of section_shapes.py is to let the tab draw what it is
computing. A picture that disagreed with the computed A or I would be
worse than no picture at all, so every test here compares the POLYGON
against the section's own property, for each section type in the tab.

  1. test_area_matches_* -- polygon area (outline less holes) equals
     section.A, for rolled I, channel, drawn profile, drawn profile with
     holes, oriented, built-up double, double channel, and compound.
  2. test_inertia_matches_* -- the same for I, which additionally proves
     the pieces are positioned correctly and not merely sized correctly.
  3. test_origin_is_the_centroid -- the frame contract every view relies
     on to draw the neutral axis at y = 0.
  4. test_rotate90_swaps_the_extents -- OrientedSection's geometry must
     follow the same transform as its properties.
  5. test_unknown_section_degrades -- returns [], never raises.
"""
import math
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

import pytest

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import welded_section_math as wsm
from apps.perforated_beam import section_shapes as shapes


def poly_area(pts):
    n = len(pts)
    return abs(sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1]
                   for i in range(n))) / 2.0


def pieces_area(pieces):
    return sum(poly_area(p.outline) - sum(poly_area(h) for h in p.holes)
               for p in pieces)


def pieces_I(pieces):
    """Second moment about y=0 of the drawn geometry, holes subtracted.
    The frame contract puts the centroid at the origin, so this is directly
    comparable with section.I."""
    total = 0.0
    for p in pieces:
        _, _, _, ixx, _ = pbm._loop_integrals(p.outline)
        total += ixx
        for h in p.holes:
            _, _, _, hxx, _ = pbm._loop_integrals(h)
            total -= hxx
    return total


def rect(w, h, name='r'):
    return pbm.CustomProfileSection(
        name, [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)])


IPE = pbm.SECTION_CATALOG['IPE 400']
UPN = pbm.CHANNEL_CATALOG['UPN 220']


def _lipped_c(mirror=False, name='C'):
    """The user's folded profile: 1800 deep, 250 base, 100/200 lips, t=10."""
    t, H, B, LT, LB = 10.0, 1800.0, 250.0, 100.0, 200.0
    pts = [(0.0, -H / 2), (B, -H / 2), (B, -H / 2 + LB), (B - t, -H / 2 + LB),
           (B - t, -H / 2 + t), (t, -H / 2 + t), (t, H / 2 - t), (B - t, H / 2 - t),
           (B - t, H / 2 - LT), (B, H / 2 - LT), (B, H / 2), (0.0, H / 2)]
    if mirror:
        pts = [(-x, y) for x, y in reversed(pts)]
    return pbm.CustomProfileSection(name, pts)


SECTIONS = {
    'rolled I': IPE,
    'channel': UPN,
    'drawn rect': rect(200, 400),
    'drawn with hole': pbm.CustomProfileSection(
        'box', [(-50, -50), (50, -50), (50, 50), (-50, 50)],
        [[(-40, -40), (40, -40), (40, 40), (-40, 40)]]),
    'oriented rotated': pbm.OrientedSection(IPE, rotate90=True),
    'oriented mirrored': pbm.OrientedSection(rect(200, 400), mirror=True),
    'built-up double': pbm.BuiltUpDoubleSection(IPE, gap=200.0),
    'double channel': pbm.BuiltUpDoubleChannelSection(UPN, overall_width=350.0),
    'lipped C': _lipped_c(),
}


@pytest.mark.parametrize('name', sorted(SECTIONS))
def test_area_matches_the_section_property(name):
    sec = SECTIONS[name]
    pieces = shapes.section_pieces(sec)
    assert pieces, f'{name}: no geometry produced'
    assert pieces_area(pieces) == pytest.approx(sec.A, rel=1e-9), name


@pytest.mark.parametrize('name', sorted(SECTIONS))
def test_inertia_matches_the_section_property(name):
    """Stronger than the area check: I is position-sensitive, so this also
    proves the pieces are placed correctly, not merely sized correctly."""
    sec = SECTIONS[name]
    pieces = shapes.section_pieces(sec)
    assert pieces_I(pieces) == pytest.approx(sec.I, rel=1e-6), name


@pytest.mark.parametrize('name', sorted(SECTIONS))
def test_origin_is_the_centroid(name):
    """The frame contract every view depends on: y = 0 is the neutral axis,
    so extreme-fibre distances can be drawn as literal distances."""
    sec = SECTIONS[name]
    pieces = shapes.section_pieces(sec)
    A = pieces_area(pieces)
    sx = 0.0
    for p in pieces:
        _, psx, _, _, _ = pbm._loop_integrals(p.outline)
        sx += psx
        for h in p.holes:
            _, hsx, _, _, _ = pbm._loop_integrals(h)
            sx -= hsx
    assert sx / A == pytest.approx(0.0, abs=1e-6 * max(1.0, sec.d)), name


def test_extents_match_the_section_depth():
    for name, sec in SECTIONS.items():
        ext = shapes.section_extents(shapes.section_pieces(sec))
        assert ext is not None
        assert ext[3] - ext[1] == pytest.approx(sec.d, rel=1e-6), name


def test_rotate90_swaps_the_extents():
    up = shapes.section_extents(shapes.section_pieces(IPE))
    rot = shapes.section_extents(shapes.section_pieces(
        pbm.OrientedSection(IPE, rotate90=True)))
    assert (rot[3] - rot[1]) == pytest.approx(up[2] - up[0], rel=1e-9)
    assert (rot[2] - rot[0]) == pytest.approx(up[3] - up[1], rel=1e-9)


# ── the user's box girder ────────────────────────────────────────────────

def test_user_box_girder_geometry():
    """Two lipped C's, lips welded, zero gap -- drawn as two pieces, not
    one, because they are two separate folded profiles."""
    A_c, B_c = _lipped_c(), _lipped_c(mirror=True, name='C right')
    cx, cy = A_c.centroid
    box = wsm.CompoundSection([
        wsm.PlacedProfile(A_c, dx=cx, dy=cy, label='left'),
        wsm.PlacedProfile(B_c, dx=2 * 250.0 - cx, dy=cy, label='right'),
    ])
    pieces = shapes.section_pieces(box)
    assert len(pieces) == 2
    assert pieces_area(pieces) == pytest.approx(box.A, rel=1e-9)
    assert pieces_I(pieces) == pytest.approx(box.I, rel=1e-6)
    ext = shapes.section_extents(pieces)
    assert ext[3] - ext[1] == pytest.approx(1800.0, rel=1e-9)   # depth
    assert ext[2] - ext[0] == pytest.approx(500.0, rel=1e-9)    # overall width


def test_compound_pieces_do_not_overlap_when_butted():
    """The two C's meet at their lips; drawn geometry must not double up."""
    A_c, B_c = _lipped_c(), _lipped_c(mirror=True, name='C right')
    cx, cy = A_c.centroid
    box = wsm.CompoundSection([wsm.PlacedProfile(A_c, dx=cx, dy=cy),
                               wsm.PlacedProfile(B_c, dx=2 * 250.0 - cx, dy=cy)])
    left, right = shapes.section_pieces(box)
    assert left.bbox()[2] == pytest.approx(right.bbox()[0], abs=1e-6)


# ── welds and elevation ──────────────────────────────────────────────────

def test_weld_lines_come_back_in_the_same_frame():
    sec = rect(200, 400)
    wp = wsm.WeldedProfile(sec, [wsm.WeldLine((-100.0, 0.0), (100.0, 0.0), label='seam')])
    welds = shapes.section_welds(wp)
    assert len(welds) == 1
    p1, p2, label = welds[0]
    assert label == 'seam'
    assert p1[1] == pytest.approx(0.0) and p2[1] == pytest.approx(0.0)


def test_opening_outlines_are_on_the_beam_axis():
    """Openings must come back measured from mid-depth, matching the beam
    profile drawn around them -- not from the soffit."""
    beam = pbm.BeamConfig(
        L=8000.0, section=IPE, material=pbm.STEEL_A36,
        openings=pbm.uniform_layout(pbm.opening_circle(250.0), 4, 700.0, 1000.0))
    outs = shapes.opening_outlines(beam)
    assert len(outs) == 4
    for _label, pts in outs:
        ys = [p[1] for p in pts]
        assert min(ys) == pytest.approx(-125.0, abs=1.0)
        assert max(ys) == pytest.approx(125.0, abs=1.0)


def test_beam_profile_outline():
    beam = pbm.BeamConfig(L=8000.0, section=IPE, material=pbm.STEEL_A36)
    box, flanges = shapes.beam_profile_outline(beam)
    assert len(box) == 4 and len(flanges) == 2
    assert box[2][0] == pytest.approx(8000.0)
    assert box[2][1] == pytest.approx(200.0)


def test_unknown_section_degrades_to_empty():
    class Mystery:
        A, I, S, d = 1000.0, 1e6, 1e4, 100.0
    assert shapes.section_pieces(Mystery()) == []
    assert shapes.section_extents([]) is None


def test_isometric_is_a_projection_not_a_rotation():
    assert shapes.isometric(0, 0, 0) == (0.0, 0.0)
    x, y = shapes.isometric(100, 50, 0)
    assert (x, y) == (100.0, 50.0)          # z = 0 plane is undistorted
    x2, y2 = shapes.isometric(0, 0, 100)
    assert x2 > 0 and y2 > 0                # depth recedes up-right
