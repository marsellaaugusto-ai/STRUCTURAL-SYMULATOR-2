"""Excel export/import round trip for every tab that offers one.

Each tab's export dialog promises "use Import to rebuild this exact model
from the file later". This file holds them to it: take a REAL model out of
the real tab (via its own `_current_state()`, after loading one of its own
examples and adding every feature the tab supports), export it, re-import it,
and compare field by field.

Driving the real app rather than hand-writing a state dict is deliberate. A
hand-written fixture encodes what the state shape was on the day the test was
written, and drifts silently; `_current_state()` is the same call the export
button makes, so a field added to the model is either round-tripped or the
test fails.

Why field by field and not just "it did not raise": an import that silently
drops a section, or reads a column into the wrong key, produces a model that
loads cleanly and analyses cleanly and is NOT the model that was saved. That
is the failure worth testing for, and only comparing values finds it.

Also asserted, because they are what make a workbook usable by a person
rather than only by the importer: every model sheet declares its units in the
column headers, and section names mean the same thing in every tab's sheet.
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

from common import _ensure_openpyxl

pytestmark = pytest.mark.skipif(not _ensure_openpyxl(),
                                reason='openpyxl unavailable')


def _tmp_xlsx():
    fd, path = tempfile.mkstemp(suffix='.xlsx')
    os.close(fd)
    return path


def _cleanup(path):
    try:
        os.unlink(path)
    except OSError:
        pass


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


TABS = {
    'beam':  ('apps.beam.beam_app', 'BeamApp'),
    'arch':  ('apps.arch.arch_app', 'ArchApp'),
    'cable': ('apps.cable.cable_app', 'CableApp'),
}


def _make(which):
    from tkinter import messagebox, filedialog
    for name in ('showerror', 'showwarning', 'showinfo'):
        setattr(messagebox, name, lambda *a, **k: None)
    filedialog.askopenfilename = lambda *a, **k: ''
    filedialog.asksaveasfilename = lambda *a, **k: ''
    mod, cls = TABS[which]
    App = getattr(__import__(mod, fromlist=[cls]), cls)
    root = _new_root_or_skip()
    root.geometry('1400x900+0+0')
    host = tk.Frame(root)
    host.pack(fill='both', expand=True)
    app = App(host)
    app.pack(fill='both', expand=True)
    root.update_idletasks()
    root.update()
    return root, app


def _compare(a, b, path='state'):
    """Deep compare two round-tripped state trees, ignoring key order and
    tolerating float representation. Returns a list of human-readable
    differences rather than raising, so a failure names every field at once."""
    diffs = []
    if isinstance(a, dict):
        if not isinstance(b, dict):
            return ['%s: %r vs %r' % (path, type(a), type(b))]
        for k in a:
            if k not in b:
                diffs.append('%s.%s missing after import' % (path, k))
            else:
                diffs += _compare(a[k], b[k], '%s.%s' % (path, k))
        return diffs
    if isinstance(a, (list, tuple)):
        if not isinstance(b, (list, tuple)):
            return ['%s: %r vs %r' % (path, type(a), type(b))]
        if len(a) != len(b):
            return ['%s: %d entries before, %d after' % (path, len(a), len(b))]
        for i, (x, y) in enumerate(zip(a, b)):
            diffs += _compare(x, y, '%s[%d]' % (path, i))
        return diffs
    if isinstance(a, float) or isinstance(b, float):
        try:
            if abs(float(a) - float(b)) > 1e-9 * max(1.0, abs(float(a))):
                diffs.append('%s: %r -> %r' % (path, a, b))
        except (TypeError, ValueError):
            diffs.append('%s: %r -> %r' % (path, a, b))
        return diffs
    if a != b:
        diffs.append('%s: %r -> %r' % (path, a, b))
    return diffs


# ── the round trips ──────────────────────────────────────────────────────────

def test_beam_model_round_trips():
    from apps.beam.beam_app import export_beam_excel, import_beam_excel
    root, app = _make('beam')
    try:
        app._load_example_overhang()
        app.point_loads.append({'x': 3.0, 'P': 25.0})
        app.moments.append({'x': 5.0, 'M': 14.0})
        app.dloads.append({'x1': 0.0, 'x2': 6.0, 'w1': 5.0, 'w2': 9.0})
        state = app._current_state()
        path = _tmp_xlsx()
        try:
            export_beam_excel(state, path)
            back = import_beam_excel(path)
        finally:
            _cleanup(path)
    finally:
        root.destroy(); gc.collect()

    for key in ('length', 'supports', 'point_loads', 'moments', 'dloads',
                'profile'):
        assert key in back, 'import dropped the whole %r section' % key
    diffs = []
    for key in ('length', 'supports', 'point_loads', 'moments', 'dloads',
                'profile'):
        diffs += _compare(state[key], back[key], key)
    assert not diffs, 'beam round trip lost data:\n  ' + '\n  '.join(diffs)


def test_arch_model_round_trips():
    from apps.arch.arch_app import export_arch_excel, import_arch_excel
    root, app = _make('arch')
    try:
        app._load_example_two_hinged()
        state = app._current_state()
        path = _tmp_xlsx()
        try:
            export_arch_excel(state, path)
            back = import_arch_excel(path)
        finally:
            _cleanup(path)
    finally:
        root.destroy(); gc.collect()

    diffs = []
    for key in state:
        if key not in back:
            diffs.append('%s missing after import' % key)
        else:
            diffs += _compare(state[key], back[key], key)
    assert not diffs, 'arch round trip lost data:\n  ' + '\n  '.join(diffs)


def test_cable_model_round_trips():
    from apps.cable.cable_app import export_cable_excel, import_cable_excel
    root, app = _make('cable')
    try:
        app._load_example_parabola()
        state = app._current_state()
        path = _tmp_xlsx()
        try:
            export_cable_excel(state, path)
            back = import_cable_excel(path)
        finally:
            _cleanup(path)
    finally:
        root.destroy(); gc.collect()

    diffs = []
    for key in state:
        if key not in back:
            diffs.append('%s missing after import' % key)
        else:
            diffs += _compare(state[key], back[key], key)
    assert not diffs, 'cable round trip lost data:\n  ' + '\n  '.join(diffs)


def test_truss_model_round_trips():
    from common import PX_PER_M
    from apps.truss.truss_reports import export_excel, import_excel_model
    from apps.truss.truss_app import analyze

    def m(x, y):
        return (x * PX_PER_M, -y * PX_PER_M)

    nodes = [m(0, 0), m(4, 0), m(4, 3), m(0, 3)]
    rods = [{'a': 0, 'b': 1, 'E': 200.0, 'A': 10.0, 'profile': 'Default'},
            {'a': 1, 'b': 2, 'E': 200.0, 'A': 12.0, 'I': 9000.0,
             'conn': 'rigid', 'udl': 7.5, 'udl_rotation_deg': 15.0,
             'profile': 'Heavy'},
            {'a': 2, 'b': 3, 'E': 200.0, 'A': 10.0, 'profile': 'Default'},
            {'a': 3, 'b': 0, 'E': 200.0, 'A': 10.0, 'profile': 'Default'}]
    loads = [{'node': 2, 'fx': 15.0, 'fy': 30.0}]
    supports = [{'node': 0, 'type': 'fixed'}, {'node': 1, 'type': 'rollerX'}]
    profiles = {'Default': {'E': 200.0, 'A': 10.0, 'I': 8000.0},
                'Heavy': {'E': 200.0, 'A': 12.0, 'I': 9000.0}}
    plates = [{'kind': 'panel', 'nodes': [0, 1, 2, 3], 'thickness_mm': 7.0,
               'G_GPa': 80.0, 'E_GPa': 200.0, 'nu': 0.3, 'Fy': 275.0,
               'Fexx': 480.0, 'weld_lines': 2},
              {'kind': 'gusset', 'node': 2, 'thickness_mm': 12.0, 'Fy': 235.0,
               'Fu': 360.0, 'Fexx': 480.0, 'weld_lines': 2, 'landing_m': 0.28,
               'conn_type': 'bolted', 'bolt_d_mm': 16.0, 'bolt_rows': 2,
               'bolt_cols': 3, 'pitch_mm': 60.0, 'gauge_mm': 55.0,
               'end_mm': 40.0, 'edge_mm': 35.0}]
    guides = [{'kind': 'func', 'expr': '4*f*x*(L-x)/L^2', 'x0': 0.0, 'x1': 20.0,
                'params': {'L': 20.0, 'f': 4.0}},
              {'kind': 'circle', 'c': (2.0, 1.0), 'r': 6.0, 'a0': 0.0, 'a1': 180.0}]
    res, err = analyze(nodes, rods, loads, supports, plates)
    assert err is None, err

    path = _tmp_xlsx()
    try:
        export_excel(nodes, rods, loads, supports, res, path,
                     profiles=profiles, plates=plates, guides=guides)
        n2, r2, l2, s2, p2, pl2, gu2 = import_excel_model(path)
    finally:
        _cleanup(path)

    assert len(n2) == len(nodes)
    for a, b in zip(nodes, n2):
        assert a[0] == pytest.approx(b[0], abs=1e-6)
        assert a[1] == pytest.approx(b[1], abs=1e-6)
    assert len(r2) == len(rods)
    for a, b in zip(rods, r2):
        assert a['a'] == b['a'] and a['b'] == b['b']
        assert a['E'] == pytest.approx(b['E'])
        assert a['A'] == pytest.approx(b['A'])
        assert a.get('conn', 'pin') == b.get('conn', 'pin')
        assert a.get('udl', 0.0) == pytest.approx(b.get('udl', 0.0))
        assert a.get('udl_rotation_deg', 0.0) == pytest.approx(
            b.get('udl_rotation_deg', 0.0))
    for a, b in zip(loads, l2):
        assert a['node'] == b['node']
        assert a['fx'] == pytest.approx(b['fx'])
        assert a['fy'] == pytest.approx(b['fy'])
    for a, b in zip(supports, s2):
        assert a['node'] == b['node'] and a['type'] == b['type']
    assert set(p2) == set(profiles)
    assert len(pl2) == 2
    pan = [q for q in pl2 if q['kind'] == 'panel'][0]
    gus = [q for q in pl2 if q['kind'] == 'gusset'][0]
    assert pan['nodes'] == [0, 1, 2, 3]
    assert pan['thickness_mm'] == pytest.approx(7.0)
    assert pan['Fy'] == pytest.approx(275.0)
    assert gus['node'] == 2 and gus['conn_type'] == 'bolted'
    assert gus['bolt_cols'] == 3 and gus['gauge_mm'] == pytest.approx(55.0)
    # construction guides are design intent, and must survive the round trip:
    # reopening a model without the curve it was laid out on loses the reason
    # the nodes are where they are
    assert len(gu2) == 2
    fn = [q for q in gu2 if q['kind'] == 'func'][0]
    arc = [q for q in gu2 if q['kind'] == 'circle'][0]
    assert fn['expr'] == '4*f*x*(L-x)/L^2'
    assert fn['params'] == {'L': pytest.approx(20.0), 'f': pytest.approx(4.0)}
    assert fn['x1'] == pytest.approx(20.0)
    assert arc['r'] == pytest.approx(6.0) and arc['a1'] == pytest.approx(180.0)


# ── presentation and nomenclature, across every tab ──────────────────────────

def _built_workbooks():
    """(tab name, path) for one exported workbook per tab, built from the
    real apps. Caller deletes the files."""
    out = []
    for which in ('beam', 'arch', 'cable'):
        root, app = _make(which)
        try:
            state = app._current_state()
            path = _tmp_xlsx()
            mod, _cls = TABS[which]
            m = __import__(mod, fromlist=['x'])
            getattr(m, 'export_%s_excel' % which)(state, path)
            out.append((which, path))
        finally:
            root.destroy(); gc.collect()

    from common import PX_PER_M
    from apps.truss.truss_reports import export_excel
    path = _tmp_xlsx()
    export_excel([(0.0, 0.0), (4 * PX_PER_M, 0.0)],
                 [{'a': 0, 'b': 1, 'E': 200.0, 'A': 10.0}],
                 [{'node': 1, 'fx': 0.0, 'fy': 10.0}],
                 [{'node': 0, 'type': 'pin'}], None, path,
                 profiles={'Default': {'E': 200.0, 'A': 10.0}})
    out.append(('truss', path))
    return out


def _model_rows(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    assert 'Model' in wb.sheetnames, wb.sheetnames
    return list(wb['Model'].iter_rows(values_only=True))


def _sections(rows):
    return [str(r[0]) for r in rows
            if r and r[0] is not None and str(r[0]).startswith('[')]


def _headers_by_section(rows):
    out = {}
    for i, r in enumerate(rows):
        if r and r[0] is not None and str(r[0]).startswith('['):
            hdr = rows[i + 1] if i + 1 < len(rows) else None
            out[str(r[0])] = [str(h) for h in (hdr or []) if h is not None]
    return out


#: header names that are genuinely unitless -- a type, a name, an index or a
#: dimensionless count. Everything else must carry its unit.
UNITLESS_OK = {
    # identities and indices
    'type', 'name', 'kind', 'nodes', 'node', 'a', 'b', 'idx', 'rod',
    'profile', 'conn', 'conn_type', 'arch_type', 'support', 'mode',
    # expressions and categories
    'shape', 'expr', 'shape_expr', 'measure', 'direction', 'udl_global',
    'params', 'family', 'set_by', 'flip', 'branch', 'pts_m',
    # dimensionless counts
    'bolt_rows', 'bolt_cols', 'weld_lines', 'n_elem', 'n_elems',
}

UNIT_SUFFIXES = ('_m', '_kn', '_mpa', '_gpa', '_cm', '_mm', '_deg', '_frac',
                 '_pct', '_m2', '_m4', '_cm2', '_cm4', '_knm', '_kncm2',
                 '_n', '_kg', '_pa')


def test_every_model_sheet_declares_its_units_in_the_headers():
    """A column called `x` is ambiguous; `x_m` is not. Units belong in the
    header, where the reader is, not in prose elsewhere in the workbook."""
    books = _built_workbooks()
    try:
        problems = []
        for name, path in books:
            for sec, headers in _headers_by_section(_model_rows(path)).items():
                for h in headers:
                    low = h.lower()
                    if low in UNITLESS_OK:
                        continue
                    if any(u in low for u in UNIT_SUFFIXES):
                        continue
                    problems.append('%s %s: %r' % (name, sec, h))
        assert not problems, (
            'these model-sheet headers carry no unit:\n  ' +
            '\n  '.join(problems))
    finally:
        for _n, p in books:
            _cleanup(p)


def test_section_names_are_consistent_across_tabs():
    """`[POINT_LOADS]` must mean the same thing in every tab's sheet. Three
    different names for one idea (DISTRIBUTED_LOADS / DLOADS / UNIFORM_LOADS)
    is what this guards against coming back."""
    books = _built_workbooks()
    try:
        seen = {}
        for name, path in books:
            for sec in _sections(_model_rows(path)):
                seen.setdefault(sec, []).append(name)
        # [UNIFORM_LOADS] is NOT on this list, and that is deliberate. Arch's
        # section holds two whole-span scalars (self weight, wind); Beam's and
        # Cable's [DISTRIBUTED_LOADS] hold a LIST of per-region loads. They are
        # different shapes carrying different data, so one name for both would
        # be the misleading choice, not the tidy one.
        #
        # [LOADS] is on it: the Truss sheet also has a [POINT_LOADS] section,
        # for loads applied ALONG a rod, so a section merely called [LOADS]
        # right next to it said nothing. It is now [NODE_LOADS].
        aliases = sorted(s for s in seen
                         if s in ('[DLOADS]', '[DIST_LOADS]', '[LOADS]'))
        assert not aliases, (
            'these duplicate or under-specify a name already used elsewhere; '
            'use [DISTRIBUTED_LOADS] or [NODE_LOADS]: %s -- seen in %s'
            % (aliases, {a: seen[a] for a in aliases}))
        # and the shared name really is shared
        assert '[DISTRIBUTED_LOADS]' in seen, seen
    finally:
        for _n, p in books:
            _cleanup(p)


def test_every_model_sheet_titles_itself():
    """The sheet is meant to be read and edited by hand, so its first row has
    to say what it is and that column order matters."""
    books = _built_workbooks()
    try:
        for name, path in books:
            title = str(_model_rows(path)[0][0] or '')
            assert 'MODEL' in title.upper(), (name, title)
            assert 'import' in title.lower(), (name, title)
    finally:
        for _n, p in books:
            _cleanup(p)


def test_truss_exports_a_model_only_workbook_before_any_analysis():
    """Saving the model you just drew, before pressing Analyze, is the whole
    point of the round trip -- and it used to raise AttributeError on
    `results` being None, which the tab reported as "Export failed". The Beam
    tab always allowed this; the Truss tab now does too."""
    from common import PX_PER_M
    from apps.truss.truss_reports import export_excel, import_excel_model
    nodes = [(0.0, 0.0), (4 * PX_PER_M, 0.0), (4 * PX_PER_M, -3 * PX_PER_M)]
    rods = [{'a': 0, 'b': 1, 'E': 200.0, 'A': 10.0},
            {'a': 1, 'b': 2, 'E': 200.0, 'A': 10.0},
            {'a': 2, 'b': 0, 'E': 200.0, 'A': 10.0}]
    loads = [{'node': 2, 'fx': 5.0, 'fy': 12.0}]
    supports = [{'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'rollerX'}]

    path = _tmp_xlsx()
    try:
        export_excel(nodes, rods, loads, supports, None, path,
                     profiles={'Default': {'E': 200.0, 'A': 10.0}})
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        # only the Model sheet, and it says why the others are absent
        assert wb.sheetnames == ['Model'], wb.sheetnames
        blurb = ' '.join(str(c) for r in wb['Model'].iter_rows(values_only=True)
                         for c in (r or []) if c)
        assert 'no analysis' in blurb.lower()
        # ...and it still round trips
        n2, r2, l2, s2, _p2, _pl2, _gu2 = import_excel_model(path)
    finally:
        _cleanup(path)

    assert len(n2) == 3 and len(r2) == 3 and len(l2) == 1 and len(s2) == 2
    assert l2[0]['node'] == 2
    assert l2[0]['fx'] == pytest.approx(5.0)
    assert l2[0]['fy'] == pytest.approx(12.0)


def test_truss_node_force_vector_sheet_balances_at_every_node():
    """The exported sheet carries its own equilibrium row, so it has to close
    -- including the moment column at a fixed support, and including a shear
    panel's corner forces. Same two bugs as the on-screen report: axial-only
    vectors, and the reaction moment added in the wrong frame."""
    from common import PX_PER_M
    from apps.truss.truss_reports import export_excel
    from apps.truss.truss_app import analyze

    def m(x, y):
        return (x * PX_PER_M, -y * PX_PER_M)

    nodes = [m(0, 0), m(3, 0), m(3, 2), m(0, 2)]
    rods = [{'a': a, 'b': b, 'E': 200.0, 'A': 60.0, 'I': 8000.0, 'conn': 'rigid'}
            for a, b in ((0, 1), (1, 2), (2, 3), (3, 0))]
    loads = [{'node': 2, 'fx': 40.0, 'fy': 0.0}]
    supports = [{'node': 0, 'type': 'fixed'}, {'node': 1, 'type': 'fixed'}]
    plates = [{'kind': 'panel', 'nodes': [0, 1, 2, 3], 'thickness_mm': 8.0,
               'G_GPa': 80.0}]
    res, err = analyze(nodes, rods, loads, supports, plates)
    assert err is None, err

    path = _tmp_xlsx()
    try:
        export_excel(nodes, rods, loads, supports, res, path, plates=plates)
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        assert 'Node Force Vectors' in wb.sheetnames
        ws = wb['Node Force Vectors']
        rows = list(ws.iter_rows(values_only=True))
    finally:
        _cleanup(path)

    header = [str(h) for h in rows[2] if h is not None]
    assert any('N axial' in h for h in header), header
    assert any('M (' in h for h in header), header

    checks = [r for r in rows if r and any(
        isinstance(c, str) and c.startswith('Sum') for c in r if c is not None)]
    assert checks, 'the sheet has no equilibrium rows at all'
    for r in checks:
        for col in (6, 7, 8):        # Fx, Fy, M columns (0-based)
            v = r[col]
            if isinstance(v, (int, float)):
                assert abs(v) < 1e-2, (col, v, r)

    body = ' '.join(str(c) for r in rows for c in (r or []) if c)
    assert 'panel' in body.lower(), 'the shear panel never appears in the sheet'
