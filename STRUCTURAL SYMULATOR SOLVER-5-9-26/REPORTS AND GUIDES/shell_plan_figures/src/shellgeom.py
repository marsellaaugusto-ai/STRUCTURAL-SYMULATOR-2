"""The one shell used by every figure: a shallow dome on a 12 x 12 m square
plan, standing on its four corners, with an automatic thickening law that
answers the corners."""
import math

A = 3.0          # half-span in x (m)
B = 3.0          # half-span in y (m)
H = 1.30          # rise (m)
T0 = 0.15        # base thickness (m)
TMAX = 0.45      # thickest (m)
CORNERS = [(-A, -B), (A, -B), (A, B), (-A, B)]


def z(x, y):
    return H * math.cos(math.pi * x / (2 * A)) * math.cos(math.pi * y / (2 * B))


def dz(x, y, h=1e-4):
    return ((z(x + h, y) - z(x - h, y)) / (2 * h),
            (z(x, y + h) - z(x, y - h)) / (2 * h))


def nrm(x, y):
    zx, zy = dz(x, y)
    n = (-zx, -zy, 1.0)
    L = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
    return (n[0] / L, n[1] / L, n[2] / L)


def dcorner(x, y):
    return min(math.hypot(x - cx, y - cy) for cx, cy in CORNERS)


def thick(x, y, on=True):
    """What 'automatic thickening' does here: keep the membrane thin where it
    is a membrane, and put material where the corner supports and the stiffened
    free edges make it bend."""
    if not on:
        return T0
    fc = math.exp(-(dcorner(x, y) / 1.9) ** 2)
    de = min(A - abs(x), B - abs(y))
    fe = 0.55 * math.exp(-(de / 0.85) ** 2)
    return T0 + (TMAX - T0) * max(fc, fe)


def mid(x, y):
    return (x, y, z(x, y))


def off(x, y, s, on=True):
    """A point on the top (s=+1) or bottom (s=-1) face."""
    nx, ny, nz = nrm(x, y)
    t = thick(x, y, on) / 2.0
    return (x + s * t * nx, y + s * t * ny, z(x, y) + s * t * nz)


def grid(n):
    return [-A + 2 * A * i / n for i in range(n + 1)], [-B + 2 * B * j / n for j in range(n + 1)]
