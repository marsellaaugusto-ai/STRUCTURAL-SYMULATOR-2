# Structural Simulator module map

The project is organized by application so that each structural tool can be maintained independently while sharing the common UI/numerical layer.

```text
main.py                         application entry point
common.py                       shared constants, widgets and numerical utilities
cirsoc_301.py                   shared design-code layer (CIRSOC 301-2018)
apps/
  truss/
    truss_app.py                Truss UI/controller
    truss_math.py               Truss/Vierendeel calculations
    truss_plates.py             gusset / shear-panel design checks
    truss_reports.py            Excel/report support
  beam/
    beam_app.py                 Beam UI/controller
  arch/
    arch_app.py                 Arch UI/controller
  cable/
    cable_app.py                single-cable UI/controller
  cable_web/
    cable_web_app.py            cable-network UI/controller
    cable_web_math.py           cable-network analysis engine
  perforated_beam/
    perforated_beam_app.py      Perforated/Cellular Beam UI/controller
    perforated_beam_math.py     Vierendeel/web-post/torsion analysis engine,
                                 plus RolledSection/ChannelSection/
                                 BuiltUpDoubleChannelSection/CustomProfileSection
    profile_sketcher_math.py    CAD-sketch geometry engine (opening shapes,
                                 snapping, validation, JSON I/O) -- no Tkinter
    profile_sketcher_ui.py      CAD-sketch Tkinter Toplevel (canvas, tools,
                                 toolbar) built on common.ZoomCanvas -- draws
                                 web OPENINGS onto an existing RolledSection
    section_profile_math.py     Single-outline geometry engine (lines + 3-point
                                 arcs) for drawing a section's own outer
                                 boundary -- no Tkinter; reuses
                                 profile_sketcher_math's snap/typed-entry helpers
    section_profile_ui.py       Tkinter Toplevel for the above -- draws the
                                 CROSS-SECTION SHAPE ITSELF, not an opening
tests/                          regression and mathematical tests
REPORTS AND GUIDES/             documentation and diagnostic reports
```

## Import rules

`main.py` imports each application through its package path, for example:

```python
from apps.truss.truss_app import TrussApp
```

Application-internal modules use relative imports, for example the Truss UI imports `.truss_math` and `.truss_reports`, while shared utilities continue to come from the root-level `common.py`.

**No tab imports another tab.** Anything two tabs both need is promoted to a
root-level module instead. `cirsoc_301.py` is the second such module: it began
inside `apps/perforated_beam/` and moved to the root on 2026-09-06, when the
Truss plate feature needed the same weld, shear and stress checks. Copying it
would have been the other option, and the wrong one — two copies of a
design-code layer drift, and a stale resistance factor is not a bug you notice
by reading the output.

The root directory containing `main.py` must therefore be the working directory when launching the application directly with:

```text
python main.py
```

## Design boundary

The Truss app is deliberately split at the stable boundary between stateful Tkinter interaction (`truss_app.py`) and deterministic calculations (`truss_math.py`). The solver receives plain lists/dictionaries and has no Tkinter, Excel, or drawing dependencies. That is the intended C++ migration boundary.

`truss_reports.py` owns Excel and PIL/matplotlib report output. Keep these in Python unless a future product requirement calls for a native reporting layer.

## Perforated Beam

Same split as Truss: `perforated_beam_math.py` is a pure-Python engine
(statics, net-section geometry, Vierendeel/web-post/torsion checks) with
no Tkinter dependency, and `perforated_beam_app.py` builds a
`perforated_beam_math.BeamConfig` from widget state and renders the
returned report. Units are mm/N/MPa/N·mm -- deliberately different from
Beam's m/kN, documented in both files' docstrings and in
`REPORTS AND GUIDES/PERFORATED_BEAM_MANIFESTO.md`.

### Profile sketcher (CAD-style opening layout)

`perforated_beam_app.py`'s "Sketch profile…" button is a second, visual
entry path into the same `self.openings` list that the numeric
shape-dropdown fields already populate -- it does not replace them, and
`BeamConfig`/`analyze_beam` are unaware it exists.

The same math/UI split as the rest of the app applies one level deeper:

- `profile_sketcher_math.py` owns the sketch's own data model
  (`CircleShape` / `PolygonShape`, both in absolute "world" mm: x along
  the beam axis, y measured from the section's bottom fiber upward),
  snapping math, AutoCAD-style typed-entry parsing (`"x,y"`, `"@dx,dy"`,
  `"length<angle"`), simple/y-simple polygon validation (delegating to
  `perforated_beam_math.opening_polygon`'s own rules rather than
  duplicating them), JSON save/load, and the one function that matters
  for correctness -- `shape_to_opening_instance()` -- which converts a
  sketched shape into a real `pbm.OpeningInstance` using the *current*
  section's depth to place local y=0 at mid-depth, resolved at Apply time
  so a sketch survives a later section change. This file has no
  `tkinter` import and is unit-tested directly in
  `tests/test_profile_sketcher.py`.
- `profile_sketcher_ui.py` is the `tk.Toplevel` itself: a `ZoomCanvas`-based
  drawing surface with Select/Move, Line/Polyline, Circle, Rectangle and
  Polygon tools, grid/endpoint/midpoint/center snapping, an Ortho toggle,
  undo/redo, an Array-along-beam and Mirror-about-centerline command, and
  sketch save/load. On Apply it calls `profile_sketcher_math` to build
  `OpeningInstance` objects and hands them to a caller-supplied callback
  (`perforated_beam_app._apply_sketch_openings`), which is the only place
  `perforated_beam_app.py` and the sketcher touch.

Data flow: `PerforatedBeamApp._open_sketcher()` seeds a `ProfileSketcher`
with the beam's current length/section depth and existing `self.openings`
(so re-opening the sketcher is an edit, not a fresh start) → the user
draws → `ProfileSketcher._apply()` validates every shape and converts the
whole sketch via `profile_sketcher_math.shapes_to_openings()` → the
resulting `OpeningInstance` list replaces `self.openings` exactly as the
manual "Generate / Add" button would.

### Section types beyond RolledSection

`PerforatedBeamApp` has a "Section type" selector (catalog / custom
rolled I-beam / built-up double channel / built-up double profile / custom
drawn profile) driving `_current_section()`, which builds whichever
`perforated_beam_math` section type is currently selected. Only
`RolledSection` supports web openings — `BeamConfig.__post_init__` rejects
the other types if `openings` is non-empty, since the opening/Vierendeel/
web-post machinery is built specifically around the I/W flange-web
geometry (see `PERFORATED_BEAM_MANIFESTO.md` §4b for why that doesn't
generalize, and what does still work for the other section types: global
statics, deflection, and the combined bending+shear+torsion check).

The custom-profile path follows the same one-way data flow as the
opening sketcher, one level up: `PerforatedBeamApp._open_profile_designer()`
opens a `SectionProfileDesigner` → the user draws a closed outline with
Line/3-point-Arc tools → on Apply, `SectionOutline.to_section()` (in
`section_profile_math.py`) flattens it (arcs discretized) and wraps it as
a `perforated_beam_math.CustomProfileSection` → that becomes
`self.custom_profile_section`, used whenever Section type is "Custom
profile (drawn)". Both built-up paths (double channel, and the more
general double profile) have no drawing step of their own — they're
fully parametric (base profile(s) + gap/width) — but share
`_open_connector_designer()`, which samples `global_T(x)` across the
whole beam for the governing torque and calls
`perforated_beam_math.design_builtup_connector()` to size the welded tie
plates from that demand.

"Double profile" mode has TWO independent "pick a base profile" widgets
(Profile A / Profile B — B defaults to mirroring A's selection only in
the sense that `BuiltUpDoubleSection.base_b` defaults to `base_a`, not in
the UI itself), each built by the same reusable
`_build_base_picker(parent, prefix)` / `_read_base_picker(prefix)` pair
(prefixes `'dp_a'`/`'dp_b'`) rather than duplicated per-slot code. Each
picker lets its base be a catalog/custom I-beam, a catalog/custom
channel, or its own independently-designed custom profile (via its own
"Design profile…" button, stored as `self.{prefix}_custom_profile_section`
— separate from the single `self.custom_profile_section` the standalone
"Custom profile (drawn)" mode uses) — this is what makes "two different
custom-drawn profiles combined into one built-up section" possible.
`_read_base_picker` also applies orientation (see below) before handing
the base to `BuiltUpDoubleSection(base_a, gap, base_b)`; any combination
of `A`/`I`/`S`/`d` (and `Aweb`/`J` if BOTH bases have them) combines
correctly, since two shapes vertically aligned at the same centroidal
height always share the combined section's neutral axis regardless of
what either shape actually is (see `PERFORATED_BEAM_MANIFESTO.md` §4b).

### Orientation

`perforated_beam_math.OrientedSection(base, rotate90, mirror)` (see
`PERFORATED_BEAM_MANIFESTO.md` §4c) lets a section be installed rotated
or mirrored relative to gravity — this module has no way to infer that
from a catalog listing alone. `_build_orientation_row(parent)` adds the
Rotate 90°/Mirror checkboxes once and is reused everywhere a base profile
gets picked: the two single-section modes' own frames, and inside
`_build_base_picker` for each of Double profile's two slots.
`_apply_orientation()`/`_read_base_picker()` wrap the constructed base in
`OrientedSection` only if either checkbox is actually set, so an
unrotated section is returned exactly as before (no wrapper overhead or
behavior change) — this is why `_current_section()`'s catalog/custom-ibeam
branches now route through `_apply_orientation()` instead of returning
the bare `RolledSection` directly.

### Movable supports

`BeamConfig.supports = (xA, xB)` generalizes every reaction/statics
function away from the old hard-coded "supports at 0 and L" assumption,
enabling overhangs while staying a determinate 2-support beam (see
`PERFORATED_BEAM_MANIFESTO.md` §4d). `ProfileSketcher` exposes this in
the CAD canvas via "Place support A"/"Place support B" buttons; on Apply
it calls back with `(openings, supports)` instead of just `openings`, and
`PerforatedBeamApp._apply_sketch_openings()` updates both.
