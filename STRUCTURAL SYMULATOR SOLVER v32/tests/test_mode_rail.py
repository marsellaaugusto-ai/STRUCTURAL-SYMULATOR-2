"""The mode rail: the column of modes down the left edge of the panel.

WHAT IT IS FOR. The Truss panel used to stack eleven sections in one
scroll -- Analyze, stability, live, self-weight, material, connection
type, two load editors, construction geometry, arrays, plates, rod
families, selection -- none louder than any other. A student looking for
"where do I put the load" read all of them. Stereo had already solved
this: you are doing exactly ONE thing at a time, and only that thing's
controls belong on screen. `common.ModeRail` is that pattern made
shareable, and this file is what keeps the two tabs from drifting apart
again.

WHAT IS ASSERTED HERE, and why each one is a bug that has happened or
would not be noticed:

* The inactive frames are `pack_forget`-ed, not merely lowered. A hidden
  frame that is still packed keeps claiming width from the drawing, which
  is the whole cost the rail was meant to remove.
* Exactly one frame is mapped. Two at once is what a half-finished
  `select()` leaves behind, and it looks like a layout bug rather than a
  state bug.
* The rail sits LEFT of the panel and OUTSIDE the sash. Inside it, every
  drag of the panel's edge would resize the rail too.
* Alt+1..9 reach the modes and return 'break'. Without the break the
  keypress also lands in whatever entry had focus, so Alt+4 switches mode
  AND types a 4 into the span field.

Live widget measurements against a real window, per MANIFESTO sec 2.
"""
import gc
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import tkinter as tk
except Exception:
    tk = None

import pytest

from common import ModeRail


MODES = (('build', '▦', 'Build', 'what it is made of'),
         ('load', '↓', 'Load', 'what it carries'),
         ('out', 'Σ', 'Results', 'what came out'))


def _root_or_skip():
    if tk is None:
        pytest.skip('tkinter not importable in this environment')
    try:
        r = tk.Tk()
    except Exception as exc:
        pytest.skip('no display: %s' % exc)
    r.geometry('900x600+0+0')
    return r


def _settle(root, n=4):
    for _ in range(n):
        root.update_idletasks()
        root.update()
        time.sleep(0.01)


@pytest.fixture()
def rail():
    root = _root_or_skip()
    host = tk.Frame(root)
    host.pack(fill='both', expand=True)
    seen = []
    r = ModeRail(host, MODES, on_change=seen.append)
    r.pack(side='left', fill='y')
    body = tk.Frame(host)
    body.pack(side='left', fill='both', expand=True)
    frames = {}
    for key, _g, label, _t in MODES:
        fr = tk.Frame(body)
        tk.Button(fr, text='in ' + label).pack()
        frames[key] = r.register(key, fr)
    _settle(root)
    try:
        yield root, r, frames, seen
    finally:
        try:
            root.destroy()
        finally:
            gc.collect()


# ═════════════════════════════════════════════════════════════════════════════
#  One at a time
# ═════════════════════════════════════════════════════════════════════════════
def test_exactly_one_frame_is_shown_and_the_rest_are_unpacked(rail):
    root, r, frames, _seen = rail
    for key, _g, _l, _t in MODES:
        r.select(key)
        _settle(root)
        assert r.active() == key
        shown = [k for k, f in frames.items() if f.winfo_ismapped()]
        assert shown == [key], 'expected only %s on screen, got %s' % (key,
                                                                       shown)
        for k, f in frames.items():
            if k == key:
                continue
            assert f.winfo_manager() == '', (
                '%s is hidden but still packed -- it keeps claiming width '
                'from the drawing, which is the cost the rail removes' % k)


def test_registering_a_frame_hides_it_unless_it_is_the_active_one(rail):
    root, r, _frames, _seen = rail
    r.select('load')
    body = tk.Frame(r.master)
    body.pack(side='left')
    late = tk.Frame(body)
    late.pack()                        # packed by its builder...
    r.register('build', late)          # ...and the rail puts it away
    _settle(root)
    assert late.winfo_manager() == ''


def test_on_change_fires_once_per_selection_with_the_key(rail):
    root, r, _frames, seen = rail
    seen.clear()
    r.select('out')
    r.select('build')
    _settle(root)
    assert seen == ['out', 'build']


def test_a_key_the_rail_does_not_have_changes_nothing(rail):
    root, r, _frames, seen = rail
    r.select('build')
    seen.clear()
    r.select('nonexistent')
    _settle(root)
    assert r.active() == 'build'
    assert seen == []


def test_label_of_reads_back_the_name_not_the_key(rail):
    _root, r, _frames, _seen = rail
    assert r.label_of('out') == 'Results'
    assert r.label_of('unknown') == 'unknown'


# ═════════════════════════════════════════════════════════════════════════════
#  Where it sits
# ═════════════════════════════════════════════════════════════════════════════
def test_the_rail_is_left_of_the_frames_it_switches(rail):
    root, r, frames, _seen = rail
    r.select('build')
    _settle(root)
    assert r.winfo_rootx() + r.winfo_width() <= frames['build'].winfo_rootx() + 2


def test_the_rail_keeps_its_width_whatever_is_in_it(rail):
    """pack_propagate(False) -- without it a long mode name widens the
    rail and the drawing pays for it."""
    root, r, _frames, _seen = rail
    _settle(root)
    assert r.winfo_width() == ModeRail.WIDTH


def test_the_shell_puts_the_rail_outside_the_sash():
    """AppShell.rail_host is a sibling of the PanedWindow, not a pane in
    it: inside, every drag of the panel edge would resize the rail too."""
    from common import AppShell
    root = _root_or_skip()
    try:
        shell = AppShell(root, panel_width=240)
        shell.pack(fill='both', expand=True)
        r = ModeRail(shell.rail_host, MODES)
        r.pack(side='left', fill='y')
        _settle(root)
        assert r.winfo_rootx() + r.winfo_width() <= shell.body.winfo_rootx() + 2
        assert shell.rail_host not in shell.body.panes()
    finally:
        root.destroy()
        gc.collect()


# ═════════════════════════════════════════════════════════════════════════════
#  Hotkeys
# ═════════════════════════════════════════════════════════════════════════════
def test_alt_digits_jump_to_the_modes_in_rail_order(rail):
    root, r, _frames, _seen = rail
    r.bind_hotkeys(root)
    for n, (key, _g, _l, _t) in enumerate(MODES, start=1):
        root.event_generate('<Alt-Key-%d>' % n, when='now')
        _settle(root, 2)
        assert r.active() == key, 'Alt+%d should select %s' % (n, key)


def test_a_hotkey_does_not_also_reach_the_entry_that_had_focus(rail):
    """Returning 'break' is the whole point: half the work in these tabs
    is typing numbers into fields, and without it Alt+2 switches mode AND
    types a 2 into whichever one has focus."""
    root, r, _frames, _seen = rail
    r.bind_hotkeys(root)
    e = tk.Entry(root)
    e.pack()
    e.focus_force()
    _settle(root)
    root.event_generate('<Alt-Key-2>', when='now')
    _settle(root, 2)
    assert r.active() == 'load'
    assert e.get() == '', 'the keypress leaked into the entry: %r' % e.get()


def test_the_hint_names_the_shortcut():
    """A key nobody is told about is a key nobody presses."""
    root = _root_or_skip()
    hints = []
    try:
        r = ModeRail(root, MODES, on_hint=hints.append)
        r.pack(side='left', fill='y')
        _settle(root)
        item = r._items['load'][0]
        item.event_generate('<Enter>', when='now')
        _settle(root, 2)
        assert hints and 'Alt+2' in hints[0], hints
        item.event_generate('<Leave>', when='now')
        _settle(root, 2)
        assert hints[-1] == '', 'leaving must clear the hint again'
    finally:
        root.destroy()
        gc.collect()


# ═════════════════════════════════════════════════════════════════════════════
#  The Truss tab's own use of it
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope='module')
def truss():
    from tkinter import messagebox, filedialog
    for name in ('showerror', 'showwarning', 'showinfo'):
        setattr(messagebox, name, lambda *a, **k: None)
    filedialog.askopenfilename = lambda *a, **k: ''
    filedialog.asksaveasfilename = lambda *a, **k: ''
    from apps.truss.truss_app import TrussApp
    root = _root_or_skip()
    root.geometry('1366x820+0+0')
    host = tk.Frame(root)
    host.pack(fill='both', expand=True)
    app = TrussApp(host)
    _settle(root)
    try:
        yield root, app
    finally:
        try:
            root.destroy()
        finally:
            gc.collect()


def test_the_truss_panel_shows_one_mode_at_a_time(truss):
    root, app = truss
    for key, _g, _l, _t in app.MODES:
        app.rail.select(key)
        _settle(root, 2)
        shown = [k for k, f in app._mode_frames.items() if f.winfo_ismapped()]
        assert shown == [key], shown
        assert app.mode_title.get() == app.rail.label_of(key).upper()


def test_the_truss_tab_opens_on_analyse(truss):
    """Not on Build. The first thing an architecture student wants from
    this tab is to press the button and see what happens; building comes
    after they have something to look at."""
    _root, app = truss
    assert app.DEFAULT_MODE == 'analyse'


def test_picking_a_tool_takes_you_to_that_tool_s_controls(truss):
    """The Load tool used to leave you to scroll for the Fx/Fy fields."""
    root, app = truss
    for tool, mode in app.TOOL_MODE.items():
        app._set_tool(tool)
        _settle(root, 2)
        assert app.rail.active() == mode, (
            'the %s tool should show the %s controls, not %s'
            % (tool, mode, app.rail.active()))


def test_selection_is_pinned_below_every_mode_rather_than_inside_one(truss):
    """What is selected is true in all six modes, so the Selection box is
    a sibling of the mode frames, packed to the bottom, rather than a
    seventh thing the rail switches away.

    `winfo_ismapped()` is NOT what this asserts, and deliberately: inside
    a ScrollPanel every widget stays mapped whether or not it has been
    scrolled past, so that check would pass on a box nobody can see. What
    is checkable is the structure -- same parent as the mode frames, last
    in the pack order, side 'bottom' -- and that is what is checked.
    """
    root, app = truss
    interior = app.panel_outer.interior
    assert app.sel_frame.master is interior, (
        'the Selection box is inside a mode frame; it would vanish with '
        'that mode')
    assert app.sel_frame.pack_info().get('side') == 'bottom'
    # Packed BEFORE the mode frames, which is what makes side='bottom'
    # hold: pack hands each slave its parcel in packing order, so a
    # bottom slave registered after an expanding one gets what is left,
    # which is nothing.
    for key, _g, _l, _t in app.MODES:
        app.rail.select(key)
        _settle(root, 2)
        assert app.sel_frame.winfo_manager() == 'pack', (
            'the Selection box was unpacked in %s mode' % key)
        frame = app._mode_frames[key]
        slaves = interior.pack_slaves()
        assert slaves.index(app.sel_frame) < slaves.index(frame), (
            'in %s mode the Selection box is registered after the mode '
            'frame, so the expanding frame takes the space first and the '
            'bottom strip gets nothing' % key)
        assert app.sel_frame.winfo_rooty() >= frame.winfo_rooty(), (
            'the Selection box is drawn above the %s controls' % key)


def test_the_analyze_button_is_reachable_without_scrolling_in_its_mode(truss):
    root, app = truss
    app.rail.select('analyse')
    _settle(root, 3)
    assert app.analyze_btn.winfo_ismapped()
    top = app.analyze_btn.winfo_rooty() - app.panel_outer.winfo_rooty()
    assert 0 <= top < 120, (
        'Analyze sits %d px down the panel; it is the one control that '
        'must never need scrolling to reach' % top)


# ═════════════════════════════════════════════════════════════════════════════
#  The toolbar the rail freed up
# ═════════════════════════════════════════════════════════════════════════════
def _bar_rows(flow):
    return [w for w in flow.bar.winfo_children()
            if getattr(w, '_is_flow_row', False)]


def test_the_toolbar_fits_one_row_on_a_1366_px_laptop(truss):
    """1366x768 is the commonest screen this app is opened on. Two rows
    there cost the drawing 30 px and make the bar read as two sentences.

    This passes because of three things together, and it is here to stop
    any of them being undone quietly: `Advanced tools` moved into
    `Display ▾`, `Live` moved out of the panel into the run group rather
    than onto a group of its own, and the tool buttons lost a fixed
    seven-character width that cost about 150 px of padding.
    """
    root, app = truss
    root.geometry('1366x820+0+0')
    _settle(root, 6)
    rows = _bar_rows(app.toolbar_flow)
    assert len(rows) == 1, (
        'the toolbar needs %d rows at 1366 px' % len(rows))


def test_the_toolbar_still_wraps_when_it_has_to(truss):
    root, app = truss
    root.geometry('1366x820+0+0')
    _settle(root, 6)
    wide = len(_bar_rows(app.toolbar_flow))
    root.geometry('800x820+0+0')
    _settle(root, 6)
    narrow = len(_bar_rows(app.toolbar_flow))
    root.geometry('1366x820+0+0')
    _settle(root, 6)
    assert narrow > wide, (
        'the toolbar did not wrap: %d row(s) at 1366 px, %d at 800 px'
        % (wide, narrow))


def test_nothing_on_the_bar_is_drawn_under_the_camera_buttons(truss):
    """`Fit / Reset view` are packed to the RIGHT of the same bar and are
    not registered as a flow group, so the wrap arithmetic cannot see
    them. Before FlowBar.reserve, the last group was laid into space they
    already held and `Export ▾` was drawn underneath `Fit` at 1366 px.
    """
    root, app = truss
    for width in (1600, 1366, 1200, 1000):
        root.geometry('%dx820+0+0' % width)
        _settle(root, 6)
        cam_left = app.toolbar_flow.reserve.winfo_rootx()
        for row in _bar_rows(app.toolbar_flow):
            for g in row.winfo_children():
                if not g.winfo_ismapped():
                    continue
                right = g.winfo_rootx() + g.winfo_width()
                assert right <= cam_left + 2, (
                    'at %d px a toolbar group runs %d px into the camera '
                    'buttons' % (width, right - cam_left))
    root.geometry('1366x820+0+0')
    _settle(root, 4)


# ═════════════════════════════════════════════════════════════════════════════
#  No mode is empty
#
#  Reported 11-10-26: "the support tools and the rod and node tools do not
#  appear in their respective tabs in the basic or advanced modes". They
#  did not. Measured before the fix, packed top-level sections per mode:
#
#           Simple   Advanced
#    Build     0         2     Node and Rod had no controls at all
#    Support   0         0     empty in BOTH
#    Load      0         2
#    Section   2         4
#    Analyse   8         8
#    Results   0         0     until something was solved
#
#  A mode the rail can take you to and leave blank is worse than no rail:
#  it reads as a broken tab.
# ═════════════════════════════════════════════════════════════════════════════
def _packed_sections(app, key):
    return [w for w in app._mode_frames[key].winfo_children()
            if w.winfo_manager()]


@pytest.mark.parametrize('advanced', [False, True])
def test_no_mode_is_ever_empty(truss, advanced):
    root, app = truss
    app.advanced.set(advanced)
    app._apply_mode()
    _settle(root, 2)
    for key, _g, label, _t in app.MODES:
        app.rail.select(key)
        _settle(root, 2)
        got = _packed_sections(app, key)
        assert got, (
            '%s mode is empty in %s -- the rail can take you there and '
            'show you nothing' % (label, 'Advanced' if advanced else 'Simple'))


@pytest.mark.parametrize('tool,mode', [('node', 'build'), ('rod', 'build'),
                                       ('support', 'support'),
                                       ('load', 'load')])
def test_each_tool_has_a_button_in_its_own_mode(truss, tool, mode):
    """Not a copy of the toolbar's: the SAME tool, set through the same
    `_set_tool`, lit by the same `_refresh_tool_buttons`."""
    root, app = truss
    assert tool in app.mode_tool_btns
    btn = app.mode_tool_btns[tool]
    assert btn.master.winfo_toplevel() is root
    app.rail.select(mode)
    _settle(root, 2)
    assert btn.winfo_ismapped(), (
        'the %s button is not on screen in %s mode' % (tool, mode))
    app._set_tool('select')
    _settle(root, 2)
    btn.invoke()
    _settle(root, 2)
    assert app.tool.get() == tool
    assert app.rail.active() == mode


def test_the_panel_tool_buttons_light_with_the_toolbar_ones(truss):
    root, app = truss
    app._set_tool('rod')
    _settle(root, 2)
    assert app.mode_tool_btns['rod'].cget('bg') == \
        app.tool_btns['rod'].cget('bg')
    assert app.mode_tool_btns['node'].cget('bg') != \
        app.mode_tool_btns['rod'].cget('bg')


def test_the_support_picker_is_visible_before_any_joint_is_clicked(truss):
    """It used to live inside the per-node editor, which is
    `pack_forget`-ed until a joint is clicked -- so Support mode was
    blank until you had already guessed what to click."""
    root, app = truss
    app.rail.select('support')
    _settle(root, 2)
    assert app.sup_frame.winfo_manager() == '', (
        'this test is meaningless if the editor is already showing')
    for key, cell in app.sup_btns.items():
        assert cell.winfo_ismapped(), '%s is not on screen' % key


def test_picking_a_support_symbol_still_sets_the_type(truss):
    root, app = truss
    app.rail.select('support')
    _settle(root, 2)
    app._pick_support('fixed')
    assert app.sup_type.get() == 'fixed'
    app._pick_support('rollerY')
    assert app.sup_type.get() == 'rollerY'


def test_the_support_symbols_are_not_captioned_twice(truss):
    """The canvas drew the name AND the cell packed a label under it, so
    each symbol said its name twice with the canvas copy clipped."""
    _root, app = truss
    for key, cell in app.sup_btns.items():
        canvas = next(w for w in cell.winfo_children()
                      if w.winfo_class() == 'Canvas')
        texts = [canvas.itemcget(i, 'text')
                 for i in canvas.find_all()
                 if canvas.type(i) == 'text']
        assert texts == [], '%s draws its own caption as well: %s' % (key,
                                                                      texts)


def test_results_says_what_is_missing_before_anything_is_solved(truss):
    root, app = truss
    app._clear_all()
    app.rail.select('results')
    _settle(root, 2)
    assert app.res_placeholder.winfo_ismapped()
    assert 'Analyze' in app.res_placeholder.cget('text')
    app._load_example()
    app._run_analysis()
    _settle(root, 2)
    assert not app.res_placeholder.winfo_ismapped(), (
        'the placeholder is still up with results underneath it')
    assert app.rod_res_frame.winfo_manager() == 'pack'


def test_the_selection_box_explains_itself_on_a_fresh_tab(truss):
    """It was blank until the first click, which is the one moment you
    do not need telling what to click."""
    _root, app = truss
    assert 'Click a node/rod' in app.sel_text.get('1.0', 'end')


# ═════════════════════════════════════════════════════════════════════════════
#  The display switches moved into Analyse
# ═════════════════════════════════════════════════════════════════════════════
def _menu_of(app, label):
    """Walked recursively: a FlowBar group that is wider than the bar
    wraps its own children into extra frames, so the Menubutton is not
    always a grandchild of the bar."""
    found = []

    def walk(w):
        for ch in w.winfo_children():
            if ch.winfo_class() == 'Menubutton' and ch.cget('text') == label:
                found.append(ch)
            walk(ch)
    walk(app.toolbar_flow.bar)
    if not found:
        return None
    return found[0].nametowidget(found[0].cget('menu'))


def _menu_labels(menu):
    out = []
    for i in range(menu.index('end') + 1):
        if menu.type(i) != 'separator':
            out.append(menu.entrycget(i, 'label'))
    return out


def test_display_keeps_only_the_advanced_toggle(truss):
    root, app = truss
    root.geometry('1600x900+0+0')
    _settle(root, 6)
    menu = _menu_of(app, 'Display ▾')
    assert menu is not None, 'the Display menu is gone'
    labels = _menu_labels(menu)
    assert 'Advanced tools' in labels
    for gone in ('Force on each member', 'Deformed shape',
                 'Moment at rigid joints', 'Letter the joints (A, B, C…)'):
        assert gone not in labels, (
            '%r is still in the Display menu; it belongs in Analyse' % gone)
    root.geometry('1366x820+0+0')
    _settle(root, 4)


@pytest.mark.parametrize('attr', ['show_force_labels', 'letter_joints',
                                  'show_load_path', 'show_deform',
                                  'show_contraflexure', 'show_node_moments',
                                  'hide_zero', 'color_util'])
def test_every_display_switch_is_in_the_analyse_panel(truss, attr):
    """One box, in front of the result it describes, instead of a menu
    three rows up that shows one switch at a time."""
    root, app = truss
    app.rail.select('analyse')
    _settle(root, 2)
    var = str(getattr(app, attr))
    boxes = [w for w in app.show_frame.winfo_children()
             if w.winfo_class() == 'Checkbutton']
    boxes += [w for f in app.show_frame.winfo_children()
              if f.winfo_class() == 'Frame'
              for w in f.winfo_children() if w.winfo_class() == 'Checkbutton']
    assert any(str(b.cget('variable')) == var for b in boxes), (
        '%s has no switch in "What to show"' % attr)
    assert all(b.winfo_ismapped() for b in boxes)


def test_the_deflection_scale_sits_with_the_deformed_shape_switch(truss):
    """The number is meaningless without the switch, and the switch is
    hard to read without the number. They were a menu and a slider at
    opposite ends of the toolbar."""
    root, app = truss
    app.rail.select('analyse')
    _settle(root, 2)
    kinds = [w.winfo_class() for w in app.def_row.winfo_children()]
    assert 'Checkbutton' in kinds and 'Scale' in kinds
    assert app.def_row.winfo_ismapped()
    scale = next(w for w in app.def_row.winfo_children()
                 if w.winfo_class() == 'Scale')
    assert str(scale.cget('variable')) == str(app.def_scale)


def test_a_switch_in_the_panel_still_redraws(truss):
    root, app = truss
    app._load_example()
    app._run_analysis()
    app.rail.select('analyse')
    _settle(root, 2)
    app.show_deform.set(False)
    app._draw()
    _settle(root, 2)
    before = len(app.zc.canvas.find_all())
    app.show_deform.set(True)
    app._draw()
    _settle(root, 2)
    assert len(app.zc.canvas.find_all()) > before, (
        'ticking Deformed shape drew nothing new')
