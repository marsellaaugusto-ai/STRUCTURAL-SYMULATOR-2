"""The app's name, version, iteration and date, and the window title made
from them.

The title reads

    Structural Simulator v32 t 01 · 05-10-26 — roof_iterations.xlsx

-- the app version, the ITERATION within it, and the date of the build,
then the Excel file the active tab is drawing, or "<tab> drawing" (Stereo
drawing, Truss drawing ...) while it draws something no file holds.

THE ITERATION. `v32 t 01 05-10-26` is the name of one round of changes to
v32: `t` for the tab the round was about (Truss), `01` the round's number
within v32, and the date it was cut, written day-month-year like every
other date this app shows. The letter is the tab, so a round of Stereo work
would be `v32 s 01 ...`. The point is that two builds of v32 handed out a
week apart can be told apart by name, which a bare "v32" cannot do.

The version, iteration and date come from BUILD_STAMP.txt, which
tools/build_release.py writes into every archive it builds. A working copy
has no stamp: version and iteration are then read from build_release.py
(APP_VERSION / APP_ITERATION, the one place those numbers live) and the
date is that of the newest source file.
"""
import os
import re
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_NAME = 'Structural Simulator'
STAMP_FILE = 'BUILD_STAMP.txt'
# day/month/year, as dates are read where the app is used
DATE_FORMAT = '%d/%m/%Y'
# The same date in the compact form the iteration name uses: 05-10-26.
ITERATION_DATE_FORMAT = '%d-%m-%y'
# Which tab a round of changes was about. One letter, because it sits
# inside a name people type and read aloud.
ITERATION_LETTER = 't'


def _source_version():
    """(version, iteration) from build_release.py, for a working copy with
    no BUILD_STAMP.txt. Either may be None."""
    try:
        with open(os.path.join(APP_DIR, 'tools', 'build_release.py'),
                  encoding='utf-8') as f:
            src = f.read()
    except OSError:
        return None, None
    ver = re.search(r'^APP_VERSION\s*=\s*(\d+)', src, re.M)
    it = re.search(r'^APP_ITERATION\s*=\s*(\d+)', src, re.M)
    return (int(ver.group(1)) if ver else None,
            int(it.group(1)) if it else None)


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
    """(version or None, date as time.struct_time, iteration or None).

    The stamp is '<version> <date>' with an optional third field '<letter>
    <number>' run together, e.g. '32 2026-10-05 t01'. The third field is
    optional so a stamp written before iterations existed still reads, and
    so does an archive built by an older copy of build_release.py.
    """
    try:
        with open(os.path.join(APP_DIR, STAMP_FILE), encoding='utf-8') as f:
            parts = f.read().split()
        ver, day = int(parts[0]), time.strptime(parts[1], '%Y-%m-%d')
    except (OSError, ValueError, IndexError):
        ver, it = _source_version()
        return ver, time.localtime(_newest_source_time()), it
    it = None
    if len(parts) > 2:
        m = re.match(r'[A-Za-z](\d+)$', parts[2])
        if m:
            it = int(m.group(1))
    return ver, day, it


def iteration_name(version, iteration, when=None, letter=ITERATION_LETTER):
    """'v32 t 01 05-10-26' -- what one round of changes is called.

    None when there is no iteration to name, so a caller can fall back to
    the plain version rather than printing a half-formed name.
    """
    if version is None or iteration is None:
        return None
    return 'v%d %s %02d %s' % (
        version, letter, iteration,
        time.strftime(ITERATION_DATE_FORMAT, when or time.localtime()))


def current_iteration_name():
    """`iteration_name` for this copy, or None."""
    ver, when, it = build_info()
    return iteration_name(ver, it, when)


def stamp_text(version, when=None, iteration=None, letter=ITERATION_LETTER):
    """What BUILD_STAMP.txt holds: '32 2026-10-05 t01'."""
    out = '%d %s' % (version, time.strftime('%Y-%m-%d', when or
                                            time.localtime()))
    if iteration is not None:
        out += ' %s%02d' % (letter, iteration)
    return out + '\n'


def window_title(document=None, tab=None, info=None):
    """'Structural Simulator v32 t 01 · 05-10-26 — <document>', the
    document being the Excel file the active tab draws, or '<tab>
    drawing'.

    With no iteration recorded it falls back to the older
    'Structural Simulator v32 · 03/10/2026' form, so an archive stamped by
    an older build_release.py still titles itself sensibly.
    """
    got = tuple(info) if info else build_info()
    ver, when = got[0], got[1]
    it = got[2] if len(got) > 2 else None
    head = APP_NAME
    if ver and it is not None:
        head += ' v%d %s %02d · %s' % (
            ver, ITERATION_LETTER, it,
            time.strftime(ITERATION_DATE_FORMAT, when))
    else:
        head += (' v%d' % ver if ver else '')
        head += ' · ' + time.strftime(DATE_FORMAT, when)
    doc = document or ('%s drawing' % tab if tab else None)
    return head + (' — ' + doc if doc else '')
