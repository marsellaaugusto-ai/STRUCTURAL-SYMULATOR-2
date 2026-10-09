"""Saved rules in the workbook: the Roles panel survives a save.

A rule is a saved QUESTION, not a saved list (see stereo_roles), and that
is exactly why it is worth writing down: a list of rod numbers would be
correct the day it was saved and quietly wrong after the next edit, while
a question re-answers itself. Until this existed the questions lived for
the session and died with it, so "overloaded diagonals" had to be typed
again every time the file was opened.

GROUPS ARE WRITTEN TWICE, BY ID AND BY NAME, and that is not redundancy.
A rule can be scoped to groups, and it holds group IDs. Ids survive an
import through the Groups sheet, which writes them -- but NOT through the
Scene sheet, which renumbers as it bakes. An id that comes back meaning a
different group is the worst outcome available here: the rule still works,
still selects rods, and selects the wrong ones. So both are written, both
must agree on the way in, and a row where they disagree is reported rather
than guessed at.

The sheet is editable, like the Groups sheet and unlike Piece Marks. A
rule is something someone wrote; there is no reason they should not write
it here.
"""
from apps.stereo import stereo_groups as sgp
from apps.stereo import stereo_roles as srl

SHEET = 'Rules'

HEADERS = ('name', 'roles', 'groups', 'group names', 'util_min', 'util_max',
           'conn', 'hidden')
INFO_HEADERS = ('info: reads as',)

#: Group names are free text, so the separator has to be something nobody
#: types. A name containing it cannot round-trip, which the sheet says.
NAME_SEP = ' | '


# ── writing ───────────────────────────────────────────────────────────────

def _roles_text(rule):
    """Roles spelled the way the panel spells them.

    Labels rather than keys, because this sheet is meant to be edited and
    nobody should have to learn that the Top chord is called top_chord.
    `role_key` reads either, so a key typed by hand still works -- and
    `label` and `role_key` undo each other for a role no generator
    registered, so an unknown one survives too.

    UNSET is the empty string, which would vanish in a comma list; its
    label is how "rods with no role" survives the trip.
    """
    roles = rule.get('roles')
    if not roles:
        return ''
    return ', '.join(sorted(srl.label(r) for r in roles))


def _groups_text(rule, groups):
    gids = rule.get('groups')
    if not gids:
        return '', ''
    found = [sgp.find(groups, gid) for gid in sorted(gids)]
    ids = ', '.join(str(g['id']) for g in found if g is not None)
    names = NAME_SEP.join(g['name'] for g in found if g is not None)
    return ids, names


def rule_rows(rules, groups=(), hidden=()):
    """One dict per rule: what the sheet shows."""
    rows = []
    for rule in rules or ():
        ids, names = _groups_text(rule, groups)
        rows.append({
            'name': rule.get('name') or 'Rule',
            'roles': _roles_text(rule),
            'groups': ids,
            'group names': names,
            'util_min': rule.get('util_min'),
            'util_max': rule.get('util_max'),
            'conn': rule.get('conn') or '',
            'hidden': 1 if (rule.get('name') in (hidden or ())) else None,
            'info: reads as': srl.describe(rule),
        })
    return rows


def write_rules_sheet(wb, rules, groups=(), hidden=()):
    """Add the Rules sheet to an openpyxl workbook. Returns the sheet."""
    from openpyxl.styles import Font, PatternFill, Alignment
    ws = wb.create_sheet(SHEET)
    ws.cell(row=1, column=1,
            value='RULES — saved questions about the rods, across every '
                  'group').font = Font(bold=True, size=12, color='1F4E79')
    notes = [
        'A rule is a QUESTION, re-asked every time it is used, so it stays '
        'right after the model changes. Nothing here is a list of rod '
        'numbers.',
        'roles: one or more role names, comma separated (Diagonal, Top '
        'chord, …). Blank means any rod. "%s" is the rods no generator '
        'gave a role.' % srl.UNSET_LABEL,
        'groups / group names: the rule asks only inside these groups. '
        'Blank means the whole model. Both columns are read and must '
        'agree — names are separated by "%s".' % NAME_SEP.strip(),
        'util_min / util_max: utilisation bounds. A rule that asks about '
        'utilisation matches nothing until the model has been analysed, '
        'rather than silently matching everything.',
        'conn: pin or rigid. Blank means either.',
        'hidden: 1 if this rule is hiding its rods. Blank means it is not.',
        'Columns headed "info:" are for reading and are not imported.',
    ]
    for k, text in enumerate(notes):
        ws.cell(row=2 + k, column=1, value=text).font = Font(
            italic=True, size=9, color='5F6368')
    hdr_row = 2 + len(notes) + 1
    hdr_fill = PatternFill('solid', fgColor='404040')
    info_fill = PatternFill('solid', fgColor='8C8C8C')
    for col, h in enumerate(HEADERS + INFO_HEADERS, 1):
        c = ws.cell(row=hdr_row, column=col, value=h)
        c.font = Font(bold=True, color='FFFFFF', size=10)
        c.fill = info_fill if h.startswith('info:') else hdr_fill
        c.alignment = Alignment(horizontal='center')
    r = hdr_row + 1
    for row in rule_rows(rules, groups, hidden):
        for col, h in enumerate(HEADERS + INFO_HEADERS, 1):
            ws.cell(row=r, column=col, value=row.get(h))
        r += 1
    ws.freeze_panes = ws.cell(row=hdr_row + 1, column=2)
    return ws


# ── reading ───────────────────────────────────────────────────────────────

def read_rules_sheet(wb):
    """The sheet's rows as dicts keyed by header, or None if there is none."""
    if SHEET not in wb.sheetnames:
        return None
    rows = list(wb[SHEET].iter_rows(values_only=True))
    hdr_i = next((i for i, r in enumerate(rows)
                  if r and r[0] is not None and str(r[0]).strip() == 'name'),
                 None)
    if hdr_i is None:
        raise ValueError('The Rules sheet has no header row (a row starting '
                         'with "name").')
    headers = [str(h).strip() if h is not None else '' for h in rows[hdr_i]]
    out = []
    for r in rows[hdr_i + 1:]:
        if not r or all(v in (None, '') for v in r):
            continue
        out.append({headers[j]: r[j] for j in range(min(len(headers), len(r)))
                    if headers[j] and not headers[j].startswith('info:')})
    return out


def role_key(text, known):
    """Role text back to a role key: a key as written, or the label a
    reader sees. Someone editing the sheet types what the panel shows them,
    and the [META] list of hidden roles is read the same way."""
    want = str(text or '').strip()
    if not want:
        return None
    if want == srl.UNSET_LABEL:
        return srl.UNSET
    lowered = want.lower()
    for key in known:
        if key.lower() == lowered or srl.label(key).lower() == lowered:
            return key
    # A role the model does not currently have is still a legitimate
    # question -- the rods that would answer it may be imported next. Keep
    # it, spelled the way a generator would write it.
    return want.lower().replace(' ', '_')


def _num(v, where):
    if v in (None, ''):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError('%s: %r is not a number' % (where, v))


def _truthy(v):
    return str(v or '').strip().lower() not in ('', '0', 'no', 'false', 'n')


def build_rules(sheet_rows, members=(), groups=()):
    """(rules, hidden_names, report) from the sheet's rows.

    Never raises on a row that merely cannot be resolved -- a rule naming a
    group that is no longer in the model is a rule that has outlived part
    of its question, not a corrupt file, and losing every other rule over
    it would be the wrong trade. Those are narrowed and reported.
    """
    known = set()
    for m in members or ():
        known.add(m.get('role') or srl.UNSET)
    known |= set(srl.ROLE_LABELS)

    rules, hidden, report = [], set(), []
    seen = set()
    for k, r in enumerate(sheet_rows or ()):
        name = str(r.get('name') or '').strip() or 'Rule %d' % (k + 1)
        if name in seen:
            report.append('Two rules are called "%s"; the second was '
                          'dropped.' % name)
            continue
        seen.add(name)

        roles = None
        text = str(r.get('roles') or '').strip()
        if text:
            roles = {role_key(t, known) for t in text.split(',')
                     if t.strip()}
            roles.discard(None)
            roles = roles or None

        gids = _resolve_groups(r, groups, name, report)

        try:
            lo = _num(r.get('util_min'), 'Rules row "%s", util_min' % name)
            hi = _num(r.get('util_max'), 'Rules row "%s", util_max' % name)
        except ValueError as exc:
            report.append('%s -- that bound was ignored.' % exc)
            lo = hi = None

        conn = str(r.get('conn') or '').strip().lower() or None
        if conn and conn not in ('pin', 'rigid'):
            report.append('Rule "%s": conn "%s" is neither pin nor rigid, so '
                          'the rule asks about either.' % (name, conn))
            conn = None

        rules.append(srl.new_rule(name, roles=roles, groups=gids,
                                  util_min=lo, util_max=hi, conn=conn))
        if _truthy(r.get('hidden')):
            hidden.add(name)
    return rules, hidden, report


def _resolve_groups(row, groups, name, report):
    """The gids a row's two group columns agree on.

    Ids survive the Groups sheet and are renumbered by the Scene sheet, so
    an id alone can come back meaning a different group -- a rule that
    still works and selects the wrong rods. Requiring the name to match is
    what catches that; where it does not, the name wins, because it is what
    the person who wrote the rule actually meant.
    """
    from apps.stereo.stereo_groups_excel import parse_ranges
    raw_ids = row.get('groups')
    raw_names = str(row.get('group names') or '').strip()
    if raw_ids in (None, '') and not raw_names:
        return None

    try:
        ids = parse_ranges(raw_ids)
    except ValueError:
        report.append('Rule "%s": the group list %r could not be read, so '
                      'the rule asks the whole model.' % (name, raw_ids))
        ids = []
    names = [n.strip() for n in raw_names.split(NAME_SEP.strip())
             if n.strip()] if raw_names else []

    out, missing = [], []
    for k, gid in enumerate(ids):
        g = sgp.find(groups, gid)
        want = names[k] if k < len(names) else None
        if g is not None and (want is None or g['name'] == want):
            out.append(gid)
            continue
        # The id is gone or now means something else. Fall back to the name.
        by_name = [o for o in groups if o['name'] == want] if want else []
        if by_name:
            out.extend(o['id'] for o in by_name)
            if g is not None:
                report.append('Rule "%s": group %d is now "%s", not "%s"; '
                              'the rule followed the name.'
                              % (name, gid, g['name'], want))
        else:
            missing.append(want or str(gid))
    # Names with no id beside them at all (someone typed the column by hand).
    for want in names[len(ids):]:
        by_name = [o for o in groups if o['name'] == want]
        if by_name:
            out.extend(o['id'] for o in by_name)
        else:
            missing.append(want)
    if missing:
        report.append('Rule "%s": no group called %s is in this model, so '
                      'the rule no longer asks about it.'
                      % (name, ' or '.join('"%s"' % m for m in missing)))
    return set(out) or None


def import_rules(path, members=(), groups=()):
    """(rules, hidden, report) from a workbook, or (None, set(), []) when it
    has no Rules sheet -- so the caller can tell "this file says there are
    no rules" from "this file does not mention rules"."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    rows = read_rules_sheet(wb)
    if rows is None:
        return None, set(), []
    return build_rules(rows, members, groups)
