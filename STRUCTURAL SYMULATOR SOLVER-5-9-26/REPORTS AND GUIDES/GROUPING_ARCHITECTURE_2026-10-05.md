# Element grouping: data architecture and object model

**Date** 2026-10-05 · **Code** `apps/stereo/scene/`, `stereo_scene_bridge.py`, `stereo_app_scene.py`
**Tests** `test_scene_graph.py` (58) + `test_scene_persistence.py` (64) + `test_scene_integration.py` (25) = 147

## Originality

Everything here is derived from published, general software-engineering and
computer-graphics practice: the **Composite**, **Flyweight**, **Prototype**
and **Visitor** patterns as catalogued by Gamma et al. (1994); homogeneous
4×4 affine transforms and recursive scene-graph traversal as in any graphics
text (Foley & van Dam); Rodrigues' rotation formula; inverse-transpose
normal transformation; and the separation of *node* from *reusable content*
that every **open** scene-description specification uses.

No commercial program's source code, proprietary algorithm, internal data
format or interface design was consulted, reverse-engineered or reproduced.
The design was derived from this app's own requirements and from the
constraints its existing solver imposes. Where a decision could have gone
either way, the reason recorded is a structural-engineering reason, not a
resemblance to another product.

---

## 1. The problem this solves

`stereo_groups.py` already nests groups to any depth, and its two rules are
sound. But a group there is **a name over a set of rod indices**:

```python
{'id': int, 'name': str, 'parent': int | None, 'members': set[int]}
```

The geometry stays in one flat global `nodes` / `members` list. Three
consequences follow, and all three are felt in the current code:

1. **A group has no frame of its own.** Moving a bay means moving the nodes
   it happens to contain, so `stereo_transform` mutates world coordinates
   and the nesting is flattened on the first edit.
2. **A group cannot be placed twice.** The Module Editor's `roles` recover
   repetition *after the fact*, by detecting congruent cells — a measurement,
   not a declaration. Nothing in the model says "this is one part, built
   twice".
3. **Every renumber has to be chased.** `remap_members`, `member_remap`,
   `remap_by_endpoints` and `geometry_violations` exist to keep index sets in
   step with geometry that moved underneath them.

### The structural constraint that shapes everything

A stiffness matrix is assembled **globally**. The solver needs one flat node
list, one flat member list, and integer indices; it knows nothing about
ownership. Meanwhile the editor wants a hierarchy with local frames and
shared content. Serving both from one structure is what produces the present
tangle — either the hierarchy leaks into the solver, or global indices leak
into the hierarchy.

**So: the graph is the source of truth; the flat model is a build product.**
Derived, never edited, discarded whenever the graph changes. This is the
same principle `stereo_groups` already applies to node membership ("DERIVED,
never stored"), applied one level up.

---

## 2. Layers

```
┌─ Layer 4 ── RESULTS PROJECTION ─────────────────────────────────┐
│  per-branch diagnosis, take-offs, part envelopes                │
│  a LOOKUP over provenance, never a second solve                 │
└──────────────────────── BakedModel.members_under / part_envelope┘
                                   ▲
┌─ Layer 3 ── SOLVER (unchanged) ─────────────────────────────────┐
│  stereo_math.analyze(nodes, members, loads, supports)           │
└─────────────────────────────────────────────────────────────────┘
                                   ▲  flat arrays + provenance
┌─ Layer 2 ── BAKE / COMPILE ─────────────────────────────────────┐
│  recursive descent accumulating one world matrix                │
│  → weld coincident endpoints → emit (nodes, members)            │
│  → record MemberOrigin per member; resolve joint names          │
└──────────────────────────────────────────── apps/stereo/scene/bake.py┘
                                   ▲
┌─ Layer 1 ── AUTHORING GRAPH (source of truth) ──────────────────┐
│  SceneObject tree · local Transform per node                    │
│  GroupNode (unique) · InstanceNode → Definition (shared)        │
│  SceneDocument: root + library + meta, canonical id numbering   │
└──────────────── apps/stereo/scene/{objects,definitions,transform,document}.py┘
        ▲                                                   ▲
        │ from_records                            to_records │
┌───────┴───────────────────────────────────────────────────┴─────┐
│  Layer 0 ── PERSISTENCE: records.py (one record form, validated)│
│  codecs: JSON (project format, atomic) · Excel sheet · snapshot │
└───────────────── apps/stereo/scene/{records,persist}.py ────────┘
```

The package imports no Tk, no numpy, and knows nothing about steel sections
— a graph that needed a section catalogue could not be tested without one.

---

## 3. Class diagram outline

```
                        ┌───────────────────────────────┐
                        │ SceneObject          «abstract»│
                        ├───────────────────────────────┤
                        │ id: int                        │
                        │ name: str                      │
                        │ local: Transform               │
                        │ parent: SceneObject | None     │
                        │ meta: dict                     │
                        ├───────────────────────────────┤
                        │ children() -> tuple            │
                        │ transform_to_root() -> Transform  ◀── memoised
                        │ world_transform() -> Transform    ◀── refuses in a
                        │ set_local / apply_local           │   definition
                        │ set_world(target)                 ◀── uses inverse()
                        │ path() -> tuple[int, ...]         │
                        │ clone() -> SceneObject   «Prototype»│
                        │ accept(visitor)          «Visitor»  │
                        │ walk() / invalidate()             │
                        └───────────▲───────────────▲───────┘
                                    │               │
        ┌───────────────────────────┴───┐     ┌─────┴──────────────────────┐
        │ Primitive          «abstract» │     │ GroupNode     «Composite»  │
        │  (a LEAF: geometry in local   │     │  UNIQUE: owns its children │
        │   coordinates)                │     ├────────────────────────────┤
        ├───────────────────────────────┤     │ _children: list            │
        │ local_points()                │     │ is_definition_content: bool│
        └──▲────────▲────────▲──────────┘     ├────────────────────────────┤
           │        │        │                │ add / remove / reparent    │
   ┌───────┴──┐ ┌───┴─────┐ ┌┴──────────────┐ │ find / resolve_path        │
   │RodPrim.  │ │MeshPrim.│ │JointPrimitive │ │ descendants()              │
   ├──────────┤ ├─────────┤ ├───────────────┤ └────────────────────────────┘
   │a, b      │ │vertices │ │at: point      │                 ▲ owns
   │joint_a/b │ │faces    │ │key: str       │                 │ (composition)
   └──────────┘ └─────────┘ └───────────────┘     ┌───────────┴────────────┐
                                                  │ InstanceNode «Flyweight│
                                                  │              extrinsic»│
                                                  ├────────────────────────┤
                                                  │ definition_id: str     │
                                                  │ overrides: dict        │
                                                  │ children() == ()  ◀────┼─ leaf when
                                                  └───────────┬────────────┘   authoring,
                                                              │ refers to       subtree
                                                              ▼ (not owns)      when baked
                        ┌─────────────────────────────────────────────────┐
                        │ Definition            «Flyweight intrinsic»     │
                        ├─────────────────────────────────────────────────┤
                        │ id, name                                        │
                        │ content: GroupNode    ◀── ONE, shared by all    │
                        │ policy: TransformPolicy  (RIGID|UNIFORM|FREE)   │
                        ├─────────────────────────────────────────────────┤
                        │ allows(transform) -> bool                       │
                        └─────────────────────────────────────────────────┘
                                              ▲ registry
                        ┌─────────────────────┴───────────────────────────┐
                        │ DefinitionLibrary                               │
                        ├─────────────────────────────────────────────────┤
                        │ define / get / place / set_instance_transform   │
                        │ instances_of(root, id, nested=True)             │
                        │ reference_count / unused / purge_unused         │
                        │ would_cycle(id, content)   ◀── keeps it finite  │
                        │ mirrored_instances(root)                        │
                        └─────────────────────────────────────────────────┘

   free functions:  make_definition(lib, group)  ──▶ Definition + InstanceNode
                    make_unique(lib, instance)   ──▶ GroupNode  «Prototype»
                    make_all_unique / edit_in_place

                        ┌─────────────────────────────────────────────────┐
                        │ Transform               «immutable value»       │
                        ├─────────────────────────────────────────────────┤
                        │ m: tuple[16 floats]   row-major, affine         │
                        ├─────────────────────────────────────────────────┤
                        │ identity/translation/rotation/scale/mirror/about│
                        │ from_frame(origin, x, y, z)                     │
                        │ __matmul__  (compose: other FIRST)              │
                        │ inverse()                                       │
                        │ apply_point / apply_direction / apply_normal    │
                        │ is_rigid / is_uniform_scale / handedness        │
                        └─────────────────────────────────────────────────┘

                        ┌─────────────────────────────────────────────────┐
                        │ BakedModel               (a BUILD PRODUCT)      │
                        ├─────────────────────────────────────────────────┤
                        │ nodes: list[(x,y,z)]      ◀─┐ exactly what      │
                        │ members: list[dict]       ◀─┘ analyze() takes   │
                        │ origins: list[MemberOrigin]                     │
                        │ joint_nodes: {name: node_index}                 │
                        │ warnings: list[str]                             │
                        ├─────────────────────────────────────────────────┤
                        │ members_under(path) / nodes_under(path)         │
                        │ shared_nodes(depth) / rollup(path, res)         │
                        │ sibling_members(i) / part_envelope(res)         │
                        │ legacy_groups(root)   ◀── migration seam        │
                        └─────────────────────────────────────────────────┘
```

---

## 4. Requirement 1 — Composite

`SceneObject` is the common base; a leaf and a group differ in exactly one
respect, whether `children()` is empty. Every walker (bake, bounds, counts,
export, validity) is therefore written **once**, and nesting is unlimited and
uniform: a group holds groups, instances and primitives in any mixture at any
depth. Rules ask what the *context* is, never how deep a node sits — the
same choice `stereo_groups` made deliberately, and kept.

**The existing two rules get stronger, not weaker.**

| `stereo_groups` rule | How it survives |
|---|---|
| A rod belongs to exactly **one** group | Becomes a fact about trees: a child has one parent. `GroupNode.add` is the only door, and it detaches from the previous parent. There is no way to *express* a rod in two groups, so there is nothing to enforce. |
| A node belongs to **every** group touching it — derived, never stored | Becomes the **weld** step of the bake. Joints are not stored in the graph at all; they are what coincident endpoints turn into when it is compiled. |
| Everything unassigned is one implicit `Ungrouped` set | Objects parented directly to the document root. Not a second code path. |
| A group is locked until opened for editing | Unchanged in spirit and far cheaper to implement: moving a group is `apply_local` on the group, which moves its whole subtree and nothing else, with no per-node conflict analysis. |

### The one decision everything else follows from

**A rod holds its endpoints as coordinates in its own local frame, not as
indices into a shared node list.** That is what lets a subtree be moved,
copied or placed twenty times without touching anything outside it.

The cost, stated plainly: the graph no longer *states* that two rods share a
joint. That fact is re-established at bake time by coincidence within
`WELD_TOL_M` (1 µm, the same value and reasoning as
`stereo_transform.MERGE_TOL_M`). Tolerance can be wrong in both directions,
so `RodPrimitive.joint_a` / `joint_b` are the escape hatch: rods sharing a
`joint_key` weld regardless of distance, and rods that merely pass close by
with different keys stay apart. That covers both real failures — a pitched
piece whose generated coordinates land a millimetre apart and must still be
one joint, and two layers of a grid that come within a millimetre and must
not be.

`JointPrimitive` is the payoff that justifies the whole bake: supports and
loads are declared against **joint names**, and the bake reports which node
index each name landed on. Restraints stop being lost on every renumber.

---

## 5. Requirement 2 — Definition vs. Instance

```
GroupNode   ── make_definition() ──▶   Definition + InstanceNode
(unique: an edit affects it alone)     (shared: an edit affects all)
GroupNode   ◀── make_unique() ─────    InstanceNode
```

Both conversions **preserve the world frame** — nothing moves on screen.
If it did, the user would have to put it back and would not know exactly
where "back" was.

The Flyweight split is drawn where a structural model requires it:

| | lives in | because |
|---|---|---|
| **Intrinsic** — topology, local coordinates, sections, connection types | the `Definition`, once | these are what make it the same *fabricated part* |
| **Extrinsic** — placement matrix, instance name, overrides, and after a solve its **own forces** | each `InstanceNode` | two copies of one truss are the same part carrying *different load*; nothing above would be true if forces were shared |

`make_unique` is Prototype: a deep copy of the content is dropped in where
the instance was, keeping its placement. The definition and every other
instance are untouched. The definition is deliberately **not** purged even
if that was its last instance — finding a part gone from the library after
making the only copy unique would lose work; `purge_unused` is an explicit
step (and loops until it settles, because dropping one definition can orphan
the ones only it referenced).

`edit_in_place` returns `(content, instance_count)`. The count is the point:
the UI is expected to say *"this changes 24 other copies"* **before** the
edit. Needing no such warning is exactly the difference a user is choosing
when they pick a unique group instead.

### Three structural consequences, all enforced or exposed

1. **A placement must not change the part.** `TransformPolicy` defaults to
   `RIGID`. Rotate, move and mirror leave every member length and section
   property intact. A non-uniform scale does not: it stretches the rods and
   leaves the section properties describing a section that is no longer
   there — wrong stresses, with nothing on screen to show it. Scaling is not
   forbidden, it is **opt-in per definition**. That is the difference between
   a trap and a decision.
2. **A mirrored instance is a different part** whenever the section is
   asymmetric (an angle, a channel). `mirrored_instances` reads *world*
   handedness, because a mirror inside a mirrored bay is the right way round
   again, and what gets fabricated is what the world matrix says.
3. **Design is governed by the worst copy.** One shared definition is one
   part; the load it must carry is the **envelope over every instance**.
   `BakedModel.part_envelope` returns min, max and `worst_member` per part.
   Sizing a component from the selected instance is a mistake that leaves no
   trace on screen, because every copy looks right.

A definition containing an instance of itself, at any remove, is an
infinitely deep model. `would_cycle` refuses it at the point of edit — the
same call `stereo_groups.reparent` already makes, for the same reason: a
cycle is cheap to prevent and impossible to recover from gracefully.

---

## 6. Requirement 3 — Transformations

### Conventions (mixing any two silently mirrors or transposes a model)

- **Column vectors.** `M @ p` applies `M` to `p`; `A @ B` means "B first,
  then A". Composing down a hierarchy therefore reads
  `W_child = W_parent @ L_child`.
- **Row-major storage**, 16 floats, `m[r*4 + c]`. Storage order is not the
  maths; it is chosen only because it prints as it reads.
- **Right-handed**, with cyclic axis pairs (Y,Z) about X, (Z,X) about Y,
  (X,Y) about Z. Taking the pairs in index order gets Y backwards — the trap
  `stereo_transform.rotate_point` already documents. The tests pin the new
  rotations against the existing proven ones across three axes and five
  angles, so the two layers can never drift into mirroring each other.

### Downward accumulation

```
world(root)   = L_root
world(child)  = world(parent) @ L_child        ← one multiply per level
```

Two forms, for two different needs:

- `transform_to_root()` — **memoised**, for interactive queries (picking,
  drawing, bounds). A parent's answer is the only thing a child needs, so
  nothing is recomputed while nothing moves. `invalidate()` walks **down**,
  because that is the direction the dependency runs.
- The **bake passes an accumulator down** and caches nothing. This is not a
  duplication; it is the resolution of a real problem (below).

### The trap: "world" does not exist inside a definition

A definition's content appears everywhere its instances do, so one node of
it has as many world positions as there are instances. Caching one of them
is a bug waiting to be read as a feature.

So `transform_to_root()` is the honest primitive — it stops at whatever root
it reaches — and `world_transform()` **refuses** when that root is a
definition's content, with a message saying why, rather than returning one
of several right answers. World positions inside definitions belong to
**paths**, not to nodes, and paths are the bake's business.

### Upward: the inverse, which is what makes editing possible

A drag happens in world space; what gets *stored* is a local frame. So:

```python
L_new = W_parent.inverse() @ W_desired        # SceneObject.set_world
```

Getting this wrong is how a nested object **jumps** when dragged — it picks
up its ancestors' transforms twice. The same inverse is what lets
`reparent(keep_world=True)` drag a truss into a bay without it moving, and
what makes `make_definition` / `make_unique` visually invisible.

The affine structure is exploited rather than running a general 4×4 solve:
with `A` the 3×3 linear part and `t` the translation, the inverse is `A⁻¹`
with `−A⁻¹t`. Fewer operations, and it cannot invent a projective bottom row
out of rounding. A singular matrix raises rather than returning nonsense.

### Points, directions and normals are three different things

| | method | translation | why it matters here |
|---|---|---|---|
| position | `apply_point` | applies | node coordinates |
| direction | `apply_direction` | **dropped** | a rod's axis, and with it its section orientation. Transforming a direction as a point displaces it, so a member in a nested group points somewhere else entirely |
| normal | `apply_normal` | inverse-transpose | a plate face, a wind panel. Under non-uniform scale a normal must follow the inverse-transpose or it stops being square to the surface — and wind pressure is then computed on a face pointing the wrong way |

`Transform` is **immutable**: every operation returns a new one, so a cached
world matrix can never be mutated out from under the node that cached it.

---

## 7. The bake, and why provenance is the whole point

```python
baked = bake(root, library)                      # pure: root is not touched
res, err = stereo_math.analyze(baked.nodes, baked.members, loads, supports)
```

`nodes` is a list of `(x, y, z)`; `members` is a list of dicts with `'a'`,
`'b'`, `'conn'` and whatever section keys the model put in `meta`. **That is
exactly what the existing solver takes** — there is no adapter, and
`tests/test_scene_graph.py` closes the loop by solving a real baked truss
with its supports addressed by joint name.

Every baked member carries a `MemberOrigin`:

```python
path           # ids from the document root down to the rod, crossing instances
primitive_id   # which rod of the definition
definition_id  # which part, or None if unique
instance_path  # which COPY
```

That makes compilation **reversible as a lookup**:

| question | before | now |
|---|---|---|
| this group's rods, deep | `rods_of(groups, gid)` over stored sets | `members_under(path)` — membership *is* the path prefix |
| this group's nodes | derived from stored sets | `nodes_under(path)` |
| where branches hand load over | `shared_nodes(...)` | `shared_nodes(depth)` |
| per-branch quantities | `group_summary` + `totals_reconcile` | `rollup(path, member_res)` |
| the same part in every copy | *not expressible* | `sibling_members(i)` |
| what to size a component for | *not expressible* | `part_envelope(member_res)` |

No second solve anywhere — the same principle `stereo_reports.submodel`
already rests on: a branch's forces are a **view** of one whole-structure
solve, because a branch cut free of its neighbours is a different structure,
usually a mechanism.

**Determinism is a requirement, not a nicety.** Reports, Excel exports and
saved comparisons all name members by index. The walk is strictly depth-first
in child order and node numbers are issued in first-touch order, so the same
graph always bakes to the same numbering, and two bakes of a graph that only
moved compare member by member.

The welder checks the 27 cells around each point rather than one rounded
cell, so a model whose connectivity changed when it was moved by half a
tolerance — a real failure mode of naive spatial hashing — cannot happen.

Degenerate rods are **reported, never silently dropped**: dropping one would
disconnect the structure somewhere the user cannot see.

---

## 8. Migration — additive, in four steps

Nothing has to be rewritten at once. `stereo_groups.py` is untouched and
keeps working.

1. **Done.** `apps/stereo/scene/` plus its tests, imported by nothing.
2. **Done — see section 10.** The read path: the tab builds a graph from its
   own model, carries it in the workbook, and answers a question the flat
   model cannot be asked.
3. **Write path.** Build a graph from the current `(nodes, members, groups)`
   and hand old code `BakedModel.legacy_groups(root)` — the records every
   report, Excel sheet and summary already reads, with disjoint leaf sets
   that still add up to the model (the one check that catches a mis-assigned
   rod). Both paths run side by side; a test asserts they agree.
4. **Write path (next).** Move the group panel, the move/rotate/mirror keys and
   the lock rules onto graph operations. `move_plan` / `group_move_plan` /
   `geometry_violations` get much smaller: moving a group is one
   `apply_local`, and a shared joint between two groups is visible in
   `shared_nodes` before the move rather than deduced after it.
5. **Instancing in the UI.** "Make component" (`make_definition`),
   "make unique" (`make_unique`), and the instance-count warning from
   `edit_in_place`. `stereo_autogroup` becomes a *definition* detector:
   congruent pieces it already finds can be promoted to one definition
   placed many times, which is what the Module Editor's roles have been
   approximating from the other direction.

### Persistence — written, see section 9

### Known gaps, named rather than discovered later

- `Transform.scale_factors()` does not see **shear**. No constructor here can
  build one and the policies refuse a free matrix unless a caller insists, so
  the gap is narrow — but it is a gap, not a rounding error.
- Per-instance `overrides` are a flat dict merged onto baked members. Rich
  per-instance *geometry* variation (one copy with an extra rod) is
  deliberately not supported: that is what `make_unique` is for.
- `meta` is copied one level deep by `clone()`. A nested mutable inside
  `meta` would be shared between copies; don't put one there.
- The Excel codec packs `meta`, `overrides`, `vertices` and `faces` into
  JSON cells, and refuses a model whose cell would exceed Excel's 32767
  characters. Sections stay where they are edited today: the `Model` sheet.
- `validate` checks structure, not engineering. A file can be structurally
  perfect and describe a mechanism; that is the solver's judgement, not the
  loader's.

---

## 9. Persistence

`records.py` turns the graph into plain dicts and back; `persist.py` writes
those records in two formats. **Neither codec knows what a `SceneObject`
is** — a third format later is another codec, not another serialiser.

| | what it is for |
|---|---|
| **JSON** (`.scene.json`) | the project format: lossless, sorted, indented, diffable, written atomically |
| **Excel** (`Scene` sheet) | inspection and interchange, written into the **same workbook** as the `Model` sheet the tab already exports, in the same `[SECTION]` + named-column style |
| **snapshot/restore** | the undo stack: the same records, never touching a disk |

### Why JSON is the project format and Excel is not

A scene graph is a tree with cross-references, variable-length geometry and
free-form metadata. JSON holds all three exactly. A spreadsheet holds the
first two awkwardly and the third not at all — a mesh's vertex list has no
fixed column count. So the Excel form carries structure and geometry in
readable columns and packs the rest into JSON cells, which is **honest about
the trade rather than dropping it**, and refuses a cell over Excel's limit
rather than truncating one: a silently clipped vertex list is a model that
loads and is not the model that was saved.

### Four decisions

**1. File ids are not object ids.** A load builds fresh objects with fresh
session ids and keeps a map from the file's ids only while it wires parents
up. Adopting the file's ids means loading a file whose ids overlap the
session counter hands two live objects the same id, and every path lookup in
the graph is then quietly wrong. `from_records` returns that map as its
third value, because a load makes new objects and anything holding ids — a
restored selection — has no other way to follow them.

**2. Child order is file order.** The records carry `parent`, not a child
list, and a parent's children are rebuilt in the order their records appear.
One ordering rather than two that can disagree.

**3. Absent means default, never error.** No `xform` is identity, no `meta`
is empty, no `name` is unnamed. Writers omit what is default, so a file stays
small and its diff shows only what someone actually set — and, the same rule
from the other side, **a file written before a field existed still loads**.
That is the convention the existing `Model` sheet already follows by reading
its columns by *name*, and the Excel codec follows it too: a column inserted
by a future build does not shift the ones before it.

**4. A file is untrusted input** — not malicious, but hand-edited,
half-merged, written by an older build, truncated by a full disk.
`validate` separates the two kinds of wrong:

- **Structural impossibility** → raises, with a message meant for a person.
  A parent cycle, a duplicate id, a missing parent, two definitions claiming
  one content root, a rod with no endpoint, **a definition that contains
  itself**. There is no graph to build.
- **Recoverable gap** → a warning, and the rest of the model loads. An
  instance whose definition is missing, an unknown `kind` from a newer
  build, an orphan nothing places. A user with a damaged file wants the
  other 99% of their work back, not a dialog. `strict=True` promotes the
  warnings for an importer that would rather refuse than guess.

A skipped object takes its subtree with it. Re-parenting the children to the
root would be worse than dropping them: they would appear in the model at
the wrong place and nothing on screen would say so.

The self-containing definition is worth singling out. The library refuses to
*build* one, so it can only arrive from a hand-edited or half-merged file —
and without the check the file loads happily and the **bake** finds out 64
levels down, having already emitted whatever it met on the way. The loader
refuses it instead, naming the loop (`'def1' -> 'def2' -> 'def1'`).

### Canonical numbering

In-memory ids come from a session counter: cheap, never reused, and
deliberately **not** what gets saved. A counter cannot promise that two
files built by the same steps come out the same — an object created and
deleted still consumes an id, so a model built, half undone and rebuilt
saves differently from the same model built once. A saved model that differs
from an identically-built one **cannot be diffed**, and a diff is how a
person checks what their last hour of editing actually changed.

So a save renumbers: ids `1..N` in the deterministic walk order, derived
from tree position alone. Definitions likewise, ordered **depth-first by
first use**, so a loader never meets a reference it cannot resolve yet and
inserting a component does not rewrite the whole table in the diff.

The renumber is applied to the **live document**, not to a copy written out.
Writing a renumbered copy would leave file and memory disagreeing about
every id — invisible until something stores an id across a save. Instead the
maps come back, in the same spirit as `stereo_groups.remap_members`, and the
session id counter is pushed past the highest assigned so nothing created
later can collide.

### Atomic writes

A save interrupted by a full disk, a crash or a closed lid must not leave a
half-written file where the model used to be. `write_text` writes to a temp
file **in the target's own directory** (so the replace is a rename within
one filesystem — across filesystems `os.replace` falls back to a copy, which
is the non-atomic behaviour this exists to avoid), `fsync`s it (the rename is
atomic, but only for content the OS has actually written), then replaces.
The temp file is removed whether the write succeeded or not.

A truncated file says what to do about it: *"it was interrupted while saving
— the previous save is the one to go back to."*

### Undo snapshots

Records rather than `clone()`, because a snapshot must capture **the
document and its library together**: an undo across "make component" has to
put the definition back too, and records are the only form holding both.
`canonical=False`, because an undo must not renumber the model the user is
still looking at — a renumber mid-edit would invalidate their selection as a
side effect of pressing Ctrl+Z once.

### Recognising one part arriving twice

`content_digest` hashes what a definition **is** — geometry, topology,
structure, nested definition references — and not its ids, names or
metadata. Two trusses with the same bars are the same part whatever they
were called, which is what an importer or a merge needs to know: bringing in
a file containing the same component twice should **offer** to reuse one
definition rather than silently stocking two parts indistinguishable on the
drawing and distinguishable in a take-off. It is an offer, not a rule — a
user may be keeping two names apart on purpose. (`-0.0` and `0.0` hash
alike, so a mirror does not make a part stop matching itself.)

### How it is tested

A round trip that "does not raise" proves nothing: an import that drops a
section, or reads a column into the wrong key, produces a model that loads
cleanly, analyses cleanly, and is **not** the model that was saved — the
same reasoning `tests/test_excel_roundtrip.py` gives for the `Model` sheet.
So the tests compare the **baked** model field by field across the round
trip (nodes, members, sections, joint names, provenance, mesh geometry,
definition digests and tree shape), deliberately **not** the ids, since a
load makes fresh objects and a canonical save renumbers on purpose —
comparing ids would fail on a correct round trip and pass on one that
scrambled the geometry.

Also pinned: that the same model built twice saves byte for byte
identically; that awkward floats (`1/3`, `1e-9`, `1e12`, `-0.0`) survive
exactly, because a layer that rounds moves the model a little every time it
is opened; that **sharing** survives, since a file that loses it loads as a
model that looks identical and behaves differently the moment someone edits
a component; that a loaded model still solves through `stereo_math.analyze`;
and thirteen separate ways of being a broken file.

---

## 10. Wiring it into the Stereo tab

Two modules, both additive. With no Scene sheet in a workbook, every path
behaves exactly as it did.

```
stereo_scene_bridge.py   flat model <-> graph. Tk-free, so the conversion is
                         tested without a window.
stereo_app_scene.py      StereoSceneMixin: the tab's use of it.
```

### The document is derived, never mirrored

`_scene_document()` builds a fresh graph from the current model every time it
is asked. `self.groups` is assigned in **eleven places across five modules** —
import, merge, paste, undo, example load, generate, the group panel — and a
stored document kept in step with all eleven would be wrong the first time
one was missed, and wrong **silently**, because a stale graph still bakes.
Building it on demand cannot go stale. Models here are thousands of rods, and
the conversion is a few milliseconds.

### What the conversion adds, and what it cannot

A flat model has no local frames, so `graph_from_model` **introduces** them,
one per group at the centroid of that group's own rods — the pivot convention
`stereo_transform` already uses, so a group rotated through the graph turns in
place exactly as the arrow keys turn a selection today. `localize=False` gives
identity frames instead, which round-trips bit for bit.

What it **cannot** add is sharing: two identical trusses in a flat model are
two sets of rods, and nothing in the file says they are one part. The graph
cannot invent that — but `content_digest` can recognise it after the fact,
which is what the **Repeated parts** button reports.

### The member order changes, and that is reported

A bake orders members by **tree position**, so a grouped rod comes before an
ungrouped one whatever their original indices: a conversion renumbers the
member list. Reports, Excel sheets and saved comparisons all name members by
index, so a renumbering that is not reported points them at the wrong rods.
Each rod therefore remembers the index it came from
(`MEMBER_INDEX_KEY`), `model_from_graph` strips that key back off (so the
solver gets the dict it always did) and returns the map — which is exactly
what `stereo_groups.remap_members` takes.

This is also what makes the Scene sheet safe to read back: groups are
re-attached to rods by the index they came from, never by position. A
workbook whose two sheets disagree about how many rods there are has been
edited by hand, and is **refused** rather than half-applied.

### The three seams

| where | what changed |
|---|---|
| `StereoApp` | one more mixin in the list |
| `stereo_reports.export_excel` | a `scene=` parameter beside `groups=`, `lifts=`, `compare=`. Writes the **Scene** sheet. Failing to write it never fails the export — the rest of the workbook is the deliverable |
| `_import_excel` | reads a Scene sheet when the workbook has one; falls back to the Groups sheet, unchanged, when it does not |

Plus three buttons in the Groups panel, under *More group tools*, beside the
checks that were already there: **Repeated parts**, **Save scene…**,
**Open scene…**.

### What is deliberately NOT done

The flat `(nodes, members, groups)` triple is **still the model**. Nothing in
this step edits it, and no group operation is rerouted through the graph.
Rerouting the lock rules and the move plans is a change to *behaviour*; this
step is not, and mixing the two would make a regression impossible to
attribute. That is step 4 above.

### Verification

The conversion is held to changing nothing, on **real generated models** —
the tab's own geometry generators, grouped by the tab's own auto-grouper,
including a case with 37 nested groups — comparing every rod's position,
every section key, every group's membership and every support. The wiring
itself is driven through a real `StereoApp`, the way
`tests/test_excel_roundtrip.py` argues for: a hand-written state dict encodes
what the model shape was the day the test was written and drifts silently,
while the tab's own methods are the ones the buttons call.
