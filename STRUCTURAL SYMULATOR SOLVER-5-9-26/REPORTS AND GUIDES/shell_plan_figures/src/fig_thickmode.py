"""Figure 8 - the Thickness mode: the rule, its convergence, and the design
comparison it produces. The numbers in the comparison table are the Kresge
Auditorium results published by Mekjavic & Piculin (2010), Table 3 - real
numbers in the shape the mode would print them."""
import sv3d as S, ui as U

INK, INK2, MUT, RULE, SOFT = U.INK, U.INK2, U.MUT, U.RULE, U.SOFT
BLUE, RUST, OK = U.BLUE, U.RUST, '#2f6f4a'
W, H = 1080, 520
o = [U.rect(0, 0, W, H, '#ffffff', None)]

# ── the panel ─────────────────────────────────────────────────────────────
PX, PY, PW, PH = 24, 24, 316, 470
o += U.panel(PX, PY, PW, PH, 'THICKNESS')
o += U.group(PX + 12, PY + 40, PW - 24, 74, 'The slab')
for k, (s, on) in enumerate([('Reinforced concrete — CIRSOC 201', True),
                             ('Steel — CIRSOC 301', False)]):
    o += U.radio(PX + 30, PY + 64 + k * 18, s, on, size=9.8)
o.append(S.text(PX + 30, PY + 104, 'class', 9.8, INK2, family='sans'))
o += U.field(PX + 70, PY + 94, 66, 'C30/37', 16)
o.append(S.text(PX + 146, PY + 104, 'base t', 9.8, INK2, family='sans'))
o += U.field(PX + 194, PY + 94, 54, '100', 16)
o.append(S.text(PX + 252, PY + 104, 'mm', 9.6, MUT))

o += U.group(PX + 12, PY + 124, PW - 24, 116, 'Thicken automatically where')
for k, (s, on) in enumerate([('punching at a support governs', True),
                             ('principal tension exceeds fₑₜₘ', False),
                             ('the bars the moments need will not fit', False),
                             ('utilisation exceeds a target', False)]):
    o += U.radio(PX + 30, PY + 148 + k * 18, s, on, size=9.6)
o.append(S.text(PX + 30, PY + 228, 'the first is what the reference study used', 9, MUT, family='sans'))

o += U.group(PX + 12, PY + 250, PW - 24, 76, 'Within these limits')
for k, (lab, val, unit) in enumerate([('min t', '100', 'mm'), ('max t', '400', 'mm')]):
    o.append(S.text(PX + 30 + k * 140, PY + 284, lab, 9.8, INK2, family='sans'))
    o += U.field(PX + 70 + k * 140, PY + 274, 46, val, 16)
    o.append(S.text(PX + 120 + k * 140, PY + 284, unit, 9.4, MUT))
o.append(S.text(PX + 30, PY + 312, 'step', 9.8, INK2, family='sans'))
o += U.field(PX + 70, PY + 302, 46, '25', 16)
o.append(S.text(PX + 120, PY + 312, 'mm', 9.4, MUT))
o.append(S.text(PX + 170, PY + 312, 'smooth over', 9.8, INK2, family='sans'))
o += U.field(PX + 240, PY + 302, 40, '1.0', 16)
o.append(S.text(PX + 284, PY + 312, 'm', 9.4, MUT))

o += U.button(PX + 12, PY + 336, PW - 24, 24, 'Run the thickening', True)
o += U.group(PX + 12, PY + 370, PW - 24, 88, 'What it did')
for k, s in enumerate(['pass 1 — raised 84 of 1 024 elements',
                       'pass 2 — raised 11',
                       'pass 3 — raised none. Converged.',
                       't now 100–325 mm  ·  concrete +6.2%  ·  steel −38%']):
    o.append(S.text(PX + 30, PY + 394 + k * 15, s, 9.4, OK if k == 2 else INK2,
                    weight='700' if k == 3 else '400', family='sans'))

# ── the three levers ──────────────────────────────────────────────────────
LX = 372
o.append(S.text(LX, 42, 'THE MODE HOLDS THREE LEVERS, NOT ONE', 10, MUT, weight='700', family='sans'))
levers = [('1 · where the material goes', 'a distributed thickness instead of one t — thickest at the supports'),
          ('2 · the edge beam', 'its depth, and whether that depth varies from apex to support'),
          ('3 · the concrete class', 'a stronger mix buys stiffness, and stiffness buys back deflection')]
for k, (t, s) in enumerate(levers):
    x = LX + k * 232
    o.append(U.rect(x, 54, 216, 72, '#f4f7fa', RULE, 1, 3))
    o.append(S.text(x + 12, 74, t, 10, INK, weight='700', family='sans'))
    words = s.split(' ')
    line, ly = '', 90
    for wd in words:
        if len(line) + len(wd) > 34:
            o.append(S.text(x + 12, ly, line, 9.2, INK2, family='sans'))
            line, ly = wd + ' ', ly + 12
        else:
            line += wd + ' '
    o.append(S.text(x + 12, ly, line, 9.2, INK2, family='sans'))

# ── the comparison table ──────────────────────────────────────────────────
TY = 152
o.append(S.text(LX, TY, 'AND PRINTS THE COMPARISON THEY MAKE', 10, MUT, weight='700', family='sans'))
cols = [(0, 'design'), (96, 'thickness'), (196, 'edge beam'), (296, 'class'),
        (368, 'σₜ max'), (436, 'Δ max'), (508, 'Δ / L'), (580, 'As top / bot'), (676, 'verdict')]
hy = TY + 24
for x, lab in cols:
    o.append(S.text(LX + x, hy, lab, 8.6, MUT, weight='700', family='sans'))
o.append(U.line(LX, hy + 7, LX + 684, hy + 7, RULE, 1))
rows = [('1  as built', 'uniform 89', '20 × 45', 'C30/37', '14.44', '−298.9', '1/164',
         '32.9 / 39.6', 'punching fails', RUST),
        ('2  thickened', 'distributed', '20 × 45', 'C40/50', '3.89', '−50.3', '1/973',
         '20.6 / 49.8', 'passes', INK),
        ('3  + edge beam', 'distributed', '30→70 taper', 'C45/55', '2.77', '−36.6', '1/1340',
         '7.3 / 13.4', 'best of the three', OK)]
for k, r in enumerate(rows):
    ry = hy + 26 + k * 26
    if k == 2:
        o.append(U.rect(LX - 6, ry - 13, 696, 22, OK, None, op=0.08))
    o.append(S.text(LX, ry, r[0], 9.6, r[9], weight='700', family='sans'))
    for j, x in [(1, 96), (2, 196), (3, 296)]:
        o.append(S.text(LX + x, ry, r[j], 9.4, INK2))
    for j, x in [(4, 368), (5, 436), (6, 508), (7, 580)]:
        o.append(S.text(LX + x, ry, r[j], 9.4, INK))
    o.append(S.text(LX + 676, ry, r[8], 9.4, r[9], weight='700', family='sans'))
o.append(U.line(LX, hy + 92, LX + 684, hy + 92, RULE, 1))
o.append(S.text(LX, hy + 110, 'mm and MPa and cm²/m, in your unit convention · σₜ is the peak principal '
                'tension, dead load · Δ/L against Isler’s 1/300', 9, MUT, family='sans'))

# ── the point of it ───────────────────────────────────────────────────────
BY = 330
o.append(U.rect(LX, BY, 684, 158, '#f7f9fb', RULE, 1, 3))
o.append(S.text(LX + 16, BY + 24, 'These are real numbers, and they are the argument for the whole mode',
                11.5, INK, weight='700', family='sans'))
lines = [
 ('Kresge Auditorium, Mekjavić & Pičulin (2010), Table 3. Distributing the same concrete — 8.9 cm everywhere, against a', INK2),
 ('thickness that grows to 30 cm at the three supports — takes the peak tension from 14.4 MPa to 3.9, and the deflection', INK2),
 ('from 299 mm to 50. The as-built shell sits at Δ/L = 1/164, four times worse than Isler’s 1/300 rule, and its snow case', INK2),
 ('fails in punching. Design 3 reaches 1/1340 and needs a fifth of the top steel.', INK2),
 ('', INK2),
 ('So automatic thickening is not a tidying-up step. It is the design decision the tab exists to make — which is why it gets', INK),
 ('a mode, a criterion you can name, limits you can build to, a convergence report, and this table.', INK),
]
for k, (s, c) in enumerate(lines):
    o.append(S.text(LX + 16, BY + 46 + k * 15, s, 9.6, c, family='sans'))

open('fig8_thickness_mode.svg', 'w').write(S.svg(W, H, '\n'.join(o), '#ffffff'))
print('fig8 written')
