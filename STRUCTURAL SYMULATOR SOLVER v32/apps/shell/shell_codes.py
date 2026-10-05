"""shell_codes.py -- the reinforced-concrete design code the Shell tab checks
against, as a swappable layer. 2026-09-14.

WHY A LAYER. The user asked for CIRSOC 201 now and for ACI 318-19 and
Eurocode 2 later. So every number that belongs to a code -- resistance
factors, load-combination coefficients, the concrete modulus, minimum steel,
bar spacing, cover, the shear strength of a slab -- lives on a DesignCode
object, and `shell_design.py` asks the selected object for it. Adding a code
is writing one subclass; no design routine changes, and no design routine
contains a code-specific number.

TWO CIRSOC EDITIONS, AND WHERE THE SHELL RULES COME FROM.

* CIRSOC 201-2024 (Proyecto de Reglamento) -- the document the user
  supplied (Downloads/PROGRAMACION/CIRSOC-201-2024-Proyecto-de-Reglamento.pdf).
  It follows ACI 318-19. Every general value below was read off that
  document and carries its clause. It does NOT contain shell rules: its
  C 1.2.10.7 sends the design of shells and folded plates to "la
  Recomendacion CIRSOC 201.03-2024 (en etapa de redaccion)" -- still being
  drafted -- exactly as ACI moved shells out of ACI 318 into ACI 318.2.
* CIRSOC 201-2005 (= ACI 318-05), whose Chapter 19 IS the shell chapter.
  Its shell-specific rules (f'c >= 21 MPa, fy <= 420 MPa, bar spacing 5t /
  3t, one-face steel mirrored) are used by BOTH classes, flagged in the
  report as "shell rule taken from CIRSOC 201-2005 Ch. 19 pending
  CIRSOC 201.03". The 2005 text itself was not on this machine; its values
  are listed in UNVERIFIED.

WIND. CIRSOC 201-2024 combines 1.0 W (Tabla 5.3.1) because it is paired
with CIRSOC 102-2024, whose wind speeds are strength-level (ASCE 7-10
basis, C 5.2.1). CIRSOC 201-2005 combined 1.6 W with the service-level
speeds of CIRSOC 102-2005. `combinations(..., wind_scale=k)` multiplies
every W factor by k, so a W case computed from 2005 speeds is combined as
1.6 x W under the 2024 code -- which reproduces the 2005 factors exactly
(0.5 x 1.6 = 0.8, 1.0 x 1.6 = 1.6). The model chooses k from the wind basis.

UNITS: MPa for stresses, mm for bar sizes, cover and spacing, m for
thickness, N/m for forces per width, N*m/m for moments per width.
"""
import math
from dataclasses import dataclass

import numpy as np


@dataclass
class Combination:
    name: str               # e.g. '(5.3.1d)  1.2D + 1.6W1 + 0.5Lr'
    factors: dict           # load-case name -> factor
    formula: str = ''       # the code's own equation label
    service: bool = False   # True for the unfactored (serviceability) set


# Load-case KINDS a user may classify a case as. A kind the code does not
# know is refused rather than silently given a factor.
KINDS = ('D', 'L', 'Lr', 'S', 'W', 'E')
KIND_LABELS = {'D': 'D  dead (self-weight, finishes)',
               'L': 'L  live (occupancy)',
               'Lr': 'Lr roof live (maintenance)',
               'S': 'S  snow',
               'W': 'W  wind',
               'E': 'E  earthquake'}

WIND_BASES = {
    '2005': 'CIRSOC 102-2005 speeds (service level; the city table in this tab)',
    '2024': 'CIRSOC 102-2024 speeds (strength level)',
}


def _pick(cases, kind):
    return [c for c, k in cases.items() if k == kind]


class DesignCode:
    """Base class. Subclasses set the attributes and implement the methods."""
    key = 'base'
    name = 'base'
    short = 'base'
    wind_basis = '2024'          # which CIRSOC 102 edition its W factors assume

    phi_tension = 0.90           # tension-controlled
    phi_compression = 0.65       # compression-controlled
    phi_shear = 0.75
    phi_plain = 0.60             # structural plain concrete
    phi_strut = 0.75             # strut-and-tie
    beta_cracked = 0.40          # strut in a tension zone
    beta_uncracked = 1.00        # concrete in biaxial compression

    fc_min_shell = 21.0          # MPa (shell rule)
    fy_max_shell = 420.0         # MPa (shell rule)

    clauses = {}
    UNVERIFIED = ()

    # -- materials ----------------------------------------------------------
    def Ec(self, fc):
        """Concrete modulus (MPa) of normal-weight concrete from f'c (MPa)."""
        return 4700.0 * math.sqrt(fc)

    def fr(self, fc):
        return 0.62 * math.sqrt(fc)

    # -- shell rules shared by both CIRSOC editions -------------------------
    def max_spacing(self, t_m, high_tension=False):
        """Largest bar spacing (mm): 5t and 450 mm, or 3t where the principal
        membrane tension is high (shell rule, 2005 19.4.10)."""
        k = 3.0 if high_tension else 5.0
        return min(k * t_m * 1000.0, 450.0)

    def high_tension_limit(self, fc):
        """Principal membrane tension stress (MPa) above which bars must be
        at most 3t apart (2005 19.4.10: 0.33 phi sqrt(f'c))."""
        return 0.33 * self.phi_tension * math.sqrt(fc)

    def plain_tension_stress(self, fc):
        """Nominal flexural tension stress (MPa) of plain concrete."""
        return 0.42 * math.sqrt(fc)

    def strut_strength(self, fc, cracked):
        """Design compressive strength (MPa) of a concrete layer or panel."""
        beta = self.beta_cracked if cracked else self.beta_uncracked
        return self.phi_strut * 0.85 * beta * fc

    # -- to be provided by each code ---------------------------------------
    def rho_min(self, fy):
        raise NotImplementedError

    def Vc(self, fc, d_m, rho_w=0.0, Nu=0.0, h_m=None):
        """Nominal one-way shear strength of the concrete, N per m of width.
        Nu: axial force per m width, COMPRESSION POSITIVE (the code's sign)."""
        raise NotImplementedError

    def min_cover_mm(self, db_mm, exposed=True, controlled=True, exposure_factor=1.0):
        raise NotImplementedError

    def punching_vc(self, fc, d_m, b0_m, beta=1.0, alpha_s=40.0):
        """Two-way (punching) shear stress the concrete carries, MPa."""
        raise NotImplementedError

    def combinations(self, cases, f1=0.5, f2=0.2, wind_scale=1.0):
        raise NotImplementedError

    def service_combination(self, cases):
        facs = {c: 1.0 for c, k in cases.items() if k in ('D', 'L', 'Lr', 'S')}
        return Combination('Service  D + L + Lr + S', facs, 'service', service=True)

    def wind_scale_for(self, basis):
        """Multiplier on W so that wind computed on `basis` speeds is
        combined correctly under this code."""
        if basis == self.wind_basis:
            return 1.0
        if self.wind_basis == '2024' and basis == '2005':
            return 1.6
        if self.wind_basis == '2005' and basis == '2024':
            return 1.0 / 1.6
        raise KeyError(f'unknown wind basis {basis!r}')


class CIRSOC201_2024(DesignCode):
    """CIRSOC 201-2024, Proyecto de Reglamento (follows ACI 318-19)."""
    key = 'cirsoc201_2024'
    name = 'CIRSOC 201-2024 (Proyecto; follows ACI 318-19)'
    short = 'CIRSOC 201-24'
    wind_basis = '2024'

    phi_plain = 0.60             # Tabla 21.2.1 (i)
    beta_cracked = 0.40          # Tabla 23.4.3(a) (a): tension zones
    beta_uncracked = 1.00        # Tabla 23.4.3(a) (b)

    clauses = {
        'scope': 'C 1.2.10.7 -- shells are to follow Recomendacion CIRSOC '
                 '201.03-2024, still being drafted; shell-specific rules are '
                 'taken from CIRSOC 201-2005 Ch. 19 meanwhile',
        'combinations': '5.3.1, Tabla 5.3.1, eqs. (5.3.1a) to (5.3.1g); 5.3.3 (0.5L)',
        'phi': 'Tabla 21.2.1: 0.65-0.90 flexure/axial (21.2.2), 0.75 shear, '
               '0.75 strut-and-tie, 0.60 plain concrete',
        'Ec': '19.2.2.1(b)  Ec = 4700 sqrt(f\'c)',
        'fr': '19.2.3.1  fr = 0.62 lambda sqrt(f\'c)',
        'fc_min': 'Tabla 19.2.1.1: 20 MPa general; shells 21 MPa (2005 19.3.1)',
        'fy_max': 'shells: fy <= 420 MPa (2005 19.3.2)',
        'minimum': '24.4.3.2  rho >= 0.0018 (deformed bars); 8.6.1.1',
        'spacing': '24.4.3.3  s <= 5h and 450 mm; shells: 3t where the '
                   'principal membrane tension > 0.33 phi sqrt(f\'c) (2005 19.4.10)',
        'shear': 'Tabla 22.5.5.1 (c): Vc = (0.66 lambda_s rho_w^(1/3) sqrt(f\'c) '
                 '+ Nu/(6Ag)) b d; 22.5.5.1.1 cap 0.42 sqrt(f\'c) b d; '
                 '22.5.5.1.2 Nu/(6Ag) <= 0.05 f\'c; 22.5.5.1.3 lambda_s',
        'plain': '14.5.2.1(a)  Mn = 0.42 sqrt(f\'c) Sm, with phi = 0.60',
        'punching': '22.6.4.1 critical section at d/2 from the column head; '
                    'Tabla 22.6.5.2 vc; 22.6.5.3 alpha_s = 40 interior',
        'strut': '23.4.3: f_ce = 0.85 beta_s f\'c; beta_s = 0.40 in tension '
                 'zones (Tabla 23.4.3(a)(a)), 1.0 where not cracked; phi = 0.75',
        'cover': 'Tabla 20.5.1.3.1 (b): weather-exposed, db <= 16 mm: 35 mm '
                 'controlled / 40 mm other; db > 16 mm: 40 / 45',
        'membrane': 'shells: tension steel in two or more directions resisting '
                    'the component of the internal forces in each (2005 19.4.2)',
        'bending': 'shells: bending with the simultaneous membrane force; '
                   'one-face steel mirrored to the other face (2005 19.4.9)',
        'buckling': 'the code requires shell buckling to be investigated but '
                    'gives no formula; the classical local formula with a '
                    'user-set reduction is used',
    }
    UNVERIFIED = (
        'shell-specific rules (f\'c >= 21 MPa, fy <= 420 MPa, 3t spacing, '
        'one-face steel mirrored) are CIRSOC 201-2005 Ch. 19 / ACI 318-05 '
        'values, pending the Recomendacion CIRSOC 201.03-2024; the 2005 text '
        'has not been read',
        'the strut efficiency 0.40 for a cracked shell layer is the most '
        'conservative entry of Tabla 23.4.3(a), used by analogy',
    )

    def rho_min(self, fy):
        return 0.0018                                   # 24.4.3.2

    def Vc(self, fc, d_m, rho_w=0.0, Nu=0.0, h_m=None):
        """Tabla 22.5.5.1 (c) -- no shear reinforcement. Works on arrays."""
        d_mm = np.asarray(d_m, float) * 1000.0
        lam_s = np.minimum(np.sqrt(2.0 / (1.0 + 0.004 * d_mm)), 1.0)   # 22.5.5.1.3
        rho_w = np.maximum(np.asarray(rho_w, float), 0.0)
        h_m = np.asarray(d_m if h_m is None else h_m, float)
        axial = np.asarray(Nu, float) / (6.0 * h_m * 1e6)              # MPa, Nu N/m
        axial = np.minimum(axial, 0.05 * fc)                            # 22.5.5.1.2
        v = 0.66 * lam_s * np.cbrt(rho_w) * math.sqrt(fc) + axial
        v = np.clip(v, 0.0, 0.42 * math.sqrt(fc))                       # 22.5.5.1.1, note 2
        return v * d_mm * 1000.0                                        # N per m width

    def punching_vc(self, fc, d_m, b0_m, beta=1.0, alpha_s=40.0):
        """Tabla 22.6.5.2 (no shear reinforcement): least of
        0.33 ls sqrt(f'c), 0.17 (1 + 2/beta) ls sqrt(f'c) and
        0.083 (2 + alpha_s d / b0) ls sqrt(f'c); ls per 22.5.5.1.3;
        alpha_s = 40 interior, 30 edge, 20 corner (22.6.5.3)."""
        lam_s = min(math.sqrt(2.0 / (1.0 + 0.004 * d_m * 1000.0)), 1.0)
        r = math.sqrt(fc) * lam_s
        return min(0.33 * r, 0.17 * (1 + 2.0 / beta) * r,
                   0.083 * (2 + alpha_s * d_m / b0_m) * r)

    def min_cover_mm(self, db_mm, exposed=True, controlled=True, exposure_factor=1.0):
        """Tabla 20.5.1.3.1 for slabs; exposure_factor 1.3 for classes A3, Q1,
        C1 and 1.5 for CL1, CL2, M1-M3, C2, Q2, Q3 (the table's note)."""
        if exposed:
            if db_mm > 16.0:
                c = 40.0 if controlled else 45.0
            else:
                c = 35.0 if controlled else 40.0
        else:
            if db_mm > 32.0:
                c = db_mm + (5.0 if controlled else 10.0)
            else:
                c = max(25.0 if controlled else 30.0,
                        db_mm + (5.0 if controlled else 10.0))
        return c * exposure_factor

    def combinations(self, cases, f1=0.5, f2=0.2, wind_scale=1.0):
        """Tabla 5.3.1, with every wind and earthquake case taken one at a
        time and each of Lr / S taken as the '(Lr o S o R)' term in turn.
        f1 is the live-load factor of (5.3.1c) to (5.3.1e) (1.0, or 0.5 where
        5.3.3 allows it); (5.3.1e) uses 0.2 S as printed (f2 is not used by
        this edition). F, H, T and R are not modelled on a roof shell."""
        return _combos(cases, {
            'a': ('(5.3.1a)', 1.4),
            'b': ('(5.3.1b)', 1.2, 1.6, 0.5),
            'c': ('(5.3.1c)', 1.2, 1.6, f1, 0.5 * wind_scale),
            'd': ('(5.3.1d)', 1.2, 1.0 * wind_scale, f1, 0.5),
            'e': ('(5.3.1e)', 1.2, 1.0, f1, 0.2),
            'f': ('(5.3.1f)', 0.9, 1.0 * wind_scale),
            'g': ('(5.3.1g)', 0.9, 1.0),
        })


class CIRSOC201_2005(DesignCode):
    """CIRSOC 201-2005 (follows ACI 318-05), which has the shell chapter."""
    key = 'cirsoc201_2005'
    name = 'CIRSOC 201-2005 (follows ACI 318-05)'
    short = 'CIRSOC 201-05'
    wind_basis = '2005'

    phi_plain = 0.55             # 9.3.5 (ACI 318-05)
    beta_cracked = 0.60          # A.3.2.2(b) (ACI 318-05)
    beta_uncracked = 1.00

    clauses = {
        'combinations': '9.2.1, eqs. (9-1) to (9-7)',
        'phi': '9.3.2 (0.90 / 0.65 / 0.75); 9.3.5 (0.55 plain concrete)',
        'Ec': '8.5.1  Ec = 4700 sqrt(f\'c)',
        'fr': '9.5.2.3  fr = 0.62 sqrt(f\'c)',
        'fc_min': '19.3.1  f\'c >= 21 MPa for shells',
        'fy_max': '19.3.2  fy <= 420 MPa for shell reinforcement',
        'membrane': '19.4.1, 19.4.2',
        'minimum': '19.4.3 -> 7.12.2.1  rho >= 0.0018 (fy = 420)',
        'bending': '19.4.4, 19.4.9',
        'spacing': '19.4.10  s <= 5t and 450 mm; 3t where the principal '
                   'membrane tension exceeds 0.33 phi sqrt(f\'c)',
        'shear': '11.3.1  Vc = sqrt(f\'c)/6 b d, with 11.3.1.2 / 11.3.1.3 for axial force',
        'plain': '22.5.1  Mn = 0.42 sqrt(f\'c) S',
        'strut': 'A.3.2 (by analogy): f_ce = 0.85 beta_s f\'c, beta_s = 0.60',
        'cover': '7.7.1(c)  shells: 20 mm for db >= 19 mm, 13 mm below',
        'buckling': '19.2 -- investigation required, no formula given',
    }
    UNVERIFIED = (
        'every value of this class is ACI 318-05\'s; the CIRSOC 201-2005 text '
        'was not on this machine',
    )

    def rho_min(self, fy):
        fy = min(fy, self.fy_max_shell)
        if fy < 420.0:
            return 0.0020
        return max(0.0018 * 420.0 / fy, 0.0014)

    def Vc(self, fc, d_m, rho_w=0.0, Nu=0.0, h_m=None):
        d_m = np.asarray(d_m, float)
        h_m = np.asarray(d_m if h_m is None else h_m, float)
        s = np.asarray(Nu, float) / (h_m * 1e6)   # MPa, compression +
        f = np.where(s >= 0, 1.0 + s / 14.0,      # 11.3.1.2
                     np.maximum(1.0 + 0.29 * s, 0.0))   # 11.3.1.3
        return f * math.sqrt(fc) / 6.0 * 1000.0 * d_m * 1000.0

    def min_cover_mm(self, db_mm, exposed=True, controlled=True, exposure_factor=1.0):
        return (20.0 if db_mm >= 19.0 else 13.0) * exposure_factor

    def punching_vc(self, fc, d_m, b0_m, beta=1.0, alpha_s=40.0):
        """11.12.2.1 (ACI 318-05): least of 0.17(1 + 2/beta), 0.083(alpha_s d/b0 + 2)
        and 0.33, times sqrt(f'c); no size effect in this edition."""
        r = math.sqrt(fc)
        return min(0.17 * (1 + 2.0 / beta) * r, 0.083 * (alpha_s * d_m / b0_m + 2) * r,
                   0.33 * r)

    def combinations(self, cases, f1=0.5, f2=0.2, wind_scale=1.0):
        return _combos(cases, {
            'a': ('(9-1)', 1.4),
            'b': ('(9-2)', 1.2, 1.6, 0.5),
            'c': ('(9-3)', 1.2, 1.6, f1, 0.8 * wind_scale),
            'd': ('(9-4)', 1.2, 1.6 * wind_scale, f1, 0.5),
            'e': ('(9-5)', 1.2, 1.0, f1, f2),
            'f': ('(9-6)', 0.9, 1.6 * wind_scale),
            'g': ('(9-7)', 0.9, 1.0),
        })


def _combos(cases, t):
    """The seven ASCE-7-shaped strength combinations, filled from table `t`:
        a: kD                              (1.4D)
        b: kD D + kL L + kR (Lr|S)
        c: kD D + kR (Lr|S) + (kL L  or  kW W)
        d: kD D + kW W + kL L + kR (Lr|S)
        e: kD D + kE E + kL L + kS S
        f: kD D + kW W
        g: kD D + kE E
    Each W and E case is taken one at a time; each Lr / S case in turn."""
    D, L = _pick(cases, 'D'), _pick(cases, 'L')
    roof = _pick(cases, 'Lr') + _pick(cases, 'S')
    W, E, S = _pick(cases, 'W'), _pick(cases, 'E'), _pick(cases, 'S')
    out = []

    def add(formula, facs):
        facs = {c: round(f, 6) for c, f in facs.items() if f}
        if not facs:
            return
        key = tuple(sorted(facs.items()))
        if any(tuple(sorted(o.factors.items())) == key for o in out):
            return
        label = ' + '.join(f'{f:g}{c}' for c, f in facs.items())
        out.append(Combination(f'{formula}  {label}', facs, formula))

    def w(base, names, f):
        d = dict(base)
        for n in names:
            d[n] = d.get(n, 0.0) + f
        return d

    fa, ka = t['a']
    add(fa, w({}, D, ka))
    roof_opts = [[r] for r in roof] or [[]]
    fb, kD, kL, kR = t['b']
    for r in roof_opts:
        add(fb, w(w(w({}, D, kD), L, kL), r, kR))
    fc_, kD, kR, kL, kW = t['c']
    for r in roof_opts:
        if not r:
            continue
        base = w(w({}, D, kD), r, kR)
        add(fc_, w(base, L, kL))
        for wi in W:
            add(fc_, w(base, [wi], kW))
    fd, kD, kW, kL, kR = t['d']
    ff, kDf, kWf = t['f']
    for wi in W:
        for r in roof_opts:
            add(fd, w(w(w(w({}, D, kD), [wi], kW), L, kL), r, kR))
        add(ff, w(w({}, D, kDf), [wi], kWf))
    fe, kD, kE, kL, kS = t['e']
    fg, kDg, kEg = t['g']
    for ei in E:
        add(fe, w(w(w(w({}, D, kD), [ei], kE), L, kL), S, kS))
        add(fg, w(w({}, D, kDg), [ei], kEg))
    return out


CODES = {CIRSOC201_2024.key: CIRSOC201_2024, CIRSOC201_2005.key: CIRSOC201_2005}
CODE_ORDER = (CIRSOC201_2024.key, CIRSOC201_2005.key)
DEFAULT_CODE = CIRSOC201_2024.key


def get_code(key=DEFAULT_CODE):
    try:
        return CODES[key]()
    except KeyError:
        raise KeyError(f'unknown design code {key!r}; available: {list(CODES)}') from None
