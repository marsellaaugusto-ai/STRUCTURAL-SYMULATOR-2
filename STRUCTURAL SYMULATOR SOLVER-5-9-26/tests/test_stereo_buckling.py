"""Buckling, as a demonstration: the load factor and shape the structure
buckles at, and the second-order load-deflection curve. Held to Euler."""
import math

import pytest

from apps.stereo import stereo_buckling as sb
from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_math as sm

E, A, I, L = 200.0, 20.0, 400.0, 4.0
EULER_kN = math.pi ** 2 * E * 1e9 * I * 1e-8 / L ** 2 / 1e3


def _column(conn, P=100.0, top=('ux', 'uy'), base=('ux', 'uy', 'uz')):
    nodes = [(0.0, 0.0, 0.0), (0.0, 0.0, L)]
    members = [{'a': 0, 'b': 1, 'conn': conn, 'E': E, 'A': A, 'I': I,
                'J': 2 * I, 'r_gyr': math.sqrt(I / A)}]
    sup = [{'node': 0, 'dofs': {d: True for d in base}},
           {'node': 1, 'dofs': {d: True for d in top}}]
    return nodes, members, [{'node': 1, 'fz': -P}], sup


@pytest.mark.parametrize('conn', ['pin', 'rigid'])
def test_a_pinned_column_buckles_at_its_euler_load(conn):
    # a rigid rod also has to be held from spinning about its own axis
    base = ('ux', 'uy', 'uz') + (('rz',) if conn == 'rigid' else ())
    n, m, loads, sup = _column(conn, base=base)
    got = sb.buckling(n, m, loads, sup)
    assert got['factors'][0] == pytest.approx(EULER_kN / 100.0, rel=0.01)
    # the shape is the column bowing out at mid-height, its ends held
    mode = got['modes'][0]
    assert mode['peak'] == ('mid', 0)
    assert max(abs(c) for c in mode['nodes'][1]) < 1e-6


def test_a_cantilever_buckles_at_a_quarter_of_it():
    """Fixed base, free top: K = 2, so pi^2 EI / (2L)^2."""
    n, m, loads, sup = _column('rigid', top=(),
                               base=('ux', 'uy', 'uz', 'rx', 'ry', 'rz'))
    got = sb.buckling(n, m, loads, sup)
    assert got['factors'][0] == pytest.approx(EULER_kN / 4.0 / 100.0,
                                              rel=0.01)


def test_a_rod_in_tension_cannot_buckle():
    n, m, loads, sup = _column('pin', P=-100.0)
    assert 'compression' in sb.buckling(n, m, loads, sup)['error']


def _grid():
    mesh = sg.flat_grid(12, 12, 1.5, 3.0, offset=True, pattern='square')
    n, m = mesh['nodes'], mesh['members']
    for x in m:
        x.update(E=E, A=A, I=I, J=2 * I, r_gyr=math.sqrt(I / A))
    sup = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = [{'node': k, 'fz': -v * 20.0} for k, v in mesh['load_nodes'].items()]
    return n, m, loads, sup


def test_a_grid_buckles_where_its_most_compressed_rod_does():
    n, m, loads, sup = _grid()
    res, err = sm.analyze(n, m, loads, sup)
    assert err is None
    i = min(range(len(m)), key=lambda j: res['member_res'][j]['N'])
    Li = sm.member_vector(n, m[i])[3]
    own = (math.pi ** 2 * E * 1e9 * I * 1e-8 / Li ** 2 / 1e3
           / abs(res['member_res'][i]['N']))
    got = sb.buckling(n, m, loads, sup, results=res)
    # pinned at its joints, the worst rod buckles on its own Euler load
    assert got['factors'][0] == pytest.approx(own, rel=0.03)
    assert got['factors'] == sorted(got['factors'])


def test_the_bow_grows_as_one_over_one_minus_lambda_over_lambda_cr():
    n, m, loads, sup = _grid()
    c = sb.load_deflection(n, m, loads, sup, steps=10)
    lcr = c['lambda_cr']
    assert c['bow_mm'][0] == pytest.approx(c['bow0_mm'])
    for lam, bow in zip(c['factors'], c['bow_mm']):
        assert bow == pytest.approx(c['bow0_mm'] / (1.0 - lam / lcr),
                                    rel=0.03)
    # the node's own first-order line is straight, and second order is
    # never less than first
    assert all(s >= f - 1e-9 for s, f in zip(c['node_mm'], c['first_mm']))
    assert c['first_mm'][-1] == pytest.approx(
        c['first_mm'][1] * c['factors'][-1] / c['factors'][1])
