# The four open items, closed — 2026-09-07

Follows `DIAGNOSIS_PLATES_BUILT_2026-09-06.md` §7. Suite **520 → 548 passed**,
0 failed. Every change below was verified by driving the real widgets and
reading the real workbooks, not by reading the code (MANIFESTO §2).

| item | status |
|---|---|
| 1 · Node Force Vectors: add the missing information | **done** |
| 2 · Block shear and gusset buckling: enact | **done** |
| 3 · Beam / Arch / Cable layout | **done** |
| 4 · Excel: presentation, import compatibility, nomenclature | **done**, and it found two real bugs |

---

## 1 · The Node Force Vectors report now reports the whole joint

**Was:** each member's AXIAL force only. Complete for a pin truss; at a rigid
(Vierendeel) joint the members also deliver shear and an end moment, so the
report understated exactly the connections it exists to size, and its own
Σ row could not close.

**Now:** the report and the exported sheet both use
`compute_node_design_actions`, and show, per member:

* `N` — the axial force alone (what it was showing before),
* `|F|`, `Fx`, `Fy` — the COMPLETE force that member delivers to the joint,
* `M` — that member's end moment,

plus any **shear panel**'s corner force, and a Σ line over members + panels +
load + reaction that now actually closes.

**A second bug found while verifying it.** `reactions[..]['m']` is stored in
the solver's canvas frame (y DOWN), while every member action is reported
y-UP, where a moment about z reverses. Adding it unconverted left ΣM reading
exactly `2·m` at every fixed support — which looks like a solver error and is
not one. Subtracting closes it: measured residual now ≤ 1e-14 at free joints
and fixed supports alike, in the window and in the workbook.

Pinned by `test_node_force_vectors_report_balances_at_every_node` (reads the
numbers back out of the live report) and
`test_truss_node_force_vector_sheet_balances_at_every_node` (reads them out
of the exported .xlsx).

`compute_node_force_vectors` itself is unchanged and still exported — it is
the axial-only set, it is correct as such, and the FBD drawings now take the
complete set so the picture and the table cannot disagree.

---

## 2 · Block shear and gusset buckling are now checked

Both were previously disclaimed rather than computed, because neither can be
evaluated without a connection detail the tab did not model. It now does.

**New connection-detail editor** on the Plates panel: welded or bolted; bolt
diameter, rows × cols, pitch, gauge, end and edge distance; and the landing
length, which sets the Whitmore width, the weld length and the buckling
length together. Every field round-trips through Excel.

**Block shear** — AISC 360 J4.3:
`Rn = 0.6·Fu·Anv + Ubs·Fu·Ant`, capped by `0.6·Fy·Agv + Ubs·Fu·Ant`.
The bolted block runs two shear planes past every bolt with a tension plane
across the outer bolt lines; the welded block is bounded by the weld lines,
with no holes so net = gross. Sanity check that the two geometries are not
swapped: on the same joint, bolted 427 kN vs welded 1570 kN design capacity.

**Gusset compression buckling** — Thornton: the Whitmore width as a column of
thickness t, `r = t/√12`, `K = 0.65` (supported on two edges), through AISC
360 E3's column curve. Only a member in COMPRESSION can buckle the plate, so
a tie returns `applies: False` rather than a number that could be read as a
check that passed.

### The provenance caveat, which is not boilerplate

Every other resistance factor in this app was transcribed from the CIRSOC
301-2018 document with its clause beside it. **These two were not** — the
document was not in hand for J4.3 and Chapter E. What is implemented is the
AISC 360 formulation, which CIRSOC states it adopts as its basis, with AISC's
factors (φ = 0.75 rupture, φ_c = 0.90 compression).

The formulas are standard and stable. The factors have not been checked.
`PHI_WELD` is the cautionary precedent: CIRSOC uses 0.60 where AISC uses 0.75
for the same limit state — a 25% difference that only reading the table would
have revealed. **Assume the same could be true here.** The caveat is carried
in `cirsoc_301.BLOCK_SHEAR_AND_BUCKLING_PROVENANCE`, printed in the plate
readout, and asserted by a test so it cannot be quietly dropped.

Still not checked, and still said so: bolt bearing and tear-out at the holes
themselves, and weld-group eccentricity.

---

## 3 · Beam, Arch and Cable — the same layout fix as the Truss tab

All three carried the identical idiom: a fixed-width right panel packed AFTER
the expanding content, its scrolled interior pinned to the panel width, and
toolbars built as one un-wrapping row.

Mapped interactive controls, 1600 px → 600 px:

| tab | before | after |
|---|---|---|
| Beam | 26 → **5** | 26 → **25** |
| Arch | 45 → **14** | 45 → **42** |
| Cable | 26 → **11** | 26 → **26** |

and **zero controls overflow the window edge at any width**, on all three.

`WrapBar` was added to `common.py` for this: it flows the direct children of
an existing single-row bar across as many rows as the width needs, without
restructuring how that bar was built. It reuses `FlowBar`'s own row-wrapping,
so it inherits the same three lessons (MANIFESTO §3c/3d/3e).

Arch and Cable also had a **third** fixed-width element — a 400 px schematic
pane. Panel + schematic already exceeds a 600 px window, which left the
expanding middle column at zero width with a dozen controls in it. Both now
cap the schematic at a third of the window, a quarter once it is genuinely
tight.

**The residual is honest, not hidden.** Arch still loses up to 3 of 45 at the
narrowest widths. Those are small controls in the middle column's
diagram-scale rows, and they are lost VERTICALLY — the rows wrap onto more
lines as the column narrows until the stack is taller than the column. That
is a different problem from the pack-order bug, and
`tests/test_tab_layouts.py` says so in its docstring rather than asserting a
threshold as though it were a law. What it does assert is what was actually
broken: the panel never disappears, and nothing is ever pushed off the edge.

---

## 4 · Excel — and the two bugs the audit found

`tests/test_excel_roundtrip.py` exports a model from each tab, re-imports it,
and compares **field by field**. It drives the real app via each tab's own
`_current_state()` rather than a hand-written fixture, so a field added to a
model is either round-tripped or the test fails — a fixture would encode the
state shape as of the day it was written and drift silently.

**Round-trip fidelity: Beam, Arch, Cable and Truss all rebuild faithfully.**
That part was already sound.

### Bug: the Truss tab could not export a model it had not analysed

`export_excel` did `results.get(...)` with no guard, so pressing Export Excel
before Analyze raised `AttributeError` and the tab reported "Export failed".
The one workflow the feature exists for — draw a model, save it, reopen it
later — was the one that did not work until you had run an analysis. The Beam
tab had always allowed this and says so in its own dialog.

Now a model-only export writes just the Model sheet, with a note saying why
the result sheets are absent, and it still round-trips.

### Bug: the exported Node Force Vectors sheet had the same two defects as the on-screen report

Axial-only vectors, and the reaction moment added in the wrong frame. Both
fixed together (§1). The sheet now carries `N axial`, `|F|`, `Fx`, `Fy`, `M`
and `Angle`, lists shear-panel corner forces, and its Σ rows close to 0.00.

### Nomenclature — three names for one idea

| tab | was | now |
|---|---|---|
| Beam | `[DLOADS]` | `[DISTRIBUTED_LOADS]` (Cable already used this) |
| Truss | `[LOADS]` | `[NODE_LOADS]` |
| Truss | `t_from_A` | `t_frac_from_A` |

`[LOADS]` became `[NODE_LOADS]` and **not** `[POINT_LOADS]`, because the
Truss sheet already has a `[POINT_LOADS]` section — for loads applied ALONG a
rod — and the two are different things. `t_from_A` did not say whether it was
a length or a fraction; it is a fraction.

**Every importer accepts both the old and the new name.** A workbook already
on disk still imports. Renaming without that would quietly break the round
trip for existing files, which is the opposite of the point.

`[UNIFORM_LOADS]` (Arch) was deliberately **left alone**: it holds two
whole-span scalars, where `[DISTRIBUTED_LOADS]` holds a list of per-region
loads. Different shapes carrying different data — one name for both would be
the misleading choice, not the tidy one. The test records that reasoning
rather than silently exempting it.

### Presentation

Two rules are now asserted for every tab's model sheet:

* **units live in the column header** — `x_m`, `P_kN`, `Fy_MPa`, not a bare
  `x`. A test enumerates the exceptions (identities, indices, expressions,
  dimensionless counts) so a new unitless header has to be justified;
* **the sheet titles itself** and says column order matters, because it is
  meant to be read and edited by hand.

---

## Verification performed

1. `pytest -q` — **548 passed** (520 before), 0 failed.
2. Width sweep 1600 → 600 px on Beam, Arch, Cable, before and after, with
   screenshots inspected at several widths.
3. All six tabs launched together and visited at 1500 / 900 / 700 px.
4. A real exported workbook opened and read: sheet list, the Node Force
   Vectors table, the `[PLATES]` block, and the section names.
5. `pyflakes` clean on every file touched.
6. The two new gusset checks cross-checked against their closed forms, and
   the AISC E3 branch continuity checked at the transition slenderness
   (0.05% step — the code's own rounding, not an error).

## Still open

* Bolt bearing / tear-out and weld-group eccentricity (§2).
* The CIRSOC clauses for J4.3 and Chapter E, to replace the two AISC factors.
* Cable Web still holds its own copy of the wrap logic now shared in
  `common.FlowBar` (a `NOTE` at `_relayout_toolbar` explains how to migrate).
* `common._beam_gauss_solve` still rejects valid, well-conditioned models
  above ~600 DOF as "singular". Not a blocker for anything shipped so far.
* The Perforated Beam tab has no Excel export/import at all, so it is the one
  tab item 4 could not cover.
