"""``[ui] clock_format`` reaching both processes, and staying out of a third.

The window and the daemon share no process state — they communicate only over
D-Bus — yet they must show the same clock. Nothing carries the answer between
them: each reads the same config file and runs the same pure resolver over its
own environment. That is the claim this module pins, on both sides, plus its
deliberate exception: the journal's own formatter is fixed at 24 hours and no
config value can reach it, because a log line is read by whoever is debugging
it rather than by whoever owns the desktop session.

The source-level check at the bottom reads the parsed tree rather than the
file's text, so a comment sitting next to the code cannot satisfy it and a
comment explaining the rule cannot break it.
"""

from __future__ import annotations

import ast
import inspect

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

# Forced, not defaulted — see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.core import presentation as english  # noqa: E402
from idasen_companion.core.locale_profile import TimeStyle  # noqa: E402
from idasen_companion.daemon.main import Daemon  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402

_TWELVE = TimeStyle.HOUR_AND_MINUTE_12
_TWENTY_FOUR = TimeStyle.HOUR_AND_MINUTE_24


class FakeClient:
    """Enough DaemonClient for AppContext: never available, so no D-Bus."""

    available = False

    def reload_config(self):  # pragma: no cover - unreachable while unavailable
        raise AssertionError("should not nudge an unavailable daemon")


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _config(clock_format: str) -> AppConfig:
    config = AppConfig()
    config.ui.clock_format = clock_format
    # Pinned rather than left at "system": "system" resolves against the host
    # environment, which would make the assertions below depend on the machine
    # running the suite rather than on the setting under test.
    config.ui.language = "en_GB"
    return config


def _window_style(qapp, tmp_path, monkeypatch, clock_format: str) -> TimeStyle:
    path = tmp_path / "config.toml"
    save_config(_config(clock_format), path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    context = AppContext(FakeClient(), tray_available=True)
    assert context.reload_config() is None
    return context.fmt.time_style


def _daemon_style(clock_format: str) -> TimeStyle:
    # __init__ opens a stats database and wires signal handlers; the method
    # under test needs none of that, and the two real call sites reach it the
    # same way — with a config and nothing else.
    return Daemon._build_formatter(  # pylint: disable=protected-access
        None, _config(clock_format)).time_style


@pytest.mark.parametrize(("clock_format", "expected"), [
    ("12", _TWELVE),
    ("24", _TWENTY_FOUR),
    ("system", _TWENTY_FOUR),  # en_GB names a 24-hour territory
])
def test_the_window_renders_the_clock_the_setting_names(
        qapp, tmp_path, monkeypatch, clock_format, expected):
    assert _window_style(qapp, tmp_path, monkeypatch, clock_format) is expected


@pytest.mark.parametrize(("clock_format", "expected"), [
    ("12", _TWELVE),
    ("24", _TWENTY_FOUR),
    ("system", _TWENTY_FOUR),
])
def test_the_daemon_renders_the_clock_the_setting_names(
        clock_format, expected):
    assert _daemon_style(clock_format) is expected


@pytest.mark.parametrize("clock_format", ["system", "12", "24"])
def test_both_processes_reach_the_same_answer(
        qapp, tmp_path, monkeypatch, clock_format):
    """The point of the whole design: no D-Bus method carries this, and none
    is needed, because both sides run one pure function over one config
    value."""
    assert (_window_style(qapp, tmp_path, monkeypatch, clock_format)
            is _daemon_style(clock_format))


@pytest.mark.parametrize("clock_format", ["system", "12", "24"])
def test_the_journal_keeps_its_stable_duration_shape(clock_format):
    """No display clock setting can alter released English journal values."""
    assert english.format_duration_human(90) == "1.5 minutes", clock_format


def test_no_config_value_can_reach_the_journals_formatter():
    """A source-level check, because a test that only asserts the *current*
    answer would still pass the day somebody wires the setting in here.

    Read from the parsed tree, never the file's text: this module's own
    explanation of the rule names the same identifiers, and a text search
    would count that explanation as a violation — or let one hide behind it.
    """
    tree = ast.parse(inspect.getsource(english))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    forbidden = {"resolve_clock_style", "ClockSetting", "AppConfig",
                 "clock_format", "config", "..config", "core.config"}
    reached = imported & forbidden
    assert not reached, (
        f"the journal's construction module imports {sorted(reached)} — the "
        f"whole point of D-14 is that no display preference can reach it")
