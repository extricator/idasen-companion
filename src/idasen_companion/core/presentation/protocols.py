"""The two capability protocols a presentation backend implements.

Two protocols, not one welded renderer (BACK-01): a :class:`LocaleFormatter`
renders atomic values, and a :class:`Translator` looks up a message. They
are declared separately because value formatting and message translation
vary independently — the Qt-free backend renders numbers and times on its
own fixed policy while sourcing English text straight from a register, and
a future backend could translate through a different catalog while still
reaching for the same locale rendering. Welding both into one renderer
would force every backend to answer both questions together even where a
caller only has an opinion about one.

Neither protocol exposes a locale-database field — there is no accessor
here for the decimal separator, the set of month names, the AM/PM text or
the first day of the week, and none should be added (BACK-02). An accessor
added "just for this one case" is how a shared layer grows an incomplete
locale engine of its own,
duplicating what a real locale library already does correctly and
completely. A capability the shared layer needs belongs on the protocol as
an operation (``number``, ``time``, ...), not as a field a caller reads and
formats itself.

``Translator`` carries ``plural`` alongside ``message`` because plural-form
selection is the catalog's decision, not Python's. gettext's ``ngettext``
and Qt's ``%n`` mechanism each already know how many forms a language needs
and which one a given count selects, so a three-form language (Polish,
Russian) is a catalog change, never a code change to this protocol or its
backends. A backend that instead chose between ``singular``/``plural`` with
a bare ``count == 1`` in Python could only ever express English's own
two-form rule.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .specs import DateStyle, IntegerSpec, NumberSpec, TimeStyle


@runtime_checkable
class LocaleFormatter(Protocol):
    """Renders atomic values (numbers, integers, times, dates) for a locale."""

    def number(self, value: float, spec: NumberSpec) -> str:
        ...

    def integer(self, value: int, spec: IntegerSpec) -> str:
        ...

    def time(self, value: datetime, style: TimeStyle) -> str:
        ...

    def date(self, value: datetime, style: DateStyle) -> str:
        ...


@runtime_checkable
class Translator(Protocol):
    """Looks up a translated message by source string."""

    def message(self, source: str, **values: object) -> str:
        ...

    def plural(self, singular: str, plural: str, count: int,
               **values: object) -> str:
        ...
