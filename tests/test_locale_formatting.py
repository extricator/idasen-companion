"""Locale-aware number formatting in ``gui.util``.

Covers the scope decision recorded in the quick task: ``QLocale`` governs
the fractional centimetre values (where a locale actually changes the
glyphs), while the small integers in ``fmt_hm``/``fmt_duration`` keep Python
formatting — only their unit letters are translated.

Skipped where PySide6 is missing, and forces the offscreen platform before
any ``QtWidgets`` import — see ``test_settings_form.py`` for why both
matter.
"""

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QLocale  # noqa: E402
from PySide6.QtWidgets import QApplication, QDoubleSpinBox  # noqa: E402

from idasen_companion.gui.pages.settings_form import SettingsFormPage  # noqa: E402
from idasen_companion.gui.util import (  # noqa: E402
    fmt_duration, fmt_height, fmt_hm, fmt_number,
)


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
    assert fmt_height(1.105) == "110.5 cm"
    assert fmt_hm(3900) == "1h 05m"
    assert fmt_hm(240) == "4m"
    assert fmt_duration(45) == "45s"


@pytest.mark.parametrize("locale", ["es_ES"], indirect=True)
def test_spanish_locale_uses_a_comma(locale):
    assert "," in fmt_number(110.5)
    assert fmt_height(1.105).startswith("110,5")


@pytest.mark.parametrize("locale", ["en_US"], indirect=True)
def test_trim_drops_a_trailing_zero_decimal(locale):
    assert fmt_number(60.0, 1, trim=True) == "60"
    assert fmt_number(60.5, 1, trim=True) == "60.5"


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
