# Cable Web v12 — Navigation and web-display correction

## Changes are deliberately scoped

This version starts from v11 and changes only the requested UI/navigation and loaded-web visualization behavior.

### Navigation commands

- **Select**: click an element; drag an empty canvas area for box selection; drag a selected node to move it.
- **Pan**: activate the Pan button and left-drag the canvas. Middle-mouse drag remains available.
- **Zoom +**: zoom in around the canvas center.
- **Zoom -**: zoom out around the canvas center.
- **Fit**: fit the current user-defined web to the visible canvas.
- **Mouse wheel**: zoom around the cursor while the cursor is over the canvas.
- **P**: Pan tool.
- **S**: Select tool.
- **+ / =**: zoom in.
- **- / _**: zoom out.
- **0**: Fit view.
- **Escape**: Select tool.

## Loaded-web display correction

The solver continues to use the same exact result. The UI now maps solved positions back to user-visible junctions and endpoints when displaying the loaded funicular. Previously the user nodes were always drawn at their original chord coordinates, while the solved cable curves had moved to their equilibrium coordinates. This could make a connecting cable (especially cable C) look detached or appear to form an incorrect arch.

Load markers are also placed on the solved funicular when a valid exact result is displayed, instead of remaining on the original straight chord.

This is display-only and does not change the structural equations.

## Antifunicular

The antifunicular is now a **single web-level reflection**. The complete solved web is mirrored about one common horizontal symmetry line located at the **highest mathematical y-coordinate of the solved web**. The line is displayed as `Antifunicular symmetry line`.

The individual cable topology is preserved during the reflection; there is no separate arbitrary mirror axis for each cable.

## Regression verification

The picture-like diagnostic web was solved after the changes. Cable C's solved midpoint is below its solved endpoint chord in mathematical coordinates, i.e. it has the expected downward sag for the downward point load + UDL. The solved junction positions are also used for display.

The existing six math tests and the picture-like regression test pass. The other structural modules are left unchanged.
