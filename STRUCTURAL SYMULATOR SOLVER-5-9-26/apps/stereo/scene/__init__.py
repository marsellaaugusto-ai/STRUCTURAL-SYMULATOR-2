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

This package does not import Tk, numpy, or anything else in the app, and it
knows nothing about steel sections -- a graph that needed a section catalogue
to be tested would not get tested. It is additive: `stereo_groups.py` keeps
working untouched, and `BakedModel.legacy_groups` hands existing reports the
records they already read.
"""
from apps.stereo.scene.bake import (
    BakedModel, MemberOrigin, WELD_TOL_M, bake,
)
from apps.stereo.scene.definitions import (
    Definition, DefinitionLibrary, TransformPolicy, edit_in_place,
    make_all_unique, make_definition, make_unique,
)
from apps.stereo.scene.objects import (
    GroupNode, InstanceNode, JointPrimitive, MeshPrimitive, Primitive,
    RodPrimitive, SceneObject,
)
from apps.stereo.scene.transform import IDENTITY, Transform

__all__ = [
    'BakedModel', 'Definition', 'DefinitionLibrary', 'GroupNode', 'IDENTITY',
    'InstanceNode', 'JointPrimitive', 'MemberOrigin', 'MeshPrimitive',
    'Primitive', 'RodPrimitive', 'SceneObject', 'Transform',
    'TransformPolicy', 'WELD_TOL_M', 'bake', 'edit_in_place',
    'make_all_unique', 'make_definition', 'make_unique',
]
