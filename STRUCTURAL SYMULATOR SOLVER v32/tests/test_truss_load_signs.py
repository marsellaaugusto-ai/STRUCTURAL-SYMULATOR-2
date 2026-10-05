"""Regression checks for rigid-member UDL and point-load directions.

Run with: python test_truss_load_signs.py
"""
from apps.truss.truss_app import analyze, compute_diagrams


NODES = [(0.0, 0.0), (240.0, 0.0)]  # 10 m because PX_PER_M = 24
SUPPORTS = [{'node': 0, 'type': 'fixed'}]
RIGID_MEMBER = {
    'a': 0, 'b': 1, 'E': 200.0, 'A': 10.0, 'I': 8000.0, 'conn': 'rigid',
}


def solve(rod):
    result, error = analyze(NODES, [rod], [], SUPPORTS)
    assert error is None, error
    return result['reactions'][0]['ry'], result['node_res'][1]['uy']


def main():
    ry, uy = solve({**RIGID_MEMBER, 'udl': 10.0, 'udl_rotation_deg': 0.0})
    assert abs(ry + 100.0) < 1e-7 and uy > 0.0

    ry, uy = solve({**RIGID_MEMBER, 'point_loads': [
        {'P': 50.0, 't': 0.5, 'angle_deg': 90.0},
    ]})
    assert abs(ry + 50.0) < 1e-7 and uy > 0.0

    ry, uy = solve({**RIGID_MEMBER, 'point_loads': [
        {'P': -50.0, 't': 0.5, 'angle_deg': 90.0},
    ]})
    assert abs(ry - 50.0) < 1e-7 and uy < 0.0

    # Exact simply-supported UDL benchmark: V(x)=50-10x kN and
    # M(x)=50x-5x² kN*m.  The maximum sagging moment is 125 kN*m at x=5 m.
    rod = {**RIGID_MEMBER, 'udl': 10.0, 'udl_rotation_deg': 0.0}
    result, error = analyze(NODES, [rod], [], [
        {'node': 0, 'type': 'pin'}, {'node': 1, 'type': 'rollerX'},
    ])
    assert error is None, error
    diagram = compute_diagrams(NODES, [rod], [], result)[0]
    peak = max(abs(moment) for moment in diagram['M'])
    assert abs(peak - 125.0) < 1e-7, peak
    mid = min(range(len(diagram['xs'])), key=lambda i: abs(diagram['xs'][i] - 5.0))
    assert abs(diagram['xs'][mid] - 5.0) < 1e-7
    assert abs(diagram['V'][mid]) < 1e-7
    assert abs(diagram['M'][mid] - 125.0) < 1e-7

    print('PASS: rigid-member load signs and exact V/M maxima are correct.')


def test_truss_load_signs():
    """pytest entry point.

    This file has always defined only `main()`. pytest collects by the `test_`
    prefix, so it collected NOTHING from here -- the checks below have never
    run as part of `pytest -q`, and the Truss tab's "one existing test" was in
    practice zero. Found while acting on DIAGNOSIS_TRUSS_2026-09-05 T-4. The
    script form still works; this only makes the suite see it.
    """
    main()


if __name__ == '__main__':
    main()
