"""The Stereo tab's use of the scene graph (apps/stereo/scene/).

What the tab gains, and what it does NOT change.

  GAINS. The model's structure now travels in the workbook as a Scene sheet
  beside the Model sheet, so nesting, each group's own frame and the named
  joints that carry supports and loads survive a round trip. A model can be
  saved and opened as a scene file of its own. And "Repeated parts" answers
  a question the flat model cannot be asked at all: which groups are the
  SAME PART, built more than once.

  UNCHANGED. The flat `(nodes, members, groups)` triple is still the model.
  Nothing here edits it, no group operation is rerouted, and with no Scene
  sheet in a workbook every path behaves exactly as before. This is the
  read side of the migration; the write side (group edits as graph
  operations) is deliberately a separate step, because rerouting the lock
  rules and the move plans is a change to behaviour, and this one is not.

The status bar is the shell's own `_set_status(text, kind)` -- NOT redefined
here. An earlier draft of this module had its own, which the shell's shadowed
because StereoShellMixin comes first in the MRO: harmless that day, and a
trap the day the order changed, when this one would have silently replaced
the real status bar and stopped colouring it.

THE DOCUMENT IS DERIVED, NEVER MIRRORED. `_scene_document()` builds a fresh
graph from the current model every time it is asked. `self.groups` is
assigned in eleven places across five modules -- import, merge, paste, undo,
example load, generate, the group panel -- and a stored document kept in
step with all eleven would be wrong the first time one was missed, and wrong
SILENTLY, because a stale graph still bakes. Building it on demand cannot go
stale. Models here are thousands of rods, not millions, and the conversion
is a few milliseconds.
"""
import os
import tkinter as tk
from tkinter import filedialog, messagebox

from apps.stereo import stereo_scene_bridge as sbr
from apps.stereo.stereo_app_shell import HINT_FG


class StereoSceneMixin:
    """Scene-graph services for the Stereo tab."""

    # ── the document ───────────────────────────────────────────────────────

    def _scene_document(self, localize=True):
        """The current model as a SceneDocument. Built fresh; never stored."""
        return sbr.graph_from_model(
            self.nodes, self.members, self.groups,
            supports=self.supports, loads=self._all_loads(),
            name=self._model_name(), localize=localize,
            meta={'source': self._model_label or 'Stereo drawing'})

    def _scene_for_export(self):
        """The document an export carries, or None if it cannot be built.

        An export must not fail because of this: the workbook's own sheets
        are the deliverable, and a Scene sheet is an addition to them. So a
        conversion that raises costs the sheet and says so in the status
        bar, rather than losing the user the export they asked for.
        """
        try:
            return self._scene_document()
        except Exception as exc:                      # noqa: BLE001
            self._set_status('Exported without the Scene sheet: %s' % exc,
                             kind='error')
            return None

    # ── the Scene sheet, on the way in ─────────────────────────────────────

    def _groups_from_scene_sheet(self, path, members):
        """The workbook's Scene sheet as groups for `members`, or None.

        None covers every ordinary reason there is nothing to read -- no
        Scene sheet, an older workbook, openpyxl missing -- so the caller
        falls back to the Groups sheet exactly as it did before.

        Rods are matched by the index they were converted FROM
        (`stereo_scene_bridge.MEMBER_INDEX_KEY`), not by position: a bake
        orders members by tree position, so matching by position would
        attach every group to the wrong rods while looking plausible. A
        workbook whose two sheets disagree about how many rods there are is
        one someone has edited by hand, and it is refused rather than
        half-applied.
        """
        try:
            from apps.stereo.scene import read_scene_sheet
            doc, warnings, _ = read_scene_sheet(path)
        except Exception:                             # noqa: BLE001
            return None
        baked = doc.bake()
        if len(baked.members) != len(members):
            return None
        groups = baked.legacy_groups(doc.root)
        src = [m.get(sbr.MEMBER_INDEX_KEY) for m in baked.members]
        if any(i is None for i in src) or sorted(src) != list(range(len(members))):
            return None
        for g in groups:
            g['members'] = {src[i] for i in g['members']}
        # A group that ends up holding nothing is one whose rods all went to
        # its subgroups; it is still a real branch of the tree, so it stays.
        if warnings:
            self._set_status('Scene sheet read with %d note(s): %s'
                             % (len(warnings), warnings[0]), kind='error')
        return groups

    # ── a scene file of its own ────────────────────────────────────────────

    def _save_scene_file(self):
        from apps.stereo.scene import SUFFIX, save_json
        if not self.members:
            messagebox.showinfo('Save scene', 'There is no model to save.')
            return
        path = filedialog.asksaveasfilename(
            defaultextension=SUFFIX,
            filetypes=[('Scene file', '*' + SUFFIX), ('All files', '*.*')])
        if not path:
            return
        try:
            save_json(self._scene_document(), path)
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror('Save scene', str(exc))
            return
        self._set_status('Scene saved to %s' % os.path.basename(path),
                         kind='ok')

    def _open_scene_file(self):
        from apps.stereo.scene import SUFFIX, load_json
        path = filedialog.askopenfilename(
            filetypes=[('Scene file', '*' + SUFFIX), ('All files', '*.*')])
        if not path:
            return
        try:
            doc, warnings, _ = load_json(path)
            nodes, members, groups, remap = sbr.model_from_graph(doc)
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror('Open scene', str(exc))
            return
        if not members:
            messagebox.showerror('Open scene', 'That scene holds no rods.')
            return
        self._push_undo('open scene')
        self._model_label = os.path.basename(path)
        self.nodes, self.members = nodes, members
        # The supports and loads the scene carried come back on the joints
        # they were saved against -- with their own kind, not as pins: a
        # roller read back as a pin removes a degree of freedom nobody
        # removed, and still analyses.
        self.supports, self.loads = sbr.anchors_from_graph(
            doc, remap.get('baked'))
        assumed = [s for s in self.supports if s.pop('assumed', False)]
        self._drop_groups()
        self.groups = groups
        self.results = None
        self.member_checks = None
        self.selected_nodes = set()
        self.selected_member = None
        self.selected_members = set()
        self._support_candidates = [s['node'] for s in self.supports]
        self._refresh_group_list()
        self._refresh_all()
        notes = list(warnings) + list(remap['warnings'])
        if assumed:
            notes.append('%d support(s) in that file carried no restraint '
                         'type and were read as pins' % len(assumed))
        if notes:
            messagebox.showwarning(
                'Opened with notes',
                'The scene opened, with %d thing(s) to know about:\n\n  %s'
                % (len(notes), '\n  '.join(notes[:8])))
        self._set_status('Scene opened: %d rods, %d groups'
                         % (len(members), len(groups)), kind='ok')

    # ── what the flat model could not be asked ─────────────────────────────

    def _group_repeated_parts(self):
        """Which groups are the same part, built more than once.

        A flat model has no way to say it, so nobody could ask. Two
        identical trusses are two sets of rods, and the only thing that
        knows they are one fabricated part is whoever drew them.
        """
        if not self.groups:
            messagebox.showinfo('Repeated parts', 'No groups yet.')
            return
        try:
            found = sbr.instanceable_groups(self._scene_document())
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror('Repeated parts', str(exc))
            return

        win = tk.Toplevel(self.root)
        win.title('Repeated parts')
        win.transient(self.root)
        tk.Label(win, text='Groups that are the same part',
                 font=('', 12, 'bold')).pack(pady=(12, 2))
        tk.Label(win, text='Compared by shape alone -- same rods, same '
                           'lengths, same arrangement -- not by name, and '
                           'not by where they sit. A part listed twice is '
                           'fabricated once and installed twice, so it is '
                           'sized for the WORST of its copies, never for '
                           'whichever one is selected.',
                 fg=HINT_FG, justify='left', wraplength=520,
                 font=('Helvetica', 8)).pack(anchor='w', padx=14)
        rows = sorted(found.values(), key=lambda v: (-len(v), v[0].name))
        txt = tk.Text(win, width=72,
                      height=min(22, max(6, sum(len(v) for v in rows) + 3)),
                      font=('Courier', 8), wrap='none')
        txt.pack(fill='both', expand=True, padx=14, pady=(6, 4))
        if not rows:
            txt.insert('end', 'Every group is a different part.\n')
        for n, same in enumerate(rows, 1):
            rods = sum(1 for o in same[0].walk() if o.KIND == 'rod')
            txt.insert('end', 'Part %d -- %d copies, %d rods each\n'
                       % (n, len(same), rods))
            for obj in same:
                txt.insert('end', '    %s\n' % (obj.name or '(unnamed)'))
            txt.insert('end', '\n')
        txt.configure(state='disabled')
        tk.Button(win, text='Close', command=win.destroy).pack(pady=(0, 10))

    def _scene_self_check(self):
        """Convert the model to a graph and back, and report any difference.

        The migration's safety net: both paths run on the same model and are
        held to agreeing, rather than the old one being replaced on the
        strength of an argument.
        """
        problems = sbr.compare_round_trip(
            self.nodes, self.members, self.groups,
            self.supports, self._all_loads())
        if not problems:
            messagebox.showinfo(
                'Scene check',
                'The model survives a round trip through the scene graph '
                'exactly:\n\n%d rods, %d groups, %d supports -- every rod in '
                'the same place, with the same section, in the same group.'
                % (len(self.members), len(self.groups), len(self.supports)))
        else:
            messagebox.showerror(
                'Scene check',
                'The round trip changed %d thing(s):\n\n  %s'
                % (len(problems), '\n  '.join(problems[:10])))
        return problems
