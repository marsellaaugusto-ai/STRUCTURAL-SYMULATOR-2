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
                      'a selection, and export them with member connectivity to an ' \
                      'Excel file the Stereo tab imports -- or go the other way and ' \
                      'build SketchUp geometry from a model the Stereo tab exported. ' \
                      'Also includes "Align by Points": rotate and move faces, ' \
                      'groups or components onto an inclined target by picking ' \
                      '1-3 pairs of matching points.'
    # 0.2.0 adds "Import from Stereo…" (model_import.rb + xlsx_reader.rb).
    # The 0.1.0 .rbz that shipped before this was built by hand and left
    # both of those files out, so the command it advertised raised
    # LoadError; tools/build_rbz.py now assembles and verifies the
    # archive so that cannot recur.
    # 0.3.0 adds the "Align by Points" pair of tools (align_math.rb,
    # align_options.rb, align_tool.rb) -- rigid rotate+move of a selection
    # onto a target plane from 1-3 picked point pairs.
    ex.version = '0.3.0'
    ex.creator = 'Augusto'
    ex.copyright = Time.now.year.to_s
    Sketchup.register_extension(ex, true)
    file_loaded(__FILE__)
  end
end
