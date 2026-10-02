"""The Truss tab's example library: nine trusses, each with a lesson.

An example on its own shows what the tab can draw; a question makes
someone look at it. Each lesson names the one idea its truss is good for
and asks two or three things to try, whose answers are on the screen, not
in this file. tests/test_truss_play.py holds every question to what the
truss actually does under its own loads -- a question whose premise the
solver contradicts would teach the wrong thing.

Every example ships with a steel section on each rod family (from the
catalogue, F24 steel), so utilisation, the score and Play load work the
moment it is loaded. Coordinates are in canvas pixels, 24 px = 1 m, y down;
loads are kN with fy positive downwards, the tab's own convention.
Kept free of Tk.
"""
from common import PX_PER_M

OX, OY = 96, 360            # where x = 0, y = 0 lands on the canvas
STEEL = 'F24 (CIRSOC) / A36'


def _p(x_m, y_m):
    return (OX + x_m * PX_PER_M, OY - y_m * PX_PER_M)


def family(section, material=STEEL):
    """A rod family's properties for a catalogue section: what the family
    manager's "Steel section…" writes."""
    from apps.stereo import stereo_profiles as sp
    props = sp.section_to_props(sp.CATALOG[section], sp.MATERIALS[material])
    prof = {k: props[k] for k in ('E', 'A', 'I', 'Fy', 'Fu', 'r_gyr', 'c_cm')}
    prof.update(catalog=section, material=material)
    return prof


def _model(nodes_m, rods, families, supports, loads, conn='pin'):
    """nodes in metres; rods as (a, b, family); the rest as the tab keeps
    them. Each rod takes its family's E, A and I."""
    profiles = {name: family(sec) for name, sec in families.items()}
    out_rods = []
    for a, b, fam in rods:
        p = profiles[fam]
        r = {'a': a, 'b': b, 'E': p['E'], 'A': p['A'], 'I': p['I'],
             'profile': fam}
        if conn == 'rigid':
            r['conn'] = 'rigid'
        out_rods.append(r)
    return {'nodes': [_p(x, y) for x, y in nodes_m], 'rods': out_rods,
            'profiles': profiles,
            'supports': [{'node': n, 'type': t} for n, t in supports],
            'loads': [{'node': n, 'fx': fx, 'fy': fy} for n, fx, fy in loads]}


# ── the nine trusses ──────────────────────────────────────────────────────

def warren():
    """10 m span, 4 m deep: two triangles each side of the middle."""
    nodes = [(0, 0), (2.5, 4), (5, 0), (7.5, 4), (10, 0)]
    rods = [(0, 1, 'Web'), (1, 2, 'Web'), (2, 3, 'Web'), (3, 4, 'Web'),
            (0, 2, 'Chord'), (2, 4, 'Chord'), (1, 3, 'Chord')]
    return _model(nodes, rods, {'Chord': 'CHS 88.9x4.0',
                                'Web': 'CHS 76.1x3.6'},
                  [(0, 'pin'), (4, 'rollerX')],
                  [(1, 0, 30), (2, 0, 60), (3, 0, 30)])


def _flat(diagonals):
    """A 12 m flat truss, 3 m deep, four 3 m bays, vertical end posts.
    Nodes 0-4 bottom, 5-9 top; loads on the top chord (a deck or purlins).
    `diagonals` is the four (a, b) diagonals, one per bay."""
    nodes = [(3 * i, 0) for i in range(5)] + [(3 * i, 3) for i in range(5)]
    rods = ([(i, i + 1, 'Chord') for i in range(4)] +
            [(5 + i, 6 + i, 'Chord') for i in range(4)] +
            [(i, 5 + i, 'Vertical') for i in range(5)] +
            [(a, b, 'Diagonal') for a, b in diagonals])
    return nodes, rods


def pratt():
    nodes, rods = _flat([(5, 1), (6, 2), (8, 2), (9, 3)])
    return _model(nodes, rods, {'Chord': 'CHS 114.3x4.5',
                                'Vertical': 'CHS 88.9x4.0',
                                'Diagonal': 'CHS 60.3x3.6'},
                  [(0, 'pin'), (4, 'rollerX')],
                  [(6, 0, 40), (7, 0, 40), (8, 0, 40)])


def howe():
    nodes, rods = _flat([(0, 6), (1, 7), (3, 7), (4, 8)])
    return _model(nodes, rods, {'Chord': 'CHS 114.3x4.5',
                                'Vertical': 'CHS 60.3x3.6',
                                'Diagonal': 'CHS 101.6x4.0'},
                  [(0, 'pin'), (4, 'rollerX')],
                  [(6, 0, 40), (7, 0, 40), (8, 0, 40)])


def king_post():
    """An 8 m roof: two rafters, a tie, and a post from the apex."""
    nodes = [(0, 0), (4, 0), (8, 0), (4, 3)]
    rods = [(0, 1, 'Tie'), (1, 2, 'Tie'), (0, 3, 'Rafter'), (3, 2, 'Rafter'),
            (1, 3, 'Post')]
    return _model(nodes, rods, {'Rafter': 'CHS 76.1x3.6',
                                'Tie': 'CHS 48.3x3.2',
                                'Post': 'CHS 42.4x3.2'},
                  [(0, 'pin'), (2, 'rollerX')], [(3, 0, 30)])


def fink():
    """A 12 m roof with a 3 m rise; the W of web rods props each rafter
    at mid-length."""
    nodes = [(0, 0), (4, 0), (8, 0), (12, 0), (3, 1.5), (6, 3), (9, 1.5)]
    rods = [(0, 1, 'Tie'), (1, 2, 'Tie'), (2, 3, 'Tie'),
            (0, 4, 'Rafter'), (4, 5, 'Rafter'), (5, 6, 'Rafter'),
            (6, 3, 'Rafter'),
            (4, 1, 'Web'), (1, 5, 'Web'), (5, 2, 'Web'), (2, 6, 'Web')]
    return _model(nodes, rods, {'Rafter': 'CHS 88.9x4.0',
                                'Tie': 'CHS 60.3x3.6',
                                'Web': 'CHS 48.3x3.2'},
                  [(0, 'pin'), (3, 'rollerX')],
                  [(4, 0, 15), (5, 0, 15), (6, 0, 15)])


def cantilever():
    """A 6 m bracket off a wall: two pins on the wall, 3 m apart."""
    nodes = [(0, 0), (0, 3), (3, 0), (3, 3), (6, 3)]
    rods = [(1, 3, 'Chord'), (3, 4, 'Chord'), (0, 2, 'Chord'),
            (2, 4, 'Chord'), (2, 3, 'Web'), (0, 3, 'Web')]
    return _model(nodes, rods, {'Chord': 'CHS 101.6x4.0',
                                'Web': 'CHS 76.1x3.6'},
                  [(0, 'pin'), (1, 'pin')], [(4, 0, 25)])


def vierendeel():
    """No diagonals: every joint is rigid, so the rods bend instead."""
    nodes = [(5 * i, 0) for i in range(5)] + [(5 * i, 4) for i in range(5)]
    rods = ([(i, i + 1, 'Frame') for i in range(4)] +
            [(5 + i, 6 + i, 'Frame') for i in range(4)] +
            [(i, 5 + i, 'Frame') for i in range(5)])
    return _model(nodes, rods, {'Frame': 'SHS 200x200x8'},
                  [(0, 'pin'), (4, 'rollerX')],
                  [(6, 0, 20), (7, 0, 20), (8, 0, 20)], conn='rigid')


def missing_diagonal():
    """The Pratt truss with the diagonal of its second bay left out."""
    m = pratt()
    m['rods'] = [r for r in m['rods']
                 if not (r['profile'] == 'Diagonal' and
                         {r['a'], r['b']} == {6, 2})]
    return m


def single_load():
    """The Pratt truss with one load, hung from the bottom chord."""
    m = pratt()
    m['loads'] = [{'node': 1, 'fx': 0.0, 'fy': 60.0}]
    return m


# (key, menu title, builder). The key names the lesson and the best score,
# so a renamed title cannot orphan either.
EXAMPLES = (
    ('warren', 'Warren truss', warren),
    ('pratt', 'Pratt truss', pratt),
    ('howe', 'Howe truss', howe),
    ('king_post', 'King-post roof', king_post),
    ('fink', 'Fink roof truss', fink),
    ('cantilever', 'Wall bracket (cantilever)', cantilever),
    ('vierendeel', 'Vierendeel girder', vierendeel),
    ('missing_diagonal', 'One diagonal missing', missing_diagonal),
    ('single_load', 'One load, many idle rods', single_load),
)

LESSONS = {
    'warren': {
        'goal': 'Triangles keep their shape: see which chord is pulled and '
                'which is pushed.',
        'questions': (
            '▶ Analyze. Which chord is in tension, the top one or the '
            'bottom one? Why that way round?',
            'As shipped it fails. ▶ Play load: at what share of the load '
            'does the first rod reach its capacity, and which rod is it? '
            'Give its family a heavier section until it passes.',
            'Delete rod 1 and ▶ Analyze. What does the animation show, '
            'and why can a four-sided bay not hold its shape?',
        ),
    },
    'pratt': {
        'goal': 'In a Pratt truss the diagonals hang in tension and the '
                'verticals push.',
        'questions': (
            '▶ Analyze. Are the diagonals in tension or compression? And '
            'the verticals?',
            'Load the Howe truss: the same box, diagonals the other way. '
            'What changes sign?',
            'Steel likes tension better than compression. Why? Hint: '
            'Explain rod… on a vertical and on a diagonal.',
        ),
    },
    'howe': {
        'goal': 'The Howe truss is the Pratt with its diagonals turned '
                'round: now they push and the verticals hang.',
        'questions': (
            '▶ Analyze. Which rods are in compression now: the diagonals '
            'or the verticals?',
            'The diagonals are longer than the verticals. Which truss '
            'needs heavier diagonals against buckling, Pratt or Howe?',
            'Compare the score with the Pratt truss. Which carries the '
            'same load with less steel?',
        ),
    },
    'king_post': {
        'goal': 'The simplest roof truss: the rafters push, the tie holds '
                'their feet together.',
        'questions': (
            '▶ Analyze. Which rod carries nothing at all, and why?',
            'Add a load at the middle of the tie (node 1) and ▶ Analyze. '
            'What does the post do now?',
            'Delete rod 1 (half of the tie) and ▶ Analyze. What do the '
            'feet of the rafters do without it?',
        ),
    },
    'fink': {
        'goal': 'The web rods of a Fink truss prop each rafter at '
                'mid-length, so the rafters buckle over half their '
                'length.',
        'questions': (
            'Tick "Colour by utilisation". Which rafter piece is the '
            'most used? Explain rod… -- what governs it?',
            '▶ Play load. Does any rod reach its capacity? How many '
            'times this load could the truss carry?',
            'Which web rods are in tension, and which push?',
        ),
    },
    'cantilever': {
        'goal': 'A bracket off a wall is a truss upside down: now the top '
                'chord is pulled and the bottom one pushes.',
        'questions': (
            '▶ Analyze. Which chord is in tension? Compare with the '
            'Warren truss.',
            'Look at the two wall reactions. One pulls, one pushes: '
            'which, and why must they be so large?',
            'Show deformed. Where does the bracket move most?',
        ),
    },
    'vierendeel': {
        'goal': 'No diagonals: the joints are rigid, so the rods bend to '
                'keep the bays square.',
        'questions': (
            '▶ Analyze and look at the moment diagrams below. Where are '
            'the moments largest?',
            'Select every rod and press "Set Pinned", then ▶ Analyze. '
            'What happens, and why?',
            'Compare the score with the Warren truss of the same span. '
            'What does bending cost in steel?',
        ),
    },
    'missing_diagonal': {
        'goal': 'One bay has lost its diagonal. A four-sided bay with '
                'pinned corners folds like a parallelogram.',
        'questions': (
            '▶ Analyze. Which bay moves in the animation?',
            'Add one rod that stops it moving and ▶ Analyze again. Does '
            'it matter which diagonal of the bay you choose?',
            'Read the line under Analyze: how many ways can it move, and '
            'how many rods does it take to stop them?',
        ),
    },
    'single_load': {
        'goal': 'With one load, many rods of a truss carry nothing. They '
                'are not useless: they hold the others in line.',
        'questions': (
            '▶ Analyze and tick "Hide zero-force rods". Which rods '
            'disappeared?',
            'Move the load to another bottom node: the same rods stay '
            'idle. Now put it on node 7 (top middle). Which idle rod '
            'starts working? Look at its joint: two rods in line, one '
            'more, and no load -- that third rod can carry nothing.',
            'If the idle rods were removed, would the truss still stand? '
            'Read the line under Analyze before you try.',
        ),
    },
}


def get(key):
    """(title, model, lesson) for an example key."""
    for k, title, build in EXAMPLES:
        if k == key:
            return title, build(), LESSONS[k]
    raise KeyError(key)
