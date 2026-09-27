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

**7 — Axial force (kN).** Red tension / blue compression, the same ramp
as the canvas. Over-capacity bars are dashed. Stats: how many bars are in
tension, in compression and near zero; the max tension and max compression
with the bar identified by BOTH its end nodes and its midpoint; the mean |N|.

**8 — Member utilization.** Only when a member carries a section. Green /
amber / red against the absolute CIRSOC-301 thresholds, with a capacity
rule drawn across the ramp at 1.0. Stats: governing utilisation and which
bar, median, mean, the count over capacity, and a one-line **verdict**.

**9 — Nodal moments (kN·m).** Orange hogging / violet sagging on the
joints, bars faded to a backdrop. On a fully pin-jointed model there is
nothing to plot, and the sheet says so in words instead of drawing white
dots under a ±0.00 key — which is what it used to do.

**10 — Deformed shape.** The undeformed geometry as a ghost, the deformed
one coloured by displacement, exaggeration factor stated in the caption.
Stats: max |u| with its node and its ux/uy/uz components, the longest bar,
and the deflection as an **L / n** ratio.

**11 — Support reactions and equilibrium.** Every restrained node's Fx, Fy,
Fz, Mx, My, Mz, then Σ reaction, Σ applied and the **residual** between
them, with a verdict. A solved model that does not close on its own
equilibrium is wrong, and that check belongs in the report.

**12 — Governing members.** The most utilised bars ranked, with length,
axial force, check mode, utilisation, KL/r and OK/OVER. Without sections
assigned it ranks by |N| instead and says why there is no code check.

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
