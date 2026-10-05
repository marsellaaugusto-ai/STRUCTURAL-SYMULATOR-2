"""Pieces of a model that stand on nothing, and picking joints to lift by.

Kept free of Tk.

A file of iterations holds many separate pieces -- trusses, modules, whole
roofs -- and a piece with no support of its own makes the whole analysis
singular. The solver can only say "free to move"; this module says WHICH
pieces, so the app can name them by group and offer a way forward.

It also holds the pick rules the Crane panel offers ("Corners", "Corners +
mid sides", "Chords ¼–¾"): where slings usually go on a module or a truss.
"""
import math

from apps.stereo import stereo_lift as slift


def floating_pieces(members, supports, skip=()):
    """Every separate piece -- rods joined through shared nodes, crane rods
    and the `skip` rods not counting -- that touches no supported node.
    Sorted rod lists, largest first."""
    skip = set(skip)
    parent = {}

    def find(n):
        while parent.setdefault(n, n) != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n
    rods = [j for j, m in enumerate(members)
            if j not in skip and m.get('role') not in slift.CRANE_ROLES]
    for j in rods:
        a, b = find(members[j]['a']), find(members[j]['b'])
        if a != b:
            parent[a] = b
    held = {find(s['node']) for s in supports if s.get('node') in parent}
    pieces = {}
    for j in rods:
        root = find(members[j]['a'])
        if root not in held:
            pieces.setdefault(root, []).append(j)
    out = [sorted(p) for p in pieces.values()]
    out.sort(key=lambda p: (-len(p), p[0]))
    return out


def lowest_nodes(nodes, members, rods, tol=1e-3):
    """The nodes of `rods` at the piece's lowest level -- where it would
    stand."""
    ns = slift.nodes_of(members, rods)
    if not ns:
        return []
    zmin = min(nodes[n][2] for n in ns)
    return sorted(n for n in ns if nodes[n][2] <= zmin + tol)


# ── pick rules ─────────────────────────────────────────────────────────────

PICK_RULES = ('corners', 'corners_mid', 'chords')
PICK_RULE_LABELS = {'corners': 'Corners', 'corners_mid': 'Corners + mid sides',
                    'chords': 'Chords ¼–¾'}
# the same, short enough for three buttons in the side panel
PICK_RULE_BUTTONS = {'corners': 'Corners', 'corners_mid': 'Corners + mid',
                     'chords': 'Chords ¼–¾'}


def _nearest(nodes, cands, x, y, lift=0.05):
    """The candidate nearest (x, y) in plan, a higher joint winning a
    near-tie (slings hook on top). A spot whose nearest joint is already
    picked adds nothing -- a lower joint under it is no second pick."""
    return min(cands, key=lambda n: math.hypot(nodes[n][0] - x,
                                              nodes[n][1] - y)
               - lift * nodes[n][2])


def pick_nodes(nodes, members, rods, rule):
    """The joints rule `rule` picks on the piece `rods`, sorted.

      'corners'      the joints nearest the four corners of the piece's
                     plan (a higher one winning a near-tie);
      'corners_mid'  those, and the ones nearest the middle of each LONG
                     side -- of all four sides when the plan is about
                     square;
      'chords'       at a quarter and three quarters of the piece's long
                     axis, the two joints furthest apart across it -- both
                     chords of a truss at its quarter points.

    Every joint of the piece is a candidate, not only the highest ones: on
    a pitched truss or module the top half by height is one side of the
    ridge, and picks there leave the centre of gravity outside them.
    """
    cands = sorted(slift.nodes_of(members, rods))
    if not cands:
        return []
    xs = [nodes[n][0] for n in cands]
    ys = [nodes[n][1] for n in cands]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    taken = []

    def add(n):
        if n not in taken:
            taken.append(n)
    if rule in ('corners', 'corners_mid'):
        spots = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        if rule == 'corners_mid':
            xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
            lx, ly = x1 - x0, y1 - y0
            square = max(lx, ly) <= 1.25 * max(min(lx, ly), 1e-9)
            if square or lx >= ly:
                spots += [(xm, y0), (xm, y1)]
            if square or ly > lx:
                spots += [(x0, ym), (x1, ym)]
        for x, y in spots:
            add(_nearest(nodes, cands, x, y))
        return sorted(taken)
    if rule == 'chords':
        along = 0 if (x1 - x0) >= (y1 - y0) else 1
        across = 1 - along
        lo, hi = (x0, x1) if along == 0 else (y0, y1)
        for f in (0.25, 0.75):
            t = lo + f * (hi - lo)
            near = sorted(cands, key=lambda n: abs(nodes[n][along] - t))[:6]
            add(max(near, key=lambda n: (nodes[n][across], nodes[n][2])))
            add(min(near, key=lambda n: (nodes[n][across], -nodes[n][2])))
        return sorted(taken)
    raise ValueError('Unknown pick rule %r.' % rule)


def plan_spread(nodes, picks, hook_xy):
    """Each pick's horizontal distance from the point under the hook."""
    hx, hy = hook_xy
    return [math.hypot(nodes[p][0] - hx, nodes[p][1] - hy) for p in picks]
