"""The one implementation of every day/clock formatter the app renders.

A "moment" here is different from a "word" (see :mod:`.words`'s own
docstring, which draws the line at "a word needs a translator and nothing
else: no locale, no unit"): rendering a :class:`~datetime.datetime` needs a
:class:`~.protocols.LocaleFormatter` for all four functions below, and a
:class:`~.protocols.Translator` for one of them, so these do not belong in
:mod:`.words`. Each function takes its capability object(s) as its first
argument(s) and reads no module global — the same Qt-free, global-free
contract PRES-02 asks of every function under ``core/presentation/``.

**Why not Python's own C-locale-bound date-formatting method on**
``datetime`` **itself.** That method renders C-locale English regardless of
the app language or ``$LANG``, because nothing here calls
``locale.setlocale`` — the trap every formatter below is written to avoid.
A backend is asked for a *style* (:class:`~.specs.DateStyle`,
:class:`~.specs.TimeStyle`) and decides on its own how to render it; nothing
in this module accepts, threads or constructs a directive- or
Qt-format-code-shaped pattern.

**Why :func:`day_heading`'s field order is fixed.** Its style renders
weekday-day-month-year, an order that suits both shipped languages (en, es).
A locale that leads with the year would want
``QLocale.FormatType.LongFormat`` instead, at the cost of the compact shape
this heading is written to match — that trade is the Qt backend's decision
to make, not this module's.

**Why :func:`day_and_clock` is one whole translated message.** The
separating space between the day and the clock stops being a Python literal
and becomes part of a translated pattern instead — a language that
separates a date from a time differently has no other way to say so.
Neither slot is itself a translated value (:func:`day_short` and
:func:`clock` render through a locale backend only and carry no catalog
entry of their own, same as :func:`day_heading`), so no mechanical check can
ever see this site; it converts on that reasoning alone.
"""

from __future__ import annotations

from datetime import datetime

from .protocols import LocaleFormatter, Translator
from .register import DAY_AND_CLOCK
from .specs import DateStyle, TimeStyle


def day_short(locale: LocaleFormatter, when: datetime) -> str:
    """A short calendar day marker, e.g. "Mon 17" (Qt) / "2026-08-17"
    (Qt-free). Carries no catalog entry — it renders through the locale
    backend only."""
    return locale.date(when, DateStyle.WEEKDAY_AND_DAY)


def day_heading(locale: LocaleFormatter, when: datetime) -> str:
    """A full calendar date as a day-separator heading, e.g.
    "Mon 17 Aug 2026" (Qt) / "2026-08-17" (Qt-free). Carries no catalog
    entry — it renders through the locale backend only."""
    return locale.date(when, DateStyle.WEEKDAY_DAY_MONTH_YEAR)


def clock(locale: LocaleFormatter, style: TimeStyle, when: datetime) -> str:
    """A wall-clock time on the clock ``style`` names, e.g. "14:32" or
    "2:32 PM". Carries no catalog entry — it renders through the locale
    backend only.

    ``style`` is an argument rather than a constant chosen here because
    which clock the app shows is a user setting resolved once, in
    ``core/clock_format.py``, and carried to every renderer by the
    presentation context. A member named in this body would be a second
    place that answers the same question.
    """
    return locale.time(when, style)


def day_and_clock(locale: LocaleFormatter, translator: Translator,
                  style: TimeStyle, when: datetime) -> str:
    """A day plus a wall-clock time, e.g. "Mon 17 14:32", as one whole
    translated message — see the module docstring for why this composes
    :func:`day_short` and :func:`clock` through a catalog pattern rather
    than joining them in Python. ``style`` travels through to the clock
    half for the reason :func:`clock` gives."""
    return translator.message(
        DAY_AND_CLOCK, day=day_short(locale, when),
        clock=clock(locale, style, when))
