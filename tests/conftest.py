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


@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def make_app_context(qapp, tmp_path, monkeypatch):
    """Build a context from caller-owned state with explicit loading intent."""
    from idasen_companion.core.config import save_config
    from idasen_companion.gui import context as context_mod

    def create(client, config, *, load_config, tray_available, path=None):
        config_path = tmp_path / "config.toml" if path is None else path
        config_path = config_path.resolve()
        if not config_path.is_relative_to(tmp_path.resolve()):
            raise ValueError("test config path must be below tmp_path")
        save_config(config, config_path)
        monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", config_path)
        context = context_mod.AppContext(client, tray_available=tray_available)
        if load_config:
            context.reload_config()
        return context

    return create


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
def _destroy_widgets_created_by_test():
    """Delete each test's widgets while the QApplication is still alive.

    Signal connections and restyle callbacks can retain pages after their
    test returns. Leaving them for interpreter cleanup crashes Qt 6.12 after
    the suite reports success. Preserve pre-existing widgets owned by wider
    fixtures, and do not create an application for non-GUI tests.
    """
    try:
        import shiboken6
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:
        yield
        return
    previous = (set(QApplication.topLevelWidgets())
                if QApplication.instance() is not None else set())
    yield
    if QApplication.instance() is None:
        return
    for widget in QApplication.topLevelWidgets():
        if widget not in previous and shiboken6.isValid(widget):
            widget.deleteLater()
    # These tests do not run app.exec(), so process deferred deletes explicitly
    # instead of leaving them until the event loop (and platform) are gone.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def _restore_the_application_style():
    """Undo any test's mutation of the session QApplication's style.

    ``gui/main.main()`` installs the app's own ``QProxyStyle``, and the
    modules that drive ``main()`` hand it the *session-scoped* ``qapp``
    fixture, so without this the style outlives the test that installed it:
    every module collected afterwards in the same process renders through a
    style it never asked for, and the suite means something different
    depending on collection order. Two modules did exactly that, and passed
    only because alphabetical collection happened to be benign.

    Restored here rather than in each module, since the hazard belongs to
    anything that calls ``main()``. A *fresh* fusion style is installed
    rather than the previous object saved and re-set: ``setStyle`` takes
    ownership of the style it replaces and may already have deleted it.
    Fusion is what the factory hands back for the default key on every
    platform this ships to, and it is what the app itself proxies.
    """
    try:
        from PySide6.QtWidgets import QApplication, QStyleFactory
    except ImportError:
        yield  # PySide6 not installed; the GUI tests importorskip themselves
        return
    yield
    application = QApplication.instance()
    if application is None:
        return
    # A style built by the factory carries its key as its object name; one
    # constructed directly (as the app's own is) does not.
    if application.style().objectName() != "fusion":
        application.setStyle(QStyleFactory.create("fusion"))


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

    LocaleProfile is built from QLocale() on every path that doesn't
    name a language, so without this the builder's own $LANG leaks into a
    rendered decimal — test_log_catalog.py's "110.0 cm" assertion would only hold on
    an English machine, and would silently fail the RPM's %check on a
    Spanish one. Guarded so the many non-Qt tests aren't made to depend on
    PySide6 being installed.
    """
    try:
        from PySide6.QtCore import QLocale
    except ImportError:
        # `yield`, not a bare `return`. This is a generator fixture, so
        # returning early yields nothing at all and pytest raises "did not
        # yield a value" — and since this one is session-scoped and autouse,
        # that error lands on every test in the run rather than on the Qt ones.
        yield
        return
    previous = QLocale()
    QLocale.setDefault(QLocale("en_US"))
    yield
    QLocale.setDefault(previous)
