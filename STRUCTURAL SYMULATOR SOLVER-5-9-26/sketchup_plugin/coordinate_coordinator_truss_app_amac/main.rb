# main.rb -- menu wiring + the Excel writer entry point.
require 'sketchup.rb'

module CoordinateCoordinatorTrussAppAMAC
  # Force UTF-8 on __FILE__ before using it for path work: Ruby doesn't
  # reliably apply the right encoding to __FILE__/__dir__ on Windows, which
  # can otherwise raise on non-English install paths
  # (rubocop-sketchup: SketchupSuggestions/FileEncoding). Computed once as a
  # namespaced constant (not a top-level local) so it's usable everywhere
  # below, including inside the UI::Command blocks further down.
  main_file = __FILE__.dup
  main_file.force_encoding('UTF-8') if main_file.respond_to?(:force_encoding)
  MY_DIR = File.dirname(main_file)

  require File.join(MY_DIR, 'xlsx_writer')
  require File.join(MY_DIR, 'xlsx_reader')
  require File.join(MY_DIR, 'model_export')
  require File.join(MY_DIR, 'model_import')
  require File.join(MY_DIR, 'pick_tool')
  require File.join(MY_DIR, 'intersections')

  # Writes nodes_m/members in the "Model" layout that
  # apps/stereo/stereo_reports.py's import_excel_model reads: a sheet named
  # "Model" with bracketed [NODES] / [MEMBERS] tables. Loads and supports
  # are intentionally left out -- SketchUp geometry has no notion of either;
  # add those inside the Stereo tab after importing.
  #
  # `groups`, when there is anything to say, adds the second sheet the
  # Stereo tab already reads (apps/stereo/stereo_groups_excel.py): one row
  # per group, nested by `parent`, listing its rods as ranges, and naming
  # the fabricated part it is a copy of. That is how the groups and
  # components someone modelled with arrive as the Stereo tab's own groups
  # and components instead of being flattened away on the trip across.
  #
  # The `component` column is the one that carries SHARING. SketchUp's two
  # container kinds mean different things and map one to one: a group is
  # unique, so it arrives as a group; a component instance is a placement
  # of a shared definition, so every instance of one definition arrives
  # carrying the same component name, and the Stereo tab then sizes them
  # together and gives them one piece mark. See model_export's
  # `component_key` for what counts as the same part and what does not.
  #
  # Only the columns that say WHERE a rod belongs are written. The section
  # columns of that sheet are left out entirely, and a cell the sheet does
  # not have reads as blank, which means "leave this rod as it is" -- so
  # importing changes the grouping and nothing else. SketchUp geometry
  # knows nothing about steel sections, and a column of guessed defaults
  # would overwrite real ones on the way in.
  def self.export_to_excel(nodes_m, members, groups = nil)
    path = UI.savepanel('Export Stereo Model', Dir.pwd, 'stereo_model.xlsx')
    return unless path
    path += '.xlsx' unless path.downcase.end_with?('.xlsx')

    wb = XlsxWriter.new
    ws = wb.add_sheet('Model')
    row = 1
    ws.set(row, 1, 'STEREO MODEL DATA — for Import from Excel (do not reorder columns)')
    row += 2

    ws.set(row, 1, '[NODES]'); row += 1
    ws.set(row, 1, 'idx'); ws.set(row, 2, 'x_m'); ws.set(row, 3, 'y_m'); ws.set(row, 4, 'z_m')
    row += 1
    nodes_m.each_with_index do |(x, y, z), i|
      ws.set(row, 1, i); ws.set(row, 2, x); ws.set(row, 3, y); ws.set(row, 4, z)
      row += 1
    end
    row += 1

    ws.set(row, 1, '[MEMBERS]'); row += 1
    headers = %w[idx a b conn E_GPa A_cm2 I_cm4 J_cm4 Fy_MPa Fu_MPa K r_gyr_cm role]
    headers.each_with_index { |h, c| ws.set(row, c + 1, h) }
    row += 1
    members.each_with_index do |m, i|
      ws.set(row, 1, i)
      ws.set(row, 2, m[:a])
      ws.set(row, 3, m[:b])
      ws.set(row, 4, 'pin')
      ws.set(row, 5, 200.0)   # E_GPa  -- structural steel default
      ws.set(row, 6, 20.0)    # A_cm2
      ws.set(row, 7, 400.0)   # I_cm4
      ws.set(row, 8, 400.0)   # J_cm4
      ws.set(row, 9, 235.0)   # Fy_MPa
      ws.set(row, 10, 360.0)  # Fu_MPa
      ws.set(row, 11, 1.0)    # K
      ws.set(row, 12, 4.0)    # r_gyr_cm
      ws.set(row, 13, '')     # role
      row += 1
    end

    write_groups_sheet(wb, groups) if groups && !groups.empty?

    wb.save(path)
    parts = (groups || []).map { |g| g[:component] }.compact.uniq.length
    UI.messagebox("Exported #{nodes_m.length} nodes, #{members.length} " \
                  "members and #{(groups || []).length} group(s)" \
                  "#{parts.zero? ? '' : ", #{parts} of them shared part(s)"}" \
                  " to:\n#{path}")
  end

  # The "Groups" sheet. Header names are read by name on the way in, so the
  # column order here is for the reader's benefit only; the one thing that
  # is load-bearing is that the header row begins with "id".
  def self.write_groups_sheet(wb, groups)
    ws = wb.add_sheet('Groups')
    row = 1
    ws.set(row, 1, 'GROUPS — the groups and components this model was ' \
                   'built from. Nesting is in the "parent" column; rows ' \
                   'sharing a "component" are copies of one part.')
    row += 2
    %w[id name parent rods component].each_with_index do |h, c|
      ws.set(row, c + 1, h)
    end
    row += 1
    groups.each do |g|
      ws.set(row, 1, g[:id])
      ws.set(row, 2, g[:name])
      ws.set(row, 3, g[:parent])     # nil -> an empty cell -> a top-level group
      ws.set(row, 4, rods_to_ranges(g[:rods]))
      ws.set(row, 5, g[:component])  # nil -> blank -> not a copy of anything
      row += 1
    end
  end

  unless file_loaded?(__FILE__)
    cmd = UI::Command.new('Pick Origin + Nodes…') do
      Sketchup.active_model.select_tool(PickNodesTool.new)
    end
    cmd.tooltip = 'Pick Origin + Nodes…'
    cmd.status_bar_text = 'Click to set the origin, then click nodes. Enter exports to Excel.'
    cmd.small_icon = File.join(MY_DIR, 'icons', 'pick_nodes_small.png')
    cmd.large_icon = File.join(MY_DIR, 'icons', 'pick_nodes_large.png')

    auto_cmd = UI::Command.new('Auto-Detect Nodes + Rods from Selection') do
      autodetect_and_export(Sketchup.active_model)
    end
    auto_cmd.tooltip = 'Auto-Detect Nodes + Rods from Selection'
    auto_cmd.status_bar_text =
      'Select edges/faces first. Finds every corner and line-line crossing, ' \
      'ignores faces, and exports (origin = current context\'s 0,0,0).'
    auto_cmd.small_icon = File.join(MY_DIR, 'icons', 'autodetect_small.png')
    auto_cmd.large_icon = File.join(MY_DIR, 'icons', 'autodetect_large.png')

    import_cmd = UI::Command.new('Import from Stereo…') do
      import_from_stereo(Sketchup.active_model)
    end
    import_cmd.tooltip = 'Import from Stereo…'
    import_cmd.status_bar_text =
      'Open an XLSX exported by the Stereo tab and build 3D geometry ' \
      '(wireframe or solid, depending on node/rod radius in [META]).'
    import_cmd.small_icon = File.join(MY_DIR, 'icons', 'autodetect_small.png')
    import_cmd.large_icon = File.join(MY_DIR, 'icons', 'autodetect_large.png')

    menu = UI.menu('Plugins').add_submenu('Coordinate coordinator truss app AMAC')
    menu.add_item(cmd)
    menu.add_item(auto_cmd)
    menu.add_separator
    menu.add_item(import_cmd)

    toolbar = UI::Toolbar.new('Coordinate coordinator truss app AMAC')
    toolbar.add_item(cmd)
    toolbar.add_item(auto_cmd)
    toolbar.add_item(import_cmd)
    toolbar.show

    file_loaded(__FILE__)
  end
end
