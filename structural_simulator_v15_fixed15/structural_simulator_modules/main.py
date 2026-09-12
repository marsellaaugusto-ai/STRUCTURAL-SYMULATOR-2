"""
main.py — entry point. Wires the four tabs (Truss, Beam, Arch, Cable) into
one ttk.Notebook. Run this file to launch the app:

    python main.py

All five module files (common.py, truss_app.py, beam_app.py, arch_app.py,
cable_app.py, main.py) must stay together in the same folder -- they import
each other by plain module name, not as an installed package.
"""
import tkinter as tk
from tkinter import ttk

from apps.truss.truss_app import TrussApp
from apps.beam.beam_app import BeamApp
from apps.arch.arch_app import ArchApp
from apps.cable.cable_app import CableApp
from apps.cable_web.cable_web_app import CableWebApp

class App:
    def __init__(self, root):
        # root is always tk.Tk() when launched from __main__
        try:
            root.title('Structural Engineering Calculator')
            root.resizable(True, True)
        except Exception:
            pass   # safety: never called with a Frame

        style = ttk.Style()
        try:
            style.theme_use('clam')
        except Exception:
            pass

        nb = ttk.Notebook(root)
        nb.pack(fill='both', expand=True)

        truss_tab = tk.Frame(nb)
        beam_tab = tk.Frame(nb)
        arch_tab = tk.Frame(nb)
        cable_tab = tk.Frame(nb)
        cable_web_tab = tk.Frame(nb)
        nb.add(truss_tab, text='Truss')
        nb.add(beam_tab, text='Beam')
        nb.add(arch_tab, text='Arch')
        nb.add(cable_tab, text='Cable')
        nb.add(cable_web_tab, text='Cable Web')

        TrussApp(truss_tab)
        beam_app = BeamApp(beam_tab)
        beam_app.pack(fill='both', expand=True)
        arch_app = ArchApp(arch_tab)
        arch_app.pack(fill='both', expand=True)
        cable_app = CableApp(cable_tab)
        cable_app.pack(fill='both', expand=True)
        cable_web_app = CableWebApp(cable_web_tab)
        cable_web_app.pack(fill='both', expand=True)


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()