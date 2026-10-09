# intersections.rb
#
# Automatic counterpart to hand-picking: given whatever the user has
# selected, find every "corner" (an edge's own endpoints) and every place
# two edges cross in 3D without sharing a vertex, and hand the combined
# point list to the same build_model used by the manual tool.
# Faces are deliberately ignored as data -- if one is in the selection we
# only use it to recover its boundary edges, never its own geometry.
#
# Groups and component instances ARE followed, and their contents arrive in
# world coordinates (see model_export.rb's each_world_segment for why that
# matters). They used to be skipped: selecting a grouped truss -- which is
# how anyone who has modelled one has it -- and running auto-detect
# reported "no edges found", and selecting a group TOGETHER with a few loose
# edges was worse, because it exported the loose few and said nothing about
# the hundreds it had dropped.
module CoordinateCoordinatorTrussAppAMAC
  # World-space segments for everything in a selection (or any entities
  # collection): the loose edges of the current context, the boundary edges
  # of any selected face, and the whole contents of any selected group or
  # component instance, however deeply nested.
  #
  # `base` is the transformation from the selection's own context to the
  # world -- the model's `edit_transform`, which is the identity at the top
  # level.
  #
  # A segment is [p0_world, p1_world, container_path]; see each_world_segment.
  def self.collect_segments(selection, base = nil)
    direct = {}      # Edge => true, de-duplicated by entity as it always was
    containers = []  # [entity, its entities]
    selection.each do |ent|
      case ent
      when Sketchup::Edge
        direct[ent] = true
      when Sketchup::Face
        ent.edges.each { |e| direct[e] = true }
      else
        sub = container_entities(ent)
        containers << [ent, sub] if sub
      end
    end

    segments = direct.keys.map do |e|
      p0 = e.start.position
      p1 = e.end.position
      base ? [p0.transform(base), p1.transform(base), []] : [p0, p1, []]
    end
    containers.each do |ent, sub|
      inner = base ? base * ent.transformation : ent.transformation
      each_world_segment(sub, inner,
                         [[container_id(ent), container_name(ent)]], 1) do |p0, p1, path|
        segments << [p0, p1, path]
      end
    end
    segments
  end

  # True if the two segments meet at a common point. Compared by POSITION,
  # not by Ruby object identity -- so two edges from separately
  # copied/arrayed geometry that merely end up coincident still count as
  # "already connected there," not as a crossing to be split. That is also
  # what makes this work across containers, where the same edge of one
  # component definition arrives twice at two different places.
  def self.shares_endpoint?(p0, p1, q0, q1, tol = NODE_MERGE_TOLERANCE_IN)
    [p0, p1].any? { |a| [q0, q1].any? { |b| points_equal?(a, b, tol) } }
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

  # Every segment endpoint, plus every genuine segment-segment crossing.
  # Candidate list only -- build_model_from_segments does the
  # de-duplication and turns this into actual nodes/members.
  #
  # The crossing search is a sweep along x: the segments are ordered by the
  # low x of their padded bounding box, so once a later segment starts to
  # the right of where the current one ends, no segment after it can touch
  # the current one either and the inner loop is done. The pairwise test was
  # affordable while this only ever saw the handful of edges loose in one
  # context; now that it follows groups it can be handed a whole building,
  # and n^2 on a few thousand edges is a visible freeze. Ordering a copy
  # leaves the caller's segment list -- and so the exported member
  # numbering -- exactly as it was.
  def self.autodetect_points(segments)
    points = []
    segments.each { |p0, p1, _| points << p0 << p1 }

    boxed = segments.map do |p0, p1, _|
      [edge_bbox(p0, p1, ON_EDGE_TOLERANCE_IN), p0, p1]
    end
    boxed.sort_by! { |bb, _, _| bb[0] }

    n = boxed.length
    (0...n).each do |i|
      bi, p0, p1 = boxed[i]
      (i + 1...n).each do |j|
        bj, q0, q1 = boxed[j]
        break if bj[0] > bi[1]      # sorted by low x: nothing further can reach back
        next unless bbox_overlap?(bi, bj)
        next if shares_endpoint?(p0, p1, q0, q1)

        pt = segment_intersection(p0, p1, q0, q1)
        points << pt if pt
      end
    end
    points
  end

  # One-shot: read the current selection, auto-detect nodes/members, export.
  # Origin is the bounding-box minimum of the detected points, so node 0
  # sits on the geometry (not at a potentially distant 0,0,0) and every
  # exported coordinate is positive. Use the manual "Pick Origin + Nodes…"
  # tool instead if you need a custom origin.
  def self.autodetect_and_export(model)
    if model.selection.empty?
      UI.messagebox('Select the edges, faces, groups or components of the truss first, then run this again.')
      return
    end

    base = begin
      model.edit_transform
    rescue StandardError
      nil
    end
    segments = collect_segments(model.selection, base)
    if segments.empty?
      UI.messagebox('No edges found in the selection -- only faces with no ' \
                     'boundary, empty groups, or other entities were selected.')
      return
    end

    points = autodetect_points(segments)
    bb = Geom::BoundingBox.new
    points.each { |p| bb.add(p) }
    origin = bb.min
    nodes_m, members, member_paths =
      build_model_from_segments(origin, points, segments)

    if members.empty?
      UI.messagebox('No members could be derived from the selection. ' \
                     'Make sure the selected edges share vertices or cross each other.')
      return
    end

    # Orphan nodes go, and the members are renumbered onto the nodes that
    # stay. Members themselves are never dropped or reordered here, so
    # member_paths stays index-for-index with them.
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

    export_to_excel(nodes_m, members, group_rows(member_paths))
  end
end
