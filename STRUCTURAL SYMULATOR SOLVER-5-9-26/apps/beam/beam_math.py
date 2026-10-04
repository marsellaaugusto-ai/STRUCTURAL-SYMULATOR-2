"""beam_math.py — the Beam tab's solver, with no user interface in it.

The deterministic half of the Beam tab: a cubic-Hermite (Hermitian) FEM beam
model, exact-statics V/M recovery, deflection integration by the same
moment-area pass the point queries use, the equilibrium self-check, and the
adaptive quadrature all of that needs.

THE BOUNDARY. This is the same split the Truss and Perforated Beam tabs are
built on -- stateful Tkinter interaction on one side, deterministic
calculation on the other -- and MODULAR_ARCHITECTURE.md calls it the intended
C++ migration boundary. Beam was the last structural tab still fused: before
2026-10-04 `BeamModel` sat in the same file as `import tkinter as tk`, so
`tests/test_beam_math.py` could not even be COLLECTED on a Python built
without Tk, to test code with no UI in it (R-8).

So nothing here may import tkinter, `common` (which imports tkinter at module
scope) or `units`. The numeric helpers come from the root-level `numerics`
module, which exists for this reason; `tests/test_beam_math.py` pins the
boundary by importing this module in a subprocess with tkinter blocked, so it
cannot quietly drift back the way `truss_math.py` has.

UNITS. SI throughout, always: metres, newtons, N*m, N/m, N*m^2 for EI. The
tab converts at its own edge -- see `units.py`, and note that the Perforated
Beam tab's engine deliberately works in mm/N/MPa instead.
"""
import math

from numerics import _beam_gauss_solve, _GAUSS5_NODES, _GAUSS5_WEIGHTS


class BeamModel:
    def __init__(self, length):
        self.L = self._valid_length(length)
        self.supports = []     # [{'x':, 'type':}]
        self.point_loads = []  # [{'x':, 'P':}]   +P = downward (N)
        self.moments = []      # [{'x':, 'M':}]   +M = CCW (N*m)
        self.dloads = []       # [{'x1':,'x2':,'w1':,'w2':}]  +w = downward (N/m)
        self.nonuniform_loads = []  # [{'fn': q(x)->N/m (+down), 'x1':, 'x2':}]
        self.EI = None         # N*m^2
        # Supports that add_support() folded into an earlier one at the same
        # station, so the tab can say so: [{'x':, 'kept':, 'added':, 'result':}]
        self.support_merges = []

    @staticmethod
    def _valid_length(length):
        """A usable beam length, or a ValueError that names the real problem.

        A zero-length beam used to come back as "Beam is fully constrained;
        nothing to solve" -- it is neither over-constrained nor a mechanism,
        and a user reading that message has no way to find the empty length
        box that caused it (2026-10-04, R-5).
        """
        try:
            length = float(length)
        except (TypeError, ValueError):
            raise ValueError(
                f'Beam length must be a number; got {length!r}.') from None
        if not math.isfinite(length) or length <= 0.0:
            raise ValueError(
                f'Beam length must be greater than zero; got {length:g} m. '
                f'Set the beam length first.')
        return length

    @staticmethod
    def _valid_EI(EI):
        """A usable bending stiffness, or a ValueError that names it.

        E = 0 used to surface as "Singular stiffness matrix -- beam is a
        mechanism", which sends the user looking at their supports instead of
        at their section. A NEGATIVE EI was worse: it SOLVED, and returned
        every deflection with the sign flipped, silently (R-5).
        """
        if EI is None:
            raise ValueError("EI must be set before solving")
        try:
            EI = float(EI)
        except (TypeError, ValueError):
            raise ValueError(f'EI must be a number; got {EI!r}.') from None
        if not math.isfinite(EI) or EI <= 0.0:
            raise ValueError(
                f'EI must be a positive, finite number; got {EI:g} N*m^2. '
                f'Check the section: E and I must both be greater than zero.')
        return EI

    def _on_beam(self, x, what):
        """Reject a station that is not on the beam.

        Nothing used to check these against the beam's own length, so a support
        or load at x = 99 on a 6 m beam was accepted and silently EXTENDED the
        mesh to 99 m while self.L stayed 6.0 -- the analysed structure was not
        the one the user described, and a 10 kN load came back as a 155 kN
        reaction with no warning (2026-09-05 finding B-5).
        """
        tol = 1e-9 * max(1.0, abs(self.L))
        if not (-tol <= x <= self.L + tol):
            raise ValueError(
                f"{what} at x = {x:g} m is not on the beam, which spans 0 to "
                f"{self.L:g} m. Move it onto the beam, or set the beam length "
                f"first.")
        return min(max(x, 0.0), self.L)

    # Which DOF each support type restrains: 'v' = vertical translation,
    # 'theta' = rotation. Written once, so the constraint assembly in solve(),
    # the merge below, and the restrained-DOF count behind the indeterminacy
    # report can never drift out of step with each other.
    SUPPORT_DOF = {
        'pin':    ('v',),
        'roller': ('v',),
        'fixed':  ('v', 'theta'),
        'guided': ('theta',),
    }

    @classmethod
    def _merged_type(cls, kept, added):
        """The support type that restrains the union of two types' DOF."""
        dof = set(cls.SUPPORT_DOF[kept]) | set(cls.SUPPORT_DOF[added])
        if dof == {'v', 'theta'}:
            return 'fixed'
        if dof == {'theta'}:
            return 'guided'
        # Vertical only. 'pin' and 'roller' restrain the same DOF in a
        # bending-only model, so there is nothing to choose between them --
        # keep the name the user entered first.
        return kept

    def add_support(self, x, type_):
        """Add a support, folding it into any support already at that station.

        Two supports at one station share a NODE, and until 2026-10-04 both of
        them reported that one node's reaction: `reaction_at()` is keyed by
        station, and `_V_M_at` added what it returned once per support. A pin
        and a roller both at x = 0 on a 6 m beam under 10 kN/m reported 90 kN
        of reaction for 60 kN of load, max |M| = 180 against a true 45, and
        failed the stress check on a beam that passes. It was silent because
        the constraint assembly was always right -- `constrained[dof] = 0.0`
        twice is idempotent -- so the displacements were right and only the
        recovery was wrong, which is why no closed form in
        tests/test_beam_math.py caught it.

        Merging rather than refusing is deliberate: a pin plus a guided
        support at one station IS a fixed support, and that is what the user
        was describing. But it is recorded in `support_merges` and reported in
        the RESULTS panel, because analysing something other than what was
        typed without saying so is the whole of this bug.
        """
        if type_ not in self.SUPPORT_DOF:
            raise ValueError(f"Unknown support type {type_}")
        x = self._on_beam(x, 'Support')
        key = round(x, 9)
        for s in self.supports:
            if round(s['x'], 9) != key:
                continue
            merged = self._merged_type(s['type'], type_)
            self.support_merges.append({'x': s['x'], 'kept': s['type'],
                                        'added': type_, 'result': merged})
            s['type'] = merged
            return s
        s = {'x': x, 'type': type_}
        self.supports.append(s)
        return s

    def add_point_load(self, x, P):
        self.point_loads.append({'x': self._on_beam(x, 'Point load'), 'P': P})

    def add_moment(self, x, M):
        self.moments.append({'x': self._on_beam(x, 'Applied moment'), 'M': M})

    def add_dload(self, x1, x2, w1, w2):
        # Normalise a right-to-left entry. q() tests `x1 <= x <= x2`, which is
        # unsatisfiable when x1 > x2, so a reversed segment used to contribute
        # NOTHING at all -- zero reactions, zero moment, no warning (finding
        # B-4). The intensities travel with their own ends, or the ramp would
        # come out flipped. The Perforated Beam tab normalises the same way.
        x1 = self._on_beam(x1, 'Distributed load start')
        x2 = self._on_beam(x2, 'Distributed load end')
        if x2 < x1:
            x1, x2, w1, w2 = x2, x1, w2, w1
        self.dloads.append({'x1': x1, 'x2': x2, 'w1': w1, 'w2': w2})

    def add_nonuniform_load(self, fn, x1, x2):
        x1 = self._on_beam(x1, 'Non-uniform load start')
        x2 = self._on_beam(x2, 'Non-uniform load end')
        if x2 < x1:
            x1, x2 = x2, x1
        self.nonuniform_loads.append({'fn': fn, 'x1': x1, 'x2': x2})

    # Longest element allowed, as a fraction of the modelled span. A mesh made
    # only of the load/support discontinuities can be too coarse to solve at
    # all: a fixed-fixed beam under a full-span UDL has exactly two nodes, all
    # four of its DOF are restrained, and solve() rejected it as "fully
    # constrained" even though it is the most common indeterminate case in any
    # textbook (2026-09-05 diagnosis, finding B-1). Guaranteeing a minimum mesh
    # removes that whole class of failure.
    #
    # This changes no result. Cubic-Hermite elements with consistent load
    # vectors are nodally exact for the load types this model supports, so the
    # extra nodes only make the deflection integration marginally finer -- and
    # the cost is bounded: subdividing every gap to at most span/4 adds at most
    # four elements in total, whatever the load layout.
    MAX_ELEM_FRACTION = 0.25

    def _node_positions(self):
        xs = {0.0, round(self.L, 9)}
        for s in self.supports: xs.add(round(s['x'], 9))
        for p in self.point_loads: xs.add(round(p['x'], 9))
        for m in self.moments: xs.add(round(m['x'], 9))
        for d in self.dloads:
            xs.add(round(d['x1'], 9)); xs.add(round(d['x2'], 9))
        for d in self.nonuniform_loads:
            xs.add(round(d['x1'], 9)); xs.add(round(d['x2'], 9))
        return self._refine(sorted(xs))

    def _refine(self, stations):
        """Split any gap longer than MAX_ELEM_FRACTION of the modelled span.

        The cap is taken from the span the stations actually cover, not from
        self.L, so a coordinate lying outside the beam cannot make the mesh
        explode -- the added element count stays bounded either way.
        """
        if len(stations) < 2:
            return stations
        max_len = (stations[-1] - stations[0]) * self.MAX_ELEM_FRACTION
        if max_len <= 0:
            return stations
        out = [stations[0]]
        for a, b in zip(stations, stations[1:]):
            seg = b - a
            n_sub = max(1, int(math.ceil(seg / max_len - 1e-9)))
            for k in range(1, n_sub):
                out.append(round(a + seg * k / n_sub, 9))
            out.append(b)
        # A rounded interior point can land on the station that follows it when
        # a gap is degenerate; keep the mesh strictly increasing.
        uniq = [out[0]]
        for v in out[1:]:
            if v > uniq[-1] + 1e-12:
                uniq.append(v)
        return uniq

    def q(self, x):
        """Total distributed load (N/m, +down convention) at x, summing the
        linear-ramp segments (self.dloads) and any non-uniform function-based
        segments (self.nonuniform_loads). NOTE: this is evaluated only at
        interior Gauss points during solve() (see the endpoint-avoiding
        quadrature below) — never call it exactly at a load segment's own
        x1/x2, since a user-supplied non-uniform load may be singular there
        by construction (e.g. 1/sqrt(...) at its own domain edge)."""
        total = 0.0
        for d in self.dloads:
            if d['x1'] - 1e-9 <= x <= d['x2'] + 1e-9:
                span = d['x2'] - d['x1']
                frac = (x - d['x1']) / span if span > 1e-12 else 0.0
                w = d['w1'] + (d['w2'] - d['w1']) * frac
                total += -w
        for d in self.nonuniform_loads:
            if d['x1'] - 1e-9 <= x <= d['x2'] + 1e-9:
                total += -d['fn'](x)
        return total

    def solve(self):
        # Re-checked here as well as in __init__: the tab rebuilds its model
        # on every Analyze, but a script can assign to m.L or m.EI directly.
        self.L = self._valid_length(self.L)
        EI = self.EI = self._valid_EI(self.EI)
        xs = self._node_positions()
        n_nodes = len(xs)
        idx_of = {x: i for i, x in enumerate(xs)}
        dof = 2 * n_nodes
        K = [[0.0] * dof for _ in range(dof)]
        F = [0.0] * dof

        elements = []
        for e in range(n_nodes - 1):
            x1, x2 = xs[e], xs[e + 1]
            Le = x2 - x1
            if Le < 1e-9:
                continue
            elements.append((e, e + 1, x1, x2, Le))

        for ei, (n1, n2, x1, x2, Le) in enumerate(elements):
            k = EI / Le ** 3
            L = Le
            ke = [
                [12 * k, 6 * L * k, -12 * k, 6 * L * k],
                [6 * L * k, 4 * L ** 2 * k, -6 * L * k, 2 * L ** 2 * k],
                [-12 * k, -6 * L * k, 12 * k, -6 * L * k],
                [6 * L * k, 2 * L ** 2 * k, -6 * L * k, 4 * L ** 2 * k],
            ]
            gidx = [2 * n1, 2 * n1 + 1, 2 * n2, 2 * n2 + 1]
            for i in range(4):
                for j in range(4):
                    K[gidx[i]][gidx[j]] += ke[i][j]

            has_load = any(
                not (d['x2'] <= x1 + 1e-9 or d['x1'] >= x2 - 1e-9) for d in self.dloads
            ) or any(
                not (d['x2'] <= x1 + 1e-9 or d['x1'] >= x2 - 1e-9) for d in self.nonuniform_loads
            )
            if has_load:
                def vfn(xx, x1=x1, L=L):
                    n = (xx - x1) / L
                    qq = self.q(xx)
                    return (qq * (1 - 3*n**2 + 2*n**3),
                            qq * L * (n - 2*n**2 + n**3),
                            qq * (3*n**2 - 2*n**3),
                            qq * L * (-n**2 + n**3))
                f_eq = _adaptive_vector_integral(vfn, x1, x2, dim=4)
                for i in range(4):
                    F[gidx[i]] += f_eq[i]

        for p in self.point_loads:
            i = idx_of[round(p['x'], 9)]
            F[2 * i] += -p['P']
        for m in self.moments:
            i = idx_of[round(m['x'], 9)]
            F[2 * i + 1] += m['M']

        # One pass over SUPPORT_DOF, so this cannot disagree with the merge
        # in add_support() or with the restrained-DOF count in
        # BeamResult.equilibrium(). Still raises on an unknown type: a model
        # can be built by hand or out of a workbook, bypassing add_support().
        constrained = {}
        for s in self.supports:
            i = idx_of[round(s['x'], 9)]
            try:
                restrains = self.SUPPORT_DOF[s['type']]
            except KeyError:
                raise ValueError(f"Unknown support type {s['type']}") from None
            if 'v' in restrains:
                constrained[2 * i] = 0.0
            if 'theta' in restrains:
                constrained[2 * i + 1] = 0.0

        free = [i for i in range(dof) if i not in constrained]
        if not free:
            raise ValueError("Beam is fully constrained; nothing to solve")

        Kff = [[K[i][j] for j in free] for i in free]
        Ff = [F[i] for i in free]
        d_free = _beam_gauss_solve(Kff, Ff)
        if d_free is None:
            raise ValueError(
                "Singular stiffness matrix — beam is a mechanism "
                "(unstable / insufficient supports).")

        d = [0.0] * dof
        for k_, i in enumerate(free):
            d[i] = d_free[k_]

        Kd = [sum(K[i][j] * d[j] for j in range(dof)) for i in range(dof)]
        R = [Kd[i] - F[i] for i in range(dof)]

        return BeamResult(self, xs, elements, d, R, idx_of, EI)

class BeamResult:
    def __init__(self, model, xs, elements, d, R, idx_of, EI):
        self.model = model
        self.xs = xs
        self.elements = elements
        self.d = d
        self.R = R
        self.idx_of = idx_of
        self.EI = EI
        # One entry per support NODE, in order, rather than one per support.
        # add_support() already merges duplicates, so model.supports is unique
        # by station -- this is the second line of defence, because
        # reaction_at() is keyed by station and anything that appended to that
        # list directly (a hand-built model, a future editor) would double
        # count every shared reaction again exactly as R-1 did.
        seen = set()
        self.support_stations = []
        for s in model.supports:
            key = round(s['x'], 9)
            if key not in seen:
                seen.add(key)
                self.support_stations.append(s['x'])

    def reaction_at(self, x):
        """Returns (Fy, M) at the support/node located at x.

        Fy is the vertical reaction, positive up. M is the COUPLE the support
        applies to the beam, positive counter-clockwise -- the same convention
        as an applied moment, since both enter the same rotational DOF of the
        same load vector. Crossing the station, the sagging-positive internal
        moment therefore jumps by exactly `-M`, which is the identity
        `support_reaction` reports and tests/test_beam_math.py pins at every
        station.

        Until 2026-10-04 the presentation layer negated this value AT x = 0
        ONLY -- a rule arrived at by trying a left-end, a right-end and a
        fixed-fixed beam and keeping what matched the M(x) diagram. What that
        produced was the internal moment at the support rather than the
        support's couple, and at an interior fixed support it was the internal
        moment on the LEFT side specifically, with nothing to say so (R-3).
        Use `support_reaction` for anything shown to a user.
        """
        i = self.idx_of[round(x, 9)]
        return self.R[2 * i], self.R[2 * i + 1]

    def support_reaction(self, x):
        """Everything there is to report about the support at station x.

            Fy       vertical reaction, + up
            M        the couple the support applies, + counter-clockwise
            M_left   internal moment just left of the station  (sagging +)
            M_right  internal moment just right of it          (sagging +)

        `M == M_left - M_right` at every station, which is what makes the
        couple well defined without a positional special case. The two
        internal moments are reported separately because at an interior
        support they genuinely differ, and a designer reading a fixed end
        wants the one on the beam side -- the hogging moment the section has
        to carry -- not the couple.
        """
        Fy, M = self.reaction_at(x)
        return {'Fy': Fy, 'M': M,
                'M_left': self.moment_at(x, side='left'),
                'M_right': self.moment_at(x, side='right')}

    def _V_M_at(self, x, side='right'):
        eps = 1e-7
        xx = x - eps if side == 'left' else x + eps
        # Clamped at the right end only. Just LEFT of the beam's left end is
        # outside the beam, where nothing is carried, and clamping xx up to 0
        # made a side='left' query at x = 0 return the value just AFTER the
        # support at that node instead of zero -- which is exactly what made
        # the reaction moment there look as though it needed negating (R-3).
        xx = min(self.model.L, xx)

        V = 0.0
        M = 0.0
        for sx in self.support_stations:
            if sx <= xx + 1e-9:
                Fy, Mr = self.reaction_at(sx)
                V += Fy
                M += Fy * (x - sx) - Mr
        for p in self.model.point_loads:
            if p['x'] <= xx + 1e-9:
                Fy = -p['P']
                V += Fy
                M += Fy * (x - p['x'])
        for mm in self.model.moments:
            if mm['x'] <= xx + 1e-9:
                M -= mm['M']

        for d in self.model.dloads:
            x1, x2 = d['x1'], d['x2']
            if xx <= x1 + 1e-9:
                continue
            xend = min(xx, x2)
            if xend - x1 < 1e-12:
                continue
            span = x2 - x1
            def qfn(s, d=d, span=span):
                frac = (s - d['x1']) / span if span > 1e-12 else 0.0
                w = d['w1'] + (d['w2'] - d['w1']) * frac
                return -w
            Vq, Mq = _gauss_VM_integral(qfn, x1, xend, x)
            V += Vq
            M += Mq

        for d in self.model.nonuniform_loads:
            x1, x2 = d['x1'], d['x2']
            if xx <= x1 + 1e-9:
                continue
            xend = min(xx, x2)
            if xend - x1 < 1e-12:
                continue
            def qfn(s, d=d):
                return -d['fn'](s)
            Vq, Mq = _gauss_VM_integral(qfn, x1, xend, x)
            V += Vq
            M += Mq

        return V, M

    def shear_at(self, x, side='right'):
        return self._V_M_at(x, side=side)[0]

    def moment_at(self, x, side='right'):
        return self._V_M_at(x, side=side)[1]

    def deflection(self, x):
        return self._theta_v_at(x)[1]

    def rotation(self, x):
        return self._theta_v_at(x)[0]

    def _theta_v_at(self, x_target):
        i0 = self.idx_of[round(0.0, 9)]
        v = self.d[2 * i0]
        th = self.d[2 * i0 + 1]
        EI = self.EI

        x_prev = 0.0
        for (n1, n2, x1, x2, Le) in self.elements:
            if x2 <= x_prev + 1e-12:
                continue
            seg_end = min(x2, x_target)
            if seg_end <= x_prev + 1e-12:
                break
            n_sub = 30
            h = (seg_end - x_prev) / n_sub
            xs_local = [x_prev + k * h for k in range(n_sub + 1)]
            Ms = [self.moment_at(xx, side='right') for xx in xs_local]
            thetas = [th]
            for k_ in range(n_sub):
                xm = (xs_local[k_] + xs_local[k_ + 1]) / 2
                Mm = self.moment_at(xm, side='right')
                seg_h = xs_local[k_ + 1] - xs_local[k_]
                dtheta = seg_h / 6 * (Ms[k_] + 4 * Mm + Ms[k_ + 1]) / EI
                thetas.append(thetas[-1] + dtheta)
            vs = [v]
            for k_ in range(n_sub):
                seg_h = xs_local[k_ + 1] - xs_local[k_]
                vs.append(vs[-1] + seg_h / 2 * (thetas[k_] + thetas[k_ + 1]))
            th = thetas[-1]
            v = vs[-1]
            x_prev = seg_end
            if seg_end >= x_target - 1e-12:
                break
        return th, v

    # Relative residual at or below which a model is reported as balanced.
    # The solver reaches ~1e-13 of the applied load on every model in
    # tests/test_beam_math.py; 1e-6 is far outside that and far inside any
    # real error, so this neither cries wolf nor passes a wrong answer.
    EQUILIBRIUM_TOL = 1e-6

    def _applied_resultants(self):
        """Everything applied to the beam, resolved about x = 0.

        Returns (Fy, M0, scale_F, scale_M) in the solver's own convention: Fy
        upward-positive -- so a downward load is negative -- and M0
        counter-clockwise-positive. The two scales are the sums of the
        individual contributions' MAGNITUDES, which is what makes a residual
        meaningful on a model whose loads cancel: an uplift of P and a load of
        P sum to zero, and dividing a residual by that zero would report any
        error at all as perfect balance.

        This is integrated from the load definitions and never touches the
        solved displacements, so it is a genuine second opinion on the answer
        rather than a restatement of it.
        """
        Fy = M0 = 0.0
        scale_F = scale_M = 0.0

        for p in self.model.point_loads:
            Fy += -p['P']
            M0 += -p['P'] * p['x']
            scale_F += abs(p['P'])
            scale_M += abs(p['P'] * p['x'])
        for mm in self.model.moments:
            M0 += mm['M']
            scale_M += abs(mm['M'])

        for d in self.model.dloads:
            span = d['x2'] - d['x1']
            if span < 1e-12:
                continue

            def qfn(sx, d=d, span=span):
                frac = (sx - d['x1']) / span
                return -(d['w1'] + (d['w2'] - d['w1']) * frac)

            q_int, mom = _gauss_VM_integral(qfn, d['x1'], d['x2'], 0.0)
            Fy += q_int
            M0 += -mom          # mom = integral of q*(0-s); the moment of q
            scale_F += abs(q_int)   # about the origin is +integral of s*q
            scale_M += abs(mom)

        for d in self.model.nonuniform_loads:
            if d['x2'] - d['x1'] < 1e-12:
                continue

            def qfn(sx, d=d):
                return -d['fn'](sx)

            q_int, mom = _gauss_VM_integral(qfn, d['x1'], d['x2'], 0.0)
            Fy += q_int
            M0 += -mom
            scale_F += abs(q_int)
            scale_M += abs(mom)

        return Fy, M0, scale_F, scale_M

    def total_applied_load(self):
        """Total applied vertical load (N, +down)."""
        return -self._applied_resultants()[0]

    def restrained_dof(self):
        """How many DOF the supports restrain, counted per NODE.

        Two supports at one station restrain one set of DOF between them, not
        two sets -- the merge in add_support() means this is normally just the
        sum, but counting per node keeps the number right for a model built by
        hand (see BeamResult.__init__ on why that case is defended at all).
        """
        dofs = set()
        for s in self.model.supports:
            i = self.idx_of[round(s['x'], 9)]
            for which in BeamModel.SUPPORT_DOF.get(s['type'], ()):
                dofs.add((i, which))
        return len(dofs)

    def equilibrium(self):
        """Does this answer balance? The check the tab never had.

        Nothing in the Beam tab ever asked whether its own result satisfied
        global equilibrium, which is exactly how R-1 came to report 90 kN of
        reaction for 60 kN of load with a green test suite. Two residuals,
        each assembled from one independent leg (the applied loads, integrated
        here) and one solver leg (the reactions, through the same
        `reaction_at` the diagrams and the reactions report use):

            residual_Fy  = sum of reactions (up) - total applied load (down)
            residual_M0  = the same balance of moments, about x = 0

        plus the closure of the diagrams themselves: just beyond the right-hand
        end of the beam there is nothing left to carry, so V and M there must
        be zero. Both residuals are also reported relative to a scale, since
        1 N of residual means something different on a 2 kN beam and a 2 MN one.

        `indeterminacy` is (restrained DOF - 2), the two being the equilibrium
        equations a planar bending model has. It tells the reader whether the
        numbers above depended on EI at all.
        """
        Fy_applied, M0_applied, scale_F, scale_M = self._applied_resultants()

        reactions_up = 0.0
        reaction_M0 = 0.0
        for sx in self.support_stations:
            fy, m_theta = self.reaction_at(sx)
            reactions_up += fy
            reaction_M0 += fy * sx + m_theta
            scale_F += abs(fy)
            scale_M += abs(fy * sx) + abs(m_theta)

        # A 1 N / 1 N*m floor, so a beam with no load at all divides by
        # something: its residual is identically zero and must read as
        # balanced, not as 0/0.
        scale_F = max(1.0, scale_F)
        scale_M = max(1.0, scale_M)

        residual_Fy = reactions_up + Fy_applied
        residual_M0 = reaction_M0 + M0_applied
        v_end = self.shear_at(self.model.L, side='right')
        m_end = self.moment_at(self.model.L, side='right')

        tol = self.EQUILIBRIUM_TOL
        n_dof = self.restrained_dof()
        return {
            'applied_down': -Fy_applied,
            'reactions_up': reactions_up,
            'residual_Fy': residual_Fy,
            'residual_M0': residual_M0,
            'shear_beyond_end': v_end,
            'moment_beyond_end': m_end,
            'scale_F': scale_F,
            'scale_M': scale_M,
            'rel_Fy': abs(residual_Fy) / scale_F,
            'rel_M0': abs(residual_M0) / scale_M,
            'constrained_dof': n_dof,
            'indeterminacy': n_dof - 2,
            'ok': (abs(residual_Fy) <= tol * scale_F
                   and abs(residual_M0) <= tol * scale_M
                   and abs(v_end) <= tol * scale_F
                   and abs(m_end) <= tol * scale_M),
        }

    def sample_diagram(self, n_per_element=30):
        """Samples V, M, and deflection along the beam for plotting.

        At any station coinciding with a discontinuity (a support reaction,
        point load, or applied moment), two points are emitted at that same
        x: the value just BEFORE the discontinuity, then the value just
        AFTER it — in that order. Plotted as connected line segments, this
        draws a clean vertical jump exactly at that point. Getting the order
        backwards (after-then-before) doesn't affect the vertical segment
        between the twin points themselves, but it DOES corrupt the sloped
        segments connecting to the neighboring stations on either side —
        the diagonal from the previous station ends up aiming at the wrong
        (post-jump) value, producing a visible zigzag/overshoot right at
        the discontinuity instead of a clean diagonal-jump-diagonal shape.
        """
        xs_out, Vs, Ms = [], [], []
        for (n1, n2, x1, x2, Le) in self.elements:
            for k in range(n_per_element + 1):
                x = x1 + Le * k / n_per_element
                # Start of an element (k=0): capture the value just AFTER
                # whatever discontinuity sits at this x (post-jump).
                # End of an element (k=n_per_element): capture the value
                # just BEFORE the discontinuity at the NEXT element's start
                # (pre-jump). Interior points have no discontinuity, so the
                # side choice there doesn't matter.
                side = 'left' if k == n_per_element else 'right'
                V = self.shear_at(x, side=side)
                M = self.moment_at(x, side=side)
                xs_out.append(x); Vs.append(V); Ms.append(M)

        # The right end of the beam (x = L) has no following element to
        # supply the closing side='right' "just after the final reaction"
        # point — the loop's own last point (side='left') already gives the
        # correct pre-final-reaction value, so just append the post-reaction
        # closing value (typically 0) after it.
        if xs_out and abs(xs_out[-1] - self.model.L) < 1e-9:
            xL = xs_out[-1]
            xs_out.append(xL)
            Vs.append(self.shear_at(xL, side='right'))
            Ms.append(self.moment_at(xL, side='right'))

        # Deflection along the SAME stations, integrated forward in one pass
        # rather than by calling deflection(x) per station. That method
        # (_theta_v_at) re-integrates the moment diagram from x = 0 every time
        # it is called, and each of its 30 sub-steps per element is an
        # O(loads) moment_at -- so sampling the curve station by station cost
        # O(stations * elements * loads), cubic in the model size (a 40-load
        # beam took 5.4 s, and this was the single biggest reason the test
        # suite ran over an hour). The moment values are already sampled just
        # above; integrating them forward once, with the same Simpson (for the
        # rotation) then trapezoid (for the deflection) rule _theta_v_at uses,
        # reproduces the same curve at a fraction of the cost. The point-query
        # deflection(x) is deliberately left untouched, so its closed-form
        # accuracy tests still bind and this fast path is checked against them.
        defl = self._integrate_deflection(xs_out, Ms)
        return {'x': xs_out, 'V': Vs, 'M': Ms, 'v': defl}

    def _integrate_deflection(self, xs, Ms):
        """Deflection at each station in `xs`, from the moment samples `Ms`.

        One cumulative sweep: rotation theta from integrating M/EI, deflection
        v from integrating theta, seeded at x = 0 from the left node's own
        solved DOF exactly as `_theta_v_at` seeds them. A zero-width interval
        (the twin before/after points that draw a shear or moment jump) leaves
        theta and v unchanged, which is correct -- slope and deflection are
        continuous across a jump in V or M. Only the sub-interval midpoint
        moment is evaluated fresh; the endpoints reuse the already-sampled
        `Ms`, whose side choice (pre-jump at an element's end, post-jump at the
        next element's start) is exactly the interior value each interval
        needs.
        """
        i0 = self.idx_of[round(0.0, 9)]
        v = self.d[2 * i0]
        th = self.d[2 * i0 + 1]
        EI = self.EI
        out = [v]
        for i in range(1, len(xs)):
            h = xs[i] - xs[i - 1]
            if h <= 1e-12:
                out.append(v)                 # zero-width twin point
                continue
            Mm = self.moment_at(0.5 * (xs[i - 1] + xs[i]), side='right')
            dth = h / 6.0 * (Ms[i - 1] + 4.0 * Mm + Ms[i]) / EI
            th_new = th + dth
            v = v + h / 2.0 * (th + th_new)
            th = th_new
            out.append(v)
        return out

def _adaptive_vector_integral(vfn, a, b, dim, tol=1e-7, max_depth=20):
    """Same adaptive-refinement scheme as `_adaptive_integral`, but for a
    vector-valued integrand `vfn(x)` that returns `dim` values sharing the
    same evaluation points (e.g. q(x) weighted by each of a beam element's
    4 Hermite shape functions in one pass, or a load's (force, moment)
    contribution together). Refinement is driven by the combined vector's
    magnitude of disagreement between the whole-panel and half-panel
    estimates. See `_adaptive_integral` for why a minimum panel width is
    also enforced."""
    min_width = max(1e-12, (b - a) * 1e-10) if b > a else 1e-12

    def gauss5(lo, hi):
        h = (hi - lo) / 2
        mid = (lo + hi) / 2
        acc = [0.0] * dim
        for node, wt in zip(_GAUSS5_NODES, _GAUSS5_WEIGHTS):
            try:
                vals = vfn(mid + node*h)
            except (ZeroDivisionError, ValueError, OverflowError):
                continue
            for i in range(dim):
                acc[i] += wt * vals[i]
        return [v * h for v in acc]

    def rec(lo, hi, whole, depth):
        if depth >= max_depth or (hi - lo) <= min_width:
            return whole
        mid = (lo + hi) / 2
        left = gauss5(lo, mid)
        right = gauss5(mid, hi)
        combined = [left[i] + right[i] for i in range(dim)]
        err = math.sqrt(sum((combined[i]-whole[i])**2 for i in range(dim)))
        scale = max(1.0, math.sqrt(sum(v*v for v in whole)))
        if err <= tol * scale:
            return combined
        lr = rec(lo, mid, left, depth+1)
        rr = rec(mid, hi, right, depth+1)
        return [lr[i] + rr[i] for i in range(dim)]

    if b <= a:
        return [0.0] * dim
    return rec(a, b, gauss5(a, b), 0)

def _gauss_VM_integral(qfn, a, b, x, n_panels=None):
    """Returns (∫ q(s) ds, ∫ q(s)*(x-s) ds) over [a,b] — the resultant force
    and its moment about station x — via adaptive Gauss-Legendre quadrature
    (see `_adaptive_vector_integral`). Accurate even where q is singular
    exactly at a or b, or varies sharply near either edge; `n_panels` is
    accepted for backward compatibility but no longer used."""
    def vfn(s):
        qs = qfn(s)
        return (qs, qs * (x - s))
    return tuple(_adaptive_vector_integral(vfn, a, b, dim=2))
