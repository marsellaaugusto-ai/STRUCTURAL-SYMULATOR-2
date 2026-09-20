import math, sv3d as S, ui as U

INK, INK2, MUT, RULE, SOFT = U.INK, U.INK2, U.MUT, U.RULE, U.SOFT
BLUE, RUST = U.BLUE, U.RUST
W, H = 1080, 640
o = [U.rect(0, 0, W, H, '#ffffff', None)]

# ══ left: how it reads today ═══════════════════════════════════════════════
o.append(S.text(24, 30, 'TODAY', 10, MUT, weight='700', family='sans'))
o.append(S.text(24, 48, 'the list lives in the top bar, closed', 11, INK2, family='sans'))
o.append(S.text(24, 240, 'drawn from the pattern the other tabs use \u2014 I have not seen your Shell toolbar', 9.4, MUT, family='sans'))
o.append(U.rect(24, 62, 470, 40, '#e9edf1', '#b9c2ca', 1, 2))
x = 34
for lab, w in [('Generate', 66), ('Analyze', 60), ('↶', 22), ('↷', 22)]:
    o += U.button(x, 71, w, 22, lab, False, 9.6)
    x += w + 6
o.append(U.rect(x + 6, 71, 96, 22, '#ffffff', '#8c979f', 1, 2))
o.append(S.text(x + 12, 86, 'Membrane N', 9.6, INK))
o.append(S.text(x + 92, 86, '▾', 9.6, INK))
o.append(U.rect(x + 110, 71, 60, 22, '#ffffff', '#8c979f', 1, 2))
o.append(S.text(x + 116, 86, 'Peak ▾', 9.6, INK))
# the dropdown, open
dx, dy = x + 6, 95
o.append(U.rect(dx, dy, 96, 132, '#ffffff', '#8c979f', 1, 1))
for k, s in enumerate(['Membrane N', 'Moment m', 'Wood-Armer', 'Utilization',
                       'Deflection', 'None']):
    if k == 0:
        o.append(U.rect(dx + 1, dy + 1 + k * 21, 94, 21, '#cfe0f0', None))
    o.append(S.text(dx + 8, dy + 16 + k * 21, s, 9.6, INK))
o += U.leader(206, 150, dx + 48, dy + 60)
o.append(S.text(40, 146, 'every quantity behind one 96 px box,', 10, RUST, family='sans'))
o.append(S.text(40, 160, 'shut by default, and not one word', 10, RUST, family='sans'))
o.append(S.text(40, 174, 'anywhere about what they mean.', 10, RUST, family='sans'))
o.append(U.line(24, 250, 494, 250, SOFT, 1))

# ══ right: proposed ════════════════════════════════════════════════════════
o.append(S.text(586, 30, 'PROPOSED', 10, MUT, weight='700', family='sans'))
o.append(S.text(586, 48, 'the list is the panel, and every row can explain itself', 11, INK2, family='sans'))
PX, PY, PW = 586, 62, 462
o += U.panel(PX, PY, PW, 210, None)
o += U.group(PX + 12, PY + 12, PW - 24, 186, 'Colour the shell by')
rows = [('Membrane force  N\u2081 / N\u2082', 'force per metre, in the shell plane', True),
        ('Bending moment  m\u2081 / m\u2082', 'the bending the shape could not avoid', False),
        ('Wood\u2013Armer design moments', 'what the reinforcement is sized from', False),
        ('Required steel  As, cm\u00b2/m', 'top and bottom, each direction', False),
        ('Utilisation (code check)', 'demand \u00f7 capacity; red is 1.0', False),
        ('Thickness  t', 'what the thickening decided', False),
        ('Deflection', 'how far each point moved', False)]
for k, (s, sub, on) in enumerate(rows):
    ry = PY + 42 + k * 24
    if on:
        o.append(U.rect(PX + 20, ry - 11, PW - 44, 22, '#dce9f6', BLUE, 1, 2))
    o += U.radio(PX + 34, ry, '', on)
    o.append(S.text(PX + 48, ry + 4, s, 10, INK, weight='700' if on else '400', family='sans'))
    o.append(S.text(PX + 232, ry + 4, sub, 9.2, MUT, family='sans'))
    o.append(S.text(PX + PW - 30, ry + 4, '?', 10.5, BLUE, weight='700', family='sans'))
o += U.leader(PX + PW - 26, PY + 212, PX + PW - 26, PY + 44)
o.append(S.text(PX + 150, PY + 228, 'one line under every row; a ? on every row opens the card below', 10, RUST, family='sans'))

# ══ the guide card ═════════════════════════════════════════════════════════
GY = 302
o.append(U.line(24, GY - 22, W - 24, GY - 22, SOFT, 1))
o.append(U.rect(24, GY, W - 48, 306, '#f7f9fb', RULE, 1, 3))
o.append(S.text(44, GY + 26, 'WHAT AM I LOOKING AT?  ·  Membrane force N₁ / N₂', 12, INK,
                weight='700', family='sans'))
o.append(S.text(44, GY + 46, 'opened from the ? on the row, or from the legend on the canvas. Same text in the tab’s guide page.',
                10, MUT, family='sans'))

# ── mini diagram: membrane forces on a patch ──────────────────────────────
def patch(cx, cy, kind):
    sc = S.Scene(scale=54.0, cx=cx, cy=cy)
    P = [(-1, -1, 0), (1, -1, 0.12), (1, 1, 0), (-1, 1, -0.12)]
    sc.face(P, '#dfe7ee', '#7d8a95', 0.9)
    sc.face([(p[0], p[1], p[2] - 0.16) for p in P], '#c3ced8', '#7d8a95', 0.7, bias=-0.3)
    for k in range(4):
        a, b = P[k], P[(k + 1) % 4]
        sc.face([a, b, (b[0], b[1], b[2] - .16), (a[0], a[1], a[2] - .16)],
                '#93a1ad', '#5d6a74', 0.6, bias=0.4)
    return sc


def arrow(o, x1, y1, x2, y2, c, sw=1.8, head=6.0, double=False):
    a = math.atan2(y2 - y1, x2 - x1)
    o.append(U.line(x1, y1, x2, y2, c, sw, cap='round'))
    for (hx, hy, ang) in ([(x2, y2, a)] + ([(x1, y1, a + math.pi)] if double else [])):
        o.append('<polygon points="%.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="%s"/>' % (
            hx, hy,
            hx - head * math.cos(ang - .42), hy - head * math.sin(ang - .42),
            hx - head * math.cos(ang + .42), hy - head * math.sin(ang + .42), c))


sc = patch(160, GY + 150, 'N')
o.append(sc.render())
for (dx, dy, c) in [(1, 0.56, '#33528c'), (-1, -0.56, '#33528c')]:
    arrow(o, 160 + dx * 108, GY + 150 + dy * 108, 160 + dx * 58, GY + 150 + dy * 58, c)
for (dx, dy, c) in [(-0.9, 0.62, '#a8432e'), (0.9, -0.62, '#a8432e')]:
    arrow(o, 160 + dx * 58, GY + 150 + dy * 58, 160 + dx * 108, GY + 150 + dy * 108, c)
o.append(S.text(160, GY + 258, 'N₁ compression (blue) · N₂ tension (red)', 9.6, INK2,
                anchor='middle', family='sans'))
o.append(S.text(160, GY + 80, 'in the plane of the shell', 9.4, MUT, anchor='middle', family='sans'))

sc = patch(368, GY + 150, 'm')
o.append(sc.render())
for s in (-1, 1):
    o.append('<path d="M%.1f %.1f a 30 30 0 0 %d %.1f %.1f" fill="none" stroke="#7b2fa8" stroke-width="1.8"/>'
             % (368 + s * 58, GY + 150 - 34 * s, 1 if s > 0 else 0, -s * 18, 58 * s))
    arrow(o, 368 + s * 58 - s * 18, GY + 150 - 34 * s + 58 * s, 368 + s * 52 - s * 18, GY + 150 - 30 * s + 60 * s, '#7b2fa8', 1.8, 5.5)
o.append(S.text(368, GY + 258, 'm₁ / m₂ bend the slab across its own thickness', 9.6, INK2,
                anchor='middle', family='sans'))
o.append(S.text(368, GY + 80, 'out of the plane of the shell', 9.4, MUT, anchor='middle', family='sans'))

# ── the words ─────────────────────────────────────────────────────────────
TXX = 520
lines = [
    ('N₁ and N₂ are the two principal MEMBRANE forces: force per metre of width, in the', INK2),
    ('plane of the shell. They are what a shell carries load with. Blue is compression,', INK2),
    ('red is tension, and the pale middle of the ramp is a patch carrying almost nothing.', INK2),
    ('', INK2),
    ('Read it like this. A well-shaped shell is mostly one colour — compression — with', INK),
    ('tension only near free edges and openings. A red patch in the middle of a dome is', INK),
    ('the shape fighting the load, and it is usually cheaper to change the shape than to', INK),
    ('thicken the slab. Bending m₁ / m₂ tells the other half of that story: a shell in pure', INK),
    ('membrane action has almost none, so wherever m is large the shell is acting as a', INK),
    ('plate, and that is exactly where automatic thickening will add material.', INK),
    ('', INK2),
    ('Units follow the tab: kN/m here, kNm/m for moments, MPa for stress.', MUT),
    ('The scale is this model’s own peak unless you pin it — so two models are not', MUT),
    ('comparable by colour alone, and the legend always prints the numbers.', MUT),
]
for k, (s, c) in enumerate(lines):
    o.append(S.text(TXX, GY + 84 + k * 15.4, s, 10, c, family='sans'))

open('fig5_colour.svg', 'w').write(S.svg(W, H, '\n'.join(o), '#ffffff'))
print('fig5 written')
