"""The app must explain why it will not start, instead of dying on an
import line.

`main.py` imports tkinter at module scope and `common.py` imports numpy
unguarded, so an interpreter missing either one killed the process before
a window existed. From a terminal that is at least a traceback; from an
editor's Run button it is indistinguishable from "the program crashes when
I open it", because the console holding the traceback may have closed
again. These tests pin the preflight that replaced it.
"""
import json
import os
import subprocess
import sys

import pytest

import main

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_this_interpreter_reports_no_problems():
    """The suite is running, so tkinter, numpy and scipy are all here --
    the preflight must not invent a problem on a working install."""
    assert main.environment_problems() == []


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
    assert sys.executable in body      # pip for THIS interpreter, not 'pip'


def test_a_dependency_that_is_present_is_not_reported(monkeypatch):
    monkeypatch.setattr(main, 'HARD_DEPENDENCIES', (
        ('json', 'json', 'the standard library', None),))
    assert main.environment_problems() == []


def test_the_tkinter_entry_carries_platform_hints():
    """tkinter is the one that catches people out, because it is not on
    PyPI: `pip install tkinter` fails and tells them nothing."""
    entry = [d for d in main.HARD_DEPENDENCIES if d[0] == 'tkinter']
    assert entry, 'tkinter must be checked'
    name, pip_name, why, hints = entry[0]
    assert pip_name is None, 'tkinter is not a pip package'
    assert hints, 'it needs OS-level instructions instead'
    joined = ' '.join(hints).lower()
    assert 'apt' in joined and 'python.org' in joined


def test_an_old_python_is_refused(monkeypatch):
    import collections
    fake = collections.namedtuple(
        'v', 'major minor micro releaselevel serial')(3, 6, 0, 'final', 0)
    monkeypatch.setattr(sys, 'version_info', fake)
    problems = main.environment_problems()
    assert any('newer is required' in title for title, _ in problems)


def test_the_report_names_the_interpreter_and_the_way_out():
    report = main.environment_report([('tkinter cannot be imported',
                                       ['needed for the GUI'])])
    assert sys.executable in report
    assert 'requirements.txt' in report
    assert 'Select Interpreter' in report      # the VS Code cause
    assert 'tkinter cannot be imported' in report


def test_reporting_writes_to_stderr_and_never_raises(capsys):
    """It is called when the app is already failing; it must not add a
    second failure of its own -- including where tkinter is the thing
    that is missing and the dialog cannot be shown."""
    main.report_environment_problems([('numpy cannot be imported',
                                       ['needed for every solver'])])
    err = capsys.readouterr().err
    assert 'cannot start' in err
    assert 'numpy cannot be imported' in err


def test_main_is_still_importable_as_a_module():
    """tests/tools/appdiag.py builds the window with main.App directly, so
    the preflight must not run on import -- only on __main__."""
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
