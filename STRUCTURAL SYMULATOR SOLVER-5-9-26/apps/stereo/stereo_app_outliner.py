"""The outliner: the group tree, shown as a tree.

The panel used to show the groups as a flat Listbox with the nesting faked
by leading spaces. That reads well enough for three groups and stops
reading at ten, and it cannot be acted on: a tree drawn in spaces has no
branch to collapse and nothing to drag.

This is the same rows in a real tree, and it is worth being clear about
what that buys, because it is not decoration:

  * A BRANCH CAN BE PUT AWAY. A roof with twelve bays is one line until
    you want it.
  * NESTING CAN BE CHANGED BY MOVING SOMETHING. Dragging a group onto
    another is the whole of "make this a subgroup of that", which was
    otherwise a thing you could only get by deleting and rebuilding.
  * THE TREE IS THE SELECTION. Clicking a row selects that group in the
    view, and selecting a group in the view scrolls to its row and
    highlights it -- the same state, shown in both places, which is the
    thing a flat list could not do once rows outnumbered the box.

WHAT IS NOT HERE. The tree shows containment and nothing else. Roles cut
across it and have their own panel (stereo_roles), and a component is a
fact about groups rather than a place in the tree (stereo_components) --
both of them things a tree cannot answer, which is exactly why they are
not in it.

The widget is still called `group_list`: it is the group list, and it is
what the rest of the tab and its tests reach for. Nothing outside this
file should touch it directly -- `_group_row_select`, `_group_row_gid`
and friends are the seam, so the widget stays an implementation detail.
"""
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from apps.stereo import stereo_groups as sgp
from apps.stereo.stereo_app_constants import BG

#: The Ungrouped row is not a group and has no id. It still needs a handle
#: in the tree, and one that can never collide with a group's.
UNGROUPED_IID = 'ungrouped'

#: How far the pointer has to move before a click becomes a drag. Without
#: it every click on a row would be a one-pixel reparent.
DRAG_SLOP_PX = 6

DROP_TAG = 'drop_target'
DROP_FILL = '#d7e8f5'

#: What a level of nesting costs in pixels, plus room for the expander and
#: a little air at the end. Measured from the widget where it can be;
#: these are the fallbacks for a theme that will not say.
INDENT_PX = 20
GUTTER_PX = 24


class StereoOutlinerMixin:
    """The group tree, its selection, and dragging a branch somewhere else."""

    def _init_outliner_state(self):
        # Which branches the user has put away. Remembered across the
        # refreshes that happen on every edit, or a tree would spring open
        # again the moment anything changed.
        self._group_closed = set()
        self._drag_from = None
        self._drag_at = None
        self._drag_live = False

    # ── building it ────────────────────────────────────────────────────────

    def _build_group_outliner(self, parent):
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill='x', padx=6, pady=(0, 2))
        self.group_list = ttk.Treeview(wrap, show='tree', height=7,
                                       selectmode='browse')
        bar = ttk.Scrollbar(wrap, orient='vertical',
                            command=self.group_list.yview)
        self.group_list.configure(yscrollcommand=bar.set)
        self.group_list.grid(row=0, column=0, sticky='ew')
        bar.grid(row=0, column=1, sticky='ns')
        # Long names are the normal case here -- "Roof 1 bottom chords"
        # with its counts, its piece mark and the part it is a copy of --
        # and a tree spends width on indentation as well. The sideways
        # scrollbar appears only when something really is too wide, so a
        # model with short names does not pay a row of chrome for it.
        self._group_xbar = ttk.Scrollbar(wrap, orient='horizontal',
                                         command=self.group_list.xview)
        self.group_list.configure(xscrollcommand=self._group_xbar.set)
        wrap.columnconfigure(0, weight=1)
        self._group_wrap = wrap
        self.group_list.column('#0', width=10, stretch=True)
        self.group_list.tag_configure(DROP_TAG, background=DROP_FILL)

        self.group_list.bind('<<TreeviewSelect>>', self._on_group_pick)
        self.group_list.bind('<Double-Button-1>', self._on_outliner_double)
        self.group_list.bind('<<TreeviewOpen>>', self._on_outliner_open)
        self.group_list.bind('<<TreeviewClose>>', self._on_outliner_close)
        self.group_list.bind('<ButtonPress-1>', self._on_outliner_press,
                             add='+')
        self.group_list.bind('<B1-Motion>', self._on_outliner_drag)
        self.group_list.bind('<ButtonRelease-1>', self._on_outliner_drop)
        for seq in ('<Button-3>', '<Button-2>', '<Control-Button-1>'):
            self.group_list.bind(seq, self._on_group_right_click)
        return self.group_list

    # ── the seam: rows by group id, never by position ─────────────────────

    @staticmethod
    def _group_row_iid(gid):
        return UNGROUPED_IID if gid is None else 'g%d' % gid

    @staticmethod
    def _group_row_gid(iid):
        """The group an item stands for: None for Ungrouped, and None for
        anything that is not a row of this tree."""
        if not iid or iid == UNGROUPED_IID:
            return None
        try:
            return int(str(iid)[1:])
        except ValueError:
            return None

    def _group_row_select(self, gid):
        """Point the tree at `gid`, opening whatever branch it is inside.

        A row inside a branch the user closed would otherwise be selected
        invisibly, and the panel would disagree with the view about what is
        current while looking as though it did not.
        """
        tree = getattr(self, 'group_list', None)
        if tree is None:
            return
        iid = self._group_row_iid(gid)
        if not tree.exists(iid):
            self._group_row_clear()
            return
        up = tree.parent(iid)
        while up:
            tree.item(up, open=True)
            self._group_closed.discard(self._group_row_gid(up))
            up = tree.parent(up)
        tree.selection_set(iid)
        tree.see(iid)

    def _group_row_clear(self):
        tree = getattr(self, 'group_list', None)
        if tree is not None:
            tree.selection_set(())

    def _group_row_labels(self):
        """Every row's text, in the order the tree shows them."""
        tree = getattr(self, 'group_list', None)
        if tree is None:
            return []
        out = []

        def walk(iid):
            for child in tree.get_children(iid):
                out.append(tree.item(child, 'text'))
                walk(child)

        walk('')
        return out

    def _group_row_count(self):
        return len(self._group_row_labels())

    # ── keeping it in step with the model ─────────────────────────────────

    def _fill_group_outliner(self, rows, keep):
        """Rebuild the tree from `rows` -- [(label, gid)] -- and reselect.

        Rows arrive in tree order with no indentation of their own; where
        each one sits comes from the group's `parent`, which is the only
        copy of that fact. Building the label and the nesting from two
        different places is how a panel starts disagreeing with its model.
        """
        tree = self.group_list
        tree.delete(*tree.get_children(''))
        placed = set()
        for label, gid in rows:
            parent = None
            if gid is not None:
                record = sgp.find(self.groups, gid)
                parent = (record or {}).get('parent')
            at = self._group_row_iid(parent) if parent in placed else ''
            tree.insert(at, 'end', iid=self._group_row_iid(gid), text=label,
                        open=gid not in self._group_closed)
            if gid is not None:
                placed.add(gid)
        if keep is not False:
            self._group_row_select(keep)
        self._fit_outliner_width()

    def _fit_outliner_width(self):
        """Give the tree column the width its longest row actually needs,
        and show the sideways scrollbar only if that is wider than the
        panel."""
        tree = self.group_list
        try:
            metric = tkfont.nametofont(
                ttk.Style().lookup('Treeview', 'font') or 'TkDefaultFont')
        except tk.TclError:
            metric = tkfont.nametofont('TkDefaultFont')
        widest = 0
        for iid, depth in self._rows_with_depth():
            text = tree.item(iid, 'text')
            widest = max(widest,
                         metric.measure(text) + depth * INDENT_PX + GUTTER_PX)
        have = tree.winfo_width()
        if have <= 1:                       # not laid out yet
            have = widest
        tree.column('#0', width=max(widest, have), stretch=(widest <= have))
        if widest > have:
            self._group_xbar.grid(row=1, column=0, sticky='ew')
        else:
            self._group_xbar.grid_forget()

    def _rows_with_depth(self, iid='', depth=0):
        out = []
        for child in self.group_list.get_children(iid):
            out.append((child, depth))
            out.extend(self._rows_with_depth(child, depth + 1))
        return out

    # ── going in, and putting a branch away ───────────────────────────────

    def _on_outliner_double(self, event):
        """Double-click a row: select its rods, as the list always did.

        Except on the expander itself, where a double-click means what it
        means everywhere -- open or close the branch -- and the tree's own
        handling is left alone.
        """
        if self._on_indicator(event):
            return None
        self._group_select_rods()
        return 'break'

    def _on_indicator(self, event):
        try:
            return 'indicator' in self.group_list.identify_element(
                event.x, event.y)
        except tk.TclError:
            return False

    def _on_outliner_open(self, _event=None):
        gid = self._group_row_gid(self.group_list.focus())
        self._group_closed.discard(gid)

    def _on_outliner_close(self, _event=None):
        """Put a branch away, and take the selection with it.

        Without the second half the two rules fight: closing a branch that
        holds the current group hides the selection, and the next refresh
        -- which happens on almost any edit -- opens the branch again to
        show it. The branch would not stay shut. Every outliner answers
        this the same way, by selecting the thing you just closed.
        """
        iid = self.group_list.focus()
        gid = self._group_row_gid(iid)
        if gid is None:
            return
        self._group_closed.add(gid)
        chosen = self.group_list.selection()
        if chosen and self._inside(chosen[0], iid):
            self._set_current_group(gid, say=False)

    def _inside(self, iid, ancestor):
        up = self.group_list.parent(iid)
        while up:
            if up == ancestor:
                return True
            up = self.group_list.parent(up)
        return False

    # ── dragging a group somewhere else ───────────────────────────────────

    def _on_outliner_press(self, event):
        self._drag_from = None
        self._drag_live = False
        if self._on_indicator(event):
            return
        iid = self.group_list.identify_row(event.y)
        if iid and self._group_row_gid(iid) is not None:
            self._drag_from = iid
            self._drag_at = (event.x, event.y)

    def _on_outliner_drag(self, event):
        if self._drag_from is None:
            return
        if not self._drag_live:
            dx = abs(event.x - self._drag_at[0])
            dy = abs(event.y - self._drag_at[1])
            if max(dx, dy) < DRAG_SLOP_PX:
                return
            self._drag_live = True
        self._show_drop_target(self.group_list.identify_row(event.y))

    def _show_drop_target(self, iid):
        tree = self.group_list
        for item in tree.tag_has(DROP_TAG):
            tree.item(item, tags=())
        if iid and iid != self._drag_from \
                and self._may_drop(self._drag_from, iid):
            tree.item(iid, tags=(DROP_TAG,))
        tree.configure(cursor='hand2' if self._drag_live else '')

    def _may_drop(self, dragged, iid):
        """Whether `dragged` could become a child of the row `iid`.

        Both rows are passed in rather than one being read off the drag
        state, because the drop clears that state before it decides -- and
        a rule that silently reads None refuses everything, which looks
        exactly like a rule that is working.

        Ungrouped is not a group, so nothing goes inside it. A group cannot
        go inside itself or anything below it, which `sgp.reparent` also
        refuses -- checked here too so a row never lights up to offer a
        move that would then be refused.
        """
        gid = self._group_row_gid(dragged)
        onto = self._group_row_gid(iid)
        if gid is None or iid == UNGROUPED_IID:
            return False
        if onto is None or onto == gid:
            return False
        return onto not in sgp.descendant_ids(self.groups, gid)

    def _on_outliner_drop(self, event):
        iid, self._drag_from = self._drag_from, None
        live, self._drag_live = self._drag_live, False
        self.group_list.configure(cursor='')
        for item in self.group_list.tag_has(DROP_TAG):
            self.group_list.item(item, tags=())
        if iid is None or not live:
            return None
        onto = self.group_list.identify_row(event.y)
        gid = self._group_row_gid(iid)
        # Dropped clear of every row: out of whatever it was in, to the top.
        parent = self._group_row_gid(onto) if onto else None
        if onto and not self._may_drop(iid, onto):
            return 'break'
        if parent == (sgp.find(self.groups, gid) or {}).get('parent'):
            return 'break'
        self._reparent_group(gid, parent)
        return 'break'

    def _reparent_group(self, gid, parent):
        """Move a group under another, or to the top. The drop's own verb.

        Rods do not move: a group holds member indices, and nesting says
        which branch owns which, not where the steel is. What changes is
        the tree, and therefore every roll-up computed over it.
        """
        if not self._guard_outside_edit('Move group', gid):
            return False
        here = sgp.find(self.groups, gid)
        if here is None:
            return False
        self._push_undo('move group')
        try:
            sgp.reparent(self.groups, gid, parent)
        except ValueError as exc:
            self._undo_stack.pop()
            messagebox.showinfo('Move group', str(exc))
            return False
        self._refresh_group_list(keep=gid)
        self._draw()
        where = ('inside %s' % self._group_display_name(parent)) \
            if parent is not None else 'to the top'
        self._set_status('%s moved %s. Its rods did not move -- nesting says '
                         'which branch owns them.'
                         % (self._group_display_name(gid), where), 'ok')
        return True
