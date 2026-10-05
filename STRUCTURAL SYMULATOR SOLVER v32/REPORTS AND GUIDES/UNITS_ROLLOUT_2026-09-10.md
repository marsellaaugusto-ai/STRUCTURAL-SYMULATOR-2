# The unit selector, finished across all six tabs — 2026-09-10

`LOAD_SCALING_AND_UNITS_2026-09-10.md` shipped `units.py`, the selector above
the notebook, and the Beam tab wired end to end. It closed by saying the other
five tabs were **not** wired, that they kept showing their own units, and that
the pattern to follow was mechanical. This finishes that.

All six tabs now follow the selector. Nothing about the way any tab computes
changed.

---

## 1 · The machinery moved out of the Beam tab

The Beam tab was wired by hand. Repeating that five more times would have meant
six copies of the same four ideas, which is how two tabs end up disagreeing
about what a kip is. `common.UnitsMixin` now holds them, and each tab supplies
only what is genuinely its own: which of its fields are which physical
quantity, and what to repaint.

A tab mixes it in, calls `init_units(repaint=...)` once, and then uses four
things: `u(quantity)` for a label, `show`/`store` to cross the boundary,
`unit_label` to register a label that names a unit, and `unit_var` to register
an entry box.

### The one thing that had to be got right

The first version converted each entry box **in place** on every switch. That
sent every value on a round trip through the *displayed* number, and a
displayed number has to be rounded to stay readable. Measured on the Cable tab:

| | value |
|---|---|
| stored span | 20 m |
| shown under AISC | 65.6168 ft |
| read back | 20.00000064 m |

Small, but it broke the property the whole feature rests on — and it did so
silently, in the direction of a saved model. The fix is that a registered box
keeps the exact figure it was given, in storage units: a switch repaints the
box from that figure rather than from what the box happens to say, and the
figure is re-read only when the user has actually typed something different.
Switching to AISC and back is now exact, and there is a test per tab that says
so.

---

## 2 · Storage is not uniform across the tabs, and pretending it was would have
corrupted data

This is the part that made the rollout more than mechanical. The six tabs do
**not** hold their numbers in the same units, and never have:

| tab | length | force | moment | stress | notes |
|---|---|---|---|---|---|
| Beam, Arch, Cable | m | kN | kN·m | kN/cm² | the app's original convention |
| Truss | m | kN | kN·m | **MPa** | plate yield has always been typed in MPa |
| Cable Web | m | **N** | — | — | self-weight in N/m |
| Perforated Beam | **mm** | **N** | **N·mm** | MPa | CIRSOC 301 works in mm and MPa |

Assuming one storage convention would not have been a cosmetic error. Read as
metres, a Perforated Beam span of 8000 mm becomes an eight-kilometre beam.

So each tab declares what it actually stores, with
`units.storage_like(...)`, and every conversion is taken relative to that
declaration. Changing any tab's storage instead would have silently
reinterpreted every model already saved in it.

`test_units_in_every_tab.py` asserts the declaration exists and is complete for
every quantity, on every tab — a tab that inherits the default storage without
meaning to is the one way this layer could still corrupt data.

---

## 3 · A third kind of length

Wiring the Truss tab turned up a real modelling gap. A plate thickness of 8 mm
was being shown as **0.8 cm** under CIRSOC, because plate thickness had been
mapped to the same quantity as a fibre distance.

Both are lengths at section scale. They are never the same unit on a drawing: a
CIRSOC or Eurocode drawing says an 8 mm plate and a 20 cm fibre distance, and
being handed either in the other's unit is friction at best and a
misread dimension at worst. So `units.py` now has three lengths, not two:

| quantity | what it is | CIRSOC | AISC |
|---|---|---|---|
| `length` | a span, a station along the member | m | ft |
| `section_length` | a fibre distance, a flange dimension | cm | in |
| `detail_length` | a plate thickness, a weld leg, a bolt spacing | **mm** | in |

Adding it took `units.py` from 10 quantities to 11, and its own test file from
127 tests to 137 without writing a new one — several of those tests are
parametrised over the quantity list.

---

## 4 · What each tab now does

**Truss.** Coordinates, polar distance, material E/A/I, node loads, rod UDL and
point load, guide geometry, all three array tools, plate and bolt dimensions,
the three result panels, the selection panel, the rod tooltip, the joint
free-body window, the plate check report and the Vierendeel diagrams. Plate
yield and electrode strength stay MPa-stored and are declared as such.

**Arch.** Span, rise, weight and wind intensity, the full section panel, point
and distributed loads, the probe, the results text, the diagram tooltips, and
all four diagram panels — captions, plotted values, axis ticks and the
`max ±…` readout convert at the single point where the values leave SI, so
those four can never disagree about which convention they are in.

**Cable.** Span, cable length, support heights, section area and allowable
tension, both tables and their headings, the point-load dialog, the probe
readout, the results text and both diagram bands.

**Perforated Beam.** Span, material, bracing length, stiffener spacing, support
positions, opening dimensions and positions, load positions and magnitudes, and
both lists. Under the app's own SI convention a span now reads **8 m** rather
than 8000 mm, which is what its report already did for span-scale lengths.

**Cable Web.** Node coordinates and point loads, cable prescribed length and
self-weight, load positions and magnitudes, the junction dialog, the tension
readouts and the diagram captions.

### Two fields that could not simply be registered

The load magnitude on the Perforated Beam and Cable Web tabs is whatever the
chosen load **type** makes it — a force, a moment, or a force per unit length.
Its unit is therefore looked up at the moment it is needed rather than fixed
when the box was built, and each row of the load list is written in the unit
its own type implies. Changing the type relabels the box without touching the
number: converting it too would silently turn a 10 kN point load into a moment
of a different size.

### Two things deliberately left in storage units

**User-written expressions.** `q(x)` on the Beam, Arch and Cable tabs, and
`y = f(x)` on the Truss tab, are formulas the user wrote. Re-reading `2*x^2` in
another convention would change what it means rather than how it is written.
The bounds beside them convert; the expression does not, and the label now says
so outright in every convention instead of leaving it to be guessed.

**Fabrication detail from the section modules.** Weld legs, part gaps and ring
thicknesses come back from `opening_reinforcement`, `assembly_check` and
`welded_section_math` as finished text. Those modules are unit-pure by design
and none of them imports this presentation layer. Their lines stay in mm, and
the Perforated Beam results header says exactly that rather than leaving the
reader to notice.

---

## 5 · Verified on each tab, same model, same instant

Every figure below was read off the real widget with the tab built, loaded and
analysed, switching only the selector between the two columns.

| tab | field | CIRSOC | AISC |
|---|---|---|---|
| Truss | material E | 200.0 GPa | 29 008 ksi |
| Truss | material A | 10.0 cm² | 1.550 in² |
| Truss | plate thickness | 8.0 mm | 0.315 in |
| Truss | bolt pitch | 60.0 mm | 2.362 in |
| Truss | max tension | 75.00 kN | 16.86 kip |
| Arch | span | 20.0 m | 65.617 ft |
| Arch | weight w | 10.0 kN/m | 0.685 kip/ft |
| Arch | I | 20 000 cm⁴ | 480.5 in⁴ |
| Arch | max moment | 38.99 kN·m | 28.76 kip·ft |
| Cable | span | 20.0 m | 65.617 ft |
| Cable | horizontal thrust | 37.69 kN | 8.47 kip |
| Cable | fibre stress | 45.227 MPa | 6.560 ksi |
| Perforated | span | 8.0 m | 26.247 ft |
| Perforated | Fy | 250.0 MPa | 36.259 ksi |
| Perforated | E | 200.0 GPa | 29 008 ksi |
| Perforated | opening diameter | 250 mm | 9.843 in |

and on every one of them the stored model came back **byte for byte identical**
across the switch, and identical again after switching back.

---

## 6 · Two defects the checks caught before anyone else could

Both were found by building the real tab and reading the real widget, not by
reading the code — which is the only way either would have shown up.

**The Cable tab's span and cable-length boxes did not follow the switch.** The
labels changed to feet, the numbers did not, and `_current_state()` then read
20 as *20 feet*, storing a 6.096 m span. A model would have shrunk to a third
of its size on a switch that was supposed to change nothing.

**A plate thickness read 0.8 cm.** Correct arithmetic, wrong unit for the
field, and the cause of the third length quantity in section 3.

---

## 7 · Tests

| file | tests | what it holds |
|---|---|---|
| `test_units.py` | 137 | every conversion pinned against a published equivalent |
| `test_units_in_beam_tab.py` | 11 | the Beam tab, wired first |
| `test_units_in_every_tab.py` | new | the other five, same property |

The central assertion in the new file is parametrised over five tabs and four
foreign conventions: switching never rewrites stored state. Its complements are
that switching there and back is exact, that every tab declares its storage,
and — on the Arch and Cable tabs — that re-running the analysis under a
different convention returns the identical SI answer, which is what would catch
a conversion applied to the model instead of to the label.

One test watches for a leak rather than a wrong number: a destroyed tab must
stop listening to the selector. Hundreds of tabs are built and torn down across
this suite, and a listener still holding a dead widget would be called on every
switch for the rest of the session.
