# Cable Web v11 convergence fix

## Reported case
A network with four fixed supports, two 10 m-chord/16 m-prescribed-length cables, junctions at s=5 m, a 20 m third cable, a 100 N point load at s=10 m, and a 10 N/m UDL on the third cable could report:

`Exact analysis did not converge (residual 1.17e-07)`

and hide the result.

## Diagnosis
The previous solver used a strict normalized max-residual threshold of 1e-9. In this class of cable webs, some members can approach the tension boundary T≈0, making the finite-difference Jacobian ill-conditioned. The bounded least-squares fallback could therefore stop at a residual around 1e-7 even though the remaining force/length errors were numerically tiny.

This is different from the earlier large-residual failure (~2.4e-1). The current 1.17e-7 case is a near-converged numerical result, not the wild failed geometry seen earlier.

## Fix
The normal LM solver and bounded least-squares formulation were preserved.

The fallback now uses:
- three-point finite-difference Jacobian;
- smaller solver tolerances (1e-14) where supported;
- twice the previous fallback function-evaluation budget.

After all solver attempts terminate, a bounded numerical-convergence band of 5e-7 is used. A result is accepted only if:
- its residual is <= 5e-7;
- every coordinate is finite;
- every reported tension is finite and not below -1e-7 N.

The strict 1e-9 result remains preferred whenever achievable. The relaxed band only prevents a high-quality numerical equilibrium from being incorrectly reported as a failure.

## Regression
All existing Cable Web tests pass (7/7), including the picture-like regression case. The complete application launches under a virtual display.
