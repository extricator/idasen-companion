"""``FakeLocale`` and ``FakeTranslator``: the two presentation test doubles.

Each stands in for one capability protocol in
``idasen_companion.core.presentation.protocols`` — ``FakeLocale`` for
``LocaleFormatter``, ``FakeTranslator`` for ``Translator`` — and implements
exactly that protocol's members and nothing else. Neither imports Qt or a
real message catalog: every method returns a deterministic marker string
that names its own input instead of a rendered value, so a test asserting
against the marker is provably testing product policy (which value, which
spec, which key) and not a locale's or a translator's own output. A test
that read a rendered string here could pass or fail for a reason that has
nothing to do with the policy it means to check; a marker cannot.

Every call is also appended, in the order it happened, to a per-instance
``calls`` list — the value (or source key) and the spec or style it was
given, unchanged. That list is what lets a test assert *what crossed the
seam*, not only what came back: PRES-07's property (a formatter states a
value and a unit, and the backend is handed neither the original metres
nor the unit token) is only checkable at all because the exact request is
on hand to inspect.

Reused by Phases 13, 14 and 15: every formatter that moves onto the shared
``Formatter`` facade gets its policy asserted against these two fakes
before its move, in ``tests/test_presentation_policy.py`` and the tests
that follow its pattern. Adding a member to either fake without adding it
to its protocol is exactly the drift
``tests/test_presentation_policy.py``'s conformance assertion exists to
catch — this module must never implement anything beyond the two protocols
it stands in for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from idasen_companion.core.presentation.specs import (
    DateStyle, IntegerSpec, NumberSpec, TimeStyle,
)


@dataclass(frozen=True)
class LocaleCall:
    """One call made to a :class:`FakeLocale` method, in the order it happened.

    ``method`` names which capability was invoked (``"number"``,
    ``"integer"``, ``"time"`` or ``"date"``); ``value`` and ``request`` are
    exactly what the caller supplied, unchanged — the evidence a policy
    test reads to prove what crossed the seam.
    """

    method: str
    value: object
    request: object


class FakeLocale:
    """Records every value/spec pair it is asked to render, and returns a
    marker naming both instead of rendering anything.

    Takes no constructor argument — there is no locale state to hold, and
    holding none is the point: nothing here can silently answer a
    product question a real backend would need an explicit unit or
    threshold to answer instead.
    """

    def __init__(self) -> None:
        self.calls: list[LocaleCall] = []

    def number(self, value: float, spec: NumberSpec) -> str:
        self.calls.append(LocaleCall("number", value, spec))
        return f"N({value!r}, {spec!r})"

    def integer(self, value: int, spec: IntegerSpec) -> str:
        self.calls.append(LocaleCall("integer", value, spec))
        return f"I({value!r}, {spec!r})"

    def time(self, value: datetime, style: TimeStyle) -> str:
        self.calls.append(LocaleCall("time", value, style))
        return f"T({value!r}, {style!r})"

    def date(self, value: datetime, style: DateStyle) -> str:
        self.calls.append(LocaleCall("date", value, style))
        return f"D({value!r}, {style!r})"


@dataclass(frozen=True)
class TranslatorCall:
    """One call made to :meth:`FakeTranslator.message`, in the order it happened.

    ``values`` is a plain ``dict`` copy of the keyword arguments supplied,
    so a test can compare it by equality without caring about kwarg order.
    """

    source: str
    values: dict[str, object]


@dataclass(frozen=True)
class PluralCall:
    """One call made to :meth:`FakeTranslator.plural`, in the order it happened.

    Kept as its own record type rather than reusing :class:`TranslatorCall`
    — a plural call carries a singular literal, a plural literal and a
    count that ``message`` never sees, so folding it into the two-field
    shape would either drop information or overload ``source`` with a
    meaning it doesn't have elsewhere.
    """

    singular: str
    plural: str
    count: int
    values: dict[str, object]


class FakeTranslator:
    """Records every source key and substitution set it is asked to look
    up, and returns a marker naming both instead of a translation.

    Never reaches for a real catalog — a test that asserted against this
    fake's output and happened to pass would be proof of nothing, since
    the marker carries no language-specific text to get right or wrong.
    """

    def __init__(self) -> None:
        self.calls: list[TranslatorCall] = []
        self.plural_calls: list[PluralCall] = []

    def message(self, source: str, **values: object) -> str:
        self.calls.append(TranslatorCall(source, dict(values)))
        return f"MSG({source!r}, {sorted(values.items())!r})"

    def plural(self, singular: str, plural: str, count: int,
               **values: object) -> str:
        self.plural_calls.append(
            PluralCall(singular, plural, count, dict(values)))
        return (f"PLURAL({singular!r}, {plural!r}, {count!r}, "
                f"{sorted(values.items())!r})")
