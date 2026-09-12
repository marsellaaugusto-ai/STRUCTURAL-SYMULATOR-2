"""App-level plate tests: creating panels from a selection, the delete
remap, and the Excel round trip.

The delete remap is the one that matters most. Node identity in this tab is
the LIST INDEX, and deleting a node shifts every index above it down by one
(Cable Web moved to stable ids to avoid exactly this -- MANIFESTO sec 1.3 --
the Truss tab did not). A plate that is not remapped in the same pass goes on
referring to the same NUMBERS while those numbers now mean different nodes:
no crash, no error, just a plate quietly attached to the wrong bay. Nothing
but a test like this one catches that.
"""
import gc
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import tkinter as tk
except Exception:
    tk = None

import pytest

from common import PX_PER_M
from apps.truss import truss_plates


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
def app():
    from tkinter import messagebox, filedialog
    for name in ('showerror', 'showwarning', 'showinfo'):
        setattr(messagebox, name, lambda *a, **k: None)
    filedialog.askopenfilename = lambda *a, **k: ''
    filedialog.asksaveasfilename = lambda *a, **k: ''

    from apps.truss.truss_app import TrussApp
    root = _new_root_or_skip()
    root.geometry('1400x900+0+0')
    host = tk.Frame(root)
    host.pack(fill='both', expand=True)
    a = TrussApp(host)
    root.update_idletasks()
    root.update()
    try:
        yield a, root
    finally:
        try:
            root.destroy()
        finally:
            gc.collect()


def vierendeel_into(a):
    """One rigid bay: nodes 0..3 counter-clockwise, rods 0..3 around it."""
    def m(x, y):
        return [x * PX_PER_M, -y * PX_PER_M]
    a.nodes = [m(0, 0), m(3, 0), m(3, 2), m(0, 2)]
    a.rods = [{'a': x, 'b': y, 'E': 200.0, 'A': 60.0, 'I': 8000.0,
               'conn': 'rigid', 'profile': 'Default'}
              for x, y in ((0, 1), (1, 2), (2, 3), (3, 0))]
    a.supports = [{'node': 0, 'type': 'fixed'}, {'node': 1, 'type': 'fixed'}]
    a.loads = [{'node': 2, 'fx': 40.0, 'fy': 0.0}]
    a.plates = []


# ── loop detection ───────────────────────────────────────────────────────────

def test_closed_loop_from_rods_accepts_a_bay_and_refuses_everything_else():
    rods = [{'a': 0, 'b': 1}, {'a': 1, 'b': 2}, {'a': 2, 'b': 3}, {'a': 3, 'b': 0},
            {'a': 0, 'b': 2}]                       # a diagonal
    loop, why = truss_plates.closed_loop_from_rods(rods, {0, 1, 2, 3})
    assert why is None
    assert set(loop) == {0, 1, 2, 3} and len(loop) == 4

    loop, why = truss_plates.closed_loop_from_rods(rods, {0, 1, 4})
    assert why is None and set(loop) == {0, 1, 2}   # the triangle 0-1-2

    # not a loop: an open chain
    loop, why = truss_plates.closed_loop_from_rods(rods, {0, 1, 2})
    assert loop is None and 'loop' in why

    # wrong count
    loop, why = truss_plates.closed_loop_from_rods(rods, {0, 1})
    assert loop is None and '3 or 4' in why

    # branching: three rods meeting one node
    branchy = [{'a': 0, 'b': 1}, {'a': 0, 'b': 2}, {'a': 0, 'b': 3}]
    loop, why = truss_plates.closed_loop_from_rods(branchy, {0, 1, 2})
    assert loop is None and ('branch' in why or 'loop' in why)


# ── creation ─────────────────────────────────────────────────────────────────

def test_add_panel_from_selected_rods(app):
    a, root = app
    vierendeel_into(a)
    a.selected_rods = {0, 1, 2, 3}
    a._add_panel()
    assert len(a.plates) == 1
    assert a.plates[0]['kind'] == 'panel'
    assert set(a.plates[0]['nodes']) == {0, 1, 2, 3}
    # adding the same bay twice is refused
    a._add_panel()
    assert len(a.plates) == 1


def test_add_panel_refuses_a_selection_that_is_not_a_bay(app):
    a, root = app
    vierendeel_into(a)
    a.selected_rods = {0, 1}
    a._add_panel()
    assert a.plates == []


def test_a_gusset_does_not_invalidate_existing_results(app):
    """A gusset is an annotation. Adding one must leave the solved results in
    place -- if it cleared them the user would think it had changed something."""
    a, root = app
    vierendeel_into(a)
    a._run_analysis()
    assert a.results is not None
    before = a.results['node_res'][2]['ux']
    a.selected_nodes = {2}
    a._add_gusset()
    assert a.results is not None, 'adding a gusset wrongly cleared the results'
    assert a.results['node_res'][2]['ux'] == before
    assert a.plate_checks and a.plate_checks[0] is not None


def test_a_panel_does_invalidate_existing_results(app):
    """A panel IS a member, so results computed without it are now stale and
    must not be left on screen as if they still applied."""
    a, root = app
    vierendeel_into(a)
    a._run_analysis()
    assert a.results is not None
    a.selected_rods = {0, 1, 2, 3}
    a._add_panel()
    assert a.results is None
    assert a.diagrams is None


def test_a_panel_actually_stiffens_the_bay_through_the_app(app):
    a, root = app
    vierendeel_into(a)
    a._run_analysis()
    bare = abs(a.results['node_res'][2]['ux'])
    a.selected_rods = {0, 1, 2, 3}
    a.plate_t.set(10.0)
    a._add_panel()
    a._run_analysis()
    plated = abs(a.results['node_res'][2]['ux'])
    assert plated < bare / 2.0, (bare, plated)
    assert a.plate_checks[0]['valid']


# ── the delete remap ─────────────────────────────────────────────────────────

def test_deleting_an_unrelated_node_remaps_plate_indices(app):
    """Delete a node BELOW the plate's own indices: every index above it
    shifts down by one, and the plate must follow. If it does not, the plate
    silently spans a different set of nodes."""
    a, root = app

    def m(x, y):
        return [x * PX_PER_M, -y * PX_PER_M]
    # node 0 is a spare, unconnected to the bay; the bay is nodes 1..4
    a.nodes = [m(-5, 0), m(0, 0), m(3, 0), m(3, 2), m(0, 2)]
    a.rods = [{'a': x, 'b': y, 'E': 200.0, 'A': 60.0, 'I': 8000.0, 'conn': 'rigid'}
              for x, y in ((1, 2), (2, 3), (3, 4), (4, 1))]
    a.supports = [{'node': 1, 'type': 'fixed'}, {'node': 2, 'type': 'fixed'}]
    a.loads = [{'node': 3, 'fx': 40.0, 'fy': 0.0}]
    a.plates = [{'kind': 'panel', 'nodes': [1, 2, 3, 4], 'thickness_mm': 8.0,
                 'G_GPa': 80.0},
                {'kind': 'gusset', 'node': 3, 'thickness_mm': 10.0}]

    coords_before = [tuple(a.nodes[i]) for i in a.plates[0]['nodes']]
    gusset_xy = tuple(a.nodes[a.plates[1]['node']])

    a.selected_nodes = {0}
    a.selected_rods = set()
    a._on_delete(None)

    assert len(a.plates) == 2, 'a plate was dropped though its nodes survived'
    # the plate must still span the SAME PHYSICAL corners, not the same numbers
    coords_after = [tuple(a.nodes[i]) for i in a.plates[0]['nodes']]
    assert coords_after == coords_before, (coords_before, coords_after)
    assert tuple(a.nodes[a.plates[1]['node']]) == gusset_xy


def test_deleting_a_plates_own_node_drops_the_plate(app):
    a, root = app
    vierendeel_into(a)
    a.plates = [{'kind': 'panel', 'nodes': [0, 1, 2, 3], 'thickness_mm': 8.0,
                 'G_GPa': 80.0},
                {'kind': 'gusset', 'node': 2, 'thickness_mm': 10.0}]
    a.selected_nodes = {2}
    a.selected_rods = set()
    a._on_delete(None)
    assert a.plates == [], 'a plate outlived the node it was attached to'


def test_deleting_a_bounding_rod_drops_the_panel(app):
    """A panel whose bay no longer has all four sides is not that panel any
    more -- it must not be left spanning open air."""
    a, root = app
    vierendeel_into(a)
    a.plates = [{'kind': 'panel', 'nodes': [0, 1, 2, 3], 'thickness_mm': 8.0,
                 'G_GPa': 80.0}]
    a.selected_rods = {1}
    a.selected_nodes = set()
    a._on_delete(None)
    assert a.plates == []


def test_every_surviving_plate_still_solves_after_a_delete(app):
    """The real risk of a bad remap is a model that still analyses and is
    quietly wrong, so end the delete tests by actually solving."""
    a, root = app

    def m(x, y):
        return [x * PX_PER_M, -y * PX_PER_M]
    # Node 0 is a spare that sits BELOW the plate's indices, so deleting it
    # shifts every one of them. It carries a pin support because a node with
    # no rods and no support is a floating mechanism and the solve would
    # (correctly) refuse the model for a reason unrelated to this test.
    a.nodes = [m(-5, 0), m(0, 0), m(3, 0), m(3, 2), m(0, 2)]
    a.rods = [{'a': x, 'b': y, 'E': 200.0, 'A': 60.0, 'I': 8000.0, 'conn': 'rigid'}
              for x, y in ((1, 2), (2, 3), (3, 4), (4, 1))]
    a.supports = [{'node': 0, 'type': 'pin'},
                  {'node': 1, 'type': 'fixed'}, {'node': 2, 'type': 'fixed'}]
    a.loads = [{'node': 3, 'fx': 40.0, 'fy': 0.0}]
    a.plates = [{'kind': 'panel', 'nodes': [1, 2, 3, 4], 'thickness_mm': 10.0,
                 'G_GPa': 80.0}]
    a._run_analysis()
    assert a.results is not None, 'the reference model did not solve'
    q_before = a.results['plate_res'][0]['q']

    a.selected_nodes = {0}
    a.selected_rods = set()
    a._on_delete(None)
    a._run_analysis()
    assert a.results is not None
    q_after = a.results['plate_res'][0]['q']
    assert q_after == pytest.approx(q_before, rel=1e-9), (q_before, q_after)


# ── Excel round trip ─────────────────────────────────────────────────────────

def test_excel_round_trip_preserves_plates(app):
    from common import _ensure_openpyxl
    if not _ensure_openpyxl():
        pytest.skip('openpyxl unavailable')
    from apps.truss.truss_reports import export_excel, import_excel_model

    a, root = app
    vierendeel_into(a)
    a.plates = [{'kind': 'panel', 'nodes': [0, 1, 2, 3], 'thickness_mm': 9.0,
                 'G_GPa': 79.0, 'E_GPa': 200.0, 'nu': 0.3,
                 'Fy': 355.0, 'Fexx': 550.0, 'weld_lines': 2},
                {'kind': 'gusset', 'node': 2, 'thickness_mm': 12.0,
                 'Fy': 235.0, 'Fu': 410.0, 'Fexx': 480.0, 'weld_lines': 2,
                 'landing_m': 0.25, 'conn_type': 'bolted', 'bolt_d_mm': 20.0,
                 'bolt_rows': 3, 'bolt_cols': 2, 'pitch_mm': 70.0,
                 'gauge_mm': 65.0, 'end_mm': 45.0, 'edge_mm': 38.0}]
    a._run_analysis()

    fd, path = tempfile.mkstemp(suffix='.xlsx')
    os.close(fd)
    try:
        export_excel(a.nodes, a.rods, a.loads, a.supports, a.results, path,
                     profiles=a.profiles, plates=a.plates)
        _n, _r, _l, _s, _p, plates, _g = import_excel_model(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    assert len(plates) == 2
    pan = [p for p in plates if p['kind'] == 'panel'][0]
    gus = [p for p in plates if p['kind'] == 'gusset'][0]
    assert pan['nodes'] == [0, 1, 2, 3]
    assert pan['thickness_mm'] == pytest.approx(9.0)
    assert pan['G_GPa'] == pytest.approx(79.0)
    assert pan['Fy'] == pytest.approx(355.0)
    assert pan['Fexx'] == pytest.approx(550.0)
    assert gus['node'] == 2
    assert gus['thickness_mm'] == pytest.approx(12.0)
    assert gus['landing_m'] == pytest.approx(0.25)
    # the connection detail must survive too -- without it block shear and
    # gusset buckling cannot be recomputed after an import, and the reopened
    # model would silently fall back to the welded defaults
    assert gus['conn_type'] == 'bolted'
    assert gus['bolt_rows'] == 3 and gus['bolt_cols'] == 2
    assert gus['bolt_d_mm'] == pytest.approx(20.0)
    assert gus['pitch_mm'] == pytest.approx(70.0)
    assert gus['gauge_mm'] == pytest.approx(65.0)
    assert gus['end_mm'] == pytest.approx(45.0)
    assert gus['edge_mm'] == pytest.approx(38.0)
    assert gus['Fu'] == pytest.approx(410.0)


def test_a_model_with_no_plates_round_trips_unchanged(app):
    """A workbook written before plates existed has no [PLATES] section, and
    must import as a plateless model rather than failing."""
    from common import _ensure_openpyxl
    if not _ensure_openpyxl():
        pytest.skip('openpyxl unavailable')
    from apps.truss.truss_reports import export_excel, import_excel_model

    a, root = app
    vierendeel_into(a)
    a._run_analysis()
    fd, path = tempfile.mkstemp(suffix='.xlsx')
    os.close(fd)
    try:
        export_excel(a.nodes, a.rods, a.loads, a.supports, a.results, path,
                     profiles=a.profiles)
        _n, _r, _l, _s, _p, plates, _g = import_excel_model(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    assert plates == []


# ── Node Force Vectors report ────────────────────────────────────────────────

def test_node_force_vectors_report_balances_at_every_node(app):
    """The report's per-node sigma line is its own equilibrium check, so it
    has to actually close -- at free joints AND at fixed supports, where the
    reaction moment is part of the balance.

    Two things this pins, both of which were wrong at some point:
      * the report used the AXIAL-only vectors, so at a rigid joint the
        members' shear was missing and the sum could not close;
      * reactions[..]['m'] is in the solver's canvas frame (y DOWN) while the
        report works y-UP, so adding it unconverted left sigma-M = 2*m at
        every fixed support.
    """
    import re
    import tkinter as tk
    tk.Toplevel.wait_window = lambda self, w=None: None

    a, root = app
    vierendeel_into(a)
    a.plates = [{'kind': 'panel', 'nodes': [0, 1, 2, 3], 'thickness_mm': 8.0,
                 'G_GPa': 80.0}]
    a._run_analysis()
    assert a.results is not None
    a._show_node_vectors_report()
    root.update_idletasks()
    root.update()

    texts = []

    def walk(w):
        if isinstance(w, tk.Text):
            texts.append(w)
        for c in w.winfo_children():
            walk(c)
    walk(root)

    checked = 0
    for t in texts:
        body = t.get('1.0', 'end')
        mf = re.search(r'\u03a3Fx=\s*([-+0-9.]+)\s+\u03a3Fy=\s*([-+0-9.]+)', body)
        mm = re.search(r'\u03a3M\s*=\s*([-+0-9.]+)', body)
        if not (mf and mm):
            continue
        checked += 1
        assert abs(float(mf.group(1))) < 1e-2, body
        assert abs(float(mf.group(2))) < 1e-2, body
        assert abs(float(mm.group(1))) < 1e-2, body
    assert checked == len(a.nodes), (checked, len(a.nodes))

    joined = '\n'.join(t.get('1.0', 'end') for t in texts)
    assert '(axial)' in joined, 'axial N is no longer reported separately'
    assert 'Panel' in joined, 'the shear panel does not appear at its joints'
