# Handoff: Structural Simulator v32, Truss tab, iterations t03 → t15

A summary of one long working session, written so that a new
conversation, in another account, can pick up where this one stopped.
Paste it in as the first message, or point the new session at this file.

---

## 1. The project in one paragraph

**Structural Simulator** is a Python/Tkinter desktop app for teaching
structures to architects. It has eight tabs: Truss, Beam, Arch, Cable,
Cable Web, Perforated Beam, Stereo and Shell (RC). This session worked
almost entirely on the **Truss tab**:

* its on-screen interface;
* its **PDF report**, built with matplotlib (`PdfPages` and bare `Figure`
  objects, never pyplot);
* its two report windows.

Steel checks follow **CIRSOC 301** (Argentina). Units are selectable;
the solver works in kN, m and mm.

* **Repository:** `github.com/marsellaaugusto-ai/STRUCTURAL-SYMULATOR-2`
* **App folder:** `STRUCTURAL SYMULATOR SOLVER v32/`
* **Working branch:** `claude/charming-cori-lnur67`. Every commit was
  pushed there; no pull request was opened.
* **Last state:** v32 **t 15**, 13-10-2026. Full test suite **3162
  passed, 1 skipped** (the long `tests/test_stereo_app.py` run separately
  is not included).
* **Last delivered archive:**
  `structural_simulator_app_v32_t15_2026-10-13_0317.zip` (committed at
  the app folder's root).

## 2. Working conventions the owner relies on

1. **Every round is an iteration** named `v32 t NN dd-mm-yy`. For each:
   * bump `APP_ITERATION` in `tools/build_release.py`;
   * rewrite `BUILD_STAMP.txt` from `build_release.stamp_text()`;
   * write `REPORTS AND GUIDES/CHANGES_v32_tNN_YYYY-MM-DD.md`, quoting the
     owner's words and covering what changed, why, and the tests.
2. **Commit** with a descriptive message, then **push** to the branch.
3. **The zip:** `python3 tools/build_release.py --zip` builds it and
   removes the previous one. Before handing it out:
   * extract it into an empty folder;
   * launch it from there and check the window title, all 8 tabs, an
     example solving, and a report exporting;
   * commit it as "The v32 t NN archive, as handed out", then push.
4. **Example reports:** regenerate them into
   `REPORTS AND GUIDES/example_reports_v32_tNN/` with `git mv` of the
   previous folder. They are exported through the app, with the
   placeholder author "A. Student" and course "Structures I".
5. **Tests:** run the full suite before every commit:
   `xvfb-run -a python -m pytest -q tests --ignore=tests/test_stereo_app.py`
   (about 11 minutes). Headless Tk runs under Xvfb.
   * When a test is wrong rather than the code, fix the test and say why.
   * When fixing a bug, check the test fails with the bug put back.
6. **The `__pycache__` files** are tracked in the repository. Never
   commit `*.cpython-311.pyc` files; the project uses 3.12.
7. **Owner preferences:**
   * English text.
   * The **"Modern report"** look.
   * Captions kept in **full**.
   * **As few pages as possible**, but the sheets they ask for come
     first.
   * Drawings at the **screen's scale**, with high-contrast thumbnails.
   * Moment drawn on the **tension face**.
   * Didactic clarity above all; they reject anything "more confusing
     than nothing", such as the big black load arrows.
   * They like to be asked questions before large visual changes, and
     they send screenshots.

## 3. What was done, iteration by iteration

| t | Date | What |
|---|---|---|
| 01–02 | 05/11-10 | Earlier sessions: Truss layout and perspective in the PDF; load path, readability, an honest unit selector. |
| 03 | 11-10 | Stereo-like UI for Truss: a **mode rail** (Build, Support, Load, Section, Analyse, Results) and the toolbar in Stereo's order. First zip. |
| 04 | 11-10 | **Section tab fixed**: applying a section to a selection of rods now updates them (family-aware). PDF gains **Utilisation** and **Buckling with λ₁, λ₂, λ₃**. |
| 05 | 11-10 | Node, rod and support tools appear in their modes; the display switches move into **Analyse → What to show**. |
| 06 | 11-10 | Everything Analyze computes goes into the PDF in few sheets: **Deflection and stress** (several graphs on one sheet), **Shear V** and **Moment M** on their own sheets, **Rod detail** (16 rods a sheet, each row with V/M diagrams and a position thumbnail), and an Explain sheet with two rods. |
| 07 | 12-10 | Diagrams at the screen's scale; thumbnail contrast; example PDFs. |
| 08 | 12-10 | **Elastic line with points of contraflexure**; a **Joints** sheet (largest single-rod moment, sign, turning arrow, tension face); moment on the tension face (fixed `normal()`). |
| 09 | 12-10 | The **fibre stress drawing** (two coloured bands per rigid rod, as on screen), checked against the canvas: 260 of 260 samples agree. |
| 10 | 12-10 | **Modern report look**: a coloured header band per sheet with chapter colours, a cover with **cards** for the key numbers, the caption in a tinted box, and a footer with model, **author, course**, units, code and date. Author and course are asked once and remembered (`truss_report_prefs.py`, `~/.structural_simulator/truss_report.json`; menu **Export ▾ → Report author and course…**). |
| 11 | 12-10 | **Trace where one load goes**: you choose the load (list, ‹ › or click a loaded joint), and the choice is remembered. Fixed **"Force on each member"**, which did nothing. Fixed a StringVar bound to the wrong Tk root. |
| 12 | 13-10 | **The traced load's arrow is highlighted** (teal, haloed; the others fade). **Large-model protocol** (`LARGE_MODEL_PROTOCOL_v32_t12_2026-10-13.md`), tested on a **64 m K-truss bridge, 97 members** (`apps/truss/truss_large.py`), with Excel and PDF files in `REPORTS AND GUIDES/large_model_protocol_v32_t12/`. The report learned slender drawings (an annotation scale), labels that never overlap (declutterer), grouped contents on the cover, and the imported file's name as its title. |
| 13 | 13-10 | **The bridge is in the examples menu** (Examples ▾ and the library), opening fitted to the window, with a 3-question lesson. Aesthetic pass on the rigid report: cover title fits beside the drawing; reaction values on the arrows; deflection limit label inside its graph; buckling modes stacked for slender trusses; smaller joint arcs. |
| 14 | 13-10 | **After ▶ Analyze the view is refitted** if the deformed shape runs out of view (panning when it fits; never on Live). **Sheet 3 labels**: nothing overlaps; each label slides along or beside its member, or goes onto two lines, before it is dropped (bridge: 83 of 97 shown). **The black load arrows are gone** from Axial forces and Utilisation; on Reactions they are short, thin and orange, hung below the joint, and labelled once when they are all equal. |
| 15 | 13-10 | **Node force vectors** (a card per joint, 8 a sheet: free-body diagram, table, **max moment with sign and turning arrow**, ΣF and ΣM = 0 ✓) and **Rod calculations** (a row per rod, 16 a sheet: L, θ, N, end components, V/Ma/Mb if rigid, free bodies at both ends) added to the PDF. **The app's two Export ▾ report windows now show exactly these card sheets**, rendered by the PDF code, with Save as PDF…. |

The current report's sheet order:

1. Cover
2. Geometry
3. Axial forces
4. Deflection and stress
5. Reactions
6. Utilisation
7. Buckling
8. Shear V and Moment M *(only when something bends)*
9. Joints *(only when something bends)*
10. Node force vectors
11. Rods
12. Rod calculations
13. Plates *(if any)*
14. Rod detail *(only when something bends)*
15. Explain

## 4. Where things live

| File | What |
|---|---|
| `apps/truss/truss_pdf.py` | The whole PDF report: the `_Report` class and `export_pdf()`. Key pieces: `frame()` (band, footer, caption box; content shifted down by `CONTENT_DY`), `CHAPTERS` (colours), `ann` / `slender` (annotation scale), `queue_label()`, `member_label()` and `declutter()` (label placement), `draw_loads()` (only on Reactions), `node_vectors()` and `_node_card()`, `rod_calculations()` and `_calc_row()`, `_node_fbd()`, `joint_moments()`, `cover()` and `_cover_title()`. |
| `apps/truss/truss_app.py` | The tab (Tk). Mode rail, toolbar, What to show, the load-path chooser (`_build_load_path_chooser`, `_trace_load_at`), `_fit_to_results`, `_model_in_view`, the card windows (`_show_card_report`, `_card_report`), Export menu. |
| `apps/truss/truss_app_design.py` | `_export_pdf_report`, `_ask_report_author`, `_report_title`. |
| `apps/truss/truss_app_play.py` | Example library window and `_load_library_example` (fits the view when needed). |
| `apps/truss/truss_examples.py` | 10 examples with lessons (the bridge is the 10th). |
| `apps/truss/truss_large.py` | `k_truss_bridge(panels, bay, depth, load, rigid)` and `hand_checks()`. |
| `apps/truss/truss_report_prefs.py` | Author and course, remembered. |
| `apps/truss/truss_math.py` | Solver: `analyze`, `compute_diagrams`, `compute_node_design_actions`, … |
| `tools/build_release.py` | `APP_ITERATION`, stamp, `--zip`. |
| Tests | `tests/test_truss_pdf.py` (report), `test_truss_large_model.py` (protocol, bridge), `test_truss_loadpath.py`, `test_truss_play.py`, `test_mode_rail.py`, `test_truss_layout.py`, `test_render_math_master.py`, `test_truss_plates_app.py`. |

## 5. Open points, and ideas not yet done

* The card chapters make long reports: the bridge is 24 sheets pinned
  and 35 rigid, taking about 20 s and 35 s to write. **Offer to make
  Node force vectors and Rod calculations optional** (for example a
  checkbox at export).
* The **on-screen canvas** loads are unchanged: still orange and sized
  to the screen. Only the PDF's black arrows were removed. Ask before
  changing the canvas.
* On long spans the deformed shape at ×50 is large; ×10 reads better.
  The view now refits after Analyze, but the magnification itself is
  not automatic.
* With *Colour by utilisation* on, the canvas legend still says
  tension, compression and zero (small, pre-existing).
* `tests/test_stereo_app.py` (very long) has not been rerun since early
  in the session.

## 6. How to resume in a new session

1. Clone the repository and check out `claude/charming-cori-lnur67`, or
   merge it into main first if that is wanted.
2. Read the latest `REPORTS AND GUIDES/CHANGES_v32_t15_2026-10-13.md`
   and this file.
3. The next round is **t 16**. Follow the conventions in section 2.
