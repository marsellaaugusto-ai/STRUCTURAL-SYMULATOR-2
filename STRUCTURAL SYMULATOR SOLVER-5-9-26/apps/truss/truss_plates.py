"""
truss_plates.py — plate design checks for the Truss/Vierendeel tab.

Two kinds of plate, deliberately kept apart because they are different
features with different physics (see
`REPORTS AND GUIDES/DIAGNOSIS_PLATE_FEATURE_2026-09-06.md`):

  * **gusset** (P-1) — a plate at ONE joint that the members meeting there
    are welded to. It is an ANNOTATION: it never enters the stiffness matrix,
    and adding one cannot change a single analysis result. What it answers is
    "how thick, how big, how much weld".

  * **panel** (P-2) — a plate FILLING a bay, welded all round, carrying that
    bay's shear as a membrane. It is a MEMBER: `truss_math.analyze` assembles
    it and it changes the load path. This module only checks the shear flow
    the solver reports for it.

WHY THIS IS NOT IN `truss_math.py`. That module is the documented C++
migration boundary (`MODULAR_ARCHITECTURE.md`): plain lists and dicts in,
deterministic equilibrium out, no Tkinter, no Excel, no drawing — and no
design code either. A resistance factor is a national-standard policy
decision, not physics, and mixing the two would mean porting CIRSOC along
with the solver. The element math lives there; the verdicts live here.

UNITS — the one thing most likely to be silently wrong here.
The Truss tab works in **kN, kN·m, m, GPa, cm², cm⁴**.
`cirsoc_301` works in **N, N·mm, mm, MPa**.
Every function below converts at its own boundary and says so, and
`tests/test_truss_plates.py` checks one worked joint computed independently
in each unit system against the other.
"""
import math

import cirsoc_301 as cirsoc

# Defaults for CIRSOC work: F-24 structural steel and an E70-class electrode.
# Stated here rather than buried in the UI so a reader can see what a plate
# with no explicit grade is being checked against.
DEFAULT_FY_MPA = 235.0      # F-24
DEFAULT_FU_MPA = 360.0
DEFAULT_FEXX_MPA = 480.0    # E70XX
DEFAULT_E_MPA = 200000.0
DEFAULT_NU = 0.3

# Whitmore's classic 30-degree dispersion half-angle.
WHITMORE_ANGLE_DEG = 30.0


# ═════════════════════════════════════════════════════════════════════════
#  Geometry helpers
# ═════════════════════════════════════════════════════════════════════════

def _member_directions(nodes, rods, node_idx):
    """Unit vectors, in the y-UP frame, pointing from `node_idx` along each
    rod that meets it, with that rod's index."""
    out = []
    for ri, rod in enumerate(rods):
        if rod['a'] == node_idx:
            other = rod['b']
        elif rod['b'] == node_idx:
            other = rod['a']
        else:
            continue
        x0, y0 = nodes[node_idx]
        x1, y1 = nodes[other]
        dx, dy = x1 - x0, -(y1 - y0)          # canvas y-down -> y-up
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        out.append({'rod': ri, 'other': other, 'ux': dx / L, 'uy': dy / L})
    return out


def gusset_outline(nodes, rods, node_idx, landing_m=0.30, margin_m=0.06,
                   px_per_m=None):
    """A simple gusset outline at a joint, in METRES, y-UP, relative to the
    node: each member gets a landing length along its own axis, and the
    outline is the convex hull of those landing points expanded by an edge
    margin.

    This is a drawing and a plate AREA, not a fabrication drawing. It exists
    so the checks below have a defensible plate size to work with and so the
    canvas has something to show; a real gusset is cut to suit clearances
    this tool knows nothing about.
    """
    dirs = _member_directions(nodes, rods, node_idx)
    if not dirs:
        return []
    pts = []
    for d in dirs:
        # a short cross-bar at the landing point, so a single member still
        # produces an area rather than a line
        px, py = d['ux'] * landing_m, d['uy'] * landing_m
        nx, ny = -d['uy'] * margin_m, d['ux'] * margin_m
        pts.append((px + nx, py + ny))
        pts.append((px - nx, py - ny))
    pts.append((0.0, 0.0))
    hull = _convex_hull(pts)
    return _offset_outward(hull, margin_m)


def _convex_hull(pts):
    """Monotone chain. Returns the hull counter-clockwise."""
    p = sorted(set((round(x, 9), round(y, 9)) for x, y in pts))
    if len(p) <= 2:
        return p

    def half(seq):
        out = []
        for q in seq:
            while len(out) >= 2:
                (x1, y1), (x2, y2) = out[-2], out[-1]
                if (x2 - x1) * (q[1] - y1) - (y2 - y1) * (q[0] - x1) > 0:
                    break
                out.pop()
            out.append(q)
        return out

    lower = half(p)
    upper = half(reversed(p))
    return lower[:-1] + upper[:-1]


def _offset_outward(pts, d):
    """Push each hull vertex radially out from the centroid by `d`. Crude,
    but a gusset outline only has to look right and bound a sensible area."""
    if not pts or d <= 0:
        return list(pts)
    cx = sum(x for x, _ in pts) / len(pts)
    cy = sum(y for _, y in pts) / len(pts)
    out = []
    for x, y in pts:
        vx, vy = x - cx, y - cy
        L = math.hypot(vx, vy)
        if L < 1e-12:
            out.append((x, y))
        else:
            out.append((x + vx / L * d, y + vy / L * d))
    return out


def polygon_area(pts):
    """Absolute area of a polygon given as [(x, y), ...]."""
    n = len(pts)
    if n < 3:
        return 0.0
    a = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def whitmore_width(nodes, rods, node_idx, rod_idx, landing_m=0.30,
                   angle_deg=WHITMORE_ANGLE_DEG):
    """Whitmore effective width, in metres, for one member framing into a
    gusset: the force spreads at `angle_deg` either side of the member axis
    over the landing length, so the effective width is 2*l*tan(theta).

    This is the width the member's force is taken to act on when checking the
    plate, and it is why a gusset is checked on an effective section rather
    than on its full width.
    """
    for d in _member_directions(nodes, rods, node_idx):
        if d['rod'] == rod_idx:
            return 2.0 * landing_m * math.tan(math.radians(angle_deg))
    return 0.0


# ═════════════════════════════════════════════════════════════════════════
#  P-1 · gusset checks
# ═════════════════════════════════════════════════════════════════════════

def gusset_checks(nodes, rods, plate, actions, code=cirsoc.CIRSOC_301):
    """Check one gusset plate against the actions its joint carries.

    `actions` is the entry for this node from
    `truss_math.compute_node_design_actions` — the COMPLETE set of member
    forces and moments, not the axial-only vectors, which at a rigid joint
    would understate what the connection has to carry.

    Returns a dict with a per-member table, the plate-level check, and the
    governing utilisation. Every stress is MPa; every force in the input is
    kN.
    """
    node_idx = int(plate.get('node', -1))
    t_mm = float(plate.get('thickness_mm', 10.0))
    Fy = float(plate.get('Fy', DEFAULT_FY_MPA))
    Fu = float(plate.get('Fu', DEFAULT_FU_MPA))
    Fexx = float(plate.get('Fexx', DEFAULT_FEXX_MPA))
    n_lines = int(plate.get('weld_lines', 2))
    landing_m = float(plate.get('landing_m', 0.30))
    detail = connection_detail(plate)

    outline = gusset_outline(nodes, rods, node_idx, landing_m=landing_m)
    area_m2 = polygon_area(outline)

    members = []
    worst = 0.0
    worst_what = 'none'
    has_rigid = False
    for mem in actions.get('members', []):
        ri = mem['rod']
        if mem.get('conn') == 'rigid':
            has_rigid = True
        P_kN = math.hypot(mem['Fx'], mem['Fy'])
        w_m = whitmore_width(nodes, rods, node_idx, ri, landing_m=landing_m)
        # kN and m -> N and mm at this boundary
        area_mm2 = w_m * 1000.0 * t_mm
        sigma = (P_kN * 1e3) / area_mm2 if area_mm2 > 1e-9 else float('inf')
        chk = cirsoc.stress_check(sigma, 0.0, Fy, code)

        # weld: the member force is carried as shear flow along the landing
        weld_len_mm = landing_m * 1000.0
        q_N_per_mm = (P_kN * 1e3) / weld_len_mm if weld_len_mm > 1e-9 else float('inf')
        leg_req = cirsoc.leg_for_shear_flow(q_N_per_mm, Fexx, n_lines, code)
        leg_min = cirsoc.min_fillet_leg(t_mm)
        leg_max = cirsoc.max_fillet_leg(t_mm)
        leg = max(leg_req, leg_min)

        # Block shear: the member tearing a block out of the plate. Uses the
        # connection detail, which is what made this uncheckable before.
        Agv, Anv, Ant, Agt, block_note = block_shear_areas(
            detail, t_mm, landing_m * 1000.0, w_m * 1000.0)
        bs = cirsoc.block_shear_strength(Agv, Anv, Ant, Fy, Fu,
                                          detail['Ubs'], code,
                                          required=P_kN * 1e3)
        # Gusset compression buckling (Thornton). Signed N, not |P|: only a
        # member in compression can buckle the plate.
        gb = gusset_buckling_check(mem.get('N', 0.0), w_m * 1000.0, t_mm,
                                    landing_m * 1000.0, Fy, code)

        members.append({
            'rod': ri, 'other': mem.get('other'), 'conn': mem.get('conn', 'pin'),
            'P_kN': P_kN, 'N_kN': mem.get('N', 0.0), 'M_kNm': mem.get('M', 0.0),
            'whitmore_mm': w_m * 1000.0,
            'sigma_MPa': sigma, 'util': chk.util, 'governing': chk.governing,
            'weld_leg_req_mm': leg_req, 'weld_leg_min_mm': leg_min,
            'weld_leg_max_mm': leg_max, 'weld_leg_mm': leg,
            'weld_leg_feasible': leg <= leg_max + 1e-9,
            'weld_min_length_mm': cirsoc.min_effective_length(leg),
            'block_shear': {'Agv': Agv, 'Anv': Anv, 'Ant': Ant, 'Agt': Agt,
                             'Rd_kN': bs.Rd / 1e3, 'util': bs.util,
                             'governing': bs.governing, 'detail': block_note},
            'buckling': gb,
        })
        if chk.util > worst:
            worst, worst_what = chk.util, 'Whitmore section, rod %d (%s)' % (ri, chk.governing)
        if bs.util > worst:
            worst, worst_what = bs.util, 'block shear, rod %d (%s)' % (ri, bs.governing)
        if gb.get('applies') and gb['util'] > worst:
            worst, worst_what = gb['util'], 'gusset buckling, rod %d (%s)' % (ri, gb['governing'])

    # plate-level: the joint resultant carried across the plate
    R_kN = actions.get('resultant', 0.0)
    gross_mm2 = math.sqrt(max(area_m2, 0.0)) * 1000.0 * t_mm
    tau = (R_kN * 1e3) / gross_mm2 if gross_mm2 > 1e-9 else 0.0
    plate_chk = cirsoc.stress_check(0.0, tau, Fy, code)
    if plate_chk.util > worst:
        worst, worst_what = plate_chk.util, 'plate gross section (%s)' % plate_chk.governing

    if detail['conn_type'] == 'bolted':
        detail_note = ('bolted, %d x %d M%.0f bolts, pitch %.0f mm, gauge %.0f mm, '
                       'end %.0f mm, edge %.0f mm'
                       % (detail['rows'], detail['cols'], detail['bolt_d_mm'],
                          detail['pitch_mm'], detail['gauge_mm'],
                          detail['end_mm'], detail['edge_mm']))
    else:
        detail_note = ('welded, two fillet lines over a %.0f mm landing'
                       % (landing_m * 1000.0))

    notes = []
    if has_rigid:
        notes.append(
            'This joint has rigid (Vierendeel) members, so it also carries '
            'their end moments. The Whitmore check below covers the member '
            'FORCES; the moment column is reported for information and is not '
            'combined into the utilisation.')
    notes.append('Connection detail assumed: ' + detail_note)
    notes.append(cirsoc.BLOCK_SHEAR_AND_BUCKLING_PROVENANCE)

    return {
        'node': node_idx, 'outline_m': outline, 'area_m2': area_m2,
        't_mm': t_mm, 'Fy': Fy, 'Fu': Fu, 'Fexx': Fexx,
        'detail': detail, 'detail_note': detail_note,
        'members': members,
        'resultant_kN': R_kN, 'tau_MPa': tau,
        'plate_util': plate_chk.util,
        'util': worst, 'governing': worst_what,
        'code': code.name, 'notes': notes,
    }


# ═════════════════════════════════════════════════════════════════════════
#  P-1 · block shear and gusset compression buckling
# ═════════════════════════════════════════════════════════════════════════
#
# These two were deliberately NOT checked in the first version of this
# module, because both need a connection detail -- how the member is
# attached, and where -- that the tab did not model. It now does (see
# `connection_detail` below), so they are checked rather than disclaimed.
#
# Read `cirsoc.BLOCK_SHEAR_AND_BUCKLING_PROVENANCE` before trusting the
# numbers: the FORMULAS are AISC 360 J4.3 and E3, which CIRSOC 301-2018
# adopts as its basis, but their two resistance factors are AISC's and have
# not been read off the CIRSOC table the way every other factor in this app
# was. CIRSOC differs from AISC on at least one factor by 25%.

#: Effective-length factor for a gusset treated as a Whitmore-width column.
#: 0.65 is Thornton's value for a gusset supported along two edges, which is
#: the ordinary truss/Vierendeel joint. A gusset free along one edge wants
#: 1.2 and this tool has no way to know which it is looking at, so this is
#: exposed rather than buried.
GUSSET_K = 0.65


def connection_detail(plate):
    """The gusset's connection detail, with defaults, as plain numbers.

    `conn_type` is 'welded' (no holes: net area = gross area) or 'bolted'.
    Bolt layout is rows ACROSS the member (the gauge direction) by cols
    ALONG it (the pitch direction), which is the orientation the block-shear
    geometry below assumes.
    """
    ct = str(plate.get('conn_type', 'welded')).strip().lower()
    if ct not in ('welded', 'bolted'):
        ct = 'welded'
    return {
        'conn_type': ct,
        'bolt_d_mm': float(plate.get('bolt_d_mm', 16.0)),
        'rows': max(int(plate.get('bolt_rows', 2)), 1),
        'cols': max(int(plate.get('bolt_cols', 2)), 1),
        'pitch_mm': float(plate.get('pitch_mm', 60.0)),
        'gauge_mm': float(plate.get('gauge_mm', 60.0)),
        'edge_mm': float(plate.get('edge_mm', 35.0)),
        'end_mm': float(plate.get('end_mm', 40.0)),
        'Ubs': float(plate.get('Ubs', 1.0)),
    }


def block_shear_areas(detail, t_mm, landing_mm, whitmore_mm):
    """(Agv, Anv, Ant, Agt) in mm^2 for one member's block-shear failure
    path through the gusset, plus a description of the block assumed.

    BOLTED: the block tears out along two shear planes running from the free
    edge past every bolt in the pitch direction, and one tension plane across
    the outermost bolt lines.

        Lv  = end distance + (cols - 1) * pitch          (per shear plane)
        Agv = 2 * t * Lv
        Anv = 2 * t * (Lv - (cols - 0.5) * hole)         (the last hole is
                                                          half-cut by the edge)
        Wt  = (rows - 1) * gauge                          (tension width)
        Ant = t * (Wt - (rows - 1) * hole)

    WELDED: there are no holes, so net = gross, and the block is the piece
    bounded by the weld lines -- shear along the two longitudinal welds over
    the landing length, tension across the Whitmore width at their end.

    Both are the standard idealisations. Neither can know about a real
    connection's clearances, so they are a check on the detail as described,
    not a substitute for drawing it.
    """
    t = max(t_mm, 0.0)
    if detail['conn_type'] == 'bolted':
        hole = detail['bolt_d_mm'] + cirsoc.HOLE_ALLOWANCE_MM
        Lv = detail['end_mm'] + (detail['cols'] - 1) * detail['pitch_mm']
        Agv = 2.0 * t * Lv
        Anv = 2.0 * t * max(Lv - (detail['cols'] - 0.5) * hole, 0.0)
        Wt = (detail['rows'] - 1) * detail['gauge_mm']
        Agt = t * Wt
        Ant = t * max(Wt - (detail['rows'] - 1) * hole, 0.0)
        note = ('bolted: %d rows x %d cols, d=%.0f mm, pitch %.0f, gauge %.0f, '
                'end %.0f' % (detail['rows'], detail['cols'],
                              detail['bolt_d_mm'], detail['pitch_mm'],
                              detail['gauge_mm'], detail['end_mm']))
    else:
        Agv = Anv = 2.0 * t * landing_mm
        Agt = Ant = t * whitmore_mm
        note = ('welded: two %.0f mm longitudinal welds, tension across the '
                '%.0f mm Whitmore width' % (landing_mm, whitmore_mm))
    return Agv, Anv, Ant, Agt, note


def gusset_buckling_check(P_kN, whitmore_mm, t_mm, landing_mm, Fy,
                          code=cirsoc.CIRSOC_301, K=GUSSET_K):
    """Thornton: the Whitmore width acting as a short column of thickness t.

    Only a member in COMPRESSION can buckle the gusset, so a tensile member
    returns util 0 with `applies` False rather than a meaningless number.

    The unbraced length is taken as the landing length -- the distance the
    force travels from the end of the connection to the supported edge.
    Thornton's own method averages three such lines (L1, L2, L3) measured off
    the real gusset outline; this tab's outline is a generated approximation,
    so averaging three lines off it would be false precision. Stated here so
    the assumption is visible rather than implied.
    """
    if P_kN >= -1e-9:                     # tension or zero: cannot buckle
        return {'applies': False, 'util': 0.0,
                'note': 'member is in tension; gusset buckling does not apply'}
    r = t_mm / math.sqrt(12.0)            # radius of gyration of a plate strip
    if r <= 1e-9:
        return {'applies': False, 'util': float('inf'), 'note': 'zero thickness'}
    slend = K * landing_mm / r
    area = whitmore_mm * t_mm
    res = cirsoc.compression_strength(area, slend, Fy, code,
                                      required=abs(P_kN) * 1e3)
    return {
        'applies': True, 'util': res.util, 'Fcr_MPa': res.Fcr,
        'Fe_MPa': res.Fe, 'slenderness': slend, 'area_mm2': area,
        'Pd_kN': res.Pd / 1e3, 'governing': res.governing,
        'K': K, 'Lc_mm': landing_mm,
        'note': 'Whitmore width as a column, K=%.2f, L=%.0f mm' % (K, landing_mm),
    }


# ═════════════════════════════════════════════════════════════════════════
#  P-2 · shear panel checks
# ═════════════════════════════════════════════════════════════════════════

def panel_aspect(pts_m):
    """(long side, short side) of the panel's bounding box, metres. Used for
    the buckling coefficient; a bounding box is the right level of precision
    for kv on a non-rectangular bay."""
    xs = [p[0] for p in pts_m]
    ys = [p[1] for p in pts_m]
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    return (max(w, h), min(w, h))


def shear_buckling_stress(a_m, b_m, t_mm, E=DEFAULT_E_MPA, nu=DEFAULT_NU):
    """Elastic critical shear stress of a rectangular plate simply supported
    on four edges, MPa:

        tau_cr = kv * pi^2 * E / (12 (1 - nu^2) (b/t)^2),
        kv = 5.34 + 4.0 (b/a)^2     for a >= b

    Simply supported is the conservative assumption for a welded infill: real
    edge restraint from the surrounding members is somewhere between simply
    supported and fixed, and claiming the fixed value would overstate the
    capacity of exactly the panels most likely to buckle.
    """
    if b_m <= 0 or t_mm <= 0:
        return float('inf')
    a_m = max(a_m, b_m)
    kv = 5.34 + 4.0 * (b_m / a_m) ** 2
    b_mm = b_m * 1000.0
    return (kv * math.pi ** 2 * E) / (12.0 * (1 - nu ** 2) * (b_mm / t_mm) ** 2)


def panel_checks(plate, plate_result, code=cirsoc.CIRSOC_301):
    """Check one shear panel against the shear flow the solver reported.

    A panel result must NEVER be shown without the buckling check. A thin
    plate buckles in shear long before it yields, so a bare tau that looks
    comfortable is the most dangerous output this feature could produce.
    """
    if not plate_result or not plate_result.get('valid'):
        return {'valid': False,
                'reason': (plate_result or {}).get('reason', 'panel not solved')}

    t_mm = float(plate_result['t_mm'])
    Fy = float(plate.get('Fy', DEFAULT_FY_MPA))
    Fexx = float(plate.get('Fexx', DEFAULT_FEXX_MPA))
    n_lines = int(plate.get('weld_lines', 2))
    E = float(plate.get('E_GPa', 200.0)) * 1000.0        # GPa -> MPa
    nu = float(plate.get('nu', DEFAULT_NU))

    tau = abs(float(plate_result['tau_MPa']))
    q_kN_per_m = float(plate_result['q'])

    yield_chk = cirsoc.stress_check(0.0, tau, Fy, code)
    a_m, b_m = panel_aspect(plate_result['pts_m'])
    tau_cr = shear_buckling_stress(a_m, b_m, t_mm, E, nu)
    buck_util = cirsoc.buckling_stress_check(tau, tau_cr, code)

    # edge weld: q in kN/m -> N/mm is a factor of exactly 1
    q_N_per_mm = abs(q_kN_per_m)
    leg_req = cirsoc.leg_for_shear_flow(q_N_per_mm, Fexx, n_lines, code)
    leg_min = cirsoc.min_fillet_leg(t_mm)
    leg_max = cirsoc.max_fillet_leg(t_mm)
    leg = max(leg_req, leg_min)

    governing = ('shear buckling (H.3.6)' if buck_util >= yield_chk.util
                 else yield_chk.governing)
    return {
        'valid': True,
        'nodes': plate_result['nodes'], 'area_m2': plate_result['area_m2'],
        't_mm': t_mm, 'Fy': Fy, 'Fexx': Fexx,
        'q_kN_per_m': q_kN_per_m, 'tau_MPa': tau,
        'a_m': a_m, 'b_m': b_m, 'b_over_t': (b_m * 1000.0 / t_mm) if t_mm else float('inf'),
        'tau_cr_MPa': tau_cr,
        'util_yield': yield_chk.util, 'util_buckling': buck_util,
        'util': max(yield_chk.util, buck_util), 'governing': governing,
        'buckling_governs': buck_util >= yield_chk.util,
        'weld_leg_req_mm': leg_req, 'weld_leg_min_mm': leg_min,
        'weld_leg_max_mm': leg_max, 'weld_leg_mm': leg,
        'weld_leg_feasible': leg <= leg_max + 1e-9,
        'code': code.name,
    }


def check_all(nodes, rods, plates, result, code=cirsoc.CIRSOC_301):
    """Run every plate's check. Returns a list parallel to `plates`, with
    None for entries that cannot be checked (no analysis yet, invalid loop).
    """
    if not plates:
        return []
    out = [None] * len(plates)
    if not result:
        return out
    from .truss_math import compute_node_design_actions
    actions = compute_node_design_actions(nodes, rods, result.get('rod_res', []),
                                          result.get('plate_res', []))
    plate_res = result.get('plate_res', [])
    for i, plate in enumerate(plates):
        kind = plate.get('kind')
        if kind == 'gusset':
            ni = int(plate.get('node', -1))
            if 0 <= ni < len(nodes):
                out[i] = gusset_checks(nodes, rods, plate, actions.get(ni, {}), code)
        elif kind == 'panel':
            pr = plate_res[i] if i < len(plate_res) else None
            out[i] = panel_checks(plate, pr, code)
    return out


# ═════════════════════════════════════════════════════════════════════════
#  Selection -> panel
# ═════════════════════════════════════════════════════════════════════════

def closed_loop_from_rods(rods, selected):
    """Turn a set of selected rod indices into the ordered node loop of the
    panel they enclose.

    Returns `(nodes, None)` on success or `(None, reason)` with a message fit
    to put straight in the status bar. The panel feature only accepts
    triangles and quadrilaterals, so this deliberately refuses anything else
    rather than triangulating behind the user's back.
    """
    sel = sorted(set(int(i) for i in selected))
    if len(sel) not in (3, 4):
        return None, ('Select 3 or 4 rods forming a closed loop '
                      '(%d selected).' % len(sel))
    try:
        edges = [(rods[i]['a'], rods[i]['b']) for i in sel]
    except (IndexError, KeyError, TypeError):
        return None, 'Selection refers to a rod that no longer exists.'

    deg = {}
    for a, b in edges:
        if a == b:
            return None, 'A rod joins a node to itself; that is not a loop.'
        deg.setdefault(a, []).append(b)
        deg.setdefault(b, []).append(a)
    if len(deg) != len(edges):
        return None, ('Those rods do not form a single closed loop '
                      '(%d rods, %d nodes).' % (len(edges), len(deg)))
    bad = [n for n, nb in deg.items() if len(nb) != 2]
    if bad:
        return None, ('Those rods branch instead of closing a loop '
                      '(node %d meets %d of them).' % (bad[0], len(deg[bad[0]])))

    start = edges[0][0]
    loop = [start]
    prev, cur = None, start
    for _ in range(len(edges) - 1):
        nxt = [n for n in deg[cur] if n != prev]
        if not nxt:
            return None, 'Those rods do not form a single closed loop.'
        prev, cur = cur, nxt[0]
        loop.append(cur)
    if len(loop) != len(edges) or set(loop) != set(deg):
        return None, 'Those rods form more than one loop.'
    return loop, None
