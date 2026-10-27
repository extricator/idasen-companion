# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from idasen_companion.core.config import (
    AppConfig, ConfigError, load_config, save_config,
)
from idasen_companion.core.migration import import_idasen_cli_config

SAMPLE_YAML = """\
mac_address: E1:B2:C3:D4:E5:F6
positions:
  focus: 1.0403
  sit: 0.62
  stand: 1.1438000000000001
"""


def test_import_full_config(tmp_path):
    p = tmp_path / "idasen.yaml"
    p.write_text(SAMPLE_YAML)
    imported = import_idasen_cli_config(p)
    assert imported is not None
    assert imported.mac == "E1:B2:C3:D4:E5:F6"
    # All positions imported, including custom ones; heights rounded sanely.
    assert imported.presets == {"focus": 1.0403, "sit": 0.62, "stand": 1.1438}


def test_missing_file_returns_none(tmp_path):
    assert import_idasen_cli_config(tmp_path / "nope.yaml") is None


def test_malformed_yaml_returns_none(tmp_path):
    p = tmp_path / "idasen.yaml"
    p.write_text("just a string")
    assert import_idasen_cli_config(p) is None


def test_mac_only(tmp_path):
    p = tmp_path / "idasen.yaml"
    p.write_text("mac_address: AA:BB:CC:DD:EE:FF\n")
    imported = import_idasen_cli_config(p)
    assert imported.mac == "AA:BB:CC:DD:EE:FF"
    assert imported.presets == {}


def test_out_of_range_positions_are_skipped_not_imported(tmp_path):
    # The idasen CLI does not bound its saved positions. Importing one outside
    # our desk range made save_config reject the whole bootstrap config — and
    # since the file is written only on success, every later start repeated it.
    p = tmp_path / "idasen.yaml"
    p.write_text("mac_address: AA:BB:CC:DD:EE:FF\n"
                 "positions:\n"
                 "  sit: 0.70\n"
                 "  perch: 1.35\n"
                 "  floor: 0.10\n")
    imported = import_idasen_cli_config(p)
    assert imported.presets == {"sit": 0.70}
    assert sorted(imported.skipped) == ["floor", "perch"]


def test_a_skipped_position_does_not_block_the_bootstrap_save(tmp_path):
    # The end-to-end property that matters: whatever the CLI config holds, the
    # config we build from it must be writable.
    p = tmp_path / "idasen.yaml"
    p.write_text("mac_address: AA:BB:CC:DD:EE:FF\n"
                 "positions:\n  perch: 1.35\n  sit: 0.70\n")
    imported = import_idasen_cli_config(p)

    cfg = AppConfig()
    cfg.desk.mac = imported.mac
    cfg.presets.update(imported.presets)
    out = tmp_path / "config.toml"
    save_config(cfg, out)  # must not raise

    assert load_config(out).presets["sit"] == 0.70


def test_bootstrap_falls_back_to_defaults_when_the_import_cannot_be_saved(
        tmp_path, monkeypatch):
    """Belt and braces for the crash loop: even if something *else* makes the
    bootstrap config unwritable, the daemon must come up rather than exit 1
    before writing the file — which is what made the failure repeat forever.
    """
    from unittest.mock import MagicMock

    import idasen_companion.daemon.config_file as config_file_mod
    from idasen_companion.core.migration import ImportedSettings

    monkeypatch.setattr(config_file_mod, "import_idasen_cli_config",
                        lambda: ImportedSettings(mac="AA:BB:CC:DD:EE:FF",
                                                 presets={"sit": 9.0}))

    activity_log = MagicMock()
    store = config_file_mod.ConfigFileStore(
        tmp_path / "config.toml", activity_log)
    cfg = store.load_or_bootstrap()  # must not raise

    assert cfg.presets["sit"] != 9.0
    assert not store.path.exists()
    levels = [c.args[0] for c in activity_log.diag.call_args_list]
    assert "error" in levels


def test_non_numeric_positions_are_ignored(tmp_path):
    p = tmp_path / "idasen.yaml"
    p.write_text("mac_address: AA:BB:CC:DD:EE:FF\n"
                 "positions:\n"
                 "  sit: 0.70\n"
                 "  bad: hello\n"
                 "  worse: true\n")   # bool is an int in Python
    imported = import_idasen_cli_config(p)
    assert imported.presets == {"sit": 0.70}
    assert imported.skipped == []  # wrong type isn't "out of range"


def test_bootstrap_without_an_import_keeps_defaults_and_watches_first_appearance(
        tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    from idasen_companion.daemon import config_file as config_file_mod

    monkeypatch.setattr(config_file_mod, "import_idasen_cli_config", lambda: None)
    store = config_file_mod.ConfigFileStore(tmp_path / "config.toml", MagicMock())

    assert store.load_or_bootstrap() == AppConfig()
    assert not store.path.exists()
    assert not store.poll_changed()
    save_config(AppConfig(), store.path)
    assert store.poll_changed()
    assert not store.poll_changed()


def test_bootstrap_import_saves_valid_positions_and_consumes_its_own_revision(
        tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    from idasen_companion.core.migration import ImportedSettings
    from idasen_companion.daemon import config_file as config_file_mod

    monkeypatch.setattr(config_file_mod, "import_idasen_cli_config", lambda:
                        ImportedSettings(mac="AA:BB:CC:DD:EE:FF",
                                         presets={"perch": 0.95},
                                         skipped=["ceiling"]))
    activity_log = MagicMock()
    store = config_file_mod.ConfigFileStore(tmp_path / "config.toml", activity_log)

    config = store.load_or_bootstrap()

    assert load_config(store.path) == config
    assert config.desk.mac == "AA:BB:CC:DD:EE:FF"
    assert config.presets["perch"] == 0.95
    assert not store.poll_changed()
    assert activity_log.emit.call_count == 1
    assert activity_log.diag.call_args.args[0] == "warning"
    assert "ceiling" in activity_log.diag.call_args.args[1]


def test_an_existing_config_does_not_attempt_bootstrap_import(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    from idasen_companion.daemon import config_file as config_file_mod

    importer = MagicMock(side_effect=AssertionError("existing config was imported"))
    monkeypatch.setattr(config_file_mod, "import_idasen_cli_config", importer)
    store = config_file_mod.ConfigFileStore(tmp_path / "config.toml", MagicMock())
    save_config(AppConfig(), store.path)

    assert store.load_or_bootstrap() == AppConfig()
    importer.assert_not_called()
    assert not store.poll_changed()
