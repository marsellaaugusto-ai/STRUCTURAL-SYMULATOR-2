# Drives the SHIPPED import -- a Stereo workbook back into SketchUp --
# against a stub SketchUp, and prints the tree it built as JSON.
#
#   ruby -I tests/ruby/stub tests/ruby/import_harness.rb <model.xlsx>
#
# The workbook is a real one written by the app, read by the extension's
# own XlsxReader, so nothing about the format is simulated here.
require 'json'
require 'sketchup.rb'

PLUGIN = File.expand_path(
  '../../sketchup_plugin/coordinate_coordinator_truss_app_amac', __dir__
)
require File.join(PLUGIN, 'main')

M = CoordinateCoordinatorTrussAppAMAC

model = Sketchup::Model.new
Sketchup.active_model = model
UI.open_path = ARGV[0]
M.import_from_stereo(model)

def describe(ents, depth = 0, out = [])
  ents.each do |e|
    case e
    when Sketchup::Group
      out << { kind: 'group', name: e.name, depth: depth,
               edges: e.entities.count { |c| c.is_a?(Sketchup::Edge) } }
      describe(e.entities, depth + 1, out)
    when Sketchup::ComponentInstance
      out << { kind: 'instance', name: e.name, depth: depth,
               definition: e.definition.name,
               edges: e.definition.entities.count { |c|
                 c.is_a?(Sketchup::Edge)
               },
               # Where this copy actually sits, so a test can check the
               # transformation put it where the model said.
               at: e.definition.entities.select { |c|
                 c.is_a?(Sketchup::Edge)
               }.flat_map { |c|
                 [c.start.position, c.end.position]
               }.map { |p|
                 p.transform(e.transformation).to_a.map { |v| v.round(3) }
               }.sort }
    end
  end
  out
end

loose = model.active_entities.count { |e| e.is_a?(Sketchup::Edge) }
puts JSON.generate(
  tree: describe(model.active_entities),
  loose_edges: loose,
  definitions: model.definitions.map(&:name).sort,
  messages: (UI.messages || [])
)
