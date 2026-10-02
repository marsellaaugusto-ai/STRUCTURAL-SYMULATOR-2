"""Buckling, as a demonstration: when does this truss buckle, and how?
The Truss tab's 2D reduction of apps/stereo/stereo_buckling.

  * BUCKLING MODES -- linear (bifurcation) buckling. Under the loads as they
    stand every rod carries an axial force N; a compressed rod gets less
    stiff sideways and a tensioned one stiffer, by the geometric stiffness
    K_G(N). The truss buckles at the load factor lambda where K + lambda K_G
    stops being positive definite: K phi = -lambda K_G phi. The lowest
    lambdas read "it buckles at 3.7 times this load"; the phis are the
    shapes it buckles into.

  * THE SECOND-ORDER LOAD-DEFLECTION CURVE -- (K + lambda K_G) u = lambda F
    with a small initial bow, stepped up in lambda: it bends away from the
    straight first-order line and runs off as lambda nears the buckling
    factor -- the amplification every second-order design rule is about.

Both are demonstrations. The CIRSOC 301 rod checks stay first-order;
nothing here changes a utilisation.

THE MODEL. One element per rod finds the truss buckling as a whole but
cannot bow a rod between its joints. So every rod is cut in two at
mid-length for this analysis only, the halves being beam-column elements
(the consistent geometric stiffness, P/(30 L) times the usual matrix):
  - a RIGID rod's halves join the end nodes' own rotations, as in the solve;
  - a PIN rod's halves end in a hinge of their own at each joint -- private
    rotations no other rod shares -- so it is still pinned there, yet can
    bow. Two elements put a pinned column within 1 % of pi^2 EI / L^2.

In the plane only: buckling out of the truss's plane is the rod check's job
(CIRSOC 301 E3 on the minor radius of gyration). Imperfections, residual
stresses and inelasticity are not modelled, so lambda is the ELASTIC
buckling load of the ideal truss -- an upper bound. Kept free of Tk.
"""
import math

import numpy as np

from common import PX_PER_M

DENSE_MAX_DOF = 3000
IMPERFECTION = 1.0 / 1000.0      # initial bow, of the buckling rod's length


def _elastic_local(E, A, I, L):
    """6x6 local stiffness, DOFs (u1, v1, t1, u2, v2, t2)."""
    a, b = E * A / L, E * I / L ** 3
    k = np.zeros((6, 6))
    k[0, 0] = k[3, 3] = a
    k[0, 3] = k[3, 0] = -a
    for (i, j), v in {(1, 1): 12, (4, 4): 12, (1, 4): -12,
                      (1, 2): 6 * L, (1, 5): 6 * L,
                      (2, 4): -6 * L, (4, 5): -6 * L,
                      (2, 2): 4 * L * L, (5, 5): 4 * L * L,
                      (2, 5): 2 * L * L}.items():
        k[i, j] = k[j, i] = b * v
    return k


def _geometric_local(P, L):
    """6x6 geometric stiffness under axial force P (N, tension +)."""
    c = P / (30.0 * L)
    g = np.zeros((6, 6))
    for (i, j), v in {(1, 1): 36, (4, 4): 36, (1, 4): -36,
                      (1, 2): 3 * L, (1, 5): 3 * L,
                      (2, 4): -3 * L, (4, 5): -3 * L,
                      (2, 2): 4 * L * L, (5, 5): 4 * L * L,
                      (2, 5): -L * L}.items():
        g[i, j] = g[j, i] = c * v
    return g


def _rotation(c, s):
    t = np.zeros((6, 6))
    for o in (0, 3):
        t[o:o + 2, o:o + 2] = [[c, s], [-s, c]]
        t[o + 2, o + 2] = 1.0
    return t


class Model:
    """The truss cut for buckling: every rod in two, pin rods hinged.

    Coordinates are metres in the canvas frame (y down); every node has
    (ux, uy), a node a rigid rod or a fixed support touches has a shared
    rotation, every rod's middle has (ux, uy, rot), and a pin rod has a
    private rotation at each end."""

    def __init__(self, nodes, rods, supports):
        self.nodes_m = [(x / PX_PER_M, y / PX_PER_M) for x, y in nodes]
        self.rods = rods
        n = 0
        self.node_dof = []
        for _ in nodes:
            self.node_dof.append([n, n + 1, None])
            n += 2
        rot_at = {s['node'] for s in supports if s['type'] == 'fixed'}
        for r in rods:
            if r.get('conn', 'pin') == 'rigid':
                rot_at |= {r['a'], r['b']}
        for i in sorted(rot_at):
            self.node_dof[i][2] = n
            n += 1
        self.elements = []        # (dof list of 6, E, A, I, c, s, L, rod)
        self.mid_dof = []
        for k, r in enumerate(rods):
            (xa, ya), (xb, yb) = self.nodes_m[r['a']], self.nodes_m[r['b']]
            L = math.hypot(xb - xa, yb - ya)
            c, s = (xb - xa) / L, (yb - ya) / L
            mid = [n, n + 1, n + 2]
            n += 3
            self.mid_dof.append(mid)
            ends = []
            for end in (r['a'], r['b']):
                ux, uy, rot = self.node_dof[end]
                if r.get('conn', 'pin') != 'rigid':
                    rot = n               # a hinge of its own
                    n += 1
                ends.append([ux, uy, rot])
            E = r['E'] * 1e9
            A = r['A'] * 1e-4
            I = max(float(r.get('I') or 0.0), 1e-6) * 1e-8
            self.elements.append((ends[0] + mid, E, A, I, c, s, L / 2, k))
            self.elements.append((mid + ends[1], E, A, I, c, s, L / 2, k))
        self.ndof = n
        fixed = set()
        for sp in supports:
            ux, uy, rot = self.node_dof[sp['node']]
            if sp['type'] in ('pin', 'rollerY', 'fixed'):
                fixed.add(ux)
            if sp['type'] in ('pin', 'rollerX', 'fixed'):
                fixed.add(uy)
            if sp['type'] == 'fixed' and rot is not None:
                fixed.add(rot)
        self.free = [d for d in range(n) if d not in fixed]

    def assemble(self, N_kN):
        K = np.zeros((self.ndof, self.ndof))
        KG = np.zeros((self.ndof, self.ndof))
        for dofs, E, A, I, c, s, L, k in self.elements:
            T = _rotation(c, s)
            ke = T.T @ _elastic_local(E, A, I, L) @ T
            kg = T.T @ _geometric_local(N_kN[k] * 1e3, L) @ T
            ix = np.ix_(dofs, dofs)
            K[ix] += ke
            KG[ix] += kg
        return K, KG

    def load_vector(self, loads):
        F = np.zeros(self.ndof)
        for ld in loads:
            ux, uy, _ = self.node_dof[ld['node']]
            F[ux] += ld['fx'] * 1e3
            F[uy] += ld['fy'] * 1e3
        return F

    def shape(self, full):
        """(node translations, rod-middle translations), metres."""
        tn = [(full[d[0]], full[d[1]]) for d in self.node_dof]
        tm = [(full[d[0]], full[d[1]]) for d in self.mid_dof]
        return tn, tm


def _bow(model, full, k):
    """How far rod k's middle has moved off the line between its ends,
    sideways to the rod."""
    tn, tm = model.shape(full)
    r = model.rods[k]
    (ax, ay), (bx, by) = tn[r['a']], tn[r['b']]
    dx, dy = tm[k][0] - (ax + bx) / 2, tm[k][1] - (ay + by) / 2
    (xa, ya), (xb, yb) = model.nodes_m[r['a']], model.nodes_m[r['b']]
    L = math.hypot(xb - xa, yb - ya)
    ex, ey = (xb - xa) / L, (yb - ya) / L
    return abs(-dx * ey + dy * ex)


def _peak(model, full):
    """(size, ('node', n) | ('mid', k)) of the largest translation."""
    tn, tm = model.shape(full)
    best = (0.0, None)
    for n, (x, y) in enumerate(tn):
        if math.hypot(x, y) > best[0]:
            best = (math.hypot(x, y), ('node', n))
    for k, (x, y) in enumerate(tm):
        if math.hypot(x, y) > best[0]:
            best = (math.hypot(x, y), ('mid', k))
    return best


def _setup(nodes, rods, supports, results):
    if not nodes or not rods:
        return {'error': 'Nothing is built yet.'}
    if results is None:
        return {'error': '▶ Analyze first: buckling starts from the rod '
                         'forces of a solved truss.'}
    N = [rr['force'] for rr in results['rod_res']]
    if min(N, default=0.0) >= -1e-6:
        return {'error': 'No rod is in compression under this load, so '
                         'nothing can buckle.'}
    model = Model(nodes, rods, supports)
    K, KG = model.assemble(N)
    f = np.asarray(model.free)
    if len(f) > DENSE_MAX_DOF:
        return {'error': 'Too big to analyse for buckling here (%d degrees '
                         'of freedom once every rod is cut in two).' % len(f)}
    return model, K[np.ix_(f, f)], KG[np.ix_(f, f)], f


def _lowest(Kf, KGf, k):
    """(lambdas ascending, vectors as columns) of K phi = -lambda K_G phi,
    positive lambdas only."""
    import scipy.linalg as sla
    nf = Kf.shape[0]
    k = max(1, min(k, nf - 1))
    mu, vec = sla.eigh(-KGf, Kf, subset_by_index=[nf - k, nf - 1])
    keep = [j for j in np.argsort(-mu) if mu[j] > 1e-12]
    return [1.0 / float(mu[j]) for j in keep], vec[:, keep]


def buckling(nodes, rods, supports, results, n_modes=3):
    """{'factors': [lambda, ...] ascending, 'modes': [{'nodes': [(dx, dy)],
    'mids': [(dx, dy)], 'peak': ('node', n) | ('mid', k)}]} with the
    largest translation of each mode 1 -- or {'error': text}."""
    got = _setup(nodes, rods, supports, results)
    if isinstance(got, dict):
        return got
    model, Kf, KGf, f = got
    try:
        lams, vec = _lowest(Kf, KGf, n_modes)
    except Exception as exc:                    # noqa: BLE001
        return {'error': 'The buckling eigenproblem did not solve (%s). '
                         'Does the truss stand under ▶ Analyze?' % exc}
    factors, modes = [], []
    full = np.zeros(model.ndof)
    for j, lam in enumerate(lams):
        full[:] = 0.0
        full[f] = vec[:, j]
        size, where = _peak(model, full)
        if size <= 0:
            continue
        tn, tm = model.shape(full)
        factors.append(lam)
        modes.append({'nodes': [(x / size, y / size) for x, y in tn],
                      'mids': [(x / size, y / size) for x, y in tm],
                      'peak': where})
    if not factors:
        return {'error': 'No buckling load was found: the compressed rods '
                         'are held stiffly enough that nothing buckles.'}
    return {'factors': factors, 'modes': modes}


def load_deflection(nodes, rods, supports, loads, results, steps=24):
    """Up to 95 % of the buckling factor: 'bow_mm', the point that buckles
    first (the peak of mode 1) given an initial bow of L/1000 in that
    shape; 'node_mm', the node that moves most, second-order; 'first_mm',
    the same node first-order (a straight line). With 'factors',
    'lambda_cr', 'where', 'bow0_mm' -- or {'error': text}. Nodal loads only:
    a span load on a rigid rod still sets the rod forces, but is not in
    the stepped load."""
    got = _setup(nodes, rods, supports, results)
    if isinstance(got, dict):
        return got
    model, Kf, KGf, f = got
    try:
        lams, vec = _lowest(Kf, KGf, 1)
    except Exception as exc:                    # noqa: BLE001
        return {'error': 'The buckling eigenproblem did not solve (%s).' % exc}
    if not lams:
        return {'error': 'Nothing buckles under this load.'}
    lcr = lams[0]
    full = np.zeros(model.ndof)
    full[f] = vec[:, 0]
    _size, where = _peak(model, full)
    if where[0] == 'mid':
        size = _bow(model, full, where[1])
        r = rods[where[1]]
        (xa, ya), (xb, yb) = model.nodes_m[r['a']], model.nodes_m[r['b']]
        L = math.hypot(xb - xa, yb - ya)
    else:
        tn, _tm = model.shape(full)
        size = math.hypot(*tn[where[1]])
        L = max(math.dist(model.nodes_m[r['a']], model.nodes_m[r['b']])
                for r in rods if where[1] in (r['a'], r['b']))
    if size <= 0:
        return {'error': 'The first buckling shape has no bow to grow.'}
    bow0 = IMPERFECTION * L
    u0 = vec[:, 0] * (bow0 / size)
    F = model.load_vector(loads)[f]
    first = np.linalg.solve(Kf, F)
    full[:] = 0.0
    full[f] = first
    tn, _tm = model.shape(full)
    mags = [math.hypot(x, y) for x, y in tn]
    node = int(np.argmax(mags))
    unit = mags[node]
    g0 = KGf @ u0

    def measure(u):
        full[:] = 0.0
        full[f] = u
        if where[0] == 'mid':
            return _bow(model, full, where[1])
        return math.hypot(*model.shape(full)[0][where[1]])

    out = {'factors': [], 'bow_mm': [], 'node_mm': [], 'first_mm': [],
           'lambda_cr': lcr, 'node': node, 'where': where,
           'bow0_mm': 1000.0 * bow0}
    top = 0.95 * lcr
    for s in range(steps + 1):
        lam = top * s / steps
        try:
            u = np.linalg.solve(Kf + lam * KGf, lam * F - lam * g0)
        except np.linalg.LinAlgError:
            break
        out['factors'].append(lam)
        out['bow_mm'].append(1000.0 * measure(u + u0))
        full[:] = 0.0
        full[f] = u
        out['node_mm'].append(1000.0 * math.hypot(*model.shape(full)[0][node]))
        out['first_mm'].append(1000.0 * lam * unit)
    return out
