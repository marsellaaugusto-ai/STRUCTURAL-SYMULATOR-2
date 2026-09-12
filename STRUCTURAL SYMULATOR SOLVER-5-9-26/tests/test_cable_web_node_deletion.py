"""Regression test for a dangling-attachment bug found while auditing
boundary-condition/mesh handling app-wide (2026-09-12): deleting a node
removed the cables incident to it and pruned loads referencing those
cables, but did NOT scrub OTHER nodes' `attachments` lists that still
named one of those now-deleted cable ids -- unlike `_delete_cable`, which
already does exactly that cleanup for a direct cable deletion.

A junction node's `attachments` entry surviving its parent cable's
deletion is invisible until something reads it: `_show_node_inspector`
lists it with no existence check, and `_apply_attachment_positions` ->
`_cable_length` -> `_cable` looks the id up with `next(... )` and no
default, raising an unhandled StopIteration the first time a user tries
to use that junction.
"""
import gc
import time

try:
    import tkinter as tk
except Exception:
    tk = None

import pytest

from common import PX_PER_M
from apps.cable_web.cable_web_app import CableWebApp

# Node x/y are stored in canvas PIXELS (PX_PER_M px = 1 m; see
# CableWebApp._straight_distance), not metres -- these helpers place nodes
# at a given metre coordinate so the cable lengths below come out sane.
def _m(v):
    return v * PX_PER_M


def _new_root_or_skip():
    if tk is None:
        pytest.skip('tkinter not importable in this environment')
    last = None
    for attempt in range(4):
        try:
            return tk.Tk()
        except Exception as ex:
            last = ex
            gc.collect()
            time.sleep(0.25 * (attempt + 1))
    pytest.skip(f'no display available to run this UI-level check ({last})')


@pytest.fixture
def app():
    root = _new_root_or_skip()
    root.geometry('900x700+0+0')
    a = CableWebApp(root)
    a.pack(fill='both', expand=True)
    root.update_idletasks()
    yield a
    try:
        root.destroy()
    except Exception:
        pass
    gc.collect()


def test_deleting_a_node_scrubs_attachments_that_named_its_cables(app):
    node_a = app._new_node(_m(0.0), _m(0.0), support=True)
    node_b = app._new_node(_m(10.0), _m(0.0), support=True)
    cable = app._new_cable(node_a['id'], node_b['id'])
    assert cable is not None

    junction = app._new_node(_m(5.0), _m(-1.0))
    app._attach_node(junction['id'], cable['id'], 5.0)
    assert junction['attachments'] == [(cable['id'], 5.0)]

    app._delete_node(node_a['id'])

    # the cable is gone, as before...
    assert all(c['id'] != cable['id'] for c in app.cables)
    # ...and now so is every OTHER node's reference to it.
    surviving = app._node(junction['id'])
    assert surviving['attachments'] == [], (
        'a dangling attachment to a deleted cable survived node deletion')


def test_a_support_node_can_be_converted_back_to_a_junction(app):
    """Regression for the same audit: the 'Support' tool could only ever
    set n['support'] = True, with no control anywhere to clear it again --
    a node marked a support by mistake, or a boundary condition the user
    simply wants to change, was otherwise stuck short of Ctrl+Z or
    delete-and-rebuild."""
    node = app._new_node(_m(1.0), _m(1.0), support=True)
    assert node['support'] is True

    app._toggle_node_support(node['id'])
    assert app._node(node['id'])['support'] is False

    app._toggle_node_support(node['id'])
    assert app._node(node['id'])['support'] is True


def test_converting_a_junction_to_a_support_clears_its_attachments(app):
    node_a = app._new_node(_m(0.0), _m(0.0), support=True)
    node_b = app._new_node(_m(10.0), _m(0.0), support=True)
    cable = app._new_cable(node_a['id'], node_b['id'])
    junction = app._new_node(_m(5.0), _m(-1.0))
    app._attach_node(junction['id'], cable['id'], 5.0)
    assert junction['attachments']

    app._toggle_node_support(junction['id'])
    assert app._node(junction['id'])['attachments'] == []


def test_the_inspector_rebuilds_cleanly_in_both_states(app):
    """Real-widget check (never trust this from reading the grid layout
    alone): selecting a node and toggling it must not raise, in either
    direction, and the inspector's title must reflect the new state."""
    node = app._new_node(_m(2.0), _m(2.0), support=False)
    app.selected_kind, app.selected_id = 'node', node['id']
    app._show_node_inspector(node['id'])
    app.update_idletasks()

    app._toggle_node_support(node['id'])
    app.update_idletasks()
    title = app.inspector.grid_slaves(row=0, column=0)[0]
    assert 'SUPPORT' in title.cget('text')

    app._toggle_node_support(node['id'])
    app.update_idletasks()
    title = app.inspector.grid_slaves(row=0, column=0)[0]
    assert 'JUNCTION' in title.cget('text')


def test_a_junctions_own_attachment_to_an_unrelated_cable_survives(app):
    """The fix must remove ONLY attachments to cables that were actually
    deleted -- an attachment to a cable that is still alive must be left
    exactly as it was."""
    node_a = app._new_node(_m(0.0), _m(0.0), support=True)
    node_b = app._new_node(_m(10.0), _m(0.0), support=True)
    node_c = app._new_node(_m(0.0), _m(5.0), support=True)
    node_d = app._new_node(_m(10.0), _m(5.0), support=True)
    cable_ab = app._new_cable(node_a['id'], node_b['id'])
    cable_cd = app._new_cable(node_c['id'], node_d['id'])

    junction = app._new_node(_m(5.0), _m(2.5))
    app._attach_node(junction['id'], cable_ab['id'], 5.0)
    app._attach_node(junction['id'], cable_cd['id'], 5.0)

    app._delete_node(node_a['id'])   # only removes cable_ab

    surviving = app._node(junction['id'])
    assert surviving['attachments'] == [(cable_cd['id'], 5.0)]
