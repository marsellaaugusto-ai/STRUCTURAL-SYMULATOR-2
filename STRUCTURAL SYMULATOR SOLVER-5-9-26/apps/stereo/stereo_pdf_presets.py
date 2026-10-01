"""Saved PDF settings (round 2, item 8).

A preset is everything that shapes a report besides the model: which sheet
groups it has, the drawing scale, whether it opens with a cover, the
project details the cover carries, and how the Groups PDF is put together
(by group NAME, so it applies to another file with the same groups). Kept
in one JSON file in the user's home, so a preset made today is there for
the next model -- the point of saving it.
"""
import json
import os

ENV = 'STEREO_PDF_PRESETS'


def store_path():
    """Where the presets live: $STEREO_PDF_PRESETS, else
    ~/.structural_simulator/pdf_presets.json."""
    p = os.environ.get(ENV)
    if p:
        return p
    return os.path.join(os.path.expanduser('~'), '.structural_simulator',
                        'pdf_presets.json')


def load(path=None):
    """{name: preset}; empty if there is no store yet or it cannot be
    read (a damaged file must not stop an export)."""
    path = path or store_path()
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_all(presets, path=None):
    path = path or store_path()
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(presets, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def put(name, preset, path=None):
    presets = load(path)
    presets[name] = preset
    save_all(presets, path)
    return presets


def remove(name, path=None):
    presets = load(path)
    presets.pop(name, None)
    save_all(presets, path)
    return presets


def make(sheets, view=None, cover=False, project=None, groups_pdf=None,
         group_names=None):
    """A preset from the current choices. `groups_pdf` items carry group
    ids, which mean nothing in another file: they are stored by name."""
    gp = None
    if groups_pdf:
        names = group_names or {}
        gp = {'mode': groups_pdf.get('mode', 'one'),
              'sheets': sorted(groups_pdf.get('sheets') or ()),
              'items': [{'name': names.get(it.get('gid'), it.get('title')),
                         'title': it.get('title'),
                         'sheets': (None if it.get('sheets') is None
                                    else sorted(it['sheets'])),
                         'on': bool(it.get('on', True))}
                        for it in groups_pdf.get('items', ())]}
    return {'sheets': sorted(sheets or ()),
            'view': dict(view or {'zoom': 1.0, 'ratio': None}),
            'cover': bool(cover),
            'project': dict(project or {}),
            'groups_pdf': gp}


def groups_pdf_for(preset, groups_by_name):
    """The preset's Groups PDF choice, with group names turned back into
    this file's group ids; groups it names that this file does not have are
    left out. None if the preset has none."""
    gp = (preset or {}).get('groups_pdf')
    if not gp:
        return None
    items = []
    for it in gp.get('items', ()):
        name = it.get('name')
        if name in groups_by_name:
            items.append({'gid': groups_by_name[name],
                          'title': it.get('title') or name,
                          'sheets': (None if it.get('sheets') is None
                                     else set(it['sheets'])),
                          'on': bool(it.get('on', True))})
    return {'mode': gp.get('mode', 'one'), 'sheets': set(gp.get('sheets')
                                                         or ()),
            'items': items}
