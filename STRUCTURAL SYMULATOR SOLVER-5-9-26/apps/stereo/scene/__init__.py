"""A scene graph for the Stereo model: nested groups with frames of their own,
shared component definitions, and a bake that compiles both into the flat
(nodes, members) model `stereo_math.analyze` already solves.

Read the modules in this order; each one is written to be read:

    transform.py    4x4 affine transforms. The composition rule that makes
                    nesting work, and the inverse that makes editing inside
                    a nested frame work.
    objects.py      the Composite: SceneObject, the primitive leaves, the
                    unique GroupNode, and the InstanceNode that shares.
    definitions.py  the Flyweight registry, the transform policy that keeps
                    a placement from silently changing the part, and the two
                    conversions (make_definition / make_unique).
    bake.py         graph -> flat model, with the provenance that reads
                    results back up the hierarchy without a second solve.
    document.py     the container persistence needs: root + library + meta,
                    canonical id numbering, and the content digest that
                    recognises one part arriving twice.
    records.py      the graph as plain dicts, with the validation that keeps
                    a damaged file from becoming a damaged model.
    persist.py      two codecs over those records -- JSON (the project
                    format, written atomically) and an Excel sheet beside
                    the Model sheet -- plus undo snapshots.

This package does not import Tk, numpy, or anything else in the app, and it
knows nothing about steel sections -- a graph that needed a section catalogue
to be tested would not get tested. It is additive: `stereo_groups.py` keeps
working untouched, and `BakedModel.legacy_groups` hands existing reports the
records they already read.
"""
from apps.stereo.scene.bake import (
    BakedModel, MemberOrigin, WELD_TOL_M, bake,
)
from apps.stereo.scene.document import (
    SceneDocument, content_digest, duplicate_definitions,
)
from apps.stereo.scene.definitions import (
    Definition, DefinitionLibrary, TransformPolicy, edit_in_place,
    make_all_unique, make_definition, make_unique,
)
from apps.stereo.scene.objects import (
    GroupNode, InstanceNode, JointPrimitive, MeshPrimitive, Primitive,
    RodPrimitive, SceneObject,
)
from apps.stereo.scene.persist import (
    SUFFIX, load_json, read_scene_sheet, restore, save_excel, save_json,
    snapshot, write_scene_sheet,
)
from apps.stereo.scene.records import (
    FORMAT, from_records, to_records, to_text, validate,
)
from apps.stereo.scene.transform import IDENTITY, Transform

__all__ = [
    'BakedModel', 'Definition', 'DefinitionLibrary', 'FORMAT', 'GroupNode',
    'IDENTITY', 'InstanceNode', 'JointPrimitive', 'MemberOrigin',
    'MeshPrimitive', 'Primitive', 'RodPrimitive', 'SUFFIX', 'SceneDocument',
    'SceneObject', 'Transform', 'TransformPolicy', 'WELD_TOL_M', 'bake',
    'content_digest', 'duplicate_definitions', 'edit_in_place',
    'from_records', 'load_json', 'make_all_unique', 'make_definition',
    'make_unique', 'read_scene_sheet', 'restore', 'save_excel', 'save_json',
    'snapshot', 'to_records', 'to_text', 'validate', 'write_scene_sheet',
]
