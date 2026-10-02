"""The About box: what the app is, whose it is, and the licences of the
open-source software it runs on.

The owner's line is the first line of LICENSE.txt at the app root, so the
copyright notice is written in exactly one place. The open-source licences
are THIRD_PARTY_NOTICES.txt when the archive ships one, and otherwise are
gathered live from this Python (notices.py) -- either way they match the
libraries actually in use.
"""
import os
import tkinter as tk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LICENSE_FILE = 'LICENSE.txt'
NOTICES_FILE = 'THIRD_PARTY_NOTICES.txt'

TITLE = 'Structural Simulator'
DISCLAIMER = ('Results are an aid to a qualified professional, who must check '
              'them. The app does not replace the design codes it cites or '
              'the designer\'s responsibility.')
BG = '#f5f5f3'


def _read(name):
    try:
        with open(os.path.join(APP_DIR, name), encoding='utf-8') as f:
            return f.read()
    except OSError:
        return None


def owner_line():
    """The licence's first non-blank line (the copyright notice), or None
    while there is no LICENSE.txt."""
    text = _read(LICENSE_FILE)
    if not text:
        return None
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def notices_text():
    shipped = _read(NOTICES_FILE)
    if shipped:
        return shipped
    import notices
    return notices.render()


def show_text(parent, title, text):
    """A read-only, scrollable text window."""
    win = tk.Toplevel(parent)
    win.title(title)
    frame = tk.Frame(win)
    frame.pack(fill='both', expand=True)
    sb = tk.Scrollbar(frame)
    sb.pack(side='right', fill='y')
    t = tk.Text(frame, wrap='word', width=90, height=32,
                font=('Courier', 9), yscrollcommand=sb.set)
    t.pack(side='left', fill='both', expand=True)
    sb.config(command=t.yview)
    t.insert('1.0', text)
    t.configure(state='disabled')
    tk.Button(win, text='Close', command=win.destroy).pack(pady=4)
    win.text_widget = t
    return win


def show_about(parent):
    win = tk.Toplevel(parent)
    win.title('About')
    win.configure(bg=BG)
    win.resizable(False, False)
    tk.Label(win, text=TITLE, bg=BG, fg='#1a6bbd',
             font=('Helvetica', 14, 'bold')).pack(padx=16, pady=(14, 2))
    owner = owner_line()
    tk.Label(win, text=owner or 'No licence file in this copy.', bg=BG,
             fg='#333' if owner else '#a33',
             font=('Helvetica', 9)).pack(padx=16)
    tk.Label(win, text=DISCLAIMER, bg=BG, fg='#555', wraplength=360,
             justify='left', font=('Helvetica', 9)).pack(padx=16, pady=8)
    row = tk.Frame(win, bg=BG)
    row.pack(pady=(0, 12))
    lic = tk.Button(row, text='Licence…',
                    state='normal' if owner else 'disabled',
                    command=lambda: show_text(win, 'Licence',
                                              _read(LICENSE_FILE) or ''))
    lic.pack(side='left', padx=4)
    oss = tk.Button(row, text='Open-source licences…',
                    command=lambda: show_text(win, 'Open-source licences',
                                              notices_text()))
    oss.pack(side='left', padx=4)
    tk.Button(row, text='Close', command=win.destroy).pack(side='left', padx=4)
    win.licence_button, win.notices_button = lic, oss
    return win
