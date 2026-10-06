# What the BIM and detailing world already solved, and what we should take

**Date** 2026-10-06 · **Branch** `claude/v32-st01`

## What this is, and why it is the safest of the three studies

The previous study looked at drawing tools. This one looks at the building
and steel-detailing world, which is far closer to our problem — it has always
had to answer *"which of these are the same fabricated part, and what do we
call it on the drawing?"*

Most of what follows is anchored to **IFC**, the openly published data
standard for building information (ISO 16739), whose schema documentation is
public. Describing an open standard — and, better still, *targeting* it — is
the cleanest possible footing: it is published precisely so that independent
programs can interoperate. Where a commercial detailing program is named, it
is to describe documented behaviour factually, in my own words.

No code, documentation text or artwork is reproduced, and nothing was
decompiled.

---

## 1. The pattern we already built, confirmed by the standard

IFC separates a **type** from its **occurrences**: shared properties live on
the type, per-placement properties on each occurrence, joined by a typing
relationship. `IfcElementAssembly` has a matching `IfcElementAssemblyType`.

That is exactly the `Definition` / `InstanceNode` split in
`apps/stereo/scene/definitions.py` — intrinsic properties shared, extrinsic
per instance. **The architecture is the industry pattern**, which is good
news: the remaining work is surfacing it, not rethinking it.

More usefully, IFC names the thing we have been calling a group when it is
a fabrication unit:

> `IfcElementAssembly` — complex assemblies aggregated from several elements.
> Steel assemblies such as **trusses** and frames are represented by it, and
> `IfcElementAssemblyTypeEnum` includes `TRUSS`, `GIRDER`, `BRACED_FRAME`,
> `RIGID_FRAME`, `BEAM_GRID`, `ARCH`.

A truss is a named concept in the standard. We are not inventing a category.

---

## 2. The single most valuable idea: marks and numbering

In steel detailing the question "which parts are identical?" is not a
convenience — it is the deliverable. Documented behaviour, common to the
major detailing packages:

- Numbering **detects identical pieces and gives them the same piece mark**.
- It runs over the whole model and is **recomputed**, not maintained by hand.
- **A comparison tolerance is an explicit setting** (a default around 1 mm is
  documented, with the advice to tighten rather than loosen it).
- Identical-*looking* parts are deliberately given **different** marks when:
  - their **orientation** differs,
  - their **shop markings** differ — because they are then genuinely
    different objects to the fabricator, even with identical geometry,
  - a "keep the number if possible" setting preserves history.

### What this tells us about what we have

`content_digest` already answers "are these the same part?" by hashing
geometry, topology and nested references. Three concrete lessons:

1. **The tolerance must be a setting, not a constant.** We hash exact floats
   today. Two trusses a hundredth of a millimetre apart are one part to a
   fabricator and two parts to us.
2. **Orientation is part of identity** — and this agrees with the mirrored
   instance problem already flagged: a mirrored asymmetric section is a
   different part. We detect it; it should feed the mark.
3. **A mark is the output.** The digest is the comparison; the deliverable is
   `T1 ×12, T1/mirrored ×4` in a schedule. That is the step we have not
   taken, and it is small.

---

## 3. Assembly is not the same thing as a group

This is the distinction our single mechanism is missing, and the standard
makes it explicit by having both:

| | what it is | our word today |
|---|---|---|
| **Assembly** (`IfcElementAssembly`) | what is **fabricated and shipped as one piece** — it gets a mark, it is counted | "group" |
| **Group** (`IfcGroup`) | a **logical** collection — a zone, a stage, a region, a reporting set | "group" |

A *bay* is a logical group. A *truss* is an assembly. Today both are the same
object in our model, which is why the group panel has to serve take-off,
visibility, locking and analysis at once.

Detailing practice adds one more idea worth having: an assembly has a **main
part** that gives it its orientation and its mark — for us, the chord that
names the truss.

---

## 4. Classification: rules, not lists

Two things the analysis and BIM worlds do that we do not:

- **Groups are many-to-many.** In analysis packages a member can belong to
  several named groups, because those groups exist for *assignment, selection
  and output*, not containment. This resolves the tension in our own rules:
  "a rod belongs to exactly one group" is right for **containment and
  take-off**, and wrong for **selection and reporting**. The answer is not to
  relax the rule; it is to have the second axis.
- **Filters are rules, not membership.** A view filter is a saved query —
  *everything whose utilisation exceeds 1.0*, *every diagonal* — evaluated
  live. Nothing is assigned by hand, so nothing goes stale when the model
  changes.

We already carry `role` (top chord, bottom chord, diagonal) on every member
and never expose it. A rule-based filter over `role`, section, utilisation
and group would answer most of what the hide/show checkboxes are reaching for.

### Design groups

Analysis packages have long had **design groups**: members designed together,
taking the governing case across the set. That is precisely
`BakedModel.part_envelope`. We arrived at it from the Flyweight pattern; the
industry arrived at it from fabrication. Both roads lead there, which is a
good sign.

---

## 5. IFC as an export target

IFC has a **structural analysis domain**, and our data already fits it:

| ours | IFC |
|---|---|
| node | `IfcStructuralPointConnection` |
| rod | `IfcStructuralCurveMember` (with a `PredefinedType` and an `Axis` for the local z) |
| rod-to-node connection | `IfcRelConnectsStructuralMember` |
| group used as a fabrication unit | `IfcElementAssembly`, `PredefinedType = TRUSS` |
| our `Definition` | `IfcElementAssemblyType`, via the typing relationship |
| logical group | `IfcGroup` *(to verify against the current schema)* |
| role | a classification reference or property set *(to verify)* |
| supports | point connections with the restraint properties |

The documentation states that a curve member's end connections are point
connections, and that the connection relationship joins them — the same shape
as our members-and-nodes.

**Why this matters beyond tidiness:** it is an open standard with public
documentation, so aligning our vocabulary to it costs nothing legally, makes
the eventual export a mapping rather than a design exercise, and means our
words match the words a structural engineer already uses.

---

## 6. What to take, in order of value

1. **Marks and numbering.** Turn `content_digest` into piece marks on a
   schedule, with a **tolerance setting**, orientation in the identity, and
   mirrored copies marked separately. Highest value, smallest step, and it
   produces a deliverable a fabricator can use.
2. **Separate assembly from logical group.** One flag on a group: *this is
   fabricated as one piece*. Assemblies get marks and are counted; logical
   groups do not. This is the distinction that stops one mechanism carrying
   five jobs.
3. **Rule-based filters over `role` and friends**, replacing hand-maintained
   visibility and analysis membership.
4. **Align the vocabulary to IFC** as we go, so an export is later a mapping.
5. **A main part per assembly**, giving it orientation and mark.

### What not to take

- **Do not adopt a full type catalogue** for assemblies the way a BIM tool
  does. Our users draw a structure and discover repetition afterwards; the
  flow should stay *draw → recognise → promote*, which is what "Repeated
  parts" already does.
- **Do not let a classification axis own geometry.** Roles and filters select
  and report; they never contain.

---

## Sources

- [IfcStructuralAnalysisDomain (IFC 4.3)](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/ifcstructuralanalysisdomain/content.html)
- [IfcStructuralCurveMember](https://standards.buildingsmart.org/IFC/RELEASE/IFC4/ADD1/HTML/schema/ifcstructuralanalysisdomain/lexical/ifcstructuralcurvemember.htm)
- [IfcRelConnectsStructuralMember](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcRelConnectsStructuralMember.htm)
- [IfcElementAssembly](https://standards.buildingsmart.org/IFC/RELEASE/IFC4/FINAL/HTML/schema/ifcproductextension/lexical/ifcelementassembly.htm)
- [IfcElementAssemblyType](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcElementAssemblyType.htm)
- [IfcElementAssemblyTypeEnum](https://steptools.com/stds/ifc/html/t_ifcelementassemblytypeenum.html)
- [Numbering and multi-numbering setups (Tekla)](https://support.tekla.com/article/numbering-and-multi-numbering-setups)
- [Why identical parts get different part positions (Tekla)](https://support.tekla.com/it/node/135546)
- [Numbering in Advance Steel (Graitec)](https://advantage.graitec.com/en-CA/knowledgebase/article/KA-01616)
