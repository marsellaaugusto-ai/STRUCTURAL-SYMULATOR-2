"""
cirsoc_301.py — design-code layer: CIRSOC 301-2018 resistance factors and
nominal strengths. SHARED, like common.py: no tab owns it.

It began life inside apps/perforated_beam/ and moved to the root on
2026-09-06, when the Truss tab'''s plate feature needed the same weld, shear
and stress checks. MODULAR_ARCHITECTURE.md keeps each tab independent and
lets them share only root-level modules, so a cross-tab import
(apps/truss importing apps/perforated_beam) was not an option. Nothing in
the content changed in that move.

WHAT CHANGED AND WHY THIS MODULE EXISTS
---------------------------------------
Until now this tab reported RAW ELASTIC UTILISATIONS -- ratios like
sqrt(sigma^2 + 3*tau^2)/Fy, with no resistance factor applied anywhere --
and the MANIFESTO said so plainly, because the CIRSOC documents were not
available and inventing clause numbers in a structural tool is worse than
having none. The documents are now in hand, so the factors and nominal
strengths below are transcribed from them, each with its clause.

Reglamento CIRSOC 301-2018, "Reglamento Argentino de Estructuras de Acero
para Edificios" (INTI-CIRSOC, July 2018), which states in its own preface
that it adopts ANSI/AISC 360-2010 as its basis. Where CIRSOC DIFFERS from
AISC the CIRSOC value governs here -- see `PHI_WELD` for the one that
matters most.

UNITS. CIRSOC writes its formulas in cm / kN / kNm and carries explicit
(10)^-1 and (10)^-3 conversion factors. This module works in the tab's own
mm / N / N*mm / MPa, in which those factors are identically 1, so they do
not appear below. Every formula here is the same equation with the unit
bookkeeping removed, not a different one.

SCOPE. This module computes CAPACITIES and resistance factors. It does not
select or combine load cases: the demands V(x)/M(x)/T(x) come from
whatever loads the user entered, and it remains the user's responsibility
that those are FACTORED actions per CIRSOC 101 (permanent/live) and
CIRSOC 102 (wind). That boundary is unchanged from before.

WEB OPENINGS. CIRSOC 301 G.8 ("Vigas con aberturas en el alma") is one
paragraph: the effect of any web opening on the design shear strength
must be determined, and where the required strength exceeds the design
strength, adequate reinforcement must be provided at the opening. It
prescribes NO method. So the Vierendeel / web-post / doubler machinery in
perforated_beam_math.py is not in conflict with CIRSOC -- it is one way of
discharging a duty CIRSOC states and deliberately leaves open, with the
method itself taken from the AISC Design Guide 31 / SCI P355 literature.
What this module adds is that the resulting stresses are now compared
against factored CIRSOC resistances (H.3.3) instead of raw Fy.
"""
import math
from dataclasses import dataclass


# ─────────────────────────────────────────────────────────────────────────
# 1. Resistance factors, each with its clause
# ─────────────────────────────────────────────────────────────────────────

PHI_FLEXURE = 0.90   # F.1(1)   -- all cases in Chapter F
PHI_SHEAR = 0.90     # G.1.1    -- Vd = phi_v * Vn
PHI_NORMAL = 0.90    # H.3.4    -- yielding under normal stress
PHI_TAU = 0.90       # H.3.5    -- yielding under shear stress
PHI_BUCKLING = 0.85  # H.3.6    -- buckling limit state, phi_c
PHI_WELD = 0.60      # Table J.2.5, SOLDADURAS DE FILETE, shear on the
                     # effective area.
                     #
                     # THIS IS NOT THE AISC VALUE. AISC 360-16 Table J2.5
                     # (and 360-10 before it) gives phi = 0.75 for the same
                     # limit state; CIRSOC 301 adopts AISC 360-10 as its
                     # basis but uses 0.60 here. Using the AISC number
                     # under CIRSOC would overstate every fillet weld's
                     # capacity by 25%, so this is the single most
                     # consequential number in this module. Verified
                     # against the table on page 202 of the 2018 edition.

E_STEEL = 200000.0   # MPa, stated in the notes to Table B.4.1b
FL_ROLLED_FACTOR = 0.7   # Table B.4.1b note (b): FL = 0.7*Fy for rolled sections
KV_UNSTIFFENED = 5.0     # G.2.1(b): unstiffened webs with h/tw <= 260


@dataclass(frozen=True)
class DesignCode:
    """The resistance factors as data, so a check can be re-run under a
    different basis (an AISC job, or a future CIRSOC edition) without
    editing formulas. Defaults are CIRSOC 301-2018."""
    name: str = 'CIRSOC 301-2018'
    phi_flexure: float = PHI_FLEXURE
    phi_shear: float = PHI_SHEAR
    phi_normal: float = PHI_NORMAL
    phi_tau: float = PHI_TAU
    phi_buckling: float = PHI_BUCKLING
    phi_weld: float = PHI_WELD
    weld_throat_factor: float = 0.707   # J.2.2(a); see fillet_throat()
    # The two below are AISC factors, NOT read off the CIRSOC table --
    # see section 7, BLOCK_SHEAR_AND_BUCKLING_PROVENANCE.
    phi_rupture: float = 0.75
    phi_compression: float = 0.90

    @property
    def citation(self):
        return (f'{self.name}: phi_b={self.phi_flexure} (F.1), '
                f'phi_v={self.phi_shear} (G.1.1), phi={self.phi_normal} (H.3.4/H.3.5), '
                f'phi_c={self.phi_buckling} (H.3.6), phi_weld={self.phi_weld} (Tabla J.2.5)')


CIRSOC_301 = DesignCode()
AISC_360 = DesignCode(name='AISC 360-16', phi_weld=0.75)   # the one factor that differs


# ─────────────────────────────────────────────────────────────────────────
# 2. Section classification -- Table B.4.1b
# ─────────────────────────────────────────────────────────────────────────

COMPACT, NONCOMPACT, SLENDER = 'compacta', 'no compacta', 'esbelta'
# Used where a section has plates but no named flange/web to classify --
# a drawn polygon. Distinct from COMPACT: unknown is not a pass.
UNKNOWN_CLASS = 'no clasificada'


def _classify(ratio, lam_p, lam_r):
    if ratio <= lam_p:
        return COMPACT
    if ratio <= lam_r:
        return NONCOMPACT
    return SLENDER


def classify_flange(section, Fy, E=E_STEEL):
    """Table B.4.1b case 11 -- flanges of rolled I and channel sections in
    flexure. b/t is the HALF-flange outstand over flange thickness.
    lam_p = 0.38*sqrt(E/Fy); lam_r = 0.83*sqrt(E/FL) with FL = 0.7*Fy."""
    b_t = (section.bf / 2.0) / section.tf
    lam_p = 0.38 * math.sqrt(E / Fy)
    lam_r = 0.83 * math.sqrt(E / (FL_ROLLED_FACTOR * Fy))
    return _classify(b_t, lam_p, lam_r), b_t, lam_p, lam_r


def classify_web(section, Fy, E=E_STEEL):
    """Table B.4.1b case 16 -- webs of doubly symmetric I sections in
    flexure. lam_p = 3.76*sqrt(E/Fy); lam_r = 5.70*sqrt(E/Fy).

    h is taken as the clear distance between flanges. For a rolled shape
    CIRSOC subtracts the root fillets too; this tab ignores fillets
    everywhere (see MANIFESTO), which makes h slightly larger and the
    classification slightly conservative -- the right direction."""
    h = section.d - 2 * section.tf
    h_tw = h / section.tw
    lam_p = 3.76 * math.sqrt(E / Fy)
    lam_r = 5.70 * math.sqrt(E / Fy)
    return _classify(h_tw, lam_p, lam_r), h_tw, lam_p, lam_r


# ─────────────────────────────────────────────────────────────────────────
# 3. Flexural strength -- Chapter F
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class FlexureResult:
    Mn: float            # nominal flexural strength, N*mm
    Md: float            # design strength phi_b * Mn, N*mm
    Mp: float
    My: float
    Lp: float            # limiting unbraced length for Mn = Mp, mm
    Lr: float
    Lb: float
    flange_class: str
    web_class: str
    governing: str       # which limit state set Mn
    note: str = ''


def flexural_strength(section, Fy, Lb=0.0, Cb=1.0, code=CIRSOC_301,
                      E=E_STEEL, G=None, load_on_top_flange=False):
    """Nominal and design flexural strength of a doubly symmetric rolled I
    section about its strong axis, per CIRSOC 301 Chapter F.

    F.2.1  Mn = Mp = Fy*Zx <= 1.5*My                (plastification)
    F.2.2  Mn = Mp                                   for Lb <= Lp
           Mn = Cb[Mp - (Mp-Mr)(Lb-Lp)/(Lr-Lp)] <= Mp   for Lp < Lb <= Lr
           Mn = Mcr <= Mp                            for Lb > Lr
    F.2.5a Lp = 1.76*ry*sqrt(E/Fyf)   (load at the web or bottom flange)
    F.2.5b Lp = 1.59*ry*sqrt(E/Fyf)   (load at the top flange)
    F.2.6a Lr = (ry*X1/FL)*sqrt(1 + sqrt(1 + X2*FL^2))
    F.2.7a Mr = FL*Sx,  FL = 0.7*Fy for rolled sections

    `Lb = 0` means the compression flange is CONTINUOUSLY BRACED, which is
    the normal condition for a floor beam with the slab on it and is the
    default here. It is not a silent assumption: `FlexureResult.note` says
    so, and the UI exposes Lb.

    F.2 applies to COMPACT sections. A non-compact or slender flange or
    web is detected and reported rather than silently run through the
    compact formula -- CIRSOC sends those to F.3/F.4/F.5, which this
    module does not implement (see `note`), so the result is capped at My
    as a conservative preliminary stand-in."""
    if G is None:
        G = E / (2 * (1 + 0.3))
    Zx = section.Zpl
    Sx = section.S
    Mp = Fy * Zx
    My = Fy * Sx
    Mp = min(Mp, 1.5 * My)                                      # F.2.1
    fl_class, _, _, _ = classify_flange(section, Fy, E)
    web_class, _, _, _ = classify_web(section, Fy, E)

    ry = math.sqrt(section.Iy / section.A)
    coeff = 1.59 if load_on_top_flange else 1.76
    Lp = coeff * ry * math.sqrt(E / Fy)                          # F.2.5a/b

    FL = FL_ROLLED_FACTOR * Fy                                   # Table B.4.1b note (b)
    Mr = FL * Sx                                                 # F.2.7a
    J = section.J
    Ag = section.A
    h0 = section.d - section.tf
    Cw = section.Iy * h0 ** 2 / 4.0        # doubly symmetric I, standard identity
    X1 = (math.pi / Sx) * math.sqrt(E * G * J * Ag / 2.0)        # F.2.4c
    X2 = 4.0 * (Cw / section.Iy) * (Sx / (G * J)) ** 2
    Lr = (ry * X1 / FL) * math.sqrt(1.0 + math.sqrt(1.0 + X2 * FL ** 2))   # F.2.6a

    note = ''
    if Lb <= 1e-9:
        Mn, governing = Mp, 'plastification (F.2.1), compression flange continuously braced'
        note = ('Lb = 0 was taken as a continuously braced compression flange. If the '
                'flange is NOT braced along its length, enter the real Lb -- lateral-'
                'torsional buckling can govern well below Mp.')
    elif Lb <= Lp:
        Mn, governing = Mp, 'plastification (F.2.1), Lb <= Lp'
    elif Lb <= Lr:
        Mn = Cb * (Mp - (Mp - Mr) * (Lb - Lp) / (Lr - Lp))       # F.2.2
        Mn = min(Mn, Mp)
        governing = 'inelastic lateral-torsional buckling (F.2.2)'
    else:
        # F.2.4a, loads at the web or bottom flange
        Mcr = ((Cb * math.pi / Lb) * math.sqrt(E * section.Iy * G * J
                                               + (math.pi * E / Lb) ** 2 * section.Iy * Cw))
        Mn = min(Mcr, Mp)                                        # F.2.3
        governing = 'elastic lateral-torsional buckling (F.2.3/F.2.4a)'

    if fl_class != COMPACT or web_class != COMPACT:
        capped = min(Mn, My)
        note = (note + ' ' if note else '') + (
            f'Section is not compact (flange {fl_class}, web {web_class}). CIRSOC sends '
            'this to F.3/F.4/F.5, which are not implemented here; Mn has been capped at '
            'My = Fy*Sx as a conservative preliminary stand-in. Verify against F.3-F.5 '
            'before relying on it.')
        Mn = capped
        governing += ' (capped at My, section not compact)'

    return FlexureResult(Mn=Mn, Md=code.phi_flexure * Mn, Mp=Mp, My=My,
                         Lp=Lp, Lr=Lr, Lb=Lb, flange_class=fl_class,
                         web_class=web_class, governing=governing, note=note)


def flexural_strength_box(section, Fy, Zx, Lb=0.0, Cb=1.0, code=CIRSOC_301,
                          E=E_STEEL, G=None, b_t=None, h_tw=None, J_eff=None):
    """Chapter F7 -- square/rectangular BOX and HSS sections.

    F2 is written for open I-sections: its Lr uses the warping constant
    through the identity Cw = Iy*h0^2/4, which is a doubly symmetric I
    identity and has no meaning for a closed cell (a closed section warps
    almost not at all). Running a box through F2 therefore does not merely
    lose accuracy, it uses a formula for a quantity the section does not
    have. F7 is the clause CIRSOC/AISC provide instead, and it keys off
    J and A rather than Cw:

      F7.2  Lp = 0.13*E*ry*sqrt(J*Ag)/Mp
            Lr = 2*E*ry*sqrt(J*Ag)/(0.7*Fy*Sx)
            Mn = Mp                                        Lb <= Lp
            Mn = Cb[Mp - (Mp - 0.7*Fy*Sx)(Lb-Lp)/(Lr-Lp)]  Lp < Lb <= Lr
            Mn = 2*E*Cb*sqrt(J*Ag)/(Lb/ry)                 Lb > Lr

    For a deep closed cell J is enormous, so Lr comes out at hundreds of
    metres and LTB effectively never governs -- which is the whole reason
    a box is chosen for a long unbraced span. That is a real result, not
    a modelling artefact, but it is only trustworthy if the WALLS are not
    slender, so both walls are classified here (B4.1b cases 12 and 13)
    and a slender one is reported rather than passed over."""
    if G is None:
        G = E / (2 * (1 + 0.3))
    Sx = section.S
    Ag = section.A
    # J_eff lets the caller hand in a torsion constant already reduced for
    # web openings; Bredt's gross J assumes an unbroken cell.
    J = section.J if J_eff is None else J_eff
    ry = math.sqrt(section.Iy / Ag)
    Mp = Fy * Zx
    My = Fy * Sx

    lam_p_f = 1.12 * math.sqrt(E / Fy)      # B4.1b case 12, HSS flange
    lam_r_f = 1.40 * math.sqrt(E / Fy)
    lam_p_w = 2.42 * math.sqrt(E / Fy)      # B4.1b case 13, HSS web
    lam_r_w = 5.70 * math.sqrt(E / Fy)
    fl_class = _classify(b_t, lam_p_f, lam_r_f) if b_t else COMPACT
    web_class = _classify(h_tw, lam_p_w, lam_r_w) if h_tw else COMPACT

    Lp = 0.13 * E * ry * math.sqrt(J * Ag) / Mp if Mp > 0 else 0.0
    Lr = 2.0 * E * ry * math.sqrt(J * Ag) / (0.7 * Fy * Sx) if Sx > 0 else 0.0

    note = ''
    if Lb <= 1e-9:
        Mn, governing = Mp, 'plastification (F7.1), compression flange continuously braced'
        note = ('Lb = 0 was taken as a continuously braced compression flange. Enter '
                'the real Lb if it is not -- though for a closed cell Lr is usually '
                'far longer than the beam, so LTB rarely governs either way.')
    elif Lb <= Lp:
        Mn, governing = Mp, 'plastification (F7.1), Lb <= Lp'
    elif Lb <= Lr:
        Mn = Cb * (Mp - (Mp - 0.7 * Fy * Sx) * (Lb - Lp) / (Lr - Lp))     # F7.2(b)
        Mn = min(Mn, Mp)
        governing = 'inelastic lateral-torsional buckling (F7.2b)'
    else:
        Mn = min(2.0 * E * Cb * math.sqrt(J * Ag) / (Lb / ry), Mp)        # F7.2(c)
        governing = 'elastic lateral-torsional buckling (F7.2c)'

    if fl_class == NONCOMPACT:
        # F7.2(b) flange local buckling, exact
        Mn_flb = Mp - (Mp - Fy * Sx) * (3.57 * b_t * math.sqrt(Fy / E) - 4.0)
        Mn = min(Mn, max(min(Mn_flb, Mp), My))
        governing += ' + noncompact flange (F7.2b)'
    if fl_class == SLENDER or web_class == SLENDER:
        walls = []
        if fl_class == SLENDER:
            walls.append(f'flange b/t = {b_t:.0f} > {lam_r_f:.0f}')
        if web_class == SLENDER:
            walls.append(f'web h/t = {h_tw:.0f} > {lam_r_w:.0f}')
        Mn = min(Mn, My)
        governing += ' (capped at My, slender wall)'
        note = (note + ' ' if note else '') + (
            'SLENDER BOX WALL: ' + '; '.join(walls) + '. F7 covers compact and '
            'noncompact walls; a slender flange goes to F7.2(c), which needs an '
            'EFFECTIVE section (reduced width) that this module does not compute, '
            'and a slender web falls outside F7 altogether. Mn has been capped at '
            'My = Fy*Sx, which is an UPPER BOUND on the reduced capacity, not a '
            'safe value. Treat the flexural result as indicative only and verify '
            'the walls before relying on it.')

    return FlexureResult(Mn=Mn, Md=code.phi_flexure * Mn, Mp=Mp, My=My,
                         Lp=Lp, Lr=Lr, Lb=Lb, flange_class=fl_class,
                         web_class=web_class, governing=governing, note=note)


def flexural_strength_general(section, Fy, Zx, Lb=0.0, Cb=1.0, code=CIRSOC_301,
                              E=E_STEEL, G=None):
    """Any other drawable section: plastification, plus a CONSERVATIVE
    elastic LTB bound.

    The general elastic LTB moment is

        Mcr = (Cb*pi/Lb) * sqrt(E*Iy*G*J + (pi*E/Lb)^2 * Iy * Cw)

    and this module has no way to compute Cw for an arbitrary drawn
    polygon. Taking Cw = 0 drops the warping term, which can only LOWER
    Mcr -- so the result is a lower bound on the true capacity, which is
    the safe direction to be wrong in. It is stated rather than hidden.

    Without a declared assembly there is no J either, and then LTB cannot
    be evaluated at all: that is reported instead of guessed."""
    if G is None:
        G = E / (2 * (1 + 0.3))
    Sx = section.S
    Mp = Fy * Zx
    My = Fy * Sx
    Mp = min(Mp, 1.5 * My)
    J = getattr(section, 'J', None)

    if Lb <= 1e-9:
        return FlexureResult(
            Mn=Mp, Md=code.phi_flexure * Mp, Mp=Mp, My=My, Lp=0.0, Lr=0.0, Lb=0.0,
            flange_class=UNKNOWN_CLASS, web_class=UNKNOWN_CLASS,
            governing='plastification, compression flange continuously braced',
            note='Lb = 0 was taken as a continuously braced compression flange, so '
                 'lateral-torsional buckling was not evaluated. Local buckling of '
                 'the individual plates is NOT classified for a drawn section -- '
                 'check it separately.')

    if not isinstance(J, (int, float)) or J <= 0:
        return FlexureResult(
            Mn=Mp, Md=code.phi_flexure * Mp, Mp=Mp, My=My, Lp=0.0, Lr=0.0, Lb=Lb,
            flange_class=UNKNOWN_CLASS, web_class=UNKNOWN_CLASS,
            governing='plastification only -- LTB NOT evaluated',
            note=f'Lb = {Lb:.0f} mm was given, but this section reports no torsion '
                 'constant J, so lateral-torsional buckling could not be evaluated '
                 'and Mn is the plastification value alone. For two profiles, '
                 'declare how they are joined ("How the profiles are joined") to '
                 'give the section a J. THIS RESULT IS NOT A COMPLETE FLEXURAL '
                 'CHECK.')

    Mcr = (Cb * math.pi / Lb) * math.sqrt(E * section.Iy * G * J)
    Mn = min(Mcr, Mp)
    return FlexureResult(
        Mn=Mn, Md=code.phi_flexure * Mn, Mp=Mp, My=My, Lp=0.0, Lr=0.0, Lb=Lb,
        flange_class=UNKNOWN_CLASS, web_class=UNKNOWN_CLASS,
        governing='elastic lateral-torsional buckling (general, warping neglected)',
        note='Cw was taken as 0 because it cannot be computed for an arbitrary '
             'drawn section. Dropping the warping term can only lower Mcr, so this '
             'is a LOWER BOUND on the real capacity. Local buckling of the '
             'individual plates is not classified either.')


# ─────────────────────────────────────────────────────────────────────────
# 4. Shear strength -- Chapter G
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class ShearResult:
    Vn: float           # nominal shear strength, N
    Vd: float           # design shear strength phi_v * Vn, N
    Cv: float
    Aw: float
    h_tw: float
    governing: str
    note: str = ''


def web_shear_buckling_coefficient(a, h, h_tw):
    """G.2.6  kv = 5 + 5/(a/h)^2 for a web with transverse stiffeners at
    spacing `a`; kv = 5 when the panel is effectively unstiffened.

    Returns (kv, note). The two escapes back to kv = 5 are both in
    G.2.1(b): a panel longer than 3h, and one longer than [260/(h/tw)]^2
    times h, are too slender in plan for the stiffeners to develop the
    shorter buckling half-wave that the formula assumes.

    This matters more than it looks: kv enters Cv linearly in the elastic
    range, so stiffeners at a/h = 1 double the shear buckling capacity
    against an unstiffened web. Not being able to say they are there cost
    a factor of two."""
    if a is None or a <= 0 or h <= 0:
        return KV_UNSTIFFENED, ''
    ratio = a / h
    limit = (260.0 / h_tw) ** 2 if h_tw > 0 else 0.0
    if ratio > 3.0 or ratio > limit:
        return KV_UNSTIFFENED, (
            f'Stiffener spacing a/h = {ratio:.2f} exceeds the G.2.1(b) limit '
            f'(3.0 and [260/(h/tw)]^2 = {limit:.2f}), so the panel counts as '
            'UNSTIFFENED and kv = 5.')
    kv = 5.0 + 5.0 / ratio ** 2
    return kv, f'kv = {kv:.2f} from stiffeners at a/h = {ratio:.2f} (G.2.6).'


def shear_web_coefficient(h_tw, Fyw, kv=KV_UNSTIFFENED, E=E_STEEL):
    """Cv per G.2.3 / G.2.4 / G.2.5 (unstiffened or stiffened web, rolled
    or built-up doubly/singly symmetric sections and channels)."""
    lim1 = 1.10 * math.sqrt(kv * E / Fyw)
    lim2 = 1.37 * math.sqrt(kv * E / Fyw)
    if h_tw <= lim1:
        return 1.0, 'shear yielding (G.2.3)'
    if h_tw <= lim2:
        return lim1 / h_tw, 'inelastic web shear buckling (G.2.4)'
    return 1.51 * kv * E / (h_tw ** 2 * Fyw), 'elastic web shear buckling (G.2.5)'


def shear_strength(section, Fy, code=CIRSOC_301, kv=KV_UNSTIFFENED, E=E_STEEL):
    """G.2.1  Vn = 0.6 * Fyw * Aw * Cv,  Aw = d * tw.

    Note Aw uses the FULL section depth d, not the clear web height -- that
    is what G.2.2 says for a rolled shape, and it is deliberately not the
    same `Aweb` the elastic stress check uses (which is (d - 2tf)*tw, the
    right area for an average web shear stress). Two different quantities
    for two different purposes; conflating them would overstate Vn."""
    return shear_strength_from_web(section.d * section.tw,                # G.2.2
                                   (section.d - 2 * section.tf) / section.tw,
                                   Fy, code=code, kv=kv, E=E)


def shear_strength_from_web(Aw, h_tw, Fy, code=CIRSOC_301, kv=KV_UNSTIFFENED,
                            E=E_STEEL, extra_note=''):
    """G.2.1  Vn = 0.6 * Fyw * Aw * Cv, given the web area and slenderness.

    Split out from `shear_strength` so a section with no single `tw` --
    a welded box has TWO web plates -- can supply its own Aw and h/tw
    from geometry (`section_plastic.web_properties`) and still go through
    exactly the same code clauses."""
    Cv, governing = shear_web_coefficient(h_tw, Fy, kv, E)
    Vn = 0.6 * Fy * Aw * Cv                                       # G.2.1
    note = extra_note
    if h_tw > 260:
        note = (note + ' ' if note else '') + (
            f'h/tw = {h_tw:.0f} exceeds 260, so kv = 5 for an unstiffened web no '
            'longer applies (G.2.1(b)) -- transverse stiffeners are required and '
            'kv must come from G.2.6.')
    return ShearResult(Vn=Vn, Vd=code.phi_shear * Vn, Cv=Cv, Aw=Aw,
                       h_tw=h_tw, governing=governing, note=note)


# ─────────────────────────────────────────────────────────────────────────
# 5. Stress-level checks -- H.3.3
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class StressCheck:
    fun: float           # required normal stress, MPa
    fuv: float           # required shear stress, MPa
    Fn_normal: float     # phi * Fy
    Fn_shear: float      # 0.6 * phi * Fy
    util_normal: float
    util_shear: float
    von_mises: float     # supplementary, NOT a CIRSOC criterion
    util: float          # governing = max of the two CIRSOC utilisations
    governing: str


def stress_check(fun, fuv, Fy, code=CIRSOC_301):
    """CIRSOC 301 H.3.3 -- non-tubular members under combined torsion,
    shear, flexure and axial load, checked as STRESSES from an elastic
    global and sectional analysis under factored actions:

        (a) H.3.4   fun <= phi * Fy          phi = 0.90
        (b) H.3.5   fuv <= 0.6 * phi * Fy    phi = 0.90

    Note what this is NOT: H.3.3 checks the normal and shear stresses
    SEPARATELY. It contains no von Mises interaction. This tab previously
    reported sqrt(sigma^2 + 3*tau^2)/Fy, which is a reasonable engineering
    check but is not the code criterion, and applied no resistance factor
    at all. Both CIRSOC ratios are returned as the result; the von Mises
    value is still computed and returned alongside, because in a strongly
    combined stress state it can exceed both, and a preliminary check
    should see that rather than have it hidden."""
    Fn_normal = code.phi_normal * Fy                              # H.3.4
    Fn_shear = 0.6 * code.phi_tau * Fy                            # H.3.5
    un = abs(fun) / Fn_normal if Fn_normal > 1e-9 else float('inf')
    uv = abs(fuv) / Fn_shear if Fn_shear > 1e-9 else float('inf')
    vm = math.sqrt(fun ** 2 + 3 * fuv ** 2) / Fy if Fy > 1e-9 else float('inf')
    util = max(un, uv)
    governing = 'normal stress (H.3.4)' if un >= uv else 'shear stress (H.3.5)'
    return StressCheck(fun=abs(fun), fuv=abs(fuv), Fn_normal=Fn_normal,
                       Fn_shear=Fn_shear, util_normal=un, util_shear=uv,
                       von_mises=vm, util=util, governing=governing)


def buckling_stress_check(f_required, Fcr, code=CIRSOC_301):
    """H.3.6 -- buckling limit state: fun or fuv <= phi_c * Fcr, phi_c = 0.85.
    Used for the web-post shear-buckling check, whose Fcr comes from
    elastic plate theory (see analyze_webpost)."""
    cap = code.phi_buckling * Fcr
    return abs(f_required) / cap if cap > 1e-9 else float('inf')


# ─────────────────────────────────────────────────────────────────────────
# 6. Fillet welds -- J.2.2 and Table J.2.5
# ─────────────────────────────────────────────────────────────────────────

def fillet_throat(leg, code=CIRSOC_301):
    """J.2.2(a): the effective throat is the shortest distance from the
    root to the face of the fillet -- 0.707*leg for an equal-leg 45
    degree fillet.

    CIRSOC allows a LARGER throat for submerged-arc welds (the leg itself
    for legs <= 9 mm, theoretical throat + 3 mm above that). That bonus is
    not taken here: it depends on the fabrication process, which this tool
    has no way to know, and ignoring it is conservative."""
    return code.weld_throat_factor * leg


def weld_strength_per_mm(leg, Fexx, n_lines=1, code=CIRSOC_301):
    """Design shear strength of a fillet weld per mm of length, N/mm.

    Table J.2.5 (SOLDADURAS DE FILETE, corte en el área efectiva):
        phi = 0.60, Fnw = 0.60*Fexx, effective area per J.2.2(a)
    so  Rd/length = phi * 0.60 * Fexx * throat."""
    return code.phi_weld * 0.60 * Fexx * fillet_throat(leg, code) * n_lines


def leg_for_shear_flow(q, Fexx, n_lines=1, code=CIRSOC_301):
    """Fillet leg required to carry a longitudinal shear flow q (N/mm),
    before the minimum-size rule of Table J.2.4 is applied."""
    denom = code.phi_weld * 0.60 * Fexx * code.weld_throat_factor * max(n_lines, 1)
    return abs(q) / max(denom, 1e-9)


# Table J.2.4 -- minimum fillet leg by the thickness of the THICKER
# connected part. (thickness_upper_bound_mm, min_leg_mm); the last entry
# covers everything above.
MIN_FILLET_TABLE = ((6.0, 3.0), (13.0, 5.0), (19.0, 6.0), (float('inf'), 8.0))


def min_fillet_leg(t_thicker):
    """Table J.2.4: minimum fillet leg for the thicker connected part.

    CIRSOC's own note on why this exists is worth keeping in view: the
    table 'está basado en experiencias y provee cierto margen respecto de
    las tensiones no calculadas que se originan durante la fabricación,
    manipuleo, transporte y montaje' -- it covers the stresses nobody
    calculates, which is exactly why a strength-only result of 0.3 mm is
    meaningless on its own."""
    for upper, leg in MIN_FILLET_TABLE:
        if t_thicker <= upper:
            return leg
    return MIN_FILLET_TABLE[-1][1]


def max_fillet_leg(t_thinner):
    """J.2.2(b), maximum fillet leg along a material edge:
        t < 6 mm    -> leg <= t
        t >= 6 mm   -> leg <= t - 2 mm
    (the third rule, leg < thickness of the thinner part joined, is
    subsumed by these when `t_thinner` is that part)."""
    if t_thinner < 6.0:
        return t_thinner
    return t_thinner - 2.0


def min_effective_length(leg):
    """J.2.2(b): the effective length of a fillet designed on strength
    must be at least 4x its nominal leg; otherwise the leg that may be
    counted is a quarter of the effective length."""
    return 4.0 * leg


FLANGE_TO_WEB_EXEMPTION = (
    'J.2.2(b): for flange-to-web joints the actual weld size need not exceed what is '
    'required to develop the capacity of the web, and the Table J.2.4 minimums do not '
    'apply. A continuous seam between two built-up pieces is normally this case -- so '
    'treat the minimum below as a fabrication default to confirm, not as a hard floor.')


# ─────────────────────────────────────────────────────────────────────────
# 7. Block shear and compression buckling -- ADDED 2026-09-07 for the Truss
#    tab's gusset plates
# ─────────────────────────────────────────────────────────────────────────
#
# PROVENANCE, AND HOW IT DIFFERS FROM EVERYTHING ABOVE. Read this before
# trusting a number out of this section.
#
# Everything above was transcribed from the CIRSOC 301-2018 document with
# its clause number beside it. The two limit states below were NOT: the
# document was not in hand for them. What they are instead is the ANSI/AISC
# 360 formulation -- which CIRSOC 301 states in its own preface that it
# adopts as its basis (see this module's header) -- with the AISC
# resistance factors.
#
# So: the FORMULAS are standard and stable across editions, and are the
# same equations CIRSOC works from. The RESISTANCE FACTORS are AISC's, and
# have not been checked against the CIRSOC table the way PHI_WELD was.
# PHI_WELD is the cautionary example: CIRSOC uses 0.60 where AISC uses
# 0.75 for the same limit state, a 25% difference, and nothing but reading
# the table would have revealed it. Assume the same could be true here.
#
# `BLOCK_SHEAR_AND_BUCKLING_PROVENANCE` below carries this warning as a
# string so a report can print it rather than leave the reader to guess.
# When the CIRSOC clauses for J4.3 (rotura de bloque) and Chapter E
# (compresion) are checked, replace the two factors and delete this note.

PHI_RUPTURE = 0.75      # AISC 360 J4.3, block shear (rupture limit state).
                        # NOT verified against CIRSOC -- see the note above.
PHI_COMPRESSION = 0.90  # AISC 360 E1, flexural buckling of a compression
                        # member. NOT verified against CIRSOC -- see above.

#: Net-area deduction per bolt hole, mm, added to the nominal bolt diameter:
#: standard metric clearance (+2 mm) plus the damage allowance conventionally
#: taken around a punched or drilled hole (+2 mm). Exposed as a constant
#: because fabrication practice varies and this is a judgement, not a law.
HOLE_ALLOWANCE_MM = 4.0

BLOCK_SHEAR_AND_BUCKLING_PROVENANCE = (
    'Block shear and gusset buckling use the AISC 360 formulation (J4.3 and '
    'E3), which CIRSOC 301-2018 adopts as its basis, with AISC resistance '
    'factors phi=0.75 and phi_c=0.90. Unlike every other check in this app '
    'those two factors have NOT been read off the CIRSOC table. CIRSOC is '
    'known to differ from AISC on at least one factor (fillet welds: 0.60 vs '
    '0.75), so confirm these against the document before using them for '
    'sign-off.')


@dataclass
class BlockShearResult:
    Rn: float            # nominal strength, N
    Rd: float            # design strength, phi * Rn
    governing: str       # which of the two terms controlled
    Agv: float
    Anv: float
    Ant: float
    util: float          # required / design, if a demand was supplied


def block_shear_strength(Agv, Anv, Ant, Fy, Fu, Ubs=1.0, code=CIRSOC_301,
                         required=0.0):
    """AISC 360 J4.3 -- block shear rupture of a connection element:

        Rn = 0.60*Fu*Anv + Ubs*Fu*Ant   <=   0.60*Fy*Agv + Ubs*Fu*Ant

    i.e. shear RUPTURE on the net shear plane, capped by shear YIELDING on
    the gross shear plane, with tension rupture on the net tension plane
    added in both cases. `Ubs` = 1.0 for a uniform tension stress
    distribution (the normal gusset case) and 0.5 where it is non-uniform.

    Areas are mm^2, stresses MPa, result N. See the provenance note above:
    the formula is AISC's and standard; the 0.75 factor has not been checked
    against CIRSOC.
    """
    shear_rupture = 0.60 * Fu * max(Anv, 0.0)
    shear_yield = 0.60 * Fy * max(Agv, 0.0)
    tension = Ubs * Fu * max(Ant, 0.0)
    if shear_rupture <= shear_yield:
        Rn, governing = shear_rupture + tension, 'shear rupture on the net area (J4.3)'
    else:
        Rn, governing = shear_yield + tension, 'shear yielding on the gross area (J4.3)'
    Rd = code.phi_rupture * Rn
    util = (abs(required) / Rd) if Rd > 1e-9 else float('inf')
    return BlockShearResult(Rn=Rn, Rd=Rd, governing=governing, Agv=Agv,
                            Anv=Anv, Ant=Ant, util=util)


@dataclass
class CompressionResult:
    Fe: float            # elastic (Euler) critical stress, MPa
    Fcr: float           # nominal critical stress, MPa
    Pn: float            # nominal strength, N
    Pd: float            # design strength phi_c * Pn, N
    slenderness: float   # K*L/r
    governing: str
    util: float


def compression_critical_stress(KL_over_r, Fy, E=E_STEEL):
    """AISC 360 E3 flexural buckling, returns (Fcr, Fe, which branch).

        Fe = pi^2 E / (KL/r)^2
        KL/r <= 4.71*sqrt(E/Fy)  ->  Fcr = 0.658^(Fy/Fe) * Fy   (inelastic)
        otherwise                ->  Fcr = 0.877 * Fe            (elastic)

    The 4.71 limit is exactly the point where Fy/Fe = 2.25, so the two
    branches meet continuously.
    """
    if KL_over_r <= 1e-9:
        return Fy, float('inf'), 'squash (zero slenderness)'
    Fe = math.pi ** 2 * E / (KL_over_r ** 2)
    if KL_over_r <= 4.71 * math.sqrt(E / Fy):
        return (0.658 ** (Fy / Fe)) * Fy, Fe, 'inelastic buckling (E3-2)'
    return 0.877 * Fe, Fe, 'elastic buckling (E3-3)'


def compression_strength(area_mm2, KL_over_r, Fy, code=CIRSOC_301,
                         E=E_STEEL, required=0.0):
    """AISC 360 E3: Pn = Fcr * Ag, Pd = phi_c * Pn. Areas mm^2, stresses
    MPa, forces N. See the provenance note above regarding phi_c."""
    Fcr, Fe, governing = compression_critical_stress(KL_over_r, Fy, E)
    Pn = Fcr * max(area_mm2, 0.0)
    Pd = code.phi_compression * Pn
    util = (abs(required) / Pd) if Pd > 1e-9 else float('inf')
    return CompressionResult(Fe=Fe, Fcr=Fcr, Pn=Pn, Pd=Pd,
                             slenderness=KL_over_r, governing=governing,
                             util=util)


def net_width(gross_width_mm, n_holes, bolt_d_mm,
              allowance_mm=HOLE_ALLOWANCE_MM):
    """Gross width less `n_holes` hole deductions, mm, never below zero.
    Each deduction is the bolt diameter plus `allowance_mm` (see
    HOLE_ALLOWANCE_MM). A welded connection has n_holes = 0, so net = gross.
    """
    return max(gross_width_mm - n_holes * (bolt_d_mm + allowance_mm), 0.0)
