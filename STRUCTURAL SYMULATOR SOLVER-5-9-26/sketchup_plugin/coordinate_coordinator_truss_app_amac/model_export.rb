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
  #
  # This is also what makes shared parts findable, and the reason is worth
  # stating: a container NESTED INSIDE a component definition is one single
  # entity, shared by every instance of that definition. Walking two copies
  # of a truss therefore reports the SAME id for the bay inside each of
  # them -- not two ids that happen to match. See `component_key`.
  def container_id(ent)
    (ent.respond_to?(:persistent_id) ? ent.persistent_id : nil) || ent.object_id
  rescue StandardError
    ent.object_id
  end

  # The definition a component instance is a copy of, or nil for a group.
  #
  # SketchUp's two container kinds mean different things here, and the
  # difference is exactly the one the Stereo tab draws. A GROUP is unique:
  # editing one does not touch another, so it is one group. A COMPONENT
  # INSTANCE is a placement of a shared definition -- one drawing, built
  # as many times as it is placed -- which is the Stereo tab's component.
  def definition_name(ent)
    return nil unless ent.is_a?(Sketchup::ComponentInstance)
    name = ent.definition.name.to_s.strip rescue ''
    name.empty? ? 'Component' : name
  rescue StandardError
    nil
  end

  # How much a transformation stretches each axis, as a string to compare
  # by. Two instances of one definition are the same fabricated part only
  # if they are the same SIZE: SketchUp lets an instance be scaled, and a
  # truss placed at 0.8 is a different piece of steel with different bar
  # lengths, however much it shares a drawing on screen.
  #
  # Magnitudes only, so a MIRRORED instance still matches the one it was
  # mirrored from -- a left-hand copy is the same part built the other way
  # round, which is a thing the Stereo tab already knows how to mark.
  def scale_signature(tr)
    return '1x1x1' if tr.nil?
    axes = [Geom::Vector3d.new(1, 0, 0), Geom::Vector3d.new(0, 1, 0),
            Geom::Vector3d.new(0, 0, 1)]
    o = Geom::Point3d.new(0, 0, 0).transform(tr)
    axes.map do |v|
      p = Geom::Point3d.new(v.x, v.y, v.z).transform(tr)
      format('%.4f', (p - o).length.to_f)
    end.join('x')
  rescue StandardError
    '1x1x1'
  end

  # Depth-first walk of `entities`, following groups and component
  # instances, yielding every edge as
  #
  #     [p0_world, p1_world, path]
  #
  # where `path` is the containers it was found inside, outermost first, as
  #
  #     [container_id, name, definition_name_or_nil, scale_signature]
  #
  # -- the provenance the Groups sheet is built from. The last two are what
  # make a component a shared part rather than a container that happens to
  # repeat; see `component_key`. An edge lying loose in the starting
  # context has an empty path.
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
      step = [container_id(ent), container_name(ent),
              definition_name(ent), scale_signature(inner)]
      each_world_segment(sub, inner, path + [step], depth + 1, &blk)
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

  # What makes two containers copies of ONE fabricated part, or nil.
  #
  # Returns [identity, display_name, definition_name, scale]. Two
  # containers with the same `identity` are the same part; the Stereo tab
  # is told so through the Groups sheet's `component` column, and then
  # sizes them together and marks them with one piece mark.
  #
  # The identity is built from the OUTERMOST component instance on the
  # path, plus the ids of the containers below it:
  #
  #   * the outermost instance, because everything under a shared
  #     definition is shared with it. Two copies of "Truss A" are the same
  #     part, and so is the bay inside each of them.
  #   * its definition name and its accumulated SCALE, because a definition
  #     placed at two sizes is two parts -- same drawing, different steel.
  #   * the ids of the containers below it, which are literally the same
  #     entities for every instance (a definition's contents are shared, not
  #     copied), so the bay inside copy 1 and the bay inside copy 2 report
  #     one id and match without being compared.
  #
  # A path with no instance on it is nil: a GROUP is unique in SketchUp --
  # editing one does not touch another -- so a group is a group, and the
  # Stereo tab's own Make component is where two of them become one part.
  #
  # What this deliberately does NOT do is merge a standalone instance of a
  # definition with one nested inside another definition. They may well be
  # the same part; they are keyed differently here, and finding that is a
  # job for comparing shapes rather than for reading the model tree. Erring
  # toward two parts costs a duplicated drawing. Erring toward one sends
  # the wrong steel.
  def component_key(path)
    at = path.index { |entry| entry[2] }
    return nil if at.nil?
    _cid, _name, defn, scale = path[at]
    below = path[(at + 1)..] || []
    identity = ([defn, scale] + below.map { |e| e[0] }).join('|')
    label = ([defn] + below.map { |e| e[1] }).join(' / ')
    [identity, label, defn, scale]
  end

  # The Groups sheet's rows, from the container path of every member.
  #
  #   [{id:, name:, parent:, rods: [member indices], component: name}, ...]
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
        key = prefix.map { |e| e[0] }
        next if ids.key?(key)
        parent = n == 1 ? nil : ids[prefix[0, n - 1].map { |e| e[0] }]
        ids[key] = rows.length + 1
        rows << { id: rows.length + 1, name: prefix[-1][1],
                  parent: parent, rods: [], part: component_key(prefix) }
      end
    end
    member_paths.each_with_index do |path, i|
      next if path.nil? || path.empty?
      rows[ids[path.map { |e| e[0] }] - 1][:rods] << i
    end
    name_components(rows)
    rows
  end

  # Turn each row's part identity into the name the Groups sheet carries.
  #
  # Only a row with rods OF ITS OWN gets one. A container that holds just
  # subgroups is a branch of the tree, and the Stereo tab's rule is that a
  # component is a group's own rods -- it refuses to make a part of a
  # branch, so writing one here would only be refused later, having
  # inflated the copy count in the meantime.
  #
  # The NAME is what the Stereo tab compares by, so it has to separate
  # exactly what the identity separates. Two things push it apart:
  #
  #   * one definition placed at more than one SIZE -- then every one of
  #     them carries its scale, so none can quietly pass for the unscaled
  #     part;
  #   * two different parts that would otherwise read the same, which
  #     happens when a definition holds two sub-containers with one name
  #     ("Truss A / Bay" twice). They are different steel, so the second
  #     gets a number. A false merge here would have the Stereo tab size
  #     one part from another part's loads.
  def name_components(rows)
    scales = {}
    rows.each do |row|
      next if row[:part].nil? || row[:rods].empty?
      (scales[row[:part][2]] ||= {})[row[:part][3]] = true
    end

    wanted = {}   # identity -> label, in first-seen order
    rows.each do |row|
      part = row[:part]
      next if part.nil? || row[:rods].empty?
      identity, label, defn, scale = part
      next if wanted.key?(identity)
      wanted[identity] =
        (scales[defn] || {}).length > 1 ? "#{label} [#{scale}]" : label
    end

    taken = {}
    final = {}
    wanted.each do |identity, label|
      name = label
      n = 1
      while taken.key?(name)
        n += 1
        name = "#{label} ##{n}"
      end
      taken[name] = true
      final[identity] = name
    end

    rows.each do |row|
      part = row.delete(:part)
      next if part.nil? || row[:rods].empty?
      row[:component] = final[part[0]]
    end
    rows
  end
end
