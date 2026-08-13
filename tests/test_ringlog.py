import json

from idasen_companion.core import logmsg
from idasen_companion.daemon.ringlog import RingLog


def _ring(**kwargs):
    # Journal writes are stubbed globally (tests/conftest.py).
    return RingLog(**kwargs)


def test_entries_kept_in_order_with_timestamps():
    clock_value = [100.0]
    ring = _ring(maxlen=3, clock=lambda: clock_value[0])
    ring.emit(logmsg.AUTOMATION_PAUSED)
    clock_value[0] = 101.0
    ring.diag("warning", "two")
    stamps = [(e.ts, e.level, e.text) for e in ring.entries()]
    assert stamps == [(100.0, "info", "Automation paused."),
                      (101.0, "warning", "two")]


def test_ring_buffer_drops_oldest():
    ring = _ring(maxlen=2, clock=lambda: 0.0)
    for name in "abc":
        ring.diag("info", name)
    assert [e.text for e in ring.entries()] == ["b", "c"]


def test_on_entry_callback_fires():
    seen = []
    ring = _ring(clock=lambda: 5.0)
    ring.on_entry = seen.append
    ring.diag("error", "boom")
    assert [(e.ts, e.level, e.channel, e.text) for e in seen] == [
        (5.0, "error", "diagnostic", "boom")]


def test_emit_carries_the_id_and_raw_params():
    """The GUI renders from these, so they must survive unformatted."""
    ring = _ring(clock=lambda: 0.0)
    ring.emit(logmsg.PRESET_SAVED, name="desk", height=1.1)
    entry = ring.entries()[0]
    assert entry.msg_id == "preset.saved"
    assert entry.params == {"name": "desk", "height": 1.1}
    assert entry.channel == "activity"
    assert entry.text == "Preset 'desk' saved at 1.1000m."


def test_emit_takes_its_level_from_the_catalog():
    ring = _ring(clock=lambda: 0.0)
    ring.emit(logmsg.CYCLE_SYNC_FAILED)
    assert ring.entries()[0].level == "warning"


def test_diag_lines_carry_no_message_id():
    # Diagnostic lines are free-form English by policy — never translated,
    # so never catalogued.
    ring = _ring(clock=lambda: 0.0)
    ring.diag("debug", "BLE: connect attempt 1 failed")
    entry = ring.entries()[0]
    assert entry.msg_id == "" and entry.params == {}
    assert entry.channel == "diagnostic"


def test_entry_serializes_for_the_wire():
    ring = _ring(clock=lambda: 7.0)
    ring.emit(logmsg.AUTOMATION_SNOOZED, minutes=5)
    assert ring.entries()[0].as_dict() == {
        "ts": 7.0, "level": "info", "channel": "activity",
        "msg_id": "automation.snoozed", "params": {"minutes": 5},
        "text": "Snoozed for 5 minutes."}


def test_unserializable_params_never_escape_the_ring():
    """The text is already rendered, so a value the wire can't carry costs the
    line its parameters — not an exception raised into the config reload or the
    move that was being logged. Every consumer downstream dumps this unguarded.
    """
    ring = _ring(clock=lambda: 0.0)
    ring.emit(logmsg.AUTOMATION_SNOOZED, minutes=object())
    entry = ring.entries()[0]
    assert entry.params == {}
    assert json.dumps(entry.as_dict())  # what GetRecent does
