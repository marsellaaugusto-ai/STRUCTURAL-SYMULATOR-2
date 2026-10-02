"""How good a design is, in one line: what it weighs, what it carries, and
whether it passes.

Bridge Designer's lasting idea is the score to beat -- the cheapest bridge
that passes. A space frame's equivalent is its weight against the load it
carries: two designs of the same roof under the same load compare on
kilograms, and a design that fails does not score at all. Kept free of Tk.
"""
import math

from apps.stereo import stereo_math as sm

G = 9.80665                   # kN/m³ of unit weight -> kg/m³ of density


def model_mass_kg(nodes, members, unit_weight_kN_m3=sm.DEFAULT_STEEL_UNIT_WEIGHT):
    """The structure's mass: every rod's A·L at its own unit weight (a
    timber rod at its grade's, stereo_math.member_unit_weight) -- the same
    figure the PDF's take-off sheet totals."""
    kg = 0.0
    for m in members:
        L = math.dist(nodes[m['a']], nodes[m['b']])
        A = float(m.get('A', 0.0) or 0.0)
        kg += (A * 1e-4 * L * sm.member_unit_weight(m, unit_weight_kN_m3)
               * 1000.0 / G)
    return kg


def score(nodes, members, results=None, checks=None,
          unit_weight_kN_m3=sm.DEFAULT_STEEL_UNIT_WEIGHT,
          self_weight_on=False):
    """{'mass_kg', 'own_kN', 'carried_kN', 'ratio', 'util', 'rod', 'passes',
    'n_over'}. Without a solve only the mass is known: the rest is None.

    `carried_kN` is the load the structure takes to the ground at full load
    -- the vertical reactions -- less its own weight when self-weight is
    one of the loads, since carrying itself is not the brief. `ratio` is
    that load over its own weight: "it carries 43 times what it weighs"."""
    mass = model_mass_kg(nodes, members, unit_weight_kN_m3)
    own = mass * G / 1000.0
    out = {'mass_kg': mass, 'own_kN': own, 'carried_kN': None,
           'ratio': None, 'util': None, 'rod': None, 'passes': None,
           'n_over': 0}
    if results is None:
        return out
    rz = abs(sum(r.get('Fz', 0.0) for r in results['reactions'].values()))
    carried = rz - own if self_weight_on else rz
    out['carried_kN'] = carried
    if own > 1e-12 and carried > 1e-9:
        out['ratio'] = carried / own
    best = None
    for i, c in enumerate(checks or ()):
        u = c.get('util')
        if c.get('checked') and u is not None and (best is None or u > best[1]):
            best = (i, u)
    if best is not None:
        out['rod'], out['util'] = best
        out['passes'] = best[1] <= 1.0 + 1e-9
        out['n_over'] = sum(1 for c in checks if c.get('checked')
                            and (c.get('util') or 0.0) > 1.0 + 1e-9)
    return out


def brief_key(nodes, carried_kN):
    """What makes two designs comparable: the same plan and the same load."""
    if not nodes or carried_kN is None:
        return None
    dx = max(p[0] for p in nodes) - min(p[0] for p in nodes)
    dy = max(p[1] for p in nodes) - min(p[1] for p in nodes)
    return (round(dx, 1), round(dy, 1), round(carried_kN))


def mass_text(kg):
    return f'{kg / 1000.0:,.2f} t' if kg >= 10000.0 else f'{kg:,.0f} kg'


def describe(sc, best_kg=None):
    """The two lines the Results panel shows."""
    first = 'Weight ' + mass_text(sc['mass_kg'])
    if sc['carried_kN'] is None:
        return first + ' -- ▶ Analyze to score it', ''
    if sc['ratio'] is not None:
        first += (f'  ·  carries {sc["carried_kN"]:,.0f} kN, '
                  f'{sc["ratio"]:,.1f}× its own weight')
    if sc['passes'] is None:
        return first, 'No rod has a section to check, so it cannot pass yet.'
    if not sc['passes']:
        return first, (f'FAILS: rod {sc["rod"]} at {sc["util"]:.2f}, '
                       f'{sc["n_over"]} over -- a design scores only when it '
                       f'passes.')
    second = f'Passes: the most used rod is at {sc["util"]:.2f}.'
    if best_kg is not None:
        if best_kg + 0.5 >= sc['mass_kg']:
            second += '  Lightest passing design so far.'
        else:
            second += f'  Lightest so far: {mass_text(best_kg)}.'
    return first, second
