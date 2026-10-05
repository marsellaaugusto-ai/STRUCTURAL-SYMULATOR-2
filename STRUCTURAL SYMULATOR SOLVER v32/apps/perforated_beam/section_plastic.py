"""
section_plastic.py — plastic modulus and web geometry for ANY drawable
section, added 2026-09-09.

WHY THIS EXISTS. `cirsoc_301.flexural_strength` needs `Zx` to form
Mp = Fy*Zx, and only `RolledSection` carried a `Zpl`. So `member_check`
declined outright for a channel, a drawn profile or a welded box:

    if not isinstance(sec, RolledSection):
        return None

That one guard removed the ENTIRE Chapter F/G member check -- gross
flexure, global shear and lateral-torsional buckling -- for every
built-up section the tab can otherwise model completely. A user drawing
the section this tab exists for got net-section and Vierendeel results
and a silent blank where the member check should be.

The observation that removes it is the same one `general_net_section`
rests on: once a section can report its own polygons, every one of these
quantities is an integral over that geometry.

PLASTIC NEUTRAL AXIS. Not the elastic centroid. It is the horizontal line
that splits the section into EQUAL AREAS, found here by bisection on
"area above the cut" -- a monotone function of the cut height, so
bisection cannot land on the wrong root. Then

    Zx = A_top * |y_top - y_pna| + A_bot * |y_pna - y_bot|

with A_top = A_bot = A/2 by construction, and y_top / y_bot the centroids
of the two halves. For a doubly symmetric section the PNA coincides with
the elastic centroid; for the lipped-C box (whose bottom lip is twice the
top one) it does not, and that difference is exactly what Zx has to
capture.

CROSS-CHECKED, not merely tested. For a `RolledSection` this generic
route must reproduce the closed-form `Zpl` the class already computes.
Both are the same integral by different methods, so they agree to
floating point or one of them is wrong -- the same discipline
`general_net_section` uses against `net_section_at`.

WEB GEOMETRY. Chapter G needs an area to yield in shear and a slenderness
to buckle at. For a rolled I both come from `tw`; for a welded box
"the web" is TWO plates and no single `tw` exists. `web_properties`
recovers them from the geometry:

  * scan the middle 60% of the depth, where flanges and lips cannot
    intrude, and take the height whose total material width is SMALLEST
    -- that is the web zone by construction;
  * `t_total` is the summed width there (both plates of a box), which is
    the area that yields;
  * `t_min` is the NARROWEST single plate there, which is what buckles.

Summing for area and taking the minimum for slenderness is the
distinction that matters: using the summed 20 mm of a two-plate box as
`tw` would halve h/tw and roughly double Cv, which is unconservative by
a factor of two on shear buckling.

`h` is taken as the FULL depth rather than the clear distance between
flanges. That is conservative (larger h/tw, smaller Cv) and avoids having
to decide, on an arbitrary drawn polygon, which material is "flange" --
a question with no general answer. The rolled path is untouched and still
uses G.2.2's own h = d - 2*tf.
"""
import math

from apps.perforated_beam import section_shapes as shapes
from apps.perforated_beam import general_net_section as gns

# Fraction of the depth scanned when looking for the web zone. Wide enough
# to find the web on any sane section, narrow enough that a flange, a lip
# or a bottom plate cannot be mistaken for one.
WEB_SCAN_BAND = 0.60
WEB_SCAN_STEPS = 61

# Bisection is on a length, so an absolute floor in mm is the honest
# tolerance; 1e-7 mm is far below any geometry this tab models.
PNA_TOL_MM = 1e-7
PNA_MAX_ITER = 200


def _pieces(section):
    pieces = shapes.section_pieces(section)
    if not pieces:
        raise ValueError(
            'This section reports no geometry, so its plastic modulus cannot be '
            'computed. A rolled I/W, channel, drawn profile, or any welded '
            'compound of those will work.')
    return [p for p in pieces if getattr(p, 'kind', 'solid') == 'solid']


def _area_above(pieces, y_cut):
    return gns._clipped_props(pieces, y_cut, True)[0]


def plastic_neutral_axis(section, pieces=None):
    """Height of the equal-area axis, in the section's own centroid frame.

    Bisection, not Newton: the area-above function is monotone but only
    piecewise smooth (its derivative jumps wherever the width changes),
    and a derivative method can stall on those corners."""
    pieces = pieces if pieces is not None else _pieces(section)
    ext = shapes.section_extents(pieces)
    if ext is None:
        raise ValueError('This section has no drawable extent.')
    lo, hi = ext[1], ext[3]
    total = _area_above(pieces, lo)
    if total <= 1e-9:
        raise ValueError('This section encloses no area.')
    half = total / 2.0

    for _ in range(PNA_MAX_ITER):
        if hi - lo <= PNA_TOL_MM:
            break
        mid = 0.5 * (lo + hi)
        if _area_above(pieces, mid) > half:
            lo = mid          # still too much above: move the cut up
        else:
            hi = mid
    return 0.5 * (lo + hi)


def plastic_modulus(section):
    """Zx about the horizontal plastic neutral axis, mm^3.

    Prefers a section's own closed-form `Zpl` when it has one, so the
    rolled path keeps its exact value and this module is only consulted
    for the shapes that had nothing."""
    own = getattr(section, 'Zpl', None)
    if isinstance(own, (int, float)) and own > 0:
        return float(own)
    return plastic_modulus_from_geometry(section)


def plastic_modulus_from_geometry(section):
    """Zx computed from the polygons, ignoring any `Zpl` the section
    carries. Exposed separately so the cross-check against the rolled
    closed form can call THIS rather than being handed the answer."""
    pieces = _pieces(section)
    y_pna = plastic_neutral_axis(section, pieces)
    A_top, y_top, _ = gns._clipped_props(pieces, y_pna, True)
    A_bot, y_bot, _ = gns._clipped_props(pieces, y_pna, False)
    if A_top <= 1e-9 or A_bot <= 1e-9:
        raise ValueError('The plastic neutral axis fell outside the material; '
                         'the section geometry is degenerate.')
    return A_top * abs(y_top - y_pna) + A_bot * abs(y_pna - y_bot)


# ─────────────────────────────────────────────────────────────────────────
# Web geometry for Chapter G
# ─────────────────────────────────────────────────────────────────────────

def _crossings(poly, y):
    """x-coordinates where the horizontal line y crosses a closed polygon.

    Half-open edge test (y1 <= y < y2): a vertex exactly on the line is
    counted once, not twice, so the crossings still pair up correctly
    into inside/outside intervals."""
    xs = []
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 <= y < y2) or (y2 <= y < y1):
            xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    xs.sort()
    return xs


def _intervals(poly, y):
    xs = _crossings(poly, y)
    return [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]


def _union(ivs):
    out = []
    for a, b in sorted(ivs):
        if out and a <= out[-1][1] + 1e-12:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _subtract(base, cuts):
    """base intervals minus cut intervals."""
    out = list(base)
    for ca, cb in cuts:
        nxt = []
        for a, b in out:
            if cb <= a or ca >= b:
                nxt.append((a, b))
                continue
            if a < ca:
                nxt.append((a, ca))
            if cb < b:
                nxt.append((cb, b))
        out = nxt
    return out


def material_runs_at(section, y, pieces=None):
    """[(x1, x2), ...] of solid material along the horizontal line y.

    One entry per separate plate, which is what lets a two-web box be
    told apart from a single web of twice the thickness -- they have the
    same area and very different buckling slenderness."""
    pieces = pieces if pieces is not None else _pieces(section)
    runs = []
    for p in pieces:
        solid = _intervals(p.outline, y)
        for h in p.holes:
            solid = _subtract(solid, _intervals(h, y))
        runs.extend(solid)
    return [(a, b) for a, b in _union(runs) if b - a > 1e-9]


class WebProperties:
    """What Chapter G needs from a section that has no single `tw`."""

    def __init__(self, Aw, h, t_total, t_min, n_webs, y_scan, note=''):
        self.Aw = Aw
        self.h = h
        self.t_total = t_total
        self.t_min = t_min
        self.n_webs = n_webs
        self.y_scan = y_scan
        self.note = note

    @property
    def h_tw(self):
        return self.h / self.t_min if self.t_min > 1e-9 else float('inf')

    def describe(self):
        webs = f'{self.n_webs} web' + ('s' if self.n_webs != 1 else '')
        return (f'{webs} totalling {self.t_total:.1f} mm '
                f'(thinnest {self.t_min:.1f} mm); Aw = {self.Aw:,.0f} mm^2, '
                f'h/tw = {self.h_tw:.0f}')


def web_properties(section):
    """Recover Aw and the web slenderness from the section's geometry.

    See the module docstring for why the total width sets the area and
    the narrowest single plate sets the slenderness."""
    pieces = _pieces(section)
    ext = shapes.section_extents(pieces)
    if ext is None:
        raise ValueError('This section has no drawable extent.')
    y0, y1 = ext[1], ext[3]
    depth = y1 - y0
    if depth <= 1e-9:
        raise ValueError('This section has zero depth.')

    mid = 0.5 * (y0 + y1)
    band = WEB_SCAN_BAND * depth / 2.0
    best = None
    for i in range(WEB_SCAN_STEPS):
        y = mid - band + 2.0 * band * i / (WEB_SCAN_STEPS - 1)
        runs = material_runs_at(section, y, pieces)
        if not runs:
            continue
        total = sum(b - a for a, b in runs)
        if best is None or total < best[0]:
            best = (total, runs, y)
    if best is None:
        raise ValueError('No material found across the middle of this section, so '
                         'its web cannot be identified.')

    t_total, runs, y_scan = best
    t_min = min(b - a for a, b in runs)
    note = ''
    if len(runs) > 1:
        note = (f'{len(runs)} separate web plates were found. Their thicknesses are '
                f'SUMMED for the shear area and the THINNEST is used for h/tw, '
                f'because each plate buckles on its own.')
    return WebProperties(Aw=depth * t_total, h=depth, t_total=t_total,
                         t_min=t_min, n_webs=len(runs), y_scan=y_scan, note=note)


class FlangeProperties:
    """The compression-flange plate of a box, recovered from geometry.

    For a box, B4.1b case 12 measures b as the CLEAR width between the
    webs, not the overall width -- the corners are restrained by the webs
    and do not participate in the plate's buckling."""

    def __init__(self, b_clear, t_flange, width_overall, note=''):
        self.b_clear = b_clear
        self.t_flange = t_flange
        self.width_overall = width_overall
        self.note = note

    @property
    def b_t(self):
        return self.b_clear / self.t_flange if self.t_flange > 1e-9 else float('inf')


def flange_properties(section, at_top=True):
    """Compression-flange plate of a box section, by scanning inward from
    the extreme fibre until the material width collapses to the webs.

    The scan is what makes this work on a drawn polygon: the flange is
    "the run of material at the extreme fibre", and its thickness is how
    far that run persists before the section narrows to its webs. No
    assumption about which points the user meant as a flange."""
    pieces = _pieces(section)
    ext = shapes.section_extents(pieces)
    if ext is None:
        raise ValueError('This section has no drawable extent.')
    y0, y1 = ext[1], ext[3]
    depth = y1 - y0
    web = web_properties(section)

    edge = y1 if at_top else y0
    inward = -1.0 if at_top else 1.0
    eps = depth * 1e-4

    runs = material_runs_at(section, edge + inward * eps, pieces)
    if not runs:
        raise ValueError('No material at the extreme fibre.')
    width0 = sum(b - a for a, b in runs)
    overall = max(b for _a, b in runs) - min(a for a, _b in runs)

    # Walk in until the section narrows appreciably: the flange has ended
    # and only the webs remain. Half-way between the two widths is a
    # robust threshold for a plate that ends abruptly.
    threshold = 0.5 * (width0 + web.t_total)

    def wide_at(depth_in):
        r = material_runs_at(section, edge + inward * depth_in, pieces)
        return (sum(b - a for a, b in r) if r else 0.0) >= threshold

    # Coarse scan to bracket the step, then bisect it. Reading the
    # thickness straight off the scan grid costs a whole step -- 2.25 mm
    # on an 1800 mm section -- and this number is compared against a
    # slenderness limit, so grid error goes straight into the verdict.
    steps = 200
    limit = depth * 0.5
    lo = 0.0
    hi = limit
    for i in range(1, steps + 1):
        probe = limit * i / steps
        if not wide_at(probe):
            lo, hi = limit * (i - 1) / steps, probe
            break
    else:
        return FlangeProperties(
            b_clear=max(overall - 2.0 * web.t_min, 0.0), t_flange=depth,
            width_overall=overall,
            note='No distinct flange plate was found -- the section does not narrow '
                 'inward from its extreme fibre, so b/t here is not meaningful.')

    for _ in range(80):
        if hi - lo <= PNA_TOL_MM:
            break
        mid = 0.5 * (lo + hi)
        if wide_at(mid):
            lo = mid
        else:
            hi = mid
    t_flange = 0.5 * (lo + hi)

    b_clear = max(overall - 2.0 * web.t_min, 0.0)
    note = ''
    if t_flange >= depth * 0.49:
        note = ('No distinct flange plate was found -- the section does not narrow '
                'inward from its extreme fibre, so b/t here is not meaningful.')
    return FlangeProperties(b_clear=b_clear, t_flange=t_flange,
                            width_overall=overall, note=note)


# ─────────────────────────────────────────────────────────────────────────
# Which Chapter F clause applies
# ─────────────────────────────────────────────────────────────────────────

BOX = 'box'
ROLLED_I = 'rolled_i'
GENERAL = 'general'


def flexural_family(section):
    """Which Chapter F treatment this section belongs to.

    This is a question about TOPOLOGY, not geometry, so it is answered
    from what the user declared rather than guessed from the polygons: a
    box and a pair of stitched channels can have identical outlines and
    utterly different torsional behaviour (see manifesto S4i). An
    `AssemblyDetail` of kind 'closed' is the declaration that the seam is
    continuous, which is what makes F7 the right clause."""
    from apps.perforated_beam import perforated_beam_math as pbm
    if isinstance(section, pbm.RolledSection):
        return ROLLED_I
    detail = getattr(section, 'detail', None)
    if detail is not None and getattr(detail, 'kind', None) == 'closed':
        return BOX
    return GENERAL
