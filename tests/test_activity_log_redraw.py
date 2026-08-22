"""Rebuilding the Activity Log costs one document write, not one per row.

The page used to redraw by calling ``QTextEdit.append`` once per visible
entry. Each append is its own document edit -- parse, insert a block,
re-lay-out, move the cursor, update the scrollbar -- and past the document's
``maximumBlockCount`` it also evicts the oldest block, which roughly
quadruples the marginal cost. Measured against a 7-day journal backlog of
~1760 visible rows, that froze the GUI thread for 1.1 s *every* time the page
was opened, while rendering the very same rows to strings cost 33 ms. Worse,
around 760 of those rows were formatted and inserted only to be thrown away
again by the cap moments later.

These assertions pin the properties that fix rests on, stated so that any
implementation with them passes and any implementation without them fails:
no row the document cannot keep is ever formatted, the work of a redraw does
not grow with the size of the backlog, and the view is left scrolled to the
newest line so the live feed keeps following it. None is a wall-clock
threshold -- a timing assertion in a suite that runs on shared CI is a flake,
and these are the structure the timing follows from.

The page is laid out (sized and shown) before every test, because two of
those properties are invisible on a widget that has no viewport: a scrollbar
with no range cannot be short of its maximum.

Skipped where PySide6 is missing, matching every other GUI test in this
suite.
"""

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

# Forced, not defaulted -- a desktop session exports QT_QPA_PLATFORM (xcb
# here), which the RPM build inherits and then aborts on a display it can't
# reach. See tests/test_settings_form.py for the same rule.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from datetime import datetime  # noqa: E402

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui import log_catalog, restyle  # noqa: E402
from idasen_companion.gui.pages.activity_log import ActivityLogPage  # noqa: E402


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
    # Sized and shown, or the log view has no viewport and its scrollbar no
    # range -- which is exactly the state the scroll assertions measure.
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


def _cap(page) -> int:
    return page.log_view.document().maximumBlockCount()


def _count_renders(monkeypatch) -> list:
    """Count trips through the line formatter, whoever calls it.

    ``log_catalog.render`` is the one place every implementation of a redraw
    has to pass through once per row it intends to show, which makes counting
    it a measure of the work done rather than of the mechanism chosen.
    """
    calls: list = []
    real = log_catalog.render

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(log_catalog, "render", counting)
    return calls


def _viewport_is_blank(page) -> bool:
    """Render the log view as the user would see it and ask whether anything
    is on it.

    Deliberately a pixel question rather than a scrollbar one: "the view shows
    something" is the property, and any way of breaking it -- scrolled past the
    end, empty document, invisible text -- should fail the same assertion. A
    viewport with text on it has more than one shade in it; one that is a
    single flat colour has nothing drawn on it at all.
    """
    image = page.log_view.viewport().grab().toImage().convertToFormat(
        QImage.Format.Format_Grayscale8)
    return len(set(bytes(image.constBits()))) <= 1


def _count_document_edits(page) -> list:
    edits: list = []
    page.log_view.document().contentsChange.connect(
        lambda *args: edits.append(1))
    return edits


def test_a_redraw_formats_no_row_the_document_cannot_keep(page, monkeypatch):
    """The rows before the cap are evicted the moment they are inserted, so
    formatting them is pure waste -- and it was the expensive part, because
    every insertion past the cap pays for an eviction too. The old loop
    formatted all 2000 of these; a document that keeps 1000 now spends some
    of that budget on day separators, so the expected render count is
    ``cap`` minus however many distinct calendar days ended up in the kept
    set -- recovered here from which entries the formatter actually saw,
    rather than assumed, since that depends on the runner's timezone."""
    cap = _cap(page)
    entries = [_entry(float(i), f"line {i}") for i in range(cap * 2)]
    page._entries = entries

    rendered_texts: list[str] = []
    real_render = log_catalog.render

    def counting(msg_id, params, text, *, fmt):
        rendered_texts.append(text)
        return real_render(msg_id, params, text, fmt=fmt)

    monkeypatch.setattr(log_catalog, "render", counting)
    page._redraw()

    kept_days = {datetime.fromtimestamp(e["ts"]).date()
                 for e in entries if e["text"] in rendered_texts}
    assert len(rendered_texts) == cap - len(kept_days), (
        f"formatted {len(rendered_texts)} rows across {len(kept_days)} "
        f"distinct days for a document that keeps {cap} blocks total")


def test_a_redraw_keeps_the_newest_rows_and_lands_on_the_last(page):
    """What the cap keeps is the *tail*. Trimming the wrong end would be a
    silent, plausible-looking regression: still 1000 lines, all of them old.

    The first *block* is now the day separator, not a row -- these entries
    span a few minutes so they land on one calendar day, spending exactly one
    block of the cap on it; the first row's index is derived from that rather
    than hardcoded, so this doesn't assume a specific split."""
    cap = _cap(page)
    entries = [_entry(float(i), f"line {i}") for i in range(cap + 50)]
    page._entries = entries
    page._redraw()

    document = page.log_view.document()
    assert document.blockCount() == cap
    lines = document.toPlainText().split("\n")
    assert "line" not in lines[0], (
        "the first block should be the day separator, not a row")
    kept_rows = cap - 1   # one block spent on the single-day separator
    assert lines[1].endswith(f"line {len(entries) - kept_rows}")
    assert lines[-1].endswith(f"line {len(entries) - 1}")


def test_a_redraw_costs_the_same_however_many_rows_it_draws(page):
    """The stall was the *number* of document edits, which is what this
    counts: the old loop paid one per row and this must not scale at all.
    Deliberately not "setHtml is called once" -- an insertHtml under a single
    edit block, or a swap to QPlainTextEdit, would be just as fast and should
    pass just as well."""
    cap = _cap(page)
    edits = _count_document_edits(page)

    page._entries = [_entry(float(i), f"line {i}") for i in range(cap // 4)]
    page._redraw()
    small = len(edits)
    edits.clear()

    page._entries = [_entry(float(i), f"line {i}") for i in range(cap * 2)]
    page._redraw()
    large = len(edits)

    assert small == large, (
        f"{small} document edits for {cap // 4} rows but {large} for "
        f"{cap * 2} -- the cost is scaling with the backlog again")
    assert page.log_view.document().blockCount() == cap


def test_a_redraw_filters_before_it_trims(page):
    """The cap counts what is *displayed*, so the filter has to run first.
    Trimming the raw backlog first would look right on an unfiltered view and
    quietly halve a filtered one -- here it would leave 500 lines of the 1000
    the document can hold, with the older half of the log unreachable.

    The first block is now the day separator, not the row it used to be --
    these entries span under an hour so the filtered set lands on one
    calendar day, spending one block of the cap on it; the expected first row
    is derived from that split rather than hardcoded."""
    cap = _cap(page)
    entries = [
        _entry(float(i), f"line {i}",
               channel="activity" if i % 2 == 0 else "diagnostic")
        for i in range(cap * 3)]
    page._entries = entries

    page.channel.setCurrentIndex(1)          # All: both channels
    page._redraw()
    assert page.log_view.document().blockCount() == cap

    page.channel.setCurrentIndex(0)          # Activity only, half the entries
    page._redraw()

    document = page.log_view.document()
    assert document.blockCount() == cap, (
        f"{document.blockCount()} lines of a possible {cap} -- trimming "
        f"before filtering would give {cap // 2}")
    activity_entries = [e for e in entries if e["channel"] == "activity"]
    kept_rows = cap - 1   # one block spent on the single-day separator
    first_kept = activity_entries[len(activity_entries) - kept_rows]
    lines = document.toPlainText().split("\n")
    assert "line" not in lines[0], (
        "the first block should be the day separator, not a row")
    assert lines[1].endswith(first_kept["text"])
    assert lines[-1].endswith(activity_entries[-1]["text"])


def test_a_redraw_leaves_the_live_feed_following_the_newest_line(page):
    """A redraw has to leave the view at the very bottom, not merely near it.
    QTextEdit auto-scrolls an appended line only while it judges the view
    already at the maximum, so a redraw that stops a few pixels short stops
    the live feed dead: the newest line never comes back into view, and no
    further append can recover it. `ensureCursorVisible` does stop short -- by
    the document's bottom margin -- which is why this is asserted on the
    scrollbar rather than on the cursor."""
    page._entries = [_entry(float(i), f"line {i}") for i in range(300)]
    page._redraw()

    scrollbar = page.log_view.verticalScrollBar()
    assert scrollbar.maximum() > 0, "no scroll range: the page was not laid out"
    assert scrollbar.value() == scrollbar.maximum(), (
        f"{scrollbar.maximum() - scrollbar.value()} px short of the bottom")

    page._on_log_entry(400.0, "info", "activity", "", {}, "a live line")

    assert scrollbar.value() == scrollbar.maximum(), (
        "the live feed stopped following the newest line")


def test_a_redraw_leaves_something_on_screen(page):
    """The white flash: a redraw that scrolls past the last line paints the
    whole viewport as background, and the user sees the pane blink empty and
    come back identical.

    A document this size is laid out lazily, so for a moment after it is
    written its scroll range is an estimate -- and the estimate is too large.
    Parking the view at that reported maximum puts it beyond the last block.
    The size matters: at 300 rows the layout finishes in one go and the range
    is honest, which is why the scroll test below never caught this. This uses
    a full document, the amount a real backlog leaves.
    """
    cap = _cap(page)
    page._entries = [_entry(float(i), f"line {i}") for i in range(cap)]

    page._redraw()

    assert not _viewport_is_blank(page), (
        "the log view is showing nothing at all straight after a redraw: "
        f"scrolled to {page.log_view.verticalScrollBar().value()} of a "
        f"reported maximum {page.log_view.verticalScrollBar().maximum()}, "
        f"in a document {page.log_view.document().blockCount()} lines long")


def test_a_live_line_arriving_before_the_scroll_range_settles_keeps_following(
        page, qapp):
    """The other half of the same problem, and the reason the fix does not stop
    at computing the bottom itself.

    Until Qt corrects the scroll range, the bar reports a maximum the view is
    no longer at -- and `value == maximum()` is exactly the test QTextEdit uses
    to decide whether an appended line should be followed. A line that arrives
    in that window would otherwise leave the feed stuck for the rest of the
    visit. Sized between the point where layout goes lazy and the block cap: at
    the cap an append evicts a line, the document stops growing and the freeze
    hides.
    """
    page._entries = [_entry(float(i), f"line {i}") for i in range(800)]
    page._redraw()

    page._on_log_entry(9e5, "info", "activity", "", {}, "a live line")
    qapp.processEvents()

    scrollbar = page.log_view.verticalScrollBar()
    assert scrollbar.maximum() > 0, "no scroll range: the page was not laid out"
    assert scrollbar.value() == scrollbar.maximum(), (
        f"{scrollbar.maximum() - scrollbar.value()} px short of the bottom: "
        "the live feed stopped following")


def test_redrawing_the_same_rows_again_does_not_touch_the_document(page):
    """Opening the page re-reads the journal and merges it in, and that merge
    is idempotent, so most redraws have nothing to say. Rebuilding the document
    anyway costs the full write and throws away whatever the reader had
    selected. The second half of this matters as much as the first: a redraw
    that *does* have something new must still write."""
    cap = _cap(page)
    page._entries = [_entry(float(i), f"line {i}") for i in range(cap)]
    page._redraw()

    edits = _count_document_edits(page)
    page._redraw()

    assert edits == [], f"{len(edits)} document edits to draw the same rows"
    assert page.log_view.document().blockCount() == cap

    page._entries.append(_entry(9e5, "something new"))
    page._redraw()

    assert edits, "a redraw with a new line in it did not write anything"
    assert page.log_view.document().toPlainText().endswith("something new")


def test_a_reader_who_scrolled_up_is_not_dragged_back_down(page, qapp):
    """Scrolling up is how you read something that has gone past, and the feed
    is supposed to stop following while you do.

    The redraw above waits for the corrected scroll range before taking the
    bottom again. That wait has to be armed only when a correction is actually
    coming: a backlog small enough to be laid out in one go gets no correction,
    so an armed handler would sit there until the range next moved for some
    unrelated reason -- the next line arriving -- and pull the reader back down.
    """
    page._entries = [_entry(float(i), f"line {i}") for i in range(300)]
    page._redraw()
    scrollbar = page.log_view.verticalScrollBar()
    assert scrollbar.maximum() > 0, "no scroll range: the page was not laid out"

    scrollbar.setValue(0)                      # the reader scrolls to the top
    page._on_log_entry(9e5, "info", "activity", "", {}, "a live line")
    qapp.processEvents()

    assert scrollbar.value() == 0, (
        f"dragged from the top down to {scrollbar.value()} by a line arriving")


def test_an_empty_backlog_leaves_the_placeholder_showing(page):
    """setHtml("") would still be a write; the placeholder only shows on a
    genuinely empty document."""
    page._entries = []
    page._redraw()

    assert page.log_view.document().toPlainText() == ""
    assert page.log_view.toPlainText() == ""


def test_a_live_line_still_arrives_one_at_a_time(page):
    """Single-row insertion is the right shape for the live feed -- it was
    only doing it in a loop that was slow. This is the path _on_log_entry
    uses, and it must keep appending to what is already there.

    The very first redraw now also draws a day separator ahead of its one
    row (D-01: a separator precedes the oldest visible row too), which is
    why the first-line assertion moved from the row itself to the block
    after it."""
    page._entries = [_entry(1.0, "first")]
    page._redraw()
    page._on_log_entry(2.0, "info", "activity", "", {}, "second")

    lines = page.log_view.document().toPlainText().split("\n")
    assert not lines[0].endswith("first"), (
        "the first block should be the day separator, not the row")
    assert lines[1].endswith("first")
    assert lines[-1].endswith("second")
