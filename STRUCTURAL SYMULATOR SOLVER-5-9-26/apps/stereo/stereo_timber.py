"""Timber members from the CIRSOC 601 Supplements (roadmap 4.3, timber half).

The SOURCE is "Suplementos del Reglamento Argentino de Estructuras de Madera
CIRSOC 601-2016, Edición 2020-1" (INTI-CIRSOC, julio 2020). Every number in
GRADES is transcribed from the table named beside it and checked against the
page image, not recalled.

What the Supplements give, and so what this module does:

  * the REFERENCE design values of each species / grade -- Fb, Ft, Fv, Fc⊥,
    Fc, E, E0,05, Emin (N/mm²) -- and the density ρ0,05 (kg/m³);
  * so a timber rod gets the grade's E for the analysis, its own weight from
    its own density, and its stresses set beside those reference values.

What the Supplements do NOT give, and so what this module does not do: the
design METHOD. The Supplements say so themselves -- their values are "para
ser utilizados con los métodos de cálculo que se indican en los Capítulos
correspondientes" of the Reglamento. The adjustment factors (load
duration, moisture, temperature, size...) and the column and beam stability
rules live in those chapters, which were not available. A reference value
is not a design value until they are applied -- for a slender strut the
difference is most of the capacity. So a timber rod is reported
`checked=False`: its stresses and the reference values are shown, and no
utilisation is claimed. When the Reglamento's chapters are in hand, the
verification slots in at `member_check`.

Units: the tables are in N/mm² (= MPa) and kg/m³. Members store E in GPa, A
in cm², I in cm⁴, like every other member in stereo_math.
"""
import math

SOURCE = ('CIRSOC 601-2016 Supplements, Edición 2020-1 (INTI-CIRSOC, '
          'julio 2020)')

G_ACCEL = 9.80665

# Columns of every table: Fb, Ft, Fv, Fc⊥, Fc, E, E0,05, Emin (N/mm²).
_COLS = ('Fb', 'Ft', 'Fv', 'Fc_perp', 'Fc', 'E', 'E005', 'Emin')

# Which axis a table's Fb is for: 'plano' = flatwise (about the board's
# weak axis), 'canto' = edgewise (about the strong axis), None = the table
# says neither, so it is not restricted to one.
_PLANO, _CANTO = 'plano', 'canto'

_ARAUCARIA = 'Araucaria angustifolia (pino paraná)'
_EUCALYPTUS = 'Eucalyptus grandis (eucalipto grandis)'
_TAEDA = 'Pinus taeda / P. elliottii (pino taeda / elliotti)'
_ALAMO = "Populus deltoides 'Australiano 106/60' / 'Stoneville 67' (álamo)"
_PONDEROSA = 'Pinus ponderosa (pino ponderosa)'


def _g(species, product, grade, values, rho, table, rho_table, bending,
       limits, Frt=None):
    d = dict(zip(_COLS, values))
    d.update(species=species, product=product, grade=grade, rho005=rho,
             table=table, rho_table=rho_table, bending=bending,
             limits=limits)
    if Frt is not None:
        d['Frt'] = Frt
    return d


_BOARDS = 'tablas: t ≤ 50 mm and d/t ≥ 2'
_THICK = 'sawn, t ≥ 50 mm'
_ANY = 'sawn, any section'
_GLULAM = 'glulam to IRAM 9660-1 (2015)'
_POLE = 'round poles, GREEN (at or above fibre saturation)'

# (key -> grade). Insertion order is the order a picker lists them in.
GRADES = {}
for _key, _grade in (
    # S.1.1.1 Araucaria angustifolia, Misiones
    ('Pino paraná tablas C1', _g(_ARAUCARIA, 'boards', '1',
        (9.4, 5.6, 0.9, 1.0, 7.2, 14600, 9800, 6200), 460,
        'S.1.1.1-1', 'S.1.1.1-2', _PLANO, _BOARDS)),
    ('Pino paraná tablas C2', _g(_ARAUCARIA, 'boards', '2',
        (4.4, 2.5, 0.5, 0.9, 5.0, 9900, 6600, 4200), 400,
        'S.1.1.1-1', 'S.1.1.1-2', _PLANO, _BOARDS)),
    ('Pino paraná aserrada C1', _g(_ARAUCARIA, 'sawn', '1',
        (10.6, 6.3, 1.1, 1.0, 7.5, 13300, 8900, 5700), 440,
        'S.1.1.1-3', 'S.1.1.1-4', _CANTO, _THICK)),
    ('Pino paraná aserrada C2', _g(_ARAUCARIA, 'sawn', '2',
        (6.6, 4.1, 0.7, 0.8, 6.3, 11400, 7700, 4900), 390,
        'S.1.1.1-3', 'S.1.1.1-4', _CANTO, _THICK)),
    ('Pino paraná aserrada C3', _g(_ARAUCARIA, 'sawn', '3',
        (5.0, 3.1, 0.6, 0.8, 5.3, 10000, 6700, 4200), 390,
        'S.1.1.1-3', 'S.1.1.1-4', _CANTO, _THICK)),
    # S.1.1.2 Eucalyptus grandis, Entre Ríos / Corrientes / Misiones
    ('Eucalipto grandis C1', _g(_EUCALYPTUS, 'sawn', '1',
        (9.4, 5.6, 0.9, 1.8, 7.2, 12000, 8100, 5100), 430,
        'S.1.1.2-1', 'S.1.1.2-2', None, _ANY)),
    ('Eucalipto grandis C2', _g(_EUCALYPTUS, 'sawn', '2',
        (7.5, 4.4, 0.8, 1.7, 6.6, 10800, 7200, 4600), 430,
        'S.1.1.2-1', 'S.1.1.2-2', None, _ANY)),
    ('Eucalipto grandis C3', _g(_EUCALYPTUS, 'sawn', '3',
        (5.6, 3.4, 0.6, 1.5, 5.6, 10000, 6700, 4200), 430,
        'S.1.1.2-1', 'S.1.1.2-2', None, _ANY + ' (pith allowed)')),
    # S.1.1.3 Pinus taeda / elliottii, NE Argentina
    ('Pino taeda tablas C1', _g(_TAEDA, 'boards', '1',
        (5.6, 3.4, 0.6, 0.9, 5.6, 10300, 6900, 4400), 420,
        'S.1.1.3-1', 'S.1.1.3-2', _PLANO, _BOARDS)),
    ('Pino taeda tablas C2', _g(_TAEDA, 'boards', '2',
        (3.4, 2.2, 0.4, 0.8, 4.6, 6000, 4000, 2600), 390,
        'S.1.1.3-1', 'S.1.1.3-2', _PLANO, _BOARDS)),
    ('Pino taeda aserrada C1', _g(_TAEDA, 'sawn', '1',
        (6.2, 3.7, 0.7, 0.9, 6.0, 7700, 5200, 3300), 420,
        'S.1.1.3-3', 'S.1.1.3-4', _CANTO,
        'sawn to IRAM 9670 (2002), sizes per its annex F')),
    ('Pino taeda aserrada C2', _g(_TAEDA, 'sawn', '2',
        (3.2, 1.9, 0.4, 0.8, 4.5, 6500, 4300, 2700), 390,
        'S.1.1.3-3', 'S.1.1.3-4', _CANTO,
        'sawn to IRAM 9670 (2002), sizes per its annex F')),
    # S.1.1.4 Populus deltoides, delta del Paraná
    ('Álamo C1', _g(_ALAMO, 'sawn', '1',
        (7.5, 4.4, 0.8, 0.9, 6.6, 8800, 5900, 3700), 400,
        'S.1.1.4-1', 'S.1.1.4-2', None, _ANY)),
    ('Álamo C2', _g(_ALAMO, 'sawn', '2',
        (5.6, 3.4, 0.6, 0.9, 5.6, 7700, 5200, 3300), 400,
        'S.1.1.4-1', 'S.1.1.4-2', None, _ANY)),
    # S.1.1.5 Pinus ponderosa, Patagonia norte
    ('Pino ponderosa C1', _g(_PONDEROSA, 'sawn', '1',
        (5.0, 3.0, 0.6, 0.7, 2.3, 5700, 3900, 2400), 330,
        'S.1.1.5-1', 'S.1.1.5-2', _PLANO, _ANY)),
    ('Pino ponderosa C2', _g(_PONDEROSA, 'sawn', '2',
        (2.8, 1.7, 0.3, 0.7, 1.7, 4200, 2800, 1800), 330,
        'S.1.1.5-1', 'S.1.1.5-2', _PLANO, _ANY)),
    # S.2.1.1 Glulam. Its density is the boards' it is made of (the
    # Supplement says so under the table); grade n is read here as made of
    # class-n boards of the same species.
    ('Laminada pino taeda G1', _g(_TAEDA, 'glulam', '1',
        (6.3, 3.5, 0.7, 0.9, 6.3, 11200, 7500, 4700), 420,
        'S.2.1.1-1', 'S.1.1.3-2', None, _GLULAM, Frt=0.1)),
    ('Laminada pino taeda G2', _g(_TAEDA, 'glulam', '2',
        (4.1, 2.3, 0.4, 0.8, 4.1, 6700, 4500, 2800), 390,
        'S.2.1.1-1', 'S.1.1.3-2', None, _GLULAM, Frt=0.1)),
    ('Laminada pino paraná G1', _g(_ARAUCARIA, 'glulam', '1',
        (7.5, 4.1, 0.8, 1.0, 7.5, 13400, 9000, 5700), 460,
        'S.2.1.1-1', 'S.1.1.1-2', None, _GLULAM, Frt=0.1)),
    ('Laminada pino paraná G2', _g(_ARAUCARIA, 'glulam', '2',
        (6.3, 3.5, 0.7, 0.9, 6.3, 11600, 7800, 4900), 400,
        'S.2.1.1-1', 'S.1.1.1-2', None, _GLULAM, Frt=0.1)),
    ('Laminada eucalipto G1', _g(_EUCALYPTUS, 'glulam', '1',
        (7.5, 4.1, 0.8, 1.8, 7.5, 13400, 9000, 5700), 430,
        'S.2.1.1-1', 'S.1.1.2-2', None, _GLULAM, Frt=0.1)),
    ('Laminada eucalipto G2', _g(_EUCALYPTUS, 'glulam', '2',
        (6.6, 3.7, 0.8, 1.7, 6.6, 11600, 7800, 4900), 430,
        'S.2.1.1-1', 'S.1.1.2-2', None, _GLULAM, Frt=0.1)),
    ('Laminada álamo G1', _g(_ALAMO, 'glulam', '1',
        (6.3, 3.5, 0.7, 0.9, 6.3, 9400, 6300, 4000), 400,
        'S.2.1.1-1', 'S.1.1.4-2', None, _GLULAM, Frt=0.1)),
    ('Laminada álamo G2', _g(_ALAMO, 'glulam', '2',
        (5.6, 3.2, 0.6, 0.9, 5.6, 8500, 5700, 3600), 400,
        'S.2.1.1-1', 'S.1.1.4-2', None, _GLULAM, Frt=0.1)),
    # S.3.1.1 Round poles, Eucalyptus grandis, green. ρ0,05 at 12 % from
    # S.1.1.2-2, as the Supplement directs.
    ('Poste eucalipto (verde)', _g(_EUCALYPTUS, 'pole', '-',
        (8.8, 5.3, 0.5, 1.1, 4.4, 9500, 6400, 4000), 430,
        'S.3.1.1-1', 'S.1.1.2-2', None, _POLE)),
):
    GRADES[_key] = _grade


def grade_names():
    return list(GRADES)


def is_round(grade_key):
    return GRADES[grade_key]['product'] == 'pole'


def unit_weight_kN_m3(grade_key):
    """ρ0,05 × g, in kN/m³: the Supplement's density -- a 5th-percentile
    value at 12 % moisture, so LOWER than a mean or a wet density."""
    return GRADES[grade_key]['rho005'] * G_ACCEL / 1000.0


# ── sections ────────────────────────────────────────────────────────────────

def rectangle(b_mm, h_mm):
    """A b × h rectangle, h the depth in the rod's vertical plane (the
    strong axis, local y, as the solver takes it) and b its width.

    Returns the member keys in member units (cm², cm⁴, cm). J is the
    torsion constant of a solid rectangle, β a b³ with a ≥ b and
    β = 1/3 − 0.21 (b/a)(1 − (b/a)⁴/12) (Roark).
    """
    b, h = float(b_mm), float(h_mm)
    if b <= 0 or h <= 0:
        raise ValueError('a timber section needs a width and a depth')
    long_, short = max(b, h), min(b, h)
    q = short / long_
    beta = 1.0 / 3.0 - 0.21 * q * (1.0 - q ** 4 / 12.0)
    return {'A': b * h / 100.0,
            'I': b * h ** 3 / 12.0 / 1e4,
            'Iw': h * b ** 3 / 12.0 / 1e4,
            'J': beta * long_ * short ** 3 / 1e4,
            'c_cm': h / 20.0, 'cw_cm': b / 20.0,
            'r_gyr': short / math.sqrt(12.0) / 10.0}


def circle(d_mm):
    d = float(d_mm)
    if d <= 0:
        raise ValueError('a pole needs a diameter')
    I = math.pi * d ** 4 / 64.0 / 1e4
    return {'A': math.pi * d * d / 4.0 / 100.0, 'I': I, 'Iw': I,
            'J': 2.0 * I, 'c_cm': d / 20.0, 'cw_cm': d / 20.0,
            'r_gyr': d / 4.0 / 10.0}


def profile(grade_key, b_mm, h_mm=None, unit_weight=None):
    """A named-profile dict (the shape self.profiles holds) for a timber
    section: the grade's E for the solver, the geometry, the density, and
    the grade key that marks every rod it is written onto as timber.

    No Fy / Fu: those are steel's, and stereo_profiles.write_section takes
    them off a rod that becomes timber.
    """
    g = GRADES[grade_key]
    sec = circle(b_mm) if g['product'] == 'pole' else rectangle(b_mm, h_mm)
    out = {'E': g['E'] / 1000.0, 'K': 1.0}
    out.update({k: sec[k] for k in ('A', 'I', 'Iw', 'J', 'c_cm', 'cw_cm',
                                    'r_gyr')})
    out['timber'] = grade_key
    out['gamma_kN_m3'] = (unit_weight_kN_m3(grade_key) if unit_weight is None
                          else float(unit_weight))
    out['material'] = 'timber: ' + grade_key
    return out


def profile_name(grade_key, b_mm, h_mm=None):
    if is_round(grade_key):
        return f'{grade_key} Ø{float(b_mm):g}'
    return f'{grade_key} {float(b_mm):g}x{float(h_mm):g}'


def describe(grade_key):
    """One line of reference values, with where they come from."""
    g = GRADES[grade_key]
    axis = {_PLANO: ' (Fb flatwise)', _CANTO: ' (Fb edgewise)'}.get(
        g['bending'], '')
    return (f"Fb {g['Fb']:g}{axis} · Ft {g['Ft']:g} · Fv {g['Fv']:g} · "
            f"Fc⊥ {g['Fc_perp']:g} · Fc {g['Fc']:g} · E {g['E']:g} · "
            f"E0,05 {g['E005']:g} · Emin {g['Emin']:g} N/mm² · "
            f"ρ0,05 {g['rho005']:g} kg/m³ — Tabla {g['table']} "
            f"(ρ: {g['rho_table']}); {g['limits']}")


# ── the member result ───────────────────────────────────────────────────────

NOT_VERIFIED = ('NOT a CIRSOC 601 verification: the reference values are '
                'unadjusted (no load-duration, moisture, temperature, size or '
                'stability factors -- those are in the Reglamento\'s chapters, '
                'not in the Supplements), so no utilisation is claimed.')


def member_check(member, axial_force_kN, member_res=None):
    """A timber rod's stresses beside its grade's reference values.

    Returns the shape check_member returns, with `checked=False` and
    `util=None` -- see the module docstring for why -- plus the numbers:
    `stresses_MPa`, `reference_MPa`, `ratios` (stress / reference value,
    unadjusted) and `slenderness` (KL over the least dimension, which is
    how timber states it).
    """
    key = member.get('timber')
    g = GRADES.get(key)
    if g is None:
        return {'checked': False, 'util': None, 'governing': None,
                'material': 'timber',
                'note': f'timber grade "{key}" is not in the CIRSOC 601 '
                        'Supplement tables this app carries'}
    A_mm2 = float(member.get('A', 0.0) or 0.0) * 100.0
    N_N = float(axial_force_kN) * 1e3
    fa = N_N / A_mm2 if A_mm2 > 0 else 0.0
    stresses = {'ft' if fa >= 0 else 'fc': abs(fa)}
    ref = {'ft': g['Ft'], 'fc': g['Fc'], 'fb': g['Fb'], 'fv': g['Fv']}

    M_strong = M_weak = V = 0.0
    if member_res and member_res.get('conn') == 'rigid':
        from apps.stereo import stereo_math as sm
        diag = sm.member_diagram(member_res)
        M_weak = max((abs(v) for v in diag['Mz']), default=0.0)
        M_strong = max((abs(v) for v in diag['My']), default=0.0)
        V = max((abs(v) for v in diag['V']), default=0.0)
    I, Iw = float(member.get('I', 0.0) or 0.0), float(member.get('Iw', 0.0) or 0.0)
    c, cw = float(member.get('c_cm', 0.0) or 0.0), float(member.get('cw_cm', 0.0) or 0.0)
    if M_strong and I and c:
        stresses['fb_strong'] = M_strong * 1e6 / (I / c * 1e3)
    if M_weak and Iw and cw:
        stresses['fb_weak'] = M_weak * 1e6 / (Iw / cw * 1e3)
    if V and A_mm2:
        # the solid rectangle's peak, 1.5 V/A (4/3 for a circle -- the
        # rectangle's figure is the larger, so it is the one used)
        stresses['fv'] = 1.5 * V * 1e3 / A_mm2

    ratios = {}
    for k, f in stresses.items():
        F = ref['fb' if k.startswith('fb') else k]
        if F:
            ratios[k] = f / F
    # Fb belongs to one axis for a board or an edgewise-graded piece; a
    # bending stress about the other axis has no reference value here.
    if g['bending'] == _PLANO:
        ratios.pop('fb_strong', None)
    elif g['bending'] == _CANTO:
        ratios.pop('fb_weak', None)

    L_m = float(member.get('_length_m', 0.0) or 0.0)
    # The least dimension, from the radius the section was built with:
    # r = d/sqrt(12) for a rectangle's thinner side, r = d/4 for a pole.
    r_mm = float(member.get('r_gyr', 0.0) or 0.0) * 10.0
    least_mm = r_mm * (4.0 if g['product'] == 'pole' else math.sqrt(12.0))
    K = float(member.get('K', 1.0) or 1.0)
    slender = (K * L_m * 1000.0 / least_mm) if least_mm > 0 else None

    parts = [f'{k} {v:.2f}' for k, v in stresses.items()]
    worst = max(ratios.items(), key=lambda kv: kv[1]) if ratios else None
    note = (f'Timber, {key} (Tabla {g["table"]}): '
            + (', '.join(parts) + ' MPa' if parts else 'no stress')
            + (f'; largest stress / reference value: {worst[0]} '
               f'{worst[1]:.2f}' if worst else '')
            + (f'; KL/d = {slender:.0f} (buckling not applied)'
               if fa < 0 and slender else '')
            + '. ' + NOT_VERIFIED)
    return {'checked': False, 'util': None, 'governing': None,
            'material': 'timber', 'grade': key, 'table': g['table'],
            'mode': 'tension' if fa >= 0 else 'compression',
            'stresses_MPa': stresses, 'reference_MPa': ref,
            'ratios': ratios, 'slenderness': slender, 'note': note}
