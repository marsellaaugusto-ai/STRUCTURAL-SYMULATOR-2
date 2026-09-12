"""
test_section_plastic.py -- plastic modulus and web geometry from polygons.

The load-bearing test is `test_generic_Zx_reproduces_the_rolled_closed_form`.
`RolledSection` already computes Zpl in closed form; this module computes
the same quantity by bisecting for the equal-area axis and integrating
the two halves. They are the same integral by different routes, so they
agree to floating point or one of them is wrong. That is the only check
that can validate the generic path on shapes where no closed form exists
to compare against -- the same discipline test_general_net_section.py
uses against net_section_at.
"""
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

import math
import pytest

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import welded_section_math as wsm
from apps.perforated_beam import section_profile_math as secm
from apps.perforated_beam import section_plastic as sp
import cirsoc_301 as cirsoc


# ── fixtures ─────────────────────────────────────────────────────────────

H, B, T, LT, LB = 1800.0, 250.0, 10.0, 100.0, 200.0
LIPPED_C = [(0., -H/2), (B, -H/2), (B, -H/2+LB), (B-T, -H/2+LB), (B-T, -H/2+T),
            (T, -H/2+T), (T, H/2-T), (B-T, H/2-T), (B-T, H/2-LT), (B, H/2-LT),
            (B, H/2), (0., H/2)]


def drawn(pts, name='p'):
    o = secm.SectionOutline(tuple(pts[0]))
    for p in list(pts[1:]) + [pts[0]]:
        o.segments.append(secm.LineSegment(tuple(p)))
    return secm.SectionSketch(o).to_section(name)


def rect(b, h):
    return drawn([(-b/2, -h/2), (b/2, -h/2), (b/2, h/2), (-b/2, h/2)], 'rect')


def box(kind='closed'):
    a = drawn(LIPPED_C, 'A')
    sk = secm.SectionSketch(secm.SectionOutline((0., 0.)))
    o = secm.SectionOutline(tuple(LIPPED_C[0]))
    for p in list(LIPPED_C[1:]) + [LIPPED_C[0]]:
        o.segments.append(secm.LineSegment(tuple(p)))
    b = secm.mirror_sketch(secm.SectionSketch(o), horizontal=True).to_section('B')
    return wsm.CompoundSection(
        [wsm.PlacedProfile(a, dx=a.centroid[0], dy=a.centroid[1]),
         wsm.PlacedProfile(b, dx=2*B - a.centroid[0], dy=b.centroid[1])],
        detail=wsm.AssemblyDetail(kind, plate_thickness=T))


# ── the cross-check ──────────────────────────────────────────────────────

@pytest.mark.parametrize('name', list(pbm.SECTION_CATALOG))
def test_generic_Zx_reproduces_the_rolled_closed_form(name):
    """Same integral, two routes. Anything but agreement means one is
    wrong, and the generic one is the one with no independent check on
    the shapes it exists for."""
    sec = pbm.SECTION_CATALOG.get(name)
    if sec is None:
        pytest.skip(f'{name} not in the catalog')
    generic = sp.plastic_modulus_from_geometry(sec)
    assert generic == pytest.approx(sec.Zpl, rel=1e-9)


def test_rectangle_matches_the_textbook_formula():
    """Zx = b*h^2/4 for a solid rectangle -- the one case anyone can check
    by hand, and the sanity floor under everything else here."""
    b, h = 120.0, 400.0
    assert sp.plastic_modulus_from_geometry(rect(b, h)) == pytest.approx(b * h**2 / 4.0, rel=1e-9)


def test_plastic_modulus_exceeds_the_elastic_one():
    """Zx > Sx always, and for a rectangle the shape factor is exactly
    1.5. A generic routine that quietly returned the ELASTIC modulus
    would pass a bare 'is it positive' test and fail this one."""
    r = rect(120.0, 400.0)
    assert sp.plastic_modulus_from_geometry(r) / r.S == pytest.approx(1.5, rel=1e-9)
    bx = box()
    assert sp.plastic_modulus_from_geometry(bx) > bx.S


# ── the plastic neutral axis itself ──────────────────────────────────────

def test_pna_splits_the_area_in_half():
    bx = box()
    pieces = sp._pieces(bx)
    y = sp.plastic_neutral_axis(bx, pieces)
    above = sp._area_above(pieces, y)
    assert above == pytest.approx(bx.A / 2.0, rel=1e-7)


def test_pna_equals_the_centroid_for_a_symmetric_section():
    r = rect(120.0, 400.0)
    assert sp.plastic_neutral_axis(r) == pytest.approx(0.0, abs=1e-6)


def test_pna_differs_from_the_centroid_when_the_section_is_asymmetric():
    """The lipped-C box has a 200 mm bottom lip against a 100 mm top one.
    Its equal-AREA axis and its elastic centroid are different heights,
    and a routine that used the centroid for both would be wrong in a way
    no symmetric test could reveal."""
    bx = box()
    y_pna = sp.plastic_neutral_axis(bx)
    y_el = bx.centroid[1]
    assert abs(y_pna - y_el) > 1.0, 'test section is not asymmetric enough to prove anything'


def test_Zx_is_reported_for_every_section_type_the_tab_can_build():
    """The whole point: none of these had a Zpl before."""
    for label, sec in [('channel', pbm.CHANNEL_CATALOG['UPN 220']),
                       ('drawn', drawn(LIPPED_C)),
                       ('closed box', box('closed')),
                       ('open pair', box('open'))]:
        z = sp.plastic_modulus(sec)
        assert z > 0, label
        assert z > sec.S, f'{label}: Zx must exceed Sx'


def test_plastic_modulus_prefers_a_sections_own_closed_form():
    """A RolledSection keeps its exact value; the generic route is only
    consulted where there is nothing."""
    sec = pbm.SECTION_CATALOG['IPE 400']
    assert sp.plastic_modulus(sec) == sec.Zpl


# ── web geometry ─────────────────────────────────────────────────────────

def test_web_of_a_rolled_I_is_the_single_web_plate():
    sec = pbm.SECTION_CATALOG['IPE 400']
    w = sp.web_properties(sec)
    assert w.n_webs == 1
    assert w.t_min == pytest.approx(sec.tw, rel=1e-6)
    assert w.Aw == pytest.approx(sec.d * sec.tw, rel=1e-6)


def test_web_of_a_box_is_two_plates_summed_for_area_and_thinnest_for_slenderness():
    """The distinction that matters. Treating the two 10 mm plates as one
    20 mm web would halve h/tw and roughly double Cv -- unconservative by
    a factor of two on shear buckling."""
    w = sp.web_properties(box())
    assert w.n_webs == 2
    assert w.t_total == pytest.approx(2 * T, rel=1e-6)
    assert w.t_min == pytest.approx(T, rel=1e-6)
    assert w.Aw == pytest.approx(H * 2 * T, rel=1e-6)      # 36,000 mm^2
    assert w.h_tw == pytest.approx(H / T, rel=1e-6)        # 180, not 90
    assert 'THINNEST' in w.note


def test_material_runs_find_the_separate_plates():
    runs = sp.material_runs_at(box(), 0.0)
    assert len(runs) == 2
    widths = sorted(b - a for a, b in runs)
    assert widths == pytest.approx([T, T], rel=1e-6)


def test_material_runs_deduct_a_hole():
    """A bolt hole through a plate splits the run in two."""
    o = secm.SectionOutline((-100.0, -100.0))
    for p in [(100., -100.), (100., 100.), (-100., 100.)]:
        o.add_line(p)
    sk = secm.SectionSketch(o)
    sk.holes.append(secm.CircleLoop((0.0, 0.0), 40.0))
    runs = sp.material_runs_at(sk.to_section('holed'), 0.0)
    assert len(runs) == 2
    assert sum(b - a for a, b in runs) == pytest.approx(200.0 - 80.0, rel=1e-3)



# ── Chapter G: stiffener spacing, and Chapter F7 on a box ────────────────

def _girder(stiff=None, Lb=0.0, Cb=1.0, openings=True):
    from apps.perforated_beam.hyperstatic_math import SupportSpec
    ops = (pbm.uniform_layout(pbm.opening_circle(1350.0), 28, 1800.0, 900.0)
           if openings else [])
    b = pbm.BeamConfig(L=50400.0, section=box('closed'),
                       material=pbm.Material(Fy=235.0, E=200000.0),
                       openings=ops,
                       support_specs=[SupportSpec(x) for x in (1800., 16200., 48600.)],
                       Lb=Lb, Cb=Cb, stiffener_spacing=stiff)
    for i in range(8):
        b.point_loads.append(pbm.PointLoad(i * 7200.0, 80000.0))
    b.dist_loads.append(pbm.DistLoad(0.0, 50400.0, 6.0, 6.0))
    b.dist_loads.append(pbm.DistLoad(18000.0, 46800.0, 1.6, 1.6))
    return b


def test_declaring_stiffeners_doubles_the_shear_buckling_capacity():
    """kv = 5 + 5/(a/h)^2 (G.2.6). At a = h that is 10 against the
    unstiffened 5, and Cv is linear in kv in the elastic range -- so the
    beam is twice as strong in shear as the default assumes. The default
    stays UNSTIFFENED because that is conservative, not because it is a
    guess that there are none."""
    plain = pbm.member_check(_girder(stiff=None))
    stiff = pbm.member_check(_girder(stiff=1800.0))
    assert plain.shear.Cv == pytest.approx(0.198, abs=0.002)
    assert stiff.shear.Cv == pytest.approx(0.397, abs=0.002)
    assert stiff.shear.Vn == pytest.approx(2 * plain.shear.Vn, rel=1e-6)
    assert 'G.2.6' in stiff.shear.note


def test_stiffeners_too_far_apart_fall_back_to_unstiffened():
    """G.2.1(b): past a/h = 3 the panel is too long in plan for the
    stiffeners to force the shorter buckling half-wave the formula
    assumes, so kv reverts to 5 rather than tending to it."""
    far = pbm.member_check(_girder(stiff=3 * 1800.0 + 1))
    assert far.shear.Cv == pytest.approx(0.198, abs=0.002)
    assert 'UNSTIFFENED' in far.shear.note


def test_box_girder_matches_the_reference_report():
    """Against 'Analisis_Viga_Alveolar_Ramas_de_Diseno' (2026-09-07),
    LRFD, t = 10 mm, stiffeners at 1.8 m. The section properties differ
    by ~2.5% because that report's mid-line model double-counts the
    corner squares where flange meets web; the checks agree."""
    m = pbm.member_check(_girder(stiff=1800.0))
    assert abs(m.Mu) / 1e6 == pytest.approx(1765.3, rel=0.01)     # kN.m
    assert abs(m.Vu) / 1e3 == pytest.approx(330.0, rel=0.01)      # kN
    assert m.shear.Aw == pytest.approx(36000.0, rel=1e-6)
    assert m.shear.h_tw == pytest.approx(180.0, rel=1e-6)
    assert m.shear.Vn / 1e3 == pytest.approx(2013.7, rel=0.01)
    assert m.util_flexure == pytest.approx(0.37, abs=0.01)
    assert m.util_shear == pytest.approx(0.18, abs=0.01)


def test_openings_reduce_the_torsion_constant_used_for_LTB():
    """Bredt's J assumes an unbroken cell; the openings cut it. Using the
    gross J is unconservative wherever J enters a stability check, and
    F7's Lp and Lr both scale with sqrt(J)."""
    J_gross = box('closed').J
    J_eff = pbm.effective_torsion_constant(_girder(stiff=1800.0))
    assert J_eff < J_gross
    # web post 450 mm over a 1800 mm pitch
    assert J_eff == pytest.approx(J_gross * 450.0 / 1800.0, rel=1e-9)
    assert pbm.effective_torsion_constant(_girder(openings=False)) is None


def test_a_box_is_checked_by_F7_not_F2():
    """F2's Lr runs through Cw = Iy*h0^2/4, an open-I identity a closed
    cell does not have. The clause that ran is named in the result."""
    m = pbm.member_check(_girder(stiff=1800.0, Lb=28800.0, Cb=1.19))
    assert 'F7' in m.flexure.governing
    assert m.flexure.Lr / 1000.0 == pytest.approx(213.4, rel=0.02)   # metres


def test_a_slender_box_wall_is_reported_rather_than_passed_over():
    """The reference report did not check the box walls at all. Both of
    this one's are slender, and F7 does not cover that -- so the result
    says the cap it applied is an upper bound, not a safe value."""
    m = pbm.member_check(_girder(stiff=1800.0))
    assert m.flexure.flange_class == cirsoc.SLENDER
    assert m.flexure.web_class == cirsoc.SLENDER
    assert 'UPPER BOUND' in m.flexure.note
    assert m.flexure.Mn == pytest.approx(m.flexure.My, rel=1e-9)

# ── which Chapter F clause ───────────────────────────────────────────────

def test_flexural_family_is_declared_not_guessed():
    """A closed box and a stitched pair have identical polygons. Only the
    AssemblyDetail distinguishes them, and it must, because F7 assumes a
    torsionally closed section."""
    assert sp.flexural_family(pbm.SECTION_CATALOG['IPE 400']) == sp.ROLLED_I
    assert sp.flexural_family(box('closed')) == sp.BOX
    assert sp.flexural_family(box('open')) == sp.GENERAL
    assert sp.flexural_family(drawn(LIPPED_C)) == sp.GENERAL


def test_a_section_with_no_geometry_is_refused_clearly():
    class Opaque:
        A = 100.0
        I = 1000.0
    with pytest.raises(ValueError, match='reports no geometry'):
        sp.plastic_modulus_from_geometry(Opaque())

