# Stereo tab — complete feature list

The space-truss (3D space-frame) calculator. Everything below is in the app
today and covered by tests. Branch `claude/stereo-structure-calculator-lqgosu`,
2110 tests passing.

Names in `code font` are the identifiers in the source, so anything here can be
found by grepping.

---

## 1. The solver

`apps/stereo/stereo_math.py` — direct stiffness, 3D, linear elastic,
small-deflection. Solves in SI; the UI converts at the boundary.

**Two element types, mixable in one model.**

- **Pin** (`conn='pin'`) — 3 translational DOF per node, axial force only.
  The classic space truss.
- **Rigid** (`conn='rigid'`) — 6 DOF per node (3 translations + 3 rotations),
  full 12×12 frame element with axial, 2 bending planes, torsion and shear
  terms. This is what a Vierendeel needs; pinned, a Vierendeel is a mechanism.

**Per-member properties.** `E` (GPa), `A` (cm²), `r` (radius of gyration, cm),
`I` (cm⁴), `J` (cm⁴), `K` (effective-length factor), `Fy`, `Fu` (MPa).
Chord and web members carry independent property sets (`_apply_sections`), so a
grid can have heavy chords and light webs without editing members one by one.

**Supports.** Any combination of the 6 DOF per node, set individually or by
preset: `free`, `pin`, `fixed`, `rollerX`, `rollerY`, `rollerZ`, `custom`.
Quick actions apply a preset to every suggested node at once.

**Loads.**
- Nodal point loads: `fx fy fz mx my mz`, any number of nodes at once.
- Self-weight (`self_weight_loads`) from member volume × unit weight.
- Area load over the generator's own exact tributary areas.
- `combine_loads` layers any number of load lists.

**Outputs.** Nodal displacements, reactions (forces and moments),
per-member axial force `N`, and for rigid members the local end actions
`Vy Vz T My_a Mz_a My_b Mz_b`.

**Diagnostics.**
- `degree_of_indeterminacy` — Maxwell count, reported in the UI.
- `check_boundary_setup` — catches a floating node, a missing load path, and
  insufficient restraint *before* the matrix goes singular, so the user gets a
  sentence instead of a LinAlgError.
- `node_moment_vectors` — the internal moment each rigid member end imposes on
  its joint, in global axes, taking the largest incident end rather than the
  sum (a sum reads ~0 at a continuous joint by equilibrium, which is the
  opposite of useful). Verified against statics: a cantilever of length L with
  tip load P reads exactly P·L, matching its own reaction axis for axis, in all
  three orientations.

**Code checks.** `stereo_checks.py` runs CIRSOC 301 per member: tension yield
and rupture, compression buckling with KL/r, reporting `util` (demand ÷
capacity), the governing `mode`, and a slenderness flag at KL/r > 200.

---

## 2. Geometry — 14 parametric families

Pick a family, set its dimensions, press Generate. Each returns nodes, members
with roles, suggested support nodes, and exact per-node tributary areas.

| Family | Notes |
|---|---|
| Flat double-layer grid | square-on-square, offset or aligned |
| Hyperbolic paraboloid (hypar) shell | |
| Hip (pyramidal) roof grid | |
| Groin (cross) vault | |
| Circular flat grid | polar layout, double layer |
| Barrel vault (circular arch) | |
| Parabolic vault | |
| Elliptic vault | |
| Dome (Schwedler ribs) | meridians + hoops + one diagonal per panel |
| Conical roof (straight rafters) | |
| Paraboloid dish (antenna) | |
| Elliptic dome | |
| Full sphere | |
| Truss bridge (Warren/Pratt-style) | |

**Chord patterns.** `square` (grid-aligned chords) or `diagonal`
(diagonal-on-diagonal). Single or double layer, with or without the offset top
layer, per family.

**Member roles** are tagged at generation (`bottom_chord`, `top_chord`,
`outer_rib`, `inner_rib`, `purlin`, `web`, `capital`, `column_shaft`,
`column_chord`, `column_tie`, `column_web`) and drive the chord/web property
split and the colouring.

---

## 3. Custom Surface Wizard

Build a truss on a surface you write yourself.
`stereo_geometry_custom_surface.py` + `stereo_app_wizard.py`.

**Two ways to define a surface.**
- Height field: `z = f(x, y)`.
- Fully parametric: `x(u,v)`, `y(u,v)`, `z(u,v)` — for anything a height field
  cannot express (torus, helicoid, cylinder).

**Expressions** are compiled by `expr_math.py`, an AST whitelist — no `eval`.
Available: `+ - * / ^`, `sqrt abs exp log log10 log2 sin cos tan asin acos atan
sinh cosh tanh floor ceil min max hypot atan2 pow`, and `pi`, `e`.

**Maths keypad** modelled on GeoGebra's, in three tabs (`123`, `f(x)`,
`f(x,y)`). Keys *show* real notation — √, π, x², |x|, ×, ÷, sin⁻¹, log₁₀, ⌊x⌋ —
and *insert* the ASCII the parser reads, plus a backspace key. It types into the
field you last clicked, or into the panel's first field if you have not clicked
one.

**Domain.**
- **Cartesian** — p, q are the surface's own x, y. A rectangular window.
- **Polar** — p is a radius, q an angle. A disk, sector or annulus.
  **Full circle** closes the seam (j = n2 welds back to j = 0).
- **pole at (x, y)** — where a polar domain's centre sits on the parameter
  plane. A polar grid's rings follow the surface's contours and its ribs run
  down the fall *only* if the pole is on the summit.
- **Find the summit(s)** (`surface_summits`) — locates every local maximum in
  the window, puts the pole on the highest, and reports the **count**: one
  summit means polar is the right chart; several means no single pole can serve
  them, and it names the alternatives. A surface that only rises towards its
  edge reports no summit rather than sending the pole to a corner.

**Module pattern.** `square`, `diagonal`, or `isometric` (a true 60°
equilateral lattice on an oblique basis — the only pattern that is fully
triangulated on a single layer without help from a web).

**Layer mode.**
- **2D** — one layer lying on the surface.
- **3D** — the surface plus a second layer offset by `depth` along the local
  normal, with `offset_side` choosing which one is the defined surface.
- **Two surfaces** — top and bottom defined independently over one shared
  domain, so the truss depth is a design variable instead of one number.

**Crossing check** (`surfaces_cross`). Two surfaces must stay on their own
sides of each other everywhere in the domain. Where they meet the web has zero
length; past a crossing every web is inverted and the truss is inside out.
Generate refuses a crossed pair and names the point. The test is local and
coordinate-free (each separation vector against its neighbour), so it handles
parametric pairs and does not false-positive on concentric domes. Sampled 3×
finer than the mesh lattice, so a crossing that dips between two nodes is caught.

---

## 4. Add-ons: columns and beams

`stereo_geometry_addons.py`. Select nodes in the 3D view, set dimensions, press
the button.

**Six column styles.**

| Style | What it is | Feet |
|---|---|---|
| `COLUMN_PLAIN` | one vertical strut per selected node, no capital | one per node |
| `COLUMN_SHAFT` | one shaft + a capital fanning to the selected nodes | 1 |
| `COLUMN_LATTICE` | four chords on a square footprint, X-braced, tied at intervals | 4 |
| `COLUMN_TAPERED` | the same lattice narrowing towards the ground | 4 |
| `COLUMN_LEGS` | four inclined struts from a splayed square footprint | 4 |
| `COLUMN_TRIPOD` | three legs at 120°, cannot rock on an uneven footing | 3 |

Parameters: height, **capital height** (how deep the fan is — it changes the
load path), width across flats, panel count, and 1- or 2-tier capitals. A
2-tier capital splits the footprint into four quadrants, fans to an
intermediate node per quadrant, and ties those into a ring (without the ring the
cluster is 2 DOF short of rigid — found by eigenanalysis).

Every foot returned is pinned automatically, because a latticed or splay-footed
column is rigid as a body and one pin leaves three rotations free.

**Five beam profiles**, attached to two parallel rows of existing nodes:

| Profile | Cross-section |
|---|---|
| `BEAM_TRIANGLE` | one apex chord on the midline |
| `BEAM_BOX` | two chords directly under the base rows |
| `BEAM_TRAPEZOID` | two chords inboard of the base rows |
| `BEAM_GRID_STRIP` | one offset node per bay under each module centre — a 1×n planar grid mirrored about z, giving half-octahedra |
| `BEAM_VIERENDEEL` | two chords, no diagonals; joints stay rigid (`rigid_required`) |

Each with a **constant** or **parabolic** depth law, any offset direction, and
multi-tier stacking for a deeper girder.

---

## 5. Visualisation

`stereo_app_render.py` + `stereo_app_colors.py`. The legend samples the exact
same colour functions the drawing calls, so the two cannot drift apart.

**Four colour systems.**

| Mode | Ramp | Scaled by |
|---|---|---|
| Axial force | red (tension) ↔ blue (compression), grey at ~0 | this model's own peak or 95th percentile |
| Utilization | green → amber → red | absolute, code-defined (red always means at capacity) |
| Node moment | orange (negative) → white (zero) → violet (positive) | the largest nodal moment in the grid |
| Deformation | pale → saturated green | the largest displacement present |

All are gamma-compressed (0.6) so a model spanning orders of magnitude still
shows contrast. Forces below 3% of the scale are drawn a flat neutral grey and
the legend **counts them**, so a field of grey reads as "these rods carry
nothing" instead of "the drawing failed".

**Moment axis selector** — resultant (signed by the tangential projection
about the structure's own centroid, so two symmetric nodes read the same
colour), or Mx / My / Mz individually.

**Force scale** — peak, or a 95th-percentile anchor with a hairline clip mark
on every rod past the end of the ramp, and a legend row counting them.

**Two fill modes over the wireframe.**
- **Shaded cells** — the mesh's own closed panels, depth-sorted (Tk has no
  z-buffer), coloured by the panel's governing member.
- **Voronoi** — a *surface* (restricted) Voronoi tessellation
  (`stereo_voronoi_surface.py`). The domain is the fabric itself, not a hull;
  the metric is geodesic along it. Three views: **Surface**, **Cells** (with
  boundary outlines where ownership changes), and **Section** (a band cut
  through the fabric on a chosen axis at a chosen position and thickness).
  Sites can be rod midpoints or nodes. Lone struts (column shafts, which belong
  to no closed panel) get crossed ribbons so they do not vanish edge-on.

**Fill density** — Light / Medium / Heavy / Solid (stipple patterns; Tk has no
alpha channel).

**Overlays and toggles.** Deformed shape (coloured by displacement or by axial
force, with a scale factor); load arrows; reaction arrows; support glyphs;
node and member ID labels; nodes on/off; rods on/off or rods-only; Cartesian
axes drawn as full lines with a ground plane; **smooth per-rod gradient** (each
rod blends between its two end values); **thickness = stress** (|N|/A, capped
at 7 px); **slenderness halos** on compression members over KL/r 200;
**hide ~0-force rods**; **load-path animation** — travelling arrowheads,
inward for tension and outward for compression, each coloured by its own rod's
axial force.

**Load %, 0–100.** The model is linear, so scaling every applied load scales
every result by exactly the same factor. The slider steps the whole display
through the load without re-solving.

---

## 6. Module Editor

A second panel, right of the canvas (`stereo_app_module_editor.py`,
`stereo_geometry_cells.py`).

- **Cell detection** — finds the mesh's closed triangles and quads.
- **Role classification** — groups congruent cells by signature; role 0 is the
  dominant repeating module, the rest are keystones and one-offs, listed
  separately.
- **Base module** — the grid's *theoretical* module, derived at generation
  (`base_module`) and frozen there. It does not change when you move a node or
  add a beam, because it is a reference drawing, not a measurement. It is
  expressed in its own local frame (so a dome panel reads upright, not tipped
  over at whatever latitude it sat at), and a single-layer surface grid's base
  module comes back **flat** — the curvature belongs to the surface, not the
  plate.
- **3D view** — the module as the real polyhedron it belongs to (ring + apex),
  orbitable and zoomable with its own camera, with CAD-style dimension callouts
  for edge lengths, the module height, and the apex angle, all computed from
  the actual coordinates.
- **2D editor** — the same cell flattened onto its own (u, v) plane. Drag a
  node, set or lock a rod's length, toggle a missing diagonal on.
- **Role-wide propagation** — every edit applies to every cell of that role at
  once, with locked rods protected across all roles.
- **Rescale** a role's cells by a factor.

---

## 7. Editing the model directly

- **Lasso multi-select** on the 3D canvas (drag a box; Shift adds).
- **Add rod** — click two nodes.
- **Delete** selected nodes or a selected member.
- **Click to inspect** a rod: endpoints, role, connectivity, axial force,
  utilisation and the governing check.
- **Undo / redo**, 60 deep, covering every model-changing command.
- **Support sandbox** — click a support to disable it and re-analyze without
  editing the model, to build intuition for redundancy.

---

## 8. Camera and canvas

Left-drag lassoes, right-drag orbits, wheel zooms, middle-drag pans. Azimuth
and elevation are explicit; Reset view reframes the model. The Module Editor's
3D view has a completely separate camera, so orbiting one never moves the other.

---

## 9. Units

Five conventions app-wide: **CIRSOC, Eurocode, NBR, CSA, AISC**. The first four
are SI and differ in which sub-unit is customary (cm² vs mm², GPa vs MPa);
AISC is a different system (kip, foot, inch, ksi). Solvers always compute in
SI; conversion happens only at the boundary — labels, entry boxes, tables,
legends and colourbar tick values.

---

## 10. Reports and I/O

- **Member Report** — a sortable table of every rod: endpoints, role,
  connectivity, N, governing mode, utilisation, status, worst first.
- **Excel export** — nodes, members, loads, supports, reactions, member
  results and checks.
- **Excel import** — reads a model back. Note it clears `load_nodes`: an
  imported model has no known roof surface, so the area load must not keep
  applying the previous mesh's tributary areas.
- **Indeterminacy readout** — the Maxwell count with a rigid-body-motion
  caveat.

---

## 11. Eleven worked examples

Each loads a complete scene and **fills the Custom Surface Wizard with the
settings that produced it**, so "how would I make one of these?" is answered by
opening the wizard. Examples not built by the wizard carry a truthful note
naming the generator instead of a recipe that would produce something else.

1. Planar grid + columns (1-tier) + beam
2. Planar grid + columns (2-tier) + multilayer beam
3. Single-surface truss: paraboloid dish (square)
4. Single-surface truss: half-cylinder (isometric)
5. Two-surface truss: dish over flat plane (square)
6. Two-surface truss: concentric domes (polar, diagonal)
7. Barrel vault (circular arch), pinned at both springing lines
8. Schwedler dome, pinned at the base ring
9. Conical roof, pinned at the base ring
10. Groin (cross) vault, pinned at the full base perimeter
11. Truss bridge (Warren/Pratt-style), pinned at the four bearings

---

## 12. Loads, in detail

**Point loads.** All six components on any number of selected nodes at once.
Plus a **size + direction** helper: type a magnitude `P` and pick a direction
(Down −Z, Up +Z, ±X, ±Y, or a typed vector), and it resolves *into* the
Fx/Fy/Fz boxes — so the resolved vector stays visible and editable before
Add/update puts it on the model. It normalises the direction, so |F| is always
the P you typed, and leaves any moments you had typed alone.

**Area load.** Spread over the generator's exact per-node tributary areas.

- **Law**: `Uniform` (one pressure), `Linear gradient` (a ramp between two
  values along X, Y or Z — a drift, a one-sided wind), or
  `q(x, y, z) expression` (anything else, compiled by `expr_math`).
- **Direction**: six presets or a typed vector.
- **Scope**: the whole surface, or the selected nodes only — so half a roof can
  carry a drift while the other half does not. Nodes outside the scope get
  **no entry at all**, not a zero one, which is what lets a second load case be
  layered on top of them.
- An expression that will not compile reports in the panel instead of silently
  loading nothing.

**Self-weight** from the members' own volume, at a settable unit weight.

---

## What it does *not* do

Stated plainly so nobody assumes otherwise:

- Linear, small-deflection only. No geometric non-linearity, no form-finding,
  no buckling capacity beyond CIRSOC's member check.
- One load case at a time. `combine_loads` exists but there is no combination
  UI.
- No per-member section rotation for rigid frames — `_local_axes` picks a
  default reference, which matters for non-symmetric sections.
- The Excel round-trip loses the wizard recipe, so an imported model cannot be
  reopened in the wizard.
- No dynamic, thermal or staged-construction analysis.
