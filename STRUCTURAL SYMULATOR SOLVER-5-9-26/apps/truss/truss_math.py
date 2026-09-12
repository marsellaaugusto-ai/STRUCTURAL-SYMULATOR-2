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


def find_zero_crossings(xs, values):
    """Return every x-position where a sampled curve crosses zero, using the
    same linear-interpolation crossing formula already used by the
    Vierendeel V/M band renderer (`draw_band` in truss_app.py): for a sign
    change between consecutive samples, interpolate the exact x where the
    line between them hits zero. `xs` must be sorted ascending and the same
    length as `values`. Used both to mark points of contraflexure on the
    deformed shape and to split a member into single-sign tension/
    compression fiber segments.
    """
    crossings = []
    for i in range(1, len(xs)):
        x0, x1 = xs[i-1], xs[i]
        v0, v1 = values[i-1], values[i]
        if v0 == 0.0 and (i == 1 or values[i-2] != 0.0):
            crossings.append(x0)
        elif v0 * v1 < 0:
            frac = -v0 / (v1 - v0)
            crossings.append(x0 + frac * (x1 - x0))
    if values and values[-1] == 0.0 and (len(values) < 2 or values[-2] != 0.0):
        crossings.append(xs[-1])
    return crossings


def deformed_shape_points(nodes, rods, node_res, rod_res, def_scale, n=24):
    """Return, per rod, a polyline of (x, y) points (same pixel/world space
    as `nodes`) along the scaled deformed shape.

    Pin rods (or any rod without a rigid `rod_res` entry) get the same
    straight-line-between-scaled-endpoints treatment as before -- a pin bar
    cannot bend. Rigid rods get the true Euler-Bernoulli cubic (Hermite)
    bending curve, driven by the already-solved end DOFs: axial elongation
    linearly interpolated, transverse deflection from the standard Hermite
    shape functions using each end's local transverse displacement AND its
    solved rotation `theta` (this is exactly the same 4-DOF (v_a, theta_a,
    v_b, theta_b) beam element `analyze()` already assembles into `kb` --
    this function only evaluates its deflection shape, not new physics).

    At t=0 and t=1 this reduces EXACTLY to the previous straight-line
    endpoints (N1(0)=1 and N3(1)=1 with all else zero recovers the plain
    ux/uy scaled offset), so this is a strict refinement, not a behavior
    change, at the two ends.

    Known simplification: this uses only the end-DOF Hermite cubic and does
    not add the particular-solution bulge from member loads (a UDL or point
    load along the rod's own span). For nodal loads this is exact; for
    member-loaded rigid rods it is a good approximation of the true elastic
    curve but omits that additional term.
    """
    out = []
    for ri, rod in enumerate(rods):
        na, nb = nodes[rod['a']], nodes[rod['b']]
        ra, rb = node_res[rod['a']], node_res[rod['b']]
        dx, dy = nb[0]-na[0], nb[1]-na[1]
        L = math.hypot(dx, dy)

        uxa_m, uya_m = ra['ux']/1000.0, ra['uy']/1000.0
        uxb_m, uyb_m = rb['ux']/1000.0, rb['uy']/1000.0

        rr = rod_res[ri] if ri < len(rod_res) else None
        is_rigid = bool(rr) and rr.get('conn', 'pin') == 'rigid' and L >= 1

        if not is_rigid:
            ax = na[0] + uxa_m*PX_PER_M*def_scale
            ay = na[1] + uya_m*PX_PER_M*def_scale
            bx = nb[0] + uxb_m*PX_PER_M*def_scale
            by = nb[1] + uyb_m*PX_PER_M*def_scale
            out.append([(ax, ay), (bx, by)])
            continue

        c, s = dx/L, dy/L
        Lm = L / PX_PER_M
        u_a_local =  c*uxa_m + s*uya_m
        v_a_local = -s*uxa_m + c*uya_m
        u_b_local =  c*uxb_m + s*uyb_m
        v_b_local = -s*uxb_m + c*uyb_m
        theta_a = ra.get('theta', 0.0)
        theta_b = rb.get('theta', 0.0)

        pts = []
        for k in range(n):
            t = k / (n-1)
            N1 = 1 - 3*t*t + 2*t**3
            N2 = (t - 2*t*t + t**3) * Lm
            N3 = 3*t*t - 2*t**3
            N4 = (-t*t + t**3) * Lm
            u_local = u_a_local*(1-t) + u_b_local*t
            v_local = N1*v_a_local + N2*theta_a + N3*v_b_local + N4*theta_b
            du_x = c*u_local - s*v_local
            du_y = s*u_local + c*v_local
            px = na[0] + t*dx + du_x*PX_PER_M*def_scale
            py = na[1] + t*dy + du_y*PX_PER_M*def_scale
            pts.append((px, py))
        out.append(pts)
    return out


def deformed_point_at(na, nb, ra, rb, rr, def_scale, t):
    """Same Hermite evaluation as `deformed_shape_points`, but for a single
    fraction `t` in [0,1] along one rod -- used to place a marker (e.g. a
    contraflexure point) at an exact x found from the moment diagram,
    rather than snapping to the nearest of that function's fixed samples.
    """
    dx, dy = nb[0]-na[0], nb[1]-na[1]
    L = math.hypot(dx, dy)
    uxa_m, uya_m = ra['ux']/1000.0, ra['uy']/1000.0
    uxb_m, uyb_m = rb['ux']/1000.0, rb['uy']/1000.0
    is_rigid = bool(rr) and rr.get('conn', 'pin') == 'rigid' and L >= 1
    if not is_rigid:
        ax = na[0] + uxa_m*PX_PER_M*def_scale
        ay = na[1] + uya_m*PX_PER_M*def_scale
        bx = nb[0] + uxb_m*PX_PER_M*def_scale
        by = nb[1] + uyb_m*PX_PER_M*def_scale
        return (ax + (bx-ax)*t, ay + (by-ay)*t)
    c, s = dx/L, dy/L
    Lm = L / PX_PER_M
    u_a_local =  c*uxa_m + s*uya_m
    v_a_local = -s*uxa_m + c*uya_m
    u_b_local =  c*uxb_m + s*uyb_m
    v_b_local = -s*uxb_m + c*uyb_m
    theta_a = ra.get('theta', 0.0)
    theta_b = rb.get('theta', 0.0)
    N1 = 1 - 3*t*t + 2*t**3
    N2 = (t - 2*t*t + t**3) * Lm
    N3 = 3*t*t - 2*t**3
    N4 = (-t*t + t**3) * Lm
    u_local = u_a_local*(1-t) + u_b_local*t
    v_local = N1*v_a_local + N2*theta_a + N3*v_b_local + N4*theta_b
    du_x = c*u_local - s*v_local
    du_y = s*u_local + c*v_local
    px = na[0] + t*dx + du_x*PX_PER_M*def_scale
    py = na[1] + t*dy + du_y*PX_PER_M*def_scale
    return (px, py)


def compute_fiber_stress(rod, rod_res_entry, Ms):
    """
    Combined axial + bending fiber stress along a rigid member, at the same
    station values used for `M` (i.e. call with `diagrams[i]['M']`).

    Returns (sigma_neg, sigma_pos): two lists, same length as `Ms`, in MPa
    (tension positive / compression negative). `sigma_neg` is the stress on
    the "local -v" side of the member -- for a horizontal member this is
    the physically-TOP fiber -- and `sigma_pos` is the "local +v" (bottom,
    for a horizontal member) side. These are exactly the local transverse
    axis and offset direction (nx, ny) = (-dy/L, dx/L) already used to draw
    the Vierendeel moment band in `_draw_vierendeel_diagram`, so a "+v side"
    fiber band renders on the same visual side as that existing diagram's
    positive-moment lobe.

    Sign check (matches the sagging-positive convention used throughout
    this module): for a horizontal member with a positive (sagging) M, the
    top fiber (local -v side) is in compression and the bottom (local +v
    side) is in tension -- the classic isostatic-beam-under-downward-load
    picture. Verified numerically against a simply-supported rigid rod
    under a downward UDL in `tests/`.

    Section depth is not stored explicitly in a rod's profile (only E, A,
    I) -- this approximates it from a rectangular-section idealization:
    h = sqrt(12*I/A), c = h/2 = sqrt(3*I/A). This is an approximation for
    non-rectangular real sections (I-beams, tubes, etc.); if the app's
    profile data is ever extended with an explicit section depth or Zx,
    prefer that instead.
    """
    A = rod.get('A', 10.0)   # cm^2
    I = rod.get('I', 8000.0)  # cm^4
    N = rod_res_entry.get('force', 0.0)  # kN, +tension/-compression
    if A <= 0:
        A = 10.0
    if I <= 0:
        I = 8000.0
    c = math.sqrt(3.0 * I / A)  # cm

    sigma_axial = 10.0 * N / A  # MPa  (10 = unit-conversion constant, see docstring math)
    sigma_neg, sigma_pos = [], []
    for M in Ms:
        sigma_bend = 1000.0 * M * c / I  # MPa
        sigma_neg.append(sigma_axial - sigma_bend)
        sigma_pos.append(sigma_axial + sigma_bend)
    return sigma_neg, sigma_pos


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
    node_moments = compute_node_moments(nodes, rods, rod_res)

    return {'node_res': node_res, 'rod_res': rod_res, 'reactions': reactions,
            'node_vectors': node_vectors, 'node_moments': node_moments}, None


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


def compute_node_moments(nodes, rods, rod_res):
    """
    For every node, the moment each connected RIGID rod applies to that
    node (the joint moment a Vierendeel connection has to carry), plus two
    summary numbers:

    - 'net': the SUM of the connected rods' end moments. This is an
      EQUILIBRIUM CHECK, not a design quantity -- at any free joint (no
      fixed support, no directly-applied moment load there), moment
      equilibrium of the joint itself guarantees this sums to ~0 no matter
      how much individual moment each connected rod carries. It only reads
      nonzero at a node with a fixed support (where the missing term is
      that support's reaction moment) or at a node with an applied moment
      load. Seeing 'net' ~0 everywhere in a Vierendeel frame is EXPECTED
      and does not mean the joints carry no moment.
    - 'max_abs': the largest individual |moment| among the connected rods,
      and 'max_abs_rod': which rod it came from. THIS is the number that
      answers "how much moment does this joint actually have to resist" --
      the quantity a Vierendeel connection needs to be designed for.

    Convention: `rod_res[i]['Ma']` is the moment at rod i's end A, `Mb` at
    end B (kN*m, same sign convention used throughout this module and
    matched against the standalone Beam app). If the node is end A of a
    rod, that rod contributes `Ma`; if end B, it contributes `Mb`. Pin rods
    always contribute 0.0 (they carry no bending by construction) and are
    still listed, so it is visually distinguishable at a glance which of a
    node's rods carry no moment at all versus which happen to have solved
    to a small value.

    Returns:
        { node_idx: {'members': [ {rod, other, conn, moment}, ... ],
                      'net': <sum of member moments>,
                      'max_abs': <largest |moment| among members>,
                      'max_abs_rod': <that rod's index, or None>} }
    """
    node_moments = {i: {'members': [], 'net': 0.0, 'max_abs': 0.0, 'max_abs_rod': None}
                     for i in range(len(nodes))}
    for ri, rod in enumerate(rods):
        a, b = rod['a'], rod['b']
        if ri >= len(rod_res):
            continue
        rr = rod_res[ri]
        is_rigid = rr.get('conn', 'pin') == 'rigid'
        Ma = float(rr.get('Ma', 0.0)) if is_rigid else 0.0
        Mb = float(rr.get('Mb', 0.0)) if is_rigid else 0.0

        node_moments[a]['members'].append({'rod': ri, 'other': b,
                                            'conn': rr.get('conn', 'pin'), 'moment': Ma})
        node_moments[a]['net'] += Ma
        node_moments[b]['members'].append({'rod': ri, 'other': a,
                                            'conn': rr.get('conn', 'pin'), 'moment': Mb})
        node_moments[b]['net'] += Mb

    for ni, data in node_moments.items():
        if data['members']:
            best = max(data['members'], key=lambda m: abs(m['moment']))
            data['max_abs'] = abs(best['moment'])
            data['max_abs_rod'] = best['rod']
            data['max_signed'] = best['moment']  # signed value, for arc direction
        else:
            data['max_signed'] = 0.0
    return node_moments



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

