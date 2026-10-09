"""Components: one part, built more than once.

A GROUP says where rods belong. A COMPONENT says that several groups are
the SAME fabricated part -- drawn once, built N times -- and that is a
different claim with a different consequence:

    A component is sized for the WORST of its copies, never for the one
    you happened to click.

That is the whole reason this exists. Every copy of a component is cut from
the same drawing, so the section has to carry the heaviest load any of them
sees. Size it from the copy on screen and every copy still looks right, the
model still solves, and the two trusses at the gable -- the ones that take
the wind -- are under-strength with nothing on the drawing to say so. It is
the one mistake here that leaves no trace.

HOW IT IS STORED. A group carries `component`: the name of the part it is a
copy of. Groups sharing that name are copies of one another. Nothing else
is stored -- not which copy is the "original", not a separate definition
record, not a correspondence table. All of that is DERIVED from the
geometry by stereo_marks, for the same reason a piece mark is: a stored
relationship outlives the edit that broke it, and a model where the stored
answer and the steel disagree is worse than one that has to work it out.

WHICH ROD IS WHICH. Two copies of a part are the same shape in different
places, so there is a correspondence between their rods, and sizing needs
it: the bottom chord of this copy is the bottom chord of all of them.
stereo_marks.canonical_order spells a group's rods in an order that depends
only on its shape, so copies of one part come out in the same order and
zipping two of them IS the correspondence. A mirrored copy is read from its
mirrored spelling, so a left-hand truss still lines up with the right-hand
one it was made from.

DIVERGENCE IS REPORTED, NEVER REPAIRED. Nothing here stops someone editing
one copy until it no longer matches the others -- that is a real thing to
want to do mid-design. `verify` says when it has happened; what to do about
it (make that one unique, or put it back) is a decision, not a cleanup.
"""
from apps.stereo import stereo_groups as sgp
from apps.stereo import stereo_marks as sm

KEY = 'component'


# ── reading what is there ─────────────────────────────────────────────────

def name_of(group):
    """The component this group is a copy of, or None."""
    name = str((group or {}).get(KEY) or '').strip()
    return name or None


def components(groups):
    """{name: [groups]}, in the order the groups appear."""
    out = {}
    for g in groups or ():
        name = name_of(g)
        if name:
            out.setdefault(name, []).append(g)
    return out


def instances_of(groups, name):
    return components(groups).get(name, [])


def copies(groups, gid):
    """How many copies of this group's part there are, counting itself.

    1 means it is unique -- which is not the same as 'no component', and
    the difference matters: a component with one copy left is still a
    drawing someone may place again.
    """
    g = sgp.find(groups, gid)
    name = name_of(g)
    return len(instances_of(groups, name)) if name else 1


def siblings(groups, gid):
    """The OTHER copies of this group's part."""
    g = sgp.find(groups, gid)
    name = name_of(g)
    if not name:
        return []
    return [o for o in instances_of(groups, name) if o['id'] != gid]


def free_name(groups, base='Part'):
    """A component name nothing is using yet."""
    taken = set(components(groups))
    n = 1
    while '%s %d' % (base, n) in taken:
        n += 1
    return '%s %d' % (base, n)


# ── the two conversions ───────────────────────────────────────────────────

def make_component(groups, gids, name=None):
    """Declare these groups copies of one part. Returns the name used.

    A group with no rods of its own is refused: a branch of the tree is not
    a thing anyone fabricates, and letting one in would make 'the copies of
    this part' mean two different things.
    """
    gids = [g for g in gids]
    chosen = [sgp.find(groups, gid) for gid in gids]
    if any(g is None for g in chosen):
        raise ValueError('no group with that id')
    if not chosen:
        raise ValueError('nothing to make a component of')
    empty = [g['name'] for g in chosen if not g['members']]
    if empty:
        raise ValueError('%s holds no rods of its own, so it is a branch of '
                         'the tree rather than a part to fabricate.'
                         % ' and '.join(empty))
    name = (str(name).strip() if name else '') or free_name(groups)
    for g in chosen:
        g[KEY] = name
    return name


def make_unique(groups, gid):
    """Detach one copy: it keeps its rods and stops being a copy of
    anything. Every other copy, and the part itself, is untouched -- which
    is the whole difference between a unique group and a component."""
    g = sgp.find(groups, gid)
    if g is None:
        raise ValueError('no group with id %r' % (gid,))
    was = name_of(g)
    g.pop(KEY, None)
    return was


def explode_component(groups, name):
    """Stop treating these groups as one part. The groups all stay."""
    found = instances_of(groups, name)
    for g in found:
        g.pop(KEY, None)
    return len(found)


# ── do they still match? ──────────────────────────────────────────────────

def matching_groups(nodes, members, groups, gid, tol_mm=sm.DEFAULT_TOL_MM):
    """Every other group that is the same part as this one, mirrors too.

    What "Make component" offers: you point at one truss and it finds the
    others. Compared by shape alone, so it finds the ones someone drew
    separately and never connected in any way.
    """
    g = sgp.find(groups, gid)
    if g is None or not g['members']:
        return []
    drawn, mirror = sm.assembly_signature(nodes, members, g['members'],
                                          tol_mm)
    if drawn is None:
        return []
    out = []
    for other in groups:
        if other['id'] == gid or not other['members']:
            continue
        sig = sm.assembly_signature(nodes, members, other['members'], tol_mm)
        if sig[0] in (drawn, mirror) and sig[0] is not None:
            out.append(other)
    return out


def verify(nodes, members, groups, name, tol_mm=sm.DEFAULT_TOL_MM):
    """Are the copies of this component still the same part?

    {'name', 'instances', 'agree', 'differ', 'mirrored', 'unknown'} --
    `differ` is the groups whose shape no longer matches the rest. Someone
    editing one copy is a real thing to do; this says it happened and
    leaves the decision alone.
    """
    found = instances_of(groups, name)
    out = {'name': name, 'instances': len(found), 'agree': [], 'differ': [],
           'mirrored': [], 'unknown': []}
    if not found:
        return out
    sigs = {g['id']: sm.assembly_signature(nodes, members, g['members'],
                                           tol_mm) for g in found}
    # The shape most of the copies agree on is the part; a minority that
    # disagrees is what diverged, not the other way round.
    tally = {}
    for drawn, _m in sigs.values():
        if drawn is not None:
            tally[drawn] = tally.get(drawn, 0) + 1
    if not tally:
        out['unknown'] = list(found)
        return out
    ref = max(tally, key=lambda k: (tally[k], k))
    ref_mirror = None
    for g in found:
        if sigs[g['id']][0] == ref:
            ref_mirror = sigs[g['id']][1]
            break
    for g in found:
        drawn, _m = sigs[g['id']]
        if drawn is None:
            out['unknown'].append(g)
        elif drawn == ref:
            out['agree'].append(g)
        elif drawn == ref_mirror:
            out['mirrored'].append(g)
            out['agree'].append(g)
        else:
            out['differ'].append(g)
    return out


# ── which rod is which ────────────────────────────────────────────────────

def correspondence(nodes, members, groups, name, tol_mm=sm.DEFAULT_TOL_MM):
    """[[rod of copy 1, rod of copy 2, ...], ...] -- one row per position.

    Every row is the same rod of the part, once per copy. Rows come from
    the canonical spelling, so a copy that was moved, turned, or mirrored
    still lines up. Copies whose shape no longer matches are left out
    entirely rather than lined up wrongly -- see `verify`.
    """
    report = verify(nodes, members, groups, name, tol_mm)
    usable = [g for g in report['agree']]
    if len(usable) < 1:
        return []
    mirrored = {g['id'] for g in report['mirrored']}
    orders = []
    for g in usable:
        order = sm.canonical_order(nodes, members, g['members'], tol_mm,
                                   handed=-1 if g['id'] in mirrored else 1)
        if order is None:
            return []
        orders.append(order)
    width = min(len(o) for o in orders)
    if any(len(o) != width for o in orders):
        return []
    return [list(row) for row in zip(*orders)]


def matching_rods(nodes, members, groups, rods, tol_mm=sm.DEFAULT_TOL_MM):
    """Every rod that is the same rod of the same part as one of `rods`.

    The set a section edit really lands on. Includes the rods given; a rod
    in no component contributes only itself, so this is always safe to use
    in place of the selection.
    """
    want = set(rods)
    out = set(want)
    owner = sgp.owner_of_rod(groups)
    by_name = {}
    for i in want:
        g = sgp.find(groups, owner.get(i))
        name = name_of(g)
        if name:
            by_name.setdefault(name, set()).add(i)
    for name, mine in by_name.items():
        for row in correspondence(nodes, members, groups, name, tol_mm):
            if mine & set(row):
                out |= set(row)
    return sorted(out)


# ── sized for the worst copy ──────────────────────────────────────────────

def envelope(nodes, members, groups, name, checks=None,
             tol_mm=sm.DEFAULT_TOL_MM):
    """One row per rod of the part: the worst of it across every copy.

    {'rods', 'worst_rod', 'worst_util', 'utils', 'length_m', 'profile',
     'spread'} -- `spread` being worst minus best, which is the number
    that says how wrong sizing from one copy would have been.

    Without `checks` the rows still come back, with no utilisations: the
    correspondence is useful before anything has been analysed.
    """
    rows = []
    for position, rods in enumerate(
            correspondence(nodes, members, groups, name, tol_mm)):
        utils = []
        for i in rods:
            u = None
            if checks and 0 <= i < len(checks):
                u = checks[i].get('util')
            utils.append(u)
        known = [(u, i) for u, i in zip(utils, rods) if u is not None]
        worst_u, worst_i = max(known) if known else (None, rods[0])
        best_u = min(u for u, _i in known) if known else None
        first = members[rods[0]] if 0 <= rods[0] < len(members) else {}
        rows.append({
            'position': position,
            'rods': list(rods),
            'utils': utils,
            'worst_rod': worst_i,
            'worst_util': worst_u,
            'best_util': best_u,
            'spread': (None if worst_u is None or best_u is None
                       else worst_u - best_u),
            'length_m': sm.rod_length(nodes, first) if first else 0.0,
            'profile': str(first.get('profile') or ''),
        })
    return rows


def governing(nodes, members, groups, name, checks=None,
              tol_mm=sm.DEFAULT_TOL_MM):
    """The rods that actually decide this part's sections: the worst copy
    of each position. Sizing from these is sizing the part."""
    return [r['worst_rod'] for r in envelope(nodes, members, groups, name,
                                             checks, tol_mm)]


def section_warning(groups, gid):
    """Said BEFORE a section edit, not after.

    A section goes on every copy, and that is the point rather than a side
    effect: the copies are one drawing, so they are one order of steel.
    Empty for a group that is not a component, which is precisely the
    difference the user is choosing between.
    """
    n = copies(groups, gid)
    if n <= 1:
        return ''
    return ('%s is built %d times. A section set here goes on all %d, and '
            'is sized for the worst of them -- they are one drawing.'
            % (name_of(sgp.find(groups, gid)), n, n))


def shape_warning(groups, gid):
    """Said BEFORE an edit that changes the SHAPE of one copy.

    And it says the opposite of the section warning, because this model is
    honest about what it can do. Sections are shared: one drawing, one
    order. Geometry is not -- each copy is its own rods, and moving a node
    in one of them moves it in that one. The copies then no longer match,
    and what was one part is two.

    Saying "this changes N copies" here would be the comfortable lie. The
    useful warning is the true one: nothing follows, and the part splits.
    """
    n = copies(groups, gid)
    if n <= 1:
        return ''
    name = name_of(sgp.find(groups, gid))
    return ('%s is built %d times, and changing the shape of this one does '
            'NOT change the others. They stop matching, and %s becomes two '
            'parts -- use Make unique first if that is what you want.'
            % (name, n, name))
