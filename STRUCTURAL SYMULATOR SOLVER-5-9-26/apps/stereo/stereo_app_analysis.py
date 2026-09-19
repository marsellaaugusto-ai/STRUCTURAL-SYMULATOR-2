"""The Analyse mode's charts: small Tk-canvas plots of what the solve found.

Why charts and not more numbers. The status bar already gives the single
governing utilisation, and the member report gives every row. Neither answers
the question a designer actually asks after a solve -- *is this structure
working as a whole, or is one member carrying the day?* A governing
utilisation of 0.9 means something completely different when six members are
near it than when one is and the rest are at 0.05. That shape is what a
histogram shows and a table does not.

Everything here draws into a plain tk.Canvas of a given width, returns the
height it used, and reads only what `analyze` already produced. No solving,
no model changes -- a chart that could alter the model would be a trap.
"""
import tkinter as tk

from apps.stereo.stereo_app_colors import force_color, util_color

CHART_BG = '#ffffff'
CHART_EDGE = '#d7dde2'
AXIS_FG = '#8a959d'
LABEL_FG = '#3b464e'
BAR_EDGE = '#ffffff'

# Utilisation bands. The last one is deliberately open-ended and separate:
# "over capacity" is a different kind of fact from "80-100% used", and
# burying it in a top band would hide the only bar that fails the check.
UTIL_BANDS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0))
UTIL_OVER = 'over'


def _frame(c, w, h, title):
    """The common chrome: a bordered plot box with a caption above it."""
    c.create_text(6, 2, text=title, anchor='nw', fill=LABEL_FG,
                  font=('Helvetica', 8, 'bold'))
    top = 18
    c.create_rectangle(6, top, w - 6, top + h, fill=CHART_BG, outline=CHART_EDGE)
    return top


def _empty(c, w, msg):
    c.create_text(w / 2, 26, text=msg, fill=AXIS_FG, font=('Helvetica', 8))
    return 44


def utilisation_histogram(canvas, width, checks, frac=1.0):
    """How many members sit in each utilisation band.

    `frac` is the Load % slider: the model is linear, so every utilisation
    scales with it exactly, and the histogram has to move with the slider or
    it would describe a load case nobody is looking at.
    """
    c = canvas
    utils = [ch['util'] * frac for ch in (checks or [])
             if ch.get('checked') and ch.get('util') is not None]
    if not utils:
        return _empty(c, width, 'Run ▶ Analyze to see utilisation.')

    counts = [0] * (len(UTIL_BANDS) + 1)
    for u in utils:
        for k, (lo, hi) in enumerate(UTIL_BANDS):
            if lo <= u < hi:
                counts[k] += 1
                break
        else:
            counts[-1] += 1

    h = 74
    top = _frame(c, width, h, f'Utilisation of {len(utils)} checked members')
    peak = max(counts) or 1
    n = len(counts)
    slot = (width - 22) / n
    base = top + h - 14
    for k, count in enumerate(counts):
        x0 = 11 + k * slot + 2
        x1 = 11 + (k + 1) * slot - 2
        bar = (base - top - 4) * (count / peak)
        if k < len(UTIL_BANDS):
            mid = sum(UTIL_BANDS[k]) / 2.0
            label = f'{UTIL_BANDS[k][1]:.1f}'
        else:
            mid = 1.2
            label = '>1'
        if count:
            c.create_rectangle(x0, base - bar, x1, base, fill=util_color(mid),
                               outline=BAR_EDGE)
            c.create_text((x0 + x1) / 2, base - bar - 6, text=str(count),
                          fill=LABEL_FG, font=('Helvetica', 7))
        c.create_text((x0 + x1) / 2, base + 6, text=label, fill=AXIS_FG,
                      font=('Helvetica', 7))
    if counts[-1]:
        c.create_text(width - 10, top + 8, anchor='ne',
                      text=f'{counts[-1]} over capacity', fill='#a3241a',
                      font=('Helvetica', 7, 'bold'))
    return top + h + 10


def force_split(canvas, width, member_res, frac=1.0):
    """Tension against compression: how the work is divided, and by how much.

    Drawn as one bar split about a centre line rather than two histograms,
    because the useful reading is the BALANCE -- a space frame with almost
    everything in compression is telling you something about its supports.
    """
    c = canvas
    forces = [r.get('N', 0.0) * frac for r in (member_res or [])]
    if not forces:
        return _empty(c, width, 'Run ▶ Analyze to see the force split.')

    peak = max((abs(f) for f in forces), default=0.0)
    if peak <= 0:
        return _empty(c, width, 'Every member carries zero force.')
    near_zero = [f for f in forces if abs(f) < 0.03 * peak]
    tens = [f for f in forces if f >= 0.03 * peak]
    comp = [f for f in forces if f <= -0.03 * peak]

    h = 70
    top = _frame(c, width, h, f'Axial force in {len(forces)} rods')
    left, right = 12, width - 12
    span = right - left
    total = max(1, len(forces))
    x = left
    for group, color in ((comp, force_color(-peak, peak)),
                         (near_zero, '#c8cfd4'),
                         (tens, force_color(peak, peak))):
        seg = span * (len(group) / total)
        if seg > 0:
            c.create_rectangle(x, top + 8, x + seg, top + 26, fill=color,
                               outline=BAR_EDGE)
        x += seg
    # One label per line. Side by side they collided at 250 px, which is the
    # only width this panel is ever asked to be.
    y = top + 32
    for text in (f'{len(comp)} compression, peak {-min(forces):,.1f}'.replace(',', ' '),
                 f'{len(tens)} tension, peak {max(forces):,.1f}'.replace(',', ' ')):
        c.create_text(left, y, anchor='nw', text=text, fill=LABEL_FG,
                      font=('Helvetica', 7))
        y += 11
    if near_zero:
        c.create_text(left, y, anchor='nw',
                      text=f'{len(near_zero)} carry ~nothing (<3% of peak)',
                      fill=AXIS_FG, font=('Helvetica', 7))
    return top + h + 10


def cell_census(canvas, width, roles, cells):
    """How many DIFFERENT cells the mesh is made of, and how dominant the
    repeating one is.

    This is the buildability reading. A grid whose role 0 covers 95% of its
    cells is one module plus a few edge pieces; one where role 0 covers 30%
    is a dozen bespoke parts, which is a fabrication cost the geometry panel
    never mentions.
    """
    c = canvas
    if not roles or not cells:
        return _empty(c, width, 'No closed cells in this mesh.')

    total = len(cells)
    ordered = sorted(roles.items(), key=lambda kv: -len(kv[1]))
    shown = ordered[:5]
    rest = sum(len(v) for _k, v in ordered[5:])

    rows = len(shown) + (1 if rest else 0)
    h = 16 + rows * 13
    top = _frame(c, width, h, f'{total} cells in {len(roles)} distinct shapes')
    left, right = 12, width - 14
    span = right - left - 46
    y = top + 8
    palette = ('#1a6bbd', '#4a90d9', '#7fb3e3', '#aecdee', '#d5e4f7')
    for k, (role_id, idxs) in enumerate(shown):
        frac = len(idxs) / total
        c.create_rectangle(left, y, left + max(2, span * frac), y + 9,
                           fill=palette[k % len(palette)], outline=BAR_EDGE)
        c.create_text(right, y + 4, anchor='e',
                      text=f'role {role_id}: {len(idxs)} ({frac * 100:.0f}%)',
                      fill=LABEL_FG, font=('Helvetica', 7))
        y += 13
    if rest:
        c.create_text(left, y + 4, anchor='w',
                      text=f'+ {rest} one-off cell(s) in {len(ordered) - 5} more shapes',
                      fill=AXIS_FG, font=('Helvetica', 7))
    return top + h + 10


def support_reactions(canvas, width, reactions, unit_label='kN', frac=1.0):
    """Where the load actually goes down. Bars per support, tallest first,
    so an unevenly loaded support line is visible rather than inferred from
    a table of numbers."""
    c = canvas
    # analyze returns {node_idx: {'Fx','Fy','Fz','Mx','My','Mz'}} in kN.
    rows = [(i, abs(r.get('Fz', 0.0)) * frac)
            for i, r in (reactions or {}).items()]
    rows = [(i, v) for i, v in rows if v > 1e-9]
    if not rows:
        return _empty(c, width, 'Run ▶ Analyze to see reactions.')
    rows.sort(key=lambda t: -t[1])
    total = sum(v for _i, v in rows)
    shown = rows[:8]

    h = 20 + len(shown) * 12
    top = _frame(c, width, h,
                 f'{len(rows)} supports carry {total:,.0f} {unit_label}'.replace(',', ' '))
    peak = shown[0][1]
    left, right = 12, width - 14
    span = right - left - 62
    y = top + 8
    for node, value in shown:
        c.create_rectangle(left, y, left + max(2, span * (value / peak)), y + 8,
                           fill='#2f6f4f', outline=BAR_EDGE)
        c.create_text(right, y + 4, anchor='e',
                      text=f'n{node}: {value:,.1f}'.replace(',', ' '),
                      fill=LABEL_FG, font=('Helvetica', 7))
        y += 12
    if len(rows) > len(shown):
        c.create_text(left, y + 4, anchor='w',
                      text=f'+ {len(rows) - len(shown)} smaller',
                      fill=AXIS_FG, font=('Helvetica', 7))
    return top + h + 10
