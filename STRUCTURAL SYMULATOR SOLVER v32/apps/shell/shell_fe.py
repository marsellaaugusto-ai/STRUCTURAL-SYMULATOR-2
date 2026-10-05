"""shell_fe.py -- finite-element core of the Shell tab, 2026-09-14.

Pure numpy/scipy; no Tkinter, no units layer, no design code. Everything here
is in strict SI: metres, newtons, pascals, radians.

ELEMENTS
  * MITC4 shell (Dvorkin & Bathe, 1984): a four-node degenerated-continuum
    shell. Membrane + bending + transverse shear, with the transverse shear
    strains sampled at the mid-edges ("tying points") so a thin element does
    not lock. It takes curved and TWISTED geometry natively -- the four
    corners of a hypar element are not coplanar, which a flat-facet element
    would have to approximate.
  * 3-D frame element (Timoshenko, 12 DOF) for edge beams and columns, with
    an optional rigid offset from the shell node to the beam centroid (an
    edge beam hanging below the shell).

DEGREES OF FREEDOM: six per node, all GLOBAL -- u, v, w, theta_x, theta_y,
theta_z. The shell's director rotation is taken from the global rotation
vector (theta x director), which is what lets two elements that meet at a
fold -- the valley of an inverted umbrella -- share a node while each keeps
its own director. The rotation about the director ("drilling") is not a
shell quantity; it is tied to the in-plane rotation of the membrane by a
weak Hughes-Brezzi penalty (1/1000 of G), which removes the singularity
without adding stiffness to any rigid-body motion. That matters: a
stabilising spring to ground would hide a real mechanism from the check in
`solve()`.

SIGN CONVENTIONS (the ones the rest of the tab reports)
  * Element nodes counter-clockwise in plan, so the element normal n points
    up (+z side) for any surface z = f(x, y).
  * Local axes per element: e1 = the global X direction projected onto the
    tangent plane, e3 = n, e2 = e3 x e1. "Nx" is the membrane force along
    e1, i.e. along x as seen in plan.
  * Membrane forces N (N/m): tension positive.
  * Moments M (N*m/m): POSITIVE = TENSION ON THE BOTTOM FACE (the face
    opposite n). Mx bends about e2 with stresses along e1.
  * Transverse shear Q (N/m): Qx on the face normal to e1, along n.
"""
import math

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

GP = 1.0 / math.sqrt(3.0)
GAUSS2 = [(-GP, -GP), (GP, -GP), (GP, GP), (-GP, GP)]
T_GAUSS = (-GP, GP)
SHEAR_FACTOR = 5.0 / 6.0
DRILL_RATIO = 1e-3          # drilling penalty = DRILL_RATIO * G

NDOF = 6


class MechanismError(RuntimeError):
    """The structure can move without resistance, so it has no unique
    answer. Carries a plain-language `hint` and the `node`/`dof` that moves
    most in the free motion."""

    def __init__(self, msg, hint='', node=None, dof=None):
        super().__init__(msg)
        self.hint = hint
        self.node = node
        self.dof = dof


# ═══════════════════════════════════════════════════════════════════════════
#  Small helpers
# ═══════════════════════════════════════════════════════════════════════════
def shape4(r, s):
    """Bilinear shape functions and their r, s derivatives for nodes
    1(-1,-1) 2(1,-1) 3(1,1) 4(-1,1)."""
    h = 0.25 * np.array([(1 - r) * (1 - s), (1 + r) * (1 - s),
                         (1 + r) * (1 + s), (1 - r) * (1 + s)])
    hr = 0.25 * np.array([-(1 - s), (1 - s), (1 + s), -(1 + s)])
    hs = 0.25 * np.array([-(1 - r), -(1 + r), (1 + r), (1 - r)])
    return h, hr, hs


def skew(v):
    """skew(v) @ w == cross(v, w), vectorised over leading axes."""
    v = np.asarray(v, float)
    z = np.zeros(v.shape[:-1])
    return np.stack([np.stack([z, -v[..., 2], v[..., 1]], -1),
                     np.stack([v[..., 2], z, -v[..., 0]], -1),
                     np.stack([-v[..., 1], v[..., 0], z], -1)], -2)


def _unit(v):
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n > 0, n, 1.0)


def local_frame(normal):
    """e1 (global X projected on the tangent plane), e2, e3 = normal. Where X
    is nearly normal to the surface, global Y is projected instead."""
    n = _unit(normal)
    X = np.array([1.0, 0.0, 0.0])
    Y = np.array([0.0, 1.0, 0.0])
    p = X - (n @ X)[..., None] * n
    bad = np.linalg.norm(p, axis=-1) < 0.2
    if np.any(bad):
        py = Y - (n @ Y)[..., None] * n
        p = np.where(bad[..., None], py, p)
    e1 = _unit(p)
    e2 = np.cross(n, e1)
    return e1, e2, n


# ═══════════════════════════════════════════════════════════════════════════
#  Directors
# ═══════════════════════════════════════════════════════════════════════════
def element_corner_normals(X, elems):
    """Unit normal of each element at each of its corners, (ne, 4, 3)."""
    xe = X[elems]
    out = np.empty(xe.shape)
    for k, (r, s) in enumerate([(-1, -1), (1, -1), (1, 1), (-1, 1)]):
        _h, hr, hs = shape4(r, s)
        gr = np.einsum('k,ekj->ej', hr, xe)
        gs = np.einsum('k,ekj->ej', hs, xe)
        out[:, k] = _unit(np.cross(gr, gs))
    return out


def nodal_directors(X, elems, fold_deg=15.0):
    """Director of each element at each corner, (ne, 4, 3).

    On a smooth surface every element meeting at a node gets the SAME
    director (the average of their corner normals), which is what makes the
    shell continuous in rotation. Across a fold -- where two elements' normals
    differ by more than `fold_deg` -- each element averages only with the
    elements on its own side, so the fold stays sharp."""
    cn = element_corner_normals(X, elems)
    ne = len(elems)
    nn = len(X)
    inc = [[] for _ in range(nn)]
    for e in range(ne):
        for k in range(4):
            inc[elems[e, k]].append((e, k))
    cos_t = math.cos(math.radians(fold_deg))
    V = np.empty_like(cn)
    for node, lst in enumerate(inc):
        if not lst:
            continue
        ns = np.array([cn[e, k] for e, k in lst])
        dots = ns @ ns.T
        for i, (e, k) in enumerate(lst):
            V[e, k] = _unit(ns[dots[i] > cos_t].sum(axis=0))
    return V


# ═══════════════════════════════════════════════════════════════════════════
#  MITC4 shell element
# ═══════════════════════════════════════════════════════════════════════════
class ShellElements:
    """All MITC4 elements of a model, vectorised.

    X: (nn, 3) node coordinates; elems: (ne, 4) node indices, counter-clockwise
    in plan; thick: (ne,) thickness; E, nu: scalars or (ne,) arrays;
    V: (ne, 4, 3) directors (default: `nodal_directors`)."""

    def __init__(self, X, elems, thick, E, nu, V=None):
        self.X = np.asarray(X, float)
        self.elems = np.asarray(elems, int)
        ne = len(self.elems)
        self.ne = ne
        self.a = np.broadcast_to(np.asarray(thick, float), (ne,)).copy()
        self.E = np.broadcast_to(np.asarray(E, float), (ne,)).copy()
        self.nu = np.broadcast_to(np.asarray(nu, float), (ne,)).copy()
        self.V = nodal_directors(self.X, self.elems) if V is None else np.asarray(V, float)
        self.xe = self.X[self.elems]                       # (ne, 4, 3)
        self.S = -skew(self.V)                             # theta -> director increment
        self.dofs = (self.elems[:, :, None] * NDOF + np.arange(NDOF)).reshape(ne, 24)

    # -- kinematics -----------------------------------------------------------
    def _derivs(self, r, s, t):
        """Covariant base vectors g_r, g_s, g_t (ne,3) and the displacement
        derivative operators D_r, D_s, D_t (ne, 3, 24)."""
        h, hr, hs = shape4(r, s)
        a2 = (0.5 * self.a)[:, None]                        # (ne,1)
        pos = self.xe + t * a2[:, None, :] * self.V         # (ne,4,3)
        g_r = np.einsum('k,ekj->ej', hr, pos)
        g_s = np.einsum('k,ekj->ej', hs, pos)
        g_t = np.einsum('k,ekj->ej', h, self.V) * a2
        ne = self.ne
        D_r = np.zeros((ne, 3, 24))
        D_s = np.zeros((ne, 3, 24))
        D_t = np.zeros((ne, 3, 24))
        I3 = np.eye(3)
        for k in range(4):
            c = 6 * k
            D_r[:, :, c:c + 3] = hr[k] * I3
            D_s[:, :, c:c + 3] = hs[k] * I3
            rot = self.S[:, k] * a2[:, :, None]              # (ne,3,3)
            D_r[:, :, c + 3:c + 6] = hr[k] * t * rot
            D_s[:, :, c + 3:c + 6] = hs[k] * t * rot
            D_t[:, :, c + 3:c + 6] = h[k] * rot
        return g_r, g_s, g_t, D_r, D_s, D_t

    @staticmethod
    def _dot(g, D):
        return np.einsum('ei,eij->ej', g, D)

    def _tying(self, t):
        """Transverse-shear covariant strain rows at the four MITC4 tying
        points (mid-edges) for thickness coordinate t. They depend on t only,
        so they are computed once per t and reused at every Gauss point."""
        key = float(t)
        cache = self.__dict__.setdefault('_tying_cache', {})
        if key not in cache:
            def e_rt(rr, ss):
                gr, _gs, gt, Dr, _Ds, Dt = self._derivs(rr, ss, t)
                return 0.5 * (self._dot(gr, Dt) + self._dot(gt, Dr))

            def e_st(rr, ss):
                _gr, gs, gt, _Dr, Ds, Dt = self._derivs(rr, ss, t)
                return 0.5 * (self._dot(gs, Dt) + self._dot(gt, Ds))
            cache[key] = (e_rt(0.0, 1.0), e_rt(0.0, -1.0), e_st(1.0, 0.0), e_st(-1.0, 0.0))
        return cache[key]

    def _cov_B(self, r, s, t):
        """Rows of the covariant strain operator at (r, s, t), MITC-tied:
        returns (B_rr, B_ss, B_rs, B_rt, B_st) each (ne, 24), plus the base
        vectors at the point."""
        g_r, g_s, g_t, D_r, D_s, D_t = self._derivs(r, s, t)
        B_rr = self._dot(g_r, D_r)
        B_ss = self._dot(g_s, D_s)
        B_rs = 0.5 * (self._dot(g_r, D_s) + self._dot(g_s, D_r))
        rtA, rtC, stD, stB = self._tying(t)
        B_rt = 0.5 * (1 + s) * rtA + 0.5 * (1 - s) * rtC
        B_st = 0.5 * (1 + r) * stD + 0.5 * (1 - r) * stB
        return (B_rr, B_ss, B_rs, B_rt, B_st), (g_r, g_s, g_t)

    @staticmethod
    def _transform(g_r, g_s, g_t, e1, e2, e3):
        """(ne, 5, 5): covariant [e_rr, e_ss, e_rs, e_rt, e_st] (tensor
        components) -> local engineering [e11, e22, g12, g13, g23]."""
        G = np.stack([g_r, g_s, g_t], axis=1)              # rows g_i
        Gc = np.transpose(np.linalg.inv(G), (0, 2, 1))     # rows g^i
        Eb = np.stack([e1, e2, e3], axis=1)                # rows e_a
        c = np.einsum('eik,eak->eia', Gc, Eb)              # c[i,a] = g^i . e_a
        r_, s_, t_ = 0, 1, 2

        def row(a, b, eng):
            f = 2.0 if eng else 1.0
            return f * np.stack([
                c[:, r_, a] * c[:, r_, b],
                c[:, s_, a] * c[:, s_, b],
                c[:, r_, a] * c[:, s_, b] + c[:, s_, a] * c[:, r_, b],
                c[:, r_, a] * c[:, t_, b] + c[:, t_, a] * c[:, r_, b],
                c[:, s_, a] * c[:, t_, b] + c[:, t_, a] * c[:, s_, b]], axis=1)
        return np.stack([row(0, 0, False), row(1, 1, False), row(0, 1, True),
                         row(0, 2, True), row(1, 2, True)], axis=1)

    def _C(self):
        """(ne, 5, 5) local plane-stress + transverse shear material matrix."""
        E, nu = self.E, self.nu
        G = E / (2 * (1 + nu))
        C = np.zeros((self.ne, 5, 5))
        f = E / (1 - nu ** 2)
        C[:, 0, 0] = f
        C[:, 1, 1] = f
        C[:, 0, 1] = C[:, 1, 0] = f * nu
        C[:, 2, 2] = G
        C[:, 3, 3] = SHEAR_FACTOR * G
        C[:, 4, 4] = SHEAR_FACTOR * G
        return C

    def local_B(self, r, s, t):
        """(ne, 5, 24) operator giving local [e11, e22, g12, g13, g23], the
        frame (e1, e2, e3) and det J at the point."""
        (B_rr, B_ss, B_rs, B_rt, B_st), (g_r, g_s, g_t) = self._cov_B(r, s, t)
        e1, e2, e3 = local_frame(np.cross(g_r, g_s))
        T = self._transform(g_r, g_s, g_t, e1, e2, e3)
        Bc = np.stack([B_rr, B_ss, B_rs, B_rt, B_st], axis=1)   # (ne,5,24)
        detJ = np.einsum('ej,ej->e', np.cross(g_r, g_s), g_t)
        return np.einsum('eab,ebj->eaj', T, Bc), (e1, e2, e3), detJ

    # -- stiffness --------------------------------------------------------------
    def stiffness(self):
        """(ne, 24, 24) element stiffness matrices in global DOFs."""
        C = self._C()
        K = np.zeros((self.ne, 24, 24))
        for (r, s) in GAUSS2:
            for t in T_GAUSS:
                B, _frame, detJ = self.local_B(r, s, t)
                if np.any(detJ <= 0):
                    bad = int(np.argmin(detJ))
                    raise ValueError(f'Element {bad} is inverted or has zero '
                                     'thickness (negative Jacobian).')
                K += np.transpose(B, (0, 2, 1)) @ (C @ B) * detJ[:, None, None]
        K += self._drilling()
        return 0.5 * (K + np.transpose(K, (0, 2, 1)))

    def _drilling(self):
        """Hughes-Brezzi drilling penalty: gamma * a * int (theta_n - omega)^2 dA
        with omega the in-plane rotation of the mid-surface, 2x2 points."""
        G = self.E / (2 * (1 + self.nu))
        gam = DRILL_RATIO * G * self.a
        K = np.zeros((self.ne, 24, 24))
        for (r, s) in GAUSS2:
            h, _hr, _hs = shape4(r, s)
            g_r, g_s, g_t, D_r, D_s, _D_t = self._derivs(r, s, 0.0)
            e1, e2, e3 = local_frame(np.cross(g_r, g_s))
            G_ = np.stack([g_r, g_s, g_t], axis=1)
            Gc = np.transpose(np.linalg.inv(G_), (0, 2, 1))
            c1 = np.einsum('eik,ek->ei', Gc, e1)          # g^i . e1
            c2 = np.einsum('eik,ek->ei', Gc, e2)
            du1 = D_r * c1[:, 0, None, None] + D_s * c1[:, 1, None, None]   # d u / d x1
            du2 = D_r * c2[:, 0, None, None] + D_s * c2[:, 1, None, None]   # d u / d x2
            omega = 0.5 * (np.einsum('ei,eij->ej', e2, du1) - np.einsum('ei,eij->ej', e1, du2))
            thn = np.zeros((self.ne, 24))
            for k in range(4):
                thn[:, 6 * k + 3:6 * k + 6] = h[k] * e3
            R = thn - omega
            dA = np.linalg.norm(np.cross(g_r, g_s), axis=1)
            K += (R * (gam * dA)[:, None])[:, :, None] * R[:, None, :]
        return K

    # -- geometry queries -------------------------------------------------------
    def centroids(self):
        return self.xe.mean(axis=1)

    def normals(self):
        _h, hr, hs = shape4(0.0, 0.0)
        gr = np.einsum('k,ekj->ej', hr, self.xe)
        gs = np.einsum('k,ekj->ej', hs, self.xe)
        return _unit(np.cross(gr, gs))

    def areas(self):
        """Mid-surface area of each element (2x2 Gauss)."""
        A = np.zeros(self.ne)
        for (r, s) in GAUSS2:
            _h, hr, hs = shape4(r, s)
            gr = np.einsum('k,ekj->ej', hr, self.xe)
            gs = np.einsum('k,ekj->ej', hs, self.xe)
            A += np.linalg.norm(np.cross(gr, gs), axis=1)
        return A

    def frames(self):
        """(e1, e2, e3) at each element centre."""
        return local_frame(self.normals())

    # -- loads ------------------------------------------------------------------
    def surface_load(self, traction_fn, per='surface', order=3):
        """Consistent nodal forces (ne, 24) for a distributed load.

        `traction_fn(P, n)` gets the points P (m, 3) and unit normals n (m, 3)
        and returns the traction vector (m, 3) in N per m^2 -- of SURFACE area
        if per == 'surface', of PLAN area if per == 'plan'."""
        pts, w = np.polynomial.legendre.leggauss(order)
        F = np.zeros((self.ne, 24))
        for i, r in enumerate(pts):
            for j, s in enumerate(pts):
                h, hr, hs = shape4(r, s)
                P = np.einsum('k,ekj->ej', h, self.xe)
                gr = np.einsum('k,ekj->ej', hr, self.xe)
                gs = np.einsum('k,ekj->ej', hs, self.xe)
                nvec = np.cross(gr, gs)
                dA = np.linalg.norm(nvec, axis=1)
                if per == 'plan':
                    dA = np.abs(nvec[:, 2])
                n = nvec / np.linalg.norm(nvec, axis=1, keepdims=True)
                tr = np.asarray(traction_fn(P, n), float)
                wgt = w[i] * w[j] * dA
                for k in range(4):
                    F[:, 6 * k:6 * k + 3] += (h[k] * wgt)[:, None] * tr
        return F

    # -- results ----------------------------------------------------------------
    def resultants(self, U):
        """Stress resultants at each element centre from global displacements
        U (ndof,). Returns dict of (ne,) arrays in the element's local frame:
        Nx, Ny, Nxy (N/m), Mx, My, Mxy (N*m/m, + = tension at the bottom),
        Qx, Qy (N/m); and 'frame' (e1, e2, e3)."""
        ue = U[self.dofs]                                   # (ne,24)
        C = self._C()
        sig = {}
        for t in (1.0, -1.0):
            B, frame, _ = self.local_B(0.0, 0.0, t)
            eps = np.einsum('eaj,ej->ea', B, ue)
            sig[t] = np.einsum('eab,eb->ea', C, eps)
        a = self.a
        top, bot = sig[1.0], sig[-1.0]
        mean = 0.5 * (top + bot)
        N = mean[:, :3] * a[:, None]
        M = 0.5 * (bot[:, :3] - top[:, :3]) * (a ** 2 / 6.0)[:, None]
        Q = mean[:, 3:5] * a[:, None]
        return {'Nx': N[:, 0], 'Ny': N[:, 1], 'Nxy': N[:, 2],
                'Mx': M[:, 0], 'My': M[:, 1], 'Mxy': M[:, 2],
                'Qx': Q[:, 0], 'Qy': Q[:, 1], 'frame': frame,
                'sig_top': top[:, :3], 'sig_bot': bot[:, :3]}


# ═══════════════════════════════════════════════════════════════════════════
#  3-D frame element
# ═══════════════════════════════════════════════════════════════════════════
def rect_section(b, h):
    """A, Iy (about local y: depth h is along local z), Iz, J, shear areas
    for a b x h rectangle (b along local y, h along local z)."""
    A = b * h
    Iy = b * h ** 3 / 12.0
    Iz = h * b ** 3 / 12.0
    lo, sh = max(b, h), min(b, h)
    beta = 1.0 / 3.0 - 0.21 * (sh / lo) * (1.0 - (sh / lo) ** 4 / 12.0)
    J = beta * lo * sh ** 3
    return {'A': A, 'Iy': Iy, 'Iz': Iz, 'J': J, 'Asy': A * 5 / 6, 'Asz': A * 5 / 6,
            'b': b, 'h': h}


def beam_axes(xa, xb):
    """Rows: local x (along the beam), y (horizontal), z (up-ish). For a
    vertical member local z is global X."""
    ex = np.asarray(xb, float) - np.asarray(xa, float)
    L = float(np.linalg.norm(ex))
    if L <= 0:
        raise ValueError('A beam element has zero length')
    ex = ex / L
    ref = np.array([0.0, 0.0, 1.0])
    if abs(ex @ ref) > 0.999:
        ref = np.array([1.0, 0.0, 0.0])
        ey = np.cross(ex, ref)
        ey /= np.linalg.norm(ey)
        ez = np.cross(ex, ey)
        # keep local z = global X for a column
        if ez @ ref < 0:
            ey, ez = -ey, -ez
    else:
        ey = np.cross(ref, ex)
        ey /= np.linalg.norm(ey)
        ez = np.cross(ex, ey)
    return np.array([ex, ey, ez]), L


def frame_local_k(E, G, sec, L):
    A, Iy, Iz, J = sec['A'], sec['Iy'], sec['Iz'], sec['J']
    py = 12 * E * Iz / (G * sec['Asy'] * L ** 2)
    pz = 12 * E * Iy / (G * sec['Asz'] * L ** 2)
    k = np.zeros((12, 12))
    k[0, 0] = k[6, 6] = E * A / L
    k[0, 6] = -E * A / L
    k[3, 3] = k[9, 9] = G * J / L
    k[3, 9] = -G * J / L
    cy = E * Iz / (1 + py)
    k[1, 1] = k[7, 7] = 12 * cy / L ** 3
    k[1, 7] = -12 * cy / L ** 3
    k[1, 5] = k[1, 11] = 6 * cy / L ** 2
    k[5, 7] = k[7, 11] = -6 * cy / L ** 2
    k[5, 5] = k[11, 11] = (4 + py) * cy / L
    k[5, 11] = (2 - py) * cy / L
    cz = E * Iy / (1 + pz)
    k[2, 2] = k[8, 8] = 12 * cz / L ** 3
    k[2, 8] = -12 * cz / L ** 3
    k[2, 4] = k[2, 10] = -6 * cz / L ** 2
    k[4, 8] = k[8, 10] = 6 * cz / L ** 2
    k[4, 4] = k[10, 10] = (4 + pz) * cz / L
    k[4, 10] = (2 - pz) * cz / L
    return np.triu(k) + np.triu(k, 1).T


class Frame:
    """One 3-D frame element between nodes a and b, with optional rigid
    offsets (vectors from each node to the beam centroid)."""

    def __init__(self, X, a, b, E, nu, sec, offset=(0.0, 0.0, 0.0), w=(0.0, 0.0, 0.0),
                 tag=''):
        self.a, self.b = int(a), int(b)
        self.E, self.G = E, E / (2 * (1 + nu))
        self.sec = sec
        self.off = np.asarray(offset, float)
        self.w = np.asarray(w, float)          # distributed load, global N/m
        self.tag = tag
        xa = X[self.a] + self.off
        xb = X[self.b] + self.off
        self.xa, self.xb = xa, xb
        self.lam, self.L = beam_axes(xa, xb)
        self.k_loc = frame_local_k(self.E, self.G, sec, self.L)
        T = np.zeros((12, 12))
        for i in range(4):
            T[3 * i:3 * i + 3, 3 * i:3 * i + 3] = self.lam
        O = np.eye(12)
        So = -skew(self.off)
        O[0:3, 3:6] = So
        O[6:9, 9:12] = So
        self.T = T @ O                         # node DOFs -> local centroid DOFs
        self.dofs = np.r_[np.arange(6) + 6 * self.a, np.arange(6) + 6 * self.b]

    def stiffness(self):
        return self.T.T @ self.k_loc @ self.T

    def _feq_local(self, w_global):
        wl = self.lam @ np.asarray(w_global, float)
        L = self.L
        f = np.zeros(12)
        f[0] = f[6] = wl[0] * L / 2
        f[1] = f[7] = wl[1] * L / 2
        f[2] = f[8] = wl[2] * L / 2
        f[5] = wl[1] * L ** 2 / 12
        f[11] = -wl[1] * L ** 2 / 12
        f[4] = -wl[2] * L ** 2 / 12
        f[10] = wl[2] * L ** 2 / 12
        return f, wl

    def load_vector(self, w_global=None):
        """Equivalent nodal loads (global node DOFs) for a uniform load."""
        f, _ = self._feq_local(self.w if w_global is None else w_global)
        return self.T.T @ f

    def end_forces(self, U, w_global=None):
        """Local end forces (12,) acting ON the element, and the local load."""
        d = self.T @ U[self.dofs]
        f_eq, wl = self._feq_local(self.w if w_global is None else w_global)
        return self.k_loc @ d - f_eq, wl

    def internal(self, U, xs=None, w_global=None):
        """Internal forces along the element at stations xs (m from end a):
        N (tension +), Vy, Vz, T, My, Mz in the LOCAL axes, from the free body
        of the part between end a and the cut."""
        f, wl = self.end_forces(U, w_global)
        if xs is None:
            xs = np.array([0.0, 0.5 * self.L, self.L])
        xs = np.asarray(xs, float)
        F1, M1 = f[0:3], f[3:6]
        Fint = -(F1[None, :] + np.outer(xs, wl))
        Mint = -(M1[None, :]
                 + np.stack([0 * xs, xs * F1[2], -xs * F1[1]], 1)
                 + np.stack([0 * xs, xs ** 2 * wl[2] / 2, -xs ** 2 * wl[1] / 2], 1))
        return {'x': xs, 'N': Fint[:, 0], 'Vy': Fint[:, 1], 'Vz': Fint[:, 2],
                'T': Mint[:, 0], 'My': Mint[:, 1], 'Mz': Mint[:, 2]}


# ═══════════════════════════════════════════════════════════════════════════
#  Assembly and solution
# ═══════════════════════════════════════════════════════════════════════════
def assemble(nn, shells=None, frames=(), k_shell=None):
    """Global sparse stiffness (CSC). `k_shell` may pass precomputed shell
    element matrices to avoid recomputing them."""
    ndof = NDOF * nn
    rows, cols, vals = [], [], []
    if shells is not None and shells.ne:
        ke = shells.stiffness() if k_shell is None else k_shell
        d = shells.dofs
        rows.append(np.repeat(d, 24, axis=1).ravel())
        cols.append(np.tile(d, (1, 24)).ravel())
        vals.append(ke.ravel())
    for fr in frames:
        kf = fr.stiffness()
        rows.append(np.repeat(fr.dofs, 12))
        cols.append(np.tile(fr.dofs, 12))
        vals.append(kf.ravel())
    if not rows:
        return sp.csc_matrix((ndof, ndof))
    K = sp.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                      shape=(ndof, ndof)).tocsc()
    K.sum_duplicates()
    return K


DOF_NAMES = ('X', 'Y', 'Z', 'rotation about X', 'rotation about Y', 'rotation about Z')


def solve(K, F, fixed, X=None, check=True, tol=1e-10):
    """Solve K U = F with the DOFs in `fixed` held at zero.

    F may be (ndof,) or (ndof, ncases) -- one factorisation serves every
    load case. Before trusting the answer, the smallest eigenvalue of the
    diagonally-scaled free stiffness is estimated by inverse iteration on
    the factorisation (cheap: a few extra back-substitutions). A structure
    that can move freely has an eigenvalue at round-off level; it is refused
    with MechanismError naming the node and direction that move most,
    instead of returning an arbitrary, very large answer.

    Returns (U, R): displacements and reactions, each shaped like F."""
    ndof = K.shape[0]
    F2 = np.asarray(F, float)
    single = F2.ndim == 1
    if single:
        F2 = F2[:, None]
    mask = np.ones(ndof, bool)
    mask[np.asarray(sorted(set(int(i) for i in fixed)), int)] = False
    free = np.nonzero(mask)[0]
    Kff = K[free][:, free].tocsc()
    diag = Kff.diagonal()
    if np.any(diag <= 0):
        i = free[int(np.argmin(diag))]
        raise _mechanism(i, X, 'nothing resists it at all')
    try:
        lu = spla.splu(Kff)
    except RuntimeError:
        i = free[int(np.argmin(diag))]
        raise _mechanism(i, X, 'the stiffness matrix is exactly singular')
    if check and len(free):
        dsc = 1.0 / np.sqrt(diag)
        rng = np.random.default_rng(1)
        # (1) A structure that can move does NOT always make the sparse
        # factorisation fail: SuperLU pivots past a round-off-sized pivot and
        # returns a factorisation that is simply wrong. So first ask whether
        # the factorisation solves anything: solve for a random load and
        # measure the residual. A sound system gives ~1e-12; one with a free
        # motion gives O(1) or worse, and its garbage solution points along
        # the free motion, which names the node that moves.
        b = rng.standard_normal(len(free))
        xb = lu.solve(b)
        rres = np.linalg.norm(Kff @ xb - b) / np.linalg.norm(b) if np.all(np.isfinite(xb)) else np.inf
        if not np.isfinite(rres) or rres > 1e-6:
            i = free[int(np.argmax(np.abs(np.nan_to_num(xb * np.sqrt(diag)))))]
            raise _mechanism(i, X, f'the equations cannot be solved (residual {rres:.1e})')
        # (2) Nearly-free motions the factorisation CAN handle: estimate the
        # smallest eigenvalue of the diagonally scaled system.
        v = rng.standard_normal(len(free))
        v /= np.linalg.norm(v)
        lam = None
        for _it in range(40):
            w = dsc * lu.solve(dsc * v)
            nw = np.linalg.norm(w)
            if not np.isfinite(nw) or nw == 0:
                break
            lam_new = 1.0 / nw
            v = w / nw
            if lam is not None and abs(lam_new - lam) <= 1e-3 * lam:
                lam = lam_new
                break
            lam = lam_new
        if lam is None or not np.isfinite(lam) or lam < tol:
            i = free[int(np.argmax(np.abs(v * dsc)))]
            raise _mechanism(i, X, f'smallest scaled stiffness {lam:.1e}')
    Uf = lu.solve(F2[free])
    if not np.all(np.isfinite(Uf)):
        raise MechanismError('The solution is not finite; the structure is unstable.')
    U = np.zeros_like(F2)
    U[free] = Uf
    R = K @ U - F2
    R[free] = 0.0
    if single:
        return U[:, 0], R[:, 0]
    return U, R


def _mechanism(dof, X, detail):
    node, comp = divmod(int(dof), NDOF)
    where = ''
    if X is not None and node < len(X):
        x, y, z = X[node]
        where = f' near (x={x:.2f}, y={y:.2f}, z={z:.2f} m)'
    what = DOF_NAMES[comp]
    hint = (f'The structure can move freely -- the largest free motion is '
            f'{"a translation in " if comp < 3 else "a "}{what} at node {node}{where}. '
            f'Add a support that holds that motion, or connect that part.')
    return MechanismError(f'The structure is a mechanism ({detail}). ' + hint,
                          hint=hint, node=node, dof=comp)
