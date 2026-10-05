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
from apps.stereo import stereo_checks as sk


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
        nodes2, members2, loads2, supports2, profiles2 = sr.import_excel_model(path)

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


# ── Profile round-trip ────────────────────────────────────────────────────

def test_excel_round_trip_with_profiles():
    """Named profiles export to a [PROFILES] section and come back intact."""
    nodes, members, loads, supports = _built_model()
    profiles = {
        'IPE 300': {'E': 200.0, 'A': 51.88, 'I': 7999.0, 'J': 15.57,
                    'Fy': 235.0, 'Fu': 360.0, 'r_gyr': 12.42, 'K': 1.0,
                    'catalog': 'IPE 300', 'material': 'F24'},
        'HEA 200': {'E': 200.0, 'A': 53.83, 'I': 3692.0, 'J': 21.0,
                    'Fy': 345.0, 'Fu': 450.0, 'r_gyr': 8.28, 'K': 0.85},
    }
    for m in members[:len(members) // 2]:
        m['profile'] = 'IPE 300'
    for m in members[len(members) // 2:]:
        m['profile'] = 'HEA 200'

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'profiles.xlsx')
        sr.export_excel(nodes, members, loads, supports, None, path,
                        profiles=profiles)
        _, members2, _, _, profiles2 = sr.import_excel_model(path)

    assert set(profiles2.keys()) == {'IPE 300', 'HEA 200'}
    for pname in profiles:
        for key in ('E', 'A', 'I', 'J', 'Fy', 'Fu', 'r_gyr', 'K'):
            assert profiles2[pname][key] == pytest.approx(profiles[pname][key], rel=1e-6), \
                f'{pname}.{key}'
    assert profiles2['IPE 300'].get('catalog') == 'IPE 300'
    assert profiles2['IPE 300'].get('material') == 'F24'

    for m in members2[:len(members2) // 2]:
        assert m.get('profile') == 'IPE 300'
    for m in members2[len(members2) // 2:]:
        assert m.get('profile') == 'HEA 200'


def test_excel_round_trip_without_profiles_returns_empty_dict():
    """A file exported without profiles still imports cleanly."""
    nodes, members, loads, supports = _built_model()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'no_profiles.xlsx')
        sr.export_excel(nodes, members, loads, supports, None, path)
        _, _, _, _, profiles2 = sr.import_excel_model(path)
    assert profiles2 == {}


# ═══════════════════════════════════════════════════════════════════════════
#  Phase 6 — export tests
# ═══════════════════════════════════════════════════════════════════════════

def _analysed_model():
    nodes, members, loads, supports = _built_model()
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None
    return nodes, members, loads, supports, res


# ── 6.1  PDF export ───────────────────────────────────────────────────────

def _pdf_page_count(path):
    """Pages in a PDF, straight out of the file's own /Type /Page objects.

    Counted from the bytes rather than from matplotlib's call count, so the
    assertion is about the artefact the user opens. The negative lookahead
    matters: every PDF also carries one /Type /Pages tree node, and
    /Type /Page is a prefix of it.
    """
    import re
    data = open(path, 'rb').read()
    return len(re.findall(rb'/Type\s*/Page(?![a-zA-Z])', data))


def test_export_pdf_creates_multi_page_file():
    nodes, members, loads, supports, res = _analysed_model()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'report.pdf')
        sr.export_pdf(nodes, members, loads, supports, res, path,
                      az_deg=35.0, el_deg=22.0)
        assert os.path.isfile(path)
        size = os.path.getsize(path)
        assert size > 1000


def test_export_pdf_without_results():
    nodes, members, loads, supports = _built_model()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'report.pdf')
        sr.export_pdf(nodes, members, loads, supports, None, path,
                      az_deg=35.0, el_deg=22.0)
        assert os.path.isfile(path)


def test_export_pdf_unanalysed_report_has_the_geometry_sheets_only():
    """Without results there is nothing to plot but the model itself --
    the general view and the five orthographic ones -- and the title
    block's 'Sheet 1 / N' must not promise sheets the file does not have."""
    nodes, members, loads, supports = _built_model()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'report.pdf')
        sr.export_pdf(nodes, members, loads, supports, None, path)
        assert _pdf_page_count(path) == 6
        bare = os.path.join(d, 'bare.pdf')
        sr.export_pdf(nodes, members, loads, supports, None, bare,
                      ortho_views=False)
        assert _pdf_page_count(bare) == 1


def test_export_pdf_with_checks_has_the_utilization_sheet():
    """The utilisation sheet exists only when a member actually carries a
    section, and the reactions/governing-member sheets always follow the
    view sheets."""
    nodes, members, loads, supports, res = _analysed_model()
    checks = sk.check_all_members(nodes, members, res['member_res'])
    assert any(c.get('checked') for c in checks)
    with tempfile.TemporaryDirectory() as d:
        with_checks = os.path.join(d, 'with.pdf')
        without = os.path.join(d, 'without.pdf')
        sr.export_pdf(nodes, members, loads, supports, res, with_checks,
                      checks=checks)
        sr.export_pdf(nodes, members, loads, supports, res, without)
        # Counted from plan_sheets rather than written out as a number:
        # the plan IS what the render loop walks and what the title
        # block's 'Sheet n / N' counts, so pinning the magic number here
        # only made this test go stale every time a sheet was added.
        n_rigid = sum(1 for m in members if m.get('conn') == 'rigid')
        assert _pdf_page_count(with_checks) == \
            len(sr.plan_sheets(res, checks, n_rigid))
        assert _pdf_page_count(without) == \
            len(sr.plan_sheets(res, None, n_rigid))
        # the utilisation sheets are exactly what the sections buy
        assert _pdf_page_count(with_checks) > _pdf_page_count(without)


# ── 6.1  PDF sheet furniture ──────────────────────────────────────────────
#
# The report is read as a DRAWING, so the furniture that makes a drawing
# readable off the screen -- which way is up, how big is it, what does the
# colour mean -- is tested here as its own behaviour rather than left to
# "the file was produced".

def test_pdf_projection_puts_z_up_for_matplotlib():
    """_iso_project answers in Tk canvas coordinates (y grows DOWN); the
    PDF path must flip it, or every sheet is a vertical mirror of the tab
    it reports on -- a sagging roof would bulge upward."""
    import math
    az, el = math.radians(35.0), math.radians(22.0)
    _, up_y = sr._pdf_project(0.0, 0.0, 1.0, az, el)
    _, down_y = sr._pdf_project(0.0, 0.0, -1.0, az, el)
    assert up_y > 0, '+Z must land ABOVE the origin on the sheet'
    assert down_y < 0
    # and it must still be the same projection, just mirrored
    sx_iso, sy_iso = sr._iso_project(3.0, -2.0, 1.5, az, el)
    sx_pdf, sy_pdf = sr._pdf_project(3.0, -2.0, 1.5, az, el)
    assert sx_pdf == pytest.approx(sx_iso)
    assert sy_pdf == pytest.approx(-sy_iso)


# ── the five orthographic views ───────────────────────────────────────────

def test_the_five_named_views_are_all_there():
    names = [n for n, _ in sr.PDF_ORTHO_VIEWS]
    assert names == ['plan', 'front', 'back', 'right', 'left']


def test_each_orthographic_view_puts_the_right_world_axes_on_the_sheet():
    """The whole point of a named view is that it IS that view. Checked by
    projecting the world unit axes and reading where they land, not by
    trusting the azimuth table."""
    import math
    expect = {
        # view:   (horizontal axis and its sheet direction, vertical, normal)
        'plan':  ('X', +1, 'Y', +1),
        'front': ('X', +1, 'Z', +1),
        'back':  ('X', -1, 'Z', +1),
        'right': ('Y', +1, 'Z', +1),
        'left':  ('Y', -1, 'Z', +1),
    }
    for name, view in sr.PDF_ORTHO_VIEWS:
        az, el = math.radians(view['az']), math.radians(view['el'])
        h_axis, h_dir, v_axis, v_dir = expect[name]
        assert (view['h'], view['v']) == (h_axis, v_axis), name

        hx, hy = sr._pdf_project(*sr.PDF_AXIS_UNIT[h_axis], az, el)
        assert hx == pytest.approx(h_dir, abs=1e-9), f'{name}: {h_axis} across'
        assert hy == pytest.approx(0.0, abs=1e-9), f'{name}: {h_axis} is level'

        vx, vy = sr._pdf_project(*sr.PDF_AXIS_UNIT[v_axis], az, el)
        assert vy == pytest.approx(v_dir, abs=1e-9), f'{name}: {v_axis} up'
        assert vx == pytest.approx(0.0, abs=1e-9), f'{name}: {v_axis} is plumb'

        # and the third axis must vanish -- that is what makes it orthographic
        nx, ny = sr._pdf_project(*sr.PDF_AXIS_UNIT[view['normal']], az, el)
        assert math.hypot(nx, ny) == pytest.approx(0.0, abs=1e-9), name


def test_the_vanishing_axis_is_marked_toward_or_away_correctly():
    """A circled dot means "coming at you", a circled cross "going away".
    Getting that backwards would mirror the reader's mental model of the
    structure, so the sign is pinned per view."""
    import math
    away = {'plan': False,    # you are above; +Z points back up at you
            'front': True,    # you look along +Y, so +Y runs away
            'back': False,    # you look along -Y, so +Y comes at you
            'right': False,   # you look along -X, so +X comes at you
            'left': True}     # you look along +X, so +X runs away
    for name, view in sr.PDF_ORTHO_VIEWS:
        az, el = math.radians(view['az']), math.radians(view['el'])
        d = sr._pdf_view_depth(*sr.PDF_AXIS_UNIT[view['normal']], az, el)
        assert (d > 0) is away[name], f'{name}: depth {d}'
        assert abs(d) == pytest.approx(1.0, abs=1e-9)


def test_ortho_frame_reports_the_mirrored_views_as_mirrored():
    """The ghost grid labels world coordinates, so it has to know that the
    back and left views run their horizontal axis the other way."""
    import math
    for name, view in sr.PDF_ORTHO_VIEWS:
        az, el = math.radians(view['az']), math.radians(view['el'])
        h_sign, v_sign = sr._pdf_ortho_frame(az, el, view['h'], view['v'])
        assert v_sign == 1.0, name
        assert h_sign == (-1.0 if name in ('back', 'left') else 1.0), name


def test_the_report_carries_a_sheet_for_every_view():
    nodes, members, loads, supports, res = _analysed_model()
    checks = sk.check_all_members(nodes, members, res['member_res'])
    with tempfile.TemporaryDirectory() as d:
        full = os.path.join(d, 'full.pdf')
        short = os.path.join(d, 'short.pdf')
        sr.export_pdf(nodes, members, loads, supports, res, full, checks=checks)
        sr.export_pdf(nodes, members, loads, supports, res, short,
                      checks=checks, ortho_views=False)
        n_rigid = sum(1 for m in members if m.get('conn') == 'rigid')
        assert _pdf_page_count(full) == \
            len(sr.plan_sheets(res, checks, n_rigid))
        # whatever else the report gains, dropping ortho_views drops
        # exactly the five orthographic sheets and nothing else
        assert _pdf_page_count(full) - _pdf_page_count(short) == 5
        assert _pdf_page_count(short) == len(sr.plan_sheets(
            res, checks, n_rigid,
            set(sr.PDF_SHEET_GROUPS) - {'views'}))


def test_an_unanalysed_report_still_carries_the_views():
    nodes, members, loads, supports = _built_model()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'r.pdf')
        sr.export_pdf(nodes, members, loads, supports, None, path)
        assert _pdf_page_count(path) == 6      # general + five views


# ── the isolated selection ────────────────────────────────────────────────

def test_submodel_keeps_only_what_was_selected_and_renumbers_it():
    nodes, members, loads, supports, res = _analysed_model()
    checks = sk.check_all_members(nodes, members, res['member_res'])
    picked = [0, 5, 9]
    (s_nodes, s_members, s_loads, s_supports, s_res, s_checks,
     node_map) = sr.submodel(nodes, members, loads, supports, res, checks,
                             member_idx=picked)

    assert len(s_members) == len(picked)
    # every kept bar brought both of its own ends, and nothing else
    expected_nodes = set()
    for i in picked:
        expected_nodes.add(members[i]['a'])
        expected_nodes.add(members[i]['b'])
    assert set(node_map) == expected_nodes
    assert len(s_nodes) == len(expected_nodes)

    # the indices are re-based, and they still point at the same geometry
    for new_m, old_i in zip(s_members, picked):
        assert 0 <= new_m['a'] < len(s_nodes)
        assert 0 <= new_m['b'] < len(s_nodes)
        assert s_nodes[new_m['a']] == pytest.approx(nodes[members[old_i]['a']])
        assert s_nodes[new_m['b']] == pytest.approx(nodes[members[old_i]['b']])
        assert new_m['_source_index'] == old_i

    # and every parallel array came with them
    assert len(s_res['member_res']) == len(picked)
    assert len(s_res['node_res']) == len(s_nodes)
    assert len(s_checks) == len(picked)
    for new_i, old_i in enumerate(picked):
        assert s_res['member_res'][new_i]['N'] == res['member_res'][old_i]['N']


def test_submodel_drops_the_loads_and_supports_of_nodes_it_left_behind():
    nodes, members, loads, supports, res = _analysed_model()
    picked = [0]
    s_nodes, s_members, s_loads, s_supports, s_res, _, node_map = sr.submodel(
        nodes, members, loads, supports, res, None, member_idx=picked)
    assert len(s_loads) < len(loads)
    for ld in s_loads:
        assert 0 <= ld['node'] < len(s_nodes)
    for sp in s_supports:
        assert 0 <= sp['node'] < len(s_nodes)
    for n in s_res['reactions']:
        assert 0 <= n < len(s_nodes)


def test_submodel_carries_a_lone_selected_node():
    """A joint picked on its own still has to travel, or an isolated node
    could never be reported."""
    nodes, members, loads, supports = _built_model()
    s_nodes, s_members, _, _, _, _, node_map = sr.submodel(
        nodes, members, loads, supports, member_idx=[], node_idx=[3])
    assert s_members == []
    assert len(s_nodes) == 1
    assert s_nodes[0] == pytest.approx(nodes[3])


def test_submodel_with_nothing_specified_is_the_whole_model():
    nodes, members, loads, supports, res = _analysed_model()
    s_nodes, s_members, s_loads, s_supports, s_res, _, _ = sr.submodel(
        nodes, members, loads, supports, res)
    assert len(s_nodes) == len(nodes)
    assert len(s_members) == len(members)
    assert len(s_loads) == len(loads)
    assert len(s_supports) == len(supports)


def test_a_selection_report_names_both_the_file_and_the_group():
    nodes, members, loads, supports, res = _analysed_model()
    s = sr.submodel(nodes, members, loads, supports, res, None,
                    member_idx=[0, 1, 2])
    meta = {'group': 'North bay ribs', 'subset_of': 'roof_v3.xlsx'}
    fields = dict(sr._pdf_sheet_meta(s[0], s[1], meta))
    assert fields['GROUP'] == 'North bay ribs'
    assert fields['FILE'] == 'roof_v3.xlsx'
    assert 'MODEL' not in fields, 'a group names its file, not a family'

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'group.pdf')
        sr.export_pdf(s[0], s[1], s[2], s[3], s[4], path, checks=s[5],
                      meta=meta)
        assert os.path.isfile(path)
        sub_rigid = sum(1 for m in s[1] if m.get('conn') == 'rigid')
        # no checks travelled with the cut, so no utilisation sheets
        assert _pdf_page_count(path) == \
            len(sr.plan_sheets(s[4], s[5], sub_rigid))


def test_a_whole_model_report_still_names_the_model():
    fields = dict(sr._pdf_sheet_meta([], [], {'grid_family': 'dome'}))
    assert fields['MODEL'] == 'dome'
    assert 'GROUP' not in fields


# ── the scale bar ─────────────────────────────────────────────────────────

def test_the_scale_bar_is_horizontal_and_exact_on_an_orthographic_view():
    """It is read as a ruler, so it is drawn level in every view. On an
    orthographic sheet that costs nothing, because the sheet's horizontal
    axis IS a world axis -- one metre of it is one data unit."""
    import math
    for name, view in sr.PDF_ORTHO_VIEWS:
        az, el = math.radians(view['az']), math.radians(view['el'])
        unit = math.hypot(*sr._pdf_project(*sr.PDF_AXIS_UNIT[view['h']],
                                           az, el))
        assert unit == pytest.approx(1.0, abs=1e-9), name


def test_the_axonometric_scale_bar_is_foreshortened_and_says_so():
    import math
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    az, el = math.radians(35.0), math.radians(22.0)
    unit = math.hypot(*sr._pdf_project(*sr.PDF_AXIS_UNIT['X'], az, el))
    assert unit < 1.0, 'X is foreshortened on an axonometric view'

    fig = plt.figure(figsize=sr.PDF_SHEET_IN)
    ax = fig.add_subplot(111)
    chosen = sr._pdf_scale_bar(ax, 20.0, (0.0, 0.0), unit_len_data=unit,
                               ref_axis='X', exact=False)
    texts = [t.get_text() for t in ax.texts]
    ys = [p.get_y() for p in ax.patches]
    plt.close(fig)

    assert chosen > 0
    assert any('foreshortened' in t for t in texts)
    assert any('along X' in t for t in texts)
    # every chequer sits on the SAME baseline: the bar is level
    assert len(ys) == sr.PDF_SCALE_DIVISIONS
    assert len({round(y, 9) for y in ys}) == 1


def test_the_scale_bar_says_true_to_scale_when_it_is():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=sr.PDF_SHEET_IN)
    ax = fig.add_subplot(111)
    sr._pdf_scale_bar(ax, 20.0, (0.0, 0.0), unit_len_data=1.0, exact=True)
    texts = [t.get_text() for t in ax.texts]
    plt.close(fig)
    assert any('true to scale' in t for t in texts)


def test_pdf_nice_length_rounds_to_1_2_or_5():
    """A graphic scale bar has to be a length the reader can divide in
    their head, so it is always 1, 2 or 5 times a power of ten -- and
    never longer than what was asked for."""
    cases = {
        1.0: 1.0, 1.9: 1.0, 2.0: 2.0, 4.99: 2.0, 5.0: 5.0, 9.99: 5.0,
        10.0: 10.0, 13.7: 10.0, 23.0: 20.0, 78.0: 50.0, 100.0: 100.0,
        0.37: 0.2, 0.09: 0.05, 640.0: 500.0,
    }
    for raw, want in cases.items():
        assert sr._pdf_nice_length(raw) == pytest.approx(want), raw
        assert sr._pdf_nice_length(raw) <= raw + 1e-9


def test_pdf_nice_length_is_safe_on_a_degenerate_model():
    """A single-node or zero-extent model gets NO scale bar rather than a
    crash or a nonsense one."""
    import math
    for bad in (0.0, -3.0, float('nan'), float('inf')):
        assert sr._pdf_nice_length(bad) == 0.0
    assert not math.isnan(sr._pdf_nice_length(0.0))


def test_pdf_axis_dirs_foreshorten_each_axis_differently():
    """The triad draws all three arms at ONE world length precisely
    because a parallel projection squashes each axis by its own factor;
    this pins that the factors really do differ, and that Z is the least
    squashed at a shallow elevation (which is why the scale bar names the
    axis it is true for)."""
    import math
    az, el = math.radians(35.0), math.radians(22.0)
    f = sr._pdf_foreshortening(az, el)
    assert set(f) == {'X', 'Y', 'Z'}
    assert f['Z'] > f['X'] > f['Y'], f
    for k, v in f.items():
        assert 0.0 < v <= 1.0 + 1e-9, (k, v)
    # straight down the Z axis, X and Y are unsquashed and Z vanishes
    flat = sr._pdf_foreshortening(0.0, math.radians(90.0))
    assert flat['X'] == pytest.approx(1.0)
    assert flat['Y'] == pytest.approx(1.0)
    assert flat['Z'] == pytest.approx(0.0, abs=1e-12)


def test_pdf_model_extents_reports_the_bounding_box():
    nodes = [(0.0, 0.0, 0.0), (6.0, 0.0, 1.5), (6.0, 4.0, -0.5)]
    dx, dy, dz = sr._pdf_model_extents(nodes)
    assert (dx, dy, dz) == pytest.approx((6.0, 4.0, 2.0))
    assert sr._pdf_model_extents([]) == (0.0, 0.0, 0.0)


def test_pdf_equilibrium_closes_on_a_solved_model():
    """The reactions sheet claims equilibrium; that claim is computed, and
    on a real solve the residual must be numerically zero."""
    nodes, members, loads, supports, res = _analysed_model()
    applied, reacted, residual = sr._pdf_equilibrium(loads, res['reactions'])
    assert applied[2] < 0, 'this model is loaded downward'
    assert reacted[2] == pytest.approx(-applied[2], rel=1e-9)
    for r in residual:
        assert abs(r) < 1e-6, residual


def test_pdf_equilibrium_handles_a_model_with_no_results_yet():
    nodes, members, loads, supports = _built_model()
    applied, reacted, residual = sr._pdf_equilibrium(loads, None)
    assert reacted == (0.0, 0.0, 0.0)
    assert residual == pytest.approx(applied)


# ── the colour key must agree with the drawing ────────────────────────────

def test_pdf_key_colours_come_from_the_colour_functions():
    """The old sheet hand-quoted hexes in its legend (#e6b800 for
    utilisation 0.5, #aaaaaa for 'near zero') that the colour functions
    never produce, so the key disagreed with the picture beside it. The
    report must only name colours the app actually paints with."""
    import inspect
    from apps.stereo import stereo_app_colors as sc
    from apps.stereo import stereo_app_constants as k

    src = inspect.getsource(sr.export_pdf)
    for bogus in ('#e6b800', '#aaaaaa', '#888888', '#cccccc'):
        assert bogus not in src, f'{bogus} is not a colour this app paints with'

    # the values the key DOES name are the constants themselves
    assert sc.util_color(0.5) == k.UTIL_MID
    assert sc.util_color(0.0) == k.UTIL_LOW
    assert sc.util_color(1.4) == k.UTIL_HIGH
    assert sc.force_color(0.0, 10.0) == k.NEAR_ZERO_COLOR


def test_pdf_and_canvas_share_one_set_of_axis_colours():
    """The triad on the sheet and the gizmo on screen must never colour
    the same axis differently."""
    from apps.stereo import stereo_app_constants as k
    from apps.stereo.stereo_app_render import StereoRenderMixin
    assert StereoRenderMixin.AXIS_COLOR_X == k.AXIS_COLOR_X
    assert StereoRenderMixin.AXIS_COLOR_Y == k.AXIS_COLOR_Y
    assert StereoRenderMixin.AXIS_COLOR_Z == k.AXIS_COLOR_Z


# ── per-sheet statistics ──────────────────────────────────────────────────

def test_pdf_force_stats_name_the_extreme_bars():
    nodes, members, loads, supports, res = _analysed_model()
    lines = sr._pdf_force_stats(nodes, members, res['member_res'])
    text = '\n'.join(lines)
    assert 'AXIAL FORCE' in text
    assert 'max tension' in text and 'max compression' in text
    forces = [mr['N'] for mr in res['member_res']]
    i_max = max(range(len(forces)), key=lambda i: forces[i])
    assert f'bar {i_max}:' in text, 'the governing bar must be identified'
    assert f'{max(forces):+.2f} kN' in text


def test_pdf_util_stats_give_a_verdict():
    nodes, members, loads, supports, res = _analysed_model()
    checks = sk.check_all_members(nodes, members, res['member_res'])
    text = '\n'.join(sr._pdf_util_stats(checks))
    assert 'governing' in text
    worst = sk.worst_utilization(checks)
    assert f'{worst:.3f}' in text
    n_over = sum(1 for c in checks if c.get('checked') and c['util'] > 1.0)
    if n_over:
        assert 'OVER capacity' in text
    else:
        assert 'within capacity' in text


def test_pdf_util_stats_say_so_when_nothing_is_checkable():
    text = '\n'.join(sr._pdf_util_stats([{'checked': False, 'util': None}] * 3))
    assert 'no member has a section assigned' in text


def test_pdf_moment_stats_are_honest_about_a_pin_jointed_model():
    """A fully pinned model has no nodal moments at all. The sheet used to
    draw white dots and claim a +-0.00 kN.m range; it must instead say
    plainly that there is nothing to plot."""
    nodes, members, loads, supports = _built_model()
    text = '\n'.join(sr._pdf_moment_stats(nodes, {}, 0, len(members)))
    assert 'PIN' in text
    assert 'nothing to plot' in text
    assert f'0 of {len(members)}' in text


def test_pdf_moment_stats_report_both_extremes_when_there_are_moments():
    nodes = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 1.0, 0.0)]
    moments = {0: -1.25, 1: 0.5, 2: 3.75}
    text = '\n'.join(sr._pdf_moment_stats(nodes, moments, 3, 3))
    assert '+3.750' in text and '-1.250' in text
    assert 'node #2' in text and 'node #0' in text


def test_pdf_deform_stats_report_the_span_over_deflection_ratio():
    nodes, members, loads, supports, res = _analysed_model()
    disps = [(nr['ux'] ** 2 + nr['uy'] ** 2 + nr['uz'] ** 2) ** 0.5
             for nr in res['node_res']]
    text = '\n'.join(sr._pdf_deform_stats(nodes, res['node_res'], disps,
                                          42.0, 3.0))
    assert 'x42' in text
    assert 'L /' in text, 'a deflection is judged as a fraction of the span'
    assert f'{max(disps):.3f} mm' in text


def test_reactions_sheet_keeps_its_totals_when_the_table_overflows():
    """On a model with hundreds of supports the body of the reactions table
    runs off the sheet. The Σ-reaction / Σ-applied / residual lines must
    survive that truncation -- they are the reason the sheet exists."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=sr.PDF_SHEET_IN)
    rows = [[str(i)] + ['0.00'] * 3 for i in range(400)]
    tail = [['Σ react'] + ['+1.000'] * 3,
            ['Σ applied'] + ['-1.000'] * 3,
            ['residual'] + ['+0.00e+00'] * 3]
    ax = sr._pdf_table_page(fig, 'Reactions', ['node', 'Fx', 'Fy', 'Fz'],
                            rows, [1, 1, 1, 1], tail_rows=tail)
    drawn = [t.get_text() for t in ax.texts]
    plt.close(fig)

    for label in ('Σ react', 'Σ applied', 'residual'):
        assert label in drawn, f'{label} was truncated away'
    assert any('further row(s) not shown' in t for t in drawn), \
        'a truncated table must say so'
    assert '399' not in drawn, 'the body should have been truncated'


def test_table_page_without_a_tail_still_renders_every_row_that_fits():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=sr.PDF_SHEET_IN)
    rows = [[str(i), 'x'] for i in range(5)]
    ax = sr._pdf_table_page(fig, 'Short', ['a', 'b'], rows, [1, 1])
    drawn = [t.get_text() for t in ax.texts]
    plt.close(fig)
    for i in range(5):
        assert str(i) in drawn
    assert not any('not shown' in t for t in drawn)


def test_pdf_fmt_bar_names_both_ends_of_a_bar():
    """One end is not enough to find a bar in the model tree or the Excel
    export."""
    nodes = [(0.0, 0.0, 0.0), (2.0, 0.0, 1.0)]
    members = [{'a': 0, 'b': 1}]
    head, mid = sr._pdf_fmt_bar(nodes, members, 0)
    assert 'nodes 0' in head and '1' in head
    assert '1.00, 0.00, 0.50' in mid


# ── 6.2  SketchUp Ruby export ────────────────────────────────────────────

def test_export_sketchup_ruby_wireframe():
    nodes, members, _, supports = _built_model()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'model.rb')
        sr.export_sketchup_ruby(nodes, members, path)
        assert os.path.isfile(path)
        text = open(path).read()
        assert 'Geom::Point3d' in text
        assert 'add_edges' in text


def test_export_sketchup_ruby_solid():
    nodes, members, _, supports = _built_model()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'model_solid.rb')
        sr.export_sketchup_ruby(nodes, members, path,
                                node_radius=0.05, rod_radius=0.02)
        text = open(path).read()
        assert 'add_circle' in text


@pytest.mark.skipif(not __import__('shutil').which('ruby'),
                    reason='ruby not installed on this host')
def test_generated_sketchup_scripts_are_valid_ruby():
    """The script is handed to SketchUp's Ruby console, where a syntax
    error surfaces as a stack trace on the user's machine and nowhere
    else. `ruby -c` catches it here instead."""
    import shutil
    import subprocess
    nodes, members, loads, supports, res = _analysed_model()
    ruby = shutil.which('ruby')
    with tempfile.TemporaryDirectory() as d:
        for name, kw in (('wire.rb', {}),
                         ('solid.rb', {'node_radius': 0.12,
                                       'rod_radius': 0.05})):
            path = os.path.join(d, name)
            sr.export_sketchup_ruby(nodes, members, path, supports=supports,
                                    results=res, **kw)
            p = subprocess.run([ruby, '-c', path], capture_output=True,
                               text=True)
            assert p.returncode == 0, f'{name}: {p.stderr}'


# ── 6.3  IFC export ──────────────────────────────────────────────────────

def test_export_ifc_creates_valid_step_file():
    nodes, members, _, supports = _built_model()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'model.ifc')
        sr.export_ifc(nodes, members, path, supports=supports)
        assert os.path.isfile(path)
        text = open(path).read()
        assert 'ISO-10303-21' in text
        assert 'IFC2X3' in text
        assert 'IFCMEMBER' in text
        assert 'END-ISO-10303-21' in text


def test_export_ifc_member_count():
    nodes, members, _, supports = _built_model()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'model.ifc')
        sr.export_ifc(nodes, members, path)
        text = open(path).read()
        n_members = text.count('IFCMEMBER(')
        assert n_members == len(members)


# ── the analysis sheets added on 2026-09-27 ──────────────────────────────

def _rigid_model():
    """The same grid, but every bar moment-connected: a Vierendeel frame.

    The along-the-rod and node-solicitation sheets exist only where a
    joint can transfer a moment, so they need a model that has some.
    """
    nodes, members, loads, supports = _built_model()
    for m in members:
        m['conn'] = 'rigid'
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None
    checks = sk.check_all_members(nodes, members, res['member_res'])
    return nodes, members, loads, supports, res, checks


def test_plan_sheets_lists_every_sheet_the_report_will_have():
    """'Sheet n of N' is counted from this list, so it has to BE the list
    the render loop walks -- not a parallel arithmetic expression."""
    nodes, members, loads, supports, res, checks = _rigid_model()
    plan = sr.plan_sheets(res, checks, n_rigid=len(members))
    assert plan[0] == 'general'
    for key in ('plan', 'front', 'back', 'right', 'left',
                'force_iso', 'force_top',
                'util_iso', 'util_top', 'util_rel',
                'moment_nodes', 'moment_rods', 'moment_rods_plan_all',
                'shear_rods', 'shear_rods_plan_all',
                'deformed', 'reactions', 'governing',
                'solicitation_rods', 'solicitation_nodes'):
        assert key in plan, key
    assert len(plan) == len(set(plan))


def test_plan_sheets_drops_the_rigid_only_sheets_on_a_pin_truss():
    """Bending and shear ALONG a rod, and a joint solicitation schedule,
    are all identically zero on a pin-jointed truss. A sheet of zeros is
    worse than no sheet: it implies the model was checked for something it
    cannot carry."""
    nodes, members, loads, supports, res = _analysed_model()
    checks = sk.check_all_members(nodes, members, res['member_res'])
    plan = sr.plan_sheets(res, checks, n_rigid=0)
    assert 'moment_nodes' in plan          # nodal moments still apply
    assert 'moment_rods' not in plan
    assert 'shear_rods' not in plan
    assert 'solicitation_rods' in plan     # N and stress still apply
    assert 'solicitation_nodes' not in plan


def test_plan_sheets_honours_a_group_subset():
    nodes, members, loads, supports, res, checks = _rigid_model()
    plan = sr.plan_sheets(res, checks, len(members), groups={'force'})
    assert plan == ['general', 'force_iso', 'force_top']
    plan = sr.plan_sheets(res, checks, len(members), groups=set())
    assert plan == ['general']


def test_export_pdf_writes_exactly_the_planned_sheets():
    """The page count of the artefact, and the plan the title block counts
    from, must agree -- a 'Sheet 3 / 19' on a 12-page file is a lie."""
    nodes, members, loads, supports, res, checks = _rigid_model()
    with tempfile.TemporaryDirectory() as d:
        for groups in (None, {'force', 'tables'}, {'moment'}, set()):
            plan = sr.plan_sheets(res, checks, len(members), groups,
                                  members=members)
            path = os.path.join(d, f'{len(plan)}.pdf')
            sr.export_pdf(nodes, members, loads, supports, res, path,
                          checks=checks, groups=groups)
            assert _pdf_page_count(path) == len(plan), groups


def test_stress_widths_track_stress_not_force():
    """A thick chord and a thin web carrying the same kN are not working
    equally hard; the sheet's line weight is |N|/A, like the canvas."""
    members = [{'A': 10.0}, {'A': 10.0}, {'A': 1.0}]
    member_res = [{'N': 100.0}, {'N': 50.0}, {'N': 100.0}]
    widths, peak = sr._pdf_stress_widths(members, member_res, lo=1.0, hi=5.0)
    assert peak == pytest.approx(100.0)          # bar 2: 100 kN over 1 cm²
    assert widths[2] == pytest.approx(5.0)       # the peak draws at full width
    assert widths[0] == pytest.approx(1.0 + 4.0 * 0.10)
    assert widths[1] == pytest.approx(1.0 + 4.0 * 0.05)
    assert widths[0] > widths[1]                 # same area, more force
    assert widths[2] > widths[0]                 # same force, less area


def test_stress_widths_are_uniform_when_nothing_is_stressed():
    widths, peak = sr._pdf_stress_widths([{'A': 10.0}] * 3,
                                         [{'N': 0.0}] * 3, lo=1.0, hi=5.0)
    assert peak == 0.0
    assert widths == [1.0, 1.0, 1.0]


def test_stress_widths_survive_a_member_with_no_section():
    widths, peak = sr._pdf_stress_widths([{'A': 0.0}, {'A': 5.0}],
                                         [{'N': 10.0}, {'N': 10.0}],
                                         lo=1.0, hi=5.0)
    assert widths[0] == pytest.approx(1.0)       # no area: no stress to show
    assert widths[1] == pytest.approx(5.0)


def _diagram_axes():
    from common import _ensure_matplotlib
    assert _ensure_matplotlib()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig = plt.figure()
    return fig, fig.add_subplot(111)


def test_table_tail_rows_are_drawn_below_the_last_body_row():
    """The summary rows are the point of the sheet, so they are drawn
    even when the body has to be truncated -- and the rule that separates
    them must not strike through the row above it."""
    fig, _ = _diagram_axes()
    import matplotlib.pyplot as plt
    plt.close(fig)
    fig = plt.figure(figsize=sr.PDF_SHEET_IN)
    try:
        rows = [[str(i), 'x'] for i in range(200)]
        tail = [['MAX', '9.99'], ['MIN', '0.01']]
        ax = sr._pdf_table_page(fig, 'T', ['a', 'b'], rows, [1.0, 1.0],
                                tail_rows=tail)
        texts = [t.get_text() for t in ax.texts]
        assert 'MAX' in texts and 'MIN' in texts
        assert any('further row(s) not shown' in t for t in texts)
        tail_y = min(t.get_position()[1] for t in ax.texts
                     if t.get_text() in ('MAX', 'MIN'))
        rule_ys = [ln.get_ydata()[0] for ln in ax.lines]
        assert any(y > tail_y for y in rule_ys)
    finally:
        plt.close(fig)


# ── the report follows the app-wide unit selector ────────────────────────

def _read_pdf_text(path):
    """Every string a reader would see on the sheets.

    Through poppler's pdftotext, not by grepping the content stream:
    matplotlib embeds a subset font and writes glyph INDICES, so the
    bytes of a page that plainly reads "kN" contain no k and no N. The
    first version of this helper searched the raw stream and passed on
    nothing at all.
    """
    import shutil
    import subprocess
    exe = shutil.which('pdftotext')
    if exe is None:
        pytest.skip('pdftotext (poppler-utils) is not installed')
    p = subprocess.run([exe, '-layout', path, '-'], capture_output=True)
    assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')
    return p.stdout.decode('utf-8', 'replace')


@pytest.fixture
def unit_selector():
    """Leave the app-wide selector exactly as it was found."""
    import units
    before = units.current()
    yield units
    units.set_current(
        [k for k in units.ORDER if units.SYSTEMS[k] is before][0])


def test_report_units_convert_from_the_tab_storage(unit_selector):
    unit_selector.set_current('aisc')
    u = sr.ReportUnits()
    assert u.v('force', 100.0) == pytest.approx(22.4809, rel=1e-3)   # kN -> kip
    assert u.v('length', 6.0) == pytest.approx(19.685, rel=1e-3)     # m  -> ft
    assert u.v('deflection', 25.4) == pytest.approx(1.0, rel=1e-3)   # mm -> in
    assert u.lab('force') == 'kip'
    assert u.title_block() == 'ft, kip, in'


def test_report_units_round_trip_through_to_storage(unit_selector):
    for key in unit_selector.ORDER:
        unit_selector.set_current(key)
        u = sr.ReportUnits()
        for quantity, value in (('length', 6.0), ('force', 250.0),
                                ('moment', 12.5), ('deflection', 3.2)):
            assert u.to_storage(quantity, u.v(quantity, value)) == \
                pytest.approx(value, rel=1e-9), (key, quantity)


def test_stress_from_kn_cm2_lands_on_the_right_unit(unit_selector):
    """|N|/A comes out of the model in kN/cm^2, while the tab stores a
    stress in MPa -- the two have to be reconciled before conversion."""
    unit_selector.set_current('cirsoc')
    assert sr.ReportUnits().stress_from_kn_cm2(1.0) == pytest.approx(10.0)
    unit_selector.set_current('aisc')
    # 1 kN/cm^2 = 10 MPa = 1.4504 ksi
    assert sr.ReportUnits().stress_from_kn_cm2(1.0) == pytest.approx(1.4504,
                                                                     rel=1e-3)


def test_the_title_block_states_the_selected_convention(unit_selector):
    nodes, members, loads, supports = _built_model()
    unit_selector.set_current('cirsoc')
    assert dict(sr._pdf_sheet_meta(nodes, members))['UNITS'] == 'm, kN, mm'
    unit_selector.set_current('aisc')
    assert dict(sr._pdf_sheet_meta(nodes, members))['UNITS'] == 'ft, kip, in'


def test_the_sheets_are_written_in_the_selected_convention(unit_selector,
                                                           tmp_path):
    """The whole point: switch the app to AISC and the PDF must not still
    say kN. Before 2026-09-27 the units were hard-coded into sixty format
    strings, so the report contradicted the screen it came from."""
    nodes, members, loads, supports, res, checks = _rigid_model()
    unit_selector.set_current('aisc')
    path = str(tmp_path / 'aisc.pdf')
    sr.export_pdf(nodes, members, loads, supports, res, path, checks=checks,
                  groups=set(sr.PDF_SHEET_GROUPS))
    text = _read_pdf_text(path)
    assert 'kip' in text
    assert 'ft, kip, in' in text
    # No line may still be written in SI -- the material unit weight
    # included, now that the app's own box follows the selector too.
    si_only = [ln for ln in text.splitlines()
               if 'kN' in ln or ' mm' in ln]
    assert si_only == [], si_only


def test_the_same_model_in_si_says_kN(unit_selector, tmp_path):
    nodes, members, loads, supports, res, checks = _rigid_model()
    unit_selector.set_current('cirsoc')
    path = str(tmp_path / 'si.pdf')
    sr.export_pdf(nodes, members, loads, supports, res, path, checks=checks)
    text = _read_pdf_text(path)
    assert 'kN' in text
    assert 'm, kN, mm' in text
    assert 'kip' not in text
    assert 'ksi' not in text


def test_a_round_scale_bar_is_round_in_the_unit_it_is_labelled_in(
        unit_selector):
    """A bar that is a round 5 m is 16.4 ft, which is not a scale bar: the
    round number has to be chosen in the unit that will be printed."""
    from common import _ensure_matplotlib
    assert _ensure_matplotlib()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    unit_selector.set_current('aisc')
    fig = plt.figure()
    ax = fig.add_subplot(111)
    try:
        u = sr.ReportUnits()
        length_m = sr._pdf_scale_bar(ax, 30.0, (0.0, 0.0), u=u)
        shown = u.v('length', length_m)
        assert round(shown, 6) in (1, 2, 5, 10, 20, 50, 100, 200), shown
        labels = [t.get_text() for t in ax.texts]
        assert any('ft' in t for t in labels)
        assert not any(t.endswith(' m') for t in labels)
    finally:
        plt.close(fig)


def test_the_storage_declaration_is_shared_with_the_tab():
    """Two copies of 'what a number in a member dict means' is exactly how
    a report starts disagreeing with the app that wrote it."""
    from apps.stereo.stereo_app import StereoApp
    assert StereoApp.STORAGE_UNITS is sr.STORAGE_UNITS


# ── serviceability, and the take-off ─────────────────────────────────────

def test_the_deflection_check_measures_against_the_span_not_the_longest_bar():
    """A serviceability limit is about how far the structure sags between
    its supports. The longest single rod in a space truss is the diagonal
    of one module; using it would make the allowance several times too
    tight and fail structures that are fine."""
    check = sr._pdf_deflection_check([10.0, 4.0], ext=(30.0, 12.0, 3.0),
                                     longest_bar_m=2.5, denom=250)
    assert check['span_m'] == pytest.approx(30.0)     # the X extent
    assert check['allow_mm'] == pytest.approx(120.0)  # 30 m / 250
    assert check['worst_mm'] == pytest.approx(10.0)
    assert check['ratio'] == pytest.approx(10.0 / 120.0)
    assert check['ok'] is True


def test_the_deflection_check_falls_back_to_the_longest_bar():
    """A lone column has no horizontal extent at all, and its longest bar
    is then the only length there is."""
    check = sr._pdf_deflection_check([3.0], ext=(0.0, 0.0, 8.0),
                                     longest_bar_m=8.0, denom=250)
    assert check['span_m'] == pytest.approx(8.0)


def test_the_deflection_check_fails_a_model_that_sags_too_far():
    check = sr._pdf_deflection_check([200.0], ext=(30.0, 12.0, 3.0),
                                     longest_bar_m=2.5, denom=250)
    assert check['ok'] is False
    assert check['ratio'] > 1.0


def test_the_deflection_check_is_skippable_and_degenerate_safe():
    assert sr._pdf_deflection_check([], (1.0, 1.0, 1.0), 1.0) is None
    assert sr._pdf_deflection_check([1.0], (0.0, 0.0, 0.0), 0.0) is None
    assert sr._pdf_deflection_check([1.0], (1.0, 1.0, 1.0), 1.0, denom=0) is None


def test_the_deformed_sheet_states_the_verdict(tmp_path):
    nodes, members, loads, supports, res, checks = _rigid_model()
    path = str(tmp_path / 'd.pdf')
    sr.export_pdf(nodes, members, loads, supports, res, path, checks=checks,
                  groups={'deformed'})
    text = _read_pdf_text(path)
    assert 'SERVICEABILITY' in text
    assert 'VERDICT' in text


def test_the_takeoff_totals_agree_with_the_self_weight_load_case():
    """The mass the report states and the weight the solver applied come
    from one unit weight, so they cannot drift apart."""
    nodes, members, loads, supports = _built_model()
    total_W_kN = sum(-ld.get('fz', 0.0)
                     for ld in sm.self_weight_loads(nodes, members))
    total_kg = total_W_kN / 9.80665 * 1000.0
    # the same arithmetic the take-off sheet does, per member
    import math
    by_hand = 0.0
    for m in members:
        L = math.dist(nodes[m['a']], nodes[m['b']])
        by_hand += (m['A'] * 1e-4 * L * sm.DEFAULT_STEEL_UNIT_WEIGHT
                    * 1000.0 / 9.80665)
    assert by_hand == pytest.approx(total_kg, rel=1e-9)


def test_the_takeoff_sheet_is_planned_with_the_tables():
    nodes, members, loads, supports, res, checks = _rigid_model()
    assert 'takeoff' in sr.plan_sheets(res, checks, len(members))
    assert 'takeoff' in sr.plan_sheets(res, checks, 0, {'tables'})
    assert 'takeoff' not in sr.plan_sheets(res, checks, 0, {'force'})


def test_the_takeoff_sheet_reports_a_mass(tmp_path):
    nodes, members, loads, supports, res, checks = _rigid_model()
    path = str(tmp_path / 't.pdf')
    sr.export_pdf(nodes, members, loads, supports, res, path, checks=checks,
                  groups={'tables'})
    text = _read_pdf_text(path)
    assert 'take-off' in text
    assert 'tonnes' in text


def test_a_model_with_timber_gets_a_material_takeoff_at_its_own_density(
        tmp_path):
    """Timber rods (stereo_timber) weigh their grade's density, not the
    steel unit weight, and the sheet stops calling itself a steel take-off."""
    from apps.stereo import stereo_timber as stt
    from apps.stereo import stereo_profiles as sp
    nodes, members, loads, supports, res, checks = _rigid_model()
    steel = str(tmp_path / 's.pdf')
    sr.export_pdf(nodes, members, loads, supports, res, steel, checks=checks,
                  groups={'tables'})
    assert 'Steel take-off' in _read_pdf_text(steel)
    sp.write_section(members[0], stt.profile('Eucalipto grandis C1', 50, 150))
    members[0]['profile'] = 'EG 50x150'
    path = str(tmp_path / 't.pdf')
    sr.export_pdf(nodes, members, loads, supports, res, path, checks=checks,
                  groups={'tables'})
    text = _read_pdf_text(path)
    assert 'Material take-off' in text and 'Steel take-off' not in text
    assert '1 timber bar(s)' in text
    import math
    m = members[0]
    kg = 75e-4 * math.dist(nodes[m['a']], nodes[m['b']]) * 430.0
    assert f'{kg:,.1f}' in text


def test_a_table_note_too_long_for_one_line_wraps_instead_of_running_off():
    """Text that runs past the paper's edge is not clipped with a mark --
    it simply stops, and the sentence that fell off is invisible."""
    fig, _ = _diagram_axes()
    import matplotlib.pyplot as plt
    plt.close(fig)
    fig = plt.figure(figsize=sr.PDF_SHEET_IN)
    try:
        note = 'word ' * 120
        ax = sr._pdf_table_page(fig, 'T', ['a'], [['1']], [1.0], note=note)
        note_lines = [t for t in ax.texts if t.get_text().startswith('word')]
        assert len(note_lines) > 1
        for t in note_lines:
            assert len(t.get_text()) <= sr.PDF_TABLE_NOTE_CHARS
    finally:
        plt.close(fig)


def test_the_takeoff_quotes_the_unit_weight_in_the_selected_units(
        unit_selector, tmp_path):
    """The material unit weight follows the selector, like the box it was
    typed into (which now does too). It used to be quoted in kN/m³ under
    every convention, on the grounds that the box said kN/m³ -- true, and
    the fix was to make both follow the selector rather than neither.

    Mass is still kg and tonnes: there is no mass in units.QUANTITIES, and
    the sheet's note says it is not a converted quantity.
    """
    nodes, members, loads, supports, res, checks = _rigid_model()
    unit_selector.set_current('aisc')
    path = str(tmp_path / 'takeoff.pdf')
    sr.export_pdf(nodes, members, loads, supports, res, path, checks=checks,
                  groups={'tables'})
    text = _read_pdf_text(path)
    assert 'kN/m³' not in text
    assert '499.7 pcf' in text      # 78.5 kN/m³, the default, in lbf/ft³
    assert 'mass (kg)' in text      # not a converted quantity
    assert 'tonnes' in text
    assert 'not a converted quantity' in text   # and the sheet says so
    # everything the selector DOES cover still followed it
    assert 'total L (ft)' in text
    assert 'A (in²)' in text


# ── the Member Calculations sheet has to stay openable ──────────────────────

def _mesh_model(span, module):
    """A grid with a chosen number of rods, using this file's own generator
    (sg.flat_grid) rather than a name that does not exist on the module."""
    mesh = sg.flat_grid(span_x=span, span_y=span, depth=1.0, module=module,
                        offset=True)
    nodes, members = mesh['nodes'], mesh['members']
    for m in members:
        m.update(E=200.0, A=15.0, I=400.0, J=400.0, Fy=250.0, Fu=400.0,
                 r_gyr=2.5, K=1.0)
    supports = [{'node': i, 'type': 'pin'} for i in mesh['support_candidates']]
    loads = sm.self_weight_loads(nodes, members)
    return nodes, members, loads, supports


def _grid_model():
    """Comfortably past DEFAULT_MAX_CALC_MEMBERS."""
    return _mesh_model(span=12.0, module=2.0)


def _image_count(path):
    import zipfile
    with zipfile.ZipFile(path) as z:
        return sum(1 for n in z.namelist() if n.startswith('xl/media/'))


def test_the_member_calculations_sheet_is_capped_by_default(tmp_path):
    """Three rendered PNGs per member: on the default grid that was 2,400
    images and a 20 MB workbook, which is slow to open and can defeat Excel
    outright. The cap already existed as a parameter and nothing passed it.
    """
    nodes, members, loads, supports = _grid_model()
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None
    out = tmp_path / 'capped.xlsx'
    sr.export_excel(nodes, members, loads, supports, res, str(out))
    imgs = _image_count(str(out))
    assert len(members) > sr.DEFAULT_MAX_CALC_MEMBERS, 'need a model past the cap'
    assert imgs == 3 * sr.DEFAULT_MAX_CALC_MEMBERS, imgs
    assert out.stat().st_size < 6_000_000, out.stat().st_size


def test_passing_none_still_renders_every_member(tmp_path):
    """The cap is a default, not a ceiling -- a caller that wants the lot
    still gets it."""
    nodes, members, loads, supports = _grid_model()
    res, _err = sm.analyze(nodes, members, loads, supports)
    out = tmp_path / 'everything.xlsx'
    sr.export_excel(nodes, members, loads, supports, res, str(out),
                    max_calc_members=None)
    assert _image_count(str(out)) == 3 * len(members)


def test_the_sheet_says_it_is_showing_only_the_worst(tmp_path):
    """A shortened sheet that does not say so reads as "these are all the
    rods", which is worse than the long file."""
    from openpyxl import load_workbook
    nodes, members, loads, supports = _grid_model()
    res, _err = sm.analyze(nodes, members, loads, supports)
    out = tmp_path / 'noted.xlsx'
    sr.export_excel(nodes, members, loads, supports, res, str(out))
    wb = load_workbook(str(out))
    note = str(wb['Member Calculations'].cell(row=2, column=1).value)
    assert str(sr.DEFAULT_MAX_CALC_MEMBERS) in note
    assert str(len(members)) in note
    assert 'most utilized' in note
    # And it points at the sheets that DO cover every rod.
    assert 'Member Forces' in note and 'Member Checks' in note


def test_a_model_under_the_cap_gets_no_note_and_every_member(tmp_path):
    from openpyxl import load_workbook
    nodes, members, loads, supports = _mesh_model(span=6.0, module=3.0)
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None
    assert len(members) <= sr.DEFAULT_MAX_CALC_MEMBERS
    out = tmp_path / 'small.xlsx'
    sr.export_excel(nodes, members, loads, supports, res, str(out))
    assert _image_count(str(out)) == 3 * len(members)
    wb = load_workbook(str(out))
    note = str(wb['Member Calculations'].cell(row=2, column=1).value)
    assert 'most utilized' not in note


# ── the workbook follows the selector too ─────────────────────────────────

def _xl_export(tmp_path, name='w.xlsx'):
    import openpyxl
    nodes, members, loads, supports, res, checks = _rigid_model()
    path = str(tmp_path / name)
    sr.export_excel(nodes, members, loads, supports, res, path, checks=checks,
                    max_calc_members=2)
    return openpyxl.load_workbook(path), (nodes, members, loads, supports,
                                          res, checks), path


def _hdrs(ws):
    return [c.value for c in ws[1]]


def test_under_si_the_workbook_is_exactly_as_it_was(tmp_path):
    wb, (nodes, members, loads, supports, res, checks), _p = _xl_export(tmp_path)
    assert _hdrs(wb['Member Forces'])[4] == 'N_kN'
    assert _hdrs(wb['Nodes']) == ['idx', 'x_m', 'y_m', 'z_m']
    assert wb['Member Forces'].cell(row=2, column=5).value == \
        pytest.approx(res['member_res'][0]['N'])


def test_under_aisc_the_readable_sheets_are_in_us_units(unit_selector,
                                                        tmp_path):
    unit_selector.set_current('aisc')
    wb, (nodes, members, loads, supports, res, checks), _p = _xl_export(tmp_path)
    mf = wb['Member Forces']
    assert _hdrs(mf)[4:6] == ['N_kip', 'length_ft']
    assert mf.cell(row=2, column=5).value == pytest.approx(
        res['member_res'][0]['N'] * 0.224809, rel=1e-4)
    assert _hdrs(wb['Nodes']) == ['idx', 'x_ft', 'y_ft', 'z_ft']
    np_ = _hdrs(wb['Node Properties'])
    assert 'ux_in' in np_ and 'Mz_kipft' in np_ and 'rx_rad' in np_
    mem = _hdrs(wb['Members'])
    assert 'E_ksi' in mem and 'A_in²' in mem and 'r_gyr_in' in mem
    assert 'slenderness' in _hdrs(wb['Member Checks'])
    summary = {r[0]: r[1] for r in wb['Summary'].iter_rows(values_only=True)
               if r and r[0]}
    assert 'Max tension (kip)' in summary
    assert 'ft, kip, in' in summary['Units']


def test_the_model_sheet_stays_in_stored_units_so_import_is_exact(
        unit_selector, tmp_path):
    """Import reads the Model sheet by its headers. A US workbook must still
    bring back the same model, not one scaled by 0.2248."""
    unit_selector.set_current('aisc')
    wb, (nodes, members, loads, supports, res, checks), path = \
        _xl_export(tmp_path)
    n2, m2, l2, s2, _p = sr.import_excel_model(path)
    assert n2 == [tuple(p) for p in nodes]
    assert m2[0]['A'] == pytest.approx(members[0]['A'])
    assert m2[0]['E'] == pytest.approx(members[0]['E'])
    assert sum(ld['fz'] for ld in l2) == pytest.approx(
        sum(ld.get('fz', 0.0) for ld in loads))


def test_a_mixed_convention_converts_only_what_differs(unit_selector,
                                                        tmp_path):
    """CSA keeps kN and m but writes sections in mm: only those columns move."""
    unit_selector.set_current('csa')
    wb, (nodes, members, *_rest), _p = _xl_export(tmp_path)
    mem = _hdrs(wb['Members'])
    assert 'A_mm²' in mem and 'E_MPa' in mem
    assert _hdrs(wb['Member Forces'])[4] == 'N_kN'
    col = mem.index('A_mm²') + 1
    assert wb['Members'].cell(row=2, column=col).value == pytest.approx(
        members[0]['A'] * 100.0)


def test_every_pictured_rod_has_its_data_beside_it(tmp_path):
    """Roadmap 2.4: the free-body pictures "next to their data"."""
    wb, (nodes, members, loads, supports, res, checks), _p = _xl_export(tmp_path)
    ws = wb['Member Calculations']
    labels = [c.value for c in ws['V'] if c.value]
    assert labels.count('Data') == 2, 'one panel per pictured rod (cap 2)'
    for lbl in ('Section', 'L', 'KL/r', 'N', 'Utilisation', 'Governs'):
        assert lbl in labels, lbl
    values = [c.value for c in ws['W'] if c.value]
    assert any(v.endswith(' m') for v in values)
    assert any(('OK' in v or 'OVER' in v) for v in values)


def test_the_data_panel_follows_the_selector(unit_selector):
    unit_selector.set_current('aisc')
    nodes, members, loads, supports, res, checks = _rigid_model()
    rows = dict(sr.member_data_rows(members[0], res['member_res'][0],
                                    checks[0], sr.ReportUnits()))
    assert rows['L'].endswith(' ft')
    assert 'kip' in rows['N'] and 'kip·ft' in rows['M max']
    assert rows['r min'].endswith(' in')


def test_the_data_panel_leaves_out_what_was_not_computed():
    rows = dict(sr.member_data_rows(
        {'profile': 'X', 'A': 10.0, 'r_gyr': 2.0, 'K': 1.0},
        {'N': 0.0, 'length_m': 2.0}, None, sr.ReportUnits()))
    assert 'V max' not in rows and 'M max' not in rows
    assert 'Utilisation' not in rows
    assert rows['KL/r'] == '100'
    assert rows['N'].endswith('(zero)')


# ── the drawing scale on the sheet ─────────────────────────────────────────

def _fit_axes():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=sr.PDF_SHEET_IN)
    return fig, sr._pdf_view_axes(fig)


def _square(n=11, step=3.0):
    return [(i * step, j * step) for i in range(n) for j in range(n)]


def test_the_fit_uses_the_middle_of_the_sheet_the_panels_leave_free():
    """A square plan used to get the band between the top panels and the
    bottom furniture -- a third of the height. Clear of the panels'
    RECTANGLES it is far larger, and still never under one."""
    import matplotlib.pyplot as plt
    fig, ax = _fit_axes()
    try:
        pts = _square()
        obstacles = [(0.0, 0.80, 0.30, 1.0), (0.75, 0.70, 1.0, 1.0),
                     (0.0, 0.0, 0.42, 0.16), (0.78, 0.0, 1.0, 0.24)]
        old = sr._pdf_fit_window(ax, pts, reserve_top=0.30,
                                 reserve_bottom=0.26)
        new = sr._pdf_fit_window_clear(ax, pts, obstacles,
                                       legacy_reserve_top=0.30,
                                       legacy_reserve_bottom=0.26)
        old_w, new_w = old[2] - old[0], new[2] - new[0]
        assert new_w < 0.75 * old_w, 'the drawing should be much larger'
        x0, y0, x1, y1 = new
        for px, py in pts:
            u, v = (px - x0) / (x1 - x0), (py - y0) / (y1 - y0)
            for a0, b0, a1, b1 in obstacles:
                assert not (a0 <= u <= a1 and b0 <= v <= b1)
    finally:
        plt.close(fig)


def test_zoom_and_true_scale():
    import matplotlib.pyplot as plt
    fig, ax = _fit_axes()
    try:
        pts = _square()
        fit = sr._pdf_fit_window_clear(ax, pts, [])
        zoomed = sr._pdf_fit_window_clear(ax, pts, [], zoom=1.5)
        assert (zoomed[2] - zoomed[0]) == pytest.approx(
            (fit[2] - fit[0]) / 1.5)
        w_in, _h = sr._pdf_axes_size_in(ax)
        true = sr._pdf_fit_window_clear(ax, pts, [], ratio=200)
        # 1:200 -- 200 m of structure per metre of paper
        assert (true[2] - true[0]) == pytest.approx(200 * 0.0254 * w_in)
    finally:
        plt.close(fig)


def test_export_pdf_takes_the_scale_and_puts_the_default_back(tmp_path):
    nodes, members, loads, supports, res, checks = _rigid_model()
    path = str(tmp_path / 's.pdf')
    sr.export_pdf(nodes, members, loads, supports, res, path, checks=checks,
                  groups={'views'}, view_zoom=1.3, view_ratio=None)
    assert sr._PDF_VIEW == sr.PDF_VIEW_DEFAULT
    sr.export_pdf(nodes, members, loads, supports, res, path, checks=checks,
                  groups={'views'}, view_ratio=100)
    assert sr._PDF_VIEW == sr.PDF_VIEW_DEFAULT


# ── Moment and shear along the rods, as the canvas colours them ────────────

def test_rod_layers_split_a_two_layer_grid_by_role():
    members = [{'a': 0, 'b': 1, 'role': 'top_chord'},
               {'a': 1, 'b': 2, 'role': 'bottom_chord'},
               {'a': 2, 'b': 3, 'role': 'web'},
               {'a': 3, 'b': 4, 'role': 'outer_rib'},
               {'a': 4, 'b': 5}]
    layers = sr.rod_layers(members)
    assert [(k, ids) for k, _t, ids in layers] == [
        ('top', [0, 3]), ('bottom', [1]), ('webs', [2, 4])]
    # only the rods asked about
    assert [k for k, _t, _i in sr.rod_layers(members, [2, 4])] == ['all']


def test_rod_layers_fall_back_to_one_layer_without_chord_roles():
    members = [{'a': 0, 'b': 1}, {'a': 1, 'b': 2, 'role': 'web'}]
    assert sr.rod_layers(members) == [('all', 'all rods', [0, 1])]
    assert sr.rod_layers([]) == []


def test_plan_sheets_has_a_plan_per_rod_layer_when_given_the_members():
    nodes, members, loads, supports, res, checks = _rigid_model()
    roles = ['top_chord', 'bottom_chord', 'web']
    for i, m in enumerate(members):
        m['role'] = roles[i % 3]
    plan = sr.plan_sheets(res, checks, len(members), members=members)
    i = plan.index('moment_rods')
    assert plan[i:i + 8] == [
        'moment_rods', 'moment_rods_plan_top', 'moment_rods_plan_bottom',
        'moment_rods_plan_webs',
        'shear_rods', 'shear_rods_plan_top', 'shear_rods_plan_bottom',
        'shear_rods_plan_webs']
    # and the document holds exactly the sheets the plan promises
    assert plan == sr.report_plan(members, res, checks)


def test_the_paper_colours_by_the_screens_own_value():
    """The point of the sheet: it shows what the canvas shows. Same signed
    value at every station, same ramp, same anchor."""
    from apps.stereo.stereo_app_render import StereoRenderMixin as RenderMixin
    nodes, members, loads, supports, res, checks = _rigid_model()
    for mr in res['member_res'][:20]:
        for t in (0.0, 0.3, 0.5, 1.0):
            for shear in (False, True):
                assert sr.rod_field_value(mr, t, shear) == pytest.approx(
                    RenderMixin._rod_field_value(mr, t, shear), abs=1e-12)


def test_the_rod_field_draws_each_rigid_rod_in_stretches():
    from apps.stereo.stereo_app_colors import moment_color
    fig, ax = _diagram_axes()
    try:
        members = [{'a': 0, 'b': 1}, {'a': 2, 'b': 3}, {'a': 0, 'b': 2}]
        pts = [(0.0, 0.0), (10.0, 0.0), (4.0, 4.0), (4.0, 4.0)]
        mres = [{'conn': 'rigid', 'length_m': 3.0, 'Mz_a': 2.0, 'Vy_a': 1.0},
                {'conn': 'rigid', 'length_m': 3.0, 'Mz_a': 1.0},
                {'conn': 'pin', 'length_m': 3.0}]
        drawn, flat = sr._pdf_rod_field(ax, members, pts, mres, False,
                                         anchor=2.0, samples=4)
        assert (drawn, flat) == (1, 1)       # the pin and the point skip
        lc = ax.collections[-1]
        assert len(lc.get_segments()) == 4
        # first stretch: the moment at its middle, t = 1/8
        want = moment_color(sr.rod_field_value(mres[0], 0.125, False), 2.0)
        got = lc.get_colors()[0][:3]
        assert tuple(round(c, 3) for c in got) == tuple(
            round(c, 3) for c in sr._hex_to_rgb(want))
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)


def test_the_moment_sheets_tag_the_rods_carrying_the_most(tmp_path):
    nodes, members, loads, supports, res, checks = _rigid_model()
    ranked = sr.rod_peaks(res['member_res'], range(len(members)), False)
    assert ranked == sorted(ranked, key=lambda r: -r[0])
    assert ranked[0][0] == pytest.approx(max(
        sm.member_peak_actions(mr, sr.PDF_DIAGRAM_SAMPLES)['M_max']
        for mr in res['member_res']))
    path = str(tmp_path / 'm.pdf')
    sr.export_pdf(nodes, members, loads, supports, res, path, checks=checks,
                  groups={'moment'})
    assert _pdf_page_count(path) == len(sr.plan_sheets(
        res, checks, len(members), {'moment'}, members=members))


def test_the_fit_moves_the_drawing_off_centre_to_grow_it():
    """A wide key across the top-left used to cap a square plan at the
    size that kept it centred; the drawing may now sit lower and right."""
    fig, ax = _diagram_axes()
    try:
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        key = [(0.0, 0.62, 0.55, 1.0)]
        x0, y0, x1, y1 = sr._pdf_fit_window_clear(ax, pts, key)
        tall = 10.0 / (y1 - y0)            # share of the axes height
        # held at the centre, the square could only reach up to the key's
        # bottom edge: 2 * (0.62 - centre) of the height, under 0.25
        assert tall > 0.5
        # it got there by moving right, beside the key
        assert (5.0 - x0) / (x1 - x0) > 0.55
        # and it is clear of the key
        for px, py in pts:
            u = (px - x0) / (x1 - x0)
            v = (py - y0) / (y1 - y0)
            assert not (u <= 0.55 + sr.PDF_FIT_PAD and v >= 0.62 - sr.PDF_FIT_PAD)
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)


# ── The orientation indicator ──────────────────────────────────────────────

def test_round_down_keeps_most_of_the_length():
    assert sr._pdf_round_down(3.7) == 3.0
    assert sr._pdf_round_down(2.6) == 2.5
    assert sr._pdf_round_down(0.47) == 0.4
    assert sr._pdf_round_down(12.0) == 12.0
    for bad in (0.0, -1.0, float('nan'), float('inf'), None):
        assert sr._pdf_round_down(bad) == 0.0
    for raw in (0.13, 1.7, 9.9, 42.0, 777.0):
        assert 0.74 * raw <= sr._pdf_round_down(raw) <= raw   # 6 of 8


def test_the_triad_is_sized_to_the_paper_not_the_model():
    """A large grid drawn large used to get a triad a few millimetres
    across: the arm was capped at 16% of the model's span. It fills its
    corner whatever the model."""
    import math
    nodes, members, loads, supports = _built_model()
    big = [(x * 20.0, y * 20.0, z * 20.0) for x, y, z in nodes]
    for pts in (nodes, big):
        fig, ax = _diagram_axes()
        try:
            az, el = math.radians(30.0), math.radians(25.0)
            proj = [sr._pdf_project(x, y, z, az, el) for x, y, z in pts]
            win, _s, arm, _g = sr._pdf_furnish(ax, pts, proj, az, el,
                                               obstacles=[])
            h = win[3] - win[1]
            longest = max(sr._pdf_foreshortening(az, el).values())
            drawn = arm * longest / h        # the longest arm, as a share
            assert 0.74 * sr.PDF_TRIAD_ARM_MAX <= drawn <= \
                sr.PDF_TRIAD_ARM_MAX + 1e-9
        finally:
            import matplotlib.pyplot as plt
            plt.close(fig)


def test_triad_labels_sit_outside_their_arrow_tips():
    import math
    fig, ax = _diagram_axes()
    try:
        az, el = math.radians(30.0), math.radians(25.0)
        ax.set_xlim(-5, 5)
        ax.set_ylim(-5, 5)
        sr._pdf_orientation_triad(ax, az, el, 2.0, (0.0, 0.0))
        dirs = sr._pdf_axis_dirs(az, el)
        labels = {t.get_text().split()[0]: t for t in ax.texts
                  if t.get_text().split() and
                  t.get_text().split()[0] in ('X', 'Y', 'Z')}
        assert set(labels) == {'X', 'Y', 'Z'}
        for name, t in labels.items():
            dx, dy = dirs[name]
            tip = (dx * 2.0, dy * 2.0)
            assert t.xy == pytest.approx(tip)
            ox, oy = t.get_position()          # offset, in points
            # pushed further along its own arm, never back toward the origin
            assert ox * dx + oy * dy > 0
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)


def test_a_crane_sheet_names_only_its_own_crane():
    """Fifteen crane codes on the sheet for one lift hid the one it is
    about: the crane sheet labels its own code alone."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    nodes = [(0, 0, 0), (1, 0, 1), (5, 0, 0), (6, 0, 1)]
    members = [{'a': 0, 'b': 1, 'addon': 'K1', 'role': 'crane_cable'},
               {'a': 2, 'b': 3, 'addon': 'K2', 'role': 'crane_cable'}]
    proj = [(x, z) for x, _y, z in nodes]
    fig = plt.figure()
    ax = fig.add_subplot(111)
    assert sr._pdf_addon_codes(ax, nodes, members, proj) == ['K1', 'K2']
    assert sr._pdf_addon_codes(ax, nodes, members, proj,
                               only={'K2'}) == ['K2']
    plt.close(fig)
