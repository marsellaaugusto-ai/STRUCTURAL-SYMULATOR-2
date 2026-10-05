# Fase 3 — Beam overhaul

**Opened** 2026-10-05 · **Branch** `claude/beam-overhaul-2026-10-05`
**Branched from** `a5924fe` — "Window title: Structural Simulator, version,
date, and the drawing in front (v32)", the tip of
`claude/stereo-structure-calculator-lqgosu`.

A tracking folder, opened before the work. Scope is not set yet, so nothing
below is a plan — it is where the phase starts from, written down while it
is still accurate.

## Why this branch starts where it does

It starts at the shipped v32 state, **not** at the grouping work on
`claude/nice-feynman-cof87g`. The two are meant to run side by side: the
grouping branch is rebuilding how the Stereo tab nests and shares its
objects, and this one is about the beam. Stacking this on top of that would
put every grouping commit into whatever pull request this phase opens, and
would tie the two to being reviewed and merged together.

If the beam work turns out to need the scene graph (it would, if beams were
ever to become objects in the same hierarchy), say so and this branch can be
rebased onto the grouping one — later and deliberately, rather than by
accident on day one.

## What is here today

The Beam tab is one module:

    apps/beam/beam_app.py              the tab itself

The Perforated Beam tab is a separate, much larger tab, and NOT the same
thing — worth saying out loud, because "beam overhaul" could mean either:

    apps/perforated_beam/perforated_beam_app.py
    apps/perforated_beam/perforated_beam_math.py
    apps/perforated_beam/hyperstatic_math.py
    apps/perforated_beam/opening_reinforcement.py
    apps/perforated_beam/general_net_section.py
    apps/perforated_beam/welded_section_math.py
    apps/perforated_beam/load_combinations.py
    apps/perforated_beam/assembly_check.py
    ... and its own README.md

Its tests:

    tests/test_beam_math.py
    tests/test_perforated_beam_math.py
    tests/test_perforated_beam_app_features.py
    tests/test_perforated_beam_views.py
    tests/test_perforated_beam_excel.py
    tests/test_hyperstatic_math.py
    tests/test_opening_reinforcement.py
    tests/test_general_net_section.py
    tests/test_load_combinations.py
    tests/test_assembly_check.py
    tests/test_assembly_detail.py
    tests/test_units_in_beam_tab.py

## Which beam?

Unanswered, and the first thing to settle, because the two tabs share almost
nothing:

- **Beam** is a single module and a simple tab.
- **Perforated Beam** is a dozen modules with its own section designer,
  profile sketcher, opening reinforcement, hyperstatic analysis and Excel
  round trip.

## Running the app and its tests here

This repository's own check, which says whether an interpreter can run it:

    python3 tools/doctor.py

In a headless container the app still runs under a virtual display:

    Xvfb :99 -screen 0 1600x1000x24 &
    DISPLAY=:99 python3 main.py

The GUI tests need that display too. They can be run in parallel, but
**keyboard tests are not reliable under parallel workers**: `event_generate`
depends on window focus, and workers sharing one X display take it from each
other. Measured on 2026-10-05, `tests/test_stereo_app.py` under `-n 4`
reported one or two failures that all passed one worker at a time, and the
set of failures changed between runs. Parallel for speed; serial before
believing a failure.

## Log

| date | what |
|---|---|
| 2026-10-05 | Folder opened. No scope set, no code changed. |
