import math, sv3d as S, ui as U

INK, INK2, MUT, RULE, SOFT = U.INK, U.INK2, U.MUT, U.RULE, U.SOFT
BLUE, RUST = U.BLUE, U.RUST
VIEW = (math.cos(S.EL) * math.sin(S.AZ), math.cos(S.EL) * math.cos(S.AZ), math.sin(S.EL))
SHELL = (154, 172, 188)
T = 0.14


def visible(q):
    n = S.normal(q)
    return n[0] * VIEW[0] + n[1] * VIEW[1] + n[2] * VIEW[2] > 0


def orient(q, want):
    n = S.normal(q)
    return list(reversed(q)) if (n[0] * want[0] + n[1] * want[1] + n[2] * want[2]) < 0 else q


def surf(sc, f, a=2.2, b=2.2, n=10, keep=None):
    h = 1e-4

    def nrm(x, y):
        zx = (f(x + h, y) - f(x - h, y)) / (2 * h)
        zy = (f(x, y + h) - f(x, y - h)) / (2 * h)
        L = math.sqrt(zx * zx + zy * zy + 1)
        return (-zx / L, -zy / L, 1 / L)

    def P(x, y, s):
        nx, ny, nz = nrm(x, y)
        return (x + s * T / 2 * nx, y + s * T / 2 * ny, f(x, y) + s * T / 2 * nz)

    xs = [-a + 2 * a * i / n for i in range(n + 1)]
    ys = [-b + 2 * b * j / n for j in range(n + 1)]
    live = [[(keep is None or keep(xs[i], ys[j])) for j in range(n + 1)] for i in range(n + 1)]
    for i in range(n):
        for j in range(n):
            if not (live[i][j] and live[i + 1][j] and live[i + 1][j + 1] and live[i][j + 1]):
                continue
            for s in (+1, -1):
                q = orient([P(xs[i], ys[j], s), P(xs[i + 1], ys[j], s),
                            P(xs[i + 1], ys[j + 1], s), P(xs[i], ys[j + 1], s)], (0, 0, s))
                if visible(q):
                    sc.face(q, S.hexof(S.shade(q, SHELL)), '#8794a0', 0.4)
            # a side wall wherever the neighbour is missing or we are on the rim
            for (di, dj, out) in ((-1, 0, (-1, 0, 0)), (1, 0, (1, 0, 0)), (0, -1, (0, -1, 0)), (0, 1, (0, 1, 0))):
                ii, jj = i + (1 if di > 0 else 0), j + (1 if dj > 0 else 0)
                ni, nj = i + di, j + dj
                inb = 0 <= ni < n and 0 <= nj < n and live[ni][nj] and live[ni + 1][nj] \
                    and live[ni + 1][nj + 1] and live[ni][nj + 1]
                if inb:
                    continue
                if di:
                    A_, B_ = (xs[ii], ys[j]), (xs[ii], ys[j + 1])
                else:
                    A_, B_ = (xs[i], ys[jj]), (xs[i + 1], ys[jj])
                q = orient([P(A_[0], A_[1], +1), P(B_[0], B_[1], +1),
                            P(B_[0], B_[1], -1), P(A_[0], A_[1], -1)], out)
                if visible(q):
                    sc.face(q, S.hexof(S.shade(q, (70, 90, 108), amb=.62, gain=.38)), '#46535e', .5, bias=.03)


W, H = 1080, 452
o = [U.rect(0, 0, W, H, '#ffffff', None)]

# ── the Shape panel ────────────────────────────────────────────────────────
PX, PY, PW, PH = 24, 24, 316, 412
o += U.panel(PX, PY, PW, PH, 'SHAPE')
o += U.group(PX + 12, PY + 40, PW - 24, 76, 'The surface')
for k, (s, on) in enumerate([('A family  — dome, vault, hypar, cone…', True),
                             ('z = f(x, y), written by you', False),
                             ('Parametric  x(u,v)  y(u,v)  z(u,v)', False)]):
    o += U.radio(PX + 30, PY + 64 + k * 18, s, on, size=9.8)
o += U.group(PX + 12, PY + 126, PW - 24, 70, 'Its formula')
o += U.field(PX + 30, PY + 148, 254, 'z = 1.3 * cos(pi*x/6) * cos(pi*y/6)')
o.append(S.text(PX + 30, PY + 182, 'the same parser and the same maths keypad', 9.2, MUT, family='sans'))
o += U.group(PX + 12, PY + 206, PW - 24, 74, 'Domain and plan')
o.append(S.text(PX + 30, PY + 232, 'x', 9.8, INK2, family='sans'))
o += U.field(PX + 44, PY + 222, 46, '−3.0', 16)
o += U.field(PX + 96, PY + 222, 46, '3.0', 16)
o.append(S.text(PX + 150, PY + 232, 'y', 9.8, INK2, family='sans'))
o += U.field(PX + 164, PY + 222, 46, '−3.0', 16)
o += U.field(PX + 216, PY + 222, 46, '3.0', 16)
o.append(S.text(PX + 30, PY + 260, 'keep where', 9.8, INK2, family='sans'))
o += U.field(PX + 100, PY + 250, 162, 'hypot(x, y) < 3')
o += U.group(PX + 12, PY + 290, PW - 24, 82, 'The mesh')
o.append(S.text(PX + 30, PY + 316, 'elements across', 9.8, INK2, family='sans'))
o += U.field(PX + 128, PY + 306, 40, '32', 16)
o.append(S.text(PX + 178, PY + 316, '×', 9.8, INK2)); o += U.field(PX + 190, PY + 306, 40, '32', 16)
for k, (s, on) in enumerate([('quad', True), ('triangle', False)]):
    o += U.radio(PX + 34 + k * 92, PY + 348, s, on, size=9.8)
o.append(S.text(PX + 214, PY + 352, '1 024 elements', 9.2, MUT, family='sans'))
o += U.button(PX + 12, PY + 380, PW - 24, 24, 'Build this shell', True)

# ── five shells the wizard makes ──────────────────────────────────────────
o.append(S.text(376, 40, 'WHAT THE SAME PANEL BUILDS', 10, MUT, weight='700', family='sans'))
shapes = [
    ('dome', lambda x, y: 1.5 * math.cos(math.pi * x / 6.4) * math.cos(math.pi * y / 6.4), None),
    ('barrel vault', lambda x, y: 1.4 * math.cos(math.pi * x / 6.0), None),
    ('hypar', lambda x, y: 0.22 * x * y, None),
    ('round plan, cut', lambda x, y: 1.4 * math.cos(math.pi * x / 6.4) * math.cos(math.pi * y / 6.4),
     lambda x, y: math.hypot(x, y) < 1.72),
    ('z = f(x,y), free', lambda x, y: 0.55 * math.sin(1.5 * x) * math.cos(1.2 * y) + 0.5, None),
]
for k, (nm, f, keep) in enumerate(shapes):
    cx = 404 + (k % 3) * 226
    cy = 140 + (k // 3) * 190
    sc = S.Scene(scale=27.0, cx=cx, cy=cy)
    surf(sc, f, n=(16 if keep else 11), keep=keep)
    o.append(sc.render())
    o.append(S.text(cx, cy + 74, nm, 10, INK2, anchor='middle', weight='600', family='sans'))
o.append(S.text(856, 330, 'every one of them is a real shell:', 10, INK2, family='sans'))
o.append(S.text(856, 346, 'a meshed surface with a thickness,', 10, INK2, family='sans'))
o.append(S.text(856, 362, 'supports you place on its corners,', 10, INK2, family='sans'))
o.append(S.text(856, 378, 'and a section you can cut anywhere.', 10, INK2, family='sans'))
o.append(S.text(856, 404, 'The crossing check, the summit finder', 9.4, MUT, family='sans'))
o.append(S.text(856, 418, 'and the plan-shape rule come across', 9.4, MUT, family='sans'))
o.append(S.text(856, 432, 'from Stereo unchanged.', 9.4, MUT, family='sans'))

open('fig6_shape.svg', 'w').write(S.svg(W, H, '\n'.join(o), '#ffffff'))
print('fig6 written')
