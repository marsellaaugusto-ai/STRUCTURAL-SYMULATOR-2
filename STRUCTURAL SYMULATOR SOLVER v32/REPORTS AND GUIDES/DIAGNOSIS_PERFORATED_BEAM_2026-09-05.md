# Perforated Beam tab — diagnostic report, 2026-09-05

**Files:** `apps/perforated_beam/` — `perforated_beam_math.py` (1 600+ lines),
`perforated_beam_app.py` (851), `profile_sketcher_math.py`,
`profile_sketcher_ui.py`, `section_profile_math.py`, `section_profile_ui.py`
**Build:** STRUCTURAL SYMULATOR SOLVER-5-9-26
**Method:** MANIFESTO §2 — closed-form validation of the section and statics
maths, plus a superposition (linearity) test that no amount of code reading
would have produced.
**Baseline:** existing suite 157 passed in 224 s.

---

## 0. Summary

| | |
|---|---|
| Section-property maths | **correct** — exact on every case tested |
| Statics for downward loads | **correct** — exact |
| Statics for **upward / non-uniform** loads | **WRONG — see P-1** |
| Best-tested tab of the five | 3 test files, all green |
| Layout | **clean** at every width 1 600 → 550 px |

This tab has the best test coverage in the project and the cleanest UI
behaviour. It also has the single worst bug found in this diagnosis: a missing
`abs()` that silently corrupts the bending-moment diagram for any non-uniform
uplift load.

### What was verified as CORRECT (do not "fix" these)

| case | quantity | agreement |
|---|---|---|
| `CustomProfileSection`, rectangle 100×300, **CCW winding** | A, I, Iy, S_top, d | exact |
| same rectangle, **CW winding** | A, I, Iy, S_top, d | exact (winding-independent ✔) |
| `RolledSection` d=400 bf=200 tf=15 tw=10 | A, I, S, A_web | exact |
| SS + full UDL | R = wL/2, M_mid = wL²/8 | exact |
| SS + P at L/3 | R = 2P/3, P/3; M = 2PL/9 | exact |
| SS + applied point moment | R = ∓M₀/L | exact |
| Uniform **negative** (uplift) load | M(−w) = −M(+w) | exact |
| Shear V, all cases incl. negative trapezoids | V(−w) = −V(+w) | exact |

Also clean: the layout does not overflow or drop a single control anywhere from
1 600 px down to 550 px — the only tab in the project of which that is true.
(It has no canvas of its own by design; the sketcher and section designer own
theirs, inside their own Toplevels.)

---

## 1. Findings

### P-1 · HIGH · Bending moment is wrong for every non-uniform uplift load

A missing `abs()` sends any *negative* trapezoidal distributed load down a
wrong-centroid branch. Shear stays correct; **the moment diagram is corrupted,
including its sign near the far support**.

**Root cause —** `perforated_beam_math.py:1047`:

```python
applied = (w1 + wx) / 2.0 * xi
if (w1 + wx) > 1e-12:                     # <-- no abs()
    xibar = xi * (2 * wx + w1) / (3 * (w1 + wx))
else:
    xibar = xi / 2.0                      # centroid of a UNIFORM strip
```

For an uplift load both `w1` and `wx` are negative, so `(w1 + wx) > 1e-12` is
False and `xibar` silently falls back to `xi/2` — the centroid of a *uniform*
strip. For a genuinely trapezoidal load that centroid is wrong, so
`M = reaction_M - applied * (xi - xibar)` is wrong everywhere inside the loaded
region.

**Measured** — by linearity, M(−w) must equal −M(+w) exactly for a determinate
elastic beam. Load w₁ = −10, w₂ = −30 N/mm over an 8 m span:

| x | correct M | reported M | error |
|---|---|---|---|
| 0.1 L | −4.992e7 | −4.981e7 | 0.21 % |
| 0.5 L | −1.600e8 | −1.467e8 | **8.33 %** |
| 0.75 L | −1.300e8 | −8.500e7 | 34.6 % |
| 0.9 L | −6.528e7 | **+1.248e7** | **119 % — wrong sign** |

The same test on a *uniform* negative load gives exact agreement (0.00e+00),
which is why this has never shown up: `w1 == w2` makes the `xi/2` fallback
accidentally correct, and uniform uplift is the case anybody would test first.

**Blast radius:** `_dist_diagram` feeds `global_V_M`, which feeds
`analyze_opening` (the Vierendeel check), `analyze_combined`, `net_I_at` and
`deflection_profile`. Every design utilisation for a beam with a non-uniform
uplift component is computed from a wrong moment. Wind uplift on a roof beam,
varying along the span, is exactly this load.

**How to fix:** one character-level change —

```python
if abs(w1 + wx) > 1e-12:
```

Better still, remove the branch entirely: the expression
`applied * (xi - xibar)` expands algebraically to
`xi**2 * (2*w1 + wx) / 6.0`, which has no division and no degenerate case at
all. That form is exact for every sign and for `w1 + wx == 0`.

**Verify:** assert `M(-w1, -w2, x) == -M(w1, w2, x)` to machine precision at
a dozen stations, for `(w1, w2)` in `[(10,30), (30,10), (0,20), (-10,-30)]`.
Add it to `tests/test_perforated_beam_math.py` — the linearity invariant is
cheap and catches this whole class of bug.

**Effort:** ~15 min plus the test. **Risk:** low, and the existing 3 test files
give you a safety net.

---

### P-2 · MEDIUM · A load with zero net resultant produces zero reactions

A trapezoidal load with `w1 = -w2` has zero resultant but a **non-zero moment**
about the supports, so it must produce equal and opposite reactions. It
produces none.

**Measured** (8 m span, w₁ = −20, w₂ = +20 N/mm):

```
w2 = +20.000  ->  RA =      0.0 N   RB =      0.0 N     <-- wrong
w2 = +20.001  ->  RA = -26 665.3 N  RB = +26 669.3 N    <-- correct
exact:            RA = -26 666.7 N  RB = +26 666.7 N
```

A 0.005 % change in one input flips the answer between 0 and 26 669 N. The
function is **discontinuous** at `w1 + w2 = 0`.

**Root cause —** two guards written to dodge a 0/0 in the centroid formula,
which instead discard a real contribution:

- `perforated_beam_math.py:1114` — `if abs(Wtot) > 1e-12:` in `reactions()`
- `perforated_beam_math.py:1032` — `if abs(Wtot) < 1e-12: RA = RB = 0.0` in
  `_dist_diagram()`

The centroid `xbar` genuinely is undefined when `w1 + w2 = 0`, but the *product*
`Wtot * (xbar - xA)` is perfectly well defined — the `(w1 + w2)` cancels:

```
Wtot * (xbar - xA)  ==  d * ( (w1 + w2)/2 * (x1 - xA)  +  d * (2*w2 + w1) / 6 )
```

where `d = x2 - x1`. That form needs no guard and no division.

**How to fix:** replace both guarded blocks with the expanded expression above.
The same rewrite fixes P-1's sibling case in `_dist_diagram`, so do P-1 and P-2
as one change.

**Verify:** the `w1 = -w2` case gives `RB = w·d²/(6·span)`, and sweeping w₂
through the ±20 crossing produces a continuous curve.

**Effort:** ~30 min together with P-1. **Risk:** low.

---

### P-3 · MEDIUM · A distributed load entered right-to-left is inverted

Entering x1 = 6000, x2 = 2000 (a plain typo) does not raise and is not
normalised — it flips the load into uplift, because `Wtot` picks up the
negative `(x2 - x1)`:

```
normal   x1=2000, x2=6000  ->  RA = +20.0 kN  RB = +20.0 kN  M_mid = +6.0e7 N·mm
reversed x1=6000, x2=2000  ->  RA = -20.0 kN  RB = -20.0 kN  M_mid = -8.0e7 N·mm
```

Both the sign *and* the magnitude are wrong (the reversed case also mis-places
the loaded region relative to the station), and nothing warns the user.

`BeamConfig.__post_init__` (`perforated_beam_math.py:975`) already validates the
support positions with a long, genuinely helpful error message — the load
coordinates deserve the same treatment.

**How to fix:** normalise in `DistLoad`/`DistTorque` (`__post_init__`: swap
`x1/x2` together with `w1/w2`), or validate in `BeamConfig.__post_init__`
alongside the existing support check. Normalising is friendlier; validating is
more honest. Either is fine — just not silence.

**Effort:** ~20 min. **Risk:** low.

---

### P-4 · LOW · Degenerate sections return numbers instead of refusing

`CustomProfileSection` is well guarded — a collinear or 2-point outline raises
a clear "outline has zero area" `ValueError`. `RolledSection` is not:

- `d = 0` returns `I = 427 500 mm⁴` (a zero-depth section with a real I)
- `tf = 80` on `d = 100` (flanges overlapping through the web) returns
  `I = 2.009e7` with no complaint

These are garbage-in cases, but the class already knows its own geometry and
could say so.

**How to fix:** a `__post_init__` on `RolledSection` asserting
`d > 2*tf > 0` and `bf > tw > 0`, with a message in the style of the existing
`BeamConfig` one.

**Effort:** ~20 min. **Risk:** low — check the built-in section library passes
first.

---

### P-5 · LOW · Dead locals

`a = self._signed_area()` is computed and unused in `CustomProfileSection.I`
(`perforated_beam_math.py:625`) and `.Iy` (`:646`). Both properties re-derive
what they need from `self.centroid` and `self.A`; the leftover call is pure
cost. `pbm` is imported unused in `profile_sketcher_ui.py:23` and
`section_profile_ui.py:17`, and five names are imported unused from
`profile_sketcher_math` in `section_profile_math.py:21`.

---

## 2. Suggested order

1. **P-1 + P-2 as one change** to `_dist_diagram` and `reactions()`, using the
   division-free expanded form, with the linearity test added to
   `tests/test_perforated_beam_math.py`. This is the highest-value fix in the
   whole project.
2. **P-3** — input normalisation, same file, natural follow-on.
3. **P-4** — section validation.
4. **P-5** — opportunistically.
