"""The diagnostic that finds workbooks whose group facts were dropped.

It tells three cases apart, and the middle one is the whole point: a file
with a Scene sheet and no group facts at all is one that MAY have been
imported and re-saved while the Scene sheet was overriding the Groups
sheet without carrying what it said. Only the person who drew it knows
whether it should have had excluded groups, so the tool points rather than
decides.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from apps.stereo import stereo_autogroup as ag
from apps.stereo import stereo_geometry as sg
from apps.stereo import stereo_reports as sr
from apps.stereo import stereo_scene_bridge as sbr
from common import _ensure_openpyxl

pytestmark = pytest.mark.skipif(not _ensure_openpyxl(),
                                reason='openpyxl unavailable')


def _model():
    mesh = sg.flat_grid(span_x=12.0, span_y=9.0, depth=1.0, module=3.0,
                        offset=True)
    nodes, members = mesh['nodes'], mesh['members']
    for m in members:
        m.setdefault('E', 200.0)
        m.setdefault('A', 20.0)
        m.setdefault('conn', 'pin')
    return nodes, members, ag.auto_groups(nodes, members)


def _write(path, groups=None, scene=False, mark=None):
    nodes, members, auto = _model()
    use = auto if groups is None else groups
    if mark and use:
        use[0].update(mark)
    doc = sbr.graph_from_model(nodes, members, use) if scene else None
    sr.export_excel(nodes, members, [], [], None, path, groups=use,
                    scene=doc)
    return use[0]['name'] if use else None


def look(path):
    import check_excluded_groups as chk
    return chk.look(path)


def test_a_file_with_no_groups_has_nothing_to_lose(tmp_path):
    path = str(tmp_path / 'bare.xlsx')
    _write(path, groups=[])
    assert look(path)[0] == 'no groups'


def test_a_file_with_no_scene_sheet_was_never_at_risk(tmp_path):
    """The Groups sheet was always read for these, so whatever it says is
    what the model had."""
    path = str(tmp_path / 'groups_only.xlsx')
    name = _write(path, scene=False, mark={'excluded': True})
    verdict, detail = look(path)
    assert verdict == 'ok'
    assert 'no Scene sheet' in detail
    assert name in detail


def test_a_file_that_still_carries_its_flags_is_fine(tmp_path):
    path = str(tmp_path / 'both.xlsx')
    name = _write(path, scene=True, mark={'excluded': True})
    verdict, detail = look(path)
    assert verdict == 'ok'
    assert 'excluded' in detail and name in detail


def test_a_scene_sheet_with_no_flags_at_all_is_flagged_for_a_look(tmp_path):
    """The signature of a file imported and re-saved while the facts were
    being dropped. It may simply never have had any -- which is why the
    tool says to look rather than that something is wrong."""
    path = str(tmp_path / 'suspect.xlsx')
    _write(path, scene=True, mark=None)
    verdict, detail = look(path)
    assert verdict == 'check'
    assert 'lost' in detail


@pytest.mark.parametrize('flag,value', [
    ('excluded', True), ('iteration', '2'), ('stage', 'lift'),
    ('position', 'north'), ('component', 'Bay A'),
])
def test_any_one_fact_is_enough_to_clear_a_file(tmp_path, flag, value):
    path = str(tmp_path / ('one_%s.xlsx' % flag))
    _write(path, scene=True, mark={flag: value})
    assert look(path)[0] == 'ok'


def test_an_unreadable_file_is_reported_not_raised(tmp_path):
    path = str(tmp_path / 'junk.xlsx')
    with open(path, 'wb') as fh:
        fh.write(b'not a workbook')
    assert look(path)[0] == 'unreadable'


def test_it_walks_a_folder_and_changes_nothing(tmp_path):
    import check_excluded_groups as chk
    _write(str(tmp_path / 'a.xlsx'), scene=True, mark={'excluded': True})
    _write(str(tmp_path / 'b.xlsx'), scene=True, mark=None)
    before = {p: os.path.getmtime(os.path.join(str(tmp_path), p))
              for p in os.listdir(str(tmp_path))}
    found = sorted(os.path.basename(p)
                   for p in chk.workbooks([str(tmp_path)]))
    assert found == ['a.xlsx', 'b.xlsx']
    assert chk.main(['check', str(tmp_path)]) == 1, 'b.xlsx is worth a look'
    after = {p: os.path.getmtime(os.path.join(str(tmp_path), p))
             for p in os.listdir(str(tmp_path))}
    assert after == before, 'it is read-only'


def test_excel_lock_files_are_skipped(tmp_path):
    """~$name.xlsx is Excel's own lock file, not a model."""
    import check_excluded_groups as chk
    _write(str(tmp_path / 'a.xlsx'), scene=True)
    with open(str(tmp_path / '~$a.xlsx'), 'wb') as fh:
        fh.write(b'lock')
    found = [os.path.basename(p) for p in chk.workbooks([str(tmp_path)])]
    assert found == ['a.xlsx']


def test_a_clean_folder_reports_success(tmp_path):
    import check_excluded_groups as chk
    _write(str(tmp_path / 'a.xlsx'), scene=True, mark={'excluded': True})
    assert chk.main(['check', str(tmp_path)]) == 0
