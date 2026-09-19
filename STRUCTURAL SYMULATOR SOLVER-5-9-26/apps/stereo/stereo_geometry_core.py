"""Shared internals every Stereo geometry generator is built on.

Deliberately tiny and dependency-free: the node bank that de-duplicates
coincident nodes, the member-adding helper that refuses zero-length and
duplicate members, and the chord-adding helper that lays a square- or
diagonal-pattern chord layer over an (i, j) grid of node ids.

Every stereo_geometry_* family module imports from here and from nothing
else in the package, so a new shape family never has to reach across into
another family's file to reuse the basic machinery. That is also why the
plan-shape mask below takes an already-compiled keep_fn rather than an
expression: compiling one needs expr_math, and this file stays clean.
"""


ROUND = 9   # coordinate rounding (m) so coincident nodes from independent
            # construction paths (e.g. a grid line and a diagonal sharing an
            # intended corner) compare equal in dict-based de-duplication.


def _key(x, y, z):
    return (round(x, ROUND), round(y, ROUND), round(z, ROUND))


class _NodeBank:
    """De-duplicates nodes by coordinate while building a generator, so two
    construction paths that land on the same physical point (e.g. a top-
    chord grid line and a diagonal web) share one node instead of silently
    creating an unconnected duplicate sitting on top of it -- the single
    most common way a hand-built mesh becomes a mechanism."""

    def __init__(self):
        self.nodes = []
        self._index = {}

    def add(self, x, y, z):
        k = _key(x, y, z)
        i = self._index.get(k)
        if i is None:
            i = len(self.nodes)
            self.nodes.append((x, y, z))
            self._index[k] = i
        return i


def _add_chords(members, seen, grid, imax, jmax, role, pattern):
    """Add chord members across a rectangular (i, j) index grid (0..imax,
    0..jmax), either along the grid lines ('square': parallel to the plan
    boundary -- Makowski's "square-on-square" family) or along the grid's
    own diagonals ('diagonal': 45 degrees to the boundary -- the
    "diagonal-on-diagonal" family). 'diagonal' reuses the EXACT SAME node
    positions 'square' does -- only which already-placed nodes get
    connected changes -- so it carries none of the clipping/re-placement
    risk a genuinely rotated node layout would."""
    if pattern == 'square':
        for j in range(jmax + 1):
            for i in range(imax):
                _add_member(members, seen, grid[(i, j)], grid[(i + 1, j)], role=role)
        for j in range(jmax):
            for i in range(imax + 1):
                _add_member(members, seen, grid[(i, j)], grid[(i, j + 1)], role=role)
    elif pattern == 'diagonal':
        for j in range(jmax):
            for i in range(imax):
                _add_member(members, seen, grid[(i, j)], grid[(i + 1, j + 1)], role=role)
                _add_member(members, seen, grid[(i + 1, j)], grid[(i, j + 1)], role=role)
    else:
        raise ValueError(f"pattern must be 'square' or 'diagonal', got {pattern!r}")


def _add_member(members, seen, a, b, **props):
    """Skip a zero-length or exactly-duplicate member instead of letting it
    silently double a stiffness contribution or divide by zero in the
    solver."""
    if a == b:
        return
    key = (min(a, b), max(a, b))
    if key in seen:
        return
    seen.add(key)
    m = {'a': a, 'b': b, 'conn': 'pin'}
    m.update(props)
    members.append(m)


# ═══════════════════════════════════════════════════════════════════════════
#  Plan-shape domain mask
# ═══════════════════════════════════════════════════════════════════════════
def apply_domain_mask(mesh, keep_fn):
    """Cut a generated mesh down to the part of the plan `keep_fn(x, y)`
    accepts, returning a NEW mesh dict with nodes re-indexed.

    What survives, and why:

    * A node survives if its own plan position passes the rule.
    * A node ALSO survives if a web ties it to a surviving node. In a
      double-layer lattice the bottom nodes sit at the cell centres and
      each is webbed to its four top corners, so this is exactly the old
      "judge a module at its centre, then keep the corners it needs"
      rule -- without needing the (i, j) indices, which an arbitrary mesh
      does not have. It is what stops the cut edge from shedding the top
      chord a surviving web still hangs from.
    * A member survives if BOTH its ends do. The chords bounding the hole
      are therefore kept, which frames the opening instead of leaving a
      ragged edge of half-connected nodes.
    * A node left with no members at all is dropped. It would be a
      free-floating point mass and the solver would call the model a
      mechanism.

    Supports are re-derived, not just remapped: a cut creates a NEW free
    edge, and the nodes on it are exactly the surviving nodes that lost a
    neighbour to the cut. Those join whichever original support candidates
    survived, because an edge the rule did not touch is still an edge.

    `load_nodes` (tributary areas) are remapped but NOT recomputed. A node
    on the cut edge keeps the area it had when it was interior, so it is
    loaded as if the removed cells were still there: an over-estimate at
    the rim, which is the safe direction to be wrong in. Recomputing true
    tributary areas for an arbitrary cut is a different problem from
    cutting the mesh, and quietly halving the edge loads would be worse
    than stating this.

    Raises ValueError when the rule leaves nothing -- an empty model is
    never what anyone meant by a plan shape.
    """
    if keep_fn is None:
        return mesh
    nodes = mesh['nodes']
    members = mesh['members']

    passes = set()
    for i, (x, y, _z) in enumerate(nodes):
        if keep_fn(x, y):
            passes.add(i)

    keep = set(passes)
    for m in members:
        if str(m.get('role', '')).startswith('web'):
            if m['a'] in passes or m['b'] in passes:
                keep.add(m['a'])
                keep.add(m['b'])

    kept_members = [m for m in members if m['a'] in keep and m['b'] in keep]
    used = set()
    for m in kept_members:
        used.add(m['a'])
        used.add(m['b'])
    keep &= used
    if not keep:
        raise ValueError('The plan rule removed the whole structure -- nothing '
                         'satisfies it inside this domain. Check the expression, '
                         'and remember x and y are in metres.')

    # The cut edge: a surviving node that lost at least one member to it.
    on_cut = set()
    for m in members:
        if (m['a'] in keep) != (m['b'] in keep):
            on_cut.add(m['a'] if m['a'] in keep else m['b'])

    order = sorted(keep)
    remap = {old: new for new, old in enumerate(order)}
    old_candidates = set(mesh.get('support_candidates', ()))
    candidates = sorted(remap[i] for i in order
                        if i in on_cut or i in old_candidates)

    load_nodes = {remap[i]: a for i, a in (mesh.get('load_nodes') or {}).items()
                  if i in remap}

    out = dict(mesh)
    out['nodes'] = [nodes[i] for i in order]
    out['members'] = [dict(m, a=remap[m['a']], b=remap[m['b']]) for m in kept_members]
    out['support_candidates'] = candidates
    out['load_nodes'] = load_nodes
    return out
