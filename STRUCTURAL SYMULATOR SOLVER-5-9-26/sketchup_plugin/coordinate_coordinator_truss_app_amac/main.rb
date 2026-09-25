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
  require File.join(MY_DIR, 'model_export')
  require File.join(MY_DIR, 'pick_tool')
  require File.join(MY_DIR, 'intersections')

  # Writes nodes_m/members in the single-sheet "Model" layout that
  # apps/stereo/stereo_reports.py's import_excel_model reads: a sheet named
  # "Model" with bracketed [NODES] / [MEMBERS] tables. Loads and supports
  # are intentionally left out -- SketchUp geometry has no notion of either;
  # add those inside the Stereo tab after importing.
  def self.export_to_excel(nodes_m, members)
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

    wb.save(path)
    UI.messagebox("Exported #{nodes_m.length} nodes and #{members.length} members to:\n#{path}")
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

    menu = UI.menu('Plugins').add_submenu('Coordinate coordinator truss app AMAC')
    menu.add_item(cmd)
    menu.add_item(auto_cmd)

    toolbar = UI::Toolbar.new('Coordinate coordinator truss app AMAC')
    toolbar.add_item(cmd)
    toolbar.add_item(auto_cmd)
    toolbar.show

    file_loaded(__FILE__)
  end
end
