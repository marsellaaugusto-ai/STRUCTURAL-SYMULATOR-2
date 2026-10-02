"""The third-party notices: who wrote the software this app runs on, and the
licence each of them ships under.

Almost every open-source licence lets the app be redistributed on one
condition: that each copyright notice and licence text goes with it. This
module gathers them from the environment the app actually runs in, so the
file can never fall behind a library upgrade:

  * every Python distribution the app uses (RUNTIME_ROOTS) and everything
    they in turn require, with the licence files each one ships in its
    .dist-info folder -- numpy's and scipy's include the native libraries
    their wheels bundle (OpenBLAS, LAPACK, libgfortran, libquadmath);
  * Python itself and Tcl/Tk, which pip knows nothing about.

Never hand-edit the output. Regenerate it from the environment being
shipped:

    python notices.py > THIRD_PARTY_NOTICES.txt

tools/build_release.py --customer does this by itself for every customer
archive, and the About box shows the same text.
"""
import glob
import importlib.metadata as md
import os
import re
import sys

# The distributions the app imports. numpy and scipy are required (see
# requirements.txt); the rest are used when present.
RUNTIME_ROOTS = ('numpy', 'scipy', 'openpyxl', 'matplotlib', 'pillow')

HEADER = """THIRD-PARTY SOFTWARE NOTICES

This product includes the following third-party software. Each component
is licensed under its own terms, reproduced in full below. These terms are
separate from, and are not changed by, the licence of this product.
"""

# FreeType (inside Pillow) is dual-licensed FTL / GPL-2; this product takes
# it under the FTL, which asks for this credit in the documentation.
FREETYPE_CREDIT = ('Portions of this software are copyright © The FreeType '
                   'Project (www.freetype.org). All rights reserved.')

_LICENCE_FILE = re.compile(r'(LICEN[CS]E|COPYING|NOTICE|AUTHORS)', re.I)
_RULE = '=' * 78


def _norm(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def _requirement_name(req):
    """'numpy<2.8,>=2.0.0' -> 'numpy'; None for an extra-only requirement."""
    if 'extra' in req.split(';', 1)[-1] and ';' in req:
        return None
    m = re.match(r'\s*([A-Za-z0-9][A-Za-z0-9._-]*)', req)
    return m.group(1) if m else None


def distributions(roots=RUNTIME_ROOTS):
    """Every installed distribution reachable from `roots`, by normalised
    name, in a stable (alphabetical) order. Roots that are not installed
    are skipped: the app runs without them."""
    seen, todo = {}, [r for r in roots]
    while todo:
        name = _norm(todo.pop())
        if name in seen:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        seen[name] = dist
        for req in dist.requires or []:
            dep = _requirement_name(req)
            if dep:
                todo.append(dep)
    return [seen[k] for k in sorted(seen)]


def _licence_name(dist):
    meta = dist.metadata
    expr = meta.get('License-Expression')
    if expr:
        return expr
    lic = (meta.get('License') or '').strip()
    if lic and '\n' not in lic and len(lic) < 80:
        return lic
    classifiers = [c.split('::')[-1].strip()
                   for c in meta.get_all('Classifier') or []
                   if c.startswith('License ::')]
    return ', '.join(classifiers) or 'see the licence text below'


def _url(dist):
    meta = dist.metadata
    for u in meta.get_all('Project-URL') or []:
        label, _, link = u.partition(',')
        if label.strip().lower() in ('homepage', 'source', 'source code',
                                     'repository', 'documentation'):
            return link.strip()
    return meta.get('Home-page') or ''


def _read(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read().strip()
    except OSError:
        return None


def licence_texts(dist):
    """[(file name, text)] for every licence file the distribution ships.
    A distribution installed by the operating system's package manager
    often drops them; its Debian 'copyright' file is used instead."""
    out, seen = [], set()
    for f in dist.files or []:
        s = str(f)
        base = os.path.basename(s)
        in_meta = '.dist-info' in s or '.egg-info' in s
        # In the metadata folder, any licence-like file; in the package
        # itself, only files named as licences -- matplotlib's font
        # licences (LICENSE_DEJAVU, LICENSE_STIX), scipy's Qhull and the
        # other vendored code.
        if in_meta and _LICENCE_FILE.search(base) or \
                re.search(r'\.dist-info/licenses/', s) or \
                not in_meta and re.match(r'(LICEN[CS]E|COPYING)', base, re.I):
            text = _read(dist.locate_file(f))
            if text and text not in seen:
                seen.add(text)
                out.append((s.split('-info/', 1)[-1], text))
    if not out:
        name = _norm(dist.metadata['Name'])
        for cand in ('/usr/share/doc/python3-%s/copyright' % name,
                     '/usr/share/doc/python3-%s/copyright'
                     % name.replace('python-', '')):
            text = _read(cand)
            if text:
                out.append(('copyright', text))
                break
    return out


def _python_licence():
    for cand in (os.path.join(sys.base_prefix, 'LICENSE.txt'),
                 os.path.join(sys.base_prefix, 'LICENSE'),
                 '/usr/lib/python%d.%d/LICENSE.txt' % sys.version_info[:2],
                 '/usr/share/doc/python%d.%d/copyright' % sys.version_info[:2]):
        text = _read(cand)
        if text:
            return text
    return None


def _tcl_tk_licence():
    """Tcl/Tk's 'license.terms', wherever this Python's Tcl keeps it."""
    cands = glob.glob(os.path.join(sys.base_prefix, 'tcl', 'tcl8*',
                                   'license.terms'))
    cands += glob.glob(os.path.join(sys.base_prefix, 'lib', 'tcl8*',
                                    'license.terms'))
    try:
        import tkinter
        lib = tkinter.Tcl().eval('info library')
        cands.insert(0, os.path.join(lib, 'license.terms'))
    except Exception:
        pass
    cands += ['/usr/share/doc/libtcl8.6/copyright',
              '/usr/share/doc/tcl8.6/copyright']
    for c in cands:
        text = _read(c)
        if text:
            return text
    return None


def _tcl_version():
    try:
        import tkinter
        return tkinter.Tcl().eval('info patchlevel')
    except Exception:
        return ''


def components(roots=RUNTIME_ROOTS):
    """One dict per component: name, version, licence, url, texts
    [(file, text)]. Python and Tcl/Tk first, then the distributions."""
    out = [{'name': 'Python', 'version': '%d.%d.%d' % sys.version_info[:3],
            'licence': 'PSF-2.0 (Python Software Foundation License)',
            'url': 'https://www.python.org/',
            'texts': [('LICENSE', t) for t in [_python_licence()] if t]},
           {'name': 'Tcl/Tk (tkinter)', 'version': _tcl_version(),
            'licence': 'TCL (BSD-style)', 'url': 'https://www.tcl-lang.org/',
            'texts': [('license.terms', t) for t in [_tcl_tk_licence()] if t]}]
    for d in distributions(roots):
        out.append({'name': d.metadata['Name'], 'version': d.version,
                    'licence': _licence_name(d), 'url': _url(d),
                    'texts': licence_texts(d)})
    return out


def missing(comps):
    """The components with no licence text at all: a release must not ship
    with any of these."""
    return [c['name'] for c in comps if not c['texts']]


def render(comps=None):
    comps = components() if comps is None else comps
    lines = [HEADER, 'Components:']
    for c in comps:
        lines.append('  - %s %s  (%s)' % (c['name'], c['version'],
                                          c['licence']))
    if any(_norm(c['name']) == 'pillow' for c in comps):
        lines += ['', FREETYPE_CREDIT]
    for c in comps:
        lines += ['', _RULE, '%s %s' % (c['name'], c['version']),
                  'Licence: %s' % c['licence']]
        if c['url']:
            lines.append('Website: %s' % c['url'])
        lines.append(_RULE)
        if not c['texts']:
            lines += ['', 'LICENCE TEXT NOT FOUND IN THIS ENVIRONMENT.']
        for fname, text in c['texts']:
            lines += ['', '--- %s ---' % fname, '', text]
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    comps = components()
    sys.stdout.write(render(comps))
    gone = missing(comps)
    if gone:
        sys.stderr.write('No licence text found for: %s\n' % ', '.join(gone))
        sys.exit(1)
