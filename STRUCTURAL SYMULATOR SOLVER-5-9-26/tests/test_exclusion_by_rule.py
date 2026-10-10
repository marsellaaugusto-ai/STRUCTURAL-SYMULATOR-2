"""Leaving rods out of the analysis by rule.

A group could already be flagged one at a time. Asking the question
instead means the temporary works, or a crane's rigging, or everything of
a role, drops out of the solve and STAYS out as the model grows, without
anyone having to remember to flag the next group.

This is the one axis change that can produce a wrong answer rather than a
missing feature, so most of this file is about the two ways it could:

  * a rule about UTILISATION deciding what the analysis contains, which
    would make the answer depend on itself -- and would show up as a
    number that quietly moves, not as an error;
  * leaving out so much that there is nothing left to solve, where the
    solver's own word for it ("singular") says nothing about why.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import tkinter as tk

from apps.stereo import stereo_groups as sgp
from apps.stereo import stereo_roles as srl


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


def roles_in(app):
    return sorted({m.get('role') for m in app.members if m.get('role')})


# ── the rods really do leave the solve ───────────────────────────────────

def test_a_rule_leaves_its_rods_out_of_the_analysis(app):
    role = roles_in(app)[0]
    assert app._excluded_rods() == set()
    app.role_rules = [srl.new_rule('No %s' % role, roles={role},
                                   exclude=True)]
    left = app._excluded_rods()
    assert left
    assert all(app.members[i].get('role') == role for i in left)


def test_the_solver_is_handed_the_model_without_them(app, monkeypatch):
    """Not just computed -- actually passed to the analysis."""
    role = roles_in(app)[0]
    app.role_rules = [srl.new_rule('No %s' % role, roles={role},
                                   exclude=True)]
    seen = {}
    import apps.stereo.stereo_app_model as mod
    real = mod.slc.service_model

    def spy(nodes, members, supports, loads, member_loads, panels,
            inert=None):
        seen['inert'] = set(inert or ())
        return real(nodes, members, supports, loads, member_loads, panels,
                    inert=inert)

    monkeypatch.setattr(mod.slc, 'service_model', spy)
    app._analyze(quiet=True)
    assert seen['inert'] == app._excluded_rods()
    assert seen['inert']


def test_the_rods_stay_in_the_model(app):
    """Left out of the solve, not deleted: still drawn, still exported."""
    role = roles_in(app)[0]
    before = len(app.members)
    app.role_rules = [srl.new_rule('x', roles={role}, exclude=True)]
    assert len(app.members) == before
    assert app._excluded_rods()


def test_a_group_flag_and_a_rule_both_count(app, monkeypatch):
    """Two ways in, answering different questions, and the solve leaves
    out what either of them names."""
    role = roles_in(app)[0]
    # Rods of a DIFFERENT role, or the group would only name what the rule
    # already does and the test would prove nothing.
    other = [i for i, m in enumerate(app.members)
             if m.get('role') and m['role'] != role][:3]
    assert len(other) == 3
    sgp.new_group(app.groups, 'Temp', members=other)
    app.groups[-1]['excluded'] = True
    app.role_rules = [srl.new_rule('x', roles={role}, exclude=True)]
    left = app._excluded_rods()
    by_rule = app._excluded_by_rule()
    assert set(other) <= left
    assert not (set(other) & by_rule), 'the group named what the rule did not'
    assert left == by_rule | set(other)


def test_a_rule_follows_the_model_as_it_grows(app):
    """The point of asking rather than flagging: rods added later are
    left out too, with nobody remembering to do anything."""
    role = roles_in(app)[0]
    app.role_rules = [srl.new_rule('x', roles={role}, exclude=True)]
    before = len(app._excluded_rods())
    at = len(app.nodes)
    app.nodes.extend([(0, -50, 0), (1, -50, 0)])
    app.members.append({'a': at, 'b': at + 1, 'role': role, 'conn': 'pin',
                        'A': 20.0, 'I': 400.0, 'E': 200.0})
    assert len(app._excluded_rods()) == before + 1


def test_an_excluded_rod_index_past_the_model_is_dropped(app):
    """A rule answering about rods that are gone must not hand the solver
    an index it cannot use."""
    app.role_rules = [srl.new_rule('x', roles={roles_in(app)[0]},
                                   exclude=True)]
    app.members[:] = app.members[:5]
    assert all(i < 5 for i in app._excluded_rods())


# ── the circularity, which is the whole danger ───────────────────────────

def test_a_utilisation_rule_cannot_leave_rods_out_after_a_solve(app):
    """The dangerous moment: before a solve such a rule matches nothing
    anyway. After one it matches plenty -- and must still change nothing
    about what the next solve contains."""
    app._analyze(quiet=True)
    assert app.member_checks, 'the model solved, so utilisations exist'
    rule = srl.new_rule('Overloaded', util_min=0.0)
    rule['exclude'] = True                    # straight past new_rule
    app.role_rules = [rule]
    assert app._rule_matching(rule), 'it matches rods now'
    assert app._excluded_rods() == set(), 'and still leaves none out'


def test_the_answer_does_not_move_when_analyze_is_pressed_again(app):
    """What circular exclusion would look like in practice: not an error,
    just a number that quietly differs on the second press."""
    rule = srl.new_rule('Overloaded', util_min=0.0)
    rule['exclude'] = True
    app.role_rules = [rule]
    app._analyze(quiet=True)
    first = [m.get('util') for m in (app.member_checks or [])]
    assert any(u is not None for u in first)
    app._analyze(quiet=True)
    second = [m.get('util') for m in (app.member_checks or [])]
    assert second == first


def test_the_dialog_says_why_it_refused(app, monkeypatch):
    said = []
    monkeypatch.setattr('apps.stereo.stereo_app_roles.messagebox.showinfo',
                        lambda *a, **kw: said.append(a))

    def fill(win):
        entries = [w for w in win.winfo_children() if isinstance(w, tk.Entry)]
        entries[0].delete(0, 'end')
        entries[0].insert(0, 'Overloaded')
        for frame in win.winfo_children():
            if isinstance(frame, tk.Frame):
                band = [w for w in frame.winfo_children()
                        if isinstance(w, tk.Entry)]
                if len(band) == 2:
                    band[0].insert(0, '1.0')
        for w in win.winfo_children():
            if isinstance(w, tk.Checkbutton):
                w.select()
        for frame in win.winfo_children():
            if isinstance(frame, tk.Frame):
                for b in frame.winfo_children():
                    if isinstance(b, tk.Button) and b.cget('text') == 'Save':
                        b.invoke()
                        return

    real = tk.Toplevel

    class Driven(real):
        def wait_window(self, *a, **kw):
            fill(self)

    monkeypatch.setattr('apps.stereo.stereo_app_roles.tk.Toplevel', Driven)
    rule = app._rule_new()
    assert rule is not None
    assert rule['exclude'] is False
    assert said and 'cannot leave rods out' in said[0][1]


# ── leaving out everything ───────────────────────────────────────────────

def test_leaving_out_everything_is_refused_with_a_reason(app, dialogs):
    """The solver's own answer for an empty model says nothing about why,
    and a rule that matched more than its author expected is how this
    happens."""
    app.role_rules = [srl.new_rule('All of it', exclude=True)]
    assert len(app._excluded_rods()) == len(app.members)
    app._analyze()
    assert app.results is None
    assert 'nothing to solve' in app.err
    assert any('left out of the analysis' in str(d) for d in dialogs)


def test_leaving_out_almost_everything_still_analyses(app):
    """The guard is for nothing left, not for not much left."""
    keep = {m.get('role') for m in app.members[:1]}
    app.role_rules = [srl.new_rule('Most of it',
                                   roles=set(roles_in(app)) - keep,
                                   exclude=True)]
    assert app._excluded_rods()
    assert len(app._excluded_rods()) < len(app.members)
    app._analyze(quiet=True)
    assert app.err is None or 'nothing to solve' not in (app.err or '')


# ── saying so, where it can be seen ──────────────────────────────────────

def test_the_panel_says_what_is_being_left_out(app):
    """Rods missing from a solve with nothing on screen to say so is the
    failure this panel could introduce."""
    role = roles_in(app)[0]
    app.role_rules = [srl.new_rule('No %s' % role, roles={role},
                                   exclude=True)]
    app._refresh_roles_list()
    text = app.roles_left_out.cget('text')
    assert 'left out of the analysis' in text
    assert 'by rule' in text and 'No %s' % role in text


def test_nothing_left_out_says_nothing(app):
    app._refresh_roles_list()
    assert app.roles_left_out.cget('text') == ''
    assert app._exclusion_note() == ''


def test_the_note_counts_the_group_flags_separately(app):
    sgp.new_group(app.groups, 'Temp', members=[0, 1, 2])
    app.groups[-1]['excluded'] = True
    app._refresh_roles_list()
    assert '3 by group' in app.roles_left_out.cget('text')


# ── it travels in the workbook ───────────────────────────────────────────

def test_the_flag_survives_the_workbook(app, tmp_path, monkeypatch):
    from common import _ensure_openpyxl
    if not _ensure_openpyxl():
        pytest.skip('openpyxl unavailable')
    role = roles_in(app)[0]
    app.role_rules = [srl.new_rule('Temporary', roles={role}, exclude=True)]
    left = app._excluded_rods()
    path = str(tmp_path / 'x.xlsx')
    monkeypatch.setattr('apps.stereo.stereo_app.filedialog.asksaveasfilename',
                        lambda **kw: path)
    app._export_excel()
    monkeypatch.setattr('apps.stereo.stereo_app.filedialog.askopenfilename',
                        lambda **kw: path)
    app._import_excel()
    assert [r['name'] for r in app.role_rules] == ['Temporary']
    assert app.role_rules[0]['exclude'] is True
    assert app._excluded_rods() == left


def test_a_workbook_claiming_a_utilisation_rule_excludes_is_corrected(app):
    """Someone can tick the column on a rule that has a band. Read it,
    drop the flag, and say so rather than honouring it."""
    from apps.stereo import stereo_roles_excel as sre
    rows = [{'name': 'Overloaded', 'roles': 'Diagonal', 'util_min': 1.0,
             'leave out': 1}]
    rules, _hidden, report = sre.build_rules(rows, app.members, app.groups)
    assert rules[0]['exclude'] is False
    assert any('cannot leave rods out' in line for line in report)
