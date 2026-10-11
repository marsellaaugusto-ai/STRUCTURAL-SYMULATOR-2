"""The Truss tab's teaching aids (apps/truss/truss_app_learn.py): Simple /
Advanced, the stability line, the mechanism drawn moving, the support
sandbox, Live, zero-force rods, labels that never overlap, folded hints."""
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

from common import PX_PER_M


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
    pytest.skip(f'no display available ({last})')


@pytest.fixture()
def app():
    from tkinter import messagebox
    for name in ('showerror', 'showwarning', 'showinfo'):
        setattr(messagebox, name, lambda *a, **k: None)
    from apps.truss.truss_app import TrussApp
    root = _new_root_or_skip()
    root.geometry('1440x900+0+0')
    host = tk.Frame(root)
    host.pack(fill='both', expand=True)
    a = TrussApp(host)
    _settle(root)
    try:
        yield a
    finally:
        try:
            a._stop_mechanism()
            root.destroy()
        finally:
            gc.collect()


def _settle(root, n=10, pause=0.02):
    for _ in range(n):
        root.update_idletasks()
        root.update()
        time.sleep(pause)


def _bboxes(c, tag):
    return [c.bbox(i) for i in c.find_withtag(tag)
            if c.itemcget(i, 'fill') != 'white']


def _slot(frame):
    """(parent, index) -- where a section sits among its own siblings.

    Its own siblings, because the panel is a mode rail: the Advanced
    sections are spread across the Build, Load and Section frames now and
    share no single pack order to be in. What has to hold is that each one
    goes back EXACTLY where it was, which is this pair.
    """
    parent = frame.master
    return str(parent), parent.pack_slaves().index(frame)


def test_the_tab_opens_simple_and_advanced_restores_every_section_in_place(app):
    order = [f for f, _ in app._adv_sections]
    assert not app.advanced.get()
    assert app.cad_bar.winfo_manager() == ''
    assert all(f.winfo_manager() == '' for f in order)

    app.advanced.set(True)
    app._apply_mode()
    assert app.cad_bar.winfo_manager() == 'pack'
    assert all(f.winfo_manager() == 'pack' for f in order)
    where = [_slot(f) for f in order]

    # Analyze stays the first thing in its own frame: Simple mode hiding
    # the sections above it must not reshuffle what is left.
    assert app.analyze_btn.master.pack_slaves()[0] is app.analyze_btn

    app.advanced.set(False)
    app._apply_mode()
    assert all(f.winfo_manager() == '' for f in order)

    # ...and back, to exactly the same slots. This is the round trip the
    # old flat-panel version of this test could only check one way.
    app.advanced.set(True)
    app._apply_mode()
    assert [_slot(f) for f in order] == where, (
        'Advanced must put every section back where it was, not merely '
        'back on screen')


def test_simple_mode_still_offers_span_loads_once_a_rod_is_rigid(app):
    app._load_example_vierendeel()
    app._draw()
    assert app.dload_frame.winfo_manager() == 'pack'
    assert app.guide_frame.winfo_manager() == ''


def test_the_stability_line_follows_the_model(app):
    app._load_example()
    app._draw()
    assert app.stability_var.get().startswith('Statically determinate')
    del app.rods[1]
    app.results = None
    app._draw()
    assert app.stability_var.get().startswith('A mechanism')
    app._load_example_vierendeel()
    app._draw()
    assert 'indeterminate to degree 12' in app.stability_var.get()


def test_a_mechanism_is_drawn_moving_and_stops_when_the_model_changes(app):
    app._load_example()
    removed = app.rods.pop(1)
    app.results = None
    app._run_analysis()
    _settle(app.root, 6, 0.05)
    assert app._mech is not None and app._mech['mm']['kind'] == 'internal'
    assert app.zc.canvas.find_withtag('mech')
    assert 'add a diagonal' in app.status_var.get()
    app.rods.insert(1, removed)
    app._draw()
    _settle(app.root, 3, 0.05)
    assert app._mech is None and not app.zc.canvas.find_withtag('mech')


class _Click:
    def __init__(self, app, node):
        self.x, self.y = app.zc.w2s(*app.nodes[node])


def test_a_support_can_be_switched_off_and_back_on(app):
    app._load_example()
    app._run_analysis()
    roller = [s['node'] for s in app.supports if s['type'] == 'rollerX'][0]
    app._on_support_right_click(_Click(app, roller))
    assert roller in app.disabled_supports
    assert app.results is None                 # one pin: it turns
    assert 'Analysis failed' in app.status_var.get()
    assert len(app.supports) == 2              # nothing was deleted
    app._on_support_right_click(_Click(app, roller))
    assert not app.disabled_supports
    assert app.results is not None


def test_live_resolves_after_an_edit(app):
    app._load_example()
    app.live_var.set(True)
    app._on_live_toggle()
    _settle(app.root, 30, 0.02)
    assert app.results is not None
    app.loads[0]['fy'] *= 2
    app.results = None
    app._draw()
    _settle(app.root, 30, 0.02)
    assert app.results is not None
    assert app.status_var.get().startswith('Live:')


def _zero_force_model(app):
    P = lambda x, y: (x * PX_PER_M, y * PX_PER_M)
    app._clear_all()
    app.nodes[:] = [P(0, 0), P(4, 0), P(2, -2), P(2, 0)]
    rod = app._new_rod
    app.rods[:] = [rod(0, 3), rod(3, 1), rod(0, 2), rod(2, 1), rod(3, 2)]
    app.supports[:] = [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'rollerX'}]
    app.loads[:] = [{'node': 2, 'fx': 0.0, 'fy': 10.0}]


def test_zero_force_rods_are_dashed_counted_and_can_be_hidden(app):
    _zero_force_model(app)
    app._run_analysis()
    assert abs(app.results['rod_res'][4]['force']) < 1e-6
    assert '1 carry no force' in app.status_var.get()
    labels = {app.zc.canvas.itemcget(i, 'text')
              for i in app.zc.canvas.find_withtag('rod_label')}
    assert any(t.startswith('4:') for t in labels)
    app.hide_zero.set(True)
    app._draw()
    labels = {app.zc.canvas.itemcget(i, 'text')
              for i in app.zc.canvas.find_withtag('rod_label')}
    assert not any(t.startswith('4:') for t in labels)


def test_no_two_numbers_are_drawn_on_top_of_each_other(app):
    app._load_example_vierendeel()
    app._run_analysis()
    c = app.zc.canvas
    boxes = _bboxes(c, 'rod_label') + _bboxes(c, 'node_label')
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert not (a[0] < b[2] and b[0] < a[2] and
                        a[1] < b[3] and b[1] < a[3]), (a, b)
    if app._labels_hidden:
        assert c.find_withtag('labels_hidden')


def _mode_of(app, widget):
    """Which mode frame a panel widget lives under, or None."""
    for key, frame in getattr(app, '_mode_frames', {}).items():
        w = widget
        while w is not None:
            if w is frame:
                return key
            w = getattr(w, 'master', None)
    return None


def test_long_grey_hints_fold_and_unfold(app):
    folded = []

    def walk(w):
        for ch in w.winfo_children():
            if getattr(ch, '_hint_full', None):
                folded.append(ch)
            walk(ch)
    walk(app.panel_outer.interior)
    assert folded, 'no long hint was folded'
    assert all(l.cget('text').endswith('more…') for l in folded)

    # The panel is a mode rail now, and <Button-1> on an unmapped widget
    # does nothing: a hint has to be BROUGHT UP before it can be clicked.
    # Advanced, because several of these sections are Advanced-only, then
    # the hint's own mode.
    app.advanced.set(True)
    app._apply_mode()
    lbl = None
    for cand in folded:
        mode = _mode_of(app, cand)
        if mode is not None:
            app.rail.select(mode)
        app.panel_outer.update_idletasks()
        app.panel_outer.update()
        if cand.winfo_ismapped():
            lbl = cand
            break
    assert lbl is not None, (
        'not one of the %d folded hints could be brought on screen -- a '
        'hint nobody can click is a hint nobody can read' % len(folded))
    lbl.event_generate('<Button-1>')
    assert lbl.cget('text').startswith(lbl._hint_full)
    lbl.event_generate('<Button-1>')
    assert lbl.cget('text').endswith('more…'), 'it must fold back, too'


def test_a_family_with_a_steel_section_gets_checked_and_coloured(app):
    app._load_example()
    app._set_family_section('Default', 'CHS 60.3x3.6', 'F24 (CIRSOC) / A36')
    app._run_analysis()
    # the example's diagonals are their own family, not given a section yet
    diag = [i for i, r in enumerate(app.rods) if r['profile'] == 'Diagonal']
    assert diag and all(not app.rod_checks[i]['checked'] for i in diag)
    assert 'Steel section' in app.rod_checks[diag[0]]['note']
    app._set_family_section('Diagonal', 'CHS 48.3x3.2', 'F24 (CIRSOC) / A36')
    app._run_analysis()
    assert app.rod_checks and all(c['checked'] for c in app.rod_checks)
    assert 'Most used rod' in app.res_var.get()
    assert 'Max deflection' in app.res_var.get()
    text = app.rod_res_text.get('1.0', 'end')
    assert 'u=' in text
    app.color_util.set(True)
    app._draw()
    text = app._explain_rod()
    assert 'CIRSOC' in text or 'utilisation' in text
    app._undo()                     # the diagonals' section came off...
    app._undo()                     # ...and then the chords'
    assert 'Fy' not in app.profiles['Default']


def test_self_weight_adds_the_rods_weight_to_the_reactions(app):
    app._load_example()
    app._run_analysis()
    before = sum(r.get('ry', 0.0) for r in app.results['reactions'].values())
    app.self_weight.set(True)
    app._on_design_option()
    after = sum(r.get('ry', 0.0) for r in app.results['reactions'].values())
    from apps.truss import truss_design as td
    w = sum(td.self_weight_loads(app.nodes, app.rods).values())
    assert abs(abs(after - before) - w) < 1e-6 * max(1.0, w)
    assert not any(ld.get('fy', 0) != ld.get('fy', 0) for ld in app.loads)
