"""Live session-bus smoke for the standalone CLI.

Run this file behind ``dbus-run-session --`` so it cannot touch a user's bus.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date

import pytest
from dbus_fast.aio import MessageBus
from dbus_fast.constants import PropertyAccess
from dbus_fast.service import ServiceInterface, dbus_property, method

from idasen_companion import DBUS_NAME, DBUS_PATH


class Desk(ServiceInterface):
    def __init__(self, calls: list[str]) -> None:
        super().__init__(f"{DBUS_NAME}.Desk1")
        self.calls = calls

    @dbus_property(access=PropertyAccess.READ)
    def Connected(self) -> "b":  # pylint: disable=invalid-name
        return True

    @dbus_property(access=PropertyAccess.READ)
    def Height(self) -> "d":  # pylint: disable=invalid-name
        return 1.10

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> "s":  # pylint: disable=invalid-name
        return "standing"

    @dbus_property(access=PropertyAccess.READ)
    def Moving(self) -> "b":  # pylint: disable=invalid-name
        return False

    @method()
    def Sit(self):  # pylint: disable=invalid-name
        self.calls.append("sit")

    @method()
    def Stop(self):  # pylint: disable=invalid-name
        self.calls.append("stop")


class Automation(ServiceInterface):
    def __init__(self) -> None:
        super().__init__(f"{DBUS_NAME}.Automation1")

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":  # pylint: disable=invalid-name
        return "active"

    @dbus_property(access=PropertyAccess.READ)
    def ActiveTime(self) -> "d":  # pylint: disable=invalid-name
        return 3900.0

    @dbus_property(access=PropertyAccess.READ)
    def TimeRemaining(self) -> "d":  # pylint: disable=invalid-name
        return 900.0

    @dbus_property(access=PropertyAccess.READ)
    def SnoozeUntil(self) -> "d":  # pylint: disable=invalid-name
        return 0.0


class Stats(ServiceInterface):
    def __init__(self) -> None:
        super().__init__(f"{DBUS_NAME}.Stats1")

    @method()
    def GetDaily(self, start: "s", end: "s") -> "s":  # pylint: disable=invalid-name
        assert start == end == date.today().isoformat()
        return json.dumps([[start, "standing", 3900.0]])


class Log(ServiceInterface):
    def __init__(self) -> None:
        super().__init__(f"{DBUS_NAME}.Log1")

    @method()
    def GetRecent(self) -> "s":  # pylint: disable=invalid-name
        return json.dumps([{
            "ts": 1_787_000_000.0,
            "level": "info",
            "channel": "activity",
            "msg_id": "daemon.stopping",
            "params": {},
            "text": "Daemon stopping.",
        }])


async def run_cli(config, *args: str) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "idasen_companion.cli",
        "--config", str(config), *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
    return process.returncode, stdout.decode(), stderr.decode()


@pytest.mark.asyncio
async def test_status_move_stop_log_shutdown_and_missing_owner(tmp_path):
    bus_address = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if "/tmp/dbus-" not in bus_address:
        pytest.skip(
            "requires the throwaway bus from: dbus-run-session -- pytest "
            "tests/test_cli_integration.py")

    config = tmp_path / "config.toml"
    config.write_text("[ui]\nlanguage = 'en'\nunits = 'cm'\nclock_format = '24'\n")
    calls: list[str] = []
    bus = await MessageBus().connect()
    for interface in (Desk(calls), Automation(), Stats(), Log()):
        bus.export(DBUS_PATH, interface)
    await bus.request_name(DBUS_NAME)

    code, stdout, stderr = await run_cli(config, "status")
    assert code == 0 and stderr == ""
    assert "Desk\n" in stdout and "110.0 cm" in stdout
    assert "Automation\n" in stdout and "Today\n" in stdout

    assert (await run_cli(config, "sit"))[0] == 0
    assert (await run_cli(config, "stop"))[0] == 0
    assert calls == ["sit", "stop"]

    code, stdout, stderr = await run_cli(config, "log", "--limit", "1")
    assert code == 0 and stderr == ""
    assert "Daemon stopping." in stdout

    bus.disconnect()
    await asyncio.sleep(0)
    code, _stdout, stderr = await run_cli(config, "status")
    assert code == 1
    assert "systemctl --user start idasen-companion.service" in stderr
    assert "Traceback" not in stderr
