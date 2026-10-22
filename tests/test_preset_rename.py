# SPDX-License-Identifier: GPL-3.0-or-later
"""Renaming a preset is one operation, on the wire and on disk.

It used to be two calls — Save under the new name, then Delete the old — with
no transaction around them, so anything landing between them (a crash, a
session ending, the daemon restarting) left both names pointing at one height.
``Presets1.Rename`` replaces both: one dict mutation, one config write, one
``PresetsChanged``. There is no half-done state left to report.

The daemon half needs no Qt and runs everywhere; the GUI half is skipped where
PySide6 is missing, since the RPM lists it as a runtime ``Requires`` rather
than a ``BuildRequires`` and the spec's ``%check`` may run this suite without
it.
"""

import os
from unittest.mock import MagicMock

import pytest
from dbus_fast import DBusError

from idasen_companion.core import logmsg
from idasen_companion.core.lengths import Length
from idasen_companion.core.config import AppConfig, ConfigError, load_config, save_config
from daemon_helpers import make_daemon_shell
from idasen_companion.daemon.config_file import ConfigFileStore

PRESETS = {"sit": 0.62, "perch": 0.95, "stand": 1.14}


# ----- the daemon: where the atomicity actually lives -----


@pytest.fixture
def daemon(tmp_path):
    """A Daemon with just the collaborators the preset writers touch.

    The configuration path is real and so is ``save_config``: the point of these is
    that the rename reaches disk in one write, which a mocked writer could not
    show.
    """
    d = make_daemon_shell()
    d.activity_log = MagicMock()
    d.config = AppConfig()
    d.config.presets = dict(PRESETS)
    d.config_file = ConfigFileStore(tmp_path / "config.toml", d.activity_log)
    d.config_file.save(d.config)
    d._ifaces = {"presets": MagicMock(), "automation": MagicMock()}
    # Reached only when the re-check finds the file changed under us, which is
    # the point of test_saving_a_preset_does_not_revert_a_concurrent_hand_edit.
    d.mock_mode = True
    d.machine = MagicMock(unconfigured=False)
    return d


def on_disk(daemon) -> dict:
    return load_config(daemon.config_file.path).presets


def test_a_rename_reaches_disk(daemon):
    daemon.rename_preset("perch", "lean")
    assert daemon.config.presets["lean"] == 0.95
    assert "perch" not in daemon.config.presets
    assert on_disk(daemon) == {"sit": 0.62, "lean": 0.95, "stand": 1.14}


def test_it_is_one_write_and_one_announcement(daemon, monkeypatch):
    from idasen_companion.daemon import config_file as config_file_mod
    writer = MagicMock(wraps=config_file_mod.save_config)
    monkeypatch.setattr(config_file_mod, "save_config", writer)
    daemon.rename_preset("perch", "lean")
    # The whole point: a client doing Save-then-Delete produced two of each,
    # with a window in between where both names existed.
    assert daemon._ifaces["presets"].PresetsChanged.call_count == 1
    writer.assert_called_once_with(daemon.config, daemon.config_file.path)
    assert not daemon.config_file.poll_changed()


def test_the_key_keeps_its_place_in_what_list_reports(daemon):
    daemon.rename_preset("perch", "lean")
    assert list(daemon.config.presets) == ["sit", "lean", "stand"]
    # The file is a different matter: tomlkit has no rename, so save_config
    # drops the old key and appends the new one. Recorded rather than fought —
    # nothing reads preset order off disk, and the GUI sorts its own list.
    assert list(on_disk(daemon)) == ["sit", "stand", "lean"]


def test_it_logs_one_line(daemon):
    daemon.rename_preset("perch", "lean")
    daemon.activity_log.emit.assert_called_once_with(
        logmsg.PRESET_RENAMED, old="perch", new="lean")


@pytest.mark.parametrize("old,new", [
    ("sit", "seat"),        # protected
    ("stand", "up"),        # protected
    ("nothing", "lean"),    # no such preset
    ("perch", "stand"),     # would collide
    ("perch", "   "),       # no name at all
])
def test_a_refused_rename_changes_nothing(daemon, old, new):
    with pytest.raises(DBusError):
        daemon.rename_preset(old, new)
    assert daemon.config.presets == PRESETS
    assert on_disk(daemon) == PRESETS
    assert not daemon._ifaces["presets"].PresetsChanged.called


def test_renaming_to_the_same_name_does_nothing(daemon):
    daemon.rename_preset("perch", "perch")
    assert on_disk(daemon) == PRESETS
    assert not daemon._ifaces["presets"].PresetsChanged.called
    assert not daemon.activity_log.emit.called


def test_surrounding_whitespace_is_trimmed(daemon):
    daemon.rename_preset("perch", "  lean  ")
    assert "lean" in daemon.config.presets


# ----- a daemon write must not clobber a hand edit -----

def test_saving_a_preset_does_not_revert_a_concurrent_hand_edit(daemon):
    """`self.config` lags the file by up to one check_interval, and
    `save_config` rewrites *every* key from memory. So editing config.toml and
    then capturing a preset from the GUI within the same minute silently
    reverted the edit — and nothing reloaded it afterwards, because the daemon
    stamps its own mtime after writing.
    """
    import re
    text = daemon.config_file.path.read_text()
    edited = re.sub(r'idle_threshold = "[^"]*"', 'idle_threshold = "7m"', text)
    assert edited != text, "fixture config has no idle_threshold to edit"
    daemon.config_file.path.write_text(edited)
    os.utime(daemon.config_file.path, (daemon.config_file.path.stat().st_mtime + 10,) * 2)

    daemon.save_preset("lean", Length(0.95))

    reloaded = load_config(daemon.config_file.path)
    assert reloaded.automation.idle_threshold == 7 * 60, "hand edit was reverted"
    assert reloaded.presets["lean"] == 0.95, "the preset never reached disk"


@pytest.mark.parametrize("operation", ["save", "rename", "delete"])
@pytest.mark.parametrize("error", [ConfigError("invalid"), OSError("disk full")])
def test_a_failed_write_leaves_the_presets_as_they_were(daemon, monkeypatch, operation, error):
    """Mutating before writing left the daemon serving presets that are not on
    disk when the write failed, with no PresetsChanged and no log line."""
    import idasen_companion.daemon.config_file as config_file_mod
    before = dict(daemon.config.presets)

    def boom(*_a, **_kw):
        raise error

    monkeypatch.setattr(config_file_mod, "save_config", boom)
    with pytest.raises(DBusError) as raised:
        if operation == "save":
            daemon.save_preset("lean", Length(0.95))
        elif operation == "rename":
            daemon.rename_preset("perch", "lean")
        else:
            daemon.delete_preset("perch")

    assert raised.value.type.endswith(".Error.ConfigWriteFailed")
    assert daemon.config.presets == before
    assert on_disk(daemon) == before
    daemon._ifaces["presets"].PresetsChanged.assert_not_called()
    daemon.activity_log.emit.assert_not_called()
    assert not daemon.config_file.poll_changed()


def test_rename_uses_the_latest_on_disk_preset_height(daemon):
    edited = daemon.config_file.load()
    edited.presets["perch"] = 0.99
    edited.automation.idle_threshold = 7 * 60
    first_mtime = daemon.config_file.path.stat().st_mtime
    save_config(edited, daemon.config_file.path)
    os.utime(daemon.config_file.path, (first_mtime + 10,) * 2)

    daemon.rename_preset("perch", "lean")

    saved = daemon.config_file.load()
    assert saved.presets["lean"] == 0.99
    assert "perch" not in saved.presets
    assert saved.automation.idle_threshold == 7 * 60
    assert not daemon.config_file.poll_changed()


@pytest.mark.parametrize("operation", ["save", "rename", "delete"])
def test_each_preset_write_consumes_its_own_revision(daemon, operation):
    if operation == "save":
        daemon.save_preset("lean", Length(0.95))
    elif operation == "rename":
        daemon.rename_preset("perch", "lean")
    else:
        daemon.delete_preset("perch")

    assert not daemon.config_file.poll_changed()


# ----- the page -----

pytest.importorskip("PySide6")

# Forced, not defaulted — see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QLineEdit, QMessageBox,
)

from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402
from idasen_companion.gui.pages import presets as presets_mod  # noqa: E402
from idasen_companion.gui.pages.presets import PresetsPage  # noqa: E402


class FakeClient(QObject):
    """The signals PresetsPage subscribes to, plus the one rename call."""

    presetsChanged = Signal(dict)
    heightChanged = Signal(float)
    connectedChanged = Signal(bool)
    availableChanged = Signal(bool)

    available = True

    def __init__(self, rename=(True, "")):
        super().__init__()
        self._rename = rename
        self.calls: list[tuple] = []

    def rename_preset_sync(self, old, new):
        self.calls.append(("rename", old, new))
        return self._rename

    def save_preset(self, name, height):  # pragma: no cover - not the rename path
        raise AssertionError("a rename is a Rename, not a Save plus a Delete")

    def delete_preset(self, name):  # pragma: no cover - as above
        raise AssertionError("a rename is a Rename, not a Save plus a Delete")


@pytest.fixture
def warnings(monkeypatch):
    """Every QMessageBox the page raises, as (kind, text)."""
    seen = []
    for kind in ("warning", "information"):
        monkeypatch.setattr(
            presets_mod.QMessageBox, kind,
            staticmethod(lambda *a, _k=kind: seen.append((_k, a[2]))
                         or QMessageBox.StandardButton.Ok))
    return seen


def make_page(qapp, tmp_path, monkeypatch, client):
    path = tmp_path / "gui-config.toml"
    save_config(AppConfig(), path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", path)
    page = PresetsPage(AppContext(client, tray_available=True))
    client.presetsChanged.emit(PRESETS)
    return page


def rename(page, old, new):
    edit = QLineEdit(new)
    page._rename_preset(old, edit)
    return edit


def test_the_page_makes_a_single_call(qapp, tmp_path, monkeypatch, warnings):
    client = FakeClient()
    page = make_page(qapp, tmp_path, monkeypatch, client)
    edit = rename(page, "perch", "lean")
    assert client.calls == [("rename", "perch", "lean")]
    assert edit.text() == "lean"
    assert warnings == []


def test_a_refusal_puts_the_field_back(qapp, tmp_path, monkeypatch, warnings):
    client = FakeClient(rename=(False, "a preset named 'stand' already exists"))
    page = make_page(qapp, tmp_path, monkeypatch, client)
    edit = rename(page, "perch", "lean")
    assert edit.text() == "perch", "the field goes back to the name that exists"
    assert len(warnings) == 1
    kind, text = warnings[0]
    assert kind == "warning"
    assert "already exists" in text


def test_a_rename_onto_a_known_name_never_reaches_the_daemon(
        qapp, tmp_path, monkeypatch, warnings):
    # The daemon refuses this too; the page just answers faster and more
    # kindly, since it already knows the preset list.
    client = FakeClient()
    page = make_page(qapp, tmp_path, monkeypatch, client)
    edit = rename(page, "perch", "sit")
    assert client.calls == []
    assert edit.text() == "perch"
    assert [kind for kind, _ in warnings] == ["information"]


def test_a_dead_daemon_discards_the_rename(qapp, tmp_path, monkeypatch, warnings):
    client = FakeClient()
    client.available = False
    page = make_page(qapp, tmp_path, monkeypatch, client)
    edit = rename(page, "perch", "lean")
    assert client.calls == []
    assert edit.text() == "perch"
