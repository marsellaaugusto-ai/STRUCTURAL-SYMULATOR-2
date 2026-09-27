"""
main.py — entry point for STRUCTURAL SYMULATOR SOLVER-5-9-26. Wires all app tabs (Truss, Beam, Arch, Cable,
Cable Web, Perforated Beam) into one ttk.Notebook. Run this file to launch
the app:

    python main.py

main.py, common.py, and every apps/<name>/ package must stay together
under the same root folder -- they import each other via the apps.<name>
package path (see REPORTS AND GUIDES/MODULAR_ARCHITECTURE.md), so this file
must be run with that root as the working directory, not installed as a
standalone package.

If it will not start, see REPORTS AND GUIDES/RUNNING_THE_APP.md, or run
`python tools/doctor.py` with the same interpreter.
"""
import sys

# ── launch preflight ──────────────────────────────────────────────────────
#
# Everything below imports tkinter, numpy and scipy at module scope, so an
# interpreter missing any one of them kills the process on an import line
# before a single window exists. From a terminal that traceback is at least
# visible. From an editor's Run button it is often a console that closes
# again, or a ModuleNotFoundError pointing at line 14 of a file the reader
# did not write -- which is indistinguishable, from the outside, from "the
# program crashes when I open it".
#
# In an editor the cause is almost always the SELECTED INTERPRETER: VS Code
# picks one per workspace, and it is frequently not the one the packages
# were installed into. So the preflight names the interpreter that is
# actually running, what it is missing, and the command that fixes it.

MIN_PYTHON = (3, 9)

HARD_DEPENDENCIES = (
    ('tkinter', None,
     'the GUI toolkit every window is built from',
     ('Debian/Ubuntu:  sudo apt install python3-tk',
      'Fedora:         sudo dnf install python3-tkinter',
      'macOS/Windows:  reinstall Python from python.org — tkinter is',
      '                included there, but not in some Homebrew, pyenv or',
      '                Microsoft Store builds')),
    ('numpy', 'numpy>=1.24',
     'every solver in the app; common.py imports it unguarded',
     None),
    ('scipy', 'scipy>=1.10',
     'the cable-web solver and the Stereo sparse assembly',
     None),
)


def environment_problems():
    """Everything about THIS interpreter that would stop the app starting.

    Returns a list of (title, detail_lines). Empty means the app will run.
    A real import is attempted rather than importlib.util.find_spec,
    because a tkinter whose _tkinter C extension is missing has a spec and
    still cannot be imported -- which is exactly the Homebrew/pyenv case.
    """
    problems = []
    if sys.version_info < MIN_PYTHON:
        want = '.'.join(str(n) for n in MIN_PYTHON)
        problems.append((
            f'Python {want} or newer is required',
            [f'this interpreter is Python {sys.version.split()[0]}']))

    for name, pip_name, why, hints in HARD_DEPENDENCIES:
        try:
            __import__(name)
            continue
        except Exception as exc:                 # ImportError, and worse
            detail = [f'needed for {why}', f'({type(exc).__name__}: {exc})']
            if pip_name:
                detail.append(f'install it:  "{sys.executable}" -m pip '
                              f'install "{pip_name}"')
            if hints:
                detail.extend(hints)
            problems.append((f'{name} cannot be imported', detail))
    return problems


def environment_report(problems):
    """The whole message, as one block of text."""
    import os
    lines = ['STRUCTURAL SYMULATOR SOLVER cannot start.', '']
    lines.append(f'Interpreter : {sys.executable}')
    lines.append(f'Version     : {sys.version.split()[0]}')
    lines.append(f'Working dir : {os.getcwd()}')
    lines.append(f'This file   : {os.path.abspath(__file__)}')
    lines.append('')
    for title, detail in problems:
        lines.append(f'  * {title}')
        for d in detail:
            lines.append(f'      {d}')
    lines.append('')
    lines.append('Install everything at once, with THIS interpreter:')
    lines.append(f'    "{sys.executable}" -m pip install -r requirements.txt')
    lines.append('')
    lines.append('In VS Code this nearly always means the selected')
    lines.append('interpreter is not the one the packages are installed in:')
    lines.append('    Ctrl+Shift+P  ->  "Python: Select Interpreter"')
    lines.append('then press F5 — .vscode/launch.json runs the app from the')
    lines.append('right folder. See REPORTS AND GUIDES/RUNNING_THE_APP.md.')
    return '\n'.join(lines)


def report_environment_problems(problems):
    """Say it on the console, and in a window when one is possible.

    Both, not either: an editor may hide the console, and the console is
    the only channel left when tkinter itself is what is missing.
    """
    text = environment_report(problems)
    sys.stderr.write(text + '\n')
    sys.stderr.flush()
    try:                                    # a window, if tkinter survived
        import tkinter as _tk
        from tkinter import messagebox as _mb
        _root = _tk.Tk()
        _root.withdraw()
        _mb.showerror('STRUCTURAL SYMULATOR SOLVER — cannot start', text)
        _root.destroy()
    except Exception:
        pass                                # console-only; already written


if __name__ == '__main__':
    # Before the imports below, not after: the whole point is to replace
    # the traceback they would raise.
    _problems = environment_problems()
    if _problems:
        report_environment_problems(_problems)
        raise SystemExit(1)

import tkinter as tk
from tkinter import ttk

import units

from apps.truss.truss_app import TrussApp
from apps.beam.beam_app import BeamApp
from apps.arch.arch_app import ArchApp
from apps.cable.cable_app import CableApp
from apps.cable_web.cable_web_app import CableWebApp
from apps.perforated_beam.perforated_beam_app import PerforatedBeamApp
from apps.stereo.stereo_app import StereoApp

class App:
    def __init__(self, root):
        # root is always tk.Tk() when launched from __main__
        try:
            root.title('STRUCTURAL SYMULATOR SOLVER-5-9-26')
            root.resizable(True, True)
        except Exception:
            pass   # safety: never called with a Frame

        style = ttk.Style()
        try:
            style.theme_use('clam')
        except Exception:
            pass

        # ── unit convention, app-wide ────────────────────────────────────────
        # Deliberately ABOVE the notebook rather than inside a tab: the choice
        # applies to every tab at once, and a per-tab copy of it would let the
        # Beam tab read in kip while the Truss tab read in kN. It changes only
        # how numbers are written -- see units.py; every solver computes in SI
        # whatever is selected here.
        self.units_bar = tk.Frame(root, bg='#ebebea')
        self.units_bar.pack(fill='x', side='top')
        tk.Label(self.units_bar, text='Units:', bg='#ebebea',
                 font=('Helvetica', 9, 'bold')).pack(side='left', padx=(8, 4), pady=3)
        self.units_var = tk.StringVar(value=units.current().name)
        self.units_box = ttk.Combobox(
            self.units_bar, textvariable=self.units_var, state='readonly', width=26,
            values=[units.SYSTEMS[k].name for k in units.ORDER])
        self.units_box.pack(side='left', pady=3)
        self.units_note = tk.Label(self.units_bar, text=units.current().note,
                                    bg='#ebebea', fg='#666', font=('Helvetica', 8))
        self.units_note.pack(side='left', padx=10)

        def _on_units_change(_event=None):
            name = self.units_var.get()
            for key in units.ORDER:
                if units.SYSTEMS[key].name == name:
                    units.set_current(key)
                    self.units_note.config(text=units.SYSTEMS[key].note)
                    break

        self.units_box.bind('<<ComboboxSelected>>', _on_units_change)

        nb = ttk.Notebook(root)
        nb.pack(fill='both', expand=True)

        truss_tab = tk.Frame(nb)
        beam_tab = tk.Frame(nb)
        arch_tab = tk.Frame(nb)
        cable_tab = tk.Frame(nb)
        cable_web_tab = tk.Frame(nb)
        perforated_beam_tab = tk.Frame(nb)
        stereo_tab = tk.Frame(nb)
        nb.add(truss_tab, text='Truss')
        nb.add(beam_tab, text='Beam')
        nb.add(arch_tab, text='Arch')
        nb.add(cable_tab, text='Cable')
        nb.add(cable_web_tab, text='Cable Web')
        nb.add(perforated_beam_tab, text='Perforated Beam')
        nb.add(stereo_tab, text='Stereo')

        TrussApp(truss_tab)
        beam_app = BeamApp(beam_tab)
        beam_app.pack(fill='both', expand=True)
        arch_app = ArchApp(arch_tab)
        arch_app.pack(fill='both', expand=True)
        cable_app = CableApp(cable_tab)
        cable_app.pack(fill='both', expand=True)
        cable_web_app = CableWebApp(cable_web_tab)
        cable_web_app.pack(fill='both', expand=True)
        perforated_beam_app = PerforatedBeamApp(perforated_beam_tab)
        perforated_beam_app.pack(fill='both', expand=True)
        StereoApp(stereo_tab)


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()