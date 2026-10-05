# Plates P-1 and P-2 — built, and what building them found

**Date:** 2026-09-06
**Plan:** `PLAN_PLATES_P1_P2_2026-09-06.md` — all stages done
**Suite:** 461 → **520 passed**, 0 failed. No existing test changed its meaning.
**Method:** MANIFESTO §2 — patch tests and closed forms against the real
solver, the real widgets driven at real window sizes, and screenshots looked at.

---

## 0. Summary

| | |
|---|---|
| P-1 gusset (annotation) | **built** — checked against CIRSOC 301-2018, never touches the solver |
| P-2 shear panel (member) | **built** — assembled into `analyze()`, changes the load path |
| New tests | **59** (32 element/checks, 12 app-level, plus the earlier 15) |
| Bugs found while building | **2**, both in new code, both caught by tests, both fixed |
| Pre-existing gap found | **1** — see §2, worth reading |
| Existing behaviour changed | **none** |

The element math was prototyped and validated *before* the plan was written,
so the risky part was settled first. What actually cost the time was the
integration — which is where both bugs were.

---

## 1. The two bugs, and why only one kind of test could see them

Worth recording because they are the same lesson twice.

### Bug 1 · the panel's corner forces had the wrong sign

`K·d` is the element's nodal **action** vector; global equilibrium reads
`Σ(K·d) = F_external`, so what an element applies **to** a node is its
*negative*. The first version stored `+K·d`.

What makes this dangerous is how quietly it passes:

* the panel still **self-equilibrates** — its four corner forces still sum to
  zero, and its moment about any point still vanishes;
* so the rigid-body patch test passed, the constant-shear patch test passed,
  and the corner-force self-equilibrium test passed — **every element-level
  test passed**;
* meanwhile every joint the panel touched was out of balance by exactly twice
  the corner force.

Only `test_joint_equilibrium_still_closes_with_a_panel_present` caught it, and
the residual it reported (38.9 kN) was exactly `2 × 19.47`, which is what
identified the cause in one step. **Element tests verify an element; only an
assembly test verifies an assembly.**

### Bug 2 · a plate outliving its nodes

Node identity in this tab is the **list index**, and `_on_delete` renumbers
every index above a deleted node. A plate stores node indices, so without a
remap in the same pass it goes on referring to the same *numbers* while those
numbers now mean different nodes — no crash, no error, a plate quietly
attached to the wrong bay.

`test_deleting_an_unrelated_node_remaps_plate_indices` asserts on the plate's
**physical corner coordinates**, not on its indices, which is the only form of
the assertion that can tell a correct remap from no remap at all. Confirmed by
deleting the remap and watching two tests fail.

(Cable Web adopted stable ids specifically to avoid this class of bug —
MANIFESTO §1.3. The Truss tab did not, so plates inherit the hazard and it is
handled explicitly rather than assumed away.)

---

## 2. A pre-existing gap this work exposed

**`compute_node_force_vectors` reports each rod's AXIAL force only.**

For a pin-jointed truss that is the whole story and its free-body diagrams are
complete. At a **rigid (Vierendeel) joint it is not**: the members also
deliver shear and an end moment. Asking a plated Vierendeel frame to satisfy
joint equilibrium through those vectors showed it could not — the residual was
essentially the entire applied load.

This matters directly for P-1, whose whole purpose is "what does this gusset
have to resist". Building the gusset check on the axial-only vectors would
have **understated the connection forces at exactly the joints a Vierendeel
user cares about**.

Fixed by adding `compute_node_design_actions()`, which returns the complete
set — force components *and* moment, per member, plus panel corner forces.
Joint equilibrium now closes to 1e-14 on a bare rigid frame and 3.6e-15 on a
plated one.

`compute_node_force_vectors` was **deliberately left as it is**: its output
feeds the existing Node Force Vectors report and its Excel export, and
silently changing what those draw is a bigger decision than this feature needs
to make. The design checks use the new function; the report still uses the old
one. Both docstrings now say which is which and why.

**Open question for you:** should the Node Force Vectors report and its FBDs
also switch to the complete actions? It would make them correct for
Vierendeel joints, at the cost of changing a drawing and an export that have
been stable for a while. I did not make that call unilaterally.

---

## 3. What was built

### P-2 · shear panel — a member of the model

Element in `truss_math.py`: constant shear flow `q = G·t·γ`, with the average
shear strain taken exactly from the polygon **boundary** by the divergence
theorem. `K = G·t·A·BᵀB`, rank 1, 8×8 for a quad and 6×6 for a triangle. No
Jacobian, no quadrature, no shape functions — and exact on triangles,
rectangles, parallelograms and general simple quadrilaterals alike.

* Assembled onto the `ux`/`uy` DOF the corner nodes already have. **No new DOF
  kind**: a membrane has no drilling DOF, so `needs_theta` is untouched and a
  pin-only model with panels still gains no rotation anywhere.
* Degenerate and self-intersecting ("bowtie") loops return `None` and are
  reported as invalid rather than assembled — a wrong-but-believable panel
  stiffness is worse than a panel the UI refuses.
* Loop orientation is normalised, so the reported shear-flow sign depends on
  the geometry and not on the order the rods happened to be clicked.

### P-1 · gusset — an annotation

`truss_plates.py`: Whitmore effective width (30° dispersion), plate gross
section, and the fillet weld leg, each against CIRSOC 301-2018 through the now
shared `cirsoc_301.py`. A gusset **never enters the stiffness matrix**, and
`test_gusset_records_never_reach_the_stiffness_matrix` pins that by asserting
every displacement and member force is bit-identical with and without one.

### Shared

`cirsoc_301.py` moved from `apps/perforated_beam/` to the root, because tabs
share only root-level modules and copying a design-code layer would let a
resistance factor drift — which is not a bug you notice by reading the output.
`MODULAR_ARCHITECTURE.md` now states the rule.

---

## 4. Verification

**Reference-free first** — these need no expected values, so they keep
applying to any panel a future change might break:

| check | result |
|---|---|
| Rigid-body translation and rotation → γ = 0, five shapes | ≤ 2.8e-17 |
| Constant-shear patch `u = k·y` → γ = k, five shapes | exact to 1e-12 |
| Corner forces self-equilibrate (ΣFx, ΣFy, ΣM) | ≤ 1.9e-16 relative |
| Joint equilibrium with a panel, **rigid** frame | 3.6e-15 |
| `t → 0` converges to the bare frame | < 1e-4 relative |
| Thicker plate monotonically stiffens the bay | strictly monotonic |
| Symmetric frame + symmetric panels → symmetric result | 1e-9 |

**Closed form:**

| check | result |
|---|---|
| Shear cantilever vs `δ = V·L/(G·t·d)` | 3.813e-3 → 3.813e-4 → 3.813e-5 as flange area ×10 |
| Panel shear flow vs `q = V/d` | exact to 1e-6 |
| `τ_cr = k_v π²E / (12(1−ν²)(b/t)²)` | exact to 1e-12 |
| Whitmore width, plate stress and weld leg, recomputed in N/mm/MPa | exact to 1e-12 |

**Three tolerance traps**, all found by measurement and all written into the
test file so they are not "fixed" the wrong way later:

1. The rigid-body patch test must be judged **relative to ‖K‖**. `G·t` is
   order 6e8, so an exactly-satisfied rigid-body mode still leaves
   `|K·d| ≈ 2e-7` — round-off amplified by stiffness. An absolute tolerance
   fails a correct element.
2. The cantilever closed form assumes **rigid flanges**. With finite flange
   area the error is the flanges stretching and decays as 1/A. The test
   asserts that **rate**, so a real element error cannot hide in a loose bound.
3. The sign trap in §1 — an element test cannot see it.

Also: Excel round-trip preserves both plate kinds and every field; a workbook
with no `[PLATES]` section still imports; the layout regression from T-1 still
passes with the new controls added; all six tabs launch and switch at 1500 px
and 820 px; and the canvas rendering was **looked at**, not just measured.

---

## 5. What this does not do — state this to users

* **No stress field.** One `τ` for the whole panel. No σx/σy/τxy contours.
* **No rotational stiffness.** A panel does not restrain joint rotation. For a
  plate welded all round, modelling its shear and nothing else is the accepted
  idealisation — it is not a substitute for a meshed plate if local stress is
  the goal.
* **No tension-field action.** Post-buckling strength is not counted; the
  buckling check is a limit, not a switch to a tension-field model.
* **P-1 does not check block shear or gusset compression buckling.** Both need
  a bolt pattern and edge distances this tab does not model. The result says
  so, in the panel and in the tooltip. A gusset reported "OK" while block
  shear was silently unchecked would be worse than no answer.

### The buckling point, which is not a footnote

A thin panel buckles in shear **long before it yields**. On the 6 mm test
panel: `τ = 0.61 MPa` against `τ_cr = 10.1 MPa` — the buckling utilisation is
**13× the yield utilisation**, and buckling governs. That is why
`panel_checks` returns both, why the readout prints them on the same line, and
why the canvas marks a buckling-governed panel distinctly. A comfortable-
looking `τ` shown on its own is the most misleading thing this feature could
produce.

---

## 6. Assumptions I proceeded on

You asked me to start, so I took the two defaults from §F of the plan without
waiting: **F-24 steel, Fy = 235 MPa** and **E70 electrode, Fexx = 480 MPa**.
Both are editable per plate in the Plates panel and both are stored in the
Excel model sheet. Say if either should differ and it is a one-line change.

Plate edges are assumed **simply supported** for the buckling check. Real edge
restraint from the surrounding members is somewhere between simply supported
and fixed; simply supported is the conservative end, and claiming the fixed
value would overstate the capacity of exactly the panels most at risk.

---

## 7. Still open

1. Should the **Node Force Vectors report** switch to the complete joint
   actions (§2)? It would be correct for Vierendeel joints; it changes an
   existing drawing and export.
2. **Block shear and gusset buckling** need a connection-detail editor
   (bolt pattern, edge distances) before they can be checked honestly.
3. `common._beam_gauss_solve` still rejects valid, well-conditioned models
   above ~600 DOF as "singular" (see `DIAGNOSIS_PLATE_FEATURE_2026-09-06.md`
   §3.2). **Not a blocker for P-1 or P-2** — a panel adds no nodes and no DOF,
   so a plated model is the same size as the bare frame. It remains a
   prerequisite for P-3.
4. Beam / Arch / Cable still share the T-1 layout idiom, and Cable Web still
   holds its own copy of the wrap logic now shared in `common.FlowBar`.
