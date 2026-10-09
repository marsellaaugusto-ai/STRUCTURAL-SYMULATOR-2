"""Stereo tab -- Tkinter UI for the 3D space-structure calculator.

This module is the PUBLIC FACADE of the Stereo tab: it assembles the
StereoApp class from the mixins below and re-exports the constants and
colour functions other modules and the tests import. `from
apps.stereo.stereo_app import StereoApp` keeps working exactly as before.

One interface over every geometry typology stereo_geometry.py can build
(flat double-layer grid, vault, dome, bridge...), full CIRSOC-checked 3D
direct-stiffness analysis (stereo_math.py), and Excel/report export
(stereo_reports.py) -- the same "geometry generator + analysis + CIRSOC
checks + report/Excel export" pipeline the Truss tab has, generalized to
3D.

The implementation is split one concern per file, so no file runs to
thousands of lines and the name says what is inside:

  stereo_app_constants.py     shared colours, sizes and label tables
  stereo_app_colors.py        the four colour spectra, as pure functions
  stereo_app_canvas_geom.py   screen-space geometry (hit test, clipping)
  stereo_app_panels.py        toolbar, canvas and sidebar panel layout
  stereo_app_model.py         generate / support / load / analyze commands
  stereo_app_view.py          camera, projection, picking, rod tool
  stereo_app_render.py        the 3D drawing pipeline and its legend
  stereo_app_module_editor.py the Module Editor panel and its two views
  stereo_app_wizard.py        the Custom Surface Wizard dialog
  stereo_app_addons.py        column and reinforcement-beam commands
  stereo_app_reports.py       refresh cycle, member report, Excel I/O

Only this file holds StereoApp's own state: __init__ (which creates every
Tk variable the panels bind to) and the undo/redo snapshot stack. A mixin
never defines __init__, so there is exactly one place to look for what
state exists.

Boundary conditions are the one area explicitly asked to be bug-free and
unrestricted: every node's six DOFs (ux,uy,uz,rx,ry,rz) can be restrained
in ANY combination, independent of the quick presets this UI also offers
as a shortcut -- see `_apply_support` in stereo_app_model.py and
`stereo_math.support_restraints`.

Structured after apps/truss/truss_app.py (a plain object mixing in
UnitsMixin, built directly into the tab Frame main.py hands it) and using
common.ScrollPanel/FlowBar for the sidebar and toolbar, exactly like every
other tab, per the 2026-09-12 request that this tab's left panel and
legibility match "the standard of the others" instead of its own
hand-rolled layout.

The 3D view is orbited/panned/zoomed with the MOUSE ONLY (right-drag orbit,
wheel zoom, middle-drag pan) -- there is deliberately no toolbar button for
any of the three, per that same request. Left-drag is reserved for a
Truss-style rubber-band LASSO that multi-selects nodes (a plain left-click
still single-selects), per the 2026-09-12 request to select supports "with
a laso function like in the truss app".
"""
import copy
import tkinter as tk
# Re-exported so `apps.stereo.stereo_app.messagebox` / `.filedialog` stay
# patchable from the tests, which is how every dialog in the tab is kept
# from opening a real modal window during a test run. Patching an
# attribute on these module objects reaches the mixins too -- they hold a
# reference to the same tkinter module, not a copy of its functions.
from tkinter import messagebox, filedialog   # noqa: F401

import units
from common import UnitsMixin

from apps.stereo.stereo_app_constants import *          # noqa: F401,F403
from apps.stereo.stereo_app_constants import FAMILY_LABEL, UNDO_LIMIT
from apps.stereo.stereo_app_colors import (             # noqa: F401
    _lerp_hex, force_color, deform_color, util_color, moment_color,
    reaction_moment_signed,
)
from apps.stereo.stereo_app_canvas_geom import (        # noqa: F401
    _point_segment_distance,
)
from apps.stereo.stereo_app_shell import StereoShellMixin
from apps.stereo.stereo_app_panels import StereoPanelsMixin
from apps.stereo.stereo_app_model import StereoModelMixin
from apps.stereo.stereo_app_view import StereoViewMixin
from apps.stereo.stereo_app_render import StereoRenderMixin
from apps.stereo.stereo_app_module_editor import StereoModuleEditorMixin
from apps.stereo.stereo_app_wizard import StereoWizardMixin
from apps.stereo.stereo_app_addons import StereoAddonsMixin
from apps.stereo.stereo_app_reports import StereoReportsMixin
from apps.stereo.stereo_app_inspector import StereoInspectorMixin
from apps.stereo.stereo_app_groups import StereoGroupsMixin
from apps.stereo.stereo_app_scene import StereoSceneMixin
from apps.stereo.stereo_app_objectmenu import StereoObjectMenuMixin
from apps.stereo.stereo_app_roles import StereoRolesMixin
from apps.stereo.stereo_app_marks import StereoMarksMixin
from apps.stereo.stereo_app_components import StereoComponentsMixin
from apps.stereo.stereo_app_groupview import StereoGroupViewMixin
from apps.stereo.stereo_app_compare import StereoCompareMixin
from apps.stereo.stereo_app_transform import StereoTransformMixin
from apps.stereo.stereo_app_clipboard import StereoClipboardMixin
from apps.stereo.stereo_app_mechanism import StereoMechanismMixin
from apps.stereo.stereo_app_playload import StereoPlayLoadMixin
from apps.stereo.stereo_app_buckling import StereoBucklingMixin
from apps.stereo.stereo_reports import STORAGE_UNITS as sr_storage_units


class StereoApp(StereoShellMixin, StereoPanelsMixin, StereoModelMixin, StereoViewMixin,
                StereoRenderMixin, StereoModuleEditorMixin,
                StereoWizardMixin, StereoAddonsMixin, StereoReportsMixin,
                StereoInspectorMixin, StereoGroupsMixin, StereoGroupViewMixin,
                StereoSceneMixin, StereoObjectMenuMixin, StereoRolesMixin,
                StereoMarksMixin, StereoComponentsMixin,
                StereoCompareMixin,
                StereoTransformMixin,
                StereoClipboardMixin, StereoMechanismMixin,
                StereoPlayLoadMixin, StereoBucklingMixin, UnitsMixin):
    """The Stereo tab.

    Holds the model (nodes, members, supports, loads), every Tk variable
    the panels bind to, and the undo stack. All behaviour is contributed
    by the mixins listed above -- each one documented in its own module --
    so this class body stays small enough to read in one screen.
    """
    # Declared in stereo_reports, and imported rather than repeated, so
    # the tab and the report it writes cannot disagree about what the
    # numbers in a member dict mean.
    STORAGE_UNITS = sr_storage_units

    @property
    def document_name(self):
        """What the window title names: the workbook this model came from
        (or the example, the merge, the variant), None for a model built
        here -- "Stereo drawing"."""
        return getattr(self, '_model_label', None)

    def __init__(self, root):
        self.root = root
        self.nodes = []
        self.members = []
        self.loads = []
        self.member_loads = []
        self._bz_profile = None    # the fitted, then edited, Bezier chain
        self._bz_grid = None       # or the fitted patch's control heights
        self._bz_drag = None       # the control currently being dragged
        self.panels = []
        self.panel_checks = []
        self._line_pick_first = None
        self._disc_hits = []
        self._disc_centre = None
        self.supports = []
        # What the current model is CALLED, when it has a name of its own:
        # an example's title, an imported file, a loaded variant. None means
        # the model came from the generator panel, so the Grid Family
        # dropdown names it. Exports read this through _model_name() --
        # they used to read the dropdown directly, which meant loading the
        # Schwedler dome example and exporting produced a report whose
        # title block said "Flat double-layer grid".
        self._model_label = None
        self.profiles = {'Default chord': {'E': 200.0, 'A': 20.0, 'I': 400.0,
                                           'J': 400.0, 'Fy': 235.0, 'Fu': 360.0,
                                           'r_gyr': 4.0, 'K': 1.0},
                         'Default web':   {'E': 200.0, 'A': 20.0, 'I': 400.0,
                                           'J': 400.0, 'Fy': 235.0, 'Fu': 360.0,
                                           'r_gyr': 4.0, 'K': 1.0}}
        self.active_profile = tk.StringVar(value='Default chord')
        self.results = None
        self.member_checks = None
        self.err = None
        self.selected_nodes = set()
        self.selected_member = None
        self.selected_members = set()
        self._support_candidates = []
        # Supports the columns took over, kept so clearing them hands them
        # back. A crane takes none: it is a lift calculation.
        self._column_freed = []
        # each crane's lift settings (stereo_lift_calc)
        self._crane_lifts = []
        # the last copy, and a paste waiting for the click that places it
        self._clip = None
        self._paste_pending = None
        self._paste_opts = None
        # Named branches of the model (roadmap 4.1). A list of dicts whose
        # shape and rules stereo_groups documents; empty means everything is
        # Ungrouped, which is a real state rather than a missing one.
        self.groups = []
        self._group_sel = None
        # The group open for editing, or None. Every group is locked; this
        # is the one piece of state the lock needs (see stereo_groups).
        self._group_editing = None
        self._group_edit_stack = []
        # (rod index, caption) of the rod a "Show me this rod" action is
        # pointing at, or None. Drawn only over a live solve: the claim it
        # makes ("this rod governs") is a claim about THAT solve.
        self._flagged_rod = None
        # Grouped / Ungrouped mode -- see _build_groups_panel. A view of the
        # model; the locks apply either way.
        self.group_view = tk.BooleanVar(value=False)
        # The current group made visible: the bar over the view, the
        # highlight, Group # labels, Pick inside group, hidden groups.
        self._init_group_view_state()
        # Roles: the axis that cuts across the group tree (stereo_roles).
        self._init_roles_state()
        self._init_marks_state()
        # Rotate / mirror (roadmap 3.4): the active axis, set by the arrow
        # keys and the panel's radio buttons alike, and where the mirror
        # plane sits.
        self.tx_axis = tk.StringVar(value='Z')
        self.tx_plane = tk.StringVar(value='auto')
        self._load_nodes = {}
        self._load_glyphs = {}
        self._disabled_supports = set()
        self._load_path_phase = 0
        self._load_path_after_id = None
        self._add_rod_first = None   # first-picked node while 'Add rod' mode is on
        self._axis_pending = None    # (dx, dy, dz) while axis-extend is active
        self._snap_node = None       # nearest node index under cursor, or None
        self._snap_midpoint = None   # (sx, sy, x, y, z, member_idx) of nearest midpoint, or None
        self._cursor_world = None    # (x, y, z) world coords under cursor
        self._shaded_cells = None    # lazy cache, see _get_shaded_cells
        # (cache slot kept free for any future expensive overlay)
        # of the camera, so it is cached against everything it really depends
        # on (geometry, domain, view, slice) and reused while orbiting.
        self._wizard_recipe = None     # the Custom Surface Wizard settings
                                        # behind the model now loaded, if any

        self.azimuth = 35.0
        self.elevation = 22.0
        self._orbit_start = None
        self._orbit_dragged = False
        self._lasso_press = None
        self._lasso_dragging = False
        self._lasso_cur = None
        self._drag_node = None          # (start_sx, start_sy) while dragging node(s)
        self._drag_node_active = False  # True once threshold exceeded

        self.grid_family = tk.StringVar(value=FAMILY_LABEL['flat_grid'])

        self._undo_stack = []
        self._redo_stack = []

        # Module Editor state -- see _build_module_editor_panel. Cells/
        # roles are recomputed only on a real topology change (a fresh
        # generate, or one of this editor's own edits), not on every
        # _refresh_all (find_cells is O(members * degree^2); most
        # _refresh_all calls -- a colour toggle, a load edit -- touch
        # neither nodes nor members and would make that work for nothing).
        self._me_cells = []
        self._me_roles = {}
        # The grid's theoretical module, frozen by _me_capture_base_module
        # the moment a mesh is generated and shown as the reference the list
        # opens on -- see that method for why it is not re-derived.
        self._me_base = None
        self._me_role_id = 0
        self._me_selection = None   # ('node', position) or ('edge', (pos_a, pos_b))
        self._me_locked_edges = set()   # {(role_id, min(pos_a,pos_b), max(pos_a,pos_b))}
        self._me_drag = None

        self._variants = []

        # Which groups of sheets the PDF report carries. None means all of
        # them; the sheet chooser writes the reader's last choice back here
        # so a second export does not have to be configured again.
        self._pdf_groups = None
        # the cover sheet (item 8): on or off, and what it says
        self._pdf_cover = False
        self.project_info = {}

        self._build_ui()
        self.init_units(repaint=self._on_units_changed)
        self.unit_var(self.unit_weight_var, 'unit_weight', digits=4)
        self.unit_label(self._self_weight_check,
                        lambda: 'Include self-weight, unit wt (%s):'
                        % self.u('unit_weight'))
        # The app opens EMPTY. It used to generate a flat grid here, which
        # meant every session started by deleting someone else's model
        # before building your own -- and made "what am I looking at?" the
        # first question rather than the last. Generate and Shape are one
        # click away; a model you did not ask for is not.
        self._clear_model(push_undo=False)

    @property
    def selected_node(self):
        """The single selected node, for the many single-node code paths
        (the selection panel, the typed node fields' auto-sync) that
        predate multi-select -- None whenever zero or more than one node
        is selected, since neither has one unambiguous "the" node.
        `selected_nodes` (a set) is the real, multi-select-capable state;
        this is a read-only convenience view over it."""
        if len(self.selected_nodes) == 1:
            return next(iter(self.selected_nodes))
        return None

    # ── model snapshot / undo-redo (same shape as truss_app.py) ─────────────
    def _model_snapshot(self):
        return {'nodes': copy.deepcopy(self.nodes), 'members': copy.deepcopy(self.members),
                'loads': copy.deepcopy(self.loads), 'supports': copy.deepcopy(self.supports),
                'profiles': copy.deepcopy(self.profiles),
                'panels': copy.deepcopy(self.panels),
                'member_loads': copy.deepcopy(self.member_loads),
                # The Bezier profile is model state, not panel state: it is
                # what the mesh was built FROM, and every drag of a handle
                # is a model change. Leaving it out made undo restore the
                # nodes while the curve that produced them kept the edit --
                # so the next Build silently undid the undo.
                'bz_profile': copy.deepcopy(self._bz_profile),
                'bz_grid': copy.deepcopy(self._bz_grid),
                # Groups hold MEMBER INDICES, so they are model state in the
                # same way the rods are. Left out, undoing a rod delete put
                # the rod back while every group stayed remapped around its
                # absence -- each branch then meant the wrong rods.
                'groups': copy.deepcopy(self.groups),
                # What the columns took off the ground, to hand back on
                # Clear, and each crane's lift settings: left out, an undone
                # column kept its list of freed supports and the next Clear
                # handed back supports the model no longer had reason to.
                'column_freed': copy.deepcopy(getattr(self, '_column_freed', [])),
                'crane_lifts': copy.deepcopy(getattr(self, '_crane_lifts', [])),
                'project_info': dict(getattr(self, 'project_info', None) or {})}

    def _restore_snapshot(self, snap):
        self.nodes = snap['nodes']
        self.members = snap['members']
        self.loads = snap['loads']
        self.supports = snap['supports']
        self.profiles = snap.get('profiles', self.profiles)
        self.panels = snap.get('panels', [])
        self.member_loads = snap.get('member_loads', [])
        self._bz_profile = copy.deepcopy(snap.get('bz_profile'))
        self._bz_grid = copy.deepcopy(snap.get('bz_grid'))
        self._bz_drag = None
        self.groups = snap.get('groups', [])
        self._column_freed = copy.deepcopy(snap.get('column_freed', []))
        self._crane_lifts = copy.deepcopy(snap.get('crane_lifts', []))
        self.project_info = dict(snap.get('project_info') or {})
        self.results = None
        self.member_checks = None
        self.panel_checks = []
        # The SELECTION is not part of the snapshot, and an undo can restore
        # a smaller model than the one the selection was made in: add a
        # column, whose last act is to select its new feet, then undo, and
        # those indices point past the end of the node list. The very next
        # selection sync then raises IndexError, which is a crash rather
        # than a wrong answer. Drop whatever no longer exists.
        # A rod load is a member index, so it needs the same clamp for the
        # same reason: an undo can restore a shorter member list, and a
        # stale index would silently load a different rod.
        nm = len(self.members)
        self.member_loads = [ld for ld in self.member_loads if 0 <= ld['member'] < nm]
        n = len(self.nodes)
        self.selected_nodes = {i for i in self.selected_nodes if i < n}
        if self.selected_member is not None and \
                self.selected_member >= len(self.members):
            self.selected_member = None
        self._disabled_supports = {i for i in self._disabled_supports if i < n}
        self._add_rod_first = (self._add_rod_first
                               if (self._add_rod_first or 0) < n else None)
        self.selected_members = {i for i in self.selected_members if i < nm}
        if hasattr(self, '_editing_gid'):
            self._editing_gid()          # closes an edit whose group is gone
            self._refresh_group_edit_controls()
        if hasattr(self, '_refresh_group_list'):
            self._refresh_group_list()

    def _push_undo(self, label=''):
        self._undo_stack.append((label, self._model_snapshot()))
        if len(self._undo_stack) > UNDO_LIMIT:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self):
        if not self._undo_stack:
            return
        _, snap = self._undo_stack.pop()
        self._redo_stack.append(('redo', self._model_snapshot()))
        self._restore_snapshot(snap)
        self._refresh_all()

    def _redo(self):
        if not self._redo_stack:
            return
        _, snap = self._redo_stack.pop()
        self._undo_stack.append(('undo', self._model_snapshot()))
        self._restore_snapshot(snap)
        self._refresh_all()
