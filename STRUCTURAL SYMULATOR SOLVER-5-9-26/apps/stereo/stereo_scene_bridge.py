"""Between the flat model and the scene graph, in both directions.

This is the seam that lets the scene graph (apps/stereo/scene/) be used by a
tab whose model is still the flat `(nodes, members, groups)` triple that
`stereo_math.analyze` solves and every report reads. Kept free of Tk, so the
conversion is tested without a window.

THE ONE DECISION THAT SHAPES THE REST: the graph is DERIVED ON DEMAND, not
mirrored. `self.groups` is assigned in eleven places across five modules --
import, merge, paste, undo, example load, generate, the group panel -- and a
parallel document kept in step with all eleven would need a hook in each,
would be wrong the first time one was missed, and would be wrong SILENTLY,
because a stale graph still bakes. Building it from the flat model whenever
it is wanted cannot go stale. It is the same principle the graph itself
rests on, and the same one `stereo_groups` already applies to node
membership: a derived fact cannot drift, a stored one can.

WHAT THE CONVERSION ADDS, and what it cannot. A flat model has no local
frames -- there were never any to record -- so `graph_from_model` INTRODUCES
them, one per group, at the centroid of that group's own rods. That is not
an arbitrary choice: it is the pivot convention `stereo_transform` already
uses, so a group rotated through the graph turns in place exactly as the
arrow keys turn a selection today. With `localize=False` every frame is the
identity instead, which round-trips bit for bit and is what a comparison
between two workbooks wants.

What it cannot add is SHARING. Two identical trusses in a flat model are two
sets of rods, and nothing in the file says they are one part. The graph
cannot invent that -- but `scene.content_digest` can recognise it after the
fact, which is what `instanceable_groups` below reports: the groups that
could become one definition, for a user to decide about.
"""
import math

from apps.stereo import stereo_groups as sgp
from apps.stereo.scene import (
    GroupNode, JointPrimitive, RodPrimitive, SceneDocument, Transform,
    bake, content_digest,
)

#: Where a support's or load's node index is remembered on its joint, so the
#: trip back can put it on the right baked node.
JOINT_SUPPORT = 'support_%d'
JOINT_LOAD = 'load_%d'

#: Set on a GroupNode built from a `stereo_groups` record, so the trip back
#: can report which graph object was which group.
GROUP_ID_KEY = 'group_id'

#: Where a rod remembers which member index it was converted FROM.
#:
#: It has to be remembered, because the bake orders members by TREE
#: POSITION -- a grouped rod comes before an ungrouped one whatever their
#: original indices -- so a conversion renumbers the member list. Reports,
#: Excel sheets and saved comparisons all name members by index, so a
#: renumbering that is not reported is a set of references that silently
#: point at the wrong rods. `model_from_graph` strips this key off the baked
#: members (so the solver sees the dict it always did) and hands back the
#: map, which is exactly what `stereo_groups.remap_members` takes.
MEMBER_INDEX_KEY = '_src_rod'

# How far a node may move on a round trip through the graph before it is a
# problem rather than arithmetic. Centroid-relative coordinates recomposed by
# the bake land within a few ULPs of where they started; a nanometre is
# several thousand times that, and still a millionth of the weld tolerance,
# so nothing can weld differently because of it.
ROUND_TRIP_TOL_M = 1e-9


def _centroid(points):
    if not points:
        return (0.0, 0.0, 0.0)
    n = float(len(points))
    return tuple(sum(p[k] for p in points) / n for k in range(3))


# ── flat model -> graph ────────────────────────────────────────────────────

def graph_from_model(nodes, members, groups=(), supports=(), loads=(),
                     name='Model', localize=True, meta=None):
    """A SceneDocument holding the same structure as the flat model.

    Every rod goes in exactly one place: its group, or the document root
    when it is Ungrouped -- which is `stereo_groups`' rule 1 expressed as
    the tree it always wanted to be. Joints are NOT carried over as
    geometry: they are what the bake re-derives from coincident endpoints.
    Supports and loads do come over, as named JointPrimitives, so they stop
    being node indices that every renumber invalidates.
    """
    doc = SceneDocument(meta=dict(meta or {}))
    doc.root.name = name
    nodes = [tuple(float(c) for c in p) for p in nodes]

    # One GroupNode per record, parents first, so a child is always added to
    # a group that already exists.
    by_gid, world = {}, {}
    for record, _depth in sgp.walk(groups):
        gid = record['id']
        parent = by_gid.get(record.get('parent'))
        # Everything the record holds beyond its rods and its place in the
        # tree -- excluded, iteration, stage, position, component -- rides
        # along in the node's metadata. It is not geometry, so the graph
        # has no opinion about it; it is also the difference between a
        # round trip that preserves the model and one that quietly puts
        # excluded rods back into the analysis.
        keep = {k: v for k, v in record.items()
                if k not in ('id', 'name', 'parent', 'members', 'meta')}
        node = GroupNode(record.get('name') or ('Group %d' % gid),
                         meta=dict(keep, **{GROUP_ID_KEY: gid}))
        (parent if parent is not None else doc.root).add(node)
        by_gid[gid] = node

        frame = Transform()
        if localize:
            own = sgp.rods_of(groups, gid, deep=True)
            pts = [nodes[i] for i in sgp.nodes_of_rods(members, own)
                   if 0 <= i < len(nodes)]
            if pts:
                frame = Transform.translation(_centroid(pts))
        world[gid] = frame
        # The local frame is the world frame with the parent's divided out,
        # which is the only way a nested frame can be stored: a child that
        # kept its world frame as its local one would pick up its parent's
        # translation a second time at bake.
        up = world.get(record.get('parent'), Transform())
        node.set_local(up.inverse() @ frame)

    owner = sgp.owner_of_rod(groups)
    for i, m in enumerate(members):
        a, b = m.get('a'), m.get('b')
        if not (isinstance(a, int) and isinstance(b, int)):
            continue
        if not (0 <= a < len(nodes) and 0 <= b < len(nodes)):
            continue
        holder = by_gid.get(owner.get(i), doc.root)
        frame = world.get(owner.get(i), Transform()).inverse()
        # Everything the member dict carries except its endpoints: the
        # endpoints become geometry, and the rest -- section, connection,
        # role, profile, add-on code -- is what the bake puts back on the
        # baked member, so a graph round trip is section-preserving.
        rest = {k: v for k, v in m.items() if k not in ('a', 'b')}
        rest[MEMBER_INDEX_KEY] = i
        holder.add(RodPrimitive(frame.apply_point(nodes[a]),
                                frame.apply_point(nodes[b]),
                                name=(m.get('role') or 'Rod %d' % i),
                                meta=rest))

    # Supports and loads, as named anchors on the geometry rather than as
    # indices into a list that the next edit renumbers.
    # The RECORD travels with the joint, not just its position. Carrying
    # only the position means a scene opened on its own has to guess what
    # kind of support each one was, and the only safe-looking guess -- a pin
    # -- is a different structure that still analyses: a roller read back as
    # a pin removes a degree of freedom nobody removed, and the reactions
    # come out wrong with nothing on screen to say so.
    for s in supports or ():
        n = s.get('node')
        if isinstance(n, int) and 0 <= n < len(nodes):
            doc.root.add(JointPrimitive(
                nodes[n], JOINT_SUPPORT % n,
                meta={'support': {k: v for k, v in s.items() if k != 'node'}}))
    for ld in loads or ():
        n = ld.get('node')
        if isinstance(n, int) and 0 <= n < len(nodes):
            doc.root.add(JointPrimitive(
                nodes[n], JOINT_LOAD % n,
                meta={'load': {k: v for k, v in ld.items() if k != 'node'}}))
    return doc


def anchors_from_graph(doc, baked=None):
    """The supports and loads a document carries, as the app's own records.

    What `_open_scene_file` needs and `model_from_graph` cannot give it:
    model_from_graph RENUMBERS records a caller already has, while a scene
    opened on its own has none to renumber -- they are in the file, on the
    joints.
    """
    baked = baked if baked is not None else doc.bake()
    by_key = {}
    for obj in doc.root.walk():
        if obj.KIND == 'joint':
            by_key[obj.key] = obj.meta

    supports, loads = [], []
    for name, node in sorted(baked.joint_nodes.items()):
        key = name.rsplit('/', 1)[-1]
        meta = by_key.get(key) or {}
        if 'support' in meta:
            supports.append(dict(meta['support'], node=node))
        elif 'load' in meta:
            loads.append(dict(meta['load'], node=node))
        elif key.startswith('support_'):
            # A joint named as a support but carrying no record: a file from
            # before the record travelled, or a hand-edited one. Named so the
            # caller can say so rather than inventing a restraint.
            supports.append({'node': node, 'type': 'pin', 'assumed': True})
    return supports, loads


# ── graph -> flat model ────────────────────────────────────────────────────

def model_from_graph(doc, supports=(), loads=()):
    """Bake `doc` back into `(nodes, members, groups, remap)`.

    `groups` comes out in `stereo_groups`' own shape, so the group panel,
    the Groups sheet, every summary and every report read it as they always
    did. `remap` carries what moved:

        {'members': {old index: new index},   see MEMBER_INDEX_KEY
         'supports': [...], 'loads': [...],   the same records, renumbered
         'joints': {name: node index},
         'group_of': {graph object id: group id},
         'warnings': [...]}

    Supports and loads are renumbered by JOINT NAME, not by position, which
    is the whole point of carrying them as joints: a model that gained a rod
    at the front still has its restraints on the right joints.
    """
    baked = doc.bake()
    groups = baked.legacy_groups(doc.root)

    # The member list is in TREE order, not the order it was converted from.
    # Strip the provenance key back off, so what the solver gets is the
    # member dict it has always been handed, and keep the map.
    member_map = {}
    for new_index, m in enumerate(baked.members):
        old = m.pop(MEMBER_INDEX_KEY, None)
        if old is not None:
            member_map[old] = new_index

    # legacy_groups numbers its own ids 1..N; say which graph object each
    # one was, so a caller can map a selection across the conversion.
    group_of, counter = {}, [0]

    def number(obj):
        for child in obj.children():
            if child.is_group() or child.is_instance():
                counter[0] += 1
                group_of[child.id] = counter[0]
                number(child)

    number(doc.root)

    at = baked.joint_nodes

    def renumber(records, pattern):
        out = []
        for record in records or ():
            n = record.get('node')
            key = pattern % n if isinstance(n, int) else None
            hit = at.get(key)
            if hit is None:
                # The joint is gone: the rod it sat on was deleted, or the
                # record arrived without a node. Dropped, and SAID so --
                # a support silently landing on node 0 is a different
                # structure that still analyses.
                baked.warnings.append(
                    'the %s on node %r has no joint in the graph any more '
                    'and was dropped' % (pattern.split('_')[0], n))
                continue
            out.append(dict(record, node=hit))
        return out

    return baked.nodes, baked.members, groups, {
        'members': member_map,
        'supports': renumber(supports, JOINT_SUPPORT),
        'loads': renumber(loads, JOINT_LOAD),
        'joints': dict(at),
        'group_of': group_of,
        'warnings': list(baked.warnings),
        'baked': baked,
    }


# ── checking the two agree ────────────────────────────────────────────────

def compare_round_trip(nodes, members, groups=(), supports=(), loads=(),
                       localize=True, tol=ROUND_TRIP_TOL_M):
    """Convert, bake, and report every way the result differs. [] is a pass.

    This is the function that makes the migration safe to do a piece at a
    time: both paths can be run on the same model and held to agreeing,
    rather than the old one being replaced on the strength of an argument.
    """
    doc = graph_from_model(nodes, members, groups, supports, loads,
                           localize=localize)
    out_nodes, out_members, out_groups, remap = model_from_graph(
        doc, supports, loads)
    problems = list(remap['warnings'])

    if len(out_members) != len(members):
        problems.append('%d rods went in and %d came out'
                        % (len(members), len(out_members)))
        return problems

    # Followed through the remap, NOT by position: the bake orders members by
    # tree position, so comparing index for index compares different rods --
    # and would report every grouped model as broken while passing one whose
    # geometry really had moved.
    pairs = []
    for i in range(len(members)):
        j = remap['members'].get(i)
        if j is None:
            problems.append('rod %d did not come back' % i)
            continue
        pairs.append((i, members[i], out_members[j]))
    if problems:
        return problems

    # Node COUNT may legitimately differ: the flat model can hold a node no
    # rod uses, and the graph has no way to carry one (a joint is what
    # endpoints weld into). What must not differ is where the rods are.
    for i, was, now in pairs:
        for key in ('a', 'b'):
            p = nodes[was[key]]
            q = out_nodes[now[key]]
            if math.dist(p, q) > tol:
                problems.append('rod %d end %s moved %.3g m (%r -> %r)'
                                % (i, key, math.dist(p, q), p, q))
        for key, value in was.items():
            if key in ('a', 'b', 'length_m', MEMBER_INDEX_KEY):
                continue
            if now.get(key) != value:
                problems.append('rod %d lost %r: %r became %r'
                                % (i, key, value, now.get(key)))

    # Group membership, compared as the SETS OF RODS each group holds, since
    # the ids are renumbered by the conversion and comparing them would fail
    # on a correct round trip.
    def by_rods(gs, through=None):
        out = []
        for g in gs:
            if not g['members']:
                continue
            idx = sorted(through[i] for i in g['members']) if through else \
                sorted(g['members'])
            out.append(tuple(idx))
        return sorted(out)

    if by_rods(groups, remap['members']) != by_rods(out_groups):
        problems.append('group membership differs: %r became %r'
                        % (by_rods(groups), by_rods(out_groups)))

    names_in = sorted(g.get('name', '') for g in groups)
    names_out = sorted(g.get('name', '') for g in out_groups)
    if names_in != names_out:
        problems.append('group names differ: %r became %r'
                        % (names_in, names_out))

    for label, before, after in (('supports', supports, remap['supports']),
                                 ('loads', loads, remap['loads'])):
        if len(before or ()) != len(after):
            problems.append('%d %s went in and %d came out'
                            % (len(before or ()), label, len(after)))
            continue
        for was, now in zip(before or (), after):
            p, q = nodes[was['node']], out_nodes[now['node']]
            if math.dist(p, q) > tol:
                problems.append('a %s moved from %r to %r' % (label, p, q))
    return problems


# ── what the flat model could not say ─────────────────────────────────────

def instanceable_groups(doc):
    """Groups whose contents are the same part, as {digest: [groups]}.

    A flat model cannot record that two identical trusses are one part made
    twice, and the conversion cannot invent it. This finds it afterwards, by
    content, so the app can OFFER to make them one definition -- the sharing
    the flat model had no way to express. An offer, not a rule: a user may
    be keeping two apart on purpose.
    """
    from apps.stereo.scene import Definition, TransformPolicy

    by_digest = {}
    for obj in doc.root.walk():
        if not obj.is_group() or obj is doc.root:
            continue
        if not any(c.KIND == 'rod' for c in obj.walk()):
            continue
        # Digested as if it were already a definition, so a group and the
        # definition it would become hash alike -- otherwise promoting one
        # group would stop it matching the others it was promoted WITH.
        probe = Definition('probe', obj.name, obj.clone(),
                           policy=TransformPolicy.RIGID)
        probe.content.set_local(Transform())
        by_digest.setdefault(content_digest(probe), []).append(obj)
    return {k: v for k, v in by_digest.items() if len(v) > 1}
