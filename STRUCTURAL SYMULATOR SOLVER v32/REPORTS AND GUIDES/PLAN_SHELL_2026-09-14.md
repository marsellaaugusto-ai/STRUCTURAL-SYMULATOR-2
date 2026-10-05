# Shell tab — build plan, 2026-09-14

Follows `DIAGNOSIS_SHELL_2026-09-14.md`. **Built 2026-09-15 — see `SHELL_TAB_2026-09-15.md`.**

Target: the live repo, `STRUCTURAL-SOLVER-repo\STRUCTURAL SYMULATOR SOLVER-5-9-26\`,
branch `perforated-beam-cirsoc-and-features`. New package `apps/shell/`, same
split as every other tab: math modules with no Tkinter, one UI controller.

---

## Phase 0 — bring the Stereo tab into the repo (small)

- Copy `apps/stereo/` and `tests/test_stereo_math.py` from `solver/`.
- Rewrite its import of `cirsoc_301` to the repo's flat form.
- Add Stereo's `tension_strength()` to the repo's `cirsoc_301.py` by hand
  (append only; read every line of the diff before committing).
- Register the tab in the repo's `main.py`; wire it to the unit selector.
- Move the surface-formula compiler into one shared place both tabs import.
- Run the repo's full suite.

## Phase 1 — the engine (`shell_fe.py`, `shell_mesh.py`, `shell_expr.py`)

- **Formulas:** named numbers and named functions (`a = 10`,
  `z(x,y) = c*x*y/(a*b)`), definitions that use other definitions, `^` and
  `2x`, evaluation over the whole mesh at once, clear error per line.
- **Mesh:** rectangular plan, nx × ny four-node elements, nodes lifted to
  z(x, y); element thickness from t(x, y) plus any thickening zones.
- **Elements:** MITC4 shell (membrane + bending + transverse shear, 6
  unknowns per node with a small stabilising stiffness for rotation about the
  normal); 3-D beam element for edge beams and columns, with its own
  rectangular concrete section; beams offset-free along the shell edge.
- **Supports:** at corners, along edges, or at columns; each fixed, pinned or
  sliding in chosen directions.
- **Loads, each a function of position:**
  vertical per m² of plan (snow, live), vertical per m² of surface (self
  weight — computed from thickness and 25 kN/m³ automatically — finishes),
  pressure normal to the surface (wind), horizontal x and y. Turned into
  correct nodal loads by integrating over each element.
- **Solve:** sparse; refuse a structure that can move freely, with a message
  saying what support is missing (same honesty rule as Stereo).
- **Results per element:** Nx, Ny, Nxy; principal N1, N2 and angle; Mx, My,
  Mxy; principal moments; Qx, Qy; displacement; reactions; edge-beam axial
  force, bending moments and shear along its length; equilibrium residual.
- **Membrane-theory reference** (`shell_membrane.py`): the closed form for a
  hypar under uniform load, plus a numerical membrane solution for any
  shallow surface under vertical load, for side-by-side comparison.

**Checks that must pass before Phase 2:**

1. Scordelis–Lo roof (the standard shell benchmark): mid-edge deflection
   within 2 % of the published 0.3024 ft at a fine mesh.
2. Pinched hemisphere and the clamped hypar benchmark — convergence with mesh.
3. Flat simply-supported plate under uniform load against the series
   solution (tests the bending part alone).
4. Hypar under uniform load with shear-carrying edges: interior Nxy within a
   few per cent of q·a·b/(2c), Nx ≈ Ny ≈ 0; edge-beam force growing linearly
   to Nxy × length.
5. Every model: reactions equal applied load in all three directions and all
   three moments; a symmetric model gives a symmetric result.
6. Timing: 40 × 40 mesh analysed in under 2 s.

## Phase 2 — the interface (`shell_app.py`)

- **Algebra panel (left):** the list of definitions; numbers get sliders
  (min / max / step editable); an input line to add new ones; tick or red
  message per row; presets menu.
- **Presets:** hypar on a square (saddle), hypar with two raised corners
  (classic Candela umbrella quarter), inverted umbrella (four hypars on one
  central column), four-hypar groined vault, barrel vault, dome — each a set
  of definitions the user can then edit.
- **3-D view (centre):** shaded surface, mesh lines on/off, edge beams and
  columns drawn solid, supports and load arrows, orbit / zoom / pan and view
  buttons (top, front, side, iso). Redraws live as sliders move.
- **Colour maps:** any result (forces, moments, deflection, steel, the
  thickness, the thickness needed, how close to failing), with a legend;
  arrows for principal-force directions; deformed shape with a scale slider
  normalised to model size (the lesson from Stereo).
- **Plan view:** the same colour map seen from above, with contour lines and
  values, and **click an element to read all its numbers**.
- **Sections:** cut the surface along any x or y line and draw N, M, Q, and
  steel along it as a diagram, like the Beam tab.

## Phase 3 — concrete design and thickness (`shell_design.py`)

- Materials: f'c, fy, cover, bar diameter, concrete unit weight, Ec from f'c.
- Per element, top and bottom layer: steel in x and in y (cm²/m) and a
  suggested bar and spacing; concrete diagonal compression; transverse
  shear; minimum steel; maximum spacing; buckling (local, from the curvature
  and the compressive principal force, with the knockdown factor shown and
  editable); deflection limit.
- **Thickness each element needs** to pass everything.
- **Show first:** after analysis the thickness-needed map and the list of
  failing zones are shown; nothing is changed.
- **Auto-thicken toggle:** when switched on, raise the elements that fail, in steps, with a taper
  into the surrounding shell, re-analyse, repeat until all pass or a maximum
  thickness is reached (then say which check could not be satisfied by
  thickness alone — e.g. a support that needs a different detail).
- Thickening zones shown as editable rules (`x < 1.5 and y < 1.5 → 0.12 m`),
  also drawable as a rectangle on the plan view.
- Edge beams: axial force, bending and shear diagrams, required steel.

## Phase 4 — wind, combinations, units, reports

- Wind velocity pressure from CIRSOC 102-2005 inputs; Cp(x, y) typed or from
  presets (flagged approximate); horizontal load fields.
- Load cases D, L / Lr, S, W and the strength combinations of the chosen
  concrete code; results shown per combination and as the envelope
  (worst of all), and the design uses the envelope.
- `units.py`: add area load (kN/m²), moment per metre (kN·m/m), steel area
  per metre (cm²/m); wire the tab to the selector like the other six.
- Report window and Excel export / import (definitions, supports, loads,
  zones, results, steel).

## Phase 5 — verification and shipping

- Sweep through the interface itself (every preset, every load type, every
  support scheme, invalid formulas, zero load, thickening round trip, Excel
  round trip, unit switching), reported as a pass/fail table.
- Screenshots of the built-in examples.
- Report `SHELL_TAB_2026-09-xx.md`, git push, zip.

---

## Decisions (answered 2026-09-14)

1. **Stereo first:** yes — moved into the repo in Phase 0 so both tabs share
   the formula engine and the 3-D view.
2. **Edge beams and columns:** in the model.
3. **Concrete code:** **CIRSOC 201 now** (the user then supplied the 2024 draft, which became the default; 2005 kept as an option). ACI 318-19 and Eurocode 2 are
   to be added later, so the design code is a separate, swappable layer
   (`shell_codes.py`: one class per code holding its factors, material
   model, minimum steel, spacing and combination rules; the design routines
   ask the selected code object and contain no code-specific numbers). The
   user is supplying the CIRSOC 201 PDF; every check will cite its clause.
4. **Thickening:** the app **first only shows** where and how much thicker
   each part needs to be. A **toggle** switches on automatic thickening
   (steps + taper + re-analyse until all pass). Zones stay editable.
5. **Start:** now, whole plan, then commit, push, zip and report.
