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
    where it is half the real depth. Otherwise the member is one of the
    hand-typed E/A/I/J sets, and the fall-back is the equivalent
    THIN-WALLED ROUND TUBE: for one, I/A = r^2/2, so c = r = r_gyr*sqrt(2).
    That is the same doubly-symmetric round/square hollow section
    stereo_math._rigid_local_stiffness already assumes when it takes
    Iy = Iz = I, so the two halves of the app agree about what an
    unspecified space-structure member is made of.
    """
    I = float(member.get('I', 0.0) or 0.0)
    c = float(member.get('c_cm', 0.0) or 0.0)
    if c <= 0.0:
        r = float(member.get('r_gyr', 0.0) or 0.0)
        c = r * math.sqrt(2.0)
    return (I / c) if (c > 1e-12 and I > 0.0) else 0.0


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
                 member_res=None):
    """Check one member's axial force against its CIRSOC/AISC capacity.

    `axial_force_kN` is signed: positive = tension, negative = compression
    (the sign convention `stereo_math.analyze` already returns).

    A member missing the fields a check needs (Fy, and r_gyr for a
    compression check) returns a result with `checked=False` and a `note`
    explaining what is missing, rather than raising or silently reporting
    a meaningless utilisation -- a member's section may simply not be
    sized yet while the geometry is still being explored.
    """
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

    # Iy = Iz = I is already assumed by the stiffness matrix, so one
    # capacity serves both bending axes.
    ratio = (Pr_N / Pc_N) if Pc_N > 1e-9 else float('inf')
    m_sum = (Mrx + Mry) / Mc
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


def check_all_members(nodes, members, member_res, code=cirsoc.CIRSOC_301):
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
                                member_res=res))
    return out


def worst_utilization(checks):
    """The governing (highest) utilisation across every checked member, or
    None if nothing has a checkable section yet -- used by the UI to show
    one headline number without the caller re-deriving max() with the
    'checked' filter every time."""
    vals = [c['util'] for c in checks if c.get('checked')]
    return max(vals) if vals else None
