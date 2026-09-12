# Structural Simulator

Python/Tkinter desktop structural simulator organized by application module.

## Requirements

`numpy` and `scipy` are both **required** — not optional. `common.py` imports
numpy unguarded, and Cable Web's network solver reaches its tolerance through
`scipy.optimize.least_squares` on every web with a junction. `openpyxl` is
needed for Excel import/export (auto-installed on first use if absent).

```text
python -m pip install -r requirements.txt
```

## Main entry point

From the directory containing `main.py`:

```text
python main.py
```

Tabs:
- Truss
- Beam
- Arch
- Cable
- Cable Web

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
tests/
  test_cable_web_math.py
  test_truss_load_signs.py
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

## Verification

Run from the project root:

```text
pytest -q
python -m compileall -q .
```

The current release reports and guides are stored in `REPORTS AND GUIDES/`.
