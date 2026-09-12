"""3D direct-stiffness solver for the Stereo (space-structure) tab.

Storage units, kept consistent with the rest of the app (see units.py /
common.UnitsMixin): node coordinates in metres, member area in cm², E and G
in GPa, Fy/Fu in MPa, nodal loads in kN, self-weight density in kN/m³.
Internally everything is converted to SI (m, N, Pa) for the assembly, the
same boundary as truss_math.py crosses with its own *1e9/*1e-4/*1e3 factors.

MODEL
-----
nodes   : list of (x, y, z) tuples, metres. Node identity is list index.
members : list of dicts, each an axial bar ('pin', the default -- a
          ball-jointed space-truss member carrying only axial force, which
          is what MERO/Nodus/Triodetic-type real space structures actually
          build) or a full 3D beam-column ('rigid' -- a moment-transferring
          connection, for a Vierendeel-type space frame), with:
              a, b        : node indices
              conn        : 'pin' (default) | 'rigid'
              E           : GPa
              A           : cm²
              Fy, Fu      : MPa      (for the CIRSOC checks)
              K           : effective-length factor (default 1.0)
              r_gyr       : cm, weak-axis radius of gyration (pin members;
                            used for the compression buckling check)
              I           : cm⁴, weak-axis second moment (rigid members
                            only -- both bending planes are given this one
                            value, i.e. a doubly-symmetric section is
                            assumed; documented simplification)
              J           : cm⁴, torsion constant (rigid members only;
                            defaults to I if omitted -- another named
                            simplification, exact for a circular/round
                            tube and conservative-ish otherwise)
loads   : list of {'node': i, 'fx': kN, 'fy': kN, 'fz': kN,
                    'mx': kN·m, 'my': kN·m, 'mz': kN·m}, global axes.
          The moment components are optional (default 0) and only make
          physical sense at a node that can actually resist a moment; a
          node loaded with a nonzero mx/my/mz is granted rotational DOFs
          for exactly that reason, on top of the 'rigid member' and
          'restrained rotation' triggers below.
supports: list of {'node': i, 'type': preset_name_or_None,
                    'dofs': {dof_name: bool, ...}}
          -- see `support_restraints` below. This is deliberately NOT a
          fixed enum of support "types": `type` supplies a starting preset
          (or none at all) and `dofs` may restrain or free ANY of the six
          DOF names on top of it, so a user is never limited to a menu of
          canned support conditions.

BOUNDARY CONDITIONS -- "any combination the user pleases"
----------------------------------------------------------
Every one of the six DOFs at every node (ux, uy, uz, rx, ry, rz) is an
independent boolean: restrained or free. A preset ('pin', 'fixed',
'rollerX', ...) is only a convenience that fills in a starting `dofs` dict;
`support_restraints` always applies the user's explicit per-DOF overrides
on top of it, and a support with no preset at all (`type=None`) is
perfectly valid -- pick exactly the DOFs you want restrained. This is what
lets a genuinely unusual condition (e.g. a node free to translate but
restrained against rotation about one axis only, or a diagonal roller) be
built without inventing a new preset name for it. `check_boundary_setup`
below validates the result (rigid-body mechanism / over-restraint) so a
mistake shows up as a clear message instead of a silently wrong or
singular solve.

DOF ALLOCATION
--------------
Exactly the same lazy trick as truss_math.py's `needs_theta`, generalized
from one rotational DOF to three: a node gets rotational DOFs (rx,ry,rz)
only if a 'rigid' member touches it, or a support at that node restrains
at least one rotational DOF. A model built entirely from 'pin' members and
translation-only supports reduces exactly to a classic 3-DOF/node space
truss.
"""
import math
import numpy as np

from common import _beam_gauss_solve

gauss_solve = _beam_gauss_solve

DOF_NAMES = ('ux', 'uy', 'uz', 'rx', 'ry', 'rz')
ROT_DOFS = ('rx', 'ry', 'rz')

DEFAULT_STEEL_UNIT_WEIGHT = 78.5   # kN/m^3
DEFAULT_NU = 0.3                   # Poisson's ratio, for G = E / (2(1+nu))

PRESET_SUPPORTS = {
    'free':    {},
    'pin':     {'ux': True, 'uy': True, 'uz': True},
    'fixed':   {'ux': True, 'uy': True, 'uz': True, 'rx': True, 'ry': True, 'rz': True},
    'rollerX': {'uy': True, 'uz': True},    # free to slide along global X only
    'rollerY': {'ux': True, 'uz': True},    # free to slide along global Y only
    'rollerZ': {'ux': True, 'uy': True},    # free to slide along global Z only
}


def support_restraints(support):
    """The full 6-bool restraint dict for one support entry: a named preset
    (if any) merged with any explicit per-DOF override. This is the one
    place "any boundary condition the user pleases" is realised -- nothing
    downstream ever looks at `type` again, only at this resolved dict."""
    base = dict.fromkeys(DOF_NAMES, False)
    preset = support.get('type')
    if preset:
        if preset not in PRESET_SUPPORTS:
            raise ValueError(f'unknown support preset {preset!r}; expected one of '
                              f'{tuple(PRESET_SUPPORTS)} or None')
        base.update(PRESET_SUPPORTS[preset])
    base.update(support.get('dofs') or {})
    return base


def member_vector(nodes, member):
    na, nb = nodes[member['a']], nodes[member['b']]
    dx, dy, dz = nb[0] - na[0], nb[1] - na[1], nb[2] - na[2]
    L = math.sqrt(dx * dx + dy * dy + dz * dz)
    return dx, dy, dz, L


def _local_axes(dx, dy, dz, L):
    """A right-handed local (x,y,z) basis for a 3D frame element: local x
    along the member; local y and z from a fixed global reference vector,
    exactly like every standard 3D frame-element formulation (McGuire,
    Gallagher & Ziemian; Przemieniecki). Global Z is the reference vector
    unless the member itself is (near-)vertical, in which case global Y is
    used instead -- otherwise the cross product used to build local y would
    be with a parallel vector and degenerate to zero."""
    lx, ly, lz = dx / L, dy / L, dz / L
    if abs(lx) < 1e-9 and abs(ly) < 1e-9:
        ref = (0.0, 1.0, 0.0)
    else:
        ref = (0.0, 0.0, 1.0)
    # local y = ref x local_x, normalized
    yx = ref[1] * lz - ref[2] * ly
    yy = ref[2] * lx - ref[0] * lz
    yz = ref[0] * ly - ref[1] * lx
    nrm = math.sqrt(yx * yx + yy * yy + yz * yz)
    yx, yy, yz = yx / nrm, yy / nrm, yz / nrm
    # local z = local_x x local_y
    zx = ly * yz - lz * yy
    zy = lz * yx - lx * yz
    zz = lx * yy - ly * yx
    return (lx, ly, lz), (yx, yy, yz), (zx, zy, zz)


def _pin_stiffness(E_GPa, A_cm2, L):
    k = (E_GPa * 1e9) * (A_cm2 * 1e-4) / L
    return k


def _rigid_local_stiffness(E_GPa, A_cm2, I_cm4, J_cm4, L, nu=DEFAULT_NU):
    """The standard 12x12 local stiffness matrix for a 3D Euler-Bernoulli
    beam-column, DOF order (ux,uy,uz,rx,ry,rz) at node a then node b.
    Bending about local z (in-plane uy/rz) uses Iz; bending about local y
    (in-plane uz/ry) uses Iy. A doubly-symmetric section is assumed
    (Iy = Iz = I, the member's one given `I`), which is exact for a round
    or square hollow section -- the common choice for space-structure
    members -- and a documented simplification otherwise."""
    E = E_GPa * 1e9
    G = E / (2.0 * (1.0 + nu))
    A = A_cm2 * 1e-4
    Iy = Iz = I_cm4 * 1e-8
    J = J_cm4 * 1e-8

    EA_L = E * A / L
    GJ_L = G * J / L
    k = np.zeros((12, 12))

    k[0, 0] = k[6, 6] = EA_L
    k[0, 6] = k[6, 0] = -EA_L

    # bending in the local x-y plane (uy, rz), stiffness from Iz
    k[1, 1] = k[7, 7] = 12 * E * Iz / L ** 3
    k[1, 7] = k[7, 1] = -12 * E * Iz / L ** 3
    k[1, 5] = k[5, 1] = 6 * E * Iz / L ** 2
    k[1, 11] = k[11, 1] = 6 * E * Iz / L ** 2
    k[5, 7] = k[7, 5] = -6 * E * Iz / L ** 2
    k[7, 11] = k[11, 7] = -6 * E * Iz / L ** 2
    k[5, 5] = k[11, 11] = 4 * E * Iz / L
    k[5, 11] = k[11, 5] = 2 * E * Iz / L

    # bending in the local x-z plane (uz, ry), stiffness from Iy
    k[2, 2] = k[8, 8] = 12 * E * Iy / L ** 3
    k[2, 8] = k[8, 2] = -12 * E * Iy / L ** 3
    k[2, 4] = k[4, 2] = -6 * E * Iy / L ** 2
    k[2, 10] = k[10, 2] = -6 * E * Iy / L ** 2
    k[4, 8] = k[8, 4] = 6 * E * Iy / L ** 2
    k[8, 10] = k[10, 8] = 6 * E * Iy / L ** 2
    k[4, 4] = k[10, 10] = 4 * E * Iy / L
    k[4, 10] = k[10, 4] = 2 * E * Iy / L

    # torsion (rx)
    k[3, 3] = k[9, 9] = GJ_L
    k[3, 9] = k[9, 3] = -GJ_L

    return k


def _rotation_12(local_x, local_y, local_z):
    """Block-diagonal 12x12 transformation (global -> local) from the 3x3
    direction-cosine matrix, repeated once per translational/rotational
    triplet at each of the two nodes."""
    r3 = np.array([local_x, local_y, local_z])
    T = np.zeros((12, 12))
    for blk in range(4):
        T[blk * 3:blk * 3 + 3, blk * 3:blk * 3 + 3] = r3
    return T


def analyze(nodes, members, loads, supports):
    """Solve the space structure. Returns (result, error). On failure,
    result is None and error is a human-readable string (mirroring every
    other solver in this app, e.g. truss_math.analyze).

    result = {
        'node_res': [{'ux','uy','uz' (mm), 'rx','ry','rz' (rad)}, ...],
        'member_res': [{'N' (kN, +tension), and for rigid members also
                         'Vy','Vz' (kN), 'T','My_a','My_b','Mz_a','Mz_b'
                         (kN·m)}, ...],
        'reactions': {node_idx: {'Fx','Fy','Fz' (kN), 'Mx','My','Mz' (kN·m)}},
    }
    """
    err = check_boundary_setup(nodes, members, supports)
    if err:
        return None, err

    N = len(nodes)
    restraints = [dict.fromkeys(DOF_NAMES, False) for _ in range(N)]
    for sp in supports:
        r = support_restraints(sp)
        node_r = restraints[sp['node']]
        for d in DOF_NAMES:
            node_r[d] = node_r[d] or r[d]

    needs_rot = [False] * N
    for m in members:
        if m.get('conn', 'pin') == 'rigid':
            needs_rot[m['a']] = True
            needs_rot[m['b']] = True
    for i in range(N):
        if any(restraints[i][d] for d in ROT_DOFS):
            needs_rot[i] = True
    for ld in loads:
        if any(ld.get(k, 0.0) for k in ('mx', 'my', 'mz')):
            needs_rot[ld['node']] = True

    dof_of = [None] * N   # (ux,uy,uz, rx_or_None, ry_or_None, rz_or_None)
    ndof = 0
    for i in range(N):
        idx = [ndof, ndof + 1, ndof + 2]
        ndof += 3
        if needs_rot[i]:
            idx += [ndof, ndof + 1, ndof + 2]
            ndof += 3
        else:
            idx += [None, None, None]
        dof_of[i] = tuple(idx)

    K = np.zeros((ndof, ndof))
    for m in members:
        dx, dy, dz, L = member_vector(nodes, m)
        if L < 1e-9:
            continue
        lx, ly, lz = dx / L, dy / L, dz / L
        a_dof, b_dof = dof_of[m['a']], dof_of[m['b']]

        if m.get('conn', 'pin') != 'rigid':
            k = _pin_stiffness(m['E'], m['A'], L)
            dirn = np.array([lx, ly, lz])
            ke33 = k * np.outer(dirn, dirn)
            idx = [a_dof[0], a_dof[1], a_dof[2], b_dof[0], b_dof[1], b_dof[2]]
            ke = np.block([[ke33, -ke33], [-ke33, ke33]])
            for i in range(6):
                for j in range(6):
                    K[idx[i], idx[j]] += ke[i, j]
        else:
            local_x, local_y, local_z = _local_axes(dx, dy, dz, L)
            kloc = _rigid_local_stiffness(m['E'], m['A'], m.get('I', 0.0),
                                           m.get('J', m.get('I', 0.0)), L)
            T = _rotation_12(local_x, local_y, local_z)
            kgl = T.T @ kloc @ T
            idx = list(a_dof) + list(b_dof)
            for i in range(12):
                for j in range(12):
                    K[idx[i], idx[j]] += kgl[i, j]

    F = np.zeros(ndof)
    for ld in loads:
        idx = dof_of[ld['node']]
        F[idx[0]] += ld.get('fx', 0.0) * 1e3
        F[idx[1]] += ld.get('fy', 0.0) * 1e3
        F[idx[2]] += ld.get('fz', 0.0) * 1e3
        for k, key in ((3, 'mx'), (4, 'my'), (5, 'mz')):
            v = ld.get(key, 0.0)
            if v:
                F[idx[k]] += v * 1e3

    constrained = set()
    for sp in supports:
        r = support_restraints(sp)
        idx = dof_of[sp['node']]
        for k, d in enumerate(DOF_NAMES):
            if r[d]:
                if idx[k] is None:
                    # a rotational restraint at a node with no rotational
                    # DOF allocated cannot happen: needs_rot was set for
                    # exactly this case above.
                    raise AssertionError('internal: rotational DOF missing '
                                          'for a restrained rotation')
                constrained.add(idx[k])

    free = [i for i in range(ndof) if i not in constrained]
    if not free:
        return None, 'All degrees of freedom are constrained -- nothing can move.'

    Kf = K[np.ix_(free, free)]
    Ff = F[free]
    U_free = gauss_solve(Kf, Ff)
    if U_free is None:
        return None, ('Singular stiffness matrix -- the structure (or some part '
                       'of it) is a mechanism, or a node is floating with no '
                       'load path to a support. Check for missing members or '
                       'missing boundary conditions.')

    U = np.zeros(ndof)
    for li, gi in enumerate(free):
        U[gi] = U_free[li]

    node_res = []
    for i in range(N):
        idx = dof_of[i]
        node_res.append({
            'ux': U[idx[0]] * 1000.0, 'uy': U[idx[1]] * 1000.0, 'uz': U[idx[2]] * 1000.0,
            'rx': U[idx[3]] if idx[3] is not None else 0.0,
            'ry': U[idx[4]] if idx[4] is not None else 0.0,
            'rz': U[idx[5]] if idx[5] is not None else 0.0,
        })

    member_res = []
    for m in members:
        dx, dy, dz, L = member_vector(nodes, m)
        if L < 1e-9:
            member_res.append({'N': 0.0, 'conn': m.get('conn', 'pin'), 'length_m': 0.0})
            continue
        lx, ly, lz = dx / L, dy / L, dz / L
        a_dof, b_dof = dof_of[m['a']], dof_of[m['b']]

        if m.get('conn', 'pin') != 'rigid':
            ua = np.array([U[a_dof[0]], U[a_dof[1]], U[a_dof[2]]])
            ub = np.array([U[b_dof[0]], U[b_dof[1]], U[b_dof[2]]])
            dirn = np.array([lx, ly, lz])
            elong = float(np.dot(ub - ua, dirn))
            N_force = (m['E'] * 1e9) * (m['A'] * 1e-4) / L * elong
            member_res.append({'N': N_force / 1e3, 'conn': 'pin', 'length_m': L})
        else:
            local_x, local_y, local_z = _local_axes(dx, dy, dz, L)
            kloc = _rigid_local_stiffness(m['E'], m['A'], m.get('I', 0.0),
                                           m.get('J', m.get('I', 0.0)), L)
            T = _rotation_12(local_x, local_y, local_z)
            idx = list(a_dof) + list(b_dof)
            dgl = np.array([U[i] for i in idx])
            dloc = T @ dgl
            floc = kloc @ dloc
            member_res.append({
                'N': floc[6] / 1e3, 'conn': 'rigid', 'length_m': L,
                'Vy_a': floc[1] / 1e3, 'Vz_a': floc[2] / 1e3, 'T': floc[3] / 1e3,
                'My_a': floc[4] / 1e3, 'Mz_a': floc[5] / 1e3,
                'My_b': floc[10] / 1e3, 'Mz_b': floc[11] / 1e3,
            })

    reactions = {}
    Ku = K @ U
    for sp in supports:
        r = support_restraints(sp)
        if not any(r.values()):
            continue
        idx = dof_of[sp['node']]
        rxn = reactions.setdefault(sp['node'], {'Fx': 0.0, 'Fy': 0.0, 'Fz': 0.0,
                                                 'Mx': 0.0, 'My': 0.0, 'Mz': 0.0})
        labels = ('Fx', 'Fy', 'Fz', 'Mx', 'My', 'Mz')
        for k, d in enumerate(DOF_NAMES):
            if r[d] and idx[k] is not None:
                resid = Ku[idx[k]] - F[idx[k]]
                rxn[labels[k]] += resid / 1e3   # N -> kN, N*m -> kN*m

    return {'node_res': node_res, 'member_res': member_res, 'reactions': reactions}, None


def check_boundary_setup(nodes, members, supports):
    """Validate supports BEFORE assembly, so a bad boundary-condition setup
    reads as a clear message instead of a numpy singular-matrix traceback
    or (worse) a silently wrong answer.

    Catches:
      * a support naming a node index out of range;
      * an unknown preset name (surfaced from `support_restraints`);
      * fewer than 3 independent translational restraints anywhere in the
        model, which always leaves at least a rigid-body translation or
        rotation free regardless of how the members are arranged -- the
        classic "floating in space" mistake. This is a coarse necessary
        check, not a full mechanism/stability analysis (a real mechanism
        hiding inside an otherwise adequately-supported model is instead
        caught by the singular-matrix guard in `analyze`).
    """
    N = len(nodes)
    for sp in supports:
        if not (0 <= sp['node'] < N):
            return f"support references node {sp['node']}, but the model has {N} nodes"
        try:
            support_restraints(sp)
        except ValueError as exc:
            return str(exc)

    restrained_axes = set()
    any_restraint = False
    for sp in supports:
        r = support_restraints(sp)
        for d in ('ux', 'uy', 'uz'):
            if r[d]:
                restrained_axes.add(d)
                any_restraint = True
    if not any_restraint:
        return ('No boundary conditions are defined -- the structure is free to '
                'translate and rotate as a rigid body. Restrain at least one node.')
    if len(restrained_axes) < 3:
        missing = sorted({'ux', 'uy', 'uz'} - restrained_axes)
        return ('The supports restrain translation along ' +
                ', '.join(sorted(a[-1] for a in restrained_axes)) +
                f' only; {", ".join(a[-1] for a in missing)} is free everywhere, so '
                'the whole structure can translate as a rigid body in that '
                'direction. Restrain it somewhere.')
    return None


def self_weight_loads(nodes, members, unit_weight_kN_m3=DEFAULT_STEEL_UNIT_WEIGHT):
    """Lump each member's self weight (kN) half-and-half onto its two end
    nodes as a downward (-z) nodal load -- the standard space-truss
    idealisation, exact for a pin member (which can carry no distributed
    load anyway) and the usual practical approximation for a rigid one."""
    totals = {}
    for m in members:
        _, _, _, L = member_vector(nodes, m)
        W = m['A'] * 1e-4 * L * unit_weight_kN_m3   # cm² -> m², times length, times kN/m3
        half = W / 2.0
        totals[m['a']] = totals.get(m['a'], 0.0) + half
        totals[m['b']] = totals.get(m['b'], 0.0) + half
    return [{'node': n, 'fx': 0.0, 'fy': 0.0, 'fz': -w} for n, w in totals.items()]


def combine_loads(*load_lists):
    """Merge several load lists (e.g. applied loads + self_weight_loads)
    into one, summing contributions that land on the same node instead of
    leaving them as separate entries analyze() would otherwise just add
    anyway -- kept separate only for readability of the combined list."""
    totals = {}
    for loads in load_lists:
        for ld in loads:
            t = totals.setdefault(ld['node'], {'node': ld['node'], 'fx': 0.0, 'fy': 0.0, 'fz': 0.0})
            t['fx'] += ld.get('fx', 0.0)
            t['fy'] += ld.get('fy', 0.0)
            t['fz'] += ld.get('fz', 0.0)
    return list(totals.values())
