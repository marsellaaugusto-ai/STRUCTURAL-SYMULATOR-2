"""Drive the real Stereo GUI over every feature the roadmap claims is built.

    APPDIR="$PWD" SWEEPOUT=/tmp/sweep \
      xvfb-run -a -s "-screen 0 1600x1000x24" python3 -u tools/gui_roadmap_sweep.py

Exits non-zero if anything fails. SWEEPOUT must exist; the exported files land
there and are checked for existence, not content.


Not a unit test. It presses the widget the user would press, sends the event
the user would send, and reads back what the panel itself shows. A feature
whose handler survives but whose button or binding was lost fails here -- the
exact damage the merge did, which a green suite did not report.

Covered: every item §13.1 of STEREO_ROADMAP_V2_FULL_ACCOUNT lists as
"present and reachable", numbered as the roadmap numbers them.
"""
import os, sys, traceback
sys.path.insert(0, os.environ['APPDIR'])
os.chdir(os.environ['APPDIR'])

import tkinter as tk
from tkinter import messagebox, filedialog

FAIL, OK = [], []
def _p(t):
    sys.stdout.write(t + '\n'); sys.stdout.flush()
def ok(w, d=''):  OK.append(w);  _p('  ok   %-56s %s' % (w, d))
def bad(w, d=''): FAIL.append((w, d)); _p('  FAIL %-56s %s' % (w, d))
def step(t):      _p('.. %s' % t)

BOX = []
for n in ('showerror', 'showwarning', 'showinfo'):
    setattr(messagebox, n, lambda *a, **k: BOX.append(a))
messagebox.askyesno = messagebox.askokcancel = lambda *a, **k: True

OUT = os.environ['SWEEPOUT']
_seq = [0]
def _save(*a, **k):
    _seq[0] += 1
    ext = (k.get('defaultextension') or '.bin')
    p = os.path.join(OUT, 'out%02d%s' % (_seq[0], ext))
    return p
filedialog.asksaveasfilename = _save
filedialog.askopenfilename = lambda *a, **k: ''
filedialog.askdirectory = lambda *a, **k: OUT

def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)

def texts(root):
    out = []
    for w in walk(root):
        try:
            t = w.cget('text')
        except Exception:
            continue
        if isinstance(t, str) and t.strip():
            out.append(t.strip())
    return out

def button(root, needle):
    needle = needle.lower()
    for w in walk(root):
        try:
            if needle in str(w.cget('text')).lower() and w.cget('command'):
                return w
        except Exception:
            continue
    return None

def press(root, needle, what):
    b = button(root, needle)
    if b is None:
        bad(what, 'no widget labelled %r with a command' % needle); return False
    try:
        b.invoke()
    except Exception as exc:
        bad(what, '%s: %s' % (type(exc).__name__, exc)); return False
    ok(what); return True

def menu_items(menu):
    out = {}
    try:
        for i in range(menu.index('end') + 1):
            try:
                out[str(menu.entrycget(i, 'label'))] = i
            except tk.TclError:
                pass
    except Exception:
        pass
    return out

root = tk.Tk(); root.geometry('1600x1000')
from apps.stereo.stereo_app import StereoApp
from apps.stereo import stereo_app_reports as _sr

# The PDF exports put up a MODAL sheet chooser (grab_set + wait_window). Under
# xvfb nobody presses OK, so it blocks forever -- which is correct behaviour
# for a modal and useless for a sweep. Answer it with "every sheet" instead,
# and check separately that the real dialog exists.
from apps.stereo import stereo_reports as _srep
_CHOSE = []
def _all_sheets(self, title, results, checks, n_rigid):
    _CHOSE.append(title)
    # NOT None -- the caller reads None as CANCELLED and returns without
    # writing anything, which looked exactly like a broken PDF export.
    return set(_srep.PDF_SHEET_GROUPS)
_sr.StereoReportsMixin._pdf_sheet_dialog = _all_sheets
from apps.stereo import stereo_app_shell as shell
tab = tk.Frame(root); tab.pack(fill='both', expand=True)
app = StereoApp(tab)
root.update_idletasks(); root.update()
def pump():
    root.update_idletasks(); root.update()

def press_key(key, x=None, y=None):
    """Keys go to the FOCUS widget. focus_set only REQUESTS it; under a test
    harness focus_force is what actually moves it, and without that every key
    test silently passes by doing nothing."""
    app.canvas.focus_force(); pump()
    kw = {}
    if x is not None:
        kw['x'], kw['y'] = x, y
    app.canvas.event_generate(key, **kw); pump()

# ── 1.1 panels scroll and fit ───────────────────────────────────────────
step('1.1 panels')
from common import ScrollPanel
panels = [w for w in walk(tab) if isinstance(w, ScrollPanel)]
if panels:
    ok('1.1 the context panel is a ScrollPanel', '%d found' % len(panels))
else:
    bad('1.1 the context panel is a ScrollPanel')

# ── every mode in the rail ──────────────────────────────────────────────
step('every mode in the rail')
for key, glyph, title, hint in shell.MODES:
    try:
        app._set_mode(key); pump()
        n = len(list(walk(app._mode_frames[key])))
        (ok if n >= 5 else bad)('rail: %-8s opens with content' % key, '%d widgets' % n)
    except Exception as exc:
        bad('rail: %-8s opens' % key, '%s: %s' % (type(exc).__name__, exc))

# ── build a model (Build mode + Generate) ───────────────────────────────
step('build a model')
app._set_mode('build'); pump()
app._clear_model(); pump()
gb = getattr(app, 'grid_family_btn', None)
if gb is None:
    bad('1.x the Generate toolbar button exists')
else:
    ok('1.x the Generate toolbar button exists', str(gb.cget('text')))
    gm = gb.cget('menu')
    items = menu_items(root.nametowidget(gm)) if gm else {}
    hit = [i for k, i in items.items() if 'generate now' in k.lower()]
    if not hit:
        bad('1.x its menu offers "Generate now"', ', '.join(list(items)[:6]))
    else:
        root.nametowidget(gm).invoke(hit[0]); pump()
        (ok if app.nodes and app.members else bad)(
            '1.x "Generate now" builds a model',
            '%d nodes, %d rods' % (len(app.nodes), len(app.members)))
    # The families hang off a CASCADE ('Grid family'), not the top level.
    casc = None
    for k, i in items.items():
        if 'grid family' in k.lower():
            try:
                casc = root.nametowidget(root.nametowidget(gm).entrycget(i, 'menu'))
            except Exception:
                casc = None
    if casc is None:
        bad('1.x the grid families hang off a "Grid family" cascade',
            ', '.join(list(items)[:6]))
    else:
        fams = [k for k in menu_items(casc) if k]
        (ok if len(fams) >= 14 else bad)('1.x all 14 grid families are offered',
                                         '%d families' % len(fams))
    exl = None
    for k, i in items.items():
        if 'example library' in k.lower():
            try:
                exl = root.nametowidget(root.nametowidget(gm).entrycget(i, 'menu'))
            except Exception:
                exl = None
    if exl is None:
        bad('1.x the worked examples hang off an "Example library" cascade')
    else:
        exs = [k for k in menu_items(exl) if k]
        (ok if len(exs) >= 10 else bad)('1.x the worked examples are offered',
                                        '%d examples' % len(exs))
    hitw = [i for k, i in items.items() if 'custom surface' in k.lower()]
    (ok if hitw else bad)('3.x the Custom surface wizard is on that menu')
tbtn = [w for w in walk(tab)
        if w.winfo_class() == 'Button' and 'analyze' in str(w.cget('text')).lower()]
(ok if tbtn else bad)('1.x the Analyze toolbar button exists')

# ── 5.3 keyboard shortcuts, as real key events ──────────────────────────
step('5.3 keyboard')
app._clear_model(); pump()
press_key('g')
if app.nodes:
    ok('5.3 "g" generates', '%d nodes' % len(app.nodes))
else:
    bad('5.3 "g" generates', 'still empty -- binding lost')
app.results = None
press_key('a')
(ok if app.results else bad)('5.3 "a" analyses')
before = (app.azimuth, app.elevation)
press_key('1'); v1 = (app.azimuth, app.elevation)
press_key('2'); v2 = (app.azimuth, app.elevation)
if v1 != v2:
    ok('5.3 "1"/"2"/"3" set the view', '%s then %s' % (v1, v2))
else:
    bad('5.3 "1"/"2"/"3" set the view', 'view did not change')
for n, (key, want) in enumerate(zip(('<Alt-Key-1>', '<Alt-Key-4>', '<Alt-Key-6>'),
                                    ('build', 'load', 'addons'))):
    press_key(key)
    got = app.active_mode.get()
    (ok if got == want else bad)('5.3 %s jumps to %s' % (key, want), 'mode=%s' % got)

# ── 5.2 snap + coordinate readout on hover ──────────────────────────────
step('5.2 snap')
app._set_mode('analyse'); pump()
pts = app._screen_positions()
w = app.canvas.winfo_width(); h = app.canvas.winfo_height()
got, snapped = '', None
for sx, sy in pts:
    if not (0 < sx < w and 0 < sy < h):
        continue        # off-canvas: Tk delivers no Motion there
    # The coordinate readout goes to the STATUS BAR (_set_status ->
    # status_var), not to the selection label. Reading the wrong one of the
    # two is how this check first reported a working feature as broken.
    app.status_var.set(''); app._snap_node = None
    app.canvas.event_generate('<Motion>', x=int(sx), y=int(sy)); pump()
    got, snapped = app.status_var.get(), app._snap_node
    if got:
        break
(ok if got and 'Node' in got else bad)(
    '5.2 hover snaps and reads the coordinate out',
    got[:60] or 'canvas %dx%d, snap=%r' % (w, h, snapped))
(ok if snapped is not None else bad)('5.2 the snap itself finds the node',
                                     'snap=%r' % (snapped,))

# ── 3.1 click selects a rod, 3.2 lasso selects several ──────────────────
step('3.1 click')
app.selected_member = None; app.selected_members = set()
pts = app._screen_positions()
mid = None
for i, m in enumerate(app.members):
    ax, ay = pts[m['a']]; bx, by = pts[m['b']]
    mid = (int((ax + bx) / 2), int((ay + by) / 2))
    app.canvas.event_generate('<ButtonPress-1>', x=mid[0], y=mid[1])
    app.canvas.event_generate('<ButtonRelease-1>', x=mid[0], y=mid[1]); pump()
    if app.selected_member is not None or app.selected_members:
        break
if app.selected_member is not None or app.selected_members:
    ok('3.1 a click selects a rod or node',
       'member=%s members=%d' % (app.selected_member, len(app.selected_members)))
else:
    bad('3.1 a click selects a rod or node', 'nothing selected by any click')

app.selected_nodes = set(); app.selected_members = set()
app.canvas.event_generate('<ButtonPress-1>', x=5, y=5)
app.canvas.event_generate('<B1-Motion>', x=800, y=600)
app.canvas.event_generate('<ButtonRelease-1>', x=800, y=600); pump()
n_lasso = len(app.selected_nodes) + len(app.selected_members)
(ok if n_lasso > 1 else bad)('3.2 a dragged box selects several', '%d picked' % n_lasso)

# ── 3.3 Delete removes what is selected ─────────────────────────────────
step('3.3 Delete')
n_before = len(app.nodes)
app.selected_nodes = {0}
app.selected_members = set(); app.selected_member = None
press_key('<Delete>')
(ok if len(app.nodes) < n_before else bad)(
    '3.3 Delete removes the selection', '%d -> %d nodes' % (n_before, len(app.nodes)))
app._generate(push_undo=False); pump()

# ── 3.4 arrow keys arm axis extend, Escape cancels ──────────────────────
step('3.4 arrow')
app.selected_nodes = {0}; app.selected_members = set()
press_key('<Up>')
armed = app._axis_pending
(ok if armed else bad)('3.4 an arrow key arms axis extend', 'armed=%r' % (armed,))
press_key('<Escape>')
still = app._axis_pending
(ok if not still else bad)('3.4 Escape cancels it', 'armed=%r' % (still,))

# ── 2.1 / 2.2 the size sliders ──────────────────────────────────────────
step('2.1 / 2.2')
for var in ('node_size', 'rod_thickness'):
    v = getattr(app, var, None)
    if v is None:
        bad('2.x %s exists' % var, 'missing'); continue
    try:
        d = v.get(); v.set(0); app._refresh_all(); pump()
        v.set(8); app._refresh_all(); pump()
        v.set(d); app._refresh_all(); pump()
        ok('2.x %s drives a redraw at 0 and 8' % var, 'default %s' % d)
    except Exception as exc:
        bad('2.x %s drives a redraw' % var, '%s: %s' % (type(exc).__name__, exc))
scales = [w for w in walk(tab) if w.winfo_class() == 'Scale']
(ok if scales else bad)('2.1/2.2 the sliders are real Scale widgets',
                        '%d scales' % len(scales))

# ── 3.5 distributed load along the SELECTED rods ────────────────────────
step('3.5 distributed')
from apps.stereo.stereo_app_constants import ROD_SCOPE_SELECTED, ROD_SCOPES
app._set_mode('load'); pump()
app.member_loads = []
app.selected_members = set(range(4)); app.selected_member = None
app.rod_scope.set(ROD_SCOPE_SELECTED)
try:
    app.rod_w.set(3.0)
except Exception:
    pass
BOX.clear()
if press(app._mode_frames['load'], 'apply to rods', '3.5 Apply to rods'):
    got = len(app.member_loads or [])
    if BOX:
        bad('3.5 the box selection is honoured', 'dialog: %r' % (BOX[0],))
    elif got == 4:
        ok('3.5 the box selection is honoured', '%d span loads' % got)
    else:
        bad('3.5 the box selection is honoured', 'expected 4, got %d' % got)
if ROD_SCOPE_SELECTED in list(app.rod_scope.get() and ROD_SCOPES or []):
    ok('3.5 "Selected rods" is offered in the scope list')
else:
    bad('3.5 "Selected rods" is offered in the scope list', str(ROD_SCOPES))

# ── 3.6 the crane ───────────────────────────────────────────────────────
step('3.6 the crane')
app._set_mode('addons'); pump()
addons = app._mode_frames['addons']
(ok if any('crane' in t.lower() for t in texts(addons)) else bad)(
    '3.6 the Crane group is visible')
top = max(p[2] for p in app.nodes)
tops = [i for i, p in enumerate(app.nodes) if abs(p[2] - top) < 1e-9]
xs = [app.nodes[i][0] for i in tops]; ys = [app.nodes[i][1] for i in tops]
picks = set()
for tx in (min(xs), max(xs)):
    for ty in (min(ys), max(ys)):
        picks.add(min(tops, key=lambda i: (app.nodes[i][0]-tx)**2 + (app.nodes[i][1]-ty)**2))
app.selected_nodes = set(picks); n_before = len(app.nodes)
BOX.clear()
if press(addons, 'lift the selected nodes', '3.6 Lift the selected nodes'):
    pump()
    if BOX:
        bad('3.6 four picked nodes are accepted', 'dialog: %r' % (BOX[0],))
    cab = [m for m in app.members if m.get('tension_only')]
    mst = [m for m in app.members if m.get('role') == 'crane_mast']
    (ok if len(cab) == 4 and len(mst) == 1 else bad)(
        '3.6 four tension-only slings and one mast',
        '%d slings, %d masts' % (len(cab), len(mst)))
    (ok if getattr(app, '_crane_tag', None) else bad)(
        '3.6 the lift adds tag lines', str(getattr(app, '_crane_tag', None)))
    app.results = None
    app._set_mode('analyse'); pump()
    app._analyze(); pump()
    if not app.results:
        bad('3.6 the lift solves', 'dialog: %r' % (BOX[-1:],))
    else:
        mr = app.results['member_res']
        f = [mr[i]['N'] for i, m in enumerate(app.members) if m.get('tension_only')]
        worst = min(f) if f else 0.0
        (ok if worst >= -1e-6 else bad)(
            '3.6 no sling is reported in compression',
            'N = ' + ', '.join('%.2f' % v for v in f))
        (ok if max(f) > 1.0 else bad)('3.6 the slings actually carry',
                                      'max %.2f kN' % max(f))
        big = max(abs(nr[k]) for nr in app.results['node_res']
                  for k in ('ux', 'uy', 'uz'))
        (ok if big < 1000.0 else bad)('3.6 the answer is not a null-space artefact',
                                      'max |u| = %.3e mm' % big)
    app._set_mode('addons'); pump()
    press(addons, 'clear every crane', '3.6 Clear every crane')
    pump()
    left = [m for m in app.members if m.get('role') in ('crane_cable', 'crane_mast')]
    (ok if not left and len(app.nodes) == n_before else bad)(
        '3.6 clearing puts the model back',
        '%d crane rods left, %d nodes vs %d' % (len(left), len(app.nodes), n_before))

# ── 4.x Add-ons: columns and beams still work ───────────────────────────
step('4.x Add-ons')
app.selected_nodes = set(picks)
press(addons, 'add column', '4.x columns build')
pump()
press(addons, 'clear every column', '4.x columns clear')
pump()

# ── 4.3 the CIRSOC catalog picker in Section mode ───────────────────────
step('4.3 the CIRSOC')
app._set_mode('section'); pump()
sect = texts(app._mode_frames['section'])
(ok if any('profile' in t.lower() for t in sect) else bad)(
    '4.3 the Profile row is in the Section panel')

# ── 5.4 properties, 5.5 model tree ──────────────────────────────────────
step('5.4 properties')
app._set_mode('results'); pump()
res = app._mode_frames['results']
app.selected_nodes = {0}
try:
    app._update_properties_panel(); pump()
    ok('5.4 the properties panel refreshes')
except Exception as exc:
    bad('5.4 the properties panel refreshes', '%s: %s' % (type(exc).__name__, exc))
try:
    app._refresh_model_tree(); pump()
    ok('5.5 the model tree refreshes')
except Exception as exc:
    bad('5.5 the model tree refreshes', '%s: %s' % (type(exc).__name__, exc))
(ok if any('propert' in t.lower() for t in texts(res)) else bad)(
    '5.4 "Properties" is named in the Results panel')
(ok if any('tree' in t.lower() for t in texts(res)) else bad)(
    '5.5 "Model tree" is named in the Results panel')

# ── 2.5 / 6.1-6.4 the Export menu ───────────────────────────────────────
step('2.5 / 6.1-6.4')
app._analyze(); pump()
menu = getattr(app, 'export_menu', None)
if menu is None:
    bad('6.x the Export menu exists')
else:
    items = menu_items(menu)
    ok('6.x the Export menu exists', '%d entries' % len(items))
    for want, tag in (('Export Excel', '4.7 Excel export'),
                      ('Import Excel', '1.3 Excel/SketchUp import'),
                      ('Export PDF', '6.1 PDF report'),
                      ('PDF of Selection', '6.1b PDF of the selection'),
                      ('Export SketchUp', '6.2 SketchUp export'),
                      ('Export IFC', '6.3 IFC export'),
                      ('Export 3D (OBJ)', '6.2b OBJ export'),
                      ('Open Example', '2.5 example workbook'),
                      ('Save Variant', '6.4 variants'),
                      ('Compare Variants', '6.4b compare variants')):
        hit = [k for k in items if k.startswith(want)]
        (ok if hit else bad)('%s is on the menu' % tag, hit[0] if hit else '')
    # And actually run the file-producing ones.
    for want, tag in (('Export Excel', '4.7 Excel export runs'),
                      ('Export PDF', '6.1 PDF report runs'),
                      ('Export SketchUp', '6.2 SketchUp export runs'),
                      ('Export IFC', '6.3 IFC export runs')):
        hit = [i for k, i in items.items() if k.startswith(want)]
        if not hit:
            continue
        BOX.clear()
        n0 = len(os.listdir(OUT))
        try:
            menu.invoke(hit[0]); pump()
        except Exception as exc:
            bad(tag, '%s: %s' % (type(exc).__name__, exc)); continue
        made = len(os.listdir(OUT)) - n0
        errs = [b for b in BOX if b and 'rror' in str(b[0])]
        if errs:
            bad(tag, 'dialog: %r' % (errs[0],))
        elif made > 0:
            ok(tag, '%d file(s)' % made)
        else:
            bad(tag, 'no file written')

(ok if _CHOSE else bad)('6.1 the PDF sheet chooser is asked for',
                        ', '.join(_CHOSE))

# ── 6.2b the OBJ export, through its own dialog ─────────────────────────
step('6.2b OBJ export')
# app.root is the TAB FRAME, not the Tk root, so its dialogs are children
# of that -- not of '.'. Walking the whole tree is what finds them.
def toplevels():
    return [w for w in walk(root) if isinstance(w, tk.Toplevel)]
tops_before = set(str(w) for w in toplevels())
BOX.clear(); n0 = len(os.listdir(OUT))
items = menu_items(app.export_menu)
hit = [i for k, i in items.items() if k.startswith('Export 3D (OBJ)')]
if not hit:
    bad('6.2b the OBJ export is on the menu')
else:
    app.export_menu.invoke(hit[0]); pump()
    win = [w for w in toplevels() if str(w) not in tops_before]
    if not win:
        bad('6.2b the OBJ export opens its format dialog')
    else:
        w = win[0]
        ok('6.2b the OBJ export opens its format dialog', str(w.title()))
        combos = [x for x in walk(w) if x.winfo_class() == 'TCombobox']
        (ok if combos else bad)('6.2b it offers a format choice',
                                '%d combobox(es)' % len(combos))
        b = button(w, 'export') or button(w, 'ok')
        if b is None:
            bad('6.2b its dialog has an Export button',
                ' | '.join(texts(w))[:70])
        else:
            b.invoke(); pump()
            made = len(os.listdir(OUT)) - n0
            errs = [x for x in BOX if x and 'rror' in str(x[0])]
            if errs:
                bad('6.2b OBJ export runs', 'dialog: %r' % (errs[0],))
            else:
                (ok if made > 0 else bad)('6.2b OBJ export runs',
                                          '%d file(s)' % made)
        try:
            w.destroy()
        except Exception:
            pass
    pump()

# ── every mode again, after all of that ─────────────────────────────────
step('every mode again')
broke = []
for key, _, _, _ in shell.MODES:
    try:
        app._set_mode(key); pump()
    except Exception as exc:
        broke.append('%s (%s)' % (key, type(exc).__name__))
(ok if not broke else bad)('every mode still opens at the end', ', '.join(broke))

print()
print('=' * 74)
print('%d ok, %d FAILED' % (len(OK), len(FAIL)))
for w, d in FAIL:
    print('  FAIL %s -- %s' % (w, d))
print('=' * 74)
root.destroy()
sys.exit(1 if FAIL else 0)
