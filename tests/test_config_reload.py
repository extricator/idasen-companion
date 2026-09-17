"""Rule 2 from docs/LOGGING.md: the activity channel records changes, not
requests.

The GUI nudges the daemon on every Save whether or not the file differs, so an
unconditional "Configuration reloaded." filled the Activity Log with an event
that told the user nothing about their desk — 163 identical lines in one
morning, from a test harness that wasn't even pointed at this config.

The same question decides whether the cycle target is re-rolled: it is a
random draw from the configured durations, so recomputing it on a no-op Save
silently re-randomizes the cycle the user is already in.
"""

import os
from pathlib import Path
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from idasen_companion.core.config import load_config
from idasen_companion.daemon.main import Daemon

CONFIG = """
[desk]
mac = "AA:BB:CC:DD:EE:FF"

[automation]
sit_duration = "45m"
stand_duration = "25m"
sit_variation = "10m"
stand_variation = "5m"
"""


@pytest.fixture
def daemon(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG)
    d = Daemon.__new__(Daemon)
    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.config_path = path
    d.mock_mode = True
    d.config = load_config(path)
    d.activity_log = MagicMock()
    d.machine = MagicMock(unconfigured=False, held=False, target_duration=1500)
    d._ifaces = {"automation": MagicMock()}
    d._config_mtime = None
    return d


def _emitted_ids(d):
    return [call.args[0].id for call in d.activity_log.emit.call_args_list]


def test_a_reload_that_changed_nothing_writes_no_activity_line(daemon):
    daemon.reload_config()
    assert "config.reloaded" not in _emitted_ids(daemon)


def test_a_no_op_reload_is_still_visible_to_a_developer(daemon):
    """It did happen, and someone chasing "did my config reach the daemon?"
    wants it — it just isn't activity."""
    daemon.reload_config()
    # Match the message, not just the level: "debug" alone passed on any
    # unrelated debug line the reload happened to emit.
    debug_lines = [call.args[1]
                   for call in daemon.activity_log.diag.call_args_list
                   if call.args[0] == "debug"]
    assert any("config" in line.lower() for line in debug_lines), debug_lines


def test_a_real_change_does_write_an_activity_line(daemon):
    daemon.config_path.write_text(CONFIG.replace('"25m"', '"30m"'))
    daemon.reload_config()
    assert "config.reloaded" in _emitted_ids(daemon)


def test_an_unknown_option_loads_and_is_reported_once(daemon):
    daemon.config_path.write_text(CONFIG.replace(
        "[automation]", "[automation]\nfuture_strategy = 'gentle'"))

    daemon.reload_config()
    assert "config.unknown_option" in _emitted_ids(daemon)
    warning_calls = [call for call in daemon.activity_log.emit.call_args_list
                     if call.args[0].id == "config.unknown_option"]
    assert len(warning_calls) == 1
    assert warning_calls[0].kwargs["section"] == "automation"
    assert warning_calls[0].kwargs["key"] == "future_strategy"

    daemon.reload_config()
    warning_calls = [call for call in daemon.activity_log.emit.call_args_list
                     if call.args[0].id == "config.unknown_option"]
    assert len(warning_calls) == 1, "unchanged warning flooded a repeated reload"


def test_a_no_op_reload_does_not_re_roll_the_cycle_target(daemon):
    daemon.reload_config()
    assert daemon.machine.update_config.call_args.kwargs["reroll_target"] is False


def test_changing_a_duration_re_rolls_the_cycle_target(daemon):
    daemon.config_path.write_text(CONFIG.replace('"25m"', '"30m"'))
    daemon.reload_config()
    assert daemon.machine.update_config.call_args.kwargs["reroll_target"] is True


def test_changing_an_unrelated_setting_leaves_the_cycle_alone(daemon):
    """The target derives from the four duration fields and nothing else, so
    editing the idle threshold must not re-randomize the current cycle."""
    daemon.config_path.write_text(
        CONFIG.replace("[automation]", '[automation]\nidle_threshold = "7m"'))
    daemon.reload_config()
    assert "config.reloaded" in _emitted_ids(daemon)
    assert daemon.machine.update_config.call_args.kwargs["reroll_target"] is False


@pytest.mark.parametrize("broken", [
    '[automation]\nsit_duration = "nonsense"\n',
    # A malformed *preset* used to escape as ValueError/TypeError rather than
    # ConfigError, so it sailed past the except below and killed the daemon
    # from inside _tick -> _check_config_file. The file is hand-editable and
    # hot-reloads, so this is a plain user action taking automation down.
    "[presets]\nsit = 'tall'\n",
    "[presets]\nsit = true\n",
    "[presets]\nsit = 2026-01-01\n",
    "[presets]\nsit = 9.0\n",
    "[schedule]\nstart = '25:00'\n",
    "not toml at all [",
])
def test_a_broken_config_is_reported_and_the_old_one_kept(daemon, broken):
    before = daemon.config
    daemon.config_path.write_text(broken)
    daemon.reload_config()  # must not raise
    assert "config.reload_failed" in _emitted_ids(daemon)
    assert daemon.config is before


def test_the_target_survives_repeated_no_op_reloads(tmp_path: Path):
    """The end-to-end version of the quirk: N Saves that change nothing used to
    re-randomize the cycle N times."""
    from idasen_companion.core.machine import StateMachine
    from idasen_companion.desk.mock import MockDesk

    path = tmp_path / "config.toml"
    path.write_text(CONFIG)
    d = Daemon.__new__(Daemon)
    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.config_path = path
    d.mock_mode = True
    d.config = load_config(path)
    d.activity_log = MagicMock()
    d._ifaces = {"automation": MagicMock()}
    d._config_mtime = None
    d.machine = StateMachine(d.config, MockDesk(), now=0.0)
    d.machine.start_without_desk_read(0.0)

    target = d.machine.target_duration
    for _ in range(20):
        d.reload_config()
    assert d.machine.target_duration == target


# ----- the mtime watch that *is* hot-reload -----

async def test_a_config_appearing_after_startup_starts_being_watched(tmp_path: Path):
    """`_note_config_mtime` records None when the file does not exist, and
    `_check_config_file` used to require a non-None mtime before doing
    anything — without ever assigning one on that branch. So once None, always
    None: the daemon watched nothing for the rest of its life, silently.

    Reached on a fresh install with no idasen-CLI config to import, which is
    exactly when the user hand-writes their MAC into the file README says
    hot-reloads.
    """
    path = tmp_path / "config.toml"
    d = Daemon.__new__(Daemon)
    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.config_path = path
    d.mock_mode = True
    d.config = load_config(path)          # defaults; no file on disk
    d.activity_log = MagicMock()
    d.machine = MagicMock(unconfigured=True, held=False, target_duration=0)
    d._ifaces = {"automation": MagicMock()}
    d._start_after_setup = AsyncMock()
    d._note_config_mtime()
    assert d._config_mtime is None

    path.write_text(CONFIG)               # the user writes their MAC
    d._check_config_file()

    assert d._config_mtime is not None, "still watching nothing"
    assert d.config.desk.mac == "AA:BB:CC:DD:EE:FF", "the edit never arrived"


async def test_later_edits_are_picked_up_too(tmp_path: Path):
    path = tmp_path / "config.toml"
    d = Daemon.__new__(Daemon)
    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.config_path = path
    d.mock_mode = True
    d.config = load_config(path)
    d.activity_log = MagicMock()
    d.machine = MagicMock(unconfigured=True, held=False, target_duration=0)
    d._ifaces = {"automation": MagicMock()}
    d._start_after_setup = AsyncMock()
    d._note_config_mtime()

    path.write_text(CONFIG)
    d._check_config_file()
    first = d._config_mtime

    os.utime(path, (first + 10, first + 10))
    path.write_text(CONFIG.replace('"45m"', '"50m"'))
    os.utime(path, (first + 20, first + 20))
    d._check_config_file()

    assert d.config.automation.sit_duration == 50 * 60


def test_an_unchanged_file_is_not_reloaded_every_tick(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG)
    d = Daemon.__new__(Daemon)
    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.config_path = path
    d.mock_mode = True
    d.config = load_config(path)
    d.activity_log = MagicMock()
    d.machine = MagicMock(unconfigured=False, held=False, target_duration=1500)
    d._ifaces = {"automation": MagicMock()}
    d._note_config_mtime()

    d.reload_config = MagicMock()
    for _ in range(5):
        d._check_config_file()
    d.reload_config.assert_not_called()
