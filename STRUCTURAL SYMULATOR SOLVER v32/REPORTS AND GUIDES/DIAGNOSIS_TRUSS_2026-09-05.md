# Truss tab — diagnostic report, 2026-09-05

**Files:** `apps/truss/truss_app.py` (3 199 lines, `TrussApp`, 61 methods),
`truss_math.py` (681), `truss_reports.py` (1 000+)
**Build:** STRUCTURAL SYMULATOR SOLVER-5-9-26
**Method:** MANIFESTO §2 — closed-form statics, method-of-joints residuals, a
cross-check of the frame element against the independently-written Beam solver,
and live widget measurement.
**Baseline:** existing suite 157 passed in 224 s. Only one of those tests
(`test_truss_load_signs.py`) touches this tab, and it covers `truss_math` load
signs only.

---

## 0. Summary

| | |
|---|---|
| Pin-truss solver | **correct** — joint residuals ~1e-13 |
| Rigid-frame (Vierendeel) element | **correct** — matches the Beam solver |
| Correctness bugs found | **none** |
| Layout | **1 MEDIUM** — panel controls vanish below 1 000 px |
| Dead code | **1 LOW** — a 175-line unreachable method |
| Tests for the 3 199-line UI | **0** |

This is the most solid tab in the project on physics. Nothing in the solver
produced a wrong number under any test applied. The findings are a layout
failure and housekeeping.

### What was verified as CORRECT (do not "fix" these)

| case | quantity | agreement |
|---|---|---|
| Triangle truss, apex load P | R = P/2; diagonal = −(P/2)/sin θ; chord = (P/2)/tan θ | ≤2.3e-16 |
| Triangle truss | ΣFx, ΣFy, ΣM | ≤1.9e-16 |
| Built-in Warren example | R₀ = R₄ = −60 kN by symmetry | ≤4.7e-16 |
| Warren example | ΣFx, ΣFy, ΣM | ≤2.7e-16 |
| Warren example | **method-of-joints residual at every free node** | ≤1.1e-13 |
| Single `rigid` rod as cantilever | tip δ, fixed-end M, reaction — vs `BeamModel` | 2.8e-4 |
| Single `rigid` rod with UDL | R = wL/2 each end; V at end a = wL/2 | exact |

The cross-check in the last two rows is the strongest evidence here: the
truss tab's 6-DOF frame element and the beam tab's Hermite element were written
separately and agree to within the beam's own integration tolerance.

Also verified clean: **Excel export → import round-trip** preserves nodes,
loads, supports, profiles and — importantly — per-rod `conn='rigid'`, `I`,
`udl` and `udl_rotation_deg`. The only differences on re-import are absent
optional keys materialising as their defaults (`conn='pin'`, `udl=0.0`,
`point_loads=[]`), which is semantically identical.

---

## 1. Findings

### T-1 · MEDIUM · Panel controls overflow, then vanish, as the window narrows

The tab has 62 measurable controls. As the window narrows they first overflow
the right edge, then Tk stops mapping them altogether — there is no scrollbar
and no re-flow, so they become simply unreachable.

| window width | mapped | overflowing | worst overflow |
|---|---|---|---|
| 1 600 px | 48 | 0 | — |
| 1 200 px | 46 | 0 | — |
| 1 000 px | 42 | **18** | +102 px |
| 900 px | 41 | **22** | +202 px |
| 800 px | **17** | 0 | — (the panel is gone, not fixed) |
| 700 px and below | **14** | 0 | — |

The "0 overflowing" at 800 px and below is not an improvement — it is the
right-hand panel disappearing entirely. Controls overflowing at 900 px include
▶ Analyze structure (+202 px), Set Pinned, Rotated, Clear UDL, Apply UDL, Add
point load, Apply to selected, Clear point loads.

Buttons that become unreachable by 900 px include Export Excel, Import Excel,
Manage profiles…, and Pick ref.

**Root cause:** fixed-width right-hand panel with no `<Configure>` handling.
Cable Web solves the identical problem with `_update_responsive_sidebars()`
bound to `<Configure>`, choosing a panel width from a small table of
breakpoints rather than scaling continuously.

**How to fix:** put the right-hand panel inside a vertically *and*
horizontally scrollable container (the tab already builds a `panel_canvas`
scroll host at `truss_app.py:693`-equivalent in the beam tab — the same idiom
applies), or mirror `_update_responsive_sidebars`. Whichever is chosen should
be applied to Beam, Arch and Cable in the same change; all four tabs share this
layout idiom and all four fail the same way.

**Verify:** re-run the width sweep and assert that the number of *mapped*
controls does not fall as the window narrows, and that none overflow.

**Effort:** ~2 h for all four tabs together. **Risk:** low, layout only.

---

### T-2 · LOW · `_draw_diagrams_legacy_overview` is unreachable dead code

`truss_app.py:2425` defines a ~175-line method (running to roughly line 2599)
that nothing ever calls. `grep` finds exactly one occurrence of the name in the
file: its own `def`. The live path is `_draw_diagrams_only`, called from nine
sites.

It is not harmless in the way dead code usually is: it contains its own copy of
the diagram scaling and layout logic, so anyone reading the file to understand
how diagrams are drawn has a 50/50 chance of reading the wrong one — and any
future fix applied to it would appear to do nothing.

Its own dead locals (`DW`, `DH` at `:2434-2435`, `span_w` at `:2451`) are
pyflakes' only complaints in that region, which is itself a hint that the method
stopped being maintained.

**How to fix:** delete it. If it is being kept as a reference implementation,
move it to `REPORTS AND GUIDES/` as a code excerpt, or leave a one-line comment
at `_draw_diagrams_only` saying where the previous version went and why.

**Effort:** ~15 min. **Risk:** low — confirm with a fresh `grep -c` after
deleting, then run the tab's examples.

---

### T-3 · LOW · Dead imports and locals

`truss_app.py`: `sys`, `subprocess` (`:14`); `_nice_ticks`,
`_find_diagram_maxima`, `make_shape_fn` from `common` (`:16`);
`compute_node_force_vectors`, `udl_local_components`, `compute_node_moments`
from `truss_math` (`:70`) — note these three *are* used indirectly via
`analyze()`, they are just not referenced in this module;
`pil_draw_node_fbd`, `pil_draw_rod_context` from `truss_reports` (`:74`);
local `panel_win` (`:238`).

`truss_reports.py`: `os`, `sys`, `subprocess` (`:2`); seven names from `common`
(`:3`); `os` redefined at `:10` shadowing the `:2` import; `openpyxl` imported
unused at `:130`.

All cosmetic. The `os` redefinition at `truss_reports.py:10` is the only one
worth a second look, since a shadowed import occasionally signals a merge
artefact.

---

### T-4 · LOW · No tests for the 3 199-line UI

`test_truss_load_signs.py` covers `truss_math` load signs (1 861 bytes). The
solver is in good shape and would be cheap to pin: the closed-form table in §0,
including the method-of-joints residual check and the cross-check against
`BeamModel`, is directly portable into `tests/test_truss_math.py`.

The joint-residual check is worth calling out as a test pattern — it needs no
reference values at all, just the model itself, so it applies to any truss a
future change might break.

---

## 2. Suggested order

1. **T-1** — bundle with the Beam / Arch / Cable layout fix; this is the only
   finding here a user would actually hit.
2. **T-2** — delete the dead method before someone edits it by mistake.
3. **T-4** — port §0 into a test module.
4. **T-3** — opportunistically.
