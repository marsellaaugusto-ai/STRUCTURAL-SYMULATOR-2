"""Saving and loading: two codecs over one record form, plus undo snapshots.

    JSON   the project format. Lossless, sorted, indented, diffable, and
           written atomically. This is what a model is saved as.
    EXCEL  an inspection and interchange format, written into a workbook
           beside the `Model` sheet the Stereo tab already exports, in the
           same `[SECTION]` + named-column style, so the two travel together
           and a person can read the structure of a model without the app.

Neither codec knows what a SceneObject is: both go through `records.py`.
Adding a third format means adding a codec, not a serialiser.

WHY JSON IS THE PROJECT FORMAT and Excel is not. A scene graph is a tree
with cross-references, variable-length geometry and free-form metadata. JSON
holds all three exactly. A spreadsheet holds the first two awkwardly and the
third not at all -- a mesh's vertex list has no fixed column count, and
`meta` is whatever the model put there. So the Excel form carries structure
and geometry in readable columns and packs `meta`, `overrides`, `vertices`
and `faces` into JSON cells, which is honest about the trade rather than
dropping them. Sections themselves stay where they already are: the `Model`
sheet, edited by column, as `stereo_groups_excel` does today.

ATOMIC WRITES. A save that is interrupted -- a full disk, a crash, a laptop
lid -- must not leave a half-written file where the model used to be. The
temp-file-then-replace dance below is the reason the previous save survives
a failed one. `os.replace` is atomic on every platform this app runs on.
"""
import json
import os
import tempfile

from apps.stereo.scene.records import (
    FORMAT, from_records, to_records, to_text,
)

#: What a saved scene file is called when nothing else is asked for.
SUFFIX = '.scene.json'

#: One sheet, three sections, in the style of the existing Model sheet.
SHEET = 'Scene'

# Excel's hard limit on the characters in one cell. A mesh big enough to pass
# it exists, so it is checked rather than discovered.
CELL_LIMIT = 32767


# ── JSON: the project format ───────────────────────────────────────────────

def save_json(doc, path, canonical=True):
    """Write `doc` to `path`. Returns `(object_map, definition_map)`.

    The maps come from the canonical renumber -- see
    SceneDocument.canonical_renumber for why a save renumbers at all and why
    the caller is handed the mapping rather than left to discover it.
    """
    data, obj_map, def_map = to_records(doc, canonical=canonical)
    write_text(path, to_text(data) + '\n')
    return obj_map, def_map


def load_json(path, strict=False):
    """Read a scene file. Returns `(doc, warnings, id_map)`."""
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(
            'this file is not readable as a scene file: %s (line %d). If it '
            'was written by this app, it was interrupted while saving -- the '
            'previous save is the one to go back to.' % (exc.msg, exc.lineno)
        ) from None
    except OSError as exc:
        raise ValueError('cannot read %s: %s' % (path, exc)) from None
    return from_records(data, strict=strict)


def write_text(path, text):
    """Write `text` to `path` atomically: a failed write keeps the old file.

    Written into the TARGET's own directory, not the system temp area, so
    the replace is a rename within one filesystem -- across filesystems
    `os.replace` falls back to a copy, which is exactly the non-atomic
    behaviour this is here to avoid.
    """
    path = os.fspath(path)
    folder = os.path.dirname(os.path.abspath(path)) or '.'
    os.makedirs(folder, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.scene-', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(text)
            fh.flush()
            # The rename is atomic, but it only protects content the OS has
            # actually written. Without the fsync a crash seconds after a
            # "successful" save can leave the new name over empty blocks.
            os.fsync(fh.fileno())
        os.replace(temp, path)
        temp = None
    finally:
        if temp is not None and os.path.exists(temp):
            os.unlink(temp)
    return path


# ── undo: the same records, never touching a disk ──────────────────────────

def snapshot(doc):
    """A complete, inert copy of `doc` for an undo stack.

    Records rather than `clone()`: a snapshot must capture the library and
    the document together (an undo across "make component" has to put the
    definition back too), and records are the only form that holds both.

    `canonical=False`, because an undo must not renumber the model the user
    is still looking at -- a renumber mid-edit would invalidate their
    selection as a side effect of pressing Ctrl+Z once.
    """
    data, _, _ = to_records(doc, canonical=False)
    return data


def restore(data):
    """A document from a snapshot. Returns `(doc, id_map)`.

    The ids are fresh (see records.py decision 1), so `id_map` -- keyed by
    the ids the snapshot was taken with -- is how a caller puts the
    selection back.
    """
    doc, _warnings, id_map = from_records(data)
    return doc, {old: obj.id for old, obj in id_map.items()}


# ── Excel: inspection and interchange ──────────────────────────────────────

def _cell(value):
    """A value as one spreadsheet cell: scalars as themselves, the rest as
    JSON text. Refuses rather than truncating -- a silently clipped vertex
    list is a model that loads and is not the model that was saved."""
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    text = json.dumps(value, sort_keys=True, separators=(',', ':'))
    if len(text) > CELL_LIMIT:
        raise ValueError(
            'one of this model\'s objects needs %d characters and a '
            'spreadsheet cell holds %d. Save it as %s instead -- the JSON '
            'format has no such limit.' % (len(text), CELL_LIMIT, SUFFIX))
    return text


def _whole(value, what):
    """A cell as a whole number, or a refusal naming the cell.

    A hand-edited sheet is the expected input for this codec, so a careless
    edit has to come back as something a person can act on -- not as
    int()'s own complaint about a literal.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError('the Scene sheet\'s %s should be a whole number '
                         'naming an object, and it holds %r' % (what, value)
                         ) from None


def _uncell(value, default=None):
    if value is None or value == '':
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


_OBJECT_COLUMNS = (
    # Read by NAME on import, so a sheet written before a column existed
    # still loads and a column added later does not shift the others --
    # the rule the existing Model sheet follows, for the same reason.
    'id', 'kind', 'parent', 'name',
    'ax_m', 'ay_m', 'az_m', 'bx_m', 'by_m', 'bz_m',
    'joint_a', 'joint_b', 'joint_key',
    'definition', 'overrides', 'vertices', 'faces', 'meta',
    'm11', 'm12', 'm13', 'tx_m',
    'm21', 'm22', 'm23', 'ty_m',
    'm31', 'm32', 'm33', 'tz_m',
)

_DEFINITION_COLUMNS = ('id', 'name', 'policy', 'content', 'meta')


def _object_row(rec):
    row = {'id': rec['id'], 'kind': rec['kind'], 'parent': rec.get('parent'),
           'name': rec.get('name') or ''}
    a, b = rec.get('a'), rec.get('b')
    if a and b:
        row.update(ax_m=a[0], ay_m=a[1], az_m=a[2],
                   bx_m=b[0], by_m=b[1], bz_m=b[2])
    at = rec.get('at')
    if at:
        row.update(ax_m=at[0], ay_m=at[1], az_m=at[2])
    for key, col in (('joint_a', 'joint_a'), ('joint_b', 'joint_b'),
                     ('key', 'joint_key'), ('definition', 'definition')):
        if rec.get(key) is not None:
            row[col] = rec[key]
    for key in ('overrides', 'vertices', 'faces', 'meta'):
        if rec.get(key):
            row[key] = _cell(rec[key])
    xform = rec.get('xform')
    if xform:
        names = ('m11', 'm12', 'm13', 'tx_m', 'm21', 'm22', 'm23', 'ty_m',
                 'm31', 'm32', 'm33', 'tz_m')
        row.update(dict(zip(names, xform)))
    return row


def _row_to_record(row):
    kind = str(row.get('kind') or '').strip()
    rec = {'id': _whole(row['id'], 'object id %r' % (row['id'],)), 'kind': kind}
    parent = row.get('parent')
    rec['parent'] = (None if parent in (None, '')
                     else _whole(parent, 'parent of object %s' % rec['id']))
    if row.get('name'):
        rec['name'] = str(row['name'])

    def point(prefix):
        vals = [row.get('%s%s_m' % (prefix, ax)) for ax in 'xyz']
        if any(v in (None, '') for v in vals):
            return None
        try:
            return [float(v) for v in vals]
        except (TypeError, ValueError):
            raise ValueError(
                'object %s has a coordinate that is not a number: %r. A '
                'formula shows its result here only once the workbook has '
                'been recalculated and saved by Excel.'
                % (rec['id'], vals)) from None

    if kind == 'rod':
        rec['a'], rec['b'] = point('a'), point('b')
        for col in ('joint_a', 'joint_b'):
            if row.get(col):
                rec[col] = str(row[col])
    elif kind == 'joint':
        rec['at'] = point('a')
        rec['key'] = str(row.get('joint_key') or '')
    elif kind == 'mesh':
        rec['vertices'] = _uncell(row.get('vertices'), []) or []
        rec['faces'] = [list(f) for f in (_uncell(row.get('faces'), []) or [])]
    elif kind == 'instance':
        rec['definition'] = str(row.get('definition') or '')
        overrides = _uncell(row.get('overrides'))
        if overrides:
            rec['overrides'] = overrides
    meta = _uncell(row.get('meta'))
    if meta:
        rec['meta'] = meta
    names = ('m11', 'm12', 'm13', 'tx_m', 'm21', 'm22', 'm23', 'ty_m',
             'm31', 'm32', 'm33', 'tz_m')
    if any(row.get(n) not in (None, '') for n in names):
        # A partly-filled transform row is a hand-edit: the missing cells are
        # read as the identity's, so typing one translation into an otherwise
        # blank row does what it looks like it does.
        ident = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0)
        rec['xform'] = [float(row[n]) if row.get(n) not in (None, '') else float(d)
                        for n, d in zip(names, ident)]
    return rec


def write_scene_sheet(wb, doc, canonical=True):
    """Add a `Scene` sheet to an open workbook. Returns the renumber maps.

    Takes a workbook rather than a path so the scene travels in the SAME
    file as the `Model` sheet the Stereo tab already writes. A model split
    across two files is a model that gets separated.
    """
    from openpyxl.styles import Font
    data, obj_map, def_map = to_records(doc, canonical=canonical)
    if SHEET in wb.sheetnames:
        del wb[SHEET]
    ws = wb.create_sheet(SHEET)
    row = 1
    ws.cell(row=row, column=1,
            value='SCENE GRAPH (%s) — for Import; do not reorder columns, '
                  'they are read by name' % FORMAT)
    ws.cell(row=row, column=1).font = Font(bold=True, size=11, color='1F4E79')
    row += 2

    ws.cell(row=row, column=1, value='[META]')
    row += 1
    ws.cell(row=row, column=1, value='root')
    ws.cell(row=row, column=2, value=data['root'])
    row += 1
    for key, value in sorted((data.get('meta') or {}).items()):
        ws.cell(row=row, column=1, value=str(key))
        ws.cell(row=row, column=2, value=_cell(value))
        row += 1
    row += 1

    ws.cell(row=row, column=1, value='[DEFINITIONS]')
    row += 1
    for col, label in enumerate(_DEFINITION_COLUMNS, 1):
        ws.cell(row=row, column=col, value=label)
        ws.cell(row=row, column=col).font = Font(bold=True)
    row += 1
    for rec in data['definitions']:
        values = {'id': rec['id'], 'name': rec.get('name', ''),
                  'policy': rec.get('policy'), 'content': rec.get('content'),
                  'meta': _cell(rec['meta']) if rec.get('meta') else None}
        for col, label in enumerate(_DEFINITION_COLUMNS, 1):
            ws.cell(row=row, column=col, value=values.get(label))
        row += 1
    row += 1

    ws.cell(row=row, column=1, value='[OBJECTS]')
    row += 1
    for col, label in enumerate(_OBJECT_COLUMNS, 1):
        ws.cell(row=row, column=col, value=label)
        ws.cell(row=row, column=col).font = Font(bold=True)
    row += 1
    for rec in data['objects']:
        values = _object_row(rec)
        for col, label in enumerate(_OBJECT_COLUMNS, 1):
            ws.cell(row=row, column=col, value=values.get(label))
        row += 1

    from openpyxl.utils import get_column_letter
    for col in range(1, len(_OBJECT_COLUMNS) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 12
    return obj_map, def_map


def save_excel(doc, path, canonical=True):
    """Write a workbook containing only the scene. Returns the renumber maps."""
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    maps = write_scene_sheet(wb, doc, canonical=canonical)
    wb.save(path)
    return maps


def read_scene_sheet(path, strict=False):
    """Rebuild a document from a workbook's `Scene` sheet.

    Returns `(doc, warnings, id_map)`. Raises ValueError, with a message for
    a person, when the sheet is missing or unreadable -- the same contract
    `stereo_reports.import_excel_model` offers for the Model sheet.
    """
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    if SHEET not in wb.sheetnames:
        raise ValueError(
            'this workbook has no "%s" sheet, so it carries no scene graph. '
            'A workbook exported before grouping was rebuilt has a "Model" '
            'sheet only -- import that instead.' % SHEET)
    rows = list(wb[SHEET].iter_rows(values_only=True))

    def section(name):
        for i, r in enumerate(rows):
            if r and r[0] == name:
                return i
        return -1

    def table(start):
        if start < 0:
            return []
        header_i = start + 1
        if header_i >= len(rows) or not rows[header_i]:
            return []
        headers = [h for h in rows[header_i] if h is not None]
        out, i = [], header_i + 1
        while (i < len(rows) and rows[i] and rows[i][0] is not None
               and not str(rows[i][0]).startswith('[')):
            out.append({headers[j]: rows[i][j]
                        for j in range(min(len(headers), len(rows[i])))})
            i += 1
        return out

    meta, root_id = {}, None
    start = section('[META]')
    if start >= 0:
        i = start + 1
        while (i < len(rows) and rows[i] and rows[i][0] is not None
               and not str(rows[i][0]).startswith('[')):
            key, value = str(rows[i][0]), rows[i][1] if len(rows[i]) > 1 else None
            if key == 'root':
                root_id = _whole(value, 'root')
            else:
                meta[key] = _uncell(value)
            i += 1
    if root_id is None:
        raise ValueError('the Scene sheet\'s [META] block does not say which '
                         'object is the root, so the tree has no top.')

    definitions = []
    for row in table(section('[DEFINITIONS]')):
        if row.get('id') in (None, ''):
            continue
        rec = {'id': str(row['id']), 'name': str(row.get('name') or ''),
               'policy': str(row.get('policy') or 'rigid'),
               'content': _whole(row.get('content'),
                                 'content of definition %r' % (row['id'],))}
        dmeta = _uncell(row.get('meta'))
        if dmeta:
            rec['meta'] = dmeta
        definitions.append(rec)

    objects = [_row_to_record(row) for row in table(section('[OBJECTS]'))
               if row.get('id') not in (None, '')]
    data = {'format': FORMAT, 'root': root_id, 'objects': objects,
            'definitions': definitions}
    if meta:
        data['meta'] = meta
    return from_records(data, strict=strict)
