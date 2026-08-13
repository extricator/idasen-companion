"""In-memory ring buffer of recent daemon events, exposed over D-Bus for the
GUI's Activity Log. The journal remains the full, persistent record.

Two ways in, one per channel (see ``docs/LOGGING.md``):

- :meth:`RingLog.emit` takes a catalogued :class:`~idasen_companion.core.logmsg.Message`
  and raw parameters. These are *activity* lines — the ones answering "why did
  my desk do that?" — so they travel as an id plus parameters and the GUI
  renders its own translated sentence.
- :meth:`RingLog.diag` takes a level and free English text. These are
  *diagnostic* lines, read only when something is wrong, and never translated.

Which one you reach for is the audience decision, and it is deliberately the
only decision the call site makes about visibility. Level means severity and
nothing else.
"""

from __future__ import annotations

import collections
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from ..core import journal
from ..core.logmsg import ENGLISH_FORMATTERS, Channel, Message, render

logger = logging.getLogger("idasen_companion")

_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO,
           "warning": logging.WARNING, "error": logging.ERROR}

#: Kept as a module-level name because the tests render lines the way the
#: journal sees them. The GUI has its own set — same raw values, rendered
#: translated and in centimetres.
FORMATTERS = ENGLISH_FORMATTERS


@dataclass(frozen=True)
class Entry:
    """One log line, in the form the GUI receives it.

    ``text`` is always populated — the English the daemon composed. A GUI that
    recognizes ``msg_id`` re-renders from ``params`` in the user's language;
    one that doesn't (an older client meeting a newer daemon) shows ``text``.

    ``params`` is JSON-serializable by construction (``RingLog.emit`` puts it
    through ``journal.wire_params``), so the three places that serialize an
    entry can do so without a guard.
    """

    ts: float
    level: str
    channel: str
    msg_id: str = ""
    params: dict = field(default_factory=dict)
    text: str = ""

    def as_dict(self) -> dict:
        return {"ts": self.ts, "level": self.level, "channel": self.channel,
                "msg_id": self.msg_id, "params": self.params,
                "text": self.text}


class RingLog:
    def __init__(self, maxlen: int = 500, clock: Callable[[], float] = time.time):
        self._entries: collections.deque = collections.deque(maxlen=maxlen)
        self._clock = clock
        self.on_entry: Callable[[Entry], None] | None = None

    def emit(self, message: Message, **params) -> None:
        """Log a catalogued activity line."""
        # Render from the raw parameters, store what the wire can carry: an
        # unserializable value (an Enum, a Path, an exception) costs the line
        # its parameters and no more. Doing it here rather than at each of the
        # three serialization points is what makes those points guard-free.
        text = render(message, params, FORMATTERS)
        self._record(Entry(
            ts=self._clock(), level=message.level,
            channel=Channel.ACTIVITY.value, msg_id=message.id,
            params=journal.wire_params(params), text=text))

    def diag(self, level: str, text: str) -> None:
        """Log a free-form diagnostic line.

        No catalog entry and no translation on purpose: these exist to be
        pasted into a bug report, where stable English is the feature.
        """
        self._record(Entry(ts=self._clock(), level=level,
                           channel=Channel.DIAGNOSTIC.value, text=text))

    def _record(self, entry: Entry) -> None:
        self._entries.append(entry)
        # Structured first, so the Activity Log can be rebuilt from the journal
        # with its ids and parameters intact. Fall back to stdout when the
        # journal isn't reachable, and log to stdout as well when nothing is
        # capturing it into the journal already (a terminal dev run).
        sent = journal.send(entry.text, entry.level, channel=entry.channel,
                            msg_id=entry.msg_id, params=entry.params)
        if not sent or not journal.stdout_is_journal():
            logger.log(_LEVELS.get(entry.level, logging.INFO), entry.text)
        if self.on_entry:
            self.on_entry(entry)

    def entries(self) -> list[Entry]:
        return list(self._entries)
