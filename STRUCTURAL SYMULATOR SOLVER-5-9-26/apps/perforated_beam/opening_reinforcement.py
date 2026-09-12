"""
opening_reinforcement.py — doubler rings around web openings, 2026-09-10.

THE PROBLEM THIS SOLVES. When the Vierendeel check fails at an opening,
there are only three ways out: thicken the whole web over the entire
span, shrink the openings, or weld a doubler ring around the few holes
that actually need one. On the 50.4 m box girder the first costs a plate
36-40 mm thick over 50 m of beam and the third costs seven rings, so the
difference is most of the steel in the webs. The tab could report the
failure but not size the fix.

HOW THE RING IS MODELLED. Not by a second set of Vierendeel formulas --
by building the REINFORCED SECTION and running the tab's own opening
check on it. `analyze_opening(beam, opening, section=...)` takes the
statics from the beam as built and the net-section geometry from
whatever section it is handed, so a doubler is evaluated by exactly the
machinery that evaluates everything else. There is no parallel model to
drift out of step.

The ring itself is a plate of thickness `t_an` laid on the OUTER face of
every web, covering the full height of the tee above and below the hole.
Covering the whole tee rather than a radial band around the hole is the
simplification SCI P100 users make by hand, and it is the one the
reference report makes too; it is slightly conservative where the ring
would really be narrower than the tee, and it is stated on every result
rather than buried here.

WHAT IT DOES NOT DO
  * It does not check the ring plate's own local buckling.
  * It does not check the ring's effect on web-post buckling (which the
    added thickness helps, so ignoring it is conservative).
  * The ring is assumed to develop its share of the force through its
    perimeter weld; `ring_weld_leg` sizes that weld for the shear flow,
    but a real detail also has to fit -- a 30 mm doubler on a 10 mm web
    needs a bevel and several passes, and that is a fabrication question
    this module cannot answer.
"""
import math

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import welded_section_math as wsm
from apps.perforated_beam import section_shapes as shapes
from apps.perforated_beam import section_plastic as sp
import cirsoc_301 as cirsoc
from apps.perforated_beam import vierendeel_hand as vh

# Largest doubler this module will search for, mm. Past this the ring is
# thicker than most webs are deep and the answer is a different section,
# not a bigger plate.
MAX_RING_MM = 80.0
RING_TOL_MM = 0.05

# Electrode strength for the ring's perimeter weld, MPa. E70xx, the same
# 482 MPa `design_builtup_connector` already assumes for this app's other
# welds -- kept identical so two welds on one drawing are not sized from
# two different consumables.
WELD_FEXX = 482.0

# Utilisation a ring is sized to reach. Not 1.0: a plate sized to exactly
# 1.000 has no margin for the rounding that fabrication will apply to it
# anyway, and the search returns the first thickness that CLEARS this.
TARGET_UTIL = 1.0


class RingResult:
    """What one opening needs, and why."""

    def __init__(self, opening, util_plain, t_required, util_ringed,
                 tee_height, note='', target=TARGET_UTIL):
        self.opening = opening
        self.util_plain = util_plain
        self.t_required = t_required        # mm; 0.0 = none needed
        self.util_ringed = util_ringed
        self.tee_height = tee_height
        self.note = note
        # The utilisation this ring was sized to reach. Not always
        # TARGET_UTIL: an ASD combination reports phi*Omega times the
        # LRFD-form number, so the sizing target is divided by that
        # ratio, and `needs_ring` has to compare against the same
        # figure the search used or a ring gets sized and then
        # declared unnecessary.
        self.target = target

    @property
    def needs_ring(self):
        """Does this opening fail without a doubler?

        Asked of the PLAIN utilisation, not of `t_required`: when no ring
        up to MAX_RING_MM is enough `t_required` is None, and comparing
        None with a float raised -- on exactly the opening that needs a
        ring most."""
        return self.util_plain > self.target

    @property
    def solved(self):
        """True when a ring of a sane thickness fixes it."""
        return self.t_required is not None

    def describe(self, scale=1.0):
        """One line for the schedule.

        `scale` is the combination's phi*Omega for an ASD run and 1.0 for
        LRFD. The SEARCH runs in LRFD form throughout -- only the target
        moves -- so the stored utilisations are LRFD-form and have to be
        scaled here to agree with every other utilisation on the report.
        Printed unscaled, a ring sized to exactly 1.00 reads as 0.67 and
        the schedule appears to be solving a problem that was not there."""
        where = f'{self.opening.label} at {self.opening.x_center / 1000:.1f} m'
        if not self.solved:
            return (f'{where}: util {self.util_plain * scale:.2f} -- NOT SOLVED by a '
                    f'ring up to {MAX_RING_MM:.0f} mm')
        if not self.needs_ring:
            return f'{where}: util {self.util_plain * scale:.2f} -- no ring needed'
        return (f'{where}: util {self.util_plain * scale:.2f} -> '
                f'{self.util_ringed * scale:.2f} with a {self.t_required:.0f} mm ring')


# ─────────────────────────────────────────────────────────────────────────
# Building the reinforced section
# ─────────────────────────────────────────────────────────────────────────

def _rect(z0, z1, y0, y1, name='ring'):
    return pbm.CustomProfileSection(
        name, [(z0, y0), (z1, y0), (z1, y1), (z0, y1)])


def ring_plates(section, opening, t_an):
    """The doubler plates for one opening, as (z0, z1, y0, y1) rectangles
    in the section's own centroid frame.

    One plate per web per tee: laid on the web's OUTER face, which is the
    face a fabricator can actually reach, and spanning the full height of
    that tee."""
    if t_an <= 0:
        return []
    pieces = shapes.section_pieces(section)
    ext = shapes.section_extents(pieces)
    if ext is None:
        return []
    zmin, ymin, zmax, ymax = ext
    d = ymax - ymin

    ys = [y for _x, y in opening.vertices_local]
    half = (max(ys) - min(ys)) / 2.0
    y_mid = 0.5 * (ymin + ymax)              # openings sit on mid-depth
    y_hole_bot, y_hole_top = y_mid - half, y_mid + half
    if y_hole_bot <= ymin or y_hole_top >= ymax:
        return []                            # no tee left to reinforce

    runs = sp.material_runs_at(section, y_mid, pieces)
    z_mid = 0.5 * (zmin + zmax)

    # WHICH FACES CAN A FABRICATOR REACH? That is what decides the detail,
    # and it is not the same answer for every section.
    #
    #   * Inside a CLOSED CELL nobody can weld, so a box girder's webs take
    #     a plate on their outer face only.
    #   * An open section -- a rolled I, a channel, a plate girder -- has
    #     both faces of its web accessible, and a ring on each is the
    #     normal detail (and the one SCI P100 draws).
    #
    # The single-web case used to fall through the "outer face" branch by
    # accident: a lone central web has its midpoint AT z_mid, so the
    # comparison put one plate on its left and none on its right. Half a
    # ring, silently.
    detail = getattr(section, 'detail', None)
    closed = bool(getattr(detail, 'is_closed', False)) and len(runs) > 1

    out = []
    for a, b in runs:
        if closed:
            # outer face = the one further from the section's own middle
            faces = [(a - t_an, a)] if 0.5 * (a + b) <= z_mid else [(b, b + t_an)]
        else:
            faces = [(a - t_an, a), (b, b + t_an)]
        for z0, z1 in faces:
            out.append((z0, z1, ymin, y_hole_bot))       # bottom tee
            out.append((z0, z1, y_hole_top, ymax))       # top tee
    return out


def reinforced_section(section, opening, t_an):
    """`section` with doubler plates added around `opening`.

    Returned as a CompoundSection so `section_shapes.section_pieces` --
    and therefore `general_net_section` and the whole opening check --
    understand it without knowing anything about rings."""
    rects = ring_plates(section, opening, t_an)
    if not rects:
        return section
    # A ROLLED CATALOG SECTION HAS NO `centroid`, and asking for one raised
    # AttributeError -- so ticking "Size doubler rings" on an IPE, the
    # commonest section this tab is used with, took the whole analysis
    # down. Drawn and compound sections carry a centroid because they are
    # positioned in a drawing frame; a rolled shape is rendered about its
    # own centroid already, so its offset is (0, 0) by construction.
    cx, cy = getattr(section, 'centroid', (0.0, 0.0))

    # FLATTEN, do not nest: CompoundSection rejects a CompoundSection as a
    # part, because an inner weld line would then be given in the inner
    # frame. An already-compound section contributes its parts directly.
    if isinstance(section, wsm.CompoundSection):
        parts = list(section.parts)
        welds = list(getattr(section, 'welds', []) or [])
    else:
        parts = [wsm.PlacedProfile(section, dx=cx, dy=cy, label='base')]
        welds = []

    # FRAME. `section_pieces` renders a part at internal dx as (dx - cx) in
    # the section's centroid frame, and `ring_plates` works in that centroid
    # frame -- so a ring at p goes in at internal dx = p + cx. The new
    # compound's own centroid differs, but it shifts every part equally, so
    # the relative geometry (which is all the opening check reads) holds.
    for i, (z0, z1, y0, y1) in enumerate(rects, 1):
        plate = _rect(-(z1 - z0) / 2.0, (z1 - z0) / 2.0,
                      -(y1 - y0) / 2.0, (y1 - y0) / 2.0, f'ring{i}')
        parts.append(wsm.PlacedProfile(plate,
                                       dx=0.5 * (z0 + z1) + cx,
                                       dy=0.5 * (y0 + y1) + cy,
                                       label=f'ring{i}'))
    return wsm.CompoundSection(parts, welds=welds,
                               detail=getattr(section, 'detail', None))


# ─────────────────────────────────────────────────────────────────────────
# Sizing
# ─────────────────────────────────────────────────────────────────────────

# The two Vierendeel methods a ring can be sized against. 'station' is
# the tab's default nine-station scan of the real net section; 'hand'
# is the rectangular-equivalent closed form the reference report uses
# (see vierendeel_hand.py). They differ by about 4x on a circular
# opening, so a ring schedule that silently answered only one of them
# was the single most confusing output this tab produced.
METHOD_STATION = 'station'
METHOD_HAND = 'hand'


def _util(beam, opening, section=None, n_stations=9, method=METHOD_STATION):
    if method == METHOD_HAND:
        r = vh.check_opening(beam, opening, section=section)
        return r.util if r is not None else 0.0
    rep = pbm.analyze_opening(beam, opening, n_stations=n_stations, section=section)
    g = rep.get('governing')
    if g is None:
        return 0.0
    return max(g.util_top, g.util_bot)


def required_ring(beam, opening, n_stations=9, max_mm=MAX_RING_MM,
                  method=METHOD_STATION, target=TARGET_UTIL):
    """Smallest doubler that brings this opening's Vierendeel check home.

    Bisection, not a formula: the tee's area, its modulus and the net
    inertia all change with the plate, and they do not combine into
    anything worth inverting by hand. Each trial is a full evaluation of
    the reinforced section through the tab's own check."""
    def u(section=None):
        return _util(beam, opening, section, n_stations=n_stations, method=method)

    plain = u()
    pieces = shapes.section_pieces(beam.section)
    ext = shapes.section_extents(pieces)
    ys = [y for _x, y in opening.vertices_local]
    tee = ((ext[3] - ext[1]) - (max(ys) - min(ys))) / 2.0 if ext else 0.0

    if plain <= target:
        return RingResult(opening, plain, 0.0, plain, tee, target=target)

    if not ring_plates(beam.section, opening, 1.0):
        return RingResult(opening, plain, None, plain, tee,
                          note='No tee left to reinforce: the opening reaches the '
                               'section edge, so a ring has nothing to sit on.',
                          target=target)

    hi = max_mm
    if u(reinforced_section(beam.section, opening, hi)) > target:
        return RingResult(opening, plain, None, plain, tee,
                          note=f'Still over-utilised with a {max_mm:.0f} mm ring. '
                               'This opening needs a different diameter, a thicker '
                               'base web, or to be omitted -- not a doubler.',
                          target=target)
    lo = 0.0
    while hi - lo > RING_TOL_MM:
        mid = 0.5 * (lo + hi)
        if u(reinforced_section(beam.section, opening, mid)) > target:
            lo = mid
        else:
            hi = mid
    return RingResult(opening, plain, hi,
                      u(reinforced_section(beam.section, opening, hi)),
                      tee, target=target)


def ring_schedule(beam, n_stations=9, max_mm=MAX_RING_MM,
                  method=METHOD_STATION, target=TARGET_UTIL):
    """Every opening, in order along the span."""
    return [required_ring(beam, op, n_stations, max_mm, method=method, target=target)
            for op in sorted(beam.openings, key=lambda o: o.x_center)]


def group_schedule(results, steps=(0.0,)):
    """Round each required ring UP to the next available plate thickness.

    Eight openings needing eight different plates is not a drawing anyone
    wants to fabricate; the reference report grouped them into two. Pass
    the thicknesses actually stocked and every opening is assigned the
    thinnest one that covers it."""
    stock = sorted(t for t in steps if t > 0)
    out = []
    for r in results:
        if not r.needs_ring or not r.solved:
            out.append((r, r.t_required))
            continue
        pick = next((t for t in stock if t >= r.t_required), None)
        out.append((r, pick if pick is not None else r.t_required))
    return out


class RingWeld:
    """What to actually detail around a ring."""

    def __init__(self, q, leg_strength, leg_min, leg_max, t_web):
        self.q = q                      # shear flow to transfer, N/mm
        self.leg_strength = leg_strength
        self.leg_min = leg_min          # Table J.2.4
        self.leg_max = leg_max          # J.2.2(b)
        self.t_web = t_web

    @property
    def leg(self):
        return max(self.leg_strength, self.leg_min)

    @property
    def governed_by(self):
        return ('the Table J.2.4 minimum' if self.leg_min >= self.leg_strength
                else 'strength')

    def describe(self):
        txt = (f'2 x {self.leg:.0f} mm fillet, continuous around the plate '
               f'(q = {self.q:,.0f} N/mm, governed by {self.governed_by}; '
               f'strength alone would give {self.leg_strength:.1f} mm)')
        if self.leg > self.leg_max > 0:
            txt += (f'. WARNING: J.2.2(b) caps the leg at {self.leg_max:.0f} mm '
                    f'along a {self.t_web:.0f} mm edge -- use a thicker base web '
                    'or a different detail.')
        return txt


def ring_weld_leg(beam, opening, t_an, code=cirsoc.CIRSOC_301, n_stations=9,
                  method=METHOD_STATION):
    """The ring's perimeter fillet, as a RingWeld.

    The ring only helps if the weld can drag it into the tee, so the
    joint carries the longitudinal shear flow q = V*Q/I between the plate
    and the web it doubles. Two lines of weld (one each side of the
    plate's perimeter run) is the normal detail and is what is assumed.

    Strength is rarely what decides this: a doubler picks up very little
    shear flow, and the Table J.2.4 minimum for the plate thickness
    almost always governs. Both are returned."""
    if t_an <= 0:
        return None
    sec_r = reinforced_section(beam.section, opening, t_an)
    # The shear the weld drags into the plate is a STATICS quantity, so
    # it is read from whichever method sized the ring -- the hand method
    # puts a quarter of the global shear in each leg, the station scan
    # splits it by the tees' relative stiffness.
    if method == METHOD_HAND:
        hand = vh.check_opening(beam, opening, section=sec_r)
        if hand is None:
            return 0.0
        V_leg = hand.V_leg
    else:
        rep = pbm.analyze_opening(beam, opening, n_stations=n_stations, section=sec_r)
        g = rep.get('governing')
        if g is None:
            return 0.0
        V_leg = abs(g.V_top)
    rects = ring_plates(beam.section, opening, t_an)
    if not rects:
        return 0.0

    pieces = shapes.section_pieces(beam.section)
    ext = shapes.section_extents(pieces)
    y_mid = 0.5 * (ext[1] + ext[3])
    # First moment of ONE ring plate about the reinforced tee's own
    # centroid: that is the force the weld has to transfer per unit length.
    z0, z1, y0, y1 = rects[0]
    A_ring = abs(z1 - z0) * abs(y1 - y0)
    arm = abs(0.5 * (y0 + y1) - y_mid)
    net = pbm.net_section_general(sec_r, y_mid - 1.0, y_mid + 1.0)
    I_tee = max(net['top'].I + net['bottom'].I, 1e-9)
    q = V_leg * A_ring * arm / I_tee
    t_web = sp.web_properties(beam.section).t_min
    thicker, thinner = max(t_an, t_web), min(t_an, t_web)
    # Two lines: one fillet along each side of the plate's perimeter run.
    return RingWeld(q=q,
                    leg_strength=cirsoc.leg_for_shear_flow(q, WELD_FEXX, n_lines=2,
                                                           code=code),
                    leg_min=cirsoc.min_fillet_leg(thicker),
                    leg_max=cirsoc.max_fillet_leg(thinner),
                    t_web=t_web)
