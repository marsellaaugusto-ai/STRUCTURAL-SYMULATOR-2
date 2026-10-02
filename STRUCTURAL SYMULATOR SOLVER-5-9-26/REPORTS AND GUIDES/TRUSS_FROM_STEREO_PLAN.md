# Truss tab — what it can take from the Stereo tab, and a plan

2026-10-02. The Truss tab is a **2D** calculator (x, y; 2 DOF per pinned node,
3 per rigid node). Its job is didactic: draw a truss, load it, and *see* how
the forces travel. Every feature below was judged against two questions:

1. Does it make sense in a plane?
2. Does it teach something, without making the tab harder to use?

A Stereo feature that is only about the third dimension, or one that is
powerful but adds controls, was left out or postponed. Section 4 lists those.

---

## 1. Where the Truss tab stands today

**What it already does well.**
- A direct editor with Node, Rod, Support, Load and Select tools.
- A CAD snap bar, coordinate and polar placement, a ruler, guides and arrays.
- Pin and rigid (Vierendeel) rods in one model, with span loads on rods.
- Reactions and the deformed shape.
- Shear and moment diagrams for rigid rods, a Vierendeel diagram and a
  compression/tension fibre diagram.
- Gusset plates and shear panels with their checks.
- Rod families (E, A, I), and unit selection.
- Undo/redo and copy/paste.
- Excel export and import.
- Two reports that show the work: *Node Force Vectors* draws a free-body
  diagram at every joint, and *Rod Calculations* gives each rod's details.

**What it does not have** (all of which Stereo has):
- No CIRSOC 301 check of the rods.
- No section catalogue.
- No PDF report.
- No statement of whether the truss is determinate.
- When the model cannot stand, no indication of *where* it is a mechanism.
- No buckling.
- No load slider.
- No self-weight.
- No weight/efficiency score.
- No lesson attached to the examples.

### Fixed today (in this change)

| # | Problem found | Fix |
|---|---|---|
| B1 | **Crash.** After *Node Force Vectors* or *Rod Calculations* had been opened, every later ▶ Analyze raised `TclError: window ".!toplevel" isn't packed`, and the diagrams never appeared. The diagram pane was packed "before the root's last child", which by then was the report window. Found by pressing all 240 controls of the tab. | The pane is now packed just above the status bar. Regression test included. The UI audit went from 7 errors to 0. |
| B2 | Apply/Remove load and Apply/Remove support recorded an undo step *before* checking that a node was picked, so Ctrl+Z could "undo" nothing. | They check first, and say "Pick a node with the Load/Support tool first." |
| B3 | In shear/moment rows, the largest value was printed exactly on top of the "0" label. | The duplicate was removed; the peak is still labelled at the peak. |
| B4 | A failed analysis left the old status text on screen (e.g. "Warren truss loaded — click ▶ Analyze"). | The status bar now says "Analysis failed — …". |
| B5 | An analysis with no loads reported "Done — 0 tension, 0 compression". | It now says why every force is zero and what to do. |
| U1 | **The diagram pane taught nothing for a classic truss**: every pinned rod had a tall row of two empty shear/moment boxes. | When no rod bends, the pane is one compact signed bar chart: one bar per rod, compression to the left of zero, tension to the right, with its value and the word. The whole result fits on one screen. When some rods do bend (Vierendeel), each row starts with its axial bar. A rod that does not bend says why ("pinned at both ends and loaded only at its nodes"). |
| U2 | The rods showed only their numbers; the forces were hidden in the side panel. | Once solved, each rod reads `number: N` (e.g. `6: -112.5`). Editing the model brings back the bare numbers. |
| U3 | The colour legend was at the bottom of a scrolling side panel. | A one-line key is drawn on the canvas once solved: red tension (+), blue compression (−), grey zero. It stays pinned to the bottom edge when the diagram pane opens. |
| U4 | The "Assumed material" box opened with a nine-line grey paragraph. | Two lines now say the same thing. |

---

## 2. Assessment: Stereo features, judged for a 2D truss

Value is didactic value; cost is implementation effort (S ≈ hours, M ≈ a day,
L ≈ several days).

### Worth bringing over

| Stereo feature | In 2D | Value | Cost | Notes |
|---|---|---|---|---|
| **Mechanism animation** (a model that cannot stand is drawn moving) | Yes. The null space of K with 2/3 DOF per node is the same mathematics. | ★★★ | M | Today a missing diagonal gives only "Singular stiffness matrix". Showing the panel collapsing is the single best lesson about triangulation. |
| **Indeterminacy readout** (m + r − 2j, plus the caveat about rigid-body motion) | Yes, and simpler than in 3D. | ★★★ | S | It says "determinate", "indeterminate to degree n" or "a mechanism" *before* the solve, and explains why the count alone can be fooled. |
| **Zero-force rods** highlighted, and *hide ~0-force rods* | Yes. | ★★★ | S | A classic exam topic. |
| **Play load 0 → 100 %** and a Load % slider | Yes. The model is linear. | ★★ | S | The rods thicken and the deformation grows as the load rises. |
| **Support sandbox** (click a support to switch it off and re-solve) | Yes. | ★★★ | S | Pin vs. roller vs. nothing, felt directly. Pairs with the mechanism animation. |
| **Live re-analysis** for small models | Yes. Truss models are always small. | ★★ | S | Drag a node and watch the forces change. |
| **Crowded-label auto-hide** (with an override) | Yes. | ★★ | S | Some overlap can already be seen on the Vierendeel example. |
| **Long hints fold behind a "?"** | Yes. | ★ | S | The *Connection type* box and the plate boxes still open with long grey paragraphs. |
| **Simple / Advanced switch** | Yes. | ★★★ | S–M | It hides the CAD bar, guides, arrays, plates and the rod-family manager in Simple mode. This one switch keeps the tab simple for beginners, and nothing is lost for advanced users. |
| **Section catalogue + CIRSOC 301 rod checks** (tension yield/fracture, compression with KL/r, slenderness limit) | Yes. `stereo_checks.check_member` works per rod from N, L and the section, so it does not care about dimension. | ★★★ | M | It turns "the force in each rod" into "is each rod strong enough". The utilisation colour scale comes with it. |
| **Explain this rod** (the CIRSOC formulas with this rod's numbers) | Yes. `stereo_explain` can be reused as it is. | ★★★ | S once the checks exist | It is the bridge between the force and the code. |
| **Governing rod + "Show me this rod"** | Yes. | ★★ | S | |
| **Self-weight** | Yes, as nodal loads from A·L·γ. | ★★ | S | |
| **Deflection limit** (L/300, L/250) | Yes. | ★★ | S | "It stands, but it sags too much." |
| **Weight / efficiency score** (kg, kg per kN carried) | Yes. `stereo_score` can be reused. | ★★★ | S | Bridge-builder motivation: "same load, lighter truss". |
| **Lessons on the examples**, plus a small example library | Yes. | ★★★ | S–M | Warren, Pratt, Howe, K, cantilever, scissor, Vierendeel, a deliberate mechanism and a zero-force-rod puzzle. Each opens with one short card: what to look at and what to try. |
| **Design variants side by side** | Yes. | ★★ | M | Pratt vs. Howe under the same load is the textbook comparison. |
| **Buckling demonstration** (modes) and the second-order load–deflection curve | Yes, as a 2D version of `stereo_buckling`, with 3 DOF per node and the same geometric stiffness pattern. | ★★ | M | Shows why the compressed rods are the ones that matter. Demonstration only, as in Stereo. |
| **PDF report**, every drawing to scale | Yes. A 2D sheet is simpler than the 3D views. | ★★ | M | Sheets: geometry with dimensions; forces (colour + labels); deformed shape; the force table; checks. Equal x/y scale on every drawing, under the same test as Stereo. |

### Left out, and why

| Stereo feature | Why not |
|---|---|
| Surface wizard, Shape mode, two-surface layers, 14 parametric families | They describe surfaces in space; a plane truss has none. |
| Module Editor, cell census, auto-grouping by pieces | They are useful because a space frame repeats thousands of cells. A 2D truss is read at a glance. |
| Columns, capitals, reinforcement beams, cable crane, simplified wind on roofs | 3D add-ons for roofs and erection. |
| View cube, orbit camera, perspective, axis gizmo | Nothing to orbit in 2D. |
| Sparse solver | Truss models are a few hundred DOF at most. |
| Groups as layers, Excel group sheets, merge of Excel files | Most of the value is in big models. The Truss tab already has rod families. |
| SketchUp and IFC export | BIM handover, not teaching. |
| The nine-mode rail | It would *add* structure to a tab whose strength is that everything is on one screen. The Simple/Advanced switch gives most of the benefit at no cost. |
| Timber (CIRSOC 601) rod checks | Possible later, after the steel checks, if wanted. |

---

## 3. Implementation plan

Every phase follows the rules the Stereo work followed:
- The pure logic goes in `apps/truss/` modules, with no Tk, and gets unit tests.
- The UI goes into `truss_app.py`, which is already 4,900 lines. New UI goes
  in small mixin modules (`truss_app_<topic>.py`), the way `stereo_app.py` was split.
- Every phase ends with the full test suite, the 240-control UI audit at
  0 errors, and screenshots read by eye.
- No phase adds a new toolbar row. New controls go in the side panel, and the
  Advanced ones hide in Simple mode.
- Every new drawing keeps x and y at one scale.

### Phase 1 — "Read the result" (S each, about 1–2 days in all)
1. **Simple / Advanced switch.** It sits on the toolbar's first row in place of
   nothing (the row has room). Simple hides:
   - the CAD bar;
   - guides and arrays;
   - plates;
   - the profile manager;
   - Vierendeel and fibre diagram modes (shown only when a rigid rod exists).

   It is remembered per session. Test: every control reachable in Advanced; the
   Simple set is listed in the test.
2. **Indeterminacy readout** under ▶ Analyze. `truss_math.indeterminacy(nodes,
   rods, supports)` returns (m, r, j, degree, verdict), with the rank check
   that catches a "determinate by count" mechanism. Tests: Warren = 0, the
   same truss with both supports fixed = +2, a missing diagonal = −1.
3. **Zero-force rods**: drawn dashed grey, with "hide 0-force rods" in the view
   options. The status bar names how many there are.
4. **Crowded labels**: rod and node numbers hide when they would overlap,
   with an override. This is a port of `_labels_crowded`.
5. **"?" folding** of the remaining long hints. This is a port of
   `_collapse_long_hints`.
6. **Support sandbox**: with the Select tool, a right-click on a support
   switches it off and re-solves. Shown with a crossed glyph.
7. **Live re-analysis** (a checkbox; on by default below 300 rods).

### Phase 2 — "Why it fell" (M)
8. **Mechanism animation.** `truss_math.mechanism_mode(nodes, rods, supports)`
   is the 2D port of `stereo_math.mechanism_mode`: the smallest singular
   vector of K, with rigid-body motion separated from internal mechanisms.
   The canvas animates the moving nodes and highlights the panel without a
   diagonal. The status bar says "This truss is a mechanism: the highlighted
   panel has no diagonal" (or "no support stops it sliding in x").
   Tests:
   - Warren minus one diagonal: the moving nodes are that panel's.
   - Only one roller: the motion is a rigid slide.
   - A lone node: it is named.

### Phase 3 — "Is it strong enough" (M, about 2–3 days)
9. **Section catalogue** for rod families (L, double-L, tube, round bar),
   reusing `stereo_profiles` and `cirsoc_301`. A family gets a real section
   instead of bare E/A/I, which are still allowed for the "forces only" use.
10. **CIRSOC 301 checks** per rod (`stereo_checks.check_member`):
    - utilisation in the rod table;
    - a *Utilisation* colour mode;
    - the governing rod in the status bar, with "Show me this rod".
11. **Explain this rod** (`stereo_explain`): the formulas with this rod's
    numbers, from a right-click or the Selection box.
12. **Self-weight** checkbox (γ = 78.5 kN/m³ by default).
13. **Deflection limit**: the maximum deflection against L/300, said in plain words.

### Phase 4 — "Play and compare" (S–M)
14. **Load % slider and ▶ Play load**: the forces and the deformed shape grow
    together, and the first rod to reach 100 % utilisation is named (after
    Phase 3).
15. **Score**: total mass, and kg per kN carried. A "best so far" line is kept
    for each example.
16. **Example library with lessons**. There are 9 examples, each with one
    card: what to look at and what to try. "Delete rod 1 and analyse" leads
    into the mechanism animation, and "Which rods carry nothing?" leads into
    the zero-force rods.
17. **Design variants**: keep up to 3 solved snapshots and show them side by
    side, at the same scale and with the same colour range.

### Phase 5 — "Stability" (M)
18. **Buckling demonstration (2D)**. `truss_buckling.py` is the 2D reduction of
    `stereo_buckling`. Each rod is split at mid-length, the geometric stiffness
    is P/(30L) for rigid rods and P/L for pin rods, and the problem is
    `eigh(-KG, K)`. It shows the modes and the factor λ ("it buckles at 3.7 ×
    this load"), plus the load–deflection window. Tests: a pinned column
    against Euler within 1 %, and a cantilever against Euler with K = 2.

### Phase 6 — "Hand it in" (M)
19. **PDF report**:
    - a cover with the model data;
    - geometry with dimensions;
    - axial forces (colour + labels + key);
    - the deformed shape with the limit;
    - the reactions;
    - the rod table with utilisation;
    - "explain" pages for the governing rods.

    All views are to scale, checked by the same aspect test as Stereo.

### Order and checkpoints
- Phases 1 and 2 first. They are cheap, and they change most what a student
  *sees*.
- Phase 3 is the largest piece of value for practitioners.
- Phases 4–6 follow in any order.
- Each phase is its own commit after the full gate. A release zip follows
  whichever phase you want to hand out.
