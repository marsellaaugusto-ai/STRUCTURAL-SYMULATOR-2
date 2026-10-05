"""Run the tests the way the app runs: one thread for numpy's linear algebra.

main.py sets these before numpy loads (see the note there), but the tests
import the modules directly, so they would otherwise get OpenBLAS's default
pool -- a thread per core, busy-waiting -- and a timing-sensitive test such
as the Cable Web at-rest preview slowed from about 12 s to over five minutes
whenever anything else was using the CPU. This file is loaded before any
test module, so the variables are in place before numpy is imported.
"""
import os

for _var in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_var, '1')
