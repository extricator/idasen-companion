"""The daemon's notification sentences, at the shared implementation.

Phase 14 moved these out of ``daemon/main.py`` so the daemon calls a
formatter rather than selecting a sentence and substituting a duration on
its own. That makes them testable here, once, instead of only through a
daemon fixture — which is criterion 2's whole argument: a shared layer
exercised only by tests written alongside it proves the tests agree with
the implementation, not that a real caller can use it.

Which sentence a state selects is asserted against ``FakeTranslator``'s
markers, so the policy assertion cannot pass or fail for a reason belonging
to a catalog. A separate pair of cases renders through the real
``GettextTranslator`` in ``es``, to prove the existing Spanish is actually
reached after the msgids changed file. ``core/i18n.py`` binds a
process-wide catalog, so those bind and release it explicitly — the idiom
``tests/test_gettext_translator.py`` uses.
"""

from __future__ import annotations

import pytest

from idasen_companion.core import i18n
from idasen_companion.core.machine import DeskState
from idasen_companion.core.presentation import register
from idasen_companion.core.presentation.formatter import (
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.gettext_translator import (
    GettextTranslator,
)
from idasen_companion.core.presentation.plain_locale import PlainLocaleFormatter
from idasen_companion.core.units import HeightUnit

from presentation_fakes import FakeLocale, FakeTranslator


@pytest.fixture
def fake():
    """A Formatter over the two fakes, plus the translator to inspect."""
    translator = FakeTranslator()
    context = PresentationContext(
        locale=FakeLocale(), translator=translator,
        unit=HeightUnit.CENTIMETRES)
    return Formatter(context), translator


def _real(language: str) -> Formatter:
    """The daemon's own pair (D-06), against a bound catalog."""
    i18n.set_language(language)
    return Formatter(PresentationContext(
        locale=PlainLocaleFormatter(), translator=GettextTranslator(),
        unit=HeightUnit.CENTIMETRES))


@pytest.fixture
def spanish():
    try:
        yield _real("es")
    finally:
        i18n.set_language(i18n.SYSTEM)


@pytest.fixture
def english():
    """The same pair with no catalog bound, so a lookup yields its source.

    ``pre_move_summary`` cannot be exercised through ``FakeTranslator``:
    the delay it substitutes goes through ``duration_verbose``, whose
    plural markers contain ``%d`` and blow up the very ``%`` substitution
    under test. Comparing the result against the register constant here is
    still a policy assertion — it names which constant the state selected —
    and it reads no Spanish.
    """
    try:
        yield _real(i18n.SYSTEM)
    finally:
        i18n.set_language(i18n.SYSTEM)


# ---- which sentence each state selects ----------------------------------

@pytest.mark.parametrize("state,source", [
    (DeskState.STANDING, register.PRE_MOVE_STANDING),
    (DeskState.SITTING, register.PRE_MOVE_SITTING),
])
def test_the_pre_move_summary_selects_a_whole_sentence_per_direction(
        english, state, source):
    assert (english.pre_move_summary(state, 3900)
            == source % english.duration_verbose(3900))


def test_the_pre_move_summary_renders_its_own_delay(english):
    """It takes seconds, not a rendered delay: rendering here is what
    leaves the caller with no duration to assemble."""
    assert english.pre_move_summary(DeskState.STANDING, 3900) == (
        "Standing up in about 1 hour 5 minutes")


@pytest.mark.parametrize("state,source", [
    (DeskState.STANDING, register.MOVE_FAILED_STANDING),
    (DeskState.SITTING, register.MOVE_FAILED_SITTING),
])
def test_the_failed_move_summary_selects_a_whole_sentence_per_direction(
        fake, state, source):
    formatter, translator = fake
    formatter.move_failed_summary(state)
    assert [call.source for call in translator.calls] == [source]


def test_the_failed_move_body_names_the_reason_when_there_is_one(fake):
    """The reason is the daemon's own English diagnostic detail — it is
    substituted, never translated."""
    formatter, translator = fake
    assert formatter.move_failed_body("timed out") == (
        FakeTranslator().message(register.MOVE_FAILED_BODY_WITH_REASON)
        % "timed out")
    assert translator.calls[-1].source == register.MOVE_FAILED_BODY_WITH_REASON


def test_the_failed_move_body_omits_the_reason_when_there_is_none(fake):
    formatter, translator = fake
    assert (formatter.move_failed_body()
            == FakeTranslator().message(register.MOVE_FAILED_BODY))
    assert [call.source for call in translator.calls] == [
        register.MOVE_FAILED_BODY]


@pytest.mark.parametrize("call_method,source", [
    (lambda f: f.pre_move_body(), register.PRE_MOVE_BODY),
    (lambda f: f.skip_action_label(), register.SKIP_ACTION),
    (lambda f: f.automation_paused_summary(),
     register.AUTOMATION_PAUSED_SUMMARY),
    (lambda f: f.automation_paused_body(), register.AUTOMATION_PAUSED_BODY),
    (lambda f: f.try_now_action_label(), register.TRY_NOW_ACTION),
])
def test_each_fixed_sentence_renders_its_own_register_entry(
        fake, call_method, source):
    formatter, translator = fake
    assert call_method(formatter) == FakeTranslator().message(source)
    assert [c.source for c in translator.calls] == [source]


def test_the_snooze_label_substitutes_its_minute_count(fake):
    formatter, translator = fake
    assert (formatter.snooze_action_label(15)
            == FakeTranslator().message(register.SNOOZE_ACTION) % 15)
    assert [c.source for c in translator.calls] == [register.SNOOZE_ACTION]


# ---- the Spanish that survived the move between files -------------------

def test_the_pre_move_summary_reaches_the_existing_spanish(spanish):
    """The msgids changed file, not text, so po/es.po's translation had to
    survive msgmerge untouched. This is what proves it did."""
    rendered = spanish.pre_move_summary(DeskState.STANDING, 3900)
    assert rendered != "Standing up in about 1 hour 5 minutes"
    assert "1 hora y 5 minutos" in rendered


@pytest.mark.parametrize("call_method,english", [
    (lambda f: f.pre_move_body(), register.PRE_MOVE_BODY),
    (lambda f: f.automation_paused_summary(),
     register.AUTOMATION_PAUSED_SUMMARY),
    (lambda f: f.move_failed_summary(DeskState.SITTING),
     register.MOVE_FAILED_SITTING),
    (lambda f: f.try_now_action_label(), register.TRY_NOW_ACTION),
])
def test_every_notification_sentence_is_translated_in_spanish(
        spanish, call_method, english):
    assert call_method(spanish) != english
