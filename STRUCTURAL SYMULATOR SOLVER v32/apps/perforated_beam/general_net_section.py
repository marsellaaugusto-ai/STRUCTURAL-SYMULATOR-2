"""
general_net_section.py — web openings in ANY section, not just a rolled I.

perforated_beam_math.net_section_at computes the tees above and below an
opening from a RolledSection's flange/web dimensions directly. That is
exact and fast, and it is why `BeamConfig` refused openings on every other
section type: a channel, a drawn profile or a welded box has no `tf`/`tw`
to put in those formulas.

This module removes that restriction WITHOUT weakening the rolled case.
The observation it rests on: once a section can report its own polygons
(section_shapes.py), "the material above the opening" is just that
geometry clipped by a horizontal half-plane. Clip, integrate, done — for a
drawn profile, a two-profile welded box, or anything else drawable.

The two paths are cross-checked against each other: for a RolledSection
the clipped result must reproduce `net_section_at` to within the tolerance
of nothing at all, because both are computing the same integral by
different routes. `test_general_net_section.py` asserts exactly that, and
it is the reason this module can be trusted on shapes where no closed-form
answer exists to compare against.

FRAME. Like `net_section_at`, y is measured from the section's BOTTOM
FIBRE, so the two are drop-in interchangeable.

WHAT THIS DOES NOT DO. It generalizes the SECTION PROPERTIES at an
opening. It does not make the Vierendeel model itself valid for any
shape: that model assumes the two tees act as chords of a Vierendeel
panel, which is a statement about structural behaviour, not geometry. For
a deep opening in a slender plate girder web, local buckling of the tees
will govern long before the Vierendeel stresses do, and nothing here
checks that -- see the warnings this module attaches.
"""
import math

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import section_shapes as shapes


# practical upper limit on opening depth in the cellular-beam literature;
# past this the tees are too shallow for the Vierendeel model to be the
# governing consideration (local buckling of the tee takes over)
DEEP_OPENING_RATIO = 0.70


def clip_halfplane(pts, y_cut, keep_above):
    """Sutherland-Hodgman clip of a closed polygon by a HORIZONTAL line.

    A half-plane is convex, so this is exact for any simple polygon. A
    concave subject can come back with coincident edges lying along the
    cut; those carry zero area and zero moment, so the integrals taken
    from the result are unaffected -- which is all it is used for."""
    if len(pts) < 3:
        return []
    sign = 1.0 if keep_above else -1.0

    def d(p):
        return sign * (p[1] - y_cut)

    out = []
    n = len(pts)
    for i in range(n):
        cur, nxt = pts[i], pts[(i + 1) % n]
        dc, dn = d(cur), d(nxt)
        if dc >= 0:
            out.append(cur)
        if (dc >= 0) != (dn >= 0):
            denom = dc - dn
            if abs(denom) > 1e-15:
                t = dc / denom
                out.append((cur[0] + t * (nxt[0] - cur[0]),
                            cur[1] + t * (nxt[1] - cur[1])))
    return out


def _clipped_props(pieces, y_cut, keep_above):
    """(A, y_bar, I_about_own_centroid) of everything on one side of the
    cut, holes deducted. y in the pieces' own frame."""
    A = sx = ixx = 0.0
    for p in pieces:
        outer = clip_halfplane(p.outline, y_cut, keep_above)
        if len(outer) >= 3:
            a, s, _, ix, _ = pbm._loop_integrals(outer)
            A += a
            sx += s
            ixx += ix
        for h in p.holes:
            inner = clip_halfplane(h, y_cut, keep_above)
            if len(inner) >= 3:
                a, s, _, ix, _ = pbm._loop_integrals(inner)
                A -= a
                sx -= s
                ixx -= ix
    if A <= 1e-9:
        return 0.0, 0.0, 0.0
    y_bar = sx / A
    return A, y_bar, ixx - A * y_bar ** 2


def section_bottom_offset(section):
    """Distance from the section's centroid down to its bottom fibre --
    the shift between `section_shapes`' centroid frame and the
    bottom-fibre frame `net_section_at` uses."""
    ext = shapes.section_extents(shapes.section_pieces(section))
    if ext is None:
        raise ValueError('This section has no drawable geometry, so an opening '
                          'through it cannot be sized.')
    return -ext[1]


def tees_at(section, y_hole_bot, y_hole_top):
    """Top and bottom tee properties for ANY drawable section.

    Same return shape as `perforated_beam_math.net_section_at`, and the
    same frame (y from the bottom fibre), so callers can use either."""
    pieces = shapes.section_pieces(section)
    ext = shapes.section_extents(pieces)
    if ext is None:
        raise ValueError('This section has no drawable geometry, so an opening '
                          'through it cannot be sized.')
    c_bot = -ext[1]
    d = ext[3] - ext[1]
    yb = y_hole_bot - c_bot                      # into the centroid frame
    yt = y_hole_top - c_bot

    A_t, ybar_t, I_t = _clipped_props(pieces, yt, keep_above=True)
    A_b, ybar_b, I_b = _clipped_props(pieces, yb, keep_above=False)

    warning = None
    valid = True
    if A_t <= 1e-9 or A_b <= 1e-9:
        valid = False
        warning = ('the opening reaches the top or bottom of the section at this '
                   'station -- nothing is left to act as a chord. Reduce the opening '
                   'height, or move it toward mid-depth.')
    else:
        depth_ratio = (y_hole_top - y_hole_bot) / max(d, 1e-9)
        if depth_ratio > DEEP_OPENING_RATIO:
            warning = (f'opening is {depth_ratio:.0%} of the section depth, beyond the '
                       f'~{DEEP_OPENING_RATIO:.0%} the Vierendeel model is normally used '
                       'within. The tees left behind are shallow; local buckling of the '
                       'tee, which this module does not check, is likely to govern '
                       'before these stresses do.')

    # back to the bottom-fibre frame
    ybar_t_abs = ybar_t + c_bot
    ybar_b_abs = ybar_b + c_bot
    top = pbm.TeeProps(
        A_t, ybar_t_abs, I_t, max(d - y_hole_top, 0.0),
        I_t / max(ybar_t_abs - y_hole_top, 1e-9),
        I_t / max(d - ybar_t_abs, 1e-9))
    bot = pbm.TeeProps(
        A_b, ybar_b_abs, I_b, max(y_hole_bot, 0.0),
        I_b / max(y_hole_bot - ybar_b_abs, 1e-9),
        I_b / max(ybar_b_abs, 1e-9))
    return {'top': top, 'bottom': bot, 'valid': valid, 'warning': warning}


def material_width_at(section, y_from_bottom):
    """Total horizontal thickness of material at a given height -- the
    general analogue of a rolled section's `tw`.

    For the two-channel welded box this correctly returns 20 mm at
    mid-depth (two 10 mm webs), which is the thickness the web-post check
    needs and which no single `tw` attribute could have supplied.

    Scanline with the even-odd rule over every loop of every piece.
    Because the pieces do not overlap and each hole lies inside its own
    outline, parity across the combined crossing set gives exactly the
    solid intervals."""
    pieces = shapes.section_pieces(section)
    ext = shapes.section_extents(pieces)
    if ext is None:
        return 0.0
    y = y_from_bottom + ext[1]                   # into the centroid frame
    xs = []
    for p in pieces:
        for loop in [p.outline] + list(p.holes):
            n = len(loop)
            for i in range(n):
                x1, y1 = loop[i]
                x2, y2 = loop[(i + 1) % n]
                if (y1 > y) != (y2 > y):
                    xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    if len(xs) < 2:
        return 0.0
    xs.sort()
    return sum(xs[i + 1] - xs[i] for i in range(0, len(xs) - 1, 2))


def net_I(section, y_hole_bot, y_hole_top):
    """Second moment of the netted section about the GROSS section's own
    neutral axis -- the quantity `net_I_at` needs for the deflection and
    for the stiffness of a hyperstatic solve."""
    res = tees_at(section, y_hole_bot, y_hole_top)
    c_bot = section_bottom_offset(section)
    t, b = res['top'], res['bottom']
    return ((t.I + t.A * (t.y_bar - c_bot) ** 2)
            + (b.I + b.A * (b.y_bar - c_bot) ** 2))


def supports_openings(section):
    """True when this section can have openings analysed through it at
    all -- i.e. it can say what shape it is."""
    try:
        return bool(shapes.section_pieces(section))
    except Exception:
        return False
