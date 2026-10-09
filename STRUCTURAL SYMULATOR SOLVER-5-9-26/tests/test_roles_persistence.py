"""Saved rules in the workbook.

A rule is a saved QUESTION, not a saved list, which is what makes it worth
writing down: it re-answers itself after the model changes. Until it
travelled in the workbook it survived the model changing and not the file
being closed, so "overloaded diagonals" had to be typed again every time.

The sharp edge is a rule SCOPED TO GROUPS. It holds group ids; ids survive
an import through the Groups sheet and are renumbered by the Scene sheet.
An id that comes back meaning a different group is the worst outcome
available: the rule still works, still selects rods, and selects the wrong
ones. Several tests below are only about that.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import tkinter as tk

from apps.stereo import stereo_roles as srl
from apps.stereo import stereo_roles_excel as sre
from common import _ensure_openpyxl

pytestmark = pytest.mark.skipif(not _ensure_openpyxl(),
                                reason='openpyxl unavailable')


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    seen = []
    for kind in ('showinfo', 'showerror', 'showwarning'):
        monkeypatch.setattr('apps.stereo.stereo_app.messagebox.%s' % kind,
                            lambda *a, _k=kind, **kw: seen.append((_k,) + a))
    return seen


@pytest.fixture(scope='module')
def tk_root():
    last = None
    for attempt in range(6):
        try:
            root = tk.Tk()
            break
        except tk.TclError as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    else:
        pytest.skip('no Tk display after 6 attempts: %s' % last)
    root.geometry('1400x900')
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def app(tk_root):
    from apps.stereo.stereo_app import StereoApp
    tab = tk.Frame(tk_root)
    a = StereoApp(tab)
    a._generate(push_undo=False)
    tab.pack(fill='both', expand=True)
    tk_root.update_idletasks()
    tk_root.update()
    yield a
    tab.destroy()


@pytest.fixture
def grouped(app):
    from apps.stereo import stereo_autogroup as ag
    app.groups = ag.auto_groups(app.nodes, app.members)
    assert app.groups, 'the auto-grouper found something to group'
    app._refresh_group_list()
    return app


def save_and_open(app, tmp_path, monkeypatch, name='rules.xlsx'):
    path = str(tmp_path / name)
    monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                        lambda **kw: path)
    app._export_excel()
    assert os.path.exists(path)
    monkeypatch.setattr('apps.stereo.stereo_app.filedialog.askopenfilename',
                        lambda **kw: path)
    app._import_excel()
    return path


def by_name(rules):
    return {r['name']: r for r in rules}


# ── the plain round trip ─────────────────────────────────────────────────

def test_a_rule_survives_the_file_being_closed(app, tmp_path, monkeypatch):
    app.role_rules = [srl.new_rule('Overloaded diagonals',
                                   roles={'diagonal'}, util_min=1.0)]
    save_and_open(app, tmp_path, monkeypatch)
    rules = by_name(app.role_rules)
    assert 'Overloaded diagonals' in rules
    got = rules['Overloaded diagonals']
    assert got['roles'] == {'diagonal'}
    assert got['util_min'] == 1.0
    assert got['util_max'] is None


@pytest.mark.parametrize('kw,check', [
    ({'roles': {'top_chord', 'bottom_chord'}},
     lambda r: r['roles'] == {'top_chord', 'bottom_chord'}),
    ({'util_min': 0.25, 'util_max': 0.75},
     lambda r: (r['util_min'], r['util_max']) == (0.25, 0.75)),
    ({'util_max': 0.5}, lambda r: r['util_max'] == 0.5),
    ({'conn': 'rigid'}, lambda r: r['conn'] == 'rigid'),
    ({'conn': 'pin'}, lambda r: r['conn'] == 'pin'),
    ({}, lambda r: r['roles'] is None and r['conn'] is None),
])
def test_every_part_of_a_rule_comes_back(app, tmp_path, monkeypatch, kw,
                                          check):
    app.role_rules = [srl.new_rule('R', **kw)]
    save_and_open(app, tmp_path, monkeypatch)
    assert len(app.role_rules) == 1
    assert check(app.role_rules[0])


def test_the_rods_a_rule_selects_are_the_same_after_a_round_trip(app,
                                                                  tmp_path,
                                                                  monkeypatch):
    """The point of saving the question rather than the answer.

    'web' is also the case that matters most for the spelling: it is a role
    no generator put in ROLE_LABELS, so it round-trips through the label
    the panel makes up for it rather than through a known name."""
    rule = srl.new_rule('The webs', roles={'web'})
    app.role_rules = [rule]
    before = srl.matching(rule, app.members, app.groups)
    assert before, 'the model has webs to find'
    save_and_open(app, tmp_path, monkeypatch)
    assert app.role_rules[0]['roles'] == {'web'}
    after = srl.matching(app.role_rules[0], app.members, app.groups)
    assert after == before


def test_several_rules_all_come_back(app, tmp_path, monkeypatch):
    app.role_rules = [srl.new_rule('A', roles={'diagonal'}),
                      srl.new_rule('B', util_min=0.9),
                      srl.new_rule('C', conn='rigid')]
    save_and_open(app, tmp_path, monkeypatch)
    assert sorted(by_name(app.role_rules)) == ['A', 'B', 'C']


def test_which_rules_are_hiding_comes_back(app, tmp_path, monkeypatch):
    app.role_rules = [srl.new_rule('A', roles={'diagonal'}),
                      srl.new_rule('B', roles={'purlin'})]
    app._hidden_rules = {'A'}
    save_and_open(app, tmp_path, monkeypatch)
    assert app._hidden_rules == {'A'}


def test_hidden_roles_come_back(app, tmp_path, monkeypatch):
    app._hidden_roles = {'diagonal', 'purlin'}
    save_and_open(app, tmp_path, monkeypatch)
    assert app._hidden_roles == {'diagonal', 'purlin'}


def test_the_rods_hidden_by_the_axis_are_the_same_afterwards(app, tmp_path,
                                                              monkeypatch):
    """Both halves of the axis at once: a hidden ROLE, which travels in
    [META], and a hidden RULE, which travels in the sheet."""
    app._hidden_roles = {'web'}
    app.role_rules = [srl.new_rule('Top chords', roles={'top_chord'})]
    app._hidden_rules = {'Top chords'}
    before = set(app._hidden_by_role())
    assert before
    save_and_open(app, tmp_path, monkeypatch)
    assert app._hidden_roles == {'web'}
    assert app._hidden_rules == {'Top chords'}
    assert set(app._hidden_by_role()) == before


def test_rods_with_no_role_survive_as_a_role(app, tmp_path, monkeypatch):
    """UNSET is the empty string, which would vanish in a comma list and
    come back as "any rod" -- a hide rule that hid the whole model."""
    app.role_rules = [srl.new_rule('Unroled', roles={srl.UNSET})]
    app._hidden_roles = {srl.UNSET}
    save_and_open(app, tmp_path, monkeypatch)
    assert app.role_rules[0]['roles'] == {srl.UNSET}
    assert app._hidden_roles == {srl.UNSET}


# ── a rule scoped to groups ──────────────────────────────────────────────

def test_a_rule_scoped_to_groups_follows_them(grouped, tmp_path, monkeypatch):
    app = grouped
    gid = app.groups[0]['id']
    name = app.groups[0]['name']
    app.role_rules = [srl.new_rule('In that bay', groups={gid})]
    save_and_open(app, tmp_path, monkeypatch)
    back = app.role_rules[0]
    assert back['groups'], 'it still names a group'
    found = [g for g in app.groups if g['id'] in back['groups']]
    assert [g['name'] for g in found] == [name], \
        'and it is the group it was written about, whatever its id is now'


def test_a_scoped_rule_selects_the_same_rods_afterwards(grouped, tmp_path,
                                                         monkeypatch):
    """The failure this guards is not a crash. A rule whose group id came
    back meaning a different group still works and selects the wrong rods."""
    app = grouped
    gid = app.groups[0]['id']
    rule = srl.new_rule('In that bay', groups={gid})
    app.role_rules = [rule]
    before = srl.matching(rule, app.members, app.groups)
    assert before
    save_and_open(app, tmp_path, monkeypatch)
    after = srl.matching(app.role_rules[0], app.members, app.groups)
    assert after == before


def test_a_rule_naming_several_groups_keeps_all_of_them(grouped, tmp_path,
                                                         monkeypatch):
    app = grouped
    if len(app.groups) < 2:
        pytest.skip('this model has only one group')
    names = {g['name'] for g in app.groups[:2]}
    app.role_rules = [srl.new_rule('Two bays',
                                   groups={g['id'] for g in app.groups[:2]})]
    save_and_open(app, tmp_path, monkeypatch)
    back = app.role_rules[0]['groups']
    assert {g['name'] for g in app.groups if g['id'] in back} == names


def test_a_group_that_is_gone_narrows_the_rule_and_says_so(app, grouped):
    """A rule that outlived part of its question is not a corrupt file.
    It is narrowed, kept, and reported -- losing every other rule over it
    would be the wrong trade."""
    rows = [{'name': 'Gone', 'groups': '77', 'group names': 'Nowhere'}]
    rules, _hidden, report = sre.build_rules(rows, app.members, app.groups)
    assert len(rules) == 1
    assert rules[0]['groups'] is None
    assert any('Nowhere' in line for line in report)


def test_an_id_that_now_means_a_different_group_follows_the_name(grouped):
    """What the Scene sheet's renumbering does. The id resolves, to the
    wrong thing; the name is what the person who wrote the rule meant."""
    app = grouped
    if len(app.groups) < 2:
        pytest.skip('this model has only one group')
    wrong_id = app.groups[0]['id']
    want = app.groups[1]['name']
    rows = [{'name': 'R', 'groups': str(wrong_id), 'group names': want}]
    rules, _hidden, report = sre.build_rules(rows, app.members, app.groups)
    found = [g for g in app.groups if g['id'] in (rules[0]['groups'] or ())]
    assert [g['name'] for g in found] == [want]
    assert any('followed the name' in line for line in report)


# ── reading a sheet someone edited ───────────────────────────────────────

def test_a_role_can_be_typed_the_way_the_panel_shows_it(app):
    rows = [{'name': 'R', 'roles': 'Diagonal, Top chord'}]
    rules, _h, _r = sre.build_rules(rows, app.members, app.groups)
    assert rules[0]['roles'] == {'diagonal', 'top_chord'}


def test_a_role_key_typed_by_hand_also_works(app):
    """The sheet writes labels, because it is meant to be edited and
    nobody should have to learn that the Top chord is top_chord. Someone
    who knows the key is not wrong, though."""
    rows = [{'name': 'R', 'roles': 'top_chord , DIAGONAL'}]
    rules, _h, _r = sre.build_rules(rows, app.members, app.groups)
    assert rules[0]['roles'] == {'top_chord', 'diagonal'}


def test_the_sheet_spells_roles_the_way_the_panel_does(app, tmp_path,
                                                        monkeypatch):
    import openpyxl
    app.role_rules = [srl.new_rule('R', roles={'top_chord'})]
    path = save_and_open(app, tmp_path, monkeypatch)
    ws = openpyxl.load_workbook(path, data_only=True)[sre.SHEET]
    flat = [str(c) for row in ws.iter_rows(values_only=True) for c in row
            if c is not None]
    assert 'Top chord' in flat
    assert 'top_chord' not in flat


def test_a_role_the_model_does_not_have_yet_is_still_a_question(app):
    """The rods that would answer it may be imported next."""
    rows = [{'name': 'R', 'roles': 'Stringer'}]
    rules, _h, _r = sre.build_rules(rows, app.members, app.groups)
    assert rules[0]['roles'] == {'stringer'}


def test_a_nonsense_bound_is_dropped_and_reported_not_raised(app):
    rows = [{'name': 'R', 'roles': 'Diagonal', 'util_min': 'soon'}]
    rules, _h, report = sre.build_rules(rows, app.members, app.groups)
    assert rules[0]['util_min'] is None
    assert rules[0]['roles'] == {'diagonal'}, 'the rest of the rule stands'
    assert report


def test_a_nonsense_conn_asks_about_either_and_says_so(app):
    rows = [{'name': 'R', 'conn': 'welded'}]
    rules, _h, report = sre.build_rules(rows, app.members, app.groups)
    assert rules[0]['conn'] is None
    assert any('neither pin nor rigid' in line for line in report)


def test_two_rules_with_one_name_keep_the_first(app):
    rows = [{'name': 'R', 'roles': 'Diagonal'},
            {'name': 'R', 'roles': 'Purlin'}]
    rules, _h, report = sre.build_rules(rows, app.members, app.groups)
    assert len(rules) == 1
    assert rules[0]['roles'] == {'diagonal'}
    assert report


def test_a_row_with_no_name_still_becomes_a_rule(app):
    rows = [{'name': '', 'roles': 'Diagonal'}]
    rules, _h, _r = sre.build_rules(rows, app.members, app.groups)
    assert len(rules) == 1
    assert rules[0]['name']


# ── the sheet itself ─────────────────────────────────────────────────────

def test_a_model_with_no_rules_writes_no_sheet(app, tmp_path, monkeypatch):
    """So the Stereo tab can tell "this file says there are no rules" from
    "this file does not mention rules" -- every workbook written before
    this existed is the second."""
    import openpyxl
    app.role_rules = []
    path = save_and_open(app, tmp_path, monkeypatch)
    assert sre.SHEET not in openpyxl.load_workbook(path).sheetnames


def test_the_sheet_says_what_each_rule_reads_as(app, tmp_path, monkeypatch):
    import openpyxl
    app.role_rules = [srl.new_rule('Overloaded diagonals',
                                   roles={'diagonal'}, util_min=1.0)]
    path = save_and_open(app, tmp_path, monkeypatch)
    ws = openpyxl.load_workbook(path, data_only=True)[sre.SHEET]
    flat = [str(c) for row in ws.iter_rows(values_only=True) for c in row
            if c is not None]
    assert any('Diagonal' in s and 'utilisation over 1.00' in s
               for s in flat), flat


def test_the_info_column_is_not_read_back(app, tmp_path, monkeypatch):
    """It is a sentence for the reader. Editing it must not become an
    edit to the rule it describes."""
    import openpyxl
    app.role_rules = [srl.new_rule('R', roles={'top_chord'}, util_min=1.0)]
    path = save_and_open(app, tmp_path, monkeypatch)
    wb = openpyxl.load_workbook(path)
    ws = wb[sre.SHEET]
    touched = False
    for row in ws.iter_rows():
        for cell in row:
            if cell.value and 'utilisation over' in str(cell.value):
                cell.value = 'any rod, utilisation over 9.99'
                touched = True
    assert touched, 'the info column was there to edit'
    wb.save(path)
    rows = sre.read_rules_sheet(openpyxl.load_workbook(path, data_only=True))
    assert all('info: reads as' not in r for r in rows)
    rules, _h, _r = sre.build_rules(rows, app.members, app.groups)
    assert rules[0]['roles'] == {'top_chord'}
    assert rules[0]['util_min'] == 1.0


def test_an_unreadable_rules_sheet_still_opens_the_model(app, tmp_path,
                                                          monkeypatch):
    """A sheet nobody can read is a reason to open the model without its
    rules, never a reason not to open the model."""
    import openpyxl
    app.role_rules = [srl.new_rule('A', roles={'diagonal'})]
    path = save_and_open(app, tmp_path, monkeypatch)
    wb = openpyxl.load_workbook(path)
    ws = wb[sre.SHEET]
    for row in ws.iter_rows():
        for cell in row:
            if cell.value == 'name':
                cell.value = 'nope'
    wb.save(path)
    rods = len(app.members)
    monkeypatch.setattr('apps.stereo.stereo_app.filedialog.askopenfilename',
                        lambda **kw: path)
    app._import_excel()
    assert len(app.members) == rods, 'the model came in'
    assert app.role_rules == []


def test_importing_a_file_with_no_rules_clears_the_old_ones(app, tmp_path,
                                                             monkeypatch):
    """The rules belong to the model, like the groups do. Keeping the
    previous file's would leave questions about rods that are gone."""
    path = str(tmp_path / 'bare.xlsx')
    monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                        lambda **kw: path)
    app.role_rules = []
    app._export_excel()
    app.role_rules = [srl.new_rule('Left over', roles={'diagonal'})]
    app._hidden_roles = {'purlin'}
    monkeypatch.setattr('apps.stereo.stereo_app.filedialog.askopenfilename',
                        lambda **kw: path)
    app._import_excel()
    assert app.role_rules == []
    assert app._hidden_roles == set()


def test_the_panel_shows_the_rules_that_came_back(app, tmp_path, monkeypatch):
    app.role_rules = [srl.new_rule('Overloaded diagonals',
                                   roles={'diagonal'}, util_min=1.0)]
    save_and_open(app, tmp_path, monkeypatch)
    win = app._rules_dialog()
    app.root.update_idletasks()
    boxes = [w for w in win.winfo_children() if isinstance(w, tk.Listbox)]
    assert boxes
    shown = boxes[0].get(0, 'end')
    assert any('Overloaded diagonals' in s for s in shown), shown
    win.destroy()
