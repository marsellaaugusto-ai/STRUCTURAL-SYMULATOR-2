"""The object hierarchy: one base class, leaves, groups, and instances.

Clean-room note. The patterns here are the published ones -- COMPOSITE for
the tree, FLYWEIGHT for the shared definition, PROTOTYPE for make-unique,
VISITOR for traversal -- plus the node/content separation that every open
scene-description format uses. No commercial program's code, algorithms or
interface decisions were consulted or reproduced.

WHAT THIS IS FOR. `stereo_groups.py` already nests groups to any depth, and
its two rules are good ones. But a group there is a NAME OVER A SET OF ROD
INDICES: the geometry stays in one flat global list, so a group has no frame
of its own, cannot be placed twice, and every edit that renumbers rods has
to be chased through every group (`remap_members`). This module turns the
same nesting into a scene graph, where a group is a CONTAINER WITH A FRAME.
The two rules survive, and get stronger:

  * "A rod belongs to exactly ONE group" stops being a rule that `assign`
    has to enforce and becomes a fact about trees: a child has one parent.
    There is no code path by which a rod ends up in two groups, because
    there is no way to express it.
  * "A node belongs to every group touching it, DERIVED, never stored"
    becomes the welding step of the bake (see bake.py). Joints are not
    stored anywhere in this graph at all; they are what coincident endpoints
    turn into when the graph is compiled.

THE ONE DECISION EVERYTHING ELSE FOLLOWS FROM: a rod here holds its two
endpoints as COORDINATES IN ITS OWN LOCAL FRAME, not as indices into a
shared node list. That is what allows a subtree to be moved, copied, or
placed twenty times without touching anything outside it -- and it is what
costs us: the graph no longer states that two rods share a joint. That fact
is re-established at bake time by coincidence within a tolerance, with
`joint_key` as the escape hatch for connections that must be exact rather
than tolerant (see RodPrimitive).

WORLD TRANSFORMS AND THE TRAP IN THEM. Inside a definition there is no such
thing as "world": the definition's content appears everywhere its instances
do, so one node of it has as many world positions as there are instances.
`transform_to_root()` is therefore the honest primitive -- it stops at
whatever root it reaches -- and `world_transform()` is the convenience that
REFUSES when that root is a definition, instead of returning one of the
several right answers. World positions inside definitions belong to paths,
not to nodes, and paths are the bake's business.
"""
import itertools

from apps.stereo.scene.transform import Transform

# In-memory ids, never reused in a session, and deliberately NOT the ids that
# get saved. A save renumbers canonically (`canonical_renumber`) so that two
# files built by the same steps compare equal and a diff of a saved model is
# readable; an in-memory counter cannot promise that and should not pretend to.
_IDS = itertools.count(1)


def _new_id():
    return next(_IDS)


class SceneObject:
    """The common base: anything that has a frame and a place in the tree.

    A leaf and a group differ in exactly one respect -- whether `children()`
    is empty -- which is the whole point of the Composite pattern and the
    reason every walker below (bake, bounds, counts, export) is written once
    rather than once per kind.
    """

    __slots__ = ('id', 'name', 'local', 'parent', 'meta', '_to_root')

    #: Subclasses set this; it is what a saved record is keyed by.
    KIND = 'object'

    def __init__(self, name='', local=None, meta=None):
        self.id = _new_id()
        self.name = str(name or '')
        self.local = local if local is not None else Transform()
        self.parent = None
        # Anything the structural model wants to hang on an object without
        # this module having to know about it: a section, a material, a
        # fabrication note, a colour. Kept opaque on purpose -- the graph's
        # job is shape and ownership, and a graph that knows what a steel
        # section is cannot be tested without one.
        self.meta = dict(meta or {})
        self._to_root = None

    # ── the tree ───────────────────────────────────────────────────────────

    def children(self):
        """Empty for a leaf. Overridden by GroupNode."""
        return ()

    def is_group(self):
        return False

    def is_instance(self):
        return False

    def ancestors(self):
        """Parent first, root last."""
        out, seen, node = [], set(), self.parent
        while node is not None and id(node) not in seen:
            seen.add(id(node))
            out.append(node)
            node = node.parent
        return out

    def root(self):
        node = self
        while node.parent is not None:
            node = node.parent
        return node

    def path(self):
        """Ids from the root down to this object, inclusive.

        The identity the bake and every result lookup uses. A node's own id
        is not enough once definitions are in play: two instances of one
        truss share every content id they contain, and only the path
        distinguishes this instance's bottom chord from that one's.
        """
        return tuple(a.id for a in reversed(self.ancestors())) + (self.id,)

    def depth(self):
        return len(self.ancestors())

    # ── frames ─────────────────────────────────────────────────────────────

    def transform_to_root(self):
        """Local frame composed up to whatever root this sits under.

        The recursion of requirement 3, in one line, memoised: a parent's
        answer is the only thing a child needs, so the whole hierarchy costs
        one multiply per level and nothing is recomputed while nothing moves.
        """
        if self._to_root is None:
            if self.parent is None:
                self._to_root = self.local
            else:
                self._to_root = self.parent.transform_to_root() @ self.local
        return self._to_root

    def world_transform(self):
        """Local frame composed up to the DOCUMENT root.

        Refuses inside a definition, where a node has one world position per
        instance and returning any single one of them would be a lie. Ask
        the bake instead: it knows the path.
        """
        top = self.root()
        if getattr(top, 'is_definition_content', False):
            raise ValueError(
                '%s sits inside definition content, where "world" is not one '
                'place: it is one per instance. Bake the document and look '
                'the path up, or use transform_to_root() for the frame '
                'relative to the definition origin.' % (self,))
        return self.transform_to_root()

    def set_local(self, transform):
        """Replace the local frame. Invalidates this subtree's cache."""
        if not isinstance(transform, Transform):
            raise TypeError('expected a Transform, got %r' % (type(transform),))
        self.local = transform
        self.invalidate()
        return self

    def apply_local(self, transform):
        """Pre-multiply: `transform` applied in the PARENT's frame.

        What a nudge, a rotate or a mirror of a whole group is: the group
        keeps its internal frame and is moved as one object within its
        parent -- which is the locked-group behaviour `stereo_groups`
        already specifies, expressed as a matrix instead of as a rule about
        which nodes may move.
        """
        return self.set_local(transform @ self.local)

    def set_world(self, target):
        """Place this object so that its world frame becomes `target`.

        The inverse half of requirement 3, and the reason the matrices had
        to be invertible: a drag happens in world space, but what gets
        stored is a LOCAL frame, so the parent's world matrix has to be
        divided out. Getting this wrong is how a nested object jumps when
        it is dragged -- it picks up its ancestors' transforms twice.
        """
        if self.parent is None:
            return self.set_local(target)
        return self.set_local(self.parent.world_transform().inverse() @ target)

    def invalidate(self):
        """Drop cached frames here and below. Cheap, and never wrong.

        Invalidation walks DOWN because that is the direction the dependency
        runs: a child's frame is built from its parent's, so a parent moving
        invalidates its descendants and nothing above it.
        """
        if self._to_root is None and not self.children():
            return
        self._to_root = None
        for child in self.children():
            child.invalidate()

    # ── copying ────────────────────────────────────────────────────────────

    def clone(self):
        """A deep, independent copy with fresh ids and no parent.

        PROTOTYPE. The copy shares nothing mutable with the original -- that
        is what "unique" means in requirement 2, and what make_unique relies
        on. `meta` is copied one level deep, which is enough for the scalar
        records this app stores; a nested mutable in `meta` would be shared,
        so don't put one there.
        """
        raise NotImplementedError

    def _copy_base_into(self, other):
        other.name = self.name
        other.local = self.local
        other.meta = dict(self.meta)
        return other

    # ── traversal ──────────────────────────────────────────────────────────

    def accept(self, visitor):
        """VISITOR: `visitor.visit_<kind>(self)`, or `visit_object`.

        Traversal lives outside the node classes so that adding an operation
        -- a take-off, a bounding box, an exporter, a validity check -- adds
        a visitor rather than a method to every class in this file.
        """
        method = getattr(visitor, 'visit_' + self.KIND, None)
        if method is None:
            method = getattr(visitor, 'visit_object')
        return method(self)

    def walk(self):
        """This object, then its whole subtree, depth first.

        Does NOT enter definitions: an InstanceNode is a leaf here. Walking
        the authoring tree and walking the baked structure are different
        questions, and conflating them is how a definition used fifty times
        gets counted once (or fifty times, in the wrong place).
        """
        yield self
        for child in self.children():
            yield from child.walk()

    def __repr__(self):
        return '<%s %d %r>' % (type(self).__name__, self.id, self.name)


# ── leaves: the geometry itself ────────────────────────────────────────────

class Primitive(SceneObject):
    """A leaf. Carries geometry in its own local coordinates."""

    __slots__ = ()
    KIND = 'primitive'

    def local_points(self):
        """Every point of this primitive, in its local frame."""
        raise NotImplementedError


class RodPrimitive(Primitive):
    """One rod: two endpoints in local coordinates, plus what it is made of.

    `joint_key` on either end names a connection that must hold EXACTLY,
    whatever the weld tolerance. Two rods given the same key -- within the
    same definition, or the same group when they are not in one -- weld to
    one joint even if their coordinates differ by more than the tolerance,
    and two rods that merely pass close by with different keys stay apart.
    That is the escape hatch for the case tolerance gets wrong in both
    directions: a pitched piece whose generated coordinates land a
    millimetre apart and must still be one joint, and two layers of a grid
    that come within a millimetre and must not be.
    """

    __slots__ = ('a', 'b', 'joint_a', 'joint_b')
    KIND = 'rod'

    def __init__(self, a, b, name='', local=None, meta=None,
                 joint_a=None, joint_b=None):
        super().__init__(name=name, local=local, meta=meta)
        self.a = tuple(float(v) for v in a)
        self.b = tuple(float(v) for v in b)
        self.joint_a = joint_a
        self.joint_b = joint_b

    def local_points(self):
        return (self.a, self.b)

    def local_length(self):
        return _dist(self.a, self.b)

    def clone(self):
        out = RodPrimitive(self.a, self.b, joint_a=self.joint_a,
                           joint_b=self.joint_b)
        return self._copy_base_into(out)


class MeshPrimitive(Primitive):
    """A plate, panel or surface: local vertices and the faces over them.

    Here so that the hierarchy covers the "lines and meshes" of requirement
    1 rather than only rods -- the app already has gusset plates and wind
    panels, and both want a frame of their own. Faces are index tuples into
    `vertices`; normals are DERIVED (and transformed by inverse-transpose,
    see Transform.apply_normal), never stored, for the same reason joints
    are not stored: a stored normal survives an edit that invalidates it.
    """

    __slots__ = ('vertices', 'faces')
    KIND = 'mesh'

    def __init__(self, vertices, faces=(), name='', local=None, meta=None):
        super().__init__(name=name, local=local, meta=meta)
        self.vertices = [tuple(float(v) for v in p) for p in vertices]
        self.faces = [tuple(int(i) for i in f) for f in faces]
        for f in self.faces:
            for i in f:
                if not 0 <= i < len(self.vertices):
                    raise ValueError('face index %d out of range for %d '
                                     'vertices' % (i, len(self.vertices)))

    def local_points(self):
        return tuple(self.vertices)

    def clone(self):
        out = MeshPrimitive(self.vertices, self.faces)
        return self._copy_base_into(out)


class JointPrimitive(Primitive):
    """A named point: where a support sits, or a load is applied.

    This exists to solve a problem the flat model has no answer to. Supports
    and loads are keyed by NODE INDEX today, so regenerating a mesh or
    deleting a rod renumbers the nodes and the restraints have to be chased
    (or are quietly lost). A joint is a named anchor carried by the graph:
    the bake reports which baked node index each name landed on, so supports
    and loads are declared against names that survive every renumber.
    """

    __slots__ = ('at', 'key')
    KIND = 'joint'

    def __init__(self, at, key, name='', local=None, meta=None):
        super().__init__(name=name or str(key), local=local, meta=meta)
        self.at = tuple(float(v) for v in at)
        self.key = str(key)

    def local_points(self):
        return (self.at,)

    def clone(self):
        out = JointPrimitive(self.at, self.key)
        return self._copy_base_into(out)


# ── the composite ──────────────────────────────────────────────────────────

class GroupNode(SceneObject):
    """A UNIQUE group: it owns its children, and nothing else shares them.

    This is one half of requirement 2. Editing a group's contents changes
    this group and no other, because the children are its own objects -- not
    references to anything. Nesting is unlimited and uniform: a group holds
    groups, instances and primitives in any mixture, at any depth, and every
    rule below asks what the CONTEXT is rather than how deep it sits (the
    same choice `stereo_groups` made deliberately, kept).
    """

    __slots__ = ('_children', 'is_definition_content')
    KIND = 'group'

    def __init__(self, name='', local=None, children=(), meta=None):
        super().__init__(name=name, local=local, meta=meta)
        self._children = []
        # True only for the root of a definition's content. It is what makes
        # world_transform() refuse rather than guess (see the module note).
        self.is_definition_content = False
        for child in children:
            self.add(child)

    def children(self):
        return tuple(self._children)

    def is_group(self):
        return True

    # ── editing membership ─────────────────────────────────────────────────

    def add(self, child, index=None):
        """Take ownership of `child`, detaching it from where it was.

        One parent, always, enforced here because here is the only door in.
        """
        if not isinstance(child, SceneObject):
            raise TypeError('only SceneObjects go in a group, got %r'
                            % (type(child),))
        if child is self or child in self.ancestors():
            raise ValueError('that would put %r inside itself' % (self.name or self.id,))
        if child.parent is not None:
            child.parent.remove(child)
        child.parent = self
        if index is None:
            self._children.append(child)
        else:
            self._children.insert(int(index), child)
        child.invalidate()
        return child

    def remove(self, child):
        """Detach `child`, which keeps its own subtree and local frame."""
        try:
            self._children.remove(child)
        except ValueError:
            raise ValueError('%r is not in %r' % (child, self)) from None
        child.parent = None
        child.invalidate()
        return child

    def reparent(self, child, new_parent, keep_world=True):
        """Move `child` to `new_parent`.

        `keep_world` is the default because it is what a user means by
        dragging a truss into a bay: the truss should not JUMP when its
        frame of reference changes. The local frame is recomputed so the
        world frame comes out the same -- which only works because the
        matrices invert.
        """
        if child.parent is not self:
            raise ValueError('%r is not a child of %r' % (child, self))
        if new_parent is child or new_parent in child.walk():
            raise ValueError('that would put %r inside itself' % (child,))
        target = child.world_transform() if keep_world else None
        new_parent.add(child)
        if target is not None:
            child.set_world(target)
        return child

    def clone(self):
        out = GroupNode()
        self._copy_base_into(out)
        for child in self._children:
            out.add(child.clone())
        return out

    # ── reading it ─────────────────────────────────────────────────────────

    def descendants(self):
        """Everything below here, depth first; this group excluded."""
        for obj in self.walk():
            if obj is not self:
                yield obj

    def find(self, predicate):
        """Every object at or below here that `predicate` accepts."""
        return [o for o in self.walk() if predicate(o)]

    def find_by_name(self, name):
        return self.find(lambda o: o.name == name)

    def find_by_id(self, oid):
        for o in self.walk():
            if o.id == oid:
                return o
        return None

    def resolve_path(self, path):
        """The object a path from here names, or None.

        Does not cross into definitions -- an instance is where the
        authoring tree ends. The bake's own index is what resolves a path
        that runs through one.
        """
        node, rest = self, tuple(path)
        if rest and rest[0] == self.id:
            rest = rest[1:]
        for oid in rest:
            nxt = None
            for child in node.children():
                if child.id == oid:
                    nxt = child
                    break
            if nxt is None:
                return None
            node = nxt
        return node


# ── the flyweight boundary ─────────────────────────────────────────────────

class InstanceNode(SceneObject):
    """A placement of a shared Definition: the other half of requirement 2.

    An instance holds a frame, a definition id, and per-instance overrides
    -- and NOT a copy of the geometry. Editing the definition's content
    changes every instance at once, because there is only ever one content
    to edit. That is FLYWEIGHT, with the split drawn where it has to be for
    a structural model:

      INTRINSIC, shared, lives in the definition:  topology, local
        coordinates, section assignments, connection types. The things that
        make it the same fabricated part.
      EXTRINSIC, per instance, lives here:  the placement matrix, the
        instance's name, overrides, and -- after a solve -- its own forces.
        Two instances of one truss are the same part carrying different
        load, and nothing above would be true if the forces were shared.

    An instance is a LEAF in the authoring tree (`children()` is empty) and
    a subtree in the baked model. Everything that walks the authoring tree
    therefore counts a definition's content once no matter how often it is
    placed, and everything that needs the real quantities bakes first.
    """

    __slots__ = ('definition_id', 'overrides')
    KIND = 'instance'

    def __init__(self, definition_id, name='', local=None, meta=None,
                 overrides=None):
        super().__init__(name=name, local=local, meta=meta)
        self.definition_id = definition_id
        self.overrides = dict(overrides or {})

    def is_instance(self):
        return True

    def clone(self):
        """Another placement of the SAME definition -- not a copy of it.

        This is the line between the two halves of requirement 2. Cloning an
        instance gives a second instance sharing one definition; to get an
        independent copy of the geometry, ask for `make_unique` (which is in
        definitions.py, because it needs the library to look the content up).
        """
        out = InstanceNode(self.definition_id, overrides=dict(self.overrides))
        return self._copy_base_into(out)


def _dist(p, q):
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2) ** 0.5
