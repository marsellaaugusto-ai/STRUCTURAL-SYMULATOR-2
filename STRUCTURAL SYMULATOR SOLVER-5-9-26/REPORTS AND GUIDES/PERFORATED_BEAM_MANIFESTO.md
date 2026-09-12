# Perforated Beam (Cellular / Castellated Beam) — Project Manifesto

**Read this before changing anything in `apps/perforated_beam/`.**

A note on where this file lives: the spec that requested this module asked
for a `MANIFESTO.md` "inside the module's folder, matching the convention
used by other modules." Having inspected the repo, that premise doesn't
quite hold — every existing module's manifesto/diagnostic history
(`DIAGNOSTIC_REPORT.md`, `CONVERGENCE_FIX_V11.md`, the Cable Web
`MANIFESTO.md`, etc.) actually lives in the shared `REPORTS AND GUIDES/`
folder at the project root, not inside `apps/<name>/`. This file follows
that real convention instead of the literal instruction, and a short
pointer file is left at `apps/perforated_beam/README.md` for anyone who
goes looking in the module folder first.

---

## 1. Design standard, units, and why

**Units: mm, N, MPa (= N/mm²), N·mm.** This is a deliberate departure from
this repo's other tabs (Beam: m/kN; Truss: m/kN implicitly) because the
governing checks here — net-section properties at an opening, plate
buckling of a web post, torsional shear in a thin plate — are all
naturally expressed in section dimensions (mm) and material stresses
(MPa), which is how AISC 360 / Eurocode 3 / the SCI/AISC castellated-beam
literature present them. Converting back and forth between m/kN and mm/MPa
inside the same formula is exactly the kind of unit-conversion bug this
choice avoids. Each tab in this program documents its own units
independently already (see each `*_app.py` class docstring); this is
consistent with that existing pattern, not a break from it.

**Standard:** CIRSOC 301 (ultimate limit state format: LRFD-style, member
resistance = capacity factor × nominal resistance, demand = factored load
effect) is the intended governing standard for global member checks, with
CIRSOC 101 (permanent/live loads) and CIRSOC 102 (wind) feeding the load
combinations that produce the V(x)/M(x)/T(x) diagrams this module
consumes. **Important limitation, stated plainly:** this module does **not**
itself implement CIRSOC 301's specific clause-by-clause resistance-factor
tables or CIRSOC 101/102 load-combination logic — I do not have reliable,
verified access to current CIRSOC clause numbers/values and did not want to
fabricate citations. What is implemented is an elastic, Fy-based
interaction check (Von Mises-type: `sqrt(sigma^2 + 3*tau^2)/Fy`) at each
opening/post/torsion station, in the *format* CIRSOC 301 and AISC 360
share (elastic stress interaction under factored loads). **Before this is
used for a real stamped design, the engineer of record must apply the
actual current CIRSOC 301 resistance factors (phi) to the utilization
ratios this module reports, and must build V(x)/M(x)/T(x) from load
combinations per CIRSOC 101/102 — this module does not select or combine
load cases for you.** The complementary-criteria note in the original
request (AISC 360 / Eurocode 3 for local opening behavior) is what the
Vierendeel/web-post/torsion formulas below actually follow, since that
literature is where these specific local checks are documented in
detail.

## 2. Libraries / dependencies

Standard library only: `math`, `dataclasses`. No numpy/scipy — every
formula here is closed-form or a short explicit loop, so an extra
dependency wasn't justified. Version: whatever Python 3.x the rest of this
program already requires (`dataclasses` needs 3.7+; the rest of the repo
already assumes a modern CPython since it uses f-strings and `tkinter`).
The UI (`perforated_beam_app.py`) uses only `tkinter`/`ttk`, matching every
other tab.

## 3. Assumptions (geometry, loading, boundary conditions)

Stated explicitly because every one of these is a scope decision, not an
accident:

1. **Single-span, simply supported, forked-end beam.** Both V(x)/M(x) and
   T(x) assume two supports (x=0, x=L), vertically simple and torsionally
   "forked" (twist restrained, warping free). Continuous/cantilever/
   propped-cantilever beams are **not** supported yet — see §5.
2. **Openings live entirely in the web.** A polygon that reaches into a
   flange (`net_section_at`'s `y_hole_top > d - tf` or `y_hole_bot < tf`)
   is flagged invalid at that station, not silently clamped into a wrong
   answer.
3. **Openings are centered on the section's mid-depth** (neutral axis for
   a doubly-symmetric section). An intentionally off-center opening isn't
   representable directly; model it as a custom polygon shifted in its own
   local `y`, understanding the "mid-depth" assumption in
   `OpeningInstance.vertices_abs` no longer matches physical intent for
   that specific case.
4. **Each opening's polygon is "y-simple":** any vertical line through its
   x-range crosses the boundary at exactly one entry/exit pair (true for
   every circle/hexagon/rectangle this module generates; true for most
   sensible single-opening custom polygons; **not** guaranteed for a
   deliberately re-entrant/self-intersecting custom polygon — see
   `opening_polygon`'s docstring).
5. **Point of contraflexure for the Vierendeel (secondary) moment is at
   each opening's geometric mid-length**, independent of the local netted
   stiffness variation across an asymmetric/polygon opening. This is the
   standard simplifying assumption in this check family (see §4); what
   *is* generalized here is that the **net section itself** is evaluated
   station-by-station from the real polygon, so an asymmetric opening's
   worst station can be found anywhere along its length, not just assumed
   at its physical edge.
6. **Global shear at an opening splits between the top/bottom tee in
   proportion to their moment of inertia** (`I_top/(I_top+I_bot)`), the
   standard approximation for this check (parallel-chord/Vierendeel-panel
   analogy), not a compatibility-based (stiffness-matrix) split.
7. **Torque reactions/diagram assume uniform GJ along the span** — see the
   derivation in `perforated_beam_math.global_T`'s docstring: for a
   uniform-GJ member with twist-restrained ends, the torque diagram has
   exactly the same closed form as a transverse-load shear diagram, which
   is what lets `T(x)` reuse `_point_diagram`/`_dist_diagram` directly.
   Local J reduction at an opening affects the *local* torsional stress
   check there, not the assumed global reaction split.
8. **St. Venant (uniform) torsion only** — no warping/bimoment (Vlasov)
   analysis. See limitations, §5.
9. Root fillets are ignored in all rolled-section property formulas
   (slightly conservative: real A, I, Zpl are marginally higher).

## 4. Formulas / methods implemented, with references

- **Rolled-section properties** (`RolledSection.A/I/S/Zpl/J`): standard
  closed-form composite-rectangle formulas for a doubly-symmetric I/W
  shape (any mechanics-of-materials or AISC Steel Construction Manual
  reference); `J` is the open thin-walled "sum of `b*t^3/3`" approximation
  (no fillet correction), commonly used for a first-pass torsion check.
- **Net tee-section properties at an opening station**
  (`net_section_at`/`_rect_pair_tee`): the tee above/below a web opening is
  treated, at each station, as a web stub + attached flange, combined by
  the standard parallel-axis theorem. This is evaluated at multiple
  stations across the opening's length (not just at its physical edges),
  driven by `polygon_y_span_at_x`'s general line/polygon intersection —
  this is what lets an *arbitrary* polygon opening be checked, generalizing
  the shape-specific formulas typically published for circular/hexagonal
  openings only (e.g. SCI Publication P355, "Design of Composite and
  Non-Composite Cellular Beams"; AISC Design Guide 31, "Castellated and
  Cellular Beam Design").
- **Vierendeel (secondary) moment** (`analyze_opening`): shear split
  between tees by `I` ratio, local moment = tee shear × distance to the
  assumed mid-length contraflexure point, combined with the tee's share of
  the global moment (as an axial force couple through the two tee
  centroids) into a combined normal stress, combined with tee shear stress
  via a Von Mises-type interaction. This is the standard methodology
  described in AISC Design Guide 31 and SCI P355, generalized here to an
  arbitrary polygon net section rather than their closed-form
  circular/hexagonal expressions.
- **Web-post shear/buckling** (`analyze_webpost`): **this is the one check
  where I deliberately did NOT try to replicate the shape-specific
  empirical SCI P355 curves** (those are calibrated specifically to
  circular and hexagonal post geometry, and applying them to an arbitrary
  polygon post shape would be a false-precision extrapolation, not a
  generalization). Instead this module uses the classical elastic
  plate-buckling-in-shear formula for a simply-supported rectangular plate
  (Timoshenko & Gere, *Theory of Elastic Stability*, 2nd ed., the
  `k = 5.34 + 4*(a/b)^2` shear-buckling coefficient for a plate with
  aspect ratio a/b ≤ 1), applied to the web post's clear width/height,
  capped at shear yield (`Fy/sqrt(3)`). This is a generalized,
  conservative-leaning method appropriate for arbitrary post shapes; for
  standard circular/hexagonal layouts, cross-check against the
  shape-specific SCI P355 curves before relying on this alone in
  production (see limitations).
- **Combined bending + torsion + doubler-plate sizing** (`analyze_combined`
  / `_combined_util`): elastic bending stress (`M/S`) plus additive shear
  from transverse shear and St. Venant torsion, combined via the same Von
  Mises-type interaction, in the spirit of AISC 360 Chapter H's stress-
  interaction format (H3 addresses torsion). Doubler-plate sizing is a
  straightforward search: add plate thickness to the web (`tw + extra_tw`)
  in `step` mm increments, recomputing shear area and `J`, until the
  interaction ratio drops to ≤ 1.0 or `max_doubler` is reached.
- **Deflection** (`deflection_profile`): double numerical integration
  (trapezoidal rule) of `M(x)/(E·I_net(x))`, with `I_net(x)` from the same
  netted tee-section machinery used for the Vierendeel check, and the two
  integration constants solved from `v(0)=v(L)=0`. Informational only —
  see limitations.

## 4b. Additional section types (channel, built-up double-channel, custom profile)

Beyond the doubly-symmetric `RolledSection`, three more section types can
be used as `BeamConfig.section`:

- **`ChannelSection`** — a single rolled U/C channel. Its strong-axis
  `Ix` uses the exact same closed form as `RolledSection.I` (flange
  x-offset doesn't affect a strong-axis second moment); `Iy`/`x_bar` are
  provided for completeness but nothing in this module's checks uses the
  weak axis.
- **`BuiltUpDoubleChannelSection`** — two identical channels placed with
  their flanges facing inward across a central gap ("toes-in"), at the
  same height, meant to be tied together at intervals by welded plates
  spanning that gap. Because both channels sit at the same height, each
  one's own centroidal axis *is* the combined section's neutral axis, so
  `Ix_total = 2 * channel.Ix` exactly — no parallel-axis term needed.
  `design_builtup_connector()` sizes those tie plates from the torque
  demand `T(x)` using classical Bredt thin-walled closed-section shear
  flow, `q = T / (2*Am)`: an unconnected channel pair is torsionally very
  weak (two open sections), and tying the flanges together lets the pair
  act as a closed box for torsion — the plates must carry the shear flow
  that closing action requires. **This is a mechanics-based
  torsion-transfer sizing check only** — it does not implement any
  specific code's built-up-member connector *spacing/stability*
  provisions (e.g. AISC 360 D4/E6-style slenderness-ratio spacing
  limits); if those also govern your design, check them independently.
- **`CustomProfileSection`** — an arbitrary simple closed outline (from
  `section_profile_ui.py`'s Line/3-point-Arc designer, arcs discretized
  into straight segments), with `A`/centroid/`Ix`/`S_top`/`S_bot`/`d` all
  computed numerically by 2D polygon integration (Green's-theorem area
  moments) rather than a shape-specific formula — verified against known
  closed-form results (rectangle, and a T-shape cross-checked by an
  independent parallel-axis hand calculation) in
  `tests/test_perforated_beam_math.py`. It deliberately does **not**
  expose `Aweb`/`J` — there's no general way to infer "the web" or a
  meaningful torsion constant from an arbitrary outline.
- **`BuiltUpDoubleSection`** — generalizes `BuiltUpDoubleChannelSection`
  to accept any TWO base sections (`base_a`, `base_b` — `base_b` defaults
  to `base_a`, the common case of doubling one profile, but can be a
  genuinely different section, including a different custom-drawn
  profile, for an asymmetric built-up pair), since the "both pieces share
  the combined section's neutral axis" combination logic (`A`/`I` simply
  add; `Aweb`/`J` too, when BOTH bases provide them) holds for any two
  side-by-side shapes vertically aligned at the same centroidal height —
  not just identical channels. `d`/`S_top`/`S_bot` use
  `_y_fiber_distances` on each base independently and take whichever
  extends further in each direction, so two bases of different depths or
  asymmetric shapes combine correctly, not just doubly-symmetric
  identical pairs. Unlike `BuiltUpDoubleChannelSection`, the
  plate-spanned `gap` has to be given directly rather than derived from
  `bf`, since there's no generic way to infer it from an arbitrary base's
  own geometry. **Important caveat for a doubly-symmetric base** (a full
  I/W section): the connecting plates only tie the *inner* flange tips
  together, so the resulting `enclosed_area` (used by
  `design_builtup_connector`'s Bredt calculation, computed from `base_a`
  only) leaves the *outer* flange overhangs outside the idealized closed
  box — treat that connector sizing as approximate (understating the true
  shear flow) for a doubly-symmetric base, and even more approximate if
  `base_a`/`base_b` differ substantially in size; it's exact for a
  channel-like (one-sided flange) base, same as
  `BuiltUpDoubleChannelSection`.

**Section protocol.** Any type used as `BeamConfig.section` must expose
`A`, `I`, `S`, `d`. `Aweb`/`J` are optional: `_combined_util` duck-types
on their presence and automatically degrades to a bending-only check
(clearly flagged in the result's `note`, not silently treated as zero
shear/torsion risk) when they're absent. **`ChannelSection` conforms to
this too** (`.d`/`.I` alias its own `.h`/`.Ix`, and it exposes `.Aweb`)
specifically so it can be used standalone as a `BuiltUpDoubleSection`
base, not just as an ingredient of `BuiltUpDoubleChannelSection` — a real
bug during development (caught by testing every base-profile kind through
the actual UI, not just the math in isolation) was `BuiltUpDoubleSection`
assuming every base had `.I`/`.d`/`.Aweb`, which was true for
`RolledSection` but not for a bare `ChannelSection` before this fix; see
`test_builtup_double_section_with_bare_channel_base_runs_end_to_end`.
Web-opening perforation support (`net_section_at`, Vierendeel, web-post)
is explicitly `RolledSection`-only — `BeamConfig.__post_init__` raises
immediately if openings are combined with any other section type
(including an `OrientedSection` wrapping a `RolledSection` — see §4c;
that check is `isinstance`-based, and rotating the section makes the
opening/net-section geometry genuinely inapplicable anyway), rather than
silently producing a wrong net section for geometry this module's opening
math was never built around.

## 4c. Orientation (`OrientedSection`)

This module has no way to know how a catalog (or custom) section is
actually installed relative to gravity — a rolled shape's catalog
listing implies nothing about site orientation. `OrientedSection(base,
rotate90=False, mirror=False)` wraps a *simple* section (`RolledSection`,
`ChannelSection`, or `CustomProfileSection` — explicitly NOT another
built-up or already-oriented section; `__post_init__` rejects that) to
correct for it:

- `rotate90=True` swaps which of the section's own two in-plane axes
  resists vertical (gravity) bending — its own weak axis (`Iy`) becomes
  what this module treats as strong/vertical. This is the orientation
  choice that actually changes any computed result, and required adding
  `Iy` (plus, for `CustomProfileSection`, `x_extent`) to every simple
  section type — verified against independent parts/parallel-axis hand
  calculations the same way `I`/`Ix` already were (see §6).
- `mirror=True` flips top and bottom (swaps `S_top`/`S_bot`). Only
  matters for a shape that isn't symmetric about its own centroidal
  horizontal axis — i.e. only a custom-drawn asymmetric profile; it's a
  provable no-op for `RolledSection`, `ChannelSection`, or either
  built-up type, all of which already are symmetric that way.
- `J` passes through unchanged either way — torsional resistance about
  the beam's own longitudinal axis doesn't depend on which way the
  cross-section faces gravity, a real physical invariant, not an
  approximation.
- `Aweb` passes through unchanged when not rotated; when rotated, it's
  re-derived as `2*bf*tf` if the base provides `bf`/`tf` (using the
  flanges as the new "vertical" shear-resisting elements — the natural
  analogue of the un-rotated `(d-2tf)*tw` formula, same *style* of
  approximation as that formula already is), and is otherwise
  unavailable (graceful bending-only degrade via the same duck-typing
  every other section type without a defined web already uses).

Composes with everything else in §4b: an `OrientedSection` can be used
directly as `BeamConfig.section`, or as a `base_a`/`base_b` for
`BuiltUpDoubleSection` (e.g. "a 90°-rotated channel, doubled" — the
double correctly uses the rotated `Iy`-based properties; see
`test_builtup_double_section_of_oriented_channel_matches_iy`). It does
NOT compose with `BuiltUpDoubleChannelSection` specifically, since that
class needs the base channel's raw `bf`/`tw`/`tf`/`h` for its own
gap-derivation geometry, not just the general `A`/`I`/`S`/`d` protocol —
use `BuiltUpDoubleSection` with an oriented `ChannelSection` base instead
if an oriented double-channel-like arrangement is needed (the UI's Double
channel mode panel says as much).

In the UI, every "pick a base profile" widget (the two single-section
modes, and each of Double profile's two independent Profile A/B pickers)
has its own Rotate 90°/Mirror checkboxes, built once via
`_build_orientation_row`/`_build_base_picker` and reused rather than
duplicated per mode.

## 4d. Movable supports (overhangs)

`BeamConfig.supports = (xA, xB)` (default `None` → `(0, L)`, i.e. supports
at both ends) lets the two supports sit anywhere along the span, including
inset from the ends to create overhangs on one or both sides — still a
**determinate 2-support beam only** (no more than 2 supports, no fixed
ends; `__post_init__` validates `0 <= xA < xB <= L`). The reaction-split
kernels (`_point_diagram`, `_moment_diagram`, `_dist_diagram`) were
generalized from their original "supports fixed at 0 and L" form to sum
contributions from anything strictly left of the cut using `[x > xA]`/
`[x > xB]` indicators — this reduces to the exact original formulas when
`xA=0, xB=L` (verified in
`test_overhang_generalization_matches_default_end_supports`), and was
independently checked against two textbook overhang cases: a symmetric
overhang with a midspan load, and a load placed *on* the overhang
(producing the expected negative/uplift reaction at the far support) —
see `test_symmetric_overhang_reactions_and_midspan_moment` and
`test_load_on_overhang_produces_uplift_reaction`. `deflection_profile`'s
boundary conditions (`v=0`) are enforced at the actual support positions
(interpolated on the integration grid), not hard-coded to the beam's own
ends.

In the UI, `profile_sketcher_ui.py`'s "Sketch profile…" canvas has
"Place support A" / "Place support B" buttons — click one, then click on
the beam envelope to set that support's x-position (drawn as a triangle
marker); Apply sends the resulting `(xA, xB)` back to
`PerforatedBeamApp.supports` alongside the opening layout.

## 5. Known limitations

- **Single-span, simply supported beams only.** No continuous, cantilever,
  propped-cantilever, or multi-span capability yet. Adding this is a
  statics-layer change (`global_V_M`/`global_T`/`reactions`), not a
  restructuring of the opening/section machinery above it — that's the
  intended extension point.
- **St. Venant torsion only — no warping/bimoment (Vlasov) analysis.** For
  members where restrained warping produces significant additional normal
  stress (short spans, torque near a rigid end, open thin-walled sections
  generally), this module's torsion check is a simplification and may
  under-predict demand. A full warping-torsion module (4th-order ODE,
  `GJ`/`ECw`, boundary-condition-dependent) is a substantial, separate
  effort — do not attempt to patch it into `_combined_util` incrementally;
  design it as its own function that returns an additional bimoment/normal
  stress term, tested against a published closed-form warping-torsion
  example, before wiring it in.
- **Web-post buckling uses a generalized elastic plate formula, not the
  shape-specific empirical SCI P355 curves.** Treat its output as
  conservative-leaning and indicative for arbitrary/custom post shapes;
  for standard circular or hexagonal (castellated) layouts, an
  independent check against the published SCI P355 curves is recommended
  before relying on this module alone.
- **Deflection is informational**, not a governing serviceability check —
  it does not add the extra local Vierendeel-mechanism flexibility beyond
  what the reduced (netted) `I(x)` already implies.
- **Fatigue is out of scope entirely** (no cyclic-load / stress-range
  checking of any kind).
- **Root fillets ignored** in all section-property formulas (see §3.9).
- **CIRSOC 301 resistance factors and CIRSOC 101/102 load combinations are
  not implemented** — see §1. This module produces elastic utilization
  ratios from whatever V(x)/M(x)/T(x) the user's own load inputs already
  represent (the user is responsible for those being properly factored).
- **Opening shapes:** any simple, "y-simple" polygon is supported (§3.4);
  a genuinely re-entrant/self-intersecting custom polygon is not validated
  against and will silently produce a wrong net section rather than an
  error — if you add validation for this, put it in `opening_polygon`,
  not scattered across callers.
- **Double-channel connector design is torsion-transfer sizing only**
  (see §4b) — it does not check the individual channel's own local
  stability between tie points, nor implement a specific code's
  connector-spacing clause. It also assumes the "toes-in, tie plates
  bridging the gap" configuration specifically; other built-up
  arrangements (toes-out, lacing, battens on the web faces instead of the
  flange gap) are not modeled.
- **`CustomProfileSection` has no shear/torsion check** — see §4b. Only
  a bending (`sigma = M/S`) utilization is computed for this section
  type; if the actual member also needs a shear or torsion check, that
  has to be done independently outside this module.
- **The section-profile designer's arc tool only discretizes into
  straight segments for the math** (20 segments per arc, same style as
  `opening_circle`'s 48-gon) — very tight-radius fillets on a very large
  overall profile could show a slightly larger discretization error than
  usual; increase `ARC_SEGMENTS` in `section_profile_math.py` if a
  specific shape needs finer resolution.
- **Movable supports are still determinate-only** (§4d) — exactly 2
  supports, no fixed ends, no more than one span. Overhangs are fully
  supported; a genuinely indeterminate (3+ support, or fixed-end) beam is
  out of scope for this module and would need an actual FEM solver (like
  the plain Beam tab's `BeamModel`), not just a statics generalization.
- **`BuiltUpDoubleSection`'s connector sizing is exact for a channel-like
  base, approximate for a doubly-symmetric one** — see §4b. This only
  affects `design_builtup_connector`'s torsion-transfer number, not the
  section's own bending properties (A/I/S/d), which are exact for any
  base.
- **`OrientedSection` only wraps simple sections, and only supports the 4
  axis-aligned orientations** (identity, 90°, mirror, 90°+mirror) — see
  §4c. No arbitrary rotation angle, and it can't wrap
  `BuiltUpDoubleChannelSection` (orient the component channel via
  `BuiltUpDoubleSection` instead, as the UI itself points out). Rotating
  a section whose base has no `bf`/`tf` (e.g. `CustomProfileSection`)
  correctly drops `Aweb` (bending-only degrade) rather than guessing a
  rotated shear area for a shape with no well-defined "flange."

## 6. Validation performed

All in `tests/test_perforated_beam_math.py` and `tests/test_section_profile.py`
(83/83 passing across the whole app's test suite as of this writing; run
`python3 -m pytest -q tests/` from the project root). What each test
actually checks against, and why it's a real check rather than
"re-deriving the same formula and comparing it to itself":

- **UDL and point-load midspan moment vs. textbook closed form**
  (`wL²/8`, `PL/4`) — independent of this module's own implementation.
- **Global equilibrium cross-check**: `R0+RL` equals total applied force,
  and moment equilibrium about x=0 holds for a *mixed* load case (point +
  distributed + applied moment together), not just each load type in
  isolation.
- **Concentrated-moment jump**: an applied point moment must produce
  exactly that jump in the moment diagram and zero effect on the shear
  diagram — a specific, checkable signature of a concentrated moment, not
  a vague "looks about right."
- **Torque-diagram/shear-diagram equivalence**: confirms `T(x)` for a
  point torque numerically matches `V(x)` for an equal-magnitude point
  load at several stations — a direct test of the derivation in §3.7,
  not just "it runs."
- **Exact rectangular net-section area** and **circular polygon-area
  convergence to `pi*r^2` within 0.5%** at n=48 — geometry sanity where a
  closed-form "right answer" exists independent of this module.
- **Zero Vierendeel moment in a zero-shear region** (between two
  symmetric point loads): the Vierendeel moment is driven by shear, so a
  region with V=0 (constant M) must give Mv≈0 regardless of the opening
  shape sitting there — a physically meaningful sanity check, not a
  magnitude check.
- **Web-post monotonicity**: a narrower post must show higher utilization
  than a wider one under identical demand — checks the buckling formula's
  direction is right without asserting a specific "correct" number (which
  would require an external published example this module doesn't have
  access to).
- **Doubler-plate search monotonicity**: the sized doubler plate must not
  leave utilization *higher* than the no-plate case.
- **End-to-end smoke test**: a full uniform-circular-opening beam under
  UDL runs `analyze_beam()` without error and returns a complete report
  (right number of openings/web-posts, non-None governing case).

**What was not validated, honestly:** no comparison against a published
worked example from AISC Design Guide 31 or SCI P355 (I did not have
reliable access to a specific numbered worked example to check against
without risking a fabricated "reference" number) or against hand
calculations by a second person. Before production use, run at least one
of this module's checks against a known published cellular/castellated
beam example and compare, and update this section with the result.

## 7. Guidance to avoid debugging loops

- **If a Vierendeel utilization looks wrong at one specific station, check
  `polygon_y_span_at_x` first** by printing its `(y_min, y_max)` at that
  exact x before assuming the stress-combination formula in
  `analyze_opening` is at fault — a wrong net-section extent (e.g. because
  a custom polygon isn't actually "y-simple", see §3.4) silently produces
  a plausible-looking but wrong tee section, not a crash.
- **If web-post utilization seems too aggressive/conservative for a
  standard circular or hexagonal layout, that is expected — see §5.**
  Don't "fix" the buckling coefficient in `analyze_webpost` to match a
  specific SCI P355 number you recall without a citation you can verify;
  if you do calibrate it, add the source and a test that pins the
  reproduced value, rather than adjusting the constant by feel.
- **If `analyze_combined`'s doubler search hits `max_doubler` without
  converging, don't just raise `max_doubler` as the first move** — check
  whether the underlying demand (`V`, `M`, or `T` at that station) is
  itself unreasonable first (e.g. a load or eccentricity entered in the
  wrong units — this module is mm/N/MPa/N·mm throughout, and the UI labels
  every input's units for exactly this reason).
- **`_point_diagram` and `_dist_diagram` are the single shared kernel for
  both the bending (V, M) and torque (T) diagrams.** If you find a bug in
  one, check whether it's actually a bug in the shared kernel (affecting
  both) before writing a second, subtly different fix in only one call
  site — this is the same class of mistake documented in the Cable Web
  manifesto's §3j ("the same sub-problem solved in two places will drift
  unless it's actually the same code").
- **This module has zero Tkinter/UI dependency** (`perforated_beam_math.py`
  imports only `math` and `dataclasses`). If a bug reproduces through the
  UI, reproduce it directly against `perforated_beam_math` functions first
  (as the tests do) — it is far cheaper to isolate there than inside
  widget callbacks in `perforated_beam_app.py`.
- Standard verification checklist for any change here: run
  `python3 -m pytest -q tests/test_perforated_beam_math.py` (must stay
  fully passing) and `python3 -m compileall -q .` from the project root.
