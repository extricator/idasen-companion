"""The activity message catalog and its renderer (see docs/LOGGING.md)."""

import pytest

from idasen_companion.core import logmsg
from idasen_companion.core.logmsg import Channel, Message, Param, render

FORMATTERS = {
    Param.DURATION: lambda s: "N/A" if s is None else f"{s / 60:.1f} minutes",
    Param.HEIGHT: lambda h: "N/A" if h is None else f"{h:.4f}m",
    Param.STATE: lambda s: str(s),
    Param.TEXT: lambda t: "n/a" if t is None else str(t),
    Param.INT: lambda n: str(int(n)),
}


def _render(msg, **params):
    return render(msg, params, FORMATTERS)


def test_catalog_is_activity_only():
    # Diagnostic lines are free-form by policy; anything catalogued is
    # user-facing and therefore translatable.
    assert all(m.channel is Channel.ACTIVITY
               for m in logmsg.all_messages().values())


def test_ids_are_unique_and_match_their_key():
    catalog = logmsg.all_messages()
    assert all(key == msg.id for key, msg in catalog.items())


def test_every_template_placeholder_is_a_declared_param():
    """A `%(name)s` with no matching param renders as the raw template."""
    for msg in logmsg.all_messages().values():
        values = {name: "x" for name in msg.params}
        try:
            msg.text % values
        except KeyError as e:
            pytest.fail(f"{msg.id}: template uses undeclared param {e}")


def test_every_cycle_note_message_declares_next_target():
    for msg in logmsg.all_messages().values():
        if msg.cycle_note:
            assert "next_target" in msg.params, msg.id


def test_render_substitutes_raw_params():
    line = _render(logmsg.PRESET_SAVED, name="desk", height=1.1)
    assert line == "Preset 'desk' saved at 1.1000m."


def test_cycle_note_is_appended_from_the_target():
    line = _render(logmsg.PRESENCE_ACTIVE_RESET, next_target=25 * 60)
    assert line.endswith(" Next change after 25.0 minutes of active time.")


def test_cycle_note_is_omitted_when_nothing_is_scheduled():
    # target 0 means automation is off or the desk is held: the line must not
    # claim a change is coming.
    line = _render(logmsg.PRESENCE_ACTIVE_RESET, next_target=0)
    assert "Next change after" not in line


def test_fallback_note_replaces_the_cycle_note_when_unscheduled():
    line = _render(logmsg.CYCLE_MOVE_FAILED, intended="standing",
                   previous="sitting", next_target=0)
    assert line.endswith(" Will try again next cycle.")


def test_missing_param_renders_as_a_placeholder_not_an_exception():
    # Losing a line (and taking its caller down) is worse than a half-rendered
    # one, so render never raises.
    line = _render(logmsg.PRESET_SAVED, name="desk")
    assert "desk" in line


def test_unknown_id_lookup_returns_none():
    # An older GUI meeting a newer daemon's id falls back to the English text
    # the daemon sent, rather than crashing.
    assert logmsg.get("nope.not.here") is None


def test_height_and_state_use_their_own_formatters():
    line = _render(logmsg.CYCLE_SYNCED, previous="sitting", current="standing",
                   height=1.1234, next_target=0)
    assert "'sitting'" in line and "'standing'" in line and "1.1234m" in line


def test_percent_literals_survive_rendering():
    msg = Message(id="t.pct", level="info", text="100%% done: %(what)s",
                  params={"what": Param.TEXT})
    assert _render(msg, what="ok") == "100% done: ok"


def test_state_values_render_as_wire_strings_not_repr():
    """DeskState/Status are StrEnum, not `str, Enum`. Under the latter
    `str(DeskState.SITTING)` is "DeskState.SITTING", so a single missed
    `.value` — there are ~20 hand-written ones in daemon/main.py — put a
    Python repr into the journal *and* into the translated Activity Log,
    because gui/log_catalog's `_state` falls through to `str(value)` for
    anything it does not recognize. Nothing caught that.
    """
    from idasen_companion.core.machine import DeskState, Status

    for member in list(DeskState) + list(Status):
        assert str(member) == member.value
        assert f"{member}" == member.value
        assert "%s" % member == member.value
        assert "." not in str(member) or "-" in member.value


def test_a_state_param_renders_the_same_with_or_without_dot_value():
    """The invariant the ~20 `.value` calls were upholding by hand."""
    from idasen_companion.core.machine import DeskState

    fmt = logmsg.ENGLISH_FORMATTERS[logmsg.Param.STATE]
    assert fmt(DeskState.STANDING) == fmt(DeskState.STANDING.value) == "standing"
