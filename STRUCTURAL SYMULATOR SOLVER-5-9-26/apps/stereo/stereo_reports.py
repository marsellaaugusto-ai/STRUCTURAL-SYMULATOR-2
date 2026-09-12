"""Excel export/import and text report for the Stereo tab, following the
same shape as apps/truss/truss_reports.py: a human-readable summary plus a
machine-parseable '[SECTION]' Model sheet that round-trips through
`import_excel_model`.

Scope note: unlike truss_reports.py this does not embed per-member PIL
free-body-diagram images -- that renderer is 2D-specific (a member and its
joint drawn in a flat local view) and a 3D equivalent was out of scope for
this first version. The Model/Members/Results sheets carry everything
needed to rebuild and re-check the structure; only the illustrated
per-member images are the cut corner.
"""
from common import _ensure_openpyxl


def export_excel(nodes, members, loads, supports, results, path, checks=None,
                  meta=None):
    """Write a workbook with Nodes, Members, Loads, Supports, Results (if
    `results` is not None), Member Checks (if `checks` is not None) and a
    machine-parseable Model sheet. `meta` is an optional dict of free-text
    generator parameters (typology, span, etc.) written at the top of the
    Model sheet purely for a human reader's benefit; it is not required by
    `import_excel_model`.
    """
    if not _ensure_openpyxl():
        raise RuntimeError('openpyxl is required for Excel export and could not '
                            'be installed automatically.')
    import openpyxl
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    def header_row(ws, labels, row=1, bold=True):
        for col, lbl in enumerate(labels, 1):
            c = ws.cell(row=row, column=col, value=lbl)
            if bold:
                c.font = Font(bold=True)

    ws = wb.create_sheet('Nodes')
    header_row(ws, ['idx', 'x_m', 'y_m', 'z_m'])
    for i, (x, y, z) in enumerate(nodes):
        ws.append([i, x, y, z])

    ws = wb.create_sheet('Members')
    header_row(ws, ['idx', 'a', 'b', 'conn', 'E_GPa', 'A_cm2', 'I_cm4', 'J_cm4',
                     'Fy_MPa', 'Fu_MPa', 'K', 'r_gyr_cm', 'role'])
    for i, m in enumerate(members):
        ws.append([i, m['a'], m['b'], m.get('conn', 'pin'), m.get('E'), m.get('A'),
                   m.get('I'), m.get('J'), m.get('Fy'), m.get('Fu'), m.get('K', 1.0),
                   m.get('r_gyr'), m.get('role', '')])

    ws = wb.create_sheet('Loads')
    header_row(ws, ['node', 'fx_kN', 'fy_kN', 'fz_kN', 'mx_kNm', 'my_kNm', 'mz_kNm'])
    for ld in loads:
        ws.append([ld['node'], ld.get('fx', 0.0), ld.get('fy', 0.0), ld.get('fz', 0.0),
                   ld.get('mx', 0.0), ld.get('my', 0.0), ld.get('mz', 0.0)])

    ws = wb.create_sheet('Supports')
    header_row(ws, ['node', 'type', 'ux', 'uy', 'uz', 'rx', 'ry', 'rz'])
    from apps.stereo.stereo_math import support_restraints
    for sp in supports:
        r = support_restraints(sp)
        ws.append([sp['node'], sp.get('type') or '', r['ux'], r['uy'], r['uz'],
                   r['rx'], r['ry'], r['rz']])

    if results is not None:
        ws = wb.create_sheet('Results')
        header_row(ws, ['node', 'ux_mm', 'uy_mm', 'uz_mm', 'rx_rad', 'ry_rad', 'rz_rad'])
        for i, nr in enumerate(results['node_res']):
            ws.append([i, nr['ux'], nr['uy'], nr['uz'], nr['rx'], nr['ry'], nr['rz']])
        ws2 = wb.create_sheet('Member Forces')
        header_row(ws2, ['member', 'a', 'b', 'conn', 'N_kN', 'length_m'])
        for i, (m, mr) in enumerate(zip(members, results['member_res'])):
            ws2.append([i, m['a'], m['b'], mr.get('conn', 'pin'), mr.get('N', 0.0),
                        mr.get('length_m', 0.0)])
        ws3 = wb.create_sheet('Reactions')
        header_row(ws3, ['node', 'Fx_kN', 'Fy_kN', 'Fz_kN', 'Mx_kNm', 'My_kNm', 'Mz_kNm'])
        for node, r in results['reactions'].items():
            ws3.append([node, r.get('Fx', 0.0), r.get('Fy', 0.0), r.get('Fz', 0.0),
                        r.get('Mx', 0.0), r.get('My', 0.0), r.get('Mz', 0.0)])

    if checks is not None:
        ws = wb.create_sheet('Member Checks')
        header_row(ws, ['member', 'checked', 'mode', 'utilization', 'governing', 'ok', 'note'])
        for i, c in enumerate(checks):
            ws.append([i, c.get('checked', False), c.get('mode', ''),
                       c.get('util'), c.get('governing', ''), c.get('ok', ''),
                       c.get('note', '')])

    _write_model_sheet(wb, nodes, members, loads, supports, meta)

    for name in wb.sheetnames:
        ws = wb[name]
        for col in range(1, 14):
            ws.column_dimensions[get_column_letter(col)].width = 12

    wb.save(path)


def _write_model_sheet(wb, nodes, members, loads, supports, meta=None):
    from openpyxl.styles import Font
    ws = wb.create_sheet('Model')
    ws.sheet_state = 'visible'
    row = 1
    ws.cell(row=row, column=1, value='STEREO MODEL DATA — for Import from Excel (do not reorder columns)')
    ws.cell(row=row, column=1).font = Font(bold=True, size=11, color='1F4E79')
    row += 2

    if meta:
        ws.cell(row=row, column=1, value='[META]'); row += 1
        for k, v in meta.items():
            ws.cell(row=row, column=1, value=str(k))
            ws.cell(row=row, column=2, value=v)
            row += 1
        row += 1

    ws.cell(row=row, column=1, value='[NODES]'); row += 1
    ws.cell(row=row, column=1, value='idx'); ws.cell(row=row, column=2, value='x_m')
    ws.cell(row=row, column=3, value='y_m'); ws.cell(row=row, column=4, value='z_m')
    row += 1
    for i, (x, y, z) in enumerate(nodes):
        ws.cell(row=row, column=1, value=i)
        ws.cell(row=row, column=2, value=x)
        ws.cell(row=row, column=3, value=y)
        ws.cell(row=row, column=4, value=z)
        row += 1
    row += 1

    ws.cell(row=row, column=1, value='[MEMBERS]'); row += 1
    for col, lbl in enumerate(['idx', 'a', 'b', 'conn', 'E_GPa', 'A_cm2', 'I_cm4',
                                'J_cm4', 'Fy_MPa', 'Fu_MPa', 'K', 'r_gyr_cm', 'role'], 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    for i, m in enumerate(members):
        vals = [i, m['a'], m['b'], m.get('conn', 'pin'), m.get('E'), m.get('A'),
                m.get('I'), m.get('J'), m.get('Fy'), m.get('Fu'), m.get('K', 1.0),
                m.get('r_gyr'), m.get('role', '')]
        for col, v in enumerate(vals, 1):
            ws.cell(row=row, column=col, value=v)
        row += 1
    row += 1

    ws.cell(row=row, column=1, value='[LOADS]'); row += 1
    for col, lbl in enumerate(['node', 'fx_kN', 'fy_kN', 'fz_kN', 'mx_kNm',
                                'my_kNm', 'mz_kNm'], 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    for ld in loads:
        vals = [ld['node'], ld.get('fx', 0.0), ld.get('fy', 0.0), ld.get('fz', 0.0),
                ld.get('mx', 0.0), ld.get('my', 0.0), ld.get('mz', 0.0)]
        for col, v in enumerate(vals, 1):
            ws.cell(row=row, column=col, value=v)
        row += 1
    row += 1

    # Supports store every raw per-DOF override plus the preset name, so a
    # round trip reproduces a hand-picked combination exactly rather than
    # only whatever a preset alone would give back.
    ws.cell(row=row, column=1, value='[SUPPORTS]'); row += 1
    for col, lbl in enumerate(['node', 'type', 'ux', 'uy', 'uz', 'rx', 'ry', 'rz'], 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    from apps.stereo.stereo_math import DOF_NAMES
    for sp in supports:
        dofs = sp.get('dofs') or {}
        vals = [sp['node'], sp.get('type') or '']
        for d in DOF_NAMES:
            vals.append(int(bool(dofs.get(d, False))) if d in dofs else '')
        for col, v in enumerate(vals, 1):
            ws.cell(row=row, column=col, value=v)
        row += 1


def import_excel_model(path):
    """Reads a 'Model' sheet written by `_write_model_sheet` and rebuilds
    (nodes, members, loads, supports). Raises ValueError with a
    human-readable message if the sheet is missing or malformed."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    if 'Model' not in wb.sheetnames:
        raise ValueError('This workbook has no "Model" sheet -- it was not '
                          'exported by the Stereo tab (or is a report-only export).')
    ws = wb['Model']
    rows = list(ws.iter_rows(values_only=True))

    def find_section(name):
        for i, r in enumerate(rows):
            if r and r[0] == name:
                return i
        return -1

    def read_table(start_idx):
        if start_idx < 0:
            return []
        hdr_i = start_idx + 1
        if hdr_i >= len(rows) or not rows[hdr_i] or rows[hdr_i][0] is None:
            return []
        headers = [h for h in rows[hdr_i] if h is not None]
        out = []
        i = hdr_i + 1
        while (i < len(rows) and rows[i] and rows[i][0] is not None
               and not str(rows[i][0]).startswith('[')):
            vals = rows[i]
            out.append({headers[j]: vals[j] for j in range(len(headers))})
            i += 1
        return out

    node_rows = read_table(find_section('[NODES]'))
    nodes = [(0.0, 0.0, 0.0)] * len(node_rows)
    for r in node_rows:
        nodes[int(r['idx'])] = (float(r['x_m']), float(r['y_m']), float(r['z_m']))

    members = []
    for r in read_table(find_section('[MEMBERS]')):
        m = {'a': int(r['a']), 'b': int(r['b']), 'conn': r.get('conn') or 'pin'}
        for key, field in (('E_GPa', 'E'), ('A_cm2', 'A'), ('I_cm4', 'I'),
                            ('J_cm4', 'J'), ('Fy_MPa', 'Fy'), ('Fu_MPa', 'Fu'),
                            ('r_gyr_cm', 'r_gyr')):
            v = r.get(key)
            if v is not None and v != '':
                m[field] = float(v)
        k = r.get('K')
        m['K'] = float(k) if k not in (None, '') else 1.0
        role = r.get('role')
        if role:
            m['role'] = str(role)
        members.append(m)

    loads = []
    for r in read_table(find_section('[LOADS]')):
        loads.append({'node': int(r['node']),
                       'fx': float(r.get('fx_kN') or 0.0),
                       'fy': float(r.get('fy_kN') or 0.0),
                       'fz': float(r.get('fz_kN') or 0.0),
                       'mx': float(r.get('mx_kNm') or 0.0),
                       'my': float(r.get('my_kNm') or 0.0),
                       'mz': float(r.get('mz_kNm') or 0.0)})

    from apps.stereo.stereo_math import DOF_NAMES
    supports = []
    for r in read_table(find_section('[SUPPORTS]')):
        sp = {'node': int(r['node'])}
        if r.get('type'):
            sp['type'] = str(r['type'])
        dofs = {}
        for d in DOF_NAMES:
            v = r.get(d)
            if v not in (None, ''):
                dofs[d] = bool(int(v))
        if dofs:
            sp['dofs'] = dofs
        supports.append(sp)

    return nodes, members, loads, supports


def summary_text(nodes, members, results, checks=None):
    """A short human-readable analysis summary, for the tab's results pane
    -- the same role truss_app._show_analysis_text plays for Truss."""
    lines = [f'Nodes: {len(nodes)}   Members: {len(members)}']
    if results is None:
        lines.append('Not yet analyzed.')
        return '\n'.join(lines)

    max_disp = 0.0
    for nr in results['node_res']:
        d = (nr['ux'] ** 2 + nr['uy'] ** 2 + nr['uz'] ** 2) ** 0.5
        max_disp = max(max_disp, d)
    lines.append(f'Max nodal displacement: {max_disp:.3f} mm')

    forces = [mr['N'] for mr in results['member_res']]
    if forces:
        lines.append(f'Max tension:     {max(forces):+.2f} kN')
        lines.append(f'Max compression: {min(forces):+.2f} kN')

    total_rz = sum(r.get('Fz', 0.0) for r in results['reactions'].values())
    lines.append(f'Total vertical reaction: {total_rz:.2f} kN')

    if checks is not None:
        from apps.stereo.stereo_checks import worst_utilization
        worst = worst_utilization(checks)
        if worst is None:
            lines.append('Member checks: no member has a section assigned yet.')
        else:
            n_over = sum(1 for c in checks if c.get('checked') and c['util'] > 1.0)
            lines.append(f'Governing member utilization: {worst:.2f}'
                         + (f'  ({n_over} member(s) over capacity)' if n_over else '  (all OK)'))
    return '\n'.join(lines)
