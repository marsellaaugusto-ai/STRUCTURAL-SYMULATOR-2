# Relative load scaling, and an app-wide unit convention — 2026-09-10

Two features from the recommendations pass, both requested with specific
notes. Suite **862 → 1000 passed**, 0 failed — 138 new tests, almost all of them
pinning the unit conversions against published equivalents.

---

## 1 · Loads are drawn relative to each other, compressed

**The note:** *"the larger the force the larger the representation with respect
to the others present in the diagram. I don't want the loads to have 1:1 ratio
in the representation, that would be messy and unreadable."*

Before, every load glyph was a fixed size regardless of magnitude — a 500 kN
point load and a 5 kN one drew the same 45 px arrow; distributed loads were a
flat 30 px band; truss loads and reactions a flat 44 px; moment arcs a flat
12 px radius. The picture carried no information about magnitude at all.

`common.LoadScale` now sizes every glyph relative to the largest of its own
kind on the model, with a square-root-ish compression (`gamma = 0.70`).

### Why not linear, and what the compression buys

A model routinely carries loads two or three orders of magnitude apart. Drawn
1:1, either the small load collapses to a stub or the large one runs off the
canvas — there is no scale factor that avoids both. Measured against the
default band:

| force ratio | drawn ratio | smallest glyph |
|---|---|---|
| 2 : 1 | **1.44 : 1** | — |
| 5 : 1 | 2.15 : 1 | — |
| 10 : 1 | 2.73 : 1 | 17.6 px |
| 100 : 1 | 4.17 : 1 | 11.5 px |
| 1000 : 1 | 4.66 : 1 | **10.3 px** |

The band and exponent were chosen against that table rather than by eye: a 2:1
difference had to be visible at a glance (an earlier `gamma = 0.5` gave only
1.22:1, too subtle), and the smallest glyph had to stay above ~10 px so an
arrowhead still reads.

### Why each kind of load is scaled separately

Point loads are a force (kN), distributed loads a force per unit length
(kN/m), moments a moment (kN·m). There is no honest linear scale between them,
and sharing one would break something that matters more: **two distributed
loads of equal intensity must draw at equal height whatever length each
covers**, which only holds when the distributed family is normalised against an
intensity of its own. Each family therefore has its own reference maximum and
its own pixel band, chosen so the families stay visually comparable without
pretending kN and kN/m are the same quantity.

### Where it applies

| tab | before | after |
|---|---|---|
| Beam — point loads | flat 45 px | 10–48 px, relative |
| Beam — moments | flat r = 12 px | 7–17 px, relative |
| Beam — distributed | flat 30 px | 5–34 px, follows q(x) |
| Truss — loads | flat 44 px | 16–56 px, relative |
| Truss — reactions | flat 44 px | 16–56 px, own scale |
| Cable — point loads | flat 22 px | 12–40 px, relative |

Arch draws no load arrows on its schematic, so there was nothing to scale.

### Two things that came with it

**Labels are lifted clear of the load band.** Point-load and moment labels used
to land inside the distributed-load block. The tallest drawn ordinate is now
computed first and labels clear it — while the *arrows* still run to the beam at
their true scaled length, since a shifted arrow would falsify the scale.

**`common.declutter_text`** nudges overlapping canvas labels apart. Two loads at
the same station put their labels in the same place; rather than invent a
placement rule per label type, whichever was drawn later is lifted until
nothing overlaps. Measured on a deliberately pathological case — four point
loads, a moment and two distributed loads, two of them at exactly x = 9 — text
collisions went **9 → 0**. Nothing is ever lifted off the canvas: where a pane
is too short, labels stay overlapped, which is visible, rather than
disappearing, which is not.

---

## 2 · A unit convention chosen once, above all the tabs

**The note:** *"a button that is above all the tabs and not in them ... choose
the unit convention from ANSI, CIRSOC, European, Brazilian, and Canada"*, with
conversion at the UI threshold.

A selector now sits **above the notebook**, so it applies to every tab at once.
A per-tab copy would let the Beam tab read in kip while the Truss tab read in
kN, which is exactly the confusion the feature exists to prevent.

### What these five conventions actually differ in

Worth stating plainly, because the list suggests more variety than there is:
**CIRSOC, Eurocode, NBR and CSA are all SI.** They differ in which SI sub-unit
is customary — cm² vs mm², GPa vs MPa — and in notation, not in the system of
measurement. Only AISC is a different system.

So this is honestly *one US-customary system plus four SI presentation
profiles*. Defining them separately still earns its keep: an engineer reading a
CIRSOC calculation expects cm² and cm⁴ and one reading CSA expects mm² and mm⁴,
and being handed the other is real friction even though no number changed
meaning.

| | length | section | area | inertia | stress | modulus |
|---|---|---|---|---|---|---|
| CIRSOC | m | cm | cm² | cm⁴ | MPa | GPa |
| Eurocode | m | cm | cm² | cm⁴ | MPa | GPa |
| NBR 8800 | m | cm | cm² | cm⁴ | MPa | GPa |
| CSA S16 | m | mm | mm² | mm⁴ | MPa | MPa |
| AISC 360 | ft | in | in² | in⁴ | ksi | ksi |
| *(storage)* | m | cm | cm² | cm⁴ | kN/cm² | GPa |

The differences between those codes that **do** matter — resistance factors,
load-combination coefficients, capacity equations — are not unit conversions
and are deliberately not in `units.py`. `cirsoc_301.py` is where that lives.

### The property that makes this safe

Switching conventions is **purely cosmetic**. It converts on the way to a label
and back from an entry box; it never rewrites stored state. Every tab keeps
holding kN, m, cm², cm⁴, GPa — declared as its own `STORAGE` system — so a
saved model and an exported workbook mean the same thing whatever happens to be
selected when they are written.

That property is the central test, asserted across all four foreign
conventions and on a there-and-back switch:
`test_switching_convention_never_rewrites_stored_state`. Its complement —
`test_the_analysis_answer_is_the_same_whatever_the_convention` — would catch a
conversion accidentally applied to the model instead of to the label.

### Verified end to end on the Beam tab

Same model, same instant, two conventions:

| | CIRSOC | AISC |
|---|---|---|
| beam length | 10.0 m | 32.808 ft |
| E | 200.0 GPa | 29 008 ksi |
| I | 8000 cm⁴ | 192.2 in⁴ |
| allowable bending σ | 160.0 MPa | 23.206 ksi |
| reaction at the pin | +30.00 kN | +6.74 kip |
| column heading | `P (kN)` | `P (kip)` |

and `_current_state()` byte-identical across the switch.

### One deliberate mistake worth recording

The first draft had **Pa → ksi out by a factor of 1000**. It would have printed
every AISC stress a thousand times too large while every other number on screen
stayed correct — the kind of defect that survives review because nothing
crashes. The constants are now derived from the three exact definitions
(1 in = 0.0254 m, 1 ft = 0.3048 m, 1 lbf = 4.4482216152605 N) rather than
written as remembered decimals, and `tests/test_units.py` pins each one against
a published equivalent rather than against the module itself.

---

## 3 · State of the rollout, honestly

`units.py` (127 tests) and the selector are complete and app-wide. **The Beam
tab is wired end to end** — toolbar, table headings, dialogs, section panel,
results text, schematic and diagram labels, all repainting on a change.

**The other five tabs are not wired yet.** They keep showing their own units,
which are the storage units, so nothing they display is wrong — but they will
not follow the selector until each is given the same treatment. Beam is the
reference implementation and the pattern is mechanical: a `_FIELD_Q` map, the
`_shown`/`_stored` pair, and a `units.on_change` listener that repaints.

Nothing about that half-state is unsafe: the selector cannot change stored
data, and an unwired tab simply ignores it.
