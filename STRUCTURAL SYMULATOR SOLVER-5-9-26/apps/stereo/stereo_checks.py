"""CIRSOC 301 / AISC 360 member checks for the Stereo tab.

Unlike the Truss tab -- where cirsoc_301 is only reached through
truss_plates.py for a gusset or shear panel, and a plain rod's axial force
is never code-checked at all (see HANDOFF_MANIFESTO_2026-09-10.md sec. on
Truss conventions) -- every member here gets a real member-level check:
tension yield (H.3.4, via `cirsoc_301.stress_check`) or compression
buckling (E3, via `cirsoc_301.compression_strength`), because a space
structure's members are exactly the elements a code check is meant for
(there is no gusset-plate abstraction standing in for them).

Units at this boundary: mm, N, MPa (cirsoc_301's own convention). Members
store E in GPa, A in cm², Fy/Fu in MPa, exactly like the rest of
stereo_math.py -- so the only conversions needed here are cm² -> mm²
(x100) and kN -> N (x1000), both done once at the top of `check_member`.
"""
import math

import cirsoc_301 as cirsoc


def elastic_section_modulus_cm3(member):
    """S = I / c, in cm3 -- what a bending check needs and the member
    record does not directly carry.

    `c_cm` is present when the section came from the profile catalog,
    where it is the real extreme-fibre distance. Otherwise the member is one
    of the hand-typed E/A/I/J sets, and the fall-back is the equivalent
    THIN-WALLED ROUND TUBE: for one, I = A*R^2/2, so c = R = sqrt(2*I/A).
    That is the same doubly-symmetric round/square hollow section
    stereo_math._rigid_local_stiffness already assumes when it takes
    Iy = Iz = I, so the two halves of the app agree about what an
    unspecified space-structure member is made of.

    The fall-back is built from I and A, NOT from r_gyr. It used to be
    r_gyr*sqrt(2), which is the same number for a round tube -- but it tied
    the BENDING check to the BUCKLING radius. When r_gyr was corrected to
    the minor principal radius (it had been the strong axis, overstating
    buckling capacity up to 26x), that coupling would have shrunk c by the
    same factor for any catalog section that lost its c_cm on the way to a
    member, and overstated bending capacity about 3x for an IPE. I and A are
    the properties the bending check is about; the radius a strut buckles
    about is a different question. Built from I = Ix, this gives c about
    14% larger than the real depth for I-sections and 9% for channels --
    conservative, which is the direction a guess must err in.

    It is still a GUESS, and no catalog section should reach it: it is 39%
    unsafe for an angle and 7% for a thick round tube. stereo_profiles
    gives every catalog shape its real c_mm for exactly that reason.
    """
    I = float(member.get('I', 0.0) or 0.0)
    c = float(member.get('c_cm', 0.0) or 0.0)
    if c <= 0.0:
        A = float(member.get('A', 0.0) or 0.0)
        c = math.sqrt(2.0 * I / A) if (A > 0.0 and I > 0.0) else 0.0
    return (I / c) if (c > 1e-12 and I > 0.0) else 0.0


def weak_axis_capacity_kNm(member, code=cirsoc.CIRSOC_301):
    """phi_b * Fy * Iw / cw, about the weak axis -- or the strong-axis
    capacity when the member has no weak axis of its own (a hand-typed
    section, taken as doubly symmetric, as the stiffness matrix takes it)."""
    Iw = float(member.get('Iw', 0.0) or 0.0)
    cw = float(member.get('cw_cm', 0.0) or 0.0)
    Fy = float(member.get('Fy', 0.0) or 0.0)
    if Iw <= 0.0 or cw <= 0.0 or Fy <= 0.0:
        return flexural_capacity_kNm(member, code)
    return code.phi_flexure * Fy * (Iw / cw * 1e3) / 1e6


def flexural_capacity_kNm(member, code=cirsoc.CIRSOC_301):
    """phi_b * Fy * S -- the YIELDING limit state only.

    Lateral-torsional and local buckling are NOT checked. For the closed
    round or square hollow section these members are assumed to be that
    is the right answer, because a closed section does not lateral-
    torsionally buckle. For an open I-section under a long unbraced
    length it is NOT conservative, which is why the report says which
    limit state this ratio came from rather than printing a bare number.
    """
    S_cm3 = elastic_section_modulus_cm3(member)
    Fy = float(member.get('Fy', 0.0) or 0.0)
    if S_cm3 <= 0.0 or Fy <= 0.0:
        return 0.0
    # cm3 -> mm3 (x1000), MPa*mm3 = N*mm -> kN*m (/1e6)
    return code.phi_flexure * Fy * (S_cm3 * 1e3) / 1e6


def check_member(member, axial_force_kN, code=cirsoc.CIRSOC_301,
                 member_res=None, timber=None):
    """Check one member's axial force against its CIRSOC/AISC capacity.

    `axial_force_kN` is signed: positive = tension, negative = compression
    (the sign convention `stereo_math.analyze` already returns).

    A member missing the fields a check needs (Fy, and r_gyr for a
    compression check) returns a result with `checked=False` and a `note`
    explaining what is missing, rather than raising or silently reporting
    a meaningless utilisation -- a member's section may simply not be
    sized yet while the geometry is still being explored.
    """
    if member.get('timber'):
        # CIRSOC 601, not 301 -- an allowable-stress check whose factors
        # (load duration, service condition, temperature, load sharing)
        # are `timber`, the app's timber settings; see stereo_timber.
        from apps.stereo import stereo_timber as stt
        return stt.member_check(member, axial_force_kN, member_res, timber)
    if member.get('aluminium'):
        # CIRSOC 701 (LRFD, like 301) -- its own alloys, buckling
        # constants and wall slenderness; see stereo_aluminium.
        from apps.stereo import stereo_aluminium as sal
        return sal.member_check(member, axial_force_kN, member_res)

    A_mm2 = member.get('A', 0.0) * 100.0        # cm^2 -> mm^2
    Fy = member.get('Fy')
    L_m = member.get('_length_m', 0.0)
    K = member.get('K', 1.0)

    if not Fy or A_mm2 <= 0:
        return {'checked': False, 'note': 'no cross-section (A, Fy) assigned yet',
                'util': None, 'governing': None}

    N = axial_force_kN * 1e3   # kN -> N

    if N >= 0.0:
        sigma = N / A_mm2
        chk = cirsoc.stress_check(sigma, 0.0, Fy, code)
        out = {'checked': True, 'mode': 'tension', 'util': chk.util,
               'governing': chk.governing, 'sigma_MPa': sigma,
               'capacity_MPa': chk.Fn_normal, 'ok': chk.util <= 1.0 + 1e-9}
        Pc_N = chk.Fn_normal * A_mm2
    else:
        r_gyr_cm = member.get('r_gyr')
        if not r_gyr_cm or r_gyr_cm <= 0:
            return {'checked': False,
                    'note': 'compression member has no radius of gyration (r_gyr) assigned',
                    'util': None, 'governing': None}
        r_mm = r_gyr_cm * 10.0
        KL_over_r = (K * L_m * 1000.0) / r_mm if r_mm > 1e-9 else float('inf')
        res = cirsoc.compression_strength(A_mm2, KL_over_r, Fy, code,
                                          required=abs(N))
        out = {'checked': True, 'mode': 'compression', 'util': res.util,
               'governing': res.governing, 'Fcr_MPa': res.Fcr,
               'Pd_kN': res.Pd / 1e3, 'slenderness': KL_over_r,
               'ok': res.util <= 1.0 + 1e-9}
        Pc_N = res.Pd

    return _add_bending_interaction(out, member, member_res, abs(N), Pc_N, code)


def _add_bending_interaction(out, member, member_res, Pr_N, Pc_N, code):
    """Fold bending into the member's ratio, per CIRSOC 301 / AISC 360 H1.1.

        Pr/Pc >= 0.2 :  Pr/Pc + (8/9)(Mrx/Mcx + Mry/Mcy) <= 1
        Pr/Pc <  0.2 :  Pr/(2Pc) + (Mrx/Mcx + Mry/Mcy)   <= 1

    The axial ratio is kept as a FLOOR on the answer, which matters more
    than it looks: with no moment at all the second branch collapses to
    Pr/(2Pc) and would halve the utilisation of every lightly-loaded rod.
    H1.1 governs combined action; the pure axial limit state still has to
    be satisfied on its own. Taking the max of the two is what makes a
    pin-jointed model -- which carries no moment anywhere -- come out of
    this with exactly the numbers it had before bending was checked.

    `Mr` is the PEAK along the member, not the larger end value: under a
    span load the governing section sits between the ends.
    """
    out['util_axial'] = out['util']
    if not member_res or member_res.get('conn') != 'rigid':
        return out

    from apps.stereo import stereo_math as sm
    diag = sm.member_diagram(member_res)
    Mrx = max((abs(v) for v in diag['Mz']), default=0.0)     # about local z
    Mry = max((abs(v) for v in diag['My']), default=0.0)     # about local y
    out['M_demand_kNm'] = math.hypot(Mrx, Mry)
    out['V_demand_kN'] = max((abs(v) for v in diag['V']), default=0.0)
    out['T_demand_kNm'] = abs(member_res.get('T', 0.0))
    if Mrx <= 1e-12 and Mry <= 1e-12:
        return out

    Mc = flexural_capacity_kNm(member, code)
    out['M_capacity_kNm'] = Mc
    if Mc <= 1e-12:
        out['bending_note'] = ('carries bending but no section modulus could '
                               'be formed (needs I and r_gyr, or a catalog profile)')
        return out

    # Each moment against its own axis's capacity, as H1.1 writes it. My --
    # about local y, the vertical plane -- is the strong axis; Mz the weak
    # one (see stereo_math._rigid_local_stiffness). A section with no weak
    # axis of its own is doubly symmetric and both capacities are Mc.
    Mc_w = weak_axis_capacity_kNm(member, code)
    out['M_capacity_weak_kNm'] = Mc_w
    ratio = (Pr_N / Pc_N) if Pc_N > 1e-9 else float('inf')
    m_sum = Mry / Mc + (Mrx / Mc_w if Mc_w > 1e-12 else float('inf'))
    if ratio >= 0.2:
        h1 = ratio + (8.0 / 9.0) * m_sum
        branch = 'H1-1a (P/Pc >= 0.2)'
    else:
        h1 = ratio / 2.0 + m_sum
        branch = 'H1-1b (P/Pc < 0.2)'

    out['util_interaction'] = h1
    out['util'] = max(out['util_axial'], h1)
    out['ok'] = out['util'] <= 1.0 + 1e-9
    if h1 >= out['util_axial']:
        out['governing'] = f"{branch}, axial + bending"
    out['mode'] = out['mode'] + ' + bending'
    return out


def check_all_members(nodes, members, member_res, code=cirsoc.CIRSOC_301,
                      timber=None):
    """Run `check_member` on every member. Returns a list parallel to
    `members`/`member_res`. Attaches each member's own length so the caller
    never has to recompute it (and cannot disagree with what the solver
    used) -- see `_length_m` consumed above."""
    from apps.stereo import stereo_math as sm
    out = []
    for m, res in zip(members, member_res):
        _, _, _, L = sm.member_vector(nodes, m)
        m_with_len = dict(m, _length_m=L)
        out.append(check_member(m_with_len, res.get('N', 0.0), code,
                                member_res=res, timber=timber))
    return out


def worst_utilization(checks):
    """The governing (highest) utilisation across every checked member, or
    None if nothing has a checkable section yet -- used by the UI to show
    one headline number without the caller re-deriving max() with the
    'checked' filter every time."""
    vals = [c['util'] for c in checks if c.get('checked')]
    return max(vals) if vals else None


# ── one section for a whole group of rods ──────────────────────────────────
#
# Roadmap v2 4.1's companion: a group of rods is usually FABRICATED alike,
# and one section for the branch is cheaper to build than five sections that
# each just fit. So: what is the smallest catalog section that carries EVERY
# rod in the group?
#
# Two things about this are easy to get wrong, and both are why the search
# below tries every candidate against every rod rather than sizing for "the
# worst member" and stopping.
#
# FIRST, the rod with the largest force is NOT necessarily the rod that
# decides the section. `check_member` takes compression capacity from KL/r,
# using each rod's OWN length, so a long slender strut at 40 kN can demand a
# heavier section than a short one at 90 kN. Which rod governs therefore
# depends on the candidate section -- it is an output of the search, not an
# input to it. Both are reported: `governing` (closest to capacity in the
# recommendation) and `largest_force` (the biggest |N|), because they differ
# often enough that showing only one would mislead.
#
# SECOND, a recommendation is a FIRST PASS. These structures are
# indeterminate, so changing sections redistributes the forces the
# recommendation was computed from. `recommend_for_group` reports the forces
# it used; applying it and re-analysing may move the answer, and
# `iterate_recommendation` is the loop that settles it.

def _trial_member(member, section, material=None):
    """`member` with `section`'s geometry substituted, everything else kept.

    E/Fy/Fu stay with the member unless a material is given: re-sizing a rod
    is not a decision to change its steel.
    """
    from apps.stereo import stereo_profiles as sp
    out = dict(member)
    sp.put_steel_section(out, section, material)
    return out


def _worst_over(members, member_res, indices, section, code=cirsoc.CIRSOC_301,
                material=None):
    """(worst util, governing index, all utils) for one candidate section."""
    worst, gov = None, None
    utils = {}
    for i in indices:
        if not (0 <= i < len(members) and i < len(member_res)):
            continue
        trial = _trial_member(members[i], section, material)
        res = member_res[i]
        chk = check_member(trial, res.get('N', 0.0), code, member_res=res)
        u = chk.get('util')
        utils[i] = u
        if u is not None and (worst is None or u > worst):
            worst, gov = u, i
    return worst, gov, utils


def recommend_for_group(nodes, members, member_res, indices,
                        candidates=None, code=cirsoc.CIRSOC_301,
                        material=None, target_util=1.0):
    """The lightest catalog section that carries every rod in `indices`.

    Returns a dict, or None if `indices` holds nothing checkable:

        name            the recommended section, or None if nothing fits
        worst_util      its utilisation at the governing rod
        governing       the rod index that decides it
        largest_force   the rod with the biggest |N| -- often NOT `governing`
        utils           {rod index: utilisation} under the recommendation
        spare           1 - worst_util, how much is left at the governing rod
        overshoot       the mean unused capacity across the group, which is
                        the price of one section for the branch
        next_up         the next heavier candidate, for deliberately
                        oversizing to something easier to build
        considered      how many candidates were tried
        forces          {rod index: N} the recommendation was computed FROM
        tried           [(name, worst_util)] in weight order, for a report

    Candidates are ordered by area, so the first that passes is the
    lightest. `target_util` below 1.0 sizes with a margin.
    """
    from apps.stereo import stereo_profiles as sp
    from apps.stereo import stereo_math as sm

    idx = [i for i in sorted(set(indices)) if 0 <= i < len(members)]
    if not idx:
        return None

    # Lengths come from the same helper the solver used, never recomputed
    # differently here.
    with_len = list(members)
    for i in idx:
        _dx, _dy, _dz, L = sm.member_vector(nodes, members[i])
        with_len[i] = dict(members[i], _length_m=L)

    pool = ([sp.CATALOG[n] for n in candidates if n in sp.CATALOG]
            if candidates is not None
            else [sp.CATALOG[n] for n in sp.catalog_names()])
    pool = [s for s in pool if getattr(s, 'A_mm2', 0) > 0]
    pool.sort(key=lambda s: s.A_mm2)
    if not pool:
        return None

    forces = {i: (member_res[i].get('N', 0.0) if i < len(member_res) else 0.0)
              for i in idx}
    largest = max(idx, key=lambda i: abs(forces.get(i, 0.0)))

    tried = []
    best = None
    for sec in pool:
        worst, gov, utils = _worst_over(with_len, member_res, idx, sec, code,
                                        material)
        tried.append((sec.name, worst))
        if worst is None:
            continue            # nothing checkable: no Fy, or no forces yet
        if worst <= target_util + 1e-9:
            best = (sec, worst, gov, utils)
            break

    if best is None:
        # Nothing in the catalog carries it. Report the heaviest and what it
        # would reach, which is more use than a bare "no".
        sec = pool[-1]
        worst, gov, utils = _worst_over(with_len, member_res, idx, sec, code,
                                        material)
        return {'name': None, 'heaviest_tried': sec.name,
                'worst_util': worst, 'governing': gov,
                'largest_force': largest, 'utils': utils, 'spare': None,
                'overshoot': None, 'next_up': None,
                'considered': len(pool), 'forces': forces, 'tried': tried,
                'note': ('No catalog section carries every rod in this group. '
                         'The heaviest tried (%s) reaches %s at rod %s.'
                         % (sec.name,
                            'n/a' if worst is None else '%.2f' % worst,
                            gov))}

    sec, worst, gov, utils = best
    order = [s.name for s in pool]
    at = order.index(sec.name)
    vals = [u for u in utils.values() if u is not None]
    return {'name': sec.name, 'worst_util': worst, 'governing': gov,
            'largest_force': largest, 'utils': utils,
            'spare': (1.0 - worst) if worst is not None else None,
            'overshoot': (1.0 - (sum(vals) / len(vals))) if vals else None,
            'next_up': (order[at + 1] if at + 1 < len(order) else None),
            'considered': len(pool), 'forces': forces, 'tried': tried,
            'note': ''}


def apply_recommendation(members, indices, name, material=None):
    """Give every rod in `indices` the named section. Returns how many.

    This is the bulk edit a group exists for: the rods in a group need not
    start out alike, but setting the group's section sets all of them.
    """
    from apps.stereo import stereo_profiles as sp
    sec = sp.CATALOG.get(name)
    if sec is None:
        raise ValueError('no catalog section named %r' % (name,))
    n = 0
    for i in sorted(set(indices)):
        if 0 <= i < len(members):
            sp.put_steel_section(members[i], sec, material)
            members[i]['profile'] = name
            n += 1
    return n


def iterate_recommendation(nodes, members, loads, supports, indices,
                           candidates=None, code=cirsoc.CIRSOC_301,
                           material=None, target_util=1.0, max_passes=6,
                           panels=None, member_loads=None):
    """Recommend, apply, re-analyse, repeat until the section settles.

    Necessary because the structure is indeterminate: stiffening a branch
    draws more load into it, so the section that just passed under the old
    forces may not pass under the new ones. Each pass re-solves the WHOLE
    structure -- never the branch alone, which would be a different
    structure.

    Returns (recommendation, history, members). `members` is a copy with the
    settled section applied; the caller's list is untouched, so a
    recommendation can be inspected before it is accepted.
    """
    from apps.stereo import stereo_math as sm
    work = [dict(m) for m in members]
    history = []
    rec = None
    for _ in range(max_passes):
        res, err = sm.analyze(nodes, work, loads, supports, panels, member_loads)
        if res is None:
            return None, history + [{'error': err}], work
        rec = recommend_for_group(nodes, work, res['member_res'], indices,
                                  candidates, code, material, target_util)
        if rec is None:
            return None, history, work
        history.append({'name': rec['name'], 'worst_util': rec['worst_util'],
                        'governing': rec['governing']})
        if rec['name'] is None:
            return rec, history, work
        if len(history) >= 2 and history[-1]['name'] == history[-2]['name']:
            rec['settled'] = True
            rec['passes'] = len(history)
            return rec, history, work
        apply_recommendation(work, indices, rec['name'], material)
    if rec is not None:
        rec['settled'] = False
        rec['passes'] = len(history)
        rec['note'] = ((rec.get('note') or '')
                       + ' The section did not settle in %d passes: it is '
                         'alternating as the load redistributes. Treat the '
                         'last one as approximate and check it by hand.'
                       % max_passes).strip()
    return rec, history, work
