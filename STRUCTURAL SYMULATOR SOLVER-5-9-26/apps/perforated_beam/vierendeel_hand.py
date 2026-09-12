"""
vierendeel_hand.py — the rectangular-equivalent Vierendeel hand method,
2026-09-10.

WHY A SECOND METHOD EXISTS. `perforated_beam_math.analyze_opening`
evaluates the Vierendeel check at nine stations across each opening,
using the REAL net section at each one. For a circular hole that is the
more faithful calculation, and it is the tab's default. But it is not
the calculation a hand-written report of the same beam contains, and on
the 50.4 m box girder the two differ by a factor of about four. A user
holding both documents cannot tell which is wrong, and the honest answer
-- neither -- is only convincing if the tab can produce BOTH numbers.

WHAT THE HAND METHOD IS. The classical closed-form check, as it appears
in the reference report for this beam and in the same shape in most
cellular-beam hand calculations:

    d_t   = (d - D_h) / 2                 tee depth AT THE HOLE CENTRE
    V_leg = |V| / (2 * n_web)             shear split evenly over the legs
    M_leg = V_leg * D_h / 2               lever = HALF THE OPENING WIDTH
    S_leg = t_w * d_t^2 / 6               the WEB STUB alone
    f_ax  = |M| * y_te / I_net            axial part, from global bending
    check   f_ax + f_loc <= phi * F_y

WHERE THE FACTOR OF FOUR COMES FROM, precisely, because this is the
question the method exists to answer. Two of its assumptions are exact
for a RECTANGULAR opening and pessimistic for a circular one:

  1. THE LEVER AND THE TEE DEPTH ARE TAKEN AT DIFFERENT PLACES. `d_t` is
     the tee at the hole's CENTRE, where the hole is deepest; `D_h/2` is
     the distance out to the hole's EDGE. In a rectangle both hold at
     once, because the tee depth does not change across the opening. In
     a circle they never do: at the centre the lever is zero, and at the
     edge the tee is the full half-depth of the section. The station
     scan pairs each lever with the tee that actually exists there, and
     finds its worst combination part-way out.

  2. THE FLANGE IS THROWN AWAY. `S_leg = t_w * d_t^2 / 6` is the modulus
     of a bare rectangular web stub. The real tee is that stub PLUS the
     flange it hangs from, which is where nearly all of its bending
     resistance lives.

Both are conservative, so the hand method is a safe upper bound on the
demand rather than an error. Neither is a substitute for a shell model
at one opening, and the report says so.

WHAT THIS MODULE DOES NOT DO. It does not check the tee's local
buckling, and for D_h/d beyond about 0.7 -- 0.75 on this beam -- that is
very likely the real governing limit state for both methods. It reports
the hole-depth ratio so the reader can see when they are outside the
range either method was calibrated in.
"""
import math

import cirsoc_301 as cirsoc
from apps.perforated_beam import general_net_section as gns
from apps.perforated_beam import section_shapes as shapes
from apps.perforated_beam import section_plastic as sp


class HandResult:
    """One opening, checked the reference report's way."""

    def __init__(self, opening, V, M, d, Dh, W, dt, tw, n_web, I_net, y_net,
                 f_ax, f_loc, util, phi_Fy, warning=''):
        self.opening = opening
        self.V = V
        self.M = M
        self.d = d
        self.Dh = Dh
        self.W = W
        self.dt = dt
        self.tw = tw
        self.n_web = n_web
        self.I_net = I_net
        self.y_net = y_net
        self.f_ax = f_ax
        self.f_loc = f_loc
        self.util = util
        self.phi_Fy = phi_Fy
        self.warning = warning

    @property
    def V_leg(self):
        return abs(self.V) / max(2 * self.n_web, 1)

    @property
    def M_leg(self):
        return self.V_leg * self.W / 2.0

    @property
    def S_leg(self):
        return self.tw * self.dt ** 2 / 6.0

    @property
    def depth_ratio(self):
        return self.Dh / max(self.d, 1e-9)

    def describe(self):
        where = f'{self.opening.label} at {self.opening.x_center / 1000:.1f} m'
        return (f'{where}: f_ax={self.f_ax:.1f} + f_loc={self.f_loc:.1f} = '
                f'{self.f_ax + self.f_loc:.1f} MPa vs {self.phi_Fy:.1f} MPa '
                f'-> util {self.util:.2f}')

    def working(self):
        """The intermediate numbers, so the reader can tick this off
        against a hand calculation line by line."""
        return [
            f'  d_t   = (d - D_h)/2 = ({self.d:.0f} - {self.Dh:.0f})/2 = {self.dt:.1f} mm',
            f'  V_leg = |V|/(2*{self.n_web}) = {abs(self.V) / 1000.0:.1f}/{2 * self.n_web} '
            f'= {self.V_leg / 1000.0:.1f} kN',
            f'  M_leg = V_leg * D_h/2 = {self.V_leg / 1000.0:.1f} kN * {self.Dh / 2000.0:.3f} m '
            f'= {self.M_leg / 1e6:.1f} kN.m',
            f'  S_leg = t_w*d_t^2/6 = {self.tw:.1f}*{self.dt:.0f}^2/6 = {self.S_leg:.0f} mm3',
            f'  f_loc = M_leg/S_leg = {self.f_loc:.1f} MPa',
            f'  f_ax  = |M|*y_te/I_net = {abs(self.M) / 1e6:.1f} kN.m * {self.y_net:.1f} mm '
            f'/ {self.I_net:.4g} mm4 = {self.f_ax:.1f} MPa',
        ]


def _web_geometry(section, y_mid, y_tee):
    """(n_web, t_w) for the legs that span the opening.

    The webs are IDENTIFIED at mid-depth, where a beam section has
    nothing but webs and the count is unambiguous -- the same scan
    Chapter G's shear area uses, so "what counts as a web" has one
    definition in this app rather than two.

    They are MEASURED at `y_tee`, the mid-height of the tee, because that
    is the material the Vierendeel leg actually bends. The two heights
    differ whenever anything thickens the stub without thickening the web
    at the hole -- which is precisely what a doubler ring does. Measuring
    at mid-depth instead reads the bare thickness however thick the ring
    is, and a ring then appears to do nothing at all.

    The THINNEST leg is returned, because each one bends on its own and
    the weakest governs."""
    pieces = shapes.section_pieces(section)
    at_mid = sp.material_runs_at(section, y_mid, pieces)
    if not at_mid:
        return 0, 0.0
    at_tee = sp.material_runs_at(section, y_tee, pieces)
    widths = []
    for a, b in at_mid:
        centre = 0.5 * (a + b)
        # The run at the tee that this web's centre-line falls inside. A
        # ring sits directly on the web's face, so the two merge into one
        # wider run and the centre-line still lands in it.
        here = next(((c, d) for c, d in at_tee if c - 1e-9 <= centre <= d + 1e-9), None)
        widths.append((here[1] - here[0]) if here else (b - a))
    return len(at_mid), min(widths)


def check_opening(beam, opening, section=None, code=None):
    """One opening by the hand method. Returns a HandResult, or None when
    the geometry gives it nothing to work with."""
    import apps.perforated_beam.perforated_beam_math as pbm

    sec = section if section is not None else beam.section
    ext = shapes.section_extents(shapes.section_pieces(sec))
    if ext is None:
        return None
    d = ext[3] - ext[1]

    ys = [y for _x, y in opening.vertices_local]
    xs = [x for x, _y in opening.vertices_local]
    Dh = max(ys) - min(ys)
    W = max(xs) - min(xs)
    dt = (d - Dh) / 2.0
    if dt <= 1e-6:
        return None

    y_mid = 0.5 * (ext[1] + ext[3])
    # Mid-height of the top tee, in the section's own frame.
    y_tee = ext[3] - dt / 2.0
    n_web, tw = _web_geometry(sec, y_mid, y_tee)
    if n_web <= 0 or tw <= 1e-9:
        return None

    # Net section at the WIDEST point of the hole -- the station the hand
    # method is written about.
    verts_abs = opening.vertices_abs(sec.d)
    span = pbm.polygon_y_span_at_x(verts_abs, opening.x_center)
    if span is None:
        return None
    y_bot, y_top = span
    net = pbm.net_section_general(sec, y_bot, y_top)
    top, bot = net['top'], net['bottom']
    # Net centroid measured from the bottom fibre, the frame the tee
    # properties already use.
    A_n = top.A + bot.A
    y_n = (top.A * top.y_bar + bot.A * bot.y_bar) / max(A_n, 1e-9)
    I_net = (top.I + top.A * (top.y_bar - y_n) ** 2
             + bot.I + bot.A * (bot.y_bar - y_n) ** 2)

    V, M = pbm.global_V_M(beam, opening.x_center)

    # The web stub's own centroid, top and bottom, in the same frame.
    y_stub_top = d - dt / 2.0
    y_stub_bot = dt / 2.0
    lever = max(abs(y_stub_top - y_n), abs(y_n - y_stub_bot))
    f_ax = abs(M) * lever / max(I_net, 1e-9)

    V_leg = abs(V) / max(2 * n_web, 1)
    M_leg = V_leg * W / 2.0
    S_leg = tw * dt ** 2 / 6.0
    f_loc = M_leg / max(S_leg, 1e-9)

    phi_Fy = cirsoc.PHI_NORMAL * beam.material.Fy
    util = (f_ax + f_loc) / max(phi_Fy, 1e-9)

    warning = ''
    if Dh / max(d, 1e-9) > 0.70:
        warning = (f'D_h/d = {Dh / d:.2f} is beyond the ~0.70 either method is '
                   'normally used within; local buckling of the tee, which neither '
                   'checks, is likely to govern before these stresses do')

    return HandResult(opening, V, M, d, Dh, W, dt, tw, n_web, I_net, lever,
                      f_ax, f_loc, util, phi_Fy, warning)


def check_all(beam, section=None):
    """Every opening, in the beam's own order. Openings the method cannot
    describe are dropped rather than reported as zero."""
    out = []
    for op in beam.openings:
        r = check_opening(beam, op, section=section)
        if r is not None:
            out.append(r)
    return out


def governing(results):
    return max(results, key=lambda r: r.util) if results else None


def required_thickness(beam, opening, section=None, t_now=None):
    """The uniform plate thickness the hand method asks for at this
    opening, mm.

    Exploits the linearity the reference report leans on: with every
    plate scaled by the same factor, A, I and S all scale with t while
    the centroid and every distance stay put, so both stress terms are
    inversely proportional to t. One evaluation therefore gives the whole
    curve -- t_req = t_now * util(t_now) -- and no sweep is needed.

    This is the number the reference's Section 7 table reports, and it is
    the one that says 36 mm where the tab's default method says 10 mm is
    already enough."""
    r = check_opening(beam, opening, section=section)
    if r is None:
        return None
    t = t_now if t_now is not None else r.tw
    return t * r.util
