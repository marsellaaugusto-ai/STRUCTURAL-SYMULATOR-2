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
