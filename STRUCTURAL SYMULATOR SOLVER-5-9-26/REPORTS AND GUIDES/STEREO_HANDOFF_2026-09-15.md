# Stereo tab — handoff

Written for whoever (or whatever) picks this up next. It assumes no memory of
the sessions that built it. Everything here is checkable against the code.

- Branch: `claude/stereo-ui-rebuild`
- Tests: **2150+ passing**, 0 skipped.
- Repo root inside the zip: `STRUCTURAL SYMULATOR SOLVER-5-9-26/`

> **Updated 2026-09-19 for the UI rebuild.** The window was rebuilt around
> eight modes and the Voronoi feature was deleted. Section 1b below is the
> new layout; `STEREO_FEATURES.md` §8 describes the window itself, with a
> screenshot of every mode in `stereo_ui_modes/`. Anything in this document
> that talks about a toolbar row or a permanently-open Module Editor column
> describes the *old* tab and has been corrected where it appears.

---

## 0. How to run anything at all

There is exactly one usable interpreter in the dev container:

```bash
/usr/bin/python3.12          # the only one with tkinter + numpy + scipy
```

Tk needs a display, so every test and screenshot runs under Xvfb:

```bash
cd "STRUCTURAL SYMULATOR SOLVER-5-9-26"
xvfb-run -a /usr/bin/python3.12 -m pytest tests/ -q          # ~5 min, 2150+ tests
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
| `stereo_app_render.py` | All canvas drawing: wireframe, fills, legend, axes, overlays, the canvas cards |
| `stereo_app_colors.py` | The four colour spectra as **pure functions**. The legend samples the same functions the drawing calls. |
| `stereo_app_constants.py` | Every tunable constant and enum |
| `stereo_app_module_editor.py` | The Module Editor mode, and the base-module card pinned to the canvas |
| `stereo_app_wizard.py` + `_keypad.py` | The Custom Surface Wizard dialog |
| `stereo_app_addons.py` | Column / beam panel commands |
| `stereo_app_reports.py` | Member report window, Excel buttons |
| `stereo_examples.py` | 11 ready-made scenes, each carrying its own wizard recipe |

---

## 1b. The window (rebuilt 2026-09-19)

`stereo_app_shell.py` owns the chrome and is the file to read first for
anything about layout: `MODES`, `VIEW_PRESETS`, `RAIL_W`, `PANEL_W`,
`TOOLBAR_H`, `STATUS_H`.

```
┌──────────────────────────────────────────────────────────────┐
│ toolbar 46 px: Generate  ▶Analyze  ↶↷  Display▾ Export▾  Load%│
├──────┬────────────┬──────────────────────────────────────────┤
│ rail │  context   │  canvas  (~79% of the width)             │
│ 76px │  panel     │   ┌legend┐                    ┌VIEW┐     │
│      │  300 px    │                                          │
│ 8    │  ONE mode  │        the model                         │
│ modes│  at a time │                                          │
│      │            │   ┌SELECTION┐          ┌BASE MODULE┐     │
├──────┴────────────┴──────────────────────────────────────────┤
│ status 30 px: nodes · rods · utilisation · deflection · ΣRz   │
└──────────────────────────────────────────────────────────────┘
```

`_build_ui` order matters: `_init_display_vars()` → `_build_toolbar()` →
`_build_status_bar()` (packed before the body so it keeps its 30 px) → `main`
→ rail → context panel → canvas → view cube → selection card →
`_populate_modes()` → `_apply_focus_ring()` → `_set_mode(DEFAULT_MODE)`.

Display state lives in `_init_display_vars()`, created eagerly, because the
Display popover is built on demand and destroyed on close — its widgets cannot
own state `_draw` reads on the first frame.

The eight modes are Build / Shape / Support / Load / Section / Add-ons /
Module / Results, reachable with **Alt+1 … Alt+8**.

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
   Do not reach for `eval`. It now also has comparisons and `and`/`or`/`not`,
   because a plan-shape rule is a region, not a height. Adding an operator
   means adding it to BOTH `_validate` and `_evaluate` — the whitelist is what
   keeps `eval` out of a field anyone can type into.

The following were all added or found during the 2026-09-19 UI rebuild:

10. **A column must take over the supports at the joints it carries.** A pin
    left at the column head is a rigid path to ground in parallel with the
    column, and it wins: measured, 0.00 kN through the column with the pin,
    23.17 kN without it.
11. **`_draw` clears the canvas wholesale** (`c.delete('all')`), so a
    remembered canvas item id goes stale every frame. The four corner cards
    (legend, view cube, selection, base module) are all found by TAG each
    frame. Storing the window id and reusing it silently does nothing.
12. **The centring pan is `w / (2 * zoom)`, not `w / 2`.** `ZoomCanvas.w2s`
    multiplies by zoom AFTER adding the pan. The two agree only at zoom 1,
    which is why the zoom-to-fit had to compute the pan after the fit.
13. **`tag_raise(item, card)` in a loop reverses the order**, because each
    call re-inserts directly above the card. To put a card under a group of
    items, use one `tag_lower(card, first_item)`.
14. **`find_all()` returns STACKING order; item ids are CREATION order.** A
    test that compares ids is not testing what is drawn over what.
15. **`ttk.Entry` subclasses `tk.Entry`** but is themed and has no
    `highlightthickness` at all. Any `isinstance(w, tk.Entry)` walk reaches
    the entry inside every readonly combobox and raises `TclError`.
16. **A `LabelFrame` is at least as wide as its own caption**, whatever its
    children need. A caption that is a whole sentence sets the panel's floor
    and silently clips everything else. Captions are headings; the sentence
    goes inside, where it can wrap.
17. **Inactive mode panels are genuinely not mapped.** The rail packs one
    mode's frame and `pack_forget`s the rest, so `winfo_ismapped` is telling
    the truth — a test asking whether a box is showing has to say which mode
    it is in first (`_mode(app, key)`).

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

**Surface Voronoi** — *deleted 2026-09-19*, with its module, its 286 tests and
its view radios, at the user's instruction ("forget about the voronoi feature,
it was a waste of time"). Nothing else depended on it. Do not restore it from
an older zip: the tab has been rebuilt around it not existing.

**Module Editor.** Detects the repeating cell, groups congruent cells into
roles, propagates an edit to every cell of a role. `base_module` derives the
grid's theoretical module and the app freezes it at generation. Since the
rebuild it is mode 7, plus a small always-visible card in the canvas corner
showing the base module.

**Shape mode + lattices + plan mask** (2026-09-19). Four lattice families
(`custom_surface_lattice`), a crossing guard, a summit finder, and
`apply_domain_mask` for cutting a rectangle into a real plan. See
`STEREO_FEATURES.md` §3b — the design decisions there are load-bearing and are
not repeated here.

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
- `scratchpad/ui_full.py` drives every family × colour mode × fill × toggle.
  Run it before shipping; it should report `0 problem(s); 1 dialog(s) raised`
  (the one dialog is the correct "Run ▶ Analyze first").
- **Probe, do not infer.** The two worst findings of the rebuild were both
  things the code looked right about: the column that carried 0.00 kN, and the
  panel fields that were clipped by exactly the chrome nobody had measured.
  Both were found by running the thing and reading a number, and both are now
  tests. When a test fails, first ask whether the ASSERTION is wrong rather
  than the code — three failures in the rebuild were tests asserting an
  implementation constant (`pan_x == w/2`) while their own docstrings claimed
  to check the behaviour.

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

**Answered 2026-09-19, so do not re-ask:**

- *Keep the Voronoi fill?* No. Deleted, with its tests. Not coming back.
- *Keep the load-path arrows?* **Yes** — explicitly. They live in the Display
  popover, 81 tests cover them, and they are not a candidate for removal.
- *Rebuild from scratch or keep the engine?* Keep the engine, rebuild the UI
  in Tkinter. That is what `claude/stereo-ui-rebuild` is.

### Still open after the rebuild

- **Is eight modes the right number?** The rail currently splits the work into
  Build / Shape / Support / Load / Section / Add-ons / Module / Results. Build
  and Shape are both "make a mesh" and could merge; Section is three fields and
  could fold into Add-ons. Nobody has used it enough in anger to say.
- **The 300 px context panel.** Everything now fits it (there is a test), but
  fitting is not the same as comfortable — several rows are tight. Widening to
  ~340 px would cost the canvas about 3% and is a one-constant change
  (`PANEL_W`), but every panel would want re-checking against the fit test.
- **Two-surface support default.** A two-surface build pins the perimeter of
  BOTH layers, which is the convention every generator in this app uses and is
  why a fresh model often reads a governing utilisation around 0.02. Supporting
  only the bottom layer's perimeter would be more realistic. It is a one-line
  change in each generator and a large change in every example's numbers, so it
  wants a deliberate decision, not a drive-by.
