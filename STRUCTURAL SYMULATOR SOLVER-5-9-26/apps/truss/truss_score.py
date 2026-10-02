"""How good a truss is, in one line: what it weighs, what it carries, and
whether it passes -- the Truss tab's twin of apps/stereo/stereo_score.

The score to beat is the lightest design that passes: two trusses for the
same span and load compare on kilograms, and one that fails does not score
at all. Kept free of Tk.
"""
from . import truss_design as td

G = 9.80665                   # m/s², kN/m³ of unit weight -> kg/m³


def mass_kg(nodes, rods, unit_weight=td.STEEL_UNIT_WEIGHT):
    """Every rod's A·L at the unit weight of steel."""
    return sum(r['A'] * 1e-4 * td.rod_length_m(nodes, r) * unit_weight
               for r in rods) * 1000.0 / G


def score(nodes, rods, results=None, checks=None, self_weight_on=False,
          unit_weight=td.STEEL_UNIT_WEIGHT):
    """{'mass_kg', 'own_kN', 'carried_kN', 'ratio', 'util', 'rod',
    'passes', 'n_over'}. Without a solve only the mass is known.

    `carried_kN` is the vertical load taken to the supports, less the
    truss's own weight when that is one of the loads (carrying itself is
    not the brief). `ratio` is that load over its own weight: "it carries
    120 times what it weighs"."""
    mass = mass_kg(nodes, rods, unit_weight)
    own = mass * G / 1000.0
    out = {'mass_kg': mass, 'own_kN': own, 'carried_kN': None,
           'ratio': None, 'util': None, 'rod': None, 'passes': None,
           'n_over': 0}
    if results is None:
        return out
    ry = abs(sum(r.get('ry', 0.0) for r in results['reactions'].values()))
    carried = ry - own if self_weight_on else ry
    out['carried_kN'] = carried
    if own > 1e-12 and carried > 1e-9:
        out['ratio'] = carried / own
    gov = td.governing(checks or [])
    if gov is not None:
        out['rod'], out['util'] = gov[0], gov[1]['util']
        out['passes'] = gov[1]['util'] <= 1.0 + 1e-9
        out['n_over'] = sum(1 for c in checks if c.get('checked')
                            and (c.get('util') or 0.0) > 1.0 + 1e-9)
    return out


def describe(s):
    """The score as one line of plain words."""
    if s is None:
        return ''
    text = 'Weighs %.0f kg' % s['mass_kg']
    if s['carried_kN'] is not None and s['carried_kN'] > 1e-9:
        text += ', carries %.1f kN' % s['carried_kN']
        if s['ratio']:
            text += ' (%.0f × its own weight)' % s['ratio']
    if s['passes'] is True:
        text += ', passes (%.2f).' % s['util']
    elif s['passes'] is False:
        text += ', FAILS: %d rod(s) over capacity.' % s['n_over']
    else:
        text += '.'
    return text


def better(new, best):
    """True when `new` is a passing design lighter than `best` (or there
    is no best yet)."""
    if not new or new.get('passes') is not True:
        return False
    return best is None or new['mass_kg'] < best['mass_kg'] - 1e-9
