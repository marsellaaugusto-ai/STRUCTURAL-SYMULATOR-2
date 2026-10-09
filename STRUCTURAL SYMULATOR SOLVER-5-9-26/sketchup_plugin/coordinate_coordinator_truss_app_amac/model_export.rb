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
#
# EVERYTHING HERE WORKS IN WORLD COORDINATES, and that is the whole point of
# `each_world_segment` below. Until it existed this file did
# `entities.grep(Sketchup::Edge)`, which sees only the edges lying loose in
# the context it was handed: anything the modeller had tucked into a group or
# a component was invisible to the export, so a truss that had been grouped
# -- the normal way to model one -- came out with nodes and NO members, or
# with the handful of members that happened not to be grouped. Nothing said
# so. Walking the containers fixes that, and it has to accumulate their
# transformations, because an edge inside a group reports its position in
# that group's own coordinate system; the group's transformation is what
# puts it where the modeller sees it.
#
# Working in world coordinates also fixes a quieter version of the same
# mistake. Picked points come from Sketchup::InputPoint, which reports in
# world coordinates, so while the user was editing INSIDE a group -- where
# the context's own transformation is not the identity -- the picks and the
# edges were being compared in two different spaces. It happened to work at
# the top level, where that transformation IS the identity, which is why it
# went unnoticed.
module CoordinateCoordinatorTrussAppAMAC
  INCH_TO_M = 0.0254
  # Perpendicular distance within which a picked point counts as "on" an
  # edge. ~0.25 mm -- tight enough to reject stray picks, loose enough to
  # absorb ordinary floating-point/inference noise.
  ON_EDGE_TOLERANCE_IN = 0.01
  # Picked points closer than this are treated as the same node.
  NODE_MERGE_TOLERANCE_IN = 0.001
  # How deep the container walk will go. SketchUp refuses to nest a
  # component inside itself, so a model cannot actually contain a cycle;
  # this is a guard against a corrupt file turning a bug into a hang, not a
  # modelling limit. Real structures nest a handful of levels deep.
  MAX_CONTAINER_DEPTH = 64

  module_function

  def points_equal?(p1, p2, tol = NODE_MERGE_TOLERANCE_IN)
    (p1.x - p2.x).abs < tol && (p1.y - p2.y).abs < tol && (p1.z - p2.z).abs < tol
  end

  # The entities inside a group or component instance, or nil for anything
  # else. A Group answers `entities` directly; a ComponentInstance keeps its
  # geometry on the definition it shares with its other copies.
  def container_entities(ent)
    if ent.is_a?(Sketchup::ComponentInstance)
      ent.definition.entities
    elsif ent.is_a?(Sketchup::Group)
      ent.entities
    end
  end

  # What a container is called in the outliner. A component instance is
  # usually left unnamed and is known by its definition's name, which is
  # what the modeller actually sees and typed.
  def container_name(ent)
    own = ent.name.to_s.strip rescue ''
    return own unless own.empty?
    if ent.respond_to?(:definition)
      dn = ent.definition.name.to_s.strip rescue ''
      return dn unless dn.empty?
    end
    ent.is_a?(Sketchup::ComponentInstance) ? 'Component' : 'Group'
  end

  # Something stable to tell two containers apart by. Two sibling groups are
  # very often given the same name (or no name at all), so the name cannot
  # be the identity -- persistent_id is the model's own answer, and
  # object_id is the fallback for an older SketchUp.
  def container_id(ent)
    (ent.respond_to?(:persistent_id) ? ent.persistent_id : nil) || ent.object_id
  rescue StandardError
    ent.object_id
  end

  # Depth-first walk of `entities`, following groups and component
  # instances, yielding every edge as
  #
  #     [p0_world, p1_world, path]
  #
  # where `path` is the containers it was found inside, outermost first, as
  # [container_id, name] pairs -- the provenance the Groups sheet is built
  # from. An edge lying loose in the starting context has an empty path.
  #
  # `base` is the transformation from the starting context to the world. At
  # the top level that is the identity (pass nil); inside a group being
  # edited it is the model's own `edit_transform`.
  #
  # Hidden geometry is walked like any other. Dropping it would be a second
  # silent omission of exactly the kind this method exists to end, and a
  # hidden brace is still a brace; guides and construction lines are not
  # edges, so they never came in to begin with.
  def each_world_segment(entities, base = nil, path = [], depth = 0, &blk)
    return if depth > MAX_CONTAINER_DEPTH
    entities.each do |ent|
      if ent.is_a?(Sketchup::Edge)
        p0 = ent.start.position
        p1 = ent.end.position
        if base
          p0 = p0.transform(base)
          p1 = p1.transform(base)
        end
        blk.call(p0, p1, path)
        next
      end
      sub = container_entities(ent)
      next if sub.nil?
      inner = base ? base * ent.transformation : ent.transformation
      each_world_segment(sub, inner,
                         path + [[container_id(ent), container_name(ent)]],
                         depth + 1, &blk)
    end
  end

  # Every edge under `entities`, nested containers included, as world-space
  # segments. See each_world_segment for what a segment is.
  def world_segments(entities, base = nil)
    out = []
    each_world_segment(entities, base) { |p0, p1, path| out << [p0, p1, path] }
    out
  end

  # origin, picked_points: Geom::Point3d in WORLD coordinates -- which is
  # what Sketchup::InputPoint#position gives you, in any editing context.
  #
  # Returns [nodes_m, members, member_paths]:
  #   nodes_m      -- Array of [x_m, y_m, z_m]; node 0 is always the origin.
  #   members      -- Array of {a: idx, b: idx}, de-duplicated.
  #   member_paths -- the container path each member was found under, index
  #                   for index with `members`.
  def build_model(origin, picked_points, entities, base = nil)
    build_model_from_segments(origin, picked_points,
                              world_segments(entities, base))
  end

  # The core, split out from build_model so it can be driven by a plain list
  # of segments -- that is what the auto-detect path already has in hand,
  # and it is what makes this testable without a running SketchUp.
  def build_model_from_segments(origin, picked_points, segments)
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

    # key -> the container path of the FIRST segment that produced it. Two
    # segments in different containers can derive the same member (geometry
    # drawn twice, or a copy welded onto its neighbour); a rod belongs to
    # exactly one group, so the first one to claim it keeps it rather than
    # the last one to overwrite it. The walk is depth-first in document
    # order, so "first" is the same on every export of the same model.
    member_set = {}
    segments.each do |es, ee, path|
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
        next if member_set.key?(key)
        member_set[key] = path || []
      end
    end

    keys = member_set.keys
    members = keys.map { |a, b| { a: a, b: b } }
    [nodes_m, members, keys.map { |k| member_set[k] }]
  end

  # '0-3, 7, 9-10' from [0,1,2,3,7,9,10] -- the rod-list spelling the
  # Stereo tab's Groups sheet reads (stereo_groups_excel.parse_ranges).
  def rods_to_ranges(idx)
    idx = idx.map(&:to_i).uniq.sort
    out = []
    k = 0
    while k < idx.length
      j = k
      j += 1 while j + 1 < idx.length && idx[j + 1] == idx[j] + 1
      out << (j == k ? idx[k].to_s : "#{idx[k]}-#{idx[j]}")
      k = j + 1
    end
    out.join(', ')
  end

  # The Groups sheet's rows, from the container path of every member.
  #
  #   [{id:, name:, parent:, rods: [member indices]}, ...]
  #
  # One row per container that has any geometry under it, nested the way the
  # model nests it. A member belongs to its INNERMOST container, because a
  # rod belongs to exactly one group -- that is the rule the Stereo tab's
  # per-group tonnages and utilisation summaries add up under. A container
  # that holds no rods of its own still gets a row when something below it
  # does: it is a real branch of the tree, and leaving it out would flatten
  # the nesting the modeller built.
  #
  # Ids are assigned outermost-first, so a parent's id is always lower than
  # its children's and the sheet reads top-down.
  def group_rows(member_paths)
    ids = {}
    rows = []
    member_paths.each do |path|
      next if path.nil?
      (1..path.length).each do |n|
        prefix = path[0, n]
        key = prefix.map { |cid, _| cid }
        next if ids.key?(key)
        parent = n == 1 ? nil : ids[prefix[0, n - 1].map { |cid, _| cid }]
        ids[key] = rows.length + 1
        rows << { id: rows.length + 1, name: prefix[-1][1],
                  parent: parent, rods: [] }
      end
    end
    member_paths.each_with_index do |path, i|
      next if path.nil? || path.empty?
      rows[ids[path.map { |cid, _| cid }] - 1][:rods] << i
    end
    rows
  end
end
