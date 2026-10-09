#!/usr/bin/env python3
"""Check workbooks for group facts that an import would have dropped.

WHY THIS EXISTS. For a while the Stereo tab wrote a Scene sheet that did
not record a group's own facts -- whether it is left out of the analysis,
which iteration it belongs to, which fabricated part it is a copy of --
while preferring that sheet over the Groups sheet, which did record them.
Importing such a file put every excluded group back INTO the analysis, and
nothing on screen said so. Re-exporting then made it permanent.

The app no longer does that: it reads the facts off the Groups sheet when
the Scene sheet has none. But a file that was imported and re-saved while
the bug was live has already lost them, and only you know what it should
have said. This tells you which files to look at.

    python3 tools/check_excluded_groups.py <file-or-folder> [...]

Reads only; nothing is written or changed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FLAGS = ('excluded', 'iteration', 'stage', 'position', 'component')


def workbooks(targets):
    for target in targets:
        if os.path.isdir(target):
            for here, _dirs, files in os.walk(target):
                for name in sorted(files):
                    if name.lower().endswith('.xlsx') and \
                            not name.startswith('~$'):
                        yield os.path.join(here, name)
        elif target.lower().endswith('.xlsx'):
            yield target


def look(path):
    """(verdict, detail) for one workbook."""
    import openpyxl
    from apps.stereo import stereo_groups_excel as sge
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:                          # noqa: BLE001
        return 'unreadable', str(exc)
    sheets = set(wb.sheetnames)
    has_scene = 'Scene' in sheets
    try:
        rows = sge.read_groups_sheet(wb)
    except Exception as exc:                          # noqa: BLE001
        return 'unreadable', 'Groups sheet: %s' % exc
    finally:
        wb.close()

    if rows is None:
        return 'no groups', 'no Groups sheet -- nothing to lose'

    marked = {}
    for r in rows:
        for key in FLAGS:
            v = r.get(key)
            if v not in (None, '') and str(v).strip():
                marked.setdefault(key, []).append(
                    str(r.get('name') or r.get('id')))
    if not has_scene:
        return ('ok', 'no Scene sheet, so the Groups sheet was always read'
                      '%s' % (' (%s)' % _spell(marked) if marked else ''))
    if not marked:
        return ('check', 'has a Scene sheet and NO group facts at all. '
                         'If this model should have excluded groups, they '
                         'were lost -- re-set them and save again.')
    return ('ok', 'has a Scene sheet, and the Groups sheet still carries '
                  '%s' % _spell(marked))


def _spell(marked):
    return '; '.join('%s: %s' % (k, ', '.join(v[:6]) +
                                 (' …' if len(v) > 6 else ''))
                     for k, v in sorted(marked.items()))


def main(argv):
    targets = argv[1:]
    if not targets:
        print(__doc__)
        return 2
    found = list(workbooks(targets))
    if not found:
        print('No .xlsx files under: %s' % ', '.join(targets))
        return 1
    worst = 0
    buckets = {'check': [], 'ok': [], 'no groups': [], 'unreadable': []}
    for path in found:
        verdict, detail = look(path)
        buckets[verdict].append((path, detail))
        if verdict == 'check':
            worst = 1
    for verdict, title in (
            ('check', 'WORTH A LOOK'),
            ('unreadable', 'COULD NOT READ'),
            ('ok', 'FINE'),
            ('no groups', 'NO GROUPS IN THE FILE')):
        rows = buckets[verdict]
        if not rows:
            continue
        print('\n%s  (%d)' % (title, len(rows)))
        for path, detail in rows:
            print('  %s' % path)
            print('      %s' % detail)
    print('\n%d workbook(s) read. Nothing was changed.' % len(found))
    return worst


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
