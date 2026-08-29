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
from PySide6.QtWidgets import QApplication, QDoubleSpinBox  # noqa: E402

from idasen_companion.core.presentation.english import EnglishTranslator  # noqa: E402
from idasen_companion.core.presentation.formatter import (  # noqa: E402
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.plain_locale import (  # noqa: E402
    PlainLocaleFormatter,
)
from idasen_companion.core.presentation.specs import (  # noqa: E402
    NumberSpec, TimeStyle,
)
from idasen_companion.core.units import HeightUnit  # noqa: E402
from idasen_companion.gui.locale_backend import QtLocaleFormatter  # noqa: E402
from idasen_companion.gui.pages.settings_form import SettingsFormPage  # noqa: E402
from idasen_companion.gui.util import fmt_day_heading  # noqa: E402


def _plain_formatter(unit: HeightUnit = HeightUnit.CENTIMETRES) -> Formatter:
    # English backend, not the Qt catalog -- these two assertions are about
    # the number/padding policy, not translation.
    return Formatter(PresentationContext(
        locale=PlainLocaleFormatter(), translator=EnglishTranslator(),
        unit=unit,
        time_style=TimeStyle.HOUR_AND_MINUTE_24))


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def locale(request):
    """Set the default QLocale for the test, restoring the previous one."""
    previous = QLocale()
    QLocale.setDefault(QLocale(request.param))
    try:
        yield
    finally:
        QLocale.setDefault(previous)


@pytest.mark.parametrize("locale", ["en_US"], indirect=True)
def test_english_locale_output_is_unchanged(locale):
    fmt = _plain_formatter()
    assert fmt.height(1.105) == "110.5 cm"
    assert fmt.duration_hm(3900) == "1h 05m"
    assert fmt.duration_hm(240) == "4m"
    assert fmt.duration(45) == "45s"


@pytest.mark.parametrize("locale", ["es_ES"], indirect=True)
def test_spanish_locale_uses_a_comma(locale):
    formatter = QtLocaleFormatter(QLocale())
    assert "," in formatter.number(110.5, NumberSpec(decimals=1))
    fmt = Formatter(PresentationContext(
        locale=formatter, translator=EnglishTranslator(),
        unit=HeightUnit.CENTIMETRES,
        time_style=TimeStyle.HOUR_AND_MINUTE_24))
    assert fmt.height(1.105).startswith("110,5")


@pytest.mark.parametrize("locale", ["en_US"], indirect=True)
def test_trim_drops_a_trailing_zero_decimal(locale):
    formatter = QtLocaleFormatter(QLocale())
    spec = NumberSpec(decimals=1, trim_trailing_zeroes=True)
    assert formatter.number(60.0, spec) == "60"
    assert formatter.number(60.5, spec) == "60.5"


@pytest.mark.parametrize("locale", ["en_US"], indirect=True)
def test_day_heading_renders_english_weekday_and_month_names(locale):
    when = datetime(2026, 8, 17)
    heading = fmt_day_heading(when)
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
    heading = fmt_day_heading(when)
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


@pytest.mark.parametrize("locale", ["es_ES"], indirect=True)
def test_a_double_spin_box_renders_the_locale_decimal_separator(locale, qapp):
    spin = QDoubleSpinBox()
    spin.setDecimals(1)
    spin.setRange(0, 200)
    spin.setValue(110.5)
    # Evidence that Qt resolves the widget's locale from QLocale::default()
    # at construction — no hand-written parsing needed for input either.
    assert "," in spin.text()
