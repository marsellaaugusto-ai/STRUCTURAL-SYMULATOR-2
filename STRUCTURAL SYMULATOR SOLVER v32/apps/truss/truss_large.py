"""Models of about a hundred members, for the large-model protocol.

REPORTS AND GUIDES/LARGE_MODEL_PROTOCOL_v32_t12_2026-10-13.md walks one
of these through the whole tab: building, the stability line, ▶ Analyze,
reading the canvas, checking the numbers by hand, the PDF and the Excel
round trip. tests/test_truss_large_model.py runs the same protocol
automatically, so a change that breaks the tab for a big model fails a
test instead of a student's hand-in.

THE K-TRUSS BRIDGE. Sixteen 4 m panels make a 64 m span, 8 m deep
(span / 8, a usual depth for a through-truss). Every vertical except the
middle one is split at mid-height, and from that mid node two diagonals
run to the top and the bottom of the next vertical, pointing away from
midspan: the "K" that gives the type its name. The deck hangs from the
bottom chord, so the loads go on the bottom joints.

    joints   17 bottom + 17 top + 16 mid-height   = 50
    members  16 + 16 chords, 29 + 4 vertical pieces, 32 diagonals = 97
    m + r - 2j = 97 + 3 - 100 = 0: statically determinate

so every force follows from statics, and two of them can be checked by
hand in a line each (see `hand_checks`).

Coordinates come out in canvas pixels like the example library's
(truss_examples._model, 24 px = 1 m, y down); loads in kN, fy positive
downwards. Kept free of Tk.
"""
from . import truss_examples as tx

#: The bridge's sections, sized so every family passes CIRSOC 301 with
#: room to spare (worst utilisation 0.73 pinned, 0.75 rigid).
K_BRIDGE_FAMILIES = {
    'Top chord': 'HEB 220',
    'Bottom chord': 'HEA 220',
    'End post': 'SHS 200x200x8',
    'Vertical': 'SHS 120x120x5',
    'Diagonal': 'SHS 150x150x6',
}


def k_truss_bridge(panels=16, bay=4.0, depth=8.0, load=60.0, rigid=False,
                   families=None):
    """The bridge as a model dict (nodes, rods, profiles, supports,
    loads), the shape truss_examples.get returns. `panels` must be even:
    the middle vertical is the one that is not split."""
    if panels < 2 or panels % 2:
        raise ValueError('panels must be an even number, 2 or more')
    n, c = panels, panels // 2
    nodes, M = [], {}
    B = list(range(n + 1))
    nodes += [(bay * i, 0.0) for i in range(n + 1)]
    T = list(range(n + 1, 2 * n + 2))
    nodes += [(bay * i, depth) for i in range(n + 1)]
    for i in range(n + 1):
        if i != c:
            M[i] = len(nodes)
            nodes.append((bay * i, depth / 2))
    rods = [(B[i], B[i + 1], 'Bottom chord') for i in range(n)]
    rods += [(T[i], T[i + 1], 'Top chord') for i in range(n)]
    for i in range(n + 1):
        if i == c:
            rods.append((B[i], T[i], 'Vertical'))
        else:
            fam = 'End post' if i in (0, n) else 'Vertical'
            rods += [(B[i], M[i], fam), (M[i], T[i], fam)]
    for i in range(n):
        if i < c:
            rods += [(M[i], T[i + 1], 'Diagonal'),
                     (M[i], B[i + 1], 'Diagonal')]
        else:
            rods += [(M[i + 1], T[i], 'Diagonal'),
                     (M[i + 1], B[i], 'Diagonal')]
    loads = [(B[i], 0.0, load) for i in range(1, n)]
    return tx._model(nodes, rods, families or K_BRIDGE_FAMILIES,
                     [(B[0], 'pin'), (B[n], 'rollerX')], loads,
                     conn='rigid' if rigid else 'pin')


def hand_checks(panels=16, bay=4.0, depth=8.0, load=60.0):
    """What the protocol checks the solver against, worked by hand.

    reaction     each support carries half of the (panels - 1) loads.
    chord        the biggest chord force is the bending moment at the
                 joint next to midspan over the depth, M / d. A section
                 cut through the panel beside the middle vertical passes
                 through one top chord, one bottom chord and the two K
                 diagonals, which meet on the vertical; moments about
                 that joint leave the chord alone.
    end post     the lower half of an end post carries the whole
                 reaction (its joint has only the post, the first bottom
                 chord, which is unloaded there, and the support).
    """
    total = (panels - 1) * load
    R = total / 2
    x = bay * (panels // 2 - 1)                 # the joint next to midspan
    # the reaction's moment, less each load to the left times its lever
    M = R * x - sum(load * (x - bay * k) for k in range(1, panels)
                    if bay * k < x)
    return {'reaction': R, 'chord': M / depth, 'end_post': R,
            'total_load': total}
