"""The Beam diagram pane stays readable as it narrows (R-13, née B-8).

Each band draws a caption at its top left, a `max ±…` readout at its top
right, and a label at each peak the solver found. All three were placed from
their own geometry with no regard for each other, so they ran through one
another as soon as the window was not wide: measured on the live canvas,
1 overlapping pair at 1500 px and 4 at 700 px, the worst being the moment
caption straight through `max ±117.19`.

The fix is the one the Arch tab already uses for the same problem (finding
A-5): fit the caption to the space actually available, dropping the
explanatory half before the name and the name before the symbol, so the
quantity is never unidentifiable; reserve the readout's own width on the
right; and place a peak label on whichever side of its point is free.

These tests measure real canvas items, because that is the only thing that
can answer the question -- `bbox` after the paint, exactly as the finding was
raised (MANIFESTO §2).
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

tk = pytest.importorskip('tkinter')

import units
import apps.beam.beam_app as beam_app
from apps.beam.beam_app import BeamApp

# The widths the finding was measured at, plus two narrower ones that reach
# the last two fallbacks: at 420 px the caption is down to its symbol, and at
# 340 px there is no room for symbol AND readout side by side, so the readout
# drops to the band's bottom right (which then leaves the caption enough width
# to come back to its full name).
WIDTHS = (1500, 1200, 900, 700, 420, 340)


@pytest.fixture
def beam(monkeypatch):
    units.set_current('cirsoc')
    try:
        root = tk.Tk()
    except tk.TclError:                       # pragma: no cover - headless CI
        pytest.skip('no display')
    monkeypatch.setattr(beam_app, 'messagebox',
                        type('B', (), {'showerror': staticmethod(lambda *a: None),
                                       'showwarning': staticmethod(lambda *a: None),
                                       'showinfo': staticmethod(lambda *a: None)}))
    root.geometry('1500x900')
    app = BeamApp(root)
    app.pack(fill='both', expand=True)
    root.update()
    # The model the collisions were measured on: a 10 m span with a UDL and an
    # off-centre point load, so every band has a peak away from midspan.
    app.length = 10.0
    app.len_var.set(10.0)
    app.supports = [{'x': 0.0, 'type': 'pin'}, {'x': 10.0, 'type': 'roller'}]
    app.dloads = [{'x1': 0.0, 'x2': 10.0, 'w1': 6.0, 'w2': 6.0}]
    app.point_loads = [{'x': 7.0, 'P': 25.0}]
    app._refresh_tables()
    app._analyze()
    root.update()
    try:
        yield app, root
    finally:
        units.set_current('cirsoc')
        try:
            root.destroy()
        except Exception:
            pass


def _texts(canvas):
    return [i for i in canvas.find_all() if canvas.type(i) == 'text']


def _collisions(canvas):
    """Every overlapping pair of text items, with the overlap in pixels."""
    items = _texts(canvas)
    out = []
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            x0, y0, x1, y1 = canvas.bbox(items[a])
            X0, Y0, X1, Y1 = canvas.bbox(items[b])
            if x0 < X1 and X0 < x1 and y0 < Y1 and Y0 < y1:
                out.append((canvas.itemcget(items[a], 'text'),
                            canvas.itemcget(items[b], 'text'),
                            min(x1, X1) - max(x0, X0)))
    return out


def _at_width(app, root, width):
    root.geometry(f'{width}x900')
    root.update()
    app._draw_diagrams()
    root.update()
    return app.diag_canvas


@pytest.mark.parametrize('width', WIDTHS)
def test_no_two_labels_overlap_at_any_width(beam, width):
    app, root = beam
    canvas = _at_width(app, root, width)
    assert _collisions(canvas) == [], (width, _collisions(canvas))


@pytest.mark.parametrize('width', WIDTHS)
def test_every_band_still_says_which_quantity_it_is(beam, width):
    """A caption elided down to nothing would be worse than an overlapping
    one. The unit is the last thing to go, and it never does."""
    app, root = beam
    canvas = _at_width(app, root, width)
    texts = [canvas.itemcget(i, 'text') for i in _texts(canvas)]
    for want in (units.label('force'), units.label('moment'),
                 units.label('deflection')):
        assert any(want in t for t in texts), (width, want, texts)


@pytest.mark.parametrize('width', WIDTHS)
def test_the_max_readout_survives_at_every_width(beam, width):
    app, root = beam
    canvas = _at_width(app, root, width)
    texts = [canvas.itemcget(i, 'text') for i in _texts(canvas)]
    assert sum(1 for t in texts if t.startswith('max ')) == 3, texts


@pytest.mark.parametrize('width', WIDTHS)
def test_no_label_escapes_its_own_canvas(beam, width):
    app, root = beam
    canvas = _at_width(app, root, width)
    cw = canvas.winfo_width()
    ch = canvas.winfo_height()
    for i in _texts(canvas):
        x0, y0, x1, y1 = canvas.bbox(i)
        text = canvas.itemcget(i, 'text')
        assert x0 >= -1 and x1 <= cw + 1, (width, text, (x0, x1), cw)
        assert y0 >= -1 and y1 <= ch + 1, (width, text, (y0, y1), ch)


def test_the_peak_markers_are_still_drawn(beam):
    """Narrowing the pane must not quietly drop the annotations it cannot
    place -- an invisible failure is what this finding was about."""
    app, root = beam
    for width in WIDTHS:
        canvas = _at_width(app, root, width)
        dots = [i for i in canvas.find_all() if canvas.type(i) == 'oval']
        labels = [canvas.itemcget(i, 'text') for i in _texts(canvas)
                  if canvas.itemcget(i, 'text').startswith('x=')]
        assert dots, width
        assert len(labels) == len(dots), (width, labels, len(dots))


def test_the_reversed_moment_caption_is_fitted_too(beam):
    """The checkbox swaps in a longer caption than the default one."""
    app, root = beam
    app.reverse_bmd_var.set(True)
    for width in WIDTHS:
        canvas = _at_width(app, root, width)
        assert _collisions(canvas) == [], (width, _collisions(canvas))


@pytest.mark.parametrize('key', ['aisc', 'eurocode'])
def test_it_holds_in_other_conventions(beam, key):
    """Unit labels differ in width -- 'kip·ft' is not 'kN·m'."""
    app, root = beam
    units.set_current(key)
    root.update()
    for width in WIDTHS:
        canvas = _at_width(app, root, width)
        assert _collisions(canvas) == [], (key, width, _collisions(canvas))


# ------------------------------------------------- the shared helper

def test_fit_caption_drops_the_explanation_before_the_name():
    from tkinter import font as tkfont
    from common import fit_caption

    try:
        root = tk.Tk()
    except tk.TclError:                       # pragma: no cover
        pytest.skip('no display')
    try:
        f = tkfont.Font(root=root, font=('Helvetica', 8, 'bold'))
        full = 'MOMENT M (kN·m) — sagging (+) plotted UP, hogging (−) down'
        name = 'MOMENT M (kN·m)'
        symbol = 'M (kN·m)'

        text, width = fit_caption(full, f.measure(full) + 10, f, symbol)
        assert text == full and width == f.measure(full)

        text, _ = fit_caption(full, f.measure(name) + 2, f, symbol)
        assert text == name

        text, _ = fit_caption(full, f.measure(symbol) + 2, f, symbol)
        assert text == symbol

        # Nothing fits: the shortest form is still returned, because a band
        # with no caption at all cannot be read.
        text, _ = fit_caption(full, 1, f, symbol)
        assert text == symbol

        # No fallback offered: it stops at the name.
        text, _ = fit_caption(full, 1, f)
        assert text == name
    finally:
        root.destroy()


def test_the_readout_moves_below_when_it_cannot_sit_beside_the_caption(beam):
    """The last fallback: a band too narrow for both puts the readout at its
    own bottom right rather than overprinting the caption."""
    app, root = beam
    wide = _at_width(app, root, 1500)
    tops = [wide.bbox(i)[1] for i in _texts(wide)
            if wide.itemcget(i, 'text').startswith('max ')]
    narrow = _at_width(app, root, 340)
    lows = [narrow.bbox(i)[1] for i in _texts(narrow)
            if narrow.itemcget(i, 'text').startswith('max ')]
    assert len(tops) == len(lows) == 3, (tops, lows)
    # The decision is per band -- each one compares its OWN caption symbol
    # against its own width -- so at 340 px it is the moment band, whose
    # symbol is the widest, that has to move. Asserting all three would be
    # asserting the wrong thing.
    moved = [lo > hi for lo, hi in zip(lows, tops)]
    assert any(moved), (tops, lows)
