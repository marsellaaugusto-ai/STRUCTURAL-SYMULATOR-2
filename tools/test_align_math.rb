# test_align_math.rb -- stock-Ruby tests for the "Align by Points" math.
#
# align_math.rb is deliberately free of SketchUp API calls (apart from
# AlignMath.to_transformation, which is not exercised here), so the solvers
# can be checked without SketchUp:
#
#   ruby tools/test_align_math.rb
#
# These cover the properties the feature promises: rigidity (no scale, no
# mirror), A1 landing exactly on B1, A2 on the ray B1->B2, coplanarity with
# B3 on the correct side, the reduced 1- and 2-pair modes, the flip option,
# and collinearity rejection.
require_relative '../sketchup_extension/coordinate_coordinator_truss_app_amac/align_math'

M = CoordinateCoordinatorTrussAppAMAC::AlignMath

$failures = 0
$checks = 0

def check(label)
  $checks += 1
  ok = yield
  unless ok
    $failures += 1
    puts "FAIL: #{label}"
  end
end

def close(a, b, tol = 1e-9)
  (a - b).abs <= tol
end

def apply(solution, pt)
  M.vadd(M.mat_mul_vec(solution[:rot], pt), solution[:trans])
end

# Reference rigid transform used to generate "known answer" cases.
def rigid(axis, angle, trans)
  rot = M.rotation_axis_angle(axis, angle)
  ->(p) { M.vadd(M.mat_mul_vec(rot, p), trans) }
end

# --- 3 pairs: exact recovery of a known rigid motion -----------------------
a1 = [0.0, 0.0, 0.0]
a2 = [10.0, 0.0, 0.0]
a3 = [0.0, 7.0, 0.0]
move = rigid([0.3, 0.5, 0.81], 0.7, [12.0, -4.0, 33.0])
b1 = move.call(a1)
b2 = move.call(a2)
b3 = move.call(a3)

sol = M.solve_3(a1, a2, a3, b1, b2, b3)
check('3-pair: solvable') { !sol.nil? }
check('3-pair: proper rotation (det == +1)') { close(M.rotation_determinant(sol[:rot]), 1.0, 1e-9) }
check('3-pair: A1 lands on B1') { M.vlength(M.vsub(apply(sol, a1), b1)) < 1e-9 }
check('3-pair: A2 lands on B2 (equal distances here)') { M.vlength(M.vsub(apply(sol, a2), b2)) < 1e-9 }
check('3-pair: A3 lands on B3 (equal distances here)') { M.vlength(M.vsub(apply(sol, a3), b3)) < 1e-9 }

# Rigidity: every pairwise distance is preserved exactly.
[[a1, a2], [a1, a3], [a2, a3]].each_with_index do |(p, q), i|
  d0 = M.vlength(M.vsub(p, q))
  d1 = M.vlength(M.vsub(apply(sol, p), apply(sol, q)))
  check("3-pair: distance #{i} preserved (no scaling)") { close(d0, d1, 1e-9) }
end

# --- 3 pairs with MISMATCHED distances ------------------------------------
# A2 must end on the ray B1->B2, at its own distance from A1, not on B2.
b2_far = M.vadd(b1, M.vscale(M.vnormalize(M.vsub(b2, b1)), 40.0))
b3_far = M.vadd(b1, M.vscale(M.vsub(b3, b1), 3.0))
sol2 = M.solve_3(a1, a2, a3, b1, b2_far, b3_far)
check('3-pair mismatched: A1 still exact') { M.vlength(M.vsub(apply(sol2, a1), b1)) < 1e-9 }
check('3-pair mismatched: A2 on the ray B1->B2') do
  dir_t = M.vnormalize(M.vsub(b2_far, b1))
  dir_a = M.vnormalize(M.vsub(apply(sol2, a2), b1))
  close(M.vdot(dir_t, dir_a), 1.0, 1e-9)
end
check('3-pair mismatched: A2 keeps its own distance from A1') do
  close(M.vlength(M.vsub(apply(sol2, a2), b1)), M.vlength(M.vsub(a2, a1)), 1e-9)
end
check('3-pair mismatched: A3 coplanar with B1-B2-B3') do
  n = M.vnormalize(M.vcross(M.vsub(b2_far, b1), M.vsub(b3_far, b1)))
  close(M.vdot(n, M.vsub(apply(sol2, a3), b1)), 0.0, 1e-9)
end
check('3-pair mismatched: A3 on the same side as B3') do
  # "Same side" within the plane: both must be on the +Y half of the
  # target frame (the half-plane the frame's Y axis points into).
  fb = M.frame(b1, b2_far, b3_far)
  y_b3 = M.vdot(fb[:y], M.vsub(b3_far, b1))
  y_a3 = M.vdot(fb[:y], M.vsub(apply(sol2, a3), b1))
  y_b3 > 0 && y_a3 > 0
end

# --- flip normal ----------------------------------------------------------
sol_flip = M.solve_3(a1, a2, a3, b1, b2, b3, true)
check('flip: still a proper rotation (det == +1, not a mirror)') do
  close(M.rotation_determinant(sol_flip[:rot]), 1.0, 1e-9)
end
check('flip: A1 still lands on B1') { M.vlength(M.vsub(apply(sol_flip, a1), b1)) < 1e-9 }
check('flip: A1->A2 direction still aligned with B1->B2') do
  dir_t = M.vnormalize(M.vsub(b2, b1))
  dir_a = M.vnormalize(M.vsub(apply(sol_flip, a2), b1))
  close(M.vdot(dir_t, dir_a), 1.0, 1e-9)
end
check('flip: source normal ends up reversed vs. unflipped') do
  n_plain = M.vnormalize(M.vcross(M.vsub(apply(sol, a2), apply(sol, a1)),
                                  M.vsub(apply(sol, a3), apply(sol, a1))))
  n_flip = M.vnormalize(M.vcross(M.vsub(apply(sol_flip, a2), apply(sol_flip, a1)),
                                 M.vsub(apply(sol_flip, a3), apply(sol_flip, a1))))
  close(M.vdot(n_plain, n_flip), -1.0, 1e-9)
end
check('flip: A3 lands on the opposite side of the B1->B2 line') do
  fb = M.frame(b1, b2, b3)
  close(M.vdot(fb[:y], M.vsub(apply(sol_flip, a3), b1)),
        -M.vdot(fb[:y], M.vsub(apply(sol, a3), b1)), 1e-9)
end
check('flip: distances preserved') do
  close(M.vlength(M.vsub(a2, a3)),
        M.vlength(M.vsub(apply(sol_flip, a2), apply(sol_flip, a3))), 1e-9)
end

# --- 2 pairs --------------------------------------------------------------
s1 = [1.0, 2.0, 3.0]
s2 = [1.0, 2.0, 13.0]   # source direction: +Z
t1 = [-5.0, 8.0, 2.0]
t2 = [-5.0, 11.0, 2.0]  # target direction: +Y
sol2p = M.solve_2(s1, s2, t1, t2)
check('2-pair: solvable') { !sol2p.nil? }
check('2-pair: proper rotation (det == +1)') { close(M.rotation_determinant(sol2p[:rot]), 1.0, 1e-9) }
check('2-pair: A1 lands on B1') { M.vlength(M.vsub(apply(sol2p, s1), t1)) < 1e-9 }
check('2-pair: A1->A2 aligned with B1->B2') do
  dir_t = M.vnormalize(M.vsub(t2, t1))
  dir_a = M.vnormalize(M.vsub(apply(sol2p, s2), t1))
  close(M.vdot(dir_t, dir_a), 1.0, 1e-9)
end
check('2-pair: distance A1-A2 unchanged') do
  close(M.vlength(M.vsub(s2, s1)), M.vlength(M.vsub(apply(sol2p, s2), t1)), 1e-9)
end
check('2-pair: rotation is the MINIMUM one (angle == angle between u and v)') do
  u = M.vnormalize(M.vsub(s2, s1))
  v = M.vnormalize(M.vsub(t2, t1))
  expected = Math.acos(M.vdot(u, v))
  # Rotation angle from the trace: trace(R) = 1 + 2 cos(angle).
  trace = sol2p[:rot][0][0] + sol2p[:rot][1][1] + sol2p[:rot][2][2]
  cos_a = (trace - 1.0) / 2.0
  cos_a = 1.0 if cos_a > 1.0
  close(Math.acos(cos_a), expected, 1e-9)
end
check('2-pair: already-aligned directions give no rotation') do
  s = M.solve_2([0.0, 0.0, 0.0], [5.0, 0.0, 0.0], [9.0, 9.0, 9.0], [14.0, 9.0, 9.0])
  close(M.rotation_determinant(s[:rot]), 1.0, 1e-12) &&
    close(s[:rot][0][0], 1.0, 1e-12) && close(s[:rot][1][1], 1.0, 1e-12)
end
check('2-pair: antiparallel directions give a 180 deg turn, not a mirror') do
  s = M.solve_2([0.0, 0.0, 0.0], [5.0, 0.0, 0.0], [0.0, 0.0, 0.0], [-5.0, 0.0, 0.0])
  moved = apply(s, [5.0, 0.0, 0.0])
  close(M.rotation_determinant(s[:rot]), 1.0, 1e-9) &&
    M.vlength(M.vsub(moved, [-5.0, 0.0, 0.0])) < 1e-9
end
check('2-pair: coincident source points rejected') do
  M.solve_2([1.0, 1.0, 1.0], [1.0, 1.0, 1.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]).nil?
end

# --- 1 pair ---------------------------------------------------------------
sol1 = M.solve_1([2.0, 3.0, 4.0], [10.0, -1.0, 0.5])
check('1-pair: pure translation, no rotation') do
  sol1[:rot] == M.identity_rotation
end
check('1-pair: translation is B1 - A1') do
  M.vlength(M.vsub(sol1[:trans], [8.0, -4.0, -3.5])) < 1e-12
end
check('1-pair: A1 lands on B1') do
  M.vlength(M.vsub(apply(sol1, [2.0, 3.0, 4.0]), [10.0, -1.0, 0.5])) < 1e-12
end

# --- collinearity ---------------------------------------------------------
check('collinear: three points on a line rejected') do
  M.collinear?([0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [25.0, 0.0, 0.0])
end
check('collinear: duplicate points rejected') do
  M.collinear?([0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [10.0, 0.0, 0.0])
end
check('collinear: nearly-collinear sliver rejected (angle < 0.1 deg)') do
  # 0.05 degrees off the X axis at 100 inches -> cross product is large, but
  # the angle test still catches it.
  far = 100.0
  off = far * Math.tan(0.05 * Math::PI / 180.0)
  M.collinear?([0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [far, off, 0.0])
end
check('collinear: a healthy triangle is accepted') do
  !M.collinear?([0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [0.0, 10.0, 0.0])
end
check('collinear: solve_3 returns nil for a collinear source') do
  M.solve_3([0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0],
            [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]).nil?
end

# --- identical frames -----------------------------------------------------
check('identity: same source and target triplet is a no-op') do
  s = M.solve_3(a1, a2, a3, a1, a2, a3)
  M.identity_solution?(s)
end
check('identity: a real move is not reported as a no-op') do
  !M.identity_solution?(sol)
end
check('identity: flip of the same triplet is NOT a no-op') do
  !M.identity_solution?(M.solve_3(a1, a2, a3, a1, a2, a3, true))
end

# --- matrix hand-off ------------------------------------------------------
check('matrix: column-major 16-element layout') do
  m = M.to_matrix_array(sol)
  m.length == 16 &&
    close(m[3], 0.0) && close(m[7], 0.0) && close(m[11], 0.0) && close(m[15], 1.0) &&
    close(m[12], sol[:trans][0], 1e-12) &&
    close(m[13], sol[:trans][1], 1e-12) &&
    close(m[14], sol[:trans][2], 1e-12) &&
    close(m[0], sol[:rot][0][0], 1e-12) &&
    close(m[1], sol[:rot][1][0], 1e-12)
end

# --- dispatch -------------------------------------------------------------
check('solve: picks the mode from the number of pairs') do
  one = M.solve([a1], [b1])
  two = M.solve([a1, a2], [b1, b2])
  three = M.solve([a1, a2, a3], [b1, b2, b3])
  one[:rot] == M.identity_rotation &&
    M.vlength(M.vsub(apply(two, a1), b1)) < 1e-9 &&
    M.vlength(M.vsub(apply(three, a3), b3)) < 1e-9
end
check('solve: extra target points beyond the source count are ignored') do
  s = M.solve([a1, a2], [b1, b2, b3])
  M.vlength(M.vsub(apply(s, a1), b1)) < 1e-9
end

puts "#{$checks - $failures}/#{$checks} checks passed"
exit($failures.zero? ? 0 : 1)
