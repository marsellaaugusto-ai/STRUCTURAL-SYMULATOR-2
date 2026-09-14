"""Geometry generators for the Stereo (3D space-structure) tab.

This module is the PUBLIC FACADE of the Stereo geometry library: it
re-exports every generator and every module-editor helper, and owns the
GENERATORS dispatch table the UI's Grid Family dropdown drives. Import
from here (`from apps.stereo import stereo_geometry as sg`) rather than
from the family modules directly, so call sites stay stable if a shape
ever moves between families.

The implementations live one family per file, so no single file grows past
a few hundred lines and the name tells you where a shape lives:

  stereo_geometry_core.py            shared node bank + member helpers
  stereo_geometry_grids.py           rectangular-plan double-layer grids
                                     (flat, hip roof, hypar, groin vault)
  stereo_geometry_vaults.py          extruded-arch vaults
                                     (barrel, parabolic, elliptic)
  stereo_geometry_domes.py           round-plan shells and radial grid
                                     (dome, cone, dish, ellipsoid,
                                     sphere, circular flat grid)
  stereo_geometry_bridges.py         truss bridge
  stereo_geometry_addons.py          column and reinforcement beam
                                     (augment an existing mesh)
  stereo_geometry_custom_surface.py  user-typed surfaces + the domain/
                                     module sampling wizard
  stereo_geometry_cells.py           module editor cell/role math

"Estructura estereo" covers real-world families of bolted/welded space
structures that are otherwise built as separate, incompatible programs.
The point of the library is to generate all of them through ONE shared
node/member representation, so the Stereo tab offers a single generator
panel that simply changes which function is called, rather than one app
per typology. Each family shares one already-validated bracing scheme, so
a new typology is usually just a different height/radius/arch PROFILE fed
into bracing that is already known to stand up.

Every one of the non-trivial typologies was actually run through
stereo_math.analyze() under self-weight across a range of mesh densities
before being accepted -- the same discipline barrel_vault's springing-line
fix, flat_grid's aligned-web fix and truss_bridge's top-cross-beam fix
were all found under: a mesh can look structurally sane (no zero-length or
duplicate members) while still being a mechanism, so "does it actually
analyze" is checked, not assumed, for every new shape and every new
bracing scheme -- see tests/test_stereo_geometry.py.

Every generator returns a plain dict:

    {'nodes': [(x, y, z), ...],        # metres, world coordinates
     'members': [{'a': i, 'b': j, 'conn': 'pin', 'role': '...'}, ...],
     'support_candidates': [node_idx, ...],   # a sensible default support
                                               # set -- NOT a restriction.
     'load_nodes': {node_idx: tributary_area_m2, ...}}  # the roof/shell
                                               # surface, for an area load.

`support_candidates` is only a suggestion the UI pre-selects with a 'pin'
preset; the whole point of the boundary-condition system in stereo_math.py
is that ANY node, not just these, can be given ANY combination of
restrained translations/rotations. Nothing in this library or in
stereo_math.py ever restricts which nodes may carry a support.

`load_nodes` is the exact (flat_grid, barrel_vault) or closed-form
midpoint-rule (dome -- see its own docstring) lumped tributary plan/shell
area belonging to each node of the load-bearing surface, in m2.
Multiplying by a pressure q (kN/m2) gives that node's share of a uniform
area load directly -- see stereo_math.area_load_to_nodal_loads. For
flat_grid and barrel_vault the areas sum EXACTLY to the modeled surface's
true area (both are locally flat/cylindrical, so the tributary split has
no curvature error); tests/test_stereo_geometry.py checks this.

Node identity is a plain list index, exactly like truss_math.py. Members
default to 'pin' (axial-only, ball-jointed) connectivity, which is the
physically correct default for the great majority of built space
structures (MERO, Nodus, Triodetic and similar systems are deliberately
moment-free at the node so that only axial force has to be resisted
there); 'rigid' (moment-transferring, Vierendeel-style) connectivity is
available on any member by setting conn='rigid', mirroring the Truss tab's
pin/rigid choice.
"""
# _NodeBank/_add_member/_add_chords are re-exported even though they are
# internal to the library: the tests build hand-made meshes with them, and
# doing so through this facade is what keeps those tests independent of
# which family module a helper happens to live in.
from apps.stereo.stereo_geometry_core import ROUND, _NodeBank, _add_chords, _add_member
from apps.stereo.stereo_geometry_grids import (
    flat_grid, hypar_shell, hip_roof_grid, groin_vault,
)
from apps.stereo.stereo_geometry_vaults import (
    barrel_vault, parabolic_vault, elliptic_vault,
)
from apps.stereo.stereo_geometry_domes import (
    dome, cone_roof, paraboloid_dish, elliptic_dome, sphere_shell,
    circular_flat_grid,
)
from apps.stereo.stereo_geometry_bridges import truss_bridge
from apps.stereo.stereo_geometry_addons import (          # noqa: F401
    add_column, reinforcement_beam,
    COLUMN_SHAFT, COLUMN_LATTICE, COLUMN_TAPERED, COLUMN_LEGS, COLUMN_STYLES,
    BEAM_TRIANGLE, BEAM_BOX, BEAM_TRAPEZOID, BEAM_PROFILES,
)
from apps.stereo.stereo_geometry_custom_surface import (
    make_height_field_surface, make_parametric_surface,
    custom_surface_grid, custom_surface_between, _domain_lattice,
)
from apps.stereo.stereo_geometry_cells import (
    find_cells, classify_cell_roles, cell_local_basis, cell_local_coords,
    project_onto_unlocked_directions, move_role_node, rescale_role_cells,
    set_role_member_length, toggle_role_member,
)

__all__ = [
    'ROUND', 'GENERATORS',
    'flat_grid', 'hypar_shell', 'hip_roof_grid', 'groin_vault',
    'barrel_vault', 'parabolic_vault', 'elliptic_vault',
    'dome', 'cone_roof', 'paraboloid_dish', 'elliptic_dome', 'sphere_shell',
    'circular_flat_grid', 'truss_bridge',
    'add_column', 'reinforcement_beam',
    'make_height_field_surface', 'make_parametric_surface',
    'custom_surface_grid', 'custom_surface_between',
    'find_cells', 'classify_cell_roles', 'cell_local_basis',
    'cell_local_coords', 'project_onto_unlocked_directions', 'move_role_node',
    'rescale_role_cells', 'set_role_member_length', 'toggle_role_member',
]


GENERATORS = {
    'flat_grid': flat_grid,
    'hypar_shell': hypar_shell,
    'hip_roof_grid': hip_roof_grid,
    'groin_vault': groin_vault,
    'circular_flat_grid': circular_flat_grid,
    'barrel_vault': barrel_vault,
    'parabolic_vault': parabolic_vault,
    'elliptic_vault': elliptic_vault,
    'dome': dome,
    'cone_roof': cone_roof,
    'paraboloid_dish': paraboloid_dish,
    'elliptic_dome': elliptic_dome,
    'sphere_shell': sphere_shell,
    'truss_bridge': truss_bridge,
    'custom_surface_grid': custom_surface_grid,
    'custom_surface_between': custom_surface_between,
}
