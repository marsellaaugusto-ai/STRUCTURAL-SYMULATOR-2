import math, sv3d as S, shellgeom as G

INK, RULE, MUT = '#1e2429', '#ccd3da', '#6b7680'
SHELL = (150, 168, 184)
VIEW = (math.cos(S.EL) * math.sin(S.AZ), math.cos(S.EL) * math.cos(S.AZ), math.sin(S.EL))
TRAMP = [(0.0, (222, 233, 244)), (0.5, (110, 160, 205)), (1.0, (176, 74, 30))]


def visible(poly):
    n = S.normal(poly)
    return n[0] * VIEW[0] + n[1] * VIEW[1] + n[2] * VIEW[2] > 0.0


def orient(poly, want):
    n = S.normal(poly)
    if n[0] * want[0] + n[1] * want[1] + n[2] * want[2] < 0:
        return list(reversed(poly))
    return poly


def panel(sc, n, mode):
    """mode: 'sheet' | 'solid' | 'auto'"""
    xs, ys = G.grid(n)
    on = (mode == 'auto')
    if mode == 'sheet':
        for i in range(n):
            for j in range(n):
                q = [G.mid(xs[i], ys[j]), G.mid(xs[i + 1], ys[j]),
                     G.mid(xs[i + 1], ys[j + 1]), G.mid(xs[i], ys[j + 1])]
                sc.face(q, S.hexof(S.shade(q, SHELL)), '#7d8a95', 0.7)
        return
    # top and bottom faces
    for i in range(n):
        for j in range(n):
            for s in (+1, -1):
                q = [G.off(xs[i], ys[j], s, on), G.off(xs[i + 1], ys[j], s, on),
                     G.off(xs[i + 1], ys[j + 1], s, on), G.off(xs[i], ys[j + 1], s, on)]
                q = orient(q, (0, 0, s))
                if not visible(q):
                    continue
                base = SHELL
                if mode == 'auto':
                    tm = sum(G.thick(p[0], p[1]) for p in
                             [(xs[i], ys[j]), (xs[i + 1], ys[j + 1])]) / 2
                    base = S.ramp((tm - G.T0) / (G.TMAX - G.T0), TRAMP)
                sc.face(q, S.hexof(S.shade(q, base)), '#7d8a95', 0.55)
    # the four side walls: this is what a thickness looks like
    edges = ([(xs[i], -G.B, xs[i + 1], -G.B, (0, -1, 0)) for i in range(n)] +
             [(xs[i], G.B, xs[i + 1], G.B, (0, 1, 0)) for i in range(n)] +
             [(-G.A, ys[j], -G.A, ys[j + 1], (-1, 0, 0)) for j in range(n)] +
             [(G.A, ys[j], G.A, ys[j + 1], (1, 0, 0)) for j in range(n)])
    for x0, y0, x1, y1, out in edges:
        q = [G.off(x0, y0, +1, on), G.off(x1, y1, +1, on),
             G.off(x1, y1, -1, on), G.off(x0, y0, -1, on)]
        q = orient(q, out)
        if not visible(q):
            continue
        base = (72, 92, 110)
        if mode == 'auto':
            tm = (G.thick(x0, y0) + G.thick(x1, y1)) / 2
            base = S.ramp((tm - G.T0) / (G.TMAX - G.T0), TRAMP)
            base = S.mix(base, (0, 0, 0), 0.18)
        sc.face(q, S.hexof(S.shade(q, base, amb=0.62, gain=0.4)), '#46535e', 0.7, bias=0.02)


def supports(sc, on):
    for cx, cy in G.CORNERS:
        p = G.off(cx, cy, -1, on)
        h, w = 0.42, 0.20
        base = p[2] - h
        sc.face([p, (cx - w, cy - w, base), (cx + w, cy - w, base)],
                '#2f6ea8', '#1b4a73', 0.6, bias=-0.25)
        sc.face([p, (cx + w, cy - w, base), (cx + w, cy + w, base)],
                '#3f81bd', '#1b4a73', 0.6, bias=-0.25)
        sc.line((cx - 0.34, cy - 0.34, base), (cx + 0.34, cy + 0.34, base),
                '#1b4a73', 1.4, bias=-0.25)


W, HH = 1080, 366
PW = 360
FIGY = 166
out = []
titles = [('A \u00b7 what it does today', 'one mid-surface, zero thickness'),
          ('B \u00b7 the same shell, built', 'one t, drawn as the solid it is'),
          ('C \u00b7 automatic thickening on', 'you see where it put the material')]
for k, mode in enumerate(['sheet', 'solid', 'auto']):
    cx = PW * k + PW / 2
    sc = S.Scene(scale=30.0, cx=cx, cy=FIGY)
    panel(sc, 8, mode)
    supports(sc, mode == 'auto')
    out.append(sc.render())
    out.append(S.text(PW * k + 22, 42, titles[k][0], 12.5, INK, weight='700', family='sans'))
    out.append(S.text(PW * k + 22, 60, titles[k][1], 11, MUT, family='sans'))
    if k:
        out.append('<line x1="%d" y1="26" x2="%d" y2="%d" stroke="%s" stroke-width="1"/>'
                   % (PW * k, PW * k, HH - 16, RULE))

# --- the same edge, cut and magnified 5x, under each panel ---------------
DY = 280
PXM = 30.0 * 5.0           # 5x the panel scale


def detail(k, kind):
    x0 = PW * k + 52
    w = 238
    out.append(S.text(x0, DY - 16, 'THE FREE EDGE, CUT AND MAGNIFIED \u00d75', 8.6, MUT,
                      weight='700', family='sans'))
    if kind == 'sheet':
        out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1.4"/>'
                   % (x0, DY + 22, x0 + w, DY + 22, INK))
        out.append(S.text(x0 + w / 2, DY + 44, 'a surface. there is no t to draw,',
                          10, '#c0561f', anchor='middle', family='sans'))
        out.append(S.text(x0 + w / 2, DY + 58, 'and none in the section either.',
                          10, '#c0561f', anchor='middle', family='sans'))
        return
    if kind == 'solid':
        h = G.T0 * PXM
        out.append('<rect x="%d" y="%.1f" width="%d" height="%.1f" fill="#b9c6d2" stroke="%s" stroke-width="1"/>'
                   % (x0, DY + 22 - h / 2, w, h, '#46535e'))
        y1, y2 = DY + 22 - h / 2, DY + 22 + h / 2
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#1a6bbd" stroke-width="1"/>'
                   % (x0 + w + 14, y1, x0 + w + 14, y2))
        for yy in (y1, y2):
            out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#1a6bbd" stroke-width="1"/>'
                       % (x0 + w + 9, yy, x0 + w + 19, yy))
        out.append(S.text(x0 + w + 24, DY + 26, 't=150', 10, '#1a6bbd'))
        out.append(S.text(x0 + w / 2, DY + 58, 'one thickness, everywhere.',
                          10, MUT, anchor='middle', family='sans'))
        return
    # tapered: the corner is thicker than mid-edge
    pts = []
    n = 40
    for i in range(n + 1):
        u = i / n
        t = G.thick(-G.A + 2 * G.A * u, -G.B) * PXM
        pts.append((x0 + w * u, DY + 22 - t / 2))
    low = [(x0 + w * (1 - i / n), DY + 22 + G.thick(-G.A + 2 * G.A * (1 - i / n), -G.B) * PXM / 2)
           for i in range(n + 1)]
    path = ' '.join('%.1f,%.1f' % p for p in pts + low)
    out.append('<polygon points="%s" fill="#dcb69b" stroke="#8c4a26" stroke-width="1"/>' % path)
    out.append(S.text(x0 - 6, DY + 26, '%d' % round(G.thick(-G.A, -G.B) * 1000), 9.6, '#8c4a26', anchor='end'))
    out.append(S.text(x0 + w / 2, DY + 6, '%d' % round(G.thick(0.0, -G.B) * 1000), 9.6, '#8c4a26', anchor='middle'))
    out.append(S.text(x0 + w + 6, DY + 26, '%d' % round(G.thick(G.A, -G.B) * 1000), 9.6, '#8c4a26'))
    out.append(S.text(x0 + w / 2, DY + 58, 'the thickening, finally legible.',
                      10, '#8c4a26', anchor='middle', family='sans'))


for k, kind in enumerate(['sheet', 'solid', 'auto']):
    detail(k, kind)

open('fig1_thickness.svg', 'w').write(S.svg(W, HH, '\n'.join(out), '#ffffff'))
print('fig1 written')
