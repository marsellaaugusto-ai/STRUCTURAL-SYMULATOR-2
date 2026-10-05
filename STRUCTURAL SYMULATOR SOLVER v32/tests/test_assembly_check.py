"""
test_assembly_check.py -- does the compound section hold together?

WHY THIS EXISTS. A user built a box girder from two lipped C profiles
whose offsets left them 1.94 mm apart, declared the assembly a closed
cell, and got a full report of composite section properties for a
section that is two separate channels. Nothing in the tab could have
told them. The failure is invisible by construction: every number goes
UP when you glue two pieces together in software, so a wrong answer
looks like a healthy one.

The tests therefore centre on the gapped case, and on the pair of frame
conversions that decide whether the measurement means anything at all.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import welded_section_math as wsm
from apps.perforated_beam import assembly_check as ac
import cirsoc_301 as cirsoc


LIPPED_C = [
    (0.0, 0.0), (250.0, 0.0), (250.0, 200.0), (240.0, 200.0), (240.0, 10.0),
    (10.0, 10.0), (10.0, 1790.0), (240.0, 1790.0), (240.0, 1700.0),
    (250.0, 1700.0), (250.0, 1800.0), (0.0, 1800.0),
]


def two_channels(gap=0.0, welds=()):
    """The reference box, with a controllable clear gap between the lips."""
    a = pbm.CustomProfileSection('C left', LIPPED_C)
    b = pbm.CustomProfileSection('C right', [(-x, y) for x, y in reversed(LIPPED_C)])
    cx = a.centroid[0]
    # Touching when the centroids are (500 - 2*cx) apart; `gap` opens it.
    return wsm.CompoundSection(
        [wsm.PlacedProfile(a, dx=0.0, dy=0.0, label='A'),
         wsm.PlacedProfile(b, dx=500.0 - 2 * cx + gap, dy=0.0, label='B')],
        welds=list(welds),
        detail=wsm.AssemblyDetail('closed', plate_thickness=10.0))


def seam_weld(section, y_lo, y_hi):
    """A vertical weld line on the seam, in the PLACED frame the section
    stores welds in."""
    cx, _cy = section.centroid
    ext = pbm  # noqa: F841  (kept for readability of the frame comment below)
    # The seam sits at the section's own mid-width, which in the placed
    # frame is the centroid's x for this symmetric pair.
    return wsm.WeldLine(p1=(cx, y_lo), p2=(cx, y_hi), label='SEAM')


# ── the gap ──────────────────────────────────────────────────────────────

def test_touching_parts_report_contact():
    gaps = ac.part_gaps(two_channels(gap=0.0))
    assert len(gaps) == 1
    assert gaps[0].touching
    assert gaps[0].gap == pytest.approx(0.0, abs=ac.TOUCH_TOL_MM)


@pytest.mark.parametrize('gap', [1.94, 5.0, 25.0])
def test_a_gap_is_measured_to_its_real_size(gap):
    g = ac.part_gaps(two_channels(gap=gap))[0]
    assert not g.touching
    assert g.gap == pytest.approx(gap, abs=0.02)


def test_the_users_own_offsets_are_caught():
    """1.94 mm: the real number from the workbook that prompted this."""
    g = ac.part_gaps(two_channels(gap=1.94))[0]
    assert g.gap == pytest.approx(1.94, abs=0.02)
    assert 'APART' in g.describe()


def test_a_hair_of_numerical_noise_is_not_a_gap():
    """Polygon arithmetic does not land on 0.000000. A tolerance below any
    fabrication gap and above the clipping noise floor is the whole point
    of TOUCH_TOL_MM; without it every healthy section would be reported
    as broken and the warning would be ignored."""
    assert ac.part_gaps(two_channels(gap=1e-6))[0].touching


def test_a_single_part_section_has_nothing_to_say():
    single = pbm.SECTION_CATALOG['IPE 400']
    assert ac.part_gaps(single) == []


# ── the audit ────────────────────────────────────────────────────────────

def test_a_healthy_section_produces_no_noise():
    sec = two_channels(gap=0.0)
    assert ac.audit(sec, detail=sec.detail) == []


def test_the_audit_says_the_section_properties_cannot_be_trusted():
    sec = two_channels(gap=1.94)
    text = '\n'.join(ac.audit(sec, detail=sec.detail))
    assert 'DO NOT TOUCH' in text
    assert 'as if they act as one piece' in text


def test_a_declared_closed_cell_over_a_gap_is_called_out_specifically():
    """J and the torsional stress come from Bredt around the cell. Over a
    gap they are not approximate; they describe a different section."""
    sec = two_channels(gap=1.94)
    text = '\n'.join(ac.audit(sec, detail=sec.detail))
    assert 'CLOSED CELL' in text
    assert 'they are wrong' in text


def test_no_closed_cell_claim_when_none_was_declared():
    sec = two_channels(gap=1.94)
    text = '\n'.join(ac.audit(sec, detail=None))
    assert 'DO NOT TOUCH' in text
    assert 'CLOSED CELL' not in text


# ── the weld walk ────────────────────────────────────────────────────────

def test_the_walk_reads_the_plate_thickness_on_each_side():
    sec = two_channels(gap=0.0)
    c = ac.weld_contact(sec, seam_weld(sec, 850.0, 950.0))
    assert c.found_both
    assert c.t_thicker == pytest.approx(10.0, abs=0.4)
    assert c.t_thinner == pytest.approx(10.0, abs=0.4)


def test_the_walk_does_not_stop_on_the_boundary_it_starts_from():
    """A weld line sits ON the interface it welds, so the sample exactly
    at d = 0 is on a polygon boundary and may read either way. Reading it
    as solid ends the run one step later and reports a 0.2 mm plate --
    which is what happened before the walk was moved one step out."""
    sec = two_channels(gap=0.0)
    c = ac.weld_contact(sec, seam_weld(sec, 850.0, 950.0))
    assert c.t_thinner > 5.0


def test_the_measured_thickness_drives_the_code_minimum():
    """The point of measuring at all: Tabla J.2.4 needs a thickness, and
    without one the seam of a symmetric box sizes to 0.0 mm."""
    sec = two_channels(gap=0.0)
    c = ac.weld_contact(sec, seam_weld(sec, 850.0, 950.0))
    assert cirsoc.min_fillet_leg(c.t_thicker) == pytest.approx(5.0)


def test_a_weld_drawn_in_empty_space_is_reported_as_holding_nothing():
    sec = two_channels(gap=0.0)
    ext_x = sec.centroid[0]
    stray = wsm.WeldLine(p1=(ext_x, 5000.0), p2=(ext_x + 100.0, 5000.0), label='X')
    c = ac.weld_contact(sec, stray)
    assert not c.found_both
    assert 'joins nothing' in c.describe()


def test_a_stray_weld_reaches_the_audit():
    sec = two_channels(gap=0.0)
    ext_x = sec.centroid[0]
    sec.welds = [wsm.WeldLine(p1=(ext_x, 5000.0), p2=(ext_x + 100.0, 5000.0), label='X')]
    assert 'nothing to join' in '\n'.join(ac.audit(sec, detail=sec.detail))


# ── the frames, which is where this goes wrong silently ──────────────────

def test_the_walk_uses_the_frame_section_pieces_renders_in():
    """Weld lines are stored in the PLACED frame and the polygons come
    back in the CENTROID frame. Skip the conversion and the walk samples a
    centroid-offset away -- 179.5 mm away on this section -- and reports
    empty space beside a perfectly good weld."""
    sec = two_channels(gap=0.0)
    cx, _ = sec.centroid
    assert cx > 100.0                              # the frames really do differ
    assert ac.weld_contact(sec, seam_weld(sec, 850.0, 950.0)).found_both


def test_each_part_is_placed_where_the_whole_render_puts_it():
    """`_pieces_of_part` must reproduce section_pieces' own translation. If
    it subtracted the inner centroid a second time, every part would move
    and the measured gap would describe a section nobody drew."""
    from apps.perforated_beam import section_shapes as shapes
    sec = two_channels(gap=0.0)
    whole = shapes.section_extents(shapes.section_pieces(sec))
    per_part = [ac._pieces_of_part(sec, i) for i in range(len(sec.parts))]
    merged = shapes.section_extents([p for group in per_part for p in group])
    assert merged == pytest.approx(whole, abs=1e-6)


# ── the explanation ──────────────────────────────────────────────────────

def test_a_symmetric_seam_is_explained_rather_than_left_reading_as_a_bug():
    sec = two_channels(gap=0.0)
    note = ac.symmetry_note(sec, seam_weld(sec, 850.0, 950.0), 0.0)
    assert 'not a mistake' in note
    assert 'Bredt' in note
    assert 'J.2.4' in note


def test_check_welds_measures_the_thickness_and_applies_the_minimum():
    """End to end: the seam that reported '0.00 mm leg on strength alone'
    and 'thicknesses not stated' must now specify 5 mm and say why."""
    sec = two_channels(gap=0.0)
    sec.welds = [seam_weld(sec, 850.0, 950.0)]
    r = wsm.check_welds(sec, 229322.0)[0]
    assert r.t_measured
    assert r.leg_to_specify == pytest.approx(5.0)
    assert 'Tabla J.2.4' in r.size_governed_by
    assert 'not a mistake' in r.size_warning


def test_stated_thicknesses_still_win_over_measured_ones():
    """The user knows things the geometry does not -- a joint to a part
    that is not modelled, for one. An explicit entry must not be
    overridden by a measurement."""
    sec = two_channels(gap=0.0)
    w = seam_weld(sec, 850.0, 950.0)
    w.t_thicker, w.t_thinner = 25.0, 25.0
    sec.welds = [w]
    r = wsm.check_welds(sec, 229322.0)[0]
    assert not r.t_measured
    assert r.leg_to_specify == pytest.approx(cirsoc.min_fillet_leg(25.0))


def test_inference_can_be_switched_off():
    sec = two_channels(gap=0.0)
    sec.welds = [seam_weld(sec, 850.0, 950.0)]
    r = wsm.check_welds(sec, 229322.0, infer_thickness=False)[0]
    assert r.leg_min_code == 0.0
    assert 'strength only' in r.size_warning


# ── finding the seam ─────────────────────────────────────────────────────

def test_the_seam_is_found_where_the_two_lips_meet():
    """The reference box is welded lip to lip, top and bottom. The contact
    faces are the outer faces of the two lips: 100 mm at the top and
    200 mm at the bottom, exactly the lip lengths the profile was drawn
    with."""
    runs = ac.contact_runs(two_channels(gap=0.0))
    assert len(runs) == 2
    lengths = sorted(round(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5)
                     for a, b in runs)
    assert lengths == [100, 200]


def test_a_gapped_pair_has_no_seam_at_all():
    """The diagnosis, stated as geometry: there is nothing to weld."""
    assert ac.contact_runs(two_channels(gap=1.94)) == []
    assert ac.seam_welds(two_channels(gap=1.94)) == []


def test_one_seam_is_reported_once():
    """Two profiles meeting along one face produce the same run once per
    edge pair that sees it. Without the merge the tab offers to weld the
    same seam three or four times."""
    runs = ac.contact_runs(two_channels(gap=0.0))
    assert len(runs) == len({(tuple(round(v, 3) for v in a),
                              tuple(round(v, 3) for v in b)) for a, b in runs})


def test_generated_welds_land_in_the_frame_check_welds_reads():
    """`contact_runs` works in the CENTROID frame; `WeldLine.p1/p2` are
    read in the PLACED frame. Get that backwards and every generated weld
    sits a centroid-offset from its seam -- 179.5 mm here -- and then
    reports a comfortable q = 0 rather than an error."""
    sec = two_channels(gap=0.0)
    cx, _cy = sec.centroid
    assert cx > 100.0                                  # the frames differ
    welds = ac.seam_welds(sec)
    assert len(welds) == 2
    for w in welds:
        c = ac.weld_contact(sec, w)
        assert c.found_both, 'a generated weld must sit on real material'
        assert c.t_thicker == pytest.approx(10.0, abs=0.4)


def test_generated_welds_size_to_the_code_minimum_end_to_end():
    sec = two_channels(gap=0.0)
    sec.welds = ac.seam_welds(sec)
    for r in wsm.check_welds(sec, 229322.0):
        assert r.leg_to_specify == pytest.approx(5.0)
        assert 'Tabla J.2.4' in r.size_governed_by


def test_a_corner_grazing_a_face_is_not_a_seam():
    """Contact needs three things at once -- parallel, touching, and
    overlapping along the shared direction. Distance alone would call a
    corner touch a weldable seam."""
    plate = pbm.CustomProfileSection('p', [(0., 0.), (100., 0.), (100., 10.), (0., 10.)])
    tee = pbm.CustomProfileSection('t', [(0., 0.), (10., 0.), (10., 100.), (0., 100.)])
    # the tee stands on one corner of the plate, overlapping by 1 mm
    sec = wsm.CompoundSection([
        wsm.PlacedProfile(plate, dx=0.0, dy=0.0, label='plate'),
        wsm.PlacedProfile(tee, dx=54.0, dy=55.0, label='tee')])
    for a, b in ac.contact_runs(sec):
        length = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        assert length >= ac.MIN_SEAM_MM
