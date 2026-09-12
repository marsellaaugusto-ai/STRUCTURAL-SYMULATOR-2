# Cable Web v9 diagnostic report

## Scope
This release is based directly on the v8 Cable Web application. The structural solver and the other structural tabs were kept unchanged. The pass was limited to verified UI/result-display defects plus Excel persistence.

## Defects found

### 1. Toolbar groups overlapped
The responsive toolbar placed every group in grid column 0. The groups therefore occupied the same horizontal position and several controls became invisible/unusable.

**Fix:** toolbar groups now flow left-to-right and wrap to additional rows. Controls inside an oversized group also wrap internally.

### 2. Responsive sidebars collapsed
The expanding canvas was packed before the right sidebar, allowing the right sidebar to collapse at narrower desktop widths.

**Fix:** fixed-width sidebars are packed first; the center canvas expands into the remaining desktop space. Widths adapt at 1200, 1000, 850, 720 and below 720 px.

### 3. Failed exact analyses displayed invalid geometry
The solver can return `converged=False` together with its final Newton iterate. The UI previously treated that iterate as a current result and drew it. This produced the apparently wild funicular shown in the reported screenshot.

**Fix:** a non-converged exact analysis is now rejected as a display result. `result=None` and `results_current=False`; the invalid geometry is hidden and the failure is reported in the status/validation area.

### 4. Display smoothing could overshoot
The previous `Canvas.create_line(..., smooth=True)` spline could invent loops/overshoot between sparse solver nodes.

**Fix:** the display now uses a bounded cubic interpolation that passes through solver nodes and is clamped to each local segment envelope. Point-load branches remain split so their exact kink is preserved. This changes display only; solver positions/equilibrium are untouched.

### 5. Excel persistence
Added Cable Web-only Excel import/export.

Workbook sheets:
- `Nodes`
- `Cables`
- `Attachments`
- `Loads`
- `README`

The workbook stores geometry in metres, forces in N, and distributed loads/self-weight in N/m. Import validates references and reconstructs the web topology.

Imported world coordinates are normalized to eliminate harmless Excel/binary round-off that can otherwise perturb this nonlinear solver at the 1e-15 level.

## Package cleanup
The previous package contained `cable_web_app.py.bak` and `cable_web_app.py.fixed`, which were development artifacts rather than runtime modules. They were removed from the release package to avoid confusion.

## Verification
- Cable Web mathematical tests: **6/6 passed**.
- Truss regression test: passed.
- All Python modules: compiled successfully.
- All project modules: imported successfully.
- Full application launch: successful (process remained running normally under the GUI test harness).
- Diagnostic A/B/C example: exact analysis converged, residual approximately `5.40e-10`.
- Box-selection path: no crash.
- Failed-analysis result suppression: passed.
- Excel export/import round trip: passed; imported diagnostic model converged with residual approximately `5.40e-10`.
- Responsive toolbar tested at 1600, 1200, 1000, 850, 720 and 650 px widths; all controls remained mapped and the groups wrapped without overlap.

## Intentionally unchanged
- `cable_web_math.py` solver formulation.
- Truss, Beam, Arch and Cable structural calculations.
- Cable Web topology/discretization strategy.
- Existing snapping semantics.
- Existing load definitions.
