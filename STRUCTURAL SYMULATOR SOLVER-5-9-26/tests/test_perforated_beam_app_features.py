"""
test_perforated_beam_app_features.py -- integration tests for the three
features added to the Perforated Beam tab, driven through the real Tk
widgets rather than the math modules directly.

The math is tested closed-form elsewhere (test_hyperstatic_math.py,
test_welded_section.py, test_section_sketch.py). What these tests cover is
the wiring that those cannot see: that the support list actually reaches
the solver, that the compound offsets actually reach the section, that a
weld drawn on a profile survives being placed into a compound, and that
the report prints numbers rather than raising.

  1. test_simple_mode_unchanged -- the determinate path still behaves
     exactly as before the feature work.
  2. test_advanced_supports_* -- the support editor produces a genuinely
     hyperstatic beam, and the report shows the textbook reactions.
  3. test_fixed_end_moment_is_reported_as_hogging_at_BOTH_ends -- the
     specific reading trap the report exists to avoid: the raw reaction
     couple is the internal moment at the left end and its negative at
     the right, so printing it raw would show a fixed-fixed beam under
     gravity as hogging at one end and sagging at the other.
  4. test_compound_offsets_reach_the_section -- a cap plate raises the
     neutral axis and makes S_top != S_bot.
  5. test_drawn_welds_move_with_their_profile -- the weld translation.
  6. test_report_includes_weld_check -- end to end through _analyze.
"""
import sys
import time
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

import pytest

tk = pytest.importorskip('tkinter')

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import hyperstatic_math as hym
from apps.perforated_beam import section_profile_math as secm
from apps.perforated_beam.perforated_beam_app import PerforatedBeamApp


@pytest.fixture(scope='session')
def tk_root():
    """ONE Tk root for the whole module, created with retries.

    Two things were learned the hard way here, both worth keeping:

    1. A root per test is flaky -- so this is session-scoped, and each
       test gets a fresh app widget instead.
    2. `tk.Tk()` still fails intermittently when the machine is loaded,
       and a bare `pytest.skip` on TclError turned that into 24 silently
       skipped tests during a full-suite run. A skipped test reads exactly
       like a passing one in the summary, so that is the worst possible
       response to a TRANSIENT failure. Retry instead, and skip only when
       the display is genuinely unavailable -- which a retry loop
       distinguishes and a single attempt cannot."""
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


@pytest.fixture
def app(tk_root):
    widget = PerforatedBeamApp(tk_root)
    yield widget
    widget.destroy()


def rect_sketch(w, h):
    o = secm.SectionOutline((-w / 2, -h / 2))
    for p in [(w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]:
        o.add_line(p)
    return secm.SectionSketch(o)


def set_supports(app, specs):
    app.support_mode_var.set('advanced')
    app._on_support_mode_change()
    app.support_specs = [{'x': x, 'kind': k, 'torsion': True} for x, k in specs]
    app._refresh_support_list()
    app._update_support_status()


def udl(app, L, w):
    app.length = L
    app.set_unit_value(app.len_var, L)
    app.loads = [{'type': 'Distributed load', 'x1': 0.0, 'x2': L,
                  'v1': w, 'v2': w, 'e': 0.0}]
    app._refresh_load_list()


# ── 1. nothing moved for the ordinary case ───────────────────────────────

def test_simple_mode_unchanged(app):
    app._load_example()
    app._analyze()
    text = app.result_text.get('1.0', 'end')
    assert 'Reactions: RA=60000.0 N, RB=60000.0 N' in text
    assert 'HYPERSTATIC' not in text
    assert app.report['reactions'] is not None


# ── 2. hyperstatic supports ──────────────────────────────────────────────

def test_advanced_mode_seeds_from_the_simple_model(app):
    """Switching modes must not throw away the supports already set."""
    app.supports = (500.0, 7500.0)
    app.support_mode_var.set('advanced')
    app._on_support_mode_change()
    assert [s['x'] for s in app.support_specs] == [500.0, 7500.0]
    assert all(s['kind'] == hym.PIN for s in app.support_specs)


def test_advanced_supports_reach_the_solver(app):
    """Two equal spans under UDL: 3wL/8, 10wL/8, 3wL/8."""
    udl(app, 8000.0, 20.0)
    set_supports(app, [(0.0, hym.PIN), (4000.0, hym.PIN), (8000.0, hym.PIN)])
    assert 'hyperstatic, 1 redundant' in app.support_status_label.cget('text')
    app._analyze()
    R = app.report['support_reactions']
    w, span = 20.0, 4000.0
    assert R[0][1] == pytest.approx(3 * w * span / 8, rel=1e-6)
    assert R[1][1] == pytest.approx(10 * w * span / 8, rel=1e-6)
    assert R[2][1] == pytest.approx(3 * w * span / 8, rel=1e-6)
    assert app.report['indeterminacy'] == 1
    assert 'HYPERSTATIC' in app.result_text.get('1.0', 'end')


def test_fixed_end_moment_is_reported_as_hogging_at_both_ends(app):
    """A fixed-fixed beam under gravity hogs at BOTH ends. The raw reaction
    couple does not read that way at the right-hand support, which is the
    whole reason the report converts to the internal moment."""
    udl(app, 8000.0, 20.0)
    set_supports(app, [(0.0, hym.FIXED), (8000.0, hym.FIXED)])
    app._analyze()
    beam = pbm.BeamConfig(L=8000.0, section=app._current_section(),
                          material=app._current_material(),
                          support_specs=[hym.SupportSpec(0.0, hym.FIXED),
                                         hym.SupportSpec(8000.0, hym.FIXED)])
    beam.dist_loads.append(pbm.DistLoad(0.0, 8000.0, 20.0, 20.0))
    exact = -20.0 * 8000.0 ** 2 / 12.0
    for x in (0.0, 8000.0):
        assert app._support_moment(beam, x) == pytest.approx(exact, rel=1e-3)
    text = app.result_text.get('1.0', 'end')
    # both printed end moments negative -> both hogging
    assert text.count('M=-') == 2
    assert 'M=+' not in text


def test_a_bad_support_list_is_reported_not_raised(app):
    app.support_mode_var.set('advanced')
    app._on_support_mode_change()
    app.support_specs = [{'x': 1000.0, 'kind': hym.PIN, 'torsion': True}]
    app._update_support_status()
    assert 'not valid' in app.support_status_label.cget('text')


# ── 3. compound section ──────────────────────────────────────────────────

def _setup_compound(app, cap_dy=212.5):
    app._clear_all()
    udl(app, 6000.0, 30.0)
    app.section_mode_var.set('Two profiles, freely placed (welded)')
    app._on_section_mode_change()
    for prefix, (w, h) in (('cp_a', (200.0, 400.0)), ('cp_b', (300.0, 25.0))):
        sk = rect_sketch(w, h)
        setattr(app, f'{prefix}_custom_profile_section', sk.to_section(f'{prefix}'))
        setattr(app, f'{prefix}_custom_profile_sketch', sk)
        getattr(app, f'{prefix}_base_kind_var').set('Custom drawn profile')
    app.compound_offset_vars['cp_a'][0].set('0')
    app.compound_offset_vars['cp_a'][1].set('0')
    app.compound_offset_vars['cp_b'][0].set('0')
    app.compound_offset_vars['cp_b'][1].set(str(cap_dy))
    app._apply_widget_state()


def test_compound_offsets_reach_the_section(app):
    """The cap plate must raise the neutral axis and break the symmetry --
    the thing the old side-by-side built-up class cannot express."""
    _setup_compound(app)
    sec = app._current_section()
    assert sec.A == pytest.approx(200 * 400 + 300 * 25, rel=1e-12)
    expect_cy = (80000 * 0.0 + 7500 * 212.5) / 87500.0
    assert sec.centroid[1] == pytest.approx(expect_cy, rel=1e-9)
    assert sec.S_top > sec.S_bot                     # bottom fiber is the far one
    # parallel-axis check, independently
    I_expect = (200 * 400 ** 3 / 12 + 80000 * expect_cy ** 2
                + 300 * 25 ** 3 / 12 + 7500 * (212.5 - expect_cy) ** 2)
    assert sec.I == pytest.approx(I_expect, rel=1e-9)


def test_compound_offset_of_zero_matches_a_side_by_side_pair(app):
    """Placed at equal height, the compound must agree with the class that
    can only do equal height."""
    app._clear_all()
    app.section_mode_var.set('Two profiles, freely placed (welded)')
    app._on_section_mode_change()
    ch = pbm.CHANNEL_CATALOG['UPN 220']
    for prefix, dx in (('cp_a', '-100'), ('cp_b', '100')):
        getattr(app, f'{prefix}_base_kind_var').set('Channel (catalog)')
        getattr(app, f'{prefix}_channel_var').set('UPN 220')
        app.compound_offset_vars[prefix][0].set(dx)
        app.compound_offset_vars[prefix][1].set('0')
    app._apply_widget_state()
    sec = app._current_section()
    old = pbm.BuiltUpDoubleSection(ch, gap=200.0)
    assert sec.A == pytest.approx(old.A, rel=1e-12)
    assert sec.I == pytest.approx(old.I, rel=1e-12)


def test_drawn_welds_move_with_their_profile(app):
    """A weld drawn along the cap plate must end up on the cap plate once
    the plate is offset -- not left behind near the origin, where it would
    report a passing check by holding nothing."""
    _setup_compound(app)
    sk = app.cp_b_custom_profile_sketch
    sk.add_weld((-150.0, -12.5), (150.0, -12.5), leg=0.0, n_lines=2, label='cap seam')
    sec = app._current_section()
    assert len(sec.welds) == 1
    weld = sec.welds[0]
    # drawn at the cap's own bottom edge (y=-12.5 about its own centroid),
    # so after placing that centroid at dy=212.5 it must sit at y=200
    assert weld.p1[1] == pytest.approx(200.0, rel=1e-9)
    assert weld.p2[1] == pytest.approx(200.0, rel=1e-9)


def test_weld_left_unmoved_would_hold_nothing(app):
    """Guards the reason the translation matters: the same weld at its
    drawn coordinates misses the assembled section entirely."""
    from apps.perforated_beam import welded_section_math as wsm
    _setup_compound(app)
    sec = app._current_section()
    stray = wsm.WeldLine((-150.0, -12.5), (150.0, -12.5))
    bad = wsm.CompoundSection(sec.parts, welds=[stray])
    moved = wsm.CompoundSection(sec.parts,
                                welds=[wsm.WeldLine((-150.0, 200.0), (150.0, 200.0))])
    assert wsm.check_welds(bad, 90000.0)[0].A_held != pytest.approx(7500.0, rel=1e-6)
    assert wsm.check_welds(moved, 90000.0)[0].A_held == pytest.approx(7500.0, rel=1e-6)


# ── 4. the report ────────────────────────────────────────────────────────

def _add_cap_weld(app, t_thick='0', t_thin='0'):
    app.cw_vars['x1'].set('-150'); app.cw_vars['y1'].set('200')
    app.cw_vars['x2'].set('150'); app.cw_vars['y2'].set('200')
    app.cw_vars['leg'].set('0'); app.cw_vars['n'].set('2')
    app.cw_vars['t_thick'].set(t_thick); app.cw_vars['t_thin'].set(t_thin)
    app._add_compound_weld()


def test_report_includes_weld_check(app):
    _setup_compound(app)
    _add_cap_weld(app)
    app._analyze()
    text = app.result_text.get('1.0', 'end')
    assert 'Weld check' in text
    assert 'CIRSOC 301' in text
    assert 'leg on strength alone' in text
    # SUPERSEDED 2026-09-10. This used to assert 'could not be checked':
    # with the thicknesses left blank, the fabrication rules were reported
    # as un-checked rather than silently skipped. They are now MEASURED
    # from the geometry instead, which serves the same intent -- never
    # skip the rule quietly -- by actually applying it. The old assertion
    # would now pin the weaker of the two behaviours.
    assert 'measured' in text
    assert 'Tabla J.2.4 minimum leg' in text
    assert 'could not be checked' not in text


def test_minimum_fillet_size_governs_a_lightly_loaded_seam(app):
    """The point of implementing Tabla J.2.4: this seam needs 0.39 mm on
    strength, which is not a weld. With the connected thicknesses stated,
    the report must say 5 mm and say why."""
    _setup_compound(app)
    _add_cap_weld(app, t_thick='25', t_thin='12')
    app._analyze()
    text = app.result_text.get('1.0', 'end')
    assert 'SPECIFY 8.0 mm' in text                    # 25 mm part -> 8 mm minimum
    assert 'minimum size, Tabla J.2.4' in text
    # The line now names the edge the maximum applies to; the value is
    # unchanged.
    assert 'J.2.2(b) maximum on the 12 mm edge: 10.0 mm' in text         # 12 mm edge -> 12-2


def test_weld_below_the_table_minimum_is_not_adequate(app):
    """A leg that passes on strength but is under the Tabla J.2.4 minimum
    must fail, not pass -- strength is not the only requirement."""
    from apps.perforated_beam import welded_section_math as wsm
    _setup_compound(app)
    sec = app._current_section()
    weld = wsm.WeldLine((-150.0, 200.0), (150.0, 200.0), leg=3.0, n_lines=2,
                        t_thicker=25.0, t_thinner=12.0)
    res = wsm.check_welds(wsm.CompoundSection(sec.parts, welds=[weld]), 90000.0)[0]
    assert res.util < 1.0                  # comfortable on strength
    assert not res.ok                      # but below the 8 mm minimum
    assert 'Tabla J.2.4' in res.note


def test_flange_to_web_joint_waives_the_minimum(app):
    """J.2.2(b) exemption -- reported, not silently applied either way."""
    from apps.perforated_beam import welded_section_math as wsm
    _setup_compound(app)
    sec = app._current_section()
    weld = wsm.WeldLine((-150.0, 200.0), (150.0, 200.0), n_lines=2,
                        t_thicker=25.0, t_thinner=12.0, flange_to_web=True)
    res = wsm.check_welds(wsm.CompoundSection(sec.parts, welds=[weld]), 90000.0)[0]
    assert res.leg_to_specify == pytest.approx(res.leg_required, rel=1e-12)
    assert 'waived' in res.size_governed_by


def test_report_shows_the_member_check(app):
    app._load_example()
    app._analyze()
    text = app.result_text.get('1.0', 'end')
    assert 'Member check on the gross section' in text
    assert 'Cap. F' in text and 'Cap. G' in text
    assert 'compacta' in text                          # IPE 400 classification
    assert 'DESIGN BASIS: CIRSOC 301-2018' in text


def test_drawn_profile_with_hole_and_weld_runs_end_to_end(app):
    app._clear_all()
    app.length = 5000.0
    app.set_unit_value(app.len_var, 5000.0)
    app.loads = [{'type': 'Point load', 'x1': 2500.0, 'v1': 80000.0, 'e': 0.0}]
    app._refresh_load_list()
    sk = rect_sketch(200.0, 300.0)
    sk.add_circle_hole((0.0, 0.0), 40.0, label='void')
    sk.add_weld((-100.0, 100.0), (100.0, 100.0), leg=5.0, n_lines=2, label='cap seam')
    app.custom_profile_section = sk.to_section('drawn')
    app.custom_profile_sketch = sk
    app.section_mode_var.set('Custom profile (drawn)')
    app._on_section_mode_change()
    app._analyze()
    text = app.result_text.get('1.0', 'end')
    assert 'cap seam' in text and 'util=' in text
    # q = V*Q/I, all three known in closed form for this shape
    import math
    I = 200 * 300 ** 3 / 12.0 - math.pi * 40.0 ** 4 / 4.0
    q = 40000.0 * (10000.0 * 125.0) / I
    assert f'{q:8.1f}' in text


# ── 5. the left panel must be reachable ──────────────────────────────────

def _lay_out(app, w=1280, h=800):
    """Lay the tab out at a real window size and return the panel canvas.

    The window is MAPPED here, not just sized. The left column is a
    PanedWindow, and Tk does not lay out a PanedWindow's panes while its
    toplevel is withdrawn -- the canvas stays 1x1, `yview_scroll` moves
    nothing, and a scrolling assertion fails against a layout that was
    never computed rather than against a real regression. A 1x1 canvas
    also proves nothing about whether the load panel can be reached,
    which is what these tests exist to check.

    It is withdrawn again immediately; the computed geometry survives, so
    the suite does not flash windows around any more than it used to."""
    app.master.geometry(f'{w}x{h}')
    app.pack(fill='both', expand=True)
    _settle(app)
    return app._left_canvas


def _settle(app):
    """Map the window long enough for Tk to lay it out, then hide it.

    Needed after ANY change that the PanedWindow has to act on -- the
    initial pack, and every `sash_place` -- because its panes keep their
    old size while the toplevel is withdrawn. Withdrawing again afterwards
    keeps the suite from flashing windows; the geometry it just computed
    survives."""
    app.master.deiconify()
    app.master.update_idletasks()
    app.master.update()
    app.master.withdraw()
    app.master.update_idletasks()


def test_left_panel_content_overflows_a_normal_window(app):
    """The reason this scrolls at all. The column is ~1030 px tall once the
    Supports panel, the lateral-bracing frame and the load panel are in it;
    a 1280x800 window shows about 750 px of that. Without scrolling the
    bottom ~280 px -- the whole Loads panel -- cannot be reached at all.

    Asserting the overflow, not just the scrollbar, keeps this test honest:
    if the panel is ever slimmed down enough to fit, this fails and says so
    rather than silently testing nothing."""
    c = _lay_out(app)
    bbox = c.bbox('all')
    content_h = bbox[3] - bbox[1]
    assert content_h > c.winfo_height(), 'panel now fits; this test no longer proves anything'


@pytest.mark.parametrize('w,h', [(1280, 800), (1366, 768), (1920, 1080)])
def test_both_ends_of_the_left_panel_are_reachable(app, w, h):
    c = _lay_out(app, w, h)
    c.yview_moveto(1.0)
    app.master.update_idletasks()
    assert c.yview()[1] >= 0.999, 'bottom of the panel cannot be reached'
    c.yview_moveto(0.0)
    app.master.update_idletasks()
    assert c.yview()[0] <= 0.001, 'top of the panel cannot be reached'


def test_load_panel_is_visible_once_scrolled_to_the_bottom(app):
    """The specific thing that was broken: the Loads panel sat below the
    fold with no way to get to it.

    Measured in CANVAS coordinates, not screen ones. The inner frame's
    origin is the canvas origin, so a child's offset within that frame is
    its canvas y -- and comparing it against `canvasy()` asks 'is it inside
    the scrolled viewport', which is true the moment the scroll is applied.
    Screen coordinates additionally depend on the window manager having
    repainted, which under a shared test root it may not have done yet."""
    c = _lay_out(app)
    inner = app._left_inner
    y_in_canvas = app.load_list.winfo_rooty() - inner.winfo_rooty()
    height = app.load_list.winfo_height()

    c.yview_moveto(0.0)
    app.master.update_idletasks()
    assert y_in_canvas > c.canvasy(c.winfo_height()), \
        'load list is already visible unscrolled; this test no longer proves anything'

    c.yview_moveto(1.0)
    app.master.update_idletasks()
    top, bottom = c.canvasy(0), c.canvasy(c.winfo_height())
    assert top <= y_in_canvas and y_in_canvas + height <= bottom + 1, \
        f'load list at canvas y={y_in_canvas} is outside the view [{top}, {bottom}]'


def test_panel_does_not_scroll_sideways(app):
    """The inner frame tracks the canvas width, so the scrollbar's own
    pixels never push the controls out of view horizontally."""
    c = _lay_out(app)
    bbox = c.bbox('all')
    assert bbox[2] - bbox[0] <= c.winfo_width() + 1


def test_compound_mode_is_the_tallest_and_still_scrolls(app):
    """Compound section mode adds two base pickers and a weld editor -- the
    tallest configuration the panel has."""
    c = _lay_out(app)
    base = c.bbox('all')[3]
    app.section_mode_var.set('Two profiles, freely placed (welded)')
    app._on_section_mode_change()
    app.master.update_idletasks()
    grown = c.bbox('all')[3]
    assert grown > base
    c.yview_moveto(1.0)
    app.master.update_idletasks()
    assert c.yview()[1] >= 0.999


def test_wheel_scrolls_the_panel(app):
    c = _lay_out(app)
    c.yview_moveto(0.0)
    app.master.update_idletasks()
    c.yview_scroll(3, 'units')
    app.master.update_idletasks()
    assert c.yview()[0] > 0.0


# -- left panel width, reported 2026-09-09 --------------------------------
#
# "in the side bar there are buttons that dont realy fit and the text on
# them is cut". Measured at the time: the column was 278 px while 23
# widgets asked for up to 358 px, so every group box and every help note
# was clipped by about 80 px.


def _hsb_shown(app):
    """Is the horizontal scrollbar in the layout?

    NOT `winfo_ismapped()`: these tests run with the toplevel
    withdrawn, where every widget reports unmapped and that assertion
    would pass whatever the bar was doing. `winfo_manager()` is ''
    once grid_remove() has pulled the widget out, and 'grid' when it
    is back."""
    return app._left_hsb.winfo_manager() != ''


def _panel_labels(app):
    """Every wrapping help note in the left column."""
    out = []
    stack = [app._left_inner]
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        if isinstance(w, tk.Label):
            try:
                if int(w.cget('wraplength')) > 0:
                    out.append(w)
            except (tk.TclError, ValueError):
                pass
    return out


def _clipped(app):
    """Widgets asking for more width than the panel gives them.

    `winfo_reqwidth()` is exactly the width below which Tk starts cutting
    a widget's content, so comparing it against the panel width IS the
    clipping test -- it needs no screenshot to detect."""
    panel = app._left_inner.winfo_width()
    out = []
    stack = [app._left_inner]
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        if w is not app._left_inner and w.winfo_reqwidth() > panel:
            out.append((w.winfo_reqwidth(), w.winfo_class()))
    return panel, out


def test_no_control_in_the_left_panel_is_clipped(app):
    """The reported bug, as an assertion. Compound mode is used because it
    is the widest configuration the column has."""
    _lay_out(app)
    app.section_mode_var.set('Two profiles, freely placed (welded)')
    app._on_section_mode_change()
    app.fit_left_panel()
    app.master.update_idletasks()
    panel, clipped = _clipped(app)
    assert not clipped, (
        f'{len(clipped)} widgets need more than the {panel}px panel: '
        f'{sorted(clipped, reverse=True)[:5]}')


def test_the_panel_fits_its_contents_without_a_horizontal_scrollbar(app):
    """Fitted, the content sits inside the canvas, so the horizontal bar
    -- which exists only for a user who drags the divider in -- is away."""
    c = _lay_out(app)
    app.fit_left_panel()
    app.master.update_idletasks()
    bbox = c.bbox('all')
    assert bbox[2] - bbox[0] <= c.winfo_width() + 1
    assert not _hsb_shown(app)


def test_the_divider_can_be_dragged(app):
    """The feature asked for: the column's width is the user's to set."""
    _lay_out(app)
    before = app._left_canvas.winfo_width()
    app._main_paned.sash_place(0, before + 90, 0)
    _settle(app)
    assert app._left_canvas.winfo_width() > before + 60


def test_dragging_the_divider_in_raises_a_horizontal_scrollbar(app):
    """Narrower than the controls need is allowed -- the user asked for
    it -- but the controls must stay REACHABLE rather than be clipped
    away, which is what the horizontal bar is for."""
    _lay_out(app)
    app._main_paned.sash_place(0, app.PANEL_MIN_W, 0)
    _settle(app)
    app._left_relayout()
    app.master.update_idletasks()
    assert _hsb_shown(app), 'narrowing past the controls must raise the bar'

    app.fit_left_panel()
    _settle(app)
    assert not _hsb_shown(app), 'fitted, the bar is not needed'


def test_the_notes_rewrap_when_the_panel_is_widened(app):
    """Otherwise the help text keeps the ribbon it was built with and
    widening the column looks broken."""
    _lay_out(app)
    app.fit_left_panel()
    app.master.update_idletasks()
    narrow = max(int(w.cget('wraplength')) for w in _panel_labels(app))

    app._main_paned.sash_place(0, app.PANEL_MAX_W, 0)
    _settle(app)
    app._left_relayout()
    app.master.update_idletasks()
    assert max(int(w.cget('wraplength')) for w in _panel_labels(app)) > narrow


def test_a_note_beside_a_button_wraps_to_the_room_it_actually_has(app):
    """The trap this cost an hour on: wrapping every note to the FULL
    panel width overflows a row that also holds a button. Each note wraps
    to the space remaining at its own x-offset, so no row exceeds the
    panel."""
    _lay_out(app)
    app.fit_left_panel()
    app.master.update_idletasks()
    panel = app._left_inner.winfo_width()
    for lbl in _panel_labels(app):
        row = lbl.master
        assert row.winfo_reqwidth() <= panel + 1, (
            f'row holding {str(lbl.cget("text"))[:40]!r} needs '
            f'{row.winfo_reqwidth()}px inside a {panel}px panel')


def test_fit_stays_within_its_own_bounds(app):
    """Clamped both ways: a very wide help note must not be able to eat
    the drawing area, and the column must not collapse to nothing."""
    _lay_out(app)
    app.fit_left_panel()
    app.master.update_idletasks()
    w = app._left_canvas.master.winfo_width()
    assert app.PANEL_MIN_W <= w <= app.PANEL_MAX_W + 2


def test_clear_resets_the_new_state(app):
    udl(app, 8000.0, 20.0)
    set_supports(app, [(0.0, hym.FIXED), (8000.0, hym.FIXED)])
    app.cw_vars['x2'].set('100')
    app._add_compound_weld()
    app._clear_all()
    assert app.support_specs == []
    assert app.compound_welds == []
    assert app.support_mode_var.get() == 'simple'


# ─────────────────────────────────────────────────────────────────────────
# 7. Load combinations and the Vierendeel method, 2026-09-10.
#
# These three controls exist because the tab and a hand-written report of
# the same beam could not be reconciled: the tab checked unfactored loads
# with the station scan, the document checked 1.2D+1.6L (governed by ASD)
# with the closed form, and neither page said so. What the tests below
# pin is the wiring -- that the combination reaches the solver, that the
# method reaches the RING SCHEDULE and not only the printed check, and
# that the user's own model is never scaled in place.
# ─────────────────────────────────────────────────────────────────────────

from apps.perforated_beam import load_combinations as lc          # noqa: E402
from apps.perforated_beam.perforated_beam_app import (             # noqa: E402
    VIER_HAND, VIER_STATION)


def _simple_loaded(app):
    app._clear_all()
    udl(app, 6000.0, 30.0)
    app._apply_widget_state()


def test_the_combination_reaches_the_reactions(app):
    """1.2 on a load classified permanent, and the reaction must move by
    exactly that -- not by 1.6, and not at all."""
    _simple_loaded(app)
    for ld in app.loads:
        ld['case'] = lc.CASE_D
    app.combo_var.set(lc.AS_ENTERED.label)
    app._analyze()
    plain = app.report['reactions'][0]
    app.combo_var.set(lc.LRFD_1.label)
    app._analyze()
    assert app.report['reactions'][0] == pytest.approx(1.2 * plain, rel=1e-9)


def test_analyzing_twice_does_not_compound_the_factors(app):
    """The trap this wiring exists to avoid. If _analyze factored the
    tab's own beam, a second press would give 1.44D and a third 1.73D,
    with nothing on screen to say the model had changed."""
    _simple_loaded(app)
    for ld in app.loads:
        ld['case'] = lc.CASE_D
    app.combo_var.set(lc.LRFD_1.label)
    app._analyze()
    once = app.report['reactions'][0]
    app._analyze()
    assert app.report['reactions'][0] == pytest.approx(once, rel=1e-12)
    assert app.loads[0]['v1'] == pytest.approx(30.0)      # the model is untouched


def test_the_report_states_which_combination_it_used(app):
    _simple_loaded(app)
    app.combo_var.set(lc.LRFD_1.label)
    app._analyze()
    text = app.result_text.get('1.0', 'end')
    assert '1.2D + 1.6L' in text
    assert 'loads as entered' not in text


def test_as_entered_keeps_the_old_disclaimer(app):
    _simple_loaded(app)
    app.combo_var.set(lc.AS_ENTERED.label)
    app._analyze()
    assert 'FACTORED actions' in app.result_text.get('1.0', 'end')


def test_the_asd_branch_scales_the_utilisations_not_the_loads(app):
    _simple_loaded(app)
    app.combo_var.set(lc.AS_ENTERED.label)
    app._analyze()
    plain = app.report['member'].util_flexure
    app.combo_var.set(lc.ASD_1.label)
    app._analyze()
    assert app.report['reactions'][0] == pytest.approx(
        app.report['reactions'][0])                        # loads unchanged
    text = app.result_text.get('1.0', 'end')
    assert 'Omega' in text
    # the member check itself is still computed in LRFD form
    assert app.report['member'].util_flexure == pytest.approx(plain, rel=1e-9)


def _perforated(app):
    """A beam with openings deep enough that the two methods separate."""
    app._clear_all()
    udl(app, 12000.0, 60.0)
    app.shape_var.set('Circle')
    app.set_unit_value(app.p1_var, 280.0)
    app.n_var.set('6')
    app.set_unit_value(app.spacing_var, 1500.0)
    app.set_unit_value(app.xstart_var, 2000.0)
    app._add_opening()
    app._apply_widget_state()


def test_the_method_selector_changes_the_reported_check(app):
    _perforated(app)
    app.vier_method_var.set(VIER_STATION)
    app._analyze()
    station = app.result_text.get('1.0', 'end')
    app.vier_method_var.set(VIER_HAND)
    app._analyze()
    hand = app.result_text.get('1.0', 'end')
    assert 'CIRSOC H.3.3, governing station' in station
    assert 'hand method, closed form' in hand


def test_both_methods_appear_whichever_is_selected(app):
    """The reconciliation is the point: a reader holding a hand
    calculation must be able to see both numbers on one page."""
    _perforated(app)
    for choice in (VIER_STATION, VIER_HAND):
        app.vier_method_var.set(choice)
        app._analyze()
        text = app.result_text.get('1.0', 'end')
        assert 'hole CENTRE' in text and 'hole EDGE' in text


def test_the_ring_schedule_follows_the_selected_method(app):
    """The complaint that prompted all of this: rings sized on one method
    beside a check printed in another. A schedule that says 'none needed'
    under a check reporting util 3 is the failure mode."""
    _perforated(app)
    app.rings_var.set(True)
    app.vier_method_var.set(VIER_HAND)
    app._analyze()
    assert 'Sized on the hand method' in app.result_text.get('1.0', 'end')
    app.vier_method_var.set(VIER_STATION)
    app._analyze()
    assert 'Sized on the station scan' in app.result_text.get('1.0', 'end')


def test_a_clean_station_scan_points_at_the_other_method(app):
    """When the station scan finds nothing, the report must not leave the
    reader thinking the question is settled -- their hand calculation
    will not agree."""
    _perforated(app)
    app.rings_var.set(True)
    app.vier_method_var.set(VIER_STATION)
    app._analyze()
    text = app.result_text.get('1.0', 'end')
    if 'None of the' in text:
        assert 'Switch the Vierendeel method' in text


def test_the_load_case_survives_a_save_and_reload(app):
    _simple_loaded(app)
    app.load_case_var.set(lc.CASE_D)
    app.set_unit_value(app.lx1_var, 1000.0)
    app.lv1_var.set(app.show('force', 5000.0))
    app.load_type_var.set('Point load')
    app._add_load()
    app.combo_var.set(lc.ASD_1.label)
    app.vier_method_var.set(VIER_HAND)
    st = app._gather_state()
    assert st['load_combination'] == 'asd_dl'
    assert st['vierendeel_method'] == 'hand'
    assert st['loads'][-1]['case'] == lc.CASE_D
    app._clear_all()
    app._apply_state(st)
    assert app.combo_var.get() == lc.ASD_1.label
    assert app.vier_method_var.get() == VIER_HAND
    assert app.loads[-1]['case'] == lc.CASE_D


def test_the_load_list_shows_each_load_s_case(app):
    """A load factored 1.6 that should have been 1.2 is invisible
    everywhere else."""
    _simple_loaded(app)
    app.load_case_var.set(lc.CASE_D)
    app._add_load()
    app._refresh_load_list()
    assert '[D]' in app.load_list.get(app.load_list.size() - 1)


def test_weld_the_seam_finds_the_joint_between_two_profiles(app, monkeypatch):
    """The answer to "how do I make sure the profiles are properly welded
    together?" -- the geometry knows where the seam is, and a weld drawn
    anywhere else reports q = 0, which reads like a pass."""
    said = {}
    monkeypatch.setattr('apps.perforated_beam.perforated_beam_app.messagebox.showinfo',
                        lambda t, m: said.setdefault('info', m))
    monkeypatch.setattr('apps.perforated_beam.perforated_beam_app.messagebox.showwarning',
                        lambda t, m: said.setdefault('warn', m))
    _setup_compound(app, cap_dy=212.5)         # the cap plate sits ON the profile
    app._weld_the_seam()
    assert 'info' in said, said
    assert app.compound_welds
    assert all(str(w.label).startswith('SEAM') for w in app.compound_welds)


def test_weld_the_seam_says_so_when_the_profiles_do_not_touch(app, monkeypatch):
    """The diagnosis the tab could not give: 1.94 mm apart, and every
    section property above describing a piece that does not exist."""
    said = {}
    monkeypatch.setattr('apps.perforated_beam.perforated_beam_app.messagebox.showwarning',
                        lambda t, m: said.setdefault('warn', m))
    monkeypatch.setattr('apps.perforated_beam.perforated_beam_app.messagebox.showinfo',
                        lambda t, m: said.setdefault('info', m))
    _setup_compound(app, cap_dy=260.0)         # lifted clear of the profile
    app._weld_the_seam()
    assert 'warn' in said, said
    assert 'not in contact' in said['warn']
    assert app.compound_welds == []


def test_running_weld_the_seam_twice_does_not_duplicate_the_welds(app, monkeypatch):
    monkeypatch.setattr('apps.perforated_beam.perforated_beam_app.messagebox.showinfo',
                        lambda t, m: None)
    _setup_compound(app, cap_dy=212.5)
    app._weld_the_seam()
    first = len(app.compound_welds)
    app._weld_the_seam()
    assert len(app.compound_welds) == first


def test_a_gapped_compound_is_called_out_in_the_report(app):
    """The audit has to reach the page, not just the module."""
    _setup_compound(app, cap_dy=260.0)
    app._analyze()
    assert 'DO NOT TOUCH' in app.result_text.get('1.0', 'end')


def test_a_warning_shared_by_every_opening_is_printed_once(app):
    """26 openings x 2 identical geometric warnings was 52 lines saying
    one thing twice, and it buried everything else on the page."""
    _perforated(app)
    # 300 mm through a 400 mm deep IPE: 75%, past the 70% the Vierendeel
    # model is used within, but still leaving a tee to check.
    app.set_unit_value(app.p1_var, 300.0)
    app.n_var.set('6')
    app._add_opening()
    app._apply_widget_state()
    app._analyze()
    text = app.result_text.get('1.0', 'end')
    n = text.count('beyond the ~70%')
    assert 0 < n <= 2, f'warning repeated {n} times'


def test_a_warning_raised_by_one_opening_names_it(app):
    """Collapsing a per-opening warning to a bare sentence would lose the
    one fact the reader needs on a variable layout."""
    app._clear_all()
    udl(app, 12000.0, 60.0)
    app.op_mode.set('Variable')
    for x, dia in ((3000.0, 200.0), (6000.0, 380.0), (9000.0, 200.0)):
        app.shape_var.set('Circle')
        app.set_unit_value(app.p1_var, dia)
        app.set_unit_value(app.xc_var, x)
        app._add_opening()
    app._apply_widget_state()
    app._analyze()
    text = app.result_text.get('1.0', 'end')
    for line in text.splitlines():
        if 'beyond the ~70%' in line:
            assert 'H2' in line, line
            assert 'H1' not in line, line
