"""The selection inspector and the model tree for the Stereo tab.

Both were built into the old sidebar. The UI rebuild replaced that sidebar
with a mode rail whose panels are built once per mode, so these moved out
here rather than into the rebuilt panels module -- they are one concern
(reading and editing whatever is currently selected) and they now attach to
the Results mode's frame like any other panel builder.

Nothing here solves anything: the inspector writes straight onto
self.nodes / self.members and then asks for a redraw, and the tree only
lists what is already in the model.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from apps.stereo.stereo_app_constants import BG, PANEL_W


class StereoInspectorMixin:
    """Contextual properties for the selection, plus the model tree."""

    def _build_properties_panel(self, parent):
        box = tk.LabelFrame(parent, text='Properties', bg=BG,
                            font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=4)
        self._panel_properties = box

        self._props_label = tk.Label(box, text='(select a node or member)',
                                      bg=BG, fg='#666', font=('Helvetica', 9),
                                      wraplength=PANEL_W - 24, justify='left')
        self._props_label.pack(anchor='w', padx=6, pady=(4, 2))

        self._props_frame = tk.Frame(box, bg=BG)
        self._props_frame.pack(fill='x', padx=6, pady=(0, 4))
        self._props_entries = {}

    def _update_properties_panel(self):
        for w in self._props_frame.winfo_children():
            w.destroy()
        self._props_entries.clear()

        sn = self.selected_node
        sm_idx = self.selected_member
        if sn is not None and sn < len(self.nodes):
            self._props_label.config(text=f'Node {sn}')
            x, y, z = self.nodes[sn]
            for lbl, key, val in [('X (m):', 'x', x), ('Y (m):', 'y', y), ('Z (m):', 'z', z)]:
                row = tk.Frame(self._props_frame, bg=BG)
                row.pack(fill='x', pady=1)
                tk.Label(row, text=lbl, bg=BG, font=('Helvetica', 8),
                         width=8, anchor='e').pack(side='left')
                var = tk.DoubleVar(value=round(val, 6))
                ent = tk.Entry(row, textvariable=var, width=10, font=('Helvetica', 8))
                ent.pack(side='left', padx=2)
                self._props_entries[key] = var

            sup = next((s for s in self.supports if s['node'] == sn), None)
            if sup:
                tk.Label(self._props_frame, text=f'Support: {sup.get("type", "custom")}',
                         bg=BG, font=('Helvetica', 8), fg='#1a6bbd').pack(anchor='w', pady=(2, 0))

            loads_at = [ld for ld in self.loads if ld['node'] == sn]
            if loads_at:
                ld = loads_at[0]
                tk.Label(self._props_frame,
                         text=f'Load: ({ld["fx"]:.1f}, {ld["fy"]:.1f}, {ld["fz"]:.1f}) kN',
                         bg=BG, font=('Helvetica', 8), fg='#e07b1f').pack(anchor='w', pady=(2, 0))

            tk.Button(self._props_frame, text='Apply', font=('Helvetica', 8),
                      command=self._apply_node_properties).pack(anchor='w', pady=(4, 0))

        elif sm_idx is not None and sm_idx < len(self.members):
            m = self.members[sm_idx]
            self._props_label.config(text=f'Member {sm_idx} (nodes {m["a"]}–{m["b"]})')

            for lbl, key, val in [
                ('E (GPa):', 'E', m.get('E', 200.0)),
                ('A (cm²):', 'A', m.get('A', 20.0)),
                ('I (cm⁴):', 'I', m.get('I', 400.0)),
                ('J (cm⁴):', 'J', m.get('J', 400.0)),
                ('Fy (MPa):', 'Fy', m.get('Fy', 235.0)),
                ('Fu (MPa):', 'Fu', m.get('Fu', 360.0)),
            ]:
                row = tk.Frame(self._props_frame, bg=BG)
                row.pack(fill='x', pady=1)
                tk.Label(row, text=lbl, bg=BG, font=('Helvetica', 8),
                         width=10, anchor='e').pack(side='left')
                var = tk.DoubleVar(value=round(val, 4))
                ent = tk.Entry(row, textvariable=var, width=10, font=('Helvetica', 8))
                ent.pack(side='left', padx=2)
                self._props_entries[key] = var

            role_row = tk.Frame(self._props_frame, bg=BG)
            role_row.pack(fill='x', pady=1)
            tk.Label(role_row, text='Role:', bg=BG, font=('Helvetica', 8),
                     width=10, anchor='e').pack(side='left')
            tk.Label(role_row, text=m.get('role', 'web'), bg=BG,
                     font=('Helvetica', 8), fg='#555').pack(side='left', padx=2)

            conn_row = tk.Frame(self._props_frame, bg=BG)
            conn_row.pack(fill='x', pady=1)
            tk.Label(conn_row, text='Conn:', bg=BG, font=('Helvetica', 8),
                     width=10, anchor='e').pack(side='left')
            tk.Label(conn_row, text=m.get('conn', 'pin'), bg=BG,
                     font=('Helvetica', 8), fg='#555').pack(side='left', padx=2)

            prof = m.get('profile', '')
            if prof:
                tk.Label(self._props_frame, text=f'Profile: {prof}',
                         bg=BG, font=('Helvetica', 8), fg='#1a6bbd').pack(anchor='w', pady=(2, 0))

            if self.results and sm_idx < len(self.results.get('member_res', [])):
                mr = self.results['member_res'][sm_idx]
                frac = self._load_frac()
                N = mr['N'] * frac
                sense = 'T' if N >= 0 else 'C'
                tk.Label(self._props_frame,
                         text=f'N = {self.fmt("force", N, sign=True)} ({sense})',
                         bg=BG, font=('Helvetica', 8, 'bold')).pack(anchor='w', pady=(2, 0))

            tk.Button(self._props_frame, text='Apply', font=('Helvetica', 8),
                      command=self._apply_member_properties).pack(anchor='w', pady=(4, 0))
        else:
            n_nodes = len(self.selected_nodes)
            n_members = len(self.selected_members)
            if n_nodes or n_members:
                parts = []
                if n_nodes:
                    parts.append(f'{n_nodes} node{"s" if n_nodes != 1 else ""}')
                if n_members:
                    parts.append(f'{n_members} member{"s" if n_members != 1 else ""}')
                self._props_label.config(text=f'{" + ".join(parts)} selected')
            else:
                self._props_label.config(text='(select a node or member)')

    def _apply_node_properties(self):
        sn = self.selected_node
        if sn is None or sn >= len(self.nodes):
            return
        try:
            x = self._props_entries['x'].get()
            y = self._props_entries['y'].get()
            z = self._props_entries['z'].get()
        except (tk.TclError, KeyError):
            return
        if not self._guard_nodes('Node position', [sn]):
            return
        self._push_undo('edit node position')
        self.nodes[sn] = (x, y, z)
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _apply_member_properties(self):
        sm_idx = self.selected_member
        if sm_idx is None or sm_idx >= len(self.members):
            return
        if not self._guard_rods('Member properties', [sm_idx]):
            return
        self._push_undo('edit member properties')
        m = self.members[sm_idx]
        for key, var in self._props_entries.items():
            try:
                m[key] = var.get()
            except tk.TclError:
                pass
        self.results = None
        self.member_checks = None
        self._refresh_all()

    def _build_model_tree_panel(self, parent):
        box = tk.LabelFrame(parent, text='Model tree', bg=BG,
                            font=('Helvetica', 10, 'bold'))
        box.pack(fill='x', padx=6, pady=4)
        self._panel_model_tree = box

        self._tree_frame = tk.Frame(box, bg=BG)
        self._tree_frame.pack(fill='x', padx=4, pady=4)

        self._tree_items = {}
        for label_key in ('Nodes', 'Members', 'Supports', 'Loads', 'Profiles'):
            row = tk.Frame(self._tree_frame, bg=BG)
            row.pack(fill='x', pady=1)
            btn = tk.Label(row, text=f'▸ {label_key} (0)', bg=BG,
                           font=('Helvetica', 9), cursor='hand2', anchor='w')
            btn.pack(fill='x')
            detail = tk.Frame(row, bg=BG)
            self._tree_items[label_key] = {'label': btn, 'detail': detail,
                                           'expanded': False}
            btn.bind('<Button-1>', lambda e, k=label_key: self._toggle_tree_section(k))

    def _refresh_model_tree(self):
        for key, item in self._tree_items.items():
            arrow = '▾' if item['expanded'] else '▸'
            count = self._tree_count(key)
            item['label'].config(text=f'{arrow} {key} ({count})')
            if item['expanded']:
                self._populate_tree_detail(key)

    def _populate_tree_detail(self, key):
        detail = self._tree_items[key]['detail']
        for w in detail.winfo_children():
            w.destroy()

        limit = 50
        if key == 'Nodes':
            for i, (x, y, z) in enumerate(self.nodes[:limit]):
                lbl = tk.Label(detail,
                               text=f'{i}: ({x:.2f}, {y:.2f}, {z:.2f})',
                               bg=BG, font=('Helvetica', 8), anchor='w',
                               cursor='hand2')
                lbl.pack(fill='x')
                lbl.bind('<Button-1>', lambda e, ni=i: self._tree_select_node(ni))
            if len(self.nodes) > limit:
                tk.Label(detail, text=f'  ... +{len(self.nodes) - limit} more',
                         bg=BG, font=('Helvetica', 8), fg='#999').pack(anchor='w')

        elif key == 'Members':
            for i, m in enumerate(self.members[:limit]):
                lbl = tk.Label(detail,
                               text=f'{i}: {m["a"]}–{m["b"]} ({m.get("role", "web")})',
                               bg=BG, font=('Helvetica', 8), anchor='w',
                               cursor='hand2')
                lbl.pack(fill='x')
                lbl.bind('<Button-1>', lambda e, mi=i: self._tree_select_member(mi))
            if len(self.members) > limit:
                tk.Label(detail, text=f'  ... +{len(self.members) - limit} more',
                         bg=BG, font=('Helvetica', 8), fg='#999').pack(anchor='w')

        elif key == 'Supports':
            for s in self.supports[:limit]:
                tk.Label(detail,
                         text=f'Node {s["node"]}: {s.get("type", "custom")}',
                         bg=BG, font=('Helvetica', 8), anchor='w').pack(fill='x')

        elif key == 'Loads':
            for ld in self.loads[:limit]:
                tk.Label(detail,
                         text=f'Node {ld["node"]}: ({ld["fx"]:.1f}, {ld["fy"]:.1f}, {ld["fz"]:.1f}) kN',
                         bg=BG, font=('Helvetica', 8), anchor='w').pack(fill='x')

        elif key == 'Profiles':
            for name in sorted(self.profiles):
                tk.Label(detail, text=name, bg=BG, font=('Helvetica', 8),
                         anchor='w').pack(fill='x')

    def _toggle_tree_section(self, key):
        item = self._tree_items[key]
        if item['expanded']:
            item['detail'].pack_forget()
            item['expanded'] = False
        else:
            item['detail'].pack(fill='x', padx=12, pady=(0, 2))
            self._populate_tree_detail(key)
            item['expanded'] = True
        arrow = '▾' if item['expanded'] else '▸'
        count = self._tree_count(key)
        item['label'].config(text=f'{arrow} {key} ({count})')
        self.panel_outer.fit_to_content()

    def _tree_count(self, key):
        if key == 'Nodes':
            return len(self.nodes)
        if key == 'Members':
            return len(self.members)
        if key == 'Supports':
            return len(self.supports)
        if key == 'Loads':
            return len(self.loads)
        if key == 'Profiles':
            return len(self.profiles)
        return 0

    def _tree_select_node(self, i):
        if i >= len(self.nodes):
            return
        self.selected_nodes = {i}
        self.selected_member = None
        self.selected_members = set()
        self._sync_selection_fields()
        self._update_properties_panel()
        self._center_on_node(i)

    def _tree_select_member(self, i):
        if i >= len(self.members):
            return
        self.selected_nodes = set()
        self.selected_member = i
        self.selected_members = {i}
        self._sync_selection_fields()
        self._update_properties_panel()
        m = self.members[i]
        mid_node = m['a']
        if mid_node < len(self.nodes):
            self._center_on_node(mid_node)

    def _center_on_node(self, i):
        if i >= len(self.nodes):
            return
        # Through _center_on_point, which does the sum _draw does. This used
        # to set the pan to minus the node's projected position, ignoring
        # both the model's centre and the zoom, so "centre on node" put the
        # node somewhere else -- often off the canvas.
        self._center_on_point(*self.nodes[i])
        self._draw()
