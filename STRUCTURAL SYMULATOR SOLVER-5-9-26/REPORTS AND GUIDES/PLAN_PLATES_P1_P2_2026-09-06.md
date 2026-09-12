# Implementation plan — plates P-1 (gusset) and P-2 (shear panel)

Follows `DIAGNOSIS_PLATE_FEATURE_2026-09-06.md`. Decisions taken:

| decision | choice |
|---|---|
| P-2 element | **4-node shear panel**, plate welded continuously all round |
| Polygons | **triangles and quads only** |
| Design code | **CIRSOC 301-2018**, reusing the existing `cirsoc_301.py` |

Nothing here is written yet. Stage 0 is a prerequisite for both; Stage 1
(P-1) and Stage 2 (P-2) are independent of each other after that, and Stage 1
is the cheaper and safer one to do first.

---

## A. The element math, already validated

The P-2 element was prototyped and checked before this plan was written, so
the plan does not rest on an untested formulation.

**Formulation (stressed-skin / Kuhn shear panel).** The plate carries constant
shear flow `q = G·t·γ` and no direct stress. The average engineering shear
strain over the polygon comes exactly from its boundary, by the divergence
theorem, with `u, v` varying linearly along each edge:

```
γ·A = ∮ (u·n_y + v·n_x) ds = Σ_edges [ −ū_i·dx_i + v̄_i·dy_i ]
```

where edge `i` runs node `i → i+1`, `dx_i = x_{i+1} − x_i`, and
`ū_i = (u_i + u_{i+1})/2`. Strain energy `U = ½·G·t·A·γ²`, so

```
K = G·t·|A| · Bᵀ B        B[2i]   = −(dx_{i−1} + dx_i) / (2A)
                          B[2i+1] = +(dy_{i−1} + dy_i) / (2A)
```

a rank-1 8×8 matrix (6×6 for a triangle). Because it is exact on the
boundary it works unchanged for triangles, rectangles, parallelograms and
general simple quadrilaterals — no Jacobian, no quadrature, no shape
functions.

**Validation already run** (prototype, five shapes):

| check | result |
|---|---|
| Rigid-body translation and rotation → γ = 0 | ✅ &#124;γ&#124; ≤ 2.8e-17 on every shape |
| Constant-shear patch `u = k·y` → γ = k exactly | ✅ exact to 1e-12 on every shape |
| Corner forces self-equilibrate (ΣFx, ΣFy, ΣM) | ✅ relative residual ≤ 1.9e-16 |
| Shear cantilever vs `δ = V·L/(G·t·d)` | ✅ converges as 1/EA: 7.6e-3 → 7.6e-5 → 7.8e-7 |
| Panel shear flow vs `q = V/d` | ✅ exact to 1e-6 |

**Two tolerance traps found while validating, to be written into the real
tests rather than rediscovered:**

1. The rigid-body patch test must be judged **relative to ‖K‖**. `Gt` is
   order 6e8, so `K·d` for an exact rigid-body mode is still ~2e-7 in
   absolute terms — pure round-off amplified by stiffness. An absolute
   tolerance here fails a correct element and invites someone to "fix" the
   element.
2. The closed-form cantilever check only matches with **rigid flanges**.
   `δ = V·L/(G·t·d)` assumes the flanges do not stretch; with finite `EA` the
   error is the flange flexibility and decays as 1/EA. The test must either
   use very stiff flanges and a matching tolerance, or assert the 1/EA
   convergence rate. Loosening the tolerance until it passes would hide a
   real element error later.

---

## B. Constraints this plan has to respect

* **`truss_math.py` is the C++ migration boundary** (`MODULAR_ARCHITECTURE.md`):
  plain lists/dicts in, no Tkinter, no Excel, no drawing. The element goes
  there; the CIRSOC checks do **not** — they are design code, not equilibrium.
* **Tabs are independent** and share only root-level `common.py`. So
  `apps/truss/` must not import `apps/perforated_beam/cirsoc_301`. Hence
  Stage 0.
* **Node identity is the list index**, and `_on_delete` renumbers every index
  above a deleted node. Plates store node indices and must be remapped in
  exactly the same pass, or they silently attach to the wrong nodes. (Cable
  Web adopted stable ids specifically to avoid this class of bug — MANIFESTO
  §1.3 — but the Truss tab kept index identity, so plates inherit the hazard.)
* **The Truss tab has no undo.** Nothing to integrate with; also nothing to
  save the user from a mis-click, so plate creation must validate before it
  commits.
* **Unit boundary.** The truss tab works in kN, m, GPa, cm², cm⁴.
  `cirsoc_301.py` works in N, mm, MPa. Every crossing is a conversion, and
  conversions are where this feature is most likely to be silently wrong.
* **`analyze()` must stay backward compatible.** Signature becomes
  `analyze(nodes, rods, loads, supports, plates=None)` — keyword, defaulting
  to `None`, so every existing caller and both existing test modules keep
  working untouched.

---

## C. Data model (both features, one list)

One `self.plates` list, discriminated by `kind`, so persistence, the delete
remap and the draw pass are each written once.

```python
# P-1 — an ANNOTATION. Never reaches analyze().
{'kind': 'gusset', 'node': 3,
 'thickness_mm': 10.0, 'Fy': 235.0, 'Fu': 360.0,
 'Fexx': 480.0, 'weld_lines': 2, 'weld_leg_mm': None,   # None = solve for it
 'outline_m': [...]}          # derived, cached for drawing

# P-2 — a MEMBER of the model. Assembled into K.
{'kind': 'panel', 'nodes': [0, 1, 2, 3],                # ordered loop, 3 or 4
 'thickness_mm': 8.0, 'G_GPa': 80.0, 'E_GPa': 200.0, 'nu': 0.3,
 'Fy': 235.0, 'Fexx': 480.0, 'weld_lines': 2}
```

`kind` is the discriminator throughout. §8 of the diagnosis argued this
annotation/member split is the thing to decide early; it is decided here, and
it is why P-1 can ship without constraining P-2.

---

## Stage 0 — promote the design-code layer *(prerequisite, small)*

**Why:** both stages need CIRSOC checks, and `apps/truss/` importing
`apps/perforated_beam/` would couple two tabs against the stated architecture.

1. Move `apps/perforated_beam/cirsoc_301.py` → root `cirsoc_301.py`, beside
   `common.py`. No content change.
2. Update `apps/perforated_beam/*` imports and `tests/test_cirsoc_301.py`.
3. Add a one-line note to `MODULAR_ARCHITECTURE.md`: the design-code layer is
   shared, like `common.py`, and no tab owns it.

**Verify:** full suite stays at 476 passed. This stage moves a file and
changes import lines; if anything else moves, it has gone wrong.

---

## Stage 1 — P-1, the gusset plate *(no solver change at all)*

The forces are already computed and already drawn. This stage is mostly
geometry, code checks and reporting.

### 1a · `apps/truss/truss_plates.py` (new)
Pure functions, no Tkinter, unit-tested directly. Keeps `truss_math.py` free
of design code.

* `gusset_outline(nodes, rods, node_idx, ...)` — the plate polygon at a
  joint: each connected member gets a landing length, the outline is their
  convex hull plus an edge margin. Returns metres.
* `whitmore_width(...)` — the 30° dispersion width for each member's force,
  clipped to the plate outline. Classic and purely geometric.
* `gusset_checks(vectors, geometry, plate, code=CIRSOC_301)` — returns, per
  member and for the plate as a whole:
  - plate gross-section normal and shear stress → `cirsoc_301.stress_check`
  - Whitmore-section stress for each member → `stress_check`
  - required fillet leg per member → `leg_for_shear_flow`, then bounded by
    `min_fillet_leg` / `max_fillet_leg`, with `min_effective_length`
  - governing utilisation and which check governs

Input is `compute_node_force_vectors()[node]` — already computed, already
correct, already covered by the joint-residual test.

**Explicitly out of scope for v1, and to be said so in the UI**, not left for
the user to assume: **block shear** and **gusset compression buckling**
(Thornton). Both need a bolt pattern / edge distances, which means a
connection-detail editor. Reporting a gusset as "OK" while silently not
checking block shear would be worse than saying it is not checked.

### 1b · UI
* Panel section "Gusset plate (selected node)": thickness, steel grade,
  electrode, weld lines; buttons Add / Remove.
* `_draw`: the outline filled beneath the rods (drawn first so rods stay on
  top), with the governing utilisation as a small label.
* Extend the existing **Node Force Vectors** report with a gusset block:
  the outline sketch, the per-member table, weld legs, and the governing
  check with its CIRSOC clause.

### 1c · Persistence
`[PLATES]` section in the Model sheet. `read_table` already tolerates a
missing section, so old workbooks import unchanged and new ones stay readable
by an older build minus the plates.

### 1d · Verification
* Unit tests on `whitmore_width` and `gusset_outline` against hand geometry.
* Weld leg round-trip: `leg_for_shear_flow(q)` then `weld_strength_per_mm`
  must return ≥ q; and the leg must respect the J.2.4 / J.2.2(b) bounds.
* **A unit-boundary test**: one worked joint computed independently in
  N/mm/MPa, asserted against the kN/m/GPa path. This is the single most
  likely place for a silent factor-of-1000.
* Excel round-trip preserves every gusset field.
* Screenshot of a gusset drawn on the Warren example.

---

## Stage 2 — P-2, the shear panel *(this is the real work)*

### 2a · `truss_math.py` — the element
* `plate_geometry(nodes, plate)` → ordered points in metres, signed area,
  orientation normalised so `A > 0`; returns `None` for a degenerate or
  self-intersecting ("bowtie") loop rather than producing a plausible wrong
  stiffness.
* `plate_stiffness(pts_m, G_Pa, t_m)` → `(K_local, B, A)` per §A.
* In `analyze()`: a `for plate in plates:` loop after the rod loop,
  assembling the 8×8 (or 6×6) block on the `ux`/`uy` DOF the corner nodes
  already have. **No new DOF kind** — `needs_theta` is untouched, so a
  pin-only model with no plates still reduces bit-for-bit to the classic
  truss, which `test_all_pin_model_has_no_bending_anywhere` already guards.
* Result recovery per plate: `γ`, `q = G·t·γ` (kN/m), `τ = q/t` (MPa), the
  four corner force vectors, and the panel area.

### 2b · Joint equilibrium — **the critical integration point**
`compute_node_force_vectors()` currently sums rod contributions only. Plate
corner forces must be added, in the same y-up frame, or the free-body
diagrams become wrong and joint equilibrium stops closing.

This is the most likely place for a silent error, and it is already guarded:
`test_warren_example_satisfies_method_of_joints_at_every_free_node` fails
immediately if a plate is assembled into `K` but omitted here. Extend that
test to a plated model.

`compute_node_moments()` needs no change — a shear panel carries no moment —
but its docstring should say so explicitly, so the next reader does not
assume it was forgotten.

### 2c · Design checks (`truss_plates.py`)
* Shear stress → `stress_check(fun=0, fuv=τ, Fy)` (H.3.5).
* **Plate shear buckling**, which governs long before yield on a thin panel:
  `τ_cr = k_v·π²·E / (12(1−ν²)(b/t)²)` with `k_v = 5.34 + 4.0/(a/b)²` for the
  panel aspect ratio, then `cirsoc_301.buckling_stress_check(τ, τ_cr)` (H.3.6,
  φ_c = 0.85) — the same route the perforated-beam web-post check already
  takes. **A panel result must never be shown without this**; a plate that
  reports τ = 40 MPa "fine" while already buckled is worse than no answer.
* Edge weld: `leg_for_shear_flow(q)` with the same J.2.4 / J.2.2(b) bounds.

### 2d · UI
* **Creation:** select rods forming a closed 3- or 4-cycle → "Add plate".
  Needs a small graph routine, `closed_loop_from_rods(rods, selected)`,
  returning the ordered node loop or a reason it is not a valid loop
  (not closed, branches, wrong length, self-intersecting). Unit-tested on
  its own — this is ordinary graph code and deserves ordinary tests.
  Selecting 3–4 nodes directly is the fallback path.
* **Drawing:** hatched fill beneath the rods, `τ` and utilisation labelled,
  colour-graded by utilisation, and a distinct hatch when buckling governs.
* **Panel section** "Shear panel (selected)": thickness, grade, electrode;
  Add / Remove; results after Analyze.
* **Deletion:** in `_on_delete`, remap plate node indices exactly as rods are
  remapped, and drop any plate that loses a node. Per §B this is a silent
  corruption risk, so it gets its own test.

### 2e · Verification
Reference-free checks first — they need no expected values, so they apply to
any model a future change might break:

1. **Rigid-body patch test**, tolerance relative to ‖K‖ (§A trap 1).
2. **Constant-shear patch test** on all five shapes.
3. **Corner-force self-equilibrium** per panel.
4. **Method-of-joints residual** on a plated Vierendeel frame (2b).
5. **`t → 0` continuity**: as plate thickness → 0 the solution must converge
   to the bare frame. Strong, reference-free, and catches sign and assembly
   errors that a single-value comparison would not.
6. **Monotonicity**: increasing `t` must monotonically stiffen the bay and
   reduce member moments.
7. **Symmetry**: a symmetric frame with symmetric plates gives symmetric
   results.

Then closed form:

8. **Shear cantilever** vs `δ = V·L/(G·t·d)`, with rigid flanges (§A trap 2).
9. **`q = V/d`** for a panel in a shear cantilever.
10. Excel round-trip; screenshots at two window widths.

---

## D. What this does *not* do

Worth stating plainly so the results are not over-read:

* **No stress field.** A shear panel reports one `τ` for the whole panel. It
  does not produce σx/σy/τxy contours — that is P-3.
* **No rotational stiffness.** The panel does not restrain joint rotation
  (§4 of the diagnosis). For a welded-all-round plate the shear-panel
  idealisation is the accepted way to model this; it is not a substitute for
  a meshed plate if the goal is local stress.
* **No tension-field action.** Post-buckling strength is not counted; the
  buckling check is a limit, not a switch to a tension-field model.
* **No block shear / gusset buckling in P-1 v1** (Stage 1a), pending a
  connection-detail editor.

---

## E. Order, and what I would do first

1. **Stage 0** — small, mechanical, unblocks everything.
2. **Stage 1 (P-1)** — no solver risk whatsoever, and it delivers the
   day-to-day answer (plate size, weld leg) using data the app already has.
3. **Stage 2a + 2b + 2e** — the element, the equilibrium integration and the
   tests, *before* any UI. The element is already validated in prototype, so
   this is mostly transcription plus the integration point that matters.
4. **Stage 2c + 2d** — checks, then UI.

Suggested first commit boundary: Stage 0 + Stage 2a + 2b + 2e — i.e. a
solver that can take plates and is proven correct, with no UI yet. That keeps
the risky part small, reviewable and fully tested on its own, and it is the
piece that would be most expensive to get wrong.

**Relative sizes**, with "delete the dead method" (T-2, 15 min) as the unit:
Stage 0 ≈ 2 units; Stage 1 ≈ a day; Stage 2 ≈ several days, roughly a third
of it in tests. Both together remain well short of P-3.

---

## F. Open items — not blocking, worth a decision before Stage 2d

1. **Does a P-2 panel also get a gusset at its corners?** Physically often
   yes. They are independent records in `self.plates`, so nothing prevents
   it; the question is only whether the UI should offer to create both.
2. **Steel grade defaults.** F-24 (Fy = 235 MPa) and electrode E70
   (Fexx = 480 MPa) are the obvious defaults for CIRSOC work — confirm.
3. **`_beam_gauss_solve`'s residual gate** (diagnosis §3.2) is *not* a
   blocker here: P-2 adds no nodes and no DOF, so a plated model is the same
   size as the bare frame. It stays a prerequisite for P-3 only.
