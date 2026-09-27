"""The two hand-out artefacts -- the SketchUp extension (.rbz) and the
whole-app archive (.zip) -- must match the sources they claim to be built
from.

This exists because the .rbz that shipped before it did not: it was zipped
by hand and left out model_import.rb and xlsx_reader.rb entirely, so the
extension's own "Import from Stereo…" menu command raised LoadError the
moment SketchUp loaded it. Nothing in the suite noticed, because nothing
in the suite had ever opened the archive.
"""
import os
import sys
import zipfile

import pytest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, 'tools'))

import build_release as br   # noqa: E402


# ── the extension ─────────────────────────────────────────────────────────

def test_plugin_sources_include_every_file_the_loader_requires():
    names = {n for n, _ in br.plugin_files()}
    missing = [r for r in br.REQUIRED_RB if r not in names]
    assert not missing, f'sketchup_plugin/ is missing {missing}'


def test_every_require_in_the_plugin_resolves_to_a_shipped_file():
    """main.rb's `require File.join(MY_DIR, 'x')` lines name the files the
    extension cannot start without -- read them out of the source rather
    than trusting REQUIRED_RB to have been kept up to date by hand."""
    import re
    main = os.path.join(br.PLUGIN_DIR, br.PLUGIN_NAME, 'main.rb')
    src = open(main).read()
    required = re.findall(r"require File\.join\(MY_DIR, '([^']+)'\)", src)
    assert required, 'main.rb should require its sibling modules'
    names = {n for n, _ in br.plugin_files()}
    for mod in required:
        assert f'{br.PLUGIN_NAME}/{mod}.rb' in names, mod


def test_the_shipped_rbz_holds_exactly_the_current_plugin_sources():
    """Byte-for-byte, not just by name: a stale archive with the right
    filenames is the same bug wearing a hat."""
    rbz = os.path.join(APP, br.RBZ_NAME)
    assert os.path.isfile(rbz), 'the .rbz is a shipped artefact; build it'
    with zipfile.ZipFile(rbz) as z:
        shipped = {i.filename: z.read(i.filename) for i in z.infolist()
                   if not i.is_dir()}
    on_disk = {name: open(disk, 'rb').read() for name, disk in br.plugin_files()}

    assert set(shipped) == set(on_disk), (
        f'only in the .rbz: {sorted(set(shipped) - set(on_disk))}; '
        f'only on disk: {sorted(set(on_disk) - set(shipped))} — '
        f'run python3 tools/build_release.py --rbz')
    stale = [n for n in on_disk if shipped[n] != on_disk[n]]
    assert not stale, (f'{stale} differ from sketchup_plugin/ — '
                       f'run python3 tools/build_release.py --rbz')


def test_the_rbz_declares_a_version_and_a_description():
    """SketchUp's Extension Manager decides whether to offer an update
    from the version string, so a release that changes the extension has
    to change it too."""
    rbz = os.path.join(APP, br.RBZ_NAME)
    with zipfile.ZipFile(rbz) as z:
        loader = z.read(f'{br.PLUGIN_NAME}.rb').decode('utf-8')
    assert 'SketchupExtension.new' in loader
    assert 'ex.description' in loader
    import re
    m = re.search(r"ex\.version\s*=\s*'([0-9]+\.[0-9]+\.[0-9]+)'", loader)
    assert m, 'the loader must set a semantic ex.version'
    major, minor, patch = (int(p) for p in m.group(1).split('.'))
    assert (major, minor, patch) >= (0, 2, 0), (
        'the import feature shipped at 0.2.0; do not regress the version')


def test_build_rbz_refuses_to_ship_an_incomplete_archive(tmp_path, monkeypatch):
    """The guard itself has to work, or it is decoration."""
    monkeypatch.setattr(br, 'REQUIRED_RB',
                        br.REQUIRED_RB + ('not_a_real_module.rb',))
    with pytest.raises(SystemExit):
        br.build_rbz(dest=str(tmp_path / 'x.rbz'))


def test_build_rbz_round_trips_into_a_loadable_archive(tmp_path):
    dest = str(tmp_path / 'built.rbz')
    path, files = br.build_rbz(dest=dest)
    assert path == dest and os.path.isfile(dest)
    assert br.verify_rbz(dest) is True
    with zipfile.ZipFile(dest) as z:
        assert z.testzip() is None
        # the loader must sit at the archive ROOT, beside its folder --
        # SketchUp's Extension Manager will not find it anywhere else
        assert f'{br.PLUGIN_NAME}.rb' in z.namelist()
        assert any(n.startswith(f'{br.PLUGIN_NAME}/') for n in z.namelist())


@pytest.mark.skipif(not __import__('shutil').which('ruby'),
                    reason='ruby not installed on this host')
def test_every_shipped_ruby_file_parses():
    assert br.ruby_syntax_check(br.plugin_files())


# ── the app archive ───────────────────────────────────────────────────────

def test_app_archive_carries_the_app_and_the_extension():
    names = {n for n, _ in br.app_files()}
    for must in ('main.py', 'common.py', 'cirsoc_301.py', 'units.py',
                 'apps/stereo/stereo_app.py', 'apps/stereo/stereo_reports.py',
                 'apps/truss/truss_app.py', 'tests/test_stereo_reports.py',
                 'tools/build_release.py', br.RBZ_NAME):
        assert must in names, must


def test_app_archive_leaves_out_caches_and_compiled_files():
    names = [n for n, _ in br.app_files()]
    assert not [n for n in names if '__pycache__' in n]
    assert not [n for n in names if n.endswith(('.pyc', '.pyo'))]
    assert not [n for n in names if '.pytest_cache' in n]


def test_build_zip_produces_a_readable_archive_rooted_in_one_folder(tmp_path):
    dest = str(tmp_path / 'app.zip')
    br.build_zip(dest=dest)
    with zipfile.ZipFile(dest) as z:
        assert z.testzip() is None
        roots = {n.split('/', 1)[0] for n in z.namelist()}
        assert len(roots) == 1, f'the archive must unpack into ONE folder: {roots}'
        root = roots.pop()
        assert f'{root}/main.py' in z.namelist()
