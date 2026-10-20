"""Decoded boundary behavior, including historical and extended records."""

from idasen_companion.core.decoded_data import (
    DailyStatRow, TransitionRow, decode_daily_rows, decode_transition_rows,
)


def test_daily_rows_keep_supported_values_and_recover_per_row():
    assert decode_daily_rows([
        [" not-a-date ", " Custom STATE ", "-2.5", "future field"],
        None, "bad", {}, [], ["day", "short"],
        ["day", "bad", None], ["day", "bad", "n/a"],
        ["day", "bad", float("nan")], ["day", "bad", float("inf")],
        [0, "", 0], ["end", 12, True],
    ]) == [DailyStatRow(" not-a-date ", " Custom STATE ", -2.5),
           DailyStatRow("0", "", 0.0), DailyStatRow("end", "12", 1.0)]
    assert decode_daily_rows({"day": "wrong envelope"}) == []


def test_transition_rows_require_renderable_time_and_keep_open_text():
    assert decode_transition_rows([
        ["-1", " Custom ", "", " Future trigger ", 0, "extra"],
        None, "bad", {}, [], [0, "short"],
        [None, "a", "b", "t", False], ["bad", "a", "b", "t", False],
        [float("nan"), "a", "b", "t", False],
        [float("inf"), "a", "b", "t", False],
        [1e100, "a", "b", "t", False],
        [0, 1, 2, 3, "nonempty"],
    ]) == [TransitionRow(-1.0, " Custom ", "", " Future trigger ", False),
           TransitionRow(0.0, "1", "2", "3", True)]
    assert decode_transition_rows(None) == []
