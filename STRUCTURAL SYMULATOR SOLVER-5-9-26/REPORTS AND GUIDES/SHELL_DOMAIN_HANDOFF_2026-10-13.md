# Shell (RC) — handoff for the next session

Written for whoever picks this up next, human or model, assuming no memory of
the sessions that produced it. Everything here is checkable against the code or
against a number the tab prints; where something is a judgement call it says so,
and where an earlier judgement turned out to be wrong it says that too.

- **Branch:** `claude/shell-rc-rebuild`, cut from `claude/stereo-ui-rebuild` so
  the Shell and Stereo tabs can be worked on in parallel.
- **Head at the time of writing:** `21c8ca8`.
- **Tests:** `2880 passed`, 0 failed, 0 skipped, about 8 minutes.
- **App folder:** `STRUCTURAL SYMULATOR SOLVER-5-9-26/`.
- **Owner's code:** CIRSOC 201 (2024 draft, which follows ACI 318-19).

Companion documents, both in this folder and both written during these
sessions:

| File | What it is |
|---|---|
| `SHELL_OVERHAUL_PLAN_2026-09-20.html` | The plan the owner approved, rev. 5, with 8 inline figures and 3 screenshots |
| `SHELL_DOMAIN_NOTE_2026-09-21.html` | The understanding note written before the domain work, with the measurements that justified it |
| `shell_plan_figures/`, `shell_domain_figures/` | Those figures and the Python that generates them (`src/`) |

Both HTML files were also published as private Artifacts on the owner's
account. Those links do **not** open from a different account unless the owner
shares them, which is why this handoff is a file in the repository rather than
a link.

---

## 0. How to run anything at all

There is exactly one usable interpreter in the dev container:

```bash
/usr/bin/python3.12          # the only one with tkinter
```

The default `python3` is 3.11 and has **no Tk at all** — `apt install python3-tk`
installed `_tkinter` only for 3.12. numpy and scipy are installed for 3.12.

```bash
cd "STRUCTURAL SYMULATOR SOLVER-5-9-26"
/usr/bin/python3.12 -m pytest -q                 # 2880 passed, ~8 min
```

**Tk tests skip silently without a display.** A run that reports `1809 passed,
966 skipped` is not a passing run, it is a run with no X server. Start one
first:

```bash
Xvfb :95 -screen 0 1400x900x24 &
DISPLAY=:95 /usr/bin/python3.12 -m pytest -q
```

…and kill it afterwards. An Xvfb started with `&` never exits on its own and
will sit there for the rest of the session looking like a hung job; the owner
noticed one at 45 minutes and asked about it. Start it as a tracked background
task so it can be stopped cleanly, or kill the PID when the tests are done.

To photograph the real app headlessly:

```bash
DISPLAY=:95 /usr/bin/python3.12 tests/tools/shoot.py --tab Shell --analyze --out /tmp/shots
```

`shoot.py` takes `--tab`, `--generate`, `--analyze`, `--modes`, `--out`,
`--prefix`. Tk draws when it is pumped, not when it is told to, so it pumps,
sleeps and pumps again before every shot — without the sleep the canvas is
photographed half-drawn, which looks exactly like a rendering bug and is not
one.

### The trap that killed two test runs

Do **not** put a `pgrep`/`pkill` for pytest in the same command line that runs
pytest:

```bash
# WRONG: pgrep matches this shell's OWN command line, kills it, exit 144
for p in $(pgrep -f "[p]ytest"); do kill "$p"; done; ... python3.12 -m pytest -q
```

The bracket trick stops `pgrep` matching its own pattern, but the word `pytest`
still appears later in the same command string, so the wrapper shell matches and
kills itself. It happened twice. Kill by explicit PID, or in a separate call.

---

## 1. What the owner asked for, in order

This is the whole arc, because the later work only makes sense against the
earlier.

1. **Overhaul the Shell simulator.** Specifically: an interface like the Stereo
   tab's; pick supports on the corners of elements; show the thickness in the
   3-D model and in the sections (the old version drew a sheet with no
   thickness); port the surface wizard; a guide for the colour maps and move
   the map list out of the toolbar where it was hidden; a better section-cut
   list. **And: write a plan with pictures first, and ask every question
   needed.** That instruction set the working pattern for everything since.
2. Use what earlier conversations had established.
3. CIRSOC 201 as the code, route A, a new branch off the Stereo one, and
   re-check the plan against two supplied papers on concrete shells.
4. Run the app from here so the owner can assess it before sending a zip.
5. Publish the plan, then work the stages.
6. **A question and five more requests** (the domain session): is there a domain
   function for an elliptical sector of a hypar; how does the "sliced element"
   work; a card showing the most tensioned, most compressed and governing
   element; stop the jagged edges on elliptical domains; can the owner build the
   structures in their own TP 2 drawing; and improve the domain feature — "given
   a surface `f(x,y)` we establish the domain, then the contour with an
   expression `g`". Again: **explain what you understood, with pictures, before
   building.**
7. "I like all the default options" — every default in the understanding note
   was accepted, so all six were built.
8. Make sure Stage 6 actually closed, and check a long-running task.
9. Produce a zip.

---

## 2. What is in the tab now

### 2a. From the staged overhaul (commits `305e2a5` … `1688134`)

- **Stage 0** — the Shell (RC) tab brought into the repository from the owner's
  zip, merged without clobbering newer Stereo work. The zip had forked *before*
  the Stereo UI rebuild: every `apps/stereo` file in it was older and smaller,
  so none was restored, and `stereo_voronoi_surface.py` was deliberately left
  deleted.
- **Stage 1** — `apps/shell/shell_solid.py`: the shell drawn as the slab it is,
  with a top, a soffit and a band round every free edge. Geometry only, no Tk,
  so it is testable against numbers (a flat plate's solid has exactly `area × t`).
  It never moves the model — a drawing that moved the model would be worse than
  one that omits the thickness.
- **Stages 2 and 3** — section cuts you can keep, each with its own colour on
  the model, in the list and in the drawing; and the six-mode left rail
  (Surface, Supports, Loads, Design, Sections, Analyse) replacing one 360 px
  column of everything. `pack_forget`, not `lower()`: a hidden-but-packed panel
  still claims its width.
- **Stage 4** — pick supports by clicking the model, and the support *sandbox*:
  a support switched off stays in the model, in the list and in the drawing, and
  is left out of the stiffness. It is how you find out what a support was
  carrying without editing the design to ask, and without the answer being "the
  matrix is singular".
- **Stage 5** — the first non-rectangular plans (`plan_rule`), Gaussian
  curvature as a colour map, and the straight generators of a ruled surface.
- **Stage 6** — the colour-map guide the list never had; the design comparison
  table; the parameter sweep; then (later, §4) L/t and the verification dome.

### 2b. From the domain session (commits `a6809f7` … `f932b23`)

**Step 1 — a contour instead of a condition.** The Surface panel now has two
boxes, and they are not the same kind of thing:

- `edge where` takes a **signed** expression: negative inside, zero *on* the
  boundary, positive outside. Because the boundary is a curve, the mesh can be
  fitted to it, a beam can be laid along it and supports can sit on it.
- `keep where` is the old yes/no condition. It can say things a single smooth
  `g` cannot (an L, a union of holes) but it leaves a staircase, because there
  is no curve anywhere in it. Both may be given; an element must pass both.

Presets: ellipse, disc, ring, sector 90°, under a hyperbola, and *sector bajo
paraboloide* — named in the owner's own words because that is what their drawing
calls it. `max` of two regions is their intersection and `min` is their union,
which is how a sector is built from a disc and two half-planes with no second
box and no special case. A shortcut writes `y` between two curves as one `g`.

New model data keys: `edge_rule`, `fit_edge` (default `True`), `snap_frac`
(default `0.55`). New methods: `ShellModel.edge_rule_fn()`,
`ShellModel._fit_boundary()`, `shell_solid.boundary_loops()`,
module-level `shell_model._plan_area()`.

**Step 2 — the mesh fitted to it.** Boundary nodes are projected onto `g = 0` by
Newton along the gradient, and a moved node is re-evaluated on the surface or it
would hang off it. Three refusals, each trading a cosmetic problem for no real
one: a move longer than `snap_frac` of an element (it would cross a neighbour);
a move outside the plan rectangle (the surface is only defined there); and a
move that inverts an element or leaves it under a tenth of **its own** area.

**Step 3 — an edge to build on.** `edges` now means the *free boundary*, so on
an uncut plan it is still the four sides, named as before, and once a rule cuts
the plan it is the cut. `rectangle` asks for the plan box on purpose. `corners`
moves each support to the nearest node *on* the cut; `at: cut` supports the
whole rim.

**Step 4 — the card that says which element decides the design.** Three numbers
already fell out of every run and none reached the eye; they went into the
report text at the bottom of the window. The Analyse panel now opens with most
tension, most compression and highest utilisation, each naming its element,
position and the combination or check that put it there. Clicking a row turns
the model to that element, colours by that field and cuts a section through it.

Each row carries **two** answers, and that is the part that matters — see §5.

**Step 5 — the surface it was cut from.** A toggle ghosts the uncut hypar behind
the sector. A Tk canvas polygon has no alpha channel, so the faces are painted
in a colour already blended against the canvas white rather than stippled, and
every ghost face is painted before every real one so the structure is never
hidden by its own reference drawing. Both are lies of a kind, so the canvas says
in red that this is reference, not analysed and not built.

**Step 6 — the design strip (*franja*).** The hand calculation a shell is really
designed by: a metre-wide band treated as an arch or a cable of span `L` and
rise `f`, with `H = q' L² / 8f`, printed beside the membrane force the model
found along the same band. Two buttons put it on the tension or compression
parabola, chosen by **sampling** the rise against the chord rather than by
assuming `z = k x y`, so it works on any surface the tab can mesh. The Sections
panel also names the worst element under the selected cut.

---

## 3. The decisions, and who made them

The understanding note put six questions to the owner with a stated default for
each. The owner accepted every default, so these are the decisions in force:

| # | Question | Decision |
|---|---|---|
| A | What does "elliptical sector" mean? | The contour language does all three readings; ship the elliptical disc as the named preset, with the angular wedge and the hyperbola region beside it |
| B | What is "the sliced element"? | The card gets tension / compression / governing, the Sections panel reports the element under the cut, and the 1 m design strip is built as its own tool |
| C | Where do the beam and supports go when the plan is cut? | On the cut; `rectangle` stays available on purpose |
| D | Trimmed shape drawn, or analysed too? | Analysed too — do not draw a shape the solver did not solve |
| E | `g(x, y)` or `y` between two curves? | `g(x, y)` as the engine, with the band offered as a shortcut that writes a `g` |
| F | How far towards the 55 × 18 m assembly? | **Not now.** It needs the other four to exist first |

Six recommendations were also made and accepted: cut rather than fade, but keep
the ghost as its own feature; do the domain and the edge conditions in one
change; two numbers in each card row; build the 1 m strip as a tool; name
presets in the owner's vocabulary; and say on the canvas what is reference
rather than structure.

---

## 4. The numbers that justify each piece

These are the measurements that made each decision, not illustrations. A
successor who changes the fitting or the edge handling should be able to
reproduce them.

**The staircase was not merely ugly.** On the 12 m hypar cut to its inscribed
circle (element size 0.5 m):

| | staircase | fitted | true |
|---|---|---|---|
| boundary length | 48.00 m | 37.69 m | 37.70 m |
| plan area | 112.0 m² | 113.00 m² | 113.10 m² |

The area converges as the mesh refines; **the perimeter does not**. 8r is the
taxicab perimeter of a circle at *every* mesh size, against 2πr — 27 % long,
forever. An edge beam laid on that boundary would have been 27 % too long and
too heavy however fine the mesh got. That single fact is why the drawn trim was
rejected in favour of a fitted mesh.

**The edge conditions were the bigger problem, and nobody had asked about them.**
With a plan rule active, the beams and supports stayed on the original
rectangle: of the 25 nodes on each edge beam only **7** still touched the shell,
while the 96-edge cut boundary carried nothing at all. The shell was hanging off
four tangent points of a ring it barely held. Putting the beam and the supports
on the cut took the same model from **19.96 mm peak deflection with 8 failing
elements to 1.54 mm with none**, at the same thickness.

**Why each card row carries two numbers.** A support is a stress singularity, so
the worst element anywhere is almost always a corner one whatever the shape
does. `in_head` alone is **4 elements of 576** on the hypar preset, while the
element that actually governs sits **1.06 m away** and is governed by punching —
a statement about the block, not about the shell. The "clear of the supports"
zone is therefore the head plus two element rows.

**The strip's load share is the hand method's one free choice.** With the share
at 0.5, `H = q' L²/8f` on the diagonal reduces **exactly** to the membrane answer
`q/2k` for a hypar — there is a test asserting that. Feeding the whole load to
one family doubles the answer and is the commonest arithmetic mistake in a hand
check of a hypar. The tool reads the real share back out of the model
(`|N| = share · q L²/8f` solved for share): **0.45 and 0.60** on the hypar
preset, **0.37 and 0.49** on the owner's TP 2 module.

**The verification dome.** Spherical cap, r = 28.80 m, half-angle 28°,
t = 10.2 cm, ν = 1/6, 4.31 kN/m² over its surface, from Mekjavić & Pičulin
(2010). The model reproduces the closed-form membrane solution to better than
1 %: apex −62.06 against −62.06 kN/m; at φ = 4°, −62.11 and −61.71 against
−62.14 and −61.69. The edge disturbance is checked by its own length scale,
β = [3(1−ν²)]^¼ √(R/t) = 21.96, spent within 3/β = 7.8°.

---

## 5. Things that were got wrong, and corrected

A successor is more likely to be helped by these than by the successes.

1. **"How does the sliced element work?" — nothing was sliced.** The plan rule
   judged each element once, at its centre, and kept or dropped it whole. There
   was no slicing anywhere in the code. Worth checking the premise of a question
   against the code before answering it.

2. **A published table carried in memory was wrong, and was not asserted.** The
   dome paper's edge values were in memory as N_φ = −62.60 kN/m. That cannot be
   right: everything the dome weighs has to leave through the edge, so
   N_φ sin α × circumference **is** the weight, which pins N_φ at −65.9 kN/m
   whatever the support does and whatever bending occurs. The model gives
   −65.42. The tests therefore assert the closed form and global equilibrium,
   and the remembered table is not asserted anywhere. **Do not add it back.**

3. **A plausible diagnosis that was simply false.** The compression parabola
   disagreed with the hand value more than the tension one, and this was first
   explained as "this strip runs into a support". It distinguishes nothing — on
   a hypar carried at four corners *both* diagonals end on supports. The real
   cause was the edge beams' weight in `q`. The strip now reports both load
   assumptions instead of claiming a mechanism.

4. **The sliver guard measured the wrong thing** (found by building the dome).
   It compared each element against a fixed fraction of the grid square, but an
   element whose centre is barely inside the curve is *supposed* to lose most of
   its area — three of its four nodes are outside it. Judged that way it looked
   like a sliver, was reverted, and the boundary kept a step exactly where the
   curve is steepest: on the dome, **24 nodes left behind and a perimeter 4.6 %
   long**. It now compares each element against its own area before the move.

5. **A pre-existing bug the new work exposed.** `section_profile` returned GRID
   positions as its element numbers, which stopped being element numbers the
   moment a plan rule removed any element. The cut face was being coloured by
   whatever element happened to land on that index, and asking for the worst
   element under a cut raised `IndexError`. It now takes `kept` and returns −1
   where the plan was cut away; the face skips those spans and the three profile
   lines are drawn in runs, because a line run straight across a hole draws
   shell that is not there.

Earlier in the project, also worth knowing: `PanedWindow.panes()` returns Tcl
path names, not widgets, so a pane swap compared against widgets silently never
fires; and a sweep that does not restore the value it moved has quietly edited
the design, so `sweep()` restores in a `finally:`.

---

## 6. Can the owner build their own TP 2 structures?

Their drawing (*TP 2 Paraboloide Hiperbólico*) was rebuilt in the tab. This is
the most useful single check of whether the tab is fit for its purpose.

**Geometry goes in exactly.** Their generating parabola is span 9√2 = 12.72 m,
rise f = 1.09 m, which is `z = k x y` with k = 0.0538 m⁻¹. Typing
`c = 4.36`, `z(x,y) = c x y/(a b)` with a = b = 9 and asking the tab what surface
it had built returned **k = 0.053827**, and the strip reads span **12.73 m**,
rise **1.090 m**.

**The hand method is vindicated for this shell.** Their membrane shear is
2 319 kg/m = 22.7 kN/m; the model's field value is 19.2–27.8 kN/m. Bending in
the field is ≤ 0.19 kNm/m, so their assumption of zero is sound. Deflection
4.4 mm long-term against a 36 mm limit.

**Where 6 cm fails is not where anyone would expect.** Nothing in the shell
passes half capacity — concrete compression 0.23, bending 0.10, transverse shear
0.41, buckling 0.22. What fails is **cover** (utilisation 1.43: 35 + 8 + 35 mm
does not fit in 60 mm, so the CIRSOC detailing minimum is 8.6 cm) and
**punching at the support block** (2.78). Neither is visible to a membrane hand
calculation. Two honest routes: go to 8.6 cm, or argue a lower cover class,
which the tab lets you set and will re-check.

**What they still cannot build** is in §7.

---

## 7. What is NOT built

Deliberately, and in rough order of how much the owner seemed to want it:

- **The 55 × 18 m assembly.** The tab meshes *one* `f(x,y)` over *one*
  rectangle. Their big figure is several hypar tiles at different orientations
  meeting along ridges and valleys. Some shapes of that kind can be written as a
  single formula — the inverted-umbrella preset already is, using `abs(x)` — but
  a general assembly of tiles is a real change to the model: several surfaces,
  shared edges, a ridge that is a beam. This was explicitly deferred (Question
  F) because the other four pieces had to exist first. **It is the largest open
  item and the most likely next request.**
- **A tie between two chosen points.** Their drawing resolves the thrust `H`
  with a tie. There are edge beams and columns but no tie member.
- **Inclined supports** that take thrust along a chosen direction.
- **Buckling load.** The solve is linear and small-deflection. The tab can
  *warn* — it prints L/t, maps Gaussian curvature and flags deflection against
  the thickness — but it cannot tell you the buckling load. OpenSees is the
  route to that and is already on the owner's reading list.
- **Form-finding.** The shape is the owner's to specify.
- **Cracked-section or long-term behaviour** — no creep, shrinkage or crack
  widths; the check stays a strength check.
- No dynamic, thermal or staged-construction analysis.

---

## 8. Verifying all of this in five minutes

```bash
cd "STRUCTURAL SYMULATOR SOLVER-5-9-26"
Xvfb :95 -screen 0 1400x900x24 &
DISPLAY=:95 /usr/bin/python3.12 -m pytest -q tests/test_shell_domain.py \
    tests/test_shell_dome.py tests/test_shell_strip.py tests/test_shell_governing.py
```

The eight shell test files and what each is for:

| File | Tests | Protects |
|---|---|---|
| `test_shell_engine.py` | 21 | MITC4 against published answers, membrane theory, CIRSOC, wind |
| `test_shell_solid.py` | 33 | The slab geometry, and the section-to-element mapping |
| `test_shell_app.py` | 21 | The window |
| `test_shell_modes.py` | 61 | The six-mode rail, colour list, cuts, guide, comparison, sweep |
| `test_shell_domain.py` | 32 | **The contour and the fitted boundary.** If anyone changes the fitting guard, these say so |
| `test_shell_governing.py` | 15 | The card, and that its second answer is really clear of the supports |
| `test_shell_strip.py` | 34 | The strip, the ghost, and the element under a cut |
| `test_shell_dome.py` | 11 | The verification dome |

The two tests worth reading first, because they encode claims about reality
rather than about code:
`test_shell_domain.py::test_the_unfitted_perimeter_is_the_taxicab_one_and_stays_wrong`
and `test_shell_strip.py::test_the_hand_value_is_the_exact_membrane_answer_for_a_hypar`.

---

## 9. Working rules the owner expects

Learned from how these sessions went, and worth keeping:

- **Plan with pictures before building.** Asked for explicitly, twice. Both
  times the plan changed what got built — the second time it surfaced the edge-
  condition problem, which was the most valuable thing in the session and was
  not on the owner's list.
- **Ask, with a stated default for each question.** The owner answered "I like
  all the default options" to six questions at once; that only works if each
  default is a real recommendation rather than a shrug.
- **Measure, do not assert.** Every claim in the note was a number from a run.
  The one place memory was trusted instead (the dome's table) is the one place
  it was wrong.
- **Say what was got wrong.** Four corrections are recorded in §5 and in the
  commit messages, in the owner's view, rather than quietly fixed.
- Commit messages in this branch are long on purpose: they carry the reasoning
  and the measurements, because the code cannot.

---

## 10. Commit map

```
21c8ca8  Build zip: the shell domain work
f932b23  Stage 6 closed: L/t in the table, and the dome in the verification set
68528a1  The strip's load: whose weight, and which family carries it
e6b8928  Steps 5 and 6: the surface it was cut from, and the strip you design by
ba01918  Step 4: the card that says which element decides the design
a6809f7  Steps 1-3: a contour, a mesh fitted to it, and an edge to build on
9582f02  The domain note: what I understood, before building any of it
1688134  Stage 6, second part: compare designs, and sweep one number
490a812  Stage 6, first part: the guide the colour list never had
2a6a559  Stage 5: the end of the rectangular plan, and two things the shape knows
c30f4b6  Stage 4: pick the supports on the model, and a sandbox to argue with them
c62fcf0  Stages 2 and 3: cuts you can keep, and one mode at a time
118c4e4  Stage 1: draw the shell as the slab it is
2c5fe7f  Rev. 5 of the plan, written with the tab running
305e2a5  Stage 0: bring the Shell (RC) tab into the repository
1eb5864  Run the app headlessly, and correct the plan: there is no Shell tab
587f84f  Read the plan against two papers on concrete shells
3a08053  Rebuild the plan on what the earlier sessions already established
ccec1c2  Record the four answers, and rebase onto the Stereo branch
f446b1c  A plan for the Shell tab, with the pictures to argue with
```

Test count over the branch: 2678 at Stage 0 → 2693 → 2728 → 2763 → 2776 →
**2880** at the head.
