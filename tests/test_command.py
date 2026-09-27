"""Shared entry routing without launching the installed GUI or daemon."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from idasen_companion import command


@pytest.mark.parametrize("arguments", [[], ["--window"]])
def test_gui_routes_preserve_arguments(monkeypatch, arguments):
    seen = []
    gui = ModuleType("idasen_companion.gui.main")
    gui.main = lambda argv: seen.append(argv) or 17
    monkeypatch.setitem(sys.modules, "idasen_companion.gui.main", gui)
    monkeypatch.setattr(command.importlib.util, "find_spec", lambda _name: object())

    assert command.main(arguments) == 17
    assert seen == [arguments]


@pytest.mark.parametrize("arguments", [[], ["--window"]])
def test_headless_gui_routes_return_usage_error(monkeypatch, capsys, arguments):
    monkeypatch.setattr(command.importlib.util, "find_spec", lambda _name: None)
    assert command.main(arguments) == 2
    assert "subcommand is required" in capsys.readouterr().err


@pytest.mark.parametrize("arguments", [[], ["--window"]])
def test_headless_routes_error_when_system_qt_is_present(monkeypatch, capsys,
                                                          arguments):
    monkeypatch.setattr(
        command.importlib.util, "find_spec",
        lambda name: None if name == "idasen_companion.gui" else object(),
    )
    assert command.main(arguments) == 2
    assert "subcommand is required" in capsys.readouterr().err


@pytest.mark.parametrize("arguments", [
    ["sit"], ["--config", "/tmp/example", "stand"], ["--help"],
    ["--version"], ["--sitt"], ["--window", "sit"],
])
def test_other_routes_never_load_gui(monkeypatch, arguments):
    seen = []
    monkeypatch.setattr(command.cli, "main", lambda argv: seen.append(argv) or 19)
    assert command.main(arguments) == 19
    assert seen == [arguments]


def test_help_names_shared_command_and_repeat_setting(capsys):
    with pytest.raises(SystemExit) as raised:
        command.main(["--help"])
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "usage: idasen-companion" in output
    assert "tray_repeat_move" in output
    assert "--window" in output
