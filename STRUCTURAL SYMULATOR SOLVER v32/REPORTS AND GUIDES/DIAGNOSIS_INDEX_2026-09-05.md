# Per-app diagnosis — index and fix order, 2026-09-05

Five per-app reports, one file each, written so they can be worked through
independently:

- [`DIAGNOSIS_TRUSS_2026-09-05.md`](DIAGNOSIS_TRUSS_2026-09-05.md)
- [`DIAGNOSIS_BEAM_2026-09-05.md`](DIAGNOSIS_BEAM_2026-09-05.md)
- [`DIAGNOSIS_ARCH_2026-09-05.md`](DIAGNOSIS_ARCH_2026-09-05.md)
- [`DIAGNOSIS_CABLE_2026-09-05.md`](DIAGNOSIS_CABLE_2026-09-05.md)
- [`DIAGNOSIS_PERFORATED_BEAM_2026-09-05.md`](DIAGNOSIS_PERFORATED_BEAM_2026-09-05.md)

**Cable Web was excluded by request** and is not covered here. Its existing
reports (`CABLE_WEB_*`) are unaffected.

**Baseline:** the existing suite was green before and after this diagnosis —
157 passed in 224 s. **No source file was modified.** Everything below was
measured by driving the real widgets and the real solvers.

---

## 1. Health at a glance

| tab | solver physics | correctness bugs | UI bugs | tests for this tab |
|---|---|---|---|---|
| Truss | correct (joint residuals ~1e-13) | 0 | 1 MEDIUM | 1 file, `truss_math` load signs only |
| Beam | correct (10 closed forms) | 3 (1 HIGH, 2 MED) | 2 (1 HIGH, 1 MED) | **0** |
| Arch | correct to ~1e-14 | 0 | 1 MEDIUM | **0** |
| Cable | correct (3 closed forms) | 1 MEDIUM | 1 MEDIUM | **0** |
| Perforated Beam | **1 HIGH wrong-answer bug** | 3 (1 HIGH, 2 MED) | 0 | 3 files ✔ |

The headline: **four of the five solvers are excellent**, several to machine
precision. The bugs are concentrated in three places — one arithmetic guard in
the Perforated Beam, one meshing edge case in the Beam, and a layout idiom
shared by four tabs.

---

## 2. Recommended fix order

Ordered by (harm × confidence) ÷ effort, not by tab.

### 1. Perforated Beam **P-1 + P-2** — silently wrong bending moments
`perforated_beam_math.py:1047` is missing an `abs()`, so **every non-uniform
uplift load gets a wrong moment diagram** — 8.3 % error at midspan, wrong sign
at 0.9 L. `:1032` and `:1114` additionally zero out any load whose resultant
happens to cancel. Both collapse into one small rewrite using the
division-free expanded form given in the report. ~30 min, and this tab already
has tests to land it against.

### 2. Beam **B-1** — fixed–fixed beams do not solve
`ValueError: Beam is fully constrained; nothing to solve` on the most common
indeterminate case in every textbook. The physics is already right; the mesh
just needs a guaranteed minimum element count. ~30 min.

### 3. Beam **B-2** and the shared layout failure (**T-1, A-1, C-2**)
Below ~1 200–1 300 px the ▶ Analyze button is **unmapped, not clipped** — the
tab's primary action simply does not exist, with no scrollbar to reveal it.
Confirmed by screenshot in the Beam report. Arch fails earliest (12 controls
overflowing at 1 400 px); by 900 px none of Beam, Arch or Cable can run an
analysis. All four tabs share one idiom and should be fixed in one pass;
Cable Web's `_update_responsive_sidebars()` is the in-project reference.
~2 h for all four.

### 4. Cable **C-1** — peak tension reported 0.5–1.7 % low
Unconservative, and first-order convergent so refining the mesh is a poor
escape. `hypot(H, R_support)` is exact and already available. ~1 h.

### 5. Input validation — Beam **B-4, B-5**, Perforated Beam **P-3**
Reversed distributed loads are silently ignored (Beam) or silently inverted
(Perforated Beam); coordinates beyond the beam length silently extend the mesh
to 99 m while `model.L` stays 6. All are plausible typos that produce a
confident wrong answer. ~1.5 h total.

### 6. Beam **B-3** — load arrows drawn at constant length
Every distributed-load arrow is exactly 30 px regardless of magnitude, so a
0→60 kN/m triangular load is drawn identically to a uniform one. The intended
scaling function is computed at `beam_app.py:1133` and thrown away. ~1 h.

### 7. Test coverage — **B-7, C-3, A-4, T-4**
Beam, Arch and Cable have **no tests at all** (4 791 lines between them), and
Truss's 3 199-line UI has none. Each report's §0 table is written to be ported
directly into a test module. Highest value per hour after the fixes above,
and the reason B-1 and P-1 survived this long.

### 8. Housekeeping — **T-2**, then the dead-import findings
`truss_app.py:2425` `_draw_diagrams_legacy_overview` is a 175-line unreachable
method containing its own copy of the diagram layout logic — a genuine trap for
the next person editing diagrams. Delete it. The unused imports across all five
tabs are cosmetic; fold them into whatever change you are already making.

---

## 3. How this was checked

Each report's §0 lists what was verified **correct**, with the agreement
achieved, so that a later change can be checked against the same numbers and so
nobody spends time "fixing" behaviour that is already right. Three findings in
the drafting of this diagnosis turned out to be errors in the *reference*
formula rather than the app (a triangular-load deflection coefficient, an
end-moment sign convention, and the funicularity of a fixed-ended arch); those
are recorded as verified-correct rather than as findings.

Method notes:

- Solvers were driven directly (no Tk) against closed-form solutions.
- The Perforated Beam bug was found by a **superposition test** — M(−w) must
  equal −M(+w) — which needs no reference values and would have caught the
  whole class of defect.
- Layout findings were measured on real mapped widgets, filtered to the root
  toplevel, with a fresh app per tab and **before** any button was invoked (an
  earlier pass produced false positives because dialogs opened by the button
  sweep were still on screen).
- The Beam layout finding was confirmed with a screenshot as well as with
  `winfo_ismapped()`, because a geometry query alone cannot prove what a user
  sees.
