"""Which part of the model a crane lifts.

A crane's job in this app is to show how a piece reacts to being lifted --
the stress the lift itself puts into it. A file can hold more than one
piece: two trusses side by side, a roof and the columns it will stand on.
The lift used to take EVERY support in the file away, so lifting one truss
left the other floating with nothing holding it and the solve refused the
whole model as a mechanism.

So a lift is of a PIECE: by default whatever is connected to the joints the
slings hook onto, or a group the user names. Only that piece comes off its
supports; everything else stays where it stands. Kept free of Tk so it can
be tested on its own.
"""

CRANE_ROLES = ('crane_cable', 'crane_mast')


def _adjacency(members, skip_roles=CRANE_ROLES):
    adj = {}
    for j, m in enumerate(members):
        if m.get('role') in skip_roles:
            continue
        adj.setdefault(m['a'], []).append((m['b'], j))
        adj.setdefault(m['b'], []).append((m['a'], j))
    return adj


def connected_piece(members, seeds, skip_roles=CRANE_ROLES):
    """The rods connected, through any chain of rods, to any of the nodes
    `seeds` -- the piece the slings hook onto. A crane's own rods do not
    count as a connection: two pieces each on its own crane are still two
    pieces."""
    adj = _adjacency(members, skip_roles)
    seen_nodes = set()
    rods = set()
    stack = [n for n in seeds if n in adj]
    while stack:
        n = stack.pop()
        if n in seen_nodes:
            continue
        seen_nodes.add(n)
        for other, j in adj.get(n, ()):
            rods.add(j)
            if other not in seen_nodes:
                stack.append(other)
    return sorted(rods)


def nodes_of(members, rods):
    out = set()
    for j in rods:
        out.add(members[j]['a'])
        out.add(members[j]['b'])
    return out


def joined_to_rest(members, rods, skip_roles=CRANE_ROLES):
    """The nodes the rods `rods` share with rods OUTSIDE them -- where a
    piece is still attached to the rest of the model. Empty for a piece
    that is free to be lifted on its own."""
    inside = set(rods)
    mine = nodes_of(members, inside)
    shared = set()
    for j, m in enumerate(members):
        if j in inside or m.get('role') in skip_roles:
            continue
        for e in ('a', 'b'):
            if m[e] in mine:
                shared.add(m[e])
    return sorted(shared)


def pieces(members, skip_roles=CRANE_ROLES):
    """Every separate piece, as a sorted list of rod ids, largest first."""
    left = set(j for j, m in enumerate(members)
               if m.get('role') not in skip_roles)
    out = []
    while left:
        j = min(left)
        piece = connected_piece(members, (members[j]['a'],), skip_roles)
        out.append(piece)
        left -= set(piece)
    out.sort(key=lambda p: (-len(p), p[0]))
    return out


def centre_of_gravity(nodes, members, rods, loads=()):
    """(x, y) in plan of the weight a lift raises: the downward nodal loads
    on the piece's joints, where there are any (they include its own weight
    when self-weight is on); otherwise the rods' own lengths, each at its
    middle -- the shape of a uniform steel piece's weight. None if there is
    nothing to weigh."""
    mine = nodes_of(members, rods)
    w = sx = sy = 0.0
    for ld in loads or ():
        n = ld.get('node')
        fz = float(ld.get('fz', 0.0) or 0.0)
        if n in mine and fz < 0 and n < len(nodes):
            w -= fz
            sx -= fz * nodes[n][0]
            sy -= fz * nodes[n][1]
    if w > 1e-12:
        return sx / w, sy / w
    import math
    for j in rods:
        a, b = nodes[members[j]['a']], nodes[members[j]['b']]
        L = math.dist(a, b)
        w += L
        sx += L * (a[0] + b[0]) / 2
        sy += L * (a[1] + b[1]) / 2
    return (sx / w, sy / w) if w > 1e-12 else None


def _plan_hull(pts):
    """Convex hull of plan points (x, y), counter-clockwise."""
    pts = sorted(set((round(x, 9), round(y, 9)) for x, y in pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def cog_outside_picks(nodes, picks, cog, tol=1e-6):
    """How far (m, in plan) the centre of gravity `cog` lies outside the
    pick points; 0.0 when it is inside or on their outline.

    Slings meeting at a hook straight over the centre of gravity can all
    pull only if the plumb line from the hook passes through the picks'
    outline -- seen from above, if the centre of gravity is inside the
    polygon the picks make. Outside it, the slings on the far side would
    have to push: they go slack and the piece tips until something else
    holds it. A real lift needs picks around the centre of gravity."""
    import math
    hull = _plan_hull([(nodes[i][0], nodes[i][1]) for i in picks])
    if not hull or cog is None:
        return 0.0
    cx, cy = cog
    if len(hull) == 1:
        return math.hypot(cx - hull[0][0], cy - hull[0][1])

    def seg_dist(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((cx - a[0]) * dx
                                                    + (cy - a[1]) * dy) / L2))
        return math.hypot(cx - a[0] - t * dx, cy - a[1] - t * dy)
    edges = list(zip(hull, hull[1:] + hull[:1])) if len(hull) > 2 \
        else [(hull[0], hull[1])]
    near = min(seg_dist(a, b) for a, b in edges)
    if len(hull) > 2 and all(
            (b[0] - a[0]) * (cy - a[1]) - (b[1] - a[1]) * (cx - a[0]) >= -tol
            for a, b in edges):
        return 0.0
    return 0.0 if near <= tol else near


# ── The crane report ──────────────────────────────────────────────────────
#
# What a lift plan needs from the solve: every sling's length, angle and
# tension, what the hook and the mast carry, what each pick point hands up,
# and -- the reason for the crane -- what the lift does to the piece: the
# members it puts over capacity.

# A cable's capacity from its diameter, when no working load limit is typed:
# the minimum breaking force of a 6x36 IWRC steel wire rope, grade 1770, is
# about 0.65 d^2 kN (d in mm), and a lifting sling works at a fifth of it.
ROPE_MBF_K = 0.65
ROPE_FACTOR = 5.0
# A sling flatter than this to the horizontal is flagged: its tension climbs
# as 1/sin(angle), and the horizontal pull it puts into the piece with it.
SLING_MIN_ANGLE_DEG = 45.0


def rope_wll_kN(d_mm, k=ROPE_MBF_K, factor=ROPE_FACTOR):
    """Working load limit (kN) of a wire rope of diameter `d_mm`."""
    d = float(d_mm)
    if d <= 0 or factor <= 0:
        return 0.0
    return k * d * d / factor


def crane_codes(members):
    """The crane codes in the model (K1, K2 ...), in order."""
    codes = {m.get('addon') for m in members
             if m.get('role') in CRANE_ROLES and m.get('addon')}
    return sorted(codes, key=lambda c: (len(c), c))


def crane_parts(members, code):
    """(cable rod ids, mast rod ids, hook node, anchor node) of crane
    `code`; the hook is the node every cable meets."""
    cables = [j for j, m in enumerate(members)
              if m.get('addon') == code and m.get('role') == 'crane_cable']
    masts = [j for j, m in enumerate(members)
             if m.get('addon') == code and m.get('role') == 'crane_mast']
    hook = anchor = None
    if cables:
        common = {members[cables[0]]['a'], members[cables[0]]['b']}
        for j in cables[1:]:
            common &= {members[j]['a'], members[j]['b']}
        hook = min(common) if common else None
    if masts and hook is not None:
        m = members[masts[0]]
        anchor = m['b'] if m['a'] == hook else m['a']
    return cables, masts, hook, anchor


def crane_report(nodes, members, results, checks, code, lifted_rods=None,
                 wll_kN=None):
    """Everything the crane report states about crane `code`, as numbers.

    `lifted_rods` is the piece it lifts; by default the piece connected to
    its pick points. `wll_kN` is each cable's working load limit, if one is
    set. Forces in kN, lengths in m, angles in degrees from horizontal.
    """
    import math
    cables, masts, hook, anchor = crane_parts(members, code)
    member_res = (results or {}).get('member_res') or []
    out = {'code': code, 'hook': hook, 'anchor': anchor,
           'hook_xyz': nodes[hook] if hook is not None else None,
           'cables': [], 'mast_N': None, 'anchor_reaction': None,
           'lifted_rods': [], 'over': [], 'worst': None, 'flat': [],
           'sum_vertical': 0.0, 'wll_kN': wll_kN, 'cable_over': []}
    if hook is None:
        return out
    hx, hy, hz = nodes[hook]
    for j in cables:
        m = members[j]
        pick = m['a'] if m['b'] == hook else m['b']
        px, py, pz = nodes[pick]
        dx, dy, dz = hx - px, hy - py, hz - pz
        L = math.sqrt(dx * dx + dy * dy + dz * dz)
        ang = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
        mr = member_res[j] if j < len(member_res) else {}
        N = float(mr.get('N', 0.0)) if mr else 0.0
        slack = bool(mr.get('slack')) or N <= 1e-9
        T = max(N, 0.0)
        row = {'rod': j, 'pick': pick, 'length': L, 'angle': ang,
               'T': T, 'slack': slack,
               'Tx': T * dx / L if L else 0.0, 'Ty': T * dy / L if L else 0.0,
               'Tz': T * dz / L if L else 0.0,
               'util': (T / wll_kN) if wll_kN else None}
        out['cables'].append(row)
        out['sum_vertical'] += row['Tz']
        if ang < SLING_MIN_ANGLE_DEG:
            out['flat'].append(row)
        if wll_kN and T > wll_kN:
            out['cable_over'].append(row)
    if masts and masts[0] < len(member_res):
        out['mast_N'] = float(member_res[masts[0]].get('N', 0.0))
    reactions = (results or {}).get('reactions') or {}
    if anchor in reactions:
        out['anchor_reaction'] = reactions[anchor]
    picks = [c['pick'] for c in out['cables']]
    rods = (list(lifted_rods) if lifted_rods is not None
            else connected_piece(members, picks))
    out['lifted_rods'] = rods
    if checks:
        rated = [(checks[j].get('util'), j) for j in rods
                 if j < len(checks) and checks[j]
                 and checks[j].get('checked')
                 and checks[j].get('util') is not None]
        if rated:
            out['worst'] = max(rated)
            out['over'] = sorted((r for r in rated if r[0] > 1.0),
                                 reverse=True)
    return out
