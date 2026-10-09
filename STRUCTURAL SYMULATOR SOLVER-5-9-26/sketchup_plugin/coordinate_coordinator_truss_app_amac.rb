# coordinate_coordinator_truss_app_amac.rb -- top-level extension loader.
# Goes in SketchUp's Plugins/ folder alongside the
# coordinate_coordinator_truss_app_amac/ subfolder (installing the .rbz via
# Extension Manager does this for you).
require 'sketchup.rb'
require 'extensions.rb'

module CoordinateCoordinatorTrussAppAMAC
  # Force UTF-8 on __FILE__ before using it for path work: Ruby doesn't
  # reliably apply the right encoding to __FILE__/__dir__ on Windows, which
  # can otherwise raise on non-English install paths
  # (rubocop-sketchup: SketchupSuggestions/FileEncoding).
  loader_file = __FILE__.dup
  loader_file.force_encoding('UTF-8') if loader_file.respond_to?(:force_encoding)
  PATH = File.dirname(loader_file)

  unless file_loaded?(__FILE__)
    # No ".rb" extension: Extension Warehouse encrypts extensions to .rbe,
    # and omitting the extension lets SketchUp find either .rb or .rbe.
    ex = SketchupExtension.new('Coordinate coordinator truss app AMAC', File.join(PATH, 'coordinate_coordinator_truss_app_amac', 'main'))
    ex.description = 'Two-way bridge to the Structural Simulator Stereo ' \
                      '(space-truss) app. Pick an origin point and node points ' \
                      '(vertices or line intersections), or auto-detect them from ' \
                      'a selection, and export them with member connectivity -- with ' \
                      'the groups they sit in, and with components arriving as shared ' \
                      'parts -- to an Excel file the Stereo tab imports, or go the ' \
                      'other way and build SketchUp geometry from a model the Stereo ' \
                      'tab exported, with its groups, its shared components and its ' \
                      'piece marks.'
    # 0.5.0 closes the loop: "Import from Stereo…" now rebuilds the
    # model's own organisation instead of a flat heap of edges. Groups
    # arrive as groups the Outliner shows, nested as they were; groups
    # that are copies of one part arrive as instances of ONE component,
    # so editing the definition still changes every copy; and each
    # container is named after the piece mark it carries, which is the
    # thing a fabricator reads off the model.
    #
    # 0.4.0 maps SketchUp's two container kinds onto the Stereo tab's,
    # one to one. A GROUP is unique -- editing one does not touch another
    # -- so it arrives as a group. A COMPONENT INSTANCE is a placement of
    # a shared definition, one drawing built as many times as it is
    # placed, so every instance of one definition arrives carrying the
    # same component name and the Stereo tab sizes them as one part. A
    # definition placed at two SIZES is two parts, and says so.
    #
    # 0.3.0 followed groups and components on the way OUT. Until it, both
    # export paths read only the edges lying loose in the current context,
    # so a truss that had been grouped -- the normal way to model one --
    # exported with no members and no warning. The groups themselves now
    # travel too, as the Stereo tab's own nested groups.
    #
    # 0.2.0 added "Import from Stereo…" (model_import.rb + xlsx_reader.rb).
    # The 0.1.0 .rbz that shipped before this was built by hand and left
    # both of those files out, so the command it advertised raised
    # LoadError; tools/build_release.py now assembles and verifies the
    # archive so that cannot recur.
    ex.version = '0.5.0'
    ex.creator = 'Augusto'
    ex.copyright = Time.now.year.to_s
    Sketchup.register_extension(ex, true)
    file_loaded(__FILE__)
  end
end
