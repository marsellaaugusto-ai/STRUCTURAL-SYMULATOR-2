"""
section_shapes.py — the DRAWABLE outline of any section this tab can build.

Every section type in the tab knows its own A, I and S, but until now none
of them could say what it LOOKS like. That is why the Perforated Beam tab
was the only tab in the program with no diagram of its own: there was
nothing to draw. This module is the missing piece — one function that
turns any section object into polygons, so the views can draw a catalog
I-beam, a hand-drawn profile with holes, and a two-profile welded compound
through the same code path.

Pure geometry: no tkinter, same math/UI boundary as the rest of the tab
(see MODULAR_ARCHITECTURE.md).

FRAME. Everything comes back with the origin AT THE SECTION'S CENTROID and
y upward. That is the frame the section properties are already expressed
in, so a view can draw the neutral axis at y = 0 and the extreme-fibre
distances as literal distances, with no per-type special-casing.

ROOT FILLETS are ignored, exactly as they are in every section-property
formula in this tab (see MANIFESTO §3.9). The drawing therefore matches
the numbers rather than the steel, which is the right way round: a picture
that disagreed with the computed I would be worse than no picture.
"""
import math

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import profile_sketcher_math as psm
from apps.perforated_beam import welded_section_math as wsm


class SectionPiece:
    """One closed region of a section: an outline and the holes cut in it.

    A section is a LIST of these rather than a single outline because a
    compound section is genuinely several disconnected pieces, and drawing
    them as one polygon would invent material in the gap between them."""

    def __init__(self, outline, holes=None, label='', kind='solid'):
        self.outline = list(outline)
        self.holes = [list(h) for h in (holes or [])]
        self.label = label
        self.kind = kind          # 'solid' | 'ghost' (ghost = not real material)

    def translated(self, dx, dy):
        return SectionPiece([(x + dx, y + dy) for x, y in self.outline],
                            [[(x + dx, y + dy) for x, y in h] for h in self.holes],
                            self.label, self.kind)

    def bbox(self):
        xs = [p[0] for p in self.outline]
        ys = [p[1] for p in self.outline]
        return min(xs), min(ys), max(xs), max(ys)


# ── primitive shapes, each centred on its own centroid ───────────────────

def _rolled_polygon(sec):
    """Doubly symmetric I, centred on its centroid (which is its middle)."""
    d, bf, tf, tw = sec.d, sec.bf, sec.tf, sec.tw
    hd, hb, ht = d / 2.0, bf / 2.0, tw / 2.0
    return [
        (-hb, -hd), (hb, -hd), (hb, -hd + tf), (ht, -hd + tf),
        (ht, hd - tf), (hb, hd - tf), (hb, hd), (-hb, hd),
        (-hb, hd - tf), (-ht, hd - tf), (-ht, -hd + tf), (-hb, -hd + tf),
    ]


def _channel_polygon(sec):
    """C with the web on the left, drawn in its own x=0..bf frame and then
    shifted so the centroid lands at the origin. The vertical centroid is
    mid-height (the shape is symmetric about it); the horizontal one is
    `x_bar`, which ChannelSection already computes."""
    h, bf, tf, tw = sec.h, sec.bf, sec.tf, sec.tw
    hh = h / 2.0
    pts = [
        (0.0, -hh), (bf, -hh), (bf, -hh + tf), (tw, -hh + tf),
        (tw, hh - tf), (bf, hh - tf), (bf, hh), (0.0, hh),
    ]
    x_bar = getattr(sec, 'x_bar', bf / 2.0)
    return [(x - x_bar, y) for x, y in pts]


def _custom_pieces(sec):
    """A drawn profile, re-centred from its sketch frame onto its centroid."""
    cx, cy = sec.centroid
    outline = [(x - cx, y - cy) for x, y in sec.outline]
    holes = [[(x - cx, y - cy) for x, y in h] for h in getattr(sec, 'holes', [])]
    return [SectionPiece(outline, holes, getattr(sec, 'name', 'profile'))]


def _oriented_pieces(sec):
    """OrientedSection: apply the same rotation/mirror to the geometry that
    it applies to the section properties, so the picture and the numbers
    cannot disagree.

    `rotate90` swaps the section's own two in-plane axes -- (x, y) -> (y, -x)
    -- which is what makes its weak axis resist vertical bending. `mirror`
    flips top for bottom."""
    base_pieces = section_pieces(sec.base)
    out = []
    for p in base_pieces:
        pts = p.outline
        holes = p.holes
        if sec.rotate90:
            pts = [(y, -x) for x, y in pts]
            holes = [[(y, -x) for x, y in h] for h in holes]
        if sec.mirror:
            pts = [(x, -y) for x, y in pts]
            holes = [[(x, -y) for x, y in h] for h in holes]
        out.append(SectionPiece(pts, holes, p.label, p.kind))
    return out


# ── the one entry point ──────────────────────────────────────────────────

def section_pieces(section):
    """Any section object -> [SectionPiece, ...], origin at its centroid.

    Returns [] for a section type with no known geometry, rather than
    raising: a view should degrade to 'no preview available' instead of
    taking the whole results pane down with it."""
    sec = getattr(section, 'section', None)
    if sec is not None and hasattr(section, 'welds'):      # WeldedProfile
        return section_pieces(sec)

    if isinstance(section, wsm.CompoundSection):
        cx, cy = section.centroid
        out = []
        for part in section.parts:
            for piece in section_pieces(part.section):
                out.append(piece.translated(part.dx - cx, part.dy - cy))
        return out

    if isinstance(section, pbm.BuiltUpDoubleSection):
        # equal height, side by side, separated by `gap`
        half = section.gap / 2.0
        out = []
        for base, sign in ((section.base_a, -1.0), (section.base_b, +1.0)):
            w = _half_width(base)
            for piece in section_pieces(base):
                out.append(piece.translated(sign * (half + w), 0.0))
        return out

    if isinstance(section, pbm.BuiltUpDoubleChannelSection):
        ch = section.channel
        gap = section.overall_width - 2 * ch.bf
        out = []
        for sign in (-1.0, +1.0):
            pts = _channel_polygon(ch)
            if sign > 0:                       # toes face inward: mirror the right one
                pts = [(-x, y) for x, y in pts]
            shift = sign * (section.overall_width / 2.0 - ch.bf + _channel_centroid_x(ch))
            out.append(SectionPiece([(x + shift, y) for x, y in pts], [], ch.name))
        return out

    if isinstance(section, pbm.OrientedSection):
        return _oriented_pieces(section)

    if isinstance(section, pbm.CustomProfileSection):
        return _custom_pieces(section)

    if isinstance(section, pbm.RolledSection):
        return [SectionPiece(_rolled_polygon(section), [], section.name)]

    if isinstance(section, pbm.ChannelSection):
        return [SectionPiece(_channel_polygon(section), [], section.name)]

    return []


def _half_width(base):
    """Distance from a base's centroid to its own left edge -- used to butt
    two profiles either side of a gap."""
    try:
        _, right, left = pbm._x_fiber_distances(base)
        return left
    except (AttributeError, TypeError):
        return getattr(base, 'bf', getattr(base, 'width', 100.0)) / 2.0


def _channel_centroid_x(ch):
    return getattr(ch, 'x_bar', ch.bf / 2.0)


def section_welds(section):
    """Weld lines in the same centroid-origin frame as `section_pieces`."""
    welds = getattr(section, 'welds', None) or []
    cx, cy = (0.0, 0.0)
    try:
        cx, cy = section.centroid
    except Exception:
        pass
    out = []
    for w in welds:
        out.append(((w.p1[0] - cx, w.p1[1] - cy),
                    (w.p2[0] - cx, w.p2[1] - cy),
                    getattr(w, 'label', '')))
    return out


def section_extents(pieces):
    """(xmin, ymin, xmax, ymax) over every piece, or None when empty."""
    if not pieces:
        return None
    boxes = [p.bbox() for p in pieces]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


# ── beam-elevation geometry ──────────────────────────────────────────────

def opening_outlines(beam):
    """Each opening as (label, [(x, y), ...]) in BEAM coordinates: x along
    the span, y measured from the section's own mid-depth, so an elevation
    can draw the holes where they actually are.

    `vertices_abs(d)` returns them relative to the section's soffit, so the
    d/2 shift below is what puts them on the same axis as the beam profile
    drawn around them."""
    out = []
    d = beam.section.d
    for op in beam.openings:
        pts = [(x, y - d / 2.0) for x, y in op.vertices_abs(d)]
        out.append((op.label, pts))
    return out


def beam_profile_outline(beam):
    """The beam seen from the side: a rectangle L long and d deep, plus the
    flange lines that make it read as a beam rather than a plate."""
    d = beam.section.d
    L = beam.L
    box = [(0.0, -d / 2.0), (L, -d / 2.0), (L, d / 2.0), (0.0, d / 2.0)]
    tf = getattr(beam.section, 'tf', None)
    flanges = []
    if tf:
        flanges = [[(0.0, d / 2.0 - tf), (L, d / 2.0 - tf)],
                   [(0.0, -d / 2.0 + tf), (L, -d / 2.0 + tf)]]
    return box, flanges


# ── axonometric projection ───────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────
# Hidden-line removal for the axonometric view (2026-09-10)
# ─────────────────────────────────────────────────────────────────────────
#
# `isometric` maps (x, y, z) -> (x + z*0.5*cos30, y + z*0.5*sin30). The 3-D
# direction that projects to nothing is therefore (-0.433, -0.25, 1) --
# so LARGER z IS FARTHER, and the direction TOWARD the viewer from any
# point is (+0.433, +0.25, -1).
#
# A beam is an extrusion along x, so whether a point is hidden does not
# depend on x at all (away from the two ends): it is decided entirely in
# the section's own (z, y) plane. Walk from the point toward the viewer;
# if the walk passes through material, the point is behind something.
# That is what lets a drawing distinguish the near web from the far one,
# which is the whole reason to bother.

VIEW_TOWARD_Z = -1.0        # toward the viewer: z decreases
VIEW_TOWARD_Y = 0.25        # ... and y rises, at the projection's own slope


def _point_in_piece(piece, z, y):
    if not psm.point_in_polygon((z, y), piece.outline):
        return False
    return not any(psm.point_in_polygon((z, y), h) for h in piece.holes)


def point_is_solid(pieces, z, y):
    """Is (z, y) inside this section's material?"""
    return any(_point_in_piece(p, z, y) for p in pieces)


def occluded_in_section(pieces, z, y, reach=None, steps=48, eps=None):
    """Is the section point (z, y) hidden behind nearer material?

    Marches from the point toward the viewer and asks whether the ray
    passes through solid material. `eps` steps off the boundary first, so
    a point ON an edge is not reported as occluded by its own piece.

    Returns False for a point already at the front, which is what makes a
    silhouette edge come out solid."""
    if not pieces:
        return False
    ext = section_extents(pieces)
    if ext is None:
        return False
    width = max(ext[2] - ext[0], 1e-9)
    depth = max(ext[3] - ext[1], 1e-9)
    if reach is None:
        reach = width * 1.05
    if eps is None:
        eps = min(width, depth) * 1e-3

    z0 = z + VIEW_TOWARD_Z * eps
    y0 = y + VIEW_TOWARD_Y * eps
    for i in range(1, steps + 1):
        t = reach * i / steps
        if point_is_solid(pieces, z0 + VIEW_TOWARD_Z * t, y0 + VIEW_TOWARD_Y * t):
            return True
    return False


def web_planes(section):
    """The z of each web plate's FRONT face, nearest first.

    Openings pass through every web, and drawing them on only one plane
    -- which is what this view did -- leaves a two-web box looking like a
    single plate. Reuses the same material scan Chapter G uses, so "what
    counts as a web" has one definition in this app, not two."""
    from apps.perforated_beam import section_plastic as sp
    try:
        pieces = shapes_pieces = section_pieces(section)
        ext = section_extents(pieces)
        if ext is None:
            return []
        y_mid = 0.5 * (ext[1] + ext[3])
        runs = sp.material_runs_at(section, y_mid, shapes_pieces)
    except Exception:
        return []
    # nearest first: smaller z is nearer the viewer
    return sorted(a for a, _b in runs)


def isometric(x, y, z, scale_z=0.5, angle_deg=30.0):
    """A plain axonometric projection: the span runs to the right, the
    section's depth is up, and the section's width recedes up-right.

    Deliberately a fixed projection with no rotation control. The purpose
    of this view is to make the arrangement legible at a glance -- which
    way the profiles face, where the openings and stitch plates fall --
    not to be a modelling environment. A free 3-D camera would be a much
    larger thing to build and maintain, and would not answer those
    questions any better."""
    a = math.radians(angle_deg)
    return (x + z * scale_z * math.cos(a),
            y + z * scale_z * math.sin(a))
