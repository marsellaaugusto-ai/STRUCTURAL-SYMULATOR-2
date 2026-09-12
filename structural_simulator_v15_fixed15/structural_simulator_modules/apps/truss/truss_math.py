"""Finite-element solver and V/M recovery for the Truss/Vierendeel tab."""
import math
from common import PX_PER_M, _beam_gauss_solve

gauss_solve = _beam_gauss_solve

def udl_local_components(rod, c, s, w):
    """Return (axial, transverse) UDL components in member local axes.

    New UI convention: udl_rotation_deg rotates the default perpendicular
    load toward the A->B member axis. 0° = perpendicular, +90° = A->B.
    Legacy imported models using udl_global/udl_angle_deg remain supported.
    """
    if 'udl_rotation_deg' in rod:
        th = math.radians(float(rod.get('udl_rotation_deg', 0.0)))
        return w * math.sin(th), w * math.cos(th)
    if rod.get('udl_global', False):
        ang = math.radians(float(rod.get('udl_angle_deg', 90.0)))
        fx, fy = w * math.cos(ang), w * math.sin(ang)
        return c * fx + s * fy, -s * fx + c * fy
    return 0.0, w


def analyze(nodes, rods, loads, supports):
    """
    Generalized 2D truss/frame solver. Each rod is independently either:
      - 'pin'   (default): pure axial bar, exactly the original truss
                behavior -- carries only N, contributes no bending
                stiffness, and never touches any rotational DOF.
      - 'rigid': full 2D frame (beam-column) element -- axial EA/L plus
                the standard Euler-Bernoulli 4x4 bending block, exactly
                like ArchModel's frame elements. Carries N, V, and end
                moments Ma/Mb. This is what lets adjoining rigid rods
                transmit moment through a joint -- the mechanism a
                Vierendeel girder relies on in place of diagonals.

    A rigid rod may also carry a uniformly distributed load ('udl' key,
    kN/m, in the selected local direction): this is converted to the classic
    fixed-end force vector (wL/2 shear, wL^2/12 moment at each end) for
    assembly, then subtracted back out of the solved end forces to
    recover the TRUE member end shear/moment -- the standard FEM
    "member load" recipe. rod_res stores enough (V at end a, the local
    transverse udl, and length) to reconstruct the exact linear-shear /
    parabolic-moment variation along the member afterwards.

    A node is only given a rotational DOF if it actually needs one: at
    least one 'rigid' rod touches it, or a 'fixed' support sits there.
    A model with every rod left 'pin' and no udl reduces EXACTLY to the
    classic pin-jointed truss (same K, same results, bit-for-bit).
    """
    N = len(nodes)

    needs_theta = [False] * N
    for rod in rods:
        if rod.get('conn', 'pin') == 'rigid':
            needs_theta[rod['a']] = True
            needs_theta[rod['b']] = True
    for s in supports:
        if s['type'] == 'fixed':
            needs_theta[s['node']] = True

    dof_of = [None] * N   # (ux_idx, uy_idx, theta_idx_or_None)
    dof = 0
    for i in range(N):
        ux_i, uy_i = dof, dof + 1
        dof += 2
        th_i = None
        if needs_theta[i]:
            th_i = dof
            dof += 1
        dof_of[i] = (ux_i, uy_i, th_i)

    K = [[0.0] * dof for _ in range(dof)]
    fixed_end = {}   # rod index -> local 6-vector fixed-end force (for udl rods)

    for ri, rod in enumerate(rods):
        na, nb = nodes[rod['a']], nodes[rod['b']]
        dx, dy = nb[0] - na[0], nb[1] - na[1]
        L = math.hypot(dx, dy)
        if L < 1: continue
        Lm = L / PX_PER_M
        c, s = dx / L, dy / L
        ax_i, ay_i, ath_i = dof_of[rod['a']]
        bx_i, by_i, bth_i = dof_of[rod['b']]

        if rod.get('conn', 'pin') != 'rigid':
            k = rod['E']*1e9 * rod['A']*1e-4 / Lm
            cc, ss, cs = c*c, s*s, c*s
            idx = [ax_i, ay_i, bx_i, by_i]
            ke = [[cc,cs,-cc,-cs],[cs,ss,-cs,-ss],
                  [-cc,-cs,cc,cs],[-cs,-ss,cs,ss]]
            for i in range(4):
                for j in range(4):
                    K[idx[i]][idx[j]] += k*ke[i][j]
        else:
            EA_L = rod['E']*1e9 * rod['A']*1e-4 / Lm
            EI = rod['E']*1e9 * rod.get('I', 8000.0)*1e-8
            kb = [[12*EI/Lm**3, 6*EI/Lm**2, -12*EI/Lm**3, 6*EI/Lm**2],
                  [6*EI/Lm**2, 4*EI/Lm, -6*EI/Lm**2, 2*EI/Lm],
                  [-12*EI/Lm**3, -6*EI/Lm**2, 12*EI/Lm**3, -6*EI/Lm**2],
                  [6*EI/Lm**2, 2*EI/Lm, -6*EI/Lm**2, 4*EI/Lm]]
            kloc = [[0.0]*6 for _ in range(6)]
            kloc[0][0] = EA_L; kloc[0][3] = -EA_L
            kloc[3][0] = -EA_L; kloc[3][3] = EA_L
            bidx = [1, 2, 4, 5]
            for i in range(4):
                for j in range(4):
                    kloc[bidx[i]][bidx[j]] += kb[i][j]
            T = [[c, s, 0, 0, 0, 0],
                 [-s, c, 0, 0, 0, 0],
                 [0, 0, 1, 0, 0, 0],
                 [0, 0, 0, c, s, 0],
                 [0, 0, 0, -s, c, 0],
                 [0, 0, 0, 0, 0, 1]]
            Tt = list(map(list, zip(*T)))
            tmp = [[sum(Tt[i][k]*kloc[k][j] for k in range(6)) for j in range(6)] for i in range(6)]
            kgl = [[sum(tmp[i][k]*T[k][j] for k in range(6)) for j in range(6)] for i in range(6)]
            idx = [ax_i, ay_i, ath_i, bx_i, by_i, bth_i]
            for i in range(6):
                for j in range(6):
                    K[idx[i]][idx[j]] += kgl[i][j]

            # Member loads are stored as *internal fixed-end actions* (FEF).
            # Their negative is the equivalent external nodal load assembled
            # into K*u = F.  Keeping this distinction explicit is essential:
            # a positive UI load (+down) must produce a positive global
            # applied-load component, not its opposite.
            # Default UDL direction is perpendicular to the rod; when
            # udl_global is true, udl_angle_deg is measured globally from
            # +X (0° = right, 90° = down).
            Ffix = [0.0]*6
            w = rod.get('udl', 0.0) * 1e3   # kN/m -> N/m
            if w != 0.0:
                wa, wt = udl_local_components(rod, c, s, w)
                # FEF = - (consistent equivalent nodal load).
                Fudl = [-wa*Lm/2, -wt*Lm/2, -wt*Lm**2/12,
                        -wa*Lm/2, -wt*Lm/2, wt*Lm**2/12]
                Ffix = [Ffix[i] + Fudl[i] for i in range(6)]

            # One or more point loads may act anywhere along the rigid rod.
            # Each entry uses position t (0..1) from end A and a global
            # direction angle (0° = right, 90° = down).
            for pl in rod.get('point_loads', []):
                P = float(pl.get('P', 0.0))*1e3
                t = max(0.0, min(1.0, float(pl.get('t', 0.5))))
                a = Lm*t
                b = Lm-a
                ang = math.radians(float(pl.get('angle_deg', 90.0)))
                fx, fy = P*math.cos(ang), P*math.sin(ang)
                pa, pt = c*fx + s*fy, -s*fx + c*fy
                # FEF = - (consistent equivalent nodal load), using the
                # same convention as the UDL above.  In particular, the
                # rotational terms are opposite at A and B; this preserves
                # the correct end moments for an off-centre point load.
                Fpl = [
                    -pa*b/Lm, -pt*b*b*(3*a+b)/(Lm**3),
                    -pt*a*b*b/(Lm**2),
                    -pa*a/Lm, -pt*a*a*(a+3*b)/(Lm**3),
                    pt*a*a*b/(Lm**2)
                ]
                Ffix = [Ffix[i] + Fpl[i] for i in range(6)]

            if any(abs(v) > 0.0 for v in Ffix):
                fixed_end[ri] = Ffix
                Fgl = [sum(Tt[i][k]*Ffix[k] for k in range(6)) for i in range(6)]
                for i in range(6):
                    K_row = idx[i]
                    # FEF are internal member actions.  The FEM equilibrium
                    # equation is K*u = F_external - FEF, so a +down member
                    # load correctly enters the global RHS as +down.
                    fixed_end.setdefault('_global_contrib', []).append((K_row, -Fgl[i]))

    F = [0.0] * dof
    for ld in loads:
        ux_i, uy_i, _ = dof_of[ld['node']]
        F[ux_i] += ld['fx']*1e3
        F[uy_i] += ld['fy']*1e3
    for gi, val in fixed_end.pop('_global_contrib', []):
        F[gi] += val

    constrained = set()
    for sp in supports:
        ux_i, uy_i, th_i = dof_of[sp['node']]
        if sp['type'] == 'pin':
            constrained.add(ux_i); constrained.add(uy_i)
        elif sp['type'] == 'rollerX': constrained.add(uy_i)
        elif sp['type'] == 'rollerY': constrained.add(ux_i)
        elif sp['type'] == 'fixed':
            constrained.add(ux_i); constrained.add(uy_i)
            if th_i is not None: constrained.add(th_i)

    free = [i for i in range(dof) if i not in constrained]
    if not free: return None, "All DOFs constrained."

    Kf     = [[K[i][j] for j in free] for i in free]
    Ff     = [F[i] for i in free]
    U_free = gauss_solve(Kf, Ff)
    if U_free is None:
        return None, "Singular stiffness matrix – check for mechanisms or floating nodes."

    Uf = [0.0]*dof
    for li, gi in enumerate(free): Uf[gi] = U_free[li]

    node_res = []
    for i in range(N):
        ux_i, uy_i, th_i = dof_of[i]
        node_res.append({'ux': Uf[ux_i]*1000, 'uy': Uf[uy_i]*1000,
                          'theta': Uf[th_i] if th_i is not None else 0.0})

    rod_res = []
    for ri, rod in enumerate(rods):
        na, nb = nodes[rod['a']], nodes[rod['b']]
        dx, dy = nb[0]-na[0], nb[1]-na[1]
        L = math.hypot(dx, dy)
        conn = rod.get('conn', 'pin')
        if L < 1:
            rod_res.append({'force': 0.0, 'V': 0.0, 'Ma': 0.0, 'Mb': 0.0, 'conn': conn,
                             'w_t': 0.0, 'length_m': 0.0})
            continue
        Lm = L/PX_PER_M
        c, s = dx/L, dy/L
        ax_i, ay_i, ath_i = dof_of[rod['a']]
        bx_i, by_i, bth_i = dof_of[rod['b']]

        if conn != 'rigid':
            deform = ((Uf[bx_i]-Uf[ax_i])*c + (Uf[by_i]-Uf[ay_i])*s)
            rod_res.append({'force': rod['E']*1e9*rod['A']*1e-4/Lm*deform/1e3,
                             'V': 0.0, 'Ma': 0.0, 'Mb': 0.0, 'conn': 'pin',
                             'w_t': 0.0, 'length_m': Lm})
        else:
            EA_L = rod['E']*1e9*rod['A']*1e-4/Lm
            EI = rod['E']*1e9*rod.get('I', 8000.0)*1e-8
            kb = [[12*EI/Lm**3, 6*EI/Lm**2, -12*EI/Lm**3, 6*EI/Lm**2],
                  [6*EI/Lm**2, 4*EI/Lm, -6*EI/Lm**2, 2*EI/Lm],
                  [-12*EI/Lm**3, -6*EI/Lm**2, 12*EI/Lm**3, -6*EI/Lm**2],
                  [6*EI/Lm**2, 2*EI/Lm, -6*EI/Lm**2, 4*EI/Lm]]
            kloc = [[0.0]*6 for _ in range(6)]
            kloc[0][0] = EA_L; kloc[0][3] = -EA_L
            kloc[3][0] = -EA_L; kloc[3][3] = EA_L
            bidx = [1, 2, 4, 5]
            for i in range(4):
                for j in range(4):
                    kloc[bidx[i]][bidx[j]] += kb[i][j]
            T = [[c, s, 0, 0, 0, 0],
                 [-s, c, 0, 0, 0, 0],
                 [0, 0, 1, 0, 0, 0],
                 [0, 0, 0, c, s, 0],
                 [0, 0, 0, -s, c, 0],
                 [0, 0, 0, 0, 0, 1]]
            dgl = [Uf[ax_i], Uf[ay_i], Uf[ath_i], Uf[bx_i], Uf[by_i], Uf[bth_i]]
            dloc = [sum(T[i][j]*dgl[j] for j in range(6)) for i in range(6)]
            floc = [sum(kloc[i][j]*dloc[j] for j in range(6)) for i in range(6)]
            Ffix = fixed_end.get(ri)
            w_t_kn = 0.0
            if Ffix is not None:
                # Recover the actual member end force using the same convention
                # as vierendeel.py: f_local = k*d_local + FEF.
                floc = [floc[i] + Ffix[i] for i in range(6)]
                w = rod.get('udl', 0.0) * 1e3
                _, wt = udl_local_components(rod, c, s, w)
                w_t_kn = wt / 1e3

            # Store transverse components of point loads in local coordinates
            # so the V/M diagram can show their discontinuities exactly.
            point_local = []
            for pl in rod.get('point_loads', []):
                pang = math.radians(float(pl.get('angle_deg', 90.0)))
                pfx = float(pl.get('P', 0.0))*math.cos(pang)
                pfy = float(pl.get('P', 0.0))*math.sin(pang)
                pt_kn = -s*pfx + c*pfy
                point_local.append({'t': max(0.0, min(1.0, float(pl.get('t', 0.5)))),
                                    'pt': pt_kn})
            # Report V/M in the same physical convention as BeamResult:
            # V is positive upward on the left cut and M is sagging-positive.
            # `floc` instead contains the element's nodal actions, whose
            # left-end transverse and moment components have the opposite
            # signs under this reporting convention.
            rod_res.append({'force': floc[3]/1e3, 'V': -floc[1]/1e3,
                             'Ma': floc[2]/1e3, 'Mb': floc[5]/1e3, 'conn': 'rigid',
                             'w_t': w_t_kn, 'point_loads_local': point_local,
                             'length_m': Lm})

    reactions = {}
    KU = [sum(K[i][j]*Uf[j] for j in range(dof)) for i in range(dof)]
    for sp in supports:
        ni = sp['node']
        ux_i, uy_i, th_i = dof_of[ni]
        rxn = reactions.setdefault(ni, {'rx': 0.0, 'ry': 0.0, 'm': 0.0, 'type': sp['type']})
        if sp['type'] in ('pin', 'rollerY', 'fixed'):
            rxn['rx'] = (KU[ux_i] - F[ux_i]) / 1e3
        if sp['type'] in ('pin', 'rollerX', 'fixed'):
            rxn['ry'] = (KU[uy_i] - F[uy_i]) / 1e3
        if sp['type'] == 'fixed' and th_i is not None:
            rxn['m'] = (KU[th_i] - F[th_i]) / 1e3

    node_vectors = compute_node_force_vectors(nodes, rods, rod_res)

    return {'node_res': node_res, 'rod_res': rod_res, 'reactions': reactions,
            'node_vectors': node_vectors}, None


def compute_node_force_vectors(nodes, rods, rod_res):
    """
    For every node, compute the individual force vector that each connected
    rod applies to that node — this is exactly the set of forces that must be
    resisted by a welded gusset/node plate.

    Convention (matches the rest of the app's CAD readouts — coordinates,
    ruler, polar angle): global X→ positive to the right, global Y↑ positive
    upward, angle measured counter-clockwise from +X, in degrees [0, 360).

    Sign rule: a rod in tension (force > 0) PULLS the node toward the rod's
    far end; a rod in compression (force < 0) PUSHES the node away from the
    far end.

    Returns:
        { node_idx: [ {rod, other, force, kind, Fx, Fy, magnitude, angle_deg}, ... ] }
        - rod:        rod index
        - other:      index of the node at the far end of that rod
        - force:      signed axial force in the rod (kN), + tension / - compression
        - kind:       'T' (tension) / 'C' (compression) / '0' (~zero)
        - Fx, Fy:     components (kN) of the force this rod exerts ON the node,
                      in global (Y-up) coordinates
        - magnitude:  |force| (kN)
        - angle_deg:  direction of (Fx, Fy) w.r.t. global +X axis, CCW, degrees
    """
    node_vectors = {i: [] for i in range(len(nodes))}
    for ri, rod in enumerate(rods):
        a, b = rod['a'], rod['b']
        na, nb = nodes[a], nodes[b]
        dx, dy = nb[0] - na[0], nb[1] - na[1]      # canvas coords (y down)
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        ux, uy = dx / L, -dy / L                    # unit vector a→b, global (y up)
        f = rod_res[ri]['force']                     # kN, + tension / - compression
        kind = 'T' if f > 0.01 else ('C' if f < -0.01 else '0')

        # force ON node a: tension pulls it toward b -> +f*unit(a->b)
        FxA, FyA = f * ux, f * uy
        node_vectors[a].append({
            'rod': ri, 'other': b, 'force': f, 'kind': kind,
            'Fx': FxA, 'Fy': FyA, 'magnitude': abs(f),
            'angle_deg': math.degrees(math.atan2(FyA, FxA)) % 360,
        })

        # force ON node b: tension pulls it toward a -> -f*unit(a->b)
        FxB, FyB = -f * ux, -f * uy
        node_vectors[b].append({
            'rod': ri, 'other': a, 'force': f, 'kind': kind,
            'Fx': FxB, 'Fy': FyB, 'magnitude': abs(f),
            'angle_deg': math.degrees(math.atan2(FyB, FxB)) % 360,
        })
    return node_vectors


def compute_diagrams(nodes, rods, loads, analysis_result=None):
    """Compute member shear/moment diagrams from the same FEM result used by
    ``analyze()``.

    The previous implementation treated every member as an isolated simply
    supported beam and only considered nodal loads.  That is incompatible
    with the rigid-member FEM model: it ignored member UDLs and member point
    loads and could therefore display a diagram different from the solved
    member forces.

    For rigid members we reconstruct V(x), M(x) from the actual local end
    forces plus the exact member-load contributions.  Pinned truss bars keep
    zero shear/moment diagrams.
    """
    diagrams = []
    N_PTS = 240
    rod_res = analysis_result.get('rod_res', []) if analysis_result else []

    for ri, rod in enumerate(rods):
        na, nb = nodes[rod['a']], nodes[rod['b']]
        dx, dy = nb[0] - na[0], nb[1] - na[1]
        L_px = math.hypot(dx, dy)
        Lm = L_px / PX_PER_M if L_px >= 1 else 1.0

        if L_px < 1 or rod.get('conn', 'pin') != 'rigid' or ri >= len(rod_res):
            xs = [0.0, Lm]
            diagrams.append({'xs': xs, 'V': [0.0, 0.0], 'M': [0.0, 0.0], 'Lm': Lm,
                             'RA': 0.0, 'RB': 0.0})
            continue

        rr = rod_res[ri]
        V1 = float(rr.get('V', 0.0)) * 1000.0       # N
        M1 = float(rr.get('Ma', 0.0)) * 1e3         # kN*m -> N*m
        wt = float(rr.get('w_t', 0.0)) * 1000.0     # N/m
        pts = rr.get('point_loads_local', [])

        xs = [k / (N_PTS - 1) * Lm for k in range(N_PTS)]
        for pl in pts:
            xp = max(0.0, min(Lm, float(pl.get('t', 0.5)) * Lm))
            xs.extend([max(0.0, xp - Lm/N_PTS), xp, min(Lm, xp + Lm/N_PTS)])
        # Add every exact stationary point of M(x), so the reported maximum
        # is not dependent on the drawing resolution.  Between point loads
        # V(x) is linear, therefore M has an extremum wherever V(x)=0.
        if abs(wt) > 1e-12:
            break_x = [0.0] + sorted(
                max(0.0, min(Lm, float(pl.get('t', 0.5)) * Lm)) for pl in pts
            ) + [Lm]
            for left, right in zip(break_x, break_x[1:]):
                p_before = sum(float(pl.get('pt', 0.0)) * 1e3 for pl in pts
                               if float(pl.get('t', 0.5)) * Lm <= left + 1e-10)
                x_zero_v = (V1 - p_before) / wt
                if left + 1e-10 < x_zero_v < right - 1e-10:
                    xs.append(x_zero_v)
        xs = sorted(set(xs))

        V = []
        M = []
        for x in xs:
            # Same sign convention as BeamResult: dM/dx = V and a positive
            # transverse member load (the UI's down direction on a horizontal
            # rod) reduces V along the member.
            v = V1 - wt * x
            m = M1 + V1 * x - wt * x * x / 2.0
            for pl in pts:
                xp = max(0.0, min(Lm, float(pl.get('t', 0.5)) * Lm))
                p = float(pl.get('pt', 0.0)) * 1000.0
                if xp <= x:
                    v -= p
                    m -= p * (x - xp)
            V.append(v / 1000.0)
            M.append(m / 1e3)

        diagrams.append({'xs': xs, 'V': V, 'M': M, 'Lm': Lm,
                         'RA': V1/1000.0, 'RB': (V[-1] if V else 0.0)})

    return diagrams

