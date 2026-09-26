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
  stereo_app_canvas_geom.py   screen-space geometry (hit test, clip,
                              Voronoi)
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
    _point_segment_distance, _clip_polygon_to_bbox, _voronoi_cells_2d,
)
from apps.stereo.stereo_app_panels import StereoPanelsMixin
from apps.stereo.stereo_app_model import StereoModelMixin
from apps.stereo.stereo_app_view import StereoViewMixin
from apps.stereo.stereo_app_render import StereoRenderMixin
from apps.stereo.stereo_app_module_editor import StereoModuleEditorMixin
from apps.stereo.stereo_app_wizard import StereoWizardMixin
from apps.stereo.stereo_app_addons import StereoAddonsMixin
from apps.stereo.stereo_app_reports import StereoReportsMixin


class StereoApp(StereoPanelsMixin, StereoModelMixin, StereoViewMixin,
                StereoRenderMixin, StereoModuleEditorMixin,
                StereoWizardMixin, StereoAddonsMixin, StereoReportsMixin,
                UnitsMixin):
    """The Stereo tab.

    Holds the model (nodes, members, supports, loads), every Tk variable
    the panels bind to, and the undo stack. All behaviour is contributed
    by the mixins listed above -- each one documented in its own module --
    so this class body stays small enough to read in one screen.
    """
    STORAGE_UNITS = units.storage_like('stereo storage', stress=units.MPA)

    def __init__(self, root):
        self.root = root
        self.nodes = []
        self.members = []
        self.loads = []
        self.supports = []
        self.results = None
        self.member_checks = None
        self.err = None
        self.selected_nodes = set()
        self.selected_member = None
        self.selected_members = set()
        self._support_candidates = []
        self._load_nodes = {}
        self._load_glyphs = {}
        self._disabled_supports = set()
        self._load_path_phase = 0
        self._load_path_after_id = None
        self._add_rod_first = None   # first-picked node while 'Add rod' mode is on
        self._axis_pending = None    # (dx, dy, dz) while axis-extend is active
        self._shaded_cells = None    # lazy cache, see _get_shaded_cells
        # The 3D Voronoi tessellation is expensive to build and independent
        # of the camera, so it is cached against everything it really depends
        # on (geometry, domain, view, slice) and reused while orbiting.
        self._voronoi_cache = None
        self._voronoi_note = ''
        self._voronoi_cut_last = 1.0   # last section thickness that was a real length
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

        self._build_ui()
        self.init_units(repaint=self._on_units_changed)
        self._generate(push_undo=False)

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
                'loads': copy.deepcopy(self.loads), 'supports': copy.deepcopy(self.supports)}

    def _restore_snapshot(self, snap):
        self.nodes = snap['nodes']
        self.members = snap['members']
        self.loads = snap['loads']
        self.supports = snap['supports']
        self.results = None
        self.member_checks = None

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
