"""Definitions, instances, and the two conversions between them.

Clean-room note. A shared definition placed by a transform is the FLYWEIGHT
pattern applied to a scene graph, and make-unique is PROTOTYPE. Both are
published, general patterns; nothing here reproduces another program's code
or interface.

THE TWO HALVES OF REQUIREMENT 2, and the one operation each direction:

    GroupNode   --- make_definition() --->   Definition + InstanceNode
    (unique: edits affect it alone)          (shared: edits affect all)
    GroupNode   <--- make_unique() ------    InstanceNode

Both conversions PRESERVE THE WORLD FRAME. Nothing moves on screen when a
group becomes a component or a component is made unique; if it did, the
operation would be unusable, because the user would then have to put it
back where it was and would not know exactly where that was.

WHAT A DEFINITION MEANS IN A STRUCTURAL MODEL, which is where this stops
being a graphics question. Two instances of one definition are the SAME
FABRICATED PART, made once and bolted in twice. Three consequences follow,
and the library enforces or exposes all three:

  1. PLACEMENT MUST NOT CHANGE THE PART. A rigid placement -- rotate, move,
     mirror -- leaves every member length and section property intact. A
     non-uniform scale does not: it stretches the rods and leaves the
     section properties describing a section that is no longer there, so
     the stresses come out wrong with nothing on screen to show it. Hence
     `TransformPolicy`, defaulting to RIGID. Scaling is not forbidden, it
     is opt-in per definition, which is the difference between a trap and
     a decision.
  2. A MIRRORED INSTANCE IS A DIFFERENT PART whenever the section is not
     symmetric (an angle, a channel). `mirrored_instances` finds them so a
     take-off can say so instead of under-ordering.
  3. DESIGN IS GOVERNED BY THE WORST COPY. One part, many load cases: the
     definition has to be sized for the envelope over all its instances,
     never for the instance that happens to be selected. The envelope is
     computed in bake.py, where the results live, but it is this file's
     `instances_of` that makes the set well defined.
"""
from apps.stereo.scene.objects import (
    GroupNode, InstanceNode, SceneObject,
)
from apps.stereo.scene.transform import Transform


class TransformPolicy:
    """What an instance is allowed to do to its definition. See note 1."""

    RIGID = 'rigid'            # rotate, mirror, move -- the part is unchanged
    UNIFORM = 'uniform'        # also one scale factor on all three axes
    FREE = 'free'              # anything, including shear; caller's problem

    ALL = (RIGID, UNIFORM, FREE)


class Definition:
    """Shared content: the part itself, in its own coordinates.

    The content is a GroupNode whose frame is the definition's ORIGIN -- the
    point an instance's matrix places. Giving a definition its own origin
    (rather than placing it by the position it happened to be created at) is
    what makes two placements comparable, and what makes a definition
    reusable from a library across files.
    """

    __slots__ = ('id', 'name', 'content', 'policy', 'meta')

    def __init__(self, def_id, name, content, policy=TransformPolicy.RIGID,
                 meta=None):
        if not isinstance(content, GroupNode):
            raise TypeError('a definition\'s content is a GroupNode, got %r'
                            % (type(content),))
        if policy not in TransformPolicy.ALL:
            raise ValueError('unknown transform policy %r' % (policy,))
        self.id = def_id
        self.name = str(name or def_id)
        self.content = content
        self.content.is_definition_content = True
        self.content.parent = None
        self.policy = policy
        self.meta = dict(meta or {})

    def allows(self, transform):
        """Does `transform` respect this definition's policy?"""
        if self.policy == TransformPolicy.FREE:
            return True
        if self.policy == TransformPolicy.UNIFORM:
            return transform.is_uniform_scale()
        return transform.is_rigid()

    def __repr__(self):
        return '<Definition %r (%s)>' % (self.name, self.policy)


class DefinitionLibrary:
    """Every definition in a document, and the operations over them."""

    def __init__(self):
        self._defs = {}
        self._next = 1

    # ── the registry ───────────────────────────────────────────────────────

    def define(self, name, content, policy=TransformPolicy.RIGID, def_id=None,
               meta=None):
        """Register content as a definition. The library does NOT copy it.

        Not copying is deliberate: `make_definition` below hands over
        content it has already detached, and a silent copy there would
        leave the caller holding a group that looks live and is not.
        """
        if def_id is None:
            def_id = 'def%d' % self._next
            self._next += 1
        if def_id in self._defs:
            raise ValueError('definition %r already exists' % (def_id,))
        d = Definition(def_id, name, content, policy=policy, meta=meta)
        self._defs[def_id] = d
        return d

    def get(self, def_id):
        d = self._defs.get(def_id)
        if d is None:
            raise KeyError('no definition %r -- an instance points at '
                           'nothing, which a load or a merge can cause; '
                           'check the file rather than the graph' % (def_id,))
        return d

    def has(self, def_id):
        return def_id in self._defs

    def all(self):
        return tuple(self._defs.values())

    def rename(self, def_id, name):
        d = self.get(def_id)
        d.name = str(name).strip() or d.name
        return d

    # ── who points at what ─────────────────────────────────────────────────

    def instances_of(self, root, def_id, nested=True):
        """Every instance of `def_id` in `root`, and by default inside other
        definitions too.

        `nested=True` matters more than it looks: a bay definition may hold
        instances of a truss definition, so the trusses actually built are
        not only the ones placed in the document. A take-off that walks the
        document alone under-counts exactly the parts that repeat most.
        """
        out = [o for o in root.walk()
               if o.is_instance() and o.definition_id == def_id]
        if nested:
            for d in self._defs.values():
                out.extend(o for o in d.content.walk()
                           if o.is_instance() and o.definition_id == def_id)
        return out

    def reference_count(self, root, def_id):
        return len(self.instances_of(root, def_id))

    def unused(self, root):
        return [d for d in self._defs.values()
                if not self.instances_of(root, d.id)]

    def purge_unused(self, root):
        """Forget definitions nothing places. Returns what was dropped.

        Repeated until it settles, because dropping a definition can orphan
        the ones only it referenced -- a one-pass purge leaves a chain of
        dead definitions behind and the file grows every time it is saved.
        """
        dropped = []
        while True:
            dead = self.unused(root)
            if not dead:
                return dropped
            for d in dead:
                del self._defs[d.id]
                dropped.append(d)

    # ── the rule that keeps the graph finite ───────────────────────────────

    def would_cycle(self, def_id, content):
        """Would putting `content` in `def_id` make it contain itself?

        A definition placing an instance of itself -- at any remove -- is an
        infinitely deep model: the bake would recurse until the stack ran
        out, and no tolerance or depth limit makes it mean anything. Refused
        at the point of edit, the same way `stereo_groups.reparent` refuses
        to make a group its own ancestor, and for the same reason: a cycle
        is cheap to prevent and impossible to recover from gracefully.
        """
        seen, stack = set(), [content]
        while stack:
            node = stack.pop()
            for obj in node.walk():
                if not obj.is_instance():
                    continue
                if obj.definition_id == def_id:
                    return True
                if obj.definition_id in seen:
                    continue
                seen.add(obj.definition_id)
                if self.has(obj.definition_id):
                    stack.append(self.get(obj.definition_id).content)
        return False

    def place(self, def_id, local=None, name='', overrides=None):
        """A new instance of `def_id`, checked against its policy."""
        d = self.get(def_id)
        local = local if local is not None else Transform()
        if not d.allows(local):
            raise ValueError(
                'definition %r is %s, and that placement is not: it would '
                'change the part itself, not just where it sits. Change the '
                'definition\'s policy if that is really wanted, or make this '
                'copy unique first.' % (d.name, d.policy))
        return InstanceNode(def_id, name=name or d.name, local=local,
                            overrides=overrides)

    def set_instance_transform(self, instance, local):
        """Move an instance, with the policy checked. Use this, not set_local.

        `set_local` is left unguarded on purpose -- the base class cannot
        know about policies -- so this is the door that checks, and the one
        the UI should call.
        """
        d = self.get(instance.definition_id)
        if not d.allows(local):
            raise ValueError('definition %r is %s; that placement is not'
                             % (d.name, d.policy))
        return instance.set_local(local)

    def mirrored_instances(self, root, def_id=None):
        """Instances placed with a handedness flip. See note 2.

        World handedness, not local: a mirrored instance inside a mirrored
        bay is the right way round again, and the part that gets fabricated
        is the one the world matrix describes.
        """
        out = []
        for obj in root.walk():
            if not obj.is_instance():
                continue
            if def_id is not None and obj.definition_id != def_id:
                continue
            if obj.world_transform().handedness() < 0:
                out.append(obj)
        return out


# ── the two conversions ────────────────────────────────────────────────────

def make_definition(library, group, name=None, policy=TransformPolicy.RIGID,
                    def_id=None):
    """Turn a unique group into a definition, placed by an instance.

    The group's own local frame becomes the INSTANCE's placement, and the
    definition's content starts at identity. That is the whole trick: the
    part is described once in its own coordinates, and where it happens to
    sit is the instance's business. Returns the new InstanceNode, already
    sitting where the group was.
    """
    if not isinstance(group, GroupNode):
        raise TypeError('only a group becomes a definition, got %r' % (type(group),))
    if group.is_definition_content:
        raise ValueError('that group is already a definition\'s content')
    parent, placement = group.parent, group.local
    index = list(parent.children()).index(group) if parent is not None else None
    if parent is not None:
        parent.remove(group)
    content = group
    content.set_local(Transform())
    definition = library.define(name or group.name or 'Component', content,
                                policy=policy, def_id=def_id)
    instance = InstanceNode(definition.id, name=definition.name, local=placement,
                            meta=dict(group.meta))
    if parent is not None:
        parent.add(instance, index=index)
    return instance


def make_unique(library, instance, name=None):
    """Turn one instance back into an independent group. PROTOTYPE.

    A deep copy of the definition's content is dropped in where the instance
    was, keeping its placement, so the model looks identical and the copy is
    now editable without touching the other instances. The definition and
    every other instance of it are untouched -- which is the half of
    requirement 2 that distinguishes a unique group from a component.

    Note what is NOT done: the definition is not purged even if this was its
    last instance. Making the only copy unique and then finding the
    definition gone from the library would lose a part someone may be about
    to place again; `purge_unused` is an explicit housekeeping step.
    """
    if not isinstance(instance, InstanceNode):
        raise TypeError('only an instance is made unique, got %r' % (type(instance),))
    definition = library.get(instance.definition_id)
    parent = instance.parent
    index = list(parent.children()).index(instance) if parent is not None else None
    group = definition.content.clone()
    group.is_definition_content = False
    group.name = name or instance.name or definition.name
    group.set_local(instance.local)
    group.meta.update(instance.meta)
    # Per-instance overrides were the one thing this copy had that the shared
    # content did not. They stop being overrides the moment the copy owns its
    # content, so they are folded in rather than dropped.
    if instance.overrides:
        group.meta.update(instance.overrides)
    if parent is not None:
        parent.remove(instance)
        parent.add(group, index=index)
    return group


def make_all_unique(library, root, def_id):
    """Every instance of `def_id` in `root`, made unique. Returns the groups.

    The "explode" direction: a definition that turns out to need twenty
    different edits was the wrong abstraction, and this un-makes it in one
    step instead of twenty.
    """
    return [make_unique(library, inst)
            for inst in library.instances_of(root, def_id, nested=False)]


def edit_in_place(library, instance):
    """The content to open when a user double-clicks an instance.

    Returns `(content, instance_count)`. The count is the whole point: an
    edit here lands on every copy, and the caller is expected to say so --
    "this changes 24 other copies" -- BEFORE the edit, not after. Opening a
    unique group needs no such warning, which is precisely the difference
    the user is choosing between.
    """
    definition = library.get(instance.definition_id)
    root = instance.root()
    return definition.content, library.reference_count(root, definition.id)
