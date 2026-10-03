"""Comparing iterations of one structure -- kept free of Tk.

A file of iterations holds the same structure several times over: each
iteration's trusses, its module, its roof, side by side. To compare them,
every group is tagged with three things:

  * ITERATION -- which version of the design it belongs to (1, 2, 3 ...);
  * STAGE     -- what kind of piece it is on the way up: a truss, a module,
                 the roof;
  * POSITION  -- which one it is within its stage (truss 1 to 4 ...).

Tags are proposed from the group names and the order of the groups, and the
user corrects what is wrong. Then the same slot -- say stage "truss",
position 2 -- can be read across the iterations.

The LIFT PLAN says how each tagged piece is picked up (a pick rule per
stage); CHECK LIFTS solves every planned lift at once with the lift
calculator (stereo_lift_calc) without adding anything to the model, and
COMPARE lays the answers out slot by iteration: weight, worst rod, the
heaviest sling, the longest sling and the rope it needs.
"""
import math
import re

from apps.stereo import stereo_floating as sf
from apps.stereo import stereo_lift as slift
from apps.stereo import stereo_lift_calc as slc

TAGS = ('iteration', 'stage', 'position')

# stage keyword -> stage name; English and Spanish, singular and plural
STAGE_WORDS = (
    (r'\b(?:roof|techo|cubierta)s?\b', 'roof'),
    (r'\b(?:modules?|m[oó]dulos?)\b', 'module'),
    (r'\b(?:truss(?:es)?|cerchas?|cabriadas?|vigas?)\b', 'truss'),
    (r'\b(?:columns?|columnas?)\b', 'column'),
)
# a number that says the iteration outright: "R2 Module 1" (roof 2),
# "It 3", "Iteration 2", "Iteración 2", "v2", "Rev 2"
ITER_PATTERNS = (
    r'\b(?:iter(?:ation|aci[oó]n)?|it)\s*[-_#.]?\s*(\d+)\b',
    r'\b(?:v|rev|version|versi[oó]n)\s*[-_#.]?\s*(\d+)\b',
    r'\bR(\d+)\b',
)
# how each stage is picked up when the plan says nothing else
DEFAULT_RULE = {'truss': 'chords', 'module': 'corners_mid',
                'roof': 'corners', 'column': 'corners'}


def _stage_of(name):
    # "R2 Module 1": a module of roof 2 -- the roof stage
    if re.search(r'\bR\d+\b', name):
        return 'roof'
    low = name.lower()
    for pat, stage in STAGE_WORDS:
        if re.search(pat, low):
            return stage
    return None


def _explicit_iteration(name):
    for pat in ITER_PATTERNS:
        m = re.search(pat, name, flags=re.IGNORECASE if not pat.startswith(
            r'\bR(') else 0)
        if m:
            return int(m.group(1))
    return None


def _trailing_number(name):
    nums = re.findall(r'(\d+)', name)
    return int(nums[-1]) if nums else None


def propose_tags(names):
    """{name: {'iteration', 'stage', 'position'}} proposed for the group
    names given (the top-level groups, in model order).

    The stage comes from a keyword in the name. The iteration comes from
    the name when it says so ("R2 Module 1", "Iteration 3"); otherwise each
    stage's groups, in the order of their numbers, are dealt out evenly
    over the iterations -- twelve trusses over three iterations is four
    each: truss 6 is iteration 2, position 2. A tag that cannot be proposed
    is left out."""
    out = {n: {} for n in names}
    by_stage = {}
    for n in names:
        st = _stage_of(n)
        if st:
            out[n]['stage'] = st
            by_stage.setdefault(st, []).append(n)
    explicit = {n: _explicit_iteration(n) for n in names}
    for n, it in explicit.items():
        if it is not None:
            out[n]['iteration'] = str(it)
    known = {int(v['iteration']) for v in out.values() if 'iteration' in v}
    # How many iterations: what the names say, else the stage with the
    # fewest pieces (one module per iteration, four trusses each ...).
    plain = {st: [n for n in ns if explicit[n] is None]
             for st, ns in by_stage.items()}
    counts = [len(ns) for ns in plain.values() if ns]
    k = max(known) if known else (min(counts) if counts else 0)
    for st, ns in plain.items():
        if not ns or not k or len(ns) % k:
            continue
        per = len(ns) // k
        order = sorted(ns, key=lambda n: (_trailing_number(n) is None,
                                          _trailing_number(n) or 0, n))
        for i, n in enumerate(order):
            out[n]['iteration'] = str(i // per + 1)
            out[n]['position'] = str(i % per + 1)
    for st, ns in by_stage.items():
        for n in ns:
            if explicit[n] is not None and 'position' not in out[n]:
                tail = _trailing_number(re.sub(ITER_PATTERNS[2], '', n))
                if tail is not None:
                    out[n]['position'] = str(tail)
    return out


def slot_of(g):
    """(stage, position) of a tagged group, or None."""
    st = g.get('stage')
    if not st:
        return None
    return (str(st), str(g.get('position') or '1'))


# ── checking a lift plan ──────────────────────────────────────────────────

def check_lift(nodes, members, rods, rule, settings, unit_weight,
               timber=None, code='KP'):
    """One planned lift, solved on a copy: picks by `rule` on `rods`, the
    hook over the centre of gravity as `settings` say. Nothing in `nodes`
    or `members` changes. Returns a row dict (see compare_rows)."""
    row = {'rule': rule, 'rods': len(rods), 'ok': False, 'verdict': '',
           'picks': [], 'weight': None, 'hook_load': None, 'T_max': None,
           'L_max': None, 'angle_min': None, 'd_req': None, 'd_std': None,
           'worst': None, 'worst_rod': None, 'over': None, 'balance': None,
           'joined': len(slift.joined_to_rest(members, rods))}
    if not rods:
        row['verdict'] = 'no rods'
        return row
    picks = sf.pick_nodes(nodes, members, rods, rule)
    row['picks'] = picks
    if len(picks) < 3:
        row['verdict'] = 'fewer than 3 picks'
        return row
    allow = settings.get('allowance', 0.0)
    weight, cog = slc.piece_weight(nodes, members, rods, allow, unit_weight)
    row['weight'] = weight
    if cog is None:
        row['verdict'] = 'weighs nothing'
        return row
    if slift.cog_outside_picks(nodes, picks, cog[:2]) > 1e-3:
        row['verdict'] = 'tips (centre of gravity outside the picks)'
        return row
    try:
        rise = slc.hook_rise(nodes, picks, cog[:2],
                             settings.get('hook_mode', 'auto'),
                             settings.get('hook_value'))
    except ValueError as exc:
        row['verdict'] = str(exc)
        return row
    top = max(nodes[p][2] for p in picks)
    sec = dict(members[rods[0]])
    for k in ('addon', 'role', 'tension_only', 'profile'):
        sec.pop(k, None)
    n2, m2, _hook = slc.add_slings(nodes, members, picks, sec,
                                   (cog[0], cog[1], top + rise))
    for m in m2[len(members):]:
        m['addon'] = code
    s = slc.solve_lift(n2, m2, {'code': code, 'rods': list(rods),
                                'daf': settings.get('daf', 1.0),
                                'allowance': allow,
                                'wll_kN': settings.get('wll_kN')},
                       unit_weight=unit_weight, timber=timber,
                       sizes=settings.get('sizes') or slc.STANDARD_ROPE_MM)
    if not s['ok']:
        row['verdict'] = ('mechanism on these picks' if s.get('loose')
                          else (s.get('error') or 'did not solve'))
        return row
    sm_ = s['summary']
    sl = sm_['slings']
    T = max(x['T'] for x in sl)
    big = max(sl, key=lambda x: x['T'])
    row.update(ok=True, verdict=sm_['verdict'], hook_load=sm_['hook_load'],
               T_max=T, L_max=max(x['length'] for x in sl),
               angle_min=min(x['angle'] for x in sl),
               d_req=big['d_req'], d_std=big['d_std'],
               worst=sm_['worst'][0] if sm_['worst'] else None,
               worst_rod=sm_['worst'][1] if sm_['worst'] else None,
               over=len(sm_['over']), balance=sm_['balance'])
    return row


COMPARE_FIELDS = (
    ('weight', 'weight kN', '%.2f'),
    ('worst', 'worst rod util', '%.2f'),
    ('over', 'rods over 1.0', '%d'),
    ('hook_load', 'hook load kN', '%.2f'),
    ('T_max', 'heaviest sling kN', '%.2f'),
    ('L_max', 'longest sling m', '%.2f'),
    ('angle_min', 'flattest sling °', '%.0f'),
    ('d_std', 'rope Ø mm', '%g'),
    ('verdict', 'verdict', '%s'),
)


def compare_rows(checked):
    """The compare table from checked lifts: `checked` is a list of
    {'stage', 'position', 'iteration', 'group', 'row'}. Returns
    (iterations, [(stage, position, field label, {iteration: text})])."""
    its = sorted({c['iteration'] for c in checked},
                 key=lambda v: (not str(v).isdigit(),
                                int(v) if str(v).isdigit() else 0, str(v)))
    slots = []
    for c in checked:
        s = (c['stage'], c['position'])
        if s not in slots:
            slots.append(s)
    order = {'truss': 0, 'module': 1, 'roof': 2, 'column': 3}
    slots.sort(key=lambda s: (order.get(s[0], 9), s[0],
                              int(s[1]) if str(s[1]).isdigit() else 0, s[1]))
    table = []
    for st, pos in slots:
        cell = {c['iteration']: c for c in checked
                if (c['stage'], c['position']) == (st, pos)}
        table.append((st, pos, 'group',
                      {it: cell[it]['group'] for it in cell}))
        for key, label, fmt in COMPARE_FIELDS:
            vals = {}
            for it, c in cell.items():
                v = c['row'].get(key)
                vals[it] = '—' if v is None else (fmt % v)
            table.append((st, pos, label, vals))
    return its, table


def best_iteration(checked):
    """{(stage, position): iteration} -- the lightest piece whose lift
    passes, per slot, where one does."""
    out = {}
    for c in checked:
        r = c['row']
        if not r['ok'] or r['verdict'] != 'OK':
            continue
        k = (c['stage'], c['position'])
        cur = out.get(k)
        if cur is None or (r['weight'] or 0) < cur[1]:
            out[k] = (c['iteration'], r['weight'] or 0)
    return {k: v[0] for k, v in out.items()}


def fmt_num(v, nd=2):
    return '—' if v is None or (isinstance(v, float) and math.isnan(v)) \
        else ('%.*f' % (nd, v))
