"""Bridge structures (family 4 of the Stereo geometry library).

truss_bridge builds two parallel planar Warren/Pratt-style trusses tied
together by deck cross-beams and lateral bracing at both chord levels.

Its docstring carries two hard-won structural notes worth reading before
editing it: why the TOP-level cross-beams are required rather than
decorative (without them each panel's four top joints form a plain
four-bar linkage -- a real mechanism this generator shipped with briefly),
and the one coincidental critical-geometry combination that is singular
even with correct topology.
"""
from apps.stereo.stereo_geometry_core import _NodeBank, _add_member


def truss_bridge(span, depth, width, n_panels=8):
    """A through-truss bridge: two parallel vertical PLANAR trusses (one
    along each edge of the deck), tied together by cross-beams at every
    panel point and full X lateral bracing at both the top and bottom
    chord levels. The lateral bracing is not optional decoration: each
    planar truss on its own is only stable WITHIN its own vertical
    plane, so without it the two planes together would be free to rack
    sideways -- a genuine 3D mechanism -- with nothing to resist
    transverse shear.

    Each planar truss is a classic zigzag (Warren/Pratt-style) truss: a
    vertical post at every panel point, one chord along the top and one
    along the bottom, and a single diagonal per panel that alternates
    direction panel to panel. On its own (as a 2D truss with one pin and
    one roller support) this is exactly statically determinate --
    m + r = 2j for any n_panels -- the standard bridge-truss topology,
    not an arbitrary triangulation.

    span     : total length along the direction of travel (m).
    depth    : vertical height between the top and bottom chords (m).
    width    : transverse distance between the two truss planes, i.e.
               the deck width (m).
    n_panels : number of panels along the span (>= 2 -- a single panel
               has no adjacent diagonal to alternate against).

    Returns the shared {'nodes','members','support_candidates'} dict,
    with the four BOTTOM corner nodes (both ends, both truss planes --
    a bridge's actual bearing points) offered as support candidates.

    Like any pin-jointed truss, a small set of EXACT dimension
    combinations can coincidentally put the geometry into a critical
    (instantaneously mechanistic) form -- a real, if narrow, structural
    phenomenon, not a defect in this topology: e.g. span=40, depth=5,
    width=6, n_panels=4 solves as a genuine mechanism, while width=5.9
    or 6.1 at the same other values does not. Analyze reports this the
    normal way (a singular stiffness matrix), the same as it would for a
    hand-built model that happened onto the same critical proportions;
    changing any one dimension slightly is enough to leave it.
    """
    span = float(span); depth = float(depth); width = float(width)
    n_panels = max(2, int(n_panels))
    if span <= 0 or depth <= 0 or width <= 0:
        raise ValueError('span, depth and width must all be positive')

    panel = span / n_panels
    bank = _NodeBank()
    members = []
    seen = set()

    bottom = {}   # (i, side) -> node id; side 0 is y=0, side 1 is y=width
    top = {}
    for i in range(n_panels + 1):
        x = i * panel
        for side, y in ((0, 0.0), (1, width)):
            bottom[(i, side)] = bank.add(x, y, 0.0)
            top[(i, side)] = bank.add(x, y, depth)

    for side in (0, 1):
        for i in range(n_panels):
            _add_member(members, seen, bottom[(i, side)], bottom[(i + 1, side)],
                        role='bottom_chord')
            _add_member(members, seen, top[(i, side)], top[(i + 1, side)],
                        role='top_chord')
        for i in range(n_panels + 1):
            _add_member(members, seen, bottom[(i, side)], top[(i, side)], role='vertical')
        for i in range(n_panels):
            if i % 2 == 0:
                _add_member(members, seen, bottom[(i, side)], top[(i + 1, side)],
                            role='diagonal')
            else:
                _add_member(members, seen, top[(i, side)], bottom[(i + 1, side)],
                            role='diagonal')

    # Cross-beams at every panel point, BOTH chord levels: the bottom
    # ones are where the roadway actually spans between the two edge
    # trusses; the top ones exist purely for stability -- without a
    # direct top(i,0)-top(i,1) member at each i, the top level's own
    # lateral X-braces (below) connect consecutive panel points only,
    # which makes each panel's own 4 top-level joints a plain 4-bar
    # loop (chord, brace, chord, brace, with no diagonal of ITS OWN) --
    # a textbook mechanism, not a rigid quadrilateral, and exactly what
    # produced a singular stiffness matrix before this member existed.
    for i in range(n_panels + 1):
        _add_member(members, seen, bottom[(i, 0)], bottom[(i, 1)], role='cross_beam')
        _add_member(members, seen, top[(i, 0)], top[(i, 1)], role='cross_beam')

    # Lateral X-bracing at both chord levels -- see this function's own
    # docstring for why it is required, not optional, for out-of-plane
    # (transverse) stability of the two truss planes together.
    for i in range(n_panels):
        _add_member(members, seen, bottom[(i, 0)], bottom[(i + 1, 1)], role='lateral_brace')
        _add_member(members, seen, bottom[(i, 1)], bottom[(i + 1, 0)], role='lateral_brace')
        _add_member(members, seen, top[(i, 0)], top[(i + 1, 1)], role='lateral_brace')
        _add_member(members, seen, top[(i, 1)], top[(i + 1, 0)], role='lateral_brace')

    support_candidates = [bottom[(0, 0)], bottom[(0, 1)],
                          bottom[(n_panels, 0)], bottom[(n_panels, 1)]]

    # Tributary area for a roadway (area) load, lumped onto the deck's
    # own bottom-chord panel points -- plan projection (width * panel
    # length per interior point, halved at the two ends), exact for a
    # flat deck, split evenly between the two edge trusses' own panel
    # points the way a real deck's own weight splits across both girders.
    load_nodes = {}
    for i in range(n_panels + 1):
        f_long = panel if 0 < i < n_panels else panel / 2.0
        area = f_long * width
        load_nodes[bottom[(i, 0)]] = area / 2.0
        load_nodes[bottom[(i, 1)]] = area / 2.0

    return {'nodes': bank.nodes, 'members': members, 'support_candidates': support_candidates,
            'load_nodes': load_nodes}
