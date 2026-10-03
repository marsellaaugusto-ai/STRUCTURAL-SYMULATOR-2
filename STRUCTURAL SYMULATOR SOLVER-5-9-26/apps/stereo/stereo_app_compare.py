"""Comparing iterations in the app: group tags, the lift plan, Check lifts
and the Compare window -- the controller over stereo_compare."""
import tkinter as tk
from tkinter import ttk

from apps.stereo import stereo_compare as scmp
from apps.stereo import stereo_floating as sf
from apps.stereo import stereo_groups as sgp


class StereoCompareMixin:

    # ── E1: tags ───────────────────────────────────────────────────────────

    def _staged_outermost(self):
        """Groups a stage can be proposed for: each one whose name names a
        stage and that sits in no group that does -- "Truss 1", not its
        "Truss 1 top strip"."""
        out = []
        for g, _lvl in sgp.walk(self.groups):
            if scmp._stage_of(g['name']) is None and not g.get('stage'):
                continue
            anc = self._group_path(g['id'])[:-1]
            if any(scmp._stage_of(sgp.find(self.groups, a)['name'])
                   or sgp.find(self.groups, a).get('stage') for a in anc):
                continue
            out.append(g)
        return out

    def _propose_group_tags(self):
        """Fill in the tags the names suggest -- blanks only; a tag the user
        set is never overwritten. Returns {gid: {tag: value}} of what was
        set."""
        cands = self._staged_outermost()
        prop = scmp.propose_tags([g['name'] for g in cands])
        changed = {}
        for g in cands:
            for k, v in prop.get(g['name'], {}).items():
                if not g.get(k):
                    g[k] = v
                    changed.setdefault(g['id'], {})[k] = v
        self._refresh_group_list()
        self._set_status('Tags proposed for %d group(s) -- check them in the '
                         'Iterations window.' % len(changed) if changed else
                         'No new tags to propose.', 'ok')
        return changed

    def _set_group_tags(self, gid, **tags):
        g = sgp.find(self.groups, gid)
        if g is None:
            return False
        for k in scmp.TAGS:
            if k in tags:
                v = str(tags[k] or '').strip()
                if v:
                    g[k] = v
                else:
                    g.pop(k, None)
        return True

    # ── E2: the lift plan ─────────────────────────────────────────────────

    def _lift_plan(self):
        """One planned lift per tagged group, in slot order."""
        rules = getattr(self, '_lift_plan_rules', None) or {}
        plan = []
        for g, _lvl in sgp.walk(self.groups):
            if not g.get('stage'):
                continue
            plan.append({
                'gid': g['id'], 'group': self._group_display_name(g['id']),
                'iteration': str(g.get('iteration') or '?'),
                'stage': str(g['stage']),
                'position': str(g.get('position') or '1'),
                'rule': rules.get(g['id']) or scmp.DEFAULT_RULE.get(
                    g['stage'], 'corners')})
        return plan

    def _set_lift_rule(self, gid, rule):
        if rule not in sf.PICK_RULES:
            raise ValueError('Unknown pick rule %r.' % rule)
        self._lift_plan_rules = dict(getattr(self, '_lift_plan_rules', None)
                                     or {})
        self._lift_plan_rules[gid] = rule

    def _check_lifts(self):
        """Solve every planned lift, each on its own and on a copy: nothing
        is added to the model. Returns the checked list."""
        try:
            settings = self._crane_settings()
        except ValueError as exc:
            self._set_status(str(exc), 'error')
            return []
        checked = []
        for p in self._lift_plan():
            rods = sorted(sgp.rods_of(self.groups, p['gid'], deep=True))
            row = scmp.check_lift(self.nodes, self.members, rods, p['rule'],
                                  settings, self._unit_weight(),
                                  timber=self._timber_settings())
            checked.append(dict(p, row=row))
        self._plan_checked = checked
        # the model these answers are for: an edit since makes them stale
        self._plan_sig = self._live_signature()
        ok = sum(1 for c in checked if c['row']['verdict'] == 'OK')
        self._set_status('Check lifts: %d of %d planned lift(s) OK.'
                         % (ok, len(checked)), 'ok' if ok == len(checked)
                         else 'error')
        return checked

    # ── E3: compare ───────────────────────────────────────────────────────

    def _compare_table(self):
        checked = getattr(self, '_plan_checked', None) or []
        if not checked or getattr(self, '_plan_sig', None) != \
                self._live_signature():
            return [], []
        return scmp.compare_rows(checked)

    def _compare_export(self):
        """What Export Excel writes on the Compare sheet, or None."""
        its, table = self._compare_table()
        if not table:
            return None
        return {'iterations': its, 'table': table,
                'best': scmp.best_iteration(self._plan_checked)}

    def _open_iterations(self):
        """The Iterations window: the tags and lift rule of every tagged
        group (editable), Propose / Check lifts, and the Compare table."""
        old = getattr(self, '_iter_win', None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
        win = tk.Toplevel(self.canvas)
        win.title('Iterations: tags, lift plan, compare')
        self._iter_win = win
        top = tk.Frame(win)
        top.pack(fill='both', expand=True, padx=8, pady=(8, 2))
        cols = ('group', 'iteration', 'stage', 'position', 'lift rule')
        tv = ttk.Treeview(top, columns=cols, show='headings', height=8)
        for c, w in zip(cols, (180, 70, 80, 70, 130)):
            tv.heading(c, text=c)
            tv.column(c, width=w, anchor='w')
        tv.pack(fill='both', expand=True)
        self._iter_tags_tv = tv

        edit = tk.Frame(win)
        edit.pack(fill='x', padx=8, pady=2)
        ev = {k: tk.StringVar() for k in scmp.TAGS}
        rule_var = tk.StringVar()
        for k in scmp.TAGS:
            tk.Label(edit, text=k, font=('Helvetica', 8)).pack(side='left')
            tk.Entry(edit, textvariable=ev[k], width=8).pack(side='left',
                                                             padx=(2, 6))
        ttk.Combobox(edit, textvariable=rule_var, state='readonly', width=16,
                     values=[sf.PICK_RULE_LABELS[r] for r in sf.PICK_RULES]
                     ).pack(side='left')
        label_rule = {v: k for k, v in sf.PICK_RULE_LABELS.items()}

        def rows():
            tv.delete(*tv.get_children())
            plan = {p['gid']: p for p in self._lift_plan()}
            for g, lvl in sgp.walk(self.groups):
                p = plan.get(g['id'])
                if p is None and lvl > 0:
                    continue
                tv.insert('', 'end', iid=str(g['id']), values=(
                    '   ' * lvl + self._group_display_name(g['id']),
                    g.get('iteration') or '', g.get('stage') or '',
                    g.get('position') or '',
                    sf.PICK_RULE_LABELS[p['rule']] if p else ''))

        def pick(_e=None):
            sel = tv.selection()
            if not sel:
                return
            g = sgp.find(self.groups, int(sel[0]))
            for k in scmp.TAGS:
                ev[k].set(g.get(k) or '')
            p = {q['gid']: q for q in self._lift_plan()}.get(g['id'])
            rule_var.set(sf.PICK_RULE_LABELS[p['rule']] if p else '')

        def apply():
            sel = tv.selection()
            if not sel:
                return
            gid = int(sel[0])
            self._set_group_tags(gid, **{k: ev[k].get() for k in scmp.TAGS})
            if rule_var.get() in label_rule:
                self._set_lift_rule(gid, label_rule[rule_var.get()])
            rows()
            tv.selection_set(str(gid))

        tv.bind('<<TreeviewSelect>>', pick)
        tk.Button(edit, text='Set', command=apply).pack(side='left',
                                                        padx=(6, 0))
        btns = tk.Frame(win)
        btns.pack(fill='x', padx=8, pady=4)
        tk.Button(btns, text='Propose tags from names',
                  command=lambda: (self._propose_group_tags(), rows())
                  ).pack(side='left')
        tk.Button(btns, text='▶ Check lifts', fg='#1a6bbd',
                  command=lambda: (self._check_lifts(), fill_compare())
                  ).pack(side='left', padx=(6, 0))

        cmp_frame = tk.LabelFrame(win, text='Compare (slot × iteration; '
                                            'green: lightest piece whose '
                                            'lift passes)')
        cmp_frame.pack(fill='both', expand=True, padx=8, pady=(2, 8))
        self._iter_cmp_frame = cmp_frame

        def fill_compare():
            for w in cmp_frame.winfo_children():
                w.destroy()
            its, table = self._compare_table()
            if not table:
                tk.Label(cmp_frame, text='Tag the groups, then ▶ Check lifts.',
                         fg='#5f6368').pack(padx=6, pady=6)
                return
            cols = ['slot', 'value'] + ['it %s' % i for i in its]
            ct = ttk.Treeview(cmp_frame, columns=cols, show='headings',
                              height=min(22, len(table)))
            for c in cols:
                ct.heading(c, text=c)
                ct.column(c, width=110 if c != 'value' else 130, anchor='w')
            best = scmp.best_iteration(self._plan_checked)
            for st, pos, label, vals in table:
                tags = ()
                ct.insert('', 'end', values=[
                    '%s %s' % (st, pos) if label == 'group' else '', label]
                    + [vals.get(i, '') for i in its], tags=tags)
            ct.pack(fill='both', expand=True)
            if best:
                tk.Label(cmp_frame, text='Lightest passing: ' + '; '.join(
                    '%s %s → iteration %s' % (st, pos, it)
                    for (st, pos), it in sorted(best.items())),
                    fg='#1d6b2e', justify='left', wraplength=620
                ).pack(anchor='w', padx=4, pady=(2, 4))
            self._iter_cmp_tv = ct

        rows()
        fill_compare()
        tk.Button(win, text='Close', command=win.destroy).pack(pady=(0, 8))
        return win
