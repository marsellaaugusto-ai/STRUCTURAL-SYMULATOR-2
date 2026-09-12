# Cable Web — Project Manifesto

**Read this before changing anything in `apps/cable_web/`.**

This document exists because the project's own history (see the other
files in this folder — `DIAGNOSTIC_REPORT.md`, `CONVERGENCE_FIX_V11.md`,
`UI_NAVIGATION_CABLE_WEB_V12.md`, `REGRESSION_NOTES.md`) shows a repeating
pattern across sessions: fix X, silently reintroduce Y; fix Y, quietly
regress X. Each individual report was technically correct about the bug
it fixed. What was missing was a stable place to write down the *general
lesson* behind each fix, so a future session (or future me) recognizes
the pattern before repeating it. That's what this file is for. It is
meant to be **added to, not replaced**, the next time a session here
learns something the hard way.

Last updated: 2026-09-05 (second pass same day), after the previous
pass's own fix was reported back as a new bug -- see sec 3w and
`CABLE_WEB_GEOMETRY_AND_DIAGRAMS_2026-09-05.md`. **`_insert_sag_vertex`,
added that morning to cure the plateau, was itself causing a visible
oscillation.** Its "don't insert on top of an existing node" guard was
scaled to the three-point WINDOW (2%), which spans two segments, so an apex
landing 4% into a segment passed it. Measured on the built-in Example's C2:
the apex landed 5.70 px from a node against 97.47 px typical spacing, and
the centred Catmull-Rom tangents across that sliver took the drawn curve
from 1 direction reversal (correct -- a single sag) to 3, overshooting the
solved envelope by 2.88 px. Guard rewritten to "the middle 60% of whichever
segment it lands in", so neither sub-segment can be under 20% of the
original; reversals back to 1, plateau sweep still 28/28, point-load plateau
still 7.6%. Also confirmed, by capturing the coordinate lists on their way
to the canvas, that the *other* half of the report -- the faceted,
polygonal look -- is NOT a defect: distributed loads are lumped at mesh
nodes, so an unloaded element is exactly straight and the solved cable
genuinely IS an <=8-sided funicular polygon. And verified the
tension/thrust diagram against the Cable tab: a point-load case agrees to
0.000% with closed form and with cable_app (H=436.4358, T=480.0794), and a
UDL case matches cable_app **to every printed digit at the same element
count** (n=8: sag 4.03727, H 130.2388, Tmax 161.9451). The one real issue
there is resolution, not formula -- Tmax is 5.1% LOW at 8 edges (161.9 vs
170.7 converged), and the diagram legend promises a V band that
`_draw_diagrams` never plots. Suite 116 -> 118. Before that: 2026-09-05, merging the fixed Cable Web into the
Truss/Perforated-Beam build and shipping it as
**STRUCTURAL SYMULATOR SOLVER-5-9-26**. Three rendering items plus a
whole-app sweep -- see sec 3u, 3v and `APP_DIAGNOSIS_2026-09-05.md`.
(1) **The reported "cables plateau at the peak or valley" is real, and had
two causes, neither of them the interpolator.** Establishing that needed a
control first: a true catenary IS flat at its vertex, so "looks flat" proves
nothing. Measuring the drawn flat run against the exact catenary's own flat
run at the same screen scale across a 28-case sweep, every plateau had an
ODD solver mesh (drawn 2.1x-6.3x flatter than truth) and every even mesh was
already faithful (0.61-0.96x). Cause A: an odd nseg puts two equal-height
nodes either side of the vertex and the true low point between them is
unreachable -- fixed by forcing an even count for cables carrying
distributed load. Cause B: a point load inserts its own breakpoint and
destroys that parity anyway (13.1% of the group flat versus 6.4% for the
same cable unloaded) -- fixed by _insert_sag_vertex, a display-only
parabolic apex recovered from the three solved nodes around the turning
point. 28/28 faithful after; both built-in examples bit-identical (Example
0.20 s / 3.55e-16, Picture Test 0.43 s / 1.98e-10). (2) **Loads are now
drawn on the antifunicular**, at mirrored positions but in their true
downward direction -- the antifunicular is the shape carrying those same
real loads in compression, so mirroring the arrows too would draw an arch
being pulled upwards. (3) **A tension/thrust diagram pane**, built in the
Truss/Beam diagram idiom exactly as sec 5 recommended: result.tensions[eid]
stepped against arc length, with thrust as the projected horizontal
component of the same data and no new solver output. It flags constant-H,
which is the live check that a cable under vertical load solved correctly.
Also restored common.py's numpy _beam_gauss_solve, which the incoming build
had silently reverted to interpreted Python -- see sec 3v. Suite 30 -> 116
tests. Before that: 2026-09-04, after a full external diagnostic pass found
three independent defects that each made the tab look broken on their own,
and all three were then fixed — see §3r, §3s and
`CABLE_WEB_DIAGNOSIS_2026-09-04.md`. (1) **SciPy turned out to be a hard
requirement, not the "fallback" the source calls it**: verbose tracing
shows all five Newton/LM seeds plateau far above tol on every multi-cable
network including both built-in examples, and 100% of converged results
came from `scipy.optimize.least_squares`. It was undeclared, absent on the
target machine, and its `ImportError` was swallowed by a bare `except` and
reported to the user as "did not converge". Now declared in a
`requirements.txt`, auto-installed by a new `_ensure_scipy()`, and raised
as a typed `MissingSolverDependency` with install instructions. (2) **The
at-rest Catenary preview was solving on the Tk main thread** from ~11 call
sites — measured 90.33 s of dead UI to build a 3-cable web (during a 48.9 s
rebuild the event loop serviced exactly ONE queued `after()` callback).
Phase 5 threaded the Analyze button and left this, the more expensive and
far more frequent one, alone. Now built on the main thread and solved on a
worker with the same queue/poll pattern, token-versioned so a stale result
is discarded, and request-coalesced (6 rapid edits → 2 solves, verified).
Same sequence now costs 1.90 s, and Straight is the new default. (3)
**`_solver_breakpoints()` left an unloaded, weightless, non-slack cable as
one rigid 2-node solver edge**, which `solve_analysis` reliably fails on —
the exact opposite of what `_solve_reference_component()` already knew
(§6). Removed; 4/4 previously-failing webs now converge, 3–20× faster, see
§3r. Also: a cable prescribed shorter than its own chord now fails/warns in
`_validate_model()` instead of validating as "structurally ready" and then
reporting a "converged" 313 kN under 372 N; a post-solve plausibility gate
flags a runaway tension:load ratio even when the residual is honest; the
dead duplicate `_result_user_node_positions` is gone; the zero-tension
display cache no longer keys on `id(result)`; and a model-serial guard
means a background Analyze result is discarded if any edit path (not just
the canvas one `self._solving` covers) changed the model underneath it.
Suite: 13 → 30 tests, 461 s → 127 s. Before that: 2026-08-31 (second pass same day), sparse matrices measured
properly (not deferred on an assumption) and a GUI diagnostic pass
across 10 diverse cable-web topologies (including this project's first
genuinely cyclic graph, a loop) — see §6. Dense vs sparse benchmarked
dof 16-3601 with correctness cross-checked at every size: crossover is
real, ~dof 240, but everything this app builds today (dof 40-150) sits
on the dense side, so implemented as a hybrid gated at dof>=150 rather
than switching unconditionally — inert for every existing case
(confirmed byte-identical), ready for a web big enough to need it.
Topology diagnostics: all 10 passed, including a first-time cyclic-graph
check and a higher-degree (5-cable) indeterminate junction; one
non-bug worth recording -- junctions separated only by a shared support
correctly solve as separate components, not one, since a support is
fixed either way. Full report: `CABLE_WEB_TOPOLOGY_DIAGNOSTIC_2026-08-31.md`.
Before that: 2026-08-31, Phase 4's remaining piece and Phase 5 done —
see §6. Profiled (not assumed) the Picture Test's ~7s reference solve:
the bounded-least-squares fallback was using its own finite-difference
Jacobian for 8.2 of 10.6 profiled seconds, even though the analytical
Jacobian already derived for the primary Newton loop differentiates the
exact same residual function — wiring it in dropped that solve to ~2s.
Sparse matrices and iteration-cap retuning left undone: the actual
bottleneck was the fallback's Jacobian, not `J^T J` assembly or the caps,
so doing those now would be optimizing an already-fixed cost, not a
real one — worth revisiting if a much larger web changes that. Also
background-threaded the Analyze button (`_solve_exact` builds the model
on the main thread, runs `solve_analysis` in a `threading.Thread`,
result returned via `queue.Queue` and picked up through
`self.after(...)` polling — the standard safe Tk pattern) with a
progress bar, disabled buttons, and a `self._solving` guard on canvas
edits so a result can't land on a model that changed underneath it;
verified the main loop stays genuinely responsive during a solve (49
successful `root.update()` calls processed mid-solve in one run), not
just "didn't crash." Before that: 2026-08-30 (second pass same day), Phase 2's actual
implementation done, plus Phase 3 (the Straight/Catenary preview
toggle) — see §6. Junctions now solve to their true self-weight
equilibrium position (a connected-component network model, every
segment discretized into several sub-edges — including taut ones, which
turned out to matter: a single rigid edge between two free junctions
repeatedly failed to converge where the same constraint split into a
few small sub-edges converged cleanly, found by direct comparison, not
assumed) instead of sitting pinned to `_point_on_chord`'s straight
chord. New regression tests confirm this on both built-in examples.
`n['x']`/`n['y']` themselves are never touched — confirmed by a test,
not assumed — so dragging/snapping/the inspector/`_point_on_chord` all
work exactly as before. A new Straight/Catenary radio toggle controls
which of these is shown, Catenary by default; Straight skips the solve
entirely rather than just hiding its result. Both built-in examples
solve in ~7s through the real UI — not instant, but this is an on-edit
recompute, never per-frame. Phase 4's sparse-matrix step and iteration
retuning, and Phase 5 (threading), remain undone. Before that, same day:
option 1 from the previous entry done: fixed
`solve_analysis` itself rather than routing around it — see §6, third
attempt. Root cause wasn't solver robustness after all — a single edge
in this formulation can never represent genuine slack (`L==target` is
required unconditionally), so every previous Phase-2 attempt was asking
for something geometrically impossible whenever a segment was slack,
regardless of Jacobian or decomposition strategy. Discretizing each
segment into several sub-edges (as `_solve_nominal_catenary` already
does) converges cleanly even with the OLD Jacobian — proving that; the
remaining slowness (17.5s) was profiled, not guessed, to a nested-Python
`J^T J` assembly, not the Jacobian. Added a verified analytical Jacobian
(closed-form, matches finite-difference to ~5e-5, FD kept behind a
flag) and moved `J^T J`/`J^T f` to numpy. Together: the same discretized
case that took 17.5s now takes 1.6s; the real Picture Test through
Analyze drops from ~15.2s (original) / 10.24s (Phase 1) to **0.66s**.
Full suite 1.8s (was 9.5s after Phase 1, ~15.9s originally). Identical
converged tension values throughout — same equations, faster, not a
different computation. Phase 2's actual wiring is still not done — this
pass stops at "the blocker is gone," deliberately, to confirm the fix
holds before building on it. Before that: 2026-08-29, a second attempt at Phase 2 (a narrower,
decomposed Gauss-Seidel relaxation instead of one big simultaneous
solve) — also blocked, and traced to the actual cause this time, not
just a symptom — see §6. A junction held taut, by a tie, well away from
where its own cables' self-weight alone would settle it (confirmed:
23.24 m away vs. a 20 m tie) is a completely ordinary, physically valid
configuration that `solve_analysis` doesn't reliably converge on,
whether solved as one big network or decomposed into one-free-node
sub-solves — ruling out decomposition strategy as the fix. Nothing
wired up; two concrete ways forward written up, no decision made yet.
Before that: same day, Phase 2 first attempted directly (see below) and
found blocked — see §6. `solve_analysis` does not reliably converge on
the real Picture Test's own topology when solved self-weight-only (the
reference/preview case): isolated, with minimal standalone models, to
cables that go slack between two junctions specifically (a taut
junction-to-junction link converges fine; the same link with real slack
does not). This is a property of the solver itself, which Phase 2's own
instructions place out of scope, so nothing was wired up — the existing
per-segment reference behavior is untouched and still in place. One
harmless, genuinely-dead-code bug fixed in passing (`_build_solver_model`'s
never-before-reachable `reference_self_weight=True` branch referenced an
undefined variable). Before that: 2026-08-29, Phases 0–1 of a 5-phase
staged solver
correctness/performance plan — see §6. `common.py`'s shared
`_beam_gauss_solve` (every tab, not just cable_web) now delegates to
numpy.linalg.solve instead of hand-rolled Gaussian elimination: same
contract, ~40% faster on the math test suite, ~33% faster wall-clock on
the one UI case big enough to show it, residuals matching the existing
diagnostic references. Phases 2–5 (the actual junction-kink fix, a
display toggle, analytical/sparse Jacobian, background-threaded Analyze)
deliberately not started this pass. Before that: 2026-08-28, after making
the at-rest (pre-Analyze) cable
rendering show each cable's real self-weight shape as the PRIMARY
display, with a visual flag for cables too short to sag, replacing a
redundant secondary "ghost" layer — see §3q. This request's own premise
("Original currently draws a straight chord regardless of length") did
not match the code as it stood — `_reference_paths` was already
preferred over a straight chord, per §3m below — so the real work was
narrower than framed: add the taut/slack visual distinction (genuinely
missing), and remove the resulting double-render once that distinction
existed. Also found, while implementing it, that `_solve_nominal_catenary`
is far too slow (~1s/segment, measured) to re-run on every drag
mouse-move; see §3q for the fallback chosen instead. Before that:
2026-08-27 (second pass same day), after the antifunicular
Fit fix below revealed a related gap while testing it at different
window sizes: the canvas's own `<Configure>` event (real pixel resizing,
as opposed to the zoom/pan state changes `_on_zoom_changed` already
covered) was never wired to anything. First symptom is the app's very
first appearance being a blank canvas; the same gap means any later
window resize leaves stale, wrong-sized content on screen too, not just
the first one. Fixed by binding the canvas's `<Configure>` to `_draw()`
directly — see §3p. Before that, same day: after a UI diagnostic pass on
`structural_simulator_v15_fixed5.zip` (run under Xvfb with real
screenshots and live interaction, not just code reading — see §2).
Re-confirmed the previously-reported wiggle (§3h) and support-drag (§3g)
bugs are both still fixed, and found and fixed one new one: `_fit_view()`
measured only the user's own nodes, so the antifunicular view — whose
underlying math was already correct — rendered almost entirely outside
the visible canvas in ordinary use, looking broken when it wasn't. See
§3o. Before that: 2026-08-21 (second pass same day), after completing the
manifesto's own "full workflow test of every dialog's fields" item:
drove the Load dialog (Point/UDL/Variable, plus error paths) and the
Junction dialog through their real widgets, not just button-invocation.
Found and fixed two real gaps — a backwards-entered load range (Start >
End) stored unswapped, and an invalid q(s) expression accepted silently
until a much-later Analyze failure — see §3n. Before that: fixed a
hit-test coincidence bug (nodes 2 and 3 in the Picture Example couldn't
be selected/dragged whenever a click drifted a couple of pixels
off-center) and made cables display their natural self-weight catenary
shape by default before solving, instead of a straight line — §3l, §3m.
Before that: fixed the flat "plateau" artifact at a slack segment's low
point and the identical bug in the ghost/reference catenary, by
extracting both into one shared, properly-resolved, timing-tested
helper (§3i–k). Before that: fixed support drag not working when a load
overlaps it, and a wrong sinusoidal path on slack/zero-tension cable
segments (§3g, §3h). Originally written 2026-08-19 after a diagnostic
pass that fixed three UI bugs (support placement not redrawing,
mouse-wheel zoom/pan not redrawing, and toolbar rows rendering
off-screen or invisible) and confirmed all three
`cableweb_report*.xlsx` cases import and solve correctly through the
real UI pipeline.

---

## 1. Architectural invariants — do not violate these

1. **The UI never does structural equilibrium math.** `cable_web_app.py`
   builds a solver model and calls `solve_force_density` /
   `solve_analysis` from `cable_web_math.py`; it does not compute
   tensions, reactions, or geometry itself. If a UI feature seems to need
   new math, the math goes in `cable_web_math.py` (or a thin adapter
   layer next to it), not in a button callback.
2. **A non-converged result is never shown as if it were valid.**
   `_solve_exact` already enforces this (`if not result.converged: self.result
   = None`) — preserve this. A near-equilibrium Newton iterate that
   *looks* like a funicular but isn't one is worse than no result at all.
3. **Object ids are stable and never reused or renumbered on delete.**
   Don't refactor toward list-index-based identity for nodes/cables/loads
   — that reintroduces exactly the class of bug stable ids were adopted
   to avoid.
4. **`cable_web_math.py` is expensive to modify, cheap to leave alone.**
   It is validated (see `tests/test_cable_web_math.py`, 7/7 passing as of
   this writing) and its convergence behavior (including the ~20s solves
   on indeterminate-junction networks, see §4) is understood and
   accepted, not accidental. Don't touch its numerical strategy to chase
   a UI-perceived problem (e.g. "it's slow") — fix the UI's *handling* of
   that behavior instead (see the busy-cursor fix in §3e below), and only
   revisit the solver itself as a deliberate, dedicated, separately-tested
   effort.

---

## 2. Diagnostic method that actually works — use this, not guesswork

Every bug in this session was found by **running the real UI under a
virtual display (Xvfb) and either taking an actual screenshot or directly
querying live widget geometry** — never by reading the code and reasoning
about what it "should" do. Two specific traps this project has already
fallen into make static reasoning unreliable here:

- A widget can report `winfo_ismapped() == True` with entirely correct
  `x, y, width, height` and still be **completely invisible**, painted
  over by a sibling widget with a higher stacking position (§3d). Don't
  trust geometry queries alone as proof something is visible.
- Screenshotting an Xvfb session with `import -window root` can silently
  capture a stale/blank buffer. Get the specific window's id via
  `root.winfo_id()` and screenshot *that* (`import -window <id>`) —
  confirmed reliable in this session; `root` was not.

**Standard verification checklist for any change in this app:**
1. Run `python3 -m pytest -q` from `structural_simulator_modules/` — must
   be 7/7 (or however many exist by the time you read this) passing.
2. Launch the app under Xvfb, actually take a screenshot at 2–3 window
   widths spanning wide to narrow (e.g. 1600px, 1000px, 550px), and
   *look at it*. Don't infer from `winfo_ismapped()` alone.
3. Programmatically invoke every toolbar button (monkeypatch
   `filedialog.askopenfilename/asksaveasfilename` to return a fixed path
   or `''`, `messagebox.*` to no-ops, and `tk.Toplevel.wait_window` to a
   no-op, or a button that opens a blocking dialog will hang the test
   process indefinitely) and confirm none raise.
4. Re-import at least one `cableweb_report*.xlsx` (or equivalent) through
   the real `_import_excel` → `_validate_model` → `_solve_exact` pipeline
   and confirm it still converges. These three files are a good
   regression fixture — keep them, or equivalents, for this purpose.

---

## 3. Specific hard-won lessons from this session (bug *classes*, not just instances)

### a. Every model-mutating branch of a click handler must redraw
`_canvas_press`'s `'support'` branch called `self._invalidate(...)` but
never `self._draw()` — every sibling branch (`'cable'`, etc.) did. The
result: a newly placed support was fully created in the model and
invisible until *any* unrelated redraw happened to fire (e.g. switching
to the Select tool). **When adding or editing a tool branch in a click
handler, check that it ends in a redraw, by direct comparison with a
sibling branch that's known to work — don't assume `_invalidate` or
similar bookkeeping helpers redraw internally.**

### b. `ZoomCanvas._on_zoom_changed` must be wired up explicitly
`common.py`'s `ZoomCanvas` updates `zoom`/`pan_x`/`pan_y` internally on
wheel-scroll and middle-drag, and calls `self._on_zoom_changed()` — a
no-op placeholder by default. Every other tab
(`self.zc._on_zoom_changed = self._draw`, see `truss_app.py`) overrides
it; Cable Web didn't, so wheel zoom and middle-drag pan silently changed
internal state with the view never repainting. **Any new `ZoomCanvas`
instance must wire `_on_zoom_changed` to a redraw in the same line it's
constructed — there's no other signal that this was forgotten.**

### c. Don't cache a layout decision keyed only on "did the input change"
The toolbar's responsive relayout short-circuited when
`bar.winfo_width()` matched a cached `_toolbar_last_width`. The *first*
call (from `after_idle`, before the window had fully stabilized) could
read a transient, wrong width, compute a wrong layout from it, and cache
that width — after which a later, legitimate resize back to the *same*
final width would hit the cache and never re-run the correct
computation. **A perf-guarding cache is only safe if the cached decision
is re-validated against reality sometime, not just re-used verbatim
because a proxy input matched.** If in doubt, don't cache a `<Configure>`
handler's work at all — for anything under a few hundred widgets it's not
worth the risk.

### d. `grid(row=, column=)` is the wrong tool for an independent flow layout
Tk's grid geometry manager sizes **each column to the widest occupant of
that column across every row** of the same parent. A "wrap groups to new
rows as needed" layout built with `grid(row=, column=)` directly on one
parent will misalign/overflow any row whose column widths don't happen to
match another row's — which they generally won't, since different rows
hold different numbers/widths of items. **For any layout where each row
should be sized independently (a flow/wrap layout), use one `Frame` per
row, `pack(side='left')` items inside it, and `pack(side='top')` the row
frames — never `grid(row=, column=)` shared across rows of varying
content.**

### e. `pack(in_=sibling_frame)` needs `.lower()` on that sibling, or it hides its own contents
Fixing (d) by introducing per-row anchor frames and
`child.pack(in_=row_frame, ...)` looks like it reparents `child` under
`row_frame` — **it does not.** `child`'s true Tk parent stays whatever it
was created with; `pack(in_=...)` only controls *where* it's drawn.
`row_frame` and `child` are still true siblings under the original
parent, and Tk's stacking order among true siblings is governed by
creation time — so a freshly-created `row_frame` (built *after* the
long-lived widgets it's meant to position) paints **on top of** them,
hiding them completely, even though every individual widget reports
itself correctly mapped and positioned. This is exactly the kind of bug
§2's "geometry looks right but isn't visible" warning is about,
and it's why the toolbar could pass a geometric overlap/off-screen check
and still render completely blank. **Any time you create a new Frame
purely as a `pack(in_=...)` positioning anchor for already-existing
sibling widgets, call `.lower()` on that anchor frame immediately** so it
sits behind, not in front of, the content it's positioning.

### f. Long synchronous solves need a busy indicator, not a rewrite
`solve_analysis` runs on the Tk main thread; a ~20s solve (observed and
expected — see §4 — for the multi-junction topology in all three
`cableweb_report*.xlsx` cases) freezes the entire UI with zero feedback
unless something explicitly shows a status message and busy cursor
*before* the blocking call, forced to paint via `update_idletasks()`.
This was missing in `_solve_exact` and has been added (status text +
`toplevel.config(cursor='watch')`, reset in a `finally:`). **This is a UI
fix, not a performance fix** — it does not change how long the solve
takes, only whether the user can tell the app is working rather than
frozen. Don't conflate "make the wait less confusing" with "make the
solver faster" — they're different problems with very different risk
profiles (see §1.4).

### g. Hit-testing must compare distances across candidate types, not use a fixed priority order
`_hit()` checked loads, then nodes, then cables, in that fixed order —
so a load positioned at or near a support (an entirely ordinary layout;
a UDL starting exactly at s=0 sits right on top of its cable's start
support) always won the hit test, even when the support was the far
closer (or exactly co-located) candidate. This silently made select+drag
on a support "not work" any time a load happened to sit there, which
reads as a random, hard-to-reproduce bug rather than what it actually
was: a deterministic priority-order defect. **Fixed by gathering the
closest candidate of each type with its own distance and picking the
global minimum** (node checked first in the candidate list so it wins
ties, e.g. a load positioned at exactly zero distance from a node — see
the code comment at `_hit()` for why ties should favor the structural
point). Verified via `_hit()` called directly at a support's exact
position with a UDL starting there (now returns the node), and at the
load's own body away from the support (still returns the load). If you
add a new selectable object type later, route it through this same
distance-comparison, not a new priority tier.

### h. A slack, unloaded (zero-tension) cable segment has no unique shape — don't trust its raw solved interior positions for display
A segment with more prescribed length than its straight-line span
(slack) and zero applied load (no self-weight, no point/UDL loads) has
**tension ≈ 0 everywhere along it** in the true solved equilibrium. This
is not a solver defect: with T=0, the force-balance equations impose no
directional preference at all, so *any* sufficiently loose configuration
of its free interior nodes is equally valid. The solver's Newton
iteration lands on whatever such configuration it happens to converge
to — which can be a visually wiggly, multi-hump path with no physical
significance, even though it satisfies the length/equilibrium
constraints exactly and the solve genuinely converges.

Diagnosed 2026-08-20 on the Picture Test example: the stretch between
a junction and its neighboring support had 2.85 units of slack, zero
load, and tensions of order `1e-12` against a network scale of
100-200 (i.e. correctly, genuinely zero) — yet displayed a sinusoidal
path (4 sign changes in the y-sequence between its 6 control points,
where a proper single-lobe catenary should show at most 1). Confirmed
this was in the RAW solved points themselves (before `_smooth_polyline`
ever runs), not a smoothing/interpolation artifact — ruling out §3d/e-style
display-math causes first, rather than assuming.

**Fix (display-only, in `_draw_solver_result`): when every edge in a
drawn group has near-zero tension (`< max(tmax * 1e-6, 1e-9)`), don't
trust that group's raw interior solved positions. Instead, treat its two
endpoints (junctions/supports/point-load nodes — always trustworthy,
never part of the arbitrary interior) as fixed, and re-derive a clean
shape by solving a small independent model with a nominal self-weight
(`weight_per_length=1.0`) between them — exactly the technique the
codebase already uses for the unloaded reference ghost in
`_update_reference_result`.** This never touches the real solved model,
tensions, or reactions — the reported `T≈0` for that stretch is correct
and is displayed as-is; only the *curve shape* drawn for that one group
is substituted. Verified by extracting the actual live `_smooth_polyline`
call arguments before/after the fix: sign changes in the affected
group's y-sequence went from 4 to 1, with zero change to the other five
groups in the same example.

**If you see another wiggly/wrong-looking cable segment in the future,
check tension first** (`result.tensions.get(eid)` for its edges) before
assuming it's a display bug — a near-zero-tension slack segment is a
different problem (and a different, already-solved fix) than an
actually-loaded segment whose curve looks wrong for some other reason.

### i. A resolution cap is not the same thing as the formula that chooses resolution
Both `_solver_breakpoints`' mesh density and the original
`_update_reference_result`/`_draw_solver_result` mini-catenary code used
`nseg = max(4, min(SOME_CAP, ceil(target/2.5)))`. It's tempting to assume
raising `SOME_CAP` fixes an under-resolved curve — it doesn't, if the
*formula* (`ceil(target/2.5)`) already produces a value well below every
cap in sight. Diagnosed 2026-08-20: for `target=11.0`, `ceil(11/2.5)=5`,
which is less than caps of 8, 10, *and* 12 — so raising the cap alone,
which was the first thing that looked like the fix, would have changed
nothing. The actual under-resolution came from the divisor (2.5 units
per segment was too coarse for this size of slack/sag), not the cap.
**When a mesh/resolution bug shows up, check what the un-capped formula
actually evaluates to for the specific case at hand before assuming the
cap is the lever to pull.**

### j. The same sub-problem solved in two places will drift unless it's actually the same code
The "give a slack, unloaded stretch a sensible nominal-self-weight shape"
logic existed independently in `_update_reference_result` (the ghost) and
in `_draw_solver_result` (the zero-tension substitution added in §3h) —
copy-pasted with a slightly different `nseg` formula in each. The
resolution bug in §3h was fixed once in the display code; the *identical*
bug was still sitting in the ghost/reference code, reported separately as
"a second flaw in the ghost catenary system" a session later. **Extracted
both into one shared method, `_solve_nominal_catenary`,** so this class of
fix now only has one place to land. If you're about to fix a bug in one
of these two call sites again, check whether it's still calling the
shared helper (it should be) rather than a reintroduced local copy.

### k. Mind the solve-time cliff when choosing a mesh resolution
Measured directly on this exact case (`target=11.0`, plain hanging chain,
nominal self-weight): 11 segments → 0.4s, 12 → 0.7s, 14 → 0.9s, 20 →
11.7s, 30 → did not converge within 30s. The relationship is not smooth
or predictable — there's a cliff somewhere between 14 and 20 for this
solver's current Newton/multi-seed strategy. `_solve_nominal_catenary`
caps at 14 for exactly this reason. **Do not raise that cap without
re-measuring timing on a range of realistic cases first** — "a bit more
resolution" can silently turn into an 11-second stall per affected
segment, and per §1.4, that's a solver-timing question, not something to
guess at.

### l. A hit-test "capture bonus" for nodes covers the case distance-comparison alone doesn't
§3g fixed the fixed-priority-order problem (loads always beat nodes) by
comparing actual distances. That's correct, but it isn't sufficient on
its own: two *unrelated* candidates can be genuinely equidistant or
even have the unrelated one closer, purely by geometric coincidence.
Diagnosed 2026-08-21 ("supports 2 and 3 don't move" in the Picture
Example): every node starts out on the same horizontal line before any
solve, so a load's hit-test line (based on its own parent cable's two
endpoints) can pass directly through a completely different, unrelated
node's position. The instant a click drifted a few pixels off that
node's exact center, the load -- still sitting at distance 0 on that
shared line -- legitimately became the closer candidate by raw distance,
and pure distance-comparison has no way to know the two aren't related.
**Fixed with a small fixed "capture bonus" subtracted from a node's
distance before comparing** (`6px / zoom`, in `_hit()`) -- a deliberate,
standard CAD convention (a snap point wins within its capture radius
even if a line is technically a hair closer), not a hack specific to
this one coincidence. This is layered on top of §3g's fix, not a
replacement for it -- both are needed together.

### m. Reusing an existing "natural shape" computation for the pre-solve display is safe; reusing it for *interaction* is a bigger, separate decision
Making cables display their natural (self-weight-only) catenary shape
before solving, instead of a straight line, was a simple, low-risk
change: `_reference_paths` (see §3h/j) was already computed and kept
current on every edit, so the "Original" drawing block just needed to
prefer it over the straight polyline when present. **But check what else
depends on the geometry you're about to change the *look* of.**
`_nearest_cable_point` -- which drives the Junction tool, cable
selection, and load placement -- explicitly and deliberately projects
onto the straight chord ("Use current straight chord for attachment
selection", per its own comment), not whatever curve is drawn. Swapping
only the *drawing* would have made cables look curved while everything
clickable on them stayed keyed to an invisible straight line underneath
-- a worse, more confusing mismatch than showing a straight line
honestly. Implemented the display-only version (low risk, matches what
was actually asked: see the shape more easily to plan attachments);
deliberately did NOT also rewire the hit-testing to follow the curve,
since that touches several interaction paths at once (junction
placement, load placement, cable selection) and deserves its own
explicit decision and testing pass, not a side effect of a display
tweak. If clicking precisely on a deeply-sagged cable's lowest point
ever needs to be exact, that's the follow-up work, and it starts at
`_nearest_cable_point`.

### n. Field-level dialog testing found what button-invocation testing can't
§2's checklist item "invoke every toolbar button" only proves a dialog
*opens* without raising — it says nothing about what happens once a user
actually types into its fields. Doing that for the Load dialog (all three
types, plus error paths) and the Junction dialog, by locating the real
`tk.Entry`/`ttk.Combobox` widgets and driving them exactly as a user
would, found two real gaps:

  - A ranged load entered backwards (Start > End, e.g. Start=17,
    End=0 on a 17m cable) was stored unswapped. It didn't crash --
    downstream lumping code already sorts internally -- but it displayed
    an inverted, confusing range everywhere it's shown (topology
    browser, inspector). Fixed: `add()` now swaps s1/s2 for ranged loads
    (Point loads always collapse s2 to s1, unaffected).
  - A syntactically invalid `q(s)` expression (e.g. `'5 + * 2s'`) was
    accepted with no error at all, and only surfaced as a failed Analyze
    much later -- confusing once the user has moved on to other edits.
    Fixed: `add()` now evaluates the expression immediately via the same
    `_safe_expr` the real solve uses (at the midpoint of the load's own
    range), so "accepted by the dialog" and "will actually solve" mean
    the same thing. The dialog stays open on failure so the typo can be
    fixed in place, matching how the numeric-value and range checks
    already behaved.

Also worth recording: `_solve_exact`'s own error handling was already
correct (it catches the SyntaxError and shows a clear message via
`messagebox.showerror`, `result` stays `None`) -- an apparent "hang" on
this exact case during testing was purely a test-harness artifact
(forgetting to monkeypatch `messagebox.showerror`, so the *real* blocking
dialog was waiting for a click that would never come). **If a live test
appears to hang, check whether `messagebox`/`filedialog` are actually
patched in *that specific* script before assuming the app is stuck** —
see §2's own checklist item 3, which exists for exactly this reason.

### o. `_fit_view()` only measured the user's own nodes — antifunicular views were invisible in normal use
A UI diagnostic pass on `structural_simulator_v15_fixed5.zip` (run under
Xvfb with real screenshots, not just code reading — see §2) found that
`_fit_view()` built its bounding box exclusively from `self.nodes` — the
original, as-drawn support/junction positions — never from
`self.result.positions` or `inverted_positions()`. Two symptoms followed
from the same root cause:

  - A cable's point-load kink in the funicular view could sit outside the
    original node bounding box and get clipped at the canvas edge, even
    after clicking Fit.
  - Far more seriously: the antifunicular view is computed correctly
    (confirmed node-by-node — e.g. Picture Test node 21 mirrors from
    y=−10.80 m to y=+10.80 m about the support line, exactly as intended)
    but rises roughly as far above the supports as the funicular sags
    below them. Neither the default view nor Fit ever accounted for that,
    so in ordinary use (load an example, Analyze, tick Antifunicular) the
    arch rendered almost entirely outside the visible canvas — a correct,
    working feature that looked completely broken.

Fixed: `_fit_view()` now widens its bounding box to include
`self.result.positions` (when a valid result is current and Funicular is
shown), `inverted_positions()` (when Antifunicular is shown), and the
unloaded/natural-catenary reference paths (when that toggle is shown) —
mirroring `_draw()`'s own visibility conditions exactly, so Fit always
frames whatever is actually on screen. Verified by re-running the
Example/Picture Test cases with the real Fit button (no manual zoom hack)
and by checking `canvas.bbox('all')` against the canvas viewport with the
grid's own intentional one-step edge-padding (see `_draw_grid`, the
`k0=...-1; k1=...+1` padding) accounted for separately — actual content
now sits within ~2px of the intended 50px margin on the constraining
axis, comfortably inside it on the other.

**Lesson for next time:** a "Fit" or "zoom to content" operation must be
defined over *everything the current view state would actually draw*,
not just the user's input geometry — any display mode that can
legitimately place solved content far outside the input's own bounding
box (an inverted/mirrored view is the obvious case, but this generalizes
to any future view mode with a similar property) needs to be added to
that operation's own bounding-box sources at the same time it's added to
`_draw()`, or it will compute correctly and still look broken.

### p. The canvas's own `<Configure>` (real resize) was never wired to a redraw at all
Found while re-testing §3o's fix at several window widths. `_on_zoom_changed`
(wired to `self._draw` since the 2026-08-19 pass, per the changelog above)
only fires when *this app's own code* changes zoom/pan — mouse wheel,
middle-drag pan, `_fit_view()`. It has nothing to do with the canvas
widget's actual on-screen pixel size, which Tk reports through a
completely different event, `<Configure>`, fired by the window manager
whenever the widget is first realized or later resized. Nothing was bound
to it. Confirmed directly: `winfo_width()`/`winfo_height()` report `1, 1`
during `__init__`'s own call to `self._draw()` (before Tk's first
geometry pass), so `_draw_grid()` computed grid-line extents for a 1x1
canvas; nothing ever redrew afterward, so the canvas stayed practically
blank — the app's very first appearance — until some unrelated action
(loading an example, any tool click, wheel-zoom) happened to call
`_draw()` again. The identical gap means any *later* resize is just as
broken: dragging the window narrower leaves the old, wider-sized grid
and geometry sitting on screen, confirmed by measuring `_draw_grid`'s own
line extents (identified by fill color, not just "everything on the
canvas") before and after a resize with no intervening redraw.

Fixed: `c.bind('<Configure>', self._on_canvas_configure)` right where the
other canvas bindings already live in `__init__`, calling `self._draw()`.
Deliberately left the existing one-time `self._draw()` call at the end of
`__init__` in place rather than removing it — this is additive, not a
reorder, so whatever initialization ordering that call already guaranteed
is untouched. Verified: item count goes from 16 (the stale 1x1-era grid)
to 113 (correct) with zero user action on a fresh launch; grid extent
(measured by color, across four different window widths from 1600 down
to 650) always reaches at least the current canvas size; a burst of 7
resizes in immediate succession redraws correctly in 0.14s total with no
exception and no runaway item growth; the existing wheel-zoom hook,
support-drag, full toolbar/tool sweep, and responsive-width layout were
all re-tested and are unaffected.

**Lesson for next time:** `_on_zoom_changed` and the canvas's native
`<Configure>` are two different notions of "the view changed" that are
easy to conflate — one is this app's own zoom/pan state, the other is
Tk telling you the widget's actual pixel size changed underneath you.
A redraw wired to one is not a redraw wired to the other; a screenshot
taken right after construction (this app's very first frame) is the
case most likely to catch the gap, since it's the one moment a
"resize" is guaranteed to have just happened without any user action
having occurred yet to paper over it with an incidental redraw.

---

### q. At-rest rendering: made the natural catenary primary, flagged taut cables, removed the redundant ghost layer
Requested as a bug fix ("Original always draws a straight chord"), but
the premise didn't match the code: `_draw()`'s "Original" branch already
preferred `_reference_paths` (the natural self-weight shape) over a
straight chord, per §3m. What was actually true, and actually fixed
here: (a) a cable with **no slack** at its current material length
(`_solve_nominal_catenary`'s `target_length <= chord` case) rendered
with **no visual distinction at all** from a genuinely sagging cable —
same color, same width, both solid; (b) "Unloaded reference" drew that
exact same `_reference_paths` data a second time, dashed and
Bezier-smoothed, directly on top of "Original"'s solid un-smoothed
version — confirmed on screen (Picture Test C3, a taut segment) as a
visible doubled/offset line, which is the concrete artifact a user would
actually perceive as "this looks wrong," even though the mechanism
wasn't a plain straight chord.

Fixed:
- `_update_reference_result()` now records, per segment, whether
  `_solve_nominal_catenary` returned a genuine catenary or its
  straight/no-slack fallback (`self._reference_segments[cid]` = list of
  `{'points': [...], 'taut': bool}`), alongside the existing flat
  `self._reference_paths` (left in its original shape so `_fit_view`'s
  §3o bbox code needed no changes).
- `_draw()`'s "Original" branch draws genuine segments in normal cable
  color/solid, taut segments in `WARNING` color with a dash — reusing an
  existing palette color instead of adding a new one.
- "Unloaded reference" removed entirely (checkbox, `BooleanVar`, guide
  text, tooltip, drawing branch); "Original" renamed to "At-rest shape"
  in the UI only (internal `self.show_original` name kept, to avoid
  touching every call site for a label change). One checkbox now
  strictly dominates what two used to show, with no loss of information.
- `_restore_snapshot` (Undo/Redo) now also calls
  `_update_reference_result()` -- a real, separate staleness gap found
  while checking "recompute live on edit" (Undo/Redo never recomputed
  the at-rest shape at all, before or after this request).

**Performance finding that changed the design:** direct measurement
(not assumption) showed `_solve_nominal_catenary` costs ~1 second per
segment. Calling `_update_reference_result()` on every `_canvas_drag`
mouse-move (the naive way to keep the at-rest shape "live" during a
drag) made dragging take ~700ms/frame -- unusable. `_draw()` itself is
cheap (~3.5ms); the cost is entirely the physics mini-solve.
Reverted that, and instead: for the duration of an active node drag,
any cable touching the dragged node falls back to the plain straight
polyline (the same fallback already used when no reference data exists
yet) instead of its now-stale `_reference_segments` entry. This is
always exactly attached to the node under the cursor (confirmed:
0.000000 world-px detachment through a 30-step synthetic drag) and costs
nothing extra, at the honest price of not looking like a real catenary
for the ~1 second the mouse is actually moving; the true shape reappears
the instant `_canvas_release`'s existing recompute runs. Also checked, on
a drag that put a support very close to a heavily-slack cable's other
end (a short-chord, high-excess-length case): the resulting reference
shape's raw points looked alarming at a glance (y: 48→68→80→60→40→20→0)
until checked properly -- x moves monotonically the whole time, y has
exactly one sign change -- a clean, tall, narrow single-lobe sag, not a
wiggle. It only looks line-like in a full-scene screenshot because the
affected span was under 1 m against a ~30 m view. Worth remembering:
eyeball a y-sequence in isolation and short-chord/high-slack geometry
will look exactly like the wiggle bug this project has chased twice
before (§3h); check x alongside y, or zoom in on the actual geometry,
before concluding either way.

Added `tests/test_cable_web_ui_reference_shape.py` (deliberately
separate from `test_cable_web_math.py`, which is scoped to the headless
solver engine per its own docstring) covering both cases end-to-end,
including the canvas fill/dash colors, not just the underlying data;
each test skips itself if no display is available so a normal headless
`pytest` run stays green. `cable_web_math.py` and
`_draw_solver_result()`'s zero-tension handling were not touched.

---

### r. A finding about the SOLVER's conditioning must be carried to every place that builds a model for it — §3j again, one layer down

§3j recorded the display-code version of this: the same sub-problem
implemented twice will drift, so extract it. The solver-side version bit
much harder, and took a year of sessions to surface.

§6 established, by direct measurement, that **a single rigid 2-node edge
between free nodes is markedly harder for `solve_analysis` than the
identical rigid constraint spread over a few small sub-edges** — that is
why `_solve_reference_component()` discretises *every* segment, taut ones
included. That finding was written down, explained at length, and applied
to exactly one of the two places this project builds a `CableWebModel`.

The other one, `_build_solver_model()` — the model the **Analyze button
actually uses** — held the opposite rule, and held it as a *documented
optimisation*: `_solver_breakpoints()` skipped the mesh whenever a cable
had no self-weight, no load and no slack, on the reasoning that fewer free
nodes means better conditioning. Because it was commented as deliberate,
nobody re-read it against §6. Measured 2026-09-04 on four webs differing
only in whether that mesh was applied:

| web                          | as shipped            | subdivided            |
|------------------------------|-----------------------|-----------------------|
| star, tie exactly taut       | FAIL 3.374e-02 1.34 s | OK 4.298e-14 0.08 s   |
| star, tie shorter than chord | FAIL 1.944e-03 0.95 s | OK 9.257e-13 0.07 s   |
| twin cables + taut tie       | FAIL 4.417e-02 5.32 s | OK 3.502e-14 0.54 s   |
| junction on a taut hanger    | FAIL 2.194e-02 0.27 s | OK 3.601e-09 0.17 s   |

4/4 fixed, and 3–20× *faster* despite the extra unknowns — the extra free
nodes cost far less than the conditioning they buy. One of those abandoned
iterates reported `Tmax = 3.08 N` where the true answer is `132.5 N`; the
UI correctly hid it (invariant §1.2 held), so the user's only symptom was
"Analyze doesn't work on this shape and I can't see why".

**What made this hard to find, and what to do about it:** the symptom
(non-convergence) points at the solver, while the cause was in the model
*handed* to the solver. Reading `solve_analysis` teaches you nothing.
`tests/test_cable_web_diagnosis_fixes.py::test_no_cable_becomes_a_single_rigid_solver_edge`
now guards the mechanism directly — it asserts `_solver_breakpoints()`
never returns just `{0, L}` — so a future "optimisation" that reintroduces
the short-circuit fails immediately and by name, instead of resurfacing as
a mysterious convergence bug months later. **Whenever a finding about the
solver's own conditioning is recorded here, grep for every
`CableWebModel()` construction site and check each one against it in the
same pass** — there are two today, and a third will be just as easy to miss.

### s. Threading the second solve: the pattern is reusable, the contention is not free

Phase 5's threading of `_solve_exact` was correct and is the model to
copy — but "the Analyze button no longer freezes the UI" was mistaken for
"the UI no longer freezes". `_update_reference_result()` was still fully
synchronous and is both more expensive and far more frequent (~11 call
sites: every new cable, drag release, dialog Apply, delete, undo, redo,
example load and mode toggle). Building a 3-cable web cost **90.33 s** of
dead UI. **When one blocking call is moved off the main thread, enumerate
every other call that reaches the same engine before declaring the freeze
fixed** — `grep` for the engine's name, not for the button's.

Three things the port needed that the original did not:

- **Split build from apply.** `_solve_reference_component()` mixed reading
  `self.nodes`, solving, and converting back to world pixels. The worker
  may touch none of the first or third. Split into
  `_build_reference_component()` / `_apply_reference_component()`, with
  everything the apply step needs about a node (notably `is_support`)
  captured *at build time* — so apply never re-reads `self.nodes`, which
  may have moved on. Same split for `_solve_nominal_catenary` via a new
  `_build_nominal_catenary()`. The original synchronous methods are kept
  as thin build+solve+apply wrappers so existing callers and tests are
  untouched.
- **Version every request.** `_reference_token` is bumped by each request;
  a result whose token is stale is discarded and the worker restarts for
  the current question. This also gives coalescing for free — only one
  worker runs at a time, so a burst of 6 rapid edits produces 2 solves
  (verified by counting worker starts), not 6.
- **Don't hold a widget reference in the worker.** Bind the queue to a
  local (`result_queue = self._reference_queue`) rather than reaching
  through `self`. A daemon thread that outlives `root.destroy()` and holds
  the last reference to the app will run `tkinter.Variable.__del__` off the
  main thread during GC and raise "main thread is not in main loop".
  Capturing only plain data makes that structurally impossible.

**The honest cost, measured, not assumed:** two CPU-bound Python threads
do not run at full speed together. Analyze alone takes 1.56 s; alongside a
running preview solve it takes 21.6 s — GIL convoying on many small numpy
operations, not a 2× split. Mitigated where it can be (a preview will not
*start* while `self._solving`, and `_poll_solve_queue` releases it
afterwards), but a preview already in flight cannot be cancelled without
adding a cooperative-cancel hook to `solve_analysis`, which is §1.4
territory and was deliberately left alone. This is why Straight is now the
default: the preview is a background nicety, and the user opts into paying
for it. **Threading converts a freeze into contention — it does not create
throughput. If the work is not worth a core, make it opt-in rather than
making it concurrent.**


### u. "Looks flat" is not a defect until you measure it against the real curve

The bug report was "the cables with self weight are not smooth, they
plateau around the peak or valley". The obvious reading is a bad
interpolator, and the first fix attempted was exactly that -- replacing
`_smooth_polyline`'s clamped Catmull-Rom with a monotone (Fritsch-Carlson)
cubic. **It was measurably worse and fixed nothing**, and the measurement
that showed this is the point of this entry.

A catenary genuinely IS flat at its vertex -- `y - y_min` grows as
`x^2/2a`. So the flat run alone cannot distinguish "under-resolved plateau"
from "correct shape". The control that does: compute the flat run of the
**mathematically exact** catenary for the same span and arc length at the
same on-screen scale, and compare. Doing that on the five original cases:

| case | drawn (as shipped) | true catenary |
|---|---|---|
| 20 m / 26 m | 6.4% | 7.0% |
| 10 m / 12.5 m | 4.1% | 7.8% |
| 30 m / 40 m | 0.0% | 3.0% |
| 16 m / 17 m | 8.0% | 10.5% |
| 24 m / 30 m | 3.1% | 4.5% |

The drawn curve was **less** flat than the truth in every one. There was no
interpolation defect at all in those cases -- and scoring four interpolator
variants against the analytic curve confirmed it: vertex error was identical
(to 0.01 px) for every variant including the original, because the vertex is
a solved node and every variant passes through it exactly. The only thing
the monotone version changed was to make the flanks worse (max deviation
1.55 -> 2.11 px, 8.76 -> 11.75 px). Reverted.

The real cause only appeared from a 28-case sweep of the same ratio: every
plateau had an ODD `nseg` (2.1x-6.3x too flat), every even one was fine.
With an odd count two nodes sit either side of the vertex at equal height
and the true low point between them is below both -- unreachable by any
interpolation through those nodes, because the DATA is wrong, not the curve
fitted to it. See sec 3v for the second cause and the fixes.

**Lesson: before "fixing" a shape, compute what the shape should be and
compare numbers.** This project already had the habit for wiggles (sec 3h's
sign-change check); flatness needed the same treatment and did not have it.
A second-order version of the same trap: the fix you reach for first is the
one that matches your mental model of the cause, and it will often "look
better" in a screenshot while being quantitatively worse.

### v. Where the mesh cannot be refined, refine the drawing -- and check what a merge silently reverted

Two follow-ons from sec 3u.

**The mesh is not the lever, again.** Having found the odd-mesh cause, the
tempting fix is a finer mesh everywhere. Measured first (sec 3k's rule), and
sec 3k's cliff is still there: `_solver_breakpoints`' divisor 2.5 -> 1.25
takes the Picture Test's Analyze from 1.2 s to 42 s, and 2.5 -> 0.8 takes it
to 240 s -- while the same refinement on a single cable is nearly free
(0.13 s -> 0.39 s). The cost is in the network solve, not the mesh. So: force
even parity (at most one extra edge, and only on cables with distributed
load, so the Picture Test is untouched -- applying it to every cable pushed
its residual from 1.98e-10 to 2.42e-08 for no visual gain), and recover the
rest in the drawing. `_insert_sag_vertex` fits a parabola through the three
solved nodes around the turning point and inserts its apex, display-only.
That is the same physics the solver used, evaluated between its own nodes --
not invented curvature -- and it is what makes the point-load case (which
destroys mesh parity no matter what `nseg` is) come out right.

**Check what a merge reverted.** This build was assembled by merging the
fixed Cable Web into a newer Truss/Perforated-Beam tree. That tree had
`common.py`'s `_beam_gauss_solve` back as hand-rolled interpreted-Python
Gaussian elimination, with `import numpy as np` removed -- MANIFESTO Phase 1
undone. It raises no error and returns the same answers, so nothing fails;
it is simply ~40% slower on the cable-web suite, for **every tab**, since all
six call that one function. It also dropped
`test_sparse_jacobian_path_matches_dense_on_a_large_chain`, the only test
that exercises the sparse Jacobian path at all. Both restored here.

**Lesson: a merge from a branch that diverged earlier can silently revert a
shared-code optimisation, and a shared helper is exactly where that is least
visible** -- no tab owns it, no test asserts its backend, and the symptom is
"a bit slower" rather than "wrong". The whole-app sweep in
`APP_DIAGNOSIS_2026-09-05.md` now checks the backend on every run.



### w. A fix that adds a point to a polyline can create a sliver, and a sliver makes a smooth interpolator oscillate

Sec 3u ended with "before fixing a shape, compute what the shape should be
and compare numbers". This entry is the sequel, and it is a correction to
that same morning's work: **`_insert_sag_vertex`, added to cure the plateau,
introduced a visible oscillation of its own.** It shipped, and it came back
as a bug report with a screenshot.

The mechanism is worth knowing because it generalises to any
"insert a computed point into a polyline" fix:

- The apex is inserted between existing nodes. Its guard against landing on
  top of one was written relative to the **three-point window** used to fit
  the parabola (`< 0.02 * span`). That window spans TWO segments, so the test
  actually permits an apex 4% into a segment.
- 4% of a segment beside a full-length neighbour is a **sliver**.
- `_smooth_polyline` uses centred (Catmull-Rom) tangents, whose magnitude is
  set by the neighbours' spacing. Across a sliver those tangents are wildly
  out of scale, the cubic overshoots, and the hard output clamp turns the
  overshoot into direction reversals.

Measured on the built-in Example's C2 (the numbers, not the screenshot):

| | apex gap | typical gap | reversals raw | reversals drawn | overshoot |
|---|---|---|---|---|---|
| old guard | 5.70 px | 97.47 px | 1 | **3** | +2.88 px |
| new guard | — | 97.47 px | 1 | **1** | +0.00 px |

**The fix is to make the guard relative to the segment being split, not to
the fitting window:** the apex must land in the middle 60% of whichever
segment it falls in, so neither sub-segment is under 20% of the original and
no sliver is possible. Note the guard is deliberately RELATIVE -- a short
segment in a well-formed mesh has short neighbours, so absolute distance is
the wrong test.

**Two lessons.**

1. **A refinement that inserts geometry must be judged on the spacing it
   produces, not only on the value it computes.** The apex position was
   correct; the resulting *mesh* was not. `tests/` now asserts the spacing
   property directly, and separately asserts the invariant that actually
   matters to the user: **the drawn curve must never have more direction
   reversals than the solved polyline it came from.** That second test is
   the one that would have caught this before shipping, and it is cheap --
   count sign changes in the offset from each group's own chord.
2. **When a fix ships and the user reports something new in the same area,
   suspect the fix first.** The report here read as a solver or Tkinter
   problem ("is it tkinter?"), and it was neither -- it was the previous
   commit. Capturing the coordinate list immediately before
   `canvas.create_line` settled it in one run and is the right first move
   for any "the drawing looks wrong" report: it separates *what we asked Tk
   to draw* from *what Tk drew*, and it has never yet been the latter.

**Not a defect, recorded so it is not "fixed" later:** the faceted,
polygonal look of a loaded span is correct. `_build_solver_model` lumps
distributed loads at the mesh nodes, so an element between nodes carries
nothing and equilibrium makes it exactly straight -- the solved cable is a
funicular polygon of at most 8 sides. Confirmed by measurement: the
Example's C1 unloaded stretches have chord offset 0.00 px and 0 reversals.
Drawing them as smooth curves would be drawing something the solver never
computed. If a smoother picture is wanted, the honest routes are a
display-only analytic parabola between solved nodes (using that span's own
solved thrust), or a single-cable refined re-solve -- never a global mesh
increase, whose cost is measured in sec 3v. **Update, same day: there was
a third route neither of those covers, and it is the one that shipped --
keep the element count and move the elements. See sec 3x.**

---

### x. When refinement is too expensive, redistribute instead -- and then check the DRAWING, because moving the nodes moves the interpolator's ground

The follow-up report to sec 3w was sharper: the loaded cable in the built-in
Example "wobbles" and looks "polygonised", and the user's own diagnosis was
that the UDL lumping is at fault -- that a discrete UDL was producing a
stepped shape.

**The lumping was not at fault.** It had already been measured exact (spread
0.0000 N against the analytic total) in the previous pass. Driving the real
widgets and reading the solved polyline gave the actual number: on C2 the
per-node turn angles ran from **5.12 deg to 62.94 deg**. The shape is not
stepped; **its turning is concentrated.** One ~63 deg bend at the low point
between two nearly straight flanks is exactly what the eye reads as a corner.

The reason is a mismatch of variables. The mesh is uniform **in arc length**;
a loaded cable's curvature is not. Near the vertex, direction changes fast;
along the flanks, barely at all. A uniform mesh spends most of its nodes where
nothing is happening.

The obvious lever -- more elements -- is the wrong one, and it was measured
before being rejected (sec 3k's rule, applied):

| elements | max turn | min turn | ratio | solve |
|---|---|---|---|---|
| 8 | 57.09 deg | 5.47 deg | 10.4 | 0.13 s |
| 48 | ~9 deg | ~0.5 deg | **18.4** | **15.9 s** |

Refinement shrinks every corner but makes the *distribution* worse, and costs
two orders of magnitude in time. The quantity that does not move is total
turning -- 150.6 deg at 8 elements, 153.6 deg at 48. **Total turning is a
property of the shape, not of the mesh.** If the total is fixed, the only free
variable left is how it is shared out, and sharing it evenly costs nothing.

**What shipped (`_graded_breakpoints` / `_apply_mesh_grading`).** Analyze runs
twice. Pass 1 solves the uniform mesh. Its solved polyline builds a
per-element measure -- a blend of arc length and turning -- and each cable's
**free** interior breakpoints are re-placed at equal increments of it. Pass 2
solves the re-meshed model. Cable ends, junctions and load boundaries are
pinned and never move, and the free-point count inside every pinned interval
is preserved exactly, so **the graded model has identical degrees of
freedom.** Behind a "Graded mesh" toggle, on by default.

---

**The part worth the entry: it made the DRAWING worse before it made it
better, and the first metric could not see that.**

The turn-angle metric said the job was done (Example 62.94 -> 33.10 deg at
blend 0.90). A screenshot of the same case said otherwise -- a flat run and a
visible corner at the vertex, *worse* than the uniform mesh it replaced.

Both were true. `_smooth_polyline` sits between the solved polyline and the
canvas, and it was uniform-parameterised Hermite: `t` runs 0..1 on every
segment regardless of that segment's length, with centred tangents
`0.5*(p[i+1]-p[i-1])`. That is correct **only when every chord is the same
length**. Grading makes them deliberately unequal -- spacing ratios up to
13.28 were measured -- so the tangents came out badly out of scale. Measured
against the exact catenary, in screen px:

| case | solved nodes | drawn curve |
|---|---|---|
| 20/26 m, uniform | 2.02 | 2.02 |
| 20/26 m, graded (blend 0.90, old interpolator) | **1.42** | **3.84** |

The nodes got better and the picture got worse, in the same run. **A metric on
the solver's output cannot see a defect introduced downstream of the solver**
-- this is sec 3w's lesson arriving from the opposite direction.

**Fix 1 -- chord-length parameterisation.** Express the tangent per unit chord
(non-uniform Catmull-Rom) and scale it by the segment's own chord inside the
Hermite basis. It **reduces exactly to the old expression when the chords are
equal**, so the grading-off path is provably untouched -- a test asserts
agreement to 1e-9 on an equal-chord polyline. Drawn deviation on the case
above: 3.84 -> 2.43 px.

**Fix 2 -- retune `blend` on the right metric.** 0.90 had been chosen on the
solved polyline. Re-swept against drawn deviation from closed form, over a
family of slackness from 20 m/21 m to 10 m/30 m:

| blend | worst drawn dev | mean |
|---|---|---|
| off (uniform) | 13.07 px | 4.93 |
| 0.25 | 7.16 | 3.08 |
| 0.50 | 3.94 | 2.17 |
| **0.65** | **2.73** | **1.87** |
| 0.75 | 3.10 | 2.12 |
| 0.90 | 5.44 | 2.89 |

**0.65 shipped.** It is also faster (the Picture test's second pass went 5.9 s
-> 1.2 s) and better on that case's turning (95.66 -> 80.89 deg), because
over-concentrating at the vertex starves the flanks and makes the system
harder to solve as well as harder to draw.

Final, with both fixes, dof identical in every row:

| case | uniform | graded |
|---|---|---|
| built-in Example, max free-node turn | 62.94 deg | **35.58 deg** |
| built-in Picture test | 120.31 deg | **80.89 deg** |
| plain UDL 10/20 m | 57.09 deg | **32.25 deg** |
| self-weight 20/26 m | 23.72 deg | **17.25 deg** |
| self-weight web + junction | 34.20 deg | **28.71 deg** |
| **drawn dev, slack 10/20 m** | **7.93 px** | **2.31 px** |

**It still makes one reported number worse.** Grading pulls nodes toward the
vertex, so elements at the SUPPORTS grow -- and peak tension lives at the
supports. On the 20 m span / 22 m arc UDL cable against a 64-edge reference of
the same model: Tmax -4.71% uniform, **-6.20% graded** (it was -6.76% at blend
0.90, so the retune recovered part of it).

Two mitigations were built and swept at blend 0.90 before either was believed.
**Both are strict trade-offs with no sweet spot**, so neither shipped:

| knob | Tmax error | Example max turn |
|---|---|---|
| uniform (no grading) | -4.71% | 62.94 deg |
| graded, no mitigation | -6.76% | 33.10 deg |
| element growth capped at 1.35x | -6.28% | 56.24 deg |
| growth capped at 1.15x | -5.38% | 60.19 deg |
| tension-gradient term, weight 0.30 | -5.90% | 39.15 deg |
| tension-gradient term, weight 0.80 | -5.01% | 66.10 deg |

Every row buys accuracy back by giving up at least as much smoothing. The
1.35x cap is the clearest: a quarter of the accuracy recovered for five sixths
of the smoothing surrendered. Both knobs were **removed from the shipped code**
rather than left at a neutral default -- a dead parameter invites someone to
turn it on later without the sweep.

**Again the mitigation was in the wrong layer.** The solved answer is not less
accurate; H moves 0.16% and the residual improves. What degrades is the
*sample*: `_diagram_series` reports one tension per edge, so a longer end
element reports a chord further from the support. The right fix is exact, not
an extrapolation -- at a cable end the vertical component IS the support
reaction, so `T_end = hypot(H, V_reaction)`. On the graded run that is
`hypot(130.45, 110.0) = 170.64 N`, **+0.39% against the 169.94 N reference** --
seventeen times better than either mesh's edge value, and it makes the mesh
question irrelevant for the number the user reads. Recorded for the next pass;
it is a diagram change, not a solver one.

**Five lessons, in order of how much they generalise.**

1. **Measure the artefact the user reported, not the nearest quantity you can
   compute.** The user sees the drawn curve. Two rounds of tuning went into
   the solved polyline before a screenshot showed the drawing had gone
   backwards. A closed-form reference (here the exact catenary) makes the
   right metric cheap; there is no excuse for not having it.
2. **"Not enough elements" and "elements in the wrong places" look identical
   on screen and have opposite costs.** Measure the *distribution* of the
   error, not just its peak -- the peak alone argued for refinement, and the
   ratio column is what showed refinement making things worse.
3. **A change that makes the mesh non-uniform invalidates every downstream
   assumption of uniformity.** The interpolator had one, silently, in the form
   of a parameterisation. Look for what assumed evenness before shipping a
   grader.
4. **Sweep constants against the final metric, and re-sweep when the metric
   changes.** 0.90 was right for the polyline and wrong for the picture.
5. **Re-meshing reads the model, so it belongs on the main thread** (sec 3s),
   and **a second pass needs a fallback, not an error**: if the graded mesh
   fails to converge, the pass-1 result is genuine and is what the user sees,
   with the status line saying so.

**Costs.** A second solve: +0.1 s on most cases, +0.7 s on the Picture test.
Hence the toggle. Grading cannot and must not remove a kink at a point load or
a junction -- those are real. The turn metric had to be changed mid-way to
exclude pinned nodes for exactly that reason: **counting them measured the
structure instead of the discretisation** and masked the benefit entirely.

---

### y. The curve was known in closed form the whole time -- the mesh was only ever approximating something we could have just written down

Sec 3x spent a whole pass making the mesh spend its elements better, and got
the built-in Example from a 62.94 deg corner to 35.58, and the drawn curve to
within 2.31 px of closed form on a slack cable. Route 1 makes that argument
mostly moot, and the reason is worth writing down because it generalises past
this app.

**A stretch of cable under a uniform load per unit arc length hangs in a
catenary, and that curve is fixed by exactly three numbers: its two endpoint
positions and the arc length between them.** This app knows all three
exactly. The endpoints are supports, junctions or point-load nodes -- the
points a solved group is trustworthy at, as the zero-tension note in
`_draw_solver_result` already said years of sessions ago. The arc length is a
model INPUT (`target_length`), not a solved quantity.

So the curve never needed the mesh. The mesh decides how well the SOLVER
approximates it; it does not decide what the curve is.

`_analytic_group_points` therefore reads no solved tension and no solved
thrust, and inherits none of their discretisation error. Measured against
closed form, in screen px, at the same 8-edge solve:

| case | uniform | graded (3x) | analytic |
|---|---|---|---|
| 20 m span / 22 m arc | 0.98 | 1.33 | **0.00** |
| 20 m span / 26 m arc | 2.02 | 1.79 | **0.00** |
| 10 m span / 20 m arc | 7.93 | 2.31 | **0.00** |

And against the SOLVER's own answer at a high mesh, which is the check that is
not self-confirming -- the reference is the solver, not the same formula:

| case | uniform | graded | analytic |
|---|---|---|---|
| UDL, unequal support heights, vs 64 edges | 0.0651 m | 0.0558 m | **0.0016 m** |
| web with a junction and a tie, vs 20 edges | 0.1617 m | 0.3443 m | **0.0557 m** |

It also costs LESS than Route 2, which is the part that inverts the intuition:
Route 2 buys its improvement with a second nonlinear solve, Route 1 with two
bisections and a sampling loop. They are therefore wired as **exclusive**
alternatives (`curve_route`, radio, `analytic` default) -- grading the mesh
underneath an analytic curve would cost a second solve to move nodes the
curve never looks at.

**Four things worth keeping.**

1. **Before optimising an approximation, check whether the exact answer is
   available.** Two passes of mesh work (3v, 3x) went into approximating a
   curve that has a closed form, on data the app already had. The question
   "what IS this shape?" was never asked; the question "how do I mesh it
   better?" was asked twice.
2. **Derive from the inputs, not from the outputs, when you can.** The first
   design took `a = H/q` from the solved thrust. Taking the geometry route
   instead -- endpoints and arc length -- removed the dependence on H, and
   with it the 5% peak-tension discretisation error 2.4 complains about. Same
   curve, strictly better provenance.
3. **A closed form needs a gate, and the gate is the hard part.**
   `_group_uniform_load` returns None for a Variable load, a UDL covering only
   part of a stretch, a non-vertical load, or a net-upward one, and the caller
   then falls back to the polygon. **Drawing a confident curve that is the
   wrong curve is worse than drawing a visibly faceted right one** -- the
   faceted one at least looks like what it is. All six gate cases are asserted.
4. **Orientation came from the data, not from a flag.** The closed form always
   sags; the antifunicular view is handed mirrored positions and must arch.
   Rather than teach the curve about the mirror, it takes its bulge direction
   from the solved polyline it is replacing -- so both views are right for the
   same reason and cannot drift apart when the mirror changes.

**A measurement bug found on the way, worth its own line.** Route 1 first
scored 0.19-0.55 px instead of 0.00, and more sampling did not move it. The
residual was the METRIC: it measured each drawn point to the nearest reference
*vertex* rather than to the reference *curve*, which overstates the gap by up
to half the reference's own sample spacing -- larger, on a steep cable, than
the thing being measured. `_drawn_deviation_from_catenary` now measures to the
segments. **When a number will not go below a floor, suspect the ruler.**

---

### z. The 2026-09-05 roadmap, built -- and the three things building it corrected

All six planned items shipped in one pass: exact anchorage tension, the V
band, a 1 kN/m default self-weight, equilibrium force vectors, web-wide T/H/V
drawn into the geometry, and Route 1 before them. What is worth keeping is not
the feature list but the three places where doing the work contradicted the
plan that described it.

**1. The peak-tension fix was exact, and it retired a regression rather than
trading against it.** Sec 3x had to record that the graded mesh made reported
Tmax worse (-4.71% -> -6.20%) and that two mitigations were strict trade-offs.
Both of those were attempts to fix a REPORTING error in the MESH. The actual
fix is one line of statics: an edge's reported tension is the true value at
that edge's MIDPOINT, because consistent lumping puts half of each element's
load at each node. So the end value is the edge's plus exactly the half
element it is missing, `V_end = V_edge +/- q*ds/2`, `T_end = hypot(H, V_end)`.

Against closed form (`T = q*a*cosh(span/2a)` = 171.05 N):

| mesh | raw edge | corrected end |
|---|---|---|
| 8 edges, uniform | 161.95 (-5.3%) | **170.48 (-0.33%)** |
| 8 edges, graded | 159.40 (-6.9%) | **170.61 (-0.26%)** |
| 16 edges | 166.57 (-2.6%) | 170.91 (-0.08%) |

The corrected value moves **0.08% between the two meshes**, because a longer
end element lowers the edge value by precisely what the correction adds back.
That is the tell for a fix being in the right layer: it does not merely
improve the number, it makes the number stop depending on the thing that was
never supposed to affect it.

**2. A feature that draws equilibrium will tell you when your equilibrium is
incomplete.** The first force-vector pass had the selected joint's arrows
failing to close by 20 N against a 316 N junction. Not a solver error -- a
missing term: the self-weight the incident edges hang on that node.
`node_reaction()` already had it, inline. Deriving the same lumping convention
a second time is exactly sec 3j's drift, so it came out as
`node_self_weight()` and both callers use it. **The bug was found because the
feature's own correctness test was ΣF = 0 rather than "does it look right".**

**3. Two documented claims turned out to be wrong, and only checking found
them.** The 2026-09-05 report said `_load_example` pinned its own self-weight
and was immune to a default change. It did not -- both examples were merely
inheriting `_new_cable`'s 0.0, as were three taut-tie test builders whose own
docstrings say "no self-weight". All five now state their premise. And the
same report recommended Route 2 as the cheaper route; it is the more expensive
one (a second nonlinear solve, against Route 1's two bisections).

**A calibration note on scales.** The web-diagram band was first proportioned
to cable arc length. On the built-in Example -- 20 m of cable inside a 10 m
wide box -- that drew bands wider than the web. A slack cable has far more
length than space, and **what a band must not overflow is the drawing, not the
member**; the reference is the solved bounding box.

**What did not change, deliberately.** One shared scale across all cables (per
member would destroy the between-member comparison the drawing exists for);
stepped bands, not smoothed (tension is constant within an edge, and a smooth
ribbon would imply resolution the solve lacks -- sec 3w's rule); force vectors
on the selected joint only; and every new overlay off by default except the
curve route, which replaces a default rather than adding one.

**Correction, same day: the web diagram was built in the wrong place.** It was
first painted onto the editing canvas. The request was for a PARALLEL DISPLAY
-- the Vierendeel/Arch idiom of a schematic beside the model, not over it --
and the difference is not cosmetic: the editor is for building the model and
the diagram is for reading it, and bands drawn over the thing you are dragging
make both jobs worse. It now lives in its own pane (`_build_funicular_pane`)
with its own quantity selector, an antifunicular flip, and a scale slider in
the Arch tab's own percent idiom. A test asserts that opening it paints
**nothing** onto the editing canvas.

Two things that pane taught, both about scale controls:

1. **A view that refits itself to its own diagram makes a scale slider look
   inert.** Fitting to the current bands shrinks the view by exactly as much
   as the band grows. The pane fits to the geometry plus the band **at 100%**,
   so the structure holds still and the band grows against it -- which is what
   a scale control is for.
2. **A square margin wastes a wide pane on a tall structure.** Fitting to the
   100% band extent instead of to a uniform allowance is both tight and
   stable.

---

### aa. Two renderers of one solve, and the test suite that could not see the difference

The user reported that the funicular diagram disagreed with the funicular
shape. It did, by **4.2 m -- 13.8% of the web -- on the built-in Picture
test**. The audit that confirmed it also turned up two more defects, and the
common thread is worth more than any of the three fixes.

**What was wrong.** The editing canvas puts every drawn stretch through three
substitutions: a zero-tension stretch gets a nominal catenary, a uniformly
loaded one gets its exact closed form (sec 3y), and anything left gets its
true vertex inserted (sec 3v). The diagram pane, written later and separately,
did none of them -- it plotted the raw solver polygon. On the Picture test C1
has 5 of 8 edges at essentially zero tension, so one view drew a clean
catenary where the other drew a meaningless scribble.

That is **sec 3j, exactly**: the same sub-problem solved in two places drifts.
It was written down in this file years before, and it still happened, because
the second renderer did not feel like "the same sub-problem" -- it felt like a
new feature. **The tell is not that two functions look alike; it is that two
outputs must agree.**

Fix: one `_display_groups`, yielding display polylines in model coordinates,
used by both views -- including the same interpolation, so they draw the same
*line* and not merely the same points. Proved inert before it was trusted: 20
canvas scenarios captured before and after, 18 bit-identical to 0.000 px.

**The two it uncovered.**

1. **The antifunicular was drawing the funicular's shape.** The zero-tension
   substitute was cached under `(result, edges)` with **no key for which view
   asked**, so whichever drew first won -- 210-273 px out of place in the
   mirrored view, predating the pane. Adding a view key fixed that and exposed
   the deeper problem: re-deriving the mirrored view cannot be exact, because
   **every substitution here picks a DIRECTION from the geometry handed to
   it** -- the nominal catenary always hangs, the analytic fit takes its bulge
   from the solved polyline. An inclined analytic stretch came out 1.4 m from
   its own mirror. The antifunicular is a reflection, so it is now *built by
   reflecting*: exact by construction, for every renderer path, and cheaper
   (one cached solve instead of two).
2. **The band spiked on curved stretches.** A stepped value drawn as one
   outline turns every step into a radial spike -- 73.6 deg turns measured.
   One ribbon per solver edge, each at that edge's single value, meeting its
   neighbour on the curve: worst turn 2.0 deg, same data, same honesty.

**A long-standing gap, measured and left open.** Four of 34 runs never
converge: a three-cable star at a free junction, and a junction tied DOWN to
an anchor. Both stall at residual 1e-2 to 3e-2. Checked against the
pre-session code at `c734ec2` -- identical failures, identical residuals, so
not a regression. The envelope is sharp: a third member at a free junction is
fine taut and pulling up; slack, or pulling down, and the solve stalls. The
likely mechanism is that a tension-only formulation has to CHOOSE which
members are active, which is a complementarity problem and not a smooth one.
Recorded rather than patched, per sec 1.4.

**Two things not to "fix" later, both recorded because they look like bugs.**

* **End tension below edge tension is correct** where a cable's low point lies
  outside its own span -- tension then increases monotonically along it and
  the shallow end is a minimum, not a peak. The correction takes its sign from
  the edge's own solved direction rather than assuming the end is the maximum,
  which is why it gets this right.
* **H is not constant on a cable with a slack stretch.** Where T = 0, H = 0,
  and a cable with both loaded and slack portions genuinely has two thrusts.
  On every cable with no slack stretch H holds to 1e-11.

**The process lesson, which is the real one.** Both display bugs were
invisible to a suite of 147 passing tests. Every one of those tests checked a
renderer against a **property** -- deviation from closed form, no added
reversals, one shared band scale -- and not one checked the two renderers
against **each other**. The audit did exactly one new thing: it compared two
things that were supposed to be the same, and got a number for the
disagreement. **When two code paths must produce the same output, assert that
directly and exactly; property tests on each path separately will pass right
through the drift.** Now three tests, asserting equality to 1e-9 rather than
approximately, because an approximate assertion lets the two drift apart again
by small steps.

---

### ab. The models that "never converged" had no solution as posed -- a cable cannot be forced to stay taut

Sec 3aa left one finding open: four of 34 audit runs never converged, on any
code version going back to `c734ec2`. A three-cable star at a free junction,
and a junction tied DOWN to an anchor beneath it. Both stalled at residual
1e-2 rather than diverging, which is the signature of a solver sitting on
something it cannot accept.

**It was.** The probe that settled it took one run: print the per-edge length
error and tension of the best attempt.

    three-cable star, best attempt, residual 2.977e-02
      edge 8   L=2.2467  target=2.2500  err=0.0033  <b>T=1.294e-28</b>
      edge 6   L=2.4973  target=2.5000  err=0.0027  T=61.06
      edge 5   L=2.4973  target=2.5000  err=0.0027  T=71.93

**Exactly one edge at T ~ 1e-28, with L a few millimetres UNDER its target.**
That is not a solver going wrong. That is the correct slack state -- and the
solver had found it and was being told it did not count.

Every solve stage imposed

    L == target_length

as an **equality** on every edge. That is right for a taut member and wrong
for a slack one. A cable carries no compression, so a member with more length
than the gap it spans must be free to sit at `L < target` with `T = 0`. With
the equality imposed, such a model has **no solution as posed** -- no seed, no
optimiser, no amount of tuning would ever have found one, because none exists.

The constitutive law of a cable is not an equation, it is a **complementarity
condition**:

    T >= 0            target - L >= 0          T * (target - L) = 0
    (cannot push)     (cannot stretch)         (taut => L = target,
                                                slack => no tension)

encoded with the Fischer-Burmeister function `phi(a,b) = a + b - sqrt(a^2+b^2)`,
which is zero exactly when all three hold, as one row per edge in place of the
equality row. Both arguments are non-dimensionalised first, or the mix of
newtons and metres would make the root depend on the choice of units.

| topology | before | after |
|---|---|---|
| three-cable star | stalled, 2.98e-2 | **converged, 6.2e-13** |
| junction tied down | stalled, 1.03e-2 | **converged, 8.2e-11** |
| audit, all 34 runs | 30 converged | **34 converged** |

Equilibrium on the two new ones holds to 1.9e-12 and 2.9e-17 -- the answers
are not merely numerically converged, they balance.

**Three things that made this safe to ship.**

1. **Strictly additive.** The stage runs only `if best is not None and not
   best[2]` -- that is, only when every existing stage has already failed. A
   model that solves today cannot reach it. Proved rather than asserted: the
   17-topology audit re-run is byte-identical on every previously converging
   row, with exactly two rows added.
2. **A guard against a trivial "solution".** A network where EVERY member is
   slack satisfies the complementarity system for free: nothing is carried, so
   every configuration with `L <= target` is an equilibrium and the shape is
   arbitrary. That is the absence of a constraint, not an answer, and
   reporting it converged would hand back a meaningless geometry with a 1e-13
   residual attached. **The guard has to scale with the applied load**: an
   unloaded weightless network settles at tensions around 1e-7, pure optimiser
   noise, which any fixed epsilon either lets through or, set high enough to
   stop, would also reject a genuinely lightly loaded web. This is also what
   keeps the nonzero default self-weight load-bearing (sec 3z).
3. **The regression test that caught it** was the one asserting a weightless
   unloaded cable does NOT converge -- written earlier to document *why* the
   default exists. It failed the moment the new stage went in. A test whose
   job is to record a rationale earned its keep by breaking.

**And one model that genuinely cannot be built.** Of the nine variants in the
audit's envelope, eight now converge. The ninth -- a star whose two 10 m
suspension cables need the junction at `y >= 0.86` while its 6 m tie needs
`y <= 0` -- is **geometrically impossible**, and no solver can help. "Did not
converge" sends you hunting for a numerical problem that is not there, so
`_unreachable_junction_note` now says which junction cannot be reached and by
how much. It is a **necessary condition only** -- it looks at cables running
straight from a junction to a support and nothing else -- so it can never cry
wolf about a web it has not fully accounted for, which a test asserts on three
solvable webs.

**The lesson.** A solve that *stalls* at a modest residual, rather than
diverging or oscillating, is usually not a numerical problem: it is the
optimiser pressed against a constraint that the formulation will not let it
satisfy. Read the per-equation residual before reaching for a better seed or a
tighter tolerance -- five seeds and a trust-region method had been thrown at
this, and none of them could fix a formulation that had ruled the answer out.

---

## 4. Known, accepted performance characteristic (not a bug)

All three provided `cableweb_report*.xlsx` cases share the same topology
pattern: two attachment nodes, each where 3 cables meet (an indeterminate
junction — more tension unknowns than equilibrium equations at that
node). `solve_analysis`'s multi-seed fallback strategy for this case
takes roughly **20 seconds** on this hardware, converging to a residual
around `1e-8`–`1e-15` (correct, just slow to reach). This was confirmed
across all three files, not just the most complex one. If this becomes a
priority to improve, treat it as a dedicated profiling/optimization task
against the existing validated test suite — not something to touch as a
side effect of a UI fix. **Update 2026-08-29: this became a priority — see
§6, Phase 1.**

---

## 5. What's next (not done in this pass, deliberately)

This pass was scoped to: fix reported UI bugs (support visibility, wheel
zoom/pan, toolbar rendering), confirm the three provided Excel cases
still solve correctly, and write this manifesto. Not touched, and not
implied to be broken:

- The ~20s solve performance (§4) — flagged, not addressed.
- `truss_app.py`, `beam_app.py`, `arch_app.py`, and their solvers — not
  touched, per the instruction to leave other tabs alone.
- Making `_nearest_cable_point` (and the other straight-chord-based
  interaction code) follow the actual catenary shape instead of the
  chord — see §3m. Discussed and deliberately deferred as its own,
  separately-scoped piece of work, not done as a side effect of the
  display-only natural-shape change.
- Tension/thrust diagrams for cables (requested 2026-08-21, not yet
  built). Recommended approach discussed with the user: reuse the
  existing Truss/Beam tab diagram-panel pattern rather than inventing a
  new one, plot `result.tensions[eid]` against arc-length `s` per cable
  (a stepped/piecewise-linear plot, same shape of problem as the Beam
  tab's shear diagram), and derive the thrust diagram as the projected
  horizontal/normal component of the same tension data — no new solver
  output needed, this is purely a display feature on data that already
  exists in `result.tensions`.
- Auto-fitting the view (e.g. right after a successful Analyze/Form-find,
  or right when Antifunicular is toggled on) instead of requiring a
  manual Fit click — discussed alongside §3o's fix and deliberately left
  out of it, since deciding when it's OK to override a user's own
  manual pan/zoom is a separate, more opinionated UX question than
  correcting Fit's bounding box was. §3o's fix means Fit always shows
  the whole picture when the user asks for it; it does not make that
  happen automatically.
- A UI diagnostic pass specifically on the Truss/Beam/Arch tabs, in the
  same style as §2's checklist — not done, no reason to believe anything
  is wrong there, just genuinely not yet checked.

If you're picking this project up next: read this file, run the
checklist in §2, and only then start changing things.

---

## 6. Staged solver-correctness/performance plan (in progress)

A 5-phase plan was handed over for `cable_web_app.py` and
`cable_web_math.py` (Phase 4 explicitly authorizes touching the solver
itself, unlike the UI-scoped work in §3 — a different request than the
ones that produced §3's entries): Phase 0 baseline, Phase 1 numpy swap
for `_beam_gauss_solve`, Phase 2 fix the junction "kink" bug (per-segment
fixed-junction reference solve → one solve per connected component, free
junctions), Phase 3 expose a Straight/Catenary preview toggle, Phase 4
analytical + sparse Jacobian and re-tuned iteration caps, Phase 5
background-thread the Analyze button. The plan is explicit: execute in
order, one phase per commit, re-verify against a captured baseline after
each, don't combine phases. This entry covers Phases 0–1 only; 2–5 are
deliberately not started.

**Phase 0 (baseline).** Note for the record: Phase 1 was implemented
before this baseline was captured (an ordering slip against the plan's
own instructions). Recovered it after the fact from the exact pre-change
delivered zip, still on disk, rather than from memory — `test_cable_web_math.py`
7/7 pass in 15.85 s; `test_picture_like_web_regression` residual
4.60e-13; UI-level Example residual 5.40e-10 (this is the "~5.4e-10"
value the plan itself cites from `CABLE_WEB_DIAGNOSTIC.md`, confirming
the baseline snapshot is the right reference point); UI-level Picture
Test residual 9.92e-15, solve time ~15.2 s.

**Phase 1 (numpy swap).** `common.py`'s `_beam_gauss_solve` (dense,
hand-rolled, partial-pivoted Gaussian elimination in interpreted Python —
shared by every tab: truss, beam, arch, cable, cable_web, confirmed by
grep, not assumed) now delegates to `numpy.linalg.solve`. Same
input/output contract (plain Python list in, plain Python list out,
`None` on failure, `[]` for `n==0`) so every call site needed zero
changes. The original's "reject if partial-pivoting hits a pivot below
1e-12" safety check has no direct equivalent against a compiled LU
solve, which doesn't expose intermediate pivots — replaced with a
residual check (`‖Ax−b‖` small relative to `‖b‖`) that catches the same
class of unreliable solve (a near-singular system silently returning
numerical garbage) by checking the thing that actually matters — whether
the returned x is trustworthy — rather than a proxy for it.

Verified against the Phase 0 baseline above:
`test_cable_web_math.py` still 7/7, now in 9.51 s (~40% faster). Two
cases (`test_three_edge_junction_self_stress`, `test_lateral_load_at_node`)
show small (~0.1–0.3%) shifts in individual converged tension values —
expected and accepted: both are statically-indeterminate self-stress
cases whose own docstrings say the tension split isn't unique, and both
assert physics (equilibrium, pinned position) rather than a specific
tension number, so they pass unchanged. `test_picture_like_web_regression`
residual 2.52e-12 (same order of magnitude as baseline, comfortably under
its own 1e-8 assertion). UI-level, through the real Analyze pipeline:
Example residual 5.396e-10 (matches the plan's own cited "~5.4e-10"
reference almost exactly) in 2.82 s (no change — this case is too small
for the dense-solve backend to matter); Picture Test residual 9.918e-15
in 10.24 s (down from 15.2 s baseline, a genuine ~33% wall-clock
improvement on the one case in this project large enough for it to show).
Full project test suite (`common.py` is shared by every tab) still 7
passed, 2 skipped headless / 9 passed under a display.

Not started: Phase 2 (the actual junction-kink correctness fix —
architecturally the biggest piece: replaces the per-cable-segment
reference solve with one solve per connected component of the web, free
junctions instead of chord-pinned ones) through Phase 5. Stopping here
deliberately, per the plan's own "do not skip ahead or combine phases" —
Phase 2 is a materially bigger, riskier change than Phase 1 and deserves
its own dedicated pass, not a rushed continuation of this one.

**Phase 2 attempted, then deliberately stopped -- blocked, not done.**
The plan's literal instruction ("reuse solve_analysis... scaled to the
whole component") does not hold up empirically for this project's own
built-in Picture Test topology. Found along the way and fixed in passing
(harmless on its own -- see below): `_build_solver_model`'s
`reference_self_weight=True` branch referenced an undefined `chord`
variable -- a dead `NameError` waiting to happen, never hit before
because both existing call sites (`_solve_exact`, `_solve_fd`) only ever
call it with the default `reference_self_weight=False`. Fixed by
computing each SEGMENT's own chord from its two solver-node positions
and comparing PER SEGMENT (the original line compared the whole cable's
`target_total` against a per-segment `chord` that didn't exist -- not
just missing, the comparison itself was the wrong granularity). This fix
changes nothing observable today (7/7 + 2 skipped headless, 9/9 under a
display, identical to Phase 1) since the branch it's inside was never
reachable before.

With that fix in place, actually calling
`_build_solver_model(include_user_loads=False, reference_self_weight=True)`
+ `solve_analysis()` on the real, unmodified Picture Test: **does not
converge** -- residual 2.09e-2, 5.4 s (confirmed through the real app
pipeline, not just a standalone reproduction). Isolated the cause with a
series of minimal standalone models (not guesswork):
- A single free junction with 3 edges radiating to 3 supports, self-weight
  only, no point load: **converges fine** (residual 1.3e-12), at any
  weight magnitude from 1.0 to 1000.0 -- rules out "self-weight is too
  small a force for this solver's tolerances" as the cause.
- Two such junctions, entirely independent (no edge between them), in one
  model: **converges fine** (residual 5.3e-13) -- rules out "solve_analysis
  can't handle more than one indeterminate junction at once".
- Two junctions, each with 2 support edges, linked to EACH OTHER by a
  third edge that is TAUT (no slack): **converges fine** (residual
  1.1e-11).
- The same, but the linking edge has real slack (extra length beyond its
  endpoints' distance): **fails** (residual 0.27) -- and this is exactly
  the shape of the real Picture Test's C1–C3–C2 chain once self-weight
  moves the junctions off their old fixed chord position enough for any
  slack to matter.
- The real Picture Test's own exact lengths, reproduced standalone (not
  just through the app): fails identically (residual ~0.056,
  independent of iteration budget, seed quality, or scaling the nominal
  weight from 1.0 up to 1000).

Working theory, refined after a second attempt (see below), not yet
proven: not simply "a slack junction-to-junction link" as first thought —
isolated further to a junction whose own would-be equilibrium (from its
slack, self-weight-bearing edges alone) sits farther from a linked
neighbor than a taut tie to that neighbor allows, so the tie must pull
it back against its own cables' sag. That is a completely ordinary,
physically valid configuration for real tensioned structures — nothing
about it is actually infeasible — but `solve_analysis`'s existing
multi-seed/least-squares fallback (built and tuned against cases with
either a real concentrated load or a short/direct taut member, per the
passing tests already in the suite) does not reliably find its way to
that equilibrium. This is a property of `solve_analysis` itself, which
Phase 2's own instructions explicitly place out of scope ("do not touch
solve_analysis()'s ... scope is the PRE-analysis reference/preview shape
only") -- so this pass stops here rather than debug the solver under a
phase that says not to touch it.

Not done, deliberately: wiring any of the above into
`_update_reference_result()`. Doing so as originally planned would make
the Picture Test's own at-rest preview -- the project's own reference
example -- fail to converge and take 5+ seconds doing it, which is a
regression against the working per-segment behavior already in place,
not an improvement. Nothing beyond the standalone `chord` fix was
changed in service of Phase 2 this pass.

**Second attempt: a narrower, decomposed approach -- also blocked, and
this matters.** Asked to try something narrower than one big
simultaneous solve, next attempted Gauss-Seidel relaxation: hold every
junction except one FIXED at its current best-estimate position, solve
for that ONE junction alone (a single free node with fixed neighbors --
structurally identical to `test_three_edge_junction_self_stress`, the
passing test), update, move to the next junction, repeat until nothing
moves. Each individual inner solve is exactly the shape of a test that
already passes, so this looked like a safe bet.

It still fails, on the exact same real numbers, and tracing why matters
more than the fact that it failed: solved junction 5's TWO real support
edges in isolation (no tie at all) to see where they alone would put it
-- (0.2, -5.0), a substantial natural sag. The tie's target length (20 m)
turns out to be too short to reach from THAT position to junction 6's
assumed spot -- the straight-line distance is 23.24 m. So the tie isn't
some edge-case irritant sitting at the margin; it is *necessarily* taut
and *necessarily* pulling junction 5 well away from where its own cables'
self-weight would otherwise settle it, every single time, regardless of
which junction is held fixed and which is free. Decomposing the network
into one-free-node sub-solves doesn't remove that tension -- it just
relocates the exact same hard case to a smaller model, where it fails
identically (confirmed: same residual to 3 significant figures whether
the tie is given zero, tiny, or full nominal weight -- ruling out
"zero-weight edges are the problem" as an explanation, same as the first
attempt's uniform-weight test already suggested).

**Conclusion:** this is not a decomposition-strategy problem that a
different caller can route around. `solve_analysis`, as it exists today,
does not reliably solve for a junction that a taut tie holds well away
from its own cables' natural self-weight sag -- global or local, one
big solve or many small ones. That is squarely a solver-robustness
question (arguably pulling forward part of Phase 4's mandate, not
something in scope for "the same length-constrained approach
`_solve_nominal_catenary` already uses" as a caller-side alternative).
Two honest ways to actually move Phase 2 forward from here, neither
attempted this pass without a decision first:
1. Treat improving `solve_analysis`'s convergence for this specific
   taut-tie-against-self-weight case as its own dedicated task (likely
   overlapping Phase 4's analytical-Jacobian work, which may well fix
   this as a side effect of being a fundamentally better-conditioned
   formulation) -- then Phase 2 as originally written becomes viable.
2. Ship a narrower Phase 2: apply the connected-component,
   free-junction solve only where it already works reliably (a junction
   whose every neighbor is a real support, or a taut tie between two
   such junctions -- both confirmed to converge above), and leave
   junctions linked by a slack tie exactly as they render today
   (chord-pinned, the pre-existing, working behavior), clearly
   commented as a known, deliberate limitation rather than silently
   producing a worse result than before.

**Third attempt: option 1 (fix `solve_analysis` itself) -- this one
worked, and it wasn't the Jacobian that mattered most.** Asked to treat
`solve_analysis`'s convergence for this case as its own task, ahead of
wiring anything into Phase 2. Root-caused properly this time instead of
tuning around the symptom:

`solve_analysis`'s residual requires `L_e == target_length` for every
single edge, unconditionally (see `residual()`'s length-constraint row --
there is no branch for "this edge is slack, L may be less than target").
A single straight edge therefore CANNOT represent genuine slack (more
material than the span needs) at all -- it can only ever be exactly
taut. `_solve_nominal_catenary` and the real per-cable model already
know this and work around it by discretizing a slack cable into several
small straight sub-edges, so the *path* can bend to use up the extra
length even though each tiny piece is individually taut. Every attempt
at Phase 2 so far used ONE edge per whole segment (support-to-junction,
junction-to-junction) -- which is fine for a segment that turns out
taut, but geometrically asks for something impossible whenever a
segment is genuinely slack, regardless of Jacobian quality, seed
quality, or decomposition strategy. Confirmed directly: the exact
previously-failing topology (junction 5's 3 edges), rebuilt with each
segment split into several sub-edges instead of one, **converges
cleanly** (residual 6.4e-15) with the ORIGINAL finite-difference
Jacobian, no other change -- proving discretization, not solver
robustness, was the actual fix for *convergence*.

That correctly-converging discretized model took 17.5s, though -- confirmed
by profiling (`cProfile`, not a guess) that the dominant cost wasn't the
Jacobian at all: `J^T J` and `J^T f` were assembled via nested Python
generator expressions, an O(dof^3) reduction done in interpreted Python,
called on every Newton/LM trial. At dof~9 (the small test-suite cases)
this is invisible; at dof~60 (a modestly discretized multi-cable
component) it dominates completely (31 of 63 profiled seconds in that
one generator expression alone, across a 5-attempt/multi-seed run).

Two independent fixes, both verified before being relied on, not after:

1. **Analytical Jacobian** (`jacobian_analytical`, `solve_analysis`'s new
   `use_analytical_jacobian=True` default). Closed-form derivatives of
   the length and equilibrium residuals above -- the length row's
   gradient is just `-u` / `+u` at each endpoint; the equilibrium row's
   position-gradient is the standard 2D "geometric stiffness" projection
   `K = (I - u u^T)/L` (rank-1, symmetric) that any truss/cable-net
   stiffness derivation produces, and its tension-gradient is just `u`
   itself. Verified, standalone, BEFORE touching this file: built the
   residual and both Jacobians independently in a throwaway script,
   compared them numerically on the passing single-junction case, the
   failing multi-junction case, and three random perturbations of it --
   max relative disagreement 5.3e-5 in every case, consistent with
   finite-difference's own ~1e-6 step truncation error, not a
   derivation mistake. `use_analytical_jacobian=False` still selects the
   original FD path, per Phase 4's own "keep FD available behind a debug
   flag" instruction, though every case checked so far gives identical
   converged answers either way -- just faster.
2. **`J^T J` / `J^T f` via numpy instead of nested-generator Python.**
   This, not the Jacobian, was the real win for larger systems: the
   17.5s discretized case above dropped to **1.6s** with this change
   alone added on top of the analytical Jacobian (roughly 11x).

Both changes verified together against the existing suite before being
considered done: `test_cable_web_math.py` 7/7, converged tension values
identical to before either change (T0=8204.5, T2=106094.1 on the
self-stress case, matching Phase 1's own numbers exactly) -- confirming
these are genuinely the same equations solved faster, not a different
computation that happens to also converge. Full project suite now runs
in **1.8s** (down from 9.5s after Phase 1, ~15.9s at the original
baseline). Through the real Analyze pipeline: Example residual 2.66e-15
in 1.19s; Picture Test residual 1.06e-11 in **0.66s** -- down from
10.24s after Phase 1 and ~15.2s at the original baseline, roughly 15-23x
faster on exactly the "indeterminate junction" case §4 flagged as the
project's known slow path. Toolbar/width/drag/full button-and-tool
sweep re-run, unaffected. `solve_force_density` was not touched.

**Where this leaves Phase 2:** the blocker is gone -- `solve_analysis`
now both converges AND runs fast enough on a properly-discretized
connected-component model to be usable for an on-edit reference-preview
recompute. Phase 2's actual implementation (identify connected
components, build a fine-discretized model per component with free
junctions, wire it into `_update_reference_result()`, add the
requirement-6 regression check comparing new free-junction positions
against the old chord-pinned ones) has **not** been done yet this
pass -- stopping here to confirm the fix itself is solid before taking
on that remaining, still-substantial piece of work.

**Phase 2 (actual implementation) and Phase 3, done together.**

`_cable_components()`: cables joined by a shared NON-support node (an
endpoint, or an attachment) are one connected component; a shared
support does not link two cables, since a support is fixed and
contributes no positional coupling between them. `_solve_reference_component()`
builds one fine-discretized `CableWebModel` per component -- every
segment gets split into sub-edges (`nseg`, same formula as
`_solve_nominal_catenary`), **including taut ones**, not just slack
ones. That last part wasn't the original design -- see below.

A cable with no interior junction at all (one segment, both ends on a
support) keeps the original direct `_solve_nominal_catenary` call
unchanged (Phase 2 requirement 4) via a new `_update_reference_single_cable()`,
extracted from the previous single-cable-only version of
`_update_reference_result()` verbatim. Junction positions from the
component solve are stored separately
(`self._reference_junction_positions`, world-px) and used **only** by
`_draw()` to choose where to paint a junction's marker -- `n['x']`/`n['y']`
themselves are never written to, so `_point_on_chord`, s-coordinate
bookkeeping, hit-testing, dragging and the inspector all keep using the
stored position exactly as before (Phase 2 requirement 1; confirmed by
a test that checks the stored position is bit-for-bit unchanged after a
solve, not just approximately equal to some independent recomputation).

**Why taut segments get discretized too, not just slack ones:** tried
the "obvious" version first -- a taut segment as a single rigid 2-node
edge, only slack segments subdivided, matching how
`_solve_nominal_catenary` already treats a single isolated segment.
Wired into the real Picture Test through the actual app: failed to
converge, 89.7s. Debugged by rebuilding the exact same model by hand
outside the app and toggling one thing at a time (not guessing):
confirmed node/edge topology matched a standalone version that HAD
converged earlier; found that giving the taut edges nonzero weight
instead of zero made it worse (72s, still failed); found that
discretizing those same taut edges into several small rigid sub-edges
in series (still zero weight, still geometrically dead straight)
converged cleanly, 5.5s. A single rigid edge between two FREE junctions
is numerically harder for this solver than the same rigid constraint
spread across a few small sub-edges, even though both describe the
exact same final shape -- likely a conditioning/leverage effect in the
Newton/LM step, not investigated further since a working, verified fix
was already in hand. A small fixed sub-edge count for taut segments
(tried: 3, regardless of length) converged the Picture Test fine but
was markedly slower than the full nseg formula on the Example (33s vs
7s) -- so every segment now uses the same nseg formula regardless of
taut/slack, rather than trying to special-case taut ones smaller.

Verified: `test_cable_web_math.py` and the full project suite unaffected
(7/7 + 2 skipped headless, 9/9 under a display). Both built-in examples,
through the real UI: Picture Test solves in ~7.1s, Example in ~7.4s --
not instant, but this is a recompute triggered on discrete edit events
only (load an example, drag-release, dialog Apply, Undo/Redo, switching
into Catenary mode), never per-frame (Phase 2 requirement 5 was already
satisfied by the existing drag-time straight-polyline fallback from the
at-rest rendering work on 2026-08-28 -- re-confirmed here, unaffected).
New regression tests (`test_cable_web_ui_reference_shape.py`) directly
confirm requirement 6 on both built-in examples: junction 5 in the
Picture Test moves from its old chord position to a measurably different
one, below it (world-px y increases downward) -- e.g. (72.0, 0.0) versus
a solved (57.1, 104.6), a real sag, not a rounding-sized nudge. Full
toolbar/width/drag/button sweep re-run clean.

**Phase 3** (Straight vs Catenary preview toggle): two `Radiobutton`s
next to "At-rest shape", `self.reference_mode` ('straight' | 'catenary',
default 'catenary' per the plan). Catenary preview is what's described
above. Straight mode does what the name says AND skips the solve
entirely rather than just not displaying its result --
`_update_reference_result()` returns immediately when the mode is
'straight', which is what makes it "a free, instant fallback" (Phase 3
requirement 6) instead of still paying the ~7s solve cost on every edit
for a result nobody's looking at. Switching mode calls a new
`_on_reference_mode_changed()` (recompute, then redraw) rather than just
redraw, so flipping to Catenary shows the real answer immediately
instead of waiting for the next unrelated edit to trigger it. Neither
`_point_on_chord()` nor stored node positions are touched by either mode
(requirement 4; the same test that confirms Phase 2's requirement 1
covers this).

Requirement 8 (fold the old "Unloaded reference" checkbox in) was
already done on 2026-08-28, before this staged plan existed -- see that
entry above; nothing further needed here, noted for the record so it
isn't mistaken for unaddressed.

Requirement 5 (grey out the toggle while a solved result is displayed,
since neither pre-analysis mode is relevant then) is left as the
open UX question the plan itself flagged it as -- not implemented, no
decision made. Screenshotted and confirmed visually: Catenary mode shows
smooth branches meeting at each junction's real sagged position, exactly
the "before/after" the original bug report described; Straight mode
reverts to the old flat chord-pinned picture.

**Not done, deliberately, this pass:** Phase 4 (analytical Jacobian and
`J^T J` via numpy already landed as part of fixing the Phase 2 blocker
above -- what's left is specifically the sparse-matrix step and
re-evaluating the fixed iteration caps) and Phase 5 (background-thread
the Analyze button). Both remain — worth noting Phase 4's sparse step
may matter less now than the plan originally anticipated, since the
dense numpy version already brought the Picture Test's reference solve
from 17.5s to ~7s at this component's actual size; whether sparse is
worth the added complexity at these problem sizes is worth measuring
before committing to it, not assuming.

**Phase 4's remaining piece (measured, not assumed) and Phase 5, done.**

Profiled the Picture Test's ~7s reference-preview solve (49 nodes, 48
edges -- the "discretize taut edges too" fix above) before touching
anything further: the 5 primary Newton+LM seeds all genuinely fail to
converge at this size (residuals 0.37-62, plateaued, not slowly
improving -- confirmed by re-running with `max_newton=300`, identical
residuals to `max_newton=60`, so this is a real plateau, not "just needs
more iterations"). The bounded least-squares fallback (`scipy.optimize.least_squares`,
`method='trf'`) does succeed, but was using its own `'3-point'`
finite-difference Jacobian, and that FD evaluation was 8.2 of the 10.6
profiled seconds. Since it differentiates the exact same `residual`
function the primary Newton loop uses, `jacobian_analytical` applies to
it completely unchanged -- moved that function out of
`take_newton_steps` to `solve_analysis`'s own scope (a relocation, not a
rewrite: same closure variables, all still in scope) so both the Newton
loop and the fallback call the same one, and passed it as the
fallback's `jac` argument instead of `'3-point'`. Picture Test reference
solve: ~7s -> ~2s. Verified: full suite unaffected (12/12 under a
display, 7+5 skipped headless), UI-level Example/Picture Test residuals
unchanged in magnitude, full toolbar/drag/button sweep re-run clean.

Given this, the sparse-matrix step and iteration-cap retuning are left
undone for now, not because they wouldn't help, but because the actual
measured bottleneck at current problem sizes was the fallback's
Jacobian, not `J^T J`'s assembly cost or the iteration caps -- exactly
the "measure, don't assume" instruction the plan itself gave for this
phase. Worth revisiting if a much larger web makes `J^T J` (still dense
numpy, O(dof^3)) the dominant cost again.

**Phase 5** (background-thread the Analyze button): `_solve_exact` now
only builds the solver model (fast, reads `self.nodes`/`self.cables`,
main-thread only) and starts a `threading.Thread` running
`solve_analysis(model)` -- `model` is a standalone `CableWebModel`, not
the live app state, so the background thread never touches Tk or
`self.nodes`/`self.cables` directly, which would not be safe. The result
crosses back via a `queue.Queue`, picked up by a new `_poll_solve_queue`
polled through `self.after(80, ...)` on the main thread -- the standard
safe pattern, not ad hoc. A `self._solving` flag disables the
Analyze/Form-find buttons and shows an indeterminate `ttk.Progressbar`
plus a status message for the duration, and is also checked at the top
of `_canvas_press` -- the main edit path (select/drag/place) is blocked
while a solve is in progress, so a result can't come back and get
attributed to a model that changed underneath it. Documented as a
deliberate, partial scope: other toolbar buttons, dialogs, and keyboard
shortcuts are not guarded -- covering every single edit entry point
would be a much larger change than "don't freeze the GUI" asked for.
`_solve_fd` (Form-find, already fast/non-iterative, not threaded) gained
the same `self._solving` re-entrancy guard so it can't run concurrently
with a background Analyze.

Verified directly, not just "it didn't crash": timed `_solve_exact()`
itself returning in 0.004s (not the full solve duration); confirmed
`root.update()` succeeds repeatedly (49 times, in one run) while the
background thread is still working, proving the main loop stays live
rather than blocked; confirmed a synthetic canvas press while
`self._solving=True` does not change selection state; confirmed the
Analyze button's state flips disabled -> normal and the progress bar
appears -> `pack_forget()`s across the solve. Screenshotted mid-solve
(buttons visibly greyed, progress bar visible, status message shown).
One test-harness-only false alarm caught and fixed, not shipped: the
existing width-sweep regression check flagged the progress bar itself
as an "unmapped control" once a solve had run at least once in that
process -- correct (it's `pack_forget()`-ed except during a solve) and
not a real bug, just that check's own assumption that every toolbar
child is always visible no longer holding; excluded it from that check
by identity rather than loosening the check generally.

**Sparse matrices, measured properly this time (not deferred on an
assumption).** Benchmarked dense (numpy) vs sparse (scipy.sparse)
Jacobian assembly + `J^T J`/`J^T f` + linear solve, same analytical
derivatives either way, on chain topologies (the same sparsity shape a
discretized slack segment produces) from dof 16 to 3601, correctness
cross-checked at every size (`np.allclose` between the two solutions,
not just "both ran"):

| dof  | dense    | sparse  | speedup |
|-----:|---------:|--------:|--------:|
|   16 |  0.03 ms | 0.38 ms |   0.08x |
|  121 |  0.21 ms | 0.56 ms |   0.37x |
|  241 |  1.39 ms | 0.79 ms |   1.75x |
|  451 |  5.90 ms | 1.00 ms |   5.93x |
|  901 | 31.49 ms | 1.43 ms |  22.0x  |
| 1801 |199.90 ms | 2.38 ms |  84.1x  |
| 3601 |  1.38 s  | 3.96 ms | 348x    |

Crossover is real and sits around dof~240 -- sparse's own construction/
conversion overhead makes it slower below that, then the gap widens
fast. Checked against what this project actually builds today: the
Example and Picture Test's real Analyze models are dof~40-50; the
Phase-2 reference-preview discretized models (the largest thing this
app currently constructs) are dof~130-150. **All of it sits on the
dense side of the measured crossover** -- so sparse would not have sped
up anything this app does today, only added risk to a proven path, if
implemented unconditionally.

Implemented as a hybrid instead, gated on
`SPARSE_JACOBIAN_DOF_THRESHOLD = 150` -- deliberately below the
measured ~240 crossover with margin, since 240 was measured on one
topology (a long chain) and a real web's sparsity pattern could differ
enough to shift it somewhat; better to switch a bit early on a case
that's still roughly break-even than switch late on a case that's
already paying dense's O(dof^3) cost. `jacobian_analytical_sparse` is a
deliberately independent implementation (not a shared-generator
refactor of the existing, already-proven dense `jacobian_analytical`)
-- same derivatives, duplicated rather than risking the dense path for
the sake of not repeating ~60 lines. A new `_sparse_lm_solve` mirrors
`_beam_gauss_solve`'s exact safety contract (residual-checked, `None`
on an unreliable solve) for the sparse case, since `_beam_gauss_solve`
itself is dense-only (and shared with every other tab -- not a function
to make sparse-aware for cable_web's sake alone).

Verified: dense-path results are byte-identical to before this change
at every existing test's problem size (all well under the threshold),
confirming the hybrid is genuinely inert for every case already
covered. New `test_sparse_jacobian_path_matches_dense_on_a_large_chain`
builds a dof~181 chain specifically to cross the threshold and
confirms the sparse path converges to a physically sensible single-lobe
sag (same sign-change check as the wiggle-bug fix, sec 3h) -- not just
"didn't crash." Full suite 13/13 under a display, 8 pass + 5 skip
headless. Full toolbar/drag/button sweep re-run clean.

**GUI diagnostics across diverse cable-web topologies, beyond the two
built-in examples.** Both built-in examples share a similar shape (a
handful of cables, 1-2 junctions); asked to confirm the at-rest
rendering and node positions generalize, not just work on those two.
Built and checked 10 topologies programmatically (not through manual
UI clicks -- `_new_node`/`_new_cable`/`_attach_node`, the same calls the
UI's own tools make): an isolated cable with no junction; a single
cable with one dead-end junction (attached, but linking to nothing
else); two fully independent cables (confirmed as two separate
`_cable_components()`, not one); a 3-cable star at one junction; a
**loop** -- three junctions forming an actual cycle, not a tree, the
first genuinely cyclic graph exercised anywhere in this project's own
testing so far; a 5-cable star at one junction (a higher-degree
indeterminate case than anything in the existing test suite); two
supports at drastically different heights; and an intentionally mixed
taut/slack multi-support chain. Each checked for: every junction
solving to a position measurably different from (and below) its old
chord position; every catenary segment showing at most one sign change
in its sag (the same wiggle-vs-real-sag check from sec 3h and the new
sparse-path test); Analyze converging with a real applied load (not
just self-weight -- a self-weight-only, zero-user-load network has no
unique tension solution and was confirmably NOT expected to converge,
which is a property of the physics, not a bug, once traced). All 10
passed; screenshotted the loop and the 5-cable star for a visual check
beyond the automated ones, plus a full toolbar/drag/mode-toggle pass on
the loop case specifically (a support drag on a looped topology followed
by Straight/Catenary toggling, same behavior as the two built-in
examples). One thing worth recording so it isn't mistaken for a bug
later: a mixed chain with junctions between supports (`support - cable -
junction - cable - support - cable - junction - ...`) is correctly
grouped as SEPARATE components at each support, not one long chain --
a shared support doesn't couple two junctions' equilibria (it's fixed
either way), so solving them separately is not a limitation, it's the
correct and cheaper answer. Full report:
`CABLE_WEB_TOPOLOGY_DIAGNOSTIC_2026-08-31.md` (delivered alongside this
zip, not duplicated into this file).
