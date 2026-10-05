# STRUCTURAL SYMULATOR SOLVER-5-9-26

Python/Tkinter desktop structural simulator organized by application module.

## Main entry point

From the directory containing `main.py`:

```text
python main.py
```

Tabs, in notebook order:
- Truss
- Beam
- Arch
- Cable
- Cable Web
- Perforated Beam
- Stereo — 3D space structures (the largest module; see the account below)
- Shell (RC) — reinforced-concrete shells

## Start here

This folder holds around sixty reports accumulated over the project. Two of
them are the current ones:

| Read | For |
|---|---|
| `RUNNING_THE_APP.md` | it will not start, or starts and shows no window |
| `STEREO_ROADMAP_V2_FULL_ACCOUNT_2026-09-28.md` | what was built since 2026-09-18, how the two branches were merged, what the merge broke, and every open problem |

Everything else is dated and describes the state of the app on its own date.
Where an older report and the account document disagree, the account
document is newer and says so explicitly.

## Project layout

```text
main.py
common.py
apps/
  truss/
    truss_app.py
    truss_math.py
    truss_reports.py
  beam/
    beam_app.py
  arch/
    arch_app.py
  cable/
    cable_app.py
  cable_web/
    cable_web_app.py
    cable_web_math.py
  perforated_beam/
    perforated_beam_app.py
    perforated_beam_math.py
tests/
  test_cable_web_math.py
  test_truss_load_signs.py
  test_perforated_beam_math.py
REPORTS AND GUIDES/
  *.md
```

`common.py` contains shared UI, constants and numerical utilities. Each folder under `apps/` contains the implementation modules for one structural application. `main.py` remains the single application entry point.

## Cable Web

`apps/cable_web/cable_web_app.py` is the graphical cable-network editor and `apps/cable_web/cable_web_math.py` is its existing analysis engine. The UI represents continuous user cables while the solver may internally subdivide them at required load/junction breakpoints.

Cable Web supports:
- supports and junctions;
- cables with individual prescribed lengths;
- point, UDL and variable loads per cable;
- geometric vs structural cable snapping;
- funicular, antifunicular and unloaded-reference displays;
- box/multi-selection and Delete;
- responsive desktop toolbar/sidebar layout;
- Excel import/export.

Excel workbooks exported by Cable Web contain `Nodes`, `Cables`, `Attachments`, `Loads` and `README` sheets.

## Perforated Beam

`apps/perforated_beam/perforated_beam_app.py` is the UI for long-span
beams with an arbitrary number/distribution of web openings
(uniform or variable/irregular pattern, arbitrary polygon shape), and
`apps/perforated_beam/perforated_beam_math.py` is its analysis engine:
global statics (V, M, T) for general loading, Vierendeel (secondary)
moment at each opening, web-post shear/buckling between openings, and a
combined bending+torsion check with automatic doubler-plate sizing. Units
are mm/N/MPa/N·mm (documented in the module itself, since this differs
from the other tabs). See
`REPORTS AND GUIDES/PERFORATED_BEAM_MANIFESTO.md` for standard/units
rationale, assumptions, references, and known limitations.

## Verification

Run from the project root:

```text
pytest -q
python -m compileall -q .
```

The current release reports and guides are stored in `REPORTS AND GUIDES/`.
