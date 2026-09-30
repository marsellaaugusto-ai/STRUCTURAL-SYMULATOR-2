"""What has to be true for the app to start on someone else's machine.

There WAS a dependency preflight here, added on the theory that the app
would not launch because tkinter, numpy or scipy were missing. That theory
was wrong: the libraries were present all along, and the real cause was a
Tkinter resize-event loop -- relayout handlers reacting to their own
children's <Configure> events and changing the layout again on each one, so
the window never finished its first layout pass. The fix for that lives in
common.py (FlowBar._schedule, WrapBar._schedule and _on_toplevel_resize);
see REPORTS AND GUIDES/STEREO_ROADMAP_V2_FULL_ACCOUNT_2026-09-28.md.

The preflight and its seven tests went with the wrong diagnosis. What is
left here is the part that was worth keeping and is still true: main.py
imports cleanly as a module, tools/doctor.py works as a standalone check
an end user can run by hand, and the .vscode launch configurations set the
working directory the package imports need.
"""
import json
import os
import subprocess
import sys

import main

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_main_is_still_importable_as_a_module():
    """tests/tools/appdiag.py builds the window with main.App directly, so
    importing main must not construct or check anything by itself."""
    assert hasattr(main, 'App')


# ── the doctor ────────────────────────────────────────────────────────────

def test_the_doctor_passes_on_the_interpreter_running_the_suite():
    p = subprocess.run([sys.executable, os.path.join(APP, 'tools', 'doctor.py')],
                       capture_output=True, text=True, cwd=APP)
    assert p.returncode == 0, p.stdout + p.stderr
    assert 'VERDICT: this interpreter can run the app.' in p.stdout
    for name in ('tkinter', 'numpy', 'scipy'):
        assert name in p.stdout


def test_the_doctor_imports_nothing_the_app_needs():
    """It has to run on the interpreter that CANNOT run the app, which is
    the only interpreter anyone will point it at."""
    src = open(os.path.join(APP, 'tools', 'doctor.py'), encoding='utf-8').read()
    head = src.split('DEPENDENCIES', 1)[0]
    for banned in ('import numpy', 'import scipy', 'import tkinter',
                   'import common', 'import main'):
        assert banned not in head, f'doctor.py imports {banned} at load time'


# ── the VS Code configuration ────────────────────────────────────────────

def _load_jsonc(path):
    """launch.json and friends are JSONC; strip the whole-line comments."""
    lines = [ln for ln in open(path, encoding='utf-8').read().split('\n')
             if not ln.strip().startswith('//')]
    return json.loads('\n'.join(lines))


def test_launch_json_sets_the_working_directory_on_every_configuration():
    """This is the whole reason the file exists. main.py, common.py and
    apps/ import each other by package path, so the app must run with the
    app folder as the working directory -- and VS Code's plain Run button
    uses the workspace root, which is the wrong folder whenever the
    repository rather than the app folder was opened."""
    cfg = _load_jsonc(os.path.join(APP, '.vscode', 'launch.json'))
    configs = cfg['configurations']
    assert len(configs) >= 2
    for c in configs:
        assert c['cwd'], f'{c["name"]} does not set cwd'
        assert c['program'].startswith('${workspaceFolder}')
        assert c['cwd'] in c['program'], \
            f'{c["name"]}: the program is not inside its own cwd'


def test_launch_json_covers_both_folders_a_reader_might_open():
    cfg = _load_jsonc(os.path.join(APP, '.vscode', 'launch.json'))
    names = [c['name'] for c in cfg['configurations']]
    assert any('app folder' in n for n in names)
    assert any('repository root' in n for n in names)
    assert any('doctor' in n.lower() for n in names)


def test_the_vscode_folder_and_the_doctor_ship_in_the_zip():
    """.vscode is in most people's ignore list, and was in this builder's
    skip list too -- an archive without launch.json is an archive whose
    F5 does not work."""
    sys.path.insert(0, os.path.join(APP, 'tools'))
    import build_release
    shipped = {rel for rel, _ in build_release.app_files()}
    assert '.vscode/launch.json' in shipped
    assert '.vscode/tasks.json' in shipped
    assert 'tools/doctor.py' in shipped
    assert 'REPORTS AND GUIDES/RUNNING_THE_APP.md' in shipped


# ── the startup check ─────────────────────────────────────────────────────
# Restored 2026-09-30 after a user reported "the zip extracts but nothing
# happens when I run main.py". An earlier version of this check was removed
# because it had been committed as the fix for the app not starting, which it
# was not -- see the module docstring. Removing it threw out something that
# was still useful: it was MISLABELLED, not useless. These tests describe what
# it actually does, which is turn a missing library into a readable message.

def test_this_interpreter_reports_no_problems():
    """The suite is running, so tkinter, numpy and scipy are all here."""
    assert main.environment_problems() == []


def test_the_check_runs_BEFORE_the_imports_it_protects():
    """The whole point, and easy to break by tidying the file.

    main.py imports tkinter at module scope, so a check placed at the bottom
    of the file never runs on the interpreter that needs it most -- the
    process is already dead at the import line. The __main__ guard that calls
    environment_problems() must appear ABOVE `import tkinter as tk`.
    """
    src = open(os.path.join(APP, 'main.py')).read()
    guard = src.index("if __name__ == '__main__':")
    tk_import = src.index('import tkinter as tk')
    assert guard < tk_import, (
        'the startup check sits below the tkinter import, so it cannot run '
        'on an interpreter without tkinter -- the case it exists for')


def test_a_missing_dependency_is_reported_with_its_fix(monkeypatch):
    monkeypatch.setattr(main, 'HARD_DEPENDENCIES', (
        ('a_module_that_is_not_installed', 'ghost>=1.0',
         'nothing at all, it does not exist', None),))
    problems = main.environment_problems()
    assert len(problems) == 1
    title, detail = problems[0]
    assert 'a_module_that_is_not_installed' in title
    body = ' '.join(detail)
    assert 'ModuleNotFoundError' in body
    assert 'ghost>=1.0' in body
    assert sys.executable in body, 'pip for THIS interpreter, not bare "pip"'


def test_a_dependency_that_is_present_is_not_reported(monkeypatch):
    monkeypatch.setattr(main, 'HARD_DEPENDENCIES', (
        ('json', 'json', 'it is in the standard library', None),))
    assert main.environment_problems() == []


def test_the_tkinter_entry_carries_platform_hints():
    """tkinter is the one that catches people out, because it is not on PyPI
    and `pip install tkinter` fails in a way that teaches nothing."""
    entry = [e for e in main.HARD_DEPENDENCIES if e[0] == 'tkinter']
    assert entry, 'tkinter must be checked -- it is imported at module scope'
    _mod, pip_name, _why, hints = entry[0]
    assert pip_name is None, 'tkinter is not a pip package'
    assert hints and {'linux', 'darwin', 'win32'} <= set(hints)


def test_an_old_python_is_refused(monkeypatch):
    import collections
    monkeypatch.setattr(main.sys, 'version_info',
                        collections.namedtuple('v', 'major minor')(3, 6))
    problems = main.environment_problems()
    assert any('3.9' in t for t, _ in problems)


def _record_dialogs(monkeypatch):
    """Capture messagebox.showerror instead of letting it open.

    These two tests were first written assuming "no display here", so the
    dialog would fail fast and be swallowed. Under xvfb there IS a display:
    the modal dialog opened and waited for a click that never came, and the
    whole file hung for ten minutes at 0% CPU. Recording the call is also a
    stronger test than "did not raise" -- it proves the message reaches the
    user, which is the only reason these functions exist.
    """
    shown = []
    monkeypatch.setattr('tkinter.messagebox.showerror',
                        lambda title, text, **kw: shown.append((title, text)))
    return shown


def test_reporting_writes_to_stderr_and_to_a_window(capsys, monkeypatch):
    """It runs when things are already broken, so it cannot add a failure of
    its own -- and it must say so where a double-click user can see it."""
    shown = _record_dialogs(monkeypatch)
    text = main.report_problems([('something is missing', ['a detail line'])])
    err = capsys.readouterr().err
    assert 'something is missing' in err
    assert 'a detail line' in err
    assert 'cannot start' in err
    assert sys.executable in text
    assert shown, 'nothing was shown in a window'
    assert 'something is missing' in shown[0][1]


def test_reporting_never_raises_even_if_the_window_cannot_open(monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError('no display')
    monkeypatch.setattr('tkinter.messagebox.showerror', broken)
    text = main.report_problems([('x', ['y'])])
    assert 'x' in text


def test_a_startup_failure_is_shown_rather_than_vanishing(monkeypatch):
    """Any exception while the tabs build must reach a dialog, not only a
    console that a double-click launch has already closed."""
    shown = _record_dialogs(monkeypatch)
    try:
        raise ValueError('a wheel came off')
    except ValueError as exc:
        main._show_startup_failure(exc)
    assert shown, 'the failure never reached a window'
    title, text = shown[0]
    assert 'failed to start' in title
    assert 'a wheel came off' in text
    assert 'ValueError' in text
