"""Shell tab -- engine tests: the MITC4 element against published answers,
the model layer against membrane theory and equilibrium, the design code
against the CIRSOC 201-2024 draft, wind against CIRSOC 102-2005, and the
design / thickening behaviour. 2026-09-14."""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.shell import shell_fe as fe
from apps.shell import shell_model as sm
from apps.shell import shell_design as sd
from apps.shell import shell_codes as codes
from apps.shell import shell_wind as wind


# ═══════════════════════════════════════════════════════════════════════════
#  Element benchmarks
# ═══════════════════════════════════════════════════════════════════════════
def _grid(nx, ny, xs, ys, zf):
    X = np.array([[x, y, zf(x, y)] for y in ys for x in xs])
    ids = np.arange(len(X)).reshape(ny + 1, nx + 1)
    el = np.stack([ids[:-1, :-1], ids[:-1, 1:], ids[1:, 1:], ids[1:, :-1]], -1).reshape(-1, 4)
    return X, el, ids


def _plate(n, t=0.01):
    a, E, nu, q = 1.0, 1e7, 0.3, 1.0
    xs = np.linspace(0, a, n + 1)
    X, el, ids = _grid(n, n, xs, xs, lambda x, y: 0.0)
    sh = fe.ShellElements(X, el, t, E, nu)
    K = fe.assemble(len(X), sh)
    F = np.zeros(6 * len(X))
    np.add.at(F, sh.dofs, sh.surface_load(lambda P, nr: np.tile([0, 0, -q], (len(P), 1))))
    fixed = [6 * i + 2 for i in set(ids[0]) | set(ids[-1]) | set(ids[:, 0]) | set(ids[:, -1])]
    for i in (ids[0, 0], ids[0, -1], ids[-1, 0]):
        fixed += [6 * i, 6 * i + 1]
    fixed.append(6 * ids[0, 0] + 5)
    U, R = fe.solve(K, F, fixed, X)
    D = E * t ** 3 / (12 * (1 - nu ** 2))
    return U, R, sh, ids, D, q


def test_simply_supported_plate_matches_the_series_solution():
    """Navier: centre deflection 0.00406 q a^4 / D, centre moment 0.0479 q a^2
    (nu = 0.3). Tests the bending part of the element alone."""
    U, R, sh, ids, D, q = _plate(32)
    w = -U[6 * ids[16, 16] + 2]
    assert w * D / q == pytest.approx(0.004062, rel=0.01)
    res = sh.resultants(U)
    e = int(np.argmin(np.linalg.norm(sh.centroids()[:, :2] - 0.5, axis=1)))
    assert res['Mx'][e] == pytest.approx(0.0479, rel=0.01)
    assert R[2::6].sum() == pytest.approx(1.0, rel=1e-9)        # reactions = load


def test_scordelis_lo_roof_converges_to_the_reference():
    """The standard curved-shell benchmark: mid free-edge vertical deflection
    0.3024 (consistent units). MITC4 approaches it from below."""
    R_, L, th, t, E, g = 25.0, 50.0, math.radians(40), 0.25, 4.32e8, 90.0
    n = 32
    xs = np.linspace(0, L, n + 1)
    ph = np.linspace(-th, th, n + 1)
    X = np.array([[x, R_ * math.sin(p), R_ * math.cos(p)] for p in ph for x in xs])
    ids = np.arange(len(X)).reshape(n + 1, n + 1)
    el = np.stack([ids[:-1, :-1], ids[:-1, 1:], ids[1:, 1:], ids[1:, :-1]], -1).reshape(-1, 4)
    sh = fe.ShellElements(X, el, t, E, 0.0)
    K = fe.assemble(len(X), sh)
    F = np.zeros(6 * len(X))
    np.add.at(F, sh.dofs, sh.surface_load(lambda P, nr: np.tile([0, 0, -g], (len(P), 1))))
    fixed = []
    for i in list(ids[:, 0]) + list(ids[:, -1]):
        fixed += [6 * i + 1, 6 * i + 2]
    fixed.append(6 * ids[n // 2, 0])
    U, _ = fe.solve(K, F, fixed, X)
    w = -U[6 * ids[0, n // 2] + 2]
    assert 0.98 < w / 0.3024 < 1.01


def test_drilling_stabiliser_does_not_change_answers():
    ref = fe.DRILL_RATIO
    try:
        out = []
        for r in (1e-5, 1e-3):
            fe.DRILL_RATIO = r
            U, *_ = _plate(12)
            out.append(U[2::6].min())
        assert out[0] == pytest.approx(out[1], rel=1e-4)
    finally:
        fe.DRILL_RATIO = ref


def test_a_structure_that_can_move_is_refused_with_a_named_node():
    X, el, ids = _grid(4, 4, np.linspace(0, 4, 5), np.linspace(0, 4, 5), lambda x, y: 0.1 * x * y)
    sh = fe.ShellElements(X, el, 0.05, 25e9, 0.2)
    K = fe.assemble(len(X), sh)
    F = np.zeros(6 * len(X))
    F[2::6] = -1000.0
    fixed = [6 * n + 2 for n in (ids[0, 0], ids[0, -1], ids[-1, 0], ids[-1, -1])]   # z only
    with pytest.raises(fe.MechanismError) as e:
        fe.solve(K, F, fixed, X)
    assert 'moves freely' in str(e.value) or 'move freely' in str(e.value)
    assert e.value.node is not None


# ═══════════════════════════════════════════════════════════════════════════
#  Model layer
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize('name', list(sm.PRESETS))
def test_every_preset_solves_and_balances(name):
    m = sm.ShellModel.preset(name)
    r = m.analyze()
    for eq in r.equilibrium:
        assert np.abs(eq['force']).max() < 1e-6 * eq['scale'] + 1e-3
        assert np.abs(eq['moment']).max() < 1e-5 * eq['scale'] * 30 + 1e-2


def test_symmetric_hypar_gives_a_symmetric_answer():
    m = sm.ShellModel.preset('Hypar saddle on four edge beams')
    r = m.analyze()
    uz = r.U[2::6, 0][:len(r.fem['mesh']['X'])].reshape(r.fem['mesh']['ids'].shape)
    # z = k x y is symmetric under (x, y) -> (-x, -y) and (x, y) -> (y, x)
    assert np.allclose(uz, uz[::-1, ::-1], atol=1e-9 + 1e-6 * np.abs(uz).max())
    assert np.allclose(uz, uz.T, atol=1e-9 + 1e-6 * np.abs(uz).max())


@pytest.mark.parametrize('beam, tol', [((50, 100), 0.03), ((100, 200), 0.015)])
def test_hypar_interior_shear_approaches_membrane_theory_as_edges_stiffen(beam, tol):
    """Membrane theory: a hypar z = k x y under q per plan area carries pure
    shear Nxy = q/(2k), with rigid edge members. With stiff edge beams the
    finite-element interior must approach that value."""
    m = sm.ShellModel.preset('Hypar saddle on four edge beams')
    d = m.data
    d['self_weight'] = False
    d['cases'] = [{'name': 'Lr', 'kind': 'Lr'}]
    d['loads'] = [{'case': 'Lr', 'type': 'plan_vertical', 'value': '1.0'}]
    d['beams'][0].update(b=beam[0], h=beam[1], offset='centre')
    r = m.analyze()
    k = r.hypar_fit()
    assert k == pytest.approx(2 * 3 / (12 * 12))
    c = r.fem['mesh']['centroids']
    inner = (np.abs(c[:, 0]) < 3.6) & (np.abs(c[:, 1]) < 3.6)
    Nxy = r.per_case[0]['Nxy'][inner].mean()
    assert Nxy == pytest.approx(1e3 / (2 * k), rel=tol)
    assert np.abs(r.per_case[0]['Nx'][inner]).max() < 0.3 * Nxy


def test_load_types_put_the_right_total_on_the_structure():
    m = sm.ShellModel.preset('Hypar saddle on four edge beams')
    d = m.data
    d['self_weight'] = False
    d['cases'] = [{'name': 'L', 'kind': 'L'}, {'name': 'W', 'kind': 'W'}]
    d['loads'] = [{'case': 'L', 'type': 'plan_vertical', 'value': '2'},
                  {'case': 'W', 'type': 'surface_x', 'value': '0.5'}]
    r = m.analyze()
    plan = 12.0 * 12.0
    area = r.fem['shells'].areas().sum()
    assert r.equilibrium[0]['applied'][2] == pytest.approx(-2e3 * plan, rel=1e-9)
    assert r.equilibrium[1]['applied'][0] == pytest.approx(0.5e3 * area, rel=1e-9)


def test_model_errors_speak_in_the_users_terms():
    m = sm.ShellModel.preset('Hypar saddle on four edge beams')
    m.ws.set_lines(['a = 12', 'b = 12', 'z(x, y) = sqrt(x)', 't = 0.1'])
    with pytest.raises(sm.ModelError) as e:
        m.analyze()
    assert 'Surface' in str(e.value)
    m.ws.set_lines(['a = 12', 'b = 12', 'z(x, y) = 0', 't = -0.1'])
    with pytest.raises(sm.ModelError):
        m.analyze()
    m = sm.ShellModel.preset('Hypar saddle on four edge beams')
    m.data['supports'] = []
    with pytest.raises(sm.ModelError):
        m.analyze()


def test_round_trip_through_a_dict_gives_the_same_answer():
    m = sm.ShellModel.preset('Inverted umbrella (4 hypars on one column)')
    r1 = m.analyze()
    m2 = sm.ShellModel.from_dict(m.to_dict())
    r2 = m2.analyze()
    assert np.allclose(r1.U, r2.U)


# ═══════════════════════════════════════════════════════════════════════════
#  Codes and wind
# ═══════════════════════════════════════════════════════════════════════════
def test_cirsoc_2024_values_read_off_the_draft():
    c = codes.get_code('cirsoc201_2024')
    assert c.Ec(30) == pytest.approx(4700 * math.sqrt(30))           # 19.2.2.1(b)
    assert c.fr(30) == pytest.approx(0.62 * math.sqrt(30))           # 19.2.3.1
    assert c.phi_plain == 0.60 and c.phi_shear == 0.75               # Tabla 21.2.1
    assert c.rho_min(420) == 0.0018                                  # 24.4.3.2
    assert c.max_spacing(0.10) == 450.0 and c.max_spacing(0.06) == 300.0
    assert c.min_cover_mm(8, exposed=True, controlled=True) == 35.0  # Tabla 20.5.1.3.1
    assert c.min_cover_mm(20, exposed=True, controlled=False) == 45.0
    # Tabla 22.5.5.1(c) with the size effect: d = 50 mm -> lambda_s = 1
    v = c.Vc(30, 0.05, rho_w=0.004, Nu=0.0) / (0.05 * 1e6)
    assert v == pytest.approx(0.66 * 0.004 ** (1 / 3) * math.sqrt(30), rel=1e-9)
    assert c.Vc(30, 0.05, 0.004, Nu=-1e9) == 0.0                     # tension -> not below 0
    # Tabla 22.6.5.2: square column, large d/b0 -> 0.33 lambda_s sqrt(f'c)
    assert c.punching_vc(30, 0.1, 1.0) == pytest.approx(0.33 * math.sqrt(30))


def test_cirsoc_2024_combinations_follow_tabla_5_3_1():
    c = codes.get_code('cirsoc201_2024')
    combos = c.combinations({'D': 'D', 'Lr': 'Lr', 'W1': 'W'}, f1=0.5)
    got = {tuple(sorted(x.factors.items())) for x in combos}
    assert (('D', 1.4),) in got                                     # (5.3.1a)
    assert (('D', 1.2), ('Lr', 1.6), ('W1', 0.5)) in got             # (5.3.1c)
    assert (('D', 1.2), ('Lr', 0.5), ('W1', 1.0)) in got             # (5.3.1d)
    assert (('D', 0.9), ('W1', 1.0)) in got                          # (5.3.1f)


def test_wind_from_2005_speeds_is_scaled_to_the_2024_factors():
    """CIRSOC 201-2024 combines 1.0 W with strength-level wind; the city
    speeds here are CIRSOC 102-2005 (service level, formerly 1.6 W). Scaling
    W by 1.6 must reproduce the 2005 factors exactly."""
    c = codes.get_code('cirsoc201_2024')
    k = c.wind_scale_for('2005')
    assert k == 1.6
    combos = c.combinations({'D': 'D', 'Lr': 'Lr', 'W1': 'W'}, wind_scale=k)
    got = {tuple(sorted(x.factors.items())) for x in combos}
    assert (('D', 0.9), ('W1', 1.6)) in got
    assert (('D', 1.2), ('Lr', 1.6), ('W1', 0.8)) in got


def test_wind_velocity_pressure_matches_the_guides_worked_example():
    assert wind._selftest()
    assert wind.velocity_pressure(48, 64, 'A') == pytest.approx(1098.45, abs=1.0)
    assert wind.Kz(10, 'C') == pytest.approx(1.00, abs=0.005)       # Tabla 5


# ═══════════════════════════════════════════════════════════════════════════
#  Design
# ═══════════════════════════════════════════════════════════════════════════
def test_nielsen_pure_shear_and_biaxial_compression():
    fx, fy, fc = sd._nielsen(np.array([0.0]), np.array([0.0]), np.array([100.0]))
    assert (fx[0], fy[0], fc[0]) == (100.0, 100.0, 200.0)
    fx, fy, fc = sd._nielsen(np.array([-300.0]), np.array([-100.0]), np.array([50.0]))
    assert fx[0] == 0 and fy[0] == 0
    n2 = -200 - math.sqrt(100 ** 2 + 50 ** 2)
    assert fc[0] == pytest.approx(-n2)
    fx, fy, fc = sd._nielsen(np.array([-400.0]), np.array([100.0]), np.array([200.0]))
    assert fx[0] == 0 and fy[0] == pytest.approx(100 + 200 ** 2 / 400)


def test_hypar_membrane_steel_by_hand():
    """A hypar element in pure shear Nxy with one central mesh needs
    Nxy/(phi fy) of steel each way -- the hand calculation of section 1 of
    the diagnosis (125 kN/m -> 3.3 cm^2/m at 420 MPa)."""
    m = sm.ShellModel.preset('Hypar saddle on four edge beams')
    S = sd.DesignSettings(m)

    class St:
        pass
    st = St()
    st.e1 = np.array([[1.0, 0, 0]])
    st.e2 = np.array([[0, 1.0, 0]])
    st.geo = tuple(np.zeros(1) for _ in range(5))
    st.E_buck, st.L_plate = 25e9, 12.0
    st.in_head = np.zeros(1, bool)
    st.heads, st.xc, st.yc = [], np.zeros(1), np.zeros(1)
    F = {k: np.zeros(1) for k in ('Nx', 'Ny', 'Mx', 'My', 'Mxy', 'Qx', 'Qy')}
    F['Nxy'] = np.array([125e3])
    util, steel = sd._check_at(st, S, F, np.array([0.10]))
    As = steel['x_mid'][0] * 1e4
    assert As == pytest.approx(125e3 / (0.9 * 420e6) * 1e4, rel=1e-9)   # 3.31 cm^2/m
    assert 3.2 < As < 3.4


def test_thickening_is_local_and_converges():
    m = sm.ShellModel.preset('Inverted umbrella (4 hypars on one column)')
    res, des, log = sd.auto_thicken(m)
    assert not des.fails.any(), log
    layer = m.data['auto_layer']
    n_raised = len(layer['points'])
    assert 0 < n_raised < 0.25 * len(des.t)          # only near the column
    far = np.hypot(*res.fem['mesh']['centroids'][:, :2].T) > 3.0
    assert np.all(des.t[far] == pytest.approx(0.10))


def test_show_first_changes_nothing():
    """The default is to SHOW where thickening is needed; the thickness of
    the model must not change until automatic thickening is switched on."""
    m = sm.ShellModel.preset('Elliptic paraboloid dome')
    r = m.analyze()
    d = sd.design(m, r)
    assert d.needs_thicker.any()
    assert m.data['auto_layer'] is None
    assert np.all(r.fem['shells'].a == pytest.approx(0.10))


def test_column_head_punching_is_checked_and_mesh_stable():
    utils = []
    # element sizes that put nodes on the head's edge (1.2 m head: +-0.6 m)
    for size in (0.3, 0.2):
        m = sm.ShellModel.preset('Inverted umbrella (4 hypars on one column)')
        m.data['mesh']['size'] = size
        r = m.analyze()
        d = sd.design(m, r)
        p = [q for q in d.punching if q['kind'] == 'column'][0]
        assert not p['coarse']
        utils.append(p['Vu'])
    assert utils[0] == pytest.approx(utils[1], rel=0.15)


def test_a_mesh_too_coarse_for_the_column_head_is_flagged():
    m = sm.ShellModel.preset('Inverted umbrella (4 hypars on one column)')
    m.data['mesh']['size'] = 0.4          # nodes at 0, +-0.4: the 1.2 m head shrinks to 0.8
    d = sd.design(m, m.analyze())
    assert [q for q in d.punching if q['kind'] == 'column'][0]['coarse']


def test_vertical_supports_only_is_refused_not_solved():
    m = sm.ShellModel.preset('Hypar saddle on four edge beams')
    m.data['supports'] = [{'at': 'corners', 'which': 'all', 'type': 'vertical', 'block': 0}]
    with pytest.raises(fe.MechanismError):
        m.analyze()
