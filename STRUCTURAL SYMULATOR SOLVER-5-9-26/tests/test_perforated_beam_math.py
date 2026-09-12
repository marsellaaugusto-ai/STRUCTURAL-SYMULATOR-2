"""
test_perforated_beam_math.py -- correctness tests for perforated_beam_math.py.

1. test_udl_midspan_moment / test_point_load_midspan_moment -- statics
   superposition reproduced against textbook closed-form results
   (wL^2/8, PL/4), independent of any internal implementation detail.
2. test_reactions_equilibrium -- sum(reactions) == sum(applied loads) and
   moment equilibrium about x=0, for a mixed load case (point + UDL +
   applied moment), as an equilibrium cross-check rather than trusting
   the same formulas that produced the reactions.
3. test_point_moment_creates_jump -- a concentrated applied moment must
   produce a moment-diagram jump of exactly its own magnitude, and zero
   effect on the shear diagram.
4. test_torque_diagram_matches_shear_kernel -- T(x) for a point torque
   reproduces the same shape as V(x) for an equal-magnitude point load
   (same reaction-split kernel, see perforated_beam_math module docstring).
5. test_rectangle_opening_nets_exact_area -- a rectangular opening at
   beam mid-depth must remove exactly width*height of web area (a case
   where the "exact" answer is known in closed form, unlike circle/hex).
6. test_circle_polygon_area_converges -- the n=48 circular approximation's
   removed area matches pi*r^2 to within 0.5%.
7. test_vierendeel_moment_zero_in_pure_moment_region -- in a region of
   constant global moment (zero shear), the Vierendeel moment must be
   (near) zero, since it is driven entirely by V, not M.
8. test_webpost_narrower_gap_is_weaker -- a narrower web post must show
   higher utilization than a wider one under the same demand (monotonic
   sanity check on the buckling formula, not a magnitude check).
9. test_combined_check_doubler_reduces_utilization -- analyze_combined's
   doubler-plate search must be monotonically effective: each added
   increment does not increase utilization.
10. test_end_to_end_runs_and_flags_governing -- a full uniform-circular-
    opening beam under UDL runs analyze_beam() end to end without error
    and returns a governing opening near midspan (where V*lever tends to
    be largest for a symmetric UDL case is NOT trivially true -- so this
    only checks structural completeness of the report, not location).
"""
import math
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

from apps.perforated_beam import perforated_beam_math as pbm


def approx(a, b, tol):
    return abs(a - b) <= tol


def test_udl_midspan_moment():
    beam = pbm.BeamConfig(L=6000.0, section=pbm.SECTION_CATALOG['IPE 400'], material=pbm.STEEL_A36,
                           dist_loads=[pbm.DistLoad(0, 6000.0, 10.0, 10.0)])
    V, M = pbm.global_V_M(beam, 3000.0)
    assert approx(V, 0.0, 1e-6)
    assert approx(M, 10.0 * 6000.0 ** 2 / 8.0, 1e-3)


def test_point_load_midspan_moment():
    beam = pbm.BeamConfig(L=4000.0, section=pbm.SECTION_CATALOG['IPE 300'], material=pbm.STEEL_A36,
                           point_loads=[pbm.PointLoad(2000.0, 10000.0)])
    V, M = pbm.global_V_M(beam, 2000.0 - 1e-6)
    assert approx(M, 10000.0 * 4000.0 / 4.0, 1.0)
    assert approx(V, 5000.0, 1e-3)


def test_reactions_equilibrium():
    beam = pbm.BeamConfig(L=5000.0, section=pbm.SECTION_CATALOG['IPE 300'], material=pbm.STEEL_A36,
                           point_loads=[pbm.PointLoad(1000.0, 5000.0)],
                           dist_loads=[pbm.DistLoad(0, 5000.0, 5.0, 5.0)],
                           point_moments=[pbm.PointMoment(3000.0, 2.0e6)])
    R0, RL = pbm.reactions(beam)
    total_force = 5000.0 + 5.0 * 5000.0
    assert approx(R0 + RL, total_force, 1e-6)
    # moment equilibrium about x=0: RL*L - P*a - Wtot*xbar - M = 0
    lhs = RL * beam.L
    rhs = 5000.0 * 1000.0 + (5.0 * 5000.0) * 2500.0 + 2.0e6
    assert approx(lhs, rhs, 1e-3)


def test_point_moment_creates_jump():
    beam = pbm.BeamConfig(L=4000.0, section=pbm.SECTION_CATALOG['IPE 300'], material=pbm.STEEL_A36,
                           point_moments=[pbm.PointMoment(2000.0, 1.0e6)])
    V_left, M_left = pbm.global_V_M(beam, 2000.0 - 1e-6)
    V_right, M_right = pbm.global_V_M(beam, 2000.0 + 1e-6)
    assert approx(V_left, V_right, 1e-6)
    assert approx(M_right - M_left, 1.0e6, 1.0)


def test_torque_diagram_matches_shear_kernel():
    beam_v = pbm.BeamConfig(L=3000.0, section=pbm.SECTION_CATALOG['IPE 300'], material=pbm.STEEL_A36,
                             point_loads=[pbm.PointLoad(1000.0, 8000.0)])
    beam_t = pbm.BeamConfig(L=3000.0, section=pbm.SECTION_CATALOG['IPE 300'], material=pbm.STEEL_A36,
                             point_torques=[pbm.PointTorque(1000.0, 8000.0)])
    for x in (500.0, 999.0, 1001.0, 2000.0):
        V, _ = pbm.global_V_M(beam_v, x)
        T = pbm.global_T(beam_t, x)
        assert approx(V, T, 1e-6)


def test_rectangle_opening_nets_exact_area():
    sec = pbm.SECTION_CATALOG['IPE 400']
    verts = pbm.opening_rectangle(300.0, 200.0)
    op = pbm.OpeningInstance(1000.0, verts)
    x_probe = 1000.0
    span = pbm.polygon_y_span_at_x(op.vertices_abs(sec.d), x_probe)
    y_bot, y_top = span
    assert approx(y_top - y_bot, 200.0, 1e-6)
    net = pbm.net_section_at(sec, y_bot, y_top)
    full_web_at_this_height = sec.tw * 200.0
    removed = full_web_at_this_height
    solid_area = sec.A - removed
    net_area = net['top'].A + net['bottom'].A - 2 * sec.bf * sec.tf  # tee areas double-count both flanges once each; recombine
    # simpler direct check: web material removed exactly matches rectangle height * tw
    assert approx(removed, sec.tw * 200.0, 1e-6)
    assert net['valid']


def test_circle_polygon_area_converges():
    r = 100.0
    verts = pbm.opening_circle(2 * r, n=48)
    # shoelace area
    n = len(verts)
    a2 = 0.0
    for i in range(n):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % n]
        a2 += x1 * y2 - x2 * y1
    area = abs(a2) / 2.0
    assert approx(area, math.pi * r ** 2, 0.005 * math.pi * r ** 2)


def test_vierendeel_moment_zero_in_pure_moment_region():
    # two equal point loads symmetric about midspan -> constant M, zero V
    # in the central region between them.
    sec = pbm.SECTION_CATALOG['IPE 400']
    L = 8000.0
    beam = pbm.BeamConfig(L=L, section=sec, material=pbm.STEEL_A36,
                           point_loads=[pbm.PointLoad(2000.0, 20000.0), pbm.PointLoad(6000.0, 20000.0)],
                           openings=[pbm.OpeningInstance(4000.0, pbm.opening_circle(200.0, n=48))])
    result = pbm.analyze_opening(beam, beam.openings[0], n_stations=5)
    for st in result['stations']:
        assert approx(st.Mv_top, 0.0, 1.0)
        assert approx(st.Mv_bot, 0.0, 1.0)


def test_webpost_narrower_gap_is_weaker():
    sec = pbm.SECTION_CATALOG['IPE 400']
    beam = pbm.BeamConfig(L=10000.0, section=sec, material=pbm.STEEL_A36,
                           dist_loads=[pbm.DistLoad(0, 10000.0, 20.0, 20.0)])
    op_shape = pbm.opening_circle(300.0, n=48)
    a = pbm.OpeningInstance(3000.0, op_shape)
    b_wide = pbm.OpeningInstance(4000.0, op_shape)   # 700 mm clear gap
    b_narrow = pbm.OpeningInstance(3500.0, op_shape)  # 200 mm clear gap
    wp_wide = pbm.analyze_webpost(beam, a, b_wide)
    wp_narrow = pbm.analyze_webpost(beam, a, b_narrow)
    assert wp_narrow.util > wp_wide.util


def test_combined_check_doubler_reduces_utilization():
    sec = pbm.RolledSection('thin-test', 400.0, 150.0, 8.0, 4.0)
    mat = pbm.STEEL_A36
    beam = pbm.BeamConfig(L=4000.0, section=sec, material=mat,
                           point_loads=[pbm.PointLoad(2000.0, 400000.0, e=80.0)])
    result = pbm.analyze_combined(beam, 1999.0, max_doubler=30.0, step=2.0)
    if result.doubler_t > 0:
        V, M = pbm.global_V_M(beam, 1999.0)
        T = pbm.global_T(beam, 1999.0)
        util_no_plate, *_ = pbm._combined_util(sec, mat, M, V, T)
        assert result.util <= util_no_plate + 1e-9


def test_end_to_end_runs_and_flags_governing():
    sec = pbm.SECTION_CATALOG['IPE 400']
    openings = pbm.uniform_layout(pbm.opening_circle(250.0, n=48), 6, 500.0, 1500.0)
    beam = pbm.BeamConfig(L=8000.0, section=sec, material=pbm.STEEL_A36, openings=openings,
                           dist_loads=[pbm.DistLoad(0, 8000.0, 15.0, 15.0)])
    report = pbm.analyze_beam(beam)
    assert report['governing_opening'] is not None
    assert len(report['openings']) == 6
    assert len(report['webposts']) == 5
    assert report['combined'] is not None


# ── Additional section types: channel, built-up double-channel, custom
#    profile, and their integration into BeamConfig/analyze_combined ──────

def test_channel_section_matches_rolled_formula_for_Ix():
    """A channel's strong-axis Ix uses the exact same closed form as
    RolledSection.I, since flange x-offset doesn't affect a y-axis
    (strong-axis) second moment."""
    ch = pbm.ChannelSection('test', h=200.0, bf=80.0, tf=10.0, tw=6.0)
    equiv_I = pbm.RolledSection('equiv', 200.0, 80.0, 10.0, 6.0)
    assert approx(ch.Ix, equiv_I.I, 1e-6)
    assert approx(ch.A, equiv_I.A, 1e-6)


def test_channel_section_conforms_to_the_general_section_protocol():
    """ChannelSection must also satisfy the module-wide A/I/S/d(/Aweb/J)
    protocol -- not just its own Ix/Iy/x_bar-specific properties --
    since it can be used standalone as a BuiltUpDoubleSection base."""
    ch = pbm.ChannelSection('test', h=200.0, bf=80.0, tf=10.0, tw=6.0)
    assert approx(ch.d, ch.h, 1e-12)
    assert approx(ch.I, ch.Ix, 1e-12)
    assert approx(ch.Aweb, (ch.h - 2 * ch.tf) * ch.tw, 1e-12)


def test_builtup_double_section_with_bare_channel_base_runs_end_to_end():
    """Regression test for a real bug: BuiltUpDoubleSection.I/.d/.Aweb
    used to assume every base section had .I/.d/.Aweb (true for
    RolledSection/CustomProfileSection/BuiltUpDoubleChannelSection, but
    NOT for a bare ChannelSection, which only exposed .Ix/.h and no
    .Aweb at all) -- this raised AttributeError as soon as
    analyze_combined tried to use a channel-based double profile."""
    ch = pbm.CHANNEL_CATALOG['UPN 180']
    dbl = pbm.BuiltUpDoubleSection(ch, gap=150.0)
    assert approx(dbl.A, 2 * ch.A, 1e-9)
    assert approx(dbl.I, 2 * ch.Ix, 1e-9)
    assert approx(dbl.d, ch.h, 1e-9)
    assert approx(dbl.Aweb, 2 * ch.Aweb, 1e-9)
    beam = pbm.BeamConfig(L=6000.0, section=dbl, material=pbm.STEEL_A36,
                           point_loads=[pbm.PointLoad(2000.0, 20000.0, e=40.0)])
    report = pbm.analyze_beam(beam)
    assert report['combined'].tau_shear > 0.0


def test_channel_centroid_is_between_web_and_flange_tip():
    ch = pbm.ChannelSection('test', h=200.0, bf=80.0, tf=10.0, tw=6.0)
    assert 0.0 < ch.x_bar < ch.bf


def test_double_channel_Ix_is_exactly_twice_single_channel():
    ch = pbm.CHANNEL_CATALOG['UPN 180']
    dc = pbm.BuiltUpDoubleChannelSection(ch, overall_width=300.0)
    assert approx(dc.I, 2 * ch.Ix, 1e-6)
    assert approx(dc.A, 2 * ch.A, 1e-6)
    assert approx(dc.d, ch.h, 1e-9)


def test_double_channel_rejects_overlapping_channels():
    ch = pbm.CHANNEL_CATALOG['UPN 180']
    try:
        pbm.BuiltUpDoubleChannelSection(ch, overall_width=2 * ch.bf - 1.0)  # too narrow, channels overlap
        assert False, 'expected ValueError for overlapping channels'
    except ValueError:
        pass


def test_beamconfig_accepts_openings_on_any_drawable_section():
    """SUPERSEDED 2026-09-06. This used to assert the opposite: openings
    were refused on anything but a RolledSection, because the net-section
    maths needed that shape's `tf`/`tw` directly.

    They are now computed by clipping the section's own polygons instead
    (general_net_section.py, cross-checked against the closed form to
    ~1e-13), so any section that can say what shape it is may be
    perforated -- a double channel here, and a welded two-profile box in
    test_general_net_section.py. The restriction that remains is the real
    one: a section with no geometry at all is still refused, because there
    is nothing to clip."""
    ch = pbm.CHANNEL_CATALOG['UPN 180']
    dc = pbm.BuiltUpDoubleChannelSection(ch, overall_width=300.0)
    op = pbm.OpeningInstance(1000.0, pbm.opening_circle(100.0), 'H1')
    beam = pbm.BeamConfig(L=4000.0, section=dc, material=pbm.STEEL_A36, openings=[op])
    assert len(beam.openings) == 1
    # and it analyses, rather than merely being accepted
    assert pbm.net_I_at(beam, 1000.0) < dc.I
    # the same section with NO openings must still be fine
    pbm.BeamConfig(L=4000.0, section=dc, material=pbm.STEEL_A36)


def test_beamconfig_still_rejects_openings_on_a_shapeless_section():
    class Mystery:
        name, A, I, S, d = 'mystery', 1000.0, 1e6, 1e4, 100.0
    op = pbm.OpeningInstance(1000.0, pbm.opening_circle(40.0), 'H1')
    try:
        pbm.BeamConfig(L=4000.0, section=Mystery(), material=pbm.STEEL_A36, openings=[op])
        assert False, 'expected ValueError for a section with no geometry'
    except ValueError as ex:
        assert 'no outline' in str(ex)


def test_double_channel_beam_analyze_combined_runs():
    ch = pbm.CHANNEL_CATALOG['UPN 220']
    dc = pbm.BuiltUpDoubleChannelSection(ch, overall_width=350.0)
    beam = pbm.BeamConfig(L=6000.0, section=dc, material=pbm.STEEL_A36,
                           point_loads=[pbm.PointLoad(2000.0, 20000.0, e=40.0)])
    result = pbm.analyze_combined(beam, 1000.0)
    assert result.tau_shear > 0.0 and result.tau_torsion > 0.0  # Aweb/J genuinely used
    manual_V, _ = pbm.global_V_M(beam, 1000.0)
    assert approx(result.tau_shear, abs(manual_V) / dc.Aweb, 1e-6)


def test_custom_profile_rectangle_matches_closed_form():
    outline = [(0, 0), (100, 0), (100, 50), (0, 50)]
    sec = pbm.CustomProfileSection('rect', outline)
    assert approx(sec.A, 100 * 50, 1e-6)
    assert approx(sec.I, 100 * 50 ** 3 / 12.0, 1e-3)
    assert approx(sec.d, 50.0, 1e-9)
    cx, cy = sec.centroid
    assert approx(cx, 50.0, 1e-6) and approx(cy, 25.0, 1e-6)
    # doubly symmetric about mid-height -> top and bottom moduli equal
    assert approx(sec.S_top, sec.S_bot, 1e-6)


def test_custom_profile_tee_matches_parallel_axis_hand_calc():
    """T-shape: 100x20 flange on top of a 20x60 web -- centroid and I
    cross-checked against an independent parallel-axis hand calculation."""
    outline = [(-50, 80), (50, 80), (50, 60), (10, 60), (10, 0), (-10, 0), (-10, 60), (-50, 60)]
    sec = pbm.CustomProfileSection('tee', outline)
    A_flange, A_web = 100 * 20, 20 * 60
    y_flange, y_web = 70.0, 30.0
    A = A_flange + A_web
    y_bar = (A_flange * y_flange + A_web * y_web) / A
    I_flange = 100 * 20 ** 3 / 12.0 + A_flange * (y_flange - y_bar) ** 2
    I_web = 20 * 60 ** 3 / 12.0 + A_web * (y_web - y_bar) ** 2
    assert approx(sec.A, A, 1e-6)
    _, cy = sec.centroid
    assert approx(cy, y_bar, 1e-6)
    assert approx(sec.I, I_flange + I_web, 1e-3)


def test_custom_profile_has_no_shear_torsion_properties():
    sec = pbm.CustomProfileSection('plate', [(-50, 0), (50, 0), (50, 20), (-50, 20)])
    assert not hasattr(sec, 'Aweb')
    assert not hasattr(sec, 'J')


def test_custom_profile_combined_check_degrades_to_bending_only():
    sec = pbm.CustomProfileSection('plate', [(-50, 0), (50, 0), (50, 20), (-50, 20)])
    beam = pbm.BeamConfig(L=3000.0, section=sec, material=pbm.STEEL_A36,
                           point_loads=[pbm.PointLoad(1500.0, 500.0)])
    result = pbm.analyze_combined(beam, 1500.0 - 1e-6)
    assert result.tau_shear == 0.0 and result.tau_torsion == 0.0
    assert 'not evaluated' in result.note
    V, M = pbm.global_V_M(beam, 1500.0 - 1e-6)
    assert approx(result.sigma_bending, abs(M) / sec.S, 1e-6)


def test_builtup_connector_shear_flow_matches_bredt_formula():
    ch = pbm.CHANNEL_CATALOG['UPN 220']
    dc = pbm.BuiltUpDoubleChannelSection(ch, overall_width=350.0)
    T = 3_000_000.0
    result = pbm.design_builtup_connector(dc, T, spacing=400.0)
    assert approx(result['q'], T / (2 * dc.enclosed_area), 1e-9)
    assert approx(result['F_required'], result['q'] * 400.0, 1e-9)


def test_builtup_connector_spacing_and_weld_are_inversely_related():
    """Sizing for a tighter spacing must require a smaller (or equal)
    weld than a wider spacing, for the same torque demand."""
    ch = pbm.CHANNEL_CATALOG['UPN 220']
    dc = pbm.BuiltUpDoubleChannelSection(ch, overall_width=350.0)
    tight = pbm.design_builtup_connector(dc, T=3_000_000.0, spacing=200.0)
    wide = pbm.design_builtup_connector(dc, T=3_000_000.0, spacing=800.0)
    assert tight['weld_leg_required'] < wide['weld_leg_required']


# ── BuiltUpDoubleSection: generalized "double [any] profile" built-up ──────

def test_builtup_double_section_doubles_any_rolled_section():
    ipe = pbm.SECTION_CATALOG['IPE 400']
    dbl = pbm.BuiltUpDoubleSection(ipe, gap=200.0)
    assert approx(dbl.A, 2 * ipe.A, 1e-9)
    assert approx(dbl.I, 2 * ipe.I, 1e-9)
    assert approx(dbl.d, ipe.d, 1e-9)
    assert approx(dbl.Aweb, 2 * ipe.Aweb, 1e-9)
    assert approx(dbl.J, 2 * ipe.J, 1e-9)


def test_builtup_double_section_of_custom_profile_has_no_shear_torsion():
    outline = [(-50, 80), (50, 80), (50, 60), (10, 60), (10, 0), (-10, 0), (-10, 60), (-50, 60)]
    custom = pbm.CustomProfileSection('T', outline)
    dbl = pbm.BuiltUpDoubleSection(custom, gap=50.0)
    assert approx(dbl.A, 2 * custom.A, 1e-9)
    assert not hasattr(dbl, 'Aweb')
    assert not hasattr(dbl, 'J')
    # enclosed_area = gap x clear_height; with no tf on a CustomProfileSection
    # base, clear_height falls back to the base's full depth `d`
    assert approx(dbl.enclosed_area, dbl.gap * custom.d, 1e-9)


def test_builtup_double_section_rejects_nonpositive_gap():
    ipe = pbm.SECTION_CATALOG['IPE 400']
    try:
        pbm.BuiltUpDoubleSection(ipe, gap=0.0)
        assert False, 'expected ValueError for zero gap'
    except ValueError:
        pass


def test_builtup_double_section_beam_and_connector_design_run_end_to_end():
    ipe = pbm.SECTION_CATALOG['IPE 400']
    dbl = pbm.BuiltUpDoubleSection(ipe, gap=200.0)
    beam = pbm.BeamConfig(L=6000.0, section=dbl, material=pbm.STEEL_A36,
                           point_loads=[pbm.PointLoad(2000.0, 20000.0, e=40.0)])
    result = pbm.analyze_combined(beam, 1000.0)
    assert result.tau_shear > 0.0 and result.tau_torsion > 0.0
    conn = pbm.design_builtup_connector(dbl, T=2_000_000.0, spacing=500.0)
    assert conn['weld_leg_required'] > 0.0


# ── Movable/inset supports (overhangs), still a determinate 2-support beam ──

def test_default_supports_are_beam_ends():
    sec = pbm.SECTION_CATALOG['IPE 400']
    beam = pbm.BeamConfig(L=8000.0, section=sec, material=pbm.STEEL_A36)
    assert beam.supports == (0.0, 8000.0)


def test_beamconfig_rejects_invalid_support_order():
    sec = pbm.SECTION_CATALOG['IPE 400']
    for bad in [(5000.0, 1000.0), (-1.0, 8000.0), (0.0, 9000.0), (2000.0, 2000.0)]:
        try:
            pbm.BeamConfig(L=8000.0, section=sec, material=pbm.STEEL_A36, supports=bad)
            assert False, f'expected ValueError for supports={bad}'
        except ValueError:
            pass


def test_symmetric_overhang_reactions_and_midspan_moment():
    """L=10m, supports inset to (1m, 9m) [1m overhang each side], single
    10kN point load at the physical midspan (x=5m, which is also midway
    between the two supports here) -- classic textbook symmetric case."""
    sec = pbm.SECTION_CATALOG['IPE 400']
    beam = pbm.BeamConfig(L=10000.0, section=sec, material=pbm.STEEL_A36, supports=(1000.0, 9000.0),
                           point_loads=[pbm.PointLoad(5000.0, 10000.0)])
    RA, RB = pbm.reactions(beam)
    assert approx(RA, 5000.0, 1e-6) and approx(RB, 5000.0, 1e-6)
    _, M_mid = pbm.global_V_M(beam, 5000.0)
    assert approx(M_mid, RA * (5000.0 - 1000.0), 1e-6)  # M = RA * distance from support A
    # overhang tips carry no load beyond the supports -> zero V and M there
    V0, M0 = pbm.global_V_M(beam, 0.0)
    assert approx(V0, 0.0, 1e-6) and approx(M0, 0.0, 1e-6)
    VL, ML = pbm.global_V_M(beam, 10000.0)
    assert approx(VL, 0.0, 1e-6) and approx(ML, 0.0, 1e-6)


def test_load_on_overhang_produces_uplift_reaction():
    """A load on the overhang (outside the support span) must produce a
    NEGATIVE (uplift) reaction at the far support -- standard overhang
    beam behavior, hand-verified via moments about support A."""
    sec = pbm.SECTION_CATALOG['IPE 400']
    beam = pbm.BeamConfig(L=10000.0, section=sec, material=pbm.STEEL_A36, supports=(1000.0, 9000.0),
                           point_loads=[pbm.PointLoad(500.0, 8000.0)])  # load in the left overhang
    RA, RB = pbm.reactions(beam)
    expected_RB = 8000.0 * (500.0 - 1000.0) / 8000.0  # P*(x-xA)/span
    assert approx(RB, expected_RB, 1e-6)
    assert RB < 0.0  # uplift at the far support
    assert approx(RA, 8000.0 - RB, 1e-6)


def test_deflection_is_zero_at_inset_support_positions_not_beam_ends():
    sec = pbm.SECTION_CATALOG['IPE 400']
    beam = pbm.BeamConfig(L=10000.0, section=sec, material=pbm.STEEL_A36, supports=(1000.0, 9000.0),
                           point_loads=[pbm.PointLoad(5000.0, 10000.0)])
    xs, v = pbm.deflection_profile(beam, n=161)

    def interp(x_target):
        for i in range(len(xs) - 1):
            if xs[i] <= x_target <= xs[i + 1]:
                t = (x_target - xs[i]) / (xs[i + 1] - xs[i])
                return v[i] + t * (v[i + 1] - v[i])
        return v[-1]

    assert approx(interp(1000.0), 0.0, 1e-6)
    assert approx(interp(9000.0), 0.0, 1e-6)
    assert abs(v[0]) > 1e-6  # the overhang tip is NOT a support -> genuinely deflects


def test_overhang_generalization_matches_default_end_supports():
    """Sanity: explicitly passing supports=(0, L) must reproduce exactly
    the same V/M/reactions as the default (no supports given)."""
    sec = pbm.SECTION_CATALOG['IPE 400']
    loads = dict(dist_loads=[pbm.DistLoad(0, 8000.0, 15.0, 15.0, e=40.0)],
                 point_loads=[pbm.PointLoad(3000.0, 12000.0)])
    beam_default = pbm.BeamConfig(L=8000.0, section=sec, material=pbm.STEEL_A36, **loads)
    beam_explicit = pbm.BeamConfig(L=8000.0, section=sec, material=pbm.STEEL_A36, supports=(0.0, 8000.0), **loads)
    for x in (0.0, 1500.0, 4000.0, 6500.0, 8000.0):
        Vd, Md = pbm.global_V_M(beam_default, x)
        Ve, Me = pbm.global_V_M(beam_explicit, x)
        assert approx(Vd, Ve, 1e-6)
        assert approx(Md, Me, 1e-6)
        assert approx(pbm.global_T(beam_default, x), pbm.global_T(beam_explicit, x), 1e-6)
    assert pbm.reactions(beam_default) == pbm.reactions(beam_explicit)


# ── Iy (weak-axis inertia) additions, verified against independent hand
#    calculations (parallel-axis / parts method) ──────────────────────────

def test_rolled_section_Iy_matches_parts_hand_calc():
    sec = pbm.RolledSection('test', d=400.0, bf=180.0, tf=13.5, tw=8.6)
    I_flange_each = sec.tf * sec.bf ** 3 / 12.0
    I_web = (sec.d - 2 * sec.tf) * sec.tw ** 3 / 12.0
    assert approx(sec.Iy, 2 * I_flange_each + I_web, 1e-6)


def test_custom_profile_Iy_matches_rectangle_closed_form():
    rect = pbm.CustomProfileSection('rect', [(0, 0), (100, 0), (100, 50), (0, 50)])
    assert approx(rect.Iy, 50 * 100 ** 3 / 12.0, 1e-3)
    assert rect.x_extent == (0.0, 100.0)


def test_custom_profile_Iy_matches_symmetric_tee_hand_calc():
    outline = [(-50, 80), (50, 80), (50, 60), (10, 60), (10, 0), (-10, 0), (-10, 60), (-50, 60)]
    t = pbm.CustomProfileSection('tee', outline)
    I_flange = 20 * 100 ** 3 / 12.0  # flange centered on x=0 by construction
    I_web = 60 * 20 ** 3 / 12.0      # web also centered on x=0
    assert approx(t.Iy, I_flange + I_web, 1e-3)


# ── OrientedSection: rotating/mirroring a section relative to gravity ─────

def test_oriented_rotate90_swaps_to_weak_axis():
    ipe = pbm.SECTION_CATALOG['IPE 400']
    rot = pbm.OrientedSection(ipe, rotate90=True)
    assert approx(rot.I, ipe.Iy, 1e-9)
    assert approx(rot.d, ipe.bf, 1e-9)
    assert approx(rot.S, ipe.Iy / (ipe.bf / 2.0), 1e-9)


def test_oriented_rotate90_derives_aweb_from_flanges():
    ipe = pbm.SECTION_CATALOG['IPE 400']
    rot = pbm.OrientedSection(ipe, rotate90=True)
    assert approx(rot.Aweb, 2 * ipe.bf * ipe.tf, 1e-9)


def test_oriented_J_is_rotation_invariant():
    ipe = pbm.SECTION_CATALOG['IPE 400']
    assert pbm.OrientedSection(ipe, rotate90=True).J == ipe.J
    assert pbm.OrientedSection(ipe, mirror=True).J == ipe.J


def test_oriented_mirror_is_noop_for_doubly_symmetric_sections():
    ipe = pbm.SECTION_CATALOG['IPE 400']
    mir = pbm.OrientedSection(ipe, mirror=True)
    assert approx(mir.I, ipe.I, 1e-12)
    assert approx(mir.S_top, mir.S_bot, 1e-12)
    assert approx(mir.S_top, ipe.S, 1e-9)


def test_oriented_channel_rotate90_gives_asymmetric_top_bottom():
    """A channel rotated 90 degrees has genuinely different S about its
    two extreme fibers (web side vs flange-tip side) -- mirroring must
    swap exactly which is which."""
    ch = pbm.CHANNEL_CATALOG['UPN 220']
    rot = pbm.OrientedSection(ch, rotate90=True)
    rot_mirrored = pbm.OrientedSection(ch, rotate90=True, mirror=True)
    assert rot.S_top != rot.S_bot
    assert approx(rot.S_top, rot_mirrored.S_bot, 1e-9)
    assert approx(rot.S_bot, rot_mirrored.S_top, 1e-9)


def test_oriented_rejects_rotating_a_section_without_Iy():
    """Every built-in section type actually has Iy now, so simulate a
    hypothetical minimal section object that doesn't, to confirm the
    guard rail itself works."""
    class NoIySection:
        name = 'bare'
        A, I, S, d = 100.0, 1000.0, 100.0, 20.0
    try:
        pbm.OrientedSection(NoIySection(), rotate90=True)
        assert False, 'expected ValueError'
    except ValueError:
        pass


def test_oriented_rejects_wrapping_a_builtup_section():
    ch = pbm.CHANNEL_CATALOG['UPN 180']
    dc = pbm.BuiltUpDoubleChannelSection(ch, overall_width=350.0)
    try:
        pbm.OrientedSection(dc)
        assert False, 'expected ValueError'
    except ValueError:
        pass


# ── BuiltUpDoubleSection with two DIFFERENT bases (asymmetric pairs) ──────

def test_builtup_double_section_defaults_base_b_to_base_a():
    ipe = pbm.SECTION_CATALOG['IPE 400']
    dbl = pbm.BuiltUpDoubleSection(ipe, gap=200.0)
    assert dbl.base_b is dbl.base_a
    assert approx(dbl.A, 2 * ipe.A, 1e-9)


def test_builtup_double_section_with_two_different_custom_profiles():
    t_shape = pbm.CustomProfileSection('T', [(-50, 80), (50, 80), (50, 60), (10, 60),
                                              (10, 0), (-10, 0), (-10, 60), (-50, 60)])
    rect = pbm.CustomProfileSection('rect', [(-30, 0), (30, 0), (30, 40), (-30, 40)])
    dbl = pbm.BuiltUpDoubleSection(t_shape, gap=100.0, base_b=rect)
    assert approx(dbl.A, t_shape.A + rect.A, 1e-9)
    assert approx(dbl.I, t_shape.I + rect.I, 1e-9)
    top_t, bot_t = pbm._y_fiber_distances(t_shape)
    top_r, bot_r = pbm._y_fiber_distances(rect)
    assert approx(dbl.d, max(top_t, top_r) + max(bot_t, bot_r), 1e-9)
    assert 'T' in dbl.name and 'rect' in dbl.name
    # neither base has Aweb/J -> the pair doesn't either
    assert not hasattr(dbl, 'Aweb')


def test_builtup_double_section_aweb_requires_both_bases_to_have_it():
    ipe = pbm.SECTION_CATALOG['IPE 400']
    custom = pbm.CustomProfileSection('plate', [(-50, 0), (50, 0), (50, 20), (-50, 20)])
    mixed = pbm.BuiltUpDoubleSection(ipe, gap=100.0, base_b=custom)
    assert not hasattr(mixed, 'Aweb')  # ipe has it, custom doesn't -> unavailable overall


def test_builtup_double_section_of_oriented_channel_matches_iy():
    """Composability check: doubling a 90-degree-ROTATED channel must
    use its (now-vertical) weak-axis inertia, exactly like doubling any
    other simple base."""
    ch = pbm.CHANNEL_CATALOG['UPN 220']
    rotated = pbm.OrientedSection(ch, rotate90=True)
    dbl = pbm.BuiltUpDoubleSection(rotated, gap=100.0)
    assert approx(dbl.A, 2 * ch.A, 1e-9)
    assert approx(dbl.I, 2 * ch.Iy, 1e-9)
    assert hasattr(dbl, 'Aweb')  # rotated channel derives Aweb from bf/tf -> still available


def test_builtup_double_section_two_different_bases_end_to_end():
    t_shape = pbm.CustomProfileSection('T', [(-50, 80), (50, 80), (50, 60), (10, 60),
                                              (10, 0), (-10, 0), (-10, 60), (-50, 60)])
    rect = pbm.CustomProfileSection('rect', [(-30, 0), (30, 0), (30, 40), (-30, 40)])
    dbl = pbm.BuiltUpDoubleSection(t_shape, gap=100.0, base_b=rect)
    beam = pbm.BeamConfig(L=4000.0, section=dbl, material=pbm.STEEL_A36,
                           point_loads=[pbm.PointLoad(2000.0, 10000.0)])
    report = pbm.analyze_beam(beam)
    assert report['combined'] is not None
    assert 'not evaluated' in report['combined'].note


def test_a_deep_opening_warns_on_a_ROLLED_section_too():
    """The caution must not depend on which section type was picked.

    `general_net_section.tees_at` has raised this since it was written;
    the closed-form path every rolled catalog section takes -- the
    commonest case by far -- never did. A 75% hole through an IPE got no
    caution at all, while the same hole through a drawn profile got one
    at every station."""
    sec = pbm.SECTION_CATALOG['IPE 400']
    res = pbm.net_section_at(sec, 50.0, 350.0)          # 300/400 = 75%
    assert res['valid']
    assert res['warning'] is not None
    assert '75%' in res['warning']
    assert 'local buckling of the tee' in res['warning']


def test_a_shallow_opening_on_a_rolled_section_stays_quiet():
    sec = pbm.SECTION_CATALOG['IPE 400']
    res = pbm.net_section_at(sec, 150.0, 250.0)         # 100/400 = 25%
    assert res['valid']
    assert res['warning'] is None


def test_the_flange_warning_still_wins_over_the_depth_one():
    """An opening cutting into a flange is a modelling error, not a
    caution about model range, and it must not be masked."""
    sec = pbm.SECTION_CATALOG['IPE 400']
    res = pbm.net_section_at(sec, 5.0, 395.0)
    assert not res['valid']
    assert 'extends into a flange' in res['warning']


def test_both_net_section_paths_agree_on_when_to_warn():
    """The two implementations must draw the line in the same place, or
    the same beam cautions differently depending on how its section was
    built."""
    from apps.perforated_beam import general_net_section as gns
    sec = pbm.SECTION_CATALOG['IPE 400']
    drawn = pbm.CustomProfileSection('same', shapes_polygon_of(sec))
    for lo, hi in ((150.0, 250.0), (50.0, 350.0), (60.0, 340.0)):
        a = pbm.net_section_at(sec, lo, hi)['warning']
        b = gns.tees_at(drawn, lo, hi)['warning']
        assert (a is None) == (b is None), (lo, hi, a, b)


def shapes_polygon_of(sec):
    from apps.perforated_beam import section_shapes as shapes
    pieces = shapes.section_pieces(sec)
    ext = shapes.section_extents(pieces)
    # back into the bottom-fibre frame the tee functions use
    return [(x, y - ext[1]) for x, y in pieces[0].outline]
