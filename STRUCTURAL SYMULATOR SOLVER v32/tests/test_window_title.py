"""The window title: name, version, date, and the drawing in front."""
import os
import sys
import time
import zipfile
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import appinfo   # noqa: E402


def test_the_title_reads_name_version_date_and_document():
    info = (31, time.strptime('2026-10-03', '%Y-%m-%d'))
    assert appinfo.window_title('roof.xlsx', tab='Stereo', info=info) == \
        'Structural Simulator v31 · 03/10/2026 — roof.xlsx'
    # nothing open: the app's drawing
    assert appinfo.window_title(None, tab='Truss', info=info) == \
        'Structural Simulator v31 · 03/10/2026 — Truss drawing'


def test_a_working_copy_reads_its_version_from_the_release_script():
    sys.path.insert(0, str(APP / 'tools'))
    import build_release as br
    if (APP / appinfo.STAMP_FILE).exists():
        pytest.skip('this copy carries a build stamp')
    ver, when, _round = appinfo.build_info()
    assert ver == br.APP_VERSION
    assert time.mktime(when) <= time.time()


def test_the_build_stamp_is_what_the_title_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(appinfo, 'APP_DIR', str(tmp_path))
    (tmp_path / appinfo.STAMP_FILE).write_text(
        appinfo.stamp_text(31, time.strptime('2026-10-03', '%Y-%m-%d')))
    ver, when, _round = appinfo.build_info()
    assert ver == 31 and time.strftime('%Y-%m-%d', when) == '2026-10-03'


def test_every_archive_carries_the_stamp_and_appinfo(tmp_path):
    sys.path.insert(0, str(APP / 'tools'))
    import build_release as br
    for customer in (False, True):
        dest = str(tmp_path / ('c.zip' if customer else 'a.zip'))
        br.build_zip(dest=dest, customer=customer)
        with zipfile.ZipFile(dest) as z:
            names = {n.split('/', 1)[1] for n in z.namelist()}
            assert 'appinfo.py' in names and br.STAMP_NAME in names
            root = z.namelist()[0].split('/', 1)[0]
            ver = z.read(f'{root}/{br.STAMP_NAME}').decode().split()[0]
        assert int(ver) == br.APP_VERSION


def test_the_window_follows_the_tab_and_its_document(monkeypatch):
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f'no display: {exc}')
    try:
        import main
        app = main.App(root)
        root.update()
        app.nb.select(6)                      # Stereo
        app.refresh_title()
        assert root.title().endswith(' — Stereo drawing')
        stereo = app.tab_apps[6][1]
        stereo._model_label = 'roof_iterations.xlsx'
        app.refresh_title()
        assert root.title().endswith(' — roof_iterations.xlsx')
        assert root.title().startswith('Structural Simulator v')
        app.nb.select(0)                      # Truss: nothing open
        app.refresh_title()
        assert root.title().endswith(' — Truss drawing')
        app.tab_apps[0][1].document_name = 'bridge.xlsx'
        app.refresh_title()
        assert root.title().endswith(' — bridge.xlsx')
        app.tab_apps[0][1]._clear_all(push_undo=False)
        app.refresh_title()
        assert root.title().endswith(' — Truss drawing')
    finally:
        root.destroy()


TABS = ('truss/truss_app', 'beam/beam_app', 'arch/arch_app', 'cable/cable_app',
        'cable_web/cable_web_app', 'perforated_beam/perforated_beam_app',
        'shell/shell_app')


@pytest.mark.parametrize('mod', TABS)
def test_every_tab_names_the_file_it_opens_and_forgets_it_on_clear(mod):
    src = (APP / 'apps' / (mod + '.py')).read_text(encoding='utf-8')
    assert 'self.document_name = os.path.basename(path)' in src
    assert 'self.document_name = None' in src


def test_a_truss_imported_from_excel_is_named(monkeypatch, tmp_path):
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f'no display: {exc}')
    try:
        from apps.truss import truss_app as ta
        frame = tk.Frame(root)
        frame.pack()
        app = ta.TrussApp(frame)
        app._load_example()
        path = str(tmp_path / 'my_bridge.xlsx')
        monkeypatch.setattr(ta.filedialog, 'asksaveasfilename',
                            lambda *a, **k: path)
        monkeypatch.setattr(ta.filedialog, 'askopenfilename',
                            lambda *a, **k: path)
        for name in ('showinfo', 'showwarning', 'showerror', 'askyesno',
                     'askokcancel'):
            monkeypatch.setattr(ta.messagebox, name, lambda *a, **k: True)
        app._run_analysis()
        app._export_excel()
        assert os.path.isfile(path)
        app._clear_all(push_undo=False)
        assert app.document_name is None
        app._import_excel()
        assert app.document_name == 'my_bridge.xlsx'
    finally:
        root.destroy()
