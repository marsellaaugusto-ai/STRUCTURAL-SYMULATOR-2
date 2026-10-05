"""The third-party notices and the About box that shows them.

Shipping the app with numpy, scipy, Tk and the rest is allowed on one
condition: each one's copyright notice and licence text goes with it.
notices.py gathers them from the environment, so these tests check that
what it gathers is complete and matches what is installed.
"""
import importlib.metadata as md
import os
import sys

import pytest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP not in sys.path:
    sys.path.insert(0, APP)

import notices   # noqa: E402


@pytest.fixture(scope='module')
def comps():
    return notices.components()


def test_every_component_has_a_licence_text(comps):
    assert notices.missing(comps) == []


def test_python_tk_and_every_installed_root_are_listed(comps):
    assert {'Python', 'Tcl/Tk (tkinter)'} <= {c['name'] for c in comps}
    names = {notices._norm(c['name']) for c in comps}
    for root in notices.RUNTIME_ROOTS:
        try:
            md.distribution(root)
        except md.PackageNotFoundError:
            continue
        assert notices._norm(root) in names, root


def test_dependencies_of_the_roots_are_followed(comps):
    """openpyxl needs et_xmlfile, which the app never imports itself."""
    names = {notices._norm(c['name']) for c in comps}
    try:
        md.distribution('openpyxl')
    except md.PackageNotFoundError:
        pytest.skip('openpyxl not installed')
    assert 'et-xmlfile' in names


def test_versions_are_the_installed_ones(comps):
    for c in comps:
        if c['name'] in ('Python', 'Tcl/Tk (tkinter)'):
            continue
        assert c['version'] == md.version(c['name']), c['name']


def test_bundled_native_libraries_are_covered(comps):
    """numpy's and scipy's wheels carry OpenBLAS and the GCC runtime;
    their licences come with the package's own licence files."""
    text = notices.render(comps)
    if 'numpy' in {c['name'] for c in comps}:
        assert 'OpenBLAS' in text


def test_the_freetype_credit_is_there_when_pillow_is(comps):
    text = notices.render(comps)
    has_pillow = any(notices._norm(c['name']) == 'pillow' for c in comps)
    assert (notices.FREETYPE_CREDIT in text) == has_pillow


def test_a_component_without_text_is_reported_and_marked():
    comps = [{'name': 'x', 'version': '1', 'licence': 'MIT', 'url': '',
              'texts': []}]
    assert notices.missing(comps) == ['x']
    assert 'LICENCE TEXT NOT FOUND' in notices.render(comps)


def test_extra_only_requirements_are_not_followed():
    assert notices._requirement_name('pytest; extra == "test"') is None
    assert notices._requirement_name('numpy<2.8,>=2.0.0') == 'numpy'
    assert notices._requirement_name(
        'six >=1.5; python_version >= "3"') == 'six'


# ── the About box ─────────────────────────────────────────────────────────

@pytest.fixture
def root():
    tk = pytest.importorskip('tkinter')
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip('no display')
    r.withdraw()
    yield r
    r.destroy()


def test_about_without_a_licence_file_says_so(root, tmp_path, monkeypatch):
    import about
    monkeypatch.setattr(about, 'APP_DIR', str(tmp_path))
    win = about.show_about(root)
    assert str(win.licence_button['state']) == 'disabled'
    win.destroy()


def test_about_reads_the_owner_from_the_licence(root, tmp_path, monkeypatch):
    import about
    (tmp_path / 'LICENSE.txt').write_text(
        '\n© 2026 Example Owner. All rights reserved.\n\nTerms...\n',
        encoding='utf-8')
    monkeypatch.setattr(about, 'APP_DIR', str(tmp_path))
    assert about.owner_line() == '© 2026 Example Owner. All rights reserved.'
    win = about.show_about(root)
    assert str(win.licence_button['state']) == 'normal'
    win.destroy()


def test_open_source_licences_prefer_the_shipped_file(root, tmp_path,
                                                     monkeypatch):
    import about
    monkeypatch.setattr(about, 'APP_DIR', str(tmp_path))
    live = about.notices_text()
    assert live.startswith('THIRD-PARTY SOFTWARE NOTICES')
    (tmp_path / 'THIRD_PARTY_NOTICES.txt').write_text('shipped',
                                                      encoding='utf-8')
    assert about.notices_text() == 'shipped'
    win = about.show_about(root)
    win.notices_button.invoke()
    shown = [w for w in win.winfo_children()
             if hasattr(w, 'text_widget')]
    assert shown and shown[0].text_widget.get('1.0', 'end').strip() == \
        'shipped'
    win.destroy()


def test_the_main_window_has_an_about_button():
    src = open(os.path.join(APP, 'main.py'), encoding='utf-8').read()
    assert 'about.show_about(root)' in src


def test_the_user_guide_ships_and_opens(root):
    import about
    assert about.guide_path() is not None
    opened = []
    assert about.open_guide(opener=opened.append) == about.guide_path()
    assert opened and opened[0].startswith('file:')
    win = about.show_about(root)
    assert str(win.guide_button['state']) == 'normal'
    win.destroy()


def test_the_user_guide_names_only_real_controls():
    """Every control the guide tells the reader to press exists in the
    app's source, so the guide cannot drift from the buttons."""
    import re
    guide = open(os.path.join(APP, 'USER_GUIDE.html'), encoding='utf-8').read()
    src = ''
    for dirpath, _d, files in os.walk(os.path.join(APP, 'apps')):
        for f in files:
            if f.endswith('.py'):
                src += open(os.path.join(dirpath, f), encoding='utf-8').read()
    src += open(os.path.join(APP, 'about.py'), encoding='utf-8').read()
    src += open(os.path.join(APP, 'main.py'), encoding='utf-8').read()
    named = set(re.findall(r'<strong>([^<]{3,40})</strong>', guide))
    named |= set(re.findall(r'<em>([A-Z][^<]{2,40}…)</em>', guide))
    parts = {p.strip() for n in named for p in n.split('→')}
    controls = {n for n in parts if n.endswith('…') or n.startswith('▶')
                or n in ('Live', 'Self-weight', 'Keep variant', 'Load %',
                         'Export PDF', 'Colour by utilisation', 'Units',
                         'Node', 'Rod', 'Support', 'Load')}
    flat = re.sub(r'\s+', ' ', src)            # '▶  Analyze' == '▶ Analyze'
    missing = [c for c in sorted(controls) if c not in flat]
    assert not missing, missing
