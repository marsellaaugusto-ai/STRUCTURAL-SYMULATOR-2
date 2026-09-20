import math, sv3d as S, shellgeom as G, ui as U

INK, INK2, MUT, RULE, SOFT = U.INK, U.INK2, U.MUT, U.RULE, U.SOFT
BLUE, RUST = U.BLUE, U.RUST
VIEW = (math.cos(S.EL) * math.sin(S.AZ), math.cos(S.EL) * math.cos(S.AZ), math.sin(S.EL))
NM = [(0.0, (40, 78, 140)), (0.5, (233, 236, 239)), (1.0, (168, 46, 36))]   # compression .. tension


def visible(q):
    n = S.normal(q)
    return n[0] * VIEW[0] + n[1] * VIEW[1] + n[2] * VIEW[2] > 0


def orient(q, want):
    n = S.normal(q)
    return list(reversed(q)) if (n[0] * want[0] + n[1] * want[1] + n[2] * want[2]) < 0 else q


def nforce(x, y):
    """A plausible membrane field: compression over the crown, tension near the
    free edges, so the picture is not a flat wash."""
    r = math.hypot(x / G.A, y / G.B)
    return max(0.0, min(1.0, 0.18 + 0.78 * r ** 2.2))


W, H = 1080, 648
TOP, RAIL, PANW, STAT = 46, 76, 300, 30
o = [U.rect(0, 0, W, H, '#f2f4f6', '#b9c2ca', 1)]

# ── toolbar ────────────────────────────────────────────────────────────────
o.append(U.rect(1, 1, W - 2, TOP, '#e9edf1', None))
o.append(U.line(1, TOP + 1, W - 1, TOP + 1, '#b9c2ca', 1))
o.append(S.text(18, 30, 'SHELL', 15, '#2a5d92', weight='700', family='sans'))
x = 88
for lab, prim, w in [('Generate ▾', False, 96), ('▶ Analyze', True, 92),
                     ('↶', False, 30), ('↷', False, 30),
                     ('Display ▾', False, 86), ('Export ▾', False, 80)]:
    o += U.button(x, 12, w, 24, lab, prim)
    x += w + 8
o.append(S.text(760, 30, 'Load %', 10, MUT, family='sans'))
o.append(U.rect(806, 20, 150, 8, '#ffffff', '#aab4bd', 1, 4))
o.append(U.rect(806, 20, 150, 8, '#cfe0f0', '#aab4bd', 1, 4))
o.append(U.rect(950, 14, 10, 20, '#6f7c86', '#4c565f', 1, 2))
o.append(S.text(966, 30, '100', 10, INK))
o += U.button(992, 12, 76, 24, 'Reset view')

# ── mode rail ──────────────────────────────────────────────────────────────
o.append(U.rect(1, TOP + 2, RAIL, H - TOP - STAT - 3, '#eef2f6', None))
MODES = [('▦', 'Build'), ('∿', 'Shape'), ('▤', 'Mesh'), ('△', 'Support'),
         ('↓', 'Load'), ('≡', 'Thickness'), ('✂', 'Sections'),
         ('◑', 'Analyse'), ('Σ', 'Results')]
for k, (gl, lab) in enumerate(MODES):
    y = TOP + 8 + k * 58
    act = lab == 'Analyse'
    if act:
        o.append(U.rect(1, y, RAIL, 54, '#ffffff', None))
        o.append(U.rect(1, y, 3.5, 54, BLUE, None))
    o.append(S.text(1 + RAIL / 2, y + 26, gl, 17, INK if act else '#5d6a74', 'middle', family='sans'))
    o.append(S.text(1 + RAIL / 2, y + 44, lab, 9.4, INK if act else '#5d6a74', 'middle',
                    '700' if act else '500', 'sans'))
o.append(U.line(RAIL + 1, TOP + 2, RAIL + 1, H - STAT, '#b9c2ca', 1))

# ── context panel: Analyse ─────────────────────────────────────────────────
PX = RAIL + 2
o.append(U.rect(PX, TOP + 2, PANW, H - TOP - STAT - 3, '#eef1f4', None))
o.append(S.text(PX + 14, TOP + 24, 'ANALYSE', 10, MUT, weight='700', family='sans'))
o.append(U.line(PX + 12, TOP + 32, PX + PANW - 12, TOP + 32, SOFT, 1))
gy = TOP + 44
o += U.group(PX + 12, gy, PANW - 24, 158, 'Colour the shell by')
o.append(S.text(PX + 232, gy + 11, '?  guide', 9.6, BLUE, weight='700', family='sans'))
items = [('Membrane force  N\u2081 / N\u2082', True), ('Bending moment  m\u2081 / m\u2082', False),
         ('Wood\u2013Armer design moments', False), ('Required steel  As, cm\u00b2/m', False),
         ('Utilisation (code check)', False), ('Thickness  t', False),
         ('Deflection', False), ('Principal directions', False)]
for k, (s, on) in enumerate(items):
    o += U.radio(PX + 30, gy + 30 + k * 16, s, on, size=9.8)
o += U.group(PX + 12, gy + 172, PANW - 24, 92, 'Draw it as')
for k, (s, on) in enumerate([('Smooth field over the elements', True),
                             ('Per-element flat fill', False),
                             ('Contour bands', False)]):
    o += U.radio(PX + 30, gy + 196 + k * 17, s, on, size=9.8)
o += U.check(PX + 30, gy + 250, 'Show the thickness in 3D', True, size=9.8)
o += U.group(PX + 12, gy + 278, PANW - 24, 132, 'What the solve found')
o.append(U.rect(PX + 28, gy + 302, 246, 46, '#ffffff', RULE, 1, 2))
bars = [0.06, 0.1, 0.17, 0.26, 0.2, 0.13, 0.05, 0.03]
for k, b in enumerate(bars):
    o.append(U.rect(PX + 36 + k * 29, gy + 344 - b * 120, 22, b * 120,
                    S.hexof(S.ramp(k / 7.0, [(0, (106, 168, 116)), (.6, (224, 176, 60)), (1, (186, 60, 44))])), None))
o.append(S.text(PX + 28, gy + 360, 'utilisation of 1 024 elements', 9.2, MUT, family='sans'))
o.append(U.rect(PX + 28, gy + 372, 246, 12, '#ffffff', RULE, 1, 2))
o.append(U.rect(PX + 28, gy + 372, 148, 12, '#33528c', None))
o.append(U.rect(PX + 176, gy + 372, 98, 12, '#a8432e', None))
o.append(S.text(PX + 28, gy + 398, '58% of the shell is in compression', 9.2, MUT, family='sans'))
o.append(U.line(PX + PANW - 1, TOP + 2, PX + PANW - 1, H - STAT, '#b9c2ca', 1))

# ── canvas ─────────────────────────────────────────────────────────────────
CX0 = PX + PANW
o.append(U.rect(CX0, TOP + 2, W - CX0 - 1, H - TOP - STAT - 3, '#ffffff', None))
sc = S.Scene(scale=58.0, cx=(CX0 + W) / 2 - 6, cy=350)
n = 14
xs, ys = G.grid(n)
for i in range(n):
    for j in range(n):
        for s in (+1, -1):
            q = [G.off(xs[i], ys[j], s), G.off(xs[i + 1], ys[j], s),
                 G.off(xs[i + 1], ys[j + 1], s), G.off(xs[i], ys[j + 1], s)]
            q = orient(q, (0, 0, s))
            if not visible(q):
                continue
            v = nforce((xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2)
            sc.face(q, S.hexof(S.shade(q, S.ramp(v, NM), amb=.66, gain=.34)), '#ffffff', 0.35)
edges = ([(xs[i], -G.B, xs[i + 1], -G.B, (0, -1, 0)) for i in range(n)] +
         [(xs[i], G.B, xs[i + 1], G.B, (0, 1, 0)) for i in range(n)] +
         [(-G.A, ys[j], -G.A, ys[j + 1], (-1, 0, 0)) for j in range(n)] +
         [(G.A, ys[j], G.A, ys[j + 1], (1, 0, 0)) for j in range(n)])
for x0, y0, x1, y1, out in edges:
    q = orient([G.off(x0, y0, +1), G.off(x1, y1, +1), G.off(x1, y1, -1), G.off(x0, y0, -1)], out)
    if visible(q):
        sc.face(q, S.hexof(S.shade(q, (64, 82, 98), amb=.6, gain=.38)), '#3a464f', 0.5, bias=.02)
for cx, cy in G.CORNERS:
    p = G.off(cx, cy, -1)
    b = p[2] - 0.40
    sc.face([p, (cx - .18, cy - .18, b), (cx + .18, cy - .18, b)], '#2f6ea8', '#1b4a73', .5, bias=-.4)
    sc.face([p, (cx + .18, cy - .18, b), (cx + .18, cy + .18, b)], '#3f81bd', '#1b4a73', .5, bias=-.4)
o.append(sc.render())

# legend card
o.append(U.rect(CX0 + 10, TOP + 12, 268, 96, '#ffffff', RULE, 1, 3))
o.append(S.text(CX0 + 22, TOP + 30, 'Membrane force N₁, kN/m', 10, INK, weight='700', family='sans'))
for i in range(180):
    o.append(U.rect(CX0 + 22 + i * 1.28, TOP + 38, 1.4, 10, S.hexof(S.ramp(i / 179., NM)), None))
o.append(U.rect(CX0 + 22, TOP + 38, 230, 10, 'none', RULE, .8))
o.append(S.text(CX0 + 22, TOP + 60, '− compression', 9.2, MUT))
o.append(S.text(CX0 + 252, TOP + 60, 'tension +', 9.2, MUT, anchor='end'))
o.append(S.text(CX0 + 22, TOP + 76, '−182', 9.2, INK))
o.append(S.text(CX0 + 137, TOP + 76, '0', 9.2, INK, anchor='middle'))
o.append(S.text(CX0 + 252, TOP + 76, '+64', 9.2, INK, anchor='end'))
o.append(S.text(CX0 + 22, TOP + 94, 'what this colour means →', 9.4, BLUE, family='sans'))

# view cube
o.append(U.rect(W - 150, TOP + 12, 138, 84, '#ffffff', RULE, 1, 3))
o.append(S.text(W - 140, TOP + 26, 'VIEW', 8.6, MUT, weight='700', family='sans'))
for k, s in enumerate(['Iso', 'Top', 'Front', 'Right', 'Back', 'Left']):
    bx = W - 142 + (k % 3) * 44
    by = TOP + 34 + (k // 3) * 26
    o += U.button(bx, by, 40, 20, s, k == 0, size=9)

# selection card
o.append(U.rect(CX0 + 10, H - STAT - 120, 232, 106, '#ffffff', RULE, 1, 3))
o.append(S.text(CX0 + 22, H - STAT - 102, 'SELECTION', 8.6, MUT, weight='700', family='sans'))
for k, s in enumerate(['element 612  ·  quad', 't = 315 mm  (auto, ×2.1)',
                       'N₁ = −164  N₂ = −41 kN/m',
                       'm₁ = 8.4 kNm/m', 'utilisation 0.92  ·  governs: N₁']):
    o.append(S.text(CX0 + 22, H - STAT - 86 + k * 15, s, 9.4, INK if k else INK))

# section preview card
o.append(U.rect(W - 262, H - STAT - 120, 250, 106, '#ffffff', RULE, 1, 3))
o.append(S.text(W - 250, H - STAT - 102, 'SECTION S1', 8.6, MUT, weight='700', family='sans'))
sx, sy, k = W - 246, H - STAT - 30, 34.0
top = [(sx + (x + G.A) * k, sy - G.off(x, 0, +1)[2] * k) for x in [(-G.A + 2 * G.A * i / 60) for i in range(61)]]
bot = [(sx + (x + G.A) * k, sy - G.off(x, 0, -1)[2] * k) for x in [(-G.A + 2 * G.A * i / 60) for i in range(61)]]
o.append('<polygon points="%s" fill="#c6d3de" stroke="#46535e" stroke-width="0.9"/>'
         % ' '.join('%.1f,%.1f' % p for p in top + list(reversed(bot))))
o.append(S.text(W - 246, H - STAT - 18, 't 150 – 315 mm along this cut', 9, MUT, family='sans'))

# ── status bar ─────────────────────────────────────────────────────────────
o.append(U.rect(1, H - STAT, W - 2, STAT - 1, '#e9edf1', None))
o.append(U.line(1, H - STAT, W - 1, H - STAT, '#b9c2ca', 1))
o.append(S.text(18, H - STAT + 19,
                'Analyzed  ·  1 024 elements  ·  1 089 nodes  ·  governing utilisation 0.92  '
                '·  peak deflection 4.1 mm  ·  ΣRz 318 kN  ·  t 150–450 mm  ·  CIRSOC',
                9.8, INK2, family='sans'))

open('fig4_window.svg', 'w').write(S.svg(W, H, '\n'.join(o), '#ffffff'))
print('fig4 written')
