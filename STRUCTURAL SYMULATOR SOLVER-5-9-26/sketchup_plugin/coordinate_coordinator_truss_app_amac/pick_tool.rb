# pick_tool.rb
#
# Interactive picking tool: first click sets the origin, every click after
# that adds a node. Uses Sketchup::InputPoint so you get SketchUp's normal
# inference for free -- Endpoint, Midpoint, On Edge, and (this is the part
# that matters for "intersection between lines") Intersection, which snaps
# to where two edges cross in 3D even if they don't share a vertex there.
#
# Enter finishes and exports. Esc cancels. There's no in-tool undo of a
# single point on purpose -- restart the tool (menu item again) if you
# misclick; keeps this first version simple.
module CoordinateCoordinatorTrussAppAMAC
  class PickNodesTool
    def initialize
      @ip = Sketchup::InputPoint.new
      @origin = nil
      @nodes = []
    end

    def activate
      @origin = nil
      @nodes = []
      update_status
    end

    def deactivate(view)
      view.invalidate
    end

    # A temporary tool (e.g. the camera orbit that middle-mouse-drag
    # activates) can suspend this one and later resume it; invalidate both
    # times so our origin/node markers don't linger stale or vanish
    # incorrectly (rubocop-sketchup: SketchupSuggestions/ToolInvalidate).
    def suspend(view)
      view.invalidate
    end

    def resume(view)
      view.invalidate
    end

    def onMouseMove(_flags, x, y, view)
      @ip.pick(view, x, y)
      view.invalidate
    end

    def onLButtonDown(_flags, x, y, view)
      @ip.pick(view, x, y)
      return unless @ip.valid?

      pt = @ip.position
      if @origin.nil?
        @origin = pt
      else
        @nodes << pt
      end
      update_status
      view.invalidate
    end

    def onReturn(view)
      finish(view)
    end

    def onCancel(_reason, view)
      @origin = nil
      @nodes = []
      view.invalidate
    end

    def getExtents
      bb = Geom::BoundingBox.new
      bb.add(@origin) if @origin
      @nodes.each { |p| bb.add(p) }
      bb
    end

    def draw(view)
      if @origin
        # style 4 = "X" -- distinct from the plain node markers below.
        view.draw_points([@origin], 14, 4, 'red')
      end
      unless @nodes.empty?
        # style 2 = filled square.
        view.draw_points(@nodes, 10, 2, 'blue')
      end
      @ip.draw(view) if @ip.valid?
    end

    private

    def update_status
      Sketchup.status_text =
        if @origin.nil?
          'Coordinate coordinator truss app AMAC: click to set the ORIGIN point.'
        else
          "Coordinate coordinator truss app AMAC: origin set. Click to add nodes (#{@nodes.length} so far). " \
          'Enter = finish & export. Esc = cancel.'
        end
    end

    def finish(view)
      if @origin.nil? || @nodes.empty?
        UI.messagebox('Pick an origin and at least one node before finishing (Enter).')
        return
      end

      model = view.model
      # InputPoint reports in world coordinates, so the edges have to be
      # gathered in world coordinates too: edit_transform is what carries
      # the context we are picking in out to the world, and it is the
      # identity at the top level. Picking while inside a group used to
      # compare the two in different spaces and find no members at all.
      base = begin
        model.edit_transform
      rescue StandardError
        nil
      end
      nodes_m, members, member_paths = CoordinateCoordinatorTrussAppAMAC
                                       .build_model(@origin, @nodes,
                                                    model.active_entities, base)
      CoordinateCoordinatorTrussAppAMAC.export_to_excel(
        nodes_m, members,
        CoordinateCoordinatorTrussAppAMAC.group_rows(member_paths))
      Sketchup.active_model.select_tool(nil)
    end
  end
end
