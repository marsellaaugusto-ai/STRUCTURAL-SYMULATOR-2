# Truss guides — fitted curves, the five-point conic, and moving them

**Date:** 2026-09-08

Answers two questions: *"I want to move the functions around — do I choose a
point?"* and *"what if I want a curve through two points with a set
property?"*

---

## Moving a guide: you grab the points that mean something

The reason "where do I grab it?" is hard to answer for a curve is that a
bounding box has no meaning. So a guide's handles are its **defining
points**, and dragging one changes exactly what that point defines:

| guide | handles |
|---|---|
| fitted curve | the two points it passes through (blue), plus a **crown handle** (orange) when the fit is by rise or sag |
| line | its two endpoints |
| 5-point conic | all five points |
| circle / ellipse | its centre |
| `y = f(x)` | one anchor |

Click the curve away from any handle and you drag the **whole guide**. Handles
win over the body, so a click near an end grabs that end rather than
translating.

Handles are drawn **on top of the structure**. Underneath, the nodes bury
them — and a handle you cannot see is a handle you will not reach for.

**A typed `y = f(x)` needed an origin to be movable at all.** The expression is
tied to the axes, so "shift this parabola 3 m right" would otherwise mean
rewriting its algebra. Every func guide now carries `ox, oy` and is evaluated
in its own frame.

### Guides never drag structure

Nodes already arrayed onto a guide **stay exactly where they are** when the
guide moves. The status bar says so, and **Re-array** re-runs that array on
the moved guide deliberately.

Re-array refuses if the node count would change — a longer guide at the same
spacing wants more nodes, and silently adding or dropping them would re-wire
which rods attach to what. It says so and stops.

Deleting a guide remaps the array history, because guide indices shift down
past the deleted one exactly as node indices do on delete. Without that, a
later Re-array would rewrite nodes from the wrong curve.

---

## Curves defined by what they must satisfy

Store the **constraints**, not the fitted coefficients. Then dragging an end
point re-solves the curve and keeps the property you asked for. Store the
coefficients and the first drag breaks the relationship the curve was built
on — which is what makes handles feel fake in weaker tools.

| family | two points, plus | solved by |
|---|---|---|
| **parabola** | rise | exact linear solve |
| **circular arc** | rise · radius · arc length | closed form / bisection |
| **semi-ellipse** | rise · arc length | bisection on `b` |
| **catenary** | sag · length | bisection on `a` |

The "set by" list changes with the family, because a parabola through two
points is fixed by its rise and asking for its *radius* is not a harder
question — it is a meaningless one.

### What was not well posed, and what I did about it

**An ellipse has five degrees of freedom.** Two points plus a perimeter leaves
a two-parameter family, not a curve. `semiellipse` is therefore the
semi-elliptical **arch**: centre on the chord midpoint, major axis along the
chord. That fixes `a` from the points and leaves `b` as the one unknown.

Its length input is the **arch itself** — the half-ellipse that is drawn — not
the full circumference. That is what someone setting the curve out measures.

**"Hyperbola" through two points** is under-determined the same way. The
structurally meaningful curve is the **catenary**, which a cable takes under
self-weight and an arch follows in pure compression, and it is well posed.
The general conic is the five-point tool below.

### One convention across families

`rise` is **up** for the parabola, the arc and the semi-ellipse. `sag` is
**down** for the catenary — the word carries the sign, and a hanging cable
goes down.

The semi-ellipse got this wrong at first: sweeping 180° → 360° also runs p0 to
p1 but bulges the *other way*, so "rise 5" raised a parabola and lowered an
ellipse. Corrected to 180° → 0°, and pinned by a test across every family,
because that is exactly the kind of inconsistency that creeps back.

---

## Conic through five points

Five points determine a unique conic — ellipse, parabola, hyperbola, circle —
as the null space of a 5×6 matrix, classified by `B² − 4AC`. Pick the tool,
click five times with the usual snaps.

Columns are normalised before the SVD: raw `x²` terms dwarf the constant
column on a 20 m span, and that conditioning alone loses several digits.

**Sampling is the hard part.** A general conic is *implicit*: it can be
vertical, it can close, and a hyperbola has two disconnected branches. Nothing
here can be plotted by stepping x, and a sampler that did would join a
hyperbola's branches with a phantom segment across the gap — which the
arc-length table would then measure as real curve and array nodes along. So
the conic is reduced to canonical form, each branch parametrised separately,
and a guide names the one branch it means.

**Five collinear points are refused. Three collinear are not, and should not
be** — they still determine a unique conic, it is just a degenerate line pair,
which has no branch to draw and is reported as such.

---

## Verification

Every curve is checked by **rebuilding one whose equation is already known**,
and every fit by **what was asked for** rather than a stored answer — so a
rewrite of the solver is held to the same standard.

| check | result |
|---|---|
| Circle through 5 points | radius exact to 1e-9 |
| Rotated ellipse (8 × 3, 30°) | residual 1e-12; semi-axes recovered to 1e-6 |
| Parabola | deviation 1e-9, classified correctly |
| Hyperbola | two branches, provably never crossing the gap |
| Every fit passes through both its points | ≤ 1e-7 |
| Parabola rise, arc radius, arc length (as R·θ) | exact |
| Semi-ellipse and catenary lengths | ≤ 1e-4 relative |
| Catenary with unequal end heights | ends and length exact |
| Dragging an end re-solves and keeps the rise | 1e-9 |

**A real accuracy bug was fixed on the way.** `point_at_arclength`
interpolated between two sampled *positions*, which puts the result on the
chord between them — 7.4 µm inside a 6 m circle. It now interpolates the
*parameter* and re-evaluates the curve, so a node arrayed along a curve is
**on** it: max error 8.9e-16, down from 7.3e-6.

Guides persist through Excel, including a fit's constraints (saving the solved
coefficients would reopen as a curve that no longer re-fits) and a conic's five
points.

---

## Not done

* **Arrays other than path are not re-runnable.** Only path arrays record
  enough to be repeated; grid and polar copies are independent geometry.
* **Only the last path array per guide is remembered**, so Re-array repeats
  that one.
* **The five-point conic cannot be edited numerically** — the points are
  placed by clicking and then dragged. There are no coordinate boxes for them.
* **A conic's branch cannot yet be switched from the UI**; the record supports
  it (`branch`) but nothing sets it after creation.
