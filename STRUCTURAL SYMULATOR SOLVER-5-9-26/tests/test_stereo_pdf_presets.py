"""Saved PDF settings (stereo_pdf_presets) and the cover sheet."""

import os

from apps.stereo import stereo_pdf_presets as spp
from apps.stereo import stereo_reports as sr


def test_presets_round_trip_through_their_file(tmp_path):
    path = str(tmp_path / 'p.json')
    assert spp.load(path) == {}
    p = spp.make({'force', 'tables'}, view={'zoom': 1.5, 'ratio': None},
                 cover=True, project={'project': 'Hangar 3'})
    spp.put('client set', p, path)
    got = spp.load(path)
    assert got['client set']['sheets'] == ['force', 'tables']
    assert got['client set']['view'] == {'zoom': 1.5, 'ratio': None}
    assert got['client set']['cover'] is True
    assert got['client set']['project'] == {'project': 'Hangar 3'}
    spp.remove('client set', path)
    assert spp.load(path) == {}


def test_a_damaged_store_reads_as_empty(tmp_path):
    path = tmp_path / 'p.json'
    path.write_text('{not json')
    assert spp.load(str(path)) == {}


def test_the_store_lives_where_the_environment_says(tmp_path, monkeypatch):
    monkeypatch.setenv(spp.ENV, str(tmp_path / 'x.json'))
    assert spp.store_path() == str(tmp_path / 'x.json')
    monkeypatch.delenv(spp.ENV)
    assert spp.store_path().endswith(os.path.join('.structural_simulator',
                                                  'pdf_presets.json'))


def test_the_groups_pdf_is_kept_by_group_name():
    cfg = {'mode': 'each', 'sheets': {'tables'},
           'items': [{'gid': 7, 'title': 'East', 'sheets': {'force'},
                      'on': True},
                     {'gid': 9, 'title': 'West', 'sheets': None, 'on': False}]}
    p = spp.make({'tables'}, groups_pdf=cfg,
                 group_names={7: 'Roof B', 9: 'Roof A'})
    assert [it['name'] for it in p['groups_pdf']['items']] == ['Roof B',
                                                              'Roof A']
    # another file, where the same groups have other ids, and one is missing
    back = spp.groups_pdf_for(p, {'Roof B': 2})
    assert back['mode'] == 'each'
    assert back['items'] == [{'gid': 2, 'title': 'East',
                              'sheets': {'force'}, 'on': True}]
    assert spp.groups_pdf_for({'groups_pdf': None}, {}) is None


def test_the_cover_comes_first_and_names_every_sheet():
    plan = sr.plan_sheets(None, None, 0, cover=True)
    assert plan[:2] == ['cover', 'general']
    assert sr.sheet_title('moment_rods_plan_top') == \
        'Bending moment along the rods, plan, top chords'
    assert sr.sheet_title('crane_K2_table') == \
        'Crane K2 — slings, hook and rope sizes'
    assert sr.sheet_title('takeoff') == 'Material take-off'
