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
import cirsoc_301 as cirsoc


def check_member(member, axial_force_kN, code=cirsoc.CIRSOC_301):
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
        return {'checked': True, 'mode': 'tension', 'util': chk.util,
                'governing': chk.governing, 'sigma_MPa': sigma,
                'capacity_MPa': chk.Fn_normal, 'ok': chk.util <= 1.0 + 1e-9}

    r_gyr_cm = member.get('r_gyr')
    if not r_gyr_cm or r_gyr_cm <= 0:
        return {'checked': False,
                'note': 'compression member has no radius of gyration (r_gyr) assigned',
                'util': None, 'governing': None}
    r_mm = r_gyr_cm * 10.0
    KL_over_r = (K * L_m * 1000.0) / r_mm if r_mm > 1e-9 else float('inf')
    res = cirsoc.compression_strength(A_mm2, KL_over_r, Fy, code, required=abs(N))
    return {'checked': True, 'mode': 'compression', 'util': res.util,
            'governing': res.governing, 'Fcr_MPa': res.Fcr,
            'Pd_kN': res.Pd / 1e3, 'slenderness': KL_over_r,
            'ok': res.util <= 1.0 + 1e-9}


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
        out.append(check_member(m_with_len, res.get('N', 0.0), code))
    return out


def worst_utilization(checks):
    """The governing (highest) utilisation across every checked member, or
    None if nothing has a checkable section yet -- used by the UI to show
    one headline number without the caller re-deriving max() with the
    'checked' filter every time."""
    vals = [c['util'] for c in checks if c.get('checked')]
    return max(vals) if vals else None
