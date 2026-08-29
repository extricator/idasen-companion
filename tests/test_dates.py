"""Behaviour of the shared moment renderers in ``core/presentation/dates.py``.

Pure ``core/`` tests: no Qt, no window, no ``QT_QPA_PLATFORM``.
``tests/test_baseline_vocabulary.py`` already covers the Qt-rendered path,
end to end through ``gui.util``, so this module exercises only the shared
layer: the *style* each function asks the locale backend for (against
``FakeLocale``'s markers, which is what proves the request itself rather
than a rendered string) and the fixed Qt-free contract 15-01 landed (against
the real ``PlainLocaleFormatter``).

Every input below is a frozen ``datetime`` literal — never the system
clock read at call time — the same reason these four functions can be
pinned at all: each takes its moment as a ``when`` argument rather than
reading the clock itself.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from idasen_companion.core.presentation import dates, register
from idasen_companion.core.presentation.plain_locale import PlainLocaleFormatter
from idasen_companion.core.presentation.specs import DateStyle, TimeStyle

from presentation_fakes import FakeLocale, FakeTranslator

_WHEN = datetime(2026, 8, 17, 14, 32)


# ----- the three locale-only functions, against the fake ------------------


def test_day_short_asks_for_the_weekday_and_day_style():
    locale = FakeLocale()
    result = dates.day_short(locale, _WHEN)
    assert [(call.value, call.request) for call in locale.calls] == [
        (_WHEN, DateStyle.WEEKDAY_AND_DAY)]
    assert result == f"D({_WHEN!r}, {DateStyle.WEEKDAY_AND_DAY!r})"


def test_day_heading_asks_for_the_weekday_day_month_year_style():
    locale = FakeLocale()
    result = dates.day_heading(locale, _WHEN)
    assert [(call.value, call.request) for call in locale.calls] == [
        (_WHEN, DateStyle.WEEKDAY_DAY_MONTH_YEAR)]
    assert result == f"D({_WHEN!r}, {DateStyle.WEEKDAY_DAY_MONTH_YEAR!r})"


@pytest.mark.parametrize("style", list(TimeStyle))
def test_clock_asks_for_the_style_it_was_given(style):
    """The style is passed through untouched: `dates` names no member of
    its own, because which clock the app shows is resolved once from the
    user's setting and carried in by the presentation context."""
    locale = FakeLocale()
    result = dates.clock(locale, style, _WHEN)
    assert [(call.value, call.request) for call in locale.calls] == [
        (_WHEN, style)]
    assert result == f"T({_WHEN!r}, {style!r})"


# ----- the same three, against the real Qt-free backend -------------------
# Pinning the ISO/24-hour contract 15-01 landed: both date styles converge
# on one ISO 8601 shape, and the clock stays 24-hour.


def test_day_short_renders_iso_on_the_plain_backend():
    assert dates.day_short(PlainLocaleFormatter(), _WHEN) == "2026-08-17"


def test_day_heading_renders_iso_on_the_plain_backend():
    assert dates.day_heading(PlainLocaleFormatter(), _WHEN) == "2026-08-17"


def test_clock_renders_24_hour_on_the_plain_backend():
    assert dates.clock(
        PlainLocaleFormatter(), TimeStyle.HOUR_AND_MINUTE_24, _WHEN) == "14:32"


def test_a_morning_hour_stays_zero_padded_on_the_plain_backend():
    assert dates.clock(
        PlainLocaleFormatter(), TimeStyle.HOUR_AND_MINUTE_24,
        datetime(2026, 8, 17, 9, 5)) == "09:05"


# ----- day_and_clock: composing the two rendered values --------------------


def test_day_and_clock_composes_through_the_one_translated_pattern():
    """Both slots arrive as keyword substitutions into ``DAY_AND_CLOCK`` --
    never concatenated, never interpolated. Asserted against the fake
    translator so what is under test is the *source string looked up* and
    *what was substituted*, not a rendered value.
    """
    locale, translator = FakeLocale(), FakeTranslator()
    style = TimeStyle.HOUR_AND_MINUTE_24
    result = dates.day_and_clock(locale, translator, style, _WHEN)

    assert [call.method for call in locale.calls] == ["date", "time"]
    assert len(translator.calls) == 1
    call = translator.calls[0]
    assert call.source == register.DAY_AND_CLOCK
    assert call.values == {
        "day": dates.day_short(FakeLocale(), _WHEN),
        "clock": dates.clock(FakeLocale(), style, _WHEN),
    }
    # The result is exactly the pattern's own substitution -- not a second,
    # independently-built string -- which is what "never concatenates" means
    # here: there is nothing for `+`, an f-string or `.join()` to have done.
    assert result == translator.message(
        register.DAY_AND_CLOCK,
        day=dates.day_short(FakeLocale(), _WHEN),
        clock=dates.clock(FakeLocale(), style, _WHEN))


def test_day_and_clock_renders_the_finished_qt_free_string():
    locale = PlainLocaleFormatter()
    translator = FakeTranslator()
    result = dates.day_and_clock(
        locale, translator, TimeStyle.HOUR_AND_MINUTE_24, _WHEN)
    assert result == translator.message(
        register.DAY_AND_CLOCK, day="2026-08-17", clock="14:32")
