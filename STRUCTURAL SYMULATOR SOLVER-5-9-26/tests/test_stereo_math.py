"""Closed-form checks for the Stereo tab's 3D solver (apps/stereo/stereo_math.py).

Every element type is validated against a textbook closed-form result
before anything more elaborate is trusted:
  * a pin (axial) bar          -> delta = PL/EA
  * a rigid (frame) cantilever -> tip deflection = PL^3/(3EI) in EACH of the
                                   two bending planes independently, and
                                   twist = TL/GJ in torsion
-- because a sign or axis mistake in the 3D transformation would otherwise
be invisible on any one single-axis case (it would still "run"; it would
just quietly answer a rotated problem).

Boundary-condition freedom is checked directly: a support built from NO
preset at all, with hand-picked individual DOFs, must solve identically to
one built from an equivalent preset -- proving the per-DOF override path
is not just decorative.
"""
import math

import numpy as np
import pytest

from apps.stereo import stereo_math as sm
from apps.stereo import stereo_geometry as sg


E_GPA = 200.0
FY = 250.0


def test_pin_bar_axial_extension_matches_PL_over_EA():
    # A single pin bar has zero stiffness transverse to its own axis, so its
    # free end also needs its OTHER two translations restrained directly
    # (not by the bar) or the model is a mechanism regardless of dimension --
    # this is physically correct, not a solver bug, and is exactly what
    # `test_pure_mechanism_is_caught_as_singular_not_a_wrong_answer` and the
    # 'no floating axis' checks below exist to confirm.
    L = 4.0
    A_cm2 = 10.0
    nodes = [(0.0, 0.0, 0.0), (L, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1, 'conn': 'pin', 'E': E_GPA, 'A': A_cm2, 'Fy': FY}]
    loads = [{'node': 1, 'fx': 100.0}]   # 100 kN tension
    supports = [{'node': 0, 'type': 'fixed'},
                {'node': 1, 'dofs': {'uy': True, 'uz': True}}]

    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None

    EA = E_GPA * 1e9 * A_cm2 * 1e-4
    expected_delta_m = (100e3 * L) / EA
    got_delta_m = res['node_res'][1]['ux'] / 1000.0
    assert got_delta_m == pytest.approx(expected_delta_m, rel=1e-9)
    assert res['member_res'][0]['N'] == pytest.approx(100.0, rel=1e-9)

    rxn = res['reactions'][0]
    assert rxn['Fx'] == pytest.approx(-100.0, rel=1e-9)


def test_rigid_cantilever_deflects_PL3_3EI_in_the_y_plane():
    L = 3.0
    A_cm2 = 20.0
    I_cm4 = 500.0
    nodes = [(0.0, 0.0, 0.0), (L, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1, 'conn': 'rigid', 'E': E_GPA, 'A': A_cm2,
                'I': I_cm4, 'J': I_cm4, 'Fy': FY}]
    P = 5.0   # kN
    loads = [{'node': 1, 'fy': -P}]
    supports = [{'node': 0, 'type': 'fixed'}]

    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None

    EI = E_GPA * 1e9 * I_cm4 * 1e-8
    expected = -(P * 1e3 * L ** 3) / (3 * EI)
    got = res['node_res'][1]['uy'] / 1000.0
    assert got == pytest.approx(expected, rel=1e-6)
    # negligible out-of-plane / axial movement
    assert res['node_res'][1]['ux'] == pytest.approx(0.0, abs=1e-9)
    assert res['node_res'][1]['uz'] == pytest.approx(0.0, abs=1e-9)


def test_rigid_cantilever_deflects_PL3_3EI_in_the_z_plane():
    """Same cantilever, load applied in Z instead of Y -- this exercises
    the OTHER bending plane (Iy instead of Iz) and would catch a sign flip
    between the two that a Y-only test cannot."""
    L = 3.0
    A_cm2 = 20.0
    I_cm4 = 500.0
    nodes = [(0.0, 0.0, 0.0), (L, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1, 'conn': 'rigid', 'E': E_GPA, 'A': A_cm2,
                'I': I_cm4, 'J': I_cm4, 'Fy': FY}]
    P = 5.0
    loads = [{'node': 1, 'fz': -P}]
    supports = [{'node': 0, 'type': 'fixed'}]

    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None

    EI = E_GPA * 1e9 * I_cm4 * 1e-8
    expected = -(P * 1e3 * L ** 3) / (3 * EI)
    got = res['node_res'][1]['uz'] / 1000.0
    assert got == pytest.approx(expected, rel=1e-6)


def test_rigid_cantilever_twists_TL_over_GJ():
    L = 3.0
    A_cm2 = 20.0
    I_cm4 = 500.0
    J_cm4 = 800.0
    nodes = [(0.0, 0.0, 0.0), (L, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1, 'conn': 'rigid', 'E': E_GPA, 'A': A_cm2,
                'I': I_cm4, 'J': J_cm4, 'Fy': FY}]
    T = 2.0   # kN*m torque about the member's own (local == global X) axis
    loads = [{'node': 1, 'mx': T}]
    supports = [{'node': 0, 'type': 'fixed'}]

    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None

    G = (E_GPA * 1e9) / (2 * (1 + sm.DEFAULT_NU))
    J = J_cm4 * 1e-8
    expected_twist = (T * 1e3 * L) / (G * J)
    assert res['node_res'][1]['rx'] == pytest.approx(expected_twist, rel=1e-6)


def test_vertical_member_uses_a_valid_local_frame_no_degenerate_cross_product():
    """The local-axis construction switches its reference vector for a
    near-vertical member (dx=dy=0) to avoid a zero cross product; this
    checks that path directly, both for correctness (a known cantilever
    deflection) and for not raising/NaN-ing."""
    L = 2.5
    A_cm2 = 15.0
    I_cm4 = 300.0
    nodes = [(0.0, 0.0, 0.0), (0.0, 0.0, L)]   # straight up the global Z axis
    members = [{'a': 0, 'b': 1, 'conn': 'rigid', 'E': E_GPA, 'A': A_cm2,
                'I': I_cm4, 'J': I_cm4, 'Fy': FY}]
    P = 4.0
    loads = [{'node': 1, 'fx': -P}]
    supports = [{'node': 0, 'type': 'fixed'}]

    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None
    assert all(math.isfinite(v) for v in res['node_res'][1].values())
    EI = E_GPA * 1e9 * I_cm4 * 1e-8
    expected = -(P * 1e3 * L ** 3) / (3 * EI)
    got = res['node_res'][1]['ux'] / 1000.0
    assert got == pytest.approx(expected, rel=1e-6)


# ── boundary-condition freedom ──────────────────────────────────────────────

def _simple_tripod():
    """Three pin bars from a common apex down to three well-spread base
    nodes -- a minimal, genuinely 3D, statically stable space truss to
    exercise boundary conditions on."""
    nodes = [(0.0, 0.0, 3.0),      # 0: apex
             (-2.0, -2.0, 0.0),    # 1
             (2.0, -2.0, 0.0),     # 2
             (0.8, 2.3, 0.0)]      # 3 -- off the x=0 plane on purpose, so the
                                   #    apex-to-3 bar has a nonzero x-direction
                                   #    cosine (see test_a_single_dof_can_be_...)
    members = [{'a': 0, 'b': i, 'conn': 'pin', 'E': E_GPA, 'A': 10.0, 'Fy': FY}
               for i in (1, 2, 3)]
    return nodes, members


def test_hand_picked_dofs_with_no_preset_match_the_equivalent_preset():
    nodes, members = _simple_tripod()
    loads = [{'node': 0, 'fz': -10.0}]

    preset_supports = [{'node': i, 'type': 'pin'} for i in (1, 2, 3)]
    res_preset, err1 = sm.analyze(nodes, members, loads, preset_supports)
    assert err1 is None

    handpicked_supports = [
        {'node': i, 'dofs': {'ux': True, 'uy': True, 'uz': True}} for i in (1, 2, 3)
    ]
    res_hand, err2 = sm.analyze(nodes, members, loads, handpicked_supports)
    assert err2 is None

    for a, b in zip(res_preset['node_res'], res_hand['node_res']):
        for k in sm.DOF_NAMES:
            assert a[k] == pytest.approx(b[k], abs=1e-9)


def _square_base_pyramid():
    """A 4-legged pyramid: an apex over a braced square base. Unlike the
    3-leg tripod, a corner here can be given LESS than a full 'pin' and
    still be stable, because the two base-edge bars into a fixed
    neighbouring corner brace its horizontal directions independently of
    the apex -- the setup this module's "any combination of restrained
    DOFs" claim needs to demonstrate on something that is not, itself, a
    mechanism the moment one corner is under-restrained."""
    nodes = [(0.0, 0.0, 3.0),        # 0: apex
             (-2.0, -2.0, 0.0),      # 1
             (2.0, -2.0, 0.0),       # 2
             (2.0, 2.0, 0.0),        # 3
             (-2.0, 2.0, 0.0)]       # 4
    members = [{'a': 0, 'b': i, 'conn': 'pin', 'E': E_GPA, 'A': 10.0, 'Fy': FY}
               for i in (1, 2, 3, 4)]
    for i, j in ((1, 2), (2, 3), (3, 4), (4, 1)):
        members.append({'a': i, 'b': j, 'conn': 'pin', 'E': E_GPA, 'A': 10.0, 'Fy': FY})
    return nodes, members


def test_a_single_dof_can_be_restrained_independent_of_the_other_five():
    """The whole point of per-DOF boundary conditions: restrain exactly one
    translational DOF at a node that would otherwise be fully free, with no
    preset at all, and see that -- and only that -- axis lock in."""
    nodes, members = _square_base_pyramid()
    # Fully support three of the four corners; the fourth gets ONLY uz
    # restrained (its own weight-bearing direction) and stays free
    # horizontally -- not a condition any preset in PRESET_SUPPORTS spells
    # directly ('pin' locks all three translations at once). Its horizontal
    # directions are instead braced through the base-edge bars into the two
    # fully-fixed neighbouring corners, exactly like a real base diaphragm.
    supports = [
        {'node': 1, 'type': 'pin'},
        {'node': 2, 'type': 'pin'},
        {'node': 3, 'type': 'pin'},
        {'node': 4, 'dofs': {'uz': True}},
    ]
    loads = [{'node': 0, 'fz': -10.0}]
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None
    # node 4 must be free to move horizontally
    assert abs(res['node_res'][4]['ux']) > 0 or abs(res['node_res'][4]['uy']) > 0
    # but its vertical reaction exists (it is carrying load)
    assert 4 in res['reactions']
    assert res['reactions'][4]['Fz'] != pytest.approx(0.0, abs=1e-9)
    # and it has no horizontal reaction, since ux/uy were never restrained there
    assert res['reactions'][4]['Fx'] == 0.0
    assert res['reactions'][4]['Fy'] == 0.0


def test_arbitrary_dof_combination_free_rotation_locked_translation_free():
    """A node fully free to translate but with ONE rotation restrained --
    not expressible by any preset -- must still assemble and solve without
    granting rotational DOFs anywhere they are not actually needed."""
    nodes = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1, 'conn': 'rigid', 'E': E_GPA, 'A': 10.0,
                'I': 200.0, 'J': 200.0, 'Fy': FY}]
    supports = [
        {'node': 0, 'type': 'fixed'},
        {'node': 1, 'dofs': {'rx': True}},   # torsionally locked tip, free otherwise
    ]
    loads = [{'node': 1, 'fy': -1.0}]
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None
    assert res['node_res'][1]['rx'] == pytest.approx(0.0, abs=1e-12)
    assert abs(res['node_res'][1]['uy']) > 0


def test_unknown_preset_name_is_rejected_with_a_clear_message():
    with pytest.raises(ValueError):
        sm.support_restraints({'node': 0, 'type': 'not_a_real_preset'})


# ── boundary-condition validation / mesh integrity ──────────────────────────

def test_no_supports_at_all_is_reported_not_silently_singular():
    nodes, members = _simple_tripod()
    err = sm.check_boundary_setup(nodes, members, [])
    assert err is not None
    assert 'boundary condition' in err.lower()


def test_free_floating_axis_is_named_in_the_error():
    """Supports that restrain only X and Y translation leave Z entirely
    free -- a rigid-body mechanism the coarse pre-check must catch by name,
    not just eventually fail with a bare singular-matrix message."""
    nodes, members = _simple_tripod()
    supports = [{'node': i, 'dofs': {'ux': True, 'uy': True}} for i in (1, 2, 3)]
    err = sm.check_boundary_setup(nodes, members, supports)
    assert err is not None
    assert 'z' in err.lower()


def test_support_on_an_out_of_range_node_is_reported():
    nodes, members = _simple_tripod()
    err = sm.check_boundary_setup(nodes, members, [{'node': 99, 'type': 'pin'}])
    assert err is not None
    assert '99' in err


def test_pure_mechanism_is_caught_as_singular_not_a_wrong_answer():
    """Two nodes joined by nothing but a single pin bar along X, both fully
    pinned in translation: perfectly adequate (not what this test is
    about) -- instead give the model a floating, disconnected node with a
    load on it and supports elsewhere, which the coarse per-axis check
    cannot see (all three axes ARE restrained somewhere) but the actual
    solve must still refuse to silently answer."""
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (5.0, 5.0, 5.0)]
    members = [{'a': 0, 'b': 1, 'conn': 'pin', 'E': E_GPA, 'A': 10.0, 'Fy': FY}]
    supports = [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'pin'}]
    loads = [{'node': 2, 'fz': -1.0}]   # node 2 has no member at all
    res, err = sm.analyze(nodes, members, loads, supports)
    assert res is None
    assert err is not None


def test_self_weight_is_split_evenly_between_the_two_end_nodes():
    L = 4.0
    A_cm2 = 10.0
    nodes = [(0.0, 0.0, 0.0), (L, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1, 'conn': 'pin', 'E': E_GPA, 'A': A_cm2, 'Fy': FY}]
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    total_W = (A_cm2 * 1e-4) * L * 78.5
    by_node = {ld['node']: ld['fz'] for ld in loads}
    assert by_node[0] == pytest.approx(-total_W / 2, rel=1e-9)
    assert by_node[1] == pytest.approx(-total_W / 2, rel=1e-9)


def test_combine_loads_sums_contributions_on_the_same_node():
    a = [{'node': 0, 'fx': 1.0, 'fy': 0.0, 'fz': 0.0}]
    b = [{'node': 0, 'fx': 2.0, 'fy': 5.0, 'fz': -1.0}]
    combined = sm.combine_loads(a, b)
    assert len(combined) == 1
    assert combined[0]['fx'] == pytest.approx(3.0)
    assert combined[0]['fy'] == pytest.approx(5.0)
    assert combined[0]['fz'] == pytest.approx(-1.0)


# ── degree_of_indeterminacy ──────────────────────────────────────────────────

def _tetrahedron():
    """A fully-triangulated 3D tetrahedron (4 joints, all 6 possible pin
    members present) with the classic minimal "3-2-1" support scheme:
    node 0 pinned in all 3 translations (fixes translation), node 1
    restrained in the 2 directions perpendicular to edge 0-1 (fixes
    rotation about the other two axes), node 2 restrained in the 1
    direction perpendicular to the 0-1-2 plane (fixes the last rotation)
    -- 6 restraint components total, the textbook minimum for a stable,
    statically DETERMINATE 3D truss (m + r - 3j = 6 + 6 - 12 = 0)."""
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    members = [{'a': a, 'b': b, 'conn': 'pin', 'E': E_GPA, 'A': 20.0, 'Fy': FY}
              for a, b in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))]
    supports = [
        {'node': 0, 'dofs': {'ux': True, 'uy': True, 'uz': True}},
        {'node': 1, 'dofs': {'uy': True, 'uz': True}},
        {'node': 2, 'dofs': {'uz': True}},
    ]
    return nodes, members, supports


def test_degree_of_indeterminacy_is_zero_for_a_minimally_supported_determinate_truss():
    nodes, members, supports = _tetrahedron()
    assert sm.degree_of_indeterminacy(nodes, members, supports) == 0
    # and it really is determinate+stable, not just numerically coincidental
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    _res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None


def test_degree_of_indeterminacy_is_positive_for_an_over_restrained_truss():
    nodes, members, supports = _tetrahedron()
    over = supports + [{'node': 3, 'dofs': {'uz': True}}]
    assert sm.degree_of_indeterminacy(nodes, members, over) == 1
    # redundant, not unstable -- it still solves fine
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    _res, err = sm.analyze(nodes, members, loads, over)
    assert err is None


def test_degree_of_indeterminacy_is_negative_for_a_mechanism():
    nodes, members, supports = _tetrahedron()
    under = supports[:2]   # drop node 2's restraint -- one rotation is now free
    assert sm.degree_of_indeterminacy(nodes, members, under) == -1
    loads = sm.self_weight_loads(nodes, members, unit_weight_kN_m3=78.5)
    _res, err = sm.analyze(nodes, members, loads, under)
    assert err is not None   # genuinely a mechanism, not just a number


def test_degree_of_indeterminacy_of_a_fixed_fixed_rigid_member_matches_hand_calc():
    # A single rigid member, both ends fully fixed, no intermediate joint:
    # every one of its 12 total reaction components is a genuine unknown,
    # but the member (as one free body) only offers 6 independent global
    # equilibrium equations -- DSI = 6 (member's own 6 internal-force
    # unknowns) + 12 (reactions) - 12 (6 DOF/node x 2 nodes) = 6, matching
    # the classic fixed-fixed-beam result once the extra out-of-plane DOF
    # a 3D formulation carries are accounted for.
    nodes = [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1, 'conn': 'rigid', 'E': E_GPA, 'A': 20.0,
               'I': 800.0, 'J': 50.0}]
    supports = [{'node': 0, 'type': 'fixed'}, {'node': 1, 'type': 'fixed'}]
    assert sm.degree_of_indeterminacy(nodes, members, supports) == 6


def test_degree_of_indeterminacy_ignores_which_load_case_is_applied():
    # a structural (geometry/connectivity/supports) property, not a
    # per-load-case one -- the whole point of "static indeterminacy"
    nodes, members, supports = _tetrahedron()
    dsi = sm.degree_of_indeterminacy(nodes, members, supports)
    assert dsi == sm.degree_of_indeterminacy(nodes, members, supports)   # pure function
    for m in members:
        assert 'conn' in m   # unchanged by the call -- no mutation either


def test_node_moment_vectors_picks_the_larger_end_not_the_sum():
    # Two collinear rigid members sharing node 1, hand-crafted member_res
    # (no real solve needed -- this only tests the aggregation rule). Both
    # members run along global X, so _local_axes works out to the global
    # frame exactly (identity transform), making the expected numbers
    # trivial to predict by hand: global Mx=T, My=My, Mz=Mz directly.
    nodes = [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (6.0, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1, 'conn': 'rigid'}, {'a': 1, 'b': 2, 'conn': 'rigid'}]
    member_res = [
        {'length_m': 3.0, 'T': 0.0, 'My_a': 5.0, 'Mz_a': 0.0, 'My_b': -5.0, 'Mz_b': 0.0},
        {'length_m': 3.0, 'T': 0.0, 'My_a': 8.0, 'Mz_a': 0.0, 'My_b': -8.0, 'Mz_b': 0.0},
    ]
    vecs = sm.node_moment_vectors(nodes, members, member_res)
    assert vecs[0] == {'Mx': 0.0, 'My': 5.0, 'Mz': 0.0}
    # node 1 sees +8 (member 1's a-end) and -5 (member 0's b-end) -- the
    # LARGER-magnitude one (8) wins, not their sum (which would be 3 and
    # would misleadingly read as "barely any moment here")
    assert vecs[1] == {'Mx': 0.0, 'My': 8.0, 'Mz': 0.0}
    assert vecs[2] == {'Mx': 0.0, 'My': -8.0, 'Mz': 0.0}


def test_node_moment_vectors_omits_nodes_touched_only_by_pin_members():
    nodes = [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1, 'conn': 'pin'}]
    member_res = [{'length_m': 3.0, 'N': 12.0}]
    assert sm.node_moment_vectors(nodes, members, member_res) == {}


def test_node_moment_vectors_matches_the_reaction_at_a_singly_connected_support():
    # A single rigid member, TILTED (not axis-aligned) so _local_axes must
    # do a genuine rotation, fixed at node 0 only. With no directly-applied
    # moment load at node 0, the support reaction moment IS exactly the
    # member's own end moment expressed in global axes -- the same
    # physical quantity, computed two different ways (the global residual
    # Ku-F vs. this function's own local-to-global transform) -- so they
    # must agree exactly if the transform here is correct.
    nodes = [(0.0, 0.0, 0.0), (2.0, 1.0, 1.0)]
    members = [{'a': 0, 'b': 1, 'conn': 'rigid', 'E': E_GPA, 'A': 20.0,
               'I': 800.0, 'J': 50.0}]
    supports = [{'node': 0, 'type': 'fixed'}]
    loads = [{'node': 1, 'fy': -5.0, 'fz': -8.0}]
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None
    vecs = sm.node_moment_vectors(nodes, members, res['member_res'])
    assert 0 in vecs
    for k in ('Mx', 'My', 'Mz'):
        assert vecs[0][k] == pytest.approx(res['reactions'][0][k], abs=1e-6)


def test_total_restrained_dofs_counts_the_minimal_3_2_1_scheme_as_exactly_6():
    nodes, members, supports = _tetrahedron()
    assert sm.total_restrained_dofs(nodes, supports) == 6


def test_total_restrained_dofs_is_zero_with_no_supports_at_all():
    nodes, members, supports = _tetrahedron()
    assert sm.total_restrained_dofs(nodes, []) == 0


def test_total_restrained_dofs_merges_duplicate_restraints_on_the_same_node():
    nodes, members, supports = _tetrahedron()
    # restraining ux on node 0 twice (already restrained) must not double-count
    duplicated = supports + [{'node': 0, 'dofs': {'ux': True}}]
    assert sm.total_restrained_dofs(nodes, duplicated) == 6


def test_total_restrained_dofs_flags_the_same_mechanism_that_negative_dsi_catches():
    # a structure can ALSO be flagged unstable via total_restrained_dofs < 6
    # even when degree_of_indeterminacy's own aggregate count would otherwise
    # be masked by internal bracing redundancy -- the caveat this helper
    # exists to catch is exactly this: DSI alone is necessary but not
    # sufficient for stability.
    nodes, members, supports = _tetrahedron()
    under = supports[:2]
    assert sm.total_restrained_dofs(nodes, under) == 5
    assert sm.total_restrained_dofs(nodes, under) < 6


# ── tension-only members / the crane (roadmap v2, 3.6) ────────────────────

def _guyed_mast():
    """A rigid mast with a guy either side, in the XZ plane.

    The mast is rigid on purpose: a pin-jointed one holds its top only along
    its own axis, so the instant a guy goes slack the top is free and the
    solve reports a mechanism -- an artefact of the idealisation, not a fact
    about the frame.
    """
    sec = dict(E=200.0, A=20.0, I=400.0, J=400.0)
    nodes = [(0.0, 0.0, 0.0), (0.0, 0.0, 4.0), (-3.0, 0.0, 0.0), (3.0, 0.0, 0.0)]
    mast = dict(sec); mast.update(a=0, b=1, conn='rigid')
    left = dict(sec); left.update(a=1, b=2, conn='pin', tension_only=True)
    right = dict(sec); right.update(a=1, b=3, conn='pin', tension_only=True)
    supports = [{'node': 0, 'type': 'fixed'}, {'node': 2, 'type': 'pin'},
                {'node': 3, 'type': 'pin'}]
    return nodes, [mast, left, right], supports


def test_a_cable_pulls_and_its_opposite_goes_slack():
    nodes, members, supports = _guyed_mast()
    res, err = sm.analyze(nodes, members, [{'node': 1, 'fx': 10.0}], supports)
    assert err is None
    left, right = res['member_res'][1], res['member_res'][2]
    assert left['N'] > 0, 'the windward guy must carry tension'
    assert right['N'] == 0.0 and right['slack'] is True


def test_the_slack_side_swaps_when_the_load_reverses():
    nodes, members, supports = _guyed_mast()
    res, _ = sm.analyze(nodes, members, [{'node': 1, 'fx': -10.0}], supports)
    left, right = res['member_res'][1], res['member_res'][2]
    assert left['slack'] is True and left['N'] == 0.0
    assert right['N'] > 0


def test_the_same_frame_in_ordinary_bars_takes_compression():
    """The premise of the whole feature: without tension_only, that member
    pushes. If this ever stops being true the cable tests prove nothing."""
    nodes, members, supports = _guyed_mast()
    for m in members:
        m.pop('tension_only', None)
    res, _ = sm.analyze(nodes, members, [{'node': 1, 'fx': 10.0}], supports)
    assert res['member_res'][2]['N'] < 0


def test_a_cable_is_never_reported_in_compression():
    nodes, members, supports = _guyed_mast()
    for fx in (-25.0, -5.0, 0.0, 5.0, 25.0):
        res, err = sm.analyze(nodes, members, [{'node': 1, 'fx': fx}], supports)
        assert err is None, f'fx={fx}: {err}'
        for i in (1, 2):
            assert res['member_res'][i]['N'] >= 0.0, f'fx={fx} put a cable in compression'


def test_a_slack_cable_reports_what_it_would_have_carried():
    """N_trial is how the active-set loop decides to bring a cable back, so
    it has to be the real trial force, not a placeholder."""
    nodes, members, supports = _guyed_mast()
    res, _ = sm.analyze(nodes, members, [{'node': 1, 'fx': 10.0}], supports)
    right = res['member_res'][2]
    assert right['slack'] is True
    assert right['N_trial'] < 0, 'the slack guy would have been in compression'


def test_without_tension_only_members_nothing_changes():
    """One pass, same answer -- every existing model must be untouched."""
    nodes, members, supports = _guyed_mast()
    for m in members:
        m.pop('tension_only', None)
    loads = [{'node': 1, 'fx': 7.0, 'fz': -3.0}]
    a, ea = sm.analyze(nodes, members, loads, supports)
    b, eb = sm._analyze_once(nodes, members, loads, supports)
    assert ea is None and eb is None
    for ra, rb in zip(a['member_res'], b['member_res']):
        assert ra['N'] == pytest.approx(rb['N'])


def test_is_tension_only_reads_the_flag_not_a_soft_section():
    assert sm.is_tension_only({'tension_only': True})
    assert not sm.is_tension_only({'E': 1e-9, 'A': 1e-9})
    assert not sm.is_tension_only({})


def test_the_slack_message_is_used_when_dropping_a_cable_is_what_broke_it(monkeypatch):
    """A cable that cannot push can leave a frame with no load path at all.
    That deserves its own message: the generic singular-matrix text sends the
    reader hunting for missing members, when the cause is a member that IS
    there and has simply gone slack.

    Driven through a stub because the interesting case is a first pass that
    SOLVES and a later one that does not -- a frame that is already a
    mechanism on pass one fails before any cable has gone slack, and then the
    generic message is the correct one.
    """
    calls = []

    def fake_once(nodes, members, loads, supports, panels=None,
                  member_loads=None, slack=frozenset()):
        calls.append(frozenset(slack))
        if not slack:
            return ({'node_res': [], 'member_res': [{'N': -5.0}],
                     'reactions': {}, 'panel_res': []}, None)
        return None, 'Singular stiffness matrix -- generic text'

    monkeypatch.setattr(sm, '_analyze_once', fake_once)
    cable = {'a': 0, 'b': 1, 'tension_only': True}
    res, err = sm.analyze([(0.0, 0.0, 0.0), (0.0, 0.0, 1.0)], [cable], [], [])
    assert res is None
    assert 'slack' in err.lower() and 'pull' in err.lower()
    assert calls == [frozenset(), frozenset({0})], calls


def test_a_frame_already_broken_on_the_first_pass_keeps_the_generic_message():
    """The other half of the rule above: nothing has gone slack yet, so the
    slack-specific message would be a false explanation."""
    sec = dict(E=200.0, A=20.0, I=400.0, J=400.0)
    cable = dict(sec); cable.update(a=0, b=1, conn='pin', tension_only=True)
    res, err = sm.analyze([(0.0, 0.0, 0.0), (0.0, 0.0, 3.0)], [cable],
                          [{'node': 0, 'fz': -50.0}],
                          [{'node': 1, 'type': 'pin'}])
    assert res is None
    assert 'slack' not in err.lower()


def test_the_crane_geometry_is_what_the_roadmap_describes():
    sec = dict(E=200.0, A=20.0, I=400.0, J=400.0)
    nodes = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 4.0, 0.0), (0.0, 4.0, 0.0)]
    out_nodes, out_members, hook, anchor = sg.add_cable_crane(
        nodes, [], [0, 1, 2, 3], sec, rise=5.0, mast=2.0)
    assert len(out_nodes) == 6
    assert out_nodes[hook] == pytest.approx((2.0, 2.0, 5.0))    # centroid, raised
    assert out_nodes[anchor] == pytest.approx((2.0, 2.0, 7.0))  # mast on top
    cables = [m for m in out_members if m['role'] == 'crane_cable']
    masts = [m for m in out_members if m['role'] == 'crane_mast']
    assert len(cables) == 4 and len(masts) == 1
    assert all(m['tension_only'] and m['conn'] == 'pin' for m in cables)
    assert all(m['b'] == hook for m in cables)
    # rigid, for the reason in the docstring: a pin-jointed mast leaves the
    # hook free to swing the moment the cables go slack
    assert masts[0]['conn'] == 'rigid'
    assert (masts[0]['a'], masts[0]['b']) == (hook, anchor)


def test_the_automatic_rise_scales_with_how_far_apart_the_nodes_are():
    near = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 1.0, 0.0)]
    far = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (5.0, 10.0, 0.0)]
    assert sg.crane_auto_rise(far, [0, 1, 2]) > sg.crane_auto_rise(near, [0, 1, 2])


def test_fewer_than_three_nodes_is_refused():
    sec = dict(E=200.0, A=20.0, I=400.0, J=400.0)
    with pytest.raises(ValueError, match='at least 3'):
        sg.add_cable_crane([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [], [0, 1], sec)


# The "does the crane carry the whole lift" equilibrium check lives in
# tests/test_stereo_app.py, on the app's own generated grid, because the app
# is what adds the restraints a lift needs. It cannot be done on a handful of
# loose nodes, and the reason turned out to be bigger than first written
# here: a body hanging from concurrent cables has THREE zero-stiffness modes,
# not one. Swing in x, swing in y, and spin about the vertical. The swings
# are there because a hanging load is a pendulum and its restoring force is a
# geometric, second-order term no linear solver carries; the spin is there
# because the slings are pinned and meet at one point.
#
# Worth knowing before writing any test of a hanging model: an equilibrium
# check CANNOT detect this. Adding a rigid-body mode to a solution does not
# violate equilibrium, so the sum-of-verticals test below passed on a model
# whose stiffness matrix had a condition number of 6.2e16 and returned
# displacements of 1.2e10 m under a different load case. What detects it is
# the conditioning, and a second asymmetric load case -- see
# TestTheLiftIsWellPosed in tests/test_stereo_app.py, and crane_steady_lines
# for the three restraints that remove the modes.


def test_a_rigid_tension_only_rod_is_refused_by_name():
    """"Tension-only" and "rigid" together is a modelling mistake, and it has
    to be reported rather than reinterpreted. Only the pin branch of the
    solve publishes `N_trial`, which is what the active-set loop reads to
    decide a slack member is wanted again -- so a rigid cable would be
    dropped from the structure on the first pass and never restored. Wrong,
    and with nothing on screen to explain it.
    """
    nodes, members, supports = _guyed_mast()
    members[1] = dict(members[1]); members[1]['conn'] = 'rigid'
    res, err = sm.analyze(nodes, members, [{'node': 1, 'fx': 10.0}], supports)
    assert res is None
    assert err is not None
    # Named by the number the canvas draws on it, which is 0-based in this
    # app (stereo_app_render labels both nodes and rods with str(i)), and the
    # fix is spelled out rather than left to be inferred.
    assert 'Rod 1' in err
    assert 'pin' in err


def test_the_rigid_cable_check_does_not_fire_on_a_correct_model():
    nodes, members, supports = _guyed_mast()
    res, err = sm.analyze(nodes, members, [{'node': 1, 'fx': 10.0}], supports)
    assert err is None and res is not None


# ── the hanging lift is a pendulum, and a linear solve knows nothing of it ──

def test_the_steady_lines_are_three_and_no_more():
    """Three zero-stiffness modes, three restraints. One fewer leaves a
    mechanism; one more starts carrying load the slings should carry."""
    nodes = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)]
    got = sg.crane_steady_lines(nodes, [0, 1, 2, 3])
    assert len(got) == 3
    dofs = [d for _n, d in got]
    assert sorted(dofs) == ['ux', 'uy', 'uy'] or sorted(dofs) == ['ux', 'ux', 'uy']


def test_the_first_two_are_both_swings_at_one_node():
    nodes = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)]
    got = sg.crane_steady_lines(nodes, [0, 1, 2, 3])
    assert got[0][0] == got[1][0], 'the two swings are held at the same node'
    assert {got[0][1], got[1][1]} == {'ux', 'uy'}


def test_the_third_is_across_the_line_not_along_it():
    """Along the line is the direction the first node already holds, so a
    second restraint there is redundant and removes nothing."""
    # Two lifted nodes far apart in x: the spin restraint has to be uy.
    nodes = [(-10.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    got = sg.crane_steady_lines(nodes, [0, 1, 2])
    assert got[2][1] == 'uy'
    # And the other way round.
    nodes = [(0.0, -10.0, 0.0), (0.0, 10.0, 0.0), (1.0, 0.0, 0.0)]
    got = sg.crane_steady_lines(nodes, [0, 1, 2])
    assert got[2][1] == 'ux'


def test_the_spin_restraint_is_on_a_different_node_from_the_swings():
    nodes = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)]
    got = sg.crane_steady_lines(nodes, [0, 1, 2, 3])
    assert got[2][0] != got[0][0]


def test_the_swings_are_held_at_the_longest_lever():
    """The further out, the less force it takes to hold the same rotation."""
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 1.0, 0.0), (20.0, 20.0, 0.0)]
    got = sg.crane_steady_lines(nodes, [0, 1, 2, 3])
    assert got[0][0] == 3


def test_crane_tag_line_still_answers_with_the_first_of_them():
    nodes = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)]
    assert sg.crane_tag_line(nodes, [0, 1, 2, 3]) == \
        sg.crane_steady_lines(nodes, [0, 1, 2, 3])[0]


def test_three_picked_nodes_still_get_three_restraints():
    nodes = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (2.0, 3.0, 0.0)]
    assert len(sg.crane_steady_lines(nodes, [0, 1, 2])) == 3


# ── mechanisms: say where, and do not believe a kilometre ───────────────────

def _hinged_pair():
    """Two pin bars meeting at a free node in a straight line: the middle
    node can move sideways with no stiffness at all."""
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    bar = {'E': 200.0, 'A': 10.0, 'I': 100.0, 'J': 100.0, 'conn': 'pin'}
    members = [dict(bar, a=0, b=1), dict(bar, a=1, b=2)]
    supports = [{'node': 0, 'type': 'pin'}, {'node': 2, 'type': 'pin'}]
    return nodes, members, supports


def test_a_mechanism_is_located_not_just_reported():
    nodes, members, supports = _hinged_pair()
    assert sm.mechanism(nodes, members, supports) == [1]
    res, err = sm.analyze(nodes, members, [{'node': 1, 'fz': -1.0}], supports)
    assert res is None
    assert 'Free to move with no stiffness: node 1.' in err


def test_a_stable_model_has_no_mechanism():
    nodes, members, supports = _hinged_pair()
    nodes.append((1.0, 1.0, 0.0))
    nodes.append((1.0, 0.0, 1.0))
    bar = dict(members[0])
    members += [dict(bar, a=1, b=3), dict(bar, a=1, b=4)]
    supports += [{'node': 3, 'type': 'pin'}, {'node': 4, 'type': 'pin'}]
    assert sm.mechanism(nodes, members, supports) == []


def test_describe_mechanism_caps_the_list():
    text = sm.describe_mechanism(list(range(20)))
    assert text.startswith(' Free to move') and '(and 12 more)' in text
    assert sm.describe_mechanism([]) == ''


def test_the_sparse_solve_matches_the_dense_one(monkeypatch):
    """Above SPARSE_MIN_DOF the matrix is assembled sparse; the answer must
    be the dense one, to round-off."""
    from apps.stereo import stereo_geometry as sg
    mesh = sg.flat_grid(12.0, 12.0, 1.5, 3.0)
    nodes, members = mesh['nodes'], [dict(m, E=200.0, A=20.0, I=400.0,
                                          J=400.0, conn='rigid')
                                     for m in mesh['members']]
    supports = [{'node': i, 'type': 'pin'}
                for i in mesh['support_candidates']]
    loads = [{'node': i, 'fz': -5.0} for i in range(len(nodes))]
    monkeypatch.setattr(sm, 'SPARSE_MIN_DOF', 10 ** 9)
    dense, err1 = sm.analyze(nodes, members, loads, supports)
    monkeypatch.setattr(sm, 'SPARSE_MIN_DOF', 0)
    sparse, err2 = sm.analyze(nodes, members, loads, supports)
    assert err1 is None and err2 is None
    for a, b in zip(dense['node_res'], sparse['node_res']):
        assert a['uz'] == pytest.approx(b['uz'], abs=1e-9)
    for a, b in zip(dense['member_res'], sparse['member_res']):
        assert a['N'] == pytest.approx(b['N'], abs=1e-7)


def test_the_sparse_solve_refuses_a_mechanism(monkeypatch):
    nodes, members, supports = _hinged_pair()
    monkeypatch.setattr(sm, 'SPARSE_MIN_DOF', 0)
    res, err = sm.analyze(nodes, members, [{'node': 1, 'fz': -1.0}], supports)
    assert res is None and 'Singular' in err


# ── a file of several pieces: which one cannot stand ──────────────────────

def _tetra(dx, supports):
    """A pin-jointed tetrahedron at x offset dx, base pinned at `supports`
    of its three base nodes (each a dict of restrained dofs)."""
    base = [(dx, 0.0, 0.0), (dx + 2.0, 0.0, 0.0), (dx + 1.0, 2.0, 0.0)]
    nodes = base + [(dx + 1.0, 0.7, 1.5)]
    pairs = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]
    members = [{'a': a, 'b': b, 'conn': 'pin', 'E': 200.0, 'A': 10.0,
                'I': 50.0, 'J': 50.0, 'Fy': 250.0} for a, b in pairs]
    sups = [dict(sp, node=k) for k, sp in enumerate(supports)]
    return nodes, members, sups


def _three_pieces():
    roll = [{'type': 'pin'}, {'dofs': {'uy': True, 'uz': True}},
            {'dofs': {'uz': True}}]
    pieces = [_tetra(0.0, roll),                      # stands
              _tetra(10.0, []),                       # no support at all
              _tetra(20.0, [{'dofs': {'ux': True}}] * 3)]   # ux only
    nodes, members, supports = [], [], []
    for n, m, s in pieces:
        off = len(nodes)
        nodes += n
        members += [dict(x, a=x['a'] + off, b=x['b'] + off) for x in m]
        supports += [dict(x, node=x['node'] + off) for x in s]
    return nodes, members, supports


def test_each_piece_that_cannot_stand_is_named_with_its_reason():
    nodes, members, supports = _three_pieces()
    msg = sm.describe_loose_pieces(nodes, members, supports)
    assert msg.startswith(' Pieces that cannot stand:')
    assert 'x 10.0 to 12.0' in msg and 'no support at all' in msg
    assert 'x 20.0 to 22.0' in msg
    assert 'x 0.0 to 2.0' not in msg          # the one that stands


def test_a_singular_file_of_pieces_says_which_piece():
    nodes, members, supports = _three_pieces()
    loads = [{'node': 3, 'fz': -10.0}]
    _res, err = sm.analyze(nodes, members, loads, supports)
    assert err is not None
    assert 'Pieces that cannot stand' in err
    assert 'x 10.0 to 12.0' in err and 'x 0.0 to 2.0' not in err


def test_the_sparse_mode_search_finds_the_zero_mode_the_dense_one_does():
    import numpy as np
    import scipy.sparse as sps
    n = sm.MECHANISM_DENSE_DOF + 100
    d = np.arange(n, dtype=float)                    # one exact zero
    w, v, _scale = sm._lowest_modes(sps.diags(d).tocsr(), k=4)
    assert abs(w[0]) < 1e-9 and list(w) == sorted(w)
    assert abs(abs(v[0, 0]) - 1.0) < 1e-6           # the mode is dof 0
    wd, _vd, _s = sm._lowest_modes(np.diag(d[:50]), k=4)
    assert abs(wd[0]) < 1e-12


# ── how a mechanism moves (drawn moving by the app) ───────────────────────

def _square(diagonal=False):
    nodes = [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]
    mem = [{'a': i, 'b': (i + 1) % 4, 'conn': 'pin', 'E': 200.0, 'A': 10.0,
            'I': 100.0, 'J': 100.0} for i in range(4)]
    if diagonal:
        mem.append({'a': 0, 'b': 2, 'conn': 'pin', 'E': 200.0, 'A': 10.0,
                    'I': 100.0, 'J': 100.0})
    pinned = {'ux': True, 'uy': True, 'uz': True}
    return nodes, mem, [{'node': 0, 'dofs': dict(pinned)},
                        {'node': 1, 'dofs': dict(pinned)}]


def test_an_unbraced_square_sways_on_its_supports():
    nodes, mem, sup = _square()
    m = sm.mechanism_mode(nodes, mem, sup)
    assert m['kind'] == 'mechanism' and m['count'] >= 1
    # the supported nodes stay put; the top moves, the largest by exactly 1
    assert m['shape'][0] == (0.0, 0.0, 0.0) and m['shape'][1] == (0.0, 0.0, 0.0)
    peak = max(math.sqrt(sum(c * c for c in d)) for d in m['shape'])
    assert peak == pytest.approx(1.0)
    assert set(sm.mechanism(nodes, mem, sup)) <= {2, 3}


def test_each_way_it_can_move_is_one_mode_and_they_wrap_round():
    nodes, mem, sup = _square()
    first = sm.mechanism_mode(nodes, mem, sup, which=0)
    again = sm.mechanism_mode(nodes, mem, sup, which=first['count'])
    assert again['which'] == 0 and again['shape'] == first['shape']


def test_with_nothing_under_it_it_falls():
    nodes, mem, _sup = _square()
    m = sm.mechanism_mode(nodes, mem, [])
    assert m['kind'] == 'rigid' and m['axis'] == 'z'
    assert m['shape'] == [(0.0, 0.0, -1.0)] * 4


def test_with_nothing_holding_x_it_slides_along_x():
    nodes, mem, _sup = _square()
    sup = [{'node': 0, 'dofs': {'uz': True, 'uy': True}},
           {'node': 1, 'dofs': {'uz': True}}]
    m = sm.mechanism_mode(nodes, mem, sup)
    assert m['kind'] == 'rigid' and m['axis'] == 'x' and m['count'] == 1
    assert m['shape'] == [(1.0, 0.0, 0.0)] * 4


def test_a_braced_and_held_square_does_not_move():
    nodes, mem, sup = _square(diagonal=True)
    sup += [{'node': 2, 'dofs': {'uy': True}},
            {'node': 3, 'dofs': {'uy': True}}]
    assert sm.mechanism_mode(nodes, mem, sup) is None
    assert sm.mechanism_mode([], [], []) is None
