"""The app's name, version and date, and the window title made from them.

The title reads

    Structural Simulator v31 · 03/10/2026 — roof_iterations.xlsx

-- the version and the date of the build, then the Excel file the active tab
is drawing, or "<tab> drawing" (Stereo drawing, Truss drawing ...) while it
draws something no file holds.

The version and date come from BUILD_STAMP.txt, which tools/build_release.py
writes into every archive it builds. A working copy has no stamp: the
version is then read from build_release.py (APP_VERSION, the one place the
number lives) and the date is that of the newest source file.
"""
import os
import re
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_NAME = 'Structural Simulator'
STAMP_FILE = 'BUILD_STAMP.txt'
# day/month/year, as dates are read where the app is used
DATE_FORMAT = '%d/%m/%Y'


def _source_version():
    try:
        with open(os.path.join(APP_DIR, 'tools', 'build_release.py'),
                  encoding='utf-8') as f:
            m = re.search(r'^APP_VERSION\s*=\s*(\d+)', f.read(), re.M)
        return int(m.group(1)) if m else None
    except OSError:
        return None


def _newest_source_time():
    newest = 0.0
    for top in ('apps', '.'):
        base = os.path.join(APP_DIR, top)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames
                           if d not in ('__pycache__', 'tests', '.git')]
            for fn in filenames:
                if fn.endswith('.py'):
                    try:
                        newest = max(newest, os.path.getmtime(
                            os.path.join(dirpath, fn)))
                    except OSError:
                        pass
            if top == '.':
                break           # the top folder only; apps/ was walked whole
    return newest or time.time()


def build_info():
    """(version or None, date as time.struct_time) of this copy."""
    try:
        with open(os.path.join(APP_DIR, STAMP_FILE), encoding='utf-8') as f:
            ver, day = f.read().split()[:2]
        return int(ver), time.strptime(day, '%Y-%m-%d')
    except (OSError, ValueError):
        return _source_version(), time.localtime(_newest_source_time())


def stamp_text(version, when=None):
    """What BUILD_STAMP.txt holds: '31 2026-10-03'."""
    return '%d %s\n' % (version, time.strftime('%Y-%m-%d', when or
                                               time.localtime()))


def window_title(document=None, tab=None, info=None):
    """'Structural Simulator v31 · 03/10/2026 — <document>', the document
    being the Excel file the active tab draws, or '<tab> drawing'."""
    ver, when = info or build_info()
    head = APP_NAME + (' v%d' % ver if ver else '')
    head += ' · ' + time.strftime(DATE_FORMAT, when)
    doc = document or ('%s drawing' % tab if tab else None)
    return head + (' — ' + doc if doc else '')
