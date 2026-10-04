# sketchup_stub.rb -- just enough of the SketchUp Ruby API to drive
# align_tool.rb in stock Ruby (see tools/test_align_tool.rb).
#
# This is a TEST DOUBLE, not an emulator: it implements only the calls
# align_tool.rb / align_options.rb actually make, and it keeps the
# bookkeeping the tests assert on (which entities were transformed, with
# what, which operations were opened/committed, which message boxes were
# raised). It is never shipped inside the .rbz.
#
# Lengths are plain Floats in inches, as the real API uses internally.

# --- Geom -------------------------------------------------------------------
module Geom
  class Vector3d
    attr_accessor :x, :y, :z

    def initialize(x = 0.0, y = 0.0, z = 0.0)
      @x = x.to_f
      @y = y.to_f
      @z = z.to_f
    end

    def length
      Math.sqrt(@x * @x + @y * @y + @z * @z)
    end

    def to_a
      [@x, @y, @z]
    end
  end

  class Point3d
    attr_accessor :x, :y, :z

    def initialize(x = 0.0, y = 0.0, z = 0.0)
      @x = x.to_f
      @y = y.to_f
      @z = z.to_f
    end

    def to_a
      [@x, @y, @z]
    end

    def -(other)
      Vector3d.new(@x - other.x, @y - other.y, @z - other.z)
    end

    def ==(other)
      other.is_a?(Point3d) && [@x, @y, @z] == [other.x, other.y, other.z]
    end

    def transform(tr)
      tr.transform_point(self)
    end

    def clone
      Point3d.new(@x, @y, @z)
    end
  end

  # 4x4 affine transformation, stored column-major in a 16-element array,
  # exactly like Geom::Transformation.new([...]) expects.
  class Transformation
    attr_reader :m

    def initialize(arg = nil)
      @m = if arg.nil?
             [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
           elsif arg.is_a?(Array) && arg.length == 16
             arg.map(&:to_f)
           else
             raise ArgumentError, "stub only supports a 16-element array, got #{arg.inspect}"
           end
    end

    def at(row, col)
      @m[col * 4 + row]
    end

    def rotation_part
      (0..2).map { |r| (0..2).map { |c| at(r, c) } }
    end

    def origin
      Point3d.new(at(0, 3), at(1, 3), at(2, 3))
    end

    def transform_point(pt)
      Point3d.new(
        at(0, 0) * pt.x + at(0, 1) * pt.y + at(0, 2) * pt.z + at(0, 3),
        at(1, 0) * pt.x + at(1, 1) * pt.y + at(1, 2) * pt.z + at(1, 3),
        at(2, 0) * pt.x + at(2, 1) * pt.y + at(2, 2) * pt.z + at(2, 3)
      )
    end

    # self * other == "apply other first, then self".
    def *(other)
      out = Array.new(16, 0.0)
      (0..3).each do |r|
        (0..3).each do |c|
          sum = 0.0
          (0..3).each { |k| sum += full(r, k) * other.full(k, c) }
          out[c * 4 + r] = sum
        end
      end
      Transformation.new(out)
    end

    def full(row, col)
      return @m[col * 4 + row] if row < 3

      col == 3 ? 1.0 : 0.0
    end

    # Affine inverse: invert the 3x3 linear part by cofactors, then map the
    # translation through it.
    def inverse
      r = rotation_part
      det = r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1]) -
            r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0]) +
            r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])
      raise ZeroDivisionError, 'singular transformation' if det.abs < 1e-15

      inv = (0..2).map do |i|
        (0..2).map do |j|
          a = r[(j + 1) % 3][(i + 1) % 3] * r[(j + 2) % 3][(i + 2) % 3]
          b = r[(j + 1) % 3][(i + 2) % 3] * r[(j + 2) % 3][(i + 1) % 3]
          (a - b) / det
        end
      end
      t = [at(0, 3), at(1, 3), at(2, 3)]
      tr = (0..2).map { |i| -(inv[i][0] * t[0] + inv[i][1] * t[1] + inv[i][2] * t[2]) }
      Transformation.new([inv[0][0], inv[1][0], inv[2][0], 0.0,
                          inv[0][1], inv[1][1], inv[2][1], 0.0,
                          inv[0][2], inv[1][2], inv[2][2], 0.0,
                          tr[0], tr[1], tr[2], 1.0])
    end

    def identity?
      ident = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
      @m.each_with_index.all? { |v, i| (v - ident[i]).abs < 1e-12 }
    end
  end

  class BoundingBox
    def initialize
      @points = []
    end

    def add(thing)
      case thing
      when Point3d then @points << thing
      when BoundingBox then @points.concat(thing.points)
      when Array then thing.each { |t| add(t) }
      else raise ArgumentError, "stub BoundingBox#add got #{thing.class}"
      end
      self
    end

    def points
      @points
    end

    def empty?
      @points.empty?
    end

    def min
      Point3d.new(@points.map(&:x).min, @points.map(&:y).min, @points.map(&:z).min)
    end

    def max
      Point3d.new(@points.map(&:x).max, @points.map(&:y).max, @points.map(&:z).max)
    end

    # Same corner numbering as the real API (bit 0 = x, 1 = y, 2 = z).
    def corner(i)
      lo = min
      hi = max
      Point3d.new(i & 1 == 0 ? lo.x : hi.x,
                  i & 2 == 0 ? lo.y : hi.y,
                  i & 4 == 0 ? lo.z : hi.z)
    end
  end
end

# --- UI ---------------------------------------------------------------------
MB_OK = 0
MB_OKCANCEL = 1
MB_YESNO = 4
IDOK = 1
IDCANCEL = 2
IDYES = 6
IDNO = 7
MF_CHECKED = 2
MF_UNCHECKED = 4
GL_LINES = 1
GL_LINE_STRIP = 3

module UI
  class << self
    # Tests set `queued` to script the user's answers and read `boxes`.
    attr_accessor :boxes, :queued, :inputs

    def reset!
      @boxes = []
      @queued = []
      @inputs = []
    end

    def messagebox(text, type = MB_OK)
      @boxes << text
      answer = @queued.shift
      return answer unless answer.nil?

      type == MB_OKCANCEL ? IDOK : IDOK
    end

    def inputbox(_prompts, defaults, _lists = nil, _title = nil)
      @inputs << defaults
      # `|| defaults` would swallow a queued `false` (the real API's "user
      # cancelled" answer), so the queue is tested for emptiness instead.
      @queued.empty? ? defaults : @queued.shift
    end
  end
  reset!
end

# --- Sketchup ---------------------------------------------------------------
module Sketchup
  class Entity
    attr_accessor :name, :material, :back_material, :layer, :parent
    attr_writer :hidden

    def initialize
      @name = ''
      @attributes = {}
      @hidden = false
      @casts_shadows = true
      @receives_shadows = true
    end

    def hidden?
      @hidden
    end

    def casts_shadows?
      @casts_shadows
    end

    def casts_shadows=(value)
      @casts_shadows = value
    end

    def receives_shadows?
      @receives_shadows
    end

    def receives_shadows=(value)
      @receives_shadows = value
    end

    def valid?
      true
    end

    def set_attribute(dict, key, value)
      (@attributes[dict] ||= {})[key] = value
    end

    def get_attribute(dict, key, default = nil)
      (@attributes[dict] || {}).fetch(key, default)
    end

    def attribute_dictionaries
      return nil if @attributes.empty?

      @attributes.map { |name, pairs| AttributeDictionary.new(name, pairs) }
    end

    def attributes_hash
      @attributes
    end
  end

  class AttributeDictionary
    attr_reader :name

    def initialize(name, pairs)
      @name = name
      @pairs = pairs
    end

    def each_pair(&block)
      @pairs.each_pair(&block)
    end
  end

  class Vertex
    attr_reader :position
    attr_accessor :edges

    def initialize(position)
      @position = position
      @edges = []
    end
  end

  class Edge < Entity
    attr_reader :start, :end
    attr_accessor :faces

    def initialize(start_vertex, end_vertex)
      super()
      @start = start_vertex
      @end = end_vertex
      @faces = []
      start_vertex.edges << self
      end_vertex.edges << self
    end

    def bounds
      Geom::BoundingBox.new.add(@start.position).add(@end.position)
    end
  end

  class Loop
    attr_reader :vertices

    def initialize(vertices, outer)
      @vertices = vertices
      @outer = outer
    end

    def outer?
      @outer
    end
  end

  class Face < Entity
    attr_reader :outer_loop, :loops, :edges

    # points: the outer loop, as an array of Geom::Point3d.
    def initialize(points, inner_points = nil)
      super()
      verts = points.map { |p| Vertex.new(p) }
      @outer_loop = Loop.new(verts, true)
      @loops = [@outer_loop]
      @edges = verts.each_with_index.map do |v, i|
        Edge.new(v, verts[(i + 1) % verts.length]).tap { |e| e.faces = [self] }
      end
      if inner_points
        inner_verts = inner_points.map { |p| Vertex.new(p) }
        @loops << Loop.new(inner_verts, false)
      end
    end

    def bounds
      bb = Geom::BoundingBox.new
      @outer_loop.vertices.each { |v| bb.add(v.position) }
      bb
    end
  end

  class ComponentDefinition
    attr_reader :entities, :name

    def initialize(name = 'definition')
      @name = name
      @entities = Entities.new(self)
    end
  end

  class ComponentInstance < Entity
    attr_accessor :transformation, :definition
    attr_writer :locked

    # transform_log records every transform! call, so tests can assert on
    # exactly what the tool applied.
    attr_reader :transform_log

    def initialize(definition, transformation = Geom::Transformation.new, bounds_points = nil)
      super()
      @definition = definition
      @transformation = transformation
      @locked = false
      @transform_log = []
      @bounds_points = bounds_points || [Geom::Point3d.new(0, 0, 0), Geom::Point3d.new(10, 10, 1)]
    end

    def locked?
      @locked
    end

    def transform!(tr)
      @transform_log << tr
      @transformation = tr * @transformation
      self
    end

    def bounds
      bb = Geom::BoundingBox.new
      @bounds_points.each { |p| bb.add(p.transform(@transformation)) }
      bb
    end

    def entities
      @definition.entities
    end
  end

  class Group < ComponentInstance
    attr_accessor :copies_made

    def copy
      dup_group = Group.new(@definition, @transformation, @bounds_points)
      dup_group.parent = parent
      parent.entities.add_existing(dup_group) if parent
      dup_group
    end
  end

  class Entities
    attr_reader :added, :transform_calls, :items

    def initialize(owner = nil)
      @owner = owner
      @items = []
      @added = []
      @transform_calls = []
    end

    def parent
      @owner
    end

    def each(&block)
      @items.each(&block)
    end

    def add_existing(entity)
      entity.parent = @owner
      @items << entity
      @added << entity
      entity
    end

    def add_group(*_args)
      group = Group.new(ComponentDefinition.new('group'), Geom::Transformation.new)
      add_existing(group)
    end

    def add_instance(definition, transformation)
      add_existing(ComponentInstance.new(definition, transformation))
    end

    def add_face(points)
      add_existing(Face.new(points.map(&:clone)))
    end

    def add_line(p1, p2)
      add_existing(Edge.new(Vertex.new(p1.clone), Vertex.new(p2.clone)))
    end

    def transform_entities(transformation, entities)
      @transform_calls << [transformation, Array(entities)]
      true
    end
  end

  class Selection
    def initialize(items = [])
      @items = items
    end

    def each(&block)
      @items.each(&block)
    end

    def empty?
      @items.empty?
    end

    def clear
      @items = []
    end

    def add(things)
      @items.concat(Array(things))
    end

    def to_a
      @items
    end
  end

  class Model
    attr_accessor :selection, :entities, :edit_transform
    attr_reader :operations, :active_tool

    def initialize
      @entities = Entities.new(self)
      @selection = Selection.new
      @edit_transform = Geom::Transformation.new
      @operations = []
      @active_tool = nil
    end

    def active_entities
      @entities
    end

    def bounds
      Geom::BoundingBox.new.add(Geom::Point3d.new(0, 0, 0))
    end

    def start_operation(name, _disable_ui = false)
      @operations << [:start, name]
      true
    end

    def commit_operation
      @operations << [:commit]
      true
    end

    def abort_operation
      @operations << [:abort]
      true
    end

    def select_tool(tool)
      @active_tool = tool
      true
    end
  end

  # Scripted InputPoint: tests set `next_position` (and optionally
  # `next_vertex`) and the tool's pick() reads it.
  class InputPoint
    attr_accessor :next_position, :next_vertex

    def pick(_view, _x, _y, _ref = nil)
      @picked = self.class.scripted_position || @next_position
      @vertex = self.class.scripted_vertex
      true
    end

    class << self
      attr_accessor :scripted_position, :scripted_vertex
    end

    def valid?
      !@picked.nil?
    end

    def position
      @picked
    end

    def vertex
      @vertex
    end

    def tooltip
      'stub'
    end

    def draw(_view)
      true
    end
  end

  class << self
    attr_accessor :status_text, :vcb_label, :vcb_value, :defaults, :active_model

    def read_default(section, key, default = nil)
      @defaults ||= {}
      @defaults.fetch([section, key], default)
    end

    def write_default(section, key, value)
      @defaults ||= {}
      @defaults[[section, key]] = value
      true
    end

    def format_length(length)
      format('%.3f"', length)
    end

    def version
      '24.0.0'
    end
  end
end

# `require 'sketchup.rb'` is a no-op in the stub world.
$LOADED_FEATURES << 'sketchup.rb'
module Kernel
  alias_method :stub_original_require, :require
  def require(name)
    return true if ['sketchup.rb', 'extensions.rb'].include?(name)

    stub_original_require(name)
  end
end

# Minimal View double: records what the tool drew so draw() is exercised.
class StubView
  attr_reader :model, :draw_calls, :texts
  attr_accessor :tooltip, :drawing_color, :line_width, :line_stipple

  def initialize(model)
    @model = model
    @draw_calls = []
    @texts = []
  end

  def invalidate
    true
  end

  def draw(mode, points)
    @draw_calls << [mode, points]
  end

  def draw_points(points, _size = 6, _style = 0, _color = nil)
    @draw_calls << [:points, points]
  end

  def draw_text(point, text)
    @texts << [point, text]
  end

  def screen_coords(point)
    Geom::Point3d.new(point.x, point.y, 0)
  end

  def pickray(_x, _y)
    nil
  end
end
