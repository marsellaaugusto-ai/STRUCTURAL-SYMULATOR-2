"""The crane as a LIFTING CALCULATOR.

The crane in this tab does not simulate a lift. It answers the questions a
lift plan asks before anything leaves the ground:

  * how heavy is the piece, and where is its centre of gravity;
  * where does the hook go (straight over the centre of gravity), how long
    is each sling and at what angle;
  * what does each sling carry, and so how thick must the rope be;
  * what does being picked up do to the piece -- axial forces, moments and
    utilisation in every rod.

So a lift is solved on its own: the piece (and nothing else in the file),
its slings, a FIXED hook, and the piece's own weight times a dynamic factor.
The piece does not swing or spin -- it only goes up. That is the "vertical
lift" condition, three restraints (two horizontal at one pick, one across
at another) that hold the rigid-body swing and spin a linear solve cannot
otherwise resolve. They are not supports of the piece: with the hook over
the centre of gravity, statics leaves them nothing to carry, and the force
they DO carry is reported as the balance check -- 0.00 kN for a balanced
lift. Nothing is added to the model's supports, and the model's own
supports play no part in the lift.

Kept free of Tk.
"""
import math

from apps.stereo import stereo_math as sm
from apps.stereo import stereo_lift as slift
from apps.stereo import stereo_geometry_addons as sga

HOOK_MODES = ('auto', 'height', 'angle', 'length')
HOOK_MODE_LABELS = {
    'auto': 'auto (≈45°)',
    'height': 'hook height above top pick (m)',
    'angle': 'flattest sling angle (°)',
    'length': 'longest sling length (m)',
}
# Wire rope diameters a sling is commonly made in, mm. Editable in the panel.
STANDARD_ROPE_MM = (6, 8, 9, 10, 11, 12, 13, 14, 16, 18, 19, 20, 22, 24, 26,
                    28, 30, 32, 36, 40, 44, 48, 52, 56, 60)
# A balance force below this is numerical: the lift is level.
BALANCE_TOL_KN = 0.01
ROPE_BASIS = ('6x36 IWRC wire rope, grade 1770: minimum breaking force '
              '≈ %.2f·d² kN (d in mm), working load limit = MBF ÷ %g'
              % (slift.ROPE_MBF_K, slift.ROPE_FACTOR))


# ── weight and centre of gravity ──────────────────────────────────────────

def piece_weight(nodes, members, rods, allowance=0.0,
                 unit_weight=sm.DEFAULT_STEEL_UNIT_WEIGHT):
    """(weight kN, (x, y, z) centre of gravity) of `rods`: each rod's own
    weight (A·L·γ, its material's γ) times (1 + allowance), the allowance
    being the connections -- gussets, bolts, welds -- as a fraction.
    (0.0, None) for nothing to weigh."""
    w = sx = sy = sz = 0.0
    for j in rods:
        m = members[j]
        a, b = nodes[m['a']], nodes[m['b']]
        L = math.dist(a, b)
        wj = (float(m.get('A', 0.0) or 0.0) * 1e-4 * L
              * sm.member_unit_weight(m, unit_weight))
        w += wj
        sx += wj * (a[0] + b[0]) / 2
        sy += wj * (a[1] + b[1]) / 2
        sz += wj * (a[2] + b[2]) / 2
    if w <= 1e-12:
        return 0.0, None
    k = 1.0 + float(allowance or 0.0)
    return w * k, (sx / w, sy / w, sz / w)


def lift_loads(nodes, members, rods, allowance=0.0, daf=1.0,
               unit_weight=sm.DEFAULT_STEEL_UNIT_WEIGHT):
    """The lift's load case: every rod's weight, half to each end, times
    (1 + allowance) times the dynamic factor. Nothing else -- the service
    loads are not on a piece in the air."""
    f = (1.0 + float(allowance or 0.0)) * float(daf or 1.0)
    out = {}
    for j in rods:
        m = members[j]
        L = math.dist(nodes[m['a']], nodes[m['b']])
        half = (float(m.get('A', 0.0) or 0.0) * 1e-4 * L
                * sm.member_unit_weight(m, unit_weight)) * f / 2.0
        for n in (m['a'], m['b']):
            out[n] = out.get(n, 0.0) + half
    return [{'node': n, 'fx': 0.0, 'fy': 0.0, 'fz': -w}
            for n, w in sorted(out.items())]


# ── where the hook goes ───────────────────────────────────────────────────

def hook_rise(nodes, picks, hook_xy, mode='auto', value=None):
    """How far above the highest pick the hook goes, for each way of
    setting it:

      'auto'    from the spread of the picks: slings near 45°;
      'height'  `value` metres above the highest pick;
      'angle'   high enough that the FLATTEST sling is at `value` degrees
                from horizontal (none flatter);
      'length'  so that the LONGEST sling is `value` metres (every other
                sling shorter, each reported with its own length).

    Raises ValueError, with the reason, for a value that cannot work."""
    if not picks:
        raise ValueError('No pick points.')
    hx, hy = hook_xy
    top = max(nodes[i][2] for i in picks)
    if mode in (None, '', 'auto'):
        return sga.crane_auto_rise(nodes, picks, hook_xy)
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError('Give a number for the hook (%s).'
                         % HOOK_MODE_LABELS.get(mode, mode))
    plan = [(math.hypot(nodes[i][0] - hx, nodes[i][1] - hy),
             top - nodes[i][2]) for i in picks]
    if mode == 'height':
        if v <= 0:
            raise ValueError('The hook has to be above the highest pick: '
                             'give a height greater than zero.')
        return v
    if mode == 'angle':
        if not 0.0 < v < 90.0:
            raise ValueError('A sling angle is between 0° and 90° from the '
                             'horizontal.')
        t = math.tan(math.radians(v))
        r = max(d * t - below for d, below in plan)
        return max(r, 0.05)
    if mode == 'length':
        far = max(math.hypot(d, below) for d, below in plan)
        if v <= far:
            raise ValueError('A %.2f m sling cannot reach: the furthest pick '
                             'is %.2f m from the point over the centre of '
                             'gravity, so the slings must be longer than '
                             'that.' % (v, far))
        r = min(math.sqrt(v * v - d * d) - below for d, below in plan)
        if r <= 0:
            raise ValueError('With %.2f m slings the hook would sit below the '
                             'highest pick: use longer slings.' % v)
        return r
    raise ValueError('Unknown hook setting %r.' % mode)


# ── cable sizing ──────────────────────────────────────────────────────────

def rope_diameter_mm(wll_kN, k=slift.ROPE_MBF_K, factor=slift.ROPE_FACTOR):
    """The wire rope diameter (mm) whose working load limit is `wll_kN`."""
    if wll_kN is None or wll_kN <= 0:
        return 0.0
    return math.sqrt(float(wll_kN) * factor / k)


def standard_size(d_mm, sizes=STANDARD_ROPE_MM):
    """The smallest listed diameter at least `d_mm`; None above the list."""
    for s in sorted(float(x) for x in sizes):
        if s >= d_mm - 1e-9:
            return s
    return None


def parse_sizes(text):
    """'8, 10, 12' -> (8.0, 10.0, 12.0); the default list for blank text."""
    out = []
    for part in str(text or '').replace(';', ',').split(','):
        part = part.strip()
        if not part:
            continue
        v = float(part)
        if v <= 0:
            raise ValueError('A rope diameter is greater than zero.')
        out.append(v)
    return tuple(sorted(out)) or tuple(float(x) for x in STANDARD_ROPE_MM)


# ── solving one lift ──────────────────────────────────────────────────────

def lift_parts(members, code):
    """(cable rod ids, pick nodes, hook node) of crane `code`."""
    cables, _masts, hook, _anchor = slift.crane_parts(members, code)
    picks = []
    for j in cables:
        m = members[j]
        picks.append(m['a'] if m['b'] == hook else m['b'])
    return cables, picks, hook


def _sub_model(nodes, members, rods):
    used = sorted({n for j in rods for n in (members[j]['a'], members[j]['b'])})
    local = {n: k for k, n in enumerate(used)}
    sub_nodes = [tuple(nodes[n]) for n in used]
    sub = []
    for j in rods:
        m = dict(members[j])
        m['a'], m['b'] = local[m['a']], local[m['b']]
        sub.append(m)
    return sub_nodes, sub, used, local


def solve_lift(nodes, members, lift, unit_weight=sm.DEFAULT_STEEL_UNIT_WEIGHT,
               timber=None, sizes=STANDARD_ROPE_MM):
    """Solve crane lift['code'] lifting lift['rods'], on its own.

    `lift` holds 'code', 'rods' (the lifted piece), and optionally 'daf'
    (dynamic factor, 1.0), 'allowance' (connections, a fraction, 0.0) and
    'wll_kN' (a sling's working load limit to check against). Returns a
    dict: 'ok', 'error', 'loose' (global nodes free to move, when it fails),
    'member_res', 'checks' ({global rod: ...}), 'node_res', 'reactions'
    ({global node: ...}) and 'summary' (see lift_summary)."""
    from apps.stereo import stereo_checks as sc
    code = lift['code']
    rods = [j for j in lift.get('rods', ()) if j < len(members)
            and members[j].get('role') not in slift.CRANE_ROLES]
    cables, picks, hook = lift_parts(members, code)
    out = {'ok': False, 'error': None, 'loose': [], 'code': code,
           'rods': rods, 'cables': cables, 'picks': picks, 'hook': hook,
           'member_res': {}, 'checks': {}, 'node_res': {}, 'reactions': {},
           'summary': None}
    if hook is None or len(cables) < 3:
        out['error'] = 'Crane %s has no hook with three or more slings.' % code
        return out
    if not rods:
        out['error'] = 'Crane %s lifts no rods.' % code
        return out
    daf = float(lift.get('daf') or 1.0)
    allow = float(lift.get('allowance') or 0.0)
    sub_ids = list(rods) + list(cables)
    sub_nodes, sub, used, local = _sub_model(nodes, members, sub_ids)
    loads = lift_loads(sub_nodes, sub, range(len(rods)), allow, daf,
                       unit_weight)
    l_picks = [local[p] for p in picks]
    l_hook = local[hook]
    supports = [{'node': l_hook, 'type': 'fixed'}]
    balance = sga.crane_steady_lines(sub_nodes, l_picks)
    for node, dof in balance:
        supports.append({'node': node, 'dofs': {dof: True}})
    res, err = sm.analyze(sub_nodes, sub, loads, supports)
    if res is None:
        out['error'] = err or 'The lift did not solve.'
        try:
            loose = sm.mechanism(sub_nodes, sub, supports) or []
        except Exception:                                   # noqa: BLE001
            loose = []
        out['loose'] = sorted(used[n] for n in loose if n < len(used))
        return out
    if err:
        out['warning'] = err
    checks = sc.check_all_members(sub_nodes, sub, res['member_res'],
                                  timber=timber)
    for k, j in enumerate(sub_ids):
        out['member_res'][j] = res['member_res'][k]
        out['checks'][j] = checks[k]
    for k, n in enumerate(used):
        out['node_res'][n] = res['node_res'][k]
    for n, r in (res.get('reactions') or {}).items():
        out['reactions'][used[n]] = r
    out['ok'] = True
    out['summary'] = lift_summary(nodes, members, out, lift, balance=[
        (used[n], d) for n, d in balance], unit_weight=unit_weight,
        sizes=sizes)
    return out


def lift_summary(nodes, members, solved, lift, balance=(),
                 unit_weight=sm.DEFAULT_STEEL_UNIT_WEIGHT,
                 sizes=STANDARD_ROPE_MM):
    """What the lift plan needs, as numbers: weight and centre of gravity,
    hook position and load, one row per sling (length, angle, tension,
    required working load limit and rope diameter, the standard size), the
    worst rod and how many are over capacity, the balance check, a verdict.
    Forces kN, lengths m, angles degrees from horizontal."""
    daf = float(lift.get('daf') or 1.0)
    allow = float(lift.get('allowance') or 0.0)
    wll = lift.get('wll_kN')
    rods = solved['rods']
    weight, cog = piece_weight(nodes, members, rods, allow, unit_weight)
    hook = solved['hook']
    hx, hy, hz = nodes[hook]
    slings = []
    for j in solved['cables']:
        m = members[j]
        pick = m['a'] if m['b'] == hook else m['b']
        px, py, pz = nodes[pick]
        dx, dy, dz = hx - px, hy - py, hz - pz
        L = math.sqrt(dx * dx + dy * dy + dz * dz)
        mr = solved['member_res'].get(j) or {}
        T = max(float(mr.get('N', 0.0) or 0.0), 0.0)
        d_req = rope_diameter_mm(T)
        slings.append({
            'rod': j, 'pick': pick, 'length': L,
            'angle': math.degrees(math.atan2(dz, math.hypot(dx, dy))),
            'T': T, 'slack': T <= 1e-9,
            'wll_req': T, 'd_req': d_req,
            'd_std': standard_size(d_req, sizes) if T > 0 else None,
            'util': (T / wll) if wll else None})
    react = solved['reactions']
    # the support reaction at the hook: up, and equal to what is lifted
    hook_load = float((react.get(hook) or {}).get('Fz', 0.0) or 0.0)
    bal = 0.0
    for n, dof in balance:
        r = react.get(n) or {}
        key = {'ux': 'Fx', 'uy': 'Fy', 'uz': 'Fz'}.get(dof, 'Fx')
        bal = max(bal, abs(float(r.get(key, 0.0) or 0.0)))
    rated = [(c.get('util'), j) for j, c in solved['checks'].items()
             if j in set(rods) and c and c.get('checked')
             and c.get('util') is not None]
    worst = max(rated) if rated else None
    over = sorted((r for r in rated if r[0] > 1.0), reverse=True)
    flat = [s for s in slings if s['angle'] < slift.SLING_MIN_ANGLE_DEG]
    slack = [s for s in slings if s['slack']]
    cable_over = [s for s in slings if s['util'] is not None and s['util'] > 1]
    if slack:
        verdict = 'slack sling'
    elif bal > BALANCE_TOL_KN:
        verdict = 'not balanced'
    elif over or cable_over:
        verdict = 'over capacity'
    else:
        verdict = 'OK'
    return {
        'code': solved['code'], 'weight': weight, 'daf': daf,
        'allowance': allow, 'lift_load': weight * daf, 'cog': cog,
        'hook_xyz': (hx, hy, hz), 'hook_load': hook_load,
        'slings': slings, 'balance': bal, 'worst': worst, 'over': over,
        'flat': flat, 'slack': slack, 'cable_over': cable_over,
        'wll_kN': wll, 'n_rods': len(rods), 'verdict': verdict,
        'rope_basis': ROPE_BASIS}


def combine(n_nodes, members, solved_lifts):
    """One results dict and one checks list over the WHOLE model from the
    separately solved lifts -- what the canvas, the reports and the crane
    sheets read. Rods no lift touches carry nothing and are marked
    'ghost'; nodes no lift touches have not moved."""
    member_res, checks = [], []
    for j, m in enumerate(members):
        member_res.append(None)
        checks.append(None)
    node_res = [None] * n_nodes
    reactions = {}
    for s in solved_lifts:
        if not s.get('ok'):
            continue
        for j, r in s['member_res'].items():
            member_res[j] = r
        for j, c in s['checks'].items():
            checks[j] = c
        for n, r in s['node_res'].items():
            node_res[n] = r
        reactions.update(s['reactions'])
    for j, m in enumerate(members):
        if member_res[j] is None:
            member_res[j] = {'N': 0.0, 'conn': 'pin', 'length_m': 0.0,
                             'w_local': (0.0, 0.0, 0.0), 'ghost': True}
        if checks[j] is None:
            checks[j] = {'checked': False, 'util': None, 'ghost': True}
    for n in range(n_nodes):
        if node_res[n] is None:
            node_res[n] = {'ux': 0.0, 'uy': 0.0, 'uz': 0.0,
                           'rx': 0.0, 'ry': 0.0, 'rz': 0.0}
    return ({'node_res': node_res, 'member_res': member_res,
             'reactions': reactions, 'panel_res': [], 'case': 'lift'},
            checks)


def summary_text(s):
    """The lift summary as plain lines, for the panel and the clipboard."""
    if not s:
        return ''
    cx, cy, cz = s['cog'] or (0.0, 0.0, 0.0)
    hx, hy, hz = s['hook_xyz']
    lines = [
        'Crane %s — %s' % (s['code'], s['verdict']),
        'Weight %.2f kN (connections +%.0f%%) · DAF %.2f · lift load %.2f kN'
        % (s['weight'], 100 * s['allowance'], s['daf'], s['lift_load']),
        'Centre of gravity x %.3f  y %.3f  z %.3f m' % (cx, cy, cz),
        'Hook x %.3f  y %.3f  z %.3f m · hook load %.2f kN'
        % (hx, hy, hz, s['hook_load']),
        'Balance %.2f kN (%s)' % (s['balance'], 'level' if s['balance']
                                  <= BALANCE_TOL_KN else 'NOT balanced'),
        'Sling   pick   length m  angle°  T kN   req. Ø mm  use Ø mm',
    ]
    for k, r in enumerate(s['slings'], 1):
        lines.append('%-6s  %5d  %8.3f  %6.1f  %6.2f  %8.1f  %8s' % (
            'S%d' % k, r['pick'], r['length'], r['angle'], r['T'],
            r['d_req'], '%g' % r['d_std'] if r['d_std'] else '—'))
    if s['worst']:
        lines.append('Worst rod %d at %.2f; %d rod(s) over capacity.'
                     % (s['worst'][1], s['worst'][0], len(s['over'])))
    return '\n'.join(lines)


def add_slings(nodes, members, picks, section, hook_xyz):
    """Hang `picks` from a hook at `hook_xyz`: the hook node and one pinned,
    tension-only sling from each pick to it. No mast -- the hook itself is
    the fixed point the lift is solved from. Returns (nodes, members, hook)."""
    nodes = list(nodes)
    members = list(members)
    hook = len(nodes)
    nodes.append(tuple(float(c) for c in hook_xyz))
    for i in picks:
        m = dict(section)
        m.update(a=i, b=hook, conn='pin', role='crane_cable',
                 tension_only=True)
        members.append(m)
    return nodes, members, hook


# ── the crane in the service analysis ─────────────────────────────────────
#
# A crane is a lift calculation, not part of the building. In the ordinary
# Analyze its slings carry nothing and its hook is not a joint: the model is
# solved without them, and the slings come back as inert rods (N = 0) so
# every list stays parallel to the model's members.

def is_crane_rod(m):
    return m.get('role') in slift.CRANE_ROLES


def service_model(nodes, members, supports, loads, member_loads=(),
                  panels=()):
    """The model the ordinary Analyze solves: everything except the crane
    rods, and except the nodes only a crane rod touches (the hook). None
    when there is no crane. The dict carries the reduced lists and the maps
    expand_service needs to give the answer back in the model's numbering.
    """
    crane = [j for j, m in enumerate(members) if is_crane_rod(m)]
    if not crane:
        return None
    crane_set = set(crane)
    kept_m = [j for j in range(len(members)) if j not in crane_set]
    struct_nodes = {n for j in kept_m
                    for n in (members[j]['a'], members[j]['b'])}
    crane_nodes = {n for j in crane for n in (members[j]['a'], members[j]['b'])}
    drop = crane_nodes - struct_nodes
    for p in panels or ():
        drop -= set(p.get('nodes', ()))
    kept_n = [i for i in range(len(nodes)) if i not in drop]
    nmap = {old: new for new, old in enumerate(kept_n)}
    mmap = {old: new for new, old in enumerate(kept_m)}
    return {
        'nodes': [nodes[i] for i in kept_n],
        'members': [dict(members[j], a=nmap[members[j]['a']],
                         b=nmap[members[j]['b']]) for j in kept_m],
        'supports': [dict(s, node=nmap[s['node']]) for s in supports
                     if s.get('node') in nmap],
        'loads': [dict(ld, node=nmap[ld['node']]) for ld in loads
                  if ld.get('node') in nmap],
        'member_loads': [dict(ld, member=mmap[ld['member']])
                         for ld in (member_loads or ())
                         if ld.get('member') in mmap],
        'panels': [dict(p, nodes=[nmap[n] for n in p['nodes']])
                   for p in (panels or ())],
        'kept_nodes': kept_n, 'kept_members': kept_m, 'crane': crane,
        'n_nodes': len(nodes), 'n_members': len(members)}


def expand_service(res, model, nodes, members):
    """`res` (solved on service_model's lists) in the full model's
    numbering: crane rods inert at N = 0, hook nodes unmoved."""
    if res is None:
        return None
    node_res = [{'ux': 0.0, 'uy': 0.0, 'uz': 0.0, 'rx': 0.0, 'ry': 0.0,
                 'rz': 0.0} for _ in range(model['n_nodes'])]
    for new, old in enumerate(model['kept_nodes']):
        node_res[old] = res['node_res'][new]
    member_res = [None] * model['n_members']
    for new, old in enumerate(model['kept_members']):
        member_res[old] = res['member_res'][new]
    for j in model['crane']:
        m = members[j]
        member_res[j] = {'N': 0.0, 'conn': 'pin',
                         'length_m': math.dist(nodes[m['a']], nodes[m['b']]),
                         'w_local': (0.0, 0.0, 0.0), 'inert': True}
    reactions = {model['kept_nodes'][n]: r
                 for n, r in (res.get('reactions') or {}).items()}
    out = dict(res)
    out.update(node_res=node_res, member_res=member_res, reactions=reactions)
    return out


def inert_check():
    """The check entry of a crane rod in the service analysis."""
    return {'checked': False, 'util': None, 'governing': None,
            'note': 'crane sling: solved only in Analyze lift', 'inert': True}


# ── the lift in the workbook ──────────────────────────────────────────────

# The Cranes sheet: one row per crane, every setting the lift was made
# with, so a workbook brings its lifts back on Import. Read by column name.
CRANE_SHEET_COLUMNS = ('code', 'group', 'picks', 'hook_x_m', 'hook_y_m',
                       'hook_z_m', 'hook_mode', 'hook_value', 'daf',
                       'allowance_pct', 'wll_kN', 'cable_spec', 'sizes_mm')


def crane_rows(records, sizes=STANDARD_ROPE_MM):
    """Rows for the Cranes sheet from the app's lift records (each with
    'code', 'group_name', 'picks', 'hook_xyz' and the settings)."""
    out = []
    for r in records:
        hx, hy, hz = r.get('hook_xyz') or (None, None, None)
        out.append([
            r.get('code'), r.get('group_name') or '',
            ' '.join(str(p) for p in r.get('picks', ())),
            hx, hy, hz, r.get('hook_mode') or 'auto', r.get('hook_value'),
            float(r.get('daf') or 1.0),
            100.0 * float(r.get('allowance') or 0.0),
            r.get('wll_kN'), r.get('cable_spec') or '',
            ', '.join('%g' % s for s in (r.get('sizes') or sizes))])
    return out


def read_crane_rows(rows):
    """The Cranes sheet's rows (dicts by column name) back to lift
    settings: {code: {...}}. Blank or unreadable cells take the defaults;
    a row with no code is skipped."""
    out = {}
    for row in rows:
        code = str(row.get('code') or '').strip()
        if not code:
            continue

        def num(key, default=None):
            try:
                v = row.get(key)
                return default if v in (None, '') else float(v)
            except (TypeError, ValueError):
                return default
        try:
            sizes = parse_sizes(row.get('sizes_mm'))
        except ValueError:
            sizes = tuple(float(x) for x in STANDARD_ROPE_MM)
        mode = str(row.get('hook_mode') or 'auto').strip()
        out[code] = {
            'code': code,
            'group_name': str(row.get('group') or '').strip() or None,
            'picks': [int(p) for p in str(row.get('picks') or '').split()
                      if p.strip().lstrip('-').isdigit()],
            'hook_mode': mode if mode in HOOK_MODES else 'auto',
            'hook_value': num('hook_value'),
            'daf': num('daf', 1.0) or 1.0,
            'allowance': (num('allowance_pct', 0.0) or 0.0) / 100.0,
            'wll_kN': num('wll_kN'),
            'cable_spec': str(row.get('cable_spec') or ''),
            'sizes': sizes}
    return out


def lift_rod_rows(nodes, members, solved, group_of=None, samples=21):
    """Rows for the Lift rods sheet: every rod a lift puts force into --
    crane, rod, its group, N, the peak M and V along it, utilisation and
    the governing check. `group_of` maps a rod to its group's name."""
    out = []
    for s in solved:
        if not s.get('ok'):
            continue
        for j in s['rods']:
            mr = s['member_res'].get(j) or {}
            ck = s['checks'].get(j) or {}
            pk = sm.member_peak_actions(mr, samples)
            out.append([s['code'], j, (group_of or {}).get(j, ''),
                        float(mr.get('N', 0.0) or 0.0), pk['M_max'],
                        pk['V_max'],
                        ck.get('util') if ck.get('checked') else None,
                        ck.get('governing') or ck.get('note') or ''])
    return out
