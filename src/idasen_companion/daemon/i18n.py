"""A verbose, localized delay for desktop notifications.

Builds a throwaway Qt-free presentation context on every call and renders
through :meth:`~idasen_companion.core.presentation.formatter.Formatter.duration_verbose`
— the shared duration policy's floor decomposition and hours split, with its
own verbose message set kept because this text lands inside a notification
*sentence* ("Desk will move in 1 hour 5 minutes") rather than the terse
"1h 05m" shape the journal and the Activity Log render through
:func:`idasen_companion.core.durations.format_duration_human`. See
``core/presentation/formatter.py`` for the merged policy and
``core/presentation/register.py`` for the marked constants it renders
through.
"""

from __future__ import annotations

from ..core.presentation.formatter import Formatter, PresentationContext
from ..core.presentation.gettext_translator import GettextTranslator
from ..core.presentation.plain_locale import PlainLocaleFormatter
from ..core.units import HeightUnit


def human_delay(seconds: int) -> str:
    """A short, localized, correctly-pluralized delay for notifications.

    Unlike ``core.durations.format_duration_human`` (English, shared with the
    English-only journald/Activity-Log path), this renders through the
    ``gettext`` catalog so "2 minutes" / "30 seconds" translate.
    """
    # A duration reads no unit; CENTIMETRES is stated explicitly rather than
    # left as a default so PresentationContext keeps one shape across every
    # caller. Phase 14's PRES-04 replaces this throwaway, per-call context
    # with one the daemon builds once and owns.
    context = PresentationContext(
        locale=PlainLocaleFormatter(), translator=GettextTranslator(),
        unit=HeightUnit.CENTIMETRES)
    return Formatter(context).duration_verbose(seconds)
