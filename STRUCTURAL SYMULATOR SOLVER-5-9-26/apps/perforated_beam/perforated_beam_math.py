"""
perforated_beam_math.py — deterministic analysis engine for the Perforated
Beam / Cellular Beam tab.

UNITS (fixed for this module, see MANIFESTO §1 for why): length mm,
force N, stress N/mm^2 = MPa, moment/torque N*mm. This differs from the
Beam tab (N, m) and Truss tab (kN, m) -- each tab documents its own units
independently, as already established in this codebase; mixing units
*within* a module is what actually causes errors, not differing
conventions *between* tabs.

Scope (single-span, simply supported, forked-end beam only -- see
MANIFESTO "Known limitations"):
  - global statics (V, M, T) for an arbitrary combination of point loads,
    point moments, point torques, trapezoidal distributed loads/torques,
    and load-eccentricity-induced torque, by closed-form superposition;
  - arbitrary-polygon web openings, uniform or variable pattern, with a
    numerically general (not shape-specific) net-section calculation;
  - Vierendeel (secondary) moment check at each opening;
  - web-post shear/buckling check between adjacent openings;
  - combined bending + torsion check with automatic doubler-plate sizing.

No Tkinter, Excel, or drawing dependencies live here -- this is the
apps/beam-style "stateful UI vs. deterministic calculation" boundary
described in REPORTS AND GUIDES/MODULAR_ARCHITECTURE.md, so this module
is the intended reuse/port boundary if a future non-Python port happens.
"""
import math
from dataclasses import dataclass, field

# ─────────────────────────────────────────────────────────────────────────
# 1. Material & rolled-section catalog
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class Material:
    """Steel material. Fy, Fu, E in MPa. G derived from E if not given
    (isotropic, nu=0.3 -- standard structural-steel assumption)."""
    Fy: float
    Fu: float = None
    E: float = 200000.0
    G: float = None
    name: str = ''

    def __post_init__(self):
        if self.Fu is None:
            self.Fu = 1.5 * self.Fy
        if self.G is None:
            self.G = self.E / (2 * (1 + 0.3))


@dataclass
class RolledSection:
    """Doubly-symmetric rolled I/W section. d = total depth, bf = flange
    width, tf = flange thickness, tw = web thickness (mm). Root fillets
    are ignored (see MANIFESTO limitations) -- a standard, slightly
    conservative simplification for area/inertia at this check level."""
    name: str
    d: float
    bf: float
    tf: float
    tw: float

    @property
    def A(self):
        return 2 * self.bf * self.tf + (self.d - 2 * self.tf) * self.tw

    @property
    def I(self):
        return (self.bf * self.d ** 3 - (self.bf - self.tw) * (self.d - 2 * self.tf) ** 3) / 12.0

    @property
    def Iy(self):
        """Weak-axis second moment, about the vertical centroidal axis.
        Informational for the section's own bending checks (this module
        is strong-axis-only there), but needed by OrientedSection to
        support rotating a section 90 degrees relative to gravity."""
        hw = self.d - 2 * self.tf
        return (2 * self.tf * self.bf ** 3 + hw * self.tw ** 3) / 12.0

    @property
    def S(self):
        return self.I / (self.d / 2.0)

    @property
    def Zpl(self):
        hw = self.d - 2 * self.tf
        return self.bf * self.tf * (self.d - self.tf) + self.tw * hw ** 2 / 4.0

    @property
    def J(self):
        """St. Venant torsion constant, open thin-walled sum-of-plates
        approximation (no fillet enhancement -- conservative)."""
        hw = self.d - 2 * self.tf
        return (2 * self.bf * self.tf ** 3 + hw * self.tw ** 3) / 3.0

    @property
    def Aweb(self):
        return (self.d - 2 * self.tf) * self.tw


# A small starter catalog (mm). Extend freely -- this is plain data, not
# a format the rest of the module depends on structurally.
SECTION_CATALOG = {
    'IPE 240': RolledSection('IPE 240', 240, 120, 9.8, 6.2),
    'IPE 300': RolledSection('IPE 300', 300, 150, 10.7, 7.1),
    'IPE 400': RolledSection('IPE 400', 400, 180, 13.5, 8.6),
    'IPE 500': RolledSection('IPE 500', 500, 200, 16.0, 10.2),
    'HEB 240': RolledSection('HEB 240', 240, 240, 17.0, 10.0),
    'HEB 300': RolledSection('HEB 300', 300, 300, 19.0, 11.0),
    'W 12x26 (approx)': RolledSection('W 12x26 (approx)', 310.4, 165.6, 9.7, 5.8),
    'W 16x40 (approx)': RolledSection('W 16x40 (approx)', 406.4, 177.8, 11.9, 7.1),
}

STEEL_A36 = Material(Fy=250.0, Fu=400.0, name='A36 / F24 approx')
STEEL_A992 = Material(Fy=345.0, Fu=450.0, name='A992 / F36 approx')


# ─────────────────────────────────────────────────────────────────────────
# 1b. Additional section types -- channel, built-up double-channel, and a
#     general numerically-integrated custom profile.
#
# SECTION PROTOCOL: every section type used as `BeamConfig.section` must
# expose `A`, `I`, `S`, `d` (mm/mm^2/mm^3/mm as usual). `Aweb` and `J` are
# OPTIONAL -- if absent, the combined bending+shear+torsion check
# (`analyze_combined`) automatically degrades to a bending-only check
# and says so in its result, rather than fabricating a shear/torsion
# property for a shape it can't infer one from. Web-opening perforation
# support (`net_section_at`, Vierendeel, web-post checks) is RolledSection-
# specific and is explicitly rejected for any other section type in
# `BeamConfig.__post_init__` -- seeing an opening's true effect on an
# arbitrary or built-up shape needs shape-specific net-section logic this
# module does not attempt to generalize (see MANIFESTO limitations).
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class ChannelSection:
    """Single rolled U/C (channel) section. h = total depth, bf = flange
    width, tf = flange thickness, tw = web thickness (mm), same
    root-fillets-ignored simplification as RolledSection. The web is
    assumed to run the full depth at one edge (x=0..tw) with both flanges
    extending from it to x=0..bf -- the standard channel shape."""
    name: str
    h: float
    bf: float
    tf: float
    tw: float

    @property
    def A(self):
        return 2 * self.bf * self.tf + (self.h - 2 * self.tf) * self.tw

    @property
    def Ix(self):
        """About the channel's own horizontal centroidal axis (mid-depth
        -- same axis a doubly-symmetric section would use, since flange
        offset in x doesn't affect a strong-axis/Ix calculation). Same
        closed form as RolledSection.I."""
        return (self.bf * self.h ** 3 - (self.bf - self.tw) * (self.h - 2 * self.tf) ** 3) / 12.0

    @property
    def x_bar(self):
        """Centroid's distance from the outer web face (x=0), needed to
        combine two channels for weak-axis properties."""
        A_web = (self.h - 2 * self.tf) * self.tw
        A_fl = 2 * self.bf * self.tf
        x_web = self.tw / 2.0
        x_fl = self.bf / 2.0
        return (A_web * x_web + A_fl * x_fl) / (A_web + A_fl)

    @property
    def Iy(self):
        """Weak-axis second moment, about the channel's own centroidal
        vertical axis. Informational only -- this module's checks are
        strong-axis (Ix) only, same scope as RolledSection."""
        A_web = (self.h - 2 * self.tf) * self.tw
        A_fl = self.bf * self.tf
        xb = self.x_bar
        I_web = (self.h - 2 * self.tf) * self.tw ** 3 / 12.0 + A_web * (self.tw / 2.0 - xb) ** 2
        I_fl_each = self.tf * self.bf ** 3 / 12.0 + A_fl * (self.bf / 2.0 - xb) ** 2
        return I_web + 2 * I_fl_each

    @property
    def S(self):
        return self.Ix / (self.h / 2.0)

    @property
    def d(self):
        """Alias for `h` -- lets ChannelSection conform to the same
        A/I/S/d protocol every other section type in this module uses
        (needed e.g. so it can be used standalone as a BuiltUpDoubleSection
        base)."""
        return self.h

    @property
    def I(self):
        """Alias for `Ix` -- this module's checks are strong-axis only,
        so `I` always means "the strong-axis value" for every section
        type; `Ix`/`Iy` stay available too since a channel's asymmetry
        makes the distinction worth keeping explicit."""
        return self.Ix

    @property
    def Aweb(self):
        return (self.h - 2 * self.tf) * self.tw

    @property
    def J(self):
        """St. Venant torsion constant, open thin-walled sum-of-plates
        approximation, same style as RolledSection.J."""
        hw = self.h - 2 * self.tf
        return (2 * self.bf * self.tf ** 3 + hw * self.tw ** 3) / 3.0


CHANNEL_CATALOG = {
    'UPN 100': ChannelSection('UPN 100', 100, 50, 8.5, 6.0),
    'UPN 140': ChannelSection('UPN 140', 140, 60, 10.0, 7.0),
    'UPN 180': ChannelSection('UPN 180', 180, 70, 11.0, 8.0),
    'UPN 220': ChannelSection('UPN 220', 220, 80, 12.5, 9.0),
    'UPN 260': ChannelSection('UPN 260', 260, 90, 14.0, 10.0),
}


@dataclass
class BuiltUpDoubleChannelSection:
    """Two identical channels placed with their flanges facing inward
    (toes-in) across a central gap, at the same height, connected at
    intervals along the beam's length by welded tie/batten plates
    spanning that gap -- the classic "double-channel box" built-up beam.
    `overall_width` is the total outer width of the built-up shape
    (flange tip to flange tip is NOT applicable here since the flanges
    face inward -- this is outer web face to outer web face); the clear
    gap the tie plates must span is derived from it.

    Strong-axis-only (Ix), same scope as RolledSection: because both
    channels sit at the same height, each one's own centroidal axis IS
    the combined section's neutral axis, so Ix_total = 2 * channel.Ix
    exactly, no parallel-axis term needed. See `design_builtup_connector`
    for sizing the tie plates themselves."""
    channel: ChannelSection
    overall_width: float
    orientation: str = 'toes_in'

    def __post_init__(self):
        if self.orientation != 'toes_in':
            raise ValueError("BuiltUpDoubleChannelSection currently only models "
                              "orientation='toes_in' (flanges facing inward across "
                              "a central gap) -- the configuration this module's "
                              "connector design check assumes.")
        if self.gap <= 0:
            raise ValueError(f'overall_width ({self.overall_width:.0f} mm) must exceed '
                              f'2 x channel flange width ({2 * self.channel.bf:.0f} mm) '
                              'so the two channels do not overlap.')

    @property
    def gap(self):
        """Clear gap between the two channels' inward-facing flange tips
        -- the span the tie plates must bridge."""
        return self.overall_width - 2 * self.channel.bf

    @property
    def d(self):
        return self.channel.h

    @property
    def name(self):
        return f'Double {self.channel.name} (built-up, {self.overall_width:.0f} mm overall)'

    @property
    def A(self):
        return 2 * self.channel.A

    @property
    def I(self):
        return 2 * self.channel.Ix

    @property
    def S(self):
        return self.I / (self.d / 2.0)

    @property
    def Aweb(self):
        """Both channel webs carry shear together."""
        return 2 * (self.channel.h - 2 * self.channel.tf) * self.channel.tw

    @property
    def J(self):
        """Open-section (unconnected) torsion constant -- a conservative
        lower bound. Once the tie plates close the section into an
        effective box, actual torsional stiffness is far higher (Bredt
        closed-section behavior); this module does not compute that
        closed-section J, since it depends on tie-plate spacing/stiffness
        rather than being a fixed section property. `design_builtup_connector`
        below sizes the plates using Bredt shear flow directly from T(x),
        independent of this J."""
        return 2 * self.channel.J

    @property
    def enclosed_area(self):
        """Am, the mean-line enclosed area of the effective closed box
        formed by the two webs (outer boundary) and the flange inner
        faces -- used for Bredt thin-walled torsion shear flow. Approximates
        the box as bounded by the webs' inner faces and the flanges' inner
        faces; ignores the small step where each channel's own flange meets
        the tie plate, consistent with this module's other section-property
        approximations (root fillets, etc. -- see MANIFESTO)."""
        clear_width = self.overall_width - 2 * self.channel.tw
        clear_height = self.channel.h - 2 * self.channel.tf
        return max(clear_width, 1e-6) * max(clear_height, 1e-6)


def _y_fiber_distances(section):
    """(dist_to_top, dist_to_bottom) from a section's own centroidal
    horizontal axis to its extreme fibers. Prefers explicit `S_top`/
    `S_bot` when the section defines them (an asymmetric shape, e.g.
    CustomProfileSection); falls back to the doubly-symmetric `d/2`
    assumption every other section type in this module uses (which is
    also exactly correct for those types, not just a rough guess)."""
    I = section.I
    if hasattr(section, 'S_top') and hasattr(section, 'S_bot'):
        return I / section.S_top, I / section.S_bot
    half = section.d / 2.0
    return half, half


def _x_fiber_distances(section):
    """(Iy, dist_to_right, dist_to_left) from a section's own centroidal
    vertical axis to its extreme fibers -- the weak-axis analogue of
    `_y_fiber_distances`, used by OrientedSection to rotate a section 90
    degrees. Requires the section to expose `Iy` (raises AttributeError,
    by design, if it doesn't -- e.g. a CustomProfileSection nobody added
    Iy support for, or any future section type that only ever models
    strong-axis behavior)."""
    Iy = section.Iy
    if hasattr(section, 'x_extent') and hasattr(section, 'centroid'):
        x_min, x_max = section.x_extent
        cx, _ = section.centroid
        return Iy, x_max - cx, cx - x_min
    if hasattr(section, 'x_bar'):
        # ChannelSection: spans x in [0, bf], centroid at x_bar.
        return Iy, section.bf - section.x_bar, section.x_bar
    # Doubly symmetric about the vertical axis too (RolledSection).
    half = section.bf / 2.0
    return Iy, half, half


@dataclass
class OrientedSection:
    """Wraps a *simple* section (RolledSection, ChannelSection, or
    CustomProfileSection -- NOT another built-up/oriented section) with
    an explicit orientation relative to gravity. This module has no way
    to know how a catalog section (or a custom one) is actually sitting
    on site, so this lets the user correct for that instead of silently
    assuming "as listed in the catalog" is how it's installed.

    `rotate90=True` swaps which of the section's own two in-plane axes
    resists *vertical* (gravity) bending -- its own weak axis (`Iy`)
    becomes what this module treats as the strong/vertical axis. This is
    the orientation choice that actually changes any computed result.

    `mirror=True` flips top and bottom (swaps which fiber is `S_top` vs
    `S_bot`). This only matters for a shape that ISN'T symmetric about
    its own centroidal horizontal axis -- a custom-drawn asymmetric
    profile, most likely. It's a no-op for RolledSection, ChannelSection,
    or either built-up type, since all of those are already symmetric
    top-to-bottom about their own centroid.

    `J` (torsion constant) passes through unchanged either way -- torsional
    resistance about the beam's own longitudinal axis doesn't depend on
    which way the cross-section faces gravity. `Aweb` passes through
    unchanged when NOT rotated; when rotated, it's re-derived from
    `bf`/`tf` if the base provides them (using the flanges as the new
    "vertical" shear-resisting elements, the natural analogue of the
    unrotated formula), and is otherwise unavailable (graceful
    bending-only degrade, same as CustomProfileSection's un-rotated
    case) -- see MANIFESTO for why this is flagged as an approximation.
    """
    base: object
    rotate90: bool = False
    mirror: bool = False

    def __post_init__(self):
        if isinstance(self.base, (BuiltUpDoubleChannelSection, BuiltUpDoubleSection, OrientedSection)):
            raise ValueError('OrientedSection can only wrap a simple section (RolledSection, '
                              'ChannelSection, or CustomProfileSection) -- orient the component '
                              'profile before combining it into a built-up section, not after.')
        if self.rotate90 and not hasattr(self.base, 'Iy'):
            raise ValueError(f'{getattr(self.base, "name", "This section")} has no weak-axis inertia '
                              '(Iy) defined, so it cannot be rotated 90 degrees.')

    @property
    def name(self):
        base_name = getattr(self.base, 'name', 'profile')
        tags = []
        if self.rotate90:
            tags.append('rotated 90°')
        if self.mirror:
            tags.append('mirrored')
        return base_name + (f' ({", ".join(tags)})' if tags else '')

    @property
    def A(self):
        return self.base.A

    @property
    def _I_and_fibers(self):
        if self.rotate90:
            I, top, bottom = _x_fiber_distances(self.base)
        else:
            I = self.base.I
            top, bottom = _y_fiber_distances(self.base)
        if self.mirror:
            top, bottom = bottom, top
        return I, top, bottom

    @property
    def I(self):
        I, _, _ = self._I_and_fibers
        return I

    @property
    def d(self):
        _, top, bottom = self._I_and_fibers
        return top + bottom

    @property
    def S_top(self):
        I, top, _ = self._I_and_fibers
        return I / max(top, 1e-9)

    @property
    def S_bot(self):
        I, _, bottom = self._I_and_fibers
        return I / max(bottom, 1e-9)

    @property
    def S(self):
        return min(self.S_top, self.S_bot)

    @property
    def J(self):
        return self.base.J

    @property
    def Aweb(self):
        if not self.rotate90:
            return self.base.Aweb
        if hasattr(self.base, 'bf') and hasattr(self.base, 'tf'):
            return 2 * self.base.bf * self.base.tf
        raise AttributeError('Cannot estimate a rotated shear area for this base section type.')


@dataclass
class BuiltUpDoubleSection:
    """Two profiles placed side by side at the same height and tied
    together at intervals by welded plates -- a generalization of
    BuiltUpDoubleChannelSection to any base shape(s), e.g. two full I/W
    sections, two custom-drawn profiles, two channels, or an ORIENTED
    version of any of those (see OrientedSection). `base_b` defaults to
    `base_a` (the common case: doubling one profile), but can be a
    DIFFERENT section -- including a different custom-drawn profile --
    for an asymmetric built-up pair. (For two identical channels
    specifically, BuiltUpDoubleChannelSection is more convenient since it
    derives the plate-spanned gap automatically from the channel's own
    flange width; this class needs `gap` given directly, since there's no
    generic way to infer it from an arbitrary base's own geometry.)

    Because both pieces sit at the same height, A/I (and Aweb/J, when
    BOTH bases provide them) simply add -- true regardless of whether the
    two bases are identical or not, AS LONG AS they're vertically aligned
    so each one's own centroidal height coincides (the standard
    side-by-side detailing assumption; genuinely offset/staggered pairs
    aren't modeled). When the two bases have different depths or are
    asymmetric top-to-bottom (e.g. a custom profile), `d`/`S_top`/`S_bot`
    correctly use whichever piece extends further in each direction from
    the shared centroidal line, via `_y_fiber_distances`.

    `enclosed_area` (for `design_builtup_connector`'s Bredt shear-flow
    calculation) treats the pair as a closed box, using `base_a`'s own
    depth/flange-thickness as the reference -- exact for a channel-like
    base, approximate for a doubly-symmetric one (see MANIFESTO §4b), and
    even more approximate if `base_a` and `base_b` differ substantially
    in size -- verify that check independently for a strongly asymmetric
    pair."""
    base_a: object  # any section exposing at least A, I, S, d (Aweb/J optional)
    gap: float
    base_b: object = None
    _name: str = None

    def __post_init__(self):
        if self.gap <= 0:
            raise ValueError(f'gap ({self.gap:.0f} mm) must be positive.')
        if self.base_b is None:
            self.base_b = self.base_a

    @property
    def name(self):
        if self._name:
            return self._name
        name_a = getattr(self.base_a, 'name', 'profile')
        if self.base_b is self.base_a:
            return f'Double {name_a} (built-up, gap={self.gap:.0f} mm)'
        name_b = getattr(self.base_b, 'name', 'profile')
        return f'{name_a} + {name_b} (built-up, gap={self.gap:.0f} mm)'

    @property
    def A(self):
        return self.base_a.A + self.base_b.A

    @property
    def I(self):
        return self.base_a.I + self.base_b.I

    @property
    def d(self):
        top_a, bot_a = _y_fiber_distances(self.base_a)
        top_b, bot_b = _y_fiber_distances(self.base_b)
        return max(top_a, top_b) + max(bot_a, bot_b)

    @property
    def S_top(self):
        top_a, _ = _y_fiber_distances(self.base_a)
        top_b, _ = _y_fiber_distances(self.base_b)
        return self.I / max(top_a, top_b, 1e-9)

    @property
    def S_bot(self):
        _, bot_a = _y_fiber_distances(self.base_a)
        _, bot_b = _y_fiber_distances(self.base_b)
        return self.I / max(bot_a, bot_b, 1e-9)

    @property
    def S(self):
        """Governing (smaller) section modulus -- matches
        CustomProfileSection's convention for an asymmetric section;
        equals the doubly-symmetric single value when both bases are."""
        return min(self.S_top, self.S_bot)

    @property
    def Aweb(self):
        """Only resolves if BOTH bases have Aweb -- if either doesn't,
        accessing this correctly raises AttributeError, so `hasattr()`
        (used by `_combined_util`'s duck-typing) sees it as absent."""
        return self.base_a.Aweb + self.base_b.Aweb

    @property
    def J(self):
        return self.base_a.J + self.base_b.J

    @property
    def enclosed_area(self):
        base_width = getattr(self.base_a, 'bf', None)
        if base_width is None:
            base_width = getattr(self.base_a, 'width', None)
        if base_width is None and hasattr(self.base_a, 'outline'):
            xs = [p[0] for p in self.base_a.outline]
            base_width = max(xs) - min(xs)
        if base_width is None:
            raise AttributeError('Cannot estimate enclosed area for connector design: the base '
                                  'section has no bf/width to derive a box from.')
        clear_height = self.base_a.d
        tf = getattr(self.base_a, 'tf', 0.0)
        if tf:
            clear_height = self.base_a.d - 2 * tf
        return max(self.gap, 1e-6) * max(clear_height, 1e-6)


@dataclass
class CustomProfileSection:
    """A general cross-section defined by its own closed outline (a list
    of (x, y) vertices in mm, arcs already discretized into short segments
    by whoever built the outline -- see section_profile_ui.py). Section
    properties (A, centroid, Ix, top/bottom section moduli) are computed
    numerically by polygon integration (2D Green's-theorem area moments),
    so ANY simple (non-self-intersecting) closed shape is supported --
    channels, angles, tees, plates, or a hand-drawn built-up shape.

    Deliberately does NOT expose `Aweb`/`J`: there is no general way to
    infer "the web" or a meaningful open-section torsion constant from an
    arbitrary outline, so `analyze_combined` correctly falls back to a
    bending-only check for this section type rather than guessing."""
    name: str
    outline: list  # [(x, y), ...] mm, absolute, not repeating the first point

    def __post_init__(self):
        area = self._signed_area()
        if abs(area) < 1e-9:
            raise ValueError('Custom profile outline has zero area -- check the '
                              'points describe a real closed shape.')

    def _signed_area(self):
        pts = self.outline
        n = len(pts)
        a = 0.0
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            a += x1 * y2 - x2 * y1
        return a / 2.0

    @property
    def A(self):
        return abs(self._signed_area())

    @property
    def centroid(self):
        """(cx, cy) in the outline's own coordinate frame."""
        pts = self.outline
        n = len(pts)
        a = self._signed_area()
        cx = cy = 0.0
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            cross = x1 * y2 - x2 * y1
            cx += (x1 + x2) * cross
            cy += (y1 + y2) * cross
        return cx / (6 * a), cy / (6 * a)

    @property
    def I(self):
        """Ix about the horizontal centroidal axis."""
        pts = self.outline
        n = len(pts)
        a = self._signed_area()
        _, cy = self.centroid
        Ix_origin = 0.0
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            cross = x1 * y2 - x2 * y1
            Ix_origin += (y1 ** 2 + y1 * y2 + y2 ** 2) * cross
        Ix_origin /= 12.0
        # Ix_origin is about the x-axis of whatever frame `outline` was
        # given in (y=0, not necessarily the centroid) -- shift it.
        return abs(Ix_origin) - self.A * cy ** 2

    @property
    def Iy(self):
        """Iy about the vertical centroidal axis -- same polygon-integration
        approach as `I`, with x and y swapped. Needed by OrientedSection
        to support rotating a custom profile 90 degrees relative to
        gravity."""
        pts = self.outline
        n = len(pts)
        a = self._signed_area()
        cx, _ = self.centroid
        Iy_origin = 0.0
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            cross = x1 * y2 - x2 * y1
            Iy_origin += (x1 ** 2 + x1 * x2 + x2 ** 2) * cross
        Iy_origin /= 12.0
        return abs(Iy_origin) - self.A * cx ** 2

    @property
    def d(self):
        ys = [p[1] for p in self.outline]
        return max(ys) - min(ys)

    @property
    def y_extent(self):
        ys = [p[1] for p in self.outline]
        return min(ys), max(ys)

    @property
    def x_extent(self):
        xs = [p[0] for p in self.outline]
        return min(xs), max(xs)

    @property
    def width(self):
        """Overall x-extent (bounding-box width) of the outline --
        useful as a generic "how wide is this shape" fallback (e.g. for
        BuiltUpDoubleSection's enclosed-area estimate) when there's no
        shape-specific `bf` to use instead."""
        xs = [p[0] for p in self.outline]
        return max(xs) - min(xs)

    @property
    def S_top(self):
        _, cy = self.centroid
        _, y_max = self.y_extent
        return self.I / max(y_max - cy, 1e-9)

    @property
    def S_bot(self):
        _, cy = self.centroid
        y_min, _ = self.y_extent
        return self.I / max(cy - y_min, 1e-9)

    @property
    def S(self):
        """Governing (smaller) section modulus -- used by any check that
        only knows about a single `S`, conservatively picking the closer
        fiber."""
        return min(self.S_top, self.S_bot)


def design_builtup_connector(section: BuiltUpDoubleChannelSection, T, spacing=None,
                              weld_Fexx=482.0, weld_phi=0.75, plate_Fy=250.0):
    """Sizes the welded tie plates connecting a BuiltUpDoubleChannelSection's
    two channels, from the torque demand T (N*mm) at the station being
    checked, using classical Bredt thin-walled closed-section shear flow:

        q = T / (2 * Am)                    (N/mm, shear flow around the box)

    This is the well-defined, code-agnostic mechanics of why these plates
    exist: an unconnected channel pair is torsionally very weak (each is
    an open thin-walled section); tying the flanges together across the
    gap lets the pair act as a closed box for torsion, and the plates
    must be sized to carry the shear flow that closing action requires.
    This function does NOT implement a specific code's built-up-member
    connector *spacing* provisions (e.g. AISC 360 D4/E6 slenderness-based
    spacing limits) -- if a specific code's spacing/stability provisions
    also govern your design, check those independently; treat this as
    the torsion-transfer sizing only (see MANIFESTO).

    Two modes:
      - `spacing` given (mm): returns the required two-sided fillet weld
        leg size to transfer that tributary connector's force in one
        plate at that spacing.
      - `spacing=None`: returns the maximum spacing achievable with a
        practical minimum weld size (4 mm fillet), i.e. "how far apart
        can the plates be" for the weakest common weld.

    Weld capacity per AISC 360 J2.4 (LRFD, elastic/simplified — same
    style as this module's other checks): phi*Rn = phi * 0.6*Fexx *
    0.707*w * L_weld, with two weld lines (one each side of the plate)
    each of length `L_weld` = `section.gap` (the plate spans the gap;
    conservatively ignoring any extra weld return length as a design
    margin, not a code minimum)."""
    Am = section.enclosed_area
    q = abs(T) / max(2 * Am, 1e-6)  # N/mm shear flow to be carried around the box
    L_weld = max(section.gap, 1e-6)  # each weld line runs the width of the plate span
    n_weld_lines = 2  # both edges of the tie plate are welded

    def weld_capacity(w):
        return weld_phi * 0.6 * weld_Fexx * 0.707 * w * L_weld * n_weld_lines

    if spacing is not None:
        F_required = q * spacing
        # required leg size from F_required = weld_capacity(w)
        w_req = F_required / max(weld_phi * 0.6 * weld_Fexx * 0.707 * L_weld * n_weld_lines, 1e-9)
        return {
            'q': q, 'spacing': spacing, 'F_required': F_required,
            'weld_leg_required': w_req, 'plate_span': L_weld,
            'note': (f'Required 2-sided fillet weld leg ~{w_req:.1f} mm to carry the '
                     f'torsion-closing shear flow at {spacing:.0f} mm plate spacing.')
        }
    else:
        w_min = 4.0
        F_cap = weld_capacity(w_min)
        spacing_max = F_cap / max(q, 1e-9)
        return {
            'q': q, 'spacing': spacing_max, 'F_required': F_cap,
            'weld_leg_required': w_min, 'plate_span': L_weld,
            'note': (f'With a practical minimum {w_min:.0f} mm 2-sided fillet weld, tie '
                     f'plates may be spaced up to ~{spacing_max:.0f} mm apart.')
        }


# ─────────────────────────────────────────────────────────────────────────
# 2. Opening geometry — arbitrary polygon, plus shape generators
# ─────────────────────────────────────────────────────────────────────────

def opening_circle(diameter, n=48):
    """Regular n-gon approximation of a circular opening, centered at its
    own local origin. n=48 keeps the polygon-approximation error on
    area/inertia below ~0.1%% (see tests) -- not an exact analytic circle,
    see MANIFESTO limitations."""
    r = diameter / 2.0
    return [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def opening_rectangle(width, height):
    """Sharp-cornered rectangular opening (no corner radius / stress
    concentration modeling -- see MANIFESTO limitations)."""
    w, h = width / 2.0, height / 2.0
    return [(-w, -h), (w, -h), (w, h), (-w, h)]


def opening_hexagon(total_width, total_height, flat_width=None):
    """Classic elongated castellated-beam hexagonal opening: horizontal
    top/bottom flats of length `flat_width`, pointed left/right ends at
    +/- total_width/2. Defaults to flat_width = 0.4*total_width, a common
    proportion in castellated-beam layouts."""
    if flat_width is None:
        flat_width = 0.4 * total_width
    e, W, H = flat_width / 2.0, total_width / 2.0, total_height / 2.0
    return [(-e, H), (e, H), (W, 0.0), (e, -H), (-e, -H), (-W, 0.0)]


def opening_polygon(vertices):
    """Pass-through for a fully arbitrary polygon. Must be a simple
    (non-self-intersecting) closed contour, listed in order (CW or CCW,
    doesn't matter -- see polygon_y_span_at_x). Must also be "y-simple":
    any vertical line through the opening's x-range crosses its boundary
    at exactly one entry and one exit point (i.e. star-shaped in y for
    every x) -- true for circles, hexagons, rectangles, and most sensible
    single-opening shapes, but NOT guaranteed for arbitrary re-entrant
    polygons. See MANIFESTO limitations."""
    verts = [(float(x), float(y)) for x, y in vertices]
    if len(verts) < 3:
        raise ValueError('opening_polygon needs at least 3 vertices')
    return verts


@dataclass
class OpeningInstance:
    """One opening placed along the beam. `vertices_local` are (x, y)
    relative to the opening's own center; y=0 is assumed to sit on the
    section's mid-depth (openings centered on the neutral axis -- see
    MANIFESTO assumptions for how to model an off-center opening)."""
    x_center: float
    vertices_local: list
    label: str = ''

    def vertices_abs(self, section_depth):
        yc = section_depth / 2.0
        return [(self.x_center + vx, yc + vy) for vx, vy in self.vertices_local]

    def x_span(self):
        xs = [v[0] for v in self.vertices_local]
        return self.x_center + min(xs), self.x_center + max(xs)


def uniform_layout(shape_vertices, n_openings, spacing, x_start, label_prefix='H'):
    """Uniform case: one shape, repeated at constant spacing (center-to-center)."""
    return [OpeningInstance(x_start + i * spacing, shape_vertices, f'{label_prefix}{i + 1}')
            for i in range(n_openings)]


def variable_layout(entries):
    """Variable case: entries = [(x_center, vertices, label), ...] -- fully
    irregular size/shape/spacing, defined per-opening."""
    return [OpeningInstance(x, v, lbl) for x, v, lbl in entries]


def polygon_y_span_at_x(vertices_abs, x):
    """Vertical line x = const intersected with a closed polygon boundary.
    Returns (y_min, y_max) of the intersection, or None if the line misses
    the polygon entirely. Assumes the "y-simple" property documented on
    opening_polygon (exactly one in/out pair per vertical line)."""
    n = len(vertices_abs)
    ys = []
    for i in range(n):
        x1, y1 = vertices_abs[i]
        x2, y2 = vertices_abs[(i + 1) % n]
        if x1 == x2:
            continue
        lo, hi = (x1, x2) if x1 < x2 else (x2, x1)
        if lo <= x <= hi:
            t = (x - x1) / (x2 - x1)
            ys.append(y1 + t * (y2 - y1))
    if not ys:
        return None
    return min(ys), max(ys)


# ─────────────────────────────────────────────────────────────────────────
# 3. Net (tee) section properties at a given station through an opening
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class TeeProps:
    A: float
    y_bar: float     # centroid, measured from the overall section's bottom fiber (y=0)
    I: float         # about the tee's own centroidal axis
    h: float         # tee depth
    S_hole: float    # section modulus to the fiber at the opening boundary (usually critical)
    S_outer: float   # section modulus to the outer (flange) fiber


def _rect_pair_tee(width_web, h_web, y0_web, width_fl, tf, y0_fl):
    """Composite tee = a web stub rectangle + a flange rectangle, both
    given by (width, height, y of their own bottom fiber). Returns
    (A, y_bar, I_about_own_centroid)."""
    A1 = width_web * h_web
    A2 = width_fl * tf
    y1 = y0_web + h_web / 2.0
    y2 = y0_fl + tf / 2.0
    A = A1 + A2
    y_bar = (A1 * y1 + A2 * y2) / A
    I1 = width_web * h_web ** 3 / 12.0 + A1 * (y1 - y_bar) ** 2
    I2 = width_fl * tf ** 3 / 12.0 + A2 * (y2 - y_bar) ** 2
    return A, y_bar, I1 + I2


def net_section_at(section: RolledSection, y_hole_bot, y_hole_top):
    """Given the local vertical extent of the opening [y_hole_bot,
    y_hole_top] at one station (from polygon_y_span_at_x), return the top
    and bottom tee properties. Only the web is assumed perforated (the
    opening must not reach into a flange) -- if it does, `valid=False`
    and a warning is attached (this station is out of scope / a modeling
    input error, not something to silently clamp)."""
    d, tf, tw, bf = section.d, section.tf, section.tw, section.bf
    warning = None
    valid = True
    if y_hole_top > d - tf + 1e-6 or y_hole_bot < tf - 1e-6:
        valid = False
        warning = ('opening extends into a flange at this station -- reduce opening '
                   'height or eccentricity, or increase section depth')
        y_hole_top = min(y_hole_top, d - tf)
        y_hole_bot = max(y_hole_bot, tf)

    h_top_web = max((d - tf) - y_hole_top, 0.0)
    A_t, ybar_t, I_t = _rect_pair_tee(tw, h_top_web, y_hole_top, bf, tf, d - tf)
    h_top = d - y_hole_top
    S_hole_t = I_t / max(ybar_t - y_hole_top, 1e-9)
    S_out_t = I_t / max((d - ybar_t), 1e-9)
    top = TeeProps(A_t, ybar_t, I_t, h_top, S_hole_t, S_out_t)

    h_bot_web = max(y_hole_bot - tf, 0.0)
    A_b, ybar_b, I_b = _rect_pair_tee(tw, h_bot_web, tf, bf, tf, 0.0)
    h_bot = y_hole_bot
    S_hole_b = I_b / max(y_hole_bot - ybar_b, 1e-9)
    S_out_b = I_b / max(ybar_b, 1e-9)
    bot = TeeProps(A_b, ybar_b, I_b, h_bot, S_hole_b, S_out_b)

    return {'top': top, 'bottom': bot, 'valid': valid, 'warning': warning}


# ─────────────────────────────────────────────────────────────────────────
# 4. Loads & statics (single-span, simply supported, forked ends)
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class PointLoad:
    x: float
    P: float          # +down, N
    e: float = 0.0    # eccentricity from shear center, mm (+e -> +torque = P*e)


@dataclass
class PointMoment:
    x: float
    M: float          # +CCW, N*mm


@dataclass
class PointTorque:
    x: float
    T: float          # N*mm, applied directly (independent of any load eccentricity)


@dataclass
class DistLoad:
    x1: float
    x2: float
    w1: float         # N/mm, +down
    w2: float
    e: float = 0.0    # eccentricity, mm


@dataclass
class DistTorque:
    x1: float
    x2: float
    t1: float         # N*mm/mm
    t2: float


@dataclass
class BeamConfig:
    L: float
    section: RolledSection
    material: Material
    openings: list = field(default_factory=list)
    point_loads: list = field(default_factory=list)
    point_moments: list = field(default_factory=list)
    point_torques: list = field(default_factory=list)
    dist_loads: list = field(default_factory=list)
    dist_torques: list = field(default_factory=list)
    supports: tuple = None  # (xA, xB); None -> defaults to (0, L), i.e. supports at both ends

    def __post_init__(self):
        if self.supports is None:
            self.supports = (0.0, self.L)
        xA, xB = self.supports
        if not (0.0 <= xA < xB <= self.L + 1e-9):
            raise ValueError(f'Supports must satisfy 0 <= xA < xB <= L; got xA={xA:.0f}, '
                              f'xB={xB:.0f}, L={self.L:.0f}. This module models a determinate '
                              '2-support beam only (no more than 2 supports, no fixed ends) -- '
                              'overhangs are fine, additional/redundant supports are not.')
        if self.openings and not isinstance(self.section, RolledSection):
            raise ValueError(
                'Web openings (perforations) are only supported for a standard '
                'RolledSection (doubly-symmetric I/W shape) -- the net-section, '
                'Vierendeel, and web-post checks are built around that specific '
                'flange/web geometry and do not generalize to a channel, '
                'built-up, or custom-drawn section. Remove the openings, or use '
                'a RolledSection for a perforated design.')


def _point_diagram(x, a, Q, xA, xB):
    """Shared 'shear-like'/'moment-like' superposition kernel for a
    concentrated action Q at x=a, for a determinate 2-support beam with
    supports at xA < xB (which may be inset from the beam's physical
    ends, creating overhangs -- see BeamConfig.supports). Reused both for
    transverse point loads (-> V, M) and point torques (-> T; the
    moment-like return value is unused in that case)."""
    span = xB - xA
    RA = Q * (xB - a) / span
    RB = Q - RA
    V = (RA if x > xA else 0.0) + (RB if x > xB else 0.0) - (Q if x > a else 0.0)
    M = (RA * (x - xA) if x > xA else 0.0) + (RB * (x - xB) if x > xB else 0.0) - (Q * (x - a) if x > a else 0.0)
    return V, M


def _moment_diagram(x, a, M0, xA, xB):
    """Concentrated applied bending moment M0 at x=a: induces a constant
    reaction couple (no net vertical force), so shear is piecewise
    constant and moment jumps by M0 at x=a."""
    span = xB - xA
    RA = -M0 / span
    RB = -RA
    V = (RA if x > xA else 0.0) + (RB if x > xB else 0.0)
    M = (RA * (x - xA) if x > xA else 0.0) + (RB * (x - xB) if x > xB else 0.0) + (M0 if x > a else 0.0)
    return V, M


def _dist_diagram(x, x1, x2, w1, w2, xA, xB):
    """Trapezoidal distributed action w1..w2 over [x1, x2], same
    determinate 2-support (possibly overhanging) span as _point_diagram.
    Reused for both distributed transverse loads (-> V, M) and
    distributed torques (-> T)."""
    span = xB - xA
    Wtot = (w1 + w2) / 2.0 * (x2 - x1)
    xbar = (x1 + x2) / 2.0  # safe default; refined below when Wtot is meaningful
    if abs(Wtot) < 1e-12:
        RA = RB = 0.0
    else:
        xbar = x1 + (x2 - x1) * (2 * w2 + w1) / (3 * (w1 + w2))
        RA = Wtot * (xB - xbar) / span
        RB = Wtot - RA
    reaction_V = (RA if x > xA else 0.0) + (RB if x > xB else 0.0)
    reaction_M = (RA * (x - xA) if x > xA else 0.0) + (RB * (x - xB) if x > xB else 0.0)
    if x <= x1:
        return reaction_V, reaction_M
    elif x <= x2:
        xi = x - x1
        Lseg = x2 - x1
        wx = w1 + (w2 - w1) * xi / Lseg if Lseg > 1e-12 else w1
        applied = (w1 + wx) / 2.0 * xi
        if (w1 + wx) > 1e-12:
            xibar = xi * (2 * wx + w1) / (3 * (w1 + wx))
        else:
            xibar = xi / 2.0
        V = reaction_V - applied
        M = reaction_M - applied * (xi - xibar)
        return V, M
    else:
        return reaction_V - Wtot, reaction_M - Wtot * (x - xbar)


def global_V_M(beam: BeamConfig, x):
    """Global shear V(x) and bending moment M(x) via linear superposition
    of every load on the beam. Exact closed-form (no discretization)."""
    xA, xB = beam.supports
    V = M = 0.0
    for pl in beam.point_loads:
        v, m = _point_diagram(x, pl.x, pl.P, xA, xB)
        V += v; M += m
    for pm in beam.point_moments:
        v, m = _moment_diagram(x, pm.x, pm.M, xA, xB)
        V += v; M += m
    for dl in beam.dist_loads:
        v, m = _dist_diagram(x, dl.x1, dl.x2, dl.w1, dl.w2, xA, xB)
        V += v; M += m
    return V, M


def global_T(beam: BeamConfig, x):
    """Global torque T(x). Direct applied torques superpose with the
    torque induced by any eccentric transverse load, using the same
    reaction-split kernel as the shear diagram (see MANIFESTO §3 for the
    equal-form-to-shear-diagram derivation for a uniform-GJ span with
    twist-restrained/forked ends)."""
    xA, xB = beam.supports
    T = 0.0
    for pl in beam.point_loads:
        if pl.e:
            t, _ = _point_diagram(x, pl.x, pl.P * pl.e, xA, xB)
            T += t
    for pt in beam.point_torques:
        t, _ = _point_diagram(x, pt.x, pt.T, xA, xB)
        T += t
    for dl in beam.dist_loads:
        if dl.e:
            t, _ = _dist_diagram(x, dl.x1, dl.x2, dl.w1 * dl.e, dl.w2 * dl.e, xA, xB)
            T += t
    for dt in beam.dist_torques:
        t, _ = _dist_diagram(x, dt.x1, dt.x2, dt.t1, dt.t2, xA, xB)
        T += t
    return T


def reactions(beam: BeamConfig):
    """Vertical reactions (RA at xA, RB at xB) -- a determinate 2-support
    beam; xA/xB default to the beam's own ends (0, L) but may be inset
    to create overhangs (see BeamConfig.supports)."""
    xA, xB = beam.supports
    span = xB - xA
    P_total = sum(pl.P for pl in beam.point_loads) + sum((dl.w1 + dl.w2) / 2.0 * (dl.x2 - dl.x1) for dl in beam.dist_loads)
    RB = 0.0
    for pl in beam.point_loads:
        RB += pl.P * (pl.x - xA) / span
    for pm in beam.point_moments:
        RB += pm.M / span
    for dl in beam.dist_loads:
        Wtot = (dl.w1 + dl.w2) / 2.0 * (dl.x2 - dl.x1)
        if abs(Wtot) > 1e-12:
            xbar = dl.x1 + (dl.x2 - dl.x1) * (2 * dl.w2 + dl.w1) / (3 * (dl.w1 + dl.w2))
            RB += Wtot * (xbar - xA) / span
    RA = P_total - RB
    return RA, RB


def net_I_at(beam: BeamConfig, x):
    """Net second moment of area of the whole cross-section at station x
    (full section away from any opening; top+bottom tee via parallel-axis
    when x lands inside an opening). Used for the deflection estimate."""
    sec = beam.section
    for op in beam.openings:
        x0, x1 = op.x_span()
        if x0 <= x <= x1:
            span = polygon_y_span_at_x(op.vertices_abs(sec.d), x)
            if span is None:
                continue
            y_bot, y_top = span
            net = net_section_at(sec, y_bot, y_top)
            t, b = net['top'], net['bottom']
            y_na = sec.d / 2.0
            return (t.I + t.A * (t.y_bar - y_na) ** 2) + (b.I + b.A * (b.y_bar - y_na) ** 2)
    return sec.I


def deflection_profile(beam: BeamConfig, n=161):
    """Simplified deflection estimate: double integration of M(x)/(E*I_net(x))
    on a fine grid, with v=0 enforced at the two support positions
    (beam.supports -- defaults to the beam's own ends, but may be inset
    to model overhangs). This uses the true netted I(x) at opening
    stations, but does NOT add the extra local (Vierendeel-mechanism)
    flexibility beyond what the reduced I already implies -- see
    MANIFESTO limitations; treat as informational, not a governing
    serviceability check."""
    L = beam.L
    xA, xB = beam.supports
    xs = [i * L / (n - 1) for i in range(n)]
    curv = []
    for x in xs:
        _, M = global_V_M(beam, x)
        I = net_I_at(beam, x)
        curv.append(M / (beam.material.E * I))
    # trapezoidal cumulative integration (arbitrary reference: defl_raw[0]=0,
    # slope[0]=0 -- physically meaningless until the BCs below fix it up)
    slope = [0.0] * n
    for i in range(1, n):
        dx = xs[i] - xs[i - 1]
        slope[i] = slope[i - 1] + 0.5 * (curv[i] + curv[i - 1]) * dx
    defl_raw = [0.0] * n
    for i in range(1, n):
        dx = xs[i] - xs[i - 1]
        defl_raw[i] = defl_raw[i - 1] + 0.5 * (slope[i] + slope[i - 1]) * dx

    def interp(x_target):
        if x_target <= xs[0]:
            return defl_raw[0]
        if x_target >= xs[-1]:
            return defl_raw[-1]
        i = int(x_target / L * (n - 1))
        i = max(0, min(i, n - 2))
        t = (x_target - xs[i]) / (xs[i + 1] - xs[i])
        return defl_raw[i] + t * (defl_raw[i + 1] - defl_raw[i])

    # v(x) = defl_raw(x) + C1*x + C2; solve C1, C2 from v(xA)=v(xB)=0
    dA, dB = interp(xA), interp(xB)
    C1 = (dA - dB) / (xB - xA)
    C2 = -dA - C1 * xA
    v = [defl_raw[i] + C1 * xs[i] + C2 for i in range(n)]
    return xs, v


# ─────────────────────────────────────────────────────────────────────────
# 5. Vierendeel check at each opening
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class StationResult:
    x: float
    V_top: float
    V_bot: float
    Mv_top: float
    Mv_bot: float
    stress_top: float
    stress_bot: float
    shear_stress_top: float
    shear_stress_bot: float
    util_top: float
    util_bot: float
    warning: str = None


def analyze_opening(beam: BeamConfig, opening: OpeningInstance, n_stations=9):
    """Vierendeel check across one opening. The point of contraflexure of
    each tee's local (secondary) bending is taken at the opening's
    geometric mid-length -- the standard simplifying assumption used for
    this check family (e.g. AISC Design Guide 31 methodology; SCI P355) --
    while the *net section* used at every station is computed exactly
    from the actual polygon, so asymmetric/irregular openings are handled
    by station-by-station evaluation rather than a single shape-specific
    formula. Returns per-station results plus the governing (max
    utilization) station.
    """
    sec, mat = beam.section, beam.material
    x0, x1 = opening.x_span()
    x_mid = (x0 + x1) / 2.0
    eps = (x1 - x0) * 1e-3 if x1 > x0 else 1e-3
    stations = [x0 + eps + i * (x1 - x0 - 2 * eps) / (n_stations - 1) for i in range(n_stations)] if n_stations > 1 else [x_mid]
    verts_abs = opening.vertices_abs(sec.d)

    results = []
    for x in stations:
        span = polygon_y_span_at_x(verts_abs, x)
        if span is None:
            continue
        y_bot, y_top = span
        net = net_section_at(sec, y_bot, y_top)
        top, bot = net['top'], net['bottom']
        V, M = global_V_M(beam, x)
        Itot = top.I + bot.I
        ratio_top = top.I / Itot if Itot > 1e-9 else 0.5
        V_top, V_bot = V * ratio_top, V * (1 - ratio_top)
        lever = abs(x - x_mid)
        Mv_top, Mv_bot = V_top * lever, V_bot * lever

        dist_centroids = top.y_bar - bot.y_bar
        F_axial = M / dist_centroids if abs(dist_centroids) > 1e-6 else 0.0

        s_top = abs(F_axial) / max(top.A, 1e-6) + abs(Mv_top) / max(top.S_hole, 1e-6)
        s_bot = abs(F_axial) / max(bot.A, 1e-6) + abs(Mv_bot) / max(bot.S_hole, 1e-6)
        tau_top = abs(V_top) / max(sec.tw * top.h, 1e-6)
        tau_bot = abs(V_bot) / max(sec.tw * bot.h, 1e-6)

        util_top = math.sqrt(s_top ** 2 + 3 * tau_top ** 2) / mat.Fy
        util_bot = math.sqrt(s_bot ** 2 + 3 * tau_bot ** 2) / mat.Fy

        results.append(StationResult(x, V_top, V_bot, Mv_top, Mv_bot, s_top, s_bot,
                                      tau_top, tau_bot, util_top, util_bot, net['warning']))

    if not results:
        return {'opening': opening, 'stations': [], 'governing': None}
    governing = max(results, key=lambda r: max(r.util_top, r.util_bot))
    return {'opening': opening, 'stations': results, 'governing': governing}


# ─────────────────────────────────────────────────────────────────────────
# 6. Web-post shear / buckling check between adjacent openings
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class WebPostResult:
    x_left: float
    x_right: float
    width: float
    tau_demand: float
    Fcr: float
    util: float
    warning: str = None


def analyze_webpost(beam: BeamConfig, opening_a: OpeningInstance, opening_b: OpeningInstance, n_probe=5):
    """Post between two adjacent openings (a to the left of b). Uses a
    generalized elastic plate-buckling-in-shear check (Timoshenko &
    Gere, 'Theory of Elastic Stability', simply-supported plate in shear:
    k = 5.34 + 4*(w/h)^2 for w<=h) applied to the clear web-post panel,
    rather than a shape-specific empirical curve -- see MANIFESTO for why
    this generalization was chosen over the circular/hexagonal-specific
    SCI P355 curves, and its (conservative-leaning, not code-calibrated)
    status."""
    sec, mat = beam.section, beam.material
    _, xa1 = opening_a.x_span()
    xb0, _ = opening_b.x_span()
    width = xb0 - xa1
    h = sec.d - 2 * sec.tf
    warning = None
    if width <= 0:
        return WebPostResult(xa1, xb0, width, 0.0, 0.0, float('inf'),
                              'openings overlap or touch -- no web post remains')

    # peak shear demand on the post: sample V(x) at a few points across
    # the post width and take the largest magnitude.
    xs = [xa1 + i * width / (n_probe - 1) for i in range(n_probe)] if n_probe > 1 else [(xa1 + xb0) / 2.0]
    Vmax = max(abs(global_V_M(beam, x)[0]) for x in xs)
    tau_demand = Vmax / (width * sec.tw)

    aspect = width / h if h > 0 else 1.0
    k = 5.34 + 4.0 * aspect ** 2 if aspect <= 1.0 else 4.0 + 5.34 * aspect ** 2
    Fcr_elastic = k * (math.pi ** 2 * mat.E) / (12.0 * (1 - 0.3 ** 2)) * (sec.tw / width) ** 2
    Fcr = min(Fcr_elastic, mat.Fy / math.sqrt(3))  # cap at shear yield
    util = tau_demand / Fcr if Fcr > 1e-9 else float('inf')
    if aspect < 0.25:
        warning = 'web post very narrow (width < 0.25*web depth) -- result is a low-confidence extrapolation, verify by other means'
    return WebPostResult(xa1, xb0, width, tau_demand, Fcr, util, warning)


# ─────────────────────────────────────────────────────────────────────────
# 7. Combined bending + torsion check, with doubler-plate sizing
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class CombinedResult:
    x: float
    sigma_bending: float
    tau_shear: float
    tau_torsion: float
    util: float
    doubler_t: float   # 0 if not required
    doubler_ok: bool
    note: str = ''


def _combined_util(section, mat: Material, M, V, T, extra_tw=0.0):
    """Combined bending + shear + torsion utilization. Shear/torsion terms
    require the section to expose `Aweb`/`J` (RolledSection and
    BuiltUpDoubleChannelSection both do); a section without them (e.g.
    CustomProfileSection) gets a bending-only check, clearly flagged via
    the returned `shear_torsion_available` flag rather than silently
    treating an unknown shear/torsion demand as zero risk.

    `extra_tw` (RolledSection doubler-plate sizing only) adds thickness
    to the web for shear-area/torsion-constant purposes; for section
    types where "the web" isn't a single well-defined element (anything
    other than RolledSection), `extra_tw` is ignored -- doubler-plate
    reinforcement sizing only makes sense for RolledSection here (see
    `analyze_combined`)."""
    sigma = abs(M) / section.S
    has_shear_torsion = hasattr(section, 'Aweb') and hasattr(section, 'J') and hasattr(section, 'd')
    if not has_shear_torsion:
        util = sigma / mat.Fy
        return util, sigma, 0.0, 0.0, False

    if isinstance(section, RolledSection) and extra_tw:
        sec_tw = section.tw + extra_tw
        Aweb = (section.d - 2 * section.tf) * sec_tw
        J = (2 * section.bf * section.tf ** 3 + (section.d - 2 * section.tf) * sec_tw ** 3) / 3.0
        t_max = max(section.tf, sec_tw)
    else:
        Aweb, J = section.Aweb, section.J
        t_max = max(getattr(section, 'tf', section.d / 20.0), getattr(section, 'tw', section.d / 40.0))
    tau_v = abs(V) / max(Aweb, 1e-6)
    tau_t = abs(T) * t_max / max(J, 1e-6)
    tau_total = tau_v + tau_t
    util = math.sqrt(sigma ** 2 + 3 * tau_total ** 2) / mat.Fy
    return util, sigma, tau_v, tau_t, True


def analyze_combined(beam: BeamConfig, x, max_doubler=25.0, step=2.0):
    """Combined bending + torsion check at station x (typically the
    Vierendeel-governing station, or the location of maximum torque).
    St. Venant (uniform) torsion only -- see MANIFESTO limitations
    regarding warping/bimoment effects. If the base RolledSection is
    insufficient, sizes a web doubler plate (added to tw for shear-area
    and torsion-constant purposes) in `step` mm increments up to
    `max_doubler`, using an AISC-360-H3-style elastic von-Mises-type
    interaction as the acceptance criterion. Doubler-plate reinforcement
    is only attempted for a RolledSection -- other section types that
    fail this check are reported as inadequate without a reinforcement
    search, since "add thickness to the web" isn't a well-defined
    operation for a channel, built-up, or custom profile."""
    sec, mat = beam.section, beam.material
    V, M = global_V_M(beam, x)
    T = global_T(beam, x)
    util, sigma, tau_v, tau_t, has_st = _combined_util(sec, mat, M, V, T)
    note_suffix = '' if has_st else ' (shear/torsion not evaluated -- section type has no defined web/torsion property)'
    if util <= 1.0:
        return CombinedResult(x, sigma, tau_v, tau_t, util, 0.0, True, 'section adequate without reinforcement' + note_suffix)

    if not isinstance(sec, RolledSection):
        return CombinedResult(x, sigma, tau_v, tau_t, util, 0.0, False,
                               f'section inadequate (util={util:.2f}); automatic reinforcement '
                               'sizing is only available for a RolledSection' + note_suffix)

    t = step
    while t <= max_doubler:
        util2, sigma2, tau_v2, tau_t2, _ = _combined_util(sec, mat, M, V, T, extra_tw=t)
        if util2 <= 1.0:
            return CombinedResult(x, sigma2, tau_v2, tau_t2, util2, t, True,
                                   f'doubler plate, t={t:.0f} mm, brings combined utilization to {util2:.2f}')
        t += step
    return CombinedResult(x, sigma, tau_v, tau_t, util, max_doubler, False,
                           f'even a {max_doubler:.0f} mm doubler plate is insufficient (util={util:.2f}) -- '
                           'reconsider section size or opening layout at this station')


# ─────────────────────────────────────────────────────────────────────────
# 8. Top-level orchestrator
# ─────────────────────────────────────────────────────────────────────────

def analyze_beam(beam: BeamConfig, n_stations_per_opening=9):
    """Run every check and assemble a full report. Returns a dict with
    'openings' (per-opening Vierendeel results), 'webposts' (per-gap
    results), 'combined' (combined check at the governing station),
    'governing_opening', 'governing_webpost', and 'reactions'."""
    ordered = sorted(beam.openings, key=lambda o: o.x_center)

    opening_reports = [analyze_opening(beam, op, n_stations_per_opening) for op in ordered]
    valid_reports = [r for r in opening_reports if r['governing'] is not None]
    governing_opening = max(valid_reports, key=lambda r: max(r['governing'].util_top, r['governing'].util_bot)) \
        if valid_reports else None

    webpost_reports = [analyze_webpost(beam, ordered[i], ordered[i + 1]) for i in range(len(ordered) - 1)]
    governing_webpost = max(webpost_reports, key=lambda w: w.util) if webpost_reports else None

    if governing_opening is not None:
        x_check = governing_opening['governing'].x
    else:
        x_check = (beam.supports[0] + beam.supports[1]) / 2.0
    combined = analyze_combined(beam, x_check)

    return {
        'reactions': reactions(beam),
        'openings': opening_reports,
        'webposts': webpost_reports,
        'governing_opening': governing_opening,
        'governing_webpost': governing_webpost,
        'combined': combined,
    }
