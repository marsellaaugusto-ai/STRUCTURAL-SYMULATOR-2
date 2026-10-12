"""Who the Truss report is by: the author and the course, remembered.

Asked for once, the first time a report is exported from the window, and
printed on the cover and in the footer of every sheet from then on. A
student hands in many reports for the same course; typing their name
into every one is the kind of chore that makes a field get left blank.
Changed at any time from Export ▾ → Report author and course….

Kept in one small JSON file in the user's home, beside the Stereo tab's
PDF presets (apps/stereo/stereo_pdf_presets), so both tabs keep their
report settings in the same place. Kept free of Tk.
"""
import json
import os

ENV = 'TRUSS_REPORT_PREFS'
KEYS = ('author', 'course')


def store_path():
    """$TRUSS_REPORT_PREFS, else ~/.structural_simulator/truss_report.json."""
    p = os.environ.get(ENV)
    if p:
        return p
    return os.path.join(os.path.expanduser('~'), '.structural_simulator',
                        'truss_report.json')


def load(path=None):
    """{'author': str, 'course': str} -- empty strings when nothing has
    been saved yet or the file cannot be read: a damaged settings file
    must never stop a report from being written."""
    out = {k: '' for k in KEYS}
    try:
        with open(path or store_path(), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return out
    if isinstance(data, dict):
        for k in KEYS:
            v = data.get(k)
            if isinstance(v, str):
                out[k] = v.strip()
    return out


def save(author, course, path=None):
    """Remember them. Returns True when written."""
    path = path or store_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'author': (author or '').strip(),
                       'course': (course or '').strip()}, f, indent=2)
        return True
    except OSError:
        return False


def is_set(path=None):
    """True once the file exists -- even with both fields left empty, so
    someone who chose to leave them blank is not asked again and again."""
    return os.path.exists(path or store_path())
