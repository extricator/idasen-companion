"""Decoded boundary behavior, including historical and extended records."""

from idasen_companion.core.decoded_data import (
    DailyStatRow, TransitionRow, decode_daily_rows, decode_transition_rows,
)


def test_daily_rows_keep_supported_values_and_recover_per_row():
    assert decode_daily_rows([
        [" not-a-date ", " Custom STATE ", "-2.5", "future field"],
        None, ["day", "short"],
        ["day", "bad", None], ["day", "bad", "n/a"],
        ["day", "bad", float("nan")], ["day", "bad", 10 ** 1000],
        [0, "", 0], ["end", 12, True],
    ]) == [DailyStatRow(" not-a-date ", " Custom STATE ", -2.5),
           DailyStatRow("0", "", 0.0), DailyStatRow("end", "12", 1.0)]
    assert decode_daily_rows({"day": "wrong envelope"}) == []


def test_transition_rows_require_renderable_time_and_keep_open_text():
    assert decode_transition_rows([
        ["-1", " Custom ", "", " Future trigger ", 0, "extra"],
        None, [0, "short"],
        [None, "a", "b", "t", False], ["bad", "a", "b", "t", False],
        [float("inf"), "a", "b", "t", False],
        [1e100, "a", "b", "t", False],
        [0, 1, 2, 3, "nonempty"],
    ]) == [TransitionRow(-1.0, " Custom ", "", " Future trigger ", False),
           TransitionRow(0.0, "1", "2", "3", True)]
    assert decode_transition_rows(None) == []


def _statistics_client(replies):
    """Use the real client JSON adapter with only the bus transport replaced."""
    from types import MethodType, SimpleNamespace

    import pytest
    pytest.importorskip("PySide6")
    from PySide6.QtDBus import QDBusMessage
    from idasen_companion.gui.dbus_client import DaemonClient

    client = SimpleNamespace()
    client._call_for_json = MethodType(DaemonClient._call_for_json, client)

    def reply(member, *_args):
        arguments = replies[member]
        return SimpleNamespace(
            type=lambda: (QDBusMessage.MessageType.ErrorMessage if arguments is None
                          else QDBusMessage.MessageType.ReplyMessage),
            arguments=lambda: arguments,
        )

    client._iface = lambda _iface: SimpleNamespace(call=reply)
    client.get_daily_stats = MethodType(DaemonClient.get_daily_stats, client)
    client.get_transitions = MethodType(DaemonClient.get_transitions, client)
    return client


def test_gui_statistics_reply_failures_are_empty():
    replies = {"GetDaily": ["invalid JSON"], "GetTransitions": [123]}
    client = _statistics_client(replies)
    assert client.get_daily_stats("start", "end") == []
    assert client.get_transitions() == []
    # Valid JSON with a non-row envelope, a transport error, and a reply with
    # no arguments are distinct ways the boundary can have nothing to show.
    replies.update(GetDaily=['{"unexpected": 1}'], GetTransitions=None)
    assert client.get_daily_stats("start", "end") == []
    assert client.get_transitions() == []
    replies.update(GetDaily=[], GetTransitions=["null"])
    assert client.get_daily_stats("start", "end") == []
    assert client.get_transitions() == []


def test_gui_statistics_decode_mixed_rows_with_appended_fields():
    import json

    client = _statistics_client({
        "GetDaily": [json.dumps([
            ["raw day", " Custom ", -2, "extra"], None,
            ["raw day", "bad", "not seconds"], ["end", "", 0],
        ])],
        "GetTransitions": [json.dumps([
            [0, "", " Custom ", " Unknown ", True, "extra"],
            ["not a timestamp", "a", "b", "t", False],
            [-1, "last", "", "", False],
        ])],
    })
    assert client.get_daily_stats("start", "end") == [
        DailyStatRow("raw day", " Custom ", -2.0), DailyStatRow("end", "", 0.0),
    ]
    assert client.get_transitions(50) == [
        TransitionRow(0.0, "", " Custom ", " Unknown ", True),
        TransitionRow(-1.0, "last", "", "", False),
    ]
