# Whole-app diagnosis and forward plan — 2026-09-05

**Build:** STRUCTURAL SYMULATOR SOLVER-5-9-26 (six tabs: Truss, Beam, Arch,
Cable, Cable Web, Perforated Beam)
**Method:** MANIFESTO §2 — real Tk widgets, real canvas, live measurement.
No conclusion below comes from reading code alone.
**Suite at time of writing:** 116 passed in 260 s.

---

## 0. Health summary

The app is in good shape. A sweep that launches all six tabs, invokes every
button on each, drives five window widths and parses every source file
produced **0 high-severity findings and 2 medium**.

| check | result |
|---|---|
| launch, all six tabs | 0.9–1.1 s, all present |
| buttons invoked | 113 across six tabs, **none raised** |
| first paint | non-blank on all five canvas tabs |
| responsive widths 1600→550 px | 2 tabs overflow (see F-1) |
| duplicate method definitions | none |
| dependency helpers | `_ensure_openpyxl` / `_ensure_scipy` / `_ensure_matplotlib` all present |
| `_beam_gauss_solve` backend | numpy (restored — see F-0) |
| dialogs raised | 15, all legitimate "do X first" guidance |

---

## 1. What was fixed in this build

### F-0. `common.py`'s numpy solver had been silently reverted — RESTORED

The incoming tree had `_beam_gauss_solve` back as hand-rolled interpreted
Python, with `import numpy as np` removed. This is MANIFESTO Phase 1 undone.

It raises no error and returns the same answers, so nothing visibly fails.
It is simply ~40% slower on the cable-web suite and ~33% wall-clock on the
one UI case big enough to show it — and it applies to **every tab**, because
all six call that one function. The same merge also dropped
`test_sparse_jacobian_path_matches_dense_on_a_large_chain`, the only test
that exercises the sparse Jacobian path at all.

Both restored. See MANIFESTO §3v for the general lesson: a shared helper is
exactly where a silent revert is least visible, because no tab owns it, no
test asserted its backend, and the symptom is "a bit slower", not "wrong".

### F-A. The cable plateau — two causes, neither of them the interpolator

Reported as "cables with self weight are not smooth, they plateau around the
peak or valley". The obvious reading is a bad interpolator; that reading is
wrong, and proving it wrong needed a control.

**A true catenary IS flat at its vertex.** So the flat run alone cannot
distinguish a defect from correct geometry. The control: compute the flat run
of the mathematically exact catenary for the same span and arc length at the
same on-screen scale, and compare. On the first five cases the drawn curve
was *less* flat than the truth in every one (6.4% vs 7.0%, 4.1% vs 7.8%,
0.0% vs 3.0%, 8.0% vs 10.5%, 3.1% vs 4.5%) — no defect there at all.

A 28-case sweep of that ratio found the real pattern: **every plateau had an
odd solver mesh**, 2.1×–6.3× flatter than truth; every even mesh was already
faithful (0.61–0.96×).

- **Cause A — odd `nseg`.** Two nodes sit either side of the vertex at equal
  height and the true low point between them is below both, so no
  interpolation through those nodes can reach it. The *data* is wrong, not
  the curve fitted to it. Fixed by forcing an even segment count for cables
  carrying distributed load.
- **Cause B — a point load** inserts its own breakpoint and destroys that
  parity whatever `nseg` is: 13.1% of the group flat versus 6.4% for the same
  cable unloaded. Fixed by `_insert_sag_vertex`, a display-only parabolic
  apex recovered from the three solved nodes around the turning point — the
  same physics the solver used, evaluated between its own nodes.

Result: **28/28 cases faithful**, point-load case 13.1% → 7.6%, and both
built-in examples bit-identical to before (Example 0.20 s / residual
3.55e-16; Picture Test 0.43 s / 1.98e-10).

Two things deliberately *not* done, both measured first:

- A monotone (Fritsch–Carlson) interpolator was tried and **reverted** — it
  was measurably worse (max deviation 1.55→2.11 px, 8.76→11.75 px) and fixed
  nothing, because the vertex is a solved node that every variant passes
  through exactly.
- A finer mesh generally: §3k's cliff is still real. Divisor 2.5 → 1.25 takes
  the Picture Test's Analyze from 1.2 s to **42 s**; 2.5 → 0.8 takes it to
  **240 s**. The cost is the network solve, not the mesh — the same
  refinement on a single cable is nearly free.

### F-B. Loads now draw on the antifunicular

Previously the antifunicular was the only view showing a solved shape with no
loads on it. They are now drawn at mirrored positions in their **true
downward direction** — the antifunicular is the shape carrying those same
real loads in compression, so mirroring the arrows too would draw an arch
being pulled upwards.

### F-C. Tension and thrust diagrams

Built in the Truss/Beam diagram idiom exactly as MANIFESTO §5 recommended:
`result.tensions[eid]` plotted stepped against arc length s (tension is
constant within a solver edge, so a stepped plot is the honest shape), with
thrust H as the projected horizontal component of the same data — no new
solver output. A cable selector picks the member; the pane is opt-in
(`Diagrams` checkbox) because it costs canvas height and has nothing to show
before a converged Analyze.

The diagram flags **constant H within 1%**, which is the live check that a
cable under purely vertical load solved correctly. On the built-in Example:
C1 H = 32.04–32.18 N, C2 H = 20.36–20.50 N, C3 constant — all correct.

---

## 2. Open findings

### F-1 · MEDIUM · Beam and Cable overflow their window at narrow widths

Measured: entry fields extend **117 px past the right edge** in the Cable tab
at a 900 px window, and **121 px** in the Beam tab at 700 px. Truss, Arch,
Cable Web and Perforated Beam are clean across 1600 → 550 px.

**Why:** Cable Web has `_update_responsive_sidebars()` bound to `<Configure>`,
which narrows its panels as the window shrinks. Beam and Cable have fixed-width
panels with no equivalent.

**How to fix:**
1. In `beam_app.py` and `cable_app.py`, give the right-hand panel frame a
   `<Configure>` binding on the tab root, mirroring
   `CableWebApp._update_responsive_sidebars`.
2. Below a threshold width, either reduce the panel width or set the entry
   widgets' `width=` smaller — the Cable Web version picks a width from a
   small table of breakpoints rather than scaling continuously, which avoids
   the caching trap in §3c.
3. **Verify** by re-running the sweep in this report (`appdiag.py`) — it
   reports any control whose right edge passes the window edge, per tab, per
   width. Expect 0 findings.

**Effort:** ~1 hour. **Risk:** low, layout-only.

### F-2 · MEDIUM · Three tabs have no tests at all

| tab | test files | covers |
|---|---|---|
| Cable Web | 4 | math **and** UI |
| Perforated Beam | 3 | math only |
| Truss | 1 | load signs only |
| **Beam** | **0** | — |
| **Arch** | **0** | — |
| **Cable** | **0** | — |

Beam (1 222 lines), Arch (1 671) and Cable (1 898) — 4 791 lines, a quarter of
the app — have no automated coverage whatsoever. Truss's 3 199-line UI has
none either; its single test covers `truss_math` load signs.

**How to fix**, cheapest-first:
1. **A shared smoke test for every tab** (~2 hours, highest value per hour).
   Generalise `appdiag.py`'s sweep into `tests/test_all_tabs_smoke.py`:
   construct each tab, assert a non-blank first paint, invoke every button
   with `messagebox`/`filedialog` patched, assert nothing raises and no
   control leaves the window at 1600/1200/900/700/550 px. This is what would
   have caught F-1 automatically.
2. **Math-level tests for Beam, Arch and Cable** (~1 day). Follow
   `test_cable_web_math.py`'s shape: a handful of closed-form cases
   (simply-supported UDL, cantilever point load, a parabolic arch under
   uniform load, a single-cable catenary) checked against hand calculations,
   plus a global-equilibrium assertion (ΣR + ΣP ≈ 0) on each.
3. **Then** UI-level tests for whichever tab is being changed next — do not
   write them all speculatively.

### F-3 · MEDIUM · A running at-rest preview slows a concurrent Analyze

Carried over from the 2026-09-04 diagnosis, unchanged. Two CPU-bound Python
threads convoy on the GIL: Analyze takes 1.56 s alone but **21.6 s** alongside
a running Catenary preview. Mitigated (a preview will not *start* while a
solve is running), but a preview already in flight cannot be cancelled.

**How to fix:** add an optional `should_continue=None` callback to
`solve_analysis`, checked once per Newton iteration and once per fallback
seed; return the current iterate marked non-converged when it returns False.
Have `_update_reference_result` pass a closure that compares the request
token. Purely additive — default `None` preserves current behaviour exactly.
This is MANIFESTO §1.4 territory (touching the solver), so it wants its own
change, its own test, and a residual comparison on both built-in examples
before and after.

**Effort:** ~half a day. **Risk:** medium — it touches `cable_web_math.py`.

### F-4 · LOW · `cable_web_app.py` is 4 010 lines

The largest module in the app, now holding the editor, the solver-model
builder, three rendering modes, the diagram pane, Excel I/O, undo/redo and
two background-solve pipelines. Nothing is wrong with it, but it is the file
every future Cable Web change has to be made in.

**How to fix, if and when it becomes painful:** extract in this order, each a
separate change with the suite green in between —
`cable_web_render.py` (drawing only, no state), then `cable_web_excel.py`
(import/export), then `cable_web_diagrams.py`. Do **not** extract the solver
model builder or the background-solve plumbing; they are entangled with app
state by design and MANIFESTO §1.1 wants that boundary left where it is.

### F-5 · LOW · Silent `except Exception` density in `cable_web_app.py`

17 occurrences, the highest in the app (next is `common.py` with 6). Each can
hide a real failure — the SciPy bug found on 2026-09-04 was exactly this
pattern, a swallowed `ImportError` presenting as a physics failure.

**How to fix:** not a bulk change. Each time you touch a function containing
one, narrow it to the exception actually expected, and add a status-bar
message on the path that is meant to be user-visible. The two that matter
most are already done (the at-rest preview now reports which component
failed and why).

---

## 3. Suggested order of work

1. **F-2 step 1** — the shared all-tabs smoke test. Cheapest, catches F-1
   and anything like it automatically, and is the safety net every later item
   leans on.
2. **F-1** — the Beam/Cable responsive layout. Small, visible, and now
   guarded by step 1.
3. **F-2 step 2** — math tests for Beam, Arch and Cable, so those three tabs
   stop being the part of the app nobody can change safely.
4. **F-3** — the cooperative-cancel hook, once there is coverage to change
   the solver against.
5. **F-4 / F-5** — opportunistically, never as a standalone refactor.

## 4. How to re-run this diagnosis

`appdiag.py` (in the session scratchpad, worth committing to `tests/tools/`)
takes the app root and an output directory:

```text
python appdiag.py "STRUCTURAL SYMULATOR SOLVER-5-9-26" diag_out
```

It writes `log.txt` and a machine-readable `findings.json`. It is safe to run
repeatedly — it patches `messagebox`, `filedialog` and `Toplevel.wait_window`
so no dialog can block it, which is MANIFESTO §2's checklist item 3 and the
reason an apparent "hang" during testing is nearly always the harness, not
the app.
