"""Distributed loads applied ALONG a member (apps/stereo/stereo_member_loads.py).

Every sign convention in that module is checked against a closed form
rather than against itself, and in BOTH local bending planes, because a
3D frame element's x-z plane carries the opposite sign to its x-y plane
and there is no way to catch a swapped sign by reasoning about the code.

The four closed forms used throughout:

    simply supported UDL   |V| = wL/2 at the ends, 0 at midspan
                           |M| = 0 at the ends,   wL^2/8 at midspan
    cantilever UDL         |V| = wL at the root,  0 at the tip
                           |M| = wL^2/2 at the root, 0 at the tip
    fixed-fixed UDL        |M| = wL^2/12 at the ends, wL^2/24 at midspan
    axially loaded column  N = -wL at the base, 0 at the free top
"""
import math

import pytest

from apps.stereo import stereo_math as sm
from apps.stereo import stereo_member_loads as ml

E, A, I, J = 200.0, 100.0, 5000.0, 10000.0
L = 6.0
W = 10.0          # kN/m


def _beam(conn='rigid', nodes=None):
    nodes = nodes or [(0.0, 0.0, 0.0), (L, 0.0, 0.0)]
    return nodes, [{'a': 0, 'b': 1, 'conn': conn, 'E': E, 'A': A, 'I': I, 'J': J}]


SIMPLY_SUPPORTED = [{'node': 0, 'dofs': {'ux': True, 'uy': True, 'uz': True, 'rx': True}},
                    {'node': 1, 'dofs': {'ux': True, 'uy': True, 'uz': True, 'rx': True}}]
CANTILEVER = [{'node': 0, 'type': 'fixed'}]

# the load direction that resolves purely into each of the member's own
# local bending planes, for a member lying along global x
Y_PLANE = (0.0, -1.0, 0.0)
Z_PLANE = (0.0, 0.0, -1.0)


def _run(supports, direction, conn='rigid', spread=ml.ALONG, w=W):
    nodes, members = _beam(conn)
    res, err = sm.analyze(nodes, members, [], supports,
                          member_loads=[{'member': 0, 'w': w, 'dir': direction,
                                         'spread': spread}])
    assert err is None, err
    return res, res['member_res'][0]


def _shear(mres, t):
    _N, Vy, Vz, _My, _Mz = ml.member_diagram(mres, t)
    return math.hypot(Vy, Vz)


def _moment(mres, t):
    _N, _Vy, _Vz, My, Mz = ml.member_diagram(mres, t)
    return math.hypot(My, Mz)


# ── the headline claim: nodal loads give a CONSTANT shear ──────────────────

def test_without_a_member_load_the_shear_along_a_rod_does_not_vary():
    """The whole reason this feature exists. Nothing acts on a member
    between its ends under nodal loads, so nothing can change the force
    transmitted across a cut -- and a "shear along the rod" gradient drawn
    over that would be an invention, not a measurement."""
    nodes, members = _beam('rigid')
    res, err = sm.analyze(nodes, members, [{'node': 1, 'fz': -25.0}], CANTILEVER)
    assert err is None, err
    mres = res['member_res'][0]
    values = [_shear(mres, k / 8.0) for k in range(9)]
    assert max(values) == pytest.approx(min(values), abs=1e-9)
    assert not ml.varies_along_the_rod(mres)


def test_with_a_member_load_the_shear_falls_linearly_and_the_moment_bows():
    res, mres = _run(SIMPLY_SUPPORTED, Z_PLANE)
    assert ml.varies_along_the_rod(mres)
    shears = [_shear(mres, k / 8.0) for k in range(9)]
    assert max(shears) - min(shears) > 1.0
    # linear in x: equal steps in the SIGNED value
    signed = [ml.member_diagram(mres, k / 8.0)[2] for k in range(9)]
    steps = [b - a for a, b in zip(signed, signed[1:])]
    for s in steps:
        assert s == pytest.approx(steps[0], abs=1e-9)


# ── simply supported, both bending planes ──────────────────────────────────

@pytest.mark.parametrize('direction', [Y_PLANE, Z_PLANE])
def test_a_simply_supported_member_load_gives_the_textbook_diagram(direction):
    _res, mres = _run(SIMPLY_SUPPORTED, direction)
    assert _shear(mres, 0.0) == pytest.approx(W * L / 2.0, abs=1e-6)
    assert _shear(mres, 0.5) == pytest.approx(0.0, abs=1e-6)
    assert _shear(mres, 1.0) == pytest.approx(W * L / 2.0, abs=1e-6)
    assert _moment(mres, 0.0) == pytest.approx(0.0, abs=1e-6)
    assert _moment(mres, 0.5) == pytest.approx(W * L * L / 8.0, abs=1e-6)
    assert _moment(mres, 1.0) == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize('direction', [Y_PLANE, Z_PLANE])
def test_a_cantilever_member_load_gives_the_textbook_diagram(direction):
    _res, mres = _run(CANTILEVER, direction)
    assert _shear(mres, 0.0) == pytest.approx(W * L, abs=1e-6)
    assert _shear(mres, 1.0) == pytest.approx(0.0, abs=1e-6)
    assert _moment(mres, 0.0) == pytest.approx(W * L * L / 2.0, abs=1e-6)
    assert _moment(mres, 0.5) == pytest.approx(W * (L / 2.0) ** 2 / 2.0, abs=1e-6)
    assert _moment(mres, 1.0) == pytest.approx(0.0, abs=1e-6)


def test_a_fixed_fixed_member_load_gives_wl2_over_12_and_24():
    """The case that separates a correct fixed-end vector from one that is
    merely half-and-half: the end moments must appear, and the midspan
    moment must be HALF the end moment and of the opposite sign."""
    nodes = [(0.0, 0.0, 0.0), (L / 2.0, 0.0, 0.0), (L, 0.0, 0.0)]
    members = [{'a': 0, 'b': 1, 'conn': 'rigid', 'E': E, 'A': A, 'I': I, 'J': J},
               {'a': 1, 'b': 2, 'conn': 'rigid', 'E': E, 'A': A, 'I': I, 'J': J}]
    loads = [{'member': i, 'w': W, 'dir': Z_PLANE, 'spread': ml.ALONG} for i in (0, 1)]
    res, err = sm.analyze(nodes, members, [], [{'node': 0, 'type': 'fixed'},
                                               {'node': 2, 'type': 'fixed'}],
                          member_loads=loads)
    assert err is None, err
    left, right = res['member_res']
    end = ml.member_diagram(left, 0.0)[3]
    mid = ml.member_diagram(left, 1.0)[3]
    assert end == pytest.approx(-W * L * L / 12.0, abs=1e-6)
    assert mid == pytest.approx(+W * L * L / 24.0, abs=1e-6)
    assert ml.member_diagram(right, 1.0)[3] == pytest.approx(end, abs=1e-6)


def test_an_axial_member_load_varies_the_axial_force_down_a_column():
    nodes = [(0.0, 0.0, 0.0), (0.0, 0.0, L)]
    members = [{'a': 0, 'b': 1, 'conn': 'rigid', 'E': E, 'A': A, 'I': I, 'J': J}]
    res, err = sm.analyze(nodes, members, [], [{'node': 0, 'type': 'fixed'}],
                          member_loads=[{'member': 0, 'w': W, 'dir': (0, 0, -1),
                                         'spread': ml.ALONG}])
    assert err is None, err
    mres = res['member_res'][0]
    assert ml.member_diagram(mres, 0.0)[0] == pytest.approx(-W * L, abs=1e-6)
    assert ml.member_diagram(mres, 0.5)[0] == pytest.approx(-W * L / 2.0, abs=1e-6)
    assert ml.member_diagram(mres, 1.0)[0] == pytest.approx(0.0, abs=1e-6)


# ── the pin case: a bar bends as a simply supported span, and only itself ──

def test_a_pin_member_bends_as_a_simply_supported_span():
    """Exact for a ball-jointed bar: its ends cannot carry moment, so its
    own bending is the wx(L-x)/2 parabola whatever the rest of the
    structure does."""
    nodes, members = _beam('pin')
    w_local = ml.local_intensity(nodes, members[0],
                                 {'w': W, 'dir': Z_PLANE, 'spread': ml.ALONG})[:3]
    mres = {'conn': 'pin', 'length_m': L, 'N': 0.0, 'w_local': w_local}
    assert _moment(mres, 0.0) == pytest.approx(0.0, abs=1e-9)
    assert _moment(mres, 0.5) == pytest.approx(W * L * L / 8.0, abs=1e-9)
    assert _moment(mres, 1.0) == pytest.approx(0.0, abs=1e-9)
    assert _shear(mres, 0.0) == pytest.approx(W * L / 2.0, abs=1e-9)
    assert _shear(mres, 0.5) == pytest.approx(0.0, abs=1e-9)


def test_a_pin_member_contributes_no_moment_to_its_joints():
    """A ball joint transmits no moment, so the member's own bending must
    NOT reach the global solve -- the equivalent nodal load is the plain
    half-and-half split self_weight_loads has always used. Getting this
    wrong would stiffen a pin-jointed truss with moments its joints
    cannot carry."""
    nodes, members = _beam('pin')
    eq = ml.equivalent_nodal_loads(nodes, members,
                                   [{'member': 0, 'w': W, 'dir': Z_PLANE,
                                     'spread': ml.ALONG}])
    assert len(eq) == 2
    for entry in eq:
        assert entry['fz'] == pytest.approx(-W * L / 2.0, abs=1e-9)
        assert entry['mx'] == pytest.approx(0.0, abs=1e-12)
        assert entry['my'] == pytest.approx(0.0, abs=1e-12)
        assert entry['mz'] == pytest.approx(0.0, abs=1e-12)


def test_a_rigid_member_does_contribute_fixed_end_moments():
    nodes, members = _beam('rigid')
    eq = ml.equivalent_nodal_loads(nodes, members,
                                   [{'member': 0, 'w': W, 'dir': Z_PLANE,
                                     'spread': ml.ALONG}])
    magnitudes = [math.sqrt(e['mx'] ** 2 + e['my'] ** 2 + e['mz'] ** 2) for e in eq]
    for mag in magnitudes:
        assert mag == pytest.approx(W * L * L / 12.0, abs=1e-9)


# ── the two spreads ────────────────────────────────────────────────────────

def test_along_and_projected_differ_by_exactly_the_tilt():
    """A snow load is quoted per PLAN metre: a sloping purlin picks up what
    falls on its plan length, not on its true length. On a 45-degree member
    that is a factor of sqrt(2), and getting it backwards overloads every
    sloping member on the roof."""
    nodes = [(0.0, 0.0, 0.0), (L, 0.0, L)]
    members = [{'a': 0, 'b': 1, 'conn': 'pin', 'E': E, 'A': A}]
    def total(spread):
        eq = ml.equivalent_nodal_loads(nodes, members,
                                       [{'member': 0, 'w': W, 'dir': (0, 0, -1),
                                         'spread': spread}])
        return -sum(e['fz'] for e in eq)
    assert total(ml.ALONG) == pytest.approx(W * math.hypot(L, L), abs=1e-9)
    assert total(ml.PROJECTED) == pytest.approx(W * L, abs=1e-9)


def test_a_projected_load_on_a_member_parallel_to_it_is_zero():
    """A column collects no snow. The projected length of a member running
    straight along the load direction is zero, and the intensity with it."""
    nodes = [(0.0, 0.0, 0.0), (0.0, 0.0, L)]
    members = [{'a': 0, 'b': 1, 'conn': 'pin', 'E': E, 'A': A}]
    wx, wy, wz, _L = ml.local_intensity(nodes, members[0],
                                        {'w': W, 'dir': (0, 0, -1),
                                         'spread': ml.PROJECTED})
    assert (wx, wy, wz) == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    # ... whereas ALONG is its own self weight, and is not zero
    wx, _wy, _wz, _L = ml.local_intensity(nodes, members[0],
                                          {'w': W, 'dir': (0, 0, -1),
                                           'spread': ml.ALONG})
    assert wx == pytest.approx(-W, abs=1e-9)


# ── equilibrium, which no amount of correct-looking diagrams guarantees ────

@pytest.mark.parametrize('conn', ['pin', 'rigid'])
def test_the_reactions_carry_exactly_the_load_that_was_applied(conn):
    """The one check that catches a fixed-end vector applied with the wrong
    SIGN: the diagrams can look entirely plausible while the structure is
    being pulled up instead of pushed down."""
    # Genuinely three-dimensional: a planar assembly of PINNED bars has no
    # out-of-plane stiffness at all and is a mechanism before the load is
    # even applied, which would fail this test for a reason that has
    # nothing to do with member loads.
    nodes = [(0.0, 0.0, 0.0), (L / 2.0, 0.0, 0.0), (L, 0.0, 0.0),
             (L / 2.0, -2.0, -2.0), (L / 2.0, 2.0, -2.0)]
    members = [{'a': 0, 'b': 1, 'conn': conn, 'E': E, 'A': A, 'I': I, 'J': J},
               {'a': 1, 'b': 2, 'conn': conn, 'E': E, 'A': A, 'I': I, 'J': J}]
    for far in (3, 4):
        for near in (0, 1, 2):
            members.append({'a': near, 'b': far, 'conn': conn,
                            'E': E, 'A': A, 'I': I, 'J': J})
    supports = [{'node': i, 'type': 'pin'} for i in (0, 2, 3, 4)]
    loads = [{'member': i, 'w': W, 'dir': (0, 0, -1), 'spread': ml.ALONG}
             for i in (0, 1)]
    res, err = sm.analyze(nodes, members, [], supports, member_loads=loads)
    assert err is None, err
    assert sum(r['Fz'] for r in res['reactions'].values()) == pytest.approx(W * L, abs=1e-6)


def test_two_loads_on_one_member_add_instead_of_replacing_each_other():
    nodes, members = _beam('rigid')
    both = [{'member': 0, 'w': W, 'dir': Z_PLANE, 'spread': ml.ALONG},
            {'member': 0, 'w': W / 2.0, 'dir': Z_PLANE, 'spread': ml.ALONG}]
    res, err = sm.analyze(nodes, members, [], SIMPLY_SUPPORTED, member_loads=both)
    assert err is None, err
    mres = res['member_res'][0]
    assert _moment(mres, 0.5) == pytest.approx(1.5 * W * L * L / 8.0, abs=1e-6)


def test_a_member_load_with_no_direction_is_refused():
    nodes, members = _beam('rigid')
    with pytest.raises(ValueError):
        ml.local_intensity(nodes, members[0], {'w': W, 'dir': (0.0, 0.0, 0.0)})


def test_an_unloaded_model_is_untouched_by_the_new_parameter():
    """Every existing caller passes no member_loads, and must get the
    identical answer it got before this feature existed."""
    nodes, members = _beam('rigid')
    a, ea = sm.analyze(nodes, members, [{'node': 1, 'fz': -25.0}], CANTILEVER)
    b, eb = sm.analyze(nodes, members, [{'node': 1, 'fz': -25.0}], CANTILEVER,
                       member_loads=[])
    assert ea is None and eb is None
    assert a['member_res'][0]['N'] == pytest.approx(b['member_res'][0]['N'])
    assert a['node_res'][1]['uz'] == pytest.approx(b['node_res'][1]['uz'])


def test_diagram_extremes_finds_the_midspan_peak():
    _res, mres = _run(SIMPLY_SUPPORTED, Z_PLANE)
    worst_v, worst_m = ml.diagram_extremes(mres)
    assert worst_v == pytest.approx(W * L / 2.0, abs=1e-6)
    assert worst_m == pytest.approx(W * L * L / 8.0, abs=1e-3)
