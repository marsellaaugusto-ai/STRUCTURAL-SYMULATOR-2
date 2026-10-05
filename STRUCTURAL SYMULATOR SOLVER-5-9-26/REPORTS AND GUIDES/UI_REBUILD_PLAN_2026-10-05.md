# Truss tab — UI rebuild plan (approved scope pending)

Date: 2026-10-05
Visual version of this plan (wireframes, interactive mock of the collapsing
panel): https://claude.ai/artifact/UjMgXApsLRS5b888PjBfJY

Follows `UI_RECOMMENDATIONS_TRUSS_2026-10-05.md`. That document listed what is
wrong; this one is the sequence for fixing the layout half of it, under four
directions from the project owner:

1. the tabs must be **self-similar in what matters**;
2. the control panel goes on the **left**;
3. its width must be **draggable**, not fixed;
4. the **buttons must be better arranged**, modelled on the Stereo tab.

**Nothing has been edited. This is the plan only.**

---

## Findings that set the direction

### The suite is already inconsistent, four ways

| Tab | Panel side | Width | Resizable |
|---|---|---|---|
| Truss | right | `PANEL_W` = 235 px | no |
| Beam, Arch, Cable | right | `PANEL_W + 105` = 340 px | no |
| Cable Web | **both** left and right | fixed | no |
| Stereo | **left** | 360 px | no |
| Perforated Beam | left | default from content | **yes — `tk.PanedWindow`, sashwidth 7** |

Two observations decide the design:

- `apps/stereo/stereo_app.py:149` packs its sidebar `side='left'` under the
  comment *"matching the rest of the app's left-panel convention"*. That
  convention is asserted in exactly one tab. The owner's instruction makes it
  real.
- `apps/perforated_beam/perforated_beam_app.py:348` already uses a
  `tk.PanedWindow` with a draggable sash, and its comment explains why: a fixed
  width *"cannot be right for everyone — the tab is used at 1280 and at 2560 —
  so the width became the user's to set"*. That is the answer for every tab.

Neither piece has to be invented. Both have to be moved into shared code.

### Truss carries the most content in the narrowest panel
235 px against its siblings' 340, for strictly more controls. The three
clipping fixes recorded in `_build_panel`'s comments are all downstream of that
one number. A draggable sash retires the class of bug.

### The toolbar
Stereo: 4 groups / ~11 controls / one row — *what to build · edit · how to look
at it · get it out*. Truss: the same `FlowBar`, ~15 controls in the main bar
plus a permanent second CAD bar, wrapping to three rows at 1280 px, and
**Analyze is in neither** — it is the 13th block down the side panel.

### Units are already code-indexed; the canvas ignores them
`units.py` is organised by design code (CIRSOC / Eurocode / NBR / CSA / AISC),
and the conversion layer is sound. But ~15 sites print the literal string
`kN`, so with AISC selected the panel reads kip and the canvas reads kN in the
same window. Separately: only `cirsoc_301.py` is implemented, so every entry in
that selector produces CIRSOC φ factors. **Open question for the owner** —
rename the entries to unit conventions, or keep the code names and state under
the selector which code the checks come from. Recommendation: the second.

---

## Phases

Each phase ends with the app running and the live-widget layout tests
(`tests/test_truss_layout.py`, `tests/test_tab_layouts.py`, `tests/tools/appdiag.py`)
passing. Work can stop after any phase.

### Phase 1 — shared layout, no visible change
Add to `common.py`, beside `FlowBar` / `ScrollPanel` / `ZoomCanvas`:
- **`AppShell`** — toolbar on top; left panel inside a `PanedWindow` with a
  draggable sash; drawing filling the rest; optional diagram pane with its own
  sash; status bar at the bottom. Sash position remembered per tab.
- **`CollapsibleSection`** — a `LabelFrame` whose title folds the body
  (`pack_forget` / re-pack), open state remembered per section.

No tab changes. Existing tests must pass unchanged.

### Phase 2 — Truss adopts the shell
- Panel right → **left**, resizable, default 340 px.
- **Analyze + the three headline results pinned to the top** of the panel, and
  Analyze added to the toolbar.
- Construction geometry, Arrays, Plates, Rod family → collapsible, closed on
  first run.
- Toolbar regrouped to **TOOLS · EDIT · VIEW · ANALYZE · OUT**:
  `Examples ▾` (both examples + new cases), `View ▾` (the three display
  checkboxes + deformation scale), `Report ▾` (Node Force Vectors + Rod
  Calculations), real Undo/Redo buttons. Twelve buttons become four controls.
- CAD bar folds behind `Precision input ▸`.
- Diagram pane gets its own sash.

Extend `test_truss_layout.py` so a collapsed section counts as *available*, not
as a lost control — the existing test asserts on the **mapped** count precisely
because an unmapped widget cannot overflow, and collapsing must not be able to
sneak past it.

### Phase 3 — units, colours, keys
- All hardcoded `kN` through `self.fmt()`.
- The selector-wording decision above.
- Reaction colour off the deformed-shape green (`CR #2ecc71` vs `CD #1D9E75`).
- `Ctrl+Y` / `Ctrl+Shift+Z` redo; `Ctrl+X` stops meaning redo.
- Pan tool + Fit button (trackpads cannot middle-drag; `reset_view` cannot find
  a model arrayed away from the origin).
- Allow saving an un-analysed model.

### Phase 4 — roll the shell out
Beam, Arch, Cable, Cable Web, Perforated Beam, Stereo — one commit per tab,
simplest first. Perforated Beam and Stereo are nearest already.

### Phase 5 — teaching features
Tier 2 of the recommendations report (axial-force diagram first, then the
deflection animation, the mechanism diagnosis, the guide). Deferred until the
shell is accepted, since all of them live inside it.

---

## Blocking question

The owner asked for **"the stereo app v32 UI"** as the model. There is no v32 in
this repository: `apps/stereo/` is the single version added in commit
`c1677bf`, 714 lines, carrying no version marker. The plan above is modelled on
that file. If v32 is a newer local build it must be supplied before Phase 1
starts.
