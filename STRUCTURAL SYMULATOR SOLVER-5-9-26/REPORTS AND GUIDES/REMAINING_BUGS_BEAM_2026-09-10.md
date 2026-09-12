# Beam tab — bugs still open, 2026-09-10

**File:** `apps/beam/beam_app.py` (1 254 lines)
**Re-diagnosis of** `DIAGNOSIS_BEAM_2026-09-05.md`. Suite green: 809 passed.

| finding | severity | status |
|---|---|---|
| B-1 fixed–fixed beam will not solve | **HIGH** | ❌ open |
| B-2 ▶ Analyze unmapped below 1300 px | HIGH | ✅ fixed |
| B-3 load arrows drawn at constant length | MED | ❌ open |
| B-4 reversed distributed load silently ignored | MED | ❌ open |
| B-5 coordinates beyond L silently extend the mesh | MED | ❌ open |
| B-6 dead imports | LOW | ❌ open |
| B-7 no physics tests | LOW | ❌ open |
| B-8 diagram caption collides with its own labels | LOW | ❌ new |

**The solver itself is still correct** — re-validated against SS+UDL,
cantilever tip deflection, propped cantilever and 2-span continuous, worst
error 2.8e-4. Excel round-trip still clean. All 18 buttons invoke without
raising. Nothing that was right has regressed.

---

## B-2 · FIXED — confirmed by screenshot

The toolbar now wraps to two rows (`WrapBar` in `common.py`). At 900 px the
▶ Analyze button is visible and every one of 27 controls is mapped; at 550 px,
26 of 27. On 2026-09-05 this fell to 5 of 27 and ▶ Analyze was unreachable
below 1300 px. Done.

---

## B-1 · HIGH · Fixed–fixed beam with no interior load point still will not solve

Unchanged since 2026-09-05. Still the highest-value open bug in the project.

```python
from apps.beam.beam_app import BeamModel
m = BeamModel(6.0); m.EI = 200e9 * 8000e-8
m.add_support(0, 'fixed'); m.add_support(6.0, 'fixed')
m.add_dload(0, 6.0, 10e3, 10e3)
m.solve()      # ValueError: Beam is fully constrained; nothing to solve
```

**The physics is already right.** Split the same UDL into 0–3 and 3–6 so an
interior node exists, and you get M_end = −30.0 kN·m (= −wL²/12 ✔),
M_mid = +15.0 kN·m (= +wL²/24 ✔), δ_mid = −2.107 mm (exact −2.109 ✔). Only
the mesh is wrong.

**Root cause:** `_node_positions()` (`beam_app.py:46`) places nodes only at
supports, loads and load-segment ends. Fixed–fixed + full-span UDL → 2 nodes →
4 DOF → both supports constrain all 4 → the `if not free:` guard at
`beam_app.py:149` fires. The message is misleading too: the beam is neither
over-constrained nor a mechanism.

**Fix:** guarantee a minimum element count independent of the load layout —
subdivide each interval so no element exceeds `L/8`, or minimally insert a
midpoint when `len(xs) == 2`. Cubic-Hermite elements with consistent load
vectors are nodally exact for these load types, so extra nodes cost nothing.

**Verify:** M_end → −wL²/12, M_mid → +wL²/24, δ_mid → wL⁴/384EI, and the four
closed forms above unchanged. **Effort ~30 min. Risk low.**

---

## B-3 · MEDIUM · Distributed-load arrows are still a constant 30 px

Re-measured on the live canvas today:

| load | arrows | min | max | ratio |
|---|---|---|---|---|
| UDL w = 20 kN/m (control) | 43 | 30.0 px | 30.0 px | 1.00 |
| triangular w₁ = 0 → w₂ = 60 kN/m | 43 | 30.0 px | 30.0 px | 1.00 |
| non-uniform q(x) = 10x (0 → 60) | 11 | 30.0 px | 30.0 px | 1.00 |

A triangular load is drawn identically to a uniform one. The load picture is
the check an engineer makes before pressing Analyze, and it still cannot show
a load shape.

`beam_app.py:1152` still computes `qfn = make_shape_fn(...)` and never uses it
— pyflakes still flags it as assigned-but-unused, which is the same smoking
gun as in September.

**Fix:** take `q_max` across all distributed loads, draw each arrow from
`y0 - 30 * q(x)/q_max` with a small floor, and draw the top chord as the
polyline through the arrow tops. The non-uniform branch already holds `qfn`.
**Effort ~1 h. Risk low — drawing only.**

---

## B-4 · MEDIUM · A distributed load entered right-to-left is still silently ignored

```
normal   x1=1, x2=5  ->  RA = 20.0 kN  RB = 20.0 kN  M_mid = 40.0 kN·m
reversed x1=5, x2=1  ->  RA =  0.0 kN  RB =  0.0 kN  M_mid =  0.0 kN·m
```

`BeamModel.q()` tests `d['x1'] - 1e-9 <= x <= d['x2'] + 1e-9`, unsatisfiable
when x1 > x2, so the load never contributes and nothing warns.

Note the Perforated Beam tab **fixed exactly this** in the same period (P-3 —
reversed input now normalises), and `BeamApp._analyze` already normalises the
*non-uniform* loads (`if x2 < x1: x1, x2 = x2, x1`) while leaving the
trapezoidal ones alone. The tab is inconsistent with itself and with its
sibling.

**Fix:** normalise in `add_dload()` — swap `w1/w2` together with `x1/x2`, or
the ramp direction flips. **Effort ~20 min.**

---

## B-5 · MEDIUM · Coordinates beyond the beam length still silently extend the mesh

```
support at x=99 on an L=6 beam  ->  node positions [0.0, 6.0, 99.0]
point load at x=99 on L=6       ->  RA = -155 kN, RB = +165 kN  (for a 10 kN load)
```

`model.L` stays 6.0 while the analysed mesh runs to 99 m. The reactions are
enormous and meaningless, and the user sees a plausible-looking diagram of a
structure they did not describe.

The four `_add_*` handlers (`beam_app.py:840-856`) still append the raw dialog
result with **no validation whatsoever** — re-read today, unchanged.

**Fix:** reject or clamp any x outside `[0, L]` in the four handlers, plus a
defensive check in `BeamModel.solve()` for when the model is driven directly or
from an imported workbook. Decide deliberately what shortening the beam should
do to entries that become invalid. **Effort ~1 h.**

*(Arch has the same class of hole — A-6/A-7. Worth one pass across both.)*

---

## B-8 · LOW · NEW · The moment-diagram caption collides with its own labels

Measured on the real canvas — overlapping text bounding boxes in
`diag_canvas`:

| window | canvas | collisions |
|---|---|---|
| 1500 px | 938 px | 0 |
| 1200 px | 642 px | 1 — caption × `x=4.88` (30 px) |
| 900 px | 477 px | 2 — caption × `max ±14.96` (18 px), × `x=4.88` |
| 700 px | 367 px | 2 — caption × `max ±14.96` (58 px), × `x=4.88` |

The caption is *"MOMENT M (kN·m) — sagging (+) plotted UP, hogging (−) plotted
DOWN"*; from 1200 px down it runs into the right-hand `max ±…` readout and the
peak annotation. Visible in the 900 px screenshot taken for B-2.

**Fix:** shorten or elide the caption when the canvas is narrow (measure with
`font.measure()` and drop the explanatory half), or move `max ±…` to a second
line. Beam is the mildest case of this; see **A-5** for the Arch version,
which is much worse. **Effort ~1 h for all three tabs together.**

---

## B-6 · LOW · Dead imports

`os`, `sys`, `subprocess` and three unused `common` names — 6 unused imports,
unchanged. Cosmetic.

## B-7 · LOW · Still no physics tests for this tab

`tests/` now holds 30 files and 809 tests, but Beam appears only in
`test_excel_roundtrip.py` (round-trip) and `test_tab_layouts.py` (layout).
`test_truss_math.py` constructs a `BeamModel` as a *reference* for the truss
cross-check — incidental, not coverage.

Nothing in the suite asserts a beam closed form, which is precisely why **B-1
has now survived two diagnoses with a green suite**. The verified table in
`DIAGNOSIS_BEAM_2026-09-05.md` §0 ports directly into
`tests/test_beam_math.py`. **~1 h, and it should land with the B-1 fix.**
