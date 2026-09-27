# The Stereo PDF report — what is on each sheet, and why

`apps/stereo/stereo_reports.py :: export_pdf`, reached from the Stereo
tab's **Export PDF…** button. Sheets are A4 landscape (ISO 216 / ISO 5457).

## What changed on 2026-09-27, and what it fixes

| Complaint | What was wrong | What it is now |
|---|---|---|
| "issues with the references" | Two legends per sheet that disagreed. The patch legend quoted hard-coded hexes — `#e6b800` for utilisation 0.5, `#aaaaaa` for "near zero", `#888888`/`#555555` for pin/rigid — that none of the colour functions ever produce. The real values are `UTIL_MID #f9a825`, `NEAR_ZERO_COLOR #9a9a9a`, `MEMBER_PIN_COLOR #555555`, `MEMBER_RIGID_COLOR #7a3fb8`. | ONE key per sheet. Its gradient is sampled from the same `force_color` / `util_color` / `moment_color` / `deform_color` the drawing is painted with, so it cannot drift. Its discrete rows take their swatch from the constants themselves. A test (`test_pdf_key_colours_come_from_the_colour_functions`) fails the build if a literal hex reappears. |
| "no items capable of displaying the orientation in 3d space" | Nothing on the sheet said which way the structure faced. | An **axis triad** on every view: X / Y / Z arrows from a common origin, coloured the same as the on-screen gizmo (now shared through `stereo_app_constants.AXIS_COLOR_*`), `+Y` marked as plan north, with the azimuth and elevation printed under it. |
| "the colour key is too big, maybe imitate the one already on the display" | A full-page-height matplotlib colorbar dominated every view. | The key is the canvas legend's own idiom, rebuilt for paper: bold caption, a short horizontal gradient strip, three proportional tick labels, then one short line swatch per discrete entry. About a fifth of the width of the old bar. |
| "there is no sense of scale" | None. | A **chequered graphic scale bar**, rounded to a 1-2-5 length, laid along the projected +X axis and labelled `true along X`. |
| "more information of the structure analysis in each panel" | The only numbers were on sheet 1. | Every view sheet carries its own stats panel, and two table sheets were added (reactions + equilibrium, governing members). |

A bug was found on the way: **every sheet was drawn upside down.**
`_iso_project` answers in Tk canvas coordinates, where y grows *downward*;
matplotlib's y grows upward. Feeding one to the other mirrored the whole
structure vertically — a roof sagging under its own weight bulged *up* on
the deformed-shape sheet, and a dome read as a bowl. `_pdf_project` now
flips it once, for the nodes, the deformed nodes, the load arrows and the
triad alike. Verified against a screenshot of the app's own canvas at the
same azimuth and elevation, not against the algebra.

## Second pass, same day: views, nomenclature, isolation

| Request | What it is now |
|---|---|
| "the top, left, right, back and front view are important too" | Five orthographic sheets between the general view and the analysis, one per view. Each azimuth/elevation is derived, not guessed — for a camera looking along `d` with `up`, the sheet's horizontal axis is `cross(d, up)`, and a test re-projects the world unit axes to confirm each view really is that view. Plan is az 0 / el 90; front az 0 / el 0; back az 180; right az −90; left az 90. |
| "nomenclature about the elevation … ghost grid almost invisible" | A background grid at a round 1-2-5 spacing, labelling real world coordinates along the bottom and left edges, plus the axis names (`X (m) →`, `↑ Z (m)`). On the elevations it also draws a dashed line at **every distinct structural Z** with its value (`+0.00`, `+1.74`, `+3.14` …) down the right-hand margin — the levels a structural elevation is read by. Capped at 14 levels, past which the round grid carries it alone. |
| "to what view we are currently watching" | Three, belt and braces: the sheet title, a bold caption centred under the drawing (`FRONT ELEVATION · looking along +Y`), and the orientation indicator, where the axis that points at the reader can no longer be an arrow. It becomes the draughtsman's **circled dot** (coming at you) or **circled cross** (going away), chosen from the sign of the view depth, with `X toward you` / `Y away from you` spelled out beneath. |
| "a PDF of any given selection or selected group in isolation" | **PDF of Selection…** in the output toolbar. `submodel()` cuts the selected bars and nodes out of the model with every parallel array — `node_res`, `member_res`, `reactions`, the member checks — filtered and renumbered to match, so the report is built by the same code path as a whole model, and the rest of the structure is *absent* rather than dimmed. Selected rods define the group; with only nodes selected it takes the rods whose both ends are selected, which is what lassoing a region means. |
| "put the name of the file and group being analyzed" | The title block grows a **GROUP** and a **FILE** field (and widens to fit six columns), sheet 1's panel opens `SELECTED GROUP` with both names and the line *shown in isolation — the rest of the model is not drawn*. |
| "make the scale indicator horizontal for all cases" | Always level now. On an orthographic sheet that is free and exactly true, because the sheet's horizontal axis **is** a world axis: the bar says `5 m · true to scale`. On the axonometric sheet nothing is horizontal in world terms, so it is drawn at the length one metre of X projects to and says `5 m · along X (foreshortened)` rather than pretending. |

One honesty note that came with the isolation feature: an isolated group is a **cut** through a structure, so its reactions cannot balance its applied load — the bars that used to carry force across the cut are gone. The reactions sheet says exactly that instead of reporting the difference as a solver error.

## Third pass, same day: the analysis sheets

| Request | What it is now |
|---|---|
| "a utilization sheet with the threshold relative to this model" | A third utilisation sheet whose ramp is stretched over **this model's own range** rather than the code's. On a structure whose worst bar sits at 0.08, the absolute sheet is a field of uniform green that says only "nothing is close to capacity"; the relative sheet shows *where the work goes*. Where the model does exceed capacity, a rule is drawn across the ramp at the position utilisation 1.0 falls, so the code limit is still on the sheet. The key says `RELATIVE scale` in so many words, because a red bar that does not mean "over capacity" has to announce itself. |
| "add to the utilization models and axial forces analysis a top view" | Axial force and utilisation are each drawn twice: axonometric, which shows the whole shape at once, and **plan**, which is the view a grid is laid out and checked in, and the only one where two bars at the same plan position cannot hide behind one another. One builder, parameterised by view, so the two cannot drift apart. |
| "and add the thickness = stress" | Bar thickness on all of those sheets is now **axial stress \|N\|/A against this model's own peak** — the same rule the canvas's Thickness-by-stress toggle uses, so a sheet and the screen weight the same bar the same way. Stress and not force: a thick chord and a thin web carrying the same kN are not working equally hard. The key states the peak in kN/cm², and the stats panel repeats it. |
| "a moment along rods and shear along rods sheet … if the space truss has any type is present" | Two sheets, drawn only when the model actually has a rigid joint (a pin-jointed truss carries neither, and a sheet of zeros implies a check that was never possible). Each rod carries a **proper diagram hung off its own axis**: the rod is the baseline, the ordinate is laid off perpendicular to it in the sheet plane, and every rod is drawn to ONE common scale so two can be compared by eye. The ordinate is the *signed* component about whichever local axis is working harder — plotting the resultant magnitude would hide every sign change, and a diagram that never crosses its baseline cannot tell hogging from sagging. A rod pointing straight at the reader has no perpendicular on that sheet, so it is skipped and counted rather than drawn in an invented direction. |
| "the maximum solicitation of the rods and of the nodes (in the vierendeel case)" | Two schedules. **Rods**: N, V, M, T, \|N\|/A and utilisation per bar, ranked, where V and M are the peak anywhere *along* the rod and not only at its ends. **Nodes**: the joint moment, the worst axial and shear framing in, the reaction and whether it is a support — the node sheet appears only on a rigid model, since that is the Vierendeel case it is for. Both end in an **envelope**: the worst of each column and which member or joint owns it, always printed even when the body has to be truncated, because that is the number the section gets sized from. |
| "a complete pdf file of a selection or group or sub group … isolated" | Already in the second pass (**PDF of Selection…**), and now it takes the sheet chooser too — with the sub-model's *own* rigid count, so a pin-jointed group cut out of a rigid model is not offered sheets it cannot fill. |
| "put the name of the document in the pdf presentation with the name of the group" | The title block's **GROUP** and **FILE** fields, from the second pass, carry it on every sheet of a selection report. |

### Two additions that answer "so is it alright?"

**A serviceability verdict on the deformed sheet.** It reported `L / 412`
and left the reader to know whether that passed. It now carries the limit
as well: the allowance `L / 250` (the recommended SI roof value; CIRSOC
301 follows EN 1993-1-1 here, and `export_pdf` takes the denominator as an
argument for a brief that says otherwise), the span it is taken over, the
ratio of worst displacement to allowance, and a one-line VERDICT.

The reference span is the model's largest **horizontal extent**, not its
longest bar. A serviceability limit is about how far a structure sags
between its supports, and the longest single rod in a space truss is the
diagonal of one module — using it would make the allowance several times
too tight. Where a model has no horizontal extent at all (a lone column)
the longest bar is the only length there is, and it is used.

The bars are still coloured by displacement **magnitude**, with the
allowance drawn as a rule across the ramp, rather than recoloured by
displacement ÷ allowance. A fraction-of-allowance ramp reads as one flat
colour on any structure comfortably inside its limit — the same flaw the
absolute utilisation sheet has — and the deflected *shape*, which is what
this sheet exists to show, would go flat with it.

**A steel take-off.** Bars, area, total and mean length, kg/m and mass per
section, ranked by mass, closing on the total in kg and tonnes. Mass is
computed from the section area and the **same unit weight the self-weight
load case uses**, so the weight the report states and the weight the
solver applied cannot disagree. Bars sharing a profile name but not an
area are marked, rather than averaged into a single misleading figure.
Mass stays in kg and tonnes in every convention, because mass is not one
of the quantities the unit selector converts.

### The units on the sheet

The app has an app-wide unit selector (CIRSOC, Eurocode, NBR, CSA, AISC).
Until this pass the report ignored it: `kN`, `m` and `mm` were hard-coded
into some sixty format strings and `m, kN, mm` into the title block.
Switch the app to AISC and the screen said kip while the sheet said kN,
over the same model, with nothing on the sheet admitting it.

Every number the report prints now goes through `ReportUnits`, which
converts from the units the tab **stores** in (declared once, in
`stereo_reports.STORAGE_UNITS`, and imported by `stereo_app` so the two
cannot drift) to the convention selected **at export time** — the one the
reader was just looking at. The title block states which.

Two things are deliberately *not* converted:

- **Utilisation**, and the **L / n** deflection ratio. Both are ratios of
  two like quantities, so they are the same number in every convention;
  "converting" them would be a straightforward error.
- The **round numbers the report chooses for itself** — a scale bar's
  length, the ghost grid's spacing, the triad's arm — are picked in the
  unit they will be *labelled* in and then converted back to draw. A bar
  that is a round 5 m is 16.4 ft, which is not a scale bar.

One unit needed reconciling: `|N| / A` falls out of the model in kN/cm²,
because that is what force and area are stored in, while the tab stores a
*stress* (Fy, Fu) in MPa. `ReportUnits.stress_from_kn_cm2` carries it
across before re-expressing it, so the peak stress on the axial-force
sheet and `Fy` in the member table are in the same unit as each other,
whichever convention is selected.

The Excel export still writes SI regardless of the selector. That is a
separate gap, and a known one.

### Choosing the sheets

The full report is nineteen sheets on a rigid-jointed model. That is the
right default for a design file and the wrong one for a slide, so
**Export PDF…** and **PDF of Selection…** both open a chooser first: six
groups of sheets (views, axial force, utilisation, moments, deformed
shape, schedules), with the number of sheets the choice produces counted
live, before anything is written. Sheet 1 — the general view and the load
case — is not optional. The choice is remembered for the next export.

The chooser runs *before* the save dialog on purpose: asked for a path
first, a reader who then cancels the chooser has already named a file that
never appears.

## Sheet by sheet

Every sheet: a frame, an **ISO 7200-style title block** bottom-right
(title, sheet n of N, model, size, units, code basis, date), the compact
colour key top-left, the stats panel top-right, the scale bar bottom-left
and the orientation triad bottom-right. The drawing is fitted into what is
left of the sheet, so no panel ever lands on the structure.

**1 — General view: model and load case.** (axonometric) Bars coloured by connection
(pin / rigid), supports as blue squares, and one arrow per loaded node
along that node's own net force direction, length ∝ |F|^0.6 of the largest
load. Stats: node/bar/support counts, the pin-rigid split, bounding-box
extents, degree of static indeterminacy, the applied load total, and the
headline results.

**2–6 — Plan, front, back, right and left.** The model over its ghost
dimension grid, each true to scale, each captioned with what you are
looking at and which way the third axis runs. The elevations carry the
structural levels. Pass `ortho_views=False` to `export_pdf` for a short
report without them.

**7-8 — Axial force (kN), general view and plan.** Red tension / blue
compression, the same ramp as the canvas; bar thickness = axial stress.
Over-capacity bars are dashed. Stats: how many bars are in tension, in
compression and near zero; the max tension and max compression with the
bar identified by BOTH its end nodes and its midpoint; the mean |N| and
the peak stress.

**9-11 — Member utilization: general view, plan, and relative.** Only when
a member carries a section. Green / amber / red against the absolute
CIRSOC-301 thresholds, with a capacity rule across the ramp at 1.0 — and
then once more with the ramp stretched over this model's own range, for a
structure whose worst bar is nowhere near capacity. Stats: governing
utilisation and which bar, median, mean, the count over capacity, and a
one-line **verdict**.

**12 — Nodal moments (kN·m).** Orange hogging / violet sagging on the
joints, bars faded to a backdrop. On a fully pin-jointed model there is
nothing to plot, and the sheet says so in words instead of drawing white
dots under a ±0.00 key — which is what it used to do.

**13-14 — Bending moment and shear ALONG the rods.** Rigid models only.
One diagram per rod, hung off the rod's own axis, all to one common
scale; the rods themselves are coloured by their peak resultant. Stats:
how many rods carry a diagram, the governing rod with its peak and the
station x it occurs at, the mean peak, and how many rods reverse sign
inside their span.

**15 — Deformed shape.** The undeformed geometry as a ghost, the deformed
one coloured by displacement, exaggeration factor stated in the caption.
Stats: max |u| with its node and its ux/uy/uz components, the longest bar,
the deflection as an **L / n** ratio, and the serviceability check against
**L / 250** with its span, allowance, ratio and verdict.

**16 — Support reactions and equilibrium.** Every restrained node's Fx, Fy,
Fz, Mx, My, Mz, then Σ reaction, Σ applied and the **residual** between
them, with a verdict. A solved model that does not close on its own
equilibrium is wrong, and that check belongs in the report.

**17 — Governing members.** The most utilised bars ranked, with length,
axial force, check mode, utilisation, KL/r and OK/OVER. Without sections
assigned it ranks by |N| instead and says why there is no code check.

**18 — Maximum solicitation, rods.** N, V, M, T, |N|/A and utilisation per
bar, with the envelope of each and the bar that owns it.

**19 — Maximum solicitation, nodes.** Rigid models only: the joint moment,
the worst axial and shear framing in, the reaction, and the envelope.

**20 — Steel take-off.** Bars, area, total and mean length, kg/m and mass
per section, ranked by mass, closing on the total in kg and tonnes.

## Rebuilding the hand-out artefacts

```
python3 tools/build_release.py          # both
python3 tools/build_release.py --rbz    # SketchUp extension only
python3 tools/build_release.py --check  # list, write nothing
```

`tests/test_build_release.py` compares the shipped `.rbz` byte-for-byte
against `sketchup_plugin/`, so the archive cannot silently go stale again
the way it had: the 0.1.0 `.rbz` was missing `model_import.rb` and
`xlsx_reader.rb`, which meant its own "Import from Stereo…" command raised
`LoadError` on load. Rebuilt and bumped to 0.2.0.
