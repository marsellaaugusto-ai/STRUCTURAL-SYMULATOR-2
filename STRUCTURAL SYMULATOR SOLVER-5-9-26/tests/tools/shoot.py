"""shoot.py -- run the app on a headless display and photograph it.

There is no screen in a cloud container, and Tk needs one, so every
"can I see it?" used to end in a description instead of a picture. This
starts a virtual display, builds the real app on it, optionally drives it
(generate, analyze, switch modes) and writes PNGs.

    python3.12 tests/tools/shoot.py --out /tmp/shots
    python3.12 tests/tools/shoot.py --tab Stereo --generate --analyze \
        --modes build,shape,support,analyse --out /tmp/shots

It is the same app the user runs: it imports main.App, or one tab's class
directly with --tab, and touches nothing.

REQUIREMENTS, and why they are stated rather than assumed:
  * an interpreter WITH tkinter. In this container that is python3.12
    (`apt install python3-tk` installed _tkinter only for 3.12), while the
    default `python3` is 3.11 and has no Tk at all. Run this file with the
    interpreter that has it or it exits with that message rather than an
    ImportError three frames deep.
  * numpy and scipy for that same interpreter (requirements.txt).
  * Xvfb and ImageMagick's `import` on PATH
    (`apt install xvfb imagemagick`).

A note on timing: Tk draws when it is pumped, not when it is told to, so
every shot pumps the event loop, sleeps, and pumps again. Without the
sleep the canvas is photographed half-drawn -- which looks exactly like a
rendering bug and is not one.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # the app root


def _require(cond, msg):
    if not cond:
        sys.exit('shoot.py: ' + msg)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', default='shots', help='directory for the PNGs')
    ap.add_argument('--tab', default=None,
                    help='one tab by name (Truss, Beam, Arch, Cable, Cable Web, '
                         'Perforated Beam, Stereo). Omitted: the whole app, every tab.')
    ap.add_argument('--size', default='1700x960')
    ap.add_argument('--display', default=os.environ.get('DISPLAY') or ':99')
    ap.add_argument('--generate', action='store_true', help='call the tab\'s _generate')
    ap.add_argument('--analyze', action='store_true', help='call the tab\'s _analyze')
    ap.add_argument('--modes', default='', help='comma-separated mode keys to visit')
    ap.add_argument('--prefix', default='')
    args = ap.parse_args()

    _require(shutil.which('Xvfb'), 'Xvfb is not on PATH (apt install xvfb)')
    _require(shutil.which('import'), "ImageMagick's `import` is not on PATH "
                                     '(apt install imagemagick)')
    try:
        import tkinter                                   # noqa: F401
    except ImportError:
        sys.exit('shoot.py: this interpreter (%s) has no tkinter. In this container '
                 'use /usr/bin/python3.12.' % sys.version.split()[0])

    os.makedirs(args.out, exist_ok=True)
    w, h = args.size.split('x')

    xvfb = None
    if not os.environ.get('DISPLAY'):
        xvfb = subprocess.Popen(['Xvfb', args.display, '-screen', '0',
                                 '%sx%sx24' % (w, h)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2.0)
    os.environ['DISPLAY'] = args.display

    try:
        _run(args, w, h)
    finally:
        if xvfb is not None:
            xvfb.terminate()


def _run(args, w, h):
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.geometry('%sx%s+0+0' % (w, h))
    try:
        ttk.Style().theme_use('clam')
    except Exception:
        pass

    def pump(n=18):
        for _ in range(n):
            root.update_idletasks()
            root.update()

    def shot(name):
        pump()
        time.sleep(0.5)          # see the note in the module docstring
        pump(8)
        path = os.path.join(args.out, args.prefix + name + '.png')
        subprocess.run(['import', '-display', os.environ['DISPLAY'], '-window',
                        'root', path], check=True)
        print('wrote', path, flush=True)

    if args.tab is None:
        from main import App
        App(root)
        pump(25)
        nb = [c for c in root.winfo_children() if c.winfo_class() == 'TNotebook'][0]
        for t in nb.tabs():
            nb.select(t)
            shot('tab_' + nb.tab(t, 'text').lower().replace(' ', '_'))
        root.destroy()
        return

    app = _one_tab(root, args.tab)
    pump(25)
    if args.generate:
        app._generate(push_undo=False)
        pump(20)
        shot('generated')
    if args.analyze:
        app._analyze()
        pump(25)
        shot('analyzed')
    for key in [m.strip() for m in args.modes.split(',') if m.strip()]:
        app._set_mode(key)
        pump(16)
        shot('mode_' + key)
    if not (args.generate or args.analyze or args.modes):
        shot('tab')
    root.destroy()


def _one_tab(root, name):
    """Build ONE tab's class into a full-window frame.

    Not through main.App: the tabs are not all widgets (StereoApp takes a
    parent and packs itself), so there is no way to reach one back out of
    the notebook's widget tree. Naming the class is shorter than searching
    for it and it fails loudly on a typo.
    """
    import tkinter as tk
    frame = tk.Frame(root)
    frame.pack(fill='both', expand=True)
    key = name.lower().replace(' ', '_')
    table = {
        'truss': ('apps.truss.truss_app', 'TrussApp', False),
        'beam': ('apps.beam.beam_app', 'BeamApp', True),
        'arch': ('apps.arch.arch_app', 'ArchApp', True),
        'cable': ('apps.cable.cable_app', 'CableApp', True),
        'cable_web': ('apps.cable_web.cable_web_app', 'CableWebApp', True),
        'perforated_beam': ('apps.perforated_beam.perforated_beam_app',
                            'PerforatedBeamApp', True),
        'stereo': ('apps.stereo.stereo_app', 'StereoApp', False),
    }
    if key not in table:
        sys.exit('shoot.py: unknown tab %r. One of: %s'
                 % (name, ', '.join(sorted(table))))
    mod, cls, packs_itself = table[key]
    import importlib
    app = getattr(importlib.import_module(mod), cls)(frame)
    if packs_itself:
        app.pack(fill='both', expand=True)
    return app


if __name__ == '__main__':
    main()
