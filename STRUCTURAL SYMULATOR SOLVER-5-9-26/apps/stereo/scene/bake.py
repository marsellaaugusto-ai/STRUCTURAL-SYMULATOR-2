"""The bake: compiling the graph into the flat model the solver needs.

Clean-room note. This is a straightforward compiler pass -- recursive
descent accumulating a transform, then a spatial-hash weld -- written from
first principles. No other program's code or algorithms were consulted.

WHY A SEPARATE STAGE AT ALL. Because the two sides want opposite things and
neither is wrong:

    the EDITOR wants a hierarchy: local frames, shared definitions, a
    subtree that can be moved or placed again without disturbing anything
    around it;
    the SOLVER wants a flat global system: one node list, one member list,
    integer indices, because a stiffness matrix is assembled globally and
    knows nothing about who owns what.

Trying to serve both from one data structure is what produces the mess this
whole design is trying to avoid: either the hierarchy leaks into the solver,
or global indices leak into the hierarchy and every edit has to renumber
them (which is what `stereo_groups.remap_members` exists to clean up after).

So the graph is the SOURCE OF TRUTH and the flat model is a BUILD PRODUCT.
It is derived, never edited, and thrown away whenever the graph changes --
exactly as `stereo_groups` keeps node membership derived and never stored,
for exactly the same reason: a derived fact cannot go stale behind your back,
and a stored one can.

WHAT MAKES IT USABLE is the PROVENANCE. Every baked member records the path
it came from, so the compilation is reversible as a lookup: a per-group
diagnosis is `members_under(path)`, and nothing has to be re-solved to get
it. That is the same principle `stereo_reports.submodel` already works on --
a branch's forces are a VIEW of one whole-structure solve, because a branch
cut free of its neighbours is a different structure, usually a mechanism.

DETERMINISM IS A REQUIREMENT, NOT A NICETY. Reports, Excel exports and
saved comparisons all name members by index. The walk is therefore strictly
depth-first in child order, and node numbers are issued in first-touch
order, so the same graph always bakes to the same numbering -- and two
bakes of a graph that only moved can be compared member by member.
"""
import math

from apps.stereo.scene.objects import (
    GroupNode, InstanceNode, JointPrimitive, MeshPrimitive, RodPrimitive,
)
from apps.stereo.scene.transform import Transform

# Two endpoints this close are the same joint. Same value, and the same
# reasoning, as stereo_transform.MERGE_TOL_M: a mirrored copy lands exactly
# on its original wherever the original sits on the mirror plane, and those
# must be ONE node, not two stacked ones the solver would read as a hinge
# nobody drew.
WELD_TOL_M = 1e-6

# A rod shorter than this is a modelling mistake, not a short rod: its
# stiffness goes to infinity and the solve either blows up or quietly
# returns nonsense. Reported, never silently dropped -- dropping it would
# disconnect the structure somewhere the user cannot see.
MIN_ROD_M = 1e-9


class MemberOrigin:
    """Where one baked member came from. The reverse of the compilation."""

    __slots__ = ('path', 'primitive_id', 'definition_id', 'instance_path')

    def __init__(self, path, primitive_id, definition_id, instance_path):
        #: ids from the document root down to the rod, crossing instances.
        self.path = path
        self.primitive_id = primitive_id
        #: the definition this rod's geometry belongs to, or None if unique.
        self.definition_id = definition_id
        #: the path of the nearest enclosing instance -- which COPY this is.
        self.instance_path = instance_path

    def part_key(self):
        """Identifies the FABRICATED PART, ignoring which copy this is.

        Two instances of one truss give the same part_key for their
        corresponding rods and different `path`s. That split is what lets a
        take-off count parts while a diagnosis counts copies.
        """
        return (self.definition_id, self.primitive_id)

    def __repr__(self):
        return '<MemberOrigin path=%r def=%r>' % (self.path, self.definition_id)


class BakedModel:
    """The flat model, plus everything needed to read results back up.

    `nodes` and `members` are exactly the shapes `stereo_math.analyze`
    takes -- a list of (x, y, z) and a list of dicts with 'a', 'b', 'conn'
    -- so this plugs into the existing solver with no adapter.
    """

    def __init__(self):
        self.nodes = []
        self.members = []
        self.origins = []           # one MemberOrigin per member, same order
        self.joint_nodes = {}       # qualified joint name -> node index
        self.node_paths = {}        # node index -> set of contributing paths
        self.warnings = []
        self.meshes = []            # (path, world vertices, faces, meta)

    # ── reading results back up the hierarchy ──────────────────────────────

    def members_under(self, path):
        """Every member index at or below `path`.

        This replaces `stereo_groups.rods_of(deep=True)`. Note what is NOT
        needed any more: there is no membership set to keep in step with the
        geometry, because membership IS the path prefix.
        """
        prefix = tuple(path)
        n = len(prefix)
        return [i for i, o in enumerate(self.origins)
                if o.path[:n] == prefix]

    def nodes_under(self, path):
        """The joints a subtree touches -- derived, as rule 2 requires."""
        out = set()
        for i in self.members_under(path):
            out.add(self.members[i]['a'])
            out.add(self.members[i]['b'])
        return sorted(out)

    def shared_nodes(self, depth=1):
        """{node: [owner paths]} for joints more than one object touches.

        `depth` is which level counts as "an object": 1 for the top-level
        groups, 2 for their children, and so on. Reported for a parent with
        its own child as well, deliberately -- a subgroup is often
        fabricated on its own and bolted in, so the joint between a bay and
        the roof it sits in is a real interface somebody has to detail.
        That is the same call `stereo_groups.shared_nodes` already made and
        documented; it is right, and it is kept.
        """
        owners = {}
        for i, origin in enumerate(self.origins):
            owner = origin.path[:depth]
            for end in ('a', 'b'):
                owners.setdefault(self.members[i][end], set()).add(owner)
        return {node: sorted(paths) for node, paths in owners.items()
                if len(paths) > 1}

    def rollup(self, path, member_res=None, unit_weight_kN_m3=78.5):
        """Quantities for one subtree: count, length, and mass if sections
        are known. The per-branch take-off, without a second solve."""
        idx = self.members_under(path)
        total_len = sum(self.members[i].get('length_m', 0.0) for i in idx)
        out = {'members': len(idx), 'length_m': total_len,
               'nodes': len(self.nodes_under(path))}
        area = 0.0
        for i in idx:
            a = self.members[i].get('A')
            if a:
                area += a * self.members[i].get('length_m', 0.0)
        out['mass_kg'] = (area * unit_weight_kN_m3 * 1000.0 / 9.80665
                          if area else None)
        if member_res:
            forces = [member_res[i].get('N', 0.0) for i in idx
                      if i < len(member_res)]
            out['N_max_kN'] = max(forces) if forces else 0.0
            out['N_min_kN'] = min(forces) if forces else 0.0
        return out

    # ── what instancing does to design ─────────────────────────────────────

    def sibling_members(self, member_index):
        """The same PART in every other copy of its definition.

        With no definitions in play this is just `[member_index]`. With
        definitions it is the set a designer actually has to look at.
        """
        key = self.origins[member_index].part_key()
        if key[0] is None:
            return [member_index]
        return [i for i, o in enumerate(self.origins) if o.part_key() == key]

    def part_envelope(self, member_res, key=lambda r: r.get('N', 0.0)):
        """{part_key: {'min','max','worst_member','instances'}} over results.

        The consequence of sharing a definition, made explicit. One shared
        definition is one part, fabricated once; the load it must carry is
        the ENVELOPE over every copy, never the copy that happens to be
        selected. Sizing a component from one instance is the mistake this
        method exists to make impossible to miss -- and it is a mistake that
        leaves no trace on screen, because every copy looks right.
        """
        out = {}
        for i, origin in enumerate(self.origins):
            if i >= len(member_res):
                break
            value = key(member_res[i])
            slot = out.setdefault(origin.part_key(),
                                  {'min': value, 'max': value,
                                   'worst_member': i, 'instances': 0})
            slot['instances'] += 1
            if value > slot['max']:
                slot['max'] = value
            if value < slot['min']:
                slot['min'] = value
            if abs(value) > abs(key(member_res[slot['worst_member']])):
                slot['worst_member'] = i
        return out

    # ── the bridge to the code that already exists ─────────────────────────

    def legacy_groups(self, root, depth=1):
        """The baked model as `stereo_groups`' own flat records.

        The migration seam, and the reason nothing has to be rewritten at
        once: every report, Excel sheet and summary that currently reads
        `[{'id','name','parent','members'}]` keeps working against a baked
        scene graph. New code asks the graph; old code is handed this.

        A record also carries `meta`, the source object's own metadata,
        when it has any. A flat group record holds more than its rods --
        whether it is left out of the analysis, which iteration it belongs
        to, which fabricated part it is a copy of -- and a caller
        converting back needs somewhere to have kept it. Without it the
        trip through a graph silently drops every one of them, and
        "excluded" coming back as "included" changes the structure that
        gets solved.
        """
        groups, by_path = [], {}
        counter = [0]

        def emit(obj, parent_id, prefix):
            path = prefix + (obj.id,)
            counter[0] += 1
            gid = counter[0]
            by_path[path] = gid
            record = {'id': gid, 'name': obj.name or ('Group %d' % gid),
                      'parent': parent_id, 'members': set()}
            if obj.meta:
                record['meta'] = dict(obj.meta)
            groups.append(record)
            for child in obj.children():
                if child.is_group() or child.is_instance():
                    emit(child, gid, path)
            return gid

        # Paths on origins are ROOT-RELATIVE (the root's own id is stripped
        # at the end of bake), so the keys built here must be too, or every
        # member set comes out empty -- silently, which is the worst way for
        # a take-off to be wrong.
        for child in root.children():
            if child.is_group() or child.is_instance():
                emit(child, None, ())
        # A member belongs to the DEEPEST emitted object containing it, so
        # the leaf sets stay disjoint and the per-group totals add up to the
        # model -- which is the one check that catches a mis-assigned rod.
        for i, origin in enumerate(self.origins):
            for n in range(len(origin.path), 0, -1):
                gid = by_path.get(origin.path[:n])
                if gid is not None:
                    groups[gid - 1]['members'].add(i)
                    break
        return groups


class _Welder:
    """Coincident points become one node. First-touch numbering.

    A plain rounded-coordinate hash would split two points that straddle a
    cell boundary a nanometre apart, so each lookup checks the 27 cells
    around the point. That keeps it O(1) per point while making the answer
    independent of where the grid happens to fall -- which matters, because
    a model that welds differently after being moved by half a tolerance is
    a model whose node count depends on where it sits.
    """

    def __init__(self, nodes, tol=WELD_TOL_M):
        self.nodes = nodes
        self.tol = float(tol)
        self.cells = {}
        self.keyed = {}

    def _cell(self, p):
        t = self.tol
        return (int(math.floor(p[0] / t)), int(math.floor(p[1] / t)),
                int(math.floor(p[2] / t)))

    def weld(self, p, joint_key=None):
        """The node index for `p`. `joint_key` welds regardless of distance."""
        if joint_key is not None:
            hit = self.keyed.get(joint_key)
            if hit is not None:
                return hit
        cx, cy, cz = self._cell(p)
        t2 = self.tol * self.tol
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for idx in self.cells.get((cx + dx, cy + dy, cz + dz), ()):
                        q = self.nodes[idx]
                        d2 = ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2
                              + (p[2] - q[2]) ** 2)
                        if d2 <= t2:
                            if joint_key is not None:
                                self.keyed[joint_key] = idx
                            return idx
        idx = len(self.nodes)
        self.nodes.append((float(p[0]), float(p[1]), float(p[2])))
        self.cells.setdefault((cx, cy, cz), []).append(idx)
        if joint_key is not None:
            self.keyed[joint_key] = idx
        return idx


def bake(root, library=None, tol=WELD_TOL_M, max_depth=64):
    """Compile the graph into a BakedModel. Pure: `root` is not touched.

    The recursion of requirement 3 in its working form. One accumulated
    world matrix is carried down and multiplied by each local frame on the
    way; no node caches its world transform here, because inside a
    definition there is no single world transform to cache (see objects.py).
    Passing the accumulator down instead makes the whole question go away.
    """
    baked = BakedModel()
    welder = _Welder(baked.nodes, tol=tol)
    names = {}

    def qualified(trail, key):
        base = '/'.join([t for t in trail if t] + [key])
        if base not in names:
            names[base] = 1
            return base
        names[base] += 1
        return '%s#%d' % (base, names[base])

    def visit(obj, world, path, definition_id, instance_path, trail, depth):
        if depth > max_depth:
            baked.warnings.append(
                'stopped at %d levels deep under %r -- a definition placing '
                'itself would be infinite, and the library refuses that, so '
                'this is a hand-built or loaded file that got past it'
                % (max_depth, obj.name or obj.id))
            return
        here = world @ obj.local
        path = path + (obj.id,)

        if isinstance(obj, RodPrimitive):
            scope = instance_path
            a = welder.weld(here.apply_point(obj.a),
                            (scope, obj.joint_a) if obj.joint_a else None)
            b = welder.weld(here.apply_point(obj.b),
                            (scope, obj.joint_b) if obj.joint_b else None)
            pa, pb = baked.nodes[a], baked.nodes[b]
            length = math.dist(pa, pb)
            if a == b or length < MIN_ROD_M:
                baked.warnings.append(
                    'rod %r (%s) is zero length after placement and was not '
                    'baked: its ends weld to the same joint'
                    % (obj.name or obj.id, '/'.join(t for t in trail if t)))
                return
            # `meta` is merged in rather than nested so the record is the one
            # the solver already reads: 'a', 'b', 'conn', and whatever
            # section keys ('A', 'E', 'I', ...) the model put there.
            member = {'a': a, 'b': b, 'conn': 'pin'}
            member.update(obj.meta)
            member['a'], member['b'] = a, b
            member['length_m'] = length
            baked.members.append(member)
            baked.origins.append(MemberOrigin(path, obj.id, definition_id,
                                              instance_path))
            baked.node_paths.setdefault(a, set()).add(path)
            baked.node_paths.setdefault(b, set()).add(path)
            return

        if isinstance(obj, JointPrimitive):
            idx = welder.weld(here.apply_point(obj.at),
                              (instance_path, obj.key))
            baked.joint_nodes[qualified(trail, obj.key)] = idx
            baked.node_paths.setdefault(idx, set()).add(path)
            return

        if isinstance(obj, MeshPrimitive):
            baked.meshes.append((path,
                                 [here.apply_point(v) for v in obj.vertices],
                                 list(obj.faces), dict(obj.meta)))
            return

        if isinstance(obj, InstanceNode):
            if library is None:
                baked.warnings.append(
                    'instance %r skipped: no definition library was passed to '
                    'bake()' % (obj.name or obj.id,))
                return
            if not library.has(obj.definition_id):
                baked.warnings.append(
                    'instance %r points at definition %r, which is not in the '
                    'library -- the model is incomplete, not merely wrong'
                    % (obj.name or obj.id, obj.definition_id))
                return
            definition = library.get(obj.definition_id)
            content = definition.content
            # Per-instance overrides are applied to the CONTENT's children on
            # the way past, without touching the shared content itself. This
            # is the extrinsic half of the flyweight: one definition, and a
            # section this copy alone carries.
            visit(content, here, path, definition.id, path,
                  trail + [obj.name or definition.name], depth + 1)
            if obj.overrides:
                # Everything this instance just emitted sits at the end of
                # the list. A PREFIX test, not equality: an instance nested
                # inside this one has a longer instance_path, and equality
                # would stop at the first of them and leave the rest of this
                # instance's own rods un-overridden.
                n = len(path)
                for i in range(len(baked.members) - 1, -1, -1):
                    if baked.origins[i].instance_path[:n] != path:
                        break
                    baked.members[i].update(obj.overrides)
            return

        if isinstance(obj, GroupNode):
            # The document root's own name is left out, so a joint name is
            # root-relative exactly as a path is. Otherwise every support in
            # a file would be keyed under whatever the model was called, and
            # renaming the model would lose the lot.
            below = trail if depth == 0 else trail + [obj.name]
            for child in obj.children():
                visit(child, here, path, definition_id, instance_path,
                      below, depth + 1)
            return

        baked.warnings.append('nothing knows how to bake %r' % (obj,))

    visit(root, Transform(), (), None, (), [], 0)
    # The root's own id is in every path; strip it so a path is relative to
    # the document and a saved path survives the root being rebuilt.
    strip = 1
    for origin in baked.origins:
        origin.path = origin.path[strip:]
        origin.instance_path = origin.instance_path[strip:]
    baked.node_paths = {n: {p[strip:] for p in paths}
                        for n, paths in baked.node_paths.items()}
    return baked
