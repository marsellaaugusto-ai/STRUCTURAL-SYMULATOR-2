"""Short codes for add-ons: C1 for a column, B1 for a reinforcement beam,
K1 for a crane, P1 for a welded shear panel.

An add-on is several rods (a column is its shaft, its capital and its
ties), and before this nothing tied them together: the rods carried a
role -- 'column_shaft', 'crane_cable' -- that said what KIND of part each
was, not WHICH column. Two columns were indistinguishable in the inspector,
the tables and the PDF. The code is written onto each rod (and onto a
panel) as `addon`, so it travels wherever the rod goes -- undo, the Excel
workbook, a group -- with no side table to keep in step.

Kept free of Tk so it can be tested on its own.
"""

import re

COLUMN, BEAM, CRANE, PANEL = 'column', 'beam', 'crane', 'panel'
PREFIX = {COLUMN: 'C', BEAM: 'B', CRANE: 'K', PANEL: 'P'}
KIND_OF = {v: k for k, v in PREFIX.items()}
NAME = {COLUMN: 'Column', BEAM: 'Beam', CRANE: 'Crane', PANEL: 'Panel'}

_CODE = re.compile(r'^([A-Z])(\d+)$')


def parse(code):
    """('C', 3) for 'C3'; None for anything that is not a code."""
    m = _CODE.match(str(code or '').strip())
    if not m or m.group(1) not in KIND_OF:
        return None
    return m.group(1), int(m.group(2))


def kind_of(code):
    p = parse(code)
    return KIND_OF[p[0]] if p else None


def describe(code):
    """'Column C3' -- what a reader is told, everywhere."""
    k = kind_of(code)
    return f'{NAME[k]} {code}' if k else str(code or '')


def used(members, panels=()):
    """Every code in use, rods and panels together."""
    out = {m.get('addon') for m in members if m.get('addon')}
    out |= {p.get('addon') for p in panels or () if p.get('addon')}
    return {c for c in out if parse(c)}


def next_code(kind, members, panels=()):
    """The next free code of this kind: one past the highest in use, so a
    deleted C2 is never handed out again while C3 still stands -- a code
    on an old printout keeps meaning the one thing."""
    pre = PREFIX[kind]
    top = max((parse(c)[1] for c in used(members, panels)
               if parse(c)[0] == pre), default=0)
    return f'{pre}{top + 1}'


def tag(members, ids, code):
    for i in ids:
        if 0 <= i < len(members):
            members[i]['addon'] = code
    return code


def index(members):
    """{code: [rod ids]} in natural order (C2 before C10)."""
    out = {}
    for i, m in enumerate(members):
        c = m.get('addon')
        if c and parse(c):
            out.setdefault(c, []).append(i)
    return dict(sorted(out.items(), key=lambda kv: (parse(kv[0])[0],
                                                    parse(kv[0])[1])))


def codes_of(members, ids):
    """The codes the rods `ids` belong to, in natural order."""
    cs = {members[i].get('addon') for i in ids if 0 <= i < len(members)}
    return sorted((c for c in cs if c and parse(c)),
                  key=lambda c: (parse(c)[0], parse(c)[1]))


def renumber_copies(members, new_ids, panels=()):
    """Give the add-on rods among `new_ids` -- rods just made by copying
    (a mirrored copy, a paste, a merged file) -- codes of their own where
    theirs is already taken by a rod outside `new_ids`. A copied column is
    a second column: leaving it C1 would make 'C1' mean two things. Rods
    that shared a code in the copy share the new one; a code nobody else
    holds is kept. Returns {old code: new code} for what changed."""
    new_set = set(new_ids)
    rest = [m for i, m in enumerate(members) if i not in new_set]
    taken = used(rest, panels)
    mapping = {}
    for i in sorted(new_set):
        if not 0 <= i < len(members):
            continue
        c = members[i].get('addon')
        if not c or not parse(c) or c not in taken:
            continue
        if c not in mapping:
            mapping[c] = next_code(kind_of(c),
                                   rest + [{'addon': v}
                                           for v in mapping.values()],
                                   panels)
        members[i]['addon'] = mapping[c]
    return mapping


def anchor(nodes, members, ids):
    """Where to put the code on a drawing: the middle of the add-on's
    rods -- beside a column's shaft, under a beam's span, not up on the
    grid it hangs from, where it would be lost among the grid's rods."""
    pts = []
    for i in ids:
        m = members[i]
        if m['a'] < len(nodes) and m['b'] < len(nodes):
            pts.append(nodes[m['a']])
            pts.append(nodes[m['b']])
    if not pts:
        return None
    x = sum(p[0] for p in pts) / len(pts)
    y = sum(p[1] for p in pts) / len(pts)
    z = sum(p[2] for p in pts) / len(pts)
    return (x, y, z)


# Which kind of add-on a rod's role says it belongs to -- for files made
# before add-ons had codes.
ROLE_KIND = {
    'crane_cable': CRANE, 'crane_mast': CRANE,
    'column_shaft': COLUMN, 'capital': COLUMN, 'capital_ring': COLUMN,
    'column_web': COLUMN, 'column_chord': COLUMN, 'column_tie': COLUMN,
    'reinf_chord': BEAM, 'reinf_web': BEAM,
}


def backfill(members, panels=()):
    """Give a code to every add-on rod that has none -- a file saved before
    codes existed. The rods of one add-on are the ones of its kind joined
    to each other (a crane's cables and mast meet at the hook; a column's
    shaft, capital and ties meet at their joints); each such cluster is one
    add-on and gets the next code. Returns the codes given, in order."""
    todo = [j for j, m in enumerate(members)
            if not m.get('addon') and m.get('role') in ROLE_KIND]
    given = []
    left = set(todo)
    while left:
        start = min(left)
        kind = ROLE_KIND[members[start]['role']]
        cluster, nodes_seen = {start}, {members[start]['a'],
                                        members[start]['b']}
        grew = True
        while grew:
            grew = False
            for j in list(left - cluster):
                m = members[j]
                if ROLE_KIND[m['role']] == kind and (
                        m['a'] in nodes_seen or m['b'] in nodes_seen):
                    cluster.add(j)
                    nodes_seen.update((m['a'], m['b']))
                    grew = True
        code = next_code(kind, members, panels)
        tag(members, cluster, code)
        given.append(code)
        left -= cluster
    for p in panels or ():
        if not p.get('addon'):
            p['addon'] = next_code(PANEL, members, panels)
            given.append(p['addon'])
    return given
