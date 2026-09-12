# Structural Simulator module map

The project is organized by application so that each structural tool can be maintained independently while sharing the common UI/numerical layer.

```text
main.py                         application entry point
common.py                       shared constants, widgets and numerical utilities
apps/
  truss/
    truss_app.py                Truss UI/controller
    truss_math.py               Truss/Vierendeel calculations
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
tests/                          regression and mathematical tests
REPORTS AND GUIDES/             documentation and diagnostic reports
```

## Import rules

`main.py` imports each application through its package path, for example:

```python
from apps.truss.truss_app import TrussApp
```

Application-internal modules use relative imports, for example the Truss UI imports `.truss_math` and `.truss_reports`, while shared utilities continue to come from the root-level `common.py`.

The root directory containing `main.py` must therefore be the working directory when launching the application directly with:

```text
python main.py
```

## Design boundary

The Truss app is deliberately split at the stable boundary between stateful Tkinter interaction (`truss_app.py`) and deterministic calculations (`truss_math.py`). The solver receives plain lists/dictionaries and has no Tkinter, Excel, or drawing dependencies. That is the intended C++ migration boundary.

`truss_reports.py` owns Excel and PIL/matplotlib report output. Keep these in Python unless a future product requirement calls for a native reporting layer.
