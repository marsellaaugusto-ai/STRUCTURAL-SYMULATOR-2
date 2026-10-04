# Beam tab — recommendations for the next update, 2026-10-04

**File reviewed:** `apps/beam/beam_app.py` (1 576 lines), with
`tests/test_beam_math.py` (267 lines, 20 tests), `tests/test_units_in_beam_tab.py`,
`tests/test_excel_roundtrip.py`, `tests/test_tab_layouts.py`.

**Method:** MANIFESTO §2 — real widgets on a real display (Xvfb), real canvas
items measured with `bbox()`, solver results checked against closed forms.
Nothing below is inferred from reading code alone except where it says so.

**Baseline measured today:** `test_beam_math.py` + `test_units_in_beam_tab.py`
+ `test_excel_roundtrip.py` + `test_tab_layouts.py` → **52 passed, 0 failed.**
Solver re-validated against SS+UDL (M = wL²/8 ✔), cantilever tip deflection
(PL³/3EI and wL⁴/8EI, worst error 2 × 10⁻⁵ ✔), propped cantilever, fixed–fixed
(wL²/12 and wL²/24 ✔), 2-span continuous. **The solver is correct on every
closed form tried.**

### First, the good news: the 2026-09-10 Beam report is out of date

`REMAINING_BUGS_BEAM_2026-09-10.md` still lists B-1, B-3, B-4, B-5 and B-7 as
open. All five are fixed in this tree, and I re-verified each one:

| old finding | status today |
|---|---|
| B-1 fixed–fixed beam will not solve | ✅ fixed (`MAX_ELEM_FRACTION` mesh refinement) |
| B-3 load arrows at constant length | ✅ fixed (`LoadScale`, true q(x) chord) |
| B-4 reversed distributed load ignored | ✅ fixed (`add_dload` normalises, w₁/w₂ travel with their ends) |
| B-5 off-beam coordinates extend the mesh | ✅ fixed (`_on_beam` in model **and** dialogs) |
| B-7 no physics tests | ✅ fixed (`test_beam_math.py`, 20 tests) |
| B-6 dead imports | ❌ still open (6, pyflakes-confirmed) |
| B-8 diagram caption collides with its labels | ❌ still open, slightly worse (§R-13) |
| `sample_diagram` O(n²) (FIXES §8) | ✅ fixed (`_integrate_deflection`; 40 loads now sample in 0.01 s) |

So this is not a list of old debt. Everything in Tier 1 below is new.

---

## Priority list

| # | recommendation | severity | effort |
|---|---|---|---|
| **R-1** | Two supports at the same station double-count the reaction — silently wrong V, M, σ | **HIGH** | ✅ **done** |
| **R-2** | No equilibrium / closure self-check anywhere in the results | **HIGH** | ✅ **done** |
| **R-3** | Reaction-moment sign is a heuristic, wrong in meaning at an interior fixed support | MED | ~3 h |
| **R-4** | Non-uniform q(x) loads bypass the unit layer *and* the on-beam check | MED | ~2 h |
| **R-5** | No validation of L, E, I, c, A — negative EI solves and returns garbage | MED | ✅ **done** |
| **R-6** | Non-numeric entry raises an unhandled `TclError`; the user sees nothing | MED | ✅ **done** |
| **R-7** | Shortening the beam leaves stale off-beam rows; Analyze then fails wholesale | MED | ✅ **done** |
| **R-8** | Split `beam_math.py` out of `beam_app.py` — the project's own stated boundary | MED | ~3 h |
| **R-9** | Adopt `common.UnitsMixin`; hard-coded `kN` / `kN/m` labels ignore the selector | MED | ~3 h |
| **R-10** | 6 dead imports (B-6) | LOW | 5 min |
| **R-11** | Retire the stale 2026-09-10 Beam report | LOW | 15 min |
| **R-12** | Tests for everything above, before the fixes land | MED | ~3 h |
| **R-13** | Diagram captions still collide — now even at 1500 px | LOW | ~1 h |
| **R-14** | No row editing, no undo, results box is editable | LOW | ~4 h |
| **R-15** | No zoom/pan, no hover readout, no diagram export | LOW | ~6 h |
| **R-16** | Results omit *where* the maxima are, both M extremes, and any deflection limit | MED | ~2 h |
| **R-17** | Excel: `w1_kNm` mislabels a kN/m load; imports are unvalidated | LOW | ~2 h |
| **R-18** | No internal hinges, springs or prescribed settlements | feature | ~1 d |
| **R-19** | One scalar EI — no stepped or haunched beams | feature | ~1 d |
| **R-20** | No load cases or factored combinations (the module already exists) | feature | ~1 d |
| **R-21** | Section properties typed by hand; no code check, crude V/A shear | feature | ~2 d |
| **R-22** | No equation guide, which `requirements.txt` already promises | feature | ~4 h |

---

# Tier 1 — correctness

## R-1 · HIGH · Two supports at the same station double-count the reaction

> **✅ Fixed 2026-10-04.** `add_support()` folds a second support at an
> occupied station into the first (union of restrained DOF, so pin + guided
> becomes a genuine `fixed`), the merge is reported in the RESULTS panel and
> the workbook, and `_V_M_at` now iterates support **nodes** so a duplicate
> reaching the list by another route cannot double count again. Covered by
> 9 tests in `test_beam_math.py` and 3 in `test_beam_equilibrium_report.py`.

The single highest-value fix in the tab. Measured, SS beam, L = 6 m, UDL
10 kN/m (total load 60 kN), with a `pin` **and** a `roller` both at x = 0:

```
REACTIONS
  x=0.00 m (pin    ): Ry=  +30.00 kN   M=   +0.00 kN·m
  x=0.00 m (roller ): Ry=  +30.00 kN   M=   +0.00 kN·m
  x=6.00 m (roller ): Ry=  +30.00 kN   M=   +0.00 kN·m     <- 90 kN of reaction for 60 kN of load

Max |V|  =    60.00 kN      (true  30.00)
Max |M|  =   180.00 kN·m    (true  45.00)
Max |defl| =   67.503 mm    (true  10.546)
STRESS CHECK   Bending sigma = 337.500 MPa   (FAIL, ratio 2.11)   <- a passing beam reported as failing
```

Worse, because it looks like a legitimate modelling choice: `pin` + `guided`
at the same x is how a user without a `fixed` type in mind builds a fixed end.

```
pin + guided at x=0, UDL 10 kN/m, roller at 6     exact (propped cantilever)
  x=0: V = +75.00   M =  -90.00                     RA = +37.5, M(0) = -45
  x=6: V = +37.50   M = +180.00                     RB = +22.5, M(6) =   0
```

The moment diagram does not even close to zero at a free end, and nothing warns.

**Root cause.** `BeamResult.reaction_at(x)` looks a reaction up **by station**
(`self.idx_of[round(x, 9)]`), so two supports sharing a node both return that
one node's residual. `_V_M_at` then loops `for s in self.model.supports` and
adds the same `Fy` once per support, and `_show_results` prints it once per
support. Constraint assembly in `solve()` is correct — `constrained[2*i] = 0.0`
twice is idempotent — so the solved displacements are right and only the
*recovery* is wrong. That is why no closed-form test catches it.

**Recommended fix** (either, not both):

* **Model-level:** `add_support` merges a second support at an existing
  station into the constraint set of the first (`pin` + `guided` → `fixed`,
  `pin` + `roller` → `pin`) and the UI tells the user it did so. This is
  strictly better than refusing, because the merged result is what the user
  meant.
* **Recovery-level:** make `_V_M_at` and the reactions report iterate over
  **constrained nodes**, not over the `supports` list.

Do the model-level merge *and* keep the recovery loop over nodes — the second
makes the class of bug unreachable even if a future editor re-introduces
duplicates.

**Verify:** the five models above against their closed forms, plus
ΣRy = Σloads and V(L⁺) = M(L⁺) = 0 for each.

## R-2 · HIGH · Nothing checks equilibrium, so R-1 could ship unnoticed

> **✅ Fixed 2026-10-04.** `BeamResult.equilibrium()` returns the force and
> moment residuals, the diagram closure beyond x = L, both scales, the
> restrained-DOF count and the degree of indeterminacy; the panel and the
> Excel `Results` sheet print them. The applied-load leg is integrated from
> the load definitions, independently of the solve. Measured residuals are
> 1e-16 to 1e-13 of the applied load on every model in the suite, and a
> deliberately corrupted reaction is caught.

The results panel prints reactions and extremes and stops. Add three numbers
the user — and the test suite — can read at a glance:

```
EQUILIBRIUM          ΣFy = +0.000 kN   (residual 1.2e-13)
                     ΣM about x=0 = +0.000 kN·m
CLOSURE              V(L⁺) = 0.000 kN     M(L⁺) = 0.000 kN·m
```

Measured today, these are ~1 × 10⁻¹³ on every valid model and grossly non-zero
on the R-1 duplicate-support model. One assertion on the residual would have
caught R-1 the day it became reachable. Put the same three rows in the Excel
`Results` sheet, where a reviewer looks for them.

Also report the degree of static indeterminacy (restrained DOF − 2, after the
R-1 dedup). It costs one line and tells the user whether the answer they are
reading depended on EI at all.

## R-3 · MED · The reaction moment is a heuristic, and means something else at an interior support

`reaction_at` returns a raw rotational-DOF residual, and `_show_results`
negates it **only at x = 0**. The docstring is admirably honest that this was
established by testing left-end, right-end and both-ends fixed cases. It does
not hold up at an interior fixed support:

```
L = 6, fixed at x = 3 only, 10 kN at x = 0 (left cantilever)
  displayed:  M = -30.00 kN·m
  M(2.99) = -29.90      M(3.01) = 0.00
  the moment the support applies to the beam = +30 kN·m
```

The printed number is the *internal* moment just left of the support, not the
support's reaction — correct-looking, useful even, but not what the column
heading says, and it is a single number where there are two different internal
moments to report.

**Recommended fix:** derive the reaction moment from the moment jump at the
node, `M_reaction = M(x⁺) − M(x⁻)`, which needs no sign heuristic and is
correct at any station; then print, for every fixed/guided support,
`M_reaction`, `M(x⁻)` and `M(x⁺)`. Delete the `if s['x'] < 1e-9: Mr = -Mr`
special case in both `_show_results` **and** `export_beam_excel` (it is
duplicated there). Pin the left-end, right-end, both-ends and interior cases
in `test_beam_math.py` first — the current behaviour at the two end cases must
not change.

## R-4 · MED · Non-uniform q(x) loads bypass the unit layer and the on-beam check

Everything else in the tab was wired through `units.py` and `_on_beam`; this
one dialog was left behind.

* `_add_nonuniform_load` hard-codes `'x₁ (m):'` / `'x₂ (m):'` and stores
  `x1_var.get()` **raw** — no `self._stored('x', …)`. But `_refresh_tables`
  *does* convert those columns (`_FIELD_Q` maps `x1`/`x2` → `length`). Under
  AISC, the dialog defaults x₂ to `6.0` labelled "m" while the table next to
  it reads `19.69` — and a user who types `20` meaning feet gets a 20-metre
  load.
* The expression is always interpreted as **kN/m** (`_qfn(x) * 1e3` in
  `_analyze`), whatever the selector says, and the schematic label prints
  `q(x) = …` with no unit at all.
* There is no `_on_beam` call. `_analyze` silently **clamps**
  (`max(0.0, min(self.length, …))`) while every other load type is refused
  with a message — the exact inconsistency B-5 was raised to remove.

**Fix:** route the two stations through `_stored`/`_shown` and `_on_beam`,
label the expression's unit with `units.label('line_load')`, and scale by the
same storage→SI factor the other loads use rather than a literal `1e3`.
Decide and document one thing: is `q(x)` in display units or always kN/m?
Either is defensible; silently being the second while the tab shows the first
is not.

## R-5 · MED · No validation of the beam's own numbers

> **✅ Fixed 2026-10-04.** `BeamModel._valid_length` / `_valid_EI` guard the
> model on the way in and again at solve time, each naming the real cause
> instead of "fully constrained" or "a mechanism". `BeamApp._model_problems`
> collects **every** reason a model cannot be analysed — bad length, no
> support, each stranded row, each non-positive E/I/c/A, each negative
> allowable — and reports them in one dialog. A zero allowable now prints
> `not checked (no allowable stress given)` instead of `OK`.

| input | today | should be |
|---|---|---|
| `L = 0` | "Beam is fully constrained; nothing to solve" | "Beam length must be greater than zero" |
| `E = 0` | "Singular stiffness matrix — beam is a mechanism" | named for the real cause |
| `EI < 0` | **solves**, returns sign-flipped deflections, no warning | refused |
| `A = 0` | shear ratio silently reported as 0 | refused |
| `allow_bend = 0` | ratio forced to 0, printed `OK` | refused, or printed as "not checked" |

The `allow_bend = 0 → OK` path is the one to fix first: `bend_ratio = … if
self.profile['allow_bend'] else 0` turns a missing allowable into a **pass**.
A missing allowable should read `not checked`, never `OK`.

Put the guards in `BeamModel.solve()` (so a model driven from a script or an
imported workbook is covered) and surface them in `_analyze`.

## R-6 · MED · Non-numeric input raises an unhandled `TclError`

> **✅ Fixed 2026-10-04.** One `_num(var, label)` read behind every entry
> box, raising a message that names the field and quotes what was typed;
> `_set_length` warns and puts the working length back, both Add dialogs
> stay open so the number can be corrected where it was typed, and
> `_current_state` (which feeds the export) fails by field name.
>
> **Noticed while testing it, still open:** the tab builds its `DoubleVar`s
> with no `master`, so they bind to `tkinter._default_root` rather than to
> the tab's own interpreter. In the running app that is the same object and
> nothing is wrong; under a test suite that creates several roots it is not,
> which is why one of these tests passed alone and failed in the full suite.
> Worth passing `master=self` when `_build_ui` is next touched (R-9 does).

Measured: type `abc` in the length box and press **Set length** →

```
TclError: expected floating-point number but got "abc"
```

`_set_length` has no `try`, so the exception escapes into the Tk callback: the
length does not change, **and no message appears**. In a double-clicked app
the traceback goes to a console nobody sees. The same hole is in `_ask`'s
`ok()` and in `_add_nonuniform_load`'s `ok()` — both read `DoubleVar.get()`
unguarded, and the dialog simply sits there. `_analyze` is wrapped, but shows
the raw Tcl text.

**Fix:** one `_read_float(var, label)` helper that catches `TclError` and shows
`'<label> must be a number; got "abc"'`, used by every entry read in the tab.
Prefer `tk.StringVar` + explicit parse over `DoubleVar` for new fields.

## R-7 · MED · Shortening the beam leaves rows that are no longer on it

> **✅ Fixed 2026-10-04.** **Set length** now counts what would fall off and
> asks once — *Delete them / Move them onto the beam / Cancel* (dismissing
> the dialog means cancel) — through `_entries_off_beam`, `_apply_length`
> and `_ask_stray_policy`, kept separate so the policy is testable without
> driving a modal dialog. Clamping drops a distributed segment that would
> collapse to zero width, since a no-op load row is the same class of
> silence. Any row still off the beam is tagged red in its own table, and
> Analyze names every one of them rather than the first.
>
> The remaining route by which a stranded row can reach Analyze is an
> imported workbook, which validates nothing — see **R-17**.

Measured: L = 6 with a point load at x = 5, then set length to 3 →

```
length = 3.0 | load still at x = 5.0 | row still shown: [5, 10]
▶ Analyze  ->  "Support at x = 6 m is not on the beam, which spans 0 to 3 m."
```

The dialogs now refuse an off-beam station (B-5, fixed) but **Set length** can
still strand entries that were legal when entered. Analyze then fails
wholesale, naming whichever entry it happened to reach first, and nothing marks
the offending rows. The 2026-09-10 report asked for this decision explicitly
and it is still open.

**Recommended behaviour:** on **Set length**, count the entries that would fall
off and ask once — *"3 entries lie beyond x = 3 m. Delete them / clamp them to
the new end / cancel."* Then tag any remaining out-of-range row with a red
Treeview tag so it is visible before Analyze, and make `_analyze` report
**every** invalid row, not just the first.

---

# Tier 2 — architecture and maintainability

## R-8 · MED · Split `beam_math.py` out of `beam_app.py`

`MODULAR_ARCHITECTURE.md` states the project's own boundary: Truss, Cable Web,
Perforated Beam and Stereo all split a pure-Python engine from the Tkinter
controller, and the split is called "the intended C++ migration boundary."
Beam is the tab that boundary matters most for, and it is the one still fused:
`BeamModel`, `BeamResult`, `_adaptive_vector_integral`, `_gauss_VM_integral`
and both Excel functions sit in the same file as `import tkinter as tk`.

This is not theoretical. Reviewing this tab, `pytest tests/test_beam_math.py`
**could not run at all** until I installed a Python with Tk — to test a
solver that has no UI in it. A contributor on a headless box or in CI hits the
same wall:

```
tests/test_beam_math.py:23: in <module>
    from apps.beam.beam_app import BeamModel
apps/beam/beam_app.py:8: in <module>
    import tkinter as tk
E   ModuleNotFoundError: No module named 'tkinter'
```

**Fix:** move `BeamModel`, `BeamResult` and the two quadrature helpers to
`apps/beam/beam_math.py`; move `export_beam_excel` / `import_beam_excel` to
`apps/beam/beam_reports.py` (mirroring `truss_reports.py`). `beam_app.py`
keeps the widgets and drops to roughly 900 lines. Re-export the names from
`beam_app` for one release so `test_truss_math.py`, which imports `BeamModel`
as its cross-check reference, keeps working unchanged.

## R-9 · MED · Adopt `common.UnitsMixin`, and let the panel headings follow the selector

`common.UnitsMixin` exists *because* of this tab — its docstring says the Beam
tab was wired to `units.py` by hand first and the machinery was then extracted
so it would not be copied six times. Arch, Cable Web and Stereo use the mixin;
Beam still carries the original hand-rolled copy (`_shown`, `_stored`,
`_FIELD_Q`, `_SECTION_Q`, `_u`, `_sec_shown`, `_sec_stored`,
`_on_units_changed`, a manual listener). Two implementations of one idea is
how two tabs end up disagreeing about what a kip is.

While in there, fix what the hand-rolled version never covered — four headings
that hard-code SI and do not repaint on a switch:

```
'POINT LOADS (+down, kN)'              -> units.label('force')
'POINT MOMENTS (+CCW, kN·m)'           -> units.label('moment')
'DISTRIBUTED LOADS (+down, kN/m)'      -> units.label('line_load')
'q(x) in kN/m (+down), over a sub-domain [x₁,x₂] (m)'
```

and the distributed-load tree's column headings, which read bare `x1 x2 w1 w2`
with no unit in any convention. `test_units_in_every_tab.py` is the natural
place to assert that no tab paints a hard-coded `kN` while AISC is selected.

## R-10 · LOW · Dead imports (B-6, still open)

```
apps/beam/beam_app.py:10: 'os' imported but unused
apps/beam/beam_app.py:10: 'sys' imported but unused
apps/beam/beam_app.py:10: 'subprocess' imported but unused
apps/beam/beam_app.py:14: 'common.INIT_CW' imported but unused
apps/beam/beam_app.py:14: 'common.INIT_CH' imported but unused
apps/beam/beam_app.py:14: 'common.INIT_DH' imported but unused
```

Truss is pyflakes-clean (T-3). Fold this into the R-8 file split, which
touches the import block anyway.

## R-11 · LOW · Retire the stale Beam bug report

`REMAINING_BUGS_BEAM_2026-09-10.md` and `REMAINING_BUGS_INDEX_2026-09-10.md`
both still mark B-1/B-3/B-4/B-5/B-7 as **OPEN** although `FIXES_2026-09-10.md`
closes them. A reader who opens the "remaining bugs" file first — the natural
thing to do — is told the highest-severity bug in the project is live when it
is not. Add a status banner at the top of each pointing at `FIXES` and at this
file.

## R-12 · MED · Tests to add — before the fixes, not after

`test_beam_math.py`'s 20 tests cover the closed forms well. Every Tier 1 item
above is a hole it does not reach:

* **R-1:** duplicate `pin`+`roller`, `pin`+`guided` and `fixed`+`roller` at one
  station → ΣRy = Σloads, and V/M equal to the single-support reference.
* **R-2:** ΣFy, ΣM and V(L⁺)/M(L⁺) residual < 1e-9 across a parametrised set
  of models — the regression net for the whole recovery path.
* **R-3:** reaction moment at a left-end, right-end, both-ends and **interior**
  fixed support, against the moment jump.
* **R-4:** a `q(x)` load entered under AISC produces the same analysed model as
  the SI-entered equivalent (a round-trip assertion, like
  `test_units_in_beam_tab.py` does for the other fields).
* **R-5:** `L = 0`, `E = 0`, `EI < 0`, `A = 0`, `allow_bend = 0` each raise
  their own named error, and `allow_bend = 0` never prints `OK`.
* **R-6:** the entry-read helper turns `"abc"` into a message, not a `TclError`.
* **R-13:** zero overlapping text bounding boxes in `diag_canvas` at 1500 /
  1200 / 900 / 700 px — the same shape of assertion `test_tab_layouts.py`
  already makes.

---

# Tier 3 — UI and reporting

## R-13 · LOW · Diagram captions still collide (B-8), now at every width

Re-measured today on the live canvas (L = 10, UDL 6 kN/m, 25 kN at x = 7),
counting overlapping text bounding boxes in `diag_canvas`:

| window | canvas | collisions | worst |
|---|---|---|---|
| 1500 px | 938 px | **1** | `x=10.00` × `max ±117.19` (36 px) |
| 1200 px | 642 px | 2 | caption × `x=6.25` (31 px) |
| 900 px | 477 px | 4 | caption × `max ±117.19` (26 px) |
| 700 px | 367 px | 4 | caption × `max ±117.19` (65 px) |

The old report measured 0 collisions at 1500 px; the peak-marker label at the
right-hand end now runs into the `max ±…` readout even on a wide window, so
this got slightly worse, not better. The schematic canvas is clean at all four
widths (`declutter_text` is doing its job there).

**Fix:** reuse what A-5 already built for Arch — `arch_app.py:1845-1875` fits
each caption to the panel (full text → name → symbol), reserves a right-hand
strip, and drops `max ±…` to the bottom-right when the panel is too narrow.
Lift that into `common.py` as one helper and call it from both tabs; a peak
label within ~40 px of the right edge should anchor `'e'` instead of centred.

## R-14 · LOW · No row editing, no undo, and the results box is editable

* Every table is Add/Delete only. To change one load's magnitude the user
  deletes the row and retypes it. Bind `<Double-1>` to reopen `_ask`
  pre-filled, which is ~20 lines given `_ask` already exists.
* There is no undo in this tab (`grep -c undo` → 0), while Truss, Cable Web,
  Stereo and the profile sketcher all have one. A deleted load is gone.
  A single `_snapshot()`/`Ctrl-Z` over the five lists plus `length` and
  `profile` would cover the tab, since all of its state is plain dicts.
* `self.res_text` is a `tk.Text` with no `state='disabled'`, so the user can
  type into their own results. Set it disabled (re-enable around the
  `insert`), which keeps copy working and stops accidental edits.

## R-15 · LOW · No zoom, no hover readout, no diagram export

`common.ZoomCanvas` is used by Truss, Cable Web, Stereo, the perforated-beam
views, the profile sketcher and the section-profile UI. Beam's schematic and
diagram panes are plain `tk.Canvas`: a 40-load beam cannot be inspected, and a
20 m beam's near-support region cannot be read at all.

Three additions, in value order:

1. **Hover readout** — a vertical cursor on the three bands with
   `x`, `V`, `M`, `δ` at the pointer. The data is already sampled in
   `sample_diagram`; this is the single most-asked-for thing in a beam tool
   and the diagrams currently label only the automatic maxima.
2. **ZoomCanvas** for both panes, for consistency with the five modules above.
3. **Export the diagrams** — `Canvas.postscript()` is one call, and a PNG via
   the already-optional Pillow. Today a report needs a screenshot.

## R-16 · MED · The results panel omits the things a checker writes down

`_show_results` prints reactions, `max |V|`, `max |M|`, `max |δ|` and two
stress ratios. Missing, in rough order of how often it is needed:

* **Where** the maxima are. The diagram marks peaks with red dots; the text
  — the part that gets copied into a calculation — gives no x.
* **Both** moment extremes. `max(diag['M'], key=abs)` collapses sagging and
  hogging into one absolute number; a continuous beam needs M⁺ and M⁻ with
  their stations, and a different section modulus may apply to each.
* **A deflection limit.** `max |δ|` is printed with nothing to compare it to.
  Add an input span/ratio (L/360, L/250, …) and a pass/fail, the same shape as
  the two stress checks. Serviceability is what governs most real beams in
  this tab's range.
* **σ and τ are evaluated at different stations.** `max|M|` and `max|V|`
  generally do not coincide, so the pair is conservative but not a real
  section check at any one point. State that in the panel, or evaluate the
  utilisation station-by-station and report the governing x (see R-21).

## R-17 · LOW · Excel round-trip details

* **Mislabelled header.** `[DISTRIBUTED_LOADS]` writes `w1_kNm` / `w2_kNm` for
  a load in **kN/m**. Anyone filling the sheet by hand reads that as kN·m.
  Rename to `w1_kN_per_m`, accepting the old name on import — the file already
  does exactly this for the renamed `[DLOADS]` section, so the precedent and
  the code pattern are both there.
* **Imports are unvalidated.** `import_beam_excel` does not check that a
  support `type` is one of the four known strings, that stations lie within
  `length`, or that `length > 0`. A hand-edited workbook therefore fails at
  **Analyze**, far from the file that caused it. Validate on import and report
  the offending row number.
* **A short row raises `IndexError`.** `read_table` does
  `{headers[j]: vals[j] for j in range(len(headers))}`; a row with fewer cells
  than headers crashes with no row number. Use `vals[j] if j < len(vals)`.
* **Sheets are always in storage units** (kN, m, cm⁴) by deliberate design —
  `units.py` explains why, and it is the right call. Write that in the Model
  sheet's header line, so an AISC user who exports does not read the numbers
  as kip.

---

# Tier 4 — features, in the order I would build them

## R-18 · Internal hinges, springs, prescribed settlements

Support types are `pin`, `roller`, `fixed`, `guided`. The most common thing a
beam tool is asked for next is the **internal hinge** (Gerber / cantilevered
construction) — a second rotational DOF at a node, which is a localised change
to `_node_positions` and the constraint assembly. Then **elastic supports**
(add `k` to the diagonal — one line, and it makes R-1's duplicate-support
scenario moot for the users who were approximating springs that way), and
**prescribed settlements** — `solve()` already stores a *value* per
constrained DOF (`constrained[2*i] = 0.0`) rather than just a flag, so half
the plumbing is there; a non-zero one also needs the `K_fc · d_c` term on the
right-hand side, which that dict keeps contained.

## R-19 · Variable EI

`BeamModel.EI` is a single scalar, so a stepped, spliced or haunched beam
cannot be modelled — and a continuous beam with a deeper section over the
supports is exactly what the hyperstatic solver is for. Make it
`EI(x)`-per-element: the element loop already computes `k = EI / Le**3`
locally, so the change is contained, and `BeamResult._theta_v_at` /
`_integrate_deflection` need `EI` sampled per interval instead of once.
Pair it with a segment table in the panel.

## R-20 · Load cases and factored combinations

`apps/perforated_beam/load_combinations.py` already implements factored
combinations (D/L factors, LRFD φRn vs ASD Rn/Ω via the `φΩ = 1.5` identity)
and is well documented. Beam checks loads **as entered** — so its utilisations
are systematically unconservative against any report that applied 1.2D + 1.6L,
which is the same "two correct calculations of two different things" problem
that module was written to end. Promote it to a root-level shared module (as
`cirsoc_301.py` was on 2026-09-06, for the same cross-tab reason — Perforated
Beam and Truss both needed it) and give Beam a case-per-load column plus a
combination picker, then an envelope over the selected combinations.

## R-21 · Real section properties and a real code check

Today the user types `I`, `c`, `A` by hand and gets elastic `M·c/I` and `V/A`
against an allowable. The parts for better already exist in the repo:

* `apps/perforated_beam/section_shapes.py` + `section_profile_ui.py` — a
  section library and designer that return A, I, S and a drawable outline.
  Beam could adopt them wholesale (both are UI-independent pure geometry at
  the math layer), and a section picker would remove the single most
  error-prone manual input in the tab.
* `cirsoc_301.py` — φ factors and nominal strengths. A real Mn (including
  lateral-torsional buckling, which an unbraced beam needs and this tab cannot
  express at all — there is no unbraced-length input) and Vn beat an allowable
  typed into a box.
* `V/A` with the gross area over-estimates shear capacity for an I-section;
  `V/A_web` or `VQ/It` is the right form, and `section_shapes` can supply Q.

Even without the code layer, evaluating the utilisation at every sampled
station and reporting the governing x would fix R-16's "σ and τ at different
places" problem for free.

## R-22 · The equation guide `requirements.txt` already promises

`requirements.txt` says matplotlib and Pillow are auto-installed "for the
LaTeX-style equation images in the **Truss/Beam/Arch** guides." Only Truss has
one (`_ensure_matplotlib` / `render_math`, `truss_app.py:4541`). Beam has no
guide at all. `common.render_math` is ready; a Beam guide showing the Hermite
element, the consistent load vector and the M/EI integration — with the tab's
sign conventions stated once, in one place — would also retire a recurring
source of confusion that R-3 and the `reverse_bmd` checkbox both point at.

### Also worth considering later

Influence lines and moving loads (a bridge/crane beam is the obvious next
engineering feature, and the solver is fast enough now — 40 loads sample in
0.01 s); a self-weight toggle driven by the section area and a unit weight
(`common.DEFAULT_SELF_WEIGHT` and `stereo_math.self_weight_loads` set the
pattern); and JSON model save/load alongside Excel, for a quick round-trip
that does not need openpyxl.

---

## Repository hygiene, outside the Beam tab itself

The repo root holds three zip archives plus a second, older tree
(`structural_simulator_v15_fixed15/`, whose `beam_app.py` is 1 220 lines — the
ancestor of this one, without the B-1/B-3/B-4/B-5 fixes). Anyone opening the
repo has four plausible copies of the Beam app to read and no marker saying
which is live. Keep `STRUCTURAL SYMULATOR SOLVER-5-9-26/` as the tree of
record, drop the zips (git is the archive), and leave a one-line README at the
root saying so.

---

## Suggested sequencing

1. **R-12 first** (tests for R-1/R-2/R-5/R-6 as *failing* tests), then
   **R-1, R-2, R-5, R-6, R-7** — one commit per finding, each with its test.
   R-2's equilibrium assertion is the net that holds everything after it.
2. **R-8 + R-10** together (the file split touches the import block), then
   **R-9** on the split file. Pure refactors, with the Tier-1 tests already in
   place to prove nothing moved.
3. **R-3, R-4, R-16, R-17, R-13** — sign conventions, units and reporting, all
   small and all user-visible.
4. **R-11** as the sequence lands, so the reports describe the tree again.
5. Tier 4 by whichever the users ask for; **R-18 (internal hinge)** and
   **R-20 (combinations)** are the two that change what the tab can answer.

Tier 1 is roughly a day and a half and removes every known way this tab can
return a wrong number without saying so. That is the update I would ship first.
