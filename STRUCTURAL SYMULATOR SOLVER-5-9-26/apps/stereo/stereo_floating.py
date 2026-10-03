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


def _upper_nodes(nodes, members, rods):
    """The piece's upper joints: the top half by height (all of them for a
    flat piece), which is where slings hook on."""
    ns = sorted(slift.nodes_of(members, rods))
    if not ns:
        return []
    zs = [nodes[n][2] for n in ns]
    lo, hi = min(zs), max(zs)
    if hi - lo < 1e-6:
        return ns
    cut = lo + 0.5 * (hi - lo)
    return [n for n in ns if nodes[n][2] >= cut - 1e-9]


def _nearest(nodes, cands, x, y, taken):
    pool = [n for n in cands if n not in taken] or list(cands)
    return min(pool, key=lambda n: (nodes[n][0] - x) ** 2
               + (nodes[n][1] - y) ** 2)


def pick_nodes(nodes, members, rods, rule):
    """The joints rule `rule` picks on the piece `rods`, sorted.

      'corners'      the upper joints nearest the four corners of the
                     piece's plan;
      'corners_mid'  those, and the ones nearest the middle of each side;
      'chords'       along the piece's long axis, on each top chord, the
                     joints nearest a quarter and three quarters of its
                     length -- how a long truss is usually picked.
    """
    cands = _upper_nodes(nodes, members, rods)
    if not cands:
        return []
    xs = [nodes[n][0] for n in cands]
    ys = [nodes[n][1] for n in cands]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    taken = []
    if rule in ('corners', 'corners_mid'):
        spots = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        if rule == 'corners_mid':
            xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
            spots += [(xm, y0), (x1, ym), (xm, y1), (x0, ym)]
        for x, y in spots:
            n = _nearest(nodes, cands, x, y, taken)
            if n not in taken:
                taken.append(n)
        return sorted(taken)
    if rule == 'chords':
        along = 0 if (x1 - x0) >= (y1 - y0) else 1
        across = 1 - along
        lo, hi = (x0, x1) if along == 0 else (y0, y1)
        span = hi - lo
        # the top chords: the upper joints in lines along the long axis,
        # told apart by their position across it
        width = (y1 - y0) if along == 0 else (x1 - x0)
        tol = max(0.05 * width, 0.05)
        lines = []
        for n in sorted(cands, key=lambda n: nodes[n][across]):
            c = nodes[n][across]
            if lines and abs(lines[-1][0] - c) <= tol:
                lines[-1][1].append(n)
            else:
                lines.append([c, [n]])
        # outermost chords only: a module's inner lines are not picked
        if len(lines) > 2:
            lines = [lines[0], lines[-1]]
        for _c, line in lines:
            for f in (0.25, 0.75):
                t = lo + f * span
                n = min(line, key=lambda n: abs(nodes[n][along] - t))
                if n not in taken:
                    taken.append(n)
        return sorted(taken)
    raise ValueError('Unknown pick rule %r.' % rule)


def plan_spread(nodes, picks, hook_xy):
    """Each pick's horizontal distance from the point under the hook."""
    hx, hy = hook_xy
    return [math.hypot(nodes[p][0] - hx, nodes[p][1] - hy) for p in picks]
