"""Figure 7 - the verification case, from Mekjavic & Piculin (2010), Table 1.

The dome's membrane curves here are computed from the closed-form membrane
solution, which reproduces that paper's own membrane column to within its
rounding; the classical (Geckeler) and finite-element values are the
paper's published numbers, drawn as markers, not recomputed.
"""
import math, sv3d as S, ui as U

INK, INK2, MUT, RULE, SOFT = U.INK, U.INK2, U.MUT, U.RULE, U.SOFT
BLUE, RUST, ASK = U.BLUE, U.RUST, '#7b2fa8'

R, T, ALPHA, NU = 28.80, 0.102, math.radians(28.0), 1.0 / 6.0
Q = 4.31                                  # kN/m^2, 2.55 dead + 1.76 live
BETA = (3 * (1 - NU ** 2)) ** 0.25 * math.sqrt(R / T)


def n_phi(p):
    return -Q * R / (1 + math.cos(p))


def n_theta(p):
    return -Q * R * (math.cos(p) - 1 / (1 + math.cos(p)))


W, H = 1080, 420
o = [U.rect(0, 0, W, H, '#ffffff', None)]
o.append(S.text(24, 30, 'THE CASE STAGE 1 HAS TO REPRODUCE', 10, MUT, weight='700', family='sans'))
o.append(S.text(24, 48, 'Rigidly supported spherical dome · Mekjavić & Pičulin (2010), Table 1',
                11.5, INK, weight='700', family='sans'))

# ── A · the dome, in section ───────────────────────────────────────────────
CX, CY, SC = 210, 430, 9.2        # px per metre
o.append(S.text(24, 78, 'A · the dome, in section', 10, INK, weight='700', family='sans'))
apex = (CX, CY - R * SC)
pts = []
n = 80
for i in range(n + 1):
    p = -ALPHA + 2 * ALPHA * i / n
    pts.append((CX + R * math.sin(p) * SC, CY - R * math.cos(p) * SC))
# the shell, at true thickness (0.102 m -> 0.5 px; drawn at x8 so it exists)
TP = T * SC * 8
up = [(x - 0, y - TP / 2) for x, y in pts]
dn = [(x, y + TP / 2) for x, y in pts]
o.append('<polygon points="%s" fill="#c6d3de" stroke="#46535e" stroke-width="0.9"/>'
         % ' '.join('%.1f,%.1f' % p for p in up + list(reversed(dn))))
# the boundary layer, 3/BETA of arc from each edge
psi = 3.0 / BETA
band = [p for p in pts if abs(math.asin(max(-1, min(1, (p[0] - CX) / (R * SC))))) > ALPHA - psi]
for sgn in (-1, 1):
    seg = [(CX + R * math.sin(sgn * (ALPHA - psi * t / 20)) * SC,
            CY - R * math.cos(ALPHA - psi * t / 20) * SC) for t in range(21)]
    o.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="5" stroke-opacity="0.30"/>'
             % (' '.join('%.1f,%.1f' % p for p in seg), RUST))
# supports
for sgn in (-1, 1):
    x = CX + sgn * R * math.sin(ALPHA) * SC
    y = CY - R * math.cos(ALPHA) * SC
    o.append('<polygon points="%.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="#2f6ea8"/>'
             % (x, y + TP / 2, x - 7, y + TP / 2 + 12, x + 7, y + TP / 2 + 12))
    for k in range(5):
        o.append(U.line(x - 9 + k * 4.5, y + TP / 2 + 12, x - 13 + k * 4.5, y + TP / 2 + 18, '#2f6ea8', 1))
o.append(U.line(CX - R * math.sin(ALPHA) * SC, CY - R * math.cos(ALPHA) * SC + 34,
                CX + R * math.sin(ALPHA) * SC, CY - R * math.cos(ALPHA) * SC + 34, BLUE, 1))
o.append(S.text(CX, CY - R * math.cos(ALPHA) * SC + 50, '2 r₀ = 26.98 m', 9.6, BLUE, anchor='middle'))
o.append(S.text(24, 276, 'r = 28.80 m · α = 28° · t = 10.2 cm · ν = 1/6', 9.6, INK))
o.append(S.text(24, 292, 'q = 4.31 kN/m² (2.55 dead + 1.76 live)', 9.6, INK))
o.append(S.text(24, 308, 'E = 32 GPa · C30/37 · bottom edge fully fixed', 9.6, INK))
o.append(S.text(24, 330, 'quad4 mesh, refined 6 014 → 12 028 elements until', 9.4, MUT, family='sans'))
o.append(S.text(24, 344, 'the forces stopped moving.', 9.4, MUT, family='sans'))
o.append(S.text(24, 366, 'thickness drawn ×8; everything else to scale.', 9.2, MUT, family='sans'))
o.append(S.text(CX + 138, 176, 'bending lives', 9.4, RUST, family='sans'))
o.append(S.text(CX + 138, 188, 'in these bands', 9.4, RUST, family='sans'))

# ── B · the two membrane curves, and where the real answer leaves them ────
GX, GY, GW, GH = 452, 296, 248, 162
o.append(S.text(GX, 78, 'B · why the edge needs its own mesh', 10, INK, weight='700', family='sans'))
o.append(S.text(GX, 96, 'the edge disturbance decays as e^(−βψ), with β = [3(1−ν²)]^¼ √(r/t) = 22.0,', 9.2, MUT, family='sans'))
o.append(S.text(GX, 109, 'so it is spent 7.8° from the edge — 3.9 m of a 14.1 m meridian.', 9.2, MUT, family='sans'))
o.append(U.rect(GX, GY - GH, GW, GH, '#ffffff', RULE, 1))
LO, HI = -70.0, 0.0


def gx(p):      # psi measured from the EDGE, as the paper tabulates it
    return GX + GW * (p / math.degrees(ALPHA))


def gy(v):
    return GY - GH * (v - LO) / (HI - LO)


for v in (-70, -60, -50, -40, -30, -20, -10, 0):
    o.append(U.line(GX, gy(v), GX + GW, gy(v), SOFT, 0.7))
    o.append(S.text(GX - 5, gy(v) + 3.4, '%d' % v, 8.6, MUT, anchor='end'))
o.append(S.text(GX - 30, gy(-35), 'kN/m', 8.6, MUT, anchor='middle'))
for d in (0, 7, 14, 21, 28):
    o.append(U.line(gx(d), GY, gx(d), GY + 4, RULE, 0.8))
    o.append(S.text(gx(d), GY + 15, '%d°' % d, 8.6, MUT, anchor='middle'))
o.append(S.text(GX + GW / 2, GY + 30, 'ψ, from the edge to the apex', 9.2, MUT,
                anchor='middle', family='sans'))
# the boundary layer band
o.append(U.rect(gx(0), GY - GH, gx(math.degrees(3 / BETA)) - gx(0), GH, RUST, None, op=0.10))
o.append(S.text(gx(math.degrees(3 / BETA)) + 5, GY - GH + 14,
                'the last %.1f°' % math.degrees(3 / BETA), 9, RUST, family='sans'))
for lab, fn, col in (('Nφ', n_phi, BLUE), ('Nθ', n_theta, ASK)):
    pl = []
    for i in range(61):
        d = 28.0 * i / 60
        pl.append((gx(d), gy(fn(ALPHA - math.radians(d)))))
    o.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="1.6"/>'
             % (' '.join('%.1f,%.1f' % p for p in pl), col))
    o.append(S.text(pl[-1][0] - 4, pl[-1][1] - 7, lab, 9.6, col, anchor='end', weight='700'))
# the published finite-element values
for d, v, col in ((0, -63.00, BLUE), (28, -62.60, BLUE), (0, -10.51, ASK), (28, -62.50, ASK)):
    o.append('<circle cx="%.1f" cy="%.1f" r="3.4" fill="#ffffff" stroke="%s" stroke-width="1.8"/>'
             % (gx(d), gy(v), col))
o.append(U.line(gx(0) + 2, gy(-43.67), gx(0) + 2, gy(-10.51), ASK, 1.0, dash='3 3'))
o.append(S.text(gx(9), gy(-22), 'membrane theory is out', 9, ASK, family='sans'))
o.append(S.text(gx(9), gy(-22) + 12, 'by 33 kN/m at the edge', 9, ASK, family='sans'))
o.append(S.text(GX, GY + 48, 'lines: the closed-form membrane solution.  circles: the paper’s', 9.2, MUT, family='sans'))
o.append(S.text(GX, GY + 61, 'finite-element values, fine mesh.  The gap at ψ = 0 is the whole', 9.2, MUT, family='sans'))
o.append(S.text(GX, GY + 74, 'reason a shell tab needs a mesh that is finer at its edges.', 9.2, MUT, family='sans'))

# ── C · the numbers ───────────────────────────────────────────────────────
TX = 726
o.append(S.text(TX, 78, 'C · the numbers to hit', 10, INK, weight='700', family='sans'))
rows = [('Nφ', '0° (edge)', '−65.67', '−62.60', '−63.00'),
        ('Nθ', '0° (edge)', '−43.78', '−11.38', '−10.51'),
        ('Mφ', '0° (edge)', '0', '−1.16', '−1.18'),
        ('Nφ', '28° (apex)', '−62.02', '−62.02', '−62.60'),
        ('Nθ', '28° (apex)', '−62.02', '−62.02', '−62.50'),
        ('Mφ', '28° (apex)', '0', '0', '0.04')]
hy = 106
for k, h in enumerate(['', 'at', 'membrane', 'Geckeler', 'FEA fine']):
    o.append(S.text(TX + [0, 34, 118, 196, 274][k], hy, h, 8.6, MUT, weight='700', family='sans'))
o.append(U.line(TX, hy + 6, TX + 320, hy + 6, RULE, 1))
for k, r in enumerate(rows):
    ry = hy + 22 + k * 19
    if k == 1:
        o.append(U.rect(TX - 4, ry - 12, 328, 18, RUST, None, op=0.10))
    o.append(S.text(TX, ry, r[0], 9.6, INK, weight='700'))
    o.append(S.text(TX + 34, ry, r[1], 9.4, MUT))
    for j in (2, 3, 4):
        o.append(S.text(TX + [0, 0, 160, 238, 316][j], ry, r[j], 9.6, INK, anchor='end'))
o.append(S.text(TX, hy + 150, 'N in kN/m, M in kNm/m.', 9, MUT, family='sans'))
o.append(U.rect(TX, hy + 162, 320, 92, '#f2f7fb', BLUE, 1, 2))
o.append(S.text(TX + 12, hy + 182, 'This is the acceptance test for Stage 1.', 10, '#124a80',
                weight='700', family='sans'))
o.append(S.text(TX + 12, hy + 201, 'Published numbers, an analytic solution beside', 9.4, INK2, family='sans'))
o.append(S.text(TX + 12, hy + 215, 'them, and a mesh study that converged at 12 028', 9.4, INK2, family='sans'))
o.append(S.text(TX + 12, hy + 229, 'elements. If the element cannot hit this, nothing', 9.4, INK2, family='sans'))
o.append(S.text(TX + 12, hy + 243, 'built on top of it is worth drawing.', 9.4, INK2, family='sans'))

open('fig7_verify.svg', 'w').write(S.svg(W, H, '\n'.join(o), '#ffffff'))
print('fig7 written · beta = %.2f · 3/beta = %.2f deg' % (BETA, math.degrees(3 / BETA)))
