"""The document: one container for the graph, its definitions and its metadata.

Why this exists. `bake(root, library)` takes the two halves separately,
which is right for a pure function but wrong for everything that has to
treat a model as one thing -- saving it, loading it, undoing an edit to it,
or asking what its id numbering is. A graph with no container has no
well-defined identity, and persistence is the first thing that needs one.

ON ID NUMBERING, which is the one decision in this file that is not obvious.

`objects.py` issues in-memory ids from a session counter: cheap, never
reused, and deliberately NOT what gets saved. A counter cannot promise that
two files built by the same steps come out the same, because it depends on
what else happened in the session -- an object created and deleted still
consumes an id, so a model built, half undone and rebuilt saves differently
from the same model built once. A saved model that differs from an
identically-built one cannot be diffed, and a diff is how a person checks
what their last hour of editing actually changed.

So a save RENUMBERS CANONICALLY: ids 1..N in the deterministic walk order,
which is derived from tree position alone. Two files built by the same steps
then compare equal byte for byte.

The renumber is applied to the LIVE document, not to a copy written out.
Writing a renumbered copy would leave the file and memory disagreeing about
every id, which is the sort of discrepancy that is invisible until something
stores an id across a save. Instead the maps are RETURNED, so a caller
holding ids -- a selection, an undo stack, a hover highlight -- can update
them, in the same spirit as `stereo_groups.remap_members`.
"""
import hashlib
import struct

from apps.stereo.scene import objects as _objects
from apps.stereo.scene.bake import bake
from apps.stereo.scene.definitions import DefinitionLibrary
from apps.stereo.scene.objects import GroupNode, InstanceNode


class SceneDocument:
    """A model: the object tree, the definitions it places, and its metadata."""

    def __init__(self, root=None, library=None, meta=None):
        self.root = root if root is not None else GroupNode('Model')
        self.library = library if library is not None else DefinitionLibrary()
        self.meta = dict(meta or {})

    # ── the obvious conveniences ───────────────────────────────────────────

    def bake(self, **kw):
        return bake(self.root, self.library, **kw)

    def walk(self):
        """Every object in the document tree. Definitions are not in it."""
        return self.root.walk()

    def walk_all(self):
        """Every object anywhere: the document tree, then each definition's
        content. What a save has to cover, and what a count has to avoid --
        a definition's content appears here ONCE however often it is placed."""
        yield from self.root.walk()
        for definition in self._definitions_in_order():
            yield from definition.content.walk()

    def find_by_id(self, oid):
        for obj in self.walk_all():
            if obj.id == oid:
                return obj
        return None

    def _definitions_in_order(self):
        """Definitions in a deterministic order: first use in the document
        walk, then any the document does not place, by id.

        Order by first use rather than by id so that the file reads in the
        order a person meets the parts, and so that inserting a new component
        does not rewrite the whole definitions table in the diff.
        """
        order, seen = [], set()

        def note(def_id):
            if def_id in seen or not self.library.has(def_id):
                return
            seen.add(def_id)
            definition = self.library.get(def_id)
            # Depth first: a definition's own instances come before it, so
            # loading never meets a reference it cannot resolve yet.
            for obj in definition.content.walk():
                if obj.is_instance():
                    note(obj.definition_id)
            order.append(definition)

        for obj in self.root.walk():
            if obj.is_instance():
                note(obj.definition_id)
        for definition in sorted(self.library.all(), key=lambda d: str(d.id)):
            note(definition.id)
        return order

    # ── canonical numbering ────────────────────────────────────────────────

    def canonical_renumber(self):
        """Renumber every object 1..N and every definition def1..defM.

        Returns `(object_map, definition_map)` -- {old: new} for each -- so a
        caller holding ids can follow. Ids come from WALK POSITION only, so
        the same structure always gets the same numbers.
        """
        obj_map, next_id = {}, 1
        for obj in self.walk_all():
            obj_map[obj.id] = next_id
            next_id += 1
        def_map, next_def = {}, 1
        for definition in self._definitions_in_order():
            def_map[definition.id] = 'def%d' % next_def
            next_def += 1

        # Assigned in a second pass. Writing ids during the walk would mean
        # reading old ids and new ones out of the same tree, and the first
        # collision would be silent.
        for obj in self.walk_all():
            obj.id = obj_map[obj.id]
            if isinstance(obj, InstanceNode):
                obj.definition_id = def_map.get(obj.definition_id,
                                                obj.definition_id)
        self.library._defs = {
            def_map[d.id]: d for d in self.library.all() if d.id in def_map
        }
        for definition in self.library.all():
            definition.id = def_map.get(definition.id, definition.id)
        self.library._next = next_def
        _objects.reserve_ids(next_id - 1)
        return obj_map, def_map


# ── identifying a part by what it is, not by what it is called ─────────────

def content_digest(definition, library=None):
    """A stable hash of what a definition actually IS.

    Geometry, topology, structure and nested definition references -- not
    ids, not names, not the metadata a user may have typed. Two trusses with
    the same bars are the same part whatever they were called, which is what
    an importer or a merge needs to know: bringing in a file that contains
    the same component twice should offer to reuse one definition rather
    than silently stocking two parts that are indistinguishable on the
    drawing and distinguishable in a take-off.

    It is an OFFER, not a rule. The digest says two definitions are
    interchangeable; whether to merge them is a decision for whoever is
    importing, because a user may be keeping two names apart on purpose.
    """
    h = hashlib.sha256()

    def feed_float(x):
        # Pack rather than format: a repr round-trips exactly, but packing
        # makes -0.0 and 0.0 hash alike, which they should, since they place
        # geometry identically.
        h.update(struct.pack('<d', 0.0 + float(x)))

    def feed(obj, depth):
        h.update(b'|%d|%s|' % (depth, obj.KIND.encode()))
        for v in obj.local.m[:12]:
            feed_float(v)
        if isinstance(obj, InstanceNode):
            # A nested definition contributes its own digest, so the hash is
            # over the whole part as built, not over a reference that could
            # point at different content in a different file.
            if library is not None and library.has(obj.definition_id):
                h.update(content_digest(library.get(obj.definition_id),
                                        library).encode())
            else:
                h.update(b'?unresolved')
            for key in sorted(obj.overrides):
                h.update(b'%s=%r' % (key.encode(), obj.overrides[key]))
            return
        for point in obj.local_points() if hasattr(obj, 'local_points') else ():
            for v in point:
                feed_float(v)
        for face in getattr(obj, 'faces', ()) or ():
            h.update(b'f%r' % (tuple(face),))
        for key in ('joint_a', 'joint_b', 'key'):
            v = getattr(obj, key, None)
            if v is not None:
                h.update(b'%s:%s' % (key.encode(), str(v).encode()))
        for child in obj.children():
            feed(child, depth + 1)

    h.update(definition.policy.encode())
    feed(definition.content, 0)
    return h.hexdigest()


def duplicate_definitions(library):
    """{digest: [definitions]} for the parts that are the same part.

    What an import dialog asks before it stocks a second copy of a component
    the file already had.
    """
    by_digest = {}
    for definition in library.all():
        by_digest.setdefault(content_digest(definition, library),
                             []).append(definition)
    return {k: v for k, v in by_digest.items() if len(v) > 1}
