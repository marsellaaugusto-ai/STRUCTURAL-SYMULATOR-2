# Arch tab — bugs still open, 2026-09-10

**File:** `apps/arch/arch_app.py` (1 748 lines)
**Re-diagnosis of** `DIAGNOSIS_ARCH_2026-09-05.md`. Suite green: 809 passed.

| finding | severity | status |
|---|---|---|
| A-1 layout | MED | ✅ fixed (3 px residual, §A-1) |
| A-2 `ArchModel(n_elem=0)` → ZeroDivisionError | LOW | ❌ open (not user-reachable) |
| A-3 dead locals / imports | LOW | ❌ open |
| A-4 no physics tests | LOW | ❌ open |
| A-5 diagram captions collide; FIBRE STRESS header illegible | MED | ❌ **new** |
| A-6 point load outside the span silently snapped to a support | MED | ❌ **new** |
| A-7 distributed load wholly outside the span silently ignored | LOW | ❌ **new** |

**The solver is still the most accurate in the project** — re-validated today:
three-hinged H = wL²/8f (2.5e-14), crown point load H = PL/4f (1.6e-12),
funicular max|M| ≈ 0 (2.6e-14), M = 0 at the crown hinge (1.0e-13), wind and
horizontal-load equilibrium (1.1e-12), fixed-support equilibrium (7.3e-15).
All three shape presets (Parabolic, Circular, Catenary-like) now verified to
analyse end-to-end through the UI. Excel round-trip clean.

---

## A-1 · FIXED (with a 3 px residual not worth chasing)

41 controls mapped at 1600 px, 39 at 900 px, 35 at 550 px — against 41 → 22 → 8
in September, when ▶ Analyze was unreachable from 900 px down. The 6 lost at
550 px go **vertically** (the diagram-scale rows wrap until the stack outgrows
the column), which `test_tab_layouts.py` documents honestly rather than
asserting a threshold.

The only edge overflow left is one `Entry` exceeding the window by **3 px at
550 px**. Not worth a change.

---

## A-5 · MEDIUM · NEW · The diagram pane's captions pile up on each other

The Arch diagram pane is four sub-plots in a narrow column, and its captions
are long. They collide **at every window size tested**, not only narrow ones.
Overlapping text bounding boxes in `diag_canvas`:

| window | canvas width | collisions |
|---|---|---|
| 1500 px | 530 px | **7** |
| 1000 px | 194 px | 22 |
| 800 px | 222 px | 20 |
| 700 px | 191 px | 23 |

Confirmed against a 1500 px screenshot — this is genuinely visible, not a
bounding-box artefact:

* *"AXIAL FORCE N (kN) — red = tension, blue = compression"* runs straight
  through *"max ±167.89"* (51 px of overlap).
* *"THRUST Fx/Fy (kN, global components)"* runs through *"max ±129.24"*.
* The **FIBRE STRESS** panel header is an unreadable pile-up: the caption, the
  `max ±6.16` readout and the hover/probe annotations are all drawn on top of
  one another, rendering as a scramble of overlapping glyphs.
* The pane's top caption is clipped at both ends, so it begins mid-word —
  *"): axial N · thrust Fx/Fy · bending M · fibre stress (run ▸ Analyze; hover
  over any arch outline for"*.

The plots themselves are drawn correctly; this is purely the labelling.

**Fix:** measure captions with `font.measure()` against the available width and
elide the explanatory half when they do not fit (keep *"AXIAL FORCE N (kN)"*,
drop *"— red = tension, blue = compression"* into a legend or tooltip); put the
`max ±…` readout on its own line, right-aligned, rather than on the caption's
line; and give the pane's top caption a wrap or an ellipsis instead of a clip.
Beam (**B-8**) and Cable (**C-6**) have milder versions of the same idiom — one
change can cover all three. **Effort ~2 h. Risk low — drawing only.**

**Verify:** re-run the text-collision count; expect 0 at 1500 px and no
caption overlapping a `max ±…` readout at any width. Take a screenshot — a
collision count alone cannot tell you the fibre-stress header became legible.

---

## A-6 · MEDIUM · NEW · A point load outside the span is silently snapped to a support

Nothing validates a point load's x against the span. A load placed outside is
accepted and quietly relocated onto the nearest node — which, for anything
beyond the span, is a **support**, where it bypasses the structure entirely:

```
span = 20 m, 50 kN point load
   x = 10.0   ->  Ray = 25 000   Rby = 25 000     (correct: mid-span)
   x = 19.9   ->  Ray =      0   Rby = 50 000     snapped to the support
   x = 25.0   ->  Ray =      0   Rby = 50 000     outside the span, accepted
   x = 999.0  ->  Ray =      0   Rby = 50 000     far outside, accepted
```

Global equilibrium still holds (ΣFy = 50 000 in every row), so nothing looks
wrong — the load has simply been moved somewhere the user did not put it, and
the arch carries none of it.

Two distinct problems are visible here:

1. **x outside `[0, span]` is not rejected.** Same class as the Beam tab's
   still-open B-5, and worth fixing in one pass with it.
2. **Nodal snapping near a support is silent.** `x = 19.9` on a 20 m span with
   `n_elem = 60` (node spacing 0.333 m) snaps to the springing. The snap itself
   is inherent to the discretisation and fine, but a load landing *on* a
   support carries nothing, and the user is not told.

**Fix:** reject `x < 0` or `x > span` in the point-load dialog and in
`ArchModel.solve()`. For (2), warn in the status bar when a load snaps onto
either springing — or, better, report the snapped position in the results so
the model being solved is visible. **Effort ~1 h.**

---

## A-7 · LOW · NEW · A distributed load wholly outside the span contributes nothing, silently

```
dist load x1=0,  x2=20  (span 20)  ->  ΣFy = 200 000   (= wL ✔)
dist load x1=20, x2=0   (reversed) ->  ΣFy = 200 000   (normalised ✔ — good)
dist load x1=30, x2=50  (outside)  ->  ΣFy =       0   silently ignored
```

Reversed input is handled correctly here — better than the Beam tab, which
still drops it (B-4). But a load whose domain misses the span entirely just
vanishes with no warning.

**Fix:** warn when a distributed load's `[x1, x2]` does not intersect
`[0, span]`, and clamp when it only partly overlaps. Cable has the same hole
(**C-5**). **Effort ~30 min, together with A-6.**

---

## A-2 · LOW · `ArchModel(n_elem=0)` still raises a bare ZeroDivisionError

`ArchModel.nodes()` divides by `self.n_elem`. **Still not reachable from the
UI** — `arch_app.py:1196` clamps with `max(4, int(self.nelem_var.get()))`, and
the Excel import path funnels through the same clamp. Recorded so nobody
"fixes" it in the UI layer, where the guard already exists.

**Fix (optional):** validate in `ArchModel.__init__` so the model layer is safe
when driven directly from a test or script, in the style of `CableModel`'s
"Cable length must exceed the span". **Effort ~10 min.**

## A-3 · LOW · Dead locals and imports

Unchanged: `os`, `sys`, `subprocess` and three `common` names (6 unused
imports); `L` and `rise` assigned and unused in `_apply_shape_preset`
(`arch_app.py:943-944`).

Re-confirmed harmless: the preset strings carry `L` and `rise` as *symbols*,
resolved later by `make_shape_fn` against a context built elsewhere. All three
presets were driven end-to-end today and analyse correctly, so these are
leftovers, not a missing substitution.

## A-4 · LOW · Still no physics tests for this tab

1 748 lines. Arch appears only in `test_excel_roundtrip.py` and
`test_tab_layouts.py`; nothing asserts an arch closed form.

This is the tab whose solver most deserves a regression net, because its
accuracy is currently its best feature and nothing in 809 tests would notice if
that changed. The table in `DIAGNOSIS_ARCH_2026-09-05.md` §0 ports directly
into `tests/test_arch_math.py`; the funicular check (max|M| ≈ 0) and the hinge
check (M = 0 at the crown) are especially good because they need no reference
values at all. **~1 h.**
