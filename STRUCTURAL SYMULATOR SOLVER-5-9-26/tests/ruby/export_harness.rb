# Drives the SHIPPED sketchup_plugin/ export code against a stub SketchUp,
# writes the xlsx it would write, and prints what it produced as JSON so a
# pytest test can both read that workbook with the app's own importer and
# check the intermediate numbers.
#
#   ruby -I tests/ruby/stub tests/ruby/export_harness.rb <how> <scenario> <out.xlsx>
#
# <how> is `select` (the auto-detect-from-selection command) or `pick` (the
# Pick Origin + Nodes tool), the two paths into the exporter.
#
# Each scenario states the world coordinates of its corners LITERALLY rather
# than asking the code under test where they are. That is the whole point of
# the `pick` path: picked points come from SketchUp in world coordinates, and
# if the walk down the model tree got a transformation wrong, the picks and
# the edges land in different places and no member is found. Deriving the
# picks from the same walk would hide exactly that.
require 'json'
require 'sketchup.rb'

PLUGIN = File.expand_path(
  '../../sketchup_plugin/coordinate_coordinator_truss_app_amac', __dir__
)
require File.join(PLUGIN, 'main')

M = CoordinateCoordinatorTrussAppAMAC

def pt(x, y, z) = Geom::Point3d.new(x, y, z)
def edge(a, b) = Sketchup::Edge.new(pt(*a), pt(*b))
def move(dx, dy, dz) = Geom::Transformation.new([dx, dy, dz])

# A right triangle in the XY plane, 100 x 100 inches: three edges sharing
# their corner vertices by position. Returns [edges, corners].
def triangle(ox = 0, oy = 0, oz = 0)
  a = [ox, oy, oz]
  b = [ox + 100, oy, oz]
  c = [ox, oy + 100, oz]
  [[edge(a, b), edge(b, c), edge(c, a)], [a, b, c]]
end

# [model, selection, world_corners]
def scenario(name)
  case name
  # Nothing is grouped: the case that worked before groups were followed,
  # kept as the proof that following them changed nothing here.
  when 'flat'
    es, corners = triangle
    [Sketchup::Model.new(es), es, corners]

  # One group holding the whole truss, moved away from the origin. This is
  # the case that used to export nodes and no members at all. The corners
  # are where the modeller SEES them, 1000 inches along x.
  when 'grouped'
    es, = triangle
    g = Sketchup::Group.new(es, move(1000, 0, 0), 'Roof')
    [Sketchup::Model.new([g]), [g],
     [[1000, 0, 0], [1100, 0, 0], [1000, 100, 0]]]

  # A group inside a group, each with its own offset: the two
  # transformations have to compose, and the nesting has to survive.
  when 'nested'
    es, = triangle
    inner = Sketchup::Group.new(es, move(0, 200, 0), 'Bay')
    outer = Sketchup::Group.new([inner], move(1000, 0, 0), 'Roof')
    [Sketchup::Model.new([outer]), [outer],
     [[1000, 200, 0], [1100, 200, 0], [1000, 300, 0]]]

  # Two instances of ONE definition, at two places: the same local geometry
  # has to land twice, in two different spots, under two rows.
  when 'components'
    es, = triangle
    defn = Sketchup::ComponentDefinition.new(es, 'Truss A')
    i1 = Sketchup::ComponentInstance.new(defn, move(0, 0, 0))
    i2 = Sketchup::ComponentInstance.new(defn, move(0, 500, 0))
    [Sketchup::Model.new([i1, i2]), [i1, i2],
     [[0, 0, 0], [100, 0, 0], [0, 100, 0],
      [0, 500, 0], [100, 500, 0], [0, 600, 0]]]

  # An instance that is ROTATED, not merely moved: a quarter turn about z
  # and 500 along x, so (x, y, z) lands at (500 - y, x, z). A walk that
  # only carried translations would put every corner somewhere else.
  when 'rotated'
    es, = triangle
    defn = Sketchup::ComponentDefinition.new(es, 'Truss A')
    tr = Geom::Transformation.new([[0, -1, 0], [1, 0, 0], [0, 0, 1]],
                                  [500, 0, 0])
    inst = Sketchup::ComponentInstance.new(defn, tr, 'Turned')
    [Sketchup::Model.new([inst]), [inst],
     [[500, 0, 0], [500, 100, 0], [400, 0, 0]]]

  # A group selected together with loose edges, and the group is moved so
  # its triangle does NOT coincide with the loose one: six nodes, not three.
  # This used to export the loose three and say nothing about the rest.
  when 'mixed'
    loose, loose_corners = triangle
    inner, = triangle
    g = Sketchup::Group.new(inner, move(0, 500, 0), 'Roof')
    [Sketchup::Model.new(loose + [g]), loose + [g],
     loose_corners + [[0, 500, 0], [100, 500, 0], [0, 600, 0]]]

  # A face is in the selection, not its edges: it contributes its boundary.
  when 'face'
    es, corners = triangle
    f = Sketchup::Face.new(es)
    [Sketchup::Model.new(es + [f]), [f], corners]

  # The user is INSIDE a group, so the context's own transformation is not
  # the identity. The picked points are in world coordinates either way,
  # which is what used to find no members here.
  when 'inside_group'
    es, = triangle
    [Sketchup::Model.new(es, es, move(1000, 0, 0)), es,
     [[1000, 0, 0], [1100, 0, 0], [1000, 100, 0]]]

  # Three instances of ONE definition: the case this is all for. They
  # arrive as three groups sharing one component name.
  when 'three_copies'
    es, = triangle
    defn = Sketchup::ComponentDefinition.new(es, 'Truss A')
    made = (0..2).map do |k|
      Sketchup::ComponentInstance.new(defn, move(0, 400 * k, 0))
    end
    [Sketchup::Model.new(made), made,
     (0..2).flat_map { |k| [[0, 400 * k, 0], [100, 400 * k, 0],
                            [0, 100 + 400 * k, 0]] }]

  # Two instances of one definition at DIFFERENT SIZES. Same drawing on
  # screen, different steel: they must not arrive as one part.
  when 'scaled_copies'
    es, = triangle
    defn = Sketchup::ComponentDefinition.new(es, 'Truss A')
    full = Sketchup::ComponentInstance.new(defn, move(0, 0, 0))
    half = Sketchup::ComponentInstance.new(
      defn, Geom::Transformation.new([[0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5]],
                                     [0, 400, 0]))
    [Sketchup::Model.new([full, half]), [full, half],
     [[0, 0, 0], [100, 0, 0], [0, 100, 0],
      [0, 400, 0], [50, 400, 0], [0, 450, 0]]]

  # A MIRRORED instance is the same part built the other way round, so it
  # keeps the component -- the Stereo tab marks the handedness itself.
  when 'mirrored_copies'
    es, = triangle
    defn = Sketchup::ComponentDefinition.new(es, 'Truss A')
    right = Sketchup::ComponentInstance.new(defn, move(0, 0, 0))
    left = Sketchup::ComponentInstance.new(
      defn, Geom::Transformation.new([[1, 0, 0], [0, -1, 0], [0, 0, 1]],
                                     [0, 400, 0]))
    [Sketchup::Model.new([right, left]), [right, left],
     [[0, 0, 0], [100, 0, 0], [0, 100, 0],
      [0, 400, 0], [100, 400, 0], [0, 300, 0]]]

  # A GROUP copied twice is NOT a shared part: SketchUp groups are unique,
  # editing one does not touch the other. They arrive as two plain groups.
  when 'copied_groups'
    a, = triangle
    b, = triangle
    [Sketchup::Model.new([Sketchup::Group.new(a, move(0, 0, 0), 'Bay'),
                          Sketchup::Group.new(b, move(0, 400, 0), 'Bay')]),
     nil,
     [[0, 0, 0], [100, 0, 0], [0, 100, 0],
      [0, 400, 0], [100, 400, 0], [0, 500, 0]]]

  # A group NESTED INSIDE a definition. Its contents are one entity shared
  # by every instance, so the bay inside copy 1 and the bay inside copy 2
  # are the same part -- and the instance itself holds no rods of its own,
  # so it is a branch rather than a part.
  when 'nested_in_component'
    es, = triangle
    bay = Sketchup::Group.new(es, move(0, 0, 0), 'Bay')
    defn = Sketchup::ComponentDefinition.new([bay], 'Truss A')
    made = (0..1).map do |k|
      Sketchup::ComponentInstance.new(defn, move(0, 400 * k, 0))
    end
    [Sketchup::Model.new(made), made,
     (0..1).flat_map { |k| [[0, 400 * k, 0], [100, 400 * k, 0],
                            [0, 100 + 400 * k, 0]] }]

  # One definition holding TWO sub-groups that share a name. They are
  # different steel and must not come back as one part just because
  # "Truss A / Bay" reads the same for both.
  when 'twin_bays'
    left_edges, = triangle(0, 0, 0)
    right_edges, = triangle(300, 0, 0)
    defn = Sketchup::ComponentDefinition.new(
      [Sketchup::Group.new(left_edges, move(0, 0, 0), 'Bay'),
       Sketchup::Group.new(right_edges, move(0, 0, 0), 'Bay')], 'Truss A')
    inst = Sketchup::ComponentInstance.new(defn, move(0, 0, 0))
    [Sketchup::Model.new([inst]), [inst],
     [[0, 0, 0], [100, 0, 0], [0, 100, 0],
      [300, 0, 0], [400, 0, 0], [300, 100, 0]]]

  # Nothing in the group at all.
  when 'empty_group'
    g = Sketchup::Group.new([], move(0, 0, 0), 'Empty')
    [Sketchup::Model.new([g]), [g], []]
  else
    raise ArgumentError, "unknown scenario #{name}"
  end
end

how, name, out = ARGV
model, selection, corners = scenario(name)
selection ||= model.active_entities
model.selection = selection
Sketchup.active_model = model
UI.save_path = out

case how
when 'select'
  M.autodetect_and_export(model)
when 'pick'
  # The clicks themselves are UI; what is under test is everything the tool
  # does with them once Enter is pressed.
  picks = corners.map { |c| pt(*c) }
  tool = M::PickNodesTool.new
  tool.instance_variable_set(:@origin, picks.first)
  tool.instance_variable_set(:@nodes, picks[1..] || [])
  tool.send(:finish, Sketchup::View.new(model))
else
  raise ArgumentError, "unknown how #{how}"
end

base = model.edit_transform
segs = how == 'select' ? M.collect_segments(model.selection, base)
                       : M.world_segments(model.active_entities, base)
puts JSON.generate(
  segments: segs.length,
  # What the Groups sheet will say, straight from the library, so a
  # failure says whether the model tree or the workbook was wrong.
  rows: M.group_rows(segs.map { |_, _, path| path }).map { |g|
    { name: g[:name], parent: g[:parent], component: g[:component],
      rods: g[:rods].length }
  },
  # Where the walk says each edge is, in world coordinates, to one
  # thousandth of an inch -- the numbers the scenario states literally.
  world: segs.map { |p0, p1, _| [p0.to_a, p1.to_a].map { |c| c.map { |v| v.round(3) } } },
  paths: segs.map { |_, _, path| path.map { |_, n| n } },
  messages: (UI.messages || []),
  wrote: File.exist?(out.to_s)
)
