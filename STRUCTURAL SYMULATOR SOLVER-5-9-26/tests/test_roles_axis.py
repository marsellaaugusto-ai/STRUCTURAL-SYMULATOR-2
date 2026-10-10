"""Roles: the axis that cuts across the group tree.

The point of this file is the word ACROSS. A group is a tree, so it can
answer "what is in this bay" and can never answer "every diagonal in the
building" -- a diagonal exists in every bay, so the set is not a branch of
anything. Every test below that matters therefore uses a model with the
same role in SEVERAL groups, and checks that one action reaches all of them.

The engine (apps/stereo/stereo_roles.py) is Tk-free and tested first,
without a window. The panel's two verbs are then driven through a real tab.
"""
import time

import pytest

from apps.stereo import stereo_groups as sgp
from apps.stereo import stereo_roles as sr


# ── the engine ─────────────────────────────────────────────────────────────

def _members():
    """Three trusses, each with a top chord, a bottom chord and two
    diagonals -- so every role appears in every group."""
    out = []
    for _ in range(3):
        out += [{'role': 'top_chord', 'conn': 'pin'},
                {'role': 'bottom_chord', 'conn': 'pin'},
                {'role': 'diagonal', 'conn': 'pin'},
                {'role': 'diagonal', 'conn': 'rigid'}]
    return out


def test_roles_are_listed_biggest_first_with_the_unrolled_last():
    members = _members() + [{'conn': 'pin'}]          # one rod with no role
    found = sr.roles_in(members)
    assert list(found) == ['diagonal', 'bottom_chord', 'top_chord', sr.UNSET]
    assert len(found['diagonal']) == 6
    assert list(found)[-1] == sr.UNSET, 'leftovers never head the list'


def test_a_role_nobody_named_is_still_counted():
    """A merged or imported model arrives without roles. Dropping those rods
    from the list would lose them from the one place that counts them."""
    found = sr.roles_in([{'conn': 'pin'}, {'role': '', 'conn': 'pin'}])
    assert found[sr.UNSET] == [0, 1]
    assert sr.label(sr.UNSET) == 'No role'


def test_an_unknown_role_gets_a_readable_name_without_a_code_change():
    assert sr.label('crane_mast') == 'Crane mast'
    assert sr.label('some_new_thing') == 'Some new thing'


def test_a_rule_is_a_question_so_it_answers_again_after_an_edit():
    members = _members()
    rule = sr.new_rule('Rigid diagonals', roles={'diagonal'}, conn='rigid')
    assert sr.matching(rule, members) == [3, 7, 11]
    # Change the model; the rule is re-asked, not re-stated.
    members[2]['conn'] = 'rigid'
    assert sr.matching(rule, members) == [2, 3, 7, 11]


def test_a_utilisation_rule_matches_nothing_before_there_is_a_solve():
    """Rather than matching everything, which would hide or select the whole
    model the first time someone saved such a rule before analysing."""
    members = _members()
    rule = sr.new_rule('Overloaded', roles={'diagonal'}, util_min=1.0)
    assert sr.matching(rule, members, (), None) == []
    assert sr.matching(rule, members, (), []) == []
    checks = [{'util': 0.2}] * len(members)
    checks[2] = {'util': 1.7}
    assert sr.matching(rule, members, (), checks) == [2]


def test_a_rod_with_no_check_is_not_swept_into_a_utilisation_rule():
    members = _members()
    checks = [{'util': None}] * len(members)
    checks[3] = {'util': 2.0}
    rule = sr.new_rule('Over', util_min=1.0)
    assert sr.matching(rule, members, (), checks) == [3]


def test_a_rule_can_be_confined_to_groups_as_well():
    members = _members()
    groups = []
    sgp.new_group(groups, 'Truss 1', members=range(0, 4))
    sgp.new_group(groups, 'Truss 2', members=range(4, 8))
    rule = sr.new_rule('Diagonals of truss 1', roles={'diagonal'},
                       groups={groups[0]['id']})
    assert sr.matching(rule, members, groups) == [2, 3]


def test_a_rule_describes_itself_in_words():
    rule = sr.new_rule('x', roles={'diagonal'}, util_min=1.0)
    assert 'Diagonal' in sr.describe(rule)
    assert 'over 1.00' in sr.describe(rule)
    assert 'any rod' in sr.describe(sr.new_rule('y'))


# ── the panel, in a real tab ───────────────────────────────────────────────

pytest.importorskip('tkinter')
import tkinter as tk                                            # noqa: E402

from apps.stereo.stereo_app import StereoApp                    # noqa: E402


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    seen = []
    for where in ('apps.stereo.stereo_app_roles.messagebox',
                  'apps.stereo.stereo_app.messagebox'):
        for kind in ('showinfo', 'showerror', 'showwarning'):
            monkeypatch.setattr('%s.%s' % (where, kind),
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
    """Three separate trusses, each its own group, each holding every role --
    so a role genuinely spans groups and the cross-cut is real."""
    tab = tk.Frame(tk_root)
    a = StereoApp(tab)
    nodes, members, groups = [], [], []
    for k in range(3):
        b, y = len(nodes), k * 4.0
        nodes.extend([(0, y, 0), (6, y, 0), (3, y, 2)])
        start = len(members)
        members.append({'a': b, 'b': b + 1, 'conn': 'pin', 'role': 'bottom_chord'})
        members.append({'a': b, 'b': b + 2, 'conn': 'pin', 'role': 'diagonal'})
        members.append({'a': b + 2, 'b': b + 1, 'conn': 'pin', 'role': 'diagonal'})
        sgp.new_group(groups, 'Truss %d' % (k + 1),
                      members=range(start, len(members)))
    a.nodes, a.members, a.groups = nodes, members, groups
    a._refresh_group_list()
    a._refresh_roles_list()
    tab.pack(fill='both', expand=True)
    tk_root.update_idletasks()
    tk_root.update()
    yield a
    tab.destroy()


def test_selecting_a_role_reaches_every_group(app):
    """The whole point: one action, all three trusses."""
    picked = app._roles_select('diagonal')
    assert len(picked) == 6
    owners = {sgp.owner_of_rod(app.groups).get(i) for i in picked}
    assert len(owners) == 3, 'a role that stops at one group is not an axis'


def test_hiding_a_role_reaches_every_group(app):
    app._roles_set_hidden('diagonal', True)
    hidden = app._hidden_rods()
    assert len(hidden) == 6
    owners = {sgp.owner_of_rod(app.groups).get(i) for i in hidden}
    assert len(owners) == 3
    app._draw()
    assert len(app.canvas.find_withtag('member')) == len(app.members) - 6
    app._roles_set_hidden('diagonal', False)
    assert app._hidden_rods() == set()


def test_the_two_axes_hide_independently_and_add_up(app):
    """A group hides a branch, a role hides a kind. Both at once is the
    union, and turning one off does not turn the other off."""
    gid = app.groups[0]['id']
    app._group_toggle_hidden(gid)
    app._roles_set_hidden('diagonal', True)
    hidden = app._hidden_rods()
    assert hidden == set(sgp.rods_of(app.groups, gid, deep=True)) | \
        set(sr.rods_with_role(app.members, {'diagonal'}))
    app._roles_set_hidden('diagonal', False)
    assert app._hidden_rods() == set(sgp.rods_of(app.groups, gid, deep=True))


def test_a_hidden_role_cannot_be_selected_or_picked(app):
    app._roles_set_hidden('diagonal', True)
    assert app._roles_select('diagonal') == set()
    _nodes, rods = app._pick_filter()
    assert rods is not None and not (rods & set(
        sr.rods_with_role(app.members, {'diagonal'})))


def test_a_rule_selects_what_it_matches_now(app):
    rule = sr.new_rule('All diagonals', roles={'diagonal'})
    app.role_rules.append(rule)
    assert len(app._rule_select(rule)) == 6
    # Re-ask after an edit: a saved LIST would still say six.
    app.members[1]['role'] = 'brace'
    assert len(app._rule_matching(rule)) == 5


def test_a_rule_can_hide_and_release(app):
    rule = sr.new_rule('All diagonals', roles={'diagonal'})
    app.role_rules.append(rule)
    app._rule_set_hidden(rule, True)
    assert len(app._hidden_rods()) == 6
    app._rule_set_hidden(rule, False)
    assert app._hidden_rods() == set()


def test_deleting_a_rule_stops_it_hiding(app):
    rule = sr.new_rule('All diagonals', roles={'diagonal'})
    app.role_rules.append(rule)
    app._rule_set_hidden(rule, True)
    app._rule_delete(rule)
    assert app.role_rules == []
    assert app._hidden_rods() == set(), 'a deleted rule must not keep hiding'


def test_the_roles_panel_lists_what_the_model_has(app):
    app._refresh_roles_list()
    labels = []
    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Button):
                try:
                    labels.append(str(c.cget('text')))
                except tk.TclError:
                    pass
            walk(c)
    walk(app._roles_rows)
    assert 'Diagonal' in labels and 'Bottom chord' in labels


# ── leaving rods out of the analysis by rule ─────────────────────────────

def _roled(roles):
    """One rod per role named, for the exclusion tests below."""
    return [{'a': i, 'b': i + 1, 'role': r, 'conn': 'pin'}
            for i, r in enumerate(roles)]


def test_a_rule_can_leave_its_rods_out():
    members = _roled(['top_chord', 'diagonal', 'diagonal', 'purlin'])
    rule = sr.new_rule('No diagonals', roles={'diagonal'}, exclude=True)
    assert rule['exclude'] is True
    assert sr.excluded_by([rule], members) == {1, 2}


def test_a_rule_that_does_not_say_so_leaves_nothing_out():
    members = _roled(['diagonal', 'diagonal'])
    rule = sr.new_rule('Diagonals', roles={'diagonal'})
    assert rule['exclude'] is False
    assert sr.excluded_by([rule], members) == set()


def test_several_rules_leave_out_the_union():
    members = _roled(['top_chord', 'diagonal', 'purlin'])
    rules = [sr.new_rule('a', roles={'diagonal'}, exclude=True),
             sr.new_rule('b', roles={'purlin'}, exclude=True),
             sr.new_rule('c', roles={'top_chord'})]
    assert sr.excluded_by(rules, members) == {1, 2}


def test_a_rule_about_utilisation_cannot_leave_rods_out():
    """Utilisation comes OUT of the analysis. A rule reading it to decide
    what the analysis contains would answer differently every time, and
    the model would solve differently depending on how often Analyze had
    been pressed. Refused where the rule is written."""
    rule = sr.new_rule('Overloaded', roles={'diagonal'}, util_min=1.0,
                       exclude=True)
    assert rule['exclude'] is False
    assert sr.can_exclude(rule) is False
    assert sr.asks_about_utilisation(rule) is True


@pytest.mark.parametrize('kw', [{'util_min': 1.0}, {'util_max': 0.5},
                                {'util_min': 0.2, 'util_max': 0.8}])
def test_any_utilisation_bound_blocks_exclusion(kw):
    assert sr.new_rule('r', exclude=True, **kw)['exclude'] is False


def test_a_rule_that_got_the_flag_some_other_way_still_cannot(monkeypatch):
    """Refused twice: once where the rule is written, and once where it
    would do the damage. A dict edited by hand, or read from a workbook
    someone changed, must not slip through."""
    members = _roled(['diagonal', 'diagonal'])
    forced = sr.new_rule('Overloaded', roles={'diagonal'}, util_min=1.0)
    forced['exclude'] = True                  # straight past new_rule
    assert sr.excluded_by([forced], members) == set()


def test_excluding_is_asked_without_the_solve_results():
    """`excluded_by` takes no checks at all, so a utilisation rule has
    nothing to answer with even if it were let through."""
    import inspect
    assert 'checks' not in inspect.signature(sr.excluded_by).parameters


def test_a_rule_scoped_to_a_group_leaves_out_that_branch():
    members = _roled(['a', 'b', 'c', 'd'])
    groups = [{'id': 1, 'name': 'Temp works', 'parent': None,
               'members': {1, 2}}]
    rule = sr.new_rule('Temporary', groups={1}, exclude=True)
    assert sr.excluded_by([rule], members, groups) == {1, 2}


def test_what_it_reads_as_says_it_leaves_rods_out():
    rule = sr.new_rule('Temporary', roles={'purlin'}, exclude=True)
    assert 'left out of the analysis' in sr.describe(rule)
    plain = sr.new_rule('Purlins', roles={'purlin'})
    assert 'left out' not in sr.describe(plain)
