"""
test_load_combinations.py -- factored load combinations.

The behaviour worth pinning here is mostly about what must NOT happen:
the user's own model must not be scaled in place, an unclassified load
must not take the smaller factor, and an unknown combination name must
not stop a beam from being analysed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import load_combinations as lc


def beam():
    b = pbm.BeamConfig(L=6000.0, section=pbm.SECTION_CATALOG['IPE 400'],
                       material=pbm.Material(Fy=250.0, E=200000.0))
    b.point_loads.append(pbm.PointLoad(3000.0, 10000.0, 0.0, lc.CASE_L))
    b.dist_loads.append(pbm.DistLoad(0.0, 6000.0, 4.0, 4.0, 0.0, lc.CASE_D))
    return b


# ── the factors ──────────────────────────────────────────────────────────

def test_lrfd_factors_each_case_separately():
    f = lc.apply(beam(), lc.LRFD_1)
    assert f.point_loads[0].P == pytest.approx(16000.0)      # 1.6 L
    assert f.dist_loads[0].w1 == pytest.approx(4.8)          # 1.2 D


def test_asd_leaves_the_loads_alone_and_moves_the_capacity_instead():
    """ASD is D + L on the load side. What changes is the comparison:
    Rn/Omega rather than phi*Rn, which is phi*Omega on the utilisation."""
    f = lc.apply(beam(), lc.ASD_1)
    assert f.point_loads[0].P == pytest.approx(10000.0)
    assert f.dist_loads[0].w1 == pytest.approx(4.0)
    assert lc.ASD_1.util_ratio == pytest.approx(0.90 * 1.67)
    assert lc.LRFD_1.util_ratio == 1.0


def test_the_dead_only_combination_drops_the_live_load():
    f = lc.apply(beam(), lc.LRFD_2)
    assert f.point_loads[0].P == pytest.approx(0.0)
    assert f.dist_loads[0].w1 == pytest.approx(1.4 * 4.0)


def test_as_entered_changes_nothing():
    f = lc.apply(beam(), lc.AS_ENTERED)
    assert f.point_loads[0].P == pytest.approx(10000.0)
    assert f.dist_loads[0].w1 == pytest.approx(4.0)
    assert lc.AS_ENTERED.is_factored is False


# ── the traps ────────────────────────────────────────────────────────────

def test_the_users_model_is_never_scaled_in_place():
    """The single most damaging possible bug in this module: factoring
    the caller's own beam would compound on every press of Analyze, and
    nothing on screen would say so. 1.2D+1.6L twice is 1.44D+2.56L."""
    b = beam()
    lc.apply(b, lc.LRFD_1)
    lc.apply(b, lc.LRFD_1)
    assert b.point_loads[0].P == pytest.approx(10000.0)
    assert b.dist_loads[0].w1 == pytest.approx(4.0)


def test_applying_twice_gives_the_same_answer_as_once():
    once = lc.apply(beam(), lc.LRFD_1)
    b = beam()
    lc.apply(b, lc.LRFD_1)
    twice = lc.apply(b, lc.LRFD_1)
    assert twice.point_loads[0].P == pytest.approx(once.point_loads[0].P)


def test_an_unclassified_load_takes_the_LARGER_factor():
    """1.6 beats 1.2, so a load nobody has classified is over-factored
    rather than under-factored. The opposite default would make silence
    unsafe."""
    b = pbm.BeamConfig(L=6000.0, section=pbm.SECTION_CATALOG['IPE 400'],
                       material=pbm.Material(Fy=250.0, E=200000.0))
    b.point_loads.append(pbm.PointLoad(3000.0, 10000.0))     # no case given
    assert b.point_loads[0].case == lc.CASE_L
    assert lc.apply(b, lc.LRFD_1).point_loads[0].P == pytest.approx(16000.0)


def test_an_unknown_combination_name_falls_back_rather_than_raising():
    """A stale key in a hand-edited workbook must not stop the model from
    opening."""
    assert lc.combination('nonsense-key') is lc.DEFAULT
    assert lc.combination(None) is lc.DEFAULT
    assert lc.combination('') is lc.DEFAULT


def test_a_combination_can_be_named_by_key_or_by_its_label():
    assert lc.combination('lrfd_12d16l') is lc.LRFD_1
    assert lc.combination(lc.LRFD_1.label) is lc.LRFD_1
    assert lc.combination(lc.LRFD_1) is lc.LRFD_1


def test_every_load_type_is_factored_not_just_the_forces():
    b = pbm.BeamConfig(L=6000.0, section=pbm.SECTION_CATALOG['IPE 400'],
                       material=pbm.Material(Fy=250.0, E=200000.0))
    b.point_moments.append(pbm.PointMoment(1000.0, 5.0e6, lc.CASE_L))
    b.point_torques.append(pbm.PointTorque(2000.0, 3.0e6, lc.CASE_L))
    b.dist_torques.append(pbm.DistTorque(0.0, 6000.0, 2.0, 2.0, lc.CASE_L))
    f = lc.apply(b, lc.LRFD_1)
    assert f.point_moments[0].M == pytest.approx(1.6 * 5.0e6)
    assert f.point_torques[0].T == pytest.approx(1.6 * 3.0e6)
    assert f.dist_torques[0].t1 == pytest.approx(1.6 * 2.0)


def test_the_section_is_shared_not_copied():
    """A drawn profile can be a large object, and nothing here touches
    it. Copying it per combination would be pure waste."""
    b = beam()
    assert lc.apply(b, lc.LRFD_1).section is b.section


# ── what the report says ─────────────────────────────────────────────────

def test_the_summary_names_the_factor_each_case_took():
    lines = '\n'.join(lc.summarise(beam(), lc.LRFD_1))
    assert '1.2D + 1.6L' in lines
    assert 'x1.2' in lines and 'x1.6' in lines


def test_the_summary_warns_when_nothing_was_classified_permanent():
    b = pbm.BeamConfig(L=6000.0, section=pbm.SECTION_CATALOG['IPE 400'],
                       material=pbm.Material(Fy=250.0, E=200000.0))
    b.point_loads.append(pbm.PointLoad(3000.0, 10000.0))
    assert 'no load is classified permanent' in '\n'.join(lc.summarise(b, lc.LRFD_1))


def test_the_asd_summary_states_the_omega_it_used():
    assert 'Omega' in '\n'.join(lc.summarise(beam(), lc.ASD_1))
