# Cable tab — bugs still open, 2026-09-10

**File:** `apps/cable/cable_app.py` (1 934 lines)
**Re-diagnosis of** `DIAGNOSIS_CABLE_2026-09-05.md`. Suite green: 809 passed.

| finding | severity | status |
|---|---|---|
| C-1 max tension under-reported | MED | ❌ open — **now visibly self-contradictory** |
| C-2 ▶ Analyze lost below 1200 px | MED | ✅ fixed |
| C-3 no physics tests | LOW | ❌ open |
| C-4 dead locals / imports | LOW | ❌ open |
| C-5 zero-tension state reported as converged | LOW | ❌ new |
| C-6 diagram end-labels collide | LOW | ❌ new |

**The shape solver is still excellent** — re-validated today against all three
closed forms it claims: parabola (H = wL²/8f, 1.4e-5), catenary (H and sag,
1.4e-5), midspan point load (1.8e-12). Excel round-trip clean. Reversed and
out-of-span *point* loads are properly rejected. Nothing has regressed.

---

## C-2 · FIXED

26 of 26 controls mapped from 1600 px to 900 px, 24 at 550 px, nothing pushed
off the edge. Was 26 → 10 with ▶ Analyze unreachable below 1200 px. Done.

---

## C-1 · MEDIUM · Max tension is still under-reported — and the tab now contradicts itself on screen

This is the same bug as September, but it is no longer only an accuracy
argument. **The app displays two different maximum tensions at the same time**,
and the lower one drives the code check.

**On the tab's own built-in “Example: catenary”, at default settings, with no
user input at all:**

| where | value |
|---|---|
| RESULTS panel — `Max tension T` | **25.48 kN** |
| RESULTS panel — `sigma = T_max/A` | 2.548 kN/cm² (uses 25.48) |
| Tension diagram, same screen — `max T=` | **25.66 kN** |
| Exact: `hypot(H, R)` = hypot(19.647, 16.500) | **25.6564 kN** |

The diagram is right. The results panel is **0.69 % low**, and it is the
results panel that feeds the stress check the engineer reads.

Re-measured across sag ratios at the app's default `n_elem = 60`:

| sag / span | true T_max | reported | error | `hypot(H,R)` | error |
|---|---|---|---|---|---|
| 0.161 | 9 614.0 N | 9 564.3 | **−0.52 %** | 9 613.3 | −0.008 % |
| 0.355 | 7 553.7 N | 7 463.2 | **−1.20 %** | 7 553.6 | −0.002 % |
| 1.026 | 12 264.6 N | 12 065.6 | **−1.62 %** | 12 264.6 | −0.0001 % |
| 7.321 | 74 210.0 N | 72 973.7 | **−1.67 %** | 74 210.3 | −0.0005 % |

Identical to the September numbers — nothing has changed here. The error is
always **negative**, i.e. on the unsafe side, and converges only **first
order** (n_elem 50 → −1.44 %, 200 → −0.36 %, 400 → −0.18 %), so refining the
mesh is an expensive way out. H itself converges second-order and is already
exact to 1e-5 at n_elem = 60 — the shape is fine, only the end-tension readout
is coarse.

**Root cause:** `CableResult.element_tension()` (`cable_app.py:566`) computes
`T = H / cos θ` from each element's **chord**. The element next to a support
runs from the support to the first interior node, and its chord is flatter
than the cable's true slope there. `tension()`, `force_components()`, the
results table and the stress check all build on it.

**Fix:** the true end tension needs no discretisation. The horizontal
component is `H` everywhere, and the vertical component at a support is
exactly the reaction — which `CableResult.reactions()` already returns exactly:

```python
T_support = math.hypot(self.H, R_vertical_at_that_support)
```

Use it for the two end stations of `tension()` and for the reported maximum;
leave the interior elements alone. That is the last column of the table above
— accurate to 0.008 % or better at the same `n_elem = 60`.

**Verify:** the results panel and the diagram must then agree (25.66 / 25.66 on
the built-in catenary example), and |error| < 0.01 % across the four sag ratios.
Record before/after on both built-in examples. **Effort ~1 h. Risk low-medium
— it changes a reported design number.**

---

## C-5 · LOW · NEW · A cable with no effective load reports `converged = True` at zero tension

A distributed load whose domain falls entirely outside the span contributes
nothing, and the solve returns a converged result with essentially zero
tension:

```
dist load x1=0,  x2=20  (span 20)  ->  H = 12 499  R = (5000, 5000)  converged=True
dist load x1=30, x2=50  (span 20)  ->  H = 6.6e-18 R = (0, 0)        converged=True
```

`H ≈ 0` is not a cable in equilibrium — it is a slack string — but the tab
presents it as a converged solution, and the stress check will happily divide
by it. The "no load at all" case behaves the same way.

**Fix:** after solving, if `H` is below a small fraction of any applied load
(or the total applied load is ~0), report "no effective load on the cable —
nothing to solve" through the status bar rather than a converged result. Also
worth warning when a load's domain does not intersect `[0, span]`, which is the
underlying user error. **Effort ~30 min.**

---

## C-6 · LOW · NEW · End-station labels collide with captions and axis ticks

Measured overlapping text bounding boxes in `diag_canvas`: 7 collisions at
1500 px, 12–16 at 700–800 px. Confirmed against a 1500 px screenshot: the
`x=0.00` end labels sit on top of the `TENSION T(x)` and `THRUST Fx/Fy`
captions, and at the bottom the `x=0.00` marker overlaps both the
`R_left: H=…, V=…` annotation and the `0` axis tick.

Much milder than the Arch version (**A-5**) — everything is still readable —
but it is the same idiom and would be fixed by the same change. **Effort:
folded into A-5.**

---

## C-3 · LOW · Still no physics tests for this tab

1 934 lines, still no test file of its own. `tests/` has four Cable **Web**
test files, which is easy to misread as coverage; this tab appears only in
`test_excel_roundtrip.py` and `test_tab_layouts.py`.

Nothing asserts a cable closed form, which is why **C-1 has survived two
diagnoses with a green suite**. The three closed forms in
`DIAGNOSIS_CABLE_2026-09-05.md` §0 port directly into
`tests/test_cable_math.py`, and one extra assertion — *the results panel's
max tension equals the diagram's* — would have caught C-1 outright. **~1 h,
and it should land with the C-1 fix.**

## C-4 · LOW · Dead locals and imports

Unchanged: `os`, `sys`, `subprocess`, three `common` names (6 unused imports);
unused locals `ch` (`:431`), `x`, `y` (`:625`), `slope` (`:713`), `R` (`:1815`).

`slope` and `R` are still worth a glance when you are next in those functions —
an unused computed value is occasionally a half-finished formula, which is
exactly what `qfn` turned out to be in the Beam tab (B-3). Neither shows any
symptom today.
