"""
perforated_beam_excel.py — whole-model Excel export/import for the
Perforated Beam tab.

This is the only tab that had no Excel round-trip, which mattered more
here than elsewhere: a cellular beam carries a drawn profile, a support
list, an opening layout and a load set, and re-entering all of it by hand
to change one number is the slowest thing about the tab.

FORMAT. A 'Model' sheet of `[BRACKETED]` blocks, each a header row
followed by data rows, exactly as the Beam, Arch and Cable tabs already
write. Blocks are located BY NAME and columns BY HEADER, never by row
number, so inserting a block or a column does not break an older file.
An unknown block is ignored and a missing one falls back to its default,
which is what lets a hand-written sheet carry only what it wants to say.

UNITS follow the tab and the drawings: positions ALONG the beam in metres
(a 50 400 mm span with supports at 16 200 mm reads as noise), everything
about the SECTION in mm, forces in N, stresses in MPa. Every column
header names its unit.

THE STATE DICT is the interchange type -- plain JSON-able values, except
`openings` (OpeningInstance) and `compound_welds` (WeldLine), which are
the app's own objects and are converted here. `export_state` and
`import_state` are pure functions of it, so the whole round-trip is
testable without a display.

OPENING SHAPES are stored parametrically -- 'Circle, 1350 mm' rather than
48 vertices -- and are recognised by RECONSTRUCTION: guess the
parameters, rebuild with the real constructor, and accept only if every
vertex matches. A shape that fails to match is written out as an explicit
vertex list instead. So the stored description is never a guess about
what the user meant; it either regenerates the polygon exactly or it
isn't used.
"""
import json

from apps.perforated_beam import perforated_beam_math as pbm
from apps.perforated_beam import hyperstatic_math as hym
from apps.perforated_beam import welded_section_math as wsm
from apps.perforated_beam import section_profile_math as secm

# Vertex match tolerance for shape recognition, in mm. The candidate is
# built by the same constructor from parameters read off the polygon
# itself, so agreement is to floating-point noise or not at all; 1e-7 mm
# is a tenth of an angstrom and cannot admit a shape that merely looks
# similar.
SHAPE_TOL = 1e-7

# openpyxl rejects a cell string longer than this, so long JSON payloads
# (a drawn profile with many segments) are split across numbered rows.
CELL_CHARS = 30000

BASE_PREFIXES = ('dp_a', 'dp_b', 'cp_a', 'cp_b')
IBEAM_KEYS = ('d', 'bf', 'tf', 'tw')
CHANNEL_KEYS = ('h', 'bf', 'tf', 'tw')


def default_state():
    """Every field the app round-trips, at the value a fresh tab has.

    Import starts from this and overwrites only what the workbook
    actually contains, so a sheet holding nothing but a span and a load
    set is a valid input rather than an error."""
    return {
        'length': 8000.0,
        'Fy': 250.0,
        'E': 200000.0,
        'Lb': 0.0,
        'Cb': 1.0,
        'load_on_top_flange': False,
        'stiffener_spacing': None,
        'section_mode': 'catalog',
        'catalog': {'section': 'IPE 400', 'rotate90': False, 'mirror': False},
        'custom_ibeam': {'d': '', 'bf': '', 'tf': '', 'tw': '',
                         'rotate90': False, 'mirror': False},
        'double_channel': {'channel': 'UPN 220', 'overall_width': 350.0,
                           'custom': {k: '' for k in CHANNEL_KEYS}},
        'double_profile': {'gap': 200.0},
        'bases': {p: _default_base() for p in BASE_PREFIXES},
        'compound_offsets': {'cp_a': (0.0, 0.0), 'cp_b': (0.0, 0.0)},
        'assembly': {'kind': 'none', 'plate_t': 0.0},
        'compound_welds': [],
        'support_mode': 'simple',
        'supports': None,
        'support_specs': [],
        'openings': [],
        'loads': [],
        'main_sketch': None,
        # New in 2026-09-10. Both default to the behaviour every
        # workbook written before then had, so an old file imports
        # unchanged.
        'load_combination': 'as_entered',
        'vierendeel_method': 'station',
    }


def _default_base():
    return {'kind': 'catalog', 'section': 'IPE 400', 'channel': 'UPN 220',
            'ibeam': {k: '' for k in IBEAM_KEYS},
            'channel_dims': {k: '' for k in CHANNEL_KEYS},
            'rotate90': False, 'mirror': False, 'sketch': None}


# ─────────────────────────────────────────────────────────────────────────
# Opening shapes: parametric where possible, explicit vertices otherwise
# ─────────────────────────────────────────────────────────────────────────

def _matches(verts, candidate):
    return (len(verts) == len(candidate)
            and all(abs(a[0] - b[0]) < SHAPE_TOL and abs(a[1] - b[1]) < SHAPE_TOL
                    for a, b in zip(verts, candidate)))


def describe_shape(verts):
    """(shape, p1, p2, p3, n_vertices, polygon_text) for one opening.

    Recognition is by reconstruction: the parameters are read off the
    polygon, the real constructor is called with them, and the result
    must match vertex for vertex. Anything else is written out as an
    explicit vertex list -- correct for every polygon, at the cost of a
    long cell."""
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    w, h, n = max(xs) - min(xs), max(ys) - min(ys), len(verts)

    if n >= 8 and _matches(verts, pbm.opening_circle(w, n=n)):
        return ('Circle', w, 0.0, 0.0, n, '')
    if n == 4 and _matches(verts, pbm.opening_rectangle(w, h)):
        return ('Rectangle', w, h, 0.0, n, '')
    if n == 6:
        # opening_hexagon lays out [(-e,H),(e,H),(W,0),(e,-H),(-e,-H),(-W,0)],
        # so the top flat's own width is the flat_width parameter.
        flat = verts[1][0] - verts[0][0]
        if _matches(verts, pbm.opening_hexagon(w, h, flat)):
            return ('Hexagon', w, h, flat, n, '')
    return ('Custom polygon', 0.0, 0.0, 0.0, n,
            '; '.join(f'{x:g},{y:g}' for x, y in verts))


def build_shape(shape, p1, p2, p3, n, polygon_text):
    """Inverse of describe_shape -- the same constructors the UI calls."""
    if shape == 'Circle':
        return pbm.opening_circle(float(p1), n=int(n) if n else 48)
    if shape == 'Rectangle':
        return pbm.opening_rectangle(float(p1), float(p2))
    if shape == 'Hexagon':
        return pbm.opening_hexagon(float(p1), float(p2), float(p3) if p3 else None)
    if shape == 'Custom polygon':
        pts = []
        for pair in str(polygon_text or '').replace('\n', ';').split(';'):
            pair = pair.strip()
            if not pair:
                continue
            x_str, y_str = pair.split(',')
            pts.append((float(x_str), float(y_str)))
        return pbm.opening_polygon(pts)
    raise ValueError(f'Unknown opening shape {shape!r}. Use Circle, Hexagon, '
                     f'Rectangle or Custom polygon.')


# ─────────────────────────────────────────────────────────────────────────
# Writing
# ─────────────────────────────────────────────────────────────────────────

def _mm_to_m(v):
    return float(v) / 1000.0


def _m_to_mm(v):
    return float(v) * 1000.0


class _Writer:
    """Bracketed-block writer. Tracks the row so each block just declares
    its header and rows."""

    def __init__(self, ws, font_bold):
        self.ws, self.row, self._bold = ws, 1, font_bold

    def title(self, text):
        c = self.ws.cell(row=self.row, column=1, value=text)
        c.font = self._bold
        self.row += 2

    def block(self, name, headers, rows):
        self.ws.cell(row=self.row, column=1, value=f'[{name}]')
        self.row += 1
        for col, label in enumerate(headers, 1):
            self.ws.cell(row=self.row, column=col, value=label)
        self.row += 1
        for r in rows:
            for col, value in enumerate(r, 1):
                if value is not None:
                    self.ws.cell(row=self.row, column=col, value=value)
            self.row += 1
        self.row += 1


def _chunks(text):
    return [text[i:i + CELL_CHARS] for i in range(0, len(text), CELL_CHARS)] or ['']


def export_state(state, path, report=None, beam=None):
    """Write `state` (and, when given, the results of the run that
    produced it) to an .xlsx at `path`."""
    import openpyxl
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    st = dict(default_state(), **state)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    w = _Writer(wb.create_sheet('Model'), Font(bold=True, size=11, color='1F4E79'))
    w.title('PERFORATED BEAM MODEL — for Import Excel '
            '(blocks are found by name and columns by header, so you may reorder or omit them)')

    w.block('GEOMETRY',
            ['length_m', 'Fy_MPa', 'E_MPa', 'Lb_mm', 'Cb', 'load_on_top_flange',
             'stiffener_spacing_mm', 'load_combination', 'vierendeel_method'],
            [[_mm_to_m(st['length']), st['Fy'], st['E'], st['Lb'], st['Cb'],
              bool(st['load_on_top_flange']),
              st.get('stiffener_spacing') or None,
              st.get('load_combination') or 'as_entered',
              st.get('vierendeel_method') or 'station']])

    w.block('SECTION_MODE', ['mode'], [[st['section_mode']]])

    cat = st['catalog']
    w.block('CATALOG', ['section', 'rotate90', 'mirror'],
            [[cat['section'], bool(cat['rotate90']), bool(cat['mirror'])]])

    ci = st['custom_ibeam']
    w.block('CUSTOM_IBEAM', ['d_mm', 'bf_mm', 'tf_mm', 'tw_mm', 'rotate90', 'mirror'],
            [[_num_or_blank(ci.get(k)) for k in IBEAM_KEYS]
             + [bool(ci.get('rotate90')), bool(ci.get('mirror'))]])

    dc = st['double_channel']
    w.block('DOUBLE_CHANNEL',
            ['channel', 'overall_width_mm', 'h_mm', 'bf_mm', 'tf_mm', 'tw_mm'],
            [[dc['channel'], dc['overall_width']]
             + [_num_or_blank(dc.get('custom', {}).get(k)) for k in CHANNEL_KEYS]])

    w.block('DOUBLE_PROFILE', ['gap_mm'], [[st['double_profile']['gap']]])

    base_rows = []
    for p in BASE_PREFIXES:
        b = dict(_default_base(), **st['bases'].get(p, {}))
        base_rows.append(
            [p, b['kind'], b['section'], b['channel']]
            + [_num_or_blank(b.get('ibeam', {}).get(k)) for k in IBEAM_KEYS]
            + [_num_or_blank(b.get('channel_dims', {}).get(k)) for k in CHANNEL_KEYS]
            + [bool(b['rotate90']), bool(b['mirror'])])
    w.block('BASE_PROFILES',
            ['profile', 'kind', 'section', 'channel',
             'd_mm', 'bf_mm', 'tf_mm', 'tw_mm',
             'ch_h_mm', 'ch_bf_mm', 'ch_tf_mm', 'ch_tw_mm', 'rotate90', 'mirror'],
            base_rows)

    w.block('COMPOUND_OFFSETS', ['profile', 'dx_mm', 'dy_mm'],
            [[p, float(st['compound_offsets'].get(p, (0.0, 0.0))[0]),
              float(st['compound_offsets'].get(p, (0.0, 0.0))[1])]
             for p in ('cp_a', 'cp_b')])

    w.block('ASSEMBLY', ['kind', 'plate_t_mm'],
            [[st['assembly']['kind'], float(st['assembly']['plate_t'])]])

    w.block('COMPOUND_WELDS',
            ['label', 'x1_mm', 'y1_mm', 'x2_mm', 'y2_mm', 'leg_mm', 'n_lines',
             'side', 't_thicker_mm', 't_thinner_mm', 'flange_to_web'],
            [[wl.label, wl.p1[0], wl.p1[1], wl.p2[0], wl.p2[1], wl.leg,
              wl.n_lines, wl.side, wl.t_thicker, wl.t_thinner, bool(wl.flange_to_web)]
             for wl in st['compound_welds']])

    sup = st['supports']
    w.block('SUPPORT_MODE', ['mode', 'xA_m', 'xB_m'],
            [[st['support_mode'],
              _mm_to_m(sup[0]) if sup else None,
              _mm_to_m(sup[1]) if sup else None]])

    w.block('SUPPORTS', ['x_m', 'kind', 'torsion_restrained'],
            [[_mm_to_m(s['x']), s['kind'], bool(s['torsion'])]
             for s in st['support_specs']])

    op_rows = []
    for op in st['openings']:
        shape, p1, p2, p3, n, poly = describe_shape(op.vertices_local)
        op_rows.append([op.label, _mm_to_m(op.x_center), shape,
                        p1 or None, p2 or None, p3 or None, n, poly or None])
    w.block('OPENINGS',
            ['label', 'x_center_m', 'shape', 'p1_mm', 'p2_mm', 'p3_mm',
             'n_vertices', 'polygon_mm'],
            op_rows)

    w.block('LOADS',
            ['type', 'x1_m', 'x2_m', 'v1', 'v2', 'e_mm', 'case'],
            [[ld['type'], _mm_to_m(ld['x1']),
              _mm_to_m(ld['x2']) if 'x2' in ld else None,
              ld.get('v1'), ld.get('v2'), ld.get('e'),
              ld.get('case') or 'L']
             for ld in st['loads']])

    sketch_rows = []
    for owner, text in [('main', st.get('main_sketch'))] + \
            [(p, st['bases'].get(p, {}).get('sketch')) for p in BASE_PREFIXES]:
        if text:
            for i, part in enumerate(_chunks(text)):
                sketch_rows.append([owner, i, part])
    w.block('SKETCHES', ['owner', 'part', 'json'], sketch_rows)

    ws = wb['Model']
    for col in range(1, 15):
        ws.column_dimensions[get_column_letter(col)].width = 15

    if report is not None and beam is not None:
        _write_results(wb, beam, report, Font, get_column_letter)

    wb.save(path)


def _num_or_blank(v):
    """A dimension entry the user has left empty stays empty rather than
    becoming 0 -- the app reads '' as "not given" and falls back to the
    catalog, and a 0 there would be a real (invalid) dimension."""
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _write_results(wb, beam, report, Font, get_column_letter):
    """A read-only record of the run: reactions, member check, the
    governing opening and post, and the station tables."""
    ws = wb.create_sheet('Results')
    ws.cell(row=1, column=1, value='PERFORATED BEAM RESULTS — read-only; '
                                   'Import Excel reads the Model sheet only') \
        .font = Font(bold=True, size=11, color='1F4E79')
    r = 3

    ws.cell(row=r, column=1, value='Reactions').font = Font(bold=True)
    r += 1
    for col, label in enumerate(['x_m', 'R_up_N', 'M_ccw_Nmm'], 1):
        ws.cell(row=r, column=col, value=label)
    r += 1
    for x, R, M in report['support_reactions']:
        ws.cell(row=r, column=1, value=_mm_to_m(x))
        ws.cell(row=r, column=2, value=R)
        ws.cell(row=r, column=3, value=M)
        r += 1
    r += 1

    # `member` is None for anything that is not a RolledSection -- Chapter
    # F needs Zx and a compactness class, Chapter G an identifiable web,
    # and member_check declines to guess at either for a drawn or built-up
    # shape. Say so in the sheet rather than leaving a reader to wonder
    # why the block is missing.
    m = report.get('member')
    ws.cell(row=r, column=1, value='Member check (gross section)').font = Font(bold=True)
    r += 1
    if m is None:
        ws.cell(row=r, column=1,
                value='not evaluated — Cap. F/G member check applies to rolled '
                      'I-sections only; the opening and web-post checks below '
                      'are unaffected')
        r += 2
    else:
        for label, value in (('Mu_Nmm', m.Mu), ('x_Mu_m', _mm_to_m(m.x_Mu)),
                             ('Vu_N', m.Vu), ('x_Vu_m', _mm_to_m(m.x_Vu)),
                             ('util_flexure', m.util_flexure),
                             ('util_shear', m.util_shear),
                             ('util', m.util), ('governing', m.governing)):
            ws.cell(row=r, column=1, value=label)
            ws.cell(row=r, column=2, value=value)
            r += 1
        r += 1

    go = report.get('governing_opening')
    if go is not None and go['governing'] is not None:
        g = go['governing']
        ws.cell(row=r, column=1, value='Governing opening').font = Font(bold=True)
        r += 1
        for label, value in (('label', go['opening'].label),
                             ('x_center_m', _mm_to_m(go['opening'].x_center)),
                             ('x_station_m', _mm_to_m(g.x)),
                             ('util_top', g.util_top), ('util_bot', g.util_bot)):
            ws.cell(row=r, column=1, value=label)
            ws.cell(row=r, column=2, value=value)
            r += 1
        r += 1

    gw = report.get('governing_webpost')
    if gw is not None:
        ws.cell(row=r, column=1, value='Governing web post').font = Font(bold=True)
        r += 1
        for label, value in (('x_left_m', _mm_to_m(gw.x_left)),
                             ('x_right_m', _mm_to_m(gw.x_right)),
                             ('width_mm', gw.width), ('tau_demand_MPa', gw.tau_demand),
                             ('Fcr_MPa', gw.Fcr), ('util', gw.util)):
            ws.cell(row=r, column=1, value=label)
            ws.cell(row=r, column=2, value=value)
            r += 1
        r += 1

    ws.cell(row=r, column=1, value='Per-opening governing station').font = Font(bold=True)
    r += 1
    for col, label in enumerate(['label', 'x_center_m', 'util_top', 'util_bot', 'warnings'], 1):
        ws.cell(row=r, column=col, value=label)
    r += 1
    for rep in report['openings']:
        g = rep['governing']
        ws.cell(row=r, column=1, value=rep['opening'].label)
        ws.cell(row=r, column=2, value=_mm_to_m(rep['opening'].x_center))
        if g is not None:
            ws.cell(row=r, column=3, value=g.util_top)
            ws.cell(row=r, column=4, value=g.util_bot)
        ws.cell(row=r, column=5, value='; '.join(rep.get('warnings') or []) or None)
        r += 1
    r += 1

    ws.cell(row=r, column=1, value='Web posts').font = Font(bold=True)
    r += 1
    for col, label in enumerate(['x_left_m', 'x_right_m', 'width_mm', 'tau_MPa', 'Fcr_MPa', 'util'], 1):
        ws.cell(row=r, column=col, value=label)
    r += 1
    for wp in report['webposts']:
        for col, value in enumerate([_mm_to_m(wp.x_left), _mm_to_m(wp.x_right),
                                     wp.width, wp.tau_demand, wp.Fcr, wp.util], 1):
            ws.cell(row=r, column=col, value=value)
        r += 1
    r += 1

    xs, v = pbm.deflection_profile(beam, n=201)
    ws.cell(row=r, column=1, value='Deflection profile (positive = downward)').font = Font(bold=True)
    r += 1
    ws.cell(row=r, column=1, value='x_m')
    ws.cell(row=r, column=2, value='deflection_mm')
    r += 1
    for xi, vi in zip(xs, v):
        ws.cell(row=r, column=1, value=_mm_to_m(xi))
        ws.cell(row=r, column=2, value=vi)
        r += 1

    for col in range(1, 7):
        ws.column_dimensions[get_column_letter(col)].width = 16


# ─────────────────────────────────────────────────────────────────────────
# Reading
# ─────────────────────────────────────────────────────────────────────────

def _as_bool(v, default=False):
    if v is None or v == '':
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ('1', 'true', 'yes', 'y', 'si', 'sí', 'x')


def _as_float(v, default=0.0):
    if v is None or v == '':
        return default
    return float(v)


class _Reader:
    """Bracketed-block reader. Blocks are found by name, columns by
    header -- so a workbook that gained a block, or lost one, still
    reads."""

    def __init__(self, rows):
        self.rows = rows

    def block(self, name):
        """-> list of {header: value} dicts, empty if the block is absent."""
        tag = f'[{name}]'
        start = None
        for i, row in enumerate(self.rows):
            if row and isinstance(row[0], str) and row[0].strip() == tag:
                start = i
                break
        if start is None or start + 1 >= len(self.rows):
            return []
        headers = [h for h in self.rows[start + 1] if h is not None]
        out = []
        i = start + 2
        while i < len(self.rows):
            row = self.rows[i]
            if not row or row[0] is None or str(row[0]).startswith('['):
                break
            out.append({headers[j]: (row[j] if j < len(row) else None)
                        for j in range(len(headers))})
            i += 1
        return out

    def one(self, name):
        rows = self.block(name)
        return rows[0] if rows else {}


# The combination keys a workbook may name. Kept as a plain tuple here
# rather than imported from load_combinations so that the Excel layer
# stays a pure format layer -- it validates the spelling, and the
# module that owns the factors resolves the meaning.
LOAD_COMBINATION_KEYS = ('as_entered', 'lrfd_12d16l', 'lrfd_14d', 'asd_dl')


def import_state(path):
    """Read a 'Model' sheet written by export_state and return a state
    dict. Raises ValueError with a message meant for a dialog."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    if 'Model' not in wb.sheetnames:
        raise ValueError('This workbook has no "Model" sheet — it was not '
                         'exported by the Perforated Beam tab.')
    rd = _Reader(list(wb['Model'].iter_rows(values_only=True)))
    st = default_state()

    g = rd.one('GEOMETRY')
    if not g:
        raise ValueError('Missing [GEOMETRY] block — at least the span is needed.')
    st['length'] = _m_to_mm(_as_float(g.get('length_m'), 8.0))
    st['Fy'] = _as_float(g.get('Fy_MPa'), 250.0)
    st['E'] = _as_float(g.get('E_MPa'), 200000.0)
    st['Lb'] = _as_float(g.get('Lb_mm'), 0.0)
    st['Cb'] = _as_float(g.get('Cb'), 1.0) or 1.0
    st['load_on_top_flange'] = _as_bool(g.get('load_on_top_flange'))
    # Blank means UNSTIFFENED, which is not the same as 0 -- a 0 spacing
    # would be a stiffener every nowhere. None is the honest empty value.
    a = g.get('stiffener_spacing_mm')
    st['stiffener_spacing'] = float(a) if a not in (None, '') and float(a) > 0 else None
    # Unknown or absent falls back to the pre-2026-09-10 behaviour rather
    # than raising: a stale key in a hand-edited workbook must not stop the
    # model from opening.
    combo = str(g.get('load_combination') or '').strip()
    st['load_combination'] = combo if combo in LOAD_COMBINATION_KEYS else 'as_entered'
    meth = str(g.get('vierendeel_method') or '').strip().lower()
    st['vierendeel_method'] = meth if meth in ('station', 'hand') else 'station'

    sm = rd.one('SECTION_MODE')
    if sm.get('mode'):
        st['section_mode'] = str(sm['mode']).strip()

    cat = rd.one('CATALOG')
    if cat:
        st['catalog'] = {'section': str(cat.get('section') or 'IPE 400'),
                         'rotate90': _as_bool(cat.get('rotate90')),
                         'mirror': _as_bool(cat.get('mirror'))}

    ci = rd.one('CUSTOM_IBEAM')
    if ci:
        st['custom_ibeam'] = {k: _blank_or_str(ci.get(f'{k}_mm')) for k in IBEAM_KEYS}
        st['custom_ibeam']['rotate90'] = _as_bool(ci.get('rotate90'))
        st['custom_ibeam']['mirror'] = _as_bool(ci.get('mirror'))

    dc = rd.one('DOUBLE_CHANNEL')
    if dc:
        st['double_channel'] = {
            'channel': str(dc.get('channel') or 'UPN 220'),
            'overall_width': _as_float(dc.get('overall_width_mm'), 350.0),
            'custom': {k: _blank_or_str(dc.get(f'{k}_mm')) for k in CHANNEL_KEYS}}

    dp = rd.one('DOUBLE_PROFILE')
    if dp:
        st['double_profile'] = {'gap': _as_float(dp.get('gap_mm'), 200.0)}

    for row in rd.block('BASE_PROFILES'):
        p = str(row.get('profile') or '').strip()
        if p not in BASE_PREFIXES:
            continue
        st['bases'][p] = {
            'kind': str(row.get('kind') or 'catalog').strip(),
            'section': str(row.get('section') or 'IPE 400'),
            'channel': str(row.get('channel') or 'UPN 220'),
            'ibeam': {k: _blank_or_str(row.get(f'{k}_mm')) for k in IBEAM_KEYS},
            'channel_dims': {k: _blank_or_str(row.get(f'ch_{k}_mm')) for k in CHANNEL_KEYS},
            'rotate90': _as_bool(row.get('rotate90')),
            'mirror': _as_bool(row.get('mirror')),
            'sketch': None}

    for row in rd.block('COMPOUND_OFFSETS'):
        p = str(row.get('profile') or '').strip()
        if p in st['compound_offsets']:
            st['compound_offsets'][p] = (_as_float(row.get('dx_mm')),
                                         _as_float(row.get('dy_mm')))

    asm = rd.one('ASSEMBLY')
    if asm:
        kind = str(asm.get('kind') or 'none').strip()
        if kind not in ('none', 'open', 'closed'):
            raise ValueError(f'[ASSEMBLY] kind must be none, open or closed; got {kind!r}.')
        st['assembly'] = {'kind': kind, 'plate_t': _as_float(asm.get('plate_t_mm'))}

    welds = []
    for i, row in enumerate(rd.block('COMPOUND_WELDS'), 1):
        welds.append(wsm.WeldLine(
            (_as_float(row.get('x1_mm')), _as_float(row.get('y1_mm'))),
            (_as_float(row.get('x2_mm')), _as_float(row.get('y2_mm'))),
            leg=max(0.0, _as_float(row.get('leg_mm'))),
            n_lines=max(1, int(_as_float(row.get('n_lines'), 1))),
            side=str(row.get('side') or 'auto').strip(),
            label=str(row.get('label') or f'CW{i}'),
            t_thicker=max(0.0, _as_float(row.get('t_thicker_mm'))),
            t_thinner=max(0.0, _as_float(row.get('t_thinner_mm'))),
            flange_to_web=_as_bool(row.get('flange_to_web'))))
    st['compound_welds'] = welds

    smo = rd.one('SUPPORT_MODE')
    if smo:
        st['support_mode'] = str(smo.get('mode') or 'simple').strip()
        xa, xb = smo.get('xA_m'), smo.get('xB_m')
        st['supports'] = ((_m_to_mm(xa), _m_to_mm(xb))
                          if xa not in (None, '') and xb not in (None, '') else None)

    specs = []
    for row in rd.block('SUPPORTS'):
        kind = str(row.get('kind') or hym.PIN).strip().lower()
        if kind not in hym.SUPPORT_KINDS:
            raise ValueError(f'[SUPPORTS] kind must be one of '
                             f'{", ".join(sorted(hym.SUPPORT_KINDS))}; got {kind!r}.')
        specs.append({'x': _m_to_mm(_as_float(row.get('x_m'))), 'kind': kind,
                      'torsion': _as_bool(row.get('torsion_restrained'), True)})
    specs.sort(key=lambda s: s['x'])
    st['support_specs'] = specs
    # An explicit support list is what routes the beam through the
    # stiffness solver, so the two must agree or the imported model is
    # not the one the sheet describes.
    if specs and st['support_mode'] != 'advanced':
        st['support_mode'] = 'advanced'
    if not specs and st['support_mode'] == 'advanced':
        st['support_mode'] = 'simple'

    openings = []
    for i, row in enumerate(rd.block('OPENINGS'), 1):
        shape = str(row.get('shape') or 'Circle').strip()
        try:
            verts = build_shape(shape, _as_float(row.get('p1_mm')),
                                _as_float(row.get('p2_mm')), _as_float(row.get('p3_mm')),
                                _as_float(row.get('n_vertices'), 48),
                                row.get('polygon_mm'))
        except Exception as ex:
            raise ValueError(f'[OPENINGS] row {i}: {ex}') from ex
        openings.append(pbm.OpeningInstance(
            _m_to_mm(_as_float(row.get('x_center_m'))), verts,
            label=str(row.get('label') or f'H{i}')))
    st['openings'] = openings

    loads = []
    for i, row in enumerate(rd.block('LOADS'), 1):
        t = str(row.get('type') or '').strip()
        if t not in ('Point load', 'Point moment', 'Point torque',
                     'Distributed load', 'Distributed torque'):
            raise ValueError(f'[LOADS] row {i}: unknown type {t!r}. Use Point load, '
                             f'Point moment, Point torque, Distributed load or '
                             f'Distributed torque.')
        ld = {'type': t, 'x1': _m_to_mm(_as_float(row.get('x1_m'))),
              'v1': _as_float(row.get('v1'))}
        if t in ('Distributed load', 'Distributed torque'):
            x2 = row.get('x2_m')
            if x2 in (None, ''):
                raise ValueError(f'[LOADS] row {i}: a {t} needs x2_m.')
            ld['x2'] = _m_to_mm(_as_float(x2))
            v2 = row.get('v2')
            ld['v2'] = _as_float(v2, ld['v1']) if v2 not in (None, '') else ld['v1']
        if t in ('Point load', 'Distributed load'):
            ld['e'] = _as_float(row.get('e_mm'))
        # Absent, blank or unrecognised all mean 'L' -- the larger LRFD
        # factor, so an old workbook is over-factored rather than under.
        case = str(row.get('case') or '').strip().upper()
        ld['case'] = case if case in ('D', 'L') else 'L'
        loads.append(ld)
    st['loads'] = loads

    joined = {}
    for row in rd.block('SKETCHES'):
        owner = str(row.get('owner') or '').strip()
        if not owner:
            continue
        joined.setdefault(owner, []).append(
            (int(_as_float(row.get('part'))), str(row.get('json') or '')))
    for owner, parts in joined.items():
        text = ''.join(p for _, p in sorted(parts))
        if not text.strip():
            continue
        try:                                    # fail here, not at Analyze
            secm.deserialize_sketch(text)
        except Exception as ex:
            raise ValueError(f'[SKETCHES] the drawing for {owner!r} could not be '
                             f'read: {ex}') from ex
        if owner == 'main':
            st['main_sketch'] = text
        elif owner in st['bases']:
            st['bases'][owner]['sketch'] = text

    return st


def _blank_or_str(v):
    """Dimension cells round-trip as strings because the widgets behind
    them are StringVars whose empty value means 'use the catalog'."""
    if v is None or v == '':
        return ''
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def sketch_to_section(text, name='custom'):
    """JSON text -> (CustomProfileSection, SectionSketch)."""
    sketch, _meta = secm.deserialize_sketch(text)
    return sketch.to_section(name), sketch


def state_to_json(state):
    """The same state as a JSON string, for tests and for anyone who
    wants the model without a spreadsheet in the way."""
    plain = dict(state)
    plain['openings'] = [{'label': o.label, 'x_center': o.x_center,
                          'vertices_local': [list(v) for v in o.vertices_local]}
                         for o in state['openings']]
    plain['compound_welds'] = [
        {'label': w.label, 'p1': list(w.p1), 'p2': list(w.p2), 'leg': w.leg,
         'n_lines': w.n_lines, 'side': w.side, 't_thicker': w.t_thicker,
         't_thinner': w.t_thinner, 'flange_to_web': w.flange_to_web}
        for w in state['compound_welds']]
    plain['compound_offsets'] = {k: list(v) for k, v in state['compound_offsets'].items()}
    plain['supports'] = list(state['supports']) if state['supports'] else None
    return json.dumps(plain, indent=2)


def sketch_to_text(sketch, meta=None):
    """SectionSketch -> the JSON the SKETCHES block carries. Returns None
    for no sketch, which is what keeps the block empty rather than
    holding the string 'null'."""
    if sketch is None:
        return None
    return secm.serialize_sketch(sketch, meta or {})
