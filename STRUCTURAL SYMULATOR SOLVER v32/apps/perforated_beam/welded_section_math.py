"""
welded_section_math.py — freely-placed multi-profile cross-sections and
their weld checks, for the Perforated Beam / Cellular Beam tab.

TWO THINGS LIVE HERE
--------------------
1. `CompoundSection`: two (or more) profiles combined into one
   cross-section with each piece placed at its OWN (dx, dy). This
   generalizes `BuiltUpDoubleSection`, which can only put two pieces side
   by side at equal height with a gap between them -- fine for a double
   channel, useless for a channel welded on top of an I-beam, a plate
   capping one flange, or any pair that is not vertically aligned.

   `BuiltUpDoubleSection` is deliberately left alone rather than
   generalized in place: its same-height assumption is what lets it add
   `I` directly with no parallel-axis term, and that shortcut is correct
   for what it models. This class carries the parallel-axis terms
   instead, which is the whole point of allowing a vertical offset.

2. `WeldLine` + `check_welds`: where the pieces are joined, and whether
   the joint can carry the longitudinal shear flow that holding them
   together requires. A built-up section only behaves as ONE section if
   the connection transfers q = V*Q/I between the pieces; without that
   check, the composite `I` computed above is a fiction.

UNITS: mm, N, MPa, N*mm -- identical to perforated_beam_math.py.

COORDINATE FRAME
----------------
`dx`/`dy` place each part's OWN CENTROID relative to a shared origin.
Centroid-relative rather than corner-relative because it is the only
reference every section type in this module already knows how to report
(`_y_fiber_distances` / `centroid`); a corner would have to be invented
per section type. The origin itself is arbitrary -- every property below
is referred to the COMBINED centroid, so shifting all parts together
changes nothing.

DESIGN BASIS FOR THE WELD CHECK -- READ THIS
--------------------------------------------
Capacity is phi * 0.60 * Fexx * throat per unit length, per CIRSOC 301
J.2.4 with Table J.2.5 (SOLDADURAS DE FILETE, corte en el área efectiva),
and the effective throat is 0.707*leg per J.2.2(a). See `cirsoc_301.py`,
which owns every factor.

**phi = 0.60, not 0.75.** CIRSOC 301 adopts AISC 360-2010 as its basis but
uses a lower resistance factor for fillet welds than AISC does (AISC
360-16 Table J2.5: phi = 0.75). Carrying the AISC number into a CIRSOC job
overstates every fillet weld by 25%. This module therefore defaults to
CIRSOC and offers `cirsoc_301.AISC_360` for when an AISC job is meant.

Minimum fillet size (Table J.2.4) and maximum fillet size (J.2.2(b)) are
now applied, because for a lightly loaded seam they GOVERN: the strength
requirement alone can return a leg of a fraction of a millimetre, which is
not a weld anybody can deposit. Note J.2.2(b)'s own exemption -- for
flange-to-web joints the Table J.2.4 minimums do not apply -- which is
reported rather than silently assumed either way.

NOT CHECKED HERE (each of these can govern a real joint):
  * base-metal rupture on the fusion face (CIRSOC sends this to J.4, and
    Table J.2.5 makes it the other half of the "lesser of" this module
    only computes one side of)
  * intermittent-weld spacing rules, and the slenderness-based connector
    spacing limits for built-up compression members
  * the transverse/eccentric component of a weld group -- this is a
    LONGITUDINAL shear-flow check only
  * the submerged-arc throat bonus of J.2.2(a), deliberately not taken
"""
import math
from dataclasses import dataclass, field

from apps.perforated_beam import perforated_beam_math as pbm
import cirsoc_301 as cirsoc
from apps.perforated_beam.perforated_beam_math import (
    _loop_integrals, _y_fiber_distances, _x_fiber_distances,
)


# ─────────────────────────────────────────────────────────────────────────
# 1. Placement
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class PlacedProfile:
    """One profile positioned inside a CompoundSection.

    `dx`, `dy` locate this profile's OWN centroid relative to the
    compound's arbitrary origin (see module docstring). `label` is
    cosmetic, used in weld and report output."""
    section: object
    dx: float = 0.0
    dy: float = 0.0
    label: str = ''

    def __post_init__(self):
        if isinstance(self.section, CompoundSection):
            raise ValueError(
                'A CompoundSection cannot be nested inside another one. Flatten the '
                'pieces into a single parts list instead -- nesting would make the '
                'weld geometry ambiguous, since an inner weld line would be expressed '
                "in the inner section's frame rather than the outer one's.")
        for attr in ('A', 'I'):
            if not hasattr(self.section, attr):
                raise ValueError(
                    f'Profile {self.label or "part"} does not expose `{attr}`, so it '
                    'cannot be combined into a compound section.')

    @property
    def name(self):
        return self.label or getattr(self.section, 'name', 'profile')

    @property
    def y_fibers(self):
        """(top, bottom) distances from this part's own centroid."""
        return _y_fiber_distances(self.section)

    @property
    def x_fibers(self):
        """(right, left) distances from this part's own centroid, or a
        symmetric fallback from the y-extent when the section exposes no
        weak-axis geometry (an `Iy`-less type). The fallback only ever
        feeds the bounding box used to decide which side of a weld line a
        part sits on, never a section property."""
        try:
            _, right, left = _x_fiber_distances(self.section)
            return right, left
        except AttributeError:
            top, bot = self.y_fibers
            half = max(top, bot)
            return half, half

    @property
    def y_extent(self):
        top, bot = self.y_fibers
        return self.dy - bot, self.dy + top

    @property
    def x_extent(self):
        right, left = self.x_fibers
        return self.dx - left, self.dx + right


# ─────────────────────────────────────────────────────────────────────────
# 2. Compound section
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class AssemblyDetail:
    """How the pieces of a compound section are actually joined -- which
    decides its torsion constant, and by an enormous margin.

    Two profiles butted together and welded ALONG THEIR FULL LENGTH form a
    CLOSED CELL, and a closed cell carries torque by Bredt shear flow:

        J = 4 * Am^2 * t / Lm          (closed, thin-walled)

    The same two profiles joined only by stitch plates at intervals do
    not: each acts as an OPEN section, and the pair sums to

        J = (1/3) * A * t^2            (open, uniform thickness)

    For the 1800x500x10 box those differ by a factor of about four
    THOUSAND. There is no defensible default between them, which is why
    this has to be declared rather than guessed: assuming 'closed' on a
    stitch-plated pair would overstate torsional stiffness by that factor,
    and assuming 'open' on a seam-welded box would throw away almost all
    of a real capacity.

    `J = (1/3) * A * t^2` deserves a word. For a thin-walled open section
    of uniform thickness the classical sum (1/3)*sum(b_i * t^3) needs the
    mean-line length, and for a section drawn as a closed polygon around a
    folded plate that length is simply A/t. Substituting gives the form
    above -- exact for uniform thickness, and needing only the one number
    the fabricator actually specifies.

    The closed-cell Am and Lm are taken from the section's outer extents
    less one plate thickness: exact for the rectangular cell this is meant
    for, approximate for anything else, and `note` says so."""
    kind: str = 'open'              # 'open' | 'closed'
    plate_thickness: float = 0.0    # mm; 0 = unknown, J stays unavailable
    label: str = ''

    def __post_init__(self):
        if self.kind not in ('open', 'closed'):
            raise ValueError(f"AssemblyDetail.kind must be 'open' or 'closed'; "
                              f'got {self.kind!r}.')
        if self.plate_thickness < 0:
            raise ValueError('plate_thickness cannot be negative.')

    @property
    def is_closed(self):
        return self.kind == 'closed'

    def torsion_constant(self, A, depth, width):
        """J for the assembled section, mm^4."""
        t = self.plate_thickness
        if t <= 0:
            raise AttributeError(
                'No plate thickness was declared for this assembly, so its torsion '
                'constant cannot be computed. Set AssemblyDetail(plate_thickness=...).')
        if not self.is_closed:
            return A * t * t / 3.0
        am = max(depth - t, 1e-6) * max(width - t, 1e-6)
        lm = 2.0 * (max(depth - t, 1e-6) + max(width - t, 1e-6))
        return 4.0 * am * am * t / lm

    def shear_area(self, section, depth):
        """Aw for the assembly: the summed thickness of the vertical walls
        over the clear depth. For the two-C box that is 2 x 10 x (1800 -
        2 x 10) = 35 600 mm^2, which no single `Aweb` attribute could have
        supplied."""
        t = self.plate_thickness
        if t <= 0:
            raise AttributeError(
                'No plate thickness was declared for this assembly, so its shear '
                'area cannot be computed. Set AssemblyDetail(plate_thickness=...).')
        from apps.perforated_beam import general_net_section as gns
        web_t = gns.material_width_at(section, depth / 2.0)
        return web_t * max(depth - 2 * t, 1e-6)

    def torsion_shear_stress(self, T, A, depth, width):
        """Peak torsional shear stress, MPa.

        The two cases need DIFFERENT formulas, not just different J:

          open   tau = T * t / J        (St Venant, peak at the surface)
          closed tau = T / (2 * Am * t) (Bredt, uniform round the cell)

        Using the open formula with a closed cell's huge J would report a
        near-zero stress; using the closed formula on an open section
        would invent a shear path that is not there. Both are wrong in the
        unconservative direction, so the detail selects the formula as
        well as the constant."""
        t = self.plate_thickness
        if t <= 0:
            raise AttributeError('No plate thickness declared for this assembly.')
        if not self.is_closed:
            return abs(T) * t / max(self.torsion_constant(A, depth, width), 1e-9)
        am = max(depth - t, 1e-6) * max(width - t, 1e-6)
        return abs(T) / (2.0 * am * t)

    def describe(self):
        if not self.is_closed:
            return ('open section (pieces joined at intervals only): '
                    'J = A*t^2/3, tau = T*t/J, torsion carried by each piece separately')
        return ('closed cell (continuous seam): J = 4*Am^2*t/Lm and tau = T/(2*Am*t) '
                'by Bredt, Am and Lm from the outer extents less one plate thickness')


@dataclass
class CompoundSection:
    """Several profiles welded into one cross-section, each freely placed.

    Section properties follow straight from the parallel-axis theorem
    about the COMBINED centroid, so an offset pair behaves correctly:
    stacking a channel on top of an I-beam raises the neutral axis, makes
    the shape asymmetric, and gives genuinely different S_top and S_bot --
    all of which `BuiltUpDoubleSection` would get wrong, because it
    assumes both pieces share a centroidal height and simply adds I.

    `Aweb` and `J` resolve only when EVERY part provides them, and
    correctly raise AttributeError otherwise, so `analyze_combined`'s
    duck-typing degrades to a bending-only check rather than inventing a
    shear area for a shape it cannot infer one from. `J` in particular is
    summed as an OPEN section: welding pieces into a closed box raises the
    true torsion constant enormously, and this class has no way to know
    whether the welds close a cell, so the open sum is the conservative
    answer -- never the unconservative one.

    THE COMPOSITE PROPERTIES ASSUME THE WELDS ACTUALLY HOLD. That is not
    decoration: if the joint slips, the pieces bend about their own
    separate axes and the real I collapses toward the sum of the
    individual I values, which for an offset pair is dramatically smaller
    than the composite value computed here. Run `check_welds` -- it is the
    check that entitles you to these numbers."""
    parts: list                                   # [PlacedProfile, ...]
    welds: list = field(default_factory=list)     # [WeldLine, ...]
    _name: str = None
    detail: AssemblyDetail = None                 # see AssemblyDetail; None -> J/Aweb
                                                  # stay unavailable, as before

    def __post_init__(self):
        if len(self.parts) < 2:
            raise ValueError(
                'A compound section needs at least 2 profiles. For a single profile, '
                'use that profile directly (or CustomProfileSection with holes if the '
                'intent was to cut voids out of it).')
        if self.A <= 0:
            raise ValueError('Compound section has zero or negative total area.')

    # ── identity ────────────────────────────────────────────────────────
    @property
    def name(self):
        if self._name:
            return self._name
        names = [p.name for p in self.parts]
        return ' + '.join(names) + ' (welded compound)'

    # ── first-order geometry ────────────────────────────────────────────
    @property
    def A(self):
        return sum(p.section.A for p in self.parts)

    @property
    def centroid(self):
        """(cx, cy) of the assembled section in the compound's own frame."""
        A = self.A
        cx = sum(p.section.A * p.dx for p in self.parts) / A
        cy = sum(p.section.A * p.dy for p in self.parts) / A
        return cx, cy

    @property
    def y_extent(self):
        return (min(p.y_extent[0] for p in self.parts),
                max(p.y_extent[1] for p in self.parts))

    @property
    def x_extent(self):
        return (min(p.x_extent[0] for p in self.parts),
                max(p.x_extent[1] for p in self.parts))

    @property
    def d(self):
        lo, hi = self.y_extent
        return hi - lo

    @property
    def width(self):
        lo, hi = self.x_extent
        return hi - lo

    # ── second-order geometry ───────────────────────────────────────────
    @property
    def I(self):
        """Strong-axis inertia about the combined centroid. The
        A*(dy - cy)^2 term is exactly what BuiltUpDoubleSection can drop
        and this class cannot."""
        _, cy = self.centroid
        return sum(p.section.I + p.section.A * (p.dy - cy) ** 2 for p in self.parts)

    @property
    def Iy(self):
        cx, _ = self.centroid
        total = 0.0
        for p in self.parts:
            Iy_own = getattr(p.section, 'Iy', None)
            if Iy_own is None:
                raise AttributeError(
                    f'Part "{p.name}" exposes no weak-axis inertia (Iy), so the '
                    'compound section cannot report one either.')
            total += Iy_own + p.section.A * (p.dx - cx) ** 2
        return total

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
        """Governing (smaller) section modulus, matching the convention
        CustomProfileSection and BuiltUpDoubleSection already use."""
        return min(self.S_top, self.S_bot)

    @property
    def Aweb(self):
        """From the declared assembly detail when there is one, otherwise
        the sum over the parts -- which resolves only if EVERY part has an
        `Aweb`, and correctly raises AttributeError when one does not, so
        `analyze_combined` degrades to a bending-only check rather than
        inventing a shear area."""
        if self.detail is not None:
            return self.detail.shear_area(self, self.d)
        return sum(p.section.Aweb for p in self.parts)

    @property
    def J(self):
        """Torsion constant.

        With an AssemblyDetail this reflects how the pieces are ACTUALLY
        joined -- a continuous seam makes a closed cell whose J is
        thousands of times the open-section value. Without one, the
        open-section sum over the parts, which resolves only if every part
        exposes a J.

        This is the single most detail-sensitive number in the whole
        section: see AssemblyDetail for why it must be declared."""
        if self.detail is not None:
            return self.detail.torsion_constant(self.A, self.d, self.width)
        return sum(p.section.J for p in self.parts)

    def torsion_shear_stress(self, T):
        """Peak torsional shear stress under torque T -- Bredt for a
        closed cell, St Venant for an open one. `_combined_util` prefers
        this over its own T*t_max/J whenever a section provides it, since
        only the section knows whether it has a closed cell."""
        if self.detail is None:
            raise AttributeError('No assembly detail declared for this section.')
        return self.detail.torsion_shear_stress(T, self.A, self.d, self.width)


# ─────────────────────────────────────────────────────────────────────────
# 3. Weld geometry
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class WeldCode:
    """Fillet-weld design basis, from CIRSOC 301-2018 Table J.2.5.

    `phi = 0.60` IS NOT A TYPO AND IS NOT THE AISC VALUE. AISC 360-16
    Table J2.5 gives phi = 0.75 for shear on the effective area of a
    fillet weld; CIRSOC 301, although it adopts AISC 360-2010 as its
    basis, uses 0.60. Running a CIRSOC job with the AISC factor overstates
    every fillet weld by 25%, so the default here is the CIRSOC one and
    `cirsoc_301.AISC_360` is available when an AISC job is actually
    intended.

    Fexx defaults to 482 MPa (an E70-class electrode). Set it to whatever
    the specified electrode gives -- it scales the capacity directly."""
    name: str = 'CIRSOC 301-2018 Tabla J.2.5'
    phi: float = cirsoc.PHI_WELD        # 0.60
    Fexx: float = 482.0                 # electrode classification strength, MPa
    throat_factor: float = 0.707        # J.2.2(a), equal-leg 45-degree fillet

    def capacity_per_mm(self, leg, n_lines=1):
        """Design shear strength of the joint per mm of length, N/mm:
        phi * 0.60 * Fexx * throat, per J.2.4 with Table J.2.5."""
        return self.phi * 0.60 * self.Fexx * self.throat_factor * leg * n_lines

    def leg_for(self, q, n_lines=1):
        """Fillet leg required on strength alone to carry shear flow `q`
        (N/mm). Table J.2.4's minimum size is applied separately by
        `check_welds`, because it is a fabrication rule rather than a
        strength one and the two answers are worth seeing apart."""
        denom = self.phi * 0.60 * self.Fexx * self.throat_factor * max(n_lines, 1)
        return abs(q) / max(denom, 1e-9)


DEFAULT_WELD_CODE = WeldCode()

# A measured run longer than this is not a plate -- it is the body of
# the section the joint lands on. 60 mm is comfortably above any plate
# this app sizes (the doubler search stops at 80 mm, and a ring that
# thick is already flagged as the wrong answer) and comfortably below
# a web depth.
DEEP_RUN_MM = 60.0


@dataclass
class WeldLine:
    """A welded joint, drawn as a straight line across the cross-section.

    `p1`/`p2` are (x, y) in the compound section's own frame. The line is
    treated as INFINITE for the purpose of splitting the section: what
    matters structurally is which material the joint has to hold on, and
    that is decided by the plane of the joint, not by where the drawn
    segment happens to stop.

    `side` picks which half is the held (detached) piece:
      'auto'      -- the smaller-area side, which is the attached piece in
                     essentially every real detail (a cap plate, a stiffener,
                     a channel welded onto a larger profile)
      'positive'  -- the side the line's left normal points to
      'negative'  -- the other one

    `leg` is the fillet leg size in mm; leave it 0 to have `check_welds`
    report the leg the shear flow REQUIRES instead of checking one you
    supplied. `n_lines` is how many parallel fillets make up this joint
    (2 for a plate welded down both edges, for instance).

    `t_thicker` / `t_thinner` are the plate thicknesses this joint
    connects, in mm. They are what CIRSOC's minimum (Table J.2.4) and
    maximum (J.2.2(b)) fillet sizes key off, and both default to 0
    meaning "not stated" -- in which case those two rules are reported as
    un-checkable rather than guessed at from the section geometry, since
    which two plates a drawn line actually joins is not something the
    geometry alone can settle.

    `flange_to_web` marks the J.2.2(b) exemption: for a flange-to-web
    joint the Table J.2.4 minimum does not apply and the weld need only
    develop the web."""
    p1: tuple
    p2: tuple
    leg: float = 0.0
    n_lines: int = 1
    side: str = 'auto'
    label: str = ''
    t_thicker: float = 0.0
    t_thinner: float = 0.0
    flange_to_web: bool = False

    def __post_init__(self):
        self.p1 = (float(self.p1[0]), float(self.p1[1]))
        self.p2 = (float(self.p2[0]), float(self.p2[1]))
        if self.side not in ('auto', 'positive', 'negative'):
            raise ValueError(f"WeldLine.side must be 'auto', 'positive' or "
                              f"'negative'; got {self.side!r}.")
        if self.length < 1e-9:
            raise ValueError(
                f'Weld line {self.label or ""} has zero length -- its two points '
                'coincide, so it defines no plane to split the section on.')
        if self.n_lines < 1:
            raise ValueError('A welded joint needs at least one weld line.')

    @property
    def length(self):
        return math.hypot(self.p2[0] - self.p1[0], self.p2[1] - self.p1[1])

    @property
    def normal(self):
        """Unit left-normal of p1->p2."""
        dx, dy = self.p2[0] - self.p1[0], self.p2[1] - self.p1[1]
        n = math.hypot(dx, dy)
        return (-dy / n, dx / n)

    def signed_distance(self, pt):
        nx, ny = self.normal
        return nx * (pt[0] - self.p1[0]) + ny * (pt[1] - self.p1[1])


def clip_polygon_halfplane(pts, weld, keep_positive):
    """Sutherland-Hodgman clip of a closed polygon against the half-plane
    on one side of a weld line.

    The clip region is a half-plane, which is convex, so this is exact for
    any simple subject polygon. A concave subject can come back with
    coincident edges running along the cut, but those contribute zero area
    and zero first moment, so the integrals taken from the result are
    still right -- which is all this is used for."""
    if not pts:
        return []
    sign = 1.0 if keep_positive else -1.0

    def inside(p):
        return sign * weld.signed_distance(p) >= 0.0

    out = []
    n = len(pts)
    for i in range(n):
        cur, nxt = pts[i], pts[(i + 1) % n]
        c_in, n_in = inside(cur), inside(nxt)
        if c_in:
            out.append(cur)
        if c_in != n_in:
            dc = sign * weld.signed_distance(cur)
            dn = sign * weld.signed_distance(nxt)
            denom = dc - dn
            if abs(denom) > 1e-15:
                t = dc / denom
                out.append((cur[0] + t * (nxt[0] - cur[0]),
                            cur[1] + t * (nxt[1] - cur[1])))
    return out


def _part_loops(part):
    """A drawn part's material as (outline, holes) in the COMPOUND frame,
    or None when the part is not polygon-defined.

    An OrientedSection deliberately returns None even when it wraps a
    drawn profile: it exposes no rotated outline, and silently welding
    against the UNrotated one would put the joint in the wrong place."""
    sec = part.section
    if not hasattr(sec, 'outline') or not hasattr(sec, 'centroid'):
        return None
    cx, cy = sec.centroid
    ox, oy = part.dx - cx, part.dy - cy
    outline = [(x + ox, y + oy) for x, y in sec.outline]
    holes = [[(x + ox, y + oy) for x, y in h] for h in getattr(sec, 'holes', [])]
    return outline, holes


def _loops_area_and_centroid(outline, holes):
    """(A, cx, cy) of one outline less its holes; (0, 0, 0) if empty."""
    if len(outline) < 3:
        return 0.0, 0.0, 0.0
    A, sx, sy, _, _ = _loop_integrals(outline)
    for h in holes:
        if len(h) < 3:
            continue
        hA, hsx, hsy, _, _ = _loop_integrals(h)
        A -= hA
        sx -= hsx
        sy -= hsy
    if A <= 1e-12:
        return 0.0, 0.0, 0.0
    return A, sy / A, sx / A


def _held_side_properties(section, weld, keep_positive):
    """(A, cy) of the material on one side of `weld`.

    Whole parts are summed directly. A part the line CUTS is clipped, when
    it is polygon-defined; when it is not (a catalog I-section, say), that
    is refused rather than approximated -- a bounding-box guess at how
    much of a rolled shape sits above an arbitrary cut would silently
    misreport Q, and Q is the entire content of this check."""
    A_tot = 0.0
    Ay_tot = 0.0
    for part in section.parts:
        x0, x1 = part.x_extent
        y0, y1 = part.y_extent
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        dists = [weld.signed_distance(c) for c in corners]
        sign = 1.0 if keep_positive else -1.0
        if all(sign * d >= -1e-9 for d in dists):          # wholly on the held side
            A_tot += part.section.A
            Ay_tot += part.section.A * part.dy
            continue
        if all(sign * d <= 1e-9 for d in dists):           # wholly on the other side
            continue
        loops = _part_loops(part)
        if loops is None:
            raise ValueError(
                f'Weld line {weld.label or ""} cuts through profile "{part.name}", '
                'which is not a drawn outline, so the area it separates cannot be '
                'computed. Put the weld at the joint BETWEEN two profiles, or model '
                'the cut piece as a drawn custom profile so its geometry is known.')
        outline, holes = loops
        clipped_out = clip_polygon_halfplane(outline, weld, keep_positive)
        clipped_holes = [clip_polygon_halfplane(h, weld, keep_positive) for h in holes]
        A, _, cy = _loops_area_and_centroid(clipped_out, clipped_holes)
        A_tot += A
        Ay_tot += A * cy
    if A_tot <= 1e-9:
        return 0.0, 0.0
    return A_tot, Ay_tot / A_tot


@dataclass
class WeldResult:
    label: str
    q: float                # longitudinal shear flow at the joint, N/mm
    Q: float                # first moment of the held area about the NA, mm^3
    A_held: float
    leg_provided: float
    leg_required: float     # on STRENGTH alone (Table J.2.5)
    n_lines: int
    capacity: float         # N/mm, 0 when no leg was supplied
    util: float             # 0.0 when no leg was supplied
    ok: bool
    note: str = ''
    leg_min_code: float = 0.0    # Table J.2.4 minimum; 0 = not checkable
    leg_max_code: float = 0.0    # J.2.2(b) maximum;    0 = not checkable
    leg_to_specify: float = 0.0  # what to actually detail: max(strength, minimum)
    size_governed_by: str = ''
    size_warning: str = ''
    t_thicker: float = 0.0       # the thicknesses the size rules were read
    t_thinner: float = 0.0       # against, stated or measured
    t_measured: bool = False     # True when they came from the geometry


@dataclass
class WeldedProfile:
    """One drawn profile that carries its own weld lines -- the
    single-piece counterpart to CompoundSection.

    A weld does not require two separate profiles: a stiffener or a doubler
    welded onto a shape drawn as ONE outline is welded just the same, and
    the shear flow across that joint is the same V*Q/I. This wrapper exists
    so `check_welds` sees the same (parts, welds, I, centroid) interface in
    both cases, instead of growing a second code path.

    The single part is placed in the profile's OWN coordinate frame, so
    weld lines drawn on the sketch land where they were drawn."""
    section: object
    welds: list = field(default_factory=list)

    @property
    def parts(self):
        cx, cy = self.section.centroid
        return [PlacedProfile(self.section, dx=cx, dy=cy,
                              label=getattr(self.section, 'name', 'profile'))]

    @property
    def name(self):
        return getattr(self.section, 'name', 'profile')

    def __getattr__(self, item):
        # Delegate every section property (A, I, Iy, d, S, S_top, S_bot,
        # centroid, y_extent, ...) to the wrapped profile. Only reached for
        # names not defined above, so `parts`/`welds`/`name` still win.
        if item.startswith('_'):
            raise AttributeError(item)
        return getattr(self.__dict__['section'], item)


def _symmetry_note(section, weld, q):
    """Why q came out zero, when it did. Lazy for the same reason as
    `_inferred_contact`."""
    try:
        from apps.perforated_beam import assembly_check as ac
        return ac.symmetry_note(section, weld, q)
    except Exception:
        return ''


def _inferred_contact(section, weld, label):
    """Plate thicknesses measured off the geometry, or None.

    LAZY IMPORT ON PURPOSE: assembly_check imports this module, so a
    top-level import here would be a cycle. Any failure is swallowed --
    a thickness this could not measure must leave the check exactly where
    it was before, reporting strength only, rather than taking the whole
    analysis down."""
    try:
        from apps.perforated_beam import assembly_check as ac
        return ac.weld_contact(section, weld, label=label)
    except Exception:
        return None


def check_welds(section, V, code=None, infer_thickness=True):
    """Longitudinal shear-flow check of every weld in a CompoundSection.

    q = V * Q / I, with Q the first moment about the combined neutral axis
    of the material the joint has to hold. This is the check that decides
    whether the section behaves as one piece at all -- see the
    CompoundSection docstring.

    `V` is the shear at the station of interest (N); the sign is
    irrelevant, so the magnitude is used. Returns a list of WeldResult.
    A weld with `leg = 0` is SIZED rather than checked: `leg_required` is
    reported and `ok` is True, because nothing has been claimed yet."""
    code = code or DEFAULT_WELD_CODE
    I = section.I
    _, cy = section.centroid
    out = []
    for i, weld in enumerate(section.welds, 1):
        label = weld.label or f'W{i}'
        # Both sides are always evaluated, even when `side` is explicit:
        # if either comes back empty the line does not actually separate
        # anything, and a weld that holds nothing is far more likely to be
        # a misplaced line than a real detail. Reporting q = 0 without
        # saying so would hide that.
        A_pos, cy_pos = _held_side_properties(section, weld, True)
        A_neg, cy_neg = _held_side_properties(section, weld, False)
        if min(A_pos, A_neg) <= 1e-9:
            out.append(WeldResult(label, 0.0, 0.0, 0.0, weld.leg, 0.0,
                                  weld.n_lines, 0.0, 0.0, True,
                                  'this line does not cut the section, so it separates '
                                  'nothing to hold - check the weld position'))
            continue
        if weld.side == 'auto':
            if A_pos <= A_neg:
                A_held, y_held, chosen = A_pos, cy_pos, 'positive'
            else:
                A_held, y_held, chosen = A_neg, cy_neg, 'negative'
            note = f'held side chosen automatically ({chosen}, the smaller area)'
        else:
            keep = weld.side == 'positive'
            A_held, y_held = (A_pos, cy_pos) if keep else (A_neg, cy_neg)
            note = f'held side = {weld.side}'
        Q = A_held * abs(y_held - cy)
        q = abs(V) * Q / max(I, 1e-9)
        leg_req = code.leg_for(q, weld.n_lines)

        # Fabrication limits (Table J.2.4 / J.2.2(b)). The stated
        # thicknesses win when there are any; otherwise they are MEASURED
        # off the geometry by walking out from the line along its own
        # normal. Leaving them blank used to mean the minimum could not be
        # applied at all, which on a seam carrying no shear flow left
        # "0.0 mm" as the entire answer.
        t_thicker, t_thinner, measured = weld.t_thicker, weld.t_thinner, False
        if infer_thickness and t_thicker <= 0:
            contact = _inferred_contact(section, weld, label)
            if contact is not None and contact.found_both:
                t_thicker, t_thinner = contact.t_thicker, contact.t_thinner
                measured = True
        # The walk reports how far it travelled before leaving material,
        # which past a plate's far face is the body of the section: a cap
        # plate's weld reads 234 mm downward, straight through flange, web
        # and far flange. The J.2.4 lookup is unaffected (the table
        # saturates above 19 mm) but the number must not be printed as a
        # plate thickness.
        deep = measured and t_thicker > DEEP_RUN_MM
        leg_min = cirsoc.min_fillet_leg(t_thicker) if t_thicker > 0 else 0.0
        leg_max = cirsoc.max_fillet_leg(t_thinner) if t_thinner > 0 else 0.0
        min_applies = leg_min > 0 and not weld.flange_to_web
        leg_specify = max(leg_req, leg_min) if min_applies else leg_req
        if min_applies and leg_min > leg_req:
            governed = 'minimum size, Tabla J.2.4 (strength alone would allow less)'
        elif leg_min > 0 and weld.flange_to_web:
            governed = 'strength, Tabla J.2.5 (Tabla J.2.4 minimum waived, J.2.2(b))'
        else:
            governed = 'strength, Tabla J.2.5'

        warnings = []
        if leg_max > 0 and leg_specify > leg_max + 1e-9:
            warnings.append(
                f'the {leg_specify:.1f} mm leg needed exceeds the {leg_max:.1f} mm maximum '
                f'for a {t_thinner:.0f} mm edge (J.2.2(b)) -- this joint cannot be made '
                'as a single fillet; use more weld lines, a thicker part, or a groove weld')
        if leg_specify > 0 and weld.length < cirsoc.min_effective_length(leg_specify):
            warnings.append(
                f'the joint is {weld.length:.0f} mm long, under the 4x leg minimum effective '
                f'length for a {leg_specify:.1f} mm fillet (J.2.2(b)); only '
                f'{weld.length / 4.0:.1f} mm of leg may be counted')
        if leg_min <= 0:
            warnings.append(
                'connected plate thicknesses could neither be stated nor measured from the '
                'geometry, so the Tabla J.2.4 minimum and the J.2.2(b) maximum could not be '
                'checked -- the leg shown is strength only')
        elif measured and deep:
            note += (f'; sits on a {t_thinner:.0f} mm part, measured from the geometry at '
                     'the line, and lands on the body of the section')
        elif measured:
            note += (f'; joins {t_thinner:.0f} mm to {t_thicker:.0f} mm, measured from the '
                     'geometry at the line')
        # The explainer fires when Q IS ZERO -- the held material's
        # centroid sitting at the section's own -- because that is what it
        # claims. Triggering on a small required leg instead put "q is
        # essentially zero" under a joint carrying 95 N/mm, since a fillet
        # is strong enough per millimetre that almost every longitudinal
        # seam needs well under a millimetre of it.
        depth = max(getattr(section, 'd', 0.0) or 0.0, 1.0)
        # 1% of the depth. The two cases this must separate are not close:
        # a symmetric box seam lands within about 0.1% of the centroid, a
        # cap plate about 40% away. Anything in between is a section this
        # note has no business claiming anything about.
        if abs(y_held - cy) < 1e-2 * depth:
            why = _symmetry_note(section, weld, q)
            if why:
                warnings.append(why)

        if weld.leg > 0:
            cap = code.capacity_per_mm(weld.leg, weld.n_lines)
            util = q / cap if cap > 1e-12 else float('inf')
            # A leg sized to exactly the requirement must not read as a
            # failure on a floating-point last bit.
            ok = util <= 1.0 + 1e-9
            if not ok:
                note += f'; needs a {leg_req:.1f} mm leg on strength, {weld.leg:.1f} mm provided'
            if min_applies and weld.leg < leg_min - 1e-9:
                ok = False
                note += (f'; {weld.leg:.1f} mm is below the {leg_min:.0f} mm minimum fillet '
                         f'for a {t_thicker:.0f} mm part (Tabla J.2.4)')
        else:
            cap, util, ok = 0.0, 0.0, True
            note += '; no leg supplied, so this is a sizing result, not a check'
        out.append(WeldResult(label, q, Q, A_held, weld.leg, leg_req,
                              weld.n_lines, cap, util, ok, note,
                              leg_min_code=leg_min, leg_max_code=leg_max,
                              leg_to_specify=leg_specify, size_governed_by=governed,
                              size_warning='; '.join(warnings),
                              t_thicker=t_thicker, t_thinner=t_thinner,
                              t_measured=measured))
    return out


def governing_weld(results):
    """The worst weld, by utilisation when any leg was supplied and by
    required leg otherwise."""
    if not results:
        return None
    if any(r.leg_provided > 0 for r in results):
        return max(results, key=lambda r: r.util)
    return max(results, key=lambda r: r.leg_required)
