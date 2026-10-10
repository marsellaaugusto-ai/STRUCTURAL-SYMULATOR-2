"""Roles: the axis that cuts ACROSS the group tree.

A group answers *what belongs to what*. It is a tree, so every rod has
exactly one, and that is right for ownership and for a take-off.

It is the wrong shape for the other question people keep asking: *show me
every diagonal*, *select the top chords*, *which bottom chords are over
capacity*. A diagonal exists in every group, so "the diagonals" is not a
branch of anything and can never be one. Forcing those questions through
the tree is what grew the Groups panel a checkbox at a time.

The data has been here the whole while. Every generator already writes a
ROLE on each member -- `top_chord`, `bottom_chord`, `diagonal`, `purlin`,
`hoop`, `meridian`, the column and crane parts -- and the reports read it.
Nothing in the tab ever let a user see it, select by it, or hide by it.
This module is that axis, and nothing more: it classifies and selects. It
never owns geometry, and a role is never a container.

A RULE is a saved question rather than a saved list:

    {'name': 'Overloaded diagonals',
     'roles': {'diagonal'}, 'groups': None,
     'util_min': 1.0, 'util_max': None, 'conn': None, 'exclude': False}

Stored as a question, it answers itself again after the model changes. A
saved LIST of rod numbers would be correct the day it was made and quietly
wrong after the next edit -- which is the same reason node membership is
derived rather than stored (see stereo_groups).

`exclude` LEAVES THE MATCHING RODS OUT OF THE ANALYSIS. A group could
already be left out one at a time; asking the question instead means
temporary works, or a crane's rigging, or everything of a role, drops out
of the solve and stays out as the model grows, without anyone having to
remember to flag the next group.

    AND IT IS WHY A RULE ABOUT UTILISATION CANNOT DO IT. Utilisation comes
    OUT of the analysis, and excluding rods changes the analysis -- so such
    a rule would answer differently every time it was asked, and the model
    would solve to a different answer depending on how many times Analyze
    had been pressed. Not an error anyone would see: just a number that
    moves. `can_exclude` refuses it where the rule is written, and
    `excluded_by` asks without the check results at all, so the refusal
    holds even for a rule that got the flag some other way.

Kept free of Tk, so all of it is tested without a window.
"""
from apps.stereo import stereo_groups as sgp

#: How a role reads to a person. Anything not here is prettified from its
#: own name, so a generator can add a role without touching this file.
ROLE_LABELS = {
    'top_chord': 'Top chord', 'bottom_chord': 'Bottom chord',
    'diagonal': 'Diagonal', 'brace': 'Brace', 'edge_brace': 'Edge brace',
    'lateral_brace': 'Lateral brace', 'purlin': 'Purlin', 'hoop': 'Hoop',
    'meridian': 'Meridian', 'outer_rib': 'Outer rib', 'inner_rib': 'Inner rib',
    'surface_chord': 'Surface chord', 'reinf_chord': 'Reinforcing chord',
    'cross_beam': 'Cross beam', 'capital': 'Capital',
    'capital_ring': 'Capital ring', 'column_chord': 'Column chord',
    'column_shaft': 'Column shaft', 'column_tie': 'Column tie',
    'column_web': 'Column web', 'crane_mast': 'Crane mast',
    'crane_cable': 'Crane cable', 'module_edit': 'Module edit',
    'user_rod': 'Drawn by hand',
}

#: What a rod with no role at all is called. Not an error: a model merged
#: or imported from elsewhere arrives without roles, and it still has to be
#: listed, or its rods would vanish from the one place that counts them.
UNSET = ''
UNSET_LABEL = 'No role'


def label(role):
    if not role:
        return UNSET_LABEL
    if role in ROLE_LABELS:
        return ROLE_LABELS[role]
    return str(role).replace('_', ' ').capitalize()


def roles_in(members):
    """{role: [rod indices]}, in a stable, readable order.

    Ordered by count, biggest first, with the unrolled rods last -- so the
    list opens on the roles that actually make up the structure, and the
    leftovers do not sit at the top pushing them down.
    """
    out = {}
    for i, m in enumerate(members):
        out.setdefault(m.get('role') or UNSET, []).append(i)
    named = {k: v for k, v in out.items() if k != UNSET}
    rows = sorted(named.items(), key=lambda kv: (-len(kv[1]), label(kv[0])))
    if UNSET in out:
        rows.append((UNSET, out[UNSET]))
    return dict(rows)


def rods_with_role(members, roles):
    """Every rod whose role is in `roles`."""
    want = {r or UNSET for r in roles}
    return [i for i, m in enumerate(members)
            if (m.get('role') or UNSET) in want]


# ── rules: a saved question, not a saved list ─────────────────────────────

def new_rule(name, roles=None, groups=None, util_min=None, util_max=None,
             conn=None, exclude=False):
    rule = {'name': (str(name).strip() or 'Rule'),
            'roles': set(roles) if roles else None,
            'groups': set(groups) if groups else None,
            'util_min': None if util_min is None else float(util_min),
            'util_max': None if util_max is None else float(util_max),
            'conn': conn or None,
            'exclude': bool(exclude)}
    # A rule that asks about utilisation can never leave rods out, however
    # it was built -- see the note at the top of this file. Refused here
    # rather than trusted to the caller, because every way of making a
    # rule comes through this function.
    if rule['exclude'] and not can_exclude(rule):
        rule['exclude'] = False
    return rule


def asks_about_utilisation(rule):
    return (rule or {}).get('util_min') is not None \
        or (rule or {}).get('util_max') is not None


def can_exclude(rule):
    """Whether this rule may leave its rods out of the analysis.

    Only the questions whose answer does not come out of the analysis. A
    rule about roles, groups or connections asks about the model as drawn,
    so it gives the same answer before and after a solve; one about
    utilisation asks about the solve itself, and using it to change the
    solve makes the answer depend on itself.
    """
    return not asks_about_utilisation(rule)


def describe(rule):
    """The rule in words, for the list and the status bar."""
    bits = []
    if rule.get('roles'):
        bits.append(' or '.join(sorted(label(r) for r in rule['roles'])))
    else:
        bits.append('any rod')
    if rule.get('conn'):
        bits.append('%s joints' % rule['conn'])
    lo, hi = rule.get('util_min'), rule.get('util_max')
    if lo is not None and hi is not None:
        bits.append('utilisation %.2f to %.2f' % (lo, hi))
    elif lo is not None:
        bits.append('utilisation over %.2f' % lo)
    elif hi is not None:
        bits.append('utilisation under %.2f' % hi)
    if rule.get('groups'):
        bits.append('in %d group(s)' % len(rule['groups']))
    said = ', '.join(bits)
    if rule.get('exclude'):
        said += ' -- left out of the analysis'
    return said


def excluded_by(rules, members, groups=()):
    """Every rod a rule leaves out of the analysis.

    Asked WITHOUT the check results, deliberately. A rule about utilisation
    must not take part -- its answer comes out of the solve it would be
    changing -- and `matching` already returns nothing for such a rule when
    it has no checks to read. So the circularity is refused twice: once
    where the rule is written, and once here, where it would do the damage.
    """
    out = set()
    for rule in rules or ():
        if not rule.get('exclude') or not can_exclude(rule):
            continue
        out.update(matching(rule, members, groups, checks=None))
    return out


def matching(rule, members, groups=(), checks=None):
    """The rods this rule selects, right now.

    `checks` is the app's member_checks (or None). A rule that asks about
    utilisation matches NOTHING until there is a solve to ask -- rather
    than silently matching everything, which would hide or select the whole
    model the first time someone saved such a rule before analysing.
    """
    wants_util = rule.get('util_min') is not None or \
        rule.get('util_max') is not None
    if wants_util and not checks:
        return []

    in_groups = None
    if rule.get('groups'):
        in_groups = set()
        for gid in rule['groups']:
            in_groups.update(sgp.rods_of(groups, gid, deep=True))

    out = []
    for i, m in enumerate(members):
        if rule.get('roles') and (m.get('role') or UNSET) not in rule['roles']:
            continue
        if rule.get('conn') and m.get('conn', 'pin') != rule['conn']:
            continue
        if in_groups is not None and i not in in_groups:
            continue
        if wants_util:
            chk = checks[i] if i < len(checks) else None
            util = (chk or {}).get('util')
            if util is None:
                continue
            if rule.get('util_min') is not None and util < rule['util_min']:
                continue
            if rule.get('util_max') is not None and util > rule['util_max']:
                continue
        out.append(i)
    return out
