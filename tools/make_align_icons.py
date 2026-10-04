#!/usr/bin/env python3
"""Generate the four PNG icons for the "Align by Points" tools.

Written by hand (zlib + struct, no Pillow) so the icons can be regenerated
anywhere the repo is checked out:

    python3 tools/make_align_icons.py

Writes align_face_small.png (16x16), align_face_large.png (24x24),
align_nodes_small.png, align_nodes_large.png into the extension's icons/
folder. Both glyphs use the same palette as the existing toolbar icons: a
blue "source" element, a red "target" element, dark outlines.
"""
import os
import struct
import zlib

BLUE = (33, 90, 190, 255)
RED = (200, 48, 48, 255)
DARK = (40, 40, 48, 255)
GREY = (120, 126, 136, 255)
CLEAR = (0, 0, 0, 0)

ICON_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "sketchup_extension",
    "coordinate_coordinator_truss_app_amac",
    "icons",
)


class Canvas:
    def __init__(self, size):
        self.size = size
        self.px = [[CLEAR] * size for _ in range(size)]

    def set(self, x, y, color):
        x, y = int(round(x)), int(round(y))
        if 0 <= x < self.size and 0 <= y < self.size:
            self.px[y][x] = color

    def line(self, x0, y0, x1, y1, color, width=1):
        """Bresenham, thickened by stamping a square brush."""
        x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while True:
            for ox in range(width):
                for oy in range(width):
                    self.set(x0 + ox, y0 + oy, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def polygon(self, pts, color):
        """Scanline fill of a convex/simple polygon."""
        ys = [p[1] for p in pts]
        for y in range(int(min(ys)), int(max(ys)) + 1):
            xs = []
            for i in range(len(pts)):
                (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % len(pts)]
                if y0 == y1:
                    continue
                if min(y0, y1) <= y < max(y0, y1):
                    xs.append(x0 + (y - y0) * (x1 - x0) / float(y1 - y0))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                for x in range(int(round(xs[i])), int(round(xs[i + 1])) + 1):
                    self.set(x, y, color)

    def dot(self, cx, cy, r, color):
        for y in range(int(cy - r), int(cy + r) + 1):
            for x in range(int(cx - r), int(cx + r) + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r + 0.25:
                    self.set(x, y, color)

    def write(self, path):
        raw = b"".join(
            b"\x00" + b"".join(struct.pack("BBBB", *self.px[y][x]) for x in range(self.size))
            for y in range(self.size)
        )

        def chunk(tag, data):
            return (
                struct.pack(">I", len(data))
                + tag
                + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
            )

        png = b"\x89PNG\r\n\x1a\n"
        png += chunk(b"IHDR", struct.pack(">IIBBBBB", self.size, self.size, 8, 6, 0, 0, 0))
        png += chunk(b"IDAT", zlib.compress(raw, 9))
        png += chunk(b"IEND", b"")
        with open(path, "wb") as fh:
            fh.write(png)


def align_face(size):
    """Two slabs — a blue source plate swinging onto a red inclined plate —
    with the three picked points marked on each."""
    c = Canvas(size)
    s = size / 24.0
    r = max(1, int(round(1.2 * s)))

    # Target plate: inclined, lower right, red.
    c.polygon(
        [(9 * s, 20 * s), (22 * s, 12 * s), (22 * s, 15 * s), (9 * s, 23 * s)], RED
    )
    c.line(9 * s, 20 * s, 22 * s, 12 * s, DARK, max(1, int(s)))
    # Source plate: flat, upper left, blue.
    c.polygon([(1 * s, 4 * s), (13 * s, 4 * s), (13 * s, 7 * s), (1 * s, 7 * s)], BLUE)
    c.line(1 * s, 4 * s, 13 * s, 4 * s, DARK, max(1, int(s)))

    # Picked points: A on the source plate, B on the target plate.
    c.dot(2.5 * s, 4 * s, r, DARK)
    c.dot(12 * s, 4 * s, r, DARK)
    c.dot(10.5 * s, 20 * s, r, DARK)
    c.dot(21 * s, 13 * s, r, DARK)

    # Motion arrow from source to target.
    c.line(5 * s, 9 * s, 7 * s, 17 * s, GREY, max(1, int(s)))
    c.line(7 * s, 17 * s, 4.5 * s, 14 * s, GREY, max(1, int(s)))
    c.line(7 * s, 17 * s, 9 * s, 13.5 * s, GREY, max(1, int(s)))
    return c


def align_nodes(size):
    """A box (the group) with three of its nodes highlighted, landing on a
    red target plane."""
    c = Canvas(size)
    s = size / 24.0
    r = max(1, int(round(1.4 * s)))
    w = max(1, int(round(s)))

    # Target plane, inclined, red.
    c.polygon([(6 * s, 21 * s), (23 * s, 14 * s), (23 * s, 17 * s), (6 * s, 24 * s)], RED)

    # Box: front face + offset back face + connectors.
    fx, fy, d = 2 * s, 6 * s, 4 * s
    bw, bh = 10 * s, 8 * s
    front = [(fx, fy), (fx + bw, fy), (fx + bw, fy + bh), (fx, fy + bh)]
    for i in range(4):
        a, b = front[i], front[(i + 1) % 4]
        c.line(a[0], a[1], b[0], b[1], BLUE, w)
    back = [(x + d, y - d * 0.6) for (x, y) in front]
    for i in range(4):
        a, b = back[i], back[(i + 1) % 4]
        c.line(a[0], a[1], b[0], b[1], GREY, w)
    for i in range(4):
        c.line(front[i][0], front[i][1], back[i][0], back[i][1], GREY, w)

    # Three highlighted nodes (the picks).
    for (x, y) in (front[0], front[2], back[1]):
        c.dot(x, y, r, DARK)
    return c


def main():
    os.makedirs(ICON_DIR, exist_ok=True)
    for name, builder in (("align_face", align_face), ("align_nodes", align_nodes)):
        for suffix, size in (("small", 16), ("large", 24)):
            path = os.path.join(ICON_DIR, "%s_%s.png" % (name, suffix))
            builder(size).write(path)
            print("wrote", path)


if __name__ == "__main__":
    main()
