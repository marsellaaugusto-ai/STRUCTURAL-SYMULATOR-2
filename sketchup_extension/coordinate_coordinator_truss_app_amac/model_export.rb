# model_export.rb
#
# Turns (origin point, picked node points, model entities) into the plain
# data the Stereo Excel format needs: a node list translated so the origin
# becomes (0, 0, 0), in meters, and a member list of node-index pairs.
#
# Connectivity is derived, not picked by hand: for every edge in the given
# entities, we find which picked nodes lie on that edge (within a small
# tolerance) and, sorted along the edge, connect each consecutive pair as a
# member. Two ordinary endpoints on an edge -> one member. Three or more
# (an intermediate node was picked, e.g. where two un-split diagonals cross
# in space and the user snapped to that "virtual" intersection with
# SketchUp's own Intersection inference) -> the edge is split into that many
# members automatically. No special-casing is needed for the "vertex vs.
# line-line intersection" distinction the picking step already resolved.
module CoordinateCoordinatorTrussAppAMAC
  INCH_TO_M = 0.0254
  # Perpendicular distance within which a picked point counts as "on" an
  # edge. ~0.25 mm -- tight enough to reject stray picks, loose enough to
  # absorb ordinary floating-point/inference noise.
  ON_EDGE_TOLERANCE_IN = 0.01
  # Picked points closer than this are treated as the same node.
  NODE_MERGE_TOLERANCE_IN = 0.001

  module_function

  def points_equal?(p1, p2, tol = NODE_MERGE_TOLERANCE_IN)
    (p1.x - p2.x).abs < tol && (p1.y - p2.y).abs < tol && (p1.z - p2.z).abs < tol
  end

  # origin, picked_points: Geom::Point3d, in the active entities' own
  # coordinate system (so this must be called with the same `entities`
  # context the points were picked in -- see PickNodesTool).
  #
  # Returns [nodes_m, members]:
  #   nodes_m -- Array of [x_m, y_m, z_m]; node 0 is always the origin.
  #   members -- Array of {a: idx, b: idx}, de-duplicated.
  def build_model(origin, picked_points, entities)
    unique_points = [origin]
    picked_points.each do |p|
      next if unique_points.any? { |u| points_equal?(u, p) }
      unique_points << p
    end

    nodes_m = unique_points.map do |p|
      [(p.x - origin.x) * INCH_TO_M,
       (p.y - origin.y) * INCH_TO_M,
       (p.z - origin.z) * INCH_TO_M]
    end

    member_set = {}
    entities.grep(Sketchup::Edge).each do |edge|
      es = edge.start.position
      ee = edge.end.position
      d = ee - es
      len2 = d.dot(d)
      next if len2 < 1e-9 # zero-length/degenerate edge

      on_edge = [] # [t_along_edge, node_index]
      unique_points.each_with_index do |p, idx|
        v = p - es
        t = v.dot(d).to_f / len2 # to_f guards against integer division
        next if t < -1e-4 || t > 1 + 1e-4 # not within the edge's span

        perp = Geom::Vector3d.new(v.x - t * d.x, v.y - t * d.y, v.z - t * d.z)
        next if perp.length > ON_EDGE_TOLERANCE_IN

        on_edge << [t, idx]
      end
      next if on_edge.length < 2

      on_edge.sort_by! { |t, _| t }
      on_edge.each_cons(2) do |(_, i1), (_, i2)|
        next if i1 == i2
        key = [i1, i2].sort
        member_set[key] = true
      end
    end

    members = member_set.keys.map { |a, b| { a: a, b: b } }
    [nodes_m, members]
  end
end
