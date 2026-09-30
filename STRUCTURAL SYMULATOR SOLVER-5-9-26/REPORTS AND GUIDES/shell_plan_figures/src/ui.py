"""Flat SVG primitives for drawing the proposed Tk panels."""
from sv3d import text

INK = '#1e2429'
INK2 = '#4c565f'
MUT = '#77838d'
RULE = '#ccd3da'
SOFT = '#e2e7ec'
PANEL = '#eef1f4'
FIELD = '#ffffff'
BLUE = '#1a6bbd'
RUST = '#c0561f'
GREEN = '#2f7d4f'
CANVAS = '#ffffff'


def rect(x, y, w, h, fill=FIELD, stroke=RULE, sw=1.0, r=0, dash=None, op=None):
    s = ('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%.1f" fill="%s"'
         % (x, y, w, h, r, fill))
    if stroke:
        s += ' stroke="%s" stroke-width="%.2f"' % (stroke, sw)
    if dash:
        s += ' stroke-dasharray="%s"' % dash
    if op is not None:
        s += ' fill-opacity="%.2f"' % op
    return s + '/>'


def line(x1, y1, x2, y2, stroke=RULE, sw=1.0, dash=None, cap='butt'):
    s = ('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%.2f" stroke-linecap="%s"'
         % (x1, y1, x2, y2, stroke, sw, cap))
    if dash:
        s += ' stroke-dasharray="%s"' % dash
    return s + '/>'


def panel(x, y, w, h, title=None, fill=PANEL):
    o = [rect(x, y, w, h, fill, RULE, 1.0, 3)]
    if title:
        o.append(text(x + 12, y + 20, title, 10, MUT, weight='700', family='sans',
                      style='letter-spacing="0.9"'))
        o.append(line(x + 12, y + 28, x + w - 12, y + 28, SOFT, 1))
    return o


def group(x, y, w, h, label):
    """A Tk LabelFrame."""
    o = [rect(x, y + 7, w, h - 7, '#ffffff', RULE, 1.0, 2, op=0.55),
         rect(x + 8, y, len(label) * 5.9 + 8, 14, PANEL, None)]
    o.append(text(x + 12, y + 11, label, 10.5, INK, weight='700', family='sans'))
    return o


def field(x, y, w, val, h=18, ph=False):
    return [rect(x, y, w, h, FIELD, '#aab4bd', 1.0, 1),
            text(x + 6, y + h - 5.5, val, 10.5, MUT if ph else INK)]


def label(x, y, s, size=10.5, fill=INK2, anchor='start', weight='400', fam='sans'):
    return text(x, y, s, size, fill, anchor, weight, fam)


def radio(x, y, s, on=False, size=10.5):
    o = ['<circle cx="%.1f" cy="%.1f" r="5" fill="#fff" stroke="#8c979f" stroke-width="1"/>' % (x, y)]
    if on:
        o.append('<circle cx="%.1f" cy="%.1f" r="2.6" fill="%s"/>' % (x, y, INK))
    o.append(text(x + 11, y + 3.6, s, size, INK, family='sans'))
    return o


def check(x, y, s, on=False, size=10.5):
    o = [rect(x - 5, y - 5, 10, 10, '#fff', '#8c979f', 1.0, 1)]
    if on:
        o.append('<path d="M%.1f %.1f l2.2 2.4 l4.2 -5.2" fill="none" stroke="%s" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>' % (x - 3.2, y - 0.2, INK))
    o.append(text(x + 11, y + 3.6, s, size, INK, family='sans'))
    return o


def button(x, y, w, h, s, primary=False, size=10.5):
    bg = '#dce9f6' if primary else '#e7ebef'
    ed = BLUE if primary else '#aab4bd'
    return [rect(x, y, w, h, bg, ed, 1.0, 2),
            text(x + w / 2, y + h / 2 + 3.6, s, size, INK if not primary else '#124a80',
                 'middle', '700' if primary else '600', 'sans')]


def swatch(x, y, c, w=10, h=10):
    return rect(x, y, w, h, c, '#55606a', 0.8, 1.5)


def eye(x, y, on=True):
    c = INK if on else '#b7c0c8'
    o = ['<path d="M%.1f %.1f q6 -6.5 12 0 q-6 6.5 -12 0z" fill="none" stroke="%s" stroke-width="1.2"/>'
         % (x, y, c),
         '<circle cx="%.1f" cy="%.1f" r="2.1" fill="%s"/>' % (x + 6, y, c)]
    if not on:
        o.append(line(x, y + 5, x + 12, y - 5, c, 1.2))
    return o


def callout(x, y, s, w=None, fill=RUST, size=10):
    return text(x, y, s, size, fill, 'start', '600', 'sans')


def leader(x1, y1, x2, y2, c=RUST):
    return [line(x1, y1, x2, y2, c, 1.0),
            '<circle cx="%.1f" cy="%.1f" r="2.2" fill="%s"/>' % (x2, y2, c)]
