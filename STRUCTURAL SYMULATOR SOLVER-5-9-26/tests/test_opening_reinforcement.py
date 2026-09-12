"""
test_opening_reinforcement.py -- doubler rings around web openings.

The ring is modelled by building the reinforced SECTION and running the
tab's own opening check on it, so most of what could go wrong is
geometric rather than arithmetic:

  * the plate landing somewhere other than against the web (a plate in
    the wrong place is still a plate, and still produces a plausible
    number, so `test_the_ring_sits_against_the_web` checks adjacency
    rather than merely that area went up);
  * the ring being added to the wrong FRAME -- `section_pieces` renders a
    part at internal dx as (dx - cx), and forgetting the +cx puts the
    doubler a centroid-offset away from the hole it is meant to help.

The sizing itself is checked by the property that matters: applying the
returned thickness must actually bring the utilisation home, and a
thicker ring must never make it worse.
"""
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

import pytest

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import section_shapes as shapes
from apps.perforated_beam import section_plastic as sp
from apps.perforated_beam import opening_reinforcement as ring
from apps.perforated_beam import welded_section_math as wsm
from apps.perforated_beam import section_profile_math as secm
from apps.perforated_beam.hyperstatic_math import SupportSpec

L = 50400.0
H, B, T, LT, LB = 1800.0, 250.0, 10.0, 100.0, 200.0
LIPPED_C = [(0., -H/2), (B, -H/2), (B, -H/2+LB), (B-T, -H/2+LB), (B-T, -H/2+T),
            (T, -H/2+T), (T, H/2-T), (B-T, H/2-T), (B-T, H/2-LT), (B, H/2-LT),
            (B, H/2), (0., H/2)]


def box(kind='closed'):
    """The 1800 x 500 lipped-C box: two folded C profiles welded at their
    lips, 10 mm plate. The section the reference report analyses."""
    o = secm.SectionOutline(tuple(LIPPED_C[0]))
    for p in list(LIPPED_C[1:]) + [LIPPED_C[0]]:
        o.segments.append(secm.LineSegment(tuple(p)))
    sk = secm.SectionSketch(o)
    a = sk.to_section('A')
    b = secm.mirror_sketch(sk, horizontal=True).to_section('B')
    return wsm.CompoundSection(
        [wsm.PlacedProfile(a, dx=a.centroid[0], dy=a.centroid[1]),
         wsm.PlacedProfile(b, dx=2 * B - a.centroid[0], dy=b.centroid[1])],
        detail=wsm.AssemblyDetail(kind, plate_thickness=T))


def girder(P=160000.0, w1=6.0, w2=1.6, dia=1350.0, n=28, start=900.0):
    sec = box('closed')
    b = pbm.BeamConfig(L=L, section=sec, material=pbm.Material(Fy=235.0, E=200000.0),
                       openings=pbm.uniform_layout(pbm.opening_circle(dia), n, 1800.0, start),
                       support_specs=[SupportSpec(x) for x in (1800., 16200., 48600.)])
    for i in range(8):
        b.point_loads.append(pbm.PointLoad(i * 7200.0, P))
    b.dist_loads.append(pbm.DistLoad(0.0, L, w1, w1))
    b.dist_loads.append(pbm.DistLoad(18000.0, 46800.0, w2, w2))
    return b


def worst_opening(beam):
    return min(beam.openings, key=lambda o: abs(o.x_center - 17100.0))


# ── geometry ─────────────────────────────────────────────────────────────

def test_the_ring_sits_against_the_web():
    """Adjacency, not just "the area went up". Each plate must share a
    face with a web run and cover a tee, or it is reinforcing air."""
    beam = girder()
    sec = beam.section
    plates = ring.ring_plates(sec, worst_opening(beam), 30.0)
    assert len(plates) == 4, 'two webs x two tees'

    pieces = shapes.section_pieces(sec)
    ext = shapes.section_extents(pieces)
    y_mid = 0.5 * (ext[1] + ext[3])
    runs = sp.material_runs_at(sec, y_mid, pieces)
    faces = {round(a, 6) for a, _b in runs} | {round(b, 6) for _a, b in runs}
    for z0, z1, y0, y1 in plates:
        assert round(z1 - z0, 6) == 30.0
        assert round(z0, 6) in faces or round(z1, 6) in faces, \
            f'plate at z {z0}..{z1} touches no web face {sorted(faces)}'
        assert y0 >= ext[1] - 1e-6 and y1 <= ext[3] + 1e-6


def test_the_ring_covers_the_tee_and_not_the_hole():
    beam = girder()
    op = worst_opening(beam)
    ys = [y for _x, y in op.vertices_local]
    half = (max(ys) - min(ys)) / 2.0
    pieces = shapes.section_pieces(beam.section)
    ext = shapes.section_extents(pieces)
    y_mid = 0.5 * (ext[1] + ext[3])
    for _z0, _z1, y0, y1 in ring.ring_plates(beam.section, op, 20.0):
        assert y1 <= y_mid - half + 1e-6 or y0 >= y_mid + half - 1e-6, \
            'a ring plate crosses the opening it is meant to frame'
        assert (y1 - y0) == pytest.approx(((ext[3] - ext[1]) - 2 * half) / 2.0, rel=1e-6)


def test_the_ring_is_added_in_the_right_frame():
    """`section_pieces` renders a part at internal dx as (dx - cx). Drop
    the +cx and the doubler lands a centroid-offset from the hole -- and
    the area and the inertia still go up, so only a POSITION check
    catches it.

    Position is checked against the WEBS, not against absolute
    coordinates: the plates are symmetric about mid-depth while this
    section's centroid sits 29 mm below it, so adding them moves the
    centroid ~10 mm and every extent with it. Comparing extents would be
    measuring the frame."""
    beam = girder()
    sec = beam.section
    op = worst_opening(beam)
    t_an = 30.0
    reinforced = ring.reinforced_section(sec, op, t_an)

    base_pieces = shapes.section_pieces(sec)
    base_ext = shapes.section_extents(base_pieces)
    depth = base_ext[3] - base_ext[1]
    y_mid = 0.5 * (base_ext[1] + base_ext[3])
    ys = [y for _x, y in op.vertices_local]
    half = (max(ys) - min(ys)) / 2.0

    # sample heights in each section's OWN frame, by fraction of depth
    new_pieces = shapes.section_pieces(reinforced)
    new_ext = shapes.section_extents(new_pieces)

    def runs_at_fraction(section, pieces, ext, f):
        y = ext[1] + f * (ext[3] - ext[1])
        return sp.material_runs_at(section, y, pieces)

    f_tee = ((y_mid + half + (base_ext[3] - (y_mid + half)) / 2.0) - base_ext[1]) / depth
    f_hole = (y_mid - base_ext[1]) / depth

    base_tee = runs_at_fraction(sec, base_pieces, base_ext, f_tee)
    new_tee = runs_at_fraction(reinforced, new_pieces, new_ext, f_tee)
    assert len(new_tee) == len(base_tee), 'the ring split a web instead of thickening it'
    for (a0, b0), (a1, b1) in zip(base_tee, new_tee):
        assert (b1 - a1) == pytest.approx((b0 - a0) + t_an, abs=1e-6), \
            'a web at the tee did not grow by exactly the ring thickness'

    # across the HOLE the ring covers nothing, so the webs are untouched
    base_hole = runs_at_fraction(sec, base_pieces, base_ext, f_hole)
    new_hole = runs_at_fraction(reinforced, new_pieces, new_ext, f_hole)
    assert [round(b - a, 6) for a, b in new_hole] == \
           [round(b - a, 6) for a, b in base_hole], \
        'the ring reaches across the opening it is meant to frame'

    # and the section got wider by a ring on each side, not taller
    assert (new_ext[2] - new_ext[0]) == pytest.approx(
        (base_ext[2] - base_ext[0]) + 2 * t_an, abs=1e-6)
    assert (new_ext[3] - new_ext[1]) == pytest.approx(depth, abs=1e-6)


def test_a_ring_adds_area_and_inertia():
    beam = girder()
    sec = beam.section
    r = ring.reinforced_section(sec, worst_opening(beam), 30.0)
    added = sum((z1 - z0) * (y1 - y0)
                for z0, z1, y0, y1 in ring.ring_plates(sec, worst_opening(beam), 30.0))
    assert r.A == pytest.approx(sec.A + added, rel=1e-6)
    assert r.I > sec.I


def test_zero_thickness_returns_the_section_untouched():
    beam = girder()
    assert ring.reinforced_section(beam.section, worst_opening(beam), 0.0) is beam.section
    assert ring.ring_plates(beam.section, worst_opening(beam), 0.0) == []


# ── sizing ───────────────────────────────────────────────────────────────

def test_an_opening_that_passes_needs_no_ring():
    """Half the load: nothing should be prescribed."""
    beam = girder(P=40000.0, w1=3.0, w2=0.8)
    r = ring.required_ring(beam, beam.openings[0])
    assert r.t_required == 0.0
    assert not r.needs_ring
    assert 'no ring needed' in r.describe()


def test_the_returned_ring_actually_brings_the_check_home():
    """The property that matters. Anything else is bookkeeping."""
    beam = girder()
    op = worst_opening(beam)
    before = ring._util(beam, op)
    assert before > 1.0, 'this fixture must fail without a ring to prove anything'

    r = ring.required_ring(beam, op)
    assert r.needs_ring and r.t_required is not None
    after = ring._util(beam, op, ring.reinforced_section(beam.section, op, r.t_required))
    assert after <= ring.TARGET_UTIL + 1e-6
    assert after == pytest.approx(r.util_ringed, rel=1e-9)


def test_a_thicker_ring_never_makes_it_worse():
    """Monotonicity is what lets the search bisect at all."""
    beam = girder()
    op = worst_opening(beam)
    utils = [ring._util(beam, op, ring.reinforced_section(beam.section, op, t))
             for t in (0.0, 5.0, 10.0, 20.0, 40.0)]
    assert utils == sorted(utils, reverse=True), utils


def test_only_the_openings_near_the_support_need_rings():
    """The whole point of a ring over a thicker web: it is a local fix for
    a local problem. On this beam the shear peak is at the interior
    support, so the rings cluster there and most of the span needs none."""
    beam = girder()
    sched = ring.ring_schedule(beam)
    need = [r for r in sched if r.needs_ring]
    assert 0 < len(need) < len(sched) / 3
    xs = [r.opening.x_center / 1000.0 for r in need]
    assert all(13.0 <= x <= 22.0 for x in xs), xs


def test_the_schedule_rounds_up_to_stock_plate():
    beam = girder()
    sched = ring.ring_schedule(beam)
    grouped = ring.group_schedule(sched, steps=(12.0, 20.0, 30.0))
    for r, t in grouped:
        if r.needs_ring and r.t_required is not None:
            assert t in (12.0, 20.0, 30.0)
            assert t >= r.t_required


def test_an_opening_that_no_ring_can_save_says_so():
    """A hole so deep the tees have nothing left is not a doubler
    problem, and pretending a big enough plate exists would be worse than
    refusing."""
    beam = girder(P=600000.0, dia=1740.0)
    r = ring.required_ring(beam, worst_opening(beam), max_mm=20.0)
    assert r.t_required is None
    assert 'NOT SOLVED' in r.describe() or r.note


# ── the perimeter weld ───────────────────────────────────────────────────

def test_the_ring_weld_is_governed_by_the_code_minimum():
    """A doubler picks up very little shear flow -- 13 N/mm here -- so a
    strength-only answer is a fraction of a millimetre and meaningless.
    Table J.2.4 is what actually decides it, and the result says which."""
    beam = girder()
    op = worst_opening(beam)
    r = ring.required_ring(beam, op)
    w = ring.ring_weld_leg(beam, op, r.t_required)
    assert w.leg_strength < 1.0
    assert w.leg == w.leg_min > 0
    assert 'J.2.4' in w.describe()
    assert w.governed_by == 'the Table J.2.4 minimum'


def test_no_ring_means_no_weld():
    beam = girder()
    assert ring.ring_weld_leg(beam, beam.openings[0], 0.0) is None


# ─────────────────────────────────────────────────────────────────────────
# The Vierendeel METHOD and the ASD target, added 2026-09-10.
#
# The complaint that prompted these: "the app denies the necessity for
# ring reinforcements, while the pdf stresses the necessity of them". The
# schedule was sized on the station scan against unfactored loads with a
# target of 1.0, while the document it was being compared with used the
# hand method, 1.2D+1.6L and ASD. Three separate disagreements, none of
# them visible on either page.
# ─────────────────────────────────────────────────────────────────────────

def test_the_hand_method_asks_for_rings_the_station_scan_does_not():
    """The headline behaviour. On this beam the station scan finds nothing
    to reinforce and the hand method finds a schedule -- and both are
    correct answers to their own question."""
    b = girder()
    op = [o for o in b.openings if abs(o.x_center - 17100.0) < 1.0][0]
    station = ring.required_ring(b, op, method=ring.METHOD_STATION)
    hand = ring.required_ring(b, op, method=ring.METHOD_HAND)
    assert hand.util_plain > station.util_plain
    assert hand.needs_ring
    assert hand.solved


def reference_service_girder():
    """The reference report's OWN load case, unfactored.

    `girder()` above defaults to a beam with double the reference's point
    loads, already factored -- convenient for exercising the ring search,
    and exactly the wrong starting point for reproducing a published
    number. Applying ASD's phi*Omega on top of loads that are already
    factored double-counts, which is the first thing that went wrong when
    these tests were written."""
    from apps.perforated_beam import load_combinations as lc
    b = girder(P=50000.0, w1=5.0, w2=1.0)
    for p in b.point_loads:
        p.case = lc.CASE_L
    for d in b.dist_loads:
        d.case = lc.CASE_D if abs(d.w1 - 5.0) < 1e-9 else lc.CASE_L
    return b


def opening_at_17_1(beam):
    return [o for o in beam.openings if abs(o.x_center - 17100.0) < 1.0][0]


def test_the_hand_method_reproduces_the_reference_ring_thickness():
    """The reference report requires 28.9 mm at x = 17.1 m and recommends
    30 mm stock. This is the number the whole convergence exercise turns
    on: if it drifts, the tab and that document have parted company
    again."""
    from apps.perforated_beam import load_combinations as lc
    combo = lc.ASD_1
    beam = lc.apply(reference_service_girder(), combo)
    r = ring.required_ring(beam, opening_at_17_1(beam), method=ring.METHOD_HAND,
                           target=ring.TARGET_UTIL / combo.util_ratio)
    assert r.util_plain * combo.util_ratio == pytest.approx(3.56, rel=0.05)
    assert r.t_required == pytest.approx(28.9, rel=0.08)


def test_the_sizing_target_moves_for_ASD_rather_than_the_utilisations():
    """The search runs in LRFD form throughout and only the threshold
    moves. A RingResult therefore has to remember the target it searched
    against, or `needs_ring` compares a scaled search with an unscaled 1.0
    and reports a ring it just sized as unnecessary."""
    from apps.perforated_beam import load_combinations as lc
    beam = lc.apply(reference_service_girder(), lc.ASD_1)
    target = ring.TARGET_UTIL / lc.ASD_1.util_ratio
    r = ring.required_ring(beam, opening_at_17_1(beam), method=ring.METHOD_HAND,
                           target=target)
    assert r.target == pytest.approx(target)
    assert r.needs_ring
    assert r.util_ringed <= target + 1e-6


def test_the_schedule_reports_utilisations_in_the_combination_it_was_sized_in():
    """Printed unscaled, a ring sized to exactly 1.00 under ASD reads as
    0.67 and the schedule appears to be solving a problem that was not
    there."""
    from apps.perforated_beam import load_combinations as lc
    beam = lc.apply(reference_service_girder(), lc.ASD_1)
    target = ring.TARGET_UTIL / lc.ASD_1.util_ratio
    r = ring.required_ring(beam, opening_at_17_1(beam), method=ring.METHOD_HAND,
                           target=target)
    assert '-> 1.00' in r.describe(lc.ASD_1.util_ratio)


def test_a_thicker_ring_never_raises_the_hand_method_utilisation():
    """Monotonicity is what justifies bisection, and it has to hold under
    BOTH methods or the search converges on nothing."""
    b = girder()
    op = [o for o in b.openings if abs(o.x_center - 17100.0) < 1.0][0]
    utils = [ring._util(b, op, ring.reinforced_section(b.section, op, t),
                        method=ring.METHOD_HAND)
             for t in (0.0, 5.0, 10.0, 20.0, 40.0)]
    assert utils == sorted(utils, reverse=True)


def test_the_ring_weld_follows_the_method_that_sized_the_ring():
    """V_leg is a statics quantity: the hand method puts a quarter of the
    global shear in each leg, the station scan splits it by the tees'
    relative stiffness. Sizing the plate one way and its weld the other
    would be two details of two different designs."""
    b = girder()
    op = [o for o in b.openings if abs(o.x_center - 17100.0) < 1.0][0]
    w_hand = ring.ring_weld_leg(b, op, 30.0, method=ring.METHOD_HAND)
    w_stat = ring.ring_weld_leg(b, op, 30.0, method=ring.METHOD_STATION)
    assert w_hand is not None and w_stat is not None
    assert w_hand.q != pytest.approx(w_stat.q, rel=1e-6)


def test_the_default_method_is_unchanged():
    """Everything written before today calls these without a method, and
    must keep getting the station scan."""
    b = girder()
    op = b.openings[0]
    assert ring.required_ring(b, op).util_plain == pytest.approx(
        ring.required_ring(b, op, method=ring.METHOD_STATION).util_plain)


def test_a_ROLLED_CATALOG_section_can_be_ringed():
    """A rolled section has no `centroid` attribute, and asking for one
    raised AttributeError -- so ticking "Size doubler rings" on an IPE,
    the commonest section this tab is used with, took the whole analysis
    down with an error dialog. The feature appeared to work only on drawn
    and compound profiles, which carry a centroid because they are
    positioned in a drawing frame."""
    sec = pbm.SECTION_CATALOG['IPE 400']
    assert not hasattr(sec, 'centroid')
    b = pbm.BeamConfig(L=8000.0, section=sec,
                       material=pbm.Material(Fy=250.0, E=200000.0),
                       openings=pbm.uniform_layout(pbm.opening_circle(240.0),
                                                   4, 1500.0, 2000.0))
    b.dist_loads.append(pbm.DistLoad(0.0, 8000.0, 80.0, 80.0))
    op = b.openings[0]
    reinforced = ring.reinforced_section(sec, op, 12.0)
    assert reinforced is not sec
    assert reinforced.A > sec.A
    r = ring.required_ring(b, op)
    assert r is not None


def test_the_ring_lands_against_the_web_on_a_rolled_section_too():
    """The frame trap again, on the path that had never been exercised:
    the plate must thicken the web run at the tee and change nothing
    across the hole."""
    sec = pbm.SECTION_CATALOG['IPE 400']
    op = pbm.OpeningInstance(2000.0, pbm.opening_circle(240.0), 'H1')
    ext = shapes.section_extents(shapes.section_pieces(sec))
    y_mid = 0.5 * (ext[1] + ext[3])
    y_tee = ext[3] - ((ext[3] - ext[1]) - 240.0) / 4.0     # inside the top tee

    before_tee = sp.material_runs_at(sec, y_tee)
    before_hole = sp.material_runs_at(sec, y_mid)
    ringed = ring.reinforced_section(sec, op, 12.0)
    after_tee = sp.material_runs_at(ringed, y_tee)
    after_hole = sp.material_runs_at(ringed, y_mid)

    assert sum(b - a for a, b in after_tee) == pytest.approx(
        sum(b - a for a, b in before_tee) + 2 * 12.0, abs=0.5)
    assert sum(b - a for a, b in after_hole) == pytest.approx(
        sum(b - a for a, b in before_hole), abs=1e-6)


def test_an_open_web_gets_a_ring_on_BOTH_faces():
    """A lone central web has its midpoint exactly at the section's
    mid-width, so the "outer face" test used to put one plate on its left
    and none on its right -- half a ring, silently, on every open
    section. Both faces of an open web are reachable and both are welded."""
    sec = pbm.SECTION_CATALOG['IPE 400']
    op = pbm.OpeningInstance(2000.0, pbm.opening_circle(240.0), 'H1')
    rects = ring.ring_plates(sec, op, 12.0)
    assert len(rects) == 4                       # 2 faces x 2 tees
    ext = shapes.section_extents(shapes.section_pieces(sec))
    y_tee = ext[3] - ((ext[3] - ext[1]) - 240.0) / 4.0
    grew = (sum(b - a for a, b in sp.material_runs_at(
                    ring.reinforced_section(sec, op, 12.0), y_tee))
            - sum(b - a for a, b in sp.material_runs_at(sec, y_tee)))
    assert grew == pytest.approx(24.0, abs=0.5)


def test_a_closed_box_still_takes_a_ring_on_the_OUTER_face_only():
    """Nobody can weld inside a closed cell. The two rules must not be
    confused: this is the case the module was written for."""
    sec = box('closed')
    op = pbm.OpeningInstance(17100.0, pbm.opening_circle(1350.0), 'H1')
    rects = ring.ring_plates(sec, op, 12.0)
    assert len(rects) == 4                       # 2 webs x 1 face x 2 tees
    ext = shapes.section_extents(shapes.section_pieces(sec))
    zmin, zmax = ext[0], ext[2]
    for z0, z1, _y0, _y1 in rects:
        # every plate lies outside the box walls, never in the cavity
        assert z0 < zmin + 1.0 or z1 > zmax - 1.0
