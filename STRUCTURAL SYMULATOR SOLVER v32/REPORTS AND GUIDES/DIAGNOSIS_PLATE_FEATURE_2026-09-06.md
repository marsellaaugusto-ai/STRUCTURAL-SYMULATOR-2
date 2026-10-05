# Plate feature — feasibility diagnosis, 2026-09-06

**Question asked:** can the Truss / Vierendeel tab gain a feature that joins
nodes and rods with a *plate*, to reinforce a polygonal section of the
structure? Is it too big a change? Is the math engine going to be a problem?

**Method:** MANIFESTO §2 — the numbers below come from running the real
solver and the real widgets, not from reading the code and reasoning about
what it should do. No code was changed for this report.

---

## 0. Short answers

| question | answer |
|---|---|
| Would I recommend it? | **Yes — but only two of the three things "plate" can mean.** |
| Is it too big a change? | **Not if scoped to a shear panel + gusset. Yes, if scoped to a stress field.** |
| Is the math engine a problem? | **The element math is not. Two other things are — see §3 and §4.** |
| Does it threaten the verified solver? | **No, if added as a new element type. `analyze()` is structured for it.** |

The single biggest risk is **not** the plate stiffness matrix. It is that a
plate has no rotational degree of freedom, so *how you attach it* decides
whether the answer is right (§4). The second biggest is a residual-tolerance
gate in shared code that already rejects valid models at ~600 DOF, which is
the range a plate feature pushes straight into (§3.2).

---

## 1. "Plate" means three different features

These are not variations of one thing. They need different data, different
math, and different output, and it is worth being explicit about which one is
wanted before any code is written.

### P-1 · Gusset plate at a joint — *connection design*
A steel plate at one node that the members meeting there are welded or bolted
to. It does **not** change the global analysis. Its job is to answer "how
thick, how big, how much weld".

### P-2 · Infill / shear panel — *a plate filling the bay*
A plate welded into a Vierendeel panel or a truss bay so the panel carries
shear as a membrane instead of by frame action. This **does** change the
global analysis: the bay gets much stiffer, moments in the surrounding
members drop, and the load path changes.

### P-3 · Full membrane finite elements — *a stress field*
Mesh the polygon with plane-stress elements and report σx, σy, τxy, principal
and von Mises stress as a contour. This is P-2 plus a small FE package.

**"Join nodes and rods with a plate in order to reinforce that polygon
section" reads as P-2**, with P-1 as the detailing that follows. That is the
recommendation in §6.

---

## 2. What is already in place (this is the good news)

The tab is unusually well set up for P-1, and reasonably set up for P-2.

**For P-1, the data already exists and is already computed.**
`truss_math.compute_node_force_vectors()` opens with:

> *"For every node, compute the individual force vector that each connected
> rod applies to that node — this is exactly the set of forces that must be
> resisted by a welded gusset/node plate."*

Its output — per-rod Fx, Fy, magnitude and angle at each joint, in a
consistent y-up frame — is precisely a gusset plate's design input, and the
**Node Force Vectors** report window already draws the free-body diagram.

**The design-code layer for the checks also already exists**, written for
another tab: `apps/perforated_beam/cirsoc_301.py` provides
`weld_strength_per_mm`, `leg_for_shear_flow`, `min_fillet_leg`,
`max_fillet_leg`, `fillet_throat`, `shear_strength` and `stress_check`,
each transcribed with its CIRSOC 301-2018 clause. A gusset plate check is
mostly a matter of calling these with the vectors above.

**The solver is structured to accept a new element type.** `analyze()`
assembles per-rod in one loop; a `for plate in plates:` loop alongside it
follows the same shape. Better, its DOF map is already adaptive:

```python
needs_theta = [False] * N
for rod in rods:
    if rod.get('conn', 'pin') == 'rigid':
        needs_theta[rod['a']] = True
        ...
dof_of[i] = (ux_i, uy_i, th_i)   # th_i is None where not needed
```

A membrane plate needs only `ux`/`uy`, which every node already has. It adds
no new DOF *kind* — it only adds stiffness to existing ones.

**Persistence is schema-tolerant.** `truss_reports.import_excel_model` reads
the Model sheet by named sections (`[NODES]`, `[RODS]`, …) via a generic
`read_table`, and a missing section yields an empty list. A `[PLATES]`
section is additive and backward-compatible in both directions.

**Joint equilibrium is now pinned by a test that needs no reference values.**
`tests/test_truss_math.py::test_warren_example_satisfies_method_of_joints_at_every_free_node`
asserts that the forces meeting at every free node cancel. If a plate is added
to the solver but *not* to `compute_node_force_vectors`, that test fails
immediately. This is the cheapest possible guard against the most likely
silent error in this feature, and it already exists.

---

## 3. Is the math engine a problem? — measured

### 3.1 Speed: not a problem in the useful range

`common._beam_gauss_solve` is `numpy.linalg.solve` (LAPACK LU), not
interpreted elimination. Assembly and reaction recovery are pure Python, and
they are what costs. Measured on an N-bay Warren truss:

| bays | nodes | DOF | `analyze()` | of which LAPACK | Python |
|---|---|---|---|---|---|
| 20 | 42 | 126 (rigid) | 0.055 s | 0.020 s | 0.035 s |
| 50 | 102 | 306 (rigid) | 0.079 s | 0.056 s | 0.023 s |
| 100 | 202 | 404 (pin) | 0.076 s | 0.067 s | 0.010 s |
| 100 | 202 | 606 (rigid) | 0.277 s | 0.154 s | 0.123 s |

A P-2 shear panel adds **no nodes at all** — it borrows the four corner nodes
it already spans. Its cost is one 8×8 block per panel. Even a hundred panels
is free at this scale. **P-2 has no performance problem.**

P-3 is different: meshing means new nodes. A 6×6 mesh in each of ten panels is
~400 new nodes, ~800 new DOF — past the table above, and into §3.2.

### 3.2 The real ceiling: a residual gate that rejects valid models

`_beam_gauss_solve` guards against handing back a meaningless solution:

```python
residual = Anp @ x - bnp
scale = max(1.0, float(np.max(np.abs(bnp))))
if np.max(np.abs(residual)) > 1e-8 * scale:
    return None      # -> "Singular stiffness matrix"
```

The tolerance is scaled by `‖b‖` only, never by `‖K‖`. Stiffness entries here
are `E·A/L` in newtons — order 1e9 — so the residual of a *perfectly good*
solve grows with problem size until it trips the gate. Measured on plain,
stable Warren trusses:

| bays | free DOF | cond(K) | max&#124;residual&#124; | tolerance | verdict |
|---|---|---|---|---|---|
| 100 | 401 | 3.3e+07 | 1.5e-05 | 1.0e-04 | accepted |
| 150 | 601 | 1.7e+08 | 1.1e-04 | 1.0e-04 | **rejected** |
| 200 | 801 | 5.2e+08 | 3.6e-04 | 1.0e-04 | **rejected** |
| 300 | 1201 | 2.6e+09 | 1.8e-03 | 1.0e-04 | **rejected** |

A condition number of 1e8–1e9 is entirely healthy for float64 (~1e16 of
headroom); these solutions are correct. The app reports *"Singular stiffness
matrix – check for mechanisms or floating nodes"* and refuses to analyse them.

This does not produce wrong numbers — it refuses to produce numbers — so it is
a robustness limit, not a correctness bug, and it does not bite today because
current models are small. **It will bite a plate feature**, because P-3 in
particular lands squarely in the 600–1200 DOF band.

The fix is to make the gate relative rather than absolute, e.g.

```python
den = np.linalg.norm(Anp, np.inf) * np.linalg.norm(x, np.inf) + np.linalg.norm(bnp, np.inf)
if np.max(np.abs(residual)) > 1e-10 * max(den, 1.0):
    return None
```

which is the standard backward-error test and stays strict for a genuinely
singular system. **This is shared code — all six tabs call it** — so it wants
its own change and its own verification pass across every tab, not a
drive-by edit inside a plate feature. Flagged as a question in §7.

---

## 4. The deep problem: a plate has no rotational DOF

This is the part most likely to produce a plausible-looking wrong answer, and
it is worth understanding before committing.

A plane-stress (membrane) element — CST, Q4, and the shear panel of P-2 alike
— has only `ux`, `uy` at each node. It has no `θ`. So when a plate is attached
to a Vierendeel frame at its four corner nodes:

* it **does** stiffen the panel against racking — that part is real and
  correct;
* it contributes **nothing** to the joint rotations `θ`, because it has no
  term that touches them.

Physically, corner-attachment models a plate **pinned at four points**. A real
infill plate is welded continuously along the members' flanges for the whole
length of every edge, which is far stiffer and also feeds shear flow into the
members along their length rather than as four point loads.

Consequences to be explicit about:

1. **A corner-attached plate under-predicts the stiffening**, and the error is
   not small or conservative in a predictable direction — it depends on the
   panel aspect ratio.
2. **Getting it right means edge coupling**: the plate's edge nodes must
   coincide with points *along* the members, which means splitting each
   member into sub-elements at those points. That is a meshing job, and it is
   the real cost of P-3 — more than the element math.
3. **P-2 sidesteps this honestly** by not pretending to be a plate at all: it
   models the panel's *shear* contribution as a calibrated equivalent (a shear
   panel element, or the classic equivalent diagonal strut), which is the
   standard idealisation for exactly this situation and is defensible because
   it does not claim a stress field it has not earned.

There is a second, related trap: a plate is thin, so its **out-of-plane
buckling** governs long before its in-plane yield. A shear panel that reports
"τ = 40 MPa, fine" while the real plate has already buckled is worse than no
answer. Any P-2 result needs a plate-buckling check beside it — the
`shear_web_coefficient` / `shear_strength` pair in `cirsoc_301.py` is the
right starting point, since a web panel between stiffeners is the same
problem.

---

## 5. What would have to change, concretely

| area | file / function | P-1 gusset | P-2 shear panel | P-3 stress field |
|---|---|---|---|---|
| model data | `TrussApp.__init__` | `self.plates = []` | same | same + mesh |
| solver | `truss_math.analyze` | — none — | one 8×8 block per panel | element library + mesh + member splitting |
| joint equilibrium | `compute_node_force_vectors` | — none — | **must include plate forces** | same |
| selection | `_on_press`, `_nodes_in_box` | pick a node | pick a closed rod loop | same |
| drawing | `TrussApp._draw` | polygon at joint | hatched panel | stress contour |
| results panel | `_show_sel`, `res_var` | plate utilisation | panel τ + buckling | new diagram mode |
| diagrams | `_draw_diagrams_only` | — none — | — none — | new renderer |
| reports | `_show_node_vectors_report` | extend (data is there) | new section | new report |
| persistence | `truss_reports` export/import | `[PLATES]` section | same | mesh too |
| design code | `perforated_beam/cirsoc_301.py` | **reuse as-is** | reuse + buckling | reuse |

Note the shape of that table: **P-1 touches no solver code at all**, and P-2
touches it in exactly two places. P-3 touches everything.

---

## 6. Recommendation

**Build P-1 and P-2. Do not build P-3 yet.**

1. **P-1 first (small).** It is nearly free: the forces are already computed,
   the free-body diagram is already drawn, and the code checks already exist
   in `cirsoc_301.py`. It carries **zero risk to the verified solver** because
   it does not touch it. It also delivers the thing an engineer actually needs
   day to day — a plate size and a weld leg.

2. **P-2 second (medium).** This is the "reinforce the polygon" behaviour that
   was asked for, at a small fraction of P-3's cost, using the standard
   idealisation. Roughly one new function in `truss_math`, one loop in
   `analyze`, an addition to `compute_node_force_vectors`, a polygon picker,
   and a hatch in `_draw`. The existing method-of-joints test guards the
   riskiest part for free.

3. **P-3 only if the stress field is the actual goal.** It is a different
   product — it turns a member-force calculator into a small FE package. It
   needs the §3.2 fix first, plus meshing, member splitting, edge coupling,
   stress recovery and a contour renderer. Judged against the rest of this
   codebase it is comparable in size to an entire new tab, not to a feature.

**Relative sizes**, taking "delete the dead method" (T-2, 15 min) as the unit:
P-1 ≈ a day; P-2 ≈ several days; P-3 ≈ several weeks. P-1 and P-2 together are
smaller than the Perforated Beam tab that already exists here.

---

## 7. Questions — these change the design, so worth settling first

1. **Which plate?** A gusset at a joint (P-1), an infill panel filling the bay
   (P-2), or a stress field (P-3)? If the mental picture is "a triangle of
   steel where the members meet", that is P-1. If it is "steel sheet filling
   this rectangle so the frame stops racking", that is P-2.

2. **Do you need plate stresses, or just the effect?** "This panel now carries
   140 kN of shear, τ = 62 MPa, utilisation 0.71" (P-2) versus a coloured
   stress contour over the plate (P-3). The first is a few days; the second
   changes what the app is.

3. **How is the plate attached in the real structure?** Welded continuously
   along every member it touches, or bolted/welded at the corners only? This
   is not a detail — per §4 it decides whether a corner-attached model is
   honest or misleading, and it is the difference between P-2 being right and
   P-2 being decorative.

4. **Should the plate change the analysis, or only annotate it?** Some users
   want the plate to stiffen the model; others want the model untouched and
   the plate merely checked against the forces the bare frame produces. These
   are opposite defaults and both are legitimate.

5. **Which polygons?** Only quadrilateral panels (a Vierendeel bay), only
   triangles, or any closed loop of rods the user selects? Quadrilateral-only
   is markedly simpler and covers the Vierendeel case that motivated the ask.

6. **Design code:** should plate and weld checks follow CIRSOC 301-2018, the
   way the Perforated Beam tab does? Reusing `cirsoc_301.py` is nearly free
   and keeps one code layer across the app.

7. **The §3.2 residual gate:** fix it now as its own change, or leave it until
   a model actually hits it? It is shared by all six tabs, so it deserves its
   own verification pass rather than riding along inside a plate feature. It
   is not urgent for P-1 or P-2; it is a prerequisite for P-3.

---

## 8. One thing to decide early, whichever route

Whether a plate is a **member of the model** or an **annotation on it**.

If it is a member, it belongs in `self.plates`, in the Excel schema, in the
solver, in the equilibrium check, and in undo — the same citizenship rods
have. If it is an annotation, it belongs to the reports layer and nothing
else. Retro-fitting the first onto the second is expensive; the reverse is
not. P-1 as described above is deliberately an annotation, and P-2 is
deliberately a member, which is why they are separable and why P-1 can ship
first without constraining P-2.
