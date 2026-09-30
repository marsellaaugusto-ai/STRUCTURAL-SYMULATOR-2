"""Groups of rods, nested arbitrarily, for per-branch diagnosis.

Roadmap v2, 4.1. A GROUP is a named set of rods -- a branch of the
structure -- and groups nest to any depth, so a roof can hold bays, and a
bay can hold its own trusses.

    ON THE WORD "GROUP". It already means three unrelated things in this
    codebase, and confusing them would be easy:

      * `stereo_reports.PDF_SHEET_GROUPS` -- which SHEETS a report contains.
      * `stereo_plates`' gusset `group` -- the coplanar rods at one node.
      * `stereo_profiles.group_names()` -- the CATALOG's headings (IPE, HEA).

    None of those is this. This module is the only place a "group" is a
    user-named branch of the model, and nothing here touches the other
    three.

TWO RULES decide everything else, and they are not arbitrary:

  1. A ROD belongs to exactly ONE group. Assigning it to another moves it.
     A rod in two groups would be counted twice in every tonnage, every
     utilisation summary and every take-off, and the per-group totals would
     then not add up to the model -- which is the one check that catches a
     mis-assigned rod.

  2. A NODE belongs to EVERY group with a rod touching it, and this is
     DERIVED, never stored. Nodes are connection points, not quantities, so
     sharing them costs nothing -- and deriving membership means a shared
     node cannot be forgotten, mis-declared, or left behind when a rod
     moves. The shared nodes are exactly where load passes from one branch
     to the next, which is why they get a sheet of their own.

Everything not assigned anywhere is the implicit UNGROUPED set. It is not a
second mode with its own code path: it is a group like any other that
happens to have no entry in the list, so it cannot silently vanish from a
total.

A group is a plain dict, like every other record in this app:

    {'id': int, 'name': str, 'parent': int | None, 'members': set[int]}

`members` holds indices into the model's own member list. Nothing here
re-solves anything: a group's diagnosis is a VIEW of one whole-structure
solve (see stereo_reports.submodel), because a branch cut free from its
neighbours is a different structure -- usually a mechanism -- and its forces
would be wrong.
"""

UNGROUPED_NAME = 'Ungrouped'


# ── building and editing the tree ──────────────────────────────────────────

def new_group(groups, name, parent=None, members=()):
    """Append a group and return it. Ids are never reused within a list."""
    name = (str(name).strip() or 'Group')
    if parent is not None and find(groups, parent) is None:
        raise ValueError('no group with id %r to nest under' % (parent,))
    gid = (max((g['id'] for g in groups), default=0) + 1)
    g = {'id': gid, 'name': name, 'parent': parent, 'members': set()}
    groups.append(g)
    if members:
        assign(groups, gid, members)
    return g


def find(groups, gid):
    for g in groups:
        if g['id'] == gid:
            return g
    return None


def assign(groups, gid, member_idx):
    """Put these rods in `gid`, taking them out of wherever they were.

    Rule 1 in one place: this is the ONLY way a rod joins a group, so there
    is no path by which a rod ends up in two.
    """
    g = find(groups, gid)
    if g is None:
        raise ValueError('no group with id %r' % (gid,))
    want = {int(i) for i in member_idx}
    for other in groups:
        if other is not g:
            other['members'] -= want
    g['members'] |= want
    return g


def unassign(groups, member_idx):
    """Return these rods to Ungrouped."""
    want = {int(i) for i in member_idx}
    for g in groups:
        g['members'] -= want


def rename(groups, gid, name):
    g = find(groups, gid)
    if g is None:
        raise ValueError('no group with id %r' % (gid,))
    g['name'] = (str(name).strip() or g['name'])
    return g


def reparent(groups, gid, parent):
    """Move a group under another, or to the top with parent=None.

    Refuses to make a group its own ancestor: a cycle would make every
    recursive walk here loop forever, and the tree would be unprintable.
    """
    g = find(groups, gid)
    if g is None:
        raise ValueError('no group with id %r' % (gid,))
    if parent is not None:
        if find(groups, parent) is None:
            raise ValueError('no group with id %r to nest under' % (parent,))
        if parent == gid or parent in descendant_ids(groups, gid):
            raise ValueError('that would put %r inside itself' % (g['name'],))
    g['parent'] = parent
    return g


def delete(groups, gid, recursive=False):
    """Remove a group. Its rods go back to Ungrouped.

    Children are re-parented to the deleted group's own parent by default,
    so deleting a middle of the tree does not silently take a whole branch
    with it. `recursive=True` deletes the subtree.
    """
    g = find(groups, gid)
    if g is None:
        raise ValueError('no group with id %r' % (gid,))
    if recursive:
        doomed = {gid} | descendant_ids(groups, gid)
        groups[:] = [x for x in groups if x['id'] not in doomed]
        return
    for child in groups:
        if child['parent'] == gid:
            child['parent'] = g['parent']
    groups.remove(g)


# ── reading the tree ──────────────────────────────────────────────────────

def children(groups, gid):
    return [g for g in groups if g['parent'] == gid]


def descendant_ids(groups, gid):
    """Every id below `gid`, at any depth."""
    out = set()
    stack = [c['id'] for c in children(groups, gid)]
    while stack:
        i = stack.pop()
        if i in out:
            continue        # a cycle cannot be built through reparent(), but
            # a hand-written list could carry one; refuse to hang on it
        out.add(i)
        stack.extend(c['id'] for c in children(groups, i))
    return out


def depth(groups, gid):
    d, seen = 0, set()
    g = find(groups, gid)
    while g is not None and g['parent'] is not None and g['id'] not in seen:
        seen.add(g['id'])
        g = find(groups, g['parent'])
        d += 1
    return d


def walk(groups, parent=None):
    """(group, depth) in display order: each group followed by its subtree."""
    out = []
    for g in [x for x in groups if x['parent'] == parent]:
        out.append((g, depth(groups, g['id'])))
        out.extend(walk(groups, g['id']))
    return out


def rods_of(groups, gid, deep=True):
    """The rods in this group, and by default in every group under it.

    `deep` is what makes a subgroup's tonnage roll up into its parent's.
    """
    g = find(groups, gid)
    if g is None:
        return []
    out = set(g['members'])
    if deep:
        for i in descendant_ids(groups, gid):
            child = find(groups, i)
            if child:
                out |= child['members']
    return sorted(out)


def ungrouped_rods(groups, n_members):
    """Rule: everything unassigned is one implicit group, not a second mode."""
    taken = set()
    for g in groups:
        taken |= g['members']
    return [i for i in range(n_members) if i not in taken]


def nodes_of(groups, members, gid, deep=True):
    """The nodes this group touches -- DERIVED from its rods, never stored."""
    out = set()
    for i in rods_of(groups, gid, deep=deep):
        if 0 <= i < len(members):
            out.add(members[i]['a'])
            out.add(members[i]['b'])
    return sorted(out)


def nodes_of_rods(members, rod_idx):
    out = set()
    for i in rod_idx:
        if 0 <= i < len(members):
            out.add(members[i]['a'])
            out.add(members[i]['b'])
    return sorted(out)


# ── shared nodes: where the branches hand load to each other ──────────────

def shared_nodes(groups, members, n_members=None, include_ungrouped=True):
    """{node: [group ids...]} for every node more than one group touches.

    Membership is LEAF-level -- each group's own rods, not its subtree --
    because that is what makes the owner sets disjoint and the count add up.

    EVERY sharing is reported, including a parent with its own child. That
    was not the first design here: it seemed tidier to hide parent/child
    sharing, on the grounds that they always share and reporting it buries
    the joints where two separate branches meet. But a subgroup is often
    fabricated on its own and bolted in, so the joint between a bay and the
    roof it sits in is a real interface that has to be detailed --
    completeness first, because a joint left out of the document is the
    failure this sheet exists to prevent. `shared_node_kind` makes the
    distinction instead, so a report can sort cross-branch joints to the top
    without any of them going missing.

    `None` in the id list is the Ungrouped set, which shares nodes with the
    named groups like anything else. That boundary is usually the one nobody
    has thought about, so it is reported by default.
    """
    owner = {}
    for g in groups:
        for n in nodes_of_rods(members, g['members']):
            owner.setdefault(n, set()).add(g['id'])
    if include_ungrouped and n_members is not None:
        for n in nodes_of_rods(members, ungrouped_rods(groups, n_members)):
            owner.setdefault(n, set()).add(None)
    return {n: sorted(ids, key=lambda i: (i is None, i))
            for n, ids in sorted(owner.items()) if len(ids) > 1}


def is_ancestor(groups, maybe_ancestor, gid):
    """Is `maybe_ancestor` above `gid` in the tree? Ungrouped (None) never is."""
    if maybe_ancestor is None or gid is None:
        return False
    return gid in descendant_ids(groups, maybe_ancestor)


def shared_node_kind(groups, owner_ids):
    """'cross' or 'internal', for one shared node's list of owners.

    INTERNAL: every owner lies on one root-to-leaf path, so the joint is
    inside a single branch's own hierarchy -- a bay meeting the roof that
    contains it.

    CROSS: two owners exist that are not related by nesting, so the joint is
    where two separate branches hand load to each other. These are the ones
    to look at first, and the Ungrouped set counts as its own branch.
    """
    ids = list(owner_ids)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if not (is_ancestor(groups, a, b) or is_ancestor(groups, b, a)):
                return 'cross'
    return 'internal'


def shared_node_rows(groups, nodes, members, member_res=None, n_members=None,
                     include_ungrouped=True):
    """One row per shared node, ready for the report.

    Carries the interface FORCE each group hands into the joint, not only
    the group names: a list of node numbers says a joint is shared, while
    the resultant from each side is what a connection is detailed from.
    Cross-branch joints sort first, then by node.
    """
    if n_members is None:
        n_members = len(members)
    shared = shared_nodes(groups, members, n_members, include_ungrouped)
    rows = []
    for node, owners in shared.items():
        kind = shared_node_kind(groups, owners)
        sides = []
        for gid in owners:
            rods = interface_rods(groups, members, node, gid)
            g = find(groups, gid) if gid is not None else None
            side = {'group': gid,
                    'name': g['name'] if g else UNGROUPED_NAME,
                    'rods': rods}
            if member_res is not None:
                fx, fy, fz = interface_force(members, member_res, rods, node,
                                             nodes)
                side.update(Fx=fx, Fy=fy, Fz=fz,
                            F=(fx * fx + fy * fy + fz * fz) ** 0.5)
            sides.append(side)
        rows.append({'node': node, 'kind': kind, 'n_groups': len(owners),
                     'sides': sides})
    rows.sort(key=lambda r: (r['kind'] != 'cross', r['node']))
    return rows


def interface_rods(groups, members, node, gid):
    """The rods of `gid` that meet at `node` -- its side of the joint.

    This is what turns a list of shared node numbers into something an
    engineer can use: with the rods from each side named, the force each
    branch hands into the joint can be summed and detailed.
    """
    g = find(groups, gid) if gid is not None else None
    pool = (g['members'] if g is not None
            else ungrouped_rods(groups, len(members)))
    return sorted(i for i in pool
                  if 0 <= i < len(members)
                  and node in (members[i]['a'], members[i]['b']))


def interface_force(members, member_res, rod_idx, node, nodes):
    """The resultant (Fx, Fy, Fz) in kN that these rods pull on `node`.

    Axial only, which is all a pinned branch can hand over; a rigid branch
    also passes moment, and that is read from the member's own end actions
    rather than reconstructed here.
    """
    fx = fy = fz = 0.0
    for i in rod_idx:
        if not (0 <= i < len(members) and i < len(member_res)):
            continue
        m = members[i]
        N = member_res[i].get('N', 0.0) or 0.0
        a, b = m['a'], m['b']
        far = b if a == node else a
        if far == node:
            continue
        ax, ay, az = nodes[node]
        bx, by, bz = nodes[far]
        dx, dy, dz = bx - ax, by - ay, bz - az
        L = (dx * dx + dy * dy + dz * dz) ** 0.5
        if L < 1e-12:
            continue
        # A member in TENSION pulls the node TOWARDS its far end.
        fx += N * dx / L
        fy += N * dy / L
        fz += N * dz / L
    return (fx, fy, fz)


# ── totals, and the check that they add up ────────────────────────────────

def group_summary(groups, nodes, members, member_res=None, checks=None,
                  unit_weight_kN_m3=78.5):
    """One row per group (plus Ungrouped): rods, nodes, length, mass, worst.

    The rows are DEEP, so a parent's figures include its subtree -- which is
    what makes a roll-up mean anything -- and they therefore do not sum to
    the model. `totals_reconcile` is the sum check, and it uses leaf rods.
    """
    rows = []

    def one(gid, name, rod_idx, level):
        L_tot = 0.0
        mass = 0.0
        worst = None
        worst_rod = None
        for i in rod_idx:
            if not (0 <= i < len(members)):
                continue
            m = members[i]
            ax, ay, az = nodes[m['a']]
            bx, by, bz = nodes[m['b']]
            L = ((bx - ax) ** 2 + (by - ay) ** 2 + (bz - az) ** 2) ** 0.5
            L_tot += L
            A_m2 = (m.get('A', 0.0) or 0.0) * 1e-4      # cm2 -> m2
            mass += A_m2 * L * unit_weight_kN_m3
            if checks and i < len(checks):
                u = checks[i].get('util')
                if u is not None and (worst is None or u > worst):
                    worst, worst_rod = u, i
        return {'id': gid, 'name': name, 'level': level,
                'n_rods': len(rod_idx),
                'n_nodes': len(nodes_of_rods(members, rod_idx)),
                'length_m': L_tot, 'weight_kN': mass,
                'worst_util': worst, 'worst_rod': worst_rod}

    for g, lvl in walk(groups):
        rows.append(one(g['id'], g['name'], rods_of(groups, g['id'], deep=True),
                        lvl))
    rest = ungrouped_rods(groups, len(members))
    if rest:
        rows.append(one(None, UNGROUPED_NAME, rest, 0))
    return rows


def totals_reconcile(groups, nodes, members, unit_weight_kN_m3=78.5):
    """Do the per-group figures account for the whole model, once each?

    This is the sheet that catches a mis-assigned rod. It sums LEAF
    membership -- each group's own rods, not its subtree -- plus Ungrouped,
    and compares that against the model. Rule 1 makes the rod count exact,
    so a mismatch is a bug here, not a rounding question.
    """
    leaf = 0
    L_leaf = 0.0
    seen = set()
    for g in groups:
        leaf += len(g['members'])
        seen |= g['members']
    rest = ungrouped_rods(groups, len(members))
    counted = sorted(seen | set(rest))

    def length_of(idx):
        tot = 0.0
        for i in idx:
            if 0 <= i < len(members):
                m = members[i]
                ax, ay, az = nodes[m['a']]
                bx, by, bz = nodes[m['b']]
                tot += ((bx - ax) ** 2 + (by - ay) ** 2 + (bz - az) ** 2) ** 0.5
        return tot

    L_leaf = length_of(counted)
    L_all = length_of(range(len(members)))
    return {'rods_in_groups': leaf,
            'rods_ungrouped': len(rest),
            'rods_counted': leaf + len(rest),
            'rods_in_model': len(members),
            'length_counted_m': L_leaf,
            'length_in_model_m': L_all,
            'ok': (leaf + len(rest) == len(members)
                   and abs(L_leaf - L_all) < 1e-6 * max(1.0, L_all))}
