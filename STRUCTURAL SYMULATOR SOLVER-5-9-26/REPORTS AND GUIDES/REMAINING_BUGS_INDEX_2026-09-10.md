# What remains unfixed — re-diagnosis of 2026-09-10

A full re-run of the 2026-09-05 diagnosis against the current tree, plus fresh
discovery on everything built since. **Cable Web excluded by request.**

**Tree diagnosed:** `STRUCTURAL-SOLVER-repo/STRUCTURAL SYMULATOR SOLVER-5-9-26`
(git-clean at `9e3b738`). The parallel `solver/` working copy differs only in
the `cirsoc_301` import path — content-identical otherwise, so every finding
below applies to both.

**Baseline:** `pytest -q` → **809 passed in 288 s**, 0 failed (was 157 on
2026-09-05).

**Method:** MANIFESTO §2 — real widgets, real canvas, live measurement, closed
forms, and screenshots for anything about what is drawn. Nothing below is
inferred from reading code alone.

---

## 1. Scoreboard against the 2026-09-05 reports

| # | finding | severity | status |
|---|---|---|---|
| **T-1** | Truss panel controls vanish when narrow | MED | ✅ **fixed** |
| **T-2** | `_draw_diagrams_legacy_overview` dead code | LOW | ✅ **fixed** (removed) |
| **T-3** | Truss dead imports | LOW | ✅ **fixed** (pyflakes clean) |
| **T-4** | Truss has no math tests | LOW | ✅ **fixed** (`test_truss_math.py`, 11 tests) |
| **B-1** | Fixed–fixed beam will not solve | **HIGH** | ❌ **OPEN** |
| **B-2** | ▶ Analyze unmapped below 1300 px | HIGH | ✅ **fixed** (verified by screenshot) |
| **B-3** | Load arrows drawn at constant length | MED | ❌ **OPEN** |
| **B-4** | Reversed distributed load silently ignored | MED | ❌ **OPEN** |
| **B-5** | Coordinates beyond L silently extend the mesh | MED | ❌ **OPEN** |
| **B-6** | Beam dead imports | LOW | ❌ **OPEN** |
| **B-7** | Beam has no physics tests | LOW | ❌ **OPEN** |
| **A-1** | Arch layout | MED | ✅ **fixed** (small residual, §3) |
| **A-2** | `ArchModel(n_elem=0)` → ZeroDivisionError | LOW | ❌ **OPEN** (not user-reachable) |
| **A-3** | Arch dead locals / imports | LOW | ❌ **OPEN** |
| **A-4** | Arch has no physics tests | LOW | ❌ **OPEN** |
| **C-1** | Max cable tension under-reported | MED | ❌ **OPEN** — and now demonstrably visible |
| **C-2** | Cable layout | MED | ✅ **fixed** |
| **C-3** | Cable has no physics tests | LOW | ❌ **OPEN** |
| **C-4** | Cable dead locals / imports | LOW | ❌ **OPEN** |
| **P-1** | Missing `abs()` → wrong M for uplift ramps | **HIGH** | ✅ **fixed** |
| **P-2** | Zero-resultant trapezoid → zero reactions | MED | ✅ **fixed** |
| **P-3** | Reversed distributed load inverted | MED | ✅ **fixed** |
| **P-4** | Degenerate sections accepted | LOW | ✅ **fixed** |
| **P-5** | Perforated Beam dead locals | LOW | ❌ **OPEN** (different ones now) |

**12 of 24 closed.** Everything in Truss and Perforated Beam is closed. Every
correctness bug that remains is in **Beam** and **Cable**.

### New findings from this pass

| # | finding | severity |
|---|---|---|
| **A-5** | Arch diagram captions collide; FIBRE STRESS header is illegible | MED |
| **A-6** | Arch point load outside the span is silently snapped to a support | MED |
| **A-7** | Arch distributed load wholly outside the span silently contributes nothing | LOW |
| **B-8** | Beam moment-diagram caption collides with its own max/peak labels | LOW |
| **C-5** | Cable reports `converged` for a zero-tension (H ≈ 0) state | LOW |
| **C-6** | Cable end-station labels collide with captions and axis ticks | LOW |

---

## 2. Verified still correct — do not re-check these

Every solver was re-validated from scratch against closed forms on the current
code. **All five pass.**

| tab | checks | worst error |
|---|---|---|
| Truss | triangle truss, Warren symmetry, method-of-joints residual at every free node, rigid-rod cantilever vs `BeamModel`, rigid rod + UDL | 1.1e-13 (joints) |
| Beam | SS+UDL, cantilever tip, propped cantilever, 2-span continuous | 2.8e-4 |
| Arch | 3-hinged H = wL²/8f, crown P → H = PL/4f, funicular max\|M\|≈0, M=0 at the hinge, wind, fixed supports | 2.5e-14 |
| Cable | parabola, catenary (H and sag), midspan point load | 1.4e-5 |
| Perforated Beam | linearity M(−w) = −M(+w), zero-resultant trapezoid, reversed load, section properties | exact |

Also re-verified clean: Excel round-trips on all four tabs; every example loads
and analyses with no dialog; **107 buttons invoked across the five tabs, none
raised**; layout has zero unreachable controls in Truss, Beam, Cable and
Perforated Beam from 1600 px down to 550 px.

---

## 3. The layout fix — what it actually achieved

Measured fresh, controls **mapped** (reachable) per width, no buttons invoked,
filtered to the root toplevel:

| tab | 1600 px | 900 px | 550 px | verdict |
|---|---|---|---|---|
| Truss | 102 | 102 | 102 | perfect |
| Beam | 27 | 27 | 26 | perfect |
| Cable | 26 | 26 | 24 | good |
| Perforated Beam | 47 | 47 | 45 | good |
| Arch | 41 | 39 | 35 | good, small residual |

Compare 2026-09-05, when Beam fell 27 → 5 and Truss 48 → 14. The ▶ Analyze
button is now visible at 900 px (screenshot confirms the toolbar wraps to two
rows). This one is genuinely done.

**One measurement caveat, recorded so it is not chased again.** A naive sweep
flags a 564 px results `Text` as "overflowing" in Beam, Arch and Cable at every
width. It is a false positive: that pane sits inside a horizontally scrollable
canvas whose scrollregion covers it, and a horizontal scrollbar is mapped. It
is reachable. The only real residual is one Arch `Entry` exceeding the edge by
**3 px at 550 px**, which is not worth a change.

---

## 4. Recommended order

1. **B-1** (HIGH) — a fixed–fixed beam under UDL still cannot be solved. The
   most common indeterminate case in every textbook, and the physics is
   already right; only the mesh is wrong. ~30 min.
2. **C-1** (MED) — the Cable tab now shows **two different maximum tensions on
   one screen**, and the *unconservative* one feeds the stress check. ~1 h.
3. **B-4 + B-5** (MED) — Beam still accepts reversed and out-of-range
   coordinates silently. **A-6 + A-7** are the same class in Arch. Fix as one
   pass across both tabs. ~2 h.
4. **A-5** (MED) — the Arch diagram pane's captions pile up on each other at
   every window size; the fibre-stress header is unreadable. ~2 h.
5. **B-3** (MED) — distributed-load arrows still a constant 30 px, so a
   triangular load is drawn exactly like a uniform one. ~1 h.
6. **B-7 / A-4 / C-3** — Beam, Arch and Cable still have no physics tests
   between them. Each report's §0 table ports straight into a test module.
   This is why B-1 and C-1 have now survived two diagnoses. ~3 h.
7. **B-8 / C-5 / C-6 / A-2 / A-3 / B-6 / C-4 / P-5** — low severity; fold into
   whatever change you are already making.

Per-app detail: `REMAINING_BUGS_BEAM_2026-09-10.md`,
`…_ARCH_…`, `…_CABLE_…`, `…_TRUSS_…`, `…_PERFORATED_BEAM_…`.
