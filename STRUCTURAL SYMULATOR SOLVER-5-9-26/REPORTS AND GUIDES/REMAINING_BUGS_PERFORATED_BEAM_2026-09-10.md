# Perforated Beam tab — bugs still open, 2026-09-10

**Files:** `apps/perforated_beam/` — 14 modules, `perforated_beam_math.py`
(94 KB), `perforated_beam_app.py` (111 KB), plus `hyperstatic_math`,
`opening_reinforcement`, `perforated_beam_views`, `section_plastic`,
`section_shapes`, `welded_section_math`, `perforated_beam_excel`, and
`cirsoc_301`
**Re-diagnosis of** `DIAGNOSIS_PERFORATED_BEAM_2026-09-05.md`. Suite: 809 passed.

## No correctness bugs remain open. Only cosmetics.

| finding | severity | status |
|---|---|---|
| P-1 missing `abs()` → wrong M for uplift ramps | **HIGH** | ✅ fixed |
| P-2 zero-resultant trapezoid → zero reactions | MED | ✅ fixed |
| P-3 reversed distributed load inverted | MED | ✅ fixed |
| P-4 degenerate sections accepted silently | LOW | ✅ fixed |
| P-5 dead locals | LOW | ❌ open (different ones now) |

This tab had the worst bug in the September diagnosis and now has none. It also
has by far the strongest test coverage in the project — roughly 350 tests
across 15 files.

---

## P-1 · FIXED — verified by the invariant that found it

The fix went further than the one-character change suggested: `_dist_diagram`
now uses the division-free expanded form, and a shared `_trapezoid_resultant`
helper (`perforated_beam_math.py:1247`) returns both the resultant and its
moment with no branch at all —

```python
return W, xi ** 2 * (2 * w1 + wx) / 6.0
```

The comment at `:1430-1432` records what the old `if (w1 + wx) > 1e-12` test
did wrong, which is the right place for that knowledge to live.

**Re-verified** with the superposition invariant that exposed it — M(−w) must
equal −M(+w) — on the ramp w₁ = −10 → w₂ = −30 N/mm over an 8 m span:

| x | 0.1 L | 0.25 L | 0.4 L | 0.5 L | 0.6 L | 0.75 L | 0.9 L |
|---|---|---|---|---|---|---|---|
| relative asymmetry | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

Exactly zero at every station. In September this was 8.33 % at midspan and a
**sign error** at 0.9 L.

## P-2 · FIXED — including the discontinuity

```
w1 = -20, w2 = +20.000  ->  RA = -26 666.7   RB = +26 666.7    (exact: 26 666.7)
w1 = -20, w2 = +20.001  ->  RA = -26 665.3   RB = +26 669.3
w1 = -20, w2 = +19.999  ->  RA = -26 668.0   RB = +26 664.0
```

The exact case is now right, and the function is continuous through
`w1 + w2 = 0` — in September it returned 0 at the crossing and 26 669 a
thousandth away.

## P-3 · FIXED

```
normal   x1=2000, x2=6000  ->  RA = 20.0 kN  RB = 20.0 kN  M_mid = 6.0e7 N·mm
reversed x1=6000, x2=2000  ->  RA = 20.0 kN  RB = 20.0 kN  M_mid = 6.0e7 N·mm
```

Reversed input now normalises instead of inverting the load. *(The Beam tab
still has this hole — see B-4 — and Arch fixed it too. Beam is now the odd one
out.)*

## P-4 · FIXED

`RolledSection` now validates, with messages in the house style:

```
d = 0          -> ValueError: z: every I-section dimension must be positive; got d = 0 mm.
tf = 80, d=100 -> ValueError: z: total depth d (100 mm) must exceed both flange thicknesses together
tw = 0         -> ValueError: z: every I-section dimension must be positive; got tw = 0 mm
```

`CustomProfileSection` still refuses a collinear or 2-point outline with its
"zero area" message, as before.

## Also re-verified clean

Section properties exact for a rectangle in **both windings** (A, I, Iy, S_top,
d) and for a rolled I-section; statics exact for UDL, point load at L/3, and an
applied point moment. Layout is clean at every width 1600 → 550 px (47 controls
mapped, 0 overflowing). The example loads and analyses in 0.02 s; 27 buttons
invoked, none raised.

*(A naive sweep flags "Apply as section" / "Apply these openings" as
off-screen. That is a harness artefact — those buttons live in the profile
designer and sketcher Toplevels, which the button sweep leaves open. Measured
properly, filtered to the root toplevel, this tab never overflows.)*

---

## P-5 · LOW · Dead locals — the only thing still open

The September ones are gone; four new ones appeared with the new modules:

| file:line | what |
|---|---|
| `opening_reinforcement.py:125` | `d = ymax - ymin` assigned, never used |
| `perforated_beam_views.py:432` | local `c` assigned, never used |
| `section_shapes.py:147` | `gap = section.overall_width - 2 * ch.bf` assigned, never used |
| `perforated_beam_app.py:1787` | f-string with no placeholders (redundant `f` prefix on a continuation line) |

All four were inspected and are genuinely inert — in particular
`section_shapes.py:147`, where the surrounding code computes the same offset
directly from `section.overall_width / 2.0 - ch.bf`, so the unused `gap` is a
leftover and not a dropped term. Plus 8 unused imports across
`perforated_beam_math`, `welded_section_math`, `section_plastic`,
`opening_reinforcement` and `general_net_section`.

Cosmetic. Fold into whatever change you are next making in those files.

---

## Caveat on this verdict

The modules built since 2026-09-05 — `opening_reinforcement`, `section_plastic`,
`perforated_beam_views`, `welded_section_math`, `hyperstatic_math`,
`cirsoc_301` — were checked for **crashes, dead code, degenerate inputs and
test coverage**, and they carry ~350 tests of their own. I did **not** re-derive
their engineering results (plastic section moduli, CIRSOC capacity factors,
doubler-plate sizing, weld shear flow) against independent hand calculations
the way I did for the core statics. That is a separate piece of work; ask for
it explicitly if you want it.

`CIRSOC_301_COMPLIANCE_2026-09-06.md` and the provenance caveat in
`OPEN_ITEMS_CLOSED_2026-09-07.md` §2 both record which factors were
transcribed from the document and which were taken from AISC — that
distinction is the thing to check before this tab is used for real design.
