"""Why this interpreter can or cannot run the app.

Run it with the SAME interpreter that fails:

    python tools/doctor.py

It imports nothing the app needs, so it runs even where the app does not,
and it prints one block that can be pasted straight into a bug report.
"""
import os
import platform
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (module, why it matters, is it required)
DEPENDENCIES = (
    ('tkinter', 'every window in the app', True),
    ('numpy', 'every solver; imported unguarded at common.py scope', True),
    ('scipy', 'the cable-web solver and the Stereo sparse assembly', True),
    ('openpyxl', 'Excel import and export', True),
    ('matplotlib', 'the PDF report and the guide equation images', False),
    ('PIL', 'free-body-diagram images inside the Excel export', False),
)

# One file per package that must sit beside main.py, because the packages
# import each other by path rather than being installed.
LAYOUT = ('main.py', 'common.py', 'units.py', 'cirsoc_301.py',
          'requirements.txt', os.path.join('apps', 'stereo', 'stereo_app.py'),
          os.path.join('apps', 'truss', 'truss_app.py'))


def _version(mod):
    for attr in ('__version__', 'VERSION', 'version'):
        v = getattr(mod, attr, None)
        if isinstance(v, str):
            return v
    if mod.__name__ == 'tkinter':
        try:
            return str(mod.TkVersion)
        except Exception:
            return ''
    return ''


def main():
    out = []
    add = out.append
    add('=' * 70)
    add('STRUCTURAL SYMULATOR SOLVER — environment doctor')
    add('=' * 70)
    add(f'interpreter   {sys.executable}')
    add(f'version       {sys.version.split()[0]}  ({platform.python_implementation()})')
    add(f'platform      {platform.platform()}')
    add(f'app folder    {APP}')
    add(f'working dir   {os.getcwd()}')
    add(f'in a venv     {"yes" if sys.prefix != sys.base_prefix else "no"}')
    add('')

    add('dependencies')
    missing_required = []
    for name, why, required in DEPENDENCIES:
        try:
            mod = __import__(name)
            add(f'  ok        {name:<12} {_version(mod):<10} {why}')
        except Exception as exc:
            mark = 'MISSING  ' if required else 'optional '
            add(f'  {mark} {name:<12} {"":<10} {why}')
            add(f'            -> {type(exc).__name__}: {exc}')
            if required:
                missing_required.append(name)
    add('')

    add('folder layout')
    missing_files = [rel for rel in LAYOUT
                     if not os.path.isfile(os.path.join(APP, rel))]
    for rel in LAYOUT:
        ok = os.path.isfile(os.path.join(APP, rel))
        add(f'  {"ok      " if ok else "MISSING "} {rel}')
    add('')

    add('=' * 70)
    if not missing_required and not missing_files:
        add('VERDICT: this interpreter can run the app.')
        add(f'  cd "{APP}"')
        add(f'  "{sys.executable}" main.py')
    else:
        add('VERDICT: this interpreter CANNOT run the app.')
        if missing_required:
            add('  install the missing packages INTO THIS INTERPRETER:')
            add(f'    "{sys.executable}" -m pip install -r '
                f'"{os.path.join(APP, "requirements.txt")}"')
            if 'tkinter' in missing_required:
                add('  tkinter is not a pip package. It comes with Python:')
                add('    Debian/Ubuntu:  sudo apt install python3-tk')
                add('    Fedora:         sudo dnf install python3-tkinter')
                add('    macOS/Windows:  reinstall from python.org (some')
                add('                    Homebrew, pyenv and Microsoft Store')
                add('                    builds omit it)')
        if missing_files:
            add('  the app folder is incomplete — these are missing:')
            for rel in missing_files:
                add(f'    {rel}')
            add('  unpack the whole zip, keeping the folder together.')
        add('')
        add('  In VS Code, pick the interpreter that reports ok above:')
        add('    Ctrl+Shift+P  ->  "Python: Select Interpreter"')
    add('=' * 70)

    text = '\n'.join(out)
    print(text)
    return 0 if (not missing_required and not missing_files) else 1


if __name__ == '__main__':
    sys.exit(main())
