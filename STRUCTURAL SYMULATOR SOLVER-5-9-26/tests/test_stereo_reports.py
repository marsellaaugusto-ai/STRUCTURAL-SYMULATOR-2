"""Excel round-trip tests for the Stereo tab (apps/stereo/stereo_reports.py),
mirroring tests/test_excel_roundtrip.py's approach for Truss: export a
model, re-import it, and the geometry/loads/supports/member properties (and
therefore a re-run analysis) must come back identical -- not merely "close".
"""
import tempfile
import os

import pytest

from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_math as sm
from apps.stereo import stereo_reports as sr


def _built_model():
    mesh = sg.flat_grid(span_x=6.0, span_y=6.0, depth=1.0, module=3.0, offset=True)
    nodes, members = mesh['nodes'], mesh['members']
    for m in members:
        m.update(E=200.0, A=15.0, I=400.0, J=400.0, Fy=250.0, Fu=400.0, r_gyr=2.5, K=1.0)
    # a moment load only makes physical sense where something can resist
    # it, so give node 0's first member a moment-transferring connection.
    for m in members:
        if m['a'] == 0 or m['b'] == 0:
            m['conn'] = 'rigid'
            break
    supports = []
    for i, node_i in enumerate(mesh['support_candidates']):
        if i == 0:
            # 'fixed' (not just translation-pinned), since this is also the
            # node carrying the mx moment load through a rigid member below
            # -- a moment needs somewhere that can actually resist rotation.
            supports.append({'node': node_i, 'type': 'fixed'})
        else:
            supports.append({'node': node_i, 'type': 'pin'})
    loads = sm.self_weight_loads(nodes, members) + [{'node': 0, 'fz': -5.0, 'mx': 1.0}]
    return nodes, members, loads, supports


def test_excel_round_trip_reproduces_the_model_exactly():
    nodes, members, loads, supports = _built_model()
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None
    checks = None

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'stereo_model.xlsx')
        sr.export_excel(nodes, members, loads, supports, res, path, checks=checks,
                         meta={'typology': 'flat_grid'})
        nodes2, members2, loads2, supports2 = sr.import_excel_model(path)

    assert len(nodes2) == len(nodes)
    for (x, y, z), (x2, y2, z2) in zip(nodes, nodes2):
        assert x2 == pytest.approx(x, abs=1e-9)
        assert y2 == pytest.approx(y, abs=1e-9)
        assert z2 == pytest.approx(z, abs=1e-9)

    assert len(members2) == len(members)
    for m, m2 in zip(members, members2):
        assert m2['a'] == m['a'] and m2['b'] == m['b']
        assert m2['conn'] == m.get('conn', 'pin')
        for f in ('E', 'A', 'I', 'J', 'Fy', 'Fu', 'r_gyr', 'K'):
            assert m2[f] == pytest.approx(m[f], rel=1e-9)

    by_node = {ld['node']: ld for ld in loads}
    by_node2 = {ld['node']: ld for ld in loads2}
    assert set(by_node) == set(by_node2)
    for n in by_node:
        for f in ('fx', 'fy', 'fz', 'mx', 'my', 'mz'):
            assert by_node2[n][f] == pytest.approx(by_node[n].get(f, 0.0), abs=1e-9)

    by_node_sp = {sp['node']: sm.support_restraints(sp) for sp in supports}
    by_node_sp2 = {sp['node']: sm.support_restraints(sp) for sp in supports2}
    assert by_node_sp == by_node_sp2

    # and it must re-analyze to the SAME answer, not just look the same
    res2, err2 = sm.analyze(nodes2, members2, loads2, supports2)
    assert err2 is None
    for a, b in zip(res['node_res'], res2['node_res']):
        for k in sm.DOF_NAMES:
            assert a[k] == pytest.approx(b[k], abs=1e-6)


def test_import_of_a_workbook_with_no_model_sheet_raises_clearly():
    from common import _ensure_openpyxl
    assert _ensure_openpyxl()
    import openpyxl
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'not_a_stereo_file.xlsx')
        wb = openpyxl.Workbook()
        wb.save(path)
        with pytest.raises(ValueError):
            sr.import_excel_model(path)


def test_iso_project_uses_z_as_vertical_axis():
    """_iso_project must treat Z as the vertical axis: a pure +Z vector
    should project predominantly upward (negative screen-y)."""
    import math
    from apps.stereo.stereo_reports import _iso_project
    az = math.radians(30)
    el = math.radians(25)
    _, sy_z = _iso_project(0, 0, 1, az, el)
    _, sy_y = _iso_project(0, 1, 0, az, el)
    assert sy_z < 0, "Z must project upward (negative screen-y)"
    assert abs(sy_z) > abs(sy_y), "Z must be the dominant vertical axis"


def test_summary_text_reports_before_and_after_analysis():
    nodes, members, loads, supports = _built_model()
    text_before = sr.summary_text(nodes, members, None)
    assert 'Not yet analyzed' in text_before

    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None
    text_after = sr.summary_text(nodes, members, res)
    assert 'Max nodal displacement' in text_after
    assert 'Max tension' in text_after
