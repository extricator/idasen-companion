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
import asyncio
from unittest.mock import MagicMock

import pytest
from dbus_fast import DBusError

from idasen_companion.core import logmsg
from idasen_companion.core.config import AppConfig, load_config, save_config
from idasen_companion.daemon.main import Daemon

PRESETS = {"sit": 0.62, "perch": 0.95, "stand": 1.14}


# ----- the daemon: where the atomicity actually lives -----


@pytest.fixture
def daemon(tmp_path):
    """A Daemon with just the collaborators the preset writers touch.

    ``config_path`` is real and so is ``save_config``: the point of these is
    that the rename reaches disk in one write, which a mocked writer could not
    show.
    """
    d = Daemon.__new__(Daemon)
    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here
    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.activity_log = MagicMock()
    d.config = AppConfig()
    d.config.presets = dict(PRESETS)
    d.config_path = tmp_path / "config.toml"
    save_config(d.config, d.config_path)
    # The writers now re-check the file before mutating, so a hand edit made
    # in the last check_interval isn't clobbered. Seed the mtime the way the
    # daemon would have after writing this file itself.
    d._config_mtime = d.config_path.stat().st_mtime
    d._note_config_mtime = MagicMock()
    d._ifaces = {"presets": MagicMock(), "automation": MagicMock()}
    # Reached only when the re-check finds the file changed under us, which is
    # the point of test_saving_a_preset_does_not_revert_a_concurrent_hand_edit.
    d.mock_mode = True
    d.machine = MagicMock(unconfigured=False)
    return d


def on_disk(daemon) -> dict:
    return load_config(daemon.config_path).presets


def test_a_rename_reaches_disk(daemon):
    daemon.rename_preset("perch", "lean")
    assert daemon.config.presets["lean"] == 0.95
    assert "perch" not in daemon.config.presets
    assert on_disk(daemon) == {"sit": 0.62, "lean": 0.95, "stand": 1.14}


def test_it_is_one_write_and_one_announcement(daemon):
    daemon.rename_preset("perch", "lean")
    # The whole point: a client doing Save-then-Delete produced two of each,
    # with a window in between where both names existed.
    assert daemon._ifaces["presets"].PresetsChanged.call_count == 1
    assert daemon._note_config_mtime.call_count == 1


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
    text = daemon.config_path.read_text()
    edited = re.sub(r'idle_threshold = "[^"]*"', 'idle_threshold = "7m"', text)
    assert edited != text, "fixture config has no idle_threshold to edit"
    daemon.config_path.write_text(edited)
    os.utime(daemon.config_path, (daemon._config_mtime + 10,) * 2)

    daemon.save_preset("lean", 0.95)

    reloaded = load_config(daemon.config_path)
    assert reloaded.automation.idle_threshold == 7 * 60, "hand edit was reverted"
    assert reloaded.presets["lean"] == 0.95, "the preset never reached disk"


def test_a_failed_write_leaves_the_presets_as_they_were(daemon, monkeypatch):
    """Mutating before writing left the daemon serving presets that are not on
    disk when the write failed, with no PresetsChanged and no log line."""
    import idasen_companion.daemon.main as main_mod
    before = dict(daemon.config.presets)

    def boom(*_a, **_kw):
        raise OSError("no space left on device")

    monkeypatch.setattr(main_mod, "save_config", boom)
    with pytest.raises(DBusError):
        daemon.save_preset("lean", 0.95)

    assert daemon.config.presets == before
    daemon._ifaces["presets"].PresetsChanged.assert_not_called()


# ----- the page -----

pytest.importorskip("PySide6")

# Forced, not defaulted — see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLineEdit, QMessageBox,
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


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


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
