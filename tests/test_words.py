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


def test_connection_phrases_reads_nothing_but_its_translator():
    """PRES-02 in miniature: the same key rendered through two different
    translators gives two different answers, so nothing here is reaching
    for a process-wide catalog of its own.
    """
    first, second = FakeTranslator(), FakeTranslator()
    second.message = lambda source, **values: f"<{source}>"  # type: ignore[method-assign]
    assert (words.connection_phrases(first, "connected")
            != words.connection_phrases(second, "connected"))
