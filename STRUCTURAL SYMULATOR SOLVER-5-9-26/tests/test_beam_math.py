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
