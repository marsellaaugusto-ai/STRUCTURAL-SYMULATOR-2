"""units.py — the unit convention the interface presents, app-wide.

Every solver in this project computes in SI base units and always will. This
module is a PRESENTATION layer: it converts at the boundary, on the way to a
label or a spreadsheet cell and back from an entry box. No solver imports it,
and nothing here can change an answer -- only how that answer is written down.

    canonical (what the solvers use)        what the user sees
    ------------------------------------    --------------------------------
    length   m                              m, mm, ft, in
    force    N                              kN, kip
    moment   N*m                            kN*m, kip*ft
    line load N/m                           kN/m, kip/ft
    stress   Pa                             MPa, kN/cm^2, ksi
    modulus  Pa                             GPa, MPa, ksi
    area     m^2                            cm^2, mm^2, in^2
    inertia  m^4                            cm^4, mm^4, in^4
    section length m                        cm, mm, in   (a fibre distance)

## What the five conventions actually differ in

Worth stating plainly, because the list of names suggests more variety than
there is: **CIRSOC (Argentina), Eurocode, NBR (Brazil) and CSA (Canada) are all
SI.** They differ in which SI sub-unit is customary -- whether a section area
is quoted in cm^2 or mm^2, whether a modulus is GPa or MPa -- and in their
notation, not in the system of measurement. Only AISC is a different system
(kip, foot, inch, ksi).

So this module is honestly "one US-customary system plus four SI presentation
profiles". Defining them separately is still worth it: an engineer reading a
CIRSOC calculation expects cm^2 and cm^4, and one reading a CSA calculation
expects mm^2 and mm^4, and being handed the other is a real friction even
though no number changed meaning.

The differences between those four codes that DO matter -- resistance factors,
load-combination coefficients, capacity equations -- are not unit conversions
and do not belong here. `cirsoc_301.py` is where that kind of thing lives.
"""

# 'length' is a span or a station along the member; 'section_length' is a
# cross-section dimension (a fibre distance, a flange thickness). They are the
# same physical quantity but never the same unit in practice -- an engineer
# writes a span in metres and a fibre distance in centimetres, and in AISC a
# span in feet and a fibre distance in inches. Giving them one unit would make
# one of the two unreadable.
# 'detail_length' is a third kind of length again: a plate thickness, a weld
# leg, a bolt diameter or a bolt spacing. Every SI code writes these in mm --
# a CIRSOC or Eurocode drawing says an 8 mm plate, never a 0.8 cm one -- while
# the same code writes a fibre distance in cm. They are the same physical
# quantity and never the same unit on a drawing, so they are separate here.
QUANTITIES = ('length', 'section_length', 'detail_length', 'force', 'moment',
              'line_load', 'stress', 'modulus', 'area', 'inertia', 'deflection')


class Unit:
    """One display unit: what to call it, and how to get there from SI base.

    `factor` multiplies a canonical SI value to produce the displayed number,
    so it reads in the direction the interface actually needs. `to_si` is its
    inverse, for values coming back out of an entry box.
    """

    __slots__ = ('label', 'factor')

    def __init__(self, label, factor):
        self.label = label
        self.factor = float(factor)

    def from_si(self, v):
        return v * self.factor

    def to_si(self, v):
        return v / self.factor

    def __repr__(self):
        return f'Unit({self.label!r}, {self.factor!r})'


class UnitSystem:
    """A named set of display units, one per quantity."""

    def __init__(self, key, name, note, **units):
        missing = [q for q in QUANTITIES if q not in units]
        if missing:
            raise ValueError(f'{key}: no unit given for {missing}')
        self.key = key
        self.name = name
        self.note = note
        self._units = {q: units[q] for q in QUANTITIES}

    def __getitem__(self, quantity):
        try:
            return self._units[quantity]
        except KeyError:
            raise KeyError(
                f'{quantity!r} is not a known quantity; expected one of '
                f'{QUANTITIES}') from None

    def label(self, quantity):
        return self[quantity].label

    def from_si(self, quantity, v):
        return self[quantity].from_si(v)

    def to_si(self, quantity, v):
        return self[quantity].to_si(v)

    def __repr__(self):
        return f'UnitSystem({self.key!r})'


# ── conversion constants, written as their definitions ──────────────────────
_KN = 1e-3                      # N     -> kN
_MPA = 1e-6                     # Pa    -> MPa  (= N/mm^2)
_GPA = 1e-9                     # Pa    -> GPa
_KN_CM2 = 1e-7                  # Pa    -> kN/cm^2   (1 kN/cm^2 = 10 MPa)
_CM = 1e2                       # m     -> cm
_CM2 = 1e4                      # m^2   -> cm^2
_MM2 = 1e6                      # m^2   -> mm^2
_CM4 = 1e8                      # m^4   -> cm^4
_MM4 = 1e12                     # m^4   -> mm^4
_MM = 1e3                       # m     -> mm

# US customary, built from the three exact definitions rather than from
# remembered decimal factors. Writing `Pa -> ksi` as a pre-computed constant is
# how this block first shipped with a factor 1000 too large: 145.0 instead of
# 0.145 microstrain-scale, which would have printed every AISC stress a
# thousand times too big. Deriving each one makes that mistake impossible to
# make silently, and the tests pin them against published equivalents.
_M_PER_IN = 0.0254                                  # exact by definition
_M_PER_FT = 0.3048                                  # exact by definition
_N_PER_LBF = 4.4482216152605                        # exact by definition

_PA_PER_PSI = _N_PER_LBF / _M_PER_IN ** 2           # 6894.757... Pa
_N_PER_KIP = _N_PER_LBF * 1e3                       # 4448.22... N

_KIP = 1.0 / _N_PER_KIP         # N     -> kip
_FT = 1.0 / _M_PER_FT           # m     -> ft
_IN = 1.0 / _M_PER_IN           # m     -> in
_KSI = 1.0 / (_PA_PER_PSI * 1e3)  # Pa   -> ksi
_IN2 = _IN ** 2                 # m^2   -> in^2
_IN4 = _IN ** 4                 # m^4   -> in^4


# ── the units themselves, named once ──────────────────────────────
# A Unit is a read-only value object (a label and a factor), so one instance is
# safely shared by every system that displays in it. Naming them here is what
# lets a tab say "I store stress in MPa" without reaching for a private
# constant, and it means each factor is written down exactly once.
M = Unit('m', 1.0)
CM = Unit('cm', _CM)
MM = Unit('mm', _MM)
FT = Unit('ft', _FT)
IN = Unit('in', _IN)

KN = Unit('kN', _KN)
KIP = Unit('kip', _KIP)

KN_M = Unit('kN·m', _KN)                 # moment
KIP_FT = Unit('kip·ft', _KIP * _FT)
KN_PER_M = Unit('kN/m', _KN)             # line load
KIP_PER_FT = Unit('kip/ft', _KIP / _FT)

MPA = Unit('MPa', _MPA)
GPA = Unit('GPa', _GPA)
KN_CM2 = Unit('kN/cm²', _KN_CM2)
KSI = Unit('ksi', _KSI)

CM2 = Unit('cm²', _CM2)
MM2 = Unit('mm²', _MM2)
IN2 = Unit('in²', _IN2)
CM4 = Unit('cm⁴', _CM4)
MM4 = Unit('mm⁴', _MM4)
IN4 = Unit('in⁴', _IN4)


def _si_profile(key, name, note, area, inertia, modulus, section_length,
                stress=None):
    """The four SI conventions differ only in these few sub-units, so they are
    built from one place rather than written out four times -- if they were
    copied, they would drift."""
    return UnitSystem(
        key, name, note,
        length=M,
        section_length=section_length,
        detail_length=MM,
        force=KN,
        moment=KN_M,
        line_load=KN_PER_M,
        stress=stress or MPA,
        modulus=modulus,
        area=area,
        inertia=inertia,
        deflection=MM,
    )


SYSTEMS = {
    'cirsoc': _si_profile(
        'cirsoc', 'CIRSOC (Argentina)',
        'SI. Section properties in cm², cm⁴, as CIRSOC 301 tabulates them.',
        area=CM2, inertia=CM4, modulus=GPA, section_length=CM),

    'eurocode': _si_profile(
        'eurocode', 'Eurocode (EN 1993)',
        'SI. Stresses in MPa (= N/mm²); section properties in cm², cm⁴.',
        area=CM2, inertia=CM4, modulus=GPA, section_length=CM),

    'nbr': _si_profile(
        'nbr', 'NBR 8800 (Brazil)',
        'SI. Same units as Eurocode; the codes differ in factors, not units.',
        area=CM2, inertia=CM4, modulus=GPA, section_length=CM),

    'csa': _si_profile(
        'csa', 'CSA S16 (Canada)',
        'SI. Section properties in mm², mm⁴ and modulus in MPa, as CSA tabulates.',
        area=MM2, inertia=MM4, modulus=MPA, section_length=MM),

    'aisc': UnitSystem(
        'aisc', 'AISC 360 (US customary)',
        'The only non-SI convention here: kip, foot, inch, ksi.',
        length=FT,
        section_length=IN,
        detail_length=IN,
        force=KIP,
        moment=KIP_FT,
        line_load=KIP_PER_FT,
        stress=KSI,
        modulus=KSI,
        area=IN2,
        inertia=IN4,
        deflection=IN),
}

# What the tabs have ALWAYS held in their own state and workbooks: kN, m,
# cm^2, cm^4, GPa -- and allowable stresses in kN/cm^2, which is the one place
# the storage convention differs from the CIRSOC display profile above.
#
# Declaring it as a system of its own is what lets the selector be purely
# cosmetic. Switching conventions converts on the way to a label and back from
# an entry box; it never rewrites stored state. Nothing in a saved model or an
# exported workbook changes meaning because someone chose a different unit
# system, which is the property that makes this feature safe to add late.
STORAGE = UnitSystem(
    'storage', 'app storage', 'Not selectable; the units the tabs store in.',
    length=M,
    section_length=CM,
    detail_length=MM,
    force=KN,
    moment=KN_M,
    line_load=KN_PER_M,
    stress=KN_CM2,
    modulus=GPA,
    area=CM2,
    inertia=CM4,
    deflection=MM,
)

def storage_like(name='app storage', **overrides):
    """A copy of STORAGE with a few quantities held in different units.

    Storage is NOT uniform across the tabs, and pretending otherwise would be
    the one way this presentation layer could corrupt data. The Beam tab has
    always held allowable stresses in kN/cm² and fibre distances in cm; the
    Truss tab holds plate yield in MPa and plate thickness in mm. Both are the
    units their own users have always typed into those boxes, and rewriting
    either would silently reinterpret every model already saved.

    So a tab declares what it actually stores, and the display conversion is
    taken relative to that rather than to a single assumed convention:

        STORAGE_UNITS = units.storage_like(stress=units.MPA,
                                           section_length=units.MM)
    """
    spec = dict(STORAGE._units)
    unknown = [q for q in overrides if q not in QUANTITIES]
    if unknown:
        raise KeyError(f'not known quantities: {unknown}')
    spec.update(overrides)
    return UnitSystem('storage', name,
                      'Not selectable; the units this tab stores in.', **spec)


def reexpress(quantity, value, src, dst):
    """One displayed number, re-written in another convention.

    `src` and `dst` are UnitSystem objects (or keys in SYSTEMS). Going through
    SI in the middle means each system only ever has to know its own
    relationship to SI, never its relationship to the other five.
    """
    src = SYSTEMS[src] if isinstance(src, str) else src
    dst = SYSTEMS[dst] if isinstance(dst, str) else dst
    return dst.from_si(quantity, src.to_si(quantity, value))


DEFAULT_SYSTEM = 'cirsoc'

# Display order for the selector: the app's own convention first, the other
# three SI profiles next, and the one genuinely different system last.
ORDER = ('cirsoc', 'eurocode', 'nbr', 'csa', 'aisc')

_current = SYSTEMS[DEFAULT_SYSTEM]
_listeners = []


def current():
    """The unit system the interface is presenting right now."""
    return _current


def set_current(key):
    """Switch conventions and tell every registered listener to repaint.

    A listener that raises is not allowed to stop the others from being told:
    a half-converted interface, where some panels show kip and others kN, is
    far worse than one panel failing to repaint.
    """
    global _current
    if key not in SYSTEMS:
        raise KeyError(f'unknown unit system {key!r}; expected one of '
                       f'{tuple(SYSTEMS)}')
    _current = SYSTEMS[key]
    for fn in list(_listeners):
        try:
            fn(_current)
        except Exception:
            pass
    return _current


def on_change(fn):
    """Register `fn(system)`, called after every switch. Returns `fn` so it
    can be used as a decorator."""
    if fn not in _listeners:
        _listeners.append(fn)
    return fn


def off_change(fn):
    if fn in _listeners:
        _listeners.remove(fn)


# ── convenience wrappers, so callers do not repeat current() everywhere ─────

def label(quantity):
    return _current.label(quantity)


def from_si(quantity, v):
    return _current.from_si(quantity, v)


def to_si(quantity, v):
    return _current.to_si(quantity, v)


def fmt(quantity, v, digits=2, with_label=True):
    """Format an SI value in the current convention, e.g. '12.50 kN'."""
    shown = _current.from_si(quantity, v)
    text = f'{shown:.{digits}f}'
    return f'{text} {_current.label(quantity)}' if with_label else text


# ── the pair the tabs actually use ──────────────────────────────────────────
# A tab holds its numbers in STORAGE units and shows them in the selected one.
# Going through SI in the middle means each system only has to know its own
# relationship to SI, not to the other five.

def to_display(quantity, stored):
    """A value as the tab stores it -> the number to show the user."""
    return _current.from_si(quantity, STORAGE.to_si(quantity, stored))


def from_display(quantity, shown):
    """A number the user typed -> the value the tab stores."""
    return STORAGE.from_si(quantity, _current.to_si(quantity, shown))


def show(quantity, stored, digits=2, with_label=False):
    """Format a STORED value in the current convention."""
    text = f'{to_display(quantity, stored):.{digits}f}'
    return f'{text} {_current.label(quantity)}' if with_label else text
