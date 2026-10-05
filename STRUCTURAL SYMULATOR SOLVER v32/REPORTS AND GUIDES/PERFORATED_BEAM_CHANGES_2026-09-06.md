# Perforated Beam — bug fixes and three new features, 2026-09-06

**Build:** STRUCTURAL SYMULATOR SOLVER-5-9-26
**Answers:** `DIAGNOSIS_PERFORATED_BEAM_2026-09-05.md` (findings P-1 … P-5)
**Method:** MANIFESTO §2 — every number below is checked against a textbook
closed form, an exact invariant of linear elasticity, or an equilibrium
statement. Nothing is checked against a previously recorded output of the
same code.

**Tests:** 157 → 256 passing (99 added). Full suite ~4 min.

---

## 0. Summary

| | |
|---|---|
| Diagnosis findings fixed | **P-1, P-2, P-3, P-4, P-5 — all five** |
| Hyperstatic beams | **added** — any number of supports, pin/roller or fixed |
| Two profiles, freely placed | **added** — each with its own dx/dy, welds checked |
| Profile designer | **4 new tools** (centre arc + 3 circle tools), holes, weld marking |
| New modules | `hyperstatic_math.py`, `welded_section_math.py` |
| Files changed | 6 source, 4 new test files, 2 docs |

---

## 1. Bug fixes

### P-1 — bending moment wrong for every non-uniform uplift load · FIXED

A missing `abs()` sent any *negative* trapezoidal load down a
wrong-centroid branch, corrupting M(x) including its sign near the far
support. Measured before/after, w₁ = −10, w₂ = −30 N/mm over 8 m, against
the exact linearity requirement M(−w) = −M(+w):

| x | before | after |
|---|---|---|
| 0.10 L | 0.21 % error | **0.00 %** |
| 0.50 L | 8.33 % error | **0.00 %** |
| 0.75 L | 34.6 % error | **0.00 %** |
| 0.90 L | **119 % — wrong sign** | **0.00 %** |

Fixed as the diagnosis recommended: the branch is gone entirely.
`applied * (xi - xibar)` expands algebraically to `xi² · (2·w1 + wx) / 6`,
which has no division and therefore no degenerate case for any sign.

### P-2 — a load with zero net resultant produced zero reactions · FIXED

`w1 = -w2` has no resultant but a real moment about the supports, so it
must produce equal and opposite reactions. The guard written to dodge a
0/0 in the centroid formula discarded that contribution, making the
function *discontinuous*: a 0.005 % input change flipped the answer
between 0 and 26 669 N.

```
w2 = +20.000   before: RA =      0.0    after: RA = -26666.7   exact: -26666.7
w2 = +20.001   before: RA = -26665.3    after: RA = -26665.3
```

Both guards replaced by the new `_trapezoid_resultant`, which returns the
resultant and its first moment in division-free form — the `(w1 + w2)`
denominator cancels analytically, so no guard is needed at all.

### P-3 — a distributed load entered right-to-left was inverted · FIXED

`DistLoad`/`DistTorque` now normalise in `__post_init__`, swapping the
ends together with their intensities. A reversed entry describes the same
physical load rather than silently becoming uplift of the wrong magnitude.

### P-4 — degenerate sections returned numbers instead of refusing · FIXED

`RolledSection.__post_init__` now rejects non-positive dimensions,
`d <= 2·tf` (flanges overlapping through the web), and `bf <= tw`, each
with a message in the style of the existing `BeamConfig` one. `d = 0`
used to return `I = 427 500 mm⁴`. The shipped catalog is verified to
still pass — the failure mode of an over-tight validator.

### P-5 — dead locals · FIXED

Removed the unused `_signed_area()` calls in `CustomProfileSection.I`/`.Iy`
and the unused `pbm` import in `section_profile_ui.py`.

---

## 2. Feature: hyperstatic (indeterminate) beams

`BeamConfig(support_specs=[SupportSpec(x, kind, torsion_restrained), …])`
→ `hyperstatic_math.py`. Any number of supports, each `'pin'`/`'roller'`
(vertical) or `'fixed'` (vertical + rotational). Covers continuous
multi-span, propped cantilever, fixed-fixed, and cantilever.

**Design:** direct-stiffness solve for the redundant reactions *only*;
V(x)/M(x) then recovered by plain equilibrium integration, so the diagrams
carry no discretization error from the shape functions. Element EI comes
from `net_I_at`, so the openings' reduced I(x) redistributes the
redundants — a real effect a constant-EI solve would miss, and the reason
this meshes at all. Torsion solved on the same mesh, which lets an
*intermediate* support fork the section. Stdlib only: banded Cholesky,
half-bandwidth 3. See MANIFESTO §4e.

**Validated against closed forms** (all exact to 1e-6 or better):

| case | quantity | result |
|---|---|---|
| 2-pin via the solver | vs. the closed-form kernel, every load type | **1e-10** (machine precision) |
| Propped cantilever | R = 5wL/8, 3wL/8; M_fix = −wL²/8; M_span = 9wL²/128 | exact |
| Fixed-fixed | M_end = −wL²/12; M_mid = +wL²/24; v = wL⁴/384EI | exact |
| Two-span continuous | R = 3wL/8, 10wL/8, 3wL/8; M_sup = −wL²/8 | exact |
| Cantilever | R = wL; M = −wL²/2; v_tip = wL⁴/8EI | exact |
| Messy 4-support beam | V(L) and M(L) must vanish | < 1e-9 relative |

**Two things found and fixed during validation, worth recording:**

1. *The rotation-DOF sign was flipped* in both directions (input and
   recovery). Caught by the propped-cantilever end moment coming out
   `+wL²/8` instead of `−wL²/8`. The fix is that no flip is needed at all:
   this module's moment convention is already the y-down one, so
   `θ = dv/dx` with v measured down is directly conjugate to it.
2. *Conditioning.* The first version's error **grew** with mesh
   refinement (7.8e-13 at 8 elements → 5.6e-7 at 320) — the signature of
   ill-conditioning, not of a discretization bug. Rotation DOFs are now
   scaled by a characteristic length before the solve.

---

## 3. Feature: two profiles, freely placed and welded

`welded_section_math.CompoundSection` — each profile positioned by its own
`(dx, dy)`, carrying the parallel-axis terms `BuiltUpDoubleSection` may
drop because it assumes equal centroidal height. That assumption is what
fails for a channel capping an I-beam: the neutral axis moves and
`S_top != S_bot`. `BuiltUpDoubleSection` is left untouched — its shortcut
is correct for what it models.

Validated by exact identities: two 100×50 plates stacked reproduce one
100×100 plate (A, I, S, d) — dropping the parallel-axis term would give
I = 2.08e6 instead of 8.33e6 — and, placed side by side at equal height,
the class agrees with `BuiltUpDoubleSection` to 1e-12.

**Weld check.** The composite properties above are only earned if the
joint transfers the longitudinal shear flow. `check_welds` computes
`q = V·Q/I` with Q from the actual geometry on the held side of the joint
(whole parts summed; a part the line cuts is clipped against the
half-plane; a rolled shape it cannot clip is **refused, not guessed**).
Checked at the station of maximum |V|, since q scales with V.

Validated against the rectangle closed form: for the stacked pair,
`q = 1500 N/mm` at the interface, cross-checked independently via
`τ_max = 1.5V/A` and `q = τ·b`. Leg sizing round-trips to utilisation
exactly 1.00.

---

## 4. Feature: profile designer

**New tools** — Centre Arc (centre, then end point, projected onto the
radius so it is usable by hand), Circle centre+radius, Circle 2-point
(diameter), Circle 3-point. Mouse and typed entry now go through one
shared `_consume_point`, so no tool can work by mouse but not by keyboard.

**Holes.** Any loop — drawn path or circle — can be cut through the
profile. `CustomProfileSection` gained `holes`, subtracted about the same
origin before the parallel-axis shift (exact, not approximate). Loops are
normalised to a common winding first, so a hole drawn clockwise removes
the same material as one drawn anticlockwise. A hole outside the outline,
or holes consuming all the area, are refused with an explanation.

Validated against the closed forms for a hollow box
(A = 100²−80², I = (100⁴−80⁴)/12, exact) and a plate with a circular hole
(πr², πr⁴/4).

**Weld marking.** A weld is drawn as a line across the section, with leg
size, line count and which side it holds. Welds drawn on a profile are
translated with it when it is placed into a compound, so a weld drawn
along a flange stays on that flange — a test pins this, because a weld
line left at its drawn coordinates would miss the assembled section and
report a *passing* check by holding nothing.

**Discretisation bias, stated.** An inscribed n-gon is always smaller than
its circle, so a polygonised hole removes slightly too little material and
the section reads marginally stiffer than reality. At the 144 segments now
used that is 0.032 % of the hole's own area (it was 0.127 % at 72, which
is why 72 was not kept). It is a bias, not noise, so it is documented
rather than left to be discovered.

---

## 4b. Left panel is now scrollable (regression from this work)

Adding the Supports panel, the lateral-bracing frame and the compound
weld editor pushed the left column to **1030 px** tall. On a 1280×800
window the viewport is ~750 px, so roughly **280 px of controls — the
entire Loads panel — could not be reached at all.** It overflows even at
1920×1080.

Fixed with the same canvas + scrollbar + mousewheel arrangement the
Truss, Beam, Arch and Cable tabs already use; Perforated Beam was the only
tab without one. The inner frame tracks the canvas's current width rather
than a fixed `PANEL_W`, so the scrollbar's own pixels do not push the
controls sideways out of view — a latent issue in the other four tabs'
fixed-width version.

Six regression tests cover it, including one that asserts the panel
*still overflows*: if the column is ever slimmed down enough to fit, that
test fails and says the others no longer prove anything, rather than
passing silently while testing nothing. Visibility is measured in canvas
coordinates, not screen ones, so it does not depend on when the window
manager repaints.

## 5. On CIRSOC — what was and was not done

The MANIFESTO's existing position (§1) is unchanged and still correct:
CIRSOC 301 is the intended governing standard, and this module implements
the *format* those checks take (elastic stress interaction under factored
loads) without claiming clause-level compliance.

What the weld work adds is that the design basis is now **explicit and
editable data** rather than constants buried in a function:

```python
WeldCode(name='CIRSOC 301 / AISC 360 J2.4 (LRFD)',
         phi=0.75, Fexx=482.0, throat_factor=0.707)
```

`phi · 0.60 · Fexx · 0.707 · leg` is the LRFD fillet-weld form shared by
CIRSOC 301 and AISC 360, and is the same expression
`design_builtup_connector` already used — so no second, competing weld
formula was introduced. The report prints the basis and its numbers on
every run, with the instruction to confirm them.

**Deliberately not done: no clause numbers or resistance-factor tables
were transcribed from memory.** I do not have verified access to CIRSOC
301, 101 or 102, and inventing citations in a structural tool is worse
than having none. The defaults above are the widely published LRFD values
— a starting point to confirm, not a citation.

**If you can supply the documents**, the clause-level work these enable is
well-defined and I would take it on: φ factors applied to the reported
utilisation ratios per CIRSOC 301 chapters F/G/H; CIRSOC 101/102 load
combinations building V(x)/M(x)/T(x) rather than the user pre-factoring
them; and minimum/maximum fillet sizes for the connected thickness, which
is the check that actually governs most of the welds this module now
sizes — the compound example in the tests needs a 0.3 mm leg for strength,
which is not a buildable weld, and the report says so explicitly rather
than letting someone specify it.

---

## 6. Where things live

| file | change |
|---|---|
| `perforated_beam_math.py` | P-1…P-5; `support_specs` dispatch; equilibrium recovery; `holes` |
| `hyperstatic_math.py` | **new** — stiffness solver, banded Cholesky, torsion |
| `welded_section_math.py` | **new** — `CompoundSection`, `WeldLine`, `check_welds` |
| `section_profile_math.py` | circles, centre arcs, `SectionSketch`, welds, persistence |
| `section_profile_ui.py` | rewritten tool palette, holes, weld editor |
| `perforated_beam_app.py` | support panel, compound panel, weld reporting |
| `tests/test_hyperstatic_math.py` | **new** — 42 tests |
| `tests/test_welded_section.py` | **new** — 34 tests |
| `tests/test_section_sketch.py` | **new** — 24 tests |
| `tests/test_perforated_beam_app_features.py` | **new** — 12 UI integration tests |

Backward compatibility: `support_specs` unset → the closed-form path runs
unchanged; profiles saved before holes and welds existed still load; the
legacy `reactions()` pair still works for 2-support beams and refuses
(pointing at `support_reactions()`) rather than truncating for others.
