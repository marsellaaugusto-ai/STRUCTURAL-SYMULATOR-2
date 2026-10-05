"""The app never installs anything behind the user's back.

It used to run "pip install" from inside the window the first time
openpyxl, SciPy or matplotlib was missing: it reached the network and
changed the customer's Python without asking. The helpers now only say
whether a library is importable, and the feature that needs it says what
to install.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import common   # noqa: E402


@pytest.mark.parametrize('helper, modules', [
    ('_ensure_openpyxl', ['openpyxl']),
    ('_ensure_scipy', ['scipy', 'scipy.optimize']),
    ('_ensure_matplotlib', ['matplotlib', 'PIL']),
])
def test_a_missing_library_is_reported_not_installed(helper, modules,
                                                      monkeypatch):
    calls = []

    def no_process(*a, **k):
        calls.append(a)
        raise AssertionError('the app tried to start a process: %r' % (a,))
    for name in ('check_call', 'call', 'run', 'Popen', 'check_output'):
        monkeypatch.setattr(subprocess, name, no_process)
    for m in modules:
        monkeypatch.setitem(sys.modules, m, None)      # import now fails
    assert getattr(common, helper)() is False
    assert calls == []


def test_a_present_library_is_reported_present():
    pytest.importorskip('openpyxl')
    assert common._ensure_openpyxl() is True


def test_no_shipped_module_runs_pip():
    """No module the app ships builds a pip command line."""
    pat = re.compile(r"""['"]-m['"]\s*,\s*['"]pip['"]|pip\.main\(""")
    offenders = []
    for path in APP.rglob('*.py'):
        rel = path.relative_to(APP).as_posix()
        if rel.split('/')[0] in ('tests', 'tools') or '__pycache__' in rel:
            continue
        if pat.search(path.read_text(encoding='utf-8', errors='replace')):
            offenders.append(rel)
    assert offenders == []


def test_main_limits_the_maths_library_before_numpy_loads():
    """The thread limit only works if it is set before numpy is imported:
    it must come before main.py's first import of common or the apps."""
    src = (APP / 'main.py').read_text(encoding='utf-8')
    limit = src.index("os.environ.setdefault(_var, '1')")
    for later in ('import common', 'from common', 'import units',
                  'from apps.'):
        pos = src.find(later)
        assert pos == -1 or pos > limit, later
    assert "'OPENBLAS_NUM_THREADS'" in src[:limit]
