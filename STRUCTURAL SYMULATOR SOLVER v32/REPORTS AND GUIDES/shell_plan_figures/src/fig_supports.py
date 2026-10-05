import math, sv3d as S, ui as U

INK, MUT, RULE = U.INK, U.MUT, U.RULE
BLUE, RUST = U.BLUE, U.RUST
VIEW = (math.cos(S.EL) * math.sin(S.AZ), math.cos(S.EL) * math.cos(S.AZ), math.sin(S.EL))

NX, NY = 5, 4
DX, DY = 1.0, 1.0
T = 0.16


def zf(i, j):
    return 0.30 * math.cos(0.42 * (i - 2.0)) * math.cos(0.38 * (j - 1.5)) - 0.30


def node(i, j, s=0):
    return (i * DX, j * DY, zf(i, j) + s * T / 2)


def quad(sc, i, j, s, fill, stroke='#8794a0'):
    q = [node(i, j, s), node(i + 1, j, s), node(i + 1, j + 1, s), node(i, j + 1, s)]
    n = S.normal(q)
    if n[2] * s < 0:
        q = list(reversed(q))
    sc.face(q, fill, stroke, 0.6)


W, H = 1080, 452
o = [U.rect(0, 0, W, H, '#ffffff', None)]
sc = S.Scene(scale=80.0, cx=300, cy=214)

SEL = {(1, 3), (2, 3), (3, 3)}
for i in range(NX - 1):
    for j in range(NY - 1):
        base = (150, 168, 184)
        hot = (i, j) in [(2, 2)]
        q = [node(i, j, 1), node(i + 1, j, 1), node(i + 1, j + 1, 1), node(i, j + 1, 1)]
        c = S.shade(q, (206, 222, 238) if hot else base)
        quad(sc, i, j, 1, S.hexof(c))
# the edge band, so the patch reads as a slab and not a sheet
for i in range(NX - 1):
    for j, out in ((0, (0, -1, 0)), (NY - 1, (0, 1, 0))):
        q = [node(i, j, 1), node(i + 1, j, 1), node(i + 1, j, -1), node(i, j, -1)]
        n = S.normal(q)
        if (n[0] * out[0] + n[1] * out[1]) < 0:
            q = list(reversed(q))
        if S.normal(q)[0] * VIEW[0] + S.normal(q)[1] * VIEW[1] + S.normal(q)[2] * VIEW[2] > 0:
            sc.face(q, S.hexof(S.shade(q, (72, 92, 110), amb=.62, gain=.4)), '#46535e', 0.6, bias=.02)
for j in range(NY - 1):
    for i, out in ((0, (-1, 0, 0)), (NX - 1, (1, 0, 0))):
        q = [node(i, j, 1), node(i, j + 1, 1), node(i, j + 1, -1), node(i, j, -1)]
        n = S.normal(q)
        if (n[0] * out[0] + n[1] * out[1]) < 0:
            q = list(reversed(q))
        if S.normal(q)[0] * VIEW[0] + S.normal(q)[1] * VIEW[1] + S.normal(q)[2] * VIEW[2] > 0:
            sc.face(q, S.hexof(S.shade(q, (72, 92, 110), amb=.62, gain=.4)), '#46535e', 0.6, bias=.02)

# every element corner is a pickable node
for i in range(NX):
    for j in range(NY):
        p = node(i, j, 1)
        q = sc.pt(p)
        selected = (i, j) in SEL
        sc.raw(U.rect(q[0] - 3.4, q[1] - 3.4, 6.8, 6.8,
                      BLUE if selected else '#ffffff', '#2c3740' if not selected else '#12457a',
                      1.0, 1), q[2] + 0.4)

# hover ring on one corner
hq = sc.pt(node(2, 2, 1))
sc.raw('<circle cx="%.1f" cy="%.1f" r="9" fill="none" stroke="%s" stroke-width="1.6"/>'
       % (hq[0], hq[1], RUST), 99)
sc.raw(U.rect(hq[0] + 12, hq[1] - 26, 118, 20, '#ffffff', RUST, 1, 2), 99)
sc.raw(S.text(hq[0] + 18, hq[1] - 12, 'corner n214 · free', 9.6, INK), 99.1)

# a whole edge picked as a line support
for j in range(NY - 1):
    sc.line(node(NX - 1, j, 1), node(NX - 1, j + 1, 1), '#7b2fa8', 3.0, bias=1.2)

# support glyphs under the picked edge and the selected corners
def pin(p, col='#2f6ea8'):
    h, w = 0.34, 0.16
    b = p[2] - h
    sc.face([p, (p[0] - w, p[1] - w, b), (p[0] + w, p[1] - w, b)], col, '#1b4a73', 0.5, bias=-0.4)
    sc.face([p, (p[0] + w, p[1] - w, b), (p[0] + w, p[1] + w, b)],
            S.hexof(S.mix((47, 110, 168), (255, 255, 255), .22)), '#1b4a73', 0.5, bias=-0.4)


for j in range(NY):
    pin(node(NX - 1, j, -1), '#7b2fa8')
for (i, j) in sorted(SEL):
    pin(node(i, j, -1))

o.append(sc.render())

# marquee
o.append(U.rect(118, 222, 150, 92, BLUE, BLUE, 1.2, 2, dash='5 4', op=0.10))
o.append(S.text(116, 216, 'drag a box — every corner inside is picked', 9.6, BLUE, family='sans'))

o.append(S.text(24, 34, 'PICKING WHAT THE SOLVER ACTUALLY RESTRAINS', 10, MUT, weight='700', family='sans'))
o.append(S.text(24, 396, 'A corner of an element IS a node of the mesh. Clicking one is therefore', 10, U.INK2, family='sans'))
o.append(S.text(24, 412, 'not an approximation of a support — it is the support, exactly where you put it.', 10, U.INK2, family='sans'))
o.append(S.text(24, 432, 'click a corner  ·  shift-click to add  ·  drag a box  ·  click an edge for the whole line  ·  Esc clears', 9.6, MUT, family='sans'))

# ── the Support panel ───────────────────────────────────────────────────────
PX, PY, PW, PH = 620, 24, 436, 350
o += U.panel(PX, PY, PW, PH, 'SUPPORT')
o.append(S.text(PX + 12, PY + 48, '3 corners selected  ·  1 edge (5 corners)', 10.5, INK, weight='700', family='sans'))
o += U.group(PX + 12, PY + 62, PW - 24, 118, 'Preset')
px, py = PX + 28, PY + 88
for k, (s, on) in enumerate([('Free', False), ('Pinned (ux uy uz)', True), ('Fully fixed', False),
                             ('Roller — slides in X', False), ('Roller — slides in Y', False),
                             ('Elastic (spring)', False)]):
    o += U.radio(px + (0 if k < 3 else 206), py + (k % 3) * 24, s, on)
o += U.group(PX + 12, PY + 192, PW - 24, 84, 'Or set the six freedoms one by one')
for k, (s, on) in enumerate([('ux', True), ('uy', True), ('uz', True),
                             ('θx', False), ('θy', False), ('θz', False)]):
    o += U.check(PX + 34 + (k % 3) * 74, PY + 222 + (k // 3) * 26, s, on)
o.append(S.text(PX + 262, PY + 224, 'a shell node has 5 or 6', 9.6, MUT, family='sans'))
o.append(S.text(PX + 262, PY + 238, 'freedoms — the panel says', 9.6, MUT, family='sans'))
o.append(S.text(PX + 262, PY + 252, 'which, for this element type.', 9.6, MUT, family='sans'))
o += U.button(PX + 12, PY + 288, 200, 24, 'Apply to the selection', True)
o += U.button(PX + 222, PY + 288, 200, 24, 'Release the selection')
o.append(S.text(PX + 12, PY + 334, 'Quick: the four plan corners · the whole boundary · the lowest ring', 9.6, BLUE, family='sans'))
o.append(S.text(PX + 12, PY + PH + 22, 'and a support sandbox: switch one off, re-solve, see what it was carrying.',
                10, MUT, family='sans'))

open('fig3_supports.svg', 'w').write(S.svg(W, H, '\n'.join(o), '#ffffff'))
print('fig3 written')
