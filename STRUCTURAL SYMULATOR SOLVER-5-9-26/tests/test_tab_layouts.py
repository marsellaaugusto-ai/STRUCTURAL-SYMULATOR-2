"""Responsive-layout regression for the Beam, Arch and Cable tabs.

Same finding as the Truss tab's T-1 (`test_truss_layout.py`), same three
causes, applied here on 2026-09-07: a fixed-width right panel packed AFTER
the expanding content, its scrolled interior pinned to the panel width, and
toolbars built as one un-wrapping row of `pack(side='left')` calls.

Measured before the fix -- mapped interactive controls, window 1600 -> 600 px:

    beam    26 -> 5
    arch    45 -> 14
    cable   26 -> 11

and after:

    beam    26 -> 25
    arch    45 -> 42
    cable   26 -> 25

with ZERO controls overflowing the window edge at any width, on all three.

WHY THE RESIDUAL IS NOT ZERO, and why this file does not assert that it is.
The controls still unmapped at the narrowest widths are small ones (34-65 px)
in the middle column's diagram-scale rows. They are not lost sideways -- they
are lost VERTICALLY: those rows wrap onto more and more lines as the column
narrows, and eventually the stack is taller than the column. That is a
different problem from T-1, it does not hide anything at any width a person
is likely to use, and pretending a percentage threshold is a physical law
would be worse than saying so. What IS asserted below is the thing that was
actually broken: the panel never disappears, and nothing is ever pushed off
the right edge.
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

TABS = {
    'beam':  ('apps.beam.beam_app', 'BeamApp'),
    'arch':  ('apps.arch.arch_app', 'ArchApp'),
    'cable': ('apps.cable.cable_app', 'CableApp'),
}


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


def _settle(root, n=12):
    for _ in range(n):
        root.update_idletasks()
        root.update()
        time.sleep(0.03)


def _make(which):
    from tkinter import messagebox, filedialog
    for name in ('showerror', 'showwarning', 'showinfo'):
        setattr(messagebox, name, lambda *a, **k: None)
    filedialog.askopenfilename = lambda *a, **k: ''
    filedialog.asksaveasfilename = lambda *a, **k: ''
    mod, cls = TABS[which]
    App = getattr(__import__(mod, fromlist=[cls]), cls)
    root = _new_root_or_skip()
    root.geometry('1600x950+0+0')
    host = tk.Frame(root)
    host.pack(fill='both', expand=True)
    app = App(host)
    app.pack(fill='both', expand=True)
    _settle(root, 14)
    return root, host, app


def _measure(root, host):
    widgets = []
    _all_widgets(host, widgets)
    controls = [w for w in widgets if w.winfo_class() in CONTROL_CLASSES]
    mapped = 0
    overflowing = []
    root_w = root.winfo_width()
    for w in controls:
        try:
            if not w.winfo_ismapped():
                continue
            x = w.winfo_rootx() - root.winfo_rootx()
            over = x + w.winfo_width() - root_w
        except Exception:
            continue
        mapped += 1
        if over > 2:
            overflowing.append((_label_of(w)[:24], over))
        elif x < -2:
            overflowing.append((_label_of(w)[:24], x))
    return mapped, overflowing


@pytest.mark.parametrize('which', sorted(TABS))
def test_the_right_panel_never_disappears(which):
    """THE T-1 bug. The panel used to be packed after the expanding content,
    so below ~850 px Tk gave it nothing and it was unmapped entirely -- with
    the analysis controls inside it."""
    root, host, app = _make(which)
    try:
        for width in WIDTHS:
            root.geometry('%dx950+0+0' % width)
            _settle(root)
            panel = app.panel_outer
            assert panel.winfo_ismapped(), (
                '%s: the right panel is not mapped at %d px -- check the pack '
                'order in _build_ui: ScrollPanel must be packed BEFORE the '
                'expanding content' % (which, width))
            assert panel.winfo_width() > 40, (
                '%s: the right panel collapsed to %d px at %d px'
                % (which, panel.winfo_width(), width))
    finally:
        root.destroy()
        gc.collect()


@pytest.mark.parametrize('which', sorted(TABS))
def test_no_control_is_pushed_off_the_right_edge(which):
    root, host, app = _make(which)
    try:
        for width in WIDTHS:
            root.geometry('%dx950+0+0' % width)
            _settle(root)
            _mapped, overflowing = _measure(root, host)
            assert not overflowing, (
                '%s at %d px: %s' % (which, width,
                                     ', '.join('%s (%+d px)' % t
                                               for t in overflowing)))
    finally:
        root.destroy()
        gc.collect()


@pytest.mark.parametrize('which', sorted(TABS))
def test_narrowing_does_not_collapse_the_control_count(which):
    """A weaker assertion than the Truss tab's, deliberately -- see this
    module's docstring. The point is that the count no longer FALLS OFF A
    CLIFF (beam went 26 -> 5, arch 45 -> 14), not that it is invariant."""
    root, host, app = _make(which)
    try:
        counts = {}
        for width in WIDTHS:
            root.geometry('%dx950+0+0' % width)
            _settle(root)
            counts[width], _ = _measure(root, host)
        widest = counts[WIDTHS[0]]
        assert widest > 0
        for width, n in counts.items():
            assert n >= 0.9 * widest, (
                '%s: only %d of %d controls mapped at %d px (%s)'
                % (which, n, widest, width, counts))
    finally:
        root.destroy()
        gc.collect()


@pytest.mark.parametrize('which', sorted(TABS))
def test_the_toolbar_wraps_instead_of_overflowing(which):
    """Direct evidence WrapBar is running: the bar's wrapped-row count must
    grow as the window narrows."""
    root, host, app = _make(which)
    try:
        def rows():
            return sum(1 for w in app.toolbar_wrap.bar.winfo_children()
                       if getattr(w, '_is_wrap_row', False))
        root.geometry('1600x950+0+0')
        _settle(root)
        wide = rows()
        root.geometry('700x950+0+0')
        _settle(root)
        narrow = rows()
        assert wide >= 1, '%s: the toolbar was never laid out by its WrapBar' % which
        assert narrow > wide, (
            '%s: the toolbar did not wrap: %d row(s) at 1600 px, %d at 700 px'
            % (which, wide, narrow))
    finally:
        root.destroy()
        gc.collect()
