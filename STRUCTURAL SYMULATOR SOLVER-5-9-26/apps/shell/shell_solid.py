"""shell_solid.py -- the shell as the solid it is, for drawing only.

The finite elements live on the mid-surface, which is correct and is why
the tab has always drawn a sheet. But the mid-surface is a bad thing to
LOOK at: the thickness is the number a shell design turns on, the tab
knows it for every element, and none of it reaches the picture. This
module offsets that surface by +/- t/2 along its own normal and returns
the faces of the resulting slab -- a top, a soffit and a band around every
free edge.

It computes geometry and nothing else. No Tk, no colour, no camera: the
caller projects, sorts and paints. That keeps it testable against numbers
(a flat plate's solid has exactly the volume area * t) rather than against
a screenshot.

WHAT IT DOES NOT DO, deliberately:

  * It does not change the analysis. These points are never handed to the
    solver; the elements stay where they were. A drawing that moved the
    model would be worse than a drawing that omits the thickness.
  * It does not mitre the corners. Two faces meeting at a ridge are each
    offset along their own normal, so on a sharply creased surface the
    solid opens a wedge at the crease of the order of t * (the angle).
    Mitring would mean solving for the intersection of the offset planes,
    which is real work for a picture; a shell is smooth almost everywhere
    and the wedge is invisible where it is.
  * It does not hide self-intersection. Offsetting inwards by more than
    the radius of curvature turns the soffit inside out. That is the
    geometry telling the truth -- such a shell cannot be built -- so
    `inward_limit` reports it rather than papering over it.

ON THE EXAGGERATION FACTOR. A 10 cm shell on a 12 m span is 0.8% of the
span; at any honest zoom it is a hairline, which is exactly why the sheet
was never obviously wrong. So the caller may scale the offset. That is a
lie about the model, and the rule here is that a lie must be labelled: the
factor is returned with the faces so the canvas can print it whenever it
is not 1.
"""
import numpy as np

# Faces come back tagged so the caller can colour and cull them by role.
TOP, BOTTOM, SIDE = 'top', 'bottom', 'side'


def element_normals(X, elems):
    """Unit normal per quad, from the diagonals.

    The diagonal cross product, not two edges: it is the same for a planar
    quad and is the least wrong of the cheap choices for a warped one,
    because it uses all four corners instead of three.
    """
    X = np.asarray(X, float)
    el = np.asarray(elems, int)
    d1 = X[el[:, 2]] - X[el[:, 0]]
    d2 = X[el[:, 3]] - X[el[:, 1]]
    n = np.cross(d1, d2)
    L = np.linalg.norm(n, axis=1, keepdims=True)
    return n / np.where(L < 1e-30, 1.0, L)


def element_areas(X, elems):
    """Quad area, as the two triangles of one diagonal."""
    X = np.asarray(X, float)
    el = np.asarray(elems, int)
    a = np.cross(X[el[:, 1]] - X[el[:, 0]], X[el[:, 3]] - X[el[:, 0]])
    b = np.cross(X[el[:, 3]] - X[el[:, 2]], X[el[:, 1]] - X[el[:, 2]])
    return 0.5 * (np.linalg.norm(a, axis=1) + np.linalg.norm(b, axis=1))


def node_normals(X, elems):
    """Area-weighted mean of the incident element normals, per node.

    Area-weighted because an unweighted mean lets a row of slivers at a cut
    edge outvote the large elements that actually define the surface there.
    A node with no element (there should be none) keeps +z rather than a
    zero vector, so nothing downstream divides by zero.
    """
    X = np.asarray(X, float)
    el = np.asarray(elems, int)
    ne = element_normals(X, el)
    w = element_areas(X, el)
    acc = np.zeros_like(X)
    for k in range(el.shape[1]):
        np.add.at(acc, el[:, k], ne * w[:, None])
    L = np.linalg.norm(acc, axis=1, keepdims=True)
    out = np.where(L < 1e-30, np.array([0.0, 0.0, 1.0]), acc / np.where(L < 1e-30, 1.0, L))
    return out


def node_thickness(X, elems, t_elem):
    """Element thickness carried to the nodes, area-weighted.

    The solid has to be continuous, and the thickness is a per-element
    number, so the two have to be reconciled somewhere. Doing it at the
    nodes means a step in t between neighbouring elements is drawn as the
    ramp it is built as, rather than as a cliff -- which is also what the
    automatic thickening's taper actually produces.
    """
    X = np.asarray(X, float)
    el = np.asarray(elems, int)
    t = np.asarray(t_elem, float)
    w = element_areas(X, el)
    num = np.zeros(len(X))
    den = np.zeros(len(X))
    for k in range(el.shape[1]):
        np.add.at(num, el[:, k], t * w)
        np.add.at(den, el[:, k], w)
    return np.where(den > 0, num / np.where(den > 0, den, 1.0), float(np.mean(t)) if len(t) else 0.0)


def boundary_edges(elems):
    """The edges that belong to exactly one element, in that element's own
    winding order.

    Found by counting, not by assuming a rectangle: the plan may be cut to
    a rule later, and then the free edge includes the boundary of every
    hole. Returned as (a, b, element) so the caller can keep the outward
    orientation the parent element implies.
    """
    el = np.asarray(elems, int)
    seen = {}
    order = []
    for e in range(len(el)):
        for k in range(el.shape[1]):
            a = int(el[e, k])
            b = int(el[e, (k + 1) % el.shape[1]])
            key = (a, b) if a < b else (b, a)
            if key in seen:
                seen[key] = None                  # shared: not a boundary
            else:
                seen[key] = (a, b, e)
                order.append(key)
    return [seen[k] for k in order if seen[k] is not None]


def inward_limit(X, elems, t_elem):
    """How far the soffit may be offset before the solid turns inside out.

    Returns the smallest (radius of curvature) along the mesh, estimated
    from how fast the node normals turn between neighbouring nodes of an
    element, and the largest half-thickness asked for. When the second
    exceeds the first the drawing is not wrong -- the shell is: a slab
    thicker than twice its own radius of curvature cannot be built, and
    saying so is more use than quietly clipping it.
    """
    X = np.asarray(X, float)
    el = np.asarray(elems, int)
    nn = node_normals(X, el)
    worst = np.inf
    for k in range(el.shape[1]):
        a = el[:, k]
        b = el[:, (k + 1) % el.shape[1]]
        ds = np.linalg.norm(X[b] - X[a], axis=1)
        dn = np.linalg.norm(nn[b] - nn[a], axis=1)
        live = dn > 1e-12
        if live.any():
            worst = min(worst, float(np.min(ds[live] / dn[live])))
    return worst, float(np.max(np.asarray(t_elem, float)) / 2.0) if len(t_elem) else 0.0


def offset_surfaces(X, elems, t_elem, exaggeration=1.0):
    """The two offset node grids, (top, bottom), each (n, 3)."""
    X = np.asarray(X, float)
    nn = node_normals(X, elems)
    half = 0.5 * float(exaggeration) * node_thickness(X, elems, t_elem)[:, None]
    return X + nn * half, X - nn * half


def solid_faces(X, elems, t_elem, exaggeration=1.0):
    """Every face of the slab, ready to project.

    Returns a dict:
        'poly'    (f, 4, 3) float -- the corners of each face, in world metres
        'elem'    (f,)      int   -- which element each face belongs to, so a
                                     field colour and a picking tag carry over
        'role'    (f,)      object-- TOP / BOTTOM / SIDE
        'normal'  (f, 3)    float -- outward unit normal, for lighting and for
                                     culling the faces that point away
        'exaggeration'            -- echoed back so the caller can label it

    The winding of every face is set so its normal points OUT of the solid:
    the top keeps the element's own winding, the soffit is reversed, and a
    side face is built from the boundary edge in its parent element's order
    and so runs the same way round the slab.
    """
    X = np.asarray(X, float)
    el = np.asarray(elems, int)
    top, bot = offset_surfaces(X, el, t_elem, exaggeration)
    ne = element_normals(X, el)

    polys = [top[el], bot[el][:, ::-1]]
    owner = [np.arange(len(el)), np.arange(len(el))]
    roles = [np.full(len(el), TOP, object), np.full(len(el), BOTTOM, object)]
    normals = [ne, -ne]

    edges = boundary_edges(el)
    if edges:
        a = np.array([e[0] for e in edges], int)
        b = np.array([e[1] for e in edges], int)
        own = np.array([e[2] for e in edges], int)
        # a -> b along the top, back along the soffit: a loop that keeps the
        # element's winding, so the face's normal points away from the shell
        side = np.stack([top[a], top[b], bot[b], bot[a]], axis=1)
        d1 = side[:, 2] - side[:, 0]
        d2 = side[:, 3] - side[:, 1]
        sn = np.cross(d1, d2)
        L = np.linalg.norm(sn, axis=1, keepdims=True)
        sn = sn / np.where(L < 1e-30, 1.0, L)
        # point it away from the element's centroid, whatever the winding gave
        cen = X[el[own]].mean(axis=1)
        out = side.mean(axis=1) - cen
        flip = np.sum(sn * out, axis=1) < 0
        sn[flip] *= -1.0
        polys.append(side)
        owner.append(own)
        roles.append(np.full(len(edges), SIDE, object))
        normals.append(sn)

    return {'poly': np.concatenate(polys, axis=0),
            'elem': np.concatenate(owner),
            'role': np.concatenate(roles),
            'normal': np.concatenate(normals, axis=0),
            'exaggeration': float(exaggeration)}


def solid_volume(X, elems, t_elem):
    """Area x thickness, element by element -- the concrete in the shell.

    Not a property of the faces above (which are a drawing) but of the same
    numbers, and the one figure that makes two thickness designs comparable.
    """
    return float(np.sum(element_areas(X, elems) * np.asarray(t_elem, float)))


# ═══════════════════════════════════════════════════════════════════════════
#  Sections
# ═══════════════════════════════════════════════════════════════════════════
# A section through a shell is a vertical plane, and the thing you want to
# see in it is the slab: top fibre, soffit, and how the thickness changes
# along the cut. The tab could already plot a RESULT along a line; this is
# the other half, the one that makes automatic thickening legible.

def section_profile(X, elems, t_elem, ids, axis, index, exaggeration=1.0):
    """The slab's profile along one strip of elements.

    `ids` is the (ny+1, nx+1) grid of node numbers the mesh was built from.
    `axis` is the axis the cut line is CONSTANT along -- 'x' means the line
    x = pos, which runs in y -- and `index` is the element column (for 'x')
    or row (for 'y') the line falls in, matching how the tab already picks
    the strip for its result plots.

    The profile runs down the MIDDLE of that strip rather than along one of
    its node lines: a cut at x = pos means the plane through the strip, and
    taking one edge of it would offset the drawing by half an element and
    quietly disagree with the values plotted from the same cut.

    Returns a dict of arrays over n stations (one per node row across the
    strip), in metres:

        's'      the in-plane coordinate along the cut -- y for an 'x' cut
        'z'      the mid-surface
        's_top', 'z_top', 's_bot', 'z_bot'
                 the two faces. The offset follows the surface normal, so on
                 a steep shell it moves ALONG the section as well as up: a
                 profile drawn as two copies of 'z' shifted by t/2 would be
                 wrong by exactly the slope, which is largest where the shell
                 is most interesting.
        't'      the thickness at each station
        'elems'  (n-1,) the element behind each span, so the cut face can be
                 coloured by the same field the model is
    """
    X = np.asarray(X, float)
    el = np.asarray(elems, int)
    ids = np.asarray(ids, int)
    k = float(exaggeration)
    if axis == 'x':
        a, b = ids[:, index], ids[:, index + 1]
        nx = ids.shape[1] - 1
        strip = np.arange(ids.shape[0] - 1) * nx + index
        coord = 1                                   # the cut runs in y
    else:
        a, b = ids[index, :], ids[index + 1, :]
        nx = ids.shape[1] - 1
        strip = index * nx + np.arange(nx)
        coord = 0                                   # the cut runs in x

    nn = node_normals(X, el)
    tn = node_thickness(X, el, t_elem)
    mid = 0.5 * (X[a] + X[b])
    nrm = 0.5 * (nn[a] + nn[b])
    L = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = nrm / np.where(L < 1e-30, 1.0, L)
    t = 0.5 * (tn[a] + tn[b])
    half = (0.5 * k * t)[:, None]
    top = mid + nrm * half
    bot = mid - nrm * half
    return {'s': mid[:, coord], 'z': mid[:, 2],
            's_top': top[:, coord], 'z_top': top[:, 2],
            's_bot': bot[:, coord], 'z_bot': bot[:, 2],
            't': t, 'elems': strip, 'axis': axis, 'index': int(index),
            'exaggeration': k}


def strip_index(xs, ys, axis, pos):
    """Which element column ('x') or row ('y') the line falls in.

    The same clamp the tab already uses for its result plots, kept here so
    the drawing and the numbers can never pick different strips.
    """
    grid = np.asarray(xs if axis == 'x' else ys, float)
    return int(np.clip(np.searchsorted(grid, pos) - 1, 0, len(grid) - 2))
