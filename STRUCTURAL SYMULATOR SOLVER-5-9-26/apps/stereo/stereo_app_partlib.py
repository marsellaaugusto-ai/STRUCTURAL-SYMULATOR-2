"""The part library in the interface: save a part, place it again.

See stereo_partlib for what a part file is and why placing one is a
merge. This file is the two verbs and the one thing they must say out
loud: where the part landed and what happened at the seam, because a
part placed touching the structure is BOLTED to it, and a joint nobody
meant is as bad as a joint nobody drew.
"""
import os
import tkinter as tk
from tkinter import filedialog, messagebox

from apps.stereo import stereo_groups as sgp
from apps.stereo import stereo_merge as smg
from apps.stereo import stereo_partlib as spl


class StereoPartLibMixin:
    """Save a group as a part file, and place one back."""

    def _part_save(self, gid=False):
        """Write the picked group out as a part someone can place again."""
        if gid is False:
            gid = self._current_group()
        g = sgp.find(self.groups, gid) if gid not in (False, None) else None
        if g is None:
            messagebox.showinfo('Save as a part',
                                'Pick a group to save as a part.')
            return None
        rods = sorted(sgp.rods_of(self.groups, gid, deep=True))
        if not rods:
            messagebox.showinfo('Save as a part',
                                '%s holds no rods, so there is nothing to '
                                'save.' % self._group_display_name(gid))
            return None
        try:
            part = spl.make_part(self.nodes, self.members, rods,
                                 self._group_display_name(gid),
                                 self.profiles, self._mark_tol_mm())
        except spl.PartError as exc:
            messagebox.showerror('Save as a part', str(exc))
            return None
        path = filedialog.asksaveasfilename(
            title='Save as a part',
            defaultextension=spl.SUFFIX,
            initialfile=_filename(part['name']),
            filetypes=[('Stereo part', '*' + spl.SUFFIX)])
        if not path:
            return None
        try:
            spl.save_part(part, path)
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror('Save as a part', str(exc))
            return None
        self._set_status('%s saved as a part: %d rod(s), %.2f m.'
                         % (part['name'], part['n_rods'], part['length_m']),
                         'ok')
        return path

    def _part_place(self, path=None, at=None):
        """Read a part file and merge it into this model.

        Its anchor node lands on the selected node, or at the origin when
        nothing is selected -- stated before it happens, because a part
        that appears somewhere unexpected in a big model is hard to find
        and easy to leave behind.
        """
        if path is None:
            path = filedialog.askopenfilename(
                title='Place a part',
                filetypes=[('Stereo part', '*' + spl.SUFFIX)])
        if not path:
            return None
        try:
            part = spl.load_part(path)
        except spl.PartError as exc:
            messagebox.showerror('Place a part', str(exc))
            return None

        if at is None:
            at = self._part_landing()
        dx, dy, dz = spl.size(part)
        if not messagebox.askyesno(
                'Place a part',
                '%s\n\n%d rod(s), %.2f m of steel, %.0f kg.\n'
                'It is %.2f x %.2f x %.2f m, and its corner joint lands '
                'at (%.2f, %.2f, %.2f).\n\n'
                'Rod ends that meet the structure become one joint with '
                'it -- a part placed touching the model is bolted to it, '
                'not floating beside it.\n\nPlace it?'
                % (part['name'], part['n_rods'], part['length_m'],
                   part['mass_kg'], dx, dy, dz, at[0], at[1], at[2])):
            return None

        base = {'nodes': list(self.nodes), 'members': list(self.members),
                'loads': list(self.loads), 'supports': list(self.supports),
                'groups': [dict(g, members=set(g['members']))
                           for g in self.groups],
                'profiles': dict(self.profiles)}
        n_before = len(base['members'])
        try:
            merged, rep = smg.merge_models(base, spl.as_model(part, at),
                                           label=part['name'])
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror('Place a part',
                                 '%s\n\nThe model was not changed.' % exc)
            return None

        self._push_undo('place a part')
        self.nodes, self.members = merged['nodes'], merged['members']
        self.loads, self.supports = merged['loads'], merged['supports']
        self.profiles = merged['profiles']
        # _drop_groups clears the tree's state as well as the list, which
        # is what makes the placed group's row land open rather than
        # inheriting whether some unrelated group was collapsed.
        self._drop_groups()
        self.groups = merged['groups']
        self._refresh_group_list()
        self._support_candidates = [s['node'] for s in self.supports]
        self.results = None
        self.member_checks = None
        self.selected_nodes = set()
        self.selected_member = None
        self.selected_members = set(range(n_before, len(self.members)))
        self._refresh_profile_combo()
        self._refresh_all()
        messagebox.showinfo(
            'Place a part',
            '%s placed.\n\n%s\n\nIts rods are selected.'
            % (part['name'],
               '\n'.join(smg.describe(rep, n_before, part['n_rods']))))
        return part

    def _part_landing(self):
        """Where a placed part's low corner goes: the selected node, or
        the origin. One selected node is a deliberate "put it here"; a
        lassoed dozen is not, so only one counts."""
        if len(self.selected_nodes) == 1:
            i = next(iter(self.selected_nodes))
            if 0 <= i < len(self.nodes):
                return tuple(self.nodes[i])
        return (0.0, 0.0, 0.0)


def _filename(name):
    """A part's name as something every filesystem will take."""
    safe = ''.join(c if (c.isalnum() or c in ' -_') else '_'
                   for c in str(name)).strip() or 'part'
    return safe + spl.SUFFIX
