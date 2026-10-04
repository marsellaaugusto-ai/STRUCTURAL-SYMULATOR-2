# Align by Points (extension v0.3.0)

Two tools that rotate and move a selection onto a target by picking matching
point pairs, with no scaling, skewing or mirroring: size, shape, material,
tag/layer, attributes and name all stay as they were.

* **Align Face to Face** — source may be loose faces/edges, groups or
  component instances (e.g. drop a flat truss onto an inclined roof plane).
* **Align Group by Nodes** — source restricted to groups and component
  instances, driven from their nodes. Only the instance transformation
  changes; the geometry inside is never edited.

Both appear in **Plugins → Coordinate coordinator truss app AMAC** and on the
extension's toolbar.

## Files

| File | Status | What it holds |
| --- | --- | --- |
| `coordinate_coordinator_truss_app_amac/align_math.rb` | **new** | Frame construction and the 1-/2-/3-pair solvers. Pure array arithmetic, no API calls, so it is unit-testable. |
| `coordinate_coordinator_truss_app_amac/align_options.rb` | **new** | Flip normal and Move/Copy, persisted with `Sketchup.write_default`, plus the options dialog. |
| `coordinate_coordinator_truss_app_amac/align_tool.rb` | **new** | `AlignByPointsTool` base class and the two tool classes (state machine, status bar/VCB, preview, apply). |
| `coordinate_coordinator_truss_app_amac/icons/align_{face,nodes}_{small,large}.png` | **new** | Toolbar icons (regenerate with `tools/make_align_icons.py`). |
| `coordinate_coordinator_truss_app_amac/main.rb` | modified | Requires the three new files; adds the menu items, the two option toggles and the toolbar buttons. |
| `coordinate_coordinator_truss_app_amac.rb` | modified | Version 0.2.0 → 0.3.0, description mentions the feature. |

Nothing else was touched: the Excel export, auto-detect and Stereo import
paths are byte-for-byte unchanged.

## Using it

1. Select what to move (before or after starting the tool — a selection made
   afterwards, e.g. from the Outliner, is picked up on the first click).
2. Pick 1–3 **source** points A1…A3 with normal inference (endpoint,
   midpoint, on-edge, on-face, intersection — it reaches inside groups
   without opening them).
3. Pick the same number of **target** points B1…B3.
4. The alignment applies on the last target pick, or on **Enter** at any
   point to use however many pairs are complete.

| Pairs | Result |
| --- | --- |
| 1 | Translation only: A1 → B1, no rotation. |
| 2 | A1 → B1, plus the minimum rotation about B1 aligning A1→A2 with B1→B2. No roll control. |
| 3 | Full rigid alignment: A1 lands on B1, A2 ends on the ray B1→B2 (at its own distance — distances need not match), and the A1-A2-A3 plane becomes coplanar with B1-B2-B3 with A3 on B3's side. |

Keys while a tool is active: **Enter** finish · **Esc** clear the picks,
**Esc** again leave the tool · **1/2/3** (VCB) fix the pair count ·
**F** toggle flip · **C** toggle Move/Copy. The status bar always shows the
current step, the live option state and the last message; the VCB shows
`picked/planned`. Distances are reported in the model's current units.

## Options

Both are remembered between sessions (`Sketchup.read_default` /
`write_default`, section `CoordinateCoordinatorTrussAppAMAC_Align`) and can be
set from **Align Options…**, the two checkable menu items, or F/C in-tool.

* **Flip normal** — the source lands face-to-back instead of face-to-face.
  Implemented as a 180° rotation of the target frame about its own X axis
  (Y→−Y, N→−N), so the determinant stays +1: a half turn, never a mirror.
* **Move / Copy** — Move transforms the selection in place. Copy leaves the
  original untouched: groups and components are duplicated (name, material,
  tag, attributes carried over, geometry shared through the definition only
  for components), and loose faces/edges are rebuilt — holes included — into
  a new group which is then transformed.

## Safety behaviour

* The whole thing runs inside one `model.start_operation('Align by Points', true)`
  / `commit_operation`, so one Ctrl+Z undoes it. Any exception aborts the
  operation and nothing is changed.
* Collinear triplets are rejected at pick time (cross product below 1e-6
  model units, or an angle under 0.1°) with a status-bar message; pick again.
* Coincident picks are rejected the same way.
* The transformation's determinant is checked before touching the model; a
  value other than +1 refuses the operation rather than mirror or scale.
* Identical source and target frames report "already identical" and write no
  undo step.
* Locked groups/components are skipped and counted in the summary.
* Unsupported entity types are ignored and counted in the summary.
* Loose geometry welded to geometry outside the selection raises an
  OK/Cancel warning that it will **deform** the neighbours (copy mode never
  does, so no warning there).
* Picking inside a group/component edit context is handled: the model-space
  transformation is conjugated by `model.edit_transform` before it is applied.

## Automated tests

```
ruby tools/test_align_math.rb    # 42 checks: the math
ruby tools/test_align_tool.rb    # 55 checks: the tool, against a stub API
python3 tools/build_rbz.py       # packages + verifies the .rbz
```

`tools/test_align_tool.rb` runs the real tool code against
`tools/sketchup_stub.rb`, a test double of the API subset used. It covers the
pick state machine, 1/2/3-pair modes, flip, move/copy, collinear and
coincident rejection, locked/empty/unsupported selections, the deform
warning (both answers), Esc, Enter, the VCB, F/C, drawing, and the edit-context
conjugation. It is not a substitute for the checklist below.

## Manual test checklist (run in SketchUp)

Set up: a flat rectangular face or a small truss group near the origin, and an
inclined face elsewhere (e.g. a rotated rectangle) as the target.

| # | Test | Expected |
| --- | --- | --- |
| 1 | **1 pair** — select the group, pick A1 on one of its corners, Enter, pick B1 on the inclined face. | Group translates so A1 sits on B1. Orientation unchanged. |
| 2 | **2 pairs** — pick A1, A2 along one of its edges, Enter, then B1, B2 along an edge of the inclined face. | A1 on B1; the A1→A2 edge now points along B1→B2; no scaling; roll is arbitrary. |
| 3 | **3 pairs** — pick A1, A2, A3 on the source face, then B1, B2, B3 on the inclined face. | A1 exactly on B1, A2 on the B1→B2 ray, source plane now coplanar with the target plane, A3 on B3's side. Size unchanged. |
| 4 | **Distances differ** — repeat 3 with B1-B2 much longer than A1-A2. | Still no scaling: A2 stops short of B2, on the ray. |
| 5 | **Flip off → on** — repeat 3 with Flip normal on (F or the menu tick). | Source lands face-to-back: same plane, flipped 180° about the B1→B2 axis. No mirroring (text/asymmetric geometry is not reversed). |
| 6 | **Move vs Copy** — run 3 with Copy on. | Original stays put; a transformed copy appears and is selected. Copy keeps name, material, tag and attributes. Run again with Move: the original itself moves. |
| 7 | **Collinear rejected** — pick A1, A2, then a third point on the same line. | Pick refused, status bar says the points would be collinear, still waiting for A3. Same for B3. |
| 8 | **Coincident rejected** — click the same vertex twice. | Second click refused with a message. |
| 9 | **Locked group** — lock the group, select it, start the tool and click. | Message that the locked object is skipped/unlockable; nothing moves, no undo step. |
| 10 | **Loose face attached to a solid** — select one face of a box, run 3 pairs with Move. | OK/Cancel warning that adjacent geometry will deform. Cancel → nothing changes. OK → the face moves and the box deforms (expected). With Copy → no warning, box untouched, a new group holds the copied face. |
| 11 | **Undo is one step** — after any successful alignment press Ctrl+Z once. | Everything returns to its previous state in a single undo ("Align by Points"). |
| 12 | **Empty selection** — start the tool with nothing selected and click. | Message asking for a selection; no crash. Then select from the Outliner and click again: it proceeds. |
| 13 | **Unsupported entities** — select a group plus a dimension/text. | The group aligns; the summary notes the ignored entity. |
| 14 | **Identical frames** — pick the same three points as source and target. | "already identical — nothing to do", no undo step created. |
| 15 | **Esc** — pick two points, press Esc, then Esc again. | First Esc clears the picks (markers vanish, "Picks cleared"); second leaves the tool. |
| 16 | **Preview** — while picking B points, move the mouse. | A dashed ghost box follows the cursor showing where the selection will land; A markers blue, B markers red, labelled A1…B3. |
| 17 | **Align Group by Nodes** — select a group, pick 3 of its nodes without opening it, then 3 target points anywhere. | Group lands as in test 3; opening it afterwards shows its internal geometry unchanged (same local coordinates). |
| 18 | **Group tool rejects loose geometry** — select a loose face and start Align Group by Nodes. | Message that it does not move loose geometry; nothing happens. |
| 19 | **Inside a group context** — double-click into a group, select geometry inside it, align it to points picked in that context. | The geometry lands where the picks say (no offset by the group's own transformation). |
| 20 | **Options persist** — set Flip on and Copy on, quit SketchUp, reopen. | The menu ticks and the tools' status bar still show Flip ON / Copy. |
| 21 | **Existing features still work** — run Pick Origin + Nodes…, Auto-Detect…, and Import from Stereo…. | Unchanged behaviour. |
