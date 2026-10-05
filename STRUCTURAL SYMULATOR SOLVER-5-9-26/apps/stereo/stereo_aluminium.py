"""Aluminium rods to the Reglamento CIRSOC 701 (Argentine aluminium
structures code, edition July 2010). Kept free of Tk.

What is covered -- closed sections, the ones a space frame is built of:

    'tube'   round tube, outside diameter D and wall t
    'rhs'    rectangular (or square) tube, width B, depth H, wall t
             (H in the rod's vertical plane: the strong axis)
    'bar'    solid round bar, diameter D

and, for each, the limit states of the Reglamento's Chapters C and D:

    C.3     axial tension: yield on the gross area, rupture on the net
            (no holes are modelled, so the net area is the gross area)
    C.4     axial compression: global flexural buckling (C.4.1-C.4.2),
            local buckling of the walls -- flat walls supported on both
            edges (C.4.6), round tube walls (C.4.9) -- and the two
            combined by area (C.4-2 to C.4-4)
    C.5     bending: yield of the extreme tension fibre (C.5.1), local
            buckling of the compressed wall (C.5.3.1, C.5.3.3), the webs
            (C.5.4.1), and lateral buckling of non-square tubes (C.5.2.5;
            C.5.2 exempts round and square tubes and solid round bars)
    D.1     axial force with bending (D.1.1 tension, D.1.2 compression)

Strengths are DESIGN strengths (phi already applied), in kN and kN m, from
stresses in MPa and section properties in cm, cm2, cm3, cm4 -- the units
the Reglamento writes its formulas in.

Not covered, and said so in every result that would need it: shear
(C.6), second-order amplification of the moments (D.3; the analysis is
first order), welded zones (Table A.2-2), and open sections (angles,
channels), whose torsional buckling (C.4.3) needs a different model.
"""
import math

REGLAMENTO = 'Reglamento CIRSOC 701 (2010)'

# Table C.1-1 resistance factors.
PHI_Y, PHI_B, PHI_C, PHI_U, PHI_CP = 0.95, 0.85, 0.85, 0.85, 0.85
TENSION_KL_R_MAX = 300.0      # C.3
COMPRESSION_KL_R_MAX = 200.0  # C.4

# Table A.2-1: minimum mechanical properties, unwelded, MPa. Only the
# alloys and products a tube or bar is made from are listed. Kt is
# Table C.1-2 (1.0 for every alloy here). E is the compression modulus of
# the table; the analysis uses E - 700 MPa, the table's note 2 average for
# deformations.
#   key: (alloy-temper, product, thickness range, Fut, Fyt, Fyc, Fuv, Fyv, E)
_A21 = [
    ('6005-T5', 'extrusions', 'up to 25 mm', 260, 240, 240, 165, 138.6, 69600),
    ('6061-T6', 'extrusions', 'all', 260, 240, 240, 165, 138.6, 69600),
    ('6061-T6', 'drawn tube', '0.63 to 12.5 mm', 290, 240, 240, 185, 138.6, 69600),
    ('6061-T6', 'pipe', 'all', 260, 240, 240, 165, 138.6, 69600),
    ('6063-T5', 'extrusions', 'up to 12.5 mm', 150, 110, 110, 90, 63.5, 69600),
    ('6063-T5', 'extrusions', '12.5 to 25 mm', 145, 105, 105, 85, 60.6, 69600),
    ('6063-T52', 'extrusions', 'up to 25 mm', 150, 110, 110, 90, 63.5, 69600),
    ('6063-T6', 'extrusions and pipe', 'all', 205, 170, 170, 130, 98.2, 69600),
    ('6105-T5', 'extrusions', 'up to 12.5 mm', 260, 240, 240, 165, 138.6, 69600),
    ('6351-T5', 'extrusions', 'up to 25 mm', 260, 240, 240, 165, 138.6, 69600),
    ('6351-T6', 'extrusions', 'up to 20 mm', 290, 255, 255, 185, 147.2, 69600),
    ('6463-T6', 'extrusions', 'up to 12.5 mm', 205, 170, 170, 130, 98.2, 69600),
    ('7005-T53', 'extrusions', 'up to 20 mm', 345, 305, 295, 195, 176.1, 72400),
]

ALLOYS = {}
for _row in _A21:
    _key = '%s %s (%s)' % _row[:3]
    ALLOYS[_key] = {'alloy': _row[0], 'product': _row[1], 'thickness': _row[2],
                    'Fut': float(_row[3]), 'Fyt': float(_row[4]),
                    'Fyc': float(_row[5]), 'Fuv': float(_row[6]),
                    'Fyv': float(_row[7]), 'E': float(_row[8]), 'Kt': 1.0,
                    'table': 'Table A.2-1'}

UNIT_WEIGHT_KN_M3 = 27.0      # aluminium alloys, about 2 700 kg/m3


def alloy_names():
    return list(ALLOYS)


def artificially_aged(alloy):
    """Tempers -T5 to -T9 use Table C.2-2; -O, -H, -T1 to -T4 Table C.2-1."""
    temper = alloy.split('-', 1)[1] if '-' in alloy else ''
    return temper[:2] in ('T5', 'T6', 'T7', 'T8', 'T9')


def buckling_constants(Fyc, Fy, Fyt, E, aged=True):
    """Tables C.2-1 / C.2-2, in MPa. Ct is found where the inelastic and
    elastic tube-wall curves meet (the tables' footnote), in tube_wall()."""
    if aged:
        Bc = Fyc * (1 + (Fyc / 15510.0) ** 0.5)
        Dc = Bc / 10 * (Bc / E) ** 0.5
        Cc = 0.41 * Bc / Dc
        Bp = Fyc * (1 + Fyc ** (1 / 3) / 21.7)
        Dp = Bp / 10 * (Bp / E) ** 0.5
        Cp = 0.41 * Bp / Dp
        Bt = Fyc * (1 + Fyc ** 0.2 / 12.8)
        Dt = Bt / 4.5 * (Bt / E) ** (1 / 3)
        Btb = 1.5 * Fy * (1 + Fy ** 0.2 / 12.8)
        k1c, k2c = 0.35, 2.27        # flat elements in compression
    else:
        Bc = Fyc * (1 + (Fyc / 6900.0) ** 0.5)
        Dc = Bc / 20 * (6 * Bc / E) ** 0.5
        Cc = 2 * Bc / (3 * Dc)
        Bp = Fyc * (1 + Fyc ** (1 / 3) / 14.5)
        Dp = Bp / 20 * (6 * Bp / E) ** 0.5
        Cp = 2 * Bp / (3 * Dp)
        Bt = Fyc * (1 + Fyc ** 0.2 / 8.5)
        Dt = Bt / 3.7 * (Bt / E) ** (1 / 3)
        Btb = 1.5 * Fy * (1 + Fy ** 0.2 / 8.5)
        k1c, k2c = 0.50, 2.04
    Bbr = 1.3 * Fyc * (1 + Fyc ** (1 / 3) / 13.3)
    Dbr = Bbr / 20 * (6 * Bbr / E) ** 0.5
    Cbr = 2 * Bbr / (3 * Dbr)
    Dtb = Btb / 2.7 * (Btb / E) ** (1 / 3)
    return {'Bc': Bc, 'Dc': Dc, 'Cc': Cc, 'Bp': Bp, 'Dp': Dp, 'Cp': Cp,
            'Bt': Bt, 'Dt': Dt, 'Btb': Btb, 'Dtb': Dtb,
            'Bbr': Bbr, 'Dbr': Dbr, 'Cbr': Cbr,
            'k1c': k1c, 'k2c': k2c, 'k1b': 0.50, 'k2b': 2.04}


# ── sections ─────────────────────────────────────────────────────────────
def section(shape, dims):
    """Properties of a closed section, member units (cm, cm2, cm3, cm4).

    dims (mm): tube {'D','t'}, rhs {'B','H','t'}, bar {'D'}. Sharp
    corners are assumed for the tube walls: the flat width b = B - 2t is
    then the larger, conservative value of C.4-2's b.
    """
    if shape == 'tube':
        D, t = float(dims['D']), float(dims['t'])
        if not (0 < t < D / 2):
            raise ValueError('a round tube needs 0 < t < D/2')
        d = D - 2 * t
        A = math.pi / 4 * (D * D - d * d)
        I = math.pi / 64 * (D ** 4 - d ** 4)
        return {'A': A / 100, 'I': I / 1e4, 'Iw': I / 1e4, 'J': 2 * I / 1e4,
                'S': I / (D / 2) / 1e3, 'Sw': I / (D / 2) / 1e3,
                'c_cm': D / 20, 'cw_cm': D / 20,
                'r_gyr': math.sqrt(I / A) / 10}
    if shape == 'rhs':
        B, H, t = float(dims['B']), float(dims['H']), float(dims['t'])
        if not (0 < t < min(B, H) / 2):
            raise ValueError('a rectangular tube needs 0 < t < min(B, H)/2')
        A = B * H - (B - 2 * t) * (H - 2 * t)
        Is = (B * H ** 3 - (B - 2 * t) * (H - 2 * t) ** 3) / 12
        Iw = (H * B ** 3 - (H - 2 * t) * (B - 2 * t) ** 3) / 12
        # Bredt: J = 4 Am^2 / (perimeter / t), on the wall's centre line.
        Am = (B - t) * (H - t)
        J = 4 * Am * Am * t / (2 * ((B - t) + (H - t)))
        return {'A': A / 100, 'I': Is / 1e4, 'Iw': Iw / 1e4, 'J': J / 1e4,
                'S': Is / (H / 2) / 1e3, 'Sw': Iw / (B / 2) / 1e3,
                'c_cm': H / 20, 'cw_cm': B / 20,
                'r_gyr': math.sqrt(min(Is, Iw) / A) / 10}
    if shape == 'bar':
        D = float(dims['D'])
        if D <= 0:
            raise ValueError('a bar needs a diameter')
        A = math.pi * D * D / 4
        I = math.pi * D ** 4 / 64
        return {'A': A / 100, 'I': I / 1e4, 'Iw': I / 1e4, 'J': 2 * I / 1e4,
                'S': I / (D / 2) / 1e3, 'Sw': I / (D / 2) / 1e3,
                'c_cm': D / 20, 'cw_cm': D / 20, 'r_gyr': D / 4 / 10}
    raise ValueError('unknown aluminium shape %r' % shape)


def section_code(shape, dims):
    """The section as one short text -- 'tube 50x3', 'rhs 100x150x3',
    'bar 20' (mm) -- so it travels through Excel like any other cell."""
    if shape == 'tube':
        return 'tube %gx%g' % (dims['D'], dims['t'])
    if shape == 'rhs':
        return 'rhs %gx%gx%g' % (dims['B'], dims['H'], dims['t'])
    if shape == 'bar':
        return 'bar %g' % dims['D']
    raise ValueError('unknown aluminium shape %r' % shape)


def parse_section(code):
    """Inverse of section_code: (shape, dims). Raises ValueError."""
    try:
        shape, size = str(code).strip().split(None, 1)
        vals = [float(v) for v in size.lower().replace('×', 'x').split('x')]
    except Exception:
        raise ValueError('not an aluminium section: %r' % code)
    names = {'tube': ('D', 't'), 'rhs': ('B', 'H', 't'), 'bar': ('D',)}
    if shape not in names or len(vals) != len(names[shape]):
        raise ValueError('not an aluminium section: %r' % code)
    return shape, dict(zip(names[shape], vals))


def profile_name(alloy_key, shape, dims):
    a = ALLOYS[alloy_key]['alloy']
    if shape == 'tube':
        return 'Al %s Ø%gx%g' % (a, dims['D'], dims['t'])
    if shape == 'rhs':
        return 'Al %s %gx%gx%g' % (a, dims['B'], dims['H'], dims['t'])
    return 'Al %s bar Ø%g' % (a, dims['D'])


def profile(alloy_key, shape, dims, unit_weight=None):
    """A named-profile dict for a rod: E for the solver (the table's E less
    700 MPa, its note 2, in GPa as the solver takes it), the geometry, and
    the keys that mark the rod as aluminium."""
    al = ALLOYS[alloy_key]
    sec = section(shape, dims)
    out = {'E': (al['E'] - 700.0) / 1000.0, 'K': 1.0}
    out.update({k: sec[k] for k in ('A', 'I', 'Iw', 'J', 'c_cm', 'cw_cm',
                                    'r_gyr')})
    out['aluminium'] = alloy_key
    out['al_section'] = section_code(shape, dims)
    out['gamma_kN_m3'] = (UNIT_WEIGHT_KN_M3 if unit_weight is None
                          else float(unit_weight))
    out['material'] = 'aluminium: ' + alloy_key
    return out


# ── local buckling of the walls ──────────────────────────────────────────
def flat_wall_compression(b_t, al, bc):
    """C.4.6: phi*FnL of a flat wall supported on both edges, MPa."""
    Fyc, E = al['Fyc'], al['E']
    Bp, Dp, k1, k2 = bc['Bp'], bc['Dp'], bc['k1c'], bc['k2c']
    S1 = (Bp - PHI_Y / PHI_C * Fyc) / (1.6 * Dp)
    S2 = k1 * Bp / (1.6 * Dp)
    if b_t <= S1:
        return PHI_Y * Fyc, 'C.4.6-1', S1, S2
    if b_t < S2:
        return PHI_C * (Bp - 1.6 * Dp * b_t), 'C.4.6-2', S1, S2
    return PHI_C * k2 * math.sqrt(Bp * E) / (1.6 * b_t), 'C.4.6-3', S1, S2


def _tube_elastic(x, E):
    return PHI_CP * math.pi ** 2 * E / (16 * x * (1 + math.sqrt(x) / 35) ** 2)


def tube_wall_compression(Rb_t, al, bc):
    """C.4.9: phi*FnL of a round tube wall, MPa. S2 is where C.4.9-2 and
    C.4.9-3 meet (the Reglamento's own definition), found by bisection."""
    Fyc, E, Bt, Dt = al['Fyc'], al['E'], bc['Bt'], bc['Dt']
    S1 = ((Bt - PHI_Y / PHI_C * Fyc) / Dt) ** 2
    inel = lambda x: PHI_C * (Bt - Dt * math.sqrt(x))
    # The elastic curve is the higher one at low Rb/t and falls below the
    # inelastic line past S2: march up until it has, then bisect.
    lo, hi = max(S1, 1e-6), max(S1, 1e-6) * 2 + 10
    while _tube_elastic(hi, E) > inel(hi) and hi < 1e6:
        lo, hi = hi, hi * 2
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _tube_elastic(mid, E) > inel(mid):
            lo = mid
        else:
            hi = mid
    S2 = 0.5 * (lo + hi)
    if Rb_t <= S1:
        return PHI_Y * Fyc, 'C.4.9-1', S1, S2
    if Rb_t < S2:
        return inel(Rb_t), 'C.4.9-2', S1, S2
    return _tube_elastic(Rb_t, E), 'C.4.9-3', S1, S2


# ── members ──────────────────────────────────────────────────────────────
def tension_strength(member, al):
    """C.3: phi*Pn, kN (net area = gross area: no holes are modelled)."""
    Ag = member['A']
    yield_ = PHI_Y * al['Fyt'] * Ag / 10
    rupture = PHI_U / al['Kt'] * al['Fut'] * Ag / 10
    if yield_ <= rupture:
        return yield_, 'C.3-1 yield on the gross area'
    return rupture, 'C.3-2 rupture on the net area'


def global_buckling_stress(kl_r, al, bc):
    """C.4.1: phi*Fng, MPa, and the slenderness parameter lambda_c."""
    Fyc, E = al['Fyc'], al['E']
    lam = kl_r / math.pi * math.sqrt(Fyc / E)
    Dc_star = math.pi * bc['Dc'] * math.sqrt(E / Fyc)
    S1 = (bc['Bc'] - Fyc) / Dc_star
    S2 = bc['Cc'] / math.pi * math.sqrt(Fyc / E)
    phi_cc = (min(1 - 0.21 * lam, 0.95) if lam <= 1.2
              else min(0.14 * lam + 0.58, 0.95))
    if lam <= S1:
        return phi_cc * Fyc, lam, phi_cc, 'C.4.1-1'
    if lam < S2:
        return phi_cc * (bc['Bc'] - Dc_star * lam), lam, phi_cc, 'C.4.1-2'
    return phi_cc * Fyc / (lam * lam), lam, phi_cc, 'C.4.1-3'


def wall_elements(shape, dims):
    """[(name, area mm2, slenderness, kind)] of the walls that can buckle
    locally under uniform compression; the rest of the area is corners."""
    if shape == 'tube':
        D, t = dims['D'], dims['t']
        A = math.pi / 4 * (D * D - (D - 2 * t) ** 2)
        return [('tube wall', A, (D - t) / 2 / t, 'tube')]
    if shape == 'rhs':
        B, H, t = dims['B'], dims['H'], dims['t']
        b, h = B - 2 * t, H - 2 * t
        return [('flange', b * t, b / t, 'flat'), ('flange', b * t, b / t, 'flat'),
                ('web', h * t, h / t, 'flat'), ('web', h * t, h / t, 'flat')]
    return []


def compression_strength(member, al, bc, kl_r):
    """C.4-2 to C.4-4: phi*Pn, kN, with the global and local limit states.
    Each wall that buckles locally below phi*Fng contributes its own phi*FnL
    on its own area; everything else carries phi*Fng."""
    phiFng, lam, phi_cc, eq = global_buckling_stress(kl_r, al, bc)
    shape, dims = member['al_shape'], member['al_dims']
    Ag_mm2 = member['A'] * 100
    walls, carried, local = wall_elements(shape, dims), 0.0, []
    used = 0.0
    for name, A_i, slender, kind in walls:
        f = (tube_wall_compression if kind == 'tube' else
             flat_wall_compression)(slender, al, bc)
        local.append({'element': name, 'slenderness': slender,
                      'phiFnL': f[0], 'eq': f[1]})
        carried += A_i * min(f[0], phiFng)
        used += A_i
    carried += max(Ag_mm2 - used, 0.0) * phiFng
    phiFnp = carried / Ag_mm2
    return {'Pd_kN': phiFnp * member['A'] / 10, 'phiFnp': phiFnp,
            'phiFng': phiFng, 'lambda_c': lam, 'phi_cc': phi_cc,
            'global_eq': eq, 'local': local}


def bending_strength(member, al, bc, axis='strong', Lb_cm=None):
    """C.5: phi*Mn about one axis, kN m, and the clause that governs."""
    shape, d = member['al_shape'], member['al_dims']
    S = member['S'] if axis == 'strong' else member['Sw']
    Fyt, Fut, Fyc, E, Kt = al['Fyt'], al['Fut'], al['Fyc'], al['E'], al['Kt']
    cand = []
    if shape == 'tube':
        cand.append((1.17 * PHI_Y * Fyt * S / 1e3, 'C.5.1.2-1'))
        cand.append((1.24 * PHI_U / Kt * Fut * S / 1e3, 'C.5.1.2-2'))
        Rb_t = (d['D'] - d['t']) / 2 / d['t']
        Btb, Dtb, Bt, Dt = bc['Btb'], bc['Dtb'], bc['Bt'], bc['Dt']
        S1 = ((Btb - 1.17 * Fyc * PHI_Y / PHI_B) / Dtb) ** 2
        # C.5.3.1-5 as printed (phi_y/phi_b in the numerator, phi_c/phi_b
        # in the denominator).
        S2 = ((Btb - PHI_Y / PHI_B * Bt) / (Dtb - PHI_C / PHI_B * Dt)) ** 2
        if Rb_t <= S1:
            cand.append((1.17 * PHI_Y * Fyc * S / 1e3, 'C.5.3.1-1'))
        elif Rb_t < S2:
            cand.append((PHI_B * (Btb - Dtb * math.sqrt(Rb_t)) * S / 1e3,
                         'C.5.3.1-2'))
        else:
            cand.append((tube_wall_compression(Rb_t, al, bc)[0] * S / 1e3,
                         'C.5.3.1-3'))
    elif shape == 'bar':
        cand.append((1.3 * PHI_Y * Fyt * S / 1e3, 'C.5.1.3-1'))
        cand.append((1.42 * PHI_U / Kt * Fut * S / 1e3, 'C.5.1.3-2'))
    else:
        B, H, t = d['B'], d['H'], d['t']
        if axis != 'strong':
            B, H = H, B
        b_t, h_t = (B - 2 * t) / t, (H - 2 * t) / t
        cand.append((PHI_Y * Fyt * S / 1e3, 'C.5.1.1-1'))
        cand.append((PHI_U / Kt * Fut * S / 1e3, 'C.5.1.1-2'))
        Bp, Dp, k1, k2 = bc['Bp'], bc['Dp'], bc['k1b'], bc['k2b']
        S1 = (Bp - PHI_Y / PHI_B * Fyc) / (1.6 * Dp)
        S2 = k1 * Bp / (1.6 * Dp)
        if b_t <= S1:
            cand.append((PHI_Y * Fyc * S / 1e3, 'C.5.3.3-1'))
        elif b_t < S2:
            cand.append((PHI_B * (Bp - 1.6 * Dp * b_t) * S / 1e3, 'C.5.3.3-2'))
        else:
            cand.append((PHI_B * k2 * math.sqrt(Bp * E) / (1.6 * b_t) * S / 1e3,
                         'C.5.3.3-3'))
        m = 0.65                       # C.5.4.1-7 with c0/cc = -1
        Bbr, Dbr = bc['Bbr'], bc['Dbr']
        S1w = (Bbr - 1.3 * PHI_Y / PHI_B * Fyc) / (m * Dbr)
        S2w = k1 * Bbr / (m * Dbr)
        if h_t <= S1w:
            cand.append((1.3 * PHI_Y * Fyc * S / 1e3, 'C.5.4.1-1'))
        elif h_t < S2w:
            cand.append((PHI_B * (Bbr - m * Dbr * h_t) * S / 1e3, 'C.5.4.1-2'))
        else:
            cand.append((PHI_B * k2 * math.sqrt(Bbr * E) / (m * h_t) * S / 1e3,
                         'C.5.4.1-3'))
        if abs(B - H) > 1e-9 and Lb_cm and axis == 'strong':
            Iy = member['Iw']
            x = Lb_cm * S / (math.sqrt(Iy * member['J']) / 2)   # Cb = 1
            S1l = ((bc['Bc'] - PHI_Y * Fyc / PHI_B) / (1.6 * bc['Dc'])) ** 2
            S2l = (bc['Cc'] / 1.6) ** 2
            if x <= S1l:
                cand.append((PHI_Y * Fyc * S / 1e3, 'C.5.2.5-1'))
            elif x < S2l:
                cand.append((PHI_B * (bc['Bc'] - 1.6 * bc['Dc'] * math.sqrt(x))
                             * S / 1e3, 'C.5.2.5-2'))
            else:
                cand.append((PHI_B * math.pi ** 2 * E / (2.56 * x) * S / 1e3,
                             'C.5.2.5-3'))
    return min(cand)


def member_check(member, axial_force_kN, member_res=None):
    """The rod's CIRSOC 701 verification: a result shaped like the steel
    and timber ones (checked, util, governing, ok, mode, note, ...).

    `axial_force_kN` is signed, tension positive. Bending is read from
    `member_res` for rigid rods, as the steel check reads it.
    """
    key = member.get('aluminium')
    al = ALLOYS.get(key)
    try:
        shape, dims = parse_section(member.get('al_section'))
        sec = section(shape, dims)
    except ValueError:
        al = None
    if al is None:
        return {'checked': False, 'util': None, 'governing': None,
                'material': 'aluminium',
                'note': 'aluminium rod without a known alloy and section'}
    m = dict(member)
    m.update(sec)
    m['al_shape'], m['al_dims'] = shape, dims
    bc = buckling_constants(al['Fyc'], al['Fyt'], al['Fyt'], al['E'],
                            artificially_aged(al['alloy']))
    L_cm = member.get('_length_m', 0.0) * 100
    K = member.get('K', 1.0)
    kl_r = K * L_cm / sec['r_gyr'] if sec['r_gyr'] > 0 else float('inf')
    N = float(axial_force_kN)
    partial, ratios, info = [], {}, {}

    Mx = My = 0.0                    # strong (local y) and weak (local z)
    if member_res and member_res.get('conn') == 'rigid':
        from apps.stereo import stereo_math as sm
        diag = sm.member_diagram(member_res)
        My = max((abs(v) for v in diag['My']), default=0.0)
        Mx = max((abs(v) for v in diag['Mz']), default=0.0)
        if max((abs(v) for v in diag['V']), default=0.0) > 1e-9:
            partial.append('shear (C.6) not checked')
        if My > 1e-12 or Mx > 1e-12:
            partial.append('moments are first order: amplify them per D.3 '
                           'where the axial force is large')

    if N >= 0:
        Pd, eq = tension_strength(m, al)
        ratios['tension (%s)' % eq] = N / Pd if Pd > 0 else float('inf')
        if kl_r > TENSION_KL_R_MAX:
            partial.append('kL/r = %.0f exceeds 300 (C.3)' % kl_r)
        info['Pd_kN'] = Pd
    else:
        comp = compression_strength(m, al, bc, kl_r)
        Pd = comp['Pd_kN']
        lead = min(comp['local'], key=lambda e: e['phiFnL'])['eq'] \
            if comp['local'] and min(e['phiFnL'] for e in comp['local']) < comp['phiFng'] \
            else comp['global_eq']
        ratios['compression (%s)' % lead] = -N / Pd if Pd > 0 else float('inf')
        if kl_r > COMPRESSION_KL_R_MAX:
            ratios['slenderness kL/r ≤ 200 (C.4)'] = kl_r / COMPRESSION_KL_R_MAX
        info.update(comp)
    info['kL/r'] = kl_r

    if My > 1e-12 or Mx > 1e-12:
        Ms, eqs = bending_strength(m, al, bc, 'strong', L_cm)
        Mw, eqw = bending_strength(m, al, bc, 'weak', L_cm)
        info.update({'phiMn_strong_kNm': Ms, 'phiMn_weak_kNm': Mw,
                     'M_demand_kNm': math.hypot(My, Mx)})
        mb = My / Ms + Mx / Mw
        if N >= 0:
            # D.1.1-1 with Mnt = S Fyt; D.1.1-2 lets the tension relieve
            # the compressed side.
            Mts = PHI_B * m['S'] * al['Fyt'] / 1e3
            Mtw = PHI_B * m['Sw'] * al['Fyt'] / 1e3
            r1 = My / Mts + Mx / Mtw + N / Pd
            r2 = mb - N / Pd
            ratios['tension + bending (D.1.1)'] = max(r1, r2)
        else:
            ratios['compression + bending (D.1.2-1)'] = -N / Pd + mb
        ratios['bending (%s / %s)' % (eqs, eqw)] = mb

    if not ratios or (abs(N) < 1e-9 and My <= 1e-12 and Mx <= 1e-12):
        return {'checked': True, 'util': 0.0, 'governing': None, 'ok': True,
                'mode': 'unloaded', 'material': 'aluminium', 'alloy': key,
                'code': REGLAMENTO, 'ratios': {}, 'partial': partial,
                'note': 'Aluminium %s: carries nothing in this load case.' % key}
    worst = max(ratios.items(), key=lambda kv: kv[1])
    mode = ('tension' if N >= 0 else 'compression') + (
        ' + bending' if (My > 1e-12 or Mx > 1e-12) else '')
    note = ('Aluminium %s, %s: governs %s at %.2f; kL/r = %.0f'
            % (al['alloy'], REGLAMENTO, worst[0], worst[1], kl_r)
            + ('. Not verified: ' + '; '.join(partial) if partial else '')
            + '. Factored (LRFD) loads expected.')
    out = {'checked': True, 'util': worst[1], 'governing': worst[0],
           'ok': worst[1] <= 1.0 + 1e-9, 'mode': mode,
           'material': 'aluminium', 'alloy': key, 'code': REGLAMENTO,
           'ratios': ratios, 'partial': partial, 'slenderness': kl_r,
           'note': note}
    out.update({k: v for k, v in info.items() if not isinstance(v, list)})
    out['local'] = info.get('local', [])
    return out
