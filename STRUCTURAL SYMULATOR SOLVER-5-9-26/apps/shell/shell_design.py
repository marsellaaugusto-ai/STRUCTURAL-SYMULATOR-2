"""shell_design.py -- reinforced-concrete design of the shell, element by
element, and the thickness each element needs. 2026-09-14.

No Tkinter. Every code number comes from the DesignCode object
(shell_codes.py); this module holds only the METHOD.

THE METHOD, per element and per strength combination
----------------------------------------------------

Forces come in the element's local axes (e1 ~ x in plan, e2 ~ y), in SI:
N = (Nx, Ny, Nxy) N/m tension +, M = (Mx, My, Mxy) N*m/m + = tension at the
bottom face, Q = (Qx, Qy) N/m.

Two reinforcement layouts, chosen per element ('auto' picks two meshes where
the thickness leaves room for them, one central mesh otherwise):

  TWO MESHES (top + bottom) -- the sandwich model. The section is idealised
  as two outer layers, each centred on its steel (distance a = cover + db
  from its face), with lever arm z = t - 2a between them. Each layer takes

        n_top = N/2 - M/z          n_bot = N/2 + M/z      (x, y, xy alike)

  and is reinforced in x and y for those in-plane forces by the yield-line
  ("Nielsen") rule for orthogonal steel:

        both steel forces   nx + |nxy|,  ny + |nxy|,  concrete 2|nxy|
        if nx < -|nxy|:     x steel 0,  y steel ny + nxy^2/|nx|,
                            concrete |nx| + nxy^2/|nx|      (and y <-> x)
        both principal forces compressive: no steel, concrete |n2|

  The concrete force is checked on a layer 2a thick against the strut
  strength (0.85 beta_s f'c phi). This satisfies the shell rule that steel in
  two directions resist the component of the internal forces in each
  (19.4.2) and that bending be designed with the simultaneous membrane force
  (19.4.9).

  ONE CENTRAL MESH -- the membrane steel by the same Nielsen rule on N, plus
  bending about the central steel: the moment M* = |M| + |Mxy| (Wood-Armer,
  both signs, since the steel is at mid-depth) needs a compression block C
  at one face with lever arm t/2 - a_c/2:

        C (t/2 - C/(1.7 f'c)) = M*/phi       ->  C (quadratic)

  and the steel carries the membrane force plus C. If the quadratic has no
  root, a single mesh cannot carry that moment at this thickness.

Also per element: transverse shear against phi Vc (no shear reinforcement in
a thin shell), buckling (below), bar spacing, and the minimum steel.

BUCKLING. The code requires shell buckling to be investigated and gives no
formula. The classical critical membrane compression of a shallow shell,

        N_cr = E t^2 |k_n| / sqrt(3 (1 - nu^2))

with k_n the normal curvature of the surface along the compressive
principal direction, is reduced by a user factor (default 0.20: imperfection
sensitivity, creep and cracking together; set it from the literature for
the form at hand). Where the surface is flat in that direction the plate
value 4 pi^2 D / L^2 is used instead.

THE THICKNESS EACH ELEMENT NEEDS. With the element's forces held fixed, the
checks are re-run at every candidate thickness from the detailing minimum
up, and the smallest that passes is `t_req`. Forces do change when the
shell is made thicker (a thicker patch attracts load and weighs more), which
is why automatic thickening re-analyses and repeats (`auto_thicken`).
"""
import math

import numpy as np

# checks made element by element (and re-made at every trial thickness)
ELEMENT_CHECKS = ('steel', 'concrete', 'bending', 'shear', 'buckling', 'spacing')
# ... plus the shear into each support block / column head, which is a check
# on the RING of elements around the block and is folded into their numbers
CHECKS = ELEMENT_CHECKS + ('punching',)
# the structural checks -- everything except the detailing minimum, which is
# a near-constant ratio (thickness for the meshes / thickness) and would
# otherwise colour the whole shell the same
STRUCTURAL_CHECKS = tuple(k for k in CHECKS if k != 'spacing')
CHECK_LABELS = {
    'punching': 'shear into a support block / column head',
    'steel': 'reinforcement fits (bars no closer than 75 mm)',
    'concrete': 'concrete compression in the shell',
    'bending': 'bending with one central mesh',
    'shear': 'transverse shear (no stirrups)',
    'buckling': 'shell buckling',
    'spacing': 'room for the meshes and cover (detailing minimum)',
}
BARS_MM = (6.0, 8.0, 10.0, 12.0, 16.0)
S_MIN_MM = 75.0


def _nielsen(nx, ny, nxy):
    """Orthogonal steel forces (fx, fy) and concrete compression force fc,
    all >= 0, per unit width, for in-plane forces (tension +)."""
    a = np.abs(nxy)
    fx = nx + a
    fy = ny + a
    fc = 2 * a
    with np.errstate(divide='ignore', invalid='ignore'):
        cx = nx < -a                                   # x strongly compressed
        fy_x = ny + np.where(cx, nxy ** 2 / np.where(cx, -nx, 1.0), 0.0)
        fc_x = np.where(cx, -nx + nxy ** 2 / np.where(cx, -nx, 1.0), 0.0)
        cy = ny < -a
        fx_y = nx + np.where(cy, nxy ** 2 / np.where(cy, -ny, 1.0), 0.0)
        fc_y = np.where(cy, -ny + nxy ** 2 / np.where(cy, -ny, 1.0), 0.0)
    fx = np.where(cx, 0.0, np.where(cy, fx_y, fx))
    fy = np.where(cy, 0.0, np.where(cx, fy_x, fy))
    fc = np.where(cx, fc_x, np.where(cy, fc_y, fc))
    # biaxial compression: no steel, concrete takes the larger compression
    c = 0.5 * (nx + ny)
    r = np.sqrt((0.5 * (nx - ny)) ** 2 + nxy ** 2)
    n1, n2 = c + r, c - r
    both = n1 <= 0
    fx = np.where(both | (fx < 0), 0.0, fx)
    fy = np.where(both | (fy < 0), 0.0, fy)
    fc = np.where(both, -n2, fc)
    return fx, fy, np.maximum(fc, 0.0)


class DesignSettings:
    def __init__(self, model):
        d = model.data['design']
        mat = model.data['material']
        self.code = model.code
        self.fc = float(mat['fc'])
        self.fy = min(float(mat['fy']), self.code.fy_max_shell)
        self.nu = float(mat.get('nu', 0.2))
        self.cover = float(d['cover_cm']) / 100.0
        self.db = float(d['bar_mm']) / 1000.0
        self.layout = d.get('layout', 'auto')
        self.kb = float(d.get('buckling_factor', 0.2))
        self.t_min = float(d.get('t_min', 0.05))
        self.t_max = float(d.get('t_max', 0.40))
        self.t_step = float(d.get('t_step', 0.01))
        self.cover_min = self.code.min_cover_mm(
            float(d['bar_mm']), bool(d.get('exposed', True)),
            bool(d.get('controlled', True)), float(d.get('exposure_factor', 1.0))) / 1000.0

    # detailing minimum thicknesses
    @property
    def a_face(self):
        """Face to centroid of that face's two crossing bar layers (m)."""
        return self.cover + self.db

    @property
    def t_single_min(self):
        return 2 * self.cover + 2 * self.db

    @property
    def t_two_min(self):
        return 2 * (self.cover + 2 * self.db) + 0.02     # 20 mm clear between meshes

    def layout_for(self, t):
        if self.layout == 'two':
            return np.ones_like(t, bool)
        if self.layout == 'single':
            return np.zeros_like(t, bool)
        return t >= self.t_two_min - 1e-9


def _surface_curvature(model, xc, yc):
    """f_x, f_y, f_xx, f_xy, f_yy of the surface at the given plan points,
    by central differences on the user's formula."""
    f = model.surface_fn()
    x0, x1, y0, y1 = model.plan_limits()
    h = 1e-3 * max(x1 - x0, y1 - y0)
    fxp, fxm = f(xc + h, yc), f(xc - h, yc)
    fyp, fym = f(xc, yc + h), f(xc, yc - h)
    f0 = f(xc, yc)
    fx = (fxp - fxm) / (2 * h)
    fy = (fyp - fym) / (2 * h)
    fxx = (fxp - 2 * f0 + fxm) / h ** 2
    fyy = (fyp - 2 * f0 + fym) / h ** 2
    fxy = (f(xc + h, yc + h) - f(xc + h, yc - h) - f(xc - h, yc + h)
           + f(xc - h, yc - h)) / (4 * h * h)
    return fx, fy, fxx, fxy, fyy


def _normal_curvature(geo, dx, dy):
    fx, fy, fxx, fxy, fyy = geo
    W = np.sqrt(1 + fx ** 2 + fy ** 2)
    num = fxx * dx ** 2 + 2 * fxy * dx * dy + fyy * dy ** 2
    den = (1 + fx ** 2) * dx ** 2 + 2 * fx * fy * dx * dy + (1 + fy ** 2) * dy ** 2
    return num / (W * np.where(den > 0, den, 1.0))


class _ElementState:
    """Geometry and forces shared by every thickness trial."""

    def __init__(self, model, res, st):
        fem = res.fem
        sh = fem['shells']
        self.t = sh.a.copy()
        self.E = fem['E']
        self.E_buck = fem['E_eff_buckling']
        cen = fem['mesh']['centroids']
        self.xc, self.yc = cen[:, 0], cen[:, 1]
        self.e1, self.e2, _ = res.frame
        self.geo = _surface_curvature(model, self.xc, self.yc)
        x0, x1, y0, y1 = fem['mesh']['plan']
        self.L_plate = min(x1 - x0, y1 - y0)
        self.plan = (x0, x1, y0, y1)
        self.combos = res.combos
        self.forces = [res.combo_forces(c) for c in res.combos]
        self.in_head = res.fem.get('in_head', np.zeros(len(self.t), bool))
        sh = res.fem['shells']
        # per column head / support block: the ring of shell elements touching
        # it, and (columns only) the shear the shell delivers into it, per
        # combination -- the punching shear
        self.heads = []
        for hd in res.fem.get('heads', []):
            head = set(hd['head_nodes'])
            inside = set(hd['head_elems'])
            ring = [e for e in range(sh.ne) if e not in inside
                    and any(int(n) in head for n in sh.elems[e])]
            V = [res.head_shear(c, hd) for c in res.combos]
            self.heads.append({'col': hd, 'ring': np.array(ring, int), 'V': V})


def _check_at(st, S, forces, t):
    """All checks for one combination at thickness t (array, per element).
    Returns (utilisations dict, steel dict)."""
    code = S.code
    fc_pa = S.fc * 1e6
    fy_pa = S.fy * 1e6
    phi_t = code.phi_tension
    two = S.layout_for(t)
    Nx, Ny, Nxy = forces['Nx'], forces['Ny'], forces['Nxy']
    Mx, My, Mxy = forces['Mx'], forces['My'], forces['Mxy']
    Qx, Qy = forces['Qx'], forces['Qy']
    util = {}
    steel = {}

    # ---- two meshes: sandwich ------------------------------------------------
    a = S.a_face
    z = np.maximum(t - 2 * a, 1e-3)
    lay_t = 2 * a
    fxT, fyT, fcT = _nielsen(Nx / 2 - Mx / z, Ny / 2 - My / z, Nxy / 2 - Mxy / z)
    fxB, fyB, fcB = _nielsen(Nx / 2 + Mx / z, Ny / 2 + My / z, Nxy / 2 + Mxy / z)
    f_strut_cr = code.strut_strength(S.fc, True) * 1e6
    f_strut_un = code.strut_strength(S.fc, False) * 1e6
    crT = (fxT > 0) | (fyT > 0)
    crB = (fxB > 0) | (fyB > 0)
    u_conc2 = np.maximum(fcT / lay_t / np.where(crT, f_strut_cr, f_strut_un),
                         fcB / lay_t / np.where(crB, f_strut_cr, f_strut_un))
    As2 = {k: v / (phi_t * fy_pa) for k, v in
           (('x_top', fxT), ('y_top', fyT), ('x_bot', fxB), ('y_bot', fyB))}

    # ---- one central mesh ------------------------------------------------------
    fxM, fyM, fcM = _nielsen(Nx, Ny, Nxy)
    u_conc1 = fcM / t / np.where((fxM > 0) | (fyM > 0), f_strut_cr, f_strut_un)
    phi_f = phi_t
    ok_b = np.ones_like(t, bool)
    Cs = []
    for M_ in (np.abs(Mx) + np.abs(Mxy), np.abs(My) + np.abs(Mxy)):
        k = 1.7 * fc_pa
        disc = (t / 2) ** 2 - 4 * (M_ / phi_f) / k
        C = np.where(disc >= 0, (t / 2 - np.sqrt(np.maximum(disc, 0))) * k / 2, np.inf)
        ok_b &= disc >= 0
        Cs.append(C)
    # bending utilisation: moment / capacity with all the section can give
    Mcap = (t / 2) ** 2 * 1.7 * fc_pa / 4 * phi_f        # at the vertex of the quadratic
    u_bend1 = np.maximum(np.abs(Mx) + np.abs(Mxy), np.abs(My) + np.abs(Mxy)) / Mcap
    As1x = np.where(np.isfinite(Cs[0]), (fxM / phi_t + Cs[0]) / fy_pa, np.inf)
    As1y = np.where(np.isfinite(Cs[1]), (fyM / phi_t + Cs[1]) / fy_pa, np.inf)

    # ---- minimum steel, one-face mirror, congestion ------------------------------
    As_min = code.rho_min(S.fy) * t                      # m^2/m per direction, total
    half = As_min / 2
    out = {}
    for d_ in ('x', 'y'):
        top = np.maximum(As2[f'{d_}_top'], half)
        bot = np.maximum(As2[f'{d_}_bot'], half)
        need_t = As2[f'{d_}_top'] > half
        need_b = As2[f'{d_}_bot'] > half
        one = need_t ^ need_b                            # 19.4.9: mirror one-face steel
        both = np.maximum(top, bot)
        out[f'{d_}_top'] = np.where(one, both, top)
        out[f'{d_}_bot'] = np.where(one, both, bot)
    mid_x = np.maximum(As1x, As_min)
    mid_y = np.maximum(As1y, As_min)
    for k_ in ('x_top', 'y_top', 'x_bot', 'y_bot'):
        steel[k_] = np.where(two, out[k_], np.nan)
    steel['x_mid'] = np.where(two, np.nan, mid_x)
    steel['y_mid'] = np.where(two, np.nan, mid_y)

    # largest steel area in one layer and direction, against the most a
    # layer can hold (16 mm bars at 75 mm)
    cap = math.pi * 0.016 ** 2 / 4 / (S_MIN_MM / 1000.0)
    worst_layer = np.where(two, np.maximum.reduce([out['x_top'], out['y_top'],
                                                   out['x_bot'], out['y_bot']]),
                           np.maximum(mid_x, mid_y))
    util['steel'] = worst_layer / cap

    util['concrete'] = np.where(two, u_conc2, u_conc1)
    util['bending'] = np.where(two, 0.0, np.where(ok_b, u_bend1, np.maximum(u_bend1, 1.0 + 1e-9)))

    # ---- transverse shear ---------------------------------------------------------
    q = np.hypot(Qx, Qy)
    alongx = np.abs(Qx) >= np.abs(Qy)
    d_eff = np.where(two, t - a, t / 2)
    As_dir = np.where(two,
                      np.where(alongx, np.maximum(out['x_top'], out['x_bot']),
                               np.maximum(out['y_top'], out['y_bot'])),
                      np.where(alongx, mid_x, mid_y))
    rho_w = np.minimum(As_dir / np.maximum(d_eff, 1e-4), 0.05)
    Nu_comp = -np.where(alongx, Nx, Ny)
    Vc = code.Vc(S.fc, d_eff, rho_w, Nu_comp, t)
    with np.errstate(divide='ignore', invalid='ignore'):
        util['shear'] = np.where(Vc > 0, q / (code.phi_shear * Vc), np.where(q > 1e-6, np.inf, 0.0))
    for hd in st.heads:
        xt, yt = hd['col']['xy']
        reach = hd['col']['cap_eff'] / 2 + d_eff          # one-way shear from d outside the face
        near = (np.abs(st.xc - xt) <= reach) & (np.abs(st.yc - yt) <= reach)
        util['shear'] = np.where(near, 0.0, util['shear'])

    # ---- buckling ---------------------------------------------------------------
    c = 0.5 * (Nx + Ny)
    r = np.sqrt((0.5 * (Nx - Ny)) ** 2 + Nxy ** 2)
    n2 = c - r
    th1 = 0.5 * np.arctan2(2 * Nxy, Nx - Ny)
    th2 = th1 + math.pi / 2
    v = np.cos(th2)[:, None] * st.e1 + np.sin(th2)[:, None] * st.e2
    kn = np.abs(_normal_curvature(st.geo, v[:, 0], v[:, 1]))
    nu = S.nu
    N_shell = st.E_buck * t ** 2 * kn / math.sqrt(3 * (1 - nu ** 2))
    D = st.E_buck * t ** 3 / (12 * (1 - nu ** 2))
    N_plate = 4 * math.pi ** 2 * D / st.L_plate ** 2
    N_cr = S.kb * np.maximum(N_shell, N_plate)
    util['buckling'] = np.where(n2 < 0, -n2 / N_cr, 0.0)

    # ---- detailing: room for the meshes ----------------------------------------------
    t_need = np.where(two, S.t_two_min, S.t_single_min)
    util['spacing'] = t_need / t
    # elements inside a column head are part of the solid head, not the shell
    for k in util:
        util[k] = np.where(st.in_head, 0.0, util[k])
    return util, steel


def critical_perimeter(xy, half, plan):
    """Length of the square of half-side `half` around plan point `xy` that
    lies INSIDE the plan rectangle, not along its boundary, and the number of
    such sides. A block at a plan corner keeps 2 sides, at an edge 3, in the
    interior 4 -- as the code's critical section 'may extend to the free edge'
    (C 22.6.4.1)."""
    x, y = xy
    x0, x1, y0, y1 = plan
    xa, xb = max(x - half, x0), min(x + half, x1)
    ya, yb = max(y - half, y0), min(y + half, y1)
    if xb <= xa or yb <= ya:
        return 0.0, 0
    tol = 1e-9 * max(1.0, x1 - x0, y1 - y0)
    length, sides = 0.0, 0
    for inside, seg in ((x - half > x0 + tol, yb - ya), (x + half < x1 - tol, yb - ya),
                        (y - half > y0 + tol, xb - xa), (y + half < y1 - tol, xb - xa)):
        if inside:
            length += seg
            sides += 1
    return length, sides


def punching(st, S, t_ring=None):
    """Two-way (punching) shear around every column head AND every support
    block (22.6): the shear the shell delivers into the block -- summed from
    element nodal forces, which is independent of the mesh -- against the
    concrete strength on the critical section d/2 outside the block face,
    counting only the part of that section inside the shell. Returns one
    dict per block; `t_req` is the thickness of the surrounding ring that
    passes."""
    code = S.code
    out = []
    plan = st.plan
    for hd in st.heads:
        blk, ring = hd['col'], hd['ring']
        if not hd['V']:
            continue
        if t_ring is not None:
            tr = float(t_ring)
        else:
            tr = float(np.mean(st.t[ring])) if len(ring) else float(st.t.mean())
        Vu = max(hd['V'])

        def check(t):
            two = bool(S.layout_for(np.array([t]))[0])
            d = t - S.a_face if two else t / 2
            b0, sides = critical_perimeter(blk['xy'], blk['cap_eff'] / 2 + d / 2, plan)
            alpha = {4: 40.0, 3: 30.0}.get(sides, 20.0)
            if b0 <= 0:
                return np.inf, d, b0, 0.0, sides
            vc = code.punching_vc(S.fc, d, b0, alpha_s=alpha)
            cap_ = code.phi_shear * vc * 1e6 * b0 * d
            return (Vu / cap_ if cap_ > 0 else np.inf), d, b0, vc, sides
        u, d, b0, vc, sides = check(tr)
        t_req = np.inf
        for tc in np.arange(max(S.t_single_min, S.t_min), S.t_max + 1e-9, 0.005):
            if check(tc)[0] <= 1.0:
                t_req = float(np.ceil(np.round(tc / S.t_step, 6)) * S.t_step)
                break
        out.append({'kind': blk['kind'], 'index': blk.get('col', blk.get('support')),
                    'xy': blk['xy'], 'Vu': Vu, 'V_all': list(hd['V']), 't': tr, 'd': d, 'b0': b0, 'vc': vc,
                    'sides': sides, 'util': u, 't_req': t_req, 'ring': ring,
                    'cap': blk['cap'], 'cap_eff': blk['cap_eff'],
                    'coarse': blk['cap_eff'] < 0.7 * blk['cap']})
    return out


def design(model, res):
    """Design every element for every strength combination. Returns a
    ShellDesign with the steel, utilisations, thickness needed and the
    edge-beam checks."""
    S = DesignSettings(model)
    st = _ElementState(model, res, S)
    t = st.t
    ne = len(t)
    u_env = {k: np.zeros(ne) for k in CHECKS}
    gov_combo = {k: np.zeros(ne, int) for k in CHECKS}
    steel_env = None
    for ci, F in enumerate(st.forces):
        util, steel = _check_at(st, S, F, t)
        for k in ELEMENT_CHECKS:
            better = util[k] > u_env[k]
            u_env[k] = np.where(better, util[k], u_env[k])
            gov_combo[k] = np.where(better, ci, gov_combo[k])
        if steel_env is None:
            steel_env = {k: v.copy() for k, v in steel.items()}
        else:
            for k in steel:
                steel_env[k] = np.fmax(steel_env[k], steel[k])
    if not st.forces:
        steel_env = {k: np.full(ne, np.nan) for k in ('x_top', 'y_top', 'x_bot', 'y_bot', 'x_mid', 'y_mid')}
    punch = punching(st, S)
    for p in punch:
        if len(p['ring']):
            r = p['ring']
            u_env['punching'][r] = np.maximum(u_env['punching'][r], p['util'])
            gov_combo['punching'][r] = int(np.argmax(p['V_all'])) if p['V_all'] else 0
    u_max = np.max(np.stack([u_env[k] for k in CHECKS]), axis=0)
    gov = np.array(CHECKS)[np.argmax(np.stack([u_env[k] for k in CHECKS]), axis=0)]
    t_req = required_thickness(st, S, t)
    # an element that passes as it is needs no more than it has
    t_req = np.where(u_max <= 1.0 + 1e-9, np.minimum(t_req, t), t_req)
    for p in punch:
        if len(p['ring']):
            t_req[p['ring']] = np.maximum(t_req[p['ring']], p['t_req'])
    t_req = np.where(st.in_head, t, t_req)
    des = ShellDesign(model, res, S, u_env, gov_combo, u_max, gov, steel_env, t_req)
    des.punching = punch
    des.in_head = st.in_head
    return des


def required_thickness(st, S, t_now):
    """Smallest candidate thickness at which every check passes for every
    combination, with the forces held fixed. np.inf where none does."""
    lo = max(S.t_min, S.t_single_min)
    k0 = int(math.ceil(lo / S.t_step - 1e-9))
    k1 = int(math.floor(S.t_max / S.t_step + 1e-9))
    grid = [k * S.t_step for k in range(k0, k1 + 1)]
    cands = np.unique(np.round(np.array([lo, S.t_two_min] + grid), 6))
    cands = cands[(cands >= lo - 1e-9) & (cands <= S.t_max + 1e-9)]
    ne = len(t_now)
    t_req = np.full(ne, np.inf)
    for tc in cands:
        tt = np.full(ne, tc)
        ok = np.ones(ne, bool)
        for F in st.forces:
            util, _ = _check_at(st, S, F, tt)
            for k in ELEMENT_CHECKS:
                ok &= util[k] <= 1.0 + 1e-9
        t_req = np.where(np.isinf(t_req) & ok, tc, t_req)
        if np.all(np.isfinite(t_req)):
            break
    return t_req


def suggest_bars(As_m2_per_m, t, S):
    """(bar diameter mm, spacing mm) for a steel area per metre, respecting
    the maximum spacing; (None, None) if it does not fit."""
    if not np.isfinite(As_m2_per_m) or As_m2_per_m <= 0:
        return None, None
    s_max = S.code.max_spacing(t)
    for db in BARS_MM:
        if db < S.db * 1000 - 1e-9:
            continue
        a = math.pi * (db / 1000) ** 2 / 4
        s = a / As_m2_per_m * 1000.0
        s = min(s, s_max)
        s = math.floor(s / 25.0) * 25.0
        if s >= S_MIN_MM:
            return db, s
    return None, None


class ShellDesign:
    def __init__(self, model, res, S, u_env, gov_combo, u_max, gov, steel, t_req):
        self.model, self.res, self.S = model, res, S
        self.util = u_env
        self.gov_combo = gov_combo
        self.util_max = u_max
        self.governing = gov
        self.steel = steel
        self.t = res.fem['shells'].a.copy()
        self.t_req = t_req
        self.fails = u_max > 1.0 + 1e-9
        self.util_structural = np.max(np.stack([u_env[k] for k in STRUCTURAL_CHECKS]), axis=0)
        self.needs_thicker = np.isfinite(t_req) & (t_req > self.t + 1e-6)
        self.cannot = ~np.isfinite(t_req)
        self.beams = design_beams(model, res, S)
        self.deflection = service_deflection(model, res)

    @property
    def ok(self):
        return not np.any(self.fails)

    def summary(self):
        S = self.S
        ne = len(self.t)
        worst = int(np.argmax(self.util_max))
        c = self.res.fem['mesh']['centroids'][worst]
        lines = [
            f'Code: {S.code.name}',
            f"f'c = {S.fc:g} MPa, fy = {S.fy:g} MPa (shell limit {S.code.fy_max_shell:g}), "
            f'cover {S.cover*1000:.0f} mm (minimum {S.cover_min*1000:.0f} mm), bars {S.db*1000:.0f} mm',
            f'Detailing minimum thickness: {S.t_single_min*100:.1f} cm with one central mesh, '
            f'{S.t_two_min*100:.1f} cm with two meshes',
            f'{int(self.fails.sum())} of {ne} elements fail at the present thickness; '
            f'{int(self.needs_thicker.sum())} need to be thicker'
            + (f', {int(self.cannot.sum())} cannot pass by thickness alone (up to '
               f'{S.t_max*100:.0f} cm)' if self.cannot.any() else ''),
            f'Worst element {worst} at (x={c[0]:.2f}, y={c[1]:.2f}): utilisation '
            f'{self.util_max[worst]:.2f}, governed by {CHECK_LABELS[self.governing[worst]]}',
        ]
        for k in CHECKS:
            lines.append(f'  max {CHECK_LABELS[k]:48s} {self.util[k].max():6.2f}')
        if self.cover_short:
            lines.append(f'  COVER {S.cover*1000:.0f} mm is less than the '
                         f'{S.cover_min*1000:.0f} mm the code requires here')
        d = self.deflection
        lines.append(f'Deflection (service, x{d["longterm"]:g} long-term): '
                     f'{d["long"]*1000:.1f} mm vs limit L/{d["limit_ratio"]:g} = '
                     f'{d["limit"]*1000:.1f} mm  ->  {"OK" if d["ok"] else "EXCEEDS"}')
        return lines

    @property
    def cover_short(self):
        return self.S.cover < self.S.cover_min - 1e-9


def service_deflection(model, res):
    d = model.data['design']
    fac = res.factors_vector(res.service)
    U = res.U @ fac
    nn_shell = len(res.fem['mesh']['X'])
    uz = U.reshape(-1, 6)[:nn_shell, 2]
    x0, x1, y0, y1 = res.fem['mesh']['plan']
    L = min(x1 - x0, y1 - y0)
    lt = float(d.get('longterm', 3.0))
    ratio = float(d.get('deflection_limit', 250.0))
    peak = float(np.abs(uz).max()) if len(uz) else 0.0
    return {'short': peak, 'long': lt * peak, 'longterm': lt, 'limit_ratio': ratio,
            'limit': L / ratio, 'span': L, 'ok': lt * peak <= L / ratio,
            'node': int(np.argmax(np.abs(uz))) if len(uz) else 0}


def design_beams(model, res, S):
    """Preliminary design of edge beams and columns (rectangular RC):
    envelope of axial force and bending over the combinations, tension steel
    for N + M, a simplified N-M interaction for compression, and stirrups
    for shear. Labelled preliminary in the report."""
    code = S.code
    fc, fy = S.fc, min(float(model.data['material']['fy']), 500.0)
    fems = res.fem['frames']
    if not fems:
        return []
    per_combo = [res.beam_internal(c) for c in res.combos]
    out = []
    for i, fr in enumerate(fems):
        if fr.tag.startswith('head'):
            continue
        b, h = fr.sec['b'], fr.sec['h']
        d = h - 0.05
        Nt = max((float(np.max(pc[i]['N'])) for pc in per_combo), default=0.0)
        Nc = min((float(np.min(pc[i]['N'])) for pc in per_combo), default=0.0)
        Mv = max((float(np.max(np.abs(pc[i]['My']))) for pc in per_combo), default=0.0)
        Mh = max((float(np.max(np.abs(pc[i]['Mz']))) for pc in per_combo), default=0.0)
        V = max((float(np.max(np.hypot(pc[i]['Vy'], pc[i]['Vz']))) for pc in per_combo), default=0.0)
        T = max((float(np.max(np.abs(pc[i]['T']))) for pc in per_combo), default=0.0)
        phi = code.phi_tension
        As_t = max(Nt, 0.0) / (phi * fy * 1e6) + Mv / (phi * fy * 1e6 * 0.9 * d) \
            + Mh / (phi * fy * 1e6 * 0.9 * (b - 0.05))
        Ag = b * h
        Ast = max(As_t, 0.01 * Ag)
        Pn_max = 0.80 * code.phi_compression * (0.85 * fc * 1e6 * (Ag - Ast) + fy * 1e6 * Ast)
        Mn = phi * Ast / 2 * fy * 1e6 * 0.9 * d
        u_comp = (-Nc) / Pn_max + (Mv + Mh) / max(Mn, 1e-9) if Nc < 0 else 0.0
        Vc = 0.17 * math.sqrt(fc) * 1e6 * b * d
        Av_s = max(V / code.phi_shear - Vc, 0.0) / (fy * 1e6 * d)     # m^2 per m
        out.append({'tag': fr.tag, 'L': fr.L, 'b': b, 'h': h, 'N_tension': Nt,
                    'N_compression': Nc, 'M_vertical': Mv, 'M_horizontal': Mh,
                    'V': V, 'T': T, 'As_long': Ast, 'u_compression': u_comp,
                    'Av_s': Av_s, 'u_shear_concrete': V / (code.phi_shear * Vc)})
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  Thickening
# ═══════════════════════════════════════════════════════════════════════════
def thickening_layer(model, des):
    """The automatic thickness layer implied by a design: every element that
    needs more thickness is raised to its t_req (rounded up to the step),
    and the raise is TAPERED into the surrounding shell at `taper` metres
    of thickness per metre of distance, since an abrupt step in a shell
    causes bending of its own. Returns a list of [x, y, t] at element
    centres (only where the result is thicker than the shell without the
    layer) with the element size, for model.data['auto_layer']."""
    d = model.data['design']
    step = float(d.get('t_step', 0.01))
    taper = float(d.get('taper', 0.10))
    S = des.S
    cen = des.res.fem['mesh']['centroids']
    xc, yc = cen[:, 0], cen[:, 1]
    base = model.element_thickness(xc, yc, with_auto=False)
    base = np.where(des.in_head, des.t, base)
    t_now = des.t
    target = np.where(des.needs_thicker, des.t_req, 0.0)
    target = np.where(des.cannot, S.t_max, target)
    target = np.ceil(np.round(target / step, 6)) * step
    keep = target > 0
    new = np.maximum(t_now, base)
    if np.any(keep):
        P = cen[keep][:, :2]
        tt = target[keep]
        dist = np.sqrt((xc[:, None] - P[None, :, 0]) ** 2 + (yc[:, None] - P[None, :, 1]) ** 2)
        tapered = np.max(tt[None, :] - taper * dist, axis=1)
        tapered = np.ceil(np.round(tapered / step, 6)) * step
        new = np.maximum(new, tapered)
    raised = new > base + 1e-9
    return {'h': float(des.res.fem['mesh']['h_el']),
            'points': [[float(x), float(y), float(t)]
                       for x, y, t, r in zip(xc, yc, new, raised) if r]}


def auto_thicken(model, max_iter=None, progress=None):
    """Analyse, design, thicken where needed, and repeat until every element
    passes (or nothing more can be done). Returns (results, design, log)."""
    max_iter = int(max_iter or model.data['design'].get('max_iter', 6))
    log = []
    res = model.analyze()
    des = design(model, res)
    for it in range(max_iter):
        n_need = int(des.needs_thicker.sum() + des.cannot.sum())
        log.append(f'pass {it + 1}: {int(des.fails.sum())} elements fail, '
                   f'{n_need} need more thickness, max t = {des.t.max()*100:.1f} cm')
        if progress:
            progress(log[-1])
        if n_need == 0:
            break
        layer = thickening_layer(model, des)
        old = model.data.get('auto_layer') or {}
        if layer == old:
            log.append('the thickness stopped changing; what still fails cannot be '
                       'fixed by thickness alone within the maximum')
            break
        model.data['auto_layer'] = layer
        res = model.analyze()
        des = design(model, res)
    else:
        log.append(f'stopped after {max_iter} passes')
    return res, des, log


def clear_thickening(model):
    model.data['auto_layer'] = None
