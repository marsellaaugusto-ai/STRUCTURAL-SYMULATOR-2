import math, sv3d as S, shellgeom as G, ui as U

INK, MUT, RULE = U.INK, U.MUT, U.RULE
SHELL = (150, 168, 184)
VIEW = (math.cos(S.EL) * math.sin(S.AZ), math.cos(S.EL) * math.cos(S.AZ), math.sin(S.EL))
UTIL = [(0.0, (228, 240, 232)), (0.35, (106, 168, 116)), (0.7, (224, 176, 60)), (1.0, (186, 60, 44))]
CUTC = ['#1a6bbd', '#c0561f', '#7b2fa8']


def visible(poly):
    n = S.normal(poly)
    return n[0] * VIEW[0] + n[1] * VIEW[1] + n[2] * VIEW[2] > 0


def orient(poly, want):
    n = S.normal(poly)
    return list(reversed(poly)) if (n[0] * want[0] + n[1] * want[1] + n[2] * want[2]) < 0 else poly


def util(x):
    return 0.30 + 0.62 * math.exp(-(((abs(x) - 1.55) / 0.85) ** 2))


def shell3d(sc, n=8):
    xs, ys = G.grid(n)
    for i in range(n):
        for j in range(n):
            for s in (+1, -1):
                q = [G.off(xs[i], ys[j], s), G.off(xs[i + 1], ys[j], s),
                     G.off(xs[i + 1], ys[j + 1], s), G.off(xs[i], ys[j + 1], s)]
                q = orient(q, (0, 0, s))
                if visible(q):
                    sc.face(q, S.hexof(S.shade(q, SHELL)), '#8794a0', 0.5)
    edges = ([(xs[i], -G.B, xs[i + 1], -G.B, (0, -1, 0)) for i in range(n)] +
             [(xs[i], G.B, xs[i + 1], G.B, (0, 1, 0)) for i in range(n)] +
             [(-G.A, ys[j], -G.A, ys[j + 1], (-1, 0, 0)) for j in range(n)] +
             [(G.A, ys[j], G.A, ys[j + 1], (1, 0, 0)) for j in range(n)])
    for x0, y0, x1, y1, out in edges:
        q = orient([G.off(x0, y0, +1), G.off(x1, y1, +1),
                    G.off(x1, y1, -1), G.off(x0, y0, -1)], out)
        if visible(q):
            sc.face(q, S.hexof(S.shade(q, (72, 92, 110), amb=0.62, gain=0.4)), '#46535e', 0.6, bias=0.02)


def cutplane(sc, kind, at, col, name):
    """A translucent plane through the model, with its trace drawn on the shell."""
    m = 40
    if kind == 'y':
        pts = [(-G.A + 2 * G.A * i / m, at) for i in range(m + 1)]
    else:
        pts = [(at, -G.B + 2 * G.B * i / m) for i in range(m + 1)]
    top = [G.off(px, py, +1) for px, py in pts]
    bot = [G.off(px, py, -1) for px, py in pts]
    sc.face(top + list(reversed(bot)), col, None, op=0.30, bias=0.6)
    for k in range(m):
        sc.line(top[k], top[k + 1], col, 1.8, bias=0.9)
        sc.line(bot[k], bot[k + 1], col, 1.2, bias=0.9)
    sc.line((pts[0][0], pts[0][1], -0.5), (pts[-1][0], pts[-1][1], -0.5), col, 1.0, dash='4 3', bias=-2)
    sc.text3((pts[-1][0] + 0.35, pts[-1][1] + 0.1, -0.5), name, size=11, fill=col,
             weight='700', family='sans')


W, H = 1080, 556
o = []
o.append(U.rect(0, 0, W, H, '#ffffff', None))

# ── 3D, left ────────────────────────────────────────────────────────────────
sc = S.Scene(scale=46.0, cx=300, cy=196)
shell3d(sc)
cutplane(sc, 'y', 0.0, CUTC[0], 'S1')
cutplane(sc, 'x', -1.6, CUTC[1], 'S2')
o.append(sc.render())
o.append(S.text(24, 34, 'THE CUTS, ON THE MODEL', 10, MUT, weight='700', family='sans'))
o.append(S.text(24, 300, 'every cut keeps its colour — the plane in 3D, the row in the list', 10, MUT, family='sans'))
o.append(S.text(24, 316, 'and the drawing below are the same colour, so no cut has to be hunted for.', 10, MUT, family='sans'))

# ── the section list panel, right ───────────────────────────────────────────
PX, PY, PW, PH = 620, 24, 436, 296
o += U.panel(PX, PY, PW, PH, 'SECTIONS')
rows = [('S1', 'along X', 'y = 0.00', CUTC[0], True, '0.32 / 0.15', '0.92'),
        ('S2', 'along Y', 'x = −1.60', CUTC[1], True, '0.32 / 0.16', '0.71'),
        ('S3', 'diagonal', 'corner–corner', CUTC[2], False, '0.45 / 0.15', '0.88')]
hy = PY + 44
o.append(S.text(PX + 34, hy, 'cut', 9, MUT, weight='700', family='sans'))
o.append(S.text(PX + 84, hy, 'direction', 9, MUT, weight='700', family='sans'))
o.append(S.text(PX + 160, hy, 'position', 9, MUT, weight='700', family='sans'))
o.append(S.text(PX + 262, hy, 't max / min  (m)', 9, MUT, weight='700', family='sans'))
o.append(S.text(PX + 398, hy, 'util', 9, MUT, weight='700', family='sans', anchor='end'))
o.append(U.line(PX + 12, hy + 6, PX + PW - 12, hy + 6, U.SOFT, 1))
for k, (nm, dr, ps, col, on, tt, ut) in enumerate(rows):
    ry = hy + 20 + k * 30
    if k == 0:
        o.append(U.rect(PX + 10, ry - 12, PW - 20, 26, '#dce9f6', U.BLUE, 1.0, 2))
    o += U.eye(PX + 16, ry, on)
    o.append(U.swatch(PX + 34, ry - 5, col))
    o.append(S.text(PX + 50, ry + 4, nm, 10.5, INK, weight='700'))
    o.append(S.text(PX + 84, ry + 4, dr, 10.5, U.INK2, family='sans'))
    o.append(S.text(PX + 160, ry + 4, ps, 10.5, U.INK2))
    o.append(S.text(PX + 262, ry + 4, tt, 10.5, INK))
    o.append(S.text(PX + 398, ry + 4, ut, 10.5, '#a8431f' if float(ut) > .85 else INK,
                    anchor='end', weight='700'))
    o.append(S.text(PX + 414, ry + 4, '✕', 10.5, '#98a3ac'))
o.append(U.line(PX + 12, hy + 116, PX + PW - 12, hy + 116, U.SOFT, 1))
o += U.button(PX + 12, hy + 128, 116, 22, '+ Cut along X')
o += U.button(PX + 136, hy + 128, 116, 22, '+ Cut along Y')
o += U.button(PX + 260, hy + 128, 116, 22, '+ Two points')
o += U.check(PX + 20, hy + 172, 'Live: drag the plane in the 3D view', True)
o += U.check(PX + 20, hy + 194, 'Dimension every station on the drawing', True)
o += U.check(PX + 20, hy + 216, 'Mark where automatic thickening acted', True)
o.append(S.text(PX + 12, PY + PH + 16, 'docked in the Section mode — not a dropdown, not a modal',
                10, MUT, family='sans'))

# ── the section drawing, bottom ─────────────────────────────────────────────
SX, SY, SCL = 78, 572, 104.0          # px per metre, true scale both ways
o.append(U.line(0, 350, W, 350, U.SOFT, 1))
o.append(S.text(24, 374, 'S1 · SECTION ALONG X AT y = 0.00', 10, MUT, weight='700', family='sans'))
o.append(S.text(268, 374, 'drawn at true scale · the thickness IS the drawing, not a note beside it',
                10, MUT, family='sans'))
n = 90
top, bot = [], []
for i in range(n + 1):
    x = -G.A + 2 * G.A * i / n
    p = G.off(x, 0.0, +1)
    q = G.off(x, 0.0, -1)
    top.append((SX + (x + G.A) * SCL, SY - p[2] * SCL))
    bot.append((SX + (x + G.A) * SCL, SY - q[2] * SCL))
# fill the cut face in bands, coloured by utilisation
for i in range(n):
    u = util((-G.A + 2 * G.A * (i + 0.5) / n))
    c = S.hexof(S.ramp(u, UTIL))
    poly = [top[i], top[i + 1], bot[i + 1], bot[i]]
    o.append('<polygon points="%s" fill="%s" stroke="%s" stroke-width="0.4"/>'
             % (' '.join('%.1f,%.1f' % p for p in poly), c, c))
o.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="1.3"/>'
         % (' '.join('%.1f,%.1f' % p for p in top), '#2c3740'))
o.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="1.3"/>'
         % (' '.join('%.1f,%.1f' % p for p in bot), '#2c3740'))
mid = [(SX + (-G.A + 2 * G.A * i / n + G.A) * SCL, SY - G.z(-G.A + 2 * G.A * i / n, 0) * SCL)
       for i in range(n + 1)]
o.append('<polyline points="%s" fill="none" stroke="#54606a" stroke-width="0.8" stroke-dasharray="5 4"/>'
         % ' '.join('%.1f,%.1f' % p for p in mid))
# thickness ladder at stations
for xs_ in (-3.0, -1.9, -0.9, 0.0, 0.9, 1.9, 3.0):
    px = SX + (xs_ + G.A) * SCL
    a = SY - G.off(xs_, 0, +1)[2] * SCL
    b = SY - G.off(xs_, 0, -1)[2] * SCL
    o.append(U.line(px, a, px, b, '#1a6bbd', 1.0))
    o.append(U.line(px - 3.5, a, px + 3.5, a, '#1a6bbd', 1.0))
    o.append(U.line(px - 3.5, b, px + 3.5, b, '#1a6bbd', 1.0))
    o.append(S.text(px, b + 15, '%d' % round(G.thick(xs_, 0) * 1000), 9.6, '#1a6bbd', anchor='middle'))
o.append(S.text(SX + G.A * SCL, SY + 34, 'wall thickness at each station, mm', 9.6, '#1a6bbd', anchor='middle', family='sans'))
# where the thickening acted
o.append(U.rect(SX, 400, 1.05 * SCL, 7, '#c0561f', None, op=0.55))
o.append(U.rect(SX + (2 * G.A - 1.05) * SCL, 400, 1.05 * SCL, 7, '#c0561f', None, op=0.55))
o.append(S.text(SX + 4, 394, 'thickening acted', 9.4, '#a8431f', family='sans'))
o.append(S.text(SX + (2 * G.A - 1.05) * SCL + 4, 394, 'thickening acted', 9.4, '#a8431f', family='sans'))
# utilisation ramp
lx, ly = 742, 424
for i in range(150):
    o.append(U.rect(lx + i * 1.4, ly, 1.5, 9, S.hexof(S.ramp(i / 149.0, UTIL)), None))
o.append(U.rect(lx, ly, 210, 9, 'none', RULE, 0.8))
o.append(S.text(lx - 8, ly + 8, 'utilisation', 9.6, MUT, anchor='end', family='sans'))
o.append(S.text(lx, ly + 21, '0.0', 9.4, MUT))
o.append(S.text(lx + 210, ly + 21, '1.0', 9.4, MUT, anchor='end'))
o.append(S.text(lx, ly + 40, 'the cut face carries the same colour the model does,', 9.8, MUT, family='sans'))
o.append(S.text(lx, ly + 54, 'so a section is a slice of the analysis, not a separate drawing.', 9.8, MUT, family='sans'))

open('fig2_sections.svg', 'w').write(S.svg(W, H, '\n'.join(o), '#ffffff'))
print('fig2 written')
