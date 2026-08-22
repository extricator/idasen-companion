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
