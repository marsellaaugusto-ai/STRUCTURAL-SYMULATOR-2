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

**Standard: CIRSOC 301-2018, now implemented — see `cirsoc_301.py`.**
(Updated 2026-09-06. The previous text of this section said the opposite,
because the documents were not available then; it is quoted at the end of
this section so the change is legible.)

The Reglamento Argentino de Estructuras de Acero para Edificios,
CIRSOC 301, edition July 2018, which states in its own preface that it
adopts ANSI/AISC 360-2010 as its basis. Every resistance factor and
nominal strength used by this tab now comes from it, with the clause
recorded next to the number:

| what | clause | value |
|---|---|---|
| flexural resistance factor | F.1(1) | φb = 0.90 |
| Mn, compact doubly symmetric I | F.2.1 | Mp = Fy·Zx ≤ 1.5·My |
| lateral-torsional buckling | F.2.2, F.2.5a/b, F.2.6a, F.2.7a | Lp, Lr, Mr |
| shear resistance factor | G.1.1 | φv = 0.90 |
| Vn | G.2.1, G.2.2 | 0.6·Fyw·Aw·Cv, Aw = d·tw |
| Cv | G.2.3–G.2.5, kv = 5 per G.2.1(b) | — |
| normal stress, yielding | H.3.4 | fun ≤ 0.90·Fy |
| shear stress, yielding | H.3.5 | fuv ≤ 0.6·0.90·Fy |
| buckling limit state | H.3.6 | φc = 0.85 |
| section classification | Tabla B.4.1b cases 11, 16 | 0.38/3.76/5.70·√(E/Fy) |
| fillet weld | J.2.4 + Tabla J.2.5 | **φ = 0.60**, Fnw = 0.60·FEXX |
| effective throat | J.2.2(a) | 0.707·leg (45° equal-leg) |
| minimum fillet leg | Tabla J.2.4 | 3 / 5 / 6 / 8 mm by thickness |
| maximum fillet leg | J.2.2(b) | t (t<6), t−2 (t≥6) |

**Two findings from that transcription are worth stating loudly.**

1. **CIRSOC's fillet-weld resistance factor is 0.60, not AISC's 0.75.**
   CIRSOC adopts AISC 360-10 as its basis, but Table J.2.5 uses a lower
   φ for shear on the effective area of a fillet weld than AISC 360-10 or
   -16 do. Carrying the AISC number into a CIRSOC job overstates every
   fillet weld by 25%. This tab defaults to CIRSOC and keeps
   `cirsoc_301.AISC_360` for when an AISC job is genuinely intended.

2. **H.3.3 is not a von Mises criterion.** It checks normal stress and
   shear stress *separately* (H.3.4 and H.3.5). The `sqrt(σ² + 3τ²)/Fy`
   this tab previously reported is a defensible engineering check but is
   not what the clause says, and it carried no resistance factor at all.
   The reported utilisation is now the CIRSOC pair; the von Mises value
   is still computed and shown alongside, because in a strongly combined
   stress state it exceeds both and a preliminary check should see that.

**Web openings: CIRSOC G.8 states a duty, not a method.** In full: the
effect of any web opening on the design shear strength must be
determined, and where the required strength exceeds the design strength,
adequate reinforcement must be provided at the opening. That is the whole
clause. So the Vierendeel / web-post / doubler-plate machinery in §4 is
not in tension with CIRSOC — it is one way of discharging a duty CIRSOC
deliberately leaves open, with the method itself from AISC Design Guide
31 and SCI P355. What changed is that its stresses are now compared
against factored CIRSOC resistances instead of raw Fy.

**What is still yours, not the tool's.** This module computes
*capacities*. It does **not** select or combine load cases: the demands
V(x)/M(x)/T(x) come from the loads you enter, and it remains your
responsibility that those are FACTORED actions per CIRSOC 101
(permanent/live) and CIRSOC 102 (wind). Also still outside the tab: base
metal rupture at a weld's fusion face (J.4), intermittent-weld spacing,
transverse/eccentric weld-group effects, fatigue (Apéndice 3), and the
non-compact/slender flexure paths F.3–F.5 (a non-compact section is
detected and its Mn capped at My as a conservative stand-in, with a
notice, rather than run through the compact formula).

> *Superseded text, kept for the record:* "this module does not itself
> implement CIRSOC 301's specific clause-by-clause resistance-factor
> tables … I do not have reliable, verified access to current CIRSOC
> clause numbers/values and did not want to fabricate citations."

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

1. **Two support models.** The closed-form path assumes two supports
   (default x=0, x=L; movable, see §4d), vertically simple and torsionally
   "forked" (twist restrained, warping free). Passing `support_specs`
   instead routes the beam through `hyperstatic_math`'s stiffness solver,
   which accepts any number of supports, each pin/roller or fixed —
   continuous multi-span, propped cantilever, fixed-fixed and cantilever
   included. **Updated 2026-09-06; see §4e.** Warping is still free at
   every support in both paths.
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
~~Web-opening perforation support is explicitly `RolledSection`-only~~ —
**LIFTED 2026-09-06, see §4g.** Openings now work on any section that can
report its own geometry. `net_section_at` is still the exact path a
`RolledSection` takes; everything else clips the section's polygons at the
opening edges, which agrees with that closed form to ~1e-13. Only a
section with no describable shape is still refused — the restriction that
was always the real one.

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

## 4e. Hyperstatic supports (`hyperstatic_math.py`, added 2026-09-06)

`BeamConfig.support_specs = [SupportSpec(x, kind, torsion_restrained), …]`
replaces the `(xA, xB)` pair with an arbitrary support list, each entry
`'pin'`/`'roller'` (vertical restraint) or `'fixed'` (vertical +
rotational). This is the only thing that selects the path: with
`support_specs` unset, every formula in §4/§4d runs exactly as before.

**Method — direct stiffness, then equilibrium recovery.** 2-node
Euler-Bernoulli elements on a mesh whose nodes fall on every support,
concentrated action, distributed-load boundary and opening edge. The
solve is used for *one* thing: finding the redundant reactions. Once
those are known the beam is determinate, so V(x)/M(x) are recovered by
plain equilibrium integration from the left end, using the same
division-free trapezoid algebra as the closed-form path. This matters:
element end-forces would carry the Hermite shape functions'
discretization error into the diagrams, which equilibrium recovery does
not. The only approximation left in V/M is the reaction values, and those
converge fast.

**Why a mesh at all.** A perforated beam is not prismatic — `net_I_at`
already reports a reduced I(x) inside each opening. On a *determinate*
beam that variation changes only deflection, never V or M, so closed-form
statics stays exact. On an *indeterminate* beam the redundants depend on
the stiffness distribution, so the openings genuinely redistribute the
reactions. Each element takes its EI from `net_I_at` at its own midpoint.
`test_openings_shift_the_redundant` pins both halves of that statement.

**Torsion** is solved on the same mesh (1 DOF/node, GJ/Le), restrained at
every support flagged `torsion_restrained` — which is what lets an
*intermediate* support fork the section, something the 2-restraint closed
form cannot express. It degrades to the closed-form torque diagram when
the section exposes no usable `J` (a drawn profile), rather than inventing
one. Warping is still not modelled, as everywhere else in this tab.

**Conventions.** Reactions are reported `(x, R_up, M_ccw)` with R positive
UP and the couple in the same sense as an applied `PointMoment`, so it
drops straight into an equilibrium sum. Note this module's "+CCW" is CCW
in its own y-down frame — already the convention `_moment_diagram`
implements — which is why the nodal rotation DOF needs no sign flip. The
stiffness path reports the RIGHT-hand limit at a station where the
closed-form path reports the left-hand one; the difference shows only *at*
a support, and the right limit is what makes `M(0)` report a built-in
end's hogging moment instead of zero.

**Reporting caution.** The reaction *couple* equals the internal bending
moment only at the left-hand end; at the right-hand end it is its negative
(the diagram must close to zero past the last support). The UI therefore
prints the internal moment via `_support_moment`, not the raw couple —
otherwise a fixed-fixed beam under gravity reads as hogging at one end and
sagging at the other.

**Stdlib only**, like the rest of the tab: the banded Cholesky in
`_banded_cholesky` exists so no numpy dependency is introduced for a
system with half-bandwidth 3. Rotation DOFs are scaled by a characteristic
length before solving — without it the recovered reactions lost most of
their significant digits by a few hundred elements, visible as an error
that *grew* with refinement.

## 4f. Freely-placed profiles and welds (`welded_section_math.py`, 2026-09-06)

`CompoundSection([PlacedProfile(sec, dx, dy), …], welds=[…])` combines
profiles with each piece's own centroid placed at `(dx, dy)`, carrying the
parallel-axis terms that `BuiltUpDoubleSection` (§4b) is entitled to drop
because it assumes equal centroidal height. That assumption is exactly
what fails for a channel capping an I-beam or a plate welded to one
flange: the neutral axis moves, the section becomes singly symmetric, and
`S_top != S_bot`. `BuiltUpDoubleSection` is deliberately left alone rather
than generalized — its shortcut is correct for what it models.

`WeldLine` + `check_welds` then answer the question those composite
properties depend on: **a built-up section only behaves as one section if
the joint transfers the longitudinal shear flow between the pieces.**
`q = V·Q/I`, with Q the first moment about the combined neutral axis of
the material on the held side of the joint — whole parts summed directly,
a part the line cuts clipped against the half-plane, and a refusal (not a
guess) when the cut part is a rolled shape with no polygon to clip.
Capacity is `phi · 0.60 · Fexx · 0.707 · leg` per unit length, the same
expression `design_builtup_connector` already used, exposed as a
`WeldCode` dataclass — see §1: the resistance factor and electrode
strength are *data* precisely so the engineer of record sets them from
their own copy of CIRSOC 301, rather than inheriting numbers nobody
verified. Not checked: base-metal rupture, minimum/maximum fillet size for
the connected thickness, intermittent-weld spacing, transverse effects.

`CustomProfileSection` also gained `holes` — closed loops subtracted about
the same origin before the parallel-axis shift, exact rather than
approximate. It still refuses to report `J`/`Aweb`: a *closed* box drawn
with holes has a far larger torsion constant than the open-section formula
gives, so guessing there would be unconservative, not merely imprecise.

## 4g. Openings on any section (`general_net_section.py`, 2026-09-06)

`net_section_at` computes the tees above and below an opening from a
`RolledSection`'s `tf`/`tw` directly. That is exact and fast, and it is
why openings were refused on every other section type — a channel, a drawn
profile or a welded box has no `tf`/`tw` to put in those formulas.

The generalization rests on one observation: once a section can report its
own polygons (§4h), *the material above the opening* is that geometry
clipped by a horizontal half-plane. Clip, integrate, done — no per-shape
logic anywhere.

**Why this can be trusted.** For a `RolledSection` the two routes compute
the same integral by completely independent means — analytic rectangles
versus polygon clipping — and agree to **~1e-13** across every catalog
section and opening depth (`test_general_net_section.py`). That agreement
is what licenses the general path on shapes where no closed form exists to
check against. `RolledSection` still takes the closed-form path.

**`material_width_at`** is the general analogue of `tw`: the total
horizontal thickness of material at a height, by scanline. For a
two-channel welded box it correctly returns 20 mm at mid-depth — two 10 mm
webs — which no single `tw` attribute could have expressed, and which the
web-post check needs.

**What did NOT generalize.** The Vierendeel MODEL is a statement about
structural behaviour, not geometry: it assumes the two tees act as chords
of a Vierendeel panel. Past roughly 0.7d the tees are too shallow for that
to be the governing consideration and local buckling of the tee takes
over — which this module does not check. A warning says so, and is
collected across **every** station rather than read off the governing one:
for a circular opening the worst-stressed station sits off-centre where
the hole is shallower and raises no warning at all, so reading it off the
governing station hid the caveat entirely.

## 4h. Drawings (`section_shapes.py`, `perforated_beam_views.py`, 2026-09-06)

This tab was the only one in the program with no diagram of its own —
Truss has nine canvases, Arch/Beam/Cable three each, Perforated Beam had
none. Workable for a catalog I-beam whose shape you already know; useless
the moment the section is two hand-drawn profiles welded together.

`section_shapes.section_pieces` turns ANY section into polygons with the
origin at its centroid, so a view can draw the neutral axis at y = 0 with
no per-type special-casing. It is validated against each section's own **A
and I** — a drawing that disagreed with the computed properties would be
worse than no drawing, so the two share one source of geometry rather than
being written twice.

Four views: **Section** (both profiles in place, holes, welds, the
extreme-fibre distances that produce S_top/S_bot), **Elevation**
(openings, supports, loads), **Diagrams** (V, M, deflected shape),
**Axonometric**.

**Scale honesty.** A 50 m beam 1.8 m deep is 28:1; drawn true to scale the
depth collapses and the openings vanish. The elevation therefore scales x
and y independently, STATES the factor on the drawing, notes that circular
openings consequently appear elliptical, and offers true scale one click
away. The axonometric enlarges the whole cross-section by a single factor,
so the section's own proportions stay true — scaling only its width, which
was the first attempt, silently distorted them.

## 4i. How the pieces are joined (`AssemblyDetail`, 2026-09-06)

Two profiles butted and seam-welded along their full length form a
**closed cell**; the same two joined only by stitch plates do not.
Everything else about the section is identical — A, I, S, the drawing —
and **J differs by a factor of about 4000** (6.75e9 vs 1.71e6 mm⁴ for the
1800×500×10 box). With load eccentricity that is the difference between a
utilisation of 0.33 and one of 3.09.

The two cases need different FORMULAS, not merely different constants:
Bredt's `J = 4Am²t/Lm` and `tau = T/(2Am·t)` for the cell, `J = At²/3` and
`tau = T·t/J` for the open pair. Applying either to the wrong case is
unconservative. There is no defensible default between them, so it must be
declared: with no `AssemblyDetail` the section keeps refusing to report
J/Aweb and the combined check stays bending-only, which is the honest
outcome when nobody has said whether the seam is continuous.

## 4j. Excel round-trip (`perforated_beam_excel.py`, 2026-09-07)

The whole model in one file — export it, edit it, import it back. Every
other tab already had this; this one did not, and it is the tab where the
absence cost the most, because a cellular beam carries four things that
are all slow to re-enter by hand: a drawn profile, a support list, an
opening layout and a load set. Changing one number meant retyping all of
them.

**Format.** A `Model` sheet of `[BRACKETED]` blocks, each a header row
followed by data rows — the same shape the Beam, Arch and Cable tabs
already write, so there is one convention in the project rather than two.
Blocks are found **by name** and columns **by header**, never by row
number. That is what lets a block be added, moved or omitted without
breaking an older file, and it is what lets a hand-written sheet carry
only the blocks it wants to say something about: a missing block falls
back to its default rather than being an error. A `Results` sheet is
added when there is a report to write, and is never read back.

**Units** follow the drawings and the report: positions ALONG the beam in
metres, everything about the SECTION in millimetres, forces in N. Every
column header names its own unit.

**Openings are stored parametrically** — `Circle, 1350 mm` in one row,
not 48 vertex pairs — and the shape is recognised by RECONSTRUCTION: the
parameters are read off the polygon, the real constructor is called with
them, and the description is accepted only if the result matches vertex
for vertex. Anything that fails to match is written out as an explicit
vertex list instead. So the stored shape is never a guess about what the
user meant; it either regenerates the polygon exactly or it is not used.
A circle whose vertices have been nudged by 0.01 mm is stored as the
polygon it actually is, not as the circle it resembles.

**A drawn profile travels as its sketch**, not as its computed section,
and is rebuilt on import through the same `SectionSketch.to_section` the
designer's Apply button uses. There is therefore exactly one route from a
drawing to a section, and an imported profile is the same object a drawn
one would have been. Long sketches are split across numbered rows because
a spreadsheet cell has a length limit.

**Import parses the whole workbook before touching a single widget.** A
file that fails to read costs the user nothing — the model already on
screen is exactly as it was. This is the reason the read layer raises
`ValueError` with a sentence meant for a dialog rather than letting a
`KeyError` escape from three frames down.

**What it does not do.** It carries the MODEL, not the analysis: the
`Results` sheet is a record, and importing a workbook clears the report
rather than restoring it, because a report that no longer matches its
inputs is worse than no report. And a `Results` sheet is only written from
a report that still matches what is on screen — a workbook whose two
sheets disagreed with each other would be the worst possible artifact to
hand someone.

## 4k. Editing a drawn profile (selection, mirroring), 2026-09-07

The designer could draw a profile but not CHANGE one. Everything was
append-only: the single Undo walked the last segment back, and anything
else meant clearing and starting again. A symmetric section — which is
most built-up sections worth drawing — had to be entered twice, by hand,
with the second half's coordinates negated mentally.

**Selection** is by `(kind, index)`: the outline, hole *i*, or weld *i*.
Deliberately not by object identity, because Undo and Load rebuild the
lists those indices point into. Every operation that can shift an index
CLEARS the selection rather than trying to remap it — a stale index that
still resolves is far worse than an empty selection, since it would
silently mirror the wrong hole. Clicking inside a closed loop selects it,
and ties resolve to the last candidate, so the small thing drawn on top
of the big one is the thing the click gets.

**Mirroring runs on the sketch, not the flattened polygon**, so a
mirrored arc stays an arc and a mirrored circle stays a circle — the
drawing is still editable afterwards, which is the whole reason a sketch
exists rather than a point list.

Two things flip that are not coordinates, and both are silent if missed:

  * A `CenterArcSegment`'s `ccw`. A reflection reverses handedness, so an
    arc that swept counter-clockwise sweeps clockwise in the mirror.
    Mirroring only its centre and end leaves both endpoints correct and
    every point between them wrong — which changes A and I with nothing
    visibly amiss until the section is applied.
  * A `SketchWeld`'s `side`. `positive`/`negative` name the side the
    line's LEFT NORMAL points to, and a reflection reverses that normal.
    Left unswapped, an explicitly-sided weld silently changes which piece
    of steel it is claimed to hold. `auto` is resolved from area at check
    time and so needs no adjustment.

Both are pinned by tests that compare against the mirrored FLATTENED
polygon and against the held area from `check_welds` — the only
representations that cannot hide either error.

"Horizontal" flips left-for-right and "vertical" top-for-bottom: the
label names what MOVES, which is how CAD tools label the buttons, and it
is pinned by a test rather than left to the wording. The mirror line is a
drawing axis, the selection's own centre, or a typed coordinate; the
typed option exists for the seam of a two-profile box.

"As a copy" duplicates holes and welds. It does NOT duplicate the
outline — a sketch has exactly one boundary, so a second would have
nowhere to live. The outline is mirrored in place and the status line
says so, rather than the checkbox appearing to do nothing.

**`Profile B = mirror of Profile A`** on the tab's compound panel is the
same transform applied to the whole assembly: it builds B from A's
sketch and sets both offsets so the two meet edge to edge. One drawing,
both halves of a symmetric box, verified to give the same A, I and depth
as the pair entered separately.

## 4l. Holes are not web openings (2026-09-07)

These are different things, and the overlap in everyday language is a
real trap — it was reported as "I don't know how to apply the circular
openings to the custom profiles".

  * A **HOLE** is a void through the cross-section, present at EVERY
    station along the beam: a bolt hole, a service void. It is drawn in
    the profile designer and it changes A and I everywhere.
  * A **WEB OPENING** is a hole through the web at intervals ALONG the
    span — the 1.35 m circles of a cellular beam — with solid section
    between. It is laid out along x, and it is what this whole tab
    exists to check.

Nothing in the code was blocking web openings on a drawn profile:
`general_net_section` clips any section that can report its outline, and
a drawn profile always can. A 26-opening layout on a drawn lipped C
analysed correctly before this change as well as after. What was missing
was any route to it from the window the user was actually in, plus a name
collision that made the Hole tool look like the answer.

So the designer now carries a **web-openings panel of its own**, with the
one thing the tab's panel cannot show: the opening drawn ON the section
at mid-depth, where `OpeningInstance.vertices_abs` puts it. Whether a
1.35 m circle fits through what is being drawn is a question asked while
drawing, and it now has a picture rather than an arithmetic answer. The
panel reports the depth ratio with the 70% Vierendeel caveat, reports the
resulting web post, and refuses a spacing that does not exceed the
diameter. Applying writes back through the tab, which updates its own
panel to match so the two places that can set openings never disagree on
screen.

## 4m. What a weld drawn on a profile actually joins (2026-09-07)

Also reported: "it is not clear how applying the welds or where applying
the welds would join the two profiles." It was not clear because there
are three separate things and the UI named none of them:

  1. A weld drawn in the **designer** lives in ONE profile's own
     coordinates and holds one part of THAT profile onto the rest of it.
     It is translated into the compound's frame when the profile is
     placed, so it stays on its flange — but it does not join A to B.
  2. **`AssemblyDetail`** is what declares the seam between the two
     profiles: continuous (closed cell) or stitched (open). This is the
     consequential one — §4i.
  3. **"Extra weld lines (compound coordinates)"** on the tab is where a
     line that actually crosses BOTH profiles goes, because such a line
     has to be given in the assembled section's frame.

The designer now says this in the weld panel, and — more usefully —
reports what the SELECTED weld holds: its held area as a percentage of
the section, its Q, and the leg required per kN of shear. A weld line
that misses the steel reports zero shear flow, which in a report reads
exactly like a passing check; it is now stated in the window where the
line can still be dragged.

## 4n. The member check on ANY section (`section_plastic.py`, 2026-09-09)

`member_check` used to open with

    if not isinstance(sec, RolledSection):
        return None

on the argument that Chapter F needs Zx and Chapter G needs an
identifiable web. Both are true. Both are also recoverable from the
polygons, and that one guard silently removed gross flexure, global shear
AND lateral-torsional buckling from every built-up section this tab
exists to model. A user who drew the 50.4 m box girder got net-section
and Vierendeel results and a blank where the member check belongs.

**Zx** is the first moment of area about the equal-area axis, not the
elastic centroid. The axis is found by bisecting "area above the cut",
which is monotone in the cut height so bisection cannot find the wrong
root; then `Zx = A_top*|y_top - y_pna| + A_bot*|y_pna - y_bot|`. For a
doubly symmetric section that axis is the centroid; for the lipped-C box,
whose bottom lip is twice the top one, it is not, and capturing that
difference is the whole job.

Validated by CROSS-CHECK, not by assertion of plausibility: for a
RolledSection the generic route must reproduce the closed-form `Zpl` the
class already computes, for every section in the catalog, to 1e-9. Same
discipline `general_net_section` uses against `net_section_at`, and the
only thing that can validate the generic path on shapes where no closed
form exists.

**Web geometry.** For a rolled I, `Aw` and `h/tw` both come from `tw`.
For a welded box "the web" is TWO plates and no single `tw` exists.
`web_properties` scans the middle 60% of the depth -- where flanges and
lips cannot intrude -- and takes the height whose total material width is
smallest. Their widths are SUMMED for the area that yields and the
NARROWEST is used for the slenderness that buckles. That distinction is
worth a factor of two: calling the box's two 10 mm plates one 20 mm web
halves h/tw and roughly doubles Cv, in the unsafe direction.

`h` is the FULL depth rather than the clear distance between flanges --
conservative, and it avoids having to decide which material on an
arbitrary polygon is "flange". The rolled path is untouched and still
uses G.2.2's own `h = d - 2*tf`.

**Which clause applies** is decided by `flexural_family`, from what the
user DECLARED rather than guessed from geometry -- a closed box and a
stitched pair have identical outlines and different torsional behaviour
(S4i):

  * rolled I -> Chapter F2, unchanged;
  * a declared closed cell -> Chapter **F7**;
  * anything else -> plastification plus a conservative LTB bound.

F7 matters, and is not a refinement of F2. F2's Lr runs through
`Cw = Iy*h0^2/4`, a doubly symmetric OPEN-I identity; a closed cell warps
almost not at all and has no such Cw. Running a box through F2 does not
lose accuracy, it uses a formula for a quantity the section does not
have. F7 keys off J and A instead, and for a deep closed cell gives
Lr in the hundreds of metres -- which is the real reason a box is chosen
for a long unbraced span.

For a drawn section with no declared assembly there is no J either, and
LTB is then reported as NOT EVALUATED rather than guessed. Where J exists
but Cw does not, Cw is taken as 0: dropping the warping term can only
lower Mcr, so the answer is a lower bound, and it says so.

**Box walls are classified** (B4.1b cases 12 and 13) before F7 is allowed
to report anything. The 50.4 m girder turns out to have a slender flange
(b/t = 48 > 41) and a slender web (h/t = 180 > 166) -- neither checked by
the reference report. F7 covers compact and noncompact walls only, so Mn
is capped at My and the note says plainly that this is an UPPER BOUND on
the reduced capacity rather than a safe value.

## 4o. Transverse stiffeners and kv (G.2.6, 2026-09-09)

`shear_strength` was hardwired to `KV_UNSTIFFENED = 5`, with no way to
declare stiffeners that are actually there. For the box girder -- whose
stiffeners sit at a = h = 1.8 m -- that is `kv = 10` under G.2.6, and Cv
is linear in kv in the elastic range, so the tab was reporting half the
shear buckling capacity the beam has.

`BeamConfig.stiffener_spacing` (blank = unstiffened) now feeds
`web_shear_buckling_coefficient`, including G.2.1(b)'s two escapes back
to kv = 5: a panel longer than 3h, or longer than `[260/(h/tw)]^2` times
h, is too long in plan for the stiffeners to force the shorter buckling
half-wave the formula assumes. Blank remains the default because it is
conservative -- not because it is a guess that there are none.

## 4p. J is reduced for the openings (2026-09-09)

Bredt's J assumes an unbroken shear-flow loop around the cell. Web
openings cut that loop over most of the span, and a J computed as if they
were not there is unconservative wherever J enters a STABILITY check --
which for a box is exactly where it matters, since F7's Lp and Lr both
scale with sqrt(J). Using the gross J put Lr at 427 m where the reference
report has 216 m.

`effective_torsion_constant` scales J by the web-post-to-pitch ratio
S0/p, the fraction of the span over which the cell is actually
continuous. This is a RULE OF THUMB from cellular-beam practice, not a
CIRSOC or AISC formula, and it is stated as such wherever it appears. It
is applied because the alternative -- the gross J -- is wrong in the
unsafe direction, and a documented approximation beats a silent
optimism.

**Agreement with the reference report.** With these three in place, on
the report's own beam (LRFD, t = 10 mm, stiffeners at 1.8 m): Aw = 36,000
mm2 and h/tw = 180 exactly; Cv 0.397 against 0.397; Vn 2013 kN against
2014; util_shear 0.182 against 0.18; util_flexure 0.367 against 0.37;
Lp 7.52 m against 7.7 and Lr 213 m against 216. The residual ~2.5% on the
section properties is the report's mid-line model double-counting the
corner squares where flange meets web; this tab integrates the real
polygon and does not.

## 4q. The 3-D view tells depth now (2026-09-10)

Reported as "out of proportion and i cant tell depth". Three separate
faults, all real:

**The cross-section was enlarged against the span.** `_section_scale`
returned `(L/8)/d` unconditionally -- x3.5 on the 50.4 m box girder, so
the drawing showed a beam that does not exist. True scale is now the
default, matching the Elevation, which had already made this trade the
other way and been corrected once (S4h). The enlargement remains as a
checkbox that states its factor.

**Nothing was hidden.** Every edge was drawn solid whether it sat at the
front of the section or behind 500 mm of steel, so a two-web box read as
a single plate. `section_shapes.occluded_in_section` decides it: with
this projection the direction toward the viewer is `(+0.433, +0.25, -1)`,
and a beam is an extrusion along x, so whether a point is hidden does not
depend on x at all -- it is settled in the section's own (z, y) plane by
walking toward the viewer and asking whether the walk passes through
material. Hidden edges are drawn DASHED, which is the drafting
convention and the thing that actually conveys depth.

**The end faces were painted in the wrong order.** The visible end is the
one at x = L, whose outward normal faces the viewer; x = 0 points away.
The old code drew the far end first and then painted the HIDDEN end
opaquely on top of it.

Openings are also drawn on EVERY web plane rather than only the front
one -- 26 solid outlines and 26 dashed on the box girder, which is most
of the depth cue on its own. `section_shapes.web_planes` reuses the same
material scan Chapter G uses, so "what counts as a web" has one
definition in this app rather than two.

The wheel always zoomed; nothing on screen said so. Fit / + / - buttons
and a one-line hint now make it discoverable.

## 4r. Doubler rings at the openings (`opening_reinforcement.py`, 2026-09-10)

When the Vierendeel check fails there are three ways out: thicken the web
over the whole span, shrink the openings, or weld a doubler ring around
the few holes that actually need one. The tab could report the failure
but not size the fix, so the third option -- the one the cellular-beam
literature actually recommends, and the one that saves most of the steel
-- could not be evaluated here at all.

**The ring is modelled by building the reinforced SECTION and running the
tab's own opening check on it.** `analyze_opening` gained one optional
argument, `section=`, which overrides the geometry used for net-section
properties while leaving the statics on the beam as built. So a doubler
is evaluated by exactly the machinery that evaluates everything else,
and there is no second Vierendeel model to drift out of step with the
first. That one-line hook is the whole reason this module is small.

The plate is laid on the OUTER face of every web -- the face a fabricator
can reach -- and covers the full height of the tee above and below the
hole. Covering the whole tee rather than a radial band is the
simplification SCI P100 users make by hand and the reference report makes
too; it is slightly conservative where the real ring would be narrower.

**Sizing is by bisection, not by formula.** The tee's area, its modulus
and the net inertia all change with the plate and do not combine into
anything worth inverting. Each trial is a full evaluation. The search is
justified by monotonicity -- a thicker ring never raises the utilisation
-- which is pinned by a test rather than assumed.

**The frame conversion is the part that bites.** `section_pieces` renders
a part at internal dx as `(dx - cx)`, so a ring computed in the centroid
frame goes in at `dx = p + cx`. Drop the `+cx` and the doubler lands a
centroid-offset from the hole -- and the area and the inertia still go
up, so every summary number still looks plausible. Only a position check
catches it, and there is one.

**The weld is governed by the code minimum, not by strength.** A doubler
picks up very little shear flow -- 13 N/mm on the worst opening here --
so a strength-only answer is 0.1 mm, which is not a weld. Table J.2.4
decides it, and the result says which of the two governed rather than
leaving a reader to wonder why a 13 mm plate is held on by a fillet a
tenth of a millimetre thick.

**Against the reference report.** It required a 28.9 mm ring at x = 17.1
m where this gives 13 mm. That is the same ~6x difference already
documented for the Vierendeel check itself: the report pairs the minimum
tee depth (which occurs at the hole's centre) with the maximum lever arm
(which occurs at its edge), a combination that never happens in a
circular opening. Neither number is a substitute for a shell model at one
opening.

NOT CHECKED: the ring plate's own local buckling; its effect on web-post
buckling (which the added thickness helps, so ignoring it is
conservative); and whether a thick doubler can practically be welded to a
thin web at all, which needs a bevel and several passes.

## 4s. Converging with a hand-written report (2026-09-10)

A user brought a written analysis of the same 50.4 m box girder and the
same openings, and the two documents did not agree. The tab said no
opening needed a doubler ring; the report devoted a section to sizing
them. Both were right, and neither said enough for anyone to see why.

**The gap decomposes exactly.** Feeding the report's own assumptions into
the tab, one at a time:

| step | shear util | flexure util | opening at 17.1 m |
|---|---|---|---|
| the user's model as exported | 0.25 | 0.24 | 0.55 |
| + Fy 235 rather than 250 (report H5) | 0.25 | 0.26 | 0.59 |
| + stiffeners at 1.8 m (report H8) | 0.13 | 0.26 | 0.59 |
| + 28 openings from x = 0.9 m (H4) | 0.13 | 0.26 | 0.59 |
| + LRFD 1.2D + 1.6L (H3, H6) | 0.18 | 0.37 | 0.84 |
| the report itself | 0.18 | 0.37 | 3.56 |

Reactions match to four figures at every step (82.0 / 585.1 / 321.3 kN
factored). Shear and flexure land on the report's own printed numbers.
**Everything converges except the Vierendeel check**, and what is left
there is not an error on either side -- it is two different models of the
same opening.

### The two Vierendeel models (`vierendeel_hand.py`)

The tab evaluates nine stations across each hole against the real net
section at each. The report uses the closed form: the tee depth at the
hole's CENTRE paired with a lever out to the hole's EDGE, and the flange
left out of the local modulus. For a RECTANGULAR opening those hold at
once. For a CIRCLE they never do -- at the centre the lever is zero, at
the edge the tee is the full half-depth -- so the closed form runs about
4x higher. Both simplifications are conservative, so it is a safe upper
bound rather than a mistake.

The answer was not to change either calculation. It was to implement the
second one as well and print BOTH on every report, with the ratio and the
reason. `vierendeel_hand.check_opening` reproduces the reference to
within 0.8% on the governing opening, including `f_loc = 649.2 MPa` to
the printed digits; the residual is entirely that the report models the
section on its mid-line while this integrates the real polygon.

### Two findings that came out of doing it

**The reference's ring table misses eleven openings.** Its own tabulated
shears show it: every opening it flags has POSITIVE V, and every opening
it declares "sin refuerzo" while showing a large demand has NEGATIVE V --
including x = 15.3 m, which its own M and V require a 21 mm ring for,
thicker than five of the seven it does specify. A signed comparison where
a magnitude was meant. Running the same beam by the same method, this tab
finds 19 openings needing a ring against the report's 8.

**Load combinations were genuinely missing here** (`load_combinations.py`).
The tab checked the loads as entered and printed a disclaimer saying so.
That is honest, and it was also 1.44x of the disagreement. ASD is handled
by scaling the utilisation by phi*Omega rather than by a second set of
capacity equations -- an identity, given that the code calibrates
Omega = 1.5/phi, and one that cannot drift out of step with the LRFD path
the way a parallel implementation would.

## 4t. Does the section actually hold together? (`assembly_check.py`)

The same workbook contained a worse problem than any of the above, and
nothing in the tab could have surfaced it: **the two C profiles were
1.94 mm apart.** Their offsets were 391 mm where the geometry needs
389.06. They touched nowhere. The tab reported A, I, S, a shear area over
two webs and a Bredt J for a declared closed cell -- every one of those
numbers describing a single piece that does not exist.

This failure mode is invisible by construction: gluing two pieces
together in software only ever makes the numbers BETTER, so a wrong
answer looks like a healthy one. `part_gaps` measures the real clear
distance between every pair of parts, and the audit says plainly that the
section properties above it cannot be trusted -- and, when a closed cell
was declared over a gap, that J and the torsional stress are not
approximate but wrong.

### The weld report answered "0.00 mm" and it was not helping

The seam of that box reported `q = 0.0 N/mm -> 0.00 mm leg`, twice, plus
a note that the connected thicknesses had not been stated. Both halves of
that were fixable:

**q really is zero, and that is real mechanics.** On a section symmetric
about the seam, each half's centroid sits at the height of the whole
section's, so V*Q/I vanishes exactly: vertical bending does not push one
half of a symmetric box past the other. The seam is still what closes the
cell and earns the section its J, and it carries the Bredt flow
q = T/(2*Am) under torsion. `symmetry_note` says this on the report, so a
correct zero stops reading as a broken tool. It is triggered by Q being
zero -- the held centroid at the section centroid -- and NOT by the
required leg being small, which is true of nearly every longitudinal seam
and once put "q is essentially zero" under a joint carrying 95 N/mm.

**The thicknesses never had to be typed.** `weld_contact` walks out from
the weld's own midpoint along its normal and measures what it finds on
each side. That turns a blank Table J.2.4 lookup into "5 mm minimum for a
10 mm part" -- an answer a fabricator can use. Stated values still win:
the user knows things the geometry does not.

Two frame conversions decide whether any of this means anything, and both
are silent when wrong. Weld lines live in the PLACED frame while
`section_pieces` renders in the CENTROID frame, so the walk must subtract
the centroid exactly as `section_welds` does -- 179.5 mm on this section,
enough to report empty space beside a perfectly good weld. And
`_pieces_of_part` must repeat `section_pieces`' own translation without
subtracting the inner centroid a second time.

### "Weld the seam", because the question was unanswerable

The user's actual words were "i still dont understand how the welding
tool works, how d i make sure the profiles are properly welded
together??". They were right that there was no way to find out. A weld
was four coordinates typed into a frame the panel did not name, and a
line that missed its seam reported a comfortable q = 0 -- so a wrong
weld and a right one produced the same reassuring output.

`contact_runs` finds every stretch where two parts touch, and the button
puts a weld on each. Contact needs three conditions at once -- parallel,
within tolerance, and overlapping when projected onto the shared
direction -- because distance alone calls a corner grazing a face a
weldable seam. Runs are merged, since two profiles meeting along one
face produce the same seam once per edge pair that sees it.

When it finds nothing, that IS the answer, and the dialog says what it
means: the profiles are not in contact, so there is no seam, and every
section property on the report describes a piece that does not exist.

## 4u. Two ring bugs the tests found (2026-09-10)

**A rolled catalog section could not be ringed at all.**
`reinforced_section` asked for `section.centroid`, which a
`RolledSection` does not have, so ticking "Size doubler rings" on an IPE
-- the commonest section this tab is used with -- raised AttributeError
and took the whole analysis down. The feature appeared to work only on
drawn and compound profiles, which carry a centroid because they are
positioned in a drawing frame. A rolled shape is rendered about its own
centroid already, so its offset is (0, 0) by construction.

**An open web got half a ring.** The plate was laid on "the outer face of
every web", decided by comparing the web's midpoint with the section's.
A lone central web has its midpoint AT the section's, so the comparison
put one plate on its left and none on its right -- on every open section,
silently. Which faces are reachable is the real question: nobody can weld
inside a closed cell, so a box's webs take a plate outside only, while
both faces of an open web are accessible and both are welded.

## 5. Known limitations

- ~~**Single-span, simply supported beams only.**~~ **LIFTED 2026-09-06.**
  Continuous, cantilever, propped-cantilever and multi-span beams are now
  supported through `support_specs` and `hyperstatic_math` (§4e). It went
  in exactly where this note predicted — as a statics-layer change behind
  `global_V_M`/`global_T`/`reactions`, with the opening and section
  machinery above it untouched.
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
- ~~**CIRSOC 301 resistance factors … are not implemented**~~ **LIFTED
  2026-09-06** — the factors and nominal strengths are now transcribed
  from CIRSOC 301-2018 with clause references (§1, `cirsoc_301.py`).
  **CIRSOC 101/102 load combinations remain NOT implemented**: this module
  produces utilisation ratios from whatever V(x)/M(x)/T(x) the user's own
  load inputs represent, and the user is still responsible for those being
  properly factored.
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
- ~~**Movable supports are still determinate-only**~~ **LIFTED
  2026-09-06.** This note called it correctly: an indeterminate beam did
  need an actual solver rather than a statics generalization, and that is
  what `hyperstatic_math` is (§4e). The closed-form path of §4d is
  unchanged and still handles the determinate 2-support case, overhangs
  included; `support_specs` opts into the solver.
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
