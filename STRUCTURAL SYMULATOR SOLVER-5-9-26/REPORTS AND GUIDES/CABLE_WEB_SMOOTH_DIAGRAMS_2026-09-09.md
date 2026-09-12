# Cable Web — smooth (closed-form) diagrams

**2026-09-09** · full application suite **790 passed**

---

## What was asked

> "I want the graphs, the diagrams (yes the funicular too) to be smooth, not
> discrete. […] maybe in order not to break the original diagram system add a
> toggle that allows me to switch between the real measurement and the
> analytic version of the diagrams like in the case of the geometry of the
> funicular."

Done, and it turned out to be more than a drawing change. The two readings do
not merely look different — they converge to the true answer at different
rates.

---

## What shipped

A **Smooth** checkbox in the header of *both* diagram surfaces — the T/H/V
diagram pane and the funicular pane — bound to one variable, so the two can
never disagree about which reading is on screen. **Off by default**: the
stepped band is what the solve literally produced, and the toggle exists to
add a reading, not to replace one.

With it on, each uniformly loaded stretch is drawn from its closed form
instead of one value per element:

```
H(s) = H            V(s) = v0 + q·s            T(s) = hypot(H, V)
```

`q` comes from the load definition. `H` and `v0` are recovered by least
squares from the elements the solve already produced. There is no second
solve and no new physics — the same recognition as the geometry's Route 1
(MANIFESTO §3y): the curve was available in closed form all along, from data
the app already had.

**Where there is no closed form, the steps stay.** `_analytic_group_params`
returns nothing wherever `_group_uniform_load` refuses — variable loads,
partly covering distributed loads, non-vertical loads, net-upward loads — and
that stretch keeps its per-element band. A smooth curve drawn where the solve
has no closed form would be a picture claiming resolution the numbers do not
have.

---

## Why the staircase was there, and why it mattered

Consistent (trapezoidal) load lumping puts an element's true value at its
**midpoint**, not at its ends. A band drawn at one value per element is
therefore not a coarse drawing of the right answer — it is the right answer
sampled only where the peak is not.

On a cable the peak tension is at the **anchorage**, which is exactly the
place no element midpoint ever lands. So the staircase is guaranteed to
under-report the number the cable is sized with.

---

## Measured, on real solves

`solve_analysis` run for real, peak tension against the closed form
`q·a·cosh(span/2a)`:

| case | stepped | smooth |
|---|---|---|
| 20 m span, 22 m arc, 10 N/m | −5.33% | **−0.34%** |
| 20 m span, 26 m arc, 10 N/m (deep sag) | −9.16% | **−0.10%** |
| 30 m span, 31 m arc, 25 N/m (taut, heavy) | −2.66% | **−0.58%** |
| 12 m span, 18 m arc, 4 N/m (very deep sag) | −10.63% | **−0.04%** |

Every stepped reading is **low, never high** — the trapezoidal sampling
showing through, and the dangerous direction for sizing.

Two identities the stepped band can never show, both now exact:

* shear **V is zero at the vertex**, and T there equals H;
* **V at each anchorage equals half the total weight**, to 1e-9.

---

## The finding: the two readings converge at different orders

The smooth reading lands *near* the closed form, not *on* it. That gap is the
**mesh**, not the smoothing: the values are recovered from element **chords**,
so they inherit the discretisation's own error. Refining settles the question.
30 m span, 31 m arc, 25 N/m:

| elements | H error | Tmax smooth | Tmax stepped |
|---|---|---|---|
| 8 | −0.6997% | −0.5772% | −2.66% |
| 16 | −0.1745% | −0.1441% | −1.21% |
| 32 | −0.0436% | −0.0360% | −0.57% |
| 64 | −0.0109% | −0.0090% | −0.28% |

Error ratios per doubling:

| | ratios | order |
|---|---|---|
| smooth | 4.01, 4.00, 4.00 | **second** |
| stepped | 2.20, 2.10, 2.05 | **first** |

Refining the mesh buys **four times as much** from the smooth reading as from
the stepped one. A drawing choice turned out to set the convergence rate of
the number being read.

---

## Tests

**11 new**, all passing, in `tests/test_cable_web_rendering_2026_09_05.py`.

*Six run with no solver at all*, on a synthetic result whose nodes sit on an
exact catenary. That is a stronger input than a solved one: a solved case
carries discretisation error, so agreement to 1e-9 would be impossible and any
disagreement ambiguous. They cover the statics identities, the drawing path's
agreement with its own formula, the fallback to steps, the default being off,
and the stepped data being untouched.

*Five run real solves*: four spans asserting the smooth peak is within 1% of
the closed form and at least four times closer than the stepped peak, plus the
convergence-order test above.

The order test asserts a **rate**, not a value. A quantity recovered from a
discretisation can never equal the continuum's, and demanding that it should
is what made the first version of that test wrong.

---

## Two bugs found while building this

1. **The readout's minimum kept coming from the old series.** The curve was
   drawn from the closed form while the "min" label still read the stepped
   values, so V's label said 13.7 N beside a curve visibly touching zero.
   Found by *looking at the render*, not by any test. When a display gains a
   second data source, every number beside it is a second consumer that has to
   be moved too.

2. **NumPy was imported at module level in `common.py`.** With Windows Smart
   App Control blocking the `_multiarray_umath` DLL, that made the whole
   application unimportable — including the ~100 tests that never touch NumPy.
   It is now imported lazily behind `_require_numpy()`, whose error names
   Smart App Control as the cause. A hard dependency at import time makes
   every unrelated test share that dependency's fate.

---

## Verification status

The solver-dependent tests could not run while Smart App Control was
enforced — it blocked NumPy's compiled extension, so 65 of them failed at
import and nothing about this work could be verified end to end. The policy
has since been lifted and everything runs clean:

```
790 passed in 300.64s
```

That is the **whole application's** suite — all six tabs — not just the Cable
Web tests, so it covers the shared `common.py` change as well. No regression
against the 5 September baseline.

### A note on where this code landed

The work was built in a partial clone that turned out to be missing 46 files
the real tree has (the Truss plates and guides modules, the Perforated Beam
section modules, `cirsoc_301.py`, and their tests). Zipping that clone would
have shipped an application with half its features deleted.

It was merged file by file instead, never by copying the tree. Two things had
to be reconciled by hand rather than taken wholesale:

* **`common.py`** — this tree had *already* made NumPy lazy, independently and
  for the same reason, on the same day. That version was kept. The two guards
  were then merged into one `_require_numpy(note='')`, so the raise is written
  once rather than twice (MANIFESTO §3j).
* **`cable_web_math.py`** — its module-level `import numpy` was still there in
  this tree, so the Cable Web tab could still take the whole app down at
  launch. It now goes through the same `_require_numpy`.

A block of Cable Web toolbar comments unique to this tree survived the merge
untouched, which is the check that it was a merge and not an overwrite.

The full narrative is in `MANIFESTO.md` §3ac.
