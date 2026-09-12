# Truss tab — bugs still open, 2026-09-10

**Files:** `apps/truss/` — `truss_app.py` (249 KB), `truss_math.py` (50 KB),
`truss_reports.py` (50 KB), `truss_plates.py`, `truss_guides.py`
**Re-diagnosis of** `DIAGNOSIS_TRUSS_2026-09-05.md`. Suite green: 809 passed.

## Nothing remains open.

All four findings from 2026-09-05 are closed, and a fresh pass over the
substantially larger tab — it has grown from 167 KB to 249 KB, with two whole
new modules — found nothing new.

| finding | severity | status |
|---|---|---|
| T-1 panel controls vanish when narrow | MED | ✅ fixed |
| T-2 `_draw_diagrams_legacy_overview` dead code | LOW | ✅ fixed |
| T-3 dead imports | LOW | ✅ fixed |
| T-4 no math tests | LOW | ✅ fixed |

---

## What was verified

### T-1 · fixed

Controls **mapped** (reachable), measured fresh with no buttons invoked and
filtered to the root toplevel:

| window | 1600 | 1400 | 1200 | 1000 | 900 | 800 | 700 | 600 | 550 |
|---|---|---|---|---|---|---|---|---|---|
| mapped | 102 | 102 | 102 | 102 | 102 | 102 | 102 | 102 | 102 |
| overflowing | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Flat at 102 across the whole range, nothing off the edge. In September this
fell 48 → 14 with 22 controls overflowing by up to 202 px at 900 px. This is
the cleanest layout of the five tabs.

### T-2 · fixed

`grep -c _draw_diagrams_legacy_overview apps/truss/truss_app.py` → **0**. The
175-line unreachable method with its own duplicate copy of the diagram layout
logic is gone.

### T-3 · fixed

`pyflakes` on `truss_app.py`, `truss_math.py`, `truss_reports.py`,
`truss_plates.py` and `truss_guides.py` reports **zero findings** — no unused
imports, no dead locals, no shadowed names. The only tab in the project of
which that is true.

### T-4 · fixed

`tests/test_truss_math.py` now exists (11 tests), including
`test_rigid_rod_cantilever_matches_the_beam_solver`, which is the
cross-solver check recommended in the September report. Truss test coverage
across all files is now ~171 tests (`test_truss_editing` 40,
`test_truss_guides` 48, `test_truss_plates` 26, `test_truss_plates_app` 13,
`test_truss_math` 11, `test_truss_layout` 3, `test_truss_load_signs` 1, plus
the truss cases inside `test_excel_roundtrip`).

### Physics — re-validated from scratch

`truss_math.py` grew from 31 KB to 50 KB, so the solver was re-checked
independently rather than assumed:

| case | quantity | agreement |
|---|---|---|
| Triangle truss, apex load | R = P/2; diagonal = −(P/2)/sin θ; chord = (P/2)/tan θ | ≤2.3e-16 |
| Built-in Warren example | R₀ = R₄ = −60 kN by symmetry | 4.7e-16 |
| Built-in Warren example | **method-of-joints residual at every free node** | 1.1e-13 |
| Single `rigid` rod as cantilever | tip δ and fixed-end M vs `BeamModel` | 2.8e-4 |
| Single `rigid` rod with UDL | R = wL/2 each end | exact |

Zero failures.

### Runtime

Both examples load and analyse cleanly (Warren 0.23 s, Vierendeel 0.16 s), the
canvas paints 1 922 and 2 125 items, **40 buttons invoked and none raised**, no
dialogs, no slow paths. Excel round-trip clean, including the September-era
`conn='rigid'`, `I`, `udl` and `udl_rotation_deg` per-rod keys, and the new
model-only export path.

---

## Caveats on this verdict

Two limits on how far the "nothing open" claim goes, stated plainly:

1. **The new surfaces were checked for crashes and coverage, not audited for
   correctness.** `truss_plates.py` (gusset/shear-panel plates, block shear,
   Whitmore buckling) and `truss_guides.py` (guide curves, conic fitting,
   arrays) carry 87 tests of their own and none of their buttons raise, but I
   did not re-derive their engineering results against independent closed
   forms the way I did for the core solver. If you want that, it is a separate
   piece of work and worth asking for explicitly.

2. **`OPEN_ITEMS_CLOSED_2026-09-07.md` §2 flags its own provenance caveat**,
   and it still stands: the block-shear and gusset-buckling **factors** were
   taken from AISC 360 rather than transcribed from CIRSOC 301, unlike every
   other factor in the app. `PHI_WELD` is the precedent — CIRSOC uses 0.60
   where AISC uses 0.75 for the same limit state, a 25 % difference. That is
   not a bug I found; it is a known, documented, and deliberately-surfaced
   gap, and it is the one thing in this tab I would not ship to a real design
   office without checking the document.
