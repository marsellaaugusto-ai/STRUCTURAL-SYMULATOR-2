"""A rendered equation must belong to the window that shows it.

`common.render_math` turns a mathtext string into a Tk PhotoImage for the
Rod Calculations report. A Tk image belongs to ONE interpreter. Without a
master, Pillow binds it to `tkinter._default_root` -- the first root the
process ever created -- which is not necessarily the window being built.
Show it in a second root and Tk refuses:

    _tkinter.TclError: image "pyimage1" doesn't exist

because that name lives in the other interpreter. One process with two Tk
roots is rare in normal use and routine in a test suite, which is where
this surfaced: `test_truss_layout.py`'s Rod Calculations case passed on its
own and failed in a full run, on pristine v32 as well as here. The bug was
the binding, not the test.
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

from common import render_math


def _root_or_skip():
    if tk is None:
        pytest.skip('tkinter not importable in this environment')
    try:
        return tk.Tk()
    except Exception as ex:
        pytest.skip(f'no display available ({ex})')


def _have_mathtext():
    try:
        import matplotlib  # noqa: F401
        from PIL import ImageTk  # noqa: F401
        return True
    except Exception:
        return False


@pytest.fixture()
def two_roots():
    """The shape that breaks it: tkinter's default root is NOT the window
    being built, because something earlier left a root alive.

    Built rather than assumed. In a bare process there is no default root
    yet, so one is made to stand in for the leak; in a full suite run an
    earlier test has usually left one already, and then the window under
    test is simply the next root. Either way the postcondition is the same
    and is asserted: the default root is not the window. The first version
    of this fixture asserted the bare-process case instead, and errored
    whenever the suite had already created a root -- which is exactly the
    condition the bug needs.
    """
    made = []
    if tk._default_root is None:
        stand_in = _root_or_skip()
        stand_in.withdraw()
        made.append(stand_in)
    app = _root_or_skip()
    app.withdraw()
    made.append(app)

    leaked = tk._default_root
    if leaked is app or leaked is None:
        pytest.skip('could not arrange a default root other than the window')
    yield leaked, app

    for r in reversed(made):
        try:
            r.destroy()
        except Exception:
            pass
    gc.collect()


def test_an_equation_shows_in_a_window_that_is_not_the_default_root(two_roots):
    if not _have_mathtext():
        pytest.skip('matplotlib/Pillow not installed')
    _leaked, app = two_roots

    img = render_math(r'$N=1$', master=app)
    assert img is not None

    label = tk.Label(app, image=img)
    label.pack()
    app.update_idletasks()          # raised TclError before the fix
    assert label.winfo_exists()


def test_without_a_master_it_binds_to_the_wrong_root(two_roots):
    """Pins WHY the master argument exists. If a future change makes this
    pass, the default-root binding is no longer dangerous and the master
    could be dropped -- but until then, dropping it reintroduces the bug."""
    if not _have_mathtext():
        pytest.skip('matplotlib/Pillow not installed')
    leaked, app = two_roots

    img = render_math(r'$N=1$')     # no master: binds to the leaked root
    assert img is not None
    with pytest.raises(tk.TclError):
        tk.Label(app, image=img).pack()
        app.update_idletasks()


def test_the_rod_calculations_report_passes_its_own_window(two_roots):
    """The call site, not just the helper: the report builds a Toplevel and
    must hand it to render_math, or the fix is academic."""
    import re
    src = (Path(__file__).resolve().parents[1]
           / 'apps' / 'truss' / 'truss_app.py').read_text(encoding='utf-8')
    m = re.search(r'render_math\((.*?)\)', src, re.S)
    assert m, 'the Rod Calculations report no longer calls render_math'
    assert 'master=' in m.group(1), (
        'render_math must be given the window that will show the image')
