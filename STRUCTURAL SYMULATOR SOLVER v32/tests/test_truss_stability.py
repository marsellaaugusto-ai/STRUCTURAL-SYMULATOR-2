"""Indeterminacy and mechanisms of the Truss tab (apps/truss/truss_stability).

Every expected value is a textbook one, worked by hand: Maxwell's count for
pin-jointed trusses, the classic degrees of the portal frames, and the
standard "enough rods in the wrong place" counter-example.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import PX_PER_M
from apps.truss import truss_stability as ts
from apps.truss.truss_math import analyze


def P(x, y):
    """A point given in metres, in the tab's pixel units."""
    return (x * PX_PER_M, y * PX_PER_M)


def rod(a, b, conn='pin'):
    return {'a': a, 'b': b, 'E': 200.0, 'A': 10.0, 'I': 8000.0,
            'conn': conn, 'udl': 0.0, 'point_loads': []}


def warren():
    """Two panels: bottom 0-1-2, top 3-4. m = 7, j = 5."""
    nodes = [P(0, 0), P(2, 0), P(4, 0), P(1, -1), P(3, -1)]
    rods = [rod(0, 1), rod(1, 2), rod(3, 4),
            rod(0, 3), rod(3, 1), rod(1, 4), rod(4, 2)]
    return nodes, rods


def test_warren_on_a_pin_and_a_roller_is_determinate():
    nodes, rods = warren()
    r = ts.check(nodes, rods, [{'node': 0, 'type': 'pin'},
                               {'node': 2, 'type': 'rollerX'}])
    assert (r['count'], r['mechanisms'], r['degree']) == (0, 0, 0)
    assert r['verdict'] == 'determinate'
    assert 'm + r − 2j = 7 + 3 − 2×5 = 0' in r['text']


def test_warren_on_two_pins_is_indeterminate_to_degree_one():
    nodes, rods = warren()
    r = ts.check(nodes, rods, [{'node': 0, 'type': 'pin'},
                               {'node': 2, 'type': 'pin'}])
    assert (r['degree'], r['verdict']) == (1, 'indeterminate')


def test_a_fixed_support_on_pinned_rods_acts_as_a_pin():
    nodes, rods = warren()
    r = ts.check(nodes, rods, [{'node': 0, 'type': 'fixed'},
                               {'node': 2, 'type': 'fixed'}])
    assert (r['degree'], r['mechanisms']) == (1, 0)


def test_a_missing_diagonal_is_a_mechanism_that_folds_its_panel():
    nodes, rods = warren()
    del rods[4]                           # the diagonal 3-1
    sup = [{'node': 0, 'type': 'pin'}, {'node': 2, 'type': 'rollerX'}]
    r = ts.check(nodes, rods, sup)
    assert (r['count'], r['mechanisms'], r['verdict']) == (-1, 1, 'mechanism')
    assert 'too few' in r['text']
    mm = ts.mechanism_mode(nodes, rods, sup)
    assert mm['kind'] == 'internal'
    assert 3 in mm['moving']              # the top joint of the opened panel
    assert ts.mechanism_mode(*warren(), sup) is None


def test_enough_rods_in_the_wrong_place_is_still_a_mechanism():
    """Two square panels: both diagonals in the left one, none in the right.
    m + r - 2j = 9 + 3 - 12 = 0, yet the right panel folds and the left one
    is redundant -- the case the count alone gets wrong."""
    nodes = [P(0, 0), P(1, 0), P(2, 0), P(0, -1), P(1, -1), P(2, -1)]
    rods = [rod(0, 1), rod(1, 2), rod(3, 4), rod(4, 5),
            rod(0, 3), rod(1, 4), rod(2, 5), rod(0, 4), rod(3, 1)]
    sup = [{'node': 0, 'type': 'pin'}, {'node': 2, 'type': 'rollerX'}]
    r = ts.check(nodes, rods, sup)
    assert r['count'] == 0
    assert (r['mechanisms'], r['degree']) == (1, 1)
    assert 'looks sufficient' in r['text']
    mm = ts.mechanism_mode(nodes, rods, sup)
    assert mm['kind'] == 'internal'
    assert set(mm['moving']) & {2, 5}


def test_one_pin_lets_the_whole_truss_turn():
    nodes, rods = warren()
    mm = ts.mechanism_mode(nodes, rods, [{'node': 0, 'type': 'pin'}])
    assert mm['kind'] == 'turn'


def test_two_rollers_let_it_slide_sideways():
    nodes, rods = warren()
    mm = ts.mechanism_mode(nodes, rods, [{'node': 0, 'type': 'rollerX'},
                                         {'node': 2, 'type': 'rollerX'}])
    assert mm['kind'] == 'slide_x'
    assert 'sliding sideways' in mm['text']


def test_a_node_that_belongs_to_no_rod_is_named():
    nodes, rods = warren()
    nodes.append(P(6, -3))
    sup = [{'node': 0, 'type': 'pin'}, {'node': 2, 'type': 'rollerX'}]
    assert ts.check(nodes, rods, sup)['mechanisms'] == 2
    mm = ts.mechanism_mode(nodes, rods, sup)
    assert mm['kind'] == 'loose' and mm['loose'] == [5]
    assert 'Node 5 is connected to no rod' in mm['text']


@pytest.mark.parametrize('support, degree', [('fixed', 3), ('pin', 1)])
def test_portal_frames_have_their_textbook_degrees(support, degree):
    nodes = [P(0, 0), P(0, -3), P(4, -3), P(4, 0)]
    rods = [rod(0, 1, 'rigid'), rod(1, 2, 'rigid'), rod(2, 3, 'rigid')]
    r = ts.check(nodes, rods, [{'node': 0, 'type': support},
                               {'node': 3, 'type': support}])
    assert (r['mechanisms'], r['degree']) == (0, degree)
    assert 'deformations + r − DOF' in r['text']


@pytest.mark.parametrize('frame', [False, True])
def test_the_stiffness_is_the_solvers_own(frame):
    """Solve K u = F with this module's K and compare with analyze()."""
    if frame:
        nodes = [P(0, 0), P(0, -3), P(4, -3), P(4, 0)]
        rods = [rod(0, 1, 'rigid'), rod(1, 2, 'rigid'), rod(2, 3, 'rigid')]
        sup = [{'node': 0, 'type': 'fixed'}, {'node': 3, 'type': 'pin'}]
        loads = [{'node': 1, 'fx': 10.0, 'fy': 20.0}]
    else:
        nodes, rods = warren()
        sup = [{'node': 0, 'type': 'pin'}, {'node': 2, 'type': 'rollerX'}]
        loads = [{'node': 3, 'fx': 5.0, 'fy': 30.0}, {'node': 4, 'fx': 0.0, 'fy': 30.0}]
    res, err = analyze(nodes, rods, loads, sup)
    assert err is None
    K, dof_of, fixed, _ = ts.assemble(nodes, rods, sup)
    F = np.zeros(K.shape[0])
    for ld in loads:
        F[dof_of[ld['node']][0]] += ld['fx'] * 1e3
        F[dof_of[ld['node']][1]] += ld['fy'] * 1e3
    free = [i for i in range(K.shape[0]) if i not in set(fixed)]
    u = np.zeros(K.shape[0])
    u[free] = np.linalg.solve(K[np.ix_(free, free)], F[free])
    for i, nr in enumerate(res['node_res']):
        assert u[dof_of[i][0]] * 1000 == pytest.approx(nr['ux'], rel=1e-9, abs=1e-12)
        assert u[dof_of[i][1]] * 1000 == pytest.approx(nr['uy'], rel=1e-9, abs=1e-12)
