# Session handoff — Arch tab review for an architecture audience

**Written:** 2026-10-13. **Review performed:** 2026-10-04.
**Purpose:** a complete, self-contained account of one Claude Code session,
written so that a different account, a different machine or a different
assistant can pick the work up with no access to the original conversation.

---

## 1. Where the work lives

| | |
|---|---|
| Repository | `marsellaaugusto-ai/STRUCTURAL-SYMULATOR-2` |
| Branch | `claude/relaxed-darwin-7cqke2` (pushed to `origin`) |
| Base | `d24c4d9` — *Merge pull request #1 … stereo-structure-calculator* |
| Commit added | `95b167e` — *Arch: recommendations report read as a teaching tool for architects* |
| Pull request | **None opened.** The branch is pushed and sitting there. |
| Files changed | One file **added**. **Zero** existing files modified. |

The added file is:

```
STRUCTURAL SYMULATOR SOLVER-5-9-26/REPORTS AND GUIDES/ARCH_RECOMMENDATIONS_FOR_ARCHITECTS_2026-10-04.md
```

A second commit on the same branch adds this handoff and corrects one
over-stated verification claim in that report — see §7.

To pick the work up anywhere:

```bash
git clone https://github.com/marsellaaugusto-ai/STRUCTURAL-SYMULATOR-2
cd STRUCTURAL-SYMULATOR-2
git checkout claude/relaxed-darwin-7cqke2
```

Note the repository root also contains three `.zip` snapshots and an older
`structural_simulator_v15_fixed15/` tree. **The live code is
`STRUCTURAL SYMULATOR SOLVER-5-9-26/`** — that is the directory `main.py`
runs from and the only one this review touched.

---

## 2. What was asked

Verbatim, the request was:

> *"please take a look to the arch app i would like a list of recomendations
> on how to improve it, may i remind you this app is not for engenieering it
> is for architects to learn how engenieering works."*

Two things follow from that sentence, and they shaped everything:

1. The deliverable is **a list of recommendations**, not code changes.
2. The judging criterion is **"does this teach an architect?"**, not *"is
   this a competent analysis package?"* The tab is a teaching instrument for
   architecture students, not a tool for engineers sizing members.

No other instructions were given. No PR was requested, so none was opened.

---

## 3. How the review was carried out

A source read of `apps/arch/arch_app.py` (1 990 lines) end to end, plus
`common.py`, `units.py`, `main.py`, the two arch test modules, and the two
prior arch reports (`DIAGNOSIS_ARCH_2026-09-05.md`,
`REMAINING_BUGS_ARCH_2026-09-10.md`). Cross-tab greps were used throughout to
establish what the Arch tab *lacks relative to its sibling tabs*, which turned
out to be the most productive technique in the whole review — several findings
are "every other tab does this and Arch doesn't."

**Limits of this review, stated plainly, because they matter to whoever
continues it:**

- **Nothing was executed.** The container had neither `tkinter`
  (`ModuleNotFoundError: No module named 'tkinter'`) nor `pytest`
  (`No module named pytest`). The app was never launched and the test suite
  was never run.
- Therefore **no numerical claim was independently verified.** The accuracy
  figures quoted in the report are inherited from
  `REMAINING_BUGS_ARCH_2026-09-10.md`, not reconfirmed.
- Every claim about **what the code does** — what a function draws, what it
  omits, which symbol is imported where — was confirmed by reading the source
  or by grep, and the line numbers in the report were machine-checked against
  the file before it was committed.

So: structural/behavioural findings are solid; numerical accuracy is taken on
the prior report's word.

---

## 4. The conclusion reached

> **The Arch solver is excellent and is not the problem. The Arch tab solves
> an arch correctly and then presents the answer as an engineer's output
> sheet.**

Not one recommendation requires touching `ArchModel.solve`,
`internal_forces`, `sample` or `fiber_stresses`. Every one is additive: a new
curve on an existing canvas, a new label on an existing number, a new input
that fills fields that already exist.

A second theme emerged and is worth carrying forward on its own:
**much of what the Arch tab needs already exists elsewhere in this
codebase and is simply unused there.** That makes several items cheap reuse
rather than new development. Specifically —

| asset | lives in | used by Arch? |
|---|---|---|
| `LoadScale` (compressed load-arrow lengths) | `common.py:450` | no — Beam, Truss, Cable all use it |
| `ZoomCanvas` (zoom / pan / picking) | `common.py:507` | no — Cable Web, Stereo, Truss, 3× Perforated Beam use it |
| `render_math` (LaTeX → image) | `common.py:132` | no — only Truss uses it |
| `InfoTooltip` | `cable_web_app.py` (14 uses) | no — zero uses anywhere else |
| `declutter_text` | `common.py:405` | no — Beam and Stereo use it |
| Section catalog (IPE / HEB / UPN) + `section_shapes.py` | `apps/perforated_beam/` | no |

`requirements.txt` even describes `_ensure_matplotlib` as serving *"the
LaTeX-style equation images in the Truss/Beam/**Arch** guides"* — the Arch
guide it names **does not exist**.

---

## 5. The findings, in full

17 items in three tiers. Line numbers are against
`apps/arch/arch_app.py` at commit `95b167e` and were verified at the time of
writing. The full argument for each is in the report; this is the index.

### Tier 1 — things that would actually teach

| # | finding | evidence | effort |
|---|---|---|---|
| 1 | **No line of thrust / middle-third band.** The single picture architects are taught arches with (Hooke, Gaudí, Heyman) is absent. `e = M/N` from data `sample()` already returns. | grep `apps/arch/` for `thrust line`, `funicular`, `eccentric`, `kern` → **0 hits** | ~1 day |
| 2 | **The schematic never draws the applied loads.** `_draw_schematic` draws the curve, 2 supports, the hinge dot, `0` and the span — nothing else. | `arch_app.py:1507-1583`; grep of that range for `point_loads`/`distributed_loads`/`w_weight`/`w_wind` → **0 hits**. Beam draws loads at `beam_app.py:1458,1479`; Cable at `cable_app.py:1838,1898-1905`; Truss in 7 places. Arch's only arrows (`1624,1629,1633`) are the thrust overlay, **off by default**. | ~1.5 h |
| 3 | **No deflected shape**, though `ArchResult.d` is already there and used only for force recovery. | `arch_app.py:312` | ~3 h |
| 4 | **The architect's numbers are unnamed.** `Rx` at x=0 *is* the horizontal thrust and nothing says so; `f/L` is never computed; the beam comparison (`M = wL²/8` vs `M ≈ 0`, `H = wL²/8f`) that justifies arches is never printed. | `_show_results`, `arch_app.py:1445` | ~2 h |
| 5 | **Examples load numbers and stop.** They don't run the analysis and say nothing about why those three cases are the three cases. | `arch_app.py:1347-1379` | ~3 h |
| 6 | **The funicular relationship is hidden.** Shapes are offered as styling. "Catenary-like" is *never* funicular for anything the tab can apply: its `k` is hard-wired to `3.0/span`, and self-weight exists only horizontal-projected, so weight-along-the-arc — what makes a catenary a catenary — cannot be modelled. | `_apply_shape_preset` `arch_app.py:1057`; `k` at `1389`; `ArchModel.w_weight` `arch_app.py:125` | ~1 week w/ #7, #15 |
| 7 | **No comparison mode.** `_analyze` overwrites `self.result`, so nothing retains a previous answer. Architects learn by contrast. | `arch_app.py:1437` | — |

### Tier 2 — barriers unrelated to structures

| # | finding | evidence | effort |
|---|---|---|---|
| 8 | **Asks for raw `E, A, I, c_top, c_bot` + 2 allowable stresses.** Nobody knows what `I = 20000 cm⁴` means, and the defaults silently make every arch steel (`E = 200 GPa`). A section catalog and `section_shapes.py` already exist in `apps/perforated_beam/`. Masonry — the arch an architect studies — needs material presets. | block at `arch_app.py:1039-1050`; defaults at `694` | ~1 day |
| 9 | **Nothing updates until a button is pressed.** Exactly one variable in the tab has a trace. Span, rise, shape expression, element count and **hinge position** do not redraw; rise needs the `Set geometry` button and the hinge dot doesn't move at all. | only trace is `arch_app.py:987`; `_set_geometry` at `1241` | ~1 h (traces) |
| 10 | **Errors speak Python.** One blanket handler surfaces raw exception text. The A-6/A-7 load validators are the right tone and should reach the rest; a mechanism failure deserves a real explanation. | `arch_app.py:1442-1443`; good model at `_validate_loads` `arch_app.py:135` | — |
| 11 | **No tooltips / glossary.** "Horizontal-projected" (load per metre of *plan*, not of *arch*) is a genuinely subtle idea stated as a parenthetical and never explained. | `InfoTooltip`: 14 uses in Cable Web, 0 in Arch | — |
| 12 | **No theory/guide panel**, though `render_math` exists and `requirements.txt` already promises an Arch guide. | `common.py:132`; Truss uses it at `truss_app.py:4541,4698` | ~1 day |

### Tier 3 — defects and gaps

| # | finding | evidence |
|---|---|---|
| 13 | **Three readouts hard-code `kN` and defeat the unit selector.** In AISC mode (genuinely kip/ft — `units.py:25-27`) the force probe prints `Fx`/`Fy` in kip and then `R` in kN *on the next line*; the thrust panel's caption says "kip" over reaction numbers in kN. Silently wrong by ×4.45, in the panel most likely to be read. **This is a real bug — fix via `self.show('force', …)`, ~15 min.** | `arch_app.py:1695`, `1869`, `1870` |
| 14 | **No buckling / second-order check, and nothing says so.** A shallow slender arch is governed by snap-through, not fibre stress; a student can get "OK" on both stress rows and learn the wrong lesson. Suggest flagging `f/L < 0.15`. | grep `apps/arch/` for `buckl` → **0 hits** |
| 15 | **No masonry / no-tension mode.** `fiber_stresses` computes elastic `σ = N/A ± Mc/I` and checks it against an allowable *tension* — the wrong model for masonry, where the real question is thrust-line containment (= finding 1). | `arch_app.py:400` |
| 16 | **A-3 (dead code) still open**: `os`, `sys`, `subprocess` (`:16`) and `INIT_CW/INIT_CH/INIT_DH` (`:21`) imported unused; `L` and `rise` assigned unused in `_apply_shape_preset` (`:1059-1060`). **A-2 and A-4 are now CLOSED** — `ArchModel.__init__` validates `n_elem` (`:109-113`) and both arch test modules now exist. `REMAINING_BUGS_ARCH_2026-09-10.md` is stale on those two rows and should be updated. | as cited |
| 17 | **Schematic has no dimensions.** Only `0` and the span are labelled. No rise dimension, no vertical axis, no crown height, no `f/L` — the numbers the student just typed appear nowhere on the drawing. | `arch_app.py:1571-1573` |

---

## 6. Recommended order of work (from the report)

| step | item | rationale | effort |
|---|---|---|---|
| 1 | Draw the loads (#2) | the tab currently lies by omission | ~1.5 h |
| 2 | Fix the hard-coded kN (#13) | a real bug, trivially fixed | ~15 min |
| 3 | Live redraw on span/rise/hinge (#9a) | unlocks the "watch it change" mode the rest depends on | ~1 h |
| 4 | Name the architect's numbers (#4) | pure text in `_show_results`, no new math | ~2 h |
| 5 | **Thrust line + middle third (#1)** | the headline teaching feature | ~1 day |
| 6 | Deflected shape (#3) | data already present | ~3 h |
| 7 | Examples that run and explain (#5) | makes 1–6 discoverable | ~3 h |
| 8 | Section picker + materials (#8) | reuse of `perforated_beam` modules | ~1 day |
| 9 | Guide + tooltips (#11, #12) | reuse of `render_math`, `InfoTooltip` | ~1 day |
| 10 | Funicular finder, comparison, masonry (#6, #7, #15) | the ambitious tier | ~1 week |

Steps 1–4 total under a day and would change the tab's character noticeably.
Step 5 is the one worth real investment.

---

## 7. Correction made on 2026-10-13

The report as first committed (`95b167e`) said *"the 2026-09-10 re-validation
holds"*, which reads as though the numerical validation had been re-run in
this session. It had not — see §3. The opening of the report has been
rewritten to attribute those figures to the prior report and to state that
nothing was executed in this pass. No finding changed; the evidence basis is
now stated accurately.

---

## 8. State of play

- **Nothing in `apps/arch/arch_app.py` has been modified.** Not one line.
  All 17 findings are open.
- The working tree is clean and the branch is pushed.
- No pull request exists. Open one from
  `claude/relaxed-darwin-7cqke2` if the report is wanted on `main`.
- Findings #13 and #16 are the only ones that are plain defects; the rest are
  design and pedagogy recommendations requiring a judgement call from the
  project owner about how far to take the teaching angle.

---

## 9. Prompt to resume this work elsewhere

Paste this into a fresh session on any account that has the repository:

> This repo is a Python/Tkinter structural simulator. The live code is in
> `STRUCTURAL SYMULATOR SOLVER-5-9-26/`; run it with `python main.py` from
> that directory. **The audience is architecture students learning how
> structures behave — not engineers sizing members.** Judge everything
> against "does this build intuition about arches?"
>
> Read `REPORTS AND GUIDES/ARCH_RECOMMENDATIONS_FOR_ARCHITECTS_2026-10-04.md`
> and `REPORTS AND GUIDES/SESSION_HANDOFF_ARCH_REVIEW_2026-10-13.md` first.
> They contain a 17-item review of `apps/arch/arch_app.py` with verified line
> numbers, an effort estimate for each and a suggested order. Nothing has been
> implemented yet.
>
> Start with steps 1–4 of the order in §6 of the handoff: draw the applied
> loads on the schematic, fix the three hard-coded `kN` readouts at
> `arch_app.py:1695/1869/1870`, add live redraw traces for span/rise/hinge,
> and rename the results so the horizontal thrust, the rise/span ratio and
> the beam comparison are named explicitly. Do not change the solver —
> `ArchModel.solve`, `internal_forces`, `sample` and `fiber_stresses` are
> validated and must not be touched.
>
> Note: you will need `tkinter`, `numpy`, `scipy` and `pytest` installed to
> run the app and its suite — the environment this review was written in had
> none of them, so nothing in the reports was executed. Verify before
> trusting any numerical figure quoted there.
