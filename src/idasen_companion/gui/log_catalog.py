"""Reader-side rendering for structured Activity Log entries.

The message definitions live only in :mod:`idasen_companion.core.logmsg`.
This adapter supplies the reader's gettext catalog and Babel-backed value
formatters while preserving the English wire fallback for unknown ids.
"""

from __future__ import annotations

from ..core import activity_log, logmsg
from ..core.presentation import Formatter

# Transitional read-only aliases: migration-audit tests can prove this module
# derives from the canonical definitions without carrying a second catalog.
TEXTS = {msg_id: message.text
         for msg_id, message in logmsg.all_messages().items()}
CYCLE_NOTE = logmsg.CYCLE_NOTE.text
_FALLBACK_NOTES = {
    msg_id: message.fallback_note
    for msg_id, message in logmsg.all_messages().items()
    if message.fallback_note
}


build_formatters = activity_log.build_formatters


def render(msg_id: str, params: dict, text: str, *, fmt: Formatter) -> str:
    """Render a known id in the reader's language, else use wire English."""
    return activity_log.render(msg_id, params, text, fmt=fmt)
