# Cable Web diagnostic reference

The built-in Example remains the regression case:

- L = 10 m.
- C1: support-to-support span L, prescribed length 2L, midpoint point load.
- C2: support-to-support span L, prescribed length 2L, full-length UDL.
- C3: joins C1 and C2 at s = L/2 on each cable, prescribed length L.

Expected exact-analysis residual is approximately 5.4e-10 N-equivalent normalized residual and the result must be marked converged.

A failed exact analysis must never be drawn as a funicular. The solver may return its last Newton iterate for diagnostics, but the UI intentionally discards that iterate as a display result unless `converged=True`.

The Unloaded reference remains a self-weight-only reference with user loads removed.

Excel import/export stores nodes, cables, attachments and loads in separate worksheets and is intended as a persistence/data-exchange format, not as a replacement for the structural solver.
