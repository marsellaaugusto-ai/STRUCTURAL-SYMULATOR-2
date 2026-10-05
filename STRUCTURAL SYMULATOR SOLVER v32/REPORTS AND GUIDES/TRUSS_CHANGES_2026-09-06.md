# Truss tab — fixes for DIAGNOSIS_TRUSS_2026-09-05, applied 2026-09-06

All four findings addressed. Suite **461 → 476 passed**, no regressions.
Nothing in the solver's numerical behaviour was changed: the diagnosis found
no correctness bug, and none was introduced.

---

## T-1 · Panel controls overflowed, then vanished — FIXED

### What was actually wrong

The diagnosis called this a fixed-width panel with no `<Configure>` handling.
Measuring the real widgets found three separate causes, and the failure was
worse than reported.

**Cause 1 — pack order.** `_build_ui` packed the expanding `ZoomCanvas`
*before* the right-hand panel. Tk's pack hands each slave a parcel in packing
order, so the panel received whatever the canvas did not want — below ~850 px,
nothing. The panel was not clipped or scrolled off; it was **unmapped
entirely**, Analyze button included, with no scrollbar and no error.
Cable Web's `_build_ui` already carried a comment about hitting this exact
trap; the Truss tab had not been given the same treatment.

**Cause 2 — the interior was pinned to the panel width.**
`panel_canvas.create_window(..., width=PANEL_W)` forced the scrolled frame to
exactly 235 px, so any row wider than that was cut off mid-widget with no way
to reach it. This was happening **even at 1600 px**, where the diagnosis
recorded "0 overflowing" — see the note on that metric below.

**Cause 3 — three single-row bars.** The toolbar, the CAD precision bar and
the diagram header each packed everything into one row with no wrapping. The
toolbar's last two buttons (*Node Force Vectors*, *Rod Calculations*) were
already unreachable at 1600 px.

### A note on the metric

The diagnosis's table reads "800 px: 17 mapped, **0 overflowing**", and flags
in prose that this is the panel disappearing rather than a fix. It is worth
stating as a rule: **an unmapped widget cannot overflow**, so an
overflow-only metric improves monotonically as the UI gets worse, and reaches
its best score when everything is gone. `tests/test_truss_layout.py` therefore
asserts on the *mapped count* as well, and its docstring says why. The same
reasoning is why every change below was checked against a screenshot and not
only against `winfo_ismapped()` (MANIFESTO §2).

### What was done

Two reusable classes were added to `common.py`, so the next tab to need this
gets it rather than growing a fourth private copy:

* **`FlowBar`** — wraps a bar of control *groups* onto as many rows as the
  width needs. Ported from Cable Web's `_relayout_toolbar` with all three of
  its hard-won lessons intact: no caching of the layout decision (§3c),
  per-row Frames instead of a shared-column grid (§3d), and `.lower()` on
  every `pack(in_=...)` anchor frame (§3e).
* **`ScrollPanel`** — a side panel that scrolls in **both** axes and sizes
  itself to its own content via `fit_to_content()`, so a later change that
  adds a wider row widens the panel instead of pushing that row behind a
  scrollbar.

In `truss_app.py`: the panel is now a `ScrollPanel` packed **before** the
canvas; the toolbar, CAD bar and diagram header are all `FlowBar`s; and four
panel rows that were individually wider than the panel were reflowed (the UDL
rotation slider and its legend, the load-direction radios, the point-load
`P` / `% from A` pair, and the point-load angle hint). Four help labels
carried *both* hard `\n` breaks and a `wraplength`, which re-wrapped
mid-phrase — the hard breaks were removed and the wraplength corrected from
`PANEL_W-30` to `PANEL_W-55`, which was ignoring the LabelFrame's own padding
and the scrollbar.

`ScrollPanel`'s horizontal scrollbar is `grid`ed, not `pack`ed. Packed lazily
next to an `expand=True` canvas it was allocated zero height and never
appeared, while reporting itself shown with a correct scrollregion — the same
packing-order trap this class exists to prevent, one level down.

`apply_responsive_width` deliberately does **not** use a breakpoint table.
Cable Web's `_update_responsive_sidebars` shrinks by a fixed percentage per
step, which on this panel pushed Analyze 12–20 px past the edge at 700 px.
The rule here is: never narrower than the content needs, never more than 45 %
of the window.

### Measured result

61 interactive controls, example model loaded, analysed, with both context
editors open:

| width | mapped before | mapped after | overflowing before | after |
|---|---|---|---|---|
| 1600 px | 49 | **61** | 0 (12 unmapped) | **0** |
| 1200 px | 46 | **61** | 0 (15 unmapped) | **0** |
| 1000 px | 42 | **61** | 18, worst +102 px | **0** |
| 900 px | 41 | **61** | 22, worst +202 px | **0** |
| 800 px | **17** | **61** | 0 — *panel gone* | **0** |
| 700 px | 14 | **61** | 0 — *panel gone* | **0** |
| 600 px | 14 | **61** | 0 — *panel gone* | **0** |

Screenshots taken at each width and inspected. Pinned by
`tests/test_truss_layout.py`, which was confirmed to fail when the original
pack order is restored.

**Not done:** Beam, Arch and Cable share this layout idiom and fail the same
way. The diagnosis recommends fixing all four together. `FlowBar` and
`ScrollPanel` make each of them a small change, but they were left alone here
to keep this change reviewable against the Truss diagnosis it answers.

---

## T-2 · `_draw_diagrams_legacy_overview` — DELETED

172 lines removed. Confirmed by `grep` that the only occurrence of the name in
the tree was its own `def`, both before and after. The live renderer,
`_draw_diagrams_only`, is now the only one.

While there: the section banner immediately below it read `Excel export` but
sat above the on-screen *report* windows, with the real `_export_excel` some
470 lines further down. Corrected, and it now records where the deleted method
went and why.

---

## T-3 · Dead imports and locals — REMOVED

`truss_app.py`: `sys`, `subprocess`, `_nice_ticks`, `_find_diagram_maxima`,
`make_shape_fn`, `compute_node_force_vectors`, `udl_local_components`,
`compute_node_moments`, `pil_draw_node_fbd`, `pil_draw_rod_context`, and the
unused local `panel_win`. `truss_reports.py`: `os`, `sys`, `subprocess`, seven
unused names from `common`, and the unused `import openpyxl` at `:130` (the
`from openpyxl import ...` lines below it are what the function uses). The
`os` redefinition the diagnosis flagged as possibly a merge artefact turned
out to be benign — a local `import matplotlib, os` inside `_get_ttf_font`,
which is now the only `os` in the file.

All three truss files are pyflakes-clean.

One import line was **kept deliberately** and now says so: `analyze` and
`compute_diagrams` are imported *from* `truss_app` by
`tests/test_truss_load_signs.py`, making that line a public re-export surface
rather than a local convenience.

---

## T-4 · Tests — ADDED (and one that never ran)

**`tests/test_truss_load_signs.py` was never executed by the suite.** It
defines only `main()`, and pytest collects by the `test_` prefix, so
`pytest -q` collected *zero* tests from it — for as long as it has existed.
The Truss tab's "one existing test" was in practice none. A `test_load_signs()`
wrapper now makes the suite see it; the script form still works.

**`tests/test_truss_math.py`** — 11 tests, the §0 closed-form table made
runnable: the triangle truss against `R = P/2`, `−(P/2)/sinθ`, `(P/2)/tanθ`;
global ΣFx/ΣFy/ΣM for the triangle and the Warren example; Warren's symmetric
reactions; the **method-of-joints residual at every free node** (which needs
no reference values at all, so it applies to any truss a future change might
break); that an all-pin model gains no rotational DOF anywhere; the rigid
element's cantilever against the independently-written `BeamModel`; and the
UDL split.

Every one was **mutation-tested**. The first pass caught 4 of 5 injected
faults but *survived* flipping the sign of the rigid element's reported axial
force — nothing loaded a rigid rod along its own axis, and the V/M/reaction
checks are blind to it. `test_rigid_rod_reports_axial_force_with_the_same_sign_as_a_pin_rod`
closes that gap; all five mutations now fail the suite.

**`tests/test_truss_layout.py`** — 3 tests pinning T-1: no control unmapped or
overflowing at any width from 1600 to 600 px; the toolbar demonstrably wraps
to more rows as the window narrows; and the panel's content stays reachable,
with the horizontal scrollbar required to have real size rather than merely
report itself shown.

---

## Verification performed

1. `pytest -q` — **476 passed** (was 461), 0 failed.
2. Width sweep 1600 → 600 px on the real widgets, before and after.
3. **Screenshots at each width, inspected** — geometry queries alone cannot
   see a widget painted over by a sibling (MANIFESTO §2, §3e).
4. All six tabs launched together via `main.App` and visited at 1600 px and
   800 px; no exception from any relayout.
5. `pyflakes` clean on all three truss files.
6. Mutation tests on the new solver tests (§T-4).
7. The layout test confirmed to **fail** when the original pack order is
   restored — a regression test that cannot fail is not a regression test.

## Follow-ups deliberately not done

* Beam / Arch / Cable share the T-1 layout idiom (see T-1).
* Cable Web still holds its own copy of the wrap logic now shared in
  `common.FlowBar`; a NOTE at `_relayout_toolbar` records this and how to
  migrate. Left alone to keep a Truss layout fix out of the most
  regression-prone tab (MANIFESTO §3j is the reason it should not stay that
  way for long).
* `common._beam_gauss_solve` rejects valid, well-conditioned models above
  ~600 DOF as "singular" — an absolute residual gate that ignores `‖K‖`.
  Measured and written up in `DIAGNOSIS_PLATE_FEATURE_2026-09-06.md` §3.2.
  Shared by all six tabs, so it wants its own change and its own verification
  pass.
