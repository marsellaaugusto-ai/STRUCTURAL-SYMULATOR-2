"""Timber members: CIRSOC 601 Supplement grades, verified to the Reglamento.

The SOURCE is "Suplementos del Reglamento Argentino de Estructuras de Madera
CIRSOC 601-2016, Edición 2020-1" (INTI-CIRSOC, julio 2020). Every number in
GRADES is transcribed from the table named beside it and checked against the
page image, not recalled.

What the Supplements give, and so what this module does:

  * the REFERENCE design values of each species / grade -- Fb, Ft, Fv, Fc⊥,
    Fc, E, E0,05, Emin (N/mm²) -- and the density ρ0,05 (kg/m³);
  * so a timber rod gets the grade's E for the analysis, its own weight from
    its own density, and its stresses set beside those reference values.

The METHOD is the Reglamento's (Reglamento CIRSOC 601-2016, Cap. 1-4, 5,
6 and 9.2): the adjustment factors (load duration, service condition,
temperature, size, volume, load sharing) and the column and beam stability
rules, applied in `member_check` below. It is an allowable-stress code, so
the check reads the stresses of SERVICE loads, unfactored (art. 1.4).

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




# ── the verification: Reglamento CIRSOC 601-2016 ───────────────────────────
#
# The Reglamento is an ALLOWABLE-STRESS code (art. 1.4: "formato de
# tensiones admisibles"): the stresses of the SERVICE loads, unfactored,
# against the reference values times every adjustment factor that applies
# (art. 2.3). Which factors apply to which value is Tabla 4.3-1 for sawn
# timber and boards, 5.3-1 for glulam and 6.3-1 for round members.
#
# The rules, with the article each one is from:
#   tension ∥            ft ≤ F't                                   3.4.1
#   compression ∥        fc ≤ F'c = Fc* CP, le/d ≤ 50               3.3.1
#   bending              fb ≤ F'b = Fb* CL, RB ≤ 50                 3.2.1
#   shear ∥              fv = 3V/2bd ≤ F'v                          3.2.2
#   bending + tension    ft/F't + fb/F*b ≤ 1, (fb − ft)/F'b ≤ 1     3.5.1
#   bending + compr.     (fc/F'c)² + fb1/(F'b1(1 − fc/FcE1))
#                         + fb2/(F'b2(1 − fc/FcE2 − (fb1/FbE)²)) ≤ 1 3.5.2
# with CP from expression 3.3.1-1, CL from 3.2.1-4, the effective length of
# lateral buckling from Tabla 3.2.1-1 (its footnote 1, the general case: a
# rod of a space structure carries no single load pattern from the table)
# and the factors CD (Tabla 4.3-2), CM (4.3-3, 5.3-2), Ct (4.3-4, 5.3-3),
# CF (4.3-1), CV (5.3-1) and Cr (art. 4.3 / 5.3 / 6.3).
#
# Checked against the worked examples of the Manual de Aplicación CIRSOC
# 601 (M.4.E.1, M.4.E.2, M.4.E.3, M.5.E.1) -- see tests/test_stereo_timber.

REGLAMENTO = 'Reglamento CIRSOC 601-2016'

# Tabla 4.3-2: (key, label, CD). One load case is checked at a time, so
# the case takes the CD of its SHORTEST load (art. 4.3).
LOAD_DURATIONS = (
    ('permanent', 'Permanente (peso propio)', 0.9),
    ('normal', '10 años (sobrecarga de uso)', 1.0),
    ('2months', '2 meses (nieve)', 1.15),
    ('7days', '7 días (constructiva)', 1.25),
    ('10min', '10 minutos (viento, sismo)', 1.6),
    ('instant', 'Instantánea (carga accidental)', 2.0),
)
TEMPERATURES = (
    ('le40', 'T ≤ 40 ºC'),
    ('40to52', '40 ºC < T ≤ 52 ºC'),
    ('52to65', '52 ºC < T ≤ 65 ºC'),
)
DEFAULT_SETTINGS = {
    'duration': 'normal',      # Tabla 4.3-2
    'wet': False,              # estado húmedo (CM, Tabla 4.3-3 / 5.3-2)
    'temperature': 'le40',     # Tabla 4.3-4 / 5.3-3
    'load_sharing': False,     # Cr = 1.10 (art. 4.3)
    'braced_edge': False,      # compression edge braced along: CL = 1
}

SLENDERNESS_MAX = 50.0         # le/d, art. 3.3.1
AXIAL_TOL_MPA = 1e-6           # below this an axial stress is round-off
RB_MAX = 50.0                  # RB, art. 3.2.1
# the column coefficient c of expression 3.3.1-1
C_COLUMN = {'sawn': 0.8, 'boards': 0.8, 'glulam': 0.9, 'pole': 0.85}


def settings_of(settings=None):
    out = dict(DEFAULT_SETTINGS)
    out.update({k: v for k, v in (settings or {}).items()
                if k in DEFAULT_SETTINGS})
    return out


def load_duration_factor(settings=None):
    key = settings_of(settings)['duration']
    for k, _label, cd in LOAD_DURATIONS:
        if k == key:
            return cd
    return 1.0


def describe_settings(settings=None):
    s = settings_of(settings)
    dur = next((lab for k, lab, _cd in LOAD_DURATIONS
                if k == s['duration']), s['duration'])
    temp = next((lab for k, lab in TEMPERATURES if k == s['temperature']),
                s['temperature'])
    return (f'CD {load_duration_factor(s):g} ({dur}), '
            f'{"estado húmedo" if s["wet"] else "estado seco"}, {temp}'
            + (', Cr 1.10' if s['load_sharing'] else '')
            + (', borde comprimido arriostrado (CL = 1)'
               if s['braced_edge'] else ''))


def wet_service_factor(grade, prop):
    """CM for one reference value (Tabla 4.3-3, sawn and boards; Tabla
    5.3-2, glulam). Round members take none (Tabla 6.3-1 has no CM: their
    values are from green poles already)."""
    product = grade['product']
    if product == 'pole':
        return 1.0
    if product == 'glulam':
        return {'Fb': 0.80, 'Ft': 0.80, 'Fv': 0.87, 'Frt': 0.87,
                'Fc_perp': 0.53, 'Fc': 0.73}.get(prop, 0.83)
    if prop == 'Fb':
        return 1.0 if grade['Fb'] <= 7.9 else 0.85     # note (1)
    if prop == 'Fc':
        return 1.0 if grade['Fc'] <= 5.2 else 0.8      # note (2)
    return {'Ft': 1.0, 'Fv': 0.97, 'Fc_perp': 0.67}.get(prop, 0.9)


def temperature_factor(prop, wet, temperature):
    """Ct, Tabla 4.3-4 (the same figures as 5.3-3; 6.3 refers to 4.3-4)."""
    col = {'le40': 0, '40to52': 1, '52to65': 2}.get(temperature, 0)
    if prop in ('Ft', 'E', 'E005', 'Emin'):
        return (1.0, 0.9, 0.9)[col]
    return ((1.0, 0.7, 0.5) if wet else (1.0, 0.8, 0.7))[col]


def size_factor(d_mm):
    """CF = (150/d)^0.2 ≤ 1.3, expression 4.3-1 (sawn and boards)."""
    if d_mm <= 0:
        return 1.0
    return min((150.0 / d_mm) ** 0.2, 1.3)


def volume_factor(d_mm, b_mm):
    """CV = (600/d)^0.1 (150/b)^0.05 ≤ 1.1, expression 5.3-1 (glulam)."""
    if d_mm <= 0 or b_mm <= 0:
        return 1.0
    return min((600.0 / d_mm) ** 0.1 * (150.0 / b_mm) ** 0.05, 1.1)


def column_stability_factor(Fc_star, FcE, c):
    """CP, expression 3.3.1-1."""
    if Fc_star <= 0:
        return 1.0
    a = FcE / Fc_star
    t = (1.0 + a) / (2.0 * c)
    return t - math.sqrt(max(t * t - a / c, 0.0))


def beam_stability_factor(Fb_star, FbE):
    """CL, expression 3.2.1-4."""
    if Fb_star <= 0:
        return 1.0
    a = FbE / Fb_star
    t = (1.0 + a) / 1.9
    return t - math.sqrt(max(t * t - a / 0.95, 0.0))


def lateral_buckling_length(lu_mm, d_mm):
    """le for a beam, Tabla 3.2.1-1 note (1): the case for loads the table
    does not list -- a rod in a space structure takes no one of its load
    patterns."""
    r = lu_mm / d_mm if d_mm > 0 else 0.0
    if r < 7.0:
        return 2.06 * lu_mm
    if r < 14.3:
        return 1.63 * lu_mm + 3.0 * d_mm
    return 1.84 * lu_mm


def _section_mm(member, grade):
    """(depth about the strong local axis, depth about the weak one, A) in
    mm / mm² -- for a pole, its diameter twice."""
    h = float(member.get('c_cm', 0.0) or 0.0) * 20.0
    b = float(member.get('cw_cm', 0.0) or 0.0) * 20.0
    A = float(member.get('A', 0.0) or 0.0) * 100.0
    if grade['product'] == 'pole':
        b = h
    return h, b, A


def member_check(member, axial_force_kN, member_res=None, settings=None):
    """A timber rod verified to the Reglamento CIRSOC 601-2016.

    The shape check_member returns -- `checked`, `util`, `governing`, `ok`,
    `mode`, `note` -- plus what a reader needs to follow it: the stresses
    (`stresses_MPa`), the adjusted design values (`design_MPa`), every
    factor (`factors`), each ratio (`ratios`), le/d (`slenderness`) and the
    reference values (`reference_MPa`). `partial` lists what the rod
    carries that its grade has no value for.
    """
    s = settings_of(settings)
    key = member.get('timber')
    g = GRADES.get(key)
    if g is None:
        return {'checked': False, 'util': None, 'governing': None,
                'material': 'timber',
                'note': f'timber grade "{key}" is not in the CIRSOC 601 '
                        'Supplement tables this app carries'}
    product = g['product']
    pole = product == 'pole'
    h, b, A = _section_mm(member, g)
    if A <= 0 or h <= 0 or b <= 0:
        return {'checked': False, 'util': None, 'governing': None,
                'material': 'timber', 'grade': key,
                'note': 'timber rod without a section (b × h or Ø)'}

    wet, temp = s['wet'], s['temperature']
    CD = load_duration_factor(s)

    def cm(prop):
        return wet_service_factor(g, prop) if wet else 1.0

    def ct(prop):
        return temperature_factor(prop, wet, temp)

    Cr = 1.10 if s['load_sharing'] else 1.0
    Emin_adj = g['Emin'] * cm('Emin') * ct('Emin')
    factors = {'CD': CD, 'Cr': Cr, 'CM_Emin': cm('Emin'),
               'Ct_Emin': ct('Emin')}
    design, ratios, stresses, partial = {}, {}, {}, []

    L_mm = float(member.get('_length_m', 0.0) or 0.0) * 1000.0
    K = float(member.get('K', 1.0) or 1.0)
    le = K * L_mm

    # ── axial ─────────────────────────────────────────────────────────
    N = float(axial_force_kN) * 1e3
    fa = N / A
    tension = fa >= 0
    # a rod with no axial force to speak of is a beam: no axial term
    axial = abs(fa) > AXIAL_TOL_MPA
    if pole:
        # art. 3.3.1: a round member buckles as the square of equal area
        d1 = d2 = math.sqrt(A)
    else:
        d1, d2 = h, b
    sl1 = le / d1 if d1 > 0 else 0.0
    sl2 = le / d2 if d2 > 0 else 0.0
    FcE1 = 0.822 * Emin_adj / sl1 ** 2 if sl1 > 0 else float('inf')
    FcE2 = 0.822 * Emin_adj / sl2 ** 2 if sl2 > 0 else float('inf')
    slender = max(sl1, sl2)

    if tension and axial:
        ft = fa
        stresses['ft'] = ft
        CF_t = 1.0 if product in ('glulam', 'pole') else size_factor(max(h, b))
        Ft_adj = g['Ft'] * CD * cm('Ft') * ct('Ft') * CF_t
        factors['CF_t'] = CF_t
        design['Ft'] = Ft_adj
        ratios['tension ∥ (3.4.1)'] = ft / Ft_adj
    elif axial:
        fc = -fa
        stresses['fc'] = fc
        Fc_star = g['Fc'] * CD * cm('Fc') * ct('Fc')
        c = C_COLUMN.get(product, 0.8)
        CP = column_stability_factor(Fc_star, min(FcE1, FcE2), c)
        factors.update(CP=CP, c=c)
        design['Fc*'] = Fc_star
        design['Fc'] = Fc_star * CP
        design['FcE'] = min(FcE1, FcE2)
        ratios['compression ∥ (3.3.1)'] = fc / design['Fc']
        ratios['le/d ≤ 50 (3.3.1)'] = slender / SLENDERNESS_MAX

    # ── bending and shear ─────────────────────────────────────────────
    M1 = M2 = V = 0.0
    if member_res and member_res.get('conn') == 'rigid':
        from apps.stereo import stereo_math as sm
        diag = sm.member_diagram(member_res)
        M1 = float(max((abs(v) for v in diag['My']), default=0.0))  # strong
        M2 = float(max((abs(v) for v in diag['Mz']), default=0.0))  # weak
        V = float(max((abs(v) for v in diag['V']), default=0.0))
    I, Iw = (float(member.get('I', 0.0) or 0.0),
             float(member.get('Iw', 0.0) or 0.0))
    c1 = float(member.get('c_cm', 0.0) or 0.0)
    c2 = float(member.get('cw_cm', 0.0) or 0.0)
    fb1 = M1 * 1e6 / (I / c1 * 1e3) if M1 and I and c1 else 0.0
    fb2 = M2 * 1e6 / (Iw / c2 * 1e3) if M2 and Iw and c2 else 0.0

    def bending_design(depth, width):
        """(F*b, CL, FbE, RB) for bending whose depth is `depth`."""
        if product in ('sawn', 'boards'):
            size = size_factor(depth)
        elif product == 'glulam':
            size = volume_factor(depth, width)
        else:
            size = 1.0
        Fb_star = g['Fb'] * CD * cm('Fb') * ct('Fb') * size * Cr
        if pole or s['braced_edge'] or L_mm <= 0:
            return Fb_star, 1.0, float('inf'), 0.0, size
        RB = math.sqrt(lateral_buckling_length(L_mm, depth) * depth
                       / width ** 2)
        FbE = 1.2 * Emin_adj / RB ** 2 if RB > 0 else float('inf')
        # art. 3.2.1: d ≤ b needs no bracing, and 1 < d/b ≤ 2 is CL = 1
        # with the ends held -- the nodes of a space structure hold them.
        if depth <= 2.0 * width:
            CL = 1.0
        else:
            CL = beam_stability_factor(Fb_star, FbE)
        return Fb_star, CL, FbE, RB, size

    # Which axis a grade's Fb is for (Supplement 1): boards flatwise
    # ("flexión de plano", about the axis whose depth is the thinner side),
    # thick sawn pieces edgewise ("de canto").
    def in_scope(depth, width):
        if g['bending'] == _PLANO:
            return depth <= width
        if g['bending'] == _CANTO:
            return depth >= width
        return True

    FbE = float('inf')
    for tag, fb, depth, width in (('1', fb1, h, b), ('2', fb2, b, h)):
        if fb <= 0:
            continue
        Fb_star, CL, FbE_i, RB, size = bending_design(depth, width)
        stresses['fb' + tag] = fb
        design['Fb*' + tag] = Fb_star
        design['Fb' + tag] = Fb_star * CL
        factors['CL' + tag] = CL
        factors[('CV' if product == 'glulam' else 'CF') + '_b' + tag] = size
        if tag == '1':
            FbE = FbE_i
        ratios[f'bending, axis {tag} (3.2.1)'] = fb / (Fb_star * CL)
        if RB:
            ratios[f'RB ≤ 50, axis {tag} (3.2.1)'] = RB / RB_MAX
        if not in_scope(depth, width):
            partial.append(
                f'bending about axis {tag} is '
                + ('edgewise' if g['bending'] == _PLANO else 'flatwise')
                + f': Supplement 1 gives {key} an Fb for '
                + ('flatwise (de plano)' if g['bending'] == _PLANO
                   else 'edgewise (de canto)')
                + ' bending only, so this ratio uses it outside its scope')
    if V and A:
        fv = (4.0 / 3.0 if pole else 1.5) * V * 1e3 / A        # 3.2.2-2
        Fv_adj = g['Fv'] * CD * cm('Fv') * ct('Fv')
        stresses['fv'] = fv
        design['Fv'] = Fv_adj
        ratios['shear ∥ (3.2.2)'] = fv / Fv_adj

    # ── combined (art. 3.5) ───────────────────────────────────────────
    if fb1 or fb2:
        if tension and axial and stresses.get('ft'):
            ft = stresses['ft']
            r1 = ft / design['Ft'] + sum(
                stresses.get('fb' + t, 0.0) / design['Fb*' + t]
                for t in ('1', '2') if 'Fb*' + t in design)
            r2 = sum(stresses.get('fb' + t, 0.0) / design['Fb' + t]
                     for t in ('1', '2') if 'Fb' + t in design) \
                - ft / max(design.get('Fb1', design.get('Fb2', 1.0)), 1e-9)
            ratios['bending + tension (3.5.1-1)'] = r1
            ratios['bending − tension (3.5.1-2)'] = max(r2, 0.0)
        elif not tension and axial:
            fc = stresses['fc']
            if fc >= FcE1 or fc >= FcE2 or (fb1 and fb1 >= FbE):
                # the conditions under 3.5.2-1: past them it has no answer
                r = max(fc / FcE1, fc / FcE2,
                        fb1 / FbE if fb1 and FbE != float('inf') else 0.0)
            else:
                Fb1 = design.get('Fb1', 1.0)
                Fb2 = design.get('Fb2', 1.0)
                bE = (fb1 / FbE) ** 2 if FbE != float('inf') else 0.0
                r = ((fc / design['Fc']) ** 2
                     + (fb1 / (Fb1 * (1.0 - fc / FcE1)) if fb1 else 0.0)
                     + (fb2 / (Fb2 * (1.0 - fc / FcE2 - bE)) if fb2 else 0.0))
            ratios['bending + compression (3.5.2-1)'] = r

    ratios = {k: float(v) for k, v in ratios.items()}
    stresses = {k: float(v) for k, v in stresses.items()}
    if not ratios:
        return {'checked': True, 'util': 0.0, 'governing': None, 'ok': True,
                'mode': 'unloaded', 'material': 'timber', 'grade': key,
                'table': g['table'], 'code': REGLAMENTO, 'stresses_MPa': {},
                'design_MPa': design, 'factors': factors, 'ratios': {},
                'slenderness': None, 'settings': s, 'partial': [],
                'reference_MPa': {'ft': g['Ft'], 'fc': g['Fc'],
                                  'fb': g['Fb'], 'fv': g['Fv']},
                'note': f'Timber {key}: carries nothing in this load case.'}
    worst = max(ratios.items(), key=lambda kv: kv[1])
    util = worst[1]
    if not axial:
        mode = 'bending'
    else:
        mode = ('tension' if tension else 'compression') + (
            ' + bending' if (fb1 or fb2) else '')
    shown = ', '.join(f'{k} {v:.2f}' for k, v in stresses.items())
    note = (f'Timber {key}, {REGLAMENTO} ({describe_settings(s)}): '
            f'{shown} MPa; governs {worst[0]} at {util:.2f}'
            + (f'; le/d = {slender:.0f}' if not tension and axial else '')
            + ('. Not verified to the letter: ' + '; '.join(partial)
               if partial else '')
            + '. Allowable-stress check: the loads must be service '
              'loads, unfactored (art. 1.4).')
    # the governing stress beside its design value, for the tables
    pair = {'tension ∥ (3.4.1)': ('ft', 'Ft'),
            'compression ∥ (3.3.1)': ('fc', 'Fc'),
            'bending, axis 1 (3.2.1)': ('fb1', 'Fb1'),
            'bending, axis 2 (3.2.1)': ('fb2', 'Fb2'),
            'shear ∥ (3.2.2)': ('fv', 'Fv')}.get(worst[0])
    if pair is None:
        pair = next(((f, F) for f, F in (('ft', 'Ft'), ('fc', 'Fc'),
                                         ('fb1', 'Fb1'), ('fb2', 'Fb2'))
                     if f in stresses and F in design), (None, None))
    out = {'checked': True, 'util': util, 'governing': worst[0],
            'ok': util <= 1.0 + 1e-9, 'mode': mode, 'material': 'timber',
            'grade': key, 'table': g['table'], 'code': REGLAMENTO,
            'stresses_MPa': stresses, 'design_MPa': design,
            'reference_MPa': {'ft': g['Ft'], 'fc': g['Fc'], 'fb': g['Fb'],
                              'fv': g['Fv']},
            'factors': factors, 'ratios': ratios,
            'slenderness': slender if not tension else (
                max(sl1, sl2) if L_mm else None),
            'settings': s, 'partial': partial, 'note': note}
    if pair[0]:
        out['sigma_MPa'] = stresses[pair[0]]
        out['capacity_MPa'] = design[pair[1]]
    out['note'] = summary(out) + '. ' + note
    return out


def summary(chk):
    """One short line for a timber rod's result: the stresses against the
    adjusted design values, and the factors that moved them -- what the
    inspector and the tables show beside the utilisation."""
    if not chk or chk.get('material') != 'timber' or not chk.get('checked'):
        return ''
    d, f, st = chk.get('design_MPa', {}), chk.get('factors', {}), \
        chk.get('stresses_MPa', {})
    parts = []
    for k, F in (('ft', 'Ft'), ('fc', 'Fc'), ('fb1', 'Fb1'), ('fb2', 'Fb2'),
                 ('fv', 'Fv')):
        if k in st and F in d:
            parts.append(f"{k} {st[k]:.2f} / F'{F[1:]} {d[F]:.2f}")
    fac = [f'{k} {f[k]:.2f}' for k in ('CD', 'CP', 'CL1', 'CF_t', 'CF_b1',
                                         'CV_b1', 'Cr') if k in f
           and not (k == 'Cr' and f[k] == 1.0)]
    return ('CIRSOC 601: ' + '; '.join(parts) + ' MPa'
            + (f" ({', '.join(fac)})" if fac else ''))


# The settings, as flat keys for a workbook's [META] block -- so a model
# saved with its timber checked for wind comes back checked for wind.
META_KEYS = {'duration': 'timber_duration', 'wet': 'timber_wet',
             'temperature': 'timber_temperature',
             'load_sharing': 'timber_load_sharing',
             'braced_edge': 'timber_braced_edge'}


def settings_to_meta(settings=None):
    s = settings_of(settings)
    return {META_KEYS[k]: s[k] for k in META_KEYS}


def settings_from_meta(meta):
    """The settings a workbook's [META] block carries, or None if it has
    none (a file saved before timber was checked)."""
    meta = meta or {}
    if not any(v in meta for v in META_KEYS.values()):
        return None
    out = {}
    for k, mk in META_KEYS.items():
        if mk not in meta:
            continue
        v = meta[mk]
        if k in ('wet', 'load_sharing', 'braced_edge'):
            v = str(v).strip().lower() in ('1', 'true', 'yes', 'si', 'sí')
        out[k] = v
    return settings_of(out)
