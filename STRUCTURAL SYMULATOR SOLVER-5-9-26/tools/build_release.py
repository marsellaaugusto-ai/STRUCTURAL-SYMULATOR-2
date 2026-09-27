#!/usr/bin/env python3
"""Build the two things that get handed out: the SketchUp extension (.rbz)
and the whole-app archive (.zip).

Both used to be assembled by hand, and the shipped .rbz had drifted out of
step with sketchup_plugin/ as a result -- it was missing model_import.rb
and xlsx_reader.rb entirely, so the extension's own "Import from Stereo…"
command would raise LoadError the moment SketchUp loaded it. A build
script is the fix: it reads the plugin folder, so it cannot forget a file
that is there, and it refuses to write an archive that is missing a file
the loader requires.

    python3 tools/build_release.py            # both, into the app root
    python3 tools/build_release.py --rbz      # just the extension
    python3 tools/build_release.py --zip      # just the app archive
    python3 tools/build_release.py --check    # verify, write nothing

An .rbz IS a zip; SketchUp's Extension Manager just wants that extension.
Its layout is fixed: the loader .rb sits at the archive root beside a
folder of the same name holding everything else.
"""
import argparse
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)

PLUGIN_DIR = os.path.join(APP, 'sketchup_plugin')
PLUGIN_NAME = 'coordinate_coordinator_truss_app_amac'
RBZ_NAME = 'CoordinateCoordinatorTrussAppAMAC.rbz'

# Files the loader/main require by name. If one of these is not in the
# archive the extension is broken on load, so the build fails loudly
# instead of shipping it.
REQUIRED_RB = (
    f'{PLUGIN_NAME}.rb',
    f'{PLUGIN_NAME}/main.rb',
    f'{PLUGIN_NAME}/xlsx_writer.rb',
    f'{PLUGIN_NAME}/xlsx_reader.rb',
    f'{PLUGIN_NAME}/model_export.rb',
    f'{PLUGIN_NAME}/model_import.rb',
    f'{PLUGIN_NAME}/pick_tool.rb',
    f'{PLUGIN_NAME}/intersections.rb',
)

# What belongs in the app archive. Everything else under the app root is
# either generated (caches), an output someone happened to leave behind, or
# an archive of its own.
ZIP_NAME = 'structural_simulator_app.zip'
ZIP_INCLUDE_DIRS = ('apps', 'tests', 'sketchup_plugin', 'tools',
                    'REPORTS AND GUIDES',
                    # ships deliberately: launch.json is what makes F5 run
                    # the app from the right working directory, which is
                    # the difference between it starting and it not. It is
                    # therefore NOT in ZIP_SKIP_DIRS below.
                    '.vscode')
ZIP_INCLUDE_FILES = ('main.py', 'common.py', 'cirsoc_301.py', 'units.py',
                     'requirements.txt', RBZ_NAME,
                     # a real model to open straight after unpacking
                     'wave_like_structure_1.xlsx')
ZIP_SKIP_DIRS = {'__pycache__', '.pytest_cache', '.git', '.idea',
                 'node_modules', '.mypy_cache', '.ruff_cache'}
ZIP_SKIP_SUFFIX = ('.pyc', '.pyo', '.pyd', '.so', '.orig', '.rej', '.swp')


def plugin_files():
    """Every file under sketchup_plugin/, as (archive_name, disk_path)."""
    out = []
    loader = os.path.join(PLUGIN_DIR, f'{PLUGIN_NAME}.rb')
    if os.path.isfile(loader):
        out.append((f'{PLUGIN_NAME}.rb', loader))
    root = os.path.join(PLUGIN_DIR, PLUGIN_NAME)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in ZIP_SKIP_DIRS)
        for fn in sorted(filenames):
            if fn.endswith(ZIP_SKIP_SUFFIX) or fn.startswith('.'):
                continue
            disk = os.path.join(dirpath, fn)
            rel = os.path.relpath(disk, PLUGIN_DIR).replace(os.sep, '/')
            out.append((rel, disk))
    return out


def build_rbz(dest=None, check_only=False):
    files = plugin_files()
    names = {n for n, _ in files}
    missing = [r for r in REQUIRED_RB if r not in names]
    if missing:
        raise SystemExit('sketchup_plugin/ is missing required file(s): '
                         + ', '.join(missing))

    checked = ruby_syntax_check(files)

    dest = dest or os.path.join(APP, RBZ_NAME)
    if check_only:
        print(f'rbz would hold {len(files)} file(s)'
              + (f'; ruby -c passed on {checked}' if checked else
                 '; ruby not installed, syntax unchecked') + ':')
        for n, _ in files:
            print(f'    {n}')
        return dest, files

    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, disk in files:
            z.write(disk, name)
    verify_rbz(dest)
    print(f'{RBZ_NAME}: {len(files)} file(s), '
          f'{os.path.getsize(dest):,} bytes -> {dest}')
    return dest, files


def ruby_syntax_check(files):
    """`ruby -c` every .rb going into the archive, when ruby is available.

    A Ruby syntax error does not surface until SketchUp tries to load the
    extension, on someone else's machine, with nothing but a stack trace
    to go on. Skipped silently where ruby is not installed, since that is
    a build-host detail rather than a fault in the plugin.
    """
    import shutil
    import subprocess
    ruby = shutil.which('ruby')
    if not ruby:
        return None
    bad = []
    for name, disk in files:
        if not name.endswith('.rb'):
            continue
        p = subprocess.run([ruby, '-c', disk], capture_output=True, text=True)
        if p.returncode != 0:
            bad.append(f'{name}: {p.stderr.strip()}')
    if bad:
        raise SystemExit('ruby syntax errors:\n  ' + '\n  '.join(bad))
    return sum(1 for n, _ in files if n.endswith('.rb'))


def verify_rbz(path):
    """Re-open the built archive and check it against REQUIRED_RB.

    Verifying the ARCHIVE rather than the list that went into it is the
    point: that is the artefact SketchUp opens, and the last one shipped
    was missing files nobody re-read it to notice.
    """
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad is not None:
            raise SystemExit(f'{path}: corrupt entry {bad}')
        names = set(z.namelist())
        missing = [r for r in REQUIRED_RB if r not in names]
        if missing:
            raise SystemExit(f'{path} is missing: ' + ', '.join(missing))
        for name in names:
            if name.endswith('.rb'):
                src = z.read(name).decode('utf-8')
                if not src.strip():
                    raise SystemExit(f'{path}: {name} is empty')
    return True


def app_files():
    """Every file that belongs in the distributable app archive."""
    out = []
    for fn in ZIP_INCLUDE_FILES:
        disk = os.path.join(APP, fn)
        if os.path.isfile(disk):
            out.append((fn, disk))
    for d in ZIP_INCLUDE_DIRS:
        root = os.path.join(APP, d)
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(x for x in dirnames if x not in ZIP_SKIP_DIRS)
            for fn in sorted(filenames):
                if fn.endswith(ZIP_SKIP_SUFFIX):
                    continue
                disk = os.path.join(dirpath, fn)
                rel = os.path.relpath(disk, APP).replace(os.sep, '/')
                out.append((rel, disk))
    # stable order, no duplicates
    seen, uniq = set(), []
    for rel, disk in out:
        if rel not in seen:
            seen.add(rel)
            uniq.append((rel, disk))
    return sorted(uniq)


def build_zip(dest=None, check_only=False):
    files = app_files()
    names = {n for n, _ in files}
    for must in ('main.py', 'common.py', 'apps/stereo/stereo_app.py',
                 'apps/stereo/stereo_reports.py', RBZ_NAME):
        if must not in names:
            raise SystemExit(f'app archive would be missing {must}')

    dest = dest or os.path.join(APP, ZIP_NAME)
    if check_only:
        print(f'zip would hold {len(files)} file(s)')
        return dest, files

    root = os.path.basename(APP)
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel, disk in files:
            z.write(disk, f'{root}/{rel}')
    with zipfile.ZipFile(dest) as z:
        bad = z.testzip()
        if bad is not None:
            raise SystemExit(f'{dest}: corrupt entry {bad}')
    print(f'{ZIP_NAME}: {len(files)} file(s), '
          f'{os.path.getsize(dest):,} bytes -> {dest}')
    return dest, files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rbz', action='store_true', help='build only the .rbz')
    ap.add_argument('--zip', action='store_true', help='build only the .zip')
    ap.add_argument('--check', action='store_true',
                    help='list what would be built, write nothing')
    args = ap.parse_args(argv)

    do_rbz = args.rbz or not args.zip
    do_zip = args.zip or not args.rbz
    if do_rbz:
        build_rbz(check_only=args.check)
    if do_zip:
        # the archive carries the extension, so build that first
        build_zip(check_only=args.check)
    return 0


if __name__ == '__main__':
    sys.exit(main())
