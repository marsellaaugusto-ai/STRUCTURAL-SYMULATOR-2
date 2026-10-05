"""Affine transforms: the one place a coordinate changes frame.

Clean-room note. Everything here is textbook homogeneous-coordinate linear
algebra -- 4x4 affine matrices, right-handed axes, Rodrigues' rotation
formula, inverse-transpose for normals. It was written from the mathematics,
not from any other program's code, and it borrows no product's UI or
proprietary algorithm.

WHY A MATRIX, when `stereo_transform.py` already rotates a selection by
mutating its coordinates. Because mutation cannot nest. A rod inside a
truss inside a bay inside a roof has FOUR frames stacked over it, and the
only composition rule that stays associative under nesting -- and
invertible, which is what lets a drag in world space become an edit in a
deeply nested local space -- is matrix multiplication. Mutating points
flattens that stack on the first edit and then the nesting is gone.

CONVENTIONS, all three of them, because mixing any two silently mirrors or
transposes a model:

  * COLUMN VECTORS. A point is a column, so `M @ p` applies M to p, and
    `A @ B` means "B first, then A". Composing down a hierarchy therefore
    reads `W_child = W_parent @ L_child`.
  * ROW-MAJOR STORAGE, 16 floats, `m[r * 4 + c]`. Storage order is not the
    maths; it is chosen only because it prints as it reads.
  * RIGHT-HANDED, with the cyclic axis pairs (Y,Z) about X, (Z,X) about Y,
    (X,Y) about Z. Taking the pairs in index order instead gets Y backwards
    -- the same trap `stereo_transform.rotate_point` documents, and the
    tests pin the two against each other so they can never drift apart.

Transforms are IMMUTABLE. Every operation returns a new one, so a cached
world matrix can never be mutated out from under the node that cached it.
"""
import math

# Below this, a scale factor is treated as a degenerate collapse rather than
# a very thin object: the inverse would be meaningless and a node dragged
# through it could not be mapped back to its local frame.
SINGULAR_EPS = 1e-12

# How far two floats may differ and still count as the same, for the
# is_rigid / handedness questions the instance policy asks. Loose enough to
# survive a few hundred composed rotations, tight enough that a real 0.1%
# scale is still reported as a scale.
NEAR_EPS = 1e-9

AXIS_PAIRS = {'X': (1, 2), 'Y': (2, 0), 'Z': (0, 1)}


class Transform:
    """A 4x4 affine transform. Immutable; compose with `@`."""

    __slots__ = ('m',)

    def __init__(self, m=None):
        if m is None:
            self.m = (1.0, 0.0, 0.0, 0.0,
                      0.0, 1.0, 0.0, 0.0,
                      0.0, 0.0, 1.0, 0.0,
                      0.0, 0.0, 0.0, 1.0)
            return
        m = tuple(float(x) for x in m)
        if len(m) != 16:
            raise ValueError('a transform is 16 floats, got %d' % len(m))
        # The bottom row is what makes this AFFINE rather than projective.
        # Nothing here can produce a perspective divide, and the inverse
        # below assumes it, so a hand-built matrix that breaks it is refused
        # at the door instead of giving wrong answers later.
        if m[12:] != (0.0, 0.0, 0.0, 1.0):
            raise ValueError('not an affine transform: bottom row is %r' % (m[12:],))
        self.m = m

    # ── constructors ───────────────────────────────────────────────────────

    @classmethod
    def identity(cls):
        return cls()

    @classmethod
    def translation(cls, dx, dy=None, dz=None):
        if dy is None and dz is None:
            dx, dy, dz = dx                      # a single (x, y, z)
        return cls((1.0, 0.0, 0.0, float(dx),
                    0.0, 1.0, 0.0, float(dy),
                    0.0, 0.0, 1.0, float(dz),
                    0.0, 0.0, 0.0, 1.0))

    @classmethod
    def rotation(cls, axis, angle_deg):
        """Right-handed turn about a world axis through the origin.

        `axis` is 'X', 'Y' or 'Z', or a 3-vector for any other line.
        """
        if not isinstance(axis, str):
            return cls.rotation_about_vector(axis, angle_deg)
        key = str(axis).upper()
        if key not in AXIS_PAIRS:
            raise ValueError('axis must be X, Y, Z or a vector, got %r' % (axis,))
        i, j = AXIS_PAIRS[key]
        t = math.radians(angle_deg)
        c, s = math.cos(t), math.sin(t)
        r = [[1.0 if a == b else 0.0 for b in range(3)] for a in range(3)]
        r[i][i], r[i][j] = c, -s
        r[j][i], r[j][j] = s, c
        return cls._from_linear(r)

    @classmethod
    def rotation_about_vector(cls, axis_vec, angle_deg):
        """Rodrigues' formula: a turn about any line through the origin."""
        x, y, z = (float(v) for v in axis_vec)
        n = math.sqrt(x * x + y * y + z * z)
        if n < SINGULAR_EPS:
            raise ValueError('cannot rotate about a zero-length axis')
        x, y, z = x / n, y / n, z / n
        t = math.radians(angle_deg)
        c, s = math.cos(t), math.sin(t)
        k = 1.0 - c
        return cls._from_linear([
            [c + x * x * k,     x * y * k - z * s, x * z * k + y * s],
            [y * x * k + z * s, c + y * y * k,     y * z * k - x * s],
            [z * x * k - y * s, z * y * k + x * s, c + z * z * k],
        ])

    @classmethod
    def scale(cls, sx, sy=None, sz=None):
        """Scale about the origin. One argument scales uniformly."""
        if sy is None and sz is None:
            if isinstance(sx, (tuple, list)):
                sx, sy, sz = sx
            else:
                sy = sz = sx
        return cls._from_linear([[float(sx), 0.0, 0.0],
                                 [0.0, float(sy), 0.0],
                                 [0.0, 0.0, float(sz)]])

    @classmethod
    def mirror(cls, axis):
        """Reflect across the plane square to `axis`, through the origin.

        This FLIPS HANDEDNESS (determinant -1), which is not a detail for a
        steel model: a mirrored angle or channel is a different part from the
        one it was mirrored from, and `handedness()` is how a caller finds
        out before it quietly ships a left-hand piece as a right-hand one.
        """
        key = str(axis).upper()
        if key not in AXIS_PAIRS:
            raise ValueError('axis must be X, Y or Z, got %r' % (axis,))
        k = {'X': 0, 'Y': 1, 'Z': 2}[key]
        s = [1.0, 1.0, 1.0]
        s[k] = -1.0
        return cls.scale(*s)

    @classmethod
    def about(cls, pivot, inner):
        """`inner`, but applied about `pivot` instead of about the origin.

        Rotating a bay turns it in place; without this it swings about the
        model origin to somewhere off the drawing. Same reasoning, and same
        default pivot (the selection's own centroid), as the existing
        `stereo_transform` keyboard operations.
        """
        to = cls.translation(pivot)
        back = cls.translation(-pivot[0], -pivot[1], -pivot[2])
        return to @ inner @ back

    @classmethod
    def from_frame(cls, origin, x_axis, y_axis, z_axis):
        """The transform taking local axes onto the given world frame.

        This is how a definition is placed by three vectors rather than by
        three angles -- the form that falls out of real geometry (a chord
        direction, the surface normal, their cross product) without anyone
        having to work out Euler angles for it.
        """
        cols = (x_axis, y_axis, z_axis)
        r = [[float(cols[c][a]) for c in range(3)] for a in range(3)]
        t = cls._from_linear(r)
        return cls.translation(origin) @ t

    @classmethod
    def _from_linear(cls, r):
        """A 3x3 linear part with no translation."""
        return cls((r[0][0], r[0][1], r[0][2], 0.0,
                    r[1][0], r[1][1], r[1][2], 0.0,
                    r[2][0], r[2][1], r[2][2], 0.0,
                    0.0, 0.0, 0.0, 1.0))

    # ── composition ────────────────────────────────────────────────────────

    def __matmul__(self, other):
        """`self @ other`: other applied FIRST, then self."""
        if not isinstance(other, Transform):
            return NotImplemented
        a, b = self.m, other.m
        out = [0.0] * 16
        for r in range(3):                       # row 3 is always (0,0,0,1)
            ar = r * 4
            for c in range(4):
                out[ar + c] = (a[ar + 0] * b[0 + c] +
                               a[ar + 1] * b[4 + c] +
                               a[ar + 2] * b[8 + c] +
                               a[ar + 3] * b[12 + c])
        out[12:] = [0.0, 0.0, 0.0, 1.0]
        return Transform(out)

    def inverse(self):
        """The transform undoing this one.

        Affine structure is exploited rather than running a general 4x4
        solve: with A the 3x3 linear part and t the translation, the inverse
        is A-inverse with -A-inverse*t. Fewer operations and, more to the
        point, it cannot invent a projective bottom row out of rounding.

        This is the method that makes a nested edit possible: a node dragged
        to a world point W inside a parent whose world matrix is P takes the
        local position `P.inverse() @ W`.
        """
        m = self.m
        a = ((m[0], m[1], m[2]), (m[4], m[5], m[6]), (m[8], m[9], m[10]))
        det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
               - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
               + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
        if abs(det) < SINGULAR_EPS:
            raise ValueError('transform is singular (determinant %g): it '
                             'collapses space and cannot be inverted' % det)
        inv = [[0.0] * 3 for _ in range(3)]
        for r in range(3):
            for c in range(3):
                r0, r1 = [k for k in range(3) if k != c]
                c0, c1 = [k for k in range(3) if k != r]
                minor = (a[r0][c0] * a[r1][c1] - a[r0][c1] * a[r1][c0])
                inv[r][c] = minor / det * (1.0 if (r + c) % 2 == 0 else -1.0)
        t = (m[3], m[7], m[11])
        it = [-sum(inv[r][c] * t[c] for c in range(3)) for r in range(3)]
        return Transform((inv[0][0], inv[0][1], inv[0][2], it[0],
                          inv[1][0], inv[1][1], inv[1][2], it[1],
                          inv[2][0], inv[2][1], inv[2][2], it[2],
                          0.0, 0.0, 0.0, 1.0))

    # ── applying it ────────────────────────────────────────────────────────

    def apply_point(self, p):
        """A POSITION: the translation applies."""
        m, x, y, z = self.m, float(p[0]), float(p[1]), float(p[2])
        return (m[0] * x + m[1] * y + m[2] * z + m[3],
                m[4] * x + m[5] * y + m[6] * z + m[7],
                m[8] * x + m[9] * y + m[10] * z + m[11])

    def apply_direction(self, v):
        """A DIRECTION (a rod's axis, a span vector): translation is dropped.

        Transforming a direction as if it were a point is the classic bug
        here: the direction comes back displaced by the translation, so a
        member's local axis -- and with it the orientation of its section --
        points somewhere else entirely in a nested group.
        """
        m, x, y, z = self.m, float(v[0]), float(v[1]), float(v[2])
        return (m[0] * x + m[1] * y + m[2] * z,
                m[4] * x + m[5] * y + m[6] * z,
                m[8] * x + m[9] * y + m[10] * z)

    def apply_normal(self, n):
        """A NORMAL (a plate's face, a panel's wind face): inverse-transpose.

        A normal is not a direction. Under a non-uniform scale a direction
        follows the matrix but a normal must follow the inverse-transpose,
        or it stops being square to the surface it describes -- and the
        pressure a wind panel picks up is then computed on a face pointing
        the wrong way.
        """
        inv = self.inverse().m
        x, y, z = float(n[0]), float(n[1]), float(n[2])
        return (inv[0] * x + inv[4] * y + inv[8] * z,
                inv[1] * x + inv[5] * y + inv[9] * z,
                inv[2] * x + inv[6] * y + inv[10] * z)

    # ── asking what it is ──────────────────────────────────────────────────

    @property
    def translation_part(self):
        return (self.m[3], self.m[7], self.m[11])

    @property
    def linear_part(self):
        m = self.m
        return ((m[0], m[1], m[2]), (m[4], m[5], m[6]), (m[8], m[9], m[10]))

    def determinant(self):
        a = self.linear_part
        return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
                - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
                + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))

    def handedness(self):
        """+1 keeps handedness, -1 mirrors it. See `mirror`."""
        return -1 if self.determinant() < 0.0 else 1

    def scale_factors(self):
        """The length each local axis comes out as, always positive.

        This is a POLAR-style read of the matrix and it does not see shear:
        a sheared matrix reports the column lengths, which are then not the
        whole story. Shear cannot be built by any constructor here, and the
        instance policy refuses a free matrix unless a caller insists, so
        the gap is narrow -- but it is a gap, not a rounding error, and
        naming it is cheaper than someone rediscovering it.
        """
        a = self.linear_part
        return tuple(math.sqrt(sum(a[r][c] ** 2 for r in range(3)))
                     for c in range(3))

    def is_rigid(self, eps=NEAR_EPS):
        """True when this only rotates, mirrors and moves: no stretch.

        The test that matters for a structural model. A rigid placement
        leaves every member length and every section property intact, so a
        definition placed rigidly is the SAME fabricated part in every copy.
        Anything else is a different part wearing the same name.
        """
        a = self.linear_part
        for i in range(3):
            for j in range(3):
                dot = sum(a[k][i] * a[k][j] for k in range(3))
                if abs(dot - (1.0 if i == j else 0.0)) > eps:
                    return False
        return True

    def is_uniform_scale(self, eps=NEAR_EPS):
        """Rigid, or rigid times one single factor on all three axes."""
        sx, sy, sz = self.scale_factors()
        if sx < SINGULAR_EPS:
            return False
        if abs(sy - sx) > eps * max(1.0, sx) or abs(sz - sx) > eps * max(1.0, sx):
            return False
        return (self @ Transform.scale(1.0 / sx)).is_rigid(eps)

    def is_identity(self, eps=NEAR_EPS):
        ident = Transform().m
        return all(abs(x - y) <= eps for x, y in zip(self.m, ident))

    # ── housekeeping ───────────────────────────────────────────────────────

    def __eq__(self, other):
        return isinstance(other, Transform) and self.m == other.m

    def __hash__(self):
        return hash(self.m)

    def approx_equal(self, other, eps=NEAR_EPS):
        return all(abs(x - y) <= eps for x, y in zip(self.m, other.m))

    def __repr__(self):
        if self.is_identity():
            return 'Transform.identity()'
        t = self.translation_part
        s = self.scale_factors()
        return ('Transform(t=(%.4g, %.4g, %.4g), scale=(%.4g, %.4g, %.4g), '
                'hand=%+d)' % (t + s + (self.handedness(),)))

    def as_rows(self):
        """The 4x4 as four tuples -- for saving, and for readable failures."""
        m = self.m
        return tuple(tuple(m[r * 4 + c] for c in range(4)) for r in range(4))


IDENTITY = Transform()
