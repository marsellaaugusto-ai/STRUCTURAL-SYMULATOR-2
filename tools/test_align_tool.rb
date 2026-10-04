# test_align_tool.rb -- drives align_tool.rb against tools/sketchup_stub.rb.
#
#   ruby tools/test_align_tool.rb
#
# The math already has its own tests (test_align_math.rb); this one exercises
# the TOOL: selection filtering, the pick state machine, Enter/Esc, the VCB,
# the undo operation, move vs. copy, locked and unsupported entities, the
# adjacent-geometry warning, and draw(). It cannot replace a pass in real
# SketchUp (see ALIGN_BY_POINTS.md for the manual checklist), but it catches
# anything that would raise on the happy path.
require_relative 'sketchup_stub'
require_relative '../sketchup_extension/coordinate_coordinator_truss_app_amac/align_math'
require_relative '../sketchup_extension/coordinate_coordinator_truss_app_amac/align_options'
require_relative '../sketchup_extension/coordinate_coordinator_truss_app_amac/align_tool'

CC = CoordinateCoordinatorTrussAppAMAC
M = CC::AlignMath

$failures = 0
$checks = 0

def check(label)
  $checks += 1
  ok = begin
    yield
  rescue StandardError => e
    puts "ERROR in #{label}: #{e.class}: #{e.message}\n  #{e.backtrace.first(3).join("\n  ")}"
    false
  end
  unless ok
    $failures += 1
    puts "FAIL: #{label}"
  end
end

def pt(x, y, z)
  Geom::Point3d.new(x, y, z)
end

# Fresh model/selection for each scenario.
def new_world(selected = [])
  model = Sketchup::Model.new
  selected.each { |e| model.entities.add_existing(e) }
  model.selection = Sketchup::Selection.new(selected)
  Sketchup.active_model = model
  UI.reset!
  Sketchup.defaults = {}
  [model, StubView.new(model)]
end

def click(tool, view, point, vertex = nil)
  Sketchup::InputPoint.scripted_position = point
  Sketchup::InputPoint.scripted_vertex = vertex
  tool.onMouseMove(0, 10, 10, view)
  tool.onLButtonDown(0, 10, 10, view)
end

def new_group(name = 'g')
  group = Sketchup::Group.new(Sketchup::ComponentDefinition.new('gdef'))
  group.name = name
  group.set_attribute('dynamic_attributes', 'len', 42)
  group
end

# A square face in the XY plane, optionally welded to a neighbour face that
# is NOT selected (shared edge) to trigger the deform warning.
def new_face(welded: false)
  face = Sketchup::Face.new([pt(0, 0, 0), pt(10, 0, 0), pt(10, 10, 0), pt(0, 10, 0)])
  if welded
    neighbour = Sketchup::Face.new([pt(0, 0, 0), pt(10, 0, 0), pt(10, -10, 0), pt(0, -10, 0)])
    # Weld: hang an extra edge off one of the face's own vertices.
    v = face.edges.first.start
    extra = Sketchup::Edge.new(v, Sketchup::Vertex.new(pt(0, 0, 25)))
    extra.faces = [neighbour]
  end
  face
end

# Source triplet and a target triplet that is the source moved by a known
# rigid motion, so the expected transformation is known exactly.
A = [pt(0, 0, 0), pt(10, 0, 0), pt(0, 7, 0)].freeze
MOVE = M.rotation_axis_angle([0.2, 0.4, 0.89], 0.6)
TRANS = [15.0, -3.0, 9.0].freeze
B = A.map do |p|
  moved = M.vadd(M.mat_mul_vec(MOVE, M.point_to_a(p)), TRANS)
  pt(*moved)
end.freeze

def run_three_pairs(tool, view, targets = B)
  A.each { |p| click(tool, view, p) }
  targets.each { |p| click(tool, view, p) }
end

# --- 3 pairs, move in place -------------------------------------------------
group = new_group
model, view = new_world([group])
tool = CC::AlignFaceToFaceTool.new
tool.activate
run_three_pairs(tool, view)

check('3 pairs: exactly one undo operation, committed') do
  model.operations == [[:start, 'Align by Points'], [:commit]]
end
check('3 pairs: the group was transformed once') { group.transform_log.length == 1 }
check('3 pairs: the applied transformation carries A1 to B1') do
  landed = A[0].transform(group.transform_log.first)
  (landed.x - B[0].x).abs < 1e-9 && (landed.y - B[0].y).abs < 1e-9 && (landed.z - B[0].z).abs < 1e-9
end
check('3 pairs: the applied transformation is rigid (det == +1)') do
  (M.rotation_determinant(group.transform_log.first.rotation_part) - 1.0).abs < 1e-9
end
check('3 pairs: group properties untouched') do
  group.name == 'g' && group.get_attribute('dynamic_attributes', 'len') == 42
end
check('3 pairs: nothing was copied') { model.entities.added.length == 1 } # just the original
check('3 pairs: picks reset so the tool is ready to run again') do
  Sketchup.vcb_value == '0/3'
end
check('3 pairs: the result is selected') { model.selection.to_a == [group] }

# --- 1 pair (Enter after one source point) ----------------------------------
group = new_group
model, view = new_world([group])
tool = CC::AlignFaceToFaceTool.new
tool.activate
click(tool, view, pt(1, 2, 3))
tool.onReturn(view)         # finish the source phase with one point
click(tool, view, pt(11, 2, 3))
check('1 pair: applied after the single target pick') { group.transform_log.length == 1 }
check('1 pair: pure translation, no rotation') do
  tr = group.transform_log.first
  rot = tr.rotation_part
  rot[0][0] == 1.0 && rot[1][1] == 1.0 && rot[2][2] == 1.0 &&
    (tr.origin.x - 10.0).abs < 1e-9 && tr.origin.y.abs < 1e-9 && tr.origin.z.abs < 1e-9
end

# --- 2 pairs (VCB sets the pair count) --------------------------------------
group = new_group
model, view = new_world([group])
tool = CC::AlignFaceToFaceTool.new
tool.activate
tool.onUserText('2', view)
click(tool, view, pt(0, 0, 0))
click(tool, view, pt(0, 0, 10))     # source direction +Z
click(tool, view, pt(5, 5, 5))
click(tool, view, pt(5, 8, 5))      # target direction +Y
check('2 pairs: VCB count honoured, applied after the second target') do
  group.transform_log.length == 1
end
check('2 pairs: A1 lands on B1 and the direction is aligned') do
  tr = group.transform_log.first
  a1 = pt(0, 0, 0).transform(tr)
  a2 = pt(0, 0, 10).transform(tr)
  dir = M.vnormalize(M.vsub(M.point_to_a(a2), M.point_to_a(a1)))
  (a1.x - 5).abs < 1e-9 && (a1.y - 5).abs < 1e-9 && (a1.z - 5).abs < 1e-9 &&
    M.vlength(M.vsub(dir, [0.0, 1.0, 0.0])) < 1e-9
end
check('2 pairs: VCB rejects anything outside 1-3') do
  before = Sketchup.vcb_value
  tool.onUserText('7', view)
  Sketchup.status_text.include?('Type 1, 2 or 3') && Sketchup.vcb_value == before
end

# --- copy mode --------------------------------------------------------------
group = new_group
model, view = new_world([group])
CC::AlignOptions.copy = true
tool = CC::AlignFaceToFaceTool.new
tool.activate
run_three_pairs(tool, view)
copies = model.entities.added.reject { |e| e.equal?(group) }
check('copy: the original was not transformed') { group.transform_log.empty? }
check('copy: exactly one copy was created and transformed') do
  copies.length == 1 && copies.first.transform_log.length == 1
end
check('copy: the copy is a Group, not a component instance') do
  copies.first.instance_of?(Sketchup::Group)
end
check('copy: name and attributes carried over') do
  copies.first.name == 'g' && copies.first.get_attribute('dynamic_attributes', 'len') == 42
end
check('copy: the copy is what ends up selected') { model.selection.to_a == copies }
CC::AlignOptions.copy = false

# --- flip normal ------------------------------------------------------------
group = new_group
model, view = new_world([group])
CC::AlignOptions.flip_normal = true
tool = CC::AlignFaceToFaceTool.new
tool.activate
run_three_pairs(tool, view)
check('flip: still rigid (det == +1, no mirror)') do
  (M.rotation_determinant(group.transform_log.first.rotation_part) - 1.0).abs < 1e-9
end
check('flip: A1 still lands on B1, A3 on the far side') do
  tr = group.transform_log.first
  a1 = A[0].transform(tr)
  a3 = A[2].transform(tr)
  fb = M.frame(M.point_to_a(B[0]), M.point_to_a(B[1]), M.point_to_a(B[2]))
  (a1.x - B[0].x).abs < 1e-9 &&
    M.vdot(fb[:y], M.vsub(M.point_to_a(a3), M.point_to_a(B[0]))) < 0
end
CC::AlignOptions.flip_normal = false

# --- collinear rejection ----------------------------------------------------
group = new_group
model, view = new_world([group])
tool = CC::AlignFaceToFaceTool.new
tool.activate
click(tool, view, pt(0, 0, 0))
click(tool, view, pt(10, 0, 0))
click(tool, view, pt(25, 0, 0))     # collinear third source pick -> rejected
check('collinear: third source pick rejected with a status message') do
  Sketchup.status_text.include?('collinear')
end
check('collinear: still in the source phase, nothing applied') do
  Sketchup.vcb_value == '2/3' && group.transform_log.empty?
end
click(tool, view, pt(0, 7, 0))      # a valid third pick is accepted
check('collinear: a valid third pick is then accepted') { Sketchup.vcb_value == '0/3' }
click(tool, view, B[0])
click(tool, view, B[1])
click(tool, view, pt(B[0].x + (B[1].x - B[0].x) * 2, B[0].y + (B[1].y - B[0].y) * 2,
                     B[0].z + (B[1].z - B[0].z) * 2)) # collinear target -> rejected
check('collinear: third TARGET pick rejected too') do
  Sketchup.status_text.include?('collinear') && group.transform_log.empty?
end

# --- coincident picks -------------------------------------------------------
group = new_group
model, view = new_world([group])
tool = CC::AlignFaceToFaceTool.new
tool.activate
click(tool, view, pt(0, 0, 0))
click(tool, view, pt(0, 0, 0))
check('coincident: a repeated source point is refused') do
  Sketchup.status_text.include?('coincides') && Sketchup.vcb_value == '1/3'
end

# --- identical frames -------------------------------------------------------
group = new_group
model, view = new_world([group])
tool = CC::AlignFaceToFaceTool.new
tool.activate
run_three_pairs(tool, view, A)      # target triplet == source triplet
check('identity: reported as a no-op') do
  Sketchup.status_text.include?('already identical')
end
check('identity: no undo operation was opened, nothing transformed') do
  model.operations.empty? && group.transform_log.empty?
end

# --- locked instance --------------------------------------------------------
group = new_group
group.locked = true
model, view = new_world([group])
tool = CC::AlignFaceToFaceTool.new
tool.activate
click(tool, view, A[0])
check('locked: refused with an explanation, nothing picked') do
  Sketchup.status_text.downcase.include?('locked') && group.transform_log.empty?
end

# --- empty selection --------------------------------------------------------
model, view = new_world([])
tool = CC::AlignFaceToFaceTool.new
tool.activate
click(tool, view, A[0])
check('empty selection: refused with an explanation, no crash') do
  Sketchup.status_text.include?('Select the faces') && model.operations.empty?
end

# --- selection made AFTER the tool started ----------------------------------
group = new_group
model, view = new_world([])
tool = CC::AlignFaceToFaceTool.new
tool.activate                        # nothing selected yet
model.entities.add_existing(group)
model.selection = Sketchup::Selection.new([group])
run_three_pairs(tool, view)
check('late selection: picked up on the first click') { group.transform_log.length == 1 }

# --- unsupported entities ignored -------------------------------------------
group = new_group
stray = Sketchup::Entity.new                      # neither instance nor geometry
model, view = new_world([group, stray])
tool = CC::AlignFaceToFaceTool.new
tool.activate
run_three_pairs(tool, view)
check('unsupported: ignored, and reported in the summary') do
  group.transform_log.length == 1 && Sketchup.status_text.include?('unsupported')
end

# --- Align Group by Nodes rejects loose geometry ----------------------------
face = new_face
model, view = new_world([face])
tool = CC::AlignGroupByNodesTool.new
tool.activate
click(tool, view, A[0])
check('group tool: loose face is not an acceptable source') do
  Sketchup.status_text.include?('does not move loose geometry') && model.operations.empty?
end

group = new_group
model, view = new_world([group])
tool = CC::AlignGroupByNodesTool.new
tool.activate
click(tool, view, A[0])             # no vertex snap -> informative note
check('group tool: a non-vertex source pick is noted but accepted') do
  Sketchup.status_text.include?('not on a vertex') && Sketchup.vcb_value == '1/3'
end
A.drop(1).each { |p| click(tool, view, p, Sketchup::Vertex.new(p)) }
B.each { |p| click(tool, view, p) }
check('group tool: only the instance transformation changed') do
  group.transform_log.length == 1 && group.definition.entities.added.empty?
end

# --- loose face, move in place, welded to unselected geometry ---------------
face = new_face(welded: true)
model, view = new_world([face])
face.parent = model
tool = CC::AlignFaceToFaceTool.new
tool.activate
UI.queued = [IDCANCEL]              # user backs out of the deform warning
run_three_pairs(tool, view)
check('welded face: the deform warning was raised') do
  UI.boxes.any? { |b| b.include?('DEFORM') }
end
check('welded face: Cancel means nothing was changed') do
  model.operations.empty? && model.entities.transform_calls.empty?
end

face = new_face(welded: true)
model, view = new_world([face])
face.parent = model
tool = CC::AlignFaceToFaceTool.new
tool.activate
UI.queued = [IDOK]                  # user proceeds
run_three_pairs(tool, view)
check('welded face: OK proceeds and transforms the face in place') do
  model.entities.transform_calls.length == 1 &&
    model.entities.transform_calls.first[1] == [face] &&
    model.operations == [[:start, 'Align by Points'], [:commit]]
end

# --- loose face, copy mode: no warning, geometry rebuilt in a group ---------
face = new_face(welded: true)
model, view = new_world([face])
face.parent = model
CC::AlignOptions.copy = true
tool = CC::AlignFaceToFaceTool.new
tool.activate
run_three_pairs(tool, view)
check('loose copy: no deform warning in copy mode') do
  UI.boxes.none? { |b| b.include?('DEFORM') }
end
check('loose copy: a new group holding the copied face was transformed') do
  groups = model.entities.added.grep(Sketchup::Group)
  groups.length == 1 &&
    groups.first.definition.entities.items.grep(Sketchup::Face).length == 1 &&
    groups.first.transform_log.length == 1
end
check('loose copy: the original face was never transformed') do
  model.entities.transform_calls.empty?
end
CC::AlignOptions.copy = false

# --- face with a hole -------------------------------------------------------
holed = Sketchup::Face.new([pt(0, 0, 0), pt(10, 0, 0), pt(10, 10, 0), pt(0, 10, 0)],
                           [pt(3, 3, 0), pt(6, 3, 0), pt(6, 6, 0), pt(3, 6, 0)])
model, view = new_world([holed])
holed.parent = model
CC::AlignOptions.copy = true
tool = CC::AlignFaceToFaceTool.new
tool.activate
run_three_pairs(tool, view)
check('hole: the inner loop was re-added (and its face erased) in the copy') do
  g = model.entities.added.grep(Sketchup::Group).first
  g.definition.entities.added.grep(Sketchup::Face).length == 2 # outer + punched hole
end
CC::AlignOptions.copy = false

# --- Escape -----------------------------------------------------------------
group = new_group
model, view = new_world([group])
tool = CC::AlignFaceToFaceTool.new
tool.activate
click(tool, view, A[0])
click(tool, view, A[1])
tool.onCancel(0, view)
check('Esc: first press clears the picks but keeps the tool') do
  Sketchup.vcb_value == '0/3' && model.active_tool.nil? &&
    Sketchup.status_text.include?('Picks cleared')
end
tool.onCancel(0, view)
check('Esc: second press leaves the tool') { model.active_tool.nil? == true }

# --- Enter with no picks ----------------------------------------------------
model, view = new_world([new_group])
tool = CC::AlignFaceToFaceTool.new
tool.activate
tool.onReturn(view)
check('Enter with nothing picked: explained, not a crash') do
  Sketchup.status_text.include?('at least one source point')
end

# --- Enter in the target phase with fewer pairs ------------------------------
group = new_group
model, view = new_world([group])
tool = CC::AlignFaceToFaceTool.new
tool.activate
A.each { |p| click(tool, view, p) }  # 3 source points
click(tool, view, B[0])              # only 1 target point...
tool.onReturn(view)                  # ...Enter applies the 1-pair mode
check('Enter in target phase: reduced mode applied') do
  group.transform_log.length == 1 &&
    (A[0].transform(group.transform_log.first).x - B[0].x).abs < 1e-9
end

# --- F / C keys -------------------------------------------------------------
model, view = new_world([new_group])
tool = CC::AlignFaceToFaceTool.new
tool.activate
flip_before = CC::AlignOptions.flip_normal?
tool.onKeyUp(102, 1, 0, view)        # 'f'
check('F key toggles flip and persists it') do
  CC::AlignOptions.flip_normal? != flip_before &&
    Sketchup.defaults[['CoordinateCoordinatorTrussAppAMAC_Align', 'flip_normal']] == !flip_before
end
tool.onKeyUp(102, 1, 0, view)
copy_before = CC::AlignOptions.copy?
tool.onKeyUp(99, 1, 0, view)         # 'c'
check('C key toggles Move/Copy') { CC::AlignOptions.copy? != copy_before }
tool.onKeyUp(99, 1, 0, view)
check('other keys are ignored') do
  before = Sketchup.status_text
  tool.onKeyUp(65, 1, 0, view)
  Sketchup.status_text == before
end

# --- draw / getExtents ------------------------------------------------------
group = new_group
model, view = new_world([group])
tool = CC::AlignFaceToFaceTool.new
tool.activate
A.each { |p| click(tool, view, p) }
Sketchup::InputPoint.scripted_position = B[0]
tool.onMouseMove(0, 10, 10, view)
tool.draw(view)
check('draw: source markers, labels and the live ghost are drawn') do
  modes = view.draw_calls.map(&:first)
  modes.include?(:points) && modes.include?(GL_LINES) &&
    view.texts.map(&:last).include?('  A1')
end
check('getExtents: covers picks and the ghost') { !tool.getExtents.empty? }
check('draw: no ghost before any target pick is pending') do
  tool2 = CC::AlignFaceToFaceTool.new
  tool2.activate
  v2 = StubView.new(model)
  Sketchup::InputPoint.scripted_position = nil
  tool2.draw(v2)
  v2.draw_calls.empty?
end

# --- options dialog ---------------------------------------------------------
Sketchup.defaults = {}
UI.reset!
UI.queued = [['Yes', 'Copy']]
check('options dialog: writes both settings') do
  CC::AlignOptions.show_dialog &&
    CC::AlignOptions.flip_normal? && CC::AlignOptions.copy?
end
UI.reset!
UI.queued = [false]                  # user cancelled the dialog
check('options dialog: Cancel changes nothing') do
  CC::AlignOptions.show_dialog == false &&
    CC::AlignOptions.flip_normal? && CC::AlignOptions.copy?
end
CC::AlignOptions.flip_normal = false
CC::AlignOptions.copy = false
check('options: summary reads back the stored values') do
  CC::AlignOptions.summary == 'Flip normal: off | Move'
end

# --- inside a group edit context --------------------------------------------
# edit_transform != identity: the model-space solution must be conjugated,
# so the transformation handed to the instance is ET^-1 * T * ET.
group = new_group
model, view = new_world([group])
et = Geom::Transformation.new([1.0, 0.0, 0.0, 0.0,
                               0.0, 1.0, 0.0, 0.0,
                               0.0, 0.0, 1.0, 0.0,
                               100.0, 50.0, 25.0, 1.0])
model.edit_transform = et
tool = CC::AlignFaceToFaceTool.new
tool.activate
run_three_pairs(tool, view)
check('edit context: the applied transformation is conjugated by edit_transform') do
  applied = group.transform_log.first
  expected = et.inverse * M.to_transformation(
    M.solve(A.map { |p| M.point_to_a(p) }, B.map { |p| M.point_to_a(p) }, false)
  ) * et
  applied.m.each_with_index.all? { |v, i| (v - expected.m[i]).abs < 1e-9 }
end

puts "#{$checks - $failures}/#{$checks} checks passed"
exit($failures.zero? ? 0 : 1)
