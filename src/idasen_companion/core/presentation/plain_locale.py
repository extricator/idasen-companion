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

This backend satisfies :class:`.protocols.LocaleFormatter` and nothing
else (BACK-01) — it renders values, and looks nothing up in a message
catalog.
"""

from __future__ import annotations

from datetime import datetime

from .specs import DateStyle, IntegerSpec, NumberSpec, TimeStyle

#: Fixed English weekday abbreviations, indexed by ``datetime.weekday()``
#: (Monday = 0). Deliberately carries no translation marker: this backend's
#: whole contract is invariance across machines and languages, and these two
#: date/time helpers are the one place that contract is allowed to diverge
#: from the Qt side's translated weekday names — the shape of that
#: divergence is written down as Phase 15's contract, not this phase's.
_WEEKDAY_ABBREVIATIONS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

#: Fixed English month abbreviations, indexed by calendar month minus one.
#: Same deliberate-invariance rule as the weekday table above.
_MONTH_ABBREVIATIONS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


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
        weekday = _WEEKDAY_ABBREVIATIONS[value.weekday()]
        if style is DateStyle.WEEKDAY_AND_DAY:
            return f"{weekday} {value.day:02d}"
        if style is DateStyle.WEEKDAY_DAY_MONTH_YEAR:
            month = _MONTH_ABBREVIATIONS[value.month - 1]
            return f"{weekday} {value.day:02d} {month} {value.year:04d}"
        raise ValueError(f"unsupported date style: {style!r}")
