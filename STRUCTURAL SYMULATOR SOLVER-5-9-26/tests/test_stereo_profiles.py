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
        sec = sp.CATALOG['IPE 300']
        assert sec.r_gyr_mm / 10.0 == pytest.approx(12.417, rel=1e-2)

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
