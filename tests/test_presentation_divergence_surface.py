"""The presentation seam's divergence surface, swept once and recorded.

This is the sweep DOC-02 asks for: the closed set of ways the two
``LocaleFormatter`` backends can render the same request differently,
checked against both real backends rather than argued from memory.
``docs/ARCHITECTURE.md`` used to name four formatters as "the one place"
the backends may diverge. That was wrong, and its replacement — the
sanctioned-divergence paragraph, stated as a category — is written against
this module's recorded verdicts.

The surface is closed, and therefore finishable: the four
``LocaleFormatter`` operations (``number``, ``integer``, ``time``, ``date``)
crossed with every ``NumberSpec``/``IntegerSpec`` field and every
``TimeStyle``/``DateStyle`` member — eight cells, not a candidate list.
"Look for other divergences" can only ever be abandoned; "enumerate these
eight cells and record a verdict for each" can be finished, then guarded by
the completeness test below, which fails on a ninth cell exactly as it
fails on an eighth going missing.

One cell per knob, though, not one per combination of knobs. Each knob's
divergence is independent of the others in both backends today, and no
shipped caller sets two at once — an integer asked for both a minimum
width and grouping renders ``0012,345`` here against ``0012.345`` through
Qt in Spanish, both malformed, and no cell isolates that interaction. A
knob that begins interacting with another is not something the completeness
test below can see.

This module installs no language and reaches no ``Translator`` at all.
``QtLocaleFormatter`` takes its ``QLocale`` at construction — the locale is
injected, not installed process-wide — and nothing this module calls reads a
message catalog. It borrows only the shipped-language list and the
code-to-``QLocale`` mapping from ``tests/language_context.py``; do not "fix"
the absence of that module's context manager by wrapping these calls in it,
because there is nothing here for it to install.

Every expected value below is hand-typed from the documented rendering
rule in ``plain_locale.py``, never seeded from a run: no environment
variable that selects or rewrites an expectation, no branch that writes one
back to source, and no ``pytest.skip`` that would let a mismatch be resolved
any way other than fixing the code (GATE-15). The offscreen-platform
assignment and the PySide6 ``importorskip`` below are the suite's standard
GUI-test preamble, and neither can change what is expected here. A separate,
older baseline mechanism elsewhere
in this test suite keeps its own regeneration discipline entirely apart
from this module, which reads none of it and writes none of it.

A "diverges" verdict below means at least one shipped language disagrees
with the Qt-free anchor, not that every language does — ``time`` agrees in
Spanish and disagrees in English, and the record would be wrong if it
claimed otherwise.
"""

from __future__ import annotations

import dataclasses
import inspect
import os
from typing import NamedTuple

import pytest

pytest.importorskip("PySide6")

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication  # noqa: E402

import presentation_samples  # noqa: E402
from language_context import SHIPPED_LANGUAGES, qt_locale_for  # noqa: E402
from idasen_companion.core.presentation.plain_locale import (  # noqa: E402
    PlainLocaleFormatter,
)
from idasen_companion.core.presentation.protocols import (  # noqa: E402
    LocaleFormatter,
)
from idasen_companion.core.presentation.specs import (  # noqa: E402
    DateStyle, IntegerSpec, NumberSpec, TimeStyle,
)
from idasen_companion.gui.locale_backend import QtLocaleFormatter  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class SweepCell(NamedTuple):
    """One (operation, knob) cell of the seam's closed surface.

    ``knob`` is the spec field name or the style member name the cell
    isolates. ``qt_free`` is the single column this cell needs: it is
    language-independent by BACK-04, since ``PlainLocaleFormatter`` reads
    no locale, so one hand-typed value covers every shipped language and
    is the anchor the divergence verdict is measured against.
    """

    operation: str
    knob: str
    args: tuple[object, ...]
    qt_free: str
    diverges: bool
    note: str


# No value below was derived by running the code and copying its output —
# each qt_free column is typed from plain_locale.py's documented rendering
# rule, and each diverges verdict is typed from locale_backend.py's
# documented rendering rule, before either backend was ever called with
# these arguments.
SEAM_SWEEP: tuple[SweepCell, ...] = (
    SweepCell(
        "number", "decimals", (110.5, NumberSpec(decimals=1)),
        "110.5", True,
        "Spanish renders a decimal comma; this is the divergence that "
        "reaches every height the app shows.",
    ),
    SweepCell(
        "number", "trim_trailing_zeroes",
        (110.0, NumberSpec(decimals=1, trim_trailing_zeroes=True)),
        "110", False,
        "Both backends express the trim as a reduced decimal count handed "
        "to their own conversion, so a whole value renders identically — "
        "the cell D-03 did not name, recorded here as the completeness "
        "DOC-02 asks for.",
    ),
    SweepCell(
        "number", "grouping",
        (12345.5, NumberSpec(decimals=1, grouping=True)),
        "12,345.5", True,
        "At this magnitude Spanish differs in both the group separator "
        "and the decimal point. Five integer digits, not four: Qt's "
        "Spanish CLDR data inserts no group separator below five.",
    ),
    SweepCell(
        "integer", "min_digits",
        (5, IntegerSpec(min_digits=2)),
        "05", False,
        "Both backends pad through Python's rjust on the already-rendered "
        "string, deliberately — a mechanism choice, not a policy one.",
    ),
    SweepCell(
        "integer", "grouping",
        (12345, IntegerSpec(grouping=True)),
        "12,345", True,
        "The cleanest isolation of the separator divergence — no decimal "
        "point is involved at all.",
    ),
    SweepCell(
        "time", "HOUR_AND_MINUTE",
        (presentation_samples.AFTERNOON, TimeStyle.HOUR_AND_MINUTE),
        "14:32", True,
        "Qt's English short time is 12-hour; Spanish agrees with the "
        "Qt-free 24-hour rendering, which is why the verdict is at least "
        "one language, not every language.",
    ),
    SweepCell(
        "date", "WEEKDAY_AND_DAY",
        (presentation_samples.AFTERNOON, DateStyle.WEEKDAY_AND_DAY),
        "2026-08-17", True,
        "Qt renders a localized weekday abbreviation; the Qt-free "
        "backend renders one ISO 8601 date in every language.",
    ),
    SweepCell(
        "date", "WEEKDAY_DAY_MONTH_YEAR",
        (presentation_samples.AFTERNOON, DateStyle.WEEKDAY_DAY_MONTH_YEAR),
        "2026-08-17", True,
        "Qt renders a localized weekday and month name; the Qt-free "
        "backend renders the same ISO 8601 date as the short form above.",
    ),
)


def _locale_formatter_operations() -> set[str]:
    """Every public member ``LocaleFormatter`` declares, by name.

    A ``property`` counts, and that is the point rather than a nicety.
    BACK-02's whole prohibition is on a locale-*database field* —
    ``decimal_separator``, ``month_names``, ``am_text``,
    ``first_day_of_week`` — and the natural Python spelling of a field on a
    protocol is a property, not a method. Admitting only functions here
    would let the completeness test below stay green through the addition
    of the one member shape the seam is written to keep out. A property
    landing here has no knob mapping, so it fails loudly instead. The
    sibling helper in ``tests/test_golden_presentation_contract.py`` already
    accepts both.
    """
    names = set()
    for name, member in inspect.getmembers(LocaleFormatter):
        if name.startswith("_"):
            continue
        if inspect.isfunction(member) or isinstance(member, property):
            names.add(name)
    return names


def _knobs_by_operation() -> dict[str, set[str]]:
    """The seam's own surface, derived mechanically from the spec module.

    The operation-to-source mapping below is written by hand — that is
    deliberate, and the completeness test is what catches a fifth
    operation that has no mapping here at all.
    """
    return {
        "number": {field.name for field in dataclasses.fields(NumberSpec)},
        "integer": {field.name for field in dataclasses.fields(IntegerSpec)},
        "time": {member.name for member in TimeStyle},
        "date": {member.name for member in DateStyle},
    }


def test_the_sweep_records_a_verdict_for_every_cell_of_the_seam():
    """A fifth ``LocaleFormatter`` operation, a new ``NumberSpec``/
    ``IntegerSpec`` field, or a new ``DateStyle`` member added later with
    no recorded verdict fails here — in both directions, so neither a
    missing cell nor a stale one can accumulate silently.
    """
    knobs_by_operation = _knobs_by_operation()
    expected_operations = _locale_formatter_operations()
    recorded_operations = set(knobs_by_operation)
    assert recorded_operations == expected_operations, (
        f"operations with no recorded knob mapping: "
        f"{sorted(expected_operations - recorded_operations)}; "
        f"recorded operations no longer on LocaleFormatter: "
        f"{sorted(recorded_operations - expected_operations)}")

    expected_cells = {
        (operation, knob)
        for operation, knobs in knobs_by_operation.items()
        for knob in knobs
    }
    recorded_cells = {(cell.operation, cell.knob) for cell in SEAM_SWEEP}
    assert expected_cells == recorded_cells, (
        f"cells with no recorded verdict: "
        f"{sorted(expected_cells - recorded_cells)}; "
        f"recorded cells no longer part of the seam: "
        f"{sorted(recorded_cells - expected_cells)}")

    unexplained = sorted(
        f"{cell.operation}/{cell.knob}" for cell in SEAM_SWEEP if not cell.note)
    assert not unexplained, f"cells with no recorded reason: {unexplained}"


# ----------------------------------------------------------------------
# Every recorded verdict, checked against both real backends.
# ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "cell", SEAM_SWEEP, ids=lambda c: f"{c.operation}-{c.knob}")
def test_every_recorded_cell_renders_its_written_qt_free_value(cell):
    """This is BACK-04 as a check: the Qt-free backend reads no locale, so
    one hand-typed column covers every language, and it is the anchor the
    divergence verdict below is measured against, rather than the two
    backends being compared only to each other.
    """
    rendered = getattr(PlainLocaleFormatter(), cell.operation)(*cell.args)
    assert rendered == cell.qt_free, (
        f"{cell.operation}/{cell.knob}: the Qt-free backend rendered "
        f"{rendered!r}, the recorded anchor is {cell.qt_free!r}")


@pytest.mark.parametrize(
    "cell", SEAM_SWEEP, ids=lambda c: f"{c.operation}-{c.knob}")
def test_every_recorded_cell_diverges_exactly_where_the_sweep_says(qapp, cell):
    """A verdict of "diverges" means at least one shipped language
    disagrees with the Qt-free anchor, not that all of them do — and a
    newly shipped language that flips a verdict is meant to turn this red,
    because that is a human's cue to look.
    """
    differing = []
    for language in SHIPPED_LANGUAGES:
        rendered = getattr(
            QtLocaleFormatter(qt_locale_for(language)),
            cell.operation)(*cell.args)
        if rendered != cell.qt_free:
            differing.append((language, rendered))
    assert bool(differing) == cell.diverges, (
        f"{cell.operation}/{cell.knob}: recorded diverges={cell.diverges}, "
        f"but the languages differing from the Qt-free anchor "
        f"{cell.qt_free!r} were "
        f"{[(lang, repr(text)) for lang, text in differing]}")
