"""
main.py — entry point for STRUCTURAL SYMULATOR SOLVER-5-9-26. Wires all app tabs (Truss, Beam, Arch, Cable,
Cable Web, Perforated Beam, Stereo, Shell (RC)) into one ttk.Notebook. Run this file to launch
the app:

    python main.py

main.py, common.py, and every apps/<name>/ package must stay together
under the same root folder -- they import each other via the apps.<name>
package path (see REPORTS AND GUIDES/MODULAR_ARCHITECTURE.md), so this file
must be run with that root as the working directory, not installed as a
standalone package.

If it will not start, see REPORTS AND GUIDES/RUNNING_THE_APP.md, or run
`python tools/doctor.py` with the same interpreter to check this one has
tkinter, numpy and scipy.
"""
# ── startup check ───────────────────────────────────────────────────────────
# This runs BEFORE the imports below, and it exists for one narrow reason:
# tkinter is imported at module scope here and numpy inside common.py, so an
# interpreter missing either dies on an import line before any window exists.
# From a terminal that is at least a traceback. From a double-click or an
# editor's Run button the console holding it can close again immediately, and
# the whole failure reads as "nothing happens when I open it".
#
# TO BE CLEAR ABOUT WHAT THIS IS NOT: an earlier version of this check was
# committed as the fix for the app not starting. That was wrong. The app hung
# with every library present, because of a Tkinter resize-event loop, and that
# is fixed in common.py (FlowBar._schedule, WrapBar._schedule and
# _on_toplevel_resize). This check does not prevent a single hang. It only
# makes a genuinely missing library say so in a window that stays open.
import os
import sys

# One thread for numpy's linear algebra, set BEFORE numpy is first imported
# (common.py imports it). Its default -- a thread per core, busy-waiting
# between calls -- buys nothing on the small matrices these solvers build,
# and next to any other busy program it collapses: measured 2026-10-02, the
# Cable Web at-rest preview took over five minutes with the default pool
# beside one other CPU-bound process, and 11.6 s with one thread. A user
# who wants more threads sets these variables; they are only defaults.
for _var in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_var, '1')

MIN_PYTHON = (3, 9)

# (module, pip name or None if it is not on PyPI, what it is needed for,
#  {platform: how to get it} or None when pip is the whole answer)
HARD_DEPENDENCIES = (
    ('tkinter', None, 'the entire user interface -- every window and widget',
     {'linux': 'sudo apt install python3-tk   (Debian/Ubuntu)\n'
               '  or: sudo dnf install python3-tkinter   (Fedora)',
      'darwin': 'brew install python-tk\n'
                '  or use the python.org build, which bundles it',
      'win32': 'rerun the Python installer, choose Modify, '
               'and tick "tcl/tk and IDLE"'}),
    ('numpy', 'numpy', 'every solver; common.py imports it at module scope',
     None),
    ('scipy', 'scipy', 'the sparse 3D solver and the cable-web convergence',
     None),
)


def environment_problems():
    """[(title, [detail lines])] for this interpreter -- empty when fine."""
    problems = []
    if sys.version_info < MIN_PYTHON:
        problems.append((
            'Python %d.%d or newer is required' % MIN_PYTHON,
            ['This interpreter is Python %s' % sys.version.split()[0],
             'at %s' % sys.executable]))
    import importlib
    for mod, pip_name, why, hints in HARD_DEPENDENCIES:
        try:
            importlib.import_module(mod)
        except Exception as exc:
            detail = ['%s: %s' % (type(exc).__name__, exc),
                      'Needed for: %s' % why]
            if pip_name:
                detail.append('Install it into THIS interpreter:')
                detail.append('  "%s" -m pip install %s'
                              % (sys.executable, pip_name))
            if hints:
                detail.append('On this platform (%s):' % sys.platform)
                detail.append('  %s' % hints.get(
                    sys.platform,
                    hints.get('linux', 'see your Python distribution')))
            detail.append('Interpreter: %s' % sys.executable)
            problems.append(('%s is missing' % mod, detail))
    return problems


def report_problems(problems):
    """Say it on stderr, and in a window when there is any way to show one."""
    lines = ['STRUCTURAL SYMULATOR SOLVER cannot start.', '']
    for title, detail in problems:
        lines.append(title)
        lines.extend('    ' + d for d in detail)
        lines.append('')
    lines.append('See REPORTS AND GUIDES/RUNNING_THE_APP.md, or run:')
    lines.append('  "%s" tools/doctor.py' % sys.executable)
    text = '\n'.join(lines)
    try:
        sys.stderr.write(text + '\n')
        sys.stderr.flush()
    except Exception:
        pass
    # A message box only works when tkinter is the thing that is present.
    # When tkinter is what is missing, stderr above is all there is.
    try:
        import tkinter as _tk
        from tkinter import messagebox as _mb
        _root = _tk.Tk()
        _root.withdraw()
        _mb.showerror('STRUCTURAL SYMULATOR SOLVER', text)
        _root.destroy()
    except Exception:
        pass
    return text


# Only when run as a program. Importing main (tests/tools/appdiag.py builds the
# window with main.App directly) must not check anything or exit.
if __name__ == '__main__':
    _problems = environment_problems()
    if _problems:
        report_problems(_problems)
        raise SystemExit(1)

import tkinter as tk
from tkinter import ttk

import units
import about
import appinfo

from apps.truss.truss_app import TrussApp
from apps.beam.beam_app import BeamApp
from apps.arch.arch_app import ArchApp
from apps.cable.cable_app import CableApp
from apps.cable_web.cable_web_app import CableWebApp
from apps.perforated_beam.perforated_beam_app import PerforatedBeamApp
from apps.stereo.stereo_app import StereoApp
from apps.shell.shell_app import ShellApp

class App:
    def __init__(self, root):
        # root is always tk.Tk() when launched from __main__
        try:
            root.title(appinfo.window_title(tab='Truss'))
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
        self.about_btn = tk.Button(self.units_bar, text='About…',
                                   font=('Helvetica', 8), relief='flat',
                                   bg='#ebebea',
                                   command=lambda: about.show_about(root))
        self.about_btn.pack(side='right', padx=8, pady=2)

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
        shell_tab = tk.Frame(nb)
        nb.add(truss_tab, text='Truss')
        nb.add(beam_tab, text='Beam')
        nb.add(arch_tab, text='Arch')
        nb.add(cable_tab, text='Cable')
        nb.add(cable_web_tab, text='Cable Web')
        nb.add(perforated_beam_tab, text='Perforated Beam')
        nb.add(stereo_tab, text='Stereo')
        nb.add(shell_tab, text='Shell (RC)')

        truss_app = TrussApp(truss_tab)
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
        stereo_app = StereoApp(stereo_tab)
        shell_app = ShellApp(shell_tab)
        shell_app.pack(fill='both', expand=True)

        # The window title names the version and date, and the Excel file
        # the tab in front is drawing -- or "<tab> drawing" when none is
        # (appinfo.window_title). Each tab keeps its own `document_name`;
        # the title follows the tab in front and any file opened in it.
        self.root, self.nb = root, nb
        self.tab_apps = [('Truss', truss_app), ('Beam', beam_app),
                         ('Arch', arch_app), ('Cable', cable_app),
                         ('Cable Web', cable_web_app),
                         ('Perforated Beam', perforated_beam_app),
                         ('Stereo', stereo_app), ('Shell (RC)', shell_app)]
        self._build_info = appinfo.build_info()
        nb.bind('<<NotebookTabChanged>>', lambda _e: self.refresh_title())
        self.refresh_title()

    def current_title(self):
        try:
            name, app = self.tab_apps[self.nb.index('current')]
        except (tk.TclError, IndexError):
            name, app = self.tab_apps[0]
        doc = getattr(app, 'document_name', None)
        return appinfo.window_title(doc, tab=name, info=self._build_info)

    def refresh_title(self):
        """Set the title from the tab in front; again every half second, so
        a file opened (or a drawing cleared) shows without every tab having
        to tell the window."""
        try:
            title = self.current_title()
            if self.root.title() != title:
                self.root.title(title)
            pending = getattr(self, '_title_after', None)
            if pending is not None:
                self.root.after_cancel(pending)
            self._title_after = self.root.after(500, self.refresh_title)
        except (tk.TclError, AttributeError):
            pass


# ═══════════════════════════════════════════════════════════════════════════════
def _fit_window_to_screen(root, want=(1440, 900), margin=(80, 120)):
    """Open at a sensible size that actually fits the display.

    Without this the toplevel takes its size from its content, which measured
    1279x1653 -- half of it below the bottom of a 1080p screen, with the tab
    strip visible and the controls not. Tk cannot know the screen is smaller
    than the content; it just honours the request.

    Clamping here is a convenience, NOT the fix for the startup hang that
    used to happen with no geometry set -- that was a relayout loop and is
    fixed in common.py._schedule. Do not remove this and assume the hang is
    back, and do not remove that and assume this covers it.
    """
    try:
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w = max(900, min(want[0], sw - margin[0]))
        h = max(600, min(want[1], sh - margin[1]))
        root.geometry('%dx%d' % (w, h))
        root.minsize(900, 600)
    except Exception:
        pass            # a size we could not set is not worth failing over


def _show_startup_failure(exc):
    """Put a traceback where a double-click user can actually read it.

    Everything above has imported, so tkinter is present and a window is
    possible. Without this, any exception while the tabs are being built
    prints to a console that a double-click launch closes immediately, and
    the app simply "does nothing" -- the single least diagnosable symptom
    this program has.
    """
    import traceback
    detail = traceback.format_exc()
    try:
        sys.stderr.write(detail)
        sys.stderr.flush()
    except Exception:
        pass
    try:
        from tkinter import messagebox
        messagebox.showerror(
            'STRUCTURAL SYMULATOR SOLVER failed to start',
            '%s: %s\n\n%s\n\nThe full traceback is above this dialog in the '
            'terminal, and in REPORTS AND GUIDES/RUNNING_THE_APP.md there is '
            'what to do about it.' % (type(exc).__name__, exc, detail[-1500:]))
    except Exception:
        pass


if __name__ == '__main__':
    root = tk.Tk()
    _fit_window_to_screen(root)
    try:
        App(root)
    except Exception as exc:
        _show_startup_failure(exc)
        raise SystemExit(1)
    root.mainloop()