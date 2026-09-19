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
# The model reads better with SMALL node dots -- the rods are the structure
# and a fat dot at every joint turns a 221-node grid into a field of blobs.
# Two pixels is what the first version of this tab used and it was right.
NODE_RADIUS_PX = 2
NODE_RADIUS_SEL_PX = 4

# A support is a filled white box around its node, not an outline: filled,
# it reads as an object sitting at the joint even where rods cross behind it.
SUPPORT_BOX_HALF_PX = 5
SUPPORT_BOX_FILL = '#eef2f5'
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
# The two along-the-rod fields. These are the only colour modes whose value
# changes WITHIN a member rather than between members, and they say
# something true only when a distributed load is actually on the rod: under
# nodal loads alone a member's shear is constant and its moment runs
# straight from one end value to the other, so the ramp would be drawing a
# single number. See stereo_member_loads for why, and _rod_field_anchor for
# what the view does about a model that carries no rod load at all.
COLOUR_ROD_MOMENT = 'Moment along rod'
COLOUR_ROD_SHEAR = 'Shear along rod'
COLOUR_MODES = (COLOUR_NONE, COLOUR_FORCE, COLOUR_UTIL, COLOUR_MOMENT,
                COLOUR_ROD_MOMENT, COLOUR_ROD_SHEAR)

FILL_NONE = 'None'
FILL_SHADED = 'Shaded cells'
FILL_MODES = (FILL_NONE, FILL_SHADED)

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


# An along-the-rod field is a PARABOLA between the member's two ends, so it
# needs enough pieces to read as a curve rather than as a two-tone rod --
# more than the linear joint-to-joint blend does, and a floor rather than a
# fixed count so a dense model's coarser gradient never flattens it away.
ROD_FIELD_SEGMENTS = 10
GRADIENT_SEGMENTS = 8
GRADIENT_SEGMENTS_DENSE = 4
GRADIENT_DENSE_MEMBERS = 900
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
                 ('vierendeel_grid', 'Vierendeel grid (no diagonals)'),
                 ('hypar_shell', 'Hyperbolic paraboloid (hypar) shell'),
                 ('elliptic_hypar_shell', 'Elliptic hyperbolic paraboloid'),
                 ('elliptic_paraboloid_shell', 'Elliptic paraboloid (sail) shell'),
                 ('conoid_shell', 'Conoid (ruled north-light shell)'),
                 ('monkey_saddle_shell', 'Monkey saddle (three-fall shell)'),
                 ('wave_shell', 'Sinusoidal wave shell'),
                 ('hip_roof_grid', 'Hip (pyramidal) roof grid'),
                 ('groin_vault', 'Groin (cross) vault'),
                 ('circular_flat_grid', 'Circular flat grid'),
                 ('barrel_vault', 'Barrel vault (circular arch)'),
                 ('parabolic_vault', 'Parabolic vault'),
                 ('elliptic_vault', 'Elliptic vault'),
                 ('catenary_vault', 'Catenary vault (pure-compression arch)'),
                 ('torus_segment', 'Torus segment (ring vault)'),
                 ('hyperboloid_tower', 'Hyperboloid of revolution (ruled)'),
                 ('elliptic_hyperboloid', 'Elliptic hyperboloid (ruled)'),
                 ('helicoid_ramp', 'Helicoid ramp (spiral deck)'),
                 ('dome', 'Dome (Schwedler ribs)'),
                 ('cone_roof', 'Conical roof (straight rafters)'),
                 ('paraboloid_dish', 'Paraboloid dish (antenna)'),
                 ('elliptic_dome', 'Elliptic dome'),
                 ('sphere_shell', 'Full sphere'),
                 ('truss_bridge', 'Truss bridge (Warren/Pratt-style)'))

# How the Maxwell-critical ruled-hyperboloid lattice is stabilised --
# see stereo_geometry_surfaces._hyperboloid_lattice for what each does and
# why the bare lattice needs one at all.
HYPERBOLOID_BRACES = (('counter', 'Counter-diagonal (lightest)'),
                      ('ring', 'Ring stiffener (stiffest)'),
                      ('none', 'None -- pure generators only'))
BRACE_KEY = {label: key for key, label in HYPERBOLOID_BRACES}
BRACE_LABEL = {key: label for key, label in HYPERBOLOID_BRACES}
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

# Which rods a DISTRIBUTED (along-the-member) load lands on. Roles are
# offered because that is how such a load is actually specified: cladding
# and snow arrive on the top chords, a service run hangs off the bottom
# ones, and nobody loads the webs by hand.
ROD_SCOPE_TOP = 'Top chords'
ROD_SCOPE_BOTTOM = 'Bottom chords'
ROD_SCOPE_CHORDS = 'All chords'
ROD_SCOPE_WEBS = 'Webs only'
ROD_SCOPE_ALL = 'Every rod'
ROD_SCOPE_SELECTED = 'Selected rod only'
ROD_SCOPES = (ROD_SCOPE_TOP, ROD_SCOPE_BOTTOM, ROD_SCOPE_CHORDS,
              ROD_SCOPE_WEBS, ROD_SCOPE_ALL, ROD_SCOPE_SELECTED)

# The member roles each scope covers. 'surface_chord' and the rib roles
# are a single-layer shell's own chords, so a "top chord" load reaches
# them too -- a shell has one surface and it is the loaded one.
ROD_SCOPE_ROLES = {
    ROD_SCOPE_TOP: {'top_chord', 'outer_rib', 'surface_chord', 'purlin', 'hoop'},
    ROD_SCOPE_BOTTOM: {'bottom_chord', 'inner_rib'},
    ROD_SCOPE_CHORDS: {'top_chord', 'bottom_chord', 'outer_rib', 'inner_rib',
                       'surface_chord', 'purlin', 'hoop', 'meridian',
                       'reinf_chord'},
    ROD_SCOPE_WEBS: {'web', 'web_diag', 'brace'},
}


# The legend sits in the corner of the canvas -- where you look when reading
# colour off the model -- on its own ground, so the ramp and its numbers are
# legible over whatever part of the structure lies behind them.
LEGEND_CARD_BG = '#fbfcfd'
LEGEND_CARD_EDGE = '#ccd4db'


# Ready-made plan-shape rules for the Shape panel, written against the
# domain the panel currently describes rather than in raw metres: {cx}/{cy}
# are the domain's own centre, {r} half its shorter side, {rin} half of
# that. A circle typed in absolute coordinates is wrong the moment the
# domain moves, and nobody wants to re-derive the centre by hand to try a
# round roof.
SHAPE_PLAN_PRESETS = (
    ('Round plan', '(x - {cx})^2 + (y - {cy})^2 < {r}^2'),
    ('Ring (open middle)', 'hypot(x - {cx}, y - {cy}) > {rin}'),
    ('L-shape (one quadrant out)', 'not (x > {cx} and y > {cy})'),
    ('Clear the rule', ''),
)


# How wide wrapped text may be inside a group box NESTED in another group
# box, which is where most of the panels' explanatory text lives. Each
# LabelFrame level costs its own padding and border, and a Checkbutton also
# spends about 20 px on its indicator before any text is drawn -- so
# wrapping at PANEL_W and trusting it to fit overflows by exactly that
# chrome. Measured rather than guessed: the support sandbox's checkbutton
# asked for 288 px inside a 300 px panel.
PANEL_TEXT_W = 244


# A welded shear panel that has not been checked yet has no verdict to
# report, so it is drawn neutral rather than in a colour from the
# utilisation ramp that would imply one.
PANEL_UNCHECKED_COLOR = '#9aa7b1'
PANEL_EDGE_COLOR = '#37474f'


# The footprint disc that follows the cursor when a column footprint is
# being picked, and the ring on the first node of a line pick.
DISC_FILL = '#ffd54f'
DISC_EDGE = '#ef6c00'
LINE_PICK_COLOR = '#1a6bbd'


# A shaded panel whose biggest tension and biggest compression are equal has
# no governing sign. Deliberately OFF the force ramp -- neither red nor blue
# nor the ramp's near-zero white -- so it cannot be misread either as a
# governing direction or as a panel carrying nothing.
BALANCED_PANEL_COLOR = '#b39ddb'
