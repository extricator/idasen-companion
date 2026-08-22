"""The window before-picture: every page, built offscreen, whole.

Phases 13-15 move formatting out of ``gui/util.py`` (see
``test_baseline_vocabulary.py``); this file is that plan's other half. The
vocabulary golden records what every formatter renders from a fixed input —
direct calls, no window built. It cannot see the roughly 325 catalogued
messages that live in the window's own chrome instead: card headings, button
labels, checkbox text, tooltips, placeholder text, combo box items, and the
sidebar's own navigation entries. This file builds the whole window offscreen,
in both shipped languages, and records every one of those.

Nothing here is a test of *behavior* — it is a recording, taken before
anything in this milestone moves a rendered string, whose only job is to fail
the moment one does. Regenerating the goldens
(``IDASEN_COMPANION_REGENERATE_WINDOW_GOLDENS=1``) is a deliberate, reviewed
act with the reason in the commit message, never a way to make a failing
comparison pass.

**Every source of variation reachable from the seven pages is neutralised
here, deliberately, and enumerated below rather than left for the next
reader to rediscover:**

- **Overview's 1s countdown ticker** is stopped immediately after
  construction, before anything is captured. The countdown string itself is
  never exercised by this walk anyway (see below) — this only rules out a
  timer callback landing mid-capture.
- **The countdown/progress text Overview would show while a cycle is
  running** is never reached: the fake client never pushes progress or
  status, so the page stays on its as-built state the whole time, and the
  live countdown wording itself is already the vocabulary golden's job
  (``fmt_countdown`` there, called directly with a fixed input).
- **The wall clock / "today"** — Statistics' ``date.today()`` is never
  reached either: its ``_refresh()`` returns immediately because the fake
  client reports unavailable, so nothing here calls it. Recorded rather than
  left to accident.
- **Timezone** is pinned session-wide by ``tests/conftest.py``'s
  ``_pin_timezone`` fixture; this file adds nothing further.
- **The default ``QLocale``** is pinned explicitly by this file itself
  (``en_US`` for the English capture, the shipped ``es`` catalog's locale for
  the Spanish one) *before* the window is built, the same way
  ``test_baseline_vocabulary.py``'s ``_language`` does — a ``QSpinBox`` /
  ``QDoubleSpinBox`` / ``QTimeEdit`` reads ``QLocale::default()`` once, at
  construction, so setting it after the window exists would be too late.
- **Both catalogs AppContext binds on a config reload** — Settings and
  Automation each call ``ctx.reload_config()`` from ``load()``, and
  ``AppContext`` now rebinds both catalogs from ``[ui] language`` on every
  reload (see ``gui/context.py``'s ``apply_language`` calls). ``cfg.ui.language``
  is set to the same value this capture installs manually, so a page visit
  mid-walk reinforces the intended language rather than silently rebinding
  back to "system". Every ``QTranslator`` installed on the session-scoped
  ``app`` over the whole walk — not just the one this function installs up
  front — is snapshotted and removed at teardown, and ``core/i18n.py``'s
  gettext binding is reset the same way, so neither catalog leaks into the
  next capture in the same process.
- **The fake client** reports a fixed, unavailable state and answers every
  method call with a no-op — nothing on any page can render a value read
  from a live desk.
- **The on-disk config** is a freshly written, fixed ``AppConfig`` in a
  throwaway directory — nothing here reads (or can accidentally write) the
  account's real config.
- **``AboutPage._lib_version``** — the installed versions of ``bleak``,
  ``idasen`` and ``PySide6`` vary by machine and by whenever dependencies
  were last resolved; frozen to a fixed placeholder for every module it is
  asked about.
- **``AboutPage``'s own ``DEFAULT_CONFIG_PATH`` / ``Path.home()``** — bound
  at import time from the real environment, and About's "Config" field
  reads them directly rather than through ``gui/context.py``'s (patched)
  copy; both are frozen to a fixed synthetic path so that field never
  depends on the account running the suite.
- **``service_ctl.autostart_state()``** shells out to systemd; stubbed to a
  fixed enabled state, mirroring ``tests/test_window_reopen.py``'s own
  precedent, rather than reading the real session's unit state.
- **``background_portal.is_flatpak()``** reads ``/.flatpak-info`` and is
  true only inside a Flatpak sandbox build; pinned False so the
  Settings/About autostart wording doesn't depend on which packaging
  pipeline happens to be building the tree the suite runs in.
- **``subprocess.run``** is disabled outright for the capture (raises), so
  the Activity Log page's threaded journal backlog read can never shell out
  to a real ``journalctl``. ``tests/conftest.py`` already guards this for
  every ordinary test, but the second-process proof below runs with no
  pytest fixtures active at all, so this file disables it itself rather than
  depending on a guard that isn't there.
- **``journal.send``** is stubbed to a no-op for the same reason.
- **The Activity Log's threaded backlog read** — after navigating to that
  page, the global ``QThreadPool`` is drained and the Qt event loop is
  pumped a fixed number of times, so its placeholder-vs-populated text is
  settled before capture rather than racing a worker thread's queued signal
  delivery. Since the fake client is unavailable and the journal read is
  disabled above, the backlog is empty either way — but the wait makes that
  a proven fact rather than a lucky race.
- **Traversal order**, while not a clock, is the only ordering ``findChildren``
  offers (only four widgets in the whole GUI carry an explicit object name —
  see ``12-RESEARCH.md`` Pitfall 5) — this is what the class-name-plus-ordinal
  keying in :func:`_walk_page` exists to make robust against, rather than a
  flat positional list.

No test in this file waits on a timer or sleeps.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("PySide6")

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import shiboken6  # noqa: E402
from PySide6.QtCore import (  # noqa: E402
    QCoreApplication, QLocale, QObject, QTranslator, Signal, QThreadPool,
)
from PySide6.QtWidgets import QApplication, QComboBox, QWidget  # noqa: E402

from idasen_companion.core import i18n as core_i18n  # noqa: E402
from idasen_companion.core import journal as journal_mod  # noqa: E402
from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.gui import background_portal  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import i18n  # noqa: E402
from idasen_companion.gui import main_window as mw  # noqa: E402
from idasen_companion.gui import service_ctl  # noqa: E402
from idasen_companion.gui.pages import about as about_mod  # noqa: E402
from idasen_companion.gui.pages.settings_form import (  # noqa: E402
    SettingsFormPage,
)
from idasen_companion.gui.service_ctl import AutostartState  # noqa: E402

#: Set to regenerate the committed goldens instead of comparing against them.
#: Unset (the default, and the only state CI ever runs in), a mismatch fails
#: with a readable diff; set, the file is rewritten and the comparison is
#: skipped, so a rewrite and a compare can never both happen in one run.
REGENERATE_ENV_VAR = "IDASEN_COMPANION_REGENERATE_WINDOW_GOLDENS"

GOLDEN_DIR = Path(__file__).parent / "goldens"

MAC = "E1:B2:C3:D4:E5:F6"

#: The seven sidebar pages, in the exact order ``MainWindow.__init__`` builds
#: them and ``window._pages`` holds them — hardcoded rather than derived,
#: since ``<interfaces>`` names this order as part of what is being captured.
PAGE_NAMES = ("overview", "automation", "presets", "statistics",
              "activity_log", "settings", "about")


class FakeClient(QObject):
    """Every signal MainWindow and its pages subscribe to, and nothing live.

    Mirrors ``tests/test_window_reopen.py``'s own fake exactly — this file
    needs the same shape, not a second hand-rolled one.
    """

    availableChanged = Signal(bool)
    heightChanged = Signal(float)
    positionChanged = Signal(str)
    connectedChanged = Signal(bool)
    movingChanged = Signal(bool)
    statusChanged = Signal(str)
    progressChanged = Signal(float, float)
    transitionCompleted = Signal(str, str, bool)
    snoozeUntilChanged = Signal(float)
    presetsChanged = Signal(dict)
    logEntry = Signal(float, str, str, str, dict, str)
    commandFailed = Signal(str, str)

    available = False

    def reload_config(self):  # pragma: no cover - unavailable, never nudged
        raise AssertionError("should not nudge an unavailable daemon")

    def __getattr__(self, name):
        # Building the whole window wires up every page's buttons, and those
        # connect to daemon calls (sit, stand, move_to_height, …) this fake
        # has no business answering. Nothing here is ever *invoked* — no test
        # presses a button — so a no-op stands in for all of them.
        return lambda *args, **kwargs: None


def _stub_autostart() -> AutostartState:
    """The unit is installed and enabled — the banner's uninteresting case.

    Same stub tests/test_window_reopen.py uses, for the same reason: the
    autostart banner's wording is not this file's subject.
    """
    return AutostartState("enabled", True, "")


def _frozen_lib_version(_module: str) -> str:
    """Stand in for ``AboutPage._lib_version``.

    The real one reads installed package metadata, which varies by machine
    and by whenever dependencies were last resolved — exactly the kind of
    drift this golden must not depend on.
    """
    return "0.0.0"


def _refuse_subprocess(*_args, **_kwargs):
    raise FileNotFoundError("subprocess disabled for the window capture")


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _drain_background_work(app: QApplication) -> None:
    """Let the Activity Log's threaded backlog read finish and its queued
    signal be delivered, so its placeholder-vs-populated text is settled
    before capture rather than racing a worker thread."""
    QThreadPool.globalInstance().waitForDone(2000)
    for _ in range(5):
        app.processEvents()


def _widget_fields(widget: QWidget) -> dict[str, str]:
    """Every distinct piece of user-visible text one widget exposes."""
    fields: dict[str, str] = {}
    text_method = getattr(widget, "text", None)
    if callable(text_method):
        try:
            value = text_method()
        except TypeError:
            value = None
        if isinstance(value, str) and value:
            fields["text"] = value
    tooltip = widget.toolTip()
    if tooltip:
        fields["tooltip"] = tooltip
    placeholder_method = getattr(widget, "placeholderText", None)
    if callable(placeholder_method):
        placeholder = placeholder_method()
        if placeholder:
            fields["placeholder"] = placeholder
    if isinstance(widget, QComboBox):
        for item_index in range(widget.count()):
            item_text = widget.itemText(item_index)
            if item_text:
                fields[f"item{item_index}"] = item_text
    accessible = widget.accessibleDescription()
    if accessible:
        fields["accessible_description"] = accessible
    return fields


def _walk_page(page: QWidget, page_name: str) -> dict[str, str]:
    """Every non-empty text field on ``page``, keyed by page name, widget
    class name and an ordinal within that class on that page.

    Only four widgets in the whole GUI carry an explicit ``objectName``
    (``12-RESEARCH.md`` Pitfall 5), so traversal order is the only ordering
    ``findChildren`` offers — keying this way, rather than a flat positional
    list, keeps a structural reorder that moves no text from rewriting the
    whole golden.
    """
    flat: dict[str, str] = {}
    ordinals: dict[str, int] = {}
    for widget in page.findChildren(QWidget):
        fields = _widget_fields(widget)
        if not fields:
            continue
        class_name = type(widget).__name__
        ordinal = ordinals.get(class_name, 0)
        ordinals[class_name] = ordinal + 1
        for field_name, value in fields.items():
            flat[f"{page_name}.{class_name}#{ordinal}.{field_name}"] = value
    return flat


def _capture_window_chrome(window: mw.MainWindow) -> dict[str, str]:
    """The window's own chrome: the sidebar navigation entries, the daemon
    banner and its button, and the connection footer — none of which live
    inside any page's own widget tree."""
    flat: dict[str, str] = {}
    for index in range(window._nav.count()):  # pylint: disable=protected-access
        text = window._nav.item(index).text()  # pylint: disable=protected-access
        if text:
            flat[f"window.NavItem#{index}.text"] = text
    for class_name, widget in (
            ("DaemonBanner", window._daemon_banner),  # pylint: disable=protected-access
            ("StartDaemonButton", window._start_daemon_btn),  # pylint: disable=protected-access
            ("ConnectionFooter", window._conn_footer),  # pylint: disable=protected-access
    ):
        text = widget.text()
        if text:
            flat[f"window.{class_name}#0.text"] = text
    return flat


def _capture_language(language: str) -> dict[str, str]:
    """Build the whole window offscreen in ``language`` and flatten its
    rendered text.

    The single implementation both the in-session double capture and the
    second-process capture call, so both prove the same construction path
    rather than two hand-written approximations of it. Runs standalone —
    with no pytest fixtures active — since a spawned second process has
    none, which is why every neutralised source this module's docstring
    lists is pinned here explicitly rather than borrowed from
    ``tests/conftest.py``.
    """
    app = QApplication.instance() or QApplication([])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(journal_mod, "send", lambda *a, **kw: True)
        mp.setattr(subprocess, "run", _refuse_subprocess)
        mp.setattr(service_ctl, "autostart_state", _stub_autostart)
        mp.setattr(background_portal, "is_flatpak", lambda: False)
        mp.setattr(about_mod.AboutPage, "_lib_version",
                   staticmethod(_frozen_lib_version))
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            config_path = tmp / "config.toml"
            cfg = AppConfig()
            cfg.desk.mac = MAC
            # AppContext now binds both catalogs from this value on every
            # config reload (see gui/context.py's apply_language calls), so
            # it has to agree with the locale this capture installs below --
            # otherwise a page visit that reloads config (Settings,
            # Automation) would silently rebind back to "system" mid-walk.
            cfg.ui.language = language
            save_config(cfg, config_path)
            mp.setattr(context_mod, "DEFAULT_CONFIG_PATH", config_path)

            # About reads its own imported copy of DEFAULT_CONFIG_PATH (bound
            # at import time from the real environment) and Path.home()
            # directly, rather than through gui/context.py — both are pinned
            # to a fixed synthetic path so the rendered "Config" field never
            # depends on the account running the suite.
            fake_home = tmp / "home" / "fakeuser"
            mp.setattr(about_mod, "DEFAULT_CONFIG_PATH",
                       fake_home / ".config" / "idasen-companion"
                       / "config.toml")
            mp.setattr(about_mod.Path, "home", staticmethod(lambda: fake_home))

            previous_locale = QLocale()
            # Every QTranslator already on the session-scoped app before this
            # capture starts -- diffed against what's installed at teardown,
            # since AppContext.reload_config() (Settings/Automation's load())
            # now installs its own translators mid-walk, not only the ones
            # this function installs up front.
            previous_translators = set(app.findChildren(QTranslator))
            if language == "en":
                QLocale.setDefault(QLocale("en_US"))
            else:
                i18n.install_translators(app, language)
            try:
                window = mw.MainWindow(FakeClient(), tray_available=True)
                try:
                    window.show()
                    # See this module's docstring: never fired anywhere in
                    # this synchronous walk, stopped anyway for good measure.
                    window.overview._ticker.stop()  # pylint: disable=protected-access
                    flat: dict[str, str] = {}
                    for index, page_name in enumerate(PAGE_NAMES):
                        window._nav.setCurrentRow(index)  # pylint: disable=protected-access
                        if page_name == "activity_log":
                            _drain_background_work(app)
                        flat.update(_walk_page(
                            window._pages[index], page_name))  # pylint: disable=protected-access
                    flat.update(_capture_window_chrome(window))
                    return flat
                finally:
                    for page in window._pages:  # pylint: disable=protected-access
                        if isinstance(page, SettingsFormPage):
                            page.discard_edits()
                    window.close()
            finally:
                for translator in set(app.findChildren(QTranslator)) - previous_translators:
                    QCoreApplication.removeTranslator(translator)
                    shiboken6.delete(translator)
                QLocale.setDefault(previous_locale)
                core_i18n.set_language(core_i18n.SYSTEM)


def _capture_in_subprocess(language: str) -> dict[str, str]:
    """Run :func:`_capture_language` in a freshly spawned interpreter.

    ``multiprocessing``'s spawn context starts a genuinely new Python
    process — re-importing every module from scratch — rather than forking
    this one, which is what makes this a real second-process proof and not
    merely a second call in the same interpreter. Not a second ``pytest``
    invocation shelled out to, because that would run through
    ``subprocess.run`` — which this module's own capture path deliberately
    disables (see :func:`_capture_language`'s docstring).
    """
    context = multiprocessing.get_context("spawn")
    with context.Pool(1) as pool:
        return pool.apply(_capture_language, (language,))


# ----------------------------------------------------------------------
# Golden I/O
# ----------------------------------------------------------------------


def _golden_path(language: str) -> Path:
    return GOLDEN_DIR / f"window_{language}.json"


def _write_golden(language: str, flat: dict[str, str]) -> None:
    path = _golden_path(language)
    path.write_text(
        json.dumps(flat, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


def _load_golden(language: str) -> dict[str, str]:
    path = _golden_path(language)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        pytest.fail(
            f"{path} does not exist. Regenerate it deliberately with "
            f"{REGENERATE_ENV_VAR}=1 .venv/bin/python -m pytest -q "
            f"tests/test_baseline_window.py, then commit the file with "
            f"a reason.", pytrace=False)
    return json.loads(text)


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


def test_every_page_produces_entries(qapp):
    """Every page appears in the capture, and so does the window chrome —
    asserted here rather than checked by eye."""
    flat = _capture_language("en")
    for page_name in PAGE_NAMES:
        assert any(key.startswith(f"{page_name}.") for key in flat), (
            f"{page_name} produced no captured entries")
    assert any(key.startswith("window.") for key in flat), (
        "the window's own chrome (nav / banner / footer) produced no "
        "captured entries")


def test_languages_differ(qapp):
    """A Spanish capture that equals the English one means the catalog, or
    the locale, never actually installed."""
    en = _capture_language("en")
    es = _capture_language("es")
    assert set(en) == set(es), (
        "English and Spanish captured a different set of keys — the two "
        "languages must render the same widget structure")
    assert en["window.NavItem#0.text"] != es["window.NavItem#0.text"], (
        "Spanish navigation entries equal the English ones")
    overview_text_keys = [key for key in en
                          if key.startswith("overview.") and key.endswith(".text")]
    assert any(en[key] != es[key] for key in overview_text_keys), (
        "no Overview heading differs between English and Spanish")


@pytest.mark.parametrize("language", ["en", "es"])
def test_matches_golden(qapp, language):
    flat = _capture_language(language)

    if os.environ.get(REGENERATE_ENV_VAR):
        _write_golden(language, flat)
        pytest.skip(f"regenerated {_golden_path(language)}")

    golden = _load_golden(language)
    differing = {
        key: (golden.get(key), flat.get(key))
        for key in golden.keys() | flat.keys()
        if golden.get(key) != flat.get(key)
    }
    assert not differing, (
        f"{language}: {len(differing)} rendered value(s) differ from "
        f"{_golden_path(language).name}:\n" +
        "\n".join(f"  {key}: golden={golden_value!r} "
                  f"actual={actual_value!r}"
                  for key, (golden_value, actual_value)
                  in sorted(differing.items())))


def test_capture_is_stable_within_a_session(qapp):
    """Two captures in the same process, back to back, must be identical —
    a picture that varies run to run is not a baseline."""
    first = _capture_language("en")
    second = _capture_language("en")
    assert first == second


def test_capture_is_stable_across_a_second_process(qapp):
    """A capture taken in a freshly spawned interpreter must match one taken
    in this one — the same proof as above, but ruling out anything this
    process happened to warm up (module-level caches, Qt's own globals)."""
    here = _capture_language("en")
    elsewhere = _capture_in_subprocess("en")
    assert here == elsewhere
