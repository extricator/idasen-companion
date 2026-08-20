"""The restyle registry: registration semantics, the palette-change trigger,
and the shared stylesheet-freshness helper later plans in this phase reuse.

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

import pytest

pytest.importorskip("PySide6")

import dataclasses  # noqa: E402
import os
import re
import warnings

# Forced, not defaulted. A desktop session exports QT_QPA_PLATFORM (xcb here),
# which the RPM build inherits — and then aborts, because the build sandbox
# can't reach that display. Tests must not depend on an ambient one.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import (  # noqa: E402
    QCoreApplication, QEvent, QObject, QSize, Signal,
)
from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QComboBox, QLabel, QLineEdit, QPushButton, QStyleFactory,
    QVBoxLayout, QWidget,
)

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import main_window as mw  # noqa: E402
from idasen_companion.gui import restyle, service_ctl  # noqa: E402
from idasen_companion.gui.pages import presets as presets_mod  # noqa: E402
from idasen_companion.gui.pages.about import AboutPage  # noqa: E402
from idasen_companion.gui.pages.activity_log import ActivityLogPage  # noqa: E402
from idasen_companion.gui.pages.automation import AutomationPage  # noqa: E402
from idasen_companion.gui.pages.overview import OverviewPage  # noqa: E402
from idasen_companion.gui.pages.presets import PresetsPage  # noqa: E402
from idasen_companion.gui.pages.settings import SettingsPage  # noqa: E402
from idasen_companion.gui.pages.statistics import StatisticsPage  # noqa: E402
from idasen_companion.gui.style import ControlStyle  # noqa: E402
from idasen_companion.gui.theme import Theme, theme  # noqa: E402
from idasen_companion.gui.widgets import (  # noqa: E402
    Card, ConnectionChip, DailyBarsChart, SegmentedControl, StatusDot,
    ToolIconButton, page_scroll, primary_button, section_label,
    selectable_icon, separator,
)

_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")

_LIGHT = {
    QPalette.ColorRole.Window: QColor("#f0f0f0"),
    QPalette.ColorRole.Base: QColor("#ffffff"),
    QPalette.ColorRole.WindowText: QColor("#000000"),
    QPalette.ColorRole.Text: QColor("#000000"),
}
_DARK = {
    QPalette.ColorRole.Window: QColor("#202326"),
    QPalette.ColorRole.Base: QColor("#141618"),
    QPalette.ColorRole.WindowText: QColor("#fcfcfc"),
    QPalette.ColorRole.Text: QColor("#fcfcfc"),
}


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated_registry(qapp):
    """Empty the registry before each test and undo its palette/trigger
    side effects after, so one test's registrations or palette flip can't
    leak into the next."""
    original_palette = QPalette(qapp.palette())
    restyle.reset_registry_for_tests()
    yield
    restyle.reset_registry_for_tests()
    # Most tests never call follow_palette(), so there is usually nothing
    # to disconnect; PySide6 both raises and warns in that case, so both
    # are swallowed here rather than only the exception.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            qapp.paletteChanged.disconnect(restyle.sweep)
        except (RuntimeError, TypeError):
            pass
    qapp.setPalette(original_palette)
    qapp.processEvents()


def flip_palette(qapp, dark: bool) -> None:
    """Install a light or dark palette and pump the event loop.

    Asserts the switch actually took, via `theme()`'s own lightness
    comparison, so a palette that failed to take is reported here rather
    than as a mystifying downstream failure.
    """
    roles = _DARK if dark else _LIGHT
    pal = QPalette(qapp.palette())
    for role, color in roles.items():
        pal.setColor(role, color)
    qapp.setPalette(pal)
    qapp.processEvents()
    assert theme().is_dark is dark, (
        f"palette flip to dark={dark} did not take -- theme().is_dark is "
        f"{theme().is_dark}")


def theme_hexes() -> set[str]:
    """Every current QColor token on Theme, as lowercase #rrggbb strings."""
    current = theme()
    return {
        getattr(current, field.name).name()
        for field in dataclasses.fields(Theme)
        if field.name != "is_dark"
    }


def assert_hexes_are_current_tokens(root: QWidget) -> None:
    """Every #rrggbb literal in `root`'s and its descendants' stylesheets
    must be a member of the theme's *current* tokens."""
    current_hexes = theme_hexes()
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        for hex_literal in _HEX_RE.findall(widget.styleSheet()):
            assert hex_literal.lower() in current_hexes, (
                f"{type(widget).__name__}#{widget.objectName()} still "
                f"names {hex_literal}, which is not a current theme token"
            )


def test_register_runs_once_at_registration_and_again_on_each_sweep(qapp):
    owner = QObject()
    calls: list[None] = []
    restyle.register(owner, lambda: calls.append(None))

    assert len(calls) == 1

    restyle.sweep()
    restyle.sweep()

    assert len(calls) == 3


def test_a_destroyed_owner_is_no_longer_swept(qapp):
    owner = QObject()
    calls: list[None] = []
    restyle.register(owner, lambda: calls.append(None))
    assert len(calls) == 1

    owner.deleteLater()
    # processEvents() alone does not process a DeferredDelete event -- Qt
    # only sends those through sendPostedEvents(None, DeferredDelete).
    # Measured: two bare processEvents() calls leave `owner` alive.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()

    restyle.sweep()  # must not raise on the deleted C++ object

    assert len(calls) == 1


def test_registering_during_a_sweep_does_not_raise(qapp):
    outer_owner = QObject()

    def register_another() -> None:
        inner_owner = QObject()
        restyle.register(inner_owner, lambda: None)
        inner_owner.setParent(outer_owner)  # keep it alive past this call

    restyle.register(outer_owner, register_another)

    restyle.sweep()  # must not raise


def test_a_palette_change_runs_every_registered_restyler(qapp):
    owner = QObject()
    calls: list[None] = []
    restyle.register(owner, lambda: calls.append(None))
    before = len(calls)

    restyle.follow_palette(qapp)
    flip_palette(qapp, dark=True)

    assert len(calls) > before, (
        "changing the application palette did not run the registered "
        "restylers -- the paletteChanged trigger did not fire")


def test_a_card_follows_a_live_light_to_dark_switch(qapp):
    flip_palette(qapp, dark=False)
    card = Card()
    card.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)

    flip_palette(qapp, dark=True)

    assert theme().card_bg.name() in card.styleSheet(), (
        "Card's stylesheet still names the pre-switch colour -- the "
        "rebuild did not run")
    assert_hexes_are_current_tokens(card)


def test_a_card_follows_a_live_dark_to_light_switch(qapp):
    flip_palette(qapp, dark=True)
    card = Card()
    card.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)

    flip_palette(qapp, dark=False)

    assert theme().card_bg.name() in card.styleSheet(), (
        "Card's stylesheet still names the pre-switch colour -- the "
        "rebuild did not run")
    assert_hexes_are_current_tokens(card)


def test_section_label_follows_a_live_light_to_dark_switch(qapp):
    flip_palette(qapp, dark=False)
    label = section_label("Section")
    label.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)

    flip_palette(qapp, dark=True)

    assert theme().muted.name() in label.styleSheet()
    assert_hexes_are_current_tokens(label)


def test_section_label_follows_a_live_dark_to_light_switch(qapp):
    flip_palette(qapp, dark=True)
    label = section_label("Section")
    label.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)

    flip_palette(qapp, dark=False)

    assert theme().muted.name() in label.styleSheet()
    assert_hexes_are_current_tokens(label)


def test_separator_follows_a_live_light_to_dark_switch(qapp):
    flip_palette(qapp, dark=False)
    line = separator()
    line.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)

    flip_palette(qapp, dark=True)

    assert theme().separator.name() in line.styleSheet()
    assert_hexes_are_current_tokens(line)


def test_primary_button_follows_a_live_light_to_dark_switch(qapp):
    flip_palette(qapp, dark=False)
    button = primary_button("Go")
    button.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)

    flip_palette(qapp, dark=True)

    assert theme().accent_fill.name() in button.styleSheet()
    assert_hexes_are_current_tokens(button)


def test_connection_chip_follows_a_live_light_to_dark_switch(qapp):
    flip_palette(qapp, dark=False)
    chip = ConnectionChip()
    chip.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)

    flip_palette(qapp, dark=True)

    assert theme().window.name() in chip.styleSheet(), (
        "ConnectionChip's own stylesheet still names the pre-switch colour")
    assert theme().secondary.name() in chip.label.styleSheet(), (
        "ConnectionChip's label stylesheet still names the pre-switch colour")
    assert_hexes_are_current_tokens(chip)


def test_segmented_control_follows_a_live_light_to_dark_switch(qapp):
    flip_palette(qapp, dark=False)
    control = SegmentedControl(["One", "Two", "Three"])
    control.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)

    flip_palette(qapp, dark=True)

    buttons = control.findChildren(QPushButton)
    assert len(buttons) == 3, "expected all three segment buttons to exist"
    # Every button, not just the first -- a restyler that closed over the
    # loop variable instead of binding it as a default argument would leave
    # every entry pointing at the last button, invisible if only one is
    # checked.
    for button in buttons:
        assert theme().card_bg.name() in button.styleSheet(), (
            f"segment button {button.text()!r} still names the "
            "pre-switch colour")
    assert_hexes_are_current_tokens(control)


def test_tool_icon_button_follows_a_live_light_to_dark_switch(qapp):
    flip_palette(qapp, dark=False)
    button = ToolIconButton(QIcon(), "tooltip", fallback="x")
    button.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)

    flip_palette(qapp, dark=True)

    assert theme().separator.name() in button.styleSheet()
    assert_hexes_are_current_tokens(button)


def test_page_scroll_viewport_follows_a_live_light_to_dark_switch(qapp):
    flip_palette(qapp, dark=False)
    scroll, _layout = page_scroll()
    scroll.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)

    flip_palette(qapp, dark=True)

    viewport = scroll.viewport()
    # The viewport fill is a QPalette colour, not a stylesheet string --
    # asserting the palette role is the actual mechanism page_scroll uses.
    assert viewport.palette().color(viewport.backgroundRole()) == theme().window


def _scrolling_page(qapp):
    """A page with enough cards to need a scrollbar, shown and laid out."""
    scroll, layout = page_scroll()
    for index in range(14):
        card = Card()
        card._restyle()  # pylint: disable=protected-access
        card.body.addWidget(QLabel(f"row {index}"))
        layout.addWidget(card)
    host = QWidget()
    box = QVBoxLayout(host)
    box.setContentsMargins(0, 0, 0, 0)
    box.addWidget(scroll)
    host.resize(300, 200)
    host.show()
    qapp.processEvents()
    return host, scroll


def _scrollbar_colours(qapp, page=None) -> list:
    """Every colour a scrolling page's vertical scrollbar renders, with
    counts -- the whole bar, since which part of it goes stale is Fusion's
    business rather than this app's."""
    host, scroll = page if page is not None else _scrolling_page(qapp)
    bar = scroll.verticalScrollBar()
    origin = bar.mapTo(host, bar.rect().topLeft())
    image = host.grab().toImage()
    counts: dict[str, int] = {}
    for y in range(origin.y(), origin.y() + bar.height()):
        for x in range(origin.x(), origin.x() + bar.width()):
            key = image.pixelColor(x, y).name()
            counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items())


def test_a_scrollbar_follows_a_live_light_to_dark_switch(qapp):
    """A scrolling page's scrollbar has to end up where a fresh one starts.

    The app draws no part of a scrollbar -- Fusion does, from the palette
    -- so this looks like it could not fail, and it did. A widget under a
    stylesheet is rendered by ``QStyleSheetStyle``, which caches the rules
    it resolved for that widget and its descendants, and a palette change
    does not invalidate that cache while setting a stylesheet does. The
    scroll area's transparency rule names no colour, so nothing ever
    re-set it, and the bar kept the colours it resolved at construction:
    reported from the installed package as a scrollbar that stayed light
    in dark mode until the app was relaunched.

    Asserted against a *freshly built* dark page rather than against any
    colour of this test's choosing, because what the bar should look like
    is Fusion's business, and only the app's failure to let it repaint is
    this app's.
    """
    flip_palette(qapp, dark=False)
    page = _scrolling_page(qapp)
    restyle.follow_palette(qapp)

    flip_palette(qapp, dark=True)
    switched = _scrollbar_colours(qapp, page)
    fresh = _scrollbar_colours(qapp)

    assert switched == fresh, (
        "a scrollbar switched live to dark renders differently from one "
        f"built dark: switched {switched[:4]} against fresh {fresh[:4]} "
        "-- it is still painting the colours it resolved under the old "
        "palette")


def test_a_status_dot_with_no_explicit_color_follows_the_switch(qapp):
    flip_palette(qapp, dark=False)
    dot = StatusDot()
    restyle.follow_palette(qapp)

    flip_palette(qapp, dark=True)

    # pylint: disable=protected-access
    assert dot._color == theme().muted, (
        "a StatusDot built with no explicit colour did not follow the "
        "switch to the new theme().muted")


def test_a_status_dot_with_an_explicit_color_is_not_reset_by_the_switch(qapp):
    flip_palette(qapp, dark=False)
    dot = StatusDot()
    error_color = theme().error
    dot.set_color(error_color)
    restyle.follow_palette(qapp)

    flip_palette(qapp, dark=True)

    # pylint: disable=protected-access
    assert dot._color == error_color, (
        "a StatusDot coloured by a domain event was reset by the sweep -- "
        "a dot currently showing a real error would go grey on a theme "
        "switch")


# ================= Window shell (main_window.py) =================
#
# A full MainWindow needs a config on disk and systemd stubbed out, exactly
# as tests/test_window_reopen.py's own fixtures do. Copied rather than
# imported -- tests/ carries no __init__.py, so importing across sibling
# test modules would rely on pytest's rootdir insertion rather than a real
# package, and no other test module in this suite does that.


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


def _build_window(monkeypatch, tmp_path, tray_available: bool,
                  client: FakeClient | None = None) -> mw.MainWindow:
    """A MainWindow wired offline, with no tray by default so the no-tray
    hint (one of D-09's four sites) is built."""
    config_path = tmp_path / "config.toml"
    cfg = AppConfig()
    cfg.desk.mac = "E1:B2:C3:D4:E5:F6"
    save_config(cfg, config_path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(service_ctl, "autostart_state", _stub_autostart)
    return mw.MainWindow(client or FakeClient(), tray_available=tray_available)


def _hint_label(window: mw.MainWindow) -> QLabel:
    # gui/pages/settings.py has its own, differently-worded "no tray" label
    # -- match on wording unique to the shell's hint (main_window.py), not
    # the "No system tray detected" prefix both share.
    return next(label for label in window.findChildren(QLabel)
                if "AppIndicator extension" in label.text())


def test_the_shell_follows_a_live_light_to_dark_switch(qapp, monkeypatch, tmp_path):
    flip_palette(qapp, dark=False)
    window = _build_window(monkeypatch, tmp_path, tray_available=False)
    window.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)
    try:
        flip_palette(qapp, dark=True)

        # Scoped to the sidebar subtree (sidebar, nav list, footer dot and
        # label) rather than the whole window: the seven pages this shell
        # hosts carry their own theme-derived stylesheets, most still frozen
        # at construction until later plans in this phase convert them, so
        # asserting over the full tree would fail on surfaces this plan
        # doesn't touch.
        assert_hexes_are_current_tokens(window._sidebar)  # pylint: disable=protected-access
        # pylint: disable=protected-access
        assert theme().sidebar_bg.name() in window._sidebar.styleSheet(), (
            "the sidebar's stylesheet still names the pre-switch colour")
        assert theme().accent.name() in window._nav.styleSheet(), (
            "the nav list's stylesheet still names the pre-switch colour")
        assert theme().secondary.name() in window._conn_footer.styleSheet(), (
            "the connection footer's stylesheet still names the "
            "pre-switch colour")
    finally:
        window.close()


def test_a_sidebar_icon_recolours_both_of_its_states(qapp):
    """``selectable_icon`` must actually *use* the resting colour, not
    merely accept it.

    The test below monkeypatches this function to record what
    ``MainWindow`` passes it, which says nothing about what it does with
    the value -- and what it used to do was ignore it: the resting glyph
    was rendered uncoloured, straight from the icon theme. That made it
    the one thing in the sidebar not derived from the palette, so on a
    live switch to dark it stayed dark-on-dark until the app was
    relaunched. Reported from the installed package.

    Built from a solid pixmap rather than from the icon theme, because the
    offscreen platform resolves no theme at all and ``selectable_icon``
    returns a null icon untouched.
    """
    flip_palette(qapp, dark=False)
    solid = QPixmap(22, 22)
    solid.fill(QColor("#000000"))
    resting, selected = QColor("#112233"), QColor("#445566")

    built = selectable_icon(QIcon(solid), selected, resting)

    for mode, expected, label in (
            (QIcon.Mode.Normal, resting, "resting"),
            (QIcon.Mode.Selected, selected, "selected")):
        image = built.pixmap(QSize(22, 22), 1.0, mode).toImage()
        opaque = {image.pixelColor(x, y).name()
                  for x in range(image.width())
                  for y in range(image.height())
                  if image.pixelColor(x, y).alpha() > 0}
        assert opaque == {expected.name()}, (
            f"a sidebar icon's {label} glyph renders {sorted(opaque)} "
            f"rather than the {expected.name()} it was given -- that state "
            "is not being recoloured, so it cannot follow the palette")


def test_the_nav_icons_are_retinted_on_a_live_switch(qapp, monkeypatch, tmp_path):
    flip_palette(qapp, dark=False)
    window = _build_window(monkeypatch, tmp_path, tray_available=False)
    window.show()
    qapp.processEvents()

    recorded: list = []

    def _recording_selectable_icon(base, selected_color, resting_color):
        recorded.append((selected_color, resting_color))
        return base

    monkeypatch.setattr(mw, "selectable_icon", _recording_selectable_icon)
    try:
        flip_palette(qapp, dark=True)
        # A live palette change reaches every MainWindow still registered
        # from any other test module's un-torn-down fixture, not just this
        # one -- restyle.py's registry is a process-wide singleton, and
        # this file's own _isolated_registry autouse fixture only owns
        # tests within this module. Discard whatever that broader sweep
        # recorded, then call this window's own restyler directly so the
        # count assertion below reflects only this window's NAV_ITEMS.
        recorded.clear()
        window._restyle_sidebar()  # pylint: disable=protected-access

        # Both states, not just the selected one. The resting glyph was the
        # icon theme's own, uncoloured, which made it the one thing in the
        # sidebar that did not follow the palette: on a live switch to dark
        # it stayed dark-on-dark until the app was relaunched.
        expected = (theme().selection_text, theme().text)
        assert recorded == [expected] * len(mw.NAV_ITEMS), (
            "the sidebar's icons were not re-tinted once per NAV_ITEMS "
            "entry to the post-switch selected *and* resting colours")
    finally:
        window.close()


def test_a_selected_sidebar_row_is_the_desktops_own_selection(
        qapp, monkeypatch, tmp_path):
    """The selected nav row fills with the desktop's Highlight at full
    strength and labels itself in its HighlightedText partner.

    Settled on after four tinted alternatives were built and judged on
    the real desktop, and it is worth knowing that none of them was
    rejected for being *wrong*: the last one measured correctly on both
    schemes and matched a primary button's own weight. The maintainer
    preferred the full-strength row anyway. That is a look decision and
    nothing here can adjudicate it, which is why this test asserts only
    which tokens the rail uses.

    What the tinted attempts did settle, and what stays settled, is that
    a tint of the accent is the harder thing to get right: it has to be
    laid on the surface the row is actually drawn on or it lands on the
    wrong side of the strip, and it desaturates if that surface is grey.
    The full-strength pair sidesteps both by not being derived at all.

    ``accent_fill`` is asserted absent rather than merely unequal,
    because the failure worth catching is a partial revert -- putting a
    tint back on the fill while leaving the label on ``selection_text``
    produces a row whose text is chosen to read on a saturated
    background and is then drawn on a pale one.
    """
    flip_palette(qapp, dark=True)
    window = _build_window(monkeypatch, tmp_path, tray_available=False)
    window.show()
    qapp.processEvents()
    try:
        sheet = window._nav.styleSheet()  # pylint: disable=protected-access
        tokens = theme()
        assert tokens.accent.name() in sheet, (
            f"a selected nav row does not fill with the desktop's own "
            f"selection colour ({tokens.accent.name()}); the sheet is "
            f"{sheet}")
        assert tokens.selection_text.name() in sheet, (
            f"a selected nav row does not label itself in the desktop's "
            f"own selected-text colour ({tokens.selection_text.name()}); "
            f"the sheet is {sheet}")
        assert tokens.accent_fill.name() not in sheet, (
            f"a selected nav row names the emphasis tint "
            f"({tokens.accent_fill.name()}) -- the row has gone back to "
            "being a tint, or half of it has")
    finally:
        window.close()


def test_the_banner_and_hint_carry_theme_tokens_on_a_live_switch(
        qapp, monkeypatch, tmp_path):
    flip_palette(qapp, dark=False)
    window = _build_window(monkeypatch, tmp_path, tray_available=False)
    window.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)
    try:
        flip_palette(qapp, dark=True)

        hint = _hint_label(window)
        current_tokens = theme_hexes()
        for widget in (window._daemon_banner, hint):  # pylint: disable=protected-access
            hexes = {h.lower() for h in _HEX_RE.findall(widget.styleSheet())}
            assert hexes, f"{type(widget).__name__} carries no hex colour at all"
            assert hexes <= current_tokens, (
                f"{type(widget).__name__} still names a colour outside the "
                "current theme's tokens")
        assert theme().error.name() in window._daemon_banner.styleSheet()  # pylint: disable=protected-access
        assert theme().muted.name() in hint.styleSheet()
    finally:
        window.close()


# ================= About, Activity Log, Automation, Settings =================
#
# These four pages build their theme-derived widgets once, at construction,
# and never destroy or rebuild them -- exactly the shape 08-01's registry was
# built for. FakeClient (above) supplies every signal each page's __init__
# connects to; none of them read ctx.cfg before load() is called, so no
# on-disk config is needed to construct one.


def _build_ctx() -> context_mod.AppContext:
    return context_mod.AppContext(FakeClient(), tray_available=True)


def test_the_about_page_follows_a_live_light_to_dark_switch(qapp):
    flip_palette(qapp, dark=False)
    page = AboutPage(_build_ctx())
    page.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)
    try:
        flip_palette(qapp, dark=True)

        assert_hexes_are_current_tokens(page)

        secondary_hex = theme().secondary.name()
        secondary_labels = [
            label for label in page.findChildren(QLabel)
            if f"color: {secondary_hex}" in label.styleSheet()]
        assert secondary_labels, (
            "no About-page label (tagline, version, meta) carries the "
            "post-switch secondary token")

        text_hex = theme().text.name()
        text_labels = [
            label for label in page.findChildren(QLabel)
            if f"color: {text_hex}" in label.styleSheet()]
        assert text_labels, (
            "the commands label does not carry the post-switch text token")
    finally:
        page.close()


def test_the_activity_log_page_follows_a_live_light_to_dark_switch(qapp):
    flip_palette(qapp, dark=False)
    page = ActivityLogPage(_build_ctx())
    page.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)
    try:
        flip_palette(qapp, dark=True)

        assert_hexes_are_current_tokens(page)

        chip_style = page._journal_chip.styleSheet()  # pylint: disable=protected-access
        assert theme().hover.name() in chip_style, (
            "the journal chip does not carry the post-switch hover token")
        assert theme().border.name() in chip_style, (
            "the journal chip does not carry the post-switch border token")
    finally:
        page.close()


def test_the_automation_page_follows_a_live_light_to_dark_switch(qapp):
    flip_palette(qapp, dark=False)
    page = AutomationPage(_build_ctx())
    page.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)
    try:
        flip_palette(qapp, dark=True)

        assert_hexes_are_current_tokens(page)

        # Every day, not just the last one built -- a restyler that closed
        # over the loop variable instead of binding it as a default argument
        # would leave every chip restyling only the last day.
        accent_border_hex = theme().accent_border.name()
        for day, chip in page.day_checks.items():
            assert accent_border_hex in chip.styleSheet(), (
                f"the {day} chip does not carry the post-switch "
                "accent_border token")
    finally:
        page.close()


def test_the_settings_page_follows_a_live_light_to_dark_switch(qapp):
    flip_palette(qapp, dark=False)
    page = SettingsPage(_build_ctx())
    page.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)
    try:
        flip_palette(qapp, dark=True)

        assert_hexes_are_current_tokens(page)

        # The Language row's help label, a _settings_row help_label.
        language_help = next(
            label for label in page.findChildren(QLabel)
            if label.text() == "Applies after you restart the app")
        assert theme().muted.name() in language_help.styleSheet(), (
            "the settings row's help label does not carry the post-switch "
            "muted token")

        # language_combo is a _themed_combo.
        assert isinstance(page.language_combo, QComboBox)
        assert theme().card_bg.name() in page.language_combo.styleSheet(), (
            "the themed combo's popup does not carry the post-switch "
            "card_bg token")
    finally:
        page.close()


def test_a_scrolling_pages_transparency_rule_does_not_unframe_its_controls(
        qapp):
    """The scroll body's own stylesheet must be qualified by object name.

    An unqualified rule applies to its widget *and every descendant*, and a
    stylesheet that names a background takes that widget off its style's box
    model -- where the border defaults to none. So a bare
    ``background: transparent`` on the scroll body silently unframed every
    control inside a scrolling page that the app does not draw itself.

    It shipped, and it was invisible for two reasons worth recording. The
    style draws the combo, spin and checkbox frames outright, so the only
    controls left exposed were the two it deliberately leaves to Fusion --
    and of those, only ``QLineEdit`` appears on a scrolling page. And the
    defect subtracts a border rather than adding anything, so every
    assertion about what *is* drawn stayed green. Reported from the
    installed package on the Settings page: the Bluetooth address field
    rendered with no box at all, only a stray line above it.

    Asserted on the real page rather than on a synthetic scroll area,
    because the bug was in how the pieces nest and a hand-built pair would
    have reproduced whichever nesting the test author had in mind.
    """
    flip_palette(qapp, dark=False)
    page = SettingsPage(_build_ctx())
    page.resize(680, 900)
    page.show()
    qapp.processEvents()
    qapp.processEvents()

    field = page.mac_edit
    image = page.grab().toImage()
    origin = field.mapTo(page, field.rect().topLeft())
    width, height = field.width(), field.height()
    card = theme().card_bg

    def painted_in_row(y: int) -> int:
        return sum(image.pixelColor(origin.x() + x, y) != card
                   for x in range(width))

    def painted_in_column(x: int) -> int:
        return sum(image.pixelColor(x, origin.y() + y) != card
                   for y in range(height))

    edges = {
        "top": painted_in_row(origin.y()),
        "bottom": painted_in_row(origin.y() + height - 1),
        "left": painted_in_column(origin.x()),
        "right": painted_in_column(origin.x() + width - 1),
    }
    missing = [name for name, count in edges.items() if count == 0]
    assert not missing, (
        f"the Bluetooth address field draws nothing on its {missing} "
        f"edge(s) -- measured {edges} against the card behind it "
        f"({card.name()}). Something in its ancestry has taken it off the "
        "style's box model, which is what an unqualified background rule "
        "does to every descendant")


# ================= Overview =================
#
# Built directly against the same FakeClient / _build_ctx() this module
# already uses for About/Activity Log/Automation/Settings -- nothing here
# needs an on-disk config, so tests/test_overview_countdown.py's fixture
# (which loads one for its own, unrelated reason) isn't required.


def test_the_overview_page_follows_a_live_light_to_dark_switch(qapp):
    flip_palette(qapp, dark=False)
    page = OverviewPage(_build_ctx())
    page.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)
    try:
        flip_palette(qapp, dark=True)

        assert_hexes_are_current_tokens(page)

        secondary_hex = theme().secondary.name()
        assert secondary_hex in page.height_label.styleSheet(), (
            "height_label does not carry the post-switch secondary token")
        assert secondary_hex in page.status_reason.styleSheet(), (
            "status_reason does not carry the post-switch secondary token")
        assert theme().accent.name() in page.countdown_bar.styleSheet(), (
            "countdown_bar does not carry the post-switch accent token")
        assert theme().muted.name() in page.progress_caption.styleSheet(), (
            "progress_caption does not carry the post-switch muted token")
    finally:
        page.close()


def test_all_three_countdown_labels_follow_a_live_switch_individually(qapp):
    flip_palette(qapp, dark=False)
    page = OverviewPage(_build_ctx())
    page.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)
    try:
        flip_palette(qapp, dark=True)

        secondary_hex = theme().secondary.name()
        # Each asserted on its own -- the three used to share one locally
        # computed stylesheet string, so a registration closing over only
        # one of them would still pass if only that one were checked here.
        assert secondary_hex in page.countdown_in_lbl.styleSheet(), (
            "countdown_in_lbl does not carry the post-switch secondary token")
        assert secondary_hex in page.countdown_time_word.styleSheet(), (
            "countdown_time_word does not carry the post-switch secondary "
            "token")
        assert secondary_hex in page.countdown_of_lbl.styleSheet(), (
            "countdown_of_lbl does not carry the post-switch secondary token")
    finally:
        page.close()


def test_the_stop_button_is_correct_in_both_states_after_a_live_switch(qapp):
    flip_palette(qapp, dark=False)
    page = OverviewPage(_build_ctx())
    page.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)
    try:
        # Idle: a switch must leave the button unstyled, not repaint it in
        # the moving state's colour.
        page.client.movingChanged.emit(False)
        flip_palette(qapp, dark=True)
        assert page.stop_btn.styleSheet() == "", (
            "a resting desk's Stop button carries a stylesheet after a "
            "switch -- a colour-only restyler would show the moving "
            "state's colour on a resting desk")

        # Moving: a switch must carry the *new* scheme's error token.
        page.client.movingChanged.emit(True)
        flip_palette(qapp, dark=False)
        assert theme().error.name() in page.stop_btn.styleSheet(), (
            "a moving desk's Stop button does not carry the post-switch "
            "error token")
    finally:
        page.close()


def test_a_switch_does_not_change_the_reported_automation_status(qapp):
    flip_palette(qapp, dark=False)
    page = OverviewPage(_build_ctx())
    page.show()
    qapp.processEvents()
    page.client.statusChanged.emit("active")
    restyle.follow_palette(qapp)
    try:
        head_before = page.status_head_lbl.text()

        flip_palette(qapp, dark=True)

        assert page.status_head_lbl.text() == head_before, (
            "a palette switch changed the reported automation status")
        # pylint: disable=protected-access
        assert page.status_dot._color == theme().success, (
            "the status dot did not follow the switch to the new "
            "theme().success")
    finally:
        page.close()


# ================= Presets and Statistics (rebuild-on-refresh) =================
#
# Both pages destroy and rebuild their rows at runtime -- Presets on every
# presetsChanged, Statistics on every _refresh -- which is exactly the shape
# 08-01's destroyed-signal-backed registry exists for. No plan in this phase
# adds a deregister pass; these tests hold that claim to an assertion rather
# than a design intention: the registry returns to its prior size across a
# rebuild, and a sweep run right after raises nothing.

_PRESETS = {"sit": 0.62, "perch": 0.95, "stand": 1.14}
_PRESETS_REBUILT = {"sit": 0.62, "lean": 0.80, "stand": 1.14}
_TRANSITIONS = [
    (1_700_000_000.0, "sitting", "standing", "manual", False),
    (1_700_000_500.0, "standing", "sitting", "automation", True),
]


class _StatsFakeClient(FakeClient):
    """FakeClient plus the two blocking reads StatisticsPage._refresh makes."""

    available = True

    def __init__(self):
        super().__init__()
        self.transitions: list[tuple] = list(_TRANSITIONS)

    def get_daily_stats(self, start, end):
        return []

    def get_transitions(self, limit=50):
        return list(self.transitions)


def _build_presets_page() -> PresetsPage:
    return PresetsPage(_build_ctx())


def _build_stats_page() -> tuple[StatisticsPage, _StatsFakeClient]:
    client = _StatsFakeClient()
    page = StatisticsPage(context_mod.AppContext(client, tray_available=True))
    return page, client


def _name_edits(page: PresetsPage) -> list[QLineEdit]:
    return page.findChildren(QLineEdit)


def _height_labels(page: PresetsPage) -> list[QLabel]:
    return [label for label in page.findChildren(QLabel)
            if "padding-left: 4px" in label.styleSheet()]


def test_the_presets_page_follows_a_live_switch_including_rebuilt_rows(qapp):
    flip_palette(qapp, dark=False)
    page = _build_presets_page()
    page.show()
    page.client.presetsChanged.emit(_PRESETS)
    qapp.processEvents()
    restyle.follow_palette(qapp)
    try:
        flip_palette(qapp, dark=True)

        assert_hexes_are_current_tokens(page)

        accent_border_hex = theme().accent_border.name()
        name_edits = _name_edits(page)
        assert name_edits, "no preset row was built"
        assert any(accent_border_hex in edit.styleSheet()
                  for edit in name_edits), (
            "no row's name_edit carries the post-switch accent_border token")

        secondary_hex = theme().secondary.name()
        height_labels = _height_labels(page)
        assert height_labels, "no preset row's height_label was found"
        assert all(secondary_hex in label.styleSheet()
                  for label in height_labels), (
            "a row's height_label does not carry the post-switch "
            "secondary token")
    finally:
        page.close()


def test_the_statistics_page_follows_a_live_switch_including_rebuilt_rows(qapp):
    flip_palette(qapp, dark=False)
    page, _client = _build_stats_page()
    page.show()
    page.on_shown()
    qapp.processEvents()
    restyle.follow_palette(qapp)
    try:
        flip_palette(qapp, dark=True)

        assert_hexes_are_current_tokens(page)

        muted_hex = theme().muted.name()
        assert muted_hex in page.stats_footer.styleSheet(), (
            "stats_footer does not carry the post-switch muted token")

        secondary_hex = theme().secondary.name()
        # "when" is the fixed-width timestamp label -- match on the style
        # rule set alongside it, since QLabel carries no other identifying
        # attribute here.
        when_labels = [label for label in page.findChildren(QLabel)
                       if label.styleSheet().startswith("color:")
                       and secondary_hex in label.styleSheet()]
        assert when_labels, (
            "no transition row's 'when' label carries the post-switch "
            "secondary token")
    finally:
        page.close()


def test_the_presets_registry_returns_to_its_prior_size_across_a_rebuild(qapp):
    page = _build_presets_page()
    page.show()
    page.client.presetsChanged.emit(_PRESETS)
    qapp.processEvents()
    before = len(restyle._registry)  # pylint: disable=protected-access

    page.client.presetsChanged.emit(_PRESETS_REBUILT)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()

    after = len(restyle._registry)  # pylint: disable=protected-access
    assert after == before, (
        f"the registry grew across a rebuild ({before} -> {after}) -- a "
        "torn-down row's entries were not dropped")

    restyle.sweep()  # must not raise on a deleted C++ object
    page.close()


def test_the_statistics_registry_returns_to_its_prior_size_across_a_rebuild(qapp):
    page, client = _build_stats_page()
    page.show()
    page.on_shown()
    qapp.processEvents()
    before = len(restyle._registry)  # pylint: disable=protected-access

    client.transitions = list(reversed(_TRANSITIONS))
    page.on_shown()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()

    after = len(restyle._registry)  # pylint: disable=protected-access
    assert after == before, (
        f"the registry grew across a rebuild ({before} -> {after}) -- a "
        "torn-down transition row's entries were not dropped")

    restyle.sweep()  # must not raise on a deleted C++ object
    page.close()


def test_a_preset_row_built_after_the_switch_carries_dark_tokens(qapp):
    flip_palette(qapp, dark=True)
    page = _build_presets_page()
    page.show()
    page.client.presetsChanged.emit(_PRESETS)
    qapp.processEvents()
    try:
        accent_border_hex = theme().accent_border.name()
        secondary_hex = theme().secondary.name()
        assert any(accent_border_hex in edit.styleSheet()
                  for edit in _name_edits(page)), (
            "a row built after a dark switch does not carry the dark "
            "accent_border token")
        assert any(secondary_hex in label.styleSheet()
                  for label in _height_labels(page)), (
            "a row built after a dark switch does not carry the dark "
            "secondary token")
    finally:
        page.close()


def test_the_legend_dots_follow_a_live_switch_in_the_charts_own_order(qapp):
    flip_palette(qapp, dark=False)
    page, _client = _build_stats_page()
    page.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)
    dots = page.findChildren(StatusDot)
    assert len(dots) >= 2, "expected at least the two legend dots"
    legend_dots = dots[:2]
    try:
        flip_palette(qapp, dark=True)

        expected = DailyBarsChart.series_colors()
        for dot, expected_color in zip(legend_dots, expected):
            # pylint: disable=protected-access
            assert dot._color == expected_color, (
                "a legend dot does not carry the post-switch "
                "series_colors() pair, in the chart's own order")
    finally:
        page.close()


def test_the_tinted_row_icon_is_re_tinted_on_a_live_switch(qapp, monkeypatch):
    flip_palette(qapp, dark=False)
    page = _build_presets_page()
    page.show()
    page.client.presetsChanged.emit(_PRESETS)
    qapp.processEvents()
    restyle.follow_palette(qapp)

    recorded: list = []

    def _recording_tinted_icon(base, color, size=16):
        recorded.append(color)
        return base

    monkeypatch.setattr(presets_mod, "tinted_icon", _recording_tinted_icon)
    try:
        recorded.clear()
        flip_palette(qapp, dark=True)

        assert recorded, "the row's move icon was never re-tinted"
        assert recorded[-1] == theme().accent, (
            "the row's move icon was not re-tinted to the post-switch "
            "accent token")
    finally:
        page.close()


# ================= Whole-window standing invariant =================
#
# Everything above proves one construct or one page was converted. This
# section proves nothing was *missed*: build a full MainWindow (all seven
# pages, the shell, both rebuild-on-refresh pages actually holding rows) and
# require every stylesheet in the whole tree to name only the current
# theme's tokens, in both switch directions. A future label added anywhere
# with a hardcoded hex fails here even though no page-specific test was ever
# written for it.
#
# An AST-based script over gui/*.py was considered instead (walk every
# setStyleSheet( call whose argument reads a theme value, assert it sits
# inside a conventionally named function) and declined: it cannot see the
# sites that already hid from a source-level read during this sweep (a
# token read into a local several lines above the call, a baked icon tint,
# a StatusDot colour -- none of which is a setStyleSheet call at all), it
# would have to couple to a naming convention that legitimately has three
# different shapes across the sites this phase converted (a bound method, a
# factory-local closure, an existing domain-event handler registered
# as-is), and a test importing anything under scripts/ needs its own entry
# in this project's sdist manifest or the RPM's install check dies at
# collection while every local run stays green. The runtime check below has
# none of those blind spots: it looks at what a widget actually carries, so
# a stale hex fails however it got there.


class _WholeWindowFakeClient(FakeClient):
    """FakeClient, but available -- so MainWindow's own
    ``client.availableChanged.emit(client.available)`` at construction
    refreshes the Statistics page for free, the same two blocking reads
    ``_StatsFakeClient`` above supplies for the page-level test."""

    available = True

    def get_daily_stats(self, start, end):
        return []

    def get_transitions(self, limit=50):
        return list(_TRANSITIONS)


def _build_populated_window(monkeypatch, tmp_path) -> mw.MainWindow:
    """A MainWindow whose two rebuild-on-refresh pages already hold rows.

    Presets gets two presets, one of them ("perch") user-created, which
    populates a pill (the current-height chip), a separator between the two
    rows, and a tinted_icon row button (the move-to button) -- Statistics
    already refreshes at construction here, since the client reports
    available, and its sample data carries one interrupted transition.
    """
    window = _build_window(
        monkeypatch, tmp_path, tray_available=False,
        client=_WholeWindowFakeClient())
    window.client.presetsChanged.emit(_PRESETS)
    return window


def _find_border_pixel(image, y: int, card_bg_hex: str):
    """The first non-background, non-transparent pixel scanning left to
    right at row ``y``. Copied from tests/test_control_contrast.py -- see
    that module's own FakeClient docstring for why this isn't imported."""
    for x in range(image.width()):
        pixel = image.pixelColor(x, y)
        if pixel.alpha() != 0 and pixel.name() != card_bg_hex:
            return pixel
    raise AssertionError(
        "no border-coloured pixel found scanning the indicator row -- "
        "the whole row reads as the card background")


def test_the_whole_window_follows_a_live_switch_in_both_directions(
        qapp, monkeypatch, tmp_path):
    """The standing invariant, over a fully constructed and populated window.

    Covers every widget reachable from here: the shell (sidebar, nav,
    footer, banner, hint), all seven pages, and the rows Presets and
    Statistics only build once actually driven. Does not cover a widget no
    code path here builds -- the setup wizard is the concrete example
    (`gui/setup_wizard.py` has zero `setStyleSheet` calls and carries no
    theme-derived stylesheet at all, so it is unaffected by this phase), nor
    a preset/transition shape this file's fixed sample data never exercises.

    ``ControlStyle`` (the checkbox/combo/spin overlay) reads ``theme()`` at
    paint time rather than baking it into a stylesheet string, so it needs
    no restyle registration at all -- there is no application-level
    stylesheet left to grep for a stale hex. The only way left to prove a
    live switch reaches it is by rendering: install it here, grab a control
    under each palette, and compare the border pixel actually painted.
    """
    flip_palette(qapp, dark=False)
    window = _build_populated_window(monkeypatch, tmp_path)
    window.show()
    qapp.processEvents()
    restyle.follow_palette(qapp)
    qapp.setStyle(ControlStyle())
    try:
        assert_hexes_are_current_tokens(window)

        combo = window.settings.language_combo
        card_bg_hex = theme().card_bg.name()
        light_pixel = _find_border_pixel(
            combo.grab().toImage(), combo.height() // 2, card_bg_hex)
        assert light_pixel.name() == theme().border.name(), (
            "the Language combo's frame does not carry the current "
            "theme().border before any switch")

        flip_palette(qapp, dark=True)
        assert_hexes_are_current_tokens(window)
        dark_pixel = _find_border_pixel(
            combo.grab().toImage(), combo.height() // 2,
            theme().card_bg.name())
        assert dark_pixel.name() == theme().border.name(), (
            "ControlStyle's overlay did not follow the live switch -- the "
            "combo frame still reads the pre-switch theme().border")
        assert dark_pixel.name() != light_pixel.name(), (
            "the combo frame's border pixel is identical before and after "
            "the switch to dark")

        # The reverse leg is not ceremony -- a rule correct in one scheme
        # and wrong in the other is the hardest kind of visual bug to
        # notice (UI-SPEC's Scheme Parity rule).
        flip_palette(qapp, dark=False)
        assert_hexes_are_current_tokens(window)
        reverted_pixel = _find_border_pixel(
            combo.grab().toImage(), combo.height() // 2,
            theme().card_bg.name())
        assert reverted_pixel.name() == theme().border.name(), (
            "ControlStyle's overlay did not follow the reverse switch")
    finally:
        qapp.setStyle(QStyleFactory.create("fusion"))
        window.close()
