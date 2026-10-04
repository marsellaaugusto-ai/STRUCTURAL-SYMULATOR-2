"""beam_reports.py — the Beam tab's Excel report and model import.

Split out of `beam_app.py` with the solver on 2026-10-04 (R-8), mirroring
`apps/truss/truss_reports.py`: the workbook layer owns openpyxl and nothing
else owns the workbook layer. Unlike `beam_math.py` this is NOT on the
math/UI boundary -- it reaches `common` for the openpyxl bootstrap, so it
needs the same environment the tab does, exactly as truss_reports does.

Both functions are a matched pair: `export_beam_excel` writes a 'Model' sheet
holding every input needed to rebuild the beam, and `import_beam_excel` reads
that sheet back. tests/test_excel_roundtrip.py holds them to it field by
field.

UNITS. The workbook is written in the tab's STORAGE units (m, kN, kN*m, cm^4,
GPa) whatever the Units selector shows, so a saved file never changes meaning
because someone picked a different convention -- see `units.py`.
"""
from common import _ensure_openpyxl


def export_beam_excel(state, path, result=None, model=None):
    """
    Writes a workbook with:
      • 'Model'   — every input needed to rebuild this exact beam (length,
                    supports, loads, section) — paired with import_beam_excel().
      • 'Results' — reactions, extremes, and a station-by-station table of
                    V, M, and deflection (only if `result` given).
    `state` is a plain dict with keys: length, supports, point_loads,
    moments, dloads, nonuniform_loads, profile.
    """
    if not _ensure_openpyxl():
        raise RuntimeError('openpyxl is not available.')
    import openpyxl
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet('Model')
    row = 1
    ws.cell(row=row, column=1, value='BEAM MODEL DATA — for Import from Excel (do not reorder columns)')
    ws.cell(row=row, column=1).font = Font(bold=True, size=11, color='1F4E79')
    row += 2

    ws.cell(row=row, column=1, value='[GEOMETRY]'); row += 1
    ws.cell(row=row, column=1, value='length_m'); row += 1
    ws.cell(row=row, column=1, value=state['length']); row += 2

    ws.cell(row=row, column=1, value='[SUPPORTS]'); row += 1
    for col, lbl in enumerate(['x_m', 'type'], 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    for s in state['supports']:
        ws.cell(row=row, column=1, value=s['x'])
        ws.cell(row=row, column=2, value=s['type'])
        row += 1
    row += 1

    ws.cell(row=row, column=1, value='[POINT_LOADS]'); row += 1
    for col, lbl in enumerate(['x_m', 'P_kN'], 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    for p in state['point_loads']:
        ws.cell(row=row, column=1, value=p['x'])
        ws.cell(row=row, column=2, value=p['P'])
        row += 1
    row += 1

    ws.cell(row=row, column=1, value='[MOMENTS]'); row += 1
    for col, lbl in enumerate(['x_m', 'M_kNm'], 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    for mm in state['moments']:
        ws.cell(row=row, column=1, value=mm['x'])
        ws.cell(row=row, column=2, value=mm['M'])
        row += 1
    row += 1

    ws.cell(row=row, column=1, value='[DISTRIBUTED_LOADS]'); row += 1
    for col, lbl in enumerate(['x1_m', 'x2_m', 'w1_kNm', 'w2_kNm'], 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    for d in state['dloads']:
        ws.cell(row=row, column=1, value=d['x1'])
        ws.cell(row=row, column=2, value=d['x2'])
        ws.cell(row=row, column=3, value=d['w1'])
        ws.cell(row=row, column=4, value=d['w2'])
        row += 1
    row += 1

    ws.cell(row=row, column=1, value='[NONUNIFORM_LOADS]'); row += 1
    for col, lbl in enumerate(['expr', 'x1_m', 'x2_m'], 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    for d in state['nonuniform_loads']:
        ws.cell(row=row, column=1, value=d['expr'])
        ws.cell(row=row, column=2, value=d['x1'])
        ws.cell(row=row, column=3, value=d['x2'])
        row += 1
    row += 1

    ws.cell(row=row, column=1, value='[SECTION]'); row += 1
    keys = ['E', 'I', 'c', 'A', 'allow_bend', 'allow_shear']
    labels = ['E_GPa', 'I_cm4', 'c_cm', 'A_cm2', 'allow_bend_kNcm2', 'allow_shear_kNcm2']
    for col, lbl in enumerate(labels, 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    for col, key in enumerate(keys, 1):
        ws.cell(row=row, column=col, value=state['profile'][key])
    row += 1

    for col in range(1, 7):
        ws.column_dimensions[get_column_letter(col)].width = 14

    if result is not None and model is not None:
        wr = wb.create_sheet('Results')
        wr.cell(row=1, column=1, value='BEAM RESULTS').font = Font(bold=True, size=11, color='1F4E79')

        row_r = 3
        wr.cell(row=row_r, column=1, value='Support')
        wr.cell(row=row_r, column=2, value='Ry_kN (+up)')
        wr.cell(row=row_r, column=3, value='M_kNm (couple, +CCW)')
        wr.cell(row=row_r, column=4, value='M_left_kNm (internal)')
        wr.cell(row=row_r, column=5, value='M_right_kNm (internal)')
        row_r += 1
        for s in model.supports:
            # No sign heuristic here either: the couple is the couple at every
            # station, and the internal moments are reported beside it (R-3).
            react = result.support_reaction(s['x'])
            wr.cell(row=row_r, column=1, value=f"x={s['x']:.3f} ({s['type']})")
            wr.cell(row=row_r, column=2, value=react['Fy'] / 1e3)
            wr.cell(row=row_r, column=3, value=react['M'] / 1e3)
            wr.cell(row=row_r, column=4, value=react['M_left'] / 1e3)
            wr.cell(row=row_r, column=5, value=react['M_right'] / 1e3)
            row_r += 1

        diag = result.sample_diagram(n_per_element=25)
        Vmax = max(diag['V'], key=abs) if diag['V'] else 0.0
        Mmax = max(diag['M'], key=abs) if diag['M'] else 0.0
        vmax = max(diag['v'], key=abs) if diag['v'] else 0.0
        row_r += 1
        wr.cell(row=row_r, column=1, value='Max |V| (kN)'); wr.cell(row=row_r, column=2, value=abs(Vmax) / 1e3)
        row_r += 1
        wr.cell(row=row_r, column=1, value='Max |M| (kN·m)'); wr.cell(row=row_r, column=2, value=abs(Mmax) / 1e3)
        row_r += 1
        wr.cell(row=row_r, column=1, value='Max |defl| (mm)'); wr.cell(row=row_r, column=2, value=abs(vmax) * 1000)
        row_r += 1

        # Does the answer balance? The reviewer who opens this workbook is the
        # reader most likely to want it, and the sheet said nothing about it
        # until 2026-10-04 -- see BeamResult.equilibrium() and R-2.
        eq = result.equilibrium()
        row_r += 1
        wr.cell(row=row_r, column=1, value='EQUILIBRIUM').font = Font(bold=True)
        row_r += 1
        for label, value in [
            ('Total load (kN, down)', eq['applied_down'] / 1e3),
            ('Sum of reactions (kN, up)', eq['reactions_up'] / 1e3),
            ('Residual sum Fy (kN)', eq['residual_Fy'] / 1e3),
            ('Residual sum M about x=0 (kN*m)', eq['residual_M0'] / 1e3),
            ('V beyond x=L (kN)', eq['shear_beyond_end'] / 1e3),
            ('M beyond x=L (kN*m)', eq['moment_beyond_end'] / 1e3),
            ('Restrained DOF', eq['constrained_dof']),
            ('Degree of indeterminacy', max(0, eq['indeterminacy'])),
            ('Balanced', 'yes' if eq['ok'] else 'NO -- DO NOT USE'),
        ]:
            wr.cell(row=row_r, column=1, value=label)
            wr.cell(row=row_r, column=2, value=value)
            row_r += 1

        for mg in getattr(model, 'support_merges', []):
            wr.cell(row=row_r, column=1, value='Note')
            wr.cell(row=row_r, column=2,
                    value=f"two supports at x={mg['x']:.3f} m merged "
                          f"({mg['kept']} + {mg['added']} -> {mg['result']})")
            row_r += 1

        hdr_row = row_r + 2
        for col, lbl in enumerate(['x_m', 'V_kN', 'M_kNm', 'defl_mm'], 1):
            wr.cell(row=hdr_row, column=col, value=lbl)
        for i in range(len(diag['x'])):
            rr = hdr_row + 1 + i
            wr.cell(row=rr, column=1, value=diag['x'][i])
            wr.cell(row=rr, column=2, value=diag['V'][i] / 1e3)
            wr.cell(row=rr, column=3, value=diag['M'][i] / 1e3)
            wr.cell(row=rr, column=4, value=diag['v'][i] * 1000)
        for col in range(1, 5):
            wr.column_dimensions[get_column_letter(col)].width = 13

    wb.save(path)


def import_beam_excel(path):
    """Reads a 'Model' sheet written by export_beam_excel() and returns a
    plain state dict (same shape as the `state` argument passed into
    export_beam_excel), or raises ValueError with a human-readable message."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    if 'Model' not in wb.sheetnames:
        raise ValueError('This workbook has no "Model" sheet — it was not '
                          'exported by the Beam tab.')
    ws = wb['Model']
    rows = list(ws.iter_rows(values_only=True))

    def find_section(name):
        for i, r in enumerate(rows):
            if r and r[0] == name:
                return i
        return -1

    def read_table(start_idx):
        hdr_i = start_idx + 1
        if hdr_i >= len(rows) or not rows[hdr_i] or rows[hdr_i][0] is None:
            return []
        headers = [h for h in rows[hdr_i] if h is not None]
        out = []
        i = hdr_i + 1
        while i < len(rows) and rows[i] and rows[i][0] is not None and not str(rows[i][0]).startswith('['):
            vals = rows[i]
            out.append({headers[j]: vals[j] for j in range(len(headers))})
            i += 1
        return out

    gi = find_section('[GEOMETRY]')
    if gi < 0:
        raise ValueError('Missing [GEOMETRY] section.')
    grow = read_table(gi)
    if not grow:
        raise ValueError('Empty [GEOMETRY] section.')
    length = float(grow[0]['length_m'])

    supports = []
    si = find_section('[SUPPORTS]')
    if si >= 0:
        for r in read_table(si):
            supports.append({'x': float(r['x_m']), 'type': str(r['type'])})

    point_loads = []
    pi = find_section('[POINT_LOADS]')
    if pi >= 0:
        for r in read_table(pi):
            point_loads.append({'x': float(r['x_m']), 'P': float(r['P_kN'])})

    moments = []
    mi = find_section('[MOMENTS]')
    if mi >= 0:
        for r in read_table(mi):
            moments.append({'x': float(r['x_m']), 'M': float(r['M_kNm'])})

    dloads = []
    # Accept the pre-2026-09-07 name too, so workbooks already on disk
    # still import. New exports use [DISTRIBUTED_LOADS], matching Cable.
    di = find_section('[DISTRIBUTED_LOADS]')
    if di < 0:
        di = find_section('[DLOADS]')
    if di >= 0:
        for r in read_table(di):
            dloads.append({'x1': float(r['x1_m']), 'x2': float(r['x2_m']),
                            'w1': float(r['w1_kNm']), 'w2': float(r['w2_kNm'])})

    nonuniform_loads = []
    ni = find_section('[NONUNIFORM_LOADS]')
    if ni >= 0:
        for r in read_table(ni):
            nonuniform_loads.append({'expr': str(r['expr']), 'x1': float(r['x1_m']), 'x2': float(r['x2_m'])})

    profile = {'E': 200.0, 'I': 8000.0, 'c': 15.0, 'A': 80.0,
               'allow_bend': 16.0, 'allow_shear': 10.0}
    seci = find_section('[SECTION]')
    if seci >= 0:
        srow = read_table(seci)
        if srow:
            s0 = srow[0]
            profile['E'] = float(s0.get('E_GPa') or profile['E'])
            profile['I'] = float(s0.get('I_cm4') or profile['I'])
            profile['c'] = float(s0.get('c_cm') or profile['c'])
            profile['A'] = float(s0.get('A_cm2') or profile['A'])
            profile['allow_bend'] = float(s0.get('allow_bend_kNcm2') or profile['allow_bend'])
            profile['allow_shear'] = float(s0.get('allow_shear_kNcm2') or profile['allow_shear'])

    return {'length': length, 'supports': supports, 'point_loads': point_loads,
            'moments': moments, 'dloads': dloads, 'nonuniform_loads': nonuniform_loads,
            'profile': profile}
