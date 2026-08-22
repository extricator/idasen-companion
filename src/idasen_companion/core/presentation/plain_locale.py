"""A :class:`LocaleFormatter` that renders every value the same way on every
machine.

Numbers print with a full stop, never a comma; :class:`.specs.TimeStyle`
renders 24-hour. Neither the numeric nor the time locale category is read
anywhere in this module — there is no ``import locale`` here, and there is
no locale to inject, which is why :class:`PlainLocaleFormatter` takes no
constructor argument.

**This is this project's deliberate product policy, not a claim about
CLDR.** glibc defines the 12-hour clock format as the empty string for
Spanish, so deriving a 12-hour flag from the process locale would hand a
Spanish user a *worse* answer than a plain 24-hour clock — not a locally
correct one this backend happened to skip. The full evidence for this
decision (git, systemd, Deluge, borgbackup, llama.cpp) lives in
``.planning/notes/vocabulary-and-presentation-decisions.md`` § 2; this
module implements that decision rather than re-arguing it.

Both :class:`.specs.DateStyle` members render an ISO 8601 calendar date
(``2026-08-17``) here, and deliberately converge on that one shape — a
short day marker and a full calendar heading are two different Qt
requests, but a Qt-free process answers them identically. ISO is named by
a standard rather than invented in this module, carries no language, and
is the readable choice in the journal lines and command-line output where
Qt-free rendering actually surfaces. Fixed English weekday and month names
were the rejected alternative: they hand a Spanish reader text that looks
half-translated, with no way for a translator to fix it. Deleting the
weekday and month abbreviation tables that used to sit here is the point
of this choice, not a side effect of it — a private month-name table is
exactly the ``month_names()`` accessor BACK-02 forbids, with the getter
removed; keeping the tables private would only have hidden the same
locale database this module exists not to have. None of this makes the
divergence between the two backends disappear — the window still renders
``lun 17 ago 2026`` where this module renders ``2026-08-17``, and
``docs/ARCHITECTURE.md`` names that divergence as the invariant's
boundary. What changes here is that the Qt-free side no longer disagrees
with the window *in English words*.

This backend satisfies :class:`.protocols.LocaleFormatter` and nothing
else (BACK-01) — it renders values, and looks nothing up in a message
catalog.
"""

from __future__ import annotations

from datetime import datetime

from .specs import DateStyle, IntegerSpec, NumberSpec, TimeStyle


class PlainLocaleFormatter:
    """Renders atomic values with this project's fixed conventions.

    Constructed with no arguments — there is no locale state to hold, which
    is the point: every method's output depends only on its own arguments.
    """

    def number(self, value: float, spec: NumberSpec) -> str:
        value = float(value)
        decimals = spec.decimals
        if spec.trim_trailing_zeroes and value == int(value):
            decimals = 0
        template = "{:,.{decimals}f}" if spec.grouping else "{:.{decimals}f}"
        return template.format(value, decimals=decimals)

    def integer(self, value: int, spec: IntegerSpec) -> str:
        rendered = "{:,d}".format(value) if spec.grouping else str(int(value))
        return rendered.rjust(spec.min_digits, "0")

    def time(self, value: datetime, style: TimeStyle) -> str:
        if style is TimeStyle.HOUR_AND_MINUTE:
            return f"{value.hour:02d}:{value.minute:02d}"
        raise ValueError(f"unsupported time style: {style!r}")

    def date(self, value: datetime, style: DateStyle) -> str:
        if style not in (DateStyle.WEEKDAY_AND_DAY, DateStyle.WEEKDAY_DAY_MONTH_YEAR):
            raise ValueError(f"unsupported date style: {style!r}")
        return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
