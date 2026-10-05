# Why the utilization view looked uniformly green, and what the rod-load
# check turned up

2026-09-20. Written from the `wave_like_function_2.xlsx` model supplied
with the question: 1985 nodes, 7742 pin-jointed rods, 60 supports.

## 1. The utilization gradient: not a bug, but a real problem

**The report:** utilization paints the whole structure one flat green,
while the thickness-by-stress view of the same model plainly shows
variation. One of the two looked wrong.

**Both are right, and they answer different questions.**

Measured on the supplied workbook's own `Member Checks` sheet:

| percentile | utilization |
|-----------:|------------:|
| p50        | 0.0049 |
| p90        | 0.0162 |
| p99        | 0.0331 |
| **max**    | **0.0454** |

The worst rod in the model is at **4.5% of capacity**. Spot-checked by
hand against the sheet: member 0 carries 0.715 kN on 20 cm^2 with
Fy = 235 MPa, so sigma = 0.357 MPa against phi*Fy = 211.5 MPa, giving
0.00169 -- exactly what the sheet reports. The numbers are correct.

`util_color` maps an **absolute, code-defined** scale: green at 0, amber
at 0.5, red at 1.0. A model whose entire range is 0 to 0.045 therefore
occupies the first 4.5% of that bar, and every rod lands in the first
tenth of the green-to-amber leg. It is supposed to look green. That is
the scale telling the truth: nothing here is anywhere near capacity.

Thickness-by-stress is **relative** -- each member against the most
stressed one in this model -- so it shows the distribution regardless of
how much spare capacity there is. Hence the disagreement.

**What changed.** A new `Auto-range utilization` toggle (Display popover
and the Analyse panel, off by default) stretches the same green-amber-red
ramp across only the range this model occupies. The absolute scale stays
the default, because for a capacity check "red = at capacity" is worth
more than contrast.

Two things keep the relative mode honest:

- The legend prints the real utilizations at each tick and states that
  red means "the busiest rod HERE, not at capacity", with the peak as a
  percentage.
- `_util_top` **caps the range at 1.0**. Auto-ranging a model whose peak
  is above capacity would slide the red end out to that peak and paint a
  rod sitting at exactly 1.0 in mid-amber -- measured: with a peak of
  2.4, util 1.0 came out `#d7a127`, which reads as "moderate". Capped,
  auto-range can only ever stretch the ramp *up to* capacity, and an
  overloaded model falls back to the absolute scale.

Over-capacity rods are drawn dashed and thickened off the **true**
utilization, never off the ramp, so they stay unmistakable at any scale.

The absolute legend now also explains itself: when the peak is under
0.25 it says so and points at the toggle, so a flat green picture is
never again mistaken for a broken gradient.

## 2. The rod distributed load: verified, and one real bug found

Checked against closed-form beam theory rather than against itself. All
figures exact to the digits shown (w = 10 kN/m, L = 6 m, 8 segments):

| case | quantity | computed | closed form |
|------|----------|---------:|------------:|
| fixed-fixed | sum Rz | 60.000000 | wL = 60 |
| fixed-fixed | end moment | 30.000000 | wL^2/12 = 30 |
| fixed-fixed | midspan moment | 15.000000 | wL^2/24 = 15 |
| simply supported | midspan moment | 45.000000 | wL^2/8 = 45 |
| simply supported | midspan deflection | -8.437500 mm | 5wL^4/384EI = -8.4375 |
| one rod | dVz along it | -7.500000 | w*Lseg = -7.5 |
| pin grid, 72 rods | sum Rz | 1957.396148 | 1957.396148 |
| sloped 30 deg, `along` | sum Rz | 60.00000 | wL |
| sloped 30 deg, `projected` | sum Rz | 51.96152 | w*L*cos30 |

With no rod load, shear is reported constant and `varies_along_the_rod`
is False -- the honest answer, not a manufactured ramp.

### The bug: pinned rods reported their bending moment backwards

`member_diagram` documents its own convention: **dMy/dx = +Vz** and
**dMz/dx = -Vy**. The rigid branch obeyed it. The pin branch did not --
it returned `+wz*x*(L-x)/2` and `-wy*x*(L-x)/2`, whose derivatives are
`-Vz` and `+Vy`. Both moments came out with the **opposite sign** to a
rigid member bending exactly the same way.

Verified by differentiating the returned moment numerically, so the
finding does not depend on any hand-written formula:

```
--- rigid ---   t=0.25: dMy/dx=  2.0000  Vz=  2.0000 -> +Vz OK
--- pin ---     t=0.25: dMy/dx= -5.0000  Vz=  5.0000 -> MISMATCH (= -Vz)
```

**Why it survived:** every existing check in
`tests/test_stereo_member_loads.py` went through `abs()` or
`math.hypot()`. The magnitudes were right, so the tests passed.
`_rod_field_value` colours the moment-along-rod view by the **signed**
value -- so every pinned rod was painted as though it were hogging when
it was sagging. Most rods in a space truss are pins, and the supplied
model is entirely pin-jointed.

Fixed, and pinned down by two new sign-aware tests: one differentiates
both branches against the stated convention, the other checks that a
sagging pin rod and a sagging rigid rod agree in sign.

## 3. Two more found while building the examples

- **The surface preview drew over everything.** It was gated only by its
  own checkbox, so the Shape panel's expression -- defaulting to `0` --
  painted a flat sheet at z=0 straight through every ready-made example
  and every family Generate. It now draws only while the Shape panel is
  in front, which is the only time it is a preview of anything.

- **The isometric fix had not reached the wizard.** Stage 1 fixed the
  overshoot in `custom_surface_lattice` (the Shape panel's path), but
  `custom_surface_grid` and `custom_surface_between` still used the
  oblique basis -- and the Custom Surface Wizard calls those two
  directly. On a 12 m domain they ran to x = 12.75, a 106% overshoot.
  Both now delegate to `isometric_lattice`.

  The cost of staying inside the domain, measured: rows are spaced to
  divide the domain a whole number of times, so the triangles are
  isosceles rather than exactly equilateral. The diagonal differs from
  the in-row chord by at most **5.7%** (n1=4; n1=6 and 12 are 0.8%,
  n1=8 is 2.0%), and the deviation depends only on n1, not on the span.
  The two properties cannot both hold -- a rectangle whose sides are not
  in the ratio of a triangular lattice cannot be tiled exactly by one --
  and the old test asserting perfectly equal members was only satisfied
  by the version that left the domain.

## 4. Six new examples

`Load Example` now carries 17 entries, six of them new:

| example | demonstrates |
|---------|--------------|
| Two-surface truss: dish over plane, ISOMETRIC | isometric in the two-surface interface, domain staying Cartesian |
| Bezier profile EXTRUDED: fitted cosine vault | fit a formula, then edit the curve |
| Bezier profile SPUN: waisted tower | the formula read as a RADIUS; a shape no height field can express |
| Bezier PATCH: fitted dish, 7x7 controls | the patch, and its degree ceiling |
| Distributed load ALONG THE RODS | the only thing that makes shear vary along a member |
| Billowing doubly-curved shell | curvature in both directions, unlike the one-way wave |

All six load, solve under self-weight, and are covered by tests. The
rod-load one required `_load_mesh` to keep the loads a mesh arrives
with: it clears rod loads on every regenerate (a rod load is a member
INDEX, so a stale one lands on whatever member now holds that number),
which was right for every other mesh and wrong for an example whose
whole point is the load.
