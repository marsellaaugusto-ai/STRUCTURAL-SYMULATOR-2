"""Excel export/import and text report for the Stereo tab, following the
same shape as apps/truss/truss_reports.py: a human-readable summary plus a
machine-parseable '[SECTION]' Model sheet that round-trips through
`import_excel_model`.

Includes PIL-rendered free-body-diagram images for each member, projected
from 3D to 2D using an isometric-style parallel projection.
"""
import units

from common import _ensure_openpyxl


# ── the units the Stereo tab stores in, and the ones a sheet writes ──────
#
# Every solver computes in SI; the tab holds its model in these units (see
# UnitsMixin and units.storage_like). Declared HERE, and imported by
# stereo_app, so the report and the tab cannot disagree about what the
# numbers in a member dict mean.
STORAGE_UNITS = units.storage_like('stereo storage', stress=units.MPA)


class ReportUnits:
    """A stored value -> the number and the label this report writes it in.

    The app has an app-wide unit selector, and until 2026-09-27 the PDF
    ignored it: 'kN', 'm' and 'mm' were hard-coded into sixty format
    strings and 'm, kN, mm' into the title block. Switch the app to AISC
    and the screen said kip while the sheet said kN, over the same model,
    with nothing on the sheet admitting it. Every number the report prints
    now goes through here.

    `system` defaults to whatever the selector is set to AT EXPORT TIME,
    which is the convention the reader was just looking at.
    """

    def __init__(self, system=None):
        self.system = units.current() if system is None else system

    def v(self, quantity, stored):
        """The number, in the reader's convention."""
        return units.reexpress(quantity, stored, STORAGE_UNITS, self.system)

    def to_storage(self, quantity, shown):
        """The inverse of v(): a number in the reader's convention back
        into the units the model is stored in.

        Needed wherever the report CHOOSES a round number -- a scale bar's
        length, a grid spacing, a triad arm. A bar that is a round 5
        metres is 16.4 feet, which is not a scale bar; the round number
        has to be picked in the unit it will be labelled with, and only
        then converted back to draw it.
        """
        return units.reexpress(quantity, shown, self.system, STORAGE_UNITS)

    def lab(self, quantity):
        return self.system.label(quantity)

    def f(self, quantity, stored, digits=2, sign=False, comma=False):
        """The number, formatted, WITHOUT its label."""
        spec = f'{"+" if sign else ""}{"," if comma else ""}.{digits}f'
        return format(self.v(quantity, stored), spec)

    def fl(self, quantity, stored, digits=2, sign=False, comma=False):
        """The number and its label, e.g. '12.50 kN'."""
        return f'{self.f(quantity, stored, digits, sign, comma)} ' \
               f'{self.lab(quantity)}'

    def title_block(self):
        """What the title block's UNITS field says."""
        return ', '.join((self.lab('length'), self.lab('force'),
                          self.lab('deflection')))

    # A stress computed straight from the model as |N| / A is in kN/cm^2:
    # kN over cm^2, the units those two are stored in. The tab stores a
    # stress in MPa (Fy, Fu), so it has to be carried across before it can
    # be re-expressed like any other stress.
    KN_CM2_TO_MPA = 10.0

    def stress_from_kn_cm2(self, sigma):
        return self.v('stress', sigma * self.KN_CM2_TO_MPA)

    def f_stress_kn_cm2(self, sigma, digits=2, comma=True):
        spec = f'{"," if comma else ""}.{digits}f'
        return (f'{format(self.stress_from_kn_cm2(sigma), spec)} '
                f'{self.lab("stress")}')


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


def member_data_rows(m, mr, chk, u):
    """(label, value) rows describing one rod, for the panel beside its
    pictures on the Member Calculations sheet (roadmap 2.4: the free-body
    images "next to their data").

    `u` is a ReportUnits, so the panel reads in the selected convention like
    the rest of the readable sheets. Anything the solve or the check did not
    produce is left out rather than shown as a zero.
    """
    import math as _m
    rows = [('Section', m.get('profile') or '—'),
            ('Connection', m.get('conn', 'pin'))]
    if m.get('A'):
        rows.append(('A', u.fl('area', float(m['A']))))
    if m.get('r_gyr'):
        rows.append(('r min', u.fl('section_length', float(m['r_gyr']))))
    L = float(mr.get('length_m') or 0.0)
    if L:
        rows.append(('L', u.fl('length', L, 3)))
    if L and m.get('r_gyr'):
        kl_r = float(m.get('K', 1.0)) * L * 100.0 / float(m['r_gyr'])
        rows.append(('KL/r', '%.0f' % kl_r))
    N = float(mr.get('N', 0.0) or 0.0)
    rows.append(('N', '%s  (%s)' % (u.fl('force', N, 2, sign=True),
                                    'tension' if N > 0.01 else
                                    'compression' if N < -0.01 else 'zero')))
    chk = chk or {}
    V = chk.get('V_demand_kN')
    if V is None and ('Vy_a' in mr or 'Vz_a' in mr):
        V = _m.hypot(float(mr.get('Vy_a', 0.0)), float(mr.get('Vz_a', 0.0)))
    if V is not None:
        rows.append(('V max', u.fl('force', float(V), 2)))
    M = chk.get('M_demand_kNm')
    if M is None and any(k in mr for k in ('My_a', 'Mz_a', 'My_b', 'Mz_b')):
        M = max(_m.hypot(float(mr.get('My_a', 0.0)), float(mr.get('Mz_a', 0.0))),
                _m.hypot(float(mr.get('My_b', 0.0)), float(mr.get('Mz_b', 0.0))))
    if M is not None:
        rows.append(('M max', u.fl('moment', float(M), 2)))
    if chk.get('checked'):
        rows.append(('Mode', str(chk.get('mode', ''))))
        if chk.get('capacity_MPa') is not None:
            rows.append(('Capacity', u.fl('stress', float(chk['capacity_MPa']), 1)))
        util = float(chk.get('util', 0.0))
        rows.append(('Utilisation', '%.2f  %s' % (util,
                                                  'OVER' if util > 1.0 else 'OK')))
        if chk.get('governing'):
            rows.append(('Governs', str(chk['governing'])))
    elif chk.get('note'):
        rows.append(('Check', str(chk['note'])))
    return rows


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


# The Member Calculations sheet embeds THREE rendered PNGs per member (the
# member in context, and a free-body diagram at each end). At three images a
# member that is 2,400 images and 25 MB of PNG for an 800-rod model, in a
# workbook that then takes 20 MB and a long time to open -- measured on the
# default grid, which is not a large model by this app's standards. The cap
# keeps the sheet to the members a reader would actually look at, chosen by
# utilization, and `max_calc_members=None` still means every member for a
# caller that wants it.
DEFAULT_MAX_CALC_MEMBERS = 40


def export_excel(nodes, members, loads, supports, results, path, checks=None,
                  meta=None, max_calc_members=DEFAULT_MAX_CALC_MEMBERS,
                  profiles=None, groups=None):
    """Write a workbook with Nodes, Members, Loads, Supports, Results (if
    `results` is not None), Member Checks (if `checks` is not None) and a
    machine-parseable Model sheet. `meta` is an optional dict of free-text
    generator parameters (typology, span, etc.) written at the top of the
    Model sheet purely for a human reader's benefit; it is not required by
    `import_excel_model`.

    `groups` (stereo_groups' list) adds the editable Groups sheet -- see
    stereo_groups_excel -- which Import from Excel reads back.

    `max_calc_members` caps the Member Calculations sheet to the N most
    critical members (sorted by utilization desc), and defaults to
    DEFAULT_MAX_CALC_MEMBERS for the reason given at that constant. Pass None
    for every member, and expect the file size to show it.
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

    # The sheets a PERSON reads follow the app-wide unit selector, like the
    # PDF. A header names its unit after the underscore ('N_kN'); under a
    # convention that shows that quantity in some other unit, the header and
    # every value under it are rewritten ('N_kip'). Under the SI conventions
    # nothing changes, so a workbook anyone already reads by column name
    # reads the same. The Model and Groups sheets stay in the stored units:
    # Import from Excel and the SketchUp extension read them by those
    # headers, and converting them would make a round trip change the model.
    xu = ReportUnits()
    _XL_TAGS = {'m': ('length', 1.0), 'mm': ('deflection', 1.0),
                'kN': ('force', 1.0), 'kNm': ('moment', 1.0),
                'MPa': ('stress', 1.0), 'GPa': ('modulus', 1.0),
                'cm2': ('area', 1.0), 'mm2': ('area', 0.01),
                'cm4': ('inertia', 1.0), 'cm': ('section_length', 1.0)}

    def _xl_q(h):
        if not isinstance(h, str) or '_' not in h:
            return None
        spec = _XL_TAGS.get(h.rsplit('_', 1)[1])
        if spec is None or xu.lab(spec[0]) == STORAGE_UNITS.label(spec[0]):
            return None
        return spec

    def xl_hdr(h):
        spec = _xl_q(h)
        if spec is None:
            return h
        return '%s_%s' % (h.rsplit('_', 1)[0],
                          xu.lab(spec[0]).replace('·', '').replace(' ', ''))

    def xl_row(hdrs, vals):
        out = []
        for h, v in zip(hdrs, vals):
            spec = _xl_q(h)
            if spec is not None and isinstance(v, (int, float)) and \
                    not isinstance(v, bool):
                v = xu.v(spec[0], v * spec[1])
            out.append(v)
        return out

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
            c = ws.cell(row=row, column=col, value=xl_hdr(lbl))
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
        ('Units', '%s — %s' % (xu.system.name, xu.title_block())),
        ('Model & Groups sheets', 'stored units (m, kN, cm, MPa), '
                                  'for Import'),
        ('', ''),
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
            ('Max tension (%s)' % xu.lab('force'),
             round(xu.v('force', max_t), 2)),
            ('Max compression (%s)' % xu.lab('force'),
             round(xu.v('force', max_c), 2)),
            ('Max displacement (%s)' % xu.lab('deflection'),
             round(xu.v('deflection', max_d), 4)),
            ('Total vertical reaction (%s)' % xu.lab('force'),
             round(xu.v('force', tot_fz), 2)),
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
        ws.append(xl_row(['idx', 'x_m', 'y_m', 'z_m'], [i, x, y, z]))
    style_data_range(ws, 2, 1 + len(nodes), 4)

    # ── Members ──────────────────────────────────────────────────────────────
    ws = wb.create_sheet('Members')
    # c_cm is APPENDED, not inserted, so no existing column moves for anyone
    # who reads these sheets by column letter. It is the real extreme-fibre
    # depth of a catalog section; a hand-typed section has none and the cell
    # is left empty rather than holding a guess.
    mem_hdrs = ['idx', 'a', 'b', 'conn', 'E_GPa', 'A_cm2', 'I_cm4', 'J_cm4',
                'Fy_MPa', 'Fu_MPa', 'K', 'r_gyr_cm', 'role', 'profile', 'c_cm']
    styled_header(ws, mem_hdrs)
    for i, m in enumerate(members):
        ws.append(xl_row(mem_hdrs, [
            i, m['a'], m['b'], m.get('conn', 'pin'), m.get('E'), m.get('A'),
            m.get('I'), m.get('J'), m.get('Fy'), m.get('Fu'), m.get('K', 1.0),
            m.get('r_gyr'), m.get('role', ''), m.get('profile', ''),
            m.get('c_cm')]))
    style_data_range(ws, 2, 1 + len(members), len(mem_hdrs))

    # ── Loads ────────────────────────────────────────────────────────────────
    ws = wb.create_sheet('Loads')
    ld_hdrs = ['node', 'fx_kN', 'fy_kN', 'fz_kN', 'mx_kNm', 'my_kNm', 'mz_kNm']
    styled_header(ws, ld_hdrs)
    for ld in loads:
        ws.append(xl_row(ld_hdrs, [
            ld['node'], ld.get('fx', 0.0), ld.get('fy', 0.0), ld.get('fz', 0.0),
            ld.get('mx', 0.0), ld.get('my', 0.0), ld.get('mz', 0.0)]))
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
            ws.append(xl_row(np_hdrs, [
                i, nr['ux'], nr['uy'], nr['uz'],
                nr['rx'], nr['ry'], nr['rz'],
                rx.get('Fx', ''), rx.get('Fy', ''), rx.get('Fz', ''),
                rx.get('Mx', ''), rx.get('My', ''), rx.get('Mz', '')]))
        style_data_range(ws, 2, 1 + len(results['node_res']), len(np_hdrs))

        # ── Member Forces (with axial-force color scale) ─────────────────────
        ws2 = wb.create_sheet('Member Forces')
        mf_hdrs = ['member', 'a', 'b', 'conn', 'N_kN', 'length_m']
        styled_header(ws2, mf_hdrs)
        for i, (m, mr) in enumerate(zip(members, results['member_res'])):
            ws2.append(xl_row(mf_hdrs, [
                i, m['a'], m['b'], mr.get('conn', 'pin'), mr.get('N', 0.0),
                mr.get('length_m', 0.0)]))
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
            ws3.append(xl_row(rxn_hdrs, [
                node, rx.get('Fx', 0.0), rx.get('Fy', 0.0), rx.get('Fz', 0.0),
                rx.get('Mx', 0.0), rx.get('My', 0.0), rx.get('Mz', 0.0)]))
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
            ws.append(xl_row(chk_hdrs, [
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
            ]))
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
            _n_all = len(members)
            _capped = (max_calc_members is not None
                       and _n_all > max_calc_members)
            note_mc = ws_mc.cell(row=2, column=1,
                value='Left: member location in the structure. '
                      'Middle/Right: free-body diagram at each end node '
                      '(every member, load and reaction converging there).'
                      + (f'  Showing the {max_calc_members} most utilized of '
                         f'{_n_all} rods -- each block carries three rendered '
                         f'images, so every rod would make this workbook '
                         f'unopenably large. Member Forces and Member Checks '
                         f'cover all {_n_all}.' if _capped else ''))
            ws_mc.merge_cells('A2:N2')
            note_mc.font = Font(name='Arial', italic=True, size=9,
                                color='555555')

            IMG_PX = 340
            ROWS_PER_BLOCK = 20
            COLS_PER_IMG = 7
            for c in range(1, 3 * COLS_PER_IMG + 3):
                ws_mc.column_dimensions[get_column_letter(c)].width = 9
            # the data panel: a label column and a value wide enough for
            # "H1-1b (P/Pc < 0.2), axial + bending"
            ws_mc.column_dimensions[get_column_letter(
                1 + 3 * COLS_PER_IMG)].width = 12
            ws_mc.column_dimensions[get_column_letter(
                2 + 3 * COLS_PER_IMG)].width = 40

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
                           f'L={xu.fl("length", Lm, 3)}   '
                           f'N={xu.fl("force", N, 2, sign=True)}   [{kind}]'))
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

                # The rod's own numbers, beside its pictures -- the section,
                # its slenderness, the forces and the check that governs --
                # so the free-body diagram can be read against them without
                # going to another sheet (roadmap 2.4).
                data_col = 1 + 3 * COLS_PER_IMG
                ws_mc.cell(row=img_row, column=data_col,
                           value='Data').font = Font(
                    size=9, italic=True, color='777777')
                chk_i = (checks[mi] if checks and mi < len(checks) else None)
                for k, (lbl, val) in enumerate(member_data_rows(
                        mem, member_res[mi], chk_i, xu)):
                    ws_mc.cell(row=img_row + 1 + k, column=data_col,
                               value=lbl).font = Font(bold=True, size=9)
                    ws_mc.cell(row=img_row + 1 + k, column=data_col + 1,
                               value=val).font = Font(size=9)

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
                ws_gp.append(xl_row(gp_hdrs, [
                    gc['group'], gc['node'], gc['member'], gc['other'],
                    gc['N_kN'], gc['mode'], gc['t_mm'], gc['whitmore_mm'],
                    gc['sigma_MPa'], gc['whitmore_util'],
                    gc['Agv'], gc['Anv'], gc['Ant'],
                    gc['block_shear_Rd_kN'], gc['block_shear_util'],
                    gc['buckling_applies'], gc['buckling_util'],
                    gc.get('buckling_Pd_kN', ''),
                    gc['util'], gc['governing'], gc['ok'],
                ]))
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

    # ── Groups sheet (editable; read back by Import from Excel) ─────────────
    if groups:
        from apps.stereo import stereo_groups_excel as _sge
        _sge.write_groups_sheet(wb, groups, members, checks=checks)

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
    # c_cm travels in the machine-read table too, or a catalog section that
    # makes the round trip through a workbook arrives without its depth and
    # its bending check falls back to a thin-tube guess -- 39% unsafe for an
    # angle. Appended, and read by column NAME on import, so a workbook
    # written before this column existed still loads.
    for col, lbl in enumerate(['idx', 'a', 'b', 'conn', 'E_GPa', 'A_cm2', 'I_cm4',
                                'J_cm4', 'Fy_MPa', 'Fu_MPa', 'K', 'r_gyr_cm', 'role',
                                'profile', 'c_cm'], 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    for i, m in enumerate(members):
        vals = [i, m['a'], m['b'], m.get('conn', 'pin'), m.get('E'), m.get('A'),
                m.get('I'), m.get('J'), m.get('Fy'), m.get('Fu'), m.get('K', 1.0),
                m.get('r_gyr'), m.get('role', ''), m.get('profile', ''),
                m.get('c_cm')]
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
                     'Fy_MPa', 'Fu_MPa', 'r_gyr_cm', 'K', 'catalog', 'material',
                     'c_cm']
        for col, lbl in enumerate(prof_hdrs, 1):
            ws.cell(row=row, column=col, value=lbl)
        row += 1
        for pname, pdata in sorted(profiles.items()):
            vals = [pname, pdata.get('E', ''), pdata.get('A', ''),
                    pdata.get('I', ''), pdata.get('J', ''),
                    pdata.get('Fy', ''), pdata.get('Fu', ''),
                    pdata.get('r_gyr', ''), pdata.get('K', ''),
                    pdata.get('catalog', ''), pdata.get('material', ''),
                    pdata.get('c_cm', '')]
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
        # Absent in a workbook written before the column existed: then the
        # member simply has no depth, and the bending check's I/A fall-back
        # applies -- conservative for the I and channel sections where the
        # radius error was largest.
        c = r.get('c_cm')
        if c not in (None, ''):
            try:
                if float(c) > 0.0:
                    m['c_cm'] = float(c)
            except (TypeError, ValueError):
                pass
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
            # The catalog depth, so assigning a re-imported profile hands it
            # on (stereo_profiles.write_section) instead of dropping it.
            pc = pr.get('c_cm')
            if pc not in (None, ''):
                try:
                    if float(pc) > 0.0:
                        pdata['c_cm'] = float(pc)
                except (TypeError, ValueError):
                    pass
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


def summary_text(nodes, members, results, checks=None, u=None):
    """A short human-readable analysis summary, for the tab's results pane
    -- the same role truss_app._show_analysis_text plays for Truss."""
    u = u or ReportUnits()
    lines = [f'Nodes: {len(nodes)}   Members: {len(members)}']
    if results is None:
        lines.append('Not yet analyzed.')
        return '\n'.join(lines)

    max_disp = 0.0
    for nr in results['node_res']:
        d = (nr['ux'] ** 2 + nr['uy'] ** 2 + nr['uz'] ** 2) ** 0.5
        max_disp = max(max_disp, d)
    lines.append(f'Max nodal displacement: '
                 f'{u.fl("deflection", max_disp, 3)}')

    forces = [mr['N'] for mr in results['member_res']]
    if forces:
        lines.append(f'Max tension:     '
                     f'{u.fl("force", max(forces), 2, sign=True)}')
        lines.append(f'Max compression: '
                     f'{u.fl("force", min(forces), 2, sign=True)}')

    total_rz = sum(r.get('Fz', 0.0) for r in results['reactions'].values())
    lines.append(f'Total vertical reaction: {u.fl("force", total_rz)}')

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


# ── SketchUp Ruby script export ───────────────────────────────────────────

def export_sketchup_ruby(nodes, members, path, node_radius=0.0, rod_radius=0.0,
                         supports=None, results=None):
    """Generate a Ruby script (.rb) that recreates the 3D model inside SketchUp.

    When executed in SketchUp (Window > Ruby Console, then `load "<path>"`),
    it builds all nodes and members as SketchUp geometry. Supports are
    marked with a colored construction point. Optionally includes analysis
    results as attribute dictionaries on each edge/vertex.

    node_radius, rod_radius: 0 = wireframe (edges only), >0 = solid meshes.
    """
    M_TO_INCH = 39.3700787402
    rb = []
    rb.append('# Stereo Structure — SketchUp model import script')
    rb.append('# Generated by Stereo App (structural_symulator)')
    rb.append('# Run in SketchUp: Window > Ruby Console, then load this file.')
    rb.append('')
    rb.append('model = Sketchup.active_model')
    rb.append('model.start_operation("Import Stereo Model", true)')
    rb.append('ents = model.active_entities')
    rb.append('')

    rb.append(f'# Nodes ({len(nodes)})')
    rb.append('nodes = []')
    for i, (x, y, z) in enumerate(nodes):
        xi = x * M_TO_INCH
        yi = y * M_TO_INCH
        zi = z * M_TO_INCH
        rb.append(f'nodes << Geom::Point3d.new({xi:.6f}, {yi:.6f}, {zi:.6f})')

    rb.append('')

    if node_radius > 0 or rod_radius > 0:
        rb.append('# Solid geometry helpers')
        rb.append(f'NODE_R = {node_radius * M_TO_INCH:.6f}')
        rb.append(f'ROD_R  = {rod_radius * M_TO_INCH:.6f}')
        rb.append('')
        if node_radius > 0:
            rb.append('# Draw node spheres')
            rb.append('nodes.each do |pt|')
            rb.append('  grp = ents.add_group')
            rb.append('  circle = grp.entities.add_circle(pt, [0,0,1], NODE_R, 12)')
            rb.append('  face = grp.entities.add_face(circle)')
            rb.append('  face.pushpull(NODE_R * 2) if face')
            rb.append('end')
            rb.append('')

    rb.append(f'# Members ({len(members)})')
    if rod_radius > 0:
        rb.append('# Draw rod cylinders')
        for i, m in enumerate(members):
            rb.append(f'# Member {i}: {m["a"]} -> {m["b"]}')
            rb.append(f'grp = ents.add_group')
            rb.append(f'p1, p2 = nodes[{m["a"]}], nodes[{m["b"]}]')
            rb.append(f'vec = p2 - p1')
            rb.append(f'circle = grp.entities.add_circle(p1, vec, ROD_R, 12)')
            rb.append(f'face = grp.entities.add_face(circle)')
            rb.append(f'face.pushpull(vec.length) if face')
    else:
        rb.append('# Wireframe edges')
        for i, m in enumerate(members):
            rb.append(f'ents.add_edges(nodes[{m["a"]}], nodes[{m["b"]}])')

    if supports:
        rb.append('')
        rb.append('# Supports')
        for s in supports:
            ni = s['node']
            stype = s.get('type', 'custom')
            rb.append(f'cp = ents.add_cpoint(nodes[{ni}])  # Support: {stype}')

    if results:
        rb.append('')
        rb.append('# Store analysis results as attribute dictionaries')
        rb.append('# Access via: entity.get_attribute("StereoResults", "key")')
        member_res = results.get('member_res', [])
        for i, mr in enumerate(member_res):
            N = mr.get('N', 0.0)
            rb.append(f'# Member {i}: N = {N:+.3f} kN')

    rb.append('')
    rb.append('model.commit_operation')
    rb.append(f'UI.messagebox("Imported {len(nodes)} nodes and {len(members)} members.")')

    with open(path, 'w') as f:
        f.write('\n'.join(rb) + '\n')


# ── IFC export ─────────────────────────────────────────────────────────────

def export_ifc(nodes, members, path, supports=None, profiles=None, results=None):
    """Export the structural model to IFC 2x3 STEP format for BIM interoperability.

    Written directly as STEP text — no external library needed. Maps:
    - Each member -> IfcMember with IfcCircleProfileDef cross-section
    - Spatial hierarchy: IfcProject > IfcSite > IfcBuilding > IfcBuildingStorey
    """
    import math
    import uuid
    import time

    def guid():
        return uuid.uuid4().hex[:22]

    def ts():
        return time.strftime('%Y-%m-%dT%H:%M:%S')

    eid = [0]
    def nid():
        eid[0] += 1
        return eid[0]

    def fv(v):
        return f'{v:.6E}'

    lines = []
    def add(text):
        i = nid()
        lines.append(f'#{i}={text};')
        return i

    timestamp = ts()

    person = add("IFCPERSON($,$,'User',$,$,$,$,$)")
    org = add("IFCORGANIZATION($,'Stereo App',$,$,$)")
    person_org = add(f"IFCPERSONANDORGANIZATION(#{person},#{org},$)")
    app = add("IFCAPPLICATION(#{org},'1.0','Stereo Structure Calculator','StereoApp')"
              .replace('#{org}', f'#{org}'))
    owner = add(f"IFCOWNERHISTORY(#{person_org},#{app},$,.NOCHANGE.,$,$,$,0)")

    dim_exp = add("IFCDIMENSIONALEXPONENTS(0,0,0,0,0,0,0)")
    si_m = add("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)")
    si_rad = add("IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.)")
    si_s = add("IFCSIUNIT(*,.SOLIDANGLEUNIT.,$,.STERADIAN.)")
    unit_assign = add(f"IFCUNITASSIGNMENT((#{si_m},#{si_rad},#{si_s}))")

    origin_3d = add(f"IFCCARTESIANPOINT(({fv(0.)},{fv(0.)},{fv(0.)}))")
    dir_z = add(f"IFCDIRECTION(({fv(0.)},{fv(0.)},{fv(1.)}))")
    dir_x = add(f"IFCDIRECTION(({fv(1.)},{fv(0.)},{fv(0.)}))")
    world_placement = add(f"IFCAXIS2PLACEMENT3D(#{origin_3d},#{dir_z},#{dir_x})")

    ctx = add(f"IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.0E-5,#{world_placement},$)")

    project = add(f"IFCPROJECT('{guid()}',#{owner},'Stereo Structure',$,$,$,$,"
                  f"(#{ctx}),#{unit_assign})")

    site_place = add(f"IFCLOCALPLACEMENT($,#{world_placement})")
    site = add(f"IFCSITE('{guid()}',#{owner},'Site',$,$,#{site_place},$,$,.ELEMENT.,$,$,$,$,$)")

    bldg_place = add(f"IFCLOCALPLACEMENT(#{site_place},#{world_placement})")
    building = add(f"IFCBUILDING('{guid()}',#{owner},'Building',$,$,#{bldg_place},$,$,.ELEMENT.,$,$,$)")

    storey_place = add(f"IFCLOCALPLACEMENT(#{bldg_place},#{world_placement})")
    storey = add(f"IFCBUILDINGSTOREY('{guid()}',#{owner},'Level 0',$,$,#{storey_place},$,$,.ELEMENT.,0.0)")

    add(f"IFCRELAGGREGATES('{guid()}',#{owner},$,$,#{project},(#{site}))")
    add(f"IFCRELAGGREGATES('{guid()}',#{owner},$,$,#{site},(#{building}))")
    add(f"IFCRELAGGREGATES('{guid()}',#{owner},$,$,#{building},(#{storey}))")

    member_ids = []
    for mi, m in enumerate(members):
        na, nb = nodes[m['a']], nodes[m['b']]
        dx, dy, dz = nb[0]-na[0], nb[1]-na[1], nb[2]-na[2]
        length = math.sqrt(dx*dx + dy*dy + dz*dz)
        if length < 1e-9:
            continue

        area_m2 = m.get('A', 10e-4)
        radius = math.sqrt(area_m2 / math.pi)

        dir_member = (dx/length, dy/length, dz/length)
        up = (0., 0., 1.)
        if abs(dir_member[2]) > 0.99:
            up = (1., 0., 0.)
        cx = (up[1]*dir_member[2]-up[2]*dir_member[1],
              up[2]*dir_member[0]-up[0]*dir_member[2],
              up[0]*dir_member[1]-up[1]*dir_member[0])
        cn = math.sqrt(sum(c*c for c in cx))
        if cn > 1e-9:
            cx = tuple(c/cn for c in cx)
        else:
            cx = (1., 0., 0.)

        pt = add(f"IFCCARTESIANPOINT(({fv(na[0])},{fv(na[1])},{fv(na[2])}))")
        ax = add(f"IFCDIRECTION(({fv(dir_member[0])},{fv(dir_member[1])},{fv(dir_member[2])}))")
        rx = add(f"IFCDIRECTION(({fv(cx[0])},{fv(cx[1])},{fv(cx[2])}))")
        place = add(f"IFCAXIS2PLACEMENT3D(#{pt},#{ax},#{rx})")
        local_place = add(f"IFCLOCALPLACEMENT(#{storey_place},#{place})")

        origin_2d = add(f"IFCCARTESIANPOINT(({fv(0.)},{fv(0.)}))")
        dir_2d = add(f"IFCDIRECTION(({fv(1.)},{fv(0.)}))")
        axis2d = add(f"IFCAXIS2PLACEMENT2D(#{origin_2d},#{dir_2d})")
        profile = add(f"IFCCIRCLEPROFILEDEF(.AREA.,$,#{axis2d},{fv(radius)})")

        extrude_dir = add(f"IFCDIRECTION(({fv(0.)},{fv(0.)},{fv(1.)}))")
        solid = add(f"IFCEXTRUDEDAREASOLID(#{profile},#{world_placement},#{extrude_dir},{fv(length)})")
        shape_rep = add(f"IFCSHAPEREPRESENTATION(#{ctx},'Body','SweptSolid',(#{solid}))")
        prod_shape = add(f"IFCPRODUCTDEFINITIONSHAPE($,$,(#{shape_rep}))")

        role = m.get('role', '')
        name = m.get('profile', f'M{mi}')
        mem = add(f"IFCMEMBER('{guid()}',#{owner},'{name}','{role}',$,#{local_place},#{prod_shape},$)")
        member_ids.append(mem)

    if member_ids:
        refs = ','.join(f'#{mid}' for mid in member_ids)
        add(f"IFCRELCONTAINEDINSPATIALSTRUCTURE('{guid()}',#{owner},$,$,({refs}),#{storey})")

    header = [
        'ISO-10303-21;',
        'HEADER;',
        f"FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');",
        f"FILE_NAME('{path}','{timestamp}',(''),(''),'','Stereo App','');",
        "FILE_SCHEMA(('IFC2X3'));",
        'ENDSEC;',
        'DATA;',
    ]
    footer = ['ENDSEC;', 'END-ISO-10303-21;']

    with open(path, 'w') as f:
        f.write('\n'.join(header) + '\n')
        f.write('\n'.join(lines) + '\n')
        f.write('\n'.join(footer) + '\n')


# ── PDF report ─────────────────────────────────────────────────────────────
#
# These sheets are handed to someone who reads DRAWINGS, so the furniture
# follows ordinary drafting practice rather than matplotlib's defaults:
#
#   * an ISO 5457-style frame with an ISO 7200-style title block in the
#     bottom-right corner, carrying the same data fields a title block is
#     required to carry (title, originator, date, sheet n of N, units,
#     code basis) -- previously there was no title block at all, so a
#     printed page could not be identified once it left the screen;
#   * a GRAPHIC scale bar, so a sheet that is printed, photocopied or
#     dropped into a slide at some other size still measures;
#   * an axonometric AXIS TRIAD, so "which way is this structure facing"
#     is answerable from the paper alone -- with each arm drawn as the
#     SAME world length, which makes the projection's own foreshortening
#     (different per axis, see _pdf_axis_dirs) directly visible rather
#     than something the reader has to know about;
#   * ONE compact colour key per view, built to mirror the tab's own
#     on-screen legend (_draw_legend in stereo_app_render.py) -- a caption,
#     a horizontal ramp sampled from the very same colour function the
#     drawing is painted with, proportional tick labels, then discrete
#     rows for everything else on the sheet. It replaces a full-page-height
#     matplotlib colorbar that dominated every view, AND the separate
#     hand-written patch legend that used to sit beside it quoting hexes
#     (#e6b800 for utilisation 0.5, #aaaaaa for "near zero") that the
#     colour functions never actually produce. Standard FEA-reporting
#     practice is that a figure legend must explain every symbol, line and
#     colour the figure uses and no others, which is exactly what the two
#     disagreeing legends failed at.
#
# Everything here is metric and in the app's own stored units: metres,
# kN, kN*m, mm.

PDF_SHEET_IN = (11.69, 8.27)        # A4 landscape (ISO 5457 / ISO 216)
PDF_FRAME = (0.026, 0.030, 0.974, 0.970)    # x0, y0, x1, y1, figure fraction
PDF_TITLE_H = 0.128                 # title-block height, figure fraction
PDF_TITLE_W = 0.560                 # title-block width, figure fraction
PDF_TITLE_W_WIDE = 0.720            # ...and when a GROUP field is present too
PDF_TITLE_FIELD_GUTTER = 2.2        # blank characters between field columns
PDF_APP_NAME = 'Stereo Structure Calculator'
PDF_CODE_BASIS = 'CIRSOC 301 / AISC 360'

PDF_KEY_X = 0.010                   # key origin, axes fraction
PDF_KEY_Y = 0.988
PDF_KEY_W = 0.200                   # ramp width, axes fraction
PDF_KEY_H = 0.020                   # ramp height, axes fraction
PDF_KEY_ROW = 0.030                 # line pitch, axes fraction
PDF_KEY_SEGMENTS = 48               # ramp resolution; matches the canvas legend
PDF_KEY_FS = 7.0                    # key font size, points

PDF_STATS_X = 0.990                 # stats panel origin (right edge), axes fraction
PDF_STATS_Y = 0.988

PDF_SCALE_DIVISIONS = 4             # chequers in the graphic scale bar
PDF_SCALE_TARGET = 0.38             # bar aims at this fraction of the drawing
                                    # (before rounding DOWN to 1-2-5, which
                                    # on a 16 m model turned 0.30 into a
                                    # stubby 2 m bar rather than a 5 m one)
PDF_MONO = 'DejaVu Sans Mono'

PDF_INK = '#333333'
PDF_RULE = '#9aa0a6'
PDF_PANEL_FACE = '#ffffff'
PDF_PANEL_EDGE = '#c8ccd0'
PDF_PANEL_ALPHA = 0.94              # opaque enough that the drawing behind
                                    # a corner panel does not ghost through
PDF_UNDEFORMED = '#c2c8cd'          # the "where it started" ghost wireframe


def _hex_to_rgb(h):
    return (int(h[1:3], 16) / 255, int(h[3:5], 16) / 255, int(h[5:7], 16) / 255)


def _pdf_project(px, py, pz, az_rad, el_rad):
    """_iso_project's parallel projection with the vertical axis flipped.

    _iso_project returns TK CANVAS coordinates, where y grows DOWNWARD --
    correct for the on-screen view, and what its own test pins ("Z must
    project upward, i.e. NEGATIVE screen-y"). Matplotlib's y grows upward,
    so handing it _iso_project's output directly drew every sheet
    vertically MIRRORED against the tab it is a report of: a roof sagging
    under its own weight bulged upward on the deformed-shape sheet, and
    the orientation triad's +Z arrow pointed at the floor.

    One flip here, applied to the nodes, the deformed nodes, the load
    arrows and the axis triad alike, is what keeps the printed sheet and
    the canvas showing the same structure the same way up.
    """
    sx, sy = _iso_project(px, py, pz, az_rad, el_rad)
    return sx, -sy


def _pdf_nice_length(raw):
    """`raw` rounded DOWN to the nearest 1, 2 or 5 times a power of ten.

    The classic graphic-scale-bar rounding: a bar has to be a length a
    reader can divide in their head (5 m, 20 m, 0.5 m), never "13.7 m".
    Returns 0.0 for a non-positive or non-finite input so a degenerate
    model simply gets no scale bar instead of raising.
    """
    import math
    if not (raw > 0.0) or not math.isfinite(raw):
        return 0.0
    exp = math.floor(math.log10(raw))
    base = 10.0 ** exp
    for mult in (5.0, 2.0, 1.0):
        if raw >= mult * base - 1e-12:
            return mult * base
    return base


def _pdf_view_depth(vx, vy, vz, az_rad, el_rad):
    """How far a world direction points AWAY from the reader.

    Positive = into the sheet, negative = out of it, ~0 = lying in the
    sheet plane. Same quantity StereoViewMixin._project returns as its
    third value, and what decides whether a vanishing axis is drawn as the
    draughtsman's circled dot (coming at you) or circled cross (going
    away) on an orthographic sheet.
    """
    import math
    sa, ca = math.sin(az_rad), math.cos(az_rad)
    se, ce = math.sin(el_rad), math.cos(el_rad)
    yr = vx * sa + vy * ca
    return yr * ce - vz * se


# The five orthographic views, each as the azimuth/elevation that produces
# it. Derived, not guessed: for a camera looking along `d` with `up`, the
# sheet's horizontal axis is cross(d, up), and _iso_project's own algebra
# then pins the azimuth. Checked by test_stereo_reports.py against both
# the resulting projection AND the sign of _pdf_view_depth.
#
#   plan   viewer above,  looking down  -Z : X right, Y up,  Z at the reader
#   front  viewer at -Y,  looking along +Y : X right, Z up,  Y away
#   back   viewer at +Y,  looking along -Y : X left,  Z up,  Y at the reader
#   right  viewer at +X,  looking along -X : Y right, Z up,  X at the reader
#   left   viewer at -X,  looking along +X : Y left,  Z up,  X away
PDF_ORTHO_VIEWS = (
    ('plan', {
        'az': 0.0, 'el': 90.0,
        'title': 'Plan — view from above',
        'caption': 'PLAN  ·  looking down (−Z)',
        'h': 'X', 'v': 'Y', 'normal': 'Z', 'kind': 'plan'}),
    ('front', {
        'az': 0.0, 'el': 0.0,
        'title': 'Front elevation',
        'caption': 'FRONT ELEVATION  ·  looking along +Y',
        'h': 'X', 'v': 'Z', 'normal': 'Y', 'kind': 'elevation'}),
    ('back', {
        'az': 180.0, 'el': 0.0,
        'title': 'Back elevation',
        'caption': 'BACK ELEVATION  ·  looking along −Y',
        'h': 'X', 'v': 'Z', 'normal': 'Y', 'kind': 'elevation'}),
    ('right', {
        'az': -90.0, 'el': 0.0,
        'title': 'Right side elevation',
        'caption': 'RIGHT ELEVATION  ·  looking along −X',
        'h': 'Y', 'v': 'Z', 'normal': 'X', 'kind': 'elevation'}),
    ('left', {
        'az': 90.0, 'el': 0.0,
        'title': 'Left side elevation',
        'caption': 'LEFT ELEVATION  ·  looking along +X',
        'h': 'Y', 'v': 'Z', 'normal': 'X', 'kind': 'elevation'}),
)

PDF_AXIS_UNIT = {'X': (1.0, 0.0, 0.0), 'Y': (0.0, 1.0, 0.0),
                 'Z': (0.0, 0.0, 1.0)}

PDF_GHOST_LINE = '#e3e6ea'      # the dimension grid: present, not competing
PDF_GHOST_TEXT = '#9aa2ab'
PDF_LEVEL_LINE = '#c9d2db'      # a named structural level, a shade stronger
PDF_MAX_LEVELS = 14             # past this a level line per storey is noise


def _pdf_ortho_frame(az_rad, el_rad, h_axis, v_axis):
    """(h_sign, v_sign) mapping sheet coordinates back to world ones.

    On an orthographic sheet each drawn axis IS a world axis, up to a
    sign: data_x = h_sign * world_h, data_y = v_sign * world_v. The ghost
    grid labels world coordinates, so it needs that sign rather than
    assuming the view happens to be the un-mirrored one.
    """
    hx, _ = _pdf_project(*PDF_AXIS_UNIT[h_axis], az_rad, el_rad)
    _, vy = _pdf_project(*PDF_AXIS_UNIT[v_axis], az_rad, el_rad)
    return (1.0 if hx >= 0 else -1.0), (1.0 if vy >= 0 else -1.0)


def _pdf_axis_dirs(az_rad, el_rad):
    """Where one world metre along each axis lands on the sheet.

    Returns {'X': (dx, dy), 'Y': (...), 'Z': (...)} in projected units.
    A parallel projection foreshortens each axis by a DIFFERENT factor
    (|dir| below), which is why the triad draws all three arms at one
    shared world length and why the scale bar is tied to a named axis
    rather than pretending one bar measures every direction.
    """
    out = {}
    for name, v in (('X', (1.0, 0.0, 0.0)),
                    ('Y', (0.0, 1.0, 0.0)),
                    ('Z', (0.0, 0.0, 1.0))):
        out[name] = _pdf_project(v[0], v[1], v[2], az_rad, el_rad)
    return out


def _pdf_foreshortening(az_rad, el_rad):
    """{'X': f, 'Y': f, 'Z': f}: projected length of one world metre."""
    import math
    return {k: math.hypot(*d)
            for k, d in _pdf_axis_dirs(az_rad, el_rad).items()}


def _pdf_model_extents(nodes):
    """(dx, dy, dz) bounding-box size of the model, in metres."""
    if not nodes:
        return (0.0, 0.0, 0.0)
    xs = [n[0] for n in nodes]
    ys = [n[1] for n in nodes]
    zs = [n[2] for n in nodes]
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


# ── sheet furniture ───────────────────────────────────────────────────────

def _pdf_sheet(fig, sheet_no, sheet_total, title, meta):
    """The frame and the ISO 7200-style title block, on every sheet.

    `meta` is an ordered list of (caption, value) pairs; they are laid out
    across the block's lower band, which is what a title block is for --
    the fields that identify the sheet once it is off the screen.
    """
    from matplotlib.patches import Rectangle

    x0, y0, x1, y1 = PDF_FRAME
    fig.add_artist(Rectangle((x0, y0), x1 - x0, y1 - y0, transform=fig.transFigure,
                             facecolor='none', edgecolor=PDF_RULE, linewidth=0.9,
                             zorder=5))

    # A selection's block carries a GROUP field on top of the usual five,
    # and six columns in the narrow block ran every value into the next.
    tb_w = PDF_TITLE_W_WIDE if len(meta or ()) > 5 else PDF_TITLE_W
    tb_x = x1 - tb_w
    tb_y = y0
    fig.add_artist(Rectangle((tb_x, tb_y), tb_w, PDF_TITLE_H,
                             transform=fig.transFigure, facecolor='#fbfbfc',
                             edgecolor=PDF_RULE, linewidth=0.9, zorder=6))

    band = tb_y + PDF_TITLE_H * 0.46
    fig.add_artist(Rectangle((tb_x, band), tb_w, 0.0,
                             transform=fig.transFigure, facecolor='none',
                             edgecolor=PDF_RULE, linewidth=0.7, zorder=7))

    pad = 0.010
    fig.text(tb_x + pad, tb_y + PDF_TITLE_H * 0.74, title,
             fontsize=11 if tb_w <= PDF_TITLE_W else 12,
             fontweight='bold', color='#1a1a1a', va='center', ha='left',
             zorder=8)
    fig.text(x1 - pad, tb_y + PDF_TITLE_H * 0.74,
             f'Sheet {sheet_no} / {sheet_total}', fontsize=9,
             color=PDF_INK, va='center', ha='right', zorder=8)

    # The identifying fields, each in a column WIDE ENOUGH FOR ITS VALUE --
    # equal columns ran 'CIRSOC 301 / AISC 360' straight into the date
    # beside it.
    if meta:
        # Each column is as wide as its own longest line PLUS a gutter, so
        # neighbouring values cannot touch however long one of them is.
        weights = [max(len(str(v)), len(str(c)) + 2) + PDF_TITLE_FIELD_GUTTER
                   for c, v in meta]
        total_w = float(sum(weights)) or 1.0
        avail = tb_w - 2 * pad
        fs = 6.6 if len(meta) <= 5 else 6.0
        acc = 0.0
        for (cap, val), wt in zip(meta, weights):
            fx = tb_x + pad + (acc / total_w) * avail
            acc += wt
            fig.text(fx, tb_y + PDF_TITLE_H * 0.30, cap, fontsize=5.6,
                     color='#7a8087', va='center', ha='left', zorder=8)
            fig.text(fx, tb_y + PDF_TITLE_H * 0.12, val, fontsize=fs,
                     color=PDF_INK, va='center', ha='left', zorder=8,
                     fontfamily=PDF_MONO)


def _pdf_sheet_meta(nodes, members, meta=None, u=None):
    """The title-block fields shared by every sheet of one report.

    When the report covers a SELECTION, the block carries two names, not
    one: the file the group came out of and the group itself. A sheet
    showing part of a structure that names only the part is not traceable
    back to anything.
    """
    import time
    u = u or ReportUnits()
    family = ''
    group = ''
    parent = ''
    if meta:
        family = meta.get('grid_family') or meta.get('typology') or ''
        group = meta.get('group') or ''
        parent = meta.get('subset_of') or ''
    fields = []
    if group:
        fields.append(('GROUP', str(group)[:20]))
        fields.append(('FILE', str(parent or family)[:20] or 'user model'))
    else:
        fields.append(('MODEL', (str(family)[:22] or 'user model')))
    fields += [
        ('SIZE', f'{len(nodes)} nodes / {len(members)} bars'),
        ('UNITS', u.title_block()),
        ('CODE', PDF_CODE_BASIS),
        ('DATE', time.strftime('%Y-%m-%d %H:%M')),
    ]
    return fields


class _PdfKey:
    """The compact colour key, drawn in one view's axes-fraction space.

    Deliberately the same idiom as the tab's own on-screen legend: a bold
    caption, then either a horizontal ramp with proportional tick labels or
    a short line swatch with a sentence beside it. The ramp SAMPLES the
    colour function the drawing itself was painted with, so the key cannot
    drift away from the picture the way a separately hand-picked list of
    hexes did.

    Every entry added here is background-panelled at finish() time, sized
    to whatever was actually written, so the key never leaves a fixed
    white rectangle floating over an empty corner.
    """

    def __init__(self, ax, x=PDF_KEY_X, y=PDF_KEY_Y):
        self.ax = ax
        self.x0 = x
        self.y = y
        self._width = PDF_KEY_W
        self._any = False

    def _t(self):
        return self.ax.transAxes

    # Rough advance width of one glyph, as a fraction of the axes width, at
    # PDF_KEY_FS on an A4-landscape sheet. Only the backing panel is sized
    # from it, so an approximation is enough -- but it has to be close, or
    # the panel either clips the text or floats a white slab across the
    # drawing.
    _CHAR_W = 0.0058

    def caption(self, text):
        self.y -= PDF_KEY_ROW * 0.95
        self.ax.text(self.x0, self.y, text, transform=self._t(),
                     fontsize=PDF_KEY_FS, fontweight='bold', color='#222222',
                     va='center', ha='left', zorder=20, clip_on=False)
        self._width = max(self._width, self._CHAR_W * 1.06 * len(text))
        self._any = True

    def note(self, text):
        self.y -= PDF_KEY_ROW * 0.82
        self.ax.text(self.x0, self.y, text, transform=self._t(),
                     fontsize=PDF_KEY_FS - 0.5, color='#5f6368', va='center',
                     ha='left', zorder=20, clip_on=False, style='italic')
        self._width = max(self._width, self._CHAR_W * 0.90 * len(text))
        self._any = True

    def ramp(self, color_fn, lo, hi, ticks, segments=PDF_KEY_SEGMENTS,
             mark=None):
        """A continuous gradient strip from `lo` to `hi`.

        `ticks` are (value, label) pairs placed at their PROPORTIONAL
        position along the bar rather than assumed to sit at its ends --
        utilisation's 0.5 tick, for one, is not the midpoint of its domain.

        `mark` is an optional (value, label) threshold drawn as a rule
        ACROSS the bar instead of a label under it, for a value that
        matters but sits too close to an end for its own tick (capacity at
        1.0 on a bar that runs to 1.2).
        """
        from matplotlib.patches import Rectangle
        # clear of the caption above -- and of the threshold label, when one
        # is printed over the bar
        self.y -= PDF_KEY_H + PDF_KEY_ROW * (1.35 if mark is not None else 0.75)
        span = (hi - lo) or 1.0
        for i in range(segments):
            frac = i / (segments - 1) if segments > 1 else 0.0
            col = _hex_to_rgb(color_fn(lo + frac * span))
            sx = self.x0 + (i / segments) * PDF_KEY_W
            w = PDF_KEY_W / segments * 1.02      # 2% overlap: no hairline seams
            self.ax.add_patch(Rectangle((sx, self.y), w, PDF_KEY_H,
                                        transform=self._t(), facecolor=col,
                                        edgecolor='none', zorder=20,
                                        clip_on=False))
        self.ax.add_patch(Rectangle((self.x0, self.y), PDF_KEY_W, PDF_KEY_H,
                                    transform=self._t(), facecolor='none',
                                    edgecolor='#888888', linewidth=0.6,
                                    zorder=21, clip_on=False))
        if mark is not None:
            mval, mlabel = mark
            mf = min(1.0, max(0.0, (mval - lo) / span))
            mx = self.x0 + mf * PDF_KEY_W
            self.ax.plot([mx, mx], [self.y, self.y + PDF_KEY_H],
                         transform=self._t(), color='#1a1a1a', linewidth=1.0,
                         zorder=22, clip_on=False)
            self.ax.text(mx, self.y + PDF_KEY_H * 1.35, mlabel,
                         transform=self._t(), fontsize=PDF_KEY_FS - 1.0,
                         color='#1a1a1a', va='bottom', ha='center', zorder=22,
                         clip_on=False)
        ty = self.y - PDF_KEY_ROW * 0.55
        for value, label in ticks:
            fp = (value - lo) / span
            fp = min(1.0, max(0.0, fp))
            ha = 'left' if fp <= 0.02 else ('right' if fp >= 0.98 else 'center')
            self.ax.text(self.x0 + fp * PDF_KEY_W, ty, label,
                         transform=self._t(), fontsize=PDF_KEY_FS - 0.5,
                         color='#444444', va='center', ha=ha, zorder=20,
                         clip_on=False)
        self.y = ty - PDF_KEY_ROW * 0.30
        self._any = True

    def row(self, color, label, dashed=False, marker=None, outline=None,
            linewidth=2.2):
        """One discrete entry: a swatch of the real colour, then its meaning."""
        self.y -= PDF_KEY_ROW
        sx0, sx1 = self.x0, self.x0 + 0.028
        if outline:
            self.ax.plot([sx0, sx1], [self.y, self.y], transform=self._t(),
                         color=_hex_to_rgb(outline), linewidth=linewidth + 1.8,
                         solid_capstyle='butt', zorder=20, clip_on=False)
        if marker:
            self.ax.plot([(sx0 + sx1) / 2], [self.y], transform=self._t(),
                         marker=marker, color=_hex_to_rgb(color),
                         markersize=4.5, linestyle='none', zorder=21,
                         clip_on=False)
        else:
            kw = {'linestyle': (0, (3.5, 2.2))} if dashed else {}
            self.ax.plot([sx0, sx1], [self.y, self.y], transform=self._t(),
                         color=_hex_to_rgb(color), linewidth=linewidth,
                         solid_capstyle='butt', zorder=21, clip_on=False, **kw)
        self.ax.text(sx1 + 0.010, self.y, label, transform=self._t(),
                     fontsize=PDF_KEY_FS, color='#444444', va='center',
                     ha='left', zorder=20, clip_on=False)
        self._width = max(self._width, 0.038 + self._CHAR_W * len(label))
        self._any = True

    def height(self):
        """How much of the axes this key has claimed, as a fraction.

        The caller hands it to _pdf_fit_window so the drawing is fitted
        BELOW the key instead of behind it.
        """
        return (PDF_KEY_Y - self.y) + 0.030 if self._any else 0.0

    def finish(self):
        """The backing panel, sized to what was actually written."""
        from matplotlib.patches import FancyBboxPatch
        if not self._any:
            return
        pad = 0.012
        w = min(self._width + 2 * pad, 0.62)
        h = (PDF_KEY_Y - self.y) + 2 * pad
        self.ax.add_patch(FancyBboxPatch(
            (self.x0 - pad, self.y - pad), w, h,
            boxstyle='round,pad=0.004,rounding_size=0.006',
            transform=self._t(), facecolor=PDF_PANEL_FACE,
            alpha=PDF_PANEL_ALPHA, edgecolor=PDF_PANEL_EDGE, linewidth=0.6,
            zorder=19, clip_on=False, mutation_aspect=1.0))


def _pdf_stats_height(ax, lines):
    """The axes fraction a stats panel of these lines will occupy."""
    if not lines:
        return 0.0
    return _pdf_text_block_height(ax, len(lines)) + (1.0 - PDF_STATS_Y) + 0.012


def _pdf_stats_panel(ax, lines, x=PDF_STATS_X, y=PDF_STATS_Y):
    """The per-view numbers, top-right, opposite the colour key.

    Every analysis sheet carries one: a view that only shows WHERE the
    extreme is, without saying what it is, which member carries it and how
    the rest of the structure is distributed around it, is half a report.
    """
    if not lines:
        return
    # ha='right' anchors the BLOCK to the sheet's right edge;
    # multialignment='left' keeps the lines inside it flush left, so
    # "label   value" pairs still line up and a sentence still reads as a
    # sentence (right-ragged prose is what the first draft produced).
    ax.text(x, y, '\n'.join(lines), transform=ax.transAxes,
            fontsize=PDF_KEY_FS, color='#333333', va='top', ha='right',
            multialignment='left', family=PDF_MONO, zorder=20, clip_on=False,
            bbox=dict(boxstyle='round,pad=0.45', facecolor=PDF_PANEL_FACE,
                      alpha=PDF_PANEL_ALPHA, edgecolor=PDF_PANEL_EDGE,
                      linewidth=0.6))


def _pdf_scale_bar(ax, model_span_m, xy, unit_len_data=1.0, ref_axis='X',
                   exact=True, divisions=PDF_SCALE_DIVISIONS, u=None):
    """A HORIZONTAL chequered graphic scale bar.

    Horizontal in every view, which is how a scale bar is read. On an
    orthographic sheet that costs nothing: the sheet's own horizontal axis
    IS a world axis, so the bar is exactly true and `exact` says so. On the
    axonometric sheet nothing is horizontal in world terms, so the bar is
    drawn at the length ONE metre of `ref_axis` projects to and labelled
    with that axis -- true for everything parallel to it, and the key
    carries the other two foreshortening factors.

    `unit_len_data` is how long one metre of `ref_axis` is in the axes'
    own data units. Returns the round length chosen, in metres (0.0 when
    the model is degenerate and no honest bar can be drawn).
    """
    from matplotlib.patches import Rectangle
    u = u or ReportUnits()

    # The round number is chosen in the unit the bar will be LABELLED in,
    # then converted back to draw it: a bar that is a round 5 m is 16.4 ft,
    # which is not a scale bar.
    shown = _pdf_nice_length(u.v('length', model_span_m) * PDF_SCALE_TARGET)
    length_m = u.to_storage('length', shown) if shown > 0 else 0.0
    if length_m <= 0.0 or unit_len_data <= 0.0:
        return 0.0

    drawn = length_m * unit_len_data
    thick = model_span_m * 0.011
    bx, by = xy
    seg = drawn / divisions
    for i in range(divisions):
        ax.add_patch(Rectangle((bx + seg * i, by), seg, thick,
                               facecolor=('#333333' if i % 2 == 0 else '#ffffff'),
                               edgecolor='#333333', linewidth=0.6, zorder=15))
    ax.text(bx, by - thick * 0.45, '0', fontsize=PDF_KEY_FS - 0.5,
            color=PDF_INK, ha='center', va='top', zorder=16)
    ax.text(bx + drawn, by - thick * 0.45, f'{shown:g}',
            fontsize=PDF_KEY_FS - 0.5, color=PDF_INK, ha='center', va='top',
            zorder=16)
    note = 'true to scale' if exact else f'along {ref_axis} (foreshortened)'
    ax.text(bx + drawn / 2.0, by + thick * 1.5,
            f'{shown:g} {u.lab("length")} · {note}',
            fontsize=PDF_KEY_FS, color=PDF_INK, ha='center', va='bottom',
            zorder=16)
    return length_m


def _pdf_orientation_triad(ax, az_rad, el_rad, arm_m, xy, caption_y=None,
                           u=None):
    """The X/Y/Z triad, every arm the same world length.

    This is what lets a reader orient the structure in 3D space from the
    printed sheet alone, which none of these views previously allowed. All
    three arms carry ONE shared world length, so the projection's own
    per-axis foreshortening is visible directly in the drawing: on a
    typical az 35 / el 22 view the Z arm reads noticeably longer than the
    Y arm, and that is the truth about the view, not a drawing error.
    """
    import math
    from apps.stereo.stereo_app_constants import (
        AXIS_COLOR_X, AXIS_COLOR_Y, AXIS_COLOR_Z,
    )
    from matplotlib.patches import Circle
    dirs = _pdf_axis_dirs(az_rad, el_rad)
    cols = {'X': AXIS_COLOR_X, 'Y': AXIS_COLOR_Y, 'Z': AXIS_COLOR_Z}
    ox, oy = xy
    flat = []
    for name in ('X', 'Y', 'Z'):
        dx, dy = dirs[name]
        if math.hypot(dx, dy) < 1e-6:
            # An axis pointing straight at (or straight away from) the
            # reader projects to nothing, which is exactly the case on
            # every orthographic sheet. Drawing a zero-length arrow there
            # would read as a bug; the draughtsman's circled dot (coming
            # at you) and circled cross (going away) say it properly.
            flat.append(name)
            continue
        ex, ey = ox + dx * arm_m, oy + dy * arm_m
        ax.annotate('', xy=(ex, ey), xytext=(ox, oy),
                    arrowprops=dict(arrowstyle='-|>', color=cols[name],
                                    linewidth=1.3, shrinkA=0, shrinkB=0,
                                    mutation_scale=9),
                    zorder=16, annotation_clip=False)
        lx, ly = ox + dx * arm_m * 1.26, oy + dy * arm_m * 1.26
        label = name + (' (N)' if name == 'Y' else '')
        ax.text(lx, ly, label, fontsize=PDF_KEY_FS + 0.6, fontweight='bold',
                color=cols[name], ha='center', va='center', zorder=17)

    notes = []
    for i, name in enumerate(flat):
        col = cols[name]
        r = arm_m * 0.16
        # Down-left of the origin, never ON it: the two axes that DO
        # project leave the origin pointing right and up in every
        # orthographic view, so the symbol drawn at the origin had an
        # arrow running straight through it.
        cx = ox - arm_m * 0.62 - (i * r * 3.2)
        cy = oy
        ax.add_patch(Circle((cx, cy), r, facecolor='white', edgecolor=col,
                            linewidth=1.2, zorder=17))
        away = _pdf_view_depth(*PDF_AXIS_UNIT[name], az_rad, el_rad) > 0
        if away:
            k = r * 0.66
            ax.plot([cx - k, cx + k], [cy - k, cy + k], color=col,
                    linewidth=1.0, zorder=18)
            ax.plot([cx - k, cx + k], [cy + k, cy - k], color=col,
                    linewidth=1.0, zorder=18)
            notes.append(f'{name} away from you')
        else:
            ax.plot([cx], [cy], marker='o', markersize=2.6, color=col,
                    linestyle='none', zorder=18)
            notes.append(f'{name} toward you')
        ax.text(cx, cy + r * 1.9, name, fontsize=PDF_KEY_FS + 0.6,
                fontweight='bold', color=col, ha='center', va='bottom',
                zorder=18)
    if not flat:
        ax.plot([ox], [oy], marker='o', markersize=2.0, color='#444444',
                linestyle='none', zorder=17)

    # On a fixed line of the furniture band, not derived from the arm
    # geometry: deriving it put the caption through the middle of the
    # flat-axis symbol on every elevation.
    u = u or ReportUnits()
    head = (f'arms = {u.v("length", arm_m):g} {u.lab("length")} (all three)'
            if not flat
            else ' · '.join(notes))
    cap_y = caption_y if caption_y is not None else oy - arm_m * 0.9
    ax.text(ox - arm_m * 0.3, cap_y,
            head + '\n'
            f'az {math.degrees(az_rad):.0f}° · el {math.degrees(el_rad):.0f}° '
            f'· parallel projection',
            fontsize=PDF_KEY_FS - 1.0, color='#5f6368', ha='center', va='top',
            linespacing=1.5, zorder=17)


# Bottom of the sheet held clear for the grid ruler, the view caption, the
# scale bar and the orientation indicator -- four things that all used to
# be crowded into the same strip and landed on top of one another.
PDF_FURNITURE_BAND = 0.26
# The axonometric sheets carry no grid ruler and no view caption, so they
# need only the two rows the band always has and should not give up the
# drawing area the orthographic ones do.
PDF_FURNITURE_BAND_ISO = 0.20
PDF_BAND_RULER = 0.005         # grid ruler numbers, at the floor
PDF_BAND_CAPTION = 0.042       # the view's name, centred
PDF_BAND_TRIAD_TEXT = 0.072    # what the orientation indicator says, right
PDF_BAND_SCALE = 0.105         # scale bar, left
PDF_BAND_TRIAD = 0.135         # orientation indicator's origin, right
# Longest triad arm that still fits inside the band, as a fraction of the
# window height. Without this the arm was sized from the MODEL and its +Z
# tip reached up out of the band and into the drawing.
PDF_TRIAD_ARM_MAX = 0.075


def _pdf_ghost_grid(ax, win, nodes, az_rad, el_rad, view, u=None):
    """The almost-invisible dimension grid behind an orthographic view.

    Two things a bare wireframe cannot tell you: HOW BIG it is and WHERE
    the parts sit. The grid answers both by labelling real world
    coordinates along the bottom and left edges at a round spacing, and on
    an elevation it also draws a line at every distinct structural Z with
    its value -- the levels a structural elevation is read by.

    Drawn at PDF_GHOST_LINE, light enough that the structure stays the
    subject; that is what "ghost" means here.

    Returns (spacing_m, n_levels) so the caller can say so in its panel.
    """
    u = u or ReportUnits()
    x0, y0, x1, y1 = win
    h_axis, v_axis = view['h'], view['v']
    h_sign, v_sign = _pdf_ortho_frame(az_rad, el_rad, h_axis, v_axis)

    # Round in the unit the ruler is labelled in, then back -- see
    # _pdf_scale_bar for why a grid at a round 2 m is not a grid at all
    # once its numbers are written in feet.
    step_shown = _pdf_nice_length(u.v('length', max(x1 - x0, y1 - y0) * 0.12))
    spacing = u.to_storage('length', step_shown) if step_shown > 0 else 0.0
    if spacing <= 0.0:
        return 0.0, 0

    def world_range(lo, hi, sign):
        a, b = lo * sign, hi * sign
        return (a, b) if a <= b else (b, a)

    import math
    wh0, wh1 = world_range(x0, x1, h_sign)
    wv0, wv1 = world_range(y0, y1, v_sign)

    for k in range(int(math.floor(wh0 / spacing)),
                   int(math.ceil(wh1 / spacing)) + 1):
        wh = k * spacing
        dxp = wh * h_sign
        if not (x0 <= dxp <= x1):
            continue
        ax.plot([dxp, dxp], [y0, y1], color=PDF_GHOST_LINE, linewidth=0.5,
                zorder=0)
        ax.text(dxp, y0 + (y1 - y0) * PDF_BAND_RULER,
                f'{u.v("length", wh):g}',
                fontsize=PDF_KEY_FS - 1.4, color=PDF_GHOST_TEXT, ha='center',
                va='bottom', zorder=1)

    for k in range(int(math.floor(wv0 / spacing)),
                   int(math.ceil(wv1 / spacing)) + 1):
        wv = k * spacing
        dyp = wv * v_sign
        if not (y0 <= dyp <= y1):
            continue
        ax.plot([x0, x1], [dyp, dyp], color=PDF_GHOST_LINE, linewidth=0.5,
                zorder=0)
        ax.text(x0 + (x1 - x0) * 0.006, dyp, f'{u.v("length", wv):g}',
                fontsize=PDF_KEY_FS - 1.4, color=PDF_GHOST_TEXT, ha='left',
                va='bottom', zorder=1)

    # The axis NAMES sit a line above the ruler numbers, not among them.
    ax.text(x1 - (x1 - x0) * 0.004, y0 + (y1 - y0) * (PDF_BAND_RULER + 0.026),
            f'{h_axis} ({u.lab("length")}) \u2192', fontsize=PDF_KEY_FS - 1.0,
            color=PDF_GHOST_TEXT, ha='right', va='bottom', zorder=1)
    ax.text(x0 + (x1 - x0) * 0.006, y1 - (y1 - y0) * 0.008,
            f'\u2191 {v_axis} ({u.lab("length")})', fontsize=PDF_KEY_FS - 1.0,
            color=PDF_GHOST_TEXT, ha='left', va='top', zorder=1)

    # Named levels: the structure's own distinct heights, which is what an
    # elevation drawing exists to let you read off.
    n_levels = 0
    if view.get('kind') == 'elevation' and nodes:
        levels = sorted({round(n[2], 4) for n in nodes})
        if len(levels) <= PDF_MAX_LEVELS:
            for z in levels:
                dyp = z * v_sign
                if not (y0 <= dyp <= y1):
                    continue
                ax.plot([x0, x1], [dyp, dyp], color=PDF_LEVEL_LINE,
                        linewidth=0.7, linestyle=(0, (6, 3)), zorder=1)
                ax.text(x1 - (x1 - x0) * 0.004, dyp,
                        f'  {u.f("length", z, 2, sign=True)} ',
                        fontsize=PDF_KEY_FS - 0.8, color='#6b7680',
                        ha='right', va='bottom', zorder=2)
                n_levels += 1
    return spacing, n_levels


def _pdf_furnish(ax, nodes, proj_2d, az_rad, el_rad, extra_pts=(),
                 reserve_top=0.0, view=None, u=None):
    """Fit the view, then hang the grid, the scale bar and the triad on it.

    `reserve_top` is how much of the axes the colour key and the stats
    panel have already claimed, so the drawing can be fitted UNDER them
    rather than behind them. `view` is one of PDF_ORTHO_VIEWS' specs when
    this is an orthographic sheet, and None for the axonometric one.

    Returns (window, scale_len_m, arm_m, grid) where grid is
    (spacing_m, n_levels) or (0.0, 0).
    """
    u = u or ReportUnits()
    band = PDF_FURNITURE_BAND if view is not None else PDF_FURNITURE_BAND_ISO
    win = _pdf_fit_window(ax, list(proj_2d) + list(extra_pts),
                          reserve_top=reserve_top, reserve_bottom=band)
    x0, y0, x1, y1 = win
    w, h = x1 - x0, y1 - y0
    dx, dy, dz = _pdf_model_extents(nodes)
    span = max(dx, dy, dz, 1e-6)

    grid = (0.0, 0)
    if view is not None:
        grid = _pdf_ghost_grid(ax, win, nodes, az_rad, el_rad, view, u=u)

    # On an orthographic sheet the drawn horizontal axis IS a world axis,
    # so one metre of it is one data unit and the bar is exactly true. On
    # the axonometric sheet it is X, foreshortened, and the label says so.
    import math
    ref = view['h'] if view is not None else 'X'
    unit = math.hypot(*_pdf_project(*PDF_AXIS_UNIT[ref], az_rad, el_rad))
    bar_xy = (x0 + w * 0.045, y0 + h * PDF_BAND_SCALE)
    scale_len = _pdf_scale_bar(ax, span, bar_xy, unit_len_data=unit,
                               ref_axis=ref, exact=view is not None, u=u)

    want = min(span * 0.16, h * PDF_TRIAD_ARM_MAX)
    arm_shown = _pdf_nice_length(u.v('length', want))
    arm = (u.to_storage('length', arm_shown) if arm_shown > 0
           else max(want, 1e-3))
    triad_xy = (x1 - w * 0.12, y0 + h * PDF_BAND_TRIAD)
    _pdf_orientation_triad(ax, az_rad, el_rad, arm, triad_xy,
                           caption_y=y0 + h * PDF_BAND_TRIAD_TEXT, u=u)

    if view is not None:
        ax.text((x0 + x1) / 2.0, y0 + h * PDF_BAND_CAPTION, view['caption'],
                fontsize=PDF_KEY_FS + 2.0, fontweight='bold', color='#2b3138',
                ha='center', va='bottom', zorder=18)
    return win, scale_len, arm, grid


def _pdf_finish_view(ax, nodes, proj_2d, az_rad, el_rad, key, stats,
                     extra_pts=(), view=None, u=None):
    """Close one view sheet.

    The order matters and is the whole point: the key and the stats panel
    are measured FIRST, the drawing is then fitted into what is left, and
    only then are the scale bar and the triad placed from the final
    window. Fitting the drawing first, as the first draft did, put the
    panels on top of the structure on any model tall enough to reach them.
    """
    reserve = max(key.height(), _pdf_stats_height(ax, stats))
    key.finish()
    _pdf_stats_panel(ax, stats)
    return _pdf_furnish(ax, nodes, proj_2d, az_rad, el_rad,
                        extra_pts=extra_pts, reserve_top=reserve, view=view,
                        u=u)


def _pdf_stress_widths(members, member_res, lo=None, hi=None):
    """Line width per bar from its axial stress |N|/A, against the model's
    own peak -- the same rule the canvas uses for its Thickness-by-stress
    toggle, so a sheet and the screen weight the same bar the same way.

    Stress rather than force: a thick chord and a thin web carrying the
    same kN are not working equally hard, and thickness is meant to read
    as "how hard is this member working".
    """
    from apps.stereo.stereo_app_constants import (
        STRESS_WIDTH_MIN, STRESS_WIDTH_MAX,
    )
    lo = STRESS_WIDTH_MIN if lo is None else lo
    hi = STRESS_WIDTH_MAX if hi is None else hi
    stresses = []
    for m, mr in zip(members, member_res):
        A = float(m.get('A', 0.0) or 0.0)
        stresses.append(abs(mr.get('N', 0.0)) / A if A > 1e-12 else 0.0)
    peak = max(stresses, default=0.0)
    if peak <= 1e-12:
        return [lo] * len(stresses), 0.0
    # pt, not px, and scaled down from the canvas's range: a PDF line is
    # measured in points and 7pt bars would merge into a solid mat.
    return [lo + (hi - lo) * (sig / peak) for sig in stresses], peak


PDF_DIAGRAM_FRAC = 0.048    # peak ordinate, as a fraction of the drawing's
                            # projected diagonal
PDF_DIAGRAM_SAMPLES = 13    # per member; enough to read a parabola's sag


def _pdf_along_rod_diagrams(ax, members, proj_2d, curves, peak, color,
                            frac=PDF_DIAGRAM_FRAC, zorder=6):
    """One diagram per member, set off perpendicular to the member itself.

    `curves[i]` is the ordinate sampled from end a to end b of member i, or
    None where that member has nothing to draw. The value is laid off along
    the member's own perpendicular IN THE SHEET PLANE, which is what a
    shear or bending diagram over a projected view means: the rod is the
    baseline and the distance from it is the magnitude. Every member is
    scaled by the SAME `peak`, so two rods can be compared by eye -- a
    per-member scale would make the least-loaded rod look like the worst.

    A rod pointing straight at the reader projects to a point and has no
    perpendicular on this sheet, so it is skipped rather than drawn in an
    arbitrary direction. Returns (extra_pts, n_drawn, n_flat): the vertices
    the diagrams reach, so the caller can fit the window around them
    instead of clipping them at the model's own edge.
    """
    import math
    from matplotlib.collections import LineCollection, PolyCollection
    if peak <= 1e-12 or not proj_2d:
        return [], 0, 0
    xs = [p[0] for p in proj_2d]
    ys = [p[1] for p in proj_2d]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    unit = frac * diag / peak

    rgb = _hex_to_rgb(color)
    outlines, fills, extra = [], [], []
    n_drawn = n_flat = 0
    for i, m in enumerate(members):
        vals = curves[i] if i < len(curves) else None
        if not vals or max(abs(v) for v in vals) <= 1e-12:
            continue
        a, b = m['a'], m['b']
        if a >= len(proj_2d) or b >= len(proj_2d):
            continue
        (ax0, ay0), (ax1, ay1) = proj_2d[a], proj_2d[b]
        dx, dy = ax1 - ax0, ay1 - ay0
        ln = math.hypot(dx, dy)
        if ln <= 1e-9:
            n_flat += 1
            continue
        nx, ny = -dy / ln, dx / ln          # left of a->b, in the sheet
        n = len(vals)
        base, curve = [], []
        for j, v in enumerate(vals):
            t = j / (n - 1) if n > 1 else 0.0
            bx, by = ax0 + dx * t, ay0 + dy * t
            base.append((bx, by))
            curve.append((bx + nx * v * unit, by + ny * v * unit))
        outlines.append(curve)
        # the closing stems at both ends are what makes it read as a
        # diagram hung off the rod rather than a stray polyline
        outlines.append([base[0], curve[0]])
        outlines.append([base[-1], curve[-1]])
        fills.append(curve + list(reversed(base)))
        extra.extend(curve)
        n_drawn += 1

    if fills:
        ax.add_collection(PolyCollection(fills, facecolors=[rgb], alpha=0.22,
                                         edgecolors='none', zorder=zorder))
    if outlines:
        ax.add_collection(LineCollection(outlines, colors=[rgb],
                                         linewidths=0.7, zorder=zorder + 0.1))
    return extra, n_drawn, n_flat


def _pdf_members(ax, members, proj_2d, color_fn, linewidth=1.0, zorder=3,
                 dashed_idx=()):
    """Every bar in one LineCollection.

    One collection instead of one Line2D per bar: an 800-bar model across
    six sheets is ~5000 artists otherwise, which is both slow to write and
    needlessly large in the file.
    """
    from matplotlib.collections import LineCollection
    segs, cols, wids = [], [], []
    dash_segs, dash_cols, dash_wids = [], [], []
    dashed_idx = set(dashed_idx)
    per_bar = isinstance(linewidth, (list, tuple))
    for i, m in enumerate(members):
        a, b = m['a'], m['b']
        if a >= len(proj_2d) or b >= len(proj_2d):
            continue
        seg = (proj_2d[a], proj_2d[b])
        col = _hex_to_rgb(color_fn(i))
        wid = (linewidth[i] if per_bar and i < len(linewidth) else
               (1.0 if per_bar else linewidth))
        if i in dashed_idx:
            dash_segs.append(seg)
            dash_cols.append(col)
            dash_wids.append(wid)
        else:
            segs.append(seg)
            cols.append(col)
            wids.append(wid)
    if segs:
        ax.add_collection(LineCollection(segs, colors=cols, linewidths=wids,
                                         zorder=zorder, capstyle='round'))
    if dash_segs:
        ax.add_collection(LineCollection(dash_segs, colors=dash_cols,
                                         linewidths=dash_wids,
                                         zorder=zorder + 0.1,
                                         linestyles=(0, (3.5, 2.2))))


def _pdf_supports(ax, supports, proj_2d):
    """The support glyph is the same small square the canvas draws."""
    from apps.stereo.stereo_app_constants import SUPPORT_COLOR
    if not supports:
        return
    pts = [proj_2d[s['node']] for s in supports
           if 0 <= s['node'] < len(proj_2d)]
    if not pts:
        return
    ax.plot([p[0] for p in pts], [p[1] for p in pts], linestyle='none',
            marker='s', markersize=4.0, color=_hex_to_rgb(SUPPORT_COLOR),
            zorder=8)


def _pdf_load_arrows(ax, nodes, loads, proj_2d, az_rad, el_rad, span_m):
    """An arrow per loaded node, along that node's own net force direction.

    A general view that shows the geometry but not what is being PUT on it
    is not a load case, and the load case is the first thing anyone asks
    about a result. Lengths are gamma-compressed against the largest load
    present, the same perceptual compression the canvas uses, so a model
    whose loads span orders of magnitude still shows every arrow.
    """
    import math
    from matplotlib.collections import LineCollection
    from apps.stereo.stereo_app_constants import LOAD_COLOR

    net = {}
    for ld in loads or ():
        i = ld.get('node')
        if i is None or not (0 <= i < len(nodes)):
            continue
        fx, fy, fz = net.get(i, (0.0, 0.0, 0.0))
        net[i] = (fx + ld.get('fx', 0.0), fy + ld.get('fy', 0.0),
                  fz + ld.get('fz', 0.0))
    mags = [math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) for v in net.values()]
    mags = [m for m in mags if m > 1e-12]
    if not mags:
        return 0
    peak = max(mags)
    full = span_m * 0.10

    segs = []
    for i, (fx, fy, fz) in net.items():
        mag = math.sqrt(fx * fx + fy * fy + fz * fz)
        if mag <= 1e-12:
            continue
        L = full * (mag / peak) ** 0.6           # same gamma as the canvas
        ux, uy, uz = fx / mag * L, fy / mag * L, fz / mag * L
        hx, hy = proj_2d[i]
        tx, ty = _pdf_project(nodes[i][0] - ux, nodes[i][1] - uy,
                              nodes[i][2] - uz, az_rad, el_rad)
        segs.append(((tx, ty), (hx, hy)))
        # two barbs, so the arrow reads as pointing AT the node
        vx, vy = hx - tx, hy - ty
        n = math.hypot(vx, vy)
        if n > 1e-12:
            vx, vy = vx / n, vy / n
            px, py = -vy, vx
            # Capped against the LONGEST arrow on the sheet, not against
            # this one's own shaft, so every head is the same size and the
            # length alone carries the magnitude.
            head = max(min(n * 0.30, full * 0.22), 1e-9)
            segs.append(((hx, hy), (hx - vx * head + px * head * 0.45,
                                    hy - vy * head + py * head * 0.45)))
            segs.append(((hx, hy), (hx - vx * head - px * head * 0.45,
                                    hy - vy * head - py * head * 0.45)))
    if segs:
        ax.add_collection(LineCollection(segs, colors=[_hex_to_rgb(LOAD_COLOR)],
                                         linewidths=0.7, zorder=6))
    return len(net)


def _pdf_view_axes(fig):
    """One drawing axes filling the sheet above the title block.

    Deliberately NOT set_aspect('equal'): that makes matplotlib resize the
    axes BOX at draw time to satisfy the aspect, which moves everything
    placed in axes fractions (the key, the stats panel) out from under the
    drawing they annotate. _pdf_fit_window does the equal-aspect fit on
    the LIMITS instead, against this fixed box, so x and y still scale
    identically and every position stays computable in advance.
    """
    x0, y0, x1, y1 = PDF_FRAME
    ax = fig.add_axes([x0 + 0.012, y0 + PDF_TITLE_H + 0.012,
                       (x1 - x0) - 0.024,
                       (y1 - y0) - PDF_TITLE_H - 0.030])
    ax.set_aspect('auto')
    ax.set_axis_off()
    return ax


def _pdf_axes_size_in(ax):
    """(width, height) of an axes box in inches."""
    fig = ax.get_figure()
    box = ax.get_position()
    fw, fh = fig.get_size_inches()
    return box.width * fw, box.height * fh


def _pdf_text_block_height(ax, n_lines, fontsize=PDF_KEY_FS, pad_pt=6.3):
    """How much of the axes height a monospaced block of n lines takes.

    Returned as an axes FRACTION, so a caller can keep that band of the
    sheet clear. matplotlib's default line spacing is 1.2 x the font size.
    """
    _, h_in = _pdf_axes_size_in(ax)
    h_pt = max(h_in * 72.0, 1e-6)
    return (n_lines * fontsize * 1.2 + pad_pt) / h_pt


def _pdf_fit_window(ax, pts, reserve_top=0.0, reserve_bottom=0.20,
                    reserve_left=0.02, reserve_right=0.02, margin=0.04):
    """Data limits that hold every point, keep the reserved bands of the
    axes clear, and scale x and y identically.

    `reserve_*` are fractions of the axes that the furniture has already
    claimed -- the colour key and the stats panel along the top, the scale
    bar and the orientation triad along the bottom. The drawing is fitted
    into what is left and centred there, so no panel ever lands on top of
    the structure it is describing.

    Returns the (x0, y0, x1, y1) window actually set.
    """
    pts = list(pts)
    if not pts:
        ax.set_xlim(0.0, 1.0)
        ax.set_ylim(0.0, 1.0)
        return (0.0, 0.0, 1.0, 1.0)

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    dw = (maxx - minx) or 1.0
    dh = (maxy - miny) or 1.0

    box_w, box_h = _pdf_axes_size_in(ax)
    fx = max(1.0 - reserve_left - reserve_right - 2 * margin, 0.05)
    fy = max(1.0 - reserve_top - reserve_bottom - 2 * margin, 0.05)

    # data units per inch: whichever direction runs out of room first
    s = max(dw / (box_w * fx), dh / (box_h * fy))
    win_w, win_h = s * box_w, s * box_h

    # centre the drawing inside the band that is still free
    cx_frac = (reserve_left + margin + (1.0 - reserve_right - margin)) / 2.0
    cy_frac = (reserve_bottom + margin + (1.0 - reserve_top - margin)) / 2.0
    x0 = (minx + maxx) / 2.0 - cx_frac * win_w
    y0 = (miny + maxy) / 2.0 - cy_frac * win_h
    ax.set_xlim(x0, x0 + win_w)
    ax.set_ylim(y0, y0 + win_h)
    return (x0, y0, x0 + win_w, y0 + win_h)


# ── per-view statistics ───────────────────────────────────────────────────

def _pdf_fmt_node(nodes, i, u=None):
    u = u or ReportUnits()
    x, y, z = (u.v('length', c) for c in nodes[i])
    return f'#{i} ({x:.2f}, {y:.2f}, {z:.2f})'


def _pdf_fmt_bar(nodes, members, i, u=None):
    """'bar 98: nodes 35 → 44 at (x, y, z)', so the reader can FIND it.

    Naming only one of a bar's two ends, as the first draft did, is not
    enough to identify it in the model tree or in the Excel export.
    """
    u = u or ReportUnits()
    m = members[i]
    a, b = m['a'], m['b']
    mid = tuple(u.v('length', (nodes[a][k] + nodes[b][k]) / 2.0)
                for k in range(3))
    return (f'bar {i}: nodes {a} → {b}',
            f'  mid ({mid[0]:.2f}, {mid[1]:.2f}, {mid[2]:.2f})')


def _pdf_force_stats(nodes, members, member_res, u=None):
    """Axial-force numbers worth printing beside the axial-force drawing."""
    u = u or ReportUnits()
    forces = [mr['N'] for mr in member_res]
    if not forces:
        return ['AXIAL FORCE', 'no members']
    i_max = max(range(len(forces)), key=lambda i: forces[i])
    i_min = min(range(len(forces)), key=lambda i: forces[i])
    peak = max(abs(f) for f in forces)
    from apps.stereo.stereo_app_constants import NEAR_ZERO_FRAC
    n_zero = sum(1 for f in forces if peak > 0 and abs(f) / peak < NEAR_ZERO_FRAC)
    n_t = sum(1 for f in forces if f > 0)
    n_c = sum(1 for f in forces if f < 0)
    total_abs = sum(abs(f) for f in forces)
    out = [
        'AXIAL FORCE',
        f'bars            {len(forces)}',
        f'in tension      {n_t}   ({n_t / len(forces):.0%})',
        f'in compression  {n_c}   ({n_c / len(forces):.0%})',
        f'near zero       {n_zero}   (<{NEAR_ZERO_FRAC:.0%} of peak)',
        '',
        f'max tension     {u.fl("force", forces[i_max], 2, sign=True)}',
    ]
    out += [f'  {ln}' for ln in _pdf_fmt_bar(nodes, members, i_max, u)]
    out.append(f'max compression {u.fl("force", forces[i_min], 2, sign=True)}')
    out += [f'  {ln}' for ln in _pdf_fmt_bar(nodes, members, i_min, u)]
    out.append(f'mean |N|        '
               f'{u.fl("force", total_abs / len(forces))}')
    return out


def _pdf_util_stats(checks):
    """Utilisation numbers: the margin table an FEA report is judged on."""
    vals = [(i, c['util']) for i, c in enumerate(checks) if c.get('checked')]
    if not vals:
        return ['UTILIZATION', 'no member has a section assigned yet']
    utils = [u for _, u in vals]
    utils_sorted = sorted(utils)
    i_worst, worst = max(vals, key=lambda t: t[1])
    n_over = sum(1 for u in utils if u > 1.0)
    n_high = sum(1 for u in utils if 0.8 < u <= 1.0)
    unchecked = len(checks) - len(vals)
    mid = utils_sorted[len(utils_sorted) // 2]
    mode = checks[i_worst].get('mode', '?')
    return [
        'UTILIZATION (demand / capacity)',
        f'checked bars    {len(vals)}' + (f'   ({unchecked} unchecked)'
                                          if unchecked else ''),
        f'governing       {worst:.3f}   bar {i_worst} ({mode})',
        f'median          {mid:.3f}',
        f'mean            {sum(utils) / len(utils):.3f}',
        '',
        f'over capacity   {n_over}  (util > 1.00)',
        f'0.80 - 1.00     {n_high}',
        f'below 0.80      {len(vals) - n_over - n_high}',
        '',
        ('VERDICT: all checked bars within capacity' if not n_over
         else f'VERDICT: {n_over} bar(s) OVER capacity'),
    ]


def _pdf_moment_stats(nodes, moment_by_node, n_rigid, n_members, u=None):
    """Nodal-moment numbers, and an honest line when there are none."""
    u = u or ReportUnits()
    if not moment_by_node:
        return [
            'NODAL MOMENTS',
            f'rigid connections  {n_rigid} of {n_members}',
            '',
            'Every connection in this model is a',
            'PIN, so no joint transfers a moment',
            'and there is nothing to plot. Give',
            'members a rigid connection to see a',
            'moment field here.',
        ]
    vals = list(moment_by_node.values())
    i_pos = max(moment_by_node, key=lambda k: moment_by_node[k])
    i_neg = min(moment_by_node, key=lambda k: moment_by_node[k])
    peak = max(abs(v) for v in vals)
    return [
        'NODAL MOMENTS (resultant, signed)',
        f'rigid connections  {n_rigid} of {n_members}',
        f'joints with moment {len(vals)}',
        '',
        f'max positive   '
        f'{u.fl("moment", moment_by_node[i_pos], 3, sign=True)}',
        f'  node {_pdf_fmt_node(nodes, i_pos, u)}',
        f'max negative   '
        f'{u.fl("moment", moment_by_node[i_neg], 3, sign=True)}',
        f'  node {_pdf_fmt_node(nodes, i_neg, u)}',
        f'peak |M|       {u.fl("moment", peak, 3)}',
        f'mean |M|       '
        f'{u.fl("moment", sum(abs(v) for v in vals) / len(vals), 3)}',
    ]


# The serviceability limit the deformed sheet is judged against. L/250 of
# the span under the total load is the common SI roof limit (CIRSOC 301
# follows EN 1993-1-1's recommended values, which give L/250 total and
# L/300 for the variable part alone). It is a RECOMMENDED value, not a
# hard rule: it is the number a project brief usually adopts and
# occasionally overrides, so export_pdf takes it as an argument.
PDF_DEFLECTION_DENOM = 250


def _pdf_deflection_check(disps, ext, longest_bar_m, denom=PDF_DEFLECTION_DENOM):
    """Worst displacement against its allowance. Returns a dict, or None.

    The reference span is the model's largest HORIZONTAL extent, not its
    longest bar: a serviceability limit is about how far the structure
    sags between its supports, and the longest single rod in a space truss
    is a diagonal of one module, which would make the allowance far too
    tight. Where the model has no horizontal extent at all (a single
    column) the longest bar is the only length there is, so it is used.

    `ratio` is displacement / allowance: at or below 1.0 the structure
    passes. It is a ratio of two lengths, so it is the same number in
    every unit convention.
    """
    if not disps or denom <= 0:
        return None
    span_m = max(ext[0], ext[1]) or longest_bar_m
    if span_m <= 0:
        return None
    allow_mm = span_m * 1000.0 / denom
    worst_mm = max(disps)
    return {
        'denom': denom,
        'span_m': span_m,
        'allow_mm': allow_mm,
        'worst_mm': worst_mm,
        'ratio': (worst_mm / allow_mm) if allow_mm > 0 else float('inf'),
        'ok': worst_mm <= allow_mm,
    }


def _pdf_deform_stats(nodes, node_res, disps, scale_factor, span_m, u=None,
                      check=None):
    """Displacement numbers, including the span/deflection ratio."""
    u = u or ReportUnits()
    if not disps:
        return ['DEFORMED SHAPE', 'no nodes']
    i_max = max(range(len(disps)), key=lambda i: disps[i])
    max_disp = disps[i_max]
    nr = node_res[i_max]
    ratio = (span_m * 1000.0 / max_disp) if max_disp > 1e-12 else float('inf')
    ratio_txt = f'L / {ratio:,.0f}' if ratio != float('inf') else 'L / inf'
    n_moving = sum(1 for d in disps if d > max_disp * 0.5) if max_disp else 0
    tail = []
    if check:
        tail = [
            '',
            f'SERVICEABILITY  L / {check["denom"]}',
            f'  span (ref)    {u.fl("length", check["span_m"])}',
            f'  allowance     {u.fl("deflection", check["allow_mm"], 3)}',
            f'  worst / allow {check["ratio"]:.3f}',
            ('  VERDICT: within L / %d' % check['denom'] if check['ok']
             else '  VERDICT: EXCEEDS L / %d' % check['denom']),
        ]
    return [
        'DEFORMED SHAPE',
        f'display scale   x{scale_factor:,.0f}',
        f'max |u|         {u.fl("deflection", max_disp, 3)}',
        f'  node {_pdf_fmt_node(nodes, i_max, u)}',
        f'   ux {u.f("deflection", nr["ux"], 3, sign=True)}'
        f'  uy {u.f("deflection", nr["uy"], 3, sign=True)}'
        f'  uz {u.f("deflection", nr["uz"], 3, sign=True)} '
        f'{u.lab("deflection")}',
        '',
        f'longest bar     {u.fl("length", span_m)}',
        # L/n is a RATIO of two lengths, so it is the one number here that
        # is the same in every convention -- and must not be converted.
        # Its L is the longest BAR; the serviceability block below takes
        # its own L over the span, and saying which is which keeps two
        # different ratios on one panel from reading as a contradiction.
        f'deflection      {ratio_txt}  (longest bar)',
        f'mean |u|        {u.fl("deflection", sum(disps) / len(disps), 3)}',
        f'nodes > 50% max {n_moving}',
    ] + tail


def submodel(nodes, members, loads, supports, results=None, checks=None,
             member_idx=None, node_idx=None):
    """A self-contained copy of PART of a model, re-indexed from zero.

    What makes a selection reportable on its own: the rest of the
    structure is not dimmed or pushed behind anything, it is simply absent
    from what comes back, so nothing can obstruct the group being looked
    at. Every parallel array travels with it -- node_res, member_res,
    reactions and the member checks are filtered and renumbered to match,
    so `export_pdf` reports a selection by exactly the same code path it
    reports a whole model.

    `member_idx` and `node_idx` are indices into the ORIGINAL model; either
    may be None for "all". A selected member always brings both of its end
    nodes, whether or not they were selected, since a bar with one end is
    not a bar.

    Returns (nodes, members, loads, supports, results, checks, node_map).
    """
    keep_m = (sorted(set(member_idx)) if member_idx is not None
              else list(range(len(members))))
    keep_m = [i for i in keep_m if 0 <= i < len(members)]

    keep_n = {i for i in (node_idx or ()) if 0 <= i < len(nodes)}
    for i in keep_m:
        keep_n.add(members[i]['a'])
        keep_n.add(members[i]['b'])
    keep_n = sorted(keep_n)
    node_map = {old: new for new, old in enumerate(keep_n)}

    sub_nodes = [tuple(nodes[i]) for i in keep_n]
    sub_members = []
    for i in keep_m:
        m = dict(members[i])
        m['a'] = node_map[members[i]['a']]
        m['b'] = node_map[members[i]['b']]
        m['_source_index'] = i      # so a report can still name the bar
        sub_members.append(m)

    sub_loads = [dict(ld, node=node_map[ld['node']]) for ld in (loads or ())
                 if ld.get('node') in node_map]
    sub_supports = [dict(s, node=node_map[s['node']]) for s in (supports or ())
                    if s.get('node') in node_map]

    sub_results = None
    if results is not None:
        node_res = results.get('node_res') or []
        member_res = results.get('member_res') or []
        reactions = results.get('reactions') or {}
        sub_results = {
            'node_res': [node_res[i] for i in keep_n if i < len(node_res)],
            'member_res': [member_res[i] for i in keep_m if i < len(member_res)],
            'reactions': {node_map[i]: r for i, r in reactions.items()
                          if i in node_map},
        }

    sub_checks = None
    if checks is not None:
        sub_checks = [checks[i] for i in keep_m if i < len(checks)]

    return (sub_nodes, sub_members, sub_loads, sub_supports, sub_results,
            sub_checks, node_map)


def _pdf_equilibrium(loads, reactions):
    """Applied load vs. reaction totals, and the residual between them.

    A solved model that does not close on its own equilibrium is wrong, and
    that check belongs in the report rather than in the reader's head.
    Returns (applied, reacted, residual), each an (Fx, Fy, Fz) tuple.
    """
    ap = [0.0, 0.0, 0.0]
    for ld in loads or ():
        ap[0] += ld.get('fx', 0.0)
        ap[1] += ld.get('fy', 0.0)
        ap[2] += ld.get('fz', 0.0)
    rc = [0.0, 0.0, 0.0]
    for r in (reactions or {}).values():
        rc[0] += r.get('Fx', 0.0)
        rc[1] += r.get('Fy', 0.0)
        rc[2] += r.get('Fz', 0.0)
    res = [a + b for a, b in zip(ap, rc)]
    return tuple(ap), tuple(rc), tuple(res)


# How much of a table sheet's note fits on one line, and how far the next
# one sits below it. Measured against the widest sheet the report draws,
# at the 7.5 pt italic the note is set in.
PDF_TABLE_NOTE_CHARS = 168
PDF_TABLE_NOTE_PITCH = 0.021


def _pdf_table_page(fig, title, headers, rows, widths, note='', tail_rows=()):
    """A plain monospaced table sheet, with alternating row shading.

    `tail_rows` are summary lines (totals, a residual) that are ALWAYS
    drawn, with the body truncated above them to make room. They cannot be
    the last few entries of `rows`, because on a model with 294 supports
    the body ran off the bottom of the sheet and took the Σ-reaction,
    Σ-applied and residual lines with it -- deleting the one thing the
    reactions sheet exists to show.
    """
    from matplotlib.patches import Rectangle
    x0, y0, x1, y1 = PDF_FRAME
    ax = fig.add_axes([x0 + 0.020, y0 + PDF_TITLE_H + 0.010,
                       (x1 - x0) - 0.040,
                       (y1 - y0) - PDF_TITLE_H - 0.040])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    ax.text(0.0, 1.0, title, fontsize=13, fontweight='bold', color='#1a1a1a',
            va='top', ha='left')
    top = 0.935
    if note:
        # Wrapped, not trimmed. A one-line note ran off the right edge of
        # the sheet the moment it said anything worth saying, and the
        # sentence that fell off was invisible -- there is no clipping
        # mark, the text simply stops at the paper's edge.
        import textwrap
        lines = textwrap.wrap(note, PDF_TABLE_NOTE_CHARS) or ['']
        for k, line in enumerate(lines):
            ax.text(0.0, 0.965 - k * PDF_TABLE_NOTE_PITCH, line, fontsize=7.5,
                    color='#5f6368', va='top', ha='left', style='italic')
        top = 0.915 - (len(lines) - 1) * PDF_TABLE_NOTE_PITCH

    total = sum(widths) or 1.0
    xs, acc = [], 0.0
    for w in widths:
        xs.append(acc / total)
        acc += w

    for x, h in zip(xs, headers):
        ax.text(x, top, h, fontsize=7.6, fontweight='bold', color='#222222',
                va='top', ha='left', family=PDF_MONO)
    ax.plot([0, 1], [top - 0.022, top - 0.022], color=PDF_RULE, linewidth=0.8)

    def draw_row(y_, row, shaded):
        if shaded:
            ax.add_patch(Rectangle((-0.004, y_ - pitch * 0.30), 1.008, pitch * 0.92,
                                   facecolor='#f4f6f8', edgecolor='none',
                                   zorder=0))
        for x, cell in zip(xs, row):
            ax.text(x, y_, str(cell), fontsize=7.2, color='#333333', va='top',
                    ha='left', family=PDF_MONO, zorder=1)

    pitch = 0.0235
    # reserve the tail (plus its rule and the truncation note) up front
    tail = list(tail_rows)
    floor = 0.02 + (len(tail) + 1.4) * pitch + (1.6 * pitch if tail else 0.0)

    y = top - 0.040
    shown = 0
    for ri, row in enumerate(rows):
        if y < floor:
            break
        draw_row(y, row, ri % 2 == 1)
        y -= pitch
        shown += 1

    # A table that silently stops at the bottom of the sheet is a table the
    # reader has no way to know is incomplete.
    if shown < len(rows):
        ax.text(0.0, y, f'… {len(rows) - shown} further row(s) not shown — '
                        f'use Export Excel for the complete table',
                fontsize=7.0, color='#5f6368', va='top', ha='left',
                style='italic')
        y -= 1.6 * pitch    # the note hangs BELOW its baseline; clear it

    if tail:
        # The rule goes BELOW the last body row's glyphs, not through them:
        # a row is drawn from its baseline downwards, so `y + pitch * 0.55`
        # -- half a line above where the next row would start -- landed
        # inside the descenders of the row above and struck it out.
        rule_y = y + pitch * 0.18
        ax.plot([0, 1], [rule_y, rule_y], color=PDF_RULE, linewidth=0.8)
        y -= pitch * 0.30
        for row in tail:
            draw_row(y, row, False)
            y -= pitch
    return ax


PDF_SHEET_GROUPS = ('views', 'force', 'utilization', 'moment',
                    'deformed', 'tables')


def plan_sheets(results=None, checks=None, n_rigid=0, groups=None):
    """Which sheets this report will actually contain, in order.

    Returned as a list of keys so the title block's "Sheet n / N" is
    counted from the same list the loop renders, rather than from a
    parallel arithmetic expression that has to be kept in step by hand.

    `groups` is any subset of PDF_SHEET_GROUPS; None means all of them.
    """
    want = set(PDF_SHEET_GROUPS if groups is None else groups)
    have_checks = bool(checks) and any(c.get('checked') for c in (checks or ()))
    plan = ['general']
    if 'views' in want:
        plan += [name for name, _ in PDF_ORTHO_VIEWS]
    if results is None:
        return plan
    if 'force' in want:
        plan += ['force_iso', 'force_top']
    if 'utilization' in want and have_checks:
        plan += ['util_iso', 'util_top', 'util_rel']
    if 'moment' in want:
        plan.append('moment_nodes')
        # Bending and shear ALONG a rod exist only where a joint can
        # transfer a moment into it; a pin-jointed truss has neither.
        if n_rigid:
            plan += ['moment_rods', 'shear_rods']
    if 'deformed' in want:
        plan.append('deformed')
    if 'tables' in want:
        plan += ['reactions', 'governing', 'solicitation_rods']
        if n_rigid:
            plan.append('solicitation_nodes')
        plan.append('takeoff')
    return plan


# ── the report itself ─────────────────────────────────────────────────────

def export_pdf(nodes, members, loads, supports, results, path, checks=None,
               meta=None, az_deg=30, el_deg=25, ortho_views=True,
               groups=None, deflection_denom=PDF_DEFLECTION_DENOM,
               unit_weight_kN_m3=None, into=None, sheet_base=0,
               sheet_total=None):
    """Generate the multi-sheet PDF analysis report.

    Sheets: 1) the general (axonometric) view with the load case, then the
    five orthographic views -- plan, front, back, right, left -- each over
    its own dimension grid; then, once the model has been analysed, axial
    force and utilisation (each in the general view and in plan, and
    utilisation once more scaled to this model's own range), nodal
    moments, bending and shear along the rods where the model has rigid
    joints, the deformed shape with its serviceability verdict, support
    reactions with the equilibrium check, the governing-member schedule,
    the maximum-solicitation schedules for the rods and the nodes, and the
    steel take-off. `plan_sheets` is the authority on which of those a
    given model and `groups` selection actually produces.

    Every sheet carries a frame, a title block, a horizontal graphic scale
    bar, an orientation indicator and one colour key; see this section's
    own header for why each of those is there.

    `meta` may carry 'group' and 'subset_of' when this report covers a
    SELECTION rather than a whole model (see submodel()): the title block
    then names both the file and the group, and the equilibrium check says
    that its residual is the force the rest of the structure carries
    across the cut rather than a solver error.

    `ortho_views=False` drops the five orthographic sheets, for a short
    report. `deflection_denom` is the serviceability limit the deformed
    sheet is judged against, as the n in L/n; None drops the check.
    `unit_weight_kN_m3` is the material unit weight the take-off sheet
    computes mass from; it defaults to the same one the self-weight load
    case uses, so the two cannot disagree.

    `into` is an already open PdfPages to append to instead of writing
    `path` -- how export_groups_pdf puts one section per group in a single
    document. `sheet_base` and `sheet_total` then number these sheets
    within the whole document ("Sheet 14 / 52"), not within this section.
    Returns the number of sheets written.
    """
    from common import _ensure_matplotlib
    if not _ensure_matplotlib():
        raise RuntimeError('matplotlib is required for PDF export.')

    import math
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    from apps.stereo.stereo_app_colors import (
        force_color, util_color, moment_color, deform_color,
        reaction_moment_signed,
    )
    from apps.stereo.stereo_app_constants import (
        MEMBER_PIN_COLOR, MEMBER_RIGID_COLOR, NEAR_ZERO_COLOR, NEAR_ZERO_FRAC,
        SUPPORT_COLOR, LOAD_COLOR, UTIL_HIGH,
        MOMENT_NEG_HIGH, MOMENT_POS_HIGH,
    )

    az = math.radians(az_deg)
    el = math.radians(el_deg)
    proj_2d = [_pdf_project(x, y, z, az, el) for x, y, z in nodes]
    ext = _pdf_model_extents(nodes)
    span_m = max(max(ext), 1e-6)
    # Whatever the app-wide selector is set to AT EXPORT TIME -- the
    # convention the reader was just looking at on screen.
    u = ReportUnits()
    sheet_meta = _pdf_sheet_meta(nodes, members, meta, u=u)

    from apps.stereo import stereo_math as _sm
    unit_weight = (_sm.DEFAULT_STEEL_UNIT_WEIGHT if unit_weight_kN_m3 is None
                   else float(unit_weight_kN_m3))

    n_rigid = sum(1 for m in members if m.get('conn') == 'rigid')
    have_checks = bool(checks) and any(c.get('checked') for c in checks)
    want = set(PDF_SHEET_GROUPS if groups is None else groups)
    if not ortho_views:
        want.discard('views')
    plan = plan_sheets(results, checks, n_rigid, want)
    views = [(n, v) for n, v in PDF_ORTHO_VIEWS if n in plan]
    group = (meta or {}).get('group')
    subset_of = (meta or {}).get('subset_of')
    total = len(plan) if sheet_total is None else sheet_total
    sheet = [0]

    def new_sheet(title):
        sheet[0] += 1
        fig = plt.figure(figsize=PDF_SHEET_IN)
        fig.patch.set_facecolor('white')
        _pdf_sheet(fig, sheet_base + sheet[0], total, title, sheet_meta)
        return fig

    def conn_color(i):
        return (MEMBER_RIGID_COLOR if members[i].get('conn') == 'rigid'
                else MEMBER_PIN_COLOR)

    import contextlib
    with (contextlib.nullcontext(into) if into is not None
          else PdfPages(path)) as pdf:
        # ── Sheet 1: model, load case, general view ─────────────────────
        fig = new_sheet('General view — model and load case')
        ax = _pdf_view_axes(fig)
        _pdf_members(ax, members, proj_2d, conn_color, linewidth=0.8)
        _pdf_supports(ax, supports, proj_2d)
        n_loaded = _pdf_load_arrows(ax, nodes, loads, proj_2d, az, el, span_m)

        key = _PdfKey(ax)
        key.caption('References')
        key.row(MEMBER_PIN_COLOR, 'bar, pin connection')
        if n_rigid:
            key.row(MEMBER_RIGID_COLOR, 'bar, rigid (moment) connection')
        key.row(SUPPORT_COLOR, 'support (restrained node)', marker='s')
        if n_loaded:
            key.row(LOAD_COLOR, 'applied load, along its own direction')
            key.note('arrow length ∝ |F|^0.6 of the largest load')

        info = ['SELECTED GROUP' if group else 'MODEL']
        if group:
            info.append(f'group           {group}')
            if subset_of:
                info.append(f'from file       {subset_of}')
            info.append('shown in isolation — the rest')
            info.append('of the model is not drawn')
            info.append('')
        if meta:
            fam = meta.get('grid_family') or meta.get('typology')
            if fam and not group:
                info.append(f'family          {fam}')
        info += [
            f'nodes           {len(nodes)}',
            f'bars            {len(members)}',
            f'  pin / rigid   {len(members) - n_rigid} / {n_rigid}',
            f'supports        {len(supports)}',
            f'loaded nodes    {n_loaded}',
            '',
            f'EXTENTS ({u.lab("length")})',
            f'  X  {u.f("length", ext[0])}   Y  {u.f("length", ext[1])}'
            f'   Z  {u.f("length", ext[2])}',
        ]
        try:
            from apps.stereo import stereo_math as sm_mod
            dgi = sm_mod.degree_of_indeterminacy(nodes, members, supports)
            info.append(f'indeterminacy   {dgi:+d}')
        except Exception:
            pass
        ap, rc, resid = _pdf_equilibrium(loads, (results or {}).get('reactions'))
        info += ['', f'APPLIED LOAD ({u.lab("force")})',
                 f'  Fx {u.f("force", ap[0], 2, sign=True)}'
                 f'  Fy {u.f("force", ap[1], 2, sign=True)}'
                 f'  Fz {u.f("force", ap[2], 2, sign=True)}']
        if results is not None:
            info += [
                '', 'RESULTS',
            ] + [f'  {ln}' for ln in
                 summary_text(nodes, members, results, checks,
                              u=u).splitlines()[1:]]
        else:
            info += ['', '(not yet analysed)']
        _pdf_finish_view(ax, nodes, proj_2d, az, el, key, info, u=u)

        pdf.savefig(fig)
        plt.close(fig)

        # ── The five orthographic views ─────────────────────────────────
        #
        # An axonometric view shows the whole shape at once but measures
        # nothing: every axis is foreshortened and depth hides geometry
        # behind geometry. These are the views a structure is actually
        # dimensioned and checked in, each over a ghost grid that labels
        # real world coordinates, and each elevation carrying a line at
        # every distinct structural level.
        for _name, view in views:
            v_az = math.radians(view['az'])
            v_el = math.radians(view['el'])
            v_proj = [_pdf_project(x, y, z, v_az, v_el) for x, y, z in nodes]
            fig = new_sheet(view['title'])
            ax = _pdf_view_axes(fig)
            _pdf_members(ax, members, v_proj, conn_color, linewidth=0.8)
            _pdf_supports(ax, supports, v_proj)

            vkey = _PdfKey(ax)
            vkey.caption('References')
            vkey.row(MEMBER_PIN_COLOR, 'bar, pin connection')
            if n_rigid:
                vkey.row(MEMBER_RIGID_COLOR, 'bar, rigid (moment) connection')
            vkey.row(SUPPORT_COLOR, 'support (restrained node)', marker='s')
            vkey.row(PDF_GHOST_LINE, 'dimension grid (world coordinates)')
            if view['kind'] == 'elevation':
                vkey.row(PDF_LEVEL_LINE, 'structural level, labelled at right',
                         dashed=True)
            vkey.note('orthographic — this view is true to scale')

            h_i = 'XYZ'.index(view['h'])
            v_i = 'XYZ'.index(view['v'])
            n_i = 'XYZ'.index(view['normal'])
            vstats = [
                view['caption'].split('  \u00b7  ')[0],
                f"across    {view['h']}   {u.fl('length', ext[h_i])}",
                f"up        {view['v']}   {u.fl('length', ext[v_i])}",
                f"depth     {view['normal']}   {u.fl('length', ext[n_i])}"
                f"  (into the sheet)",
                '',
                f'nodes     {len(nodes)}',
                f'bars      {len(members)}',
                f'supports  {len(supports)}',
            ]
            if view['kind'] == 'elevation' and nodes:
                levels = sorted({round(n[2], 4) for n in nodes})
                vstats += ['',
                           f'levels    {len(levels)}',
                           f'  lowest  '
                           f'{u.fl("length", levels[0], 2, sign=True)}',
                           f'  highest '
                           f'{u.fl("length", levels[-1], 2, sign=True)}']
            _pdf_finish_view(ax, nodes, v_proj, v_az, v_el, vkey, vstats,
                             view=view, u=u)
            pdf.savefig(fig)
            plt.close(fig)

        if results is None:
            return

        member_res = results['member_res']
        node_res = results['node_res']

        # ── Axial force and utilization, each in two views ──────────────
        #
        # Both analyses are drawn twice: axonometric, which shows the whole
        # shape at once, and plan, which is the view a grid is actually
        # laid out and checked in and the only one where two bars at the
        # same plan position cannot hide behind each other. The builders
        # are parameterised by view rather than copied, so the two can
        # never drift apart.
        max_abs_N = max((abs(mr['N']) for mr in member_res), default=0.0)
        over = set()
        if have_checks:
            over = {i for i, c in enumerate(checks)
                    if c.get('checked') and c['util'] > 1.0}
        widths, peak_sigma = _pdf_stress_widths(members, member_res)
        plan_view = dict(PDF_ORTHO_VIEWS)['plan']

        def view_proj(view):
            if view is None:
                return proj_2d, az, el
            v_az, v_el = math.radians(view['az']), math.radians(view['el'])
            return ([_pdf_project(x, y, z, v_az, v_el) for x, y, z in nodes],
                    v_az, v_el)

        def thickness_rows(key):
            if peak_sigma > 0:
                key.note(f'bar thickness = axial stress |N|/A against this '
                         f'model\'s own peak, '
                         f'{u.f_stress_kn_cm2(peak_sigma)}')

        def force_sheet(view):
            where = 'plan view' if view else 'general view'
            fig = new_sheet(f'Axial force — N ({u.lab("force")}), {where}')
            ax = _pdf_view_axes(fig)
            pts, v_az, v_el = view_proj(view)

            def fc(i):
                return force_color(member_res[i]['N'], max_abs_N)

            _pdf_members(ax, members, pts, fc, linewidth=widths, dashed_idx=over)
            _pdf_supports(ax, supports, pts)

            key = _PdfKey(ax)
            key.caption(f'Axial force, {u.lab("force")}  '
                        f'(+ tension / − compression)')
            if max_abs_N > 0:
                key.ramp(lambda N: force_color(N, max_abs_N), -max_abs_N, max_abs_N,
                         [(-max_abs_N,
                           f'−{u.f("force", max_abs_N, 1, comma=True)}'),
                          (0.0, '0'),
                          (max_abs_N,
                           f'+{u.f("force", max_abs_N, 1, comma=True)}')])
                n_zero = sum(1 for mr in member_res
                             if abs(mr['N']) / max_abs_N < NEAR_ZERO_FRAC)
                if n_zero:
                    key.row(NEAR_ZERO_COLOR,
                            f'~0: {n_zero} bars below {NEAR_ZERO_FRAC:.0%} of the scale')
            else:
                key.note('every bar reads exactly zero axial force')
            key.row(SUPPORT_COLOR, 'support', marker='s')
            if over:
                key.row(MEMBER_PIN_COLOR,
                        f'dashed: {len(over)} bar(s) over capacity', dashed=True)
            thickness_rows(key)
            stats = _pdf_force_stats(nodes, members, member_res, u=u)
            if peak_sigma > 0:
                stats += ['', f'peak stress     '
                              f'{u.f_stress_kn_cm2(peak_sigma)}']
            _pdf_finish_view(ax, nodes, pts, v_az, v_el, key, stats, view=view,
                             u=u)
            pdf.savefig(fig)
            plt.close(fig)

        def util_sheet(view, relative=False):
            worst = max((c['util'] for c in checks if c.get('checked')),
                        default=0.0)
            scale = worst if (relative and worst > 1e-9) else 1.2
            where = 'plan view' if view else 'general view'
            title = ('Member utilization — scaled to this model'
                     if relative else f'Member utilization — demand / capacity, {where}')
            fig = new_sheet(title)
            ax = _pdf_view_axes(fig)
            pts, v_az, v_el = view_proj(view)

            def uc(i):
                c = checks[i]
                if not c.get('checked'):
                    return NEAR_ZERO_COLOR
                # Relative: stretch this model's own range across the whole
                # ramp, so a structure whose worst bar sits at 0.08 still
                # shows WHERE the work goes. Absolute: the code threshold,
                # where red always means the same thing.
                if not relative:
                    return util_color(c['util'])
                return util_color(min(c['util'] / scale * 1.2, 1.2))

            _pdf_members(ax, members, pts, uc, linewidth=widths, dashed_idx=over)
            _pdf_supports(ax, supports, pts)

            key = _PdfKey(ax)
            if relative:
                key.caption(f'Utilization, scaled to this model (peak {worst:.3f})')
                # The ramp's own domain is 0..1.2; relative mode stretches
                # 0..worst across it, so the tick VALUES are ramp positions
                # while the tick LABELS are the utilisations they stand for.
                cap = (1.2 / worst) if worst > 1.0 else None
                key.ramp(util_color, 0.0, 1.2,
                         [(0.0, '0'), (0.6, f'{worst * 0.5:.3f}'),
                          (1.2, f'{worst:.3f}')],
                         mark=(cap, 'capacity 1.0') if cap else None)
                key.note('RELATIVE scale — the reddest bar is this model\'s own '
                         'worst, not the code limit')
            else:
                key.caption('Utilization (demand ÷ capacity)')
                key.ramp(util_color, 0.0, 1.2,
                         [(0.0, '0'), (0.5, '0.5'), (1.2, '≥1.2')],
                         mark=(1.0, 'capacity 1.0'))
                key.note('absolute code thresholds — not relative to this model')
            n_unchecked = sum(1 for c in checks if not c.get('checked'))
            if n_unchecked:
                key.row(NEAR_ZERO_COLOR,
                        f'{n_unchecked} bar(s) with no section assigned')
            if over:
                key.row(UTIL_HIGH, f'dashed: {len(over)} bar(s) over capacity',
                        dashed=True)
            key.row(SUPPORT_COLOR, 'support', marker='s')
            thickness_rows(key)
            _pdf_finish_view(ax, nodes, pts, v_az, v_el, key,
                             _pdf_util_stats(checks), view=view, u=u)
            pdf.savefig(fig)
            plt.close(fig)

        if 'force_iso' in plan:
            force_sheet(None)
        if 'force_top' in plan:
            force_sheet(plan_view)
        if 'util_iso' in plan:
            util_sheet(None)
        if 'util_top' in plan:
            util_sheet(plan_view)
        if 'util_rel' in plan:
            util_sheet(None, relative=True)

        if 'moment_nodes' in plan:
            # nodal moments
            # ── Sheet 4: nodal moments ──────────────────────────────────────
            fig = new_sheet(f'Nodal moments — M ({u.lab("moment")})')
            ax = _pdf_view_axes(fig)
            moment_by_node = {}
            max_abs_m = 0.0
            centroid_xy = (sum(n[0] for n in nodes) / max(len(nodes), 1),
                           sum(n[1] for n in nodes) / max(len(nodes), 1))
            support_set = {s['node'] for s in supports}
            for i in support_set:
                r = results['reactions'].get(i)
                if r is not None:
                    m_val = reaction_moment_signed(
                        r, node_xy=(nodes[i][0], nodes[i][1]), centroid_xy=centroid_xy)
                    moment_by_node[i] = m_val
                    max_abs_m = max(max_abs_m, abs(m_val))
            from apps.stereo import stereo_math as sm_mod
            for i, vec in sm_mod.node_moment_vectors(nodes, members, member_res).items():
                if i in moment_by_node:
                    continue
                m_val = reaction_moment_signed(
                    vec, node_xy=(nodes[i][0], nodes[i][1]), centroid_xy=centroid_xy)
                moment_by_node[i] = m_val
                max_abs_m = max(max_abs_m, abs(m_val))
            # A joint whose moment rounds to nothing is not a data point; keeping
            # it would paint a field of white dots and let the key claim a
            # ±0.00 kN·m range, which is what the old sheet did on every
            # pin-jointed model.
            if max_abs_m <= 1e-9:
                moment_by_node = {}

            from apps.stereo.stereo_app_constants import MOMENT_BACKDROP_COLOR
            _pdf_members(ax, members, proj_2d,
                         lambda i: (MOMENT_BACKDROP_COLOR if moment_by_node
                                    else conn_color(i)),
                         linewidth=0.7)
            _pdf_supports(ax, supports, proj_2d)
            if moment_by_node:
                for idx, val in moment_by_node.items():
                    sx, sy = proj_2d[idx]
                    ax.plot([sx], [sy], marker='o', markersize=5.0,
                            color=_hex_to_rgb(moment_color(val, max_abs_m)),
                            markeredgecolor='#9a9a9a', markeredgewidth=0.4,
                            linestyle='none', zorder=9)

            key = _PdfKey(ax)
            if moment_by_node:
                key.caption(f'Node moment, {u.lab("moment")} '
                            f'(resultant, sagging + / hogging −)')
                peak_shown = u.v('moment', max_abs_m)
                key.ramp(lambda m_: moment_color(m_, max_abs_m), -max_abs_m, max_abs_m,
                         [(-max_abs_m, f'−{peak_shown:,.3g}'), (0.0, '0'),
                          (max_abs_m, f'+{peak_shown:,.3g}')])
                key.row(MOMENT_BACKDROP_COLOR,
                        'bars faded — the NODE colour is the content')
                key.row(MOMENT_NEG_HIGH, 'orange = hogging (negative)')
                key.row(MOMENT_POS_HIGH, 'violet = sagging (positive)')
            else:
                key.caption(f'Node moment, {u.lab("moment")}')
                key.note('no joint in this model transfers a moment')
                key.row(MEMBER_PIN_COLOR, 'bar, pin connection')
            key.row(SUPPORT_COLOR, 'support', marker='s')
            _pdf_finish_view(ax, nodes, proj_2d, az, el, key,
                             _pdf_moment_stats(nodes, moment_by_node, n_rigid,
                                               len(members), u=u), u=u)
            pdf.savefig(fig)
            plt.close(fig)

        # ── Bending and shear ALONG the rods ────────────────────────────
        #
        # The nodal-moment sheet answers "which joints work"; these two
        # answer "and what happens between them", which is the part a
        # report built from end actions alone could not show at all. Both
        # are drawn as a proper diagram hung off each rod, to one common
        # scale, over the model itself.
        def along_rod_sheet(kind):
            from apps.stereo import stereo_math as sm_mod
            is_moment = kind == 'moment'
            quantity = 'moment' if is_moment else 'force'
            unit = u.lab(quantity)
            curves, peaks, res_peaks, flips = [], [], [], 0
            for i, mr in enumerate(member_res):
                if mr.get('conn') != 'rigid':
                    curves.append(None)
                    peaks.append(0.0)
                    res_peaks.append(0.0)
                    continue
                d = sm_mod.member_diagram(mr, PDF_DIAGRAM_SAMPLES)
                pair = (d['Mz'], d['My']) if is_moment else (d['Vy'], d['Vz'])
                # The rod is bent in BOTH local planes; plotting the
                # resultant magnitude would hide every sign change, and a
                # diagram that never crosses its baseline cannot show
                # hogging against sagging. So the ordinate is the signed
                # component about whichever local axis is working harder,
                # and the resultant is what the statistics report.
                ca, cb = pair
                use = ca if (max(map(abs, ca), default=0.0)
                             >= max(map(abs, cb), default=0.0)) else cb
                curves.append(list(use))
                peaks.append(max(map(abs, use), default=0.0))
                res_peaks.append(max(d['M' if is_moment else 'V'], default=0.0))
                if max(use, default=0.0) > 1e-9 and min(use, default=0.0) < -1e-9:
                    flips += 1

            peak_ord = max(peaks, default=0.0)
            peak_res = max(res_peaks, default=0.0)
            name = ('Bending moment along the rods' if is_moment
                    else 'Shear along the rods')
            fig = new_sheet(f'{name} — {unit}')
            ax = _pdf_view_axes(fig)
            hot = MOMENT_POS_HIGH if is_moment else MOMENT_NEG_HIGH

            def rc(i):
                if peak_res <= 1e-12:
                    return conn_color(i)
                v = res_peaks[i] / peak_res
                return moment_color(v if is_moment else -v, 1.0)

            _pdf_members(ax, members, proj_2d, rc, linewidth=1.1)
            _pdf_supports(ax, supports, proj_2d)
            extra, n_drawn, n_flat = _pdf_along_rod_diagrams(
                ax, members, proj_2d, curves, peak_ord, hot)

            key = _PdfKey(ax)
            key.caption(f'Peak |{"M" if is_moment else "V"}| along each rod, {unit}')
            if peak_res > 1e-12:
                peak_shown = u.v(quantity, peak_res)
                key.ramp(lambda v: moment_color(v if is_moment else -v, 1.0),
                         0.0, 1.0,
                         [(0.0, '0'), (0.5, f'{peak_shown * 0.5:,.3g}'),
                          (1.0, f'{peak_shown:,.3g}')])
                key.row(hot, 'diagram: the value along the rod, to one '
                             'common scale')
                key.note('ordinate = the SIGNED component about the rod\'s '
                         'more heavily worked local axis, so a sign change '
                         'along the span shows')
                key.note(f'tallest diagram = '
                         f'{u.v(quantity, peak_ord):,.3g} {unit}; '
                         f'the ramp above is the RESULTANT peak per rod')
            else:
                key.note(f'no rod in this model carries '
                         f'{"bending" if is_moment else "shear"}')
            key.row(MEMBER_PIN_COLOR, 'bar, pin connection (carries neither)')
            key.row(SUPPORT_COLOR, 'support', marker='s')
            if n_flat:
                key.note(f'{n_flat} rod(s) point at the reader on this view '
                         f'and have no diagram here')

            stats = [f'rods, rigid     {n_rigid} of {len(members)}',
                     f'with a diagram  {n_drawn}']
            if peak_res > 1e-12:
                gi = max(range(len(res_peaks)), key=lambda i: res_peaks[i])
                gd = sm_mod.member_peak_actions(member_res[gi],
                                                PDF_DIAGRAM_SAMPLES)
                at = gd['x_M' if is_moment else 'x_V']
                L = member_res[gi].get('length_m', 0.0) or 0.0
                live = [v for v in res_peaks if v > 1e-12]
                stats += ['',
                          'governing rod']
                stats += [f'  {ln.strip()}'
                          for ln in _pdf_fmt_bar(nodes, members, gi, u)]
                stats += [f'  peak          '
                          f'{u.fl(quantity, res_peaks[gi], 3, comma=True)}',
                          f'  at x          {u.f("length", at, 3)} of '
                          f'{u.fl("length", L, 3)}',
                          '',
                          f'mean peak       '
                          f'{u.fl(quantity, sum(live) / len(live), 3, comma=True)}',
                          f'sign reverses   {flips} rod(s) in span']
            _pdf_finish_view(ax, nodes, proj_2d, az, el, key, stats,
                             extra_pts=extra, u=u)
            pdf.savefig(fig)
            plt.close(fig)

        if 'moment_rods' in plan:
            along_rod_sheet('moment')
        if 'shear_rods' in plan:
            along_rod_sheet('shear')

        if 'deformed' in plan:
            # deformed shape
            # ── Sheet 5: deformed shape ─────────────────────────────────────
            fig = new_sheet(f'Deformed shape — displacement '
                            f'({u.lab("deflection")})')
            ax = _pdf_view_axes(fig)
            disps = [(nr['ux'] ** 2 + nr['uy'] ** 2 + nr['uz'] ** 2) ** 0.5
                     for nr in node_res]
            max_disp = max(disps, default=0.0)

            longest = 0.0
            for m in members:
                na, nb = nodes[m['a']], nodes[m['b']]
                longest = max(longest, sum((a - b) ** 2 for a, b in zip(na, nb)) ** 0.5)
            if max_disp > 0 and longest > 0:
                scale_factor = longest * 0.05 / (max_disp / 1000.0)
            else:
                scale_factor = 1.0

            def_nodes = []
            for i, (x, y, z) in enumerate(nodes):
                nr = node_res[i]
                def_nodes.append((x + nr['ux'] / 1000.0 * scale_factor,
                                  y + nr['uy'] / 1000.0 * scale_factor,
                                  z + nr['uz'] / 1000.0 * scale_factor))
            def_proj = [_pdf_project(x, y, z, az, el) for x, y, z in def_nodes]

            _pdf_members(ax, members, proj_2d, lambda i: PDF_UNDEFORMED,
                         linewidth=0.5, zorder=2)
            _pdf_members(ax, members, def_proj,
                         lambda i: deform_color(
                             (disps[members[i]['a']] + disps[members[i]['b']]) / 2.0,
                             max_disp),
                         linewidth=1.1, zorder=4)
            _pdf_supports(ax, supports, proj_2d)

            check = (_pdf_deflection_check(disps, ext, longest,
                                           deflection_denom)
                     if deflection_denom else None)

            key = _PdfKey(ax)
            key.caption(f'Deformed shape, displacement in '
                        f'{u.lab("deflection")} (×{scale_factor:,.0f})')
            if max_disp > 0:
                shown = u.v('deflection', max_disp)
                # The ramp stays a MAGNITUDE scale and the allowance is
                # marked on it, rather than the bars being recoloured by
                # displacement/allowance. A fraction-of-allowance ramp
                # reads as one flat colour on any structure comfortably
                # inside its limit -- the same flaw the absolute
                # utilisation sheet has -- and the deflected SHAPE, which
                # is what this sheet exists to show, would go with it.
                mark = None
                if check and check['allow_mm'] <= max_disp:
                    mark = (check['allow_mm'], f'L / {check["denom"]}')
                key.ramp(lambda d: deform_color(d, max_disp), 0.0, max_disp,
                         [(0.0, '0'), (max_disp / 2.0, f'{shown / 2.0:,.3g}'),
                          (max_disp, f'{shown:,.3g}')],
                         mark=mark)
            else:
                key.note('the model did not move')
            key.row(PDF_UNDEFORMED, 'undeformed geometry (reference)')
            key.row(SUPPORT_COLOR, 'support', marker='s')
            if check:
                key.note(f'serviceability limit L / {check["denom"]} = '
                         f'{u.fl("deflection", check["allow_mm"], 2)} over a '
                         f'{u.fl("length", check["span_m"])} span — '
                         f'{"within" if check["ok"] else "EXCEEDED"}')
            key.note('exaggerated — the scale bar measures the undeformed model')
            _pdf_finish_view(ax, nodes, proj_2d, az, el, key,
                             _pdf_deform_stats(nodes, node_res, disps,
                                               scale_factor, longest, u=u,
                                               check=check),
                             extra_pts=def_proj, u=u)
            pdf.savefig(fig)
            plt.close(fig)

        if 'reactions' in plan:
            # support reactions
            # ── Sheet 6: reactions and equilibrium ──────────────────────────
            fig = new_sheet('Support reactions and equilibrium')
            reactions = results['reactions']
            rows = []
            for i in sorted(reactions):
                r = reactions[i]
                x, y, z = nodes[i]
                rows.append([
                    str(i)] + [u.f('length', c) for c in (x, y, z)]
                    + [u.f('force', r.get(k, 0.0), 3, sign=True)
                       for k in ('Fx', 'Fy', 'Fz')]
                    + [u.f('moment', r.get(k, 0.0), 4, sign=True)
                       for k in ('Mx', 'My', 'Mz')])
            ap, rc, resid = _pdf_equilibrium(loads, reactions)
            tail = [
                ['Σ react', '', '', ''] +
                [u.f('force', v, 3, sign=True) for v in rc] + ['', '', ''],
                ['Σ applied', '', '', ''] +
                [u.f('force', v, 3, sign=True) for v in ap] + ['', '', ''],
                ['residual', '', '', ''] +
                [f'{u.v("force", v):+.2e}' for v in resid] + ['', '', ''],
            ]
            worst_res = max(abs(v) for v in resid)
            scale_ref = max(abs(v) for v in ap) or 1.0
            if group:
                # An isolated group is a CUT through a structure: the bars that
                # used to carry load across the cut are gone, so the residual is
                # exactly that transferred force. Calling it a solver error, as
                # the whole-model wording does, would be wrong.
                verdict = (f'residual '
                           f'{u.fl("force", worst_res, 2, comma=True)} is the '
                           f'force the rest of the structure carries across '
                           f'this cut, not an error')
            else:
                verdict = ('equilibrium satisfied'
                           if worst_res <= max(1e-6, scale_ref * 1e-6)
                           else f'residual {u.v("force", worst_res):.3e} '
                                f'{u.lab("force")} — CHECK THE MODEL')
            _pdf_table_page(
                fig, f'Support reactions ({u.lab("force")}, {u.lab("moment")})',
                ['node', 'x', 'y', 'z', 'Fx', 'Fy', 'Fz', 'Mx', 'My', 'Mz'],
                rows, [0.9, 1.0, 1.0, 1.0, 1.25, 1.25, 1.25, 1.3, 1.3, 1.3],
                note=f'Σ reaction + Σ applied must come to zero — {verdict}. '
                     f'{len(reactions)} restrained node(s).',
                tail_rows=tail)
            pdf.savefig(fig)
            plt.close(fig)

        if 'governing' in plan:
            # governing members
            # ── Sheet 7: governing members ──────────────────────────────────
            fig = new_sheet('Governing members')
            forces = [mr['N'] for mr in member_res]
            if have_checks:
                order = sorted((i for i, c in enumerate(checks) if c.get('checked')),
                               key=lambda i: checks[i]['util'], reverse=True)[:26]
                headers = ['bar', 'from', 'to', f'L ({u.lab("length")})',
                           f'N ({u.lab("force")})', 'mode',
                           'util', 'KL/r', 'status']
                rows = []
                for i in order:
                    c = checks[i]
                    m = members[i]
                    na, nb = nodes[m['a']], nodes[m['b']]
                    L = sum((a - b) ** 2 for a, b in zip(na, nb)) ** 0.5
                    sl = c.get('slenderness')
                    rows.append([
                        str(i), str(m['a']), str(m['b']),
                        u.f('length', L, 3),
                        u.f('force', forces[i], 2, sign=True),
                        c.get('mode', ''),
                        f'{c["util"]:.3f}',
                        (f'{sl:.0f}' if isinstance(sl, (int, float)) else '—'),
                        ('OK' if c['util'] <= 1.0 else 'OVER'),
                    ])
                _pdf_table_page(
                    fig, 'Most utilized members (CIRSOC 301 / AISC 360)',
                    headers, rows, [0.8, 0.8, 0.8, 1.1, 1.25, 1.35, 1.0, 1.0, 1.0],
                    note='Ranked by utilisation. Tension is checked against yield '
                         '(H.3.4); compression against flexural buckling (E3).')
            else:
                order = sorted(range(len(forces)), key=lambda i: abs(forces[i]),
                               reverse=True)[:26]
                rows = []
                for i in order:
                    m = members[i]
                    na, nb = nodes[m['a']], nodes[m['b']]
                    L = sum((a - b) ** 2 for a, b in zip(na, nb)) ** 0.5
                    rows.append([str(i), str(m['a']), str(m['b']),
                                 u.f('length', L, 3),
                                 u.f('force', forces[i], 2, sign=True),
                                 ('tension' if forces[i] >= 0 else 'compression'),
                                 m.get('conn', 'pin')])
                _pdf_table_page(
                    fig, 'Most loaded members',
                    ['bar', 'from', 'to', f'L ({u.lab("length")})',
                     f'N ({u.lab("force")})', 'sense', 'conn'],
                    rows, [0.8, 0.8, 0.8, 1.1, 1.25, 1.4, 1.0],
                    note='Ranked by |N|. No member carries a section yet, so no '
                         'code check could be run — assign profiles to get the '
                         'utilisation schedule here.')
            pdf.savefig(fig)
            plt.close(fig)

        # ── Maximum solicitation ────────────────────────────────────────
        #
        # "Solicitation" as the schedule a designer actually details from:
        # every internal action a rod or a joint carries, side by side, with
        # the ENVELOPE -- the worst of each column and which member owns it
        # -- always printed, because that is the number that sizes the
        # section and the number a reader came to the sheet for.
        if 'solicitation_rods' in plan:
            from apps.stereo import stereo_math as sm_mod
            fig = new_sheet('Maximum solicitation — rods')
            sol = []
            for i, mr in enumerate(member_res):
                pk = sm_mod.member_peak_actions(mr, PDF_DIAGRAM_SAMPLES)
                A = float(members[i].get('A', 0.0) or 0.0)
                sol.append({
                    'i': i,
                    'N': mr.get('N', 0.0),
                    'V': pk['V_max'],
                    'M': pk['M_max'],
                    'T': abs(mr.get('T', 0.0)),
                    'sig': (abs(mr.get('N', 0.0)) / A) if A > 1e-12 else None,
                    'L': mr.get('length_m', 0.0) or 0.0,
                    'util': (checks[i]['util'] if have_checks
                             and i < len(checks) and checks[i].get('checked')
                             else None),
                })
            rank = (lambda r: (r['util'] if r['util'] is not None else -1.0,
                               abs(r['N'])))
            order = sorted(range(len(sol)), key=lambda i: rank(sol[i]),
                           reverse=True)[:26]
            headers = ['bar', 'from', 'to', f'L ({u.lab("length")})',
                       f'N ({u.lab("force")})', f'V ({u.lab("force")})',
                       f'M ({u.lab("moment")})', f'T ({u.lab("moment")})',
                       f'|N|/A ({u.lab("stress")})', 'util']

            def sol_row(r, label=None):
                return [label or str(r['i']),
                        '' if label else str(members[r['i']]['a']),
                        '' if label else str(members[r['i']]['b']),
                        '' if label else u.f('length', r['L'], 3),
                        u.f('force', r['N'], 2, sign=True),
                        u.f('force', r['V'], 2),
                        u.f('moment', r['M'], 3),
                        u.f('moment', r['T'], 3),
                        ('—' if r['sig'] is None
                         else f"{u.stress_from_kn_cm2(r['sig']):.3f}"),
                        ('—' if r['util'] is None else f"{r['util']:.3f}")]

            rows = [sol_row(sol[i]) for i in order]

            def worst(field):
                live = [r for r in sol if r[field] is not None]
                if not live:
                    return None
                return max(live, key=lambda r: abs(r[field]))

            tail = []
            for field, label in (('N', 'axial N'), ('V', 'shear V'),
                                 ('M', 'moment M'), ('T', 'torsion T'),
                                 ('sig', 'stress |N|/A'), ('util', 'utilisation')):
                w = worst(field)
                if w is None or abs(w[field]) <= 1e-12:
                    continue
                quantity = {'N': 'force', 'V': 'force', 'M': 'moment',
                            'T': 'moment'}.get(field)
                if quantity:
                    shown, unit = u.v(quantity, w[field]), u.lab(quantity)
                elif field == 'sig':
                    shown, unit = u.stress_from_kn_cm2(w[field]), u.lab('stress')
                else:
                    shown, unit = w[field], ''
                tail.append([f'MAX {label}',
                             str(members[w['i']]['a']), str(members[w['i']]['b']),
                             u.f('length', w['L'], 3),
                             f'{shown:+.3f} {unit}'.strip() if field == 'N'
                             else f'{shown:.3f} {unit}'.strip(),
                             f"bar {w['i']}", '', '', '', ''])
            _pdf_table_page(
                fig, 'Maximum solicitation of the rods', headers, rows,
                [1.55, 0.7, 0.7, 0.95, 1.1, 1.0, 1.15, 1.15, 1.0, 0.95],
                note='Ranked by utilisation, then by |N|. V and M are the peak '
                     'anywhere ALONG the rod, not only at its ends; a pin-ended '
                     'rod carries neither. MAX rows: the envelope over every rod.',
                tail_rows=tail)
            pdf.savefig(fig)
            plt.close(fig)

        if 'solicitation_nodes' in plan:
            from apps.stereo import stereo_math as sm_mod
            fig = new_sheet('Maximum solicitation — nodes')
            mvec = sm_mod.node_moment_vectors(nodes, members, member_res)
            incident = [[] for _ in nodes]
            for i, m in enumerate(members):
                incident[m['a']].append((i, 'a'))
                incident[m['b']].append((i, 'b'))
            react = results.get('reactions', {}) or {}
            joints = []
            for j in range(len(nodes)):
                mv = mvec.get(j)
                mres = (0.0 if mv is None else
                        (mv['Mx'] ** 2 + mv['My'] ** 2 + mv['Mz'] ** 2) ** 0.5)
                nmax = vmax = 0.0
                for i, end in incident[j]:
                    mr = member_res[i]
                    nmax = max(nmax, abs(mr.get('N', 0.0)))
                    vmax = max(vmax, abs(mr.get(f'Vy_{end}', 0.0)),
                               abs(mr.get(f'Vz_{end}', 0.0)))
                r = react.get(j)
                rmag = (0.0 if r is None else
                        (r.get('Fx', 0.0) ** 2 + r.get('Fy', 0.0) ** 2
                         + r.get('Fz', 0.0) ** 2) ** 0.5)
                joints.append({'j': j, 'deg': len(incident[j]), 'M': mres,
                               'N': nmax, 'V': vmax, 'R': rmag,
                               'sup': r is not None})
            order = sorted(range(len(joints)),
                           key=lambda k: (joints[k]['M'], joints[k]['N']),
                           reverse=True)[:26]
            headers = ['node', f'x, y, z ({u.lab("length")})', 'rods',
                       f'M joint ({u.lab("moment")})',
                       f'max |N| ({u.lab("force")})',
                       f'max |V| ({u.lab("force")})',
                       f'reaction ({u.lab("force")})', 'support']
            rows = []
            for k in order:
                jt = joints[k]
                x, y, z = (u.v('length', c) for c in nodes[jt['j']])
                rows.append([str(jt['j']), f'{x:.2f}, {y:.2f}, {z:.2f}',
                             str(jt['deg']), u.f('moment', jt['M'], 3),
                             u.f('force', jt['N'], 2),
                             u.f('force', jt['V'], 2),
                             (u.f('force', jt['R'], 2) if jt['sup'] else '—'),
                             ('yes' if jt['sup'] else '')])
            tail = []
            # Short labels on purpose: the first column is one column wide,
            # and a label that outruns it prints straight over the next one.
            for field, label, quantity in (('M', 'M joint', 'moment'),
                                           ('N', '|N| rod', 'force'),
                                           ('V', '|V| rod', 'force'),
                                           ('R', 'reaction', 'force')):
                live = [jt for jt in joints if jt[field] > 1e-12]
                if not live:
                    continue
                w = max(live, key=lambda jt: jt[field])
                x, y, z = (u.v('length', c) for c in nodes[w['j']])
                tail.append([f'MAX {label}', f'{x:.2f}, {y:.2f}, {z:.2f}',
                             str(w['deg']), u.fl(quantity, w[field], 3),
                             f"node {w['j']}", '', '', ''])
            _pdf_table_page(
                fig, 'Maximum solicitation of the nodes', headers, rows,
                [0.85, 1.9, 0.75, 1.5, 1.35, 1.35, 1.3, 0.9],
                note='Ranked by the moment the joint transfers. "M joint" is the '
                     'largest resultant end-moment any rigid rod imposes there — '
                     'what a Vierendeel connection is detailed for; a pin joint '
                     'reads 0.00 by definition.',
                tail_rows=tail)
            pdf.savefig(fig)
            plt.close(fig)

        if 'takeoff' in plan:
            # ── Steel take-off ──────────────────────────────────────────
            #
            # What the structure weighs, by section. It is the number a
            # brief is costed from and the one an audience remembers
            # ("this dome is four tonnes"), and it comes free out of data
            # the report already has.
            fig = new_sheet('Steel take-off')
            by_profile = {}
            for i, m in enumerate(members):
                na, nb = nodes[m['a']], nodes[m['b']]
                L = math.dist(na, nb)
                name = (m.get('profile') or '').strip() or '(no profile)'
                A = float(m.get('A', 0.0) or 0.0)
                e = by_profile.setdefault(name, {'n': 0, 'L': 0.0, 'A': A,
                                                 'kg': 0.0, 'mixed': False})
                e['n'] += 1
                e['L'] += L
                # kN/m^3 -> kg/m^3 at standard gravity, so the sheet can
                # report a mass rather than a weight.
                e['kg'] += A * 1e-4 * L * unit_weight * 1000.0 / 9.80665
                if abs(A - e['A']) > 1e-9:
                    e['mixed'] = True       # one name, two section areas

            rows = []
            for name in sorted(by_profile, key=lambda k: -by_profile[k]['kg']):
                e = by_profile[name]
                rows.append([
                    name[:22] + (' *' if e['mixed'] else ''),
                    str(e['n']),
                    ('—' if e['mixed'] else f"{u.v('area', e['A']):.2f}"),
                    u.f('length', e['L'], 2, comma=True),
                    u.f('length', e['L'] / e['n'], 3),
                    f"{e['kg'] / max(e['L'], 1e-9):.2f}",
                    f"{e['kg']:,.1f}",
                ])
            total_L = sum(e['L'] for e in by_profile.values())
            total_kg = sum(e['kg'] for e in by_profile.values())
            tail = [['TOTAL  (kg)', str(len(members)), '',
                     u.f('length', total_L, 2, comma=True), '', '',
                     f'{total_kg:,.1f}'],
                    ['TOTAL  (tonnes)', '', '', '', '', '',
                     f'{total_kg / 1000.0:,.3f}']]
            foot = ''
            if any(e['mixed'] for e in by_profile.values()):
                foot = (' A row marked * groups bars that share a profile '
                        'NAME but not the same area, so its area and mass '
                        'per length are not one number.')
            _pdf_table_page(
                fig, 'Steel take-off, by section',
                ['profile', 'bars', f'A ({u.lab("area")})',
                 f'total L ({u.lab("length")})',
                 f'mean L ({u.lab("length")})', 'kg/m', 'mass (kg)'],
                rows, [2.2, 0.8, 1.1, 1.35, 1.35, 1.0, 1.3],
                # The unit weight through the selector like every other
                # number on the sheet: "78.5 kN/m³" under a US heading was
                # the one quantity the report still printed in SI regardless.
                note=f'Mass from the section area at '
                     f'{u.f("unit_weight", unit_weight, 1)} '
                     f'{u.lab("unit_weight")} — the unit weight the '
                     f'self-weight load case uses, so the two cannot disagree. Bars with no '
                     f'section contribute none. kg whatever the '
                     f'convention: mass is not a converted quantity.{foot}',
                tail_rows=tail)
            pdf.savefig(fig)
            plt.close(fig)
    return sheet[0]


# ── one document, a section per group ─────────────────────────────────────
#
# Roadmap v2 4.1's report. The branches of the model (stereo_groups) each get
# the same sheets a selection report gets -- by the same code, export_pdf on
# a submodel -- in ONE document, behind two sheets only a grouped model has:
# a summary of every group, with the check that the groups account for the
# model exactly once, and the joints where groups meet, with the force each
# side hands across. Every group section is a VIEW of the one whole-model
# solve, never a re-solve of the branch cut free: a branch on its own is a
# different structure, usually a mechanism (see stereo_groups).

def report_plan(members, results=None, checks=None, groups=None,
                ortho_views=True):
    """The sheet keys export_pdf will write for this model -- its own rule,
    so a document that holds several reports can number them in advance."""
    n_rigid = sum(1 for m in members if m.get('conn') == 'rigid')
    want = set(PDF_SHEET_GROUPS if groups is None else groups)
    if not ortho_views:
        want.discard('views')
    return plan_sheets(results, checks, n_rigid, want)


def group_report_order(branch_groups, n_members, gids=None,
                       include_ungrouped=True):
    """[(gid, name, level, rods)] in the order the document gives them.

    The tree's own order, each group with its subtree's rods (so a parent's
    section shows the whole branch), then Ungrouped when it has rods: the
    rods nobody assigned are part of the structure too, and a document that
    left them out would not add up. `gids` limits it to some groups -- the
    "PDF of this group" action passes one.
    """
    from apps.stereo import stereo_groups as sgp
    out = []
    for g, lvl in sgp.walk(branch_groups):
        if gids is not None and g['id'] not in gids:
            continue
        rods = sgp.rods_of(branch_groups, g['id'], deep=True)
        if rods:
            out.append((g['id'], g['name'], lvl, rods))
    if include_ungrouped and gids is None:
        rest = sgp.ungrouped_rods(branch_groups, n_members)
        if rest:
            out.append((None, sgp.UNGROUPED_NAME, 0, rest))
    return out


# Rows of the joints table per sheet. The table sheet fits thirty
# under its three-line note; a joint's rows are never split across two
# sheets, so a sheet may carry a few fewer.
PDF_JOINT_ROWS_PER_SHEET = 30


def _joint_table_rows(shared, u):
    """[[rows of one joint], ...] -- a block per joint, one row per side."""
    blocks = []
    for r in shared:
        block = []
        for k, side in enumerate(r['sides']):
            rods_txt = ','.join(str(i) for i in side['rods'])
            has_f = 'F' in side
            block.append([
                r['node'] if k == 0 else '',
                r['kind'].upper() if k == 0 else '',
                side['name'][:22],
                rods_txt[:22] + ('…' if len(rods_txt) > 22 else ''),
                u.f('force', side['Fx'], 2, sign=True) if has_f else '—',
                u.f('force', side['Fy'], 2, sign=True) if has_f else '—',
                u.f('force', side['Fz'], 2, sign=True) if has_f else '—',
                u.f('force', side['F'], 2) if has_f else '—'])
        blocks.append(block)
    return blocks


def _paginate_blocks(blocks, per_sheet=PDF_JOINT_ROWS_PER_SHEET):
    """Pack whole blocks into sheets of at most `per_sheet` rows. A block
    longer than a sheet gets one to itself (the table marks the overflow)."""
    pages, cur = [], []
    for b in blocks:
        if cur and len(cur) + len(b) > per_sheet:
            pages.append(cur)
            cur = []
        cur = cur + b
    if cur or not pages:
        pages.append(cur)
    return pages


def export_groups_pdf(nodes, members, loads, supports, results, path,
                      branch_groups, checks=None, meta=None, gids=None,
                      az_deg=30, el_deg=25, groups=None, ortho_views=False,
                      unit_weight_kN_m3=None,
                      deflection_denom=PDF_DEFLECTION_DENOM):
    """The grouped model as ONE document: summary, shared joints, and then a
    section per group -- or per group in `gids` -- built by export_pdf.

    `groups` picks the sheets each section carries, as for export_pdf;
    `ortho_views` defaults off here because five orthographic sheets per
    branch make a long document, and the summary and joint sheets are what
    a grouped report is for. Sheets are numbered across the whole document.
    Returns the list of (title, first sheet) for every part, which is also
    what the summary sheet prints as its contents.
    """
    from common import _ensure_matplotlib
    if not _ensure_matplotlib():
        raise RuntimeError('matplotlib is required for PDF export.')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from apps.stereo import stereo_groups as sgp
    from apps.stereo import stereo_math as _sm

    u = ReportUnits()
    unit_weight = (_sm.DEFAULT_STEEL_UNIT_WEIGHT if unit_weight_kN_m3 is None
                   else float(unit_weight_kN_m3))
    member_res = (results or {}).get('member_res') if results else None
    order = group_report_order(branch_groups, len(members), gids=gids)
    if not order:
        raise ValueError('No group with any rods to report.')

    # Every section is cut from the model first, so its sheet count is known
    # before the first sheet is drawn and "Sheet n / N" is true throughout.
    sections = []
    for gid, name, lvl, rods in order:
        sub = submodel(nodes, members, loads, supports, results, checks,
                       member_idx=rods)
        n = len(report_plan(sub[1], sub[4], sub[5], groups, ortho_views))
        sections.append((gid, name, lvl, rods, sub, n))
    # The joints table runs over as many sheets as it needs: a joint left
    # off the list is a connection nobody details, which is the failure
    # that sheet exists to prevent. Worked out now, for the numbering.
    shared = sgp.shared_node_rows(branch_groups, nodes, members, member_res)
    wanted = {gid for gid, *_ in order}
    if gids is not None:
        shared = [r for r in shared
                  if any(sd['group'] in wanted for sd in r['sides'])]
    joint_pages = _paginate_blocks(_joint_table_rows(shared, u))
    head = 1 + len(joint_pages)   # summary, then the joints
    total = head + sum(s[5] for s in sections)

    sheet_meta = _pdf_sheet_meta(nodes, members, meta, u=u)
    contents = [('Groups — summary', 1), ('Joints shared between groups', 2)]
    first_sheet = {}
    at = head + 1
    for gid, name, lvl, rods, sub, n in sections:
        contents.append(('%s%s' % ('   ' * lvl, name), at))
        first_sheet[gid] = at
        at += n

    def page(no, title):
        fig = plt.figure(figsize=PDF_SHEET_IN)
        fig.patch.set_facecolor('white')
        _pdf_sheet(fig, no, total, title, sheet_meta)
        return fig

    with PdfPages(path) as pdf:
        # ── the summary ────────────────────────────────────────────────
        rows_sum = sgp.group_summary(branch_groups, nodes, members, member_res,
                                     checks, unit_weight_kN_m3=unit_weight)
        rows = []
        for r in rows_sum:
            if gids is not None and r['id'] not in wanted:
                continue
            rods = (sgp.rods_of(branch_groups, r['id'], deep=True)
                    if r['id'] is not None
                    else sgp.ungrouped_rods(branch_groups, len(members)))
            secs = sorted({(members[i].get('profile') or '—')
                           for i in rods if 0 <= i < len(members)})
            first = first_sheet.get(r['id'], '')
            rows.append([
                ('  ' * r['level'] + r['name'])[:26],
                r['n_rods'], r['n_nodes'],
                u.f('length', r['length_m']),
                u.f('force', r['weight_kN'], 2),
                '—' if r['worst_util'] is None else '%.2f' % r['worst_util'],
                '—' if r['worst_rod'] is None else r['worst_rod'],
                (', '.join(secs))[:30] + ('…' if len(', '.join(secs)) > 30
                                          else ''),
                first])
        rec = sgp.totals_reconcile(branch_groups, nodes, members,
                                   unit_weight_kN_m3=unit_weight)
        tail = [['every rod once', rec['rods_in_groups'], '', '', '', '', '',
                 '%d in groups + %d ungrouped = %d of %d  %s'
                 % (rec['rods_in_groups'], rec['rods_ungrouped'],
                    rec['rods_counted'], rec['rods_in_model'],
                    'OK' if rec['ok'] else 'DOES NOT ADD UP'), '']]
        fig = page(1, 'Groups — summary')
        _pdf_table_page(
            fig, 'Groups — summary and contents',
            ['group', 'rods', 'nodes', f'length ({u.lab("length")})',
             f'weight ({u.lab("force")})', 'worst', 'at rod', 'sections',
             'sheet'],
            rows, [2.6, 0.6, 0.6, 1.1, 1.1, 0.6, 0.7, 2.6, 0.5],
            note='A parent\'s row includes its subgroups, so the rows do not '
                 'sum to the model; the last line is the check that does: '
                 'every rod counted exactly once, in its own group or in '
                 'Ungrouped. Each group\'s section is a view of the one '
                 'whole-model solve -- a branch cut free would be a '
                 'different structure.',
            tail_rows=tail)
        pdf.savefig(fig)
        plt.close(fig)

        # ── the joints between them ────────────────────────────────────
        n_cross = sum(1 for r in shared if r['kind'] == 'cross')
        for k, body in enumerate(joint_pages):
            title = 'Joints shared between groups'
            if len(joint_pages) > 1:
                title += ' (%d of %d)' % (k + 1, len(joint_pages))
            fig = page(2 + k, title)
            _pdf_table_page(
                fig, title,
                ['node', 'kind', 'group', 'its rods at the joint',
                 f'Fx ({u.lab("force")})', f'Fy ({u.lab("force")})',
                 f'Fz ({u.lab("force")})', f'|F| ({u.lab("force")})'],
                body or [['—', '', 'no joint is shared between groups', '',
                          '', '', '', '']],
                [0.6, 0.8, 2.0, 2.2, 1.0, 1.0, 1.0, 1.0],
                note='Every joint two groups meet at, with the force each '
                     'side\'s rods pull on it (axial, from the whole-model '
                     'solve) -- what the connection there is detailed from. '
                     'CROSS joints join separate branches and come first; '
                     'INTERNAL ones join a group to its own subgroup, still a '
                     'joint to detail if the subgroup is fabricated apart. '
                     'Ungrouped counts as a branch.',
                tail_rows=[['', '', '%d joint(s): %d cross, %d internal'
                            % (len(shared), n_cross, len(shared) - n_cross),
                            '', '', '', '', '']])
            pdf.savefig(fig)
            plt.close(fig)

        # ── a section per group ────────────────────────────────────────
        base = head
        for gid, name, lvl, rods, sub, n in sections:
            s_nodes, s_members, s_loads, s_supports, s_res, s_checks, _ = sub
            g_meta = dict(meta or {})
            g_meta['group'] = name
            g_meta['subset_of'] = (meta or {}).get('grid_family') or 'model'
            written = export_pdf(
                s_nodes, s_members, s_loads, s_supports, s_res, None,
                checks=s_checks, meta=g_meta, az_deg=az_deg, el_deg=el_deg,
                ortho_views=ortho_views, groups=groups,
                deflection_denom=deflection_denom,
                unit_weight_kN_m3=unit_weight_kN_m3,
                into=pdf, sheet_base=base, sheet_total=total)
            if written != n:
                # The contents and every "Sheet n / N" were numbered from n.
                raise RuntimeError('section %r wrote %d sheets, planned %d'
                                   % (name, written, n))
            base += n
    return contents
