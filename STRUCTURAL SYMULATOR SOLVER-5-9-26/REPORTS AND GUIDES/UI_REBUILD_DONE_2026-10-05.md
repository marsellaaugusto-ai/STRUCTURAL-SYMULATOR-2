# Truss / app-wide UI rebuild — what was done

Date: 2026-10-05
Plan this follows: `UI_REBUILD_PLAN_2026-10-05.md`
Findings it acts on: `UI_RECOMMENDATIONS_TRUSS_2026-10-05.md`

Tests: **1270 passing**, from a 1216 baseline. Run with
`xvfb-run -a python -m pytest tests/ -q` on a Python with tkinter.

---

## Phase 1 — the shared layout (`common.py`)

**`AppShell`** — toolbar on top, control panel on the LEFT behind a
draggable sash, drawing filling the rest, optional diagram pane under it
behind a second sash, status bar pinned at the bottom. It generalises the
two tabs that already had it right: Stereo put its sidebar on the left,
Perforated Beam made the divider draggable.

**`CollapsibleSection`** — a LabelFrame whose title bar folds the body away.
Folding keeps the section in place with its title readable, which is what
separates it from a control lost off the panel edge.

**`ZoomCanvas.fit_to_bbox`** — zoom and centre on a world rectangle.

**`AppShell.auto_fit_panel`** — the panel asks for what its content needs,
yields to a third of the window when the window cannot afford that, and
stops doing either the moment the user drags the sash. Added after the
tests caught a real regression: with the panel refusing to give ground, the
Arch tab mapped 45 controls at 1600 px and 40 at 900 px.

## Phase 2 — the Truss tab

| Before | After |
|---|---|
| Panel on the right, fixed 235 px | Panel on the LEFT, draggable, 340 px default |
| Analyze 13th block down, ~900 px into a shorter column | Analyze at the top of the panel AND in the toolbar |
| Nine LabelFrames always open | Four advanced ones ship folded |
| CAD bar: 2–3 permanent rows | Folds behind "Precision input" |
| Diagram band fixed 260 px | Its own pane with a draggable sash |
| ~15 controls in the bar, 3 rows at 1280 px | Five groups, menus, one row |

Toolbar order, from the Stereo tab: **TOOLS · EDIT · VIEW · ANALYZE · OUT**.
Twelve buttons became the `Examples ▾`, `View ▾`, `Report ▾` and `Excel ▾`
menus. Undo and Redo finally have buttons.

## Phase 3 — Tier 1

- **Member forces (N) diagram.** A pin-jointed bar carries no shear and no
  moment, so the only non-Vierendeel diagram mode drew two empty boxes per
  member for every classic truss — a beginner's first Analyze produced a
  blank. One bar per member, length ∝ |N|, red tension, blue compression.
  The pane opens on the diagram the model actually has.
- **Units.** ~15 hardcoded `kN` strings now go through the unit layer, so
  the drawing, the tooltips, the free-body diagrams and the typeset
  equations follow the selected design code. A test switches to AISC and
  scans every canvas text item for `kN`.
- Reactions are no longer green (`CD` and `CR` were two greens four rows
  apart in the same legend). Now `#6A1B9A`.
- `Ctrl+X` no longer means Redo; redo is `Ctrl+Y` / `Ctrl+Shift+Z`.
- A **Pan tool** and space-drag — `ZoomCanvas` panned only on the middle
  button, which most trackpads do not have.
- **Fit** — `reset_view` goes to the origin, which stops being the model as
  soon as you build away from it.
- A model can be **saved before it is analysed**. `export_excel` always
  handled `results=None`; only the UI guard refused.
- Support types are **named for what they do**. Stored keys unchanged.
- The diagram caption follows the mode.

## Phase 5 — Tier 2

- **"Why won't it analyse" is the lesson.** Four modals gone. The panel
  explains in plain language that the structure can move without any member
  changing length, names the loose joint or the unbraced bay, and the
  drawing rings it in orange. Both fixes it offers — a diagonal, or Set
  Rigid — are asserted by tests to actually clear the diagnosis, and a
  triangle is asserted never to be reported as a mechanism.
- **Zero-force members** are dashed, labelled 0 and counted, instead of
  sharing the grey of "not solved yet".
- **Animate** sways the deflected shape; **live mode** re-solves on every
  edit without popping modals or the diagram pane.
- **Forces written on each member**, so a screenshot of the canvas stands
  on its own.
- **A guide, and F1** — organised by question, not by control, because a
  student who does not know what a mechanism is cannot look up the control
  they need. Includes the sign conventions that were scattered through the
  panel in 7-point grey.
- **A five-step checklist** across the top of the panel that ticks itself.

## Phase 4 — the other tabs

| Tab | Before | Now |
|---|---|---|
| Truss | panel right, 235 px, fixed | shell, left, draggable |
| Beam, Arch, Cable | panel right, 340 px, fixed | shell, left, draggable |
| Cable Web | two fixed sidebars, breakpoint table | two panes, both dragged |
| Perforated Beam | left panel, draggable sash | unchanged — it was already right |
| Stereo | left sidebar, fixed 360 px | **unchanged, deliberately** |

---

## Not done, and why

- **Stereo has no sash yet.** Its panel is already on the left, so it is
  only the draggable width that is missing. Left alone because of the
  unanswered question below: rewriting its `_build_ui` would make that
  merge worse for no gain.
- **Load-path visualisation** (Tier 2, item 20 of the recommendations) —
  animated chevrons tracing a load to the supports. The largest remaining
  teaching feature and the one most worth doing next.
- **Tier 3** (material presets by name, support symbols as buttons, the
  global text-size control, letters for joints) was not in scope for this
  pass.

## Open questions for the owner

1. **Stereo "v32".** There is no v32 in this repository — `apps/stereo/` is
   the single version from commit `c1677bf`, 714 lines, no version marker.
   Everything modelled on "the Stereo UI" used that file.
2. **The unit selector names design codes, but only CIRSOC 301 is
   implemented.** `cirsoc_301.py` supplies the φ factors for every plate
   check whichever entry is chosen, so picking "AISC 360" changes kN to kip
   and nothing else. Either rename the entries to unit conventions, or keep
   the code names and state under the selector which code the checks come
   from. The second was recommended and is **not yet applied** — it needs
   the owner's choice.
