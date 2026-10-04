# Arch tab — recommendations, read as a teaching tool for architects

**File reviewed:** `apps/arch/arch_app.py` (1 990 lines) plus `common.py`,
`units.py`, `tests/test_arch_math.py`, `tests/test_arch_asymmetric_supports.py`.
**Date:** 2026-10-04.
**Frame of reference for this review:** the audience is an architecture
student learning how structures behave — not an engineer sizing a member.
Everything below is judged against *"does this build an intuition about
arches?"*, not against *"is this a competent analysis package?"*

That distinction matters, because the answer to the second question is
already **yes**. The solver is the most accurate in the project — the
2026-09-10 re-validation holds (`H = wL²/8f` to 2.5e-14, funicular
`max|M| ≈ 0`, `M = 0` at the crown hinge), and nothing below asks you to
change a line of the math. Every recommendation is about what the tab
*shows* and *asks for*, not what it computes.

The one-sentence summary: **the Arch tab solves an arch correctly and then
presents the answer as an engineer's output sheet.** An architect reads
shape, not sign conventions. The whole list follows from that.

---

## Tier 1 — the things that would actually teach

### 1. Draw the line of thrust. This is the headline item.

The thrust line is *the* way arches are taught to architects — Hooke's
hanging chain, Gaudí's string models, Heyman's masonry arch. It is the
single picture that makes an arch make sense: where the resultant actually
passes through the section, and whether it stays inside the stone.

The tab does not have it. Grep `apps/arch/` for `thrust line`, `funicular`,
`eccentric`, `middle third` or `kern`: zero hits. What exists instead is
`_draw_thrust_vectors` (`arch_app.py:1584`), an opt-in overlay of arrows at
discrete stations — useful, but it shows *force at points*, not *the path
the force takes*.

Everything needed is already computed. At every sampled station
`ArchResult.sample()` returns `N` and `M`, so the eccentricity is one line:

```
e = M / N          # metres off the centreline
```

Plot `y_centreline + e` as a second curve on the schematic and you have the
thrust line. Shade the band `±h/6` around the centreline (the middle third,
derivable from the `c_top`/`c_bot` already in the section inputs) and the
student can see, directly, the rule that governs every masonry arch ever
built: *inside the band, the whole section is in compression; outside it,
the arch wants to crack.*

This single addition changes the tab from a calculator into the thing the
course is about. **Highest value-per-line-of-code item in the file.**

### 2. The schematic never draws the loads. Fix this first — it is 90 minutes.

`_draw_schematic` (`arch_app.py:1507-1583`) draws: the arch curve, two
support symbols, the hinge dot, and the labels `0` and the span. That is
all. It never references `self.point_loads`, `self.distributed_loads`,
`w_weight` or `w_wind` — confirmed by grep over the function body.

So a student types a 50 kN point load at x = 4 m, looks at the picture,
and nothing has changed. The only arrows anywhere in this tab
(`arch_app.py:1624, 1629, 1633`) belong to the thrust overlay, which is
**off by default** and only appears *after* analysis.

Every other tab draws its loads — Beam at `beam_app.py:1458, 1479`, Cable at
`cable_app.py:1838, 1898-1905`, Truss in seven places. Arch is the only one
that doesn't, and it is the tab where seeing the load against the curve
matters most, because the entire lesson is *this shape against that load*.

`common.LoadScale` already exists for exactly this (square-root-compressed
arrow lengths so a 500 kN load doesn't draw off-canvas next to a 5 kN one);
Beam, Truss and Cable all import it, Arch does not.

### 3. Show the deflected shape.

There is no deflected-shape plot anywhere in the tab. The displacement
vector is sitting right there — `ArchResult.d` (`arch_app.py:312`) — and is
used only to recover internal forces.

For an architect, "the arch squashes and spreads" is a more useful mental
model than any stress number. Draw the original centreline in grey and the
displaced one (amplified ×50, ×100, with the existing scale-slider idiom) in
colour, and the difference between a two-hinged, three-hinged and fixed arch
becomes visible instead of tabular.

### 4. Name the quantities an architect actually reasons with.

`_show_results` (`arch_app.py:1445`) prints: reactions as `Rx`/`Ry`, max
axial tension, max axial compression, max `|M|`, and a stress check. It is
correct and it is unreadable to the target user.

What is missing is not more numbers — it is the *three* numbers that carry
the architectural argument:

- **Horizontal thrust H.** It is already printed, as `Rx` at `x=0`. Call it
  what it is: *"Horizontal thrust H = 100.0 kN — this is the force your
  foundation, buttress or tie has to resist."* An architect needs to know
  the arch pushes outward. `Rx` does not say that.
- **Rise-to-span ratio f/L.** Never shown, never computed. It is the
  parameter architects design with, and it is `rise/span`.
- **The comparison that makes the arch worth building:** for the same span
  and load, a simply-supported beam carries `M = wL²/8`. The arch carries
  `M ≈ 0` and `H = wL²/8f` instead. Printing both side by side —
  *"a beam here would need M = 500 kN·m; this arch needs 0, and pushes out
  with 100 kN"* — is the entire justification for arches, in one line, from
  numbers the tab already has.

Add a derived line: *halve the rise and the thrust doubles.* The solver
already proves it; nothing in the interface says it.

### 5. Make the three Examples teach instead of just loading numbers.

`_load_example_two_hinged` / `_three_hinged` / `_fixed`
(`arch_app.py:1347-1379`) set a span, a rise, a shape and two load values,
then stop. They do not run the analysis, and they say nothing about why
those three cases are the three cases.

Each should (a) run `_analyze` itself, and (b) drop a short
*"what to notice"* note into the RESULTS pane — e.g. for the three-hinged
parabola under UDL: *"The bending moment is zero everywhere. The parabola is
the funicular shape for this load: the arch is in pure compression. Now
change the load to a point load at the quarter point and watch the moment
appear."*

That last clause is the important half. An example that ends with an
instruction to go break it is a lesson; one that just loads numbers is a
preset.

Worth adding a fourth: **the same arch as a beam** (set rise ≈ 0) so the
student can see the thrust vanish and the moment explode. The solver already
handles it — `_analyze`'s context guards a zero rise at `arch_app.py:1388`.

### 6. The funicular relationship is the lesson, and the shape presets hide it.

Three presets exist (`_apply_shape_preset`, `arch_app.py:1057`): Parabolic,
Circular, Catenary-like. They are offered as a styling choice, with no
indication that **the choice of shape is a structural decision coupled to
the load.**

The parabola is funicular for a uniform load *on the horizontal projection*
(which is what `w_weight` is — `ArchModel.w_weight`, `arch_app.py:125`, is
documented "horizontal-projected"). The catenary is funicular for weight
*along the arc*. That second load case does not exist in the model at all,
which means the "Catenary-like" preset is never funicular for anything the
tab can apply. Its `k` is hard-wired to `3.0/span` (`arch_app.py:1389`) — an
arbitrary shape parameter, not a derived one.

Two recommendations, in order of value:

- **A "Find the funicular" button.** For the loads currently entered, solve
  the funicular shape and offer to adopt it as the centreline. Then the
  student sees *"for THIS load, THIS is the shape with no bending"* — which
  is Hooke, Gaudí and Gothic vaulting in a single click.
- **Add self-weight-along-the-arc** as a load type alongside the
  horizontal-projected one, so the true catenary becomes demonstrable. Right
  now the one shape every architect has heard of cannot be shown doing the
  one thing it is famous for.

### 7. Add a comparison mode.

Architects learn by contrast. The three support conditions are currently
three separate runs with three separate screens, and nothing retains the
previous answer — `_analyze` overwrites `self.result` (`arch_app.py:1437`).

*Same arch, same load, three support conditions, three columns* — with
H, max M and max σ in a small table — teaches more in one screen than
three sequential runs do in ten minutes. Same for *same support, three
shapes* and *same everything, three rise values.*

---

## Tier 2 — barriers that have nothing to do with structures

These are the places where the tab asks an architect for something only an
engineer can supply. Every one of them is a point where a student stops
learning about arches and starts fighting the form.

### 8. Nobody knows what `I = 20000 cm⁴` means.

The CROSS-SECTION / MATERIAL block (`arch_app.py:1039-1050`) asks for seven
raw numbers: `E`, `A`, `I`, `c_top`, `c_bot`, and two allowable stresses.
An architect can supply none of them from first principles, and the defaults
(`arch_app.py:694`) silently make every arch a steel one — `E = 200 GPa`.

The project already solved this elsewhere. `apps/perforated_beam/` carries a
section catalog (IPE, HEB, UPN — see `perforated_beam_excel.py:73-99`), a
section-properties module, a profile sketcher, and `section_shapes.py`,
which turns any section into drawable polygons. The Arch tab uses none of it.

Two changes, both reuse rather than new code:

- **A section picker** that fills `A`, `I`, `c_top`, `c_bot` from the
  catalog, with the chosen section *drawn* next to the fields. Keep the
  manual entries for anyone who wants them.
- **Material presets** — stone, brick, concrete, timber, steel — setting `E`
  and the allowable stresses together. Arches in architectural history are
  overwhelmingly masonry; the tab currently cannot be a masonry arch without
  the student knowing masonry's modulus.

### 9. Nothing updates until you press a button.

Only one variable in the whole tab has a trace: the custom-support
comboboxes (`arch_app.py:987`). Span, rise, shape expression, element count
and **hinge position** do not redraw the schematic when typed — `rise` needs
the `Set geometry` button (`arch_app.py:1241`), and the hinge dot does not
move at all until something else forces a repaint.

For a learning tool this is the wrong default. The insight *"as I drag the
rise down, the thrust climbs"* only lands if it happens continuously. Two
steps:

- Trace `span_var`, `rise_var`, `hinge_var` and `expr_var` to
  `_draw_schematic` (debounced). Cheap, immediate improvement.
- Then: make the rise and the load positions **draggable on the schematic.**
  `common.ZoomCanvas` already provides the canvas interaction layer and is
  used by Cable Web, Stereo, Truss and three Perforated Beam views — Arch is
  the only drawing tab still on a bare `tk.Canvas` (`arch_app.py:768`),
  with no zoom, no pan and no picking.

### 10. Errors speak Python, not architecture.

`_analyze` wraps everything in one handler (`arch_app.py:1442-1443`):

```python
except Exception as e:
    messagebox.showerror('Analysis failed', str(e))
```

So a typo in the shape expression surfaces as `Unknown name in shape
expression: 'sinn'`, and a singular stiffness matrix surfaces as whatever
`_beam_gauss_solve` happens to raise. The load validators added for A-6/A-7
(`ArchModel._validate_loads`, `arch_app.py:135`) are a good model of the
right tone — *"A point load at x = 25 m is not on the arch, which spans 0 to
20 m"* — and that tone should reach the rest of the failure paths.

A mechanism failure in particular deserves a real explanation: *"This arch
is a mechanism — with hinges at both springings and the crown it can still
move. Add a support or remove a hinge."* That is a teachable moment the tab
currently spends a traceback on.

### 11. There is no glossary, and the infrastructure for one already exists.

`InfoTooltip` is defined and used **14 times** in `cable_web_app.py` and
nowhere else in the project. Arch has zero.

Every bolded panel header in `_build_panel` — `SHAPE y = f(x)`,
`SUPPORTS / HINGE`, `LOADS (horizontal-projected)`, `CROSS-SECTION` — and
every diagram caption is a place where a one-sentence tooltip would carry a
definition. "Horizontal-projected" in particular is a genuinely subtle idea
(load per metre of *plan*, not per metre of *arch*) that the tab states as a
parenthetical and never explains.

### 12. There is no theory panel, and that infrastructure exists too.

`common.render_math` (`common.py:132`) renders LaTeX to an image, and
`requirements.txt` explicitly describes it as serving "the LaTeX-style
equation images in the Truss/Beam/**Arch** guides". The Truss tab uses it
(`truss_app.py:4541, 4698`). **The Arch guide it names does not exist.**

Finish the thing the requirements file already promises: a short guide
window with `H = wL²/(8f)`, the funicular idea, what each support condition
does to the degree of indeterminacy, and why a three-hinged arch is the one
that doesn't care about settlement. Cable Web's guide button
(`cable_web_app.py:1181`) is the pattern to copy.

---

## Tier 3 — defects and gaps found while reading

These are ordinary bugs and omissions, listed separately because they are
not about the audience.

### 13. Three readouts ignore the unit selector. **Real bug.**

`units.py` offers five conventions and AISC is genuinely US-customary
(kip, ft, ksi — see `units.py:25-27`). Three readouts bypass it and
hard-code kN:

| line | text |
|---|---|
| `arch_app.py:1695` | `f"R  = {R/1e3:8.2f} kN"` |
| `arch_app.py:1869` | `f"◄ R_left: Rx={Rx0/1e3:+.2f} kN, ..."` |
| `arch_app.py:1870` | `f"► R_right: Rx={Rxn/1e3:+.2f} kN, ..."` |

In AISC mode each of these sits directly beside a correctly converted value:
the force probe prints `Fx` and `Fy` in kip (via `sh_f`) and then `R` in kN
on the next line; the thrust panel's caption says `({F_})` — "kip" — over
reaction numbers in kN. Both are silently wrong by a factor of 4.45, and
both are in the panel an architect is most likely to read.

Fix: route all three through `self.show('force', …)` and `self.u('force')`,
exactly as the neighbouring lines already do. **~15 minutes.**

### 14. There is no buckling or second-order check, and nothing says so.

Grep `apps/arch/` for `buckl`: nothing. The solver is first-order linear
elastic, which is correct for what it claims to be — but a shallow arch is
governed by *snap-through*, not by fibre stress, and a student can currently
model a very shallow, very slender arch, get a clean "OK" on both stress
rows, and take away precisely the wrong lesson.

At minimum, state the limit in the RESULTS pane. Better: flag shallow
arches (say `f/L < 0.15`) with a note that buckling, not stress, is likely
to govern.

### 15. No masonry (tension-less) mode.

`fiber_stresses` (`arch_app.py:400`) computes elastic `σ = N/A ± Mc/I` with
tension positive, and `_show_results` checks it against an allowable tension.
For a masonry arch that is the wrong model — masonry has effectively no
tension capacity, and the real question is whether the thrust line stays
within the section, which is recommendation 1.

A "masonry / no-tension" toggle that swaps the stress check for a thrust-line
containment check would make the tab usable for the arches architects
actually study.

### 16. Still-open items from `REMAINING_BUGS_ARCH_2026-09-10.md`.

- **A-3, dead code.** Unchanged and confirmed today: `os`, `sys`,
  `subprocess` (`arch_app.py:16`) and `INIT_CW`, `INIT_CH`, `INIT_DH`
  (`arch_app.py:21`) are imported unused; `L` and `rise` are assigned and unused in
  `_apply_shape_preset` (`arch_app.py:1059-1060`).
- **A-2 and A-4 are now closed** — `ArchModel.__init__` validates `n_elem`
  (`arch_app.py:109-113`), and `tests/test_arch_math.py` plus
  `tests/test_arch_asymmetric_supports.py` now exist. The remaining-bugs
  table should be updated to say so.

### 17. Schematic is missing its own dimensions.

`_draw_schematic` labels `0` and the span (`arch_app.py:1571-1573`) and
nothing else. No rise dimension, no vertical axis, no crown height — the
three numbers the student just typed are nowhere on the drawing. Add
dimension lines for span and rise, and label the `f/L` ratio on the
schematic itself.

---

## Suggested order of work

| # | item | why first | rough effort |
|---|---|---|---|
| 1 | Draw the loads on the schematic (**2**) | the tab currently lies by omission; smallest change with the largest credibility gain | ~1.5 h |
| 2 | Fix the hard-coded kN (**13**) | a real bug, and trivially fixed | ~15 min |
| 3 | Live redraw on span/rise/hinge (**9a**) | unlocks the "watch it change" mode everything else depends on | ~1 h |
| 4 | Rename and add the architect's numbers (**4**) | pure text in `_show_results`; no new math | ~2 h |
| 5 | Thrust line + middle third (**1**) | the headline teaching feature | ~1 day |
| 6 | Deflected shape (**3**) | data already present | ~3 h |
| 7 | Examples that run and explain (**5**) | makes 1–6 discoverable | ~3 h |
| 8 | Section picker + materials (**8**) | reuse of existing `perforated_beam` modules | ~1 day |
| 9 | Guide window + tooltips (**11**, **12**) | reuse of `render_math` and `InfoTooltip` | ~1 day |
| 10 | Funicular finder, comparison mode, masonry mode (**6**, **7**, **15**) | the ambitious tier | ~1 week |

Items 1–4 together are under a day and would change the tab's character
noticeably. Item 5 is the one worth the real investment.

---

## One closing note on what not to change

The solver. It is the most accurate module in the project, it is now covered
by tests, and every recommendation above is additive — a new curve on an
existing canvas, a new label on an existing number, a new input that fills
existing fields. Nothing here requires touching `ArchModel.solve`,
`internal_forces`, `sample` or `fiber_stresses`, and nothing should.
