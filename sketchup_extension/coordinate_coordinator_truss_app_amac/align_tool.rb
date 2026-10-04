# align_tool.rb
#
# "Align by Points" -- two tools that move a selection onto a target by
# picking matching point pairs, instead of by eyeballing rotations:
#
#   AlignFaceToFaceTool    -- source may be loose faces/edges, groups or
#                             component instances (e.g. drop a flat truss
#                             onto an inclined roof plane).
#   AlignGroupByNodesTool  -- source restricted to groups and component
#                             instances, picked by their nodes; only the
#                             instance transformation changes, never the
#                             geometry inside it.
#
# Both share this base class, the math in align_math.rb and the options in
# align_options.rb. The only differences are which entity types they accept
# and the wording of their prompts.
#
# Interaction (state machine):
#   phase :source -> pick 1..3 source points A1..A3
#                    (3rd pick, or Enter, advances to the target phase)
#   phase :target -> pick the same number of target points B1..B3
#                    (last pick, or Enter, applies the alignment)
#   Esc            -> clears the current picks; Esc again exits the tool
#   VCB            -> type 1, 2 or 3 to fix the number of point pairs
#   F / C          -> toggle Flip normal / Copy mode without leaving the tool
#
# Coordinate spaces: Sketchup::InputPoint#position is in MODEL space, while
# instance.transformation and entities.transform_entities work in the space
# of the current editing context. The two coincide at the top level, so the
# model-space transformation is conjugated by model.edit_transform before it
# is applied (see #local_transformation) -- otherwise the feature would be
# wrong whenever the user is inside a group or component.
require 'sketchup.rb'

module CoordinateCoordinatorTrussAppAMAC
  class AlignByPointsTool
    # Marker/ghost styling. Point styles: 2 = filled square, 4 = "X"
    # (matching pick_tool.rb's conventions).
    SOURCE_COLOR = 'blue'.freeze
    TARGET_COLOR = 'red'.freeze
    GHOST_COLOR = 'magenta'.freeze
    POINT_SIZE = 10
    MAX_PAIRS = 3

    # loose_geometry_allowed: true for Align Face to Face (faces and edges
    # are valid sources), false for Align Group by Nodes (groups and
    # component instances only).
    def initialize(loose_geometry_allowed)
      @loose_ok = loose_geometry_allowed
      @ip = Sketchup::InputPoint.new
      reset_picks
      @items = nil
    end

    # --- tool lifecycle ---------------------------------------------------

    def activate
      reset_picks
      @items = nil
      collect_items(Sketchup.active_model)
      update_ui
    end

    def deactivate(view)
      Sketchup.status_text = ''
      view.invalidate
    end

    # A temporary tool (middle-mouse orbit, for instance) can suspend and
    # resume this one; invalidate both times so markers and the ghost do not
    # linger stale or vanish (rubocop-sketchup: SketchupSuggestions/
    # ToolInvalidate).
    def suspend(view)
      view.invalidate
    end

    def resume(view)
      update_ui
      view.invalidate
    end

    # --- picking ----------------------------------------------------------

    def onMouseMove(_flags, x, y, view)
      @ip.pick(view, x, y)
      view.tooltip = @ip.tooltip if @ip.valid?
      update_ui
      view.invalidate
    end

    def onLButtonDown(_flags, x, y, view)
      @ip.pick(view, x, y)
      return unless @ip.valid?

      if @phase == :source
        add_source_point(@ip.position, view)
      else
        add_target_point(@ip.position, view)
      end
    end

    def onReturn(view)
      if @phase == :source
        if @source_pts.empty?
          notify('Pick at least one source point before pressing Enter.')
          return
        end
        @message = nil
        @planned = @source_pts.length
        @phase = :target
        update_ui
        view.invalidate
      else
        if @target_pts.empty?
          notify('Pick at least one target point before pressing Enter.')
          return
        end
        # Enter with fewer target points than source points applies the
        # reduced mode for however many pairs are complete.
        apply(view)
      end
    end

    # Esc clears the picks so the user can start the sequence again; a
    # second Esc (nothing picked) leaves the tool.
    def onCancel(_reason, view)
      if @source_pts.empty? && @target_pts.empty?
        Sketchup.active_model.select_tool(nil)
      else
        reset_picks
        notify('Picks cleared. Esc again to leave the tool.')
        view.invalidate
      end
    end

    def enableVCB?
      true
    end

    # Typing 1, 2 or 3 fixes how many point pairs the alignment will use,
    # before or during picking.
    def onUserText(text, view)
      n = text.to_s.strip.to_i
      unless (1..MAX_PAIRS).include?(n)
        notify('Type 1, 2 or 3 to set the number of point pairs.')
        return
      end

      @message = nil
      @planned = n
      @source_pts = @source_pts.take(n)
      @target_pts = @target_pts.take(n)
      @phase = @source_pts.length >= n ? :target : :source
      update_ui
      view.invalidate
    end

    # F toggles "flip normal", C toggles Move/Copy -- both persist via
    # Sketchup.write_default, so they survive the session. Modifier and
    # arrow keys are intentionally left alone.
    def onKeyUp(key, _repeat, _flags, view)
      case key
      when 70, 102 # F, f
        AlignOptions.toggle_flip_normal
      when 67, 99  # C, c
        AlignOptions.toggle_copy
      else
        return
      end
      update_ui
      view.invalidate
    end

    # --- drawing ----------------------------------------------------------

    def getExtents
      bb = Geom::BoundingBox.new
      @source_pts.each { |p| bb.add(p) }
      @target_pts.each { |p| bb.add(p) }
      ghost_corners.each { |p| bb.add(p) }
      bb.add(Sketchup.active_model.bounds) if bb.empty?
      bb
    end

    def draw(view)
      draw_picked(view, @source_pts, SOURCE_COLOR, 'A')
      draw_picked(view, @target_pts, TARGET_COLOR, 'B')
      draw_ghost(view)
      @ip.draw(view) if @ip.valid?
    end

    private

    def reset_picks
      @source_pts = []
      @target_pts = []
      @phase = :source
      @planned = MAX_PAIRS
      @message = nil
    end

    # --- selection ---------------------------------------------------------

    # Sorts the current selection into what this tool can move. Called on
    # activate and again lazily (first pick / apply) so the user can select
    # before OR after starting the tool, as long as something is selected by
    # the time the alignment runs.
    def collect_items(model)
      instances = []
      faces = []
      edges = []
      locked = 0
      unsupported = 0

      model.selection.each do |ent|
        case ent
        when Sketchup::Group, Sketchup::ComponentInstance
          if ent.locked?
            locked += 1
          else
            instances << ent
          end
        when Sketchup::Face
          @loose_ok ? faces << ent : unsupported += 1
        when Sketchup::Edge
          @loose_ok ? edges << ent : unsupported += 1
        else
          unsupported += 1
        end
      end

      @items = {
        instances: instances,
        faces: faces,
        edges: edges,
        locked: locked,
        unsupported: unsupported
      }
      @ghost_corners = nil
      @items
    end

    def items
      @items || collect_items(Sketchup.active_model)
    end

    def movable?(set = items)
      !(set[:instances].empty? && set[:faces].empty? && set[:edges].empty?)
    end

    def movable_entities(set = items)
      set[:instances] + set[:faces] + set[:edges]
    end

    # Re-reads the selection when nothing usable was collected yet, so a
    # selection made after the tool started still works. Returns false (and
    # explains why) when there is still nothing to move.
    def ensure_items
      collect_items(Sketchup.active_model) unless movable?

      return true if movable?

      if items[:locked] > 0
        notify("Selection holds only locked #{items[:locked] == 1 ? 'object' : 'objects'} — unlock it first.")
      elsif items[:unsupported] > 0
        notify(@loose_ok ? 'Selection holds no faces, groups or component instances.' :
                           'Select a group or component instance — this tool does not move loose geometry.')
      else
        notify(@loose_ok ? 'Select the faces, groups or components to align first.' :
                           'Select the group or component instance to align first.')
      end
      false
    end

    # --- point picking ----------------------------------------------------

    def add_source_point(pt, view)
      return unless ensure_items

      if @source_pts.any? { |p| AlignMath.coincident?(AlignMath.point_to_a(p), AlignMath.point_to_a(pt)) }
        notify('That point coincides with a source point already picked — pick a different one.')
        return
      end

      if @source_pts.length == 2 && collinear_with?(@source_pts, pt)
        notify('A1, A2 and A3 would be collinear (no plane) — pick a third point off that line.')
        return
      end

      # The pick is good: drop any earlier rejection message before the
      # note below may set a new one.
      @message = nil
      # Align Group by Nodes is meant to be driven from the group's own
      # nodes; a free-space pick still works, so this is a note, not a veto.
      if !@loose_ok && @ip.vertex.nil?
        notify('Note: that source pick is not on a vertex/endpoint of the group.')
      end

      @source_pts << pt
      @phase = :target if @source_pts.length >= @planned
      update_ui # keeps the vertex note above, if there was one
      view.invalidate
    end

    def add_target_point(pt, view)
      if @target_pts.any? { |p| AlignMath.coincident?(AlignMath.point_to_a(p), AlignMath.point_to_a(pt)) }
        notify('That point coincides with a target point already picked — pick a different one.')
        return
      end

      if @target_pts.length == 2 && collinear_with?(@target_pts, pt)
        notify('B1, B2 and B3 would be collinear (no plane) — pick a third point off that line.')
        return
      end

      @message = nil
      @target_pts << pt
      update_ui
      view.invalidate
      apply(view) if @target_pts.length >= @source_pts.length
    end

    def collinear_with?(first_two, pt)
      AlignMath.collinear?(AlignMath.point_to_a(first_two[0]),
                           AlignMath.point_to_a(first_two[1]),
                           AlignMath.point_to_a(pt))
    end

    # --- solving ----------------------------------------------------------

    def solution_for(source_pts, target_pts)
      n = [source_pts.length, target_pts.length].min
      return nil if n < 1

      AlignMath.solve(source_pts.take(n).map { |p| AlignMath.point_to_a(p) },
                      target_pts.take(n).map { |p| AlignMath.point_to_a(p) },
                      AlignOptions.flip_normal?)
    end

    # Solution including the point currently under the cursor as the next
    # target point, for the live ghost.
    def preview_solution
      pts = @target_pts.dup
      pts << @ip.position if @phase == :target && @ip.valid? && pts.length < @source_pts.length
      solution_for(@source_pts, pts)
    end

    # --- applying ---------------------------------------------------------

    def apply(view)
      return unless ensure_items

      solution = solution_for(@source_pts, @target_pts)
      if solution.nil?
        notify('Those points do not define a usable alignment (collinear or coincident) — pick again.')
        return
      end

      # Belt and braces: the math only ever builds proper rotations, so a
      # determinant other than +1 would mean a bug. Refuse rather than
      # mirror or scale the user's geometry.
      det = AlignMath.rotation_determinant(solution[:rot])
      if (det - 1.0).abs > 1e-6
        UI.messagebox("Internal error: the computed transformation is not a pure rotation " \
                      "(determinant #{format('%.6f', det)}). Nothing was changed.")
        return
      end

      if AlignMath.identity_solution?(solution)
        reset_picks
        notify('Source and target frames are already identical — nothing to do.')
        view.invalidate
        return
      end

      set = items
      copy_mode = AlignOptions.copy?
      # Moving loose geometry that is welded to geometry outside the
      # selection drags the neighbours' vertices along -- which deforms
      # them. Say so and let the user back out. Copy mode never touches the
      # original, so the warning does not apply there.
      if !copy_mode && attached_geometry?(set) &&
         UI.messagebox("Some selected loose geometry is connected to geometry that is not selected.\n\n" \
                       "Moving it will DEFORM that adjacent geometry.\n\n" \
                       "Continue anyway? (Cancel to stop — or switch to Copy mode, " \
                       'which leaves the original untouched.)', MB_OKCANCEL) == IDCANCEL
        notify('Alignment cancelled — nothing was changed.')
        return
      end

      model = view.model
      transformation = local_transformation(model, solution)
      model.start_operation('Align by Points', true)
      begin
        results = copy_mode ? apply_as_copy(set, transformation) : apply_in_place(set, transformation)
        model.commit_operation
      rescue StandardError => e
        model.abort_operation
        UI.messagebox("Align by Points failed, nothing was changed:\n#{e.message}")
        return
      end

      model.selection.clear
      model.selection.add(results) unless results.empty?
      summary = result_summary(solution, set, copy_mode, results)

      # Ready for the next alignment: keep the tool live, drop the picks and
      # re-read the selection (which now holds the copies, in copy mode).
      # reset_picks clears the message, so the summary is set after it.
      reset_picks
      @items = nil
      notify(summary)
      view.invalidate
    end

    # model.edit_transform maps the current editing context to model space.
    # The solution is in model space, so the equivalent transformation
    # INSIDE the context is ET^-1 * T * ET. At the top level ET is the
    # identity and this is a no-op.
    def local_transformation(model, solution)
      t_model = AlignMath.to_transformation(solution)
      et = model.edit_transform
      return t_model if et.identity?

      et.inverse * t_model * et
    end

    def apply_in_place(set, transformation)
      set[:instances].each { |inst| inst.transform!(transformation) }

      # Loose geometry is moved per owning Entities collection, because
      # transform_entities only accepts entities it owns.
      loose = set[:faces] + set[:edges]
      loose.group_by { |ent| ent.parent.entities }.each do |entities, ents|
        entities.transform_entities(transformation, ents)
      end
      set[:instances] + loose
    end

    def apply_as_copy(set, transformation)
      results = []
      set[:instances].each do |inst|
        copy = duplicate_instance(inst)
        next if copy.nil?

        copy.transform!(transformation)
        results << copy
      end

      # Loose faces/edges are copied into a new group (one per owning
      # Entities collection) and the group is transformed, which keeps the
      # original geometry -- and anything welded to it -- untouched.
      (set[:faces] + set[:edges]).group_by { |ent| ent.parent.entities }.each do |entities, ents|
        group = copy_loose_geometry(entities, ents)
        next if group.nil?

        group.transform!(transformation)
        results << group
      end
      results
    end

    # Groups and component instances are duplicated differently: a Group has
    # its own definition, so Group#copy is the right call, while a component
    # gets a second instance of the shared definition. Either way the
    # instance-level properties (name, material, tag/layer, attributes) are
    # carried over, and nothing inside the definition is touched.
    def duplicate_instance(inst)
      copy =
        if inst.is_a?(Sketchup::Group) && inst.respond_to?(:copy)
          inst.copy
        else
          inst.parent.entities.add_instance(inst.definition, inst.transformation)
        end
      return nil if copy.nil?

      copy_instance_properties(inst, copy)
      copy
    end

    def copy_instance_properties(src, dst)
      dst.name = src.name if src.respond_to?(:name) && dst.respond_to?(:name=)
      dst.material = src.material
      dst.layer = src.layer
      dst.hidden = src.hidden?
      dst.casts_shadows = src.casts_shadows? if dst.respond_to?(:casts_shadows=)
      dst.receives_shadows = src.receives_shadows? if dst.respond_to?(:receives_shadows=)
      copy_attributes(src, dst)
    end

    def copy_attributes(src, dst)
      dicts = src.attribute_dictionaries
      return if dicts.nil?

      dicts.each do |dict|
        dict.each_pair { |key, value| dst.set_attribute(dict.name, key, value) }
      end
    end

    # Rebuilds the given loose faces/edges inside a fresh group: the outer
    # loop of each face, then each inner loop added and its face erased,
    # which leaves the loop's edges behind and so punches the hole back
    # through. Per-face material/back material/tag are carried over.
    def copy_loose_geometry(entities, ents)
      faces = ents.grep(Sketchup::Face)
      edges = ents.grep(Sketchup::Edge)
      return nil if faces.empty? && edges.empty?

      group = entities.add_group
      g_ents = group.entities

      faces.each do |face|
        new_face = g_ents.add_face(face.outer_loop.vertices.map(&:position))
        next if new_face.nil?

        new_face.material = face.material
        new_face.back_material = face.back_material
        new_face.layer = face.layer
        copy_attributes(face, new_face)

        face.loops.each do |loop|
          next if loop.outer?

          hole = g_ents.add_face(loop.vertices.map(&:position))
          hole.erase! if hole && hole.valid?
        end
      end

      edges.each do |edge|
        new_edges = g_ents.add_line(edge.start.position, edge.end.position)
        Array(new_edges).each { |e| e.layer = edge.layer if e.is_a?(Sketchup::Edge) }
      end

      group
    end

    # True when any vertex of the moving loose geometry also carries an edge
    # that is NOT moving -- i.e. the selection is welded to geometry that
    # will be stretched rather than moved.
    def attached_geometry?(set)
      moving_edges = {}
      set[:faces].each { |f| f.edges.each { |e| moving_edges[e] = true } }
      set[:edges].each { |e| moving_edges[e] = true }
      return false if moving_edges.empty?

      vertices = {}
      moving_edges.each_key do |edge|
        vertices[edge.start] = true
        vertices[edge.end] = true
      end
      vertices.each_key do |vertex|
        vertex.edges.each { |edge| return true unless moving_edges[edge] }
      end
      false
    end

    def result_summary(solution, set, copy_mode, results)
      pairs = [@source_pts.length, @target_pts.length].min
      mode = case pairs
             when 1 then 'translation only'
             when 2 then 'translation + minimum rotation'
             else 'full 3-point alignment'
             end
      distance = Sketchup.format_length(AlignMath.vlength(solution[:trans]))
      notes = []
      notes << "#{set[:locked]} locked object(s) skipped" if set[:locked] > 0
      notes << "#{set[:unsupported]} unsupported entity(ies) ignored" if set[:unsupported] > 0
      suffix = notes.empty? ? '' : " (#{notes.join('; ')})"
      "#{copy_mode ? 'Copied' : 'Moved'} #{results.length} object(s) — #{pairs} pair(s), #{mode}, " \
        "A1 travelled #{distance}#{AlignOptions.flip_normal? ? ', flipped' : ''}#{suffix}"
    end

    # --- status bar / VCB --------------------------------------------------

    # The status bar carries two things: the standing prompt for the current
    # step, and (when there is one) the message from the last action --
    # a rejected pick, a toggle, the summary of the alignment just applied.
    # Both are written together, every time, so refreshing the prompt can
    # never wipe a message the user has not read yet. @message is cleared by
    # the next successful pick, not by mouse movement.
    def update_ui
      Sketchup.status_text =
        if @message
          "Align by Points: #{@message} — #{status_prompt}"
        else
          status_prompt
        end
      Sketchup.vcb_label = 'Pairs'
      picked = @phase == :source ? @source_pts.length : @target_pts.length
      Sketchup.vcb_value = "#{picked}/#{@planned}"
    end

    def status_prompt
      options = AlignOptions.summary
      hint = '[F] flip, [C] Move/Copy, [1-3] pairs, Esc cancels'
      if @phase == :source
        n = @source_pts.length + 1
        source_word = @loose_ok ? 'source point' : 'source node'
        "Pick #{source_word} #{n} of #{@planned} (Enter to finish with fewer points) — " \
          "#{options} — #{hint}"
      else
        n = @target_pts.length + 1
        total = @source_pts.length
        "Pick target point #{n} of #{total} (Enter applies what is picked) — #{options} — #{hint}"
      end
    end

    def notify(message)
      @message = message
      update_ui
    end

    # --- ghost preview -----------------------------------------------------

    # Eight corners of the selection's bounding box, in MODEL space (bounds
    # are reported in the owning context's space, so they get the editing
    # context's transformation applied).
    def ghost_corners
      return @ghost_corners if @ghost_corners

      set = @items
      return [] if set.nil? || !movable?(set)

      bb = Geom::BoundingBox.new
      movable_entities(set).each { |ent| bb.add(ent.bounds) }
      return @ghost_corners = [] if bb.empty?

      et = Sketchup.active_model.edit_transform
      @ghost_corners = (0..7).map { |i| bb.corner(i).transform(et) }
    end

    # Bounding-box corner indices that form its 12 edges.
    BOX_EDGES = [[0, 1], [1, 3], [3, 2], [2, 0],
                 [4, 5], [5, 7], [7, 6], [6, 4],
                 [0, 4], [1, 5], [2, 6], [3, 7]].freeze

    def draw_ghost(view)
      corners = ghost_corners
      return if corners.empty?

      solution = preview_solution
      return if solution.nil?

      transformation = AlignMath.to_transformation(solution)
      moved = corners.map { |p| p.transform(transformation) }
      segments = []
      BOX_EDGES.each { |a, b| segments << moved[a] << moved[b] }

      view.drawing_color = GHOST_COLOR
      view.line_width = 2
      view.line_stipple = '-'
      view.draw(GL_LINES, segments)
      view.line_stipple = ''
    end

    def draw_picked(view, points, color, label)
      return if points.empty?

      view.draw_points(points, POINT_SIZE, 2, color)
      if points.length > 1
        view.drawing_color = color
        view.line_width = 2
        view.line_stipple = ''
        view.draw(GL_LINE_STRIP, points)
      end
      points.each_with_index do |pt, i|
        view.draw_text(view.screen_coords(pt), "  #{label}#{i + 1}")
      end
    end
  end

  # Tool 1: loose faces/edges, groups and component instances.
  class AlignFaceToFaceTool < AlignByPointsTool
    def initialize
      super(true)
    end
  end

  # Tool 2: groups and component instances only. Same point-pair logic and
  # the same math; only the instance transformation changes, so the group's
  # internal geometry is never edited.
  class AlignGroupByNodesTool < AlignByPointsTool
    def initialize
      super(false)
    end
  end
end
