"""The vocabulary before-picture: ``gui/util.py`` rendered today, whole.

Phases 13-15 move every formatter this file exercises out of ``gui/util.py``
and into the shared presentation layer. Nothing here is a test of *behavior*
in the usual sense — it is a recording, taken before any of those moves
land, of exactly what each formatter renders today in both shipped
languages. Its only job is to fail the moment a rendered string changes,
which a baseline taken *after* the move could never do: a "before" recorded
after the fact agrees with itself no matter what changed, and proves
nothing.

Every case is a direct call into ``gui.util`` with a fixed, representative
input — no window is built, no widget renders anything. Regeneration is
deliberate and explicit: set the environment variable named below and the
comparison is skipped in favor of writing the file, so the two behaviors
never happen in the same run and a failing comparison can never be silently
made to pass. The variable must stay unset in CI. Regenerating a golden is a
reviewed, reasoned act — its own commit should say why the recorded value
changed, since after Phase 12 that reason should always be a deliberate
formatter move, not an accident.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QLocale  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from language_context import installed_language as _language  # noqa: E402
from idasen_companion.core.presentation import register  # noqa: E402
from idasen_companion.core.presentation.formatter import (  # noqa: E402
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.specs import TimeStyle  # noqa: E402
from idasen_companion.core.presentation.gettext_translator import (  # noqa: E402
    GettextTranslator,
)
from idasen_companion.core.units import HeightUnit  # noqa: E402
from idasen_companion.gui import util  # noqa: E402
from idasen_companion.gui.locale_backend import QtLocaleFormatter  # noqa: E402

#: Set to regenerate the committed goldens instead of comparing against them.
#: Unset (the default, and the only state CI ever runs in), a mismatch fails
#: with a readable diff; set, the file is rewritten and the comparison is
#: skipped, so a rewrite and a compare can never both happen in one run.
REGENERATE_ENV_VAR = "IDASEN_COMPANION_REGENERATE_VOCABULARY_GOLDENS"

GOLDEN_DIR = Path(__file__).parent / "goldens"

#: A stand-in for the theme tokens ``connection_state`` reads a color off of.
#: Only its text outputs are recorded here, so the color values themselves
#: are never inspected.
_THEME = SimpleNamespace(success="success", error="error", muted="muted")


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


# ----------------------------------------------------------------------
# Case groups. Each returns a flat {case_name: rendered_value} mapping for
# whichever language/locale is currently installed via _language() above.
# ----------------------------------------------------------------------


def _connection_cases() -> dict[str, str]:
    cases: dict[str, str] = {}
    for name, connected, available, persistent in (
        ("connected", True, True, False),
        ("disconnected", False, False, False),
        ("on_demand", False, True, False),
    ):
        _color, footer, chip = util.connection_state(
            _THEME, connected, available, persistent)
        cases[f"footer_{name}"] = footer
        cases[f"chip_{name}"] = chip
    return cases


_HEIGHT_METERS = 1.105
_HEIGHT_METERS_WHOLE = 1.10


def _height_formatter(unit: HeightUnit) -> Formatter:
    # Same pair _duration_formatter() builds below (D-09), just parameterized
    # on the unit under test rather than fixed at centimetres: each unit gets
    # its own Formatter, per D-07, rather than a shared instance mutated
    # through a process-global setter.
    context = PresentationContext(
        locale=QtLocaleFormatter(QLocale()), translator=GettextTranslator(),
        unit=unit,
        time_style=TimeStyle.HOUR_AND_MINUTE_24)
    return Formatter(context)


def _height_cases() -> dict[str, str]:
    cases: dict[str, str] = {}
    for unit in (HeightUnit.CENTIMETRES, HeightUnit.INCHES):
        fmt = _height_formatter(unit)
        cases[f"value_{unit}"] = fmt.height_value(_HEIGHT_METERS)
        cases[f"value_trim_{unit}"] = fmt.height_value(
            _HEIGHT_METERS_WHOLE, trim=True)
        cases[f"message_{unit}"] = fmt.height(_HEIGHT_METERS)
        cases[f"suffix_{unit}"] = util.suffix_height(unit)
        cases[f"preset_tick_{unit}"] = fmt.preset_tick(
            "Sit", _HEIGHT_METERS, trim=True)
    return cases


def _spin_suffix_cases() -> dict[str, str]:
    # suffix_height is covered per-unit in _height_cases; these two are the
    # remaining spin-box suffix exception CLAUDE.md documents.
    return {
        "minutes": util.suffix_minutes(),
        "seconds": util.suffix_seconds(),
    }


_DURATION_CASES = (
    ("sub_minute", 45),
    ("minutes_only", 240),
    ("hour_exact", 3600),
    ("hours_minutes", 3900),
)


def _duration_formatter() -> Formatter:
    # The same pair AppContext.fmt builds (D-09): QLocale() reads the
    # currently-installed default, and GettextTranslator reads whatever
    # _language() above just bound.
    context = PresentationContext(
        locale=QtLocaleFormatter(QLocale()), translator=GettextTranslator(),
        unit=HeightUnit.CENTIMETRES,
        time_style=TimeStyle.HOUR_AND_MINUTE_24)
    return Formatter(context)


def _duration_cases() -> dict[str, str]:
    fmt = _duration_formatter()
    return {name: fmt.duration(seconds)
            for name, seconds in _DURATION_CASES}


_COUNTDOWN_CASES = (
    ("typical", 125),
    ("zero", 0),
    ("large", 3661),
)


def _countdown_cases() -> dict[str, str]:
    return {name: util.fmt_countdown(seconds)
            for name, seconds in _COUNTDOWN_CASES}


_CLOCK_CASES = (
    ("afternoon", datetime(2026, 8, 17, 14, 32)),
    ("morning", datetime(2026, 8, 17, 9, 5)),
    ("midnight", datetime(2026, 8, 17, 0, 0)),
)


def _clock_formatter() -> Formatter:
    """The window's pairing at the clock style every recording here has
    always used. Named separately from :func:`_height_formatter` so the two
    axes this module records -- the unit and the clock -- move one at a time
    and a regeneration diff says which."""
    return Formatter(PresentationContext(
        locale=QtLocaleFormatter(QLocale()), translator=GettextTranslator(),
        unit=HeightUnit.CENTIMETRES,
        time_style=TimeStyle.HOUR_AND_MINUTE))


def _clock_cases() -> dict[str, str]:
    fmt = _clock_formatter()
    return {name: util.fmt_clock(fmt, when) for name, when in _CLOCK_CASES}


_DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_DAY_LIST_CASES = (
    ("empty", []),
    ("single", ["mon"]),
    ("run_three", ["mon", "tue", "wed"]),
    ("run_five", ["mon", "tue", "wed", "thu", "fri"]),
    ("nonconsecutive", ["mon", "wed", "fri"]),
)

_DAY_WHEN = datetime(2026, 8, 17, 14, 32)


def _day_cases() -> dict[str, str]:
    cases = {f"label_{key}": util.day_label(key) for key in _DAY_KEYS}
    cases.update({f"list_{name}": util.fmt_days(days)
                  for name, days in _DAY_LIST_CASES})
    cases["and_clock"] = util.fmt_day_and_clock(
        _clock_formatter(), _DAY_WHEN)
    cases["bare_label"] = util.fmt_day_label(_DAY_WHEN)
    cases["heading"] = util.fmt_day_heading(_DAY_WHEN)
    return cases


def _status_cases() -> dict[str, str]:
    # The key lists come from the register, which is where the tables live
    # after Phase 14; every case still renders through `gui.util`, so the
    # recorded values are unchanged by the move.
    cases = {f"label_{key}": util.status_label(key)
             for key in register.STATUS_LABELS}
    cases["label_unknown"] = util.status_label("unknown-status")
    cases.update({f"head_{key}": util.status_head(key)
                  for key in register.STATUS_HEADS})
    cases["head_unknown"] = util.status_head("unknown-status")
    return cases


def _position_cases() -> dict[str, str]:
    return {
        "sitting": util.position_label("sitting"),
        "standing": util.position_label("standing"),
        "empty": util.position_label(""),
        "unknown": util.position_label("custom-spot"),
    }


def _trigger_cases() -> dict[str, str]:
    cases = {key: util.trigger_label(key) for key in register.TRIGGER_LABELS}
    cases["unknown"] = util.trigger_label("unknown-trigger")
    return cases


def _preset_cases() -> dict[str, str]:
    cases = {key: util.preset_label(key) for key in register.PRESET_LABELS}
    cases["custom"] = util.preset_label("my-custom-preset")
    return cases


def _daemon_error_cases() -> dict[str, str]:
    cases = {key: util.daemon_error_message(key)
             for key in register.DAEMON_ERROR_MESSAGES}
    cases["generic_fallback"] = util.daemon_error_message("", "")
    cases["unknown_with_detail"] = util.daemon_error_message(
        "org.freedesktop.DBus.Error.NoReply", "Message recipient disconnected")
    return cases


#: A fixed instant (not ``time.time()``), so the rendered clock string is
#: deterministic under the suite's pinned timezone rather than reflecting
#: whenever the harness happened to run.
_SNOOZE_UNTIL = 1_800_000_000.0


def _cycle_cases() -> dict[str, str]:
    return {
        "snooze_later": util.snooze_line(_clock_formatter(), 0),
        "snooze_specific": util.snooze_line(
            _clock_formatter(), _SNOOZE_UNTIL),
        "due_now": util.due_now_label(),
        "position_or_custom_known": util.position_or_custom("standing"),
        "position_or_custom_custom": util.position_or_custom(""),
    }


#: Every group `<interfaces>` names, and the minimum size that keeps it
#: representative. A case silently dropped in a later edit shrinks a count
#: here and fails test_group_coverage, instead of the picture quietly
#: shrinking unnoticed.
_GROUPS = {
    "connection": (_connection_cases, 6),
    "height": (_height_cases, 10),
    "spin_suffix": (_spin_suffix_cases, 2),
    "duration": (_duration_cases, 4),
    "countdown": (_countdown_cases, 3),
    "clock": (_clock_cases, 3),
    "day": (_day_cases, 15),
    "status": (_status_cases, 23),
    "position": (_position_cases, 4),
    "trigger": (_trigger_cases, 5),
    "preset": (_preset_cases, 3),
    "daemon_error": (_daemon_error_cases, 9),
    "cycle": (_cycle_cases, 5),
}


def _render_groups() -> dict[str, dict[str, str]]:
    """Every group's cases, rendered under whatever language is installed."""
    return {name: builder() for name, (builder, _minimum) in _GROUPS.items()}


def _flatten(groups: dict[str, dict[str, str]]) -> dict[str, str]:
    flat: dict[str, str] = {}
    for group_name, cases in groups.items():
        for case_name, value in cases.items():
            flat[f"{group_name}.{case_name}"] = value
    return flat


def _render_vocabulary(language: str) -> dict[str, dict[str, str]]:
    with _language(language):
        return _render_groups()


# ----------------------------------------------------------------------
# Golden I/O
# ----------------------------------------------------------------------


def _golden_path(language: str) -> Path:
    return GOLDEN_DIR / f"vocabulary_{language}.json"


def _write_golden(language: str, flat: dict[str, str]) -> None:
    path = _golden_path(language)
    path.write_text(
        json.dumps(flat, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


def _load_golden(language: str) -> dict[str, str]:
    path = _golden_path(language)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        pytest.fail(
            f"{path} does not exist. Regenerate it deliberately with "
            f"{REGENERATE_ENV_VAR}=1 .venv/bin/python -m pytest -q "
            f"tests/test_baseline_vocabulary.py, then commit the file with "
            f"a reason.", pytrace=False)
    return json.loads(text)


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


@pytest.mark.parametrize("language", ["en", "es"])
def test_group_coverage(qapp, language):
    """Every group `<interfaces>` names is still represented, at its floor.

    Reads the per-group minimums off ``_GROUPS`` itself, so a case quietly
    dropped from a builder function shrinks the picture and fails here
    rather than shrinking silently.
    """
    groups = _render_vocabulary(language)
    for name, (_builder, minimum) in _GROUPS.items():
        assert len(groups[name]) >= minimum, (
            f"{language}: group {name!r} has {len(groups[name])} cases, "
            f"expected at least {minimum}")
    total = sum(len(cases) for cases in groups.values())
    assert total >= 80, f"{language}: only {total} cases rendered in total"


def test_languages_differ(qapp):
    """A Spanish golden that equals the English one means the catalog, or
    the locale, never actually installed — this would otherwise hide behind
    a comparison that technically passes."""
    en_groups = _render_vocabulary("en")
    es_groups = _render_vocabulary("es")
    assert es_groups["status"] != en_groups["status"], (
        "Spanish status words equal the English ones")
    assert es_groups["height"] != en_groups["height"], (
        "Spanish height rendering equals the English one")


@pytest.mark.parametrize("language", ["en", "es"])
def test_matches_golden(qapp, language):
    flat = _flatten(_render_vocabulary(language))

    if os.environ.get(REGENERATE_ENV_VAR):
        _write_golden(language, flat)
        pytest.skip(f"regenerated {_golden_path(language)}")

    golden = _load_golden(language)
    differing = {
        key: (golden.get(key), flat.get(key))
        for key in golden.keys() | flat.keys()
        if golden.get(key) != flat.get(key)
    }
    assert not differing, (
        f"{language}: {len(differing)} rendered value(s) differ from "
        f"{_golden_path(language).name}:\n" +
        "\n".join(f"  {key}: golden={golden_value!r} "
                  f"actual={actual_value!r}"
                  for key, (golden_value, actual_value)
                  in sorted(differing.items())))
