"""shell_wind.py -- wind velocity pressure per CIRSOC 102-2005, and a few
starting-point pressure-coefficient patterns for a shell roof. 2026-09-14.

SOURCE. Transcribed from the CIRSOC 102-2005 tables reproduced in the FAUD
UNMdP guide "Accion del viento" (Downloads/guia viento torre cirsoc2005.pdf):

    qz = 0.613 * Kz * Kzt * Kd * V^2 * I          [N/m^2, V in m/s]     (art. 5.10)
    Kz = 2.01 (z/zg)^(2/alpha)   for 5 m <= z <= zg                    (Tabla 5, nota 2)
    Kz = 2.01 (5/zg)^(2/alpha)   for z < 5 m
    Caso 1 only: z not taken below 30 m in exposure A, nor 10 m in B.
    alpha, zg ........................................................ Tabla 4
    I (categoria I..IV) = 0.87, 1.00, 1.15, 1.15 ........................ Tabla 1
    Kd = 0.85 for buildings and for vaulted roofs ("cubiertas abovedadas") Tabla 6
    G = 0.85 for a rigid structure (natural frequency >= 1 Hz) ......... 5.8
    V: Figura 1A (map) / 1B (cities), 3-s gust at 10 m, exposure C.

WHAT CIRSOC 102 DOES NOT GIVE. Pressure coefficients for a hyperbolic
paraboloid, or any doubly curved roof. The patterns in CP_PRESETS are
therefore STARTING POINTS for the user to edit -- labelled approximate
everywhere they appear -- and the design wind on a real shell should come
from a wind-tunnel study or published measurements on the same form. The
tab does not pretend otherwise.

SIGN (CIRSOC 102 convention, repeated by the guide): a POSITIVE pressure
acts TOWARD the surface, a negative one away from it (suction). On a roof,
the tab applies p = qz * G * Cp on the upper face, so positive pushes the
shell down along -n and negative lifts it.
"""
EXPOSURE = {       # Tabla 4: alpha, zg (m)
    'A': (5.0, 457.0),
    'B': (7.0, 366.0),
    'C': (9.5, 274.0),
    'D': (11.5, 213.0),
}
EXPOSURE_LABELS = {
    'A': 'A  large city centres (>= 50% of buildings over 20 m)',
    'B': 'B  urban / suburban, wooded, many close obstructions',
    'C': 'C  open terrain with scattered obstructions under 10 m',
    'D': 'D  flat unobstructed coast, wind from open water',
}
IMPORTANCE = {'I': 0.87, 'II': 1.00, 'III': 1.15, 'IV': 1.15}
KD_BUILDING = 0.85
G_RIGID = 0.85

#: Figura 1B -- basic wind speed V (m/s) by city
CITY_V = {
    'Bahia Blanca': 55.0, 'Bariloche': 46.0, 'Buenos Aires': 45.0,
    'Catamarca': 43.0, 'Comodoro Rivadavia': 67.5, 'Cordoba': 45.0,
    'Corrientes': 46.0, 'Formosa': 45.0, 'La Plata': 46.0, 'La Rioja': 44.0,
    'Mar del Plata': 51.0, 'Mendoza': 39.0, 'Neuquen': 48.0, 'Parana': 52.0,
    'Posadas': 45.0, 'Rawson': 60.0, 'Resistencia': 45.0,
    'Rio Gallegos': 60.0, 'Rosario': 50.0, 'Salta': 35.0, 'Santa Fe': 51.0,
    'San Juan': 40.0, 'San Luis': 45.0, 'San Miguel de Tucuman': 40.0,
    'San Salvador de Jujuy': 34.0, 'Santa Rosa': 50.0,
    'Santiago del Estero': 43.0, 'Ushuaia': 60.0, 'Viedma': 60.0,
}


def Kz(z, exposure='C', case=2):
    """Velocity-pressure exposure coefficient (Tabla 5 note 2)."""
    alpha, zg = EXPOSURE[exposure]
    z = float(z)
    if case == 1:
        if exposure == 'A':
            z = max(z, 30.0)
        elif exposure == 'B':
            z = max(z, 10.0)
    z = min(max(z, 5.0), zg)
    return 2.01 * (z / zg) ** (2.0 / alpha)


def velocity_pressure(V, z, exposure='C', category='II', Kzt=1.0,
                      Kd=KD_BUILDING, case=2):
    """qz in N/m^2 (art. 5.10)."""
    return 0.613 * Kz(z, exposure, case) * Kzt * Kd * float(V) ** 2 * IMPORTANCE[category]


# Starting-point Cp patterns, as formulas the user sees and edits. They use
# the plan limits x0, x1, y0, y1 that the tab puts in scope for loads.
CP_PRESETS = {
    'Uplift, uniform (Cp = -0.8)': '-0.8',
    'Pressure, uniform (Cp = +0.4)': '0.4',
    'Wind along +x: windward half down, leeward half up':
        'If(x < (x0+x1)/2, 0.5, -0.8)',
    'Wind along +x: linear +0.5 -> -0.8': '0.5 - 1.3*(x - x0)/(x1 - x0)',
    'Wind along +y: linear +0.5 -> -0.8': '0.5 - 1.3*(y - y0)/(y1 - y0)',
}
CP_NOTE = ('CIRSOC 102 gives no pressure coefficients for a hypar or other '
           'doubly curved roof. These patterns are starting points only; use '
           'wind-tunnel or published data for the actual form.')


def describe(V, z, exposure, category, Kzt=1.0, Kd=KD_BUILDING, G=G_RIGID, case=2):
    """Lines of text showing the velocity-pressure calculation step by step."""
    alpha, zg = EXPOSURE[exposure]
    kz = Kz(z, exposure, case)
    I = IMPORTANCE[category]
    q = velocity_pressure(V, z, exposure, category, Kzt, Kd, case)
    return [
        f'CIRSOC 102-2005 velocity pressure (art. 5.10)',
        f'  V = {V:g} m/s   exposure {exposure} (alpha = {alpha:g}, zg = {zg:g} m)',
        f'  z = {z:g} m  ->  Kz = 2.01 (max(z,5)/zg)^(2/alpha) = {kz:.3f}',
        f'  Kzt = {Kzt:g}   Kd = {Kd:g}   I (cat. {category}) = {I:g}',
        f'  qz = 0.613 Kz Kzt Kd V^2 I = {q:.1f} N/m^2 = {q/1000:.3f} kN/m^2',
        f'  design pressure p = qz G Cp with G = {G:g}',
    ]


def _selftest():
    # Tabla 5, exposure C, z = 10 m -> Kz = 1.00; exposure A caso 2, z = 5 m -> 0.33
    assert abs(Kz(10, 'C') - 1.00) < 0.005
    assert abs(Kz(4, 'A') - 0.330) < 0.002
    # the guide's own example: Neuquen V = 48 m/s, exp. A, z = 64 m -> 1098.45 N/m^2
    assert abs(velocity_pressure(48, 64, 'A') - 1098.45) < 1.0
    return True


if __name__ == '__main__':
    print(_selftest())
    print('\n'.join(describe(45, 8, 'C', 'II')))
