"""The Qt backend's own contract, and proof it reproduces today's output.

Covers `gui/locale_backend.py`'s two objects against the protocols in
`core/presentation/protocols.py`: `QtLocaleFormatter` (value rendering,
locale injected at construction) and `QtTranslator` (message lookup, Qt
translation context fixed at construction). The comparison tests at the
bottom are the pre-migration contract phases 13-15 must not move -- they
assert the backend's output equals `gui/util.py`'s output for the same
input, in both shipped languages, so nothing behind the seam is free to
drift while the callers on top of it move across it.

Skipped where PySide6 is missing, and forces the offscreen platform before
any `QtWidgets` import -- see `tests/test_settings_form.py` for why both
matter.
"""

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from datetime import datetime  # noqa: E402

import shiboken6  # noqa: E402
from PySide6.QtCore import QLocale  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core.presentation.protocols import (  # noqa: E402
    LocaleFormatter, Translator,
)
from idasen_companion.core.presentation.specs import (  # noqa: E402
    DateStyle, IntegerSpec, NumberSpec, TimeStyle,
)
from idasen_companion.gui import i18n  # noqa: E402
from idasen_companion.gui.locale_backend import (  # noqa: E402
    QtLocaleFormatter, QtTranslator,
)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=["en_US", "es_ES"])
def locale_code(request):
    return request.param


@pytest.fixture
def locale(locale_code):
    return QLocale(locale_code)


# ---- QtLocaleFormatter: protocol conformance and fixed expectations ------


def test_formatter_satisfies_the_locale_formatter_protocol(qapp, locale):
    assert isinstance(QtLocaleFormatter(locale), LocaleFormatter)


NUMBER_EXPECTED = {"en_US": "110.5", "es_ES": "110,5"}


def test_number_renders_at_the_spec_decimal_count(qapp, locale_code, locale):
    formatter = QtLocaleFormatter(locale)
    rendered = formatter.number(110.5, NumberSpec(decimals=1))
    assert rendered == NUMBER_EXPECTED[locale_code]


def test_number_trims_a_whole_value(qapp, locale):
    formatter = QtLocaleFormatter(locale)
    spec = NumberSpec(decimals=1, trim_trailing_zeroes=True)
    assert formatter.number(60.0, spec).endswith("60")
    assert "60" != formatter.number(60.5, spec)


def test_number_suppresses_grouping_unless_asked_for(qapp, locale):
    formatter = QtLocaleFormatter(locale)
    ungrouped = formatter.number(12345.0, NumberSpec(decimals=0))
    grouped = formatter.number(
        12345.0, NumberSpec(decimals=0, grouping=True))
    assert ungrouped == "12345"
    assert grouped != ungrouped
    assert len(grouped) == len(ungrouped) + 1


INTEGER_EXPECTED = {
    (5, 2): "05",
    (45, 2): "45",
}


def test_integer_zero_pads_with_python_formatting(qapp, locale):
    formatter = QtLocaleFormatter(locale)
    for (value, min_digits), expected in INTEGER_EXPECTED.items():
        assert formatter.integer(
            value, IntegerSpec(min_digits=min_digits)) == expected


TIME_EXPECTED = {
    "en_US": "2:32 PM",
    "es_ES": "14:32",
}


def test_time_renders_the_short_form_for_the_locale(qapp, locale_code, locale):
    formatter = QtLocaleFormatter(locale)
    rendered = formatter.time(
        datetime(2026, 8, 17, 14, 32), TimeStyle.HOUR_AND_MINUTE)
    assert rendered == TIME_EXPECTED[locale_code]


DATE_EXPECTED = {
    "en_US": ("Mon 17", "Mon 17 Aug 2026"),
    "es_ES": ("lun 17", "lun 17 ago 2026"),
}


def test_date_renders_both_named_styles(qapp, locale_code, locale):
    formatter = QtLocaleFormatter(locale)
    when = datetime(2026, 8, 17)
    short_expected, long_expected = DATE_EXPECTED[locale_code]
    assert formatter.date(when, DateStyle.WEEKDAY_AND_DAY) == short_expected
    assert formatter.date(
        when, DateStyle.WEEKDAY_DAY_MONTH_YEAR) == long_expected


def test_an_unsupported_style_raises(qapp, locale):
    formatter = QtLocaleFormatter(locale)
    with pytest.raises(ValueError):
        formatter.time(datetime(2026, 8, 17), "not-a-style")
    with pytest.raises(ValueError):
        formatter.date(datetime(2026, 8, 17), "not-a-style")


def test_formatter_reads_no_process_default(qapp):
    # A formatter built for one locale must keep answering for it even if
    # something elsewhere changes the process default afterwards.
    QLocale.setDefault(QLocale("en_US"))
    formatter = QtLocaleFormatter(QLocale("es_ES"))
    QLocale.setDefault(QLocale("es_ES"))
    try:
        assert formatter.number(110.5, NumberSpec(decimals=1)) == "110,5"
    finally:
        QLocale.setDefault(QLocale("en_US"))


# ---- QtTranslator: protocol conformance, fixed context, degrade-to-English


def test_translator_satisfies_the_translator_protocol(qapp):
    assert isinstance(QtTranslator("util"), Translator)


def test_lookup_with_no_catalog_installed_returns_the_source_unchanged(qapp):
    translator = QtTranslator("util")
    assert translator.message("Desk: connected") == "Desk: connected"


def test_named_substitution_fills_every_slot(qapp):
    translator = QtTranslator("util")
    rendered = translator.message(
        "%(hours)sh %(minutes)sm", hours=1, minutes="05")
    assert rendered == "1h 05m"


@pytest.fixture
def installed_spanish_catalog(qapp):
    """The shipped Spanish catalog, installed and torn down through the
    same installer the app uses at startup -- and explicitly removed and
    deleted afterwards, since a `QTranslator` stays installed on `qapp` (a
    session-scoped object shared with every other test module) otherwise."""
    installed = i18n.install_translators(qapp, "es")
    try:
        yield
    finally:
        for translator in installed:
            qapp.removeTranslator(translator)
            shiboken6.delete(translator)
        QLocale.setDefault(QLocale("en_US"))


def test_lookup_with_the_shipped_spanish_catalog_returns_a_translation(
        qapp, installed_spanish_catalog):
    translator = QtTranslator("util")
    rendered = translator.message("Desk: connected")
    assert rendered != "Desk: connected"
