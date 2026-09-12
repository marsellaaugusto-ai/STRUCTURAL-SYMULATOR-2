# Handoff manifesto — Structural Simulator Solver, 2026-09-10

Written so this work can be picked up cold, on another account, with no memory
of the chat that produced it. It is the state of play, the map of the code, the
conventions the work follows, and the list of what is still open. Read it top to
bottom once; after that the section headings are the index.

---

## 0 · The one-paragraph summary

This is a Python 3.13 + Tkinter desktop structural-analysis app with six tabs
(Truss, Beam, Arch, Cable, Cable Web, Perforated Beam). Over this work a full
bug diagnosis was run on every tab, the confirmed bugs were fixed, and two
requested features were built: loads drawn to a relative scale, and an app-wide
unit-convention selector. As of this document the unit selector is wired through
**all six tabs**, the full test suite is **1145 passing** (one Cable Web
threading test flakes only in an hour-long single-process run and passes clean
on its own), and everything is committed and pushed. The first performance item
on the open list — the cubic cost of the Beam tab's diagram sampling — has since
been fixed (section 7, item 1). What remains is a short list of enhancements
that were offered and deferred, not bugs.

---

## 1 · Where the code is, and the two-tree trap

There are **two copies** of this project on disk and they are **not** the same
tree. This has caused wasted work before; read this before editing anything.

| path | what it is |
|---|---|
| `…\CLAUDE CARPETA DE TRABAJO\solver\` | a copy of the 2026-09-05 download. **Stale.** Do not treat as current. |
| `…\CLAUDE CARPETA DE TRABAJO\STRUCTURAL-SOLVER-repo\STRUCTURAL SYMULATOR SOLVER-5-9-26\` | **the live git repo and the target of all work.** |

The two diverge **on purpose**. If you ever need to reconcile them, sync
individual files and compare by **content**, never by path, and never copy one
tree over the other wholesale.

- **Git repo root:** `…\STRUCTURAL-SOLVER-repo\` (the folder *above* the
  `STRUCTURAL SYMULATOR SOLVER-5-9-26\` app folder).
- **Remote:** `https://github.com/Mathster-a11y/STRUCTURAL-SOLVER-.git`
- **Branch:** `perforated-beam-cirsoc-and-features` (all work lives here; it is
  not merged to a default branch).

---

## 2 · How to run things

Python is not on `PATH` as `python`. Use the full interpreter path:

```
C:\Users\Usuario\AppData\Local\Programs\Python\Python313\python.exe
```

From the **app folder** (`STRUCTURAL SYMULATOR SOLVER-5-9-26\`):

```bash
# launch the app
python.exe main.py

# the whole suite (slow: ~65 min single-process, because sample_diagram is O(n^2))
python.exe -m pytest -q

# one tab's tests, fast
python.exe -m pytest tests/test_units_in_every_tab.py -q

# lint one file for real errors (ignore "unused"/"f-string missing placeholder" noise)
python.exe -m pyflakes apps/beam/beam_app.py
```

Set `PYTHONIOENCODING=utf-8` for any script that prints the unit glyphs
(cm², kN·m, ◄, ⁴) or Windows cp1252 will raise `UnicodeEncodeError`.

**Two hard-won testing rules for this project:**

1. Never conclude a UI or rendering fact from reading code. Build the real Tk
   widget, drive it, and read the real value back (real widgets, real canvas,
   live measurement). Two genuine unit-rollout bugs on this exact task were
   invisible in the source and only showed up when the built widget was driven.
2. Judge any shape/rendering fix by the drawn curve's deviation from the closed
   form **plus an actual screenshot**, never by a solver-side metric alone.

---

## 3 · The workflow this project follows

**Diagnose → plan → build**, in that order, and each shipment goes out as three
things together: a **git push**, a **zip** of the app folder, and a **written
report** in `REPORTS AND GUIDES/`. That is the expected shape of a deliverable
here; do not consider a piece of work shipped until all three exist.

Multi-line Python written from the shell should go through a file (the Write
tool or a heredoc to a `.py`), not an inline `bash -c` string — quoting breaks
otherwise.

---

## 4 · The architecture, tab by tab

Every solver computes in **SI base units** and always will. `main.py` wires the
six tabs into one `ttk.Notebook`, with the unit selector packed **above** the
notebook so it applies to all tabs at once.

| tab | file | solver approach |
|---|---|---|
| Truss | `apps/truss/truss_app.py` | direct-stiffness; pin + rigid (Vierendeel) rods; gusset/panel plate checks |
| Beam | `apps/beam/beam_app.py` | cubic-Hermite beam elements |
| Arch | `apps/arch/arch_app.py` | 6-DOF 2D frame elements from a smooth y=f(x) |
| Cable | `apps/cable/cable_app.py` | funicular chain, Newton–Raphson |
| Cable Web | `apps/cable_web/cable_web_app.py` + `cable_web_math.py` | force-density net solve, scipy least_squares; background worker thread for the at-rest preview |
| Perforated Beam | `apps/perforated_beam/` (many modules) | net-section + Vierendeel + web-post + CIRSOC 301 / AISC 360 code checks, doubler rings |

Shared foundation: **`common.py`** (colours, canvas scale, `ZoomCanvas`,
`ScrollPanel`, `FlowBar`, the numeric helpers, and now `LoadScale`,
`declutter_text`, and `UnitsMixin`). Every tab imports **from** `common.py`;
`common.py` imports from no tab.

`apps/perforated_beam/cirsoc_301.py` is where **code differences that matter**
live — resistance factors, load-combination coefficients, capacity equations.
Those are deliberately not unit conversions and are not in `units.py`.

---

## 5 · The two features that were built

### 5.1 · Relative load scaling

`common.LoadScale` sizes every load glyph relative to the largest of its own
kind on the model, with a compression exponent (`gamma = 0.70`) so a model with
loads three orders of magnitude apart still draws all of them legibly. Point
loads, distributed loads and moments are each scaled **separately** — they are
different physical quantities (kN, kN/m, kN·m) and sharing one scale would make
two equal-intensity UDLs draw at different heights depending on their length.
`common.declutter_text` nudges overlapping canvas labels apart without ever
lifting one off the canvas. Applied to Beam, Truss and Cable; Arch draws no load
arrows on its schematic. Report: `LOAD_SCALING_AND_UNITS_2026-09-10.md`.

### 5.2 · The unit selector (the bulk of the recent work)

A combobox above the notebook picks one of five conventions: **CIRSOC
(Argentina), Eurocode, NBR (Brazil), CSA (Canada), AISC (US customary)**. The
first four are all SI and differ only in which sub-unit is customary (cm² vs
mm², GPa vs MPa) and in notation; only AISC is a different system. So `units.py`
is honestly *one US-customary system plus four SI presentation profiles*.

**`units.py`** is a presentation layer. No solver imports it; nothing in it can
change an answer, only how an answer is written down. Key pieces:

- `QUANTITIES` — 11 of them. Note **three** distinct lengths, which matters:
  - `length` — a span or station (m / ft)
  - `section_length` — a fibre distance, a flange dimension (cm / in)
  - `detail_length` — a plate thickness, weld leg, bolt spacing (**mm on every
    SI code** / in). A drawing never writes a plate thickness in cm even when a
    fibre distance beside it is in cm; this quantity exists because conflating
    the two showed an 8 mm plate as "0.8 cm".
- `SYSTEMS` — the five conventions, built from named `Unit` objects.
- `STORAGE` — the app's original storage convention (kN, m, cm², cm⁴, GPa, and
  allowable stress in kN/cm²).
- `storage_like(...)` — a copy of STORAGE with a few quantities overridden, so a
  tab can declare it stores something different (see 5.3).
- `reexpress(quantity, value, src, dst)` — one number re-written between two
  systems, via SI in the middle.
- `set_current` / `current` / `on_change` / `off_change`, and the boundary pair
  `to_display` / `from_display`. `set_current` isolates a raising listener so a
  half-converted interface (some panels kip, others kN) can never happen.
- **Every US-customary constant is derived from three exact definitions**
  (1 in = 0.0254 m, 1 ft = 0.3048 m, 1 lbf = 4.4482216152605 N). This is
  deliberate: the first draft had Pa→ksi wrong by a factor of 1000, which would
  have printed every AISC stress a thousand times too large while everything
  else looked fine. `tests/test_units.py` pins each constant against a published
  equivalent, not against the module.

**`common.UnitsMixin`** is the shared machinery every tab mixes in, so the four
ideas (which field is which quantity; `show`/`store` at the boundary; a
`unit_label`/`unit_var` registration; a repaint listener) live in one place
rather than six copies that would drift. The Beam tab was wired first, by hand,
and is the reference implementation.

**The property the whole feature rests on:** switching conventions is purely
cosmetic. It converts on the way to a label and back from an entry box; it never
rewrites stored state. A registered entry box keeps the **exact stored figure**
and repaints from it, rather than converting the displayed (rounded) number in
place — otherwise 20 m → 65.6168 ft → 20.00000064 m and a round trip drifts.

Reports: `LOAD_SCALING_AND_UNITS_2026-09-10.md` (Beam), `UNITS_ROLLOUT_2026-09-10.md`
(the other five).

### 5.3 · Storage is NOT uniform across the tabs

This is the subtlety that made the rollout more than mechanical. Each tab
declares what it actually holds via `storage_like`, and every conversion is
taken relative to that. Assuming one convention would have read a Perforated
Beam span of 8000 mm as an eight-kilometre beam.

| tab | length | force | moment | stress | detail |
|---|---|---|---|---|---|
| Beam, Arch, Cable | m | kN | kN·m | kN/cm² | mm |
| Truss | m | kN | kN·m | **MPa** (plate yield) | mm |
| Cable Web | m | **N** | — | — | mm |
| Perforated Beam | **mm** | **N** | **N·mm** | MPa | mm |

Two kinds of value are deliberately left in storage units, with the label saying
so outright: **user-written expressions** (`q(x)`, `y=f(x)` — re-reading a
formula in another convention would change its meaning) and **fabrication detail
returned as finished text** by the unit-pure section modules
(`opening_reinforcement`, `assembly_check`, `welded_section_math` — none imports
the presentation layer).

Two fields cannot be registered once because their quantity depends on the load
**type**: the load magnitude on the Perforated Beam and Cable Web tabs is a
force for a point load and a force-per-length for a UDL. They are converted by
hand, and the label follows the type. (Verified against the solver: a Cable Web
UDL is lumped as `magnitude * (a1 - a0)` in arc length, so its magnitude is
genuinely N/m.)

---

## 6 · Current state

- Branch `perforated-beam-cirsoc-and-features`, working tree **clean**, all
  pushed to `origin`.
- Latest commits (newest first):
  - `27b2862` Units: wire the remaining five tabs to the app-wide selector
  - `3359b04` Perforated Beam: converge with a hand-written report
  - `d62d7dc` Loads drawn relative to each other, and a unit convention chosen
  - `bd0b799` Beam, Cable and Arch: fix the 2026-09-10 diagnosis
  - `a7e78f9` Re-diagnosis 2026-09-10
- Test suite: **1145 passed**. The lone flake is
  `tests/test_cable_web_diagnosis_fixes.py::test_at_rest_preview_does_not_block_the_main_thread`,
  which times out only in the hour-long single-process run and passes in ~60–160 s
  on its own. It asserts a background solver thread settles within 600 s; the
  failure is resource starvation late in a saturated run, **not** a code defect.
- Test files: 39, of which the unit-selector ones are `test_units.py` (137),
  `test_units_in_beam_tab.py` (11), `test_units_in_every_tab.py` (parametrised
  over the five other tabs × four foreign conventions).

The last shipped zip:
`STRUCTURAL-SYMULATOR-SOLVER_2026-09-10_units-all-tabs.zip` (122 files).

---

## 7 · What is still open (enhancements, not bugs)

These were offered as recommendations, the user approved starting on them, and
the units + load-scaling work was done first. Untouched:

1. **`sample_diagram` was O(n²)/cubic — DONE 2026-09-10.** Fixed: the deflection
   curve is now integrated in one forward pass over the already-sampled moment
   values instead of calling `deflection(x)` (which restarts from x=0) per
   station. ~240× faster at 20 loads, ~360× at 40; shear/moment byte-identical,
   deflection unchanged to <2e-4. See `PERF_SAMPLE_DIAGRAM_2026-09-10.md`. The
   point-query `deflection(x)` method was left untouched on purpose so its
   closed-form tests still bind.
2. **Undo/redo** in Beam, Arch, Cable, Perforated Beam (Truss already has it —
   `_push_undo` / `_model_snapshot`, and `test_truss_editing.py` walks the
   mutators asserting each grows the history; copy that shape).
3. **In-place table editing** (currently add/delete rows via dialogs).
4. **Load combinations** surfaced more broadly (Perforated Beam has
   `load_combinations.py`; the others do not expose combinations).

Low-severity leftovers from the 2026-09-10 diagnosis, documented in the
`REMAINING_BUGS_*_2026-09-10.md` files and intentionally not fixed: dead locals
/ unused imports (B-6, C-4, A-3, P-5) and B-8, C-5, C-6.

**Verified-correct, do NOT "fix":** the triangular-load max-deflection
coefficient (0.00652·wL⁴/EI), the beam end-moment sign convention, and the
0.43% springing moment on a *fixed* arch (that is elastic shortening, not a
bug). Also the results `Text` widget in Beam/Arch/Cable that a naïve sweep flags
as "overflowing" — it sits in a horizontally scrollable canvas and is reachable.

---

## 8 · Reports to read, in order

In `REPORTS AND GUIDES/`:

- `MANIFESTO.md` and `PERFORATED_BEAM_MANIFESTO.md` — the project's own design
  rules (referenced as "MANIFESTO §…" in code comments; §2 = real-widget
  testing, §3j = don't solve the same sub-problem in two places).
- `REMAINING_BUGS_INDEX_2026-09-10.md` → the per-tab `REMAINING_BUGS_*` files —
  the second-pass diagnosis and what it left open.
- `FIXES_2026-09-10.md` — what the `bd0b799` fix commit changed.
- `LOAD_SCALING_AND_UNITS_2026-09-10.md` — feature 1 and the Beam wiring.
- `UNITS_ROLLOUT_2026-09-10.md` — feature 2 across the other five tabs (the most
  recent work; read this and section 5 of this file together).

---

## 9 · How to verify the units feature yourself

The permanent regression is `tests/test_units_in_every_tab.py`. To eyeball a
single tab live, build the real app, load an example, analyse, then switch
`units.set_current('aisc')` and read the widget back — the pattern the two
`test_units_in_*` files use. The assertions that matter, per tab:

- switching to any foreign convention never changes `_current_state()` /
  `_gather_state()` / `_snapshot()` (byte-identical);
- switching there and back is exact;
- re-running the analysis under a different convention returns the identical SI
  answer (this is what would catch a conversion applied to the model instead of
  the label);
- a destroyed tab stops listening to the selector (no leaked listeners).

---

## 10 · Account of every chat session on this account

The whole of this app's Claude-assisted work lives in five session transcripts
under `C:\Users\Usuario\.claude\projects\`. One is an empty stub; the four real
ones are recounted below in the order they were started. Together they are
**~6085 assistant turns and ~3212 tool calls across ~101 human messages**, from
2026-09-04 to 2026-09-11. Every session followed the same shipping shape: git
push + zip + written report. Recurring interruptions ("pause", "continue",
"Alcancé mi límite de uso… continúa donde lo dejaste") are usage-limit and
manual pauses, not scope changes, and are omitted below.

The transcripts themselves are the primary record; this is the map to them.

### Session 1 — Cable Web  ·  transcript `8b2b3a06`
**2026-09-04 → 2026-09-10 · 1834 turns · 970 tool calls · 34 human messages.**

*Asked:* Starting from a zip (`structural_simulator_v15_fixed15`), diagnose the
Cable Web tab and fix what impedes it. Then: make the funicular and
antifunicular cable shapes smooth (they plateaued at the peak/valley under
self-weight), add loads to the antifunicular, and add tension/thrust diagrams
like the truss. Then a deeper geometry complaint with two zoom screenshots — an
unloaded segment should be a smooth catenary but wobbled, and a UDL-loaded
segment should be a smooth parabola but came out polygonal/stepped. Make
default cable self-weight 1 kN/m. Add a toggle between the two fix routes
(cheaper one default). Add parallel funicular/antifunicular thrust/shear/tension
diagrams with a flip toggle and a scale slider like the arch. Run a full test
(examples + ≥10 new cases), fix the tied-down-junction convergence bug and the
rest. Finally, add a toggle for smooth (closed-form) versus real per-edge
diagrams.

*Delivered:* The diagnosis and fixes; the root-cause explanation that a
force-density net makes truly smooth shapes hard, so smoothing is a closed-form
overlay behind a toggle (route 2 default, route 1 available); the diagram suite;
the convergence fix; a 65-test solver suite; repeated git pushes and zips. This
is the origin of `cable_web_app.py`, `cable_web_math.py`, and the
`CABLE_WEB_DIAGNOSIS_*` / `DIAGNOSTIC_REPORT` docs.

### Session 2 — Remaining apps: diagnosis, fixes, load scaling, units  ·  transcript `b19a3851`
**2026-09-06 → 2026-09-11 · 1025 turns · 532 tool calls · 18 human messages.**
**(This is the session that produced this manifesto.)**

*Asked:* Diagnose every app except Cable Web, one report per app, so bugs could
be fixed app by app. Then re-diagnose and report only what remained unsolved.
Push the reports, then start fixing. Then: recommendations for changes and
additions, classified into GUI / UI / Math-engine. Then build two of them, with
two notes — loads drawn to a *relative* (not 1:1) scale, and a unit-convention
button *above* the tabs offering ANSI/AISC, CIRSOC, European, Brazilian and
Canadian conventions, converting at the UI boundary. Then wire the remaining
tabs. Then check for remaining bugs and write this handoff.

*Delivered:* The `REMAINING_BUGS_*_2026-09-10` diagnosis set; the `bd0b799` fix
commit; `common.LoadScale` + `declutter_text` relative load scaling; `units.py`
+ `common.UnitsMixin` + the selector, wired through all six tabs; the
`test_units*` suites; and the reports `LOAD_SCALING_AND_UNITS_2026-09-10`,
`UNITS_ROLLOUT_2026-09-10`, and this file.

### Session 3 — Perforated Beam  ·  transcript `b9900809`
**2026-09-06 → 2026-09-10 · 2304 turns · 1233 tool calls · 33 human messages.**
*(The largest session by far.)*

*Asked:* From `DIAGNOSIS_PERFORATED_BEAM_20260905`, fix the bugs and add:
hyperstatic (continuous/fixed-end) perforated beams; a two-profile built-up
custom section; and more drawing tools in the profile designer. Check every
result against supplied codes (AISC 360-10 and 360-16, CIRSOC 301/302/303).
Add a scrollable left panel so every button is reachable. Model a specific
real beam: two folded-steel C profiles, 1 cm thick, 1.8 m tall, 25 cm base,
10 cm and 20 cm lips, welded at the lips, circular openings ⌀1.35 m at 1.8 m
spacing, 50.4 m span. Fix the bending and moment diagrams (upside down) and the
excessive vertical deformation display; switch span-scale lengths from mm to m.
Explain why the deflection was so large and propose a fix. Add Excel
import/export. Extend the profile designer: select and edit the polyline,
mirror horizontally/vertically/about an axis, clarify weld placement, and apply
circular openings to a custom profile. Against a supplied "Viga Alveolar"
reference PDF, close any calculation gaps (the ZP1 work) and tidy the sidebar
(resizable left panel). Fix the 3-D view (out of proportion, no depth cue → add
dashed hidden lines and zoom) and add/explain ring reinforcement. Reconcile a
real discrepancy: the app denied needing doubler rings where the reference PDF
required them, and reinforcement only worked on pre-designed profiles.

*Delivered:* The hyperstatic solver path, the built-up/compound sections, the
profile designer tools, the Excel round-trip, the 3-D fixes, the doubler-ring
sizing, and the CIRSOC/AISC code checks — the whole `apps/perforated_beam/`
module set (`hyperstatic_math`, `assembly_check`, `opening_reinforcement`,
`welded_section_math`, `section_profile_*`, `perforated_beam_excel`, etc.),
`cirsoc_301.py`, and the `DIAGNOSIS_PERFORATED_BEAM` / `PERFORATED_BEAM_MANIFESTO`
docs, with commits `b847919`, `9e3b738`, `3359b04`. **This is where the
"reconcile the app with a hand-written reference report number by number" rule
came from** — the user wants the two made to agree, not an argument for why the
app is right.

### Session 4 — Truss: plate feature and CAD tools  ·  transcript `f073c1fe`
**2026-09-06 → 2026-09-08 · 922 turns · 477 tool calls · 16 human messages.**

*Asked:* From `DIAGNOSIS_TRUSS_20260905`, do the fixes and — after a diagnosis
of feasibility, which the user explicitly asked for before any change — add a
plate feature: join nodes and rods with a plate to reinforce a polygon region
of a truss or Vierendeel frame (both a checked-only gusset, P1, and a
load-carrying shear panel, P2). Make exported Excel from every app clear,
well-labelled, and re-importable. Then a batch of CAD/editing tools: make the
selection box visible, enable Ctrl+Z / Ctrl+X, copy-paste with a reference
point, ghost geometry, node arrays, and construction guides — including fitting
a parabola / hyperbola / elliptic arc through two points with a fixed property
(height or perimeter), and moving/selecting those guides.

*Delivered:* The gusset and shear-panel plates with their checks
(`truss_plates.py`), the CAD/editing layer (undo/redo, clipboard, arrays,
construction guides — `truss_guides.py`), the Excel presentation work, and the
`DIAGNOSIS_TRUSS` / `DIAGNOSIS_PLATE*` / `TRUSS_LOAD_SIGN_FIX_GUIDE` docs.
**This is where the Truss tab's undo/redo lives**, which is the model to copy
when adding undo/redo to the other tabs (open item 7.2).

### The stub — transcript `062d7ad8` (project `C--Users-Usuario`)
Empty (one line, no turns). A session that opened in the wrong working directory
and was never used. No content.
