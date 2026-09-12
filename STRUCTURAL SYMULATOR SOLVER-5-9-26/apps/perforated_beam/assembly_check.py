"""
assembly_check.py — does the compound section actually hold together?
2026-09-10.

THE PROBLEM THIS SOLVES, and it is the one that prompted the module.
A user built a box girder from two lipped C profiles, declared the
assembly a CLOSED CELL, drew a weld along each lip, and got a report
full of confident numbers: A = 51 084 mm², I = 2.08e10 mm⁴, J = 6.8e9
mm⁴ by Bredt, a shear area over two webs. Every one of those numbers
assumes the two profiles act as a single piece.

They were 1.94 mm apart. The lips faced each other across a gap and
never touched at any point, so the "closed cell" enclosed nothing, the
composite inertia was the inertia of a section that does not exist, and
the tab said none of it. The offsets were 391 mm apart where the
geometry needs 389.06, and nothing on screen could have told them.

This module answers three questions the geometry can answer and the user
should not have to:

  1. DO THE PARTS TOUCH? `part_gaps` measures the real clear distance
     between every pair of parts. A compound section whose parts do not
     touch is not one section, whatever the section-property code
     computes for it.

  2. IS THERE MATERIAL WHERE THE WELD IS? `weld_contact` walks out from
     the weld line's own midpoint along its normal and reports what it
     finds on each side. A weld drawn in empty space joins nothing, and
     -- because `check_welds` computes q from a half-plane clip rather
     than from what is at the line -- it reports a comfortable q = 0
     rather than an error.

  3. HOW THICK ARE THE PARTS IT JOINS? The same walk gives the two
     thicknesses, which is what CIRSOC Table J.2.4's minimum fillet and
     J.2.2(b)'s maximum need. Until now those were fields the user had
     to type, so they were almost always blank and the weld check
     reported "strength only" -- and strength alone on a seam carrying
     no shear flow is 0.0 mm, which is not a weld and is not an answer.

WHY A SEAM CAN CARRY NO SHEAR FLOW AND STILL BE ESSENTIAL. On a section
symmetric about the seam -- two channels toe to toe, the commonest way
to make a box -- each half's centroid sits at the same height as the
whole section's, so Q = 0 and q = V·Q/I = 0 exactly. That is real
mechanics, not a defect: vertical bending genuinely does not push one
half of a symmetric box past the other. The seam is still what makes the
cell closed, and therefore what earns the section its Bredt J and its
torsional stiffness; it carries the Bredt shear flow q = T/(2·A_m)
whenever there IS torsion, and it is sized by the Table J.2.4 minimum
when there is not. `symmetry_note` says so, so that a 0.0 mm answer
stops reading as a broken tool.
"""
import math

from apps.perforated_beam import section_shapes as shapes
from apps.perforated_beam import welded_section_math as wsm
import cirsoc_301 as cirsoc

# A gap this small is a rounding artefact of the polygon arithmetic, not a
# fabrication gap. 0.05 mm is well under any tolerance a fabricator works
# to and well over the 1e-9 noise floor of the clipping.
TOUCH_TOL_MM = 0.05

# How far to walk from a weld line before giving up on finding material,
# as a fraction of the section's larger dimension.
WALK_REACH = 0.55
WALK_STEP_MM = 0.20


def _seg_distance(p, q, r, s):
    """Shortest distance between segments pq and rs."""
    def dot(a, b):
        return a[0] * b[0] + a[1] * b[1]

    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1])

    def point_seg(a, b, c):
        """distance from a to segment bc"""
        d = sub(c, b)
        L2 = dot(d, d)
        if L2 <= 1e-18:
            return math.hypot(a[0] - b[0], a[1] - b[1])
        t = max(0.0, min(1.0, dot(sub(a, b), d) / L2))
        proj = (b[0] + t * d[0], b[1] + t * d[1])
        return math.hypot(a[0] - proj[0], a[1] - proj[1])

    u, v, w = sub(q, p), sub(s, r), sub(p, r)
    a, b, c = dot(u, u), dot(u, v), dot(v, v)
    d, e = dot(u, w), dot(v, w)
    den = a * c - b * b
    if den > 1e-12:
        tc = max(0.0, min(1.0, (b * e - c * d) / den))
        sc = max(0.0, min(1.0, (a * e - b * d) / den))
        p1 = (p[0] + tc * u[0], p[1] + tc * u[1])
        p2 = (r[0] + sc * v[0], r[1] + sc * v[1])
        direct = math.hypot(p1[0] - p2[0], p1[1] - p2[1])
    else:
        direct = float('inf')
    # Endpoint cases are checked unconditionally: the parametric solution
    # above is only the true minimum when both clamps are inactive, and
    # deciding that is fiddlier than just taking the smaller answer.
    return min(direct,
               point_seg(p, r, s), point_seg(q, r, s),
               point_seg(r, p, q), point_seg(s, p, q))


def _loops_of(piece):
    return [piece.outline] + list(piece.holes or ())


def _min_distance(pieces_a, pieces_b):
    best = float('inf')
    for pa in pieces_a:
        for la in _loops_of(pa):
            for i in range(len(la)):
                p, q = la[i], la[(i + 1) % len(la)]
                for pb in pieces_b:
                    for lb in _loops_of(pb):
                        for j in range(len(lb)):
                            r, s = lb[j], lb[(j + 1) % len(lb)]
                            d = _seg_distance(p, q, r, s)
                            if d < best:
                                best = d
                                if best <= 1e-9:
                                    return 0.0
    return best


class PartGap:
    def __init__(self, label_a, label_b, gap):
        self.label_a = label_a
        self.label_b = label_b
        self.gap = gap

    @property
    def touching(self):
        return self.gap <= TOUCH_TOL_MM

    def describe(self):
        if self.touching:
            return f'{self.label_a} and {self.label_b}: in contact'
        return (f'{self.label_a} and {self.label_b}: {self.gap:.2f} mm APART -- '
                'they are not in contact anywhere')


def part_gaps(section):
    """The clear distance between every pair of parts of a compound
    section, in the section's own frame. [] for anything that is not a
    compound of two or more parts."""
    parts = list(getattr(section, 'parts', ()) or ())
    if len(parts) < 2:
        return []
    rendered = []
    for i, part in enumerate(parts):
        label = getattr(part, 'label', None) or f'part {i + 1}'
        rendered.append((label, _pieces_of_part(section, i)))
    out = []
    for i in range(len(rendered)):
        for j in range(i + 1, len(rendered)):
            la, pa = rendered[i]
            lb, pb = rendered[j]
            if not pa or not pb:
                continue
            out.append(PartGap(la, lb, _min_distance(pa, pb)))
    return out


def _pieces_of_part(section, index):
    """One part's polygons, in the same frame `section_pieces` renders the
    whole compound in.

    There is no published way to ask `section_pieces` for a single part,
    so this repeats the one line it uses: the part's own pieces come back
    already centred on the part's centroid, and are translated by
    (dx - cx, dy - cy). The inner centroid is NOT subtracted again -- it
    has already been taken out. Doing it twice puts each part a centroid
    offset from where it really is, and the gap this module measures then
    describes a section nobody drew."""
    parts = list(getattr(section, 'parts', ()) or ())
    part = parts[index]
    cx, cy = section.centroid
    return [p.translated(part.dx - cx, part.dy - cy)
            for p in shapes.section_pieces(part.section)]


class WeldContact:
    """What sits on each side of a weld line, measured from the line."""

    def __init__(self, label, t_positive, t_negative, gap, midpoint):
        self.label = label
        self.t_positive = t_positive     # mm of material on the +normal side
        self.t_negative = t_negative
        self.gap = gap                   # clear distance between the two, mm
        self.midpoint = midpoint

    @property
    def found_both(self):
        return self.t_positive > 0 and self.t_negative > 0

    @property
    def t_thicker(self):
        return max(self.t_positive, self.t_negative)

    @property
    def t_thinner(self):
        return min(self.t_positive, self.t_negative)

    def describe(self):
        if not self.found_both:
            side = 'both sides' if self.t_thicker <= 0 else 'one side'
            return (f'{self.label}: no material on {side} of the line -- this weld '
                    'joins nothing where it is drawn')
        txt = (f'{self.label}: joins {self.t_negative:.1f} mm to {self.t_positive:.1f} mm')
        if self.gap > 2 * WALK_STEP_MM:
            # Measured along the normal in WALK_STEP_MM steps, so it is a
            # flag rather than a dimension; `part_gaps` measures the real
            # clear distance exactly.
            txt += f', across a gap of about {self.gap:.1f} mm'
        return txt


def weld_contact(section, weld, label=None):
    """Walk out from the weld's midpoint along its normal and report the
    material found on each side.

    This is what turns a blank `t_thicker`/`t_thinner` -- which is what
    the fields almost always are, because they must be typed by hand --
    into a Table J.2.4 minimum the report can actually quote."""
    pieces = shapes.section_pieces(section)
    ext = shapes.section_extents(pieces)
    if ext is None:
        return None
    reach = WALK_REACH * max(ext[2] - ext[0], ext[3] - ext[1])
    # Weld lines are stored in the PLACED frame; `section_pieces` renders
    # in the CENTROID frame. `section_welds` bridges the two by
    # subtracting the centroid, and so must this walk -- otherwise it
    # samples a point a centroid-offset away from the joint and reports
    # empty space beside a perfectly good weld.
    cx, cy = (0.0, 0.0)
    try:
        cx, cy = section.centroid
    except Exception:
        pass
    mx = 0.5 * (weld.p1[0] + weld.p2[0]) - cx
    my = 0.5 * (weld.p1[1] + weld.p2[1]) - cy
    nx, ny = weld.normal

    def run_along(sign):
        """(start_distance, thickness) of the first solid run out this
        way, or (None, 0.0).

        The walk starts ONE STEP OUT, never at d = 0. A weld line sits on
        the interface it welds, so the sample exactly on it is on a
        polygon boundary and `point_is_solid` may answer either way; when
        it answers True the run ends at the next sample and the joint is
        reported as holding a 0.2 mm plate. Skipping the ambiguous point
        costs one step of accuracy on a 10 mm plate and removes the
        failure mode entirely."""
        start = None
        d = WALK_STEP_MM
        while d <= reach:
            x = mx + sign * nx * d
            y = my + sign * ny * d
            solid = shapes.point_is_solid(pieces, x, y)
            if solid and start is None:
                start = d
            elif not solid and start is not None:
                return start, d - start
            d += WALK_STEP_MM
        if start is not None:
            return start, reach - start
        return None, 0.0

    s_pos, t_pos = run_along(+1.0)
    s_neg, t_neg = run_along(-1.0)
    gap = 0.0
    if s_pos is not None and s_neg is not None:
        gap = s_pos + s_neg
    return WeldContact(label or weld.label or 'weld', t_pos, t_neg, gap, (mx, my))


def symmetry_note(section, weld, q=0.0):
    """Why this weld carries (almost) no longitudinal shear flow.

    The CALLER decides when to ask -- `check_welds` asks whenever the
    strength requirement is negligible, which is the situation a reader
    would otherwise take for a broken tool. This function only explains;
    it does not re-litigate the threshold."""
    dx = weld.p2[0] - weld.p1[0]
    dy = weld.p2[1] - weld.p1[1]
    if abs(dx) <= abs(dy) * 1e-3:
        return ('this q is not a mistake. The line is vertical and the section is '
                'symmetric about it, so each half has its centroid at the same '
                'height as the whole and V*Q/I vanishes: vertical bending does not '
                'push one half of a symmetric box past the other. The seam is still '
                'what CLOSES the cell -- it is what earns this section its Bredt J '
                'and its torsional stiffness -- and it carries the Bredt shear flow '
                'q = T/(2*Am) whenever there is torsion. Size it by the Table J.2.4 '
                'minimum, and check it again against any torsion you apply.')
    return ('this q is not a mistake: the material this line holds has its centroid '
            'at the height of the section centroid, so V*Q/I vanishes. Size the '
            'joint by the Table J.2.4 minimum, and check it again if the beam is '
            'ever loaded in torsion.')


def audit(section, detail=None):
    """Everything this module can say about one section, as report lines.

    Empty when there is nothing to say, so a healthy section adds no
    noise to the report."""
    lines = []
    gaps = [g for g in part_gaps(section) if not g.touching]
    if gaps:
        lines.append('*** THE PARTS OF THIS SECTION DO NOT TOUCH ***')
        for g in gaps:
            lines.append(f'    {g.describe()}')
        lines.append('    Every section property above -- A, I, S, and the shear area --')
        lines.append('    was computed as if they act as one piece. They cannot: nothing')
        lines.append('    transfers force between them. Correct the profile offsets so')
        lines.append('    the parts meet, or model them as separate members.')
        if detail is not None and getattr(detail, 'is_closed', False):
            lines.append('    The assembly is declared a CLOSED CELL, so J and the torsional')
            lines.append('    shear stress were taken from Bredt around a cell that is open.')
            lines.append('    Those two results are not merely approximate here; they are wrong.')

    welds = list(getattr(section, 'welds', ()) or [])
    empty = []
    for i, w in enumerate(welds, 1):
        c = weld_contact(section, w, label=w.label or f'W{i}')
        if c is not None and not c.found_both:
            empty.append(c)
    if empty:
        lines.append('')
        lines.append('Weld lines with nothing to join:')
        for c in empty:
            lines.append(f'    {c.describe()}')
    return lines


# ─────────────────────────────────────────────────────────────────────────
# Where the seam actually is
# ─────────────────────────────────────────────────────────────────────────

# A contact run shorter than this is a corner touching a corner, not a
# seam anybody would weld along.
MIN_SEAM_MM = 5.0


def _overlap_along(p, q, r, s, tol):
    """The stretch of segment pq that segment rs lies against, or None.

    Two plates are in contact where their faces are PARALLEL and within
    `tol` of each other, over some length. That is three conditions, and
    all three have to hold: near-parallel, near-touching, and overlapping
    when projected onto the shared direction. Checking only the distance
    would call a corner grazing a face a seam."""
    ux, uy = q[0] - p[0], q[1] - p[1]
    vx, vy = s[0] - r[0], s[1] - r[1]
    lu = math.hypot(ux, uy)
    lv = math.hypot(vx, vy)
    if lu < tol or lv < tol:
        return None
    ux, uy = ux / lu, uy / lu
    vx, vy = vx / lv, vy / lv
    if abs(ux * vy - uy * vx) > 1e-3:            # not parallel
        return None
    # perpendicular offset of rs from pq's line
    if abs((r[0] - p[0]) * (-uy) + (r[1] - p[1]) * ux) > tol:
        return None
    ta = 0.0
    tb = lu
    tc = (r[0] - p[0]) * ux + (r[1] - p[1]) * uy
    td = (s[0] - p[0]) * ux + (s[1] - p[1]) * uy
    lo = max(ta, min(tc, td))
    hi = min(tb, max(tc, td))
    if hi - lo < MIN_SEAM_MM:
        return None
    return ((p[0] + ux * lo, p[1] + uy * lo),
            (p[0] + ux * hi, p[1] + uy * hi))


def contact_runs(section, tol=TOUCH_TOL_MM):
    """Every stretch where two different parts touch, as segments in the
    section's own centroid frame.

    This is the answer to "where do the welds go": a seam is exactly the
    line along which two pieces are in contact, and the geometry knows
    where that is."""
    parts = list(getattr(section, 'parts', ()) or ())
    if len(parts) < 2:
        return []
    rendered = [_pieces_of_part(section, i) for i in range(len(parts))]
    out = []
    for i in range(len(rendered)):
        for j in range(i + 1, len(rendered)):
            for pa in rendered[i]:
                for la in _loops_of(pa):
                    for m in range(len(la)):
                        p, q = la[m], la[(m + 1) % len(la)]
                        for pb in rendered[j]:
                            for lb in _loops_of(pb):
                                for n in range(len(lb)):
                                    r, s = lb[n], lb[(n + 1) % len(lb)]
                                    seg = _overlap_along(p, q, r, s, tol)
                                    if seg is not None:
                                        out.append(seg)
    return _merge_collinear(out)


def _merge_collinear(segments, tol=TOUCH_TOL_MM):
    """Collapse duplicates and touching collinear pieces.

    Two profiles meeting along one face produce the same run once per
    edge pair that sees it, so without this a single seam comes back
    three or four times and the tab offers to weld it three or four
    times."""
    out = []
    for seg in segments:
        placed = False
        for k, have in enumerate(out):
            merged = _join(have, seg, tol)
            if merged is not None:
                out[k] = merged
                placed = True
                break
        if not placed:
            out.append(seg)
    return out


def _join(a, b, tol):
    (ax1, ay1), (ax2, ay2) = a
    ux, uy = ax2 - ax1, ay2 - ay1
    L = math.hypot(ux, uy)
    if L < 1e-9:
        return None
    ux, uy = ux / L, uy / L
    ts = []
    for pt in (b[0], b[1]):
        if abs((pt[0] - ax1) * (-uy) + (pt[1] - ay1) * ux) > tol:
            return None                       # not on the same line
        ts.append((pt[0] - ax1) * ux + (pt[1] - ay1) * uy)
    lo, hi = min(0.0, min(ts)), max(L, max(ts))
    if min(ts) > L + tol or max(ts) < -tol:
        return None                           # disjoint, keep them apart
    return ((ax1 + ux * lo, ay1 + uy * lo), (ax1 + ux * hi, ay1 + uy * hi))


def seam_welds(section, label_prefix='SEAM'):
    """Weld lines along every contact run, in the PLACED frame the
    section stores welds in.

    `contact_runs` works in the centroid frame that `section_pieces`
    renders; `WeldLine.p1/p2` are read in the placed frame. The centroid
    is added back here, once, so callers never have to think about it --
    getting this backwards puts every generated weld a centroid-offset
    from the seam it was generated for, and every one of them then
    reports a comfortable q = 0."""
    cx, cy = getattr(section, 'centroid', (0.0, 0.0))
    out = []
    for i, ((x1, y1), (x2, y2)) in enumerate(contact_runs(section), 1):
        out.append(wsm.WeldLine(p1=(x1 + cx, y1 + cy), p2=(x2 + cx, y2 + cy),
                                label=f'{label_prefix}{i}'))
    return out
