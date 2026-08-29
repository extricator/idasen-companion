"""A :class:`LocaleFormatter` that renders every value the same way on every
machine.

Numbers print with a full stop, never a comma; a :class:`.specs.TimeStyle`
renders the clock it names, and its twelve-hour members render fixed
English ``AM``/``PM``. Neither the numeric nor the time locale category is
read anywhere in this module — there is no ``import locale`` here, and
there is no locale to inject, which is why :class:`PlainLocaleFormatter`
takes no constructor argument.

**This is this project's deliberate product policy, not a claim about
CLDR.** glibc defines the 12-hour clock format as the empty string for
Spanish, so deriving a twelve-or-twenty-four answer from the process
locale would hand a Spanish user a *worse* answer than a plain 24-hour
clock — not a locally correct one this backend happened to skip. The full
evidence for this decision (git, systemd, Deluge, borgbackup, llama.cpp)
lives in ``.planning/notes/vocabulary-and-presentation-decisions.md`` § 2;
this module implements that decision rather than re-arguing it. What that
decision leaves this backend is the *rendering*, not the choice: which
clock to render is now a product answer resolved once in ``core/`` from
``[ui] clock_format`` and handed in as the style. A twelve-hour style
therefore renders here in fixed English, the same call the ISO dates below
make — one language's tokens for everybody, rather than a locale database
this module exists not to have.

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
        if style is TimeStyle.HOUR_AND_MINUTE_24:
            return f"{value.hour:02d}:{value.minute:02d}"
        if style is TimeStyle.HOUR_MINUTE_AND_SECOND_24:
            return (f"{value.hour:02d}:{value.minute:02d}"
                    f":{value.second:02d}")
        # A twelve-hour clock here is fixed English, exactly as the date
        # styles above are fixed ISO: the meridiem token is written out
        # inline rather than exposed through an accessor, because a getter
        # for it is the locale-database field BACK-02 keeps out of this
        # backend. Routing the token through the message catalog was the
        # rejected alternative — it would put a translated fragment inside
        # a rendered value, which is the seam this module exists to hold.
        hour = value.hour % 12 or 12
        meridiem = "AM" if value.hour < 12 else "PM"
        if style is TimeStyle.HOUR_AND_MINUTE_12:
            return f"{hour}:{value.minute:02d} {meridiem}"
        if style is TimeStyle.HOUR_MINUTE_AND_SECOND_12:
            return (f"{hour}:{value.minute:02d}"
                    f":{value.second:02d} {meridiem}")
        raise ValueError(f"unsupported time style: {style!r}")

    def date(self, value: datetime, style: DateStyle) -> str:
        if style not in (DateStyle.WEEKDAY_AND_DAY, DateStyle.WEEKDAY_DAY_MONTH_YEAR):
            raise ValueError(f"unsupported date style: {style!r}")
        return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
