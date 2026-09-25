# intersections.rb
#
# Automatic counterpart to hand-picking: given whatever the user has
# selected, find every "corner" (an edge's own endpoints) and every place
# two edges cross in 3D without sharing a vertex, and hand the combined
# point list to the same StereoExport.build_model used by the manual tool.
# Faces are deliberately ignored as data -- if one is in the selection we
# only use it to recover its boundary edges, never its own geometry.
module CoordinateCoordinatorTrussAppAMAC
  # Pulls Sketchup::Edge entities out of a selection (or any entities
  # collection). Faces contribute their boundary edges only; anything else
  # (Group, ComponentInstance, text, guides, ...) is skipped -- this tool
  # works on the flat wireframe of the current editing context, same scope
  # as the manual picking tool.
  def self.collect_edges(selection)
    edges = {}
    selection.each do |ent|
      case ent
      when Sketchup::Edge
        edges[ent] = true
      when Sketchup::Face
        ent.edges.each { |e| edges[e] = true }
      end
    end
    edges.keys
  end

  # True if the two edges meet at a common point (by position, not Ruby
  # object identity -- so two edges from separately copied/arrayed geometry
  # that merely end up coincident still count as "already connected there,"
  # not as a crossing to be split).
  def self.shares_vertex?(e1, e2, tol = NODE_MERGE_TOLERANCE_IN)
    pts1 = [e1.start.position, e1.end.position]
    pts2 = [e2.start.position, e2.end.position]
    pts1.any? { |p1| pts2.any? { |p2| points_equal?(p1, p2, tol) } }
  end

  def self.edge_bbox(p0, p1, pad)
    [[p0.x, p1.x].min - pad, [p0.x, p1.x].max + pad,
     [p0.y, p1.y].min - pad, [p0.y, p1.y].max + pad,
     [p0.z, p1.z].min - pad, [p0.z, p1.z].max + pad]
  end

  def self.bbox_overlap?(a, b)
    a[0] <= b[1] && b[0] <= a[1] &&
      a[2] <= b[3] && b[2] <= a[3] &&
      a[4] <= b[5] && b[4] <= a[5]
  end

  # Closest points between two 3D segments (p0-p1) and (q0-q1). Returns the
  # midpoint of those closest points if both parameters land inside their
  # segment's span (with a little slack) and the segments actually meet
  # within tolerance -- nil for parallel, skew, or out-of-span cases.
  def self.segment_intersection(p0, p1, q0, q1)
    d1 = p1 - p0
    d2 = q1 - q0
    r = p0 - q0
    a = d1.dot(d1)
    e = d2.dot(d2)
    return nil if a < 1e-9 || e < 1e-9 # degenerate (zero-length) edge

    f = d2.dot(r)
    b = d1.dot(d2)
    c = d1.dot(r)
    denom = a * e - b * b
    return nil if denom.abs < 1e-9 # parallel

    t = (b * f - c * e).to_f / denom # .to_f: guard against integer division
    s = (a * f - b * c).to_f / denom
    return nil if t < -1e-4 || t > 1 + 1e-4
    return nil if s < -1e-4 || s > 1 + 1e-4

    cp = Geom::Point3d.new(p0.x + t * d1.x, p0.y + t * d1.y, p0.z + t * d1.z)
    cq = Geom::Point3d.new(q0.x + s * d2.x, q0.y + s * d2.y, q0.z + s * d2.z)
    gap = (cp - cq).length
    return nil if gap > ON_EDGE_TOLERANCE_IN

    Geom::Point3d.new((cp.x + cq.x) / 2.0, (cp.y + cq.y) / 2.0, (cp.z + cq.z) / 2.0)
  end

  # Every edge endpoint, plus every genuine edge-edge crossing among
  # `edges`. Candidate list only -- StereoExport.build_model does the
  # de-duplication and turns this into actual nodes/members.
  def self.autodetect_points(edges)
    points = []
    edges.each { |e| points << e.start.position << e.end.position }

    n = edges.length
    (0...n).each do |i|
      ei = edges[i]
      p0 = ei.start.position
      p1 = ei.end.position
      bi = edge_bbox(p0, p1, ON_EDGE_TOLERANCE_IN)
      (i + 1...n).each do |j|
        ej = edges[j]
        next if shares_vertex?(ei, ej)

        q0 = ej.start.position
        q1 = ej.end.position
        next unless bbox_overlap?(bi, edge_bbox(q0, q1, ON_EDGE_TOLERANCE_IN))

        pt = segment_intersection(p0, p1, q0, q1)
        points << pt if pt
      end
    end
    points
  end

  # One-shot: read the current selection, auto-detect nodes/members, export.
  # Origin is the bounding-box minimum of the selected edges, so node 0
  # sits on the geometry (not at a potentially distant 0,0,0) and every
  # exported coordinate is positive. Use the manual "Pick Origin + Nodes…"
  # tool instead if you need a custom origin.
  def self.autodetect_and_export(model)
    if model.selection.empty?
      UI.messagebox('Select the edges (and/or faces) of the truss first, then run this again.')
      return
    end

    edges = collect_edges(model.selection)
    if edges.empty?
      UI.messagebox('No edges found in the selection (only faces/other entities were selected).')
      return
    end

    points = autodetect_points(edges)
    bb = Geom::BoundingBox.new
    points.each { |p| bb.add(p) }
    origin = bb.min
    nodes_m, members = build_model(origin, points, edges)

    if members.empty?
      UI.messagebox('No members could be derived from the selection. ' \
                     'Make sure the selected edges share vertices or cross each other.')
      return
    end

    connected = {}
    members.each { |m| connected[m[:a]] = true; connected[m[:b]] = true }
    orphan_count = nodes_m.length - connected.size
    if orphan_count > 0
      nodes_m_clean = []
      remap = {}
      nodes_m.each_with_index do |coords, old_idx|
        next unless connected[old_idx]
        remap[old_idx] = nodes_m_clean.length
        nodes_m_clean << coords
      end
      members = members.map { |m| { a: remap[m[:a]], b: remap[m[:b]] } }
      nodes_m = nodes_m_clean
    end

    export_to_excel(nodes_m, members)
  end
end
