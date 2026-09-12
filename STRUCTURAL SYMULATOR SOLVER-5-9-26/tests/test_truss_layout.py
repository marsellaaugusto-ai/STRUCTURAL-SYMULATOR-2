"""Regression guard for DIAGNOSIS_TRUSS_2026-09-05 finding T-1.

What went wrong: the right-hand panel was packed AFTER the expanding canvas,
so Tk handed it whatever the canvas did not want. As the window narrowed the
panel's controls first ran off the right edge and then stopped being mapped at
all -- at 800 px the entire panel, Analyze button included, was gone, with no
scrollbar and no error. The toolbar failed the same way from the other end:
its last two buttons were already unreachable at 1600 px.

Measured before the fix (61 interactive controls in the tab):

    width   mapped  overflowing   worst overflow
    1600      49         0            --
    1200      46         0            --
    1000      42        18          +102 px
     900      41        22          +202 px
     800      17         0          -- (the panel is GONE, not fixed)

Note the trap in that last row, and why this file asserts on the MAPPED count
rather than only on overflow: an unmapped widget cannot overflow, so
"0 overflowing" at 800 px read like a pass while being the worst case in the
table. A metric that improves when the thing it measures disappears is not
measuring the right thing. Both numbers are asserted here for that reason.

Per MANIFESTO sec 2 these are live widget measurements against a real window,
not inferences from the layout code.
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


WIDTHS = (1600, 1200, 1000, 900, 800, 700, 600)

CONTROL_CLASSES = ('Button', 'TButton', 'Checkbutton', 'TCheckbutton',
                   'Radiobutton', 'TRadiobutton', 'TCombobox', 'Entry',
                   'TEntry', 'Scale', 'Listbox')


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


def _all_widgets(w, out):
    try:
        if not w.winfo_exists():
            return
    except Exception:
        return
    out.append(w)
    try:
        kids = w.winfo_children()
    except Exception:
        return
    for ch in kids:
        _all_widgets(ch, out)


def _label_of(w):
    try:
        v = str(w.cget('text'))
        if v and not v.startswith('PY_VAR'):
            return v
    except Exception:
        pass
    return w.winfo_class()


@pytest.fixture()
def truss_app():
    from tkinter import messagebox, filedialog
    for name in ('showerror', 'showwarning', 'showinfo'):
        setattr(messagebox, name, lambda *a, **k: None)
    filedialog.askopenfilename = lambda *a, **k: ''
    filedialog.asksaveasfilename = lambda *a, **k: ''

    from apps.truss.truss_app import TrussApp
    root = _new_root_or_skip()
    root.geometry('1600x950+0+0')
    host = tk.Frame(root)
    host.pack(fill='both', expand=True)
    app = TrussApp(host)
    app._load_example()
    app._run_analysis()
    # Both context editors are only packed by the Load / Support tool's click
    # handler; pack them here so their controls are measured too -- otherwise
    # seven of the tab's controls are "unmapped" for a legitimate reason and
    # a real disappearance would hide among them.
    app.load_frame.pack(fill='x', padx=8, pady=4, before=app.sel_frame)
    app.sup_frame.pack(fill='x', padx=8, pady=4, before=app.sel_frame)
    _settle(root)
    try:
        yield root, host, app
    finally:
        try:
            root.destroy()
        finally:
            gc.collect()


def _settle(root, n=12):
    for _ in range(n):
        root.update_idletasks()
        root.update()
        time.sleep(0.03)


def _measure(root, host):
    """(mapped, unmapped, [(label, overflow_px), ...]) at the current width."""
    widgets = []
    _all_widgets(host, widgets)
    controls = [w for w in widgets if w.winfo_class() in CONTROL_CLASSES]
    mapped = unmapped = 0
    overflowing = []
    root_w = root.winfo_width()
    for w in controls:
        try:
            if not w.winfo_ismapped():
                unmapped += 1
                continue
            x = w.winfo_rootx() - root.winfo_rootx()
            over = x + w.winfo_width() - root_w
        except Exception:
            continue
        mapped += 1
        if over > 2:
            overflowing.append((_label_of(w)[:28], over))
        elif x < -2:
            overflowing.append((_label_of(w)[:28], x))
    return mapped, unmapped, overflowing


def _deliberately_hidden(app):
    """Controls the tab hides ON PURPOSE at the current moment, which must not
    be counted against the layout.

    The Construction-geometry panel shows only the fields the chosen guide
    kind uses -- a straight line has no radius, an arc has no expression --
    so a handful of entries are always unpacked and CANNOT all be visible at
    once. That is a different thing from a control the layout has lost, which
    is what this file is guarding, so it is subtracted precisely rather than
    the assertion being softened to a threshold.
    """
    hidden = 0
    for key, row in getattr(app, '_guide_rows', {}).items():
        if row.winfo_manager():
            continue
        hidden += sum(1 for c in row.winfo_children()
                      if c.winfo_class() in CONTROL_CLASSES)
    return hidden


def test_no_control_is_dropped_or_pushed_off_as_the_window_narrows(truss_app):
    root, host, _app = truss_app
    seen = {}
    for width in WIDTHS:
        root.geometry('%dx950+0+0' % width)
        _settle(root)
        mapped, unmapped, overflowing = _measure(root, host)
        seen[width] = (mapped, unmapped - _deliberately_hidden(_app), overflowing)

    widest = seen[WIDTHS[0]][0]
    assert widest > 0, 'measured no controls at all -- the harness is broken'

    for width in WIDTHS:
        mapped, unmapped, overflowing = seen[width]
        assert unmapped == 0, (
            'at %d px, %d control(s) are not mapped at all, over and above '
            'the guide fields the panel hides on purpose. Before T-1 the '
            'whole right panel vanished below 850 px; check the pack order in '
            '_build_ui -- the ScrollPanel must be packed BEFORE the expanding '
            'ZoomCanvas.' % (width, unmapped))
        assert mapped == widest, (
            'at %d px only %d of %d controls are mapped -- the count must not '
            'fall as the window narrows' % (width, mapped, widest))
        assert not overflowing, (
            'at %d px these controls sit past the window edge: %s' %
            (width, ', '.join('%s (%+d px)' % t for t in overflowing)))


def test_toolbar_wraps_to_more_rows_as_the_window_narrows(truss_app):
    """The toolbar must actually re-flow, not merely avoid overflowing by
    luck. Its wrapped-row count is the direct evidence FlowBar is running."""
    root, _host, app = truss_app

    def row_count(flow):
        return sum(1 for w in flow.bar.winfo_children()
                   if getattr(w, '_is_flow_row', False))

    root.geometry('1600x950+0+0')
    _settle(root)
    wide = row_count(app.toolbar_flow)

    root.geometry('700x950+0+0')
    _settle(root)
    narrow = row_count(app.toolbar_flow)

    assert wide >= 1, 'the toolbar was never laid out by its FlowBar'
    assert narrow > wide, (
        'the toolbar did not wrap: %d row(s) at 1600 px, %d at 700 px'
        % (wide, narrow))


def test_panel_keeps_its_content_reachable(truss_app):
    """The panel is allowed to be narrower than its content -- that is what
    the horizontal scrollbar is for -- but only when the window is genuinely
    tight, and the scrollbar must actually appear when it happens."""
    root, _host, app = truss_app
    panel = app.panel_outer

    root.geometry('1600x950+0+0')
    _settle(root)
    assert panel.canvas.winfo_width() >= panel.interior.winfo_reqwidth() - 2, (
        'on a wide window the panel should fit its own content without '
        'needing horizontal scrolling')

    root.geometry('600x950+0+0')
    _settle(root)
    if panel.interior.winfo_reqwidth() > panel.canvas.winfo_width() + 1:
        assert panel._hsb_shown, (
            'the panel content is wider than the panel but no horizontal '
            'scrollbar is shown -- the content is unreachable')
        assert panel.hsb.winfo_ismapped() and panel.hsb.winfo_height() > 0, (
            'the horizontal scrollbar is flagged as shown but has no size; '
            'a pack()ed latecomer next to an expand=True canvas gets zero '
            'space -- it must be grid()ed')
