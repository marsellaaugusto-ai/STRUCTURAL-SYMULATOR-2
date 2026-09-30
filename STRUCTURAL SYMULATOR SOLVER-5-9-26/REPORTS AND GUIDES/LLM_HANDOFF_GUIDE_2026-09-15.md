# Handoff guide for the next developer (human or LLM) — 2026-09-15

Read this first. It says what the application is, how it is built, the rules the
owner expects you to follow, what was done in the last session (the Shell tab),
and exactly what is left. Detailed build notes: `SHELL_TAB_2026-09-15.md`,
`PLAN_SHELL_2026-09-14.md`, `DIAGNOSIS_SHELL_2026-09-14.md`,
`HANDOFF_MANIFESTO_2026-09-10.md` (general project rules, section 11 = latest).

> **Note on this copy (STRUCTURAL_SYMULATOR_final_20260915 + Shell).** This
> folder is the "final_20260915" version of the app (its own, newer Stereo tab
> split into many `stereo_app_*` files, and newer `common.py`), with the Shell
> tab added on 2026-09-15. What was added: `apps/shell/`, `formula.py`,
> `view3d.py`, the four new unit quantities in `units.py` (area load, moment
> per metre, steel per metre, unit weight — nothing else in that file
> changed), the Shell tab registered in `main.py`, and the tests
> `test_formula.py`, `test_shell_engine.py`, `test_shell_app.py` plus the Shell
> cases in `test_units.py` / `test_units_in_every_tab.py`. The Stereo tab here
> is NOT the one described below and does not use `formula.py`; it still has
> its own `expr_math.py`. The git repo / branch named in this guide holds the
> *other* version; treat this folder as the one to continue from.

---

## 1. What the application is

A desktop structural-analysis app, **Python 3.13 + Tkinter + numpy/scipy**
(openpyxl for Excel). Launch: `python main.py` from the app folder. One window,
8 tabs: Beam, Truss, Arch, Cable, Cable Web, Perforated Beam, Stereo Structure,
Shell (RC). A unit selector (CIRSOC / AISC / CSA / Eurocode / NBR) changes how
numbers are *shown*, never what is stored.

- Repo: `https://github.com/Mathster-a11y/STRUCTURAL-SOLVER-.git`
- Branch: `perforated-beam-cirsoc-and-features` (last commits 53c9ca7, 6dd86f4)
- App folder inside the repo: `STRUCTURAL SYMULATOR SOLVER-5-9-26/`
- Tests: `python -m pytest tests -q` from the app folder → **1302 passed**
  (~6 min). Occasional Tk "init.tcl couldn't read file" skips are a Windows
  environment glitch, not a bug.

## 2. Layout and architecture rule

```
main.py            builds the window and the 8 tabs
units.py           unit conventions, UnitsMixin (entry boxes that convert)
formula.py         shared GeoGebra-like formula language (Shell + Stereo)
view3d.py          shared 3-D camera (orbit/zoom/views) and colour scales
common.py          shared widgets (ZoomCanvas, ScrollPanel, ...)
cirsoc_301.py      steel code (CIRSOC 301) used by several tabs
apps/<tab>/        one package per tab
tests/             pytest, one or more files per tab
REPORTS AND GUIDES/ diagnosis, plans, build reports, this guide
```

**Rule:** every tab splits into math modules that never import Tkinter, and one
`*_app.py` controller. Math is tested directly; the UI is tested by building the
real Tk widget and calling the controller's own methods (see
`tests/test_shell_app.py`). Keep this split.

## 3. Owner's working rules (follow them)

1. **Diagnose → plan → build → ship.** Write a diagnosis `.md`, then a plan
   `.md`, ask the owner the open decisions, build, then **git push + a zip + a
   written report** in `REPORTS AND GUIDES/`.
2. **Explain in plain language.** Say what actually happens and why, list
   choices as concrete actions one per line. No compressed jargon.
3. **Test through the UI code path**, not only the math layer.
4. **Geometry/rendering fixes** are judged against a closed-form answer *and* a
   picture (a real screenshot; if the screen is locked, the canvas-to-PNG
   replay script used last session).
5. **Reference reports:** if the app disagrees with a hand calculation, reconcile
   the two number by number; don't just argue the app is right.
6. **Two trees:** a working copy `solver/` exists outside the repo and diverges on
   purpose. Sync single files, compare by content, read every removed ("-") line
   of a diff before committing. Never copy the whole tree over.
7. Units: storage is SI per tab (`STORAGE_UNITS`); a displayed value that the
   user did not retype must never be written back (prevents round-trip drift).

## 4. The Shell (RC) tab — what was built

Goal from the owner: design reinforced-concrete shells (hyperbolic paraboloids
first) under uniform and non-uniform vertical and horizontal (wind) loads, with a
GeoGebra-like formula input, a chosen thickness, and a map of where the shell
must be thicker — **shown first, thickened automatically only when a toggle is
switched on**. Code: **CIRSOC 201** now (2024 draft is default, 2005 selectable);
**ACI 318-19 and Eurocode 2 later**.

### Files (`apps/shell/`)

| File | Content |
|---|---|
| `shell_fe.py` | Finite elements. MITC4 4-node shell (6 unknowns/node, transverse shear by tying points, drilling stiffness `DRILL_RATIO=1e-3`, nodal directors that respect folds >15°). 3-D Timoshenko beam `Frame` with rigid end offsets. `assemble`, `solve` (scipy `splu`; detects a structure that can move freely by solving a random load and checking the residual, then finds the moving node/direction → `MechanismError`). `resultants()` gives N, M, Q per element at its centre. |
| `shell_model.py` | The model as a plain dict (`_base()`), `PRESETS` (saddle hypar, one raised corner, inverted umbrella on one column, barrel vault, elliptic dome; all t=10 cm), `ShellModel` (mesh, thickness per element = base t(x,y) + zones + automatic layer, loads, supports, beams, columns), `Results` (combinations, equilibrium check, forces per combination, beam forces, shear into column heads, hypar fit). |
| `shell_codes.py` | The swappable design-code layer. `DesignCode` base class; `CIRSOC201_2024` (default), `CIRSOC201_2005`; `CODES`, `get_code`. Holds φ factors, combinations, concrete shear Vc with size effect, punching (Tabla 22.6.5.2), cover, spacing limits, clause citations, and a list of rules it could **not** verify. |
| `shell_wind.py` | CIRSOC 102-2005 wind: qz = 0.613·Kz·Kzt·Kd·V²·I, exposure A–D, city speeds (Fig. 1B), approximate Cp patterns for hypars/vaults (flagged approximate). |
| `shell_design.py` | Per element: steel per face and direction (sandwich model + Nielsen), concrete strut crushing, shear, local buckling (classical formula × editable knock-down), minimum thickness from cover, punching at column heads; thickness each element needs; `auto_thicken()` (steps + taper + re-analyse until all pass); edge-beam preliminary design; service deflection. |
| `shell_reports.py` | Text report (sections 1–9 incl. membrane-theory comparison and code clauses), Excel export/import (sheet 'Model (import)' round-trips the model). |
| `shell_app.py` | The Tk interface: left panel pages Definitions / Supports / Loads / Design; 3-D view with colour maps (`FIELDS`), click an element for its numbers, section cut window, report window, Excel buttons, unit wiring. |

Shared: `formula.py` (Workspace of definitions like `a = 12`,
`z(x, y) = 2 f x y / (a b)`; sliders on free numbers; errors shown per line;
safe evaluation through an AST allow-list, no `eval` of raw text) and
`view3d.py` (`Orbit3D`, `VIEWS`, `colours_for`).

### Conventions you must keep

- Local element axes: e1 = global X projected on the surface; e3 = normal.
- **M positive = tension on the bottom face.** N positive = tension.
- Loads: vertical per m² of plan or of surface, normal pressure (wind),
  horizontal x/y, point loads; each value may be a formula in x, y.
- Self-weight is automatic from thickness × unit weight (25 kN/m³).
- **Point supports and columns are rigid blocks** (default 1.0 m) tied to the
  shell by very stiff arms. A true point support gives forces that grow without
  limit as the mesh is refined — do not "simplify" this back to a point.
  An element belongs to a block only if **all 4** of its nodes are tied.
- Mesh is sized by element length (default 0.5 m); a block must span several
  elements or punching results are unreliable (the app warns).
- Wind: speeds are CIRSOC 102-**2005**; under the 2024 code W is multiplied by
  **1.6** (field "speed from" = 2024 removes that).
- Minimum thickness from 35 mm weather-exposed cover: 8.6 cm (one mesh) /
  12.2 cm (two meshes). This is the check that often governs thin shells.

### Verification done (pinned in `tests/test_shell_engine.py`)

- Scordelis–Lo roof: within 1.1 % of 0.3024 ft.
- Simply-supported flat plate vs series solution.
- Hypar with stiff edge beams: interior Nxy → q/(2k) within 0.5 %; with
  realistic beams the shell carries 4–5 % more (report shows the comparison).
- Reactions = applied load in all 6 directions for every preset.
- Mechanism detection (supports that only hold vertically are refused with a reason).
- UI sweep: every preset × every colour map, bad formulas, thickening round
  trip, Excel round trip, unit switching (`tests/test_shell_app.py`, 25 tests).

### Important CIRSOC facts found in the owner's PDF (2024 draft)

- It has **no shell chapter**; C 1.2.10.7 points to CIRSOC 201.03 (not yet
  published). Shell-specific rules therefore come from CIRSOC 201-2005 /
  ACI 318 practice and are listed in the report as "verify before sign-off"
  (`shell_codes.py` → `UNVERIFIED`).
- Combinations (Tabla 5.3.1) use 1.0 W, which assumes the new 2024 wind speeds.

## 5. What is left — pick from this list

Ordered roughly by value to the owner. Each item says where to work.

1. **ACI 318-19 and Eurocode 2** (owner asked for these "later"). Add a class
   per code in `shell_codes.py` subclassing `DesignCode`, fill the same methods
   (`strut_strength`, `max_spacing`, combinations, Vc, punching_vc, cover,
   clauses), add to `CODES`/`CODE_ORDER`. No other file should need code
   numbers. Add tests mirroring the CIRSOC ones.
2. **Check the "unverified" shell rules** once the owner supplies CIRSOC 201-2005
   or ACI 318.2 text; update `UNVERIFIED` and cite clauses.
3. **Edge-beam full design**: axial force + bending + shear diagrams along each
   beam and required steel (today only a preliminary check in `design_beams`).
   Add a beam diagram window like the Beam tab.
4. **Global buckling** (whole-shell): today only local buckling with a knock-down
   factor. Needs a geometric stiffness matrix in `shell_fe.py` and an
   eigenvalue solve (`scipy.sparse.linalg.eigsh`, shift-invert).
5. **Non-rectangular plans** (circles, polygons): mesh is currently a rectangle
   in plan (`ShellModel.mesh`).
6. Plan items not built: pinched-hemisphere and clamped-hypar benchmarks; a test
   that edge-beam force grows linearly along the edge; a numerical membrane
   solution for any surface; two extra presets (Candela umbrella quarter,
   four-hypar groined vault); contour lines with values in the top view; load
   arrows in the 3-D view; drawing thickening zones with the mouse (now typed
   as rules like `abs(x) < 1 and abs(y) < 1`).
7. Update to CIRSOC 102-2024 wind speeds and CIRSOC 201.03 when published.
8. Move the Stereo tab onto `view3d.py` and wire it to the unit selector (it
   ignores it now; its labels state units so nothing shown is wrong).

## 6. Pitfalls already hit (don't repeat)

- SuperLU returns garbage silently on a singular system → keep the residual
  check in `solve`.
- The thickness search grid must include the current thickness, or passing
  elements get reported as needing more.
- The automatic thickening layer is stored as `{'h', 'points'}` and applies only
  near those points; a "nearest point" rule thickened the whole shell.
- The utilisation map defaults to **structural** checks; the cover/minimum
  thickness check made the full map a uniform colour.
- Membrane-theory comparison must use shell-only loads (not beam self-weight).
- In Bash, heredocs with backticks break; write patch files instead.

## 7. Deliverables of this session

- Commits 53c9ca7 and 6dd86f4 (+ this guide) on the branch above.
- Zip: `STRUCTURAL-SYMULATOR-SOLVER_2026-09-15_handoff.zip` in the owner's
  working folder (no `__pycache__`), top folder `STRUCTURAL-SYMULATOR-SOLVER-5-9-26/`.
- Requirements: `pip install -r requirements.txt` (numpy, scipy, openpyxl;
  add pytest to run the tests).
