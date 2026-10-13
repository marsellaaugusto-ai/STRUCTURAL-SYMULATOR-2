# Handoff — SketchUp extension "Align by Points", 2026-10-13

Written so this work can be picked up cold, on another account, with no memory
of the chat that produced it. Same intent as
`STRUCTURAL SYMULATOR SOLVER-5-9-26/REPORTS AND GUIDES/HANDOFF_MANIFESTO_2026-09-10.md`,
but for the SketchUp side of the project. Read it top to bottom once; after
that the section headings are the index.

---

## 0 · The one-paragraph summary

The SketchUp extension **Coordinate coordinator truss app AMAC** (the two-way
bridge between SketchUp and the Stereo space-truss tab of the Python solver)
gained a new feature: **Align by Points** — two tools that rotate and move a
selection onto a target by picking 1, 2 or 3 pairs of matching points, rigidly
(rotation + translation only; never scale, skew or mirror). The extension's
source, which previously existed **only** inside a hand-built `.rbz`, was
vendored into this git repo first, then the feature was built on top. Extension
version went **0.2.0 → 0.3.0**. Everything is committed and pushed on branch
`claude/amazing-cori-dt1fvj` (commit `f20668c`, 27 files, +4252 lines). No pull
request was opened. 97 automated checks pass (42 math + 55 tool) in stock Ruby;
**the feature has not yet been run inside SketchUp** — the manual checklist for
that is the one open item (section 8).

---

## 1 · Where things are

| path | what it is |
|---|---|
| `sketchup_extension/coordinate_coordinator_truss_app_amac.rb` | extension loader (`SketchupExtension`, version string lives here) |
| `sketchup_extension/coordinate_coordinator_truss_app_amac/` | the extension package (all `.rb` + `icons/`) |
| `sketchup_extension/README.md` | layout, how to build, how to test |
| `sketchup_extension/ALIGN_BY_POINTS.md` | feature documentation + **21-item manual test checklist** |
| `sketchup_extension/HANDOFF_ALIGN_BY_POINTS_2026-10-13.md` | this file |
| `tools/build_rbz.py` | packages **and verifies** the installable `.rbz` |
| `tools/make_align_icons.py` | regenerates the four `align_*` PNG icons |
| `tools/test_align_math.rb` | 42 checks on the math, stock Ruby |
| `tools/test_align_tool.rb` | 55 checks driving the real tool code |
| `tools/sketchup_stub.rb` | test double of the SketchUp API subset (never shipped) |
| `dist/CoordinateCoordinatorTrussAppAMAC_v32_AlignByPoints_2026-10-04.rbz` | the built, installable archive (committed) |

The Python solver tree (`STRUCTURAL SYMULATOR SOLVER-5-9-26/`) was **not
touched** in this work.

### Repo / branch state

- GitHub: `marsellaaugusto-ai/STRUCTURAL-SYMULATOR-2`
- Branch: `claude/amazing-cori-dt1fvj` (pushed, tracking `origin`)
- Commit: `f20668c` — *Add "Align by Points" tools to the SketchUp extension (v0.3.0)*
- Parent: `d24c4d9` (merge of PR #1, the Stereo tab work) — the branch was at
  parity with `main` before this commit, so the diff **is** this feature.
- Session that produced it: https://claude.ai/code/session_01RrrwajkUg4BwtpUpRvsC39

---

## 2 · What happened, in order

1. The starting point was an uploaded archive,
   `CoordinateCoordinatorTrussAppAMAC_v31_2026-10-03_1350.rbz` (8 Ruby files,
   4 icons, 1168 lines), plus a detailed feature request: add "Align by
   Points" as two tools, with 1/2/3-pair modes, flip-normal and move/copy
   options, specific math, specific safety behaviour, menu/toolbar entries, a
   manual test checklist and explanatory comments.
2. The archive was extracted and all eight existing files were read to learn
   the namespace (`CoordinateCoordinatorTrussAppAMAC`), the comment style
   (long "why" headers, rubocop-sketchup notes), and the existing conventions
   (`Sketchup::InputPoint` for inference, `start_operation`/`commit_operation`,
   `UI::Command` + submenu + toolbar wiring in `main.rb`).
3. **The repo turned out not to contain the extension source at all** — only
   the Python solver and some zips. (The loader's comments even referenced a
   `tools/build_release.py` that did not exist here.) Decision: vendor the
   extension into `sketchup_extension/`, unchanged, as the base, so the
   feature could be committed as a reviewable diff and the `.rbz` could be
   rebuilt reproducibly.
4. **The first run was interrupted** partway through this exploration, before
   any file was written. When asked "did you finish this? where is the zip?"
   the honest answer was no and there was none; the work was then done in
   full.
5. The feature was written (section 4), icons generated, `main.rb` and the
   loader updated, tests written and run, the `.rbz` built and verified,
   documentation written, and everything committed and pushed.

---

## 3 · What the feature does (user-facing)

Both tools live in **Plugins → Coordinate coordinator truss app AMAC** and on
the extension's toolbar:

- **Align Face to Face…** — source may be loose faces/edges, groups or
  component instances. Typical use: drop a flat truss onto an inclined roof
  plane.
- **Align Group by Nodes…** — source restricted to groups and component
  instances, driven from their nodes (inference reaches inside without opening
  them). Only the instance transformation changes; internal geometry is never
  edited.
- **Align Options…** plus two checkable menu items,
  *Align: Flip Normal (face-to-back)* and *Align: Copy Instead of Move*.

Flow: select what to move (before **or** after starting the tool — a selection
made afterwards is picked up on the first click) → pick 1–3 source points
A1…A3 → pick the same number of target points B1…B3 → it applies on the last
target pick, or on **Enter** at any point with however many pairs are complete.

| pairs | result |
|---|---|
| 1 | translation only, A1 → B1, no rotation |
| 2 | A1 → B1 plus the **minimum** rotation about B1 aligning A1→A2 with B1→B2; no roll control |
| 3 | full rigid alignment: A1 on B1, A2 on the **ray** B1→B2 at its own distance (distances need not match), source plane coplanar with B1-B2-B3, A3 on B3's side |

Keys in-tool: **Enter** finish · **Esc** clear picks, **Esc** again leave ·
**1/2/3** (VCB) fix the pair count · **F** flip · **C** Move/Copy. The status
bar carries the current step, the live option state and the last message; the
VCB shows `picked/planned`; distances are reported via
`Sketchup.format_length`, i.e. in the model's current units.

---

## 4 · The code, file by file

| file | lines | contents |
|---|---|---|
| `align_math.rb` | 347 | frames, the three solvers, tolerances, matrix hand-off |
| `align_options.rb` | 86 | the two persisted options, dialog, toggles, summary |
| `align_tool.rb` | 687 | `AlignByPointsTool` + the two subclasses |
| `main.rb` | modified | three `require`s, three `UI::Command`s, two checkable toggles, toolbar entries |
| `coordinate_coordinator_truss_app_amac.rb` | modified | 0.2.0 → 0.3.0, description mentions the feature |
| `icons/align_{face,nodes}_{small,large}.png` | — | 16px and 24px, generated by `tools/make_align_icons.py` |

Nothing else in the extension changed: the Excel export, auto-detect and
Stereo import paths are byte-for-byte as they were in v31.

### 4.1 `align_math.rb` — deliberately API-free

Every solver is plain Ruby arithmetic on `[x, y, z]` arrays. The **only**
SketchUp call in the file is `AlignMath.to_transformation`. That was a
deliberate choice so the math is unit-testable in stock Ruby, and so the one
place that touches the API is small enough to read at a glance.

The math, as implemented:

```
frame(P1, P2, P3):
  origin = P1
  X = (P2 - P1).normalize
  N = ((P2 - P1) x (P3 - P1)).normalize
  Y = N x X                       # right-handed, orthonormal, det = +1

T = Frame_B * Frame_A.inverse  =>  R = R_B * R_A^T ,  t = B1 - R * A1
```

- **2 pairs**: `rotation_between(u, v)` — axis `(u × v).normalize`, angle
  `acos(u · v)` via Rodrigues; rotation taken about B1 (`t = B1 - R·A1`).
  Degenerate cases handled explicitly: `u·v ≈ +1` → identity; `u·v ≈ −1` →
  180° about an axis built by crossing `u` with whichever world axis it is
  least aligned with.
- **1 pair**: translation `B1 − A1`, identity rotation.
- **Flip normal**: applied to the **target** frame as a 180° rotation about
  its own X axis (`Y → −Y`, `N → −N`). Negating **two** columns keeps the
  determinant at +1 — a half turn, never a mirror. (Negating `N` alone would
  give det = −1 and mirror the geometry; that is the trap this avoids.)
- Matrices are kept 3×3 row-major internally and converted **once** to
  SketchUp's 16-element column-major layout in `to_matrix_array`.

Tolerances (all named constants at the top of the file):
`COLLINEAR_CROSS_TOL = 1e-6`, `MIN_ANGLE_DEG = 0.1`, `COINCIDENT_TOL = 1e-6`,
`IDENTITY_ROT_TOL = IDENTITY_TRANS_TOL = 1e-9`. Collinearity is tested **both**
ways — cross-product length *and* the scale-free angle at P1 — because a long
thin sliver can have a numerically large cross product and still be junk.

### 4.2 `align_options.rb`

`Sketchup.read_default` / `write_default`, section
`CoordinateCoordinatorTrussAppAMAC_Align`, keys `flip_normal` and `copy_mode`.
`truthy?` accepts both booleans and the strings `'true'`/`'false'` so an older
stored value cannot break. `show_dialog` is a `UI.inputbox` with `No|Yes` and
`Move|Copy` dropdowns and returns `false` on Cancel.

### 4.3 `align_tool.rb` — one base class, two tools

`initialize(loose_geometry_allowed)`: `true` for `AlignFaceToFaceTool`,
`false` for `AlignGroupByNodesTool`. That flag is the **only** behavioural
difference besides prompt wording.

State machine: `@phase` is `:source` then `:target`; `@planned` is the pair
count (3 by default, lowered by Enter or the VCB); `@source_pts` / `@target_pts`
hold `Geom::Point3d`s.

Things worth knowing before editing it:

- **Coordinate spaces.** `InputPoint#position` is **model** space, while
  `instance.transform!` and `entities.transform_entities` work in the current
  editing context. `local_transformation` conjugates:
  `ET⁻¹ · T_model · ET` with `ET = model.edit_transform` (a no-op at the top
  level). Without this the feature is wrong whenever the user is inside a
  group or component.
- **Selection filtering** (`collect_items`) sorts the selection into
  `instances / faces / edges / locked (count) / unsupported (count)`. Locked
  objects are skipped and counted; unsupported types are ignored and counted;
  both are reported in the result summary. `ensure_items` re-reads the
  selection lazily, which is what makes "select after activating the tool"
  work.
- **Status messages** all go through `@message` + `update_ui`, which writes the
  message *and* the standing prompt together. See section 6 — this is where
  the one real bug was.
- **Copy mode.** Groups use `Group#copy` (guarded by `respond_to?`), because
  `add_instance(group.definition, …)` would return a *ComponentInstance* and
  silently turn a group into a multi-instance component. Component instances
  use `parent.entities.add_instance(definition, transformation)` and then
  `copy_instance_properties` (name, material, layer/tag, hidden,
  casts/receives shadows, attribute dictionaries).
- **Loose geometry copy** rebuilds each face in a fresh group from
  `outer_loop.vertices.map(&:position)`, then for each inner loop adds a face
  and `erase!`s it — which leaves the loop's edges behind and so punches the
  hole back through. Per-face material, back material and layer are carried
  over. The group is then transformed, so the original is never touched.
- **Deform warning** (`attached_geometry?`): collect the edges of all moving
  faces plus the selected loose edges, take their vertices, and if any edge at
  those vertices is *not* in the moving set, the selection is welded to
  something that will be stretched → `UI.messagebox(..., MB_OKCANCEL)`,
  `IDCANCEL` aborts before any operation is opened. Copy mode skips the check
  because nothing deforms.
- **Guards before touching the model**: determinant checked for +1 (refuses
  otherwise rather than mirror/scale), identity solution reported as a no-op
  with **no** undo step written, and the whole apply wrapped in
  `start_operation('Align by Points', true)` with `abort_operation` on any
  exception.
- **Preview**: the ghost is the selection's bounding-box corners (transformed
  by `edit_transform` into model space) run through the *pending* solution,
  which includes the point currently under the cursor; drawn as 12 dashed
  `GL_LINES` segments. Picked points draw as markers plus a `GL_LINE_STRIP`
  chain and `A1…B3` labels at `view.screen_coords`.

---

## 5 · How to build and test it

```bash
ruby tools/test_align_math.rb      # 42/42 — the math
ruby tools/test_align_tool.rb      # 55/55 — the tools, against the stub API
python3 tools/build_rbz.py         # writes dist/…rbz, after verifying it
python3 tools/make_align_icons.py  # only if the icons need regenerating
```

Neither test needs SketchUp. Ruby 3.3.6 and Python 3 were used here; there is
no gem or pip dependency anywhere in this work (the extension's XLSX
reader/writer are hand-rolled for exactly that reason, a pre-existing choice).

`build_rbz.py` refuses to write the archive unless: every source `.rb` is
packaged, every `require File.join(MY_DIR, '…')` resolves to a packaged file,
every `File.join(MY_DIR, 'icons', '…')` exists in the archive, `ruby -c`
passes on every file, and every `.rb` opens the
`CoordinateCoordinatorTrussAppAMAC` module. That last set of checks exists
because the 0.1.0 release shipped without `model_import.rb` /
`xlsx_reader.rb` and raised `LoadError` on a menu item it advertised.

`tools/sketchup_stub.rb` is a **test double**, not an emulator: `Geom::Point3d`
/ `Vector3d` / `Transformation` (real 4×4 column-major multiply and affine
inverse) / `BoundingBox`, `Sketchup::{Model, Entities, Selection, Group,
ComponentInstance, ComponentDefinition, Face, Edge, Loop, Vertex,
AttributeDictionary, InputPoint}`, `UI.messagebox` / `inputbox` with a scripted
answer queue, `Sketchup.read_default` / `write_default` / `format_length`, and
a `StubView` that records what was drawn. It implements only what the tool
calls, and it records what the tool did (transform log per entity, operation
log per model, message-box texts) so the tests can assert on it.

What the 55 tool checks cover: the pick state machine, all three modes,
flip, move vs copy (including that a copied group is still a `Group` and keeps
name/attributes), collinear and coincident rejection for both A and B
triplets, identical frames, locked / empty / late / unsupported selections,
the group tool refusing loose geometry and noting a non-vertex pick, the
deform warning with **both** answers, the hole-punching copy path, Esc twice,
Enter with no picks and Enter for a reduced mode, the VCB (valid and invalid
input), F/C toggles with persistence, `draw`/`getExtents`, the options dialog
including Cancel, and the `edit_transform` conjugation.

---

## 6 · Bugs found while testing (both fixed)

1. **Status messages were being wiped before the user could read them.**
   Every rejection notice ("those points are collinear", "that point
   coincides", "already identical", the result summary) was written to
   `Sketchup.status_text` and then immediately overwritten by the prompt
   refresh (`update_ui`) one or two lines later. Found by the stub tests, five
   of them failing at once. Fixed by routing everything through `@message`,
   which `update_ui` renders **together** with the standing prompt; the
   message is cleared by the next successful pick, not by mouse movement (so
   a notice survives while the user hovers). Consequence worth keeping in
   mind: never call `Sketchup.status_text =` directly in this tool — call
   `notify`.
2. **A bug in the test double itself**: `UI.inputbox`'s stub did
   `@queued.shift || defaults`, which swallowed a queued `false` — the real
   API's "user cancelled" answer — so the Cancel path silently tested the
   accept path. Fixed to test the queue for emptiness instead. Worth
   remembering when extending the stub: `false` and `nil` are meaningful
   answers in this API.

---

## 7 · Decisions and their reasons

| decision | why |
|---|---|
| Vendor the extension source into the repo | it existed only inside a hand-built `.rbz`; without source in git there is no reviewable diff and no reproducible build |
| Math as plain arrays, API only at the edge | makes it testable without SketchUp, which is the only way any of this could be verified here |
| Flip as a 180° turn about the frame's X axis | keeps det = +1; the obvious alternative (negate N) mirrors the geometry |
| `Group#copy` for groups, `add_instance` for components | `add_instance` on a group's definition returns a ComponentInstance and makes the group multi-instance — a silent type and behaviour change |
| Rebuild loose faces loop-by-loop for the copy | there is no "duplicate these entities" call; `add_group(entities)` *moves* them |
| Conjugate by `edit_transform` | model-space picks vs context-space transforms; otherwise wrong inside a group |
| Keep the tool alive after applying | aligning several objects in a row is the normal workflow; picks reset, selection re-read |
| Soft note (not a veto) for a non-vertex pick in the nodes tool | the spec says nodes, but a free-space pick is still useful and vetoing it would be annoying |
| Commit the built `.rbz` into `dist/` | so it can be downloaded straight from the branch without a build step |
| Write a stub API + 97 checks | no SketchUp in this environment; a syntax check alone would have caught none of the bugs in section 6 |

---

## 8 · What is open

1. **The 21-item manual checklist in `ALIGN_BY_POINTS.md` has not been run** —
   there is no SketchUp in the environment this was built in. That is the one
   real piece of outstanding verification. It covers 1/2/3 pairs, mismatched
   distances, flip on/off, move vs copy, collinear rejected, coincident
   rejected, locked group, loose face attached to a solid (Cancel **and** OK),
   single-step undo, empty/late/unsupported selection, identical frames, Esc,
   the live preview, the nodes tool (including that internal geometry is
   unchanged), working inside a group context, option persistence across a
   restart, and a regression pass on the three pre-existing commands.
2. **Known limitations of the loose-geometry copy path**: faces are rebuilt
   from loop vertex positions, so `Sketchup::Curve`/arc metadata, edge
   smooth/soft flags and hidden-edge state are **not** carried over, and
   copied edges keep only their layer. Fine for flat polygonal truss
   geometry; would need work for curved or smoothed surfaces. Groups and
   components are unaffected (they are duplicated whole).
3. **Attribute copying is one level deep** — `copy_attributes` walks
   `attribute_dictionaries` and its key/value pairs, not nested
   sub-dictionaries. Enough for ordinary dynamic-component attributes; not a
   general deep copy.
4. **No rubocop-sketchup run** — the gem is not installed here. The code
   follows the conventions the existing files document in comments (namespaced
   everything, UTF-8 `__FILE__` handling, `suspend`/`resume` invalidation),
   but it has not been linted.
5. **No pull request was opened** (none was asked for). The branch is pushed
   and ready if one is wanted.
6. Deferred by design, not bugs: no in-tool undo of a single picked point
   (Esc clears the sequence, matching `pick_tool.rb`'s existing choice); no
   roll control in 2-pair mode (inherent to the mode); arrow/Ctrl/Shift keys
   left unused, as the spec allowed.

---

## 9 · Picking this up in a new session

Paste something like this:

> The repo `marsellaaugusto-ai/STRUCTURAL-SYMULATOR-2`, branch
> `claude/amazing-cori-dt1fvj`, holds a SketchUp extension under
> `sketchup_extension/`. Read `sketchup_extension/HANDOFF_ALIGN_BY_POINTS_2026-10-13.md`
> first, then `ALIGN_BY_POINTS.md`. The "Align by Points" feature is built,
> tested in stock Ruby (`ruby tools/test_align_math.rb` and
> `ruby tools/test_align_tool.rb`) and packaged
> (`python3 tools/build_rbz.py`), but has never been run inside SketchUp.
> <then say what you want: run the manual checklist, fix something it turned
> up, extend the feature, open a PR, …>

If the installable archive is what is needed rather than the source:
`dist/CoordinateCoordinatorTrussAppAMAC_v32_AlignByPoints_2026-10-04.rbz`
(extension version 0.3.0) — install via SketchUp's Extension Manager →
*Install Extension…*. Rebuild it any time with `python3 tools/build_rbz.py`;
the file name carries the version and the date automatically.

If feedback arrives from a real SketchUp run, the likely suspects in order:
inference behaviour at pick time (`@ip.pick` without a reference point),
`Group#copy` semantics on the installed SketchUp version, and anything about
`view.draw_text` placement — these are the three areas the stub cannot
faithfully reproduce. The math itself is covered by the 42 checks and is the
least likely place for a surprise.
