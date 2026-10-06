# How other programs organise a model — and what it means for ours

**Date** 2026-10-06 · **Branch** `claude/v32-st01`

## What this document is, and is not

It describes the **publicly documented, user-facing behaviour** of widely
used programs, in my own words, to inform our own design. Functional
concepts, workflows and ideas are not protected by copyright — which covers
expression, not function — and naming a product to describe what it does is
ordinary factual reference.

Nothing here reproduces another program's source code, documentation text,
icons or interface artwork, and nothing was decompiled or reverse-engineered.
Behaviour details change between releases; verify any specific before relying
on it. Where a design decision of ours happens to resemble one of theirs, it
is because both answer the same problem, and section 2 shows the problems are
not always the same.

Two practical cautions, neither of them legal advice: do not copy UI artwork
or wording, and if we ever build something genuinely unusual rather than an
industry commonplace, a patent search is a real step for a professional.

---

## 1. The one idea that explains all of them

Every program here is solving **three different problems**, and the confusion
in ours comes from using one mechanism for all three.

| axis | the question it answers | typical names |
|---|---|---|
| **Containment** | *what belongs to what?* — a strict tree, one parent each | group, folder |
| **Reuse** | *which things are the same thing?* — one source, many placements | component, block, symbol, smart object |
| **Classification** | *what kind is this?* — cross-cutting labels, any object, any branch | layer, tag |

Containment is a **tree**. Classification is a **cross-cut** — it deliberately
ignores the tree, which is the whole point: "every top chord in the building"
is not a branch of anything. Reuse is a **reference**, not a place.

A program feels clean when these three stay separate and messy when one is
asked to do another's job. That single sentence is the most useful thing in
this document.

---

## 2. Program by program

### SketchUp — surface modeller

- Raw geometry is **sticky**: edges and faces that touch merge. A **group**
  is first of all a wall against that stickiness — a container so its
  contents stop fusing with their neighbours.
- **Groups behave as independent copies.** Copy one, edit it, and the other
  is unchanged.
- **Components** are the reuse axis: a named definition, many instances,
  editing the definition changes every instance, and *Make Unique* detaches
  one. Components carry an insertion point and axes, can be saved to a file
  and re-loaded, and can be set to glue to or cut openings in a surface.
- **Tags** (called layers before 2020) are the classification axis, and are
  deliberately weak: they control **visibility only**, never containment.
  The documented habit is to leave raw geometry untagged and tag the groups
  and components instead.
- The **Outliner** is the containment tree: nest, rename, hide, lock.
- Workflow: click selects the outermost container; double-click enters it and
  the rest dims; Esc leaves; right-click offers the object's own verbs;
  anything drawn inside a container belongs to it.

**Cleanest separation of the three axes of any program here.**

### AutoCAD — drafting

- The **layer** is the organising idea, and it carries **properties**:
  colour, linetype, lineweight, transparency, plot style, printable or not,
  on/off, freeze/thaw, lock. Objects normally inherit them ("ByLayer"), so a
  layer is classification *and* formatting at once. Layers are **flat** —
  no nesting — with naming conventions and filters standing in for structure.
  **Layer States** save and restore whole configurations.
- **Blocks** are the reuse axis and are strong: a named definition, inserted
  many times, edited in one place and updated everywhere. Three features
  matter to us:
  - **Attributes** — named fields carried *per insertion* (a mark, a size, a
    note), extractable into a schedule. This is how a drawing becomes a
    bill of materials.
  - **Dynamic blocks** — one definition with parameters, so a family of
    sizes is one block rather than twenty.
  - **Nested blocks** and a defined base point.
- **Groups** in AutoCAD are *only a selection convenience*: a named set that
  selects together, toggleable. They are **not** containers, have no frame of
  their own, and objects keep their layers. **This is almost exactly what our
  groups are today** — worth knowing, because our users expect the SketchUp
  meaning of the word.
- **Xrefs** bring in whole external drawings by reference.

**The lesson is attributes and layer states, not the layer system itself.**

### Adobe Illustrator — vector

- The **Layers panel is the containment tree**: layers, sublayers, groups
  and individual objects all appear in one outline, with stacking order,
  visibility, lock and selection shown together and synced two ways with the
  canvas.
- **Isolation Mode**: double-click a group to work inside it with everything
  else dimmed and inert — the same context idea as SketchUp, arrived at
  independently.
- **Symbols** are the reuse axis: definition plus instances, with *Break
  Link* to detach one.
- Appearance and Graphic Styles share *formatting* without containment —
  a fourth axis, closer to our sections and profiles than to groups.

**The lesson is the panel: one tree that reflects the model rather than a
board of buttons that commands it.**

### Adobe Photoshop / InDesign — briefly

- **Layer groups** are folders: containment, named, collapsible.
- **Smart Objects** are reuse with an explicit choice: a plain duplicate
  shares the source, so editing one changes both, while "new smart object via
  copy" makes an independent one. **Linked** smart objects point at an
  external file.
- InDesign adds **master pages** — inheritance of a template, which is reuse
  of *arrangement* rather than of an object.

**The lesson is making "shared or independent?" an explicit choice at the
moment of copying**, instead of a surprise discovered later.

### Closest to our domain

Structural BIM tools (families and assemblies, piece marks, cast units) are
nearer to us than any of the above, because they already treat a shared
definition as **a fabricated part**: it gets a mark, it is counted, it is
detailed once and installed many times. Worth looking at next if this is
useful.

---

## 3. The comparison

### 3.1 How each axis is handled

| | **SketchUp** | **AutoCAD** | **Illustrator** | **Ours today** | **Ours proposed** |
|---|---|---|---|---|---|
| **Containment** | Group, nested; Outliner | *(none — blocks nest, but drawing has no tree)* | Layers panel tree with groups and sublayers | `stereo_groups` tree, nested | same tree, surfaced as an outliner |
| **Reuse** | Component + instances; Make Unique | Block definition + references; attributes; dynamic | Symbol + instances; Break Link | **none** | `Definition` / `InstanceNode` (built, not yet surfaced) |
| **Classification** | Tags — visibility only | Layer — visibility **and** properties; flat; layer states | folded into the layers tree | **none** (roles exist in the data, unused) | a role/tag axis over the existing `role` field |
| **Selection unit** | outermost container | object; groups select together | object, or group | rod | **group (stage 1 — done)** |
| **Enter to edit** | double-click, Esc out | Block Editor / REFEDIT | Isolation Mode | right-click / Esc | double-click, Esc (stage 1 — done) |
| **Delete vs dissolve** | Delete vs Explode | ERASE vs EXPLODE | Delete vs Ungroup | **only dissolve** | Delete vs Explode (stage 1 — done) |
| **Ownership of new work** | follows the open context | layer dropdown, set before drawing | follows the open context | manual "add to group" | follows the context (stage 2) |

### 3.2 The verbs

| action | SketchUp | AutoCAD | Illustrator | ours today | ours proposed |
|---|---|---|---|---|---|
| make a container | Make Group | GROUP *(selection set)* | Group | New group from selection | same, `G` |
| make it reusable | Make Component | BLOCK | Make Symbol | — | Make Component |
| detach one copy | Make Unique | *(explode + re-block)* | Break Link | — | Make Unique |
| go inside | double-click | Block Editor | double-click | right-click | double-click |
| come out | Esc | close editor | Esc | Esc | Esc |
| add to it | draw inside it | — | drag in the panel | a button | draw inside it |
| remove the container | Explode | EXPLODE | Ungroup | "Delete group" | **Explode** |
| remove it and contents | Delete | ERASE | Delete | **missing** | **Delete** |

### 3.3 What a container carries

| property | SketchUp group | AutoCAD block | Illustrator symbol | ours today |
|---|---|---|---|---|
| own origin / frame | yes | yes (base point) | yes | **no** (scene graph adds it) |
| transform per placement | yes | yes | yes | no |
| name | yes | yes (definition) | yes | yes |
| nesting | yes | yes | yes | yes |
| visibility | via tags | via layers | in the panel | on the group |
| lock | yes | via layers | yes | on the group (always, implicitly) |
| per-placement data | — | **attributes** | — | — |
| counted in a schedule | via components | **via attributes** | — | per-group totals |

---

## 4. What our groups are actually being asked to do

Today one mechanism carries **five jobs**:

1. containment (which rods belong together) — *a tree, correctly*
2. visibility (hide/show)
3. locking (what may be edited)
4. analysis membership (leave out of analysis / put back)
5. reporting and section assignment (per-group take-off, apply a section)

Jobs 2 and 4 are **classification**, not containment: "hide every diagonal"
and "leave the temporary bracing out of this run" are cross-cutting
questions. Forcing them through a strict tree is why the panel grew a
checkbox for each.

**And there is no reuse axis at all** — which is why the same truss drawn
four times is four unrelated sets of rods.

---

## 5. The path ahead

1. **Keep groups for containment only.** Stage 1 made a group a thing you can
   select, enter and delete. Stages 2–3 take the rest of the buttons off it.
2. **Add the classification axis we already half-have.** `role` is written by
   the auto-grouper (top chord, bottom chord, diagonal) and read by reports,
   but a user cannot see or select by it. Making roles first-class — select
   by role, hide by role, report by role — removes the pressure on the group
   tree to answer cross-cutting questions. **This is the biggest single win
   still unclaimed, and most of the data is already there.**
3. **Surface the reuse axis.** `Definition` / `InstanceNode` are built and
   tested; they need Make Component, Make Unique, and the two things a
   drawing tool never has to show: the **sizing envelope over all copies**,
   and the **mirrored-handedness warning**.
4. **Borrow attributes, in structural clothing.** AutoCAD's per-insertion
   attributes are how a drawing becomes a bill of materials. Ours is the
   **piece mark**: a per-instance mark on a shared definition, so a schedule
   can say "T1 ×12, T1-mirrored ×4".
5. **Borrow layer states, in ours.** Saved configurations of what is visible
   and what is in the analysis — which is what the Iterations/compare feature
   is already reaching towards.
6. **One outliner.** The Adobe lesson: a tree that *reflects* the model, with
   two-way selection and drag-to-reparent, instead of a list plus fourteen
   buttons that *command* it.

### Where we must not follow

- **A container must never block connection.** In a surface modeller a group
  stops geometry fusing; here two rod ends at one point *must* fuse or the
  structure has a hinge nobody drew. Ownership, never connection.
- **Analysis stays whole-model.** A branch cut free of its neighbours is
  usually a mechanism, so per-group results are a view of one solve.
- **A shared definition is a fabricated part**, so it is sized for its worst
  copy, and a mirrored instance of an asymmetric section is a different part.
  No drawing tool has to care; we do.
