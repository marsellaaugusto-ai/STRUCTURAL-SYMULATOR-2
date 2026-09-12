# Cable Web — root-cause diagnosis and fix guide

**Build tested:** `structural_simulator_v15_fixed15 (1)` · `apps/cable_web`
**Date:** 2026-09-04 · Windows 11 · Python 3.13.2 · numpy 2.5.2
**Method:** MANIFESTO §2 — real Tk windows, real widgets, live canvas
inspection and screenshots. No code in the repository was modified; every
measurement was taken against a copy.

**Coverage:** 6 purpose-built topologies (every load type, driven through the
real Load dialog's widgets), 4 controlled A/B variants, both built-in
examples, with and without SciPy. Existing suite: 13/13 pass (461 s).

---

## STATUS: all five fix-guide steps are implemented and verified

Applied to this tree on 2026-09-04, same day as the diagnosis. Measured
after-values, not expected ones:

| | before | after |
|---|---|---|
| Degree-3 star, Analyze | FAILED, residual 3.37e-02 | converged, 4.30e-14 |
| Build a 3-cable web (Catenary) | 90.33 s of frozen UI | 1.90 s |
| Build a 3-cable web (Straight, now default) | — | 0.05 s |
| Event loop during a background preview | 1 callback in 48.9 s | 626 callbacks |
| Missing SciPy | "did not converge" | names the package + install command |
| Six rapid edits | one solve queued per edit | 2 solves (coalesced) |
| Example Analyze | 0.13 s, residual 2.66e-15 | 0.20 s, residual 3.55e-16 |
| Picture test Analyze | 0.41 s, residual 1.98e-10 | 0.41 s, residual 1.98e-10 |
| Test suite | 13 tests, 461 s | 30 tests, 127 s |

Files changed: `common.py` (`_ensure_scipy`), `apps/cable_web/cable_web_math.py`
(`MissingSolverDependency`), `apps/cable_web/cable_web_app.py` (the rest),
`requirements.txt` (new), `REPORTS AND GUIDES/README.md`,
`REPORTS AND GUIDES/MANIFESTO.md` (§3r, §3s, changelog),
`tests/test_cable_web_diagnosis_fixes.py` (new, 17 tests),
`tests/test_cable_web_ui_reference_shape.py` (updated for the threaded API).

**One trade-off worth knowing about.** Threading converts a freeze into
contention; it does not create throughput. Two CPU-bound Python threads
convoy on the GIL: Analyze takes 1.56 s alone but 21.6 s alongside a running
at-rest preview. Mitigated where it can be (a preview will not *start* while
`self._solving`, and `_poll_solve_queue` releases it afterwards), but a
preview already in flight cannot be cancelled without adding a
cooperative-cancel hook inside `solve_analysis` — §1.4 territory, and
deliberately left alone. This is the other reason Straight is now the
default.

---

## 0. Summary

The GUI hypothesis is right, and it is also incomplete. Two of the three root
causes *are* in the GUI layer — but not in the layout, the canvas, Fit,
hit-testing, dragging or the redraw wiring. Everything §3 of the manifesto
fixed has stayed fixed (verified, see §4).

Three independent defects, each sufficient on its own to make the tab look
broken:

1. **SciPy is not installed, and every multi-cable web depends on it
   absolutely.** The Newton/LM solver never converges on its own — not even
   on the app's own *Example*. The failed import is swallowed silently and
   surfaces as "did not converge".
2. **The default at-rest *Catenary* preview runs a full network solve
   synchronously on the Tk main thread, on every edit.** 90 seconds of dead
   UI to build a three-cable web, for a picture that changes nothing about
   the analysis.
3. **Even with SciPy, `Analyze` fails reliably whenever a cable reaches the
   solver as a single rigid edge.** The other solve path already learned
   this (MANIFESTO §6); `_build_solver_model()` never did.

---

## 1. Root cause 1 — SciPy is a hard, undeclared, missing requirement

`cable_web_math.py:1020` · `common.py:18`

### Symptom
"✕ Exact analysis did not converge" on essentially every web with a
junction, including both built-in examples. The at-rest Catenary preview
draws nothing but straight chords. No message ever mentions a package.

### Mechanism
All five Newton/LM seeds in `solve_analysis` plateau far above the 1e-9
tolerance on real networks. Every successful analysis in this entire test
run came from the *fallback*, `scipy.optimize.least_squares`. Its import
sits inside a bare `try/except Exception` whose only reaction is a `print`
guarded by `verbose` — which is `False`. An `ImportError` is therefore
indistinguishable, to the user, from genuine non-convergence.

`common.py` ships `_ensure_openpyxl()` and `_ensure_matplotlib()`
auto-installers. There is no `_ensure_scipy()`, no `requirements.txt`, and
the README names no dependency at all. (`common.py` also imports `numpy`
unguarded at module scope — the whole five-tab app dies without it.)

### Evidence

```
Built-in Example, verbose solve_analysis:
  seed [as-drawn]                        -> converged=False  residual=1.356e-01
  seed [as-drawn+feasible-tensions]      -> converged=False  residual=4.250e-01
  seed [force-density(q=characteristic)] -> converged=False  residual=2.078e-02
  seed [force-density(q x0.1)]           -> converged=False  residual=1.806e+01
  seed [force-density(q x10)]            -> converged=False  residual=4.166e-01
  bounded least-squares [best]           -> residual=2.663e-15   <- SciPy. Every time.
  FINAL converged=True (seed: bounded-least-squares)
```

```
Your interpreter — C:\Users\Usuario\AppData\Local\Programs\Python\Python313
  numpy       present
  scipy       MISSING
  openpyxl    MISSING   (auto-installs on first Excel use)
  matplotlib  MISSING   (auto-installs)
```

Without SciPy: both built-in examples FAIL; 4/4 hand-built network
topologies FAIL; the at-rest preview returns `paths=[]` for every networked
component.

### Nuance
A single cable between two supports still solves without SciPy — which is
exactly why this reads as intermittent rather than as a missing dependency.
The moment a junction or a second cable enters the model, nothing converges.

---

## 2. Root cause 2 — the at-rest preview blocks the Tk main thread

`cable_web_app.py:2067` (`_update_reference_result`), called from `:1225`
(`_new_cable`), `:1153` (`_canvas_release`), `:1440`, `:1448`, `:1531`,
`:2896`, `:2997`, `:3049`, `:3069` (`_restore_snapshot`), `:3214`

### Symptom
The window stops repainting and Windows greys it out as "Not Responding"
after clicking *Example*, after releasing a dragged support, after Undo,
after Redo, after applying a cable length. It comes back, so it reads as a
hang that resolves rather than as a slow calculation.

### Mechanism
`_update_reference_result()` calls `solve_analysis` on a fine-discretised
network model, synchronously, from the calling thread. Phase 5 threaded
`_solve_exact` (the *Analyze* button) and left this one alone — but this one
is far more expensive and fires far more often. Catenary is the default.

### Evidence

Same 12-step build sequence, same machine, only the At-rest mode differs:

| Action                                        | Catenary | Straight |
|-----------------------------------------------|---------:|---------:|
| attach both junctions, redraw                 | 21.52 s  | 0.00 s   |
| drag support S1 (press + 12 moves + release)  | 23.32 s  | 0.02 s   |
| Undo                                          | 21.81 s  | 0.00 s   |
| Redo                                          | 23.45 s  | 0.00 s   |
| **TOTAL to build a 3-cable web**              | **90.33 s** | **0.04 s** |
| Analyze afterwards                            | 1.31 s   | 1.21 s   |
| Analyze residual                              | 7.22e-09 | 7.22e-09 |

The 90 seconds buy a preview drawing only. The analysis is identical.

Is it really a freeze, or just slow? Counting timer callbacks serviced:

```
  Analyze button (background thread)      0.19 s   after() callbacks serviced: 3
  At-rest Catenary preview (main thread) 48.90 s   after() callbacks serviced: 1
                                                   ^ only the one already queued
```

Other blocking measurements (min–max across runs; the fallback's seed loop
runs to a variable depth, so the same click costs 20 s one time and 150 s
the next):

| Action                                   | With SciPy      | Without SciPy | Preview produced |
|------------------------------------------|-----------------|---------------|------------------|
| Click *Example*                          | 15.2 – 64.7 s   | 15.2 s        | 3 paths / **0**  |
| Click *Picture test*                     | 20.5 – 153.2 s  | 16.4 s        | 3 paths / **0**  |
| Toggle Straight → Catenary               | 155.6 s         | —             | 3 paths          |
| `_update_reference_result()`, Example    | 48.9 – 196.1 s  | 0.3 s         | 3 paths / **0**  |
| 3-cable star, slack tie                  | 43.6 s          | 0.3 s         | **0 paths, both**|

### Worse
When the component solve fails, the entire cost is paid and then discarded
by a blanket `except Exception` that clears the caches and says nothing.
Measured: a 3-cable star with a slack tie spent **43.63 s** and produced
`paths=[]` — 43 seconds of frozen window for zero pixels and zero
explanation. Without SciPy this is the *normal* path.

### Already visible in your own suite
`pytest -q` takes 461 s, and 263 s of it is one test —
`test_example_junction_moves_off_the_old_chord` — which does nothing but
call `_load_example()`.

---

## 3. Root cause 3 — a single rigid solver edge will not converge

`cable_web_app.py:1627` (`_solver_breakpoints`)

### Symptom
Some perfectly ordinary webs analyse instantly; others, differing only in a
cable length, fail at residual 1e-2. There is no pattern the user can see,
because the thing that differs is invisible in the UI.

### Mechanism
`_solver_breakpoints()` deliberately refuses to subdivide a cable that has
no self-weight, carries no load, and is not slack:

```python
needs_mesh = c['w'] > 0.0 or target > chord + 1e-9
if include_user_loads:
    needs_mesh = needs_mesh or any(l['cable'] == cid for l in self.loads)
```

Its comment calls this an optimisation — *"a load-free cable such as a short
tie between two web junctions should remain one solver edge […] the old code
subdivided every cable, which […] made small web examples needlessly
ill-conditioned."* For this solver, that is exactly backwards.

The other solve path already knows this. `_solve_reference_component()`
subdivides *every* segment including taut ones, and MANIFESTO §6 explains
why at length: *"a single rigid edge between two FREE junctions is
numerically harder for this solver than the same rigid constraint spread
across a few small sub-edges."* That finding was never carried into
`_build_solver_model()` — the model the *Analyze* button actually uses.
**This is §3j of the manifesto happening again.**

### Evidence
Four topologies, each solved twice. The only difference is whether that one
cable is subdivided — same lengths, same loads, same geometry.

```
                                   AS SHIPPED                 SUBDIVIDED
star, tie exactly taut (8.0)   FAIL 3.374e-02 1.34s   ->  OK 4.298e-14 0.08s
star, tie shorter than chord   FAIL 1.944e-03 0.95s   ->  OK 9.257e-13 0.07s
twin cables + taut tie         FAIL 4.417e-02 5.32s   ->  OK 3.502e-14 0.54s
junction tied by taut hanger   FAIL 2.194e-02 0.27s   ->  OK 3.601e-09 0.17s
                                                          4/4 fixed, 3-20x faster
```

In the last case the abandoned iterate reported `Tmax = 3.08 N` where the
true answer is `132.5 N`. The app correctly refused to draw it — invariant
§1.2 is holding — but the user simply sees a failure.

---

## 4. The six test topologies

Built through the same calls the UI's own tools make, with every load entered
through the real Load dialog's widgets (combobox, entries, *Add load*
button), not by appending dictionaries. At-rest set to Straight so the
numbers measure the solver, not §2.

| # | Topology | Loading | Analyze | Residual | Verdict |
|---|----------|---------|--------:|---------:|---------|
| 1 | 1 cable, 2 level supports, 12 m over a 10 m span | point 200 N at midspan | 0.12 s | 2.13e-10 | correct |
| 2 | 1 cable, supports 5 m apart in height, self-weight 5 N/m | full-length UDL 8 N/m | 0.12 s | 7.43e-12 | correct |
| 3 | degree-3 star, 3 cables at one free junction, tie exactly taut | point 150 N + UDL 6 N/m | 1.74 s | 3.37e-02 | **FAILS — §3** |
| 4 | twin suspenders, 2 attachment junctions, tie shorter than its chord | variable q(s)=4+2s, point 120 N | 228.4 s | 7.15e-08 | **accepted, absurd** |
| 5 | cyclic web — 3 junctions in a closed triangle, 3 stays | UDL 12 N/m + horizontal 90 N | 0.92 s | 4.31e-16 | correct |
| 6 | cable + interior junction + hanger to a lower anchor | point + UDL + custom-angle 60 N | 0.66 s | 8.32e-09 | correct |

Global equilibrium (ΣR + ΣP) was checked on every converged case: residual
force ≤ 3e-6 N throughout. Slack members correctly report T ≈ 0 and zero
reaction.

### Case 4 deserves its own note

Case 4 prescribes the tie shorter than the straight distance between its two
junctions. `_validate_model()` raised no objection — "✓ Model is
structurally ready." The solve then ran for **228 seconds** and was accepted
as converged via the relaxed `practical_tol = 5e-7` band, reporting
**313 kN of tension and 313 kN support reactions under 372 N of applied
load**, and drawing one cable folded into a closed teardrop on itself.

That band exists for a good reason (`CONVERGENCE_FIX_V11.md`) and its
residual test is satisfied honestly. What is missing is any check that the
*answer* is physical. A cable prescribed shorter than its own chord is the
same condition the at-rest renderer already flags in amber as "can't reach
at this length" — the validator just never looks.

---

## 5. Two smaller defects

### 4. `_result_user_node_positions` is defined twice — `:2488` and `:3219`

The one at line 2488 returns a *set of node ids* and is dead. The one at
3219 returns the actual solved-position mapping and wins, purely because it
comes later in the file. Today the behaviour is correct. Any refactor that
reorders these two silently replaces the funicular node placement with a set
of integers. Delete line 2488's copy.

### 5. `_zero_tension_shape_cache` is keyed on `id(result)` — `:2637`

CPython reuses object addresses after garbage collection. When a previous
`CableWebResult` is collected and a new one lands at the same address, a
cache entry `(id(result), tuple(eids))` from the old solve can be served to
the new one — and the edge-id tuples *do* repeat, because edge numbering
restarts at 1 for every model. The result is a stale display curve on a
fresh analysis. Key it on a monotonic counter bumped in
`_poll_solve_queue`, or clear the cache there.

---

## 6. Ruled out — do not spend time here

Each of these was tested directly, not assumed:

- **Toolbar layout** — 0 unmapped, 0 off-screen controls at 1600 / 1200 /
  900 / 700 / 550 px. §3c–e stayed fixed.
- **First paint** — 105 canvas items present immediately after
  construction, before any user action. §3p holds.
- **Canvas `<Configure>`** — a 1500→900 px resize redraws (135→95 items).
- **Fit view** — content lands inside the viewport in funicular,
  antifunicular and both-on modes. The apparent overflow is the
  antifunicular symmetry line, drawn edge-to-edge by design, plus the
  grid's intentional one-step padding. §3o holds.
- **Hit-testing and drag** — all 6 nodes selected at centre and 3 px
  off-centre; support drag moved the model and the drawing together. §3g
  and §3l hold.
- **Toolbar buttons** — every button invoked; none raised. The Load dialog
  accepted Point, UDL and Variable `q(s)` through its real widgets.
- **Excel round-trip** — export → clear → import preserved 6 nodes /
  3 cables / 2 loads, and re-Analyze returned the identical residual.
- **`_beam_gauss_solve`** — suspected as a hidden failure source
  (its residual acceptance test is scaled by ‖b‖ only). Instrumented and
  cleared: 0 rejections out of 1040–1210 calls per run.
- **Hiding bad results** — every non-converged solve left the canvas
  showing only at-rest geometry, no funicular colours drawn. Invariant §1.2
  intact.

---

## 7. Fix guide

Ordered by how much each one unblocks, and written so each step is
independently verifiable before the next is started. Steps 1 and 2a are
small and give back a usable app within minutes; step 3 is the real
engineering.

### Step 1 — install SciPy, then make its absence impossible to miss

```
py -m pip install scipy openpyxl
```

Then close the hole. Add `_ensure_scipy()` to `common.py` beside the two
installers already there:

```python
def _ensure_scipy():
    try:
        import scipy.optimize
        return True
    except ImportError:
        pass
    try:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', 'scipy', '--quiet'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import scipy.optimize
        return True
    except Exception:
        return False
```

And in `cable_web_math.py`, stop swallowing the import — separate "SciPy is
absent" from "the maths did not converge":

```python
    if best is not None and not best[2]:
        try:
            from scipy.optimize import least_squares
        except ImportError:
            raise RuntimeError(
                'Cable Web needs SciPy for networks with junctions.\n'
                'Install it with:  py -m pip install scipy')
        try:
            ...
```

Add a `requirements.txt` (`numpy`, `scipy`, `openpyxl`) and name it in the
README.

**Verify:** load *Example*, click Analyze — expect converged, residual
≈ 2.7e-15. Then temporarily rename your `scipy` folder and confirm you get
the install instruction, not "did not converge".

### Step 2 — stop the at-rest preview from blocking the main thread

**2a — change the default (one line, immediate relief).** In
`CableWebApp.__init__`:

```python
self.reference_mode = tk.StringVar(value='straight')   # was 'catenary'
```

Catenary stays one click away. This alone takes the 3-cable build from
90.33 s to 0.04 s with no change to any analysis result.

**2b — thread it, exactly as Phase 5 threaded Analyze.** The safe pattern is
already in this file; reuse it rather than inventing a second one.

1. Split `_update_reference_result()` into a main-thread part that builds
   the per-component `CableWebModel`s, and a worker that runs the solves.
2. Return results over a `queue.Queue`, collected by an `after(80, …)`
   poller, mirroring `_poll_solve_queue`.
3. Stamp each request with an incrementing token and discard any result
   whose token is stale — the model can change several times while one
   preview is still running.
4. Coalesce: an edit arriving while a preview is in flight should cancel and
   re-queue, not enqueue a second solve. Straight polylines are the honest
   thing to draw meanwhile — the drag-time fallback already does exactly
   this.

**Do not skip:** `_update_reference_result()`'s blanket `except Exception`
currently discards a failed component solve silently. Once threaded, set a
status message ("At-rest preview unavailable for this web") so a 40-second
computation that produces nothing at least says so.

**Verify:** re-run the editing sequence on Catenary and confirm the window
keeps repainting. Objective check: schedule a repeating `root.after(50, …)`
counter and confirm it keeps ticking during the preview — today it services
exactly one callback in 48.9 s.

### Step 3 — subdivide every cable in `_build_solver_model`, not just slack ones

In `_solver_breakpoints()`, delete the `needs_mesh` condition and always
apply the mesh:

```python
# Every cable is subdivided, including taut and unloaded ones. A single
# rigid 2-node edge is numerically much harder for solve_analysis than the
# same constraint split into a few sub-edges -- the identical finding
# _solve_reference_component() is already built on (MANIFESTO sec 6).
# Measured 2026-09-04: 4/4 previously-failing webs converge, 3-20x faster.
nseg = max(4, min(8, int(math.ceil(L / 2.5))))
for k in range(1, nseg):
    pts.add(L * k / nseg)
```

Delete the stale comment above it that describes the old behaviour as
desirable, and record the reason in MANIFESTO §6 — this is the second time
the project has learned it, and §3j exists precisely to stop a third.

**Check the cost before committing.** This adds free nodes to every model.
In the four measured cases it made solves *faster* (5.32 s → 0.54 s on the
largest), but the §3k cliff is real: time the two built-ins and the three
`cableweb_report*.xlsx` fixtures before and after, and keep the numbers. If
some large web regresses, subdivide only cables whose two endpoints are both
free rather than reverting.

**Verify:** build the degree-3 star — supports at (0, 8), (14, 8), (7, −6),
free junction at (7, 2); cables 10 m, 10 m and 8 m to the junction; a 150 N
point load at s = 9 on the first and a 6 N/m UDL on the second. It fails
today at 3.37e-02 and should converge at ~1e-14. Then re-run `pytest -q` —
13/13, with the residuals in `test_cable_web_math.py` unchanged.

### Step 4 — make `_validate_model()` catch geometrically impossible cables

- **Before the solve:** if `length_override < chord` for a cable whose
  endpoints are both supports, that is an error, not a warning — the model
  has no solution. If either endpoint is free, warn: "C3 is prescribed 14 m
  but its endpoints are 20 m apart; the junctions will be pulled together
  under very high tension."
- **After the solve:** when a result is accepted only through the relaxed
  `practical_tol` band, compare `max(tensions)` against the total applied
  load. Two or three orders of magnitude apart is not a converged funicular;
  say so in the validation panel rather than drawing it.

**Verify:** case 4 above — tie 14 m between junctions 20 m apart — must warn
before the solve and flag the 313 kN result afterwards, instead of reporting
a clean "Analysis converged".

### Step 5 — housekeeping

- Delete the dead `_result_user_node_positions` at line 2488.
- Re-key `_zero_tension_shape_cache` off `id(result)`.
- Extend the `self._solving` guard. It covers `_canvas_press` and the two
  solve buttons; `_new_cable`, the dialogs, Undo/Redo and the example
  loaders all still mutate the model mid-solve. The manifesto documents this
  as deliberate partial scope — reasonable when Analyze took a second, less
  so once step 2b puts a second background solve in flight.
- The test suite spends 461 s, 458 s of which is the Catenary preview. After
  step 2a it drops to seconds, which makes it something that gets run.

---

## 8. Regression tests worth adding

1. **The taut-edge case.** Assert `_solver_breakpoints()` never returns
   exactly two points for a cable in a multi-cable model, and that the
   degree-3 star converges below 1e-9. This is the test that would have
   caught root cause 3.
2. **The dependency.** A test that imports `scipy.optimize` and fails loudly
   if absent, so the environment problem surfaces at `pytest` time instead
   of as a physics result.
3. **The freeze.** Assert `_update_reference_result()` returns in under, say,
   200 ms — measuring the promise (the main thread stays free), not the
   solver's speed.

---

## 9. Lesson for MANIFESTO §3

Proposed new entry, in the same spirit as §3j:

> **A numerical lesson learned in one solve path must be carried to every
> other solve path that builds a model of the same kind.** §3j recorded the
> display-code version of this: the same sub-problem implemented twice will
> drift. The solver-side version bit harder. MANIFESTO §6 established, with
> direct measurement, that a single rigid 2-node edge between free nodes is
> much harder for `solve_analysis` than the same constraint split into
> sub-edges, and `_solve_reference_component()` was built on that finding.
> `_build_solver_model()` — the *other* place this project builds a
> `CableWebModel` — kept the opposite rule, and kept it as a documented
> "optimisation", so nobody re-examined it. Whenever a finding about the
> solver's own conditioning is recorded, grep for every `CableWebModel()`
> construction site and check each one against it, in the same pass.
