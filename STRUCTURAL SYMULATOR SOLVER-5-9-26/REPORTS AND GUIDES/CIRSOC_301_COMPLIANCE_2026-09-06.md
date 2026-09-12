# CIRSOC 301 conformance — Perforated Beam tab, 2026-09-06

**Source:** Reglamento CIRSOC 301, *Reglamento Argentino de Estructuras de
Acero para Edificios*, edición Julio 2018 (INTI-CIRSOC). Its own preface
states that it adopts **ANSI/AISC 360-2010** as its basis.
**Cross-checked against:** ANSI/AISC 360-16, and the SAP2000 *Steel Frame
Design Manual — AISC 360-10*.

**Status:** the resistance factors and nominal strengths are now
implemented, in `apps/perforated_beam/cirsoc_301.py`, each with its clause
recorded beside it. Before this change the tab applied **no resistance
factor anywhere**.

**Tests:** 268 → 319 passing. 51 added, of which 46 verify this layer
directly against the clause formulas (`tests/test_cirsoc_301.py`).

---

## 1. Two findings you should know about

### 1.1 CIRSOC's fillet-weld φ is 0.60, not AISC's 0.75

| standard | clause | φ | Fnw |
|---|---|---|---|
| **CIRSOC 301-2018** | Tabla J.2.5, *soldaduras de filete*, corte en el área efectiva | **0.60** | 0.60·F_EXX |
| AISC 360-16 | Table J2.5, fillet welds | 0.75 | 0.60·F_EXX |

CIRSOC adopts AISC 360-10 as its basis but uses a **lower** factor here.
The practical effect is direct: **a CIRSOC fillet weld must be 25% larger
than the AISC one for the same shear flow.**

I had defaulted to 0.75 before you supplied the documents. That was
**unconservative for a CIRSOC job**, and it is exactly the class of error
I declined to guess at earlier. It is now 0.60, with
`cirsoc_301.AISC_360` available when an AISC job is genuinely meant.

### 1.2 H.3.3 is not a von Mises criterion

H.3.3 governs this tab's station checks — "miembros no tubulares
sometidos a combinación de torsión, corte, flexión y carga axil",
verified as **stresses from an elastic global and sectional analysis**,
which is precisely what the Vierendeel and combined checks compute. But
it checks the two stresses **separately**:

- **H.3.4** `fun ≤ φ·Fy`, φ = 0.90 → 225 MPa for F24
- **H.3.5** `fuv ≤ 0.6·φ·Fy`, φ = 0.90 → 135 MPa for F24

There is no `sqrt(σ² + 3τ²)` interaction in the clause. That is what the
tab reported before, unfactored. The reported utilisation is now the
CIRSOC pair. The von Mises value is still computed and shown alongside,
because in a strongly combined state it exceeds both — dropping it would
lose information, and presenting it as the code answer would misstate the
code.

---

## 2. What is implemented, clause by clause

| quantity | clause | implemented as |
|---|---|---|
| φ flexure | F.1(1) | 0.90 |
| Mn, compact I | F.2.1 | Mp = Fy·Zx ≤ 1.5·My |
| LTB regimes | F.2.2 | Mp / interpolation / Mcr |
| Lp | F.2.5a, F.2.5b | 1.76·ry·√(E/Fyf); 1.59 if load on top flange |
| Lr, Mr | F.2.6a, F.2.7a, F.2.4c | X1/X2 formulation; FL = 0.7·Fy |
| φ shear | G.1.1 | 0.90 |
| Vn | G.2.1, G.2.2 | 0.6·Fyw·Aw·Cv, **Aw = d·tw** |
| Cv | G.2.3 / G.2.4 / G.2.5 | three regimes, kv = 5 (G.2.1(b)) |
| normal stress | H.3.4 | fun ≤ 0.90·Fy |
| shear stress | H.3.5 | fuv ≤ 0.54·Fy |
| buckling | H.3.6 | φc = 0.85 |
| classification | Tabla B.4.1b, casos 11 y 16 | 0.38, 3.76, 5.70·√(E/Fy) |
| weld strength | J.2.4 + Tabla J.2.5 | φ=0.60, Fnw=0.60·F_EXX |
| effective throat | J.2.2(a) | 0.707·leg |
| **minimum fillet leg** | **Tabla J.2.4** | 3 / 5 / 6 / 8 mm by thickest part |
| **maximum fillet leg** | **J.2.2(b)** | t if t<6; t−2 if t≥6 |
| min effective length | J.2.2(b) | 4× leg |
| flange-to-web exemption | J.2.2(b) | minimum table waived, reported |

Two details worth flagging because they are easy to get wrong:

- **`Aw = d·tw` uses the FULL depth** (G.2.2), which is *not* the same as
  the `Aweb = (d−2tf)·tw` the elastic stress check uses. Two quantities
  for two purposes; conflating them overstates Vn by ~7% on an IPE 400.
  A test pins the distinction.
- **Cv has a genuine 0.2% discontinuity** at the G.2.4/G.2.5 boundary
  (1.10/1.37 = 0.80292 vs 1.51/1.37² = 0.80452), because the constants
  are rounded. That is in the standard, not in the code; a test records
  it at the size it actually is.

---

## 3. Web openings — CIRSOC states a duty, not a method

**G.8, in full:** the effect of any web opening on the design shear
strength must be determined, and where the required strength exceeds the
design strength, adequate reinforcement must be provided at the opening.

That is the entire clause. CIRSOC prescribes **no method** for perforated
beams. So the Vierendeel / web-post / doubler-plate machinery in this tab
is not in conflict with CIRSOC — it is one way of discharging a duty the
standard deliberately leaves open, with the method itself taken from AISC
Design Guide 31 and SCI P355. What changed is that its stresses are now
compared against **factored CIRSOC resistances** (H.3.3) rather than raw
Fy, and that a member-level Chapter F / Chapter G check on the gross
section now runs alongside.

---

## 4. What the numbers actually did

Example beam: IPE 400, F24 (Fy = 250), L = 8 m, 8 × ⌀250 openings, UDL
15 N/mm at 40 mm eccentricity.

| check | before (no φ) | after (CIRSOC) | ratio |
|---|---|---|---|
| Vierendeel H1 | 0.499 | 0.501 | 1.00 |
| Vierendeel H3 | 0.521 | 0.563 | 1.08 |
| Vierendeel H4 | 0.506 | 0.555 | 1.10 |
| Web post [825–1275] | 0.085 | 0.091 | 1.07 |
| Fillet weld leg, q = 95 N/mm | 0.31 mm | 0.39 mm | **1.25** |

Everything moved in the conservative direction, as it must when
resistance factors are applied for the first time. The web-post ratio is
1.069 rather than 1/0.85: for these stocky posts the elastic plate stress
exceeds shear yield, so **yielding governs (H.3.5), not buckling
(H.3.6)** — the code picks the applicable clause rather than applying
φc = 0.85 to a yielding case.

New member check for the same beam, none of which existed before:

```
Section class: flange compacta, web compacta (Tabla B.4.1b)
Flexure : Mu=1.2e+08   Md=phi_b*Mn=2.786e+08   util=0.43
          Mp=3.096e+08, Lp=2009 mm, Lr=6188 mm
Shear   : Vu=6.0e+04   Vd=phi_v*Vn=4.644e+05   util=0.13
          Aw=3440 mm2, Cv=1.000 (shear yielding, G.2.3), h/tw=43.4
```

---

## 5. Using it for preliminary design — what is still yours

**The tool computes capacities. It does not choose load cases.** Demands
come from the loads you type in, and it remains your responsibility that
they are **factored actions per CIRSOC 101** (permanent/live) **and
CIRSOC 102** (wind). The report says so on every run. Implementing the
combinations is the obvious next step if you want it.

**Also still outside the tab:**

- **Base-metal rupture at a weld's fusion face** (J.4). Table J.2.5 makes
  the weld capacity the *lesser* of electrode and base metal; only the
  electrode side is computed. For a normal fillet on adequate plate the
  electrode governs, but this is not checked.
- **Web crippling and bearing stiffeners at concentrated forces —
  CIRSOC 301 §J.10.** Confirmed present in the standard and NOT yet
  implemented here. The relevant clauses are J.10.2 (fluencia local del
  alma, φ = 1.0, Rn = (5k + N)·Fyw·tw away from a member end and
  (2.5k + N)·Fyw·tw near one), J.10.3 (pandeo localizado del alma,
  φ = 0.75), and J.10.8 (rigidizadores para fuerzas concentradas), which
  is the stiffener-design clause. This is the check that answers "will the
  point loads and the supports cripple the web, and what plates do I need"
  — the reason stitch plates were specified at every load point in the
  50.4 m box girder. It is the clearest next gap to close.

  A caution that comes with it, from the AISC 360-16 commentary to J10:
  *"Equations J10-4, J10-5a and J10-5b assume restraint between the flange
  and the web, which may not be present when small and/or intermittent
  welds join the elements of built-up sections."* — i.e. the crippling
  equations themselves are questionable on a stitch-plated built-up
  member, which is precisely the detailing option under consideration.
- **Intermittent-weld spacing**, and the slenderness-based connector
  spacing limits for built-up compression members.
- **Transverse / eccentric weld-group effects** — the weld check is
  longitudinal shear flow only.
- **F.3–F.5** (non-compact and slender flexure). A non-compact or slender
  section is *detected* and its Mn capped at My as a conservative
  stand-in, with a notice — not silently pushed through the compact
  formula.
- **Fatigue** (Apéndice 3), entirely.
- **Lateral-torsional buckling defaults to "continuously braced"**
  (Lb = 0), which is right for a floor beam under a slab and wrong for a
  free-standing one. Lb, Cb and top-flange loading are now UI inputs; the
  report states which assumption produced Mn rather than hiding it.
- **CIRSOC 302** (*Elementos Estructurales de Tubos de Acero*) is not
  used: this tab models hot-rolled and built-up plate sections.

### CIRSOC 303 — correction, 2026-09-06

An earlier note here, and a caveat given twice in conversation, said that
a folded cold-formed section such as a 10 mm lipped channel was **"CIRSOC
303's scope, not 301's"**. **That was wrong.** It was said while the only
available copy of 303 was an unreadable scan — i.e. asserted without the
document. A legible copy has now been read, and it says the opposite:

> **§4.1** — *"Este capítulo se aplica al diseño de elementos
> estructurales fabricados con chapas, flejes o planchuelas dobladas o
> conformadas en frío… **cuyos espesores son menores que los aceptados por
> el Reglamento CIRSOC 301**."*

> **§1.1** — *"…pudiéndose usar espesores **menores** que los permitidos en
> el Reglamento CIRSOC 301… siendo **complemento** del Reglamento CIRSOC
> 301 y debiéndose emplear **en conjunción con él**."*

303 defines its own scope by reference to 301: it covers material
**thinner than 301 accepts**, and complements rather than replaces it.
301 sets no lower thickness bound for members — it covers welded plate
girders and slender webs (F.5) directly — and 10 mm plate is entirely
ordinary for it. 303's thin-sheet range is far below that; it discusses
welding sheet down to 1.5 mm.

Three further reasons 303 is the wrong instrument here even if thickness
were borderline:

- It is a **Recomendación** (1991), not a Reglamento, "en trámite de
  incorporación al SIREA".
- Its safety format is **allowable stress with a global factor γ ≥ 1.6**
  (§Cap. 3, §5.4.1), not the LRFD φ·Rn of 301-2018. Mixing the two would
  be a category error, not merely imprecise.
- It contains **nothing on web openings** — one incidental mention of
  welding around openings, and no method.

**Conclusion: CIRSOC 301 is the correct standard for a 10 mm folded
section, and the implementation in `cirsoc_301.py` is the right basis for
it.** The one thing 303 offers that 301 does not is the permitted increase
in yield strength from cold working (§1.3.2); ignoring it, as this tab
does, is conservative.

**Suggested check before trusting a result:** run one beam you have
already designed by hand and compare. The member check (§4) is the
easiest place to start, because Mp and Vn are two-line hand calculations.

---

## 6. Where it lives

| file | role |
|---|---|
| `apps/perforated_beam/cirsoc_301.py` | **new** — every factor and nominal strength, with clauses |
| `perforated_beam_math.py` | H.3.3 at each station; φc/H.3.5 branch on the web post; `member_check` |
| `welded_section_math.py` | φ = 0.60; Tabla J.2.4 / J.2.2(b) fillet limits |
| `perforated_beam_app.py` | design-basis header, member-check block, weld sizing, Lb/Cb inputs |
| `tests/test_cirsoc_301.py` | **new** — 46 tests against the clause formulas |
