# Truss tab — selection box, undo/redo, clipboard, guides and arrays

**Date:** 2026-09-07

One bug and five features, all on the Truss tab. Verified by driving the real
widgets and looking at the result (MANIFESTO §2), with the geometry checked
against closed forms.

---

## The keyboard map

Not the usual one, and deliberately so — it is what was asked for:

| key | action |
|---|---|
| `Ctrl+Z` | undo |
| `Ctrl+X` | **redo** — *not* cut. There is no cut. |
| `Ctrl+C` | copy, about a base point |
| `Ctrl+V` | paste at the cursor |

The shortcuts are bound tab-wide (`bind_all`) so they work wherever focus
sits, with two guards on every one of them:

* **not while typing.** Ctrl+Z inside a number field belongs to the field.
  Undoing the whole structure because someone mistyped a dimension would be
  startling.
* **not while another tab is showing.** `bind_all` is application-wide; in a
  six-tab notebook, without a `winfo_ismapped()` check the Truss tab's Ctrl+Z
  would fire while the user is looking at Cable Web.

---

## The bug: the selection box was invisible

`_on_drag_motion` had always stored the far corner in `_box_cur` and called
`_draw()`, and `_on_release` had always computed the right selection from it.
But **`_draw()` never read `_box_cur`** — there was no `create_rectangle`
anywhere in the file. Every geometric query was already correct; only the
feedback was missing, so you were selecting blind and the per-motion redraw
was pure cost with nothing to show for it.

Now drawn last (over the structure it is selecting), as a dashed band with a
light stipple and a live `w × h` readout in metres.

Pinned by `test_the_selection_box_is_actually_drawn`, which asserts on the
canvas item itself. Nothing weaker could have caught this: every geometry
check passed while nothing was visible. Confirmed by removing the band again
— 1 failed, 36 passed.

---

## Undo / redo

**Snapshot-based, not command-based**, and that is the important decision.
Node identity in this tab is the **list index**, and deleting a node
renumbers everything above it. A command log would need a correct inverse for
every operation that renumbers — exactly the class of bug that has already
bitten this tab twice (plates, and the delete remap). Snapshots sidestep the
question entirely, and the model is a few plain lists of small dicts, so a
deep copy costs microseconds.

* 16 mutators record a step, plus node placement, rod drawing, paste and all
  three arrays.
* Results, diagrams and plate checks are **not** snapshotted. They are derived
  from the model, and restoring a stale analysis beside an older model would
  show numbers that do not describe what is on screen. Undo clears them and
  the Analyze button greys out — the honest state.
* History is capped at 120 steps; a new edit discards the redo branch, as
  every editor does.

`test_every_mutator_pushes_undo` walks the mutators and fails if one stops
recording. That guard exists because the failure is silent: a new mutating
method that forgets `_push_undo` does not crash and does not misbehave, it
just quietly becomes un-undoable, and nobody finds out until they need it.

---

## Move a selection

**This did not exist before.** There was no way to reposition a node at all —
only create and delete. Now: press a selected node, drag, release.

The **cursor** is snapped and that one offset applied to every selected node,
rather than snapping each node independently. Snapping them independently
would distort the selection, which is the opposite of moving it.

One `Ctrl+Z` returns the selection to where the drag started, not to some
intermediate position: the before-state is pushed and the move re-applied on
top of it at release.

---

## Copy / paste about a reference point

`Ctrl+C` stores the selected geometry **with a base point** — the snapped
cursor if it is over a node or a grid point, otherwise the selection's
corner. `Ctrl+V` drops it offset by (destination − base). The base point is
what makes this a drafting tool rather than a rough duplicate: copy a bay
with its bottom-left node as the base, paste onto the next node along, and
the copy lands exactly.

**What travels:** nodes, the rods *between* selected nodes, and each rod's own
properties — profile, E/A/I, connection type, UDL, its own point loads.

**What does not:** supports, nodal loads and plates. Those are placed per
location, and silently duplicating a support or a load would change how the
structure behaves in a way that is easy to miss and hard to notice later.
Asserted by `test_paste_carries_rod_properties_but_not_supports_or_loads`.

---

## Construction geometry ("guides")

Curves you define by equation, drawn in the same view, that are **not**
structure: never analysed, never members, contributing nothing to the
stiffness matrix.

**On the name.** This tab already calls something else "ghost" —
`_compute_ghost`, the marker showing where the next node will land. These are
**guides** throughout, in the code and in the UI, so the two cannot be
confused by a future reader.

Three kinds: `y = f(x)` (through the existing safe expression compiler the
Arch tab uses, so `^` and implicit multiplication like `4(x+1)` both work), a
line through two points, and a circle/arc.

**"Curve" is now a fourth snap toggle** beside Grid / Node / Angle. It sits
after the node snap (an existing node still wins — you rarely want a new node
a millimetre off one you already have) and *before* grid, because landing
exactly on the guide is the whole reason the guide is there; grid snap would
drag the point back off the curve.

Guides also persist in the Excel model sheet as `[GUIDES]`. That was not
asked for, but reopening a model without the curve it was laid out on loses
the reason the nodes are where they are. Backward compatible in both
directions — a workbook without the section imports as a model without
guides.

---

## The three arrays

### Path array — the one with real math in it

Nodes distributed **along the arc length** of a guide, between two stations,
by count or by spacing, optionally chained with rods.

Arc length is the whole point. "Evenly spaced along the curve" is not equal
steps in x, and on a parabola the difference is large: equal-x spacing bunches
nodes where the curve is steep, which is exactly where a bridge chord needs
them spread evenly. Measured on a 20 m, 4 m-rise parabola with 9 nodes, the
x-steps run **2.24 m to 2.72 m** while the distance along the curve is
constant. If those x-steps had come out uniform, the feature would be wrong.

### Grid array
Rows × columns at a given dx, dy, from the selection. Includes the originals,
so 1 × 1 is a no-op rather than a duplicate-in-place.

### Polar array
Centre, count, sweep, and whether copies rotate.

**A full 360° steps by `total/count`; a partial sweep by `total/(count−1)`.**
Otherwise the last copy of a full circle lands exactly on the first. This is
what every CAD tool does, and the reason is that a circle is periodic while a
partial sweep has two distinct ends.

---

## Verification

The geometry lives in `apps/truss/truss_guides.py` with no Tkinter in it, and
is checked against **closed forms, not against its own output**:

| check | result |
|---|---|
| Line length = &#124;p1 − p0&#124; | exact to 1e-12 |
| Arc length = R·θ | 1e-6 |
| Parabola vs the analytic integral | 1.3e-8 relative — 0.07 µm on a 6 m curve |
| Chord summation converges from below, never overshoots | monotonic over 8 → 2048 samples |
| Path-array evenness, measured by an **independent Simpson integrator** | gaps equal to 1e-6 |
| Polar copies preserve their radius | 1e-9 |

The independent integrator matters: measuring the module's evenness with the
module's own arc-length table would only prove it agrees with itself.

**Two real defects found in my own geometry while testing**, both fixed:

1. `polar_array(rotate_items=False)` rotated the copies anyway. The offset was
   computed per point, which is arithmetically identical to rotating the item.
   It now uses one reference per item.
2. `closest_point` only tested sample points, capping the Curve snap's
   accuracy at half the sample spacing — 1.25 mm on a 5 m guide. It now
   projects onto each segment, which is exact for a line.

Two other test failures during the run turned out to be **my expectations,
not the code**: a tolerance one notch tighter than the sampler's measured
convergence, and an evenness check whose own nearest-sample lookup was doing
the quantising. Both were corrected in the test, with the measured numbers
written down so the next reader can tell a real regression from convergence.

The layout regression test also needed a precise change rather than a
loosened one: the guide panel shows only the fields the chosen kind uses, so
five entries are always unpacked and *cannot* all be visible at once. That is
different from a control the layout has lost, so the test subtracts exactly
those rather than being softened to a threshold.

---

## Worked example: the parabolic reticulated bridge

1. Add a guide: `y = 4*f*x*(L-x)/L^2`, `L=24, f=5`, x from 0 to 24.
2. Add a second guide: a line from (0,0) to (24,0) — the deck.
3. Path-array 9 nodes along the parabola, "connect with rods" on → top chord.
4. Path-array 9 nodes along the deck line → bottom chord.
5. Draw the verticals and diagonals; Curve snap keeps new nodes on the guides.
6. Supports, loads, Analyze.

Built end to end during verification: 18 nodes, 25 rods, apex exactly at the
guide, chords evenly spaced along their curves.

---

## Not done

* **Guides are not selectable on the canvas** — they are managed from the list
  in the panel. Clicking one to pick it up would be the natural next step.
* **Arrays are not associative.** Copies are independent geometry; changing
  the guide afterwards does not move nodes already placed along it.
* Path array places nodes on ONE guide at a time; there is no "between two
  guides" ruled-surface array.
