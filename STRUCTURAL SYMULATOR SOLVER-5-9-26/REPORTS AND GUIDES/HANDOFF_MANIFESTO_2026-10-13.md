# Handoff manifesto — the grouping work, 2026-10-13

Written so this work can be picked up cold, on another account, with no memory
of the chat that produced it. It follows the same purpose as
`HANDOFF_MANIFESTO_2026-09-10.md`, which covers the earlier units/diagnosis
arc; read that one for the app as a whole and this one for everything about
grouping. Read top to bottom once; after that the headings are the index.

---

## 0 · The one-paragraph summary

The Stereo tab had been using one word, "group", for three unrelated jobs, and
the workflow around it felt fragmented as a direct result. This arc separated
those jobs into three axes, then built five features on top of that separation:
a group tree you manipulate directly, piece marks derived from geometry,
roles/rules as a first-class axis, components (one part built many times), and
a SketchUp round trip that no longer loses grouped geometry. Each of the five
was taken to its option **C** (the fullest version offered in the plan). The
suite stands at **4527 tests**, 26 commits, 72 files, +12,742/-291 lines, all on
branch **`claude/v32-st01`**, pushed. Nothing from the plan is outstanding. The
one open item is not code: there is no `LICENSE.txt`, and the shipped user guide
tells customers to read one.

---

## 1 · Where the work is

- **Repository** `marsellaaugusto-ai/STRUCTURAL-SYMULATOR-2`
- **Branch** `claude/v32-st01` — all 26 commits, pushed, tree clean at `37f5ce1`
- **The two-tree trap** the earlier manifesto warns about still applies: the git
  root is the *parent* directory and the app lives in the subfolder
  `STRUCTURAL SYMULATOR SOLVER-5-9-26/`. Git pathspecs and `git diff --stat`
  output carry that prefix. Run the app and the tests from the app folder.
- **`claude/nice-feynman-cof87g`** also exists and is **stale**: `v32-st01` is
  26 commits ahead of it and 0 behind, and contains it (merge `7b6da4c`).
  Nothing is stranded there; it simply is not where the work went.

---

## 2 · The standing constraints on this work

These were set by the user and held throughout. They are not optional
background; they shaped specific design decisions and the wording of every
report.

> "To ensure complete legal compliance and originality, do not copy,
> reverse-engineer, or reference the source code, proprietary algorithms, or
> specific UI design choices of any existing commercial software like SketchUp,
> Revit, or AutoCAD. Instead, design a clean-room solution based on universal,
> open-source software engineering patterns."

> "be mindful of copyright laws im just looking for information of more
> established apps that can inform my app, please give me information that
> doesnt break the rules and laws."

> "The idea is not to copy their ideas but to help use what they do to inform a
> way to stream line the process of using similar features and inspire our
> work."

What that meant in practice: everything here derives from published, general
software-engineering practice (**Composite** for the containment tree,
**Flyweight** for one definition built many times, canonical-form hashing as
used in graph isomorphism and geometry dedup, principal-axis frame selection
from a point cloud) and from fabrication convention that long predates any
software (identical pieces carry one mark and a count). Where a decision could
have gone either way, the reason recorded in the code is a
structural-engineering or fabrication reason, never a resemblance to another
product. `REPORTS AND GUIDES/GROUPING_ARCHITECTURE_2026-10-05.md` and
`GROUPING_WORK_FULL_ACCOUNT_2026-10-10.md` both carry an explicit
**Originality** section; keep that convention.

The SketchUp extension is a separate matter and is legitimate: it uses
SketchUp's **published public Ruby API**, which is documented for exactly this
purpose. Nothing was decompiled or reverse-engineered.

---

## 3 · The plan this followed

Work was driven by a comparison document the user commissioned, **"Grouping
Models Compared"**, `https://claude.ai/artifact/1aqMotynH8gU3PtbwHDS6F`. It set
out five tasks, each with options A/B/C of increasing ambition. **That link is
on the old account** — if it does not open after the switch, the plan is fully
reconstructed in §5 below and in the three analysis reports listed in §10, so
nothing depends on recovering it.

---

## 4 · The idea the whole thing rests on

One word, three jobs:

| Axis | Question it answers | Shape |
|---|---|---|
| **Containment** | what is inside what | a tree: one parent |
| **Reuse** | which of these are the same part | a reference: many instances, one definition |
| **Classification** | which pieces count as X | a cross-cut: any piece in any number of sets |

Two rules follow, and both are load-bearing. Breaking either is how this gets
undone:

- **Derived, never stored.** Node membership, piece marks, `_excluded_rods` and
  the scene document are all computed from geometry on demand. A stored answer
  can disagree with the model; a derived one cannot.
- **A container bounds ownership, never connection.** Rod ends still fuse
  across a group boundary. This is the opposite of a drawing tool's behaviour,
  and it is deliberate: a bolted joint does not stop being a joint because
  someone drew a box around one side of it.

A third principle governs the marks: **err toward "different."** Marking two
identical trusses apart costs one duplicated drawing. Marking two different
trusses the same sends the wrong steel to site.

---

## 5 · The five tasks, as built

### Task 1 — Direct manipulation (B and C)

**B** put the verbs under the pointer — select, enter, delete a group where the
user is already looking, rather than in a distant panel.

**C** made the group list a real tree: `apps/stereo/stereo_app_outliner.py`
(375 lines), a `ttk.Treeview` replacing a flat `Listbox`. Expand/collapse, drag
to reparent, and a refusal to drop a branch inside itself — the one move the
containment axis cannot allow, because nothing can contain itself. *Ungrouped*
is not a group, so nothing goes inside it; the way back to the top is to drop
clear of the rows.

### Task 2 — Piece marks (B and C)

`apps/stereo/stereo_marks.py` (637 lines). A part's signature is its length
plus its section. An assembly's is a canonical geometric signature: the point
cloud chooses its own frame — farthest node from the centroid, then farthest
off that line, then the cross product — quantised to a tolerance. **Ties in
that choice are symmetries**, so a tied pick still places the geometry
correctly.

**C** keeps a number stable across revisions *without* storing the mark. What
is stored is a **signature → number** map, which cannot be wrong: it either
matches a part in the model or matches nothing. That is how the register
reconciles with "derived, never stored" instead of contradicting it. Numbers
can be issued and withdrawn; the map travels on the `Mark Register` sheet.

### Task 3 — Roles as a real axis (B, C, and persistence)

`stereo_roles.py` — a role is a question asked of the model, not a frozen list
of rods, so it keeps up as the model changes. `stereo_roles_excel.py` puts
saved rules on a `Rules` sheet so they travel with the model.

**C** lets a rule decide what the analysis contains, and this is where the work
**refuses** something. Utilisation comes *out* of the analysis, so a rule
asking about utilisation cannot decide what goes *in* without circularity. It
is refused in three places: `new_rule`, `excluded_by` (which deliberately takes
**no** `checks` argument, so it cannot see results even by accident), and the
sheet reader. The decisive test is that pressing Analyze twice gives the same
numbers. The app also refuses to analyse when every rod has been excluded,
rather than solving an empty model.

### Task 4 — Components (B and C)

`stereo_components.py` — copies are sized together and marked once, because a
part is fabricated once and installed many times. `verify` reports copies that
have drifted out of agreement.

**C** took a component across files: `stereo_partlib.py`, `.part.json`, format
`STEREO-PART/1`. A part is stored relative to an **anchor node** — the part's
own node nearest its bounding-box low corner — *not* the bounding-box corner,
which is usually not a node at all. Placing goes through
`stereo_merge.merge_models`, so rods fuse at the seam, a taken group name is
renamed, and a part placed exactly where it came from adds nothing.

### Task 5 — SketchUp (B, C, and shared parts)

Measured against the shipped 0.2.0, the old export was worse than
"unsupported": a grouped truss exported as *"No edges found"*; a group plus
loose edges reported *"Exported 3 nodes and 3 members"* while silently dropping
three; picking inside a group gave *"Exported 3 nodes and 0 members"*. Fixed by
`each_world_segment`, which walks containers recursively in world space.

**Shared parts**: a component definition's contents are *one* entity set shared
by every instance, so nested containers report the same `persistent_id` across
copies — which is what lets components arrive as shared parts rather than
unrelated look-alikes.

**C** is the round trip back out: `model_groups_in.rb` (331 lines) rebuilds
groups from the workbook as real containers, positions them by a rigid
transform fitted between point clouds, and emits component instances where two
groups are the same part.

Relevant SketchUp API semantics, learned the hard way and worth keeping:
`A * B` means apply B then A; `InputPoint#position` is already world
coordinates; `Group` vs `ComponentInstance` is exactly unique vs shared.

---

## 6 · What travels in the workbook

| Sheet | Written by | Read by |
|---|---|---|
| `Model` | `_write_model_sheet` | model open |
| `Groups` | `stereo_groups_excel` | model open |
| `Scene` | `scene/persist.py` | model open |
| `Rules` | `stereo_roles_excel` | `import_rules` |
| `Piece Marks` | `stereo_marks_excel` | **nothing — by design** |
| `Mark Register` | `stereo_marks_excel` | `_register_from_workbook` |

`Piece Marks` is written to be read by a person and never read back, because
marks are derived. Only the register is read.

---

## 7 · The extension

**Version 0.5.0**, `sketchup_plugin/coordinate_coordinator_truss_app_amac.rb`
line 57. Install from SketchUp's *Extension Manager → Install Extension*.

**Anyone picking this up must reinstall it.** 0.2.0 writes no groups or
components and reads none back, so all of Task 5 is invisible until they do.
`tools/build_release.py` hard-fails if `model_groups_in.rb` is missing from
`REQUIRED_RB`, so the archive cannot silently ship without it.

---

## 8 · How to run and test — the environment facts that cost time

These were all learned by losing time to them. They are the most practically
useful section here.

```bash
# tkinter: the DEFAULT python3 does NOT have it. Use 3.12 explicitly.
/usr/bin/python3.12 -m pytest tests/ -q          # 3.12 has tkinter 8.6
/usr/local/bin/python3                           # does NOT -- tests silently skip

# a display is required; verify it with Tk, not with xdpyinfo (not installed)
Xvfb :91 -screen 0 1600x1200x24 &
DISPLAY=:91 /usr/bin/python3.12 -c "import tkinter; tkinter.Tk()"

# the whole suite, in parallel (~26 min)
DISPLAY=:91 /usr/bin/python3.12 -m pytest tests/ -q -p xdist -n 4
```

- **Xvfb displays die often.** When the display is gone, Tk tests *skip* rather
  than fail, so a run can look green while testing nothing. **Count the `s`
  characters** in pytest's progress output; zero skips is the real check.
- **Five tests fail under xdist and pass serially.** This is a property of the
  runner, not of the code. Do not chase them:
  - `test_perforated_beam_app_features.py` — `test_the_divider_can_be_dragged`,
    `test_dragging_the_divider_in_raises_a_horizontal_scrollbar`,
    `test_the_notes_rewrap_when_the_panel_is_widened`
  - `test_stereo_app.py::test_delete_key_on_the_canvas_deletes_the_selection`
  - `test_truss_layout.py::test_analysis_still_shows_diagrams_after_a_report_window_opened[_show_rod_calculations_report]`

  The first four need **window focus** (`event_generate` does nothing without
  it); the last is a `pyimage1` cross-root `TclError` from batching app tests
  into one process. All five were verified passing serially — the first three at
  48/48 in their own file, the fourth at 9/9, and the delete-key one at position
  99 of a 689-test serial run.
- **A long-lived pytest process degrades badly.** `test_stereo_app.py` (1000
  tests) runs at **3.8 s/test** in a fresh process and **6.6 s/test** averaged
  over a 689-test run, having slowed to ~10 s/test by the end — roughly 2.6×
  worse on identical tests. It is cumulative Tk state, not heavy tests: the
  slowest 15 are only 17% of the run and the other 301 average 3.3 s. This is
  why xdist finishes all 4527 in 26 minutes while this one file takes 76
  serially: the workers never live long enough to degrade. **If this file grows
  further, split it or recycle the process.** Nothing was changed here; it is a
  suite property, not a product bug.
- **Never `pkill -f <pattern>`** when the pattern can match your own command
  line — it kills your shell (exit 144). Kill by PID.
- **Do not edit files while a suite runs.** Three full regressions were
  invalidated that way during this arc.

---

## 9 · Current state

- **Suite: 4527 tests.** Last full parallel run: **4517 passed, 5 failed**, the
  five being the xdist artifacts in §8. `test_stereo_app.py` separately
  verified **1000/1000 serially**, in two segments (ids 1–689 and 685–1000,
  overlapping five so nothing fell between them).
- **New tests from this arc: 436** across 14 new files, plus 5 Ruby stub/harness
  files (`tests/ruby/`) and additions to 4 existing test files.
- **Three archives, one build stamp** `2026-10-10_0427`:
  `CoordinateCoordinatorTrussAppAMAC_v32st01_2026-10-10_0427.rbz` (0.5.0),
  `structural_simulator_app_v32st01_2026-10-10_0427.zip` (409 entries),
  `structural_simulator_customer_v32st01_2026-10-10_0427.zip` (157 entries).
  All four copies of the `.rbz` are byte-identical.
- **A plain `python3 tools/build_release.py` now builds all three.** It used not
  to: the customer archive was cut by hand at release points only, which is how
  it came to be shipping the 2026-10-03 app and the 0.2.0 extension three weeks
  late. `--rbz`, `--zip`, `--customer` still each build only what they name,
  except that the extension is built whenever an archive is, since both
  archives embed it.

---

## 10 · Reports to read, in order

1. `GROUP_WORKFLOW_ANALYSIS_2026-10-06.md` — why the workflow felt fragmented
2. `CONTAINER_MODELS_COMPARED_2026-10-06.md` — how other programs organise a model
3. `BIM_IDEAS_FOR_GROUPING_2026-10-06.md` — what the BIM/detailing world settled on
4. `GROUPING_ARCHITECTURE_2026-10-05.md` — the scene graph and object model
5. `GROUPING_WORK_FULL_ACCOUNT_2026-10-10.md` — all five tasks, and the audit
6. `HANDOFF_MANIFESTO_2026-09-10.md` — the app as a whole, before this arc

---

## 11 · Bugs found and fixed

The ones in my own first attempts are listed too, because they are the ones a
successor is most likely to reintroduce.

**In the existing code, found while building:**

1. **SketchUp export silently dropped grouped geometry** — see §5, Task 5. The
   worst kind: it reported success with a wrong count.
2. **`stereo_merge` carried group facts from its own hardcoded tuple**, drifted
   from `GROUP_FLAGS`, dropping `component`. Merging two models that each had
   components left look-alike groups that would then be sized apart.
3. **Old workbooks lost their `excluded` flag.** The `Scene` sheet never
   recorded the group flags and won on import, so the flag was *still* being
   lost after the first fix. `_carry_group_flags` now matches by **rod set**,
   falling back to name for branches. `tools/check_excluded_groups.py` sorts a
   folder of workbooks into FINE / WORTH A LOOK / NO GROUPS.
4. **The launch configurations were never committed.** `.gitignore` had a
   blanket `.vscode/` rule; `git add` skips an ignored path silently and
   `git status` stays clean, so the commit meant to add them carried only the
   rebuilt archives. The files existed locally, their three tests passed
   locally (they read from disk), and the zip shipped them (the builder copies
   from disk) — while a fresh clone had neither. The rule now keeps those two
   files and a test asserts **tracked-ness**, because reading from disk can
   never catch this.

**Mine, corrected during the work:**

5. **`_may_drop` read the dragged row off `self._drag_from`,** which the drop
   handler clears first — so **every drop was refused**, and the refusal tests
   passed anyway, because a refused drop and a broken one look identical from
   outside.
6. **The part anchored on the bounding-box corner**, which is usually not a
   node, so placing a part on a joint fused nothing and it floated beside the
   model.
7. **`mark_register` was missing from the undo snapshot**, so undoing an issue
   left the model held to numbers never issued.
8. **Collapse memory survived `_drop_groups`.** Group ids restart at 1, so an
   imported model could open with an unrelated branch collapsed.
9. **`name_components` used a Ruby single-quoted `'×'`** — a literal
   backslash-u — and could hand two different parts the same label, merging
   them.
10. **`collect_segments` still built 2-element path entries** after
    `each_world_segment` moved to 4, so components came back `None`.
11. **Four errors in my own first draft of the user guide**, caught by writing
    it against the code: the menu items are `Make component…` and
    `Make unique (detach this copy)`, the button is `Issue numbers…`, and
    dropping a group on *Ungrouped* does **not** move it to the top.

---

## 12 · What is open

**One item, and it is a decision rather than a task.**

**There is no `LICENSE.txt`.** `CUSTOMER_EXTRA_FILES` in
`tools/build_release.py` declares it, but the file does not exist and the
builder skips it silently (`if os.path.isfile`). Meanwhile the user guide
shipped to customers, section 10, says *"The licence for this product is in
LICENSE.txt and under About… → Licence…"* — so a customer is pointed at a file
that is not there, and About → Licence… has nothing to read.
`THIRD_PARTY_NOTICES.txt` **is** generated and present, so third-party
compliance is fine; what is missing is the product's own terms. Which licence
this ships under is the owner's decision and was deliberately left to them.
Drop a `LICENSE.txt` at the app root and the next build includes it
automatically — its first line also becomes the owner line in the About box.

**Not open, but worth a successor's judgement:**

- The customer archive deliberately excludes `.vscode` and
  `REPORTS AND GUIDES`, so the launch-configuration fix does not reach
  customers. Defensible — a customer unzipping and running `main.py` is not
  using VS Code's Run button — but the report that motivated `launch.json` was
  *"the zip extracts but nothing happens when I run main.py"*, so it is worth
  deciding on purpose rather than by default.
- `anchor_of` returns `None` for `.part.json` files written before the anchor
  fix; those place on the bounding-box corner as before.
- Stable marks depend on the tolerance, which is user-settable for exactly that
  reason.
- A rule cannot ask about anything the analysis produces. That is a refusal,
  not a gap, and it should stay refused.

---

## 13 · Commit-by-commit account

| Commit | Date | What |
|---|---|---|
| `271c240` | 10-06 | Analysis: why the grouping workflow feels fragmented |
| `7d3ef67` | 10-06 | Stage 1: a group is a thing you can select, enter and delete |
| `1096de1` | 10-06 | Compare how other programs organise a model |
| `95b3eb0` | 10-06 | What the BIM and detailing world already solved |
| `d6e820a` | 10-09 | Tasks 1 and 3: verbs under the pointer, roles as a real axis |
| `f5565ad` | 10-09 | Drop my duplicate dim path — the app already dimmed |
| `9077e1d` | 10-09 | Fix the last stale assertion about the group edit button |
| `d289d3c` | 10-09 | Task 5: the SketchUp export follows groups and components |
| `5084b4e` | 10-09 | Task 2: piece marks |
| `06a6a6a` | 10-09 | Task 4: components — one part, built more than once |
| `e6c6395` | 10-09 | Saved rules travel in the workbook |
| `62c9b4f` | 10-09 | SketchUp components arrive as shared parts |
| `caddb28` | 10-09 | Old workbooks keep their group facts, and a tool to check them |
| `4084098` | 10-09 | Task 5C: the round trip back out |
| `d832ac2` | 10-09 | Task 1C: the groups are a tree, and act like one |
| `ed24545` | 10-10 | Task 2C: a piece mark keeps its number between revisions |
| `420de5b` | 10-10 | Task 3C: leaving rods out of the analysis by rule |
| `b181fed` | 10-10 | Task 4C: a part saved to a file, placed in another model |
| `7697d34` | 10-10 | The .vscode launch configurations (archives only — see `dea18e5`) |
| `dea18e5` | 10-10 | The launch configurations were never actually committed |
| `f12d7ca` | 10-10 | Full account of the five tasks, and what an audit found |
| `0b70d48` | 10-10 | The user guide covers the grouping work |
| `de6cadd` | 10-10 | The second audit gap is closed too |
| `a6b8cfd` | 10-10 | Rebuild both archives: 0.5.0, launch configs, new documentation |
| `97c445c` | 10-10 | Rebuild the customer archive: it still carried the 10-03 app |
| `37f5ce1` | 10-10 | A plain build produces all three archives, with one stamp |

---

## 14 · First things to do on the new account

1. **Confirm the branch.** `git fetch && git log --oneline -1 origin/claude/v32-st01`
   should show `37f5ce1` (or later). All the work is there; `nice-feynman-cof87g`
   is stale.
2. **Reinstall the extension** — 0.5.0, per §7. Nothing from Task 5 is visible
   until you do.
3. **Run the suite the way §8 describes** — `/usr/bin/python3.12`, a verified
   display, xdist. Expect 4517/5 and check the five against §8's list before
   investigating anything.
4. **Decide the licence** (§12). It is the only thing genuinely outstanding.
5. **Run `tools/check_excluded_groups.py`** over your own model folder. Models
   saved before `caddb28` may have lost their `excluded` flags, and that tool is
   read-only — it reports, it does not modify.
