"""Rotate and mirror a selection (roadmap v2 3.4).

The arrow keys choose an axis -- left/right X, up/down Y, PgUp/PgDn Z -- as
they already did for extending a rod. With an axis active:

    R, type an angle, Enter   rotates the selection about that axis
    M                         mirrors it across the plane square to that axis
    Shift+M                   mirrors a COPY, which is how half a structure
                              is drawn and the other half made from it

Everything here is plain geometry on lists, so it is tested without a
window. The app decides WHICH nodes move (a locked group moves whole, or
not at all -- see stereo_groups.move_plan) and calls these to move them.

The pivot is the centroid of the nodes being moved: rotating a bay turns it
in place, and mirroring it flips it over its own middle, rather than
swinging it about the model's origin to somewhere off the drawing.
"""
import math

AXES = {'X': 0, 'Y': 1, 'Z': 2}

# Two nodes this close (metres) are the same joint. A mirrored copy lands
# exactly on its original wherever the original sits ON the mirror plane,
# and those must be one node, not two stacked ones that the solver would
# treat as a hinge nobody drew.
MERGE_TOL_M = 1e-6


def centroid(points):
    n = len(points)
    if not n:
        return (0.0, 0.0, 0.0)
    return tuple(sum(p[k] for p in points) / n for k in range(3))


def rotate_point(p, axis, angle_deg, pivot):
    """`p` turned by `angle_deg` about the line through `pivot` parallel to
    `axis`, right-handed (a positive angle about Z turns X towards Y)."""
    # The two coordinates that turn, in CYCLIC order -- (y, z) about X,
    # (z, x) about Y, (x, y) about Z -- which is what makes every axis
    # right-handed. Taking them in index order gets Y backwards.
    i, j = {'X': (1, 2), 'Y': (2, 0), 'Z': (0, 1)}[axis]
    t = math.radians(angle_deg)
    c, s = math.cos(t), math.sin(t)
    d = [p[a] - pivot[a] for a in range(3)]
    out = list(p)
    out[i] = pivot[i] + c * d[i] - s * d[j]
    out[j] = pivot[j] + s * d[i] + c * d[j]
    return tuple(out)


def mirror_point(p, axis, pivot):
    """`p` reflected across the plane through `pivot` square to `axis`."""
    k = AXES[axis]
    out = list(p)
    out[k] = 2.0 * pivot[k] - p[k]
    return tuple(out)


def rotated(nodes, ids, axis, angle_deg, pivot=None):
    """A new node list with `ids` rotated. Other nodes are untouched."""
    ids = sorted(set(ids))
    if pivot is None:
        pivot = centroid([nodes[i] for i in ids])
    out = list(nodes)
    for i in ids:
        out[i] = rotate_point(nodes[i], axis, angle_deg, pivot)
    return out


def mirrored(nodes, ids, axis, pivot=None):
    """A new node list with `ids` reflected in place."""
    ids = sorted(set(ids))
    if pivot is None:
        pivot = centroid([nodes[i] for i in ids])
    out = list(nodes)
    for i in ids:
        out[i] = mirror_point(nodes[i], axis, pivot)
    return out


def _find(nodes, p, tol):
    for i, q in enumerate(nodes):
        if (abs(q[0] - p[0]) <= tol and abs(q[1] - p[1]) <= tol
                and abs(q[2] - p[2]) <= tol):
            return i
    return None


def mirror_copy(nodes, members, ids, axis, pivot=None, member_ids=None,
                tol=MERGE_TOL_M):
    """Add a mirrored copy of nodes `ids` and the rods among them.

    Returns (nodes, members, node_map, new_member_ids): `node_map` sends each
    original node to its copy, which is an EXISTING node wherever the copy
    lands on one (a node on the mirror plane copies onto itself). The rods
    copied are those with both ends in `ids`, plus any in `member_ids`
    whose ends are both copied; a copy that would duplicate a rod already
    there, or join a node to itself, is skipped.
    """
    ids = sorted(set(ids))
    if pivot is None:
        pivot = centroid([nodes[i] for i in ids])
    out_nodes = list(nodes)
    node_map = {}
    for i in ids:
        q = mirror_point(nodes[i], axis, pivot)
        hit = _find(out_nodes, q, tol)
        if hit is None:
            out_nodes.append(q)
            hit = len(out_nodes) - 1
        node_map[i] = hit
    want = {j for j, m in enumerate(members)
            if m['a'] in node_map and m['b'] in node_map}
    for j in (member_ids or ()):
        if 0 <= j < len(members) and members[j]['a'] in node_map \
                and members[j]['b'] in node_map:
            want.add(j)
    out_members = list(members)
    have = {frozenset((m['a'], m['b'])) for m in members}
    new_ids = []
    for j in sorted(want):
        m = members[j]
        a, b = node_map[m['a']], node_map[m['b']]
        key = frozenset((a, b))
        if a == b or key in have:
            continue
        copy = dict(m, a=a, b=b)
        out_members.append(copy)
        have.add(key)
        new_ids.append(len(out_members) - 1)
    return out_nodes, out_members, node_map, new_ids
