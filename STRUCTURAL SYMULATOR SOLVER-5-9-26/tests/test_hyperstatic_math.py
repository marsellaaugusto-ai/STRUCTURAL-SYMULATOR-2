"""
test_hyperstatic_math.py -- correctness tests for hyperstatic_math.py and
for the diagnosis fixes P-1..P-4 in perforated_beam_math.py.

Every check here is against a value known independently of this code --
a textbook closed form, an exact invariant of linear elasticity, or an
equilibrium statement -- rather than against a previously recorded output
of the same functions. See MANIFESTO §2.

A. Diagnosis regressions (2026-09-05 report)
   1. test_moment_linearity_under_load_reversal -- P-1. For a linear
      elastic determinate beam, M(-w) == -M(+w) EXACTLY. The old code
      lost this for any non-uniform uplift ramp, by up to a sign flip,
      because a missing abs() sent negative ramps down a uniform-strip
      centroid fallback. The invariant is what catches the whole class.
   2. test_zero_resultant_ramp_still_produces_reactions -- P-2. A ramp
      with w1 == -w2 has zero resultant but a non-zero moment about the
      supports, so it MUST produce equal and opposite reactions.
   3. test_reactions_continuous_through_zero_resultant -- P-2, stated as
      continuity: sweeping w2 through the crossing must not step.
   4. test_reversed_distributed_span_is_normalised -- P-3.
   5. test_degenerate_rolled_section_refused / _catalog_still_valid --
      P-4, including the check that the fix does not reject the shipped
      catalog.

B. The stiffness solver
   6. test_two_pin_reproduces_closed_form -- the determinate case solved
      through the FE path must match the closed-form kernel to machine
      precision, for every load type. This is what pins down the sign
      conventions (especially the rotation DOF).
   7. test_propped_cantilever / test_fixed_fixed / test_two_span_
      continuous / test_cantilever -- the four standard textbook
      indeterminate results.
   8. test_diagrams_close_at_free_end -- V(L) and M(L) must vanish on an
      arbitrarily messy 4-support beam. One residual that exercises every
      sign convention in the recovery at once.
   9. test_openings_soften_the_beam / test_openings_shift_redundant --
      the perforated-specific reason this solver meshes at all: on an
      indeterminate beam the reduced I(x) at an opening changes the
      REACTIONS, not just the deflection.
  10. test_singular_arrangements_refused -- a mechanism must produce the
      explanatory error, not a bare linear-algebra failure.
"""
import math
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

import pytest

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import hyperstatic_math as hym
from apps.perforated_beam.hyperstatic_math import SupportSpec


SEC = pbm.SECTION_CATALOG['IPE 400']
MAT = pbm.Material(Fy=250.0, E=200000.0)
L = 8000.0
W = 20.0        # N/mm, downward


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def beam(specs=None, loads=(), dloads=(), moments=(), Lb=L, openings=(), section=SEC):
    b = pbm.BeamConfig(L=Lb, section=section, material=MAT,
                       openings=list(openings),
                       support_specs=list(specs) if specs else None)
    for x, P in loads:
        b.point_loads.append(pbm.PointLoad(x, P))
    for x1, x2, w1, w2 in dloads:
        b.dist_loads.append(pbm.DistLoad(x1, x2, w1, w2))
    for x, M in moments:
        b.point_moments.append(pbm.PointMoment(x, M))
    return b


# ── A. diagnosis regressions ─────────────────────────────────────────────

@pytest.mark.parametrize('w1,w2', [(10.0, 30.0), (30.0, 10.0), (0.0, 20.0),
                                   (-10.0, -30.0), (-30.0, 10.0), (7.5, 7.5)])
def test_moment_linearity_under_load_reversal(w1, w2):
    """P-1: M(-w) == -M(+w) exactly, for every sign combination.

    The pre-fix code was exact for a UNIFORM negative load (w1 == w2 made
    the wrong centroid accidentally right), which is precisely why this
    survived so long -- uniform uplift is the case anyone tests first. So
    the non-uniform combinations above are the ones that matter."""
    pos = beam(dloads=[(0.0, L, w1, w2)])
    neg = beam(dloads=[(0.0, L, -w1, -w2)])
    for f in (0.1, 0.25, 0.5, 0.6, 0.75, 0.9):
        x = L * f
        _, Mp = pbm.global_V_M(pos, x)
        _, Mn = pbm.global_V_M(neg, x)
        assert approx(Mn, -Mp, 1e-12), f'x={x}: M(-w)={Mn}, -M(+w)={-Mp}'


@pytest.mark.parametrize('w1,w2', [(10.0, 30.0), (-10.0, -30.0), (-30.0, 10.0)])
def test_shear_linearity_under_load_reversal(w1, w2):
    pos = beam(dloads=[(0.0, L, w1, w2)])
    neg = beam(dloads=[(0.0, L, -w1, -w2)])
    for f in (0.1, 0.5, 0.9):
        x = L * f
        Vp, _ = pbm.global_V_M(pos, x)
        Vn, _ = pbm.global_V_M(neg, x)
        assert approx(Vn, -Vp, 1e-12)


def test_zero_resultant_ramp_still_produces_reactions():
    """P-2: w1 = -w2 over the full span has no resultant but a real moment
    about the supports. Closed form for a full-span antisymmetric ramp:
    RB = +w*L/6, RA = -w*L/6."""
    w = 20.0
    b = beam(dloads=[(0.0, L, -w, w)])
    RA, RB = pbm.reactions(b)
    assert approx(RB, w * L / 6.0, 1e-12), RB
    assert approx(RA, -w * L / 6.0, 1e-12), RA
    assert approx(RA + RB, 0.0, 1e-12)


def test_reactions_continuous_through_zero_resultant():
    """P-2 as continuity: the old guard made reactions DISCONTINUOUS at
    w1 + w2 == 0 -- a 0.005% input change flipped the answer between 0 and
    26 669 N. Neighbouring inputs must now give neighbouring answers."""
    prev = None
    for w2 in (19.99, 19.999, 20.0, 20.001, 20.01):
        _, RB = pbm.reactions(beam(dloads=[(0.0, L, -20.0, w2)]))
        if prev is not None:
            assert abs(RB - prev) < 50.0, f'step of {abs(RB - prev):.1f} N at w2={w2}'
        prev = RB


def test_reversed_distributed_span_is_normalised():
    """P-3: entering x1 > x2 is a typo, and used to silently invert the
    load. It must now describe the same beam as the correctly ordered
    entry."""
    fwd = beam(dloads=[(2000.0, 6000.0, 10.0, 25.0)])
    rev = beam(dloads=[(6000.0, 2000.0, 25.0, 10.0)])
    assert pbm.reactions(fwd) == pytest.approx(pbm.reactions(rev), rel=1e-12)
    for f in (0.2, 0.5, 0.8):
        assert pbm.global_V_M(fwd, L * f) == pytest.approx(
            pbm.global_V_M(rev, L * f), rel=1e-12)


def test_reversed_distributed_torque_is_normalised():
    a = pbm.DistTorque(6000.0, 2000.0, 5.0, 9.0)
    assert (a.x1, a.x2, a.t1, a.t2) == (2000.0, 6000.0, 9.0, 5.0)


@pytest.mark.parametrize('kwargs', [
    dict(d=0.0, bf=200.0, tf=15.0, tw=10.0),      # zero depth
    dict(d=100.0, bf=200.0, tf=80.0, tw=10.0),    # flanges overlap through the web
    dict(d=400.0, bf=200.0, tf=200.0, tw=10.0),   # d == 2*tf exactly
    dict(d=400.0, bf=8.0, tf=15.0, tw=10.0),      # flange narrower than the web
    dict(d=400.0, bf=200.0, tf=-15.0, tw=10.0),   # negative thickness
])
def test_degenerate_rolled_section_refused(kwargs):
    """P-4: these used to return a plausible I with no complaint."""
    with pytest.raises(ValueError):
        pbm.RolledSection('degenerate', **kwargs)


def test_shipped_catalog_still_valid():
    """The P-4 guard must not reject any real section -- the failure mode
    of an over-tight validator."""
    for name, sec in pbm.SECTION_CATALOG.items():
        assert sec.A > 0 and sec.I > 0, name


# ── B. the stiffness solver ──────────────────────────────────────────────

CASES = {
    'udl': dict(dloads=[(0.0, L, W, W)]),
    'ramp': dict(dloads=[(1000.0, 6000.0, 5.0, 25.0)]),
    'uplift_ramp': dict(dloads=[(1000.0, 6000.0, -5.0, -25.0)]),
    'point_loads': dict(loads=[(L / 3, 50000.0), (0.7 * L, -12000.0)]),
    'point_moment': dict(moments=[(0.4 * L, 3.0e7)]),
    'mixed': dict(loads=[(L / 4, 30000.0)], dloads=[(0.0, L, 4.0, 16.0)],
                  moments=[(0.6 * L, -1.5e7)]),
}


@pytest.mark.parametrize('name', sorted(CASES))
def test_two_pin_reproduces_closed_form(name):
    """The determinate case routed through the FE path must reproduce the
    closed-form kernel. This is the test that pins the sign conventions --
    in particular the rotation DOF, which the 'point_moment' case would
    catch at 200% error if it were flipped."""
    kw = CASES[name]
    hyp = beam([SupportSpec(0.0), SupportSpec(L)], **kw)
    det = beam(None, **kw)
    stations = [L * f for f in (0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95)]
    dets = [pbm.global_V_M(det, x) for x in stations]
    # Normalise against the diagram's own global peak: V is identically
    # zero at midspan of a symmetric UDL, so a local-value denominator
    # would turn a rounding residual into an infinite relative error.
    Vref = max(abs(v) for v, _ in dets) or 1.0
    Mref = max(abs(m) for _, m in dets) or 1.0
    for x, (dv, dm) in zip(stations, dets):
        hv, hm = pbm.global_V_M(hyp, x)
        assert abs(hv - dv) / Vref < 1e-8, f'V at x={x}'
        assert abs(hm - dm) / Mref < 1e-8, f'M at x={x}'


def test_propped_cantilever():
    """Fixed at 0, propped at L, full UDL: R = 5wL/8 and 3wL/8,
    M_fixed = -wL^2/8, M_max_span = 9wL^2/128 at x = 5L/8."""
    b = beam([SupportSpec(0.0, 'fixed'), SupportSpec(L, 'pin')],
             dloads=[(0.0, L, W, W)])
    R = pbm.support_reactions(b)
    assert approx(R[0][1], 5 * W * L / 8, 1e-6)
    assert approx(R[1][1], 3 * W * L / 8, 1e-6)
    assert approx(R[0][2], -W * L * L / 8, 1e-6)
    assert approx(pbm.global_V_M(b, 0.0)[1], -W * L * L / 8, 1e-6)
    assert approx(pbm.global_V_M(b, 5 * L / 8)[1], 9 * W * L * L / 128, 1e-6)
    _, v = pbm.deflection_profile(b)
    assert max(v) == pytest.approx(W * L ** 4 / (185.0 * MAT.E * SEC.I), rel=0.01)


def test_fixed_fixed():
    """Both ends built in, full UDL: M_end = -wL^2/12, M_mid = +wL^2/24,
    v_mid = wL^4/(384 EI)."""
    b = beam([SupportSpec(0.0, 'fixed'), SupportSpec(L, 'fixed')],
             dloads=[(0.0, L, W, W)])
    R = pbm.support_reactions(b)
    assert approx(R[0][1], W * L / 2, 1e-6)
    assert approx(R[1][1], W * L / 2, 1e-6)
    assert approx(R[0][2], -W * L * L / 12, 1e-6)
    assert approx(pbm.global_V_M(b, L / 2)[1], W * L * L / 24, 1e-6)
    _, v = pbm.deflection_profile(b)
    assert max(v) == pytest.approx(W * L ** 4 / (384 * MAT.E * SEC.I), rel=0.01)


def test_two_span_continuous():
    """Two equal spans, UDL throughout: the classic R = 3wL/8, 10wL/8,
    3wL/8 with M = -wL^2/8 over the interior support."""
    b = beam([SupportSpec(0.0), SupportSpec(L), SupportSpec(2 * L)],
             dloads=[(0.0, 2 * L, W, W)], Lb=2 * L)
    R = pbm.support_reactions(b)
    assert approx(R[0][1], 3 * W * L / 8, 1e-6)
    assert approx(R[1][1], 10 * W * L / 8, 1e-6)
    assert approx(R[2][1], 3 * W * L / 8, 1e-6)
    assert approx(pbm.global_V_M(b, L)[1], -W * L * L / 8, 1e-6)
    assert approx(pbm.global_V_M(b, 3 * L / 8)[1], 9 * W * L * L / 128, 1e-6)


def test_cantilever():
    """A single fixed support is determinate, but must still solve."""
    b = beam([SupportSpec(0.0, 'fixed')], dloads=[(0.0, L, W, W)])
    R = pbm.support_reactions(b)
    assert approx(R[0][1], W * L, 1e-6)
    assert approx(R[0][2], -W * L * L / 2, 1e-6)
    _, v = pbm.deflection_profile(b)
    assert v[-1] == pytest.approx(W * L ** 4 / (8 * MAT.E * SEC.I), rel=0.01)


def test_diagrams_close_at_free_end():
    """Nothing lies beyond x = L, so V(L) and M(L) must both vanish once
    the last support's reaction is counted. One residual that exercises
    every sign convention in the equilibrium recovery simultaneously."""
    b = beam([SupportSpec(0.0, 'fixed'), SupportSpec(3000.0),
              SupportSpec(7000.0), SupportSpec(L, 'fixed')],
             loads=[(1500.0, 40000.0), (5000.0, -15000.0)],
             dloads=[(0.0, L, 5.0, 25.0), (2000.0, 6000.0, -8.0, 12.0)],
             moments=[(4000.0, 2.5e7)])
    V_end, M_end = pbm.global_V_M(b, L)
    P_total = (sum(pl.P for pl in b.point_loads)
               + sum((d.w1 + d.w2) / 2 * (d.x2 - d.x1) for d in b.dist_loads))
    M_ref = max(abs(pbm.global_V_M(b, L * k / 8.0)[1]) for k in range(1, 8))
    assert abs(V_end) < 1e-9 * abs(P_total)
    assert abs(M_end) < 1e-9 * M_ref
    assert approx(sum(r[1] for r in pbm.support_reactions(b)), P_total, 1e-9)


def test_reactions_refuses_when_pair_is_not_the_whole_story():
    b = beam([SupportSpec(0.0), SupportSpec(L / 2), SupportSpec(L)],
             dloads=[(0.0, L, W, W)])
    with pytest.raises(ValueError, match='support_reactions'):
        pbm.reactions(b)
    assert len(pbm.support_reactions(b)) == 3


def _perforated(specs, Lb=L):
    """A beam with a run of circular openings through the middle third."""
    shape = pbm.opening_circle(250.0)
    ops = pbm.uniform_layout(shape, n_openings=6, spacing=600.0, x_start=2500.0)
    return beam(specs, dloads=[(0.0, Lb, W, W)], openings=ops, Lb=Lb)


def test_both_paths_report_deflection_with_the_SAME_sign():
    """They did not, and it was a real defect rather than a convention.

    The closed-form path integrates EI*v'' = M, which is Euler-Bernoulli
    with v measured UPWARD, so it returned a sagging beam as negative. The
    stiffness path works in a +down frame and returned the same beam as
    positive. The deflection diagram therefore pointed up or down
    according to which support mode the user picked. Both are now
    POSITIVE = DOWNWARD."""
    kw = dict(L=8000.0, section=SEC, material=MAT)
    det = pbm.BeamConfig(**kw)
    hyp = pbm.BeamConfig(support_specs=[SupportSpec(0.0), SupportSpec(8000.0)], **kw)
    for b in (det, hyp):
        b.dist_loads.append(pbm.DistLoad(0.0, 8000.0, 20.0, 20.0))
    _, v_det = pbm.deflection_profile(det)
    _, v_hyp = pbm.deflection_profile(hyp)
    exact = 5 * 20.0 * 8000.0 ** 4 / (384 * MAT.E * SEC.I)
    # both positive (sagging down), both the textbook magnitude
    assert max(v_det) == pytest.approx(exact, rel=0.01)
    assert max(v_hyp) == pytest.approx(exact, rel=0.01)
    assert min(v_det) == pytest.approx(0.0, abs=1e-6)
    assert min(v_hyp) == pytest.approx(0.0, abs=1e-6)
    # and they agree with each other station by station
    for a, b in zip(v_det, v_hyp):
        assert a == pytest.approx(b, abs=0.02 * exact)


def test_cantilever_tip_deflects_downward_not_up():
    """A sign check that cannot pass by accident: a downward-loaded
    cantilever must give a POSITIVE tip deflection."""
    b = beam([SupportSpec(0.0, 'fixed')], dloads=[(0.0, L, W, W)])
    _, v = pbm.deflection_profile(b)
    assert v[-1] > 0
    assert v[-1] == pytest.approx(W * L ** 4 / (8 * MAT.E * SEC.I), rel=0.01)


def test_openings_soften_the_beam():
    solid = beam([SupportSpec(0.0), SupportSpec(L)], dloads=[(0.0, L, W, W)])
    holed = _perforated([SupportSpec(0.0), SupportSpec(L)])
    assert max(pbm.deflection_profile(holed)[1]) > max(pbm.deflection_profile(solid)[1])


def test_openings_shift_the_redundant():
    """The reason this solver meshes rather than assuming prismatic EI: on
    an INDETERMINATE beam the reduced I(x) at the openings redistributes
    the reactions, which a constant-EI solve would miss entirely. On the
    determinate beam the same openings must leave the reactions untouched
    -- that contrast is the actual content of this test."""
    det_solid = beam([SupportSpec(0.0), SupportSpec(L)], dloads=[(0.0, L, W, W)])
    det_holed = _perforated([SupportSpec(0.0), SupportSpec(L)])
    assert approx(pbm.support_reactions(det_solid)[0][1],
                  pbm.support_reactions(det_holed)[0][1], 1e-9)

    specs = [SupportSpec(0.0, 'fixed'), SupportSpec(L, 'fixed')]
    ind_solid = beam(specs, dloads=[(0.0, L, W, W)])
    ind_holed = _perforated([SupportSpec(0.0, 'fixed'), SupportSpec(L, 'fixed')])
    m_solid = pbm.support_reactions(ind_solid)[0][2]
    m_holed = pbm.support_reactions(ind_holed)[0][2]
    # Openings concentrated at midspan soften the middle, so the span
    # carries relatively less and the built-in ends attract MORE hogging.
    assert abs(m_holed) > abs(m_solid)


@pytest.mark.parametrize('specs,match', [
    ([SupportSpec(1000.0)], 'free to rotate'),
    ([SupportSpec(0.0), SupportSpec(0.0)], 'share the station'),
    ([SupportSpec(-50.0), SupportSpec(L)], 'outside the beam'),
])
def test_singular_arrangements_refused(specs, match):
    with pytest.raises(ValueError, match=match):
        pbm.BeamConfig(L=L, section=SEC, material=MAT, support_specs=specs)


def test_empty_support_specs_means_default_not_error():
    """An empty list reads as 'not specified', like None -- the beam falls
    back to the determinate closed-form path rather than complaining."""
    b = pbm.BeamConfig(L=L, section=SEC, material=MAT, support_specs=[])
    assert b.support_specs == []
    assert b.supports == (0.0, L)
    assert not b.is_hyperstatic
    with pytest.raises(ValueError, match='at least one support'):
        hym.normalize_supports([], L)


def test_unknown_support_kind_refused():
    with pytest.raises(ValueError, match='Unknown support kind'):
        SupportSpec(0.0, 'encastrado')


def test_degree_of_indeterminacy():
    assert hym.degree_of_indeterminacy([SupportSpec(0.0), SupportSpec(L)]) == 0
    assert hym.degree_of_indeterminacy([SupportSpec(0.0, 'fixed')]) == 0
    assert hym.degree_of_indeterminacy(
        [SupportSpec(0.0, 'fixed'), SupportSpec(L)]) == 1
    assert hym.degree_of_indeterminacy(
        [SupportSpec(0.0, 'fixed'), SupportSpec(L, 'fixed')]) == 2
    assert hym.degree_of_indeterminacy(
        [SupportSpec(0.0), SupportSpec(L / 2), SupportSpec(L)]) == 1


def test_solution_is_memoized_but_not_stale():
    """The app builds the BeamConfig first and appends loads afterwards, so
    a cache that ignored later mutation would describe an unloaded beam."""
    b = beam([SupportSpec(0.0), SupportSpec(L)])
    first = b.hyperstatic_solution()
    assert b.hyperstatic_solution() is first          # memoized
    b.dist_loads.append(pbm.DistLoad(0.0, L, W, W))
    second = b.hyperstatic_solution()
    assert second is not first                        # invalidated
    assert approx(second.reactions[0][1], W * L / 2, 1e-6)


def test_end_to_end_perforated_hyperstatic_report():
    """A continuous perforated beam must run the whole analyze_beam
    pipeline -- Vierendeel, web post, combined -- not just the statics."""
    b = _perforated([SupportSpec(0.0), SupportSpec(4000.0), SupportSpec(L)])
    report = pbm.analyze_beam(b)
    assert report['openings']
    assert report['combined'] is not None
