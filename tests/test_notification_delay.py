"""The verbose delay a desktop notification says, in both languages.

The caller changed in Phase 14 and the values did not. This used to reach
``daemon/i18n.py``'s ``human_delay``, which built a throwaway presentation
context on every call; that module is gone and the daemon now owns one
:class:`~idasen_companion.core.presentation.Formatter` built from
its config, so these render through the shared implementation directly.
``human_delay`` had already been a pure ``duration_verbose`` delegation
since Phase 13, which is why every expected string below is unchanged from
when it was written.

``core/i18n.py`` binds a process-wide catalog; these tests bind and release
it explicitly, the same idiom ``tests/test_gettext_translator.py`` uses, so
no state leaks into other test modules.
"""

from __future__ import annotations

import pytest

from idasen_companion.core import i18n
from idasen_companion.core.presentation import (
    Formatter, PresentationContext,
)
from idasen_companion.core.locale_profile import TimeStyle
from idasen_companion.core.i18n import (
    GettextTranslator,
)
from idasen_companion.core.locale_profile import LocaleProfile
from idasen_companion.core.display_prefs import HeightUnit


@pytest.fixture(autouse=True)
def _reset_language():
    yield
    i18n.set_language(i18n.SYSTEM)


def _delay(seconds: int) -> str:
    """The pair the daemon builds for itself (D-06), rendering one delay.

    A duration reads no unit; CENTIMETRES is stated rather than defaulted
    because ``PresentationContext.unit`` carries no default on purpose — a
    caller states an answer instead of handing the context a policy
    question.
    """
    context = PresentationContext(
        locale=LocaleProfile("en_US"), translator=GettextTranslator(),
        unit=HeightUnit.CENTIMETRES,
        time_style=TimeStyle.HOUR_AND_MINUTE_24)
    return Formatter(context).duration_verbose(seconds)


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "1 second"),
        (30, "30 seconds"),
        (90, "1 minute"),            # floor, not round -- D-02's corrected range
        (3599, "59 minutes"),
        (3900, "1 hour 5 minutes"),  # D-02's own worked example
    ],
)
def test_the_delay_renders_english_under_the_system_catalog(seconds, expected):
    i18n.set_language(i18n.SYSTEM)
    assert _delay(seconds) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (30, "30 segundos"),
        (90, "1 minuto"),
        (3900, "1 hora y 5 minutos"),
    ],
)
def test_the_delay_translates_under_the_spanish_catalog(seconds, expected):
    i18n.set_language("es")
    assert _delay(seconds) == expected


def test_the_delay_no_longer_rounds():
    """The measured D-02 correction: 90 seconds now says '1 minute', not
    the '2 minutes' the old `round(seconds / 60)` arithmetic produced."""
    i18n.set_language(i18n.SYSTEM)
    assert _delay(90) == "1 minute"


def test_the_delay_no_longer_floors_hours_out():
    """3900 seconds now splits into hours and minutes, where the old
    arithmetic never split hours at all and said '65 minutes'."""
    i18n.set_language(i18n.SYSTEM)
    assert _delay(3900) == "1 hour 5 minutes"
