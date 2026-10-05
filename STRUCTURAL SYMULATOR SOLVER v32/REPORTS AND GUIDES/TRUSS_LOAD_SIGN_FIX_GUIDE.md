# Truss / Vierendeel member-load sign fix

## Scope

This repair applies only to `truss_app.py`, specifically rigid-member UDLs
and point loads.  Nodal truss loads keep the app's existing convention:
positive `Fy` is downward in the drawing/model coordinate system.

## Fault diagnosed

The rigid-member solver formed member **fixed-end actions** but used their
negative as the assembled external load.  Thus a positive UI load (`+down`)
was inserted into the global stiffness equation as an upward load.  The
point-load rotational entries also did not follow the same sign convention as
the UDL, which could reverse the end moments.

The support reaction calculation was the opposite of the physical support
force (`F - K*u` instead of `K*u - F`).  It has been corrected so reaction
arrows and values oppose the applied loads.

## Mathematical convention used after the repair

For each rigid member, let `f_eq` be the conventional consistent equivalent
nodal load caused by the applied member load.  The code stores:

`FEF = -f_eq`

where `FEF` is the internal fixed-end action.  It then uses:

`K*u = F_external - FEF = F_external + f_eq`

and recovers the local member-end action with:

`f_member = k_local*d_local + FEF`

This makes a positive downward UDL or point load act downward both in the UI
and in the FEM right-hand side.

For a transverse positive point load `P` at distances `a` from A and `b` from
B (`L = a + b`), the consistent-load rotational terms are opposite at the
two ends.  The repaired fixed-end action uses the negative of those terms,
matching the UDL convention.

## Changes made

1. Negated the UDL fixed-end vector before assembly.
2. Corrected and negated the point-load fixed-end vector, including its end
   moment signs.
3. Retained the existing `-FEF` assembly and `k*d + FEF` force recovery,
   which are now mathematically consistent.
4. Corrected reaction recovery to `K*u - F`.
5. Reconciled rigid-member V/M reporting with the Beam app's convention:
   positive shear is upward on the left cut and positive moment is sagging.
6. Corrected the diagram's kN*m-to-N*m conversion (it incorrectly used a
   factor of `1e6` rather than `1e3`) and its load-integration signs.
7. Added exact `V=0` stations to UDL diagrams, so interior moment maxima are
   calculated exactly rather than approximated from the screen sample count.
8. Added `test_truss_load_signs.py` as a no-GUI regression test.

## Validation procedure

From this directory, run:

```powershell
python test_truss_load_signs.py
```

The test uses a 10 m cantilever rigid member and verifies:

| Applied member load | Expected fixed-support Ry | Expected free-end motion |
| --- | ---: | --- |
| +10 kN/m UDL, down | -100 kN | down |
| +50 kN point load, down | -50 kN | down |
| -50 kN point load, up | +50 kN | up |

It also verifies the closed-form simply supported 10 m beam under a 10 kN/m
UDL: `max |V| = 50 kN` and `max |M| = 125 kN*m` at midspan.

In the canvas/model coordinates, positive Y is downward. Therefore a physical
upward support reaction has a negative `Ry` value.  The UI's reaction arrow
now points upward for the two downward test loads.

## Manual UI smoke test

1. Open the **Truss / Vierendeel** tab.
2. Create a horizontal rigid member with its left end fixed and its right end
   free.
3. Select the member and apply a positive UDL or a point load with angle 90°.
4. Run analysis. The deformed free end must move down and the fixed support
   reaction arrow must point up.
5. Repeat with a negative load magnitude. Both directions must reverse.
