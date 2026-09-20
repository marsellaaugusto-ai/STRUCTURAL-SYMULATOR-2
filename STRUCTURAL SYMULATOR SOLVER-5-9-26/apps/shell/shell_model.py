"""shell_model.py -- the Shell tab's model, 2026-09-14.

A ShellModel is everything the user defined, as plain data (so it can be
saved, exported to Excel and read back), plus the steps that turn it into a
finite-element model and an answer:

    model = ShellModel.preset('Hypar saddle on four edge beams')
    res = model.analyze()          # every load case + every combination
    des = shell_design.design(model, res)

No Tkinter. The UI (shell_app.py) edits the data and calls these methods;
the tests drive exactly the same methods.

STORAGE UNITS (what the fields hold -- the UI converts for display):
    plan, heights, surface, thickness formulas ... m
    edge-beam / column section b, h ............ cm
    area loads .................................. kN/m^2
    point loads ................................. kN
    f'c, fy ..................................... MPa
    unit weight ................................. kN/m^3
Every computation below converts to SI (N, m, Pa) at the point of use.
"""
import copy
import math

import numpy as np

import formula
from apps.shell import shell_fe as fe
from apps.shell import shell_codes as codes
from apps.shell import shell_wind as wind

KN = 1e3
MPA = 1e6


# ═══════════════════════════════════════════════════════════════════════════
#  Vocabulary
# ═══════════════════════════════════════════════════════════════════════════
LOAD_TYPES = {
    'plan_vertical':    'Vertical, per m² of PLAN (snow, roof live), + downward',
    'surface_vertical': 'Vertical, per m² of SURFACE (finishes), + downward',
    'normal':           'Normal pressure (wind), + pushes onto the surface',
    'surface_x':        'Horizontal x, per m² of surface, + toward +x',
    'surface_y':        'Horizontal y, per m² of surface, + toward +y',
    'projected_x':      'Horizontal x, per m² projected on a vertical plane ⟂ x',
    'projected_y':      'Horizontal y, per m² projected on a vertical plane ⟂ y',
    'point':            'Point load at (x, y): Px, Py, P↓ in kN',
}

SUPPORT_TYPES = {
    'pinned':   '111000',   # holds x, y, z
    'fixed':    '111111',
    'vertical': '001000',
    'z+x':      '101000',
    'z+y':      '011000',
}
SUPPORT_LABELS = {
    'pinned': 'Pinned (holds x, y, z)',
    'fixed': 'Fixed (holds everything)',
    'vertical': 'Vertical only (z)',
    'z+x': 'z and x',
    'z+y': 'z and y',
}
SUPPORT_AT = {
    'corners': 'All four corners',
    'low_corners': 'The two lowest corners',
    'high_corners': 'The two highest corners',
    'edge': 'Every node of one edge (x0, x1, y0, y1)',
    'edges': 'Every node of all four edges',
    'point': 'Nearest node to a point (x, y)',
}
# Point-like supports get a solid support block (abutment) of this plan size
# unless the support says otherwise: a shell corner on a single node is a
# singularity -- the shear next to it grows without limit as the mesh is
# refined -- and no real shell sits on a point.
POINT_SUPPORTS = ('corners', 'low_corners', 'high_corners', 'point')
DEFAULT_BLOCK = 1.0
BEAM_OFFSETS = ('below', 'centre', 'above')
EDGE_NAMES = ('x0', 'x1', 'y0', 'y1')

# Section of the rigid arms that tie a column head's shell nodes to the
# column top: a 1 m x 1 m block at ten times the concrete modulus -- stiff
# enough to act rigid against a shell a few centimetres thick, not so stiff
# that it spoils the conditioning of the system.
RIGID_SECTION = fe.rect_section(1.0, 1.0)


class ModelError(ValueError):
    """Something in the model definition prevents analysis; the message says
    what and where, in terms the user entered."""


# ═══════════════════════════════════════════════════════════════════════════
#  Presets
# ═══════════════════════════════════════════════════════════════════════════
def _base(**over):
    m = {
        'lines': [], 'sliders': {},
        'surface': 'z', 'thickness': 't',
        'plan': {'x0': '-a/2', 'x1': 'a/2', 'y0': '-b/2', 'y1': 'b/2'},
        'mesh': {'nx': 24, 'ny': 24, 'size': 0.5},
        'material': {'fc': 30.0, 'fy': 420.0, 'Ec': 0.0, 'nu': 0.2, 'gamma': 25.0},
        'supports': [{'at': 'corners', 'which': 'all', 'type': 'pinned'}],
        'beams': [{'line': 'edges', 'b': 25.0, 'h': 50.0, 'offset': 'below'}],
        'columns': [],
        'cases': [{'name': 'D', 'kind': 'D'}, {'name': 'Lr', 'kind': 'Lr'}],
        'self_weight': True, 'self_weight_case': 'D',
        'loads': [
            {'case': 'D', 'type': 'surface_vertical', 'value': '1.0',
             'note': 'waterproofing + finishes'},
            {'case': 'Lr', 'type': 'plan_vertical', 'value': '0.96',
             'note': 'roof live load (maintenance)'},
        ],
        'wind': {'V': 45.0, 'z': 8.0, 'exposure': 'C', 'category': 'II',
                 'Kzt': 1.0, 'Kd': wind.KD_BUILDING, 'G': wind.G_RIGID,
                 'basis': '2005'},
        'design': {'code': codes.DEFAULT_CODE, 'layout': 'auto', 'cover_cm': 3.5,
                   'exposed': True, 'controlled': True, 'exposure_factor': 1.0,
                   'bar_mm': 8.0, 'f1': 0.5, 'f2': 0.2, 'buckling_factor': 0.20,
                   'creep': 0.0, 'deflection_limit': 250.0, 'longterm': 3.0,
                   't_min': 0.05, 't_max': 0.40, 't_step': 0.01, 'taper': 0.10,
                   'max_iter': 6, 'auto_thicken': False},
        'zones': [],
        'auto_layer': None,
    }
    for k, v in over.items():
        m[k] = v
    return m


PRESETS = {
    'Hypar saddle on four edge beams': lambda: _base(
        lines=['# Hyperbolic paraboloid (saddle) over a rectangle',
               'a = 12', 'b = 12', 'f = 3',
               'z(x, y) = 2 f x y / (a b)',
               't = 0.10'],
        sliders={'a': [4.0, 30.0, 0.5], 'b': [4.0, 30.0, 0.5], 'f': [0.5, 8.0, 0.1]},
    ),
    'Hypar, one raised corner (classic)': lambda: _base(
        lines=['# Hypar with one corner raised by c: z = c x y / (a b)',
               'a = 10', 'b = 10', 'c = 2.5',
               'z(x, y) = c x y / (a b)',
               't = 0.10'],
        plan={'x0': '0', 'x1': 'a', 'y0': '0', 'y1': 'b'},
        sliders={'a': [4.0, 30.0, 0.5], 'b': [4.0, 30.0, 0.5], 'c': [0.5, 8.0, 0.1]},
    ),
    'Inverted umbrella (4 hypars on one column)': lambda: _base(
        lines=['# Candela-type inverted umbrella: four hypar quadrants,',
               '# outer edges level at height h, low point on the column',
               'a = 12', 'b = a', 'h = 2', 'A = a/2',
               'z(x, y) = h (abs(x)/A + abs(y)/A - abs(x) abs(y)/A^2)',
               't = 0.10'],
        sliders={'a': [4.0, 30.0, 0.5], 'h': [0.5, 6.0, 0.1]},
        supports=[],
        beams=[{'line': 'edges', 'b': 15.0, 'h': 30.0, 'offset': 'below'},
               {'line': 'x=0', 'b': 20.0, 'h': 40.0, 'offset': 'below'},
               {'line': 'y=0', 'b': 20.0, 'h': 40.0, 'offset': 'below'}],
        columns=[{'x': '0', 'y': '0', 'height': 4.0, 'b': 50.0, 'h': 50.0,
                  'base': 'fixed', 'capital': 1.2}],
    ),
    'Barrel vault (cylinder)': lambda: _base(
        lines=['# Circular-arc barrel vault spanning in y, length a in x',
               'a = 20', 'b = 10', 'R = 8',
               'z(x, y) = sqrt(R^2 - y^2) - sqrt(R^2 - (b/2)^2)',
               't = 0.10'],
        supports=[{'at': 'edge', 'which': 'y0', 'type': 'pinned'},
                  {'at': 'edge', 'which': 'y1', 'type': 'pinned'}],
        beams=[{'line': 'x0', 'b': 20.0, 'h': 60.0, 'offset': 'below'},
               {'line': 'x1', 'b': 20.0, 'h': 60.0, 'offset': 'below'}],
    ),
    'Elliptic paraboloid dome': lambda: _base(
        lines=['# Shallow elliptic paraboloid (dome) on edge beams',
               'a = 16', 'b = 16', 'f = 2.5',
               'z(x, y) = f (1 - (2x/a)^2) + f (1 - (2y/b)^2) - f',
               't = 0.10'],
    ),
}
DEFAULT_PRESET = 'Hypar saddle on four edge beams'


# ═══════════════════════════════════════════════════════════════════════════
#  The model
# ═══════════════════════════════════════════════════════════════════════════
class ShellModel:
    def __init__(self, data=None):
        self.data = copy.deepcopy(data) if data is not None else PRESETS[DEFAULT_PRESET]()
        self.ws = formula.Workspace(self.data['lines'], self.data.get('sliders'))

    @classmethod
    def preset(cls, name):
        return cls(PRESETS[name]())

    # -- data ---------------------------------------------------------------
    def sync(self):
        """Copy the workspace text back into `data` (after UI edits)."""
        self.data['lines'] = self.ws.lines
        self.data['sliders'] = {k: list(v) for k, v in self.ws.sliders.items()}
        return self.data

    def to_dict(self):
        return copy.deepcopy(self.sync())

    @classmethod
    def from_dict(cls, d):
        base = _base()
        for k, v in d.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k].update(v)
            else:
                base[k] = v
        return cls(base)

    @property
    def code(self):
        return codes.get_code(self.data['design']['code'])

    # -- geometry -----------------------------------------------------------
    def plan_limits(self):
        p = self.data['plan']
        try:
            x0, x1 = self.ws.scalar(p['x0']), self.ws.scalar(p['x1'])
            y0, y1 = self.ws.scalar(p['y0']), self.ws.scalar(p['y1'])
        except formula.FormulaError as exc:
            raise ModelError(f'Plan limits: {exc}') from None
        if not (x1 > x0 and y1 > y0):
            raise ModelError(f'The plan must have x1 > x0 and y1 > y0 '
                             f'(got x {x0:g}..{x1:g}, y {y0:g}..{y1:g}).')
        return x0, x1, y0, y1

    def surface_fn(self):
        name = self.data['surface']
        if self.ws.has_function(name):
            return self.ws.function(name)
        if self.ws.has_number(name):
            v = self.ws.number(name)
            return lambda x, y: np.full(np.broadcast(x, y).shape, v)
        d = self.ws.get(name)
        why = f': {d.error}' if d is not None and d.error else ''
        raise ModelError(f'Define the surface as {name}(x, y) = ... in the '
                         f'definitions list{why}.')

    def thickness_fn(self):
        name = self.data['thickness']
        if self.ws.has_function(name):
            return self.ws.function(name)
        if self.ws.has_number(name):
            v = self.ws.number(name)
            return lambda x, y: np.full(np.broadcast(x, y).shape, v)
        d = self.ws.get(name)
        why = f': {d.error}' if d is not None and d.error else ''
        raise ModelError(f'Define the thickness as {name} = ... (metres) in '
                         f'the definitions list{why}.')

    def mesh(self):
        """Node grid, elements, element thickness and plan data."""
        x0, x1, y0, y1 = self.plan_limits()
        mesh = self.data['mesh']
        size = float(mesh.get('size') or 0.0)
        if size > 0:
            # element size given: the counts follow the plan, so a slider that
            # stretches the plan keeps the elements the same size
            nx = max(2, int(math.ceil((x1 - x0) / size - 1e-9)))
            ny = max(2, int(math.ceil((y1 - y0) / size - 1e-9)))
        else:
            nx = int(mesh['nx'])
            ny = int(mesh['ny'])
        if nx < 2 or ny < 2:
            raise ModelError('The mesh needs at least 2 x 2 elements.')
        if nx * ny > 6400:
            raise ModelError('The mesh is limited to 6 400 elements (80 x 80).')
        xs = np.linspace(x0, x1, nx + 1)
        ys = np.linspace(y0, y1, ny + 1)
        XX, YY = np.meshgrid(xs, ys)                    # [j, i]
        try:
            ZZ = np.asarray(self.surface_fn()(XX, YY), float)
        except formula.FormulaError as exc:
            raise ModelError(f'Surface: {exc}') from None
        X = np.stack([XX.ravel(), YY.ravel(), ZZ.ravel()], axis=1)
        ids = np.arange(len(X)).reshape(ny + 1, nx + 1)
        elems = np.stack([ids[:-1, :-1], ids[:-1, 1:], ids[1:, 1:], ids[1:, :-1]],
                         -1).reshape(-1, 4)
        cen = X[elems].mean(axis=1)
        h_el = float(np.hypot(xs[1] - xs[0], ys[1] - ys[0]))
        t = self.element_thickness(cen[:, 0], cen[:, 1], h_el=h_el)
        return {'X': X, 'elems': elems, 'ids': ids, 'xs': xs, 'ys': ys,
                'nx': nx, 'ny': ny, 'plan': (x0, x1, y0, y1), 't': t,
                'centroids': cen, 'h_el': h_el}

    def element_thickness(self, xc, yc, with_auto=True, h_el=None):
        """Thickness at element centres: the t(x, y) definition, raised by any
        thickening zone whose rule holds, and by the automatic layer.

        The automatic layer holds only the RAISED points ([x, y, t] at the
        centres of the elements it thickened, plus the element size it was
        made on). A point applies to an element only if it lies within that
        element -- within 0.6 of an element diagonal, of the current or the
        original mesh, whichever is larger -- so a remeshed model picks the
        raise up where it was and nowhere else."""
        try:
            t = np.asarray(self.thickness_fn()(xc, yc), float).copy()
        except formula.FormulaError as exc:
            raise ModelError(f'Thickness: {exc}') from None
        if np.any(t <= 0):
            i = int(np.argmin(t))
            raise ModelError(f'The thickness is {t[i]:g} m at (x={xc[i]:.2f}, '
                             f'y={yc[i]:.2f}); it must be positive.')
        for zn in self.data.get('zones', []):
            rule = self._zone_rule(zn)
            hit = np.asarray(rule(xc, yc), bool)
            t = np.where(hit, np.maximum(t, float(zn['t'])), t)
        layer = self.data.get('auto_layer')
        if with_auto and layer:
            pts, h0 = (layer.get('points', []), layer.get('h', 0.0))                 if isinstance(layer, dict) else (layer, 0.0)
            L = np.asarray(pts, float)
            if L.ndim == 2 and len(L):
                tol = 0.6 * max(h_el or 0.0, float(h0) or 0.0)
                d2 = (xc[:, None] - L[None, :, 0]) ** 2 + (yc[:, None] - L[None, :, 1]) ** 2
                j = np.argmin(d2, axis=1)
                hit = np.sqrt(d2[np.arange(len(xc)), j]) <= tol + 1e-9
                t = np.where(hit, np.maximum(t, L[j, 2]), t)
        return t

    def _zone_rule(self, zn):
        try:
            return self.ws.compile(zn['rule'])
        except formula.FormulaError as exc:
            raise ModelError(f'Thickening zone "{zn["rule"]}": {exc}') from None

    # -- load formulas ------------------------------------------------------
    def wind_pressure(self):
        """qz (kN/m^2) from the wind panel."""
        w = self.data['wind']
        return wind.velocity_pressure(w['V'], w['z'], w['exposure'], w['category'],
                                      w.get('Kzt', 1.0), w.get('Kd', wind.KD_BUILDING)) / KN

    def load_names(self):
        """Extra names a load formula may use: the plan limits and the wind."""
        x0, x1, y0, y1 = self.plan_limits()
        return {'x0': x0, 'x1': x1, 'y0': y0, 'y1': y1,
                'qz': self.wind_pressure(), 'G': float(self.data['wind'].get('G', wind.G_RIGID))}

    def load_fn(self, expr):
        ws = self.ws
        names = dict(ws._ns_values)
        names.update(self.load_names())
        try:
            return formula.compile_function(expr, formula.COORDS, names,
                                            dict(ws._ns_funcs), ws._autocall)
        except formula.FormulaError as exc:
            raise ModelError(f'Load "{expr}": {exc}') from None

    # -- the finite-element model ------------------------------------------
    def build(self):
        """Mesh + elements + beams + columns + supports. Returns a dict the
        analysis uses; nothing here depends on the loads."""
        m = self.mesh()
        mat = self.data['material']
        fc = float(mat['fc'])
        if fc <= 0:
            raise ModelError("f'c must be positive.")
        Ec_mpa = float(mat.get('Ec') or 0.0) or self.code.Ec(fc)
        creep = float(self.data['design'].get('creep', 0.0) or 0.0)
        E = Ec_mpa * MPA
        nu = float(mat.get('nu', 0.2))
        X = m['X']
        shells = fe.ShellElements(X, m['elems'], m['t'], E, nu)
        m['E'] = E
        m['Ec_mpa'] = Ec_mpa
        m['E_eff_buckling'] = E / (1.0 + creep)
        m['nu'] = nu
        gam = float(mat.get('gamma', 25.0)) * KN

        Xall = [X]
        nn0 = len(X)
        frames = []
        beam_lines = []
        t_node = np.asarray(self.thickness_fn()(X[:, 0], X[:, 1]), float) * np.ones(len(X))
        for bi, bm in enumerate(self.data.get('beams', [])):
            b, h = float(bm['b']) / 100.0, float(bm['h']) / 100.0
            if b <= 0 or h <= 0:
                raise ModelError(f'Beam {bi + 1}: b and h must be positive.')
            sec = fe.rect_section(b, h)
            for line_name, nodes in self._line_nodes(bm['line'], m):
                off_mode = bm.get('offset', 'below')
                seg = []
                for a_, b_ in zip(nodes[:-1], nodes[1:]):
                    tm = 0.5 * (t_node[a_] + t_node[b_])
                    dz = {'below': -(h - tm) / 2, 'centre': 0.0, 'above': (h - tm) / 2}[off_mode]
                    fr = fe.Frame(X, a_, b_, E, nu, sec, offset=(0.0, 0.0, dz),
                                  w=(0.0, 0.0, -gam * b * h), tag=f'beam{bi}:{line_name}')
                    frames.append(fr)
                    seg.append(len(frames) - 1)
                beam_lines.append({'beam': bi, 'line': line_name, 'nodes': list(nodes),
                                   'frames': seg, 'b': b, 'h': h})
        fixed = set()
        support_nodes = []
        heads = []
        for si, spec in enumerate(self.data.get('supports', [])):
            # The sandbox: a support switched OFF stays in the model, in the
            # list and in the drawing, and is left out of the stiffness. It is
            # how you find out what a support was carrying without editing the
            # design to ask -- and without the answer being "the matrix is
            # singular", which is what deleting one usually gets you.
            if spec.get('off'):
                continue
            code = SUPPORT_TYPES.get(spec.get('type', 'pinned'), spec.get('type'))
            if not (isinstance(code, str) and len(code) == 6 and set(code) <= {'0', '1'}):
                raise ModelError(f'Support {si + 1}: unknown type {spec.get("type")!r}.')
            point_like = spec.get('at', 'corners') in POINT_SUPPORTS
            block = float(spec.get('block', DEFAULT_BLOCK) or 0.0) if point_like else 0.0
            for n in self._support_nodes(spec, m):
                support_nodes.append((n, code))
                for k, c in enumerate(code):
                    if c == '1':
                        fixed.add(fe.NDOF * n + k)
                if block > 0:
                    hd = self._rigid_block(n, block, X, nn0, m, E, nu, frames, f'block{si}')
                    hd.update({'kind': 'support', 'support': si})
                    heads.append(hd)
        columns = []
        for ci, col in enumerate(self.data.get('columns', [])):
            try:
                cx, cy = self.ws.scalar(str(col['x'])), self.ws.scalar(str(col['y']))
            except formula.FormulaError as exc:
                raise ModelError(f'Column {ci + 1}: {exc}') from None
            H = float(col['height'])
            if H <= 0:
                raise ModelError(f'Column {ci + 1}: the height must be positive.')
            top = int(np.argmin((X[:, 0] - cx) ** 2 + (X[:, 1] - cy) ** 2))
            base_xyz = X[top] - np.array([0.0, 0.0, H])
            Xall.append(base_xyz[None, :])
            base = nn0 + len(columns)
            b, h = float(col['b']) / 100.0, float(col['h']) / 100.0
            sec = fe.rect_section(b, h)
            Xtmp = np.vstack(Xall)
            fr = fe.Frame(Xtmp, base, top, E, nu, sec, w=(0.0, 0.0, -gam * b * h),
                          tag=f'column{ci}')
            frames.append(fr)
            col_frame = len(frames) - 1
            bcode = SUPPORT_TYPES['fixed' if col.get('base', 'fixed') == 'fixed' else 'pinned']
            for k, c in enumerate(bcode):
                if c == '1':
                    fixed.add(fe.NDOF * base + k)
            support_nodes.append((base, bcode))
            # The column HEAD. A column never meets a shell at a point: the
            # shell thickens into a solid head (capital) the size of the
            # column or larger. Modelled as a rigid block: every shell node
            # inside the head's plan square is tied to the column top by a
            # rigid arm, and the elements inside it are part of the head,
            # not of the shell. Without this, the shear next to the column
            # grows without limit as the mesh is refined (a point support is
            # a singularity), and automatic thickening chases it forever.
            cap = float(col.get('capital') or 0.0) or max(b, h)
            hd = self._rigid_block(top, cap, Xtmp, nn0, m, E, nu, frames, f'head{ci}')
            hd.update({'kind': 'column', 'col': ci})
            heads.append(hd)
            columns.append({'col': ci, 'top': top, 'base': base, 'frame': col_frame,
                            'b': b, 'h': h, 'H': H, 'cap': cap, 'head': hd})
        Xfull = np.vstack(Xall)
        if not fixed:
            raise ModelError('The shell has no supports. Add supports or a column.')
        in_head = np.zeros(len(m['elems']), bool)
        for hd in heads:
            in_head[hd['head_elems']] = True
        return {'mesh': m, 'shells': shells, 'frames': frames, 'X': Xfull,
                'nn': len(Xfull), 'fixed': sorted(fixed), 'support_nodes': support_nodes,
                'beam_lines': beam_lines, 'columns': columns, 'gamma': gam,
                'in_head': in_head, 'heads': heads,
                'E': E, 'Ec_mpa': Ec_mpa, 'E_eff_buckling': m['E_eff_buckling'], 'nu': nu}

    @staticmethod
    def _rigid_block(center, cap, X, nn0, m, E, nu, frames, tag):
        """Tie every shell node inside a cap x cap plan square around node
        'center' to it with rigid arms, and return the block's description.
        The elements whose four corners are all tied are part of the block,
        not of the shell. 'cap_eff' is the size the mesh actually resolves -- on a
        mesh coarser than the block it can be much smaller than asked for,
        and the design warns about it."""
        xt, yt = X[center, 0], X[center, 1]
        tol = 1e-6 * max(1.0, cap)
        inside = ((np.abs(X[:nn0, 0] - xt) <= cap / 2 + tol) &
                  (np.abs(X[:nn0, 1] - yt) <= cap / 2 + tol))
        nodes = [int(n) for n in np.nonzero(inside)[0]]
        for n in nodes:
            if n != center:
                frames.append(fe.Frame(X, center, n, E * 10.0, nu, RIGID_SECTION, tag=tag))
        # an element is part of the block only if ALL its corners are tied to
        # it; one with a corner outside still deforms, so it is still shell
        tied = np.zeros(nn0, bool)
        tied[nodes] = True
        elems = np.nonzero(tied[m['elems']].all(axis=1))[0]
        ext = max((max(abs(X[n, 0] - xt), abs(X[n, 1] - yt)) for n in nodes), default=0.0)
        return {'center': int(center), 'xy': (float(xt), float(yt)), 'cap': float(cap),
                'cap_eff': 2.0 * float(ext), 'head_nodes': nodes,
                'head_elems': elems.tolist()}

    def _line_nodes(self, spec, m):
        """Node chains for a beam line spec: an edge name, 'edges', or
        'x=<formula>' / 'y=<formula>' snapped to the nearest grid line."""
        ids = m['ids']
        spec = str(spec).strip()
        out = []
        if spec == 'edges':
            for e in EDGE_NAMES:
                out.extend(self._line_nodes(e, m))
            return out
        if spec == 'x0':
            return [('x0', list(ids[:, 0]))]
        if spec == 'x1':
            return [('x1', list(ids[:, -1]))]
        if spec == 'y0':
            return [('y0', list(ids[0, :]))]
        if spec == 'y1':
            return [('y1', list(ids[-1, :]))]
        if '=' in spec:
            axis, expr = spec.split('=', 1)
            axis = axis.strip()
            try:
                v = self.ws.scalar(expr)
            except formula.FormulaError as exc:
                raise ModelError(f'Beam line "{spec}": {exc}') from None
            if axis == 'x':
                i = int(np.argmin(np.abs(m['xs'] - v)))
                return [(f'x={m["xs"][i]:.3g}', list(ids[:, i]))]
            if axis == 'y':
                j = int(np.argmin(np.abs(m['ys'] - v)))
                return [(f'y={m["ys"][j]:.3g}', list(ids[j, :]))]
        raise ModelError(f'Unknown beam line "{spec}". Use x0, x1, y0, y1, '
                         'edges, x=<value> or y=<value>.')

    def _support_nodes(self, spec, m):
        ids, X = m['ids'], m['X']
        corners = [ids[0, 0], ids[0, -1], ids[-1, -1], ids[-1, 0]]
        at = spec.get('at', 'corners')
        which = spec.get('which', 'all')
        if at == 'corners':
            names = {'x0y0': ids[0, 0], 'x1y0': ids[0, -1], 'x1y1': ids[-1, -1],
                     'x0y1': ids[-1, 0]}
            if which in (None, '', 'all'):
                return corners
            return [names[w.strip()] for w in str(which).split(',')]
        if at == 'low_corners':
            return sorted(corners, key=lambda n: X[n, 2])[:2]
        if at == 'high_corners':
            return sorted(corners, key=lambda n: -X[n, 2])[:2]
        if at == 'edge':
            return self._line_nodes(which, m)[0][1]
        if at == 'edges':
            s = set()
            for e in EDGE_NAMES:
                s.update(self._line_nodes(e, m)[0][1])
            return sorted(s)
        if at == 'point':
            try:
                px, py = (self.ws.scalar(str(v)) for v in str(which).split(','))
            except (formula.FormulaError, ValueError) as exc:
                raise ModelError(f'Support point "{which}": give it as x, y ({exc})') from None
            return [int(np.argmin((X[:, 0] - px) ** 2 + (X[:, 1] - py) ** 2))]
        raise ModelError(f'Unknown support location {at!r}.')

    # -- loads ----------------------------------------------------------------
    def case_kinds(self):
        out = {}
        for c in self.data['cases']:
            if c['kind'] not in codes.KINDS:
                raise ModelError(f'Load case {c["name"]}: unknown kind {c["kind"]!r}.')
            out[c['name']] = c['kind']
        if self.data.get('self_weight') and self.data.get('self_weight_case') not in out:
            raise ModelError(f'The self-weight case "{self.data.get("self_weight_case")}" '
                             'is not in the list of load cases.')
        return out

    def load_vectors(self, fem):
        """(ndof, ncases) nodal loads in N / N*m, and the case names."""
        cases = list(self.case_kinds())
        shells, frames = fem['shells'], fem['frames']
        ndof = fe.NDOF * fem['nn']
        F = np.zeros((ndof, len(cases)))
        # each shell element's own consistent load, per case: needed to know
        # what an element delivers to its nodes (the shear into a column head)
        Fe_cases = np.zeros((len(cases), shells.ne, 24))
        col = {c: i for i, c in enumerate(cases)}
        Z = np.array([0.0, 0.0, 1.0])
        for li, ld in enumerate(self.data.get('loads', [])):
            if ld['case'] not in col:
                raise ModelError(f'Load {li + 1} is in case "{ld["case"]}", which is '
                                 'not in the list of load cases.')
            j = col[ld['case']]
            typ = ld['type']
            if typ == 'point':
                F[:, j] += self._point_load(ld, fem)
                continue
            fn = self.load_fn(ld['value'])

            def trac(P, n, fn=fn, typ=typ):
                v = np.asarray(fn(P[:, 0], P[:, 1]), float) * KN * np.ones(len(P))
                if typ in ('plan_vertical', 'surface_vertical'):
                    return -v[:, None] * Z
                if typ == 'normal':
                    return -v[:, None] * n
                if typ == 'surface_x':
                    return v[:, None] * np.array([1.0, 0, 0])
                if typ == 'surface_y':
                    return v[:, None] * np.array([0, 1.0, 0])
                if typ == 'projected_x':
                    return (v * np.abs(n[:, 0]))[:, None] * np.array([1.0, 0, 0])
                if typ == 'projected_y':
                    return (v * np.abs(n[:, 1]))[:, None] * np.array([0, 1.0, 0])
                raise ModelError(f'Unknown load type {typ!r}.')
            per = 'plan' if typ == 'plan_vertical' else 'surface'
            try:
                Fe = shells.surface_load(trac, per=per)
            except formula.FormulaError as exc:
                raise ModelError(f'Load {li + 1} ("{ld["value"]}"): {exc}') from None
            np.add.at(F[:, j], shells.dofs, Fe)
            Fe_cases[j] += Fe
        if self.data.get('self_weight'):
            j = col[self.data['self_weight_case']]
            gam = fem['gamma']
            t_e = shells.a

            # per element constant thickness: traction = gamma * t (surface)
            Fe = np.zeros((shells.ne, 24))
            w = gam * t_e
            pts, wg = np.polynomial.legendre.leggauss(2)
            for ii, r in enumerate(pts):
                for jj, s in enumerate(pts):
                    h, hr, hs = fe.shape4(r, s)
                    gr = np.einsum('k,ekj->ej', hr, shells.xe)
                    gs = np.einsum('k,ekj->ej', hs, shells.xe)
                    dA = np.linalg.norm(np.cross(gr, gs), axis=1)
                    for k in range(4):
                        Fe[:, 6 * k + 2] -= h[k] * wg[ii] * wg[jj] * dA * w
            np.add.at(F[:, j], shells.dofs, Fe)
            Fe_cases[j] += Fe
            for fr in frames:
                F[fr.dofs, j] += fr.load_vector()
        return F, cases, Fe_cases

    def _point_load(self, ld, fem):
        X = fem['X']
        try:
            px, py = self.ws.scalar(str(ld.get('x', 0))), self.ws.scalar(str(ld.get('y', 0)))
        except formula.FormulaError as exc:
            raise ModelError(f'Point load position: {exc}') from None
        n = int(np.argmin((X[:fem['mesh']['X'].shape[0], 0] - px) ** 2 +
                          (X[:fem['mesh']['X'].shape[0], 1] - py) ** 2))
        f = np.zeros(fe.NDOF * fem['nn'])
        f[6 * n + 0] = float(ld.get('Px', 0.0)) * KN
        f[6 * n + 1] = float(ld.get('Py', 0.0)) * KN
        f[6 * n + 2] = -float(ld.get('Pz', 0.0)) * KN
        return f

    # -- analysis -------------------------------------------------------------
    def analyze(self):
        """Solve every load case, then form every combination. Returns a
        Results object."""
        if self.ws.errors():
            bad = '; '.join(f'{t} -> {e}' for t, e in self.ws.errors()[:3])
            raise ModelError(f'Fix the definitions first: {bad}')
        fem = self.build()
        fem['k_shell'] = fem['shells'].stiffness()
        K = fe.assemble(fem['nn'], fem['shells'], fem['frames'], k_shell=fem['k_shell'])
        F, cases, fem['Fe_cases'] = self.load_vectors(fem)
        U, R = fe.solve(K, F, fem['fixed'], fem['X'])
        return Results(self, fem, cases, U, R, F)


# ═══════════════════════════════════════════════════════════════════════════
#  Results
# ═══════════════════════════════════════════════════════════════════════════
def principal(Nx, Ny, Nxy):
    """Principal values (max, min) and the angle of the max one from e1."""
    c = 0.5 * (Nx + Ny)
    r = np.sqrt((0.5 * (Nx - Ny)) ** 2 + Nxy ** 2)
    ang = 0.5 * np.arctan2(2 * Nxy, Nx - Ny)
    return c + r, c - r, ang


class Results:
    """Per-case answers, combinations and the queries the UI and design
    need. All fields in SI (N/m, N*m/m, m)."""

    FIELDS = ('Nx', 'Ny', 'Nxy', 'Mx', 'My', 'Mxy', 'Qx', 'Qy')

    def __init__(self, model, fem, cases, U, R, F):
        self.model = model
        self.fem = fem
        self.cases = cases
        self.kinds = model.case_kinds()
        self.U, self.R, self.F = U, R, F
        sh = fem['shells']
        self.per_case = []
        for j in range(len(cases)):
            r = sh.resultants(U[:, j])
            self.per_case.append({k: r[k] for k in self.FIELDS})
        self.frame = sh.frames()
        code = model.code
        d = model.data['design']
        self.wind_scale = code.wind_scale_for(model.data['wind'].get('basis', '2005'))
        self.combos = code.combinations(self.kinds, d.get('f1', 0.5), d.get('f2', 0.2),
                                        wind_scale=self.wind_scale)
        self.service = code.service_combination(self.kinds)
        self.equilibrium = [self._equilibrium(j) for j in range(len(cases))]

    # -- combining --------------------------------------------------------------
    def factors_vector(self, combo):
        return np.array([combo.factors.get(c, 0.0) for c in self.cases])

    def combo_field(self, combo, name):
        f = self.factors_vector(combo)
        return sum(f[j] * self.per_case[j][name] for j in range(len(self.cases)) if f[j])  \
            if np.any(f) else np.zeros(self.fem['shells'].ne)

    def combo_forces(self, combo):
        return {k: self.combo_field(combo, k) for k in self.FIELDS}

    def combo_U(self, combo):
        return self.U @ self.factors_vector(combo)

    def case_forces(self, j):
        return self.per_case[j]

    # -- equilibrium ----------------------------------------------------------
    def _equilibrium(self, j):
        """Applied loads + reactions, forces and moments about the origin.
        Returns (residual force N, residual moment N*m, scale N)."""
        X = self.fem['X']
        F = self.F[:, j].reshape(-1, 6)
        R = self.R[:, j].reshape(-1, 6)
        tot = F + R
        f = tot[:, :3].sum(axis=0)
        mom = (np.cross(X, tot[:, :3]) + tot[:, 3:]).sum(axis=0)
        scale = max(np.abs(F[:, :3]).sum(), 1.0)
        return {'force': f, 'moment': mom, 'scale': scale,
                'applied': F[:, :3].sum(axis=0), 'reaction': R[:, :3].sum(axis=0)}

    # -- queries ----------------------------------------------------------------
    def node_disp(self, U):
        return U.reshape(-1, 6)[:, :3]

    def beam_internal(self, combo_or_case):
        """Internal forces along every beam/column frame for a combination
        (Combination) or a case index (int). Self-weight on frames belongs to
        the self-weight case and is factored with it."""
        if isinstance(combo_or_case, int):
            fac = np.zeros(len(self.cases))
            fac[combo_or_case] = 1.0
        else:
            fac = self.factors_vector(combo_or_case)
        U = self.U @ fac
        swc = self.model.data.get('self_weight_case')
        sw = self.model.data.get('self_weight')
        k = fac[self.cases.index(swc)] if (sw and swc in self.cases) else 0.0
        out = []
        for fr in self.fem['frames']:
            out.append(fr.internal(U, xs=np.linspace(0, fr.L, 5), w_global=fr.w * k))
        return out

    def head_shear(self, combo, column):
        # 'column' is a head / block entry of fem['heads']
        """Vertical force (N, downward +) that the SHELL delivers into a
        column head -- the punching shear -- for a combination. Summed from
        the nodal forces of the shell elements just outside the head (each
        element's K u minus its own load), so beams framing into the head
        and loads on the head itself are not counted as shell shear."""
        fac = self.factors_vector(combo)
        U = self.U @ fac
        sh = self.fem['shells']
        Fe = np.tensordot(fac, self.fem['Fe_cases'], axes=1)       # (ne, 24)
        head = set(column['head_nodes'])
        inside = set(column['head_elems'])
        Vz = 0.0
        for e in range(sh.ne):
            if e in inside:
                continue
            nodes = sh.elems[e]
            touch = [k for k in range(4) if int(nodes[k]) in head]
            if not touch:
                continue
            f = self.fem['k_shell'][e] @ U[sh.dofs[e]] - Fe[e]
            for k in touch:
                Vz += -f[6 * k + 2]          # force of the element on the node
        return -Vz

    def hypar_fit(self):
        """If the surface is a hyperbolic paraboloid z = p + q x + r y + k x y
        (exactly, on the mesh), return k; else None."""
        X = self.fem['mesh']['X']
        x, y, z = X[:, 0], X[:, 1], X[:, 2]
        A = np.stack([np.ones_like(x), x, y, x * y], axis=1)
        coef, *_ = np.linalg.lstsq(A, z, rcond=None)
        res = np.abs(A @ coef - z).max()
        span = max(z.max() - z.min(), 1e-9)
        if res < 1e-7 * max(span, 1.0) and abs(coef[3]) > 1e-9:
            return float(coef[3])
        return None
