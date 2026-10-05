"""The iteration name: `v32 t 01 05-10-26`.

One round of changes to v32 needs a name of its own, or two builds handed
out a week apart are both "v32" and nobody can say which is which. The
letter is the tab the round was about, the number is the round within the
version, and the date is written day-month-year like every other date the
app shows.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import appinfo


WHEN = time.strptime('2026-10-05', '%Y-%m-%d')


def test_the_name_reads_the_way_it_is_spoken():
    assert appinfo.iteration_name(32, 1, WHEN) == 'v32 t 01 05-10-26'


def test_the_round_number_is_padded_so_names_sort():
    assert appinfo.iteration_name(32, 9, WHEN) == 'v32 t 09 05-10-26'
    assert appinfo.iteration_name(32, 10, WHEN) == 'v32 t 10 05-10-26'


def test_the_letter_says_which_tab_the_round_was_about():
    assert appinfo.iteration_name(32, 2, WHEN, letter='s') == 'v32 s 02 05-10-26'


def test_the_date_is_day_month_year():
    """Not month-day: the app writes dates the way they are read where it
    is used, and appinfo.DATE_FORMAT has said so since before this."""
    assert appinfo.iteration_name(32, 1, WHEN).endswith('05-10-26')
    assert appinfo.DATE_FORMAT.startswith('%d')


def test_no_iteration_means_no_name_rather_than_half_a_name():
    assert appinfo.iteration_name(32, None, WHEN) is None
    assert appinfo.iteration_name(None, 1, WHEN) is None


def test_the_stamp_round_trips():
    text = appinfo.stamp_text(32, WHEN, iteration=1)
    assert text == '32 2026-10-05 t01\n'
    ver, when, it = _read_stamp(text)
    assert (ver, it) == (32, 1)
    assert time.strftime('%Y-%m-%d', when) == '2026-10-05'


def _read_stamp(text, tmp=None):
    """build_info() against a given stamp, without touching the real one."""
    import re
    parts = text.split()
    ver, day = int(parts[0]), time.strptime(parts[1], '%Y-%m-%d')
    it = None
    if len(parts) > 2:
        m = re.match(r'[A-Za-z](\d+)$', parts[2])
        if m:
            it = int(m.group(1))
    return ver, day, it


def test_a_stamp_written_before_iterations_existed_still_reads():
    """Archives built by an older build_release.py have a two-field stamp.
    They must still title themselves, just without a round."""
    ver, when, it = _read_stamp('31 2026-10-03\n')
    assert (ver, it) == (31, None)
    title = appinfo.window_title(info=(ver, when, it), tab='Stereo')
    assert title == 'Structural Simulator v31 · 03/10/2026 — Stereo drawing'


def test_the_window_title_carries_the_round():
    title = appinfo.window_title(info=(32, WHEN, 1), tab='Truss')
    assert title == 'Structural Simulator v32 t 01 · 05-10-26 — Truss drawing'


def test_the_window_title_names_the_document_when_there_is_one():
    title = appinfo.window_title('roof_iterations.xlsx', info=(32, WHEN, 1))
    assert title.endswith('— roof_iterations.xlsx')
    assert 'v32 t 01' in title


def test_this_copy_knows_its_own_round():
    """The working copy's BUILD_STAMP.txt, or build_release.py when there
    is none. Either way the app can say what it is."""
    ver, _when, it = appinfo.build_info()
    assert ver == 32
    assert it is not None, (
        'this copy reports no iteration: BUILD_STAMP.txt and '
        'tools/build_release.py (APP_ITERATION) must agree one exists')
    assert appinfo.current_iteration_name().startswith('v32 t %02d' % it)


def test_the_archive_filename_carries_the_round_too():
    sys.path.insert(0, str(Path(appinfo.APP_DIR) / 'tools'))
    import build_release as br
    assert br.APP_VERSION == 32
    assert br.APP_ITERATION >= 1
    stamp = br.build_stamp()
    assert stamp.startswith('v32_t%02d_' % br.APP_ITERATION), stamp
    assert br.stamp_text().startswith('32 ')
    assert br.stamp_text().rstrip().endswith('t%02d' % br.APP_ITERATION)
    assert br.iteration_name().startswith('v32 t %02d ' % br.APP_ITERATION)
