# Stereo tab — 2026-09-12 session report

Covers every change made to the Stereo (3D space-structure) tab across this
entire conversation, in the order it happened: two rounds of didactic display
features, a user-reported structural bug in the vault generators (and a real
mechanism that fix exposed), a node-delete feature, a GeoGebra-style
expression/domain wizard for defining custom surfaces, and a Module Editor for
directly reshaping a grid's own repeating cell. Every item below was verified
against a real, running Tk widget (per this project's own testing standard —
"never conclude a UI fact from reading code alone") and/or the direct-stiffness
solver, never assumed from reading the generator code alone.

**Suite: 1561 → 1658 passed, 0 failed**, across the four commits this report
covers in detail (§3–§6); the two earlier commits (§1–§2) were already
complete and tested before this report's window opened. Full suite re-run
twice at the end of every stage, back-to-back, with identical results both
times — the standard check for the Tk-interpreter flakiness this session
itself found and fixed (§5.5).

| # | change | kind | commit |
|---|---|---|---|
| 1 | Multi-tier columns/beams, deformed-only view, deform colour modes, reference shade, legend fix | feature | `02ba6de` |
| 2 | Reaction arrows, click-to-inspect, Load % animation, utilization heat-map | feature | `da5853e` |
| 3 | Vault supports moved to the springing lines; a real mechanism it exposed, fixed | **bug fix** | `88298d4` |
| 4 | Select nodes and delete them | feature | `8a300f7` |
| 5 | Custom Surface Wizard (typed-expression surfaces + domain/module) | feature | `8601c99` |
| 6 | Module Editor (cell/role detection + propagated edits) | feature | `d3f7c9a` |

---

## 1 · Multi-tier columns/beams, didactic display features (`02ba6de`)

Requested as: "the capital of a column is always equal to the module it's
under… sometimes the capital is a two-modules-thick inverted pyramid," plus a
set of display/legibility asks for teaching with the deformed shape.

- `add_column(..., tiers=1|2)`: `tiers=2` ("two modules thick") splits the
  selected footprint into 4 angular quadrants, fans the shaft head to one
  intermediate node per quadrant, each intermediate fans on to its own
  quadrant's targets, and ties the intermediates together in a ring. The ring
  tie is not optional — eigenanalysis found the head+intermediates cluster 2
  DOF short of rigid without it.
- `reinforcement_beam(..., tiers>=1)`: stacks that many apex rows between the
  two base rows, each tier independently getting the same triangulation a
  single tier already had, tied to its neighbour for through-thickness
  stiffness.
- "Show deformed" gained a **Deformed only** toggle (hides the reference
  structure entirely) and a **colour-mode** toggle (white-to-green
  displacement spectrum, or the same red/blue force colouring as the rest
  of the app).
- The reference structure fades to an **adjustable grey** (a toolbar slider)
  whenever the deformed overlay is shown, so it reads as a backdrop instead
  of competing with the overlay.
- The legend's "dashed = over capacity" note got its own row with an actual
  dashed swatch, instead of being folded into the "~0 force" row's text
  where it was easy to miss (this was the user's own complaint: seeing
  dashed rods in a two-opposite-supports arrangement with no visible
  explanation of what the dashes meant).

## 2 · Reaction arrows, click-to-inspect, Load %, utilization heat-map (`da5853e`)

Four follow-on didactic features, all approved together:

- **Reaction arrows**: a toggle draws each support's solved reaction
  (Fx/Fy/Fz) pointing *away* from the node (the support pushing back),
  sized with the same `LoadScale` convention as load arrows but in a
  distinct colour.
- **Click-to-inspect**: clicking near a rod (not a node) hit-tests against
  the nearest member's own screen-space line segment via
  `_point_segment_distance` and shows its force/utilization/governing
  check — a one-click alternative to the full Member Report table.
- **Load % slider**: steps the applied load 0–100%. The solver is
  linear-elastic, so this scales every displayed displacement, force,
  reaction and arrow by the same fraction via plain multiplication of the
  already-solved results (superposition) — no re-solve per tick.
- **Utilization heat-map**: green→amber→red at an **absolute**, code-defined
  threshold (0 / 0.5 / 1.0), unlike `force_color`'s per-model relative
  range, so red always means "at or over capacity," the same in every model.

---

## 3 · Vault support-placement bug, and the mechanism it exposed (`88298d4`)

**User report:** "the supports in the vault cases make no sense, they should
be at the base of the vault, not at the sides of the arch."

### 3.1 The bug

`barrel_vault`/`parabolic_vault`/`elliptic_vault` offered every node on the
two **end cross-sections** (`bi=0`, `bi=n_bays`, every arch station) as
support candidates — treating the vault like a beam spanning its own length
between two end diaphragms. A real barrel vault's arch action instead sends
thrust to the two **springing lines** (`ai=0`, `ai=n_arch`), running the
vault's full length — where the shell's own weight actually needs to land,
continuously, along the two long walls.

**Fix**: `support_candidates` now unions `outer[(bi, 0)]`/`outer[(bi,
n_arch)]` over every `bi` (plus the inner layer's own springing lines when
double-layered), instead of `outer[(0, ai)]`/`outer[(n_bays, ai)]` over every
`ai`. Verified geometrically (every offered node sits at `y = ±half-span`,
across every longitudinal station) and via a rewritten test,
`test_barrel_vault_support_candidates_are_on_the_two_springing_lines`
(the old test's own name described the bug's behaviour as if it were
correct).

### 3.2 The mechanism this correction exposed

The OLD (wrong) support pattern accidentally supported *every* node when
`n_bays=1` and heavily over-constrained the model otherwise, masking a real
structural mechanism the existing bracing had never actually been asked to
resist. Two distinct modes, found by the same eigenanalysis method used
throughout this project (build the reduced stiffness matrix, find near-zero
eigenvalues, read the mode shape):

1. **Every bay's rib flexing identically along the vault's length.** The
   existing bracing (purlins + inter-bay diagonals) only resists *relative*
   motion between bays — a mode where every bay deforms the *same* way has
   no relative motion for it to see. **Fix**: an intra-rib "skip-one"
   diagonal (`outer[(bi,ai)]`–`outer[(bi,ai+2)]`, role `rib_diag`),
   triangulating each rib within its own plane, independent of every other
   bay.
2. **A longitudinal shear mode specific to the non-circular profiles**
   (parabolic/elliptic), at a couple of `n_arch`/`n_bays` combinations —
   the double layer's own `web_diag`/`edge_brace` bracing left a genuine
   zero-energy mode there (confirmed: every member's elongation under the
   mode was exactly zero). **Fix**: the existing single-layer-only `brace`
   diagonal now applies unconditionally to both layers, closing the mode
   regardless of arch profile.

**Verification**: a sweep of 300+ combinations
(`n_arch`∈{2,3,4,…,20}×`n_bays`∈{1,…,12}×`double_layer`×`depth`, across all
three vault families) — **zero failures**. A dedicated regression test,
`test_barrel_vault_rib_is_stable_when_only_the_springing_lines_are_pinned`
(and its extruded-arch-family analogue), pins this down permanently.

---

## 4 · Select nodes and delete them (`8a300f7`)

Mirrors `truss_app.py`'s own `_on_delete`: select node(s) via click/lasso,
then Delete/Backspace (bound on the canvas, matching `truss_app.py`) or the
"Delete selected node(s)" button removes them. Cascades to every member
touching a deleted node, and remaps every remaining node-INDEX reference
(other members' `a`/`b`, supports, loads, `support_candidates`, `load_nodes`)
down past the removed indices — node identity in this tab is the list index,
so a stale reference after the list shifts would be silent corruption, not a
crash. Goes through undo/redo. A deletion that leaves the rest of the
structure a mechanism surfaces the normal way (`Analyze` reports a singular
stiffness matrix) — nothing is auto-patched.

---

## 5 · Custom Surface Wizard (`8601c99`)

The first of two large features from the user's own design brief (confirmed
over several rounds of clarifying questions before any code was written).

### 5.1 `apps/stereo/expr_math.py` — a restricted expression compiler

Not `eval()` on the raw string — that would run arbitrary Python for text
typed into a box. Parses with `ast` and validates the **whole tree structure**
at compile time against an explicit whitelist (constant type, name, binop,
unary op, and call — with arity checked against a per-function table) before
ever evaluating anything.

**Bugs found and fixed while writing its own tests** (5 of 20 tests failed
on the first pass): the initial validator only checked *names*, not node
*types*, so `x.real` (attribute access), `sin(x, y)` (wrong arity),
`max(x, y=2)` (keyword args), `[i for i in range(10)]`/`(lambda: 1)()`
(comprehension/lambda), and `'a'` (a string literal) all slipped past
compile-time rejection. Rewrote the validator to walk and type-check every
node, not just `Name` nodes — all 20 tests pass after the fix.

### 5.2 Surface definition and sampling (`stereo_geometry.py`)

- `make_height_field_surface(expr_z)` (`z = f(x, y)`) and
  `make_parametric_surface(expr_x, expr_y, expr_z)` (`x/y/z` of `u, v` — for
  a torus, a cylinder, anything a height field can't express), both
  normalized to one shared `surface(p, q) -> (x, y, z)` shape so every piece
  of downstream machinery is written once.
- `custom_surface_grid(surface, coord, pattern, p_range, q_range, n1, n2,
  module, depth, offset_side)`: Cartesian or Polar domain; `square`/
  `diagonal`/`isometric` (a true 60°-equilateral-triangle lattice, confirmed
  with the user) module pattern; a 2D (single layer) or 3D (that surface
  plus a second layer offset along the surface's own numerically-estimated
  local normal) module.
- `custom_surface_between(surface_top, surface_bottom, …)`: two
  independently-defined surfaces connected as a top/bottom double layer over
  one shared domain lattice — the wizard UI enforces identical domain
  settings on both (confirmed with the user), which is what makes their
  nodes correspond 1:1.

**Bugs found and fixed during validation:**

- **Isometric + a full 2π Polar sweep spirals, and forcing it to close the
  seam produced a wrong, arbitrarily-long connecting member.** The oblique
  60° basis shifts radius by a fixed amount on every angular step, so it
  cannot close into concentric rings the way `square`/`diagonal` can — fixed
  by making `isometric` never wrap, documented as an open spiral fan rather
  than a closed disk for that specific combination.
- **A genuine mechanism on the non-circular (parabolic/elliptic-profile)
  double-layer 3D module**, at 2 of 32 combinations in the first validation
  sweep (e.g. `n_bays=1, n_arch=10`) — root-caused via eigenanalysis to the
  same class of longitudinal-shear mode found in §3.2, fixed the same way
  (the `brace` diagonal applies unconditionally to both layers). Re-swept
  84 combinations (5 surfaces × 3 patterns × 4 mesh densities) after the
  fix: zero failures.
- **2D module + `square`/`diagonal` has no diagonal bracing of its own** —
  documented rather than "fixed": a single pin-jointed layer with these two
  patterns is topologically just an (optionally 45°-rotated) orthogonal
  grid, with no diagonal at all; whether it happens to analyze depends on
  the specific surface's curvature. `isometric` is the only 2D pattern
  guaranteed stable on its own regardless of surface shape.

### 5.3 Wizard UI

A "Custom Surface Wizard…" dialog: a calculator-style button palette
(operators, `π`/`e`, trig, `sqrt`, etc. — `^` reads as power, not Python's
XOR) inserts into whichever expression field last had focus; single-surface
or two-surface mode; domain/pattern/module controls; a "Generate" button that
loads the resulting mesh through the same `_load_mesh` path every other
generator uses.

### 5.4 A real Tk bug this surfaced (not just this feature's own bugs)

Every wizard-local `tk.StringVar`/`IntVar`/etc. now passes `master=win`
explicitly. Left to the default, a `Variable` binds to whatever
`tkinter._default_root` happens to be at creation time — not necessarily the
Toplevel's own interpreter once more than one `Tk()` root exists in the
process, which this app's own test suite does (one session-scoped root per
test file). When they don't match, a widget's edits never reach its "own"
Python `Variable` object at all: `entry.insert()` visibly changes the
widget, but `var.get()` keeps returning the untouched default. **Found by
running the wizard's own tests as part of the FULL suite rather than in
isolation** — 3 tests failed only when run alongside the rest of the
project's Tk-based tests, never alone. Confirmed fixed by re-running the
full suite twice back-to-back afterward (1627 passed both times).

---

## 6 · Module Editor (`d3f7c9a`)

The second large feature from the user's design brief — confirmed over
**three** rounds of clarifying questions (propagation model, curved-module
preview, edit capabilities, rod-locking semantics, shared-node conflict
resolution, keystone handling) before any code was written, per the user's
own explicit request to "ask all the questions you need… try not to assume
anything important."

### 6.1 Cell detection and role classification (generic, not per-family)

- `find_cells(nodes, members)`: every minimal 3-/4-node closed circuit of
  existing members. A quad is only reported when *neither* diagonal already
  exists (otherwise it is really two triangles, both already found on
  their own).
- `classify_cell_roles`: groups cells by **congruence signature** (sorted
  edge lengths, plus both diagonals for a quad) into "roles" numbered by
  decreasing cell count — role 0 is always the grid's dominant, repeating
  module; every other role is a rarer shape (a dome's apex fan, a vault's
  end panel) surfaced in the "keystone / singular modules" list.
- `_canonical_cycle`: rotates/reflects each cell's node order to whichever
  gives the lexicographically smallest edge-length sequence, so two
  congruent cells agree on which position is "the same" corner — required
  for an edit at position *k* to land on the analogous corner everywhere.
- `cell_local_basis`/`cell_local_coords`: an orthonormal (u, v, n) frame per
  cell (Gram-Schmidt'd from its own first two edges), used both to render
  the cell locally flattened and to express an edit in a frame that stays
  meaningful as the cell's orientation changes around a dome or fans out
  along a vault (confirmed with the user as the propagation frame).

Deliberately **generic over `(nodes, members)` alone**, not tied to any
generator's own `(i,j)`/`(bi,ai)` indexing — confirmed with the user
("all grid families") and verified directly: ran it against all 11 preset
families plus a wizard-built isometric 3D custom surface, zero crashes,
zero invalid node/member references, all under 2.3 seconds even for a
30×30-module (1861-node, 7200-member) flat grid.

### 6.2 Role-wide edits, and three real bugs found while testing them

- `move_role_node`: moves one canonical position across every cell of a
  role, each in its own local frame; a physical node proposed by more than
  one cell (an ordinary shared corner) gets the **average** of every
  proposal — confirmed with the user as the intended tradeoff for a
  corner shared between differently-oriented neighbours.
- `set_role_member_length`: sets one edge's length by moving its "far"
  corner along the current direction, computed from the pre-edit snapshot.
- `toggle_role_member`: adds/removes one diagonal across every cell of a
  role, propagating whatever action applies to the representative cell.
- `rescale_role_cells`: scales a role by a factor, "keeping its shape."
- `project_onto_unlocked_directions`: Gram-Schmidt projection stripping any
  component of a requested move that runs along a **locked** rod's own
  direction — confirmed with the user as "sideways motion only" (a locked
  rod's endpoints can still swing, never stretch it).

**Bug 1 — rescale diluted the requested factor.** Scaling each cell about
its *own* centroid, then averaging conflicting proposals at a shared corner,
partially cancelled the scale: asking for ×2.0 on a role whose cells share
corners measurably produced ×1.5. Fixed by scaling the whole role about
**one shared centroid** instead — an unambiguous similarity transform, every
pairwise distance now scales by exactly the requested factor (verified for
×2.0, ×0.5, ×1.3).

**Bug 2 — `set_role_member_length` cascaded through shared corners.** The
first version read each cell's positions from the being-mutated output list,
so a corner already moved by an earlier cell in the loop was treated as
"fixed" by a later cell that shared it — a genuinely order-dependent result.
Fixed to always read from the original pre-edit snapshot and average
conflicting proposals, matching the other three edit functions; a test now
pins order-independence (processing a role's cells in reverse gives the
identical result).

**Bug 3 — hit-testing broke for the `toggle` tag.** The click hit-test
stripped a hardcoded 4 characters to recover a tag's position numbers
(`"node3"` → `"3"`, `"edge0_1"` → `"0_1"`) — correct for `node`/`edge`, but
`"toggle0_2"` has a 6-character prefix, so `[4:]` produced `"gle0_2"` and
`int()` would have raised. Fixed to strip exactly `len(tag)` characters.

### 6.3 A design bug found only by actually exercising the propagation model

Editing a role was originally wired to re-run `find_cells`/
`classify_cell_roles` after every edit, on the theory that the editor should
always reflect the mesh's current, honest topology. **Tested against a
densely-shared role** (a flat_grid's own pyramidal-web triangles, where
nearly every node is shared by many cells) rather than assumed safe: setting
one triangle's edge to a new length fragmented role 0 from **2 roles into
26** in a single edit, because the shared-corner averaging (§6.2, confirmed
behaviour) inevitably drifts different cells slightly out of exact
congruence, and re-classifying immediately treats that drift as "these are
now different shapes." Fixed by making geometric edits (move / set-length /
rescale) **not** re-trigger cell/role detection at all — the node/member
*graph* hasn't changed, only where the nodes sit, so the existing cell/role
list is still exactly as structurally valid as before. Only a real topology
change (toggling a rod, or anything outside this editor — generate, delete,
undo, add-ons) re-detects roles. Verified: the same edit that fragmented 2→26
roles before the fix now leaves the role count at exactly 2, with the
mini-canvas and selection still showing the live, correct new geometry.

### 6.4 UI

A new right-hand "Module Editor" panel (packed before the expanding canvas —
same reasoning as the left sidebar's own `ScrollPanel`, documented there):
role selector, a locally-flattened mini-canvas (click-drag a node, click a
rod to set/lock its length, click a dashed potential diagonal to add it),
a rescale-by-factor control, and the keystone/singular-modules list with an
explicit warning that editing one of those doesn't propagate the way editing
the dominant module does.

---

## 7 · Diagnostic pass (this report's own verification)

Beyond the per-feature tests above:

- Full suite run **twice, back-to-back, after every stage** — 1658/1658
  both times at the end (the standard check this session's own Tk-flakiness
  finding, §5.4, made necessary).
- Module Editor topology detection swept across **all 11 preset families**
  plus a wizard-built isometric 3D custom surface — no crashes, no invalid
  node/member references, all well under the time a single Generate click
  already takes.
- Cross-feature interplay checked directly: node-delete → Module Editor
  (index references stay valid), Wizard-generate → Module Editor (picks up
  the new mesh), undo/redo through a mix of delete/wizard/module-editor
  edits (each step's node/member count restored exactly).
- Edge cases: deleting every node down to zero (Module Editor shows its
  empty-state message, no crash) and regenerating afterward; a 30×30-module
  flat grid (1861 nodes, 7200 members) — the single slowest case measured,
  2.3 s for cell/role detection, which only ever runs once per Generate/
  Delete/Undo action, never per frame.

**Known, disclosed (not "fixed away") limitations**, each a genuine tradeoff
confirmed with the user rather than an oversight:

- A 2D module in `square`/`diagonal` pattern has no diagonal bracing of its
  own (§5.2) — use `isometric`, or `rigid` connectivity, for a guaranteed-
  stable single layer.
- `isometric` over a full-turn Polar domain is an open spiral, not a closed
  disk (§5.2).
- A geometric edit on a densely-shared role gives every cell's own edge an
  *averaged*, not always exactly the typed, result (§6.2/§6.3) — only a role
  whose cells share no nodes at all lands on the exact target everywhere.
