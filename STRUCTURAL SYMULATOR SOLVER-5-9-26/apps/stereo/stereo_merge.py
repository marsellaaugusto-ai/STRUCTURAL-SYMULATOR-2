"""Merge several models into one structure (roadmap v2 4.5).

Designing by parts -- roof, columns, bracing, each its own workbook -- and
combining them: the second model's nodes that land on the first's (within a
tolerance, 1 mm by default) become the same joint, its rods are re-indexed
onto the combined node list, and every rod keeps its OWN properties.

What happens where the two meet, decided here once:

  * A rod that ends up between the same two nodes as a rod already there
    is NOT added a second time -- two coincident rods would double that
    path's stiffness and its steel. The first model's rod, and so its
    section, is kept, and the count is reported. Nothing is averaged.
  * A rod whose two ends merge into one node is dropped: it has no length.
  * Loads on a merged node ADD: each part carried its own share of the load
    at that joint, and the joint carries both.
  * Supports on a merged node COMBINE: a direction restrained in either
    model is restrained in the result. Being stricter is the safe reading
    of two parts each saying "this is held".
  * Groups come along with their rods re-indexed; a name already used gets
    the part's label added rather than silently joining another group.
"""
import math

DEFAULT_TOL_M = 0.001


class _Grid:
    """A spatial hash so finding a coincident node is not O(n^2)."""

    def __init__(self, tol):
        self.tol = max(float(tol), 1e-12)
        self.cells = {}

    def _key(self, p):
        return tuple(int(math.floor(c / self.tol)) for c in p)

    def add(self, i, p):
        self.cells.setdefault(self._key(p), []).append((i, p))

    def find(self, p):
        kx, ky, kz = self._key(p)
        best, best_d = None, None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for i, q in self.cells.get((kx + dx, ky + dy, kz + dz), ()):
                        d = math.dist(p, q)
                        if d <= self.tol and (best_d is None or d < best_d):
                            best, best_d = i, d
        return best


def merge_models(base, part, tol=DEFAULT_TOL_M, label='part'):
    """Merge `part` into `base`. Both are dicts with 'nodes', 'members',
    'loads', 'supports' and optionally 'groups' and 'profiles'. Returns
    (merged, report); neither input is modified.

    `report` holds: nodes_added, nodes_merged, members_added,
    members_duplicate, members_degenerate, loads_added, supports_added,
    supports_combined, groups_added, groups_renamed, profiles_conflicting.
    """
    from apps.stereo import stereo_groups as sgp
    nodes = [tuple(p) for p in base['nodes']]
    members = [dict(m) for m in base['members']]
    loads = [dict(ld) for ld in base.get('loads') or ()]
    supports = [dict(s, dofs=dict(s['dofs'])) if s.get('dofs') else dict(s)
                for s in base.get('supports') or ()]
    groups = [dict(g, members=set(g['members']))
              for g in base.get('groups') or ()]
    profiles = dict(base.get('profiles') or {})
    rep = dict(nodes_added=0, nodes_merged=0, members_added=0,
               members_duplicate=0, members_degenerate=0, loads_added=0,
               supports_added=0, supports_combined=0, groups_added=0,
               groups_renamed=0, profiles_conflicting=[])

    grid = _Grid(tol)
    for i, p in enumerate(nodes):
        grid.add(i, p)
    node_map = {}
    for i, p in enumerate(part['nodes']):
        p = tuple(float(c) for c in p)
        hit = grid.find(p)
        if hit is None:
            nodes.append(p)
            hit = len(nodes) - 1
            grid.add(hit, p)
            rep['nodes_added'] += 1
        else:
            rep['nodes_merged'] += 1
        node_map[i] = hit

    have = {frozenset((m['a'], m['b'])): j for j, m in enumerate(members)}
    member_map = {}
    for j, m in enumerate(part['members']):
        a, b = node_map[m['a']], node_map[m['b']]
        if a == b:
            rep['members_degenerate'] += 1
            continue
        key = frozenset((a, b))
        if key in have:
            rep['members_duplicate'] += 1
            member_map[j] = have[key]
            continue
        members.append(dict(m, a=a, b=b))
        have[key] = len(members) - 1
        member_map[j] = len(members) - 1
        rep['members_added'] += 1

    for ld in part.get('loads') or ():
        loads.append(dict(ld, node=node_map[ld['node']]))
        rep['loads_added'] += 1

    from apps.stereo.stereo_math import support_restraints
    by_node = {s['node']: s for s in supports}
    for s in part.get('supports') or ():
        n = node_map[s['node']]
        if n not in by_node:
            new = dict(s, node=n)
            if s.get('dofs'):
                new['dofs'] = dict(s['dofs'])
            supports.append(new)
            by_node[n] = new
            rep['supports_added'] += 1
            continue
        mine = by_node[n]
        r1, r2 = support_restraints(mine), support_restraints(s)
        combined = {d: bool(r1[d] or r2[d]) for d in r1}
        if combined != r1:
            # No preset names an arbitrary combination: the restraints go in
            # explicitly and the preset is dropped (support_restraints reads
            # the dofs alone then).
            mine['dofs'] = combined
            mine.pop('type', None)
            rep['supports_combined'] += 1

    names = {g['name'] for g in groups}
    next_id = 1 + max((g['id'] for g in groups), default=0)
    id_map = {}
    for g in part.get('groups') or ():
        id_map[g['id']] = next_id
        next_id += 1
    for g in part.get('groups') or ():
        name = g['name']
        if name in names:
            name = '%s (%s)' % (name, label)
            rep['groups_renamed'] += 1
        names.add(name)
        own = set()
        for j in g['members']:
            if j in member_map:
                own.add(member_map[j])
        groups.append({'id': id_map[g['id']], 'name': name,
                       'parent': id_map.get(g['parent']),
                       'members': own})
        rep['groups_added'] += 1
    # Rule 1 -- a rod in one group only. A rod the part grouped that landed
    # on a base rod stays where the base had it.
    seen = set()
    for g in groups:
        g['members'] -= seen
        seen |= g['members']

    for name, pdata in (part.get('profiles') or {}).items():
        if name in profiles and profiles[name] != pdata:
            rep['profiles_conflicting'].append(name)
            continue
        profiles.setdefault(name, dict(pdata))

    # where each of the part's nodes and rods went -- a paste carries rod
    # loads, roof-load areas and group membership across with these
    rep['node_map'] = dict(node_map)
    rep['member_map'] = dict(member_map)
    return ({'nodes': nodes, 'members': members, 'loads': loads,
             'supports': supports, 'groups': groups, 'profiles': profiles},
            rep)


def describe(rep, n_base_members, n_part_members):
    """The summary the roadmap asks for, plus what was decided at the seam."""
    lines = ['Merged %d node(s), combined %d + %d members. %d coincident '
             'node(s) were merged.' % (rep['nodes_added'], n_base_members,
                                       rep['members_added'],
                                       rep['nodes_merged'])]
    if rep['members_duplicate']:
        lines.append('%d rod(s) lay on a rod already there and were not added '
                     'twice (the first model\'s section kept).'
                     % rep['members_duplicate'])
    if rep['members_degenerate']:
        lines.append('%d rod(s) shrank to nothing when their ends merged and '
                     'were dropped.' % rep['members_degenerate'])
    if rep['supports_combined']:
        lines.append('%d support(s) at a shared joint combined: a direction '
                     'held in either model is held.' % rep['supports_combined'])
    if rep['groups_renamed']:
        lines.append('%d group name(s) were already used and got the file\'s '
                     'name added.' % rep['groups_renamed'])
    if rep['profiles_conflicting']:
        lines.append('Profile(s) %s differ between the files; the first '
                     'file\'s definition is kept.'
                     % ', '.join(rep['profiles_conflicting'][:5]))
    return lines
