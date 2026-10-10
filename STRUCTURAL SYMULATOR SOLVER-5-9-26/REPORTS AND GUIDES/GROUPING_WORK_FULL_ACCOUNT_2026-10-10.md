# Grouping: full account of the five tasks

**Date** 2026-10-10 · **Branch** `claude/v32-st01` · **Extension** 0.5.0
**Code** `apps/stereo/stereo_marks*.py`, `stereo_components.py`, `stereo_roles*.py`,
`stereo_partlib.py`, `stereo_app_{marks,components,outliner,partlib}.py`,
`sketchup_plugin/.../{model_export,intersections,model_groups_in}.rb`
**Tests** 427 across 14 files (listed per task below), inside a suite of 4523

## Originality

Everything here derives from published, general software-engineering practice
and from structural-engineering and fabrication requirements: the **Composite**
pattern for the containment tree; **Flyweight** for one definition built many
times; canonical-form hashing, as used in graph isomorphism and geometry
dedup generally; principal-axis frame selection from a point cloud; and the
long-standing fabrication convention that identical pieces carry one mark and
a count.

No commercial program's source code, proprietary algorithm, internal data
format or interface design was consulted, reverse-engineered or reproduced.
Where a decision could have gone either way, the reason recorded is a
structural-engineering or fabrication reason, not a resemblance to another
product.

## The diagnosis this all rests on

The app had been treating one word, "group", as three unrelated jobs. Keeping
them apart is what made the rest tractable:

| Axis | Question it answers | Shape |
|---|---|---|
| **Containment** | what is inside what | a tree: one parent |
| **Reuse** | which of these are the same part | a reference: many instances, one definition |
| **Classification** | which pieces count as X | a cross-cut: any piece in any number of sets |

Two rules follow, and both are load-bearing:

- **Derived, never stored.** Node membership, piece marks, `_excluded_rods`
  and the scene document are all computed from geometry on demand. A stored
  answer can disagree with the model; a derived one cannot.
- **A container bounds ownership, never connection.** Rod ends still fuse
  across a group boundary. This is the opposite of a drawing tool's
  behaviour, and it is deliberate: a bolted joint does not stop being a
  joint because someone drew a box around one side of it.

## Task 1 — Direct manipulation · B and C

**B** put the verbs under the pointer: select, enter, delete a group where
the user is already looking, instead of in a distant panel.

**C** made the group list an actual tree (`stereo_app_outliner.py`, 375
lines). A `ttk.Treeview` replaced the flat `Listbox`: expand/collapse,
drag to reparent, and a refusal to drop a branch inside itself — which
would make a cycle and is the one move the containment axis cannot allow.

Three bugs worth recording:

- `_may_drop` read the dragged row from `self._drag_from`, which the drop
  handler clears first, so **every drop was refused**. The refusal tests
  passed anyway, because a refused drop and a broken one look identical
  from outside. The helper now asserts the outliner is laid out.
- Collapse memory survived `_drop_groups`. Group ids restart at 1, so an
  imported model could open with an unrelated branch collapsed.
- Closing a branch that held the selection hid it, and the next refresh
  reopened the branch to show it again. Closing now takes the selection
  with it.

**Tests** `test_outliner.py` (27)

## Task 2 — Piece marks · B and C

**B** answers "which of these are the same, and how many" by geometry
(`stereo_marks.py`, 637 lines). A part's signature is its length plus its
section; an assembly's is a canonical geometric signature: the point cloud
chooses its own frame — farthest node from the centroid, then farthest off
that line, then the cross product — and is quantised to a tolerance.

Ties in that choice **are** symmetries, so a tied pick still places the
geometry correctly. The tolerance errs toward *different* on purpose:
marking two identical trusses apart costs one duplicated drawing, while
marking two different trusses the same sends the wrong steel to site.

**C** keeps a mark's number stable across revisions without storing the
mark. What is stored is a **signature to number** map, which cannot be
wrong — it either matches a part in the model or it matches nothing. So
the register reconciles with "derived, never stored" rather than
contradicting it. Numbers can be issued and withdrawn.

One bug: the register was absent from the undo snapshot, so undoing an
issue left the model held to numbers that had never been issued.

**Tests** `test_stereo_marks.py` (62) + `test_marks_integration.py` (38)

## Task 3 — Roles as a real axis · B, C, and persistence

**B** made classification its own axis (`stereo_roles.py`): a role is a
question asked of the model, not a frozen list of rods.

**Persistence** put saved rules in the workbook on a `Rules` sheet
(`stereo_roles_excel.py`), so they travel with the model.

**C** lets a rule decide what the analysis contains. This is where the
work had to **refuse** something: utilisation comes *out* of the analysis,
so a rule asking about utilisation cannot decide what goes *in* without
circularity. It is refused in three places — `new_rule`, `excluded_by`
(which deliberately takes no `checks` argument, so it cannot see results
even by accident), and the sheet reader. The decisive test is that
pressing Analyze twice gives the same numbers.

The app also now refuses to analyse when every rod has been excluded,
rather than solving an empty model.

**Tests** `test_roles_axis.py` (27) + `test_roles_persistence.py` (32)
+ `test_exclusion_by_rule.py` (16)

## Task 4 — Components · B and C

**B** made one part buildable many times (`stereo_components.py`): copies
are sized together and marked once, and `verify` reports copies that have
drifted out of agreement with the rest.

**C** took a component across files (`stereo_partlib.py`): `.part.json`,
format `STEREO-PART/1`.

The design decision that mattered, and that I got wrong first: a part is
stored relative to an **anchor node** — the part's own node nearest its
bounding-box low corner — not relative to the bounding-box corner itself.
The corner is usually *not* a node, so placing a part on a joint landed
nothing on that joint, nothing fused, and the part floated beside the
model. `anchor_of` returns `None` for files written before the fix.

Placing is `stereo_merge.merge_models`, not a second paste path, so rods
fuse at the seam, a taken group name is renamed, and a part placed exactly
where it came from adds nothing — the alternative being a second rod
hidden inside the first, doubling a stiffness with nothing on screen to
show it.

**Tests** `test_stereo_components.py` (28) + `test_components_integration.py`
(27) + `test_partlib.py` (29) + `test_partlib_integration.py` (21)

## Task 5 — SketchUp · B, C, and shared parts

**B** made the export follow groups and components. Measured against the
shipped 0.2.0 code, the old behaviour was worse than "unsupported": a
grouped truss exported as *"No edges found"*; a group plus loose edges
reported *"Exported 3 nodes and 3 members"* while silently dropping three;
picking inside a group gave *"Exported 3 nodes and 0 members"*. Fixed by
`each_world_segment`, which walks containers recursively in world space.

**Shared parts**: a component definition's contents are *one* entity set
shared by every instance, so nested containers report the same
`persistent_id` across copies. Components therefore arrive as shared parts
rather than as unrelated look-alikes.

**C** is the round trip back out (`model_groups_in.rb`, 331 lines): groups
read from the workbook are rebuilt as real containers, positioned by a
rigid transform fitted between point clouds, and emitted as component
instances where two groups are the same part.

Two bugs: `collect_segments` still built 2-element path entries after
`each_world_segment` moved to 4, so components came back `None`; and
`name_components` used a Ruby single-quoted `'×'` (a literal
backslash-u) and could hand two different parts the same label, which
would have merged them.

**Tests** `test_sketchup_export_groups.py` (59) +
`test_sketchup_import_groups.py` (32)

## Old workbooks keep their group facts

A model saved before this work has a `Scene` sheet that never recorded the
group flags, and that sheet won on import — so `excluded` was still being
lost *today*, after the first fix. `_carry_group_flags` now matches groups
by **rod set**, falling back to name for branches. `tools/check_excluded_groups.py`
sorts a folder of workbooks into FINE / WORTH A LOOK / NO GROUPS.

A related pre-existing bug surfaced here: `stereo_merge` carried group
facts from its own hardcoded tuple, which had drifted from `GROUP_FLAGS`
and was dropping `component`. Merging two models that each had components
left look-alike groups that would then be sized apart.

**Tests** `test_check_excluded_groups.py` (13)

## The workbook surface

| Sheet | Written by | Read by |
|---|---|---|
| `Model` | `_write_model_sheet` | model open |
| `Groups` | `stereo_groups_excel` | model open |
| `Scene` | `scene/persist.py` | model open |
| `Rules` | `stereo_roles_excel` | `import_rules` |
| `Piece Marks` | `stereo_marks_excel` | report only (derived) |
| `Mark Register` | `stereo_marks_excel` | `_register_from_workbook` |

`Piece Marks` is written but never read back, and that is correct: marks
are derived. Only the register — the signature-to-number map — is read.

## Audit, 2026-10-10

Verified: every module exists and is tracked; every engine has a real
consumer in app code, not only in tests; all four new mixins are in
`StereoApp`'s bases with their `_init_*` calls firing; every feature has a
UI entry point; the Ruby file is required at load **and** in the builder's
`REQUIRED_RB`, which hard-fails without it; no `TODO`/`FIXME`/stub remains
in the new modules; all nine carry module docstrings.

Two gaps were found by this audit, not by the test suite:

1. **The launch configurations were never committed** (fixed, `dea18e5`).
   `.gitignore` had a blanket `.vscode/` rule, so the commit meant to add
   `launch.json` and `tasks.json` went in carrying only the rebuilt
   archives. `git add` skips an ignored path silently and `git status`
   stays clean, so there was nothing to notice. The files existed locally,
   their three tests passed locally, and the zip shipped them — because the
   builder copies from disk — while a fresh clone had neither and its Run
   button failed exactly as before. The rule now keeps those two files,
   and a new test asserts **tracked-ness** rather than existence, because
   reading from disk can never catch this.

2. **`USER_GUIDE.html` documents none of it** (open). The guide was last
   touched 2026-10-03, before this work, and is hand-written rather than
   generated. Piece marks, the outliner, part files and components have no
   user-facing documentation.

## Known limits

- Stable marks rely on the tolerance. Two trusses differing by less than it
  share a mark; the tolerance is user-settable for exactly that reason.
- `anchor_of` is `None` for `.part.json` files written before the anchor
  fix; those place on the bounding-box corner as before.
- A rule cannot ask about anything the analysis produces. This is a refusal,
  not a gap.
