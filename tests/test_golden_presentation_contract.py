"""GATE-08's written contract: the four moment renderers' divergence, typed
by hand from frozen inputs, plus a backend-equality pinning for every other
shared formatter.

**Why a date/time golden does not change minute to minute.** The obvious
worry about pinning a date or a clock rendering is that the value under
test moves with the wall clock, so any fixed expectation goes stale on its
own. That worry does not apply here: every input below is a frozen literal
``datetime``, and each of the four helpers under test takes its moment as a
``when`` argument rather than reading the system clock itself. That is the
same property that let these four move into the shared presentation layer
at all in Phase 15's second plan — a formatter that read the clock could be
neither pinned nor shared — so pinning them here costs nothing new.

**Why this module has no regeneration path.** GATE-08 exists against a
specific failure: a golden test seeded from whatever the code currently
returns pins a bug as a contract, and a rewrite-on-demand command is what
lets that seeding happen invisibly, again, the next time someone is in a
hurry. So there is no environment variable here, no branch that writes an
expectation back to source, and no ``pytest.skip`` that would let a mismatch
be resolved any way other than fixing the code. The files under
``tests/goldens/`` are a different, older artifact — Phase 12's
before-picture, serving a different purpose (BACK-03) — and keep their own
regeneration discipline entirely untouched by this module.

**The two halves.** For the four moment renderers, a person typed out three
columns of expected text — the Qt backend bound to English, the Qt backend
bound to Spanish, and the Qt-free backend — because these four are the one
place PRES-01 sanctions the two backends disagreeing in more than
formatting mechanics. For every other shared formatter, the pinning is an
**equality assertion** between the same two backends (Qt bound to English,
Qt-free) plus one hand-typed anchor per distinct method: an equality
assertion records a *relationship*, not a captured value, so it cannot be
seeded with a bug the way a value copied from a single run can be — and the
anchor is what stops both backends being broken identically from passing
unnoticed.
"""

from __future__ import annotations

import inspect
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, NamedTuple

import pytest

pytest.importorskip("PySide6")

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QCoreApplication, QLocale, QTranslator  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import presentation_samples  # noqa: E402
from idasen_companion.core import i18n as core_i18n  # noqa: E402
from idasen_companion.core.presentation.formatter import (  # noqa: E402
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.gettext_translator import (  # noqa: E402
    GettextTranslator,
)
from idasen_companion.core.units import HeightUnit  # noqa: E402
from idasen_companion.gui import i18n  # noqa: E402
from idasen_companion.gui.locale_backend import QtLocaleFormatter  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@contextmanager
def _language(language: str) -> Iterator[None]:
    """Install exactly what a real run installs for ``language``, then undo
    it. Copied from ``tests/test_baseline_vocabulary.py``'s own fixture of
    the same name — see that module for the full reasoning; this is the
    established en/es switching mechanism and this module reuses its shape
    rather than inventing a second one.
    """
    app = QApplication.instance()
    previous_locale = QLocale()
    if language == "en":
        QLocale.setDefault(QLocale("en_US"))
        installed: list[QTranslator] = []
        core_i18n.set_language("en")
    else:
        installed = i18n.apply_language(app, language)
    try:
        yield
    finally:
        for translator in installed:
            QCoreApplication.removeTranslator(translator)
        QLocale.setDefault(previous_locale)
        core_i18n.set_language(core_i18n.SYSTEM)


def _qt_formatter() -> Formatter:
    return Formatter(PresentationContext(
        locale=QtLocaleFormatter(QLocale()), translator=GettextTranslator(),
        unit=HeightUnit.CENTIMETRES))


# ----------------------------------------------------------------------
# Half one: the four moment renderers, hand-typed from the spec.
# ----------------------------------------------------------------------

#: The narrow no-break space (U+202F) Qt's English short-time format places
#: before "AM"/"PM" — written as the six-character Python escape sequence
#: below, never pasted, because a plain space there looks identical on
#: screen and fails the assertion.
_NNBSP = "\u202f"

_AFTERNOON = datetime(2026, 8, 17, 14, 32)
_MORNING = datetime(2026, 8, 17, 9, 5)


class GoldenRow(NamedTuple):
    """One (helper, moment) pair with its three hand-typed columns."""

    case: str
    helper: str
    when: datetime
    qt_en: str
    qt_es: str
    qt_free: str


#: Typed from the spec, cross-checked against the committed
#: ``tests/goldens/vocabulary_{en,es}`` baselines after writing (both
#: agreed with every value below). No row here is derived by running the
#: code and copying its output — that is the exact seeding GATE-08 exists to
#: prevent.
GOLDEN_DATE_TIME_CONTRACT: tuple[GoldenRow, ...] = (
    GoldenRow(
        "day_short", "day_short", _AFTERNOON,
        qt_en="Mon 17",
        qt_es="lun 17",
        qt_free="2026-08-17",
    ),
    GoldenRow(
        "day_heading", "day_heading", _AFTERNOON,
        qt_en="Mon 17 Aug 2026",
        qt_es="lun 17 ago 2026",
        qt_free="2026-08-17",
    ),
    GoldenRow(
        "clock_afternoon", "clock", _AFTERNOON,
        qt_en=f"2:32{_NNBSP}PM",
        qt_es="14:32",
        qt_free="14:32",
    ),
    GoldenRow(
        "clock_morning", "clock", _MORNING,
        qt_en=f"9:05{_NNBSP}AM",
        qt_es="9:05",
        qt_free="09:05",
    ),
    GoldenRow(
        "day_and_clock", "day_and_clock", _AFTERNOON,
        qt_en=f"Mon 17 2:32{_NNBSP}PM",
        qt_es="lun 17 14:32",
        qt_free="2026-08-17 14:32",
    ),
)


@pytest.mark.parametrize("row", GOLDEN_DATE_TIME_CONTRACT, ids=lambda r: r.case)
def test_the_four_moment_renderers_match_their_written_contract(qapp, row):
    """Each row's three columns are asserted against a freshly built
    ``Formatter`` for that column's backend — never against each other,
    so a coincidental agreement between two backends cannot mask a wrong
    value in the third.
    """
    with _language("en"):
        assert getattr(_qt_formatter(), row.helper)(row.when) == row.qt_en
    with _language("es"):
        assert getattr(_qt_formatter(), row.helper)(row.when) == row.qt_es
    assert (getattr(presentation_samples.build_plain_formatter(), row.helper)
            (row.when) == row.qt_free)


@pytest.mark.parametrize("row", GOLDEN_DATE_TIME_CONTRACT, ids=lambda r: r.case)
def test_the_four_moment_renderers_diverge_from_the_qt_free_column(row):
    """The divergence itself is written down, not left to be discovered
    later: at least one Qt column must disagree with the Qt-free one for
    every row in the contract, which is the whole reason these four are
    PRES-01's sanctioned exception rather than pinned by equality like
    everything else in this module.
    """
    assert row.qt_en != row.qt_free or row.qt_es != row.qt_free, (
        f"{row.case}: both Qt columns match the Qt-free column — this row "
        f"belongs in the equality half below, not in the hand-typed "
        f"contract")


# ----------------------------------------------------------------------
# Half two: every other shared formatter, by backend equality plus anchor.
# ----------------------------------------------------------------------

_DATE_TIME_HELPERS = frozenset(row.helper for row in GOLDEN_DATE_TIME_CONTRACT)

#: The equality-pinned rows from the shared sample table: everything that is
#: not one of the four moment renderers above.
_EQUALITY_SAMPLES = tuple(
    row for row in presentation_samples.SAMPLES
    if row.method not in _DATE_TIME_HELPERS)

#: One hand-typed anchor per distinct method among the equality-pinned
#: samples, keyed by *case* rather than by method (``connection_phrases``
#: returns a tuple, not a string, and only one of its three branches needs
#: an anchor), so the equality assertions below cannot pass because both
#: backends independently broke the same way. Typed from the spec, then
#: cross-checked against a live run of both backends.
ANCHORS: dict[str, object] = {
    "height_value": "110.5",
    "height": "110.5 cm",
    "preset_tick": "Sit · 110.5",
    "connection_phrases_connected": ("Desk: connected", "Connected"),
    "status_label": "Automation active",
    "status_head": "Active",
    "position_label": "Sitting",
    "preset_label": "Sit",
    "trigger_label": "automation",
    "pre_move_summary": "Standing up in about 1 hour 5 minutes",
    "pre_move_body": "The desk will move once you're due.",
    "snooze_action_label": "Snooze 15 min",
    "skip_action_label": "Skip this one",
    "automation_paused_summary": "Automation paused",
    "automation_paused_body": (
        "The desk was moved to an unrecognized position. It will resume "
        "once the desk is back at sit or stand."),
    "move_failed_summary": "The desk didn't stand up",
    "move_failed_body": (
        "It didn't respond (offline). The next change is a whole interval "
        "away."),
    "try_now_action_label": "Try now",
    "later_label": "later",
    "snooze_line": "Snoozed until 14:32",
    "due_now_label": "Due now",
    "minutes_label": "5 minutes",
    "position_or_custom": "Standing",
    "countdown": "2:05",
    "day_label": "Mon",
    "fmt_days": "Mon–Wed",
    "duration_verbose": "1 hour 5 minutes",
    "duration_hm": "1h 05m",
    "duration": "45s",
}


def _rendered(formatter: Formatter, row: presentation_samples.Sample):
    return getattr(formatter, row.method)(*row.args, **row.kwargs)


@pytest.mark.parametrize(
    "row", _EQUALITY_SAMPLES, ids=lambda r: r.case)
def test_every_other_formatter_agrees_between_backends(qapp, row):
    """``qt_output == plain_output`` for everything that is not one of the
    four sanctioned exceptions above. An equality assertion records a
    relationship rather than a captured value, so it cannot be seeded with
    a bug the way a value copied from a single run could be.
    """
    with _language("en"):
        qt_output = _rendered(_qt_formatter(), row)
    plain_output = _rendered(presentation_samples.build_plain_formatter(), row)
    assert qt_output == plain_output, (
        f"{row.case}: Qt/en rendered {qt_output!r}, the Qt-free backend "
        f"rendered {plain_output!r} — these two are supposed to agree")
    anchor = ANCHORS.get(row.case)
    if anchor is not None:
        assert qt_output == anchor, (
            f"{row.case}: Qt/en rendered {qt_output!r}, expected the "
            f"hand-typed anchor {anchor!r} — an anchor mismatch means both "
            f"backends could be wrong the same way and the equality check "
            f"above would never catch it")


def test_every_distinct_equality_pinned_method_has_an_anchor():
    """The anchor table is not allowed to quietly stop covering a method:
    every distinct method among the equality-pinned samples needs at least
    one of its cases in :data:`ANCHORS`, so the equality half can never pass
    purely because two backends broke identically.
    """
    anchored_methods = {row.method for row in _EQUALITY_SAMPLES
                         if row.case in ANCHORS}
    equality_methods = {row.method for row in _EQUALITY_SAMPLES}
    missing = equality_methods - anchored_methods
    assert not missing, f"no anchor recorded for: {sorted(missing)}"


# ----------------------------------------------------------------------
# The completeness self-check.
# ----------------------------------------------------------------------


def _public_formatter_members() -> set[str]:
    """Every public ``Formatter`` member — method or property — by name."""
    names = set()
    for name, member in inspect.getmembers(Formatter):
        if name.startswith("_"):
            continue
        if inspect.isfunction(member) or isinstance(member, property):
            names.add(name)
    return names


def test_every_public_formatter_method_has_a_sample_row():
    """A formatter added later with no row in ``presentation_samples.SAMPLES``
    fails here, in both directions — the same "measured, not assumed"
    completeness shape ``tests/test_translation_collisions.py`` uses for its
    own register, so neither a missing row nor a dead one can accumulate
    silently.
    """
    expected = _public_formatter_members() - set(presentation_samples.NOT_FORMATTERS)
    covered = {row.method for row in presentation_samples.SAMPLES}
    assert expected == covered, (
        f"missing sample rows: {sorted(expected - covered)}; "
        f"stale sample rows for methods no longer public: "
        f"{sorted(covered - expected)}")
