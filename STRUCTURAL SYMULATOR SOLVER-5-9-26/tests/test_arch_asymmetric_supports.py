"""Regression test for a boundary-condition gap found while auditing the app
for boundary-condition/mesh bugs (2026-09-12): ArchModel has always taken
support_a and support_b independently (apply_support(0, support_a) and
apply_support(n, support_b) never assumed they match), but the UI's single
'arch_type' combobox always set both ends to the SAME condition -- so a
real, common case (one abutment pinned, the other fixed) could not be built
at all despite nothing in the solver preventing it.

This adds a 'Custom (per end)' option exposing support_a/support_b
independently; these tests drive the real ArchApp widget end to end
(generate -> analyze -> export -> import), per this project's own testing
rule against trusting UI wiring from source alone.
"""
import gc
import os
import tempfile
import time

import tkinter as tk
import pytest

from apps.arch.arch_app import ArchApp, export_arch_excel, import_arch_excel


@pytest.fixture(scope='session')
def tk_root():
    last = None
    for attempt in range(6):
        try:
            root = tk.Tk()
            break
        except tk.TclError as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    else:
        pytest.skip(f'no Tk display after 6 attempts: {last}')
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def app(tk_root):
    a = ArchApp(tk_root)
    a.pack(fill='both', expand=True)
    tk_root.update_idletasks()
    yield a
    a.pack_forget()
    a.destroy()
    gc.collect()


def test_custom_per_end_frame_only_shows_for_that_selection(app):
    assert not app.custom_sup_frame.winfo_ismapped()
    app.arch_type_var.set('Custom (per end)')
    app._on_arch_type_change()
    app.update_idletasks()
    assert app.custom_sup_frame.winfo_ismapped()

    app.arch_type_var.set('Fixed')
    app._on_arch_type_change()
    app.update_idletasks()
    assert not app.custom_sup_frame.winfo_ismapped()


def test_asymmetric_ends_reach_the_solved_model_independently(app):
    app.arch_type_var.set('Custom (per end)')
    app._on_arch_type_change()
    app.support_a_var.set('pin')
    app.support_b_var.set('fixed')
    app._analyze()
    assert app.result is not None
    assert app.model.support_a == 'pin'
    assert app.model.support_b == 'fixed'


def test_the_two_presets_still_set_both_ends_the_same(app):
    app.arch_type_var.set('Fixed')
    app._on_arch_type_change()
    app._analyze()
    assert app.model.support_a == app.model.support_b == 'fixed'

    app.arch_type_var.set('Two-hinged')
    app._on_arch_type_change()
    app._analyze()
    assert app.model.support_a == app.model.support_b == 'pin'


def test_asymmetric_supports_round_trip_through_excel(app):
    app.arch_type_var.set('Custom (per end)')
    app._on_arch_type_change()
    app.support_a_var.set('pin')
    app.support_b_var.set('fixed')
    app._analyze()

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'arch.xlsx')
        export_arch_excel(app._current_state(), path, result=app.result, model=app.model)
        st = import_arch_excel(path)

    assert st['arch_type'] == 'Custom (per end)'
    assert st['support_a'] == 'pin'
    assert st['support_b'] == 'fixed'


def test_importing_an_older_workbook_with_no_per_end_columns_defaults_to_pin(app, tmp_path):
    """A workbook exported before this feature existed has a [SUPPORTS]
    section with only arch_type/hinge_frac columns -- import must not
    KeyError on the missing support_a/support_b columns."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Model'
    ws.append(['ARCH MODEL DATA'])
    ws.append([])
    ws.append(['[GEOMETRY]'])
    ws.append(['span_m', 'rise_m', 'n_elem', 'shape_expr'])
    ws.append([20.0, 4.0, 40, '4*rise*x*(L-x)/L**2'])
    ws.append([])
    ws.append(['[SUPPORTS]'])
    ws.append(['arch_type', 'hinge_frac'])
    ws.append(['Two-hinged', 0.5])
    path = str(tmp_path / 'old_arch.xlsx')
    wb.save(path)

    st = import_arch_excel(path)
    assert st['support_a'] == 'pin'
    assert st['support_b'] == 'pin'
