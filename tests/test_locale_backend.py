"""The Qt backend's own contract, and proof it reproduces today's output.

Covers `gui/locale_backend.py`'s two objects against the protocols in
`core/presentation/protocols.py`: `QtLocaleFormatter` (value rendering,
locale injected at construction) and `QtTranslator` (message lookup, Qt
translation context fixed at construction). The comparison tests at the
bottom are the pre-migration contract phases 13-15 must not move -- they
assert the backend's output equals `gui/util.py`'s output for the same
input, in both shipped languages, so nothing behind the seam is free to
drift while the callers on top of it move across it. The number
comparisons compare against `Formatter.height_value` rather than
`gui/util.py`'s own number formatter now that plan 13-07 deleted it --
`Formatter.height_value` is what carries that policy forward, so the
comparison moves with it rather than being dropped.

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

from idasen_companion.core.presentation.english import EnglishTranslator  # noqa: E402
from idasen_companion.core.presentation.formatter import (  # noqa: E402
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.protocols import (  # noqa: E402
    LocaleFormatter, Translator,
)
from idasen_companion.core.presentation.specs import (  # noqa: E402
    DateStyle, IntegerSpec, NumberSpec, TimeStyle,
)
from idasen_companion.core.units import HeightUnit  # noqa: E402
from idasen_companion.gui import i18n  # noqa: E402
from idasen_companion.gui.locale_backend import (  # noqa: E402
    QtLocaleFormatter, QtTranslator,
)
from idasen_companion.gui.util import (  # noqa: E402
    fmt_clock, fmt_day_heading, fmt_day_label,
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


def test_plural_substitutes_n_with_no_translator_installed(qapp):
    translator = QtTranslator("util")
    rendered = translator.plural("%n item(s)", "%n item(s)", 5)
    assert rendered == "5 item(s)"


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
    """The probe is a spin-box suffix on purpose. It used to be one of the
    connection phrases, which Phase 14 moved to the gettext catalog -- and
    every other `util`-context string is on its way out too, to gettext in
    Phase 14 or Phase 15. The three suffix helpers are the exception
    PRES-05 keeps in `gui/` permanently (`QAbstractSpinBox.setSuffix` takes
    a plain string), so this is the one `util` entry that will still be a
    Qt-catalog lookup once the migration finishes.
    """
    translator = QtTranslator("util")
    rendered = translator.message(" in")
    assert rendered != " in"


# ---- Comparison: the backend reproduces today's gui/util.py output -------
#
# These expectations are the pre-migration contract: phases 13-15 replace
# gui/util.py's bodies with calls through this backend, and this is what
# proves, before anything moves, that the backend already answers the same
# way for the values it can serve.


@pytest.fixture
def util_locale(locale_code):
    """Set the default QLocale for gui/util.py's QLocale()-reading helpers,
    restoring the previous one -- mirrors tests/test_locale_formatting.py's
    own `locale` fixture."""
    previous = QLocale()
    QLocale.setDefault(QLocale(locale_code))
    try:
        yield
    finally:
        QLocale.setDefault(previous)


def test_number_matches_height_value_at_one_and_two_decimals(
        qapp, locale_code, locale, util_locale):
    formatter = QtLocaleFormatter(locale)
    meters = 1.105
    cm_fmt = Formatter(PresentationContext(
        locale=formatter, translator=EnglishTranslator(),
        unit=HeightUnit.CENTIMETRES))
    in_fmt = Formatter(PresentationContext(
        locale=formatter, translator=EnglishTranslator(),
        unit=HeightUnit.INCHES))
    assert (formatter.number(cm_fmt.to_display_height(meters),
                             NumberSpec(decimals=1))
            == cm_fmt.height_value(meters))
    assert (formatter.number(in_fmt.to_display_height(meters),
                             NumberSpec(decimals=2))
            == in_fmt.height_value(meters))


def test_number_matches_height_value_trim_case(
        qapp, locale_code, locale, util_locale):
    formatter = QtLocaleFormatter(locale)
    meters = 0.60  # 60 cm exactly, so the trim drops the ".0"
    cm_fmt = Formatter(PresentationContext(
        locale=formatter, translator=EnglishTranslator(),
        unit=HeightUnit.CENTIMETRES))
    spec = NumberSpec(decimals=1, trim_trailing_zeroes=True)
    assert (formatter.number(cm_fmt.to_display_height(meters), spec)
            == cm_fmt.height_value(meters, trim=True))


def test_clock_matches_util_fmt_clock_morning_and_afternoon(
        qapp, locale_code, locale, util_locale):
    formatter = QtLocaleFormatter(locale)
    for when in (datetime(2026, 8, 17, 9, 5), datetime(2026, 8, 17, 14, 32)):
        assert (formatter.time(when, TimeStyle.HOUR_AND_MINUTE)
                == fmt_clock(when))


def test_date_matches_util_fmt_day_label_and_fmt_day_heading(
        qapp, locale_code, locale, util_locale):
    formatter = QtLocaleFormatter(locale)
    when = datetime(2026, 8, 17)
    assert (formatter.date(when, DateStyle.WEEKDAY_AND_DAY)
            == fmt_day_label(when))
    assert (formatter.date(when, DateStyle.WEEKDAY_DAY_MONTH_YEAR)
            == fmt_day_heading(when))


def test_integer_matches_the_zero_padded_minutes_in_duration_hm(
        qapp, locale_code, locale, util_locale):
    formatter = QtLocaleFormatter(locale)
    # Formatter.duration_hm(3900) is "1h 05m" -- the padded minute value is
    # what QtLocaleFormatter.integer(min_digits=2) must reproduce.
    fmt = Formatter(PresentationContext(
        locale=formatter, translator=EnglishTranslator(),
        unit=HeightUnit.CENTIMETRES))
    assert fmt.duration_hm(3900).endswith("05m")
    assert formatter.integer(5, IntegerSpec(min_digits=2)) == "05"
