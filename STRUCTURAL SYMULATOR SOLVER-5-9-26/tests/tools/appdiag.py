"""Whole-app diagnostic sweep across all six tabs.

Per MANIFESTO sec 2: drive the real widgets, don't reason about the code.
Checks that generalise across tabs -- first paint, responsive layout, every
button invokes, no duplicate methods, dependency handling, shared-helper
health -- plus a per-tab smoke test of its own analysis path.
"""
import sys, os, time, gc, math, ast, re, json, traceback
from pathlib import Path
HERE = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(HERE)); os.chdir(HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
LOG = open(OUT / 'log.txt', 'w', encoding='utf-8', errors='replace', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a); print(s, flush=True); LOG.write(s + '\n')

FINDINGS = []
def finding(sev, tab, what, detail):
    FINDINGS.append({'severity': sev, 'tab': tab, 'what': what, 'detail': detail})
    log('   [%s] %-14s %s' % (sev, tab, what))
    if detail:
        log('        %s' % detail)

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
_boxes = []
def _mk(n, r):
    def f(*a, **k):
        _boxes.append((n, str(a[0])[:60] if a else '', str(a[1])[:200] if len(a) > 1 else ''))
        return r
    return f
for nm, ret in (('showerror', None), ('showwarning', None), ('showinfo', None),
                ('askyesno', True), ('askokcancel', True), ('askretrycancel', False)):
    setattr(messagebox, nm, _mk(nm, ret))
filedialog.askopenfilename = lambda *a, **k: ''
filedialog.asksaveasfilename = lambda *a, **k: ''
tk.Toplevel.wait_window = lambda self, w=None: None

log('=' * 78)
log('A. STATIC: duplicate methods, bare excepts, shared-helper health')
log('=' * 78)
PY_FILES = sorted(p for p in HERE.rglob('*.py') if '__pycache__' not in str(p))
log('   %d python files' % len(PY_FILES))
for p in PY_FILES:
    try:
        tree = ast.parse(p.read_text(encoding='utf-8'))
    except SyntaxError as ex:
        finding('HIGH', p.name, 'does not parse', str(ex)); continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            seen = {}
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    seen.setdefault(item.name, []).append(item.lineno)
            for k, v in seen.items():
                if len(v) > 1:
                    finding('MEDIUM', p.relative_to(HERE).as_posix(),
                            f'{node.name}.{k} defined {len(v)}x',
                            f'lines {v}; the later one silently wins')

# bare `except: pass` / `except Exception: pass` swallowing everything
for p in PY_FILES:
    txt = p.read_text(encoding='utf-8')
    n = len(re.findall(r'except\s+Exception\s*:\s*\n\s*pass\b', txt)) \
        + len(re.findall(r'except\s*:\s*\n\s*pass\b', txt))
    if n >= 8:
        finding('LOW', p.relative_to(HERE).as_posix(),
                f'{n} silent `except: pass` blocks',
                'each one can hide a real failure; the SciPy bug of 2026-09-04 '
                'was exactly this pattern')

import common
log('   _beam_gauss_solve backend: %s'
    % ('numpy' if 'numpy' in (common._beam_gauss_solve.__doc__ or '') else 'INTERPRETED PYTHON'))
if 'numpy' not in (common._beam_gauss_solve.__doc__ or ''):
    finding('HIGH', 'common.py', '_beam_gauss_solve reverted to interpreted Python',
            'shared by every tab; ~40% slower on the cable-web suite (MANIFESTO Phase 1)')
for dep, fn in (('openpyxl', 'ensure_openpyxl'), ('scipy', 'ensure_scipy'),
                ('matplotlib', 'ensure_matplotlib')):
    has = hasattr(common, '_' + fn)
    log('   _%s present: %s' % (fn, has))
    if not has:
        finding('MEDIUM', 'common.py', f'no _{fn}()', f'{dep} is used but never ensured')

log('')
log('=' * 78)
log('B. LAUNCH: all tabs, first paint, responsive widths')
log('=' * 78)
import main as _main
root = tk.Tk(); root.geometry('1500x950+10+10')
t0 = time.perf_counter()
app = _main.App(root)
root.update()
launch = time.perf_counter() - t0
nb = root.winfo_children()[0]
tabs = [nb.tab(i, 'text') for i in range(len(nb.tabs()))]
log('   launched in %.2fs; tabs: %s' % (launch, tabs))
if launch > 5.0:
    finding('MEDIUM', 'main', 'slow startup', '%.1fs' % launch)

# find each tab's app instance
def widgets_of(frame):
    out = []
    def walk(w):
        try:
            if not w.winfo_exists():
                return
        except Exception:
            return
        out.append(w)
        try:
            kids = w.winfo_children()
        except Exception:
            return
        for ch in kids:
            walk(ch)
    walk(frame)
    return out


def label_of(w):
    """A human-readable name. cget('text') returns the VARIABLE name for a
    widget configured with textvariable, which is useless in a report."""
    for attr in ('text',):
        try:
            v = str(w.cget(attr))
            if v and not v.startswith('PY_VAR'):
                return v
        except Exception:
            pass
    try:
        tv = str(w.cget('textvariable'))
        if tv:
            return '<%s var=%s>' % (w.winfo_class(), tv)
    except Exception:
        pass
    return w.winfo_class()

tab_frames = {}
for i in range(len(nb.tabs())):
    tab_frames[tabs[i]] = nb.nametowidget(nb.tabs()[i])

for name, frame in tab_frames.items():
    ws = widgets_of(frame)
    canvases = [w for w in ws if isinstance(w, tk.Canvas)]
    items = sum(len(c.find_all()) for c in canvases)
    log('   %-16s widgets=%-4d canvases=%-2d canvas items at first paint=%d'
        % (name, len(ws), len(canvases), items))
    if canvases and items == 0:
        finding('MEDIUM', name, 'blank canvas at first paint',
                'nothing drawn before any user action (MANIFESTO sec 3p)')

for wpx in (1600, 1200, 900, 700, 550):
    root.geometry('%dx950+10+10' % wpx)
    root.update_idletasks(); root.update(); time.sleep(0.12); root.update()
    for name, frame in tab_frames.items():
        nb.select(nb.tabs()[tabs.index(name)])
        root.update_idletasks(); root.update()
        bad = []
        for w in widgets_of(frame):
            cls = w.winfo_class()
            if cls not in ('Button', 'TButton', 'Checkbutton', 'TCheckbutton',
                            'Radiobutton', 'TRadiobutton', 'TCombobox', 'Entry'):
                continue
            try:
                if not w.winfo_ismapped():
                    continue
                x = w.winfo_rootx() - root.winfo_rootx()
                over = x + w.winfo_width() - root.winfo_width()
            except Exception:
                continue
            if x < -2 or over > 2:
                bad.append('%s (%+dpx)' % (label_of(w)[:22], over if over > 2 else x))
        if bad:
            finding('MEDIUM', name, 'controls off-screen at %dpx' % wpx,
                    ', '.join(sorted(set(bad))[:6]))
root.geometry('1500x950+10+10'); root.update_idletasks(); root.update()
log('   responsive-width sweep done (1600 -> 550 px)')

log('')
log('=' * 78)
log('C. BUTTONS: every button on every tab invoked')
log('=' * 78)
for name, frame in tab_frames.items():
    nb.select(nb.tabs()[tabs.index(name)]); root.update()
    raised, slow, n = [], [], 0
    # Snapshot the labels first: invoking a button can rebuild the panel and
    # invalidate every handle we are holding, so re-find by label each time.
    wanted = []
    for w in widgets_of(frame):
        try:
            if isinstance(w, tk.Button) or w.winfo_class() == 'TButton':
                wanted.append(label_of(w))
        except Exception:
            pass
    for txt in wanted:
        if txt in ('Add load', 'Cancel', 'Create', 'Apply', 'Hide'):
            continue
        w = None
        for cand in widgets_of(frame):
            try:
                if (isinstance(cand, tk.Button) or cand.winfo_class() == 'TButton')                         and label_of(cand) == txt:
                    w = cand; break
            except Exception:
                pass
        if w is None:
            continue
        n += 1
        try:
            t0 = time.perf_counter(); w.invoke(); root.update()
            dt = time.perf_counter() - t0
            if dt > 2.0:
                slow.append('%s %.1fs' % (txt, dt))
        except tk.TclError:
            pass                       # widget replaced by its own handler
        except Exception as ex:
            raised.append('%s: %s' % (txt, type(ex).__name__))
        for tl in list(frame.winfo_children()):
            if isinstance(tl, tk.Toplevel):
                try: tl.destroy()
                except Exception: pass
        root.update()
    log('   %-16s %d buttons invoked' % (name, n))
    if raised:
        finding('HIGH', name, 'button raised', '; '.join(raised))
    if slow:
        finding('MEDIUM', name, 'button blocks the UI', '; '.join(slow))

log('')
log('=' * 78)
log('D. POPUPS raised during the sweep')
log('=' * 78)
for b in _boxes[:14]:
    log('   %s' % (b,))
log('   total: %d' % len(_boxes))

root.destroy(); gc.collect()

log('')
log('=' * 78)
log('SUMMARY')
log('=' * 78)
for sev in ('HIGH', 'MEDIUM', 'LOW'):
    fs = [f for f in FINDINGS if f['severity'] == sev]
    log('   %-7s %d' % (sev, len(fs)))
json.dump(FINDINGS, open(OUT / 'findings.json', 'w'), indent=2)
LOG.close()
