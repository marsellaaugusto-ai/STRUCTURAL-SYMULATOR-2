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
        # 1 general + 5 orthographic + 4 analysis + 2 tables, and one more
        # analysis sheet when the members carry a checkable section
        assert _pdf_page_count(with_checks) == 12
        assert _pdf_page_count(without) == 11


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
        # 1 general + 5 orthographic + 4 analysis + 2 tables
        assert _pdf_page_count(full) == 12
        assert _pdf_page_count(short) == 7
        assert _pdf_page_count(full) - _pdf_page_count(short) == 5


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
        assert _pdf_page_count(path) == 11   # no checks -> no utilisation sheet


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
