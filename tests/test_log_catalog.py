"""Activity Log reader rendering derives from the one canonical catalog."""

import pytest

pytest.importorskip("PySide6.QtCore",
                    reason="GUI catalog needs PySide6")

from idasen_companion.core import i18n, logmsg  # noqa: E402
from idasen_companion.core.presentation import EnglishTranslator  # noqa: E402
from idasen_companion.core.presentation import (  # noqa: E402
    Formatter, PresentationContext,
)
from idasen_companion.core.locale_profile import TimeStyle
from idasen_companion.core.locale_profile import (  # noqa: E402
    LocaleProfile,
)
from idasen_companion.core.display_prefs import HeightUnit  # noqa: E402
from idasen_companion.gui import log_catalog  # noqa: E402


def _formatter() -> Formatter:
    context = PresentationContext(
        locale=LocaleProfile("en_US"), translator=EnglishTranslator(),
        unit=HeightUnit.CENTIMETRES,
        time_style=TimeStyle.HOUR_AND_MINUTE_24)
    return Formatter(context)


def test_every_message_has_a_translatable_twin():
    missing = set(logmsg.all_messages()) - set(log_catalog.TEXTS)
    assert not missing, f"no GUI catalog entry for: {sorted(missing)}"


def test_the_gui_catalog_has_no_orphans():
    extra = set(log_catalog.TEXTS) - set(logmsg.all_messages())
    assert not extra, f"GUI catalog entry with no message: {sorted(extra)}"


@pytest.mark.parametrize("msg_id", sorted(logmsg.all_messages()))
def test_the_english_matches_exactly(msg_id):
    assert log_catalog.TEXTS[msg_id] == logmsg.all_messages()[msg_id].text


def test_the_cycle_note_matches():
    assert log_catalog.CYCLE_NOTE == logmsg.CYCLE_NOTE.text


def test_every_fallback_note_has_a_twin():
    expected = {mid: m.fallback_note
                for mid, m in logmsg.all_messages().items() if m.fallback_note}
    assert log_catalog._FALLBACK_NOTES == expected


def test_the_gui_formats_every_parameter_kind():
    """A new Param kind with no GUI formatter would render as '?' at runtime."""
    assert set(log_catalog.build_formatters(_formatter())) == set(logmsg.Param)


def test_build_formatters_covers_every_param_the_journal_covers():
    """The GUI's table and the journal's ``ENGLISH_FORMATTERS`` cannot drift
    in *coverage* the same way the tests above already stop them drifting in
    *text* — a ``Param`` member added to one without the other would render
    ``?`` on whichever side got missed."""
    assert (set(log_catalog.build_formatters(_formatter()))
            == set(logmsg.ENGLISH_FORMATTERS))


def test_render_requires_fmt():
    """``fmt`` is keyword-only precisely so a caller cannot omit it and get a
    stale or wrong renderer by accident -- omitting it must fail loudly."""
    with pytest.raises(TypeError):
        log_catalog.render("cycle.skipped", {"state": "sitting",
                                             "next_target": 0}, "")


def test_every_message_renders_in_the_gui():
    """Drive the whole catalog through the GUI renderer with plausible values,
    so a template the GUI can't fill fails here rather than in the log."""
    samples = {
        logmsg.Param.DURATION: 1500,
        logmsg.Param.HEIGHT: 1.1,
        logmsg.Param.STATE: "sitting",
        logmsg.Param.TEXT: "x",
        logmsg.Param.INT: 3,
    }
    fmt = _formatter()
    for msg_id, message in logmsg.all_messages().items():
        params = {name: samples[kind] for name, kind in message.params.items()}
        line = log_catalog.render(msg_id, params, "fallback", fmt=fmt)
        assert line and "%(" not in line, f"{msg_id}: {line}"


def test_an_unknown_id_falls_back_to_the_daemon_text():
    # An older GUI meeting a newer daemon shows the English it was sent
    # rather than nothing at all.
    assert log_catalog.render(
        "nope.not.here", {}, "English text", fmt=_formatter()) == "English text"


def test_a_diagnostic_line_falls_back_to_its_text():
    # Diagnostic lines carry no id by design.
    assert log_catalog.render(
        "", {}, "BLE: connect failed", fmt=_formatter()) == "BLE: connect failed"


def test_state_words_stay_lowercase_for_mid_sentence_use():
    line = log_catalog.render("cycle.skipped",
                              {"state": "sitting", "next_target": 0}, "",
                              fmt=_formatter())
    assert "staying sitting." in line


def test_heights_render_in_centimetres_for_the_gui():
    line = log_catalog.render("preset.saved", {"name": "desk", "height": 1.1}, "",
                              fmt=_formatter())
    assert "110.0 cm" in line


def test_sub_minute_durations_stay_visible():
    """The GUI's minutes-and-hours format floored these to "0m" while the
    journal reported real seconds — and a lock reports an idle time near zero,
    so the disagreement was on screen routinely."""
    fmt = _formatter()
    line = log_catalog.render("presence.now_idle", {"idle_time": 0}, "", fmt=fmt)
    assert "0s" in line
    line = log_catalog.render("presence.now_idle", {"idle_time": 45}, "", fmt=fmt)
    assert "45s" in line
    line = log_catalog.render("presence.now_idle", {"idle_time": 3900}, "", fmt=fmt)
    assert "1h 05m" in line


def test_snooze_reader_accepts_old_minutes_and_new_duration_payloads():
    fmt = _formatter()
    old = log_catalog.render(
        "automation.snoozed", {"minutes": 10}, "old fallback", fmt=fmt)
    new = log_catalog.render(
        "automation.snoozed", {"duration": 600}, "new fallback", fmt=fmt)
    assert old == new == "Snoozed for 10m."


@pytest.mark.parametrize(("count", "expected"), [
    (1, "Escaneo finalizado: 1 dispositivo encontrado."),
    (2, "Escaneo finalizado: 2 dispositivos encontrados."),
])
def test_scan_count_uses_the_spanish_plural_rule(count, expected):
    i18n.set_language("es")
    try:
        assert log_catalog.render(
            "scan.finished", {"count": count}, "fallback", fmt=_formatter()
        ) == expected
    finally:
        i18n.set_language(i18n.SYSTEM)
