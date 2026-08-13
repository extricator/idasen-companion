"""The Activity Log's two sources overlap, and merging them naively doubled
every line.

The journal is the persistent record; the daemon's ring buffer is the live
tail. The *same* line exists in both — but the ring stamps it when the daemon
emits it and the journal stamps it when journald receives it, under a
millisecond later and never identical. Keying the merge on an exact timestamp
therefore matched nothing, and the user saw every daemon line twice.

Also covers the other half of the same upgrade: the wire payload changing
length under a GUI that is already running.
"""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6.QtCore", reason="Activity Log page needs PySide6")

from idasen_companion.gui.dbus_client import DaemonClient  # noqa: E402
from idasen_companion.gui.pages.activity_log import ActivityLogPage  # noqa: E402


def _bare_page(ring_entries=None, available=True, on_screen=()):
    page = ActivityLogPage.__new__(ActivityLogPage)
    page._entries = list(on_screen)
    page._seeded = False
    page._loading = False
    page.client = MagicMock(available=available)
    if ring_entries is not None:
        page.client.get_recent_log.return_value = ring_entries
    page._redraw = lambda: None
    return page


def _page(journal_entries, ring_entries, on_screen=()):
    page = _bare_page(ring_entries, on_screen=on_screen)
    page._merge_backlog(journal_entries)
    return page._entries


def _entry(ts, text, **kw):
    base = {"ts": ts, "level": "info", "channel": "activity", "msg_id": "",
            "params": {}, "text": text}
    base.update(kw)
    return base


def test_the_same_line_from_both_sources_appears_once():
    """0.75 ms apart in the real world — measured, not guessed."""
    entries = _page(
        journal_entries=[_entry(1000.001592, "Daemon stopping.")],
        ring_entries=[_entry(1000.000838, "Daemon stopping.")])
    assert [e["text"] for e in entries] == ["Daemon stopping."]


def test_a_line_only_the_ring_has_is_kept():
    """Anything journald hasn't flushed yet still has to show up."""
    entries = _page(
        journal_entries=[_entry(1000.0, "Automation paused.")],
        ring_entries=[_entry(1000.0, "Automation paused."),
                      _entry(1005.0, "Automation resumed.")])
    assert [e["text"] for e in entries] == ["Automation paused.",
                                            "Automation resumed."]


def test_a_genuine_repeat_much_later_is_not_swallowed():
    entries = _page(
        journal_entries=[_entry(1000.0, "Automation paused.")],
        ring_entries=[_entry(9000.0, "Automation paused.")])
    assert len(entries) == 2


def test_entries_come_out_oldest_first():
    entries = _page(
        journal_entries=[_entry(2000.0, "b"), _entry(1000.0, "a")],
        ring_entries=[_entry(3000.0, "c")])
    assert [e["text"] for e in entries] == ["a", "b", "c"]


def test_the_journal_alone_is_enough_when_no_daemon_is_running():
    page = _bare_page(available=False)
    page._merge_backlog([_entry(1.0, "Daemon stopping.")])
    assert [e["text"] for e in page._entries] == ["Daemon stopping."]
    page.client.get_recent_log.assert_not_called()


def test_the_labelled_copy_of_a_line_wins():
    """A native journal send can fail (journald backpressure), and the line
    then reaches journald as plain stdout: unlabelled, so `read_recent` classes
    it as a diagnostic. Preferring that copy dropped a real activity line out
    of the default filter and lost its translation."""
    entries = _page(
        journal_entries=[_entry(1000.0, "Automation paused.",
                                channel="diagnostic")],
        ring_entries=[_entry(1000.0, "Automation paused.",
                             msg_id="automation.paused")])
    assert len(entries) == 1
    assert entries[0]["channel"] == "activity"
    assert entries[0]["msg_id"] == "automation.paused"


def test_a_line_that_arrived_while_the_journal_was_being_read_is_kept():
    """The read runs on a worker thread, so live D-Bus lines can land during
    it. They exist nowhere but on screen."""
    entries = _page(journal_entries=[_entry(1000.0, "Automation paused.")],
                    ring_entries=[],
                    on_screen=[_entry(1001.0, "Automation resumed.")])
    assert [e["text"] for e in entries] == ["Automation paused.",
                                            "Automation resumed."]


def test_reloading_does_not_double_what_is_already_on_screen():
    """Reopening the page re-reads the journal, and by then the ring's copy of
    a line is on screen as well as in the journal."""
    page = _bare_page(ring_entries=[])
    page._merge_backlog([_entry(1000.0, "Automation paused.")])
    page._merge_backlog([_entry(1000.0, "Automation paused.")])
    assert len(page._entries) == 1


def test_the_ring_is_normalized_so_an_older_daemon_cannot_break_rendering():
    entries = _page(journal_entries=[],
                    ring_entries=[{"ts": 1.0, "text": "hi"}])
    assert entries == [{"ts": 1.0, "level": "info", "channel": "activity",
                        "msg_id": "", "params": {}, "text": "hi"}]


# ----- wire-format skew -----
#
# An RPM upgrade restarts the daemon under an already-running GUI, so a client
# can meet a payload of a different length than it was built for. The
# tuple-unpack version raised ValueError on every single log line, forever,
# until the GUI was relaunched.


def _emitted(args):
    client = DaemonClient.__new__(DaemonClient)
    seen = []
    client.logEntry = MagicMock(emit=lambda *a: seen.append(a))
    client._on_log_entry(MagicMock(arguments=lambda: args))
    return seen


def test_a_current_payload_is_unpacked_in_full():
    assert _emitted([1.0, "info", "activity", "preset.saved",
                     '{"name": "desk"}', "Preset 'desk' saved."]) == [
        (1.0, "info", "activity", "preset.saved", {"name": "desk"},
         "Preset 'desk' saved.")]


def test_an_older_daemons_three_field_payload_still_renders():
    assert _emitted([1.0, "info", "Daemon stopping."]) == [
        (1.0, "info", "activity", "", {}, "Daemon stopping.")]


def test_a_truncated_payload_is_dropped_not_raised():
    assert _emitted([1.0, "info"]) == []


def test_unparsable_params_do_not_lose_the_line():
    entry = _emitted([1.0, "info", "activity", "x", "not json", "text"])[0]
    assert entry[4] == {} and entry[5] == "text"


def test_non_object_params_are_ignored():
    entry = _emitted([1.0, "info", "activity", "x", "[1,2]", "text"])[0]
    assert entry[4] == {}
