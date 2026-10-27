# SPDX-License-Identifier: GPL-3.0-or-later
"""Command and rendering contract for the Qt-free CLI."""

from __future__ import annotations

import json
from datetime import date

import pytest

from idasen_companion import cli
from idasen_companion.core import i18n
from idasen_companion.core.config import load_config, save_config
from idasen_companion.core.decoded_data import DailyStatRow


class FakeClient:
    def __init__(self, *, status: str = "active",
                 position: str = "standing") -> None:
        self.calls: list[tuple[str, str, tuple[object, ...]]] = []
        self.closed = False
        self.status = status
        self.position = position

    async def properties(self, interface: str,
                         names: tuple[str, ...]) -> dict[str, object]:
        values = {
            "Connected": True,
            "Height": 1.10,
            "Position": self.position,
            "Moving": False,
            "Status": self.status,
            "ActiveTime": 3900.0,
            "TimeRemaining": 1020.0,
            "SnoozeUntil": 0.0,
        }
        return {name: values[name] for name in names}

    async def call(self, interface: str, member: str,
                   *args: object) -> object:
        self.calls.append((interface, member, args))
        if member == "GetDaily":
            today = date.today().isoformat()
            return json.dumps([
                [today, "sitting", 7200.0],
                [today, "standing", 3900.0],
            ])
        if member == "GetRecent":
            return json.dumps([
                {"ts": 1_787_000_000.0, "level": "info",
                 "channel": "activity", "msg_id": "daemon.stopping",
                 "params": {}, "text": "Daemon stopping."},
                {"ts": 1_787_000_001.0, "level": "warning",
                 "channel": "diagnostic", "msg_id": "",
                 "params": {}, "text": "BLE diagnostic"},
            ])
        return None

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_status_has_the_three_settled_sections_and_shared_values():
    args = cli.build_parser().parse_args(["status"])
    output = await cli._dispatch(args, load_config(), FakeClient())
    assert output.splitlines()[0] == "Desk"
    assert "Automation" in output.splitlines()
    assert "Today" in output.splitlines()
    assert "110.0 cm" in output
    assert "Standing" in output
    assert "  Status: Automation active" in output.splitlines()
    assert "1h 05m" in output
    assert "Sitting down in 17m" in output
    assert "2h 00m" in output


@pytest.mark.asyncio
async def test_status_decodes_named_daily_rows_and_keeps_valid_neighbors(monkeypatch):
    client = FakeClient()

    async def call(*_args):
        return json.dumps([
            ["raw day", "sitting", "3600", "extra"], None,
            ["day", "standing", "bad"], ["day", "short"],
            ["day", " Future ", -1], ["day", "standing", 0],
        ])

    monkeypatch.setattr(client, "call", call)
    snapshot = await cli._read_status(client)
    assert snapshot.daily == (
        DailyStatRow("raw day", "sitting", 3600.0),
        DailyStatRow("day", " Future ", -1.0), DailyStatRow("day", "standing", 0.0),
    )
    assert snapshot.daily[0].seconds == 3600.0
    output = cli._status_text(snapshot, cli._formatter(load_config()),
                              persistent_connection=True)
    assert "  Sitting: 1h 00m" in output.splitlines()
    assert "  Standing: 0m" in output.splitlines()


@pytest.mark.asyncio
async def test_status_uses_the_selected_spanish_catalog():
    config = load_config()
    config.ui.language = "es"
    i18n.set_language("es")
    try:
        output = await cli._dispatch(
            cli.build_parser().parse_args(["status"]), config, FakeClient())
    finally:
        i18n.set_language(i18n.SYSTEM)
    assert output.startswith("Escritorio\n")
    assert "Automatización\n" in output
    assert "Hoy\n" in output
    assert "Altura: 110,0 cm" in output
    assert "  Posición: De pie" in output.splitlines()
    assert "  Estado: Automatización activa" in output.splitlines()


@pytest.mark.parametrize(
    ("status", "position", "status_line", "position_line"),
    [
        ("future-MODE ", "focus-SPOT", "  Status: future-MODE ",
         "  Position: Focus-spot"),
        ("", "", "  Status: ", "  Position: Custom"),
    ],
)
def test_status_command_preserves_open_values(
    tmp_path, monkeypatch, capsys, status, position, status_line, position_line,
):
    path = tmp_path / "config.toml"
    path.write_text("[ui]\nlanguage = 'en'\n")
    client = FakeClient(status=status, position=position)

    async def connect():
        return client

    monkeypatch.setattr(cli.DaemonClient, "connect", connect)
    try:
        assert cli.main(["--config", str(path), "status"]) == 0
    finally:
        i18n.set_language(i18n.SYSTEM)
    captured = capsys.readouterr()
    assert captured.err == ""
    assert status_line in captured.out.splitlines()
    assert position_line in captured.out.splitlines()
    assert "  Next: 17m left" in captured.out.splitlines()
    assert client.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("argv", "member", "values"),
    [
        (["sit"], "GestureMove", ("sit",)),
        (["stand"], "GestureMove", ("stand",)),
        (["toggle"], "GestureMove", ("toggle",)),
        (["stop"], "Stop", ()),
        (["preset", "focus"], "MoveToPreset", ("focus",)),
    ],
)
async def test_write_commands_map_to_existing_desk_methods(argv, member, values):
    client = FakeClient()
    args = cli.build_parser().parse_args(argv)
    assert await cli._dispatch(args, load_config(), client) == ""
    assert client.calls == [(cli.IFACE_DESK, member, values)]


@pytest.mark.asyncio
async def test_log_limit_is_client_side_and_unknown_text_falls_back():
    client = FakeClient()
    args = cli.build_parser().parse_args(["log", "--limit", "1"])
    output = await cli._dispatch(args, load_config(), client)
    assert output.endswith("BLE diagnostic")
    assert "Daemon stopping" not in output
    assert client.calls == [(cli.IFACE_LOG, "GetRecent", ())]


@pytest.mark.parametrize(("payload", "detail"), [
    (123, "D-Bus reply was not JSON text"),
    ('{"unexpected": []}', "D-Bus reply was not a JSON list"),
])
def test_log_envelope_errors_keep_exit_one_and_exact_detail(
    tmp_path, monkeypatch, capsys, payload, detail,
):
    path = tmp_path / "config.toml"
    path.write_text("[ui]\nlanguage = 'en'\n")
    client = FakeClient()

    async def call(*_args):
        return payload

    async def connect():
        return client

    monkeypatch.setattr(client, "call", call)
    monkeypatch.setattr(cli.DaemonClient, "connect", connect)
    try:
        assert cli.main(["--config", str(path), "log"]) == 1
    finally:
        i18n.set_language(i18n.SYSTEM)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert detail in captured.err
    assert "Traceback" not in captured.err
    assert client.closed


@pytest.mark.parametrize("argv", [[], ["preset"], ["log", "--limit", "0"]])
def test_usage_errors_keep_argparses_exit_code_two(argv):
    with pytest.raises(SystemExit) as raised:
        cli.build_parser().parse_args(argv)
    assert raised.value.code == 2


def test_unknown_config_is_visible_nonfatal_and_survives_known_save(
    tmp_path, monkeypatch, capsys,
):
    path = tmp_path / "config.toml"
    path.write_text(
        "[ui]\nunits = 'cm'\nfuture_option = true\n\n"
        "[future]\nmode = 'careful'\n")
    client = FakeClient()

    async def connect():
        return client

    monkeypatch.setattr(cli.DaemonClient, "connect", connect)
    assert cli.main(["--config", str(path), "status"]) == 0
    captured = capsys.readouterr()
    assert "unknown option [ui] future_option" in captured.err
    assert "unknown section [future]" in captured.err
    assert captured.out.startswith("Desk\n")
    assert client.closed

    config = load_config(path)
    config.ui.units = "in"
    save_config(config, path)
    saved = path.read_text()
    assert "future_option = true" in saved
    assert "[future]" in saved and "mode = 'careful'" in saved


def test_malformed_config_is_exit_one_without_traceback(tmp_path, capsys):
    path = tmp_path / "config.toml"
    path.write_text("[ui]\nunits = 7\n")
    assert cli.main(["--config", str(path), "status"]) == 1
    captured = capsys.readouterr()
    assert "Invalid configuration" in captured.err
    assert "Traceback" not in captured.err


def test_daemon_absence_is_exit_one_without_traceback(monkeypatch, capsys):
    async def connect():
        raise ConnectionError("no session bus owner")

    monkeypatch.setattr(cli.DaemonClient, "connect", connect)
    assert cli.main(["status"]) == 1
    captured = capsys.readouterr()
    assert "no session bus owner" in captured.err
    assert "systemctl --user start" in captured.err
    assert "Traceback" not in captured.err
