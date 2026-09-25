"""Every module-level constant the Stereo tab's UI and renderer share.

Kept in one place, with no imports of its own, so a colour, a pixel size
or a dropdown's label list can be found and changed without reading any
drawing or layout code -- and so no two modules can drift apart holding
their own copy of the same value.

Grouped below as: canvas/panel geometry, node & member colours, the four
colour-spectrum ramps (axial force, deformation, utilisation, moment),
load-path animation, and the dropdown label tables (grid families, module
patterns, support presets, DOF names).
"""

BG = '#f0f0ee'
CANVAS_BG = '#ffffff'
PANEL_W = 300
MODULE_PANEL_W = 300
MODULE_CANVAS_SIZE = 260
MODULE_RING_COLOR = '#333333'
MODULE_APEX_EDGE_COLOR = '#c0392b'
MODULE_APEX_NODE_COLOR = '#c0392b'
MODULE_FACE_FILL = '#cfe0fb'
MODULE_DIM_COLOR = '#555555'

NODE_COLOR = '#1a1a1a'
NODE_SEL_COLOR = '#e0522b'
ADD_ROD_PENDING_COLOR = '#e67e22'   # ring around the first-picked node in
                                     # 'Add rod' mode, waiting on the second
SUPPORT_COLOR = '#1a6bbd'
SUPPORT_DISABLED_COLOR = '#b9bec4'
MEMBER_PIN_COLOR = '#555555'
MEMBER_RIGID_COLOR = '#7a3fb8'
NEAR_ZERO_COLOR = '#9a9a9a'
NEAR_ZERO_FRAC = 0.03
TENSION_LOW = '#f6cec4'
TENSION_HIGH = '#a3241a'
COMPRESSION_LOW = '#c9dcf5'
COMPRESSION_HIGH = '#17458c'
GAMMA = 0.6   # perceptual compression, same idiom as common.LoadScale's gamma
UNDO_LIMIT = 60
LOAD_COLOR = '#e07b1f'
SUPPORT_BOX_HALF_PX = 7
LASSO_DRAG_THRESHOLD_PX = 4
DEFORM_LOW = '#eaf6ee'    # pale green -- legible, deliberately not pure white
DEFORM_HIGH = '#0e7a3d'   # saturated green -- the largest displacement present
DEFORM_GAMMA = 0.6
DEFORM_MODE_DISPLACEMENT = 'Displacement'
DEFORM_MODE_FORCE = 'Axial force'
DEFORM_MODES = (DEFORM_MODE_DISPLACEMENT, DEFORM_MODE_FORCE)
REACTION_COLOR = '#c2185b'
UTIL_LOW = '#2e7d32'    # green -- well within capacity
UTIL_MID = '#f9a825'    # amber -- approaching capacity
UTIL_HIGH = '#c62828'   # red -- at or over capacity
MEMBER_SEL_COLOR = '#e0522b'
MEMBER_SEL_HIT_PX = 8
SLENDER_HALO_COLOR = '#ffb300'
SLENDERNESS_LIMIT = 200.0   # AISC/CIRSOC's own recommended (non-mandatory) practical limit

# "Thickness by stress": a member's drawn line width scales with its axial
# STRESS |N|/A relative to the most-stressed member in the model. The cap is
# the whole point of the pair -- an uncapped scale makes one hot member
# swallow its neighbours on a dense mesh, so the ratio only ever moves the
# width between these two values, however extreme the stress ratio gets.
STRESS_WIDTH_MIN = 1.0   # px, the least-stressed member (and any at ~0)
STRESS_WIDTH_MAX = 7.0   # px, the hard cap at the highest stress in the model

# "Smooth gradient": each rod is drawn as a run of short lines blending from
# the value at one end to the value at the other, so the colour field reads
# as continuous across a joint instead of jumping. The segment count is a
# direct multiplier on canvas items, so a dense model uses a coarser run --
# on a 3000-rod grid each rod is only a few pixels long on screen and the
# extra steps buy nothing visible.
# The toolbar's two radio groups. Both exist because the underlying choice
# really is one-of-N: only one quantity can colour the model at a time, and
# only one fill can sit behind it. They were checkboxes once, with the
# exclusivity enforced silently in the renderer (utilization beat force beat
# moment) and nothing on screen admitting it.
COLOUR_NONE = 'None'
COLOUR_FORCE = 'Axial force'
COLOUR_UTIL = 'Utilization'
COLOUR_MOMENT = 'Node moment'
COLOUR_MODES = (COLOUR_NONE, COLOUR_FORCE, COLOUR_UTIL, COLOUR_MOMENT)

FILL_NONE = 'None'
FILL_SHADED = 'Shaded cells'
FILL_VORONOI = 'Voronoi'
FILL_MODES = (FILL_NONE, FILL_SHADED, FILL_VORONOI)

# How the force colourbar's ends are anchored.
#
# SCALE_PEAK is the literal maximum |N| in the model, which keeps the
# legend's numbers true for every rod but lets a single extreme member set
# the scale for all the others: measured across the 14 grid families the
# MEDIAN member carries only 12-32% of the peak, so most of the structure
# lands in the pale middle of the ramp.
#
# SCALE_P95 anchors at the 95th percentile of |N| instead, which lifts that
# median from about 0.44 to 0.55 of the ramp. The few members above the
# anchor are then off the top of the scale, so they are marked CLIPPED
# rather than silently drawn the same as one exactly at the anchor.
SCALE_PEAK = 'Peak force'
SCALE_P95 = '95th percentile'
SCALE_MODES = (SCALE_PEAK, SCALE_P95)
FORCE_SCALE_PERCENTILE = 95
CLIP_MARK_COLOR = '#111111'   # the hairline that marks a rod above the anchor
CLIP_MARK_DASH = (2, 3)

# Cell outlines in the Voronoi "Cells" view -- drawn over the fill along the
# rods where ownership changes, which is what makes the cells read as cells
# rather than as a continuous colour field.
# How opaque a fill is drawn. A Tk canvas polygon has no alpha channel, so
# "see-through" is a stipple pattern: at gray25 a quarter of the pixels are
# the fill and the rest is whatever is behind it. The trade runs both ways --
# solid lets the nearest patch hide every patch behind it and the shape loses
# all depth, while the sparsest pattern washes the dark end of the colour ramp
# out towards the canvas. Offered as a control rather than settled here,
# because which end matters depends on the model and on the reader.
FILL_DENSITY_STIPPLE = {'Light': 'gray25', 'Medium': 'gray50',
                        'Heavy': 'gray75', 'Solid': ''}
FILL_DENSITIES = tuple(FILL_DENSITY_STIPPLE)
FILL_DENSITY_DEFAULT = 'Light'

CELL_EDGE_COLOR = '#33414d'
CELL_EDGE_WIDTH = 1

GRADIENT_SEGMENTS = 8
GRADIENT_SEGMENTS_DENSE = 4
GRADIENT_DENSE_MEMBERS = 900
GRADIENT_DISABLE_MEMBERS = 3000
LABEL_DISABLE_NODES = 2000
LOAD_PATH_DISABLE_MEMBERS = 2000
DRAW_THROTTLE_MS = 33
LOAD_PATH_NEAR_ZERO_FRAC = 0.02   # members below this fraction of the largest |N| stay still
LOAD_PATH_ARROW_HALF_PX = 7   # half-length of each travelling arrowhead glyph
LOAD_PATH_ANIM_TICKS = 24     # ticks per full loop (24 * LOAD_PATH_TICK_MS = 3.6s)
LOAD_PATH_COLOR_FLOOR = 0.35  # least saturated a load-path arrow may be drawn
MOMENT_NEG_HIGH = '#c46a12'   # saturated orange -- negative moment
MOMENT_ZERO_COLOR = '#ffffff'   # white -- zero moment
MOMENT_POS_HIGH = '#6a2ca0'   # saturated violet -- positive moment
MOMENT_GAMMA = 0.6
MOMENT_NODE_OUTLINE = '#999999'   # keeps a white (zero-moment) node visible
                                   # against the canvas's own white background
MOMENT_BACKDROP_COLOR = '#dcdcdc'   # pale grey the members fade to in moment
                                     # mode, so the node colours -- the actual
                                     # content of that view -- aren't lost
                                     # among dark rod lines converging at a
                                     # busy joint
MOMENT_NODE_RADIUS_PX = 6   # bigger than the normal 4px dot for the same
                            # reason -- a small dot is the first thing a
                            # cluster of member lines swallows

DOF_LABELS = (('ux', 'Ux'), ('uy', 'Uy'), ('uz', 'Uz'),
              ('rx', 'Rx'), ('ry', 'Ry'), ('rz', 'Rz'))
PRESET_NAMES = ('free', 'pin', 'fixed', 'rollerX', 'rollerY', 'rollerZ', 'custom')
GRID_PATTERNS = (('square', 'Square (grid-aligned chords)'),
                 ('diagonal', 'Diagonal (diagonal-on-diagonal chords)'))
PATTERN_KEY = {label: key for key, label in GRID_PATTERNS}
PATTERN_LABEL = {key: label for key, label in GRID_PATTERNS}

GRID_FAMILIES = (('flat_grid', 'Flat double-layer grid'),
                 ('hypar_shell', 'Hyperbolic paraboloid (hypar) shell'),
                 ('hip_roof_grid', 'Hip (pyramidal) roof grid'),
                 ('groin_vault', 'Groin (cross) vault'),
                 ('circular_flat_grid', 'Circular flat grid'),
                 ('barrel_vault', 'Barrel vault (circular arch)'),
                 ('parabolic_vault', 'Parabolic vault'),
                 ('elliptic_vault', 'Elliptic vault'),
                 ('dome', 'Dome (Schwedler ribs)'),
                 ('cone_roof', 'Conical roof (straight rafters)'),
                 ('paraboloid_dish', 'Paraboloid dish (antenna)'),
                 ('elliptic_dome', 'Elliptic dome'),
                 ('sphere_shell', 'Full sphere'),
                 ('truss_bridge', 'Truss bridge (Warren/Pratt-style)'))
FAMILY_KEY = {label: key for key, label in GRID_FAMILIES}
FAMILY_LABEL = {key: label for key, label in GRID_FAMILIES}

# Which member roles (stereo_geometry.py tags every member with one) act as
# CHORDS (the primary top/bottom/outer/hoop/meridian framing) vs WEBS (the
# diagonals/braces tying the two chord surfaces, or a single layer's shell,
# together). A role not listed here defaults to the web section, which is
# always the more numerous and lighter-loaded member family in practice.
CHORD_ROLES = {'bottom_chord', 'top_chord', 'outer_rib', 'inner_rib', 'purlin',
              'hoop', 'meridian', 'reinf_chord', 'surface_chord',
              # a latticed column's four verticals are its chords in exactly
              # the same sense the grid's are: the primary framing carrying
              # the load, with the ties and X-bracing as its webs
              'column_chord', 'column_shaft'}

QUICK_SUPPORT_CUSTOM = 'Custom (edit per node below)'
QUICK_SUPPORT_PIN = 'All suggested nodes: pinned'
QUICK_SUPPORT_FIXED = 'All suggested nodes: fixed'
QUICK_SUPPORT_CLEAR = 'Clear all supports'
QUICK_SUPPORT_CHOICES = (QUICK_SUPPORT_CUSTOM, QUICK_SUPPORT_PIN,
                         QUICK_SUPPORT_FIXED, QUICK_SUPPORT_CLEAR)
MOMENT_AXIS_RESULTANT = 'Resultant (dominant)'
MOMENT_AXIS_MX = 'Mx'
MOMENT_AXIS_MY = 'My'
MOMENT_AXIS_MZ = 'Mz'
MOMENT_AXES = (MOMENT_AXIS_RESULTANT, MOMENT_AXIS_MX, MOMENT_AXIS_MY, MOMENT_AXIS_MZ)


# How an area load varies over the surface it is applied to.
#
#   UNIFORM   one pressure everywhere -- a dead load, a code snow load.
#   GRADIENT  a straight ramp from one end of the chosen axis to the other:
#             a drift, a one-sided wind, a water depth on a fall.
#   FIELD     q as a typed expression in x, y and z, compiled by expr_math
#             against the same whitelist the Custom Surface Wizard uses. The
#             general case, and the reason the other two do not need to grow
#             options: anything they cannot say, this can.
AREA_UNIFORM = 'Uniform'
AREA_GRADIENT = 'Linear gradient'
AREA_FIELD = 'q(x, y, z) expression'
AREA_LAWS = (AREA_UNIFORM, AREA_GRADIENT, AREA_FIELD)

# Which way an area load pushes. Presets for the cases that come up, plus a
# typed vector for everything else -- a wind on a sloping face, a seismic
# component, a pull normal to one wall.
LOAD_DIRECTIONS = {
    'Down (−Z)': (0.0, 0.0, -1.0),
    'Up (+Z)': (0.0, 0.0, 1.0),
    '+X': (1.0, 0.0, 0.0),
    '−X': (-1.0, 0.0, 0.0),
    '+Y': (0.0, 1.0, 0.0),
    '−Y': (0.0, -1.0, 0.0),
    'Custom': None,
}
LOAD_DIRECTION_NAMES = tuple(LOAD_DIRECTIONS)

# Where an area load lands.
AREA_SCOPE_ALL = 'Whole roof/shell surface'
AREA_SCOPE_SELECTED = 'Selected nodes only'
AREA_SCOPES = (AREA_SCOPE_ALL, AREA_SCOPE_SELECTED)
