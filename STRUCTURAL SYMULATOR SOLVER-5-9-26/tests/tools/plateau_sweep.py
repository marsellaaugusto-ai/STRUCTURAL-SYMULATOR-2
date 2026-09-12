"""Find where the drawn cable is genuinely flatter than the true catenary.

For each span/length, compare the flat run of the DRAWN funicular against
the flat run of the mathematically exact catenary at the same on-screen
scale. A ratio near 1 means the rendering is faithful (a real catenary IS
flat at its vertex); a large ratio is an actual plateau artifact.
"""
import sys, os, time, math
from pathlib import Path
HERE = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(HERE)); os.chdir(HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
import tkinter as tk
from tkinter import messagebox
for n, r in (('showerror', None), ('showwarning', None), ('showinfo', None), ('askyesno', True)):
    setattr(messagebox, n, (lambda rr: (lambda *a, **k: rr))(r))
import apps.cable_web.cable_web_app as cwa
cwa.messagebox = messagebox
from apps.cable_web.cable_web_app import CableWebApp, PX_PER_M

root = tk.Tk(); root.geometry('1400x900+10+10')
app = CableWebApp(root); app.pack(fill='both', expand=True)
app.reference_mode.set('straight'); root.update()
calls = []
_orig = CableWebApp._smooth_polyline
CableWebApp._smooth_polyline = staticmethod(
    lambda p, samples_per_segment=12: (calls.append(list(p)) or _orig(p, samples_per_segment)))
_draw = []
_oc = tk.Canvas.create_line
def cl(self, *a, **k):
    if len(a) > 6:
        _draw.append(list(a))
    return _oc(self, *a, **k)
tk.Canvas.create_line = cl


def M(x, y):
    return x * PX_PER_M, -y * PX_PER_M


def reset():
    app.nodes = []; app.cables = []; app.loads = []
    app.result = None; app.results_current = False; app._solver_meta = None
    app.next_node_id = app.next_cable_id = app.next_load_id = 1
    app._history = []; app._future = []


def cat_a(span, arc):
    lo, hi = 1e-6, 1e6
    for _ in range(300):
        a = 0.5 * (lo + hi)
        if 2.0 * a * math.sinh(span / (2.0 * a)) > arc:
            lo = a
        else:
            hi = a
    return 0.5 * (lo + hi)


def flat_pc(pts):
    if len(pts) < 2:
        return 0.0
    ymax = max(p[1] for p in pts)
    near = sorted(p[0] for p in pts if ymax - p[1] <= 0.75)
    w = max(p[0] for p in pts) - min(p[0] for p in pts)
    return 100.0 * (near[-1] - near[0]) / max(w, 1e-9) if len(near) > 1 else 0.0


print('%-8s %-8s %5s %9s %9s %7s  %s' %
      ('span', 'cable', 'nseg', 'drawn%', 'true%', 'ratio', 'verdict'))
print('-' * 74)
worst = []
for span in (8.0, 10.0, 12.0, 16.0, 20.0, 25.0, 30.0):
    for f in (1.05, 1.15, 1.3, 1.5):
        arc = round(span * f, 1)
        reset()
        a_ = app._new_node(*M(0, 0), support=True)
        b_ = app._new_node(*M(span, 0), support=True)
        c = app._new_cable(a_['id'], b_['id'])
        c['length_override'] = arc
        c['w'] = 10.0
        root.update()
        nseg = len(app._solver_breakpoints(c['id'])) - 1
        calls.clear(); _draw.clear()
        t0 = time.perf_counter(); app._solve_exact()
        while app._solving and time.perf_counter() - t0 < 120:
            root.update(); time.sleep(0.02)
        if app.result is None:
            print('%-8.1f %-8.1f %5d  ANALYZE FAILED' % (span, arc, nseg)); continue
        app._fit_view(); app._draw(); root.update()
        if not calls:
            continue
        raw = max(calls, key=len)
        curve = _orig(raw, 10)
        d = flat_pc(curve)
        scale = (curve[-1][0] - curve[0][0]) / span
        a = cat_a(span, arc); top = math.cosh(span / (2 * a))
        N = 3000
        ys = [-(a * (math.cosh((span * i / N - span / 2.0) / a) - top)) * scale
              for i in range(N + 1)]
        ymax = max(ys)
        near = [span * i / N for i, y in enumerate(ys) if ymax - y <= 0.75]
        t = 100.0 * (max(near) - min(near)) / span if len(near) > 1 else 0.0
        ratio = d / t if t > 1e-9 else (99.0 if d > 0 else 1.0)
        verdict = 'OK' if ratio <= 1.35 else ('PLATEAU x%.1f' % ratio)
        if ratio > 1.35:
            worst.append((ratio, span, arc, nseg, d, t))
        print('%-8.1f %-8.1f %5d %8.1f%% %8.1f%% %7.2f  %s'
              % (span, arc, nseg, d, t, ratio, verdict))

print()
if worst:
    worst.sort(reverse=True)
    print('WORST OFFENDERS:')
    for r, sp, ar, ns, d, t in worst[:8]:
        print('  %.1f m span / %.1f m cable (nseg=%d): drawn %.1f%% vs true %.1f%%  = %.1fx'
              % (sp, ar, ns, d, t, r))
else:
    print('No case where the drawn curve is more than 1.35x flatter than the true catenary.')
root.destroy()
