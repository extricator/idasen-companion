"""Qt-free command-line front end for the Idasen Companion daemon."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError

from . import DBUS_NAME, DBUS_PATH, __version__
from .core import activity_log, i18n
from .core.clock_format import ClockSetting, resolve_clock_style
from .core.config import (
    AppConfig, ConfigError, DEFAULT_CONFIG_PATH, format_config_warning,
    load_config,
)
from .core.locale_profile import LocaleProfile, resolve_app_locale
from .core.presentation import daemon_errors
from .core.presentation.formatter import Formatter, PresentationContext
from .core.presentation.gettext_translator import GettextTranslator
from .core.units import UnitSetting, resolve_height_unit

IFACE_DESK = f"{DBUS_NAME}.Desk1"
IFACE_AUTO = f"{DBUS_NAME}.Automation1"
IFACE_PRESETS = f"{DBUS_NAME}.Presets1"
IFACE_STATS = f"{DBUS_NAME}.Stats1"
IFACE_LOG = f"{DBUS_NAME}.Log1"

class Client(Protocol):
    """The narrow daemon surface consumed by command dispatch."""

    async def properties(self, interface: str, names: tuple[str, ...]) -> dict[str, Any]: ...
    async def call(self, interface: str, member: str, *args: object) -> object: ...
    def close(self) -> None: ...


class DaemonClient:
    """High-level dbus-fast proxy for the daemon's existing interfaces."""

    def __init__(self, bus: MessageBus, proxy: Any) -> None:
        self._bus = bus
        self._proxy = proxy

    @classmethod
    async def connect(cls) -> DaemonClient:
        bus = await MessageBus().connect()
        try:
            introspection = await bus.introspect(DBUS_NAME, DBUS_PATH)
            proxy = bus.get_proxy_object(DBUS_NAME, DBUS_PATH, introspection)
        except BaseException:
            bus.disconnect()
            raise
        return cls(bus, proxy)

    async def properties(self, interface: str,
                         names: tuple[str, ...]) -> dict[str, Any]:
        proxy_interface = self._proxy.get_interface(interface)
        values = await asyncio.gather(*(
            getattr(proxy_interface, f"get_{_snake(name)}")() for name in names
        ))
        return dict(zip(names, values))

    async def call(self, interface: str, member: str, *args: object) -> object:
        proxy_interface = self._proxy.get_interface(interface)
        return await getattr(proxy_interface, f"call_{_snake(member)}")(*args)

    def close(self) -> None:
        self._bus.disconnect()


def _snake(name: str) -> str:
    """PascalCase D-Bus member name to dbus-fast proxy attribute suffix."""
    result = []
    for index, character in enumerate(name):
        if character.isupper() and index:
            result.append("_")
        result.append(character.lower())
    return "".join(result)


@dataclass(frozen=True)
class StatusSnapshot:
    connected: bool
    height: float
    position: str
    moving: bool
    status: str
    active_time: float
    time_remaining: float
    snooze_until: float
    daily: tuple[tuple[str, str, float], ...]


def _formatter(config: AppConfig) -> Formatter:
    locale_name = resolve_app_locale(config.ui.language, os.environ)
    locale = LocaleProfile(locale_name)
    unit = resolve_height_unit(
        UnitSetting(config.ui.units), language=config.ui.language,
        environ=os.environ)
    time_style = resolve_clock_style(
        ClockSetting(config.ui.clock_format), language=config.ui.language,
        environ=os.environ)
    return Formatter(PresentationContext(
        locale=locale, translator=GettextTranslator(), unit=unit,
        time_style=time_style))


async def _read_status(client: Client) -> StatusSnapshot:
    desk, automation = await asyncio.gather(
        client.properties(IFACE_DESK, ("Connected", "Height", "Position", "Moving")),
        client.properties(IFACE_AUTO, (
            "Status", "ActiveTime", "TimeRemaining", "SnoozeUntil")),
    )
    today = date.today().isoformat()
    rows = _json_rows(await client.call(IFACE_STATS, "GetDaily", today, today))
    daily = tuple(
        (str(row[0]), str(row[1]), float(row[2]))
        for row in rows if isinstance(row, (list, tuple)) and len(row) >= 3)
    return StatusSnapshot(
        connected=bool(desk["Connected"]), height=float(desk["Height"]),
        position=str(desk["Position"]), moving=bool(desk["Moving"]),
        status=str(automation["Status"]),
        active_time=float(automation["ActiveTime"]),
        time_remaining=float(automation["TimeRemaining"]),
        snooze_until=float(automation["SnoozeUntil"]), daily=daily)


def _json_rows(payload: object) -> list:
    if not isinstance(payload, str):
        raise ValueError("D-Bus reply was not JSON text")
    decoded = json.loads(payload)
    if not isinstance(decoded, list):
        raise ValueError("D-Bus reply was not a JSON list")
    return decoded


def _status_text(snapshot: StatusSnapshot, fmt: Formatter, *,
                 persistent_connection: bool) -> str:
    position = fmt.position_or_custom(snapshot.position)
    if snapshot.moving:
        position = i18n.pgettext("cli.status", "%(position)s (moving)") % {
            "position": position}
    if snapshot.connected:
        connection = i18n.pgettext("cli.status", "Connected")
    elif persistent_connection:
        connection = i18n.pgettext("cli.status", "Disconnected")
    else:
        connection = i18n.pgettext("cli.status", "On demand")
    desk_values = {
        "height": (fmt.height(snapshot.height) if snapshot.height else
                   i18n.pgettext("cli.status", "Unavailable")),
        "position": position,
        "connection": connection,
    }

    status = fmt.status_label(snapshot.status)
    elapsed = fmt.duration(snapshot.active_time)
    if snapshot.status == "snoozed" and snapshot.snooze_until:
        next_change = fmt.snooze_line(
            fmt.clock(datetime.fromtimestamp(snapshot.snooze_until)))
    elif snapshot.time_remaining <= 0:
        next_change = fmt.due_now_label()
    elif snapshot.position == "sitting":
        next_change = i18n.pgettext(
            "cli.status", "Standing up in %(duration)s") % {
            "duration": fmt.duration(snapshot.time_remaining)}
    elif snapshot.position == "standing":
        next_change = i18n.pgettext(
            "cli.status", "Sitting down in %(duration)s") % {
            "duration": fmt.duration(snapshot.time_remaining)}
    else:
        next_change = i18n.pgettext("cli.status", "%(duration)s left") % {
            "duration": fmt.duration(snapshot.time_remaining)}

    totals = {"sitting": 0.0, "standing": 0.0}
    for _day, state, seconds in snapshot.daily:
        if state in totals:
            totals[state] += seconds
    return "\n".join((
        i18n.pgettext("cli.status", "Desk"),
        i18n.pgettext("cli.status", "  Height: %(height)s") % desk_values,
        i18n.pgettext("cli.status", "  Position: %(position)s") % desk_values,
        i18n.pgettext("cli.status", "  Connection: %(connection)s") % desk_values,
        "",
        i18n.pgettext("cli.status", "Automation"),
        i18n.pgettext("cli.status", "  Status: %(status)s") % {
            "status": status},
        i18n.pgettext("cli.status", "  Elapsed: %(duration)s") % {
            "duration": elapsed},
        i18n.pgettext("cli.status", "  Next: %(next)s") % {
            "next": next_change},
        "",
        i18n.pgettext("cli.status", "Today"),
        i18n.pgettext("cli.status", "  Sitting: %(duration)s") % {
            "duration": fmt.duration_hm(totals["sitting"])},
        i18n.pgettext("cli.status", "  Standing: %(duration)s") % {
            "duration": fmt.duration_hm(totals["standing"])},
    ))


def _log_text(rows: list, fmt: Formatter, limit: int | None) -> str:
    selected = rows[-limit:] if limit is not None else rows
    lines = []
    for row in selected:
        if not isinstance(row, dict):
            raise ValueError("activity log entry was not an object")
        timestamp = datetime.fromtimestamp(float(row.get("ts", 0.0)))
        params = row.get("params", {})
        if not isinstance(params, dict):
            params = {}
        message = activity_log.render(
            str(row.get("msg_id", "")), params, str(row.get("text", "")),
            fmt=fmt)
        lines.append(i18n.pgettext("cli.log", "%(when)s  %(message)s") % {
            "when": fmt.day_and_clock(timestamp), "message": message})
    return "\n".join(lines)


async def _dispatch(args: argparse.Namespace, config: AppConfig,
                    client: Client) -> str:
    fmt = _formatter(config)
    if args.command == "status":
        return _status_text(
            await _read_status(client), fmt,
            persistent_connection=config.desk.connection == "persistent")
    if args.command == "log":
        rows = _json_rows(await client.call(IFACE_LOG, "GetRecent"))
        return _log_text(rows, fmt, args.limit)
    commands = {
        "sit": (IFACE_DESK, "Sit", ()),
        "stand": (IFACE_DESK, "Stand", ()),
        "toggle": (IFACE_DESK, "Toggle", ()),
        "stop": (IFACE_DESK, "Stop", ()),
    }
    interface, member, values = (commands[args.command]
                                 if args.command != "preset"
                                 else (IFACE_DESK, "MoveToPreset", (args.name,)))
    await client.call(interface, member, *values)
    return ""


def _positive(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="idasen-companion-cli",
        description="Control and inspect the Idasen Companion daemon.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH,
                        help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show desk, automation and today's totals")
    for name in ("sit", "stand", "toggle", "stop"):
        commands.add_parser(name, help=f"send the {name} command")
    preset = commands.add_parser("preset", help="move to a named preset")
    preset.add_argument("name", metavar="NAME")
    log = commands.add_parser("log", help="show the daemon's recent activity")
    log.add_argument("--limit", type=_positive, metavar="N")
    return parser


async def _run(args: argparse.Namespace, config: AppConfig,
               client: Client | None = None) -> str:
    owned = client is None
    active_client = client or await DaemonClient.connect()
    try:
        return await _dispatch(args, config, active_client)
    finally:
        if owned:
            active_client.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        i18n.set_language(config.ui.language)
        for warning in config.warnings:
            print(format_config_warning(warning), file=sys.stderr)
        output = asyncio.run(_run(args, config))
    except ConfigError as error:
        print(i18n.pgettext("cli.error", "Invalid configuration: %(detail)s") % {
            "detail": error}, file=sys.stderr)
        return 1
    except (DBusError, ConnectionError, OSError, RuntimeError, ValueError,
            json.JSONDecodeError) as error:
        name = getattr(error, "type", "")
        detail = str(error)
        if isinstance(error, DBusError):
            detail = daemon_errors.daemon_error_message(
                GettextTranslator(), name, detail)
        message = i18n.pgettext(
            "cli.error",
            "Could not contact the Idasen Companion daemon: %(detail)s\n"
            "Start it with: systemctl --user start idasen-companion.service")
        print(message % {"detail": detail}, file=sys.stderr)
        return 1
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
