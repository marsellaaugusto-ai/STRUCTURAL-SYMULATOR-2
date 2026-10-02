"""Is each rod strong enough? The Truss tab's CIRSOC 301 rod checks, its
self-weight and its deflection limit. Kept free of Tk.

The checks are the Stereo tab's own (apps/stereo/stereo_checks), so a rod
gets the same verdict in either tab:

  * every rod: axial tension, or compression with flexural buckling on
    kL/r -- r is the section's MINOR radius of gyration, so a plane truss
    is also checked for buckling out of its plane, on the safe side;
  * a rigid rod also carries its in-plane bending, combined by CIRSOC 301
    H1.1 with the peak moment along the rod.

A rod checks only once its family has a steel section (Fy and r), picked
from the catalogue in the family manager; until then it says so.
"""
import math

from common import PX_PER_M

STEEL_UNIT_WEIGHT = 78.5        # kN/m3
DEFLECTION_LIMIT = 300          # span / 300

_SECTION_KEYS = ('Fy', 'Fu', 'r_gyr', 'c_cm', 'Iw', 'cw_cm', 'J', 'K',
                 'catalog', 'material')


def rod_length_m(nodes, rod):
    (xa, ya), (xb, yb) = nodes[rod['a']], nodes[rod['b']]
    return math.hypot(xb - xa, yb - ya) / PX_PER_M


def member_for(nodes, rod, profiles):
    """The rod as a stereo_checks member: its own E, A, I, and the section
    keys (Fy, r, depth...) of its family."""
    prof = profiles.get(rod.get('profile', 'Default'), {})
    m = {k: prof[k] for k in _SECTION_KEYS if prof.get(k) is not None}
    m.update({'E': rod['E'], 'A': rod['A'], 'I': rod.get('I', prof.get('I')),
              'conn': 'pin', '_length_m': rod_length_m(nodes, rod)})
    m.setdefault('K', 1.0)
    return m


def check_rods(nodes, rods, profiles, results, diagrams=None):
    """One check per rod, parallel to `rods`. A rod without a steel section
    returns checked=False and what to do about it."""
    from apps.stereo import stereo_checks as sc
    out = []
    rod_res = results['rod_res']
    for i, rod in enumerate(rods):
        m = member_for(nodes, rod, profiles)
        if not m.get('Fy') or not m.get('r_gyr'):
            out.append({'checked': False, 'util': None, 'governing': None,
                        'note': 'no steel section: pick one for its family '
                                '(Rod family → Manage profiles… → Steel '
                                'section…)'})
            continue
        N = rod_res[i]['force']
        chk = sc.check_member(m, N)
        if not chk.get('checked'):
            out.append(chk)
            continue
        chk['material'] = chk.get('material', 'steel')
        if rod.get('conn') == 'rigid' and diagrams and i < len(diagrams):
            Mr = max((abs(v) for v in diagrams[i].get('M', [])), default=0.0)
            Mc = sc.flexural_capacity_kNm(m)
            chk['M_demand_kNm'] = Mr
            if Mr > 1e-9 and Mc > 1e-9:
                Pc_kN = (chk['Pd_kN'] if N < 0 else
                         chk['capacity_MPa'] * m['A'] * 100 / 1e3)
                ratio = abs(N) / Pc_kN if Pc_kN > 1e-9 else float('inf')
                if ratio >= 0.2:
                    h1, branch = ratio + 8 / 9 * Mr / Mc, 'H1-1a'
                else:
                    h1, branch = ratio / 2 + Mr / Mc, 'H1-1b'
                chk.update({'M_capacity_kNm': Mc, 'util_axial': chk['util'],
                            'util_interaction': h1})
                if h1 > chk['util']:
                    chk['util'] = h1
                    chk['governing'] = '%s, axial + bending' % branch
                chk['ok'] = chk['util'] <= 1 + 1e-9
                chk['mode'] += ' + bending'
        out.append(chk)
    return out


def governing(checks):
    """(rod index, check) of the most used checked rod, or None."""
    best = None
    for i, c in enumerate(checks):
        if c.get('checked') and c.get('util') is not None:
            if best is None or c['util'] > best[1]['util']:
                best = (i, c)
    return best


def self_weight_loads(nodes, rods, unit_weight=STEEL_UNIT_WEIGHT):
    """Half of every rod's weight on each of its end nodes, as loads in the
    tab's convention (kN, fy positive = down). {node: fy}."""
    out = {}
    for r in rods:
        w = r['A'] * 1e-4 * rod_length_m(nodes, r) * unit_weight
        for n in (r['a'], r['b']):
            out[n] = out.get(n, 0.0) + w / 2
    return out


def with_self_weight(loads, nodes, rods, unit_weight=STEEL_UNIT_WEIGHT):
    """`loads` plus the self-weight, merged node by node (the model's own
    load list is never changed)."""
    merged = {ld['node']: dict(ld) for ld in loads}
    for n, fy in self_weight_loads(nodes, rods, unit_weight).items():
        ld = merged.setdefault(n, {'node': n, 'fx': 0.0, 'fy': 0.0})
        ld['fy'] = ld['fy'] + fy
    return list(merged.values())


def deflection(nodes, supports, node_res):
    """The largest vertical deflection against span / 300. The span is the
    horizontal distance between the outermost supports (the whole model's
    width for a single support, as a cantilever's reach)."""
    if not node_res:
        return None
    xs = [nodes[s['node']][0] for s in supports]
    if len(set(xs)) >= 2:
        span = (max(xs) - min(xs)) / PX_PER_M
    else:
        allx = [p[0] for p in nodes]
        span = (max(allx) - min(allx)) / PX_PER_M
    i = max(range(len(node_res)), key=lambda k: abs(node_res[k]['uy']))
    d_mm = abs(node_res[i]['uy'])
    limit_mm = span * 1000 / DEFLECTION_LIMIT if span > 0 else 0.0
    ratio = (span * 1000 / d_mm) if d_mm > 1e-12 else float('inf')
    return {'node': i, 'deflection_mm': d_mm, 'span_m': span,
            'limit_mm': limit_mm, 'L_over': ratio,
            'ok': d_mm <= limit_mm + 1e-12}
