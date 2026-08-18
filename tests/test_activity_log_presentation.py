"""The Activity Log page's cosmetic polish: day separators, the three-day
history window, and the copy chip's muted, spaced icon.

Skipped where PySide6 is missing, and forces the offscreen platform before
any ``QtWidgets`` import — see ``tests/test_settings_form.py`` for why both
matter.
"""

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

# Forced, not defaulted -- a desktop session exports QT_QPA_PLATFORM (xcb
# here), which the RPM build inherits and then aborts on a display it can't
# reach. See tests/test_settings_form.py for the same rule.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from datetime import datetime  # noqa: E402

from PySide6.QtCore import QObject, QSize, Qt, Signal  # noqa: E402
from PySide6.QtGui import QColor, QFontMetricsF, QIcon, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import restyle, util  # noqa: E402
from idasen_companion.gui.pages import activity_log as activity_log_mod  # noqa: E402
from idasen_companion.gui.pages.activity_log import ActivityLogPage  # noqa: E402
from idasen_companion.gui.theme import extra_icon_gap, theme  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeClient(QObject):
    """Every signal the page's __init__ subscribes to, and nothing live.
    Copied rather than imported from a sibling GUI test module -- tests/
    carries no __init__.py, and no other test module in this suite imports
    across siblings."""

    availableChanged = Signal(bool)
    logEntry = Signal(float, str, str, str, dict, str)

    available = False

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture
def page(qapp):
    restyle.reset_registry_for_tests()
    widget = ActivityLogPage(context_mod.AppContext(FakeClient(),
                                                    tray_available=True))
    widget.resize(900, 500)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.hide()
    widget.deleteLater()
    qapp.processEvents()
    restyle.reset_registry_for_tests()


def _entry(ts: float, text: str, **kw) -> dict:
    base = {"ts": ts, "level": "info", "channel": "activity", "msg_id": "",
            "params": {}, "text": text}
    base.update(kw)
    return base


# ----- history window -----


def test_history_window_is_three_days():
    assert ActivityLogPage._HISTORY == "-3 days"


# ----- day separators -----


def test_a_separator_precedes_each_day_group_including_the_oldest(page):
    """The oldest visible row gets a heading too, not just later day changes
    -- CONTEXT.md D-01's explicit rule."""
    day1_first = datetime(2026, 8, 16, 9, 0, 0)
    day1_second = datetime(2026, 8, 16, 10, 0, 0)
    day2 = datetime(2026, 8, 17, 9, 0, 0)
    page._entries = [
        _entry(day1_first.timestamp(), "first day, first line"),
        _entry(day1_second.timestamp(), "first day, second line"),
        _entry(day2.timestamp(), "second day, first line"),
    ]
    page._redraw()

    lines = page.log_view.document().toPlainText().split("\n")
    assert len(lines) == 5, f"expected 2 separators + 3 rows, got {lines}"
    assert util.fmt_day_heading(day1_first) in lines[0]
    assert lines[1].endswith("first day, first line")
    assert lines[2].endswith("first day, second line")
    assert util.fmt_day_heading(day2) in lines[3]
    assert lines[4].endswith("second day, first line")


def test_a_backlog_within_one_day_draws_exactly_one_separator(page):
    day = datetime(2026, 8, 17, 8, 0, 0)
    page._entries = [
        _entry(day.replace(hour=h).timestamp(), f"hour {h}")
        for h in (8, 9, 10)]
    page._redraw()

    lines = page.log_view.document().toPlainText().split("\n")
    assert len(lines) == 4, f"expected 1 separator + 3 rows, got {lines}"
    assert util.fmt_day_heading(day) in lines[0]


def test_a_live_entry_on_a_new_day_gets_its_own_separator(page):
    day1 = datetime(2026, 8, 16, 9, 0, 0)
    page._entries = [_entry(day1.timestamp(), "first day")]
    page._redraw()

    day2 = datetime(2026, 8, 17, 9, 0, 0)
    page._on_log_entry(day2.timestamp(), "info", "activity", "", {}, "second day")

    lines = page.log_view.document().toPlainText().split("\n")
    assert len(lines) == 4, f"expected sep, row, sep, row, got {lines}"
    assert util.fmt_day_heading(day1) in lines[0]
    assert lines[1].endswith("first day")
    assert util.fmt_day_heading(day2) in lines[2]
    assert lines[3].endswith("second day")


def test_a_live_entry_on_the_same_day_gets_no_new_separator(page):
    day = datetime(2026, 8, 17, 9, 0, 0)
    page._entries = [_entry(day.timestamp(), "first line")]
    page._redraw()

    page._on_log_entry(day.replace(hour=10).timestamp(), "info", "activity",
                       "", {}, "second line")

    lines = page.log_view.document().toPlainText().split("\n")
    assert len(lines) == 3, f"expected sep, row, row, got {lines}"
    assert lines[1].endswith("first line")
    assert lines[2].endswith("second line")


def test_a_full_backlog_still_hits_the_cap_and_starts_with_a_separator(page):
    cap = page.log_view.document().maximumBlockCount()
    day = datetime(2026, 8, 17, 0, 0, 0)
    page._entries = [
        _entry(day.timestamp() + i, f"line {i}") for i in range(cap * 2)]

    page._redraw()

    document = page.log_view.document()
    assert document.blockCount() == cap
    first_block_text = document.firstBlock().text()
    assert util.fmt_day_heading(day) in first_block_text
    assert "line" not in first_block_text, (
        "the first block should be the day separator, not a row")


# ----- copy chip: muted glyphs, spacing -----


def _filled_icon() -> QIcon:
    """A non-null icon independent of the platform's icon theme --
    `QIcon.fromTheme` resolves nothing under the offscreen platform these
    tests run on."""
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor("black"))
    return QIcon(pixmap)


def _patch_icon_helpers(monkeypatch):
    """Record every icon name activity_log asks for, and every colour it
    hands to tinted_icon, independent of whether an icon theme resolves
    anything. Returns the two recording lists."""
    requested: list[tuple[str, ...]] = []
    tints: list = []

    def fake_icon(*names: str) -> QIcon:
        requested.append(names)
        return _filled_icon()

    def fake_tinted_icon(base, color, *args, **kwargs):
        tints.append(color)
        return base

    monkeypatch.setattr(activity_log_mod, "icon", fake_icon)
    monkeypatch.setattr(activity_log_mod, "tinted_icon", fake_tinted_icon)
    return requested, tints


def test_the_chips_glyphs_are_tinted_and_follow_the_copied_state(page, monkeypatch):
    """D-03: both glyphs go through tinted_icon, and a palette sweep
    mid-confirmation keeps the tick rather than reverting to edit-copy.

    The two take different tokens deliberately -- the dense copy outline is
    tinted lighter so it lands at the same visual weight as the thin tick
    and as the label beside it. See _apply_journal_chip_icon for the
    coverage measurements behind that.
    """
    requested, tints = _patch_icon_helpers(monkeypatch)
    resting_tint = theme().muted
    copied_tint = theme().secondary
    assert resting_tint != copied_tint, (
        "this test cannot tell the two tints apart if the tokens are equal")

    # A fresh chip (never copied) resolves the resting glyph.
    restyle.sweep()
    assert requested[-1] == ("edit-copy",)
    assert tints[-1] == resting_tint

    # A successful copy asks for the confirmation glyph.
    page._copy_journal_cmd()
    assert requested[-1] == activity_log_mod._COPIED_ICON_NAMES
    assert tints[-1] == copied_tint
    assert page._journal_chip.text() == page._JOURNAL_CMD

    # A palette sweep while the confirmation is showing must not revert it.
    requested.clear()
    tints.clear()
    restyle.sweep()
    assert requested[-1] == activity_log_mod._COPIED_ICON_NAMES
    assert tints[-1] == copied_tint

    # Restoring drops back to the resting glyph, and its lighter tint.
    page._restore_journal_chip()
    assert requested[-1] == ("edit-copy",)
    assert tints[-1] == resting_tint
    assert page._journal_chip.text() == page._JOURNAL_CMD


def test_the_chips_text_carries_no_leading_space(page):
    assert page._journal_chip.text() == page._JOURNAL_CMD
    assert not page._journal_chip.text().startswith(" ")


def test_the_chip_asks_for_the_apps_own_icon_gap(page, monkeypatch):
    """D-04: the chip is a SpacedLabelButton, so it asks for
    extra_icon_gap(...) more width than a plain QPushButton carrying the same
    stylesheet, font, icon size, icon and text -- the stylesheet has to
    match too, since a QPushButton's own padding is part of its sizeHint and
    the chip carries one the throwaway comparison button otherwise wouldn't."""
    _patch_icon_helpers(monkeypatch)
    page._apply_journal_chip_icon()   # pick up the now-non-null fake icon

    plain = QPushButton(page._JOURNAL_CMD)
    plain.setFont(page._journal_chip.font())
    plain.setIconSize(page._journal_chip.iconSize())
    plain.setIcon(page._journal_chip.icon())
    plain.setStyleSheet(page._journal_chip.styleSheet())

    extra = page._journal_chip.sizeHint().width() - plain.sizeHint().width()
    assert extra == extra_icon_gap(plain.fontMetrics().height())


def test_the_confirmation_glyph_is_line_art_not_a_filled_badge():
    """The chip tints its glyph to a flat colour, so the confirmation icon
    has to be a drawing rather than a solid shape -- tinting a solid shape
    returns a featureless block.

    This shipped once: the candidate list led with the plainest tick name,
    which Breeze answers with a filled emblem, and the chip rendered a grey
    square. Measured at 16px on Breeze: that emblem inks the entire box,
    while the names kept below ink 16 subpixels and the copy glyph beside
    them inks 55. The assertion is on the request order rather than on
    rendered pixels, because CI has no icon theme to render against.
    """
    assert "checkmark" not in activity_log_mod._COPIED_ICON_NAMES
    # object-select-symbolic is the one of these Adwaita also answers, so it
    # must stay in the list for a non-Breeze desktop to get any tick at all.
    assert "object-select-symbolic" in activity_log_mod._COPIED_ICON_NAMES


def test_a_day_separator_is_centred_and_its_rows_are_not(page):
    """The heading divides the log rather than belonging to a row, so it is
    centred while the data rows stay in their left-aligned columns.

    Asserts the alignment Qt actually resolved on each block, not the markup
    that asked for it -- Qt's rich-text engine supports a subset of CSS, and
    an alignment it silently dropped would still leave the expected string
    sitting in the HTML.
    """
    midnight = datetime(2026, 8, 18, 0, 0, 5).timestamp()
    page._entries = [_entry(midnight, "first line of a new day")]
    page._redraw()

    alignments = []
    block = page.log_view.document().begin()
    while block.isValid():
        alignments.append(bool(block.blockFormat().alignment()
                               & Qt.AlignmentFlag.AlignHCenter))
        block = block.next()

    assert alignments, "redraw produced no blocks"
    assert alignments[0] is True, "the day separator should be centred"
    assert not any(alignments[1:]), "data rows should stay left-aligned"


def _separator_line(page) -> str:
    return page.log_view.document().toPlainText().split("\n")[0]


def test_the_day_separator_is_ruled_out_to_the_view_width(page, qapp):
    """The rules grow to fill whatever the heading leaves, so the separator
    spans the view rather than floating as a short run in the middle."""
    day = datetime(2026, 8, 18, 9, 0, 0)
    page._entries = [_entry(day.timestamp(), "one line")]
    page._redraw()

    wide = _separator_line(page)
    assert util.fmt_day_heading(day) in wide
    # It reaches the measured width, give or take the odd cell that centring
    # leaves when the remainder doesn't divide evenly between the two rules.
    assert len(wide) >= page._separator_width - 2


def test_a_narrower_view_gets_a_shorter_rule(page, qapp):
    """The rule is re-measured on resize rather than baked in at build."""
    day = datetime(2026, 8, 18, 9, 0, 0)
    page._entries = [_entry(day.timestamp(), "one line")]
    page._redraw()
    wide = len(_separator_line(page))

    page.resize(500, 500)
    qapp.processEvents()
    page._redraw()
    narrow = len(_separator_line(page))

    assert narrow < wide, f"rule did not shrink with the view ({narrow} vs {wide})"
    assert util.fmt_day_heading(day) in _separator_line(page)


def test_the_separator_never_outgrows_the_view_at_any_width(page, qapp):
    """The held-back cell has to keep the separator inside the view at every
    width, not just the two the other tests happen to use -- an over-long
    separator wraps, spilling a stub of rule onto a second visual line and
    shoving the heading off centre."""
    day = datetime(2026, 8, 18, 9, 0, 0)
    page._entries = [_entry(day.timestamp(), "one line")]

    for width in range(400, 1100, 50):
        page.resize(width, 500)
        qapp.processEvents()
        page._redraw()
        line = _separator_line(page)
        advance = QFontMetricsF(page.log_view.font()).horizontalAdvance("─")
        painted = len(line) * advance
        assert painted <= page.log_view.viewport().width(), (
            f"separator is {painted:.0f}px wide in a "
            f"{page.log_view.viewport().width()}px viewport at width={width}")


def test_redrawing_after_a_resize_that_changed_nothing_is_still_idempotent(page):
    """The width is measured with the scrollbar's own width always reserved,
    so the first draw of a long backlog measures the same as every later one.
    Measuring the live viewport did not: the bar appears between the first
    and second draw and silently rewrote an otherwise unchanged document."""
    day = datetime(2026, 8, 18, 0, 0, 0)
    page._entries = [
        _entry(day.timestamp() + i, f"line {i}") for i in range(200)]
    page._redraw()
    first = page._separator_width

    page._redraw()
    assert page._separator_width == first
