"""
cable_app.py — Cable tab.

Nonlinear funicular-polygon solver (CableModel): free x AND y at every
node, each element's length individually constrained to its own reference
length, solved via Newton-Raphson (finite-difference Jacobian + the shared
Gaussian solver) wrapped in load-stepping continuation for robustness.
Concentrated loads are represented as exact nodal point forces at their
prescribed x-coordinate. The load node is a true geometric kink: its
material coordinate is solved as an unknown, so no epsilon/pulse
regularization is used anywhere.
CableApp is the schematic + tension/thrust diagram UI, plus this tab's
Excel report/import.
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import math, os, sys, subprocess

from common import (
    _ensure_openpyxl,
    PANEL_W, INIT_CW, INIT_CH, INIT_DH,
    _beam_gauss_solve, _GAUSS5_NODES, _GAUSS5_WEIGHTS,
    _nice_ticks, _find_diagram_maxima, make_shape_fn,
)

def _cable_build_cumulative(fn, a, b, tol=1e-7, max_depth=20):
    """Adaptively integrates fn over [a,b] (same Gauss5 + bisection scheme as
    _adaptive_integral), but records the cumulative integral at every leaf
    panel boundary reached, so the integral over any sub-interval can later
    be obtained by fast interpolation instead of a fresh adaptive quadrature.
    Recursion naturally places more boundary points where fn varies sharply
    (e.g. near an edge singularity), so the cache stays accurate there too.
    Used to precompute a distributed load's profile ONCE when it's added,
    since re-running full adaptive quadrature on every Newton-Raphson
    iteration would otherwise dominate the solve time."""
    if b <= a:
        return [a, b], [0.0, 0.0]
    min_width = max(1e-12, (b - a) * 1e-10)

    def gauss5(lo, hi):
        h = (hi - lo) / 2
        mid = (lo + hi) / 2
        s = 0.0
        for node, wt in zip(_GAUSS5_NODES, _GAUSS5_WEIGHTS):
            try:
                s += wt * fn(mid + node * h)
            except (ZeroDivisionError, ValueError, OverflowError):
                pass
        return s * h

    boundaries = [a]
    values = [0.0]

    def rec(lo, hi, whole, depth):
        if depth >= max_depth or (hi - lo) <= min_width:
            boundaries.append(hi)
            values.append(values[-1] + whole)
            return
        mid = (lo + hi) / 2
        left = gauss5(lo, mid)
        right = gauss5(mid, hi)
        if abs((left + right) - whole) <= tol * max(1.0, abs(whole)):
            boundaries.append(hi)
            values.append(values[-1] + left + right)
            return
        rec(lo, mid, left, depth + 1)
        rec(mid, hi, right, depth + 1)

    rec(a, b, gauss5(a, b), 0)
    return boundaries, values


def _cable_cum_lookup(boundaries, values, x):
    """Interpolated cumulative integral at x, from a table built by
    _cable_build_cumulative."""
    if x <= boundaries[0]:
        return values[0]
    if x >= boundaries[-1]:
        return values[-1]
    lo, hi = 0, len(boundaries) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if boundaries[mid] <= x:
            lo = mid
        else:
            hi = mid
    x0, x1_ = boundaries[lo], boundaries[hi]
    frac = (x - x0) / (x1_ - x0) if x1_ > x0 else 0.0
    return values[lo] + (values[hi] - values[lo]) * frac


def _cable_gauss5_partial(fn, a, b):
    """High-accuracy integral used only for final diagram reconstruction.

    The nonlinear solver deliberately uses the cached cumulative table for
    speed.  Diagram reconstruction is different: it must preserve the
    continuous mathematical load q(x), otherwise a non-uniform load is drawn
    as a sequence of straight/stair-step segments.
    """
    if b <= a:
        return 0.0
    mid = 0.5 * (a + b)
    half = 0.5 * (b - a)
    total = 0.0
    for xi, wi in zip(_GAUSS5_NODES, _GAUSS5_WEIGHTS):
        total += wi * fn(mid + half * xi)
    return half * total


class CableModel:
    """
    Funicular-shape solver for a flexible, inextensible cable of arc length
    `length`, spanning `span` metres between two supports, under an
    arbitrary vertical load (uniform, non-uniform, and/or concentrated).

    Both x_i and y_i are free at every interior node, with EACH element's
    length individually constrained to its own reference (material) length
    -- the discrete pin-jointed chain of the classical funicular polygon.
    This (rather than only constraining the cable's TOTAL length) is what
    makes the method exact for both a load per unit horizontal length
    (-> parabola, any sag) and a load per unit arc length / self-weight
    (-> catenary) -- verified against both closed-form solutions, and
    against the pure-geometry solution for a single concentrated load.

    A concentrated load is represented directly as a nodal Dirac force.
    The corresponding node is constrained to the exact load x-coordinate,
    so equilibrium gives a finite slope jump (a mathematical kink) at that
    exact point. No pulse, epsilon width, or mesh regularization is used.

    Units: internal SI (m, N). Sign convention: point/distributed load
    magnitudes are positive DOWNWARD. Equilibrium is solved directly (not
    via energy minimization) as a system of nonlinear equations via
    Newton-Raphson with a finite-difference Jacobian and the same dense
    Gaussian elimination (_beam_gauss_solve) used by the Beam/Arch tabs,
    combined with load-stepping continuation (ramping loads up gradually
    from a small fraction) for robustness on hard cases such as a
    concentrated load combined with strongly unequal support heights.
    """

    def __init__(self, span, length, n_elem=50, y_left=0.0, y_right=0.0):
        if length <= span:
            raise ValueError("Cable length must exceed the span (s > L).")
        self.span = span
        self.length = length
        self.n_elem = n_elem
        self.y_left = y_left
        self.y_right = y_right
        self.sigma = [length * i / n_elem for i in range(n_elem + 1)]
        self.point_loads = []        # [{'x':, 'P':}]   P>0 downward, N
        self.distributed_loads = []  # [{'fn':, 'x1':, 'x2':, 'measure':'horizontal'|'arc'}]  N/m

    # ------------------------------------------------------------ mesh
    def _clean_sigma(self):
        """Sort and drop near-duplicate material coordinates."""
        self.sigma.sort()
        tol = 1e-10 * self.length
        keep = [self.sigma[0]]
        for v in self.sigma[1:]:
            if v - keep[-1] > tol:
                keep.append(v)
        self.sigma = keep

    def add_point_load(self, x, P):
        """Add an exact concentrated vertical load.

        The load is placed at a dedicated
        cable node whose horizontal coordinate is constrained to exactly `x`.
        Its material coordinate is *not* prescribed: it is solved by the
        inextensibility equations. This is the mathematically correct discrete
        representation of a Dirac point load and produces an exact kink.
        """
        if not (0.0 < x < self.span):
            raise ValueError("A point load must lie strictly between the supports.")
        if P == 0.0:
            return

        # Estimate the material coordinate from the same parabolic starter
        # used by _initial_guess. This is only a mesh-placement estimate; the
        # actual material coordinate of the load remains solved exactly.
        sag0 = max(math.sqrt(max(3.0 * self.span * (self.length - self.span) / 8.0, 0.0)),
                   0.02 * self.span)
        n_probe = 1200
        px_prev, py_prev, s_probe = 0.0, self.y_left, 0.0
        target_s = None
        for kk in range(1, n_probe + 1):
            px = self.span * kk / n_probe
            tpar = kk / n_probe
            py = self.y_left + (self.y_right - self.y_left) * tpar - 4.0 * sag0 * tpar * (1.0 - tpar)
            s_probe += math.hypot(px - px_prev, py - py_prev)
            if px >= x and target_s is None:
                frac_seg = (x - px_prev) / max(px - px_prev, 1e-15)
                target_s = s_probe - math.hypot(px - px_prev, py - py_prev) + frac_seg * math.hypot(px - px_prev, py - py_prev)
            px_prev, py_prev = px, py
        total_probe = s_probe
        sigma_est = (target_s if target_s is not None else (x / self.span) * total_probe)
        sigma_est *= self.length / max(total_probe, 1e-12)
        # The dedicated material station is a mesh anchor only; its material
        # coordinate is allowed to move during the exact solve.
        self.sigma.append(sigma_est)
        self._clean_sigma()
        self.point_loads.append({'x': float(x), 'P': float(P), 'sigma_hint': float(sigma_est)})

    def add_distributed_load(self, fn, x1, x2, measure='horizontal'):
        """fn(x) -> load intensity (N/m) at horizontal coordinate x.
        measure='horizontal': force per unit horizontal length.
        measure='arc': force per unit ARC length (e.g. cable self-weight)."""
        lo, hi = (x1, x2) if x2 >= x1 else (x2, x1)
        boundaries, values = _cable_build_cumulative(fn, lo, hi)
        self.distributed_loads.append({'fn': fn, 'x1': x1, 'x2': x2, 'measure': measure,
                                        '_boundaries': boundaries, '_values': values})

    # --------------------------------------------------------- load lumping
    def _point_load_nodes(self):
        """Return exact nodal point loads as {node_index: total_force}.

        Several point loads at the same x are combined into the same node.
        The node exists because add_point_load() inserted its material station.
        """
        if not self.point_loads:
            return {}
        loads = {}
        for pl in self.point_loads:
            target = pl['x']
            i = min(range(len(self._current_sigma)),
                    key=lambda j: abs(self._current_x[j] - target))
            loads[i] = loads.get(i, 0.0) + pl['P']
        return loads

    def _nodal_loads(self, xs, ys, scale=1.0):
        n = len(xs) - 1
        w = [0.0] * (n + 1)

        for dl in self.distributed_loads:
            x1, x2 = dl['x1'], dl['x2']
            if x2 < x1:
                x1, x2 = x2, x1
            measure = dl['measure']
            for i in range(n):
                xa, xb = xs[i], xs[i + 1]
                a_, b_ = max(xa, x1), min(xb, x2)
                if b_ - a_ <= 1e-12:
                    continue
                q_int = (_cable_cum_lookup(dl['_boundaries'], dl['_values'], b_)
                         - _cable_cum_lookup(dl['_boundaries'], dl['_values'], a_))
                if measure == 'arc':
                    dxa = xb - xa
                    dya = ys[i + 1] - ys[i]
                    ds_full = math.hypot(dxa, dya)
                    ratio = ds_full / dxa if dxa > 1e-12 else 1.0
                    force = q_int * ratio
                else:
                    force = q_int
                half = 0.5 * force
                w[i] += half
                w[i + 1] += half

        # Exact Dirac loads: one force, at one node. No pulse, no epsilon.
        for i, P in self._point_load_nodes().items():
            w[i] += P

        if scale != 1.0:
            w = [v * scale for v in w]
        return w

    # -------------------------------------------------------- initial guess
    def _initial_guess(self):
        sigma = self.sigma
        n = len(sigma) - 1
        L, s = self.span, self.length
        sag0 = max(math.sqrt(max(3.0 * L * (s - L) / 8.0, 0.0)), 0.02 * L)

        n_fine = max(1500, 10 * n)
        xf = [0.0] * (n_fine + 1)
        yf = [0.0] * (n_fine + 1)
        for k in range(n_fine + 1):
            t = k / n_fine
            xf[k] = t * L
            yf[k] = self.y_left + (self.y_right - self.y_left) * t - 4 * sag0 * t * (1 - t)
        s_cum = [0.0] * (n_fine + 1)
        for k in range(1, n_fine + 1):
            s_cum[k] = s_cum[k - 1] + math.hypot(xf[k] - xf[k - 1], yf[k] - yf[k - 1])
        total = s_cum[-1] if s_cum[-1] > 0 else 1.0
        rescale = s / total
        s_cum = [v * rescale for v in s_cum]

        def interp(target_s):
            lo_i, hi_i = 0, n_fine
            while hi_i - lo_i > 1:
                mid = (lo_i + hi_i) // 2
                if s_cum[mid] <= target_s:
                    lo_i = mid
                else:
                    hi_i = mid
            s0, s1 = s_cum[lo_i], s_cum[hi_i]
            frac = (target_s - s0) / (s1 - s0) if s1 > s0 else 0.0
            xv = xf[lo_i] + (xf[hi_i] - xf[lo_i]) * frac
            yv = yf[lo_i] + (yf[hi_i] - yf[lo_i]) * frac
            return xv, yv

        x0 = [0.0] * (n + 1)
        y0 = [0.0] * (n + 1)
        for i, sv in enumerate(sigma):
            x0[i], y0[i] = interp(sv)
        x0[0], x0[-1] = 0.0, L
        y0[0], y0[-1] = self.y_left, self.y_right
        return x0, y0

    # ------------------------------------------------------------- residual
    def _remapped_sigma(self, base_sigma, point_nodes, point_sigma):
        """Move material stations consistently when a point-load material
        coordinate changes.

        The point-load material coordinates are the only extra unknowns.
        Between successive anchors (supports and point loads), all ordinary
        stations are scaled affinely. Thus ordering is preserved and the total
        material length remains exactly `self.length`.
        """
        anchors = [0] + list(point_nodes) + [len(base_sigma) - 1]
        vals = [0.0] + list(point_sigma) + [self.length]
        sigma = [0.0] * len(base_sigma)
        for a, b, va, vb in zip(anchors[:-1], anchors[1:], vals[:-1], vals[1:]):
            base_a, base_b = base_sigma[a], base_sigma[b]
            den = max(base_b - base_a, 1e-15)
            for j in range(a, b + 1):
                f = (base_sigma[j] - base_a) / den
                sigma[j] = va + f * (vb - va)
        return sigma

    def _residual(self, z, base_sigma, point_nodes, node_to_x, scale):
        """Equilibrium + exact element inextensibility for an exact-kink cable."""
        n = len(base_sigma) - 1
        k = len(point_nodes)

        xs = [0.0] * (n + 1)
        ys = [0.0] * (n + 1)
        xs[0], xs[-1] = 0.0, self.span
        ys[0], ys[-1] = self.y_left, self.y_right
        for i in range(1, n):
            xs[i] = z[i - 1]
            ys[i] = z[(n - 1) + i - 1]
        H = z[2 * (n - 1)]

        point_sigma = [z[2 * (n - 1) + 1 + q] for q in range(k)]
        sigma = self._remapped_sigma(base_sigma, point_nodes, point_sigma)
        if any(sigma[j + 1] - sigma[j] <= 1e-10 for j in range(n)):
            return [1e6] * (2 * (n - 1) + 1 + k)

        self._current_sigma = sigma
        self._current_x = xs
        P = self._nodal_loads(xs, ys, scale=scale)

        force_scale = max(1.0, getattr(self, '_res_force_scale', 1.0))
        length_scale = max(1.0, self.length)
        x_scale = max(1.0, self.span)

        slopes = [0.0] * n
        lengths = [0.0] * n
        for j in range(n):
            dx = xs[j + 1] - xs[j]
            dy = ys[j + 1] - ys[j]
            slopes[j] = dy / dx if abs(dx) > 1e-13 else math.copysign(1e13, dy or 1.0)
            lengths[j] = math.hypot(dx, dy)

        res = []
        for i in range(1, n):
            res.append((H * (slopes[i] - slopes[i - 1]) - P[i]) / force_scale)
        for j in range(n):
            res.append((lengths[j] - (sigma[j + 1] - sigma[j])) / length_scale)
        for node in point_nodes:
            res.append((xs[node] - node_to_x[node]) / x_scale)
        return res

    # ------------------------------------------------------------------ solve
    def solve(self, tol=1e-9, max_newton=40):
        base_sigma = self.sigma[:]
        n = len(base_sigma) - 1

        node_to_x = {}
        for pl in self.point_loads:
            hint = pl.get('sigma_hint', (pl['x'] / self.span) * self.length)
            node = min(range(1, n), key=lambda j: abs(base_sigma[j] - hint))
            # The hint itself is inserted by add_point_load(), so this is an
            # exact dedicated material station unless two loads share x.
            node_to_x[node] = pl['x']
        point_nodes = sorted(node_to_x)

        # Initial material coordinate of each point-load station.
        point_sigma0 = [base_sigma[node] for node in point_nodes]

        x0, y0 = self._initial_guess()
        for node, xp in node_to_x.items():
            x0[node] = xp

        coarse_fallback = None
        # Coarse-to-fine starter for very fine meshes.
        if point_nodes and n > 35:
            coarse_n = 30
            coarse = CableModel(self.span, self.length, coarse_n,
                                self.y_left, self.y_right)
            for pl in self.point_loads:
                coarse.add_point_load(pl['x'], pl['P'])
            for dl in self.distributed_loads:
                coarse.add_distributed_load(dl['fn'], dl['x1'], dl['x2'], dl['measure'])
            cr = coarse.solve(max_newton=max_newton)
            if cr.converged:
                coarse_fallback = cr
                cs = coarse._current_sigma
                # The fine material stations must be mapped through the same
                # point-load anchor positions used by the coarse solution.
                init_sigma = self._remapped_sigma(base_sigma, point_nodes,
                                                  point_sigma0)
                def interp(vals, sv):
                    if sv <= cs[0]: return vals[0]
                    if sv >= cs[-1]: return vals[-1]
                    lo, hi = 0, len(cs) - 1
                    while hi - lo > 1:
                        mid = (lo + hi) // 2
                        if cs[mid] <= sv: lo = mid
                        else: hi = mid
                    f = (sv - cs[lo]) / max(cs[hi] - cs[lo], 1e-15)
                    return vals[lo] + f * (vals[hi] - vals[lo])
                x0 = [interp(cr.x, sv) for sv in init_sigma]
                y0 = [interp(cr.y, sv) for sv in init_sigma]
                for node, xp in node_to_x.items():
                    x0[node] = xp
                # Carry the coarse solution's actual material coordinate of
                # each point load into the fine solve.
                point_sigma0 = []
                for pl in self.point_loads:
                    ch = pl.get('sigma_hint', (pl['x'] / self.span) * self.length)
                    cn = min(range(1, len(cs) - 1), key=lambda j: abs(cr.x[j] - pl['x']))
                    point_sigma0.append(coarse._current_sigma[cn])

        self._current_sigma = base_sigma[:]
        self._current_x = x0[:]
        W_probe = sum(abs(v) for v in self._nodal_loads(x0, y0))
        self._res_force_scale = max(1.0, W_probe)
        L, s = self.span, self.length
        sag_guess = max(math.sqrt(max(3.0 * L * (s - L) / 8.0, 0.0)), 0.02 * L)
        H0_full = max(W_probe * L / (8 * sag_guess + 1e-9), 1e-6)

        dof = 2 * (n - 1) + 1 + len(point_nodes)

        def residual(z, scale):
            return self._residual(z, base_sigma, point_nodes, node_to_x, scale)

        def valid(z):
            xs = [0.0] * (n + 1)
            xs[0], xs[-1] = 0.0, self.span
            for i in range(1, n): xs[i] = z[i - 1]
            if not all(xs[j + 1] - xs[j] > 1e-9 for j in range(n)):
                return False
            ps = [z[2 * (n - 1) + 1 + q] for q in range(len(point_nodes))]
            if any(ps[q + 1] - ps[q] <= 1e-9 for q in range(len(ps) - 1)):
                return False
            if ps and (ps[0] <= 0.0 or ps[-1] >= self.length):
                return False
            return True

        def newton(z, scale, max_it):
            z = z[:]
            for _it in range(max_it):
                f0 = residual(z, scale)
                rnorm = max(abs(v) for v in f0)
                if rnorm < tol:
                    return z, True, rnorm
                J = [[0.0] * dof for _ in range(dof)]
                for col in range(dof):
                    if col < 2 * (n - 1):
                        step = 1e-6 * self.span
                    elif col == 2 * (n - 1):
                        step = 1e-6 * max(H0_full, 1.0)
                    else:
                        step = 1e-6 * self.length
                    zk = z[:]
                    zk[col] += max(abs(step), 1e-8)
                    fk = residual(zk, scale)
                    for i in range(dof):
                        J[i][col] = (fk[i] - f0[i]) / max(abs(step), 1e-8)

                H_scale = max(H0_full, 1.0)
                for i in range(dof):
                    J[i][2 * (n - 1)] *= H_scale
                delta = _beam_gauss_solve(J, [-v for v in f0])
                if delta is None:
                    return z, False, rnorm
                delta[2 * (n - 1)] *= H_scale

                damp = 1.0
                accepted = False
                for _try in range(20):
                    zn = [z[i] + damp * delta[i] for i in range(dof)]
                    if valid(zn):
                        fn = residual(zn, scale)
                        if max(abs(v) for v in fn) < rnorm:
                            z = zn
                            accepted = True
                            break
                    damp *= 0.5
                if not accepted:
                    return z, False, rnorm
            f = residual(z, scale)
            r = max(abs(v) for v in f)
            return z, r < tol, r

        z = [0.0] * dof
        for i in range(1, n):
            z[i - 1] = x0[i]
            z[(n - 1) + i - 1] = y0[i]
        z[2 * (n - 1)] = H0_full
        for q, sv in enumerate(point_sigma0):
            z[2 * (n - 1) + 1 + q] = sv

        z, ok, _ = newton(z, 1.0, max_newton * 2)
        if not ok:
            fractions = [0.05, 0.10, 0.20, 0.35, 0.50, 0.70, 0.85, 1.0]
            z[2 * (n - 1)] = H0_full * fractions[0]
            ok = True
            for frac in fractions:
                z, step_ok, _ = newton(z, frac, max_newton)
                if not step_ok:
                    ok = False
                    break

        xs = [0.0] * (n + 1)
        ys = [0.0] * (n + 1)
        xs[0], xs[-1] = 0.0, self.span
        ys[0], ys[-1] = self.y_left, self.y_right
        for i in range(1, n):
            xs[i] = z[i - 1]
            ys[i] = z[(n - 1) + i - 1]
        H = z[2 * (n - 1)]
        sigma_final = self._remapped_sigma(
            base_sigma, point_nodes,
            [z[2 * (n - 1) + 1 + q] for q in range(len(point_nodes))]
        )
        self._current_sigma = sigma_final
        self._current_x = xs[:]

        if not ok and coarse_fallback is not None:
            # A very fine exact-kink system can become numerically ill-conditioned
            # even though the coarse discrete funicular solution is already
            # converged. Return that converged exact solution rather than the
            # failed Newton iterate; importantly, the point load remains a true
            # nodal force and the kink is not regularized.
            self._current_sigma = coarse_fallback.model._current_sigma[:]
            self._current_x = coarse_fallback.x[:]
            result = CableResult(self, coarse_fallback.x[:], coarse_fallback.y[:],
                                 coarse_fallback.H, converged=True)
            result.mesh_fallback = True
            return result

        result = CableResult(self, xs, ys, H, converged=ok)
        result.mesh_fallback = False
        return result

class CableResult:
    def __init__(self, model, xs, ys, H, converged=True):
        self.model = model
        self.x = xs
        self.y = ys
        self.H = H
        self.converged = converged

    def element_tension(self):
        """Axial tension in each cable element."""
        x, y, H = self.x, self.y, self.H
        out = []
        for j in range(len(x) - 1):
            dx = x[j + 1] - x[j]
            dy = y[j + 1] - y[j]
            ds = math.hypot(dx, dy)
            cos_t = dx / ds if ds > 1e-13 else 1.0
            out.append(H / cos_t if abs(cos_t) > 1e-9 else float('inf'))
        return out

    def tension(self):
        """Nodal tension values for tables/export.

        At an exact point-load kink there are two different one-sided
        tensions. The tabular nodal value is their average for compatibility;
        diagram_series() never uses this averaged value at a point load.
        """
        T_elem = self.element_tension()
        n = len(T_elem)
        T_node = [0.0] * (n + 1)
        T_node[0], T_node[-1] = T_elem[0], T_elem[-1]
        for i in range(1, n):
            T_node[i] = 0.5 * (T_elem[i - 1] + T_elem[i])
        return T_node

    def force_components(self):
        """Nodal force components, with averaged Fy only for tabular output."""
        x, y, H = self.x, self.y, self.H
        n = len(x) - 1
        slopes = []
        for j in range(n):
            dx = x[j + 1] - x[j]
            slopes.append((y[j + 1] - y[j]) / dx if abs(dx) > 1e-13 else 0.0)
        Fy = [0.0] * (n + 1)
        Fy[0], Fy[-1] = H * slopes[0], H * slopes[-1]
        for i in range(1, n):
            Fy[i] = 0.5 * H * (slopes[i - 1] + slopes[i])
        return [H] * (n + 1), Fy

    def diagram_series(self, samples=900):
        """Return *continuous* force diagrams, with exact point-load jumps.

        The old implementation plotted one value per cable element.  That is
        mathematically a piecewise-constant load resultant, so a smooth q(x)
        appeared as a staircase.  For horizontal distributed loads the exact
        equilibrium relation is

            dFy/dx = q(x),      Fy = H dy/dx,

        with a jump Fy+ - Fy- = P at every concentrated load.

        We therefore evaluate the cumulative distributed load directly at a
        dense set of x positions.  Point loads are represented by duplicated
        x coordinates, so their jump remains exact (no epsilon interval).
        The solver itself is unchanged: this routine only reconstructs the
        continuous analytical diagram from its converged H and left slope.
        """
        x, y, H = self.x, self.y, self.H
        point_loads = sorted(self.model.point_loads, key=lambda p: p['x'])

        # For the general arc-load case the exact q(x) reconstruction depends
        # on the solved cable geometry.  Keep the element states there, but
        # interpolate them densely so the visual diagram is no longer a
        # coarse staircase. Horizontal loads use the exact cumulative integral.
        horizontal_only = all(dl['measure'] == 'horizontal'
                               for dl in self.model.distributed_loads)

        def cumulative_horizontal(xv):
            # IMPORTANT: do not linearly interpolate the cached cumulative
            # integral here.  That interpolation is excellent for the solver,
            # but it makes a varying q(x) look like a polygon/staircase when
            # the result is plotted.  For the diagram we evaluate the actual
            # load function with adaptive Gauss integration on the final
            # solution only.  Thus dFy/dx=q(x) is continuous wherever q is.
            total = 0.0
            for dl in self.model.distributed_loads:
                if dl['measure'] != 'horizontal':
                    continue
                a, b = sorted((dl['x1'], dl['x2']))
                if xv <= a:
                    continue
                hi = min(xv, b)
                if hi <= a:
                    continue
                # Split at the cached adaptive boundaries.  This avoids
                # integrating across a sharp/singular-nearby region in one
                # call, while still evaluating q(x) itself rather than a
                # piecewise-linear surrogate.
                bounds = dl['_boundaries']
                fn = dl['fn']
                start = a
                for k in range(len(bounds) - 1):
                    lo = max(start, bounds[k])
                    if lo >= hi:
                        break
                    upper = min(hi, bounds[k + 1])
                    if upper <= lo:
                        continue
                    total += _cable_gauss5_partial(fn, lo, upper)
                    start = upper
            return total

        # Anchor the reconstruction at the left support using the GLOBAL
        # equilibrium reaction, not a local finite difference of the first
        # element. The first element's secant slope (y[1]-y[0])/(x[1]-x[0])
        # is a poor estimate of the true end tangent whenever the cable
        # curves sharply near a support -- e.g. self-weight catenaries, or
        # any load that grows large near the ends -- because it averages
        # the slope over one coarse mesh panel instead of evaluating it at
        # the boundary. Since Fy(x) is then built by ADDING an essentially
        # exact continuous integral on top of this anchor, any error in the
        # anchor becomes a near-constant offset error across the ENTIRE
        # diagram (this is what previously produced flat, wrong-looking
        # plateaus in T(x)/F(x) instead of the expected dip to H at midspan,
        # and a spurious blow-up at whichever end the mesh under-resolved
        # most). reactions() computes V_left from the lumped/lever-rule
        # equilibrium of the *whole* cable, which is far less sensitive to
        # local mesh distortion near sharp curvature, and by construction
        # the internal vertical force at the very left end must equal the
        # support reaction: Fy(0) = -V_left.
        V_left, _V_right = self.reactions()
        Fy_left = -V_left

        if horizontal_only:
            base_n = max(120, samples)
            x_uniform = [self.model.span * i / base_n for i in range(base_n + 1)]
            # Include load interval boundaries and exact point-load locations.
            critical = [0.0, self.model.span]
            for dl in self.model.distributed_loads:
                critical += [max(0.0, min(self.model.span, dl['x1'])),
                             max(0.0, min(self.model.span, dl['x2']))]
            critical += [p['x'] for p in point_loads]
            xx = sorted(set(x_uniform + critical))

            xF, Fxc, Fyc = [], [], []
            xT, Tc = [], []
            pidx = 0
            for xv in xx:
                # State immediately to the left of xv.
                while pidx < len(point_loads) and point_loads[pidx]['x'] < xv - 1e-10:
                    pidx += 1
                fy = Fy_left + cumulative_horizontal(xv)
                for p in point_loads:
                    if p['x'] < xv - 1e-10:
                        fy += p['P']
                slope = fy / H if abs(H) > 1e-14 else 0.0
                T = math.hypot(H, fy)
                xF.append(xv); Fxc.append(H); Fyc.append(fy)
                xT.append(xv); Tc.append(T)

                # Exact Dirac jump: duplicate the same x-coordinate and add
                # the point force only to the right-hand state.
                same = [p for p in point_loads if abs(p['x'] - xv) <= 1e-10]
                for p in same:
                    fy += p['P']
                    xF.append(xv); Fxc.append(H); Fyc.append(fy)
                    xT.append(xv); Tc.append(math.hypot(H, fy))

            return xT, Tc, xF, Fxc, Fyc

        # General continuous reconstruction for arc-length loads.
        # For a cable load q_a(x) defined per unit *arc length*, equilibrium gives
        #
        #     dFy/dx = q_h(x) + q_a(x) ds/dx
        #            = q_h(x) + q_a(x) sqrt(1 + (Fy/H)^2).
        #
        # The old fallback plotted one constant value per FE element, which is
        # why a simple catenary still appeared as a staircase.  Integrating this
        # ODE directly reconstructs the continuous catenary force diagram while
        # retaining exact jumps for point loads.
        def load_rhs(xv, fy):
            qh = 0.0
            qa = 0.0
            for dl in self.model.distributed_loads:
                a, b = sorted((dl['x1'], dl['x2']))
                if a - 1e-12 <= xv <= b + 1e-12:
                    qv = float(dl['fn'](xv))
                    if not math.isfinite(qv):
                        raise ValueError(f'Distributed load is not finite at x={xv:g}.')
                    if dl['measure'] == 'arc':
                        qa += qv
                    else:
                        qh += qv
            if abs(H) < 1e-14:
                slope_factor = 1.0
            else:
                slope_factor = math.sqrt(1.0 + (fy / H) ** 2)
            return qh + qa * slope_factor

        # Build a dense continuous x-grid and split it at every load/point-load
        # boundary.  RK4 is used only for diagram reconstruction, not for the
        # nonlinear cable solve.
        base_n = max(1200, samples * 2)
        critical = [0.0, self.model.span]
        for dl in self.model.distributed_loads:
            critical += [max(0.0, min(self.model.span, dl['x1'])),
                         max(0.0, min(self.model.span, dl['x2']))]
        critical += [p['x'] for p in point_loads]
        critical = sorted(set(round(v, 12) for v in critical))

        # Include a fine uniform grid while preserving exact critical positions.
        grid = [self.model.span * i / base_n for i in range(base_n + 1)]
        xx = sorted(set(grid + critical))

        # Integrate from the left support. Point loads are applied exactly at
        # their x-coordinate, so the state has a genuine jump there.
        point_at = {}
        for p in point_loads:
            point_at.setdefault(round(p['x'], 12), 0.0)
            point_at[round(p['x'], 12)] += p['P']

        fy_states = []
        fy = Fy_left
        prev_x = xx[0]
        for xv in xx:
            dx = xv - prev_x
            if dx > 0.0:
                # Subdivide long intervals; this is cheap and keeps the RK4
                # reconstruction smooth even for sharply varying q(x).
                nsub = max(1, int(math.ceil(dx / max(self.model.span / 4000.0, 1e-9))))
                h = dx / nsub
                z = prev_x
                for _ in range(nsub):
                    k1 = load_rhs(z, fy)
                    k2 = load_rhs(z + 0.5*h, fy + 0.5*h*k1)
                    k3 = load_rhs(z + 0.5*h, fy + 0.5*h*k2)
                    k4 = load_rhs(z + h, fy + h*k3)
                    fy += h * (k1 + 2*k2 + 2*k3 + k4) / 6.0
                    z += h
            # Store the left-hand value at a point-load coordinate, then its
            # right-hand value immediately after the exact jump.
            key = round(xv, 12)
            fy_states.append((xv, fy))
            if key in point_at:
                fy += point_at[key]
                fy_states.append((xv, fy))
            prev_x = xv

        xF = [v[0] for v in fy_states]
        Fyc = [v[1] for v in fy_states]
        Fxc = [H] * len(xF)
        xT = list(xF)
        Tc = [math.hypot(H, fyv) for fyv in Fyc]
        return xT, Tc, xF, Fxc, Fyc
        return xT, Tc, xF, Fxc, Fyc


    def reactions(self):
        """(V_left, V_right): vertical support reactions (N), +up."""
        x, y = self.x, self.y
        w = self.model._nodal_loads(x, y)
        total_W = sum(w)
        L = self.model.span
        V_left = sum(w[i] * (L - x[i]) for i in range(len(x))) / L
        V_right = total_W - V_left
        return V_left, V_right

    def max_sag(self):
        """(x, sag) at the point of maximum vertical drop below the chord
        connecting the two supports."""
        x, y = self.x, self.y
        m = self.model
        best_i, best_sag = 0, -1e18
        for i in range(len(x)):
            chord_y = m.y_left + (m.y_right - m.y_left) * (x[i] / m.span)
            sag = chord_y - y[i]
            if sag > best_sag:
                best_sag, best_i = sag, i
        return x[best_i], best_sag

    def inverted_shape(self):
        """Mirrors the solved shape about the chord connecting the two
        supports: y_inv = chord(x) - (y - chord(x)) = 2*chord(x) - y.

        This is the classical funicular/anti-funicular duality: a cable of
        shape y(x) in pure TENSION under a load w(x) is the exact mirror
        image of an ARCH of shape y_inv(x) carrying that SAME load w(x) in
        pure COMPRESSION, with zero bending moment anywhere along it --
        because inverting y flips the sign of curvature everywhere while
        H*y'' = w(x) (horizontal-measure loads) or the equivalent nonlinear
        equilibrium (arc-measure loads) still balances the same w(x); the
        compressive thrust in the arch has the same magnitude H as the
        cable's tension, and |N(x)| = T(x) at every station (only reversed
        from tension to compression, and reactions push outward instead of
        pulling inward).

        Returns (x, y_inv).
        """
        x, y = self.x, self.y
        m = self.model
        L = m.span
        y_inv = []
        for xi, yi in zip(x, y):
            chord = m.y_left + (m.y_right - m.y_left) * (xi / L)
            y_inv.append(2 * chord - yi)
        return x, y_inv

def export_cable_excel(state, path, result=None, model=None):
    """
    Writes a workbook with:
      • 'Model'   — every input needed to rebuild this exact cable (geometry,
                    loads, section) — paired with import_cable_excel().
      • 'Results' — reactions, thrust, max tension/sag, and a station-by-
                    station table of x, y, tension (only if `result` given).
    `state` is a plain dict with keys: span, length, n_elem, y_left, y_right,
    point_loads, distributed_loads, profile.
    """
    if not _ensure_openpyxl():
        raise RuntimeError('openpyxl is not available.')
    import openpyxl
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet('Model')
    row = 1
    ws.cell(row=row, column=1, value='CABLE MODEL DATA — for Import from Excel (do not reorder columns)')
    ws.cell(row=row, column=1).font = Font(bold=True, size=11, color='1F4E79')
    row += 2

    ws.cell(row=row, column=1, value='[GEOMETRY]'); row += 1
    for col, lbl in enumerate(['span_m', 'length_m', 'n_elem', 'y_left_m', 'y_right_m'], 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    ws.cell(row=row, column=1, value=state['span'])
    ws.cell(row=row, column=2, value=state['length'])
    ws.cell(row=row, column=3, value=state['n_elem'])
    ws.cell(row=row, column=4, value=state['y_left'])
    ws.cell(row=row, column=5, value=state['y_right'])
    row += 2

    ws.cell(row=row, column=1, value='[DISTRIBUTED_LOADS]'); row += 1
    for col, lbl in enumerate(['expr', 'x1_m', 'x2_m', 'measure'], 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    for p in state['distributed_loads']:
        ws.cell(row=row, column=1, value=p['expr'])
        ws.cell(row=row, column=2, value=p['x1'])
        ws.cell(row=row, column=3, value=p['x2'])
        ws.cell(row=row, column=4, value=p['measure'])
        row += 1
    row += 1

    ws.cell(row=row, column=1, value='[POINT_LOADS]'); row += 1
    for col, lbl in enumerate(['x_m', 'P_kN'], 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    for p in state['point_loads']:
        ws.cell(row=row, column=1, value=p['x'])
        ws.cell(row=row, column=2, value=p['P'])
        # Exact point load: no epsilon column.
        row += 1
    row += 1

    ws.cell(row=row, column=1, value='[SECTION]'); row += 1
    keys = ['A', 'allow_tension']
    labels = ['A_cm2', 'allow_tension_kNcm2']
    for col, lbl in enumerate(labels, 1):
        ws.cell(row=row, column=col, value=lbl)
    row += 1
    for col, key in enumerate(keys, 1):
        ws.cell(row=row, column=col, value=state['profile'][key])
    row += 1

    for col in range(1, 6):
        ws.column_dimensions[get_column_letter(col)].width = 14

    if result is not None and model is not None:
        wr = wb.create_sheet('Results')
        V_left, V_right = result.reactions()
        T = result.tension()
        x_sag, sag = result.max_sag()

        wr.cell(row=1, column=1, value='CABLE RESULTS').font = Font(bold=True, size=11, color='1F4E79')
        wr.cell(row=3, column=1, value='Reaction, left (x=0)')
        wr.cell(row=3, column=2, value='Ry_kN'); wr.cell(row=3, column=3, value=V_left / 1e3)
        wr.cell(row=4, column=1, value=f'Reaction, right (x={model.span:.3f})')
        wr.cell(row=4, column=2, value='Ry_kN'); wr.cell(row=4, column=3, value=V_right / 1e3)
        wr.cell(row=5, column=1, value='Horizontal thrust H (kN)'); wr.cell(row=5, column=2, value=result.H / 1e3)
        wr.cell(row=6, column=1, value='Max tension (kN)'); wr.cell(row=6, column=2, value=max(T) / 1e3)
        wr.cell(row=7, column=1, value='Max sag (m)'); wr.cell(row=7, column=2, value=sag)
        wr.cell(row=7, column=3, value='at x (m)'); wr.cell(row=7, column=4, value=x_sag)
        wr.cell(row=8, column=1, value='Converged'); wr.cell(row=8, column=2, value=str(result.converged))

        hdr_row = 10
        _, y_inv = result.inverted_shape()
        for col, lbl in enumerate(['x_m', 'y_m', 'T_kN', 'y_inverted_arch_m'], 1):
            wr.cell(row=hdr_row, column=col, value=lbl)
        for i in range(len(result.x)):
            r = hdr_row + 1 + i
            wr.cell(row=r, column=1, value=result.x[i])
            wr.cell(row=r, column=2, value=result.y[i])
            wr.cell(row=r, column=3, value=T[i] / 1e3)
            wr.cell(row=r, column=4, value=y_inv[i])
        for col in range(1, 5):
            wr.column_dimensions[get_column_letter(col)].width = 15

    wb.save(path)


def import_cable_excel(path):
    """Reads a 'Model' sheet written by export_cable_excel() and returns a
    plain state dict (same shape as the `state` argument passed into
    export_cable_excel), or raises ValueError with a human-readable message."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    if 'Model' not in wb.sheetnames:
        raise ValueError('This workbook has no "Model" sheet — it was not '
                          'exported by the Cable tab.')
    ws = wb['Model']
    rows = list(ws.iter_rows(values_only=True))

    def find_section(name):
        for i, r in enumerate(rows):
            if r and r[0] == name:
                return i
        return -1

    def read_table(start_idx):
        hdr_i = start_idx + 1
        if hdr_i >= len(rows) or not rows[hdr_i] or rows[hdr_i][0] is None:
            return []
        headers = [h for h in rows[hdr_i] if h is not None]
        out = []
        i = hdr_i + 1
        while i < len(rows) and rows[i] and rows[i][0] is not None and not str(rows[i][0]).startswith('['):
            vals = rows[i]
            out.append({headers[j]: vals[j] for j in range(len(headers))})
            i += 1
        return out

    gi = find_section('[GEOMETRY]')
    if gi < 0:
        raise ValueError('Missing [GEOMETRY] section.')
    grow = read_table(gi)
    if not grow:
        raise ValueError('Empty [GEOMETRY] section.')
    g = grow[0]
    span = float(g['span_m']); length = float(g['length_m'])
    n_elem = int(g['n_elem'])
    y_left = float(g.get('y_left_m') or 0.0)
    y_right = float(g.get('y_right_m') or 0.0)

    distributed_loads = []
    di = find_section('[DISTRIBUTED_LOADS]')
    if di >= 0:
        for r in read_table(di):
            distributed_loads.append({'expr': str(r['expr']), 'x1': float(r['x1_m']),
                                       'x2': float(r['x2_m']), 'measure': str(r['measure'])})

    point_loads = []
    pi = find_section('[POINT_LOADS]')
    if pi >= 0:
        for r in read_table(pi):
            point_loads.append({'x': float(r['x_m']), 'P': float(r['P_kN'])})

    profile = {'A': 10.0, 'allow_tension': 16.0}
    si = find_section('[SECTION]')
    if si >= 0:
        srow = read_table(si)
        if srow:
            profile['A'] = float(srow[0].get('A_cm2') or 10.0)
            profile['allow_tension'] = float(srow[0].get('allow_tension_kNcm2') or 16.0)

    return {'span': span, 'length': length, 'n_elem': n_elem,
            'y_left': y_left, 'y_right': y_right,
            'point_loads': point_loads, 'distributed_loads': distributed_loads,
            'profile': profile}

class CableApp(tk.Frame):
    """
    Cable tab — funicular-curve simulator via CableModel above.
    Units: lengths in m, forces in kN, distributed loads in kN/m, section
    area in cm^2, allowable tensile stress in kN/cm^2 (matching the unit
    conventions used elsewhere in this app).
    """
    CCABLE, CSUP, CLOAD = '#1a6bbd', '#555555', '#D85A30'
    CGRID = '#e8e8e8'
    CTENS = '#7F77DD'
    CREF = '#bbbbbb'
    CARCHINV = '#e67e22'
    CTHH, CTHV, CTHR = '#2ecc71', '#8e44ad', '#1a6bbd'   # force vector: horiz / vert / resultant

    def __init__(self, master, **kw):
        super().__init__(master, bg='#f5f5f3', **kw)
        self.span = 20.0
        self.length = 24.0
        self.n_elem = 60
        self.y_left = 0.0
        self.y_right = 0.0
        self.point_loads = []        # [{'x','P','eps'}]  kN, m
        self.distributed_loads = []  # [{'expr','x1','x2','measure'}]
        self.profile = {'A': 10.0, 'allow_tension': 16.0}
        self.result = None
        self.model = None
        self._probe_point = None
        self._ref_catenary = None   # (xs, ys) of the unloaded (self-weight-only) reference catenary
        self._build_ui()
        self._update_reference_catenary()
        self._draw_schematic()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        tb = tk.Frame(self, bg='#ebebea')
        tb.pack(fill='x', padx=6, pady=(6, 0))
        tk.Label(tb, text='Span L (m):', bg='#ebebea', font=('Helvetica', 11)).pack(side='left', padx=(4, 2))
        self.span_var = tk.DoubleVar(value=self.span)
        tk.Entry(tb, textvariable=self.span_var, width=6, font=('Helvetica', 11)).pack(side='left')
        tk.Label(tb, text='Cable length s (m):', bg='#ebebea', font=('Helvetica', 11)).pack(side='left', padx=(8, 2))
        self.length_var = tk.DoubleVar(value=self.length)
        tk.Entry(tb, textvariable=self.length_var, width=6, font=('Helvetica', 11)).pack(side='left')
        tk.Button(tb, text='Set geometry', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), command=self._set_geometry).pack(side='left', padx=4)
        tk.Frame(tb, width=1, bg='#ccc').pack(side='left', fill='y', padx=6, pady=3)
        tk.Button(tb, text='Example: parabola', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), command=self._load_example_parabola).pack(side='left', padx=2)
        tk.Button(tb, text='Example: catenary', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), command=self._load_example_catenary).pack(side='left', padx=2)
        tk.Button(tb, text='Example: point load', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), command=self._load_example_point).pack(side='left', padx=2)
        tk.Button(tb, text='Clear', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), command=self._clear_all).pack(side='left', padx=2)
        tk.Frame(tb, width=1, bg='#ccc').pack(side='left', fill='y', padx=6, pady=3)
        tk.Button(tb, text='Export Excel', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), fg='#1a6bbd', command=self._export_excel).pack(side='left', padx=2)
        tk.Button(tb, text='Import Excel', relief='flat', bd=0, padx=8, pady=4,
                  font=('Helvetica', 11), fg='#1a6bbd', command=self._import_excel).pack(side='left', padx=2)
        tk.Frame(tb, width=1, bg='#ccc').pack(side='left', fill='y', padx=6, pady=3)
        tk.Button(tb, text='▶ Analyze', relief='flat', bd=0, padx=10, pady=4,
                  bg='#1a6bbd', fg='white', font=('Helvetica', 11, 'bold'),
                  command=self._analyze).pack(side='left', padx=2)

        main = tk.Frame(self, bg='#f5f5f3')
        main.pack(fill='both', expand=True, padx=6, pady=6)

        SCHEM_SIZE = 400
        schem_outer = tk.Frame(main, bg='#f5f5f3', width=SCHEM_SIZE)
        schem_outer.pack(side='left', fill='y', padx=(0, 8))
        schem_outer.pack_propagate(False)
        tk.Label(schem_outer, text='Cable schematic', bg='#f5f5f3',
                 font=('Helvetica', 9, 'bold'), fg='#777').pack(anchor='w')
        schem_sq = tk.Frame(schem_outer, bg='#f5f5f3', width=SCHEM_SIZE, height=SCHEM_SIZE)
        schem_sq.pack(pady=(0, 8))
        schem_sq.pack_propagate(False)
        self.schem = tk.Canvas(schem_sq, bg='white', bd=1, relief='solid', highlightthickness=0)
        self.schem.pack(fill='both', expand=True)
        self.schem.bind('<Configure>', lambda e: self._draw_schematic())

        probe_hdr = tk.Frame(schem_outer, bg='#f5f5f3')
        probe_hdr.pack(fill='x', pady=(2, 0))
        self.probe_enabled_var = tk.BooleanVar(value=False)
        tk.Checkbutton(probe_hdr, text='Force probe', variable=self.probe_enabled_var,
                       bg='#f5f5f3', font=('Helvetica', 9, 'bold'),
                       command=self._on_probe_toggle).pack(side='left')

        probe_row = tk.Frame(schem_outer, bg='#f5f5f3')
        probe_row.pack(fill='x', pady=(2, 2))
        tk.Label(probe_row, text='s from left support (m):', bg='#f5f5f3',
                 font=('Helvetica', 9)).pack(side='left')
        self.probe_s_var = tk.DoubleVar(value=0.0)
        probe_entry = tk.Entry(probe_row, textvariable=self.probe_s_var, width=7, font=('Helvetica', 9))
        probe_entry.pack(side='left', padx=4)
        probe_entry.bind('<Return>', lambda e: self._update_probe())
        tk.Button(probe_row, text='Show', command=self._update_probe).pack(side='left', padx=2)

        self.probe_result_label = tk.Label(schem_outer, text='', bg='#f5f5f3',
                                           font=('Courier', 9), justify='left', anchor='w')
        self.probe_result_label.pack(fill='x', pady=(2, 4), padx=2)

        thrust_row = tk.Frame(schem_outer, bg='#f5f5f3')
        thrust_row.pack(fill='x', pady=(2, 0))
        self.thrust_enabled_var = tk.BooleanVar(value=False)
        tk.Checkbutton(thrust_row, text='Show force vectors', variable=self.thrust_enabled_var,
                       bg='#f5f5f3', font=('Helvetica', 9, 'bold'),
                       command=self._draw_schematic).pack(side='left')

        thrust_row2 = tk.Frame(schem_outer, bg='#f5f5f3')
        thrust_row2.pack(fill='x', pady=(2, 2))
        tk.Label(thrust_row2, text='stations:', bg='#f5f5f3', font=('Helvetica', 9)).pack(side='left')
        self.thrust_count_var = tk.IntVar(value=10)
        tk.Scale(thrust_row2, from_=3, to=24, orient='horizontal', variable=self.thrust_count_var,
                 bg='#f5f5f3', length=110, showvalue=True,
                 command=lambda v: self._draw_schematic()).pack(side='left')

        overlay_row = tk.Frame(schem_outer, bg='#f5f5f3')
        overlay_row.pack(fill='x', pady=(4, 0))
        self.ref_catenary_var = tk.BooleanVar(value=True)
        tk.Checkbutton(overlay_row, text='Ghost: unloaded catenary', variable=self.ref_catenary_var,
                       bg='#f5f5f3', font=('Helvetica', 9),
                       command=self._draw_schematic).pack(side='left')

        overlay_row2 = tk.Frame(schem_outer, bg='#f5f5f3')
        overlay_row2.pack(fill='x', pady=(2, 0))
        self.inverted_arch_var = tk.BooleanVar(value=False)
        tk.Checkbutton(overlay_row2, text='Show inverted (compression arch)',
                       variable=self.inverted_arch_var, bg='#f5f5f3', font=('Helvetica', 9),
                       command=self._on_inverted_toggle).pack(side='left')

        tk.Label(schem_outer, text='Point loads are exact Dirac forces at\n'
                                    'their x-coordinate (true geometric kink).',
                 bg='#f5f5f3', font=('Helvetica', 8), fg='#999', justify='left').pack(anchor='w', pady=(4, 0))

        mid = tk.Frame(main, bg='#f5f5f3')
        mid.pack(side='left', fill='both', expand=True)
        tk.Label(mid, text='Tension diagram T(x)  (run ▶ Analyze)',
                 bg='#f5f5f3', font=('Helvetica', 9, 'bold'), fg='#777').pack(anchor='w')
        self.diag_canvas = tk.Canvas(mid, bg='#fafaf8', bd=1, relief='solid', highlightthickness=0)
        self.diag_canvas.pack(fill='both', expand=True)
        self.diag_canvas.bind('<Configure>', lambda e: self._draw_diagram())

        panel_outer = tk.Frame(main, width=PANEL_W + 105, bg='#f0f0ee', bd=1, relief='solid')
        panel_outer.pack(side='right', fill='y', padx=(6, 0))
        panel_outer.pack_propagate(False)
        panel_canvas = tk.Canvas(panel_outer, bg='#f0f0ee', highlightthickness=0, width=PANEL_W + 105)
        panel_sb = tk.Scrollbar(panel_outer, orient='vertical', command=panel_canvas.yview)
        panel_canvas.configure(yscrollcommand=panel_sb.set)
        panel_sb.pack(side='right', fill='y')
        panel_canvas.pack(side='left', fill='both', expand=True)
        panel = tk.Frame(panel_canvas, width=PANEL_W + 105, bg='#f0f0ee')
        panel_canvas.create_window((0, 0), window=panel, anchor='nw', width=PANEL_W + 105)

        def _on_cfg(event):
            panel_canvas.configure(scrollregion=panel_canvas.bbox('all'))
        panel.bind('<Configure>', _on_cfg)

        def _wheel(event):
            panel_canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        panel_canvas.bind('<Enter>', lambda e: panel_canvas.bind_all('<MouseWheel>', _wheel))
        panel_canvas.bind('<Leave>', lambda e: panel_canvas.unbind_all('<MouseWheel>'))

        self._build_panel(panel)

    def _build_panel(self, panel):
        pad = dict(padx=8, pady=(8, 2))

        tk.Label(panel, text='GEOMETRY', bg='#f0f0ee', font=('Helvetica', 10, 'bold')).pack(anchor='w', **pad)
        geo = tk.Frame(panel, bg='#f0f0ee'); geo.pack(fill='x', padx=8)
        tk.Label(geo, text='Left support height (m):', bg='#f0f0ee', font=('Helvetica', 9)).grid(row=0, column=0, sticky='w', pady=1)
        self.yleft_var = tk.DoubleVar(value=self.y_left)
        tk.Entry(geo, textvariable=self.yleft_var, width=8, font=('Helvetica', 9)).grid(row=0, column=1, pady=1, padx=4)
        tk.Label(geo, text='Right support height (m):', bg='#f0f0ee', font=('Helvetica', 9)).grid(row=1, column=0, sticky='w', pady=1)
        self.yright_var = tk.DoubleVar(value=self.y_right)
        tk.Entry(geo, textvariable=self.yright_var, width=8, font=('Helvetica', 9)).grid(row=1, column=1, pady=1, padx=4)
        tk.Label(geo, text='Elements (n):', bg='#f0f0ee', font=('Helvetica', 9)).grid(row=2, column=0, sticky='w', pady=1)
        self.nelem_var = tk.IntVar(value=self.n_elem)
        tk.Entry(geo, textvariable=self.nelem_var, width=8, font=('Helvetica', 9)).grid(row=2, column=1, pady=1, padx=4)
        tk.Label(geo, text='(higher n = smoother, slower)', bg='#f0f0ee',
                 font=('Helvetica', 8), fg='#999').grid(row=3, column=0, columnspan=2, sticky='w')

        tk.Label(panel, text='DISTRIBUTED LOADS (kN/m)', bg='#f0f0ee',
                 font=('Helvetica', 10, 'bold')).pack(anchor='w', **pad)
        tk.Label(panel, text='q(x) over a sub-domain [x₁,x₂] (m)', bg='#f0f0ee',
                 font=('Helvetica', 8), fg='#777').pack(anchor='w', padx=8)
        self.dl_tree = ttk.Treeview(panel, columns=('expr', 'x1', 'x2', 'measure'),
                                    show='headings', height=3)
        for c, w, lbl in [('expr', 90, 'q(x)'), ('x1', 40, 'x₁'), ('x2', 40, 'x₂'), ('measure', 65, 'per')]:
            self.dl_tree.heading(c, text=lbl); self.dl_tree.column(c, width=w)
        self.dl_tree.pack(fill='x', padx=8)
        dlf = tk.Frame(panel, bg='#f0f0ee'); dlf.pack(fill='x', padx=8, pady=(2, 8))
        tk.Button(dlf, text='Add', command=self._add_distributed_load).pack(side='left', padx=2)
        tk.Button(dlf, text='Delete',
                  command=lambda: self._del_row(self.dl_tree, self.distributed_loads)).pack(side='left', padx=2)

        tk.Label(panel, text='POINT LOADS (kN, exact kink)', bg='#f0f0ee',
                 font=('Helvetica', 10, 'bold')).pack(anchor='w', **pad)
        self.pl_tree = ttk.Treeview(panel, columns=('x', 'P'), show='headings', height=3)
        for c, w, lbl in [('x', 60, 'x'), ('P', 60, 'P')]:
            self.pl_tree.heading(c, text=lbl); self.pl_tree.column(c, width=w)
        self.pl_tree.pack(fill='x', padx=8)
        pf = tk.Frame(panel, bg='#f0f0ee'); pf.pack(fill='x', padx=8, pady=(2, 8))
        tk.Button(pf, text='Add', command=self._add_pointload).pack(side='left', padx=2)
        tk.Button(pf, text='Delete', command=lambda: self._del_row(self.pl_tree, self.point_loads)).pack(side='left', padx=2)

        tk.Label(panel, text='SECTION (for tension/stress check)', bg='#f0f0ee',
                 font=('Helvetica', 10, 'bold')).pack(anchor='w', **pad)
        sec = tk.Frame(panel, bg='#f0f0ee'); sec.pack(fill='x', padx=8)
        self.sec_vars = {}
        fields = [('A', 'Area A (cm²)'), ('allow_tension', 'Allow. tension σ (kN/cm²)')]
        for i, (key, label) in enumerate(fields):
            tk.Label(sec, text=label, bg='#f0f0ee', font=('Helvetica', 9)).grid(row=i, column=0, sticky='w', pady=1)
            v = tk.DoubleVar(value=self.profile[key])
            self.sec_vars[key] = v
            tk.Entry(sec, textvariable=v, width=8, font=('Helvetica', 9)).grid(row=i, column=1, pady=1, padx=4)

        tk.Label(panel, text='RESULTS', bg='#f0f0ee', font=('Helvetica', 10, 'bold')).pack(anchor='w', **pad)
        self.res_text = tk.Text(panel, height=16, bg='white', font=('Courier', 9), relief='solid', bd=1)
        self.res_text.pack(fill='both', expand=True, padx=8, pady=(2, 10))

    # ── row management ──────────────────────────────────────────────────────
    def _del_row(self, tree, data_list):
        sel = tree.selection()
        if not sel:
            return
        idx = tree.index(sel[0])
        del data_list[idx]
        self._refresh_tables()

    def _refresh_tables(self):
        self.pl_tree.delete(*self.pl_tree.get_children())
        for r in self.point_loads:
            self.pl_tree.insert('', 'end', values=(r['x'], r['P']))
        self.dl_tree.delete(*self.dl_tree.get_children())
        for r in self.distributed_loads:
            self.dl_tree.insert('', 'end', values=(r['expr'], r['x1'], r['x2'], r['measure']))
        self._draw_schematic()

    def _ask(self, title, fields):
        win = tk.Toplevel(self); win.title(title); win.grab_set()
        win.configure(bg='#f0f0ee')
        vars_ = {}
        for i, (key, label, default) in enumerate(fields):
            tk.Label(win, text=label, bg='#f0f0ee').grid(row=i, column=0, sticky='w', padx=8, pady=4)
            v = tk.DoubleVar(value=default)
            vars_[key] = v
            tk.Entry(win, textvariable=v, width=10).grid(row=i, column=1, padx=8, pady=4)
        result = {}

        def ok():
            for k, v in vars_.items():
                result[k] = v.get()
            win.destroy()
        tk.Button(win, text='OK', command=ok, bg='#1a6bbd', fg='white').grid(
            row=len(fields), column=0, columnspan=2, pady=8)
        win.wait_window()
        return result if result else None

    def _add_pointload(self):
        r = self._ask('Add exact point load', [
            ('x', 'x (m)', self.span_var.get() / 2),
            ('P', 'P (kN, +down)', 10.0),
        ])
        if r:
            if not (0.0 < r['x'] < self.span_var.get()):
                messagebox.showerror('Invalid point load',
                                     'The exact point load must lie strictly between the supports.')
                return
            self.point_loads.append(r)
            self._refresh_tables()

    def _add_distributed_load(self):
        win = tk.Toplevel(self); win.title('Add distributed load'); win.grab_set()
        win.configure(bg='#f0f0ee')
        tk.Label(win, text='q(x) in kN/m  (vars: x, xc, L, s; xc=x-L/2; ^ or ** = power):', bg='#f0f0ee',
                 font=('Helvetica', 9)).grid(row=0, column=0, columnspan=2, sticky='w', padx=8, pady=(8, 2))
        expr_var = tk.StringVar(value='1.0')
        tk.Entry(win, textvariable=expr_var, width=28, font=('Helvetica', 9)).grid(
            row=1, column=0, columnspan=2, sticky='we', padx=8, pady=2)

        tk.Label(win, text='x₁ (m):', bg='#f0f0ee', font=('Helvetica', 9)).grid(
            row=2, column=0, sticky='w', padx=8, pady=4)
        x1_var = tk.DoubleVar(value=0.0)
        tk.Entry(win, textvariable=x1_var, width=10).grid(row=2, column=1, padx=8, pady=4)

        tk.Label(win, text='x₂ (m):', bg='#f0f0ee', font=('Helvetica', 9)).grid(
            row=3, column=0, sticky='w', padx=8, pady=4)
        x2_var = tk.DoubleVar(value=self.span_var.get())
        tk.Entry(win, textvariable=x2_var, width=10).grid(row=3, column=1, padx=8, pady=4)

        tk.Label(win, text='Measured per unit:', bg='#f0f0ee', font=('Helvetica', 9)).grid(
            row=4, column=0, sticky='w', padx=8, pady=4)
        measure_var = tk.StringVar(value='horizontal')
        cb = ttk.Combobox(win, textvariable=measure_var,
                           values=['horizontal', 'arc'], width=10, state='readonly')
        cb.grid(row=4, column=1, padx=8, pady=4)
        tk.Label(win, text='"horizontal" = per metre of span (e.g. deck load)\n'
                           '"arc" = per metre of cable (e.g. self-weight)',
                 bg='#f0f0ee', font=('Helvetica', 8), fg='#777', justify='left').grid(
            row=5, column=0, columnspan=2, sticky='w', padx=8)

        result = {}

        def ok():
            expr = expr_var.get().strip()
            try:
                ctx = {'L': self.span_var.get(), 's': self.length_var.get()}
                x1_, x2_ = x1_var.get(), x2_var.get()
                x_mid = (min(x1_, x2_) + max(x1_, x2_)) / 2
                make_shape_fn(expr, ctx)(x_mid)   # validate it compiles & evaluates
            except Exception as e:
                messagebox.showerror('Invalid expression', str(e)); return
            result['expr'] = expr
            result['x1'] = x1_var.get()
            result['x2'] = x2_var.get()
            result['measure'] = measure_var.get()
            win.destroy()

        tk.Button(win, text='OK', command=ok, bg='#1a6bbd', fg='white').grid(
            row=6, column=0, columnspan=2, pady=8)
        win.wait_window()
        if result:
            self.distributed_loads.append(result)
            self._refresh_tables()

    def _set_geometry(self):
        span = self.span_var.get()
        length = self.length_var.get()
        if length <= span:
            messagebox.showerror('Invalid geometry',
                                  'Cable length s must exceed the span L (s > L).')
            return
        self.span = span
        self.length = length
        self.y_left = self.yleft_var.get()
        self.y_right = self.yright_var.get()
        # clear any previous analysis -- it belongs to the OLD geometry, and
        # _draw_schematic() prefers self.result when present, so leaving it
        # set here would silently keep showing the stale shape
        self.result = None
        self.model = None
        self.res_text.delete('1.0', 'end')
        self.diag_canvas.delete('all')
        self._probe_point = None
        if hasattr(self, 'probe_result_label'):
            self.probe_result_label.config(text='')
        self._update_reference_catenary()
        self._draw_schematic()

    def _clear_all(self):
        self.point_loads = []
        self.distributed_loads = []
        self.result = None; self.model = None
        self._probe_point = None
        if hasattr(self, 'probe_result_label'):
            self.probe_result_label.config(text='')
        self._refresh_tables()
        self.res_text.delete('1.0', 'end')
        self.diag_canvas.delete('all')

    # ── Excel export / import ────────────────────────────────────────────────
    def _current_state(self):
        return {
            'span': self.span_var.get(), 'length': self.length_var.get(),
            'n_elem': int(self.nelem_var.get()),
            'y_left': self.yleft_var.get(), 'y_right': self.yright_var.get(),
            'point_loads': self.point_loads, 'distributed_loads': self.distributed_loads,
            'profile': {k: v.get() for k, v in self.sec_vars.items()},
        }

    def _export_excel(self):
        if not _ensure_openpyxl():
            messagebox.showerror(
                'Missing library',
                'Could not install openpyxl automatically.\n\n'
                'Please open a terminal and run:\n'
                '    pip install openpyxl\n'
                'then try again.')
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.xlsx',
            filetypes=[('Excel workbook', '*.xlsx')],
            initialfile='cable_report.xlsx',
            title='Save Excel report')
        if not path:
            return
        try:
            export_cable_excel(self._current_state(), path,
                                result=self.result, model=self.model)
            messagebox.showinfo(
                'Exported', f'Report saved to:\n{path}\n\n'
                'Includes a "Model" sheet — use "Import" to rebuild this '
                'exact cable from the file later.' +
                ('' if self.result else '\n\n(Run ▶ Analyze first to also '
                                         'include a "Results" sheet next time.)'))
        except Exception as e:
            messagebox.showerror('Export failed', str(e))

    def _import_excel(self):
        if not _ensure_openpyxl():
            messagebox.showerror(
                'Missing library',
                'Could not install openpyxl automatically.\n\n'
                'Please open a terminal and run:\n'
                '    pip install openpyxl\n'
                'then try again.')
            return
        path = filedialog.askopenfilename(
            filetypes=[('Excel workbook', '*.xlsx')],
            title='Import cable from Excel')
        if not path:
            return
        try:
            st = import_cable_excel(path)
        except Exception as e:
            messagebox.showerror('Import failed', str(e)); return

        self._clear_all()
        self.span = st['span']; self.length = st['length']
        self.span_var.set(st['span']); self.length_var.set(st['length'])
        self.nelem_var.set(st['n_elem'])
        self.yleft_var.set(st['y_left']); self.yright_var.set(st['y_right'])
        self.point_loads = st['point_loads']
        self.distributed_loads = st['distributed_loads']
        for k, v in st['profile'].items():
            if k in self.sec_vars:
                self.sec_vars[k].set(v)
                self.profile[k] = v
        self._refresh_tables()
        self._update_reference_catenary()
        self._draw_schematic()

    # ── examples ─────────────────────────────────────────────────────────────
    def _load_example_parabola(self):
        self._clear_all()
        self.span = 20.0; self.length = 22.0
        self.span_var.set(20.0); self.length_var.set(22.0)
        self.yleft_var.set(0.0); self.yright_var.set(0.0)
        self.distributed_loads.append({'expr': '2.0', 'x1': 0.0, 'x2': 20.0, 'measure': 'horizontal'})
        self._refresh_tables()
        self._update_reference_catenary()

    def _load_example_catenary(self):
        self._clear_all()
        self.span = 20.0; self.length = 22.0
        self.span_var.set(20.0); self.length_var.set(22.0)
        self.yleft_var.set(0.0); self.yright_var.set(0.0)
        self.distributed_loads.append({'expr': '1.5', 'x1': 0.0, 'x2': 20.0, 'measure': 'arc'})
        self._refresh_tables()
        self._update_reference_catenary()

    def _load_example_point(self):
        self._clear_all()
        self.span = 20.0; self.length = 24.0
        self.span_var.set(20.0); self.length_var.set(24.0)
        self.yleft_var.set(0.0); self.yright_var.set(0.0)
        self.point_loads.append({'x': 10.0, 'P': 50.0})
        self._refresh_tables()
        self._update_reference_catenary()

    # ── analysis ─────────────────────────────────────────────────────────────
    def _analyze(self):
        try:
            self.span = self.span_var.get()
            self.length = self.length_var.get()
            self.n_elem = max(6, int(self.nelem_var.get()))
            self.y_left = self.yleft_var.get()
            self.y_right = self.yright_var.get()

            if self.length <= self.span:
                messagebox.showerror('Invalid geometry',
                                      'Cable length s must exceed the span L (s > L).')
                return

            m = CableModel(self.span, self.length, n_elem=self.n_elem,
                            y_left=self.y_left, y_right=self.y_right)

            ctx = {'L': self.span, 's': self.length}
            for p in self.distributed_loads:
                qfn = make_shape_fn(p['expr'], ctx)
                x1 = max(0.0, min(self.span, p['x1']))
                x2 = max(0.0, min(self.span, p['x2']))
                if x2 < x1:
                    x1, x2 = x2, x1

                def scaled_fn(x, _qfn=qfn):
                    return _qfn(x) * 1e3   # kN/m -> N/m

                m.add_distributed_load(scaled_fn, x1, x2, measure=p['measure'])

            for p in self.point_loads:
                m.add_point_load(p['x'], p['P'] * 1e3)  # kN -> N; exact nodal force

            for k in self.sec_vars:
                self.profile[k] = self.sec_vars[k].get()

            self.result = m.solve()
            self.model = m
            self._update_reference_catenary()
            self._draw_diagram()
            self._show_results()
            if self.probe_enabled_var.get():
                self._update_probe()
            self._draw_schematic()
            if not self.result.converged:
                messagebox.showwarning(
                    'Convergence warning',
                    'The equilibrium residual is larger than expected for this '
                    'configuration — results may be inaccurate. Try increasing '
                    'the element count (n), or checking that the point load lies inside the span, '
                    'or checking that s is sufficiently larger than L.')
        except Exception as e:
            messagebox.showerror('Analysis failed', str(e))

    def _show_results(self):
        r = self.result; m = self.model
        V_left, V_right = r.reactions()
        T = r.tension()
        x_sag, sag = r.max_sag()
        Tmax = max(T)

        A_cm2 = self.profile['A']
        allow_t = self.profile['allow_tension']
        sigma_kncm2 = (Tmax / 1e3) / A_cm2 if A_cm2 else 0.0
        ratio = sigma_kncm2 / allow_t if allow_t else 0.0

        lines = ['REACTIONS (vertical, +up)']
        lines.append(f"  Left  (x=0)        : Ry = {V_left/1e3:+8.2f} kN")
        lines.append(f"  Right (x={m.span:.2f}) : Ry = {V_right/1e3:+8.2f} kN")
        lines += ['', f'Horizontal thrust H     = {r.H/1e3:8.2f} kN',
                  f'Max tension             T = {Tmax/1e3:8.2f} kN',
                  f'Max sag                   = {sag:8.3f} m  at x = {x_sag:.2f} m', '',
                  'STRESS CHECK']
        lines.append(f'  sigma = T_max/A = {sigma_kncm2:7.3f} kN/cm²   allow = {allow_t:.3f} '
                      f'({"OK" if ratio <= 1.0 else "FAIL"}, ratio {ratio:.2f})')
        if not r.converged:
            lines += ['', '*** WARNING: solver did not fully converge ***',
                      'Results below may be inaccurate.']

        if getattr(self, 'inverted_arch_var', None) is not None and self.inverted_arch_var.get():
            lines += ['', 'INVERTED ARCH (compression) — anti-funicular of this cable',
                      '  Mirroring this shape about the chord gives an arch that carries',
                      '  the SAME load in pure compression, with zero bending moment:',
                      f'    thrust  H = {r.H/1e3:8.2f} kN  (same magnitude, now pushing outward)',
                      f'    max |N| = {Tmax/1e3:8.2f} kN  (compression, N(x) = T(x) of the cable)']

        self.res_text.delete('1.0', 'end')
        self.res_text.insert('1.0', '\n'.join(lines))

    # ── drawing ──────────────────────────────────────────────────────────────
    def _draw_schematic(self):
        c = self.schem
        c.delete('all')
        w = c.winfo_width() or 400
        h = c.winfo_height() or 400
        L = max(self.span_var.get() if hasattr(self, 'span_var') else self.span, 1e-6)

        if self.result is not None:
            xs_s, ys_s = self.result.x, self.result.y
        else:
            # un-analyzed preview: shallow parabola-ish sag for visual reference
            yl = self.yleft_var.get() if hasattr(self, 'yleft_var') else self.y_left
            yr = self.yright_var.get() if hasattr(self, 'yright_var') else self.y_right
            s_ = self.length_var.get() if hasattr(self, 'length_var') else self.length
            sag0 = max(math.sqrt(max(3.0 * L * (s_ - L) / 8.0, 0.0)), 0.02 * L) if s_ > L else 0.05 * L
            n_s = 60
            xs_s = [L * i / n_s for i in range(n_s + 1)]
            ys_s = [yl + (yr - yl) * (x / L) - 4 * sag0 * (x / L) * (1 - x / L) for x in xs_s]

        # ghost reference catenary: only usable if it still matches the
        # current span (it's recomputed on geometry changes, but skip rather
        # than misdraw if something went stale)
        ref = self._ref_catenary
        show_ref = (getattr(self, 'ref_catenary_var', None) is not None
                    and self.ref_catenary_var.get() and ref is not None
                    and abs(ref[0][-1] - L) < 1e-6)

        show_inv = (self.result is not None and getattr(self, 'inverted_arch_var', None) is not None
                    and self.inverted_arch_var.get())
        inv_x, inv_y = self.result.inverted_shape() if show_inv else (None, None)

        all_y = list(ys_s) + [0.0]
        if show_ref:
            all_y += list(ref[1])
        if show_inv:
            all_y += list(inv_y)

        minx, maxx = 0.0, L
        miny, maxy = min(all_y), max(all_y)
        span_x = max(maxx - minx, 1e-6)
        span_y = max(maxy - miny, 1e-6)

        pad_side, pad_top, pad_bottom = 30, 26, 40
        avail_w = max(w - 2 * pad_side, 10)
        avail_h = max(h - pad_top - pad_bottom, 10)
        scale = min(avail_w / span_x, avail_h / span_y)

        offx = pad_side + (avail_w - span_x * scale) / 2 - minx * scale
        offy_top = pad_top + (avail_h - span_y * scale) / 2

        def X(x): return offx + x * scale
        def Y(y): return offy_top + (maxy - y) * scale

        # ── ghost layer 1: unloaded (self-weight-only) reference catenary of
        # the same span/length/support heights -- drawn first so it always
        # sits BEHIND the actual loaded shape, for a direct "how far did the
        # load pull this cable away from its natural hang" comparison.
        if show_ref:
            pts_ref = [(X(xv), Y(yv)) for xv, yv in zip(ref[0], ref[1])]
            flat_ref = [v for p in pts_ref for v in p]
            if len(pts_ref) > 1:
                c.create_line(*flat_ref, fill=self.CREF, width=2, dash=(4, 3), smooth=True)

        # ── ghost layer 2: the same shape inverted about the chord -- the
        # funicular/anti-funicular arch that would carry this exact load in
        # pure compression with zero bending moment.
        if show_inv:
            pts_inv = [(X(xv), Y(yv)) for xv, yv in zip(inv_x, inv_y)]
            flat_inv = [v for p in pts_inv for v in p]
            if len(pts_inv) > 1:
                c.create_line(*flat_inv, fill=self.CARCHINV, width=2, dash=(6, 2), smooth=True)

        pts = [(X(x), Y(y)) for x, y in zip(xs_s, ys_s)]
        flat = [v for p in pts for v in p]
        if len(pts) > 1:
            c.create_line(*flat, fill=self.CCABLE, width=3, smooth=True)

        for x0, y0 in [(xs_s[0], ys_s[0]), (xs_s[-1], ys_s[-1])]:
            sx, sy = X(x0), Y(y0)
            c.create_polygon(sx - 10, sy + 18, sx + 10, sy + 18, sx, sy,
                              fill='', outline=self.CSUP, width=2)

        for p in self.point_loads:
            xi = p['x']
            yi = None
            if self.result is not None:
                best_d = None
                for xv, yv in zip(xs_s, ys_s):
                    d = abs(xv - xi)
                    if best_d is None or d < best_d:
                        best_d, yi = d, yv
            else:
                yi = ys_s[min(range(len(xs_s)), key=lambda k: abs(xs_s[k] - xi))]
            sx, sy = X(xi), Y(yi)
            c.create_line(sx, sy - 22, sx, sy, fill=self.CLOAD, width=2, arrow='last', arrowshape=(8, 10, 3))
            c.create_text(sx, sy - 30, text=f"P={p['P']:g}", fill=self.CLOAD, font=('Helvetica', 8))

        c.create_text(X(0), h - 14, text='0', font=('Helvetica', 8), fill='#555')
        c.create_text(X(L), h - 14, text=f'{L:.1f} m', font=('Helvetica', 8), fill='#555')

        legend_y = 14
        if show_ref:
            c.create_line(w - 150, legend_y, w - 130, legend_y, fill=self.CREF, width=2, dash=(4, 3))
            c.create_text(w - 125, legend_y, text='unloaded catenary', anchor='w',
                          font=('Helvetica', 7), fill='#999')
            legend_y += 13
        if show_inv:
            c.create_line(w - 150, legend_y, w - 130, legend_y, fill=self.CARCHINV, width=2, dash=(6, 2))
            c.create_text(w - 125, legend_y, text='inverted (compression)', anchor='w',
                          font=('Helvetica', 7), fill='#b5651d')

        if self.probe_enabled_var.get() and self._probe_point is not None:
            px, py = self._probe_point
            sx, sy = X(px), Y(py)
            c.create_line(sx, pad_top, sx, sy, fill='#1a6bbd', dash=(3, 2))
            c.create_oval(sx - 6, sy - 6, sx + 6, sy + 6, fill='#1a6bbd', outline='white', width=1.5)

        if self.thrust_enabled_var.get() and self.result is not None:
            self._draw_thrust_vectors(c, X, Y, L)

    def _draw_thrust_vectors(self, c, X, Y, L):
        """Overlays the internal tension vector -- decomposed into its
        global horizontal and vertical components, plus the resultant -- at
        evenly spaced stations along the cable. Vector lengths share one
        common force->length scale (set by the single largest resultant
        among the displayed stations), so relative magnitudes stay
        comparable at a glance."""
        r = self.result
        x, y = r.x, r.y
        Fx, Fy = r.force_components()
        n_vec = max(3, self.thrust_count_var.get())
        n_nodes = len(x)

        stations = []
        for k in range(n_vec):
            frac = (k + 0.5) / n_vec
            idx = min(int(round(frac * (n_nodes - 1))), n_nodes - 1)
            stations.append((x[idx], y[idx], Fx[idx], Fy[idx]))

        max_R = max((math.hypot(fx, fy) for _, _, fx, fy in stations), default=0.0)
        if max_R < 1e-9:
            return
        force_scale = (0.22 * L) / max_R

        for x0, y0, Fxv, Fyv in stations:
            fx_m, fy_m = Fxv * force_scale, Fyv * force_scale
            ox, oy = X(x0), Y(y0)

            hx, hy = X(x0 + fx_m), Y(y0)
            if abs(fx_m) > 1e-6:
                c.create_line(ox, oy, hx, hy, fill=self.CTHH, width=2,
                              arrow='last', arrowshape=(8, 10, 3))
            vx, vy = X(x0), Y(y0 + fy_m)
            if abs(fy_m) > 1e-6:
                c.create_line(ox, oy, vx, vy, fill=self.CTHV, width=2,
                              arrow='last', arrowshape=(8, 10, 3))
            rx, ry = X(x0 + fx_m), Y(y0 + fy_m)
            c.create_line(ox, oy, rx, ry, fill=self.CTHR, width=2,
                          arrow='last', arrowshape=(9, 11, 4))
            c.create_oval(ox - 3, oy - 3, ox + 3, oy + 3, fill='#333', outline='')

    # ── force probe ──────────────────────────────────────────────────────────
    def _on_probe_toggle(self):
        if not self.probe_enabled_var.get():
            self.probe_result_label.config(text='')
            self._probe_point = None
            self._draw_schematic()
        else:
            self._update_probe()

    def _on_inverted_toggle(self):
        self._draw_schematic()
        if self.result is not None:
            self._show_results()

    def _update_probe(self):
        if not self.probe_enabled_var.get():
            return
        if not self.result or not self.model:
            self.probe_result_label.config(text='Run ▶ Analyze first.')
            return
        sigma = self.model.sigma
        s_max = sigma[-1]
        s_target = max(0.0, min(s_max, self.probe_s_var.get()))
        best_i, best_d = 0, None
        for i, sv in enumerate(sigma):
            d = abs(sv - s_target)
            if best_d is None or d < best_d:
                best_d, best_i = d, i

        x, y = self.result.x, self.result.y
        T = self.result.tension()
        Fx, Fy = self.result.force_components()
        R = math.hypot(Fx[best_i], Fy[best_i])

        self._probe_point = (x[best_i], y[best_i])
        self.probe_result_label.config(text=(
            f"s = {sigma[best_i]:.2f} m  (x={x[best_i]:.2f}, y={y[best_i]:.2f})\n"
            f"Fx = {Fx[best_i]/1e3:+8.2f} kN\n"
            f"Fy = {Fy[best_i]/1e3:+8.2f} kN\n"
            f"T  = {T[best_i]/1e3:8.2f} kN"))
        self._draw_schematic()

    # ── reference (unloaded) catenary ───────────────────────────────────────
    def _update_reference_catenary(self):
        """Recomputes the plain catenary that this cable's span/length/
        support heights would settle into hanging under nothing but its own
        weight (no external point/distributed loads) -- a fixed reference
        shape for the given (L, s, y_left, y_right) alone. Its geometry does
        not depend on the actual self-weight magnitude used (any positive
        value gives the same shape, only H scales), so an arbitrary uniform
        intensity is used purely as a solver input."""
        try:
            span = self.span_var.get() if hasattr(self, 'span_var') else self.span
            length = self.length_var.get() if hasattr(self, 'length_var') else self.length
            yl = self.yleft_var.get() if hasattr(self, 'yleft_var') else self.y_left
            yr = self.yright_var.get() if hasattr(self, 'yright_var') else self.y_right
            if length <= span:
                self._ref_catenary = None
                return
            ref_m = CableModel(span, length, n_elem=40, y_left=yl, y_right=yr)
            ref_m.add_distributed_load(lambda x: 1.0, 0.0, span, measure='arc')
            ref_r = ref_m.solve()
            self._ref_catenary = (ref_r.x, ref_r.y) if ref_r.converged else None
        except Exception:
            self._ref_catenary = None

    def _draw_diagram(self):
        c = self.diag_canvas
        c.delete('all')
        w = c.winfo_width() or 400
        h = c.winfo_height() or 200
        if self.result is None:
            return
        x = self.result.x
        xT, T_raw, xF, Fx_raw, Fy_raw = self.result.diagram_series()
        T = [v / 1e3 for v in T_raw]  # kN
        Fx = [v / 1e3 for v in Fx_raw]
        Fy = [v / 1e3 for v in Fy_raw]
        V_left, V_right = self.result.reactions()
        H = self.result.H

        band_h = h / 2
        pad_l, pad_r, pad_t, pad_b = 45, 20, 22, 26
        L = max(x[-1] - x[0], 1e-9)

        def draw_band(ys_list, box, y_label, curve_specs, title):
            top, bot = box
            left, right = pad_l, w - pad_r
            plot_top, plot_bot = top + pad_t, bot - pad_b
            allvals = [v for ys in ys_list for v in ys]
            vmax = max(allvals) if allvals else 1.0
            vmin = min(min(allvals), 0.0) if allvals else 0.0
            span_v = max(vmax - vmin, 1e-9)

            def X(xv): return left + (xv - x[0]) / L * (right - left)
            def Yv(vv): return plot_bot - (vv - vmin) / span_v * (plot_bot - plot_top)

            v_ticks = _nice_ticks(vmin, vmax, 6)
            for vt in v_ticks:
                yy = Yv(vt)
                if plot_top - 1 <= yy <= plot_bot + 1:
                    c.create_line(left, yy, right, yy, fill='#eee')
                    c.create_text(left - 6, yy, text=f'{vt:g}', anchor='e', font=('Helvetica', 7), fill='#999')
            x_ticks = _nice_ticks(x[0], x[-1], 8)
            for xt in x_ticks:
                xx = X(xt)
                if left - 1 <= xx <= right + 1:
                    c.create_line(xx, plot_top, xx, plot_bot, fill='#eee')
                    c.create_text(xx, plot_bot + 9, text=f'{xt:g}', anchor='n', font=('Helvetica', 7), fill='#888')

            c.create_text(left, top + 8, text=title, anchor='w', font=('Helvetica', 8, 'bold'), fill='#555')
            c.create_line(left, plot_bot, right, plot_bot, fill='#999')
            c.create_line(left, plot_top, left, plot_bot, fill='#999')
            c.create_text((left + right) / 2, bot - 8, text='x (m)', font=('Helvetica', 8), fill='#555')
            c.create_text(left - 32, (plot_top + plot_bot) / 2, text=y_label, font=('Helvetica', 8),
                          fill='#555', angle=90)

            for ci, (xs_c, ys, color, name) in enumerate(curve_specs):
                pts = []
                for xv, vv in zip(xs_c, ys):
                    pts += [X(xv), Yv(vv)]
                if len(pts) >= 4:
                    c.create_line(*pts, fill=color, width=2)
                vabsmax = max((abs(v) for v in ys), default=0.0)
                c.create_text(right - 8, plot_top + 2 + 11 * ci,
                              text=f"max {name}={vabsmax:.2f}", anchor='e', font=('Helvetica', 8), fill=color)
                locs, _ = _find_diagram_maxima(xs_c, ys)
                for xv in locs:
                    idx = min(range(len(xs_c)), key=lambda i: abs(xs_c[i] - xv))
                    sx, sy = X(xs_c[idx]), Yv(ys[idx])
                    c.create_oval(sx - 4, sy - 4, sx + 4, sy + 4, fill=color, outline='white', width=1)
                    c.create_text(sx, sy - 11 if ys[idx] >= 0 else sy + 11,
                                  text=f"x={xv:.2f}", font=('Helvetica', 7), fill=color)
            return X, Yv, plot_top, plot_bot

        draw_band([T], (0, band_h), 'T (kN)', [(xT, T, self.CTENS, 'T')], 'TENSION  T(x)')
        Xt, Yt, ptop, pbot = draw_band(
            [Fx, Fy], (band_h, h), 'F (kN)',
            [(xF, Fx, self.CTHH, 'Fx'), (xF, Fy, self.CTHV, 'Fy')],
            'THRUST  Fx / Fy  (kN, global components)')

        # ── reaction call-outs, clearly labelled, at both supports ──
        left, right = pad_l, w - pad_r
        Ry_l, Ry_r = V_left / 1e3, V_right / 1e3
        H_kn = H / 1e3
        y0 = pbot + 2
        c.create_line(left - 14, y0, left + 2, y0, fill='#c0392b', width=2, arrow='first', arrowshape=(7, 9, 3))
        c.create_text(left + 6, y0, text=f"◄ R_left: H={H_kn:.2f} kN, V={Ry_l:.2f} kN ▲",
                      anchor='w', font=('Helvetica', 8, 'bold'), fill='#c0392b')
        c.create_text(right - 6, y0, text=f"► R_right: H={H_kn:.2f} kN, V={Ry_r:.2f} kN ▲",
                      anchor='e', font=('Helvetica', 8, 'bold'), fill='#c0392b')
        c.create_line(0, band_h, w, band_h, fill='#ccc')  # divider between bands
