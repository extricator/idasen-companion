"""Configuration model, loading, validation, and saving.

The config lives at ``~/.config/idasen-companion/config.toml``. Reading
uses stdlib ``tomllib``; writing uses ``tomlkit`` so user comments and
formatting survive round-trips. Durations are stored in the file as
compact strings ("45m") and held in memory as integer seconds.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .durations import format_duration_compact, parse_duration
from .units import UnitSetting

DEFAULT_CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
) / "idasen-companion"
# IDASEN_COMPANION_CONFIG overrides the path (used by tests/dev runs).
DEFAULT_CONFIG_PATH = Path(
    os.environ.get("IDASEN_COMPANION_CONFIG", DEFAULT_CONFIG_DIR / "config.toml")
)

# Reference script fallbacks, preserved verbatim.
FALLBACK_PRESETS = {"sit": 0.62, "stand": 1.10}

VALID_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
VALID_CONNECTION_MODES = ("on-demand", "persistent")
# What automation does when a sync finds the desk was moved off sit/stand
# (physical panel or another BLE client). "yield" leaves it where the user
# put it and pauses until it returns to a cycle preset; "adopt" classifies
# to the nearer preset and keeps cycling (the pre-2026-07 behaviour).
VALID_EXTERNAL_POLICIES = ("yield", "adopt")
# What happens when a scheduled move is cut short (the paddle, an obstruction).
# "undo" returns the desk to the height the move started from, "leave" accepts
# where it stopped, "retry" re-issues the move toward the target. Recovery is
# attempted exactly once either way. Was the bool return_to_start_on_interruption
# (True = undo, False = leave); both it and its own predecessor
# retry_on_interruption are still accepted on load.
VALID_INTERRUPTION_POLICIES = ("undo", "leave", "retry")
# GUI window/tray behaviour (only meaningful when a system tray exists).
# The action a tray-icon gesture performs: open the window, flip sit/stand,
# go to sit or stand, or nothing.
VALID_TRAY_ACTIONS = ("window", "toggle", "sit", "stand", "none")
# What repeating a move gesture does while the desk is still moving: nothing,
# stop it where it is, or send it back to the height the move started from.
VALID_TRAY_REPEAT = ("off", "stop", "reverse")
# close_action: what the window's close button does when a tray exists.
# "tray" hides to the tray (keep running); "quit" exits the whole app.
VALID_CLOSE_ACTIONS = ("tray", "quit")
# units: how the GUI shows heights. A display setting only — heights are
# metres in this config, in the state machine, in the stats DB and on the
# D-Bus wire, whatever this says. "system" derives the unit from the desktop
# locale (see gui/util.resolve_height_unit); "cm" and "in" pin it.
# Derived from UnitSetting rather than restated as three strings, so the
# validator and the type cannot drift apart; its value and order are the
# same three strings this held before ("system", "cm", "in") and reach the
# validation message _require_choice below builds.
VALID_UNITS = tuple(member.value for member in UnitSetting)

# Physical limits of the Idåsen desk (from the Linak controller).
MIN_HEIGHT = 0.62
MAX_HEIGHT = 1.27


class ConfigError(Exception):
    """Raised when the configuration file is invalid."""


@dataclass
class DeskConfig:
    mac: str = ""
    connection: str = "on-demand"
    linger: int = 15  # seconds to stay connected after the last operation


@dataclass
class AutomationConfig:
    # Master switch for the sit/stand cycle. Off means the app is a manual
    # desk remote: presets, manual moves and stats all keep working, only the
    # timer stops. Distinct from the transient Pause (D-Bus, lost on restart)
    # — this is a durable preference.
    enabled: bool = True
    sit_duration: int = 45 * 60
    stand_duration: int = 25 * 60
    sit_variation: int = 10 * 60  # add 0..N random whole minutes per sitting cycle
    stand_variation: int = 5 * 60
    check_interval: int = 60
    idle_threshold: int = 10 * 60  # lenient: gates active-time accounting
    recent_input_threshold: int = 3 * 60  # strict: gates desk movement
    sync_interval: int = 5 * 60  # periodic height sync (reference: --log-interval); 0 = off
    # See VALID_INTERRUPTION_POLICIES. Default "undo": a move you cut short
    # puts the desk back where it was rather than parking it mid-travel.
    interruption_policy: str = "undo"
    # See VALID_EXTERNAL_POLICIES. Default "yield": respect a manual move to
    # an off-cycle position rather than cycling away from it.
    external_move_policy: str = "yield"


@dataclass
class ScheduleConfig:
    enabled: bool = False
    days: list[str] = field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])
    start: str = "09:00"
    end: str = "17:00"


@dataclass
class NotificationsConfig:
    enabled: bool = True
    lead_time: int = 30
    # Notices about faults the app cannot fix on its own — today only a failed
    # move. Kept apart from `enabled`, which announces what automation is
    # *doing*: someone who switched the announcements off has not asked to stop
    # hearing that the desk didn't move. A SyncFailed deliberately stays a log
    # line either way — it fires on every routine position check, so a desk
    # left switched off would notify all afternoon.
    problems: bool = True


@dataclass
class AdvancedConfig:
    movement_tolerance: float = 0.02  # interruption detection tolerance vs preset target


@dataclass
class UiConfig:
    # "system" follows the desktop locale; otherwise a catalog code like "es".
    # Both the GUI (Qt) and the daemon's notifications honor this. Applied at
    # startup — the GUI bakes strings at construction, so a change needs a
    # relaunch to fully take effect.
    language: str = "system"
    # See VALID_UNITS. The unit heights are *shown* in; nothing stored or sent
    # changes with it. "system" follows the locale's measurement system, which
    # is a first guess rather than an answer — plenty of people in metric
    # countries think about a desk in inches, and the reverse — so the two
    # explicit values exist to override it for good.
    #
    # Stays str, not UnitSetting: this attribute name is the TOML key
    # (_apply_section resolves it with hasattr/getattr straight from
    # tomllib), and the tomlkit write path in save_config below writes
    # whatever this holds verbatim, so a StrEnum instance must never reach
    # it. Coercion to UnitSetting happens at the point of use instead — the
    # boundary core/units.py's resolve_height_unit sits behind.
    units: str = "system"
    # Window/tray behaviour. All of these only bite when a system tray exists;
    # with no tray the window always shows and closing it exits (see gui/main).
    # What each tray-icon gesture does (see VALID_TRAY_ACTIONS). Left-click
    # defaults to opening the window (least surprising). Double-click has no
    # entry on purpose: StatusNotifierItem trays (KDE, GNOME, most modern
    # Linux) don't deliver a double-click, so the action can never fire.
    tray_left_click: str = "window"
    tray_middle_click: str = "toggle"
    # See VALID_TRAY_REPEAT: repeating a move gesture while the desk is still
    # moving stops it (default), reverses it to the start, or does nothing.
    tray_repeat_move: str = "stop"
    # See VALID_CLOSE_ACTIONS: what the window close button does with a tray.
    close_action: str = "tray"
    # Hide to the tray when the window is minimised (not only when closed).
    minimize_to_tray: bool = False
    # Start with the window hidden to the tray (True) instead of shown (False).
    start_minimized: bool = True
    # Whether the user has asked the Flatpak Background portal to autostart
    # the daemon at login. This is the source of truth for that toggle
    # because the portal has no method to read a grant back — unlike the
    # systemd unit, which is asked directly on every read — so the app has to
    # remember what it last asked for and re-assert it once at GUI startup.
    # Unused under the RPM: systemd's own unit state is authoritative there.
    run_at_login: bool = False


@dataclass
class AppConfig:
    desk: DeskConfig = field(default_factory=DeskConfig)
    automation: AutomationConfig = field(default_factory=AutomationConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    presets: dict[str, float] = field(default_factory=lambda: dict(FALLBACK_PRESETS))


_DURATION_FIELDS = {
    ("desk", "linger"),
    ("automation", "sit_duration"),
    ("automation", "stand_duration"),
    ("automation", "sit_variation"),
    ("automation", "stand_variation"),
    ("automation", "check_interval"),
    ("automation", "idle_threshold"),
    ("automation", "recent_input_threshold"),
    ("automation", "sync_interval"),
    ("notifications", "lead_time"),
}


def _apply_section(target, section_name: str, data: dict) -> None:
    for toml_key, value in data.items():
        if not hasattr(target, toml_key):
            raise ConfigError(f"unknown option [{section_name}] {toml_key}")
        if (section_name, toml_key) in _DURATION_FIELDS:
            if isinstance(value, str):
                try:
                    value = parse_duration(value)
                except ValueError as error:
                    raise ConfigError(f"[{section_name}] {toml_key}: {error}") from error
            elif isinstance(value, int) and not isinstance(value, bool):
                pass  # raw seconds accepted
            else:
                raise ConfigError(f"[{section_name}] {toml_key}: expected duration string")
        else:
            expected = type(getattr(target, toml_key))
            if expected is float and isinstance(value, int) and not isinstance(value, bool):
                value = float(value)
            if not isinstance(value, expected) or isinstance(value, bool) is not (expected is bool):
                raise ConfigError(
                    f"[{section_name}] {toml_key}: expected {expected.__name__}, got {type(value).__name__}"
                )
        setattr(target, toml_key, value)


def _require_choice(section: str, key: str, value: str,
                    valid: tuple[str, ...]) -> None:
    """Reject an option whose value isn't one of a fixed set, naming them all
    — every closed-set option in this file gets the same sentence."""
    if value not in valid:
        raise ConfigError(
            f"[{section}] {key} must be one of {', '.join(valid)}")


def _validate(config: AppConfig) -> None:
    automation = config.automation
    if automation.check_interval <= 0:
        raise ConfigError("[automation] check_interval must be positive")
    if automation.sit_duration <= 0 or automation.stand_duration <= 0:
        raise ConfigError("[automation] sit_duration and stand_duration must be positive")
    for name in ("sit_variation", "stand_variation", "idle_threshold",
                 "recent_input_threshold", "sync_interval"):
        if getattr(automation, name) < 0:
            raise ConfigError(f"[automation] {name} must not be negative")
    _require_choice("automation", "external_move_policy",
                    automation.external_move_policy, VALID_EXTERNAL_POLICIES)
    _require_choice("automation", "interruption_policy",
                    automation.interruption_policy, VALID_INTERRUPTION_POLICIES)
    _require_choice("desk", "connection",
                    config.desk.connection, VALID_CONNECTION_MODES)
    for key in ("tray_left_click", "tray_middle_click"):
        _require_choice("ui", key, getattr(config.ui, key), VALID_TRAY_ACTIONS)
    _require_choice("ui", "tray_repeat_move",
                    config.ui.tray_repeat_move, VALID_TRAY_REPEAT)
    _require_choice("ui", "units", config.ui.units, VALID_UNITS)
    _require_choice("ui", "close_action",
                    config.ui.close_action, VALID_CLOSE_ACTIONS)
    for day in config.schedule.days:
        if day not in VALID_DAYS:
            raise ConfigError(f"[schedule] unknown day {day!r}")
    for label in ("start", "end"):
        _parse_hhmm(getattr(config.schedule, label), f"[schedule] {label}")
    if not (0 < config.advanced.movement_tolerance < 0.5):
        raise ConfigError("[advanced] movement_tolerance out of range")
    for name, height in config.presets.items():
        # Still reachable via save_config, which validates an in-memory config
        # that nothing forced through the loader's coercion.
        _preset_height(name, height)
        if not (MIN_HEIGHT - 0.01 <= float(height) <= MAX_HEIGHT + 0.01):
            raise ConfigError(
                f"[presets] {name}: {height} m outside desk range "
                f"{MIN_HEIGHT}-{MAX_HEIGHT} m"
            )


def _preset_height(name: str, value: object) -> float:
    """A preset height as a float, or ConfigError naming what was found."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            f"[presets] {name}: expected a height in meters, got "
            f"{type(value).__name__}")
    return float(value)


def _parse_hhmm(text: str, label: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = text.split(":")
        hour, minute = int(hour_text), int(minute_text)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return hour, minute
    except (ValueError, AttributeError):
        raise ConfigError(f"{label}: expected HH:MM, got {text!r}") from None


def load_config(path: Path | None = None) -> AppConfig:
    """Load config from ``path`` (default location if None). A missing file
    yields pure defaults; a malformed file raises ConfigError."""
    path = path or DEFAULT_CONFIG_PATH
    config = AppConfig()
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return config
    try:
        data = tomllib.loads(raw.decode())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise ConfigError(f"{path}: {error}") from error

    for section_name in ("desk", "automation", "schedule", "notifications",
                         "advanced", "ui"):
        section_data = data.pop(section_name, None)
        if section_data is None:
            continue
        if not isinstance(section_data, dict):
            raise ConfigError(f"[{section_name}] must be a table")
        if section_name == "advanced":
            # Obsolete: the sit/stand boundary is now the preset midpoint, so an
            # existing [advanced] table may still carry this key — drop it rather
            # than failing the unknown-option check.
            section_data.pop("sitting_height_threshold", None)
        if section_name == "automation":
            # Back-compat: interruption handling was a bool before it became a
            # 3-way policy, and that bool was itself renamed once:
            #   retry_on_interruption -> return_to_start_on_interruption
            #                         -> interruption_policy
            # True meant "return to the start height" (now "undo"), False meant
            # "leave it where it stopped" (now "leave"). The newer key wins, and
            # an explicit interruption_policy wins over both.
            legacy = section_data.pop("return_to_start_on_interruption", None)
            if legacy is None:
                legacy = section_data.pop("retry_on_interruption", None)
            else:
                section_data.pop("retry_on_interruption", None)
            if "interruption_policy" not in section_data and isinstance(legacy, bool):
                section_data["interruption_policy"] = "undo" if legacy else "leave"
        if section_name == "ui":
            # Removed option: tray_double_click. StatusNotifierItem trays don't
            # deliver double-clicks, so the action was dropped — ignore the key
            # from a config written by an older version rather than failing the
            # unknown-option check.
            section_data.pop("tray_double_click", None)
        _apply_section(getattr(config, section_name), section_name, section_data)

    presets = data.pop("presets", None)
    if presets is not None:
        if not isinstance(presets, dict):
            raise ConfigError("[presets] must be a table of name = height")
        # Coerce here rather than leaving it to _validate: a bare float() would
        # raise ValueError/TypeError straight past this module's contract (and
        # past the daemon's `except ConfigError`, killing it mid-run on a hand
        # edit), which also made _validate's isinstance check unreachable.
        # `bool` is excluded explicitly because it *is* an int in Python, so
        # `sit = true` would otherwise be accepted as a 1.0 m desk height.
        config.presets = {name: _preset_height(name, h) for name, h in presets.items()}
    for name, height in FALLBACK_PRESETS.items():
        config.presets.setdefault(name, height)

    # Back-compat: the old in-app global-shortcuts portal wrote a [hotkeys]
    # table. The portal is gone, but an existing config still carries the
    # section — drop it silently rather than failing the unknown-section check.
    data.pop("hotkeys", None)

    if data:
        raise ConfigError(f"unknown config section(s): {', '.join(sorted(data))}")

    _validate(config)
    return config


def save_config(config: AppConfig, path: Path | None = None) -> None:
    """Write config to disk, preserving comments/layout of an existing file."""
    import tomlkit

    _validate(config)
    path = path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        document = tomlkit.parse(path.read_text())
    except FileNotFoundError:
        document = tomlkit.document()

    def put(section: str, key: str, value) -> None:
        if section not in document:
            document[section] = tomlkit.table()
        document[section][key] = value

    def drop(section: str, key: str) -> None:
        """Remove a key written by an older version. All of them are ignored
        on load; dropping them here is what stops the file accumulating
        spellings that no longer mean anything."""
        table = document.get(section)
        if table is not None and key in table:
            del table[key]

    put("desk", "mac", config.desk.mac)
    put("desk", "connection", config.desk.connection)
    put("desk", "linger", format_duration_compact(config.desk.linger))

    automation = config.automation
    put("automation", "enabled", automation.enabled)
    for toml_key in ("sit_duration", "stand_duration", "sit_variation", "stand_variation",
                "check_interval", "idle_threshold", "recent_input_threshold",
                "sync_interval"):
        put("automation", toml_key, format_duration_compact(getattr(automation, toml_key)))
    put("automation", "interruption_policy", automation.interruption_policy)
    put("automation", "external_move_policy", automation.external_move_policy)
    # The superseded boolean spellings (both folded into interruption_policy
    # on load).
    drop("automation", "retry_on_interruption")
    drop("automation", "return_to_start_on_interruption")

    put("schedule", "enabled", config.schedule.enabled)
    put("schedule", "days", config.schedule.days)
    put("schedule", "start", config.schedule.start)
    put("schedule", "end", config.schedule.end)

    put("notifications", "enabled", config.notifications.enabled)
    put("notifications", "lead_time", format_duration_compact(config.notifications.lead_time))
    put("notifications", "problems", config.notifications.problems)

    put("advanced", "movement_tolerance", config.advanced.movement_tolerance)
    # The obsolete classification threshold (the boundary is now the preset
    # midpoint).
    drop("advanced", "sitting_height_threshold")

    for toml_key in ("language", "units", "tray_left_click", "tray_middle_click",
                "tray_repeat_move", "close_action", "minimize_to_tray",
                "start_minimized", "run_at_login"):
        put("ui", toml_key, getattr(config.ui, toml_key))
    # The removed double-click action (SNI trays never delivered it).
    drop("ui", "tray_double_click")

    # The in-app global-shortcuts portal is gone; drop the obsolete [hotkeys]
    # table from a config written by an older version.
    if "hotkeys" in document:
        del document["hotkeys"]

    if "presets" not in document:
        document["presets"] = tomlkit.table()
    for name in list(document["presets"].keys()):
        if name not in config.presets:
            del document["presets"][name]
    for name, height in config.presets.items():
        document["presets"][name] = round(float(height), 4)

    tmp_path = path.with_suffix(".toml.tmp")
    tmp_path.write_text(tomlkit.dumps(document))
    tmp_path.replace(path)
