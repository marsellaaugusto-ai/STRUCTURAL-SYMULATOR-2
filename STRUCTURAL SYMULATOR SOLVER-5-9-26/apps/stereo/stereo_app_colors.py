"""The Stereo tab's four colour spectra, as pure functions.

Each maps one analysis quantity to a hex colour, and each is used in two
places that MUST agree: the wireframe/face drawing itself and the legend's
numeric colourbar. Keeping them here, taking only plain numbers and
returning only a string, is what lets the legend sample the exact same
function the drawing code calls rather than reimplementing the ramp:

  force_color   -- axial force, red (tension) / blue (compression)
  deform_color  -- nodal displacement magnitude, white to green
  util_color    -- CIRSOC utilisation, green / amber / red
  moment_color  -- signed nodal moment, orange (negative) to violet
                   (positive) through white

reaction_moment_signed sits alongside them because it produces the signed
scalar moment_color consumes -- the choice of WHICH moment component (a
single axis or the resultant, and with which sign convention) is part of
the colouring decision, not of the analysis.
"""
import math

from apps.stereo.stereo_app_constants import (
    TENSION_LOW, TENSION_HIGH, COMPRESSION_LOW, COMPRESSION_HIGH, GAMMA,
    NEAR_ZERO_COLOR, NEAR_ZERO_FRAC,
    DEFORM_LOW, DEFORM_HIGH, DEFORM_GAMMA,
    UTIL_LOW, UTIL_MID, UTIL_HIGH,
    MOMENT_NEG_HIGH, MOMENT_ZERO_COLOR, MOMENT_POS_HIGH, MOMENT_GAMMA,
    MOMENT_AXIS_RESULTANT, MOMENT_AXIS_MX, MOMENT_AXIS_MY, MOMENT_AXIS_MZ,
)

def _lerp_hex(c1, c2, t):
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return f'#{r:02x}{g:02x}{b:02x}'


def force_color(N, max_abs_N):
    """Red for tension, blue for compression, a gradient by |N| relative to
    the largest force anywhere in the current results -- gamma-compressed
    the same way common.LoadScale sizes a load glyph, so a model with
    forces spanning orders of magnitude still shows visible contrast
    instead of one saturated member and everything else looking ~0. Forces
    below NEAR_ZERO_FRAC of the model's max are drawn a flat neutral grey
    ("~0" in the legend) rather than a barely-tinted color no one could
    read as tension or compression anyway."""
    if max_abs_N < 1e-9:
        return NEAR_ZERO_COLOR
    frac = abs(N) / max_abs_N
    if frac < NEAR_ZERO_FRAC:
        return NEAR_ZERO_COLOR
    frac = min(1.0, frac) ** GAMMA
    if N >= 0:
        return _lerp_hex(TENSION_LOW, TENSION_HIGH, frac)
    return _lerp_hex(COMPRESSION_LOW, COMPRESSION_HIGH, frac)


def deform_color(disp_mm, max_disp_mm):
    """White-to-green spectrum for the deformed-shape overlay: pale (but
    not pure white -- that would be illegible against the canvas
    background) for near-zero displacement, saturated green for whatever
    moved the most, gamma-compressed the same way force_color and
    common.LoadScale size/color everything else in this app so a model
    with displacements spanning orders of magnitude still shows visible
    contrast instead of one saturated member and a field of invisible
    near-white ones."""
    if max_disp_mm < 1e-9:
        return DEFORM_LOW
    frac = min(1.0, disp_mm / max_disp_mm) ** DEFORM_GAMMA
    return _lerp_hex(DEFORM_LOW, DEFORM_HIGH, frac)


def util_color(util):
    """Green-amber-red heat-map for a member's utilization (demand/
    capacity ratio): green at 0, amber at 0.5, red at 1.0 and beyond --
    unlike force_color (which reads sign and relative magnitude within
    THIS model's own force range), this reads an ABSOLUTE, code-defined
    threshold that is the same from one model to the next, so "red" always
    means the same thing: at or over capacity."""
    util = max(0.0, util)
    if util <= 0.5:
        return _lerp_hex(UTIL_LOW, UTIL_MID, util / 0.5)
    if util <= 1.0:
        return _lerp_hex(UTIL_MID, UTIL_HIGH, (util - 0.5) / 0.5)
    return UTIL_HIGH
def reaction_moment_signed(reaction, axis=MOMENT_AXIS_RESULTANT, node_xy=None, centroid_xy=None):
    """One signed scalar (kN*m) from a solved reaction's own Mx/My/Mz, for
    moment_color. `axis` picks which:

    'Mx'/'My'/'Mz' : that single component's own signed value directly --
                  lets you look at one specific bending direction in
                  isolation (e.g. the moment resisting bending about the
                  span's own transverse axis) instead of a blend of all
                  three. Unaffected by node_xy/centroid_xy below -- this
                  is a deliberately literal single-component view.
    'Resultant (dominant)' (default) : the RESULTANT magnitude
                  (sqrt(Mx^2+My^2+Mz^2)). The SIGN comes from `node_xy`
                  and `centroid_xy` when both are given: the horizontal
                  moment's component TANGENTIAL to the line from the
                  structure's own planar centroid out to this node (or
                  sign(Mz) when Mz itself is the larger part of the
                  moment). This matters because Mx/My are components of
                  an axial vector: under a proper 180-degree rotation
                  about Z -- exactly the relationship between two
                  diagonally-opposite, physically identically-loaded
                  nodes of a symmetric grid -- BOTH Mx and My flip sign,
                  even though the physical bending intensity at the two
                  nodes is identical. Confirmed numerically on a
                  symmetric 4-corner-fixed grid under symmetric
                  self-weight: corner (0,0) came out Mx=+0.02/My=-0.02
                  and its diagonal opposite (9,9) Mx=-0.02/My=+0.02 --
                  same magnitude, everything flipped -- which used to
                  paint two equally-loaded, symmetric nodes as opposite
                  colours (orange vs. violet). The tangential projection
                  is invariant under exactly this kind of rotation (the
                  moment vector and the local tangential direction
                  corotate together), so symmetric nodes read the same
                  sign, matching the "sagging/hogging" scalar convention
                  every statics course actually uses instead of a raw,
                  basis-dependent vector component. Falls back to the
                  old "whichever component is largest" sign when either
                  geometry argument is omitted, or the node sits exactly
                  at the centroid (no tangential direction is defined
                  there)."""
    mx = reaction.get('Mx', 0.0)
    my = reaction.get('My', 0.0)
    mz = reaction.get('Mz', 0.0)
    if axis == MOMENT_AXIS_MX:
        return mx
    if axis == MOMENT_AXIS_MY:
        return my
    if axis == MOMENT_AXIS_MZ:
        return mz
    resultant = math.sqrt(mx * mx + my * my + mz * mz)
    if node_xy is not None and centroid_xy is not None:
        rx, ry = node_xy[0] - centroid_xy[0], node_xy[1] - centroid_xy[1]
        rnorm = math.hypot(rx, ry)
        if rnorm > 1e-9:
            tx, ty = -ry / rnorm, rx / rnorm
            horiz_mag = math.hypot(mx, my)
            if abs(mz) >= horiz_mag:
                return resultant if mz >= 0 else -resultant
            tangential = mx * tx + my * ty
            return resultant if tangential >= 0 else -resultant
    dominant = max((mx, my, mz), key=abs)
    return resultant if dominant >= 0 else -resultant


def moment_color(m_signed, max_abs_m):
    """Continuous orange-white-violet diverging spectrum for a node's own
    moment (a support's reaction moment, see reaction_moment_signed, or an
    ordinary joint's own value, see stereo_math.node_moment_vectors):
    orange at the most negative moment PRESENT ANYWHERE IN THE GRID, white
    at exactly zero, violet at the most positive -- so `max_abs_m` (the
    largest |moment| across every node currently being coloured, supports
    and interior rigid joints alike) is what scales any one node's colour,
    making it always relative to the rest of the structure rather than an
    absolute threshold. This is the per-node quantity a RIGID
    (moment-transferring) connection scheme actually produces, unlike a
    pin-jointed truss's, which reacts to force only and would read as
    white everywhere regardless of load."""
    if max_abs_m < 1e-9:
        return MOMENT_ZERO_COLOR
    frac = min(1.0, abs(m_signed) / max_abs_m) ** MOMENT_GAMMA
    if m_signed >= 0:
        return _lerp_hex(MOMENT_ZERO_COLOR, MOMENT_POS_HIGH, frac)
    return _lerp_hex(MOMENT_ZERO_COLOR, MOMENT_NEG_HIGH, frac)
