This module's MANIFESTO.md is not in this folder.

Read `REPORTS AND GUIDES/PERFORATED_BEAM_MANIFESTO.md` at the project root
instead -- that's where every other module's manifesto/diagnostic history
actually lives in this project (see `MODULAR_ARCHITECTURE.md`), so the
perforated-beam manifesto follows that same real convention rather than
living here.

## Files in this folder

- `perforated_beam_math.py` -- the pure-Python analysis engine (statics,
  net-section, Vierendeel, web-post, combined bending+torsion). No
  Tkinter dependency.
- `perforated_beam_app.py` -- the Tkinter tab: builds a `BeamConfig` from
  widget state, calls the engine, renders the report.
- `profile_sketcher_math.py` / `profile_sketcher_ui.py` -- an optional,
  CAD-style way to build the opening layout by drawing lines, circles,
  rectangles and polygons instead of typing shape parameters, opened via
  the "Sketch profile…" button in the Web openings panel. Produces the
  exact same `OpeningInstance` list the manual dropdown fields do --
  see `REPORTS AND GUIDES/MODULAR_ARCHITECTURE.md` for the full data-flow
  description, and `tests/test_profile_sketcher.py` for the geometry
  engine's correctness tests.
- `section_profile_math.py` / `section_profile_ui.py` -- draws the
  cross-section's own outer boundary (not an opening) with Line, Arc,
  Centre-Arc and three Circle tools, opened via "Design profile…" when
  Section type is set to "Custom profile (drawn)". Produces a
  `perforated_beam_math.CustomProfileSection`, whose properties are
  computed numerically from the drawn outline rather than a closed-form
  shape formula -- see `tests/test_section_profile.py`.

  A Select tool picks the outline, a hole or a weld for mirroring,
  moving or deleting; mirroring works on the SKETCH so arcs stay arcs and
  circles stay circles (manifesto §4k, `tests/test_sketch_transforms.py`
  for the geometry and `tests/test_section_designer_editing.py` for the
  wiring). The window also carries a web-openings panel that previews one
  opening ON the section at mid-depth -- note that a HOLE and a WEB
  OPENING are different things, §4l -- and a readout of what a selected
  weld actually holds, §4m.
- `perforated_beam_excel.py` -- the whole-model Excel round-trip behind
  the tab's "Export Excel" / "Import Excel" buttons: a `Model` sheet of
  `[BRACKETED]` blocks found by name, with columns found by header, plus
  a `Results` sheet written only when there is a matching report. Pure
  and headless -- it converts a plain state dict, and the app supplies
  that dict from its widgets -- so the entire format is tested without a
  display in `tests/test_perforated_beam_excel.py`. See manifesto §4j for
  why openings are stored parametrically and why a drawn profile travels
  as its sketch.
- `section_plastic.py` -- plastic modulus (Zx) and web/flange geometry
  for any section that can report its polygons, which is what lets the
  Chapter F/G member check run on a channel, a drawn profile or a welded
  box instead of returning None. The plastic neutral axis is the
  EQUAL-AREA axis, found by bisection; the generic result is cross-checked
  against `RolledSection`'s closed-form `Zpl` for every catalog section
  (`tests/test_section_plastic.py`). See manifesto S4n, and S4o/S4p for
  the stiffener spacing and the opening reduction to J that go with it.
- `opening_reinforcement.py` -- doubler rings around the openings that
  fail: which ones need one, how thick, rounded to stock plate, and the
  perimeter weld that holds it on. Sizes by bisection over the REAL
  reinforced section rather than a second set of Vierendeel formulas --
  `analyze_opening(..., section=...)` is the hook that makes that
  possible. See manifesto S4r; tests in
  `tests/test_opening_reinforcement.py`.
- `load_combinations.py` -- LRFD and ASD combinations. Each load carries
  a case (D or L, defaulting to L because 1.6 > 1.2, so silence
  over-factors rather than under-factors), and `apply` returns a FACTORED
  COPY so pressing Analyze twice cannot compound the factors. ASD scales
  the utilisation by phi*Omega instead of re-deriving every capacity.
  See manifesto S4s; tests in `tests/test_load_combinations.py`.
- `vierendeel_hand.py` -- the closed-form Vierendeel check most written
  calculations use, alongside the tab's nine-station scan. It runs about
  4x higher on a circular opening, for reasons the report now explains
  rather than leaving two documents to disagree. Reproduces the reference
  report to within 0.8%. See manifesto S4s; tests in
  `tests/test_vierendeel_hand.py`.
- `assembly_check.py` -- does the compound section hold together? Measures
  the clear gap between parts (a real model had two channels 1.94 mm
  apart, reported as one composite section), measures the plate
  thicknesses at each weld so Table J.2.4 can be applied without them
  being typed, and explains why a symmetric seam carries no shear flow.
  `contact_runs`/`seam_welds` find the line the two profiles actually
  touch along, which is what the "Weld the seam" button puts welds on.
  See manifesto S4t; tests in `tests/test_assembly_check.py`.
- `ChannelSection` / `BuiltUpDoubleChannelSection` (in
  `perforated_beam_math.py`, no dedicated UI file needed -- it's fully
  parametric) -- models two channels tied together across a central gap
  by welded plates, and `design_builtup_connector()` sizes those plates
  from the beam's actual torque demand. See the manifesto §4b for exactly
  what this check does and doesn't cover.
