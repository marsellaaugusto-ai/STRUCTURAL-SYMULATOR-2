"""Steel profile catalog for the Stereo tab.

Profiles are plain data: each entry stores dimensional inputs and computes
the section properties the solver needs (A, I, J, r_gyr).  The catalog
covers the most-used Argentine/European series (IPE, HEA, HEB, UPN) and
a starter set of hollow sections (round and square tubes).  Every dimension
is in mm; derived properties are returned in the STEREO TAB'S working
units (A in cm2, I/J in cm4, r_gyr in cm) by the helper that maps a
catalog entry into a member-property dict.

Materials carry Fy/Fu in MPa.  The two pre-built materials match the
CIRSOC 301 / AISC designations the rest of the app already uses.

    r_gyr IS THE MINOR PRINCIPAL RADIUS. That is the contract
    stereo_math documents ("weak-axis radius of gyration"), and it is the
    only radius a compression check may use, because a strut buckles about
    its weakest axis. Until 2026-09-30 every class here returned
    sqrt(Ix/A), the STRONG axis, which overstated buckling capacity by up
    to 26x for I-sections and 30x for channels (Euler load, which goes as
    r squared) -- a violation of the contract, not a choice. Angles were
    worse than the Ix/Iy pair could show: an angle buckles about its minor
    PRINCIPAL axis (v-v), which is not either geometric axis, so it is
    computed here from the exact geometry. Checked against EN 10056-1:
    L 50x5 gives r_v = 0.98 cm, the published value.

    c_mm IS THE EXTREME-FIBRE DISTANCE for bending about the axis of Ix,
    and every shape now has one. section_to_props used to look for it as
    `d` or `h`, which three classes spell `D`, `H` and `leg`, so tubes and
    angles never had one and bending fell back to a thin-round-tube guess
    that is 39% unsafe for an angle.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────
# 1. Section dataclasses
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class ISection:
    """Doubly-symmetric rolled I/H section.  All dimensions in mm."""
    name: str
    d: float       # total depth
    bf: float      # flange width
    tf: float      # flange thickness
    tw: float      # web thickness

    @property
    def A_mm2(self) -> float:
        return 2 * self.bf * self.tf + (self.d - 2 * self.tf) * self.tw

    @property
    def Ix_mm4(self) -> float:
        return (self.bf * self.d ** 3
                - (self.bf - self.tw) * (self.d - 2 * self.tf) ** 3) / 12.0

    @property
    def Iy_mm4(self) -> float:
        hw = self.d - 2 * self.tf
        return (2 * self.tf * self.bf ** 3 + hw * self.tw ** 3) / 12.0

    @property
    def J_mm4(self) -> float:
        hw = self.d - 2 * self.tf
        return (2 * self.bf * self.tf ** 3 + hw * self.tw ** 3) / 3.0

    @property
    def r_x_mm(self) -> float:
        """Strong-axis radius -- for reporting, never for buckling."""
        return math.sqrt(self.Ix_mm4 / self.A_mm2)

    @property
    def r_gyr_mm(self) -> float:
        """Minor principal radius: about the WEB axis, sqrt(Iy/A)."""
        return math.sqrt(self.Iy_mm4 / self.A_mm2)

    @property
    def c_mm(self) -> float:
        return self.d / 2.0


    # The weak axis, for a rigid joint's bending stiffness and check about it
    # (see section_to_props): the second moment and the distance to the
    # extreme fibre, the flange tip, half the flange width.
    @property
    def Iw_mm4(self) -> float:
        return self.Iy_mm4

    @property
    def cw_mm(self) -> float:
        return self.bf / 2.0
    @property
    def shape(self) -> str:
        return 'I'


@dataclass
class ChannelSection:
    """UPN / C channel.  All dimensions in mm."""
    name: str
    d: float
    bf: float
    tf: float
    tw: float

    @property
    def A_mm2(self) -> float:
        return 2 * self.bf * self.tf + (self.d - 2 * self.tf) * self.tw

    @property
    def Ix_mm4(self) -> float:
        return (self.bf * self.d ** 3
                - (self.bf - self.tw) * (self.d - 2 * self.tf) ** 3) / 12.0

    @property
    def Iy_mm4(self) -> float:
        hw = self.d - 2 * self.tf
        return (2 * self.tf * self.bf ** 3 + hw * self.tw ** 3) / 12.0

    @property
    def J_mm4(self) -> float:
        hw = self.d - 2 * self.tf
        return (2 * self.bf * self.tf ** 3 + hw * self.tw ** 3) / 3.0

    @property
    def r_x_mm(self) -> float:
        """Strong-axis radius -- for reporting, never for buckling."""
        return math.sqrt(self.Ix_mm4 / self.A_mm2)

    @property
    def r_gyr_mm(self) -> float:
        """Minor principal radius, sqrt(Iy/A). The channel is symmetric
        about its strong axis, so x and y are its principal axes."""
        return math.sqrt(self.Iy_mm4 / self.A_mm2)

    @property
    def c_mm(self) -> float:
        return self.d / 2.0


    # The weak axis, for a rigid joint's bending stiffness and check about it
    # (see section_to_props): the second moment and the distance to the
    # extreme fibre, the whole flange width -- an upper bound on the distance from the weak axis to the toe, so S comes out low.
    @property
    def Iw_mm4(self) -> float:
        return self.Iy_mm4

    @property
    def cw_mm(self) -> float:
        return self.bf
    @property
    def shape(self) -> str:
        return 'C'


@dataclass
class RoundTube:
    """Circular hollow section (CHS).  All dimensions in mm."""
    name: str
    D: float       # outer diameter
    t: float       # wall thickness

    @property
    def A_mm2(self) -> float:
        ri = (self.D - 2 * self.t) / 2.0
        ro = self.D / 2.0
        return math.pi * (ro ** 2 - ri ** 2)

    @property
    def Ix_mm4(self) -> float:
        ri = (self.D - 2 * self.t) / 2.0
        ro = self.D / 2.0
        return math.pi * (ro ** 4 - ri ** 4) / 4.0

    @property
    def Iy_mm4(self) -> float:
        return self.Ix_mm4

    @property
    def J_mm4(self) -> float:
        ri = (self.D - 2 * self.t) / 2.0
        ro = self.D / 2.0
        return math.pi * (ro ** 4 - ri ** 4) / 2.0

    @property
    def r_x_mm(self) -> float:
        return math.sqrt(self.Ix_mm4 / self.A_mm2)

    @property
    def r_gyr_mm(self) -> float:
        """Every axis is principal and alike, so this was always right."""
        return math.sqrt(self.Ix_mm4 / self.A_mm2)

    @property
    def c_mm(self) -> float:
        # D, not d: this lookup is what section_to_props used to miss.
        return self.D / 2.0


    # The weak axis, for a rigid joint's bending stiffness and check about it
    # (see section_to_props): the second moment and the distance to the
    # extreme fibre, the same in every direction.
    @property
    def Iw_mm4(self) -> float:
        return self.Ix_mm4

    @property
    def cw_mm(self) -> float:
        return self.D / 2.0
    @property
    def shape(self) -> str:
        return 'CHS'


@dataclass
class RectTube:
    """Rectangular/square hollow section (RHS/SHS).  All dimensions in mm."""
    name: str
    H: float       # outer height
    B: float       # outer width
    t: float       # wall thickness

    @property
    def A_mm2(self) -> float:
        return 2 * self.t * (self.H + self.B - 2 * self.t)

    @property
    def Ix_mm4(self) -> float:
        return (self.B * self.H ** 3
                - (self.B - 2 * self.t) * (self.H - 2 * self.t) ** 3) / 12.0

    @property
    def Iy_mm4(self) -> float:
        return (self.H * self.B ** 3
                - (self.H - 2 * self.t) * (self.B - 2 * self.t) ** 3) / 12.0

    @property
    def J_mm4(self) -> float:
        h_m = self.H - self.t
        b_m = self.B - self.t
        return 2 * self.t * (h_m * b_m) ** 2 / (h_m + b_m)

    @property
    def r_x_mm(self) -> float:
        return math.sqrt(self.Ix_mm4 / self.A_mm2)

    @property
    def r_gyr_mm(self) -> float:
        """Minor principal radius. x and y are principal (double symmetry);
        min() rather than Iy because nothing guarantees H >= B in the table,
        and a square section has them equal."""
        return math.sqrt(min(self.Ix_mm4, self.Iy_mm4) / self.A_mm2)

    @property
    def c_mm(self) -> float:
        # Ix is about the axis parallel to B, so its fibres are H/2 out.
        return self.H / 2.0


    # The weak axis, for a rigid joint's bending stiffness and check about it
    # (see section_to_props): the second moment and the distance to the
    # extreme fibre, half the side that bends about the weaker axis.
    @property
    def Iw_mm4(self) -> float:
        return min(self.Ix_mm4, self.Iy_mm4)

    @property
    def cw_mm(self) -> float:
        return (self.B if self.Iy_mm4 <= self.Ix_mm4 else self.H) / 2.0
    @property
    def shape(self) -> str:
        return 'RHS'


@dataclass
class EqualAngle:
    """Equal-leg angle (L).  All dimensions in mm."""
    name: str
    leg: float     # leg length
    t: float       # thickness

    def _geometry(self):
        """(A, centroid from the heel, Ix, Ixy) about the centroid, exactly.

        The angle is two rectangles -- the full vertical leg, and the
        horizontal leg less the corner they share -- so every property
        follows from the parallel-axis theorem with nothing approximated.
        The previous closed-form Ix was 16% high (L 50x5: 13.09 cm4 against
        a published 11.00), and it is what the bending check used.
        """
        L, t = self.leg, self.t
        rects = ((0.0, t, 0.0, L), (t, L, 0.0, t))      # x0, x1, y0, y1
        A = sum((x1 - x0) * (y1 - y0) for x0, x1, y0, y1 in rects)
        cx = sum((x1 - x0) * (y1 - y0) * (x0 + x1) / 2.0
                 for x0, x1, y0, y1 in rects) / A
        cy = sum((x1 - x0) * (y1 - y0) * (y0 + y1) / 2.0
                 for x0, x1, y0, y1 in rects) / A
        Ix = Ixy = 0.0
        for x0, x1, y0, y1 in rects:
            b, h = x1 - x0, y1 - y0
            dx, dy = (x0 + x1) / 2.0 - cx, (y0 + y1) / 2.0 - cy
            Ix += b * h ** 3 / 12.0 + b * h * dy * dy
            Ixy += b * h * dx * dy
        return A, cy, Ix, Ixy

    @property
    def A_mm2(self) -> float:
        return self.t * (2 * self.leg - self.t)

    @property
    def Ix_mm4(self) -> float:
        """About the geometric axis parallel to one leg, through the centroid."""
        return self._geometry()[2]

    @property
    def Iy_mm4(self) -> float:
        # Equal legs: the two geometric axes are mirror images.
        return self.Ix_mm4

    @property
    def Iv_mm4(self) -> float:
        """The MINOR PRINCIPAL moment, about the v-v axis (at 45 degrees to
        the legs). Neither geometric axis is principal for an angle, so
        min(Ix, Iy) cannot find this -- it has to come from the product of
        inertia: I_v = (Ix + Iy)/2 - sqrt(((Ix - Iy)/2)^2 + Ixy^2)."""
        _A, _cy, Ix, Ixy = self._geometry()
        return Ix - abs(Ixy)          # Ix == Iy, so the root is just |Ixy|

    @property
    def J_mm4(self) -> float:
        return (2 * self.leg - self.t) * self.t ** 3 / 3.0

    @property
    def r_x_mm(self) -> float:
        return math.sqrt(self.Ix_mm4 / self.A_mm2)

    @property
    def r_gyr_mm(self) -> float:
        """Minor principal radius r_v -- about 0.64 of r_x for an equal
        angle, and the radius an angle strut actually buckles about.
        L 50x5 gives 0.98 cm, the EN 10056-1 value."""
        return math.sqrt(self.Iv_mm4 / self.A_mm2)

    @property
    def c_mm(self) -> float:
        """Far fibre from the centroidal x axis: the tip of the leg. The
        centroid sits near the heel, so this is most of the leg length --
        which is exactly what the old thin-tube fallback could not see."""
        _A, cy, _Ix, _Ixy = self._geometry()
        return self.leg - cy


    # The weak axis, for a rigid joint's bending stiffness and check about it
    # (see section_to_props): the second moment and the distance to the
    # extreme fibre, the leg tips, leg/sqrt(2) from the minor principal (v) axis.
    @property
    def Iw_mm4(self) -> float:
        return self.Iv_mm4

    @property
    def cw_mm(self) -> float:
        return self.leg / math.sqrt(2.0)
    @property
    def shape(self) -> str:
        return 'L'


# ─────────────────────────────────────────────────────────────────────────
# 2. Material
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class Material:
    name: str
    Fy: float      # yield stress, MPa
    Fu: float      # ultimate stress, MPa
    E: float = 200_000.0   # Young's modulus, MPa


STEEL_F24 = Material('F24 (CIRSOC) / A36', Fy=235.0, Fu=360.0)
STEEL_F36 = Material('F36 (CIRSOC) / A992', Fy=345.0, Fu=450.0)

MATERIALS: Dict[str, Material] = {
    m.name: m for m in [STEEL_F24, STEEL_F36]
}


# ─────────────────────────────────────────────────────────────────────────
# 3. Profile catalogs
# ─────────────────────────────────────────────────────────────────────────

_IPE: List[ISection] = [
    ISection('IPE 80',   80,  46,  5.2, 3.8),
    ISection('IPE 100', 100,  55,  5.7, 4.1),
    ISection('IPE 120', 120,  64,  6.3, 4.4),
    ISection('IPE 140', 140,  73,  6.9, 4.7),
    ISection('IPE 160', 160,  82,  7.4, 5.0),
    ISection('IPE 180', 180,  91,  8.0, 5.3),
    ISection('IPE 200', 200, 100,  8.5, 5.6),
    ISection('IPE 220', 220, 110,  9.2, 5.9),
    ISection('IPE 240', 240, 120,  9.8, 6.2),
    ISection('IPE 270', 270, 135, 10.2, 6.6),
    ISection('IPE 300', 300, 150, 10.7, 7.1),
    ISection('IPE 330', 330, 160, 11.5, 7.5),
    ISection('IPE 360', 360, 170, 12.7, 8.0),
    ISection('IPE 400', 400, 180, 13.5, 8.6),
    ISection('IPE 450', 450, 190, 14.6, 9.4),
    ISection('IPE 500', 500, 200, 16.0, 10.2),
    ISection('IPE 550', 550, 210, 17.2, 11.1),
    ISection('IPE 600', 600, 220, 19.0, 12.0),
]

_HEA: List[ISection] = [
    ISection('HEA 100', 96,  100,  8.0, 5.0),
    ISection('HEA 120', 114, 120,  8.0, 5.0),
    ISection('HEA 140', 133, 140,  8.5, 5.5),
    ISection('HEA 160', 152, 160,  9.0, 6.0),
    ISection('HEA 180', 171, 180,  9.5, 6.0),
    ISection('HEA 200', 190, 200, 10.0, 6.5),
    ISection('HEA 220', 210, 220, 11.0, 7.0),
    ISection('HEA 240', 230, 240, 12.0, 7.5),
    ISection('HEA 260', 250, 260, 12.5, 7.5),
    ISection('HEA 280', 270, 280, 13.0, 8.0),
    ISection('HEA 300', 290, 300, 14.0, 8.5),
    ISection('HEA 320', 310, 300, 15.5, 9.0),
    ISection('HEA 340', 330, 300, 16.5, 9.5),
    ISection('HEA 360', 350, 300, 17.5, 10.0),
    ISection('HEA 400', 390, 300, 19.0, 11.0),
    ISection('HEA 450', 440, 300, 21.0, 11.5),
    ISection('HEA 500', 490, 300, 23.0, 12.0),
]

_HEB: List[ISection] = [
    ISection('HEB 100', 100, 100, 10.0, 6.0),
    ISection('HEB 120', 120, 120, 11.0, 6.5),
    ISection('HEB 140', 140, 140, 12.0, 7.0),
    ISection('HEB 160', 160, 160, 13.0, 8.0),
    ISection('HEB 180', 180, 180, 14.0, 8.5),
    ISection('HEB 200', 200, 200, 15.0, 9.0),
    ISection('HEB 220', 220, 220, 16.0, 9.5),
    ISection('HEB 240', 240, 240, 17.0, 10.0),
    ISection('HEB 260', 260, 260, 17.5, 10.0),
    ISection('HEB 280', 280, 280, 18.0, 10.5),
    ISection('HEB 300', 300, 300, 19.0, 11.0),
    ISection('HEB 320', 320, 300, 20.5, 11.5),
    ISection('HEB 340', 340, 300, 21.5, 12.0),
    ISection('HEB 360', 360, 300, 22.5, 12.5),
    ISection('HEB 400', 400, 300, 24.0, 13.5),
    ISection('HEB 450', 450, 300, 26.0, 14.0),
    ISection('HEB 500', 500, 300, 28.0, 14.5),
]

_UPN: List[ChannelSection] = [
    ChannelSection('UPN 80',   80,  45,  8.0, 6.0),
    ChannelSection('UPN 100', 100,  50,  8.5, 6.0),
    ChannelSection('UPN 120', 120,  55,  9.0, 7.0),
    ChannelSection('UPN 140', 140,  60, 10.0, 7.0),
    ChannelSection('UPN 160', 160,  65, 10.5, 7.5),
    ChannelSection('UPN 180', 180,  70, 11.0, 8.0),
    ChannelSection('UPN 200', 200,  75, 11.5, 8.5),
    ChannelSection('UPN 220', 220,  80, 12.5, 9.0),
    ChannelSection('UPN 240', 240,  85, 13.0, 9.5),
    ChannelSection('UPN 260', 260,  90, 14.0, 10.0),
    ChannelSection('UPN 280', 280,  95, 15.0, 10.0),
    ChannelSection('UPN 300', 300, 100, 16.0, 10.0),
]

_CHS: List[RoundTube] = [
    RoundTube('CHS 42.4x3.2',   42.4, 3.2),
    RoundTube('CHS 48.3x3.2',   48.3, 3.2),
    RoundTube('CHS 60.3x3.6',   60.3, 3.6),
    RoundTube('CHS 76.1x3.6',   76.1, 3.6),
    RoundTube('CHS 88.9x4.0',   88.9, 4.0),
    RoundTube('CHS 101.6x4.0', 101.6, 4.0),
    RoundTube('CHS 114.3x4.5', 114.3, 4.5),
    RoundTube('CHS 139.7x5.0', 139.7, 5.0),
    RoundTube('CHS 168.3x5.0', 168.3, 5.0),
    RoundTube('CHS 219.1x6.3', 219.1, 6.3),
    RoundTube('CHS 273.0x6.3', 273.0, 6.3),
    RoundTube('CHS 323.9x8.0', 323.9, 8.0),
]

_RHS: List[RectTube] = [
    RectTube('SHS 40x40x3',     40,  40, 3.0),
    RectTube('SHS 50x50x3',     50,  50, 3.0),
    RectTube('SHS 60x60x4',     60,  60, 4.0),
    RectTube('SHS 80x80x4',     80,  80, 4.0),
    RectTube('SHS 100x100x5',  100, 100, 5.0),
    RectTube('SHS 120x120x5',  120, 120, 5.0),
    RectTube('SHS 150x150x6',  150, 150, 6.0),
    RectTube('SHS 200x200x8',  200, 200, 8.0),
    RectTube('RHS 60x40x3',     60,  40, 3.0),
    RectTube('RHS 80x40x4',     80,  40, 4.0),
    RectTube('RHS 100x50x4',   100,  50, 4.0),
    RectTube('RHS 120x60x5',   120,  60, 5.0),
    RectTube('RHS 150x100x5',  150, 100, 5.0),
    RectTube('RHS 200x100x6',  200, 100, 6.0),
]

_ANGLES: List[EqualAngle] = [
    EqualAngle('L 25x3',   25, 3.0),
    EqualAngle('L 30x3',   30, 3.0),
    EqualAngle('L 40x4',   40, 4.0),
    EqualAngle('L 50x5',   50, 5.0),
    EqualAngle('L 60x6',   60, 6.0),
    EqualAngle('L 70x7',   70, 7.0),
    EqualAngle('L 80x8',   80, 8.0),
    EqualAngle('L 90x9',   90, 9.0),
    EqualAngle('L 100x10', 100, 10.0),
    EqualAngle('L 120x12', 120, 12.0),
    EqualAngle('L 150x15', 150, 15.0),
]


# ── Grouped for the picker UI ──────────────────────────────────────────

CATALOG_GROUPS: List[Tuple[str, list]] = [
    ('IPE',         _IPE),
    ('HEA',         _HEA),
    ('HEB',         _HEB),
    ('UPN',         _UPN),
    ('CHS (tubes)', _CHS),
    ('RHS/SHS',     _RHS),
    ('L (angles)',  _ANGLES),
]

CATALOG: Dict[str, object] = {}
for _grp_name, _sections in CATALOG_GROUPS:
    for _s in _sections:
        CATALOG[_s.name] = _s


# ─────────────────────────────────────────────────────────────────────────
# 4. Convert a catalog section + material into a stereo member-property dict
# ─────────────────────────────────────────────────────────────────────────

def section_to_props(section, material: Optional[Material] = None) -> dict:
    """Return a dict with the keys the stereo solver needs, in the tab's
    working units (E in GPa, A in cm2, I/J in cm4, r_gyr in cm, Fy/Fu
    in MPa).  If *material* is None the E/Fy/Fu fields are omitted so
    the caller can fill them from whatever the profile already carries."""
    props: dict = {
        'A':     section.A_mm2 / 100.0,       # mm2 -> cm2
        'I':     section.Ix_mm4 / 10_000.0,   # mm4 -> cm4
        'J':     section.J_mm4 / 10_000.0,
        'r_gyr': section.r_gyr_mm / 10.0,     # mm -> cm; MINOR principal
        # Distance to the extreme fibre for bending about the axis of I, so
        # a bending check forms S = I/c from real geometry and never falls
        # back on the thin-round-tube guess, which is 39% unsafe for an
        # angle. Every class carries c_mm; this used to look for `d` or
        # `h` and so missed CHS (D), RHS (H) and angles (leg) entirely.
        'c_cm':  section.c_mm / 10.0,
        # The WEAK axis, for a rigid joint. A frame element bends two ways,
        # and taking both stiffnesses as I (the strong one) made an IPE as
        # stiff sideways as it is in its own plane -- about 13 times too
        # stiff for an IPE 200. Iw and cw are the weak axis's second moment
        # and extreme-fibre distance; stereo_math puts the strong axis in
        # the vertical plane through the rod (where gravity bends a beam)
        # and this one square to it.
        'Iw':    section.Iw_mm4 / 10_000.0,
        'cw_cm': section.cw_mm / 10.0,
    }
    if material is not None:
        props['E']  = material.E / 1000.0      # MPa -> GPa
        props['Fy'] = material.Fy
        props['Fu'] = material.Fu
    return props


def catalog_names() -> List[str]:
    """All catalog profile names, in display order."""
    return list(CATALOG.keys())


def group_names() -> List[str]:
    """The group headings (IPE, HEA, ...) in display order."""
    return [g for g, _ in CATALOG_GROUPS]


def profiles_in_group(group: str) -> List[str]:
    """Profile names within a catalog group."""
    for g, sections in CATALOG_GROUPS:
        if g == group:
            return [s.name for s in sections]
    return []


def profile_summary(name: str) -> str:
    """One-line summary for display in the profile picker."""
    sec = CATALOG.get(name)
    if sec is None:
        return name
    a_cm2 = sec.A_mm2 / 100.0
    ix_cm4 = sec.Ix_mm4 / 10_000.0
    r_cm = sec.r_gyr_mm / 10.0
    # "r min", not "r": a bare r beside a strong-axis I invites reading it as
    # the strong-axis radius, which is precisely the mistake this table used
    # to make on the reader's behalf.
    return f'{name}  (A={a_cm2:.1f} cm², I={ix_cm4:.0f} cm⁴, r min={r_cm:.2f} cm)'


STEEL_KG_PER_M3 = 7850.0


def section_properties(name: str) -> List[Tuple[str, str, str, str]]:
    """The properties a reader checks a section by, for a properties box.

    Rows of (symbol, value, unit, meaning), already formatted, in the order
    a steel table prints them. The two radii are both given and both named,
    because the minor one is what a strut buckles about and the major one
    is what a bending check uses -- showing one bare "r" invites reading
    the wrong one, the mistake this catalog itself once made. [] for a name
    that is not in the catalog (a hand-typed section has no table row).
    """
    sec = CATALOG.get(name)
    if sec is None:
        return []
    A = sec.A_mm2 / 100.0
    Ix = sec.Ix_mm4 / 10_000.0
    Iy = sec.Iy_mm4 / 10_000.0
    J = sec.J_mm4 / 10_000.0
    c = sec.c_mm / 10.0
    # "Strong" and "weak" only mean something for a section that has them.
    # An angle's x and y are its two legs, equal here, and its weakest axis
    # is neither (v-v); a round tube is the same about every axis.
    if isinstance(sec, EqualAngle):
        ax, ay = 'about a leg (x-x)', 'about the other leg (y-y)'
    elif isinstance(sec, RoundTube):
        ax = ay = 'about any axis'
    elif abs(Ix - Iy) <= 1e-9 * max(Ix, Iy, 1e-12):
        ax = ay = 'about either axis'       # a square tube
    else:
        ax, ay = 'strong axis', 'weak axis'
    rows = [
        ('A', '%.2f' % A, 'cm²', 'area'),
        ('Ix', '%.1f' % Ix, 'cm⁴', 'second moment, ' + ax),
        ('Iy', '%.1f' % Iy, 'cm⁴', 'second moment, ' + ay),
        ('J', '%.2f' % J, 'cm⁴', 'torsion constant'),
        ('rx', '%.2f' % (sec.r_x_mm / 10.0), 'cm', 'radius of gyration, ' + ax),
        ('r min', '%.2f' % (sec.r_gyr_mm / 10.0), 'cm',
         'radius of gyration, minor -- buckling uses this'),
        ('c', '%.1f' % c, 'cm', 'centroid to extreme fibre, ' + ax),
        ('Wx', '%.1f' % (Ix / c if c > 0 else 0.0), 'cm³',
         'elastic section modulus, ' + ax),
        ('mass', '%.2f' % (A * 1e-4 * STEEL_KG_PER_M3), 'kg/m',
         'steel at 7850 kg/m³'),
    ]
    if isinstance(sec, EqualAngle):
        rows.insert(3, ('Iv', '%.1f' % (sec.Iv_mm4 / 10_000.0), 'cm⁴',
                        'second moment, minor principal (v-v)'))
    return rows


# Printed under every properties table: the catalog builds each section from
# its nominal plate dimensions, without the root fillets of a rolled shape,
# so A, I and mass run a few per cent under a published steel table -- on
# the safe side, and worth saying so nobody takes it for a transcription.
SECTION_PROPERTIES_NOTE = ('From nominal plate dimensions, without root '
                           'fillets: a few per cent under published tables, '
                           'on the safe side.')


# ── writing a section onto a member without leaving a stale depth ────────────

# The member keys a section is made of. c_cm is deliberately NOT in this list:
# it travels by its own rule (write_section), because it is only true of the
# exact catalog section it came from.
SECTION_KEYS = ('E', 'A', 'I', 'J', 'Fy', 'Fu', 'r_gyr', 'K')


# Keys that are only true of the exact catalog section they came from, so
# they travel by write_section's rule rather than as plain section keys: the
# extreme-fibre depth, and the weak axis's second moment and depth.
CATALOG_EXTRAS = ('c_cm', 'Iw', 'cw_cm')


def write_section(target, values):
    """Copy a section onto a member or profile dict, and keep c_cm honest.

    `target` gets every SECTION_KEY present in `values`. It gets `c_cm` if
    and only if `values` carries one -- otherwise any `c_cm` it already had
    is REMOVED, not left behind.

    Leaving it behind is not a tidiness problem, it is unsafe: a small
    catalog depth kept beside a larger hand-typed I gives S = I/c too big,
    so a member's bending capacity is overstated by exactly the ratio of
    the two sections. Without c_cm the bending check falls back to a
    thin-tube assumption derived from I and A, which is conservative for
    the I and channel sections where that ratio is largest.
    """
    for k in SECTION_KEYS:
        if k in values:
            target[k] = values[k]
    # c_cm and the weak axis (Iw, cw_cm) by the same rule: carried when the
    # values have them, REMOVED when they do not. A weak-axis I left beside
    # a hand-typed strong one belongs to some other section entirely.
    for k in CATALOG_EXTRAS:
        if values.get(k):
            target[k] = values[k]
        else:
            target.pop(k, None)
    return target


def depth_still_valid(depth, I_now, rel_tol=1e-6):
    """Does a remembered catalog depth still describe a section with I_now?

    `depth` is (c_cm, I_at_pick) or None. The depth belongs to the catalog
    section it was read from, and the only evidence available that the user
    has not since typed a different section over it is that I is unchanged.
    """
    if not depth:
        return False
    c_cm, I_then = depth
    if not c_cm or I_then is None:
        return False
    try:
        I_now = float(I_now)
    except (TypeError, ValueError):
        return False
    scale = max(abs(I_then), abs(I_now), 1e-12)
    return abs(I_now - I_then) <= rel_tol * scale


def extras_still_valid(remembered, I_now, rel_tol=1e-6):
    """The catalog extras (CATALOG_EXTRAS) remembered beside the I they were
    picked with, if that I is still the one in use -- else {}.

    `remembered` is ({key: value}, I_at_pick) or None. As depth_still_valid,
    and for the same reason: an unchanged I is the only evidence there is
    that the section has not been typed over.
    """
    if not remembered:
        return {}
    extras, I_then = remembered
    if not extras:
        return {}
    return dict(extras) if same_I(I_then, I_now, rel_tol) else {}


def same_I(I_then, I_now, rel_tol=1e-6):
    """Is this still the same section, as far as its I can tell? Float noise
    allowed; None or junk on either side is "no"."""
    try:
        I_then, I_now = float(I_then), float(I_now)
    except (TypeError, ValueError):
        return False
    scale = max(abs(I_then), abs(I_now), 1e-12)
    return abs(I_now - I_then) <= rel_tol * scale
