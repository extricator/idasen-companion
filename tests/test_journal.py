"""Structured journal encoding and the journalctl reader (see docs/LOGGING.md)."""

import json
import struct
from unittest.mock import MagicMock, patch

from idasen_companion.core import journal

# conftest stubs journal.send for every test so nothing writes to the real
# journal. Grab the genuine article at import time — this module is the one
# place that tests send() itself.
_REAL_SEND = journal.send


def test_plain_field_uses_the_text_form():
    assert journal._encode_field("MESSAGE", "hello") == b"MESSAGE=hello\n"


def test_multiline_field_uses_the_binary_form():
    # A value containing a newline has no unambiguous text encoding, so the
    # protocol switches to an explicit length prefix.
    out = journal._encode_field("MESSAGE", "a\nb")
    assert out == b"MESSAGE\n" + struct.pack("<Q", 3) + b"a\nb\n"


def test_oversized_field_is_truncated_not_dropped():
    out = journal._encode_field("MESSAGE", "x" * 99999)
    assert len(out) < 99999
    assert out.startswith(b"MESSAGE=")


def test_truncation_does_not_split_a_character():
    """Cutting bytes mid-character leaves journald holding invalid UTF-8, which
    journalctl then hands back as a byte array — a form read_recent only
    unpacks for MESSAGE, so IC_PARAMS silently lost its parameters."""
    # 'é' is two bytes, so a limit that isn't a multiple of two lands inside one.
    value = "é" * journal._MAX_FIELD
    out = journal._encode_field("IC_PARAMS", value)
    body = out[len(b"IC_PARAMS="):-1]
    assert len(body) <= journal._MAX_FIELD
    body.decode("utf-8")  # raises if a character was split


def test_send_reports_failure_instead_of_raising_when_unavailable():
    with patch.object(journal, "available", return_value=False):
        assert _REAL_SEND("hi") is False


def test_unserializable_params_cost_the_line_its_params_not_an_exception():
    assert journal.encode_params({"height": object()}) == "{}"
    assert journal.wire_params({"height": object()}) == {}
    assert journal.wire_params({"height": 1.1}) == {"height": 1.1}
    assert journal.wire_params(None) == {}


def test_send_still_delivers_a_line_whose_params_will_not_serialize():
    sock = MagicMock()
    with patch.object(journal, "available", return_value=True), \
            patch.object(journal, "_journal_socket", return_value=sock):
        assert _REAL_SEND("hi", params={"x": object()}) is True
    payload = sock.sendto.call_args.args[0]
    assert b"MESSAGE=hi\n" in payload
    assert journal.FIELD_PARAMS.encode() not in payload


def test_send_drops_the_line_rather_than_blocking_on_a_full_journald():
    """The daemon logs from inside its event loop, so a blocking sendto against
    a full receive buffer would stall desk automation until journald drained."""
    sock = MagicMock()
    sock.sendto.side_effect = BlockingIOError()
    with patch.object(journal, "available", return_value=True), \
            patch.object(journal, "_journal_socket", return_value=sock):
        assert _REAL_SEND("hi") is False


def test_send_discards_a_broken_socket_so_the_next_line_gets_a_fresh_one():
    sock = MagicMock()
    sock.sendto.side_effect = OSError("bad file descriptor")
    with patch.object(journal, "available", return_value=True), \
            patch.object(journal, "_journal_socket", return_value=sock), \
            patch.object(journal, "_drop_socket") as drop:
        assert _REAL_SEND("hi") is False
    drop.assert_called_once()


def test_the_socket_is_reused_and_never_blocks():
    journal._drop_socket()
    with patch.object(journal.socket, "socket", return_value=MagicMock()) as new:
        first = journal._journal_socket()
        assert journal._journal_socket() is first
    first.setblocking.assert_called_once_with(False)
    assert new.call_count == 1
    journal._drop_socket()


def _journalctl(entries):
    """Fake a journalctl -o json run returning `entries`."""
    class Proc:
        returncode = 0
        stdout = "\n".join(json.dumps(e) for e in entries)
    return patch.object(journal.subprocess, "run", return_value=Proc())


def test_read_recent_maps_priority_to_level_and_parses_params():
    with _journalctl([{
        "MESSAGE": "Preset 'desk' saved at 1.1000m.",
        "PRIORITY": "6",
        "__REALTIME_TIMESTAMP": "1700000000000000",
        journal.FIELD_CHANNEL: "activity",
        journal.FIELD_MSG_ID: "preset.saved",
        journal.FIELD_PARAMS: json.dumps({"name": "desk", "height": 1.1}),
    }]):
        entries = journal.read_recent()
    assert entries == [{
        "ts": 1700000000.0, "level": "info", "channel": "activity",
        "msg_id": "preset.saved", "params": {"name": "desk", "height": 1.1},
        "text": "Preset 'desk' saved at 1.1000m.",
    }]


def test_read_recent_reads_level_and_id_off_an_unlabelled_entry():
    # Lines written before this shipped (or captured from stdout) have no
    # channel field. Level still comes from PRIORITY; there is no id to read.
    with _journalctl([{"MESSAGE": "old line", "PRIORITY": "4",
                       "__REALTIME_TIMESTAMP": "1000000"}]):
        entries = journal.read_recent()
    assert entries[0]["level"] == "warning"
    assert entries[0]["msg_id"] == ""


def test_read_recent_decodes_binary_messages():
    with _journalctl([{"MESSAGE": list(b"multi\nline"), "PRIORITY": "6",
                       "__REALTIME_TIMESTAMP": "1000000"}]):
        entries = journal.read_recent()
    assert entries[0]["text"] == "multi\nline"


def test_read_recent_returns_entries_oldest_first():
    with _journalctl([
        {"MESSAGE": "b", "__REALTIME_TIMESTAMP": "2000000"},
        {"MESSAGE": "a", "__REALTIME_TIMESTAMP": "1000000"},
    ]):
        entries = journal.read_recent()
    assert [e["text"] for e in entries] == ["a", "b"]


def test_read_recent_survives_a_missing_journalctl():
    # No journal is a cosmetic loss (the live feed still works), never a crash.
    with patch.object(journal.subprocess, "run", side_effect=OSError):
        assert journal.read_recent() == []


def test_read_recent_skips_unparsable_lines():
    class Proc:
        returncode = 0
        stdout = 'not json\n{"MESSAGE": "ok", "__REALTIME_TIMESTAMP": "1"}\n'
    with patch.object(journal.subprocess, "run", return_value=Proc()):
        entries = journal.read_recent()
    assert [e["text"] for e in entries] == ["ok"]


def test_inherited_journal_stream_does_not_count_as_owning_it():
    """$JOURNAL_STREAM is inherited, so its presence proves nothing — a shell
    in a systemd-managed terminal carries it while writing to a pipe. Without
    the fd comparison a hand-run daemon prints nothing at all."""
    with patch.dict("os.environ", {"JOURNAL_STREAM": "1:2"}):
        assert journal.stdout_is_journal() is False


def test_matching_device_and_inode_counts_as_owning_it():
    import os
    stat = os.fstat(1)
    with patch.dict("os.environ",
                    {"JOURNAL_STREAM": f"{stat.st_dev}:{stat.st_ino}"}):
        assert journal.stdout_is_journal() is True


def test_absent_journal_stream_is_not_systemd():
    with patch.dict("os.environ", {}, clear=True):
        assert journal.stdout_is_journal() is False


def test_malformed_journal_stream_is_tolerated():
    with patch.dict("os.environ", {"JOURNAL_STREAM": "garbage"}):
        assert journal.stdout_is_journal() is False


def test_unlabelled_entries_are_diagnostics_not_activity():
    """The GUI binary is also called `idasen-companion`, so its stderr lands
    under the same identifier. Defaulting unlabelled entries to activity put
    Python tracebacks in the user's "why did my desk move?" feed."""
    with _journalctl([{"MESSAGE": "Traceback (most recent call last):",
                       "PRIORITY": "6", "__REALTIME_TIMESTAMP": "1000000"}]):
        entries = journal.read_recent()
    assert entries[0]["channel"] == "diagnostic"


def test_labelled_entries_keep_their_channel():
    with _journalctl([{"MESSAGE": "Automation paused.", "PRIORITY": "6",
                       "__REALTIME_TIMESTAMP": "1000000",
                       journal.FIELD_CHANNEL: "activity",
                       journal.FIELD_MSG_ID: "automation.paused"}]):
        entries = journal.read_recent()
    assert entries[0]["channel"] == "activity"
