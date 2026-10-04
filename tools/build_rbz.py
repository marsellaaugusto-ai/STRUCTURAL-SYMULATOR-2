#!/usr/bin/env python3
"""Assemble and verify the SketchUp .rbz for the extension.

    python3 tools/build_rbz.py [--out DIR]

A .rbz is just a zip whose root holds the loader .rb plus the extension's
support folder. Building it by hand is how the 0.1.0 release shipped without
model_import.rb/xlsx_reader.rb and raised LoadError on a menu item that
advertised itself, so this script also VERIFIES the archive before writing
it:

  * every .rb and icon in sketchup_extension/ is in the archive;
  * every `require File.join(MY_DIR, '...')` in the extension resolves to a
    file that is in the archive;
  * every icon path mentioned in main.rb is in the archive;
  * `ruby -c` passes on every .rb (skipped when ruby is unavailable).

Exits non-zero (and writes nothing) if any check fails.
"""
import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "sketchup_extension")
PACKAGE = "coordinate_coordinator_truss_app_amac"
LOADER = PACKAGE + ".rb"


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def extension_version():
    match = re.search(r"ex\.version\s*=\s*'([^']+)'", read(os.path.join(SRC, LOADER)))
    if not match:
        sys.exit("could not find ex.version in " + LOADER)
    return match.group(1)


def collect_files():
    """[(absolute path, archive name)] for everything that ships."""
    out = [(os.path.join(SRC, LOADER), LOADER)]
    for root, _dirs, names in os.walk(os.path.join(SRC, PACKAGE)):
        for name in sorted(names):
            if name.startswith("."):
                continue
            absolute = os.path.join(root, name)
            out.append((absolute, os.path.relpath(absolute, SRC).replace(os.sep, "/")))
    return sorted(out, key=lambda pair: pair[1])


def verify(files):
    names = {arcname for _abs, arcname in files}
    problems = []

    ruby_files = [(a, n) for a, n in files if n.endswith(".rb")]
    if not any(n == LOADER for _a, n in files):
        problems.append("loader %s missing" % LOADER)

    # requires must resolve
    for absolute, arcname in ruby_files:
        body = read(absolute)
        for required in re.findall(r"require File\.join\(MY_DIR, '([^']+)'\)", body):
            target = "%s/%s.rb" % (PACKAGE, required)
            if target not in names:
                problems.append("%s requires '%s' -> %s is not in the archive"
                                % (arcname, required, target))
        # icons referenced from File.join(MY_DIR, 'icons', '...')
        for icon in re.findall(r"File\.join\(MY_DIR, 'icons', '([^']+)'\)", body):
            target = "%s/icons/%s" % (PACKAGE, icon)
            if target not in names:
                problems.append("%s references icon %s, which is not in the archive"
                                % (arcname, target))

    # every source .rb must actually be shipped (catches a new file that was
    # written but never required/packaged)
    for root, _dirs, filenames in os.walk(SRC):
        for name in filenames:
            if not name.endswith(".rb"):
                continue
            arcname = os.path.relpath(os.path.join(root, name), SRC).replace(os.sep, "/")
            if arcname not in names:
                problems.append("source file %s is not in the archive" % arcname)

    # syntax check
    if shutil.which("ruby"):
        for absolute, arcname in ruby_files:
            result = subprocess.run(["ruby", "-c", absolute],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if result.returncode != 0:
                problems.append("ruby -c failed for %s:\n%s"
                                % (arcname, result.stdout.decode("utf-8", "replace")))
    else:
        print("note: ruby not found, skipping the syntax check")

    # every .rb must be inside the extension namespace (SketchUp extensions
    # share one Ruby process; a top-level class would collide)
    for absolute, arcname in ruby_files:
        if "module CoordinateCoordinatorTrussAppAMAC" not in read(absolute):
            problems.append("%s does not open the CoordinateCoordinatorTrussAppAMAC module"
                            % arcname)

    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(REPO, "dist"),
                        help="directory to write the .rbz into (default: dist/)")
    parser.add_argument("--name", default=None, help="override the archive file name")
    args = parser.parse_args()

    files = collect_files()
    problems = verify(files)
    if problems:
        print("FAILED verification:")
        for problem in problems:
            print("  - " + problem)
        return 1

    version = extension_version()
    stamp = datetime.date.today().isoformat()
    name = args.name or ("CoordinateCoordinatorTrussAppAMAC_v%s_%s.rbz" % (version, stamp))
    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, name)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for absolute, arcname in files:
            zf.write(absolute, arcname)

    # Read the finished archive back and confirm it opens cleanly.
    with zipfile.ZipFile(out_path) as zf:
        bad = zf.testzip()
        if bad is not None:
            print("archive is corrupt at " + bad)
            return 1
        listed = zf.namelist()

    print("wrote %s (%d files, %.1f KB), extension version %s"
          % (out_path, len(listed), os.path.getsize(out_path) / 1024.0, version))
    for entry in sorted(listed):
        print("   " + entry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
