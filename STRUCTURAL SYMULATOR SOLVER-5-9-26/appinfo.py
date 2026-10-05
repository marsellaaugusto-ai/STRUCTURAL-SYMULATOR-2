"""The app's name, version and date, and the window title made from them.

The title reads

    Structural Simulator v31 · 03/10/2026 — roof_iterations.xlsx

-- the version and the date of the build, then the Excel file the active tab
is drawing, or "<tab> drawing" (Stereo drawing, Truss drawing ...) while it
draws something no file holds.

An EDITION -- a line of work taken off a released version and still being
edited -- sits next to the version:

    Structural Simulator v32 st01 · 05/10/2026 — roof_iterations.xlsx

so a window cannot be mistaken for the release it came from. No edition
means the reference build, and the title reads exactly as it always did.

The version, date and edition come from BUILD_STAMP.txt, which
tools/build_release.py writes into every archive it builds. A working copy
has no stamp: they are then read from build_release.py (APP_VERSION and
APP_EDITION, the one place each lives) and the date is that of the newest
source file.
"""
import os
import re
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_NAME = 'Structural Simulator'
STAMP_FILE = 'BUILD_STAMP.txt'
# day/month/year, as dates are read where the app is used
DATE_FORMAT = '%d/%m/%Y'


def _release_script():
    try:
        with open(os.path.join(APP_DIR, 'tools', 'build_release.py'),
                  encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def _source_version():
    m = re.search(r'^APP_VERSION\s*=\s*(\d+)', _release_script(), re.M)
    return int(m.group(1)) if m else None


def _source_edition():
    """APP_EDITION from the release script: 'st01', or None for the
    reference build (where it is written as None, not deleted)."""
    m = re.search(r'^APP_EDITION\s*=\s*(None|[\'"]([^\'"]*)[\'"])',
                  _release_script(), re.M)
    if not m or m.group(1) == 'None':
        return None
    return m.group(2) or None


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
    """(version or None, date as time.struct_time) of this copy.

    Two elements, as it has always been: `main.py` keeps the result and
    hands it back to `window_title`, and widening the tuple would break
    every caller that unpacks it. The edition is its own question --
    `edition()` -- because it is read from the same two places but is not
    part of the version.
    """
    try:
        with open(os.path.join(APP_DIR, STAMP_FILE), encoding='utf-8') as f:
            ver, day = f.read().split()[:2]
        return int(ver), time.strptime(day, '%Y-%m-%d')
    except (OSError, ValueError):
        return _source_version(), time.localtime(_newest_source_time())


_UNREAD = object()
_edition = _UNREAD


def _this_edition():
    """'st01' for an edited line of work, None for the reference build.

    Read once and kept: the title is rebuilt on every tab change, and this
    would otherwise open a file each time to answer a question whose answer
    cannot change while the app is running.
    """
    global _edition
    if _edition is _UNREAD:
        try:
            with open(os.path.join(APP_DIR, STAMP_FILE), encoding='utf-8') as f:
                parts = f.read().split()
            _edition = parts[2] if len(parts) > 2 else None
        except OSError:
            _edition = _source_edition()
    return _edition


#: What this copy is. `window_title` takes an `edition` argument that shadows
#: the name inside it, so the lookup lives under a private name and this is
#: the one callers use.
edition = _this_edition


def stamp_text(version, when=None, edition=None):
    """What BUILD_STAMP.txt holds: '32 2026-10-03 st01', or two fields when
    there is no edition -- which is what a stamp written before editions
    existed looks like, and it still reads correctly."""
    out = '%d %s' % (version, time.strftime('%Y-%m-%d', when or
                                            time.localtime()))
    return out + (' %s\n' % edition if edition else '\n')


def window_title(document=None, tab=None, info=None, edition=_UNREAD):
    """'Structural Simulator v32 st01 · 03/10/2026 — <document>', the
    document being the Excel file the active tab draws, or '<tab> drawing'.

    `edition` defaults to whatever this copy is; pass None for the reference
    rendering, or a string to force one.
    """
    ver, when = info or build_info()
    mark = _this_edition() if edition is _UNREAD else edition
    head = APP_NAME + (' v%d' % ver if ver else '')
    if ver and mark:
        head += ' ' + mark
    head += ' · ' + time.strftime(DATE_FORMAT, when)
    doc = document or ('%s drawing' % tab if tab else None)
    return head + (' — ' + doc if doc else '')
