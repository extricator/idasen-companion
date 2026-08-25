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
import os
from datetime import datetime
from typing import NamedTuple

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
from idasen_companion.core.presentation.specs import NumberSpec  # noqa: E402
from idasen_companion.core.units import HeightUnit  # noqa: E402
from idasen_companion.gui.locale_backend import QtLocaleFormatter  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


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

#: The representative height this module's cases render, mirroring
#: ``presentation_samples.py``'s own representative height so a reader
#: only has to learn one number.
_HEIGHT_METERS = 1.105


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
    """

    case: str
    helper: str
    args: tuple[object, ...]
    qt_free: str
    through: str = "formatter"


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
    ContractCase("day_short", "day_short", (_AFTERNOON,), qt_free="2026-08-17"),
    ContractCase("day_heading", "day_heading", (_AFTERNOON,),
                 qt_free="2026-08-17"),
    ContractCase("clock_afternoon", "clock", (_AFTERNOON,), qt_free="14:32"),
    ContractCase("clock_morning", "clock", (_MORNING,), qt_free="09:05"),
    ContractCase("day_and_clock", "day_and_clock", (_AFTERNOON,),
                 qt_free="2026-08-17 14:32"),
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
#: The daemon column agrees with the qt_free column in every row below
#: because the three gettext patterns these cases reach — the height-unit
#: suffix, the day-and-clock join, and the preset-tick separator — are
#: deliberately identical in Spanish today (``po/es.po``). That agreement
#: is a fact being pinned, not a redundancy: the day a Spanish translation
#: of one of those patterns changes, this daemon column goes red and the
#: journal column (``build_plain_formatter``, reached by no catalog) does
#: not.
GOLDEN_BY_LANGUAGE: dict[str, tuple[LanguageRendering, ...]] = {
    "en": (
        LanguageRendering("day_short", window="Mon 17", daemon="2026-08-17"),
        LanguageRendering("day_heading", window="Mon 17 Aug 2026",
                           daemon="2026-08-17"),
        LanguageRendering("clock_afternoon", window=f"2:32{_NNBSP}PM",
                           daemon="14:32"),
        LanguageRendering("clock_morning", window=f"9:05{_NNBSP}AM",
                           daemon="09:05"),
        LanguageRendering("day_and_clock", window=f"Mon 17 2:32{_NNBSP}PM",
                           daemon="2026-08-17 14:32"),
        LanguageRendering("height_value", window="110.5", daemon="110.5"),
        LanguageRendering("height", window="110.5 cm", daemon="110.5 cm"),
        LanguageRendering("preset_tick", window="Sit · 110.5",
                           daemon="Sit · 110.5"),
        LanguageRendering("number_grouping", window="12,345.5",
                           daemon="12,345.5"),
    ),
    "es": (
        LanguageRendering("day_short", window="lun 17", daemon="2026-08-17"),
        LanguageRendering("day_heading", window="lun 17 ago 2026",
                           daemon="2026-08-17"),
        LanguageRendering("clock_afternoon", window="14:32", daemon="14:32"),
        LanguageRendering("clock_morning", window="9:05", daemon="09:05"),
        LanguageRendering("day_and_clock", window="lun 17 14:32",
                           daemon="2026-08-17 14:32"),
        # The window column carries a decimal comma here because Qt renders
        # through QLocale; the daemon column carries a full stop because
        # PlainLocaleFormatter reads no locale and the surrounding catalog
        # pattern (po/es.po) is unchanged in Spanish.
        LanguageRendering("height_value", window="110,5", daemon="110.5"),
        LanguageRendering("height", window="110,5 cm", daemon="110.5 cm"),
        LanguageRendering("preset_tick", window="Sit · 110,5",
                           daemon="Sit · 110.5"),
        LanguageRendering("number_grouping", window="12.345,5",
                           daemon="12,345.5"),
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
            presentation_samples.build_daemon_formatter(), case) == row.daemon


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
    "day_label": "Mon",
    "fmt_days": "Mon–Wed",
    "duration_verbose": "1 hour 5 minutes",
    "duration_hm": "1h 05m",
    "duration": "45s",
}


def _rendered(formatter: Formatter, row: presentation_samples.Sample):
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


_LANGUAGE_ALL_SAMPLE_PAIRS = [
    (language, row)
    for language in SHIPPED_LANGUAGES
    for row in presentation_samples.SAMPLES
]


@pytest.mark.parametrize(
    "language, row", _LANGUAGE_ALL_SAMPLE_PAIRS,
    ids=[f"{language}-{row.case}" for language, row in _LANGUAGE_ALL_SAMPLE_PAIRS])
def test_the_qt_free_backend_renders_the_same_in_every_shipped_language(
        qapp, language, row):
    """``BACK-04`` expressed as a check rather than as a promise: the
    Qt-free backend reads no locale, and the pass-through English
    translator reads no catalog, so the journal pairing's output must be
    identical no matter which language the process has installed. This is
    also what ``docs/LOGGING.md``'s stable greppable English promise
    depends on — the journal must read the same in any language.

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
    """
    expected = _public_formatter_members() - set(presentation_samples.NOT_FORMATTERS)
    covered = {row.method for row in presentation_samples.SAMPLES}
    assert expected == covered, (
        f"missing sample rows: {sorted(expected - covered)}; "
        f"stale sample rows for methods no longer public: "
        f"{sorted(covered - expected)}")
