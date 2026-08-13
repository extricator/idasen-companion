"""Structured reads and writes against the systemd journal.

The journal is this app's log of record (``docs/LOGGING.md``): everything goes
there, both channels, always English. Two things need more than plain stdout
to make that work.

**Writing.** The daemon logs to stdout, and systemd turns stdout into journal
entries carrying nothing but ``MESSAGE``. That is enough to read a log by eye
and not enough to rebuild the Activity Log from one — the channel, the message
id and its parameters would all be gone, so history would arrive as
untranslatable English while live lines arrived translated. Sending natively
to ``/run/systemd/journal/socket`` keeps the structure. The protocol is a
plain datagram of ``FIELD=value`` lines, so this needs no dependency; it
degrades to stdout wherever the socket isn't there (a non-systemd system, a
container, a test).

**Reading.** The GUI seeds its Activity Log from ``journalctl -o json`` rather
than from a second on-disk store, because journald already persists, indexes
and rotates exactly this.

Both sides filter on ``SYSLOG_IDENTIFIER``, not on the unit: entries the GUI
writes itself (autostart toggled while the daemon is down) are not in the
daemon's cgroup and would be invisible to a ``-u idasen-companion`` query.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
from pathlib import Path
from typing import Any

SYSLOG_IDENTIFIER = "idasen-companion"
_SOCKET_PATH = "/run/systemd/journal/socket"

# Custom journal fields. Uppercase, underscore-separated and not
# leading-underscore, which journald reserves for the fields it trusts.
FIELD_CHANNEL = "IC_CHANNEL"
FIELD_MSG_ID = "IC_MSG_ID"
FIELD_PARAMS = "IC_PARAMS"

_PRIORITY = {"error": 3, "warning": 4, "info": 6, "debug": 7}
_PRIORITY_TO_LEVEL = {0: "error", 1: "error", 2: "error", 3: "error",
                      4: "warning", 5: "info", 6: "info", 7: "debug"}

# journald's datagram limit is generous but finite, and an oversized send
# raises EMSGSIZE rather than truncating. Cap the parts that can grow without
# bound (a BlueZ error string, a stack-ish message) so a long line degrades to
# a short one instead of vanishing.
_MAX_FIELD = 8192


def _encode_field(name: str, value: str) -> bytes:
    """One journal field in the native protocol.

    Values without newlines go as ``NAME=value``; anything else needs the
    binary form (``NAME``, then a 64-bit little-endian length, then the raw
    value), because the parser has no other way to know where a multi-line
    value ends.
    """
    raw = value.encode("utf-8", "replace")
    if len(raw) > _MAX_FIELD:
        # Truncating bytes can land mid-character, and journald stores the
        # result verbatim: `journalctl -o json` then hands the field back as a
        # byte array instead of a string, which `read_recent` only unpacks for
        # MESSAGE. IC_PARAMS took that path silently, losing an entry's
        # parameters and with them its translation. Cut back to a whole
        # character.
        raw = raw[:_MAX_FIELD].decode("utf-8", "ignore").encode("utf-8")
    if b"\n" in raw:
        return (name.encode("ascii") + b"\n"
                + struct.pack("<Q", len(raw)) + raw + b"\n")
    return name.encode("ascii") + b"=" + raw + b"\n"


def available() -> bool:
    """Whether the journal socket is there to send to."""
    return Path(_SOCKET_PATH).exists()


def encode_params(params: dict | None) -> str:
    """Message parameters as JSON for the wire, never raising.

    Both transports carry parameters as a JSON string — the journal field and
    the D-Bus signal (PySide6's QtDBus can't demarshal a map). Neither is worth
    an exception: a parameter that won't serialize (an Enum, a Path, an
    exception object) should cost that line its parameters, not abort the
    config reload or the move that was being logged.
    """
    if not params:
        return "{}"
    try:
        return json.dumps(params)
    except (TypeError, ValueError):
        return "{}"


def wire_params(params: dict | None) -> dict:
    """``params`` reduced to what will survive the wire.

    Applied once when a line is recorded, so every consumer downstream —
    journal field, D-Bus signal, ``GetRecent`` — is dumping something that is
    already known to serialize, and sees the same values the GUI will.
    """
    return json.loads(encode_params(params))


# One socket for the process, reused. Reconnecting per line is wasteful, but
# the reason it is cached is that it can then be non-blocking: the daemon logs
# from inside its asyncio loop, and a blocking `sendto` against a full journald
# receive buffer stalls desk automation until journald drains. Losing the line
# is the lesser failure, as everywhere else in this module.
# A mutable module-level singleton reassigned via `global`, not a constant —
# UPPER_CASE would claim an immutability that is false.
_socket: socket.socket | None = None  # pylint: disable=invalid-name


def _journal_socket() -> socket.socket:
    global _socket
    if _socket is None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.setblocking(False)
        _socket = sock
    return _socket


def _drop_socket() -> None:
    global _socket
    if _socket is not None:
        try:
            _socket.close()
        except OSError:
            pass
        _socket = None


def stdout_is_journal() -> bool:
    """Whether this process's *own* stdout is a journal stream.

    Used to decide whether stdout logging would duplicate what the native send
    already delivered. systemd sets ``$JOURNAL_STREAM`` to the ``device:inode``
    of the stream it handed the unit — and the variable is *inherited*, so its
    mere presence proves nothing: a shell run from any systemd-managed terminal
    carries it while writing to a pipe. Comparing the numbers against the real
    fd is the documented check, and without it a developer running the daemon
    by hand gets no terminal output at all.
    """
    value = os.environ.get("JOURNAL_STREAM")
    if not value:
        return False
    try:
        device, inode = (int(part) for part in value.split(":", 1))
        stat = os.fstat(1)
    except (ValueError, OSError):
        return False
    return stat.st_dev == device and stat.st_ino == inode


def send(message: str, level: str = "info", *, channel: str = "activity",
         msg_id: str = "", params: dict | None = None) -> bool:
    """Write one structured entry. Returns False if it couldn't be delivered.

    Never raises: a logger that can take its caller down is worse than a lost
    line, and every caller here is on a path where losing the line is the
    lesser failure.
    """
    if not available():
        return False
    fields = [
        _encode_field("MESSAGE", message),
        _encode_field("PRIORITY", str(_PRIORITY.get(level, 6))),
        _encode_field("SYSLOG_IDENTIFIER", SYSLOG_IDENTIFIER),
        _encode_field(FIELD_CHANNEL, channel),
    ]
    if msg_id:
        fields.append(_encode_field(FIELD_MSG_ID, msg_id))
    if params:
        encoded = encode_params(params)
        if encoded != "{}":  # unserializable: still send the line, minus them
            fields.append(_encode_field(FIELD_PARAMS, encoded))
    try:
        _journal_socket().sendto(b"".join(fields), _SOCKET_PATH)
        return True
    except BlockingIOError:
        return False   # journald is backed up; drop the line rather than wait
    except OSError:
        _drop_socket()  # the socket may be the broken part; start over next time
        return False


def _entry_from_record(raw: dict) -> dict[str, Any] | None:
    """One ``journalctl -o json`` record as a log entry, or None if it carries
    no message this app can show."""
    message = raw.get("MESSAGE")
    if isinstance(message, list):  # binary field: journalctl gives bytes
        try:
            message = bytes(message).decode("utf-8", "replace")
        except (TypeError, ValueError):
            return None
    if not isinstance(message, str):
        return None
    try:
        entry_timestamp = int(raw.get("__REALTIME_TIMESTAMP", 0)) / 1_000_000
    except (TypeError, ValueError):
        entry_timestamp = 0.0
    try:
        priority = int(raw.get("PRIORITY", 6))
    except (TypeError, ValueError):
        priority = 6
    params = {}
    if raw.get(FIELD_PARAMS):
        try:
            params = json.loads(raw[FIELD_PARAMS])
        except (TypeError, ValueError):
            params = {}
    return {
        "ts": entry_timestamp,
        "level": _PRIORITY_TO_LEVEL.get(priority, "info"),
        # **The activity channel is opt-in.** Only entries this app wrote
        # through `send` carry a channel; everything else under the same
        # identifier is raw stdout/stderr — the daemon's pre-upgrade log
        # lines, and, because the GUI binary is also called
        # `idasen-companion`, every Python traceback and Qt warning it
        # ever prints. Defaulting those to activity put a stack trace in
        # the user's "why did my desk move?" feed. They are still worth
        # keeping: an unhandled GUI exception is exactly what a bug report
        # wants. It is just diagnostics.
        "channel": raw.get(FIELD_CHANNEL) or "diagnostic",
        "msg_id": raw.get(FIELD_MSG_ID) or "",
        "params": params if isinstance(params, dict) else {},
        "text": message,
    }


def read_recent(since: str = "-7 days", limit: int = 2000) -> list[dict]:
    """Recent entries this app wrote, oldest first.

    Returns dicts of ``{ts, level, channel, msg_id, params, text}`` — the same
    shape the live D-Bus signal carries, so the GUI can append both through
    one path.

    Filters on ``SYSLOG_IDENTIFIER`` so that lines the GUI wrote while the
    daemon was down are included. Returns an empty list on any failure
    (no journalctl, no journal, a permissions problem): a missing backlog is a
    cosmetic loss, and the live feed still works.
    """
    try:
        proc = subprocess.run(
            ["journalctl", "--user", "-t", SYSLOG_IDENTIFIER, "-o", "json",
             "--since", since, "-n", str(limit)],
            capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []

    # Heterogeneous records — float timestamp, str level, dict params — so the
    # inferred value type was a union, and sorting on "ts" read as sorting on
    # something possibly a dict. It is always the float computed above; saying
    # `Any` is closer to the truth than a union that lists types no single key
    # can hold.
    entries: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except ValueError:
            continue
        entry = _entry_from_record(raw)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda e: e["ts"])
    return entries
