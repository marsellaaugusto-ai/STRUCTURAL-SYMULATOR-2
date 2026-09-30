# Shell tab (reinforced-concrete hypar) — feasibility diagnosis, 2026-09-14

**Question asked:** add a shell structural calculator — hyperbolic paraboloids
(hypars) and other surfaces in reinforced concrete — with uniform and
non-uniform vertical loads and horizontal (wind) loads; compute the forces and
everything else needed to design the shell; type the surface as a function,
with an interface like GeoGebra's; choose the shell thickness, find out where
it has to be thicker, and make it thicker in the design.

**Method:** no code was changed for this report. Both project trees were
surveyed, the installed libraries were checked, and the solver speed was
measured with a timing probe the same size as a real shell model.

---

## 0. Short answers

| question | answer |
|---|---|
| Would I recommend it? | **Yes**, as a new eighth tab, **Shell**, built on a finite-element shell solver, with the classic hand formula (membrane theory) shown beside it as a check. |
| Is it too big a change? | It is the **largest single feature since Cable Web**: a new tab of roughly 4 000–6 000 lines including tests. It **does not touch** the solvers of the other tabs. It needs three new entries in `units.py` and new load combinations. |
| Is the math engine going to be a problem? | **No.** numpy 2.5 and scipy 1.18 are installed (and already required by `common.py`). Measured: a 40 × 40 mesh (10 086 unknowns) assembles in 0.03 s and solves in 0.21 s; 60 × 60 in 0.58 s. A "make it thicker and re-check" loop of ten re-solves takes 2–3 s. |
| What is the real risk? | Not speed. **(1) The edges.** A hypar sends its load into its edges; that is where the shell bends, where the edge beams pile up force, and so where thickening is actually needed. If the edges are modelled carelessly the design is wrong exactly where it matters. **(2) Wind.** No code — CIRSOC 102, ASCE 7 or Eurocode 1 — publishes pressure coefficients for a hypar surface, so the wind pattern has to be entered by the user or taken from an approximate preset, and the app must say so. |

---

## 1. How a hypar actually carries load (why the design needs what it needs)

In plain terms, because every design decision below follows from this.

**Mostly by in-plane forces.** A thin shell carries load mostly by forces
*within* its surface — stretching, squeezing and shearing it, like a sheet of
cloth pulled tight. These are the **membrane forces** Nx, Ny, Nxy, in kN per
metre of shell. For a hypar z = c·x·y/(a·b) (plan a × b, corner rise c) under a
uniform vertical load q per m² of plan, the textbook answer is that the shell
carries the load as **pure shear, the same everywhere**:

    Nxy = q · a · b / (2 c)

Example: a 10 m × 10 m hypar with 2 m rise and q = 5 kN/m² has Nxy = 125 kN/m.
Along one diagonal that is 125 kN/m of compression (an arch), along the other
125 kN/m of tension (a hanging cable). The tension diagonal needs steel:
about 3.3 cm²/m of 420 MPa bar. A 6 cm shell sees a compressive stress of
about 2.1 MPa — small for concrete. This is why hypars can be so thin.

**The edges collect it.** That shear arrives at the straight edges and must be
picked up by **edge beams**, whose axial force grows linearly along their
length: N = Nxy × distance. In the example the edge beam reaches
125 × 10 = **1 250 kN** at the low corner. The edge beams, not the shell, are
often the biggest members in a hypar.

**Where the hand formula stops working, the shell bends.** Next to the edges
and supports, under loads that are not uniform (wind on one half, snow drifts),
and wherever the surface is not a pure hypar, the membrane answer is
incomplete: the shell also **bends**, with moments Mx, My, Mxy in kN·m per
metre. In a thin concrete shell, **bending is what decides the thickness** —
and only a finite-element model shows it. That is the main reason for building
a finite-element solver rather than coding the textbook formulas alone.

**Thin shells can buckle.** The compressed diagonal of a hypar is an arch that
can snap through if the shell is too thin. This needs its own check; it often
sets the minimum thickness of a large, flat hypar.

---

## 2. What the app has today, and what is missing

Every existing tab models **lines** — bars, beams, cables. There is no element
that models a **surface**, there is **no concrete design** (only steel, via
CIRSOC 301), no wind-on-a-surface load, and no concept of thickness varying
over a member. So the new pieces are:

| needed | exists? |
|---|---|
| shell finite element (membrane + bending, 6 unknowns per node) | **no** — new |
| edge-beam / column element in 3-D (to frame the shell) | **no** — Stereo has a 3-D *bar* (axial only); an edge beam must also bend |
| typing a surface z = f(x, y) | **yes, but only in `solver/`** — see §3.1 |
| a 3-D view that can orbit, zoom, pan | **yes, but only in `solver/`** (Stereo's wireframe); a surface also needs **shading and colour maps** — new |
| sliders and live redraw (the GeoGebra feel) | **no** — new |
| loads that vary over the surface: vertical, normal pressure, horizontal | **no** — new |
| wind velocity pressure | the formula is standard (CIRSOC 102-2005, same form as ASCE 7); the guide `guia viento torre cirsoc2005.pdf` is on disk in `Downloads` |
| reinforced-concrete design of a surface (steel per metre each way, top and bottom) | **no** — new |
| a code text for concrete | **no CIRSOC 201 PDF on this machine** (CIRSOC 301, 302, 303 are in `Downloads\PROGRAMACION`) |
| thickness that varies, and a "make it thicker here" tool | **no** — new |
| load combinations with wind | **partly** — `load_combinations.py` knows D and L only, no W, S or Lr |
| units | **partly** — `units.py` has `line_load` (kN/m, fits membrane forces) but no area load (kN/m²), moment per metre (kN·m/m) or steel area per metre (cm²/m) |
| Excel export/import, report window | pattern exists in every tab; copy the shape |

---

## 3. Two things found in the project itself

### 3.1 The Stereo Structure tab is not in the repo, and not on GitHub

The Stereo tab (space grids, built 2026-09-11) exists **only in `solver/`**.
The live git repo — `STRUCTURAL-SOLVER-repo\STRUCTURAL SYMULATOR SOLVER-5-9-26\`,
branch `perforated-beam-cirsoc-and-features` — has six tabs and no
`apps/stereo/`. Nothing on any remote branch has it either (the new
`origin/main-2` is a copy of the old `main`).

This matters for the shell tab because Stereo holds the two pieces the shell
would otherwise have to rewrite: the safe surface-formula compiler
(`make_surface_fn`, with `^` as power and `2x` meaning `2*x`) and the 3-D orbit
projection. Writing them a second time would break the project's own rule
(MANIFESTO §3j: do not solve the same sub-problem in two places).

Moving Stereo into the repo is small but not a plain copy: `stereo_math.py`
imports `from apps.perforated_beam import cirsoc_301`, and in the repo that
module sits at the root and is imported as `import cirsoc_301`. Stereo also
added `tension_strength()` to `solver/`'s copy of `cirsoc_301.py`; the repo's
copy is a different, larger file, so that function has to be added to it by
hand, not by copying the file over.

### 3.2 A shell is a much larger model than anything else in the app

A 40 × 40 shell mesh has ~10 000 unknowns; the largest Stereo grid has a few
thousand. The shared solver `common._beam_gauss_solve` is dense, pure Python,
and cannot go near this size. The shell tab must use scipy's **sparse** solver
(`scipy.sparse.linalg.spsolve`), which is what the timings in §0 used. Stereo's
rank check (smallest vs largest eigenvalue, to refuse a structure that can
move freely instead of printing garbage) is also dense; for a shell it has to
become a sparse check — a free-body test plus a residual and
displacement-sanity test — or it will take minutes.

---

## 4. What the engineering choices are

**Solver: finite elements, with the hand formula beside it.** A four-node
shell element (MITC4 — the standard element in commercial shell programs,
which handles curved, twisted surfaces like a hypar without the element
becoming artificially stiff), plus a 3-D beam element for edge beams and
columns. Results per element: the membrane forces, the bending moments, the
transverse shears, the principal forces and their directions, deflections and
reactions. The membrane-theory answer (the formula in §1, and a numerical
version for any shallow surface under vertical load) is computed alongside,
and the report shows both, with the ratio, so the numbers can be followed by
hand — the same habit as the Perforated Beam reconciliation.

**Concrete design: steel per metre in each direction, top and bottom.** Each
element's membrane forces and moments are split into a top layer and a bottom
layer (the "sandwich" method), and each layer gets the orthogonal steel it
needs to carry its in-plane forces (the standard method for reinforcing a
surface in two fixed directions). Then: the concrete diagonal compression
check, the transverse shear check, minimum steel (shrinkage and temperature),
maximum bar spacing, the buckling check, and deflection. From these the app
computes, **for every element, the thickness it would need to pass
everything**.

**Thickness: base value, formula, and automatic thickening.** The user sets a
base thickness, or types a thickness function t(x, y) the same way as the
surface. After analysis, the app colours the surface by how close each part is
to failing and by the thickness each part needs. A **Thicken** button then
thickens the parts that need it — in steps (for example 1 cm), with a gradual
taper into the thinner shell around them, since a sudden step in a shell
creates bending of its own — re-analyses (a thicker patch attracts more force,
so one pass is not enough), and repeats until every element passes. The zones
it creates are shown as editable rules, so the result can be adjusted by hand.

**Wind: pressure field over the surface.** The velocity pressure comes from
CIRSOC 102-2005 (basic wind speed, exposure category, height, importance
factor). How that pressure is distributed over a hypar is not in any code, so
the pressure coefficient is a function Cp(x, y) the user can type, with a few
presets as starting points (windward half pushed, leeward half sucked, uplift
over the whole roof). Presets are labelled **approximate** in the report.
Separately, any load can be entered as a horizontal load in x or y, also as a
function of position, which covers what "horizontal loads" literally means.

**GeoGebra-like interface.** GeoGebra works by a list of definitions on the
left (the "algebra view") — numbers, which automatically get sliders, and
functions that use them — and a graph that redraws the moment anything
changes. The shell tab can work the same way: a list such as

    a = 10          ← slider
    b = 10          ← slider
    c = 2           ← slider
    z(x, y) = c·x·y/(a·b)
    t(x, y) = 0.06
    q(x, y) = 5
    Cp(x, y) = …

with a line at the bottom to type new definitions, each row showing a green
tick or a red error, and the 3-D surface redrawing live as a slider moves. The
analysis itself runs when asked for (about a second), not on every slider
tick.

---

## 5. Recommendation

Build it, as the eighth tab, in the live repo, in five phases (see
`PLAN_SHELL_2026-09-14.md`): engine and benchmarks first, then the interface,
then concrete design and thickening, then wind, combinations and reports,
then a full check through the interface with screenshots. First, move the
Stereo tab into the repo so the two tabs share one formula engine and one 3-D
view instead of two copies.

The questions that change the design are listed at the end of the plan.
