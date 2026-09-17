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
hurry. So there is no environment variable here that selects or rewrites an
expectation, no branch that writes one back to source, and no ``pytest.skip``
that would let a mismatch be resolved any way other than fixing the code.
(The offscreen-platform assignment and the PySide6 ``importorskip`` below are
the suite's standard GUI-test preamble, and the one skip further down reports
an absent system locale. None of the three can change what is expected.)
The files under ``tests/goldens/`` are a different, older artifact — Phase 12's
before-picture, serving a different purpose (BACK-03) — and keep their own
regeneration discipline entirely untouched by this module.

**The two halves.** For the small, closed set of cases where a rendering
is deliberately allowed to differ by more than formatting mechanics
(PRES-01's sanctioned exception), a person typed out expected text against
three pairings: the **window** pairing (Qt bound to a shipped language's
gettext catalog), the **daemon** pairing (the Qt-free locale backend bound
to that same gettext catalog — the pairing ``daemon/main.py``'s
``_build_formatter`` really constructs), and the **journal** pairing (the
Qt-free locale backend bound to the pass-through English translator that
keeps ``docs/LOGGING.md``'s greppable-English promise). English proves
nothing for the daemon pairing — its gettext-bound translator and the
journal's pass-through translator return identical strings in English —
so the daemon pairing's row set is exercised in Spanish, not only English.
``BACK-04`` and the pass-through translator make the journal pairing
identical in every language by construction, so it needs no per-language
row and is asserted once against a single shared column. The window and
daemon pairings each carry a row set per shipped language instead, so
adding a language costs one row set — and a shipped language with no row
set fails the build, naming itself, rather than passing silently
uncovered. For every other shared formatter, the pinning is an **equality
assertion** between the window pairing and the journal pairing plus one
hand-typed anchor per distinct method: an equality assertion records a
*relationship*, not a captured value, so it cannot be seeded with a bug
the way a value copied from a single run can be — and the anchor is what
stops both backends being broken identically from passing unnoticed.
"""

from __future__ import annotations

import inspect
import locale
import os
from contextlib import contextmanager
from typing import Iterator, NamedTuple

import pytest

pytest.importorskip("PySide6")

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QLocale  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import presentation_samples  # noqa: E402
from language_context import (  # noqa: E402
    SHIPPED_LANGUAGES, installed_language as _language,
)
from idasen_companion.core.presentation.formatter import (  # noqa: E402
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.gettext_translator import (  # noqa: E402
    GettextTranslator,
)
from idasen_companion.core.presentation.specs import (  # noqa: E402
    NumberSpec, TimeStyle,
)
from idasen_companion.core.units import HeightUnit  # noqa: E402
from idasen_companion.gui.locale_backend import QtLocaleFormatter  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _qt_formatter() -> Formatter:
    return Formatter(PresentationContext(
        locale=QtLocaleFormatter(QLocale()), translator=GettextTranslator(),
        unit=HeightUnit.CENTIMETRES,
        time_style=TimeStyle.HOUR_AND_MINUTE_24))


# ----------------------------------------------------------------------
# Half one: the four moment renderers, hand-typed from the spec.
# ----------------------------------------------------------------------

#: The no-break space (U+00A0) Qt places *inside* Spanish's meridiem
#: designator ("p.\u00a0m.") — written as the six-character Python escape
#: sequence below, never pasted, because a plain space there looks identical
#: on screen and fails the assertion. The separator before the designator is
#: a plain ASCII space in both languages: the explicit format string this
#: backend now asks for inserts one, where Qt's old locale-governed
#: short-time format used a narrow no-break space.
_NNBSP = "\u202f"

#: The two moments and the one height this module's cases render, read from
#: the shared sample table rather than re-declared here. They were literals
#: with a comment saying they mirrored that table, which is a description of
#: an intention and not an enforcement of it: nothing relates a contract
#: case's arguments to the sample row's arguments for the same case, so
#: moving the shared moment left this module still pinning the old one and
#: both modules green. ``tests/test_presentation_divergence_surface.py``
#: already read the shared table by reference; this now does too.
_AFTERNOON = presentation_samples.AFTERNOON
_MORNING = presentation_samples.MORNING
_AFTERNOON_TO_THE_SECOND = presentation_samples.AFTERNOON_TO_THE_SECOND
_HEIGHT_METERS = presentation_samples.HEIGHT_METERS


class ContractCase(NamedTuple):
    """One hand-typed case: a case name, the method to call, the positional
    arguments to call it with, and the single Qt-free rendering every
    language shares — ``BACK-04`` plus the pass-through English translator
    make the Qt-free backend language-independent by construction, so one
    column covers every shipped language rather than one per language.

    ``through`` names what ``helper`` is looked up on: ``"formatter"`` for
    a case reached through a ``Formatter`` method (every case but one), and
    ``"locale"`` for the grouping case, which must reach
    ``formatter.context.locale`` directly because no ``Formatter`` facade
    method exposes a grouping toggle.

    ``time_style`` is the clock the case's formatter is put on before it
    renders, mirroring the shared sample table's own field. A case that
    reaches no clock keeps the default and is unaffected.
    """

    case: str
    helper: str
    args: tuple[object, ...]
    qt_free: str
    through: str = "formatter"
    time_style: TimeStyle = TimeStyle.HOUR_AND_MINUTE_24


class LanguageRendering(NamedTuple):
    """One case's hand-typed rendering in one shipped language: the
    **window** pairing (``QtLocaleFormatter`` + ``GettextTranslator``) and
    the **daemon** pairing (``PlainLocaleFormatter`` + ``GettextTranslator``).
    Both sides carry the same translator, so any difference between them
    here is a genuine value-rendering divergence rather than a translation
    difference.
    """

    case: str
    window: str
    daemon: str


#: Typed from the spec, cross-checked against the committed
#: ``tests/goldens/vocabulary_{en,es}`` baselines after writing (both
#: agreed with every value below). No case here is derived by running the
#: code and copying its output — that is the exact seeding GATE-08 exists to
#: prevent. The last case (D-16) pins ``NumberSpec.grouping``, a divergence
#: the seam permits that no shipped caller reaches — see the module this
#: case's helper reaches, ``core/presentation/specs.py``. Five integer
#: digits are used deliberately: Qt's Spanish CLDR data inserts no group
#: separator below five digits, so a four-digit value would pin only the
#: decimal-point divergence the ``day_and_clock``-adjacent rows already
#: cover, not the separator itself.
CONTRACT_CASES: tuple[ContractCase, ...] = (
    ContractCase("day_short", "day_short", (_AFTERNOON,), qt_free="Mon 17"),
    ContractCase("day_heading", "day_heading", (_AFTERNOON,),
                 qt_free="Mon 17 Aug 2026"),
    ContractCase("clock_afternoon_12", "clock", (_AFTERNOON,),
                 qt_free="2:32 PM",
                 time_style=TimeStyle.HOUR_AND_MINUTE_12),
    ContractCase("clock_morning_12", "clock", (_MORNING,),
                 qt_free="9:05 AM",
                 time_style=TimeStyle.HOUR_AND_MINUTE_12),
    ContractCase("clock_with_seconds_12", "clock_with_seconds",
                 (_AFTERNOON_TO_THE_SECOND,), qt_free="2:32:05 PM",
                 time_style=TimeStyle.HOUR_AND_MINUTE_12),
    ContractCase("day_and_clock_24", "day_and_clock", (_AFTERNOON,),
                 qt_free="Mon 17 14:32"),
    ContractCase("day_and_clock_12", "day_and_clock", (_AFTERNOON,),
                 qt_free="Mon 17 2:32 PM",
                 time_style=TimeStyle.HOUR_AND_MINUTE_12),
    ContractCase("height_value", "height_value", (_HEIGHT_METERS,),
                 qt_free="110.5"),
    ContractCase("height", "height", (_HEIGHT_METERS,), qt_free="110.5 cm"),
    ContractCase("preset_tick", "preset_tick", ("Sit", _HEIGHT_METERS, True),
                 qt_free="Sit · 110.5"),
    ContractCase(
        "number_grouping", "number",
        (12345.5, NumberSpec(decimals=1, grouping=True)),
        qt_free="12,345.5", through="locale"),
)

#: One row set per shipped language (D-12): a language costs one row set,
#: and test_every_shipped_language_has_a_hand_typed_row_set (D-13) fails,
#: naming the language, rather than warning, when one is missing.
#:
#: Four of the rows below reach a gettext pattern: ``height`` (the
#: height-unit suffix), the two ``day_and_clock`` rows (the day-and-clock
#: join) and ``preset_tick`` (the preset-tick separator). For those the
#: daemon column agreeing with the qt_free column is a fact being pinned —
#: all three patterns are deliberately identical in Spanish today
#: (``po/es.po``), and the day a Spanish translation of one of them
#: changes, that daemon column goes red while the journal column
#: (``build_plain_formatter``, reached by no catalog) does not.
#:
#: The remaining rows reach no translator at all — ``day_short``,
#: ``day_heading`` and the two 12-hour clocks render through the locale
#: backend only, ``height_value`` calls its number method only, and
#: ``number_grouping`` bypasses the ``Formatter`` facade entirely. Their
#: daemon column is identical to the qt_free column by construction, no
#: catalog change can ever turn it red, and they are carried for table
#: uniformity rather than for coverage.
GOLDEN_BY_LANGUAGE: dict[str, tuple[LanguageRendering, ...]] = {
    "en": (
        LanguageRendering("day_short", window="Mon 17", daemon="Mon 17"),
        LanguageRendering("day_heading", window="Mon 17 Aug 2026",
                           daemon="Mon 17 Aug 2026"),
        LanguageRendering("clock_afternoon_12", window="2:32 PM",
                           daemon="2:32 PM"),
        LanguageRendering("clock_morning_12", window="9:05 AM",
                           daemon="9:05 AM"),
        LanguageRendering("clock_with_seconds_12", window="2:32:05 PM",
                           daemon="2:32:05 PM"),
        LanguageRendering("day_and_clock_24", window="Mon 17 14:32",
                           daemon="Mon 17 14:32"),
        LanguageRendering("day_and_clock_12", window="Mon 17 2:32 PM",
                           daemon="Mon 17 2:32 PM"),
        LanguageRendering("height_value", window="110.5", daemon="110.5"),
        LanguageRendering("height", window="110.5 cm", daemon="110.5 cm"),
        LanguageRendering("preset_tick", window="Sit · 110.5",
                           daemon="Sit · 110.5"),
        LanguageRendering("number_grouping", window="12,345.5",
                           daemon="12,345.5"),
    ),
    "es": (
        LanguageRendering("day_short", window="lun 17", daemon="lun 17"),
        LanguageRendering("day_heading", window="lun 17 ago 2026",
                           daemon="lun 17 ago 2026"),
        # The new sanctioned divergence, and a new row rather than an
        # accident: at the 12-hour setting the window renders Spanish's own
        # CLDR meridiem designator while the Qt-free side renders fixed
        # English. The two agree on the *clock*, which is what the setting
        # controls; they differ in glyphs, which docs/ARCHITECTURE.md
        # already permits.
        LanguageRendering("clock_afternoon_12",
                           window=f"2:32 p.{_NNBSP}m.",
                           daemon=f"2:32 p.{_NNBSP}m."),
        LanguageRendering("clock_morning_12",
                           window=f"9:05 a.{_NNBSP}m.",
                           daemon=f"9:05 a.{_NNBSP}m."),
        LanguageRendering("clock_with_seconds_12",
                           window=f"2:32:05 p.{_NNBSP}m.",
                           daemon=f"2:32:05 p.{_NNBSP}m."),
        LanguageRendering("day_and_clock_24", window="lun 17 14:32",
                           daemon="lun 17 14:32"),
        LanguageRendering("day_and_clock_12",
                           window=f"lun 17 2:32 p.{_NNBSP}m.",
                           daemon=f"lun 17 2:32 p.{_NNBSP}m."),
        # The window column carries a decimal comma here because Qt renders
        # through QLocale; the daemon column carries a full stop because
        # PlainLocaleFormatter reads no locale and the surrounding catalog
        # pattern (po/es.po) is unchanged in Spanish.
        LanguageRendering("height_value", window="110,5", daemon="110,5"),
        LanguageRendering("height", window="110,5 cm", daemon="110,5 cm"),
        LanguageRendering("preset_tick", window="Sit · 110,5",
                           daemon="Sit · 110,5"),
        LanguageRendering("number_grouping", window="12.345,5",
                           daemon="12.345,5"),
    ),
}

_CASES_BY_NAME: dict[str, ContractCase] = {case.case: case for case in
                                            CONTRACT_CASES}


def _rendered_by_case(formatter: Formatter, case: ContractCase):
    """Render one case against one formatter. Most cases go through the
    ``Formatter`` facade; the grouping case cannot, because no facade
    method exposes a grouping toggle — the seam permits the divergence,
    but no product call reaches it.
    """
    formatter = presentation_samples.with_time_style(
        formatter, case.time_style)
    if case.through == "locale":
        return getattr(formatter.context.locale, case.helper)(*case.args)
    return getattr(formatter, case.helper)(*case.args)


@pytest.mark.parametrize("case", CONTRACT_CASES, ids=lambda c: c.case)
def test_every_hand_typed_case_renders_its_written_qt_free_value(case):
    """No language block is needed here: ``BACK-04`` plus the pass-through
    English translator make the Qt-free rendering language-independent by
    construction, and plan 04's second equality loop turns that same
    property into a standing check across every shipped language.
    """
    assert _rendered_by_case(
        presentation_samples.build_plain_formatter(), case) == case.qt_free


_LANGUAGE_ROW_PAIRS = [
    (language, row)
    for language, rows in GOLDEN_BY_LANGUAGE.items()
    for row in rows
]


@pytest.mark.parametrize(
    "language, row", _LANGUAGE_ROW_PAIRS,
    ids=[f"{language}-{row.case}" for language, row in _LANGUAGE_ROW_PAIRS])
def test_every_hand_typed_rendering_matches_its_written_contract(
        qapp, language, row):
    """Both the window formatter and the daemon formatter are built *and*
    rendered inside one ``_language(language)`` block: ``_qt_formatter()``
    reads the process default ``QLocale``, and ``GettextTranslator`` reads
    the process-wide gettext catalog — both at call time, so both must be
    read from inside the same binding.
    """
    case = _CASES_BY_NAME[row.case]
    with _language(language):
        assert _rendered_by_case(_qt_formatter(), case) == row.window
        assert _rendered_by_case(
            presentation_samples.build_daemon_formatter(language),
            case) == row.daemon


@pytest.mark.parametrize("case", CONTRACT_CASES, ids=lambda c: c.case)
def test_every_hand_typed_case_diverges_from_the_qt_free_column(case):
    """The divergence itself is written down, not left to be discovered
    later: at least one shipped language's window rendering must disagree
    with the Qt-free rendering for every case in the contract — the whole
    reason a case belongs in this hand-typed contract rather than in the
    equality half below. This is a pure data assertion on already-typed
    strings, no formatter call, and it extends to every future case
    through this same parametrization rather than a duplicated body.
    """
    windows = [row.window for rows in GOLDEN_BY_LANGUAGE.values()
               for row in rows if row.case == case.case]
    assert any(window != case.qt_free for window in windows), (
        f"{case.case}: every language's window column matches the "
        f"Qt-free column — this case belongs in the equality half below, "
        f"not in the hand-typed contract")


def test_every_shipped_language_has_a_hand_typed_row_set():
    """A shipped language with no row set fails here, naming it — a
    warning is a claim nobody reads (D-13). Never a hardcoded language
    pair (D-10): both sides come from the same enumerations the rest of
    this module already uses.
    """
    shipped = set(SHIPPED_LANGUAGES)
    covered = set(GOLDEN_BY_LANGUAGE)
    missing = shipped - covered
    stale = covered - shipped
    assert not missing and not stale, (
        f"no contract rows for: {sorted(missing)}; "
        f"contract rows for no-longer-shipped language(s): {sorted(stale)}")


@pytest.mark.parametrize("language", SHIPPED_LANGUAGES)
def test_every_language_row_set_covers_every_contract_case(language):
    """Each language's row set is checked against ``CONTRACT_CASES`` in
    both directions, so neither a missing case nor a stale one can
    accumulate silently in one language's row set.
    """
    expected = {case.case for case in CONTRACT_CASES}
    covered = {row.case for row in GOLDEN_BY_LANGUAGE[language]}
    assert expected == covered, (
        f"{language}: missing rows for {sorted(expected - covered)}; "
        f"stale rows for methods no longer in the contract: "
        f"{sorted(covered - expected)}")


# ----------------------------------------------------------------------
# Half two: every other shared formatter, by backend equality plus anchor.
# ----------------------------------------------------------------------

#: The cases pinned by hand above rather than by equality — every case
#: reached through the ``Formatter`` facade (``through="formatter"``), so
#: the grouping case, which reaches the locale backend directly and names no
#: sample row at all, is not mistaken for one.
#:
#: Keyed by *case*, deliberately, and not by the method the case calls. A
#: method can carry several sample rows (``connection_phrases`` has three,
#: ``clock`` two), and the hand-typed contract takes cases one at a time. Key
#: this by method and the first contract row added for a method that already
#: has samples silently evicts *every* one of that method's rows from the
#: equality half below — and, because the anchor check is keyed off what is
#: left, then demands that method's anchor be deleted as stale. That is a
#: coverage cliff the suite would push an author down rather than flag, so
#: the two halves partition the sample table by case and
#: test_the_two_halves_partition_every_sample holds them to it.
_HAND_TYPED_CASES = frozenset(
    case.case for case in CONTRACT_CASES if case.through == "formatter")

#: The equality-pinned rows from the shared sample table: everything that is
#: not one of the hand-typed cases above.
_EQUALITY_SAMPLES = tuple(
    row for row in presentation_samples.SAMPLES
    if row.case not in _HAND_TYPED_CASES)

#: One hand-typed anchor per distinct method among the equality-pinned
#: samples, keyed by *case* rather than by method (``connection_phrases``
#: returns a tuple, not a string, and only one of its three branches needs
#: an anchor), so the equality assertions below cannot pass because both
#: backends independently broke the same way. Typed from the spec, then
#: cross-checked against a live run of both backends.
ANCHORS: dict[str, object] = {
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
    "clock_afternoon_24": "14:32",
    "clock_with_seconds_24": "14:32:05",
    "day_label": "Mon",
    "fmt_days": "Mon–Wed",
    "duration_verbose": "1 hour 5 minutes",
    "duration_hm": "1h 05m",
    "duration": "45s",
    "duration_minutes": "10 min",
}


def _rendered(formatter: Formatter, row: presentation_samples.Sample):
    formatter = presentation_samples.with_time_style(formatter, row.time_style)
    return getattr(formatter, row.method)(*row.args, **row.kwargs)


_LANGUAGE_EQUALITY_PAIRS = [
    (language, row)
    for language in SHIPPED_LANGUAGES
    for row in _EQUALITY_SAMPLES
]


@pytest.mark.parametrize(
    "language, row", _LANGUAGE_EQUALITY_PAIRS,
    ids=[f"{language}-{row.case}" for language, row in _LANGUAGE_EQUALITY_PAIRS])
def test_the_two_locale_bearing_backends_agree_in_every_shipped_language(
        qapp, language, row):
    """The window pairing (``QtLocaleFormatter`` + ``GettextTranslator``)
    against the daemon pairing (``PlainLocaleFormatter`` +
    ``GettextTranslator``), for every formatter that is not one of the
    sanctioned exceptions above, in every shipped language. Both sides
    carry the *same* translator, so the words match by construction and
    any failure here is a genuine value-rendering difference, never a
    translation difference. Neither side names any expected text — this is
    an equality assertion, which pins a relationship rather than a
    captured value, so it works in a language nobody has written yet.

    The rejected alternative is comparing the window pairing against the
    **journal** pairing in Spanish: that would compare translated text
    against deliberately-untranslated text, so nearly every row would fail
    for a reason that is not a defect — see the ``en``-only branch below
    for where the journal comparison still belongs.

    Both formatters are built *and* rendered inside one ``_language(...)``
    block: ``GettextTranslator`` reads the process-wide gettext catalog at
    call time, so it must be read from inside the same binding that
    installed it.
    """
    with _language(language):
        window_output = _rendered(_qt_formatter(), row)
        daemon_output = _rendered(
            presentation_samples.build_daemon_formatter(), row)
    assert window_output == daemon_output, (
        f"{language}/{row.case}: the window pairing rendered "
        f"{window_output!r}, the daemon pairing rendered {daemon_output!r} "
        f"— these two are supposed to agree")

    if language != "en":
        return

    # The journal pairing and the hand-typed anchors are English-only by
    # construction: the journal's pass-through translator is deliberately
    # untranslated (D-07), and the anchors below are typed in English, so
    # neither check would mean anything run against another language.
    plain_output = _rendered(presentation_samples.build_plain_formatter(), row)
    assert window_output == plain_output, (
        f"{row.case}: Qt/en rendered {window_output!r}, the Qt-free "
        f"journal backend rendered {plain_output!r} — these two are "
        f"supposed to agree")
    anchor = ANCHORS.get(row.case)
    if anchor is not None:
        assert window_output == anchor, (
            f"{row.case}: Qt/en rendered {window_output!r}, expected the "
            f"hand-typed anchor {anchor!r} — an anchor mismatch means both "
            f"backends could be wrong the same way and the equality check "
            f"above would never catch it")


#: ``en`` is the baseline the loop below compares against, so it is not also
#: one of the languages compared *to* it: that half of the parametrization
#: asserted a value equals itself, and a green count inflated by tautologies
#: reads as coverage it is not. Should ``es`` ever be dropped this loop
#: generates nothing, which is honest — the POSIX-locale leg below is what
#: keeps a shipped-language-independent axis under test either way.
_LANGUAGE_ALL_SAMPLE_PAIRS = [
    (language, row)
    for language in SHIPPED_LANGUAGES if language != "en"
    for row in presentation_samples.SAMPLES
]


@pytest.mark.parametrize(
    "language, row", _LANGUAGE_ALL_SAMPLE_PAIRS,
    ids=[f"{language}-{row.case}" for language, row in _LANGUAGE_ALL_SAMPLE_PAIRS])
def test_the_qt_free_backend_renders_the_same_in_every_shipped_language(
        qapp, language, row):
    """One of ``BACK-04``'s two axes as a check: the **app** language. The
    pass-through English translator reads no catalog and the Qt-free locale
    backend reads no ``QLocale``, so the journal pairing's output must be
    identical no matter which language the process has installed. This is
    also what ``docs/LOGGING.md``'s stable greppable English promise
    depends on — the journal must read the same in any language.

    It is only that one axis. What :func:`_language` varies is the default
    ``QLocale`` and the gettext catalog, and a backend that read the *POSIX*
    locale instead — the reintroduced ``import locale`` or C-library date
    conversion ``plain_locale.py``'s own docstring names as the trap — would
    sail straight through this loop. The leg below varies that second axis,
    and ``tests/test_plain_locale.py``'s structural gate is what holds it
    where no foreign locale is installed to vary.

    Every row in :data:`presentation_samples.SAMPLES` is checked here,
    including the four moment renderers already pinned by hand above:
    the journal pairing is language-independent for those too, and there
    is no reason to exclude them from this check.
    """
    with _language("en"):
        baseline = _rendered(presentation_samples.build_plain_formatter(), row)
    with _language(language):
        other = _rendered(presentation_samples.build_plain_formatter(), row)
    assert baseline == other, (
        f"{row.case}: the Qt-free backend rendered {baseline!r} in en but "
        f"{other!r} in {language} — it must read no locale (BACK-04)")


#: Locales whose number and date conventions differ from ``C``'s, tried in
#: order. Only the two categories that could change a rendering are bound:
#: the C library's number conversion reads the numeric category and its date
#: conversion reads the time one, and leaving the character-type and message
#: categories alone keeps this from disturbing a Qt already loaded in the
#: same process. ``tests/test_plain_locale.py`` binds the same two, for the
#: same reason.
_HOSTILE_POSIX_LOCALES = ("es_ES.UTF-8", "de_DE.UTF-8", "fr_FR.UTF-8")


@contextmanager
def _posix_locale(candidates: tuple[str, ...]) -> Iterator[str]:
    """Bind the numeric and time categories to the first installed
    candidate, then restore whatever was there.

    Skips, rather than passes, where the C library has none of them
    generated — a GitHub runner and the RPM buildroot both carry English
    only. That is a capability-absent skip: it reports that this leg did not
    run, and it cannot resolve a mismatch, so GATE-15's "no skip that lets a
    mismatch be resolved by anything except fixing the code" is untouched by
    it. The structural gate in ``tests/test_plain_locale.py`` is what proves
    this property where this leg only corroborates it.
    """
    saved_numeric = locale.setlocale(locale.LC_NUMERIC)
    saved_time = locale.setlocale(locale.LC_TIME)
    try:
        for candidate in candidates:
            try:
                locale.setlocale(locale.LC_NUMERIC, candidate)
                locale.setlocale(locale.LC_TIME, candidate)
            except locale.Error:
                continue
            yield candidate
            return
        pytest.skip(
            f"none of {candidates} is generated on this machine — the "
            f"structural gate in tests/test_plain_locale.py is what proves "
            f"BACK-04's POSIX axis, not this leg")
    finally:
        locale.setlocale(locale.LC_NUMERIC, saved_numeric)
        locale.setlocale(locale.LC_TIME, saved_time)


@pytest.mark.parametrize(
    "row", presentation_samples.SAMPLES, ids=lambda r: r.case)
def test_the_qt_free_backend_ignores_the_posix_locale_too(row):
    """``BACK-04``'s other axis, and the one the app language loop above
    cannot reach: the POSIX locale. A ``locale.format_string`` or a
    C-library date conversion reintroduced anywhere under
    ``core/presentation/`` follows the numeric and time categories, and
    follows nothing ``_language`` installs — under a Spanish POSIX locale
    those would render ``110,5`` and ``lun 17`` where the journal must read
    ``110.5`` and ``2026-08-17``, which is precisely the "Qt-free side
    disagrees with the window in English words" outcome the design was
    written to remove.

    The baseline is taken under ``C`` rather than under whatever the runner
    left behind, so this compares two named locales and not the ambient one
    against itself — a machine already running in Spanish would otherwise
    make the comparison vacuous.
    """
    with _posix_locale(("C",)):
        baseline = _rendered(presentation_samples.build_plain_formatter(), row)
    with _posix_locale(_HOSTILE_POSIX_LOCALES) as name:
        under_locale = _rendered(
            presentation_samples.build_plain_formatter(), row)
    assert baseline == under_locale, (
        f"{row.case}: the Qt-free backend rendered {baseline!r} under the C "
        f"locale but {under_locale!r} under {name} — it must read no "
        f"locale, POSIX included (BACK-04)")


def test_every_distinct_equality_pinned_method_has_an_anchor():
    """The anchor table is guarded in both directions: every distinct
    method among the equality-pinned samples needs at least one of its
    cases in :data:`ANCHORS` (so the equality half can never pass purely
    because two backends broke identically), and every key in
    :data:`ANCHORS` must still name a case among the equality-pinned
    samples (so a case that moves to the hand-typed contract cannot leave
    a stale anchor behind that reads like coverage it no longer is).
    """
    equality_cases = {row.case for row in _EQUALITY_SAMPLES}
    anchored_methods = {row.method for row in _EQUALITY_SAMPLES
                         if row.case in ANCHORS}
    equality_methods = {row.method for row in _EQUALITY_SAMPLES}
    missing = equality_methods - anchored_methods
    stale = set(ANCHORS) - equality_cases
    assert not missing and not stale, (
        f"no anchor recorded for: {sorted(missing)}; "
        f"anchor(s) for case(s) no longer equality-pinned: {sorted(stale)}")


def test_the_two_halves_partition_every_sample():
    """Every sample row belongs to exactly one half — hand-typed above or
    equality-pinned below — and every hand-typed case names a real sample
    row. The split is what makes a method's remaining cases keep their
    equality coverage when one of its cases enters the hand-typed contract,
    and this is what holds the two halves to it: a hand-typed case naming no
    sample row is a contract row nothing else exercises, and a sample in
    neither half is a formatter nothing pins.
    """
    sample_cases = {row.case for row in presentation_samples.SAMPLES}
    orphaned = _HAND_TYPED_CASES - sample_cases
    assert not orphaned, (
        f"hand-typed case(s) naming no row in the shared sample table: "
        f"{sorted(orphaned)} — the two tables have drifted apart on case "
        f"names, and the equality half is silently covering a case the "
        f"contract believes it owns")
    equality_cases = {row.case for row in _EQUALITY_SAMPLES}
    assert equality_cases | _HAND_TYPED_CASES == sample_cases, (
        f"sample row(s) in neither half: "
        f"{sorted(sample_cases - equality_cases - _HAND_TYPED_CASES)}")
    assert not equality_cases & _HAND_TYPED_CASES, (
        f"case(s) in both halves at once: "
        f"{sorted(equality_cases & _HAND_TYPED_CASES)}")


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

    The exclusion table is guarded first, and it has to be: it is the one
    table that decides what everything below measures, and subtracting a
    name that is not on ``Formatter`` at all takes nothing out of the
    comparison and is never reported. A dead excuse then reads like a
    decision someone made — and the same unguarded line is how a live
    formatter could be excused out of the contract, the sweep and the
    Qt-free callability leg at once.
    """
    public = _public_formatter_members()
    excused = set(presentation_samples.NOT_FORMATTERS)
    phantom = excused - public
    assert not phantom, (
        f"NOT_FORMATTERS excuses member(s) that are not on Formatter at "
        f"all: {sorted(phantom)}")
    expected = public - excused
    covered = {row.method for row in presentation_samples.SAMPLES}
    assert expected == covered, (
        f"missing sample rows: {sorted(expected - covered)}; "
        f"stale sample rows for methods no longer public: "
        f"{sorted(covered - expected)}")
