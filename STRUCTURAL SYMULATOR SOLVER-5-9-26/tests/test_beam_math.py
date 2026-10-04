"""Beam tab: the solver against closed-form solutions.

Written with the 2026-09-10 re-diagnosis (finding B-7): the Beam tab had no
physics test of any kind, which is why B-1 -- a fixed-fixed beam refusing to
solve at all -- survived two diagnoses with a green suite. Beam appeared only
in test_excel_roundtrip.py (round-trip) and test_tab_layouts.py (layout).

Every expected value here is a textbook closed form, written out in the test
name, so a failure says which piece of physics broke rather than "a number
moved". The tolerances are on the loose side of what the solver actually
achieves (it is typically 1e-5 or better on deflections and exact on statics)
so that a harmless meshing or quadrature change does not fail the suite -- only
a real change of answer does.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.beam.beam_app import BeamModel

# E = 200 GPa, I = 8000 cm^4 -> 16.0e6 N.m^2, the app's own default section.
EI = 200e9 * 8000e-8
L = 6.0
W = 10e3        # N/m, downward
P = 40e3        # N,  downward
M0 = 25e3       # N.m, +CCW

STATICS_TOL = 1e-9      # reactions and moments come out of exact statics
DEFLECTION_TOL = 3e-3   # deflections carry the M/EI integration error


def _model(build, length=L):
    m = BeamModel(length)
    m.EI = EI
    build(m)
    return m


def _solve(build, length=L):
    return _model(build, length).solve()


def _rel(got, want, scale=None):
    return abs(got - want) / max(abs(scale if scale is not None else want), 1e-12)


# ---------------------------------------------------------------- determinate

def test_simply_supported_udl_matches_wl2_over_8():
    r = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                          m.add_dload(0, L, W, W)))
    assert _rel(r.reaction_at(0)[0], W * L / 2) < STATICS_TOL
    assert _rel(r.reaction_at(L)[0], W * L / 2) < STATICS_TOL
    assert _rel(r.moment_at(L / 2), W * L * L / 8) < STATICS_TOL
    assert _rel(r.deflection(L / 2), -5 * W * L ** 4 / (384 * EI)) < DEFLECTION_TOL


def test_simply_supported_central_point_load_matches_pl_over_4():
    r = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                          m.add_point_load(L / 2, P)))
    assert _rel(r.reaction_at(0)[0], P / 2) < STATICS_TOL
    assert _rel(r.moment_at(L / 2, 'left'), P * L / 4) < STATICS_TOL
    assert _rel(r.deflection(L / 2), -P * L ** 3 / (48 * EI)) < DEFLECTION_TOL


def test_cantilever_tip_point_load_matches_pl3_over_3ei():
    r = _solve(lambda m: (m.add_support(0, 'fixed'), m.add_point_load(L, P)))
    assert _rel(r.reaction_at(0)[0], P) < STATICS_TOL
    assert _rel(r.moment_at(0.0, 'right'), -P * L) < STATICS_TOL
    assert _rel(r.deflection(L), -P * L ** 3 / (3 * EI)) < DEFLECTION_TOL
    assert _rel(r.rotation(L), -P * L ** 2 / (2 * EI)) < DEFLECTION_TOL


def test_cantilever_udl_matches_wl4_over_8ei():
    r = _solve(lambda m: (m.add_support(0, 'fixed'), m.add_dload(0, L, W, W)))
    assert _rel(r.moment_at(0.0, 'right'), -W * L * L / 2) < STATICS_TOL
    assert _rel(r.deflection(L), -W * L ** 4 / (8 * EI)) < DEFLECTION_TOL


def test_simply_supported_triangular_load():
    """Load ramping 0 -> W. Note the max deflection coefficient is 0.00652*w*L^4
    (equivalently 0.01304*W_total*L^3); the two forms differ by a factor of two
    and picking the wrong one is an easy way to "find" a bug that is not there.
    """
    r = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                          m.add_dload(0, L, 0.0, W)))
    w_total = W * L / 2
    assert _rel(r.reaction_at(0)[0], w_total / 3) < STATICS_TOL
    assert _rel(r.reaction_at(L)[0], 2 * w_total / 3) < STATICS_TOL
    assert _rel(r.moment_at(L / math.sqrt(3)), W * L * L / (9 * math.sqrt(3))) < STATICS_TOL
    assert _rel(r.deflection(0.5193 * L), -0.00652 * W * L ** 4 / EI) < DEFLECTION_TOL


def test_end_moment_reactions_are_a_couple():
    """A +CCW moment M0 at the left end of a simply-supported span gives
    R_left = +M0/L and M(0+) = -M0. The sign reads backwards against a naive
    expectation and is correct; see DIAGNOSIS_BEAM_2026-09-05.md section 0."""
    r = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                          m.add_moment(0.0, M0)))
    assert _rel(r.reaction_at(0)[0], M0 / L) < STATICS_TOL
    assert _rel(r.reaction_at(L)[0], -M0 / L) < STATICS_TOL
    assert _rel(r.moment_at(1e-5, 'right'), -M0) < 1e-4
    assert abs(r.moment_at(L, 'left')) < STATICS_TOL * M0


def test_overhang_reactions_and_hogging_moment():
    r = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(4.0, 'roller'),
                          m.add_dload(0, 6.0, W, W)), length=6.0)
    assert _rel(r.reaction_at(4.0)[0], 45e3) < STATICS_TOL
    assert _rel(r.reaction_at(0.0)[0], 15e3) < STATICS_TOL
    assert _rel(r.moment_at(4.0, 'left'), -W * 2 * 2 / 2) < STATICS_TOL


# -------------------------------------------------------------- indeterminate

def test_fixed_fixed_udl_solves_and_matches_wl2_over_12():
    """Regression for B-1 (2026-09-05 / 2026-09-10).

    A fixed-fixed beam whose only nodes are its two supports has four DOF, all
    of them restrained, and solve() used to reject the most common
    indeterminate case in any textbook with "Beam is fully constrained;
    nothing to solve". The physics was always right -- only the mesh was too
    coarse -- so this asserts both that it solves AND that it solves correctly.
    """
    m = _model(lambda mm: (mm.add_support(0, 'fixed'), mm.add_support(L, 'fixed'),
                           mm.add_dload(0, L, W, W)))
    assert len(m._node_positions()) >= 3, 'the mesh must not collapse to its supports'
    r = m.solve()
    assert _rel(r.moment_at(0.0, 'right'), -W * L * L / 12) < STATICS_TOL
    assert _rel(r.moment_at(L / 2), W * L * L / 24) < STATICS_TOL
    assert _rel(r.reaction_at(0)[0], W * L / 2) < STATICS_TOL
    assert _rel(r.deflection(L / 2), -W * L ** 4 / (384 * EI)) < DEFLECTION_TOL


def test_fixed_fixed_central_point_load_matches_pl_over_8():
    r = _solve(lambda m: (m.add_support(0, 'fixed'), m.add_support(L, 'fixed'),
                          m.add_point_load(L / 2, P)))
    assert _rel(r.moment_at(0.0, 'right'), -P * L / 8) < STATICS_TOL
    assert _rel(r.moment_at(L / 2), P * L / 8) < STATICS_TOL
    assert _rel(r.deflection(L / 2), -P * L ** 3 / (192 * EI)) < DEFLECTION_TOL


def test_fixed_fixed_with_no_load_is_solvable_and_flat():
    r = _solve(lambda m: (m.add_support(0, 'fixed'), m.add_support(L, 'fixed')))
    assert abs(r.deflection(L / 2)) < 1e-12


def test_propped_cantilever_matches_3wl_over_8():
    r = _solve(lambda m: (m.add_support(0, 'fixed'), m.add_support(L, 'roller'),
                          m.add_dload(0, L, W, W)))
    assert _rel(r.reaction_at(L)[0], 3 * W * L / 8) < STATICS_TOL
    assert _rel(r.reaction_at(0)[0], 5 * W * L / 8) < STATICS_TOL
    assert _rel(r.moment_at(0.0, 'right'), -W * L * L / 8) < STATICS_TOL


def test_two_equal_spans_continuous_matches_1_25_wl():
    r = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                          m.add_support(2 * L, 'roller'),
                          m.add_dload(0, 2 * L, W, W)), length=2 * L)
    assert _rel(r.reaction_at(L)[0], 1.25 * W * L) < STATICS_TOL
    assert _rel(r.reaction_at(0)[0], 0.375 * W * L) < STATICS_TOL
    assert _rel(r.moment_at(L, 'left'), -W * L * L / 8) < STATICS_TOL


def test_guided_support_carries_moment_but_no_shear():
    r = _solve(lambda m: (m.add_support(0, 'fixed'), m.add_support(L, 'guided'),
                          m.add_dload(0, L, W, W)))
    assert _rel(r.reaction_at(0)[0], W * L) < STATICS_TOL
    assert _rel(r.moment_at(0.0, 'right'), -W * L * L / 3) < STATICS_TOL
    assert _rel(r.moment_at(L, 'left'), W * L * L / 6) < STATICS_TOL


# ------------------------------------------------------------- non-uniform q

def test_nonuniform_constant_expression_equals_the_equivalent_udl():
    from common import make_shape_fn
    a = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                          m.add_dload(0, L, W, W)))
    b = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                          m.add_nonuniform_load(make_shape_fn('10000', {'L': L}), 0, L)))
    assert _rel(b.reaction_at(0)[0], a.reaction_at(0)[0]) < 1e-9
    assert _rel(b.moment_at(L / 2), a.moment_at(L / 2)) < 1e-9
    assert _rel(b.deflection(L / 2), a.deflection(L / 2)) < 1e-9


def test_nonuniform_sinusoid_matches_its_closed_form():
    from common import make_shape_fn
    r = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                          m.add_nonuniform_load(
                              make_shape_fn('10000*sin(pi*x/L)', {'L': L}), 0, L)))
    assert _rel(r.reaction_at(0)[0], W * L / math.pi) < 1e-6
    assert _rel(r.moment_at(L / 2), W * L * L / math.pi ** 2) < 1e-6
    assert _rel(r.deflection(L / 2), -W * L ** 4 / (math.pi ** 4 * EI)) < DEFLECTION_TOL


# -------------------------------------------------------------- global checks

def test_global_equilibrium_on_an_asymmetric_mixed_model():
    r = _solve(lambda m: (m.add_support(1.0, 'pin'), m.add_support(8.0, 'roller'),
                          m.add_point_load(3.0, 20e3),
                          m.add_dload(4.0, 9.0, 5e3, 12e3),
                          m.add_moment(6.0, 15e3)), length=10.0)
    applied = 20e3 + (5e3 + 12e3) / 2 * 5.0
    total_reaction = r.reaction_at(1.0)[0] + r.reaction_at(8.0)[0]
    assert _rel(total_reaction, applied) < 1e-9
    # nothing is carried beyond the last support of a free-ended overhang
    assert abs(r.shear_at(9.999, 'right')) < 1e-6 * applied
    assert abs(r.moment_at(10.0, 'left')) < 1e-6 * applied * 2


def test_a_genuine_mechanism_is_still_rejected():
    """The B-1 fix must not turn the real error into silence: a beam with one
    roller and a load on it is a mechanism and must still raise."""
    with pytest.raises(ValueError):
        _solve(lambda m: (m.add_support(2.0, 'roller'), m.add_point_load(3.0, 1e3)))


# ------------------------------------------------------------ input handling

@pytest.mark.parametrize('w1,w2', [(W, W), (0.0, 60e3), (60e3, 0.0)])
def test_a_distributed_load_entered_right_to_left_gives_the_same_answer(w1, w2):
    """Regression for B-4.

    q() tests `x1 <= x <= x2`, which is unsatisfiable when x1 > x2, so a
    reversed segment used to contribute nothing at all -- zero reactions, zero
    moment, no warning. The intensities must travel with their own ends, or a
    ramp comes back flipped, which is why the asymmetric cases are here.
    """
    fwd = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                            m.add_dload(1.0, 5.0, w1, w2)))
    rev = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                            m.add_dload(5.0, 1.0, w2, w1)))
    assert _rel(rev.reaction_at(0)[0], fwd.reaction_at(0)[0]) < 1e-9
    assert _rel(rev.reaction_at(L)[0], fwd.reaction_at(L)[0]) < 1e-9
    assert _rel(rev.moment_at(L / 2), fwd.moment_at(L / 2)) < 1e-9


@pytest.mark.parametrize('build', [
    lambda m: m.add_support(99.0, 'roller'),
    lambda m: m.add_point_load(99.0, 10e3),
    lambda m: m.add_moment(-3.0, 1e3),
    lambda m: m.add_dload(0.0, 99.0, W, W),
    lambda m: m.add_nonuniform_load(lambda x: 1.0, -1.0, 3.0),
])
def test_a_station_off_the_beam_is_refused(build):
    """Regression for B-5.

    Nothing checked these against the beam's own length, so a support or load
    at x = 99 on a 6 m beam silently extended the mesh to 99 m while model.L
    stayed 6.0 -- a 10 kN load came back as a 155 kN reaction.
    """
    m = BeamModel(L)
    m.EI = EI
    with pytest.raises(ValueError):
        build(m)


def test_the_beam_ends_themselves_are_valid_stations():
    """The B-5 guard must not reject x = 0 or x = L, which is where supports
    normally live."""
    r = _solve(lambda m: (m.add_support(0.0, 'pin'), m.add_support(L, 'roller'),
                          m.add_point_load(L, 0.0), m.add_dload(0.0, L, W, W)))
    assert _rel(r.reaction_at(0)[0], W * L / 2) < STATICS_TOL


# ---------------------------------------- two supports at one station (R-1)
#
# BeamResult.reaction_at() looks a reaction up by STATION, so two supports
# sharing a node both reported that one node's residual -- and _V_M_at added
# it once per support. A pin and a roller both at x = 0 on a 6 m beam under
# 10 kN/m reported 90 kN of reaction for 60 kN of load, max |M| = 180 against
# a true 45, and failed the stress check on a beam that passes. Constraint
# assembly was always right (`constrained[dof] = 0.0` twice is idempotent),
# so the displacements were right and only the recovery was wrong -- which is
# why no closed form in this file caught it.
#
# A second support at an occupied station is merged into the first: the DOF it
# restrains are added to that station's, which is what the user meant by
# putting it there.

def _udl_reference():
    """Simply-supported span under a full UDL, one support per station."""
    return _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                             m.add_dload(0, L, W, W)))


@pytest.mark.parametrize('dup', ['pin', 'roller'])
def test_a_second_vertical_support_at_one_station_does_not_double_count(dup):
    r = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(0, dup),
                          m.add_support(L, 'roller'), m.add_dload(0, L, W, W)))
    ref = _udl_reference()
    assert _rel(r.reaction_at(0)[0], W * L / 2) < STATICS_TOL
    # V just right of the support is probed at x + 1e-7, so it carries that
    # much of the UDL whatever the supports are -- hence the comparison
    # against the one-support reference, which carries the same artifact, and
    # a looser absolute tolerance beside it.
    assert _rel(r.shear_at(0.0, 'right'), ref.shear_at(0.0, 'right')) < STATICS_TOL
    assert _rel(r.shear_at(0.0, 'right'), W * L / 2) < 1e-6
    assert _rel(r.moment_at(L / 2), W * L * L / 8) < STATICS_TOL
    assert _rel(r.moment_at(L / 2), ref.moment_at(L / 2)) < STATICS_TOL
    assert abs(r.moment_at(L, 'right')) < STATICS_TOL * W * L * L


def test_duplicate_supports_are_merged_into_one_entry():
    """The reactions report and the Excel sheet both iterate model.supports, so
    a duplicate must not survive as a second row claiming its own reaction."""
    m = _model(lambda mm: (mm.add_support(0, 'pin'), mm.add_support(0, 'roller'),
                           mm.add_support(L, 'roller'), mm.add_dload(0, L, W, W)))
    assert [s['x'] for s in m.supports] == [0.0, L]


@pytest.mark.parametrize('first,second', [('pin', 'guided'), ('guided', 'pin'),
                                          ('roller', 'guided')])
def test_a_vertical_and_a_rotational_support_at_one_station_act_as_fixed(first, second):
    """The worst form of the bug, because it looks like a legitimate model: a
    pin plus a guided support at one station is how a user builds a fixed end
    without reaching for the 'fixed' type. It must give the propped cantilever,
    which it did not -- M(0) came out -90 against a true -45, and the moment
    diagram did not close at the free end."""
    r = _solve(lambda m: (m.add_support(0, first), m.add_support(0, second),
                          m.add_support(L, 'roller'), m.add_dload(0, L, W, W)))
    assert _rel(r.reaction_at(0)[0], 5 * W * L / 8) < STATICS_TOL
    assert _rel(r.reaction_at(L)[0], 3 * W * L / 8) < STATICS_TOL
    assert _rel(r.moment_at(0.0, 'right'), -W * L * L / 8) < STATICS_TOL
    assert abs(r.moment_at(L, 'right')) < STATICS_TOL * W * L * L


def test_merging_a_duplicate_support_names_the_type_it_became():
    m = _model(lambda mm: (mm.add_support(0, 'pin'), mm.add_support(0, 'guided')))
    assert m.supports[0]['type'] == 'fixed'
    assert len(m.supports) == 1


def test_two_identical_supports_at_one_station_change_nothing():
    for kind in ('pin', 'roller', 'fixed', 'guided'):
        m = _model(lambda mm, k=kind: (mm.add_support(0, k), mm.add_support(0, k)))
        assert [s['type'] for s in m.supports] == [kind], kind


def test_a_merge_is_recorded_so_the_tab_can_say_it_happened():
    """Silently changing the model the user described is what this bug was.
    Merging is the right answer, but it has to be reported."""
    m = _model(lambda mm: (mm.add_support(0, 'pin'), mm.add_support(0, 'guided'),
                           mm.add_support(L, 'roller')))
    assert len(m.support_merges) == 1
    note = m.support_merges[0]
    assert note['x'] == 0.0
    assert note['added'] == 'guided'
    assert note['result'] == 'fixed'


def test_merging_keeps_the_mesh_and_the_dof_count_right():
    plain = _model(lambda mm: (mm.add_support(0, 'fixed'), mm.add_support(L, 'roller'),
                               mm.add_dload(0, L, W, W)))
    merged = _model(lambda mm: (mm.add_support(0, 'pin'), mm.add_support(0, 'guided'),
                                mm.add_support(L, 'roller'), mm.add_dload(0, L, W, W)))
    assert merged._node_positions() == plain._node_positions()
    assert (merged.solve().equilibrium()['indeterminacy']
            == plain.solve().equilibrium()['indeterminacy'])


def test_an_unknown_support_type_is_refused_when_it_is_added():
    m = BeamModel(L)
    m.EI = EI
    with pytest.raises(ValueError, match='Unknown support type'):
        m.add_support(0.0, 'spring')


# ------------------------------------------- equilibrium and closure (R-2)
#
# Nothing in the tab checked that its own answer balanced, which is why R-1
# could report 90 kN of reaction for 60 kN of load with a green suite. These
# residuals are the net: one leg (the applied total) is integrated
# independently of the solver, the other comes back through the same recovery
# path the diagrams and the reactions report use.

EQ_BUILDS = {
    'ss_udl': (lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                          m.add_dload(0, L, W, W)), L),
    'cantilever_point': (lambda m: (m.add_support(0, 'fixed'),
                                    m.add_point_load(L, P)), L),
    'cantilever_right_end': (lambda m: (m.add_support(L, 'fixed'),
                                        m.add_point_load(0.0, P)), L),
    'fixed_fixed': (lambda m: (m.add_support(0, 'fixed'), m.add_support(L, 'fixed'),
                               m.add_dload(0, L, W, W)), L),
    'propped': (lambda m: (m.add_support(0, 'fixed'), m.add_support(L, 'roller'),
                           m.add_dload(0, L, W, W)), L),
    'two_span': (lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                            m.add_support(2 * L, 'roller'),
                            m.add_dload(0, 2 * L, W, W)), 2 * L),
    'guided_end': (lambda m: (m.add_support(0, 'fixed'), m.add_support(L, 'guided'),
                              m.add_dload(0, L, W, W)), L),
    'interior_fixed': (lambda m: (m.add_support(L / 2, 'fixed'),
                                  m.add_point_load(0.0, P),
                                  m.add_point_load(L, P / 2)), L),
    'overhangs_ramp_and_moment': (
        lambda m: (m.add_support(1.0, 'pin'), m.add_support(8.0, 'roller'),
                   m.add_point_load(3.0, 20e3), m.add_dload(4.0, 9.0, 5e3, 12e3),
                   m.add_moment(6.0, 15e3)), 10.0),
    'merged_duplicate': (lambda m: (m.add_support(0, 'pin'), m.add_support(0, 'guided'),
                                    m.add_support(L, 'roller'),
                                    m.add_dload(0, L, W, W)), L),
}


@pytest.mark.parametrize('name', sorted(EQ_BUILDS))
def test_every_valid_model_balances(name):
    build, length = EQ_BUILDS[name]
    eq = _solve(build, length=length).equilibrium()
    assert eq['ok'], eq
    assert abs(eq['residual_Fy']) <= 1e-9 * eq['scale_F'], eq
    assert abs(eq['residual_M0']) <= 1e-9 * eq['scale_M'], eq
    assert abs(eq['shear_beyond_end']) <= 1e-9 * eq['scale_F'], eq
    assert abs(eq['moment_beyond_end']) <= 1e-9 * eq['scale_M'], eq


def test_the_total_applied_load_is_integrated_not_assumed():
    """Point loads, a trapezoid and a q(x) expression in one model, against the
    hand-computed total. This is the leg of the check that does not come from
    the solver, so it has to be right on its own."""
    from common import make_shape_fn
    r = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                          m.add_point_load(2.0, P),
                          m.add_dload(0.0, 3.0, 4e3, 10e3),
                          m.add_nonuniform_load(
                              make_shape_fn('10000*sin(pi*x/L)', {'L': L}), 0, L)))
    want = P + (4e3 + 10e3) / 2 * 3.0 + 2 * W * L / math.pi
    assert _rel(r.equilibrium()['applied_down'], want) < 1e-6


def test_the_reactions_sum_to_the_applied_load():
    eq = _udl_reference().equilibrium()
    assert _rel(eq['reactions_up'], eq['applied_down']) < 1e-9
    assert _rel(eq['applied_down'], W * L) < 1e-9


def test_an_uplift_load_balances_too():
    """A negative P is upward; the residual must stay a residual and not a
    sum of absolute values that cancels by luck."""
    eq = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                           m.add_point_load(2.0, -P),
                           m.add_point_load(4.0, P))).equilibrium()
    assert eq['ok']
    assert abs(eq['applied_down']) < 1e-9 * P
    assert eq['scale_F'] >= P, 'the scale must not collapse when loads cancel'


def test_a_model_with_no_load_at_all_balances():
    eq = _solve(lambda m: (m.add_support(0, 'pin'),
                           m.add_support(L, 'roller'))).equilibrium()
    assert eq['ok']
    assert eq['scale_F'] > 0 and eq['scale_M'] > 0, 'no division by a zero scale'


def test_a_corrupted_reaction_is_caught():
    """The point of the check. If any future change makes the recovery disagree
    with the loads -- double counting a reaction, dropping a load segment,
    reading the wrong DOF -- this is what says so. R-1 went unnoticed for two
    diagnoses because nothing asked this question."""
    r = _udl_reference()
    eq = r.equilibrium()
    assert eq['ok']
    i = r.idx_of[round(0.0, 9)]
    r.R[2 * i] *= 2.0                      # as if one reaction were counted twice
    bad = r.equilibrium()
    assert not bad['ok']
    assert abs(bad['residual_Fy']) > 1e-6 * bad['scale_F']


@pytest.mark.parametrize('name,degree', [
    ('ss_udl', 0),
    ('cantilever_point', 0),
    ('interior_fixed', 0),
    ('propped', 1),
    ('two_span', 1),
    ('fixed_fixed', 2),
])
def test_the_degree_of_indeterminacy_is_reported(name, degree):
    """A planar bending model has two equilibrium equations, so the degree is
    (restrained DOF) - 2. It tells the user whether the answer they are reading
    depended on EI at all."""
    build, length = EQ_BUILDS[name]
    assert _solve(build, length=length).equilibrium()['indeterminacy'] == degree


def test_merging_a_duplicate_support_does_not_inflate_the_degree():
    """pin + guided at one station is a fixed support: two restrained DOF, not
    three."""
    eq = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(0, 'guided'),
                           m.add_support(L, 'roller'),
                           m.add_dload(0, L, W, W))).equilibrium()
    assert eq['constrained_dof'] == 3
    assert eq['indeterminacy'] == 1


# ------------------------------------------- the model's own numbers (R-5)
#
# A beam with no length and a beam with no stiffness both used to fail as
# something else: L = 0 came back as "Beam is fully constrained; nothing to
# solve" (it is neither), and E = 0 as "Singular stiffness matrix -- beam is a
# mechanism" (it is not). A NEGATIVE EI solved happily and returned
# deflections with the sign flipped, with nothing said at all.

@pytest.mark.parametrize('length', [0.0, -3.0, float('nan')])
def test_a_beam_with_no_length_says_so(length):
    with pytest.raises(ValueError, match='length'):
        BeamModel(length)


def test_a_length_zeroed_after_construction_is_still_caught():
    """The guard is on the way in AND at solve time: the tab rebuilds its
    model every Analyze, but a script can assign to m.L."""
    m = BeamModel(L)
    m.EI = EI
    m.add_support(0, 'pin')
    m.add_support(L, 'roller')
    m.L = 0.0
    with pytest.raises(ValueError, match='length'):
        m.solve()


@pytest.mark.parametrize('bad', [0.0, -1.0, -16e6, float('inf'), float('nan')])
def test_a_beam_with_no_usable_stiffness_says_so(bad):
    """A negative EI is the dangerous one: it solved, and every deflection came
    back with the wrong sign."""
    m = BeamModel(L)
    m.EI = bad
    m.add_support(0, 'pin')
    m.add_support(L, 'roller')
    m.add_dload(0, L, W, W)
    with pytest.raises(ValueError, match='EI'):
        m.solve()


def test_the_missing_ei_message_still_distinguishes_unset_from_invalid():
    m = BeamModel(L)
    m.add_support(0, 'pin')
    with pytest.raises(ValueError, match='must be set'):
        m.solve()


def test_a_valid_tiny_beam_is_not_caught_by_the_new_guards():
    """The guards must reject nothing that works. A 50 mm span with a light
    section is a legitimate model."""
    m = BeamModel(0.05)
    m.EI = 1.0
    m.add_support(0.0, 'pin')
    m.add_support(0.05, 'roller')
    m.add_dload(0.0, 0.05, 1.0, 1.0)
    assert m.solve().equilibrium()['ok']


# ------------------------------------- what a reaction moment IS (R-3)
#
# reaction_at() returns the raw rotational-DOF residual, and the tab negated
# it AT x = 0 ONLY, a rule arrived at by trying a left-end, a right-end and a
# fixed-fixed beam and keeping what matched the M(x) diagram. It does not
# generalise: at an interior fixed support the printed number was the internal
# moment on the support's LEFT side, not the couple the support applies, and a
# station with different internal moments either side has no single "the
# moment" to print at all.
#
# The residual is in fact the support's couple, counter-clockwise positive --
# the same convention as an applied moment -- which is provable rather than
# asserted: crossing a support, the sagging-positive internal moment jumps by
# exactly minus that couple. That identity is the test, and it holds at every
# station without a positional special case.

REACTION_MODELS = {
    'ss_udl': (lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                          m.add_dload(0, L, W, W)), L),
    'cantilever_left': (lambda m: (m.add_support(0, 'fixed'),
                                   m.add_point_load(L, P)), L),
    'cantilever_right': (lambda m: (m.add_support(L, 'fixed'),
                                    m.add_point_load(0.0, P)), L),
    'fixed_fixed': (lambda m: (m.add_support(0, 'fixed'), m.add_support(L, 'fixed'),
                               m.add_dload(0, L, W, W)), L),
    'propped': (lambda m: (m.add_support(0, 'fixed'), m.add_support(L, 'roller'),
                           m.add_dload(0, L, W, W)), L),
    'interior_fixed': (lambda m: (m.add_support(L / 2, 'fixed'),
                                  m.add_point_load(0.0, P)), L),
    'guided_end': (lambda m: (m.add_support(0, 'fixed'), m.add_support(L, 'guided'),
                              m.add_dload(0, L, W, W)), L),
    'two_span': (lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                            m.add_support(2 * L, 'roller'),
                            m.add_dload(0, 2 * L, W, W)), 2 * L),
}


@pytest.mark.parametrize('name', sorted(REACTION_MODELS))
def test_a_reaction_moment_is_the_jump_in_the_internal_moment(name):
    """The identity that replaces the sign heuristic, at every station."""
    build, length = REACTION_MODELS[name]
    r = _solve(build, length=length)
    for sx in r.support_stations:
        react = r.support_reaction(sx)
        jump = react['M_left'] - react['M_right']
        scale = max(abs(react['M']), abs(jump), 1e3)
        assert abs(react['M'] - jump) < 1e-6 * scale, (name, sx, react)


def test_the_internal_moment_left_of_the_left_end_is_zero():
    """Nothing is carried outside the beam. A query at x = 0 with side='left'
    used to come back with the value just AFTER the support at that node, which
    is precisely what made the reaction moment there look like it needed
    negating."""
    r = _solve(lambda m: (m.add_support(0, 'fixed'), m.add_point_load(L, P)))
    assert abs(r.moment_at(0.0, 'left')) < 1e-9 * P * L
    assert abs(r.shear_at(0.0, 'left')) < 1e-9 * P
    assert abs(r.moment_at(L, 'right')) < 1e-9 * P * L


def test_a_fixed_end_reports_the_hogging_moment_on_the_beam_side():
    """What a designer reads off a cantilever: the root moment is -PL, and it
    is on the beam side of the support whichever end the support is at."""
    left = _solve(lambda m: (m.add_support(0, 'fixed'), m.add_point_load(L, P)))
    right = _solve(lambda m: (m.add_support(L, 'fixed'), m.add_point_load(0.0, P)))
    assert _rel(left.support_reaction(0.0)['M_right'], -P * L) < STATICS_TOL
    assert _rel(right.support_reaction(L)['M_left'], -P * L) < STATICS_TOL
    # ... and the couples the two supports apply are mirror images
    assert _rel(left.support_reaction(0.0)['M'],
                -right.support_reaction(L)['M']) < STATICS_TOL


def test_fixed_fixed_couples_are_equal_and_opposite():
    """A symmetric beam's two end COUPLES are anti-symmetric while its two end
    internal moments are equal -- the distinction the old single column could
    not express."""
    r = _solve(lambda m: (m.add_support(0, 'fixed'), m.add_support(L, 'fixed'),
                          m.add_dload(0, L, W, W)))
    a, b = r.support_reaction(0.0), r.support_reaction(L)
    assert _rel(a['M'], W * L * L / 12) < STATICS_TOL
    assert _rel(b['M'], -W * L * L / 12) < STATICS_TOL
    assert _rel(a['M_right'], -W * L * L / 12) < STATICS_TOL
    assert _rel(b['M_left'], -W * L * L / 12) < STATICS_TOL


def test_an_interior_fixed_support_reports_both_sides():
    """The case the old single column could not express: a fixed support at
    midspan with load on one cantilever only.

    The cantilever reaches LEFT from the support, so taking moments about the
    support for that segment, the tip load P (downward, at a distance L/2 to
    the left) contributes +P*L/2 counter-clockwise and the support's couple
    must be -P*L/2 to balance it. The internal moment is -P*L/2 on the loaded
    side and zero on the other, so there is no single 'the' moment here --
    which is the point."""
    r = _solve(lambda m: (m.add_support(L / 2, 'fixed'), m.add_point_load(0.0, P)))
    react = r.support_reaction(L / 2)
    assert _rel(react['Fy'], P) < STATICS_TOL
    assert _rel(react['M'], -P * L / 2) < STATICS_TOL
    assert _rel(react['M_left'], -P * L / 2) < STATICS_TOL
    assert abs(react['M_right']) < STATICS_TOL * P * L


def test_a_pin_applies_no_couple():
    r = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                          m.add_dload(0, L, W, W)))
    for sx in (0.0, L):
        react = r.support_reaction(sx)
        assert abs(react['M']) < 1e-9 * W * L * L
        assert abs(react['M_left'] - react['M_right']) < 1e-9 * W * L * L


def test_a_guided_support_applies_a_couple_but_no_force():
    r = _solve(lambda m: (m.add_support(0, 'fixed'), m.add_support(L, 'guided'),
                          m.add_dload(0, L, W, W)))
    react = r.support_reaction(L)
    assert abs(react['Fy']) < 1e-9 * W * L
    assert abs(react['M']) > 0.1 * W * L * L / 6


def test_the_couples_close_the_global_moment_balance():
    """The independent confirmation that the convention is right: equilibrium()
    sums these couples as counter-clockwise couples about x = 0, and it
    balances to machine precision on every model here."""
    for name, (build, length) in REACTION_MODELS.items():
        eq = _solve(build, length=length).equilibrium()
        assert eq['ok'], name


def test_support_reaction_and_reaction_at_agree_on_the_force():
    r = _solve(lambda m: (m.add_support(0, 'pin'), m.add_support(L, 'roller'),
                          m.add_dload(0, L, W, W)))
    for sx in (0.0, L):
        assert r.support_reaction(sx)['Fy'] == r.reaction_at(sx)[0]
