# Arch tab — diagnostic report, 2026-09-05

**File:** `apps/arch/arch_app.py` (1 671 lines: `ArchModel`, `ArchResult`,
`ArchApp`)
**Build:** STRUCTURAL SYMULATOR SOLVER-5-9-26
**Method:** MANIFESTO §2 — closed-form validation against the exact
three-hinged-arch solutions, mesh- and stiffness-convergence studies, and live
widget measurement.
**Baseline:** existing suite 157 passed in 224 s. None of them touch this tab.

---

## 0. Summary

| | |
|---|---|
| Solver physics | **correct to machine precision** — the best in the project |
| Correctness bugs found | **none** |
| Layout | **1 MEDIUM** — controls overflow from 1 400 px, then vanish |
| Automated tests for this tab | **0** |

The arch solver is exceptional. Its docstring claims validation against
H = wL²/(8f) for a three-hinged parabolic arch and against classic beam
formulas; that claim was re-tested independently here and holds at the 1e-14
level. Nothing in this tab produced a wrong number under any test applied.

### What was verified as CORRECT (do not "fix" these)

20 m span, 4 m rise, parabolic centreline, 60 elements unless noted:

| case | quantity | agreement |
|---|---|---|
| Three-hinged, full UDL | H = wL²/(8f) | 2.5e-14 |
| Three-hinged, full UDL | R_y = wL/2 both springings; ΣFx, ΣFy | ≤1.0e-14 |
| Three-hinged, full UDL | **max \|M\| along the arch ≈ 0** (funicular) | 1.3e-8 N·m vs wL²/8 = 5e5 |
| Three-hinged, crown point load | H = PL/(4f); R_y = P/2 | ≤3.6e-12 |
| Three-hinged | **M = 0 exactly at the crown hinge** | 1.3e-8 N·m |
| Self-weight `w_weight` | H = wL²/(8f); ΣFy | ≤2.4e-14 |
| Wind `w_wind` | ΣFx + applied = 0; ΣFy = 0 | ≤1.1e-12 |
| Distributed load, `direction='horizontal'` | ΣFx + applied = 0 | 1.0e-12 |
| Two-hinged, point load at L/4 | ΣFx, ΣFy, ΣM about springing A | ≤2.1e-12 |
| Fixed–fixed, full UDL | ΣFx, ΣFy | ≤7.3e-15 |

Two convergence studies confirm the discretisation is sound rather than
accidentally right:

- **Mesh:** H is exact to 5.8e-16 at n_elem = 10 and stays exact through
  n_elem = 240 — the parabolic arch under UDL is captured by the straight-element
  chain at any resolution, as it should be.
- **Axial stiffness:** for the *two*-hinged arch, H → wL²/(8f) as EA → ∞
  (ratio 0.99877 at A = 0.01 m², 0.99999 at A = 1 m², 1.00000 at A = 100 m²).
  This is the elastic-shortening effect appearing at exactly the right
  magnitude and in the right direction.

The fixed–fixed case shows springing moments of ±2 160 N·m against wL²/8 =
500 000 N·m — 0.43 %. That is **not** a bug: a fixed-ended parabolic arch under
UDL is not perfectly funicular once axial shortening is included, and 0.43 %
is consistent with the A = 0.01 m² row of the stiffness study above.

Also verified clean: **Excel export → import round-trip** on all three built-in
examples (11 state keys, zero differences), including `shape_expr`, `arch_type`,
`hinge_x` and `n_elem`. The `n_elem` value is clamped by
`arch_app.py:1153` (`max(4, ...)`) so an imported or typed 0 cannot reach the
model. The `Circular` and `Catenary-like` shape presets were checked
algebraically and both pass through (0,0), (L/2, rise) and (L,0) correctly.

---

## 1. Findings

### A-1 · MEDIUM · Controls overflow from 1 400 px, and half of them are gone by 1 200 px

This tab starts losing controls **earlier than any other** — the results `Text`
pane overflows at 1 600 px, and 12 controls overflow at 1 400 px.

Measured across the tab's 41 controls:

| window width | mapped | overflowing | worst overflow |
|---|---|---|---|
| 1 600 px | 41 | 1 | +7 px |
| 1 400 px | 41 | **12** | **+207 px** |
| 1 200 px | **22** | 0 | — (panel collapsed, not fixed) |
| 900 px | 15 | 0 | — |
| 550 px | **8** | 0 | — |

As with the other tabs, "0 overflowing" below 1 200 px means the controls have
been unmapped rather than laid out — Tk drops what does not fit instead of
clipping or scrolling it.

Named buttons that become unreachable: **1 200 px** — Add, Delete. **900 px** —
also Export Excel, Import Excel, ▶ Analyze. **700 px** — also Clear, Example:
fixed. **550 px** — 8 of the 11 named buttons.

So from 900 px down, this tab cannot run an analysis at all.

**Root cause:** a fixed-width right-hand panel plus a fixed-width results `Text`
widget, neither responding to `<Configure>`. The `Text` pane is the first thing
to overflow and is the reason this tab fails earlier than Beam or Cable.

**How to fix:** the same change as Beam (B-2), Cable (C-2) and Truss (T-1) —
these four tabs share one layout idiom and one failure mode, and should be
fixed in one pass. For this tab specifically, also give the results `Text` a
`width` that is recomputed on `<Configure>` (or let it shrink via
`pack(fill='both', expand=True)` with a small `width=` floor), since it alone
accounts for the 1 400 px overflow.

**Verify:** re-run the width sweep and assert the mapped-control count never
decreases as the window narrows, and that nothing overflows at 1 600 → 800 px.

**Effort:** ~2 h for all four tabs. **Risk:** low, layout only.

---

### A-2 · LOW · `ArchModel(n_elem=0)` raises a bare `ZeroDivisionError`

Constructing the model directly with `n_elem = 0` divides by zero in
`ArchModel.nodes()` (`arch_app.py:119`, `self.span * i / self.n_elem`).

**This is not reachable from the UI** — `arch_app.py:1153` clamps with
`max(4, int(self.nelem_var.get()))`, and the Excel import path funnels through
the same clamp. It is a defensive gap in the model API only, and it is recorded
here so that nobody "fixes" it in the UI layer where the guard already exists.

**How to fix:** if you want the model layer safe when driven directly (a test,
a script, a future headless mode), validate in `ArchModel.__init__`:
`if n_elem < 1: raise ValueError(...)`, in the style of `CableModel`'s
"Cable length must exceed the span" message.

**Effort:** ~10 min. **Risk:** none.

---

### A-3 · LOW · Dead imports and locals

`os`, `sys`, `subprocess` (`arch_app.py:13`) and `INIT_CW`, `INIT_CH`,
`INIT_DH` from `common` (`:15`) are imported unused.

`_apply_shape_preset` (`arch_app.py:898`) reads `L = self.span_var.get() or
self.span` and `rise = self.rise_var.get() or self.rise` at `:900-901` and then
uses neither — the preset strings it sets (`'4*rise*x*(L-x)/L**2'` etc.) carry
`L` and `rise` as *symbols*, resolved later by `make_shape_fn` against a context
built at `:998`, `:1155` and `:1252`. The two locals are leftovers, not a
missing substitution. Verified: all three preset expressions evaluate correctly,
and the `R`/`k` context values they reference are supplied and guarded against a
zero rise at all three sites.

---

### A-4 · LOW · No automated tests for this tab

1 671 lines, zero tests — and this is the tab whose solver most deserves a
regression net, because its accuracy is currently its best feature and nothing
would notice if that changed. The table in §0 is directly portable into
`tests/test_arch_math.py`; the funicular check (max |M| ≈ 0 for a parabolic
arch under UDL) and the hinge check (M = 0 at the crown) are especially good
tests because they need no reference values at all.

---

## 2. Suggested order

1. **A-1** — bundle with the Beam / Cable / Truss layout fix. It is the only
   finding in this tab that affects a user.
2. **A-4** — port §0 into a test module; cheapest way to keep the best solver
   in the project from silently regressing.
3. **A-2**, **A-3** — opportunistically, when next in the file.
