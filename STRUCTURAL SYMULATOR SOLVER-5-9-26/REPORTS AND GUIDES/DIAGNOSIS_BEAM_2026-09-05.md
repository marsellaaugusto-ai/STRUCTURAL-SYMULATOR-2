# Beam tab — diagnostic report, 2026-09-05

**File:** `apps/beam/beam_app.py` (1 222 lines: `BeamModel`, `BeamResult`, `BeamApp`)
**Build:** STRUCTURAL SYMULATOR SOLVER-5-9-26 (from `Downloads/STRUCTURAL SYMULATOR SOLVER59265`)
**Method:** MANIFESTO §2 — real Tk widgets, real canvas, live measurement, plus
closed-form validation of the solver. Every number below was measured, not read
off the source.
**Baseline:** existing suite 157 passed in 224 s before any change.

---

## 0. Summary

| | |
|---|---|
| Solver physics | **correct** — 10 independent closed-form cases, worst error 3.7e-4 |
| Blocking bugs | **2 HIGH** (one solver, one UI) |
| Silent-wrong-answer bugs | **2 MEDIUM** |
| Drawing bugs | **1 MEDIUM** |
| Automated tests for this tab | **0** |

The solver is the strongest part of this tab. Everything wrong with Beam is
around it: one meshing edge case, one layout failure that hides the Analyze
button, and input handling that accepts nonsense silently.

### What was verified as CORRECT (do not "fix" these)

Closed-form checks, all passing (`EI` = 200 GPa × 8 000 cm⁴ = 16.0 MN·m²):

| case | quantity | agreement |
|---|---|---|
| SS + full UDL | R, M_mid = wL²/8, δ = 5wL⁴/384EI | 2.2e-4 |
| SS + central P | R, M = PL/4, δ = PL³/48EI | 2.8e-4 |
| Cantilever + tip P | R, M = −PL, δ = PL³/3EI, θ = PL²/2EI | 2.8e-4 |
| Cantilever + UDL | M = −wL²/2, δ = wL⁴/8EI | 3.7e-4 |
| Propped cantilever | R_roller = 3wL/8, M_fix = −wL²/8 | 1.1e-3 |
| SS + end moment | R = ∓M₀/L, M(0⁺) = −M₀ | 1.7e-6 |
| 2-span continuous | R_mid = 1.25wL, M_sup = −wL²/8 | exact |
| SS + triangular | R = W/3, 2W/3; M_max; δ = 0.00652wL⁴/EI | 9.3e-5 |
| Guided support | M_fix = −wL²/3, M_guided = +wL²/6 | 1e-15 |
| Non-uniform q = w·sin(πx/L) | R = wL/π, M = wL²/π², δ = wL⁴/π⁴EI | 2.3e-4 |
| Mixed asymmetric | ΣR = ΣP, ΣM about x=0 | 1.1e-12 |

Also verified clean: **Excel export → import round-trip** on all three built-in
examples (7 state keys, zero differences); non-numeric text typed into a numeric
field is caught and reported through a dialog.

The sign convention on `add_moment` is self-consistent and correct (a +CCW
moment M₀ at the left end of a simply-supported beam gives R_left = +M₀/L and
M(0⁺) = −M₀). It reads "backwards" against a naive expectation — it is not.

---

## 1. Findings

### B-1 · HIGH · A fixed–fixed beam with no interior load point cannot be solved

The single most common statically-indeterminate textbook case fails outright.

**Reproduce:**

```python
from apps.beam.beam_app import BeamModel
m = BeamModel(6.0); m.EI = 200e9 * 8000e-8
m.add_support(0, 'fixed'); m.add_support(6.0, 'fixed')
m.add_dload(0, 6.0, 10e3, 10e3)
m.solve()      # ValueError: Beam is fully constrained; nothing to solve
```

**Measured:** the same beam solves correctly the moment *any* interior node
exists — split the UDL into 0–3 and 3–6, or add a midspan point load, and you
get M_end = −30.0 kN·m (= −wL²/12 ✔), M_mid = +15.0 kN·m (= +wL²/24 ✔),
δ_mid = −2.107 mm (exact −2.109 mm ✔). **The physics is right; only the mesh
is wrong.**

**Root cause:** `BeamModel._node_positions()` (`beam_app.py:45`) puts nodes only
at supports, loads and load-segment ends. A fixed–fixed beam with a full-span
UDL yields exactly 2 nodes → 4 DOF → both fixed supports constrain all 4 → the
`if not free:` guard at `beam_app.py:148` fires.

The error message is also actively misleading: the beam is neither
over-constrained nor a mechanism. It is a perfectly ordinary beam with too
coarse a mesh.

**How to fix:** guarantee a minimum element count independent of the load
layout. In `_node_positions()`, after collecting the discontinuity stations,
subdivide each resulting interval so that no element is longer than, say,
`L / 8` — or, minimally, insert a midpoint whenever `len(xs) == 2`. A cubic
Hermite element with a consistent load vector is nodally exact for these load
types, so extra nodes cost accuracy nothing and cost a trivial amount of time.

**Verify:** M_end → −wL²/12, M_mid → +wL²/24, δ_mid → wL⁴/384EI on the case
above, and confirm the 10 closed-form cases in §0 are unchanged.

**Effort:** ~30 min. **Risk:** low — meshing only, no change to element or
recovery maths. Add the fixed–fixed case to the suite at the same time.

---

### B-2 · HIGH · The ▶ Analyze button disappears below ~1300 px window width

**Measured, with a screenshot for confirmation.** The toolbar is a single
non-wrapping `pack` row whose required width is **1 306 px**. ▶ Analyze sits at
x = 1 215 with width 95, so it needs a 1 310 px window. Below that Tk does not
clip it — it **unmaps** it entirely.

| window width | ▶ Analyze `winfo_ismapped()` |
|---|---|
| 1 600 px | 1 (visible) |
| 1 300 px | 1 (visible) |
| **1 200 px** | **0 — gone** |
| 1 100 / 1 000 / 900 px | 0 — gone |

The 1 200 px screenshot shows the toolbar ending at "Import Excel", itself
clipped at the right edge. There is no scrollbar and no overflow menu, so at
1 200 px **the tab's primary action is unreachable** — the user has to widen
the window to discover it exists.

More controls go the same way as the window narrows. Of 27 measured controls in
the tab: 27 mapped at 1 600 px, 23 at 900 px (7 of them overflowing, worst
+233 px), and only **5 at 600 px**. Buttons lost by 900 px: Clear, Export
Excel, Import Excel, ▶ Analyze.

**Root cause:** fixed-width toolbar packed left-to-right with no wrapping,
no minimum-size handling, and no scroll container. The Cable Web tab already
solves this with `_update_responsive_sidebars()` bound to `<Configure>`.

**How to fix:** either (a) put the toolbar in a horizontally scrollable frame,
or (b) bind `<Configure>` and re-flow the toolbar into two rows below a
threshold width, or (c) — cheapest and most robust — move ▶ Analyze out of the
overflow-prone end of the toolbar and anchor it with `side='right'` so it is
packed *first* and therefore never the control that gets dropped.

**Verify:** re-run the width sweep and assert ▶ Analyze reports
`winfo_ismapped() == 1` at 1 600 → 800 px.

**Effort:** ~1 h for (c), ~3 h for (a)/(b). **Risk:** low, layout only.

---

### B-3 · MEDIUM · Distributed-load arrows are drawn at a constant length

Every load arrow in the schematic is exactly **30 px tall regardless of load
magnitude or shape**. Measured on the real canvas:

| load | arrows | min length | max length | ratio |
|---|---|---|---|---|
| trapezoid w₁=0 → w₂=60 kN/m | 54 | 30.0 px | 30.0 px | 1.00 |
| non-uniform q(x) = 10x (0→60 kN/m) | 11 | 30.0 px | 30.0 px | 1.00 |

A triangular load is therefore drawn identically to a uniform one — the picture
says "uniform" while the text label says "0.0→60.0 kN/m". The load diagram is
the main visual check an engineer makes before hitting Analyze, and it cannot
currently show a load shape at all.

**Root cause:** `beam_app.py:1118-1128` (trapezoid) draws each arrow from a
fixed `top = y0 - 30` to the beam line. In the non-uniform branch,
`beam_app.py:1133` computes `qfn = make_shape_fn(...)` and then **never uses
it** — the intended magnitude scaling was never wired up (pyflakes flags `qfn`
as assigned-but-unused).

**How to fix:** scale each arrow's length by its own intensity. Compute
`q_max` over all distributed loads in the model, then draw each arrow from
`y0 - 30 * q(x)/q_max` (with a small floor so a near-zero ordinate stays
visible), and draw the top chord as the polyline through those arrow tops
rather than a straight line. The non-uniform branch already has `qfn` in hand.

**Verify:** re-measure arrow lengths for w₁=0 → w₂=60; expect a monotonic ramp
with max/min ≈ the load ratio, and the same for q(x) = 10x.

**Effort:** ~1 h. **Risk:** low, drawing only — no solver contact.

---

### B-4 · MEDIUM · A distributed load entered right-to-left is silently ignored

If the user types x1 = 5, x2 = 1 (a very ordinary typo, and the dialog offers
no hint that order matters), the load contributes **nothing at all** and the
analysis reports a beam under no load, with no warning.

```
normal   x1=1, x2=5   ->  RA = 20.0 kN   RB = 20.0 kN   M_mid = 40.0 kN·m
reversed x1=5, x2=1   ->  RA =  0.0 kN   RB =  0.0 kN   M_mid =  0.0 kN·m
```

**Root cause:** `BeamModel.q()` (`beam_app.py:65`) tests
`d['x1'] - 1e-9 <= x <= d['x2'] + 1e-9`, which is unsatisfiable when x1 > x2,
so the segment never contributes. The `has_load` element test at
`beam_app.py:112` likewise never fires.

Note the inconsistency: `BeamApp._analyze` *does* normalise the non-uniform
loads (`if x2 < x1: x1, x2 = x2, x1`, `beam_app.py:1021`) but not the
trapezoidal ones.

**How to fix:** normalise in `add_dload()` — `if x2 < x1: x1, x2, w1, w2 = x2,
x1, w2, w1` (swap the intensities with the coordinates, or the ramp direction
flips). Alternatively validate in `_add_dload` and refuse with a dialog. Do
both if you want the user to learn the convention.

**Effort:** ~20 min. **Risk:** low.

---

### B-5 · MEDIUM · Coordinates beyond the beam length silently extend the mesh

Nothing validates load or support coordinates against the beam's own length.
A support or load at x = 99 on a 6 m beam is accepted, and the analysed beam
silently becomes 99 m long while `model.L` stays 6.0:

```
supports at 0 and 99 on an L=6 beam -> node positions [0.0, 6.0, 99.0]
point load at x=99 on an L=6 beam   -> RA = -155 kN, RB = +165 kN  (for a 10 kN load)
```

The reactions are enormous and meaningless, but nothing says so — the user sees
a plausible-looking diagram of a structure they did not describe.

**Root cause:** `_node_positions()` unions every coordinate it is given without
reference to `self.L`; `BeamApp._add_support` / `_add_pointload` /
`_add_moment` / `_add_dload` (`beam_app.py:827-843`) append the raw dialog
result with no range check at all.

**How to fix:** validate on entry — reject (or clamp, with a status-bar
message) any x outside `[0, L]` in the four `_add_*` handlers, and add a
defensive check in `BeamModel.solve()` so the model layer is safe when driven
directly or from an imported workbook. Changing the beam length afterwards
should re-validate the existing entries.

**Effort:** ~1 h. **Risk:** low. Decide deliberately whether shortening the
beam should delete now-invalid entries or just flag them.

---

### B-6 · LOW · Dead imports

`os`, `sys`, `subprocess` (`beam_app.py:10`) and `INIT_CW`, `INIT_CH`, `INIT_DH`
from `common` (`beam_app.py:12`) are imported and never used. Harmless; clean
up when you are next in the file's header for another reason.

---

### B-7 · LOW · No automated tests for this tab

1 222 lines, zero test files. Every finding above was found by driving the tab
from a throwaway script; none of them would be caught by the existing suite.
The closed-form table in §0 is ready-made as a test module — porting it is
roughly an hour and would have caught B-1 immediately.

---

## 2. Suggested order

1. **B-1** — solver correctness, smallest fix, add the regression test with it.
2. **B-2** — the tab is unusable at common window sizes.
3. **B-4** and **B-5** together — both are input validation in the same four
   handlers, one change.
4. **B-3** — visible improvement, no risk.
5. **B-7** — port §0 into `tests/test_beam_math.py` once B-1 is in.
6. **B-6** — opportunistically.
