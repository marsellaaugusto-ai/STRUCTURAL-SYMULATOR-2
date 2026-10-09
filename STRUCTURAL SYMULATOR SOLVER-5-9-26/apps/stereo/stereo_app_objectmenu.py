"""Right-click on the canvas: the object's own verbs, where the object is.

Why this exists. Everything a group can have done to it used to live in a
panel on the far side of the window -- a list to pick a row in, then a
button or a sub-menu to press. The object you were looking at and the
controls that acted on it were never in the same place, so every operation
cost a journey across the screen and a check that the right row was still
highlighted.

Right-click used to OPEN the group under the pointer. That is one useful
verb out of eight, bound to the gesture every other program uses for "show
me what I can do with this". Opening now has a menu entry of its own (and
a double-click, from stage 1), and the gesture does what it does elsewhere.

The menu is built from WHAT IS UNDER THE POINTER, read through the same
`stereo_groups.object_at` the click and the lock rules use, so it can never
offer a verb the rest of the tab would refuse.
"""
import tkinter as tk

from apps.stereo import stereo_groups as sgp


class StereoObjectMenuMixin:
    """The canvas's own context menu."""

    def _object_menu_at(self, ex, ey):
        """Build and post the menu for whatever is at (ex, ey)."""
        menu = tk.Menu(self.canvas, tearoff=False)
        editing = self._editing_gid()
        rod = self._select_member_at(ex, ey, allowed=self._pick_filter()[1])
        gid = self._group_object_for_rod(rod) if rod is not None else None
        owner = (sgp.owner_of_rod(self.groups).get(rod)
                 if rod is not None and self.groups else None)

        if gid is not None:
            name = self._group_display_name(gid)
            menu.add_command(label='Enter %s' % name,
                             command=lambda g=gid: self._menu_enter(g))
            menu.add_command(label='Select it',
                             command=lambda g=gid: self._menu_select(g))
            menu.add_separator()
            menu.add_command(label='Rename…',
                             command=lambda g=gid: self._menu_on(g, self._group_rename))
            menu.add_command(label='Hide it',
                             command=lambda g=gid: self._menu_hide(g))
            menu.add_separator()
            menu.add_command(label='Explode (keep the rods)',
                             command=lambda g=gid: self._menu_on(g, self._group_explode))
            menu.add_command(label='Delete it and its rods',
                             command=lambda g=gid: self._group_delete_object(g))
        elif rod is not None:
            # A loose rod, or one of the open group's own.
            where = ('in %s' % self._group_display_name(owner)) if owner \
                is not None else 'Ungrouped'
            menu.add_command(label='Rod %d — %s' % (rod, where), state='disabled')
            menu.add_separator()
            if self.selected_members or self.selected_nodes:
                menu.add_command(label='New group from the selection',
                                 command=self._group_new_from_selection)
            if owner is not None:
                menu.add_command(
                    label='Take it out of %s' % self._group_display_name(owner),
                    command=lambda r=rod: self._menu_unassign(r))
        else:
            menu.add_command(label='Nothing under the pointer', state='disabled')

        # Always available, because they are about where you are standing
        # rather than about what you clicked.
        if editing is not None:
            menu.add_separator()
            menu.add_command(label='Leave %s' % self._group_display_name(editing),
                             command=self._group_step_out)
        if getattr(self, '_hidden_groups', None):
            menu.add_separator()
            menu.add_command(label='Show all groups', command=self._group_show_all)

        try:
            menu.tk_popup(self.canvas.winfo_rootx() + ex,
                          self.canvas.winfo_rooty() + ey)
        finally:
            menu.grab_release()
        self._last_object_menu = menu          # kept so a test can read it
        return menu

    # ── the verbs, each one thin ───────────────────────────────────────────

    def _menu_enter(self, gid):
        return self._group_open(gid, nested=self._editing_gid() is not None)

    def _menu_select(self, gid):
        self._set_current_group(gid, say=False)
        self._group_select_object(gid)
        self._draw()
        return gid

    def _menu_on(self, gid, fn):
        """Run a panel verb against `gid` by making it current first.

        The panel's verbs read the current row. Rather than duplicate each
        one here -- a second copy that would drift -- the menu points the
        row at what was clicked and calls the one that already exists.
        """
        self._set_current_group(gid, say=False)
        return fn()

    def _menu_hide(self, gid):
        self._group_toggle_hidden(gid)
        self._draw()

    def _menu_unassign(self, rod):
        self._push_undo('remove from group')
        sgp.unassign(self.groups, [rod])
        self._refresh_group_list()
        self._draw()
