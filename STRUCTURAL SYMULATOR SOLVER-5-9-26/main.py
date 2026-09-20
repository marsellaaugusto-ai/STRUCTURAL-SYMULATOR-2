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
"""
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
from apps.shell.shell_app import ShellApp

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
        shell_tab = tk.Frame(nb)
        nb.add(truss_tab, text='Truss')
        nb.add(beam_tab, text='Beam')
        nb.add(arch_tab, text='Arch')
        nb.add(cable_tab, text='Cable')
        nb.add(cable_web_tab, text='Cable Web')
        nb.add(perforated_beam_tab, text='Perforated Beam')
        nb.add(stereo_tab, text='Stereo')
        nb.add(shell_tab, text='Shell (RC)')

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
        shell_app = ShellApp(shell_tab)
        shell_app.pack(fill='both', expand=True)


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()