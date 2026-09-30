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
