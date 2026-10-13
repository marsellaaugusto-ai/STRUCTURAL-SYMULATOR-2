# Beam tab overhaul — session handoff, 2026-10-04 → 2026-10-13

Everything one session did to the Beam tab, written to be picked up by someone
who was not there. It assumes only that you can run the app.

**Repository:** `marsellaaugusto-ai/STRUCTURAL-SYMULATOR-2`
**Branch:** `claude/sleepy-bohr-sizbwf` (9 commits ahead of `main`, pushed)
**Tree of record:** `STRUCTURAL SYMULATOR SOLVER-5-9-26/`
**Test suite:** 1259 passing at the start → **1452 passing, 0 failing** now
**Companion documents:**
`BEAM_UPDATE_RECOMMENDATIONS_2026-10-04.md` (the review, with every item's
status) and `BEAM_TAB_CURRENT_STATE_2026-10-13.md` (what the tab does now).

---

## 1. What was asked, and what happened

The request was: *"take a look at the beam app … I would like a list of
recommendations in order to update it."* That produced a measured review of
22 items (R-1 … R-22). The next ten exchanges implemented R-1 … R-17 — every
correctness, architecture and reporting item. R-18 … R-22 are features and
remain open; they are specified in the review.

The method throughout, which the project's own MANIFESTO §2 asks for: real
widgets on a real display (Xvfb), canvas items measured with `bbox()`, solver
results checked against textbook closed forms, and **tests written first and
confirmed failing for the right reason** before any fix.

---

## 2. The nine commits

| commit | what it did |
|---|---|
| `f7853f3` | The review itself: 22 prioritised recommendations, measured. |
| `bb78d4c` | **R-1, R-2** — stop double-counting a shared reaction; add an equilibrium self-check. |
| `79bfc7f` | **R-5, R-6, R-7** — validate the inputs, name the bad field, handle stranded rows. |
| `f1702c1` | **R-3, R-4** — a reaction moment that means one thing; q(x) loads wired to the unit layer. |
| `5127c47` | **R-8, R-10** — split the solver out of the UI behind a numeric core that needs no Tk. |
| `d82573a` | **R-9** — one implementation of the unit layer; labels follow the selector. |
| `4b31a8e` | **R-16, R-17** — report where the extremes are, check deflection, validate workbooks. |
| `cdded4e` | **R-13** — a diagram pane that stays readable as it narrows. |
| `1e7541e` | **R-14, R-15** — edit rows, undo, hover readout, x zoom, diagram export. |

Net: **+6376 / −1068 lines** across 17 files.

---

## 3. The first thing to know: the old bug report was wrong

`REMAINING_BUGS_BEAM_2026-09-10.md` lists B-1, B-3, B-4, B-5 and B-7 as open.
**All five were already fixed** when this session started; `FIXES_2026-09-10.md`
closes them. A reader who opens the "remaining bugs" file first — the natural
thing to do — is told the highest-severity bug in the project is live when it
is not. Only B-6 (dead imports) and B-8 (caption collisions) were genuinely
open, and both are now done too (as R-10 and R-13).

Treat `BEAM_UPDATE_RECOMMENDATIONS_2026-10-04.md` as the live record for this
tab.

---

## 4. The defects that were fixed, with their measurements

### Silently wrong answers

**R-1 — two supports at one station double-counted the reaction.** A station
is a node, and `reaction_at` is keyed by station, so two supports sharing one
both returned that node's residual while `_V_M_at` added it once per support.

```
6 m span, 10 kN/m (60 kN total), pin AND roller both at x = 0:
  reported reactions   30 + 30 + 30 = 90 kN   for 60 kN of load
  Max |M|              180 kN·m               against a true 45
  stress check         FAIL ratio 2.11         on a beam that passes
```

`pin` + `guided` at one station — how a user builds a fixed end without
reaching for `fixed` — gave M(0) = −90 against a true −45 and a moment diagram
that did not close at the free end. Constraint assembly was always right, so
the displacements were right and only the *recovery* was wrong, which is why no
closed-form test caught it. `add_support` now merges a second support at an
occupied station (union of restrained DOF, so pin + guided becomes a genuine
`fixed`), reports the merge, and `_V_M_at` iterates support **nodes**.

**R-2 — nothing checked that the answer balanced.** That is how R-1 survived a
green suite. `BeamResult.equilibrium()` now returns the force and moment
residuals, the diagram's closure beyond x = L, both scales, the restrained-DOF
count and the degree of indeterminacy. The applied-load leg is integrated from
the load definitions, independently of the solve. Residuals measure 1e-16 to
1e-13 of the applied load on every model in the suite.

**R-5 — a missing allowable printed `OK`.** `ratio = demand / allow if allow
else 0` turned a blank box into a pass. A check that cannot fail is worse than
no check; zero now reads `not checked`. Also: `L = 0` reported "fully
constrained", `E = 0` reported "a mechanism", and a **negative EI solved** and
returned every deflection with the sign flipped.

### Silent misbehaviour

**R-4 — q(x) loads bypassed the unit layer and the on-beam check.** The dialog
hard-coded "(m)" and stored raw, while the table converted for display: under
AISC it offered a default of `6.0` labelled "m" beside a table reading
`19.69 ft`, and someone typing `20` meaning feet got a 20-metre load. An
off-beam domain was silently clamped rather than refused.

**Found while fixing it:** `BeamApp._on_beam` compared stations to `[0, L]`
*exactly* while the model allows a tolerance. 6 m is 19.68503937007874 ft,
which converts back to 6.000000000000001 m, so **every** Add dialog refused a
load at the far end of the beam under AISC.

**R-6 — non-numeric input raised an unhandled `TclError` and said nothing.**
`_set_length` read `DoubleVar.get()` unguarded, so the exception escaped into
the Tk callback: the length did not change and nothing was said. In a
double-clicked app that traceback goes to a console nobody sees.

**R-7 — shortening the beam stranded entries** that were legal when entered.
Analyze then failed wholesale, naming whichever one it reached first, with
nothing marking the offending rows.

### Ambiguous reporting

**R-3 — the reaction-moment column meant two different things.** It was negated
at x = 0 only, a rule arrived at by trying three beams and keeping what matched
the diagram. What that produced was the internal moment at the support, not the
support's couple — and at an interior support, the internal moment on the *left*
side specifically, with nothing to say so. `support_reaction()` now returns the
couple (CCW positive) *and* the internal moment on each side, with no heuristic,
because `M == M_left − M_right` at every station.

> **A correction worth carrying forward:** the review originally claimed the
> interior support's couple was +30 kN·m where the tab showed −30. That was
> wrong. Taking moments about the support for the left-reaching cantilever, the
> tip load contributes +P·L/2 counter-clockwise, so the couple is −30 and the
> residual already held it. The displayed *number* was right; what was wrong
> was that the column meant different things at different stations. The review
> file carries this correction inline.

**R-16 — the panel omitted what a checker writes down:** where the maxima are,
both moment extremes separately, and any deflection limit.

**R-17 — the workbook** wrote `w1_kNm` for a kN/m line load, validated nothing
on import, and raised `IndexError` with no row number on a short row.

### Architecture

**R-8 — the solver lived in the same file as the widgets.** Not theoretical:
`pytest tests/test_beam_math.py` **could not be collected** on a Python without
Tk, to test code with no UI in it. Moving the code was not enough, because
`common.py` imports tkinter at module scope — so the shared numeric core moved
to root-level `numerics.py`, which imports only `math`, and `common.py`
re-exports it as the same objects.

> **Measured in passing, still open:** of the modules
> `MODULAR_ARCHITECTURE.md` describes as pure engines, only
> `perforated_beam_math.py` and `profile_sketcher_math.py` actually import
> without tkinter. **`truss_math.py` and `cable_web_math.py` do not** — they
> import `common`. Pointing them at `numerics` is a one-line change each.

**R-9 — two implementations of the unit layer.** `common.UnitsMixin` exists
*because* of this tab (its docstring says so), and it already had
`_shown`/`_stored`/`_u` with the same signatures the tab had grown by hand — so
none of the 85 call sites changed; only the duplicate machinery behind them
went. Four labels also spelled their unit out in SI and never repainted: under
AISC the panel said *POINT LOADS (+down, kN)* above a table of kip.

### Presentation

**R-13 — the diagram pane's labels collided**, 1 overlapping pair at 1500 px
and 4 at 700 px. Fixed with `common.fit_caption`, **which the Arch tab now
calls too** — two copies of one rule is exactly how Beam still had this bug a
month after Arch fixed it.

Two more defects the new tests caught: **every x-axis number was clipped at any
window size** (bands filled the pane to `h − 20`, labels drawn at `bot + 10`),
and **tick density ignored the width** (eight labels requested however narrow
the pane, so `9` and `10` overlapped at 340 px).

**R-14/R-15 — the tab could only be added to and looked at.** No row editing,
no undo (while four other tabs had one), an editable results box, no way to
read a value at a station, no way to get closer to a crowded region, and no way
out but a screenshot.

---

## 5. Decisions a successor should know about

1. **Merging duplicate supports, not refusing them.** A pin plus a guided
   support at one station *is* a fixed support, and that is what the user
   described. But the merge is reported in the panel and the workbook, because
   analysing something other than what was typed without saying so was the
   whole of R-1.
2. **A stored `q(x)` expression keeps its storage units** (kN/m, x in m) and
   the tab says so in the dialog, the heading and the schematic label. It
   cannot follow the selector: the string is stored verbatim, so if its meaning
   tracked the convention, switching would silently change the load — the one
   property `units.py` exists to prevent. This follows the Arch tab's wording.
3. **The section boxes are not in the undo.** They hold a value being typed,
   not a committed change, and rewriting a box under the cursor is worse than
   leaving it. Undo covers the five tables and the length.
4. **Zoom is on the x axis, not `common.ZoomCanvas`** — a deliberate deviation
   from the review's own suggestion. The diagrams are three stacked plots
   sharing one axis; uniform 2-D zoom would scale the band heights and the text
   along with the span, which is not what "look closer at the support" means.
   The schematic shares the window so the two are never of different pieces of
   beam. **If consistency with Truss/Stereo matters more, this is the one
   decision to revisit.**
5. **Export is PostScript.** It is what a Tk canvas produces unaided: vector,
   printable, convertible anywhere. A `.png` name is honoured when Pillow and
   Ghostscript are both present and says plainly what happened when they are
   not, rather than writing something broken.
6. **The deflection limit is dimensionless** (`L/n`, default 360), so it is
   deliberately not registered as a `unit_var`.

---

## 6. Running it, and the environment traps

```bash
cd "STRUCTURAL SYMULATOR SOLVER-5-9-26"
python main.py                       # the app; needs tkinter + numpy + scipy
python -m pytest tests/ -q           # 1452 tests
```

* **tkinter is required for the UI tests and for the app.** A Python built
  without it can still run the solver and `tests/test_beam_math.py`
  (87 passed, 1 skipped) — that is R-8's whole point — but everything that
  builds a widget will skip or fail.
* **A display is required** for the UI tests. Headless: `xvfb-run -a python -m
  pytest tests/ -q`. Without one they skip with "no display", which can make a
  broken UI look green — check the skip count.
* **`numpy` and `scipy` are mandatory**, not optional; `requirements.txt`
  explains why. `openpyxl` is needed for Excel.
* **Line endings are mixed per file in this repo** and there is no
  `.gitattributes`. `beam_app.py` is CRLF while the tests and the new modules
  are LF. Any tool that rewrites a whole file will flip its endings and produce
  a diff of the entire file — that happened twice in this session and had to be
  undone. **Adding a `.gitattributes` is the cheapest remaining housekeeping
  win.**

---

## 7. What is still open

From the review, in the order worth doing:

| # | item | why |
|---|---|---|
| **R-18** | Internal hinges, elastic springs, prescribed settlements | The most-asked-for next feature; a Gerber beam cannot be modelled at all today. |
| **R-19** | Variable EI (stepped / haunched) | `BeamModel.EI` is one scalar, so a deeper section over the supports is impossible. |
| **R-20** | Load cases and factored combinations | The tab checks loads **as entered**, so its utilisations are systematically unconservative against any report that applied 1.2D + 1.6L. `apps/perforated_beam/load_combinations.py` already implements this and should be promoted to a root module, as `cirsoc_301.py` was. |
| **R-21** | Section library and real code checks | `I`, `c`, `A` are typed by hand; `V/A` uses the gross area; there is no unbraced length, so no lateral-torsional buckling. The parts exist in `apps/perforated_beam/`. |
| **R-22** | The equation guide `requirements.txt` already promises | It claims matplotlib is for "the Truss/**Beam**/Arch guides"; only Truss has one. |

Housekeeping, none of it in the Beam tab:

* `truss_math.py` and `cable_web_math.py` still need Tk (one line each).
* No `.gitattributes` (see §6).
* Three zip archives and a stale `structural_simulator_v15_fixed15/` tree sit
  at the repository root with nothing saying which copy is live. Its
  `beam_app.py` is the 1220-line ancestor of this one and has none of these
  fixes.
* `arch_app.py` has its own dead imports (finding A-3) and stores its
  distributed-load stations raw — the same R-4 defect, with a label that
  actively promises feet.

---

## 8. Where to look in the code

```
STRUCTURAL SYMULATOR SOLVER-5-9-26/
  numerics.py                 NEW. The numeric core, imports only math:
                              _beam_gauss_solve, _require_numpy, the Gauss
                              nodes/weights, make_shape_fn. No tkinter, so a
                              solver can be imported and tested headlessly.
  common.py                   Shared widgets and helpers. Re-exports numerics.
                              NEW here: fit_caption, HoverTooltip.
  apps/beam/
    beam_math.py              NEW, 812 lines. BeamModel, BeamResult, the
                              adaptive quadrature. SI only. No tkinter,
                              no common, no units — pinned by a test.
    beam_reports.py           NEW, 365 lines. The Excel export and import.
    beam_app.py               1907 lines. The Tkinter half only. Re-exports
                              the four names above for anything that imported
                              them from here before the split.
  tests/
    test_beam_math.py                  52 tests  solver + the Tk-free boundary
    test_beam_equilibrium_report.py    22        equilibrium, extremes, R-3
    test_beam_input_validation.py      27        R-5, R-6, R-7
    test_beam_nonuniform_loads.py      19        R-4 and the end-station tolerance
    test_beam_diagram_labels.py         9 (×6 widths)  R-13
    test_beam_table_editing.py         22        R-14
    test_beam_diagram_interaction.py   26        R-15
    test_units_in_beam_tab.py          15        R-9
```

---

## 9. If you continue this work

* **Write the test first and watch it fail for the right reason.** Four of the
  defects in §4 were found that way, and three more were found by tests written
  for a *different* item — R-13's "no label leaves its canvas" test caught a
  label I pushed off the canvas three commits later.
* **When one of your own assertions fails, check which of you is wrong.** Five
  times in this session the test was wrong, not the code: Tk ignores inserts on
  a disabled `Text` rather than raising; it refuses to synthesise a `Double`
  modifier at all; the narrow-pane readout relocation is decided per band, not
  for all three; `ws.cell(..., value=None)` does not clear a cell; and the
  interior-support couple really is negative.
* **Measure, don't infer.** Every number in §4 came from a running widget or a
  solved model. The project's MANIFESTO §2 asks for this, and it is why the
  review's claims held up.
* **Share a rule rather than copying it.** `fit_caption` and `HoverTooltip` are
  in `common.py` and used by two tabs each, because the one-month-old
  divergence between Arch and Beam is what made R-13 necessary.
