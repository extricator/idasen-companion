"""Behaviour of the shared vocabulary in ``core/presentation/words.py``.

Pure ``core/`` tests: no Qt, no window, no ``QT_QPA_PLATFORM``. Every case
here asserts against ``FakeTranslator``'s markers rather than a rendered
Spanish string, so what is being checked is *which* source key a state
selects — the product policy — and never a catalog's own output.

These are also where the unrecognized-key fallbacks are pinned. Each word
is reached two ways after Phase 14 — a ``Formatter`` method and a
``gui/util.py`` forwarder — and a forwarder that quietly changed a default
would render subtly different text at one of the GUI's call sites with no
test covering that site. The fallback is therefore tested once, here, at
the shared implementation both doors reach.
"""

from __future__ import annotations

import pytest

from idasen_companion.core.presentation import register, words

from presentation_fakes import FakeTranslator


@pytest.mark.parametrize("connected,available,persistent,expected", [
    (True, True, False, "connected"),
    (True, False, True, "connected"),
    (False, False, False, "disconnected"),
    (False, True, True, "disconnected"),
    (False, False, True, "disconnected"),
    (False, True, False, "on-demand"),
])
def test_connection_state_key_reproduces_the_branch_order(
        connected, available, persistent, expected):
    """Connected wins outright; then unavailable-or-persistent; then the
    fall-through. `persistent=True` with `available=True` is the case worth
    naming: a persistent link that is not up reads as disconnected, not as
    on-demand.
    """
    assert words.connection_state_key(
        connected, available, persistent) == expected


@pytest.mark.parametrize("key,footer,chip", [
    ("connected", register.CONNECTION_FOOTER_CONNECTED,
     register.CONNECTION_CHIP_CONNECTED),
    ("disconnected", register.CONNECTION_FOOTER_DISCONNECTED,
     register.CONNECTION_CHIP_DISCONNECTED),
    ("on-demand", register.CONNECTION_FOOTER_ON_DEMAND,
     register.CONNECTION_CHIP_ON_DEMAND),
])
def test_connection_phrases_selects_the_pair_for_each_key(key, footer, chip):
    translator = FakeTranslator()
    assert words.connection_phrases(translator, key) == (
        translator.message(footer), translator.message(chip))
    assert [call.source for call in translator.calls] == [
        footer, chip, footer, chip]


def test_an_unrecognized_connection_key_falls_through_to_on_demand():
    """The pre-move branch tested two states and returned the third
    unguarded, so anything unrecognized already rendered as on-demand. A
    forwarder changes no default (D-02), so neither does the move.
    """
    translator = FakeTranslator()
    assert (words.connection_phrases(translator, "nonsense")
            == words.connection_phrases(FakeTranslator(), "on-demand"))
    assert [call.source for call in translator.calls] == [
        register.CONNECTION_FOOTER_ON_DEMAND,
        register.CONNECTION_CHIP_ON_DEMAND]


@pytest.mark.parametrize("lookup,table", [
    (words.status_label, register.STATUS_LABELS),
    (words.status_head, register.STATUS_HEADS),
])
def test_a_known_status_renders_its_own_register_entry(lookup, table):
    translator = FakeTranslator()
    for key, source in table.items():
        assert lookup(translator, key) == FakeTranslator().message(source)


@pytest.mark.parametrize("lookup", [words.status_label, words.status_head])
def test_an_unrecognized_status_falls_back_to_the_raw_wire_value(lookup):
    """A status the app has not been taught yet shows as its wire value
    rather than as nothing. That was the behaviour before the move and a
    forwarder changes no default (D-02); tests/test_status_labels.py is what
    stops the fallback becoming the way a new status ships.
    """
    translator = FakeTranslator()
    assert lookup(translator, "unknown-status") == "unknown-status"
    assert translator.calls == []


def test_the_two_status_tables_share_their_wording_where_it_matches():
    """`Paused`, `Automation off` and `Last move failed` are one source
    string in both tables, so they are one catalog entry and a translator
    cannot render one state two ways. The heads table is shorter only where
    the two genuinely differ.
    """
    shared = {key for key in register.STATUS_HEADS
              if register.STATUS_HEADS[key] == register.STATUS_LABELS.get(key)}
    assert shared == {"paused", "disabled", "move-failed"}


@pytest.mark.parametrize("lookup,table", [
    (words.position_label, register.POSITION_LABELS),
    (words.preset_label, register.PRESET_LABELS),
    (words.trigger_label, register.TRIGGER_LABELS),
])
def test_a_known_key_renders_its_own_register_entry(lookup, table):
    translator = FakeTranslator()
    for key, source in table.items():
        assert lookup(translator, key) == FakeTranslator().message(source)


def test_an_unknown_position_capitalizes_and_an_empty_one_is_blank():
    """Two different fallbacks, both today's behaviour: an unrecognized
    position is still worth showing capitalized, but an empty one renders
    as nothing so a caller can substitute its own placeholder.
    """
    translator = FakeTranslator()
    assert words.position_label(translator, "custom-spot") == "Custom-spot"
    assert words.position_label(translator, "") == ""
    assert translator.calls == []


def test_an_unknown_trigger_falls_back_to_the_raw_wire_value():
    translator = FakeTranslator()
    assert words.trigger_label(translator, "nope") == "nope"
    assert translator.calls == []


def test_a_user_named_preset_is_returned_verbatim():
    """Only the two protected presets are ours to translate. A user's own
    preset name is their words and is never capitalized, translated or
    otherwise touched.
    """
    translator = FakeTranslator()
    assert words.preset_label(translator, "my desk") == "my desk"
    assert words.preset_label(translator, "SIT") == "SIT"
    assert translator.calls == []


def test_the_three_sit_stand_renderings_are_three_separate_entries():
    """`f3c2add` records a merge that was wrong for exactly this reason.
    The desk's *state* as a label, the preset *button*'s imperative, and
    the journal's lowercase mid-sentence adjective are three concepts that
    happen to collide in English; Spanish needs three different words, so
    they must stay three catalog entries. This pins the two that live in
    the register apart from each other — the third is `gui/log_catalog.py`'s
    and renders through the English-only backend, not through a catalog.
    """
    assert (set(register.POSITION_LABELS.values())
            & set(register.PRESET_LABELS.values())) == set()


def test_every_day_key_renders_its_own_register_entry():
    translator = FakeTranslator()
    for key, source in register.DAY_NAMES.items():
        assert (words.day_label(translator, key)
                == FakeTranslator().message(source))


def test_an_empty_day_list_renders_the_no_days_stand_in():
    """Reachable: the Automation page lets every day chip be unchecked and
    `_validate` does not refuse an empty list."""
    translator = FakeTranslator()
    assert (words.fmt_days(translator, [])
            == FakeTranslator().message(register.NO_DAYS))
    assert [call.source for call in translator.calls] == [register.NO_DAYS]


def test_a_single_day_renders_as_that_day_alone():
    translator = FakeTranslator()
    assert (words.fmt_days(translator, ["mon"])
            == FakeTranslator().message(register.DAY_NAMES["mon"]))
    assert register.DAY_PAIR not in [c.source for c in translator.calls]


def test_a_run_of_two_stays_a_comma_pair():
    """Two consecutive days are below the run threshold, so they join
    through the pair pattern rather than collapsing into a range."""
    translator = FakeTranslator()
    words.fmt_days(translator, ["mon", "tue"])
    sources = [call.source for call in translator.calls]
    assert register.DAY_RANGE not in sources
    assert sources.count(register.DAY_PAIR) == 1


def test_a_run_of_three_or_more_collapses_into_a_range():
    translator = FakeTranslator()
    words.fmt_days(translator, ["mon", "tue", "wed", "thu", "fri"])
    sources = [call.source for call in translator.calls]
    assert sources.count(register.DAY_RANGE) == 1
    assert register.DAY_PAIR not in sources


def test_a_mixed_list_folds_one_pair_pattern_left_across_its_parts():
    """Three non-consecutive days need two joins, not one three-slot
    message: the fold is deliberately one pair pattern applied repeatedly
    rather than CLDR's start/middle/end key set.
    """
    translator = FakeTranslator()
    words.fmt_days(translator, ["mon", "wed", "fri"])
    sources = [call.source for call in translator.calls]
    assert sources.count(register.DAY_PAIR) == 2
    assert register.DAY_RANGE not in sources


def test_a_range_and_a_loose_day_combine_through_both_patterns():
    translator = FakeTranslator()
    words.fmt_days(translator, ["mon", "tue", "wed", "fri"])
    sources = [call.source for call in translator.calls]
    assert sources.count(register.DAY_RANGE) == 1
    assert sources.count(register.DAY_PAIR) == 1


def test_the_day_list_is_rendered_in_week_order_not_argument_order():
    translator = FakeTranslator()
    scrambled = words.fmt_days(translator, ["fri", "mon", "wed"])
    assert scrambled == words.fmt_days(FakeTranslator(),
                                       ["mon", "wed", "fri"])


def test_connection_phrases_reads_nothing_but_its_translator():
    """PRES-02 in miniature: the same key rendered through two different
    translators gives two different answers, so nothing here is reaching
    for a process-wide catalog of its own.
    """
    first, second = FakeTranslator(), FakeTranslator()
    second.message = lambda source, **values: f"<{source}>"  # type: ignore[method-assign]
    assert (words.connection_phrases(first, "connected")
            != words.connection_phrases(second, "connected"))
