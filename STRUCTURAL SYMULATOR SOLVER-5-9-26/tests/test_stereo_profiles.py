"""Tests for the CIRSOC steel profile catalog (apps/stereo/stereo_profiles.py).

Covers section property computations, catalog structure, unit conversions,
and the helper functions the UI uses to browse and pick profiles.
"""
import math
import pytest

from apps.stereo import stereo_profiles as sp


# ── section geometry ──────────────────────────────────────────────────────

class TestISectionProperties:
    def test_ipe300_area(self):
        sec = sp.CATALOG['IPE 300']
        assert sec.A_mm2 / 100.0 == pytest.approx(51.881, rel=1e-3)

    def test_ipe300_moment_of_inertia(self):
        sec = sp.CATALOG['IPE 300']
        assert sec.Ix_mm4 / 1e4 == pytest.approx(7998.987, rel=1e-3)

    def test_ipe300_torsion_constant(self):
        sec = sp.CATALOG['IPE 300']
        assert sec.J_mm4 / 1e4 == pytest.approx(15.574, rel=1e-2)

    def test_ipe300_radius_of_gyration(self):
        """r_gyr is the MINOR principal radius -- the one a strut buckles
        about -- which for an IPE is about the web axis.

        This test used to assert 12.417 cm, the STRONG-axis radius, and so
        pinned the bug in place: a compression check reading it overstated
        an IPE 300's buckling capacity by (12.42/3.41)^2 = 13x. Published
        (ArcelorMittal / EN 10365): i_y = 12.46 cm strong, i_z = 3.35 cm
        weak. The catalog ignores root fillets, hence the 2% tolerance.
        """
        sec = sp.CATALOG['IPE 300']
        assert sec.r_gyr_mm / 10.0 == pytest.approx(3.35, rel=2e-2)
        assert sec.r_x_mm / 10.0 == pytest.approx(12.417, rel=1e-2)

    def test_all_i_sections_have_positive_properties(self):
        for name, sec in sp.CATALOG.items():
            if sec.shape == 'I':
                assert sec.A_mm2 > 0, f'{name} A_mm2 must be positive'
                assert sec.Ix_mm4 > 0, f'{name} Ix_mm4 must be positive'
                assert sec.J_mm4 > 0, f'{name} J_mm4 must be positive'
                assert sec.r_gyr_mm > 0, f'{name} r_gyr_mm must be positive'


class TestChannelSectionProperties:
    def test_upn_has_positive_properties(self):
        for name, sec in sp.CATALOG.items():
            if sec.shape == 'C':
                assert sec.A_mm2 > 0, f'{name} area'
                assert sec.Ix_mm4 > 0, f'{name} Ix'


class TestRoundTubeProperties:
    def test_thin_wall_area_approximation(self):
        t = sp.RoundTube('test', D=100.0, t=1.0)
        approx_A = math.pi * 100.0 * 1.0
        assert t.A_mm2 == pytest.approx(approx_A, rel=0.02)

    def test_round_tube_shape_label(self):
        t = sp.RoundTube('test', D=100.0, t=5.0)
        assert t.shape == 'CHS'


class TestRectTubeProperties:
    def test_rect_tube_area(self):
        r = sp.RectTube('test', B=100.0, H=50.0, t=5.0)
        expected = 100.0 * 50.0 - (100.0 - 10.0) * (50.0 - 10.0)
        assert r.A_mm2 == pytest.approx(expected)

    def test_square_tube_symmetry(self):
        r = sp.RectTube('test', B=100.0, H=100.0, t=5.0)
        assert r.Ix_mm4 == pytest.approx(r.Iy_mm4, rel=1e-9)


class TestEqualAngleProperties:
    def test_equal_angle_has_positive_properties(self):
        for name, sec in sp.CATALOG.items():
            if sec.shape == 'L':
                assert sec.A_mm2 > 0, f'{name} area'
                assert sec.Ix_mm4 > 0, f'{name} Ix'
                assert sec.r_gyr_mm > 0, f'{name} r_gyr'


# ── catalog structure ─────────────────────────────────────────────────────

def test_catalog_has_at_least_100_profiles():
    assert len(sp.CATALOG) >= 100

def test_catalog_names_returns_all_profiles():
    assert sp.catalog_names() == list(sp.CATALOG.keys())

def test_group_names_covers_all_families():
    groups = sp.group_names()
    assert 'IPE' in groups
    assert 'HEA' in groups
    assert 'HEB' in groups
    assert 'UPN' in groups
    assert any('CHS' in g for g in groups)

def test_profiles_in_group_returns_correct_names():
    ipe_names = sp.profiles_in_group('IPE')
    assert len(ipe_names) > 0
    for name in ipe_names:
        assert name.startswith('IPE')
        assert name in sp.CATALOG

def test_profiles_in_unknown_group_returns_empty():
    assert sp.profiles_in_group('NONEXISTENT') == []

def test_every_catalog_entry_belongs_to_a_group():
    all_in_groups = set()
    for g in sp.group_names():
        for name in sp.profiles_in_group(g):
            all_in_groups.add(name)
    assert all_in_groups == set(sp.CATALOG.keys())


# ── section_to_props conversion ──────────────────────────────────────────

def test_section_to_props_units():
    sec = sp.CATALOG['IPE 300']
    props = sp.section_to_props(sec, sp.STEEL_F24)
    assert 'A' in props and 'I' in props and 'J' in props and 'r_gyr' in props
    assert 'E' in props and 'Fy' in props and 'Fu' in props
    assert props['A'] == pytest.approx(sec.A_mm2 / 100.0)
    assert props['I'] == pytest.approx(sec.Ix_mm4 / 1e4)
    assert props['J'] == pytest.approx(sec.J_mm4 / 1e4)
    assert props['r_gyr'] == pytest.approx(sec.r_gyr_mm / 10.0)
    assert props['E'] == pytest.approx(200.0)
    assert props['Fy'] == pytest.approx(235.0)
    assert props['Fu'] == pytest.approx(360.0)

def test_section_to_props_without_material_omits_E_Fy_Fu():
    sec = sp.CATALOG['IPE 300']
    props = sp.section_to_props(sec)
    assert 'A' in props
    assert 'E' not in props
    assert 'Fy' not in props
    assert 'Fu' not in props

def test_section_to_props_f36_material():
    sec = sp.CATALOG['IPE 200']
    props = sp.section_to_props(sec, sp.STEEL_F36)
    assert props['Fy'] == pytest.approx(345.0)
    assert props['Fu'] == pytest.approx(450.0)


# ── profile_summary ──────────────────────────────────────────────────────

def test_profile_summary_contains_area():
    s = sp.profile_summary('IPE 300')
    assert 'A=' in s
    assert 'cm²' in s or 'cm' in s

def test_profile_summary_unknown_returns_name():
    assert sp.profile_summary('No Such Profile') == 'No Such Profile'


# ── materials ─────────────────────────────────────────────────────────────

def test_steel_f24_values():
    assert sp.STEEL_F24.Fy == 235.0
    assert sp.STEEL_F24.Fu == 360.0
    assert sp.STEEL_F24.E == pytest.approx(200_000.0)

def test_steel_f36_values():
    assert sp.STEEL_F36.Fy == 345.0
    assert sp.STEEL_F36.Fu == 450.0


# ── the radius a strut buckles about (fixed 2026-09-30) ──────────────────────
#
# r_gyr used to be sqrt(Ix/A) -- the STRONG axis -- for every shape, which
# overstated compression capacity by up to 26x (Euler load) for I-sections
# and 30x for channels. These pin the corrected values to PUBLISHED tables,
# not to the code's own arithmetic, so a regression cannot pass by agreeing
# with itself.

import math as _math


def test_every_section_uses_its_minor_radius_for_buckling():
    """r_gyr can never exceed the strong-axis radius: it is the minimum."""
    for name, sec in sp.CATALOG.items():
        assert sec.r_gyr_mm <= sec.r_x_mm * (1 + 1e-9), name


def test_doubly_symmetric_sections_use_the_smaller_of_their_two_axes():
    for name, sec in sp.CATALOG.items():
        if sec.shape in ('I', 'C', 'RHS'):
            want = _math.sqrt(min(sec.Ix_mm4, sec.Iy_mm4) / sec.A_mm2)
            assert sec.r_gyr_mm == pytest.approx(want, rel=1e-12), name


def test_an_i_section_buckles_about_its_web_axis():
    """Published ArcelorMittal: IPE 200 i_z = 2.24 cm (weak), i_y = 8.26 cm."""
    sec = sp.CATALOG['IPE 200']
    assert sec.r_gyr_mm / 10.0 == pytest.approx(2.24, rel=3e-2)
    assert sec.r_x_mm / 10.0 == pytest.approx(8.26, rel=3e-2)


def test_a_round_tube_is_unchanged_because_it_was_always_right():
    for name, sec in sp.CATALOG.items():
        if sec.shape == 'CHS':
            assert sec.r_gyr_mm == pytest.approx(sec.r_x_mm, rel=1e-12), name


def test_an_angle_buckles_about_its_minor_principal_axis():
    """The case min(Ix, Iy) cannot find: for an equal angle Ix == Iy, and
    the axis it actually buckles about is v-v, at 45 degrees to the legs.
    Published EN 10056-1, L 50x50x5: r_v = 0.98 cm, r_x = 1.51 cm."""
    sec = sp.CATALOG['L 50x5']
    assert sec.r_gyr_mm / 10.0 == pytest.approx(0.98, rel=2e-2)
    assert sec.r_x_mm / 10.0 == pytest.approx(1.51, rel=3e-2)


def test_the_angle_moment_of_inertia_matches_the_published_table():
    """The old closed form gave 13.09 cm4 for L 50x5; published is 11.00.
    Exact two-rectangle geometry gives 11.25 -- the remaining 2% is the
    root radius, which the catalog does not model for any shape."""
    sec = sp.CATALOG['L 50x5']
    assert sec.Ix_mm4 / 1e4 == pytest.approx(11.0, rel=3e-2)


def test_an_angles_minor_radius_is_about_two_thirds_of_its_geometric_one():
    """A structural rule of thumb for equal angles, r_v ~ 0.64 r_x -- a
    check that the principal-axis maths has the right shape, independent of
    any one tabulated section."""
    for name, sec in sp.CATALOG.items():
        if sec.shape == 'L':
            assert 0.60 < sec.r_gyr_mm / sec.r_x_mm < 0.68, (
                name, sec.r_gyr_mm / sec.r_x_mm)


# ── the depth a bending check needs ──────────────────────────────────────────

def test_every_catalog_shape_now_has_an_extreme_fibre_depth():
    """section_to_props looked for `d` or `h`; CHS, RHS and angles spell it
    D, H and leg, so they never had one."""
    for name, sec in sp.CATALOG.items():
        assert sec.c_mm > 0, name
        assert sp.section_to_props(sec)['c_cm'] == pytest.approx(sec.c_mm / 10.0)


@pytest.mark.parametrize('name,attr', [('IPE 200', 'd'), ('UPN 100', 'd')])
def test_open_sections_are_half_their_depth(name, attr):
    sec = sp.CATALOG[name]
    assert sec.c_mm == pytest.approx(getattr(sec, attr) / 2.0)


def test_a_tube_is_half_its_outer_dimension():
    for name, sec in sp.CATALOG.items():
        if sec.shape == 'CHS':
            assert sec.c_mm == pytest.approx(sec.D / 2.0), name
        if sec.shape == 'RHS':
            assert sec.c_mm == pytest.approx(sec.H / 2.0), name


def test_an_angles_depth_is_most_of_the_leg_because_its_centroid_is_at_the_heel():
    """What a thin-tube guess cannot see, and why it is 39% unsafe for an
    angle. Published L 50x5: centroid 14.0 mm from the heel, so the far
    fibre is 36 mm out -- not the ~23 mm a tube-shaped guess gives."""
    sec = sp.CATALOG['L 50x5']
    assert sec.c_mm == pytest.approx(50.0 - 14.0, rel=3e-2)


# ── carrying a section onto a member without leaving a stale depth ───────────

def test_write_section_carries_the_depth_when_there_is_one():
    m = {}
    sp.write_section(m, dict(A=10.0, I=100.0, r_gyr=2.0, c_cm=5.0))
    assert m['c_cm'] == 5.0


def test_write_section_removes_a_stale_depth_rather_than_leaving_it():
    """A small catalog depth left beside a larger hand-typed I gives
    S = I/c too big: bending capacity overstated by the ratio of the two
    sections. update() only adds keys, which is how that would happen."""
    m = {'A': 5.0, 'I': 20.0, 'c_cm': 3.0}
    sp.write_section(m, dict(A=50.0, I=900.0, r_gyr=4.0))
    assert 'c_cm' not in m
    assert m['I'] == 900.0


def test_write_section_only_touches_section_keys():
    m = {'a': 0, 'b': 1, 'role': 'chord', 'conn': 'rigid'}
    sp.write_section(m, dict(A=10.0, I=100.0))
    assert (m['a'], m['b'], m['role'], m['conn']) == (0, 1, 'chord', 'rigid')


def test_a_remembered_depth_holds_only_while_I_is_unchanged():
    assert sp.depth_still_valid((5.0, 400.0), 400.0)
    assert sp.depth_still_valid((5.0, 400.0), 400.0000001)   # float noise
    assert not sp.depth_still_valid((5.0, 400.0), 401.0)     # a new section
    assert not sp.depth_still_valid(None, 400.0)
    assert not sp.depth_still_valid((0.0, 400.0), 400.0)
    assert not sp.depth_still_valid((5.0, 400.0), 'not a number')


# ── the properties box ─────────────────────────────────────────────────────

def test_the_properties_box_names_both_radii_and_which_one_buckles():
    rows = {r[0]: r for r in sp.section_properties('IPE 200')}
    for sym in ('A', 'Ix', 'Iy', 'J', 'rx', 'r min', 'c', 'Wx', 'mass'):
        assert sym in rows, sym
    sec = sp.CATALOG['IPE 200']
    assert rows['r min'][1] == '%.2f' % (sec.r_gyr_mm / 10.0)
    assert 'buckling' in rows['r min'][3]
    assert float(rows['rx'][1]) > float(rows['r min'][1])
    assert 'strong' in rows['Ix'][3] and 'weak' in rows['Iy'][3]


def test_the_properties_box_agrees_with_what_members_are_given():
    props = sp.section_to_props(sp.CATALOG['HEA 200'])
    rows = {r[0]: r for r in sp.section_properties('HEA 200')}
    assert float(rows['A'][1]) == pytest.approx(props['A'], abs=0.005)
    assert float(rows['Ix'][1]) == pytest.approx(props['I'], abs=0.05)
    assert float(rows['c'][1]) == pytest.approx(props['c_cm'], abs=0.05)
    assert float(rows['Wx'][1]) == pytest.approx(props['I'] / props['c_cm'],
                                                 abs=0.05)
    assert float(rows['mass'][1]) == pytest.approx(props['A'] * 0.785,
                                                   abs=0.005)


def test_an_angle_is_described_by_its_legs_and_its_v_axis():
    rows = {r[0]: r for r in sp.section_properties('L 50x5')}
    assert 'Iv' in rows, 'the axis an angle actually buckles about'
    assert 'leg' in rows['Ix'][3]
    assert 'strong' not in rows['Ix'][3]
    assert rows['r min'][1] == '0.98', 'EN 10056-1 r_v for L 50x5'


def test_a_round_tube_has_no_strong_axis():
    rows = {r[0]: r for r in sp.section_properties('CHS 76.1x3.6')}
    assert 'any axis' in rows['Ix'][3]


def test_a_hand_typed_section_has_no_table_row():
    assert sp.section_properties('my own section') == []


def test_a_square_tube_has_no_strong_axis_either():
    rows = {r[0]: r for r in sp.section_properties('SHS 200x200x8')}
    assert 'either axis' in rows['Ix'][3]
    rows = {r[0]: r for r in sp.section_properties('RHS 200x100x6')}
    assert 'strong' in rows['Ix'][3]
