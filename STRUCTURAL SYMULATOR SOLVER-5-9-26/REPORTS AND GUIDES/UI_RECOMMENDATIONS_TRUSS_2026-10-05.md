# Truss tab — UI recommendations for an architectural-education audience

Date: 2026-10-05
Scope: `apps/truss/truss_app.py` (and the shared widgets it uses in `common.py`).
Audience assumption, as stated by the project owner: **the users are architecture
students learning how structures behave**, not practising structural engineers.
Nothing here asks for a change to the solver — every item is about what the
screen says, where it says it, and in what order.

This document is advisory. No code was changed.

---

## 0. The one-paragraph verdict

The Truss tab is, as a piece of engineering software, unusually well built: the
FlowBar/ScrollPanel work means no control is ever lost off an edge, the snapping
and CAD entry are genuinely CAD-grade, the hover tooltips are informative, and
the Rod Calculations report — context diagram, typeset equation, free-body
diagram at both ends — is exactly the right didactic idea. The problem is that
the tab is laid out as a **modelling tool that happens to produce teaching
material**, when for this audience it should be a **teaching instrument that
happens to let you model**. Concretely: the primary action (Analyze) is the
thirteenth block down a scrolling panel; the diagram pane shows nothing but
empty boxes for a classic pin-jointed truss; the vocabulary on screen
(`rollerX`, `Fexx`, Whitmore, landing, block shear) is steel-detailing
vocabulary; and the deepest teaching moment the app can offer — "your structure
is a mechanism, it moves" — is delivered as the string
`Singular stiffness matrix – check for mechanisms or floating nodes.`

The list below is ordered by *value to a learning architect per hour of work*.

---

## Tier 1 — high value, low effort

### 1. Add an axial-force (N) diagram; it is the only diagram a truss has
`_draw_diagrams_only` (line ~4067) draws, per member, a Shear V panel and a
Moment M panel. For a pin-jointed rod both are identically zero by definition,
and the code correctly labels each row `pin — no bending`. The consequence: a
student loads the built-in Warren truss example, presses Analyze, and the
diagram pane fills with seven rows of empty rectangles. The first analysis a
beginner ever runs produces a blank result.

`compute_diagrams` (`truss_math.py:1010`) returns `xs / V / M / Lm / RA / RB` —
there is no `N` anywhere in it.

- Add a fourth diagram mode, **"Member forces (N)"**: one horizontal bar per
  member, length ∝ |N|, red for tension, blue for compression, member id and
  value on the bar.
- Make it the **default mode whenever no rod in the model is `rigid`** (i.e. for
  every classic truss), and keep `truss`/`vierendeel`/`fiber` as they are.
- This is the single highest-value change in the document.

### 2. Move Analyze (and the results) to the top of the panel
`self.analyze_btn` is packed at line 1034 of `_build_panel`, after: material,
selection, connection type, distributed load, point load, construction
geometry, arrays, plates, the gusset bolt grid, plate checks and rod families.
On anything short of a tall monitor the student must scroll a 235 px column
past ten LabelFrames to reach the button that does the thing the app is for,
and then keep scrolling to find the numbers it produced.

- Pin a compact **Analyze + headline results strip** at the top of the right
  panel, or better, as a non-scrolling footer of that panel so it is on screen
  at all times.
- Headline results = the three numbers already in `res_var` (max tension, max
  compression, max displacement), nothing more.

### 3. Collapse the advanced blocks by default
Of the eleven always-packed panel sections, four are irrelevant to an
architecture student for weeks: **Plates** (with its Gusset-connection
sub-frame: bolt d, rows × cols, pitch, gauge, end, edge, landing), **Arrays**
(path/grid/polar), **Construction geometry** (y=f(x), 5-pt conic, fitted
families) and **Rod family / profile**.

- Give each LabelFrame a disclosure triangle; remember the state.
- Ship with Plates, Arrays, Construction geometry and Rod family **collapsed**.
- The tab stops looking like a steel-detailing package and starts looking like
  a place to try an idea.

### 4. Fix the unit contradictions on the canvas
The app has a global unit selector in `main.py` and a careful `UnitsMixin`, and
then prints `kN` literally in places the selector cannot reach. If a student
switches to kip, the panel says kip and the drawing says kN, in the same
window, about the same number:

- `truss_app.py:2200-2201` — node hover tooltip (`Load Fx=… kN`, `Rx=… kN`)
- `truss_app.py:2230-2231, 2242` — load and support hover tooltips
- `truss_app.py:3090` — "Rod forces on this node" in the Selection panel
- `truss_app.py:3338` — the point-load label drawn on the member
- `truss_app.py:3736, 3751` — the load and reaction arrow labels on the canvas
- `truss_app.py:4461-4478` — the free-body-diagram canvases
- `truss_app.py:4624-4646` — the typeset equations in Rod Calculations
- `truss_app.py:2657, 2796` — status-bar confirmations

All of these should go through `self.fmt(...)` / `self.u(...)` like the rest of
the tab already does. A teaching tool that contradicts itself about units
teaches the wrong lesson very efficiently.

### 5. Two different greens mean two different things
`common.py:183` `CD = "#1D9E75"` (deformed shape) and `common.py:194`
`CR = "#2ecc71"` (reaction arrows) are both green, and the panel legend
(`truss_app.py:1059`) lists them four rows apart. Give reactions a hue nothing
else uses — a dark violet or black-green — or distinguish them by form
(reaction = solid triangle-tailed arrow, deformation = dashed line) and say so
in the legend.

### 6. `Ctrl+X` is bound to Redo
`truss_app.py:283`. Every other application the student has ever used binds
`Ctrl+X` to Cut. Bind Redo to `Ctrl+Y` and `Ctrl+Shift+Z`, and leave `Ctrl+X`
either unbound or wired to an actual cut.

### 7. Undo exists and is invisible
There is a full undo/redo stack with human-readable labels (`_push_undo('load
example')`, `_undo` reports `Undo: <label>`), and no button anywhere. Two
toolbar buttons, greyed when the stack is empty, with the pending label in the
tooltip. Beginners experiment far more freely when they can see the way back.

### 8. Panning requires a middle mouse button
`ZoomCanvas` binds pan to `<ButtonPress-2>` / `<B2-Motion>` only
(`common.py:534-536`). A large share of this audience is on a laptop trackpad
or an Apple mouse with no middle button, and therefore **cannot pan at all**.
Cable Web already solved this with an explicit `Pan` tool button. Add the same
here, plus space-bar-drag as the CAD-standard alternative.

### 9. There is no "zoom to fit"
`reset_view()` returns to zoom = 1, pan = 0. A student who path-arrays nodes
onto a guide at x = 60 m loses the model off-screen and has no way to find it
except by guessing at pan. Add a **Fit model** button (Cable Web has `Fit`)
and bind it to a key.

### 10. A half-built model cannot be saved
`_export_excel` (line 4688) refuses with "Run the analysis first before
exporting". So a student who has placed twenty nodes and must leave the studio
cannot save. There is also no `Ctrl+S` and no native project file.

- Allow export of an unsolved model (write the results sheets only when results
  exist).
- Add `Ctrl+S` / `Ctrl+O` for a simple JSON model file — faster, lossless, and
  easier to hand in and mark than a workbook.

### 11. The diagram-pane caption describes one mode and is shown in all three
`truss_app.py:330` — `(shear silhouette left, moment silhouette right — rigid
rods only)` is a description of the Vierendeel mode and stays on screen in
Truss-diagram and Fiber mode too. Make the caption follow `diagram_mode`.

---

## Tier 2 — the didactic layer the app is missing

### 12. Give the Truss tab the help system Cable Web already has
Cable Web has `_show_guide` (a two-tab dialog: step-by-step workflow + a
reference entry for every single control), a `📖 How to use Cable Web` button,
`F1`, and an `InfoTooltip` on essentially every toolbar widget. The Truss tab
has **six** tooltips in 4 800 lines (`_bind_widget_tooltip`, 6 call sites) and
no guide at all. Port the pattern. For this audience the guide should be
organised around *questions* ("How do I stop my truss from collapsing?",
"Why is this member grey?"), not around controls.

### 13. Turn the failure messages into the lesson
Three dead-end modals (`Need ≥ 2 nodes.`, `Need ≥ 1 rod.`, `Need ≥ 1 support.`
at lines 2956-2961) and one that is the most important teaching moment the app
will ever have:

> `Singular stiffness matrix – check for mechanisms or floating nodes.`

For an architect, "your structure is a mechanism" *is* the curriculum. Replace
with a diagnostic panel that:
- names it in plain language — *"This structure isn't stable yet: it can move
  without stretching any member. That's a mechanism, not a truss."*
- **shows it**: highlight the unrestrained node(s) or the un-triangulated bay in
  orange on the canvas; where the null-space of the stiffness matrix can be
  extracted, animate the model moving along it. Seeing the four-bar square
  parallelogram itself over teaches more than any sentence.
- offers the fix as a button: *"Add a diagonal here"*, *"This node needs a
  second support"*.
- the three "Need ≥ …" cases become the same panel, non-modal, as a live
  readiness checklist rather than a popup you dismiss.

### 14. A visible build checklist
Replace the single status line's opening message with a five-step strip that
ticks itself: **① Joints ② Members ③ Supports ④ Loads ⑤ Analyze**, each step
lit when satisfied, Analyze enabled only at ⑤ (the button already greys itself
via `analyze_btn` colour, but it stays clickable and the greying is not
explained). This gives a first-time user the whole workflow in one glance and
removes the need for the three warning modals entirely.

### 15. Animate the deflection
`def_scale` (1–300) is already the right control. Add a **play button** that
oscillates the deformed shape between 0 and the set scale at ~1 Hz. Exaggerated
motion is the most effective single device for making a non-engineer feel what
a structure is doing, and the deformed geometry is already computed
(`deformed_shape_points`). Cost: a `root.after` loop around the existing draw.

### 16. Call out the zero-force members
Zero-force members are the classic first lesson of truss analysis and the app
currently renders them in the same grey as "not yet analysed" (`CZ`), which
conflates "this member carries nothing" with "I haven't solved yet". Give
solved-zero its own treatment (thin dashed, a small `0` tag) and a one-line
explanation in the Selection panel: *"carries no force in this load case —
remove it and the truss still stands, but it may be doing a job in another
load case."*

### 17. Label the forces on the drawing, not only in the table
Architects read drawings. The canvas already encodes force beautifully by
colour and line weight (`lw = 2 + min(5, |f|/8)`) — the remaining step is an
optional **"Show member forces"** toggle that writes the value and T/C directly
on each member, so the drawing is self-contained and screenshot-able for a
crit. Today the numbers live in a 22-character-wide `Text` widget
(`rod_res_text`, 7 rows) that nobody will read on a projector.

### 18. Make "what if?" the cheapest action in the app
Two cheap moves, both enormous for learning:
- **Auto-analyze.** These models are a handful of DOF; the solve is
  instantaneous. Offer a *Live* toggle that re-solves on every edit, so dragging
  a node makes the colours change under the cursor. The explicit Analyze step
  breaks exactly the feedback loop that teaches.
- **Ghost comparison.** Keep the previous result as a faint underlay so that
  adding one diagonal visibly redistributes the forces. "Before/after" is how
  the lesson lands.

### 19. One permanent Conventions card
Sign conventions are currently scattered through fine print: `Fy (kN, ↓+)`,
`0° = right, 90° = down`, `0° ⟂ +90° along A→B −90° opposite`, `% from A`,
`end s = 0 means the whole guide`. Each is correct and each is 7–8 pt grey.
Collect them into one small always-available card (a `?` in the toolbar) with a
*drawing* of the axes, the positive load direction, tension positive, and the
member-local A→B direction. Replace the scattered fine print with a link to it.

### 20. Make the load path visible
The thing an architect actually needs to internalise is *where the load goes*.
Consider a **load-path mode**: click a loaded joint and the app traces, with
animated chevrons along the members, the route from that load to each support,
with the share each path carries. This does not require new mathematics — the
member forces are all solved — and it is the one feature that would make this
tab unambiguously an architectural-education tool rather than a small FEM
front-end.

---

## Tier 3 — vocabulary, legibility, polish

### 21. Replace engineer-speak in the visible labels
Keep the technical term, lead with the meaning:
- `rollerX` / `rollerY` → **"Roller (slides horizontally)"** / **"Roller (slides
  vertically)"**. These are the literal combobox values at line 528.
- `pin` → **"Pin (held, can rotate)"**; `fixed` → **"Fixed (held, can't rotate)"**.
- `UDL` → **"Spread load along member"** (UDL).
- `Fexx` → **"Weld metal strength (Fexx)"**; `landing`, `Whitmore`,
  `block shear`, `Thornton` → keep, but inside the collapsed advanced block
  with a one-line gloss each.
- `5-pt conic`, `s` along a guide, `w_t` → gloss or hide.

### 22. Draw the support types instead of naming them
A `ttk.Combobox` of four words is the wrong control for four things that have
universally recognised *symbols* — and the app already draws all four in
`_draw_support`. Replace the combobox with four icon buttons using those same
glyphs. The student learns the symbol by using it. Same treatment for
Connection type: show the little pin circle vs. the moment-connection ticks
that `_draw` already renders on rigid rods.

### 23. Material by name, not by number
"Assumed material (all rods)" opens with a five-line 8 pt grey disclaimer and
then asks for E, A and I as bare numbers. An architecture student does not know
that E = 200. Offer a **preset dropdown** — Steel S275, Glulam GL24h, Reinforced
concrete, Aluminium — that fills E, and a small section-size preset that fills
A and I, with the raw fields still editable underneath. Move the disclaimer into
a `?` popover.

### 24. Typography is below classroom legibility
The panel is `PANEL_W = 235` px and carries a great deal of 7 pt and 8 pt text
in `#666` on `#f0f0ee` (e.g. the guide help lines, `0° ⟂ +90° along A→B`, the
plate defaults note, the array hints). On a projector or a shared screen this
is unreadable, and on a 4K laptop it is unreadable up close too.
- Floor the body text at 9 pt and the help text at 9 pt italic in `#555`.
- Add a single **text-size control** (100 % / 125 % / 150 %) applied as one
  scale factor to every font in the tab. Every `font=('Helvetica', n)` is
  currently a literal; routing them through one helper is a mechanical change
  and would also serve a "presentation mode" for teaching.

### 25. Stop the panel from jumping
`load_frame` and `sup_frame` are `pack_forget()`-ed and re-packed as the tool
changes, which shifts everything below them. Reserve the slot (or put both in a
fixed-height contextual area at the top of the panel) so the Selection panel and
the rest do not move under the cursor.

### 26. Letters for joints, numbers for members
Nodes and rods are both labelled with bare integers, and both renumber when
something is deleted, so a student's notes stop matching the screen. The classic
teaching convention — joints A, B, C…, members 1, 2, 3… — removes the ambiguity
at a glance, and stable ids (never reused) would stop a deletion rewriting the
drawing's labels.

### 27. Don't rely on hue alone for tension/compression
Red/blue is a reasonably colour-vision-safe pair, but the legend distinguishes
seven colours by hue alone, two of which are the near-identical greens of
item 5. Add the sign to the legend swatches (`T +` / `C −`) and consider a
hatch or arrowhead convention (arrows pointing into the member for compression,
out for tension) — which also happens to be how the textbook draws it.

### 28. Give the diagram pane a draggable splitter
`diag_outer` packs with a fixed `INIT_DH = 260` canvas and `fill='x'`. After an
analysis, on a 768 px-high laptop, the vertical budget is roughly: units bar +
notebook tab (~50) + toolbar wrapped to 2–3 rows (~90) + CAD bar wrapped
(~80) + diagram pane (~280) + status (~25) ≈ 525 px of chrome, leaving ~240 px
for the model itself. The drawing should always be the largest thing on screen.
Make canvas/diagrams a `PanedWindow` with a draggable sash, remember the
position, and let the diagram pane be collapsed to a title bar.

### 29. Let the CAD bar collapse
The whole `SNAP / COORD / POLAR / Ruler / cursor` strip is professional-grade
precision input that an architecture student will not touch in their first
sessions, and it costs two to three permanent rows at typical window widths.
Collapse it to a single **"Precision input ▸"** toggle, expanded on demand and
remembered.

### 30. Small things
- `'Select "Node" and click canvas to start.'` is the opening status message
  but the Node tool is not actually pre-selected in the button row until
  `_refresh_tool_buttons` runs — make the starting state unmistakable
  (Node tool highlighted *and* the canvas showing a faint "click to place your
  first joint" watermark while the model is empty).
- The two examples are named `Example` and `Example: Vierendeel`. Name them for
  what they teach: *"Warren truss — how triangles carry load"* and
  *"Vierendeel girder — carrying load with no diagonals"*, and consider a small
  gallery (Pratt, Howe, Fink, cantilever, three-pin) with a one-line "what this
  shows" on each. Worked examples are the highest-leverage teaching content a
  tool like this can carry, and the infrastructure for them already exists.
- The Rod Calculations report is excellent and almost nobody will find it: it is
  a blue text button in the fourth toolbar group, named like an export. Promote
  it — "Show me the working" — and offer it directly from a selected member.

---

## What should **not** change

- The FlowBar / ScrollPanel responsive work. The comments in `_build_ui` record
  real measured failures (42 of 61 controls mapped at 1000 px). Any reflow
  proposed above must keep that property.
- The hover tooltips on nodes, rods, loads and supports. They are the best part
  of the current UI.
- The Rod Calculations and Node Force Vectors reports — content-wise these are
  already pitched exactly right for a learner. They only need to be findable.
- The adaptive 1-2-5 grid, the ghost preview, and the snapping. They make the
  tab feel like a drawing instrument, which is the right feel for this audience.
