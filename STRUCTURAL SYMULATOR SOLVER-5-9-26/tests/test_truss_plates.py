"""Verification of the Truss tab's shear-panel element and plate design checks.

Plan: `REPORTS AND GUIDES/PLAN_PLATES_P1_P2_2026-09-06.md`, stages 2a/2b/2e.

The reference-free checks come first on purpose. A patch test, a
self-equilibrium check and a `t -> 0` continuity check need no expected
values at all, only the model, so they keep applying to any panel a future
change might break — unlike a single hand-computed number, which only pins
the one case it was written for.

TWO TOLERANCE TRAPS, both found while prototyping this element, both of which
would otherwise be "fixed" by loosening a tolerance until it passed:

  1. The rigid-body patch test must be judged RELATIVE TO ||K||. G*t is of
     order 6e8, so an exactly-satisfied rigid-body mode still leaves
     |K*d| ~ 2e-7 in absolute terms -- pure float64 round-off amplified by
     the element's own stiffness. An absolute tolerance fails a correct
     element and invites someone to go "fix" the formulation.
  2. The shear-cantilever closed form delta = V*L/(G*t*d) assumes RIGID
     flanges. With finite flange area the discrepancy is the flanges
     stretching, and it decays as 1/A: measured 3.813e-3, 3.813e-4, 3.813e-5
     for A = 1e5, 1e6, 1e7 cm^2 -- one decade of error per decade of area,
     exactly. The test below asserts that CONVERGENCE RATE rather than a bare
     tolerance, so it stays sensitive to a real element error instead of
     absorbing one.

A third trap, found the hard way while building this and worth stating
because no element-level test can see it: the panel's corner forces are
K*d, the element's nodal ACTIONS, and what the panel applies to a node is
their NEGATIVE. With the sign wrong the panel still self-equilibrates -- its
four corner forces still sum to zero -- so every check in section 1 passes
happily while every joint the panel touches is out of balance by twice the
corner force. Only `test_joint_equilibrium_still_closes_with_a_panel_present`
catches it. Element tests verify an element; only an assembly test verifies
an assembly.
"""
import math

import pytest

from common import PX_PER_M
from apps.truss.truss_app import analyze
from apps.truss.truss_math import (plate_geometry, plate_stiffness,
                                   plate_material, plate_node_loop,
                                   compute_node_design_actions)


# ── helpers ──────────────────────────────────────────────────────────────────

def m(x, y):
    """metres -> the canvas pixel frame `nodes` uses (y DOWN)."""
    return (x * PX_PER_M, -y * PX_PER_M)


SHAPES = {
    'square':        [(0, 0), (2, 0), (2, 2), (0, 2)],
    'rectangle':     [(0, 0), (3, 0), (3, 1.5), (0, 1.5)],
    'parallelogram': [(0, 0), (3, 0), (3.8, 1.5), (0.8, 1.5)],
    'trapezoid':     [(0, 0), (3, 0), (2.4, 1.5), (0.4, 1.5)],
    'triangle':      [(0, 0), (2.5, 0), (0, 2.0)],
}


def build(shape_pts, t_mm=8.0, G_GPa=80.0):
    nodes = [m(x, y) for x, y in shape_pts]
    plate = {'kind': 'panel', 'nodes': list(range(len(shape_pts))),
             'thickness_mm': t_mm, 'G_GPa': G_GPa}
    geom = plate_geometry(nodes, plate)
    assert geom is not None
    idx, pts, area, B = geom
    G_Pa, t_m = plate_material(plate)
    K = plate_stiffness(area, B, G_Pa, t_m)
    return nodes, plate, idx, pts, area, B, K, G_Pa, t_m


def matvec(K, d):
    return [sum(K[i][j] * d[j] for j in range(len(d))) for i in range(len(K))]


def norm_inf(K):
    return max(max(abs(v) for v in row) for row in K)


# ── 1. patch tests ───────────────────────────────────────────────────────────

@pytest.mark.parametrize('name', sorted(SHAPES))
def test_rigid_body_motion_produces_no_shear_and_no_force(name):
    """Translation and rotation are strain-free for any shape. Judged
    relative to ||K|| -- see trap 1 in this module's docstring."""
    nodes, plate, idx, pts, area, B, K, G_Pa, t_m = build(SHAPES[name])
    kscale = norm_inf(K)
    for mode in ('tx', 'ty', 'rot'):
        d = []
        for (x, y) in pts:
            if mode == 'tx':
                d += [1.0, 0.0]
            elif mode == 'ty':
                d += [0.0, 1.0]
            else:
                d += [-y, x]                      # unit rigid rotation
        gamma = sum(B[i] * d[i] for i in range(len(B)))
        assert abs(gamma) < 1e-12, (name, mode, gamma)
        f = matvec(K, d)
        assert max(abs(v) for v in f) < 1e-12 * kscale, (name, mode)


@pytest.mark.parametrize('name', sorted(SHAPES))
def test_constant_shear_field_is_reproduced_exactly(name):
    """Impose u = k*y, v = 0 -- a pure shear field of magnitude k. The
    element must return gamma = k exactly, on every shape, which is what
    makes it valid for trapezoids and triangles and not only rectangles."""
    nodes, plate, idx, pts, area, B, K, G_Pa, t_m = build(SHAPES[name])
    k = 1e-3
    d = []
    for (x, y) in pts:
        d += [k * y, 0.0]
    gamma = sum(B[i] * d[i] for i in range(len(B)))
    assert gamma == pytest.approx(k, rel=1e-12), (name, gamma)
    q = G_Pa * t_m * gamma
    assert q == pytest.approx(G_Pa * t_m * k, rel=1e-12)


@pytest.mark.parametrize('name', sorted(SHAPES))
def test_corner_forces_self_equilibrate(name):
    """Whatever the panel does, it applies no net force or moment to the
    structure -- it only redistributes. Reference-free."""
    nodes, plate, idx, pts, area, B, K, G_Pa, t_m = build(SHAPES[name])
    d = []
    for (x, y) in pts:
        d += [1e-3 * y, 5e-4 * x]
    f = matvec(K, d)
    n = len(pts)
    scale = max(max(abs(v) for v in f), 1.0)
    sfx = sum(f[2 * i] for i in range(n))
    sfy = sum(f[2 * i + 1] for i in range(n))
    sm = sum(pts[i][0] * f[2 * i + 1] - pts[i][1] * f[2 * i] for i in range(n))
    assert abs(sfx) / scale < 1e-12
    assert abs(sfy) / scale < 1e-12
    assert abs(sm) / scale < 1e-12


# ── 2. invalid geometry is refused, not approximated ─────────────────────────

def test_degenerate_and_bowtie_panels_are_rejected():
    """A wrong-but-believable panel stiffness is worse than a panel the UI
    reports as invalid, so these must return None rather than a number."""
    square = [m(0, 0), m(2, 0), m(2, 2), m(0, 2)]
    # a valid quad, for contrast
    assert plate_node_loop(square, {'nodes': [0, 1, 2, 3]}) is not None
    # self-intersecting ("bowtie"): swap two corners
    assert plate_node_loop(square, {'nodes': [0, 1, 3, 2]}) is None
    # repeated node
    assert plate_node_loop(square, {'nodes': [0, 1, 1, 2]}) is None
    # wrong loop length
    assert plate_node_loop(square, {'nodes': [0, 1]}) is None
    assert plate_node_loop(square, {'nodes': [0, 1, 2, 3, 0]}) is None
    # out of range
    assert plate_node_loop(square, {'nodes': [0, 1, 2, 99]}) is None
    # zero area (three collinear points)
    line = [m(0, 0), m(1, 0), m(2, 0)]
    assert plate_node_loop(line, {'nodes': [0, 1, 2]}) is None


def test_node_loop_orientation_is_normalised():
    """Both windings of the same quad must give the same panel, so the sign
    of the reported shear flow depends on the geometry and not on the order
    the user happened to click the rods in."""
    square = [m(0, 0), m(2, 0), m(2, 2), m(0, 2)]
    a = plate_node_loop(square, {'nodes': [0, 1, 2, 3]})
    b = plate_node_loop(square, {'nodes': [3, 2, 1, 0]})
    assert a is not None and b is not None
    # same cyclic sequence, possibly rotated
    assert set(a) == set(b)
    doubled = a + a
    assert any(doubled[i:i + len(b)] == b for i in range(len(a)))


# ── 3. the shear cantilever, against the closed form ─────────────────────────

def shear_cantilever(EA_cm2, npan=6, depth=2.0, panel=1.0, V=50.0, t_mm=8.0,
                     G_GPa=80.0):
    """A column of square panels between two flanges, tip shear V (kN).
    Flanges and posts are pin bars; ALL transverse flexibility therefore
    comes from the panels. Returns (tip deflection m, closed form m)."""
    nodes, rods, plates = [], [], []
    for i in range(npan + 1):
        nodes.append(m(i * panel, 0.0))        # bottom flange node 2i
        nodes.append(m(i * panel, depth))      # top flange node 2i+1

    def bar(a, b):
        rods.append({'a': a, 'b': b, 'E': 200.0, 'A': EA_cm2})

    for i in range(npan):
        bar(2 * i, 2 * i + 2)
        bar(2 * i + 1, 2 * i + 3)
    for i in range(npan + 1):
        bar(2 * i, 2 * i + 1)
    for i in range(npan):
        plates.append({'kind': 'panel',
                       'nodes': [2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1],
                       'thickness_mm': t_mm, 'G_GPa': G_GPa})
    loads = [{'node': 2 * npan, 'fx': 0.0, 'fy': V / 2.0},
             {'node': 2 * npan + 1, 'fx': 0.0, 'fy': V / 2.0}]
    supports = [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'pin'}]
    res, err = analyze(nodes, rods, loads, supports, plates)
    assert err is None, err
    tip = (res['node_res'][2 * npan]['uy'] +
           res['node_res'][2 * npan + 1]['uy']) / 2.0 / 1000.0   # mm -> m
    exact = (V * 1e3) * (npan * panel) / (G_GPa * 1e9 * t_mm / 1000.0 * depth)
    return tip, exact


def test_shear_cantilever_converges_to_the_closed_form_as_flanges_stiffen():
    """delta = V*L/(G*t*d) assumes rigid flanges. With finite EA the error is
    the flanges stretching and must fall roughly an order of magnitude for
    each order of magnitude of EA -- see trap 2 in the module docstring.
    Asserting the RATE, not a bare tolerance, keeps this sensitive to a real
    element error instead of absorbing one."""
    errs = []
    for EA_cm2 in (1e5, 1e6, 1e7):
        tip, exact = shear_cantilever(EA_cm2)
        errs.append(abs(tip - exact) / exact)
    # Measured: 3.813e-3, 3.813e-4, 3.813e-5 -- exactly one decade of error
    # per decade of flange area, which is the signature of the flanges being
    # the ONLY remaining source of discrepancy. Assert that RATE, not just a
    # final tolerance, so a real element error cannot hide inside a loose
    # bound.
    assert errs[0] > errs[1] > errs[2], errs
    for a, b in zip(errs, errs[1:]):
        assert 5.0 < a / b < 20.0, errs
    assert errs[-1] < 1e-4, errs


def test_panel_shear_flow_equals_V_over_depth():
    """In a shear cantilever every panel carries q = V/d, exactly."""
    V, depth = 50.0, 2.0
    nodes, rods, plates = [], [], []
    npan, panel = 4, 1.0
    for i in range(npan + 1):
        nodes.append(m(i * panel, 0.0))
        nodes.append(m(i * panel, depth))
    for i in range(npan):
        rods.append({'a': 2*i, 'b': 2*i+2, 'E': 200.0, 'A': 1e5})
        rods.append({'a': 2*i+1, 'b': 2*i+3, 'E': 200.0, 'A': 1e5})
    for i in range(npan + 1):
        rods.append({'a': 2*i, 'b': 2*i+1, 'E': 200.0, 'A': 1e5})
    for i in range(npan):
        plates.append({'kind': 'panel', 'nodes': [2*i, 2*i+2, 2*i+3, 2*i+1],
                       'thickness_mm': 8.0, 'G_GPa': 80.0})
    res, err = analyze(nodes, rods,
                       [{'node': 2*npan, 'fx': 0.0, 'fy': V/2.0},
                        {'node': 2*npan+1, 'fx': 0.0, 'fy': V/2.0}],
                       [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'pin'}],
                       plates)
    assert err is None, err
    for pr in res['plate_res']:
        assert pr['valid']
        assert abs(pr['q']) == pytest.approx(V / depth, rel=1e-6)
        # tau = q / t, in MPa
        assert pr['tau_MPa'] == pytest.approx(pr['q'] * 1e3 / (pr['t_mm'] / 1000.0) / 1e6
                                              * (1 if pr['q'] >= 0 else 1), rel=1e-9)


# ── 4. integration with the rest of the solver ───────────────────────────────

def vierendeel(with_plate_t=None):
    """A one-bay rigid-jointed Vierendeel frame, optionally with a shear
    panel filling the bay."""
    nodes = [m(0, 0), m(3, 0), m(3, 2), m(0, 2)]
    rods = [{'a': a, 'b': b, 'E': 200.0, 'A': 60.0, 'I': 8000.0, 'conn': 'rigid'}
            for a, b in ((0, 1), (1, 2), (2, 3), (3, 0))]
    loads = [{'node': 2, 'fx': 40.0, 'fy': 0.0}]
    supports = [{'node': 0, 'type': 'fixed'}, {'node': 1, 'type': 'fixed'}]
    plates = []
    if with_plate_t is not None:
        plates.append({'kind': 'panel', 'nodes': [0, 1, 2, 3],
                       'thickness_mm': with_plate_t, 'G_GPa': 80.0})
    return nodes, rods, loads, supports, plates


def test_a_vanishing_plate_converges_to_the_bare_frame():
    """As t -> 0 the plated model must approach the unplated one. Strong and
    reference-free: it catches a sign error, a stray factor and a
    mis-assembled DOF index, none of which a single-value check would."""
    base, err = analyze(*vierendeel(None)[:4], vierendeel(None)[4])
    assert err is None
    ref = base['node_res'][2]['ux']
    prev = None
    for t in (1e-1, 1e-3, 1e-5):
        nodes, rods, loads, supports, plates = vierendeel(t)
        res, err = analyze(nodes, rods, loads, supports, plates)
        assert err is None, err
        d = abs(res['node_res'][2]['ux'] - ref)
        if prev is not None:
            assert d < prev, (t, d, prev)
        prev = d
    assert prev / abs(ref) < 1e-4


def test_a_thicker_plate_monotonically_stiffens_the_bay():
    """The whole point of the feature: more plate, less sway."""
    sway = []
    for t in (0.0, 2.0, 4.0, 8.0, 16.0):
        nodes, rods, loads, supports, plates = vierendeel(t if t else None)
        res, err = analyze(nodes, rods, loads, supports, plates)
        assert err is None, err
        sway.append(abs(res['node_res'][2]['ux']))
    for a, b in zip(sway, sway[1:]):
        assert b < a, sway
    assert sway[-1] < sway[0] / 2.0, sway


def test_joint_equilibrium_still_closes_with_a_panel_present():
    """THE integration check. A panel pushes corner forces into its nodes; if
    it is assembled into K but left out of compute_node_force_vectors, the
    rod forces alone no longer balance the load and this residual blows up.
    That omission is the single easiest silent error in this feature."""
    nodes, rods, loads, supports, plates = vierendeel(10.0)
    res, err = analyze(nodes, rods, loads, supports, plates)
    assert err is None, err
    vectors = res['node_vectors']
    assert any(v.get('kind') == 'plate' for vs in vectors.values() for v in vs), \
        'no plate contribution reached the node force vectors at all'

    # These are RIGID members, so the joint also carries their shear and end
    # moment, and only compute_node_design_actions reports all of it. Writing
    # this check against the axial-only vectors is what first exposed that
    # gap -- see that function's docstring.
    acts = compute_node_design_actions(nodes, rods, res['rod_res'], res['plate_res'])
    assert any(a['plates'] for a in acts.values()), 'no panel reached the joint actions'
    supported = {s['node'] for s in supports}
    load_at = {}
    for ld in loads:
        fx, fy = load_at.get(ld['node'], (0.0, 0.0))
        load_at[ld['node']] = (fx + ld['fx'], fy + ld['fy'])
    for ni in range(len(nodes)):
        if ni in supported:
            continue
        fx, fy = load_at.get(ni, (0.0, 0.0))
        # actions are y-UP, applied loads are y-DOWN
        assert abs(acts[ni]['Fx'] + fx) < 1e-9, (ni, acts[ni]['Fx'], fx)
        assert abs(acts[ni]['Fy'] - fy) < 1e-9, (ni, acts[ni]['Fy'], fy)
        assert abs(acts[ni]['M']) < 1e-9, (ni, acts[ni]['M'])


def test_panels_add_no_rotational_dof():
    """A membrane has no drilling DOF. A pin-only model with panels must
    still solve with zero rotation everywhere -- if a panel ever starts
    touching theta, this is the first thing that moves."""
    nodes = [m(0, 0), m(2, 0), m(2, 2), m(0, 2)]
    rods = [{'a': a, 'b': b, 'E': 200.0, 'A': 20.0}
            for a, b in ((0, 1), (1, 2), (2, 3), (3, 0))]
    plates = [{'kind': 'panel', 'nodes': [0, 1, 2, 3],
               'thickness_mm': 8.0, 'G_GPa': 80.0}]
    res, err = analyze(nodes, rods, [{'node': 2, 'fx': 25.0, 'fy': 0.0}],
                       [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'pin'}],
                       plates)
    assert err is None, err
    for nr in res['node_res']:
        assert nr['theta'] == 0.0
    # ...and the panel alone is what makes this pin-jointed square stable:
    # without it the same model is a mechanism.
    res2, err2 = analyze(nodes, rods, [{'node': 2, 'fx': 25.0, 'fy': 0.0}],
                         [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'pin'}])
    assert res2 is None and err2 is not None


def test_gusset_records_never_reach_the_stiffness_matrix():
    """P-1 gussets are annotations. Adding one must not change any result."""
    nodes, rods, loads, supports, _ = vierendeel(None)
    bare, err = analyze(nodes, rods, loads, supports)
    assert err is None
    gusset = [{'kind': 'gusset', 'node': 2, 'thickness_mm': 12.0,
               'Fy': 235.0, 'Fu': 360.0, 'Fexx': 480.0}]
    with_g, err = analyze(nodes, rods, loads, supports, gusset)
    assert err is None
    for a, b in zip(bare['node_res'], with_g['node_res']):
        assert a['ux'] == b['ux'] and a['uy'] == b['uy'] and a['theta'] == b['theta']
    for a, b in zip(bare['rod_res'], with_g['rod_res']):
        assert a['force'] == b['force'] and a['Ma'] == b['Ma']


def test_symmetric_frame_with_symmetric_panels_gives_symmetric_results():
    nodes = [m(0, 0), m(2, 0), m(4, 0), m(0, 2), m(2, 2), m(4, 2)]
    rods = [{'a': a, 'b': b, 'E': 200.0, 'A': 40.0, 'I': 8000.0, 'conn': 'rigid'}
            for a, b in ((0, 1), (1, 2), (3, 4), (4, 5), (0, 3), (1, 4), (2, 5))]
    plates = [{'kind': 'panel', 'nodes': [0, 1, 4, 3], 'thickness_mm': 6.0, 'G_GPa': 80.0},
              {'kind': 'panel', 'nodes': [1, 2, 5, 4], 'thickness_mm': 6.0, 'G_GPa': 80.0}]
    res, err = analyze(nodes, rods, [{'node': 4, 'fx': 0.0, 'fy': 30.0}],
                       [{'node': 0, 'type': 'pin'}, {'node': 2, 'type': 'rollerX'}],
                       plates)
    assert err is None, err
    # mirrored panels carry equal and opposite shear flow
    q0, q1 = res['plate_res'][0]['q'], res['plate_res'][1]['q']
    assert q0 == pytest.approx(-q1, rel=1e-9), (q0, q1)
    # ...and the two supports share the load
    assert res['reactions'][0]['ry'] == pytest.approx(res['reactions'][2]['ry'], rel=1e-9)


# ── 5. design checks (P-1 gusset, P-2 panel) ─────────────────────────────────

import cirsoc_301 as cirsoc
from apps.truss import truss_plates as tp


def test_shear_buckling_stress_matches_the_closed_form():
    """tau_cr = kv*pi^2*E / (12(1-nu^2)(b/t)^2), kv = 5.34 + 4(b/a)^2."""
    a, b, t = 3.0, 2.0, 8.0
    kv = 5.34 + 4.0 * (b / a) ** 2
    expected = (kv * math.pi ** 2 * 200000.0) / (12.0 * (1 - 0.3 ** 2)
                                                 * (b * 1000.0 / t) ** 2)
    assert tp.shear_buckling_stress(a, b, t) == pytest.approx(expected, rel=1e-12)
    # a square panel is the stiffest case for a given b; a long one tends to
    # kv -> 5.34, so tau_cr must fall as the panel gets longer
    long_panel = tp.shear_buckling_stress(20.0, b, t)
    square = tp.shear_buckling_stress(b, b, t)
    assert long_panel < square
    # halving the thickness quarters tau_cr
    assert tp.shear_buckling_stress(a, b, t / 2) == pytest.approx(
        tp.shear_buckling_stress(a, b, t) / 4.0, rel=1e-12)


def test_buckling_governs_a_thin_panel_and_yield_a_stocky_one():
    """The reason a panel result is never shown without its buckling check:
    on a thin plate buckling governs by an order of magnitude."""
    nodes, rods, loads, supports, plates = vierendeel(6.0)
    res, err = analyze(nodes, rods, loads, supports, plates)
    assert err is None
    thin = tp.panel_checks(plates[0], res['plate_res'][0])
    assert thin['buckling_governs']
    assert thin['util_buckling'] > 5 * thin['util_yield']

    # a very stocky panel (small bay, thick plate) is yield-governed instead
    stocky = tp.panel_checks({'kind': 'panel', 'thickness_mm': 40.0},
                             {'valid': True, 't_mm': 40.0, 'tau_MPa': 90.0,
                              'q': 3600.0, 'nodes': [0, 1, 2, 3],
                              'area_m2': 0.25, 'pts_m': [(0, 0), (0.5, 0),
                                                         (0.5, 0.5), (0, 0.5)]})
    assert not stocky['buckling_governs']
    assert stocky['governing'].startswith('shear stress')


def test_panel_weld_leg_respects_the_fabrication_bounds():
    nodes, rods, loads, supports, plates = vierendeel(8.0)
    res, _ = analyze(nodes, rods, loads, supports, plates)
    chk = tp.panel_checks(plates[0], res['plate_res'][0])
    # never below the Table J.2.4 minimum for the thicker part...
    assert chk['weld_leg_mm'] >= cirsoc.min_fillet_leg(chk['t_mm']) - 1e-12
    # ...and the J.2.2(b) maximum is reported so an infeasible weld is visible
    assert chk['weld_leg_max_mm'] == pytest.approx(cirsoc.max_fillet_leg(chk['t_mm']))
    # the strength requirement alone must actually carry the shear flow
    cap = cirsoc.weld_strength_per_mm(chk['weld_leg_req_mm'], chk['Fexx'], 2)
    assert cap >= abs(chk['q_kN_per_m']) - 1e-6


def test_panel_check_reports_invalid_panels_rather_than_guessing():
    assert tp.panel_checks({'kind': 'panel'}, None)['valid'] is False
    assert tp.panel_checks({'kind': 'panel'},
                           {'valid': False, 'reason': 'bowtie'})['valid'] is False


def test_gusset_resultant_equals_the_applied_load_at_that_joint():
    """The gusset is checked against the joint's actual resultant, so at a
    loaded free joint that resultant must be the applied load itself."""
    nodes, rods, loads, supports, plates = vierendeel(None)
    plates = [{'kind': 'gusset', 'node': 2, 'thickness_mm': 10.0}]
    res, err = analyze(nodes, rods, loads, supports, plates)
    assert err is None
    chk = tp.check_all(nodes, rods, plates, res)[0]
    assert chk['resultant_kN'] == pytest.approx(40.0, rel=1e-9)
    assert chk['members'], 'no members reported at the gusset'
    assert any(m['conn'] == 'rigid' for m in chk['members'])
    # Two caveats must be stated. The rigid-joint one (the joint also carries
    # member end moments), and -- since block shear and gusset buckling ARE
    # now checked -- the provenance one: their resistance factors are AISC's
    # and have not been read off the CIRSOC table, unlike every other factor
    # in this app. A number that looks like every other CIRSOC result but is
    # not sourced the same way has to say so.
    joined = ' '.join(chk['notes'])
    assert 'end moments' in joined
    assert 'NOT been read off the CIRSOC table' in joined
    assert 'phi=0.75' in joined and 'phi_c=0.90' in joined


def test_gusset_unit_boundary_kN_m_GPa_vs_N_mm_MPa():
    """The single most likely place for a silent factor of 1000: the tab works
    in kN/m/GPa, cirsoc_301 works in N/mm/MPa. Recompute one member's plate
    stress and weld leg by hand, in N and mm, and require the module to agree.
    """
    nodes, rods, loads, supports, _ = vierendeel(None)
    plates = [{'kind': 'gusset', 'node': 2, 'thickness_mm': 10.0,
               'Fy': 235.0, 'Fexx': 480.0, 'weld_lines': 2,
               'landing_m': 0.30}]
    res, _ = analyze(nodes, rods, loads, supports, plates)
    chk = tp.check_all(nodes, rods, plates, res)[0]
    mem = chk['members'][0]

    # by hand, in N and mm
    P_N = mem['P_kN'] * 1e3
    w_mm = 2.0 * 300.0 * math.tan(math.radians(30.0))      # Whitmore, mm
    assert mem['whitmore_mm'] == pytest.approx(w_mm, rel=1e-12)
    sigma = P_N / (w_mm * 10.0)                            # N / (mm * mm)
    assert mem['sigma_MPa'] == pytest.approx(sigma, rel=1e-12)
    assert mem['util'] == pytest.approx(
        cirsoc.stress_check(sigma, 0.0, 235.0).util, rel=1e-12)
    q = P_N / 300.0                                        # N per mm of landing
    assert mem['weld_leg_req_mm'] == pytest.approx(
        cirsoc.leg_for_shear_flow(q, 480.0, 2), rel=1e-12)


def test_check_all_skips_what_it_cannot_check():
    nodes, rods, loads, supports, _ = vierendeel(None)
    plates = [{'kind': 'gusset', 'node': 99, 'thickness_mm': 10.0},   # bad node
              {'kind': 'panel', 'nodes': [0, 1, 3, 2],                # bowtie
               'thickness_mm': 8.0, 'G_GPa': 80.0}]
    res, err = analyze(nodes, rods, loads, supports, plates)
    assert err is None
    out = tp.check_all(nodes, rods, plates, res)
    assert out[0] is None                       # node out of range: skipped
    assert out[1] is not None and out[1]['valid'] is False
    assert tp.check_all(nodes, rods, plates, None) == [None, None]


# ── 6. block shear and gusset compression buckling ───────────────────────────

def test_block_shear_matches_the_closed_form_and_picks_the_governing_term():
    """AISC J4.3: Rn = 0.6*Fu*Anv + Ubs*Fu*Ant, capped by 0.6*Fy*Agv + Ubs*Fu*Ant.
    The cap is not a maximum on the whole expression -- it replaces only the
    shear term -- so a case either side of the switch is worth pinning."""
    Fy, Fu = 235.0, 360.0
    # net area small enough that shear RUPTURE governs
    r1 = cirsoc.block_shear_strength(Agv=2000.0, Anv=1200.0, Ant=500.0, Fy=Fy, Fu=Fu)
    assert r1.Rn == pytest.approx(0.6 * Fu * 1200.0 + Fu * 500.0, rel=1e-12)
    assert 'rupture' in r1.governing
    # net area close to gross -> shear YIELDING on the gross area governs
    r2 = cirsoc.block_shear_strength(Agv=2000.0, Anv=1950.0, Ant=500.0, Fy=Fy, Fu=Fu)
    assert r2.Rn == pytest.approx(0.6 * Fy * 2000.0 + Fu * 500.0, rel=1e-12)
    assert 'yielding' in r2.governing
    # the design value carries the factor, and utilisation follows from it
    assert r2.Rd == pytest.approx(0.75 * r2.Rn, rel=1e-12)
    r3 = cirsoc.block_shear_strength(2000.0, 1950.0, 500.0, Fy, Fu, required=r2.Rd)
    assert r3.util == pytest.approx(1.0, rel=1e-9)


def _solved(nodes, rods, loads, supports, plates=None):
    res, err = analyze(nodes, rods, loads, supports, plates)
    assert err is None, err
    return res


def test_a_bolted_gusset_has_less_block_shear_capacity_than_a_welded_one():
    """Holes remove net area and the bolted block is smaller, so this
    ordering is the sanity check that the two geometries are not swapped."""
    nodes, rods, loads, supports, _ = vierendeel(None)
    common = {'kind': 'gusset', 'node': 2, 'thickness_mm': 10.0,
              'Fy': 235.0, 'Fu': 360.0, 'Fexx': 480.0}
    welded = tp.check_all(nodes, rods, [dict(common)],
                          _solved(nodes, rods, loads, supports))[0]
    bolted_plate = dict(common, conn_type='bolted', bolt_rows=3, bolt_cols=2,
                        bolt_d_mm=16.0, pitch_mm=60.0, gauge_mm=60.0, end_mm=40.0)
    bolted = tp.check_all(nodes, rods, [bolted_plate],
                          _solved(nodes, rods, loads, supports))[0]
    wr = welded['members'][0]['block_shear']['Rd_kN']
    br = bolted['members'][0]['block_shear']['Rd_kN']
    assert br < wr, (br, wr)
    assert 'welded' in welded['detail_note']
    assert 'bolted' in bolted['detail_note'] and 'M16' in bolted['detail_note']


def test_net_width_deducts_one_hole_allowance_per_hole():
    assert tp.cirsoc.net_width(200.0, 0, 16.0) == pytest.approx(200.0)
    assert tp.cirsoc.net_width(200.0, 2, 16.0) == pytest.approx(
        200.0 - 2 * (16.0 + cirsoc.HOLE_ALLOWANCE_MM))
    # never negative, however many holes are claimed
    assert tp.cirsoc.net_width(20.0, 5, 16.0) == 0.0


def test_gusset_buckling_only_applies_to_a_member_in_compression():
    """A tie cannot buckle the plate. Returning util 0 with applies=False is
    the honest answer; returning a number would invite it to be read as a
    check that passed."""
    tens = tp.gusset_buckling_check(+50.0, 300.0, 10.0, 300.0, 235.0)
    assert tens['applies'] is False and tens['util'] == 0.0
    comp = tp.gusset_buckling_check(-50.0, 300.0, 10.0, 300.0, 235.0)
    assert comp['applies'] is True and comp['util'] > 0.0


def test_gusset_buckling_follows_the_column_curve():
    """Thornton: the Whitmore width as a column of thickness t, r = t/sqrt(12).
    A thinner plate is more slender and must have a lower critical stress."""
    thick = tp.gusset_buckling_check(-50.0, 300.0, 20.0, 300.0, 235.0)
    thin = tp.gusset_buckling_check(-50.0, 300.0, 6.0, 300.0, 235.0)
    assert thin['slenderness'] > thick['slenderness']
    assert thin['Fcr_MPa'] < thick['Fcr_MPa']
    assert thin['util'] > thick['util']
    # slenderness is K*L/r with r = t/sqrt(12)
    assert thick['slenderness'] == pytest.approx(
        tp.GUSSET_K * 300.0 / (20.0 / math.sqrt(12.0)), rel=1e-12)
    # ...and Fcr must equal the code layer's own column curve at that slenderness
    Fcr, _Fe, _g = cirsoc.compression_critical_stress(thick['slenderness'], 235.0)
    assert thick['Fcr_MPa'] == pytest.approx(Fcr, rel=1e-12)


def test_compression_curve_branches_meet_at_the_transition():
    """AISC E3's two branches are continuous to within their own rounding
    (4.71 and 0.877 are rounded constants), so a small step is expected and a
    large one means the branch condition is wrong."""
    Fy = 235.0
    lam = 4.71 * math.sqrt(cirsoc.E_STEEL / Fy)
    lo, _, g_lo = cirsoc.compression_critical_stress(lam - 1e-6, Fy)
    hi, _, g_hi = cirsoc.compression_critical_stress(lam + 1e-6, Fy)
    assert 'inelastic' in g_lo and 'elastic' in g_hi
    assert abs(lo - hi) / lo < 1e-3, (lo, hi)
    # and the curve is monotonically decreasing in slenderness
    prev = float('inf')
    for s_ in (10, 40, 80, 120, 160, 200):
        Fcr, _, _ = cirsoc.compression_critical_stress(s_, Fy)
        assert Fcr < prev
        prev = Fcr
