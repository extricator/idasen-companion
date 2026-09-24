"""Qt-free reader-side rendering for structured Activity Log entries."""

from __future__ import annotations

from . import logmsg
from .logmsg import Param
from .presentation import Formatter
from .i18n import GettextTranslator
from .i18n import MessageKey, P_


_STATE_WORDS = {
    "sitting": P_("activity-log.parameter", "sitting"),
    "standing": P_("activity-log.parameter", "standing"),
}
_NOT_AVAILABLE = P_("activity-log.parameter", "N/A")


def _translate(key: MessageKey) -> str:
    return GettextTranslator().message(key)


def _state(value: object) -> str:
    key = _STATE_WORDS.get(str(value))
    return _translate(key) if key is not None else str(value)


def build_formatters(fmt: Formatter) -> dict[Param, object]:
    """Build value renderers for the reader's locale and display unit."""
    return {
        Param.DURATION: lambda seconds: (
            _translate(_NOT_AVAILABLE) if seconds is None else fmt.duration(seconds)),
        Param.HEIGHT: lambda height: (
            _translate(_NOT_AVAILABLE) if height is None else fmt.height(height)),
        Param.STATE: _state,
        Param.TEXT: lambda value: (
            _translate(_NOT_AVAILABLE) if value is None else str(value)),
        Param.INT: lambda count: fmt.context.locale.integer(int(count)),
    }


def render(msg_id: str, params: dict, text: str, *, fmt: Formatter) -> str:
    """Render a known id in the reader's language, else use wire English."""
    message = logmsg.get(msg_id)
    if message is None:
        return text
    return logmsg.render(
        message, params, build_formatters(fmt),
        translator=GettextTranslator())
