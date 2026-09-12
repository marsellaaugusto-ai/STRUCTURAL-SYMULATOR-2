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
  cross-section's own outer boundary (not an opening) with Line and
  3-point-Arc tools, opened via "Design profile…" when Section type is
  set to "Custom profile (drawn)". Produces a
  `perforated_beam_math.CustomProfileSection`, whose properties are
  computed numerically from the drawn outline rather than a closed-form
  shape formula -- see `tests/test_section_profile.py`.
- `ChannelSection` / `BuiltUpDoubleChannelSection` (in
  `perforated_beam_math.py`, no dedicated UI file needed -- it's fully
  parametric) -- models two channels tied together across a central gap
  by welded plates, and `design_builtup_connector()` sizes those plates
  from the beam's actual torque demand. See the manifesto §4b for exactly
  what this check does and doesn't cover.
