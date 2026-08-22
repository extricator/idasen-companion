"""The one implementation of every ordinary word the app renders.

A "word" here is a short piece of user-facing vocabulary selected by a wire
value — a connection state, a status, a desk position, a preset, a trigger,
a day name — as opposed to a *value* (a height, a duration) that
:mod:`.formatter` renders through a locale backend. A word needs a
translator and nothing else: no locale, no unit.

**Three layers, one implementation.** Each function here is written once,
takes a :class:`~.protocols.Translator` as its first argument, and is
reached two ways:

* as a :class:`~.formatter.Formatter` method, which is how the daemon and
  the future CLI say the word — neither may import ``gui/``, and neither
  may be handed a second way to spell the same thing;
* through a signature-unchanged forwarder in ``gui/util.py``, which
  constructs a :class:`~.gettext_translator.GettextTranslator` and passes
  its arguments straight through, so the GUI's existing call sites keep
  their imports and their calls.

A forwarder is a forwarder: it changes no default. Every unrecognized-key
fallback below is the behaviour the GUI shipped before the move, and each
one is tested here rather than at the forwarder.

**Qt-free and global-free.** Nothing in this module imports Qt and nothing
reads a module global: the translator arrives as an argument, which is what
PRES-02 asks of every function under ``core/presentation/``. The single
named exemption to that rule lives one module over, in
:mod:`.gettext_translator`, because gettext has exactly one current catalog
per process; it is not re-granted here.
"""

from __future__ import annotations

from .protocols import Translator
from .register import (
    CONNECTION_CHIP_CONNECTED, CONNECTION_CHIP_DISCONNECTED,
    CONNECTION_CHIP_ON_DEMAND, CONNECTION_FOOTER_CONNECTED,
    CONNECTION_FOOTER_DISCONNECTED, CONNECTION_FOOTER_ON_DEMAND,
    POSITION_LABELS, PRESET_LABELS, STATUS_HEADS, STATUS_LABELS,
    TRIGGER_LABELS,
)


def connection_state_key(connected: bool, available: bool,
                         persistent: bool) -> str:
    """The desk's connection state as a key: connected/disconnected/on-demand.

    Split out from :func:`connection_phrases` deliberately. ``gui/util.py``'s
    ``connection_state`` needs the same state twice — once to pick a theme
    colour, which cannot live under ``core/``, and once to pick the words,
    which now do — and one shared key lets it branch on each without either
    half restating the other's condition, where it would be free to drift.
    """
    if connected:
        return "connected"
    if not available or persistent:
        return "disconnected"
    return "on-demand"


def connection_phrases(translator: Translator, key: str) -> tuple[str, str]:
    """The ``(footer_text, chip_text)`` pair for a connection state key.

    Any key other than ``"connected"`` or ``"disconnected"`` falls through
    to the on-demand pair, which is exactly the shape the branch had before
    the move: two tests and a return, with the last state unguarded.
    """
    if key == "connected":
        return (translator.message(CONNECTION_FOOTER_CONNECTED),
                translator.message(CONNECTION_CHIP_CONNECTED))
    if key == "disconnected":
        return (translator.message(CONNECTION_FOOTER_DISCONNECTED),
                translator.message(CONNECTION_CHIP_DISCONNECTED))
    return (translator.message(CONNECTION_FOOTER_ON_DEMAND),
            translator.message(CONNECTION_CHIP_ON_DEMAND))


def status_label(translator: Translator, status: str) -> str:
    """The long automation-status sentence for a status wire value.

    Falls back to the raw status string for an unrecognized key: a status
    the app has not been taught yet is better shown as its wire value than
    as nothing at all, and `tests/test_status_labels.py` is what stops that
    fallback from becoming the way a new status ships.
    """
    source = STATUS_LABELS.get(status)
    return translator.message(source) if source is not None else status


def status_head(translator: Translator, status: str) -> str:
    """The short Overview status head word for a status wire value.

    Falls back to the raw status string for an unrecognized key."""
    source = STATUS_HEADS.get(status)
    return translator.message(source) if source is not None else status


def position_label(translator: Translator, position: str) -> str:
    """The display word for a desk position wire value.

    Falls back to a capitalized copy for anything unrecognized, and ``""``
    for an empty/unknown position (callers substitute their own
    placeholder).
    """
    source = POSITION_LABELS.get(position)
    if source is not None:
        return translator.message(source)
    return position.capitalize() if position else ""


def preset_label(translator: Translator, name: str) -> str:
    """The display name for a preset.

    ``sit``/``stand`` are ours and translate; anything else the user named
    themselves and is shown verbatim. Replaces ``name.capitalize()``, which
    left the rail ticks and the tray submenu in English next to buttons
    that were translated — the same preset labelled two ways on one screen.
    """
    source = PRESET_LABELS.get(name)
    return translator.message(source) if source is not None else name


def trigger_label(translator: Translator, trigger: str) -> str:
    """The word for a transition's trigger wire value.

    Falls back to the raw trigger string for an unrecognized key."""
    source = TRIGGER_LABELS.get(trigger)
    return translator.message(source) if source is not None else trigger
