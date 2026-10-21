"""Locale-aware number formatting in ``gui.util`` and the shared ``Formatter``.

Covers the scope decision recorded in the quick task: ``QLocale`` governs
the fractional centimetre values (where a locale actually changes the
glyphs), while the small integers in ``Formatter.duration``/``duration_hm``
keep Python formatting — only their unit letters are translated.

Skipped where PySide6 is missing, and forces the offscreen platform before
any ``QtWidgets`` import — see ``test_settings_form.py`` for why both
matter.
"""

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from datetime import datetime  # noqa: E402

from PySide6.QtCore import QLocale  # noqa: E402

from idasen_companion.core.presentation import EnglishTranslator  # noqa: E402
from idasen_companion.core.i18n import (  # noqa: E402
    GettextTranslator,
)
from idasen_companion.core.presentation import (  # noqa: E402
    Formatter, PresentationContext,
)
from idasen_companion.core.locale_profile import (  # noqa: E402
    LocaleProfile,
)
from idasen_companion.core.locale_profile import TimeStyle  # noqa: E402
from idasen_companion.core.display_prefs import HeightUnit  # noqa: E402
from idasen_companion.core.lengths import Length
from idasen_companion.core.locale_profile import LocaleProfile  # noqa: E402
from idasen_companion.gui.pages.settings_form import SettingsFormPage  # noqa: E402
from idasen_companion.gui.util import fmt_day_heading  # noqa: E402


@pytest.fixture
def locale(request):
    """Set the default QLocale for the test, restoring the previous one."""
    previous = QLocale()
    QLocale.setDefault(QLocale(request.param))
    try:
        yield
    finally:
        QLocale.setDefault(previous)


@pytest.mark.parametrize("locale", ["es_ES"], indirect=True)
def test_spanish_locale_uses_a_comma(locale):
    formatter = LocaleProfile(QLocale().name())
    assert "," in formatter.number(110.5, decimals=1)
    fmt = Formatter(PresentationContext(
        locale=formatter, translator=EnglishTranslator(),
        unit=HeightUnit.CENTIMETRES,
        time_style=TimeStyle.HOUR_AND_MINUTE_24))
    assert fmt.height(Length(1.105)).startswith("110,5")


@pytest.mark.parametrize("locale", ["en_US"], indirect=True)
def test_trim_drops_a_trailing_zero_decimal(locale):
    formatter = LocaleProfile(QLocale().name())
    assert formatter.number(
        60.0, decimals=1, trim_trailing_zeroes=True) == "60"
    assert formatter.number(
        60.5, decimals=1, trim_trailing_zeroes=True) == "60.5"


def _ambient_formatter() -> Formatter:
    """The window pairing on whatever QLocale the `locale` fixture set.

    fmt_day_heading takes a Formatter now rather than reading the process
    default itself, so these tests build one over the ambient locale — the
    thing the fixture is actually varying.
    """
    return Formatter(PresentationContext(
        locale=LocaleProfile(QLocale().name()), translator=GettextTranslator(),
        unit=HeightUnit.CENTIMETRES,
        time_style=TimeStyle.HOUR_AND_MINUTE_24))


@pytest.mark.parametrize("locale", ["en_US"], indirect=True)
def test_day_heading_renders_english_weekday_and_month_names(locale):
    when = datetime(2026, 8, 17)
    heading = fmt_day_heading(_ambient_formatter(), when)
    assert QLocale().dayName(when.isoweekday(),
                             QLocale.FormatType.ShortFormat) in heading
    assert QLocale().monthName(when.month,
                               QLocale.FormatType.ShortFormat) in heading
    assert "2026" in heading


@pytest.mark.parametrize("locale", ["es_ES"], indirect=True)
def test_day_heading_renders_spanish_weekday_and_month_names(locale):
    """Assert on the locale's own supplied names, not an exact string --
    QLocale governs the words, this only checks they made it in."""
    when = datetime(2026, 8, 17)
    heading = fmt_day_heading(_ambient_formatter(), when)
    assert QLocale().dayName(when.isoweekday(),
                             QLocale.FormatType.ShortFormat) in heading
    assert QLocale().monthName(when.month,
                               QLocale.FormatType.ShortFormat) in heading
    assert "2026" in heading


# ---- call sites: spin suffixes and input, under the pinned/overridden locale


@pytest.mark.parametrize("locale", ["en_US"], indirect=True)
def test_minute_and_second_spin_suffixes(locale, qapp):
    assert SettingsFormPage._minutes_spin(1, 10).suffix() == " min"
    assert SettingsFormPage._seconds_spin(0, 10).suffix() == " s"
