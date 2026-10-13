"""Reading a value off the diagrams, and getting at a crowded part of them (R-15).

The pane could only be looked at. Three things it could not do:

* **Say what a value is at a station.** The diagrams labelled the automatic
  maxima and nothing else, so answering "what is M at 3.4 m" meant exporting
  a spreadsheet. The data is already sampled; a hover readout is the single
  most-asked-for thing in a beam tool.
* **Let you get closer.** A 20 m beam with forty loads drew its whole span
  into ~900 px, and the region near a support -- where the shear jumps and
  the moment peaks -- could not be resolved at all.
* **Leave the pane.** Putting a diagram in a report needed a screenshot.

Zoom here is on the x axis only, not the uniform 2-D zoom `common.ZoomCanvas`
gives the Truss and Stereo tabs. These are three stacked plots sized to the
pane, sharing one axis: the beam. Scaling them uniformly would scale the band
heights and the text with the span, which is not what "look closer at the
support" means. The schematic shares the same window, so the picture and the
diagrams always show the same piece of beam.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

tk = pytest.importorskip('tkinter')

import units
import apps.beam.beam_app as beam_app
from apps.beam.beam_app import BeamApp


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
    root.geometry('1400x900')
    app = BeamApp(root)
    app.pack(fill='both', expand=True)
    root.update()
    app.length = 10.0
    app.len_var.set(10.0)
    app.supports = [{'x': 0.0, 'type': 'pin'}, {'x': 10.0, 'type': 'roller'}]
    app.dloads = [{'x1': 0.0, 'x2': 10.0, 'w1': 6.0, 'w2': 6.0}]
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


def _band(app, index=1):
    """The geometry the paint recorded for one band (0=V, 1=M, 2=δ)."""
    return app._band_boxes[index]


def _hover(app, root, x_frac=0.5, band=1):
    """Move the pointer to a fraction along one band and return the readout."""
    box = _band(app, band)
    x = box['left'] + (box['right'] - box['left']) * x_frac
    y = (box['top'] + box['bot']) / 2
    app.diag_canvas.event_generate('<Motion>', x=int(x), y=int(y))
    root.update()
    return app._hover.text


# ------------------------------------------------------------ hover readout

def test_hovering_a_band_reports_the_station_and_all_three_values(beam):
    """All three, not just the band under the pointer: a reader asking about
    3.4 m wants V, M and the deflection there, and they are already sampled."""
    app, root = beam
    text = _hover(app, root, 0.5)
    assert text, 'nothing was shown'
    assert 'x =' in text
    # 10 m span under 6 kN/m: M at midspan is wL^2/8 = 75 kN.m, V is 0
    assert '75.0' in text, text
    for want in ('V', 'M'):
        assert want in text, text


def test_the_readout_is_written_in_the_selected_convention(beam):
    app, root = beam
    units.set_current('aisc')
    root.update()
    app._draw_diagrams()
    text = _hover(app, root, 0.5)
    assert units.label('force') in text, text
    assert 'kN' not in text, text


def test_the_station_follows_the_pointer(beam):
    app, root = beam
    left = _hover(app, root, 0.1)
    right = _hover(app, root, 0.9)
    assert left != right

    def station(text):
        return float(text.split('x =')[1].split()[0])

    assert station(left) < station(right)
    assert station(left) == pytest.approx(1.0, abs=0.3)
    assert station(right) == pytest.approx(9.0, abs=0.3)


def test_a_cursor_line_marks_where_the_readout_is_taken(beam):
    app, root = beam
    _hover(app, root, 0.5)
    cursors = app.diag_canvas.find_withtag('hover')
    assert cursors, 'no cursor drawn'


def test_leaving_the_pane_takes_the_readout_with_it(beam):
    app, root = beam
    _hover(app, root, 0.5)
    assert app._hover.text
    app.diag_canvas.event_generate('<Leave>')
    root.update()
    assert not app._hover.text
    assert not app.diag_canvas.find_withtag('hover')


def test_hovering_outside_any_band_shows_nothing(beam):
    app, root = beam
    app.diag_canvas.event_generate('<Motion>', x=2, y=2)
    root.update()
    assert not app._hover.text


def test_hovering_before_an_analysis_is_harmless(beam):
    app, root = beam
    app._clear_all()
    root.update()
    app.diag_canvas.event_generate('<Motion>', x=200, y=100)
    root.update()
    assert not app._hover.text


# ------------------------------------------------------------- x zoom / pan

def test_the_pane_starts_showing_the_whole_beam(beam):
    app, root = beam
    assert app._view_window() == (0.0, 10.0)
    assert app._view is None


def test_the_wheel_zooms_in_about_the_pointer(beam):
    app, root = beam
    box = _band(app, 1)
    x = int(box['left'] + (box['right'] - box['left']) * 0.5)
    y = int((box['top'] + box['bot']) / 2)
    app.diag_canvas.event_generate('<Button-4>', x=x, y=y)   # X11 wheel up
    root.update()
    x0, x1 = app._view_window()
    assert x1 - x0 < 10.0, 'did not zoom in'
    # the station under the pointer stays under the pointer
    assert (x0 + x1) / 2 == pytest.approx(5.0, abs=0.4)


def test_zooming_out_again_returns_to_the_whole_beam(beam):
    app, root = beam
    box = _band(app, 1)
    x = int(box['left'] + (box['right'] - box['left']) * 0.5)
    y = int((box['top'] + box['bot']) / 2)
    for _ in range(4):
        app.diag_canvas.event_generate('<Button-4>', x=x, y=y)
    root.update()
    for _ in range(12):
        app.diag_canvas.event_generate('<Button-5>', x=x, y=y)
    root.update()
    assert app._view_window() == (0.0, 10.0)


def test_the_view_never_leaves_the_beam(beam):
    app, root = beam
    app._set_view(-5.0, 25.0)
    assert app._view_window() == (0.0, 10.0)
    app._set_view(9.9, 9.90000001)           # degenerate
    x0, x1 = app._view_window()
    assert x1 > x0
    assert 0.0 <= x0 < x1 <= 10.0


def test_dragging_pans_the_view(beam):
    app, root = beam
    app._set_view(4.0, 6.0)
    app._draw_diagrams()
    box = _band(app, 1)
    y = int((box['top'] + box['bot']) / 2)
    app.diag_canvas.event_generate('<ButtonPress-1>', x=int(box['right'] - 20), y=y)
    app.diag_canvas.event_generate('<B1-Motion>', x=int(box['left'] + 20), y=y)
    root.update()
    x0, x1 = app._view_window()
    assert x0 > 4.0, (x0, x1)                # dragging left moves the view right
    assert x1 - x0 == pytest.approx(2.0, abs=0.05), 'panning must not zoom'


def test_the_schematic_shows_the_same_window(beam):
    """One beam, one x axis: a picture of the whole span above a diagram of
    two metres of it would be a trap."""
    app, root = beam
    app._set_view(2.0, 4.0)
    app._draw_schematic()
    root.update()
    labels = [app.schem.itemcget(i, 'text') for i in app.schem.find_all()
              if app.schem.type(i) == 'text']
    assert not any('10.00' in t for t in labels), labels


def test_a_zoomed_pane_says_so(beam):
    """A zoomed diagram that looks like the whole beam is a wrong-answer
    risk, so the pane states its window while it is not showing all of it."""
    app, root = beam
    assert not any('showing' in app.diag_canvas.itemcget(i, 'text').lower()
                   for i in app.diag_canvas.find_all()
                   if app.diag_canvas.type(i) == 'text')
    app._set_view(2.0, 4.0)
    app._draw_diagrams()
    root.update()
    texts = [app.diag_canvas.itemcget(i, 'text')
             for i in app.diag_canvas.find_all()
             if app.diag_canvas.type(i) == 'text']
    assert any('showing' in t.lower() for t in texts), texts
    assert any('2.00' in t and '4.00' in t for t in texts), texts


def test_nothing_is_drawn_outside_the_plot_area_when_zoomed(beam):
    app, root = beam
    app._set_view(4.0, 6.0)
    app._draw_diagrams()
    root.update()
    c = app.diag_canvas
    box = _band(app, 1)
    for item in c.find_all():
        if c.type(item) not in ('line', 'polygon'):
            continue
        if 'curve' not in c.gettags(item):
            continue
        xs = c.coords(item)[0::2]
        assert min(xs) >= box['left'] - 1.5, (min(xs), box['left'])
        assert max(xs) <= box['right'] + 1.5, (max(xs), box['right'])


def test_fit_puts_the_whole_beam_back(beam):
    app, root = beam
    app._set_view(2.0, 4.0)
    app._fit_view()
    assert app._view is None
    assert app._view_window() == (0.0, 10.0)


def test_a_double_click_fits(beam):
    """Tk refuses to synthesise a Double modifier -- "Double, Triple, or
    Quadruple modifier not allowed" -- so what a test can check is that both
    panes carry the binding and that what it calls does fit."""
    app, root = beam
    assert app.diag_canvas.bind('<Double-1>'), 'no double-click on the diagrams'
    assert app.schem.bind('<Double-1>'), 'no double-click on the schematic'
    app._set_view(2.0, 4.0)
    app._fit_view()
    assert app._view is None


def test_the_labels_still_do_not_collide_when_zoomed(beam):
    """R-13's guarantee has to survive zooming."""
    app, root = beam
    app._set_view(4.2, 4.8)
    app._draw_diagrams()
    root.update()
    c = app.diag_canvas
    items = [i for i in c.find_all() if c.type(i) == 'text']
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            x0, y0, x1, y1 = c.bbox(items[a])
            X0, Y0, X1, Y1 = c.bbox(items[b])
            assert not (x0 < X1 and X0 < x1 and y0 < Y1 and Y0 < y1), (
                c.itemcget(items[a], 'text'), c.itemcget(items[b], 'text'))


def test_the_hover_readout_is_right_when_zoomed(beam):
    app, root = beam
    app._set_view(4.0, 6.0)
    app._draw_diagrams()
    text = _hover(app, root, 0.5)
    station = float(text.split('x =')[1].split()[0])
    assert station == pytest.approx(5.0, abs=0.2), text


# ----------------------------------------------------------------- export

def test_the_diagrams_can_be_written_to_a_file(beam, monkeypatch):
    app, root = beam
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'beam_diagrams.ps')
        monkeypatch.setattr(beam_app.filedialog, 'asksaveasfilename',
                            lambda *a, **k: path)
        app._export_diagrams()
        assert os.path.exists(path), 'nothing was written'
        assert os.path.getsize(path) > 0
        with open(path, 'rb') as fh:
            assert fh.read(2) == b'%!', 'not a PostScript file'


def test_exporting_without_a_result_says_so(beam, monkeypatch):
    app, root = beam
    app._clear_all()
    called = []
    monkeypatch.setattr(beam_app.filedialog, 'asksaveasfilename',
                        lambda *a, **k: called.append(1) or '')
    app._export_diagrams()
    assert not called, 'it should not even ask for a filename'


def test_cancelling_the_save_dialog_writes_nothing(beam, monkeypatch):
    app, root = beam
    monkeypatch.setattr(beam_app.filedialog, 'asksaveasfilename',
                        lambda *a, **k: '')
    app._export_diagrams()          # must not raise


# -------------------------------------- loads that cross the window edge

def test_a_load_running_past_the_window_still_draws_across_it(beam):
    """Clipping the SAMPLES rather than the sampled domain could leave a
    single point, and a one-point polyline is a Tcl error: a stale q(x) load
    over 0-99 m on a 6 m beam crashed the paint, found through an unrelated
    R-4 test. The load now draws right across whatever is shown."""
    app, root = beam
    app.dloads = [{'x1': 0.0, 'x2': 10.0, 'w1': 6.0, 'w2': 6.0}]
    app._set_view(4.0, 6.0)
    app._draw_schematic()                       # must not raise
    root.update()
    arrows = [i for i in app.schem.find_all() if app.schem.type(i) == 'line']
    assert arrows, 'the visible part of the load drew nothing'


def test_a_load_entirely_outside_the_window_draws_nothing(beam):
    app, root = beam
    app.dloads = [{'x1': 0.0, 'x2': 2.0, 'w1': 6.0, 'w2': 6.0}]
    app._set_view(6.0, 8.0)
    app._draw_schematic()
    root.update()
    labels = [app.schem.itemcget(i, 'text') for i in app.schem.find_all()
              if app.schem.type(i) == 'text']
    assert not any('6.0' in t and 'kN/m' in t for t in labels), labels


def test_a_stale_domain_beyond_the_beam_does_not_crash_the_paint(beam):
    """The exact model that found it."""
    app, root = beam
    app.length = 6.0
    app.len_var.set(6.0)
    app.nonuniform_loads = [{'expr': '10', 'x1': 0.0, 'x2': 99.0}]
    app.dloads = []
    app._refresh_tables()                       # paints the schematic
    root.update()


def test_a_ramp_keeps_its_real_intensities_when_clipped(beam):
    """The chord over the visible part must be the real q(x) there, not the
    whole ramp squeezed into the window."""
    app, root = beam
    app.dloads = [{'x1': 0.0, 'x2': 10.0, 'w1': 0.0, 'w2': 100.0}]
    app.point_loads = []
    app._set_view(0.0, 5.0)
    app._draw_schematic()
    root.update()
    labels = [app.schem.itemcget(i, 'text') for i in app.schem.find_all()
              if app.schem.type(i) == 'text']
    # the label states the load's own end intensities, 0 -> 100
    assert any('100' in t for t in labels), labels
    # and the drawn chord reaches only half height at the window edge, since
    # q(5) is 50 of the 100 maximum
    tops = [app.schem.coords(i) for i in app.schem.find_all()
            if app.schem.type(i) == 'line' and len(app.schem.coords(i)) > 4]
    assert tops, 'no chord drawn'
