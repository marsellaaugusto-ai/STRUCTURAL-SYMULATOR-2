"""A rod's code check, written out as a hand calculation.

What a student checks a program against is a worked solution: the formula,
the numbers put into it, the result, and the article it comes from. The
member checks (stereo_checks for steel, stereo_timber for timber) already
hold every number; this lays them out in that order -- the way StaR2 or a
textbook example does -- so a utilisation on the screen can be followed
back to the clause that produced it.

Kept free of Tk. `explain` returns the steps; `as_text` writes them as the
plain monospace page the app shows. Units are the codes' own (N, mm, MPa,
kN·m), whatever the unit selector shows elsewhere: that is how the
formulas are printed in CIRSOC 301 and 601.
"""
import math

import cirsoc_301 as cirsoc


def _step(title, formula, numbers, result, ref=''):
    return {'title': title, 'formula': formula, 'numbers': numbers,
            'result': result, 'ref': ref}


def _f(x, d=2):
    return f'{x:,.{d}f}'


def explain(member, axial_force_kN, check, member_res=None, length_m=None,
            timber_settings=None, code=cirsoc.CIRSOC_301):
    """The steps of `check` (one entry of member_checks) for `member`.

    Returns {'heading': str, 'steps': [step...], 'util': float|None,
    'verdict': str}. A rod without a check (no section, unloaded) gets a
    heading and the reason, and no steps."""
    L = float(length_m if length_m is not None
              else member.get('_length_m', 0.0) or 0.0)
    if not check or not check.get('checked'):
        return {'heading': 'This rod has no code check',
                'steps': [], 'util': None,
                'verdict': (check or {}).get('note', 'nothing to check')}
    if check.get('mode') == 'unloaded':
        return {'heading': 'This rod carries nothing in this load case',
                'steps': [], 'util': check.get('util'),
                'verdict': check.get('note', '')}
    if check.get('material') == 'timber':
        out = _explain_timber(member, axial_force_kN, check, L,
                              timber_settings)
    else:
        out = _explain_steel(member, axial_force_kN, check, member_res, L,
                             code)
    util = check.get('util')
    out['util'] = util
    out['verdict'] = (f'utilisation {util:.3f} -- '
                      + ('OK' if util is not None and util <= 1.0 + 1e-9
                         else 'OVER CAPACITY'))
    return out


# ── steel: CIRSOC 301 ─────────────────────────────────────────────────────

def _explain_steel(member, N_kN, chk, member_res, L, code):
    A = float(member.get('A', 0.0)) * 100.0             # mm²
    Fy = float(member.get('Fy', 0.0))
    N = float(N_kN) * 1e3                                # N
    steps = []
    heading = (f'Steel, {code.name} -- '
               f'A = {_f(A, 0)} mm², Fy = {_f(Fy, 0)} MPa, L = {_f(L, 3)} m')
    if N >= 0:
        sigma = N / A
        phiFy = code.phi_normal * Fy
        steps.append(_step('Axial stress', 'σ = N / A',
                           f'{_f(N, 0)} N / {_f(A, 0)} mm²',
                           f'{_f(sigma)} MPa'))
        steps.append(_step('Design stress', 'φ · Fy',
                           f'{code.phi_normal} × {_f(Fy, 0)}',
                           f'{_f(phiFy)} MPa', 'H.3.4'))
        steps.append(_step('Tension ratio', 'σ / (φ Fy)',
                           f'{_f(sigma)} / {_f(phiFy)}',
                           f'{sigma / phiFy:.3f}', 'H.3.4'))
        Pc = phiFy * A
    else:
        K = float(member.get('K', 1.0) or 1.0)
        r = float(member.get('r_gyr', 0.0)) * 10.0       # mm
        KLr = K * L * 1000.0 / r
        E = cirsoc.E_STEEL
        Fcr, Fe, branch = cirsoc.compression_critical_stress(KLr, Fy, E)
        lim = 4.71 * math.sqrt(E / Fy)
        Pn = Fcr * A
        Pd = code.phi_compression * Pn
        steps.append(_step('Slenderness', 'K·L / r',
                           f'{K:g} × {_f(L * 1000, 0)} mm / {_f(r, 1)} mm',
                           f'{KLr:.1f}', 'E2'))
        steps.append(_step('Euler stress', 'Fe = π² E / (KL/r)²',
                           f'π² × {_f(E, 0)} / {KLr:.1f}²',
                           f'{_f(Fe)} MPa', 'E3-4'))
        steps.append(_step('Which branch', 'KL/r ≤ 4.71 √(E/Fy) ?',
                           f'{KLr:.1f} vs 4.71 √({_f(E, 0)}/{_f(Fy, 0)}) '
                           f'= {lim:.1f}',
                           'inelastic' if KLr <= lim else 'elastic',
                           'E3'))
        if KLr <= lim:
            steps.append(_step('Critical stress', 'Fcr = 0.658^(Fy/Fe) · Fy',
                               f'0.658^({_f(Fy, 0)}/{_f(Fe)}) × {_f(Fy, 0)}',
                               f'{_f(Fcr)} MPa', 'E3-2'))
        else:
            steps.append(_step('Critical stress', 'Fcr = 0.877 · Fe',
                               f'0.877 × {_f(Fe)}', f'{_f(Fcr)} MPa',
                               'E3-3'))
        steps.append(_step('Design strength', 'Pd = φc · Fcr · A',
                           f'{code.phi_compression} × {_f(Fcr)} × '
                           f'{_f(A, 0)}', f'{_f(Pd / 1e3)} kN', 'E3-1'))
        steps.append(_step('Compression ratio', '|N| / Pd',
                           f'{_f(abs(N) / 1e3)} / {_f(Pd / 1e3)}',
                           f'{abs(N) / Pd:.3f}', 'E3'))
        Pc = Pd
    if 'util_interaction' in chk:
        from apps.stereo import stereo_math as sm
        from apps.stereo import stereo_checks as sc
        Mc = chk.get('M_capacity_kNm') or 0.0
        Mcw = chk.get('M_capacity_weak_kNm') or Mc
        diag = sm.member_diagram(member_res) if member_res else None
        Mry = max((abs(v) for v in diag['My']), default=0.0) if diag else 0.0
        Mrx = max((abs(v) for v in diag['Mz']), default=0.0) if diag else 0.0
        S = sc.elastic_section_modulus_cm3(member) * 1e3        # mm³
        steps.append(_step('Bending capacity', 'Mc = φb · Fy · S',
                           f'{code.phi_flexure} × {_f(Fy, 0)} × '
                           f'{_f(S, 0)} mm³', f'{_f(Mc, 3)} kN·m', 'F.1'))
        if abs(Mcw - Mc) > 1e-9:
            Sw = Mcw * 1e6 / (code.phi_flexure * Fy) if Fy else 0.0
            steps.append(_step('Weak-axis capacity', 'Mcw = φb · Fy · Iw/cw',
                               f'{code.phi_flexure} × {_f(Fy, 0)} × '
                               f'{_f(Sw, 0)} mm³', f'{_f(Mcw, 3)} kN·m',
                               'F.1'))
        ratio = abs(N) / Pc if Pc > 0 else float('inf')
        if ratio >= 0.2:
            steps.append(_step('Axial + bending',
                               'Pr/Pc + 8/9 (Mry/Mc + Mrx/Mcw)',
                               f'{ratio:.3f} + 8/9 ({_f(Mry, 3)}/{_f(Mc, 3)}'
                               f' + {_f(Mrx, 3)}/{_f(Mcw, 3)})',
                               f'{chk["util_interaction"]:.3f}', 'H1-1a'))
        else:
            steps.append(_step('Axial + bending',
                               'Pr/(2Pc) + (Mry/Mc + Mrx/Mcw)',
                               f'{ratio:.3f}/2 + ({_f(Mry, 3)}/{_f(Mc, 3)}'
                               f' + {_f(Mrx, 3)}/{_f(Mcw, 3)})',
                               f'{chk["util_interaction"]:.3f}', 'H1-1b'))
    steps.append(_step('Governs', 'the largest ratio', chk.get('governing')
                       or '', f'{chk["util"]:.3f}'))
    return {'heading': heading, 'steps': steps}


# ── timber: CIRSOC 601 ────────────────────────────────────────────────────

def _explain_timber(member, N_kN, chk, L, settings):
    from apps.stereo import stereo_timber as stt
    s = chk.get('settings') or stt.settings_of(settings)
    g = stt.GRADES[chk['grade']]
    f, d, st = chk['factors'], chk['design_MPa'], chk['stresses_MPa']
    wet, temp = s['wet'], s['temperature']

    def cm(p):
        return stt.wet_service_factor(g, p) if wet else 1.0

    def ct(p):
        return stt.temperature_factor(p, wet, temp)

    steps = []
    heading = (f'Timber {chk["grade"]} (Tabla {g["table"]}), '
               f'{stt.REGLAMENTO} -- allowable stress, service loads; '
               + stt.describe_settings(s))
    A = float(member.get('A', 0.0)) * 100.0
    N = float(N_kN) * 1e3
    if 'ft' in st:
        steps.append(_step('Tension stress', 'ft = N / A',
                           f'{_f(N, 0)} N / {_f(A, 0)} mm²', f'{_f(st["ft"])} MPa',
                           '3.4.1'))
        steps.append(_step('Adjusted design value',
                           "F't = Ft · CD · CM · Ct · CF",
                           f'{g["Ft"]:g} × {f["CD"]:g} × {cm("Ft"):g} × '
                           f'{ct("Ft"):g} × {f.get("CF_t", 1.0):.3f}',
                           f'{_f(d["Ft"])} MPa', 'Tabla 4.3-1'))
        steps.append(_step('Tension ratio', "ft / F't",
                           f'{_f(st["ft"])} / {_f(d["Ft"])}',
                           f'{st["ft"] / d["Ft"]:.3f}', '3.4.1'))
    if 'fc' in st:
        c = f['c']
        Emin = g['Emin'] * cm('Emin') * ct('Emin')
        sl = chk['slenderness']
        steps.append(_step('Compression stress', 'fc = |N| / A',
                           f'{_f(abs(N), 0)} N / {_f(A, 0)} mm²',
                           f'{_f(st["fc"])} MPa', '3.3'))
        K = float(member.get('K', 1.0) or 1.0)
        dmin = K * L * 1000.0 / sl if sl else 0.0
        steps.append(_step('Slenderness', 'le / d = K·L / d (the thinner side)',
                           f'{K:g} × {_f(L * 1000, 0)} mm / {_f(dmin, 0)} mm',
                           f'{sl:.1f}  (≤ 50)', '3.3.1'))
        steps.append(_step('Buckling stress', "FcE = 0.822 E'min / (le/d)²",
                           f'0.822 × {_f(Emin, 0)} / {sl:.1f}²',
                           f'{_f(d["FcE"])} MPa', '3.3.1'))
        steps.append(_step('Value before stability', 'Fc* = Fc · CD · CM · Ct',
                           f'{g["Fc"]:g} × {f["CD"]:g} × {cm("Fc"):g} × '
                           f'{ct("Fc"):g}', f'{_f(d["Fc*"])} MPa',
                           'Tabla 4.3-1'))
        a = d['FcE'] / d['Fc*']
        steps.append(_step('Ratio of buckling to crushing', 'α = FcE / Fc*',
                           f'{_f(d["FcE"])} / {_f(d["Fc*"])}', f'{a:.3f}',
                           '3.3.1'))
        steps.append(_step('Column stability factor',
                           'CP = (1+α)/2c − √[((1+α)/2c)² − α/c]',
                           f'(1+{a:.3f})/(2×{c:g}) − √[((1+{a:.3f})/'
                           f'(2×{c:g}))² − {a:.3f}/{c:g}]',
                           f'{f["CP"]:.3f}', '3.3.1-1'))
        steps.append(_step('Adjusted design value', "F'c = Fc* · CP",
                           f'{_f(d["Fc*"])} × {f["CP"]:.3f}',
                           f'{_f(d["Fc"])} MPa', 'Tabla 4.3-1'))
        steps.append(_step('Compression ratio', "fc / F'c",
                           f'{_f(st["fc"])} / {_f(d["Fc"])}',
                           f'{st["fc"] / d["Fc"]:.3f}', '3.3.1'))
    for t in ('1', '2'):
        if 'fb' + t not in st:
            continue
        size = f.get('CF_b' + t, f.get('CV_b' + t, 1.0))
        I = float(member.get('I' if t == '1' else 'Iw', 0.0) or 0.0)
        ce = float(member.get('c_cm' if t == '1' else 'cw_cm', 0.0) or 0.0)
        Sx = I / ce * 1e3 if I and ce else 0.0                 # mm³
        M = st['fb' + t] * Sx / 1e6                         # kN·m
        steps.append(_step(f'Bending stress, axis {t}', 'fb = M / S',
                           f'{_f(M, 3)} kN·m × 10⁶ / {_f(Sx, 0)} mm³',
                           f'{_f(st["fb" + t])} MPa', '3.2.1-1'))
        steps.append(_step(f'Value before stability, axis {t}',
                           'Fb* = Fb · CD · CM · Ct · (CF or CV) · Cr',
                           f'{g["Fb"]:g} × {f["CD"]:g} × {cm("Fb"):g} × '
                           f'{ct("Fb"):g} × {size:.3f} × {f["Cr"]:g}',
                           f'{_f(d["Fb*" + t])} MPa', 'Tabla 4.3-1'))
        steps.append(_step(f'Beam stability, axis {t}', "F'b = Fb* · CL",
                           f'{_f(d["Fb*" + t])} × {f["CL" + t]:.3f}',
                           f'{_f(d["Fb" + t])} MPa', '3.2.1-4'))
    if 'fv' in st:
        steps.append(_step('Shear', ("fv / F'v,  fv = 4V / 3A" if g['product']
                                     == 'pole' else "fv / F'v,  fv = 3V / 2A"),
                           f'{_f(st["fv"])} / {_f(d["Fv"])}',
                           f'{st["fv"] / d["Fv"]:.3f}', '3.2.2'))
    for k, v in chk['ratios'].items():
        if k.startswith('bending +') or k.startswith('bending −'):
            steps.append(_step('Combined', k, '', f'{v:.3f}', ''))
    steps.append(_step('Governs', 'the largest ratio', chk.get('governing')
                       or '', f'{chk["util"]:.3f}'))
    return {'heading': heading, 'steps': steps}


def as_text(expl, title=''):
    """The steps as a monospace page."""
    lines = []
    if title:
        lines += [title, '=' * len(title)]
    lines += [expl['heading'], '']
    for k, s in enumerate(expl['steps'], start=1):
        ref = f'  [{s["ref"]}]' if s['ref'] else ''
        lines.append(f'{k:>2}. {s["title"]}{ref}')
        if s['formula']:
            lines.append(f'      {s["formula"]}')
        if s['numbers']:
            lines.append(f'      = {s["numbers"]}')
        lines.append(f'      = {s["result"]}')
        lines.append('')
    lines.append(expl['verdict'])
    return '\n'.join(lines)
