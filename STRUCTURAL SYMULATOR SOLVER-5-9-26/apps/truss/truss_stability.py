"""Can this truss stand, and is it determinate? Kept free of Tk.

Two questions a student asks before trusting any force in a truss:

  * INDETERMINACY. Maxwell's count -- members + reactions - 2 x joints for a
    pin-jointed truss -- generalised to the rods this tab has: a pin rod
    has one deformation (it stretches), a rigid rod three (it stretches and
    bends at both ends), a shear panel one. The count can be fooled: a
    truss can have "enough" rods with two of them in the wrong place. So
    the count is corrected by the rank of the stiffness matrix:

        mechanisms  k = free DOF - rank(K_free)
        degree      s = (deformation modes - free DOF) + k

    k > 0 means it moves (whatever the count says); otherwise s = 0 is
    statically determinate and s > 0 indeterminate to degree s.

  * HOW IT MOVES, when it cannot stand: the null vector of K_free, sorted
    into a whole-body motion (a missing support: it slides or turns as one
    piece) or an internal one (a missing diagonal, a joint held by one rod,
    a node that belongs to nothing), for the canvas to animate.

The stiffness here is assembled with the same element rules as
truss_math.analyze (tests/test_truss_stability.py checks that both give the
same displacements), so this module and the solver never disagree about
what is stiff.
"""
import math

import numpy as np

from common import PX_PER_M
from .truss_math import plate_geometry, plate_material, plate_stiffness

# A null-space eigenvalue of the Jacobi-scaled stiffness is below this
# fraction of the largest. Scaling first keeps EA/L and EI/L^3 terms, which
# differ by orders of magnitude, from hiding a mechanism or inventing one.
NULL_TOL = 1e-9

SUPPORT_DOF = {'pin': ('x', 'y'), 'rollerX': ('y',), 'rollerY': ('x',),
               'fixed': ('x', 'y', 't')}


def _dofs(nodes, rods, supports):
    """(dof_of, ndof): the solver's numbering -- ux, uy per node, plus a
    rotation where a rigid rod or a fixed support needs one."""
    n = len(nodes)
    needs_theta = [False] * n
    for r in rods:
        if r.get('conn', 'pin') == 'rigid':
            needs_theta[r['a']] = needs_theta[r['b']] = True
    for s in supports:
        if s.get('type') == 'fixed' and 0 <= s.get('node', -1) < n:
            needs_theta[s['node']] = True
    dof_of, d = [], 0
    for i in range(n):
        th = None
        if needs_theta[i]:
            th = d + 2
        dof_of.append((d, d + 1, th))
        d += 3 if needs_theta[i] else 2
    return dof_of, d


def assemble(nodes, rods, supports, plates=None):
    """Global stiffness K (N/m, N, N m), the DOF numbering, the constrained
    DOF and the number of deformation modes. Rods shorter than 1 px are
    skipped, as the solver skips them."""
    dof_of, ndof = _dofs(nodes, rods, supports)
    K = np.zeros((ndof, ndof))
    modes = 0
    for r in rods:
        na, nb = nodes[r['a']], nodes[r['b']]
        dx, dy = nb[0] - na[0], nb[1] - na[1]
        L = math.hypot(dx, dy)
        if L < 1:
            continue
        Lm = L / PX_PER_M
        c, s = dx / L, dy / L
        ax, ay, at = dof_of[r['a']]
        bx, by, bt = dof_of[r['b']]
        if r.get('conn', 'pin') != 'rigid':
            k = r['E'] * 1e9 * r['A'] * 1e-4 / Lm
            v = np.array([-c, -s, c, s])
            idx = [ax, ay, bx, by]
            K[np.ix_(idx, idx)] += k * np.outer(v, v)
            modes += 1
        else:
            EA = r['E'] * 1e9 * r['A'] * 1e-4 / Lm
            EI = r['E'] * 1e9 * r.get('I', 8000.0) * 1e-8
            kl = np.zeros((6, 6))
            kl[0, 0] = kl[3, 3] = EA
            kl[0, 3] = kl[3, 0] = -EA
            kb = np.array([[12 / Lm**3, 6 / Lm**2, -12 / Lm**3, 6 / Lm**2],
                           [6 / Lm**2, 4 / Lm, -6 / Lm**2, 2 / Lm],
                           [-12 / Lm**3, -6 / Lm**2, 12 / Lm**3, -6 / Lm**2],
                           [6 / Lm**2, 2 / Lm, -6 / Lm**2, 4 / Lm]]) * EI
            bi = [1, 2, 4, 5]
            kl[np.ix_(bi, bi)] += kb
            T = np.zeros((6, 6))
            T[0, :2] = (c, s)
            T[1, :2] = (-s, c)
            T[2, 2] = 1
            T[3, 3:5] = (c, s)
            T[4, 3:5] = (-s, c)
            T[5, 5] = 1
            idx = [ax, ay, at, bx, by, bt]
            K[np.ix_(idx, idx)] += T.T @ kl @ T
            modes += 3
    for p in plates or []:
        if p.get('kind') != 'panel':
            continue
        geom = plate_geometry(nodes, p)
        if geom is None:
            continue
        loop, _pts, area, B = geom
        G, t = plate_material(p)
        if G <= 0 or t <= 0:
            continue
        kp = np.array(plate_stiffness(area, B, G, t))
        idx = []
        for ni in loop:
            idx += [dof_of[ni][0], dof_of[ni][1]]
        K[np.ix_(idx, idx)] += kp
        modes += int(np.linalg.matrix_rank(kp, tol=1e-9 * abs(kp).max()))
    fixed = set()
    for sp in supports:
        ux, uy, th = dof_of[sp['node']]
        for d in SUPPORT_DOF.get(sp.get('type'), ()):
            if d == 'x':
                fixed.add(ux)
            elif d == 'y':
                fixed.add(uy)
            elif th is not None:
                fixed.add(th)
    return K, dof_of, sorted(fixed), modes


def _null_space(Kf):
    """Orthonormal basis of the (Jacobi-scaled) null space of Kf, in the
    original DOF, as columns."""
    if Kf.size == 0:
        return np.zeros((0, 0))
    diag = np.diag(Kf).copy()
    scale = np.where(diag > 0, 1.0 / np.sqrt(np.where(diag > 0, diag, 1.0)), 1.0)
    Ks = Kf * scale[:, None] * scale[None, :]
    w, V = np.linalg.eigh(Ks)
    top = max(abs(w).max(), 1e-300)
    null = V[:, w < NULL_TOL * top] * scale[:, None]
    return null


def check(nodes, rods, supports, plates=None):
    """Indeterminacy and mechanisms of the model as it stands.

    Returns a dict:
      members_modes, reactions, joints, dof  -- the counts that go in
      count       Maxwell's count: modes + reactions - DOF
      mechanisms  k, from the rank of K
      degree      s, the static indeterminacy
      verdict     'mechanism' | 'determinate' | 'indeterminate'
      text        one line for the panel
    """
    K, dof_of, fixed, modes = assemble(nodes, rods, supports, plates)
    ndof = K.shape[0]
    free = [i for i in range(ndof) if i not in set(fixed)]
    reactions = len(fixed)
    count = modes + reactions - ndof
    Kf = K[np.ix_(free, free)]
    k = _null_space(Kf).shape[1] if free else 0
    s = count + k
    pin_only = all(r.get('conn', 'pin') != 'rigid' for r in rods)
    panels = plates and any(p.get('kind') == 'panel' for p in plates)
    if pin_only and not panels and ndof == 2 * len(nodes):
        formula = 'm + r − 2j = %d + %d − 2×%d = %d' % (
            modes, reactions, len(nodes), count)
    else:
        formula = 'deformations + r − DOF = %d + %d − %d = %d' % (
            modes, reactions, ndof, count)
    if k > 0:
        verdict = 'mechanism'
        if count < 0:
            text = ('A mechanism: too few rods or supports (%s). It can move '
                    'without stretching any rod.' % formula)
        else:
            text = ('A mechanism, although the count looks sufficient (%s): '
                    'some rods or supports are in the wrong place, so it can '
                    'move without stretching any rod.' % formula)
    elif s == 0:
        verdict = 'determinate'
        text = 'Statically determinate (%s): statics alone gives every force.' % formula
    else:
        verdict = 'indeterminate'
        text = ('Statically indeterminate to degree %d (%s): the forces '
                'also depend on the stiffness of the rods.' % (s, formula))
    return {'members_modes': modes, 'reactions': reactions,
            'joints': len(nodes), 'dof': ndof, 'count': count,
            'mechanisms': k, 'degree': s, 'verdict': verdict, 'text': text}


def mechanism_mode(nodes, rods, supports, plates=None):
    """How the model moves, when it cannot stand; None when it stands.

    Returns {'motion': [(dx, dy) per node, largest = 1], 'kind':
    'slide_x' | 'slide_y' | 'turn' | 'internal', 'moving': [node ids that
    move relative to the rest], 'loose': [nodes no rod reaches], 'text'}.
    """
    K, dof_of, fixed, _modes = assemble(nodes, rods, supports, plates)
    ndof = K.shape[0]
    fset = set(fixed)
    free = [i for i in range(ndof) if i not in fset]
    if not free:
        return None
    null = _null_space(K[np.ix_(free, free)])
    if null.shape[1] == 0:
        return None
    n = len(nodes)
    touched = set()
    for r in rods:
        touched.add(r['a'])
        touched.add(r['b'])
    loose = [i for i in range(n) if i not in touched]

    def motion_of(vec):
        u = np.zeros(ndof)
        u[free] = vec
        m = np.array([(u[dof_of[i][0]], u[dof_of[i][1]]) for i in range(n)])
        big = np.abs(m).max()
        return m / big if big > 0 else m

    # Prefer the mode that moves the connected structure, not a loose node
    # alone: pick the null vector with the most motion outside `loose`.
    best, best_score = None, -1.0
    for j in range(null.shape[1]):
        m = motion_of(null[:, j])
        score = sum(math.hypot(*m[i]) for i in range(n) if i not in loose)
        if score > best_score:
            best, best_score = m, score
    m = best
    pts = np.array([(x / PX_PER_M, y / PX_PER_M) for x, y in nodes])
    kind, text = 'internal', None
    rigid_fit = None
    conn = [i for i in range(n) if i not in loose]
    if len(conn) >= 2 and best_score > 0:
        # Fit u = a - th*y, v = b + th*x to the connected joints: a whole-
        # body motion fits exactly.
        A = np.zeros((2 * len(conn), 3))
        rhs = np.zeros(2 * len(conn))
        for k_, i in enumerate(conn):
            x, y = pts[i]
            A[2 * k_] = (1, 0, -y)
            A[2 * k_ + 1] = (0, 1, x)
            rhs[2 * k_], rhs[2 * k_ + 1] = m[i]
        sol, *_ = np.linalg.lstsq(A, rhs, rcond=None)
        resid = np.abs(A @ sol - rhs).max()
        if resid < 1e-6:
            rigid_fit = sol
    if best_score == 0 and loose:
        kind = 'loose'
        text = ('Node%s %s %s connected to no rod, so nothing holds %s. '
                'Delete %s or connect %s.'
                % ('s' if len(loose) > 1 else '', ', '.join(map(str, loose)),
                   'are' if len(loose) > 1 else 'is',
                   'them' if len(loose) > 1 else 'it',
                   'them' if len(loose) > 1 else 'it',
                   'them' if len(loose) > 1 else 'it'))
    elif rigid_fit is not None:
        a, b, th = rigid_fit
        span = max(np.ptp(pts[conn, 0]), np.ptp(pts[conn, 1]), 1e-9)
        if abs(th) * span < 1e-6 * max(abs(a), abs(b), 1e-12) or abs(th) < 1e-9:
            if abs(a) >= abs(b):
                kind = 'slide_x'
                text = ('Nothing stops the whole truss sliding sideways: '
                        'add a pin support, or turn a roller into a pin.')
            else:
                kind = 'slide_y'
                text = ('Nothing stops the whole truss moving up and down: '
                        'support it vertically.')
        else:
            kind = 'turn'
            text = ('The whole truss can turn about one point: one support '
                    'is not enough. Add a second support away from the first.')
    mags = np.hypot(m[:, 0], m[:, 1])
    if kind == 'internal':
        rb = np.zeros_like(m)
        if len(conn) >= 2:
            # Moving RELATIVE to the rest: remove the best whole-body fit so
            # a panel that folds is told apart from the part that follows it.
            A = np.zeros((2 * len(conn), 3))
            rhs = np.zeros(2 * len(conn))
            for k_, i in enumerate(conn):
                x, y = pts[i]
                A[2 * k_] = (1, 0, -y)
                A[2 * k_ + 1] = (0, 1, x)
                rhs[2 * k_], rhs[2 * k_ + 1] = m[i]
            sol, *_ = np.linalg.lstsq(A, rhs, rcond=None)
            for i in conn:
                x, y = pts[i]
                rb[i] = (sol[0] - sol[2] * y, sol[1] + sol[2] * x)
        rel = np.hypot(*(m - rb).T)
        moving = [i for i in conn if rel[i] > 0.25 * rel.max()] if rel.max() > 0 else []
        text = ('Part of the truss can move without stretching any rod: the '
                'highlighted joints. Usually a panel with no diagonal, or a '
                'joint held by a single rod -- add a diagonal there.')
    else:
        moving = [i for i in range(n) if mags[i] > 0.25 * mags.max()]
    if loose and kind != 'loose':
        text += ' Also: node%s %s %s connected to no rod.' % (
            's' if len(loose) > 1 else '', ', '.join(map(str, loose)),
            'are' if len(loose) > 1 else 'is')
    return {'motion': [tuple(map(float, v)) for v in m], 'kind': kind,
            'moving': moving, 'loose': loose, 'text': text}
