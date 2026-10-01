"""Copy and paste in the Stereo tab (round 2, item 7).

Copy puts the selection on the system clipboard as text
(stereo_clipboard), so a paste works in the same file, after opening
another file, or in another window of the app. Paste places it at a typed
offset or at a node clicked on the model, once or as an array of copies,
and optionally brings along the supports, loads and group membership of
what was copied.
"""

import tkinter as tk
from tkinter import messagebox

from apps.stereo import stereo_clipboard as scb
from apps.stereo.stereo_app_constants import BG, PANEL_TEXT_W
from apps.stereo.stereo_app_shell import HINT_FG


class StereoClipboardMixin:

    def _build_clipboard_panel(self, parent):
        box = tk.LabelFrame(parent, text='Copy / paste', bg=BG,
                            font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=(0, 8))
        tk.Label(box, text='Ctrl+C copies the selected rods and nodes -- to '
                           'the system clipboard, so it pastes into another '
                           'file or window too. Ctrl+V pastes: at an offset, '
                           'or at a node you click, once or as an array.',
                 bg=BG, fg=HINT_FG, font=('Helvetica', 8), justify='left',
                 wraplength=PANEL_TEXT_W).pack(anchor='w', padx=6, pady=(2, 4))
        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', padx=6, pady=(0, 6))
        tk.Button(row, text='Copy', font=('Helvetica', 8),
                  command=self._copy_selection).pack(side='left', expand=True,
                                                     fill='x')
        tk.Button(row, text='Paste…', font=('Helvetica', 8),
                  command=self._paste_dialog).pack(side='left', expand=True,
                                                   fill='x', padx=(3, 0))

    # ── copy ───────────────────────────────────────────────────────────────

    def _copy_selection(self, _event=None):
        clip = scb.make_clip(
            self.nodes, self.members, self.selected_nodes,
            set(self.selected_members) | ({self.selected_member}
                                          if self.selected_member is not None
                                          else set()),
            supports=self.supports, loads=self.loads,
            load_nodes=self._load_nodes, member_loads=self.member_loads,
            groups=self.groups, profiles=self.profiles)
        if clip is None:
            self._set_status('Select the rods or nodes to copy first.',
                             'error')
            return 'break'
        self._clip = clip
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(scb.to_text(clip))
        except tk.TclError:
            pass                        # the in-app copy still works
        self._set_status('Copied %d rod(s) and %d node(s). Ctrl+V to paste.'
                         % (len(clip['members']), len(clip['nodes'])), 'ok')
        return 'break'

    def _clipboard_clip(self):
        """What a paste would paste: the system clipboard's copy if it holds
        one (another window's, another file's), else this window's last."""
        try:
            clip = scb.from_text(self.root.clipboard_get())
        except tk.TclError:
            clip = None
        return clip or getattr(self, '_clip', None)

    # ── paste ──────────────────────────────────────────────────────────────

    def _paste_defaults(self, clip):
        """A first paste goes alongside: one copy's width along x."""
        prev = getattr(self, '_paste_opts', None)
        if prev:
            return dict(prev)
        xs = [p[0] for p in clip['nodes']]
        return {'place': 'offset', 'dx': round(max(xs) - min(xs), 6) or 1.0,
                'dy': 0.0, 'dz': 0.0, 'count': 1,
                'supports': False, 'loads': True, 'groups': True}

    def _paste_dialog(self, _event=None):
        clip = self._clipboard_clip()
        if clip is None:
            self._set_status('Nothing to paste -- copy a selection first '
                             '(Ctrl+C).', 'error')
            return 'break'
        opts = self._paste_ask(clip)
        if opts is None:
            return 'break'
        self._paste_opts = dict(opts)
        if opts['place'] == 'point':
            self._paste_pending = (clip, opts)
            self._set_status('Click the node the copy\'s corner node goes on '
                             '(Esc cancels).', 'ok')
            return 'break'
        self._paste_with(clip, opts, (0.0, 0.0, 0.0))
        return 'break'

    def _paste_ask(self, clip):
        """The paste dialog; the options chosen, or None if cancelled."""
        d = self._paste_defaults(clip)
        win = tk.Toplevel(self.root)
        win.title('Paste')
        win.transient(self.root)
        tk.Label(win, text='Paste %d rod(s), %d node(s)'
                 % (len(clip['members']), len(clip['nodes'])),
                 font=('', 11, 'bold')).pack(pady=(10, 4), padx=14)
        place = tk.StringVar(master=win, value=d['place'])
        f = tk.Frame(win)
        f.pack(fill='x', padx=14)
        tk.Radiobutton(f, text='Offset by (m):', variable=place,
                       value='offset').grid(row=0, column=0, sticky='w')
        vs = {}
        for k, key in enumerate(('dx', 'dy', 'dz')):
            vs[key] = tk.DoubleVar(master=win, value=d[key])
            tk.Label(f, text=key[1]).grid(row=0, column=1 + 2 * k)
            tk.Entry(f, textvariable=vs[key], width=7).grid(
                row=0, column=2 + 2 * k, padx=(0, 4))
        tk.Radiobutton(f, text='At a node I click (the offset then steps '
                               'the array)', variable=place, value='point'
                       ).grid(row=1, column=0, columnspan=7, sticky='w')
        ar = tk.Frame(win)
        ar.pack(fill='x', padx=14, pady=(6, 0))
        tk.Label(ar, text='Copies (array):').pack(side='left')
        count = tk.IntVar(master=win, value=d['count'])
        tk.Spinbox(ar, from_=1, to=200, textvariable=count, width=5).pack(
            side='left', padx=4)
        tk.Label(ar, text='each one offset further on', fg='grey').pack(
            side='left')
        car = tk.LabelFrame(win, text='Bring along')
        car.pack(fill='x', padx=14, pady=(8, 0))
        bring = {}
        for key, text in (('supports', 'supports'),
                          ('loads', 'loads (point, on rods, roof areas)'),
                          ('groups', 'group membership')):
            bring[key] = tk.BooleanVar(master=win, value=d[key])
            tk.Checkbutton(car, text=text, variable=bring[key]).pack(
                anchor='w', padx=6)
        out = {'o': None}

        def ok():
            try:
                o = {'place': place.get(), 'count': max(1, int(count.get()))}
                for key in ('dx', 'dy', 'dz'):
                    o[key] = float(vs[key].get())
            except (tk.TclError, ValueError):
                messagebox.showerror('Paste', 'Enter numbers for the offset '
                                              'and the copies.')
                return
            o.update({k: bool(v.get()) for k, v in bring.items()})
            out['o'] = o
            win.destroy()

        btns = tk.Frame(win)
        btns.pack(pady=(10, 12))
        tk.Button(btns, text='Paste', command=ok, width=10).pack(
            side='left', padx=4)
        tk.Button(btns, text='Cancel', command=win.destroy, width=10).pack(
            side='left', padx=4)
        win.grab_set()
        try:
            self.root.wait_window(win)
        finally:
            try:
                if win.winfo_exists():
                    win.grab_release()
                    win.destroy()
            except tk.TclError:
                pass
        return out['o']

    def _paste_at_click(self, ex, ey):
        """The click a paste-at-a-point is waiting for."""
        clip, opts = self._paste_pending
        hit = self._nearest_node_to(ex, ey)
        if hit is None:
            self._set_status('Click ON a node to paste at it (Esc cancels).',
                             'error')
            return
        self._paste_pending = None
        rx, ry, rz = scb.ref_point(clip)
        x, y, z = self.nodes[hit]
        self._paste_with(clip, opts, (x - rx, y - ry, z - rz),
                         first_at_base=True)

    def _paste_with(self, clip, opts, base, first_at_base=False):
        """Paste `clip` `opts['count']` times: at `base` + k steps (k from 0
        when placed at a clicked point, from 1 for a typed offset)."""
        step = (opts['dx'], opts['dy'], opts['dz'])
        start = 0 if first_at_base else 1
        offsets = [tuple(b + s * k for b, s in zip(base, step))
                   for k in range(start, start + opts['count'])]
        model = {'nodes': self.nodes, 'members': self.members,
                 'loads': self.loads, 'supports': self.supports,
                 'groups': self.groups, 'profiles': self.profiles,
                 'member_loads': self.member_loads,
                 'load_nodes': self._load_nodes}
        new, rep, new_rods, new_nodes = scb.paste(
            model, clip, offsets, carry_supports=opts.get('supports'),
            carry_loads=opts.get('loads'), carry_groups=opts.get('groups'))
        if not new_rods and not new_nodes:
            self._set_status('The paste lands exactly on what is already '
                             'there -- nothing to add.', 'ok')
            return False
        self._push_undo('paste')
        n_before = len(self.members)
        self.nodes, self.members = new['nodes'], new['members']
        self.loads, self.supports = new['loads'], new['supports']
        self.profiles = new['profiles']
        self.member_loads = new['member_loads']
        self._load_nodes = new['load_nodes']
        if opts.get('groups'):
            self.groups = new['groups']
        self._adopt_new_rods(n_before)
        self.selected_nodes = set(new_nodes)
        self.selected_members = set(new_rods)
        self.selected_member = None
        self.results = None
        self.member_checks = None
        self._me_maybe_refresh_topology()
        self._refresh_all()
        self._set_status(
            'Pasted %d cop%s: %d rod(s) and %d node(s) added%s.'
            % (rep['copies'], 'y' if rep['copies'] == 1 else 'ies',
               len(new_rods), len(new_nodes),
               (', %d node(s) joined to the structure' % rep['nodes_merged']
                if rep['nodes_merged'] else '')), 'ok')
        return True
