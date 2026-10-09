# A small stand-in for the parts of the SketchUp Ruby API that
# sketchup_plugin/ touches, so the SHIPPED extension code can be run and
# tested outside SketchUp. Nothing here is a copy of SketchUp's own
# implementation: these are plain-Ruby objects with the same names and the
# same documented behaviour, written from the public API contract -- the
# equivalent of a test double for any other library.
#
# The one piece with real arithmetic in it is Geom::Transformation, and the
# contract that matters is the composition order: (A * B) applied to a point
# must equal A applied to (B applied to it), which is what makes the
# standard `transformation * instance.transformation` recursion down a model
# tree produce world coordinates.
module Geom
  class Vector3d
    attr_accessor :x, :y, :z
    def initialize(x = 0.0, y = 0.0, z = 0.0)
      @x = x.to_f
      @y = y.to_f
      @z = z.to_f
    end

    def dot(o) = @x * o.x + @y * o.y + @z * o.z
    def length = Math.sqrt(dot(self))
    def to_a = [@x, @y, @z]

    def cross(o)
      Vector3d.new(@y * o.z - @z * o.y, @z * o.x - @x * o.z,
                   @x * o.y - @y * o.x)
    end

    def normalize
      n = length
      n < 1e-12 ? Vector3d.new(0, 0, 0) : Vector3d.new(@x / n, @y / n, @z / n)
    end

    def -(o) = Vector3d.new(@x - o.x, @y - o.y, @z - o.z)
    def +(o) = Vector3d.new(@x + o.x, @y + o.y, @z + o.z)
  end

  class Point3d
    attr_accessor :x, :y, :z
    def initialize(x = 0.0, y = 0.0, z = 0.0)
      @x = x.to_f
      @y = y.to_f
      @z = z.to_f
    end

    def -(other)
      if other.is_a?(Point3d)
        Vector3d.new(@x - other.x, @y - other.y, @z - other.z)
      else
        Point3d.new(@x - other.x, @y - other.y, @z - other.z)
      end
    end

    def transform(tr) = tr.apply(self)
    def to_a = [@x, @y, @z]
  end

  # An affine transformation held as a 3x3 linear part plus a translation.
  class Transformation
    attr_reader :m, :t

    # Transformation.new                            -> identity
    # Transformation.new([dx, dy, dz])              -> translation
    # Transformation.new(m_3x3, [dx, dy, dz])       -> general affine
    # Transformation.new(xaxis, yaxis, zaxis, origin) -> a frame, which is
    #   SketchUp's own four-argument form: the three axes become the
    #   matrix COLUMNS, so the transformation carries frame coordinates
    #   out into the space the axes are expressed in.
    def initialize(a = nil, b = nil, c = nil, d = nil)
      if !c.nil?
        @m = [[a.x, b.x, c.x], [a.y, b.y, c.y], [a.z, b.z, c.z]]
        @t = [d.x, d.y, d.z]
      elsif a.nil?
        @m = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        @t = [0.0, 0.0, 0.0]
      elsif b.nil?
        @m = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        @t = a.respond_to?(:x) ? [a.x, a.y, a.z] : a.map(&:to_f)
      else
        @m = a.map { |r| r.map(&:to_f) }
        @t = b.respond_to?(:x) ? [b.x, b.y, b.z] : b.map(&:to_f)
      end
    end

    def self.translation(v)
      Transformation.new(v.respond_to?(:x) ? [v.x, v.y, v.z] : v)
    end

    # The inverse of an affine map: invert the linear part by cofactors,
    # then carry the translation back through it.
    def inverse
      a, b, c = @m[0]
      d, e, f = @m[1]
      g, h, i = @m[2]
      det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
      raise 'singular transformation' if det.abs < 1e-15
      inv = [[(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
             [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
             [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]]
      t = (0..2).map { |r| -(0..2).sum { |k| inv[r][k] * @t[k] } }
      Transformation.new(inv, t)
    end

    def apply(p)
      Point3d.new(@m[0][0] * p.x + @m[0][1] * p.y + @m[0][2] * p.z + @t[0],
                  @m[1][0] * p.x + @m[1][1] * p.y + @m[1][2] * p.z + @t[1],
                  @m[2][0] * p.x + @m[2][1] * p.y + @m[2][2] * p.z + @t[2])
    end

    # self * other == "apply other, then self".
    def *(other)
      m = (0..2).map do |i|
        (0..2).map { |j| (0..2).sum { |k| @m[i][k] * other.m[k][j] } }
      end
      t = (0..2).map do |i|
        (0..2).sum { |k| @m[i][k] * other.t[k] } + @t[i]
      end
      Transformation.new(m, t)
    end
  end

  class BoundingBox
    def initialize
      @pts = []
    end

    def add(p) = @pts << p
    def empty? = @pts.empty?

    def min
      Point3d.new(@pts.map(&:x).min || 0.0,
                  @pts.map(&:y).min || 0.0,
                  @pts.map(&:z).min || 0.0)
    end

    def max
      Point3d.new(@pts.map(&:x).max || 0.0,
                  @pts.map(&:y).max || 0.0,
                  @pts.map(&:z).max || 0.0)
    end
  end
end

module Sketchup
  @next_pid = 0
  class << self
    def next_pid
      @next_pid += 1
    end

    attr_accessor :active_model, :status_text
  end

  class Entity
    attr_accessor :name, :persistent_id
    def initialize(name = '')
      @name = name
      @persistent_id = Sketchup.next_pid
    end
  end

  class Vertex
    attr_accessor :position
    def initialize(position)
      @position = position
    end
  end

  # A real Entities collection, because the import side BUILDS one: it
  # adds groups, places instances and moves geometry about. The export
  # side only ever reads, and a plain Array answered that, which is why
  # the scenarios still hand one over -- anything that responds to `each`
  # works where only reading happens.
  class Entities
    include Enumerable
    attr_accessor :owner

    def initialize(items = [], owner = nil)
      @items = items.to_a
      @owner = owner
    end

    def each(&blk) = @items.each(&blk)
    def to_a = @items.dup
    def length = @items.length
    def size = @items.length
    def empty? = @items.empty?
    def [](i) = @items[i]
    def <<(e)
      @items << e
      e
    end

    def remove(e) = @items.delete(e)

    def add_line(p0, p1) = self << Edge.new(p0, p1)
    def add_face(*_pts) = nil

    def add_group(*_args)
      g = Group.new(Entities.new, Geom::Transformation.new)
      g.parent_entities = self
      self << g
    end

    def add_instance(definition, transformation)
      i = ComponentInstance.new(definition, transformation)
      i.parent_entities = self
      self << i
    end

    # Moves the geometry itself, which is what SketchUp's own does -- the
    # points change, no container is wrapped round them.
    def transform_entities(tr, ents)
      ents.to_a.each do |e|
        if e.is_a?(Edge)
          e.start.position = e.start.position.transform(tr)
          e.end.position = e.end.position.transform(tr)
        elsif e.respond_to?(:transformation)
          e.transformation = tr * e.transformation
        end
      end
      true
    end
  end

  class Edge < Entity
    attr_reader :start, :end
    def initialize(p0, p1, name = '')
      super(name)
      @start = Vertex.new(p0)
      @end = Vertex.new(p1)
    end
  end

  class Face < Entity
    attr_reader :edges
    def initialize(edges, name = '')
      super(name)
      @edges = edges
    end
  end

  class Group < Entity
    attr_reader :entities
    attr_accessor :transformation, :parent_entities
    def initialize(entities, transformation = Geom::Transformation.new, name = '')
      super(name)
      @entities = entities.is_a?(Entities) ? entities : Entities.new(entities)
      @entities.owner = self
      @transformation = transformation
    end

    # SketchUp's own: the group's contents become a definition, and an
    # instance of it takes the group's place with the group's transform.
    def to_component
      definition = ComponentDefinition.new(@entities, @name)
      Sketchup.active_model&.definitions&.add(definition)
      inst = ComponentInstance.new(definition, @transformation, @name)
      if @parent_entities
        @parent_entities.remove(self)
        inst.parent_entities = @parent_entities
        @parent_entities << inst
      end
      inst
    end
  end

  class ComponentDefinition < Entity
    attr_reader :entities
    def initialize(entities, name = '')
      super(name)
      @entities = entities.is_a?(Entities) ? entities : Entities.new(entities)
      @entities.owner = self
    end
  end

  class ComponentInstance < Entity
    attr_reader :definition
    attr_accessor :transformation, :parent_entities
    def initialize(definition, transformation = Geom::Transformation.new, name = '')
      super(name)
      @definition = definition
      @transformation = transformation
    end

    def entities = @definition.entities
  end

  class Definitions
    include Enumerable
    def initialize = @items = []
    def each(&blk) = @items.each(&blk)
    def add(d)
      @items << d
      d
    end
    def length = @items.length
  end

  class Model
    attr_accessor :selection, :edit_transform
    attr_reader :tools_selected, :definitions, :operations
    def initialize(entities = [], selection = nil, edit_transform = nil)
      @active_entities = entities.is_a?(Entities) ? entities
                                                  : Entities.new(entities)
      @selection = selection || @active_entities
      @edit_transform = edit_transform || Geom::Transformation.new
      @tools_selected = []
      @definitions = Definitions.new
      @operations = []
    end

    def active_entities = @active_entities

    def active_entities=(v)
      @active_entities = v.is_a?(Entities) ? v : Entities.new(v)
    end

    def start_operation(name, *_rest)
      @operations << [:start, name]
      true
    end

    def commit_operation
      @operations << [:commit]
      true
    end

    def select_tool(tool)
      @tools_selected << tool
      nil
    end
  end

  # Picking is the one thing a test cannot drive: it needs a cursor over a
  # viewport. The tests set the tool's points directly and exercise
  # everything it does with them afterwards, so this only has to exist.
  class InputPoint
    attr_accessor :position
    def valid? = !@position.nil?
    def pick(*) = nil
    def draw(*) = nil
  end

  class View
    attr_reader :model
    def initialize(model)
      @model = model
    end

    def invalidate = nil
    def draw_points(*) = nil
  end
end

module UI
  class << self
    # Every message the code under test tried to show the user, so a test
    # can assert on what it said instead of on what it silently did not.
    attr_reader :messages

    def messagebox(text, *)
      (@messages ||= []) << text.to_s
      nil
    end

    def savepanel(*) = @save_path
    def openpanel(*) = @open_path
    attr_accessor :save_path, :open_path

    def menu(*) = DummyMenu.new
  end

  class DummyMenu
    def add_submenu(*) = self
    def add_item(*) = nil
    def add_separator = nil
  end

  class Command
    attr_accessor :tooltip, :status_bar_text, :small_icon, :large_icon
    def initialize(_name, &blk)
      @blk = blk
    end
  end

  class Toolbar
    def initialize(*); end
    def add_item(*) = nil
    def show = nil
  end
end

# main.rb guards its menu/toolbar wiring with file_loaded?; saying "already
# loaded" keeps the require to the parts under test.
def file_loaded?(_path) = true
def file_loaded(_path) = nil
