# The Beam tab as it now stands — 2026-10-13

What the tab does, how it behaves, and what it will and will not tell you.
Current as of branch `claude/sleepy-bohr-sizbwf` (suite: 1452 passing).

For *why* it is like this, see `SESSION_HANDOFF_BEAM_2026-10-13.md`; for the
open items, `BEAM_UPDATE_RECOMMENDATIONS_2026-10-04.md`.

---

## 1. What it analyses

A single straight beam in bending, by cubic-Hermite (Hermitian) finite
elements with consistent load vectors, solved by direct stiffness. Isostatic
and hyperstatic alike: simple spans, single and double cantilevers, propped
cantilevers, fixed–fixed, and continuous beams over any number of supports.

| you can model | notes |
|---|---|
| **Supports** `pin`, `roller`, `fixed`, `guided` | At any station, including the ends. Two at one station merge into the union of what they restrain (pin + guided → fixed) and the panel says so. |
| **Point loads** | +P is downward. |
| **Point moments** | +M is counter-clockwise. |
| **Trapezoidal distributed loads** | `w1 → w2` over `[x1, x2]`; a reversed pair is normalised, intensities travelling with their own ends. Overlapping loads superpose. |
| **Non-uniform loads `q(x)`** | Any expression in `x` and `L` using math functions; `^` means power and `2x` means `2*x`. Adaptive Gauss quadrature, so it is accurate even where `q` is singular at its own domain edge. |
| **Section / material** | `E`, `I`, extreme-fibre distance `c`, shear area `A`, allowable bending and shear stress, and a deflection limit `L/n`. |

**It cannot yet model** internal hinges, elastic or settling supports, variable
EI along the span, axial force, or more than one load case at a time (R-18 to
R-20).

---

## 2. What it reports

Press **▶ Analyze**. The results panel is read-only and written in whichever
unit convention the selector above the notebook names.

```
REACTIONS   (Ry: + up.   M: the couple the support applies,
             + counter-clockwise.)
  x=0.00 m (fixed  ): Ry=  +30.00 kN   M=  +30.00 kN·m
      internal M: just left    +0.00, just right   -30.00 kN·m
  x=6.00 m (fixed  ): Ry=  +30.00 kN   M=  -30.00 kN·m
      internal M: just left   -30.00, just right    +0.00 kN·m

EXTREMES
  Max |V|    =     30.00 kN   at x = 0.00 m
  Max +M     =    +15.00 kN·m at x = 3.00 m  (sagging)
  Max -M     =    -30.00 kN·m at x = 0.00 m  (hogging)

EQUILIBRIUM
  Total load       =    +60.00 kN (down)
  Sum of reactions =    +60.00 kN (up)
  Residual SumFy   = +1.46e-14 kN   (1.2e-16 of load)  ok
  Residual SumM(0) = +5.82e-14 kN·m   (1.4e-16)  ok
  Beyond x = L     : V = +1.46e-14 kN   M = +5.82e-14 kN·m
  Statically indeterminate to degree 2 (4 restrained DOF)

SERVICEABILITY
  Max |defl| =     2.109 mm   at x = 3.00 m
    allowable = L/360 = 16.667 mm   (OK, ratio 0.13)

STRESS CHECK
  Bending sigma = M*c/I = 56.250 MPa
    allowable = 160.000 MPa   (OK, ratio 0.35)
  Shear tau = V/A   =  3.750 MPa
    allowable = 100.000 MPa   (OK, ratio 0.04)
```

Three things to read carefully:

* **`M` in REACTIONS is the couple the support applies**, counter-clockwise
  positive — the same convention as an applied moment. The *internal* moment,
  which is what a section has to carry, is the indented line below it, given on
  each side because at an interior support they differ.
* **EQUILIBRIUM is a genuine second opinion.** The applied total is integrated
  from the load definitions and never touches the solved displacements, so a
  residual that is not ~1e-13 of the load means the answer is wrong, not
  imprecise. If it ever reads `*** OUT OF BALANCE ***`, do not use the result.
* **σ and τ are evaluated at different stations** (max |M| and max |V|), so the
  pair is conservative rather than a section check at one point. The panel says
  so whenever those stations differ.

A missing allowable — a zero in any of the three limit boxes — reads
`not checked`, never `OK`.

---

## 3. The diagrams

Three stacked bands: shear, moment, deflection, sharing the beam's x axis with
the schematic above them.

* **Hover** anywhere in the pane for `x`, `V`, `M` and `δ` at that station,
  with a cursor drawn across all three bands.
* **Wheel** zooms the x axis about the pointer; **drag** pans; **double-click**
  or **Fit x** restores the whole span. The schematic follows the same window,
  and a zoomed pane states its range in blue at the bottom — a zoomed diagram
  that looks like the whole beam would be a trap.
* **Reverse BMD** plots sagging downward, for readers who expect that
  convention. The caption states which way round it is.
* **Export diagrams…** writes the pane as PostScript (vector, printable). A
  `.png` name works if Pillow and Ghostscript are installed, and says so
  plainly if not.
* Captions shorten as the pane narrows — explanation, then name, then symbol —
  so the quantity is always identifiable, and no two labels overlap at any
  width.

---

## 4. Editing a model

* **Add / Edit / Delete** under each table. **Double-click a row** to edit it:
  the row's own dialog reopens pre-filled, in the current convention.
* **Delete removes every selected row** (the tables are multi-select), as one
  undo step.
* **Ctrl-Z** unwinds up to 20 changes to the structural model — the five tables
  and the beam length. It also clears any diagrams on screen, because they
  belong to the model that was analysed. The section/material boxes are not
  part of undo.
* **Set length** asks what to do about anything that would fall off the
  shortened beam: *delete them*, *move them onto the beam*, or *cancel*
  (dismissing the dialog means cancel). Anything still off the beam is tagged
  red in its own table.
* **Three worked examples** — cantilever, double overhang, continuous — load a
  complete model in one click.

Every station is validated as it is entered: off the beam is refused, with the
numbers written in the convention you are using. **Analyze reports every
problem at once** — a bad length, a missing support, each stranded row, each
non-positive section number — rather than one dialog at a time.

Typing something that is not a number is named for the box it is in:
*"Beam length must be a number — got "abc"."*

---

## 5. Units

One selector above the notebook drives every tab. The Beam tab **stores** in
m, kN, kN·m, kN/m, GPa, cm², cm⁴, kN/cm², and shows whatever you select —
CIRSOC, Eurocode, NBR, CSA or AISC. Switching is **presentation only**: it
converts on the way to a label and back from an entry box, and never rewrites
the model. Every label, table heading and results line follows it.

Two deliberate exceptions, both stated in the interface where they apply:

1. **A `q(x)` expression is always in storage units** (kN/m, with `x` and `L`
   in m). The string is stored verbatim, so if its meaning followed the
   selector, switching convention would silently change your load.
2. **An exported workbook is always in storage units**, and its second line
   says so. A saved file must not change meaning because someone picked a
   different convention.

---

## 6. Excel

**Export Excel** writes two sheets:

* **Model** — every input needed to rebuild the beam: `[GEOMETRY]`,
  `[SUPPORTS]`, `[POINT_LOADS]`, `[MOMENTS]`, `[DISTRIBUTED_LOADS]`,
  `[NONUNIFORM_LOADS]`, `[SECTION]`. **Import Excel** reads it back.
* **Results** — reactions (with both internal moments), the extremes, the
  equilibrium rows with a `Balanced: yes / NO — DO NOT USE` verdict, any
  support-merge notes, and a station-by-station table of V, M and deflection.

Imports are validated by column **and sheet row number**, so a hand-edited
file fails at the file rather than later at Analyze:

```
Row 10: 'wobbly' is not a support type. Use one of: fixed, guided, pin, roller.
```

Older workbooks still import: both the pre-2026-09-07 `[DLOADS]` section name
and the pre-2026-10-04 `w1_kNm` column spelling are accepted, and a file
written before the deflection limit existed gets the default of 360.

---

## 7. How it is put together

```
numerics.py          the numeric core — imports only `math`, so a solver
                     can be imported and tested with no display at all
common.py            shared widgets and helpers; re-exports numerics
apps/beam/
  beam_math.py       BeamModel, BeamResult, adaptive quadrature. SI only.
                     No tkinter, no common, no units — enforced by a test.
  beam_reports.py    the Excel export and import
  beam_app.py        the Tkinter half: widget state in, a BeamModel built
                     from it, the result drawn and written out
```

`BeamModel`, `BeamResult`, `export_beam_excel` and `import_beam_excel` are
re-exported from `beam_app` so code predating the split keeps working.

The solver works in SI throughout — m, N, N·m, N/m, EI in N·m² — and the tab
converts at its own edge. (The Perforated Beam tab deliberately uses mm/N/MPa
instead; both say so in their own docstrings.)

### Accuracy

Measured against fifteen closed forms (2026-10-13). **Statics are exact** —
reactions and moments come back to within 1.2 × 10⁻¹⁵ to 3.9 × 10⁻¹³ relative,
i.e. floating-point noise. **Deflections carry the M/EI integration error**:
worst 2.8 × 10⁻⁴ (fixed–fixed midspan), typically 2–6 × 10⁻⁵. So a moment or a
reaction from this tab is as good as the arithmetic; a deflection is good to
about three or four figures, which is well inside anything serviceability
turns on.

The cases checked:

| case | checked against |
|---|---|
| simple span + UDL | M = wL²/8, δ = 5wL⁴/384EI |
| cantilever, point and UDL | PL³/3EI, wL⁴/8EI |
| propped cantilever | R = 3wL/8, M = −wL²/8 |
| fixed–fixed | M_end = −wL²/12, M_mid = +wL²/24, δ = wL⁴/384EI |
| two equal spans | R_mid = 1.25wL, M = −wL²/8 |
| guided end | M_end = −wL²/3, M_far = +wL²/6 |
| sinusoidal q(x) | wL/π, wL²/π², wL⁴/π⁴EI |

Every model in the suite also satisfies the equilibrium check to within 1e-13
of its applied load, which is a check of the *recovery* rather than of the
solve and so catches a different class of error — see §2.

---

## 8. Running it

```bash
cd "STRUCTURAL SYMULATOR SOLVER-5-9-26"
python main.py
```

Needs **numpy** and **scipy** (both mandatory — see `requirements.txt`),
**tkinter** for the interface, and **openpyxl** for Excel, which the tab will
install on first use if it is missing. Matplotlib and Pillow are optional and
only used for equation images and PNG export.

```bash
python -m pytest tests/ -q              # 1452 tests
xvfb-run -a python -m pytest tests/ -q  # headless; otherwise the UI tests skip
```

---

## 9. Known limits

Worth knowing before trusting a number to a drawing:

* **Loads are checked as entered, not factored.** There is no load-case or
  combination support, so a utilisation here is systematically lower than one
  from a report that applied 1.2D + 1.6L (R-20).
* **The stress checks are elastic and allowable-based**: `M·c/I` against a
  typed allowable, and `V/A` on the **gross** area. No resistance factors, no
  nominal strengths, and no unbraced length — therefore no lateral-torsional
  buckling (R-21).
* **One EI for the whole span** (R-19), and **no internal hinges, springs or
  settlements** (R-18).
* **σ and τ come from different stations**, as §2 says.
* The deflection limit compares `max |δ|` against `L/n` using the full beam
  length; for a cantilever, codes usually apply a different rule.
