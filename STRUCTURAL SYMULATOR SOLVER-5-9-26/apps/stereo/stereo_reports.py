"""Excel export/import and text report for the Stereo tab, following the
same shape as apps/truss/truss_reports.py: a human-readable summary plus a
machine-parseable '[SECTION]' Model sheet that round-trips through
`import_excel_model`.

Includes PIL-rendered free-body-diagram images for each member, projected
from 3D to 2D using an isometric-style parallel projection.
"""
from common import _ensure_openpyxl


# ── PIL rendering helpers for 3D→2D free-body diagrams ───────────────────

def _get_ttf_font(size):
    try:
        import matplotlib, os
        from PIL import ImageFont
        path = os.path.join(matplotlib.get_data_path(), 'fonts', 'ttf',
                            'DejaVuSans.ttf')
        return ImageFont.truetype(path, size)
    except Exception:
        from PIL import ImageFont
        return ImageFont.load_default()


def _pil_to_xlsx_buf(pil_img):
    import io
    buf = io.BytesIO()
    pil_img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _iso_project(px, py, pz, az_rad, el_rad):
    """Parallel (isometric-style) projection of a 3D point to 2D screen coords.

    az_rad: azimuth angle (rotation around vertical Z axis)
    el_rad: elevation angle above horizontal
    Returns (screen_x, screen_y) with Z pointing up.
    """
    import math
    ca, sa = math.cos(az_rad), math.sin(az_rad)
    ce, se = math.cos(el_rad), math.sin(el_rad)
    sx = px * ca - py * sa
    sy = -(px * sa * se + pz * ce + py * ca * se)
    return sx, sy


def pil_draw_member_context_3d(nodes, members, member_idx, member_res=None,
                               size=260):
    """Render the full 3D structure with one member highlighted, projected
    to 2D using a fixed isometric view.  Mirrors the 2D truss version
    `pil_draw_rod_context` from apps/truss/truss_reports.py."""
    import math
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (size, size), (255, 255, 255))
    d = ImageDraw.Draw(img)
    if not nodes:
        return img

    az = math.radians(30)
    el = math.radians(25)

    pts_2d = [_iso_project(x, y, z, az, el) for x, y, z in nodes]
    xs = [p[0] for p in pts_2d]
    ys = [p[1] for p in pts_2d]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    spanx = (maxx - minx) or 1.0
    spany = (maxy - miny) or 1.0
    pad = 24
    scale = min((size - 2 * pad) / spanx, (size - 2 * pad) / spany)
    cx0 = (minx + maxx) / 2
    cy0 = (miny + maxy) / 2

    def tx(idx):
        sx, sy = pts_2d[idx]
        return (size / 2 + (sx - cx0) * scale,
                size / 2 + (sy - cy0) * scale)

    for i, m in enumerate(members):
        if i == member_idx:
            continue
        p0, p1 = tx(m['a']), tx(m['b'])
        d.line([p0, p1], fill=(200, 200, 200), width=2)

    mem = members[member_idx]
    p0, p1 = tx(mem['a']), tx(mem['b'])
    color = (136, 136, 136)
    if member_res:
        f = member_res[member_idx].get('N', 0.0)
        if f > 0.01:
            color = (226, 75, 74)
        elif f < -0.01:
            color = (55, 138, 221)
    d.line([p0, p1], fill=color, width=4)

    font = _get_ttf_font(11)
    for i, _ in enumerate(nodes):
        x, y = tx(i)
        if i in (mem['a'], mem['b']):
            d.ellipse([x - 5, y - 5, x + 5, y + 5],
                      fill=(239, 159, 39), outline=(51, 51, 51))
            d.text((x, y - 16), str(i), fill=(51, 51, 51), font=font,
                   anchor='mm')
        else:
            d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(153, 153, 153))
    return img


def pil_draw_node_fbd_3d(node_idx, nodes, members, member_res, loads,
                         reactions, size=340):
    """Render a free-body diagram at a node with isometric X/Y/Z axes and
    engineering vector notation: F = |F| [ux, uy, uz] kN."""
    import math
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (size, size), (255, 255, 255))
    d = ImageDraw.Draw(img)
    cx = cy = size / 2

    az = math.radians(30)
    el = math.radians(25)

    # ── Draw isometric X / Y / Z axes ───────────────────────────────────
    axis_len = size * 0.18
    axis_color = (180, 180, 180)
    axis_font = _get_ttf_font(11)
    for label, vec3 in (('X', (1, 0, 0)), ('Y', (0, 1, 0)), ('Z', (0, 0, 1))):
        sx, sy = _iso_project(*vec3, az, el)
        sm = math.hypot(sx, sy)
        if sm < 1e-6:
            continue
        ux, uy = sx / sm, sy / sm
        ex, ey = cx + ux * axis_len, cy + uy * axis_len
        d.line([(cx, cy), (ex, ey)], fill=axis_color, width=1)
        ah = 5
        ang = math.atan2(-(ey - cy), ex - cx)
        a1 = (ex - ah * math.cos(ang - 0.45), ey + ah * math.sin(ang - 0.45))
        a2 = (ex - ah * math.cos(ang + 0.45), ey + ah * math.sin(ang + 0.45))
        d.polygon([(ex, ey), a1, a2], fill=axis_color)
        lx = cx + ux * (axis_len + 12)
        ly = cy + uy * (axis_len + 12)
        d.text((lx, ly), label, fill=(120, 120, 120), font=axis_font,
               anchor='mm')

    nx, ny, nz = nodes[node_idx]

    # ── Collect force vectors ────────────────────────────────────────────
    vecs = []
    for mi, m in enumerate(members):
        if m['a'] != node_idx and m['b'] != node_idx:
            continue
        other = m['b'] if m['a'] == node_idx else m['a']
        ox, oy, oz = nodes[other]
        dx, dy, dz = ox - nx, oy - ny, oz - nz
        L = math.sqrt(dx * dx + dy * dy + dz * dz)
        if L < 1e-12:
            continue
        N = member_res[mi].get('N', 0.0) if member_res else 0.0
        ux3, uy3, uz3 = dx / L, dy / L, dz / L
        fx3, fy3, fz3 = N * ux3, N * uy3, N * uz3
        sx, sy = _iso_project(fx3, fy3, fz3, az, el)
        mag = abs(N)
        kind = 'T' if N > 0.01 else ('C' if N < -0.01 else 'Z')
        if mag > 1e-9:
            sign = 1.0 if N >= 0 else -1.0
            uvec = (sign * ux3, sign * uy3, sign * uz3)
        else:
            uvec = (ux3, uy3, uz3)
        vecs.append({'sx': sx, 'sy': sy, 'mag': mag, 'kind': kind,
                     'name': f'M{mi}', 'uvec': uvec})

    load = next((l for l in loads if l['node'] == node_idx), None)
    if load:
        lfx = load.get('fx', 0.0)
        lfy = load.get('fy', 0.0)
        lfz = load.get('fz', 0.0)
        lmag = math.sqrt(lfx ** 2 + lfy ** 2 + lfz ** 2)
        if lmag > 1e-6:
            lsx, lsy = _iso_project(lfx, lfy, lfz, az, el)
            vecs.append({'sx': lsx, 'sy': lsy, 'mag': lmag, 'kind': 'L',
                         'name': 'Load',
                         'uvec': (lfx / lmag, lfy / lmag, lfz / lmag)})

    rxn = reactions.get(node_idx) if reactions else None
    if rxn:
        rfx = rxn.get('Fx', 0.0)
        rfy = rxn.get('Fy', 0.0)
        rfz = rxn.get('Fz', 0.0)
        rmag = math.sqrt(rfx ** 2 + rfy ** 2 + rfz ** 2)
        if rmag > 1e-6:
            rsx, rsy = _iso_project(rfx, rfy, rfz, az, el)
            vecs.append({'sx': rsx, 'sy': rsy, 'mag': rmag, 'kind': 'R',
                         'name': 'Rxn',
                         'uvec': (rfx / rmag, rfy / rmag, rfz / rmag)})

    mags = [v['mag'] for v in vecs]
    maxmag = max(mags) if mags else 1.0
    if maxmag < 1e-9:
        maxmag = 1.0
    Rmax, Rmin = size * 0.28, size * 0.11
    font = _get_ttf_font(9)
    font_sm = _get_ttf_font(8)

    def _vec_label(name, mag, uvec):
        ux, uy, uz = uvec
        return (f'{name} = {mag:.1f} kN\n'
                f'[{ux:+.2f}, {uy:+.2f}, {uz:+.2f}]')

    def arrow(v, color):
        sx2d, sy2d = v['sx'], v['sy']
        screen_mag = math.hypot(sx2d, sy2d)
        if screen_mag < 1e-6:
            return
        ux, uy = sx2d / screen_mag, sy2d / screen_mag
        length = Rmin + (Rmax - Rmin) * (v['mag'] / maxmag)
        ex, ey = cx + ux * length, cy + uy * length
        dashed = v['kind'] in ('L', 'R')
        if dashed:
            n_dash = max(2, int(length / 6))
            for k in range(n_dash):
                if k % 2 == 0:
                    x0 = cx + ux * length * k / n_dash
                    y0 = cy + uy * length * k / n_dash
                    x1 = cx + ux * length * (k + 1) / n_dash
                    y1 = cy + uy * length * (k + 1) / n_dash
                    d.line([(x0, y0), (x1, y1)], fill=color, width=2)
        else:
            d.line([(cx, cy), (ex, ey)], fill=color, width=2)
        ang = math.atan2(-(ey - cy), ex - cx)
        ah = 8
        a1 = (ex - ah * math.cos(ang - 0.4), ey + ah * math.sin(ang - 0.4))
        a2 = (ex - ah * math.cos(ang + 0.4), ey + ah * math.sin(ang + 0.4))
        d.polygon([(ex, ey), a1, a2], fill=color)
        label = _vec_label(v['name'], v['mag'], v['uvec'])
        lx = cx + ux * (length + 30)
        ly = cy + uy * (length + 30)
        d.multiline_text((lx, ly), label, fill=color, font=font_sm,
                         anchor='mm', align='center')

    for v in vecs:
        if v['kind'] == 'T':
            color = (226, 75, 74)
        elif v['kind'] == 'C':
            color = (55, 138, 221)
        elif v['kind'] == 'L':
            color = (216, 90, 48)
        elif v['kind'] == 'R':
            color = (46, 204, 113)
        else:
            color = (136, 136, 136)
        arrow(v, color)

    d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(51, 51, 51))
    return img


def export_excel(nodes, members, loads, supports, results, path, checks=None,
                  meta=None, max_calc_members=None, profiles=None):
    """Write a workbook with Nodes, Members, Loads, Supports, Results (if
    `results` is not None), Member Checks (if `checks` is not None) and a
    machine-parseable Model sheet. `meta` is an optional dict of free-text
    generator parameters (typology, span, etc.) written at the top of the
    Model sheet purely for a human reader's benefit; it is not required by
    `import_excel_model`.

    `max_calc_members` caps the Member Calculations sheet to the N most
    critical members (sorted by utilization desc). None = all members.
    """
    if not _ensure_openpyxl():
        raise RuntimeError('openpyxl is required for Excel export and could not '
                            'be installed automatically.')
    import math
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    HDR_FILL = PatternFill('solid', fgColor='404040')
    HDR_FONT = Font(name='Arial', bold=True, color='FFFFFF', size=10)
    BODY_FONT = Font(name='Arial', size=10)
    TITLE_FONT = Font(name='Arial', bold=True, size=14, color='1F4E79')
    LABEL_FONT = Font(name='Arial', bold=True, size=10, color='333333')
    VALUE_FONT = Font(name='Arial', size=10)
    OVER_FILL = PatternFill('solid', fgColor='FDECEA')
    OK_FILL = PatternFill('solid', fgColor='E2EFDA')
    thin_side = Side(style='thin', color='BFBFBF')
    THIN_BORDER = Border(left=thin_side, right=thin_side,
                         top=thin_side, bottom=thin_side)

    def styled_header(ws, labels, row=1):
        for col, lbl in enumerate(labels, 1):
            c = ws.cell(row=row, column=col, value=lbl)
            c.font = HDR_FONT
            c.fill = HDR_FILL
            c.border = THIN_BORDER
            c.alignment = Alignment(horizontal='center')
        ws.row_dimensions[row].height = 22

    def style_data_range(ws, start_row, end_row, n_cols):
        for r in range(start_row, end_row + 1):
            for c in range(1, n_cols + 1):
                cell = ws.cell(row=r, column=c)
                cell.border = THIN_BORDER
                cell.font = BODY_FONT

    # ── Cover sheet ──────────────────────────────────────────────────────────
    ws_cover = wb.create_sheet('Summary')
    ws_cover.sheet_properties.tabColor = '1F4E79'
    ws_cover.column_dimensions['A'].width = 28
    ws_cover.column_dimensions['B'].width = 20
    ws_cover.column_dimensions['C'].width = 10

    r = 1
    t = ws_cover.cell(row=r, column=1, value='STEREO STRUCTURE CALCULATOR')
    t.font = TITLE_FONT
    t.alignment = Alignment(horizontal='left')
    r += 1
    import datetime
    ws_cover.cell(row=r, column=1, value='Export date:').font = LABEL_FONT
    ws_cover.cell(row=r, column=2,
                  value=datetime.datetime.now().strftime('%Y-%m-%d %H:%M')).font = VALUE_FONT
    r += 1
    if meta and meta.get('grid_family'):
        ws_cover.cell(row=r, column=1, value='Grid family:').font = LABEL_FONT
        ws_cover.cell(row=r, column=2, value=meta['grid_family']).font = VALUE_FONT
        r += 1
    r += 1

    cover_data = [
        ('Nodes', len(nodes)),
        ('Members', len(members)),
        ('Loads', len(loads)),
        ('Supports', len(supports)),
    ]

    if results is not None:
        forces = [mr.get('N', 0.0) for mr in results['member_res']]
        max_t = max((f for f in forces if f > 0), default=0.0)
        max_c = min((f for f in forces if f < 0), default=0.0)
        disps = results.get('node_res', [])
        max_d = 0.0
        for nr in disps:
            d = math.sqrt(nr.get('ux', 0)**2 + nr.get('uy', 0)**2 + nr.get('uz', 0)**2)
            if d > max_d:
                max_d = d
        rxns = results.get('reactions', {})
        tot_fz = sum(r.get('Fz', 0.0) for r in rxns.values())
        cover_data += [
            ('', ''),
            ('Max tension (kN)', round(max_t, 2)),
            ('Max compression (kN)', round(max_c, 2)),
            ('Max displacement (mm)', round(max_d, 4)),
            ('Total vertical reaction (kN)', round(tot_fz, 2)),
        ]

    if checks is not None:
        n_checked = sum(1 for c in checks if c.get('checked'))
        n_over = sum(1 for c in checks if c.get('checked') and c.get('util', 0) > 1.0)
        max_util = max((c.get('util', 0) for c in checks if c.get('checked')), default=0.0)
        cover_data += [
            ('', ''),
            ('Members checked', n_checked),
            ('Members over capacity', n_over),
            ('Governing utilization', round(max_util, 3)),
        ]

    for label, val in cover_data:
        if label == '':
            r += 1
            continue
        ws_cover.cell(row=r, column=1, value=label).font = LABEL_FONT
        c = ws_cover.cell(row=r, column=2, value=val)
        c.font = VALUE_FONT
        if isinstance(val, (int, float)):
            c.number_format = '0.00' if isinstance(val, float) else '0'
        r += 1

    # ── Nodes ────────────────────────────────────────────────────────────────
    ws = wb.create_sheet('Nodes')
    styled_header(ws, ['idx', 'x_m', 'y_m', 'z_m'])
    for i, (x, y, z) in enumerate(nodes):
        ws.append([i, x, y, z])
    style_data_range(ws, 2, 1 + len(nodes), 4)

    # ── Members ──────────────────────────────────────────────────────────────
    ws = wb.create_sheet('Members')
    mem_hdrs = ['idx', 'a', 'b', 'conn', 'E_GPa', 'A_cm2', 'I_cm4', 'J_cm4',
                'Fy_MPa', 'Fu_MPa', 'K', 'r_gyr_cm', 'role', 'profile']
    styled_header(ws, mem_hdrs)
    for i, m in enumerate(members):
        ws.append([i, m['a'], m['b'], m.get('conn', 'pin'), m.get('E'), m.get('A'),
                   m.get('I'), m.get('J'), m.get('Fy'), m.get('Fu'), m.get('K', 1.0),
                   m.get('r_gyr'), m.get('role', ''), m.get('profile', '')])
    style_data_range(ws, 2, 1 + len(members), len(mem_hdrs))

    # ── Loads ────────────────────────────────────────────────────────────────
    ws = wb.create_sheet('Loads')
    ld_hdrs = ['node', 'fx_kN', 'fy_kN', 'fz_kN', 'mx_kNm', 'my_kNm', 'mz_kNm']
    styled_header(ws, ld_hdrs)
    for ld in loads:
        ws.append([ld['node'], ld.get('fx', 0.0), ld.get('fy', 0.0), ld.get('fz', 0.0),
                   ld.get('mx', 0.0), ld.get('my', 0.0), ld.get('mz', 0.0)])
    style_data_range(ws, 2, 1 + len(loads), len(ld_hdrs))

    # ── Supports ─────────────────────────────────────────────────────────────
    ws = wb.create_sheet('Supports')
    sup_hdrs = ['node', 'type', 'ux', 'uy', 'uz', 'rx', 'ry', 'rz']
    styled_header(ws, sup_hdrs)
    from apps.stereo.stereo_math import support_restraints
    for sp in supports:
        r = support_restraints(sp)
        ws.append([sp['node'], sp.get('type') or '', r['ux'], r['uy'], r['uz'],
                   r['rx'], r['ry'], r['rz']])
    style_data_range(ws, 2, 1 + len(supports), len(sup_hdrs))

    # ── Node Properties (displacements + reactions + moments) ─────────────────
    if results is not None:
        ws = wb.create_sheet('Node Properties')
        np_hdrs = ['node', 'ux_mm', 'uy_mm', 'uz_mm', 'rx_rad', 'ry_rad', 'rz_rad',
                   'Fx_kN', 'Fy_kN', 'Fz_kN', 'Mx_kNm', 'My_kNm', 'Mz_kNm']
        styled_header(ws, np_hdrs)
        reactions = results.get('reactions', {})
        for i, nr in enumerate(results['node_res']):
            rx = reactions.get(i, {})
            ws.append([i, nr['ux'], nr['uy'], nr['uz'],
                       nr['rx'], nr['ry'], nr['rz'],
                       rx.get('Fx', ''), rx.get('Fy', ''), rx.get('Fz', ''),
                       rx.get('Mx', ''), rx.get('My', ''), rx.get('Mz', '')])
        style_data_range(ws, 2, 1 + len(results['node_res']), len(np_hdrs))

        # ── Member Forces (with axial-force color scale) ─────────────────────
        ws2 = wb.create_sheet('Member Forces')
        mf_hdrs = ['member', 'a', 'b', 'conn', 'N_kN', 'length_m']
        styled_header(ws2, mf_hdrs)
        for i, (m, mr) in enumerate(zip(members, results['member_res'])):
            ws2.append([i, m['a'], m['b'], mr.get('conn', 'pin'), mr.get('N', 0.0),
                        mr.get('length_m', 0.0)])
        n_mf = len(members)
        style_data_range(ws2, 2, 1 + n_mf, len(mf_hdrs))
        if n_mf > 0:
            col_letter = get_column_letter(5)
            rng = f'{col_letter}2:{col_letter}{1 + n_mf}'
            ws2.conditional_formatting.add(rng, ColorScaleRule(
                start_type='min', start_color='4472C4',
                mid_type='percentile', mid_value=50, mid_color='D9D9D9',
                end_type='max', end_color='C00000'))

        # ── Reactions ────────────────────────────────────────────────────────
        ws3 = wb.create_sheet('Reactions')
        rxn_hdrs = ['node', 'Fx_kN', 'Fy_kN', 'Fz_kN', 'Mx_kNm', 'My_kNm', 'Mz_kNm']
        styled_header(ws3, rxn_hdrs)
        for node, rx in results['reactions'].items():
            ws3.append([node, rx.get('Fx', 0.0), rx.get('Fy', 0.0), rx.get('Fz', 0.0),
                        rx.get('Mx', 0.0), rx.get('My', 0.0), rx.get('Mz', 0.0)])
        style_data_range(ws3, 2, 1 + len(results['reactions']), len(rxn_hdrs))

    # ── Member Checks (with utilization color scale) ─────────────────────────
    if checks is not None:
        ws = wb.create_sheet('Member Checks')
        chk_hdrs = ['member', 'a', 'b', 'role', 'conn', 'N_kN', 'mode',
                    'A_cm2', 'r_gyr_cm', 'K', 'length_m', 'slenderness',
                    'sigma_MPa', 'capacity_MPa', 'Fcr_MPa', 'Pd_kN',
                    'utilization', 'governing', 'ok', 'note']
        styled_header(ws, chk_hdrs)
        member_res = results['member_res'] if results else [{}] * len(members)
        for i, c in enumerate(checks):
            row_num = i + 2
            m = members[i]
            mr = member_res[i] if i < len(member_res) else {}
            ws.append([
                i, m['a'], m['b'], m.get('role', ''), m.get('conn', 'pin'),
                mr.get('N', ''),
                c.get('mode', ''),
                m.get('A', ''), m.get('r_gyr', ''), m.get('K', 1.0),
                mr.get('length_m', ''),
                c.get('slenderness', ''),
                c.get('sigma_MPa', ''),
                c.get('capacity_MPa', ''),
                c.get('Fcr_MPa', ''),
                c.get('Pd_kN', ''),
                c.get('util'),
                c.get('governing', ''), c.get('ok', ''),
                c.get('note', ''),
            ])
            if c.get('checked') and c.get('util', 0) > 1.0:
                for col in range(1, len(chk_hdrs) + 1):
                    ws.cell(row=row_num, column=col).fill = OVER_FILL
            elif c.get('checked') and c.get('ok'):
                for col in range(1, len(chk_hdrs) + 1):
                    ws.cell(row=row_num, column=col).fill = OK_FILL
        n_chk = len(checks)
        style_data_range(ws, 2, 1 + n_chk, len(chk_hdrs))
        if n_chk > 0:
            util_col = chk_hdrs.index('utilization') + 1
            col_letter = get_column_letter(util_col)
            rng = f'{col_letter}2:{col_letter}{1 + n_chk}'
            ws.conditional_formatting.add(rng, ColorScaleRule(
                start_type='num', start_value=0, start_color='70AD47',
                mid_type='num', mid_value=0.7, mid_color='FFC000',
                end_type='num', end_value=1.0, end_color='C00000'))

    # ── Member Calculations (picture-in-context + FBD at each end) ─────────
    if results is not None:
        try:
            from openpyxl.drawing.image import Image as XLImage
            ws_mc = wb.create_sheet('Member Calculations')
            ws_mc.merge_cells('A1:N1')
            t_mc = ws_mc['A1']
            t_mc.value = ('STEREO STRUCTURE CALCULATOR — MEMBER CALCULATIONS '
                          '(location + force vectors)')
            t_mc.font = Font(name='Arial', bold=True, size=13, color='1F4E79')
            t_mc.alignment = Alignment(horizontal='center', vertical='center')
            t_mc.fill = PatternFill('solid', start_color='D6E4F0')
            note_mc = ws_mc.cell(row=2, column=1,
                value='Left: member location in the structure. '
                      'Middle/Right: free-body diagram at each end node '
                      '(every member, load and reaction converging there).')
            ws_mc.merge_cells('A2:N2')
            note_mc.font = Font(name='Arial', italic=True, size=9,
                                color='555555')

            IMG_PX = 340
            ROWS_PER_BLOCK = 20
            COLS_PER_IMG = 7
            for c in range(1, 3 * COLS_PER_IMG + 3):
                ws_mc.column_dimensions[get_column_letter(c)].width = 9

            member_res = results['member_res']
            reactions = results.get('reactions', {})

            calc_indices = list(range(len(members)))
            if max_calc_members is not None and len(calc_indices) > max_calc_members:
                def _util_key(i):
                    if checks and i < len(checks) and checks[i].get('checked'):
                        return -checks[i].get('util', 0.0)
                    return 0.0
                calc_indices = sorted(calc_indices, key=_util_key)[:max_calc_members]
                calc_indices.sort()

            row0 = 4
            for mi in calc_indices:
                mem = members[mi]
                a, b = mem['a'], mem['b']
                na, nb = nodes[a], nodes[b]
                dx = nb[0] - na[0]
                dy = nb[1] - na[1]
                dz = nb[2] - na[2]
                Lm = math.sqrt(dx * dx + dy * dy + dz * dz)
                N = member_res[mi].get('N', 0.0)
                kind = ('Tension' if N > 0.01
                        else ('Compression' if N < -0.01 else 'Zero'))

                hdr_row = row0
                ws_mc.merge_cells(start_row=hdr_row, start_column=1,
                                  end_row=hdr_row, end_column=14)
                hc = ws_mc.cell(row=hdr_row, column=1,
                    value=(f'Member {mi}  (Node {a} → Node {b})   '
                           f'L={Lm:.3f} m   N={N:+.2f} kN   [{kind}]'))
                hc.font = Font(name='Arial', bold=True, size=11,
                               color='1F4E79')
                hc.fill = PatternFill('solid', start_color='EFF4FA')

                img_row = hdr_row + 1
                ctx_img = pil_draw_member_context_3d(
                    nodes, members, mi, member_res, size=IMG_PX)
                fbd_a = pil_draw_node_fbd_3d(
                    a, nodes, members, member_res, loads, reactions,
                    size=IMG_PX)
                fbd_b = pil_draw_node_fbd_3d(
                    b, nodes, members, member_res, loads, reactions,
                    size=IMG_PX)

                ws_mc.cell(row=img_row, column=1,
                           value='Location in structure').font = Font(
                    size=9, italic=True, color='777777')
                ws_mc.cell(row=img_row, column=1 + COLS_PER_IMG,
                           value=f'End A — Node {a}').font = Font(
                    size=9, italic=True, color='777777')
                ws_mc.cell(row=img_row, column=1 + 2 * COLS_PER_IMG,
                           value=f'End B — Node {b}').font = Font(
                    size=9, italic=True, color='777777')

                ws_mc.add_image(
                    XLImage(_pil_to_xlsx_buf(ctx_img)),
                    f'{get_column_letter(1)}{img_row + 1}')
                ws_mc.add_image(
                    XLImage(_pil_to_xlsx_buf(fbd_a)),
                    f'{get_column_letter(1 + COLS_PER_IMG)}{img_row + 1}')
                ws_mc.add_image(
                    XLImage(_pil_to_xlsx_buf(fbd_b)),
                    f'{get_column_letter(1 + 2 * COLS_PER_IMG)}{img_row + 1}')

                row0 = hdr_row + ROWS_PER_BLOCK
        except Exception:
            pass

    # ── Gusset Plates (Whitmore + block shear for coplanar nodes) ─────────────
    if results is not None:
        from apps.stereo import stereo_plates as sp
        member_res = results['member_res']
        Fy_plate = members[0].get('Fy', sp.DEFAULT_FY_MPA) if members else sp.DEFAULT_FY_MPA
        Fu_plate = members[0].get('Fu', sp.DEFAULT_FU_MPA) if members else sp.DEFAULT_FU_MPA
        gusset_checks = sp.check_all_gussets(
            nodes, members, member_res, Fy=Fy_plate, Fu=Fu_plate)
        if gusset_checks:
            ws_gp = wb.create_sheet('Gusset Plates')
            gp_hdrs = ['group', 'node', 'member', 'other', 'N_kN', 'mode',
                       't_mm', 'whitmore_mm', 'sigma_MPa', 'whitmore_util',
                       'Agv_mm2', 'Anv_mm2', 'Ant_mm2',
                       'block_shear_Rd_kN', 'block_shear_util',
                       'buckling_applies', 'buckling_util', 'buckling_Pd_kN',
                       'utilization', 'governing', 'ok']
            styled_header(ws_gp, gp_hdrs)
            for gc in gusset_checks:
                ws_gp.append([
                    gc['group'], gc['node'], gc['member'], gc['other'],
                    gc['N_kN'], gc['mode'], gc['t_mm'], gc['whitmore_mm'],
                    gc['sigma_MPa'], gc['whitmore_util'],
                    gc['Agv'], gc['Anv'], gc['Ant'],
                    gc['block_shear_Rd_kN'], gc['block_shear_util'],
                    gc['buckling_applies'], gc['buckling_util'],
                    gc.get('buckling_Pd_kN', ''),
                    gc['util'], gc['governing'], gc['ok'],
                ])
                row_num = ws_gp.max_row
                if gc['util'] > 1.0:
                    for col in range(1, len(gp_hdrs) + 1):
                        ws_gp.cell(row=row_num, column=col).fill = OVER_FILL
                elif gc['ok']:
                    for col in range(1, len(gp_hdrs) + 1):
                        ws_gp.cell(row=row_num, column=col).fill = OK_FILL
            n_gp = len(gusset_checks)
            style_data_range(ws_gp, 2, 1 + n_gp, len(gp_hdrs))
            if n_gp > 0:
                util_col = gp_hdrs.index('utilization') + 1
                col_letter = get_column_letter(util_col)
                rng = f'{col_letter}2:{col_letter}{1 + n_gp}'
                ws_gp.conditional_formatting.add(rng, ColorScaleRule(
                    start_type='num', start_value=0, start_color='70AD47',
                    mid_type='num', mid_value=0.7, mid_color='FFC000',
                    end_type='num', end_value=1.0, end_color='C00000'))

    # ── Model sheet (machine-parseable round-trip) ───────────────────────────
    _write_model_sheet(wb, nodes, members, loads, supports, meta,
                       results=results, checks=checks, profiles=profiles)

    for name in wb.sheetnames:
        ws = wb[name]
        for col in range(1, 22):
            ws.column_dimensions[get_column_letter(col)].width = 14

    wb.save(path)


def _write_model_sheet(wb, nodes, members, loads, supports, meta=None,
                       results=None, checks=None, profiles=None):
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
                                'J_cm4', 'Fy_MPa', 'Fu_MPa', 'K', 'r_gyr_cm', 'role',
                                'profile'], 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    for i, m in enumerate(members):
        vals = [i, m['a'], m['b'], m.get('conn', 'pin'), m.get('E'), m.get('A'),
                m.get('I'), m.get('J'), m.get('Fy'), m.get('Fu'), m.get('K', 1.0),
                m.get('r_gyr'), m.get('role', ''), m.get('profile', '')]
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

    if profiles:
        row += 1
        ws.cell(row=row, column=1, value='[PROFILES]'); row += 1
        prof_hdrs = ['name', 'E_GPa', 'A_cm2', 'I_cm4', 'J_cm4',
                     'Fy_MPa', 'Fu_MPa', 'r_gyr_cm', 'K', 'catalog', 'material']
        for col, lbl in enumerate(prof_hdrs, 1):
            ws.cell(row=row, column=col, value=lbl)
        row += 1
        for pname, pdata in sorted(profiles.items()):
            vals = [pname, pdata.get('E', ''), pdata.get('A', ''),
                    pdata.get('I', ''), pdata.get('J', ''),
                    pdata.get('Fy', ''), pdata.get('Fu', ''),
                    pdata.get('r_gyr', ''), pdata.get('K', ''),
                    pdata.get('catalog', ''), pdata.get('material', '')]
            for col, v in enumerate(vals, 1):
                ws.cell(row=row, column=col, value=v)
            row += 1

    if results is not None:
        row += 1
        ws.cell(row=row, column=1, value='[RESULTS_SUMMARY]'); row += 1
        ws.cell(row=row, column=1, value='key')
        ws.cell(row=row, column=2, value='value')
        row += 1

        max_disp = 0.0
        for nr in results['node_res']:
            d = (nr['ux'] ** 2 + nr['uy'] ** 2 + nr['uz'] ** 2) ** 0.5
            max_disp = max(max_disp, d)

        forces = [mr['N'] for mr in results['member_res']]
        max_tension = max(forces) if forces else 0.0
        max_compression = min(forces) if forces else 0.0
        total_rz = sum(r.get('Fz', 0.0) for r in results['reactions'].values())

        summary = [
            ('max_displacement_mm', round(max_disp, 4)),
            ('max_tension_kN', round(max_tension, 4)),
            ('max_compression_kN', round(max_compression, 4)),
            ('total_vertical_reaction_kN', round(total_rz, 4)),
        ]

        if checks is not None:
            from apps.stereo.stereo_checks import worst_utilization
            worst = worst_utilization(checks)
            n_over = sum(1 for c in checks if c.get('checked') and c['util'] > 1.0)
            n_checked = sum(1 for c in checks if c.get('checked'))
            summary.append(('governing_utilization', round(worst, 4) if worst is not None else ''))
            summary.append(('members_checked', n_checked))
            summary.append(('members_over_capacity', n_over))

        for key, val in summary:
            ws.cell(row=row, column=1, value=key)
            ws.cell(row=row, column=2, value=val)
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

    _SECTION_DEFAULTS = {'E': 200.0, 'A': 20.0, 'I': 400.0, 'J': 400.0,
                          'Fy': 235.0, 'Fu': 360.0, 'r_gyr': 4.0}
    members = []
    for r in read_table(find_section('[MEMBERS]')):
        m = {'a': int(r['a']), 'b': int(r['b']), 'conn': r.get('conn') or 'pin'}
        for key, field in (('E_GPa', 'E'), ('A_cm2', 'A'), ('I_cm4', 'I'),
                            ('J_cm4', 'J'), ('Fy_MPa', 'Fy'), ('Fu_MPa', 'Fu'),
                            ('r_gyr_cm', 'r_gyr')):
            v = r.get(key)
            if v is not None and v != '':
                m[field] = float(v)
        for field, default in _SECTION_DEFAULTS.items():
            m.setdefault(field, default)
        k = r.get('K')
        m['K'] = float(k) if k not in (None, '') else 1.0
        role = r.get('role')
        if role:
            m['role'] = str(role)
        profile = r.get('profile')
        if profile and str(profile).strip():
            m['profile'] = str(profile).strip()
        members.append(m)

    profiles = {}
    prof_idx = find_section('[PROFILES]')
    if prof_idx >= 0:
        for pr in read_table(prof_idx):
            pname = str(pr.get('name', '')).strip()
            if not pname:
                continue
            pdata = {}
            for key, field in (('E_GPa', 'E'), ('A_cm2', 'A'), ('I_cm4', 'I'),
                                ('J_cm4', 'J'), ('Fy_MPa', 'Fy'), ('Fu_MPa', 'Fu'),
                                ('r_gyr_cm', 'r_gyr')):
                v = pr.get(key)
                if v is not None and v != '':
                    pdata[field] = float(v)
            pk = pr.get('K')
            if pk not in (None, ''):
                pdata['K'] = float(pk)
            for extra in ('catalog', 'material'):
                v = pr.get(extra)
                if v and str(v).strip():
                    pdata[extra] = str(v).strip()
            profiles[pname] = pdata

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

    return nodes, members, loads, supports, profiles


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


def _sphere_mesh(cx, cy, cz, r, n_lon=8, n_lat=6):
    """Return (verts, faces) for a UV sphere centred at (cx,cy,cz)."""
    import math
    verts = []
    verts.append((cx, cy, cz + r))
    for i in range(1, n_lat):
        phi = math.pi * i / n_lat
        sp, cp = math.sin(phi), math.cos(phi)
        for j in range(n_lon):
            theta = 2.0 * math.pi * j / n_lon
            verts.append((cx + r * sp * math.cos(theta),
                          cy + r * sp * math.sin(theta),
                          cz + r * cp))
    verts.append((cx, cy, cz - r))

    faces = []
    for j in range(n_lon):
        j2 = (j + 1) % n_lon
        faces.append((0, 1 + j2, 1 + j))
    for i in range(n_lat - 2):
        base = 1 + i * n_lon
        for j in range(n_lon):
            j2 = (j + 1) % n_lon
            a = base + j
            b = base + j2
            c = base + n_lon + j2
            d = base + n_lon + j
            faces.append((a, b, c))
            faces.append((a, c, d))
    bot = len(verts) - 1
    base = 1 + (n_lat - 2) * n_lon
    for j in range(n_lon):
        j2 = (j + 1) % n_lon
        faces.append((bot, base + j, base + j2))
    return verts, faces


def _cylinder_mesh(ax, ay, az, bx, by, bz, r, n_sides=8):
    """Return (verts, faces) for a capped cylinder from A to B."""
    import math
    dx, dy, dz = bx - ax, by - ay, bz - az
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1e-12:
        return [], []
    ux, uy, uz = dx / length, dy / length, dz / length
    if abs(uz) < 0.9:
        px, py, pz = 0.0, 0.0, 1.0
    else:
        px, py, pz = 1.0, 0.0, 0.0
    vx = uy * pz - uz * py
    vy = uz * px - ux * pz
    vz = ux * py - uy * px
    vl = math.sqrt(vx * vx + vy * vy + vz * vz)
    vx, vy, vz = vx / vl, vy / vl, vz / vl
    wx = uy * vz - uz * vy
    wy = uz * vx - ux * vz
    wz = ux * vy - uy * vx

    verts = []
    for end_pt in ((ax, ay, az), (bx, by, bz)):
        ex, ey, ez = end_pt
        for j in range(n_sides):
            theta = 2.0 * math.pi * j / n_sides
            ct, st = math.cos(theta), math.sin(theta)
            verts.append((ex + r * (ct * vx + st * wx),
                          ey + r * (ct * vy + st * wy),
                          ez + r * (ct * vz + st * wz)))

    faces = []
    for j in range(n_sides):
        j2 = (j + 1) % n_sides
        a, b = j, j2
        c, d = n_sides + j2, n_sides + j
        faces.append((a, b, c))
        faces.append((a, c, d))
    for j in range(2, n_sides):
        faces.append((0, j - 1, j))
    base = n_sides
    for j in range(2, n_sides):
        faces.append((base, base + j, base + j - 1))
    return verts, faces


def export_obj(nodes, members, path, node_radius=0.0, rod_radius=0.0):
    """Export the model as a Wavefront OBJ file.

    node_radius / rod_radius in metres:
      - both 0  -> wireframe (vertices + line elements)
      - > 0     -> solid mesh (spheres at nodes, cylinders for rods)
    """
    lines = ['# Stereo structure model']
    wireframe = (node_radius <= 0.0 and rod_radius <= 0.0)

    if wireframe:
        for x, y, z in nodes:
            lines.append(f'v {x:.6f} {y:.6f} {z:.6f}')
        for m in members:
            lines.append(f'l {m["a"] + 1} {m["b"] + 1}')
    else:
        v_offset = 0
        if node_radius > 0:
            lines.append('o nodes')
            for x, y, z in nodes:
                verts, faces = _sphere_mesh(x, y, z, node_radius)
                for vx, vy, vz in verts:
                    lines.append(f'v {vx:.6f} {vy:.6f} {vz:.6f}')
                for f in faces:
                    lines.append(
                        f'f {f[0]+1+v_offset} {f[1]+1+v_offset} {f[2]+1+v_offset}')
                v_offset += len(verts)

        if rod_radius > 0:
            lines.append('o rods')
            for m in members:
                ax, ay, az = nodes[m['a']]
                bx, by, bz = nodes[m['b']]
                verts, faces = _cylinder_mesh(ax, ay, az, bx, by, bz,
                                             rod_radius)
                for vx, vy, vz in verts:
                    lines.append(f'v {vx:.6f} {vy:.6f} {vz:.6f}')
                for f in faces:
                    lines.append(
                        f'f {f[0]+1+v_offset} {f[1]+1+v_offset} {f[2]+1+v_offset}')
                v_offset += len(verts)
        else:
            for x, y, z in nodes:
                lines.append(f'v {x:.6f} {y:.6f} {z:.6f}')
            v_base = v_offset + 1
            for m in members:
                lines.append(f'l {m["a"]+v_base} {m["b"]+v_base}')

    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
