"""The Roles panel: the axis that cuts across the group tree.

See stereo_roles for why this is a separate axis rather than more groups.
In short: "every diagonal" is not a branch of anything, so a tree can never
answer it, and every attempt to make the tree answer it added a control.

What this adds, and nothing more:

  * every role in the model, with its rod count;
  * click one to SELECT its rods, anywhere in the model;
  * tick one to HIDE them, anywhere in the model;
  * save a RULE -- a question, not a list -- and select or hide by it.

A rule is re-asked every time it is used, so it stays right after the model
changes. Rules live for the session; they are not yet written into the
workbook, which is the obvious next step and deliberately not in this one.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from apps.stereo import stereo_roles as sr
from apps.stereo.stereo_app_constants import BG, PANEL_TEXT_W
from apps.stereo.stereo_app_shell import HINT_FG


class StereoRolesMixin:
    """Select and hide by role, and by saved rule."""

    def _init_roles_state(self):
        self._hidden_roles = set()
        self.role_rules = []
        self._hidden_rules = set()        # names of rules currently hiding
        self._roles_rows = None
        self._rules_list = None

    # ── what is hidden by this axis ────────────────────────────────────────

    def _hidden_by_role(self):
        """Rods hidden by a role or by a rule. Re-asked every time.

        A rule hides by its QUESTION, so a rod that stops matching comes
        back on its own and one that starts matching goes away -- which is
        the whole reason a rule is not a saved list of rod numbers.
        """
        hidden = set()
        if getattr(self, '_hidden_roles', None):
            hidden.update(sr.rods_with_role(self.members, self._hidden_roles))
        for rule in getattr(self, 'role_rules', ()) or ():
            if rule['name'] in getattr(self, '_hidden_rules', ()):
                hidden.update(sr.matching(rule, self.members, self.groups,
                                          self.member_checks))
        return {i for i in hidden if 0 <= i < len(self.members)}

    # ── the panel ──────────────────────────────────────────────────────────

    def _build_roles_panel(self, parent):
        box = tk.LabelFrame(parent, text='Roles (across every group)', bg=BG,
                            font=('Helvetica', 8, 'bold'))
        box.pack(fill='x', padx=6, pady=(6, 2))
        tk.Label(box, text='A role is not a group: a diagonal exists in every '
                           'one of them. Click a role to select it everywhere; '
                           'tick to hide it everywhere.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W - 12).pack(anchor='w', padx=4,
                                                    pady=(2, 3))
        self._roles_rows = tk.Frame(box, bg=BG)
        self._roles_rows.pack(fill='x', padx=4)

        rule = tk.Frame(box, bg=BG)
        rule.pack(fill='x', padx=4, pady=(4, 4))
        tk.Button(rule, text='Save a rule…', font=('Helvetica', 8),
                  command=self._rule_new).pack(side='left', expand=True, fill='x')
        tk.Button(rule, text='Rules…', font=('Helvetica', 8),
                  command=self._rules_dialog).pack(side='left', expand=True,
                                                   fill='x', padx=(3, 0))
        self._refresh_roles_list()
        return box

    def _refresh_roles_list(self):
        rows = getattr(self, '_roles_rows', None)
        if rows is None:
            return
        for w in rows.winfo_children():
            w.destroy()
        found = sr.roles_in(self.members) if self.members else {}
        if not found:
            tk.Label(rows, text='No rods yet.', bg=BG, fg=HINT_FG,
                     font=('Helvetica', 8)).pack(anchor='w')
            return
        for role, idx in found.items():
            line = tk.Frame(rows, bg=BG)
            line.pack(fill='x')
            var = tk.BooleanVar(value=role in self._hidden_roles)
            tk.Checkbutton(line, variable=var, bg=BG,
                           command=lambda r=role, v=var:
                               self._roles_set_hidden(r, v.get())
                           ).pack(side='left')
            tk.Button(line, text='%s' % sr.label(role), font=('Helvetica', 8),
                      anchor='w', relief='flat', bg=BG,
                      command=lambda r=role: self._roles_select(r)
                      ).pack(side='left', expand=True, fill='x')
            tk.Label(line, text='%d' % len(idx), bg=BG, fg=HINT_FG,
                     font=('Courier', 8)).pack(side='right', padx=(2, 4))

    # ── the two verbs ──────────────────────────────────────────────────────

    def _roles_select(self, role, additive=False):
        rods = set(sr.rods_with_role(self.members, {role}))
        rods -= self._hidden_rods()
        if not rods:
            self._set_status('No %s is visible to select.' % sr.label(role),
                             'idle')
            return set()
        self.selected_members = (self.selected_members | rods) if additive \
            else rods
        self.selected_nodes = set()
        self.selected_member = None
        self._sync_selection_fields()
        self._set_status('%d %s selected, across every group.'
                         % (len(rods), sr.label(role).lower()), 'ok')
        self._draw()
        return rods

    def _roles_set_hidden(self, role, hide):
        if hide:
            self._hidden_roles.add(role)
        else:
            self._hidden_roles.discard(role)
        self._draw()
        return self._hidden_roles

    # ── rules ──────────────────────────────────────────────────────────────

    def _rule_new(self):
        """A small dialog: which roles, and optionally a utilisation band."""
        if not self.members:
            messagebox.showinfo('Rules', 'There is no model yet.')
            return None
        win = tk.Toplevel(self.root)
        win.title('Save a rule')
        win.transient(self.root)
        tk.Label(win, text='A rule is a question, not a list of rods. It is '
                           'asked again every time it is used, so it stays '
                           'right after the model changes.',
                 fg=HINT_FG, justify='left', wraplength=360,
                 font=('Helvetica', 8)).pack(anchor='w', padx=12, pady=(10, 6))

        tk.Label(win, text='Name:', font=('Helvetica', 9)).pack(anchor='w', padx=12)
        name = tk.Entry(win, width=34)
        name.insert(0, 'New rule')
        name.pack(anchor='w', padx=12, pady=(0, 6))

        tk.Label(win, text='Roles (none ticked = any rod):',
                 font=('Helvetica', 9)).pack(anchor='w', padx=12)
        lb = tk.Listbox(win, selectmode='multiple', height=7, width=34,
                        exportselection=False)
        keys = list(sr.roles_in(self.members))
        for r in keys:
            lb.insert('end', sr.label(r))
        lb.pack(anchor='w', padx=12, pady=(0, 6))

        band = tk.Frame(win)
        band.pack(anchor='w', padx=12, pady=(0, 8))
        tk.Label(band, text='Utilisation from', font=('Helvetica', 9)).pack(side='left')
        lo = tk.Entry(band, width=6); lo.pack(side='left', padx=(4, 4))
        tk.Label(band, text='to', font=('Helvetica', 9)).pack(side='left')
        hi = tk.Entry(band, width=6); hi.pack(side='left', padx=(4, 0))

        made = {}

        def ok():
            def num(e):
                t = e.get().strip()
                try:
                    return float(t) if t else None
                except ValueError:
                    return None
            roles = {keys[i] for i in lb.curselection()}
            made['rule'] = sr.new_rule(name.get(), roles=roles or None,
                                       util_min=num(lo), util_max=num(hi))
            win.destroy()

        row = tk.Frame(win); row.pack(pady=(0, 10))
        tk.Button(row, text='Save', command=ok).pack(side='left', padx=4)
        tk.Button(row, text='Cancel', command=win.destroy).pack(side='left', padx=4)
        win.wait_window()

        rule = made.get('rule')
        if rule is not None:
            self.role_rules = [r for r in self.role_rules
                               if r['name'] != rule['name']] + [rule]
            self._set_status('Rule "%s" saved: %s'
                             % (rule['name'], sr.describe(rule)), 'ok')
        return rule

    def _rule_matching(self, rule):
        return sr.matching(rule, self.members, self.groups, self.member_checks)

    def _rule_select(self, rule):
        rods = set(self._rule_matching(rule)) - self._hidden_rods()
        if not rods:
            self._set_status('"%s" matches nothing right now%s.'
                             % (rule['name'],
                                ' (no analysis yet)' if not self.member_checks
                                and (rule['util_min'] is not None
                                     or rule['util_max'] is not None) else ''),
                             'idle')
            return set()
        self.selected_members = rods
        self.selected_nodes = set()
        self.selected_member = None
        self._sync_selection_fields()
        self._set_status('%d rod(s) match "%s".' % (len(rods), rule['name']), 'ok')
        self._draw()
        return rods

    def _rule_set_hidden(self, rule, hide):
        if hide:
            self._hidden_rules.add(rule['name'])
        else:
            self._hidden_rules.discard(rule['name'])
        self._draw()
        return self._hidden_rules

    def _rules_dialog(self):
        if not self.role_rules:
            messagebox.showinfo('Rules', 'No rules saved yet. "Save a rule…" '
                                         'makes one.')
            return None
        win = tk.Toplevel(self.root)
        win.title('Saved rules')
        win.transient(self.root)
        tk.Label(win, text='Saved rules', font=('', 12, 'bold')).pack(pady=(10, 2))
        lb = tk.Listbox(win, width=58, height=min(10, len(self.role_rules)))
        for r in self.role_rules:
            mark = '[hidden] ' if r['name'] in self._hidden_rules else ''
            lb.insert('end', '%s%s — %s (%d now)'
                      % (mark, r['name'], sr.describe(r),
                         len(self._rule_matching(r))))
        lb.pack(padx=12, pady=(0, 8))

        def picked():
            s = lb.curselection()
            return self.role_rules[s[0]] if s else None

        def act(fn):
            def go():
                r = picked()
                if r is not None:
                    fn(r)
                    win.destroy()
            return go

        row = tk.Frame(win); row.pack(pady=(0, 10))
        tk.Button(row, text='Select', command=act(self._rule_select)
                  ).pack(side='left', padx=3)
        tk.Button(row, text='Hide / show',
                  command=act(lambda r: self._rule_set_hidden(
                      r, r['name'] not in self._hidden_rules))
                  ).pack(side='left', padx=3)
        tk.Button(row, text='Delete', command=act(self._rule_delete)
                  ).pack(side='left', padx=3)
        tk.Button(row, text='Close', command=win.destroy).pack(side='left', padx=3)
        self._last_rules_window = win
        return win

    def _rule_delete(self, rule):
        self.role_rules = [r for r in self.role_rules if r is not rule]
        self._hidden_rules.discard(rule['name'])
        self._draw()
        return self.role_rules
