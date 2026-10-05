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


# ── how the delivered archives are named ──────────────────────────────────
# Asked for on 2026-09-30: every archive handed out carries its version and
# the moment it was built, so a zip sitting in a downloads folder can be told
# apart from the four earlier ones without opening it.

def test_the_stamp_carries_version_date_and_time():
    import re
    stamp = br.build_stamp()
    # The version token may carry an EDITION ('v32st01'), which is what tells
    # an edited build apart from the release it came off -- the whole point
    # of the name, so the pattern allows it rather than rejecting it.
    assert re.fullmatch(r'v\d+[a-z]*\d*_\d{4}-\d{2}-\d{2}_\d{4}', stamp), stamp
    assert stamp.startswith('v%d' % br.APP_VERSION)
    assert stamp.startswith(br.version_tag() + '_')


def test_an_edition_is_visible_in_every_archive_name():
    """An edited build in a downloads folder must not read as the release."""
    if not br.APP_EDITION:
        assert br.version_tag() == 'v%d' % br.APP_VERSION
        return
    assert br.APP_EDITION in br.version_tag()
    assert br.APP_EDITION in br.stamped(br.ZIP_BASE, '.zip')
    assert br.stamp_text().split()[2] == br.APP_EDITION


def test_the_edition_is_not_folded_into_the_version_number():
    """APP_VERSION stays an int: the build script formats it with %d, appinfo
    parses it with int(), and the archive series counts on it."""
    assert isinstance(br.APP_VERSION, int)
    assert br.APP_EDITION is None or isinstance(br.APP_EDITION, str)
    assert int(br.stamp_text().split()[0]) == br.APP_VERSION


def test_the_version_lives_in_exactly_one_place():
    """A number spelled into a filename template as well as into APP_VERSION
    is a number that will disagree with itself."""
    src = open(os.path.join(APP, 'tools', 'build_release.py')).read()
    assert f'v{br.APP_VERSION}_' not in src, (
        'the version is hard-coded into a string as well as APP_VERSION')
    assert br.APP_VERSION > 21, (
        'the series continues the repo history, whose last numbered archive '
        'was structural_simulator_v21_moment_arrows.zip')


def test_stamped_builds_the_name_the_reader_sees():
    name = br.stamped(br.ZIP_BASE, '.zip', 'v22_2026-09-30_0415')
    assert name == 'structural_simulator_app_v22_2026-09-30_0415.zip'


def test_the_archive_names_are_stamped_and_the_inner_rbz_name_is_not():
    """SketchUp does not care what the .rbz file is called, but the loader
    inside it and the folder beside it must keep their fixed names -- and the
    app archive ships the extension under that canonical name, which is what
    every earlier report refers to."""
    dest, _ = br.build_zip(check_only=True)
    base = os.path.basename(dest)
    assert base.startswith(br.ZIP_BASE + '_v')
    assert base.endswith('.zip')
    assert br.RBZ_NAME == br.RBZ_BASE + '.rbz'
    assert '_v' not in br.RBZ_NAME
    shipped = {rel for rel, _ in br.app_files()}
    assert br.RBZ_NAME in shipped


def test_prune_older_keeps_the_one_it_is_told_to(tmp_path, monkeypatch):
    monkeypatch.setattr(br, 'APP', str(tmp_path))
    keep = tmp_path / 'thing_v22_2026-09-30_0415.zip'
    for name in ('thing_v20_2026-09-01_0900.zip',
                 'thing_v21_2026-09-15_1200.zip',
                 'thing_v22_2026-09-30_0415.zip'):
        (tmp_path / name).write_bytes(b'x')
    (tmp_path / 'unrelated.zip').write_bytes(b'x')
    br.prune_older('thing', '.zip', str(keep))
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ['thing_v22_2026-09-30_0415.zip', 'unrelated.zip']


def test_building_to_an_explicit_dest_leaves_the_app_folder_alone(tmp_path):
    """A test that builds into tmp_path must not touch APP.

    This is not hypothetical. When the stamped naming went in, build_zip
    pruned `APP/structural_simulator_app_v*.zip` and build_rbz copied its
    result over `APP/CoordinateCoordinatorTrussAppAMAC.rbz` regardless of
    where they had been asked to write. The suite's own tmp_path builds then
    deleted the archives that had just been delivered. Destructive steps are
    gated on `dest is None` now, and this holds them there.
    """
    before = sorted(n for n in os.listdir(APP)
                    if n.endswith(('.zip', '.rbz')))
    stamps = {n: os.stat(os.path.join(APP, n)).st_mtime_ns for n in before}

    br.build_zip(dest=str(tmp_path / 'somewhere_else.zip'))
    br.build_rbz(dest=str(tmp_path / 'somewhere_else.rbz'))

    after = sorted(n for n in os.listdir(APP)
                   if n.endswith(('.zip', '.rbz')))
    assert after == before, (
        f'building into tmp_path changed APP: gone={set(before) - set(after)}, '
        f'new={set(after) - set(before)}')
    for n in after:
        assert os.stat(os.path.join(APP, n)).st_mtime_ns == stamps[n], (
            f'{n} was rewritten by a build aimed somewhere else')


def test_the_customer_archive_ships_the_app_and_nothing_internal(tmp_path):
    """No tests, build tools, internal reports, plugin sources or editor
    settings -- only what a customer runs."""
    import zipfile
    dest = str(tmp_path / 'customer.zip')
    br.build_zip(dest=dest, customer=True)
    with zipfile.ZipFile(dest) as z:
        rels = {n.split('/', 1)[1] for n in z.namelist() if '/' in n}
    for must in ('main.py', 'common.py', 'apps/stereo/stereo_app.py',
                 'apps/truss/truss_app.py', br.RBZ_NAME, 'requirements.txt',
                 'USER_GUIDE.html', 'tools/doctor.py'):
        assert must in rels, must
    for r in rels:
        top = r.split('/', 1)[0]
        assert top not in br.CUSTOMER_SKIP_DIRS or r in br.CUSTOMER_KEEP, r
    assert 'tools/build_release.py' not in rels


def test_the_customer_archive_carries_generated_third_party_notices(tmp_path):
    """Generated from this environment at build time, so the archive can
    never ship notices for library versions it does not run on."""
    import importlib.metadata as md
    dest = str(tmp_path / 'customer.zip')
    br.build_zip(dest=dest, customer=True)
    with zipfile.ZipFile(dest) as z:
        names = {n.split('/', 1)[1]: n for n in z.namelist() if '/' in n}
        assert br.NOTICES_NAME in names
        text = z.read(names[br.NOTICES_NAME]).decode('utf-8')
    for dist in ('numpy', 'scipy'):
        assert '%s %s' % (dist, md.version(dist)) in text, dist
    assert 'about.py' in names and 'notices.py' in names


def test_the_customer_build_stops_when_a_licence_text_is_missing(
        tmp_path, monkeypatch):
    sys.path.insert(0, APP)
    import notices
    sys.path.remove(APP)
    real = notices.components

    def without_numpy_text():
        comps = real()
        for c in comps:
            if c['name'] == 'numpy':
                c['texts'] = []
        return comps
    monkeypatch.setattr(notices, 'components', without_numpy_text)
    with pytest.raises(SystemExit, match='numpy'):
        br.build_zip(dest=str(tmp_path / 'c.zip'), customer=True)
