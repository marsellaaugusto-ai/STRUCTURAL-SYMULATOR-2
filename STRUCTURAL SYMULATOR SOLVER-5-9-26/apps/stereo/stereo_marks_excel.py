"""The piece-mark schedule as a workbook sheet.

The counterpart to stereo_groups_excel: that sheet is EDITABLE, and
importing it writes back onto the model. This one is not. A mark is derived
from the geometry every time (see stereo_marks), so a mark typed into a
spreadsheet would be a number with nothing behind it -- and the one way a
wrong mark reaches the shop floor is by surviving the edit that made it
wrong. The sheet says so at the top, and nothing here reads it back.
"""
from apps.stereo import stereo_marks as sm

SHEET = 'Piece Marks'

ASSEMBLY_HEADERS = ('mark', 'qty', 'rods each', 'length each (m)',
                    'total length (m)', 'mass each (kg)', 'total mass (kg)',
                    'mirrored', 'groups')
PART_HEADERS = ('mark', 'qty', 'profile', 'conn', 'length each (m)',
                'total length (m)', 'mass each (kg)', 'total mass (kg)',
                'role(s)')


def write_marks_sheet(wb, nodes, members, groups=(), tol_mm=None):
    """Add the Piece Marks sheet. Returns (sheet, the schedule dict)."""
    from openpyxl.styles import Font, PatternFill, Alignment
    data = sm.schedule(nodes, members, groups or (), tol_mm)
    ws = wb.create_sheet(SHEET)
    hdr_fill = PatternFill('solid', fgColor='404040')

    def band(row, title):
        c = ws.cell(row=row, column=1, value=title)
        c.font = Font(bold=True, size=11, color='1F4E79')
        return row + 1

    def head(row, headers):
        for col, h in enumerate(headers, 1):
            c = ws.cell(row=row, column=col, value=h)
            c.font = Font(bold=True, color='FFFFFF', size=10)
            c.fill = hdr_fill
            c.alignment = Alignment(horizontal='center')
        return row + 1

    def note(row, text):
        ws.cell(row=row, column=1, value=text).font = Font(
            italic=True, size=9, color='5F6368')
        return row + 1

    r = band(1, 'PIECE MARKS — identical pieces, and how many of each')
    r = note(r, 'Read-only. Marks are worked out from the geometry every '
                'time this is exported, never stored, so they always agree '
                'with the steel. Editing this sheet changes nothing on the '
                'way back in.')
    r = note(r, 'Compared to the nearest %g mm. Two pieces that differ by '
                'less than that count as the same piece; the setting is in '
                'the Groups panel.' % data['tol_mm'])
    r = note(r, 'A mark ending "%s" is the MIRROR image of the one it is '
                'numbered with -- the same shape built the other way round. '
                'It is a different piece of steel and cannot be installed '
                'in its place.' % sm.MIRROR_SUFFIX)
    r = note(r, 'These marks describe THIS model. They are not comparable '
                'with a schedule exported before the model changed.')
    r += 1

    r = band(r, 'ASSEMBLIES — groups fabricated and shipped as one piece')
    if data['assemblies']:
        r = head(r, ASSEMBLY_HEADERS)
        for row in data['assemblies']:
            for col, v in enumerate((
                    row['mark'], row['qty'], row['n_rods'],
                    row['length_m'], row['total_length_m'],
                    row['mass_kg'], row['total_mass_kg'],
                    'yes' if row['mirrored'] else None,
                    ', '.join(row['names'])), 1):
                c = ws.cell(row=r, column=col, value=v)
                if isinstance(v, float):
                    c.number_format = '0.000'
            r += 1
    else:
        r = note(r, 'No groups with rods of their own, so there is nothing '
                    'to fabricate as an assembly yet.')
    r += 1

    r = band(r, 'PARTS — single rods, the list steel is ordered from')
    r = head(r, PART_HEADERS)
    for row in data['parts']:
        for col, v in enumerate((
                row['mark'], row['qty'], row['profile'], row['conn'],
                row['length_m'], row['total_length_m'],
                row['mass_kg'], row['total_mass_kg'],
                ', '.join(row['roles'])), 1):
            c = ws.cell(row=r, column=col, value=v)
            if isinstance(v, float):
                c.number_format = '0.000'
        r += 1

    r += 1
    ws.cell(row=r, column=1, value='TOTAL').font = Font(bold=True)
    ws.cell(row=r, column=2,
            value=sum(x['qty'] for x in data['parts'])).font = Font(bold=True)
    for col, total in ((6, sum(x['total_length_m'] for x in data['parts'])),
                       (8, sum(x['total_mass_kg'] for x in data['parts']))):
        c = ws.cell(row=r, column=col, value=total)
        c.font = Font(bold=True)
        c.number_format = '0.000'
    return ws, data
