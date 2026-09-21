"""The figures for the domain / trimming / governing-element note.

Every grid drawing here is computed from the same rules the tab uses -- an
element is judged at its centre -- so the pictures cannot drift from the
code by being drawn from memory. Output: plain SVG strings, themed through
CSS custom properties so they read on both a light and a dark page.
"""
import math

W = 300          # one panel
PAD = 16


def _grid(n, size):
    """n x n cells over [-1, 1]^2 mapped into a `size` box."""
    step = size / n
    return step


def _px(u, size):
    """model coordinate in [-1, 1] -> pixel in [0, size]"""
    return (u + 1.0) * size / 2.0


def ellipse_cut(n=12, rx=0.86, ry=0.72, size=248, show_centres=True,
                show_band=True):
    """The plan cut as it happens today: keep where (x/rx)^2 + (y/ry)^2 < 1,
    judged at the element centre."""
    out = []
    step = 2.0 / n
    kept, dropped = [], []
    for j in range(n):
        for i in range(n):
            cx = -1 + (i + 0.5) * step
            cy = -1 + (j + 0.5) * step
            inside = (cx / rx) ** 2 + (cy / ry) ** 2 < 1.0
            x0, y0 = _px(-1 + i * step, size), _px(-1 + j * step, size)
            w = step * size / 2
            (kept if inside else dropped).append((x0, y0, w, cx, cy, inside))
    for x0, y0, w, cx, cy, ins in dropped:
        out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{w:.1f}" '
                   f'class="cell-out"/>')
    for x0, y0, w, cx, cy, ins in kept:
        out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{w:.1f}" '
                   f'class="cell-in"/>')
    if show_band:
        # the half-element band the centre test can overshoot by
        h = step * size / 2 / 2 * math.sqrt(2)
        for f, cls in ((1.0, 'band'),):
            out.append(_ell_path(rx, ry, size, grow=h, cls='band'))
            out.append(_ell_path(rx, ry, size, grow=-h, cls='band'))
    out.append(_ell_path(rx, ry, size, cls='curve'))
    if show_centres:
        for x0, y0, w, cx, cy, ins in kept + dropped:
            out.append(f'<circle cx="{x0 + w/2:.1f}" cy="{y0 + w/2:.1f}" r="1.7" '
                       f'class="{"dot-in" if ins else "dot-out"}"/>')
    return '\n'.join(out), len(kept), n * n


def _ell_path(rx, ry, size, grow=0.0, cls='curve', n=180):
    pts = []
    for k in range(n + 1):
        th = 2 * math.pi * k / n
        # outward normal offset by `grow` pixels
        px, py = rx * math.cos(th), ry * math.sin(th)
        nx, ny = math.cos(th) / rx, math.sin(th) / ry
        L = math.hypot(nx, ny) or 1.0
        gx = grow / (size / 2)
        px += gx * nx / L
        py += gx * ny / L
        pts.append(f'{_px(px, size):.1f},{_px(py, size):.1f}')
    return f'<polyline points="{" ".join(pts)}" class="{cls}"/>'


def trimmed_cut(n=12, rx=0.86, ry=0.72, size=248):
    """Option B: the kept cells are clipped to the curve for DRAWING only."""
    body, kept, tot = ellipse_cut(n, rx, ry, size, show_centres=False, show_band=False)
    clip = _ell_path(rx, ry, size, cls='curve')
    return (f'<defs><clipPath id="clipEll"><path d="{_ell_d(rx, ry, size)}"/></clipPath></defs>'
            f'<g clip-path="url(#clipEll)">{body}</g>{clip}')


def _ell_d(rx, ry, size, n=180):
    pts = []
    for k in range(n + 1):
        th = 2 * math.pi * k / n
        pts.append(f'{_px(rx*math.cos(th), size):.1f},{_px(ry*math.sin(th), size):.1f}')
    return 'M ' + ' L '.join(pts) + ' Z'


def fitted_cut(n=12, rx=0.86, ry=0.72, size=248, snap=0.55):
    """Option C: the boundary NODES are moved onto the curve, so the element
    edges follow it. A node moves only if the move is under `snap` of an
    element; the cells are then real quadrilaterals, drawn as such."""
    step = 2.0 / n
    def inside(cx, cy):
        return (cx / rx) ** 2 + (cy / ry) ** 2 < 1.0
    # which cells survive (same centre test)
    keep = {}
    for j in range(n):
        for i in range(n):
            cx, cy = -1 + (i + .5) * step, -1 + (j + .5) * step
            keep[(i, j)] = inside(cx, cy)
    # nodes on the boundary of the kept set get projected onto the ellipse
    node = {}
    for j in range(n + 1):
        for i in range(n + 1):
            nx_, ny_ = -1 + i * step, -1 + j * step
            touch = [keep.get((i + di, j + dj), False)
                     for di in (-1, 0) for dj in (-1, 0)]
            on_edge = any(touch) and not all(touch)
            if on_edge:
                px, py = _project(nx_, ny_, rx, ry)
                if math.hypot(px - nx_, py - ny_) <= snap * step:
                    nx_, ny_ = px, py
            node[(i, j)] = (nx_, ny_)
    out = []
    for (i, j), ok in keep.items():
        if not ok:
            continue
        p = [node[(i, j)], node[(i + 1, j)], node[(i + 1, j + 1)], node[(i, j + 1)]]
        pts = ' '.join(f'{_px(a, size):.1f},{_px(b, size):.1f}' for a, b in p)
        out.append(f'<polygon points="{pts}" class="cell-in"/>')
    out.append(_ell_path(rx, ry, size, cls='curve'))
    return '\n'.join(out)


def _project(x, y, rx, ry, it=60):
    """Nearest point of the ellipse, by Newton on the angle."""
    th = math.atan2(y / ry, x / rx)
    for _ in range(it):
        cx, cy = rx * math.cos(th), ry * math.sin(th)
        dx, dy = -rx * math.sin(th), ry * math.cos(th)
        ddx, ddy = -rx * math.cos(th), -ry * math.sin(th)
        f = (cx - x) * dx + (cy - y) * dy
        fp = dx * dx + dy * dy + (cx - x) * ddx + (cy - y) * ddy
        if abs(fp) < 1e-12:
            break
        th -= f / fp
    return rx * math.cos(th), ry * math.sin(th)


def ghost_cut(n=12, rx=0.86, ry=0.72, size=248):
    """Option A: everything is drawn, the outside faintly (Tk has no alpha,
    so on the real canvas this is a stipple)."""
    body, _, _ = ellipse_cut(n, rx, ry, size, show_centres=False, show_band=False)
    return (body.replace('class="cell-out"', 'class="cell-ghost"')
            + '\n' + _ell_path(rx, ry, size, cls='curve'))


# ── a hypar patch in isometric, so the 3-D pictures are the real surface ──
def hypar_iso(rule=None, n=14, w=300, h=200, k=0.5, ghost=False,
              trim=None, rulings=False, az=0.35, el=0.55, zex=1.0, pad=10,
              zfun=None):
    """z = k x y over [-1, 1]^2, drawn painter-order in an isometric view.

    rule(x, y) -> bool keeps a cell (judged at its centre, as the tab does).
    ghost=True draws the discarded cells faintly instead of not at all.
    trim(x, y, i, j) -> (x, y) may pull a NODE onto the boundary curve.

    On the azimuth: at az = 45 degrees the eye looks straight down the high
    diagonal of the saddle, the whole ridge projects to one vertical line and
    the surface reads as a folded tent. 20 degrees breaks that symmetry. The
    elevation stays high enough that the plan still reads as a quadrilateral.

    `zfun` overrides z. For an illustration, pass the saddle in its OWN axes,
    z = k(x^2 - y^2) -- the same hyperbolic paraboloid rotated 45 degrees in
    plan. Drawn as z = k x y its two high corners sit on the depth diagonal,
    one of them projects inside the outline of the other three, and the patch
    reads as a folded wing instead of a saddle.
    The result is fitted to the box afterwards, so neither angle can push the
    drawing outside its viewBox.
    """
    ca, sa = math.cos(az), math.sin(az)
    ce, se = math.cos(el), math.sin(el)

    def raw(x, y, z):
        return (ca * x - sa * y, -(sa * x + ca * y) * se - ce * z * zex)

    step = 2.0 / n
    node = {}
    for j in range(n + 1):
        for i in range(n + 1):
            x, y = -1 + i * step, -1 + j * step
            if trim is not None:
                x, y = trim(x, y, i, j)
            node[(i, j)] = (x, y, (zfun(x, y) if zfun else k * x * y))
    pts = [raw(*q) for q in node.values()]
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    sx = (w - 2 * pad) / max(max(xs) - min(xs), 1e-9)
    sy = (h - 2 * pad) / max(max(ys) - min(ys), 1e-9)
    sc = min(sx, sy)
    ox = pad + ((w - 2 * pad) - (max(xs) - min(xs)) * sc) / 2 - min(xs) * sc
    oy = pad + ((h - 2 * pad) - (max(ys) - min(ys)) * sc) / 2 - min(ys) * sc

    def proj(x, y, z):
        px, py = raw(x, y, z)
        return ox + px * sc, oy + py * sc

    cells = []
    for j in range(n):
        for i in range(n):
            cx, cy = -1 + (i + .5) * step, -1 + (j + .5) * step
            keep = True if rule is None else bool(rule(cx, cy))
            if not keep and not ghost:
                continue
            p = [node[(i, j)], node[(i + 1, j)], node[(i + 1, j + 1)], node[(i, j + 1)]]
            depth = sum(math.sin(az) * a + math.cos(az) * b for a, b, _ in p)
            cells.append((depth, p, keep))
    cells.sort(key=lambda c: -c[0])          # far first: painter order
    out = []
    for _d, p, keep in cells:
        pts_ = ' '.join('%.1f,%.1f' % proj(*q) for q in p)
        out.append(f'<polygon points="{pts_}" class="{"face" if keep else "face-ghost"}"/>')
    if rulings:
        for t in (-1, -0.5, 0, 0.5, 1):
            a1, b1 = proj(t, -1, k * t * -1), proj(t, 1, k * t * 1)
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="ruling"/>'
                       % (a1[0], a1[1], b1[0], b1[1]))
            a1, b1 = proj(-1, t, -k * t), proj(1, t, k * t)
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="ruling"/>'
                       % (a1[0], a1[1], b1[0], b1[1]))
    return '\n'.join(out)


def snap_to_ellipse(rx, ry, tol):
    """A `trim` for hypar_iso: pull a node onto the ellipse if it is within
    `tol` of it and its cell neighbourhood straddles the curve."""
    def f(x, y, i, j):
        r = math.hypot(x / rx, y / ry)
        if r < 1e-9:
            return x, y
        px, py = _project(x, y, rx, ry)
        if math.hypot(px - x, py - y) <= tol:
            return px, py
        return x, y
    return f


def staircase_outline(n=12, rx=0.86, ry=0.72, size=248, cls='stair'):
    """The boundary of the KEPT set, as the segments an element edge with only
    one element behind it traces. This is what the solver still sees when only
    the drawing has been trimmed."""
    step = 2.0 / n
    keep = {}
    for j in range(n):
        for i in range(n):
            cx, cy = -1 + (i + .5) * step, -1 + (j + .5) * step
            keep[(i, j)] = (cx / rx) ** 2 + (cy / ry) ** 2 < 1.0
    segs = []
    for (i, j), ok in keep.items():
        if not ok:
            continue
        x0, y0 = -1 + i * step, -1 + j * step
        x1, y1 = x0 + step, y0 + step
        if not keep.get((i - 1, j), False): segs.append(((x0, y0), (x0, y1)))
        if not keep.get((i + 1, j), False): segs.append(((x1, y0), (x1, y1)))
        if not keep.get((i, j - 1), False): segs.append(((x0, y0), (x1, y0)))
        if not keep.get((i, j + 1), False): segs.append(((x0, y1), (x1, y1)))
    out = []
    for (ax, ay), (bx, by) in segs:
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="%s"/>'
                   % (_px(ax, size), _px(ay, size), _px(bx, size), _px(by, size), cls))
    return '\n'.join(out)
