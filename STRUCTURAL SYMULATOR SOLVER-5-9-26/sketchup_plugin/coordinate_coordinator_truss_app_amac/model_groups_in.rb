# model_groups_in.rb
#
# The way back. model_export sends a SketchUp model to the Stereo tab with
# its groups and its shared parts intact; this brings a Stereo model the
# other way, as groups the Outliner shows and components the Component
# Browser lists -- with the piece mark on each one, which is the thing a
# fabricator actually reads.
#
# Three pieces, and the third is the only hard one:
#
#   * GROUPS. The Groups sheet is a flat list with a `parent` column, so
#     the tree is rebuilt by making every group outermost-first and adding
#     each one's rods to its own entities. A rod belongs to exactly one
#     group, which is what makes that unambiguous.
#
#   * MARKS. Each container is named "<group> [T1]". SketchUp has no idea
#     what a piece mark is, and does not need one: the name is what the
#     Outliner shows and what someone reads off the model.
#
#   * COMPONENTS. Groups sharing a `component` are copies of one part, and
#     the whole point of sending them back as component instances is that
#     they stay one part in SketchUp too -- edit the definition and every
#     copy follows. That needs the TRANSFORMATION from the first copy onto
#     each of the others, and the workbook does not carry one. See
#     `rigid_between`.
module CoordinateCoordinatorTrussAppAMAC
  # Two nodes closer than this are the same point when checking that a
  # transformation really does land one copy on another. Generous: these
  # are coordinates that have been through metres, a spreadsheet and back.
  PLACE_TOLERANCE_IN = 0.05

  # ── the Groups sheet ─────────────────────────────────────────────────────

  # '0-3, 7, 9-10' -> [0,1,2,3,7,9,10]. The spelling model_export writes
  # and stereo_groups_excel.parse_ranges reads; this is the third reader of
  # it and the only one in Ruby.
  def self.parse_rod_ranges(text)
    out = []
    text.to_s.tr(';', ',').tr(' ', ',').split(',').each do |tok|
      tok = tok.strip
      next if tok.empty?
      if tok.include?('-') && !tok.start_with?('-')
        lo, hi = tok.split('-', 2)
        lo = lo.to_f.round
        hi = hi.to_f.round
        next if hi < lo
        (lo..hi).each { |i| out << i }
      else
        out << tok.to_f.round
      end
    end
    out.uniq.sort
  end

  # The Groups sheet as records, or [] when the workbook has none.
  #
  #   [{id:, name:, parent:, rods: [...], component:, mark:}, ...]
  def self.groups_from_sheet(reader)
    grid = reader.sheet('Groups')
    return [] if grid.nil?
    head_at = grid.index { |r| r && r[0].to_s.strip == 'id' }
    return [] if head_at.nil?
    headers = grid[head_at].map { |c| c.to_s.strip }
    col = {}
    headers.each_with_index { |h, i| col[h] = i unless h.empty? }
    return [] if col['id'].nil?

    out = []
    grid[(head_at + 1)..].to_a.each do |row|
      next if row.nil? || row.compact.empty?
      raw = ->(name) { col[name] ? row[col[name]] : nil }
      id = raw.call('id')
      next if id.nil? || id.to_s.strip.empty?
      parent = raw.call('parent')
      component = raw.call('component').to_s.strip
      mark = raw.call('info: piece mark').to_s.strip
      out << { id: id.to_f.round,
               name: raw.call('name').to_s.strip,
               parent: (parent.nil? || parent.to_s.strip.empty? ? nil
                        : parent.to_f.round),
               rods: parse_rod_ranges(raw.call('rods')),
               component: (component.empty? ? nil : component),
               mark: (mark.empty? ? nil : mark) }
    end
    out
  end

  # What the Outliner should call this container.
  def self.group_label(record)
    name = record[:name].to_s.strip
    name = "Group #{record[:id]}" if name.empty?
    record[:mark] ? "#{name} [#{record[:mark]}]" : name
  end

  # ── placing one copy of a part on top of another ────────────────────────

  def self.centroid_of(pts)
    n = pts.length.to_f
    Geom::Point3d.new(pts.sum { |p| p.x } / n,
                      pts.sum { |p| p.y } / n,
                      pts.sum { |p| p.z } / n)
  end

  # An orthonormal frame the point cloud chooses for itself: the first axis
  # points at whichever node sits farthest from the centre, the second at
  # the farthest node off that line. Both are intrinsic to the cloud, so a
  # moved and turned copy of it yields the moved and turned copy of the
  # frame -- which is exactly what makes one map onto the other.
  #
  # Where several nodes tie for farthest the choice is arbitrary, and that
  # is harmless rather than lucky: a tie IS a symmetry of the part, so the
  # two frames differ by a motion that maps the part onto itself, and the
  # geometry still lands where it belongs. `rigid_between` checks anyway.
  def self.cloud_frame(pts, flip = false)
    c = centroid_of(pts)
    local = pts.map { |p| p - c }
    far = local.max_by(&:length)
    return nil if far.nil? || far.length < 1e-6
    e1 = far.normalize

    wide = local.map { |v| v - scaled(e1, v.dot(e1)) }.max_by(&:length)
    if wide.nil? || wide.length < 1e-6
      ref = e1.z.abs < 0.9 ? Geom::Vector3d.new(0, 0, 1)
                           : Geom::Vector3d.new(1, 0, 0)
      e2 = e1.cross(ref).normalize
    else
      e2 = wide.normalize
    end
    e3 = e1.cross(e2)
    e3 = scaled(e3, -1.0) if flip
    [Geom::Transformation.new(e1, e2, e3, c), c]
  end

  def self.scaled(v, k)
    Geom::Vector3d.new(v.x * k, v.y * k, v.z * k)
  end

  # A transformation that carries `src` onto `dst`, or nil.
  #
  # Both are the node clouds of two copies of one fabricated part, so a
  # rigid motion between them exists -- the workbook simply does not record
  # which. It is recovered from each cloud's own frame, and then CHECKED:
  # every source point has to land on a destination point. If it does not,
  # the mirrored frame is tried, because a left-hand copy is a real thing
  # the Stereo tab already marks. If that fails too the answer is nil, and
  # the caller builds that copy as a plain group rather than placing an
  # instance somewhere wrong. Geometry in the wrong place is worse than
  # geometry that is not shared.
  def self.rigid_between(src, dst)
    return nil if src.length < 2 || src.length != dst.length
    base, = cloud_frame(src)
    return nil if base.nil?
    [false, true].each do |flip|
      target, = cloud_frame(dst, flip)
      next if target.nil?
      tr = target * base.inverse
      return tr if lands_on?(src, dst, tr)
    end
    nil
  end

  def self.lands_on?(src, dst, tr, tol = PLACE_TOLERANCE_IN)
    src.all? do |p|
      q = p.transform(tr)
      dst.any? { |d| (d - q).length <= tol }
    end
  end

  # The nodes a set of rods touches, in world inches, de-duplicated.
  def self.rod_points(nodes, members, rods)
    seen = {}
    out = []
    rods.each do |i|
      m = members[i]
      next if m.nil?
      [m[:a], m[:b]].each do |n|
        next if n.nil? || n >= nodes.length
        next if seen[n]
        seen[n] = true
        out << Geom::Point3d.new(*nodes[n])
      end
    end
    out
  end

  # ── building the tree ────────────────────────────────────────────────────

  # Build every group, nested, and return what was made.
  #
  # `draw` is called as draw.call(entities, rod_index) and is whatever the
  # importer is drawing a rod with -- an edge, or a cylinder. Keeping it a
  # block is what lets wireframe and solid share all of this.
  #
  # Rods in no group are left to the caller: they belong in the context the
  # import is happening in, not in a container nobody asked for.
  def self.build_group_tree(ents, records, nodes, members, draw)
    made = {}
    report = { groups: 0, instances: 0, definitions: 0, loose_copies: [] }
    parts = {}
    records.each do |r|
      next if r[:component].nil? || r[:rods].empty?
      (parts[r[:component]] ||= []) << r
    end
    # A component whose group has children cannot be an instance: every
    # copy shares one definition, and children differ from copy to copy.
    # Such a group is built plainly, which is what it already was.
    has_child = {}
    records.each { |r| has_child[r[:parent]] = true unless r[:parent].nil? }
    parts.each_key do |name|
      parts[name] = parts[name].reject { |r| has_child[r[:id]] }
    end
    parts.reject! { |_name, rs| rs.length < 2 }

    definitions = {}
    ordered(records).each do |r|
      host = r[:parent].nil? ? ents : (made[r[:parent]] || ents)
      host = host.entities if host.respond_to?(:entities)
      made[r[:id]] = build_one(host, r, nodes, members, draw, parts,
                               definitions, report)
    end
    report[:groups] = made.length
    report[:definitions] = definitions.length
    [made, report]
  end

  # Records outermost-first, so a child is always added to a parent that
  # already exists. The sheet is written that way, but a hand-edited one
  # need not be, and a child built before its parent would silently land in
  # the wrong place.
  def self.ordered(records)
    by_id = {}
    records.each { |r| by_id[r[:id]] = r }
    out = []
    seen = {}
    place = lambda do |r, guard|
      return if r.nil? || seen[r[:id]] || guard[r[:id]]
      guard[r[:id]] = true
      place.call(by_id[r[:parent]], guard) unless r[:parent].nil?
      return if seen[r[:id]]
      seen[r[:id]] = true
      out << r
    end
    records.each { |r| place.call(r, {}) }
    out
  end

  def self.build_one(host, record, nodes, members, draw, parts, definitions,
                     report)
    name = group_label(record)
    family = record[:component] && parts[record[:component]]
    if family.nil? || family.first.equal?(record)
      made = host.add_group
      record[:rods].each { |i| draw.call(made.entities, i) }
      if family
        # The first copy becomes the definition every other copy shares.
        # Centred on itself, so the component's axes sit on the part rather
        # than wherever the model happens to be in space.
        inst = to_component(made, record[:component], record, nodes, members)
        definitions[record[:component]] = inst.definition if inst
        made = inst || made
        report[:instances] += 1 if inst
      end
      made.name = name
      return made
    end

    # Another copy of a part already built: place an instance of it.
    first = family.first
    definition = definitions[record[:component]]
    tr = definition && rigid_between(
      rod_points(nodes, members, first[:rods]),
      rod_points(nodes, members, record[:rods]))
    if tr.nil?
      # Nothing lined up, so this copy is built on its own. Said out loud
      # by the caller: a copy quietly left out of its part is a drawing
      # that disagrees with the model.
      made = host.add_group
      record[:rods].each { |i| draw.call(made.entities, i) }
      made.name = name
      report[:loose_copies] << name
      return made
    end
    inst = host.add_instance(definition, tr * placement(first, nodes, members))
    inst.name = name
    report[:instances] += 1
    inst
  end

  # Where the first copy's definition has to be put back to stand where it
  # was drawn: it was centred when the definition was made.
  def self.placement(record, nodes, members)
    c = centroid_of(rod_points(nodes, members, record[:rods]))
    Geom::Transformation.translation(Geom::Vector3d.new(c.x, c.y, c.z))
  end

  # Turn the group holding the first copy into a component, with its
  # contents centred on the part.
  def self.to_component(group, name, record, nodes, members)
    c = centroid_of(rod_points(nodes, members, record[:rods]))
    back = Geom::Transformation.translation(
      Geom::Vector3d.new(-c.x, -c.y, -c.z))
    group.entities.transform_entities(back, group.entities.to_a)
    inst = group.to_component
    inst.transformation = Geom::Transformation.translation(
      Geom::Vector3d.new(c.x, c.y, c.z))
    inst.definition.name = unique_definition_name(inst.definition, name)
    inst
  rescue StandardError
    nil
  end

  # A definition name SketchUp will accept. The model may already hold one
  # under this name from an earlier import, and SketchUp keeps them unique
  # whether or not we do; doing it here means the name says which import it
  # came from rather than being silently renamed.
  def self.unique_definition_name(definition, wanted)
    model = Sketchup.active_model
    taken = {}
    begin
      model.definitions.each do |d|
        taken[d.name] = true unless d.equal?(definition)
      end
    rescue StandardError
      return wanted
    end
    return wanted unless taken[wanted]
    n = 2
    n += 1 while taken["#{wanted} (#{n})"]
    "#{wanted} (#{n})"
  end
end
