# SketchUp extension: Coordinate coordinator truss app AMAC

Source of the SketchUp extension that bridges this repo's Structural
Simulator **Stereo** (space-truss) app and SketchUp, now also carrying the
**Align by Points** tools.

```
sketchup_extension/
  coordinate_coordinator_truss_app_amac.rb      loader (SketchupExtension)
  coordinate_coordinator_truss_app_amac/
    main.rb            menu + toolbar wiring, Excel export entry point
    xlsx_writer.rb     dependency-free XLSX writer
    xlsx_reader.rb     dependency-free XLSX reader
    model_export.rb    picked points -> nodes/members
    model_import.rb    Stereo XLSX -> SketchUp geometry
    pick_tool.rb       "Pick Origin + Nodes" tool
    intersections.rb   auto-detect nodes/rods from a selection
    align_math.rb      Align by Points: frames and 1/2/3-pair solvers
    align_options.rb   Align by Points: persisted options + dialog
    align_tool.rb      Align by Points: the two tool classes
    icons/
  ALIGN_BY_POINTS.md   feature documentation + manual test checklist
```

## Build the installable .rbz

```
python3 tools/build_rbz.py            # writes dist/CoordinateCoordinatorTrussAppAMAC_v<version>_<date>.rbz
```

The script verifies the archive before writing it: every source `.rb` is
packaged, every `require` and icon path resolves, `ruby -c` passes on each
file, and each file stays inside the `CoordinateCoordinatorTrussAppAMAC`
namespace. Install the result with SketchUp's Extension Manager
(*Install Extension…*).

## Tests

```
ruby tools/test_align_math.rb    # the alignment math, in stock Ruby
ruby tools/test_align_tool.rb    # the tools, against tools/sketchup_stub.rb
```

Neither needs SketchUp. The manual checklist that does is in
`ALIGN_BY_POINTS.md`.

## Icons

```
python3 tools/make_align_icons.py     # regenerates the align_* PNGs
```
