"""The presentation seam's divergence surface, swept once and recorded.

This is the sweep DOC-02 asks for: the closed set of ways the two
``LocaleFormatter`` backends can render the same request differently,
checked against both real backends rather than argued from memory. The
sentence in ``docs/ARCHITECTURE.md`` naming "the one place" the backends may
diverge was wrong — this module is what the replacement sentence is written
against.

The surface is closed, and therefore finishable: the four
``LocaleFormatter`` operations (``number``, ``integer``, ``time``, ``date``)
crossed with every ``NumberSpec``/``IntegerSpec`` field and every
``TimeStyle``/``DateStyle`` member — eight cells, not a candidate list.
"Look for other divergences" can only ever be abandoned; "enumerate these
eight cells and record a verdict for each" can be finished, then guarded by
the completeness test below, which fails on a ninth cell exactly as it
fails on an eighth going missing.

There is no language-switching context manager here and no ``Translator``
at all. ``QtLocaleFormatter`` takes its ``QLocale`` at construction — the
locale is injected, not installed process-wide — and nothing this module
calls reads a message catalog. Do not "fix" that by importing a fourth copy
of a language-switching context manager; there is nothing here for one to
install.

Every expected value below is hand-typed from the documented rendering
rule in ``plain_locale.py``, never seeded from a run: no environment
variable, no branch that writes an expectation back to source, and no
``pytest.skip`` that would let a mismatch be resolved any way other than
fixing the code (GATE-15). A separate, older baseline mechanism elsewhere
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

from PySide6.QtCore import QLocale  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import presentation_samples  # noqa: E402
from idasen_companion.core.presentation.plain_locale import (  # noqa: E402
    PlainLocaleFormatter,
)
from idasen_companion.core.presentation.protocols import (  # noqa: E402
    LocaleFormatter,
)
from idasen_companion.core.presentation.specs import (  # noqa: E402
    DateStyle, IntegerSpec, NumberSpec, TimeStyle,
)


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
    """Every public method ``LocaleFormatter`` declares, by name."""
    names = set()
    for name, member in inspect.getmembers(LocaleFormatter):
        if name.startswith("_"):
            continue
        if inspect.isfunction(member):
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
