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
    def r_gyr_mm(self) -> float:
        return math.sqrt(self.Ix_mm4 / self.A_mm2)

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
    def r_gyr_mm(self) -> float:
        return math.sqrt(self.Ix_mm4 / self.A_mm2)

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
    def r_gyr_mm(self) -> float:
        return math.sqrt(self.Ix_mm4 / self.A_mm2)

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
    def r_gyr_mm(self) -> float:
        return math.sqrt(self.Ix_mm4 / self.A_mm2)

    @property
    def shape(self) -> str:
        return 'RHS'


@dataclass
class EqualAngle:
    """Equal-leg angle (L).  All dimensions in mm."""
    name: str
    leg: float     # leg length
    t: float       # thickness

    @property
    def A_mm2(self) -> float:
        return self.t * (2 * self.leg - self.t)

    @property
    def Ix_mm4(self) -> float:
        L, t = self.leg, self.t
        return (L * t ** 3 + (L - t) * t ** 3) / 3.0 + \
               t * (L - t) * ((L - t / 2.0) / 2.0) ** 2

    @property
    def Iy_mm4(self) -> float:
        return self.Ix_mm4

    @property
    def J_mm4(self) -> float:
        return (2 * self.leg - self.t) * self.t ** 3 / 3.0

    @property
    def r_gyr_mm(self) -> float:
        return math.sqrt(self.Ix_mm4 / self.A_mm2)

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
        'r_gyr': section.r_gyr_mm / 10.0,     # mm -> cm
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
    return f'{name}  (A={a_cm2:.1f} cm², I={ix_cm4:.0f} cm⁴, r={r_cm:.2f} cm)'
