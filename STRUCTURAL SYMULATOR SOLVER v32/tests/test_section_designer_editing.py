"""
test_section_designer_editing.py -- the profile designer's selection,
mirroring, weld feedback and web-opening panel, driven through the real
Tk widgets.

`test_sketch_transforms.py` proves the geometry of a mirror. What these
tests cover is everything that sits between the user and that geometry
and cannot be seen from the math side:

  * that clicking actually selects the thing under the cursor, including
    the small thing drawn on top of the big one;
  * that a selection is dropped whenever the indices it names could have
    moved, since a stale index that still resolves would mirror the
    WRONG hole rather than fail;
  * that the outline is mirrored in place instead of silently ignoring
    "as a copy", because a sketch has only one boundary;
  * that a weld line which misses the steel is reported as holding
    nothing -- it otherwise reads exactly like a passing check;
  * that web openings set in the designer reach the beam, and that the
    tab's own panel agrees with them afterwards.
"""
import sys
import time
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

import pytest

tk = pytest.importorskip('tkinter')

from apps.perforated_beam import section_profile_math as secm
from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam.section_profile_ui import SectionProfileDesigner
from apps.perforated_beam.perforated_beam_app import PerforatedBeamApp


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    """Every messagebox in both modules, redirected into a list.

    Without this a test that triggers an unexpected dialog does not fail
    -- it HANGS, because a modal box with no mainloop behind it waits for
    a click that will never come. That cost a full test run to find, so
    the guard is autouse rather than opt-in: no test in this file can
    open a real dialog even by accident.

    Returns the recorded calls as [(kind, title, message), ...].
    """
    seen = []
    for mod in ('apps.perforated_beam.section_profile_ui',
                'apps.perforated_beam.perforated_beam_app'):
        for kind in ('showinfo', 'showerror', 'showwarning'):
            monkeypatch.setattr(f'{mod}.messagebox.{kind}',
                                lambda *a, _k=kind, **kw: seen.append((_k,) + a))
    return seen


@pytest.fixture(scope='session')
def tk_root():
    """Retrying root -- a bare skip on TclError turns a transient failure
    into a silently skipped test, which reads like a passing one."""
    last = None
    for attempt in range(6):
        try:
            root = tk.Tk()
            break
        except tk.TclError as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    else:
        pytest.skip(f'no Tk display after 6 attempts: {last}')
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


def rect_sketch(w=100.0, h=200.0, x0=0.0, y0=0.0):
    o = secm.SectionOutline((x0, y0))
    for p in [(x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]:
        o.add_line(p)
    return secm.SectionSketch(o)


@pytest.fixture
def designer(tk_root):
    d = SectionProfileDesigner(tk_root, existing_sketch=rect_sketch())
    d.withdraw()
    d.update_idletasks()
    yield d
    try:
        d.destroy()
    except tk.TclError:
        pass


# ── selection ────────────────────────────────────────────────────────────

def test_clicking_inside_the_outline_selects_it(designer):
    designer.tool.set('select')
    designer._pick_at((50.0, 100.0))
    assert designer.selection == [('outline', None)]


def test_clicking_far_away_selects_nothing(designer):
    designer.tool.set('select')
    designer._pick_at((50.0, 100.0))
    designer._pick_at((5000.0, 5000.0))
    assert designer.selection == []


def test_a_hole_wins_over_the_outline_it_sits_in(designer):
    """Both contain the click point. The small thing drawn on top is the
    one the user aimed at, so ties must not resolve to the outline."""
    designer.sketch.holes.append(secm.CircleLoop((50.0, 100.0), 20.0))
    designer.tool.set('select')
    designer._pick_at((50.0, 100.0))
    assert designer.selection == [('hole', 0)]


def test_shift_click_adds_and_toggles(designer):
    designer.sketch.holes.append(secm.CircleLoop((50.0, 100.0), 20.0))
    designer.tool.set('select')
    designer._pick_at((50.0, 100.0))                 # the hole
    designer._pick_at((5.0, 5.0), add=True)          # the outline corner
    assert set(designer.selection) == {('hole', 0), ('outline', None)}
    designer._pick_at((50.0, 100.0), add=True)       # toggle the hole off
    assert designer.selection == [('outline', None)]


def test_select_all_picks_every_entity(designer):
    designer.sketch.holes.append(secm.CircleLoop((50.0, 100.0), 10.0))
    designer.sketch.welds.append(secm.SketchWeld((0.0, 150.0), (100.0, 150.0)))
    designer._select_all()
    assert set(designer.selection) == {('outline', None), ('hole', 0), ('weld', 0)}


@pytest.mark.parametrize('action', ['undo', 'clear', 'mirror'])
def test_selection_is_dropped_when_indices_could_move(designer, action):
    """A stale index that still RESOLVES is the dangerous case: it would
    silently act on a different hole. Dropping the selection is the safe
    response, so it is pinned."""
    designer.sketch.holes.append(secm.CircleLoop((50.0, 100.0), 10.0))
    designer._select_all()
    assert designer.selection
    if action == 'undo':
        designer._undo()
    elif action == 'clear':
        designer._clear_all()
    else:
        designer.mirror_about.set('axis')
        designer._mirror_selection(True)
    assert designer.selection == []


# ── mirroring through the UI ─────────────────────────────────────────────

def test_mirror_about_the_axis_moves_the_outline_across_zero(designer):
    designer.tool.set('select')
    designer._pick_at((50.0, 100.0))
    designer.mirror_about.set('axis')
    designer._mirror_selection(True)
    xs = [p[0] for p in designer.sketch.outline_points()]
    assert max(xs) == pytest.approx(0.0)
    assert min(xs) == pytest.approx(-100.0)


def test_mirror_about_a_typed_coordinate(designer):
    """The case the box girder needs: reflect about the seam, not zero."""
    designer.tool.set('select')
    designer._pick_at((50.0, 100.0))
    designer.mirror_about.set('custom')
    designer.mirror_at_var.set('100')
    designer._mirror_selection(True)
    xs = [p[0] for p in designer.sketch.outline_points()]
    assert (min(xs), max(xs)) == pytest.approx((100.0, 200.0))


def test_mirror_about_the_selection_centre_leaves_the_bbox_put(designer):
    before = secm.sketch_bbox(designer.sketch, include_welds=False)
    designer._select_all()
    designer.mirror_about.set('centre')
    designer._mirror_selection(True)
    after = secm.sketch_bbox(designer.sketch, include_welds=False)
    assert after == pytest.approx(before)


def test_mirroring_a_hole_as_a_copy_adds_a_second_one(designer):
    designer.sketch.holes.append(secm.CircleLoop((25.0, 100.0), 10.0))
    designer.tool.set('select')
    designer._pick_at((25.0, 100.0))
    designer.mirror_about.set('custom')
    designer.mirror_at_var.set('50')
    designer.mirror_copy.set(True)
    designer._mirror_selection(True)
    assert len(designer.sketch.holes) == 2
    assert designer.sketch.holes[0].center == pytest.approx((25.0, 100.0))
    assert designer.sketch.holes[1].center == pytest.approx((75.0, 100.0))


def test_the_outline_is_mirrored_in_place_even_with_copy_on(designer):
    """A sketch has exactly one boundary, so 'as a copy' cannot apply to
    it. It must transform in place and SAY so -- a checkbox that appears
    to do nothing is worse than one that explains itself."""
    designer.tool.set('select')
    designer._pick_at((50.0, 100.0))
    designer.mirror_about.set('axis')
    designer.mirror_copy.set(True)
    designer._mirror_selection(True)
    xs = [p[0] for p in designer.sketch.outline_points()]
    assert max(xs) == pytest.approx(0.0)
    assert 'in place' in designer.status.cget('text')


def test_mirroring_nothing_does_not_change_the_sketch(designer, dialogs):
    before = designer.sketch.outline_points()
    designer.selection = []
    designer._mirror_selection(True)
    assert designer.sketch.outline_points() == before
    assert dialogs and 'Select something first' in dialogs[0][2]


def test_a_bad_typed_mirror_coordinate_is_refused(designer, dialogs):
    before = designer.sketch.outline_points()
    designer._select_all()
    designer.mirror_about.set('custom')
    designer.mirror_at_var.set('not a number')
    designer._mirror_selection(True)
    assert dialogs, 'a non-numeric mirror line must be reported'
    assert designer.sketch.outline_points() == before


# ── move / delete ────────────────────────────────────────────────────────

def test_move_selection_shifts_by_the_typed_offset(designer):
    designer._select_all()
    designer.entry_var.set('25,-10')
    designer._move_selection()
    xs = [p[0] for p in designer.sketch.outline_points()]
    ys = [p[1] for p in designer.sketch.outline_points()]
    assert (min(xs), min(ys)) == pytest.approx((25.0, -10.0))


def test_delete_selection_removes_holes_high_index_first(designer):
    """Deleting several entries at once must not shift the indices out
    from under the later deletions."""
    for cx in (20.0, 50.0, 80.0):
        designer.sketch.holes.append(secm.CircleLoop((cx, 100.0), 5.0))
    designer.selection = [('hole', 0), ('hole', 2)]
    designer._delete_selection()
    assert len(designer.sketch.holes) == 1
    assert designer.sketch.holes[0].center == pytest.approx((50.0, 100.0))


# ── weld feedback ────────────────────────────────────────────────────────

def test_a_weld_that_misses_the_section_says_it_holds_nothing(designer):
    """The whole reason this readout exists: a weld holding nothing
    reports zero shear flow, which is indistinguishable from a passing
    check in the report."""
    designer.sketch.welds.append(secm.SketchWeld((500.0, 500.0), (600.0, 500.0), leg=6.0))
    designer._refresh_side_lists()
    designer.weld_list.selection_set(0)
    designer._update_weld_effect()
    assert 'holds nothing' in designer.weld_effect.cget('text')


def test_a_weld_that_cuts_the_section_reports_the_held_area(designer):
    designer.sketch.welds.append(secm.SketchWeld((-10.0, 180.0), (110.0, 180.0), leg=6.0))
    designer._refresh_side_lists()
    designer.weld_list.selection_set(0)
    designer._update_weld_effect()
    text = designer.weld_effect.cget('text')
    assert 'holds' in text and 'mm²' in text
    # the capped piece is 100 wide x 20 tall = 2000 mm^2
    assert '2,000' in text


# ── web openings ─────────────────────────────────────────────────────────

def test_no_opening_panel_without_a_context(designer):
    """A designer opened with no beam behind it has nothing to apply
    openings to, so the panel is absent rather than inert. (The tab
    itself supplies a context from every entry point, base-profile
    pickers included -- see test_designer_openings_reach_the_beam...)"""
    assert designer.opening_ctx is None
    assert not hasattr(designer, 'op_vars')


def test_opening_panel_reports_the_depth_ratio(tk_root):
    applied = []
    ctx = {'count': 0, 'apply': lambda *a: applied.append(a)}
    d = SectionProfileDesigner(tk_root, existing_sketch=rect_sketch(w=250.0, h=1800.0),
                               opening_ctx=ctx)
    d.withdraw()
    try:
        d.op_vars['dia'].set('1350')
        d._update_opening_status()
        text = d.op_status.cget('text')
        assert '1800' in text            # the section depth it measured
        assert '75.0 %' in text          # 1350 / 1800
        assert '70%' in text             # and the warning that follows
        assert d.op_status.cget('fg') == '#b03030'
    finally:
        d.destroy()


def test_opening_panel_accepts_a_sane_layout(tk_root):
    applied = []
    ctx = {'count': 0, 'apply': lambda *a: applied.append(a)}
    d = SectionProfileDesigner(tk_root, existing_sketch=rect_sketch(w=250.0, h=1800.0),
                               opening_ctx=ctx)
    d.withdraw()
    try:
        for k, v in (('dia', '1000'), ('spacing', '1800'), ('xstart', '2700'), ('n', '26')):
            d.op_vars[k].set(v)
        d._update_opening_status()
        assert d.op_status.cget('fg') == '#2e9e4f'
        d._apply_openings()
        assert applied == [(1000.0, 1800.0, 2700.0, 26)]
    finally:
        d.destroy()


def test_overlapping_openings_are_refused(tk_root, dialogs):
    applied = []
    ctx = {'count': 0, 'apply': lambda *a: applied.append(a)}
    d = SectionProfileDesigner(tk_root, existing_sketch=rect_sketch(250.0, 1800.0),
                               opening_ctx=ctx)
    d.withdraw()
    try:
        d.op_vars['dia'].set('1800')
        d.op_vars['spacing'].set('1800')       # equal -- no web post at all
        d._apply_openings()
        assert dialogs, 'overlapping openings must be refused'
        assert applied == []
    finally:
        d.destroy()


# ── end to end, through the tab ──────────────────────────────────────────

@pytest.fixture
def app(tk_root):
    widget = PerforatedBeamApp(tk_root)
    yield widget
    widget.destroy()


def test_designer_openings_reach_the_beam_and_the_tabs_own_panel(app):
    """The user's report was that there is no way to apply openings to a
    custom profile from the UI. This is the path that answers it."""
    app._openings_from_designer(1350.0, 1800.0, 2700.0, 26)
    assert len(app.openings) == 26
    assert app.openings[0].x_center == pytest.approx(2700.0)
    assert app.openings[-1].x_center == pytest.approx(2700.0 + 25 * 1800.0)
    # and the tab's own panel now shows the same thing, so the two places
    # that can set openings cannot disagree on screen
    assert app.shape_var.get() == 'Circle'
    assert app.p1_var.get() == '1350'
    assert int(app.n_var.get()) == 26
    assert float(app.spacing_var.get()) == pytest.approx(1800.0)


def test_openings_analyse_on_a_drawn_profile(app):
    """The capability the user could not reach: a drawn custom profile
    with circular web openings, analysed end to end."""
    H, B, T, LT, LB = 1800.0, 250.0, 10.0, 100.0, 200.0
    pts = [(0., -H/2), (B, -H/2), (B, -H/2+LB), (B-T, -H/2+LB), (B-T, -H/2+T),
           (T, -H/2+T), (T, H/2-T), (B-T, H/2-T), (B-T, H/2-LT), (B, H/2-LT),
           (B, H/2), (0., H/2)]
    o = secm.SectionOutline(tuple(pts[0]))
    for p in pts[1:]:
        o.add_line(tuple(p))
    sk = secm.SectionSketch(o)

    app.custom_profile_section = sk.to_section('custom')
    app.custom_profile_sketch = sk
    app.section_mode_var.set('Custom profile (drawn)')
    app._on_section_mode_change()
    app.length = 50400.0
    app.set_unit_value(app.len_var, 50400.0)
    app.supports = (1800.0, 48600.0)
    app._openings_from_designer(1350.0, 1800.0, 2700.0, 26)
    app.loads = [{'type': 'Distributed load', 'x1': 0.0, 'x2': 50400.0,
                  'v1': 5.0, 'v2': 5.0, 'e': 0.0}]
    app._analyze()

    assert app.report is not None, app.result_text.get('1.0', 'end')[:400]
    assert len(app.report['openings']) == 26
    assert app.report['governing_opening'] is not None


def test_mirror_a_into_b_builds_the_box_girder(app):
    """One drawing, both profiles. A and I must match the pair entered
    separately, which is what makes this a shortcut rather than a
    different section."""
    H, B, T, LT, LB = 1800.0, 250.0, 10.0, 100.0, 200.0
    pts = [(0., -H/2), (B, -H/2), (B, -H/2+LB), (B-T, -H/2+LB), (B-T, -H/2+T),
           (T, -H/2+T), (T, H/2-T), (B-T, H/2-T), (B-T, H/2-LT), (B, H/2-LT),
           (B, H/2), (0., H/2)]
    o = secm.SectionOutline(tuple(pts[0]))
    for p in pts[1:]:
        o.add_line(tuple(p))
    app.cp_a_custom_profile_sketch = secm.SectionSketch(o)
    app.cp_a_custom_profile_section = app.cp_a_custom_profile_sketch.to_section('custom')
    app.cp_a_base_kind_var.set('Custom drawn profile')
    app.cp_a_on_kind_change()

    app._mirror_a_into_b()

    assert app.cp_b_custom_profile_sketch is not None
    assert app.cp_b_custom_profile_section.A == pytest.approx(25600.0, rel=1e-9)

    app.section_mode_var.set('Two profiles, freely placed (welded)')
    app._on_section_mode_change()
    app.assembly_kind_var.set('closed')
    app.assembly_t_var.set('10')
    app._apply_widget_state()
    sec = app._current_section()
    assert sec.A == pytest.approx(51200.0, rel=1e-9)
    assert sec.d == pytest.approx(1800.0, rel=1e-9)
    assert sec.I == pytest.approx(2.1065561354e10, rel=1e-6)


def test_mirror_a_into_b_without_a_drawn_a_explains_itself(app, dialogs):
    app.cp_a_custom_profile_sketch = None
    app._mirror_a_into_b()
    assert dialogs and 'Custom drawn profile' in dialogs[0][2]


# ── layout, which no solver-side metric can see ──────────────────────────

def test_the_side_panel_scrolls(tk_root):
    """The weld readout, the scope note and the whole web-openings block
    together push the side panel past the window. Without a scrollbar its
    lower half -- including the button that applies the openings -- is
    simply unreachable, which is the exact complaint that put a scrollbar
    on the tab's own left column. Found by looking at the window; pinned
    here so it cannot come back quietly."""
    ctx = {'count': 0, 'apply': lambda *a: None}
    d = SectionProfileDesigner(tk_root, existing_sketch=rect_sketch(250.0, 1800.0),
                               opening_ctx=ctx)
    d.geometry('1280x820')
    d.withdraw()
    try:
        d.update_idletasks()
        assert hasattr(d, '_side_canvas'), 'the side panel must be inside a scroll canvas'
        inner_h = d._side_inner.winfo_reqheight()
        # The content really is taller than any sane window, so the
        # scrollbar is load-bearing rather than decorative.
        assert inner_h > 700, f'side panel content only {inner_h}px -- test is not proving anything'
        d._side_canvas.configure(scrollregion=d._side_canvas.bbox('all'))
        region = d._side_canvas.cget('scrollregion')
        assert region, 'scrollregion must be set or the panel cannot scroll'
        assert float(str(region).split()[3]) >= inner_h - 1
    finally:
        d.destroy()


def test_the_apply_openings_button_is_inside_the_scrolled_frame(tk_root):
    """Reachability, not just existence: the button must be a descendant
    of the scrollable frame, so scrolling can bring it into view."""
    ctx = {'count': 0, 'apply': lambda *a: None}
    d = SectionProfileDesigner(tk_root, existing_sketch=rect_sketch(250.0, 1800.0),
                               opening_ctx=ctx)
    d.withdraw()
    try:
        d.update_idletasks()
        found = []

        def walk(w):
            for child in w.winfo_children():
                if isinstance(child, tk.Button) and 'openings to the beam' in str(child.cget('text')):
                    found.append(child)
                walk(child)

        walk(d._side_inner)
        assert found, 'the Apply-openings button must live inside the scrolled frame'
    finally:
        d.destroy()


def test_the_toolbar_rows_stay_within_the_default_window(tk_root):
    """Packed as one row, the seven drawing tools plus the file actions
    ran off the right edge and Save/Load could not be clicked at all."""
    d = SectionProfileDesigner(tk_root, existing_sketch=rect_sketch())
    d.geometry('1280x820')
    d.withdraw()
    try:
        d.update_idletasks()
        rows = [c for c in d.winfo_children()
                if isinstance(c, tk.Frame) and c.winfo_reqwidth() > 0]
        for row in rows:
            assert row.winfo_reqwidth() <= 1280, (
                f'a toolbar row needs {row.winfo_reqwidth()}px, more than the '
                f'1280px window -- its right-hand buttons are unreachable')
    finally:
        d.destroy()


def test_typing_a_diameter_updates_the_readout_not_just_the_drawing(tk_root):
    """The preview circle and the depth-ratio text describe the same
    opening. If only the drawing followed the entry box, the numbers
    beside it would quietly describe the previous diameter."""
    ctx = {'count': 0, 'apply': lambda *a: None}
    d = SectionProfileDesigner(tk_root, existing_sketch=rect_sketch(250.0, 1000.0),
                               opening_ctx=ctx)
    d.withdraw()
    try:
        d.op_vars['dia'].set('500')
        assert '50.0 %' in d.op_status.cget('text')
        d.op_vars['dia'].set('900')          # no explicit refresh call
        assert '90.0 %' in d.op_status.cget('text')
    finally:
        d.destroy()
