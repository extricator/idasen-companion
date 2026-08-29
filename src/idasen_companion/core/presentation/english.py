"""The English-only :class:`Translator` backend for journald's own output.

journald's reader is a grep, not a person: a bug report quotes a log line
verbatim, and a search across weeks of history has to match regardless of
what ``[ui] language`` happened to be set to when each line was written.
That makes the journal's language a product decision, not a locale
question -- it must stay stable and greppable English no matter which
catalog the rest of the app is bound to.

``GettextTranslator`` cannot serve that path: in the daemon it is bound to
the process-wide catalog that ``[ui] language`` controls, so its output
would follow the user's language exactly where the journal must not.
``EnglishTranslator`` is a second, deliberately trivial backend instead --
it returns every source string unchanged and selects English's own plural
rule (``count != 1``). This is why ``core/durations.py``'s English journal
output stops being a second decomposition algorithm: the arithmetic (the
threshold, the hours-and-minutes split, the zero-padding) is shared with
every other duration rendering, and only the backend behind it differs.

No module-level instance is created here. ``tests/test_presentation_no_globals.py``'s
module-level-binding rule flags exactly that shape -- a shared instance
would be the same process-wide state PRES-02 forbids everywhere else in
this package. Callers construct one per call; it holds no state and costs
nothing to build.
"""

from __future__ import annotations

from ..units import HeightUnit
from .formatter import Formatter, PresentationContext
from .plain_locale import PlainLocaleFormatter
from .specs import TimeStyle


class EnglishTranslator:
    """Returns every source string unchanged, selecting English's plural rule.

    Deliberately reaches no catalog of any kind -- no import of the
    process-wide translation module, no ``ngettext``, nothing that follows
    ``[ui] language``. That absence is the entire point: it is what keeps
    this backend's output identical regardless of that catalog's current
    binding.
    """

    def message(self, source: str, **values: object) -> str:
        return source % values if values else source

    def plural(self, singular: str, plural: str, count: int,
               **values: object) -> str:
        text = singular if count == 1 else plural
        return text % values if values else text


def format_duration_human(seconds: float | None) -> str:
    """The journal's compact, greppable duration: "30s" / "45m" / "1h 05m".

    Matches the shape ``gui/log_catalog.py`` renders the same
    ``Param.DURATION`` value in, which closes the split PRES-03 exists to
    close -- the same log event no longer reads "45.0 minutes" for journald
    and "45m" for the Activity Log.

    ``None`` renders as "N/A", the same convention
    ``core/logmsg.py``'s ``Param.HEIGHT`` formatter already uses; nothing in
    this move changes that.

    Builds a throwaway :class:`~idasen_companion.core.presentation.formatter.Formatter`
    per call rather than binding one at module level -- the module-level
    instance :mod:`tests.test_presentation_no_globals` flags and PRES-02
    forbids. It cannot live in ``core/durations.py`` instead:
    ``core/presentation/formatter.py`` already imports that module for
    ``decompose_hms``, so the reverse import here would be circular. The
    unit is stated explicitly as centimetres, the same one-line convention
    plan 13-03's ``daemon/i18n.py`` uses for its own throwaway context --
    the journal never renders a height, so the unit is inert, but
    :class:`~idasen_companion.core.presentation.formatter.PresentationContext`
    carries no default for it to fall back on.
    """
    if seconds is None:
        return "N/A"
    context = PresentationContext(
        locale=PlainLocaleFormatter(), translator=EnglishTranslator(),
        unit=HeightUnit.CENTIMETRES,  # inert: this renderer never touches a height
        # Fixed, and unreachable from the user's display preferences: a
        # journal line is read by whoever is debugging it, so it stays
        # stable and greppable whatever the desktop session is set to --
        # the same argument the pass-through English translator beside it
        # already makes. The setting that moves every other surface's
        # clock does not reach this file at all.
        time_style=TimeStyle.HOUR_AND_MINUTE_24)
    return Formatter(context).duration(seconds)
