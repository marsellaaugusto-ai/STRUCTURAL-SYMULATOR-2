"""
load_combinations.py — factored load combinations, 2026-09-10.

THE PROBLEM THIS SOLVES. Every check in this tab compared the loads AS
ENTERED against a design capacity, and the report said so:

    "Demands come from the loads as entered -- it remains your
     responsibility that they are FACTORED actions per CIRSOC 101/102."

That is honest, but it is also the single largest reason this tab and a
hand-written report of the same beam disagree. On the reference report
for the 50.4 m box girder the factored demand is 1.44x the service
demand, so every utilisation the tab printed was 44% low against a
document that had applied 1.2D + 1.6L. Two correct calculations of two
different things read as a bug in one of them.

WHAT A COMBINATION IS HERE. Two numbers and a flag:

  * a factor per load case (D, L), applied to the loads themselves;
  * whether the result is checked against phi*Rn (LRFD) or Rn/Omega
    (ASD).

The second is why `util_ratio` exists rather than a second set of
capacity code. Every check in this app has the form

    demand <= phi * Rn          (LRFD)

and its ASD counterpart is, by the construction of AISC 360 / CIRSOC 301
itself,

    demand <= Rn / Omega        (ASD)

so the ASD utilisation is the LRFD-form utilisation multiplied by
phi*Omega. This is an identity, not an approximation: the code's own
calibration fixes Omega = 1.5/phi, and the paired values it publishes
(phi = 0.90 with Omega = 1.67, phi = 0.60 with Omega = 2.50) reproduce
1.5 to within the rounding in the table. Scaling one number is therefore
exactly equivalent to re-deriving every capacity in ASD form, and it
cannot drift out of step with the LRFD path the way a parallel
implementation would.

CLASSIFICATION IS THE USER'S, NOT A GUESS. A load carries a `case`, and
nothing in this module infers one. An unclassified load defaults to 'L',
which takes the LARGER LRFD factor (1.6 against 1.2) -- so a beam whose
loads nobody has classified is over-factored rather than under-factored,
and the report says which loads were treated as what.

WHAT THIS IS NOT. It is not the full CIRSOC 101 combination set: there
is no W, E, S, R or temperature case, no 0.5L companion terms, and no
pattern loading of the live load on a continuous beam. Those matter, and
a beam whose design is decided by wind or by pattern live load is not
finished by this module. What is here is the pair a building-frame beam
is usually sized by, and the pair the reference report used.
"""
import copy

import cirsoc_301 as cirsoc

# The load cases this module understands. Kept deliberately short: an
# unrecognised case is a silent mis-factoring, so the UI offers exactly
# these and `factor_for` refuses anything else.
CASE_D = 'D'
CASE_L = 'L'
CASES = (CASE_D, CASE_L)
CASE_LABELS = {CASE_D: 'D (permanent)', CASE_L: 'L (variable / live)'}
DEFAULT_CASE = CASE_L

# phi * Omega for the strength limit states this tab checks. CIRSOC 301
# pairs phi = 0.90 with Omega = 1.67 for flexure (F.1), shear (G.1.1) and
# the normal/shear stress checks of H.3.4 and H.3.5, which is every check
# an ASD utilisation is reported for here.
OMEGA_B = 1.67
ASD_UTIL_RATIO = cirsoc.PHI_FLEXURE * OMEGA_B      # 1.503


class LoadCombination:
    """One combination: what multiplies each case, and how the result is
    compared with capacity."""

    def __init__(self, key, label, factors, asd=False, note=''):
        self.key = key
        self.label = label
        self.factors = dict(factors)
        self.asd = asd
        self.note = note

    @property
    def util_ratio(self):
        """Multiply an LRFD-form utilisation by this to get the one this
        combination actually reports. 1.0 for LRFD; phi*Omega for ASD."""
        return ASD_UTIL_RATIO if self.asd else 1.0

    @property
    def is_factored(self):
        return any(abs(f - 1.0) > 1e-9 for f in self.factors.values())

    def factor_for(self, case):
        if case not in CASES:
            case = DEFAULT_CASE
        return self.factors.get(case, 1.0)

    def describe(self):
        bits = [self.label]
        if self.asd:
            bits.append(f'capacity compared as Rn/Omega with Omega={OMEGA_B:g} '
                        f'(utilisations scaled by phi*Omega = {ASD_UTIL_RATIO:.3f})')
        if self.note:
            bits.append(self.note)
        return '; '.join(bits)

    def __repr__(self):
        return f'<LoadCombination {self.key!r}>'


AS_ENTERED = LoadCombination(
    'as_entered', 'As entered (no factors applied)', {CASE_D: 1.0, CASE_L: 1.0},
    note='the loads are used exactly as typed; it remains yours to confirm they '
         'are already the factored actions')
LRFD_1 = LoadCombination(
    'lrfd_12d16l', 'LRFD  U = 1.2D + 1.6L', {CASE_D: 1.2, CASE_L: 1.6})
LRFD_2 = LoadCombination(
    'lrfd_14d', 'LRFD  U = 1.4D', {CASE_D: 1.4, CASE_L: 0.0},
    note='governs only when the permanent load dominates')
ASD_1 = LoadCombination(
    'asd_dl', 'ASD  U = D + L', {CASE_D: 1.0, CASE_L: 1.0}, asd=True)

COMBINATIONS = (AS_ENTERED, LRFD_1, LRFD_2, ASD_1)
BY_KEY = {c.key: c for c in COMBINATIONS}
BY_LABEL = {c.label: c for c in COMBINATIONS}
DEFAULT = AS_ENTERED


def combination(key_or_label, default=None):
    """Look one up by key or by the label the UI shows. Unknown names fall
    back rather than raising: a stale key in a saved workbook must not stop
    the beam from being analysed."""
    if isinstance(key_or_label, LoadCombination):
        return key_or_label
    name = str(key_or_label or '')
    return BY_KEY.get(name) or BY_LABEL.get(name) or (default or DEFAULT)


def _case_of(load):
    return getattr(load, 'case', DEFAULT_CASE) or DEFAULT_CASE


def apply(beam, combo):
    """`beam` with every load multiplied by its case factor.

    A COPY is returned, always -- including for AS_ENTERED. The caller
    holds the user's model, and a combination that scaled it in place
    would compound on the next press of Analyze: two runs of 1.2D + 1.6L
    would give 1.44D + 2.56L, and nothing on screen would say so.

    The section, supports and openings are shared with the original
    rather than deep-copied: they are not touched here, and a drawn
    profile can be a large object to duplicate 28 times over."""
    combo = combination(combo)
    out = copy.copy(beam)
    for attr, fields in (('point_loads', ('P',)),
                         ('dist_loads', ('w1', 'w2')),
                         ('point_moments', ('M',)),
                         ('point_torques', ('T',)),
                         ('dist_torques', ('t1', 't2'))):
        src = list(getattr(beam, attr, ()) or ())
        scaled = []
        for load in src:
            f = combo.factor_for(_case_of(load))
            new = copy.copy(load)
            for name in fields:
                setattr(new, name, getattr(load, name) * f)
            scaled.append(new)
        setattr(out, attr, scaled)
    return out


def summarise(beam, combo):
    """The lines the report prints about how the demands were formed."""
    combo = combination(combo)
    lines = [f'Load combination: {combo.describe()}']
    if not combo.is_factored and not combo.asd:
        return lines
    tally = {}
    for attr in ('point_loads', 'dist_loads', 'point_moments',
                 'point_torques', 'dist_torques'):
        for load in getattr(beam, attr, ()) or ():
            case = _case_of(load)
            tally[case] = tally.get(case, 0) + 1
    if tally:
        parts = [f'{n} as {CASE_LABELS.get(c, c)} x{combo.factor_for(c):g}'
                 for c, n in sorted(tally.items())]
        lines.append('    ' + '; '.join(parts))
    if tally.get(CASE_D) is None and combo.is_factored:
        lines.append('    NOTE: no load is classified permanent (D). Every load took the '
                     f'{CASE_L} factor, which is the larger one -- classify them in the '
                     'Loads panel if that is not what you meant.')
    return lines
