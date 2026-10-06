# Streamlining groups and components — analysis and proposal

**Date** 2026-10-06 · **Branch** `claude/v32-st01`

## Originality

What follows observes the *user-facing behaviour* of a widely documented
modelling workflow and uses it to derive design principles. No code, asset,
file format or interface artwork is copied, decompiled or reproduced. Where
a principle is adopted it is re-derived for a structural model of nodes and
rods, which — as section 3 shows — breaks several of the assumptions that
workflow rests on. The result is our own design, informed rather than
imitated, exactly as asked.

---

## 1. What is actually wrong today

Read from the code, not from impressions.

### The model underneath is mostly right

`stereo_groups.py` already has: unlimited nesting, one owner per rod,
derived node membership, a current context (`_group_open` / `_group_step_out`),
and a breadcrumb (`_group_path`). **The data model is not the problem.**

### The interaction surface is the problem

| what you do | what happens today |
|---|---|
| click a rod | selects **that rod** |
| double-click a rod | makes its group "current" *in the panel* |
| double-click again | the group above it |
| press Delete | deletes **nodes/rods** — it has never heard of groups |
| panel "Delete group" | **dissolves the group; the rods survive, Ungrouped** |

Three findings follow, and they explain the frustration exactly.

**1. There is no "delete a group" at all.** The button called *Delete group*
performs what SketchUp would call **Explode**: the container goes, the
geometry stays. There is no command anywhere that removes a group *and* the
rods in it. So the Delete key is not merely unbound — the operation it would
perform does not exist.

**2. Selection and the group tree are two different worlds.** Clicking
selects rods. Double-clicking moves a highlight in a side panel. Nothing you
do on the canvas ever *selects a group as an object*, so a group can never be
the thing you move, copy, delete, or drag — it is only ever a filter applied
from a list.

**3. Four pieces of state model one idea.** `_group_editing` (which group is
open), `_group_sel` (which row is current), `Pick inside group` (a checkbox),
and `Dim others` (another checkbox) are four controls for one question:
*what am I working on right now?* Each was added to patch a gap left by the
others. That is what "fragmented" means in practice, and it is why the panel
has fourteen buttons.

**The work is therefore mostly routing, not rebuilding.** The operations
exist; they are reachable only from a panel, and the panel is not where your
hands are.

---

## 2. How the reference workflow behaves, and why

Observed behaviour, then the principle under it.

| behaviour | the principle it encodes |
|---|---|
| A click selects the outermost closed container, never its contents | **One selection unit per context.** You cannot accidentally grab a part of something you meant to move whole. |
| Double-click enters it; outside dims but stays visible; Esc leaves | **Context replaces mode.** There is no "edit groups" mode — there is a place you are standing, and a breadcrumb saying where. |
| Nested containers: double-click again goes deeper | **One rule at every depth.** Nothing special about level 2. |
| Geometry drawn inside a container belongs to it | **Ownership follows context, not a later assignment step.** This is the single biggest workflow saving: there is no "add to group" button because there is nothing to add — you drew it there. |
| Delete removes the container *and* its contents; Explode removes only the container | **Two different verbs, two different names.** Conflating them is exactly our bug. |
| Right-click on the object offers its operations | **Operations live on the thing, not in a distant board.** |
| An Outliner shows the tree; selection is two-way; drag reparents | **The list reflects the model; it does not control it.** |
| A component has a *definition*; all instances share it; "Make Unique" detaches one | **Shared content is explicit**, and so is leaving it. |
| Containers stop geometry merging with its neighbours | **A container is a boundary against unwanted fusion** — see 3.1. |

---

## 3. Where our domain genuinely differs

This is the part a copy would get wrong.

### 3.1 Our geometry fuses at the joints, on purpose

In that workflow, containers exist largely to stop touching geometry from
merging. We have the same phenomenon in a sharper form: two rod ends at the
same point **must** become one joint, or the structure is a mechanism with a
hinge nobody drew. Our weld tolerance is the fusion rule.

But a structural group must NOT prevent welding. A truss bolted to the next
truss shares a real joint, and that joint is how load passes between them.

**So a container is a boundary of OWNERSHIP, never of CONNECTION.** That is
the opposite of the reference behaviour, and getting it backwards would
silently disconnect structures. Our existing rules already say this — a rod
belongs to one group, a node belongs to every group touching it, derived —
and they stay exactly as they are.

### 3.2 A group cannot be analysed on its own

Contents can be edited in isolation; they cannot be *solved* in isolation. A
branch cut free of its neighbours is usually a mechanism. Per-group results
are therefore a view of one whole-structure solve — which is what
`stereo_reports.submodel` already does and what the scene graph's provenance
makes a lookup.

### 3.3 A shared definition is a fabricated part

Instances of one definition are not just visually identical: they are **the
same part, made once, installed many times**. Two consequences with no
analogue in a drawing tool:

- it must be sized for the **worst** of its copies, never the selected one;
- a **mirrored** instance is a different part whenever the section is
  asymmetric (an angle, a channel).

Both are already computed (`part_envelope`, `mirrored_instances`); they need
somewhere in the UI to appear.

### 3.4 Moving a group is constrained by its neighbours

A shared joint belongs to two groups. Moving one group alone would move a
joint the other group owns too. The current code already refuses this and
names the joints — correct, and worth keeping rather than smoothing away.

---

## 4. The proposed model

### 4.1 One context, one selection

```
click a rod            selects the whole group that owns it, in this context
Alt+click              selects the individual rod (the escape hatch)
double-click           ENTER that group: it becomes the context
Esc                    leave, one level up
breadcrumb             Model › Roof 1 › Bay 3        (always visible)
```

Inside a group, the same rule one level down: click selects its children —
a rod, or a subgroup as one object.

**This retires `Pick inside group`, `Dim others`, `_group_sel` and the
separate "Open group" button.** Four controls become one place you stand
plus one thing you have selected.

### 4.2 Verbs that say what they do

| key | verb | what it does |
|---|---|---|
| `Delete` | **Delete** | the selected group **and its rods** |
| `G` | **Group** | a group from the selection |
| `Shift+G` | **Explode** | dissolve the container; rods survive (today's "Delete group") |
| `Enter` / double-click | **Enter** | step into the group |
| `Esc` | **Leave** | step out |
| right-click | the rest | rename, lock, hide, make component, make unique |

Renaming today's destructive-sounding button to **Explode** is half the fix
on its own.

### 4.3 Ownership follows context

Draw a rod while inside a group and it belongs to that group. No assignment
step, no button. "Add selection to group" stays for fixing up imports, but
stops being the normal path.

### 4.4 The panel becomes an outliner

A tree: name, rod count, visibility, lock. Selection two-way with the canvas.
Drag to reparent. The fourteen buttons drop to a handful, because the rest
moved onto the object's right-click menu.

### 4.5 Components, with the structural part added

Make Component, Make Unique, and the "this changes N copies" warning before
editing shared content — all three already exist in `apps/stereo/scene/`.
What is missing is the panel surface, plus showing the envelope and the
mirrored-part warning where someone sizing a component will see them.

---

## 5. Importing groups from SketchUp

### What the extension does today

`model_export.rb`:

```ruby
entities.grep(Sketchup::Edge).each do |edge|   # line 52
```

called with `view.model.active_entities` (`pick_tool.rb:108`).

**The extension has no concept of groups or components at all.** Not a gap in
what it writes — a gap in what it *looks at*. Two consequences:

1. **No hierarchy travels.** There is nothing to import, because nothing is
   collected.
2. **Geometry inside any group or component is invisible to it.** `grep` over
   one entities collection does not recurse, so edges nested in a group are
   never seen unless you have entered that group first. A model organised the
   way SketchUp encourages exports as *empty or partial* today.

The import side (`model_import.rb:233`) does `ents.add_group` — one group
around the whole model, so a round trip also collapses whatever structure it
had.

So this is **new capability in the Ruby, not a tweak**: recurse the entity
tree, compose each container's `transformation` down the path, and record
which container each edge came from.

### The mapping is exact

| SketchUp | ours |
|---|---|
| `Sketchup::Group` | `GroupNode` (unique) |
| `Sketchup::ComponentInstance` | `InstanceNode` |
| `Sketchup::ComponentDefinition` | `Definition` |
| instance `transformation` | the instance's local `Transform` |
| nesting | the composite tree |

That the correspondence is one-to-one is the strongest evidence the scene
graph is the right target for this import. The workbook's **Scene** sheet
already carries exactly this shape, so the Ruby writes that sheet and the
existing importer reads it.

### Work required

1. `model_export.rb` — recurse groups/components, compose transformations,
   emit a path per edge, and a definition table for components.
2. `xlsx_writer.rb` — write the Scene sheet.
3. `model_import.rb` — rebuild real containers instead of one flat group.
4. A version handshake, so an old extension and a new app (or the reverse)
   say so plainly rather than importing half a model.

**Reinstalling the .rbz in SketchUp will be required.**

---

## 6. Suggested staging

Each stage is usable on its own and can be judged before the next starts.

| stage | what changes | felt as |
|---|---|---|
| **1** | click selects the group · Delete deletes it · Explode renamed · Esc/double-click context · breadcrumb | the two complaints fixed, immediately |
| **2** | right-click menu on canvas · retire the four redundant controls · ownership follows context | far fewer buttons, nothing lost |
| **3** | outliner panel with two-way selection and drag-to-reparent | the list stops being a control board |
| **4** | components in the UI: make/unique/envelope/mirrored | the part-level work the flat model never could do |
| **5** | the SketchUp extension: recursive export, Scene sheet, round trip | groups survive the import |

Stage 1 is the one you asked for twice, so it goes first.

---

## 7. Decisions needed before stage 1

1. **Delete = group + rods?** Today's only "delete" is an explode. Proposed:
   Delete removes both; Explode (Shift+G) removes only the container.
2. **Group-first selection by default?** Proposed: yes, with Alt+click for
   the single rod.
3. **Lock.** Today every group is locked and you open one to edit. Under a
   context model, lock becomes an explicit per-group flag. Existing tests pin
   the old rule.
4. **Does your SketchUp work actually use groups/components today**, and
   should component instances come in as *shared definitions* (one part,
   many copies) or as plain groups?
