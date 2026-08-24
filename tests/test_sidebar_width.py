"""The sidebar's own width math, and the gate that keeps it honest.

``gui/widgets.py::sidebar_width_for_labels`` is a pure function: given the
labels the sidebar will render and the font it renders them in, it returns
the width the sidebar needs, clamped between a floor (today's hardcoded
176px, so English never moves) and a ceiling (so a pathological translation
cannot eat the window). The first half of this file covers that function's
own clamp behaviour directly.

The second half is the gate that would have caught the sidebar's defect
before a human did: it builds the real navigation list, per shipped
language, offscreen, and asks Qt's own ``sizeHintForColumn`` whether it
still fits the width the app computed -- deliberately not by re-running the
app's own arithmetic, which could only ever agree with itself.

Skipped where PySide6 is missing, and forces the offscreen platform before
any ``QtWidgets`` import -- see ``tests/test_settings_form.py`` for why both
matter.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

import os

# Forced, not defaulted. A desktop session exports QT_QPA_PLATFORM (xcb here),
# which the RPM build inherits — and then aborts, because the build sandbox
# can't reach that display. Tests must not depend on an ambient one.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from contextlib import contextmanager
from typing import Iterator

import shiboken6  # noqa: E402
from PySide6.QtCore import (  # noqa: E402
    QCoreApplication, QLocale, QObject, Qt, QTranslator, Signal,
)
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QPixmap  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QListWidget, QListWidgetItem,
)

from idasen_companion.core import i18n as core_i18n  # noqa: E402
from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import i18n, main_window as mw, service_ctl  # noqa: E402
from idasen_companion.gui.i18n import available_languages  # noqa: E402
from idasen_companion.gui.widgets import (  # noqa: E402
    SIDEBAR_WIDTH_CEILING, SIDEBAR_WIDTH_FLOOR, emphasize,
    sidebar_width_for_labels,
)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_short_labels_return_exactly_the_floor(qapp):
    label = QLabel()
    assert sidebar_width_for_labels(["Overview", "About"],
                                     label.font()) == SIDEBAR_WIDTH_FLOOR


def test_far_too_long_labels_return_exactly_the_ceiling(qapp):
    label = QLabel()
    absurd = "X" * 500
    assert sidebar_width_for_labels([absurd], label.font()) == SIDEBAR_WIDTH_CEILING


def test_a_midsize_label_list_lands_between_floor_and_ceiling_and_uses_demibold(qapp):
    label = QLabel()
    font = label.font()
    # Long enough to push past the floor, short of the ceiling -- chosen so
    # this assertion is about the clamp's open middle, not either edge.
    labels = ["Registro de actividad", "Automatización"]
    computed = sidebar_width_for_labels(labels, font)
    assert SIDEBAR_WIDTH_FLOOR < computed < SIDEBAR_WIDTH_CEILING

    # The DemiBold weight is genuinely in play: the helper's answer must
    # exceed what the *normal*-weight advance plus the same chrome would
    # give, proven here by computing the normal-weight advance directly
    # rather than by re-running emphasize().
    normal_metrics = QFontMetrics(font)
    normal_widest = max(normal_metrics.horizontalAdvance(text)
                         for text in labels)
    chrome = computed - max(
        QFontMetrics(emphasize(font)).horizontalAdvance(text)
        for text in labels)
    assert computed > normal_widest + chrome


def test_an_empty_label_list_returns_the_floor(qapp):
    label = QLabel()
    assert sidebar_width_for_labels([], label.font()) == SIDEBAR_WIDTH_FLOOR


# ================= Per-shipped-language fit =================
#
# Copied, not imported (tests/ carries no __init__.py): the FakeClient /
# _stub_autostart / _build_window trio is tests/test_theme_restyle.py's own,
# whose comment at its definition explains the same choice; the _language
# context manager is tests/test_baseline_vocabulary.py's.


class FakeClient(QObject):
    """Every signal MainWindow and its pages subscribe to, and nothing live.

    ``available`` stays False so no page attempts a D-Bus read during
    construction.
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
        return lambda *args, **kwargs: None


def _stub_autostart():
    """The unit is installed and enabled -- the banner's uninteresting case."""
    return service_ctl.AutostartState("enabled", True, "")


def _build_window(monkeypatch, tmp_path, language: str) -> mw.MainWindow:
    config_path = tmp_path / "config.toml"
    cfg = AppConfig()
    cfg.desk.mac = "E1:B2:C3:D4:E5:F6"
    # AppContext rebinds both catalogs from this value on every config
    # reload; writing it here (rather than relying on _language() alone)
    # is what stops a page visit from rebinding back to "system" mid-test.
    cfg.ui.language = language
    save_config(cfg, config_path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(service_ctl, "autostart_state", _stub_autostart)
    return mw.MainWindow(FakeClient(), tray_available=True)


@contextmanager
def _language(language: str) -> Iterator[None]:
    """Install exactly what a real run installs for ``language``, then undo
    it -- including any translator ``AppContext.reload_config`` installs of
    its own mid-test, which a fixed pre-recorded list of translators would
    miss."""
    app = QApplication.instance()
    previous_locale = QLocale()
    before = set(app.findChildren(QTranslator))
    if language == "en":
        QLocale.setDefault(QLocale("en_US"))
        core_i18n.set_language("en")
    else:
        i18n.apply_language(app, language)
    try:
        yield
    finally:
        after = set(app.findChildren(QTranslator))
        for translator in after - before:
            QCoreApplication.removeTranslator(translator)
            shiboken6.delete(translator)
        QLocale.setDefault(previous_locale)
        core_i18n.set_language(core_i18n.SYSTEM)


# Not the hardcoded ["en", "es"] the pre-existing baseline tests use --
# available_languages() is gui/pages/settings.py's own enumeration idiom, so
# a newly shipped language is covered the day its catalog lands.
@pytest.mark.parametrize("language", ["en", *available_languages()])
def test_every_shipped_language_fits_the_computed_sidebar_width(
        qapp, monkeypatch, tmp_path, language):
    with _language(language):
        window = _build_window(monkeypatch, tmp_path, language)
        try:
            # setFixedWidth sets minimum and maximum together; asserting
            # they agree also proves the sidebar is genuinely fixed, not
            # merely wide today.
            # pylint: disable=protected-access
            assert window._sidebar.minimumWidth() == window._sidebar.maximumWidth()
            computed_width = window._sidebar.minimumWidth()

            # The worst case any row can reach once selected: every item
            # DemiBold, not just the one _bold_selected_nav currently bolds.
            # A synthetic non-null icon at the real iconSize stands in for
            # the theme icon, rather than window._nav's own -- offscreen,
            # with no icon theme installed, QIcon.fromTheme resolves every
            # named icon to null (confirmed on this machine), and a null
            # icon leaves Qt's own icon/text gap unreserved in the size
            # hint. That would understate sizeHintForColumn(0) by exactly
            # the chrome this test exists to police, wherever it runs --
            # not only in a stripped CI container. A real desktop icon
            # theme fills that space in production; this stands in for it.
            worst_case_icon_size = window._nav.iconSize()
            pixmap = QPixmap(worst_case_icon_size)
            pixmap.fill(Qt.GlobalColor.transparent)
            worst_case_icon = QIcon(pixmap)

            worst_case = QListWidget()
            worst_case.setIconSize(worst_case_icon_size)
            worst_case.setStyleSheet(window._nav.styleSheet())
            metrics = QFontMetrics(emphasize(window._nav.font()))
            widest_label = ""
            widest_advance = -1
            for i in range(window._nav.count()):
                text = window._nav.item(i).text()
                item = QListWidgetItem(worst_case_icon, text)
                font = item.font()
                font.setWeight(QFont.Weight.DemiBold)
                item.setFont(font)
                worst_case.addItem(item)
                advance = metrics.horizontalAdvance(text)
                if advance > widest_advance:
                    widest_advance = advance
                    widest_label = text

            needed = worst_case.sizeHintForColumn(0)
            try:
                assert needed <= computed_width, (
                    f"{language!r}: Qt asked for {needed}px to fit every "
                    f"navigation label DemiBold (widest: {widest_label!r}), "
                    f"but the sidebar was only given {computed_width}px -- "
                    "raise SIDEBAR_WIDTH_CEILING or re-check the chrome "
                    "constants in gui/theme.py")
            finally:
                shiboken6.delete(worst_case)
        finally:
            window.close()
            shiboken6.delete(window)
