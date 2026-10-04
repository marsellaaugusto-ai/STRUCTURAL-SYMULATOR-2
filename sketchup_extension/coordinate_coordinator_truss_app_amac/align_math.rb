# align_math.rb
#
# The rigid-body math behind "Align by Points" (align_tool.rb).
#
# Everything here is deliberately plain Ruby arithmetic on [x, y, z]
# arrays -- no Geom:: calls inside the solvers -- for two reasons:
#   1. it is unit-testable outside SketchUp (tools/test_align_math.rb runs
#      it in stock Ruby), and
#   2. it keeps the one place that touches the API (to_transformation) small
#      enough to read at a glance.
#
# ---------------------------------------------------------------------------
# Frame construction (the 3-pair case)
# ---------------------------------------------------------------------------
# A triplet of non-collinear points P1, P2, P3 defines exactly one
# right-handed orthonormal frame:
#
#   origin = P1
#   X      = (P2 - P1).normalize                  # first picked direction
#   N      = ((P2 - P1) x (P3 - P1)).normalize    # plane normal
#   Y      = N x X                                # completes the triad
#
# X, Y, N are mutually perpendicular unit vectors (X and N are perpendicular
# by construction of the cross product, and Y = N x X is perpendicular to
# both), so the matrix whose COLUMNS are X, Y, N is a pure rotation:
# orthonormal with determinant +1. No scale, no shear, no mirror -- which is
# exactly the guarantee the feature needs.
#
# Writing frame F as the pair (R_F, origin_F), the map "local coords ->
# model coords" is p_model = R_F * p_local + origin_F. So the transformation
# that carries frame A onto frame B is
#
#   T = Frame_B * Frame_A.inverse
#     => R = R_B * R_A^T          (R_A^-1 == R_A^T for a rotation)
#        t = B1 - R * A1          (so A1 lands exactly on B1)
#
# Consequences, all of them intended:
#   * A1 -> B1 exactly.
#   * A1->A2 becomes parallel to B1->B2, so A2 lands somewhere on the ray
#     B1->B2 -- at distance |A1A2|, not necessarily on B2, because the two
#     distances need not match and nothing is scaled.
#   * The A1-A2-A3 plane becomes the B1-B2-B3 plane, with A3 on B3's side
#     (both frames put their third point at +Y, by construction of Y).
#
# "Flip normal" is applied to the TARGET frame as a 180 degrees rotation
# about its own X axis: Y_B -> -Y_B, N_B -> -N_B, X_B unchanged. Negating
# two columns leaves the determinant at +1, so the result is still a proper
# rotation -- it is a half turn, never a mirror. (Negating N alone would
# flip the determinant to -1 and mirror the geometry.)
#
# ---------------------------------------------------------------------------
# The reduced modes
# ---------------------------------------------------------------------------
# 1 pair -- pure translation by B1 - A1. No rotation at all, because one
#   point pair carries no orientation information.
#
# 2 pairs -- translation plus the MINIMUM rotation about B1 that takes the
#   direction u = (A2-A1).normalize to v = (B2-B1).normalize. The minimum
#   rotation is the one whose axis is perpendicular to both directions,
#   axis = (u x v).normalize, by the angle acos(u . v) (Rodrigues' formula
#   below). Degenerate cases:
#     u . v ~ +1  -> already aligned, rotation = identity;
#     u . v ~ -1  -> antiparallel, any axis perpendicular to u gives a valid
#                    180 degrees turn, so one is built explicitly.
#   There is no roll control with 2 pairs: rotation about the u/v direction
#   itself is left wherever the source happened to be.
module CoordinateCoordinatorTrussAppAMAC
  module AlignMath
    # Cross-product length below which a point triplet counts as collinear,
    # in model units (inches) squared -- |AB x AC| is an area, so a triplet
    # spanning less than this has no usable plane.
    COLLINEAR_CROSS_TOL = 1e-6
    # Second collinearity guard, scale-free: the angle at P1 between P1->P2
    # and P1->P3. Catches long, very thin triplets whose cross product is
    # numerically large but whose plane is still junk.
    MIN_ANGLE_DEG = 0.1
    # Two picked points closer than this are the same point (inches).
    COINCIDENT_TOL = 1e-6
    # Identity test for the final transformation: max rotation-matrix
    # deviation, and translation length (inches).
    IDENTITY_ROT_TOL = 1e-9
    IDENTITY_TRANS_TOL = 1e-9

    module_function

    # --- small vector helpers (plain 3-element arrays) ---------------------

    def vsub(a, b)
      [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
    end

    def vadd(a, b)
      [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
    end

    def vscale(a, s)
      [a[0] * s, a[1] * s, a[2] * s]
    end

    def vdot(a, b)
      a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    end

    def vcross(a, b)
      [a[1] * b[2] - a[2] * b[1],
       a[2] * b[0] - a[0] * b[2],
       a[0] * b[1] - a[1] * b[0]]
    end

    def vlength(a)
      Math.sqrt(vdot(a, a))
    end

    # nil (rather than a raise) for a zero-length vector: callers treat that
    # as "degenerate pick" and report it to the user.
    def vnormalize(a)
      len = vlength(a)
      return nil if len < COINCIDENT_TOL

      [a[0] / len, a[1] / len, a[2] / len]
    end

    def coincident?(a, b)
      vlength(vsub(a, b)) < COINCIDENT_TOL
    end

    # --- collinearity -----------------------------------------------------

    # True when P1, P2, P3 cannot define a plane: any two of them coincide,
    # the cross product is shorter than COLLINEAR_CROSS_TOL, or the angle at
    # P1 is under MIN_ANGLE_DEG.
    def collinear?(p1, p2, p3)
      d12 = vsub(p2, p1)
      d13 = vsub(p3, p1)
      l12 = vlength(d12)
      l13 = vlength(d13)
      return true if l12 < COINCIDENT_TOL || l13 < COINCIDENT_TOL
      return true if coincident?(p2, p3)

      cross_len = vlength(vcross(d12, d13))
      return true if cross_len < COLLINEAR_CROSS_TOL

      # sin(angle) = |AB x AC| / (|AB| |AC|); compare against the tolerance
      # angle directly so the test does not depend on the model's scale.
      sin_angle = cross_len / (l12 * l13)
      sin_angle = 1.0 if sin_angle > 1.0
      Math.asin(sin_angle) * 180.0 / Math::PI < MIN_ANGLE_DEG
    end

    # --- frames -----------------------------------------------------------

    # Orthonormal frame of a point triplet: { origin:, x:, y:, n: }.
    # Returns nil when the triplet is collinear (caller rejects the pick).
    #
    # flip == true applies the 180 degrees half turn about the frame's own X
    # axis described in the file header (Y -> -Y, N -> -N), which is what
    # turns a face-to-face landing into a face-to-back one while keeping the
    # frame a proper rotation.
    def frame(p1, p2, p3, flip = false)
      return nil if collinear?(p1, p2, p3)

      x = vnormalize(vsub(p2, p1))
      n = vnormalize(vcross(vsub(p2, p1), vsub(p3, p1)))
      return nil if x.nil? || n.nil?

      y = vnormalize(vcross(n, x))
      return nil if y.nil?

      if flip
        y = vscale(y, -1.0)
        n = vscale(n, -1.0)
      end
      { origin: p1, x: x, y: y, n: n }
    end

    # --- rotation matrices ------------------------------------------------
    #
    # Rotations are 3x3 matrices stored row-major as [[r00, r01, r02], ...],
    # so m[row][col] and mat_mul_vec(m, v) read the obvious way. They are
    # converted to SketchUp's column-major 16-element layout only once, in
    # to_transformation.

    def identity_rotation
      [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    end

    def mat_mul_vec(m, v)
      [vdot(m[0], v), vdot(m[1], v), vdot(m[2], v)]
    end

    def mat_mul(a, b)
      (0..2).map do |i|
        (0..2).map do |j|
          a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j]
        end
      end
    end

    def mat_transpose(m)
      (0..2).map { |i| (0..2).map { |j| m[j][i] } }
    end

    # Rotation whose COLUMNS are the given axes -- i.e. the matrix that maps
    # (1,0,0) to x, (0,1,0) to y, (0,0,1) to n. That is the "local -> model"
    # rotation of the frame built from those axes.
    def rotation_from_axes(x, y, n)
      [[x[0], y[0], n[0]],
       [x[1], y[1], n[1]],
       [x[2], y[2], n[2]]]
    end

    # Rodrigues' rotation formula: rotation by `angle` radians about the unit
    # vector `axis`. R = I + sin(a) K + (1 - cos(a)) K^2, with K the
    # cross-product matrix of the axis.
    def rotation_axis_angle(axis, angle)
      u = vnormalize(axis)
      return identity_rotation if u.nil?

      ux, uy, uz = u
      c = Math.cos(angle)
      s = Math.sin(angle)
      t = 1.0 - c
      [[t * ux * ux + c,       t * ux * uy - s * uz, t * ux * uz + s * uy],
       [t * ux * uy + s * uz,  t * uy * uy + c,      t * uy * uz - s * ux],
       [t * ux * uz - s * uy,  t * uy * uz + s * ux, t * uz * uz + c]]
    end

    # Minimum rotation taking unit vector u onto unit vector v (see the
    # 2-pair notes in the file header).
    def rotation_between(u, v)
      un = vnormalize(u)
      vn = vnormalize(v)
      return identity_rotation if un.nil? || vn.nil?

      dot = vdot(un, vn)
      dot = 1.0 if dot > 1.0
      dot = -1.0 if dot < -1.0
      return identity_rotation if dot > 1.0 - 1e-12

      if dot < -1.0 + 1e-12
        # Antiparallel: a half turn about ANY axis perpendicular to u works.
        # Cross u with whichever world axis it is least aligned with, so the
        # cross product is never degenerate.
        helper = un[0].abs < 0.9 ? [1.0, 0.0, 0.0] : [0.0, 1.0, 0.0]
        return rotation_axis_angle(vcross(un, helper), Math::PI)
      end

      rotation_axis_angle(vcross(un, vn), Math.acos(dot))
    end

    # --- the three alignment modes ----------------------------------------
    #
    # All three return { rot: 3x3 row-major rotation, trans: [x, y, z] },
    # meaning p' = rot * p + trans, or nil when the picks are unusable.

    # 1 pair: translation only.
    def solve_1(a1, b1)
      { rot: identity_rotation, trans: vsub(b1, a1) }
    end

    # 2 pairs: A1 -> B1, plus the minimum rotation about B1 aligning
    # A1->A2 with B1->B2.
    def solve_2(a1, a2, b1, b2)
      u = vsub(a2, a1)
      v = vsub(b2, b1)
      return nil if vlength(u) < COINCIDENT_TOL || vlength(v) < COINCIDENT_TOL

      rot = rotation_between(u, v)
      # Rotate about B1 rather than the origin: translate A1 to B1 first,
      # then spin around that fixed point -> t = B1 - R * A1.
      { rot: rot, trans: vsub(b1, mat_mul_vec(rot, a1)) }
    end

    # 3 pairs: full rigid alignment, T = Frame_B * Frame_A.inverse.
    def solve_3(a1, a2, a3, b1, b2, b3, flip = false)
      fa = frame(a1, a2, a3, false)
      fb = frame(b1, b2, b3, flip)
      return nil if fa.nil? || fb.nil?

      ra = rotation_from_axes(fa[:x], fa[:y], fa[:n])
      rb = rotation_from_axes(fb[:x], fb[:y], fb[:n])
      # R_A is a rotation, so its inverse is its transpose.
      rot = mat_mul(rb, mat_transpose(ra))
      { rot: rot, trans: vsub(b1, mat_mul_vec(rot, a1)) }
    end

    # Dispatch on how many pairs the user actually picked. `flip` only has
    # meaning for the 3-pair mode, where a plane normal exists to flip.
    def solve(source_points, target_points, flip = false)
      n = [source_points.length, target_points.length].min
      case n
      when 1 then solve_1(source_points[0], target_points[0])
      when 2 then solve_2(source_points[0], source_points[1],
                          target_points[0], target_points[1])
      when 3 then solve_3(source_points[0], source_points[1], source_points[2],
                          target_points[0], target_points[1], target_points[2],
                          flip)
      end
    end

    # True when the solution would not move anything (identical source and
    # target frames) -- the tool reports this instead of writing an empty
    # undo step.
    def identity_solution?(solution)
      return true if solution.nil?

      id = identity_rotation
      (0..2).each do |i|
        (0..2).each do |j|
          return false if (solution[:rot][i][j] - id[i][j]).abs > IDENTITY_ROT_TOL
        end
      end
      vlength(solution[:trans]) <= IDENTITY_TRANS_TOL
    end

    # Determinant of the rotation part -- a sanity check that the result is a
    # proper rotation (+1) and not a mirror (-1). Used by the tool as a
    # belt-and-braces guard before touching the model, and by the tests.
    def rotation_determinant(rot)
      rot[0][0] * (rot[1][1] * rot[2][2] - rot[1][2] * rot[2][1]) -
        rot[0][1] * (rot[1][0] * rot[2][2] - rot[1][2] * rot[2][0]) +
        rot[0][2] * (rot[1][0] * rot[2][1] - rot[1][1] * rot[2][0])
    end

    # Flat 16-element column-major matrix, the layout
    # Geom::Transformation.new takes: the first three groups of four are the
    # transformed X, Y, Z axes, the fourth is the origin.
    def to_matrix_array(solution)
      r = solution[:rot]
      t = solution[:trans]
      [r[0][0], r[1][0], r[2][0], 0.0,
       r[0][1], r[1][1], r[2][1], 0.0,
       r[0][2], r[1][2], r[2][2], 0.0,
       t[0],    t[1],    t[2],    1.0]
    end

    # The only SketchUp-API line in this file.
    def to_transformation(solution)
      Geom::Transformation.new(to_matrix_array(solution))
    end

    # Geom::Point3d (or anything with x/y/z) -> plain array, in inches.
    def point_to_a(pt)
      [pt.x.to_f, pt.y.to_f, pt.z.to_f]
    end
  end
end
