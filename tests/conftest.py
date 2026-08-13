"""Shared test setup.

The daemon now writes structured entries straight to the systemd journal
(``core/journal.py``), which means an unguarded test run would scribble into
the developer's — and the RPM build's — real journal. Stub the send for every
test; the tests that care about journal behavior patch it themselves.
"""

import os
import subprocess
import time

import pytest

from idasen_companion.core import journal

# Set here, at conftest import, because conftest is imported before
# collection — the environment variable must be set at that point, before any
# GUI test module is collected. Forced rather than setdefault: a desktop
# session exports QT_QPA_PLATFORM=xcb and rpmbuild inherits it, then aborts
# on the display it cannot reach. Individual GUI test modules still set it
# themselves so each stays runnable alone.
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(autouse=True)
def no_real_journal_writes(monkeypatch):
    monkeypatch.setattr(journal, "send", lambda *a, **kw: True)


@pytest.fixture(autouse=True)
def no_real_subprocesses(monkeypatch):
    """Keep the suite off the machine it runs on.

    Two paths shell out and are reached by ordinary tests, not just the ones
    that mean to exercise them:

      - ``gui/service_ctl._run`` runs ``systemctl --user``. Building a
        SettingsPage calls ``load()`` -> ``_load_autostart()``, so several
        tests spawned a real ``is-enabled`` each. It never failed, because
        ``_run`` degrades to (-1, "", "") in a sandbox — but the rendered
        AutostartState then differs between a dev box and the rpmbuild
        chroot, which is a test that means different things in each.

      - ``core/journal.read_recent`` runs ``journalctl``. Dormant only
        because ``ActivityLogPage.on_shown`` is never reached today; one
        test that shows the page would wake it up.

    Both degrade to their documented "unavailable" answer when the binary is
    missing, which is what this simulates.

    Stubbed at the ``subprocess.run`` layer, not at ``_run``/``read_recent``,
    so the tests that do mean to exercise those still patch over this with
    their own canned results.
    """
    def refuse(*_args, **_kwargs):
        raise FileNotFoundError("subprocess disabled in tests")

    monkeypatch.setattr(subprocess, "run", refuse)


@pytest.fixture(autouse=True)
def _restore_global_height_unit():
    """Undo any test's mutation of gui/util.py's process-global height unit.

    ``AppContext.__init__`` calls ``util.set_height_unit(cfg.ui.units)``, and
    the shipped default is "system" — which, against the en_US default pinned
    below, resolves to inches. So merely *constructing* an AppContext switched
    every later test's height rendering to inches, permanently.

    Nothing revealed it, because collection is alphabetical and the two
    leakers happen to sort after their victims. The suite passed in file order
    and failed 6 tests in reverse order; it would also have broken under
    pytest-xdist, pytest-randomly, a -k filter, or simply a new test file whose
    name sorts differently. Restoring here makes the suite order-independent by
    construction rather than by luck.
    """
    try:
        from idasen_companion.gui import util
    except ImportError:
        yield  # PySide6 not installed; the GUI tests importorskip themselves
        return
    previous = util._unit
    yield
    util._unit = previous


@pytest.fixture(scope="session", autouse=True)
def _pin_timezone():
    """Pin TZ for the whole run.

    The schedule reads naive local time (`datetime.fromtimestamp`) — the right
    design, since "09:00" means the user's 09:00. But it means every schedule
    and statistics test is evaluated against whatever TZ the machine is in, and
    the RPM's %check runs in a chroot that may be UTC while a developer's box
    is not. Pinning makes the day-boundary and DST cases mean the same thing
    everywhere, and lets them be written at all.
    """
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"  # has DST, unlike UTC
    time.tzset()
    yield
    if previous is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous
    time.tzset()


@pytest.fixture(scope="session", autouse=True)
def _pin_default_locale():
    """Pin QLocale's default to en_US for the whole run.

    gui/util.py's fmt_number()/fmt_height() read QLocale() to render
    decimals, so without this the builder's own $LANG leaks into their
    output — test_log_catalog.py's "110.0 cm" assertion would only hold on
    an English machine, and would silently fail the RPM's %check on a
    Spanish one. Guarded so the many non-Qt tests aren't made to depend on
    PySide6 being installed.
    """
    try:
        from PySide6.QtCore import QLocale
    except ImportError:
        return
    previous = QLocale()
    QLocale.setDefault(QLocale("en_US"))
    yield
    QLocale.setDefault(previous)
