"""Buckling, as a demonstration: when does this structure buckle, and how?

Two of the things MASTAN2 and Arcade teach with, on the model in the tab:

  * BUCKLING MODES -- the linear (bifurcation) buckling analysis. Under the
    loads as they stand every rod carries an axial force N; a compressed rod
    gets less stiff sideways and a tensioned one stiffer, by the GEOMETRIC
    stiffness K_G(N). The structure buckles at the load factor lambda where
    K + lambda K_G stops being positive definite: the eigenproblem
    K phi = -lambda K_G phi. Its lowest lambdas are "it buckles at 3.4 times
    this load", and the phis are the shapes it buckles into.

  * THE SECOND-ORDER LOAD-DEFLECTION CURVE -- (K + lambda K_G) u = lambda F,
    stepped up in lambda. A first-order answer grows in proportion to the
    load; this one bends away from that line and runs off to infinity as
    lambda nears the buckling factor -- the amplification every
    second-order design rule is about.

Both are demonstrations. The code checks (stereo_checks) stay first-order,
as before; nothing here changes a utilisation.

THE MODEL. One element per rod finds the structure buckling as a whole but
cannot bow a rod between its joints, and over-estimates a rod's own Euler
load by 22 % where it can. So every rod is cut in two at mid-length for
this analysis (only), the halves being beam elements:
  - a RIGID rod's halves join the end nodes' own rotations, as in the solve;
  - a PIN rod's halves end in a hinge of their own at each joint -- private
    rotations no other rod shares -- so the rod is still pinned there, yet
    can bow. (A tiny spring about the rod's own axis at mid-length holds its
    free twist, which plays no part in flexural buckling.)
Two elements put a pinned column's Euler load within 1 % of pi^2 EI / L^2.

What it is NOT: imperfections, residual stresses, inelasticity and local
buckling of the section are not modelled, so lambda is the ELASTIC
buckling load of the ideal structure -- an upper bound, which is what
CIRSOC 301 E3's Fe is for one rod. Kept free of Tk.
"""
import math

import numpy as np

from apps.stereo import stereo_math as sm

DENSE_MAX_DOF = 1500
MAX_DOF = 80000
TWIST_SPRING = 1e-3          # x GJ/L, about the rod's axis at its middle


def _rotation(dx, dy, dz, L):
    lx, ly, lz = sm._local_axes(dx, dy, dz, L)
    return sm._rotation_12(lx, ly, lz)


def _geometric_local(P, L):
    """12x12 geometric stiffness of a beam element under axial force P (N,
    tension +), DOF order and signs as stereo_math._rigid_local_stiffness."""
    c = P / (30.0 * L)
    g = np.zeros((12, 12))
    # bending in local x-y (uy, rz)
    for (i, j), v in {(1, 1): 36, (7, 7): 36, (1, 7): -36,
                      (1, 5): 3 * L, (1, 11): 3 * L,
                      (5, 7): -3 * L, (7, 11): -3 * L,
                      (5, 5): 4 * L * L, (11, 11): 4 * L * L,
                      (5, 11): -L * L}.items():
        g[i, j] = g[j, i] = c * v
    # bending in local x-z (uz, ry)
    for (i, j), v in {(2, 2): 36, (8, 8): 36, (2, 8): -36,
                      (2, 4): -3 * L, (2, 10): -3 * L,
                      (4, 8): 3 * L, (8, 10): 3 * L,
                      (4, 4): 4 * L * L, (10, 10): 4 * L * L,
                      (4, 10): -L * L}.items():
        g[i, j] = g[j, i] = c * v
    return g


class Model:
    """The structure cut for buckling: every rod in two, pin rods hinged.

    `dof` maps each original node to its six global DOFs (rotations always
    present here), `mid` each rod to its middle node's six, and `hinge`
    (rod, end) to a pin rod's private rotations at that end."""

    def __init__(self, nodes, members, supports, skip=()):
        self.nodes, self.members = nodes, members
        self.skip = set(skip)
        n = 0
        self.dof = []
        for _ in nodes:
            self.dof.append(list(range(n, n + 6)))
            n += 6
        self.mid, self.hinge = {}, {}
        for i, m in enumerate(members):
            if i in self.skip or sm.member_vector(nodes, m)[3] < 1e-9:
                continue
            self.mid[i] = list(range(n, n + 6))
            n += 6
            if m.get('conn', 'pin') != 'rigid':
                for end in ('a', 'b'):
                    self.hinge[(i, end)] = list(range(n, n + 3))
                    n += 3
        self.ndof = n
        fixed = set()
        for sp in supports:
            r = sm.support_restraints(sp)
            for k, d in enumerate(sm.DOF_NAMES):
                if r[d]:
                    fixed.add(self.dof[sp['node']][k])
        # A node no rigid rod reaches has no rotational stiffness at all in
        # this model (its pin rods turn on hinges of their own): its
        # rotations are not degrees of freedom of anything, and stay out.
        turned = set()
        for i, m in enumerate(members):
            if i in self.mid and m.get('conn', 'pin') == 'rigid':
                turned.update((m['a'], m['b']))
        for k in range(len(nodes)):
            if k not in turned:
                fixed.update(self.dof[k][3:])
        self.free = [d for d in range(n) if d not in fixed]

    def halves(self, i):
        """[(dofs12, dx, dy, dz, L/2)] for rod i's two halves."""
        m = self.members[i]
        dx, dy, dz, L = sm.member_vector(self.nodes, m)
        mid = self.mid[i]
        out = []
        for end, first in (('a', True), ('b', False)):
            node = self.dof[m[end]]
            rot = self.hinge.get((i, end), node[3:])
            end12 = node[:3] + list(rot)
            idx = end12 + mid if first else mid + end12
            out.append((idx, dx, dy, dz, L / 2.0))
        return out

    def assemble(self, axial_N=None):
        """(K, KG) over every DOF, as scipy sparse COO arrays; KG is None
        without axial forces. axial_N[i] in N, tension +."""
        rows, cols, kv, gv = [], [], [], []
        for i, m in enumerate(self.members):
            if i not in self.mid:
                continue
            E, A = m['E'], m['A']
            I = m.get('I', 0.0) or 0.0
            if m.get('conn', 'pin') != 'rigid' and I <= 0:
                I = max(A * float(m.get('r_gyr', 0.0) or 0.0) ** 2, 1e-6)
            J = m.get('J', I) or I
            P = 0.0 if axial_N is None else float(axial_N[i])
            for idx, dx, dy, dz, h in self.halves(i):
                T = _rotation(dx, dy, dz, 2.0 * h)
                k = sm._rigid_local_stiffness(E, A, I, J, h,
                                              Iw_cm4=m.get('Iw'))
                ke = T.T @ k @ T
                ge = T.T @ _geometric_local(P, h) @ T if axial_N is not None \
                    else None
                rows.extend(np.repeat(idx, 12))
                cols.extend(np.tile(idx, 12))
                kv.extend(ke.ravel())
                gv.extend(ge.ravel() if ge is not None else np.zeros(144))
            # hold the rod's free twist about its own axis
            dx, dy, dz, L = sm.member_vector(self.nodes, m)
            e = np.array([dx, dy, dz]) / L
            G = m['E'] * 1e9 / (2.0 * (1.0 + sm.DEFAULT_NU))
            kt = TWIST_SPRING * G * J * 1e-8 / L
            r = self.mid[i][3:]
            blk = kt * np.outer(e, e)
            rows.extend(np.repeat(r, 3))
            cols.extend(np.tile(r, 3))
            kv.extend(blk.ravel())
            gv.extend(np.zeros(9))
        import scipy.sparse as sps
        shape = (self.ndof, self.ndof)
        K = sps.coo_matrix((kv, (rows, cols)), shape=shape).tocsr()
        KG = (sps.coo_matrix((gv, (rows, cols)), shape=shape).tocsr()
              if axial_N is not None else None)
        return K, KG

    def load_vector(self, loads):
        F = np.zeros(self.ndof)
        for ld in loads:
            d = self.dof[ld['node']]
            for k, key in enumerate(('fx', 'fy', 'fz', 'mx', 'my', 'mz')):
                F[d[k]] += ld.get(key, 0.0) * 1e3
        return F

    def translations(self, vec):
        """Per original node (dx, dy, dz) and per rod the middle's, metres."""
        nodes = [tuple(vec[d[k]] for k in range(3)) for d in self.dof]
        mids = {i: tuple(vec[d[k]] for k in range(3))
                for i, d in self.mid.items()}
        return nodes, mids


def _solve_first_order(nodes, members, loads, supports, panels, member_loads):
    res, err = sm.analyze(nodes, members, loads, supports, panels=panels,
                          member_loads=member_loads)
    if res is None:
        return None, err
    return res, None


def _skip(members, res):
    """Rods that carry nothing in this model: slack tension-only rods."""
    return {i for i, (m, r) in enumerate(zip(members, res['member_res']))
            if m.get('tension_only') and abs(r.get('N', 0.0)) < 1e-9}


def _reduced(model, K, KG):
    f = np.asarray(model.free)
    Kf = K[f][:, f]
    KGf = KG[f][:, f] if KG is not None else None
    return Kf, KGf


def _setup(nodes, members, loads, supports, panels, member_loads, results):
    """(model, Kf, KGf, free index array, results) or {'error': text}."""
    if not nodes or not members:
        return {'error': 'Nothing is built yet.'}
    res = results
    if res is None:
        res, err = _solve_first_order(nodes, members, loads, supports, panels,
                                      member_loads)
        if res is None:
            return {'error': err}
    N = [r.get('N', 0.0) * 1e3 for r in res['member_res']]
    if min(N, default=0.0) >= -1e-6:
        return {'error': 'No rod is in compression under this load, so '
                         'nothing can buckle.'}
    model = Model(nodes, members, supports, skip=_skip(members, res))
    if len(model.free) > MAX_DOF:
        return {'error': 'Too big to analyse for buckling here (%d degrees '
                         'of freedom once every rod is cut in two).'
                         % len(model.free)}
    K, KG = model.assemble(N)
    Kf, KGf = _reduced(model, K, KG)
    return model, Kf, KGf, np.asarray(model.free), res


def _lowest(Kf, KGf, k):
    """(lambdas ascending, vectors as columns) of K phi = -lambda K_G phi,
    positive lambdas only."""
    nf = Kf.shape[0]
    k = max(1, min(k, nf - 2))
    if nf <= DENSE_MAX_DOF:
        import scipy.linalg as sla
        mu, vec = sla.eigh(-KGf.toarray(), Kf.toarray(),
                           subset_by_index=[nf - k, nf - 1])
    else:
        # K once factorised, then the few largest mu of K^-1 (-K_G):
        # ARPACK on that operator needs a handful of back-substitutions,
        # where the generalised form crawled for minutes.
        import scipy.sparse.linalg as spla
        lu = spla.splu(Kf.tocsc())
        A = (-KGf).tocsr()
        op = spla.LinearOperator((nf, nf), matvec=lambda x: lu.solve(A @ x),
                                 dtype=float)
        mu, vec = spla.eigs(op, k=k, which='LR', tol=1e-8)
        mu, vec = np.real(mu), np.real(vec)
    keep = [j for j in np.argsort(-mu) if mu[j] > 1e-12]
    return [1.0 / float(mu[j]) for j in keep], vec[:, keep]


def _peak(model, full):
    """(size, where): the largest translation in a DOF vector, at a node
    ('node', n) or a rod's middle ('mid', i)."""
    tn, tm = model.translations(full)
    best = (0.0, None)
    for n, t in enumerate(tn):
        v = math.sqrt(sum(c * c for c in t))
        if v > best[0]:
            best = (v, ('node', n))
    for i, t in tm.items():
        v = math.sqrt(sum(c * c for c in t))
        if v > best[0]:
            best = (v, ('mid', i))
    return best


def _at(model, full, where):
    """How far `where` has moved: a node's whole movement, or a rod's BOW
    -- its middle's movement off the straight line between its two ends,
    sideways to the rod -- which is what buckling of the rod itself is."""
    tn, tm = model.translations(full)
    if where[0] == 'node':
        return math.sqrt(sum(c * c for c in tn[where[1]]))
    i = where[1]
    m = model.members[i]
    a, b = np.array(tn[m['a']]), np.array(tn[m['b']])
    d = np.array(tm[i]) - (a + b) / 2.0
    dx, dy, dz, L = sm.member_vector(model.nodes, m)
    e = np.array([dx, dy, dz]) / L
    return float(np.linalg.norm(d - (d @ e) * e))


def buckling(nodes, members, loads, supports, panels=None, member_loads=None,
             n_modes=3, results=None):
    """{'factors': [lambda...] ascending, 'modes': [{'nodes': [...],
    'mids': {...}, 'peak': ('node', n) | ('mid', i)} ...] (translations,
    the largest 1), 'ndof': n} -- or {'error': text}. `results` reuses a
    first-order solve of these loads."""
    got = _setup(nodes, members, loads, supports, panels, member_loads,
                 results)
    if isinstance(got, dict):
        return got
    model, Kf, KGf, f, _res = got
    try:
        lams, vec = _lowest(Kf, KGf, n_modes)
    except Exception as exc:                    # noqa: BLE001
        return {'error': 'The buckling eigenproblem did not solve (%s). '
                         'Is the model stable under ▶ Analyze?' % exc}
    factors, modes = [], []
    full = np.zeros(model.ndof)
    for j, lam in enumerate(lams):
        full[:] = 0.0
        full[f] = vec[:, j]
        size, where = _peak(model, full)
        if size <= 0:
            continue
        tn, tm = model.translations(full)
        factors.append(lam)
        modes.append({'nodes': [tuple(c / size for c in t) for t in tn],
                      'mids': {i: tuple(c / size for c in t)
                               for i, t in tm.items()},
                      'peak': where})
    if not factors:
        return {'error': 'No buckling load was found: the compressed rods '
                         'are held stiffly enough that nothing buckles.'}
    return {'factors': factors, 'modes': modes, 'ndof': Kf.shape[0]}


IMPERFECTION = 1.0 / 1000.0    # of the buckling rod's length (L/1000)


def load_deflection(nodes, members, loads, supports, panels=None,
                    member_loads=None, results=None, steps=24):
    """The second-order curves, against the load factor lambda up to 95 %
    of the buckling factor:

      'bow_mm'    the point that buckles first (the peak of mode 1), given
                  an initial bow of L/1000 in the shape of that mode -- it
                  grows as (lambda/lcr) / (1 - lambda/lcr) and runs away;
      'node_mm'   the node that moves most under the load, second-order,
      'first_mm'  the same node first-order: a straight line.

    (K + lambda K_G) u = lambda F - lambda K_G u0, u0 the initial bow.
    Returns those lists with 'factors', 'lambda_cr', 'node', 'where',
    'bow0_mm' -- or {'error': text}."""
    got = _setup(nodes, members, loads, supports, panels, member_loads,
                 results)
    if isinstance(got, dict):
        return got
    model, Kf, KGf, f, _res = got
    try:
        lams, vec = _lowest(Kf, KGf, 1)
    except Exception as exc:                    # noqa: BLE001
        return {'error': 'The buckling eigenproblem did not solve (%s).'
                         % exc}
    if not lams:
        return {'error': 'Nothing buckles under this load.'}
    lcr = lams[0]
    full = np.zeros(model.ndof)
    full[f] = vec[:, 0]
    _size, where = _peak(model, full)
    size = _at(model, full, where)
    if size <= 0:
        return {'error': 'The first buckling shape has no bow to grow.'}
    if where[0] == 'mid':
        L = sm.member_vector(nodes, members[where[1]])[3]
    else:
        L = max(sm.member_vector(nodes, m)[3] for m in members
                if where[1] in (m['a'], m['b']))
    bow0 = IMPERFECTION * L
    u0 = vec[:, 0] * (bow0 / size)
    if member_loads:
        from apps.stereo import stereo_member_loads as mloads
        loads = list(loads) + mloads.equivalent_nodal_loads(nodes, members,
                                                            member_loads)
    F = model.load_vector(loads)[f]
    import scipy.sparse.linalg as spla
    first = spla.spsolve(Kf.tocsc(), F)
    full[:] = 0.0
    full[f] = first
    tn, _tm = model.translations(full)
    mags = [math.sqrt(sum(c * c for c in t)) for t in tn]
    node = int(np.argmax(mags))
    unit = mags[node]
    g0 = KGf @ u0
    out = {'factors': [], 'bow_mm': [], 'node_mm': [], 'first_mm': [],
           'lambda_cr': lcr, 'node': node, 'where': where,
           'bow0_mm': 1000.0 * bow0}
    top = 0.95 * lcr
    for s in range(steps + 1):
        lam = top * s / steps
        try:
            u = spla.spsolve((Kf + lam * KGf).tocsc(), lam * F - lam * g0)
        except Exception:                       # noqa: BLE001
            break
        if not np.all(np.isfinite(u)):
            break
        full[:] = 0.0
        full[f] = u + u0
        out['factors'].append(lam)
        out['bow_mm'].append(1000.0 * _at(model, full, where))
        full[:] = 0.0
        full[f] = u
        out['node_mm'].append(1000.0 * _at(model, full, ('node', node)))
        out['first_mm'].append(1000.0 * lam * unit)
    return out
