"""Copy and paste of nodes and rods (round 2, item 7).

A copy is a self-contained piece of model -- its nodes, its rods with every
property, and, if asked, the supports, loads and group membership that hang
on them -- so it can be pasted into the same file or, through the system
clipboard as text, into another file or another window of the app.

A paste is a merge (stereo_merge.merge_models): a pasted node that lands on
an existing one IS that node, so a copy dropped against the structure joins
it, and a rod pasted exactly over an existing rod is not added twice. A
paste can be repeated as an array: N copies, each one step further on.

Kept free of Tk so it can be tested on its own.
"""
import json
import math

MAGIC = 'STEREO-CLIP/1'


def make_clip(nodes, members, sel_nodes=(), sel_members=(), supports=(),
              loads=(), load_nodes=None, member_loads=(), groups=(),
              profiles=None):
    """The selection as a clip: the selected rods, plus every rod with both
    ends among the selected nodes, and the nodes they need. Returns None
    when nothing would be copied."""
    sel_nodes = set(sel_nodes)
    rods = set(i for i in sel_members if 0 <= i < len(members))
    rods |= {i for i, m in enumerate(members)
             if m['a'] in sel_nodes and m['b'] in sel_nodes}
    keep = set(sel_nodes)
    for i in rods:
        keep.add(members[i]['a'])
        keep.add(members[i]['b'])
    keep = sorted(n for n in keep if 0 <= n < len(nodes))
    if not keep:
        return None
    nmap = {n: k for k, n in enumerate(keep)}
    rods = sorted(rods)
    rmap = {r: k for k, r in enumerate(rods)}
    c_nodes = [list(map(float, nodes[n])) for n in keep]
    c_members = []
    for r in rods:
        m = dict(members[r])
        m['a'], m['b'] = nmap[m['a']], nmap[m['b']]
        c_members.append(m)
    c_supports = []
    for s in supports or ():
        if s.get('node') in nmap:
            d = dict(s, node=nmap[s['node']])
            if s.get('dofs'):
                d['dofs'] = dict(s['dofs'])
            c_supports.append(d)
    c_loads = [dict(ld, node=nmap[ld['node']]) for ld in loads or ()
               if ld.get('node') in nmap]
    c_areas = {str(nmap[n]): float(a) for n, a in (load_nodes or {}).items()
               if n in nmap}
    c_mloads = [dict(ml, member=rmap[ml['member']])
                for ml in member_loads or () if ml.get('member') in rmap]
    c_groups = []
    for g in groups or ():
        own = sorted(rmap[r] for r in g.get('members', ()) if r in rmap)
        if own:
            c_groups.append({'id': g['id'], 'name': g['name'], 'rods': own})
    used = {m.get('profile') for m in c_members if m.get('profile')}
    c_profiles = {k: v for k, v in (profiles or {}).items() if k in used}
    # the reference point a paste-at-a-point puts on the clicked spot: the
    # node nearest the copy's lowest corner
    lo = [min(p[k] for p in c_nodes) for k in range(3)]
    ref = min(range(len(c_nodes)),
              key=lambda k: (math.dist(c_nodes[k], lo), k))
    return {'magic': MAGIC, 'nodes': c_nodes, 'members': c_members,
            'supports': c_supports, 'loads': c_loads, 'load_areas': c_areas,
            'member_loads': c_mloads, 'groups': c_groups,
            'profiles': c_profiles, 'ref': ref}


def to_text(clip):
    """The clip as clipboard text -- one line naming what it is, then JSON."""
    return MAGIC + '\n' + json.dumps(clip, default=_jsonable)


def _jsonable(o):
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    try:
        return float(o)
    except (TypeError, ValueError):
        return str(o)


def from_text(text):
    """The clip in clipboard text, or None if it is not one."""
    if not isinstance(text, str) or not text.startswith(MAGIC):
        return None
    try:
        clip = json.loads(text[len(MAGIC):].strip())
    except ValueError:
        return None
    if not isinstance(clip, dict) or clip.get('magic') != MAGIC:
        return None
    return clip


def ref_point(clip):
    return tuple(clip['nodes'][clip.get('ref', 0)])


def paste(model, clip, offsets, carry_supports=False, carry_loads=False,
          carry_groups=False, tol=0.001):
    """Paste `clip` once per offset (dx, dy, dz) into `model` -- a dict with
    nodes, members, loads, supports, groups, profiles, member_loads and
    load_nodes. Returns (new model, report, [new rod ids], [new node ids]).

    Groups: a pasted rod joins the group its original was in, when that
    group is in this model (by id, else by name); otherwise a group of that
    name is made. A pasted rod that lands on an existing rod keeps that
    rod's group -- it IS that rod."""
    from apps.stereo import stereo_merge as smg
    from apps.stereo import stereo_addon_codes as sac
    cur = {k: model.get(k) for k in ('nodes', 'members', 'loads',
                                     'supports', 'groups', 'profiles')}
    cur['groups'] = [dict(g, members=set(g['members']))
                     for g in model.get('groups') or ()]
    member_loads = [dict(ml) for ml in model.get('member_loads') or ()]
    load_nodes = dict(model.get('load_nodes') or {})
    total = {'nodes_added': 0, 'nodes_merged': 0, 'members_added': 0,
             'members_duplicate': 0, 'copies': 0}
    new_rods, new_nodes = [], []
    for off in offsets:
        dx, dy, dz = (float(c) for c in off)
        part = {'nodes': [(x + dx, y + dy, z + dz)
                          for x, y, z in clip['nodes']],
                'members': [dict(m) for m in clip['members']],
                'loads': ([dict(ld) for ld in clip.get('loads', ())]
                          if carry_loads else []),
                'supports': ([dict(s) for s in clip.get('supports', ())]
                             if carry_supports else []),
                'profiles': clip.get('profiles') or {}}
        n_before_nodes = len(cur['nodes'])
        n_before_rods = len(cur['members'])
        groups_kept = cur['groups']
        cur['groups'] = []          # merge must not touch them; done below
        cur, rep = smg.merge_models(cur, part, tol=tol, label='pasted')
        cur['groups'] = groups_kept
        nmap, rmap = rep['node_map'], rep['member_map']
        # each copy of an add-on is an add-on of its own: C1 pasted three
        # times is C2, C3, C4 -- not three rods' worth of one C2
        sac.renumber_copies(cur['members'],
                            range(n_before_rods, len(cur['members'])))
        for k in total:
            if k in rep:
                total[k] += rep[k]
        total['copies'] += 1
        new_rods += [j for j in range(n_before_rods, len(cur['members']))]
        new_nodes += [n for n in range(n_before_nodes, len(cur['nodes']))]
        if carry_loads:
            for ml in clip.get('member_loads', ()):
                j = rmap.get(ml['member'])
                if j is not None and j >= n_before_rods:
                    member_loads.append(dict(ml, member=j))
            for k, area in (clip.get('load_areas') or {}).items():
                n = nmap.get(int(k))
                if n is not None and n >= n_before_nodes:
                    load_nodes[n] = area
        if carry_groups:
            by_id = {g['id']: g for g in cur['groups']}
            by_name = {g['name']: g for g in cur['groups']}
            for cg in clip.get('groups', ()):
                g = by_id.get(cg['id'])
                if g is None or g['name'] != cg['name']:
                    g = by_name.get(cg['name'])
                if g is None:
                    nid = 1 + max((x['id'] for x in cur['groups']), default=0)
                    g = {'id': nid, 'name': cg['name'], 'parent': None,
                         'members': set()}
                    cur['groups'].append(g)
                    by_id[nid] = by_name[cg['name']] = g
                for r in cg['rods']:
                    j = rmap.get(r)
                    if j is not None and j >= n_before_rods:
                        g['members'].add(j)
    cur['member_loads'] = member_loads
    cur['load_nodes'] = load_nodes
    return cur, total, new_rods, new_nodes


def array_offsets(step, count):
    """`count` copies, the k-th `k` steps along: [(step), (2 step), ...]."""
    sx, sy, sz = (float(c) for c in step)
    return [(sx * k, sy * k, sz * k) for k in range(1, int(count) + 1)]
