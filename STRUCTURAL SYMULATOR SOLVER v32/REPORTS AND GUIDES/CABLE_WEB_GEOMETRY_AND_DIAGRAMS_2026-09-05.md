# Cable Web — curve geometry, diagram verification, and two feature plans

**Date:** 2026-09-05 (second pass) · **Build:** STRUCTURAL SYMULATOR SOLVER-5-9-26
**Method:** MANIFESTO §2 — capture the real coordinate lists on their way to
the canvas and measure them. Nothing below is inferred from reading code.

Covers four things you asked for:

1. **Diagnosis** — why the funicular wobbles and looks polygonal (pics 1 and 2).
2. **Verification** — is the tension/thrust diagram integrated correctly?
3. **Plan** — web-wide thrust (H and V) and tension diagrams drawn *into* the
   geometry, following the funicular curve.
4. **Plan** — equilibrium force vectors at supports and nodes.

---

## PART 1 — The wobble and the polygonal shape

### 1.0 Short answer

**It is not Tkinter.** Tk draws exactly the coordinate list it is handed. I
captured those lists immediately before they reach `canvas.create_line` and
measured them; the defects are in the numbers we produce, not in how Tk
renders them.

There are **two separate causes**, and they need opposite responses:

| | what you see | cause | status |
|---|---|---|---|
| **A** | wobble / oscillation | **a regression I introduced in this build** | **fixed** |
| **B** | polygonal, faceted | the solved shape genuinely *is* a polygon | correct — needs a feature, not a fix |

### 1.1 Cause A — the wobble was mine, and it is fixed

When I added `_insert_sag_vertex` in the 5-9-26 build (to cure the *plateau*
you reported earlier), its "don't insert on top of an existing node" guard
was written as *"not within 2% of the three-point window"*. That window spans
two segments, so 2% of it is 4% of a segment — far too weak.

Measured on the built-in Example, cable C2:

```
raw solved points of the drawn group (screen px, offset from its own chord)
   0  (395.09, 617.84)   offset    -0.000
   1  (440.34, 704.18)   offset   -97.413
   2  (520.93, 759.00)   offset  -184.942
   3  (526.63, 759.24)   offset  -187.971   <- inserted apex, 5.70 px from pt 2
   4  (606.42, 712.17)   offset  -186.566
   ...
```

The apex landed **5.70 px** from an existing node against a **97.47 px**
typical spacing. `_smooth_polyline` uses centred (Catmull-Rom) tangents, and
those overshoot badly across a sliver segment. The consequence, measured:

| | direction reversals in the raw data | in the drawn curve | overshoot beyond the solved envelope |
|---|---|---|---|
| with the old guard | 1 (correct — a single sag) | **3** | **+2.88 px** |
| after the fix | 1 | **1** | +0.00 px |

A correct sag has exactly one direction reversal. Three is the oscillation.

**The fix:** the apex must land in the **middle 60%** of whichever segment it
splits, so neither resulting sub-segment is ever shorter than 20% of the
original and no sliver can be created. Verified: reversals back to 1, the
plateau sweep still 28/28 faithful, and the point-load plateau still fixed
(7.6%, against 13.1% before the insertion existed). Two new regression tests
guard it — one on the geometry helper directly, one asserting that the drawn
curve never has more direction reversals than the solved polyline.

I am sorry this one reached you; it is exactly the "fix X, regress Y" pattern
the manifesto exists to catch, and the guard it needed is now a test.

### 1.2 Cause B — the polygonal look is the solved shape, and it is correct

This one is **not a bug**, and it cannot be fixed by drawing differently
without drawing something that was never solved.

`_build_solver_model` **lumps every distributed load at the mesh nodes**.
Between two nodes there is then no load at all, and equilibrium requires an
unloaded cable element to be **exactly straight**. So the solved cable is a
funicular *polygon*, not a smooth curve — and with `nseg = max(4, min(8, …))`
it is at most an 8-sided one.

Measured on the Example, confirming the physics rather than assuming it:

```
C1  L=20.0 m  w=0 N/m   point load P-A at s=10, junction at s=5
      s  0.00 ->  2.50   T=78.48   no distributed load -> must be DEAD STRAIGHT
      ...
   measured chord offset on those stretches: 0.00 px, 0 direction reversals
```

Two consequences worth being explicit about:

- **A cable with `w = 0` and only point loads has no catenary anywhere.** Its
  true shape is straight lines between the load points. If pic 1's "unloaded
  segment" belongs to a cable with self-weight left at 0, then a straight
  segment is the right answer and the curve you expect would be wrong.
  → *Question for you at the end of this document.*
- **Where a distributed load does act**, the true shape is a catenary or
  parabola, and we approximate it with at most 8 chords. At normal zoom that
  reads as a curve; zoomed in, as in your screenshots, the facets show.

**Why not just use a finer mesh?** Measured, because MANIFESTO §3k requires
it:

| `_solver_breakpoints` divisor | single cable | built-in Example | Picture Test |
|---|---|---|---|
| 2.5 (current, ≤8 edges) | 0.13 s | 0.86 s | **1.2 s** |
| 1.25 (≤16) | 0.12 s | 15.6 s | **42 s** |
| 0.8 (≤24) | 0.39 s | 22.7 s | **240 s** |

Refining is nearly free for **one cable** and catastrophic for a **network** —
the cost is the coupled solve, not the mesh. So a blanket refinement is off
the table, and the honest options are:

- **B1 (recommended, cheap).** A display-only "smooth loaded spans" toggle:
  between consecutive solved nodes on a span carrying distributed load, draw
  the analytic parabola implied by that span's own solved thrust
  (`y'' = q/H`), instead of the chord. Uses only solved quantities, adds no
  unknowns, costs nothing per frame. Off by default.
- **B2 (accurate, targeted).** A "refine this cable" action that re-solves a
  **single, isolated** cable at high mesh purely for display and reporting.
  Cheap precisely because it is one cable, per the table above.
- **B3 (do not do).** Raise the mesh globally.

---

## PART 2 — Is the tension/thrust diagram integrated correctly?

**Yes. The integration is exactly right.** I verified it three ways, against
the Cable tab as you asked and against closed-form values.

### 2.1 Definitions agree

The Cable tab solves the classic H-formulation: `H` is one scalar horizontal
thrust, constant along the cable, and `T = H / cos θ` per element. Cable Web
solves a network and reports a per-edge axial tension, deriving
`H = T·cos θ` and `V = T·sin θ`. These are inverses of each other — the same
convention.

### 2.2 Point load — exact to 0.000%

Span 20 m, arc 22 m, 400 N at midspan. Closed form: `f = √((S/2)² − (L/2)²)`,
`H = PL/4f`, `T = hypot(H, P/2)`.

| | sag f (m) | H (N) | T (N) |
|---|---|---|---|
| closed form | 4.58258 | 436.4358 | 480.0794 |
| Cable tab | 4.58258 | 436.4358 | 480.0794 |
| **Cable Web** | **4.58258** | **436.4358** | **480.0794** |

Support reactions sum to exactly 400.00 N.

### 2.3 UDL — identical at matched discretisation

Same cable, UDL 10 N/m along the arc. Cable Web uses 8 edges; the Cable tab
defaults to 50. Run the Cable tab at **n_elem = 8** and the two agree to every
digit printed:

| n_elem | sag (m) | H (N) | Tmax (N) |
|---|---|---|---|
| **8 (= Cable Web)** | **4.03727** | **130.2388** | **161.9451** |
| 16 | 4.01376 | 130.8043 | 166.5669 |
| 32 | 4.00795 | 130.9457 | 168.8263 |
| 64 | 4.00650 | 130.9810 | 169.9437 |
| 200 | 4.00607 | 130.9916 | 170.6989 |
| 400 | 4.00603 | 130.9924 | 170.8760 |

Cable Web reported **H = 130.2388, Tmax = 161.9451, sag = 4.03727** — the
n_elem = 8 row, exactly.

`T = hypot(H, V)` holds on every edge to 1e-6 relative. Vertical equilibrium
also checks out once the lumping is accounted for: end-edge V is
96.25 + 96.25 = 192.50 N, the support reactions sum to 220.00 N = the applied
load, and the 27.50 N difference is precisely the load lumped **at** the two
support nodes.

### 2.4 The real issue: Tmax is under-reported by ~5%

Not a formula error — a **resolution** one. Peak tension occurs at the
supports, where the cable is steepest, and 8 edges cannot resolve it:
**161.9 N reported against 170.7 N converged, 5.1% low.** For anyone sizing a
cable that is an unconservative error.

**Recommended fixes**, in order:

1. **Report the convergence status.** Add a note to the diagram when the
   cable is at the 8-edge cap: "peak tension under-resolved at this mesh".
   ~1 hour, no risk.
2. **Add the V band.** The diagram legend already reads
   `T = cable tension · H = horizontal thrust · V = vertical shear`, but **V
   is never plotted** — `_diagram_series` computes it and `_draw_diagrams`
   ignores it. Either plot it or drop it from the legend; plotting it is
   better and is ~30 minutes.
3. **Use B2 above** (single-cable refined re-solve) for the reported maxima.

---

## PART 3 — PLAN: web-wide T / H / V diagrams drawn into the geometry

Everything below is a plan. Nothing is implemented.

### 3.1 What it should look like

Value curves offset **perpendicular to the funicular's own local tangent**,
so the diagram follows the deformed cable rather than a straight baseline —
the technique `arch_app._draw_curve_diagram` already uses. Its core is
worth copying almost verbatim:

```python
def offset_pts(values):
    pts = []
    for x, y, cc, ss, v in zip(xs_, ys_, tc, ts, values):
        nx_, ny_ = -ss, cc                 # unit normal to the local tangent
        off = (v / maxabs) * offset_scale
        pts.append((x + nx_*off, y + ny_*off))
    return pts
```

The arch version also draws **value gridlines that follow the arch's own
shape** — the centreline offset by a constant "nice" tick — which is what
makes a curved-baseline diagram readable. Copy that too.

### 3.2 Workflow

**Step 0 — baseline (30 min).** Record `pytest -q` (currently 116 passed),
screenshot both built-in examples, save the T/H numbers from §2. Every later
step is checked against these.

**Step 1 — the toggle and an empty overlay (1 h).**
- Add `self.show_web_diagrams = tk.BooleanVar(value=False)` beside
  `show_diagrams`. **Off by default**, as you asked.
- Add a `Web diagrams` checkbutton in the same `views` group, command
  `self._draw`.
- Add `_draw_web_diagrams(self, canvas)` called from `_draw()` **after**
  `_draw_solver_result` and **before** the node markers, guarded by
  `if self.show_web_diagrams.get() and result_pos and self._solver_meta:`.
- Leave the body empty. **Verify:** toggling changes nothing, suite still
  116, both examples pixel-identical with it off.

*This step exists on its own so that "the feature is off" is proven before
any drawing code is written.*

**Step 2 — one quantity, one cable (2 h).**
- Reuse `_diagram_series(cid)` — it already returns `(s0, s1, T, H, V)` per
  edge and is verified in §2. **Do not write a second derivation.**
- Build the polyline of solved positions per drawn group, exactly as
  `_draw_solver_result` does (reuse its `by_cable` / group-splitting logic;
  factor it out rather than duplicating it — MANIFESTO §3j).
- For each edge, compute the unit normal from its own solved direction and
  offset by `(v / vmax) * offset_scale`, `offset_scale ≈ 0.25 × the web's
  bounding-box diagonal`.
- Draw tension only, one cable, filled quads between the funicular and the
  offset curve, as the arch does.
- **Verify:** the peak offset lands where §2 says Tmax is; the diagram is
  zero-width where T ≈ 0.

**Step 3 — all cables, one shared scale (1 h).**
- One `vmax` across the whole web, or the diagram lies about relative
  magnitude between cables. Show the scale in a caption.
- **Verify:** on the Example, C1's band is visibly larger than C3's in the
  same ratio as their tensions (78.5 vs 26.6).

**Step 4 — H and V, selectable (1–2 h).**
- A radio group `T / H / V`, or three checkbuttons with distinct colours.
  Reuse `CT` for tension, and the Cable tab's `CTHH` / `CTHV` greens and
  purples for H and V so the two tabs read alike.
- **Verify against §2's numbers**: H must come out visually constant along a
  vertically-loaded cable. That is a free correctness check, and the reason
  to do H before V.

**Step 5 — gridlines and labels (1 h).** Port the arch's shape-following
tick lines and its `max ±` caption.

**Step 6 — the antifunicular (30 min).** Decide explicitly whether the
overlay also draws on the mirrored web. Recommendation: **no** for the first
version — it doubles the clutter and the mirrored web already carries loads.
Write the decision down either way.

### 3.3 Risks

- **Clutter.** A web with 6 cables and 3 quantities is unreadable. Mitigate
  with one quantity at a time and a per-cable filter reusing the existing
  `diag_combo`.
- **Scale coupling.** `offset_scale` must derive from the *web's* bounding
  box, not the canvas, or it changes with zoom. The arch code gets this right
  — follow it.
- **Do not touch** `_draw_solver_result`'s existing output. Add a sibling
  method; that keeps the toggle genuinely additive.

---

## PART 4 — PLAN: equilibrium force vectors at supports and nodes

### 4.1 The data already exists

- **Supports:** `CableWebResult.node_reaction(sid)` returns `(Rx, Ry)`.
  Verified in §2 — reactions summed to exactly the applied load in both cases.
- **Junctions:** the resultant of the incident edge tensions plus any applied
  nodal load. At equilibrium this is zero, which is itself the useful display:
  drawing the individual member forces at a junction shows *how* they cancel.

**No new solver output is needed.** Same principle as the tension diagram.

### 4.2 Reference implementation to copy

`cable_app._draw_thrust_vectors` is almost exactly this feature, one tab
over: horizontal / vertical / resultant arrows, one shared force→length
scale set by the largest resultant, colours `CTHH` / `CTHV` / `CTHR`. Copy
its structure and its scale convention so the two tabs look like one product.

### 4.3 Workflow

**Step 1 — toggle first, again (30 min).** `self.show_force_vectors =
tk.BooleanVar(value=False)`, a checkbutton, and an empty
`_draw_force_vectors(canvas, positions)` called from `_draw()` after the
nodes. **Verify off-by-default before writing any drawing.**

**Step 2 — support reactions (1–2 h).**
- For each support, get `(Rx, Ry)` via `_solver_meta['node_map']`.
- One shared scale: `force_scale = 0.18 * web_diagonal / max_resultant`.
- Draw H, V and resultant arrows, plus a value label on the resultant.
- **Verify numerically, not visually:** assert ΣR + ΣP ≈ 0 in a test. §2's
  cross-check is the template — that is the property that makes this feature
  worth having, so it should be the test.

**Step 3 — junction equilibrium (2–3 h).**
- At each free node, draw one arrow per incident solver edge, along that
  edge's own solved direction, magnitude = its tension.
- Add the applied nodal load as a fourth arrow in `LOAD` colour.
- **Verify:** their vector sum is zero to solver tolerance — again, as a test.
- **Watch for:** a junction where 5 cables meet becomes an unreadable star.
  Consider drawing junction vectors only for the *selected* node.

**Step 4 — scale control (30 min).** The Cable tab exposes a vector count;
here a scale slider is more useful, since magnitudes vary hugely across a web.

**Step 5 — antifunicular (30 min).** Reactions mirror with the geometry. The
same decision as §3.6 — recommendation: mirror them, since a reaction is a
property of the shape, unlike an applied load.

### 4.4 Suggested order across both features

1. **Part 2 fix 2** — plot V, or drop it from the legend. 30 minutes, removes
   an inconsistency you would hit immediately while checking the new diagrams.
2. **Part 4** (force vectors) before Part 3 (web diagrams) — it is smaller,
   has a crisp correctness test (ΣF = 0), and builds the shared
   `force_scale` / arrow helpers that Part 3 then reuses.
3. **Part 3** in the six steps above.
4. **Part 1 B1** (analytic parabola between solved nodes) last — it is the
   most cosmetic, and by then the diagrams will have told you whether the
   8-edge mesh is actually limiting you.

---

## PART 5 — Answers received, and what they change

### 5.1 Pic 1 has `w = 1` — so it IS a catenary, and the cause is facet count

Confirmed: that cable carries self-weight, so its stretch genuinely should be
a smooth catenary. The faceting is §1.2's cause, and measuring a cable built
to match pic 1 (24 m over a 20 m span, `w = 1 N/m`, junction at s = 5, plus a
tie) shows exactly why it looks so coarse:

| drawn group | solved points | chord | sag from chord | **straight facets** |
|---|---|---|---|---|
| before the junction | 3 | 181 px | 3.0 px | **2** |
| main span | 9 | 638 px | 113.0 px | 8 |
| the tie | 6 | 228 px | 189.1 px | **5** |

The mesh is allocated **per cable** (`_solver_breakpoints` gave 9 edges for
the 24 m cable), but the *drawing* splits into groups at every junction and
point load — so a short sub-group inherits only its share, and can end up
with **as few as 2 facets across real curvature**. The tie is the worst case
here: a 189 px sag drawn with 5 chords. That is what you zoomed into.

This changes the recommendation. Before doing B1 or B2, do:

### B0 — guarantee a minimum facet count per drawn GROUP (recommended first)

Today the breakpoint budget is spread uniformly along the whole cable and
then chopped up by whatever hard points exist. Instead, ensure every
*segment between hard points* gets a minimum number of subdivisions of its
own.

**Workflow**

1. In `_solver_breakpoints`, after the hard points (attachments, load
   positions) are collected, walk consecutive pairs and add interior points
   to any gap that has fewer than `n_min` subdivisions. Start with
   `n_min = 4`.
2. Keep the existing even-parity rule from §3v for spans carrying
   distributed load — apply it **per segment** now, not per cable.
3. **Measure before committing** (MANIFESTO §3k): time Analyze on both
   built-in examples and on a junction-heavy web, and record dof. The
   expected cost is small — pic 1's short group goes from 2 facets to 4,
   i.e. +2 edges — but "expected" is not "measured".
4. **Verify** with the existing `tests/tools/plateau_sweep.py` plus a new
   assertion that no drawn group has fewer than `n_min` facets when it
   carries curvature.

This is cheap precisely because it adds nodes only where they are missing,
rather than everywhere. B1 (analytic parabola between solved nodes) becomes
optional polish afterwards; B2 (single-cable refined re-solve) stays the
route for accurate reported maxima.

### 5.2 Force vectors — specification settled

Per your answer:

- **All supports** get reaction vectors, always (when the toggle is on).
- **Only the selected joint** gets its member-force star — which also solves
  the legibility problem I flagged.
- **Vectors scale with zoom.** This is a real design decision, not a detail:
  it means the arrow length is computed in **world** units and transformed
  through `zc.w2s` like any other geometry, rather than being a fixed pixel
  length. Zooming in then magnifies the arrows with the structure.

Concretely, in `_draw_force_vectors`:

```python
# world-space arrow: scales with zoom because w2s does the scaling
force_scale = 0.18 * web_diagonal_world / max_resultant   # world px per N
tipx, tipy = ox_world + Fx * force_scale, oy_world + Fy * force_scale
sx0, sy0 = self.zc.w2s(ox_world, oy_world)
sx1, sy1 = self.zc.w2s(tipx, tipy)
```

Note the arrow **head** should stay a constant pixel size (Tk's `arrowshape`
is in pixels) or it will become grotesque at high zoom — so scale the shaft
in world units and leave the head in screen units. Worth a step of its own:

4a. **Zoom behaviour.** Verify at 3 zoom levels that shaft length tracks the
    structure and the head stays legible. Add a scale slider so a web with
    one dominant reaction can still show the small ones.

### 5.3 NEW FEATURE — default cable self-weight 1 kN/m

Requested: every cable should default to 1 kN/m instead of 0.

**This is well-motivated, and the data supports it more strongly than you may
realise.** A cable with no self-weight and no applied load has no unique
equilibrium, so it cannot solve at all. Measured convergence across
self-weight values:

| model | w=0 | w=1 | w=10 | w=50 | w=100 | w=250 | w=500 | w=1000 |
|---|---|---|---|---|---|---|---|---|
| built-in Example (2:1 slack, has loads) | OK | OK | OK | FAIL | FAIL | FAIL | FAIL | FAIL |
| built-in Picture test | OK | OK | OK | OK | OK | OK | OK | OK |
| single cable 20/22 m, **no loads** | **FAIL** | OK | OK | OK | OK | OK | OK | OK |
| single cable 10/20 m, **no loads** | **FAIL** | OK | OK | OK | OK | OK | OK | OK |
| 3-cable web, **no loads** | **FAIL** | OK | OK | OK | OK | OK | OK | OK |

Read the bottom three rows: **today, drawing a cable and pressing Analyze
without adding a load fails.** Any nonzero self-weight fixes that. So the
change genuinely improves first-use behaviour.

**But 1 kN/m specifically needs care**, for two measured reasons:

1. **Magnitude.** At 1 kN/m a 20 m cable weighs 20 000 N. The built-in
   Example's point load is 100 N. Self-weight would dominate applied loads by
   ~200×, so every result in a tutorial-scale model becomes a self-weight
   result. On the Picture Test, forcing w = 1000 took Tmax from 199.9 N to
   **20 100 N**.
2. **Convergence at high w on very slack geometry.** The Example's 2:1-slack
   four-support web fails above w ≈ 10. It is an extreme diagnostic shape,
   not a realistic structure, but it is also this project's own regression
   case.

**Both are avoidable**, because the built-in examples can pin their own
values — `_load_example` already sets `w = 0.0` explicitly on all three
cables, so it is immune to a default change. `_load_picture_example` does
**not**, so it would inherit the new default and every reference number in it
would move.

**Workflow**

1. **Pin the examples first, as a separate change.** Add explicit
   `c1['w'] = c2['w'] = c3['w'] = 0.0` to `_load_picture_example`, matching
   what `_load_example` already does.
   **Verify:** both examples' residuals and tensions unchanged, suite green.
   *Doing this first means the default change cannot move any regression
   number.*
2. **Change the default.** `_new_cable`'s `'w': 0.0` → `'w': 1000.0`.
   **Verify:** draw a single cable, no loads, press Analyze — it now
   converges where it previously failed. That is the acceptance test for this
   feature and it should be written as one.
3. **Resolve the units presentation.** The inspector field is labelled
   **`Self-weight (N/m)`** and the solver takes N/m, so 1 kN/m is `1000.0` in
   that box. Two options:
   - *Recommended, non-breaking:* keep the field in N/m, default it to
     1000.0, and add a live read-out beside it — "= 1.000 kN/m". Nothing
     stored changes, so every existing model and every Excel workbook keeps
     its meaning.
   - *Alternative:* relabel the field to kN/m and divide on display. This
     reads better but **silently reinterprets every existing model by 1000×**
     unless a migration is written. Only do this with an explicit conversion
     on load and a version marker in the Excel export.
   Note you set pic 1's cable to `1`, which under the current label is
   **1 N/m — a thousandth of what you are asking for as the default.** That
   ambiguity is the reason to do this step at all.
4. **Check the knock-on to meshing.** `w > 0` flips `needs_mesh` and the
   §3v even-parity rule for *every* cable, so every new model gets slightly
   more dof. Measured on the Picture Test with w applied: 24 → 26 edges,
   66 → 72 dof, Analyze 1.92 s → 1.85 s — no worse, but confirm on a larger
   web before shipping.
5. **Excel is safe.** Verified: the export writes a self-weight column and
   the import reads it, so existing workbooks keep their own values and do
   not silently pick up the new default.

**Recommendation on the number itself.** Ship the default as requested
(1 kN/m) *after* step 1, since real cables do weigh roughly that and the
examples are then immune. But consider exposing it as a preference, because
a user experimenting at tutorial scale with 100 N loads will find every
result dominated by self-weight. A middle path — default 1 kN/m, with the
inspector showing self-weight total alongside applied total — makes the
dominance visible instead of surprising.

### 5.4 Revised order of work

1. **Pin `_load_picture_example`'s self-weight** (§5.3 step 1). 15 minutes,
   protects every later measurement.
2. **Plot the V band, or drop it from the legend** (§2.4). 30 minutes.
3. **Default self-weight 1 kN/m** (§5.3 steps 2–4).
4. **B0 — minimum facets per drawn group** (§5.1). This is now the highest-value
   geometry fix and is cheap.
5. **Force vectors** (Part 4, as revised in §5.2).
6. **Web-wide diagrams** (Part 3).
7. **B1 / B2** last, if B0 has not already made them unnecessary.

---

## Still open — one question

**Web diagrams: how many quantities on screen at once?**

I asked this badly last time. Concretely, once the overlay exists you will
have three quantities to draw along each cable — tension T, horizontal thrust
H, vertical component V — and a web may have six or more cables. Two ways to
present that:

- **(a) One at a time.** A radio group `T / H / V` above the canvas. Picking
  one draws that quantity as a band along *every* cable. Clean, always
  legible, but you compare quantities by toggling.
- **(b) All three at once.** Three coloured bands offset along each cable
  simultaneously. Everything visible together, but on a six-cable web that is
  18 overlapping bands plus the structure itself.

I recommend **(a)**, with the existing per-cable selector kept so you can
also narrow to one member. Tell me which you want and I will write the step
list to match — it changes step 4 of Part 3 and nothing else.


---

## PART 6 — The UDL: the lumping is exact, the meshing is not

Reported: the UDL distribution looks stepped/discrete and is suspected of
causing a wobble or polygonised shape on the Example's C2.

### 6.1 The lumping is exactly correct

Measured directly on the Example's C2 (UDL-B, 10 N/m over 20 m, junction at
s = 5):

```
breakpoints: 0.00 2.50 5.00 7.50 10.00 12.50 15.00 17.50 20.00   UNIFORM
interior nodal loads: min -25.0000  max -25.0000  spread 0.0000 N
expected q*ds = 10.0000 * 2.5000  =  25.0000 N
```

Every interior node receives exactly `q·Δs`; the two end nodes receive
exactly half. That is textbook consistent (trapezoidal) lumping, and the
spread across nodes is **0.0000 N**. There is no defect in the UDL
distribution.

### 6.2 There is no wobble in the solved data either

Turn angles at C2's interior nodes:

```
node 1 (s= 2.50):  +10.61 deg
node 2 (s= 5.00):   -1.19 deg   <- junction: a real kink, correctly there
node 3 (s= 7.50):  +28.12 deg
node 4 (s=10.00):  +62.94 deg
node 5 (s=12.50):  +31.90 deg
node 6 (s=15.00):  +10.97 deg
node 7 (s=17.50):   +5.12 deg
```

Away from the junction all six turns have the **same sign** — the polygon is
convex. Nothing oscillates.

### 6.3 What you are actually seeing: curvature concentration

Look at the spread: **5.12° to 62.94°, a ratio of 12.3.** The mesh is uniform
in **arc length**, but a catenary's curvature is concentrated at its vertex.
So almost all of the turning piles into the one or two elements at the low
point, and that single ~63° corner is what the eye reads as "polygonised" —
two nearly-straight flanks meeting at a sharp bend.

Confirmed on a plain UDL cable at the Example's 2:1 slack ratio:

| elements | max turn | min turn | ratio | total turn | Analyze |
|---|---|---|---|---|---|
| 8 | 57.09° | 5.47° | 10.4 | 150.6° | 0.14 s |
| 12 | 39.92° | 2.96° | 13.5 | 151.9° | 0.12 s |
| 16 | 30.46° | 2.02° | 15.1 | 152.5° | 0.13 s |
| 24 | 20.57° | 1.23° | 16.7 | 153.1° | 0.92 s |
| 32 | 15.50° | 0.88° | 17.6 | 153.3° | 0.41 s |
| 48 | 10.37° | 0.56° | 18.4 | 153.6° | **15.93 s** |

Two things to read here. The **total** turning barely moves (150.6° → 153.6°)
— it is a property of the shape, and the solve is consistent. But the
**largest single corner** falls from 57° to 10°, and the **ratio gets worse**
(10.4 → 18.4): refining a uniform mesh shrinks every corner but concentrates
the distribution even more. Uniform refinement is treating the symptom.

### 6.4 A fix I tried, and why I reverted it

The obvious display-only fix: between two solved nodes, bow the chord by the
sag the load implies, `q·Δx²/(8H)`, with q and H both already known. Offline
against a 32-element reference it looked excellent:

```
chords between solved nodes (today)   max dev 5.04 px   max corner 57.09 deg
+ analytic sag per element            max dev 2.99 px   max corner 10.29 deg
```

**Shipped, it made the drawing worse** — max corner 62.9° → **97.9°**, and
direction reversals 1 → 3. Cause, once measured: a per-element bow returns to
the chord at *both* ends, so it leaves each node at an angle instead of
smoothing through it. For a 2.5 m element with 0.12 m of sag that is 10.8° at
each end, and the two adjacent bows tilt in opposite senses — so it **adds**
roughly 21° of kink at every shared node, on top of the turn already there.
My offline test missed it because that formula omitted the arc-to-horizontal
correction and so under-corrected; the correct magnitude made the artefact
worse, not better.

Reverted in full. Suite back to 118 passed, C2's turn angles back to the
values in §6.2. **I was not going to ship a second half-right fix in the same
area** — §3w exists because of the first one.

### 6.5 The two routes that would actually work

**Route 1 — display-only, correct formulation.** The mistake was doing it per
element. A loaded stretch is *one* continuous curve: integrate `y'' = q/H`
across the whole drawn group in a single pass, anchored at the group's
endpoints, rather than bowing each chord independently. Smooth by
construction, since there are no per-element seams to kink at.
*Effort ~3 h. Risk: moderate — needs care where H varies along the group and
where the group is steep. Verify against a 32-element solve, as §6.4 did, and
additionally assert the drawn curve adds no direction reversals (the test
from §1.1 already does this).*

**Route 2 — grade the mesh by curvature. My recommendation.** Instead of
spacing breakpoints uniformly in s, place them densely where the cable turns
fastest. With the total turning fixed at ~151°, a perfectly graded 8-element
mesh gives ~19° per corner instead of 57° — **a 3× improvement at zero extra
degrees of freedom**, which uniform refinement cannot match at any cost shown
in §6.3's table.

*Workflow:*
1. Solve once with today's uniform mesh (cheap, already happens).
2. From that solution, compute the turning per element and re-place the
   breakpoints so each element carries roughly equal turning.
3. Re-solve on the graded mesh. Two solves instead of one — for the Picture
   Test that is ~2.4 s, acceptable.
4. **Verify:** max corner per group, before and after, on both built-in
   examples and a junction-heavy web; residuals unchanged in magnitude; dof
   unchanged.
5. **Watch for:** the grading must not move a breakpoint that a load
   position or junction pins. Those stay fixed; only the free interior ones
   move.

~~Route 2 also improves the **accuracy** problem from §2.4 (peak tension
under-reported by 5.1%), because it puts elements where the tension gradient
is steepest.~~ **CORRECTED — this was wrong. Route 2 is now built, and it
makes the reported peak tension *worse* (−4.71% → −6.20%), because it moves
elements AWAY from the supports where tension peaks. See §7.4 for the
measurements and for the exact fix, which lives in the reporting layer.**
Route 1 only improves appearance. If you only want one, take Route 2 —
that recommendation stands on the geometry alone.

---

## PART 7 — Route 2 is BUILT (and it needed a second fix I did not expect)

Status: **shipped**, on by default, behind a toggle. 124 tests pass.

### 7.1 What was built

`_graded_breakpoints` / `_apply_mesh_grading` in `apps/cable_web/cable_web_app.py`.
Analyze now runs **twice**:

1. **Pass 1** solves today's uniform mesh — unchanged, same cost.
2. On the main thread (never in the worker — it reads `self.nodes`), the solved
   polyline becomes a per-element measure: a blend of arc length and turning.
   Each cable's *free* interior breakpoints are re-placed at equal increments
   of it.
3. **Pass 2** solves the re-meshed model and is what you see.

Cable ends, junctions and load boundaries are **pinned** and never move, and
the free-point count inside every pinned interval is preserved exactly — so the
graded model has **identical degrees of freedom**. Nothing got bigger; the
nodes moved to where the cable actually curves.

New UI: a **"Graded mesh"** checkbox beside *Diagrams*, on by default, with a
tooltip explaining the cost. Toggling it says so in the status line; it applies
on the next Analyze.

### 7.2 The part I did not expect, and you should know about

The turn-angle metric said the job was done. **A screenshot of the same case
said the opposite** — the graded curve had a flat run and a visible corner at
the vertex, *worse* than the uniform mesh it replaced.

Both were true, and the reason is a second bug that grading exposed rather than
caused. `_smooth_polyline` — the display interpolator between the solved
polyline and the canvas — was **uniform-parameterised**: it ran its cubic
parameter 0→1 on every segment regardless of that segment's length, with
tangents `0.5*(p[i+1]-p[i-1])`. That is correct **only if every segment is the
same length**. It always had been. Grading makes them deliberately unequal —
I measured spacing ratios up to **13.28:1** — so the tangents came out wildly
out of scale.

Measured against the exact catenary, in screen pixels:

| | solved nodes | drawn curve |
|---|---|---|
| 20/26 m cable, uniform mesh | 2.02 px | 2.02 px |
| 20/26 m cable, graded (first attempt) | **1.42 px** | **3.84 px** |

The nodes got better and the picture got worse, in the same run. This is the
same class of problem as §1.1 — and it is why measuring the *solver* output is
not enough when the complaint is about the *drawing*.

**Fix 1 — chord-length parameterisation.** Express each tangent per unit chord
and scale it by the segment's own chord. It **reduces exactly to the old
formula when the segments are equal**, so the grading-off path is provably
unchanged (a test asserts agreement to 1e-9). Drawn deviation 3.84 → 2.43 px.

**Fix 2 — re-tune the blend on the right metric.** The turning weight had been
picked at 0.90 against the solved polyline. Re-swept against drawn deviation
from closed form, over a family of slackness:

| turning weight | worst drawn dev | mean |
|---|---|---|
| off (uniform) | 13.07 px | 4.93 |
| 0.25 | 7.16 | 3.08 |
| 0.50 | 3.94 | 2.17 |
| **0.65 (shipped)** | **2.73** | **1.87** |
| 0.75 | 3.10 | 2.12 |
| 0.90 | 5.44 | 2.89 |

0.65 is also *faster* (the Picture test's second pass went 5.9 s → 1.2 s) and
better on that case's turning, because over-concentrating at the vertex starves
the flanks and makes the system harder to solve as well as harder to draw.

### 7.3 Final measured result

Largest turn at a **free** interior node (kinks at point loads and junctions are
physically real, are excluded, and grading neither can nor should remove them).
`dof` identical in every row:

| case | uniform | graded | |
|---|---|---|---|
| built-in **Example** (your cable 2) | 62.94° | **35.58°** | 1.8× |
| built-in Picture test | 120.31° | **80.89°** | 1.5× |
| plain UDL, 10 m span / 20 m cable | 57.09° | **32.25°** | 1.8× |
| self-weight, 20 m span / 26 m cable | 23.72° | **17.25°** | 1.4× |
| self-weight web + junction | 34.20° | **28.71°** | 1.2× |

And the metric that matches your eye — how far the **drawn** curve sits from
the exact catenary:

| cable | uniform | graded |
|---|---|---|
| 20 m span / 22 m arc (shallow) | 0.98 px | 1.34 px |
| 20 m span / 26 m arc | 2.02 px | **1.81 px** |
| 10 m span / 20 m arc (very slack) | 7.93 px | **2.31 px** |

The shallow case is slightly worse — 0.36 px, well under a line width — because
a shallow catenary has nearly uniform curvature and a uniform mesh is already
close to optimal there. The slack cases, which are the ones that looked
polygonal, improve by 3–10 px. That is the trade the 0.65 sweep chose, with
eyes open.

Convergence improved too: the Picture test's residual went 1.98e-10 → 4.89e-15.

### 7.4 The cost

A second solve: **+0.1 s** on most cases, **+0.7 s** on the built-in Picture
test. That is why it is a toggle, and why the tooltip says to turn it off if
Analyze feels slow.

### 7.5 It made §2.4's peak tension worse — read this before sizing a cable

Grading pulls nodes toward the vertex, so the elements **at the supports get
longer** — and the supports are exactly where peak tension lives. Measured on
the 20 m span / 22 m arc UDL cable against a 64-edge reference **of the same
model**:

| mesh | reported Tmax | error |
|---|---|---|
| 64 edges (reference) | 169.94 N | — |
| 8 uniform | 161.95 N | −4.71% |
| 8 **graded** | 159.40 N | **−6.20%** |

So §6.5's claim that *"Route 2 also improves the accuracy problem from §2.4"*
was **wrong, and it is corrected here.** It does the opposite. The solved answer
is not worse — H moves 0.16% and the residual improves — but the *reported peak*
is a coarser sample of it.

I built and swept two mitigations before believing either. **Both are strict
trade-offs with no sweet spot, so neither shipped** (measured at the earlier
0.90 weight):

| variant | Tmax error | Example max turn |
|---|---|---|
| uniform (grading off) | −4.71% | 62.94° |
| graded, no mitigation | −6.76% | **33.10°** |
| + element growth capped at 1.35× | −6.28% | 56.24° |
| + growth capped at 1.15× | −5.38% | 60.19° |
| + tension-gradient term, weight 0.30 | −5.90% | 39.15° |
| + tension-gradient term, weight 0.80 | −5.01% | 66.10° |

Every row buys accuracy back by surrendering at least as much smoothing. Both
knobs were removed from the shipped code rather than left in at a neutral
default — a dead parameter invites someone to turn it on later without the
sweep.

**The mitigation belongs in a different layer, and it is exact.** At a cable end
the vertical component *is* the support reaction, so

```
T_end = hypot(H, V_reaction)
```

On the graded run above: `hypot(130.45, 110.0) = 170.64 N` — **+0.39%** against
the 169.94 N reference. Seventeen times better than either mesh's edge value,
and it makes the mesh question irrelevant for the number you read off the
diagram. **This is now the recommended next change** and it supersedes §2.4's
item 3 (single-cable refined re-solve), which is far more expensive for a worse
answer. ~1–2 h, contained in `_diagram_series`.

Until then: if you are sizing a cable, either turn **Graded mesh off** (−4.71%
instead of −6.20%) or read the peak from a refined run.

### 7.6 One metric had to be redefined mid-investigation

The first turn-angle measurements showed grading doing almost nothing. The
metric was counting **every** interior node, including the genuine kinks at
point loads and junctions. Those are structure, not discretisation; grading
cannot remove them and must not try. Excluding pinned nodes was not moving the
goalposts, it was measuring the right thing — and once excluded, all five cases
improved. If you re-measure this yourself, exclude them too or you will conclude
the feature does nothing.

### 7.7 Tests added

In `tests/test_cable_web_rendering_2026_09_05.py`:

- `test_graded_mesh_evens_out_the_turning_at_the_same_dof` — the point of the
  feature, asserted as *same dof, smaller max turn, smaller max/min ratio*.
- `test_graded_mesh_draws_closer_to_the_true_catenary` — the user-facing claim,
  against closed form rather than another discretisation.
- `test_smoothing_is_unchanged_on_an_evenly_spaced_polyline` — the
  parameterisation change is inert on a uniform mesh, to 1e-9.
- `test_grading_never_moves_a_pinned_breakpoint` — on a twin-tie web with
  junctions **and** a point load, so pinned points of every kind exist.
- `test_grading_is_cleared_when_the_model_changes`.
- `test_both_examples_still_converge_with_grading`.

If the graded mesh fails to converge, the pass-1 result is genuinely converged
and is what you see, with the status line saying so. A new feature must not be
able to turn a working answer into a failure.
