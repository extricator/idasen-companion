"""Rendering assertions for `PlainLocaleFormatter`, plus the
locale-independence gate for BACK-04.

The gate is deliberately two-legged, and the two legs are not peers: the
**structural** check below (`test_structural_gate_holds_no_locale_reference`)
is what proves the property, because it runs everywhere this suite runs,
including the RPM's `%check` on a container that carries no non-English
langpack. The **behavioural** test beside it is corroboration on a machine
that happens to have both locales installed — it skips honestly, rather
than failing, where they are not, and says so at the skip.

**The structural gate covers the whole shared package, not one module.**
BACK-04's promise is about what a Qt-free *process* renders, and a caller
reaches that rendering through `Formatter`, `dates.py`, `words.py` and the
rest of `core/presentation/` — a POSIX-locale-following call reintroduced
into any of them breaks the promise exactly as one in `plain_locale.py`
would. `tests/test_golden_presentation_contract.py` has the behavioural
counterpart that drives every shared formatter under a hostile locale, and
that one skips where the locale is absent; this is the leg that does not.
"""

import ast
import locale
from datetime import datetime
from pathlib import Path

import pytest

from idasen_companion.core.presentation.plain_locale import PlainLocaleFormatter
from idasen_companion.core.presentation.protocols import LocaleFormatter
from idasen_companion.core.presentation.specs import (
    DateStyle,
    IntegerSpec,
    NumberSpec,
    TimeStyle,
)

PRESENTATION_DIR = (
    Path(__file__).resolve().parent.parent
    / "src" / "idasen_companion" / "core" / "presentation"
)

PLAIN_LOCALE_PATH = PRESENTATION_DIR / "plain_locale.py"

#: Every module of the shared presentation package, discovered rather than
#: listed, so a module a later phase adds is gated the day it lands.
PRESENTATION_MODULES = sorted(PRESENTATION_DIR.rglob("*.py"))

FORMATTER = PlainLocaleFormatter()


# ---- Rendering ------------------------------------------------------------

def test_satisfies_locale_formatter_protocol_and_nothing_more():
    assert isinstance(FORMATTER, LocaleFormatter)


@pytest.mark.parametrize("value,decimals,expected", [
    (110.5, 1, "110.5"),  # centimetres
    (43.51, 2, "43.51"),  # inches
])
def test_number_renders_both_height_decimal_counts(value, decimals, expected):
    assert FORMATTER.number(value, NumberSpec(decimals=decimals)) == expected


def test_number_trims_a_whole_value_to_no_fraction():
    spec = NumberSpec(decimals=1, trim_trailing_zeroes=True)
    assert FORMATTER.number(110.0, spec) == "110"


def test_number_does_not_trim_a_fractional_value():
    spec = NumberSpec(decimals=1, trim_trailing_zeroes=True)
    assert FORMATTER.number(110.5, spec) == "110.5"


def test_number_grouping_off_by_default():
    assert FORMATTER.number(1234.5, NumberSpec(decimals=1)) == "1234.5"


def test_number_grouping_uses_a_comma_when_requested():
    spec = NumberSpec(decimals=1, grouping=True)
    assert FORMATTER.number(1234.5, spec) == "1,234.5"


def test_integer_unpadded_by_default():
    assert FORMATTER.integer(5, IntegerSpec()) == "5"


def test_integer_zero_padded_to_min_digits():
    assert FORMATTER.integer(5, IntegerSpec(min_digits=2)) == "05"


# The time cases below are unchanged by D-08 -- "14:32" already contains no
# words, so the time half of this backend was never part of the divergence
# the date half is settling here.
@pytest.mark.parametrize("hour,minute,expected", [
    (9, 5, "09:05"),      # morning
    (12, 0, "12:00"),     # noon
    (14, 32, "14:32"),    # afternoon
    (0, 0, "00:00"),      # midnight
])
def test_time_renders_two_digit_24_hour(hour, minute, expected):
    when = datetime(2026, 8, 21, hour, minute)
    assert FORMATTER.time(when, TimeStyle.HOUR_AND_MINUTE) == expected


# The clock a style names is rendered, never chosen: the twelve-hour
# members print fixed English AM/PM with no leading zero on the hour, the
# same fixed-tokens call the ISO dates below make.
@pytest.mark.parametrize("hour,minute,expected", [
    (9, 5, "9:05 AM"),      # morning, no leading zero on the hour
    (12, 0, "12:00 PM"),    # noon wraps to twelve, and is PM
    (14, 32, "2:32 PM"),    # afternoon
    (0, 0, "12:00 AM"),     # midnight wraps to twelve, and is AM
])
def test_time_renders_a_fixed_english_twelve_hour_clock(hour, minute, expected):
    when = datetime(2026, 8, 21, hour, minute)
    assert FORMATTER.time(when, TimeStyle.HOUR_AND_MINUTE_12) == expected


@pytest.mark.parametrize("hour,minute,expected", [
    (9, 5, "09:05"),
    (12, 0, "12:00"),
    (14, 32, "14:32"),
    (0, 0, "00:00"),
])
def test_time_renders_the_named_twenty_four_hour_clock(hour, minute, expected):
    when = datetime(2026, 8, 21, hour, minute)
    assert FORMATTER.time(when, TimeStyle.HOUR_AND_MINUTE_24) == expected


@pytest.mark.parametrize("style,expected", [
    (TimeStyle.HOUR_MINUTE_AND_SECOND_24, "14:32:05"),
    (TimeStyle.HOUR_MINUTE_AND_SECOND_12, "2:32:05 PM"),
])
def test_time_renders_the_seconds_bearing_styles(style, expected):
    when = datetime(2026, 8, 21, 14, 32, 5)
    assert FORMATTER.time(when, style) == expected


@pytest.mark.parametrize("style,expected", [
    (TimeStyle.HOUR_MINUTE_AND_SECOND_24, "09:05:07"),
    (TimeStyle.HOUR_MINUTE_AND_SECOND_12, "9:05:07 AM"),
])
def test_time_zero_pads_the_seconds_field(style, expected):
    when = datetime(2026, 8, 21, 9, 5, 7)
    assert FORMATTER.time(when, style) == expected


def test_time_an_unsupported_style_raises():
    with pytest.raises(ValueError):
        FORMATTER.time(datetime(2026, 8, 17, 14, 32), "not-a-style")


def test_date_weekday_and_day_renders_iso_8601():
    when = datetime(2026, 8, 17, 14, 32)
    assert FORMATTER.date(when, DateStyle.WEEKDAY_AND_DAY) == "2026-08-17"


def test_date_weekday_day_month_year_renders_iso_8601():
    when = datetime(2026, 8, 17, 14, 32)
    assert FORMATTER.date(when, DateStyle.WEEKDAY_DAY_MONTH_YEAR) == "2026-08-17"


def test_date_zero_pads_a_single_digit_month_and_day():
    when = datetime(2026, 1, 3)
    assert FORMATTER.date(when, DateStyle.WEEKDAY_AND_DAY) == "2026-01-03"
    assert FORMATTER.date(when, DateStyle.WEEKDAY_DAY_MONTH_YEAR) == "2026-01-03"


def test_date_the_two_styles_converge_on_the_same_rendering():
    # D-08: both DateStyle members render an ISO 8601 date here, so this
    # backend answers a short-marker request and a full-heading request
    # identically -- an equality assertion records that relationship rather
    # than a value either side could be seeded from a bug.
    when = datetime(2026, 8, 17, 14, 32)
    assert (FORMATTER.date(when, DateStyle.WEEKDAY_AND_DAY)
            == FORMATTER.date(when, DateStyle.WEEKDAY_DAY_MONTH_YEAR))


def test_date_an_unsupported_style_still_raises():
    when = datetime(2026, 8, 17)
    with pytest.raises(ValueError):
        FORMATTER.date(when, "not-a-style")


# ---- Structural locale-independence gate -----------------------------------

def _locale_offenders(tree: ast.AST) -> list[str]:
    """Every node in `tree` that would let a rendered value vary with the
    process locale: an import of the locale module under any alias, a call
    that sets or reads through it, a call into the C library's own
    locale-sensitive date conversion, a bare reference to a locale-category
    name, or a locale-sensitive number presentation type in a format spec.

    Reads the parsed tree, never the file's own text, so an explanatory
    comment sitting next to the code cannot satisfy this check by accident —
    and `specs.py`, whose docstrings discuss the very conversion named here
    as the shape it exists not to be, stays clean for that reason.
    """
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "locale":
                    offenders.append(f"{node.lineno}: import locale")
        elif isinstance(node, ast.ImportFrom) and node.module == "locale":
            offenders.append(f"{node.lineno}: from locale import ...")
        elif isinstance(node, ast.Call):
            func = node.func
            called = (func.attr if isinstance(func, ast.Attribute)
                       else func.id if isinstance(func, ast.Name) else None)
            if called in {"setlocale", "format_string", "nl_langinfo",
                          "localeconv", "strftime", "strptime"}:
                offenders.append(f"{node.lineno}: {called}(...)")
        elif isinstance(node, ast.Name) and node.id.startswith("LC_"):
            offenders.append(f"{node.lineno}: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("LC_"):
            offenders.append(f"{node.lineno}: .{node.attr}")
        elif isinstance(node, ast.JoinedStr):
            for part in node.values:
                if not (isinstance(part, ast.FormattedValue)
                        and part.format_spec is not None):
                    continue
                for spec_part in part.format_spec.values:
                    if (isinstance(spec_part, ast.Constant)
                            and isinstance(spec_part.value, str)
                            and spec_part.value.endswith("n")):
                        offenders.append(
                            f"{node.lineno}: locale-sensitive 'n' format type")
    return offenders


def test_structural_gate_holds_no_locale_reference_in_plain_locale():
    """The gate this property's proof is anchored on. It has been proven to
    go red twice by hand (once for an added `import locale`, once for an
    added `setlocale` call), each time reverted; see 12-05-SUMMARY.md for
    the exact commands and observed exit statuses.
    """
    tree = ast.parse(PLAIN_LOCALE_PATH.read_text())
    offenders = _locale_offenders(tree)
    assert not offenders, (
        "plain_locale.py reads process locale state, defeating BACK-04's "
        "fixed-convention policy: " + "; ".join(offenders))


def test_the_package_walk_found_the_modules_it_gates():
    """A parametrization over an empty list passes by generating nothing,
    so the walk that feeds the gate below is asserted separately: a broken
    path would otherwise silently retire the whole check.
    """
    found = {path.name for path in PRESENTATION_MODULES}
    assert {"plain_locale.py", "formatter.py", "dates.py"} <= found, (
        f"the presentation package walk found {sorted(found)} — the "
        f"structural gate below is only as wide as this list")


@pytest.mark.parametrize(
    "module_path", PRESENTATION_MODULES, ids=lambda p: p.name)
def test_no_module_of_the_shared_package_reads_process_locale_state(
        module_path):
    """The same gate, over every module a Qt-free caller's rendering passes
    through. `PlainLocaleFormatter` is where the temptation is concentrated,
    but it is not the only place a locale-following call would defeat
    BACK-04: the journal's output is composed by `Formatter`, `dates.py` and
    `words.py` on top of it, and a weekday rendered through the C library
    there reads the process locale exactly as one rendered here would.
    """
    offenders = _locale_offenders(ast.parse(module_path.read_text()))
    assert not offenders, (
        f"{module_path.name} reads process locale state, so a Qt-free "
        f"rendering would vary with the machine it runs on (BACK-04): "
        + "; ".join(offenders))


# ---- Behavioural corroboration ---------------------------------------------

def test_behavioural_corroboration_under_a_comma_and_12_hour_combination():
    """Corroboration, not proof — the structural gate above is the proof,
    because it runs everywhere this suite runs, including the RPM `%check`
    on a container with no non-English langpack installed and no
    `BuildRequires` added for one. This test only runs where the local
    machine happens to carry both a comma-decimal locale (`de_DE.UTF-8`,
    for `LC_NUMERIC`) and a 12-hour locale (`en_US.UTF-8`, for `LC_TIME` —
    no single locale defines both properties, per RESEARCH.md), and skips
    honestly, rather than failing, everywhere else.
    """
    saved_numeric = locale.setlocale(locale.LC_NUMERIC)
    saved_time = locale.setlocale(locale.LC_TIME)
    both_available = True
    try:
        locale.setlocale(locale.LC_NUMERIC, "de_DE.UTF-8")
        locale.setlocale(locale.LC_TIME, "en_US.UTF-8")
    except locale.Error:
        both_available = False
    try:
        if not both_available:
            pytest.skip(
                "de_DE.UTF-8 and/or en_US.UTF-8 not installed on this "
                "machine -- the structural gate above is what proves this "
                "property, not this test; skipping honestly rather than "
                "adding a BuildRequires for a langpack the RPM buildroot "
                "would still not carry")
        formatter = PlainLocaleFormatter()
        when = datetime(2026, 8, 21, 14, 32)
        assert formatter.number(1234.5, NumberSpec(decimals=1, grouping=True)) == "1,234.5"
        assert formatter.time(when, TimeStyle.HOUR_AND_MINUTE) == "14:32"
    finally:
        locale.setlocale(locale.LC_NUMERIC, saved_numeric)
        locale.setlocale(locale.LC_TIME, saved_time)
