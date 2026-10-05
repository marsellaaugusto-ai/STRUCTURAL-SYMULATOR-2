# Running the app — and what to do when it will not start

## The short version

```
cd "STRUCTURAL SYMULATOR SOLVER-5-9-26"
python -m pip install -r requirements.txt
python main.py
```

In VS Code: **open this folder** (not the repository root), pick the
interpreter you just installed into, and press **F5**.

## "It crashes when I open it in VS Code"

It is almost never the code. It is that VS Code ran a *different Python*
from the one the packages are installed into. VS Code remembers an
interpreter per workspace and will happily pick a system Python, a stale
virtual environment, or a Microsoft Store build.

`main.py` imports `tkinter` on its first line of real work, and `common.py`
imports `numpy` unguarded. Miss either and the process dies on an import
line before a window exists — and from a Run button that looks like a
crash, because the console that held the traceback may have closed again.
So the first thing to do is run **the doctor** below, which says which
interpreter you are on and what it is missing.

## "It starts, but no window ever appears"

This is a different fault and it has a different cause. There is no
traceback, nothing is missing, and the process sits burning most of a core
forever.

That was a **Tkinter resize-event loop**, fixed on 2026-09-28 in
`common.py`. A `<Configure>` binding on a toplevel fires for every
descendant as well, because a widget's bindtags include its toplevel; the
toolbar's relayout handlers were reacting to their own children's resize
events and changing the layout again on each one, so the first layout pass
never finished. The fix defers each relayout to a short timer instead of
`after_idle`, which is what let it re-enter:
`FlowBar._schedule`, `WrapBar._schedule` and `_on_toplevel_resize`.

**A correction worth recording**, because the wrong answer was shipped
first: a dependency *preflight* was added to `main.py` on 2026-09-27 under
the belief that this was a missing-library problem. It was not — the
libraries were installed the whole time — and the preflight has been
removed. If you are reading an older copy of this file, or an older commit
message claiming a launch crash was fixed by checking dependencies, that
claim is wrong. `REPORTS AND GUIDES/STEREO_ROADMAP_V2_FULL_ACCOUNT_2026-09-28.md`
§4 has the reproduction and §12.5 the correction.

## The doctor

```
python tools/doctor.py
```

It imports nothing the app needs, so it runs even where the app does not.
It prints the interpreter, the platform, every dependency with its version
or the error it raised, whether the folder layout is intact, and a verdict.
In VS Code it is also the **Environment doctor** entry in the Run menu and
in the task list. Paste its output into a bug report and the cause is
usually obvious from it alone.

## What VS Code needs, and why

`.vscode/launch.json` ships with three configurations:

| Configuration | Use it when |
|---|---|
| **Structural Simulator (app folder open)** | you opened `STRUCTURAL SYMULATOR SOLVER-5-9-26` |
| **Structural Simulator (repository root open)** | you opened the repository, one level up |
| **Environment doctor** | it still will not start |

Two configurations rather than one because of the working directory.
`main.py`, `common.py` and every `apps/<name>/` package import each other by
package path — they are not installed — so the app must run with the app
folder as the working directory. VS Code's plain **Run** button uses the
*workspace* root, which is the wrong folder whenever the repository rather
than the app folder is what was opened. Both configurations set `cwd`
explicitly, so **F5 works either way**; the bare Run button does not.

`.vscode/tasks.json` adds **Install requirements**, which runs pip with
whichever interpreter is currently selected — the point being that it
cannot install into the wrong one.

## Requirements, and which are real

| Package | Required? | Without it |
|---|---|---|
| `tkinter` | yes | nothing starts; it is part of Python, not a pip package |
| `numpy` | yes | nothing starts; `common.py` imports it at module scope |
| `scipy` | yes | the cable-web solver converges on no network with a junction |
| `openpyxl` | yes in practice | no Excel import or export (the app says what to install) |
| `matplotlib` | yes in practice | no PDF report, no guide equation images (the app says what to install) |
| `Pillow` | optional | no free-body-diagram images inside the Excel export |

`tkinter` is the one that catches people out, because it is not on PyPI:

- Debian/Ubuntu — `sudo apt install python3-tk`
- Fedora — `sudo dnf install python3-tkinter`
- macOS / Windows — reinstall Python from python.org. It is included
  there, but some Homebrew, pyenv and Microsoft Store builds omit it.

## Python version

3.9 or newer. The doctor says so rather than letting it fail later on
a syntax or stdlib difference.
