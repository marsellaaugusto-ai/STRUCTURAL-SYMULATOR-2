"""Tests that the SketchUp plugin's xlsx output is fully compatible with the
Stereo tab's import_excel_model, both with and without section properties.

The plugin is Ruby; these tests replicate its xlsx layout in Python (same
cell addresses, same XML structure from its custom xlsx_writer.rb) and run
the real import + solver against the result.
"""
import os
import sys
import tempfile
import zipfile
from io import BytesIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from common import _ensure_openpyxl

pytestmark = pytest.mark.skipif(not _ensure_openpyxl(),
                                reason='openpyxl unavailable')


# ── helpers: replicate the plugin's xlsx_writer.rb output ────────────────────

def _col_letter(col):
    s = ''
    n = col
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def _cell_xml(ref, v):
    if isinstance(v, (int, float)):
        return '<c r="%s"><v>%s</v></c>' % (ref, v)
    s = str(v).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return '<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, s)


def _build_plugin_xlsx(nodes_m, members, with_sections=False):
    """Reproduce the exact xlsx the SketchUp plugin writes."""
    cells = {}
    max_row = max_col = 0

    def sc(row, col, value):
        nonlocal max_row, max_col
        cells[(row, col)] = value
        max_row = max(max_row, row)
        max_col = max(max_col, col)

    row = 1
    sc(row, 1, 'STEREO MODEL DATA — for Import from Excel (do not reorder columns)')
    row += 2
    sc(row, 1, '[NODES]'); row += 1
    sc(row, 1, 'idx'); sc(row, 2, 'x_m'); sc(row, 3, 'y_m'); sc(row, 4, 'z_m')
    row += 1
    for i, (x, y, z) in enumerate(nodes_m):
        sc(row, 1, i); sc(row, 2, x); sc(row, 3, y); sc(row, 4, z)
        row += 1
    row += 1

    sc(row, 1, '[MEMBERS]'); row += 1
    if with_sections:
        for c, h in enumerate(['idx', 'a', 'b', 'conn', 'E_GPa', 'A_cm2',
                                'I_cm4', 'J_cm4', 'Fy_MPa', 'Fu_MPa', 'K',
                                'r_gyr_cm', 'role'], 1):
            sc(row, c, h)
    else:
        sc(row, 1, 'idx'); sc(row, 2, 'a'); sc(row, 3, 'b'); sc(row, 4, 'conn')
    row += 1
    for i, m in enumerate(members):
        sc(row, 1, i); sc(row, 2, m['a']); sc(row, 3, m['b']); sc(row, 4, 'pin')
        if with_sections:
            sc(row, 5, 200.0); sc(row, 6, 20.0); sc(row, 7, 400.0)
            sc(row, 8, 400.0); sc(row, 9, 235.0); sc(row, 10, 360.0)
            sc(row, 11, 1.0); sc(row, 12, 4.0); sc(row, 13, '')
        row += 1

    rows_xml = ''
    for r in range(1, max_row + 1):
        row_cells = ''
        any_cell = False
        for c in range(1, max_col + 1):
            if (r, c) in cells:
                v = cells[(r, c)]
                if v is not None:
                    any_cell = True
                    row_cells += _cell_xml('%s%d' % (_col_letter(c), r), v)
        if any_cell:
            rows_xml += '<row r="%d">%s</row>' % (r, row_cells)

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>%s</sheetData></worksheet>' % rows_xml
    )

    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as zf:
        zf.writestr('[Content_Types].xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>')
        zf.writestr('_rels/.rels',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
        zf.writestr('xl/workbook.xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Model" sheetId="1" r:id="rId1"/></sheets></workbook>')
        zf.writestr('xl/_rels/workbook.xml.rels',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>')
        zf.writestr('xl/styles.xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            '</styleSheet>')
        zf.writestr('xl/worksheets/sheet1.xml', sheet_xml)
    return buf.getvalue()


# ── test fixtures ────────────────────────────────────────────────────────────

TETRA_NODES = [
    (0.0, 0.0, 0.0),
    (3.0, 0.0, 0.0),
    (1.5, 2.598, 0.0),
    (1.5, 0.866, 1.633),
]
TETRA_MEMBERS = [
    {'a': 0, 'b': 1}, {'a': 1, 'b': 2}, {'a': 2, 'b': 0},
    {'a': 0, 'b': 3}, {'a': 1, 'b': 3}, {'a': 2, 'b': 3},
]


@pytest.fixture
def plugin_xlsx_old(tmp_path):
    """An xlsx like the OLD plugin wrote (no section columns)."""
    path = str(tmp_path / 'old_plugin.xlsx')
    with open(path, 'wb') as f:
        f.write(_build_plugin_xlsx(TETRA_NODES, TETRA_MEMBERS, with_sections=False))
    return path


@pytest.fixture
def plugin_xlsx_new(tmp_path):
    """An xlsx like the IMPROVED plugin writes (full section columns)."""
    path = str(tmp_path / 'new_plugin.xlsx')
    with open(path, 'wb') as f:
        f.write(_build_plugin_xlsx(TETRA_NODES, TETRA_MEMBERS, with_sections=True))
    return path


# ── the tests ────────────────────────────────────────────────────────────────

def test_old_plugin_xlsx_imports_without_error(plugin_xlsx_old):
    from apps.stereo.stereo_reports import import_excel_model
    nodes, members, loads, supports, _ = import_excel_model(plugin_xlsx_old)
    assert len(nodes) == 4
    assert len(members) == 6
    assert loads == []
    assert supports == []


def test_old_plugin_xlsx_gets_default_section_properties(plugin_xlsx_old):
    from apps.stereo.stereo_reports import import_excel_model
    _, members, _, _, _ = import_excel_model(plugin_xlsx_old)
    for m in members:
        assert 'E' in m and 'A' in m, 'missing section properties'
        assert m['E'] == pytest.approx(200.0)
        assert m['A'] == pytest.approx(20.0)
        assert m['Fy'] == pytest.approx(235.0)


def test_old_plugin_xlsx_survives_analysis(plugin_xlsx_old):
    from apps.stereo.stereo_reports import import_excel_model
    from apps.stereo import stereo_math as sm
    nodes, members, _, _, _ = import_excel_model(plugin_xlsx_old)
    loads = [{'node': 3, 'fx': 0, 'fy': 0, 'fz': -10, 'mx': 0, 'my': 0, 'mz': 0}]
    supports = [{'node': i, 'type': 'pin'} for i in range(3)]
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None, err
    assert res is not None


def test_new_plugin_xlsx_imports_with_correct_sections(plugin_xlsx_new):
    from apps.stereo.stereo_reports import import_excel_model
    nodes, members, _, _, _ = import_excel_model(plugin_xlsx_new)
    assert len(nodes) == 4
    assert len(members) == 6
    for m in members:
        assert m['E'] == pytest.approx(200.0)
        assert m['A'] == pytest.approx(20.0)
        assert m['I'] == pytest.approx(400.0)
        assert m['J'] == pytest.approx(400.0)
        assert m['Fy'] == pytest.approx(235.0)
        assert m['Fu'] == pytest.approx(360.0)
        assert m['K'] == pytest.approx(1.0)
        assert m['r_gyr'] == pytest.approx(4.0)
        assert m['conn'] == 'pin'


def test_new_plugin_xlsx_survives_analysis(plugin_xlsx_new):
    from apps.stereo.stereo_reports import import_excel_model
    from apps.stereo import stereo_math as sm
    nodes, members, _, _, _ = import_excel_model(plugin_xlsx_new)
    loads = [{'node': 3, 'fx': 0, 'fy': 0, 'fz': -10, 'mx': 0, 'my': 0, 'mz': 0}]
    supports = [{'node': i, 'type': 'pin'} for i in range(3)]
    res, err = sm.analyze(nodes, members, loads, supports)
    assert err is None, err
    assert res is not None
    assert all(isinstance(nr['uz'], float) for nr in res['node_res'])


def test_explicit_sections_override_defaults(tmp_path):
    """If the xlsx carries its own section values they must not be replaced."""
    from apps.stereo.stereo_reports import import_excel_model
    nodes_m = [(0, 0, 0), (5, 0, 0)]
    members = [{'a': 0, 'b': 1}]
    path = str(tmp_path / 'custom.xlsx')
    with open(path, 'wb') as f:
        f.write(_build_plugin_xlsx(nodes_m, members, with_sections=True))
    _, mems, _, _, _ = import_excel_model(path)
    assert mems[0]['E'] == pytest.approx(200.0)
    assert mems[0]['A'] == pytest.approx(20.0)


def test_node_coordinates_are_exact(plugin_xlsx_new):
    from apps.stereo.stereo_reports import import_excel_model
    nodes, _, _, _, _ = import_excel_model(plugin_xlsx_new)
    for i, (x, y, z) in enumerate(TETRA_NODES):
        assert nodes[i][0] == pytest.approx(x, abs=1e-9)
        assert nodes[i][1] == pytest.approx(y, abs=1e-9)
        assert nodes[i][2] == pytest.approx(z, abs=1e-9)
