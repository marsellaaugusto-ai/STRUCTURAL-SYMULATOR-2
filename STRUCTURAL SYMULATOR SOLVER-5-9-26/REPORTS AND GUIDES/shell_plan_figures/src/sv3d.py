"""Tiny painter's-algorithm 3D -> SVG helper for the plan figures.

Deliberately the same drawing model the Tk app uses: project, sort by depth,
paint back to front. No z-buffer, so a figure drawn here cannot promise
something the real canvas could not deliver.
"""
import math

AZ = math.radians(35.0)
EL = math.radians(24.0)


def project(p, scale=1.0, az=AZ, el=EL):
    x, y, z = p
    X = x * math.cos(az) - y * math.sin(az)
    Y = x * math.sin(az) + y * math.cos(az)
    sx = X * scale
    sy = (Y * math.sin(el) - z * math.cos(el)) * scale
    depth = Y * math.cos(el) + z * math.sin(el)
    return sx, sy, depth


def normal(poly):
    ax, ay, az_ = poly[0]
    bx, by, bz = poly[1]
    cx, cy, cz = poly[2]
    ux, uy, uz = bx - ax, by - ay, bz - az_
    vx, vy, vz = cx - ax, cy - ay, cz - az_
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    L = math.hypot(math.hypot(nx, ny), nz) or 1.0
    return nx / L, ny / L, nz / L


LIGHT = (-0.35, -0.55, 0.76)


def shade(poly, base, amb=0.48, gain=0.52):
    n = normal(poly)
    d = abs(n[0] * LIGHT[0] + n[1] * LIGHT[1] + n[2] * LIGHT[2])
    f = amb + gain * d
    return mix(base, (255, 255, 255), min(1.0, max(0.0, (f - 0.45) * 1.15)))


def mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def hexof(c):
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(round(v)))) for v in c)


def ramp(t, stops):
    """t in 0..1 through a list of (pos, (r,g,b))."""
    t = max(0.0, min(1.0, t))
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if t <= p1 or i == len(stops) - 2:
            u = 0.0 if p1 <= p0 else (t - p0) / (p1 - p0)
            return mix(c0, c1, max(0.0, min(1.0, u)))
    return stops[-1][1]


class Scene:
    """Collects faces and lines, then emits them back-to-front."""

    def __init__(self, scale=26.0, cx=0.0, cy=0.0, az=AZ, el=EL):
        self.items = []
        self.scale = scale
        self.cx, self.cy = cx, cy
        self.az, self.el = az, el

    def pt(self, p):
        sx, sy, d = project(p, self.scale, self.az, self.el)
        return (sx + self.cx, sy + self.cy, d)

    def face(self, poly, fill, stroke=None, sw=0.6, op=1.0, bias=0.0):
        pts = [self.pt(p) for p in poly]
        d = sum(q[2] for q in pts) / len(pts) + bias
        path = ' '.join('%.2f,%.2f' % (q[0], q[1]) for q in pts)
        s = '<polygon points="%s" fill="%s"' % (path, fill)
        if stroke:
            s += ' stroke="%s" stroke-width="%.2f" stroke-linejoin="round"' % (stroke, sw)
        if op != 1.0:
            s += ' fill-opacity="%.2f"' % op
        s += '/>'
        self.items.append((d, s))

    def line(self, a, b, stroke='#1e2429', sw=1.0, dash=None, bias=0.0, cap='round', op=1.0):
        pa, pb = self.pt(a), self.pt(b)
        d = (pa[2] + pb[2]) / 2 + bias
        s = ('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" '
             'stroke-width="%.2f" stroke-linecap="%s"' % (pa[0], pa[1], pb[0], pb[1], stroke, sw, cap))
        if dash:
            s += ' stroke-dasharray="%s"' % dash
        if op != 1.0:
            s += ' stroke-opacity="%.2f"' % op
        s += '/>'
        self.items.append((d, s))

    def dot(self, p, r=2.4, fill='#1e2429', stroke=None, sw=1.0, bias=0.0):
        q = self.pt(p)
        s = '<circle cx="%.2f" cy="%.2f" r="%.2f" fill="%s"' % (q[0], q[1], r, fill)
        if stroke:
            s += ' stroke="%s" stroke-width="%.2f"' % (stroke, sw)
        s += '/>'
        self.items.append((q[2] + bias, s))

    def raw(self, svg, depth):
        self.items.append((depth, svg))

    def text3(self, p, txt, **kw):
        q = self.pt(p)
        self.items.append((q[2] + kw.pop('bias', 1e6), text(q[0], q[1], txt, **kw)))

    def render(self):
        return '\n'.join(s for _, s in sorted(self.items, key=lambda it: it[0]))


def text(x, y, s, size=11, fill='#1e2429', anchor='start', weight='400',
         family='mono', style=''):
    fam = ("'IBM Plex Mono',ui-monospace,Menlo,monospace" if family == 'mono'
           else "'IBM Plex Sans Condensed',-apple-system,'Segoe UI',sans-serif")
    esc = (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
    return ('<text x="%.2f" y="%.2f" font-family="%s" font-size="%.1f" fill="%s" '
            'text-anchor="%s" font-weight="%s" %s>%s</text>'
            % (x, y, fam, size, fill, anchor, weight, style, esc))


def svg(w, h, body, bg='none'):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="100%%" '
            'role="img">\n<rect width="%d" height="%d" fill="%s"/>\n%s\n</svg>'
            % (w, h, w, h, bg, body))
