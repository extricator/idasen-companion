"""Reader-side rendering for structured Activity Log entries.

The message definitions live only in :mod:`idasen_companion.core.logmsg`.
This adapter supplies the reader's gettext catalog and Babel-backed value
formatters while preserving the English wire fallback for unknown ids.
"""

from __future__ import annotations

from ..core import logmsg
from ..core.logmsg import Param
from ..core.presentation.formatter import Formatter
from ..core.presentation.gettext_translator import GettextTranslator
from ..core.presentation.register import MessageKey, P_
from ..core.presentation.specs import IntegerSpec


_STATE_WORDS = {
    "sitting": P_("activity-log.parameter", "sitting"),
    "standing": P_("activity-log.parameter", "standing"),
}
_NOT_AVAILABLE = P_("activity-log.parameter", "N/A")

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


def _tr(key: MessageKey) -> str:
    return GettextTranslator().message(key)


def _state(value: object) -> str:
    key = _STATE_WORDS.get(str(value))
    return _tr(key) if key is not None else str(value)


def build_formatters(fmt: Formatter) -> dict[Param, object]:
    """Build value renderers for the reader's locale and display unit."""
    return {
        Param.DURATION: lambda seconds: (
            _tr(_NOT_AVAILABLE) if seconds is None else fmt.duration(seconds)),
        Param.HEIGHT: lambda height: (
            _tr(_NOT_AVAILABLE) if height is None else fmt.height(height)),
        Param.STATE: _state,
        Param.TEXT: lambda value: (
            _tr(_NOT_AVAILABLE) if value is None else str(value)),
        Param.INT: lambda count: fmt.context.locale.integer(
            int(count), IntegerSpec()),
    }


def render(msg_id: str, params: dict, text: str, *, fmt: Formatter) -> str:
    """Render a known id in the reader's language, else use wire English."""
    message = logmsg.get(msg_id)
    if message is None:
        return text
    return logmsg.render(
        message, params, build_formatters(fmt),
        translator=GettextTranslator())
