# Beam diagram sampling: from cubic to flat — 2026-09-10

The first open item from the recommendations list. `BeamResult.sample_diagram`
was the single biggest reason the test suite ran for over an hour, and it made a
beam with many loads visibly slow to draw. It is now roughly **240× faster at 20
loads and 360× at 40**, with the shear and moment diagrams byte-identical and
the deflection curve unchanged to within 2e-4.

---

## What was slow, measured not guessed

`sample_diagram` samples shear, moment and deflection along the beam for
plotting. A profile at 20 point loads showed **all** the time in one place:

| function | share of the 1.67 s |
|---|---|
| `deflection` → `_theta_v_at` | 1.665 s |
| shear + moment sampling | 0.002 s |

`moment_at` was called **437,473 times** for a single draw. The shear and moment
curves were never the problem.

The cause is that `sample_diagram` called `deflection(x)` once per station, and
`deflection(x)` → `_theta_v_at(x)` **re-integrates the whole moment diagram from
x = 0 every time it is called**, sub-dividing each element 30 ways, and each
sub-step is an `O(loads)` moment evaluation. So sampling the curve cost
`O(stations × elements × 30 × loads)` — and stations, elements and loads all
grow together with the model, which is the cubic blow-up. Wall time bore it out:

| point loads | before | after |
|---|---|---|
| 2  | 0.055 s | 0.001 s |
| 10 | 0.209 s | 0.002 s |
| 20 | 0.972 s | 0.004 s |
| 40 | 5.443 s | 0.015 s |

Per-station time went from 4.28 ms at 40 loads to a flat 0.01 ms.

---

## The fix

The moment values are already sampled at every station for the moment diagram.
The deflection is now integrated **forward in one cumulative pass** over those
same samples — rotation from integrating M/EI (Simpson), deflection from
integrating the rotation (trapezoid), seeded at x = 0 from the left node's own
solved degrees of freedom. This is the same rule `_theta_v_at` uses; it simply
runs once across the beam instead of restarting from zero at every station. A
zero-width interval — the twin before/after points that draw a shear or moment
jump — leaves rotation and deflection untouched, which is correct, since slope
and deflection are continuous across a jump in V or M.

The one thing deliberately left alone is the point-query `deflection(x)` method
itself. It keeps its original restart-from-zero integrator, so the closed-form
deflection tests (`test_beam_math.py`, tolerance 3e-3, plus a 1e-9
mesh-invariance check) still bind on the exact code they were written for, and
the fast sampling path is validated against them rather than replacing them.

---

## Verification

Six models spanning the cases that matter — simply-supported UDL, mid-span point
load, cantilever tip load, fixed-fixed UDL, a triangular ramp, and a
twenty-load beam with an applied moment — were sampled before and after and
compared arm's-length:

- **Shear and moment arrays: byte-identical** in every case.
- **Deflection: worst relative deviation 1.85e-4**, well under the suite's 3e-3
  deflection tolerance and far below anything visible in a drawn curve. This is
  ordinary integration-scheme noise (a single pass on the 25-point sample grid
  versus the method's 30-point restart), not a change of answer.
- `test_beam_math.py`, `test_units_in_beam_tab.py`, `test_excel_roundtrip.py`
  and `test_tab_layouts.py` all pass.
- The rendered diagrams were screenshotted on the twenty-load model: clean
  stepped shear, a smooth sagging moment curve, and a smooth downward deflection
  curve with no wobble or artefact.

---

## Knock-on effect

This path is exercised by every beam analysis, the Excel export, and the results
panel's max-deflection readout. Making it flat instead of cubic is why the full
test suite, previously about 65 minutes, will run markedly faster from here —
the practical payoff being a tighter verify loop for every change after this one.
