"""Where does this load go? One load's own share of a solved truss.

WHAT THIS IS FOR. "The force is 48 kN here and -96 kN there" is an answer
a student can read without understanding anything. "Three quarters of that
roof load walks down the left diagonal into the pinned support" is what an
architect actually needs, and it is the one reading the numbers do not
hand you. This produces that sentence, and the data for an animation of
it.

HOW IT WORKS: SUPERPOSITION, not a flow heuristic.

The structure is linear elastic, so the answer for all the loads together
is exactly the sum of the answers for each load on its own. Solve the same
model with ONLY the chosen load applied, and the member forces that come
back ARE that load's path -- every member's share of it, and the reactions
are exactly where it lands. Nothing is estimated and nothing is assumed
about which way the load "wants" to go.

WHY NOT THE OBVIOUS THING. The first version of this walked the joints,
splitting the load at each one between the members that resisted it. It
looked reasonable and it was wrong: on this project's own Warren truss it
reported a quarter-point load going 100% to the near support, where
statics says 75/25. A load path drawn from a plausible-looking rule that
disagrees with the reactions teaches something false, and the student has
no way to catch it. Superposition cannot disagree with the reactions,
because the reactions are what it returns.

The cost is one extra solve per trace. These models are a handful of
degrees of freedom; the Warren example solves in well under a millisecond.

Deliberately free of Tk, like truss_stability and truss_guides.
"""
import math

#: A member carrying less than this fraction of the biggest force in the
#: single-load solve is not part of the story, and drawing it crowds out
#: the members that are.
MIN_SHARE = 0.02


def _unit(nodes, a, b):
    dx = nodes[b][0] - nodes[a][0]
    dy = nodes[b][1] - nodes[a][1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return 0.0, 0.0
    return dx / L, dy / L


def trace(nodes, rods, supports, plates, loads, start_node, analyze_fn):
    """This load's own share of the structure.

    `analyze_fn` is `truss_math.analyze`, passed in so this module needs
    no import of its own and a test can hand it a stub.

    Returns a dict:
        'start'      the joint the load sits on
        'magnitude'  that load's size, in the solver's units
        'forces'     {rod index: axial force due to THIS load alone}
        'share'      {rod index: |N| / the biggest |N|}, 0..1, for drawing
        'supports'   {node: fraction of the load landing there}
        'order'      rod indices, nearest the load first, for an animation
        'reactions'  {node: (Rx, Ry)} from the single-load solve
        'note'       None, or why nothing could be traced
    """
    out = {'start': start_node, 'magnitude': 0.0, 'forces': {}, 'share': {},
           'supports': {}, 'order': [], 'reactions': {}, 'note': None}

    load = next((l for l in (loads or []) if l['node'] == start_node), None)
    if load is None:
        out['note'] = 'No load is applied at that joint.'
        return out
    mag = math.hypot(load.get('fx', 0.0), load.get('fy', 0.0))
    if mag < 1e-9:
        out['note'] = 'The load at that joint is zero.'
        return out
    out['magnitude'] = mag

    # The same structure, carrying this load and nothing else.
    res, err = analyze_fn(nodes, rods, [dict(load)], supports, plates)
    if err or not res:
        out['note'] = err or 'The structure could not be solved.'
        return out

    rod_res = res.get('rod_res', [])
    forces = {i: float(r.get('force', 0.0)) for i, r in enumerate(rod_res)}
    peak = max((abs(v) for v in forces.values()), default=0.0)
    out['forces'] = forces
    if peak > 1e-12:
        out['share'] = {i: abs(v) / peak for i, v in forces.items()
                        if abs(v) / peak >= MIN_SHARE}

    # Where it lands. The reactions of a single-load solve ARE the split,
    # so this is statics, not an estimate.
    total = 0.0
    for node, rxn in (res.get('reactions') or {}).items():
        rx, ry = rxn.get('rx', 0.0), rxn.get('ry', 0.0)
        out['reactions'][node] = (rx, ry)
        total += math.hypot(rx, ry)
    if total > 1e-12:
        for node, (rx, ry) in out['reactions'].items():
            frac = math.hypot(rx, ry) / total
            if frac > 1e-6:
                out['supports'][node] = frac

    out['order'] = _outward_order(rods, start_node, out['share'])
    if not out['share']:
        out['note'] = ('This load alone puts no measurable force in any '
                       'member -- it is carried straight into a support '
                       'under it.')
    return out


def _outward_order(rods, start_node, share):
    """The carrying members, nearest the load first.

    Breadth-first over the joints from the loaded one, so an animation
    runs outward the way the load travels rather than in index order.
    """
    at = {}
    for i, rod in enumerate(rods):
        at.setdefault(rod['a'], []).append(i)
        at.setdefault(rod['b'], []).append(i)

    order, seen_rod, seen_node = [], set(), {start_node}
    frontier = [start_node]
    while frontier:
        nxt = []
        for joint in frontier:
            for ri in at.get(joint, ()):
                if ri in seen_rod:
                    continue
                seen_rod.add(ri)
                if ri in share:
                    order.append(ri)
                rod = rods[ri]
                far = rod['b'] if rod['a'] == joint else rod['a']
                if far not in seen_node:
                    seen_node.add(far)
                    nxt.append(far)
        frontier = nxt
    return order


def flow_direction(nodes, rods, ri, forces, start_node, rods_at=None):
    """Which way to draw the chevrons on member `ri`: a unit vector.

    A member in TENSION hands its load on toward the end it is pulling;
    one in COMPRESSION pushes it on the other way. Both are drawn running
    AWAY from the loaded joint, because that is the direction the load is
    travelling, which is what the animation is about.
    """
    rod = rods[ri]
    a, b = rod['a'], rod['b']
    # Which end is nearer the load, by hop count, decides the sense.
    near = a if _hops(rods, start_node, a) <= _hops(rods, start_node, b) else b
    far = b if near == a else a
    ux, uy = _unit(nodes, near, far)
    return ux, uy


def _hops(rods, start, target, limit=60):
    if start == target:
        return 0
    at = {}
    for rod in rods:
        at.setdefault(rod['a'], []).append(rod['b'])
        at.setdefault(rod['b'], []).append(rod['a'])
    seen, frontier, d = {start}, [start], 0
    while frontier and d < limit:
        d += 1
        nxt = []
        for n in frontier:
            for m in at.get(n, ()):
                if m == target:
                    return d
                if m not in seen:
                    seen.add(m)
                    nxt.append(m)
        frontier = nxt
    return limit


def summary(result, joint_name=str, force_fmt=None):
    """One sentence: where this load lands, biggest share first."""
    if result.get('note'):
        return result['note']
    rows = sorted(result['supports'].items(), key=lambda kv: -kv[1])
    if not rows:
        return 'This load does not reach a support.'
    parts = ['%s %.0f%%' % (joint_name(node), share * 100)
             for node, share in rows]
    head = 'The load at %s lands on: %s.' % (joint_name(result['start']),
                                             ', '.join(parts))
    if force_fmt is not None and result['forces']:
        worst = max(result['forces'].items(), key=lambda kv: abs(kv[1]))
        head += (' Its hardest-working member is rod %d at %s.'
                 % (worst[0], force_fmt(worst[1])))
    return head
