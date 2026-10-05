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
            mass += A_m2 * L * (float(m['gamma_kN_m3'])
                                if m.get('gamma_kN_m3') else unit_weight_kN_m3)
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


# ── surviving a renumber ───────────────────────────────────────────────────

def remap_members(groups, old_to_new):
    """Rewrite every group's membership after the member list was rebuilt.

    A group holds MEMBER INDICES, and several operations rebuild that list by
    filtering it -- deleting rods or nodes, and clearing an add-on, which also
    drops the rods it made. Every index after a dropped one then means a
    different rod. Left alone, a branch would quietly point at the wrong part
    of the structure, which is worse than having no branch at all: the report
    would still be produced, and it would be wrong.

    `old_to_new` maps a surviving old index to its new one; anything absent
    was deleted and leaves the group. Call it at every site that rebuilds
    `members`.
    """
    for g in groups:
        g['members'] = {old_to_new[i] for i in g['members'] if i in old_to_new}
    return groups


def member_remap(n_before, dropped):
    """{old index: new index} for a filter that removed `dropped`."""
    drop = set(dropped)
    out = {}
    new = 0
    for i in range(n_before):
        if i in drop:
            continue
        out[i] = new
        new += 1
    return out


# ── locking: a group is one object until it is opened for editing ─────────
#
# Asked for in these words: once made, a group is an uneditable object unless
# edit mode is opened for it; it moves as a whole but its parts cannot; its
# nodes cannot be moved, but rods can still be added to them; and while one
# group is being edited, everything outside it is blocked -- still drawn, for
# context, but not selectable, movable or deletable.
#
# So there is no per-group "locked" flag to forget to set. EVERY group is
# locked, always, and the one piece of state is which group -- if any -- is
# open. `editing` below is that group's id, or None when none is open.
#
# Groups behave like LAYERS, at every depth alike. Opening a group opens its
# OWN rods -- not its subgroups. A subgroup is a closed object inside its
# parent, exactly as a top-level group is a closed object in the model: it
# moves as a whole when one of its nodes is dragged, its parts stay put, and
# to change them it is opened in its turn. So a subgroup has every feature
# a group has, because the rules below never ask how deep a group sits --
# only what the CONTEXT is: the model when nothing is open, the open group's
# inside when one is.
#
# Three decisions the request left open, taken here so they are in one place:
#
#   * A group that shares a joint with ANOTHER group cannot be moved on its
#     own: the joint belongs to both, and moving it would change a group that
#     is not being moved. The refusal names the joints and the other group.
#     Ungrouped rods are not an object, so a joint shared only with them
#     moves, and they stretch to follow.
#   * Grabbing a node that two groups share takes BOTH groups: the joint is
#     part of each, so "the object this node belongs to" is both of them.
#   * A group's own section can be set while it is locked. The lock is about
#     geometry and membership -- the mistakes that cannot be seen until the
#     report is wrong -- and sizing a branch is what groups exist for.

def top_group(groups, gid):
    """The outermost group containing `gid` -- the object a click lands on."""
    g, seen = find(groups, gid), set()
    while g is not None and g['parent'] is not None and g['id'] not in seen:
        seen.add(g['id'])
        up = find(groups, g['parent'])
        if up is None:
            break
        g = up
    return g['id'] if g is not None else None


OWN = 'own'


def object_at(groups, gid, editing=None):
    """Which object `gid`'s rods are part of, seen from the current context.

    No group open: the outermost group holding `gid`. A group open: OWN if
    `gid` IS the open group (its own rods, editable one by one), the child of
    the open group that holds `gid` (a closed object inside it), or None
    when `gid` is outside the open group altogether.
    """
    if editing is None:
        return top_group(groups, gid)
    if gid == editing:
        return OWN
    g, seen = find(groups, gid), set()
    while g is not None and g['id'] not in seen:
        seen.add(g['id'])
        if g['parent'] == editing:
            return g['id']
        if g['parent'] is None:
            return None
        g = find(groups, g['parent'])
    return None


def context_objects(groups, editing=None):
    """The closed objects in the current context: the top-level groups,
    or the open group's direct subgroups."""
    return [g['id'] for g in groups if g['parent'] == editing]


def owner_of_rod(groups):
    """{rod index: gid} for every grouped rod, leaf level."""
    out = {}
    for g in groups:
        for i in g['members']:
            out[i] = g['id']
    return out


def rods_at_nodes(members):
    """{node: [rod indices]} -- the adjacency every rule below reads."""
    out = {}
    for i, m in enumerate(members):
        out.setdefault(m['a'], []).append(i)
        if m['b'] != m['a']:
            out.setdefault(m['b'], []).append(i)
    return out


def editable_rods(groups, editing, n_members):
    """The rods that may be changed one by one right now.

    With no group open these are the Ungrouped rods -- every grouped rod is
    part of a locked object. With a group open they are that group's OWN
    rods: its subgroups are closed objects inside it, as locked as any
    top-level group, until they are opened in their turn.
    """
    if editing is None:
        return set(ungrouped_rods(groups, n_members))
    g = find(groups, editing)
    return set(g['members']) if g else set()


def protected_rods(groups, editing):
    """Grouped rods that may not be changed one by one: everything but the
    open group's own rods (its subgroups are closed objects)."""
    g = find(groups, editing) if editing is not None else None
    inside = set(g['members']) if g else set()
    return set(owner_of_rod(groups)) - inside


def editable_nodes(groups, members, editing, n_nodes=None):
    """Nodes that may be selected and changed one by one right now.

    No group open: every node no grouped rod touches (a grouped node belongs
    to an object and moves only with it). A group open: the nodes of its
    own rods that no subgroup of it touches -- a subgroup's node belongs to
    that closed object, the same rule one level down. Everything outside
    the open group is blocked while editing. `n_nodes` counts nodes no rod
    touches at all, which the member list alone cannot see.
    """
    if editing is not None:
        g = find(groups, editing)
        own = set(nodes_of_rods(members, g['members'])) if g else set()
        inner = set()
        for d in descendant_ids(groups, editing):
            inner |= set(nodes_of_rods(members, find(groups, d)['members']))
        return own - inner
    touched = set(nodes_of_rods(members, owner_of_rod(groups)))
    if n_nodes is None:
        n_nodes = 1 + max((max(m['a'], m['b']) for m in members), default=-1)
    return {n for n in range(n_nodes) if n not in touched}


def node_groups(groups, members, node, adjacency=None):
    """The groups (leaf level) with a rod at `node`."""
    own = owner_of_rod(groups)
    adj = adjacency if adjacency is not None else rods_at_nodes(members)
    return sorted({own[i] for i in adj.get(node, ()) if i in own})


def _conflicts(groups, members, moving_nodes, moving_rods, editing, adj=None):
    """{node: [gid...]} -- moving nodes that a protected rod outside the move
    also uses. Moving such a node would change a group nobody opened."""
    if adj is None:
        adj = rods_at_nodes(members)
    guard = protected_rods(groups, editing) - set(moving_rods)
    own = owner_of_rod(groups)
    out = {}
    for n in moving_nodes:
        hit = sorted({own[i] for i in adj.get(n, ()) if i in guard})
        if hit:
            out[n] = hit
    return out


def move_plan(groups, members, selected_nodes, editing=None):
    """What a drag of these selected nodes is allowed to move.

    Returns {'nodes': [...], 'groups': [...], 'conflicts': {node: [gid]}}.
    With `conflicts` non-empty nothing may move.

    The same rule at every depth (see object_at): a node that belongs to a
    closed object in the current context brings that whole object along --
    the outermost group when nothing is open, a subgroup of the open group
    when one is. A node only the open group's own rods (or, with nothing
    open, no group at all) touch moves by itself. A selected node outside
    the open group is ignored rather than dragged along.
    """
    adj = rods_at_nodes(members)
    own = owner_of_rod(groups)
    sel = {int(n) for n in selected_nodes}
    objs = set()
    free = set()
    for n in sel:
        gids = {own[i] for i in adj.get(n, ()) if i in own}
        if editing is None and not gids:
            free.add(n)
            continue
        here = {object_at(groups, g, editing) for g in gids}
        found = {o for o in here if o not in (None, OWN)}
        if found:
            objs |= found
        elif OWN in here:
            free.add(n)
    rods = set()
    for t in objs:
        rods |= set(rods_of(groups, t, deep=True))
    nodes = set(nodes_of_rods(members, rods)) | free
    return {'nodes': sorted(nodes), 'groups': sorted(objs),
            'conflicts': _conflicts(groups, members, nodes, rods, editing, adj)}


def group_move_plan(groups, members, gid, editing=None):
    """Moving one named group -- and its subgroups -- as a whole."""
    rods = set(rods_of(groups, gid, deep=True))
    nodes = set(nodes_of_rods(members, rods))
    return {'nodes': sorted(nodes), 'groups': [gid],
            'conflicts': _conflicts(groups, members, nodes, rods, editing)}


def delete_blockers(groups, members, node_targets, member_targets, editing=None):
    """{gid or None: [rods]} that a delete would take but may not.

    Deleting a node takes every rod at it, so a node shared with anything
    outside what may be edited blocks the delete even when the node itself
    is inside. None as a key is the Ungrouped set, blocked while a group is
    open for the same reason as everything else outside it.
    """
    nodes = {int(n) for n in node_targets}
    going = {int(i) for i in member_targets}
    going |= {i for i, m in enumerate(members)
              if m['a'] in nodes or m['b'] in nodes}
    allowed = editable_rods(groups, editing, len(members))
    own = owner_of_rod(groups)
    out = {}
    for i in sorted(going - allowed):
        out.setdefault(own.get(i), []).append(i)
    return out


def rod_locked(groups, i, editing=None):
    """May this rod NOT be changed on its own right now?"""
    if editing is None:
        return int(i) in owner_of_rod(groups)
    g = find(groups, editing)
    return int(i) not in (g['members'] if g else set())


def node_locked(groups, members, n, editing=None):
    """May this node NOT be moved on its own right now?"""
    if editing is None:
        return bool(node_groups(groups, members, n))
    return int(n) not in editable_nodes(groups, members, editing)


def assign_blockers(groups, rod_idx, target, editing=None):
    """{gid: [rods]} this assignment would take out of a locked group.

    A rod leaves a group only while that group is open: `assign` MOVES a
    rod, so without this, adding a selection to one branch could silently
    empty another. `target` None means Ungroup.
    """
    own = owner_of_rod(groups)
    g_open = find(groups, editing) if editing is not None else None
    inside = set(g_open['members']) if g_open else set()
    out = {}
    for i in sorted({int(i) for i in rod_idx}):
        g = own.get(i)
        if g is None or g == target or i in inside:
            continue
        out.setdefault(g, []).append(i)
    return out


def target_open(groups, target, editing=None):
    """May rods be added to `target` without asking? Only if it is open."""
    if target is None:
        return editing is None
    return editing is not None and (
        target == editing or target in descendant_ids(groups, editing))


# ── an operation that rebuilds the model must not disturb a locked group ──

def geometry_violations(groups, nodes_before, members_before, nodes_after,
                        members_after, editing=None, tol=1e-9):
    """[(gid, rod, why)] for protected rods an operation removed or moved.

    For the operations that rebuild the whole node or member list from a
    rule -- the Module Editor's role edits, the add-ons -- and so cannot be
    checked one click at a time. Rods are matched by their END NODES, not
    their index, because several of these operations reorder the list.
    Node indices of existing nodes are assumed stable, which every one of
    them keeps (they append new nodes; the ones that drop nodes are checked
    before they run).
    """
    after = {}
    for i, m in enumerate(members_after):
        after.setdefault(frozenset((m['a'], m['b'])), i)
    own = owner_of_rod(groups)
    out = []
    for i in sorted(protected_rods(groups, editing)):
        if not (0 <= i < len(members_before)):
            continue
        m = members_before[i]
        if frozenset((m['a'], m['b'])) not in after:
            out.append((own[i], i, 'removed'))
            continue
        for n in (m['a'], m['b']):
            if n >= len(nodes_after) or n >= len(nodes_before):
                out.append((own[i], i, 'node %d gone' % n))
                break
            p, q = nodes_before[n], nodes_after[n]
            if max(abs(p[k] - q[k]) for k in range(3)) > tol:
                out.append((own[i], i, 'node %d moved' % n))
                break
    return out


def remap_by_endpoints(groups, members_before, members_after):
    """Carry every group across a rebuild that may have reordered the rods.

    Index-based remapping needs to be told what was dropped; this finds each
    rod again by its two end nodes, so it also survives an operation that
    inserts or reorders. A rod that is gone leaves its group.
    """
    after = {}
    for i, m in enumerate(members_after):
        after.setdefault(frozenset((m['a'], m['b'])), i)
    for g in groups:
        keep = set()
        for i in g['members']:
            if 0 <= i < len(members_before):
                m = members_before[i]
                j = after.get(frozenset((m['a'], m['b'])))
                if j is not None:
                    keep.add(j)
        g['members'] = keep
    return groups


def describe_conflicts(groups, conflicts, limit=6):
    """'node 12 (Roof, Bay 2), node 14 (Roof)' -- for a refusal message."""
    parts = []
    for n in sorted(conflicts)[:limit]:
        names = ', '.join(_name(groups, g) for g in conflicts[n])
        parts.append('node %d (%s)' % (n, names))
    more = len(conflicts) - limit
    return ', '.join(parts) + (' and %d more' % more if more > 0 else '')


def describe_rods(groups, by_group, limit=8):
    """'Roof: rods 3, 4, 9; Ungrouped: rod 12' -- for a refusal message."""
    parts = []
    for g in sorted(by_group, key=lambda k: (k is None, k if k is not None else 0)):
        rods = by_group[g]
        shown = ', '.join(str(i) for i in rods[:limit])
        if len(rods) > limit:
            shown += ' and %d more' % (len(rods) - limit)
        parts.append('%s: rod%s %s' % (_name(groups, g),
                                       's' if len(rods) != 1 else '', shown))
    return '; '.join(parts)


def _name(groups, gid):
    if gid is None:
        return UNGROUPED_NAME
    g = find(groups, gid)
    return g['name'] if g else '?'
