"""``daemon/i18n.py``'s ``human_delay`` -- now a thin caller of the shared
duration policy, verified through the real ``gettext`` catalog in both
English and Spanish.

``core/i18n.py`` binds a process-wide catalog; these tests bind and release
it explicitly, the same idiom ``tests/test_gettext_translator.py`` uses, so
no state leaks into other test modules.
"""

from __future__ import annotations

import pytest

from idasen_companion.core import i18n
from idasen_companion.daemon.i18n import human_delay


@pytest.fixture(autouse=True)
def _reset_language():
    yield
    i18n.set_language(i18n.SYSTEM)


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
def test_human_delay_renders_english_under_the_system_catalog(seconds, expected):
    i18n.set_language(i18n.SYSTEM)
    assert human_delay(seconds) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (30, "30 segundos"),
        (90, "1 minuto"),
        (3900, "1 hora y 5 minutos"),
    ],
)
def test_human_delay_translates_under_the_spanish_catalog(seconds, expected):
    i18n.set_language("es")
    assert human_delay(seconds) == expected


def test_human_delay_no_longer_rounds():
    """The measured D-02 correction: 90 seconds now says '1 minute', not
    the '2 minutes' the old `round(seconds / 60)` arithmetic produced."""
    i18n.set_language(i18n.SYSTEM)
    assert human_delay(90) == "1 minute"


def test_human_delay_no_longer_floors_hours_out():
    """3900 seconds now splits into hours and minutes, where the old
    arithmetic never split hours at all and said '65 minutes'."""
    i18n.set_language(i18n.SYSTEM)
    assert human_delay(3900) == "1 hour 5 minutes"
