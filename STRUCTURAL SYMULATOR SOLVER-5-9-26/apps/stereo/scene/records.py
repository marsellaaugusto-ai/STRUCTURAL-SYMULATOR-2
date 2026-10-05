"""The record form: the graph as plain lists of plain dicts, and back.

One intermediate, two formats. `persist.py` writes these records as JSON or
as an Excel sheet, and neither codec knows anything about SceneObjects. Any
third format later -- a merge payload, a clipboard clip, an undo snapshot --
is another codec over the same records, not another serialiser.

Records are plain dicts and lists, like every other record in this app, and
for the same reason: they print, they diff, they compare, and a test can
hand-write one without constructing a graph.

FOUR DECISIONS worth knowing about before reading the code.

1. FILE IDS ARE NOT OBJECT IDS. A load builds fresh objects with fresh
   session ids and keeps a map from the file's ids while it wires parents up.
   The alternative -- adopting the file's ids -- means loading a file whose
   ids overlap the session counter hands two live objects the same id, and
   every path lookup in the graph is then quietly wrong. The file's ids are a
   wiring detail with a lifetime of one load.

2. CHILD ORDER IS FILE ORDER. The records carry `parent`, not a child list,
   and a parent's children are rebuilt in the order their records appear.
   One ordering rather than two that can disagree, and it makes the table
   readable top to bottom.

3. ABSENT MEANS DEFAULT, NEVER ERROR. A record with no `xform` is at
   identity, no `meta` is empty, no `name` is unnamed. Writers omit what is
   default so a file stays small and its diff shows only what someone
   actually set -- and, the same rule from the other side, a file written
   before a field existed still loads. That is the convention the existing
   Model sheet already follows by reading its columns by NAME.

4. A FILE IS UNTRUSTED INPUT. Not malicious -- hand-edited, half-merged,
   written by an older build, truncated by a full disk. `validate` separates
   the two kinds of wrong: a STRUCTURAL IMPOSSIBILITY (a parent cycle, a
   duplicate id, a parent that is not there) raises, because there is no
   graph to build; a RECOVERABLE GAP (an instance whose definition is
   missing, an unknown kind) is a warning and the rest of the model loads,
   because a user with a damaged file wants the other 99% of their work
   back, not a dialog.
"""
import copy
import json

from apps.stereo.scene.definitions import (
    Definition, DefinitionLibrary, TransformPolicy,
)
from apps.stereo.scene.document import SceneDocument
from apps.stereo.scene.objects import (
    GroupNode, InstanceNode, JointPrimitive, MeshPrimitive, RodPrimitive,
)
from apps.stereo.scene.transform import Transform

#: Bumped only when a reader must behave differently, never for an added
#: field -- an added field is handled by decision 3 above.
FORMAT = 'STEREO-SCENE/1'

KINDS = ('group', 'rod', 'mesh', 'joint', 'instance')

# The identity transform's 12 stored floats, for the "omit what is default"
# rule. The bottom row of an affine matrix is always (0, 0, 0, 1), so it is
# implied rather than stored: 12 numbers a person can read across, not 16
# with four of them always the same.
_IDENTITY_12 = (1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0)


def xform_to_record(transform):
    """The 12 significant floats, or None when it is the identity."""
    twelve = tuple(transform.m[:12])
    return None if twelve == _IDENTITY_12 else [float(v) for v in twelve]


def xform_from_record(values):
    """12 floats back to a Transform. None or absent means identity."""
    if values is None:
        return Transform()
    values = list(values)
    if len(values) == 16:
        # Tolerated, not written: a hand-edited file, or one from a tool that
        # pasted a full 4x4. The bottom row is checked by Transform itself.
        return Transform(values)
    if len(values) != 12:
        raise ValueError('a transform is 12 numbers (or 16), got %d'
                         % len(values))
    return Transform(values + [0.0, 0.0, 0.0, 1.0])


# ── graph -> records ───────────────────────────────────────────────────────

def to_records(doc, canonical=True):
    """The document as records. Renumbers canonically unless told not to.

    Returns `(data, object_map, definition_map)`; the maps are empty when
    `canonical` is False. See SceneDocument.canonical_renumber for why the
    renumber touches the live document and why the maps come back.
    """
    obj_map, def_map = (doc.canonical_renumber() if canonical else ({}, {}))
    objects = []

    def emit(obj, parent_id):
        rec = {'id': obj.id, 'kind': obj.KIND, 'parent': parent_id}
        if obj.name:
            rec['name'] = obj.name
        xform = xform_to_record(obj.local)
        if xform is not None:
            rec['xform'] = xform
        if obj.meta:
            # Deep, not dict(): a shallow copy leaves a nested mutable in
            # `meta` shared with the live object, so a snapshot taken for an
            # undo would carry the very edits it exists to roll back. The
            # cost is proportional to the metadata, not to the model.
            rec['meta'] = copy.deepcopy(obj.meta)

        if isinstance(obj, RodPrimitive):
            rec['a'] = list(obj.a)
            rec['b'] = list(obj.b)
            if obj.joint_a is not None:
                rec['joint_a'] = str(obj.joint_a)
            if obj.joint_b is not None:
                rec['joint_b'] = str(obj.joint_b)
        elif isinstance(obj, MeshPrimitive):
            rec['vertices'] = [list(v) for v in obj.vertices]
            rec['faces'] = [list(f) for f in obj.faces]
        elif isinstance(obj, JointPrimitive):
            rec['at'] = list(obj.at)
            rec['key'] = obj.key
        elif isinstance(obj, InstanceNode):
            rec['definition'] = obj.definition_id
            if obj.overrides:
                rec['overrides'] = copy.deepcopy(obj.overrides)

        objects.append(rec)
        for child in obj.children():
            emit(child, obj.id)

    emit(doc.root, None)
    definitions = []
    for definition in doc._definitions_in_order():
        emit(definition.content, None)
        rec = {'id': definition.id, 'name': definition.name,
               'policy': definition.policy, 'content': definition.content.id}
        if definition.meta:
            rec['meta'] = copy.deepcopy(definition.meta)
        definitions.append(rec)

    data = {'format': FORMAT, 'root': doc.root.id, 'objects': objects,
            'definitions': definitions}
    if doc.meta:
        data['meta'] = copy.deepcopy(doc.meta)
    return data, obj_map, def_map


# ── records -> graph ───────────────────────────────────────────────────────

def validate(data, strict=False):
    """Check records before anything is built. Returns a list of warnings.

    Raises ValueError, with a message meant for a person, on anything that
    makes a graph impossible rather than merely incomplete. `strict` promotes
    the warnings to errors, which is what a test or an importer that would
    rather refuse than guess should pass.
    """
    warnings = []

    def fail(msg):
        raise ValueError(msg)

    if not isinstance(data, dict):
        fail('a scene file is a record, not %s' % type(data).__name__)
    fmt = data.get('format')
    if fmt != FORMAT:
        family = str(fmt or '').split('/')[0]
        if family != FORMAT.split('/')[0]:
            fail('this is not a scene file: its format is %r, expected %r'
                 % (fmt, FORMAT))
        # Same family, different version. Nothing to migrate yet -- version 1
        # is the only one there has been -- so this is the hook, and saying so
        # beats a silent attempt that half works.
        fail('this scene file is version %r and this build reads %r; no '
             'migration exists for it yet' % (fmt, FORMAT))

    objects = data.get('objects')
    if not isinstance(objects, list) or not objects:
        fail('the file has no objects')

    by_id, order = {}, []
    for rec in objects:
        if not isinstance(rec, dict):
            fail('an object record is a dict, not %s' % type(rec).__name__)
        oid = rec.get('id')
        if not isinstance(oid, int) or isinstance(oid, bool):
            fail('object id %r is not a whole number' % (oid,))
        if oid in by_id:
            fail('two objects share the id %d, so nothing can tell which one '
                 'a parent or a definition means' % oid)
        by_id[oid] = rec
        order.append(oid)
        kind = rec.get('kind')
        if kind not in KINDS:
            warnings.append('object %d has unknown kind %r and was skipped '
                            '(a newer build may write it)' % (oid, kind))

    root_id = data.get('root')
    if root_id not in by_id:
        fail('the file names object %r as its root, and there is no such '
             'object' % (root_id,))
    if by_id[root_id].get('kind') != 'group':
        fail('the root must be a group, not %r' % (by_id[root_id].get('kind'),))

    # Parents: present, and acyclic.
    for oid in order:
        parent = by_id[oid].get('parent')
        if parent is None:
            continue
        if parent not in by_id:
            fail('object %d says its parent is %r, and there is no such '
                 'object' % (oid, parent))
        parent_kind = by_id[parent].get('kind')
        if parent_kind in KINDS and parent_kind != 'group':
            fail('object %d is inside object %d, which is a %r and cannot '
                 'hold anything' % (oid, parent, parent_kind))
        # A parent of UNKNOWN kind is not an error here: it was already
        # warned about and its subtree is skipped with it. Failing instead
        # would turn one record a newer build wrote into a refusal to open
        # the file at all, which is the opposite of decision 4.
    # Each object is walked up only until it meets ground already proved
    # acyclic, so the whole check is one pass rather than one per object --
    # a single chain of ten thousand objects would otherwise be fifty
    # million steps on every load.
    grounded = set()
    for oid in order:
        seen, walker = [], oid
        while walker is not None and walker not in grounded:
            if walker in seen:
                loop = seen[seen.index(walker):]
                fail('objects %s form a loop of parents, which is not a tree'
                     % ', '.join(str(x) for x in loop))
            seen.append(walker)
            walker = by_id[walker].get('parent')
        grounded.update(seen)

    # Definitions: content present, a group, and its own root.
    definitions = data.get('definitions') or []
    if not isinstance(definitions, list):
        fail('definitions are a list, not %s' % type(definitions).__name__)
    def_ids, content_ids = set(), {}
    for rec in definitions:
        if not isinstance(rec, dict):
            fail('a definition record is a dict, not %s' % type(rec).__name__)
        did = rec.get('id')
        if not isinstance(did, str) or not did:
            fail('definition id %r is not a name' % (did,))
        if did in def_ids:
            fail('two definitions share the id %r' % did)
        def_ids.add(did)
        content = rec.get('content')
        if content not in by_id:
            fail('definition %r names object %r as its content, and there is '
                 'no such object' % (did, content))
        if by_id[content].get('kind') != 'group':
            fail('definition %r\'s content must be a group, not %r'
                 % (did, by_id[content].get('kind')))
        if by_id[content].get('parent') is not None:
            fail('definition %r\'s content (object %d) also sits inside '
                 'object %d; content is its own root'
                 % (did, content, by_id[content]['parent']))
        if content in content_ids:
            fail('definitions %r and %r both claim object %d as their content'
                 % (content_ids[content], did, content))
        content_ids[content] = did
        policy = rec.get('policy', TransformPolicy.RIGID)
        if policy not in TransformPolicy.ALL:
            warnings.append('definition %r has unknown policy %r; read as %r'
                            % (did, policy, TransformPolicy.RIGID))

    # A definition that places itself, at any remove, is an infinitely deep
    # model: nothing can bake it. The library refuses to build one, so this
    # can only arrive from a hand-edited or half-merged file -- and the bake
    # finds out 64 levels down, having already emitted whatever it met on
    # the way. Cheaper and clearer to refuse the file here, naming the loop.
    children_of = {}
    for oid in order:
        children_of.setdefault(by_id[oid].get('parent'), []).append(oid)

    def places(content_id):
        """The definitions placed anywhere under one definition's content."""
        out, stack = set(), [content_id]
        while stack:
            node = stack.pop()
            rec = by_id[node]
            if rec.get('kind') == 'instance':
                out.add(rec.get('definition'))
            stack.extend(children_of.get(node, ()))
        return out

    uses = {content_ids[c]: places(c) for c in content_ids}
    state = {}

    def chase(did, trail):
        if state.get(did) == 'done':
            return
        if state.get(did) == 'open':
            loop = trail[trail.index(did):] + [did]
            fail('definition %s contains itself, which is a model of '
                 'infinite depth' % ' -> '.join(repr(d) for d in loop))
        state[did] = 'open'
        for nxt in sorted(uses.get(did, ()), key=str):
            if nxt in uses:
                chase(nxt, trail + [did])
        state[did] = 'done'

    for did in sorted(uses, key=str):
        chase(did, [])

    # Every root-parented object is either THE root or some definition's
    # content. An object that is neither is an orphan: it would be silently
    # dropped, and a silently dropped subtree is a lost piece of structure.
    for oid in order:
        if by_id[oid].get('parent') is None and oid != root_id:
            if oid not in content_ids:
                warnings.append(
                    'object %d has no parent and is no definition\'s content, '
                    'so nothing places it; it was skipped' % oid)

    # Instances: their definition exists, and the geometry they carry parses.
    for oid in order:
        rec = by_id[oid]
        kind = rec.get('kind')
        if kind == 'instance':
            if rec.get('definition') not in def_ids:
                warnings.append(
                    'object %d places definition %r, which this file does not '
                    'contain; it was skipped' % (oid, rec.get('definition')))
        elif kind == 'rod':
            for end in ('a', 'b'):
                if not _is_point(rec.get(end)):
                    fail('rod %d has no usable %r endpoint: %r'
                         % (oid, end, rec.get(end)))
        elif kind == 'joint':
            if not _is_point(rec.get('at')):
                fail('joint %d has no usable position: %r' % (oid, rec.get('at')))
            if not str(rec.get('key') or '').strip():
                fail('joint %d has no key, and a joint is its name' % oid)
        elif kind == 'mesh':
            verts = rec.get('vertices') or []
            if not all(_is_point(v) for v in verts):
                fail('mesh %d has an unusable vertex' % oid)
            for face in rec.get('faces') or []:
                if not all(isinstance(i, int) and 0 <= i < len(verts)
                           for i in face):
                    fail('mesh %d has a face pointing at a vertex it does '
                         'not have: %r' % (oid, face))
        if 'xform' in rec:
            try:
                xform_from_record(rec['xform'])
            except (ValueError, TypeError) as exc:
                fail('object %d has an unusable transform: %s' % (oid, exc))

    if strict and warnings:
        fail('the file has %d problem(s) and strict loading was asked for:\n  %s'
             % (len(warnings), '\n  '.join(warnings)))
    return warnings


def _is_point(value):
    return (isinstance(value, (list, tuple)) and len(value) == 3
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    for v in value))


def from_records(data, strict=False):
    """Build a SceneDocument from records.

    Returns `(doc, warnings, id_map)`, where `id_map` is {file id: new object}
    -- the third element because a load makes FRESH objects (decision 1), so
    anything holding ids across the load, such as a selection restored from
    an undo snapshot, has no other way to follow them.

    Validation runs first, so nothing is half-built when a file turns out to
    be impossible -- a half-built document is worse than none, because it
    looks like a model.
    """
    warnings = list(validate(data, strict=strict))
    by_id = {rec['id']: rec for rec in data['objects']}
    skip = _unbuildable(data, by_id)

    built = {}
    for rec in data['objects']:
        if rec['id'] in skip:
            continue
        obj = _build_one(rec)
        if obj is None:
            continue
        built[rec['id']] = obj

    # Parents in FILE ORDER, which is what makes child order survive.
    for rec in data['objects']:
        obj = built.get(rec['id'])
        parent = built.get(rec.get('parent'))
        if obj is not None and parent is not None:
            parent.add(obj)

    root = built[data['root']]
    library = DefinitionLibrary()
    highest = 0
    for rec in data.get('definitions') or []:
        content = built.get(rec['content'])
        if content is None:
            continue
        policy = rec.get('policy', TransformPolicy.RIGID)
        if policy not in TransformPolicy.ALL:
            policy = TransformPolicy.RIGID
        definition = Definition(rec['id'], rec.get('name') or rec['id'],
                                content, policy=policy,
                                meta=copy.deepcopy(rec.get('meta')))
        library._defs[definition.id] = definition
        digits = ''.join(c for c in str(rec['id']) if c.isdigit())
        if digits:
            highest = max(highest, int(digits))
    # The next definition made in this session must not reuse a saved id.
    library._next = highest + 1

    doc = SceneDocument(root=root, library=library,
                        meta=copy.deepcopy(data.get('meta')))
    return doc, warnings, built


def _unbuildable(data, by_id):
    """Ids that validate() warned about, plus everything under them.

    A skipped group takes its subtree with it. Keeping the children and
    re-parenting them to the root would be worse than dropping them: they
    would appear in the model at the wrong place, at the wrong scale, and
    nothing on screen would say so.
    """
    bad = set()
    def_ids = {rec.get('id') for rec in (data.get('definitions') or [])}
    content_ids = {rec.get('content') for rec in (data.get('definitions') or [])}
    for oid, rec in by_id.items():
        if rec.get('kind') not in KINDS:
            bad.add(oid)
        elif rec.get('kind') == 'instance' and rec.get('definition') not in def_ids:
            bad.add(oid)
        elif (rec.get('parent') is None and oid != data.get('root')
              and oid not in content_ids):
            bad.add(oid)
    # Close downwards.
    changed = True
    while changed:
        changed = False
        for oid, rec in by_id.items():
            if oid not in bad and rec.get('parent') in bad:
                bad.add(oid)
                changed = True
    return bad


def _build_one(rec):
    kind, name = rec.get('kind'), rec.get('name', '')
    local = xform_from_record(rec.get('xform'))
    meta = copy.deepcopy(rec.get('meta') or {})
    if kind == 'group':
        return GroupNode(name=name, local=local, meta=meta)
    if kind == 'rod':
        return RodPrimitive(rec['a'], rec['b'], name=name, local=local,
                            meta=meta, joint_a=rec.get('joint_a'),
                            joint_b=rec.get('joint_b'))
    if kind == 'mesh':
        return MeshPrimitive(rec.get('vertices') or [], rec.get('faces') or [],
                             name=name, local=local, meta=meta)
    if kind == 'joint':
        return JointPrimitive(rec['at'], rec['key'], name=name, local=local,
                              meta=meta)
    if kind == 'instance':
        return InstanceNode(rec['definition'], name=name, local=local,
                            meta=meta,
                            overrides=copy.deepcopy(rec.get('overrides')))
    return None


# ── a canonical text form, for diffing and for tests ──────────────────────

def to_text(data):
    """Records as sorted, indented JSON text: the form a diff reads.

    Keys sorted and one field per line on purpose. A file whose diff shows
    the one number that changed is a file a person can review; a
    single-line dump of the same data is not.
    """
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
