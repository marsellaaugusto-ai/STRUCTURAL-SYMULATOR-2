# Stereo tab — handoff

Written for whoever (or whatever) picks this up next. It assumes no memory of
the sessions that built it. Everything here is checkable against the code.

- Branch: `claude/stereo-structure-calculator-lqgosu`
- Head at time of writing: `9103b72`
- Tests: **2110 passing**, 0 skipped. UI exercise: 0 problems.
- Repo root inside the zip: `STRUCTURAL SYMULATOR SOLVER-5-9-26/`

---

## 0. How to run anything at all

There is exactly one usable interpreter in the dev container:

```bash
/usr/bin/python3.12          # the only one with tkinter + numpy + scipy
```

Tk needs a display, so every test and screenshot runs under Xvfb:

```bash
cd "STRUCTURAL SYMULATOR SOLVER-5-9-26"
xvfb-run -a /usr/bin/python3.12 -m pytest tests/ -q          # ~4.5 min, 2110 tests
xvfb-run -a /usr/bin/python3.12 main.py                      # the app itself
```

**Run the FULL suite before every commit, not just the file you touched.** Two
real bugs in this project were only ever visible in a full run: a Tk variable
bound to the wrong interpreter (every wizard field read back its default), and
the keypad focus bug below. Single-file runs hid both.

A second gotcha: some Tk focus behaviour depends on the Xvfb screen size,
because there is no window manager to hand focus to a toplevel. If a UI test
passes alone and fails in CI, try
`xvfb-run -a -s "-screen 0 1600x1000x24"` before assuming flakiness — that is
how the keypad bug surfaced.

---

## 1. Layout of the code

The Stereo tab is a space-truss (3D pin/rigid frame) calculator. It lives in
`apps/stereo/`. Nothing else in the app imports it except `main.py`.

### Solver and pure geometry (no Tk — test these directly)

| File | What it owns |
|---|---|
| `stereo_math.py` | Direct-stiffness 3D solver (`analyze`), pin and rigid elements, self-weight, area loads, `node_moment_vectors`, `degree_of_indeterminacy` |
| `stereo_geometry.py` | Re-export hub only. Everything below is imported through it, plus `GENERATORS` |
| `stereo_geometry_core.py` | `_NodeBank` (coordinate dedup), `_add_member`, `ROUND` |
| `stereo_geometry_grids.py` | `flat_grid`, `hypar_shell`, `hip_roof_grid`, `circular_flat_grid` |
| `stereo_geometry_vaults.py` | `barrel_vault`, `parabolic_vault`, `elliptic_vault`, `groin_vault` |
| `stereo_geometry_domes.py` | `dome`, `cone_roof`, `paraboloid_dish`, `elliptic_dome`, `sphere_shell` |
| `stereo_geometry_bridges.py` | `truss_bridge` |
| `stereo_geometry_custom_surface.py` | The Custom Surface Wizard's engine: typed expressions → surface callables → mesh. **Read this one first if you touch surfaces.** |
| `stereo_geometry_addons.py` | Columns (6 styles) and reinforcement beams (5 profiles × 2 depth laws) |
| `stereo_geometry_cells.py` | Module Editor maths: `find_cells`, `classify_cell_roles`, local frames, role-wide edits, `base_module` |
| `stereo_voronoi_surface.py` | Surface (restricted) Voronoi tessellation for the filled views |
| `stereo_checks.py` | CIRSOC member checks (utilisation, slenderness) |
| `stereo_reports.py` | Excel export/import |
| `expr_math.py` | AST-whitelist expression compiler. Nothing else may `eval`. |

### UI (Tk mixins)

`StereoApp` in `stereo_app.py` composes mixins and is the **only** class with
an `__init__`. Every other file is a mixin with no state of its own:

```
StereoApp(StereoPanelsMixin, StereoModelMixin, StereoViewMixin,
          StereoRenderMixin, StereoModuleEditorMixin, StereoWizardMixin,
          StereoAddonsMixin, StereoReportsMixin, UnitsMixin)
```

| File | What it owns |
|---|---|
| `stereo_app_panels.py` | Builds every left-hand control panel. If a widget exists, it was made here. |
| `stereo_app_model.py` | Commands that change the model: generate, load example, supports, loads, `_all_loads`, `_apply_sections` |
| `stereo_app_view.py` | Camera, selection, lasso, click-to-inspect, `_load_frac` |
| `stereo_app_render.py` | All canvas drawing: wireframe, fills, Voronoi, legend, axes, overlays |
| `stereo_app_colors.py` | The four colour spectra as **pure functions**. The legend samples the same functions the drawing calls. |
| `stereo_app_constants.py` | Every tunable constant and enum |
| `stereo_app_module_editor.py` | The Module Editor panel |
| `stereo_app_wizard.py` + `_keypad.py` | The Custom Surface Wizard dialog |
| `stereo_app_addons.py` | Column / beam panel commands |
| `stereo_app_reports.py` | Member report window, Excel buttons |
| `stereo_examples.py` | 11 ready-made scenes, each carrying its own wizard recipe |

---

## 2. Invariants — break these and something silently breaks

These are the non-obvious rules. Each one exists because violating it caused a
real bug.

1. **Units are a presentation layer.** Solvers compute in SI and store in
   `STORAGE_UNITS` (kN, m, cm², MPa for this tab). Anything the user *reads*
   goes through `self.u(quantity)` / `self.show()` / `self.fmt()` from
   `UnitsMixin`. Four of the five conventions are SI, so a hard-coded "kN"
   looks fine until someone switches to AISC (kip/ft). Colour ramps do **not**
   convert — they only ever see a ratio.
2. **Rigid members need I and J, not just E and A.** `_apply_sections` must not
   overwrite `conn` on a member carrying `rigid_required` — a Vierendeel beam
   pinned is a mechanism and the matrix goes singular.
3. **`add_column` returns a LIST of feet.** A latticed or splay-footed column
   is rigid as a body; pinning one foot leaves three rotations free. Pin every
   foot returned.
4. **`load_nodes` is the generator's exact tributary areas**, keyed by node
   index. It must be cleared when a mesh arrives from anywhere else (Excel
   import does this) or the area load applies areas from a structure that no
   longer exists.
5. **Loads outside an area load's scope get no entry at all**, not a zero one —
   that is what lets `combine_loads` layer a second field on top of them.
6. **The Module Editor's base module is frozen at generation**
   (`_me_capture_base_module`, called only from `_load_mesh`). It is a
   reference drawing, not a measurement of the current mesh. Its node indices
   are its own, so the edit actions refuse it.
7. **Two surfaces must not cross inside the domain** — see §4.
8. **Tk canvas has no z-buffer and no alpha.** Depth-sort filled polygons
   yourself; "opacity" is a stipple pattern (`gray25`/`gray50`/`gray75`/`''`).
9. **`expr_math` is the only expression evaluator.** It is an AST whitelist.
   Do not reach for `eval`.

---

## 3. What was built, in order, and why

Each item names the file to look at. All are done and tested.

**Solver and generators.** 3D direct stiffness with pin and rigid elements;
14 parametric families; exact tributary areas per node.

**Custom Surface Wizard.** Height-field `z = f(x,y)` or fully parametric
`x,y,z of (u,v)`; Cartesian or polar domain; square / diagonal / isometric
patterns; single layer, offset double layer, or two independent surfaces.
GeoGebra-style keypad (`stereo_app_wizard_keypad.py`) whose keys *show* real
notation (√, π, x², |x|, ×) and *insert* the ASCII the parser reads.

**Add-ons.** Columns: `COLUMN_PLAIN` (no capital, one post per selected node),
`SHAFT`, `LATTICE`, `TAPERED`, `LEGS`, `TRIPOD`, with explicit capital height,
width and panel count. Beams: `TRIANGLE`, `BOX`, `TRAPEZOID`, `GRID_STRIP`,
`VIERENDEEL`, each with a constant or parabolic depth law.

**Visualisation.** Four colour systems (axial force, deformation, utilisation,
nodal moment) as pure functions in `stereo_app_colors.py`; smooth per-rod
gradients; thickness by stress; slenderness halos; load-path animation coloured
by axial force; support sandbox; full-line axes.

**Surface Voronoi** (`stereo_voronoi_surface.py`). This replaced a convex-hull
approach that drew patches out in the void a vault arched over. The domain is
the mesh's own panels; the metric is geodesic along the fabric (a panel's
candidate sites are the ones lying *on* it, so nearest-of-those *is* the
geodesic answer — O(panels), no graph search). Lone struts (column shafts,
which belong to no closed panel) get crossed ribbons so they do not vanish
edge-on.

**Module Editor.** Detects the repeating cell, groups congruent cells into
roles, propagates an edit to every cell of a role. `base_module` derives the
grid's theoretical module and the app freezes it at generation.

**Loads.** Point loads on any number of selected nodes, with a magnitude +
direction helper that resolves *into* the Fx/Fy/Fz boxes rather than becoming a
second place a load can live. Area loads with a law (uniform / linear gradient
along an axis / typed `q(x,y,z)`), a direction (6 presets or a typed vector),
and a scope (whole surface or selected nodes only).

**Polar pole.** A polar grid has one singular point. Its rings follow the
surface's contours and its ribs run down the fall **only if the pole is on the
summit**. It used to be hard-wired to the parameter origin.
`surface_summits()` finds the summits and the wizard has a *pole at* field and
a *Find the summit(s)* button. The summit **count** is the useful output: one
means polar is the right chart, several means no single pole can serve them.

---

## 4. The two-surface crossing check (newest, read this)

`stereo_geometry_custom_surface.surfaces_cross()`.

**The failure.** A double-layer grid is a truss only while its layers stay on
their own sides of each other. Where they meet the web has zero length — a
member with no direction. Past a crossing every web is inverted and one layer's
chords pass through the other's. The model is inside out, and nothing
downstream notices.

**Why it is easy to hit.** The domain is usually a rectangle and the surfaces
are usually radial, so the corners reach **41% further** than the edge
midpoints. The shipped example used a dish reaching its flat bottom layer at
r = 6.93 over the square −6…6, whose corners are 8.49 m out: it was 2.00 m
inside out at all four corners. A test fixture had the same fault.

**The test.** Local and coordinate-free, so it works for parametric pairs as
well as height fields: sample the separation vector (top − bottom) over the
domain; the layers have swapped between two neighbouring samples exactly when
those two vectors point in opposite directions. Locality matters — two
concentric domes have webs pointing very differently at the crown and the rim
without ever crossing, and a single reference direction would reject them.

Sampled `CROSS_CHECK_REFINE = 3` times finer than the mesh lattice, so a
crossing that dips *between* two nodes is caught. A crossing narrower than that
net can still slip through, which is why it returns a report rather than
claiming a proof. `custom_surface_between` raises `ValueError` naming the
point; the wizard renders that as a status message.

**Not checked:** the `module='3d'` offset path. Its second layer is parallel by
construction and the two can never swap. An offset *can* fold through itself
when the depth exceeds the surface's radius of curvature — a different failure,
not tested for. See §5.

---

## 5. What is left to do

Ranked by how much it would improve the tool.

### 5.1 Stitch polar patches over a multi-summit surface — *the big one*

A sinusoidal roof over an 18 × 18 m field has eight summits. One polar grid has
one pole, so at most one summit can be served; with the pole at the origin of
that surface it lands on a *saddle* and serves none.

Today the honest answers are (a) use a Cartesian or isometric lattice, which
has no pole, or (b) run the wizard once per summit and join the patches by
hand. (b) is where the work is.

Three designs, in increasing order of difficulty:

1. **Shared boundary ring.** Every patch stops on a ring the neighbouring patch
   also samples, so nodes coincide and `_NodeBank` welds them. Constrains every
   patch to the same module size. Cleanest structurally.
2. **Cartesian gasket.** Patches stop short of the valleys; a Cartesian strip
   fills between them. Easiest to use, ugliest at the joins.
3. **Proximity weld.** Patches overlap and coincident-within-tolerance nodes
   are merged. Easiest to build, and it can produce slivers.

Start by asking the user which. The geometry pieces already exist:
`surface_summits` gives the centres, `custom_surface_grid` builds one patch,
`_NodeBank` already dedups coincident coordinates.

### 5.2 Drag the pole on the canvas

The pole is two numbers and a button. Clicking a point in plan to place it,
with the found summits drawn as snap markers, would be a much better tool. It
needs a plan-view pick and a preview overlay — a real piece of UI, not a
one-liner.

### 5.3 Surface curvature census outside the wizard

`surface_summits` is only reachable from the wizard. "This shell has 3 summits,
2 hollows and 4 saddles" is a useful read on *any* loaded model and says a lot
about where it wants supports. Needs saddle detection added (currently only
maxima and minima) and a home in a panel other than the surface builder.

### 5.4 Offset self-intersection

`module='3d'` with a depth greater than the surface's radius of curvature folds
the offset layer through itself. Detecting it properly means comparing the
principal curvatures against the offset distance. Nothing currently warns.

### 5.5 A conformal / geodesic chart — *research, not a task*

The rigorous answer to 5.1: parameterise the whole surface so modules follow
the principal curvature directions everywhere, with summits and saddles falling
out as the chart's own singular points. Curvature tensor field → cross-field
solve → quad-meshing. This is what commercial mesh generators do. Do not start
it without a decision that it is worth weeks.

### 5.6 Smaller, well-scoped

- **Buckling / second-order analysis.** The solver is linear small-deflection.
  Slenderness is flagged but no buckling capacity is computed beyond CIRSOC's
  member check.
- **Load combinations.** One load case at a time. `combine_loads` exists and is
  the right seam.
- **Excel round-trip of the wizard recipe.** Export keeps nodes and members but
  loses the surface expressions, so an imported model cannot reopen in the
  wizard. `_wizard_recipe` is the thing to serialise.
- **Member orientation for rigid frames.** `_local_axes` picks a default
  reference; there is no per-member rotation control, which matters for
  non-symmetric sections.

---

## 6. Working practices that were in force

Keep them; they are why the suite is trustworthy.

- Never break an existing feature. Run the full suite before every commit.
- A test's name is a sentence about behaviour, and its docstring says **why**
  the behaviour matters — usually by naming the bug it prevents.
- Comments explain *why*, including what was tried and rejected. Several
  docstrings record a rejected approach (a plain sum of joint moments, a convex
  hull domain, a single reference direction for the crossing test). Do not
  delete those; they stop the same mistake being re-made.
- When a check cannot actually deliver what its comment claims, remove it
  rather than leave the claim. There is a worked example: a crossing guard was
  added to the `3d` offset path, found to be a no-op there, and taken back out
  with a comment saying so.
- Verify UI changes with an Xvfb screenshot, not by reasoning about the code.
- `scratchpad/ui_full.py` drives every family × colour mode × fill × Voronoi
  view × toggle. Run it before shipping; it should report
  `0 problem(s); 1 dialog(s) raised` (the one dialog is the correct
  "Run ▶ Analyze first").

---

## 7. Open questions for the user

Unanswered at handoff. Ask before building 5.1 or 5.2.

1. Is the multi-summit sinusoid a real design case, or was it a way of probing
   where the polar idea breaks? If the latter, the summit census plus
   Cartesian/isometric already covers it and 5.1 is not worth the effort.
2. If patches: which of the three joining strategies in 5.1?
3. Is a draggable pole worth the UI work, or are two numbers and a snap button
   enough?
4. Should the curvature census live outside the wizard, and in which panel?
