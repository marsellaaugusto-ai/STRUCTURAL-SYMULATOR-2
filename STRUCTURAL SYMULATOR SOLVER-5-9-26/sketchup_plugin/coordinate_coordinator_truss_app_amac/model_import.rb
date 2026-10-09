# model_import.rb
#
# Imports a Stereo model from an XLSX file exported by the Stereo tab
# (apps/stereo/stereo_reports.export_excel) and builds 3D geometry in
# SketchUp.
#
# The Model sheet contains bracketed sections [META], [NODES], [MEMBERS],
# etc.  The importer reads:
#   [META]    -> node_radius_m, rod_radius_m (both default to 0 = wireframe)
#   [NODES]   -> idx, x_m, y_m, z_m
#   [MEMBERS] -> idx, a, b
#
# Geometry rules (matching export_obj in stereo_reports.py):
#   radius = 0  -> wireframe: edges for rods, no node geometry
#   radius > 0  -> solid: sphere meshes at nodes, cylinder meshes for rods
#
# The Groups sheet, when the workbook has one, rebuilds the model's own
# organisation: its groups as SketchUp groups, nested; the groups that are
# copies of one part as instances of one component; and each container
# named after the piece mark it carries. See model_groups_in.rb. Without
# that sheet -- every workbook written before groups existed -- the import
# is the flat geometry it always was.
require 'sketchup.rb'

module CoordinateCoordinatorTrussAppAMAC
  M_TO_INCH = 39.3700787402

  # Parse the [SECTION] layout from the Model sheet grid (2D array).
  # Returns a hash  { section_name => { headers: [...], rows: [[...], ...] } }
  def self.parse_model_sections(grid)
    sections = {}
    current = nil
    headers = nil

    grid.each do |row|
      next if row.nil? || row.compact.empty?
      first = row[0].to_s.strip

      if first.start_with?('[') && first.end_with?(']')
        current = first
        headers = nil
        sections[current] = { headers: [], rows: [] }
        next
      end

      next unless current

      if headers.nil?
        headers = row.map { |c| c.to_s.strip }
        sections[current][:headers] = headers
      else
        sections[current][:rows] << row
      end
    end
    sections
  end

  # Build a UV sphere mesh as SketchUp entities.
  def self.build_sphere(ents, cx, cy, cz, r, n_lon = 8, n_lat = 6)
    verts = []
    verts << Geom::Point3d.new(cx, cy, cz + r)
    (1...n_lat).each do |i|
      phi = Math::PI * i / n_lat
      sp = Math.sin(phi)
      cp = Math.cos(phi)
      n_lon.times do |j|
        theta = 2.0 * Math::PI * j / n_lon
        verts << Geom::Point3d.new(
          cx + r * sp * Math.cos(theta),
          cy + r * sp * Math.sin(theta),
          cz + r * cp
        )
      end
    end
    verts << Geom::Point3d.new(cx, cy, cz - r)

    # Top cap
    n_lon.times do |j|
      j2 = (j + 1) % n_lon
      _add_face(ents, verts[0], verts[1 + j2], verts[1 + j])
    end
    # Body bands
    (0...(n_lat - 2)).each do |i|
      base = 1 + i * n_lon
      n_lon.times do |j|
        j2 = (j + 1) % n_lon
        a = base + j
        b = base + j2
        c = base + n_lon + j2
        d = base + n_lon + j
        _add_face(ents, verts[a], verts[b], verts[c])
        _add_face(ents, verts[a], verts[c], verts[d])
      end
    end
    # Bottom cap
    bot = verts.length - 1
    base = 1 + (n_lat - 2) * n_lon
    n_lon.times do |j|
      j2 = (j + 1) % n_lon
      _add_face(ents, verts[bot], verts[base + j], verts[base + j2])
    end
  end

  # Build a capped cylinder mesh between two points.
  def self.build_cylinder(ents, ax, ay, az, bx, by, bz, r, n_sides = 8)
    dx = bx - ax; dy = by - ay; dz = bz - az
    length = Math.sqrt(dx * dx + dy * dy + dz * dz)
    return if length < 1e-12

    ux = dx / length; uy = dy / length; uz = dz / length
    if uz.abs < 0.9
      px, py, pz = 0.0, 0.0, 1.0
    else
      px, py, pz = 1.0, 0.0, 0.0
    end
    vx = uy * pz - uz * py
    vy = uz * px - ux * pz
    vz = ux * py - uy * px
    vl = Math.sqrt(vx * vx + vy * vy + vz * vz)
    vx /= vl; vy /= vl; vz /= vl
    wx = uy * vz - uz * vy
    wy = uz * vx - ux * vz
    wz = ux * vy - uy * vx

    pts = []
    [[ax, ay, az], [bx, by, bz]].each do |ex, ey, ez|
      n_sides.times do |j|
        theta = 2.0 * Math::PI * j / n_sides
        ct = Math.cos(theta); st = Math.sin(theta)
        pts << Geom::Point3d.new(
          ex + r * (ct * vx + st * wx),
          ey + r * (ct * vy + st * wy),
          ez + r * (ct * vz + st * wz)
        )
      end
    end

    # Tube faces
    n_sides.times do |j|
      j2 = (j + 1) % n_sides
      a = j; b = j2; c = n_sides + j2; d = n_sides + j
      _add_face(ents, pts[a], pts[b], pts[c])
      _add_face(ents, pts[a], pts[c], pts[d])
    end
    # End caps
    (2...n_sides).each { |j| _add_face(ents, pts[0], pts[j - 1], pts[j]) }
    base = n_sides
    (2...n_sides).each { |j| _add_face(ents, pts[base], pts[base + j], pts[base + j - 1]) }
  end

  def self._add_face(ents, *pts)
    ents.add_face(pts)
  rescue StandardError
    nil
  end

  # Main import entry point.
  def self.import_from_stereo(model)
    path = UI.openpanel('Import Stereo Model', Dir.pwd, 'xlsx Files|*.xlsx||')
    return unless path

    begin
      reader = XlsxReader.new(path)
    rescue StandardError => e
      UI.messagebox("Failed to read XLSX file:\n#{e.message}")
      return
    end

    grid = reader.sheet('Model')
    unless grid
      UI.messagebox("No 'Model' sheet found in #{File.basename(path)}.")
      return
    end

    sections = parse_model_sections(grid)

    # Read META
    node_radius = 0.0
    rod_radius = 0.0
    if sections['[META]']
      sections['[META]'][:rows].each do |row|
        key = row[0].to_s.strip
        val = row[1]
        case key
        when 'node_radius_m' then node_radius = val.to_f
        when 'rod_radius_m'  then rod_radius  = val.to_f
        end
      end
    end

    # Read NODES
    unless sections['[NODES]']
      UI.messagebox('No [NODES] section found.')
      return
    end
    nodes = []
    sections['[NODES]'][:rows].each do |row|
      next if row[0].nil?
      x = row[1].to_f * M_TO_INCH
      y = row[2].to_f * M_TO_INCH
      z = row[3].to_f * M_TO_INCH
      nodes << [x, y, z]
    end

    # Read MEMBERS
    unless sections['[MEMBERS]']
      UI.messagebox('No [MEMBERS] section found.')
      return
    end
    members = []
    sections['[MEMBERS]'][:rows].each do |row|
      next if row[0].nil?
      a = row[1].to_i
      b = row[2].to_i
      members << { a: a, b: b }
    end

    if nodes.empty?
      UI.messagebox('No nodes found in the file.')
      return
    end

    groups = groups_from_sheet(reader)

    # Build geometry
    model.start_operation('Import Stereo Model', true)
    ents = model.active_entities
    nr_inch = node_radius * M_TO_INCH
    rr_inch = rod_radius * M_TO_INCH
    wireframe = (nr_inch <= 0 && rr_inch <= 0)

    # One way of drawing a rod, whichever mode we are in, so the grouping
    # below does not have to know which it is.
    draw = lambda do |into, i|
      m = members[i]
      next if m.nil? || m[:a] >= nodes.length || m[:b] >= nodes.length
      if rr_inch > 0
        ax, ay, az = nodes[m[:a]]
        bx, by, bz = nodes[m[:b]]
        build_cylinder(into, ax, ay, az, bx, by, bz, rr_inch)
      else
        into.add_line(Geom::Point3d.new(*nodes[m[:a]]),
                      Geom::Point3d.new(*nodes[m[:b]]))
      end
    end

    report = nil
    if groups.empty?
      host = wireframe ? ents : ents.add_group.entities
      if nr_inch > 0
        nodes.each { |x, y, z| build_sphere(host, x, y, z, nr_inch) }
      end
      (0...members.length).each { |i| draw.call(host, i) }
    else
      # Nodes are not owned by any one group -- a joint is where two
      # branches hand load to each other -- so they go in the context the
      # import happens in, beside the groups rather than inside one.
      if nr_inch > 0
        nodes.each { |x, y, z| build_sphere(ents, x, y, z, nr_inch) }
      end
      _made, report = build_group_tree(ents, groups, nodes, members, draw)
      # Whatever the sheet did not place. A rod belongs to exactly one
      # group, and the ones in none are the Stereo tab's Ungrouped set.
      placed = {}
      groups.each { |g| g[:rods].each { |i| placed[i] = true } }
      (0...members.length).each { |i| draw.call(ents, i) unless placed[i] }
    end

    model.commit_operation

    said = ["Imported #{nodes.length} nodes and #{members.length} members.",
            "Node radius: #{node_radius} m, Rod radius: #{rod_radius} m",
            "(#{wireframe ? 'wireframe' : 'solid'} mode)"]
    if report
      said << ''
      said << "#{report[:groups]} group(s), " \
              "#{report[:definitions]} shared component(s) placed as " \
              "#{report[:instances]} instance(s)."
      unless report[:loose_copies].empty?
        said << ''
        said << 'These were listed as copies of a part, but their shape ' \
                'did not line up with the first copy, so each was built on ' \
                'its own rather than placed as an instance somewhere wrong:'
        said << '  ' + report[:loose_copies].join(', ')
      end
    end
    UI.messagebox(said.join("\n"))
  end
end
