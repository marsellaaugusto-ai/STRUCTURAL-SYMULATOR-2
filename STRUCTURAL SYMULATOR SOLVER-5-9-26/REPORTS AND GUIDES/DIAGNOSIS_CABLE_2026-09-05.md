# Cable tab — diagnostic report, 2026-09-05

**File:** `apps/cable/cable_app.py` (1 898 lines: `CableModel`, `CableResult`,
`CableApp`)
**Build:** STRUCTURAL SYMULATOR SOLVER-5-9-26
**Method:** MANIFESTO §2 — closed-form validation against all three exact
solutions this solver claims to reproduce (parabola, catenary, single point
load), plus live widget measurement.
**Baseline:** existing suite 157 passed in 224 s. Note: those tests cover Cable
**Web**, not this tab — Cable has no tests of its own.

---

## 0. Summary

| | |
|---|---|
| Funicular shape solver | **correct** — matches all three closed forms to ≤1.4e-5 |
| Reported peak tension | **systematically low by 0.5–1.7 %** (unconservative) |
| Layout | Analyze button lost below ~1 200 px |
| Automated tests for this tab | **0** |

The solver is excellent — the claim in its docstring that it is exact for both
per-horizontal-metre and per-arc-metre loading holds up under measurement. The
one real defect is in how tension is *reported*, not how the shape is solved.

### What was verified as CORRECT (do not "fix" these)

| case | quantity | agreement |
|---|---|---|
| Parabolic, UDL per horizontal m, sag 2 m / 20 m span | sag, H = wL²/8f | 1.4e-5 |
| Catenary, self-weight per arc m | H, sag = (H/w)(cosh(wL/2H)−1) | 1.4e-5 |
| Catenary shape at quarter points | y(x) vs (H/w)(cosh(w(x−L/2)/H)−…) | ≤4e-3 |
| Single midspan point load, weightless | sag, H = PL/4f, T = √(H²+(P/2)²) | 1.8e-12 |
| Support reactions, parabolic case | R = wL/2 each | exact |

Convergence of H with mesh refinement is second-order and reaches 1.6e-6 at
n_elem = 400. Degenerate inputs are handled well: `length ≤ span` raises "Cable
length must exceed the span (s > L)"; a point load at or outside a support
raises "A point load must lie strictly between the supports"; an upward point
load and a zero-magnitude load both solve without complaint. Excel export →
import round-trips cleanly on all three built-in examples (8 state keys, zero
differences).

---

## 1. Findings

### C-1 · MEDIUM · Maximum cable tension is reported low, and the error is unconservative

Peak tension is taken from the *chord* of the end element, which is always
flatter than the true tangent at the support. The reported maximum is therefore
always **below** the true maximum — the wrong direction for a design value.

**Measured** at the app's own default mesh (`n_elem = 60`, `cable_app.py:1055`),
catenary under self-weight, 20 m span:

| sag / span | true T_max | reported | error | `hypot(H, R)` | error |
|---|---|---|---|---|---|
| 0.161 | 9 614.0 N | 9 564.3 | **−0.52 %** | 9 613.3 | −0.008 % |
| 0.355 | 7 553.7 N | 7 463.2 | **−1.20 %** | 7 553.6 | −0.002 % |
| 1.026 | 12 264.6 N | 12 065.6 | **−1.62 %** | 12 264.6 | −0.0001 % |
| 7.321 | 74 210.0 N | 72 973.7 | **−1.67 %** | 74 210.3 | −0.0005 % |

Convergence is only **first order** — halving the element size only halves the
error, so refining the mesh is an expensive way out:

```
n_elem =  10  ->  -7.16 %
n_elem =  50  ->  -1.44 %
n_elem = 200  ->  -0.36 %
n_elem = 400  ->  -0.18 %
```

Contrast H itself, which converges second-order and is already exact to 1e-5 at
n_elem = 60. The shape is fine; only the end-tension readout is coarse.

**Root cause:** `CableResult.element_tension()` (`cable_app.py:565`) computes
`T = H / cos θ` from each element's chord. That is exact *for that element*, but
the element adjacent to a support spans from the support to the first interior
node, and its chord slope is not the cable's slope at the support. `tension()`,
`force_components()` and the results table all build on it.

**How to fix:** the true end tension needs no discretisation at all. The
horizontal component is `H` everywhere (that is what makes a cable a cable) and
the vertical component at a support is exactly the support reaction, which
`CableResult.reactions()` already returns exactly (it gives 5 000.000000 N on
the parabolic case against an exact 5 000). So:

```python
T_support = math.hypot(self.H, R_vertical_at_that_support)
```

The last column of the table above is that expression — accurate to 0.008 % or
better at the *same* n_elem = 60, i.e. two to three orders of magnitude better
for no extra cost. Use it for the two end stations of `tension()` and for the
reported maximum; leave the interior elements as they are.

**Verify:** re-run the four rows above and expect |error| < 0.01 % at
n_elem = 60; confirm the built-in Example and Picture Test tensions move only
at the end nodes.

**Effort:** ~1 h. **Risk:** low-medium — it changes a reported design number,
so record the before/after on both built-in examples in the commit message.

---

### C-2 · MEDIUM · The ▶ Analyze button disappears below ~1 200 px window width

Same class of failure as the Beam tab. The toolbar is a single non-wrapping
`pack` row; as the window narrows Tk **unmaps** the controls that no longer fit
rather than clipping or scrolling them.

Measured across the tab's 26 controls:

| window width | mapped | overflowing | worst overflow |
|---|---|---|---|
| 1 600 px | 26 | 0 | — |
| 1 200 px | 25 | 0 | — (▶ Analyze already lost) |
| 1 000 px | 23 | 6 | +133 px |
| 900 px | 22 | 6 | +233 px |
| 800 px | **12** | 0 | — (half the tab gone) |
| 550 px | **10** | 0 | — |

Named buttons lost, by width: **1 200 px** — ▶ Analyze. **900 px** — Clear,
Export Excel, Import Excel, ▶ Analyze. **700 px** — also Add, Delete, Example:
point load. **550 px** — 8 of 11.

**How to fix:** see B-2 in the Beam report — the same three options apply, and
whichever you pick should be applied to Beam, Arch and Cable together since all
three share the layout idiom. Cable Web's `_update_responsive_sidebars()` is the
in-project reference implementation.

**Effort:** ~1 h if done alongside Beam and Arch. **Risk:** low, layout only.

---

### C-3 · LOW · No automated tests for this tab

1 898 lines, zero tests. The `tests/` directory has four Cable **Web** test
files and none for Cable — an easy thing to misread as coverage. The three
closed-form cases in §0 are directly portable into `tests/test_cable_math.py`
and would pin both the shape solver and C-1's fix.

---

### C-4 · LOW · Dead imports and locals

`os`, `sys`, `subprocess` (`cable_app.py:17`) and `INIT_CW`, `INIT_CH`,
`INIT_DH` (`:19`) are imported unused. Unused locals: `ch` (`:430`), `x`, `y`
(`:624`), `slope` (`:712`), `R` (`:1779`). Worth a glance at `slope` and `R`
when you are next in those functions — an unused computed value is occasionally
a half-finished formula rather than a leftover (that is exactly what `qfn` turned
out to be in the Beam tab, finding B-3). Neither showed any symptom here.

---

## 2. Suggested order

1. **C-1** — it is the one number in this tab an engineer would put in a
   drawing, and it is currently on the unsafe side.
2. **C-2** — bundle with the Beam and Arch layout fix.
3. **C-3** — port §0 into a test module, ideally in the same change as C-1 so
   the new tension formula ships with its own proof.
4. **C-4** — opportunistically.
