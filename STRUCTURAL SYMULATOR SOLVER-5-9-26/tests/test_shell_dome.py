"""The spherical dome: membrane theory, and the edge disturbance.

The case is the one in Mekjavic & Piculin (2010): a spherical cap of
radius 28.80 m and half-angle 28 degrees, 10.2 cm thick, nu = 1/6,
E = 32 GPa, under 4.31 kN/m2 of its own surface. It is in the
verification set because it is the one shape whose answer is known in
closed form all the way through, and because it exercises the two things
a flat-plate benchmark cannot: a doubly curved mid-surface, and a
boundary layer.

WHAT IS ASSERTED AND WHAT IS NOT. The interior is checked against the
classical membrane solution for a spherical shell under a load uniform
over its surface,

    N_phi   = -q R / (1 + cos phi)
    N_theta =  q R ( 1 / (1 + cos phi) - cos phi )

and the edge against global equilibrium, which fixes the meridional
force there whatever the bending does: everything the dome weighs has to
leave through the edge, so N_phi sin(alpha) times the edge circumference
IS the weight, and no support condition can change it. Published tables
of edge values are not asserted, because a number read off a table and
carried in memory is not evidence; the closed-form results are.

The edge disturbance is checked by its own length scale. Shell theory
gives the decay rate beta = [3(1 - nu^2)]^(1/4) sqrt(R/t), here 22.0, so
the disturbance is spent within about 3/beta = 7.8 degrees of the edge.
The test asserts both halves of that: that the hoop force really does
collapse at the edge (it is a boundary layer, not a smooth field), and
that it really has recovered outside it (it is a LOCAL disturbance, not
a wrong answer everywhere).
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.shell import shell_model as sm

R = 28.80                     # sphere radius, m
ALPHA = math.radians(28.0)    # half-angle of the cap
T = 0.102                     # thickness, m
Q = 4.31                      # load per m2 of SURFACE, kN/m2
NU = 1.0 / 6.0
E_MPA = 32000.0
RB = R * math.sin(ALPHA)      # base radius, 13.52 m
BETA = (3 * (1 - NU ** 2)) ** 0.25 * math.sqrt(R / T)       # 21.96


def n_phi(phi):
    """Membrane meridional force, kN/m (negative = compression)."""
    return -Q * R / (1 + math.cos(phi))


def n_theta(phi):
    """Membrane hoop force, kN/m."""
    return Q * R * (1.0 / (1 + math.cos(phi)) - math.cos(phi))


@pytest.fixture(scope='module')
def dome():
    m = sm.ShellModel.preset('Elliptic paraboloid dome')
    m.data['lines'] = ['# Mekjavic & Piculin (2010) verification dome',
                       'R = 28.80', 'al = 28 pi / 180', 'rb = R sin(al)',
                       'zc = R cos(al)',
                       'z(x, y) = sqrt(R^2 - x^2 - y^2) - zc', 't = 0.102']
    m.ws = type(m.ws)(m.data['lines'], None)
    m.data['sliders'] = {}
    m.data['plan'] = {'x0': '-rb', 'x1': 'rb', 'y0': '-rb', 'y1': 'rb'}
    # the circular plan is why this case had to wait for the contour: on a
    # staircase edge there is no ring to pin and no boundary layer to find
    m.data['edge_rule'] = 'hypot(x, y) - rb'
    m.data['mesh'] = {'nx': 40, 'ny': 40, 'size': 0.5}
    m.data['material'] = {'fc': 30.0, 'fy': 420.0, 'Ec': E_MPA, 'nu': NU,
                          'gamma': 25.0}
    m.data['self_weight'] = False          # the paper's q is the whole load
    m.data['beams'] = []
    m.data['columns'] = []
    m.data['supports'] = [{'at': 'cut', 'which': 'all', 'type': 'pinned'}]
    m.data['cases'] = [{'name': 'D', 'kind': 'D'}]
    m.data['loads'] = [{'case': 'D', 'type': 'surface_vertical', 'value': '4.31'}]
    res = m.analyze()
    return m, res


def ring(res, phi_deg, tol=0.45):
    """(N_phi, N_theta, M_phi) in kN/m and kNm/m, averaged over the elements
    on the +x axis at that colatitude. On the x axis the meridian runs in x
    and the parallel in y, so the global resultants are the spherical ones
    without any rotation."""
    g = res.fem['mesh']
    F = res.combo_forces(res.service)
    cen = g['centroids']
    rad = np.hypot(cen[:, 0], cen[:, 1])
    want = R * math.sin(math.radians(phi_deg))
    sel = (np.abs(cen[:, 1]) < 0.55) & (cen[:, 0] > 0) & (np.abs(rad - want) < tol)
    assert sel.any(), 'no element at phi = %g deg' % phi_deg
    return (F['Nx'][sel].mean() / 1e3, F['Ny'][sel].mean() / 1e3,
            F['Mx'][sel].mean() / 1e3)


# ── the model is the dome that was asked for ───────────────────────────────

def test_the_geometry_is_the_cap_in_the_paper(dome):
    m, res = dome
    g = res.fem['mesh']
    assert RB == pytest.approx(13.521, abs=1e-3)
    rad = np.hypot(g['X'][:, 0], g['X'][:, 1])
    used = g['used']
    assert rad[used].max() == pytest.approx(RB, abs=1e-6)
    # the highest NODE, not the crown: the grid does not put one at x = y = 0,
    # so the drawn apex sits a couple of millimetres low on a 28.8 m sphere
    assert g['X'][:, 2].max() == pytest.approx(R - R * math.cos(ALPHA), abs=5e-3)


def test_the_circular_edge_is_fitted_not_stepped(dome):
    """The reason this case could not be built before the contour landed."""
    m, res = dome
    g = res.fem['mesh']
    assert g['has_edge_rule'] and g['fitted'].sum() > 50
    from apps.shell import shell_solid as solid
    per = 0.0
    for loop in solid.boundary_loops(g['elems']):
        P = g['X'][np.asarray(loop, int), :2]
        per += float(np.hypot(*(P[1:] - P[:-1]).T).sum())
    assert per == pytest.approx(2 * math.pi * RB, rel=2e-3)


# ── membrane theory, in the interior ───────────────────────────────────────

def test_the_apex_carries_half_the_radius_times_the_load(dome):
    """N = -qR/2 at the crown, in both directions: the one value of a dome
    everybody knows by heart."""
    m, res = dome
    nphi, nth, _mphi = ring(res, 0.6)
    assert nphi == pytest.approx(-Q * R / 2, rel=0.01)
    assert nth == pytest.approx(-Q * R / 2, rel=0.01)


@pytest.mark.parametrize('phi_deg', [4, 8, 12, 16])
def test_the_interior_is_the_membrane_solution(dome, phi_deg):
    m, res = dome
    phi = math.radians(phi_deg)
    nphi, nth, _mphi = ring(res, phi_deg)
    assert nphi == pytest.approx(n_phi(phi), rel=0.02)
    assert nth == pytest.approx(n_theta(phi), rel=0.03)


def test_the_meridional_force_grows_towards_the_edge(dome):
    m, res = dome
    vals = [ring(res, p)[0] for p in (4, 12, 20, 26)]
    assert all(b < a for a, b in zip(vals, vals[1:])), vals


def test_the_interior_carries_almost_no_bending(dome):
    """A membrane state is the claim; a moment of a few percent of q R t is
    what backs it up."""
    m, res = dome
    for p in (4, 8, 12, 16):
        assert abs(ring(res, p)[2]) < 0.05 * Q * R * T


# ── the edge: equilibrium, and a boundary layer ────────────────────────────

def test_the_edge_meridional_force_is_what_equilibrium_demands(dome):
    """Everything the dome weighs leaves through the edge, so this one is
    not a matter of theory or of support condition: N_phi sin(alpha) times
    the circumference IS the weight."""
    m, res = dome
    weight = Q * 2 * math.pi * R * R * (1 - math.cos(ALPHA))     # kN
    per_m = weight / (2 * math.pi * RB)
    nphi = ring(res, 27.2)[0]
    assert -nphi * math.sin(ALPHA) == pytest.approx(per_m, rel=0.03)
    assert nphi == pytest.approx(n_phi(ALPHA), rel=0.03)


def test_the_hoop_force_collapses_at_the_edge(dome):
    """The disturbance a pinned edge makes: the membrane solution wants the
    edge to move inwards and the support will not let it, so the hoop force
    there is nothing like the membrane value. A model that reported -43
    kN/m at the edge would be reporting membrane theory, not a shell."""
    m, res = dome
    edge = ring(res, 27.2)[1]
    assert abs(edge) < 0.6 * abs(n_theta(ALPHA))


def test_the_disturbance_is_confined_to_its_own_length_scale(dome):
    """beta = [3(1-nu^2)]^(1/4) sqrt(R/t) = 22, so it is spent about 3/beta
    = 7.8 degrees in. Outside that the shell is back on membrane theory --
    which is what makes it a boundary LAYER and not a wrong answer."""
    assert BETA == pytest.approx(22.0, abs=0.1)
    m, res = dome
    psi = math.degrees(3.0 / BETA)
    assert psi == pytest.approx(7.8, abs=0.2)
    inside = math.degrees(ALPHA) - psi - 2.0            # clear of the layer
    nth = ring(res, inside)[1]
    assert nth == pytest.approx(n_theta(math.radians(inside)), rel=0.05)


def test_bending_appears_only_in_the_edge_zone(dome):
    m, res = dome
    far = abs(ring(res, 8)[2])
    near = abs(ring(res, 26)[2])
    assert near > 10 * far


# ── the whole thing balances ───────────────────────────────────────────────

def test_the_reactions_add_up_to_the_weight(dome):
    m, res = dome
    weight = Q * 2 * math.pi * R * R * (1 - math.cos(ALPHA)) * 1e3     # N
    eq = res.equilibrium[0]
    assert abs(eq['applied'][2]) == pytest.approx(weight, rel=0.01)
    assert abs(eq['reaction'][2]) == pytest.approx(weight, rel=0.01)
    assert abs(eq['force'][2]) < 1e-6 * weight
