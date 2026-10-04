# align_options.rb
#
# The two options both "Align by Points" tools share, persisted between
# sessions with Sketchup.write_default / read_default:
#
#   flip_normal -- land the source face-to-BACK instead of face-to-face.
#                  Implemented in align_math.rb as a 180 degrees rotation of
#                  the target frame about its own X axis, so the result stays
#                  a proper rotation and never a mirror.
#   copy        -- "Move" transforms the selection in place; "Copy" leaves the
#                  original untouched and transforms a duplicate.
#
# Exposed three ways, so the user can set them before or during a pick:
#   * "Align Options…" (a UI.inputbox),
#   * two checkable menu items, and
#   * the F / C keys while either tool is active (see align_tool.rb).
require 'sketchup.rb'

module CoordinateCoordinatorTrussAppAMAC
  module AlignOptions
    # Registry/plist section for Sketchup.read_default / write_default.
    SECTION = 'CoordinateCoordinatorTrussAppAMAC_Align'.freeze
    KEY_FLIP = 'flip_normal'.freeze
    KEY_COPY = 'copy_mode'.freeze

    module_function

    # read_default returns whatever was written (true/false here), or the
    # supplied fallback the first time the extension runs. Older builds may
    # have stored the strings 'true'/'false', so both are accepted.
    def flip_normal?
      truthy?(Sketchup.read_default(SECTION, KEY_FLIP, false))
    end

    def flip_normal=(value)
      Sketchup.write_default(SECTION, KEY_FLIP, truthy?(value))
    end

    def copy?
      truthy?(Sketchup.read_default(SECTION, KEY_COPY, false))
    end

    def copy=(value)
      Sketchup.write_default(SECTION, KEY_COPY, truthy?(value))
    end

    def truthy?(value)
      value == true || value.to_s.strip.downcase == 'true'
    end

    def toggle_flip_normal
      self.flip_normal = !flip_normal?
      report
    end

    def toggle_copy
      self.copy = !copy?
      report
    end

    # One-line summary used in status-bar prompts and after a toggle, so the
    # current setting is always visible without opening the dialog.
    def summary
      "Flip normal: #{flip_normal? ? 'ON' : 'off'} | #{copy? ? 'Copy' : 'Move'}"
    end

    def report
      Sketchup.status_text = "Align by Points — #{summary}"
    end

    # Small modal dialog. Returns true when the user accepted it (UI.inputbox
    # returns false on Cancel), so callers can skip re-reporting on cancel.
    def show_dialog
      prompts = ['Flip normal (face-to-back)', 'Move or Copy']
      defaults = [flip_normal? ? 'Yes' : 'No', copy? ? 'Copy' : 'Move']
      lists = ['No|Yes', 'Move|Copy']
      results = UI.inputbox(prompts, defaults, lists, 'Align by Points — Options')
      return false unless results

      self.flip_normal = (results[0] == 'Yes')
      self.copy = (results[1] == 'Copy')
      report
      true
    end
  end
end
