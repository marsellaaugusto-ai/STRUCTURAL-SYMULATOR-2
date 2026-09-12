# Cable Web v10 regression notes

## Frozen baseline
v9 was treated as the frozen baseline. No structural redesign was performed.

## Reproduced failure
A second diagnostic was built from the geometry visible in the reported screenshot:
- four fixed supports in two pairs;
- two support-to-support cables, each with a 10 m chord and 16 m prescribed length;
- one interior junction on each of those cables at s = 5 m;
- a third 20 m cable joining the two junctions;
- a 100 N vertical point load at s = 10 m on the third cable;
- a 10 N/m vertical UDL over the full third cable.

The previous solver stalled at approximately residual 2.40e-1. The returned iterate was not a valid equilibrium and the UI correctly hid it, but the model itself still could not be solved.

## Root cause
The normal nonlinear LM solver rejected every trial step that made any cable tension temporarily negative. In a multi-cable network this hard rejection can trap the iteration at the tension boundary even when a valid positive-tension equilibrium exists elsewhere in the feasible region.

## Fix
The existing Newton/LM solver remains the first path and is unchanged. When it fails, `solve_analysis` now makes a bounded nonlinear least-squares fallback using the same equilibrium and prescribed-length residual equations, with cable tensions constrained to T >= 0. It tries the best existing seed, as-drawn, and several force-density seeds. The fallback is only accepted when the same residual tolerance is satisfied.

The reproduced case now converges with residual approximately 5.6e-12 and all reported tensions non-negative.

## Visualization fix
The display interpolation was already intended to be display-only. It no longer passes the custom bounded interpolation through Tk's second `smooth=True` spline. Structural junctions and point-load positions are hard visual breakpoints, so the display does not invent curvature or erase real kinks.

## New UI regression example
The Cable Web toolbar now has `Picture test`, which loads the reproduced case. `Example` remains unchanged.

## Regression status
- Cable Web math tests: 7/7 passed.
- Full application launch: passed; 5 tabs present.
- Picture test exact analysis: converged, residual ~5.6e-12.
- Select-button zoom test: unchanged.
- Python compilation: passed.
