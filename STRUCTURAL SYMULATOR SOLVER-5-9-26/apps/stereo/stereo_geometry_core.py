"""Shared internals every Stereo geometry generator is built on.

Deliberately tiny and dependency-free: the node bank that de-duplicates
coincident nodes, the member-adding helper that refuses zero-length and
duplicate members, and the chord-adding helper that lays a square- or
diagonal-pattern chord layer over an (i, j) grid of node ids.

Every stereo_geometry_* family module imports from here and from nothing
else in the package, so a new shape family never has to reach across into
another family's file to reuse the basic machinery.
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
