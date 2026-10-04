# Cable tab — recommendations, read as a teaching tool for architects

**Date:** 2026-10-04
**File reviewed:** `apps/cable/cable_app.py` (2 069 lines)
**Audience assumption (stated by the user):** this app is **not** a production
engineering tool. It exists so that **architects learn how engineering
works**. Every recommendation below is judged against that, not against
whether the answer is right.

**Starting position: the physics is in good shape and is not the problem.**
`DIAGNOSIS_CABLE_2026-09-05.md` finding **C-1** (max tension under-reported
0.5–1.7 % on the unsafe side) is **fixed** — `tension()` now takes the two
support nodes from `hypot(H, V_reaction)` instead of the end element's chord.
**C-3** (no physics tests) is **fixed** — `tests/test_cable_math.py` now
asserts the parabola, the catenary, the point-load closed form, and the
results-panel-equals-diagram check that would have caught C-1. **C-2** is
fixed. So this report is almost entirely about **pedagogy and interaction**,
which is where the remaining value is.

Measurements below were taken in this session against the real solver
(tkinter stubbed, numpy present).

---

## A · The inputs are engineer-shaped, not architect-shaped

### A-1 · HIGHEST VALUE · Let them type the **sag**, not the cable length

The tab's primary geometry input is `Cable length s`, and it refuses `s ≤ L`.
**No architect knows s.** They know "I want this cable to dip about 2 m", or
"I want a sag of about a tenth of the span".

Worse, `s` is a terrible dial to hold in your hand, because sag is enormously
sensitive to it. Measured on L = 20 m:

| sag you want | cable length you must type |
|---|---|
| 1.0 m (L/20) | s = 20.13 m |
| 2.0 m (L/10) | s = 20.52 m |
| 3.0 m (L/6.7) | s = 21.14 m |

A 3× change in the thing the architect cares about hides in the **third
significant figure** of the thing the app asks for. The tab's own
`Example: parabola` ships s = 22 m, which is a sag of 4.04 m = **L/5** — a
very deep cable — and nothing on screen says so.

**Do this:** make `Sag f` (or a `sag/span` dropdown: L/5, L/10, L/15, L/20)
the primary input and derive `s` from it, showing `s` as a read-only
consequence. The solver does not need to change: wrap the existing
`CableModel` in a one-dimensional root find on `s` against the target sag
(`max_sag()` already returns it), seeded by the parabolic series
`s ≈ L(1 + (8/3)(f/L)² − (32/5)(f/L)⁴)` which is accurate enough to converge
in two or three iterations. At 0.07 s per solve (A-4) that is imperceptible.

Keep `s` as an advanced input for the rare user who genuinely has a cable
length.

### A-2 · Replace "Area A (cm²) + allowable σ" with a cable you can picture

`SECTION (for tension/stress check)` asks for `A` in cm² and
`allow_tension` in kN/cm². An architect does not size cables in cm², and
"kN/cm²" is a unit almost nobody carries intuition for.

**Do this:** a short picker — *12 mm stainless rod, 20 mm spiral strand,
32 mm spiral strand, 50 mm locked coil* — that fills `A` and `σ_allow`
behind the scenes and displays the **diameter** next to the utilisation.
Keep the numeric fields as an override. The lesson an architect should take
away is "that roof needs a 32 mm cable, not a 12 mm one", which is a
sentence they can use in a design conversation; "σ = 2.548 kN/cm²" is not.

### A-3 · Self-weight should be a checkbox, not an expression you must know to write

The tab's single best physics lesson is the difference between a load per
metre of **span** (→ parabola) and a load per metre of **cable** (→
catenary). Self-weight is the natural example of the second. Today, to model
it, the user must: open the `Add distributed load` modal, know that
self-weight is the `arc` case, and type its intensity in kN/m as a formula.

**Do this:** `☑ Include cable self-weight`, computing `A × 78.5 kN/m³` from
the section chosen in A-2 and adding it as an `arc` load automatically. Then
the parabola/catenary distinction becomes something the user can *toggle and
watch*, instead of something they must already understand in order to type.

### A-4 · "Elements (n)" does not belong in an architect's panel

`Elements (n)` sits in the GEOMETRY block with the hint
*"(higher n = smoother, slower)"*. It changes no physics the user is here to
learn. Measured solve times (L = 20, s = 22, UDL):

| n | time | H |
|---|---|---|
| 30 | 0.15 s | 24 747 N |
| 60 (default) | **0.07 s** | 24 757 N |
| 120 | 0.23 s | 24 760 N |
| 200 | 0.95 s | 24 760 N |
| 400 | 4.96 s | 24 761 N |

H is converged to 0.05 % at the default. There is nothing for a learner to
gain here and a 5-second freeze to lose. Move it behind an "Advanced"
disclosure, or remove it.

---

## B · Make it live — the solver is already fast enough

### B-1 · HIGHEST VALUE · Drop the ▶ Analyze gate and recompute on change

Measured: **0.07 s** for a UDL at the default mesh, **0.11 s** with a point
load. That is comfortably inside interactive territory.

The entire reason a simulator teaches better than a textbook is the
cause-and-effect loop: *move this, watch that*. Right now the loop is
type a number → press ▶ Analyze → read a monospace table. That is the
rhythm of a calculation, not of an experiment.

**Do this:** sliders for sag, load magnitude and load position, recomputing
on drag (debounce ~80 ms, and skip the reference-catenary re-solve while
dragging). The thing you want an architect to *feel* is that **flattening a
cable makes the force explode** — and that is a sensation you can only get
from a slider, never from a table.

### B-2 · Put the live numbers next to the drawing, in big type

Three or four numbers that move as they drag: **sag ratio (L/n)**,
**H**, **T_max**, **utilisation**. The results `tk.Text` block is a good
reference readout and a poor instrument panel. Lead with the instrument
panel; keep the table underneath.

---

## C · The drawing is doing less teaching than it could

### C-1 · Distributed loads are **never drawn**

`_draw_schematic()` draws the cable, the supports, the ghost catenary, the
inverted arch, the probe, the force vectors, and nicely magnitude-scaled
arrows for point loads (`LoadScale`). It contains **no reference to
`self.distributed_loads` at all** — verified by scanning the whole function.

So a learner adds `q(x) = 2.0` over the full span, looks at the picture,
sees nothing change, and reasonably concludes the input did not take. This is
the most likely "the app is broken" report you will get from a non-engineer,
and it is the cheapest item on this list to fix.

**Do this:** draw q(x) as a row of short arrows (or a shaded band) above the
cable, height proportional to intensity, with the `arc` case visibly
following the cable and the `horizontal` case visibly level — which *shows*
the distinction A-3 asks you to teach.

### C-2 · Draw the sag, and label it as a ratio

`Max sag = 4.037 m at x = 10.00` is printed in the results text. It should
be a **dimension line on the schematic**: the chord, a vertical tick down to
the lowest point, labelled `f = 4.04 m = L/5`. Architects read drawings.
A dimension on the drawing is worth a paragraph of table.

### C-3 · Draw the reactions at the supports as arrows

Reactions currently appear only as red text under the *diagram* pane
(`R_left: H=…, V=… ▲`). The single most important thing about a cable, and
the thing that surprises architects most, is that **it pulls its supports
inward and down** — that is why cable roofs need those enormous anchorages.
A pair of arrows at each anchor, labelled H and V, teaches that in one
glance. Consider sketching the implied anchor block too.

### C-4 · Use `ZoomCanvas`

Every other tab (`truss`, `stereo`, `perforated_beam`, `cable_web`) uses
`common.ZoomCanvas`. The Cable schematic is a plain `tk.Canvas`, capped at a
third of the window by `_on_root_configure`. A learner should be able to zoom
into the kink under a point load — that kink is the lesson.

### C-5 · Add a q(x) band to the diagram pane

The diagram shows `T(x)` and `Fx / Fy`. The load those came from is not
plotted. Three stacked bands — **q(x)**, **Fy(x)**, **T(x)** — read top to
bottom as a derivation, and `diagram_series()` already reconstructs the
continuous `dFy/dx = q(x)` relation, so the data is in hand.

---

## D · Teach the ideas, not only the numbers

### D-1 · HIGHEST VALUE · Make the beam↔cable comparison explicit

This is the one idea that changes how an architect thinks, and the tab does
not state it:

> **H = M_beam / f**

A cable carries exactly the load a beam would, and converts the bending
moment into a pure tension by **dividing by the sag**. Halve the sag, double
the force. That is the whole discipline of cable structures in one line.

**Do this:** in the results, next to H, print
*"a simply supported beam of this span under this load would need
M = wL²/8 = 100 kN·m. This cable needs no bending at all — because
H × f = 100 kN·m. Halve the sag and H doubles."* The Beam tab's solver is
next door if you want the comparison computed rather than quoted.

### D-2 · Show the working

`common.render_math` (matplotlib LaTeX images) exists and is used by **only
one tab**, Truss, which pops a calculation window with the equations
substituted. The Cable tab is the tab with the cleanest closed forms of any
in the app:

- `H = wL² / (8f)`
- `T(x) = √(H² + Fy(x)²)`, maximum at the support
- `T_max = hypot(H, V)` — exactly what `tension()` now does
- `s ≈ L(1 + (8/3)(f/L)²)`

**Do this:** a "Show the working" pane with those formulas, this cable's
numbers substituted, **and the comparison against the solved value** —
"hand formula 24 750 N, solver 24 757 N, 0.03 %". Telling a learner *when
the simple formula is good enough* is a genuine engineering lesson, and it
is one this app is uniquely placed to give because it has both numbers.

### D-3 · Promote the inverted-arch toggle — it is the best thing in the tab

`☐ Show inverted (compression arch)` is a 9-point checkbox in a column of
checkboxes. It is the Gaudí / Isler / Otto lesson: **hang a chain, invert
it, and you have an arch that carries that load in pure compression with
zero bending moment.** For an architecture audience this is the headline,
not a display option.

**Do this:** a named button with a caption ("this is why Gaudí hung chains
in his workshop"), and ideally **"send this shape to the Arch tab"** so the
learner can watch the same curve carry the same load in compression and see
the moment diagram come out flat. You already have both tabs and the Arch
tab already accepts a `y = f(x)` shape.

### D-4 · The three Example buttons load geometry but teach nothing

`Example: parabola`, `Example: catenary`, `Example: point load` set inputs
and say nothing. Each should also post a short paragraph:

> *"This load is per metre of **span** — like a deck hanging from the cable
> — so the shape is a **parabola**. Now switch 'per' from horizontal to arc
> and press Analyze again: the same numbers give a **catenary**, because the
> load now follows the cable. Watch how little the shape changes and how much
> the name matters."*

That turns three buttons into three lessons at essentially no cost.

---

## E · Honest feedback instead of silent nonsense

### E-1 · MEDIUM · A slack cable reports "converged" and the stress check says OK

Still open from `REMAINING_BUGS_CABLE_2026-09-10.md` (**C-5**), re-measured
today:

| case (span 20 m) | result |
|---|---|
| distributed load over [0, 20] | H = 24 757 N, reactions (±), `converged=True` |
| distributed load over **[30, 50]** | **H = 2e-17**, reactions (0, 0), `converged=True` |
| no load at all | **H = 2e-17**, `converged=True` |

H ≈ 0 is not a cable in equilibrium, it is a slack string. The tab presents
it as a converged solution, `_show_results` then computes `sigma = 0` and
prints **OK, ratio 0.00**. For a learner being taught to trust the tool's
verdict, "OK" on a structure that is carrying nothing is the worst possible
output.

**Do this:** after solving, if the total applied load is ~0 or H is a tiny
fraction of it, replace the results with *"no effective load on this cable —
nothing to solve"*. Separately warn when a load's `[x₁, x₂]` does not
overlap `[0, L]`, which is the actual user error behind the second row.

### E-2 · Rewrite the error dialogs as teaching messages

> *"Cable length s must exceed the span L (s > L)."*

Correct, and nearly meaningless to an architect. Compare:

> *"A cable can't be shorter than the gap it spans — it would have to be a
> straight strut, and a cable can't push. Give it some slack: increase s
> above 20 m, or type the sag you want instead."*

Same for the point-load-outside-the-span rejection. Every error dialog in a
teaching app is a free teaching moment, and there are five of them here
(`_set_geometry`, `_add_pointload`, `_add_distributed_load`, `_analyze`, and
the convergence warning).

### E-3 · The q(x) unit convention is a trap for learners

By deliberate design (and the label says so outright), when the user selects
an imperial convention the bounds `x₁, x₂` convert but the **q(x)
expression stays in kN/m with x in metres** — because re-reading `2*x^2` in
another convention would change what the formula means.

The reasoning is sound for an expression field. For this audience the
conclusion should be different: **hide the expression field** behind the
advanced panel and give architects simple, fully-unit-aware inputs —
*uniform*, *triangular*, *point* — in the units they selected. Keep `q(x)`
for the power user who wants `2*x^2`.

---

## F · Housekeeping (small, real)

### F-1 · Dead imports — finding C-4, still open

`os`, `sys`, `subprocess`, `INIT_CW`, `INIT_CH`, `INIT_DH` are each imported
and referenced exactly once in the file: on the import line. Six dead names.

### F-2 · Stale comment advertising a design that was removed

```python
self.point_loads = []        # [{'x','P','eps'}]  kN, m
```

There is no `eps` any more, and its absence is a selling point of this
solver — the point load is an exact Dirac force at a solved material
coordinate, with no pulse or epsilon regularisation. The comment says the
opposite of the docstring eight lines above it.

### F-3 · The two tab names invite confusion

`Cable` and `Cable Web` are different solvers with four separate test files
for one of them (a confusion the C-3 note already flagged). For a learner
browsing tabs, **`Single Cable`** and **`Cable Net`** would say what they
are.

---

## Suggested order of work

| # | item | why first | effort |
|---|---|---|---|
| 1 | **C-1** draw distributed loads | it currently looks broken | ~1 h |
| 2 | **A-1** sag as the input | unblocks every other interaction | ~3 h |
| 3 | **B-1** live recompute on slider drag | turns a calculator into a simulator | ~3 h |
| 4 | **D-1** the `H = M_beam/f` sentence | highest lesson-per-line in the list | ~30 min |
| 5 | **E-1** slack cable not reported OK | it is the one wrong *verdict* left | ~30 min |
| 6 | **C-2 / C-3** draw sag and reactions | architects read drawings | ~2 h |
| 7 | **D-3** promote the inverted arch | the headline idea for this audience | ~1 h |
| 8 | **A-2 / A-3** cable picker + self-weight checkbox | removes the last cm²/formula barriers | ~3 h |
| 9 | **D-2** show the working | best use of existing `render_math` | ~2 h |
| 10 | **D-4, E-2, A-4, F-1…F-3** | polish, all cheap | ~3 h |

Items 1, 4 and 5 together are under two hours and already change the
character of the tab.
