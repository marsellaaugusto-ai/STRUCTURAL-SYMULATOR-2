"""Live-widget checks for the shared layout shell (common.AppShell and
common.CollapsibleSection).

These two widgets exist to end a spread the tabs had drifted into: six tabs,
four different arrangements of the same three things (toolbar, control panel,
drawing). The shell fixes the arrangement in ONE place -- panel on the left,
behind a draggable sash -- so a tab cannot quietly go its own way again.

Per MANIFESTO sec 2 these are measurements against a real mapped window, not
inferences from the layout code. Every assertion below was false for at least
one tab before the shell existed.
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


def _new_root_or_skip():
    if tk is None:
        pytest.skip('tkinter not importable in this environment')
    last = None
    for attempt in range(4):
        try:
            return tk.Tk()
        except Exception as ex:
            last = ex
            gc.collect()
            time.sleep(0.25 * (attempt + 1))
    pytest.skip(f'no display available to run this UI-level check ({last})')


@pytest.fixture()
def root():
    r = _new_root_or_skip()
    r.geometry('1280x800')
    yield r
    try:
        r.destroy()
    except Exception:
        pass
    gc.collect()


def _settle(root, times=3):
    for _ in range(times):
        root.update_idletasks()
        root.update()


# ═════════════════════════════════════════════════════════════════════════════
#  AppShell
# ═════════════════════════════════════════════════════════════════════════════
def _shell(root, **kw):
    from common import AppShell
    sh = AppShell(root, **kw)
    sh.pack(fill='both', expand=True)
    tk.Button(sh.toolbar, text='Analyze').pack(side='left')
    tk.Entry(sh.panel.interior).pack(fill='x')
    tk.Canvas(sh.work, bg='white').pack(fill='both', expand=True)
    tk.Label(sh.lower, text='diagrams').pack()
    _settle(root)
    return sh


def test_panel_is_on_the_left_of_the_drawing(root):
    """The whole point of the shell. Truss, Beam, Arch and Cable each put
    this panel on the RIGHT; Stereo put it on the left and called that the
    house convention. Now it is one."""
    sh = _shell(root)
    assert sh.panel.winfo_ismapped()
    assert sh.work.winfo_ismapped()
    assert sh.panel.winfo_rootx() < sh.work.winfo_rootx()


def test_panel_starts_at_the_requested_width(root):
    sh = _shell(root, panel_width=340)
    assert abs(sh.panel.winfo_width() - 340) <= 2


def test_sash_can_be_dragged_and_the_panel_follows(root):
    """A fixed panel width 'cannot be right for everyone -- the tab is used
    at 1280 and at 2560' (perforated_beam_app). The width is the user's."""
    sh = _shell(root, panel_width=340)
    start = sh.panel.winfo_width()
    sh.body.sash_place(0, 520, 0)
    _settle(root)
    assert sh.panel.winfo_width() > start
    assert abs(sh.panel.winfo_width() - 520) <= 8

    sh.body.sash_place(0, 200, 0)
    _settle(root)
    assert abs(sh.panel.winfo_width() - 200) <= 8


def test_drawing_keeps_a_floor_no_matter_the_sash(root):
    """The drawing is what every tab is for; controls never swallow it."""
    from common import AppShell
    sh = _shell(root, panel_width=340)
    sh.body.sash_place(0, 4000, 0)      # drag far past the window edge
    _settle(root)
    assert sh.work.winfo_width() >= AppShell.WORK_MIN - 8


def test_lower_pane_shows_hides_and_keeps_its_contents(root):
    """The diagram band was a fixed 260 px that the drawing could not
    reclaim. It is now a pane with its own sash, and hiding it must not
    destroy what the tab built inside it."""
    sh = _shell(root)
    assert not sh.lower_visible()

    sh.show_lower(height=200)
    _settle(root)
    assert sh.lower_visible() and sh.lower.winfo_ismapped()
    assert sh.lower.winfo_height() > 50

    sh.hide_lower()
    _settle(root)
    assert not sh.lower_visible()
    assert not sh.lower.winfo_ismapped()

    sh.show_lower(height=200)
    _settle(root)
    assert sh.lower.winfo_children(), 'contents must survive a hide/show'
    assert sh.lower.winfo_children()[0].winfo_ismapped()


def test_status_bar_stays_mapped_when_the_window_is_small(root):
    """Packed before the expanding body on purpose: a status bar packed
    after it is the first thing Tk starves."""
    sh = _shell(root)
    for w in (1280, 900, 700, 520):
        root.geometry(f'{w}x620')
        _settle(root)
        assert sh.status_label.winfo_ismapped(), f'status bar lost at {w} px'


def test_set_status_reaches_the_label(root):
    sh = _shell(root)
    sh.set_status('Done — 4 tension, 3 compression.')
    _settle(root)
    assert 'tension' in sh.status_label.cget('text')


# ═════════════════════════════════════════════════════════════════════════════
#  CollapsibleSection
# ═════════════════════════════════════════════════════════════════════════════
def _section(root, **kw):
    from common import CollapsibleSection
    sec = CollapsibleSection(root, text='Plates', **kw)
    sec.pack(fill='x')
    btn = tk.Button(sec.body, text='Add shear panel')
    btn.pack()
    _settle(root)
    return sec, btn


def test_section_starts_in_the_state_it_was_given(root):
    shut, shut_btn = _section(root, open=False)
    assert not shut.is_open()
    assert not shut_btn.winfo_ismapped()

    open_sec, open_btn = _section(root, open=True)
    assert open_sec.is_open()
    assert open_btn.winfo_ismapped()


def test_toggling_folds_and_unfolds_the_body(root):
    sec, btn = _section(root, open=True)
    sec.toggle(); _settle(root)
    assert not btn.winfo_ismapped()
    sec.toggle(); _settle(root)
    assert btn.winfo_ismapped()


def test_a_folded_section_still_shows_its_title(root):
    """Folding is not hiding. The section keeps its place and its name, so
    the control stays discoverable -- that is the whole difference between
    this and a widget that fell off the panel edge."""
    sec, _btn = _section(root, open=False)
    assert sec.winfo_ismapped()
    assert sec.title_label.winfo_ismapped()
    assert 'Plates' in sec.title_label.cget('text')


def test_the_marker_says_which_way_the_section_will_go(root):
    from common import CollapsibleSection
    sec, _btn = _section(root, open=True)
    assert sec.title_label.cget('text').startswith(CollapsibleSection.MARK_OPEN)
    sec.set_open(False); _settle(root)
    assert sec.title_label.cget('text').startswith(CollapsibleSection.MARK_SHUT)


def test_clicking_the_title_toggles_it(root):
    sec, btn = _section(root, open=True)
    sec.title_label.event_generate('<Button-1>')
    _settle(root)
    assert not btn.winfo_ismapped()
    sec.header.event_generate('<Button-1>')
    _settle(root)
    assert btn.winfo_ismapped()


def test_retitling_keeps_the_fold_marker(root):
    """Several panels retitle themselves ('Load on node 3'). A caller that
    does so must not have to know this is not a LabelFrame."""
    from common import CollapsibleSection
    sec, _btn = _section(root, open=True)
    sec.configure(text='Load on node 3')
    assert 'Load on node 3' in sec.title_label.cget('text')
    assert sec.title_label.cget('text').startswith(CollapsibleSection.MARK_OPEN)


def test_on_toggle_callback_fires(root):
    seen = []
    sec, _btn = _section(root, open=True)
    sec.on_toggle(lambda s: seen.append(s.is_open()))
    sec.set_open(False)
    sec.set_open(True)
    assert seen == [False, True]


def test_set_open_to_the_current_state_is_a_no_op(root):
    seen = []
    sec, _btn = _section(root, open=True)
    sec.on_toggle(lambda s: seen.append(s.is_open()))
    sec.set_open(True)
    assert seen == []
